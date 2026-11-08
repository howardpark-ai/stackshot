"""Scenario test for the suites' scratch folders — no server, no network.

A suite's folders are locked while it runs and removed when it ends, however it ends. Covers:
  * tests/_scratch.py, run in a child process with a TMPDIR of its own: the folder is gone after a normal end, sys.exit, an
    exception, os._exit, SIGTERM and SIGHUP; a forked child's exit leaves its parent's folder alone; a tracked file is removed;
    KEEP_SCRATCH=1 keeps the folder and names it on stderr
  * tests/run-suite, copied beside two throwaway suites: a suite that leaks a plain tempfile.mkdtemp, one that fails after
    making a folder, and one that leaves a file from a subprocess, leave nothing in the caller's TMPDIR (uv's own lock file
    aside); KEEP_SCRATCH=1 keeps the run's folder
  * three real suites, run through tests/run-suite and straight with python (no run-suite): nothing is left in TMPDIR;
    the migration suite (its migr-run-* folders) straight with python: nothing left either
  * no suite makes a temp folder or file by any other way than _scratch, or names a /tmp path

    tests/run-suite scratch        → exit 0 / 1"""
import json, os, pathlib, re, shutil, signal, subprocess, sys, tempfile, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="scratchtest-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:600]}")

def left(d):
    """what is in a TMPDIR after a run, uv's own lock file (one per project path, kept on purpose) aside"""
    return sorted(p.name for p in pathlib.Path(d).iterdir() if not re.fullmatch(r"uv-[0-9a-f]+\.lock", p.name))

def fresh(name):
    d = T / name; d.mkdir(); return d

# ---- 1. the helper, in a child process
def child(name, body, pre="", **env):
    """run `body` after `pre`, `import _scratch; d = _scratch.mkdtemp('x-')` in a child with a TMPDIR of its own; (rc, what is left, stderr)"""
    td = fresh(f"h-{name}")
    src = T / f"{name}.py"
    src.write_text(f"import os, sys, signal, tempfile\nsys.path.insert(0, {SCR!r})\n{pre}\nimport _scratch\n"
                   f"d = _scratch.mkdtemp('x-'); open(os.path.join(d, 'f'), 'w').write('x'); os.makedirs(os.path.join(d, 'sub/deeper'))\n{body}\n")
    e = {k: v for k, v in os.environ.items() if k not in ("KEEP_SCRATCH", "TMPDIR") and not k.startswith("COVERAGE_")}   # a measured run's own coverage stays out
    e.update(TMPDIR=str(td), **env)
    p = subprocess.run([sys.executable, str(src)], env=e, capture_output=True, text=True, timeout=60)
    return p.returncode, left(td), p.stderr

rc, l, _ = child("normal", "")
check("helper: a normal end removes the folder", rc == 0 and l == [], (rc, l))
rc, l, _ = child("exit1", "sys.exit(1)")
check("helper: sys.exit(1) removes it, the exit status stays", rc == 1 and l == [], (rc, l))
rc, l, err = child("raise", "raise RuntimeError('boom')")
check("helper: an exception removes it", rc == 1 and l == [] and "boom" in err, (rc, l, err[-200:]))
rc, l, _ = child("osexit", "os._exit(3)")
check("helper: os._exit (how the suites end) removes it, the status stays", rc == 3 and l == [], (rc, l))
rc, l, _ = child("term", "os.kill(os.getpid(), signal.SIGTERM); import time; time.sleep(5)")
check("helper: SIGTERM removes it and the process still ends by the signal", rc == -signal.SIGTERM and l == [], (rc, l))
rc, l, err = child("term-cov", "os.kill(os.getpid(), signal.SIGTERM); import time; time.sleep(5)",
                   pre=f"import coverage; _c = coverage.Coverage(data_file={str(T / 'cov.data')!r}, config_file=False); _c.set_option('run:sigterm', True); _c.start()")
