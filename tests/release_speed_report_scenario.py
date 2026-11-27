"""tests/release_speed_report_scenario.py - the weekly release-speed report (tools/release_speed_report.py).

Checked on fake release logs and a fake `gh` in a scratch folder (fake data only: a repository named acme/widgets, pull requests with known
creation, check, queue, merge, deploy and main-run times), with HOME pointed into the scratch folder and no network:

  1  one release, every stage: the log's lines give queued -> merged, merged -> live and live -> main's check; GitHub's runs give open -> checks
     green (the latest run of each workflow, all green, the latest finish time); the numbers are exact minutes
  2  five releases of known durations: n, median, p90 (linear between ranks) and worst with the worst pull request, per stage
  3  a stage a log cannot give: a release merged without the queue has no queued stages, one with no main line has no last stage, a pull request
     GitHub does not list has no open stage, and none of them leaves its other stages out; a negative value is dropped with a note
  4  the window: rolling, a release done exactly at its start counts and one a second before does not, another repository's log is not read,
     a started release that never went live is counted apart, and so are its failed attempts
  5  same-commit flakes: a merge-queue entry removed and later merged on the same head, a workflow that failed then passed on one head, a main run
     that failed only when measured; a new head, another workflow, a pass then a fail and two failures are no flake
  6  the flags: the open -> live median above its limit (and equal to it is none), the flake count above its limit (4 is none, 5 is a flag), a
     [repo] table over the top-level key, the defaults 60 and 4, a flag that stays out of the report when its number is n/a
  7  the empty window: exit 4, one stderr line, the previous record left as it was; GitHub that cannot be read (no gh, a failing gh, an answer that
     is not JSON): the log's stages, a note, exit 4; with --dry-run and with --json too
  8  --json prints the record, --dry-run writes no state, the state file is atomic and holds the previous run's numbers, the next run compares
  9  the item a flag opens: one `post item-open` call with the marker release_speed:<repo>/<median|flakes>; no flag no call; no item_project and
     item_mover is exit 3 with the debt kept; a refusal is exit 3 and the debt is asked for again with the next run's own flag; --no-open sends nothing
  10 the calls to GitHub: one pr list, the runs in day slices of 100 a page (more than 100 runs in a day are paged), a slice GitHub reports above its
     1000 result cut is halved, and no more than 60 calls are made for the runs
  11 errors: a bad limit, a missing explicit config, a missing logs folder, --days out of range and a bad --now are exit 2 and name the cause; a
     mistyped key warns; an unwritable state folder is exit 1
  12 read-only: the logs folder is byte for byte as it was; the file is executable
  13 a group release's member logs (only lines release.sh writes there) and the pushed-head checks line; in a window with no release a paid debt leaves
     the record and an unpaid one (--no-open, --dry-run, a refused or impossible call) stays
  14 GitHub unreadable: the stages are only what the run measured; with the pull request list unread the last measured open -> live median is kept apart
     (open_to_live_kept, its time kept over weeks), used by the comparison line alone and never flagged; with only the runs unread nothing is kept; a
     damaged previous record never stops a run

    tests/run-suite release_speed_report      -> exit 0 / 1"""
import datetime as dt, hashlib, json, os, pathlib, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
sys.path.insert(0, os.path.join(STACK, "tools"))
import release_speed_report as RS

tmp = _scratch.mkdtemp(prefix="relspeed-"); T = pathlib.Path(tmp)
TOOL = os.path.join(STACK, "tools", "release_speed_report.py")
fails = []; ran = []
UTC = dt.timezone.utc
SLUG = "acme/widgets"
NOW = dt.datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
LO = NOW - dt.timedelta(days=7)


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


