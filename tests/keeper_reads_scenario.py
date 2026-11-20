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
reader("k1"); e0 = KR._PENDING[RD][0]; reader("k1")
check("a row read again since the last write is one pending key, and the site's last-read time does not move within the minute", KR._PENDING[RD][1] == {"k1"} and KR._PENDING[RD][0] == e0, KR._PENDING)
KR._LAST[RD] = time.monotonic() - KR.EVERY - 5
reader("k1")
check("...it moves once a minute (on the monotonic clock), and adds no second key", KR._PENDING and KR._PENDING[RD][1] == {"k1"} and KR._PENDING[RD][0] > e0, KR._PENDING)
KR.flush()
check("a row read again after a write adds no second key to the file", keys(RD) == ["k1"], keys(RD))
KR._STATE["flushed"] = time.monotonic()
reader("zz")
check("a read within the minute is only counted", "zz" not in (keys(RD) or []) and KR._PENDING, sites())
KR._STATE["flushed"] = time.monotonic() - KR.EVERY - 1
reader("yy")
check("the first read after the minute writes what is waiting", {"zz", "yy"} <= set(keys(RD)) and not KR._PENDING, sites())
hb = filed()["flushed"]

# ---- 3. the flush never blocks on the lock (a due flush while another process holds it is skipped)
import fcntl
KR._STATE["flushed"] = time.monotonic() - KR.EVERY - 1
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
# a minute ago on the monotonic clock itself: 0.0 is under a minute ago on a box up for less than one, which a fresh CI runner is
KR._STATE["flushed"] = time.monotonic() - KR.EVERY - 1; before = filed()["flushed"]; time.sleep(1.1); KR.gauge([])
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
check("an unreadable file is a loud line and no counts, the gauge is unknown (exit status 2), and the report leaves the file alone", r.returncode == 2 and r.stdout.splitlines()[0].startswith("NOT RECORDING?") and "unreadable" in r.stdout.splitlines()[0] and "removal-candidate" not in r.stdout and F.read_text() == "{ nope", r.stdout)
F.unlink()
r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env=env, cwd=STACK)
check("a missing file is a loud line (not a quiet week), the gauge is unknown (exit status 2), and the report does not create it", r.returncode == 2 and r.stdout.splitlines()[0].startswith("NOT RECORDING?") and "not a week of no reads" in r.stdout.splitlines()[0] and not F.exists(), (r.stdout, r.stderr[-300:]))
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
    def __init__(self, t): self.now = t; self.mono = t        # the wall clock and the monotonic clock: a test steps the wall clock alone to show it does not matter
    def time(self): return self.now
    def monotonic(self): return self.mono
    def sleep(self, s): time.sleep(s)
clock = Clock(1_000_000.0); real_time = KR.time; KR.time = clock
class Proc:
    """One process's counter state, swapped in for the module's own while a step of that process runs (two writers in one test process)."""
    def __init__(self): self.b = ({}, {}, {}, {**INIT_STATE, "flushed": clock.monotonic(), "hooked": True})
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
F.unlink(missing_ok=True); sched.clear(); solo = Proc(); clock.now = clock.mono = 2_000_000.0
with solo:
    KR._STATE["flushed"] = clock.now
    clock.now = clock.mono = 2_000_010.0; reader("solo")
    check("a read within the minute of the last write is not written yet, and a timer is set for the minute's end (50 seconds on)", not F.exists() and len(sched) == 1 and abs(sched[0].delay - 50.0) < 0.01, [h.delay for h in sched])
    clock.now = clock.mono = 2_000_020.0; reader("solo2")
    check("another read before then sets no second timer", len(sched) == 1, len(sched))
    clock.now = clock.mono = 2_000_060.0; sched[0].fn()
    check("the timer's flush writes what waits, with no further call", {"solo", "solo2"} <= set(keys(RD) or []) and not KR._PENDING and KR._STATE["timer"] is None, (filed(), KR._PENDING))
    reader("solo3")
    check("a read after that, within the new minute, sets the next timer", len(sched) == 2 and not sched[1].cancelled, len(sched))
    KR._path = lambda: T / "no-such-folder" / "keeper-reads.json"
    try: sched[1].fn()
    finally: KR._path = real
    check("a timer's flush that fails sets the timer again, and the count waits", len(sched) == 3 and KR._PENDING and KR._STATE["timer"] is sched[2], (len(sched), KR._PENDING))
    clock.now = clock.mono = 2_000_070.0
    KR._at_exit()
    check("the flush at exit cancels the timer and writes", sched[2].cancelled and "solo3" in keys(RD) and KR._STATE["timer"] is None, (sched[2].cancelled, filed()))
    clock.now = clock.mono = 2_000_100.0; KR._STATE["flushed"] = clock.now; KR._STATE["gauge"] = ["projects/s"]
    KR.gauge(["projects/s"])
    check("a gauge update that is not due and changed nothing waits for a timer too (its heartbeat)", KR._STATE["timer"] is not None and not sched[-1].cancelled, KR._STATE["timer"])
KR._after = real_after; KR.time = real_time
EVERY0 = KR.EVERY; KR.EVERY = 0.3
made = []
KR._after = lambda delay, fn: (made.append(real_after(delay, fn)), made[-1])[1]
F.unlink(missing_ok=True)
with Proc():
    KR._STATE["flushed"] = time.monotonic(); reader("thr")
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
F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {"a": {"last": iso(2.0), "keys": ["x"]}, "b": {}}, "legacy": {"count": 2, "keys": ["x"], "at": iso(time.time()), "gen": 4}}))
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
check("a key pruned from the file (its row is not in the gauge) is not in the file, and the process remembers no key it has written", keys(RD) == ["r1"] and not KR._SEEN.get(RD), (keys(RD), KR._SEEN))
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

# ---- 15-22. the gauge's guarantees: the generation is read before the rows, a refused gauge is computed again (once), an epoch rides with the generation, a key another process pruned is counted again, a temporary file is the writer's own,
#      the wait is on the monotonic clock, a damaged gauge is unknown and never zero, and the docs say what is and is not promised.
def attempt(name, fn):
    """A check whose body may raise (a call that the code under test does not have yet): a raise is a failed check, not the end of the run. `fn` returns (condition, what was seen)."""
    ran.append(name)
    try:
        ok, got = fn()
    except BaseException as e:  # noqa: BLE001
        fails.append(name); print(f"FAIL {name}: raised {e!r}"[:700]); return
    if not ok:
        fails.append(name); print(f"FAIL {name}: {str(got)[:700]}")
def fresh_state():
    """No file, no pending count, a process state as a new process has it (and no timer waiting)."""
    for p in list((T / "state").glob("keeper-reads.json*")) + list((T / "state").glob(".keeper-reads.json*")): p.unlink()
    for d_ in (KR._PENDING, KR._SEEN, KR._LAST): d_.clear()
    KR._STATE.clear(); KR._STATE.update({**INIT_STATE, "flushed": 1e12, "hooked": True, "timer": None})        # not due: a read waits for an explicit flush
    KR._after = lambda delay, fn: Handle(delay, fn)                                                            # and no real timer is started
class Virt(Proc):
    """Another process: its own counter state, due to write at once."""
    def __init__(self): self.b = ({}, {}, {}, {**INIT_STATE, "flushed": 0.0, "hooked": True, "timer": None})
def other_publishes(keys_):
    with Virt(): KR.gauge(keys_); KR.flush()
