"""Scenario test for `suitemap.py fetch` and for `select` with no --map (Mon Nov 23rd 2026) — a throwaway git repo of two tiny suites and a fake `gh` on PATH; no network, no token.

A test runner's copy of the tree has no map of its own: CI restores it from the Actions cache, which only a run can read, and the artifact main's run publishes needs a token to download.
`fetch` is run where the token is, before the tree is sent: it downloads the map of main's newest successful run at or before HEAD into `.suitemap-ci/map.json` (a folder git does not
ignore, so the copy carries it), and `select` with no --map reads it there. This suite checks that: fetch writes the map of the right run (never a run of a commit HEAD does not descend
from, nor another workflow's), tries the next older run when an artifact is gone, refuses a corrupt, old-format or hash-less map and a refused `gh`, and leaves no file behind on a failure;
select uses the fetched map and names the main commit it is of; with no map, a corrupt or old-format one, or one whose commit the checkout lacks, it prints `all` and says in one line that
the pick is wider than CI's; and the folder stays unignored and uncommitted in this checkout.

    tests/run-suite suitemap_fetch        → exit 0 / 1"""
import json, os, pathlib, shutil, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__))
import _scratch
tmp = _scratch.mkdtemp(prefix="suitemapfetch-"); T = pathlib.Path(tmp)
R = T / "repo"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

def git(*a, repo=None): return subprocess.run(["git", "-C", str(repo or R), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout
def write(rel, text): p = R / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")
def commit(msg): git("add", "-A"); git("commit", "-qm", msg); return git("rev-parse", "HEAD").strip()

R.mkdir()
git("init", "-q", "-b", "main")
git("remote", "add", "origin", "git@github.com:owner/name.git")   # never fetched: GIT_SSH_COMMAND below is false
write("tests/suitemap.py", '"""stand-in for the harness file of the throwaway repo"""\nFORMAT = 1\n')
write("tests/a_scenario.py", "print('a')\n")
write("tests/b_scenario.py", "print('b')\n")
A = commit("base")
write("tests/a_scenario.py", "print('a changed')\n")
B = commit("change a")
FAR = "f" * 40   # a main commit HEAD does not descend from (main moved on)

def a_map(commit_=A, fmt=1): return {"format": fmt, "commit": commit_, "strace": True, "measured": "x", "suites": {"a": {"ok": True, "seconds": 2}, "b": {"ok": True, "seconds": 3}}}
MAPS = T / "maps"; MAPS.mkdir()
def put_map(name, obj): p = MAPS / name; p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8"); return p
GOOD = put_map("good.json", a_map())

# the fake gh: `gh api …` lists the runs in $FAKE_GH_RUNS, `gh run download ID … -D DIR` copies $FAKE_GH_MAP to DIR/map.json (an id in $FAKE_GH_GONE has no artifact), each call is logged
BIN = T / "bin"; BIN.mkdir()
(BIN / "gh").write_text(f"""#!{sys.executable}
import os, shutil, sys
a = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f: f.write(" ".join(a) + "\\n")
if os.environ.get("FAKE_GH_MODE") == "denied":
    sys.stderr.write("gh: HTTP 401: Bad credentials\\n"); sys.exit(1)
if a[0] == "api":
    print(os.environ["FAKE_GH_RUNS"])
elif a[:2] == ["run", "download"]:
    if a[2] in os.environ.get("FAKE_GH_GONE", "").split(","):
        sys.stderr.write("no valid artifacts found to download\\n"); sys.exit(1)
    shutil.copy(os.environ["FAKE_GH_MAP"], os.path.join(a[a.index("-D") + 1], "map.json"))
""", encoding="utf-8")
os.chmod(BIN / "gh", 0o755)
GITONLY = T / "gitonly"; GITONLY.mkdir()
(GITONLY / "git").symlink_to(shutil.which("git"))   # a PATH with git and no gh
LOG = T / "gh.log"

def runs(*rows): return json.dumps({"workflow_runs": [{"id": i, "head_sha": s, "path": p, "status": "completed", "conclusion": "success", "created_at": f"2026-11-2{n}T00:00:00Z"} for n, (i, s, p) in enumerate(rows)]})
WF = ".github/workflows/tests.yml"
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "SUITEMAP_", "GITHUB_", "GH_", "STACKSHOT_TEST"))}
ENV.update(SUITEMAP_ROOT=str(R), SUITEMAP_CACHE_DIR=str(T / "cache"), STACKSHOT_TEST_LAUNCHER="", GIT_SSH_COMMAND="false", GIT_TERMINAL_PROMPT="0", HOME=str(T / "home"),
           FAKE_GH_LOG=str(LOG), PATH=f"{BIN}:{os.environ['PATH']}")
