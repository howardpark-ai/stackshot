"""Scenario test for the one save of an item (stackshot/service/writes.py, `save` under the three write contexts PLAIN, NAMED and QUIET) — a scratch store, fake `Steps`, no server, no port, no network.

The save runs the steps that are still server.py's through `Steps` and its own stamps in an order that is part of what a save means. This suite installs fake steps that record each call, wraps the
stamps and the file write of `writes` in recorders (which call the real function), and holds what the order and the context decide:

  1  contexts       PLAIN runs the mover settling and the owner steps; NAMED runs the owner steps only; QUIET runs neither; the other steps (ask, the three hand-off steps, phase, the lists, the search
                    index) run in all three, and the two hand-off steps that take `quiet` are told so for QUIET alone; a context outside the three is refused
  2  order          the whole sequence of a PLAIN save, from the read-only guard to the search index; the phase is stored before the last-activity record reads it; the project's id is stamped before the
                    item file is written, and the file holds it
  3  mirror         `mirror=False` queues no GitHub job even when GitHub is on; `mirror=True` queues one when it is on and none when it is off; `background` reaches the job
  4  read-only      the guard is the first thing a save does: a refused guard stops it before any step, any stamp or the file, and the stored item stays as it was
  5  after the write the lists, the search index, the hand-back line (a closed item only) and the pending answer's ack (a writer only) follow the file, and a step that fails there never fails the write
  6  before         the step that reads the version before gets the stored file (None for a new item), through the project's id

    tests/run-suite writes        -> exit 0 / 1"""
import json, os, pathlib, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="wr2-writes-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home").mkdir(); (T / "store/a").mkdir(parents=True); (T / "fleet").mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import readonly as ro, store as cstore
from stackshot.github import ghsync as gh
from stackshot.model import item_project as ip
from stackshot.service import writes
cstore.STORE = T / "store"

LOG = []                                    # what the save did, in order: (name, detail)
SEEN = {}                                   # what a recorder saw at the moment it ran
FAIL_STEP = set()                           # the steps that raise (section 5)
def rec(name, **detail): LOG.append((name, detail))
def step(name, fn=None):
    def run(*a):
        rec(name, args=a)
        if fn: fn(*a)
        if name in FAIL_STEP: raise RuntimeError(name + " broke")
    return run
def set_phase(gid, item): item.setdefault("metadata", {})["phase"] = "wr2-phase"
def fake_steps():
    return writes.Steps(
        settle_mover=step("settle_mover"), owner_steps=step("owner_steps"), ask_stamp=step("ask_stamp"), handoff_on_save=step("handoff_on_save"),
        handoff_his_over=step("handoff_his_over"), handoff_follow=step("handoff_follow"), phase_stamp=step("phase_stamp", set_phase),
        foryou_on_save=step("foryou_on_save"), landed_on_save=step("landed_on_save"), search_touch=step("search_touch"),
        handback_drop=step("handback_drop"), answer_ack=step("answer_ack"))
writes.install(fake_steps())

real = {n: getattr(writes, n) for n in ("record_writer", "_stamp_activity", "_stamp_last_activity")}
real_guard, real_ip_stamp, real_write_item = ro.guard, ip.stamp, cstore._write_item
real_enabled, real_on_change = gh.enabled, gh.on_change
def wrap(name):
    def run(*a, **k):
        rec(name)
        return real[name](*a, **k)
    return run
def last_activity(item, *a, **k):
    SEEN["phase_at_last_activity"] = (item.get("metadata") or {}).get("phase")
    rec("_stamp_last_activity")
    return real["_stamp_last_activity"](item, *a, **k)
def guard(what=""):
    rec("guard")
    return real_guard(what)
def ip_stamp(meta):
    rec("ip.stamp")
    if isinstance(meta, dict): meta["wr2_ip_marker"] = 1          # a mark in the item at the moment of the stamp: the file written after it holds it
    return real_ip_stamp(meta)
def write_item(p, item):
    rec("write_item", marked=bool((item.get("metadata") or {}).get("wr2_ip_marker")))
    return real_write_item(p, item)
GH_ON = [False]
def gh_enabled(): return GH_ON[0]
def on_change(gid, before, item, background=False):
    rec("ghsync", background=background)
writes.record_writer = wrap("record_writer"); writes._stamp_activity = wrap("_stamp_activity"); writes._stamp_last_activity = last_activity
ro.guard = guard; ip.stamp = ip_stamp; cstore._write_item = write_item; gh.enabled = gh_enabled; gh.on_change = on_change