check("helper: SIGTERM with coverage.py's handler in place (a measured run, sigterm = true): removed, coverage saves, still ends by the signal",
      rc == -signal.SIGTERM and l == [] and any(p.name.startswith("cov.data") for p in T.iterdir()), (rc, l, err[-300:]))
rc, l, _ = child("hup", "os.kill(os.getpid(), signal.SIGHUP); import time; time.sleep(5)")
check("helper: SIGHUP removes it", rc == -signal.SIGHUP and l == [], (rc, l))
td = fresh("h-forkcheck")
src = T / "forkcheck.py"
src.write_text(f"import os, sys\nsys.path.insert(0, {SCR!r})\nimport _scratch\nd = _scratch.mkdtemp('x-')\npid = os.fork()\n"
               f"if pid == 0: os._exit(0)\nos.waitpid(pid, 0)\nprint(os.path.isdir(d))\n")
p = subprocess.run([sys.executable, str(src)], env={**os.environ, "TMPDIR": str(td)}, capture_output=True, text=True, timeout=60)
check("helper: a forked child's exit leaves its parent's folder in place, and the parent removes it at its own end", p.stdout.strip() == "True" and left(td) == [], (p.stdout, left(td)))
rc, l, _ = child("track", "f2 = os.path.join(tempfile.gettempdir(), 'tracked-file'); open(f2, 'w').write('x'); _scratch.track(f2)\n"
                         "d2 = os.path.join(tempfile.gettempdir(), 'tracked-dir'); os.makedirs(d2 + '/a'); _scratch.track(d2)")
check("helper: track() removes a file and a folder made some other way", rc == 0 and l == [], (rc, l))
rc, l, err = child("keep", "", KEEP_SCRATCH="1")
check("helper: KEEP_SCRATCH=1 keeps the folder and names it on stderr", rc == 0 and len(l) == 1 and f"scratch kept: " in err and l[0] in err, (rc, l, err))
rc, l, _ = child("keep0", "", KEEP_SCRATCH="0")
check("helper: KEEP_SCRATCH=0 is no opt-out", rc == 0 and l == [], (rc, l))
rc, l, _ = child("keepclosed", "sys.stderr.close(); os._exit(7)", KEEP_SCRATCH="1")
check("helper: KEEP_SCRATCH=1 with a closed stderr still ends with the given status", rc == 7 and len(l) == 1, (rc, l))
rc, l, _ = child("keepclosed2", "sys.stderr.close(); sys.exit(7)", KEEP_SCRATCH="1")
check("helper: …also through sys.exit", rc == 7 and len(l) == 1, (rc, l))
rc, l, _ = child("daemon", """import threading, shutil
go = threading.Event(); done = threading.Event()
def w():                       # a daemon thread of the suite that writes into the folder just after the first removal pass
    go.wait(); os.makedirs(os.path.join(d, 'late'), exist_ok=True); open(os.path.join(d, 'late', 'f'), 'w').close(); done.set()
threading.Thread(target=w, daemon=True).start()
real = shutil.rmtree; n = [0]
def rm(p, ignore_errors=False):
    real(p, ignore_errors=True); n[0] += 1
    if n[0] == 1: go.set(); done.wait(5)
shutil.rmtree = rm""")
check("helper: a daemon thread writing into the folder while it is removed does not keep it", rc == 0 and l == [], (rc, l))
rc, l, _ = child("relative", "os.chdir(tempfile.gettempdir()); os.makedirs('rel-dir/a'); _scratch.track('rel-dir'); os.chdir('/')")
check("helper: track() of a relative path removes it after a chdir", rc == 0 and l == [], (rc, l))

# ---- 2. run-suite, beside throwaway suites (the same shared test environment, the same lock)
RS = T / "rs"; (RS / "tests").mkdir(parents=True)
for f in ("run-suite", "_scratch.py"):
    shutil.copy(os.path.join(SCR, f), RS / "tests" / f)
for f in ("pyproject.toml", "uv.lock"):   # the one project is at the checkout's root: run-suite looks for it beside its own folder
    shutil.copy(os.path.join(STACK, f), RS / f)
