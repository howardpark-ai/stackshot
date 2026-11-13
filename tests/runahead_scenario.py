"""Scenario test for tests/_runahead.py, the run-ahead the release suites use to start their scenarios a few at a time. No release.sh here: a stand-in for the scenario run that
sleeps a little and writes down when it started, in a script of the same shape as the release suites (`s = scenario(...)`, `check(...)`), run once with run-ahead on and once with
RELEASE_SUITE_PAR=1 (off).

What it proves: the same results come back in the same order with it on and off, with nothing run twice that did not have to be; scenarios that are coming start while an earlier
one runs (a plain run of one after another takes the sum of their times, this one overlaps them); and the ones that must not start early do not: after a statement that could
change what they read (a call that is not a reader), when they read a name the suite assigns first, when they continue another scenario's folder (`reuse=`); a run started on
arguments that turn out different when the suite gets there is dropped, and the call runs again with its own.

    tests/run-suite runahead        → exit 0 / 1"""
import json, os, pathlib, subprocess, sys
import _scratch
SCR = os.path.dirname(os.path.abspath(__file__))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:800]}" if got is not None else ""))

STEP = 0.5   # seconds one stand-in run takes
SCRIPT = '''
import json, sys, threading, time
sys.path.insert(0, %(scr)r)
import _runahead
T0 = time.time(); LOG = []; LOCK = threading.Lock()
def run(name, *pos, **kw):
    with LOCK: LOG.append([name, round(time.time() - T0, 2)])
    time.sleep(%(step)s)
    return {"name": name, "kw": kw}
RA = _runahead.make(run)
def scenario(name, *pos, **kw): return RA.call(name, pos, kw) if RA else run(name, *pos, **kw)
def fast(name, **kw): return scenario(name, **{**dict(base="B"), **kw})
LEVEL = 1
def inc(name): return scenario(name, level=LEVEL)
OUT = []
def check(name, cond, got=None): OUT.append([name, bool(cond)])
GOT = {}
# 1. plain calls one after another, with checks between: the ones that follow start with the first
s = scenario("a", n=1)
check("a", s["name"] == "a" and s["kw"] == {"n": 1})
s = scenario("b", n=2)
check("b", s["kw"]["n"] == 2)
s = fast("c")
check("c", s["kw"] == {"base": "B"})
s = scenario("c2", extra={"X": "1"}, files={"f": "t"})
check("c2", s["kw"]["extra"] == {"X": "1"})
# 2. a call that is not a reader stops the look-ahead: what follows starts when the suite reaches it
GOT["barrier"] = [1]
GOT["barrier"].append(2)
s = scenario("d")
check("d", s["name"] == "d")
# 3. a name assigned between the statement the suite is at and the call: the call starts when the suite gets there, and reads the new value
s = scenario("e", n=1)
N = 5
s = scenario("f", n=N)
check("f reads the value assigned before it", s["kw"]["n"] == 5)
# 4. reuse= continues another scenario's folder: never early
s1 = scenario("g")
s2 = scenario("h", reuse=s1)
check("h gets what g returned", s2["kw"]["reuse"]["name"] == "g")
# 5. arguments that turn out different when the suite gets there: the run started for the old ones is dropped, the call runs again with its own
s = scenario("x")
LEVEL = 2
s = inc("y")
check("y reads the level the suite had set", s["kw"] == {"level": 2})
# 6. a loop whose body only runs scenarios and checks does not stop the look-ahead; what follows it starts with the loop
for nm in ("l1", "l2"):
    s = scenario(nm)
    check("loop " + nm, s["name"] == nm)
s = scenario("z1")
s = scenario("z2")
check("z2", s["name"] == "z2")
print(json.dumps({"log": LOG, "out": OUT, "on": RA is not None, "total": round(time.time() - T0, 2)}))
'''

def play(par):
    d = _scratch.mkdtemp(prefix="runahead-")
    p = pathlib.Path(d) / "play.py"; p.write_text(SCRIPT % {"scr": SCR, "step": STEP})
    r = subprocess.run([sys.executable, str(p)], env={**os.environ, "RELEASE_SUITE_PAR": str(par)}, capture_output=True, text=True, timeout=120)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): return {"error": r.stdout + r.stderr}