def blank(i, **kw): return {"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": "open", "metadata": {"project": "projects/alpha"}, **kw}
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
n_item = [100]
def run_save(ctx=None, **kw):
    """A save of a new item with a fresh id, with the log cleared first; → (log names, the id)."""
    n_item[0] += 1; gid = f"a{n_item[0]}"; LOG.clear(); SEEN.clear()
    if ctx is None: writes.save(gid, blank(n_item[0]), **kw)
    else: writes.save(gid, blank(n_item[0]), ctx=ctx, **kw)
    return [n for n, _ in LOG], gid
def args_of(name): return next((d.get("args") for n, d in LOG if n == name), None)

# ---------------------------------------------------------------- 1. contexts
plain, _ = run_save(); plain_log = list(LOG)
named, _ = run_save(writes.NAMED)
quiet, _ = run_save(writes.QUIET); quiet_log = list(LOG)
check("1 a save with no context is a PLAIN one: the mover is settled and the owner steps follow", "settle_mover" in plain and "owner_steps" in plain and plain.index("settle_mover") < plain.index("owner_steps"), plain)
check("1 PLAIN is the default context of save", writes.save.__defaults__[-1] is writes.PLAIN and writes.PLAIN.settle == "", writes.save.__defaults__)
check("1 NAMED runs the owner steps and does not settle the mover", "owner_steps" in named and "settle_mover" not in named, named)
check("1 QUIET runs neither the mover settling nor the owner steps", "settle_mover" not in quiet and "owner_steps" not in quiet, quiet)
OTHER = ["ask_stamp", "handoff_on_save", "handoff_his_over", "handoff_follow", "phase_stamp", "foryou_on_save", "landed_on_save", "search_touch"]
for label, got in (("PLAIN", plain), ("NAMED", named), ("QUIET", quiet)):
    check(f"1 {label} still runs every other step once", all(got.count(s) == 1 for s in OTHER), got)
quiet_flag = lambda log: ([d["args"][3] for n, d in log if n == "handoff_his_over"], [d["args"][5] for n, d in log if n == "handoff_follow"])
check("1 the hand-off steps are told `quiet` for a QUIET save", quiet_flag(quiet_log) == ([True], [True]), quiet_flag(quiet_log))
check("1 …and not for a PLAIN one", quiet_flag(plain_log) == ([False], [False]), quiet_flag(plain_log))
try: writes.WriteContext(settle="loud"); bad = None
except ValueError as e: bad = str(e)
check("1 a context outside the three is refused", bad is not None and "loud" in bad, bad)
check("1 the three contexts are the three values", (writes.PLAIN.settle, writes.NAMED.settle, writes.QUIET.settle) == ("", writes.SETTLE_NAMED, writes.SETTLE_QUIET), None)

# ---------------------------------------------------------------- 2. order
FULL = ["guard", "settle_mover", "owner_steps", "record_writer", "_stamp_activity", "ask_stamp", "handoff_on_save", "handoff_his_over", "handoff_follow", "phase_stamp",
        "_stamp_last_activity", "ip.stamp", "write_item", "foryou_on_save", "landed_on_save", "search_touch"]
check("2 the whole order of a PLAIN save, from the guard to the search index", plain == FULL, plain)
check("2 a QUIET save keeps that order without the two steps it leaves out", quiet == [s for s in FULL if s not in ("settle_mover", "owner_steps")], quiet)
check("2 the phase is stored before the last-activity record", plain.index("phase_stamp") < plain.index("_stamp_last_activity"), plain)
check("2 …and the last-activity record reads the phase just stored", SEEN.get("phase_at_last_activity") == "wr2-phase", SEEN)
check("2 the project's id is stamped before the item file is written", plain.index("ip.stamp") < plain.index("write_item"), plain)
check("2 …and the file written holds what the stamp set", dict(next(d for n, d in plain_log if n == "write_item"))["marked"] is True and rd(101)["metadata"].get("wr2_ip_marker") == 1, (plain_log, rd(101)["metadata"]))
check("2 the lists and the search index follow the file", plain.index("write_item") < min(plain.index(s) for s in ("foryou_on_save", "landed_on_save", "search_touch")), plain)