def legacy(): return filed().get("legacy") or {}
KR.time = time
PUB = T / "state" / "published.json"
ROW = lambda src: {"session": "team-x", "role": "name", "keeper_source": src}
ROWS_ZERO = {"projects/marked": ROW("mark"), "projects/plain": {}}
ROWS_ONE = {"projects/legacy-one": ROW("legacy"), "projects/marked": ROW("mark")}
real_registry = PRJ.registry
def only_sync(fn):
    """A registry whose build is `fn` for the publisher (the sync pass, or its retry), and the real one for anyone else that reads it (the id adoption in the same pass)."""
    return lambda: fn() if sys._getframe(1).f_code.co_name in ("sync", "again") else real_registry()

# 15. the generation is read before the rows are computed (a registry build that another process publishes during), and a refused gauge is computed again once
def lock_is_free():
    with open(str(F) + ".lock", "a") as lk:
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(lk, fcntl.LOCK_UN); return True
        except BlockingIOError: return False
def t15a():
    fresh_state(); calls = []; free = []
    def racing():
        calls.append(1)
        if len(calls) == 1:
            other_publishes(["projects/legacy-one"])          # the build is slow: another process publishes a nonzero gauge while it runs
            return ROWS_ZERO                                      # and this process's rows are the older view: no legacy row
        free.append(lock_is_free())
        return ROWS_ONE
    PRJ.registry = only_sync(racing)
    try:
        with Virt(): PRJ.sync(path=PUB, force=True)
    finally: PRJ.registry = real_registry
    return legacy().get("count") == 1 and legacy().get("keys") == ["projects/legacy-one"] and len(calls) == 2 and free == [True], (legacy(), len(calls), free)
attempt("a publisher that snapshots zero (the registry it built has no legacy row), while another process publishes a nonzero gauge: its zero is refused, and it computes again and writes what the registry holds then, outside the file's lock", t15a)
def t15b():
    fresh_state(); calls = []
    def always():
        calls.append(1); other_publishes([f"projects/r{len(calls)}"]); return ROWS_ZERO
    PRJ.registry = only_sync(always)
    try:
        with Virt(): PRJ.sync(path=PUB, force=True)
    finally: PRJ.registry = real_registry
    return len(calls) == 2 and legacy().get("keys") == ["projects/r2"] and legacy().get("count") == 1, (len(calls), legacy())
attempt("a gauge refused again by another publisher is not tried a third time: one retry, then the other process's gauge stays", t15b)
def t15c():
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot()
    other_publishes(["projects/a", "projects/b"])
    with Virt(): KR.gauge([], base=base); KR.flush()
    return legacy().get("keys") == ["projects/a", "projects/b"] and legacy().get("gen") == 2, legacy()
attempt("a gauge computed after a snapshot that is no longer the file's (another gauge written since) is refused under the lock and the file keeps the newer one", t15c)

def t15d():
    fresh_state(); calls = []
    def emptying():
        calls.append(1)
        if len(calls) == 1:
            other_publishes(["projects/legacy-one"]); return ROWS_ZERO
        return {}                                                # the registry reads as empty when it is asked again
    PRJ.registry = only_sync(emptying)
    try:
        with Virt(): PRJ.sync(path=PUB, force=True)
    finally: PRJ.registry = real_registry
    return len(calls) == 2 and legacy().get("keys") == ["projects/legacy-one"] and legacy().get("count") == 1, (len(calls), legacy())
attempt("a retry that finds the registry empty publishes nothing (an empty registry is never a zero gauge): the other process's gauge stays", t15d)

# 16. an epoch rides with the generation: a file removed or replaced starts a new epoch, and an older in-memory gauge never wins over it
def t16a():
    fresh_state(); other_publishes(["projects/a"]); e1 = legacy().get("epoch"); calls = []
    def removing():
        calls.append(1)
        if len(calls) == 1:
            F.unlink(); other_publishes(["projects/x"])        # the file is removed and starts again: generation 1 once more, new content
            return ROWS_ZERO
        return {"projects/x": ROW("legacy")}
    PRJ.registry = only_sync(removing)
    try:
        with Virt(): PRJ.sync(path=PUB, force=True)
    finally: PRJ.registry = real_registry
    return legacy().get("keys") == ["projects/x"] and isinstance(e1, str) and e1 and legacy().get("epoch") not in (None, e1) and len(calls) == 2, (e1, legacy(), len(calls))
attempt("a file removed after the publisher took its snapshot: the older gauge (a zero) does not win by a generation that went back to 1, the file's new epoch makes it refused, and the retry writes the current rows", t16a)
def t16b():
    fresh_state(); other_publishes(["projects/a"]); e1 = legacy().get("epoch"); base = KR.snapshot()
    d_ = filed(); d_["epoch"] = d_["legacy"]["epoch"] = "another-run"; d_["legacy"]["keys"] = ["projects/z"]; F.write_text(json.dumps(d_))      # the same generation as the snapshot's, another epoch: a different run of generations
    with Virt(): KR.gauge([], base=base); KR.flush()
    return base == (e1, 1) and legacy().get("keys") == ["projects/z"] and legacy().get("epoch") == "another-run", (base, legacy())
attempt("the same generation under another epoch is another gauge: the older one is refused", t16b)
def t16c():
    fresh_state()
    F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}, "legacy": {"count": 1, "keys": ["a"], "at": iso(1.0), "gen": 3}}))
    s3 = KR.snapshot(); ok3 = KR.load()[1] == ""
    F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}, "legacy": {"count": 1, "keys": ["a"], "at": iso(1.0)}}))
    s0 = KR.snapshot(); ok0 = KR.load()[1] == ""
    with Virt(): KR.gauge(["b"], base=s0); KR.flush()
    return ok3 and ok0 and s3 == (None, 3) and s0 == (None, 0) and legacy().get("gen") == 1 and isinstance(legacy().get("epoch"), str) and legacy()["epoch"] and legacy().get("keys") == ["b"], (s3, s0, legacy())
attempt("a file without an epoch (as the live one is) still loads and counts as epoch none, with its generation (or 0); the first gauge written to it takes an epoch", t16c)
def t16d():
    fresh_state(); other_publishes(["projects/a"]); e1 = legacy().get("epoch"); reader("q"); KR.flush()
    other_publishes(["projects/a", "projects/b"])
    return isinstance(e1, str) and legacy().get("epoch") == e1 and legacy().get("gen") == 2, legacy()
attempt("the epoch stays through the generations of one file, and a read-only flush changes neither", t16d)

# 17. a key another process pruned from the file is counted again by a long-lived process that counted it before (two real processes)
def t17():
    fresh_state(); env17 = {**os.environ, "PYTHONPATH": STACK}
    code_a = ("import sys; sys.path.insert(0, %r)\nfrom stackshot.projects import keeper_reads as KR\nfor line in sys.stdin:\n    cmd, _, arg = line.strip().partition(' ')\n"
              "    if cmd == 'read': KR.note('long lived', arg, 1); print('ok', flush=True)\n    elif cmd == 'flush': print(KR.flush(), flush=True)\n    elif cmd == 'quit': break\n" % STACK)
    import select
    pa = subprocess.Popen([sys.executable, "-c", code_a], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env17)
    def ask(line):
        pa.stdin.write(line + "\n"); pa.stdin.flush()
        return pa.stdout.readline().strip() if select.select([pa.stdout], [], [], 30)[0] else "timeout"
    SITE = "long lived <- __main__.<module>"
    try:
        r = [ask("read r1"), ask("flush")]
        first = keys(SITE)
        KR.gauge(["projects/other"]); KR.flush()                    # another process's gauge: r1 is not a row of it, so its key leaves the file
        pruned = keys(SITE)
        KR.gauge(["r1"]); KR.flush()                                # and a gauge that lists r1 again
        r += [ask("read r1"), ask("flush")]
        last = keys(SITE)
    finally:
        try: ask("quit")
        except Exception: pass
        try: pa.wait(10)
        except Exception: pa.kill(); pa.wait(5)
    return r == ["ok", "True", "ok", "True"] and first == ["r1"] and pruned == [] and last == ["r1"], (r, first, pruned, last)
