"""Scenario test for tools/mq_replay.py `build-cases`, the step that turns past release logs and git history into the merge queue's replay cases (tests/mq_replay/cases.json).

No network and no real GitHub: a throwaway git world in a scratch folder (a "work" checkout with a small dated history, a bare "origin" that serves any sha, a second
clone that lacks one commit) and fixture release logs in six example shapes (with the fixture's shas): a merged PR on the fast path (the
fast-ok ledger line, a covering main run, a suite that failed only when measured), a merged PR on the old path (no ledger line: the merge is found in main's history), a refusal
at checks with a pending check, an attempt that ends `still pending` followed by a refusal on a conflict that names its files, a refusal on `UNKNOWN` (no queue equivalent), and a log
that names no head at all.

Covers: a merged PR's base is M^1 and its head is M^2 with release.sh's `Merge branch 'main' into` commit peeled off (the head the author pushed, not the merge); the selection can ask
for the head the attempt started with instead; M, M's tree, main's run id, the covering commit, the flaky suite, branch and owner (from the `Merge pull request #N from` commit); the
PR check fixture; a refusal's base is main's first-parent tip before the FAILED line's time (not main's tip, not the head's parent), its head the `(head sha)` of its attempt, the
expected queue reason from the log's words (a check failure keeps its names and states; a conflict names its files), and the merge-tree facts (clean, conflicting files, tree equal to M's);
the second attempt of a log is the one selected; a group's base is the tip the old path first saw (or the selection's override), each PR keeping its own base; a head with no sha
in the log, a sha the checkout does not know, a sha the remote does not serve, a refusal with no queue equivalent, a base before the `queue/**` trigger, a missing log and an attempt that
does not exist are dropped with their reasons, printed and recorded, and `--strict` makes them an exit 1; the checkout is read only (refs, HEAD and object count unchanged) and the
scratch folder is gone after a run and after a SIGTERM during a fetch; `--check` accepts what build wrote, refuses a changed head, a changed tree, a check state outside
pass|fail|pending|cancel and a missing sha (a warning with --allow-missing), writes nothing, and with --verify fetch gets a sha the checkout lacks from the remote; the
checked-in tests/mq_replay/cases.json has the 20 cases c01 to c20 with full shas and valid states, and the built-in selection is the same 20.

    tests/run-suite mq_replay        → exit 0 / 1"""
import importlib.util, json, os, pathlib, shutil, signal, subprocess, sys, time
import _scratch
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
TOOL = os.path.join(STACK, "tools", "mq_replay.py")
CASES_REAL = os.path.join(SCR, "mq_replay", "cases.json")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ROOT = pathlib.Path(_scratch.mkdtemp(prefix="mqreplay-"))
HOME = ROOT / "home"; HOME.mkdir()
TOOL_TMP = ROOT / "tool-tmp"; TOOL_TMP.mkdir()
REAL_GIT = shutil.which("git")
BIN = ROOT / "bin"; BIN.mkdir()
(BIN / "git").write_text(f'#!/bin/sh\ncase " $* " in *" fetch "*) if [ -n "$K1_HANG" ]; then : > "$K1_HANG"; exec sleep 25; fi;; esac\nexec {REAL_GIT} "$@"\n')
(BIN / "git").chmod(0o755)
BASE_ENV = {"HOME": str(HOME), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "TMPDIR": str(TOOL_TMP)}
ENV = {**BASE_ENV, "PATH": f"{BIN}:{os.environ['PATH']}"}
AUTHOR = ["-c", "user.name=Test Author", "-c", "user.email=author@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

def g(cwd, *args, date=None, ok=True):
    env = {**BASE_ENV, "PATH": os.environ["PATH"]}
    if date: env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    r = subprocess.run([REAL_GIT, "-C", str(cwd), *AUTHOR, *args], capture_output=True, text=True, env=env, timeout=60)
    if ok and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} in {cwd}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()

WC = ROOT / "work"; ORIGIN = ROOT / "origin.git"
def commit(path, content, msg, date):
    (WC / path).write_text(content); g(WC, "add", path); g(WC, "commit", "-q", "-m", msg, date=date); return g(WC, "rev-parse", "HEAD")