(RS / "tests" / "leak_scenario.py").write_text(
    "import tempfile, os\nd = tempfile.mkdtemp(prefix='leaked-'); open(os.path.join(d, 'f'), 'w').write('x')\n"
    "open(os.path.join(tempfile.gettempdir(), 'loose-file'), 'w').write('x')\nprint('ok: leak')\n")
(RS / "tests" / "fail_scenario.py").write_text(
    "import sys, os\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport _scratch\n"
    "d = _scratch.mkdtemp('failing-'); open(os.path.join(d, 'f'), 'w').write('x')\nraise SystemExit('FAILED: a check failed')\n")
(RS / "tests" / "sub_scenario.py").write_text(
    "import subprocess, sys, tempfile\nsubprocess.run([sys.executable, '-c', 'import tempfile, os; d = tempfile.mkdtemp(); "
    "open(os.path.join(d, \"f\"), \"w\").write(\"x\")'], check=True)\nprint('ok: sub')\n")
def runsuite(name, tmpdir, rs=None, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("KEEP_SCRATCH", "TMPDIR")}
    e.update(TMPDIR=str(tmpdir), **env)
    p = subprocess.run([str(rs or RS / "tests" / "run-suite"), name], env=e, capture_output=True, text=True, timeout=300, cwd=str(RS))
    return p.returncode, left(tmpdir), p.stdout + p.stderr
td = fresh("r-leak"); rc, l, out = runsuite("leak", td)
check("run-suite: a suite that leaks a plain tempfile.mkdtemp and a loose file leaves nothing", rc == 0 and l == [], (rc, l, out[-300:]))
td = fresh("r-fail"); rc, l, out = runsuite("fail", td)
check("run-suite: a failing suite leaves nothing, and run-suite exits with its status", rc == 1 and l == [] and "a check failed" in out, (rc, l, out[-300:]))
td = fresh("r-sub"); rc, l, out = runsuite("sub", td)
check("run-suite: what a subprocess of the suite left is removed too", rc == 0 and l == [], (rc, l, out[-300:]))
td = fresh("r-keep"); rc, l, out = runsuite("leak", td, KEEP_SCRATCH="1")
check("run-suite: KEEP_SCRATCH=1 keeps the run's folder (with the leak in it) and names it", rc == 0 and len(l) == 1 and l[0].startswith("rs.") and "scratch kept" in out, (rc, l, out[-300:]))
td = fresh("r-nosuite"); rc, l, out = runsuite("nonesuch", td)
check("run-suite: an unknown suite is refused before any folder is made", rc == 2 and l == [], (rc, l, out[-200:]))
(RS / "tests" / "sleepy_scenario.py").write_text(
    "import sys, os, time\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport _scratch\n"
    "d = _scratch.mkdtemp('sleepy-'); open(os.path.join(d, 'f'), 'w').write('x')\n"
    "open(os.path.join(os.environ['TMPDIR'], 'loose-file'), 'w').write('x')\nprint('started', flush=True); time.sleep(60)\n")
def sleepy(td, argv0=()):
    e = {k: v for k, v in os.environ.items() if k not in ("KEEP_SCRATCH", "TMPDIR")}; e["TMPDIR"] = str(td)
    p = subprocess.Popen([*argv0, str(RS / "tests" / "run-suite"), "sleepy"], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(RS))
    return p, p.stdout.readline()          # blocks until the suite says it is running
for sig, label in ((signal.SIGTERM, "TERM"), (signal.SIGHUP, "HUP")):
    td = fresh(f"r-sleepy-{label}"); p, first = sleepy(td)
    t0 = time.time(); p.send_signal(sig)       # to run-suite's pid alone
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    took = time.time() - t0
    check(f"run-suite: a {label} to its pid alone stops a sleeping suite within 2 s, with status 143 and nothing left", first.strip() == "started" and took < 2 and p.returncode == 143 and left(td) == [], (first, round(took, 2), p.returncode, left(td)))
    p.stdout.close()