attempt("a long-lived process counted r1, another process pruned the key and wrote a gauge that lists the row again: the long-lived process's next read of r1 is counted, not suppressed by its memory", t17)
def t17b():
    fresh_state(); reader("q1"); before = "q1" in KR._SEEN.get(RD, set()); KR.flush(); after = "q1" in KR._SEEN.get(RD, set()); reader("q1")
    return before and not after and KR._PENDING.get(RD, [0, set()])[1] == {"q1"}, (before, after, KR._PENDING)
attempt("a key leaves the process's memory with the write that put it in the file, and a read after that is pending again (the file is what says a key is counted)", t17b)

# 18. the temporary file is the writer's own: named by the process and a counter, removed only by the writer that made it, and a failed write never takes another writer's
def t18a():
    fresh_state(); seen18 = []; real_fsync = os.fsync
    def spy(fd): seen18.append(sorted(p.name for p in (T / "state").iterdir() if p.name.endswith(".tmp"))); return real_fsync(fd)
    os.fsync = spy
    try: reader("t1"); KR.flush(); reader("t2"); KR.flush()
    finally: os.fsync = real_fsync
    left = sorted(p.name for p in (T / "state").iterdir() if p.name.endswith(".tmp"))
    return len(seen18) == 2 and all(len(x) == 1 and str(os.getpid()) in x[0] for x in seen18) and seen18[0] != seen18[1] and left == [], (seen18, left)
attempt("each write uses a temporary name of its own (the process id and a counter), and none is left", t18a)
def t18b():
    fresh_state(); env18 = {**os.environ, "PYTHONPATH": STACK}
    code_b = ("import os, sys; sys.path.insert(0, %r)\nfrom stackshot.projects import keeper_reads as KR\nreal = os.fsync\n"
              "def slow(fd):\n    print('writing', flush=True); sys.stdin.readline(); return real(fd)\nsys.stdin.readline()\nos.fsync = slow\n"
              "KR.note('b probe', 'bkey', 1)\nprint('result', KR.flush(), flush=True)\n" % STACK)
    import select
    pb = subprocess.Popen([sys.executable, "-c", code_b], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env18)
    def line(): return pb.stdout.readline().strip() if select.select([pb.stdout], [], [], 30)[0] else "timeout"
    got = {}; hooked = []; real_flock = fcntl.flock; real_replace = os.replace
    def hook(fd, how):
        r = real_flock(fd, how)
        if how == fcntl.LOCK_UN and not hooked:
            hooked.append(1); pb.stdin.write("go\n"); pb.stdin.flush(); got["b"] = line()          # the lock is free: another process takes it and is mid-write
        return r
    def failing(a, b):
        if str(a).endswith(".tmp"): raise OSError("disk full")
        return real_replace(a, b)
    fcntl.flock = hook; os.replace = failing
    try: reader("a1"); ok_a = KR.flush()
    finally: fcntl.flock = real_flock; os.replace = real_replace
    try:
        pb.stdin.write("\n"); pb.stdin.flush(); got["res"] = line()
    finally:
        try: pb.wait(10)
        except Exception: pb.kill(); pb.wait(5)
    mine = sorted(p.name for p in (T / "state").iterdir() if p.name.endswith(".tmp"))
    return ok_a is False and got.get("b") == "writing" and got.get("res") == "result True" and "bkey" in (keys("b probe <- __main__.<module>") or []) and mine == [] and "a1" in KR._PENDING.get(RD, [0, set()])[1], (ok_a, got, mine)
attempt("a write that fails does not remove the temporary file of another process that took the lock right after it: that process's write succeeds, and the failing writer's own file is gone", t18b)

# 19. the wait before the next write is on the monotonic clock: a wall clock that steps back does not delay a flush
class Clk:
    def __init__(self): self.wall = 5_000_000.0; self.mono = 5_000_000.0
    def time(self): return self.wall
    def monotonic(self): return self.mono
    def sleep(self, s): time.sleep(s)
def t19a():
    fresh_state(); clk = Clk(); sched19 = []
    KR._after = lambda delay, fn: (sched19.append(Handle(delay, fn)), sched19[-1])[1]; KR.time = clk
    try:
        KR._STATE["flushed"] = clk.mono
        clk.mono += 10; clk.wall += 10 - 7200                  # ten seconds later by the monotonic clock; the wall clock was stepped back two hours
        reader("m1")
    finally: KR.time = time
    return len(sched19) == 1 and abs(sched19[0].delay - 50.0) < 0.5 and not F.exists(), [h.delay for h in sched19]
attempt("a read ten seconds after a write, with the wall clock stepped back two hours: the timer is set for the 50 seconds left, not for hours", t19a)
def t19b():
    fresh_state(); clk = Clk(); sched19 = []
    KR._after = lambda delay, fn: (sched19.append(Handle(delay, fn)), sched19[-1])[1]; KR.time = clk
    try:
        KR._STATE["flushed"] = clk.mono
        clk.mono += 61; clk.wall += 61 - 7200
        reader("m2")
    finally: KR.time = time
    return "m2" in (keys(RD) or []) and not KR._PENDING, (filed(), KR._PENDING, [h.delay for h in sched19])
attempt("a read a minute after the last write is written at once even when the wall clock was stepped back meanwhile", t19b)

# 20. a damaged gauge is unknown and never zero: the file is replaced as damaged, the report says "gauge unknown", and `stackshot keeper-reads` exits non-zero
import contextlib, io
G = {"at": iso(1.0), "gen": 2}
SHAPES = (("a gauge with no count (its keys listed)", {"sites": {}, "legacy": {**G, "keys": ["projects/a"]}}),
          ("a gauge with no count and no keys", {"sites": {}, "legacy": {"at": iso(1.0)}}),
          ("a gauge with no list of keys", {"sites": {}, "legacy": {**G, "count": 0}}),
          ("a gauge whose keys are null", {"sites": {}, "legacy": {**G, "count": 0, "keys": None}}),
          ("a gauge that counts fewer rows than it lists", {"sites": {}, "legacy": {**G, "count": 0, "keys": ["projects/a"]}}),
          ("an epoch that is a number", {"sites": {}, "legacy": {**G, "count": 0, "keys": [], "epoch": 5}}),
          ("an epoch that is empty", {"sites": {}, "legacy": {**G, "count": 0, "keys": [], "epoch": ""}}),
          ("an extra field 1e999 in the gauge", '{"sites": {}, "legacy": {"count": 1, "keys": ["a"], "at": "x", "gen": 2, "extra": 1e999}}'),
          ("an extra field -1e999 in a site", '{"sites": {"s": {"last": "x", "keys": [], "extra": -1e999}}}'),
          ("an extra field 1E999 at the top", '{"sites": {}, "extra": 1E999, "legacy": {"count": 0, "keys": []}}'),
          ("an extra field Infinity in the gauge", '{"sites": {}, "legacy": {"count": 0, "keys": [], "extra": Infinity}}'))