def on(branch, start=None):
    if start: g(WC, "checkout", "-q", "-b", branch, start)
    else: g(WC, "checkout", "-q", branch)
def merge(branch, msg, date):
    g(WC, "merge", "-q", "--no-ff", "-m", msg, branch, date=date); return g(WC, "rev-parse", "HEAD")

# ---------------------------------------------------------------- the world
WC.mkdir(); g(WC, "init", "-q", "-b", "main")
H = {}
H["P0"] = commit("base.txt", "0\n", "init", "2026-06-02T00:00:00Z")
on("pr14", "main"); H["h14"] = commit("f14.txt", "1\n", "old pr", "2026-06-02T01:00:00Z"); on("main")
H["M14"] = merge("pr14", "Merge pull request #14 from acme-org/old-pr", "2026-06-02T02:00:00Z")
H["TRIG"] = commit("trigger.txt", "queue/**\n", "ci: queue/** runs the workflow", "2026-06-03T00:00:00Z")
H["A1"] = commit("a.txt", "one\n", "a1", "2026-06-03T01:00:00Z")
on("pr10", "main"); H["hq"] = commit("f10.txt", "1\n", "pr10 first", "2026-06-03T01:30:00Z"); H["h1"] = commit("f10.txt", "2\n", "pr10 second", "2026-06-03T02:00:00Z")
on("main"); H["A2"] = commit("other.txt", "x\n", "a2", "2026-06-03T03:00:00Z")
on("pr10"); H["mrg"] = merge("main", "Merge branch 'main' into feat-x", "2026-06-03T03:30:00Z")
on("main"); H["M10"] = merge("pr10", "Merge pull request #10 from acme-org/feat-x", "2026-06-03T05:00:00Z")
H["B1"] = commit("b1.txt", "b\n", "b1", "2026-06-03T08:00:00Z")
on("prX", H["A1"]); H["hX"] = commit("fx.txt", "x\n", "refused head", "2026-06-03T09:30:00Z")
on("pr12", H["A1"]); H["hc"] = commit("a.txt", "branch change\n", "conflicting head", "2026-06-03T09:00:00Z")
on("main"); H["B2"] = commit("a.txt", "main change\n", "b2", "2026-06-03T12:00:00Z")
on("pr20", "main"); H["hg20"] = commit("f20.txt", "1\n", "pr20", "2026-06-03T13:00:00Z")
on("pr21", "main"); H["hg21"] = commit("f21.txt", "1\n", "pr21", "2026-06-03T13:10:00Z")
on("main"); H["M20"] = merge("pr20", "Merge pull request #20 from acme-org/g20", "2026-06-03T14:00:00Z")
H["M21"] = merge("pr21", "Merge pull request #21 from acme-org/g21", "2026-06-03T14:30:00Z")
on("prL", "main"); H["hL"] = commit("fl.txt", "l\n", "local only head", "2026-06-03T15:00:00Z"); on("main")
g(ROOT, "init", "-q", "--bare", "-b", "main", str(ORIGIN)); g(ORIGIN, "config", "uploadpack.allowAnySHA1InWant", "true")
g(WC, "remote", "add", "origin", f"file://{ORIGIN}")
g(WC, "push", "-q", "origin", "main", f"{H['hX']}:refs/heads/tmp-x", f"{H['hc']}:refs/heads/tmp-c", f"{H['hq']}:refs/heads/tmp-q")
for t in ("tmp-x", "tmp-c", "tmp-q"): g(ORIGIN, "update-ref", "-d", f"refs/heads/{t}")   # the commits stay on origin, on no branch (a closed PR's head)
g(WC, "fetch", "-q", "origin")
g(WC, "checkout", "-q", "main")
def s7(k): return H[k][:7]
TRIG = H["TRIG"]

# ---------------------------------------------------------------- the logs (example shapes)
LOGS = ROOT / "logs"; LOGS.mkdir()
def start(pr, ts, head, title="Fixture change"):
    s = f"{ts} release of PR #{pr} starts in /home/user/stackshot (howardpark-ai/stackshot)\n"
    if head: s += f"{ts} PR #{pr}: {title} (head {head})\n"
    return s + f"{ts} merge queue (shadow): PR #{pr} queued (mode shadow: groups are built and tested, nothing is merged; driver running)\n"
