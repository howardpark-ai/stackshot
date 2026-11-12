"""tests/test_trim_report_scenario.py - the weekly test-suite size report (tools/test_trim_report.py).

Checked on a fake repository built in a scratch folder (a few suites with known numbers of check lines, a suite map with known times),
with HOME and the XDG folders pointed into the scratch folder, a fake `gh` on PATH for --fetch, and no network:

  1  the measure: which lines count as test lines (check(, ck(, assert, self.assert...; not a comment, a def, or another call)
  2  the first run: counts, serial minutes from the map, the slowest 8 in order (ten suites, so the cut is seen), the machine record in the
     state file at the default XDG place, no temporary file left beside it
  3  the second run: suites added and deleted by name, test lines added and deleted per suite, the record replaced; --dry-run writes nothing
  4  thresholds: the placeholders never trigger; each of the four keys triggers on its own with a TRIGGER line, exit 0, the lines kept in the
     state file; a [repo] table overrides the top-level key; growth is scaled down to a week for a gap longer than a week
  5  no suite times: a missing or damaged map gives n/a and a note and no minute trigger; --fetch downloads the artifact into a folder it
     removes again, and a failing gh gives n/a with the reason
  6  errors: an unwritable state folder is a clear message and a nonzero status with nothing printed on stdout; a bad config value, a missing
     explicit config and a checkout with no suites are status 2; a damaged previous record is started over with a note
  7  read-only: the fake repository is byte for byte as it was, and nothing outside the state folder is written

    tests/run-suite test_trim_report        -> exit 0 / 1"""
import hashlib, json, os, pathlib, stat, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
sys.path.insert(0, os.path.join(STACK, "tools"))
import test_trim_report as TR

tmp = _scratch.mkdtemp(prefix="trimreport-"); T = pathlib.Path(tmp)
TOOL = os.path.join(STACK, "tools", "test_trim_report.py")
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


# ------------------------------------------------------------------ 1 the measure
SAMPLE = '''import x
check("a", 1)
    ck("b", 2)
assert x
    assert y, "why"
self.assertEqual(1, 1)
# check("comment")
def check(name, cond):
    pass
x = check("assigned", 1)
print("check(")
assertion = 3
check_other(1)
'''
check("count_test_lines: check(, ck(, assert and self.assert lines only", TR.count_test_lines(SAMPLE) == 5, TR.count_test_lines(SAMPLE))

# ------------------------------------------------------------------ the fake repository
REPO = T / "work" / "fakerepo"
(REPO / "tests").mkdir(parents=True)
HOME = T / "home"; HOME.mkdir()
GH_BIN = T / "bin"; GH_BIN.mkdir()


def suite(name, n):
    (REPO / "tests" / f"{name}_scenario.py").write_text("import os\n" + "".join(f'check("c{i}", {i} == {i})\n' for i in range(n)) + "# check(\"not counted\")\n")


SUITES = {f"s{i:02d}": 3 + i for i in range(1, 11)}      # s01 .. s10 with 4 .. 13 check lines
for n, c in SUITES.items():
    suite(n, c)
(REPO / "tests" / "suitemap.py").write_text("# a tool, not a suite\ncheck('x', 1)\n")      # not a *_scenario.py: not a suite
(REPO / "tests" / "browser_check.py").write_text("check('x', 1)\n")                       # a manual check: not a suite
SECONDS = {n: 30.0 * (i + 1) for i, n in enumerate(sorted(SUITES))}                       # s01 30 s .. s10 300 s; total 1650 s = 27.5 min
SECONDS["gone_long_ago"] = 9999.0                                                          # a suite the checkout no longer has: not counted
MAP = T / "map.json"
MAP.write_text(json.dumps({"format": 1, "commit": "a" * 40, "strace": False, "suites": {n: {"ok": True, "seconds": s, "py": {}} for n, s in SECONDS.items()}}))
STATE = HOME / ".local" / "state" / "stackshot" / "test-trim"
CONF = T / "trim.toml"


def tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(path).rglob("*")):
        h.update(str(p.relative_to(path)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def run(*args, now="2026-01-05T09:00:00+00:00", env=None, cwd=REPO, home=HOME):
    e = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": tmp, "LANG": "C.UTF-8"}
    e.update(env or {})
    r = subprocess.run([sys.executable, TOOL, *(["--now", now] if now else []), *args], capture_output=True, text=True, env=e, cwd=cwd, timeout=120)
    return r


def record():
    return json.loads((STATE / "fakerepo.json").read_text())


real_state = pathlib.Path(os.path.expanduser("~/.local/state/stackshot/test-trim"))
real_before = (real_state.exists(), sorted(p.name for p in real_state.glob("*")) if real_state.exists() else [])

# ------------------------------------------------------------------ 2 the first run
r = run("--map", str(MAP))
check("first run: exit 0", r.returncode == 0, r.stderr)
out = r.stdout
check("first run: header and suite count (the tool, the manual check and the helper are no suites)", "test-trim report: fakerepo" in out and "suites: 10\n" in out, out)
total_lines = sum(SUITES.values())
check("first run: test lines are the sum of the check lines", f"test lines: {total_lines:,}" in out, out)
check("first run: serial minutes count only suites the checkout has", "serial minutes: 27.5 (10 of 10 suites timed)" in out, out)
slow = [l.strip() for l in out.splitlines() if l.startswith("  ") and ". s" in l]
check("first run: the slowest 8, slowest first", [l.split()[1] for l in slow] == ["s10", "s09", "s08", "s07", "s06", "s05", "s04", "s03"], slow)
check("first run: the slowest are shown with minutes", slow and slow[0].endswith("5.0 min") and slow[-1].endswith("1.5 min"), slow)
check("first run: the baseline is said", "this run is the baseline" in out, out)
check("first run: no trigger with the placeholders", "TRIGGER" not in out and "Follow-up" not in out, out)
rec = record()
check("first run: the record is at the default XDG place and holds the counts", rec["suite_count"] == 10 and rec["test_lines"] == total_lines and rec["serial_minutes"] == 27.5 and rec["format"] == 1, rec)
check("first run: the record keeps per-suite lines and the slowest 8", rec["suites"]["s03"] == 6 and len(rec["slowest"]) == 8 and rec["triggers"] == [], rec)
check("first run: the map's commit is kept", rec["map_commit"] == "a" * 40, rec.get("map_commit"))
check("first run: no temporary file is left beside the record", sorted(p.name for p in STATE.iterdir()) == ["fakerepo.json"], list(STATE.iterdir()))

# ------------------------------------------------------------------ 3 the second run
suite("s03", 20)               # 6 -> 20 lines: +14
suite("s05", 4)                # 8 -> 4 lines: -4
suite("n01", 7); suite("n02", 2)
(REPO / "tests" / "s10_scenario.py").unlink()    # 13 lines deleted
before_rec = (STATE / "fakerepo.json").read_bytes()
r = run("--map", str(MAP), "--dry-run", now="2026-01-12T09:00:00+00:00")
check("dry run: exit 0 and the record is untouched", r.returncode == 0 and (STATE / "fakerepo.json").read_bytes() == before_rec, r.stderr)
check("dry run: reports against the previous run", "7.0 days ago" in r.stdout, r.stdout)
r = run("--map", str(MAP), now="2026-01-12T09:00:00+00:00")
out = r.stdout
check("second run: exit 0", r.returncode == 0, r.stderr)
check("second run: suites added and deleted", "2 suites added, 1 deleted" in out and "added: n01, n02" in out and "deleted: s10" in out, out)
up, down = 7 + 2 + 14, 13 + 4
check("second run: test lines added and deleted", f"{up} test lines added, {down} deleted (net +{up - down})" in out, out)
check("second run: the days since the previous run", "(7.0 days ago)" in out, out)
rec2 = record()
check("second run: the record replaced the first", rec2["suite_count"] == 11 and rec2["added_suites"] == ["n01", "n02"] and rec2["deleted_suites"] == ["s10"] and rec2["tests_added"] == up and rec2["tests_deleted"] == down, rec2)
check("second run: n01 and n02 have no time, so they are untimed", "untimed" in out and "(9 of 11 suites timed, 2 untimed)" in out, out)
check("second run: still one file in the state folder", sorted(p.name for p in STATE.iterdir()) == ["fakerepo.json"], list(STATE.iterdir()))

# ------------------------------------------------------------------ 4 thresholds
base = ["--map", str(MAP), "--state-dir", str(T / "st4"), "--config", str(CONF)]


def with_conf(text, *args, now="2026-01-05T09:00:00+00:00"):
    CONF.write_text(text)
    return run(*base, *args, now=now)


r = with_conf("")
check("thresholds: the placeholders do not trigger", r.returncode == 0 and "TRIGGER" not in r.stdout, r.stdout + r.stderr)
r = with_conf("max_suites = 5\n")
check("trigger: max_suites, exit 0, follow-up named", r.returncode == 0 and "TRIGGER: max_suites: 11 suites > 5" in r.stdout and "deep scan" in r.stdout, r.stdout + r.stderr)
check("trigger: the state file keeps the line", [t["key"] for t in json.loads((T / "st4" / "fakerepo.json").read_text())["triggers"]] == ["max_suites"]
      and json.loads((T / "st4" / "fakerepo.json").read_text())["triggers"][0]["line"] == "TRIGGER: max_suites: 11 suites > 5", (T / "st4" / "fakerepo.json").read_text()[:300])
r = with_conf("max_serial_minutes = 20.5\n")
check("trigger: max_serial_minutes", "TRIGGER: max_serial_minutes: 22.5 serial minutes > 20.5" in r.stdout and r.returncode == 0, r.stdout)
r = with_conf("max_suite_minutes = 4\n")
check("trigger: max_suite_minutes names the slowest suite and how many are over", "TRIGGER: max_suite_minutes: s09 takes 4.5 min (1 over) > 4" in r.stdout, r.stdout)
r = with_conf("max_suites = 11\nmax_serial_minutes = 22.5\nmax_suite_minutes = 4.5\n")
check("no trigger: a value equal to its limit is not over it", "TRIGGER" not in r.stdout and json.loads((T / "st4" / "fakerepo.json").read_text())["triggers"] == [], r.stdout)
r = with_conf("max_suites = 100\n[fakerepo]\nmax_suites = 3\n")
check("trigger: the [repo] table overrides the top-level key", "TRIGGER: max_suites: 11 suites > 3" in r.stdout, r.stdout)
r = with_conf("max_suites = 3\n[otherrepo]\nmax_suites = 100\n")
check("trigger: another repo's table is not read", "TRIGGER: max_suites: 11 suites > 3" in r.stdout, r.stdout)
r = with_conf("max_suites = 3\nmax_serial_minutes = 1\nmax_suite_minutes = 1\n")
keys = [l.split(":")[1].strip() for l in r.stdout.splitlines() if l.startswith("TRIGGER")]
check("trigger: several at once, in the order suites, serial, single", keys == ["max_suites", "max_serial_minutes", "max_suite_minutes"], keys)
# growth: the state for st4 holds the run above (now 2026-01-05); 30 more lines in a week vs a limit of 25 / 40
suite("g01", 30)
r = with_conf("max_test_line_growth = 25\n", now="2026-01-12T09:00:00+00:00")
check("trigger: max_test_line_growth over a week", r.returncode == 0 and "TRIGGER: max_test_line_growth: +30 test lines per week > 25" in r.stdout, r.stdout)
suite("g02", 30)
r = with_conf("max_test_line_growth = 40\n", now="2026-01-26T09:00:00+00:00")   # 14 days later, +30 lines: 15 a week
check("growth is scaled down to a week for a longer gap: no trigger at 15 a week", "TRIGGER" not in r.stdout and json.loads((T / "st4" / "fakerepo.json").read_text())["growth_per_week"] == 15.0, r.stdout)
suite("g03", 60); suite("g04", 60)
r = with_conf("max_test_line_growth = 40\n", now="2026-01-27T09:00:00+00:00")   # one day later, +120 lines: not scaled up
check("growth is not scaled up for a gap shorter than a week", "TRIGGER: max_test_line_growth: +120 test lines per week > 40" in r.stdout, r.stdout)
for k in ("g01", "g02", "g03", "g04"):
    (REPO / "tests" / f"{k}_scenario.py").unlink()
r = with_conf("max_test_line_growth = 1\n", now="2026-02-04T09:00:00+00:00")
check("a fall in test lines never triggers", "TRIGGER" not in r.stdout and r.returncode == 0, r.stdout)

# ------------------------------------------------------------------ 5 no suite times, --fetch
base = ["--state-dir", str(T / "st5"), "--config", str(CONF)]
CONF.write_text("max_serial_minutes = 0\nmax_suite_minutes = 0\n")
r = run(*base, "--map", str(T / "no-such-map.json"))
check("no map: n/a, a note, no minute trigger, exit 0", r.returncode == 0 and "serial minutes: n/a" in r.stdout and "no suite times:" in r.stdout and "TRIGGER" not in r.stdout, r.stdout + r.stderr)
check("no map: the record has null minutes", json.loads((T / "st5" / "fakerepo.json").read_text())["serial_minutes"] is None)
(T / "bad-map.json").write_text("{not json")
r = run(*base, "--map", str(T / "bad-map.json"))
check("damaged map: n/a with the reason", r.returncode == 0 and "is not JSON" in r.stdout, r.stdout)
(T / "old-map.json").write_text(json.dumps({"format": 2, "commit": "b", "suites": {}}))
r = run(*base, "--map", str(T / "old-map.json"))
check("a map of another format is not read", "is not a suite map of format 1" in r.stdout, r.stdout)
r = run(*base)
check("default map path is <root>/.suitemap/map.json (absent here)", "suitemap/map.json" in r.stdout and "serial minutes: n/a" in r.stdout, r.stdout)

GH_LOG = T / "gh.log"; GH_DIR = T / "gh.dir"
fake_gh = f'''#!/bin/sh
echo "$@" >> {GH_LOG}
case "$1 $2" in
  "run list") [ -n "$GH_FAIL" ] && {{ echo "boom" >&2; exit 1; }}; echo '[{{"databaseId": 4242}}]' ;;
  "run download")
    while [ $# -gt 0 ]; do [ "$1" = "--dir" ] && dir=$2; shift; done
    echo "$dir" > {GH_DIR}
    mkdir -p "$dir/nested"; cp {MAP} "$dir/nested/map.json" ;;
  *) exit 9 ;;
esac
'''
(GH_BIN / "gh").write_text(fake_gh); (GH_BIN / "gh").chmod(0o755)
PATH2 = f"{GH_BIN}:{os.environ['PATH']}"
CONF.write_text("")
r = run(*base, "--fetch", "--github", "acme/widgets", env={"PATH": PATH2})
check("--fetch: the artifact's map is used", r.returncode == 0 and "serial minutes: 22.5 (9 of 11 suites timed, 2 untimed)" in r.stdout, r.stdout + r.stderr)
calls = GH_LOG.read_text().splitlines()
check("--fetch: two gh calls, for main's push run of tests.yml and the suitemap artifact",
      len(calls) == 2 and "--repo acme/widgets" in calls[0] and "--workflow tests.yml" in calls[0] and "--branch main" in calls[0] and "--event push" in calls[0]
      and calls[1].startswith("run download 4242") and "--name suitemap" in calls[1], calls)
check("--fetch: the download folder is removed again", not pathlib.Path(GH_DIR.read_text().strip()).exists(), GH_DIR.read_text())
r = run(*base, "--fetch", "--github", "acme/widgets", env={"PATH": PATH2, "GH_FAIL": "1"})
check("--fetch: a failing gh gives n/a and the reason", r.returncode == 0 and "serial minutes: n/a" in r.stdout and "gh run list failed: boom" in r.stdout, r.stdout + r.stderr)
r = run(*base, "--fetch")
check("--fetch: no repository to ask is said (the fake repo has no origin)", "needs --github OWNER/REPO" in r.stdout, r.stdout + r.stderr)
check("--fetch: no folder of the tool is left in the scratch folder", not [p for p in T.iterdir() if p.name.startswith("test-trim-")], list(T.iterdir()))

# ------------------------------------------------------------------ 6 errors
blocker = T / "blocker"; blocker.write_text("a file, not a folder")
r = run("--map", str(MAP), "--state-dir", str(blocker / "inside"))
check("unwritable state folder (its parent is a file): nonzero, clear message, nothing on stdout",
      r.returncode == 1 and r.stdout == "" and "cannot write the state folder" in r.stderr and str(blocker) in r.stderr, (r.returncode, r.stdout, r.stderr))
if os.geteuid() != 0:
    ro = T / "readonly"; ro.mkdir(); ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        r = run("--map", str(MAP), "--state-dir", str(ro))
        check("read-only state folder: nonzero, clear message", r.returncode == 1 and r.stdout == "" and "cannot write the state folder" in r.stderr, (r.returncode, r.stderr))
    finally:
        ro.chmod(stat.S_IRWXU)
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(blocker / "inside"))
check("dry run does not need a writable state folder", r.returncode == 0 and "test-trim report" in r.stdout, r.stderr)
CONF.write_text("max_suites = -1\n")
r = run("--map", str(MAP), "--state-dir", str(T / "st6"), "--config", str(CONF))
check("a bad config value: status 2 naming the key", r.returncode == 2 and "max_suites must be a number" in r.stderr, (r.returncode, r.stderr))
CONF.write_text('max_suites = "many"\n')
r = run("--map", str(MAP), "--state-dir", str(T / "st6"), "--config", str(CONF))
check("a config value of the wrong type: status 2", r.returncode == 2 and "max_suites must be a number" in r.stderr, (r.returncode, r.stderr))
CONF.write_text("max_suites = \n")
r = run("--map", str(MAP), "--state-dir", str(T / "st6"), "--config", str(CONF))
check("a config that is not TOML: status 2", r.returncode == 2 and "not valid TOML" in r.stderr, (r.returncode, r.stderr))
r = run("--map", str(MAP), "--state-dir", str(T / "st6"), "--config", str(T / "missing.toml"))
check("an explicit config that is missing: status 2", r.returncode == 2 and "does not exist" in r.stderr, (r.returncode, r.stderr))
empty = T / "empty"; empty.mkdir()
r = run("--map", str(MAP), "--state-dir", str(T / "st6"), cwd=empty)
check("a checkout with no suites: status 2, nothing written", r.returncode == 2 and "no tests/*_scenario.py" in r.stderr and not (T / "st6").exists(), (r.returncode, r.stderr))
r = run("--now", "yesterday")
check("a bad --now: status 2", r.returncode == 2 and "not an ISO time" in r.stderr, r.stderr)
(T / "st7").mkdir(); (T / "st7" / "fakerepo.json").write_text("{broken")
r = run("--map", str(MAP), "--state-dir", str(T / "st7"))
check("a damaged previous record is started over with a note", r.returncode == 0 and "starting over" in r.stdout and "this run is the baseline" in r.stdout, r.stdout + r.stderr)
check("a damaged previous record is replaced by a good one", json.loads((T / "st7" / "fakerepo.json").read_text())["format"] == 1)
(T / "st7" / "fakerepo.json").write_text(json.dumps({"format": 1, "generated": "not a time", "suites": {"a": 1}}))
r = run("--map", str(MAP), "--state-dir", str(T / "st7"))
check("a previous record with a bad time is started over", r.returncode == 0 and "damaged; starting over" in r.stdout, r.stdout + r.stderr)

# ------------------------------------------------------------------ 7 read-only, nothing outside
r = run("--map", str(MAP), "--json", "--dry-run")
check("--json prints the record", r.returncode == 0 and json.loads(r.stdout)["repo"] == "fakerepo", r.stdout[:200] + r.stderr)
shot = tree_hash(REPO)
for extra in ([], ["--dry-run"], ["--json"]):
    run("--map", str(MAP), "--state-dir", str(T / "st8"), *extra)
check("a run leaves the checkout byte for byte as it was", tree_hash(REPO) == shot)
check("the run created nothing under the fake home but its state folder", sorted(str(p.relative_to(HOME)) for p in HOME.rglob("*") if p.is_file()) == [".local/state/stackshot/test-trim/fakerepo.json"],
      sorted(str(p.relative_to(HOME)) for p in HOME.rglob("*")))
real_after = (real_state.exists(), sorted(p.name for p in real_state.glob("*")) if real_state.exists() else [])
check("the invoking user's own state folder is untouched", real_after == real_before, (real_before, real_after))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
