"""tests/trim_open_scenario.py - the item a weekly test-trim report opens when a threshold is passed (tools/test_trim_report.py, the step after the TRIGGER lines).

Run on a fake repository in a scratch folder, with HOME and the XDG folders inside it and a FAKE CLIENT (`--client`) that records its arguments and answers as told: no
network, no server. The real client is only used for what it checks by itself (its usage line, the arguments the report builds), never for a call that reaches a server.

  1  no trigger: no call, no item line, status 0, the state file written as always
  2  one trigger: exactly one call; the route's arguments (project, mover, a step that starts with the mover, a marker the route takes), at most 7 description lines of at most
     118 characters naming the repository, the threshold with its value and its limit, and the state file; the item's id is printed after the report
  3  the marker: stable for a repository and a trigger set (a repeat run sends the same one), another trigger set or repository gives another, the short names come in the
     order suites, serial, slowest, growth; odd repository names stay inside the marker's characters and length
  4  --no-open and --dry-run: what would be sent is printed, nothing is called, the state is written (or not, for a dry run), status 0
  5  a failed call: the refusal text on stderr, status 3, the report still printed and the state written, ONE call (no retry); an empty answer, a client that cannot be run and a
     client that does not answer in time are the same; a client that prints more than an id is a failure
  6  --json: the record carries item_open (sent or not); a failed call still prints it
  7  the limits: a very long state path, a long repository name and many triggers keep every line within 118 characters and at most 7 lines
  8  the arguments are the real client's: its parser takes them and builds a body the route's checks pass (field by field), and the default client is the checkout's own file
  9  no trigger kind is forgotten: the four thresholds give four short names and one line each

    tests/run-suite trim_open        -> exit 0 / 1"""
import contextlib, io, json, os, pathlib, re, stat, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
sys.path.insert(0, os.path.join(STACK, "tools")); sys.path.insert(0, STACK)
import test_trim_report as TR

tmp = _scratch.mkdtemp(prefix="trimopen-"); T = pathlib.Path(tmp)
TOOL = os.path.join(STACK, "tools", "test_trim_report.py")
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


# ------------------------------------------------------------------ the fake repository, the fake client
REPO = T / "work" / "fakerepo"; (REPO / "tests").mkdir(parents=True)
HOME = T / "home"; HOME.mkdir()
for i in range(1, 11):
    (REPO / "tests" / f"s{i:02d}_scenario.py").write_text("".join(f'check("c{j}", {j} == {j})\n' for j in range(3 + i)))      # 10 suites, 4 .. 13 check lines
MAP = T / "map.json"
MAP.write_text(json.dumps({"format": 1, "commit": "a" * 40, "suites": {f"s{i:02d}": {"ok": True, "seconds": 30.0 * i} for i in range(1, 11)}}))     # 27.5 min, slowest 5.0
CONF = T / "trim.toml"
LOG = T / "client.log"; MODE = T / "client.mode"
CLIENT = T / "fake-client"
CLIENT.write_text(f'''#!{sys.executable}
import json, sys, time
mode = open({str(MODE)!r}).read().split()[0] if __import__("os").path.exists({str(MODE)!r}) else "ok"
with open({str(LOG)!r}, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if mode == "ok":
    print("item-4242")
elif mode == "refuse":
    print("stackshot: item not opened [400] mover 'x' is not a background agent listed on the page", file=sys.stderr); sys.exit(1)
elif mode == "silent":
    sys.exit(1)
elif mode == "empty":
    sys.exit(0)
elif mode == "chatty":
    print("item-1\\nitem-2")
elif mode == "hang":
    time.sleep(60)
''')
CLIENT.chmod(0o755)


def mode(m):
    MODE.write_text(m)