def run_main(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = KR.main(list(args))
    return rc, buf.getvalue()
def unknown_line(lines): return any(l.startswith("legacy keepers: gauge unknown") for l in lines) and not any(l.startswith("legacy keepers: 0 ") for l in lines)
for label, doc in SHAPES:
    text = doc if isinstance(doc, str) else json.dumps(doc)
    def t20(text=text):
        fresh_state(); F.write_text(text); d20, p20 = KR.load(); rep20 = KR.report(); rc20, out20 = run_main()
        return (d20 == {} and p20.startswith("unreadable") and KR.count_of(d20, p20) is None and unknown_line(rep20) and rc20 != 0 and "gauge unknown" in out20), (p20, rep20[:3], rc20)
    attempt(f"damaged gauge ({label}): the file is unreadable, the gauge is unknown (never zero), the report says so and the command exits non-zero", t20)
    def t20b(text=text):
        fresh_state(); F.write_text(text); reader("m1"); ok20 = KR.flush()
        return ok20 is True and BAD.exists() and BAD.read_text() == text and keys(RD) == ["m1"] and KR.load()[1] == "" and "Infinity" not in F.read_text(), (ok20, BAD.exists(), F.read_text()[:200])
    attempt(f"damaged gauge ({label}): a flush keeps it as .bad and writes a file that reads", t20b)
def t20c():
    fresh_state(); F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}, "legacy": {"count": 0, "keys": [], "at": iso(time.time()), "gen": 2}}))
    rc, out = run_main(); rep = KR.report()
    return KR.count_of(*KR.load()) == 0 and rc == 0 and rep[0].startswith("legacy keepers: 0 registry row(s)") and "gauge unknown" not in out, (rc, rep[:2])
attempt("a gauge of zero that is well formed is zero: it reads as zero and the command exits 0", t20c)
def t20d():
    fresh_state(); res = []
    res.append((KR.count_of(*KR.load()), run_main()[0]))                                                 # no file
    F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}}))
    res.append((KR.count_of(*KR.load()), run_main()[0], unknown_line(KR.report())))                       # a file with no gauge yet
    r = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": STACK}, cwd=STACK)
    res.append((r.returncode, "gauge unknown" in r.stdout))
    return res[0] == (None, 2) and res[1] == (None, 2, True) and res[2][0] != 0 and res[2][1], res
attempt("no file, and a file with no gauge yet, are unknown too: the gauge is not zero, the command exits non-zero (also as a real process)", t20d)

# 22. a gauge that is not being refreshed is unknown, not its old count: the heartbeat of the file (any process's read flush) must not make an old gauge look current
def gauge_file(at, count=0, flushed=None, keys_=None, gen=3):
    return json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time() if flushed is None else flushed), "sites": {},
                       "legacy": {"count": count, "keys": keys_ or [], "at": at, "gen": gen, "epoch": "e1"}})
def stale_checks(label, text, loud_gauge=True):
    def t():
        fresh_state(); F.write_text(text); d_, p_ = KR.load(); rep_ = KR.report(); rc_, out_ = run_main()
        r_ = subprocess.run([sys.executable, "-m", "stackshot.projects.keeper_reads"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": STACK}, cwd=STACK)
        gauge_loud = any(l.startswith("NOT RECORDING?") and "gauge" in l for l in rep_)
        return (p_ == "" and KR.count_of(d_, p_) is None and unknown_line(rep_) and rc_ == 2 and r_.returncode == 2 and (gauge_loud or not loud_gauge)), (p_, KR.count_of(d_, p_), rep_[:3], rc_, r_.returncode)
    attempt(label, t)
attempt("the bound on a gauge's age is a named constant of a few sync periods (above the minute between two writes, at most an hour)", lambda: (isinstance(getattr(KR, "GAUGE_STALE", None), float) and KR.EVERY < KR.GAUGE_STALE <= 3600.0, getattr(KR, "GAUGE_STALE", None)))
stale_checks("an old file (last write and gauge weeks ago, gauge zero): the gauge is unknown, not zero, the report says so loudly, and the status is 2 (command and in process)", gauge_file(iso(time.time() - 21 * 86400), flushed=time.time() - 21 * 86400))
stale_checks("a current heartbeat with a gauge computed a month ago (its publisher stopped): unknown, a loud line about the gauge, status 2; the heartbeat does not make it current", gauge_file(iso(time.time() - 30 * 86400)))
stale_checks("a gauge with a count above zero and an old time reads as unknown too, not as its count", gauge_file(iso(time.time() - 3600), count=2, keys_=["projects/a", "projects/b"]))
def t22d():
    out = []
    for age_, want in ((KR.GAUGE_STALE - 30, 0), (KR.GAUGE_STALE + 30, None)):
        fresh_state(); F.write_text(gauge_file(iso(time.time() - age_))); d_, p_ = KR.load(); out.append((KR.count_of(d_, p_), run_main()[0]))
    return out == [(0, 0), (None, 2)], out
attempt("a gauge just inside the bound still reads (zero is zero, status 0); one just outside it is unknown (status 2)", t22d)
def t22e():
    fresh_state(); d_ = json.loads(gauge_file(iso(time.time()))); del d_["legacy"]["at"]; F.write_text(json.dumps(d_)); dd, pp = KR.load()
    return pp == "" and KR.count_of(dd, pp) is None and run_main()[0] == 2, (pp, KR.count_of(dd, pp))
attempt("a gauge with no time of its own cannot be told from an old one: unknown", t22e)
def t22f():
    fresh_state(); other_publishes(["projects/a"]); rep_ = KR.report(); rc_, _ = run_main()
    return KR.count_of(*KR.load()) == 1 and rc_ == 0 and rep_[0].startswith("legacy keepers: 1 registry row(s)") and not any(l.startswith("NOT RECORDING") for l in rep_), rep_[:2]
attempt("a gauge written just now is current: its count, no loud line, status 0", t22f)

def naive(t): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t))
stale_checks("a gauge dated an hour ahead of the clock is unknown, not its count: a loud line about the gauge, status 2", gauge_file(iso(time.time() + 3600)))
stale_checks("a gauge dated a year ahead of the clock is unknown too", gauge_file(iso(time.time() + 365 * 86400)))
stale_checks("a gauge with a naive time an hour ahead (no zone: read as the writer's, UTC) is unknown", gauge_file(naive(time.time() + 3600)))
stale_checks("a gauge dated in the year 9999 is unknown, and the report does not raise", gauge_file("9999-12-31T23:59:59Z"))
stale_checks("a gauge dated in the year 9999 with a count above zero is unknown too", gauge_file("9999-12-31T23:59:59Z", count=1, keys_=["projects/a"]))
def t22g():
    out = []
    for at_ in (iso(time.time() + 2), naive(time.time())):
        fresh_state(); F.write_text(gauge_file(at_)); d_, p_ = KR.load(); rep_ = KR.report(); out.append((KR.count_of(d_, p_), run_main()[0], rep_[0].startswith("legacy keepers: 0 "), any(l.startswith("NOT RECORDING") for l in rep_)))
    return out == [(0, 0, True, False)] * 2, out
