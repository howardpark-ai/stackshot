"""Scenario test for the Runners data (runners.py) and the Runners page (ui/runners.py) — fake GitHub answers, fake switch files, a fake ssh; no network, no ssh, no live store.

Covers: the runner list (idle, running, offline) per machine and repo, the box taken from the runner's name (the labels only as a fallback); a running runner with its PR (linked) and with
a branch only (linked to the run), the time it has run; an offline runner switched off (mode off), held for one repo only (the other repo's runner on
the same box is not), stopped by the box-a gate, offline with no switch reason (a fault, marked apart) and on a box that cannot be reached ("box not
reachable", not a fault); a missing mode file (on for box-a, off for a WSL box); the ssh read (read-only script, BatchMode, short timeout) cached
per box, only made when a box has an offline runner, never when [runners] ssh_enabled is false; the snapshot cache (two requests, one fetch; jobs
fetched only when a runner is busy); a GitHub error on one repo or both and an empty list (the page renders, shows the error); the page and
/runners.json over HTTP in-process (JSON shape, no-store, the sign-in in front); the link in the board's header; every runner the fake GitHub lists
appears on the page. The review of that change: hostile text escaped in the page and the JSON, one fetch for two threads at once (the second gets the
previous snapshot, stale), the build deadline, odd GitHub answers cached as errors, no redirect followed, fixed words for an unreachable box, the poll pausing
while the tab is hidden and the stale cue. Section 10: the owner of each repo read from GitHub (cached, followed when it changes), an organization's shared runners
listed beside the repo's own (once per org, paginated, no duplicates), the 403/404 line naming the missing permission, and a runner's machine taken from its labels (a new machine gets a row).
Section 12 (the CI runners page and the Disable / Enable button): the five count cards (Offline red above 0), "disabled" apart from "offline" in the counts and the machine's state
line, the switch read for every machine (a Linux machine asked with shell lines, the way that answered remembered), switch_box run against a fake pool-mode.sh in a scratch folder (argv, minimal
environment, timeout, one change per machine at a time, a refused machine name or action runs nothing, the real script is never run), the buttons on the page, and the POST /runners/switch
route (sign-in, same origin, per-machine token, size cap, fleet-name check, read-only refusal, JSON answer). Also (box-g): a [runners] boxes entry named in [runners.ssh_hosts] is
a button machine without being in the fleet's names, and a box in neither is refused.

    tests/run-suite runners        → exit 0 / 1"""
import base64, datetime as dt, json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="runnerstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai"),
                 ("fleet_names", f"{tmp}/session-names.tsv"), ("mode_file", f"{tmp}/ci/mode"), ("hold_file", f"{tmp}/ci/hold"), ("gate_file", f"{tmp}/ci/halted")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^repos = \[\]', 'repos = ["salamander", "stackshot"]', toml); assert n == 1      # the example lists no repo; this instance has both repos
toml, n = re.subn(r'(?m)^# myrepo = "mine"$', lambda m: 'salamander = "S<i>&\\"x"', toml); assert n == 1      # the example documents [runners.labels]; this instance labels one repo with hostile text, which the panel must escape
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "ci"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("1")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"))
    if not cond: fails.append(name)

from stackshot.web import runners as R
from stackshot.web.ui import runners as R2
from stackshot.web.runners import RunnersError

# ---- fixtures: a fake GitHub, a fake ssh, a fixed clock
T0 = dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.timezone.utc).timestamp()
ZONE_HOURS = 4; ABBR = f"+{ZONE_HOURS:02d}"                   # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST) and its own abbreviation
CLK = dt.datetime.fromtimestamp(T0, dt.timezone(dt.timedelta(hours=ZONE_HOURS))).strftime("%H:%M")      # T0's clock time in that zone ("16:00")
CLOCK = [T0]; R._now = lambda: CLOCK[0]; R2._now = R._now
def iso(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def rn(name, box, online=True, busy=False): return {"id": sum(map(ord, name)), "name": name, "status": "online" if online else "offline", "busy": busy,
                                                     "labels": [{"name": x} for x in ("self-hosted", "Linux", "X64", box, "pool", "light")]}
RUNNERS = {
    "salamander": [rn("box-a-salamander", "box-a"), rn("box-a-salamander-2", "box-a", busy=True), rn("box-a-salamander-10", "box-a"),
                   rn("box-b-salamander", "box-b", online=False), rn("box-c-salamander", "box-c", online=False)],
    "stackshot": [rn("box-a-stackshot", "box-a", online=False), rn("box-a-stackshot-2", "box-a", busy=True), rn("box-b-stackshot", "box-b", online=False),
                  rn("box-c-stackshot", "box-c"), rn("box-c-stackshot-2", "box-c", online=False)],
}
RUNS = {"salamander": [{"id": 11, "head_branch": "feature-x", "html_url": "https://github.com/example-owner/salamander/actions/runs/11", "pull_requests": [{"number": 17}],
                        "run_started_at": iso(T0 - 400)}],
        "stackshot": [{"id": 22, "head_branch": "other", "html_url": "https://github.com/example-owner/stackshot/actions/runs/22", "pull_requests": [{"number": 7}], "run_started_at": iso(T0 - 10)},
                      {"id": 21, "head_branch": "nightly-fix", "html_url": "https://github.com/example-owner/stackshot/actions/runs/21", "pull_requests": [],
                       "run_started_at": iso(T0 - 4000)}]}
JOBS = {11: [{"id": 111, "status": "in_progress", "runner_name": "box-a-salamander-2", "started_at": iso(T0 - 300)},
             {"id": 112, "status": "completed", "runner_name": "box-a-salamander", "started_at": iso(T0 - 900)}],
        21: [{"id": 211, "status": "in_progress", "runner_name": "box-a-stackshot-2", "started_at": iso(T0 - 3725)}],
        22: [{"id": 221, "status": "in_progress", "runner_name": "somebody-else", "started_at": iso(T0 - 5)}]}
CALLS = []; BROKEN = set()
QUEUED = {}                                          # repo → its queued runs (none unless a check puts some); their jobs are looked up in JOBS by run id
TIMEOUTS = []
OWNER_CALLS = []                                     # the owner lookups are kept apart from CALLS: the checks below count the runner, run and job calls
OWNER = {"login": "example-owner", "type": "User"}      # what GET /repos/<owner>/<repo> says about the owner: a user, so these suites read the repos' own runners only
def fake_get(path, timeout=8):
    TIMEOUTS.append(timeout)
    if re.fullmatch(r"/repos/example-owner/\w+|/repositories/\d+", path):
        OWNER_CALLS.append(path); return {"owner": dict(OWNER)}
    CALLS.append(path)
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runners\?per_page=100&page=(\d+)", path)
    if m:
        if m.group(1) in BROKEN: raise RunnersError(f"GitHub answered 502 for /repos/example-owner/{m.group(1)}/actions/runners")
        rs = RUNNERS[m.group(1)] if m.group(2) == "1" else []
        return {"total_count": len(RUNNERS[m.group(1)]), "runners": rs}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs\?status=in_progress&per_page=\d+", path)
    if m: return {"workflow_runs": RUNS[m.group(1)]}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs\?status=queued&per_page=\d+", path)
    if m: return {"workflow_runs": QUEUED.get(m.group(1), [])}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs/(\d+)/jobs\?filter=latest&per_page=100", path)
    if m: return {"jobs": JOBS[int(m.group(2))]}
    raise AssertionError("unexpected GitHub path " + path)
REAL_GET = R._get; R._get = fake_get
SSH = []; SSH_OUT = {}        # host → stdout text, or an Exception
REAL_SSH = R._ssh
FLAVORS_ASKED = []
def fake_ssh(host, timeout, flavor="ps"):
    SSH.append(host); FLAVORS_ASKED.append((host, flavor)); v = SSH_OUT[host]
    if isinstance(v, Exception): raise v
    return v
R._ssh = fake_ssh
def wsl(mode, hold="none"): return f"mode file: {mode}\r\nhold file: {hold}\r\n"
def setfiles(mode=None, hold=None, gate=None):
    for n, v in (("mode", mode), ("hold", hold), ("halted", gate)):
        p = T / "ci" / n
        if v is None: p.unlink(missing_ok=True)
        else: p.write_text(v)
def fresh():
    R.reset(); CALLS.clear(); SSH.clear(); BROKEN.clear(); CLOCK[0] = T0
def by(snap): return {x["name"]: x for x in snap["runners"]}
def aged(secs=600):
    """A snapshot in which every offline runner has already been offline for `secs` (past R.OFFLINE_GRACE_S): read once, the marks set back, read again with that one as the previous."""
    snap = R.snapshot()
    for x in snap["runners"]:
        if x["state"] == "offline": x["off_since"] = CLOCK[0] - secs
    return R.snapshot(force=True)
import time
def settle(limit=10):                                # a page request starts its rebuild in a thread: wait until it has landed
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        with R._LOCK:
            if R._SERVE["thread"] is None and R._CACHE.get("snap") is not None: return True
        time.sleep(0.01)
    return False
def get_settled(c, path, **kw):                      # the first request is answered at once (from nothing: a placeholder) and kicks the rebuild; the next one has the table
    c.get(path, **kw); settle(); return c.get(path, **kw)
def row(html, box):                                  # one machine's row: its name cell (state, buttons) and its runner list
    return re.search(rf'<tr class="[^"]*"><th scope="row"><div class="mname">{box}</div>(.*?)</tr>', html, re.S).group(1)
def tcard(html, label):                              # the number on one count card
    m = re.search(rf'<div class="rcard[^"]*"><b>(\d+)</b><span>{label}</span>', html); return int(m.group(1)) if m else None
def heads(snap): return [R2._tag(c) for c in R._columns(snap)]

# ---- 1. the states, per machine and repo
setfiles(mode="on\n", hold="", gate="")
SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on", "salamander")})
fresh(); snap = aged(); x = by(snap)
check("every runner GitHub lists is in the snapshot (10 of 10)", len(snap["runners"]) == 10 == sum(len(v) for v in RUNNERS.values()), len(snap["runners"]))
check("the box comes from the name",x["box-b-stackshot"]["box"] == "box-b" and x["box-c-salamander"]["box"] == "box-c" and x["box-a-salamander"]["box"] == "box-a")
check("idle: online and not busy", x["box-a-salamander"]["state"] == "idle" and x["box-c-stackshot"]["state"] == "idle")
check("running: online and busy", x["box-a-salamander-2"]["state"] == "running" and x["box-a-stackshot-2"]["state"] == "running")
check("offline: not online", x["box-b-salamander"]["state"] == "offline" and x["box-a-stackshot"]["state"] == "offline")
j = x["box-a-salamander-2"]["job"]
check("running with a PR: the PR number, the repo, the start from the job", j["pr"] == 17 and j["repo"] == "salamander" and j["started"] == T0 - 300, j)
j = x["box-a-stackshot-2"]["job"]
check("running with no PR: the branch and the run's link; the job is the runner's own (the other run's job is not taken)", j["pr"] == 0 and j["branch"] == "nightly-fix"
      and j["url"].endswith("/actions/runs/21") and j["started"] == T0 - 3725, j)
check("offline, mode off on the box: 'disabled on box-b'", (x["box-b-stackshot"]["kind"], x["box-b-stackshot"]["reason"]) == ("switch", "disabled on box-b"), x["box-b-stackshot"])
check("offline, held for the repo: 'held for salamander on box-c'", (x["box-c-salamander"]["kind"], x["box-c-salamander"]["reason"]) == ("switch", "held for salamander on box-c"), x["box-c-salamander"])
check("the same box's other repo is not held: its offline runner has no reason, so it is a fault", x["box-c-stackshot-2"]["kind"] == "fault", x["box-c-stackshot-2"])
check("offline on box-a with the switch on, no hold and no gate entry: a fault", x["box-a-stackshot"]["kind"] == "fault" and "did not disable it" in x["box-a-stackshot"]["reason"], x["box-a-stackshot"])
check("the ssh read happened once per box with an offline runner, and only for those", sorted(SSH) == ["box-b", "box-c"], SSH)
html = R2.table_html(snap, T0)
check("the table: a row per machine in order, one heading per repo (the runner lists are per machine)", re.findall(r'<div class="mname">([\w-]+)</div>', html) == ["box-a", "box-b", "box-c"]
      and heads(snap) == ["salamander", "stackshot"] and "<thead>" in html, html[:400])
c = row(html, "box-a")
check("a machine's runners are listed in natural order (…-2 before …-10)", c.index("box-a-salamander</b>") < c.index("box-a-salamander-2</b>") < c.index("box-a-salamander-10</b>"), c)
check("a running runner: the PR is a link to the pull request, with the time it has run", '<a href="https://github.com/example-owner/salamander/pull/17"' in c and "salamander #17</a> · 5m" in c, c)
check("a running runner with a branch only: the branch, linked to the run, with 1h 02m", 'href="https://github.com/example-owner/stackshot/actions/runs/21"' in c and "stackshot nightly-fix</a> · 1h 02m" in c, c)
check("a disabled runner says 'disabled' (no reason tail: the machine's state line says it once), a held one says which repo holds it",
      '<span class="rst">disabled</span>' in row(html, "box-b") and "disabled on box-b" not in row(html, "box-b") and "held for salamander on box-c" in row(html, "box-c"), row(html, "box-b"))
check("the machine's state line: disabled (dim row) for box-b, 'disabling' with the job count while one runs, 'on · X of Y busy' otherwise",
      '<div class="mstate disabled"><span class="offw">disabled</span>' in html and '<tr class="isoff"><th scope="row"><div class="mname">box-b</div>' in html
      and "on</span> · 2 of 4 busy" in row(html, "box-a"), row(html, "box-a")[:300])
check("a fault is marked apart (class fault, a warning sign) and a disabled one is not", '<li class="rn fault">' in c and "⚠" in c and '<li class="rn off">' in row(html, "box-b")
      and "⚠" not in row(html, "box-b"), c)
check("the count cards: 10 runners, 2 running, 3 idle, 3 disabled, 2 offline (a disabled runner is not 'offline')",
      [tcard(html, w) for w in ("Runners", "Running", "Idle", "Disabled", "Offline")] == [10, 2, 3, 3, 2], html[:900])
check("the page dates its read, and says nothing of GitHub calls", f"Updated {CLK}:00 {ABBR}" in html and "github calls" not in html.lower(), html[:300])

# ---- 2. the cache
fresh(); R.snapshot(); n1 = len(CALLS); R.snapshot(); R.snapshot()
check("two more requests inside cache_s make no GitHub call and no ssh", len(CALLS) == n1 > 0 and sorted(SSH) == ["box-b", "box-c"], (n1, len(CALLS), SSH))   # the switch of every remote machine is read once, offline runner or not
check("jobs were fetched for the busy runners only (one in-progress list per repo, the jobs of the runs until each busy runner is matched)",
      sum("status=in_progress" in p for p in CALLS) == 2 and sum("/jobs" in p for p in CALLS) == 3, CALLS)
CLOCK[0] = T0 + 24; R.snapshot(); check("24 s later: still the same snapshot", len(CALLS) == n1)
CLOCK[0] = T0 + 26; R.snapshot()
check("26 s later: GitHub is read again", len(CALLS) == 2 * n1, (n1, len(CALLS)))
check("…but the ssh reads are kept 120 s", sorted(SSH) == ["box-b", "box-c"], SSH)
CLOCK[0] = T0 + 130; R.snapshot(); check("130 s later: each box is read again", sorted(SSH) == ["box-b", "box-b", "box-c", "box-c"], SSH)
fresh(); R.snapshot(force=True); n = len(CALLS); R.snapshot(force=True)
check("force reads again", len(CALLS) == 2 * n)
SAVE = {k: list(v) for k, v in RUNNERS.items()}
for k in RUNNERS: RUNNERS[k] = [r for r in RUNNERS[k] if r["status"] == "online" and not r["busy"]]
fresh(); R.snapshot()
check("no runner busy and none offline: the runner lists only, no run or job call; the remote machines' switches are still read (the Disable and Enable buttons show them)",
      len(CALLS) == 2 and all("/runs" not in p for p in CALLS) and sorted(SSH) == ["box-b", "box-c"], (CALLS, SSH))
RUNNERS.update(SAVE)

# ---- 3. the switch: unreachable, missing files, ssh off, the gate
fresh(); SSH_OUT["box-b"] = RunnersError("ssh exit 255")
snap = aged(); x = by(snap)
check("a box that cannot be reached: 'box not reachable', not a fault", (x["box-b-stackshot"]["kind"], x["box-b-stackshot"]["reason"]) == ("unreachable", "box not reachable (ssh exit 255)")
      and x["box-b-salamander"]["kind"] == "unreachable", x["box-b-stackshot"])
html = R2.table_html(snap, T0)
check("…and it is not drawn as a fault", "box not reachable" in html and '<li class="rn fault">' in row(html, "box-a") and '<li class="rn fault">' not in row(html, "box-b"))
check("an unreachable box does not spoil the others (box-c answered)", x["box-c-salamander"]["kind"] == "switch")
n = len(SSH); CLOCK[0] = T0 + 40; R.snapshot(force=True)
check("a failed read is kept too: no second ssh within 40 s", len(SSH) == n, SSH)
CLOCK[0] = T0 + 70; R.snapshot(force=True)
check("…and tried again after 60 s, though ssh_cache_s is 120", SSH.count("box-b") == 2, SSH)
SSH_OUT["box-b"] = wsl("missing (= off)")
fresh(); x = by(R.snapshot())
check("a WSL box with no mode file reads as off", x["box-b-stackshot"]["reason"] == "disabled on box-b", x["box-b-stackshot"])
SSH_OUT["box-b"] = wsl("on")
fresh(); x = by(aged())
check("a WSL box with mode on and nothing held: its offline runner is a fault", x["box-b-stackshot"]["kind"] == "fault", x["box-b-stackshot"])
SSH_OUT["box-b"] = "garbage\r\n"
fresh(); x = by(R.snapshot())
check("an answer with no mode line counts as not reachable", x["box-b-stackshot"]["kind"] == "unreachable", x["box-b-stackshot"])
SSH_OUT["box-b"] = wsl("off")
setfiles(mode="off\n", hold="stackshot\n")
fresh(); x = by(R.snapshot())
check("box-a mode off: disabled on box-a (mode wins over the hold)", x["box-a-stackshot"]["reason"] == "disabled on box-a", x["box-a-stackshot"])
setfiles(mode=None, hold="Stackshot, salamander\n")
fresh(); x = by(R.snapshot())
check("box-a: a missing mode file is on; the hold file's words (any case, comma or space) hold", x["box-a-stackshot"]["reason"] == "held for stackshot on box-a", x["box-a-stackshot"])
setfiles(mode="on\n", hold="", gate="actions.runner.example-owner-stackshot.box-a-stackshot.service\n")
fresh(); x = by(R.snapshot())
check("box-a: a unit named in the gate's file is 'stopped by the CI gate', not a fault", (x["box-a-stackshot"]["kind"], x["box-a-stackshot"]["reason"]) == ("switch", "stopped by the CI gate on box-a"), x["box-a-stackshot"])
setfiles(mode="on\n", hold="", gate="")
R._cfg.CFG["runners"]["ssh_enabled"] = False
fresh(); x = by(R.snapshot())
check("[runners] ssh_enabled false: no ssh at all, the WSL boxes' offline runners say the switch was not read", SSH == [] and x["box-b-stackshot"]["kind"] == "unread"
      and "not read" in x["box-b-stackshot"]["reason"], (SSH, x["box-b-stackshot"]))
R._cfg.CFG["runners"]["ssh_enabled"] = True
SSH_OUT["box-b"] = wsl("off"); SSH_OUT["box-c"] = wsl("on", "salamander")

# ---- 4. the ssh call itself: a read-only script, key auth, a short timeout (subprocess replaced; nothing is run)
import subprocess
RUNS_SEEN = []
class Done:                                                   # what subprocess.run returns
    def __init__(self, rc, out): self.returncode, self.stdout = rc, out
def fake_run(args, **kw):
    RUNS_SEEN.append((args, kw))
    if FAKE_RUN[0] == "timeout": raise subprocess.TimeoutExpired(args, kw.get("timeout"))
    return Done(FAKE_RUN[0], "mode file: on\r\nhold file: stackshot\r\n")
REAL_RUN = subprocess.run; FAKE_RUN = [0]; R.subprocess.run = fake_run
out = REAL_SSH("box-b", 12); a, kw = RUNS_SEEN[-1]
script = base64.b64decode(a[-1].rsplit(" ", 1)[1]).decode("utf-16-le")
check("the ssh call: BatchMode, ConnectTimeout, no shared connection, '--' before the host, stdin closed, the given timeout", a[0] == "ssh" and "BatchMode=yes" in a and "ConnectTimeout=5" in a
      and "ControlPath=none" in a and a[a.index("--") + 1] == "box-b" and kw["timeout"] == 12 and kw["stdin"] == subprocess.DEVNULL, (a[:-1], kw))
check("…it runs powershell -NoProfile -NonInteractive -EncodedCommand, no ExecutionPolicy change", a[-1].startswith("powershell -NoProfile -NonInteractive -EncodedCommand ") and "ExecutionPolicy" not in a[-1])
check("…the script reads the mode and hold files and writes nothing", "build-pool" in script and "'mode file: '" in script and "'hold file: '" in script
      and not re.search(r"WriteAllText|Move-Item|New-Item|Set-Content|Out-File|Remove-Item|Add-Content|>", script), script)
check("…its answer is read as it prints (carriage returns dropped)", out == "mode file: on\nhold file: stackshot\n" and R._parse_wsl(out)["held"] == ["stackshot"], out)
FAKE_RUN[0] = 255
try: REAL_SSH("box-b", 12); failed = None
except RunnersError as e: failed = str(e)
check("ssh exiting 255 is a RunnersError", failed == "ssh exit 255", failed)
FAKE_RUN[0] = "timeout"
try: REAL_SSH("box-b", 12); failed = None
except RunnersError as e: failed = str(e)
check("a timeout is a RunnersError", failed is not None and failed == "ssh timed out", failed)
R.subprocess.run = REAL_RUN

# ---- 5. a GitHub error, an empty list
fresh(); BROKEN.add("stackshot"); snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a GitHub error on one repo: the other repo is shown, the error is stated, the cells say unknown", {x["repo"] for x in snap["runners"]} == {"salamander"} and "stackshot" in snap["errors"]
      and "GitHub error: stackshot: GitHub answered 502" in html and "stackshot: unknown (GitHub error)" in row(html, "box-a") and "box-a-salamander-2" in row(html, "box-a"), html[:600])
fresh(); BROKEN.update(("stackshot", "salamander")); snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a GitHub error on both repos: the page still renders (a row per machine, the errors above, the Runners card at 0)", html.count('<th scope="row">') == 3 and html.count('role="alert"') == 2 and tcard(html, "Runners") == 0, html[:600])
SAVE = {k: list(v) for k, v in RUNNERS.items()}
for k in RUNNERS: RUNNERS[k] = []
fresh(); snap = R.snapshot(); html = R2.table_html(snap, T0)
check("no runners at all (a clean read): the page says so in one plain line, with no error, no count card and no empty machine rows (section 15 has the rest)",
      "GitHub lists no self-hosted CI runners" in html and "alert" not in html and "rcard" not in html and "<table" not in html and "no runners" not in html, html[:500])
RUNNERS.update(SAVE)
from stackshot.github import ghsync
fresh()