MAPDIR = R / ".suitemap-ci"; MAPFILE = MAPDIR / "map.json"
def tool(*a, **env): return subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), *a], capture_output=True, text=True, env={**ENV, **env}, cwd=str(R))
def calls(): return LOG.read_text().splitlines() if LOG.exists() else []
def fresh():
    shutil.rmtree(MAPDIR, ignore_errors=True); LOG.unlink(missing_ok=True)
def leftovers(): return sorted(p.name for p in MAPDIR.iterdir()) if MAPDIR.exists() else None

# ---- fetch
RUNS = runs((9, B, ".github/workflows/other.yml"), (8, FAR, WF), (7, A, WF))   # newest first: another workflow's run of HEAD itself, a commit HEAD does not descend from, then base A
fresh(); r = tool("fetch", FAKE_GH_RUNS=RUNS, FAKE_GH_MAP=str(GOOD))
dl = [c for c in calls() if c.startswith("run download")]
check("fetch: writes the map of the newest successful run of the tests workflow at or before HEAD, and says which main commit and run it is of",
      r.returncode == 0 and MAPFILE.exists() and MAPFILE.read_bytes() == GOOD.read_bytes() and A[:12] in r.stdout and "run 7" in r.stdout and ".suitemap-ci/map.json" in r.stdout and r.stdout.count("\n") == 1, (r.returncode, r.stdout, r.stderr))
check("fetch: it downloads the `suitemap` artifact of that run alone, from the repository `origin` names, never a run of a commit HEAD does not descend from nor of another workflow",
      len(dl) == 1 and dl[0].startswith("run download 7 --repo owner/name -n suitemap -D "), dl)
check("fetch: it asks for successful pushes to main, and the folder holds the map alone (its download folder is gone)",
      any("branch=main" in c and "event=push" in c and "status=success" in c for c in calls()) and leftovers() == ["map.json"], (calls(), leftovers()))

fresh(); r = tool("fetch", "--sha", A[:10], FAKE_GH_RUNS=runs((8, B, WF), (7, A, WF)), FAKE_GH_MAP=str(GOOD))
check("fetch --sha: the run of that commit, not the newest one at or before HEAD", r.returncode == 0 and [c.split()[2] for c in calls() if c.startswith("run download")] == ["7"], (r.returncode, calls()))

fresh(); r = tool("fetch", FAKE_GH_RUNS=runs((8, B, WF), (7, A, WF)), FAKE_GH_MAP=str(GOOD), FAKE_GH_GONE="8")
check("fetch: a run whose artifact is gone (expired) is skipped for the next older run at or before HEAD",
      r.returncode == 0 and [c.split()[2] for c in calls() if c.startswith("run download")] == ["8", "7"] and MAPFILE.exists() and leftovers() == ["map.json"], (r.returncode, r.stderr, calls()))

fresh(); r = tool("fetch", FAKE_GH_RUNS=runs((8, FAR, WF)), FAKE_GH_MAP=str(GOOD))
check("fetch: no successful run at or before HEAD is a failure with a line, and nothing is downloaded or written",
      r.returncode == 1 and "no successful run" in r.stderr and not [c for c in calls() if c.startswith("run download")] and not MAPFILE.exists(), (r.returncode, r.stderr, calls()))

fresh(); r = tool("fetch", FAKE_GH_MODE="denied", FAKE_GH_RUNS="{}")
check("fetch: a gh that is refused (no token) fails with gh's own words and what to do, and writes nothing",
      r.returncode == 1 and "401" in r.stderr and "token" in r.stderr and not MAPFILE.exists(), (r.returncode, r.stderr))

fresh(); r = tool("fetch", PATH=str(GITONLY), FAKE_GH_RUNS=RUNS)
check("fetch: with no gh on the machine it says so and writes nothing", r.returncode == 1 and "gh cannot be run" in r.stderr and not MAPFILE.exists(), (r.returncode, r.stderr))