def merged_fast(pr, ts, M, prev, branch, run, cov, flaky=None):
    s = (f"{ts[:11]}11:00:00Z checks pass\n{ts[:11]}11:00:02Z deploy lock taken\n{ts[:11]}11:00:09Z merged\n{ts[:11]}11:00:11Z deleted the head branch {branch}\n"
         f"{ts[:11]}11:00:14Z recorded the merge {M[:7]} in the fast-ok ledger (the PR's checks passed on a head that contained main's tip): a later release may count the live checkout as at the tip while it is not deployed\n"
         f"deploying {prev[:7]}..{M[:7]}:\n  {M[:7]} Merge pull request #{pr} from acme-org/{branch}\nrestarts: stackshot.service\n  checkout /home/user/stackshot · user alex\n"
         f"{ts[:11]}11:00:37Z done: {M[:7]}, restarted stackshot.service\n"
         f"{ts[:11]}12:45:12Z main's tests passed on {M[:7]} (run {run}, on {cov[:7]}, which contains {M[:7]})\n")
    if flaky: s += f"{ts[:11]}12:45:12Z main's run: {flaky} failed only when measured, then passed plainly (flaky?): the report goes to the keeper\n"
    return s
def put(pr, text): (LOGS / f"pr-{pr}.log").write_text(text)

put(10, start(10, "2026-06-03T04:00:00Z", s7("hq")) + merged_fast(10, "2026-06-03T04:00:00Z", H["M10"], H["A2"], "feat-x", 9000006, H["B1"], "release, pilot"))
put(14, start(14, "2026-06-02T01:30:00Z", s7("h14")) + merged_fast(14, "2026-06-02T01:30:00Z", H["M14"], H["P0"], "old-pr", 41400000001, H["M14"]))
put(11, start(11, "2026-06-03T09:40:00Z", s7("hX"), "A refused change") + "2026-06-03T10:00:00Z FAILED at checks: a check failed: tool-text-model=fail, suites=pending\n")
put(12, start(12, "2026-06-03T08:30:00Z", s7("hc")) + "2026-06-03T08:50:00Z FAILED at checks: still pending after 50 min\n"
        + start(12, "2026-06-03T12:50:00Z", s7("hc")) + "2026-06-03T12:51:00Z checks pass\n2026-06-03T12:55:00Z update-branch round 1 of 3: main's tip " + s7("B2") + " is not in the PR head; merging main into the branch (a merge, no force push)\n"
        "2026-06-03T12:55:01Z update-branch: the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 2): merging main into " + s7("hq") + " in a temporary worktree\n"
        "2026-06-03T12:55:02Z update-branch: the snapshot is not regenerated: declined: the conflict is not only the snapshot: a.txt\n"
        "2026-06-03T13:00:00Z FAILED at update-branch: X Cannot update PR branch due to conflicts; the branch could not be brought up to date, nothing was merged (a conflict with main is for the PR's author to resolve)\n")
retest = lambda pr, ts, h, tip: f"{ts} retest needed for the PR head {h} on main's tip {s7(tip)}: main's side changes tests/tool_text.snapshot.json\n"
put(20, start(20, "2026-06-03T13:20:00Z", s7("hg20")) + retest(20, "2026-06-03T13:26:30Z", s7("hg20"), "B2") + merged_fast(20, "2026-06-03T13:20:00Z", H["M20"], H["B2"], "g20", 9000017, H["M21"]))
# the old path, no ledger line: the merge is found in main's history; main's run is the short form
put(21, start(21, "2026-06-03T13:21:00Z", s7("hg21")) + retest(21, "2026-06-03T13:25:07Z", s7("hg21"), "B1")
        + "2026-06-03T14:30:00Z merged\n2026-06-03T14:30:05Z deleted the head branch g21\n2026-06-03T15:10:00Z main's tests pass at " + s7("M21") + " (run 9000016)\n")