# ---- 6. the real GitHub call: the token goes in a header, an error never shows it or the query
import urllib.request, urllib.error, io
SECRET = "test-token-" + "0123456789"          # a fake token; only its being absent from the error text matters
ghsync.token = lambda *a, **k: SECRET
SEEN = []
def fake_urlopen(req, timeout=0):
    SEEN.append((req.full_url, dict(req.header_items()), timeout))
    if "boom" in req.full_url: raise urllib.error.HTTPError(req.full_url, 403, "rate limit", {}, io.BytesIO(b'{"message":"' + SECRET.encode() + b'"}'))
    return io.BytesIO(b'{"runners": []}')
real_open = R._open; R._open = lambda req, timeout: fake_urlopen(req, timeout)
R._get = REAL_GET
try:
    d = R._get("/repos/example-owner/stackshot/actions/runners?per_page=100&page=1")
    url, hdr, to = SEEN[-1]
    check("_get: the API url, the token as a bearer header, a timeout", url.startswith("https://api.github.com/repos/example-owner/stackshot/actions/runners") and hdr.get("Authorization") == f"Bearer {SECRET}"
          and 0 < to <= 30 and d == {"runners": []}, (url, to))
    try: R._get("/repos/example-owner/boom/actions/runners?per_page=100&page=1"); err = ""
    except RunnersError as e: err = str(e)
    check("_get: an HTTP error says the code and the path without its query, and never the token", err == "GitHub answered 403 for /repos/example-owner/boom/actions/runners" and SECRET not in err, err)
    ghsync.token = lambda *a, **k: ""
    try: R._get("/x"); err = ""
    except RunnersError as e: err = str(e)
    check("_get: with no token it says so", "no GitHub token" in err, err)
    # the ETag of an answer goes back as If-None-Match, and a 304 (not counted by GitHub) gives the kept answer
    ghsync.token = lambda *a, **k: SECRET
    class _Resp(io.BytesIO):
        def __init__(self, body, headers): super().__init__(body); self.headers = headers; self.status = 200
    ETAG_SEEN = []
    def etag_urlopen(req, timeout=0):
        h = dict(req.header_items()); ETAG_SEEN.append(h.get("If-none-match"))
        if h.get("If-none-match") == '"etag-one"': raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {"x-ratelimit-remaining": "4000", "x-ratelimit-limit": "5000"}, io.BytesIO(b""))
        return _Resp(b'{"runners": [1]}', {"ETag": '"etag-one"', "x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4001", "x-ratelimit-used": "999", "x-ratelimit-reset": "1", "x-ratelimit-resource": "core"})
    R._open = lambda req, timeout: etag_urlopen(req, timeout)
    R._ETAGS.clear()
    from stackshot.core import ghbudget as gb
    led0 = gb.count("r")
    a1 = R._get("/repos/example-owner/stackshot/actions/runners?per_page=100&page=1"); a2 = R._get("/repos/example-owner/stackshot/actions/runners?per_page=100&page=1")
    check("_get: the first read sends no validator, the second sends the ETag and a 304 gives the first answer back (a copy)", ETAG_SEEN == [None, '"etag-one"'] and a1 == a2 == {"runners": [1]} and a1 is not a2, (ETAG_SEEN, a1, a2))
    check("_get: the two reads are one in the host's hourly ledger, the 304 none", gb.count("r") == led0 + 1, (gb.count("r"), led0))
    cap_was = ghsync._cfg.CFG.get("github", {}).get("read_budget"); ghsync._cfg.CFG.setdefault("github", {})["read_budget"] = gb.count("r")
    n_seen = len(ETAG_SEEN)
    try: R._get("/repos/example-owner/another/actions/runners"); err = ""
    except RunnersError as e: err = str(e)
    check("_get: over the read cap nothing is sent; the page's error says when reads resume", len(ETAG_SEEN) == n_seen and err.startswith("GitHub reads are held by the hourly cap (") and "resume in about" in err, (err, len(ETAG_SEEN) - n_seen))
    if cap_was is None: ghsync._cfg.CFG["github"].pop("read_budget", None)
    else: ghsync._cfg.CFG["github"]["read_budget"] = cap_was
    R._get("/repos/example-owner/other/actions/runners")
    check("_get: another path has its own ETag (none sent for it)", ETAG_SEEN[-1] is None, ETAG_SEEN)
    # the page no longer shows the hour's GitHub calls: the ledger itself stays, only the line is gone
    check("the 'GitHub calls' line is gone from the page: no calls_line, no such text in the table or the JSON",
          not hasattr(R, "calls_line") and "github calls" not in R2.table_html(R._unread('x'), T0).lower() and "github calls" not in R2.data(R._unread('x'), T0)["html"].lower())
    check("_get: the rate-limit headers it saw are recorded", ghsync.rate_seen().get("limit") == 5000, ghsync.rate_seen())
finally:
    R._open = real_open
R._get = fake_get

# ---- 7. over HTTP, in-process
from stackshot.web import server
server._publish = lambda: None
from stackshot.web.ui import render as ui_render
from starlette.testclient import TestClient
fresh(); setfiles(mode="on\n", hold="", gate="")
SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on", "salamander")})
with TestClient(server.mcp.http_app()) as c:
    r = get_settled(c, "/runners")
    check("GET /runners: 200 HTML, not cached", r.status_code == 200 and r.headers["content-type"].startswith("text/html") and r.headers.get("cache-control") == "no-store", (r.status_code, r.headers))
    h = r.text
    names = re.findall(r'<b class="rname">([^<]+)</b>', h)
    gh = sorted(x["name"] for v in RUNNERS.values() for x in v)
    check("the page lists every runner the fake GitHub lists, once each (10 = 10)", sorted(names) == gh and len(names) == 10, (len(names), len(gh)))
    check("…in the board's chrome: the home title bar, the page's own title, and the 30 s refresh of /runners.json", "<h1>CI runners</h1>" in h
          and "fetch('/runners.json'" in h and ",30000)" in h and 'id="rn-body"' in h, h[-1500:])
    # the home title bar and the side panel on this page too, as on every other page
    bad = []
    if re.findall(r'<(?:h1|p) class="site"><a href="([^"]*)"><img class="logo"', h) != ["/"]: bad.append("title link is not exactly one href=/")
    if '<a href="/">\u2190' in h: bad.append("the old back arrow link is still there")
    for need in (ui_render._PANEL_BODY + '<div id="layout">', '<aside id="panel"', 'id="panel-edge"', 'id="panel-scrim"', 'id="panel-open"', 'id="machines"', 'id="runners"', 'id="audit-panel"', ui_render._PANEL_JS[:60]):
        if need not in h: bad.append("missing " + need)
    # the board item (Oliver): pinned by default, nothing remembered
    if '<body class="panel-pin">' not in h or 'aria-expanded="true" title="Hide summary panel"' not in h: bad.append("the panel does not render pinned")
    if "stackshot.panel" in h or "localStorage" in ui_render._PANEL_JS: bad.append("the panel state is stored in the browser")
    if h.count('<nav class="hcards"') != 1: bad.append("the header's count cards are not there once")
    if h.count('<aside id="panel"') != 1 or h.count('id="layout"') != 1 or h.count("</div><script>") < 1: bad.append("panel / layout not once, or no script")
    check("/runners has the home title as a link to /, the header's count cards and the same side panel, once", bad == [], bad)
    ids = re.findall(r'\bid="([^"]+)"', h)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    check("no id is used twice on the page (the panel's ids against the runners content)", not dup, dup)
    check("the page's own table is unchanged beside the panel (10 runner rows in the table body, and the panel's Runners section is a separate block)",
          'id="rn-body"' in h and h.index('id="rn-body"') < h.index('<aside id="panel"') and 'id="runners"' in h[h.index('<aside id="panel"'):], ids)
    n = len(CALLS); r2 = c.get("/runners.json"); d = r2.json()
    settle()
    check("GET /runners.json: JSON, not cached, from the cached snapshot (no new GitHub call)", r2.status_code == 200 and r2.headers["content-type"].startswith("application/json")
          and r2.headers.get("cache-control") == "no-store" and len(CALLS) == n, (r2.status_code, len(CALLS), n))
    check("…its shape: ts, stale, errors, a runner list with state, job and reason, and the table as html", set(d) == {"ts", "stale", "refreshing", "pending", "errors", "counts", "switch", "runners", "html"} and len(d["runners"]) == 10
          and {x["state"] for x in d["runners"]} == {"idle", "running", "offline"} and d["html"].startswith('<p class="sub rasof"') and "<table" in d["html"], d.keys())
    run = next(x for x in d["runners"] if x["name"] == "box-a-salamander-2")
    check("…a running runner carries its job (repo, PR, elapsed seconds), an offline one its reason", run["job"]["pr"] == 17 and run["job"]["elapsed_s"] == 300
          and next(x for x in d["runners"] if x["name"] == "box-b-stackshot")["reason"] == "disabled on box-b", run)
    check("…and html is what the page holds in its body", d["html"] in h.replace("&#x27;", "'") or re.sub(r"\s", "", d["html"][:200]) in re.sub(r"\s", "", h), d["html"][:100])
    BROKEN.add("stackshot"); R.reset()
    r = get_settled(c, "/runners")
    check("a GitHub error: the page is still a 200 and says it", r.status_code == 200 and "GitHub error: stackshot: GitHub answered 502" in r.text, r.status_code)
    check("…and so does the JSON", "stackshot" in c.get("/runners.json").json()["errors"])
    BROKEN.clear(); R.reset()
    h = ui_render.Board(str(T / "store")).render({"html"})["html"]
    hd = h[h.find('<header class="top">'):h.find("</header>")]
    check("the board's header no longer links /runners (the panel's Runners cards link it, and there is no separate link)", '<header class="top">' in h and "/runners" not in hd and "Runners page" not in h, hd[:400])
    real_mode, server._signin._auth_mode = server._signin._auth_mode, (lambda: "google"); server._cfg.CFG["auth"]["ui_open"] = False
    r1, r2 = c.get("/runners", follow_redirects=False), c.get("/runners.json", follow_redirects=False)
    check("[auth] ui_open = false: both ask for the board's sign-in first, as the other pages do", r1.status_code == 302 and r1.headers["location"] == "/ui/login?next=%2Frunners"
          and r2.status_code == 302 and r2.headers["location"] == "/ui/login?next=%2Frunners.json", (r1.status_code, r1.headers.get("location"), r2.status_code))
    server._signin._auth_mode = real_mode; server._cfg.CFG["auth"]["ui_open"] = True

# ---- 7b. the machine comes from the runner's name; the labels are only the fallback
def rl(name, *labels, online=True): return {"id": sum(map(ord, name)), "name": name, "status": "online" if online else "offline", "busy": False,
                                            "labels": [{"name": x} for x in ("self-hosted", "pool", "heavy") + labels]}
def rows_of(h): return {b: len(re.findall(r'<li class="rn ', rw)) for b, rw in re.findall(r'<tr class="[^"]*"><th scope="row"><div class="mname">([\w-]+)</div>(.*?)</tr>', h, re.S)}
SAVED_RUNNERS = dict(RUNNERS)
try:
    RUNNERS["salamander"] = [rl("box-a-salamander", "box-a"), rl("box-b-salamander-3", "box-a", "box-b"), rl("box-b-salamander-4", "box-b"),
                             rl("oddname", "box-c"), rl("oddname2", "box-b", "box-a"), rl("mystery")]
    RUNNERS["stackshot"] = [rl("box-a-stackshot", "box-a"), rl("box-c-stackshot", "box-c"), rl("box-c-stackshot-2", "box-a")]
    R._get = fake_get; fresh(); setfiles(mode="on\n", hold="", gate="")
    snap = R.snapshot(); x = by(snap)
    check("a runner named box-b-salamander-3 with the labels box-a and box-b lands in box-b (the name wins over a stale label)", x["box-b-salamander-3"]["box"] == "box-b", x["box-b-salamander-3"])
    check("a runner named oddname with the label box-c lands in box-c (no box in its name: the label)", x["oddname"]["box"] == "box-c", x["oddname"])
    check("a name with no box and several box labels: the first box in the configured order (box-a before box-b)", x["oddname2"]["box"] == "box-a", x["oddname2"])
    check("a name with no box and no box label stays 'other'", x["mystery"]["box"] == "other", x["mystery"])
    check("a name with a box and a label for another one: the name (box-c-stackshot-2 carries only box-a)", x["box-c-stackshot-2"]["box"] == "box-c", x["box-c-stackshot-2"])
    check("a plain runner is where its name and label say", x["box-a-salamander"]["box"] == "box-a" and x["box-c-stackshot"]["box"] == "box-c")
    want = {"box-a": 3, "box-b": 2, "box-c": 3, "other": 1}
    html = R2.table_html(snap, T0)
    check("the page: a row per machine plus 'other', in order", list(rows_of(html)) == ["box-a", "box-b", "box-c", "other"], list(rows_of(html)))
    check("the page: each row lists the right number of runners (3, 2, 3, 1)", rows_of(html) == want, rows_of(html))
    check("the page: box-b-salamander-3 is in the box-b row and not in the box-a row", "box-b-salamander-3</b>" in row(html, "box-b") and "box-b-salamander-3</b>" not in row(html, "box-a"))
    check("the page counts them: 9 runners", tcard(html, "Runners") == 9, html[:600])
    with TestClient(server.mcp.http_app()) as c:
        R.reset(); CALLS.clear()
        d = get_settled(c, "/runners.json").json()
        counts = {}
        for q in d["runners"]: counts[q["box"]] = counts.get(q["box"], 0) + 1
        check("/runners.json: the per-box counts are right (3, 2, 3, 1)", counts == want, counts)
        check("/runners.json: the runner list says box-b for box-b-salamander-3", next(q for q in d["runners"] if q["name"] == "box-b-salamander-3")["box"] == "box-b")
        check("/runners.json html: the same counts per row", rows_of(d["html"]) == want, rows_of(d["html"]))
        check("GET /runners: the same counts per row on the served page", rows_of(c.get("/runners").text) == want, rows_of(c.get("/runners").text))
finally:
    RUNNERS.clear(); RUNNERS.update(SAVED_RUNNERS); R.reset(); CALLS.clear()

# ---- 7c. the Runners column lists one runner per line, top to bottom (ui/runners.py): .rl is a single column track
def rl_rule(css):
    m = re.search(r"(?m)^\.rl\{([^}]*)\}", css); return m.group(1) if m else ""
def rl_columns(css):                                 # the .rl rule's grid-template-columns, or None when it has none
    m = re.search(r"grid-template-columns:([^;}]+)", rl_rule(css)); return m.group(1).strip() if m else None
SIX = {"ts": T0, "errors": {}, "runners": [{"box": "box-a", "repo": "salamander", "state": st, "name": f"box-a-salamander-{i}", "kind": "", "reason": "", "job": None}
                                          for i, st in enumerate(("idle", "running", "idle", "offline", "idle", "running"))]}
for label, mod in (("ui/runners.py", R2),):
    rule, cols = rl_rule(mod._CSS), rl_columns(mod._CSS)
    check(f"{label}: the runner list (.rl) is one column: a single grid track and no auto-fill or repeat()", rule and cols is not None and "repeat(" not in cols and "auto-fill" not in cols
          and "auto-fit" not in cols and len(cols.split()) == 1, (rule, cols))
    check(f"{label}: the runner list's gap leaves no column gap (one runner per line)", re.search(r"gap:\s*\S+\s+0(?:px)?\s*(?:;|$)", rule) is not None, rule)
    check(f"{label}: no later rule (the phone layout included) puts the runner list back into columns",
          [m.group(0) for m in re.finditer(r"\.rl\b[^{]*\{[^}]*grid-template-columns[^}]*\}", mod._CSS)] == [f".rl{{{rule}}}"], re.findall(r"\.rl\b[^{]*\{[^}]*\}", mod._CSS))
    h = mod.table_html(SIX, T0)
    lists = re.findall(r'<ul class="rl">(.*?)</ul>', h, re.S)
    check(f"{label}: a machine with six runners draws them as one list of six, in order", len(lists) == 1 and re.findall(r"<b class=\"rname\">([^<]+)</b>", lists[0]) == [f"box-a-salamander-{i}" for i in range(6)],
          (len(lists), re.findall(r"<b class=\"rname\">([^<]+)</b>", h)))

# ---- 8. the review's cases (the review): a hostile text, single flight, the deadline, odd answers, no redirect, the stale cue
import threading, time, http.client, http.server
EVIL = '"><img src=x onerror=1>'
def evil_in(h): return "<img src=x" in h or re.search(r"<[^>]*onerror\s*=", h) is not None

# 8a. hostile runner name, head_branch, run url, GitHub error text, ssh error text: escaped everywhere, nothing raw
SAVE = ({k: list(v) for k, v in RUNNERS.items()}, {k: list(v) for k, v in RUNS.items()}, dict(JOBS))
RUNNERS["salamander"].append(rn(EVIL, "box-a", busy=True)); RUNNERS["salamander"].append(rn(EVIL + "-off", "box-b", online=False))
RUNS["salamander"].append({"id": 12, "head_branch": EVIL, "html_url": 'javascript:alert(1)"', "pull_requests": [], "run_started_at": iso(T0 - 60)})
JOBS[12] = [{"id": 121, "status": "in_progress", "runner_name": EVIL, "started_at": iso(T0 - 60)}]
RUNS["salamander"].sort(key=lambda r: r["id"])
SSH_OUT["box-b"] = RunnersError(EVIL); SSH_OUT["box-c"] = wsl("on", "salamander")
class Hostile:                                       # GitHub's error for the second repo carries the markup
    def __call__(self, path, timeout=8):
        if "/stackshot/actions/runners" in path: raise RunnersError(EVIL)
        return fake_get(path, timeout)
fresh(); R._get = Hostile(); setfiles(mode="on\n", hold="", gate="")
with TestClient(server.mcp.http_app()) as c:
    h = get_settled(c, "/runners").text; j = c.get("/runners.json").json()
    check("hostile texts: no raw <img or onerror= tag in /runners", not evil_in(h) and "&lt;img src=x" in h, [m for m in re.findall(r".{40}<img.{40}", h)][:2])
    check("…nor in /runners.json html", not evil_in(j["html"]) and "&lt;img src=x" in j["html"], j["html"][:300])
    check("…the hostile branch and the javascript: link: the branch shown escaped, the link a github.com address", "javascript:" not in j["html"] and 'href="https://github.com/example-owner/salamander/tree/' in j["html"], j["html"][:300])
    check("…the ssh error text is not shown at all (a fixed 'ssh failed')", "box not reachable (ssh failed)" in j["html"], j["html"][:200])
R._get = fake_get; RUNNERS.update(SAVE[0]); RUNS.update(SAVE[1]); JOBS.clear(); JOBS.update(SAVE[2])
SSH_OUT["box-b"] = wsl("off")

# 8b. single flight: two threads call snapshot() at once, one fetch runs
GATE = threading.Event(); STARTED = threading.Event()
def blocking_get(path, timeout=8):
    STARTED.set(); GATE.wait(10); return fake_get(path, timeout)
def runner_lists(): return sum("/actions/runners?" in p for p in CALLS)
fresh(); R._get = blocking_get; GATE.clear(); STARTED.clear(); got = []
try:
    t1 = threading.Thread(target=lambda: got.append(R.snapshot()), daemon=True); t1.start(); STARTED.wait(5)
    t2 = threading.Thread(target=lambda: got.append(R.snapshot()), daemon=True); t2.start(); time.sleep(0.3)
    check("two threads at once, nothing cached: the second waits for the first's build", got == [] and t2.is_alive())
finally:
    GATE.set()
t1.join(10); t2.join(10)
check("…then both get the one snapshot and only one fetch ran (2 runner lists, one per repo)", len(got) == 2 and got[0] is got[1] and runner_lists() == 2, (len(got), runner_lists()))
fresh(); R._get = fake_get; R.snapshot(); first_n = len(R.snapshot()["runners"]); CLOCK[0] = T0 + 100
R._get = blocking_get; GATE.clear(); STARTED.clear(); got = []; CALLS.clear()
try:
    t1 = threading.Thread(target=lambda: got.append(R.snapshot()), daemon=True); t1.start(); STARTED.wait(5)
    t0 = time.monotonic(); st = R.snapshot(); took = time.monotonic() - t0
    check("a rebuild in flight and a previous snapshot: the next request gets it at once, marked stale", took < 1 and st["stale"] is True and len(st["runners"]) == first_n and st["ts"] == T0, (took, st.get("stale")))
    h = R2.table_html(st, T0 + 100); d = R2.data(st, T0 + 100)
    check("…the table says when it was last refreshed, and the JSON says stale", f"not refreshed since {CLK}:00 {ABBR}" in h and d["stale"] is True, h[:200])
    check("…the page marks the body stale", 'data-stale="1"' in R2.page_html(ui_render.Board(str(T / "store")), st))
finally:
    GATE.set()
t1.join(10)
check("…when the rebuild ends the snapshot is fresh again (not stale)", R.snapshot()["stale"] is False and R.snapshot()["ts"] == T0 + 100)
R._get = fake_get

# 8c. the deadline: the whole build is bounded, the calls get shorter timeouts, and nothing is fetched past it
MONO = [1000.0]; R._mono = lambda: MONO[0]
def slow_get(path, timeout=8):
    MONO[0] += 9; return fake_get(path, timeout)
fresh(); R._get = slow_get; TIMEOUTS.clear(); snap = R.snapshot(); x = by(snap)
check("a slow GitHub (9 s a call, 20 s for the build): the repo that ran out of time is an error, the first repo is shown", "stackshot" in snap["errors"] and "out of time" in snap["errors"]["stackshot"]
      and "box-a-salamander-2" in x, snap["errors"])
check("…each call's timeout is capped by what is left (8, 8, then 2 s)", TIMEOUTS[:3] == [8, 8, min(8, 20 - 18)] or (TIMEOUTS[0] == 8 and max(TIMEOUTS) <= 8 and min(TIMEOUTS) < 3), TIMEOUTS)
check("…no job is fetched past the deadline, no ssh read starts with no time left", sum("/jobs" in p for p in CALLS) <= 1 and SSH == [] and x["box-b-salamander"]["kind"] == "unread", (CALLS, SSH))
R._mono = time.monotonic; R._get = fake_get

# 8d. odd answers: a cut-off read, a non-numeric count, junk runs and jobs; the error is recorded and cached like any other
class Odd:
    def __init__(self, how): self.how = how
    def __call__(self, path, timeout=8):
        if self.how == "short" and "/stackshot/actions/runners" in path: CALLS.append(path); raise http.client.IncompleteRead(b"par")
        if self.how == "count" and "/salamander/actions/runners" in path: CALLS.append(path); return {"total_count": "many", "runners": RUNNERS["salamander"]}
        if self.how == "junk" and "/salamander/actions/runs?" in path: CALLS.append(path); return {"workflow_runs": ["junk", None, 7] + RUNS["salamander"]}
        if self.how == "junk" and "/salamander/actions/runs/11/jobs" in path: CALLS.append(path); return {"jobs": ["junk", None] + JOBS[11]}
        return fake_get(path, timeout)
fresh(); R._get = Odd("short"); snap = R.snapshot(); n = len(CALLS); R.snapshot(); R.snapshot()
check("a cut-off read (IncompleteRead) on one repo: recorded as an error with the kind of exception only, the other repo shown", set(snap["errors"]) == {"stackshot"} and "IncompleteRead" in snap["errors"]["stackshot"]
      and {x["repo"] for x in snap["runners"]} == {"salamander"}, snap["errors"])