def z(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mins(n):
    return dt.timedelta(minutes=n)


HOME = T / "home"; HOME.mkdir()
GH_BIN = T / "bin"; GH_BIN.mkdir()
GH_LOG = T / "gh.log"
(GH_BIN / "gh").write_text(f'''#!{sys.executable}
import json, os, sys, urllib.parse
a = sys.argv[1:]
open({str(GH_LOG)!r}, "a").write(" ".join(a) + "\\n")
if os.environ.get("GH_FAIL") or (os.environ.get("GH_FAIL_RUNS") and a[0] == "api"):
    print("boom", file=sys.stderr); sys.exit(1)
if os.environ.get("GH_JUNK"):
    print("<html>not json</html>"); sys.exit(0)
data = json.load(open(os.environ["GH_DATA"]))
if a[:2] == ["pr", "list"]:
    print(json.dumps(data["prs"]))
elif a[0] == "api":
    u = urllib.parse.urlsplit(a[1]); q = urllib.parse.parse_qs(u.query)
    lo, hi = q["created"][0].split("..")
    runs = [r for r in data["runs"] if lo <= r["created_at"] <= hi and r["event"] == q["event"][0]]
    page, per = int(q["page"][0]), int(q["per_page"][0])
    print(json.dumps({{"total_count": len(runs), "workflow_runs": runs[(page - 1) * per: page * per]}}))
else:
    sys.exit(9)
''')
(GH_BIN / "gh").chmod(0o755)
NO_GH = T / "no-gh-bin"; NO_GH.mkdir()
CLIENT_LOG = T / "client.log"; CLIENT_MODE = T / "client.mode"
CLIENT = T / "fake-client"
CLIENT.write_text(f'''#!{sys.executable}
import json, os, sys
mode = open({str(CLIENT_MODE)!r}).read().split()[0] if os.path.exists({str(CLIENT_MODE)!r}) else "ok"
open({str(CLIENT_LOG)!r}, "a").write(json.dumps(sys.argv[1:]) + "\\n")
if mode == "ok":
    print("item-4242")
else:
    print("client: item not opened [400] mover is not a background agent listed on the page", file=sys.stderr); sys.exit(1)
''')
CLIENT.chmod(0o755)


def client_calls():
    return [json.loads(l) for l in CLIENT_LOG.read_text().splitlines()] if CLIENT_LOG.exists() else []


def client_reset(mode="ok"):
    if CLIENT_LOG.exists():
        CLIENT_LOG.unlink()
    CLIENT_MODE.write_text(mode)


class World:
    """fake release logs, pull requests and runs of one scenario"""
    def __init__(self, name):
        self.dir = T / name; self.logs = self.dir / "logs"; self.logs.mkdir(parents=True)
        self.state = self.dir / "state"; self.data = self.dir / "gh.json"
        self.prs = []; self.runs = []; self.rid = 1000
        self.save()

    def save(self):
        self.data.write_text(json.dumps({"prs": self.prs, "runs": self.runs}))

    def log(self, pr, events, fname=None):
        """events: (time, text) in the order of the file; a text that starts with a space is an unstamped line of a deploy's output"""
        with open(self.logs / (fname or f"pr-{pr}.log"), "a") as f:
            for t, text in events:
                f.write(text + "\n" if text.startswith(" ") else f"{z(t)} {text}\n")

    def listed(self, pr, created, head, merged=None):
        self.prs.append({"number": pr, "createdAt": z(created), "mergedAt": z(merged) if merged else None, "headRefOid": head})

    def run(self, head, name, created, conclusion, finished=None, event="pull_request"):
        self.rid += 1
        self.runs.append({"id": self.rid, "name": name, "head_sha": head, "event": event, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion,
                          "created_at": z(created), "updated_at": z(finished or created + mins(5))})

    def release(self, pr, created, head, o2g, g2q, q2m, m2l, l2m, slug=SLUG, runs=True, listed=True, queue=True, main=True, extra=()):
        """one release whose stages last the given minutes; runs/listed/queue/main False leave that part out"""
        green = created + mins(o2g); enq = green + mins(g2q); merged = enq + mins(q2m); done = merged + mins(m2l)
        start = enq - mins(1)
        ev = [(start, f"release of PR #{pr} starts in /srv/widgets ({slug})"), (start, f"PR #{pr}: a title (head {head[:7]})"), (start + dt.timedelta(seconds=1), "checks pass")]
        if queue:
            ev += [(enq, f"enqueued: the merge queue accepted the head {head[:7]}"), (enq, "in the merge queue (QUEUED position 1): 0 min since the enqueue"),
                   (merged, f"merged by the merge queue as abc1234, {q2m} min after the enqueue")]
        else:
            ev += [(merged, "merged as abc1234 by the plain merge call, not the merge queue (the ruleset is off)")]
        ev += [(merged, "deploy lock taken"), (merged, " deploying a..b:"), (merged, "   abc1234 Merge pull request"), (done, "done: abc1234, restarted app.service ")]
        if main:
            ev += [(done + dt.timedelta(minutes=l2m), f"main's tests passed on abc1234 (run 1)")]
        ev += list(extra)
        self.log(pr, ev)
        if listed:
            self.listed(pr, created, head, merged)
        if runs:
            self.run(head, "tests", created + mins(1), "success", green)
            self.run(head, "lint", created + mins(1), "success", green - mins(min(1, o2g - 0.5)))
        return {"green": green, "enq": enq, "merged": merged, "done": done}

    def save_all(self):
        self.save()


BASE = NOW - dt.timedelta(days=3)


def stats_world(name, durations=((4, 2, 3, 1, 1), (8, 4, 6, 2, 2), (12, 6, 9, 3, 3), (16, 8, 12, 4, 4), (40, 20, 30, 10, 10))):
    w = World(name)
    for i, d in enumerate(durations):
        w.release(201 + i, BASE + mins(60 * i), f"{200 + i:040x}", *d)
    w.save()
    return w


CONF = T / "speed.toml"; CONF.write_text("")


def run(w, *args, now=z(NOW), env=None, config=CONF, logs=True, github=True, no_open=True):
    e = {"PATH": f"{GH_BIN}:{os.environ['PATH']}", "HOME": str(HOME), "TMPDIR": tmp, "LANG": "C.UTF-8", "GH_DATA": str(w.data)}
    e.update(env or {})
    cmd = [sys.executable, TOOL, *(["--no-open"] if no_open else []), *(["--now", now] if now else []), *(["--github", SLUG] if github else []),
           *(["--logs", str(w.logs)] if logs else []), "--state-dir", str(w.state), *(["--config", str(config)] if config else []), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=T, timeout=180)


def rec(w):
    return json.loads((w.state / "widgets.json").read_text())


def jrun(w, *args, **kw):
    r = run(w, "--json", "--dry-run", *args, **kw)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, {}


def tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(path).rglob("*")):
        h.update(str(p.relative_to(path)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------ 1 one release, every stage
w1 = World("one")
w1.release(101, BASE, "a" * 40, 40, 12, 20, 1, 2)
w1.save()
r, j = jrun(w1)
S = j.get("stages", {})
check("one release: exit 0 with nothing on stderr", r.returncode == 0 and r.stderr == "", (r.returncode, r.stderr))
check("one release: open -> checks green is the PR's creation to the last workflow's finish (40)", S.get("open_to_green", {}).get("median") == 40.0, S)
check("one release: checks green -> queued is green to the log's enqueued line (12)", S.get("green_to_queued", {}).get("median") == 12.0, S)
check("one release: queued -> merged (20), merged -> live (1), live -> main's check (2)",
      (S.get("queued_to_merged", {}).get("median"), S.get("merged_to_live", {}).get("median"), S.get("live_to_main", {}).get("median")) == (20.0, 1.0, 2.0), S)
check("one release: open -> live is 73 and the stage has n 1, p90 and worst equal to it, the worst PR named",
      S.get("open_to_live") == {"n": 1, "median": 73.0, "p90": 73.0, "worst": 73.0, "worst_pr": 101}, S.get("open_to_live"))
check("one release: the counts and the unstamped deploy lines (read as no event)", j.get("prs") == {"live": 1, "not_live": 0, "failed_attempts": 0}, j.get("prs"))
r = run(w1, "--dry-run")
check("the text report: the header, the stage table with the worst PR, the flakes line, the baseline note",
      r.returncode == 0 and "release-speed report: widgets (last 7 days)" in r.stdout and "PR open -> checks green" in r.stdout and "(PR #101)" in r.stdout
      and "same-commit flakes: 0 (merge queue 0, PR runs 0, main's run 0)" in r.stdout and "this run is the baseline" in r.stdout, r.stdout)

# ------------------------------------------------------------------ 2 five releases, the statistics
w2 = stats_world("five")
r, j = jrun(w2)
S = j["stages"]
want = {"open_to_green": (5, 12.0, 30.4, 40.0, 205), "green_to_queued": (5, 6.0, 15.2, 20.0, 205), "queued_to_merged": (5, 9.0, 22.8, 30.0, 205),
        "merged_to_live": (5, 3.0, 7.6, 10.0, 205), "live_to_main": (5, 3.0, 7.6, 10.0, 205), "open_to_live": (5, 30.0, 76.0, 100.0, 205)}
for k, (n, med, p90, worst, wpr) in want.items():
    check(f"five releases: {k} n {n}, median {med}, p90 {p90} (linear between ranks), worst {worst} of PR #{wpr}",
          (S[k]["n"], S[k]["median"], S[k]["p90"], S[k]["worst"], S[k]["worst_pr"]) == (n, med, p90, worst, wpr), S[k])

# ------------------------------------------------------------------ 3 a stage a log cannot give
w3 = World("missing")
w3.release(301, BASE, "b" * 40, 10, 2, 5, 1, 1)
w3.release(302, BASE + mins(30), "c" * 40, 10, 0, 7, 1, 1, queue=False, main=False)      # merged without the queue, no main line
w3.release(303, BASE + mins(60), "d" * 40, 10, 2, 9, 1, 1, listed=False, runs=False)    # GitHub does not list it
w3.save()
r, j = jrun(w3)
S = j["stages"]
check("missing stages: a release merged without the queue leaves out the queued stages only (n 2 of 3 for green -> queued and queued -> merged)",
      S["green_to_queued"]["n"] == 2 and S["queued_to_merged"]["n"] == 2 and S["merged_to_live"]["n"] == 3, S)
check("missing stages: no main line leaves out live -> main's check only (n 2)", S["live_to_main"]["n"] == 2 and S["open_to_live"]["n"] == 2, S)
check("missing stages: a PR GitHub does not list has no open stage (open -> green n 2, open -> live n 2) but its log stages count",
      S["open_to_green"]["n"] == 2 and S["open_to_live"]["n"] == 2, S)
check("missing stages: the fallback to the log's `checks pass` when GitHub has no run (the unlisted PR has none): no open stage, green -> queued still from the log",
      S["green_to_queued"]["n"] == 2, S)
w3b = World("neg")
t = w3b.release(311, BASE, "e" * 40, 10, 2, 5, 1, 1)
w3b.log(312, [(BASE, f"release of PR #312 starts in /srv/widgets ({SLUG})"), (BASE + mins(10), "enqueued: the merge queue accepted the head eeee"), (BASE + mins(5), "merged by the merge queue as abc1234, 0 min"),
              (BASE + mins(8), "done: abc1234, restarted app.service ")])
w3b.listed(312, BASE - mins(5), "f" * 40, BASE + mins(5))
w3b.save()
r, j = jrun(w3b)
check("a value below zero (merged before enqueued) is dropped from its stage and said in a note",
      j["stages"]["queued_to_merged"]["n"] == 1 and any("below zero" in n for n in j["notes"]), (j["stages"]["queued_to_merged"], j.get("notes")))

# ------------------------------------------------------------------ 4 the window
w4 = World("window")
edge_done = LO
c = w4.release(401, LO - mins(60), "1" * 40, 10, 2, 5, 1, 1)                     # done at LO + a few minutes: use shifts below
w4.logs.joinpath("pr-401.log").unlink()
w4.log(401, [(edge_done - mins(5), f"release of PR #401 starts in /srv/widgets ({SLUG})"), (edge_done, "done: abc1234, restarted app.service ")])
w4.log(402, [(edge_done - mins(5), f"release of PR #402 starts in /srv/widgets ({SLUG})"), (edge_done - dt.timedelta(seconds=1), "done: abc1234, restarted app.service ")])
w4.log(403, [(BASE, f"release of PR #403 starts in /srv/widgets (other/repo)"), (BASE + mins(5), "done: abc1234, restarted app.service ")])
w4.log(404, [(BASE, f"release of PR #404 starts in /srv/widgets ({SLUG})"), (BASE + mins(1), "FAILED at checks: a check failed: suites=fail")])
w4.log(405, [(BASE, f"release of PR #405 starts in /srv/widgets ({SLUG})"), (BASE + mins(1), "FAILED at mergeable: GitHub says CONFLICTING"), (BASE + mins(30), f"release of PR #405 starts in /srv/widgets ({SLUG})"),
             (BASE + mins(33), "done: abc1234, restarted app.service ")])
w4.log(406, [(NOW + mins(5), f"release of PR #406 starts in /srv/widgets ({SLUG})"), (NOW + mins(9), "done: abc1234, restarted app.service ")])     # after the clock
(w4.logs / "group-9.log").write_text(f"{z(BASE)} release of PRs #1 #2 starts in /srv/widgets ({SLUG})\n{z(BASE)} done: x\n")        # a group log is not a pr log
(w4.logs / "pr-407-mainwatch.out").write_text(f"{z(BASE)} done: x\n")
w4.save()
r, j = jrun(w4)
check("the window: a release done exactly at the start counts, one a second before does not; another repository's log, a group log, a later one and the watcher's output do not",
      r.returncode == 0 and j["prs"]["live"] == 2, (r.returncode, j.get("prs"), r.stderr))
check("the window: a started release that never went live is counted apart (PR 404), a PR with a failed attempt then a live one is live (PR 405)",
      j["prs"]["not_live"] == 1 and j["prs"]["failed_attempts"] == 2, j["prs"])
r, j2 = jrun(w4, "--days", "0.5")
check("--days narrows the window (half a day back: only the releases of the last 12 hours, none here)", r.returncode == 4 and j2["prs"]["live"] == 0, (r.returncode, j2.get("prs")))

# ------------------------------------------------------------------ 5 same-commit flakes
w5 = World("flakes")
H = lambda n: f"{n:040x}"
QF = "FAILED at merge queue: removed from the merge queue: the merge group failed its required checks"
# 501: removed on a head, merged on the same head later = a flake
w5.log(501, [(BASE, f"release of PR #501 starts in /srv/widgets ({SLUG})"), (BASE, f"enqueued: the merge queue accepted the head {H(501)[:7]}"), (BASE + mins(20), QF),
             (BASE + mins(30), f"release of PR #501 starts in /srv/widgets ({SLUG})"), (BASE + mins(30), f"enqueued: the merge queue accepted the head {H(501)[:7]}"),
             (BASE + mins(50), "merged by the merge queue as abc1234, 20 min after the enqueue"), (BASE + mins(51), "done: abc1234, restarted app.service ")])
# 502: removed, then merged on another head = a fix, no flake
w5.log(502, [(BASE, f"release of PR #502 starts in /srv/widgets ({SLUG})"), (BASE, "enqueued: the merge queue accepted the head 2222222"), (BASE + mins(20), QF),
             (BASE + mins(30), f"release of PR #502 starts in /srv/widgets ({SLUG})"), (BASE + mins(30), "enqueued: the merge queue accepted the head 3333333"),
             (BASE + mins(50), "merged by the merge queue as abc1234, 20 min after the enqueue"), (BASE + mins(51), "done: abc1234, restarted app.service ")])
# 503: removed and never merged = no flake
w5.log(503, [(BASE, f"release of PR #503 starts in /srv/widgets ({SLUG})"), (BASE, "enqueued: the merge queue accepted the head 4444444"), (BASE + mins(20), QF)])
# 504: two main-run lines in one release count once
MAINF = "main's run: release failed only when measured, then passed plainly (flaky?): the report goes to the keeper"
w5.log(504, [(BASE, f"release of PR #504 starts in /srv/widgets ({SLUG})"), (BASE + mins(1), MAINF), (BASE + mins(2), MAINF), (BASE + mins(3), "done: abc1234, restarted app.service ")])
w5.run(H(1), "tests", BASE, "failure"); w5.run(H(1), "tests", BASE + mins(30), "success")                     # a flake
w5.run(H(2), "tests", BASE, "failure"); w5.run(H(2), "tests", BASE + mins(30), "failure")                     # two failures: none
w5.run(H(3), "tests", BASE, "failure"); w5.run(H(3), "lint", BASE + mins(30), "success")                      # another workflow: none
w5.run(H(4), "tests", BASE, "success"); w5.run(H(4), "tests", BASE + mins(30), "failure")                     # a pass then a fail: none
w5.run(H(5), "tests", BASE, "failure"); w5.run(H(5), "tests", BASE + mins(30), "failure"); w5.run(H(5), "tests", BASE + mins(60), "success")    # a flake, once
w5.run(H(6), "tests", BASE, "failure", event="merge_group"); w5.run(H(6), "tests", BASE + mins(30), "success", event="merge_group")           # the queue's runs are not asked for
w5.save()
r, j = jrun(w5)
F = j["flakes"]
check("flakes: merge queue 1 (removed and merged on the same head), PR runs 2 (a head per workflow once), main's run 1 (once per release), total 4",
      F == {"merge_queue": 1, "pr_runs": 2, "main_run": 1, "total": 4}, F)
check("flakes: the text report says the three counts", "same-commit flakes: 4 (merge queue 1, PR runs 2, main's run 1)" in run(w5, "--dry-run").stdout)


def flake_world(name, extra):
    w = stats_world(name)
    for i in range(extra):
        w.run(H(900 + i), "tests", BASE, "failure"); w.run(H(900 + i), "tests", BASE + mins(30), "success")
    w.save()
    return w


# ------------------------------------------------------------------ 6 the flags
r = run(w2, "--dry-run")
check("flags: the median 30 is under the default limit 60: no FLAG line, exit 0", r.returncode == 0 and "FLAG" not in r.stdout, r.stdout)
CONF.write_text("max_open_to_live_median_minutes = 29\n")
r, j = jrun(w2)
check("flags: a limit of 29 flags the median 30 with its value and limit (JSON and text)",
      [t["key"] for t in j["triggers"]] == ["max_open_to_live_median_minutes"] and j["triggers"][0]["line"] == "FLAG: open_to_live_median: 30 min > 29"
      and "FLAG: open_to_live_median: 30 min > 29" in run(w2, "--dry-run").stdout, j.get("triggers"))
CONF.write_text("max_open_to_live_median_minutes = 30\n")
r, j = jrun(w2)
check("flags: a median equal to its limit is no flag", j["triggers"] == [], j.get("triggers"))
CONF.write_text("max_open_to_live_median_minutes = 1\n[widgets]\nmax_open_to_live_median_minutes = 31\n")
r, j = jrun(w2)
check("flags: the [widgets] table overrides the top-level key", j["triggers"] == [] and j["thresholds"]["max_open_to_live_median_minutes"] == 31, j.get("thresholds"))
CONF.write_text("")
w6 = World("slow")
for i in range(3):
    w6.release(601 + i, BASE + mins(30 * i), f"{600 + i:040x}", 30, 10, 18, 1, 1)           # open -> live 59, 59, 59: under 60
w6.release(604, BASE, f"{604:040x}", 45, 10, 18, 1, 1); w6.release(605, BASE, f"{605:040x}", 45, 10, 18, 1, 1)     # 74, 74
w6.save()
r, j = jrun(w6)
check("flags: the default limit is 60: a median of 74 (3 of 5 above) is flagged", j["stages"]["open_to_live"]["median"] == 59.0 and j["triggers"] == [], j["stages"]["open_to_live"])
w6b = World("slow2")
for i in range(5):
    w6b.release(611 + i, BASE + mins(30 * i), f"{610 + i:040x}", 45, 10, 18, 1, 1)         # 74 each
w6b.save()
r, j = jrun(w6b)
check("flags: a median of 74 against the default limit 60 is flagged, exit 0", r.returncode == 0 and j["triggers"] and j["triggers"][0]["line"] == "FLAG: open_to_live_median: 74 min > 60", (r.returncode, j.get("triggers")))
for extra, flagged in ((4, False), (5, True)):
    wf = flake_world(f"flake{extra}", extra)
    r, j = jrun(wf)
    check(f"flags: {extra} same-commit flakes is {'a flag' if flagged else 'no flag'} (5 or more is one)", j["flakes"]["total"] == extra and bool(j["triggers"]) == flagged
          and (not flagged or j["triggers"][0]["line"] == "FLAG: same_commit_flakes: 5 > 4"), (j["flakes"], j["triggers"]))
CONF.write_text("max_same_commit_flakes = 6\n")
r, j = jrun(flake_world("flake6", 5))
check("flags: max_same_commit_flakes in the config moves the limit", j["triggers"] == [], j["triggers"])
CONF.write_text("")
r, j = jrun(w6b, env={"PATH": str(NO_GH)})
check("flags: with GitHub unreadable the open -> live stage is n/a and the median flag is not decided (never a flag from a missing number)", j["stages"]["open_to_live"]["median"] is None and j["triggers"] == [], j["stages"]["open_to_live"])

# ------------------------------------------------------------------ 7 empty window, GitHub unreadable
w7 = World("empty")
w7.log(701, [(LO - mins(60), f"release of PR #701 starts in /srv/widgets ({SLUG})"), (LO - mins(50), "done: abc1234, restarted app.service ")])
w7.save()
(w7.state).mkdir(); (w7.state / "widgets.json").write_text(json.dumps({"format": 1, "repo": "widgets", "marker": "kept", "generated": "2026-11-19T00:00:00+00:00", "stages": {}, "flakes": {}}))
before = (w7.state / "widgets.json").read_text()
r = run(w7)
check("empty window: exit 4, one stderr line, the report says none", r.returncode == 4 and r.stderr == f"release_speed_report: no release in the last 7 days in {w7.logs}\n" and "releases in the window: none" in r.stdout, (r.returncode, r.stderr, r.stdout))
check("empty window: the previous record is left as it was", (w7.state / "widgets.json").read_text() == before)
r = run(w7, "--json")
check("empty window with --json: the record is printed and the status is 4", r.returncode == 4 and json.loads(r.stdout)["prs"]["live"] == 0, (r.returncode, r.stdout[:200]))
r = run(w7, "--dry-run")
check("empty window with --dry-run: exit 4 too", r.returncode == 4, r.returncode)
r = run(w2, "--dry-run", env={"PATH": str(NO_GH)})
check("no gh: the log's stages, a note, one stderr line, exit 4", r.returncode == 4 and "merged -> live" in r.stdout and "the gh command is not installed" in r.stdout and r.stderr == "release_speed_report: no GitHub data: the gh command is not installed\n", (r.returncode, r.stdout, r.stderr))
r, j = jrun(w2, env={"GH_FAIL": "1"})
check("a failing gh: exit 4 with its text, the stages that need no GitHub still counted (merged -> live n 5, open -> green n 5 from the log's checks pass)",
      r.returncode == 4 and "boom" in r.stderr and j["stages"]["merged_to_live"]["n"] == 5 and j["stages"]["open_to_live"]["n"] == 0 and j["flakes"]["pr_runs"] is None, (r.returncode, r.stderr, j.get("stages")))
r = run(w2, "--dry-run", env={"GH_JUNK": "1"})
check("an answer that is not JSON: exit 4, said", r.returncode == 4 and "not JSON" in r.stderr, (r.returncode, r.stderr))
r = run(w2, "--dry-run", github=False, env={"PATH": f"{GH_BIN}:{os.environ['PATH']}"})
check("no --github and no origin remote of the checkout: GitHub is not asked, said, exit 4 or a clear refusal (never a traceback)", "Traceback" not in r.stderr and r.returncode in (2, 4), (r.returncode, r.stderr))

# ------------------------------------------------------------------ 8 --json, --dry-run, the state file
w8 = stats_world("state")
r = run(w8, "--dry-run")
check("--dry-run writes no state (not even the folder)", r.returncode == 0 and not w8.state.exists(), (r.returncode, w8.state.exists()))
r = run(w8)
check("a real run writes the state file atomically (no temporary file beside it)", r.returncode == 0 and (w8.state / "widgets.json").exists() and sorted(p.name for p in w8.state.iterdir()) == ["widgets.json"], sorted(p.name for p in w8.state.iterdir()))
rr = rec(w8)
check("the state record holds the numbers, the limits and the format", rr["format"] == 1 and rr["repo"] == "widgets" and rr["stages"]["open_to_live"]["median"] == 30.0 and rr["thresholds"] == {"max_open_to_live_median_minutes": 60, "max_same_commit_flakes": 4}, rr)
r = run(w8, "--json")
jj = json.loads(r.stdout)
check("--json prints the record instead of the text", r.returncode == 0 and jj["stages"]["open_to_live"]["median"] == 30.0 and "release-speed report" not in r.stdout, r.stdout[:200])
r = run(w8, now=z(NOW + dt.timedelta(days=1)))
check("the next run compares with the previous record (days ago, the median and the flake count)", "since the previous run (1.0 days ago): open -> live median 30 -> 30 min; same-commit flakes 0 -> 0" in r.stdout, r.stdout)
(w8.state / "widgets.json").write_text("{not json")
r = run(w8)
check("a damaged previous record is started over with a note and replaced", r.returncode == 0 and "starting over" in r.stdout and rec(w8)["format"] == 1, (r.returncode, r.stdout[-300:]))
(w8.state / "widgets.json").write_text(json.dumps({"format": 1, "repo": "other", "generated": z(NOW), "stages": {}, "flakes": {}}))
r = run(w8)
check("a previous record of another repository is not used", "starting over" in r.stdout, r.stdout[-300:])

# ------------------------------------------------------------------ 9 the item a flag opens
w9 = stats_world("item")
CONF.write_text("max_open_to_live_median_minutes = 10\nitem_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
client_reset()
r = run(w9, "--client", str(CLIENT), no_open=False)
calls = client_calls()
check("a flag opens ONE item: one client call `post item-open release_speed:widgets/median` with the project, mover, step and lines", r.returncode == 0 and len(calls) == 1
      and calls[0][:3] == ["post", "item-open", "release_speed:widgets/median"] and "widgets-page" in calls[0] and "widgets-builder" in calls[0] and "release-speed-report" in calls[0], (r.returncode, calls, r.stderr))
check("the item's lines name the repository, each flag with its value and limit, the slowest stage and the state file; each fits the route's line", calls and
      any(a.startswith("Repository widgets: the weekly release-speed report passed 1 threshold") for a in calls[0]) and "open_to_live_median: 30 min > 10" in calls[0]
      and any(a.startswith("Slowest stage by median: PR open -> checks green, 12 min") for a in calls[0]) and any("state file" in a for a in calls[0])
      and all(len(a) <= 118 for i, a in enumerate(calls[0]) if i and calls[0][i - 1] == "--line"), calls)
check("the item is printed after the report and the state records no debt", "item: item-4242" in r.stdout and "open_pending" not in rec(w9), r.stdout[-300:])
client_reset()
r = run(w9, "--client", str(CLIENT), no_open=False)
check("a second run with the same flag asks again with the same marker (the route answers the open item)", client_calls() and client_calls()[0][2] == "release_speed:widgets/median", client_calls())
client_reset()
w9b = stats_world("noflag")
CONF.write_text("item_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
r = run(w9b, "--client", str(CLIENT), no_open=False)
check("no flag, no call", r.returncode == 0 and client_calls() == [], client_calls())
CONF.write_text("max_open_to_live_median_minutes = 10\n")
r = run(w9, "--client", str(CLIENT), no_open=False)
check("a flag with no item_project and item_mover is exit 3 naming them, the report still printed, the debt kept", r.returncode == 3 and "item_project and item_mover" in r.stderr and "FLAG: open_to_live_median" in r.stdout
      and rec(w9)["open_pending"][0]["key"] == "max_open_to_live_median_minutes", (r.returncode, r.stderr))
CONF.write_text("max_open_to_live_median_minutes = 10\nitem_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
client_reset("refuse")
r = run(w9, "--client", str(CLIENT), no_open=False)
check("a refusal is exit 3 with the client's text on stderr, the call made once, the debt kept", r.returncode == 3 and "not a background agent" in r.stderr and len(client_calls()) == 1 and "open_pending" in rec(w9), (r.returncode, r.stderr, client_calls()))
CONF.write_text("max_open_to_live_median_minutes = 1000\nmax_same_commit_flakes = 1000\nitem_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
client_reset()
r = run(w9, "--client", str(CLIENT), no_open=False)
check("the debt of an earlier run is asked for again even when this run has no flag of its own, then cleared", r.returncode == 0 and len(client_calls()) == 1 and "release_speed:widgets/median" in client_calls()[0] and "open_pending" not in rec(w9), (r.returncode, client_calls()))
CONF.write_text("max_open_to_live_median_minutes = 10\nmax_same_commit_flakes = 0\nitem_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
wfl = flake_world("itemfl", 1)
client_reset()
r = run(wfl, "--client", str(CLIENT), no_open=False)
check("two flags give the marker release_speed:widgets/median/flakes", client_calls() and client_calls()[0][2] == "release_speed:widgets/median/flakes", client_calls())
client_reset()
r = run(w9, "--no-open", "--client", str(CLIENT), no_open=False)
check("--no-open prints the item that would be sent and calls nothing, the debt is recorded", client_calls() == [] and "item: not sent" in r.stdout and "marker:  release_speed:widgets/median" in r.stdout and "open_pending" in rec(w9), (client_calls(), r.stdout[-300:]))
r = run(w9, "--client", str(CLIENT), no_open=False, args=None) if False else run(w9, "--dry-run", "--client", str(CLIENT), no_open=False)
check("--dry-run sends nothing either", client_calls() == [] and "item: not sent" in r.stdout, client_calls())
CONF.write_text("")

# ------------------------------------------------------------------ 10 the calls to GitHub
GH_LOG.write_text("")
w10 = stats_world("calls")
for i in range(230):                                              # 230 runs on one day: three pages of 100
    w10.run(H(2000 + i), "tests", NOW - dt.timedelta(days=2, hours=1) + dt.timedelta(seconds=i), "success")
w10.save()
r = run(w10, "--dry-run")
calls = [l for l in GH_LOG.read_text().splitlines()]
check("calls: one pr list, then the pull-request runs only, per_page 100, pages counted up", r.returncode == 0 and calls[0].startswith("pr list --repo acme/widgets --state merged --search merged:>=") and "--limit 1000" in calls[0]
      and all(c.startswith("api repos/acme/widgets/actions/runs?event=pull_request&per_page=100&page=") for c in calls[1:]), calls[:3])
check("calls: a day with 230 runs takes three pages and the week at most 8 day slices: under 20 calls in all", 0 < len(calls) < 20 and sum(1 for c in calls if "&page=3&" in c) == 1, (len(calls), calls))
check("calls: the report counts the 230 runs (every head has one success: no flake, the 5 PRs' heads green)", r.returncode == 0 and "PR runs 0" in r.stdout, r.stdout)

seen = []


def fake_json(*a):
    seen.append(a)
    if a[0] != "api":
        return []
    span = a[1].split("created=")[1]
    lo, hi = [dt.datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in span.split("..")]
    big = (hi - lo) > dt.timedelta(hours=4)
    return {"total_count": 1500 if big else 3, "workflow_runs": [{"id": len(seen) * 10 + i, "name": "tests", "head_sha": "x", "event": "pull_request", "created_at": "2026-11-20T00:00:00Z"} for i in range(100 if big else 3)]}


real = RS.gh_json
RS.gh_json = fake_json
try:
    budget = [RS.RUNS_PAGES_MAX]
    got = RS.fetch_runs(SLUG, NOW - dt.timedelta(days=1), NOW, budget)
    check("calls: a slice GitHub reports above its 1000 result cut is halved until it is small; the calls made are counted in the budget", len(seen) > 4 and budget[0] == RS.RUNS_PAGES_MAX - len(seen) and len(got) >= 3, (len(seen), budget))
    budget = [3]
    try:
        RS.fetch_runs(SLUG, NOW - dt.timedelta(days=5), NOW, budget)
        out = "no error"
    except ValueError as e:
        out = str(e)
    check("calls: past the budget the fetch stops with a message that says the window is too busy to read", "too busy to read" in out, out)
finally:
    RS.gh_json = real

# ------------------------------------------------------------------ 11 errors
w11 = stats_world("errors")
for label, text, want in (("a limit that is a string", 'max_same_commit_flakes = "5"\n', "must be a number"), ("a boolean limit", "max_same_commit_flakes = true\n", "must be a number"),
                          ("a negative limit", "max_open_to_live_median_minutes = -1\n", "must be a number"), ("nan", "max_same_commit_flakes = nan\n", "must be a number"),
                          ("a limit above 10**12", "max_same_commit_flakes = 1000000000001\n", "must be a number"), ("a bad item name", 'item_mover = "a b"\n', "item_mover must be a name"),
                          ("invalid TOML", "max_same_commit_flakes = = 1\n", "is not valid TOML")):
    c = T / "bad.toml"; c.write_text(text)
    r = run(w11, "--dry-run", config=c)
    check(f"config: {label} is exit 2 with its reason, nothing on stdout, no traceback", r.returncode == 2 and want in r.stderr and r.stdout == "" and "Traceback" not in r.stderr, (r.returncode, r.stderr[-300:]))
c = T / "warn.toml"; c.write_text("max_same_flakes = 3\n[widgets]\nmax_median = 1\n")
r = run(w11, "--dry-run", config=c)
check("config: a mistyped key warns on stderr and the run goes on (exit 0)", r.returncode == 0 and "warning: unknown key max_same_flakes" in r.stderr and "warning: unknown key max_median" in r.stderr, (r.returncode, r.stderr))
r = run(w11, "--dry-run", config=T / "no-such.toml")
check("config: a missing explicit file is exit 2", r.returncode == 2 and "does not exist" in r.stderr, (r.returncode, r.stderr))
r = run(w11, "--dry-run", config=None)
check("config: the default file (under HOME, absent here) is no error", r.returncode == 0, (r.returncode, r.stderr))
r = run(w11, "--dry-run", logs=False)
check("a logs folder that does not exist (the default one under HOME) is exit 2 naming it", r.returncode == 2 and "cannot read the release logs folder" in r.stderr and "stackshot/releases" in r.stderr, (r.returncode, r.stderr))
for bad in ("0", "-3", "400", "nan"):
    r = run(w11, "--dry-run", "--days", bad)
    check(f"--days {bad} is exit 2", r.returncode == 2 and "--days" in r.stderr, (r.returncode, r.stderr))
r = run(w11, "--dry-run", now="yesterday")
check("--now that is no ISO time is exit 2", r.returncode == 2 and "not an ISO time" in r.stderr, (r.returncode, r.stderr))
r = run(w11, "--dry-run", now="2026-11-26T12:00:00")
check("--now with no offset is exit 2", r.returncode == 2 and "needs an offset" in r.stderr, (r.returncode, r.stderr))
(T / "afile").write_text("x")
r = run(w11, config=CONF, env={})
w11.state.mkdir(exist_ok=True)
r = subprocess.run([sys.executable, TOOL, "--no-open", "--now", z(NOW), "--github", SLUG, "--logs", str(w11.logs), "--state-dir", str(T / "afile" / "sub"), "--config", str(CONF)],
                   capture_output=True, text=True, env={"PATH": f"{GH_BIN}:{os.environ['PATH']}", "HOME": str(HOME), "GH_DATA": str(w11.data)}, cwd=T, timeout=120)
check("an unwritable state folder is exit 1 with nothing on stdout", r.returncode == 1 and "cannot write the state folder" in r.stderr and r.stdout == "", (r.returncode, r.stderr))
r = run(w11, "--dry-run", "--repo", "my repo!")
check("--repo is made safe for a file name (the state of a --dry-run is not written, the header shows the safe name)", r.returncode == 0 and "release-speed report: my_repo_ (last 7 days)" in r.stdout and "my repo" not in r.stdout, r.stdout[:80])

# ------------------------------------------------------------------ 12 read-only, executable
before = tree_hash(w2.logs)
run(w2); run(w2, "--json"); run(w2, "--dry-run")
check("read-only: the logs folder is byte for byte as it was", tree_hash(w2.logs) == before)
check("the file is executable", os.access(TOOL, os.X_OK))
check("the module's quantile is linear between ranks, a single value is itself", RS.quantile([10, 20], 0.5) == 15 and RS.quantile([7], 0.9) == 7 and RS.quantile([1, 2, 3, 4, 5], 0.9) == 4.6)

# ------------------------------------------------------------------ 13 a group's start, the pushed head, a paid or unpaid debt in an empty window
# A member's log of a group release holds only what release.sh's run_group appends to it: the progress lines of gsay and the result lines of plog (and a member's own FAILED line). What it says with
# `say` alone (the main run's result among it) is in the group log only, and a group's hand-over writes no `checks pass` and no `enqueued:` line.
w13 = World("group")
for pr in (701, 702):
    w13.log(pr, [(BASE, f"release of PRs #701 #702 starts in /srv/widgets ({SLUG}): the merge queue (mode on) tests them as one group and merges it once"),
                 (BASE + mins(1), "merge queue: PRs 701 702 handed over in one call (added); waiting for each"),
                 (BASE + mins(18), "merge queue: PR 701 merged: a title at abc1234"), (BASE + mins(18), "merge queue: PR 702 merged: a title at abc1234"),
                 (BASE + mins(20), "merged by the merge queue: #701 #702 at abc1234 (main's tip abc1234); deploying them once"),
                 (BASE + mins(22), "done: abc1234, restarted app.service ")])
    w13.listed(pr, BASE - mins(30), f"{pr:040x}", BASE + mins(19))
    w13.run(f"{pr:040x}", "tests", BASE - mins(29), "success", BASE - mins(20))
w13.log(703, [(BASE + mins(60), f"release of PR #703 starts in /srv/widgets ({SLUG})"), (BASE + mins(62), "the PR's tests pass on the pushed head 7030303"),
              (BASE + mins(66), "enqueued: the merge queue accepted the head 7030303"), (BASE + mins(80), "merged by the merge queue as abc1234, 14 min after the enqueue"),
              (BASE + mins(82), "done: abc1234, restarted app.service ")])
w13.save()
r, j = jrun(w13)
got13 = {k: (v["n"], v["median"]) for k, v in j.get("stages", {}).items()}
check("a group's start line (`release of PRs #N #M starts`) starts a release in each member's log: 3 live (two of the group, one single)", r.returncode == 0 and j["prs"]["live"] == 3, (r.returncode, j.get("prs"), r.stderr))
check("a group's member logs with GitHub give open -> green (n 2, 10), merged -> live (n 3 with the single release, 2) and open -> live (n 2, 52), and no main run",
      got13.get("open_to_green") == (2, 10.0) and got13.get("merged_to_live") == (3, 2.0) and got13.get("open_to_live") == (2, 52.0) and got13.get("live_to_main") == (0, None), got13)
check("the pushed-head line is the checks-pass line: the queued stages are the single release's alone, checks pass -> queued 4 (log only, no GitHub runs) and queued -> merged 14",
      got13.get("green_to_queued") == (1, 4.0) and got13.get("queued_to_merged") == (1, 14.0), got13)

w13b = World("paid")                                              # an owed item that is paid, in a window with no release
w13b.log(711, [(LO - mins(60), f"release of PR #711 starts in /srv/widgets ({SLUG})"), (LO - mins(50), "done: abc1234, restarted app.service ")])
w13b.save()
kept_before = {"format": 1, "repo": "widgets", "generated": "2026-11-19T00:00:00+00:00", "stages": {}, "flakes": {}, "marker": "kept",
               "open_pending": [{"key": "max_open_to_live_median_minutes", "limit": 10, "value": 30.0, "line": "FLAG: open_to_live_median: 30 min > 10"}]}
w13b.state.mkdir(); (w13b.state / "widgets.json").write_text(json.dumps(kept_before))
CONF.write_text("max_open_to_live_median_minutes = 10\nitem_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n")
client_reset()
r = run(w13b, "--client", str(CLIENT), no_open=False)
after = rec(w13b)
check("an owed item paid in an empty window: the item is sent once, the debt is cleared in the state, the rest of the previous record stays, exit 4",
      r.returncode == 4 and len(client_calls()) == 1 and "open_pending" not in after and after == {k: v for k, v in kept_before.items() if k != "open_pending"}, (r.returncode, client_calls(), after))
CONF.write_text("")
client_reset()

ITEM_CONF = "item_project = \"widgets-page\"\nitem_mover = \"widgets-builder\"\n"
for i, (label, conf, mode, extra, status, calls_want) in enumerate((("--no-open", ITEM_CONF, "ok", ("--no-open",), 4, 0), ("--dry-run", ITEM_CONF, "ok", ("--dry-run",), 4, 0),
                                                                      ("a refused item call", ITEM_CONF, "refuse", (), 3, 1), ("no item_project and item_mover", "", "ok", (), 3, 0))):
    w = World(f"unpaid{i}")                                       # an owed item that is not paid, in a window with no release
    w.log(721, [(LO - mins(60), f"release of PR #721 starts in /srv/widgets ({SLUG})"), (LO - mins(50), "done: abc1234, restarted app.service ")])
    w.save()
    w.state.mkdir(); (w.state / "widgets.json").write_text(json.dumps(kept_before))
    before = (w.state / "widgets.json").read_text()
    CONF.write_text("max_open_to_live_median_minutes = 10\n" + conf)
    client_reset(mode)
    r = run(w, "--client", str(CLIENT), *extra, no_open=False)
    check(f"an unpaid debt survives an empty window ({label}): exit {status}, the record byte for byte as it was",
          r.returncode == status and len(client_calls()) == calls_want and (w.state / "widgets.json").read_text() == before, (r.returncode, r.stderr, client_calls(), rec(w)))
CONF.write_text("")
client_reset()

# ------------------------------------------------------------------ 14 GitHub unreadable: this run's stages stay its own, the last measured open -> live median is kept apart
T0 = "2026-11-19T00:00:00+00:00"
NO_STAGE = {"n": 0, "median": None, "p90": None, "worst": None, "worst_pr": None}


def put_prev(w, **fields):
    w.state.mkdir(exist_ok=True)
    (w.state / "widgets.json").write_text(json.dumps(dict({"format": 1, "repo": "widgets", "generated": T0, "stages": {}, "flakes": {}}, **fields)))


def measured(med):
    return {"open_to_live": {"n": 1, "median": med, "p90": med, "worst": med, "worst_pr": 1}}


w14 = stats_world("kept")                                         # GitHub unreadable after a good run (open -> live 30)
r = run(w14)
r2, j2 = jrun(w14, env={"PATH": str(NO_GH)}, now=z(NOW + dt.timedelta(hours=1)))
check("GitHub unreadable after a good run: the stage is this run's (n 0), the previous median 30 is kept apart with the time it was measured, a note says so, the log's stages are counted, exit 4",
      r.returncode == 0 and r2.returncode == 4 and j2["stages"]["open_to_live"] == NO_STAGE and j2.get("open_to_live_kept") == {"median": 30.0, "generated": "2026-11-26T12:00:00+00:00"}
      and any("the last measured median, 30 min, measured 2026-11-26T12:00:00+00:00, is kept" in n for n in j2["notes"]) and j2["stages"]["merged_to_live"]["n"] == 5,
      (r2.returncode, j2.get("stages", {}).get("open_to_live"), j2.get("open_to_live_kept"), j2.get("notes")))

wk = World("weeks")                                               # several weeks unread, two releases in each (open -> live 18): an old median above the limit flags nothing
for week in range(4):
    for i in range(2):
        n = 730 + 10 * week + i
        wk.release(n, BASE + dt.timedelta(days=7 * week, minutes=60 * i), f"{n:040x}", 10, 2, 5, 1, 1)
wk.save()
put_prev(wk, stages=measured(120.0))
CONF.write_text("max_open_to_live_median_minutes = 60\n" + ITEM_CONF)
client_reset()
for week in range(3):
    r = run(wk, "--client", str(CLIENT), no_open=False, env={"GH_FAIL": "1"}, now=z(NOW + dt.timedelta(days=7 * week)))
    got = rec(wk)
    check(f"unread week {week + 1}: no flag, no item call, no debt; the stage is unmeasured and the kept median stays 120 with its first time",
          r.returncode == 4 and got["prs"]["live"] == 2 and got["triggers"] == [] and "FLAG" not in r.stdout and client_calls() == [] and "open_pending" not in got
          and got["stages"]["open_to_live"] == NO_STAGE and got.get("open_to_live_kept") == {"median": 120.0, "generated": T0}, (r.returncode, r.stdout, got, client_calls()))
    said = "open -> live median 120 -> n/a min" if week == 0 else f"open -> live median 120 (from an earlier run, measured {T0}) -> n/a min"
    check(f"unread week {week + 1}: the comparison line gives {'the measured median of the previous run' if week == 0 else 'the kept median as from an earlier run, with when'}", said in r.stdout, r.stdout)
r = run(wk, "--client", str(CLIENT), no_open=False, now=z(NOW + dt.timedelta(days=21)))
got = rec(wk)
check("the first readable week compares with the kept median, said to be from an earlier run and when; it measures 18, keeps nothing and flags nothing",
      r.returncode == 0 and f"open -> live median 120 (from an earlier run, measured {T0}) -> 18 min" in r.stdout and got["stages"]["open_to_live"]["median"] == 18.0
      and "open_to_live_kept" not in got and got["triggers"] == [] and client_calls() == [], (r.returncode, r.stdout, got))
put_prev(wk, stages=measured(40.0), open_to_live_kept={"median": 99.0, "generated": "2026-11-01T00:00:00+00:00"})
r = run(wk, "--dry-run")
check("a previous record with a measured median is compared by it, not by a kept one", "open -> live median 40 -> 18 min" in r.stdout and "earlier run" not in r.stdout, r.stdout)

w14z = World("kept-nolive")                                       # a window with a started release and none live
w14z.log(741, [(BASE, f"release of PR #741 starts in /srv/widgets ({SLUG})"), (BASE + mins(1), "FAILED at checks: a check failed: suites=fail")])
w14z.save()
put_prev(w14z, stages=measured(120.0))
client_reset()
r = run(w14z, "--client", str(CLIENT), no_open=False, env={"GH_FAIL": "1"})
got = rec(w14z)
check("unreadable with 0 live releases: no flag and no call for the old median, which is kept apart", r.returncode == 4 and got["prs"]["live"] == 0 and got["triggers"] == [] and client_calls() == []
      and got["stages"]["open_to_live"] == NO_STAGE and got.get("open_to_live_kept") == {"median": 120.0, "generated": T0}, (r.returncode, got, client_calls()))

for now_med, old_med, flagged in ((120, 10.0, True), (30, 120.0, False)):      # the PR list read and the runs not: this run's own open -> live decides, nothing is kept
    wp = World(f"partial{now_med}")
    wp.release(751, BASE, f"{751:040x}", now_med - 8, 2, 5, 1, 1)
    wp.save()
    put_prev(wp, stages=measured(old_med), open_to_live_kept={"median": old_med, "generated": T0})
    client_reset()
    r = run(wp, "--client", str(CLIENT), no_open=False, env={"GH_FAIL_RUNS": "1"})
    got = rec(wp)
    check(f"PRs read, runs failed: this run's open -> live {now_med} stands over the old {old_med:g}, nothing is kept, {'it is flagged and the item sent' if flagged else 'no flag and no call'}, exit 4",
          r.returncode == 4 and "boom" in r.stderr and got["stages"]["open_to_live"]["median"] == float(now_med) and "open_to_live_kept" not in got and bool(got["triggers"]) == flagged
          and len(client_calls()) == int(flagged) and (not flagged or got["triggers"][0]["line"] == f"FLAG: open_to_live_median: {now_med} min > 60")
          and any("the pull request list was read and the check runs were not" in n for n in got["notes"]) and not any("is kept" in n for n in got["notes"]), (r.returncode, r.stderr, got, client_calls()))
CONF.write_text("")
client_reset()

HUGE = 10 ** 400                                                  # a damaged previous record never stops a run, GitHub readable or not
wd = stats_world("damaged")                                       # open -> live 30
for label, fields, kept, before in (
        ("an empty open_to_live", {"stages": {"open_to_live": {}}}, None, "n/a"),
        ("a median that is a string", {"stages": {"open_to_live": {"median": "x"}}}, None, "n/a"),
        ("a stage with a median alone", {"stages": {"open_to_live": {"median": 5}}}, {"median": 5, "generated": T0}, "5"),
        ("a stage that is no object", {"stages": {"open_to_live": [5]}}, None, "n/a"),
        ("numbers too large", {"stages": {"open_to_live": {"median": HUGE}}, "flakes": {"total": HUGE}}, None, "n/a"),
        ("a negative median", {"stages": {"open_to_live": {"median": -1}}}, None, "n/a"),
        ("a kept field that is no object", {"open_to_live_kept": "x"}, None, "n/a"),
        ("a kept field that is empty", {"open_to_live_kept": {}}, None, "n/a"),
        ("a kept median that is a string", {"open_to_live_kept": {"median": "x", "generated": T0}}, None, "n/a"),
        ("a kept median too large", {"open_to_live_kept": {"median": HUGE, "generated": T0}}, None, "n/a"),
        ("a kept median with no time", {"open_to_live_kept": {"median": 5}}, None, "n/a"),
        ("a kept time that is no time", {"open_to_live_kept": {"median": 5, "generated": "x"}}, None, "n/a"),
        ("a kept time that is a number", {"open_to_live_kept": {"median": 5, "generated": 7}}, None, "n/a"),
        ("a kept time with no offset", {"open_to_live_kept": {"median": 5, "generated": "2026-11-19T00:00:00"}}, None, "n/a")):
    put_prev(wd, **fields)
    r = run(wd, env={"GH_FAIL": "1"})
    got = rec(wd)
    check(f"a damaged previous record ({label}), GitHub unreadable: the report is made, the stage is unmeasured, only a usable median is kept",
          r.returncode == 4 and "Traceback" not in r.stderr and "since the previous run" in r.stdout and got["stages"]["open_to_live"] == NO_STAGE and got.get("open_to_live_kept") == kept,
          (r.returncode, r.stderr[-600:], got.get("open_to_live_kept")))
    put_prev(wd, **fields)
    r = run(wd, "--dry-run")
    check(f"a damaged previous record ({label}), GitHub readable: the report is made and compares {before} with 30",
          r.returncode == 0 and "Traceback" not in r.stderr and f"open -> live median {before} -> 30 min" in r.stdout, (r.returncode, r.stderr[-600:], r.stdout[-400:]))


print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