put(30, "2026-06-03T10:00:00Z release of PR #30 starts in /home/user/stackshot (howardpark-ai/stackshot)\n2026-06-03T10:20:00Z FAILED at checks: a check failed: suites=fail\n")
put(31, start(31, "2026-06-03T10:00:00Z", "deadbee") + "2026-06-03T10:20:00Z FAILED at checks: a check failed: suites=fail\n")
put(32, start(32, "2026-06-03T15:30:00Z", s7("hL")) + "2026-06-03T15:50:00Z FAILED at checks: a check failed: suites=fail\n")
# no `(head ...)` line at all: the head is the sha of `merging main into`
put(34, start(34, "2026-06-03T09:40:00Z", None) + "2026-06-03T09:45:00Z update-branch: the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 2): merging main into " + s7("hX") + " in a temporary worktree\n"
        "2026-06-03T10:00:00Z FAILED at checks: a check failed: suites=fail\n")
put(33, start(33, "2026-06-03T10:00:00Z", s7("hX")) + "2026-06-03T10:20:00Z FAILED at mergeable: GitHub says UNKNOWN (a conflict with main, or still computing)\n")

SELECTION = [
    {"id": "t-merged", "prs": [[10, 0]]},
    {"id": "t-queue", "prs": [[10, 0]], "head": "queue"},
    {"id": "t-refused", "prs": [[11, 0]]},
    {"id": "t-conflict", "prs": [[12, 1]]},
    {"id": "t-group", "prs": [[20, 0], [21, 0]]},
    {"id": "t-omit", "prs": [[20, 0], [21, 0]], "fixture": {"21": "omit"}, "group_base": s7("A2"), "note": "n"},
    {"id": "t-failalone", "prs": [[20, 0], [11, 0]], "fixture": {"11": "omit"}},
    {"id": "t-fallback", "prs": [[34, 0]]},
    {"id": "d-nosha", "prs": [[30, 0]]},
    {"id": "d-unknown", "prs": [[31, 0]]},
    {"id": "d-fetch", "prs": [[32, 0]]},
    {"id": "d-noequiv", "prs": [[33, 0]]},
    {"id": "d-pretrigger", "prs": [[14, 0]]},
    {"id": "d-nolog", "prs": [[99, 0]]},
    {"id": "d-attempt", "prs": [[10, 5]]},
]
SEL = ROOT / "selection.json"; SEL.write_text(json.dumps(SELECTION))

# ---------------------------------------------------------------- helpers
def run(*args, env=None, timeout=120, repo=WC):
    return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, env=env or ENV, timeout=timeout, cwd=str(ROOT))
def build(out, *extra, repo=WC):
    owner = [] if "--repo-owner" in extra else ["--repo-owner", "other-org"]    # the remote is a file path: the repository's owner cannot be read from it
    return run("build-cases", "--repo", str(repo), "--logdir", str(LOGS), "--out", str(out), "--selection", str(SEL), "--trigger", TRIG, "--remote", f"file://{ORIGIN}", *owner, *extra)
def snapshot(repo):
    return (g(repo, "for-each-ref"), g(repo, "rev-parse", "HEAD"), g(repo, "count-objects", "-v"), g(repo, "status", "--porcelain"))
def left_over(): return sorted(p.name for p in TOOL_TMP.iterdir())

before = snapshot(WC)
OUT = ROOT / "cases.json"
r = build(OUT)
after = snapshot(WC)
check("build-cases exits 0 with drops (no --strict)", r.returncode == 0, (r.returncode, r.stderr[-600:]))
check("the checkout is read only: refs, HEAD, loose object count and files unchanged", before == after, (before, after))
check("no scratch folder is left after a run", left_over() == [], left_over())
doc = json.loads(OUT.read_text())
cases = {c["id"]: c for c in doc["cases"]}
dropped = {d["id"]: d["reason"] for d in doc["dropped"]}
check("format and trigger recorded", doc["format"] == 1 and doc["trigger"] == TRIG)
check("built the 8 buildable cases and dropped the 7 others", sorted(cases) == sorted(["t-merged", "t-queue", "t-refused", "t-conflict", "t-group", "t-omit", "t-failalone", "t-fallback"]) and len(dropped) == 7, (sorted(cases), sorted(dropped)))