for what, body in (("a corrupt artifact", "{not json"), ("an old-format artifact", a_map(fmt=0)), ("an artifact with no suites", {"format": 1, "commit": A}), ("an artifact whose commit is no hash", a_map(commit_="main"))):
    fresh(); bad = put_map("bad.json", body); r = tool("fetch", FAKE_GH_RUNS=runs((7, A, WF)), FAKE_GH_MAP=str(bad))
    check(f"fetch: {what} is refused with the reason, and nothing is written", r.returncode == 1 and "refused" in r.stderr and not MAPFILE.exists() and leftovers() == [], (r.returncode, r.stderr, leftovers()))

fresh(); r = tool("fetch", FAKE_GH_RUNS=runs((8, B, WF), (7, A, WF)), FAKE_GH_MAP=str(put_map("bad.json", "{not json")))
check("fetch: a refused artifact of the newest run is not the end: the next older run is tried, and the failure lists each run it tried",
      r.returncode == 1 and r.stderr.count("run 8") == 1 and r.stderr.count("run 7") == 1 and len([c for c in calls() if c.startswith("run download")]) == 2, (r.returncode, r.stderr))

# ---- select with no --map
fresh(); tool("fetch", FAKE_GH_RUNS=RUNS, FAKE_GH_MAP=str(GOOD))
r = tool("select")
check("select: with no --map it reads the fetched map and picks by it (only the suite the change touched, not `all`)", r.returncode == 0 and r.stdout.split() == ["a"], (r.returncode, r.stdout, r.stderr))
check("select: it names the main commit the map is of and how far HEAD is from it", f"CI map of main {A[:12]}" in r.stderr and "1 commit(s) before" in r.stderr, r.stderr)
check("select: a pick by a map says nothing about being wider than CI's", "wider" not in r.stderr, r.stderr)
r2 = tool("select", "--map", str(MAPFILE))
check("select: --map with the same file gives the same pick (CI's way is unchanged)", r2.returncode == 0 and r2.stdout == r.stdout, (r2.stdout, r2.stderr))

shutil.rmtree(MAPDIR); r = tool("select")
check("select: with no map here it prints `all`, exits 0, and says in one line that this is wider than CI's pick and to run fetch first",
      r.returncode == 0 and r.stdout.split() == ["all"] and sum("wider than CI" in l for l in r.stderr.splitlines()) == 1 and "tests/suitemap.py fetch" in r.stderr and "no CI map here" in r.stderr, (r.returncode, r.stdout, r.stderr))
r = tool("select", "--map", str(T / "none.json"))
check("select: an explicit --map that is missing says it is wider than CI's pick, with no hint to fetch (CI restores that file itself)",
      r.stdout.split() == ["all"] and "wider than CI" in r.stderr and "fetch" not in r.stderr, (r.stdout, r.stderr))

for what, body, word in (("a corrupt map", "{not json", "JSON"), ("an old-format map", a_map(fmt=0), "format 0"), ("a map with no suites table", {"format": 1, "commit": A}, "no commit or no suites")):
    MAPDIR.mkdir(exist_ok=True); MAPFILE.write_text(body if isinstance(body, str) else json.dumps(body)); r = tool("select")
    check(f"select: {what} is refused with the reason, nothing of it is used, and the pick (`all`) is said to be wider than CI's",
          r.returncode == 0 and r.stdout.split() == ["all"] and "refused" in r.stderr and word in r.stderr and "wider than CI" in r.stderr, (r.returncode, r.stdout, r.stderr))

MAPFILE.write_text(json.dumps(a_map(commit_="1" * 40))); r = tool("select")
check("select: a map of a commit this checkout lacks (a copy sent without history) picks `all` and says so in one line",
      r.stdout.split() == ["all"] and "does not hold" in r.stderr and "wider than CI" in r.stderr, (r.stdout, r.stderr))

# ---- the folder is the one a test runner's copy carries, and never a commit's
REAL = os.path.dirname(SCR)
ign = lambda p: subprocess.run(["git", "-C", REAL, "check-ignore", "-q", p]).returncode == 0
check("the fetched map's folder is not ignored by git (a test runner's copy carries only unignored files), CI's own .suitemap/ still is",
      not ign(".suitemap-ci/map.json") and ign(".suitemap/map.json"))
tracked = subprocess.run(["git", "-C", REAL, "ls-files", "--", ".suitemap-ci"], capture_output=True, text=True).stdout.split()
check("no commit holds a file under .suitemap-ci/ (a fetched map is never committed; checked in CI, where the checkout is the change's own)", not tracked or not os.environ.get("GITHUB_ACTIONS"), tracked)

print(("ok" if not fails else "FAILED") + f": suitemap fetch scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