check("…and cached like any other result (no new call in the next requests)", len(CALLS) == n)
fresh(); R._get = Odd("count"); snap = R.snapshot()
check("a non-numeric total_count: that repo is an error (ValueError), not a crash", set(snap["errors"]) == {"salamander"} and "ValueError" in snap["errors"]["salamander"] and {x["repo"] for x in snap["runners"]} == {"stackshot"}, snap["errors"])
fresh(); R._get = Odd("junk"); snap = R.snapshot(); x = by(snap)
check("junk among the runs and jobs (strings, null, numbers) is skipped: the job is still found, no error", snap["errors"] == {} and x["box-a-salamander-2"]["job"]["pr"] == 17, snap["errors"])
R._get = fake_get

# 8e. a redirect is never followed (the Authorization header would follow it)
check("the opener has a no-redirect handler that answers None", any(isinstance(h, R._NoRedirect) for h in R._OPENER.handlers) and R._NoRedirect().redirect_request(None, None, 302, "", {}, "http://x/") is None)
SEEN_PATHS = []
class Redirecting(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN_PATHS.append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/a"): self.send_response(302); self.send_header("Location", "/b"); self.end_headers()
        else: self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
httpd = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)         # an ephemeral port, never 8010 or 8020
th = threading.Thread(target=httpd.serve_forever, daemon=True); th.start()
real_api = ghsync.api_url; ghsync.token = lambda *a, **k: "ghp_REDIRTEST"; ghsync.api_url = lambda: f"http://127.0.0.1:{httpd.server_address[1]}"
R._get = REAL_GET
try:
    try: R._get("/a/x"); err = ""
    except RunnersError as e: err = str(e)
finally:
    R._get = fake_get; ghsync.api_url = real_api; httpd.shutdown(); httpd.server_close(); th.join(5)
check("a 302 from GitHub is an error, and the redirect target is never requested", err == "GitHub answered 302 for /a/x" and [p for p, _ in SEEN_PATHS] == ["/a/x"], (err, SEEN_PATHS))

# 8f. the unreachable box: only fixed words, never stderr
for exc, want in ((RunnersError("ssh exit 255"), "box not reachable (ssh exit 255)"), (RunnersError("ssh timed out"), "box not reachable (ssh timed out)"),
                  (RunnersError("Permission denied (publickey) for home@192.0.2.3"), "box not reachable (ssh failed)")):
    SSH_OUT["box-b"] = exc; fresh(); x = by(R.snapshot())
    check(f"unreachable: {want!r}", x["box-b-stackshot"]["reason"] == want and x["box-b-stackshot"]["kind"] == "unreachable", x["box-b-stackshot"])
SSH_OUT["box-b"] = wsl("off")

# 8g. the page's script: the poll pauses while the tab is hidden, loads at once on return, and says when it could not refresh
fresh(); R.snapshot(); pg = R2.page_html(ui_render.Board(str(T / "store")), R.snapshot())
check("the script polls every 30 s only while the tab is visible", "setInterval(function(){if(!document.hidden)load()},30000)" in pg, pg[-1200:])
check("…and loads at once when the tab becomes visible again", "visibilitychange" in pg and "if(!document.hidden)load()" in pg)
check("…a failed or non-JSON reply (an expired sign-in) marks the table stale and says so", "data-stale" in pg and "sign in again" in pg and "Not refreshed since " in pg and "indexOf('json')<0" in pg)
check("…a stale table is drawn muted by a [data-stale] rule", "[data-stale]{opacity:" in pg and 'id="rn-note"' in pg)


# 8h. an abandoned "building" mark (a build that never came back) does not stop the next request from rebuilding
fresh(); R._get = fake_get
R._CACHE["building"] = {"ev": threading.Event(), "since": time.monotonic() - 20 - 30 - 1}      # older than build_s + 30 s
t0 = time.monotonic(); snap = R.snapshot(); took = time.monotonic() - t0
check("a building mark older than build_s + 30 s is abandoned: the next request rebuilds (no wait, a fresh snapshot, the mark cleared)", took < 5 and len(snap["runners"]) == 10
      and snap["stale"] is False and runner_lists() == 2 and "building" not in R._CACHE, (took, len(snap["runners"]), runner_lists()))
fresh(); R._CACHE["building"] = {"ev": threading.Event(), "since": time.monotonic() - 5}
R._CACHE["snap"] = {"ts": T0 - 100, "errors": {}, "runners": [], "stale": False}
st = R.snapshot()
check("…a recent mark is still respected: the previous snapshot comes back stale and nothing is fetched", st["stale"] is True and CALLS == [], (st.get("stale"), CALLS))
fresh()
check("the page's fetch is aborted after 15 s and busy is cleared, so one that never settles cannot stop the polling", "new AbortController()" in pg and "ac.abort();busy=false},15000" in pg and "clearTimeout(tm)" in pg, pg[-1400:])

# ---- 9. the side panel's Runners section: the last snapshot, never a build
import datetime as _dtm
NOW = _dtm.datetime.fromtimestamp(T0 + 30, _dtm.timezone.utc)
def board_html(now=NOW): return ui_render.Board(str(T / "store"), now=now).html()
def runners_section(h):
    a = h.find('<section id="runners">'); return h[a:h.find("</section>", a)] if a >= 0 else ""
RLINK = "Runners page"
RC = re.compile(r'<a class="pc rc" href="/runners" target="_blank" rel="noopener"><b class="rn">(.*?)</b><span class="rv (\w+)">(.*?)</span><span class="go" aria-hidden="true">↗</span></a>', re.S)
def cards(sec): return RC.findall(sec)
def words(frag): return re.sub(r"\s+", " ", __import__("html").unescape(re.sub(r"<[^>]+>", " ", frag))).strip()
def card_lines(sec):
    """{box name as written in the HTML: [its one count, as drawn]} (one line a machine, summed over its repos)"""
    return {n: [t] for n, c, t in cards(sec)}
def card_cls(sec): return {n: c for n, c, t in cards(sec)}
def audit_section(h):
    a = h.find('<section id="audit-panel">'); return h[a:h.find("</section>", a)] if a >= 0 else ""
LABEL = 'S<i>&"x'                                           # [runners.labels] salamander = S<i>&"x (set in the top of this file)
def seeded(broken=()):
    """Build a snapshot with the fake GitHub (its offline runners long offline, so faults, not restarts), then cache only it (the panel reads the cache and never builds)."""
    fresh(); BROKEN.update(broken); R.AUTOSTART = False; snap = aged(); BROKEN.clear(); R.reset(); R._CACHE["snap"] = snap; CALLS.clear(); return snap

# 9a. no snapshot yet: a short line, the heading links /runners, no GitHub call, no thread (AUTOSTART is off at import)
fresh(); R.AUTOSTART = False
sec = runners_section(board_html())
check("panel, no snapshot: 'not read yet', the heading is plain text, and no 'Runners page ↗' link in the section any more",
      "not read yet" in sec and "<h2 class=\"hdr\">Runners</h2>" in sec and "<a" not in sec and RLINK not in sec and not cards(sec), sec[:400])
check("panel: the hour's GitHub calls are no longer a loose line in the Runners section (a card in the Audit section now)", "github calls" not in sec and 'class="mnote"' in sec and sec.count('class="mnote"') == 1, sec[-300:])
check("…rendering made no GitHub call and started no build (a test that renders the board never reaches GitHub)", CALLS == [] and R._PEEK["thread"] is None and R.peek() is None, CALLS)
hh = board_html()
check("…the section is a fold in the side panel, open on load, between Machines and Anchor hub's place", sec.startswith('<section id="runners"><details class="fold" data-fold="runners" open><summary>')
      and 0 < hh.find('<section id="machines">') < hh.find('<section id="runners">') < hh.find("</aside>") and hh.find("</main>") < hh.find('<section id="runners">'))

# 9b. counts per card and per repo, from the fixture
setfiles(mode="on\n", hold="", gate="")
SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on", "salamander")})
seeded(); sec = runners_section(board_html()); cl = card_lines(sec); calls_after_render = len(CALLS)
check("panel: a one-line card per machine in the config's order, each linking to /runners in a new tab; the heading is plain, no 'Runners page' link, no per-repo line, no hover text on a card (the section's order grip has its own)",
      list(cl) == ["box-a", "box-b", "box-c"] and sec.count('<a class="pc rc" href="/runners"') == 3 and sec.count("<a ") == 3 and RLINK not in sec and 'class="mr' not in sec and "<h2 class=\"hdr\">Runners</h2>" in sec
      and "title=" not in re.sub(r"<button.*?</button>", "", sec, flags=re.S) and '<div class="rlist">' in sec and '<div class="matrix">' not in sec, (list(cl), sec.count('<a class="pc rc" href="/runners"'), sec.count("<a "), RLINK in sec, 'class="mr' in sec, "title=" in sec))
check("panel: the count is summed over the machine's repos (box-a: salamander 1 of 3 running + stackshot 1 of 1 = 2/4), the repo labels are gone from the card", cl["box-a"] == ["2/4"] and "stackshot" not in sec and "S&lt;i" not in sec, cl["box-a"])
check("panel: a machine whose switch is off and which runs no job reads 'disabled' (box-b: both repos offline because it was disabled)", cl["box-b"] == ["disabled"], cl["box-b"])
SSH_OUT["box-b"] = wsl("on"); seeded(); cl_on = card_lines(runners_section(board_html())); SSH_OUT["box-b"] = wsl("off")
check("panel: the same machine with its switch on and no runner online reads 'offline' (that is the fault case)", cl_on["box-b"] == ["offline"], cl_on["box-b"])
seeded()
check("panel: an all-offline repo adds nothing to the sum: box-c (salamander offline, stackshot one idle online runner) reads 0/1", cl["box-c"] == ["0/1"], cl["box-c"])
cc = card_cls(sec)
check("panel: the count's class: busy while some runners run and some do not (box-a 2/4), idle at 0 busy (box-c 0/1), off for a disabled machine (box-b); the arrow is aria-hidden after the count",
      cc == {"box-a": "busy", "box-b": "off", "box-c": "idle"} and sec.count('<span class="go" aria-hidden="true">↗</span></a>') == 3, cc)
for css_part in ("#panel .pc.rc{display:flex", "#panel .pc.rc .rv.busy{color:var(--fg);font-weight:700}", "#panel .pc.rc .rv.full{color:var(--warn);font-weight:700}", "#panel a.pc.rc:hover{border-color:var(--acc)}", "#panel a.pc.rc:hover .go{color:var(--acc)}"):
    check(f"panel CSS: {css_part}", css_part in ui_render._RUN_CSS, css_part)
check("panel CSS: the muted count and arrow use the panel's own variables (no new colour)", "#panel .pc.rc .rv{flex:none;font-variant-numeric:tabular-nums;color:var(--mut)}" in ui_render._RUN_CSS and "#panel .pc.rc .go{flex:none;color:var(--mut)}" in ui_render._RUN_CSS)
check("card_total: full when every online runner is busy, busy when some are, idle at none; the sum over repos",
      R.card_total({"box": "x", "lines": [{"state": "ok", "active": 1, "online": 1}, {"state": "ok", "active": 2, "online": 2}]}) == {"text": "3/3", "cls": "full"}
      and R.card_total({"box": "x", "lines": [{"state": "ok", "active": 1, "online": 3}, {"state": "ok", "active": 0, "online": 2}]}) == {"text": "1/5", "cls": "busy"}
      and R.card_total({"box": "x", "lines": [{"state": "ok", "active": 0, "online": 2}, {"state": "ok", "active": 0, "online": 1}]}) == {"text": "0/3", "cls": "idle"}
      and R.card_total({"box": "x", "lines": [{"state": "ok", "active": 2, "online": 2}, {"state": "offline", "active": 0, "online": 0}]}) == {"text": "2/2", "cls": "full"})
check("card_total: no online runner reads offline, a failed read unknown, no line 'no runners' (all idle); a sum beside a repo that could not be read carries ' ?'",
      R.card_total({"box": "x", "lines": [{"state": "offline", "active": 0, "online": 0}]}) == {"text": "offline", "cls": "idle"}
      and R.card_total({"box": "x", "lines": [{"state": "offline", "active": 0, "online": 0}, {"state": "unknown", "active": 0, "online": 0}]}) == {"text": "unknown", "cls": "idle"}
      and R.card_total({"box": "x", "lines": []}) == {"text": "no runners", "cls": "idle"}
      and R.card_total({"box": "x", "lines": [{"state": "ok", "active": 1, "online": 3}, {"state": "unknown", "active": 0, "online": 0}]}) == {"text": "1/3 ?", "cls": "busy"})
check("card_total: a machine whose switch is off and which runs no job reads 'disabled' (class off), even when a repo's list failed",
      R.card_total({"box": "x", "disabled": True, "lines": [{"state": "offline", "active": 0, "online": 0}]}) == {"text": "disabled", "cls": "off"}
      and R.card_total({"box": "x", "disabled": True, "lines": [{"state": "unknown", "active": 0, "online": 0}]}) == {"text": "disabled", "cls": "off"})
check("panel: no 'other' card while every runner is on a known box, and rendering from the cache made no call", "other" not in cl and calls_after_render == 0, (list(cl), calls_after_render))

# 9c. labels: [runners.labels] entry, else the repo's name; hostile text escaped (labels, box names, runner names)
check("labels: the panel's cards carry no repo label (the Runners page keeps them), so no label text, raw or escaped, reaches the panel", "S<i>" not in sec and "S&lt;i" not in sec and "salamander" not in sec, sec[:500])
check("labels: a repo with no entry shows its own name on the Runners page's side of it", R.label("stackshot") == "stackshot" and R.label("salamander") == LABEL)
SAVE = {k: list(v) for k, v in RUNNERS.items()}
RUNNERS["stackshot"].append(rn("<img src=x>-stackshot", "box-a")); RUNNERS["stackshot"][-1]["labels"] = [{"name": "self-hosted"}]
seeded(); sec = runners_section(board_html()); cl = card_lines(sec)
check("an 'other' card appears only when such a runner exists, last, with its own count", list(cl) == ["box-a", "box-b", "box-c", "other"] and cl["other"] == ["0/1"], cl)
check("…a runner named with hostile text never reaches the panel (only counts are drawn)", "<img" not in sec and "img src" not in sec, sec)
RUNNERS.update(SAVE)
boxes_save = R._cfg.CFG["runners"]["boxes"]; R._cfg.CFG["runners"]["boxes"] = ["box-a", "<b>x</b>"]
try:
    seeded(); sec = runners_section(board_html())
finally:
    R._cfg.CFG["runners"]["boxes"] = boxes_save
check("a box name is escaped in its card", "&lt;b&gt;x&lt;/b&gt;" in sec and "<b>x</b>" not in sec and "<b>x" not in sec, sec[:400])

# 9d. a repo with no runners on a box shows no line; a repo whose GitHub read failed reads unknown there
RUNNERS["salamander"] = [r for r in RUNNERS["salamander"] if r["name"] != "box-c-salamander"]
seeded(); cl = card_lines(runners_section(board_html()))
check("a repo with no runners on a box adds nothing there (box-c has only stackshot now: 0/1; box-a still 2/4)", cl["box-c"] == ["0/1"] and cl["box-a"] == ["2/4"], cl)
RUNNERS.update(SAVE)
seeded(("stackshot",)); cl = card_lines(runners_section(board_html()))
check("a repo whose GitHub read failed shows a ' ?' after the sum of the repos that could be read (box-a: salamander 1/3, stackshot unknown), and 'unknown' where nothing could (silence would read as no runners)", cl["box-a"] == ["1/3 ?"] and cl["box-c"] == ["unknown"] and cl["box-b"] == ["disabled"], cl)
seeded(("salamander", "stackshot")); cl = card_lines(runners_section(board_html()))
check("both reads failed: every card says unknown, except a machine whose switch is off (it reads 'disabled' without GitHub)", cl == {"box-a": ["unknown"], "box-b": ["disabled"], "box-c": ["unknown"]}, cl)

# 9e. an old snapshot says when it was read; a young one says nothing (the block's fingerprint holds still between rebuilds)
seeded()
check("a snapshot younger than three times the larger of panel_refresh_s and the publish interval (30 min) carries no note, even past the idle publish interval", "last read at" not in runners_section(board_html()) and "last read at" not in runners_section(board_html(_dtm.datetime.fromtimestamp(T0 + 1700, _dtm.timezone.utc))))
sec = runners_section(board_html(_dtm.datetime.fromtimestamp(T0 + 1900, _dtm.timezone.utc)))
check(f"…an older one says 'last read at {CLK} {ABBR}' and still shows its numbers", f"last read at {CLK} {ABBR}" in sec and "2/4" in words(sec), sec[:400])

# 9e2. the GitHub calls card in the Audit section: the name, writes / reads (cap muted, thousands separator) and the 60-minute window counted, from the ledger file as of the render
from stackshot.core import ghbudget as _gbm
_led = R._cfg.state("github", _gbm.LEDGER_NAME); _led_save = _led.read_bytes() if _led.exists() else None
_tzn = R._cfg.tz()
try:
    _led.parent.mkdir(parents=True, exist_ok=True)
    _led.write_text(json.dumps({_gbm.WRITE: [NOW.timestamp() - 5 * i - 1 for i in range(15)], _gbm.READ: [NOW.timestamp() - 2 * i - 1 for i in range(1204)] + [NOW.timestamp() - 3700]}), encoding="utf-8")   # one read is older than the hour
    _hh = board_html(); asec = audit_section(_hh); _end = NOW.astimezone(_tzn); _start = _end - __import__("datetime").timedelta(minutes=60)
    _want = ('<div id="ghcalls" class="pc ghc"><b class="lbl mh">GitHub calls</b><span class="lbl">writes</span><span class="val">15 <span class="cap">/ ' + f"{_gbm.write_cap():,}" + '</span></span>'
             '<span class="lbl">reads</span><span class="val">1,204 <span class="cap">/ ' + f"{_gbm.read_cap():,}" + '</span></span>'
             f'<span class="lbl">counted</span><span class="val">{_start:%H:%M} – {_end:%H:%M}</span></div>')
    check("GitHub calls card: in the Audit section, named 'GitHub calls', rows writes / reads / counted; the count with a thousands separator and the cap in its muted span; the window is the 60 minutes before the render, HH:MM in the board's zone",
          _want in asec and asec.count('class="pc ghc"') == 1 and "1,204 " in asec and "(1,205" not in asec, (asec[-700:], _want))
    check("…it sits in the same section as the daily audit card, after it when the audit is on, and a read older than the hour is not counted (1,204, not 1,205)", asec.startswith('<section id="audit-panel"><details class="fold" data-fold="audit-panel" open><summary><h2 class="hdr">Audit</h2></summary>')
          and asec.index('id="ghcalls"') > asec.index('id="audit"'), asec[:600])
    check("…and the section shows with the audit off: the hide rule leaves a section that holds the calls card", "#audit-panel:has(#audit[hidden]):not(:has(#ghcalls)){display:none}" in ui_render._RUN_CSS)
    check("…the hour's calls are not in the Runners section any more, nor the line in the Audit section's text", "github calls this hour" not in _hh and "github calls" not in runners_section(_hh))
    check("…the GitHub calls card styles: the count in the text colour, the cap muted, 8px under the audit card, the name row a flex row", "#panel .ghc{margin-top:8px;font-size:12px}#panel .ghc .val{color:var(--fg)}#panel .ghc .val .cap{color:var(--mut)}" in ui_render._RUN_CSS
          and "#panel :is(.audit,.ghc)>.mh{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center" in ui_render._RUN_CSS)
    _led.write_text("{not json", encoding="utf-8")
    check("…a torn ledger reads as an empty hour: 0 / cap, no error", '<span class="val">0 <span class="cap">/ ' + f"{_gbm.write_cap():,}" in audit_section(board_html()))
    _led.unlink()
    check("…before the ledger exists the card is not drawn and reading it makes no file", 'id="ghcalls"' not in audit_section(board_html()) and not _led.exists())
    check("…without a ledger and with the audit off nothing is left in the Audit section but its hidden card (the section hides itself)", 'id="audit"' in audit_section(board_html()) and " hidden>" in audit_section(board_html()))
finally:
    if _led_save is None: _led.unlink(missing_ok=True)
    else: _led.write_bytes(_led_save)

# 9f. peek(): no snapshot → None and one background build; many peeks → no second; never blocks
GATE2 = threading.Event(); STARTED2 = threading.Event(); LISTS_SEEN = []
def stalled_get(path, timeout=8):
    if "/actions/" not in path: return fake_get(path, timeout)      # the owner lookup answers; the runner list is what stalls
    if "/actions/runners?" in path: LISTS_SEEN.append(path); STARTED2.set()
    GATE2.wait(30)                                           # a GitHub that does not answer until the test lets it
    return fake_get(path, timeout)
def wait_for(cond, secs=10):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond(): return True
        time.sleep(0.02)
    return False
def peek_thread_done(): th = R._PEEK["thread"]; return th is None or not th.is_alive()
fresh(); R.AUTOSTART = False
check("peek, autostart off: None, no thread, no GitHub call (what a test or an import sees)", R.peek() is None and R._PEEK["thread"] is None and CALLS == [], CALLS)
fresh(); R.AUTOSTART = True; R._get = stalled_get; GATE2.clear(); STARTED2.clear(); LISTS_SEEN.clear()
try:
    t0 = time.monotonic(); first = R.peek(); took = time.monotonic() - t0
    check("peek, no snapshot: returns None at once and starts one background build", first is None and took < 1 and STARTED2.wait(5) and R._PEEK["thread"] is not None, (first, took))
    t0 = time.monotonic(); res = []
    ths = [threading.Thread(target=lambda: res.append(R.peek()), daemon=True) for _ in range(40)]
    for t in ths: t.start()
    for t in ths: t.join(5)
    for _ in range(300): R.peek()
    took = time.monotonic() - t0
    check("peek, build stalled in GitHub: 340 more peeks (40 of them at once) all return None at once and start no second build", res == [None] * 40 and took < 2 and len(LISTS_SEEN) == 1, (len(res), took, len(LISTS_SEEN)))
    t0 = time.monotonic(); hs = board_html(); took = time.monotonic() - t0
    check("…and the board renders meanwhile with 'not read yet' (a stalled GitHub never holds a render)", took < 5 and "not read yet" in runners_section(hs) and len(LISTS_SEEN) == 1, (took, len(LISTS_SEEN)))
    GATE2.set()
    check("…when GitHub answers, the one build ends and its snapshot is cached", wait_for(lambda: "snap" in R._CACHE and peek_thread_done()) and R.peek() is not None and len(LISTS_SEEN) == 2, (len(LISTS_SEEN), list(R._CACHE)))
    n = len(CALLS); [R.peek() for _ in range(200)]
    check("peek, fresh snapshot: the same snapshot every time, no new call, no thread", len(CALLS) == n and R.peek() is R._CACHE["snap"] and peek_thread_done())
    CLOCK[0] = T0 + 60; n = len(LISTS_SEEN); [R.peek() for _ in range(50)]
    check("peek, snapshot 60 s old (past cache_s 25, under panel_refresh_s 120): the old snapshot, no rebuild, no thread", R.peek() is R._CACHE["snap"] and R._CACHE["snap"]["ts"] == T0 and peek_thread_done() and len(LISTS_SEEN) == n and R.conf("panel_refresh_s") == 120 and R.conf("cache_s") == 25, (len(LISTS_SEEN), n))
    CLOCK[0] = T0 + 130; GATE2.clear(); STARTED2.clear(); n = len(LISTS_SEEN)
    t0 = time.monotonic(); old = R.peek(); took = time.monotonic() - t0
    check("peek, snapshot 130 s old (past panel_refresh_s): the old snapshot comes back at once and one rebuild starts", old is R._CACHE["snap"] and old["ts"] == T0 and took < 1 and STARTED2.wait(5), (took,))
    [R.peek() for _ in range(200)]
    check("…200 more peeks while it runs start no second build", len(LISTS_SEEN) == n + 1, (len(LISTS_SEEN), n))
    GATE2.set()
    check("…it ends, and the snapshot is the new one (two lists per build: one per repo)", wait_for(lambda: R._CACHE["snap"]["ts"] == T0 + 130 and peek_thread_done()) and len(LISTS_SEEN) == n + 2, (R._CACHE["snap"]["ts"], len(LISTS_SEEN)))
    R.reset(); CALLS.clear(); R._CACHE["building"] = {"ev": threading.Event(), "since": time.monotonic()}      # the /runners page's own build in flight
    check("peek while another build is in flight: starts none of its own", R.peek() is None and R._PEEK["thread"] is None and CALLS == [], CALLS)