def calls():
    return [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []


def reset():
    if LOG.exists():
        LOG.unlink()
    mode("ok")


def run(*args, now="2026-01-05T09:00:00+00:00", cwd=REPO, client=True, root=REPO):
    e = {"PATH": os.environ["PATH"], "HOME": str(HOME), "TMPDIR": tmp, "LANG": "C.UTF-8"}
    return subprocess.run([sys.executable, TOOL, "--now", now, "--root", str(root), "--map", str(MAP), "--config", str(CONF),
                           *(["--client", str(CLIENT)] if client else []), *args], capture_output=True, text=True, env=e, cwd=cwd, timeout=120)


def parsed(argv):
    """the route's fields out of the client's argv: ['post', 'item-open', marker, '--project', p, ...]"""
    d = {"marker": argv[2], "lines": []}
    i = 3
    while i < len(argv):
        k, v = argv[i], argv[i + 1]
        if k == "--line":
            d["lines"].append(v)
        else:
            d[k[2:]] = v
        i += 2
    return d


MARKER = re.compile(r"[a-z][a-z0-9_.-]{0,39}:[A-Za-z0-9][A-Za-z0-9._/-]{0,79}")        # the route's own rule (docs/client-contract.md, "The marker")
OVER = "max_suites = 5\n"                                                              # 10 suites > 5
ITEMS = "item_project = \"projects/example\"\nitem_mover = \"example-builder\"\n"        # where the item goes: the config file's two keys
DEST = {"item_project": "projects/example", "item_mover": "example-builder"}
ST = T / "st"

# ------------------------------------------------------------------ 1 no trigger: no call
reset(); CONF.write_text("")
r = run("--state-dir", str(ST))
check("no trigger: exit 0, the report printed, no call of the client", r.returncode == 0 and "test-trim report: fakerepo" in r.stdout and calls() == [] and not LOG.exists(), (r.returncode, r.stderr, calls()))
check("no trigger: no item line", "item:" not in r.stdout and r.stderr == "", r.stdout + r.stderr)
check("no trigger: the state file is written as always", (ST / "fakerepo.json").exists())
r = run("--state-dir", str(ST), "--json")
check("no trigger with --json: the record has no item_open", r.returncode == 0 and "item_open" not in json.loads(r.stdout) and calls() == [], r.stdout)

# ------------------------------------------------------------------ 2 one trigger, one call
reset(); CONF.write_text(ITEMS + OVER); shutil_state = T / "st2"
r = run("--state-dir", str(shutil_state))
c = calls()
check("trigger: exit 0 and exactly one call", r.returncode == 0 and len(c) == 1, (r.returncode, r.stderr, c))
d = parsed(c[0]) if c else {"marker": "", "lines": []}
check("trigger: the call is the route's `post item-open <marker> ...` verb", c and c[0][:2] == ["post", "item-open"], c)
check("trigger: project, mover and sender are the fixed ones", d.get("project") == "projects/example" and d.get("mover") == "example-builder"
      and d.get("sender") == "test-trim-report", d)
check("trigger: the step starts with the mover and says what it does", d.get("step", "").startswith("example-builder: ") and "deep scan" in d["step"] and "fakerepo" in d["step"], d.get("step"))
check("trigger: the subject names the work and the repository, with no instance prefix", d.get("subject") == "Deep-scan the fakerepo test suites", d.get("subject"))
check("trigger: the marker is test_trim:<repo>/<short name>", d["marker"] == "test_trim:fakerepo/suites" and MARKER.fullmatch(d["marker"]), d["marker"])
check("trigger: at most 7 lines, each at most 118 characters (a bullet of at most 120)", 1 <= len(d["lines"]) <= 7 and all(0 < len(x) <= 118 for x in d["lines"]), d["lines"])
check("trigger: a line names the repository", any("fakerepo" in x for x in d["lines"]), d["lines"])
check("trigger: a line gives the threshold with its value and its limit", "max_suites: 10 suites > 5" in d["lines"], d["lines"])
check("trigger: a line names the state file with the full report's numbers", any(str(shutil_state / "fakerepo.json") in x for x in d["lines"]), d["lines"])
check("trigger: no line carries a control character or a leading bullet marker", all(not re.search(r"[\x00-\x1f\x7f]", x) and not x.startswith(("-", "*")) for x in d["lines"]), d["lines"])
check("trigger: the report is printed first, then the item's id", r.stdout.index("TRIGGER: max_suites") < r.stdout.index("item: item-4242") and r.stdout.rstrip().endswith("not filed again)"), r.stdout)
check("trigger: the state file keeps the trigger line as before", json.loads((shutil_state / "fakerepo.json").read_text())["triggers"][0]["line"] == "TRIGGER: max_suites: 10 suites > 5")
check("trigger: nothing on stderr", r.stderr == "", r.stderr)

# ------------------------------------------------------------------ 3 the marker
r = run("--state-dir", str(shutil_state), now="2026-01-12T09:00:00+00:00")
c = calls()
check("a repeat run with the same trigger: a second call, with the same marker (the route answers the open item)", len(c) == 2 and parsed(c[1])["marker"] == parsed(c[0])["marker"] and r.returncode == 0, c)
check("a repeat run: the same arguments in the same order but for the numbers that moved", c[0][:5] == c[1][:5] and parsed(c[1])["project"] == parsed(c[0])["project"], c)
CONF.write_text(ITEMS + "max_suites = 5\nmax_serial_minutes = 1\n")
r = run("--state-dir", str(shutil_state), now="2026-01-19T09:00:00+00:00")
m3 = parsed(calls()[-1])["marker"]
check("a trigger kind that was not there before gives another marker", m3 == "test_trim:fakerepo/suites/serial" and m3 != parsed(c[0])["marker"], m3)
CONF.write_text(ITEMS + "max_suites = 5\nmax_serial_minutes = 1\nmax_suite_minutes = 1\nmax_test_line_growth = 0\n")
suite_added = REPO / "tests" / "g01_scenario.py"; suite_added.write_text('check("a", 1)\n' * 30)
try:
    r = run("--state-dir", str(shutil_state), now="2026-01-26T09:00:00+00:00")
finally:
    suite_added.unlink()
d = parsed(calls()[-1])
check("all four kinds: the marker lists them in the order suites, serial, slowest, growth", d["marker"] == "test_trim:fakerepo/suites/serial/slowest/growth" and MARKER.fullmatch(d["marker"]), d["marker"])
check("all four kinds: one description line each, plus the repository line and the state file line (6 lines)", len(d["lines"]) == 6 and [x.split(":")[0] for x in d["lines"][1:5]] == ["max_suites", "max_serial_minutes", "max_suite_minutes", "max_test_line_growth"], d["lines"])
check("all four kinds: still ONE call for the run", len(calls()) == 4 and r.returncode == 0, len(calls()))
CONF.write_text(ITEMS + "max_serial_minutes = 1\n")
r = run("--state-dir", str(shutil_state), now="2026-02-02T09:00:00+00:00")
check("only the serial minutes over: its own marker", parsed(calls()[-1])["marker"] == "test_trim:fakerepo/serial", parsed(calls()[-1])["marker"])
CONF.write_text(ITEMS + OVER)
other = T / "work" / "other-repo.v2"; (other / "tests").mkdir(parents=True)
for p_ in (REPO / "tests").glob("*_scenario.py"):
    (other / "tests" / p_.name).write_text(p_.read_text())
r = run("--state-dir", str(T / "st3b"), root=other, cwd=other)
check("another repository gives another marker (the repository name is in it)", parsed(calls()[-1])["marker"] == "test_trim:other-repo.v2/suites", parsed(calls()[-1])["marker"])
for name, repo_arg in (("a name with spaces and a slash", "my repo/x y"), ("a unicode name", "r\u00e9p\u00f4-\u65e5\u672c"), ("a name of 100 characters", "n" * 100), ("a name with a colon and a quote", "a:b'c"), ("a name that starts with a dot", ".hidden"),
                         ("a name that starts with an underscore", "_x"), ("a name that starts with a hyphen", "-x"), ("a name that starts with a non-ASCII letter", "\u00e9-x"), ("a name of only dots", "...")):
    r = run("--state-dir", str(T / "st3c"), f"--repo={repo_arg}")
    d = parsed(calls()[-1]) if r.returncode == 0 else {"marker": "", "lines": []}
    check(f"marker for {name}: valid for the route, at most 80 characters after the colon, still ends with the trigger name", r.returncode == 0 and MARKER.fullmatch(d["marker"]) and d["marker"].endswith("/suites")
          and len(d["marker"].split(":", 1)[1]) <= 80, (r.returncode, r.stderr, d["marker"]))
long_repo = "n" * 100
r = run("--state-dir", str(T / "st3d"), f"--repo={long_repo}")
d = parsed(calls()[-1])
check("a 100-character repository name: every line and the subject still fit", all(len(x) <= 118 for x in d["lines"]) and len(d["subject"]) <= 60 and len(d["step"]) <= 140, (d["lines"], d["subject"], d["step"]))

# ------------------------------------------------------------------ 4 --no-open and --dry-run
reset(); n_before = len(calls())
r = run("--state-dir", str(T / "st4"), "--no-open")
check("--no-open: exit 0, no call, the report printed", r.returncode == 0 and calls() == [] and "TRIGGER: max_suites" in r.stdout, (r.returncode, r.stderr, calls()))
check("--no-open: what would be sent is printed (marker, project, mover, subject, step and every line)", "item: not sent" in r.stdout and "marker:  test_trim:fakerepo/suites" in r.stdout and "project: projects/example" in r.stdout
      and "mover:   example-builder" in r.stdout and "subject: Deep-scan the fakerepo test suites" in r.stdout and "step:    example-builder: " in r.stdout
      and "line:    max_suites: 10 suites > 5" in r.stdout and "item: item-" not in r.stdout, r.stdout)
check("--no-open: the state is written as usual", (T / "st4" / "fakerepo.json").exists())
r = run("--state-dir", str(T / "st4d"), "--dry-run")
check("--dry-run: nothing is sent either, the item is shown, and no state is written", r.returncode == 0 and calls() == [] and "item: not sent" in r.stdout and not (T / "st4d" / "fakerepo.json").exists(), (r.stdout, r.stderr))
CONF.write_text("")
r = run("--state-dir", str(T / "st4"), "--no-open")
check("--no-open with no trigger: nothing printed about an item", r.returncode == 0 and "item" not in r.stdout.replace("test-trim report", "") and calls() == [], r.stdout)
CONF.write_text(ITEMS + OVER)
r = run("--state-dir", str(T / "st4"), "--no-open", "--json")
j = json.loads(r.stdout)
check("--no-open --json: item_open says it was not sent and holds the marker and the lines", j["item_open"]["sent"] is False and j["item_open"]["marker"] == "test_trim:fakerepo/suites" and j["item_open"]["lines"][1] == "max_suites: 10 suites > 5" and calls() == [], r.stdout[:400])

# ------------------------------------------------------------------ 4b where the item goes comes from the config file, never from the code
reset(); CONF.write_text(OVER)
r = run("--state-dir", str(T / "st4b"))
check("no item_project and item_mover in the config: status 3 and the reason, no call, the report and the state as usual", r.returncode == 3 and "item_project and item_mover" in r.stderr and calls() == []
      and "TRIGGER: max_suites" in r.stdout and (T / "st4b" / "fakerepo.json").exists(), (r.returncode, r.stderr, calls()))
r = run("--state-dir", str(T / "st4b"), "--no-open")
check("--no-open with no destination in the config: says which key is not set, status 0", r.returncode == 0 and "(item_project is not set)" in r.stdout and "(item_mover is not set)" in r.stdout and calls() == [], r.stdout)
CONF.write_text('item_project = "projects/example"\n' + OVER)
r = run("--state-dir", str(T / "st4b"))
check("only the project set: still status 3 (a mover is needed), no call", r.returncode == 3 and calls() == [], (r.returncode, r.stderr))
CONF.write_text(OVER + 'item_project = "projects/top"\nitem_mover = "top-builder"\n[fakerepo]\nitem_mover = "table-builder"\n')
r = run("--state-dir", str(T / "st4b"))
d = parsed(calls()[-1]) if calls() else {}
check("the repository's table overrides a top-level item key", r.returncode == 0 and d.get("project") == "projects/top" and d.get("mover") == "table-builder" and d.get("step", "").startswith("table-builder: "), (r.stderr, d))
for bad in ('item_mover = 5\n', 'item_mover = "a b"\n', 'item_project = ""\n', 'item_project = "x:y"\n', 'item_mover = "' + "a" * 81 + '"\n'):
    reset(); CONF.write_text(OVER + bad)
    r = run("--state-dir", str(T / "st4b"))
    check(f"a bad item key ({bad[:22].strip()}): config problem, status 2, no call", r.returncode == 2 and "must be a name" in r.stderr and calls() == [], (r.returncode, r.stderr))
reset(); CONF.write_text(ITEMS + OVER)
r = run("--state-dir", str(T / "st4b"))
check("the item keys are known keys: no unknown-key warning", r.returncode == 0 and "unknown key" not in r.stderr, r.stderr)

# ------------------------------------------------------------------ 5 a failed call: the text, status 3, one call, no retry
reset(); mode("refuse")
r = run("--state-dir", str(T / "st5"))
check("a refused call: status 3, the client's refusal text on stderr", r.returncode == 3 and "not a background agent listed on the page" in r.stderr and "was not opened" in r.stderr and "test_trim:fakerepo/suites" in r.stderr, (r.returncode, r.stderr))
check("a refused call: exactly ONE call (no retry, no loop)", len(calls()) == 1, calls())
check("a refused call: the report is still on stdout and the state is written", "TRIGGER: max_suites" in r.stdout and "item: item-" not in r.stdout and (T / "st5" / "fakerepo.json").exists(), r.stdout)
for m_, why in (("silent", "exited 1 and printed nothing"), ("empty", "exited 0 and printed nothing"), ("chatty", "was not opened")):
    reset(); mode(m_)
    r = run("--state-dir", str(T / "st5"), now="2026-02-09T09:00:00+00:00")
    check(f"a client that is {m_}: status 3 with a reason, one call, the report printed", r.returncode == 3 and "was not opened" in r.stderr and len(calls()) == 1 and "TRIGGER: max_suites" in r.stdout, (r.returncode, r.stderr, calls()))
reset(); mode("silent")
r = run("--state-dir", str(T / "st5"), now="2026-02-16T09:00:00+00:00")
check("a client that fails without a word: the reason names its exit status", "the client exited 1 and printed nothing" in r.stderr, r.stderr)
reset(); mode("empty")
r = run("--state-dir", str(T / "st5"), now="2026-02-23T09:00:00+00:00")
check("a client that exits 0 with no id: still a failure, the reason says it printed nothing", r.returncode == 3 and "the client exited 0 and printed nothing" in r.stderr, r.stderr)
reset()
r = run("--state-dir", str(T / "st5"), "--client", str(T / "no-such-client"))
check("a client that cannot be run: status 3 and the reason, the report printed", r.returncode == 3 and "was not opened" in r.stderr and "cannot be run" in r.stderr and "TRIGGER: max_suites" in r.stdout, (r.returncode, r.stderr))
mode("hang"); LOG.unlink(missing_ok=True)
old_timeout = TR.OPEN_TIMEOUT; TR.OPEN_TIMEOUT = 1
try:
    t0 = time.time()
    try:
        TR.file_item(TR.item_request("fakerepo", [{"key": "max_suites", "line": "TRIGGER: max_suites: 10 suites > 5"}], str(T / "st" / "fakerepo.json"), DEST), str(CLIENT), True)
        got = None
    except TR.Fail as e:
        got = (e.code, str(e))
    el = time.time() - t0
finally:
    TR.OPEN_TIMEOUT = old_timeout
check("a client that does not answer in time: status 3, 'did not answer', the call ended at the timeout (not 60 s), one call", got and got[0] == 3 and "did not answer within 1 seconds" in got[1] and el < 20 and len(calls()) == 1, (got, el, calls()))
check("…and the hung client was ended (nothing of it is left to wait for)", el < 20)
reset()
r = run("--state-dir", str(T / "st5"), now="2026-03-02T09:00:00+00:00")
check("after a failure the next run asks again, once, with the same marker (the weekly run is the retry)", r.returncode == 0 and len(calls()) == 1 and "item: item-4242" in r.stdout, (r.returncode, r.stderr, calls()))

# ------------------------------------------------------------------ 5b a failed call is retried next week, even when the numbers of next week trigger nothing
G = REPO / "tests" / "g01_scenario.py"; S5 = T / "st5b"
reset(); CONF.write_text(ITEMS + "max_test_line_growth = 25\n")
try:
    r = run("--state-dir", str(S5), now="2026-04-06T09:00:00+00:00")
    check("week 0 (the baseline): no trigger, no call", r.returncode == 0 and calls() == [] and "open_pending" not in (S5 / "fakerepo.json").read_text(), (r.stdout, r.stderr))
    G.write_text('check("a", 1)\n' * 30)                          # +30 test lines: over the growth limit of 25 a week
    mode("refuse")
    r = run("--state-dir", str(S5), now="2026-04-13T09:00:00+00:00")
    rec = json.loads((S5 / "fakerepo.json").read_text())
    check("week 1: the growth trigger fires, the call is refused: status 3, one call, the report printed", r.returncode == 3 and len(calls()) == 1 and "TRIGGER: max_test_line_growth" in r.stdout, (r.returncode, r.stderr, calls()))
    check("week 1: the state records the owed item (the growth trigger with its line) and moves its baseline on", [t["key"] for t in rec.get("open_pending", [])] == ["max_test_line_growth"] and rec["test_lines"] == sum(rec["suites"].values())
          and rec["open_pending"][0]["line"].startswith("TRIGGER: max_test_line_growth: +30"), rec.get("open_pending"))
    week1 = parsed(calls()[0])
    mode("ok")
    r = run("--state-dir", str(S5), "--no-open", now="2026-04-20T09:00:00+00:00")
    check("week 2 with --no-open: nothing is sent, the owed item is shown, and the debt stays in the state", r.returncode == 0 and len(calls()) == 1 and "item: not sent" in r.stdout and "max_test_line_growth: +30" in r.stdout
          and [t["key"] for t in json.loads((S5 / "fakerepo.json").read_text()).get("open_pending", [])] == ["max_test_line_growth"], (r.stdout, r.stderr))
    r = run("--state-dir", str(S5), "--dry-run", now="2026-04-20T09:00:00+00:00")
    check("week 2 with --dry-run: nothing is sent and the state is not touched", len(calls()) == 1 and [t["key"] for t in json.loads((S5 / "fakerepo.json").read_text()).get("open_pending", [])] == ["max_test_line_growth"], (r.stdout, r.stderr))
    r = run("--state-dir", str(S5), now="2026-04-20T09:00:00+00:00")
    week2 = parsed(calls()[-1]) if len(calls()) == 2 else {}
    check("week 2: no growth of its own (no TRIGGER line), yet the owed item is asked for: one call, with the same marker as week 1", r.returncode == 0 and len(calls()) == 2 and "TRIGGER:" not in r.stdout
          and week2.get("marker") == week1["marker"] == "test_trim:fakerepo/growth", (r.returncode, r.stdout, r.stderr, calls()))
    check("week 2: the same description line for the growth, the note says an item was owed, and the item's id is printed", "max_test_line_growth: +30" in " ".join(week2.get("lines", [])) and "still owed" in r.stdout and "item: item-4242" in r.stdout, r.stdout)
    check("week 2: the debt is cleared once the item is opened", "open_pending" not in (S5 / "fakerepo.json").read_text(), (S5 / "fakerepo.json").read_text()[:200])
    r = run("--state-dir", str(S5), now="2026-04-27T09:00:00+00:00")
    check("week 3: nothing owed and no trigger: no call", r.returncode == 0 and len(calls()) == 2 and "item" not in r.stdout.replace("test-trim report", ""), (r.stdout, calls()))
    # a failure, then a run with another trigger of its own: one item, asked for both (the owed one and the new one, in the thresholds' order)
    S5c = T / "st5c"; reset(); CONF.write_text(ITEMS + "max_test_line_growth = 25\nmax_serial_minutes = 1000\n")
    G.unlink(); run("--state-dir", str(S5c), now="2026-05-04T09:00:00+00:00")
    G.write_text('check("a", 1)\n' * 30); mode("refuse")
    run("--state-dir", str(S5c), now="2026-05-11T09:00:00+00:00")
    mode("ok"); CONF.write_text(ITEMS + "max_test_line_growth = 25\nmax_serial_minutes = 1\n")
    r = run("--state-dir", str(S5c), now="2026-05-18T09:00:00+00:00")
    d = parsed(calls()[-1])
    check("an owed trigger and a new one of the next run go into ONE call, one marker with both names in the thresholds' order", r.returncode == 0 and len(calls()) == 2 and d["marker"] == "test_trim:fakerepo/serial/growth", (r.returncode, calls()[-1:], r.stderr))
    # the same threshold owed and fired again: the new run's numbers are the ones sent
    S5e = T / "st5e"; G2 = REPO / "tests" / "g02_scenario.py"; reset(); CONF.write_text(ITEMS + "max_test_line_growth = 25\n")
    G.unlink(); run("--state-dir", str(S5e), now="2026-05-04T09:00:00+00:00")
    G.write_text('check("a", 1)\n' * 30); mode("refuse")
    run("--state-dir", str(S5e), now="2026-05-11T09:00:00+00:00")
    mode("ok"); G2.write_text('check("a", 1)\n' * 40)
    try:
        r = run("--state-dir", str(S5e), now="2026-05-18T09:00:00+00:00")
    finally:
        G2.unlink(missing_ok=True)
    d = parsed(calls()[-1]) if len(calls()) == 2 else {"lines": []}
    check("a threshold owed and over again: ONE line for it, with this run's numbers (+40), not the old ones", r.returncode == 0 and len(calls()) == 2 and sum("max_test_line_growth" in x for x in d["lines"]) == 1
          and any("+40 test lines" in x for x in d["lines"]) and not any("+30 test lines" in x for x in d["lines"]), (r.returncode, d["lines"]))
    # a damaged debt in the state is ignored
    S5d = T / "st5d"; reset(); CONF.write_text(ITEMS + OVER); G.unlink()
    run("--state-dir", str(S5d), "--no-open", now="2026-06-01T09:00:00+00:00")
    rec = json.loads((S5d / "fakerepo.json").read_text()); rec["open_pending"] = ["x", {"key": "bogus", "line": "TRIGGER: bogus"}, {"key": "max_suites", "line": 5}, 7]
    (S5d / "fakerepo.json").write_text(json.dumps(rec))
    CONF.write_text(ITEMS)
    r = run("--state-dir", str(S5d), now="2026-06-08T09:00:00+00:00")
    check("a damaged open_pending in the state is ignored: no trigger, no call, status 0", r.returncode == 0 and calls() == [], (r.returncode, r.stdout, r.stderr, calls()))
finally:
    G.unlink(missing_ok=True)
CONF.write_text(ITEMS + OVER)

# ------------------------------------------------------------------ 6 --json
reset()
r = run("--state-dir", str(T / "st6"), "--json")
j = json.loads(r.stdout) if r.returncode == 0 else {}
check("--json: item_open is sent with the id, the call made once", j.get("item_open", {}).get("sent") is True and j["item_open"]["item"] == "item-4242" and len(calls()) == 1 and r.stdout.count("\n") == 1, (r.returncode, r.stdout[:300]))
reset(); mode("refuse")
r = run("--state-dir", str(T / "st6"), "--json", now="2026-03-09T09:00:00+00:00")
check("--json with a refused call: status 3, the JSON still on stdout (one line) and the refusal on stderr", r.returncode == 3 and r.stdout.count("\n") == 1 and json.loads(r.stdout)["triggers"] and "was not opened" in r.stderr, (r.returncode, r.stdout[:200], r.stderr))
check("--json state file does not hold the item answer (the state is the report's record only)", "item_open" not in (T / "st6" / "fakerepo.json").read_text())

# ------------------------------------------------------------------ 7 the limits
reset()
deep = T / ("d" * 60) / ("e" * 60) / ("f" * 60)
r = run("--state-dir", str(deep))
d = parsed(calls()[-1])
check("a 180-character state folder: the last line is cut from the front, within 118, and still ends with the file name", r.returncode == 0 and len(d["lines"][-1]) <= 118 and d["lines"][-1].startswith("Full numbers: the report's state file ...") and d["lines"][-1].endswith("fakerepo.json"), d["lines"][-1])
check("…every other line is within 118 characters and there are at most 7", all(len(x) <= 118 for x in d["lines"]) and len(d["lines"]) <= 7, d["lines"])
home_state = HOME / ".local" / "state" / "stackshot" / "test-trim"
r = run()
d = parsed(calls()[-1])
check("a state file under HOME is shown with ~ (no home folder name in the item)", d["lines"][-1] == "Full numbers: the report's state file ~/.local/state/stackshot/test-trim/fakerepo.json" and str(HOME) not in " ".join(d["lines"]), d["lines"][-1])
long_suite = "x" * 80
(REPO / "tests" / f"{long_suite}_scenario.py").write_text('check("a", 1)\n')
try:
    MAP.write_text(json.dumps({"format": 1, "commit": "a" * 40, "suites": {long_suite: {"ok": True, "seconds": 1200.0}}}))
    CONF.write_text(ITEMS + "max_suite_minutes = 1\n")
    r = run("--state-dir", str(T / "st7"))
finally:
    (REPO / "tests" / f"{long_suite}_scenario.py").unlink()
d = parsed(calls()[-1])
check("a trigger line longer than 118 characters (a long suite name) is cut with '...'", r.returncode == 0 and any(x.endswith("...") and len(x) == 118 and x.startswith("max_suite_minutes: ") for x in d["lines"]), d["lines"])

# ------------------------------------------------------------------ 8 the real client takes the arguments
MAP.write_text(json.dumps({"format": 1, "commit": "a" * 40, "suites": {f"s{i:02d}": {"ok": True, "seconds": 30.0 * i} for i in range(1, 11)}})); CONF.write_text(ITEMS + OVER)
from stackshot.fleet import client
bodies = []
real_post = client.post
client.post = lambda what, body, timeout=20.0: (bodies.append((what, body)) or (200, {"item": "item-1"}))
try:
    req = TR.item_request("fakerepo", [{"key": "max_suites", "line": "TRIGGER: max_suites: 10 suites > 5"}, {"key": "max_test_line_growth", "line": "TRIGGER: max_test_line_growth: +30 test lines per week > 25"}], "/x/y/fakerepo.json", DEST)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = client.item_open(TR.request_argv(req)[2:])
finally:
    client.post = real_post
check("the real client's parser takes the arguments the report builds and prints the item id", rc == 0 and buf.getvalue() == "item-1\n" and len(bodies) == 1 and bodies[0][0] == "item-open", (rc, buf.getvalue(), bodies))
b = bodies[0][1] if bodies else {}
check("…the body's keys are the seven the route takes, with nothing else", set(b) <= {"marker", "project", "subject", "description", "step", "mover", "sender"} and {"marker", "project", "subject", "description", "step", "mover"} <= set(b), sorted(b))
check("…marker, sender, step, lines: each passes the route's own rule", MARKER.fullmatch(b["marker"]) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}", b["sender"]) and b["step"].startswith(b["mover"] + ": ")
      and len(b["description"]) <= 7 and all(len("- " + x) <= 120 for x in b["description"]) and len(b["subject"]) <= 60, b)