c = cases.get("t-merged", {"prs": [{}]}); p = c["prs"][0]
check("merged: base is M^1", p.get("base") == H["A2"] and c.get("base") == H["A2"], p.get("base"))
check("merged: head is M^2 with release.sh's `Merge branch 'main' into` commit peeled off (the author's last push, not the merge)", p.get("head") == H["h1"] and p.get("peeled") == 1, (p.get("head"), p.get("peeled")))
check("merged: the log's head (the one the attempt started with) is recorded beside it", p.get("queue_head") == H["hq"], p.get("queue_head"))
check("merged: M, M's tree and expected_tree", p.get("merge") == H["M10"] and p.get("merge_tree") == g(WC, "rev-parse", H["M10"] + "^{tree}") == c.get("expected_tree"), p.get("merge_tree"))
check("merged: kind and outcome", c.get("kind") == "merged" and c.get("known_outcome") == "merged" and p.get("known_outcome") == "merged" and "group_max" not in c)
check("merged: main's run id, the covering commit, the flaky suites", p.get("main_run") == {"result": "pass", "run": 9000006, "on": H["B1"], "flaky": ["release", "pilot"]}, p.get("main_run"))
check("merged: branch and owner from the `Merge pull request #N from` commit; the check fixture", (p.get("owner"), p.get("branch"), p.get("checks")) == ("acme-org", "feat-x", {"suites": "pass"}), (p.get("owner"), p.get("branch"), p.get("checks")))
check("merged: merge-tree of head into base is clean and has M's tree", p.get("offline_merge") == {"clean": True, "conflicts": [], "tree_equals_merge": True}, p.get("offline_merge"))
check("selection `head: queue` takes the head the attempt started with", cases.get("t-queue", {"prs": [{}]})["prs"][0].get("head") == H["hq"])

c = cases.get("t-refused", {"prs": [{}]}); p = c["prs"][0]
check("refused: base is main's first-parent tip before the FAILED line's time (not main's tip, not the head's parent)", p.get("base") == H["B1"] and p.get("base") not in (g(WC, "rev-parse", "origin/main"), H["A1"]), p.get("base"))
check("refused: head is the attempt's `(head sha)`, full length, found on the remote by sha", p.get("head") == H["hX"], p.get("head"))
check("refused: outcome, stage, the log's words, refusal time", (p.get("known_outcome"), p.get("stage"), p.get("reason"), p.get("refused_at")) == ("refused", "checks", "a check failed: tool-text-model=fail, suites=pending", "2026-06-03T10:00:00Z"), p)
check("refused: expected queue reason keeps the check names and states; the fixture is exactly those states", p.get("expected_reason") == "refused: a check failed: tool-text-model=fail, suites=pending" and p.get("checks") == {"tool-text-model": "fail", "suites": "pending"}, (p.get("expected_reason"), p.get("checks")))
check("refused: kind, no expected tree, merges clean offline", c.get("kind") == "refused" and c.get("expected_tree") is None and p.get("offline_merge") == {"clean": True, "conflicts": []}, (c.get("kind"), p.get("offline_merge")))
check("refused: branch is unknown (no merge commit of #11) and recorded as null", p.get("branch") is None and p.get("owner") is None)

c = cases.get("t-conflict", {"prs": [{}]}); p = c["prs"][0]
check("the second attempt of a log is the one selected (the first ended `still pending`)", p.get("attempt") == 1, p.get("attempt"))
check("an attempt with a `(head sha)` line and a `merging main into` line of another sha: the head line wins", p.get("head") == H["hc"] and p.get("queue_head") == H["hc"], (p.get("head"), p.get("queue_head")))
pf = cases.get("t-fallback", {"prs": [{}]})["prs"][0]
check("no `(head sha)` line: the head is the sha of `merging main into`", pf.get("head") == H["hX"], pf.get("head"))
check("conflict refusal: base is main's tip before the FAILED time, expected reason names the files from the log", p.get("base") == H["B2"] and p.get("expected_reason") == "refused: conflicts with main (a.txt)" and p.get("conflict_files") == ["a.txt"], p)
check("conflict refusal: git's merge-tree conflicts on the same file", p.get("offline_merge") == {"clean": False, "conflicts": ["a.txt"]}, p.get("offline_merge"))