attempt("a gauge a couple of seconds ahead (the same host's rounding) and a naive time that is now both still read: zero is zero, no loud line, status 0", t22g)
attempt("the tolerance for a time ahead is a named constant of a few seconds", lambda: (isinstance(getattr(KR, "GAUGE_AHEAD", None), float) and 0 < KR.GAUGE_AHEAD <= 10.0, getattr(KR, "GAUGE_AHEAD", None)))
def t22h():
    fresh_state(); d_ = json.loads(gauge_file(iso(time.time()))); d_["since"] = "9999-12-31T23:59:59Z"; d_["sites"] = {"s <- m.f": {"last": "9999-12-31T23:59:59Z", "keys": ["a"]}}; d_["flushed"] = "9999-12-31T23:59:59Z"
    F.write_text(json.dumps(d_)); rep_ = KR.report(); return any("s <- m.f" in l for l in rep_), rep_[:2]
attempt("a last-read, a start or a heartbeat time in the year 9999 does not crash the report", t22h)

# 23. two publishers in one process: the step from the snapshot to the end of `gauge()` is one at a time, so the later snapshot's rows are the ones that stay
def t23a():
    fresh_state(); started = threading.Event(); release = threading.Event()
    def build():
        if threading.current_thread().name == "older":
            started.set(); release.wait(5); return ROWS_ZERO          # the older view of the registry, slow to build
        return ROWS_ONE                                                 # the newer view
    PRJ.registry = only_sync(build); ts = []
    try:
        with open(str(F) + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)                              # another process holds the file's lock: no write goes through, the gauges wait in memory
            try:
                ts = [threading.Thread(target=lambda: PRJ.sync(path=PUB, force=True), name=n_) for n_ in ("older", "newer")]
                ts[0].start(); started.wait(5); ts[1].start(); time.sleep(0.3); release.set()
                for t_ in ts: t_.join(10)
            finally: fcntl.flock(lk, fcntl.LOCK_UN)
    finally: PRJ.registry = real_registry; release.set()
    KR.flush()
    return all(not t_.is_alive() for t_ in ts) and legacy().get("keys") == ["projects/legacy-one"] and legacy().get("count") == 1, (legacy(), [t_.is_alive() for t_ in ts])
attempt("two syncs of one process share one snapshot while another process holds the file's lock: the older rows (finished last) do not overwrite the newer ones", t23a)
def t23b():
    fresh_state(); held = PRJ._GAUGE_STEP; held.acquire(); old_wait = PRJ.GAUGE_STEP_WAIT; PRJ.GAUGE_STEP_WAIT = 0.2; t0 = time.time()
    PRJ.registry = only_sync(lambda: ROWS_ONE)
    try: PRJ.sync(path=PUB, force=True, reg=None)
    finally: held.release(); PRJ.GAUGE_STEP_WAIT = old_wait; PRJ.registry = real_registry
    return time.time() - t0 < 3.0 and not F.exists() and KR._STATE["gauge"] is None, (time.time() - t0, F.exists(), KR._STATE["gauge"])
attempt("a sync that cannot take the gauge step within its bound goes on without publishing a gauge (it never waits for long, and the next sync publishes)", t23b)

# 24. a file has an epoch from the moment it is created, gauge or not: a file reset to no gauge is not the one a publisher snapshotted as no gauge
def t24a():
    fresh_state(); reader("x1"); KR.flush(); e_ = filed().get("epoch"); s_ = KR.snapshot()
    return isinstance(e_, str) and bool(e_) and s_ == (e_, 0) and "legacy" not in filed(), (e_, s_, filed())
attempt("a file created by a read flush, with no gauge, carries an epoch, and the snapshot takes it", t24a)
def t24b():
    fresh_state(); base = KR.snapshot()                                   # no file: A snapshots "no gauge"
    other_publishes(["projects/x"]); F.unlink()                           # B publishes, then the file is reset
    reader("r1"); KR.flush()                                              # a read flush creates the file again, with no gauge
    with Virt(): KR.gauge([], base=base); KR.flush()                      # A's older zero arrives
    return base == KR.ABSENT and legacy() == {}, (base, legacy())
attempt("a publisher that snapshotted no gauge does not write over a file that was reset to no gauge since (the new file has an epoch of its own)", t24b)
def t24c():
    fresh_state(); other_publishes(["projects/a"])
    return isinstance(filed().get("epoch"), str) and filed()["epoch"] == legacy().get("epoch") and KR.snapshot() == (filed()["epoch"], 1), (filed().get("epoch"), legacy())
attempt("the gauge's epoch is the file's", t24c)
def t24d():
    fresh_state(); F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}, "legacy": {"count": 1, "keys": ["a"], "at": iso(time.time()), "gen": 4}}))
    s_ = KR.snapshot(); reader("q"); KR.flush()
    return s_ == (None, 4) and KR.snapshot() == (None, 4) and "epoch" not in filed(), (s_, KR.snapshot(), filed().get("epoch"))
attempt("a file with no epoch (as the live one is) stays so through a read flush: a publisher that snapshotted it is not refused for that; its first gauge takes an epoch", t24d)
def t24e():
    fresh_state(); F.write_text("{ nope"); reader("q"); KR.flush()
    return isinstance(filed().get("epoch"), str) and BAD.exists(), (filed(), BAD.exists())
attempt("a damaged file replaced by a flush starts a new epoch", t24e)

# 25. a temporary file left by a writer that was killed is swept, under the lock, once it is more than a minute old
def t25a():
    fresh_state(); st = T / "state"; old_t = time.time() - 300; young = st / ".keeper-reads.json.4242.7.tmp"; old = st / ".keeper-reads.json.4243.1.tmp"; fixed = st / ".keeper-reads.json.tmp"; other = st / ".other.json.9.1.tmp"
    for p_ in (young, old, fixed, other): p_.write_text("{}")
    for p_ in (old, fixed, other): os.utime(p_, (old_t, old_t))
    reader("s1"); KR.flush()
    left = sorted(p.name for p in st.iterdir() if p.name.endswith(".tmp"))
    return left == sorted([young.name, other.name]) and keys(RD) == ["s1"], left
