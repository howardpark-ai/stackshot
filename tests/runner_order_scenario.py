"""Scenario test for the order of the minute set at its one-minute pace (runner.py, server._minute_ticks). Fixture data, no live store, no network.
The real Runner runs the server's real table on a fake clock, with every tick function replaced by a recorder, and the order the recorders are called in is what is checked:

  1  the table: the events that end a wait first (watchers' pass, anchor pass, the phase sweep, event waits, done check, step proof), then the hand-off tick, the answers, the stall pass and the
     other fleet clocks, then the publish; the stall pass is behind the hand-off tick and every wait-ender
  2  the minute: driven in 20 s steps (the old pace) for ten minutes, the paced clocks run once a minute, not every step · every round that runs a paced clock runs the whole
     table in that order · the hand-off and stall clocks are a minute apart, not 20 s · a tick that raises costs the order nothing
  3  a wake event between two minutes runs the two event ticks alone, in order, and the minute's round after it still starts with them
  4  the pace is the one number: a runner built with the module's default is a minute, one built with 20 s runs three times as often (the flag off keeps the old threads at 20 s)

    tests/run-suite runner_order        -> exit 0 / 1"""
import contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, threading, time, types

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="runner-order-"); T = pathlib.Path(tmp)
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
from stackshot.core import config as _cfg
from stackshot.web import server
server._publish = lambda: None

class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s

EXPECT = ["wake_pass", "anchor_pass", "phase_sweep", "evwait_tick", "check_tick", "proof_tick", "handoff_tick", "answer_tick",
          "roles_sync_safe", "clients_tick", "pilot_fallback_tick", "stall_tick", "handback_tick", "fleet_publish"]
TEN = ["filing_tick", "dates_tick", "wake_catchup", "silence_tick", "archive_tick"]          # the ten-minute set: right after the minute set in the round that finds it due
ORDER = EXPECT + TEN
SERVER_FNS = {"wake_pass": "_minute_wake_pass", "anchor_pass": "_minute_anchor_pass", "phase_sweep": "_phase_tick", "evwait_tick": "_evwait_tick", "check_tick": "_check_tick", "proof_tick": "_proof_tick",
              "handoff_tick": "_handoff_tick", "answer_tick": "_answer_tick", "roles_sync_safe": "_roles_sync_safe", "clients_tick": "_clients_tick",
              "pilot_fallback_tick": "_pilot_fallback_tick", "stall_tick": "_stall_tick",
              "handback_tick": "_handback_tick", "fleet_publish": "_minute_fleet_publish", "filing_tick": "_filing_tick", "dates_tick": "_dates_tick", "wake_catchup": "_minute_wake_catchup", "silence_tick": "_silence_tick", "archive_tick": "_archive_tick"}
clk = Clock()
log: list[tuple[str, float]] = []
saved = {}
boom_in = {"name": None}
def install():
    for label, fn in SERVER_FNS.items():
        saved[fn] = getattr(server, fn)
        def f(label=label):
            log.append((label, clk()))
            if boom_in["name"] == label: raise RuntimeError(f"{label} broke")
            return []
        setattr(server, fn, f)
    saved["_next_wake"] = server._next_wake
    server._next_wake = lambda: None
def restore():
    for fn, orig in saved.items(): setattr(server, fn, orig)

def new_runner(pace=None):
    kw = {} if pace is None else {"pace": pace}
    return R.Runner(server._minute_ticks(), holding=lambda: False, wake_wait=server._minute_wake_wait, event=threading.Event(), clock=clk, **kw)

def rounds_of(entries):
    """The log cut into rounds: a run of ticks ends when the table starts over (a name at or before the previous one in the table's order)."""
    out, cur, last = [], [], -1
    for n, t in entries:
        i = ORDER.index(n)
        if cur and i <= last: out.append(cur); cur = []
        cur.append((n, t)); last = i
    if cur: out.append(cur)
    return out

# ---- 1. the table
names = [t.name for t in server._minute_ticks()]
check("1 table: the minute set's order, wait-enders first, then the hand-off tick, the answers, then the fleet's clocks and the publish, then the ten-minute set", names == ORDER, names)
check("1 table: every wait-ender is ahead of the hand-off tick and of the stall pass", all(names.index(w) < names.index("handoff_tick") < names.index("stall_tick")
      for w in ("wake_pass", "anchor_pass", "phase_sweep", "evwait_tick", "check_tick", "proof_tick")), names)
check("1 table: the answers are ahead of the stall pass and the publish ends the minute set, with the ten-minute set right after it", names.index("answer_tick") < names.index("stall_tick") and names[len(EXPECT) - 1] == "fleet_publish" and names[len(EXPECT):] == TEN, names)