c = cases.get("t-group", {"prs": [{}, {}]})
# the fixture: the PR listed first has the LATER `main's tip` line (B2, 13:26:30), the second the EARLIER one (B1, 13:25:07); main's tip before the earliest start is B2 again, so the clock rule,
# the latest line, the first-listed PR's line and the earliest line do not all give the same base
check("group: kind, no group_max key, base is the tip of the earliest `main's tip` line (not the latest line, not the first PR's, not main's tip at the first start)",
      (c.get("kind"), "group_max" in c, c.get("base")) == ("group", False, H["B1"]) and g(WC, "rev-list", "-1", "--first-parent", "--before=2026-06-03T13:20:00Z", "main") == H["B2"], (c.get("kind"), "group_max" in c, c.get("base")))
check("group: each PR keeps its own base (M^1); no single expected tree", [q.get("base") for q in c["prs"]] == [H["B2"], H["M20"]] and "expected_tree" not in c, [q.get("base") for q in c["prs"]])
check("group: heads, merges and trees per PR; both merge clean into their own base with M's tree", [(q.get("head"), q.get("merge")) for q in c["prs"]] == [(H["hg20"], H["M20"]), (H["hg21"], H["M21"])] and all(q["offline_merge"]["tree_equals_merge"] for q in c["prs"]))
check("old path with no ledger line: M found in main's history; main's run from the short line", c["prs"][1].get("main_run") == {"result": "pass", "run": 9000016, "on": H["M21"], "flaky": []}, c["prs"][1].get("main_run"))
check("selection group_base overrides; a fixture `omit` leaves the PR's checks empty with its note", cases["t-omit"]["base"] == H["A2"] and cases["t-omit"]["prs"][1]["checks"] == {} and "checks_note" in cases["t-omit"]["prs"][1] and cases["t-omit"]["prs"][0]["checks"] == {"suites": "pass"})

pb = cases.get("t-failalone", {"prs": [{}, {}]})["prs"][1]
check("a refused PR whose checks are left out has no expected_reason but an explicit `expect` (the chain drops it on its own); the others keep theirs",
      pb.get("known_outcome") == "refused" and pb.get("checks") == {} and "expected_reason" not in pb and str(pb.get("expect", "")).startswith("fails alone:") and cases["t-refused"]["prs"][0].get("expected_reason") and "expect" not in cases["t-refused"]["prs"][0], pb)

check("a head with no sha in the log is dropped, with the reason", "no sha recoverable" in dropped.get("d-nosha", ""), dropped.get("d-nosha"))
check("a sha the checkout does not know is dropped", "deadbee" in dropped.get("d-unknown", "") and "not a commit" in dropped.get("d-unknown", ""), dropped.get("d-unknown"))
check("a sha the remote does not serve by itself is dropped", "does not serve" in dropped.get("d-fetch", ""), dropped.get("d-fetch"))
check("a refusal with no queue equivalent (UNKNOWN) is dropped", "no queue equivalent" in dropped.get("d-noequiv", ""), dropped.get("d-noequiv"))
check("a base that does not contain the queue/** trigger is dropped", "trigger" in dropped.get("d-pretrigger", ""), dropped.get("d-pretrigger"))
check("a missing log and a missing attempt are dropped", "no release log" in dropped.get("d-nolog", "") and "no attempt 5" in dropped.get("d-attempt", ""), (dropped.get("d-nolog"), dropped.get("d-attempt")))
check("every drop is printed on stderr", all(f"DROPPED {i}" in r.stderr for i in dropped), r.stderr[-500:])
check("the summary table lists the cases written", "t-group" in r.stdout and "7 dropped" in r.stdout, r.stdout[-400:])
check("--strict: a drop is an exit 1", build(ROOT / "strict.json", "--strict").returncode == 1)
check("a dropped case is written no PR record (cases hold only built cases)", all(i not in cases for i in dropped))

