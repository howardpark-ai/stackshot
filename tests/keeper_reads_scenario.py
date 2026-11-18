"""Scenario test for the keeper read gauge and counter (stackshot/projects/keeper_reads.py): fixture data, no live state, no network, no server process (a temporary config and a temporary state folder).

Covers: a read at a removal-candidate site (an old keeper form answering a keeper question) is counted per site (the kind of read and the function that made it) once per distinct row key per process,
so a read repeated a thousand times is one key; the counts are added to `<state>/keeper-reads.json` by one atomic write, at most once a minute and when the process ends, with `since` kept and the last
read time per site; the inventory gauge (registry rows whose keeper only an old form names, their page keys bounded at 50) is written with the next flush and refreshed by `projects.sync`; the file
carries a heartbeat (the last successful write) that a failed write does not move; the flush never waits on the file's lock (a due flush while another process holds it is skipped and the counts stay in
memory, then written); a damaged file is kept once as `.bad` and the report says so; a state folder that is missing, a read-only standby and an unwritable folder never change what a read answers; the readers
that note answer only for an old form, and the by-design name readers note nothing; the report (`stackshot keeper-reads`, text and `--json`) prints a loud line when the file is missing, unreadable or
older than a day, the gauge, each site with its last read in the instance's timezone and its distinct keys, and the readers that stay; it writes nothing.

    tests/run-suite keeper_reads        → exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keeperreads-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store", "state", "brain", "secrets"): (T / d).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, STACK)
from stackshot.projects import keeper_reads as KR
from stackshot.projects import keeper as KP
from stackshot.anchors import anchors as ANC
from stackshot.core import config as cfg

INIT_STATE = dict(KR._STATE)       # what a fresh process starts from, taken before anything ran
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
F = T / "state" / "keeper-reads.json"; BAD = T / "state" / "keeper-reads.json.bad"
def filed(): return json.loads(F.read_text()) if F.exists() else {}
def sites(): return {k: len(v["keys"]) for k, v in (filed().get("sites") or {}).items()}
def keys(site): return (filed().get("sites") or {}).get(site, {}).get("keys")
ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
RD = "probe <- __main__.reader"

# ---- 1. counting: per site and per distinct key, kept in the process, written once on flush
def reader(key="k1"): KR.note("probe", key, 1)               # a function that notes itself
def helper(key="k1"): KR.note("probe via helper", key)       # a helper that notes for its caller
def caller(key="k1"): helper(key)
check("nothing is written by a read: the file does not exist before a flush", not F.exists())
for _ in range(1000): reader()
reader("k2"); caller(); caller("k2")
check("a read is counted in the process and nothing is on disk yet", not F.exists() and len(KR._PENDING) == 2, KR._PENDING)
check("a thousand reads of one row are one pending key, not a thousand", KR._PENDING[RD][1] == {"k1", "k2"}, KR._PENDING)
check("the flush reports success", KR.flush() is True)
check("per site: the function that noted itself, the caller of a helper that noted for it; each row once", sites() == {RD: 2, "probe via helper <- __main__.caller": 2}, sites())
d = filed()
check("the file carries its schema, when it was made, its heartbeat and the last read per site", d["schema"] == 1 and re.match(ISO, d["since"]) and re.match(ISO, d["flushed"]) and all(re.match(ISO, v["last"]) for v in d["sites"].values()), d)
check("the keys are the rows read", keys(RD) == ["k1", "k2"], filed())
since = d["since"]
check("nothing is left pending after a flush and no temp file is left beside the file", not KR._PENDING and sorted(p.name for p in (T / "state").iterdir()) == ["keeper-reads.json", "keeper-reads.json.lock"], sorted(p.name for p in (T / "state").iterdir()))
reader("k3"); reader("k1"); KR.flush()
check("a second flush adds the new key to the first and keeps `since`", keys(RD) == ["k1", "k2", "k3"] and filed()["since"] == since, filed())
check("a flush with nothing pending and no gauge is a success and writes nothing", (lambda b: KR.flush() is True and F.read_text() == b)(F.read_text()))
KR._SEEN.clear(); KR._LAST.clear(); reader("k1"); KR.flush()
check("a process that read the same row again (a restart) adds no new key", keys(RD) == ["k1", "k2", "k3"], filed())
many = set(f"r{i}" for i in range(KR.KEYS_PER_SITE + 50))
KR._SEEN[RD] = set(many); KR._PENDING[RD] = [time.time(), set(many)]; KR.flush()
check("the keys of a site are bounded", len(keys(RD)) == KR.KEYS_PER_SITE, len(keys(RD)))
F.unlink(); KR._SEEN.clear(); KR._LAST.clear()

# ---- 2. the last read moves once a minute for a row already counted; at most one write a minute
reader("k1"); KR.flush()
KR._LAST[RD] = time.time() - KR.EVERY - 5
reader("k1")
check("a row already counted moves the site's last-read time once a minute, and adds no key", KR._PENDING and KR._PENDING[RD][1] == set(), KR._PENDING)
KR.flush()
KR._STATE["flushed"] = time.time()
reader("zz")
check("a read within the minute is only counted", "zz" not in (keys(RD) or []) and KR._PENDING, sites())
KR._STATE["flushed"] = time.time() - KR.EVERY - 1
reader("yy")
check("the first read after the minute writes what is waiting", {"zz", "yy"} <= set(keys(RD)) and not KR._PENDING, sites())
hb = filed()["flushed"]

# ---- 3. the flush never blocks on the lock (a due flush while another process holds it is skipped)
import fcntl
KR._STATE["flushed"] = time.time() - KR.EVERY - 1
with open(str(F) + ".lock", "a") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)         # another process holds the file's lock
    got = []; t0 = time.time()
    t = threading.Thread(target=lambda: (reader("held"), got.append(1))); t.start(); t.join(5)
    check("a read that is due to write does not wait on the file's lock: it answers at once, the write is skipped", got == [1] and time.time() - t0 < 3, (got, time.time() - t0))
    check("...the count stays in memory and the file is unchanged", "held" not in (keys(RD) or []) and KR._PENDING[RD][1] == {"held"}, KR._PENDING)
    t = threading.Thread(target=lambda: got.append(KR.flush())); t.start(); t.join(5)
    check("a flush called while the lock is held returns False at once and keeps the counts", got[-1] is False and KR._PENDING, got)
    fcntl.flock(lk, fcntl.LOCK_UN)
check("...and the next flush writes them", KR.flush() is True and "held" in keys(RD) and not KR._PENDING, filed())
check("the heartbeat moved with the write that succeeded", filed()["flushed"] >= hb, filed())

# ---- 4. a failed write never breaks a read; the counts wait; the heartbeat does not move
hb = filed()["flushed"]
real = KR._path
KR._path = lambda: T / "no-such-folder" / "keeper-reads.json"
reader("a1"); reader("a2")
check("a state folder that is gone: the flush fails quietly, the counts stay pending, no folder is made", KR.flush() is False and not (T / "no-such-folder").exists() and len(KR._PENDING[RD][1]) == 2, KR._PENDING)
KR._path = real
check("the heartbeat did not move for a write that failed", filed()["flushed"] == hb)
KR.flush()
check("...and they are written at the next flush", {"a1", "a2"} <= set(keys(RD)), keys(RD))
(T / "state").chmod(0o500)
try:
    reader("b1")
    ok = KR.flush()
finally:
    (T / "state").chmod(0o700)
check("an unwritable folder: the flush fails quietly and keeps the count", (ok is False or os.geteuid() == 0) and (KR._PENDING or os.geteuid() == 0), (ok, KR._PENDING))
KR.flush()
from stackshot.core import readonly as RO
saved = RO.is_read_only
RO.is_read_only = lambda: True
reader("c1")
hb = filed()["flushed"]
check("a read-only standby writes nothing and keeps the count in memory", KR.flush() is False and "c1" not in keys(RD) and KR._PENDING and filed()["flushed"] == hb)
RO.is_read_only = saved
KR.flush()
check("...and writes it when it is no standby", "c1" in keys(RD), keys(RD))
check("note() never raises, whatever the frame depth", KR.note("deep", "k", 99) is None)

# ---- 5. a damaged file is kept once as .bad, started again, and said so
F.write_text("{ not json"); reader("d1"); KR.flush()
check("a damaged file is started again, not an error, and the old one is kept as .bad", BAD.read_text() == "{ not json" and keys(RD) == ["d1"] and re.match(ISO, filed()["restarted"]), (F.read_text()[:200], BAD.exists()))
F.write_text("[1, 2]"); reader("d2"); KR.flush()
check("a second damage keeps one backup only: the newest damaged file", BAD.read_text() == "[1, 2]" and sorted(p.name for p in (T / "state").iterdir()) == ["keeper-reads.json", "keeper-reads.json.bad", "keeper-reads.json.lock"], sorted(p.name for p in (T / "state").iterdir()))
rep = KR.report()
check("the report says a damaged file was replaced and where the old one is", any("damaged file was replaced" in l and "keeper-reads.json.bad" in l for l in rep), rep)
F.unlink(); BAD.unlink()

# ---- 6. the gauge: registry rows whose keeper only an old form names
KR._STATE["gauge"] = None
KR.gauge(["projects/b", "projects/a"]); KR.flush()
check("the gauge is the count of legacy rows and their page keys, in order", filed()["legacy"]["count"] == 2 and filed()["legacy"]["keys"] == ["projects/a", "projects/b"] and re.match(ISO, filed()["legacy"]["at"]), filed())
KR.gauge([f"projects/p{i:03d}" for i in range(120)]); KR.flush()
check("the gauge lists at most 50 keys and counts them all", filed()["legacy"]["count"] == 120 and len(filed()["legacy"]["keys"]) == 50, filed()["legacy"])
KR.gauge([]); KR.flush()
check("zero rows is a gauge of zero, written, not an absent one", filed()["legacy"]["count"] == 0 and filed()["legacy"]["keys"] == [], filed())
KR._STATE["flushed"] = 0.0; before = filed()["flushed"]; time.sleep(1.1); KR.gauge([])
check("the gauge is written again as a heartbeat when a minute has passed, with nothing else pending", filed()["flushed"] > before, filed())
from stackshot.projects import projects as PRJ
KR.gauge(["projects/stale"]); KR.flush()
PRJ.sync(reg={"projects/legacy-one": {"session": "team-legacy", "role": "name", "keeper_source": "legacy"}, "projects/marked": {"session": "team-m-main", "role": "mark", "keeper_source": "mark"}, "projects/plain": {}},
         path=T / "state" / "published.json")
KR.flush()
check("projects.sync refreshes the gauge from the registry it publishes", filed()["legacy"]["count"] == 1 and filed()["legacy"]["keys"] == ["projects/legacy-one"], filed()["legacy"])

# ---- 7. the readers: a read is counted only where an old form is what decides the keeper of the row (keeper_source legacy), never where a mark answers
F.unlink(); KR._SEEN.clear(); KR._LAST.clear(); KR._PENDING.clear(); KR._STATE["gauge"] = None
raw = {"projects/forge": {"session": "team-forge-main", "role": "mark", "legacy_session": "team-forge", "legacy_role": "name"},
       "projects/forge/sub": {"session": "team-forge-main", "role": "inherited"},
       "projects/loft": {"session": "team-loft", "role": "name"},
       "projects/pier": {"session": "team-pier-main", "role": "agent"},
       "projects/pier/sub": {"session": "team-pier-main", "role": "inherited"},
       "projects/none": {"session": "", "role": ""}}
marked = {k: {**v, **KP.fields(k, raw)} for k, v in raw.items()}
KR.flush()
check("the keeper_source of the fixture: marks answer, the name line and the agent line are legacy", [marked[k]["keeper_source"] for k in raw] == ["mark", "mark", "legacy", "legacy", "legacy", ""], [marked[k]["keeper_source"] for k in raw])
check("building the rows (keeper.fields, which runs before the record is laid over them) is not counted: the gauge counts the final rows", not F.exists() or not sites(), sites())
check("the legacy rows of the fixture are the ones the gauge would count", {k for k, v in marked.items() if v["keeper_source"] == "legacy"} == {"projects/loft", "projects/pier", "projects/pier/sub"})
F.unlink(missing_ok=True); KR._SEEN.clear(); KR._PENDING.clear()
KP.names_of(marked["projects/forge"]); KP.names_of(marked["projects/pier"]); KP.name_line(marked["projects/loft"]); KP.name_line(marked["projects/forge"]); KP.name_line(marked["projects/none"])
KR.flush()
check("keeper.names_of (a legacy_session exists only under a mark) and keeper.name_line (the name readers) are not instrumented", not F.exists() or not sites(), sites())
ANC.name_line("projects/forge", marked); ANC.name_line("projects/forge/sub", marked); ANC.name_line("projects/none", marked); KR.flush()
check("anchors.name_line counts no mark and no inherited mark", not F.exists() or not sites(), sites())
ANC.name_line("projects/loft", marked); ANC.name_line("projects/loft", marked); ANC.name_line("projects/pier", marked); KR.flush()
check("...and counts a row whose old form decides the keeper, once each", [(k, v) for k, v in sites().items()] == [("old form as the keeper <- __main__.<module>", 2)] and keys("old form as the keeper <- __main__.<module>") == ["projects/loft", "projects/pier"], sites())
F.unlink(missing_ok=True); KR._SEEN.clear(); KR._PENDING.clear()
ANC.session_hubs("team-forge-main", marked, {}); ANC.session_hubs("team-forge", marked, {}); KR.flush()
check("anchors.session_hubs counts nothing for a session a mark names", not F.exists() or not sites(), sites())
ANC.session_hubs("team-loft", marked, {}); KR.flush()
check("...and counts a page matched by its own legacy name line alone", keys("old form as the keeper <- __main__.<module>") == ["projects/loft"], sites())
from stackshot.projects import pages as PG
F.unlink(missing_ok=True); KR._SEEN.clear(); KR._PENDING.clear()
PG.keeper_of("projects/x", {"projects/x": {"display-name": "team-x"}}); PG.keeper_of("projects/y", {"projects/y": {"agent": "team-y"}}); PG.keeper_of("projects/x", {"projects/x": {"display-name": "team-x"}}, marks=False)
KR.flush()
check("pages.keeper_of is not instrumented (the mark lives in the record, which it does not see)", not F.exists() or not sites(), sites())

# ---- 8. the report and the command
F.unlink(missing_ok=True); KR._SEEN.clear(); KR._PENDING.clear(); KR._LAST.clear()
KR.gauge(["projects/a", "projects/b"] + [f"k{i}" for i in range(5)] + ["z"])
for i in range(5): reader(f"k{i}")
caller("z"); KR.flush()
rep = KR.report()
check("the report: the gauge, then the sites with the most keys first, each with its last read and key count", rep[0].startswith("legacy keepers: 8 registry row(s)") and "projects/a, projects/b" in rep[0] and rep[1].startswith("removal-candidate readers, since ")
      and rep[2].split()[0] == "5" and rep[2].endswith(RD) and rep[3].split()[0] == "1" and " last " in rep[2], rep)
check("the report says what a quiet week does and does not show", any(l == KR.QUIET for l in rep) and "gauge at zero" in KR.QUIET and "not covered" in KR.QUIET and "old keeper forms can go" not in "\n".join(rep), rep)
check("the report lists the readers that stay", sum(l.startswith("  stays  ") for l in rep) == len(KR.BY_DESIGN) and len(KR.BY_DESIGN) >= 1, rep)
check("the report lists the readers not counted, which stay until the readers are removed", sum(l.startswith("  until removed  ") for l in rep) == len(KR.UNTIL_REMOVED) and len(KR.UNTIL_REMOVED) >= 1, rep)
check("no loud line when the file is fresh", not any(l.startswith("NOT RECORDING") for l in rep), rep)
before = F.read_text()
env = {**os.environ, "PYTHONPATH": STACK}
r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env=env, cwd=STACK)
check("the command prints the report and writes nothing", r.returncode == 0 and r.stdout.splitlines()[0] == rep[0] and F.read_text() == before, (r.returncode, r.stdout, r.stderr[-300:]))
r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads", "--json"], capture_output=True, text=True, env=env, cwd=STACK)
check("--json is the file's own content", r.returncode == 0 and json.loads(r.stdout) == json.loads(before), r.stdout[:300])
d = json.loads(before); d["flushed"] = iso(time.time() - 2 * 86400); F.write_text(json.dumps(d))
rep = KR.report()
check("a file last written more than a day ago is a loud line, ahead of the counts", rep[0].startswith("NOT RECORDING?") and "more than a day ago" in rep[0] and any(l.startswith("legacy keepers") for l in rep), rep)
d["flushed"] = iso(time.time() - 3600); F.write_text(json.dumps(d))
check("a file written an hour ago is not loud", not KR.report()[0].startswith("NOT RECORDING"), KR.report())
del d["flushed"]; F.write_text(json.dumps(d))
check("a file with no heartbeat is a loud line", KR.report()[0].startswith("NOT RECORDING?") and "no time of a last successful write" in KR.report()[0], KR.report())
F.write_text("{ nope")
r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env=env, cwd=STACK)
check("an unreadable file is a loud line and no counts, and the report leaves the file alone", r.returncode == 0 and r.stdout.splitlines()[0].startswith("NOT RECORDING?") and "unreadable" in r.stdout.splitlines()[0] and "removal-candidate" not in r.stdout and F.read_text() == "{ nope", r.stdout)
F.unlink()
r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env=env, cwd=STACK)
check("a missing file is a loud line (not a quiet week) and the report does not create it", r.returncode == 0 and r.stdout.splitlines()[0].startswith("NOT RECORDING?") and "not a week of no reads" in r.stdout.splitlines()[0] and not F.exists(), (r.stdout, r.stderr[-300:]))
# ---- 9. the flush at exit waits for the lock: processes that exit together lose no key
F.unlink(missing_ok=True); (T / "state" / "keeper-reads.json.lock").unlink(missing_ok=True); KR._STATE["gauge"] = None
N = 24
start = time.time() + 1.5
code = "import sys, time; sys.path.insert(0, %r); from stackshot.projects import keeper_reads as KR; t = float(sys.argv[2])\nwhile time.time() < t: pass\nKR.note('exit probe', sys.argv[1], 1)" % STACK
procs = [subprocess.Popen([sys.executable, "-c", code, f"proc{i:02d}", str(start)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for i in range(N)]
errs = [pr.communicate()[1].decode()[-200:] for pr in procs]
check("the processes ended cleanly", all(pr.returncode == 0 for pr in procs), errs)
got = set(keys("exit probe <- __main__.<module>") or [])
check("24 processes that note one key each and exit together: every key reached the file", got == {f"proc{i:02d}" for i in range(N)}, sorted({f"proc{i:02d}" for i in range(N)} - got))
held = []
with open(str(F) + ".lock", "a") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    KR.note("exit probe", "late", 1)
    t0 = time.time(); t = threading.Thread(target=lambda: held.append(KR.flush(0.3))); t.start(); t.join(5)
    check("a flush with a bounded wait gives up when the lock stays held, after about that wait", held == [False] and 0.25 <= time.time() - t0 < 3, (held, time.time() - t0))
    fcntl.flock(lk, fcntl.LOCK_UN)
check("...keeping the count for the next flush", KR.flush() is True and "late" in keys("exit probe <- __main__.<module>"), filed())
import errno
real_flock = fcntl.flock
def broken_flock(fd, how):
    raise OSError(errno.ENOLCK, "No locks available")
fcntl.flock = broken_flock
try:
    KR.note("exit probe", "enolck", 1)
    t0 = time.time(); r = KR.flush(2.0)
finally:
    fcntl.flock = real_flock
check("a lock error that is not a held lock (ENOLCK) fails the exit-time wait at once, not after the two seconds", r is False and time.time() - t0 < 0.5, (r, time.time() - t0))
check("...and keeps the count for the next flush", KR.flush() is True and "enolck" in keys("exit probe <- __main__.<module>"), filed())
check("the flush at exit is the one that waits: it is registered as the exit hook with the wait", KR.EXIT_WAIT == 2.0 and KR._at_exit.__name__ == "_at_exit")

# ---- 10. a gauge on disk carries a generation that grows by one with every gauge written: a publisher writes only a gauge it computed after reading the current generation, whatever the clocks say
class Clock:
    def __init__(self, t): self.now = t
    def time(self): return self.now
    def monotonic(self): return time.monotonic()
    def sleep(self, s): time.sleep(s)
clock = Clock(1_000_000.0); real_time = KR.time; KR.time = clock
class Proc:
    """One process's counter state, swapped in for the module's own while a step of that process runs (two writers in one test process)."""
    def __init__(self): self.b = ({}, {}, {}, {**INIT_STATE, "flushed": clock.time(), "hooked": True})
    def __enter__(self):
        self.out = tuple(dict(x) for x in (KR._PENDING, KR._SEEN, KR._LAST, KR._STATE))
        for live, mine in zip((KR._PENDING, KR._SEEN, KR._LAST, KR._STATE), self.b): live.clear(); live.update(mine)
        return self
    def __exit__(self, *a):
        self.b = tuple(dict(x) for x in (KR._PENDING, KR._SEEN, KR._LAST, KR._STATE))
        for live, mine in zip((KR._PENDING, KR._SEEN, KR._LAST, KR._STATE), self.out): live.clear(); live.update(mine)
sched = []
class Handle:
    def __init__(self, delay, fn): self.delay, self.fn, self.cancelled = delay, fn, False
    def cancel(self): self.cancelled = True
real_after = KR._after
KR._after = lambda delay, fn: (sched.append(Handle(delay, fn)), sched[-1])[1]
def gen(): return (filed().get("legacy") or {}).get("gen")
def publish(keys_, at=None, fresh=True):
    """A fresh process computes a gauge and writes it (at wall-clock time `at`)."""
    if at is not None: clock.now = at
    with Proc(): KR.gauge(keys_); KR.flush()
F.unlink(missing_ok=True); clock.now = 1_000_000.0
# the older publisher computes its zero gauge while another process holds the file's lock: its write is skipped and the gauge waits; the newer publisher then writes
older = Proc()
with open(str(F) + ".lock", "a") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    with older: KR.gauge([])
    fcntl.flock(lk, fcntl.LOCK_UN)
check("the older publisher's write was skipped (the lock was held): no file yet", not F.exists(), filed())
publish(["projects/a"])
check("the newer publisher's gauge is generation 1", gen() == 1 and filed()["legacy"]["count"] == 1, filed().get("legacy"))
with older:
    reader("k1"); ok = KR.flush()
check("the older publisher flushes last, with the very same clock reading: its zero does not overwrite the newer gauge (it computed it before the file's generation)", ok is True and filed()["legacy"]["count"] == 1 and filed()["legacy"]["keys"] == ["projects/a"] and gen() == 1, filed().get("legacy"))
check("...but its read is still counted", "k1" in (keys(RD) or []) and filed()["flushed"] == iso(1_000_000.0), filed())
with older: KR.flush(); KR.flush(KR.EXIT_WAIT)
check("...and not at its exit-time flush either", filed()["legacy"]["count"] == 1 and gen() == 1, filed().get("legacy"))
with older: KR.gauge([]); KR.flush()
check("a gauge it computes after reading the file's generation is written, as the next generation", filed()["legacy"]["count"] == 0 and gen() == 2, filed().get("legacy"))
# a clock that steps back (or any writer that once stamped a later time) never freezes the gauge
publish(["projects/x"], at=5_000_000.0)
publish([], at=4_990_000.0)
check("the clock stepped back by hours: a newer gauge is still written (generations, not times, decide)", filed()["legacy"]["count"] == 0 and gen() == 4, filed().get("legacy"))
publish(["projects/y"], at=4_980_000.0)
check("...and the next one too; the time written is for display only", filed()["legacy"]["keys"] == ["projects/y"] and gen() == 5 and filed()["legacy"]["at"] == iso(4_980_000.0), filed().get("legacy"))
publish(["projects/y", "projects/z"], at=4_980_000.0)
check("two gauges written at one clock reading: the later one is the newer", filed()["legacy"]["count"] == 2 and gen() == 6, filed().get("legacy"))
# a file with a time far ahead, or an infinite one, froze the gauge in the version that compared times
good = {"schema": 1, "since": iso(1_000_000.0), "flushed": iso(1_000_000.0), "sites": {}}
F.write_text(json.dumps({**good, "legacy": {"count": 1, "keys": ["a"], "at": "2099-01-01T00:00:00Z", "stamp": 4_000_000_000.0}}))
publish(["projects/n"], at=1_000_050.0)
check("a gauge from the previous version (no generation, a time far ahead) is replaced by a gauge written now, as generation 1", filed()["legacy"]["keys"] == ["projects/n"] and gen() == 1, filed().get("legacy"))
F.write_text(json.dumps({**good, "legacy": {"count": 1, "keys": ["a"], "at": iso(1_000_000.0), "stamp": float("inf")}}))
d10, prob10 = KR.load()
check("an infinite stamp is a damaged file, not a gauge that nothing can replace", prob10.startswith("unreadable") and d10 == {}, prob10)
BAD.unlink(missing_ok=True); publish(["projects/q"], at=1_000_060.0)
check("...and the next gauge replaces it, the old file kept as .bad", filed()["legacy"]["keys"] == ["projects/q"] and gen() == 1 and BAD.exists(), (filed().get("legacy"), BAD.exists()))
BAD.unlink(missing_ok=True)

# ---- 11. a read recorded by a process that then makes no other call is written when its minute is up, on a timer, not at its exit only
F.unlink(missing_ok=True); sched.clear(); solo = Proc(); clock.now = 2_000_000.0
with solo:
    KR._STATE["flushed"] = clock.now
    clock.now = 2_000_010.0; reader("solo")
    check("a read within the minute of the last write is not written yet, and a timer is set for the minute's end (50 seconds on)", not F.exists() and len(sched) == 1 and abs(sched[0].delay - 50.0) < 0.01, [h.delay for h in sched])
    clock.now = 2_000_020.0; reader("solo2")
    check("another read before then sets no second timer", len(sched) == 1, len(sched))
    clock.now = 2_000_060.0; sched[0].fn()
    check("the timer's flush writes what waits, with no further call", {"solo", "solo2"} <= set(keys(RD) or []) and not KR._PENDING and KR._STATE["timer"] is None, (filed(), KR._PENDING))
    reader("solo3")
    check("a read after that, within the new minute, sets the next timer", len(sched) == 2 and not sched[1].cancelled, len(sched))
    KR._path = lambda: T / "no-such-folder" / "keeper-reads.json"
    try: sched[1].fn()
    finally: KR._path = real
    check("a timer's flush that fails sets the timer again, and the count waits", len(sched) == 3 and KR._PENDING and KR._STATE["timer"] is sched[2], (len(sched), KR._PENDING))
    clock.now = 2_000_070.0
    KR._at_exit()
    check("the flush at exit cancels the timer and writes", sched[2].cancelled and "solo3" in keys(RD) and KR._STATE["timer"] is None, (sched[2].cancelled, filed()))
    clock.now = 2_000_100.0; KR._STATE["flushed"] = clock.now; KR._STATE["gauge"] = ["projects/s"]
    KR.gauge(["projects/s"])
    check("a gauge update that is not due and changed nothing waits for a timer too (its heartbeat)", KR._STATE["timer"] is not None and not sched[-1].cancelled, KR._STATE["timer"])
KR._after = real_after; KR.time = real_time
EVERY0 = KR.EVERY; KR.EVERY = 0.3
made = []
KR._after = lambda delay, fn: (made.append(real_after(delay, fn)), made[-1])[1]
F.unlink(missing_ok=True)
with Proc():
    KR._STATE["flushed"] = time.time(); reader("thr")
    check("a real timer: one is started, on a daemon thread (a process does not wait for it at its end)", len(made) == 1 and made[0].daemon is True, made)
    t_end = time.time() + 10.0
    while time.time() < t_end and not ("thr" in (keys(RD) or []) and not KR._PENDING): time.sleep(0.05)       # a poll, not a fixed sleep: a slow box only waits longer
    check("...and with no other call the read is in the file a moment after the interval", "thr" in (keys(RD) or []) and not KR._PENDING, filed())
KR._after = real_after; KR.EVERY = EVERY0

# ---- 12. a file whose nested values are malformed is a damaged file: the report does not crash, and a flush keeps it as .bad and starts again
for label, doc in (("a site's keys that is a number", {"sites": {"reader": {"keys": 1}}}), ("a site that is a number", {"sites": {"reader": 1}}), ("keys that are not strings", {"sites": {"r": {"keys": [1, 2]}}}),
                   ("a site's last that is a number", {"sites": {"r": {"last": 5, "keys": []}}}), ("a gauge count that is a word", {"sites": {}, "legacy": {"count": "x"}}), ("gauge keys that are a number", {"sites": {}, "legacy": {"count": 1, "keys": 3}}),
                   ("a gauge that is a list", {"sites": {}, "legacy": [1]}), ("a heartbeat that is a number", {"sites": {}, "flushed": 5}),
                   ("a gauge count that is NaN", {"sites": {}, "legacy": {"count": float("nan"), "keys": []}}), ("a gauge count that is Infinity", {"sites": {}, "legacy": {"count": float("inf"), "keys": []}}),
                   ("a gauge count that is not a whole number", {"sites": {}, "legacy": {"count": 1.5, "keys": []}}), ("a gauge count that is true", {"sites": {}, "legacy": {"count": True, "keys": []}}),
                   ("a negative gauge count", {"sites": {}, "legacy": {"count": -1, "keys": []}}), ("a gauge generation that is not a whole number", {"sites": {}, "legacy": {"count": 1, "keys": [], "gen": 1.5}}),
                   ("a gauge generation that is Infinity", {"sites": {}, "legacy": {"count": 1, "keys": [], "gen": float("inf")}}), ("a gauge generation that is a word", {"sites": {}, "legacy": {"count": 1, "keys": [], "gen": "3"}}),
                   ("a negative gauge generation", {"sites": {}, "legacy": {"count": 1, "keys": [], "gen": -1}}), ("a gauge stamp that is NaN", {"sites": {}, "legacy": {"count": 1, "keys": [], "stamp": float("nan")}})):
    F.write_text(json.dumps(doc)); BAD.unlink(missing_ok=True)
    d12, prob12 = KR.load()
    try: rep12 = KR.report(); crashed = ""
    except Exception as e: rep12 = []; crashed = repr(e)
    check(f"malformed ({label}): the file reads as unreadable and the report does not crash, it says nothing can be told", d12 == {} and prob12.startswith("unreadable") and not crashed and rep12 and rep12[0].startswith("NOT RECORDING?"), (prob12, crashed, rep12[:1]))
    F.write_text(json.dumps(doc)); KR._SEEN.clear(); KR._PENDING.clear(); KR._STATE["gauge"] = None; reader("m1"); ok12 = KR.flush()
    check(f"malformed ({label}): a flush keeps it as .bad, replaces it, and the file then reads", ok12 is True and BAD.exists() and BAD.read_text() == json.dumps(doc) and keys(RD) == ["m1"] and KR.load()[1] == "" and bool(filed().get("restarted")), (ok12, filed()))
for label, text in (("a file nested a hundred thousand lists deep", "[" * 100000), ("a file nested fifty thousand objects deep", '{"a":' * 50000)):
    F.write_text(text); BAD.unlink(missing_ok=True)
    try: d12, prob12 = KR.load(); crashed = ""
    except BaseException as e: d12, prob12, crashed = {}, "", repr(e)[:80]
    check(f"malformed ({label}): load() says unreadable and does not raise", not crashed and d12 == {} and prob12.startswith("unreadable"), (prob12, crashed))
    KR._SEEN.clear(); KR._PENDING.clear(); KR._STATE["gauge"] = None; reader("m2"); ok12 = KR.flush()
    check(f"malformed ({label}): a flush keeps it as .bad and starts again, once", ok12 is True and BAD.exists() and BAD.read_text() == text and keys(RD) == ["m2"], (ok12, F.read_text()[:100]))
F.unlink(missing_ok=True); BAD.unlink(missing_ok=True)
F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {"a": {"last": iso(2.0), "keys": ["x"]}, "b": {}}, "legacy": {"count": 2, "keys": ["x"], "at": iso(3.0), "gen": 4}}))
check("a file this code writes, with a site that has no keys yet and a gauge with a generation, still reads", KR.load()[1] == "" and not KR.report()[0].startswith("NOT RECORDING"), KR.load()[1])

# ---- 13. a site's keys are rows of the current gauge: a row that has since got a mark leaves the sites when the gauge is computed
F.unlink(missing_ok=True); BAD.unlink(missing_ok=True); KR._STATE["gauge"] = None; KR._STATE["gauge_at"] = 0.0; KR._SEEN.clear(); KR._PENDING.clear()
for k in ("p/a", "p/b", "p/c"): reader(k)
KR.flush()
check("fixture: three rows read at a site, no gauge yet: nothing is pruned", keys(RD) == ["p/a", "p/b", "p/c"], keys(RD))
KR.gauge(["p/b", "p/c"]); KR.flush()
check("a gauge without row p/a drops that row's key from the site; the site stays with its last read", keys(RD) == ["p/b", "p/c"] and filed()["sites"][RD]["last"], filed())
reader("p/d"); KR.gauge(["p/b", "p/c"]); KR.flush()
check("a read of a row the gauge does not list is not kept either", keys(RD) == ["p/b", "p/c"], keys(RD))
KR.gauge([]); KR.flush()
check("the gauge at zero leaves no key at any site: the sites are at zero with it", keys(RD) == [] and filed()["legacy"]["count"] == 0 and sites() == {RD: 0}, filed())
rep13 = KR.report()
check("...and the report prints the site with 0 keys, and still the quiet-week line", any(l.split()[:2] == ["0", "key(s)"] and l.endswith(RD) for l in rep13) and KR.QUIET in rep13, rep13)
KR._SEEN.clear(); reader("p/b"); KR.gauge(["p/b"]); KR.flush()
check("a row that is back in the gauge is counted again by the next read", keys(RD) == ["p/b"], keys(RD))

# a process that both reads and publishes: a key pruned against its cached gauge is counted again when it is read again
F.unlink(missing_ok=True); KR._STATE["gauge"] = None; KR._SEEN.clear(); KR._PENDING.clear()
reader("r1"); reader("r2"); KR.gauge(["r1"]); KR.flush()
check("a key pruned from the file (its row is not in the gauge) is dropped from the process's seen set too", keys(RD) == ["r1"] and "r2" not in KR._SEEN.get(RD, set()) and "r1" in KR._SEEN.get(RD, set()), (keys(RD), KR._SEEN))
KR.gauge(["r1", "r2"]); reader("r2"); KR.flush()
check("...so the next read of it is counted once the gauge lists the row", keys(RD) == ["r1", "r2"], keys(RD))

# ---- 14. the flush at exit waits for a timer's flush that is writing, and a write that fails leaves no temporary file
F.unlink(missing_ok=True); KR._STATE["gauge"] = None; KR._SEEN.clear(); KR._PENDING.clear()
TMP = T / "state" / ".keeper-reads.json.tmp"
with Proc():
    KR._STATE["flushed"] = time.time()
    reader("slow1")
    started = threading.Event(); real_fsync = os.fsync
    def slow_fsync(fd): started.set(); time.sleep(0.6); return real_fsync(fd)
    os.fsync = slow_fsync
    try:
        th = threading.Thread(target=KR.flush); th.start()                  # the timer's flush: it has taken the counts and is writing
        started.wait(5); t0 = time.time()
        KR._at_exit()                                                        # the process ends: this must not return before that write is done
        waited = time.time() - t0; there = "slow1" in (keys(RD) or [])
    finally:
        os.fsync = real_fsync
    th.join(5)
    check("the exit-time flush waits for a timer flush that is mid-write: the read is in the file when it returns, and no temporary file is left", there and waited >= 0.3 and not TMP.exists(), (there, waited, TMP.exists()))
    reader("slow2")
    real_replace = os.replace
    def failing_replace(a, b):
        if str(a).endswith(".tmp"): raise OSError("disk full")
        return real_replace(a, b)
    os.replace = failing_replace
    try: ok14 = KR.flush(); left = TMP.exists()
    finally: os.replace = real_replace
    check("a write that fails after the temporary file was made removes it, and the count waits", ok14 is False and not left and "slow2" in KR._PENDING.get(RD, [0, set()])[1], (ok14, left, KR._PENDING))
    check("...and the next flush writes it", KR.flush() is True and "slow2" in keys(RD) and not TMP.exists(), keys(RD))
    held14 = threading.Event(); gate = threading.Event()
    def slow_fsync2(fd): held14.set(); gate.wait(5); return real_fsync(fd)
    os.fsync = slow_fsync2
    try:
        reader("slow3"); th = threading.Thread(target=KR.flush); th.start(); held14.wait(5)
        reader("slow4"); got14 = KR.flush()
        gate.set(); th.join(5)
    finally:
        os.fsync = real_fsync; gate.set()
    check("a flush that finds another flush of the same process writing does not wait for it and does not take the counts: they are written by the next one", got14 is False and "slow4" in KR._PENDING.get(RD, [0, set()])[1] and "slow3" in keys(RD), (got14, KR._PENDING, keys(RD)))
    KR.flush()
KR.time = real_time

from stackshot import cli
check("the program is registered under `stackshot keeper-reads`", cli.PROGRAMS.get("keeper-reads", ("",))[0] == "stackshot.projects.keeper_reads")

if fails: print(f"FAILED: keeper reads scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper reads scenario, {len(ran)} checks")