finally:
    GATE2.set(); th = R._PEEK["thread"]
    if th is not None: th.join(10)
    R.AUTOSTART = False; R._get = fake_get; fresh()
# 9g. a rebuild peek started that changes the counts asks for a republish: once per panel_refresh_s, never on equal counts, a failing hook breaks nothing
PUBS = []
SAVE = {k: [dict(x) for x in v] for k, v in RUNNERS.items()}
fresh(); R.AUTOSTART = True; R.ON_CHANGE = lambda: PUBS.append(CLOCK[0]) or True
try:
    R.peek()
    check("republish: the first read (no snapshot before) asks for one publish", wait_for(lambda: "snap" in R._CACHE and peek_thread_done()) and len(PUBS) == 1, PUBS)
    CLOCK[0] = T0 + 130; R.peek(); wait_for(lambda: R._CACHE["snap"]["ts"] == T0 + 130 and peek_thread_done())
    check("republish: a rebuild with the same counts asks for none", len(PUBS) == 1, PUBS)
    RUNNERS["salamander"][0]["busy"] = True; CLOCK[0] = T0 + 260; R.peek(); wait_for(lambda: R._CACHE["snap"]["ts"] == T0 + 260 and peek_thread_done())
    check("republish: a rebuild with other counts (box-a salamander 1/3 -> 2/3) asks for one", len(PUBS) == 2 and PUBS[-1] == T0 + 260, PUBS)
    RUNNERS["salamander"][0]["busy"] = False; CLOCK[0] = T0 + 290; R._peek_run(R._CACHE["snap"])
    check("republish: other counts again 30 s later (inside panel_refresh_s) are throttled: no second publish", R._CACHE["snap"]["ts"] == T0 + 290 and len(PUBS) == 2, (PUBS, R._CACHE["snap"]["ts"]))
    RUNNERS["salamander"][0]["busy"] = True; CLOCK[0] = T0 + 400; R._peek_run(R._CACHE["snap"])
    check("republish: …and past panel_refresh_s since the last request it is asked again", len(PUBS) == 3 and PUBS[-1] == T0 + 400, PUBS)
    def boom(): raise RuntimeError("publish broke")
    R.ON_CHANGE = boom; RUNNERS["salamander"][0]["busy"] = False; CLOCK[0] = T0 + 600
    try: R._peek_run(R._CACHE["snap"]); raised = False
    except Exception: raised = True
    check("republish: a hook that raises breaks neither the rebuild nor the thread's cleanup", not raised and R._CACHE["snap"]["ts"] == T0 + 600 and R._PEEK["thread"] is None)
    R.ON_CHANGE = None; RUNNERS["salamander"][0]["busy"] = True; CLOCK[0] = T0 + 800
    try: R._peek_run(R._CACHE["snap"]); raised = False
    except Exception: raised = True
    check("republish: with no hook set (a test, an import) nothing is asked and nothing breaks", not raised and R._CACHE["snap"]["ts"] == T0 + 800)
    # the server wires it to the debounced publish, in __main__ only
    check("republish: server.py sets ON_CHANGE to its wrapper of the debounced publish in __main__ only", re.search(r"(?m)^    _runners\.ON_CHANGE = _publish_if_idle\b", pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8")) is not None and R.ON_CHANGE is None)
finally:
    R.ON_CHANGE = None; R.AUTOSTART = False; th = R._PEEK["thread"]
    if th is not None: th.join(10)
    RUNNERS.update(SAVE); fresh()

# 9g2. a hook that turns the request down (False: a publish is still running) is asked again every RETRY_S for up to RETRY_MAX_S, one chain at a time; the throttle slot is taken only on True
EMPTY = {"ts": T0, "errors": {}, "failed": [], "runners": [], "stale": False}
real_retry = (R.RETRY_S, R.RETRY_MAX_S)
def chain_done(): return R._PEEK["retry"] is None
try:
    fresh(); calls = []; answers = [False, False, True]
    R.RETRY_S, R.RETRY_MAX_S = 0.03, 5.0; R.ON_CHANGE = lambda: (calls.append(1), answers[min(len(calls) - 1, 2)])[1]
    R._notify(None, EMPTY)
    check("retry: a hook that answers False twice, then True, is called three times and takes the slot once", wait_for(lambda: len(calls) == 3 and chain_done()) and R._PEEK["pub"] is not None, (len(calls), R._PEEK))
    R._notify(None, EMPTY); time.sleep(0.15)
    check("…the slot is then held: another notify inside panel_refresh_s asks nothing and starts no chain", len(calls) == 3 and chain_done(), len(calls))
    fresh(); calls = []
    R.RETRY_S, R.RETRY_MAX_S = 0.05, 0.3; R.ON_CHANGE = lambda: (calls.append(1), False)[1]
    R._notify(None, EMPTY)
    check("retry: a hook that always answers False stops after the limit (about RETRY_MAX_S / RETRY_S + 1 tries) and gives up quietly", wait_for(chain_done) and 2 <= len(calls) <= 8 and R._PEEK["pub"] is None, (len(calls), R._PEEK))
    n = len(calls); time.sleep(0.3)
    check("…it asks no more after giving up, and takes no slot, so a later change starts a fresh chain", len(calls) == n and (R._notify(None, EMPTY), wait_for(lambda: len(calls) > n and chain_done()))[1], (n, len(calls)))
    fresh(); calls = []
    R.RETRY_S, R.RETRY_MAX_S = 0.1, 0.5; R.ON_CHANGE = lambda: (calls.append(1), False)[1]
    R._notify(None, EMPTY); R._notify(None, EMPTY); R._notify(None, EMPTY)
    check("retry: two more notifies while a chain is waiting start no second chain (one try so far)", len(calls) == 1 and R._PEEK["retry"] is not None, (len(calls), R._PEEK["retry"]))
    check("…and the one chain stays within the limit (a second chain would double the tries)", wait_for(chain_done) and len(calls) <= 6, len(calls))
    fresh(); calls = []; R.RETRY_S, R.RETRY_MAX_S = 5.0, 60.0; R.ON_CHANGE = lambda: (calls.append(1), False)[1]
    R._notify(None, EMPTY); tm = R._PEEK["retry"]; R.reset()
    check("reset() cancels a waiting retry and clears the chain", len(calls) == 1 and R._PEEK["retry"] is None and not tm.is_alive() or (tm.join(1), not tm.is_alive())[1])
finally:
    R.RETRY_S, R.RETRY_MAX_S = real_retry; R.ON_CHANGE = None; fresh()
# the server's wrapper: False while the debounce timer's publish is alive (it stays alive through the whole publish), else it schedules one and says True
published = []; real_pub, real_timer = server._publish, server._PUB_TIMER
server._publish = lambda: published.append(1)
live = threading.Timer(60, lambda: None); live.daemon = True; live.start()
try:
    server._PUB_TIMER = live; a = server._publish_if_idle()
    check("server._publish_if_idle: False and no publish asked while the debounce timer's publish is alive", a is False and published == [], (a, published))
    live.cancel(); live.join(5); server._PUB_TIMER = live; b = server._publish_if_idle()
    check("…True and one publish asked once that timer is dead", b is True and published == [1], (b, published))
    server._PUB_TIMER = None; c2 = server._publish_if_idle()
    check("…and True with no timer at all", c2 is True and published == [1, 1], published)
finally:
    live.cancel(); server._publish, server._PUB_TIMER = real_pub, real_timer

# 9h. [runners] panel = false stops the background read; a thread that cannot start never breaks a render; no test-started server reaches GitHub
import types
fresh(); R.AUTOSTART = True; R._cfg.CFG["runners"]["panel"] = False
try:
    r0 = R.peek(); hh = board_html()
    check("panel = false: peek() starts nothing and the board renders 'not read yet' (the key stops the read even with AUTOSTART on)", r0 is None and R._PEEK["thread"] is None and CALLS == [] and "not read yet" in runners_section(hh), CALLS)
finally:
    R._cfg.CFG["runners"]["panel"] = True; R.AUTOSTART = False
class NoThread(threading.Thread):
    def start(self): raise RuntimeError("can't start new thread")
fresh(); R.AUTOSTART = True; real_threading = R.threading
R.threading = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading) if not k.startswith("__")}); R.threading.Thread = NoThread
try:
    r0 = R.peek(); hh = board_html()
    check("a thread that cannot be started: peek() still returns, no thread is left marked, the board renders", r0 is None and R._PEEK["thread"] is None and "not read yet" in runners_section(hh))
finally:
    R.threading = real_threading; R.AUTOSTART = False; fresh()
starters = sorted(p.name for p in pathlib.Path(SCR).glob("*.py") if re.search(r"Popen\(\[[^\]]*server\.py", p.read_text(encoding="utf-8")))
check("every suite that starts server.py is known (neutral_install, reload, sala_absent) and sets [runners] panel = false in the config it starts it with",
      starters == ["neutral_install_scenario.py", "reload_scenario.py", "sala_absent_scenario.py"] and all('(r"(?m)^panel = true", "panel = false")' in pathlib.Path(SCR, n).read_text(encoding="utf-8") for n in starters), starters)
check("…and the example config's default is true, so the key is what stops it", re.search(r"(?m)^panel = true", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None and R.DEFAULTS["panel"] is True)

# 9i. 'unknown' means the runner LIST read failed (snapshot["failed"]); a failed jobs read keeps the runners and is not unknown
def runs_broken_get(path, timeout=8):
    if "/actions/runs?" in path: raise RunnersError("GitHub answered 502 for /repos/example-owner/salamander/actions/runs")
    return fake_get(path, timeout)
fresh(); R._get = runs_broken_get; snap = aged(); R._get = fake_get; R.reset(); R._CACHE["snap"] = snap
sec = runners_section(board_html()); cl = card_lines(sec)
check("a failed jobs read is an error but not a failed list: failed is empty, the counts stay, no 'unknown' line", snap["errors"] and snap["failed"] == [] and "unknown" not in words(sec)
      and cl["box-a"] == ["2/4"], (snap["errors"], snap["failed"], cl))
snap = seeded(("stackshot",))
check("a failed list read is in failed, and only that repo reads unknown", snap["failed"] == ["stackshot"] and card_lines(runners_section(board_html()))["box-c"] == ["unknown"], snap["failed"])
check("a snapshot of nothing read marks every repo failed", R._unread("x")["failed"] == ["salamander", "stackshot"] and snap is not None)
sec = runners_section(board_html())
check("'unknown' and 'offline' are drawn muted like an idle count (class idle), a counted machine has its own class", '<span class="rv idle">unknown</span>' in sec and '<span class="rv busy">' in sec and ".mr.unknown{" in ui_render._RUN_CSS, sec[:600])

# 9j. [runners.ids] (name = repository ID): a repo with an ID is read at /repositories/<id>/actions/..., one without at /repos/<owner>/<repo>/actions/...; the page's links
# take owner/name from the run's own repository.full_name (no extra call), else [runners] owner
ID_S, ID_T = 9000023, 9000024
def id_get(path, timeout=8):
    asked = path                                      # what runners.py asked for is what CALLS keeps; the fake answers as the same repo by name
    if re.fullmatch(r"/repositories/\d+|/repos/example-owner/\w+", path): return fake_get(path, timeout)       # an owner lookup
    m = re.match(r"/repositories/(\d+)/", path)
    if m:
        name = {str(ID_S): "salamander", str(ID_T): "stackshot"}[m.group(1)]
        path = path.replace(f"/repositories/{m.group(1)}/", f"/repos/example-owner/{name}/", 1)
    try: return fake_get(path, timeout)
    finally: CALLS[-1] = asked
import copy
runs_save = copy.deepcopy(RUNS)
RUNS["salamander"][0]["repository"] = {"full_name": "neworg/salamander"}                                  # the repo moved to another owner; GitHub's run says so
R._cfg.CFG["runners"]["ids"] = {"salamander": ID_S}
fresh(); R._get = id_get; snap = R.snapshot(); R._get = fake_get
check("[runners.ids] with an ID for one repo: its runner, run and job calls use /repositories/<id>/actions/…",
      sum(p.startswith(f"/repositories/{ID_S}/actions/runners?") for p in CALLS) == 1
      and f"/repositories/{ID_S}/actions/runs?status=in_progress&per_page=30" in CALLS and f"/repositories/{ID_S}/actions/runs/11/jobs?filter=latest&per_page=100" in CALLS, CALLS)
check("…and the repo with no ID is read at /repos/<owner>/<repo>/actions/… as before, with no /repositories call for it",
      "/repos/example-owner/stackshot/actions/runners?per_page=100&page=1" in CALLS and not any(p.startswith("/repos/example-owner/salamander") for p in CALLS)
      and not any(p.startswith("/repositories/") and not p.startswith(f"/repositories/{ID_S}/") for p in CALLS), CALLS)
check("the snapshot is the same as by name (10 runners, the PR job found), the ID is not shown in it", len(snap["runners"]) == 10 and by(snap)["box-a-salamander-2"]["job"]["pr"] == 17
      and str(ID_S) not in json.dumps(R2.data(snap, T0)["runners"]), snap["errors"])
html = R2.table_html(snap, T0)
check("a link to GitHub takes owner/name from the run's own full_name (neworg/salamander) with no extra call", '<a href="https://github.com/neworg/salamander/pull/17"' in row(html, "box-a"), row(html, "box-a"))
check("…and a run with no repository object falls back to [runners] owner (example-owner/stackshot)", 'href="https://github.com/example-owner/stackshot/actions/runs/21"' in row(html, "box-a"), row(html, "box-a"))
RUNS["salamander"][0]["repository"] = {"full_name": '"><script>x'}
fresh(); R._get = id_get; html = R2.table_html(R.snapshot(), T0); R._get = fake_get
check("a full_name that is not owner/name is ignored (owner + name instead), nothing unescaped reaches the page", "<script>x" not in html and 'github.com/example-owner/salamander/pull/17' in html, row(html, "box-a"))
RUNS.clear(); RUNS.update(runs_save)
R._cfg.CFG["runners"]["ids"] = {"salamander": str(ID_S), "stackshot": ID_T}
fresh(); R._get = id_get; snap = R.snapshot(); R._get = fake_get
check("an ID as a digit string works, and every repo with an ID uses the /repositories path", len(snap["runners"]) == 10 and not any(p.startswith("/repos/") for p in CALLS)
      and f"/repositories/{ID_T}/actions/runners?per_page=100&page=1" in CALLS, CALLS)
R._cfg.CFG["runners"]["ids"] = {"salamander": "abc", "stackshot": 0, "x": True}
check("a bad entry (not digits, zero, a bool) is ignored: that repo is found by name", R._ids() == {} and R._api("salamander") == "/repos/example-owner/salamander", R._ids())
R._cfg.CFG["runners"].pop("ids", None)
fresh(); snap = R.snapshot()
check("no [runners.ids] at all: every call is /repos/<owner>/<repo>/actions/…, behaviour unchanged", CALLS and all(p.startswith("/repos/example-owner/") for p in CALLS) and len(snap["runners"]) == 10, CALLS)
check("the example config documents [runners.ids] (empty) and carries no ID", "[runners.ids]" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
      and R._ids() == {} and not re.search(r"\b(9000023|9000024)\b", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")))

check("the example config documents [runners.labels] (empty), and the server turns AUTOSTART on only in __main__",
      "[runners.labels]" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8") and R.AUTOSTART is False
      and re.search(r"(?m)^    _runners\.AUTOSTART = True", pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8")) is not None)

# ---- 10. the runners are found from the repo: the repo's owner is read from GitHub, an organization's shared runners are listed too, a runner's machine comes from its labels
# A fake GitHub that answers the owner lookup, the repo-level and the org-level lists (paginated), and the runs and jobs of fake_get above.
W = {"owners": {}, "org": {}, "repo": {}}      # repo name → owner dict | Exception; org login → runners | Exception; repo name → runners
WCALLS = []
def page_of(path, rs):
    m = re.search(r"&page=(\d+)", path); n = int(m.group(1)); return {"total_count": len(rs), "runners": rs[(n - 1) * 100:n * 100]}
def world_get(path, timeout=8):
    m = re.fullmatch(r"/repos/example-owner/(\w+)", path)
    if m:
        WCALLS.append(path); o = W["owners"].get(m.group(1), {"login": "example-owner", "type": "User"})
        if isinstance(o, Exception): raise o
        return {"owner": dict(o)}
    m = re.fullmatch(r"/orgs/([\w-]+)/actions/runners\?per_page=100&page=\d+", path)
    if m:
        WCALLS.append(path); v = W["org"].get(m.group(1), [])
        if isinstance(v, Exception): raise v
        return page_of(path, v)
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runners\?per_page=100&page=\d+", path)
    if m:
        WCALLS.append(path); return page_of(path, W["repo"].get(m.group(1), []))
    return fake_get(path, timeout)
ORG = {"login": "example-org", "type": "Organization"}
def orn(i, name, machine, online=True, busy=False, labels=None):
    return {"id": 9000 + i, "name": name, "status": "online" if online else "offline", "busy": busy,
            "labels": [{"name": x} for x in (labels if labels is not None else ("self-hosted", "Linux", "X64", "pool", "heavy", "light", machine))]}
FLEET = [orn(1, "box-a-1", "box-a"), orn(2, "box-a-light-1", "box-a", labels=("self-hosted", "Linux", "X64", "pool", "light", "box-a")),
         orn(3, "box-b-1", "box-b"), orn(4, "box-b-2", "box-b", busy=True), orn(5, "box-b-light-1", "box-b", labels=("self-hosted", "Linux", "X64", "pool", "light", "box-b")),
         orn(6, "box-c-1", "box-c"), orn(7, "box-c-2", "box-c", online=False), orn(8, "box-c-light-1", "box-c", labels=("self-hosted", "Linux", "X64", "pool", "light", "box-c"))]
def world(owners=None, org=None, repo=None):
    W["owners"], W["org"], W["repo"] = owners or {}, org or {}, repo or {}
    fresh(); WCALLS.clear(); R._get = world_get
def rows_of2(html): return {m.group(1): m.group(2) for m in re.finditer(r'<tr class="[^"]*"><th scope="row"><div class="mname">([^<]+)</div>(.*?)</tr>', html, re.S)}
SSH_OUT.update({"box-b": wsl("on"), "box-c": wsl("on")})

# 10a. an organization owns both repos and every runner is an org runner: the repo-level lists are empty, the page lists the org's runners
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET})
R._CACHE["snap"] = {"ts": T0 - 100, "errors": {}, "failed": [], "switch": {}, "stale": False, "runners": [{"name": "box-c-2", "repo": "example-org/*", "state": "offline", "off_since": T0 - 600}]}      # the offline org runner was first seen offline 10 minutes ago
snap = R.snapshot(); x = by(snap); html = R2.table_html(snap, T0)
check("org-owned repos, org runners only: every runner of the org's list is on the page, no error", len(snap["runners"]) == 8 and snap["errors"] == {} and snap["failed"] == [], (len(snap["runners"]), snap["errors"]))
check("…the owner of each repo was read once (GET /repos/…), and the org's list once for the two repos", sorted(p for p in WCALLS if "/actions/" not in p) == ["/repos/example-owner/salamander", "/repos/example-owner/stackshot"]
      and sum(p.startswith("/orgs/example-org/actions/runners?") for p in WCALLS) == 1, WCALLS)
check("…the repo-level lists were read as well (empty here)", sum(p.startswith("/repos/example-owner/") and "/actions/runners?" in p for p in WCALLS) == 2, WCALLS)
check("…one column for the org's shared runners and none for the two repos, which have no runners of their own", heads(snap) == ["example-org (shared)"], heads(snap))
check("…a row per machine in order, from the labels (box-a, box-b, box-c), each runner on its machine",
      list(rows_of2(html)) == ["box-a", "box-b", "box-c"] and {n: v["box"] for n, v in x.items()} == {"box-a-1": "box-a", "box-a-light-1": "box-a", "box-b-1": "box-b", "box-b-2": "box-b",
      "box-b-light-1": "box-b", "box-c-1": "box-c", "box-c-2": "box-c", "box-c-light-1": "box-c"}, {n: v["box"] for n, v in x.items()})
check("…idle, running and offline as before", x["box-a-1"]["state"] == "idle" and x["box-b-2"]["state"] == "running" and x["box-c-2"]["state"] == "offline", [(n, v["state"]) for n, v in x.items()])
check("…the runner is in the org column (repo 'example-org/*') and the page counts all eight", x["box-b-1"]["repo"] == "example-org/*" and [tcard(html, w) for w in ("Runners", "Running", "Idle", "Disabled", "Offline")] == [8, 1, 6, 0, 1], html[:700])
check("…an offline org runner on a WSL box with its switch on is a fault, as for a repo's runner", x["box-c-2"]["kind"] == "fault", x["box-c-2"])
check("…the busy org runner's job was looked for in the runs of the repos and, none holding it, reads 'job not found' without a repo name", "job not found" in html and ", job not found" not in html, html[:600])
check("…the JSON carries the same runners", len(R2.data(snap, T0)["runners"]) == 8 and "box-a-1</b>" in R2.data(snap, T0)["html"])
cl = card_lines((lambda s: (R.reset(), R._CACHE.__setitem__("snap", s))[0] or runners_section(board_html()))(snap))
check("…the side panel: a card per machine with the org's runners as its one count", cl == {"box-a": ["0/2"], "box-b": ["1/3"], "box-c": ["0/2"]}, cl)

# 10b. a busy org runner's job is found in whichever repo's runs hold it (salamander's runs first, then stackshot's)
JOBS_SAVE = {k: list(v) for k, v in JOBS.items()}
JOBS[22] = [{"id": 221, "status": "in_progress", "runner_name": "box-b-2", "started_at": iso(T0 - 70)}]
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET}); snap = R.snapshot(); x = by(snap); html = R2.table_html(snap, T0)
j = x["box-b-2"]["job"]
check("a busy org runner: its job is found in stackshot's runs (PR 7), the job's repo named, linked with the run's own repository when it says so",
      j["pr"] == 7 and j["repo"] == "stackshot" and j["started"] == T0 - 70 and "stackshot #7</a> · 1m" in html, j)
JOBS.update(JOBS_SAVE)

# 10c. both repos share the org's runners: no duplicates, and a runner both a repo list and the org list return shows once
dup = [dict(FLEET[0])]
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET}, repo={"salamander": dup, "stackshot": dup})
snap = R.snapshot()
check("the same runner in both repos' lists and in the org's list is one runner (same id and name)", len(snap["runners"]) == 8 and [x["name"] for x in snap["runners"]].count("box-a-1") == 1, [x["name"] for x in snap["runners"]])
check("…it stays in the repo's column, the first that read it, and the page then has that column besides the org's", by(snap)["box-a-1"]["repo"] == "salamander" and heads(snap) == ["example-org (shared)", "salamander"], heads(snap))
orgp = [r for r in FLEET] + [orn(100 + i, f"home-more-{i}", "home-more") for i in range(1, 121)]
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": orgp}); snap = R.snapshot()
check("an org with 128 runners: read in two pages of 100, all shown, a new machine (home-more) gets its own row after the known ones",
      len(snap["runners"]) == 128 and sum(p.startswith("/orgs/example-org/actions/runners?") for p in WCALLS) == 2
      and list(rows_of2(R2.table_html(snap, T0))) == ["box-a", "box-b", "box-c", "home-more"], (len(snap["runners"]), WCALLS))

