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
KR.gauge(["projects/a", "projects/b"])
for i in range(5): reader(f"k{i}")
caller("z"); KR.flush()
rep = KR.report()
check("the report: the gauge, then the sites with the most keys first, each with its last read and key count", rep[0].startswith("legacy keepers: 2 registry row(s)") and "projects/a, projects/b" in rep[0] and rep[1].startswith("removal-candidate readers, since ")
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
F.unlink(missing_ok=True); (T / "state" / "keeper-reads.json.lock").unlink(missing_ok=True)
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

from stackshot import cli
check("the program is registered under `stackshot keeper-reads`", cli.PROGRAMS.get("keeper-reads", ("",))[0] == "stackshot.projects.keeper_reads")

if fails: print(f"FAILED: keeper reads scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper reads scenario, {len(ran)} checks")