check("…the arguments of the real call match what the fake client was handed (same builder)", TR.request_argv(req)[:2] == ["post", "item-open"] and TR.request_argv(req).count("--line") == len(req["lines"]))
check("the default client is this checkout's stackshot/fleet/client.py, run with this Python", TR.client_command(None) == [sys.executable, os.path.join(STACK, "stackshot", "fleet", "client.py")] and os.path.isfile(TR.client_command(None)[1]), TR.client_command(None))
check("--client names the program as given", TR.client_command("/x/y") == ["/x/y"])
r = run("--state-dir", str(T / "st8"), client=False)
check("with no --client the real client runs and, with no token on the (fake) home, refuses: status 3, its text on stderr, the report printed", r.returncode == 3 and "was not opened" in r.stderr and "no token on this machine" in r.stderr and "TRIGGER:" in r.stdout, (r.returncode, r.stderr[:400]))

# ------------------------------------------------------------------ 9 the four thresholds
check("the four thresholds have four different short names", sorted(TR.SHORT) == sorted(TR.DEFAULTS) and len(set(TR.SHORT.values())) == 4 and list(TR.SHORT.values()) == ["suites", "serial", "slowest", "growth"], TR.SHORT)
check("--no-open and --client are in the tool's own help", all(f in subprocess.run([sys.executable, TOOL, "--help"], capture_output=True, text=True).stdout for f in ("--no-open", "--client")))

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"{len(ran)}/{len(ran)} checks passed"); sys.exit(0)