td = fresh("r-sleepy-int"); t0 = time.time()
p, first = sleepy(td, ("timeout", "-s", "INT", "2"))
out = first + p.stdout.read(); p.wait(); p.stdout.close()
check("run-suite: `timeout -s INT` still gives the suite a KeyboardInterrupt (the traceback of where it sat), ends in time and leaves nothing",
      p.returncode == 124 and "KeyboardInterrupt" in out and time.time() - t0 < 20 and left(td) == [], (p.returncode, out[-300:], left(td)))

# ---- 2b. locks: systemd-tmpfiles skips a folder that holds a BSD lock (tmpfiles.d(5)), so a running suite's folders hold one
def is_locked(path):
    """True when someone holds a lock on `path` that stops an exclusive one (`flock -n <dir> true` fails)"""
    return subprocess.run(["flock", "-n", str(path), "true"], capture_output=True).returncode != 0

td = fresh("lock-run"); src = T / "lockrun.py"
src.write_text(f"import os, sys, time\nsys.path.insert(0, {SCR!r})\nimport _scratch\nd = _scratch.mkdtemp('x-')\nprint(d, flush=True); time.sleep(60)\n")
p = subprocess.Popen([sys.executable, str(src)], env={**os.environ, "TMPDIR": str(td)}, stdout=subprocess.PIPE, text=True)
d = p.stdout.readline().strip()
free_before = not is_locked(fresh("lock-probe"))        # a folder nobody holds is not locked: the probe itself works
check("lock: while a suite runs, flock -n on its folder fails", d != "" and is_locked(d) and free_before, (d, free_before))
p.kill(); p.wait(); p.stdout.close()
check("lock: after a crash (SIGKILL) the folder is left and its lock is gone", os.path.isdir(d) and not is_locked(d), (d, os.path.isdir(d)))
td = fresh("lock-end"); rc, l, _ = child("lockend", "print(d)")
check("lock: after a normal end the folder is gone", rc == 0 and l == [], (rc, l))

td = fresh("lock-child"); src = T / "lockchild.py"; ready = T / "lockchild.ready"
# the forked child marks that it runs, so its fork handler has closed the lock before the suite ends: under strace -f a new child
# waits for strace to let it go, and on a busy box the check below came first
src.write_text(f"import os, pathlib, subprocess, sys, time\nsys.path.insert(0, {SCR!r})\nimport _scratch\nd = _scratch.mkdtemp('x-')\n"
               "ex = subprocess.Popen(['sleep', '60'])\npid = os.fork()\n"
               f"if pid == 0:\n    pathlib.Path({str(ready)!r}).touch(); time.sleep(60); os._exit(0)\n"
               f"end = time.time() + 30\nwhile not os.path.exists({str(ready)!r}) and time.time() < end: time.sleep(0.01)\n"
               "print(d, ex.pid, pid, flush=True)\n")
outf = T / "lockchild.out"      # to a file: a pipe would stay open for as long as the children do
with open(outf, "w") as fo:
    p = subprocess.run([sys.executable, str(src)], env={**os.environ, "TMPDIR": str(td), "KEEP_SCRATCH": "1"}, stdout=fo, stderr=subprocess.STDOUT, text=True, timeout=60)
p.stdout = outf.read_text(); p.stderr = ""
d, *pids = p.stdout.split()[:3]
alive = [q for q in pids if os.path.exists(f"/proc/{q}")]
check("lock: a child process (exec'd, or forked) that outlives the suite does not keep the folder locked",
      p.returncode == 0 and len(alive) == 2 and os.path.isdir(d) and not is_locked(d), (p.returncode, p.stdout, alive, p.stderr[-200:]))
for q in pids: os.kill(int(q), signal.SIGKILL)

td = fresh("lock-rs"); p, first = sleepy(td)
rs = [x for x in td.iterdir() if x.name.startswith("rs.")]
inner = [x for x in rs[0].iterdir() if x.name.startswith("sleepy-")] if rs else []
check("lock: while a suite runs through run-suite, flock -n fails on run-suite's folder and on the suite's own",
      first.strip() == "started" and len(rs) == 1 and is_locked(rs[0]) and len(inner) == 1 and is_locked(inner[0]), (first, rs, inner))