# ---------------------------------------------------------------- 3. mirror
GH_ON[0] = True
names, _ = run_save(mirror=False)
check("3 mirror=False queues no GitHub job even when GitHub is on", "ghsync" not in names, names)
names, _ = run_save(mirror=True, background=True); jobs = [d for n, d in LOG if n == "ghsync"]
check("3 mirror=True queues one when GitHub is on, after the file", names.count("ghsync") == 1 and names.index("write_item") < names.index("ghsync"), names)
check("3 …and `background` reaches the job", jobs and jobs[0]["background"] is True, jobs)
names, _ = run_save()
check("3 the default is to mirror", names.count("ghsync") == 1, names)
GH_ON[0] = False
names, _ = run_save(mirror=True)
check("3 mirror=True queues nothing when GitHub is off", "ghsync" not in names, names)

# ---------------------------------------------------------------- 4. read-only
n_item[0] += 1; gid_ro = f"a{n_item[0]}"; LOG.clear()
ro._reload_for_test(True)
try:
    try: writes.save(gid_ro, blank(n_item[0])); refused = None
    except ro.ReadOnlyError as e: refused = e
finally: ro._reload_for_test(False)
check("4 a save on the standby copy is refused", refused is not None, refused)
check("4 …before any step, stamp or file: the guard is the only call", [n for n, _ in LOG] == ["guard"] and not (T / f"store/a/{gid_ro[1:]}.json").exists(), LOG)
n_item[0] += 1; gid_ro2 = f"a{n_item[0]}"; writes.save(gid_ro2, blank(n_item[0])); stored = (T / f"store/a/{gid_ro2[1:]}.json").read_text(); LOG.clear()
ro._reload_for_test(True)
try:
    try: writes.save(gid_ro2, {**blank(n_item[0]), "subject": "[home] changed"}, writer="home-front", ctx=writes.QUIET)
    except ro.ReadOnlyError: pass
finally: ro._reload_for_test(False)
check("4 …a stored item stays as it was", (T / f"store/a/{gid_ro2[1:]}.json").read_text() == stored and [n for n, _ in LOG] == ["guard"], LOG)

# ---------------------------------------------------------------- 5. after the write
n_item[0] += 1; gid5 = f"a{n_item[0]}"; LOG.clear()
writes.save(gid5, blank(n_item[0]))
check("5 no writer: no pending-answer ack, and an open item drops no hand-back line", "answer_ack" not in [n for n, _ in LOG] and "handback_drop" not in [n for n, _ in LOG], LOG)
LOG.clear(); done = blank(n_item[0], status="completed")
writes.save(gid5, done, writer="home-front"); names = [n for n, _ in LOG]
check("5 a writer's save of a closed item drops the hand-back line and acks the pending answer, after the lists", names[-2:] == ["handback_drop", "answer_ack"] and names.index("search_touch") < names.index("handback_drop"), names)
check("5 the ack is for the writer", args_of("answer_ack") == (gid5, "home-front"), args_of("answer_ack"))
FAIL_STEP.update({"foryou_on_save", "landed_on_save", "handback_drop", "answer_ack"})
n_item[0] += 1; gid5b = f"a{n_item[0]}"; LOG.clear()
try: writes.save(gid5b, blank(n_item[0], status="completed"), writer="home-front"); err = None
except Exception as e: err = e
FAIL_STEP.clear()
names = [n for n, _ in LOG]
check("5 a list, the hand-back line or the ack that fails never fails the write, and the steps after it still run", err is None and (T / f"store/a/{gid5b[1:]}.json").exists() and names[-3:] == ["search_touch", "handback_drop", "answer_ack"], (err, names))

# ---------------------------------------------------------------- 6. before
n_item[0] += 1; gid6 = f"a{n_item[0]}"; LOG.clear()
writes.save(gid6, blank(n_item[0]))
first_before = [d["args"][1] for n, d in LOG if n == "handoff_on_save"][0]
LOG.clear(); second = blank(n_item[0], subject="[home] second")
writes.save(gid6, second)
second_before = [d["args"][1] for n, d in LOG if n == "handoff_on_save"][0]
check("6 a new item has no version before", first_before is None, first_before)
check("6 a stored item's version before is the file as it stood, not the item being saved", isinstance(second_before, dict) and second_before.get("subject") == f"[home] item {n_item[0]}" and second["subject"] == "[home] second", second_before)
check("6 the item written is the one given", rd(n_item[0])["subject"] == "[home] second", rd(n_item[0]))

print(("ok" if not fails else "FAILED") + f": writes scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