attempt("a flush removes the temporary files of the counter that a killed writer left, once they are more than a minute old; a younger one and another file's stay", t25a)
def t25b():
    fresh_state(); old = T / "state" / ".keeper-reads.json.4243.1.tmp"; old.write_text("{}"); os.utime(old, (time.time() - 300,) * 2)
    with open(str(F) + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try: reader("s2"); r_ = KR.flush()
        finally: fcntl.flock(lk, fcntl.LOCK_UN)
    return r_ is False and old.exists(), (r_, old.exists())
attempt("nothing is swept while another process holds the file's lock (the lock is what says no live writer is mid-write)", t25b)

# 26. the module's own text agrees with the docs
attempt("the module's text says a site counts a key once between two writes of a process, not once per process", lambda: (lambda src: ("once between two writes of a process" in src and "once per process" not in src, None))((pathlib.Path(STACK) / "stackshot" / "projects" / "keeper_reads.py").read_text(encoding="utf-8")))

# 21. the docs say what is promised and what is not
DOC = (pathlib.Path(STACK) / "docs" / "projects.md").read_text(encoding="utf-8")
attempt("the docs no longer say a stale zero cannot turn up as a newer one", lambda: ("a stale zero cannot turn up as a newer one" not in DOC and "written only if no gauge has been written since it was computed" not in DOC, None))
attempt("the docs name the compare under the lock, the epoch, the bounded retry, and the one stale gauge that is not ruled out", lambda: (all(w in DOC for w in ("epoch", "bounded", "under the lock", "one stale gauge")), None))
attempt("the docs say a zero gauge is evidence only after a gauge written by a process that started after the last deploy", lambda: ("only counts as evidence after a gauge written by a process that started after the last deploy" in DOC, None))
attempt("the docs say a damaged gauge is unknown, never zero", lambda: ("gauge unknown" in DOC and "never zero" in DOC, None))
SRC = (pathlib.Path(STACK) / "stackshot" / "projects" / "keeper_reads.py").read_text(encoding="utf-8")
attempt("the docs say the time of a gauge is never compared between publishers and that the reader compares it with now: old, unreadable or ahead of the clock by more than the tolerance is unknown", lambda: (all(w in DOC for w in ("never compared between publishers", "the reader compares it with now", "ahead of the clock by more than")) and "shown, never compared" not in DOC, None))
attempt("the module text says the same about the time of a gauge", lambda: ("never compared between publishers" in SRC and "the reader compares it with now" in SRC and "for display only and is never compared" not in SRC, None))
attempt("the gauge() text says the retry is outside the file's lock, not every lock", lambda: ("outside the file's lock" in SRC and "outside every lock" not in SRC, None))
attempt("the docs say --json prints the file as it is and is not a gate (the exit status and the report are)", lambda: ("`--json` prints the file as it is" in DOC and "not a gate" in DOC, None))
attempt("the docs say the generation and epoch compare is only as strong as the oldest writer while an older version still writes the file", lambda: ("only as strong as the oldest writer" in DOC and "older version" in DOC, None))
attempt("the docs say a gauge computed more than five minutes ago is unknown, whatever the file's last write says", lambda: ("computed more than five minutes ago" in DOC and "whatever the file's last write says" in DOC, None))
attempt("the docs say the gauge step of a sync is one at a time in a process, within a bound", lambda: ("one at a time" in DOC and "gauge step" in DOC, None))
attempt("the docs say a file has an epoch from the moment it is created", lambda: ("from the moment it is created" in DOC, None))
attempt("the docs say a leftover temporary file older than a minute is swept under the lock", lambda: ("more than a minute old" in DOC and "swept" in DOC, None))
attempt("the docs say a `sync(reg=...)` carries the weaker promise", lambda: ("`sync(reg=...)`" in DOC and "weaker promise" in DOC, None))

# 27. four small findings of the gauge: a refusal in a timer or exit flush is recorded (the file's gauge stays, the report says so), a file made again never matches what a publisher saw as no file, a gauge a caller hands over is checked like the file's,
#     and the report and the exit status read one clock
def t27a():
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot(); other_publishes(["projects/a", "projects/b"])
    with Virt():
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = []     # not due (an unchanged gauge, a recent write): the gauge waits for the timer
        KR.gauge([], base=base); armed = KR._STATE["timer"] is not None; KR._tick()
    rep_ = KR.report()
    line = [l for l in rep_ if "refused" in l and l.startswith("NOT RECORDING?")]
    return armed and legacy().get("keys") == ["projects/a", "projects/b"] and legacy().get("gen") == 2 and re.match(ISO, str(filed().get("refused"))) and len(line) == 1 and line[0].startswith("NOT RECORDING?") and "older rows" in line[0], (armed, legacy(), filed().get("refused"), rep_[:3])
attempt("a gauge refused in the timer's flush (nothing else called it again) leaves the file's gauge as it is and records the refusal, and the report says so, loudly, and that the gauge may be from older rows", t27a)
def refused_timer(older, mine, remove=False):
    """The file holds `older` (another publisher wrote it first, from older rows); this process computed `mine` against the stamp before that, and its timer's flush is refused."""
    fresh_state(); other_publishes(mine); base = KR.snapshot(); other_publishes(older)
    if remove: F.unlink()
    with Virt():
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = sorted(mine)
        KR.gauge(mine, base=base); KR._tick()
    return KR.load()
def t27m():
    d_, p_ = refused_timer([], ["projects/a"]); rc_, out_ = run_main(); rep_ = KR.report()
    return p_ == "" and legacy().get("count") == 0 and re.match(ISO, str(d_.get("refused"))) and KR.count_of(d_, p_) is None and KR.count_of() is None and rc_ == 2 and unknown_line(rep_) and any(l.startswith("NOT RECORDING?") and "refused" in l for l in rep_), (KR.count_of(d_, p_), rc_, rep_[:3])
attempt("a refused timer flush whose file gauge is zero (the other publisher's, maybe the older rows): the gauge reads unknown, never zero, with a loud line, and the status is 2", t27m)
def t27n():
    d_, p_ = refused_timer([], ["projects/a"]); other_publishes(["projects/a"]); d2, p2 = KR.load()
    return "refused" not in d2 and KR.count_of(d2, p2) == 1 and run_main()[0] == 0, (d2, run_main()[0])
attempt("the next gauge written clears the refusal and the gauge reads again", t27n)
def t27o():
    d_, p_ = refused_timer([], ["projects/a"], remove=True); rep_ = KR.report(); loud = [l for l in rep_ if l.startswith("NOT RECORDING?") and "refused" in l]
    return "legacy" not in d_ and re.match(ISO, str(d_.get("refused"))) and KR.count_of(d_, p_) is None and run_main()[0] == 2 and len(loud) == 1 and "no gauge" in loud[0] and "older rows" not in loud[0] and "stays as it is" not in loud[0], (d_, loud)
attempt("a refusal that came from a file removed since is worded for it: there is no gauge in the file (not 'the gauge above stays'), the gauge is unknown and the status is 2", t27o)
def t27p():
    fresh_state(); other_publishes(["projects/x"]); calls = []
    def racing():
        calls.append(1)
        if len(calls) == 1: other_publishes([])                           # another publisher, from older rows, writes a zero while this build runs
        return ROWS_ONE
    PRJ.registry = only_sync(racing)
    try:
        with Virt(): PRJ.sync(path=PUB, force=True)
    finally: PRJ.registry = real_registry
    d_, p_ = KR.load()
    return len(calls) == 2 and legacy().get("keys") == ["projects/legacy-one"] and "refused" not in d_ and KR.count_of(d_, p_) == 1, (len(calls), legacy(), d_.get("refused"))
attempt("a sync whose gauge is refused, and whose second computing gives the same rows: the corrected gauge is written at once (the retry is not held back by the minute between two writes)", t27p)
def t27b():
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot(); other_publishes(["projects/a", "projects/b"])
    with Virt():
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = []
        KR.gauge([], base=base); KR._at_exit()
    first = (re.match(ISO, str(filed().get("refused"))) is not None, legacy().get("keys"))
    reader("q"); KR.flush()
    kept = re.match(ISO, str(filed().get("refused"))) is not None                    # a read flush does not clear it: only a gauge written does
    other_publishes(["projects/c"])
    return first == (True, ["projects/a", "projects/b"]) and kept and "refused" not in filed() and legacy().get("keys") == ["projects/c"], (first, kept, filed())
attempt("a gauge refused at the exit flush is recorded too; a read flush keeps the record and the next gauge written clears it", t27b)
def t27c():
    fresh_state(); reader("q"); KR.flush()
    return "refused" not in filed() and not any("refused" in l for l in KR.report()), (filed(), KR.report()[:3])
attempt("a flush that offers no gauge records no refusal", t27c)
def t27d():
    fresh_state(); other_publishes(["projects/a"]); F.write_text(json.dumps({**filed(), "refused": 5}))
    return KR.load()[1].startswith("unreadable"), KR.load()[1]
attempt("a refusal record that is not a time is damage like any other value of the file", t27d)

# a file that exists never matches what a publisher saw when there was no file
def t27e():
    fresh_state(); base = KR.snapshot()                                                  # no file
    F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {"s <- m.f": {"last": iso(1.0), "keys": ["a"]}}}))       # a file made again with no epoch and no gauge (a previous version's writer)
    with Virt(): KR.gauge([], base=base); KR.flush()
    return base == KR.ABSENT and legacy() == {} and KR.snapshot() != KR.ABSENT, (base, legacy(), KR.snapshot())