p.send_signal(signal.SIGTERM); p.wait(timeout=10); p.stdout.close()
check("lock: run-suite's folder is gone after the suite ends", left(td) == [], left(td))

# ---- 3. real suites: nothing left, through run-suite and with python alone (no run-suite)
for name in ("rename", "redact", "lead"):
    td = fresh(f"real-{name}"); rc, l, out = runsuite(name, td, rs=pathlib.Path(SCR) / "run-suite")
    check(f"real suite {name} through run-suite: passes, leaves nothing in TMPDIR", rc == 0 and l == [], (rc, l, out[-300:]))
    td = fresh(f"direct-{name}")
    e = {k: v for k, v in os.environ.items() if k not in ("KEEP_SCRATCH", "TMPDIR")}; e["TMPDIR"] = str(td)
    p = subprocess.run([sys.executable, os.path.join(SCR, f"{name}_scenario.py")], env=e, capture_output=True, text=True, timeout=300, cwd=STACK)
    check(f"real suite {name} with python alone: passes, leaves nothing in TMPDIR", p.returncode == 0 and left(td) == [], (p.returncode, left(td), p.stdout[-300:], p.stderr[-300:]))

# the migration suite makes its run folders (migr-run-*, with a wake-ledger.json each) and copies of its fixture; before it made
# them with tempfile.mkdtemp and never removed the three run folders (many of them sat in /tmp). With python alone, so that
# run-suite's own TMPDIR clean-up cannot hide a leak: nothing may be left in TMPDIR, and a folder made anywhere else (a bare /tmp)
# is caught by the source check of the next check and of section 4.
td = fresh("direct-migration")
e = {k: v for k, v in os.environ.items() if k not in ("KEEP_SCRATCH", "TMPDIR")}; e["TMPDIR"] = str(td)
p = subprocess.run([sys.executable, os.path.join(SCR, "migration_scenario.py")], env=e, capture_output=True, text=True, timeout=300, cwd=STACK)
check("real suite migration with python alone: passes, and leaves nothing in TMPDIR (its migr-run-* folders included)", p.returncode == 0 and left(td) == [], (p.returncode, left(td), p.stdout[-300:], p.stderr[-300:]))
src_m = (pathlib.Path(SCR) / "migration_scenario.py").read_text(encoding="utf-8")
check("migration suite: its three migr-run-* folders are made by _scratch.mkdtemp, none by tempfile",
      len(re.findall(r'_scratch\.mkdtemp\(prefix="migr-run-"', src_m)) == 3 and 'tempfile.mkdtemp(prefix="migr-run-"' not in src_m)

# ---- 4. no suite goes round _scratch
bad = []
for f in sorted(pathlib.Path(SCR).glob("*.py")):
    if f.name in ("_scratch.py", "scratch_scenario.py"):
        continue
    for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
        code = line
        if re.search(r"\btempfile\.(mkdtemp|mkstemp|NamedTemporaryFile|TemporaryFile|SpooledTemporaryFile)\(", code) and f.name != "suitemap.py":
            bad.append(f"{f.name}:{n}: {line.strip()[:100]}")
        if re.search(r"""["']/tmp(/|["'])""", code) and "resolve = lambda name: \"/tmp/sock\"" not in code and "two-users" not in f.name:
            bad.append(f"{f.name}:{n}: {line.strip()[:100]}")
check("no suite makes a temp folder or file except through _scratch, or names a /tmp path", not bad, bad)
sh = [l for l in (pathlib.Path(SCR) / "run-suite").read_text().split("\n") if "mktemp" in l]
check("run-suite makes its folder under ${TMPDIR:-/tmp}, never a bare /tmp path", len(sh) == 1 and '"${TMPDIR:-/tmp}/' in sh[0], sh)

print(("ok" if not fails else "FAILED") + f": scratch scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