install()
try:
    # ---- 2. ten minutes in 20 s steps
    r = new_runner()
    check("2 the runner built over the server's table has the one-minute pace", r.pace == 60.0 and R.PACE == 60.0, (r.pace, R.PACE))
    t0 = clk()
    r._pace_end = t0; r._wake_at = None; r.started = t0       # the thread is not used: the rounds are driven by hand on the fake clock
    steps = 0
    while clk() < t0 + 600:
        r.run_round()
        clk.advance(20.0); steps += 1
        if steps == 11: boom_in["name"] = "check_tick"      # a failing done check in the middle: the clocks after it still run
        if steps == 14: boom_in["name"] = None
    rounds = rounds_of(log)
    paced_rounds = [x for x in rounds if any(n == "handoff_tick" for n, _ in x)]
    n_ho = sum(1 for n, _ in log if n == "handoff_tick")
    check("2 minute: in ten minutes of 20 s steps the hand-off clock ran 9 or 10 times (once a minute), not 30", 9 <= n_ho <= 10, n_ho)
    check("2 minute: the stall pass ran as often as the hand-off tick (the same rounds)", sum(1 for n, _ in log if n == "stall_tick") == n_ho)
    full = [[n for n, _ in x if n not in TEN] for x in paced_rounds]
    bad = [x for x in full if x != EXPECT]
    n_ten = sum(1 for n, _ in log if n == "filing_tick")
    ten_after = all([n for n, _ in x][len(EXPECT):] == TEN for x in paced_rounds if any(n in TEN for n, _ in x))
    check("2 ten-minute set: in ten minutes it ran once (the first paced round), right after the minute set in that round", n_ten == 1 and sum(1 for n, _ in log if n == "dates_tick") == 1 and sum(1 for n, _ in log if n == "silence_tick") == 1 and ten_after, (n_ten, ten_after))
    check("2 order: every round that runs a paced clock runs the whole table, in the table's order, including the ten-minute passes in front", bool(full) and not bad, bad[:2])
    th = [t for n, t in log if n == "handoff_tick"]
    check("2 gap: two hand-off ticks are never less than a minute apart", all(b - a >= 60.0 for a, b in zip(th, th[1:])), [b - a for a, b in zip(th, th[1:])])
    ts = [t for n, t in log if n == "stall_tick"]
    check("2 gap: …nor two stall passes", all(b - a >= 60.0 for a, b in zip(ts, ts[1:])), [b - a for a, b in zip(ts, ts[1:])])
    st = {t["name"]: t for t in r.status()["ticks"]}
    check("2 guard: the done check that failed was recorded and every tick behind it still ran in those rounds",
          st["check_tick"]["errors"] >= 1 and st["check_tick"]["last_error"] and st["handoff_tick"]["errors"] == 0 and st["stall_tick"]["errors"] == 0 and not bad, st["check_tick"])

    # ---- 3. a wake event between two minutes
    log.clear(); boom_in["name"] = None
    clk.t = 5000.0
    r3 = new_runner(); r3._pace_end = clk(); r3._wake_at = None
    r3.run_round(); log.clear()                      # the first round: everything once
    clk.advance(25.0); r3.run_round(event=True)
    check("3 wake: an event 25 s into the minute runs the watchers' pass and the anchor pass alone, in order", [n for n, _ in log] == ["wake_pass", "anchor_pass"], log)
    log.clear(); clk.advance(35.0)
    r3.run_round()
    check("3 wake: …and the minute after it starts with them again and runs the table in order, the ten-minute set (due at this first paced round) right after the minute set", [n for n, _ in log] == ORDER, [n for n, _ in log])
finally:
    restore()

# ---- 4. the one number
clk.t = 9000.0; log.clear(); install()
try:
    r_old = new_runner(pace=20.0); r_old._pace_end = clk(); r_old._wake_at = None
    for _ in range(10):
        r_old.run_round(); clk.advance(20.0)
    cnt_old = sum(1 for n, _ in log if n == "handoff_tick")
    log.clear(); clk.t = 9000.0
    r_new = new_runner(); r_new._pace_end = clk(); r_new._wake_at = None
    for _ in range(10):
        r_new.run_round(); clk.advance(20.0)
    cnt_new = sum(1 for n, _ in log if n == "handoff_tick")
    check("4 pace: three minutes in 20 s steps (the first paced round comes one pace after the start): a 20 s runner ticks the hand-off clock 9 times (the old cadence), the default runner 3 times (once a minute)", cnt_old == 9 and cnt_new == 3, (cnt_old, cnt_new))
finally:
    restore()

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
