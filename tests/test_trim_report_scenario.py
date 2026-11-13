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
  7  a previous record that cannot be used (a field missing or mistyped, no UTC offset, a count that is negative, infinite or not whole,
     another format or repository, not JSON, nested too deep): started over with one note and replaced, the next run compares with it
  8  the config file: a mistyped key warns on stderr (exit 0), nan and booleans are status 2
  9  growth equal to its limit does not trigger; the shipped limit never triggers with a previous run
  10 a write that fails after the probe passed: status 1 and no temporary file
  11 the suite map: negative, infinite and mistyped times are ignored with a note; a map matching no suite prints no slowest line
  12 --fetch is taken before --map (and the docstring says so); no temporary folder gives one line; SIGTERM removes the download folder,
     and the handler is restored
  13 a root named g[1]; the file is executable
  14 read-only: the fake repository is byte for byte as it was, and nothing outside the state folder is written
  15 hostile input: a map nested too deep, a time beyond float range, 1e308, NaN or past a year; a config that is not UTF-8, nested too deep,
     or holds a huge, infinite, negative or mistyped limit (all exit 2 or a note, never a traceback); no config file at all still runs
  16 the previous record's clock and the arithmetic: a record dated in the future is clamped to age 0; LIST_MAX cuts the name lists and says
     how many more; minutes at zero and at the rounding boundaries; the net figure comes from the previous record's test_lines
  17 the edges by plain numbers (not the tool's own constants): a suite time of 31622400 s is a time and 31622401 s is not; a limit of 10**12 is
     accepted and one more refused by name; 20 names list whole, 21 list 20 and 'and 1 more', 25 list 20 and 'and 5 more' (added, deleted, the
     note of ignored times); a config is a file: a pipe (a FIFO with no writer, one with a writer, /dev/stdin) is refused within 15 s instead of
     hanging, a terminal is refused, a folder gives its old message, no descriptor is left open; a limit of 0, 0.0 or -0.0 is stored as zero
     (never -0); a config with a UTF-8 byte order mark or in UTF-16 is a clear status 2, never a traceback

    tests/run-suite test_trim_report        -> exit 0 / 1"""
import contextlib, hashlib, io, json, os, pathlib, shutil, signal, stat, subprocess, sys, tempfile, time

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
    r = subprocess.run([sys.executable, TOOL, "--no-open", *(["--now", now] if now else []), *args], capture_output=True, text=True, env=e, cwd=cwd, timeout=120)     # --no-open: a trigger here never calls the client (the item step has its own suite, trim_open)
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
check("--fetch: two gh calls, exactly: main's push run of tests.yml, then the suitemap artifact (the name is not a prefix of another)",
      calls == ["run list --repo acme/widgets --workflow tests.yml --branch main --event push --status success --limit 1 --json databaseId",
                f"run download 4242 --repo acme/widgets --name suitemap --dir {GH_DIR.read_text().strip()}"], calls)
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
(T / "st7" / "fakerepo.json").write_text(json.dumps({"format": 1, "repo": "fakerepo", "generated": "not a time", "suites": {"a": 1}, "test_lines": 1}))
r = run("--map", str(MAP), "--state-dir", str(T / "st7"))
check("a previous record with a bad time is started over", r.returncode == 0 and "damaged (generated); starting over" in r.stdout, r.stdout + r.stderr)

# ------------------------------------------------------------------ 7 a previous record that cannot be used
r = run("--map", str(MAP), "--state-dir", str(T / "st9g"), now="2026-01-12T09:00:00+00:00")
GOOD = json.loads((T / "st9g" / "fakerepo.json").read_text())


def mutated(**kw):
    d = json.loads(json.dumps(GOOD)); d.update(kw)
    return json.dumps(d)


def dropped(k):
    d = json.loads(json.dumps(GOOD)); del d[k]
    return json.dumps(d)


def with_suite(value_text):
    d = json.loads(json.dumps(GOOD)); d["suites"]["a"] = "@@"
    return json.dumps(d).replace('"@@"', value_text)


def damaged_run(key, text, expect=None):
    folder = T / "st9" / key.replace(" ", "_").replace("/", "_"); folder.mkdir(parents=True)
    (folder / "fakerepo.json").write_text(text)
    r = run("--map", str(MAP), "--state-dir", str(folder), now="2026-01-19T09:00:00+00:00")
    notes = [l for l in r.stdout.splitlines() if l.startswith("note:")]
    ok = (r.returncode == 0 and "Traceback" not in r.stderr and len(notes) == 1 and "starting over" in notes[0]
          and "this run is the baseline" in r.stdout and (expect is None or expect in notes[0]))
    check(f"previous record ({key}): started over with one note, exit 0, no traceback", ok, (r.returncode, r.stderr[-400:], notes))
    fresh = json.loads((folder / "fakerepo.json").read_text())
    check(f"previous record ({key}): replaced by this run's record", fresh["format"] == 1 and fresh["repo"] == "fakerepo" and fresh["generated"].startswith("2026-01-19") and fresh["test_lines"] == sum(fresh["suites"].values()), fresh.get("generated"))
    r2 = run("--map", str(MAP), "--state-dir", str(folder), now="2026-01-26T09:00:00+00:00")
    check(f"previous record ({key}): the next run compares with the record that replaced it", r2.returncode == 0 and "(7.0 days ago)" in r2.stdout and "starting over" not in r2.stdout, r2.stdout + r2.stderr)


(T / "st9ok").mkdir()
(T / "st9ok" / "fakerepo.json").write_text(json.dumps(GOOD))
r = run("--map", str(MAP), "--state-dir", str(T / "st9ok"), now="2026-01-19T09:00:00+00:00")
check("a sound previous record is used (the control of the damaged ones)", r.returncode == 0 and "(7.0 days ago)" in r.stdout and "starting over" not in r.stdout, r.stdout + r.stderr)
damaged_run("format 2", mutated(format=2), "not of this tool's format")
damaged_run("format true", mutated(format=True), "not of this tool's format")
damaged_run("format missing", dropped("format"), "not of this tool's format")
damaged_run("another repository", mutated(repo="otherrepo"), "otherrepo")
damaged_run("no repo field", dropped("repo"), "repository")
damaged_run("no test_lines", dropped("test_lines"))
damaged_run("test_lines a string", mutated(test_lines="x"))
damaged_run("test_lines true", mutated(test_lines=True))
damaged_run("test_lines negative", mutated(test_lines=-1))
damaged_run("test_lines a float", mutated(test_lines=1.5))
damaged_run("test_lines huge", mutated(test_lines=10 ** 30))
damaged_run("generated without an offset", mutated(generated="2026-01-05T09:00:00"), "UTC offset")
damaged_run("generated a bare date", mutated(generated="2026-01-05"), "UTC offset")
damaged_run("generated a number", mutated(generated=5))
damaged_run("generated missing", dropped("generated"))
damaged_run("suites a list", mutated(suites=[1, 2]))
damaged_run("a suite count of 1e999", with_suite("1e999"))
damaged_run("a negative suite count", with_suite("-3"))
damaged_run("a suite count of true", with_suite("true"))
damaged_run("a suite count as a string", with_suite('"3"'))
damaged_run("a suite count with a fraction", with_suite("2.5"))
damaged_run("a huge suite count", with_suite("1" + "0" * 40))
damaged_run("a JSON list", "[1, 2]")
damaged_run("JSON null", "null")
damaged_run("an empty file", "")
damaged_run("nesting deep enough to overflow the parser", "[" * 200000)

# ------------------------------------------------------------------ 8 the config file: mistyped keys, nan, booleans
CONF.write_text("max_suite = 5\nMAX_SUITES = 5\nmax_serial_minutes = 100\n[fakerepo]\nmax_test_line_growht = 3\n[otherrepo]\nmax_suites = 100\nmax_suit = 4\n")
r = run("--map", str(MAP), "--state-dir", str(T / "st10"), "--config", str(CONF))
check("an unknown key: one warning line per key on stderr, none for known keys or another repo's good keys",
      r.stderr.splitlines() == [f"warning: unknown key max_suite in {CONF}", f"warning: unknown key MAX_SUITES in {CONF}",
                                f"warning: unknown key max_test_line_growht in {CONF} (table [fakerepo])", f"warning: unknown key max_suit in {CONF} (table [otherrepo])"], r.stderr)
check("an unknown key: exit 0, the report is printed and the key is not used", r.returncode == 0 and "test-trim report: fakerepo" in r.stdout and "TRIGGER" not in r.stdout, r.stdout)
CONF.write_text("max_suites = 100\nmax_serial_minutes = 100\n[fakerepo]\nmax_suite_minutes = 100\n[otherrepo]\nmax_suites = 3\n")
r = run("--map", str(MAP), "--state-dir", str(T / "st10"), "--config", str(CONF))
check("a config with only the four keys (and another repo's table) warns of nothing", r.returncode == 0 and r.stderr == "", r.stderr)
for key in ("max_suites", "max_serial_minutes", "max_suite_minutes", "max_test_line_growth"):
    for bad in ("nan", "+nan", "true", "false"):
        CONF.write_text(f"{key} = {bad}\n")
        r = run("--map", str(MAP), "--state-dir", str(T / "st10"), "--config", str(CONF))
        check(f"{key} = {bad}: exit 2 naming the key", r.returncode == 2 and f"{key} must be a number" in r.stderr and r.stdout == "", (r.returncode, r.stderr))
CONF.write_text("[fakerepo]\nmax_suites = nan\n")
r = run("--map", str(MAP), "--state-dir", str(T / "st10"), "--config", str(CONF))
check("nan in the repo's table: exit 2 naming the key", r.returncode == 2 and "max_suites must be a number" in r.stderr, (r.returncode, r.stderr))

# ------------------------------------------------------------------ 9 growth at its limit, and the default limit with a previous run
st11 = ["--state-dir", str(T / "st11"), "--map", str(MAP)]
run(*st11, now="2026-02-10T09:00:00+00:00")                       # the baseline
suite("e01", 30)
CONF.write_text("max_test_line_growth = 30\n")
r = run(*st11, "--config", str(CONF), "--dry-run", "--json", now="2026-02-17T09:00:00+00:00")
j = json.loads(r.stdout)
check("growth equal to its limit does not trigger", j["growth_per_week"] == 30.0 and j["triggers"] == [], j.get("triggers"))
CONF.write_text("max_test_line_growth = 29\n")
r = run(*st11, "--config", str(CONF), "--dry-run", now="2026-02-17T09:00:00+00:00")
check("growth one above its limit triggers", "TRIGGER: max_test_line_growth: +30 test lines per week > 29" in r.stdout, r.stdout)
suite("e02", 3000)
r = run(*st11, "--dry-run", "--json", now="2026-02-17T09:00:00+00:00")        # no config file at all: the shipped placeholder
j = json.loads(r.stdout)
check("the default max_test_line_growth with a previous run never triggers", r.returncode == 0 and j["growth_per_week"] == 3030.0 and j["triggers"] == [], r.stdout[:300] + r.stderr)
for k in ("e01", "e02"):
    (REPO / "tests" / f"{k}_scenario.py").unlink()

# ------------------------------------------------------------------ 10 a failed write, after the probe passed
st12 = T / "st12"; (st12 / "fakerepo.json").mkdir(parents=True)     # the record's place is a folder: the probe file can be made, the rename cannot
r = run("--map", str(MAP), "--state-dir", str(st12))
check("a failed write after the probe passed: exit 1, a message, nothing on stdout", r.returncode == 1 and r.stdout == "" and "cannot write" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stdout[:100], r.stderr))
check("a failed write leaves no temporary file behind", sorted(p.name for p in st12.iterdir()) == ["fakerepo.json"], [p.name for p in st12.iterdir()])

# ------------------------------------------------------------------ 11 the suite map: negative, non-finite and mistyped times; a map that matches nothing
(T / "neg-map.json").write_text(json.dumps({"format": 1, "commit": "c" * 40, "suites": {
    "s01": {"seconds": -5}, "s02": {"seconds": 60}, "s03": {"seconds": float("inf")}, "s04": {"seconds": "9"}, "s05": {"seconds": True},
    "s06": {"ok": False}, "gone_long_ago": {"seconds": -1}}}))
r = run("--map", str(T / "neg-map.json"), "--state-dir", str(T / "st13"))
notes = [l for l in r.stdout.splitlines() if l.startswith("note:")]
check("a negative, infinite or mistyped time is ignored with a note naming the suites that have it (not a suite the checkout lacks, not a missing time)",
      r.returncode == 0 and len(notes) == 1 and notes[0].endswith(": s01, s03, s04, s05"), (r.stdout, r.stderr))
check("those suites count as untimed and add no minutes", "serial minutes: 1.0 (1 of 11 suites timed, 10 untimed)" in r.stdout and "slowest 1:" in r.stdout, r.stdout)
(T / "none-map.json").write_text(json.dumps({"format": 1, "commit": "d", "suites": {"other": {"seconds": 5}}}))
r = run("--map", str(T / "none-map.json"), "--state-dir", str(T / "st13"))
check("a map that matches no suite prints no slowest line", r.returncode == 0 and "serial minutes: 0.0 (0 of 11 suites timed, 11 untimed)" in r.stdout and "slowest" not in r.stdout, r.stdout)

# ------------------------------------------------------------------ 12 --fetch beats --map, a folder that cannot be made, SIGTERM
base = ["--state-dir", str(T / "st5"), "--config", str(CONF)]
CONF.write_text("")
r = run(*base, "--fetch", "--github", "acme/widgets", "--map", str(T / "no-such-map.json"), env={"PATH": PATH2})
check("--fetch wins over --map", r.returncode == 0 and "serial minutes: 22.5 (9 of 11 suites timed, 2 untimed)" in r.stdout, r.stdout + r.stderr)
doc = pathlib.Path(TOOL).read_text(encoding="utf-8")       # the file's text, not the module's docstring attribute (the suitemap tripwire pins those uses)
check("the docstring lists --fetch before --map, as the code takes them", 0 < doc.index("--fetch         the `suitemap`") < doc.index("--map FILE      this file"))
EMPTY_CONF = T / "empty.toml"; EMPTY_CONF.write_text("")


def inproc(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = TR.main(["--root", str(REPO), "--now", "2026-01-05T09:00:00+00:00", "--dry-run", "--config", str(EMPTY_CONF), *args])
        except BaseException as e:
            rc = f"raised {e!r}"
    return rc, out.getvalue(), err.getvalue()


term_before = signal.getsignal(signal.SIGTERM)       # taken before any in-process run of main
real_mkdtemp = tempfile.mkdtemp


def no_folder(*a, **k):
    raise PermissionError(13, "Permission denied")


tempfile.mkdtemp = no_folder
try:
    rc, out, err = inproc("--fetch", "--github", "acme/widgets", "--state-dir", str(T / "st14"))
finally:
    tempfile.mkdtemp = real_mkdtemp
check("--fetch with no temporary folder: one line saying so, n/a minutes, exit 0, no traceback",
      rc == 0 and "no suite times: cannot make a temporary folder for the download: Permission denied" in out and "serial minutes: n/a" in out and "Traceback" not in err, (rc, out[-300:], err))

rc, out, err = inproc("--map", str(MAP), "--state-dir", str(T / "st14"))
check("main restores the SIGTERM handler it found", rc == 0 and signal.getsignal(signal.SIGTERM) == term_before, (rc, signal.getsignal(signal.SIGTERM)))
rc, out, err = inproc("--map", str(MAP), "--state-dir", str(T / "st14"), "--config", str(T / "missing.toml"))
check("main restores the SIGTERM handler after a failed run too", rc == 2 and signal.getsignal(signal.SIGTERM) == term_before, (rc, signal.getsignal(signal.SIGTERM)))

SLOW_BIN = T / "bin-slow"; SLOW_BIN.mkdir(); SLOW_PID = T / "slow.pid"; TOKEN = f"trimreport-fake-{os.getpid()}"
(SLOW_BIN / "gh").write_text(f"#!/bin/sh\necho $$ > {SLOW_PID}\nexec sleep 30\n"); (SLOW_BIN / "gh").chmod(0o755)
slow_env = {"PATH": f"{SLOW_BIN}:{os.environ['PATH']}", "HOME": str(HOME), "TMPDIR": tmp, "LANG": "C.UTF-8", "TRIMREPORT_FAKE": TOKEN}
child = subprocess.Popen([sys.executable, TOOL, "--now", "2026-01-05T09:00:00+00:00", "--fetch", "--github", "acme/widgets", "--dry-run", "--config", str(EMPTY_CONF)],
                         env=slow_env, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
fake_pid = None


def tool_folders():
    return sorted(p.name for p in T.iterdir() if p.name.startswith("test-trim-"))


try:
    waited = 0.0
    while waited < 20 and not (SLOW_PID.exists() and SLOW_PID.read_text().strip()):
        time.sleep(0.05); waited += 0.05
    fake_pid = int(SLOW_PID.read_text().strip()) if SLOW_PID.exists() and SLOW_PID.read_text().strip() else None
    during = tool_folders()
    child.send_signal(signal.SIGTERM)                      # by PID: the tool we started, and nothing else
    try:
        out, err = child.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill(); out, err = child.communicate()
    check("SIGTERM during the download: the tool ends with status 143 (its handler ran, it was not killed)", child.returncode == 143, (child.returncode, err[-300:]))
    check("SIGTERM during the download: the folder existed and is removed", len(during) == 1 and tool_folders() == [], (during, tool_folders()))
    check("SIGTERM during the download: the waiting gh is stopped too", fake_pid is not None and not os.path.exists(f"/proc/{fake_pid}"), fake_pid)
finally:
    if child.poll() is None:
        child.kill(); child.wait()
    if fake_pid is not None and os.path.exists(f"/proc/{fake_pid}"):
        try:                                               # only our own fake gh: it carries the token in its environment
            if TOKEN.encode() in pathlib.Path(f"/proc/{fake_pid}/environ").read_bytes():
                os.kill(fake_pid, signal.SIGKILL)
        except OSError:
            pass

# ------------------------------------------------------------------ 13 a root whose name holds glob characters, the file's mode
GLOBBY = T / "g[1]"; shutil.copytree(REPO, GLOBBY)
r = run("--root", str(GLOBBY), "--map", str(MAP), "--dry-run", "--state-dir", str(T / "st15"))
check("a root named g[1] is measured like any other (the path is not a pattern)", r.returncode == 0 and "suites: 11\n" in r.stdout and "g_1_" in r.stdout, (r.returncode, r.stdout[:200], r.stderr))
with open(TOOL) as f:
    first_line = f.readline()
check("the tool is executable and has its shebang, like tools/text_check.py", os.stat(TOOL).st_mode & 0o111 == 0o111 and first_line.startswith("#!"), oct(os.stat(TOOL).st_mode))

# ------------------------------------------------------------------ 14 read-only, nothing outside
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

# ------------------------------------------------------------------ 15 hostile input: a map and a config that would overflow or recurse
def clean(r):
    return "Traceback" not in r.stderr and "Error" not in r.stderr


def map_run(name, text, *extra):
    f = T / f"hostile-{name}.json"; f.write_text(text)
    return run("--map", str(f), "--dry-run", "--state-dir", str(T / "st16"), *extra)


r = map_run("deep", "[" * 200000)
check("a map nested deep enough to overflow the parser: one note, n/a minutes, exit 0, no traceback",
      r.returncode == 0 and clean(r) and "no suite times:" in r.stdout and "nested too deeply" in r.stdout and "serial minutes: n/a" in r.stdout, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
r = map_run("bigint", '{"format": 1, "suites": {"s01": {"seconds": 1' + "0" * 400 + '}, "s02": {"seconds": 60}}}')
check("a time that is an int beyond float range: ignored with a note naming the suite, no OverflowError",
      r.returncode == 0 and clean(r) and "ignored" in r.stdout and r.stdout.count("s01") == 1 and "serial minutes: 1.0 (1 of 11 suites timed" in r.stdout, (r.returncode, r.stdout[-400:], r.stderr[-300:]))
r = map_run("huge", '{"format": 1, "suites": {"s01": {"seconds": 1e308}, "s02": {"seconds": 1e308}, "s03": {"seconds": 60}}}', "--json")
j = json.loads(r.stdout) if r.returncode == 0 else {}
note = (j.get("notes") or [""])[0]
check("times of 1e308 are ignored: the minutes stay finite and the record is plain JSON",
      r.returncode == 0 and j.get("serial_minutes") == 1.0 and "Infinity" not in r.stdout and "s01, s02" in note, (r.returncode, r.stdout[:400], r.stderr[-300:]))
(T / "year.json").write_text(json.dumps({"format": 1, "suites": {"a": {"seconds": TR.SECONDS_MAX}, "b": {"seconds": TR.SECONDS_MAX + 1}, "c": {"seconds": 0}}}))
got = TR.read_map(str(T / "year.json"))
check("the limit is a year: a year is a time, a year and a second is not, and 0 seconds is", got[0] == {"a": float(TR.SECONDS_MAX), "c": 0.0} and got[2] == ["b"], got)
r = map_run("nan", '{"format": 1, "suites": {"s01": {"seconds": NaN}, "s02": {"seconds": Infinity}, "s03": {"seconds": -Infinity}}}')
check("NaN, Infinity and -Infinity times are ignored with one note", r.returncode == 0 and clean(r) and r.stdout.count("note:") == 1 and "s01, s02, s03" in r.stdout, (r.stdout[-300:], r.stderr))

(T / "latin.toml").write_bytes(b"max_suites = 5\n# caf\xe9 \xff\xfe\n")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(T / "latin.toml"))
check("a config that is not UTF-8: status 2, one clear line, nothing on stdout, no traceback",
      r.returncode == 2 and r.stdout == "" and "is not UTF-8 text" in r.stderr and str(T / "latin.toml") in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stdout[:100], r.stderr))
CONF.write_text("a = " + "{b = " * 500 + "1" + "}" * 500 + "\n")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(CONF))
check("a config nested too deep: status 2 and a message, not a traceback", r.returncode == 2 and r.stdout == "" and "Traceback" not in r.stderr and "nested too deeply" in r.stderr, (r.returncode, r.stderr[-300:]))
CONF.write_text("max_suites = 1" + "0" * 5000 + "\n")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(CONF))
check("a config number with thousands of digits: status 2 and a message, not a traceback", r.returncode == 2 and r.stdout == "" and "Traceback" not in r.stderr and "cannot be read" in r.stderr, (r.returncode, r.stderr[-300:]))
for key in ("max_suites", "max_serial_minutes", "max_suite_minutes", "max_test_line_growth"):
    for bad in ("1" + "0" * 400, "1e400", "inf", "-inf", "-0.5", "1e13", '"5"', "[1]"):
        CONF.write_text(f"{key} = {bad}\n")
        r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(CONF))
        check(f"{key} = {bad[:12]}: exit 2 naming the key, no traceback, nothing on stdout",
              r.returncode == 2 and f"{key} must be a number from 0 to" in r.stderr and "Traceback" not in r.stderr and r.stdout == "", (r.returncode, r.stderr[-300:]))
CONF.write_text("[fakerepo]\nmax_suites = " + "9" * 30 + "\n")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(CONF))
check("a huge value in the repo's table is refused too", r.returncode == 2 and "max_suites must be a number from 0 to" in r.stderr, (r.returncode, r.stderr[-300:]))
for key, good in (("max_suites", "0"), ("max_serial_minutes", "0.5"), ("max_suite_minutes", "1000000000000"), ("max_test_line_growth", "0")):
    CONF.write_text(f"{key} = {good}\n")
    r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), "--config", str(CONF))
    check(f"{key} = {good}: the edges of the range are accepted", r.returncode == 0 and "test-trim report" in r.stdout, (r.returncode, r.stderr[-300:]))
CONF.write_text("")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st16"), env={"XDG_CONFIG_HOME": str(T / "no-config-home")})
check("no thresholds file at the default place (as on a fresh machine): the tool still runs, exit 0, nothing on stderr, no trigger",
      r.returncode == 0 and r.stderr == "" and "test-trim report: fakerepo" in r.stdout and "TRIGGER" not in r.stdout and not (T / "no-config-home").exists(), (r.returncode, r.stdout[:200], r.stderr))


# ------------------------------------------------------------------ 16 the previous record's clock and the report's arithmetic
def baseline(folder, when, minus=0):
    """a previous record made by the tool at `when`, with `minus` fewer test lines in s01 (so the next run grew by that much)"""
    shutil.rmtree(folder, ignore_errors=True)
    run("--map", str(MAP), "--state-dir", str(folder), now=when)
    f = folder / "fakerepo.json"; d = json.loads(f.read_text())
    d["suites"]["s01"] -= minus; d["test_lines"] -= minus
    f.write_text(json.dumps(d))
    return f


# (a) a previous record dated after the clock is not trusted past now
st17 = T / "st17"
baseline(st17, "2026-04-01T09:00:00+00:00", minus=3)
r = run("--map", str(MAP), "--state-dir", str(st17), "--dry-run", now="2026-03-01T09:00:00+00:00")
check("a previous record dated in the future: its age is clamped to 0.0 days, never negative", r.returncode == 0 and "since the previous run (0.0 days ago)" in r.stdout, r.stdout + r.stderr)
r = run("--map", str(MAP), "--state-dir", str(st17), "--dry-run", "--json", now="2026-03-01T09:00:00+00:00")
check("a previous record dated in the future: the growth is the plain net, not scaled", json.loads(r.stdout)["growth_per_week"] == 3.0, r.stdout[:200])
CONF.write_text("max_test_line_growth = 2\n")
r = run("--map", str(MAP), "--state-dir", str(st17), "--dry-run", "--config", str(CONF), now="2026-03-01T09:00:00+00:00")
check("a previous record dated in the future still triggers on its plain net growth", "TRIGGER: max_test_line_growth: +3 test lines per week > 2" in r.stdout, r.stdout)
CONF.write_text("")
baseline(st17, "2026-02-01T09:00:00+00:00", minus=3)
r = run("--map", str(MAP), "--state-dir", str(st17), "--dry-run", now="2026-03-01T09:00:00+00:00")
check("control: a previous record from the past keeps its true age (28.0 days)", "since the previous run (28.0 days ago)" in r.stdout, r.stdout)

# (b) LIST_MAX: more added or deleted suites than the cap are cut and the rest counted
many = [f"zz{i:02d}" for i in range(TR.LIST_MAX + 5)]
for n in many:
    suite(n, 1)
st18 = T / "st18"; shutil.rmtree(st18, ignore_errors=True)
run("--map", str(MAP), "--state-dir", str(st18), now="2026-03-01T09:00:00+00:00")
for n in many:
    (REPO / "tests" / f"{n}_scenario.py").unlink()
r = run("--map", str(MAP), "--state-dir", str(st18), "--dry-run", now="2026-03-08T09:00:00+00:00")
dline = [l for l in r.stdout.splitlines() if l.startswith("  deleted:")]
check("more deleted suites than LIST_MAX: the line lists exactly LIST_MAX names and says how many more",
      dline == ["  deleted: " + ", ".join(many[:TR.LIST_MAX]) + ", and 5 more"], dline)
check("the cut does not touch the count in the summary line", f"{TR.LIST_MAX + 5} deleted" in r.stdout, r.stdout)
st19 = T / "st19"; shutil.rmtree(st19, ignore_errors=True)
run("--map", str(MAP), "--state-dir", str(st19), now="2026-03-01T09:00:00+00:00")
for n in many[:TR.LIST_MAX]:
    suite(n, 1)
r = run("--map", str(MAP), "--state-dir", str(st19), "--dry-run", now="2026-03-08T09:00:00+00:00")
aline = [l for l in r.stdout.splitlines() if l.startswith("  added:")]
check("exactly LIST_MAX added suites are listed whole, with no 'and more'", aline == ["  added: " + ", ".join(many[:TR.LIST_MAX])], aline)
for n in many[:TR.LIST_MAX]:
    (REPO / "tests" / f"{n}_scenario.py").unlink()
check("names_line: LIST_MAX + 5 names are cut to LIST_MAX and the rest counted; LIST_MAX names are not cut",
      TR.names_line("x", many) == "  x: " + ", ".join(many[:TR.LIST_MAX]) + ", and 5 more" and TR.names_line("x", many[:TR.LIST_MAX]) == "  x: " + ", ".join(many[:TR.LIST_MAX]), TR.names_line("x", many))
for n in many:
    suite(n, 1)
(T / "listmax-map.json").write_text(json.dumps({"format": 1, "suites": {n: {"seconds": -1} for n in many}}))
r = run("--map", str(T / "listmax-map.json"), "--state-dir", str(T / "st16"), "--dry-run")
for n in many:
    (REPO / "tests" / f"{n}_scenario.py").unlink()
note = [l for l in r.stdout.splitlines() if l.startswith("note:")]
check("the note on ignored times is cut at LIST_MAX too and counts the rest", len(note) == 1 and note[0].endswith(": " + ", ".join(many[:TR.LIST_MAX]) + ", and 5 more"), note)

# (c) minutes: seconds / 60 rounded to two places, added up, shown with one; zero and the half boundaries
def minutes_of(seconds_by_suite):
    f = T / "bound-map.json"; f.write_text(json.dumps({"format": 1, "suites": {n: {"seconds": s} for n, s in seconds_by_suite.items()}}))
    return json.loads(run("--map", str(f), "--state-dir", str(T / "st20"), "--dry-run", "--json").stdout)


jz = minutes_of({"s01": 0})
check("a suite of 0 seconds is timed, at 0.0 minutes (not untimed, not dropped)", jz["serial_minutes"] == 0.0 and jz["untimed"] == jz["suite_count"] - 1 and jz["timed"] == [["s01", 0.0]], (jz["serial_minutes"], jz["untimed"], jz["timed"]))
jz = minutes_of({"s01": 0.3})
check("0.3 s is 0.005 min, which rounds up to 0.01 (two places, not one, not cut)", jz["timed"] == [["s01", 0.01]] and jz["serial_minutes"] == 0.01, jz["timed"])
jz = minutes_of({"s01": 1.5, "s02": 1.5})
check("1.5 s is 0.03 min and two of them add to 0.06", jz["timed"] == [["s01", 0.03], ["s02", 0.03]] and jz["serial_minutes"] == 0.06, (jz["timed"], jz["serial_minutes"]))
jz = minutes_of({"s01": 89.4, "s02": 89.7})
check("89.4 s is 1.49 min and 89.7 s is 1.495, rounded up to 1.5", jz["timed"] == [["s02", 1.5], ["s01", 1.49]], jz["timed"])
jz = minutes_of({"s01": 30})
check("30 s is exactly 0.5 min", jz["timed"] == [["s01", 0.5]] and jz["serial_minutes"] == 0.5, jz["timed"])
r = run("--map", str(T / "bound-map.json"), "--state-dir", str(T / "st20"), "--dry-run")
check("the text shows one place: 0.5 min", "serial minutes: 0.5 (1 of 11 suites timed, 10 untimed)" in r.stdout and "1. s01  0.5 min" in r.stdout, r.stdout)
(T / "m125.json").write_text(json.dumps({"format": 1, "suites": {"s01": {"seconds": 75}}}))
CONF.write_text("max_suite_minutes = 1.25\nmax_serial_minutes = 1.25\n")
r = run("--map", str(T / "m125.json"), "--state-dir", str(T / "st20"), "--dry-run", "--config", str(CONF))
check("a suite of exactly 75 s (1.25 min) is not over a limit of 1.25", "TRIGGER" not in r.stdout, r.stdout)
CONF.write_text("max_suite_minutes = 1.24\nmax_serial_minutes = 1.24\n")
r = run("--map", str(T / "m125.json"), "--state-dir", str(T / "st20"), "--dry-run", "--config", str(CONF))
check("and it is over 1.24, in both minute thresholds", "TRIGGER: max_suite_minutes: s01 takes 1.2 min (1 over) > 1.2" in r.stdout and "TRIGGER: max_serial_minutes: 1.2 serial minutes > 1.2" in r.stdout, r.stdout)
CONF.write_text("")

# (d) the net figure is this run's test lines minus the previous record's test_lines, signed, with thousands separators
st21 = T / "st21"
suite("zbig", 2500)
f21 = baseline(st21, "2026-03-01T09:00:00+00:00")
d21 = json.loads(f21.read_text()); now_lines = d21["test_lines"]
check("(the control: the baseline holds the test lines now, with the big suite)", now_lines == sum(d21["suites"].values()) and now_lines > 2500, now_lines)
for prev_lines, expect in ((0, f"(net +{now_lines:,})"), (now_lines + 7, "(net -7)"), (now_lines, "(net +0)")):
    d21["test_lines"] = prev_lines; f21.write_text(json.dumps(d21))
    r = run("--map", str(MAP), "--state-dir", str(st21), "--dry-run", now="2026-03-08T09:00:00+00:00")
    check(f"net growth is the test lines now minus the previous record's test_lines: {expect}", expect in r.stdout, r.stdout)
(REPO / "tests" / "zbig_scenario.py").unlink()

# ------------------------------------------------------------------ 17 the edges of the constants, pinned by their plain numbers
# (sections 15 and 16 read the limits from the tool itself, so a changed constant moved the test with it: these use the numbers)
check("the constants are the documented numbers: a year of seconds, 20 listed names, a limit of 10**12", (TR.SECONDS_MAX, TR.LIST_MAX, TR.THRESHOLD_MAX) == (31622400, 20, 10 ** 12), (TR.SECONDS_MAX, TR.LIST_MAX, TR.THRESHOLD_MAX))


def edge_map(name, seconds_by_suite):
    f = T / f"{name}.json"; f.write_text(json.dumps({"format": 1, "suites": {n: {"seconds": s} for n, s in seconds_by_suite.items()}}))
    return f


# what the fake repository holds now, from the repository and the map themselves (not from what an earlier section left in mind)
NOW17 = TR.measure_suites(str(REPO)); N17 = len(NOW17); A17, B17 = sorted(NOW17)[:2]
TIMED17 = sorted(((n, round(SECONDS[n] / 60, 2)) for n in NOW17 if n in SECONDS), key=lambda x: (-x[1], x[0]))
SER17 = round(sum(m for _, m in TIMED17), 2)
check("(the control: the fake repository has suites, some of them timed and some not, for the checks below)", N17 >= 3 and 0 < len(TIMED17) < N17, (N17, TIMED17))

# (a) SECONDS_MAX: 31,622,400 s is a time, one second more is not
r = run("--map", str(edge_map("sec-edge", {A17: 31622400, B17: 31622401})), "--state-dir", str(T / "st22"), "--dry-run", "--json")
j = json.loads(r.stdout) if r.returncode == 0 else {}
check("a suite time of exactly 31622400 s (366 days) is timed, at 527040.0 min", r.returncode == 0 and j.get("timed") == [[A17, 527040.0]] and j.get("serial_minutes") == 527040.0, (r.returncode, r.stdout[:300], r.stderr))
check("a suite time of 31622401 s is ignored and counted as untimed: every suite but one is untimed", j.get("untimed") == N17 - 1 and len(j.get("timed", [])) == 1, (j.get("untimed"), j.get("timed")))
check("the note for 31622401 s names that suite, in the whole text",
      j.get("notes") == ["suite times ignored (negative, not a finite number or above a year), counted as untimed: " + B17], j.get("notes"))
r = run("--map", str(edge_map("sec-edge2", {A17: 31622400.5})), "--state-dir", str(T / "st22"), "--dry-run", "--json")
j = json.loads(r.stdout)
check("a float time of 31622400.5 s is above the limit as well", j["timed"] == [] and j["notes"] and j["notes"][0].endswith(": " + A17), (j["timed"], j["notes"]))

# (b) THRESHOLD_MAX: 10**12 is a limit, one more is refused by name
for key in ("max_suites", "max_serial_minutes", "max_suite_minutes", "max_test_line_growth"):
    CONF.write_text(f"{key} = 1000000000000\n")
    r = run("--map", str(MAP), "--dry-run", "--json", "--state-dir", str(T / "st23"), "--config", str(CONF))
    j = json.loads(r.stdout) if r.returncode == 0 else {}
    check(f"{key} = 1000000000000 (the maximum) is accepted and kept as the limit", r.returncode == 0 and j.get("thresholds", {}).get(key) == 10 ** 12 and j.get("triggers") == [], (r.returncode, r.stderr[-300:]))
    for over in ("1000000000001", "1000000000000.5"):
        CONF.write_text(f"{key} = {over}\n")
        r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st23"), "--config", str(CONF))
        check(f"{key} = {over} (above the maximum) is refused: exit 2, naming the key and the maximum, nothing on stdout",
              r.returncode == 2 and r.stdout == "" and f"{key} must be a number from 0 to 1000000000000, got " in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stdout[:100], r.stderr[-300:]))
CONF.write_text("[fakerepo]\nmax_suites = 1000000000001\n")
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st23"), "--config", str(CONF))
check("1000000000001 in the repository's table is refused too", r.returncode == 2 and "max_suites must be a number from 0 to 1000000000000" in r.stderr, (r.returncode, r.stderr[-300:]))


# (c) LIST_MAX = 20: 20 names list whole, 21 list 20 and "and 1 more"; added, deleted and the note of ignored times
def zz(n):
    return [f"zy{i:02d}" for i in range(n)]


def list_lines(n, kind):
    """run the report with n suites added (kind 'added'), n deleted ('deleted') or n with an unusable time ('note'); the matching output line"""
    names = zz(n); st = T / f"st24{kind}{n}"; shutil.rmtree(st, ignore_errors=True)
    try:
        if kind == "added":
            run("--map", str(MAP), "--state-dir", str(st), now="2026-03-01T09:00:00+00:00")
            for x in names:
                suite(x, 1)
            r = run("--map", str(MAP), "--state-dir", str(st), "--dry-run", now="2026-03-08T09:00:00+00:00")
            return names, [l for l in r.stdout.splitlines() if l.startswith("  added:")]
        if kind == "deleted":
            for x in names:
                suite(x, 1)
            run("--map", str(MAP), "--state-dir", str(st), now="2026-03-01T09:00:00+00:00")
            for x in names:
                (REPO / "tests" / f"{x}_scenario.py").unlink()
            r = run("--map", str(MAP), "--state-dir", str(st), "--dry-run", now="2026-03-08T09:00:00+00:00")
            return names, [l for l in r.stdout.splitlines() if l.startswith("  deleted:")]
        for x in names:
            suite(x, 1)
        r = run("--map", str(edge_map(f"neg{n}", {x: -1 for x in names})), "--state-dir", str(st), "--dry-run")
        return names, [l for l in r.stdout.splitlines() if l.startswith("note:")]
    finally:
        for x in names:
            (REPO / "tests" / f"{x}_scenario.py").unlink(missing_ok=True)
        shutil.rmtree(st, ignore_errors=True)


NOTE_HEAD = "note: suite times ignored (negative, not a finite number or above a year), counted as untimed: "
for kind, head in (("added", "  added: "), ("deleted", "  deleted: "), ("note", NOTE_HEAD)):
    names, lines = list_lines(20, kind)
    check(f"exactly 20 names ({kind}) are listed whole, with no 'and N more'", lines == [head + ", ".join(names)], lines)
    names, lines = list_lines(21, kind)
    check(f"21 names ({kind}) list the first 20 and say 'and 1 more'", lines == [head + ", ".join(names[:20]) + ", and 1 more"], lines)
    names, lines = list_lines(25, kind)
    check(f"25 names ({kind}) list the first 20 and say 'and 5 more' (the count is worked out, not a fixed 1)", lines == [head + ", ".join(names[:20]) + ", and 5 more"], lines)
check("names_line at the edge by plain numbers: 20 names whole, 21 cut to 20 and 'and 1 more', 25 cut to 20 and 'and 5 more'",
      TR.names_line("x", zz(20)) == "  x: " + ", ".join(zz(20)) and TR.names_line("x", zz(21)) == "  x: " + ", ".join(zz(20)) + ", and 1 more"
      and TR.names_line("x", zz(25)) == "  x: " + ", ".join(zz(20)) + ", and 5 more", TR.names_line("x", zz(25)))

# (d) a config is a file: a pipe is refused, with a writer or without one, and a hang fails the check (each run has its own 15 s limit)
def run_limited(*args, stdin_text=None):
    """the tool with its own 15 s limit, by its Popen object (only the child this test started): (returncode, stdout, stderr, hung)"""
    e = {"PATH": os.environ["PATH"], "HOME": str(HOME), "TMPDIR": tmp, "LANG": "C.UTF-8"}
    p = subprocess.Popen([sys.executable, TOOL, "--now", "2026-01-05T09:00:00+00:00", "--map", str(MAP), "--dry-run", "--state-dir", str(T / "st25"), *args],
                         stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e, cwd=REPO)
    try:
        try:
            out, err = p.communicate(stdin_text, timeout=15)
            return p.returncode, out, err, False
        except subprocess.TimeoutExpired:
            p.kill(); out, err = p.communicate()
            return p.returncode, out, err, True
    finally:
        if p.poll() is None:
            p.kill(); p.wait()


def open_fds():
    return sorted(os.listdir("/proc/self/fd"))


fifo = T / "fifo.toml"; os.mkfifo(fifo)
try:
    rc, fout, ferr, hung = run_limited("--config", str(fifo))
    check("a FIFO with no writer as the config file does not hang the report (it ends within 15 s)", not hung, "still waiting after 15 s")
    check("a FIFO with no writer: exit 2, one clear line naming the file, nothing on stdout, no traceback",
          not hung and rc == 2 and fout == "" and f"config file {fifo} is a pipe, not a file" in ferr and "Traceback" not in ferr, (rc, fout[:100], ferr[-300:]))
    wfd = os.open(fifo, os.O_RDWR)                  # this test holds the pipe open both ways, so the tool finds a writer with data waiting
    try:
        os.write(wfd, b"max_suites = 7\n")
        rc, fout, ferr, hung = run_limited("--config", str(fifo))
    finally:
        os.close(wfd)
    check("a FIFO with a writer and a config waiting is refused too (a config is a file), without a hang",
          not hung and rc == 2 and fout == "" and f"config file {fifo} is a pipe, not a file" in ferr and "Traceback" not in ferr, (hung, rc, fout[:100], ferr[-300:]))
finally:
    fifo.unlink()
rc, fout, ferr, hung = run_limited("--config", "/dev/stdin", stdin_text="max_suites = 7\n")
check("echo 'max_suites = 7' | tool --config /dev/stdin is refused: exit 2, 'is a pipe, not a file', nothing on stdout, no hang, no traceback",
      not hung and rc == 2 and fout == "" and "config file /dev/stdin is a pipe, not a file" in ferr and "Traceback" not in ferr, (hung, rc, fout[:100], ferr[-300:]))
r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st25"), "--config", "/dev/null")
check("a device that reads as empty (/dev/null) is still a config file with no keys", r.returncode == 0 and "TRIGGER" not in r.stdout and r.stderr == "", (r.returncode, r.stderr[-300:]))
try:
    pty_master, pty_slave = os.openpty()
except OSError:
    pty_master = pty_slave = None
if pty_slave is not None:
    try:
        pty_name = os.ttyname(pty_slave)
        rc, fout, ferr, hung = run_limited("--config", pty_name)
        check("a terminal as the config file: exit 2, 'is not a regular file', no hang, no traceback (the non-blocking flag does not leak into a read)",
              not hung and rc == 2 and fout == "" and f"config file {pty_name} is not a regular file" in ferr and "Traceback" not in ferr, (hung, rc, fout[:100], ferr[-300:]))
    finally:
        os.close(pty_master); os.close(pty_slave)
rc, fout, ferr, hung = run_limited("--config", str(T))
check("a folder as the config file: the message it always had, exit 2, no traceback",
      not hung and rc == 2 and fout == "" and f"cannot read config file {T}: Is a directory" in ferr and "Traceback" not in ferr, (hung, rc, ferr[-300:]))
# no descriptor is left open by a config that is refused or unreadable (50 calls each, so one leak per call shows)
fifo2 = T / "fifo2.toml"; os.mkfifo(fifo2); (T / "bad.toml").write_text("max_suites = \n"); (T / "latin2.toml").write_bytes(b"\xff\xfe")
try:
    for label, target in (("a folder", T), ("a pipe", fifo2), ("a file that is not TOML", T / "bad.toml"), ("a file that is not UTF-8", T / "latin2.toml"), ("a good file", EMPTY_CONF)):
        before = open_fds()
        for _ in range(50):
            try:
                TR.load_thresholds(str(target), "fakerepo", True)
            except TR.Fail:
                pass
        check(f"{label} as the config file leaves no descriptor open after 50 calls", open_fds() == before, (before, open_fds()))
finally:
    fifo2.unlink()

# (e) a limit of zero is zero in every key and is stored as zero (0.0 for a float, 0 for a whole number), never -0.0: only -0.0 differs from what
# a plain comparison with 0 would let through, so it is the pin; 0, 0.0, +0 and -0 are controls (they already were zero)
top17 = TIMED17[0]
for key, line in (("max_suites", f"TRIGGER: max_suites: {N17} suites > 0"), ("max_serial_minutes", f"TRIGGER: max_serial_minutes: {SER17:.1f} serial minutes > 0"),
                  ("max_suite_minutes", f"TRIGGER: max_suite_minutes: {top17[0]} takes {top17[1]:.1f} min ({sum(1 for _, m in TIMED17 if m > 0)} over) > 0")):
    for zero in ("0", "0.0", "-0.0", "+0", "-0"):
        CONF.write_text(f"{key} = {zero}\n")
        r = run("--map", str(MAP), "--dry-run", "--json", "--state-dir", str(T / "st26"), "--config", str(CONF))
        j = json.loads(r.stdout) if r.returncode == 0 else {}
        stored = json.dumps(j.get("thresholds", {}).get(key)); want_stored = "0.0" if "." in zero else "0"
        check(f"{key} = {zero} ({'the pin: -0.0 is stored as zero' if zero == '-0.0' else 'control'}): accepted, the line says '> 0', stored as {want_stored}, no minus sign anywhere",
              r.returncode == 0 and [t["line"] for t in j.get("triggers", [])] == [line] and stored == want_stored and "-0" not in json.dumps(j["thresholds"]) and "-0" not in line,
              (r.returncode, r.stderr[-200:], j.get("triggers"), j.get("thresholds")))
st26 = T / "st26g"; run("--map", str(MAP), "--state-dir", str(st26), now="2026-03-01T09:00:00+00:00"); suite("zg1", 1)
for zero in ("0", "0.0", "-0.0"):
    CONF.write_text(f"max_test_line_growth = {zero}\n")
    r = run("--map", str(MAP), "--state-dir", str(st26), "--dry-run", "--json", "--config", str(CONF), now="2026-03-08T09:00:00+00:00")
    j = json.loads(r.stdout) if r.returncode == 0 else {}
    check(f"max_test_line_growth = {zero} ({'the pin' if zero == '-0.0' else 'control'}): one added line triggers, '> 0', stored as {'0.0' if '.' in zero else '0'}",
          r.returncode == 0 and [t["line"] for t in j.get("triggers", [])] == ["TRIGGER: max_test_line_growth: +1 test lines per week > 0"]
          and json.dumps(j["thresholds"]["max_test_line_growth"]) == ("0.0" if "." in zero else "0"), (r.returncode, r.stderr[-200:], j.get("triggers"), j.get("thresholds")))
(REPO / "tests" / "zg1_scenario.py").unlink()
CONF.write_text(f"max_suites = {N17}\n"); r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st26"), "--config", str(CONF))
check("(the control: a limit equal to the count does not trigger, so the zero cases above are the limit's doing)", "TRIGGER" not in r.stdout, r.stdout)
CONF.write_text("")

# (f) a config file with a byte order mark, and one in UTF-16: a clear failure each, never a traceback (the tool does not strip a mark)
for label, raw, want in (("a UTF-8 byte order mark", b"\xef\xbb\xbfmax_suites = 5\n", "is not valid TOML"),
                         ("UTF-16 with its byte order mark", "max_suites = 5\n".encode("utf-16"), "is not UTF-8 text"),
                         ("UTF-16 without a byte order mark", "max_suites = 5\n".encode("utf-16-le"), "is not valid TOML")):
    bom = T / "bom.toml"; bom.write_bytes(raw)
    r = run("--map", str(MAP), "--dry-run", "--state-dir", str(T / "st27"), "--config", str(bom))
    check(f"a config in {label}: exit 2, '{want}', the file named, nothing on stdout, no traceback",
          r.returncode == 2 and r.stdout == "" and want in r.stderr and str(bom) in r.stderr and "Traceback" not in r.stderr and not (T / "st27").exists(), (r.returncode, r.stdout[:100], r.stderr[-300:]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