# 10d. a user-owned repo: only its own runners, no org call
world(owners={"salamander": {"login": "example-owner", "type": "User"}, "stackshot": {"login": "example-owner", "type": "User"}},
      repo={"salamander": [orn(20, "box-a-salamander", "box-a"), orn(21, "box-b-salamander", "box-b", online=False)], "stackshot": [orn(22, "box-a-stackshot", "box-a")]},
      org={"example-owner": [orn(30, "should-not-show", "box-a")]})
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("user-owned repos: their own runners, a column per repo, and no /orgs call at all", sorted(by(snap)) == ["box-a-salamander", "box-a-stackshot", "box-b-salamander"]
      and heads(snap) == ["salamander", "stackshot"] and not any(p.startswith("/orgs/") for p in WCALLS) and snap["errors"] == {}, (sorted(by(snap)), heads(snap), WCALLS))
world(owners={"salamander": ORG, "stackshot": {"login": "example-owner", "type": "User"}}, org={"example-org": FLEET}, repo={"stackshot": [orn(23, "box-a-stackshot", "box-a")]})
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("one repo in an org and one user-owned: the org's runners, and the user-owned repo's own, side by side", len(snap["runners"]) == 9 and heads(snap) == ["example-org (shared)", "stackshot"], heads(snap))

# 10e. the org's runners cannot be read: what was read stays, one plain line names the missing permission
for code in (403, 404):
    world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": RunnersError(f"GitHub answered {code} for /orgs/example-org/actions/runners", code)}, repo={"stackshot": [orn(24, "box-a-stackshot", "box-a")]})
    snap = R.snapshot(); html = R2.table_html(snap, T0)
    check(f"org runners answered {code}: the repo's own runner is still shown", list(by(snap)) == ["box-a-stackshot"] and snap["failed"] == ["org:example-org"], (list(by(snap)), snap["failed"]))
    uh = __import__("html").unescape(html)                 # the page escapes its quotes
    check(f"…one plain line says the org's runners could not be read and which permission is missing (fine-grained and classic)", html.count('role="alert"') == 1
          and "example-org: the organization's shared runners could not be read" in uh and 'organization "Self-hosted runners: read"' in uh and "admin:org read" in uh, uh[:600])
    check("…no token and no URL in that line, and the org's column says unknown", "http" not in re.search(r'<p class="rerr".*?</p>', html).group(0) and "unknown (GitHub error)" in html, html[:700])
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": RunnersError("GitHub answered 502 for /orgs/example-org/actions/runners", 502)})
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("org runners answered 502: the line says it could not be read and why, and does not blame a permission", "could not be read (GitHub answered 502" in html and "Self-hosted runners" not in html, html[:500])
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": RunnersError("GitHub answered 403 for /orgs/example-org/actions/runners", 403)})
snap = R.snapshot(); R.reset(); R._CACHE["snap"] = snap; cl = card_lines(runners_section(board_html()))
check("the side panel reads 'unknown' for the org's runners it could not read, not 'no runners'", all(v == ["unknown"] for v in cl.values()) and len(cl) == 3, cl)

# 10f. a machine label nobody configured: a row of its own, no config key needed; the label rules
def box(name, *labels): return R._box_of({"name": name, "labels": [{"name": x} for x in labels]})
GH = ("self-hosted", "Linux", "X64")
check("machine from labels: GitHub's labels and the role tags are not machines (box-b-1 → box-b)", box("box-b-1", *GH, "pool", "heavy", "light", "box-b") == "box-b")
check("…a machine label nobody listed is the machine (home-new-1 → home-new), the name agreeing", box("home-new-1", *GH, "pool", "heavy", "home-new") == "home-new")
check("…the only label left is the machine even when the name says nothing of it (ci-7 labelled newbox)", box("ci-7", *GH, "newbox") == "newbox")
check("…several labels left: the one that is a known fleet machine", box("zzz-1", *GH, "extra", "box-c") == "box-c")
check("…several unknown labels left: the one the name starts with; else the name's prefix before -<n> or -light-<n>", box("home-x-light-3", *GH, "alpha", "home-x") == "home-x" and box("foo-light-3", *GH, "alpha", "beta") == "foo" and box("foo-12", *GH, "alpha", "beta") == "foo")
check("…macOS / Windows / ARM64 labels are GitHub's, not machines", box("mac-1", "self-hosted", "macOS", "ARM64", "mac") == "mac" and box("win-1", "self-hosted", "Windows", "X64", "win") == "win")
check("…a name that carries a known machine wins over a stale label for another (box-c-stackshot-2 labelled box-a)", box("box-c-stackshot-2", *GH, "box-a") == "box-c")
check("…no label and no known machine in the name: 'other'", box("mystery", *GH) == "other" and box("mystery") == "other")
check("…[runners] role_labels adds role tags of its own", (R._cfg.CFG["runners"].__setitem__("role_labels", ["gpu"]), box("zz-1", *GH, "gpu", "newbox"))[1] == "newbox" and R._cfg.CFG["runners"].pop("role_labels") == ["gpu"])
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET + [orn(40, "home-new-1", "home-new", labels=("self-hosted", "Linux", "X64", "pool", "heavy", "home-new")), orn(41, "weird-1", "x", labels=("self-hosted",))]})
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a runner whose machine label is new: its machine gets a row after the configured ones, 'other' last for the runner nothing places",
      list(rows_of2(html)) == ["box-a", "box-b", "box-c", "home-new", "other"] and by(snap)["home-new-1"]["box"] == "home-new" and by(snap)["weird-1"]["box"] == "other", list(rows_of2(html)))
check("…the panel gets the card too", list(card_lines((R.reset(), R._CACHE.__setitem__("snap", snap))[0] or runners_section(board_html()))) == ["box-a", "box-b", "box-c", "home-new", "other"])

# 10g. the owner is cached, and an owner change is picked up
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET})
R.snapshot(); n_lookup = lambda: sum("/actions/" not in p for p in WCALLS)
check("first build: one owner lookup per repo", n_lookup() == 2, WCALLS)
CLOCK[0] = T0 + 30; R.snapshot(); CLOCK[0] = T0 + 100; R.snapshot()
check("two more builds inside owner_cache_s: no new owner lookup", n_lookup() == 2, WCALLS)
orgs_read = lambda: sum(p.startswith("/orgs/") for p in WCALLS)
n_org = orgs_read()
W["owners"]["salamander"] = {"login": "example-owner", "type": "User"}                  # salamander moves from the org to a user
CLOCK[0] = T0 + 601; snap = R.snapshot()
check("past owner_cache_s the owners are read again (4 lookups), the move is followed, and the org is still read for stackshot", n_lookup() == 4 and orgs_read() == n_org + 1 and len(snap["runners"]) == 8, (n_lookup(), orgs_read(), n_org))
W["owners"]["salamander"] = RunnersError("GitHub answered 502 for /repos/example-owner/salamander", 502)
W["owners"]["stackshot"] = {"login": "example-owner", "type": "User"}                   # stackshot moves out of the org too
n_org = orgs_read(); CLOCK[0] = T0 + 1300; snap = R.snapshot(); html = R2.table_html(snap, T0 + 1300)
check("a re-read that fails keeps the older answer (salamander stays user-owned, no error line); stackshot's move is followed: the org is no longer read, a column per repo again",
      snap["errors"] == {} and orgs_read() == n_org and heads(snap) == ["salamander", "stackshot"] and snap["runners"] == [], (snap["errors"], orgs_read(), n_org, heads(snap)))
world(owners={"salamander": RunnersError("GitHub answered 502 for /repos/example-owner/salamander", 502), "stackshot": ORG}, org={"example-org": FLEET}, repo={"salamander": [orn(50, "box-a-salamander", "box-a")]})
snap = R.snapshot()
check("an owner that cannot be read and was never cached: the repo's own runners show, with a line that its organization's runners may be missing, and the other repo's org is read",
      "account that owns it could not be read" in snap["errors"].get("account:salamander", "") and "box-a-salamander" in by(snap) and "box-b-1" in by(snap) and snap["failed"] == [], snap["errors"])
world(owners={"salamander": {"login": "", "type": "Organization"}, "stackshot": {"login": "../x", "type": "Organization"}})
snap = R.snapshot()
check("an owner answer with no usable login (empty, or a path-like one) is an error, never put into a URL", not any(p.startswith("/orgs/") for p in WCALLS)
      and all("account that owns it could not be read" in snap["errors"].get("account:" + r, "") for r in ("salamander", "stackshot")), (WCALLS, snap["errors"]))

# 10g2. an error about a repo's owner or about the running jobs is a line, never a column or an unknown cell; only a failed list is
def jobs_a_get(path, timeout=8):
    if path.startswith("/repos/example-owner/salamander/actions/runs?"): raise RunnersError("GitHub answered 502 for /repos/example-owner/salamander/actions/runs", 502)
    return world_get(path, timeout)
world(owners={"salamander": ORG, "stackshot": ORG}, org={"example-org": FLEET}); R._get = jobs_a_get
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a busy org runner and a failed jobs read on salamander: the line is shown, the runners stay, and no salamander column or unknown cell appears",
      "jobs:salamander" in snap["errors"] and "salamander" not in snap["errors"] and snap["failed"] == [] and len(snap["runners"]) == 8 and heads(snap) == ["example-org (shared)"]
      and "unknown (GitHub error)" not in html and "the running jobs could not be read" in html, (snap["errors"], heads(snap)))
check("…the busy runner's job was not in stackshot's runs, so it reads 'job not found'", "job not found" in html)
world(owners={"salamander": RunnersError("GitHub answered 502 for /repos/example-owner/salamander", 502), "stackshot": ORG}, org={"example-org": FLEET})
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a failed owner read: its line is shown, with no salamander column and no unknown cell", "account:salamander" in snap["errors"] and heads(snap) == ["example-org (shared)"]
      and "unknown (GitHub error)" not in html and "account that owns it could not be read" in html, (snap["errors"], heads(snap)))
world(owners={"salamander": {"login": "example-owner", "type": "User"}, "stackshot": {"login": "example-owner", "type": "User"}}, org={"example-org": FLEET}, repo={"salamander": [orn(60, "box-a-salamander", "box-a")]})
W["repo"]["stackshot"] = []
R._get = lambda p, t=8: (_ for _ in ()).throw(RunnersError("GitHub answered 502 for " + p, 502)) if p.startswith("/repos/example-owner/stackshot/actions/runners") else world_get(p, t)
snap = R.snapshot(); html = R2.table_html(snap, T0)
check("a failed repo list still makes its column, with unknown cells (it is in failed)", snap["failed"] == ["stackshot"] and heads(snap) == ["salamander", "stackshot"] and "unknown (GitHub error)" in html, (snap["failed"], heads(snap)))

# 10g3. a failed owner read is kept 60 s, so a hanging GitHub does not spend each build's time on owner reads
world(owners={"salamander": RunnersError("GitHub answered 502 for /repos/example-owner/salamander", 502), "stackshot": ORG}, org={"example-org": FLEET})
lk = lambda: sum(p == "/repos/example-owner/salamander" for p in WCALLS)
R.snapshot(); a = lk()
CLOCK[0] = T0 + 30; R.snapshot(force=True)
check("a failed owner read with no older answer is not repeated within 60 s (one read of salamander's owner in two builds), and the line stays", a == 1 and lk() == 1 and "account:salamander" in R.snapshot()["errors"], (a, lk()))
CLOCK[0] = T0 + 61; R.snapshot(force=True)
check("…and is tried again after 60 s", lk() == 2, lk())
W["owners"]["salamander"] = ORG
CLOCK[0] = T0 + 125; snap = R.snapshot(force=True)
check("…when it answers again the line goes", lk() == 3 and "account:salamander" not in snap["errors"], (lk(), snap["errors"]))
CLOCK[0] = T0 + 125 + 601; W["owners"]["salamander"] = RunnersError("GitHub answered 502 for /repos/example-owner/salamander", 502)
R.snapshot(force=True); n = lk(); CLOCK[0] += 30; snap = R.snapshot(force=True)
check("an expired good answer whose re-read fails: the older answer is used, and the failed read is not repeated within 60 s either", lk() == n and snap["errors"] == {} and len(snap["runners"]) == 8, (lk(), n, snap["errors"]))
check("a 403 on the org's runners also names a rate limit or SSO as a cause", (lambda t: "or GitHub is limiting the token" in t and "rate limit or SSO" in t)(R._org_error("o", RunnersError("x", 403))))

# 10h. [runners.ids] keeps working: the owner is looked up at /repositories/<id>
R._cfg.CFG["runners"]["ids"] = {"salamander": 111, "stackshot": 222}
W["owners"], W["org"], W["repo"] = {}, {"example-org": FLEET}, {}
seen_ids = []
def ids_world(path, timeout=8):
    m = re.fullmatch(r"/repositories/(\d+)", path)
    if m: seen_ids.append(path); return {"owner": dict(ORG)}
    if re.match(r"/repositories/\d+/actions/runners\?", path): seen_ids.append(path); return {"total_count": 0, "runners": []}
    if re.match(r"/repositories/\d+/actions/runs", path): return {"workflow_runs": []}          # the busy runner: no run holds it
    return world_get(path, timeout)
fresh(); WCALLS.clear(); R._get = ids_world; snap = R.snapshot()
check("with [runners.ids]: owner lookup and the repo-level lists go by ID, the org's list by login, and the result is the same", sorted(seen_ids) == sorted(["/repositories/111", "/repositories/222",
      "/repositories/111/actions/runners?per_page=100&page=1", "/repositories/222/actions/runners?per_page=100&page=1"]) and len(snap["runners"]) == 8 and snap["errors"] == {}, (seen_ids, snap["errors"]))