attempt("a publisher that snapshotted no file, then a file with no epoch and no gauge appears: no file is not the same stamp as a file without an epoch, so the older zero is refused", t27e)
def t27f():
    fresh_state(); base = KR.snapshot()                                                  # no file: A computes zero
    other_publishes(["projects/x"]); F.unlink()                                          # another process publishes a row, then the file is removed
    reader("r1"); KR.flush()                                                             # and a read flush creates it again
    with Virt(): KR.gauge([], base=base); KR.flush()
    return legacy() == {} and isinstance(filed().get("epoch"), str), (legacy(), filed())
attempt("a publisher snapshots no file and computes zero, another publishes a row, the file is removed and created again by a read flush: the first publisher's zero is refused", t27f)
def t27g():
    fresh_state(); F.write_text(json.dumps({"schema": 1, "since": iso(1.0), "flushed": iso(time.time()), "sites": {}})); base = KR.snapshot(); F.unlink()          # a file without an epoch, then it is removed
    with Virt(): KR.gauge([], base=base); KR.flush()
    return base == (None, 0) and base != KR.ABSENT and legacy() == {}, (base, legacy())
attempt("a publisher that snapshotted a file without an epoch, which is then removed: its gauge is refused, not taken as the first one", t27g)
def t27h():
    fresh_state(); base = KR.snapshot(); F.write_text("{ nope"); s_bad = KR.snapshot()
    with Virt(): KR.gauge(["projects/a"], base=s_bad); KR.flush()
    return base == KR.ABSENT and s_bad == KR.ABSENT and legacy().get("gen") == 1 and legacy().get("keys") == ["projects/a"] and BAD.exists(), (base, s_bad, legacy())
attempt("the first gauge of a file that is missing or damaged is written as generation 1 against the stamp that says no file", t27h)

# a gauge a caller hands to count_of is checked like the file's
def damaged_docs():
    now_ = iso(time.time()); out = []
    for label, doc in SHAPES:
        d_ = json.loads(doc) if isinstance(doc, str) else json.loads(json.dumps(doc))
        if isinstance(d_.get("legacy"), dict) and "at" in d_["legacy"]: d_["legacy"]["at"] = now_
        out.append((label, d_))
    return out
for label, d_ in damaged_docs():
    def t27i(d_=d_):
        return KR.count_of(d_, "") is None, KR.count_of(d_, "")
    attempt(f"a damaged gauge handed to count_of ({label}) is unknown, not zero, even with a current time", t27i)
def t27j():
    ok_ = {"sites": {}, "legacy": {"count": 0, "keys": [], "at": iso(time.time()), "gen": 2}}
    loop_ = {"sites": {}, "legacy": {"count": 0, "keys": [], "at": iso(time.time())}}; loop_["legacy"]["self"] = loop_
    return KR.count_of(ok_, "") == 0 and KR.count_of(loop_, "") is None and KR.count_of({"legacy": "x"}, "") is None and KR.count_of(["x"], "") is None, None
attempt("a well formed gauge handed to count_of reads as itself, and a self-referring or wrongly typed one is unknown, without a raise", t27j)

# one timestamp per report: a gauge at the edge of the bound prints a count and exits 0, or says unknown and exits 2, never one of each
class Ticking:
    def __init__(self, t): self.t = t
    def time(self): self.t += 2.0; return self.t - 2.0                                  # every reading of the clock is two seconds later than the one before
    def monotonic(self): return self.t
def t27k():
    fresh_state(); t0 = time.time(); F.write_text(gauge_file(iso(t0 - KR.GAUGE_STALE + 1.0), flushed=t0)); KR.time = Ticking(t0)
    try: rc_, out_ = run_main()
    finally: KR.time = time
    return rc_ == 0 and "legacy keepers: 0 registry row(s)" in out_, (rc_, out_[:200])
attempt("a gauge just inside the bound, read by a clock that runs on between readings: the report and the exit status agree (one reading of the clock: the count, and status 0)", t27k)
def t27l():
    fresh_state(); t0 = time.time(); F.write_text(gauge_file(iso(t0 - KR.GAUGE_STALE - 1.0), flushed=t0)); KR.time = Ticking(t0)
    try: rc_, out_ = run_main()
    finally: KR.time = time
    return rc_ == 2 and "legacy keepers: gauge unknown" in out_ and "legacy keepers: 0 " not in out_, (rc_, out_[:200])
attempt("a gauge just outside the bound is unknown in both the report and the status", t27l)

# 28. follow-ups of the refusal record: the unknown ends at the next sync, the report words it for every writer and shows a text that is not a time, a record counts by its presence, a document handed to count_of is checked as it stands,
#     and a stale gauge after a refusal is the documented limit, replaced by the next sync
def refusal_in_this_process():
    """A process (a Virt) offers a gauge computed against a stamp another publisher has moved: its timer's flush is refused and the refusal is recorded. Returns with the Virt closed and the file holding the record."""
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot(); other_publishes(["projects/a", "projects/b"])
    with Virt():
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = ["projects/a"]
        KR.gauge(["projects/a"], base=base); KR._tick()
def t28a():
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot(); other_publishes(["projects/a", "projects/b"])
    with Virt():                                                                                 # one process: it records the refusal, and it is the one that publishes next
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = ["projects/a"]
        KR.gauge(["projects/a"], base=base); KR._tick()                                          # the timer's flush is refused and the refusal is recorded
        held = "refused" in filed() and KR.count_of() is None; flag = KR._STATE.get("recorded")
        KR.gauge(["projects/a"])                                                                 # the next sync, the same rows, the minute since its last write not up
        flag_after = KR._STATE.get("recorded")
    return held and flag and "refused" not in filed() and legacy().get("keys") == ["projects/a"] and legacy().get("gen") == 3 and KR.count_of() is not None and not flag_after, (held, flag, filed(), flag_after)
attempt("a refusal this process recorded ends at its next gauge, written at once even with the same rows and the minute not up (the unknown ends at the next sync, not a minute after it)", t28a)
def t28b():
    fresh_state(); other_publishes(["projects/a"]); base = KR.snapshot(); other_publishes(["projects/a", "projects/b"])
    with Virt():
        KR._STATE["gauge"] = None
        KR.gauge(["projects/a"], base=base, again=lambda: None)              # refused, and there is nothing to compute again from
        flag = KR._STATE["recorded"]; held = "refused" in filed()
        KR.gauge(["projects/a"], again=lambda: None)                         # the next sync, the same rows, the minute not up
        flag_after = KR._STATE["recorded"]
    return flag and held and "refused" not in filed() and legacy().get("keys") == ["projects/a"] and not flag_after, (flag, held, filed(), flag_after)