# ---------------------------------------------------------------- --verify local: the unreachable head is in the checkout, so the fetch-failure case builds
rn = run("build-cases", "--repo", str(WC), "--logdir", str(LOGS), "--out", str(ROOT / "noowner.json"), "--selection", str(SEL), "--trigger", TRIG, "--remote", f"file://{ORIGIN}")
check("no repository owner derivable (a file remote) and no --repo-owner: exit 2 with a clear message, no file written, no scratch left",
      rn.returncode == 2 and "--repo-owner" in rn.stderr and "unknown" in rn.stderr and not (ROOT / "noowner.json").exists() and left_over() == [], (rn.returncode, rn.stderr[-300:], left_over()))
rl = build(ROOT / "local.json", "--verify", "local")
dl = {d["id"] for d in json.loads((ROOT / "local.json").read_text())["dropped"]}
check("--verify local does not need the remote: the local-only head builds, the others stay dropped", rl.returncode == 0 and "d-fetch" not in dl and "d-unknown" in dl, (rl.returncode, sorted(dl)))

ro = build(ROOT / "owner.json", "--repo-owner", "acme-org")
po = {c["id"]: c for c in json.loads((ROOT / "owner.json").read_text())["cases"]}["t-merged"]["prs"][0]
check("--repo-owner: a head branch in the repository's own namespace records no `owner` key (the file names no login of the instance); the branch stays", ro.returncode == 0 and "owner" not in po and po.get("branch") == "feat-x", (ro.returncode, po))

# ---------------------------------------------------------------- --check
def chk(path, *extra, repo=WC):
    return run("build-cases", "--check", "--repo", str(repo), "--cases", str(path), *extra)
bytes_before = OUT.read_bytes(); snap = snapshot(WC)
rc = chk(OUT)
check("--check accepts what build wrote", rc.returncode == 0 and "0 problem(s)" in rc.stdout, (rc.returncode, rc.stdout, rc.stderr[-400:]))
check("--check writes nothing: the file, the checkout and the scratch folder", OUT.read_bytes() == bytes_before and snapshot(WC) == snap and left_over() == [])

def tampered(name, fn):
    d = json.loads(OUT.read_text()); fn({c["id"]: c for c in d["cases"]}); f = ROOT / f"tamper-{name}.json"; f.write_text(json.dumps(d)); return f
f = tampered("head", lambda cs: cs["t-merged"]["prs"][0].update(head=H["A1"]))
rc = chk(f); check("--check refuses a changed head (merge-tree no longer says what the file says)", rc.returncode == 1 and "t-merged #10" in rc.stderr, rc.stderr[-500:])
f = tampered("tree", lambda cs: (cs["t-merged"]["prs"][0].update(merge_tree="0" * 40)))
rc = chk(f); check("--check refuses a merge_tree that is not M's tree", rc.returncode == 1 and "merge_tree" in rc.stderr, rc.stderr[-500:])
f = tampered("state", lambda cs: cs["t-refused"]["prs"][0]["checks"].update(suites="failed"))
rc = chk(f); check("--check refuses a check state outside pass|fail|pending|cancel", rc.returncode == 1 and "check states" in rc.stderr, rc.stderr[-500:])
f = tampered("short", lambda cs: cs["t-merged"]["prs"][0].update(head=s7("h1")))
rc = chk(f); check("--check refuses an abbreviated sha", rc.returncode == 1 and "full sha" in rc.stderr, rc.stderr[-500:])
f = tampered("missing", lambda cs: cs["t-refused"]["prs"][0].update(head="1" * 40))
rc = chk(f); check("--check refuses a sha the checkout lacks", rc.returncode == 1 and "is not available" in rc.stderr, rc.stderr[-500:])
rc = chk(f, "--allow-missing"); check("--allow-missing makes it a warning", rc.returncode == 0 and "warning" in rc.stderr, (rc.returncode, rc.stderr[-300:]))

# a second checkout that never had the unreachable head: local verification fails, a fetch by sha from the remote gets it
W2 = ROOT / "work2"; g(ROOT, "clone", "-q", f"file://{ORIGIN}", str(W2))
rc = chk(OUT, repo=W2); check("a checkout without the refused head fails --verify local", rc.returncode == 1 and "is not available" in rc.stderr, (rc.returncode, rc.stderr[-300:]))
rc = chk(OUT, "--verify", "fetch", repo=W2); check("--verify fetch gets it from the remote by sha", rc.returncode == 0, (rc.returncode, rc.stderr[-400:]))
check("--check leaves no scratch folder", left_over() == [], left_over())