on, off = play(4), play(1)
check("both plays ran to the end", "log" in on and "log" in off, (on.get("error"), off.get("error")))
if "log" in on and "log" in off:
    names = lambda r: [n for n, _ in r["log"]]
    at = lambda r, n: next(t for k, t in r["log"] if k == n)
    expected = ["a", "b", "c", "c2", "d", "e", "f", "g", "h", "x", "y", "l1", "l2", "z1", "z2"]
    check("run-ahead is on in the first play and off in the second", on["on"] and not off["on"], (on["on"], off["on"]))
    check("every check of the script passes with it on and with it off, the same checks in the same order", on["out"] == off["out"] and all(ok for _, ok in on["out"]) and len(on["out"]) == 11, (on["out"], off["out"]))
    check("off: every scenario ran once, in the order of the script, one after another (each starts after the one before ended)",
          names(off) == expected and all(off["log"][i + 1][1] >= off["log"][i][1] + STEP - 0.05 for i in range(len(expected) - 1)), off["log"])
    check("on: a scenario ran for every call of the script, and one more for the call whose arguments changed (y), no other run twice",
          sorted(names(on)) == sorted([*expected, "y"]) and names(on).count("y") == 2, names(on))
    check("on: the scenarios that follow the first start with it (a, b, c, c2 begin within one step of each other)", max(at(on, n) for n in ("b", "c", "c2")) < at(on, "a") + STEP, on["log"])
    check("on: after a call that is not a reader nothing starts early: d starts when the suite reaches it, after a, b, c and c2 are read", at(on, "d") >= at(on, "a") + STEP - 0.05, on["log"])
    check("on: f reads a name the suite assigns after e (N): it starts only when the suite gets to it, after e", at(on, "f") >= at(on, "e") + STEP - 0.05, on["log"])
    check("on: h, that continues g's folder (reuse=), starts after g is done", at(on, "h") >= at(on, "g") + STEP - 0.05, on["log"])
    ys = [t for k, t in on["log"] if k == "y"]
    check("on: y was started early on the level the suite had not yet changed, dropped, and run again after the suite changed it", len(ys) == 2 and ys[1] >= ys[0], ys)
    check("on: a loop of scenarios and checks does not stop the look-ahead: z1, after it, starts before the loop's second run does", at(on, "z1") < at(on, "l2"), on["log"])
    check("on: the whole script takes less than off (the runs overlap)", on["total"] < off["total"] - 2 * STEP, (on["total"], off["total"]))

# what the look-ahead may start early and what may stand between: the rules on single statements
import ast, _runahead as ra
def stmt(src): return ast.parse(src).body[0]
for src, want in (('s = scenario("a", n=1)', True), ('scenario("a")', True), ('s = fast("a", runs=json.dumps([{"id": 1}]), files=QF(["1"]))', True), ('a, b = inc("x", "y", merge="ok")', True),
                  ('s = scenario("a", reuse=s1)', False), ('s = scenario("a", lockhook=lambda d: 1)', False), ('s = scenario("a", **kw)', False), ('s = scenario("a", side="25")', False),
                  ('s = scenario("a", extra={"X": write_it()})', False), ('s = scenario("a", extra={"X": (y := 2)})', False), ('s = other("a")', False), ('s.x = scenario("a")', False)):
    check(f"candidate: {src} is {'started early' if want else 'not started early'}", ra._candidate(stmt(src)) == want)
for src, want in (('check("x", s["rc"] == 0 and len(s["gh"]) == 2)', True), ('check("x", lock_free(s), s["out"])', True), ('check("x", subprocess.run(["true"]).returncode == 0)', False),
                  ('FAST = 1', True), ('a, b = "1", "2"', True), ('x = pathlib.Path(_scratch.mkdtemp(prefix="p-"))', True), ('dirs.append(x)', True), ('x.write_text("a")', False), ('x = open(p, "a")', False),
                  ('import json', True), ('def f(): pass', True), ('s = scenario("a", reuse=s1)', True), ('GOT["a"] = 1', False), ('os.environ["A"] = "1"', False),
                  ('for n in ("a", "b"):\n    s = scenario(n)\n    check(n, s["rc"] == 0)', True), ('for n in ("a", "b"):\n    subprocess.run(["true"])', False),
                  ('if p.exists():\n    check("x", 1)', True), ('if p.exists():\n    p.unlink()', False), ('try:\n    pass\nfinally:\n    pass', False), ('with open(p) as f:\n    pass', False)):
    check(f"between: {src.splitlines()[0]} is {'inert' if want else 'a stop'}", ra._inert(stmt(src)) == want)
print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