attempt("a sync whose gauge was refused and had no registry to compute again from: the record stands until the next sync's gauge, which is written at once and clears it", t28b)
def t28c():
    refusal_in_this_process(); rep_ = KR.report(); loud = [l for l in rep_ if l.startswith("NOT RECORDING?") and "refused" in l]
    return len(loud) == 1 and "an earlier flush (possibly this process's, possibly another's)" in loud[0] and "could not compute the rows again" in loud[0] and "other publisher" not in loud[0] and "at the end of a process or from the timer" not in loud[0], loud
attempt("the report words a refusal for every writer: an earlier flush that may be this process's own, and any flush that could not compute the rows again (not only a timer or exit flush)", t28c)
def t28d():
    out = []
    for text, want in (("yesterday", '"yesterday" (not a time)'), ("a" * 100 + "\nsecond line", '"' + "a" * 40 + '..." (not a time)'), ("\x1b[31mred\x1b[0m\r\nx", '"[31mred[0m x" (not a time)')):
        fresh_state(); other_publishes(["projects/a"]); F.write_text(json.dumps({**filed(), "refused": text})); d_, p_ = KR.load()
        rep_ = KR.report(); loud = [l for l in rep_ if l.startswith("NOT RECORDING?") and "refused" in l]
        out.append(p_ == "" and KR.count_of(d_, p_) is None and run_main()[0] == 2 and len(loud) == 1 and want in loud[0] and "offered ?" not in loud[0] and "\n" not in loud[0] and "\x1b" not in loud[0] and unknown_line(rep_))
        other_publishes(["projects/a"]); out.append("refused" not in filed() and KR.count_of() == 1)             # the next gauge written clears it
    return all(out), (out, loud)
attempt("a refusal record that is a string but not a time is printed as it stands (one line, cut, no control characters), the gauge is unknown, the status is 2, and the next gauge clears it", t28d)
def t28e():
    fresh_state(); other_publishes(["projects/a"]); F.write_text(json.dumps({**filed(), "refused": ""})); d_, p_ = KR.load()
    rep_ = KR.report(); rc_ = run_main()[0]; loud = [l for l in rep_ if l.startswith("NOT RECORDING?") and "refused" in l]
    first = (p_ == "" and KR.count_of(d_, p_) is None and KR.count_of() is None and rc_ == 2 and len(loud) == 1 and unknown_line(rep_))
    reader("q"); KR.flush(); kept = filed().get("refused") == ""                                    # a read flush keeps the record
    other_publishes(["projects/a"])
    return first and kept and "refused" not in filed() and KR.count_of() == 1 and run_main()[0] == 0, (first, kept, filed())
attempt("an empty refusal record is a record: the gauge is unknown, the status is 2, a read flush keeps it, and the next gauge written clears it", t28e)
def good_doc(**over):
    return {"sites": {}, "legacy": {"count": 0, "keys": [], "at": iso(time.time()), "gen": 1, "epoch": "e1"}, **over}
def with_legacy(**over):
    d_ = good_doc(); d_["legacy"] = {**d_["legacy"], **over}; return d_
def t28f():
    cases = {"a tuple of keys in the gauge": with_legacy(count=1, keys=("projects/a",)),
             "a tuple of keys in a site": good_doc(sites={"s <- m.f": {"last": iso(1.0), "keys": ("a",)}}),
             "a tuple of sites": good_doc(sites=({"last": iso(1.0), "keys": []},)),
             "a site name that is not a string": good_doc(sites={1: {"last": iso(1.0), "keys": []}}),
             "a key that is not a string at the top": {**good_doc(), 7: "x"},
             "a key that is not a string in the gauge": (lambda d_: (d_["legacy"].__setitem__(5, "x"), d_)[1])(good_doc()),
             "a set in an extra field": good_doc(extra={"a"}),
             "a tuple in an extra field": good_doc(extra=("a",)),
             "a count of 0.0": with_legacy(count=0.0),
             "a count of True": with_legacy(count=True),
             "a count of False": with_legacy(count=False)}
    got = {k: KR.count_of(v, "") for k, v in cases.items()}
    return all(v is None for v in got.values()) and KR.count_of(good_doc(), "") == 0 and KR.count_of(with_legacy(count=1, keys=["projects/a"]), "") == 1, got
attempt("a document handed to count_of is checked as it stands, not as JSON would convert it: a tuple, a set, a key that is not a string, a float or a boolean count is unknown, never zero (a good one still reads)", t28f)
def t28g():
    fresh_state(); other_publishes([]); base_a = KR.snapshot()                       # the file holds a zero; publisher A reads it, then computes rows that hold a legacy row
    other_publishes([])                                                              # another publisher, from older rows, writes a zero (the next generation)
    with Virt():                                                                     # A's flush is the timer's: refused, and the refusal is recorded; the stamp stays
        KR._STATE["flushed"] = 1e12; KR._STATE["gauge"] = ["projects/new"]
        KR.gauge(["projects/new"], base=base_a); KR._tick()
    after_refusal = ("refused" in filed(), KR.count_of(), KR.snapshot()[1])
    with Virt(): KR.gauge([], base=base_a); KR.flush()                               # publisher B took its snapshot before the refusal (as the rule says, before its rows): refused too
    still = ("refused" in filed(), KR.count_of(), KR.snapshot()[1])
    with Virt(): KR.gauge([], base=KR.snapshot()); KR.flush()                        # publisher C computed its rows before the row appeared and took its snapshot only now (the documented limit): accepted
    stale = (KR.count_of(), legacy().get("gen"), "refused" in filed())
    with Virt(): KR.gauge(["projects/new"], base=KR.snapshot()); KR.flush()          # the next sync, from the live registry
    replaced = (KR.count_of(), legacy().get("keys"), "refused" in filed(), run_main()[0])
    return after_refusal == (True, None, 2) and still == (True, None, 2) and stale == (0, 3, False) and replaced == (1, ["projects/new"], False, 0), (after_refusal, still, stale, replaced)
attempt("a refusal leaves the stamp as it is: a publisher that snapshotted before it is refused, one that snapshotted after it (its rows older) is accepted (the documented single stale gauge), and the next sync replaces that gauge", t28g)
attempt("the docs say a stale gauge can follow a refusal too, that a later stage recomputes the legacy rows from the live record instead of trusting the gauge, and that a gauge handed to count_of is checked as it stands",
        lambda: (all(w in DOC for w in ("A refusal on record does not change this", "recomputes the legacy rows from the live record", "a tuple, a set or a key that is not a string")), None))
attempt("the docs say any flush of an older version drops the record, a refusal for any flush that could not compute the rows again, the unknown ends at the next sync, and a text that is not a time is printed as it is",
        lambda: (all(w in DOC for w in ("any flush of an older version", "a flush that could not compute the rows again", "so the unknown ends at the next sync", "cut to 40 characters", "an empty string included")) and "a read flush of an older version" not in DOC, None))
attempt("the module's text says the publisher syncs about once a minute from the end of a round, not every 20 seconds", lambda: ("about every 20 seconds" not in SRC and "about once a minute, counted from the end of a round" in SRC, None))
attempt("the docs say a refused gauge in a timer or exit flush is recorded, and that a file made again never matches no file", lambda: ("refused" in DOC and "a timer or exit flush" in DOC and "never matches" in DOC, None))
fresh_state()
KR._after = real_after

from stackshot import cli
check("the program is registered under `stackshot keeper-reads`", cli.PROGRAMS.get("keeper-reads", ("",))[0] == "stackshot.projects.keeper_reads")

if fails: print(f"FAILED: keeper reads scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper reads scenario, {len(ran)} checks")