R._cfg.CFG["runners"].pop("ids", None); R._get = fake_get; fresh()
check("the example config documents owner_cache_s and role_labels", all(k in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8") for k in ("owner_cache_s", "role_labels")))

# 11. the rows follow the Machines panel's order (fleet.machines_order), not the [runners] boxes order
from stackshot.fleet import fleet as _fl
for L, nm in (("a", "box-a"), ("b", "box-c"), ("d", "box-b"), ("e", "box-d"), ("x", "box-e")):
    (T / f"fleet/{L}").mkdir(exist_ok=True); (T / f"fleet/{L}/sessions.json").write_text("{}")
    (T / f"fleet/{L}/machine.json").write_text(json.dumps({"letter": L, "fleet": nm, "claude": "1.0.0"}))
MP = R._cfg.CFG.setdefault("machines_panel", {}); ssh_save = MP.get("ssh_hosts"); MP["ssh_hosts"] = ["box-d", "box-g"]      # box-d is a fleet machine AND still listed
boxes_save = list(R._cfg.CFG["runners"]["boxes"]); SAVE = {k: list(v) for k, v in RUNNERS.items()}
def page_rows(snap): return re.findall(r'<div class="mname">([\w-]+)</div>', R2.table_html(snap, T0))
try:
    check("the Machines order: the publisher, the fleet by letter, then the ssh hosts that are not fleet machines; box-d once",
          _fl.machines_order() == ["box-a", "box-c", "box-b", "box-d", "box-e", "box-g"], _fl.machines_order())
    check("the Machines order: a repeated or blank host is one name, a lone string is a list",
          _fl.machines_order({"a": "box-a"}, ["x", "x", "box-a"]) == ["box-a", "x"] and _fl.ssh_host_names() == ["box-d", "box-g"])
    MP["ssh_hosts"] = " box-d "
    check("…a host written as one string with spaces round it", _fl.ssh_host_names() == ["box-d"], _fl.ssh_host_names())
    MP["ssh_hosts"] = ["box-d", "box-g"]
    RUNNERS["stackshot"].append(rn("boxd-ci-1", "box-d")); RUNNERS["stackshot"].append(rn("zzz-ci-1", "zzz-box"))
    snap = seeded()
    check("Runners page: the rows follow the Machines order (box-c before box-b although [runners] boxes lists box-b first); a machine the panel lacks comes after",
          page_rows(snap) == ["box-a", "box-c", "box-b", "box-d", "zzz-box"], page_rows(snap))
    check("side panel: the Runners cards in the same order", list(card_lines(runners_section(board_html()))) == ["box-a", "box-c", "box-b", "box-d", "zzz-box"], list(card_lines(runners_section(board_html()))))
    check("counts(): the same order, the one source of both", [c["box"] for c in R.counts(snap)] == ["box-a", "box-c", "box-b", "box-d", "zzz-box"])
    R._cfg.CFG["runners"]["boxes"] = ["zzz-box", "box-b", "box-a"]
    snap = seeded()
    check("a [runners] boxes order does not beat the Machines order: zzz-box, listed first, still comes after the Machines' machines",
          page_rows(snap) == ["box-a", "box-c", "box-b", "box-d", "zzz-box"], page_rows(snap))
    RUNNERS["stackshot"].append(rn("other-ci", "x")); RUNNERS["stackshot"][-1]["labels"] = [{"name": "self-hosted"}]
    R._cfg.CFG["runners"]["boxes"] = ["zzz-box", "yyy-box"]
    snap = seeded()
    check("a machine in no Machines list keeps its old order ([runners] boxes) after the listed ones, with a row though it has no runner, and 'other' last",
          page_rows(snap) == ["box-a", "box-c", "box-b", "box-d", "zzz-box", "yyy-box", "other"], page_rows(snap))
finally:
    R._cfg.CFG["runners"]["boxes"] = boxes_save; RUNNERS.update(SAVE)
    if ssh_save is None: MP.pop("ssh_hosts", None)
    else: MP["ssh_hosts"] = ssh_save

# ---- 12. the Disable / Enable button: the cards, the machine states, the Linux status read, switch_box with a fake pool-mode (never the real one), the buttons on the page, the route's gates
import threading, time, stat
# 12a. the count cards and the states
check("the Offline card is red ('bad') above 0 and plain at 0",
      'rcard bad"><b>2</b><span>Offline' in R2._cards({"runners": 5, "running": 1, "idle": 2, "disabled": 0, "offline": 2}) and "bad" not in R2._cards({"runners": 3, "running": 1, "idle": 2, "disabled": 0, "offline": 0}))
setfiles(mode="off\n", hold="", gate="")
SSH_OUT.update({"box-b": wsl("on"), "box-c": wsl("on")})
fresh(); snap = R.snapshot(); html = R2.table_html(snap, T0); x = by(snap); t = R2.tally(snap)
check("a machine told to stop while a job runs: 'disabling', the busy runner still reads running, its other runners read disabled",
      "disabling" in row(html, "box-a") and x["box-a-salamander-2"]["state"] == "running" and x["box-a-salamander"].get("disabled") and not x["box-a-salamander-2"].get("disabled"), row(html, "box-a")[:500])
check("tally: running + idle + disabled + offline add up to the runners, and a disabled runner is not counted offline",
      t["running"] + t["idle"] + t["disabled"] + t["offline"] == t["runners"] == 10 and t["disabled"] >= 3, t)
SAVE12 = {k: list(v) for k, v in RUNNERS.items()}
for k in RUNNERS: RUNNERS[k] = [dict(r, busy=False) for r in RUNNERS[k]]
fresh(); snap = R.snapshot(); html = R2.table_html(snap, T0)
check("the same machine with no job running reads 'disabled'", re.search(r'<span class="offw">disabled</span>', row(html, "box-a")) is not None, row(html, "box-a")[:300])
RUNNERS.update(SAVE12); setfiles(mode="on\n", hold="", gate="")
fresh(); html = R2.table_html(aged(), T0)
check("a machine that is on reads 'on' with how many of its runners are busy", re.search(r'<span class="on">on</span> · 2 of 4 busy', row(html, "box-a")) is not None, row(html, "box-a")[:300])

# 12b. the status read of a Linux machine (box-d, box-g) and the fallback between the two ways of asking
RUNS_SEEN.clear()
FAKE_RUN[0] = 0; R.subprocess.run = fake_run
try:
    out = REAL_SSH("box-d", 12, "sh"); a, kw = RUNS_SEEN[-1]
finally:
    R.subprocess.run = REAL_RUN
check("the Linux ssh call: the same ssh options, the host after '--', and the read-only shell lines as the remote command (no powershell)",
      a[0] == "ssh" and "BatchMode=yes" in a and "ControlPath=none" in a and a[a.index("--") + 1] == "box-d" and a[-1] == R._sh_status() and "powershell" not in a[-1] and kw["timeout"] == 12, a)
check("…those lines write nothing", not re.search(r">|\brm\b|\btee\b|\bmv\b|\bsed -i", R._sh_status()), R._sh_status())
check("a Linux box's file states: 'missing (= on)' is on, 'missing (= off)' is off",
      R._parse_wsl("mode file: missing (= on)\nhold file: none\n")["mode"] == "on" and R._parse_wsl("mode file: missing (= off)\nhold file: none\n")["mode"] == "off")
SEQ = []
def flav_ssh(host, timeout, flavor="ps"):
    SEQ.append(flavor)
    if host == "box-c": raise RunnersError("ssh exit 255")
    if flavor == "ps": raise RunnersError("ssh exit 127" if host == "box-d" else "ssh exit 1")
    return "mode file: missing (= on)\nhold file: none\n"
R._ssh = flav_ssh
try:
    fresh(); SEQ.clear()
    r1 = R._read_remote("box-d", "box-d", 5); first = list(SEQ); SEQ.clear()
    r2 = R._read_remote("box-d", "box-d", 5)
    check("a machine that does not know powershell (exit 127) is asked again the Linux way, and the way that answered is asked first next time",
          first == ["ps", "sh"] and r1["mode"] == "on" and SEQ == ["sh"] and R._FLAVOR.get("box-d") == "sh" and r2["mode"] == "on", (first, SEQ, R._FLAVOR))
    SEQ.clear(); r3 = R._read_remote("box-g", "box-g", 5)
    check("…also when the first way answers 1", SEQ == ["ps", "sh"] and r3["mode"] == "on", SEQ)
    SEQ.clear()
    try: R._read_remote("box-c", "box-c", 5); err = ""
    except RunnersError as e: err = str(e)
    check("…but a machine that cannot be reached (exit 255) is not asked a second way", SEQ == ["ps"] and err == "ssh exit 255", (SEQ, err))
finally:
    R._ssh = fake_ssh; R.reset()

# 12c. switch_box against a fake pool-mode.sh in a scratch folder: the argv, the environment, the timeout, one at a time, the refusals before anything runs
FAKE_DIR = pathlib.Path(_scratch.mkdtemp(prefix="runners-fake-switch-"))
FAKE = FAKE_DIR / "pool-mode.sh"
FAKE.write_text('''#!/bin/bash
d="$(dirname "$0")"
echo "$# $1 $2" >> "$d/calls.log"
env | cut -d= -f1 | sort > "$d/env-names.$2"
pwd -P > "$d/cwd.$2"
case "$2" in
  box-b) echo "mode file: $1"; echo "pool-mode: $2 -> $1 (done)"; exit 0;;
  box-c) echo "mode file: $1"; echo "pool-mode: could not list the organization's runners (HTTP 403)" >&2; exit 1;;
  box-d) printf 'pool-mode: could not %s %s (\\033[31mssh refused\\033[0m)\\n' "$1" "$2" >&2; exit 1;;
  box-g) echo $$ > "$d/pid.$2"; sleep 30; exit 0;;
  box-a) echo started > "$d/started.$2"; for i in $(seq 1 200); do [ -f "$d/release" ] && break; sleep 0.1; done; echo "mode file: $1"; exit 0;;
esac
exit 2
''', encoding="utf-8")
FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
LOGF = FAKE_DIR / "calls.log"
def ncalls(): return len(LOGF.read_text().splitlines()) if LOGF.exists() else 0
FLEET5 = ["box-g", "box-a", "box-c", "box-b", "box-d"]
real_fleet_boxes, R.fleet_boxes = R.fleet_boxes, (lambda: list(FLEET5))
os.environ["B624_DECOY_SECRET"] = "not-a-real-secret"        # a variable of the server's own that the script must never see
CFGR = R._cfg.CFG["runners"]; was_script, was_to = CFGR.get("switch_script"), CFGR.get("switch_timeout_s")
SSH_OUT.update({"box-d": "mode file: on\nhold file: none\n", "box-g": "mode file: on\nhold file: none\n"})
try:
    CFGR["switch_script"] = ""
    check("no switch_script set: switch_enabled is false and a press is refused, nothing runs", not R.switch_enabled() and R.switch_box("box-b", "off") == (False, "The Disable and Enable buttons are not set up on this board ([runners] switch_script is empty)."))
    CFGR["switch_script"] = str(FAKE_DIR / "missing.sh")
    check("a switch_script that is not a file: refused with its own sentence", R.switch_box("box-b", "off") == (False, "The CI switch script ([runners] switch_script) was not found on this machine."))
    CFGR["switch_script"] = str(FAKE); CFGR["switch_timeout_s"] = 1
    n0 = ncalls()
    bad = [R.switch_box(b, "off") for b in ("box-b; rm -rf x", "../box-b", "box-b\nbox-a", "$(id)", "-o", "home-nope", "BOX-B", "", " box-b", "a" * 200)]
    check("a name that is not a fleet machine (shell text, a path, a flag, a newline, an unknown or empty name) is refused with one sentence and nothing runs",
          all(r == (False, "That is not a machine of the fleet.") for r in bad) and ncalls() == n0, bad)
    bad = [R.switch_box("box-b", a) for a in ("reboot", "ON", "Disable", "", "off;id", "status")]
    check("an action other than off or on is refused and nothing runs", all(r == (False, "The action must be off (Disable) or on (Enable).") for r in bad) and ncalls() == n0, bad)
    ok, text = R.switch_box("box-b", "off")
    check("Disable: the script gets exactly 'off <box>' (argv list, no shell string); the answer says a job already running finishes, then no new job",
          ok is True and text == "box-b is disabled: a job already running finishes, then it takes no new job." and LOGF.read_text().splitlines()[-1] == "2 off box-b", (ok, text, LOGF.read_text()))
    ok, text = R.switch_box("box-b", "on")
    check("Enable: 'on <box>', and the answer says it takes jobs again within about 30 s", ok is True and text == "box-b is enabled: it takes jobs again within about 30 s." and LOGF.read_text().splitlines()[-1] == "2 on box-b", (ok, text))
    names = set((FAKE_DIR / "env-names.box-b").read_text().split())
    check("the script runs with a minimal environment: none of the server's settings or a decoy secret in the server's own environment",
          names <= set(R._SWITCH_ENV) | {"PWD", "SHLVL", "_", "OLDPWD"} and "B624_DECOY_SECRET" not in names and not any(k.startswith("STACKSHOT") for k in names), sorted(names))
    check("…in the home folder", (FAKE_DIR / "cwd.box-b").read_text().strip() == os.path.realpath(os.path.expanduser("~")))
    ok, text = R.switch_box("box-c", "off")
    check("the mode file is the switch: exit 1 after 'mode file: off' (pool-mode.sh could not list the runners afterwards) still counts, with a note saying what failed",
          ok is True and text.startswith("box-c is disabled: a job already running finishes") and "could not list the organization's runners" in text and "HTTP 403" in text, text)
    ok, text = R.switch_box("box-d", "off")
    check("a failure says so, with the script's own 'pool-mode:' line and no control characters", ok is False and text.startswith("Disable box-d failed.") and "pool-mode: could not off box-d" in text and "ssh refused" in text and "\x1b" not in text, repr(text))
    t0_ = time.monotonic(); ok, text = R.switch_box("box-g", "on"); took = time.monotonic() - t0_
    pid = int((FAKE_DIR / "pid.box-g").read_text())
    try: os.kill(pid, 0); alive = True
    except ProcessLookupError: alive = False
    check("a script that hangs is stopped after the timeout (switch_timeout_s 1 is raised to the 5 s floor), and the answer says the machine may or may not have changed",
          ok is False and "longer than 5 s" in text and "may or may not have changed" in text and 4.5 < took < 12 and not alive, (ok, text, took, alive))
    check("…and the lock is released: the same machine can be asked again", R.switch_box("box-b", "off")[0] is True)
    # one at a time per machine
    (FAKE_DIR / "release").unlink(missing_ok=True); (FAKE_DIR / "started.box-a").unlink(missing_ok=True)
    CFGR["switch_timeout_s"] = 60
    first_res = []
    th = threading.Thread(target=lambda: first_res.append(R.switch_box("box-a", "off"))); th.start()
    for _ in range(100):
        if (FAKE_DIR / "started.box-a").exists(): break
        time.sleep(0.1)
    n_before = ncalls()
    second = R.switch_box("box-a", "on")
    other = R.switch_box("box-b", "off")
    (FAKE_DIR / "release").write_text("go"); th.join(20)
    check("a second press for a machine whose change is still running is refused ('already running') and runs nothing; another machine is not held up",
          second == (False, "A change for box-a is already running; wait for it to end.") and ncalls() == n_before + 1 and other[0] is True and first_res and first_res[0][0] is True, (second, other, first_res))
    fresh(); snap0 = R.snapshot(); R._SSH_CACHE["box-b"] = (R._now(), {"ok": True, "mode": "on", "held": [], "gate": None, "since": 0.0})
    R.switch_box("box-b", "off")
    check("after a press the machine's cached switch read is dropped", "box-b" not in R._SSH_CACHE)
    n = len(CALLS); R.snapshot()
    check("…and the next snapshot is built again", len(CALLS) > n, (n, len(CALLS)))

    # 12d. the buttons on the page: Disable when the switch is on, Enable when it is off, both when it could not be read; none without a token maker, a script or a fleet machine
    tk = lambda b: "tok-" + b
    SSH_OUT.update({"box-b": wsl("off"), "box-c": RunnersError("ssh exit 255")}); setfiles(mode="on\n", hold="", gate="")
    fresh(); snap = R.snapshot(); html = R2.table_html(snap, T0, tk)
    def forms(rw): return re.findall(r'<form class="mact" method="post" action="/runners/switch"><input type="hidden" name="box" value="([^"]+)"><input type="hidden" name="act" value="(\w+)"><input type="hidden" name="token" value="([^"]+)"><button type="submit" class="b">(\w+)</button></form>', rw)
    check("box-a (switch on): one button, Disable (act=off), with the form token for that machine", forms(row(html, "box-a")) == [("box-a", "off", "tok-box-a", "Disable")], row(html, "box-a")[:400])
    check("box-b (switch off): one button, Enable (act=on)", forms(row(html, "box-b")) == [("box-b", "on", "tok-box-b", "Enable")], row(html, "box-b")[:400])
    check("box-c (not reachable): both buttons, Disable and Enable", forms(row(html, "box-c")) == [("box-c", "off", "tok-box-c", "Disable"), ("box-c", "on", "tok-box-c", "Enable")], row(html, "box-c")[:400])
    check("no token maker: no button (a read-only copy, a page for nobody)", "mact" not in R2.table_html(snap, T0) and "mact" not in R2.table_html(snap, T0, None))
    CFGR["switch_script"] = ""
    check("no switch_script: no button even with a token maker", "mact" not in R2.table_html(snap, T0, tk))
    CFGR["switch_script"] = str(FAKE); R.fleet_boxes = lambda: ["box-a", "box-c"]
    hosts_was = CFGR.get("ssh_hosts"); CFGR["ssh_hosts"] = {}
    check("a machine that is neither in the fleet's names nor named in [runners.ssh_hosts] gets no button (box-b here)", forms(row(R2.table_html(snap, T0, tk), "box-b")) == [] and len(forms(R2.table_html(snap, T0, tk))) == 3)
    # the board item, box-g: a machine outside the fleet's names that [runners] boxes lists and [runners.ssh_hosts] names gets its switch read and its button; the fleet's names are not needed for it
    CFGR["ssh_hosts"] = {"box-b": "box-b"}
    check("a [runners] boxes entry named in [runners.ssh_hosts] but outside the fleet's names is a button machine (box-b here)", R.switch_boxes() == ["box-a", "box-b", "box-c"], R.switch_boxes())
    fresh(); snap_h = R.snapshot(); html_h = R2.table_html(snap_h, T0, tk)
    check("…its switch is read over ssh through the named host", "box-b" in SSH, SSH)
    check("…and it gets its button (Enable: the switch it answered is off) with the viewer's token; the fleet's two machines keep theirs",
          forms(row(html_h, "box-b")) == [("box-b", "on", "tok-box-b", "Enable")] and [f[0] for f in forms(html_h)] == ["box-a", "box-c", "box-c", "box-b"], [f[0] for f in forms(html_h)])
    CFGR["ssh_hosts"] = {"box-b": "box-b", "zzz-box": "zzz-box"}
    check("a name in [runners.ssh_hosts] that [runners] boxes does not list is no button machine", "zzz-box" not in R.switch_boxes() and R.switch_box("zzz-box", "off") == (False, "That is not a machine of the fleet."), R.switch_boxes())
    CFGR["ssh_hosts"] = {"box-b": "", "box-c": "box-c"}
    check("an [runners.ssh_hosts] entry with an empty host names no host: no button machine", R.switch_boxes() == ["box-a", "box-c"], R.switch_boxes())
    CFGR["ssh_hosts"] = {"box-b": "box-b"}; n0 = ncalls()
    ok, text = R.switch_box("box-b", "off")
    check("switch_box accepts it: pool-mode.sh gets 'off box-b' (argv list)", ok is True and LOGF.read_text().splitlines()[-1] == "2 off box-b" and ncalls() == n0 + 1, (ok, text))
    n0 = ncalls()
    bad = [R.switch_box(b, "off") for b in ("box-g", "box-d", "home-nope", "", "box-b;id", "-o")]
    check("a box in neither the fleet's names nor [runners.ssh_hosts] (box-g and box-d here, not named) or an unknown name is refused and nothing runs",
          all(r == (False, "That is not a machine of the fleet.") for r in bad) and ncalls() == n0, bad)
    if hosts_was is None: CFGR.pop("ssh_hosts", None)
    else: CFGR["ssh_hosts"] = hosts_was
    R.fleet_boxes = lambda: list(FLEET5)
    page = R2.page_html(ui_render.Board(str(T / "store")), snap, tk)
    check("wording: never 'switched off', 'Turn off' or 'Turn on' (page, script or styles); the buttons say Disable and Enable",
          not any(w.lower() in (page + R2._JS).lower() for w in ("switched off", "turn off", "turn on", "turned off")) and ">Disable<" in page and ">Enable<" in page)
    check("the page: title and heading 'CI runners', the five count cards, a result line, no 'GitHub calls' line",
          "<title>CI runners" in page and "<h1>CI runners</h1>" in page and all(tcard(page, w) is not None for w in ("Runners", "Running", "Idle", "Disabled", "Offline")) and 'id="rn-result"' in page and "github calls" not in page.split("<h1>CI runners</h1>", 1)[1].split('id="rn-body"', 1)[0].lower(),
          (re.findall(r"<title>[^<]*", page), '<main id="top">' in page))   # the side panel (outside <main>) keeps its own GitHub calls card

    # 12e. the route: POST only, signed in, the board's own origin, the form's token, read-only refusal, validated machine
    EMAIL = "oliver@example.org"; BOARD12 = server.BOARD_URL
    COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
    SAME = {"Origin": BOARD12}; JSONH = {"Origin": BOARD12, "Accept": "application/json"}
    allowed_was = server._cfg.CFG["auth"].get("allowed_emails"); ui_open_was = server._cfg.CFG["auth"].get("ui_open"); real_mode = server._signin._auth_mode
    server._cfg.CFG["auth"]["allowed_emails"] = [EMAIL]; server._cfg.CFG["auth"]["ui_open"] = False; server._signin._auth_mode = lambda: "google"
    CFGR["switch_timeout_s"] = 60
    try:
        with TestClient(server.mcp.http_app(), base_url=BOARD12) as c:
            def post(data, headers=SAME, cookie=COOKIE):
                c.cookies.clear()
                if cookie: c.cookies.set(server._UI_COOKIE, cookie)
                return c.post("/runners/switch", data=data, headers=headers, follow_redirects=False)
            def tok(box, email=EMAIL): return server._runners_switch_token(email, box)
            good = lambda box="box-b", act="off": {"box": box, "act": act, "token": tok(box)}
            n0 = ncalls()
            r = post(good(), cookie=None)
            check("not signed in (ui_open off, auth on): 403, nothing runs", r.status_code == 403 and ncalls() == n0, (r.status_code, r.text))
            r = post(good(), cookie=server._ui_sign(json.dumps({"email": "intruder@example.org", "exp": time.time() + 3600})))
            check("signed in as someone who is not allowed: 403, nothing runs", r.status_code == 403 and ncalls() == n0, r.status_code)
            r = post(good(), cookie="forged.cookie")
            check("a forged cookie: 403, nothing runs", r.status_code == 403 and ncalls() == n0, r.status_code)
            r1 = post(good(), headers={}); r2 = post(good(), headers={"Origin": "https://evil.example.net"}); r3 = post(good(), headers={"Origin": "null"})
            check("no Origin, a foreign Origin, Origin 'null': 403 each, nothing runs (the same-origin check of the board's other actions)", [r1.status_code, r2.status_code, r3.status_code] == [403, 403, 403] and ncalls() == n0, (r1.status_code, r2.status_code, r3.status_code))
            r1 = post({"box": "box-b", "act": "off", "token": "0" * 64}); r2 = post({"box": "box-b", "act": "off"}); r3 = post({"box": "box-b", "act": "off", "token": tok("box-a")}); r4 = post({"box": "box-b", "act": "off", "token": tok("box-b", "other@example.org")})
            check("a wrong, a missing, another machine's or another viewer's token: 403 each, nothing runs", [r1.status_code, r2.status_code, r3.status_code, r4.status_code] == [403] * 4 and ncalls() == n0, [r1.status_code, r2.status_code, r3.status_code, r4.status_code])
            r1 = post({"box": "box-b", "act": "off", "token": "café-日本語"}); r2 = post({"box": "box-b", "act": "off", "token": tok("box-b") + "é"})
            check("a non-ASCII token: 403 each (compared as bytes), not a 500, nothing runs", [r1.status_code, r2.status_code] == [403, 403] and ncalls() == n0, (r1.status_code, r2.status_code))
            r = post({**good(), "pad": "x" * 5000})
            check("a body over 4096 bytes: 413, nothing runs", r.status_code == 413 and ncalls() == n0, r.status_code)
            r1 = post({"box": "box-b", "act": "reboot", "token": tok("box-b")}); r2 = post({"box": "box-b", "act": "", "token": tok("box-b")})
            check("an action other than off or on: 400 each, nothing runs", [r1.status_code, r2.status_code] == [400, 400] and ncalls() == n0, (r1.status_code, r1.text))
            hostile = ["home-nope", "box-b;id", "../box-b", "box-b box-a", "-o", ""]
            rs = [post({"box": b, "act": "off", "token": tok(b)}) for b in hostile]
            check("a machine that is not in fleet.names(), even with a valid token for that very text: 400 each, nothing runs (checked before any command)", [x_.status_code for x_ in rs] == [400] * len(hostile) and ncalls() == n0, [(b, x_.status_code) for b, x_ in zip(hostile, rs)])
            # the board item, box-g: outside the fleet's names, the route accepts a machine only when [runners] boxes lists it and [runners.ssh_hosts] names it
            hosts_r = CFGR.get("ssh_hosts"); R.fleet_boxes = lambda: ["box-a", "box-c"]
            try:
                CFGR["ssh_hosts"] = {}
                r1 = post(good("box-b", "off"), headers=JSONH)
                check("outside the fleet's names and not in [runners.ssh_hosts]: 400, nothing runs", r1.status_code == 400 and ncalls() == n0, (r1.status_code, r1.text))
                CFGR["ssh_hosts"] = {"box-b": "box-b"}
                r2 = post(good("box-b", "off"), headers=JSONH)
                check("…named in [runners.ssh_hosts] and listed in [runners] boxes: 200, the script ran once with 'off box-b'", r2.status_code == 200 and r2.json()["ok"] is True and ncalls() == n0 + 1 and LOGF.read_text().splitlines()[-1] == "2 off box-b", (r2.status_code, r2.text))
                n0 = ncalls()
                r3 = post(good("box-g", "off"), headers=JSONH)
                check("…another box that is neither (box-g not named): 400, nothing runs", r3.status_code == 400 and ncalls() == n0, (r3.status_code, r3.text))
            finally:
                R.fleet_boxes = lambda: list(FLEET5)
                if hosts_r is None: CFGR.pop("ssh_hosts", None)
                else: CFGR["ssh_hosts"] = hosts_r
            n0 = ncalls()
            r = c.get("/runners/switch", headers=SAME)
            check("GET is not allowed on the switch route (POST only)", r.status_code in (404, 405), r.status_code)
            r = post(good("box-b", "off"), headers=JSONH)
            check("signed in, own origin, right token: 200 and JSON {ok, text}; the script ran once with 'off box-b'",
                  r.status_code == 200 and r.json() == {"ok": True, "text": "box-b is disabled: a job already running finishes, then it takes no new job."}
                  and ncalls() == n0 + 1 and LOGF.read_text().splitlines()[-1] == "2 off box-b", (r.status_code, r.text))
            r = post(good("box-b", "on"))
            check("a form post without Accept: json gets the same text as plain text", r.status_code == 200 and r.text == "box-b is enabled: it takes jobs again within about 30 s." and r.headers["content-type"].startswith("text/plain"), (r.status_code, r.text))
            r = post(good("box-d", "off"), headers=JSONH); j = r.json()
            check("the script failing: 502 and {ok: false, text} with the reason, shown back on the page", r.status_code == 502 and j["ok"] is False and j["text"].startswith("Disable box-d failed.") and "ssh refused" in j["text"], (r.status_code, r.text))
            # the page carries the buttons for the viewer; the token in them is the one the route accepts
            SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on")}); R.reset()
            h = get_settled(c, "/runners", headers={"Cookie": f"{server._UI_COOKIE}={COOKIE}"}).text
            fs = forms(row(h, "box-b"))
            check("GET /runners (signed in): the Enable button for box-b carries the viewer's token for that machine", len(fs) == 1 and fs[0][:2] == ("box-b", "on") and fs[0][2] == tok("box-b") and fs[0][3] == "Enable", fs)
            jd = get_settled(c, "/runners.json", headers={"Cookie": f"{server._UI_COOKIE}={COOKIE}"}).json()
            check("/runners.json: the same buttons in its html", len(forms(row(jd["html"], "box-a"))) == 1 and jd["counts"]["runners"] == 10, jd.get("counts"))
            check("the token follows the viewer and the machine only", tok("box-b") == tok("box-b") and tok("box-b") != tok("box-a") and tok("box-b") != tok("box-b", "x@example.org"))
            # read-only copy: refused first, and no buttons drawn
            from stackshot.core import readonly
            try:
                readonly._reload_for_test(True)
                n0 = ncalls(); r = post(good())
                check("a read-only copy (STACKSHOT_READ_ONLY): 503 with the standby sentence, nothing runs", r.status_code == 503 and readonly.REFUSAL in r.text and ncalls() == n0, (r.status_code, r.text))
                check("…and its page draws no button (no token maker)", server._runners_token_maker(None) is None)
            finally:
                readonly._reload_for_test(False)
            CFGR["switch_script"] = ""
            r = post(good())
            check("no switch_script: the token maker is None (no button on the page); a press from an old page is refused with the sentence, nothing runs", server._runners_token_maker(None) is None and r.status_code == 502 and "not set up" in r.text and ncalls() == n0, (r.status_code, r.text))
            CFGR["switch_script"] = str(FAKE)
        # the board open (auth off, as in the other suites): the switch still needs a real signed-in address, as /answer and /watch do, so an anonymous viewer is refused and no button is drawn
        server._cfg.CFG["auth"]["ui_open"] = True; server._signin._auth_mode = lambda: "off"
        with TestClient(server.mcp.http_app(), base_url=BOARD12) as c:
            n0 = ncalls()
            r = c.post("/runners/switch", data={"box": "box-b", "act": "off", "token": server._runners_switch_token("", "box-b")}, headers=JSONH)
            r2 = c.post("/runners/switch", data={"box": "box-b", "act": "off", "token": server._runners_switch_token("", "box-b")}, headers={"Origin": "https://evil.example.net"})
            check("the board open: an anonymous viewer is refused with 403 even with a matching token and the board's own origin, and nothing runs", r.status_code == 403 and r2.status_code == 403 and ncalls() == n0, (r.status_code, r2.status_code))
            SSH_OUT.update({"box-b": wsl("off")}); R.reset()
            h = get_settled(c, "/runners").text
            check("…and the open board's page draws no Disable / Enable button", "/runners/switch" not in h and not forms(row(h, "box-b")), len(h))
    finally:
        server._signin._auth_mode = real_mode
        if allowed_was is None: server._cfg.CFG["auth"].pop("allowed_emails", None)
        else: server._cfg.CFG["auth"]["allowed_emails"] = allowed_was
        if ui_open_was is None: server._cfg.CFG["auth"].pop("ui_open", None)
        else: server._cfg.CFG["auth"]["ui_open"] = ui_open_was
finally:
    R.fleet_boxes = real_fleet_boxes; os.environ.pop("B624_DECOY_SECRET", None)
    for k_, v_ in (("switch_script", was_script), ("switch_timeout_s", was_to)):
        if v_ is None: CFGR.pop(k_, None)
        else: CFGR[k_] = v_
    (FAKE_DIR / "release").write_text("go")                       # lets a fake still waiting finish
    R.reset()


# ---- 13. the pages never build in the request (stale while revalidate), and a busy runner's start and end gaps are named
# Made-up names throughout (box-a, salamander, stackshot, example-owner); the fake GitHub, ssh and clock are the ones above. The "before" figure is what the routes did until now:
# snapshot() rebuilt inside the request once the snapshot was older than cache_s.
import copy, threading
SLOW_S = 0.4
def slow_fake(path, timeout=8):
    time.sleep(SLOW_S); return fake_get(path, timeout)
def lists_asked(): return sum("/actions/runners?" in p for p in CALLS)
def clean_state():
    R.PERSIST = False; (T / "state" / R.SNAP_FILE).unlink(missing_ok=True)

# 13a. a stale snapshot, slow GitHub: the old path waits for the whole rebuild, serve() answers at once
setfiles(mode="on\n", hold="", gate="")
SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on", "salamander")})
fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40; R._get = slow_fake; CALLS.clear()
t0 = time.monotonic(); old = R.snapshot(); before_s = time.monotonic() - t0              # the route's call until now
fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40; R._get = slow_fake; CALLS.clear()
t0 = time.monotonic(); sv = R.serve(); after_s = time.monotonic() - t0
print(f"measured: a request with a stale snapshot and GitHub taking {SLOW_S} s a call: before {before_s:.2f} s (snapshot() rebuilds in the request), after {after_s:.3f} s (serve())")
check("a stale snapshot, slow GitHub: the old path took the whole rebuild (3 calls or more at 0.4 s)", before_s >= 3 * SLOW_S and old["ts"] == T0 + 40, before_s)
check("…serve() answers at once with the last snapshot, 40 s old, a rebuild running, and not 'stale' (a rebuild is on its way)", after_s < 0.15 and sv["ts"] == T0 and sv["age_s"] == 40
      and sv["refreshing"] is True and sv["stale"] is False and len(sv["runners"]) == 10, (after_s, sv.get("age_s"), sv.get("refreshing"), sv.get("stale")))
h = R2.table_html(sv, CLOCK[0])
check("…its page says how old it is and that it is refreshing, and has no 'not refreshed since' line", f"Updated {CLK}:00 {ABBR} · 40s ago · refreshing now · page checks every 30 s" in h and "not refreshed since" not in h, h[:200])
check("…and in the JSON (refreshing, not pending)", R2.data(sv, CLOCK[0])["refreshing"] is True and R2.data(sv, CLOCK[0])["pending"] is False)
check("…the rebuild lands in the background: the next answer is the new snapshot, not refreshing", settle() and R.serve()["ts"] == T0 + 40 and R.serve()["refreshing"] is False and lists_asked() == 2, (lists_asked(),))

# 13b. many requests at once, one rebuild
fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40; R._get = slow_fake; CALLS.clear()
outs, took = [], []
def hit():
    t = time.monotonic(); outs.append(R.serve()); took.append(time.monotonic() - t)
ths = [threading.Thread(target=hit) for _ in range(12)]
for t in ths: t.start()
for t in ths: t.join(5)
settle()
check("12 requests at once on a stale snapshot: every one answered at once with the old snapshot", len(outs) == 12 and max(took) < 0.3 and all(o["ts"] == T0 for o in outs), (len(outs), max(took)))
check("…and one rebuild ran for all of them (one runner list per repo: 2, not 24)", lists_asked() == 2, lists_asked())
n = len(CALLS); R.serve(); R.serve(); settle()
check("…a fresh snapshot is served without a call", len(CALLS) == n)
CLOCK[0] = T0 + 40 + 24; R.serve(); settle()
check("…24 s after the rebuild still none (cache_s 25 s: no more often than before)", len(CALLS) == n, len(CALLS) - n)
CLOCK[0] = T0 + 40 + 26; R.serve(); settle()
check("…26 s after it, one more rebuild", lists_asked() == 4 and R.serve()["ts"] == T0 + 66, (lists_asked(), R.serve()["ts"]))
R.mark_dirty(); sv = R.serve(); settle()
check("a button press (mark_dirty): the next answer is still the old snapshot at once and one rebuild follows", sv["refreshing"] is True and lists_asked() == 6, (sv["refreshing"], lists_asked()))

# 13c. a rebuild that hangs: the old snapshot is served and, once the rebuild has overrun (past 2 x build_s), said honestly to be stale
GATE.clear(); STARTED.clear()
OFF = [0.0]; R._mono = lambda: time.monotonic() + OFF[0]            # the rebuild's running time moves with this offset, as the wall clock moves with CLOCK
fresh(); R._get = fake_get; R.snapshot(); R._get = blocking_get; CLOCK[0] = T0 + 40
try:
    R.serve(); STARTED.wait(5); CLOCK[0] = T0 + 100; OFF[0] = 41
    sv = R.serve(); h = R2.table_html(sv, CLOCK[0]); d = R2.data(sv, CLOCK[0])
    check("a rebuild that never ends (41 s, past 2 x build_s) and a 100 s old snapshot: served at once, refreshing, stale, and the page says 'not refreshed since' with the time it was read",
          sv["ts"] == T0 and sv["refreshing"] is True and sv["stale"] is True and f"not refreshed since {CLK}:00 {ABBR}" in h and "1m ago" in h and d["stale"] is True, (sv.get("stale"), h[:300]))
finally:
    GATE.set(); OFF[0] = 0.0
settle()

# 13c2. the cue is stale only when no refresh is on its way: a first open after the page sat idle, an overrunning refresh, a failed refresh
import stackshot.web.ui.releasing as _rel
_rel._run = lambda argv: ""                            # the page's header reads the release queue (systemd units of the host): none here
BOARD13 = ui_render.Board(str(T / "store"))
def pages13(sv): return {"page": R2.page_html(BOARD13, sv)}
def body_tag(pg): return pg.split('id="rn-body"')[1].split(">")[0]          # the opening tag of the table's body, where data-stale and data-refreshing are set
GATE.clear(); STARTED.clear()
fresh(); R._get = fake_get; R.snapshot(); R._get = blocking_get; CLOCK[0] = T0 + 100               # idle for 100 s (past cache_s + build_s + 30 s = 75 s): nobody has asked since
try:
    sv = R.serve(); STARTED.wait(5); pg = pages13(sv); h = R2.table_html(sv, CLOCK[0])
    check("a first open after idle (snapshot 100 s old): served at once, a refresh started, and NOT stale", sv["age_s"] == 100 and sv["refreshing"] is True and sv["stale"] is False and STARTED.is_set() and len(sv["runners"]) == 10, (sv.get("age_s"), sv.get("refreshing"), sv.get("stale")))
    check("…drawn at full strength: no data-stale on the body, no 'not refreshed since', and the JSON says stale false",
          all("data-stale" not in body_tag(t_) for t_ in pg.values()) and "not refreshed since" not in h and "refreshing now" in h and R2.data(sv, CLOCK[0])["stale"] is False, h[:200])
    check("…the page tells its script a refresh is running, which asks again within 2 s instead of after its 30 s interval",
          all('data-refreshing="1"' in body_tag(t_) and "if(box.hasAttribute('data-refreshing'))setTimeout(load,2000);" in t_ for t_ in pg.values()), [body_tag(t_) for t_ in pg.values()])
    OFF[0] = 39; sv = R.serve()
    check("…a refresh that has run 39 s (under 2 x build_s) is still not stale", sv["refreshing"] is True and sv["stale"] is False, sv.get("stale"))
    OFF[0] = 41; sv = R.serve(); pg = pages13(sv); h = R2.table_html(sv, CLOCK[0])
    check("an overrunning refresh (41 s, past 2 x build_s): stale, with the warning, the dimming and the JSON flag",
          sv["refreshing"] is True and sv["stale"] is True and f"not refreshed since {CLK}:00 {ABBR}" in h and R2.data(sv, CLOCK[0])["stale"] is True
          and all("data-stale" in body_tag(t_) for t_ in pg.values()), (sv.get("stale"), h[:200]))
finally:
    GATE.set(); OFF[0] = 0.0
settle()
def refuse(path, timeout=8): raise RunnersError("GitHub answered 502 for " + path, 502)
fresh(); R._get = fake_get; R.snapshot(); R._get = refuse; CLOCK[0] = T0 + 100
R.serve(); settle(); CLOCK[0] += 2; sv = R.serve(); pg = pages13(sv); h = R2.table_html(sv, CLOCK[0])
check("a failed refresh: the last runners are kept and the answer is stale, with the warning, the dimming and the JSON flag",
      sv["refreshing"] is False and sv["stale"] is True and len(sv["runners"]) == 10 and sv["ts"] == T0 and f"not refreshed since {CLK}:00 {ABBR}" in h
      and R2.data(sv, CLOCK[0])["stale"] is True and all("data-stale" in body_tag(t_) for t_ in pg.values()), (sv.get("stale"), h[:300]))
check("…the error line says how old the runners shown are", "showing the runners read" in h, h[:400])
R._get = fake_get; CLOCK[0] += 30; R.serve(); settle(); sv = R.serve()
check("…and the next refresh that reads the runners clears it", sv["stale"] is False and sv["ts"] == CLOCK[0] and "not refreshed since" not in R2.table_html(sv, CLOCK[0]), (sv.get("stale"), sv["ts"]))
R._mono = time.monotonic

# 13d. nothing read yet and no file: a placeholder at once, then the table
fresh(); R._get = slow_fake; clean_state(); CLOCK[0] = T0
t0 = time.monotonic(); sv = R.serve(); took_s = time.monotonic() - t0
check("no snapshot yet: the answer is at once, pending, with no runners", took_s < 0.15 and sv["pending"] is True and sv["runners"] == [] and sv["refreshing"] is True, (took_s, sv))
check("…the page says it is reading, draws no table, and the JSON says pending", "Reading the runners" in R2.table_html(sv, T0) and "<table" not in R2.table_html(sv, T0)
      and R2.data(sv, T0)["pending"] is True and R2.data(sv, T0)["counts"]["runners"] == 0)
check("…and the first read lands in the background", settle() and R.serve().get("pending") is None and len(R.serve()["runners"]) == 10)

# 13e. the last snapshot is kept in a file across restarts
fresh(); R._get = fake_get; clean_state(); R.snapshot()
check("persistence is off until the server turns it on: no file is written", not (T / "state" / R.SNAP_FILE).exists())
try:
    fresh(); R.PERSIST = True; R.snapshot(); f = T / "state" / R.SNAP_FILE
    check("with persistence on, a build writes the file (owner-only) with the figures only: no flags", f.exists() and (f.stat().st_mode & 0o077) == 0
          and set(json.loads(f.read_text())) == {"version", "ts", "errors", "failed", "runners", "switch"}, f.exists() and sorted(json.loads(f.read_text())))
    check("…no temp file is left beside it", [p.name for p in f.parent.iterdir() if p.name != R.SNAP_FILE and p.name.startswith(".runners-")] == [])
    R.reset(); CALLS.clear()                                  # a restart: nothing cached
    check("after a restart restore() takes the file back", R.restore() is True and R.peek() is not None and R.peek()["ts"] == T0)
    CLOCK[0] = T0 + 5; sv = R.serve()
    check("…the first request is served from it at once, 5 s old, with no GitHub call and no rebuild", sv["ts"] == T0 and len(sv["runners"]) == 10 and not sv.get("pending") and CALLS == [] and sv["refreshing"] is False, (CALLS, sv.get("refreshing")))
    CLOCK[0] = T0 + 100; R._get = slow_fake; sv = R.serve()
    check("…an old one is served at once too and refreshed once, by its own time", sv["ts"] == T0 and sv["refreshing"] is True and settle() and lists_asked() == 2 and R.serve()["ts"] == T0 + 100, (lists_asked(),))
    check("…and the file now holds the new snapshot", json.loads(f.read_text())["ts"] == T0 + 100)
    R.reset(); f.write_text("{not json"); check("a damaged file is ignored: no snapshot, the first request is pending", R.restore() is False and R.serve()["pending"] is True); settle()
    for label_, bad_ in (("a wrong shape", {"version": 1, "ts": T0, "errors": {}, "failed": [], "switch": {}, "runners": [{"name": 5}]}), ("a time in the future", {"ts": T0 + 99999, "errors": {}, "failed": [], "switch": {}, "runners": []}),
                         ("a list instead of an object", [1, 2])):
        R.reset(); f.write_text(json.dumps(bad_)); check(f"a file with {label_} is ignored", R.restore() is False and R.peek() is None)
    R.reset(); R._CACHE["snap"] = {"ts": T0, "errors": {}, "failed": [], "runners": [], "stale": False}
    f.write_text(json.dumps({"ts": T0, "errors": {}, "failed": [], "switch": {}, "runners": []}))
    check("restore() does not replace a snapshot that is already cached", R.restore() is False and R.peek()["ts"] == T0)
    fresh(); R.PERSIST = True; f.write_text(json.dumps({"ts": 1}))
    R._get = lambda p, t=8: (_ for _ in ()).throw(RunnersError("GitHub answered 502 for " + p, 502)); R.snapshot()
    check("a build where every list failed is not written over the last good file", json.loads(f.read_text()) == {"ts": 1})
finally:
    clean_state(); R._get = fake_get; fresh()

# 13f. over HTTP: /runners, /runners.json draw at once on a stale snapshot
with TestClient(server.mcp.http_app()) as c:
    for path in ("/runners", "/runners.json", "/runners", "/runners.json"):
        fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40; R._get = slow_fake
        t0 = time.monotonic(); r = c.get(path); took_s = time.monotonic() - t0
        body = r.json()["html"] if path.endswith(".json") else r.text
        print(f"measured: GET {path} on a stale snapshot, GitHub taking {SLOW_S} s a call: {took_s:.3f} s")
        check(f"GET {path} on a stale snapshot, slow GitHub: 200 at once with the old table, refreshing now, no 'not refreshed since'",
              r.status_code == 200 and took_s < 0.3 and "refreshing now" in body and "not refreshed since" not in body and body.count('<b class="rname">') == 10, (r.status_code, took_s, body[:300]))
        settle()
    R._get = fake_get
    pages_ = [c.get(p).text for p in ("/runners", "/runners")]
    check("the page's script asks again within seconds while a rebuild runs or nothing is read", all("d.refreshing||d.pending" in t_ and "setTimeout(load,3000)" in t_ for t_ in pages_))
    settle()

# 13g. a busy runner's job: the gaps at the start and end of a job are named, "job not found" is left for a real mismatch
SAVED = (copy.deepcopy(RUNS), copy.deepcopy(JOBS), copy.deepcopy(RUNNERS), copy.deepcopy(QUEUED))
def restore_data():
    RUNS.clear(); RUNS.update(copy.deepcopy(SAVED[0])); JOBS.clear(); JOBS.update(copy.deepcopy(SAVED[1])); RUNNERS.clear(); RUNNERS.update(copy.deepcopy(SAVED[2])); QUEUED.clear(); QUEUED.update(copy.deepcopy(SAVED[3]))
def line(snap, name, mod=R2):                                # the runner's row text, tags stripped
    html = mod.table_html(snap, CLOCK[0]); m = re.search(rf'<b class="rname">{name}</b>(.*?)</li>', html, re.S); return re.sub(r"<[^>]+>", "", m.group(1)) if m else None
S2 = "box-a-salamander-2"
try:
    fresh(); R._get = fake_get; snap = R.snapshot(); j = by(snap)[S2]["job"]
    check("the normal case is unchanged: the in-progress run names the job (PR 17, 5 minutes), no phase", j["pr"] == 17 and j["phase"] == "" and "salamander #17 · 5m" in line(snap, S2), line(snap, S2))
    # a job whose run is still queued
    QUEUED["salamander"] = RUNS["salamander"]; RUNS["salamander"] = []; fresh(); snap = R.snapshot(); j = by(snap)[S2]["job"]
    check("a run still queued while its job has started: the job is found in the queued runs and named (PR 17), not 'job not found'", j["pr"] == 17 and j["phase"] == "" and "job not found" not in line(snap, S2)
          and any("status=queued" in p for p in CALLS), (j, line(snap, S2)))
    check("…at most MAX_QUEUED queued runs are asked for, one list call per repo with an unmatched runner", all(p.endswith(f"per_page={R.MAX_QUEUED}") for p in CALLS if "status=queued" in p) and sum("status=queued" in p for p in CALLS) == 1, [p for p in CALLS if "queued" in p])
    restore_data()
    # the job has just finished, the run goes on
    JOBS[11][0]["status"] = "completed"; JOBS[11][0]["completed_at"] = iso(T0 - 10); fresh(); snap = R.snapshot(); j = by(snap)[S2]["job"]
    check("a job completed 10 s ago, its run still going: 'finishing job…' with the PR it ran for", j["phase"] == "finishing" and j["pr"] == 17 and "salamander #17 · finishing job…" in line(snap, S2)
          and "job not found" not in R2.table_html(snap, T0), (j, line(snap, S2)))
    check("…and a runner whose finished job is already listed is not looked for in the queued runs", not any("status=queued" in p for p in CALLS), [p for p in CALLS if "queued" in p])
    JOBS[11][0]["completed_at"] = iso(T0 - 1000); fresh(); snap = R.snapshot(); j = by(snap)[S2]["job"]
    check("a job completed 1000 s ago is no explanation for a runner busy now: 'job not found' (nothing else to go on)", j["phase"] == "lost" and "job not found" in line(snap, S2), line(snap, S2))
    restore_data()
    # the run has completed: the previous snapshot knew the job
    fresh(); snap = R.snapshot(); RUNS["salamander"] = []; CLOCK[0] = T0 + 30; snap = R.snapshot(force=True); j = by(snap)[S2]["job"]
    check("the run completed while the runner is still busy: 'finishing job…' carrying the PR of the job the last snapshot saw, but not its start (the gap is not time on a job)", j["phase"] == "finishing" and j["pr"] == 17 and j["started"] == 0.0
          and "salamander #17 · finishing job…" in line(snap, S2) and "5m" not in line(snap, S2), (j, line(snap, S2)))
    CLOCK[0] = T0 + 100; snap = R.snapshot(force=True); j = by(snap)[S2]["job"]
    check("…still told at the next rebuild, 70 s into the gap", j["phase"] == "finishing" and j["gap"] == T0 + 30, j)
    CLOCK[0] = T0 + 230; snap = R.snapshot(force=True); j = by(snap)[S2]["job"]
    check("…and past GAP_S (180 s) of it a mismatch: 'job not found'", j["phase"] == "lost" and "job not found" in line(snap, S2), (j, line(snap, S2)))
    CLOCK[0] = T0 + 260; CALLS.clear(); snap = R.snapshot(force=True)
    check("…a mismatch already told is not looked for in the queued runs again (no extra calls beyond today's)", not any("status=queued" in p for p in CALLS) and by(snap)[S2]["job"]["phase"] == "lost", [p for p in CALLS if "queued" in p])
    restore_data()
    # a runner that was idle in the last snapshot and is busy now with no run naming it yet
    RUNNERS["salamander"][1]["busy"] = False; fresh(); snap = R.snapshot(); RUNNERS["salamander"][1]["busy"] = True; RUNS["salamander"] = []; CLOCK[0] = T0 + 30; snap = R.snapshot(force=True)
    j = by(snap)[S2]["job"]
    check("busy now, idle in the last snapshot, no run names it: 'starting job…' with its repo, no 'job not found'", j["phase"] == "starting" and "salamander · starting job…" in line(snap, S2) and "job not found" not in line(snap, S2), (j, line(snap, S2)))
    restore_data(); CLOCK[0] = T0 + 60; snap = R.snapshot(force=True)
    check("…and when the run is listed at the next rebuild the job is named", by(snap)[S2]["job"]["pr"] == 17 and by(snap)[S2]["job"]["phase"] == "", by(snap)[S2]["job"])
    # the run's name is told when there is no PR or branch to link
    restore_data(); RUNS["salamander"][0].update(pull_requests=[], head_branch="", name="nightly build", display_title="nightly build  of\nthings")
    JOBS[11][0]["status"] = "completed"; JOBS[11][0]["completed_at"] = iso(T0 - 5); fresh(); snap = R.snapshot()
    check("a finishing job with no PR or branch names the run (whitespace squeezed): 'salamander · nightly build of things · finishing job…'", "salamander · nightly build of things · finishing job…" in (line(snap, S2) or ""), line(snap, S2))
    # a real mismatch: no run anywhere names the runner, nothing before it either
    restore_data(); RUNS["salamander"] = []; fresh(); snap = R.snapshot()
    check("a busy runner no run names and no earlier snapshot knows: 'job not found' stays", by(snap)[S2]["job"]["phase"] == "lost" and "salamander, job not found" in line(snap, S2), line(snap, S2))
    check("…and the JSON carries the phase for a script (job.phase, job.run)", {"phase", "run"} <= set(next(q for q in R2.data(snap, T0)["runners"] if q["name"] == S2)["job"]))
finally:
    restore_data(); fresh()


# 13h. the review's cases for the pages' rebuild: a stalled thread, a press during a build, a build that reads nothing, a saved file of another shape
GS = {}; ORDER = []; GL = threading.Lock()
def gated_get(path, timeout=8):                             # every thread's first call waits on a gate of its own (ORDER holds them in the order the threads came)
    me = threading.get_ident()
    with GL:
        if me not in GS:
            GS[me] = threading.Event(); ORDER.append(GS[me])
    GS[me].wait(10); return fake_get(path, timeout)
def wait_for(cond, limit=5):
    t0_ = time.monotonic()
    while time.monotonic() - t0_ < limit:
        if cond(): return True
        time.sleep(0.01)
    return False
try:
    # 1. a stalled build does not block the rebuilds after it
    GS.clear(); ORDER.clear(); MONO[0] = 1000.0; R._mono = lambda: MONO[0]
    fresh(); R._get = fake_get; R.snapshot(); R._get = gated_get; CLOCK[0] = T0 + 40
    R.serve(); th_a = R._SERVE["thread"]; wait_for(lambda: len(ORDER) == 1)
    check("a rebuild is stalled: the page says refreshing and no second one starts yet", R.serve()["refreshing"] is True and len(ORDER) == 1 and R._SERVE["thread"] is th_a, len(ORDER))
    MONO[0] += 51                                           # past build_s (20) + 30 s
    R.serve(); th_b = R._SERVE["thread"]
    check("…past build_s + 30 s the stalled thread no longer counts: a new rebuild starts", th_b is not th_a and wait_for(lambda: len(ORDER) == 2), (th_b is th_a, len(ORDER)))
    check("…and the page is refreshing again (the new thread's mark)", R.serve()["refreshing"] is True)
    ORDER[0].set(); th_a.join(5)
    check("when the stalled thread ends it does not clear the newer thread's place", not th_a.is_alive() and R._SERVE["thread"] is th_b and R.serve()["refreshing"] is True, (th_a.is_alive(), R._SERVE["thread"] is th_b))
    for e_ in ORDER: e_.set()
    th_b.join(5)
    check("…and when the newer one ends the place is free", settle() and R._SERVE["thread"] is None and R.serve()["refreshing"] is False)
finally:
    for e_ in ORDER: e_.set()
    R._mono = time.monotonic; R._get = fake_get
settle()

try:
    # 2. a press during a rebuild is not lost when the rebuild lands
    GATE.clear(); STARTED.clear(); fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40; R._get = blocking_get; CALLS.clear()
    R.serve(); STARTED.wait(5); R.mark_dirty()
    GATE.set(); settle()
    check("a press while a rebuild runs: that rebuild lands marked out of date", R._CACHE["snap"].get("dirty") is True and lists_asked() == 2, (R._CACHE["snap"].get("dirty"), lists_asked()))
    R._get = fake_get; sv = R.serve(); settle()
    check("…so the next answer starts one more rebuild (4 runner lists in all), and a third finds it fresh", sv["refreshing"] is True and lists_asked() == 4 and not R._CACHE["snap"].get("dirty"), lists_asked())
    n_ = len(CALLS); R.serve(); settle()
    check("…which asks nothing more", len(CALLS) == n_)
finally:
    GATE.set(); R._get = fake_get
settle()

try:
    # 3. a rebuild that reads nothing keeps the last good runners
    fresh(); R._get = fake_get; R.snapshot(); CLOCK[0] = T0 + 40
    R._get = lambda p, t=8: (_ for _ in ()).throw(RunnersError("GitHub answered 502 for " + p, 502))
    snap = R.snapshot()
    check("every list failed: the 10 runners of the last good snapshot stay, with its own time", len(snap["runners"]) == 10 and snap["ts"] == T0, (len(snap["runners"]), snap["ts"]))
    check("…only the error line is new, and it says how old the runners shown are", list(snap["errors"]) == ["all"] and "502" in snap["errors"]["all"] and "showing the runners read 40s ago" in snap["errors"]["all"], snap["errors"])
    h = R2.table_html(snap, CLOCK[0])
    check("…the page draws the table and the error line", h.count('<b class="rname">') == 10 and "showing the runners read 40s ago" in h)
    CALLS.clear(); CLOCK[0] = T0 + 45; R.serve(); settle()
    check("…the next try waits cache_s as after any build: nothing asked 5 s later", CALLS == [], CALLS)
    R._get = fake_get; CLOCK[0] = T0 + 40 + 26; R.serve(); settle()
    check("…26 s after it the next rebuild reads again and the error line is gone", len(R.serve()["runners"]) == 10 and R.serve()["ts"] == T0 + 66 and R.serve()["errors"] == {}, R.serve()["errors"])
    fresh(); R._get = lambda p, t=8: (_ for _ in ()).throw(RunnersError("GitHub answered 502 for " + p, 502)); snap = R.snapshot()
    check("with no earlier snapshot a failed rebuild is still an empty one with its errors", snap["runners"] == [] and len(snap["errors"]) == 2 and len(snap["failed"]) == 2, snap["errors"])
finally:
    R._get = fake_get

try:
    # 4. a saved file of another version, or a job without its start, is not taken
    fresh(); R._get = fake_get; clean_state(); R.PERSIST = True; R.snapshot(); f = T / "state" / R.SNAP_FILE; good = json.loads(f.read_text())
    R.reset(); check("the file as written is taken back (control)", R.restore() is True)
    d_ = dict(good); d_.pop("version"); f.write_text(json.dumps(d_)); R.reset()
    check("a file with no version is ignored", R.restore() is False and R.peek() is None)
    d_ = copy.deepcopy(good); d_["version"] = 2; f.write_text(json.dumps(d_)); R.reset()
    check("a file of another version is ignored", R.restore() is False and R.peek() is None)
    d_ = copy.deepcopy(good); jr_ = next(x for x in d_["runners"] if x.get("job")); jr_["job"].pop("started"); f.write_text(json.dumps(d_)); R.reset()
    check("a file whose job has no start is ignored", R.restore() is False and R.peek() is None)
finally:
    clean_state(); R._get = fake_get; fresh()


# ---- 14. a runner offline for a short while is not a fault (WSL runners restart after each job): the clock is the snapshots' own `off_since`, the grace R.OFFLINE_GRACE_S (5 minutes)
import copy
G = R.OFFLINE_GRACE_S; G_i = int(G)
RUNNERS_G14 = copy.deepcopy(RUNNERS); SSH_G14 = dict(SSH_OUT)
def set_box_b_online(online):                         # the one runner these checks flip: box-b's stackshot runner
    RUNNERS["stackshot"][2] = rn("box-b-stackshot", "box-b", online=online)
def at(dt_s):                                         # the clock at T0 + dt_s, one forced read of box-b's stackshot runner
    CLOCK[0] = T0 + dt_s; return by(R.snapshot(force=True))["box-b-stackshot"]
try:
    check("14: the grace is 5 minutes", G == 300.0, G)
    setfiles(mode="on\n", hold="", gate=""); SSH_OUT.update({"box-b": wsl("on"), "box-c": wsl("on")})
    fresh(); set_box_b_online(False)
    x = at(0)
    check("14a: offline for 0 s with the switch on and nothing held: not a fault, it reads as restarting", (x["kind"], x["state"], x["disabled"]) == ("restarting", "offline", False), x)
    check("14a: …the reason says how long it has been offline", x["reason"] == "offline for 0s", x["reason"])
    snap = R.snapshot(); html = R2.table_html(snap, CLOCK[0])
    check("14a: …the page does not draw it red (no fault class, no warning sign) and the Offline card has none of it", '<li class="rn fault">' not in row(html, "box-b") and "⚠" not in row(html, "box-b"), row(html, "box-b"))
    li = re.search(r'<li class="rn (\w+)">(?:(?!</li>).)*box-b-stackshot</b> <span class="rst">(\w+)</span>', row(html, "box-b"), re.S)
    check("14a/3: …it is drawn with the idle style and the word 'restarting' (not the hollow offline dot, not the word 'offline')", li is not None and (li.group(1), li.group(2)) == ("idle", "restarting") and "rn offline" not in row(html, "box-b"), row(html, "box-b"))
    cl = {c["box"]: R.card_total(c) for c in R.counts(snap)}
    check("14a/4: …the side panel counts the machine as online, as the cards do (box-b reads 0/2, not 'offline')", cl["box-b"] == {"text": "0/2", "cls": "idle"}, cl)
    off0 = tcard(html, "Offline")
    check("14a: …the cards still add up (it counts as idle, between two jobs)", sum(tcard(html, w) for w in ("Running", "Idle", "Disabled", "Offline")) == tcard(html, "Runners"), html[:700])
    x = at(G - 1)
    check("14a: still offline 299 s later: still not a fault, and the time offline is counted from the first read", (x["kind"], x["reason"]) == ("restarting", "offline for 4m") and x["off_since"] == T0, x)
    x = at(G)
    check("14b: offline for the full grace: a fault, with the reason it had before the grace", (x["kind"], x["reason"]) == ("fault", "offline, and the CI switch did not disable it"), x)
    snap = R.snapshot(); html = R2.table_html(snap, CLOCK[0])
    check("14b: …drawn red with the warning sign, and the Offline card counts the red ones (none before the grace)", '<li class="rn fault">' in row(html, "box-b") and "⚠" in row(html, "box-b") and off0 == 0 and tcard(html, "Offline") == html.count('<li class="rn fault">') > 0, (off0, row(html, "box-b")))
    for dt_s in range(G_i + 25, 3601, 25): x = at(dt_s)       # the page polled every 25 s for an hour
    x = at(G + 3600)
    check("14b: offline for an hour, the page polled regularly: still a fault, and the first-seen time did not move", x["kind"] == "fault" and x["off_since"] == T0, x)
    # c: back online clears the clock; the next gap starts fresh
    set_box_b_online(True); x = at(G + 3700)
    check("14c: back online: idle, and the row carries no offline mark", (x["state"], x["kind"]) == ("idle", "") and "off_since" not in x, x)
    set_box_b_online(False); x = at(G + 3710)
    check("14c: offline again 10 s later: a new gap, restarting, counted from now (not a fault although the first gap was long ago)", (x["kind"], x["off_since"]) == ("restarting", T0 + G + 3710), x)
    x = at(G + 3710 + G - 1)
    check("14c: …and a fault only after its own 5 minutes: not yet at 299 s", x["kind"] == "restarting", x)
    x = at(G + 3710 + G)
    check("14c: …a fault at 300 s", x["kind"] == "fault", x)
    # d: the switch's reasons are unchanged and do not wait for the grace
    SSH_OUT["box-b"] = wsl("off"); fresh(); set_box_b_online(False); x = at(0)
    check("14d: disabled by the switch: 'disabled on box-b' at once, disabled, not restarting", (x["kind"], x["reason"], x["disabled"]) == ("switch", "disabled on box-b", True), x)
    SSH_OUT["box-b"] = wsl("on", "stackshot"); fresh(); set_box_b_online(False); x = at(0)
    check("14d: held for the repo: 'held for stackshot on box-b' at once", (x["kind"], x["reason"], x["disabled"]) == ("switch", "held for stackshot on box-b", True), x)
    SSH_OUT["box-b"] = RunnersError("ssh exit 255"); fresh(); set_box_b_online(False); x = at(0)
    check("14d: a box that cannot be reached: 'box not reachable' at once, not restarting", (x["kind"], x["reason"]) == ("unreachable", "box not reachable (ssh exit 255)"), x)
    check("14d: _why_offline with no time given (a direct call) says fault, as before the grace", R._why_offline("box-b", "stackshot", "n", {"ok": True, "mode": "on", "held": [], "gate": []}) == ("fault", "offline, and the CI switch did not disable it"))
    # e: the mark survives a restart of the server (the snapshot file carries it)
    SSH_OUT["box-b"] = wsl("on"); fresh(); clean_state(); R.PERSIST = True; set_box_b_online(False)
    at(0); R.reset(); R.restore()
    check("14e: after a restart the first-seen time is taken from the saved snapshot", any(r.get("off_since") == T0 for r in R._CACHE["snap"]["runners"] if r["name"] == "box-b-stackshot"), None)
    x = at(G + 1)
    check("14e: …so the gap is counted across the restart: a fault 301 s after the first read", (x["kind"], x["off_since"]) == ("fault", T0), x)
    # f: the mark is carried only from a recent snapshot (1, 2): a long gap between two reads may hide an online stretch
    B = R._carry_s()
    check("14f/1: the bound is 3 x the largest of cache_s, panel_refresh_s and the publish interval (30 minutes with [publish] every_minutes = 10), never less than the grace",
          B == 1800.0 == 3 * 60 * float(R._cfg.get("publish", "every_minutes", default=10)) and B >= 3 * float(R.conf("panel_refresh_s")) and B >= G, B)
    SSH_OUT["box-b"] = wsl("on"); fresh(); set_box_b_online(False); at(0)
    x = at(B)
    check("14f/1: a previous snapshot exactly the bound old still passes its mark on (a fault: first seen 360 s ago)", (x["kind"], x["off_since"]) == ("fault", T0), x)
    fresh(); set_box_b_online(False); at(0)
    x = at(B + 1)
    check("14f/1: a previous snapshot older than the bound passes nothing on: the clock starts now, so no instant fault", (x["kind"], x["off_since"], x["reason"]) == ("restarting", T0 + B + 1, "offline for 0s"), x)
    fresh(); set_box_b_online(False); at(0)
    x = at(7200)
    check("14f/1: a snapshot hours old (a page nobody opened) gives no instant fault either", (x["kind"], x["off_since"]) == ("restarting", T0 + 7200), x)
    x = at(7200 + 100)
    check("14f/1: …and polled again soon after, the new clock runs on from there", (x["kind"], x["off_since"]) == ("restarting", T0 + 7200), x)
    x = at(7200 + 100 + G_i)
    check("14f/1: …and reaches the fault 300 s after the first read of the new clock", (x["kind"], x["off_since"]) == ("fault", T0 + 7200), x)
    fresh(); set_box_b_online(False); at(0); set_box_b_online(True); at(100); set_box_b_online(False)      # 2: two blips with an unseen online stretch between two offline reads
    x = at(3600)
    check("14f/2: offline at 0 s, online unseen, offline again an hour later: a new short gap, not one long outage", (x["kind"], x["off_since"]) == ("restarting", T0 + 3600), x)
    fresh(); set_box_b_online(False); at(0); set_box_b_online(True); at(100); set_box_b_online(False)
    x = at(7200)
    check("14f/2: …also when the online read lies between and the offline reads are hours apart", (x["kind"], x["off_since"]) == ("restarting", T0 + 7200), x)
    # g: nobody views /runners: only the timer publish's board render rebuilds the snapshot, every 10 minutes (the previous snapshot is 600 s old at each rebuild)
    SSH_OUT["box-b"] = wsl("on"); fresh(); set_box_b_online(False)
    x0 = at(0); x1 = at(600); x2 = at(1200)
    check("14g: a runner offline for good, snapshots rebuilt only every 10 minutes: first read restarting, the next (600 s later) a fault with the first-seen time carried", (x0["kind"], x1["kind"], x2["kind"], x1["off_since"], x2["off_since"]) == ("restarting", "fault", "fault", T0, T0), (x0, x1, x2))
    fresh(); set_box_b_online(False); x = [at(t) for t in (0, 600, 1200, 1800, 2400, 3000)][-1]
    check("14g: …and stays a fault over the next rebuilds, 10 minutes apart", (x["kind"], x["off_since"]) == ("fault", T0), x)
    # h: a machine whose only runners are restarting reads as online, not 'no runner online'
    SSH_OUT["box-b"] = wsl("on"); fresh(); set_box_b_online(False); snap = R.snapshot(force=True); mine = [r for r in snap["runners"] if r["box"] == "box-b"]
    check("14h: the fixture: all of box-b's runners are offline and restarting", mine and all(r["state"] == "offline" and r["kind"] == "restarting" for r in mine), mine)
    st = R2._machine_state(mine, snap["switch"]["box-b"])
    check("14h: the machine's state line counts them online ('on · 0 of 2 busy', not 'no runner online')", "no runner online" not in st[0] and "0 of 2 busy" in st[0], st)
    fresh(); set_box_b_online(False); snap = aged(); mine = [r for r in snap["runners"] if r["box"] == "box-b"]
    check("14h: and once they are faults the line says 'no runner online' again", "no runner online" in R2._machine_state(mine, snap["switch"]["box-b"])[0], R2._machine_state(mine, snap["switch"]["box-b"]))
    # a restart: the saved snapshot is hours old when the server comes back
    fresh(); clean_state(); R.PERSIST = True; set_box_b_online(False)
    at(0); R.reset(); R.restore()
    x = at(7200)
    check("14f/1: after a restart that took hours the saved mark is not carried: no instant fault", (x["kind"], x["off_since"]) == ("restarting", T0 + 7200), x)
finally:
    RUNNERS.clear(); RUNNERS.update(RUNNERS_G14); SSH_OUT.clear(); SSH_OUT.update(SSH_G14); clean_state(); fresh()


# ---- 15. runners are optional: no [runners] table, a table with no repo, or a clean read of no runner = the feature is off, silently (no error, no empty block, no read)
# The same fake GitHub, ssh and clock as above. The config is the module's own dict (R._cfg.CFG), put back at the end.
NOT_USED_OFF = "This board does not use self-hosted CI runners."
NOT_USED_ZERO = "GitHub lists no self-hosted CI runners for the repositories this board follows."
CFG_RUNNERS_15 = copy.deepcopy(R._cfg.CFG.get("runners"))
OLD_FAULT = {"version": 1, "ts": T0 - 3000, "errors": {}, "failed": [], "switch": {"box-a": {"ok": True, "mode": "on", "held": [], "gate": [], "since": 0}},
             "runners": [{"name": "box-a-old", "repo": "salamander", "box": "box-a", "state": "offline", "job": None, "kind": "fault", "reason": "offline, and the CI switch did not disable it",
                          "disabled": False, "stopping": False, "off_since": T0 - 2900}]}      # what an earlier config with runners left in <state>/runners-snapshot.json
def clean_page(h, what):
    """The page, the JSON html or the panel carries no fault, no error line, no card, no table and no machine row."""
    bad = [w for w in ("rerr", "GitHub error", "rcard", "<table", "rtab", "box-a", "box-b", "box-c", "Disable", "Enable", "offline", "fault", "Traceback", "unknown") if w in h]
    check(f"{what}: no error line, no count card, no table, no machine row, no button, no offline word", not bad, bad)
def off_is_silent(label, line):
    """Everything the feature touches, with the feature off: nothing is read, started or drawn."""
    fresh(); clean_state(); R._get = fake_get; R.AUTOSTART = True; R.PERSIST = True; CALLS.clear(); SSH.clear(); OWNER_CALLS.clear()
    (T / "state").mkdir(parents=True, exist_ok=True); (T / "state" / R.SNAP_FILE).write_text(json.dumps(OLD_FAULT))
    try:
        check(f"{label}: enabled() is False and the saved snapshot of an earlier config is not taken back", R.enabled() is False and R.restore() is False and R._CACHE.get("snap") is None)
        t0 = time.monotonic(); sv = R.serve(); took = time.monotonic() - t0
        check(f"{label}: serve() answers at once with no runner, no error, not pending, not refreshing, and starts no thread", took < 0.15 and sv["runners"] == [] and sv["errors"] == {} and sv["failed"] == []
              and not sv.get("pending") and not sv["refreshing"] and R._SERVE["thread"] is None, sv)
        check(f"{label}: peek() is None and starts no rebuild even with AUTOSTART on", R.peek() is None and R._PEEK["thread"] is None)
        h = R2.table_html(sv, CLOCK[0])
        check(f"{label}: the page body is the one plain line", h == f'<p class="sub rnotused" role="status">{line}</p>', h)
        clean_page(h, f"{label}: page body")
        d = R2.data(sv, CLOCK[0])
        check(f"{label}: the JSON has zero counts, no error, no runner, not pending, and the same line as its html", d["counts"] == {"runners": 0, "running": 0, "idle": 0, "disabled": 0, "offline": 0}
              and d["errors"] == {} and d["runners"] == [] and d["pending"] is False and d["html"] == h, d)
        bh = board_html(); sec = runners_section(bh)
        check(f"{label}: the side panel's Runners section is one plain line, 'not used on this board': no card, no link to the page, no 'not read yet'", "not used on this board" in sec and sec.count('class="mnote"') == 1
              and not cards(sec) and "<a " not in sec and "not read yet" not in sec and 'href="/runners"' not in bh, sec[:300])
        order = ["projects-panel", "audit-panel", "runners", "anchorhub", "machines"]
        moved = ui_render.apply_panel_order(bh, order)
        check(f"{label}: a saved panel order still applies (five markers, in that order)", re.findall(r"<!--ps:([a-z0-9-]+)-->", moved) == order, re.findall(r"<!--ps:([a-z0-9-]+)-->", moved))
        check(f"{label}: no GitHub call, no ssh, no thread, and the saved file is left as it was", CALLS == [] and OWNER_CALLS == [] and SSH == [] and R._PEEK["thread"] is None
              and (T / "state" / R.SNAP_FILE).read_text() == json.dumps(OLD_FAULT), (CALLS, SSH))
        with TestClient(server.mcp.http_app()) as c:
            r = c.get("/runners"); j = c.get("/runners.json")
            body = r.text.split('id="rn-body"', 1)[1].split("</main>", 1)[0] if 'id="rn-body"' in r.text else ""
            check(f"{label}: GET /runners is a 200 page with the plain line, no subtitle about machines, no error", r.status_code == 200 and line in body and "GitHub Actions runners on each machine" not in r.text
                  and 'role="alert"' not in body, r.status_code)
            clean_page(body, f"{label}: /runners body")
            jd = j.json()
            check(f"{label}: GET /runners.json is a 200 with zero counts and no error", j.status_code == 200 and jd["errors"] == {} and jd["counts"]["runners"] == 0 and line in jd["html"] and jd["pending"] is False, (j.status_code, jd))
            check(f"{label}: …and the routes made no GitHub call and no ssh", CALLS == [] and SSH == [], (CALLS, SSH))
            hp = c.get("/")
            check(f"{label}: the board's home still renders (200) with the plain Runners line and no card", hp.status_code == 200 and "not used on this board" in runners_section(hp.text) and not cards(runners_section(hp.text))
                  and 'id="machines"' in hp.text, hp.status_code)
    finally:
        R.AUTOSTART = False; clean_state(); fresh()
try:
    # 15a. no [runners] table at all
    R._cfg.CFG.pop("runners", None)
    off_is_silent("15a no [runners] table", NOT_USED_OFF)
    # 15b. the table is there (the live shape: switch script, state dir, gate file, machines) but lists no repo
    R._cfg.CFG["runners"] = {**copy.deepcopy(CFG_RUNNERS_15), "repos": [], "switch_script": "~/ci-switch.sh", "state_dir": "~/.config/ci", "gate_file": "/var/lib/ci/halted"}
    off_is_silent("15b [runners] with repos = []", NOT_USED_OFF)
    check("15b: …the buttons do not come back either (no machine row to put them on)", "mact" not in R2.table_html(R.serve(), CLOCK[0], token=lambda b: "t"))
    # 15c. repos listed, GitHub lists no runner and no error: the same plain line (its own words), no section, no cards
    R._cfg.CFG["runners"] = copy.deepcopy(CFG_RUNNERS_15)
    saved_runners = copy.deepcopy(RUNNERS); RUNNERS["salamander"] = []; RUNNERS["stackshot"] = []
    try:
        fresh(); clean_state(); R._get = fake_get; R.AUTOSTART = False; setfiles(mode="on\n", hold="", gate="")
        check("15c: enabled() is True with repos listed", R.enabled() is True)
        snap = R.snapshot(force=True)
        check("15c: a clean read of zero runners: no error, no failed list, unused()", snap["runners"] == [] and snap["errors"] == {} and snap["failed"] == [] and R.unused(snap), snap)
        h = R2.table_html(R.serve(), CLOCK[0])
        check("15c: the page body is the plain line (its own words), no cards, no table, no machine row", h == f'<p class="sub rnotused" role="status">{NOT_USED_ZERO}</p>', h)
        clean_page(h, "15c: page body")
        R.reset(); R._CACHE["snap"] = snap
        bh = board_html(); sec = runners_section(bh)
        check("15c: the side panel's Runners section is one plain line, 'no self-hosted runners': no card, no link, no per-machine 'no runners' line", "no self-hosted runners" in sec and sec.count('class="mnote"') == 1
              and not cards(sec) and "<a " not in sec and "box-a" not in sec, sec[:300])
        d = R2.data(R.serve(), CLOCK[0])
        check("15c: the JSON: zero counts, no error, the plain line", d["counts"]["runners"] == 0 and d["errors"] == {} and NOT_USED_ZERO in d["html"], d)
        check("15c: the placeholder before the first read is not 'unused'", R.unused({"ts": 0, "errors": {}, "failed": [], "runners": [], "pending": True}) is False)
        # the saved snapshot of an earlier config with a fault runner is replaced by the first read, not kept
        fresh(); clean_state(); R.PERSIST = True; (T / "state").mkdir(parents=True, exist_ok=True); (T / "state" / R.SNAP_FILE).write_text(json.dumps(OLD_FAULT))
        check("15c: a saved snapshot from an earlier config is taken back while repos are listed", R.restore() is True)
        R.serve(); settle()
        sv = R.serve()
        check("15c: …and the first rebuild replaces it: no runner, no fault, the plain line", sv["runners"] == [] and R2.table_html(sv, CLOCK[0]) == f'<p class="sub rnotused" role="status">{NOT_USED_ZERO}</p>', sv["runners"])
        # a read that FAILED is not hidden as 'unused': the error is shown
        fresh(); clean_state(); BROKEN.update({"salamander", "stackshot"})
        snap = R.snapshot(force=True); BROKEN.clear()
        h = R2.table_html(snap, CLOCK[0])
        check("15c: both runner lists failing is an error, not 'unused': the error line is drawn and the plain line is not", R.unused(snap) is False and "GitHub error: salamander: GitHub answered 502" in h and NOT_USED_ZERO not in h, h[:300])
    finally:
        RUNNERS.clear(); RUNNERS.update(saved_runners); fresh(); clean_state()
    # 15d. runners listed: nothing changes (the cards, the table, the panel section and the subtitle are all there)
    fresh(); clean_state(); R._get = fake_get; setfiles(mode="on\n", hold="", gate=""); SSH_OUT.update({"box-b": wsl("off"), "box-c": wsl("on", "salamander")})
    snap = R.snapshot(force=True); R._CACHE["snap"] = snap
    h = R2.table_html(R.serve(), CLOCK[0])
    check("15d: with runners, the page body is the cards and the table as before (ten runners, five cards, no plain line)", h.count('<li class="rn ') == 10 and h.count('<div class="rcard ') == 5 and "<table" in h
          and "rnotused" not in h and R.enabled() is True and not R.unused(snap), h[:200])
    pg = R2.page_html(ui_render.Board(str(T / "store")), snap)
    check("15d: …with its subtitle, and the panel keeps its Runners section with a card per machine", "GitHub Actions runners on each machine" in pg and "rnotused" not in pg and len(cards(runners_section(board_html()))) >= 3,
          len(cards(runners_section(board_html()))))
finally:
    if CFG_RUNNERS_15 is None: R._cfg.CFG.pop("runners", None)
    else: R._cfg.CFG["runners"] = CFG_RUNNERS_15
    R.AUTOSTART = False; clean_state(); fresh()


print(("ok" if not fails else "FAILED") + f": runners scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