# ---------------------------------------------------------------- SIGTERM during a fetch
marker = ROOT / "hang.marker"
env = {**ENV, "K1_HANG": str(marker)}
p = subprocess.Popen([sys.executable, TOOL, "build-cases", "--repo", str(WC), "--logdir", str(LOGS), "--out", str(ROOT / "term.json"), "--selection", str(SEL), "--trigger", TRIG, "--remote", f"file://{ORIGIN}", "--repo-owner", "other-org"],
                     env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    for _ in range(300):
        if marker.exists() or p.poll() is not None: break
        time.sleep(0.1)
    mid = left_over()
    if p.poll() is None: p.send_signal(signal.SIGTERM)
    try: o, e = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill(); o, e = p.communicate()
finally:
    if p.poll() is None: p.kill(); p.wait()
check("while a fetch runs the scratch folder exists (the case is real)", marker.exists() and len(mid) == 1 and mid[0].startswith("mq-replay-"), (marker.exists(), mid))
check("a SIGTERM there: exit 143, the scratch folder is gone, no cases file written", p.returncode == 143 and left_over() == [] and not (ROOT / "term.json").exists(), (p.returncode, left_over(), e[-300:]))

# ---------------------------------------------------------------- the module, the built-in selection, the checked-in file
spec = importlib.util.spec_from_file_location("mq_replay_tool", TOOL); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
ids = [s["id"] for s in mod.SELECTION]
check("the built-in selection is c01 to c20, each attempt a [pr, n] pair", ids == [f"c{i:02d}" for i in range(1, 21)] and all(isinstance(x, int) for s in mod.SELECTION for pr in s["prs"] for x in pr))
att = mod.parse_log(LOGS / "pr-12.log")
check("parse_log: one record per `release of PR starts`; the first attempt ended `still pending`", len(att) == 2 and att[0]["words"] == "still pending after 50 min" and att[1]["stage"] == "update-branch" and att[1]["conflict_files"] == ["a.txt"], att)
check("check_states reads names and states, and refuses a state outside the four", mod.check_states("a check failed: suites=fail, tool-text=pass") == {"suites": "fail", "tool-text": "pass"} and mod.check_states("still pending after 50 min") is None)
try: mod.check_states("a check failed: suites=weird"); weird = False
except ValueError: weird = True
check("check_states raises on an unknown state", weird)

if os.path.exists(CASES_REAL):
    real = json.loads(open(CASES_REAL).read())
    rc = real["cases"]
    shas_ok = all(len(x) == 40 and set(x) <= set("0123456789abcdef") for c in rc for x in [c["base"]] + [q[k] for q in c["prs"] for k in ("head", "base")] + [q["merge"] for q in c["prs"] if q["known_outcome"] == "merged"])
    states_ok = all(s in mod.VALID_STATES for c in rc for q in c["prs"] for s in q["checks"].values())
    check("tests/mq_replay/cases.json: format 1, the 20 cases c01 to c20, nothing dropped", real["format"] == 1 and [c["id"] for c in rc] == ids and real["dropped"] == [], ([c["id"] for c in rc], real.get("dropped")))
    check("tests/mq_replay/cases.json: full shas, check states pass|fail|pending|cancel, kinds and outcomes", shas_ok and states_ok and all(c["kind"] in ("merged", "refused", "group") for c in rc) and all(q["known_outcome"] in ("merged", "refused") for c in rc for q in c["prs"]))
    check("tests/mq_replay/cases.json: every merged single case has M's tree as expected_tree; every refused PR an expected reason or (checks left out, c13's) an `expect`, never both; c12 and c13 are groups",
          all(c.get("expected_tree") == c["prs"][0]["merge_tree"] for c in rc if c["kind"] == "merged") and all(bool(q.get("expected_reason")) != bool(q.get("expect")) for c in rc for q in c["prs"] if q["known_outcome"] == "refused")
          and [c["kind"] for c in rc if c["id"] in ("c12", "c13")] == ["group", "group"])
else:
    check("tests/mq_replay/cases.json is checked in", False)

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
