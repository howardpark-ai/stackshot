"""Scenario test for the start's roles.json step (web/server.py `_start_background`): the slow read of roles.json and projects.json (`sala sessions --json`, over ssh when the agents live on another box) runs
beside the migration, hand-off and wake passes instead of before them, and is waited for before the runner starts.

Fixture data, no network, no real sala, no server socket. `_roles_sync_safe` is replaced by a function that takes a second; the passes after it note whether it was still running when they ran.

  1  overlap     the first pass after the roles step (the migrations) runs while the roles step is still running: the start does not wait for it there
  2  before_run  when the runner starts, the roles step has ended (its result is on disk before the runner, the publish timer and the first request), and the start returns normally
  3  total       the whole start takes less than the passes and the roles step added together (the step's second is spent beside the passes, not before them)
  4  failure     a roles step that raises does not end the start (the real `_roles_sync_safe` catches its own errors; the thread reports one it did not and goes on)
  5  order       the project-id stamp still runs before the roles step, and the roles step starts before the migrations

    tests/run-suite start_roles_overlap        → exit 0 / 1"""
import json, os, pathlib, re, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="startroles-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for k in ("STACKSHOT_URL", "STACKSHOT_READ_ONLY"): os.environ.pop(k, None)
for d in ("store/a", "fleet/a", "state", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.web import server

SLOW = 1.0          # s: what the roles step takes
PASS = 0.2          # s: what each pass after it takes (five of them are held, so the passes together take about a second)
events: list = []   # (name, seconds since the start began)
state = {"roles": "idle", "t0": 0.0, "raise": False}
def now(): return round(time.monotonic() - state["t0"], 2)

def fake_roles():
    events.append(("roles begin", now())); state["roles"] = "running"
    time.sleep(SLOW)
    if state["raise"]:
        state["roles"] = "failed"; events.append(("roles failed", now())); raise RuntimeError("sala unreachable")
    state["roles"] = "done"; events.append(("roles end", now()))

class Stop(Exception): pass

def make_pass(name, result=False):
    def f(*a, **k):
        events.append((name, now(), state["roles"])); time.sleep(PASS); return result
    return f

def patch_start():
    """Everything the start does that is not under test is a note and a short wait; the runner's start ends the run, as a start that went on would open threads."""
    saved = {}
    def put(obj, attr, val):
        saved[(obj, attr)] = getattr(obj, attr); setattr(obj, attr, val)
    put(server, "_roles_sync_safe", fake_roles)
    put(server._wc, "record", lambda *_a, **_k: "")
    put(server._prj, "stamp_registry", make_pass("stamp"))
    put(server._stallsvc, "stall_pause_reload", lambda: None); put(server._stallsvc, "stall_pause_check", lambda: None)
    put(server._wait_fixes, "_wait_alias_check", lambda: None); put(server._gates, "post_wake_alias_check", lambda: None)
    for n in ("migrate_holds", "migrate_needs", "_session_ids_pass", "migrate_owner_mover", "_retire_rank_pass", "_close_marks_pass", "_nested_steps_pass"):
        put(server._migrations, n, make_pass(n))
    put(server._migrations, "_mover_backfill_pass", make_pass("_mover_backfill_pass", []))
    put(server._handoff, "handoff_repair_pass", make_pass("handoff_repair_pass"))
    put(server._wakes, "wake_pass", make_pass("wake_pass"))
    put(server._stamp_svc, "_phase_tick", make_pass("_phase_tick"))
    def record_start():
        events.append(("runner start", now(), state["roles"])); raise Stop()
    put(server._runner, "record_server_start", record_start)
    return saved

def unpatch(saved):
    for (obj, attr), v in saved.items(): setattr(obj, attr, v)

def run_start(raises=False):
    events.clear(); state.update(roles="idle", raise_=None); state["raise"] = raises
    saved = patch_start(); state["t0"] = time.monotonic(); stopped = False
    try:
        server._start_background()
    except Stop:
        stopped = True
    finally:
        unpatch(saved)
    return stopped, time.monotonic() - state["t0"]

def at(name): return next((e for e in events if e[0] == name), None)

# ---- 1-3. a slow roles step runs beside the passes
stopped, took = run_start()
check("(setup) the start ran its passes and reached the runner", stopped and at("runner start") is not None and at("wake_pass") is not None, events)
m = at("migrate_holds")
check("1: the first migration runs while the roles step is still running", m is not None and m[2] == "running", m)
check("1: …and so does the wake pass (the passes take about a second and the step a second: they are not queued behind it)", at("wake_pass") is not None and at("wake_pass")[2] in ("running", "done"), at("wake_pass"))
r = at("runner start")
check("2: when the runner starts, the roles step has ended", r is not None and r[2] == "done" and at("roles end") is not None and at("roles end")[1] <= r[1], events)
passes = [e for e in events if len(e) == 3 and e[0] not in ("runner start",)]
serial = SLOW + PASS * len(passes)
print(f"start took {took:.2f} s (roles step {SLOW} s, {len(passes)} passes of {PASS} s: {serial:.2f} s one after the other)")
check("3: the start takes less than the roles step and the passes one after the other", took < serial - 0.5, (round(took, 2), round(serial, 2)))

# ---- 4. a roles step that raises
stopped, took = run_start(raises=True)
check("4: a roles step that raised does not end the start: the runner is still reached", stopped and at("runner start") is not None and at("roles failed") is not None, events)

# ---- 5. the order in the source
src = open(f"{STACK}/stackshot/web/server.py").read().split("def _start_background")[-1]
check("5: the project-id stamp, then the roles step's start, then the migrations, then the wait for the step, then the runner",
      src.index("_prj.stamp_registry()") < src.index("_roles_sync_safe()") < src.index("_migrations.migrate_holds()") < src.index("_roles_start.join()") < src.index("_runner.record_server_start()"))

print(f"start_roles_overlap: {len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
