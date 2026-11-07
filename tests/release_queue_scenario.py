"""Scenario test for release.sh --run, second half: what comes after the merge (covering runs, the CI-run poller) and the release queue. Same setup as release_scenario.py:
no network, no real gh, git or deploy, release.sh copied into a temp dir beside stubs (tests/_release_harness.py).

Covering runs (section 14: three PRs merged close together; main cancelled two runs and every release waited for the tip's
queued run until it gave up): a release whose merge commit is M is satisfied by a passed main run on any commit that contains M (git merge-base
--is-ancestor), deployed at the newest such passed commit; a cancelled run is skipped; a run still queued or going is waited for; a failed run on a commit
that contains M fails the release, but one that comes after a pass on M or between M and it does not (the oldest failed commit decides, and the log names its
run); WAIT_MAIN counts from when a covering run starts, CAP_MAIN from the merge, and the last log line names both; the same rule for the deploy at the merge's watch
(main_green post): a cancelled run with a later passing one is not unknown, a cancelled run alone is unknown after the cap, a failing later commit with no pass
before it rolls back.

The CI-run poller (section 15): while it waits for the PR's checks and for main's run, release.sh first asks `salamander ci-runs <repo> --sha <sha> --max-age 120` (a fake
`salamander` on PATH here, never the host's). A fresh answer that lists a run of the commit still going (in progress or queued, or one run of several) makes the cycle wait with no
GitHub call at all (no `gh pr checks`, no git fetch, no `gh run list`/`view`); the cap and WAIT_MAIN still end the wait. A run listed as completed (whatever its conclusion), no run of the sha
listed, exit 3, 4 or 5, output that is not JSON, or no salamander on PATH: the GitHub read, which alone passes or fails the release (never the poller). Main's wait counts only push runs.

The release queue (section 16): `release.sh queue N...` starts every waiting PR's release at once (four at a time), so GitHub's merge queue gets them together; the deploy lock
serializes the deploys. A PR that fails before its merge (checks, a conflict, removed from the merge queue) is skipped and the queue goes on; a failed main run for a merged one pauses it.

    tests/run-suite release_queue        → exit 0 / 1"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
from _release_harness import *
def gl(s): return s["gh"].splitlines()
def enqueues(s): return [l for l in gl(s) if l.startswith("pr merge")]
# ---- 14. covering runs: a release is satisfied by a run on any commit that contains its merge commit M. Three PRs (#38, #41 and #42) merge close together
# in a row; main's workflow runs one run at a time and cancels a queued run when a newer push arrives, so the runs on #38's and #42's merges are cancelled, the run on
# #41's own merge passes, and the run on the newest commit is queued behind it. The history is linear, oldest first: A (#38's merge), B (#41's), C (#42's), D (the tip).
SA, SB, SC, SD = "a" * 40, "b" * 40, "c" * 40, "d" * 40
INC_HIST = ",".join([SA, SB, SC, SD])
INC_RUNS = json.dumps([{"databaseId": 14, "headSha": SD}, {"databaseId": 13, "headSha": SC}, {"databaseId": 12, "headSha": SB}, {"databaseId": 11, "headSha": SA}])
def inc(name, oid, **kw):   # the old path (no up-to-date tip is readable), release of the PR whose merge commit is OID, the four runs
    return scenario(name, **{**dict(merge="ok", runs=INC_RUNS, history=INC_HIST, merge_oid=oid), **kw})
s = inc("cover-41", SB, main11="replaced", main12="pass", main13="replaced", main14="queued")
check("#41: three merges, two runs cancelled, the run on its own merge passed, the tip still queued: deploys at once on M's passing run, pinned to M",
      s["rc"] == 0 and s["deployed"] and not s["sleeps"] and s["deploy_to"] == SB and "main's tests pass at bbbbbbb (run 12)" in s["log"] and "which contains" not in s["log"], (s["out"], s["sleeps"], s["deploy_to"]))
check("…a run on a commit before M is not read at all, and the release is green", "run view 11" not in s["gh"] and s["msg"].rstrip("\n").endswith(GREEN_ARGS) and "main at 0106c0d" in s["msg"], (s["gh"], s["msg"]))
s = inc("cover-38", SA, main11="replaced", main12="pass", main13="replaced", main14="queued")
check("#38: its own run was cancelled, the next run, on B which contains A, passed: deploys at B at once, and the log says the run is on a commit that contains the merge",
      s["rc"] == 0 and not s["sleeps"] and s["deploy_to"] == SB and "main's tests pass at bbbbbbb (run 12, on bbbbbbb, which contains aaaaaaa)" in s["log"]
      and "deploying bbbbbbb, the newest commit containing the merge aaaaaaa whose run passed" in s["log"], (s["log"], s["deploy_to"]))
s = inc("cover-42-later", SC, main13="replaced", main14="queued,queued,pending,pass")
check("#42: its run was cancelled and the tip's covering run is still queued, then going, then passes: waited for (polled every 20 s), then deployed at the tip's commit",
      s["rc"] == 0 and s["sleeps"] == ["20"] * 3 and s["deploy_to"] == SD and "main's tests pass at ddddddd (run 14, on ddddddd, which contains ccccccc)" in s["log"], (s["log"], s["sleeps"], s["deploy_to"]))
s = inc("cover-two-passed", SB, main11="replaced", main12="pass", main13="pass", main14="queued")
check("two runs that contain M passed: the deploy goes to the newest passed commit (C), the third still queued",
      s["rc"] == 0 and not s["sleeps"] and s["deploy_to"] == SC and "main's tests pass at ccccccc (run 13, on ccccccc, which contains bbbbbbb)" in s["log"], (s["log"], s["deploy_to"]))

# a cancelled run with no later run covering M: waited for until the cap, then failed (before the deploy) with both limits named; the cancelled run named
s = inc("cover-cancelled-only", SC, runs=json.dumps([{"databaseId": 13, "headSha": SC}]), main13="replaced", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("a cancelled run and no later run: not a failure, waited 20 s three times until the cap, then FAILED at main's tests (merged, not deployed) naming both limits and the cancelled run",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 3
      and "FAILED at main's tests: no finished run on main covers ccccccc after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 1 min); the run 13 on ccccccc was cancelled and no later run covers ccccccc: merged, not deployed" in s["msg"],
      (s["msg"], s["sleeps"]))
check("…the lock is free after, and the red report got no fd 9", lock_free(s), s["client_fd9"])
check("…and the log said so once, at the first look (the wait was 1 min): the cancelled run named, a later run that contains the merge waited for, GitHub reads said honestly",
      s["log"].count("main's runs covering ccccccc were canceled (run 13 on ccccccc, the newest one); waiting for a later main run that contains it, reading main's runs from GitHub every 20 s") == 1, s["log"])
# the same state held for 12 min (a release that logged nothing for a long time): one line every 5 min on the test's clock (20 s sleeps), at 0, 5 and 10 min
s = inc("cover-cancelled-only-log", SC, runs=json.dumps([{"databaseId": 13, "headSha": SC}]), main13="replaced", extra={"RELEASE_WAIT_MAIN": "720", "RELEASE_CAP_MAIN": "720"})
check("only cancelled runs cover the merge for 12 min: a line every 5 min (three in all), not one per look and not none; the wait still ends at the cap with the same message",
      s["rc"] == 1 and not s["deployed"] and len(s["sleeps"]) == 36
      and s["log"].count("main's runs covering ccccccc were canceled (run 13 on ccccccc, the newest one); waiting for a later main run that contains it") == 3
      and "FAILED at main's tests: no finished run on main covers ccccccc after 12 min since the merge (the cap is 12 min)" in s["msg"], (s["log"], len(s["sleeps"]), s["msg"]))
s = inc("cover-cancelled-then-pass-log", SC, main13="replaced", main14="queued,pass")
check("a cancelled run with a later covering run (queued, then passing): that is not the canceled-only state, so no canceled line is logged",
      s["rc"] == 0 and "were canceled" not in s["log"], s["log"])
# the next state after a cancelled run: a later covering run going (read from GitHub, the ci-runs file lists nothing). It used to log nothing at all; now one line every 5 min on the test's clock
s = inc("cover-running-log", SC, main13="replaced", main14=",".join(["pending"] * 40 + ["pass"]))
RUNNING_LINE = "main's run 14 is running, on ddddddd, which contains ccccccc ("
check("a cancelled run, then the covering run going for 13 min (40 polls of 20 s): the log says so every 5 min (at 0, 5 and 10 min), with the run, its commit, the minutes so far and that GitHub is read, then it passes",
      s["rc"] == 0 and s["deploy_to"] == SD and len(s["sleeps"]) == 40
      and s["log"].count(RUNNING_LINE) == 3 and s["log"].count("min so far); waiting for it to finish, reading main's runs from GitHub every 20 s") == 3
      and RUNNING_LINE + "0 min so far)" in s["log"] and RUNNING_LINE + "5 min so far)" in s["log"] and RUNNING_LINE + "10 min so far)" in s["log"], (s["log"], len(s["sleeps"])))
s = inc("cover-running-short", SC, main13="replaced", main14="pending,pending,pass")
check("a covering run going for 40 s only: one line (the first look), not one per poll",
      s["rc"] == 0 and s["log"].count("is running, on ddddddd, which contains ccccccc (") == 1, s["log"])

# a failed covering run fails the release as before; the oldest commit that failed decides, and the log names its run
s = inc("cover-fail-own", SC, main13="fail", live=NOTLIVE)
check("a failed run on M itself: fails at once, merged and not deployed, red, no wait",
      s["rc"] == 1 and not s["deployed"] and not s["sleeps"] and "FAILED at main's tests: the run on main for ccccccc failed (run every suite, measured=failure;" in s["msg"]
      and "decided it" not in s["msg"] and "merged, not deployed" in s["msg"] and "--release" not in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-fail-later", SB, main12="replaced", main13="fail", main14="pass", live=NOTLIVE)
check("M's own run was cancelled and the next commit's run failed, with no pass on M or between: the release fails, judged by that oldest failed commit, which the message and the log name; the later pass is not waited for",
      s["rc"] == 1 and not s["deployed"] and "run view 14" not in s["gh"]
      and "FAILED at main's tests: the run on main for ccccccc failed (run every suite, measured=failure;" in s["msg"]
      and "ccccccc is the oldest commit after the merge bbbbbbb whose run failed, and no run on bbbbbbb or between them passed, so that run decided it" in s["msg"]
      and "the run 13 on ccccccc decided: the oldest commit that failed after the merge bbbbbbb" in s["log"], (s["msg"], s["log"]))
s = inc("cover-fail-after-pass", SB, main12="pass", main13="fail", main14="fail")
check("M's run passed and a later commit's run failed (and the one after it too): the failure is that later commit's, not this release's: deploys at M, the log names the oldest failed run",
      s["rc"] == 0 and s["deployed"] and s["deploy_to"] == SB and "run view 14" not in s["gh"] and not s["sleeps"]
      and "the run 13 on ccccccc failed after the pass on bbbbbbb: judged by the oldest commit that failed, which is not this release, so the pass on bbbbbbb decides" in s["log"], (s["log"], s["deploy_to"]))
s = inc("cover-fail-between", SA, main11="pass", main12="fail", main13="pass", main14="queued")
check("A passed, B failed, C passed after it: the oldest failure bounds the pass, so the deploy goes to A, never to C",
      s["rc"] == 0 and s["deploy_to"] == SA and "main's tests pass at aaaaaaa (run 11)" in s["log"], (s["log"], s["deploy_to"]))

# the limit counts from when a covering run starts (in progress), not from the merge
RUN14 = json.dumps([{"databaseId": 14, "headSha": SD}])
s = inc("cover-wait-from-start", SD, runs=RUN14, main14="queued,queued,queued,queued,queued,pending,pending,pass", extra={"RELEASE_WAIT_MAIN": "60"})
check("queued for five polls (100 s, more than the 60 s limit), then 40 s in progress, then passes: deployed; the queue did not use the run's limit up",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 7 and s["deploy_to"] == SD, (s["out"], s["sleeps"]))
s = inc("cover-wait-limit", SD, runs=RUN14, main14="queued,queued,pending", extra={"RELEASE_WAIT_MAIN": "60"})
check("queued for two polls, then in progress and never done: gives up 60 s after it started (five polls in all, not three), unknown, merged and not deployed, both limits named",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 5
      and "no finished run on main covers ddddddd after 1 min since the merge (the cap is 180 min) and 1 min since a covering run started (the limit is 1 min): merged, not deployed" in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-wait-cap", SD, runs=RUN14, main14="queued", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100"})
check("queued and never starting: the cap from the merge ends the wait (five polls), whatever the run's own limit",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 5 and "no finished run on main covers ddddddd after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started" in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-wait-restart", SD, runs=json.dumps([{"databaseId": 14, "headSha": SD}, {"databaseId": 15, "headSha": SD}]), main14="pending,pending,replaced", main15="pending,pending,pass", extra={"RELEASE_WAIT_MAIN": "60"})
check("a run going for 40 s is cancelled and another covering run starts: its limit starts again from its own start (not from the first), so it can finish",
      s["rc"] == 0 and s["deployed"] and "main's tests pass at ddddddd (run 15)" in s["log"], (s["out"], s["sleeps"]))

# the waits are read off the clock, not counted in polls: each look at main's runs costs 40 s here besides the 20 s sleep, so a 100 s cap ends after two sleeps, not five
s = inc("cover-clock", SD, runs=RUN14, main14="queued", poll_cost="40", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100"})
check("a look that takes time counts: with 40 s a look and 20 s a sleep the 100 s cap is reached after two sleeps (counting sleeps would have waited five), the line naming the minutes from the clock",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 2 and "after 2 min since the merge (the cap is 1 min)" in s["msg"], (s["msg"], s["sleeps"]))
# a run on a commit this checkout does not have (not fetched yet) is skipped, whatever state GitHub says; a re-run of an older commit, with a later id, keeps its place by commit
s = inc("cover-unfetched", SB, runs=json.dumps([{"databaseId": 99, "headSha": "9" * 40}, *json.loads(INC_RUNS)]), main99="pass", main11="replaced", main12="pass", main13="replaced", main14="queued")
check("a main run on a commit the checkout does not have is no cover (not read at all), whatever its state: the release still deploys on B",
      s["rc"] == 0 and s["deploy_to"] == SB and "run view 99" not in s["gh"], (s["gh"], s["deploy_to"]))
s = inc("cover-rerun-order", SB, runs=json.dumps([{"databaseId": 12, "headSha": SB}, {"databaseId": 20, "headSha": SD}, {"databaseId": 21, "headSha": SC}]), main12="replaced", main20="fail", main21="pass")
check("a re-run of an older commit (C, run 21) created after the tip's run (D, run 20) keeps its place by commit: B cancelled, C passed, D failed after it: deploys at C (ordered by run id the failure on D would have come first and failed the release)",
      s["rc"] == 0 and s["deploy_to"] == SC and "the run 20 on ddddddd failed after the pass on ccccccc" in s["log"], (s["log"], s["deploy_to"]))

# the same rule for the watch after the deploy (main_green post)
s = fast("post-covered", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="cancelled", main8="pass")
check("after the fast deploy: the run on the merge was cancelled, a later run on a commit that contains it passed: not unknown, no rollback; recorded as the last good commit, the log names the later commit",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["lastgood"] == MERGE and "main's tests passed on 0106c0d (run 8, on 0107c0d, which contains 0106c0d)" in s["log"], (s["msgs"], s["log"], s["lastgood"]))
s = fast("post-covered-list", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER, "status": "completed", "conclusion": "success", "attempt": 1},
                                                            {"databaseId": 7, "headSha": MERGE, "status": "completed", "conclusion": "cancelled", "attempt": 1}]), main7="pass", main8="pass")
check("a run the list says is completed and cancelled is skipped with no run view; the later run decides, and the list asks for status, conclusion and attempt",
      s["rc"] == 0 and "run view 7" not in s["gh"] and "run view 8" in s["gh"] and "--json databaseId,headSha,status,conclusion,attempt" in s["gh"] and not red(s), (s["gh"], s["msgs"]))
s = fast("post-covered-later", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="replaced", main8="queued,pending,pass")
check("…a covering run still queued is waited for (two 20 s polls) and passes: green",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["sleeps"] == ["20", "20"] and "(run 8, on 0107c0d, which contains 0106c0d)" in s["log"], (s["msgs"], s["sleeps"]))
s = fast("post-pass-then-fail", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="pass", main8="fail", heads=f"{BASE},{MERGE}")
check("after the fast deploy: the run on the merge passed and the next commit's failed: not this release's, no rollback, the log names the failed run",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["lastgood"] == MERGE and "the run 8 on 0107c0d failed after the pass on 0106c0d" in s["log"], (s["msgs"], s["deploys"], s["log"]))
s = fast("post-fail-later", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="replaced", main8="fail", heads=f"{BASE},{MERGE}")
check("after the fast deploy: the run on the merge was cancelled and the next commit's failed: rolled back to the last good commit, the report naming the commit that decided",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "the run on main for 0107c0d failed" in red(s)[0]
      and "0107c0d is the oldest commit after the merge 0106c0d whose run failed, and no run on 0106c0d or between them passed, so that run decided it" in red(s)[0], (s["deploys"], s["msgs"]))
# the board item on the post-deploy check: a finished green run whose step results are not in yet is waited for, never rolled back
s = fast("post-late", merge="ok", main7="late,late,pass")
check("after the fast deploy: completed and green but the suites step has no conclusion yet: waited for (two 20 s polls), then passes: no rollback, no red report, recorded as the last good commit",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["sleeps"] == ["20", "20"] and s["lastgood"] == MERGE and "main's tests passed on 0106c0d (run 7)" in s["log"], (s["rc"], s["deploys"], s["msgs"], s["sleeps"], s["lastgood"]))
s = fast("post-late-never", merge="ok", main7="late", heads=f"{BASE},{MERGE}", extra={"RELEASE_WAIT_STEPS": "60"})
check("after the fast deploy: the step results never arrive: given up after RELEASE_WAIT_STEPS and failed like any failed run (rolled back), the report saying the step results never arrived",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["sleeps"] == ["20"] * 3 and "step results never arrived in 1 min" in red(s)[0], (s["deploys"], s["sleeps"], s["msgs"]))
s = fast("post-queued-forever", merge="ok", main7="queued", extra={"RELEASE_CAP_MAIN": "100"})
check("after the fast deploy: a covering run that never starts is given up at the cap, unknown: deployed and NOT rolled back, both limits named",
      s["rc"] == 1 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] * 5 and "the cap is 1 min) and 0 min since a covering run started (the limit is 90 min): deployed at 0106c0d and NOT rolled back" in red(s)[0], (s["msgs"], s["sleeps"]))


# ---- 15. the CI-run poller: sala keeps a file of the repo's newest runs; a fresh one that shows the commit's run still going makes a cycle wait with no GitHub call.
# Anything else (completed, not listed, exit 3/4/5, garbage, no salamander) is the GitHub read, which alone decides. salamander's calls are in s["sal"], one line each.
SAL_ARGS = f"ci-runs example-owner/stackshot --sha {HEADSHA} --max-age 120"
def pr_reads(s): return s["gh"].count("pr checks 23")
def run_lists(s): return s["gh"].count("run list --repo")
def fetches(s): return s["git"].splitlines().count("fetch --quiet origin main")
s = scenario("pr-wait-poller", merge="ok", salamander="running,queued,completed")
check("PR checks: the poller shows the head's run going (in progress, then queued): two cycles wait with no `gh pr checks`; it shows completed: the GitHub read, once, passes",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"] and pr_reads(s) == 1 and "checks pass" in s["log"], (s["rc"], s["sleeps"], s["gh"], s["out"]))
check("PR checks: salamander is asked about the PR head, with the 120 s age, in the repo's own name; the log says the wait is on the ci-runs file (a line at the start)",
      s["sal"][0] == SAL_ARGS and s["log"].count("waiting on the ci-runs file, no GitHub call") == 1 and f"checks on {HEADSHA[:7]}: 1 of 1 run(s) of {HEADSHA[:7]} not completed" in s["log"], (s["sal"][:2], s["log"]))
s = scenario("pr-wait-poller-forever", merge="ok", salamander="running", extra={"RELEASE_WAIT_CHECKS": "300"})
check("PR checks: a run the poller shows going for good never makes a GitHub call, and the cap still ends the wait (5 min here): FAILED at checks, nothing merged",
      s["rc"] == 1 and not s["deployed"] and pr_reads(s) == 0 and len(s["sleeps"]) == 15 and "still pending after 5 min" in s["msg"] and not merges(s), (s["rc"], s["sleeps"][:3], s["gh"], s["msg"]))
s = scenario("pr-wait-poller-mixed", merge="ok", salamander="mixed,completed", checks="pass")
check("PR checks: one run of the commit completed and another still going counts as going (as sala's release.sh does), then the GitHub read",
      s["rc"] == 0 and s["sleeps"] == ["20"] and pr_reads(s) == 1, (s["sleeps"], s["gh"]))
s = scenario("pr-wait-poller-completed-fail", merge="ok", salamander="completed", checks="fail")
check("PR checks: the poller says completed (success) but the GitHub read says a check failed: the release fails on the GitHub read",
      s["rc"] == 1 and not s["deployed"] and pr_reads(s) == 1 and "FAILED at checks: a check failed" in s["msg"] and not merges(s), (s["rc"], s["msg"], s["gh"]))
s = scenario("pr-wait-poller-completed-pass", merge="ok", salamander="completed", salamander_conclusion="failure", checks="pass")
check("PR checks: the poller says the run completed with a failure but the GitHub read passes: it passes (the poller never fails a release)",
      s["rc"] == 0 and s["deployed"] and pr_reads(s) == 1 and "FAILED" not in s["log"], (s["rc"], s["log"]))
for mode in ("stale", "none", "unreadable", "usage", "garbage", "empty"):
    s = scenario(f"pr-wait-poller-{mode}", merge="ok", salamander=mode, checks="pending,pass")
    check(f"PR checks: salamander answers {mode} (exit 4 stale, 3 no file, 5 unreadable, 2 usage, 0 with no JSON, 0 with no run of the sha listed): every cycle is the GitHub read, a missing sha is no failure",
          s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and pr_reads(s) == 2 and "ci-runs file" not in s["log"] and s["sal"] and s["sal"][0] == SAL_ARGS, (mode, s["rc"], s["sleeps"], s["gh"], s["log"]))
s = scenario("pr-wait-no-salamander", merge="ok", nosalamander=True, checks="pending,pass")
check("PR checks: no salamander on PATH: the GitHub read every cycle, nothing else changes",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and pr_reads(s) == 2 and not s["sal"] and "ci-runs file" not in s["log"], (s["rc"], s["sleeps"], s["gh"], s["sal"]))
s = scenario("pr-wait-poller-off", merge="ok", salamander="running", checks="pending,pass", extra={"RELEASE_CIRUNS_MAX_AGE": "0"})
check("RELEASE_CIRUNS_MAX_AGE=0: the poller is never asked, the GitHub read every cycle", s["rc"] == 0 and pr_reads(s) == 2 and not s["sal"], (s["gh"], s["sal"]))
s = scenario("pr-wait-poller-dated", merge="ok", salamander="running", checks="pending,pass", extra={"RELEASE_CIRUNS_MAX_AGE": "30"})
check("RELEASE_CIRUNS_MAX_AGE is the --max-age handed to salamander", s["sal"] and s["sal"][0] == SAL_ARGS.replace("--max-age 120", "--max-age 30"), s["sal"][:1])

# main's wait, the old path (3b): sequence of the stub's answers is the PR wait's first (one call), then one per look at main's run
s0 = scenario("main-wait-baseline", merge="ok", main="pending,pending,pass")
s = scenario("main-wait-poller", merge="ok", salamander="completed,running,queued,completed", main="pass")
check("main's wait: the poller shows main's push run of the merge going for two looks: no `gh run list`, no `gh run view`, and no git fetch either; the third look (completed) reads GitHub, which passes it",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"] and run_lists(s) == 1 and s["gh"].count("run view 7") == 1 and "main's tests pass at 0106c0d (run 7)" in s["log"]
      and fetches(s) == fetches(s0) - 2, (s["rc"], s["sleeps"], s["gh"], fetches(s), fetches(s0), s["log"]))
check("main's wait: salamander is asked about the merge commit, and the log names the run that is waited on (a line at the start)",
      s["sal"][1] == "ci-runs example-owner/stackshot --sha 0106c0de0106c0de0106c0de0106c0de0106c0de --max-age 120"
      and s["log"].count("main's run 7 on 0106c0d: 1 of 1 run(s) of 0106c0d not completed") == 1 and "waiting on the ci-runs file, no GitHub call" in s["log"], (s["sal"], s["log"]))
s = scenario("main-wait-poller-completed-fail", merge="ok", salamander="completed", main="fail", live=NOTLIVE)
check("main's wait: the poller says the run completed (success) but the GitHub read says the suites failed: FAILED at main's tests, merged and not deployed",
      s["rc"] == 1 and not s["deployed"] and run_lists(s) == 1 and "FAILED at main's tests" in s["msg"] and "merged, not deployed" in s["msg"], (s["rc"], s["msg"]))
s = scenario("main-wait-poller-limit", merge="ok", salamander="completed,running", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100000"})
check("main's wait: a run the poller shows going counts against WAIT_MAIN as a run from the GitHub read does, with no GitHub call: given up as unknown, merged and not deployed",
      s["rc"] == 1 and not s["deployed"] and run_lists(s) == 0 and "the limit is 1 min" in s["msg"] and "merged, not deployed" in s["msg"] and s["sleeps"] == ["20"] * 3, (s["rc"], s["sleeps"], s["gh"], s["msg"]))
s = scenario("main-wait-poller-pr-event", merge="ok", salamander="completed,running,running", salamander_event="pull_request", main="pass")
check("main's wait keeps main's push runs: a run of the merge commit that is a pull_request run, going, is not waited on; the GitHub read is made at once",
      s["rc"] == 0 and s["deployed"] and not s["sleeps"] and run_lists(s) == 1 and "waiting on the ci-runs file" not in s["log"], (s["sleeps"], s["gh"], s["log"]))
for mode in ("stale", "none", "unreadable", "empty"):
    s = scenario(f"main-wait-poller-{mode}", merge="ok", salamander=f"completed,{mode}", main="pending,pass")
    check(f"main's wait: salamander answers {mode}: the GitHub read (fetch, run list, run view) every look, as before",
          s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and run_lists(s) == 2 and "ci-runs file" not in s["log"], (mode, s["sleeps"], s["gh"], s["log"]))
s = scenario("main-wait-no-salamander", merge="ok", nosalamander=True, main="pending,pass")
check("main's wait: no salamander on PATH: the GitHub read every look", s["rc"] == 0 and s["sleeps"] == ["20"] and run_lists(s) == 2 and not s["sal"], (s["sleeps"], s["gh"]))

# main's wait, the deploy at the merge: the run of the merge is watched after the deploy
s = fast("fast-poller", merge="ok", salamander="completed,running,running,completed", main="pass")
check("gate open: the deploy at the merge, then main's run watched through the poller: two looks with no GitHub call, the third reads GitHub and passes, recorded as last good; nothing else changes",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view"] and s["sleeps"] == ["20", "20"] and run_lists(s) == 1 and s["lastgood"] == MERGE
      and not red(s) and lock_views(s) == ["free"] and "main's tests passed on 0106c0d (run 7)" in s["log"], (s["rc"], s["deploys"], s["order"], s["sleeps"], s["gh"], s["log"]))
s = fast("fast-poller-fail", merge="ok", salamander="completed,running,completed", main="fail", heads=f"{BASE},{MERGE}")
check("gate open: the poller shows the run completed and the GitHub read says it failed: rolled back to the last good commit, as without the poller",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0] and run_lists(s) == 1, (s["deploys"], s["msgs"], s["gh"]))
s = fast("fast-poller-stale", merge="ok", salamander="completed,stale", main="pending,pass")
check("gate open: a stale poller file: the GitHub read at every look, polled every 20 s", s["rc"] == 0 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] and run_lists(s) == 2, (s["sleeps"], s["gh"]))

# the PR-checks wait looks every 60 s by default (RELEASE_POLL_PR; the suite sets 20) and shares its read between releases for RELEASE_GH_TTL s, like main's
s = scenario("pr-wait-default-poll", merge="ok", checks="pending,pending,pass", extra={"RELEASE_POLL_PR": ""})
check("PR checks: the default look is every 60 s", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["60", "60"] and pr_reads(s) == 3, (s["sleeps"], s["gh"], s["out"]))
s = scenario("pr-wait-default-cap", merge="ok", checks="pending", secs=240, extra={"RELEASE_POLL_PR": ""})
check("PR checks: the 50 min cap is the same at 60 s: 50 sleeps of 60 s, 51 looks, then FAILED at checks, nothing merged",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["60"] * 50 and pr_reads(s) == 51 and "still pending after 50 min" in s["msg"] and not merges(s), (s["rc"], len(s["sleeps"]), pr_reads(s), s["msg"]))
s = scenario("pr-wait-cached", merge="ok", checks="pending,pass", extra={"RELEASE_GH_TTL": "300", "RELEASE_WAIT_CHECKS": "300"})
check("PR checks: a read is reused inside RELEASE_GH_TTL (fake sleeps move no clock): one `gh pr checks`, the pending answer reused until the cap",
      s["rc"] == 1 and pr_reads(s) == 1 and "still pending after 5 min" in s["msg"] and (s["dir"] / "releases/gh-cache").is_dir(), (s["rc"], pr_reads(s), s["msg"]))
s1 = scenario("pr-wait-shared-1", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
s2 = scenario("pr-wait-shared-2", merge="ok", checks="fail", reuse=s1, extra={"RELEASE_GH_TTL": "300"})
check("PR checks: a second release on the same box for the same head reads what the first read: no new `gh pr checks`, so it agrees with it",
      s1["rc"] == 0 and pr_reads(s1) == 1 and s2["rc"] == 0 and pr_reads(s2) == 1, (pr_reads(s1), s2["rc"], pr_reads(s2)))
s = scenario("pr-wait-cache-head", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
s_other = scenario("pr-wait-cache-other-head", merge="ok", checks="fail", reuse=s, prheads="1111111def5678abc1234def5678abc1234def56", head="1111111def5678abc1234def5678abc1234def56", extra={"RELEASE_GH_TTL": "300"})
check("PR checks: the cache key holds the PR head: another head asks GitHub again (a fresh answer, here a failure) and does not take the first head's pass",
      s["rc"] == 0 and s_other["rc"] == 1 and pr_reads(s_other) == 2 and "FAILED at checks" in s_other["msg"], (s_other["rc"], s_other["gh"], s_other["msg"]))
s = scenario("pr-wait-cache-private", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
check("PR checks: the cache folder is private to the user (mode 700)", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777) == "0o700", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777))

# ---- 16. the release queue. GitHub's merge queue tests PRs together only when they reach it together, so `release.sh queue N [N...]` records PR numbers in order and starts the plain release of EVERY waiting one at once
# (4 running at a time, release.sh's own number); each release enqueues its PR, waits for GitHub's merge, takes the deploy lock for its deploy (which serializes them), and when it is deployed leaves the queue and lets the next
# waiting PRs start. One that fails before its merge (checks, a conflict, removed from the merge queue) is skipped and the queue goes on; a failed main run for a merged one pauses it.
def q(name, *args, **kw):   # the front door: release.sh queue ...
    return scenario(name, args=args, front=True, pr="queue", **{"units": "", **kw})
QF = lambda queue, started=(): {"releases/queue": "".join(f"{n}\n" for n in queue), **({"releases/queue.started": "".join(f"{n}\n" for n in started)} if started else {})}   # a started PR stays in the queue file until it is deployed
PAUSED = "PR #22 failed at main's tests after its merge, 2026-11-02T00:00:00Z\n"
s = q("q-add", "25", "35", "25")
check("queue: PRs are recorded in order (one queued twice stays where it is) and EVERY waiting one starts at once, as release.sh N, marked as started by the queue and still in the queue file until it is deployed",
      s["rc"] == 0 and s["started"] == ["25", "35"] and s["queue"] == ["25", "35"] and s["started_marks"] == ["25", "35"] and "queued PR #25" in s["out"] and "PR #25 is queued already" in s["out"]
      and "release queue, in order: 25 35" in s["out"] and s["order"] == ["start:25", "start:35"] and [l.split()[:3] for l in s["gh"].splitlines()] == [["pr", "checks", "25"], ["pr", "checks", "35"]], (s["rc"], s["started"], s["queue"], s["out"], s["gh"]))
s2 = q("q-add-more", "37", reuse=s, units="25 35")
check("queue: a PR added while others run starts at once too (the cap is four)", s2["rc"] == 0 and s2["started"] == ["25", "35", "37"] and s2["queue"] == ["25", "35", "37"] and s2["started_marks"] == ["25", "35", "37"], (s2["started"], s2["queue"], s2["out"]))
s3 = q("q-list", "--list", reuse=s2, units="25 35 37")
check("queue --list: the queued PRs in order, each running", s3["rc"] == 0 and "release queue, in order: 25 35 37" in s3["out"] and s3["out"].count("running (its release starts the next waiting one when it is deployed)") == 3, s3["out"])
s3 = q("q-drop", "--drop", "35", reuse=s2, units="25 35 37")
check("queue --drop N: takes it out (and its started mark), the rest keep their order", s3["rc"] == 0 and s3["queue"] == ["25", "37"] and s3["started_marks"] == ["25", "37"] and "dropped PR #35" in s3["out"] and "dropped PR #35" in s3["qlog"], (s3["queue"], s3["out"]))
s3 = q("q-drop-absent", "--drop", "999", reuse=s2, units="25 35 37")
check("queue --drop of a PR that is not queued: exit 1, the queue unchanged", s3["rc"] == 1 and s3["queue"] == ["25", "37"] and "not in the release queue" in s3["out"], (s3["rc"], s3["out"]))
for nm, a in (("q-bad-number", ("abc",)), ("q-bad-empty", ()), ("q-bad-drop", ("--drop",)), ("q-bad-option", ("--fast",))):
    s3 = q(nm, *a)
    check(f"{nm}: refused with exit 2 and the usage, nothing queued or started", s3["rc"] == 2 and ("usage: release.sh queue" in s3["out"] or "is not a PR number" in s3["out"]) and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"]))
s3 = q("q-start-fail", "25", "35", start_fail="25")
check("queue: a PR whose release cannot be started is logged and skipped (out of the queue), and the next one starts", s3["rc"] == 0 and s3["started"] == ["35"] and s3["queue"] == ["35"] and s3["started_marks"] == ["35"]
      and "could not start the release of PR #25" in s3["out"], (s3["started"], s3["out"]))
# the cap: four releases run at once, the others wait; a release that is deployed lets the next waiting one start
s = q("q-cap", "41", "42", "43", "44", "45", "46")
check("queue: at most four releases run at once: the first four start, the others wait in the queue", s["rc"] == 0 and s["started"] == ["41", "42", "43", "44"] and s["queue"] == ["41", "42", "43", "44", "45", "46"]
      and s["started_marks"] == ["41", "42", "43", "44"] and "4 of at most 4 running" in s["out"] or "release queue, in order: 41 42 43 44 45 46" in s["out"], (s["started"], s["queue"], s["out"]))
s2 = q("q-cap-more", "47", reuse=s, units="41 42 43 44")
check("queue: with four running a PR added waits (nothing more starts)", s2["rc"] == 0 and s2["started"] == ["41", "42", "43", "44"] and s2["queue"][-1] == "47" and "nothing to start (4 of at most 4 running" in s2["out"], (s2["started"], s2["out"]))
s2 = q("q-cap-list", "--list", reuse=s, units="41 42 43 44")
check("queue --list: the running ones and the waiting ones are told apart", "PR #41: running" in s2["out"] and "PR #45: waiting" in s2["out"] and "PR #46: waiting" in s2["out"], s2["out"])
s = fast("q-cap-handoff", merge="ok", files=QF(["23", "25", "26", "27", "28", "29"], started=["23", "25", "26", "27"]), units="25 26 27")
check("queue: when a release is deployed it leaves the queue and the next waiting PR starts, up to four running (25, 26 and 27 still run: only 28 starts)",
      s["rc"] == 0 and s["started"] == ["28"] and s["queue"] == ["25", "26", "27", "28", "29"] and s["started_marks"] == ["25", "26", "27", "28"] and "release queue: started the release of PR #28 (4 of at most 4 running" in s["log"], (s["started"], s["queue"], s["log"][-400:]))
# queue refuses a PR with a failing check row (the releaser read `gh pr checks N` by hand before; now the command does): one read of the rows per PR not queued yet, refused with the failing rows printed, nothing queued, no bypass
def gh_checks(s): return [l.split()[2] for l in s["gh"].splitlines() if l.startswith("pr checks")]
s3 = q("q-check-fail", "25", "35", checks="fail")
check("queue: a PR with a failing check row is refused: exit 1, `refused: PR N has failing check rows:` and the row's name, state and link; nothing queued or started",
      s3["rc"] == 1 and "refused: PR 25 has failing check rows:\n  suites  FAILURE  https://ci.example/suites\n" in s3["out"] and "lint" not in s3["out"] and not s3["queue"] and not s3["started"]
      and "queued PR" not in s3["out"] and "refused PR #25: refused: PR 25 has failing check rows:" in s3["qlog"], (s3["rc"], s3["out"], s3["queue"], s3["started"], s3["qlog"]))
check("queue: every PR named is read and each failing one printed; one refusal queues none of them", "refused: PR 35 has failing check rows:" in s3["out"] and gh_checks(s3) == ["25", "35"], (s3["out"], s3["gh"]))
s3 = q("q-check-one-fails", "25", "35", checks="pass,fail")
check("queue: the PR with all rows passing is not refused, but the command queues nothing while another PR it names is (35 here fails)",
      s3["rc"] == 1 and "refused: PR 35 has failing check rows:" in s3["out"] and "refused: PR 25" not in s3["out"] and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-shard", "25", checks="shardfail")
check("queue: a matrix shard row counts like any row (the shard's own line, the pending suites row and the passing shard are not printed)",
      s3["rc"] == 1 and "refused: PR 25 has failing check rows:\n  suites (shard 3/4)  FAILURE  https://ci.example/shard3\n" in s3["out"] and "shard 1/4" not in s3["out"] and "PENDING" not in s3["out"] and not s3["queue"],
      (s3["rc"], s3["out"], s3["queue"]))
for nm, cv, row in (("timedout", "timedout", "suites  TIMED_OUT  https://ci.example/timed-out"), ("cancel", "cancel", "suites  CANCELLED  https://ci.example/suites")):
    s3 = q(f"q-check-{nm}", "25", checks=cv)
    check(f"queue: a {nm} row refuses too", s3["rc"] == 1 and row in s3["out"] and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-pending", "25", "35", checks="pending")
check("queue: a pending row does not refuse: both PRs are queued and both start, as without the gate",
      s3["rc"] == 0 and s3["queue"] == ["25", "35"] and s3["started"] == ["25", "35"] and "refused" not in s3["out"] and gh_checks(s3) == ["25", "35"], (s3["rc"], s3["out"], s3["queue"], s3["started"]))
s3 = q("q-check-skipping", "25", checks="skipping")
check("queue: skipped and passing rows queue the PR", s3["rc"] == 0 and s3["queue"] == ["25"] and s3["started"] == ["25"] and "refused" not in s3["out"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-pass", "25", "35", checks="pass")
check("queue: all rows passing queues the PRs (the read asks for the name, state, bucket and link of the rows)",
      s3["rc"] == 0 and s3["queue"] == ["25", "35"] and "queued PR #25" in s3["out"] and "pr checks 25 --repo example-owner/stackshot --json name,state,bucket,link" in s3["gh"], (s3["rc"], s3["out"], s3["queue"], s3["gh"]))
s3 = q("q-check-unreadable", "25", "35", checks="unreadable")
check("queue: a PR whose rows cannot be read (gh fails) is refused with gh's error, never queued blindly: exit 1, nothing queued or started",
      s3["rc"] == 1 and "refused: PR 25: its check rows could not be read, so it is not queued: GraphQL: Could not resolve to a PullRequest with the number of 25. (HTTP 502)" in s3["out"]
      and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"], s3["started"]))
s3 = q("q-check-nochecks", "25", checks="nochecks")
check("queue: gh saying no checks were reported on the PR yet is a read of no rows: queued", s3["rc"] == 0 and s3["queue"] == ["25"] and "refused" not in s3["out"], (s3["rc"], s3["out"], s3["queue"]))
s2 = q("q-add-more2", "37", reuse=s, units="")
s3 = q("q-check-already", "37", reuse=s2, units="", checks="fail")
check("queue: a PR queued already is not read again and keeps its place (its rows may fail now: the command adds nothing and refuses nothing)",
      s3["rc"] == 0 and "PR #37 is queued already" in s3["out"] and "refused" not in s3["out"] and gh_checks(s3).count("37") == 1, (s3["rc"], s3["out"], s3["queue"], s3["gh"]))  # the one read is the earlier command's that queued it
s3 = q("q-check-has-no-bypass", "25", "--force", checks="fail")
check("queue: there is no bypass option: an option is only the usage error, and release.sh's text names none", s3["rc"] == 2 and not s3["queue"] and not re.search(r"RELEASE_[A-Z_]*(FORCE|SKIP_CHECK|BYPASS)", pathlib.Path(STACK, "release.sh").read_text()), (s3["rc"], s3["out"]))
home = subprocess.run(["bash", os.path.join(STACK, "release.sh"), "--help"], capture_output=True, text=True)
check("--help: names the queue's four forms and its rules", all(t in home.stdout for t in ("./release.sh queue N [N...]", "queue --list", "queue --drop N", "queue --resume", "pauses the queue", "skipped")), home.stdout[:200])

# the queue's release reaches "deployed": it leaves the queue and starts the next waiting PRs then, before it waits on main's run
s = fast("q-deploy", merge="ok", files=QF(["23", "25", "35"], started=["23"]), units="")
check("queue: the release the queue started leaves the queue when it is deployed (after the deploy and its report, before main's run) and the waiting PRs start",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["started"] == ["25", "35"] and s["order"] == [f"deploy:{MERGE}", "client:message", "start:25", "start:35", "run-view"]
      and s["queue"] == ["25", "35"] and s["started_marks"] == ["25", "35"] and "release queue: started the release of PR #25 (1 of at most 4 running, 2 queued)" in s["log"], (s["order"], s["started"], s["queue"], s["log"][-600:]))
s = scenario("q-deploy-old-path", merge="ok", files=QF(["23", "25"], started=["23"]), units="")
check("queue: with the gate closed (main's tests first) the next one starts at the deploy too", s["rc"] == 0 and s["deployed"] and s["started"] == ["25"] and s["order"][-1] == "start:25" and s["queue"] == ["25"], (s["order"], s["started"]))
s = fast("q-deploy-last", merge="ok", files=QF(["23"], started=["23"]), units="")
check("queue: the last queued release finds nothing more to start and lets go of the queue", s["rc"] == 0 and not s["started"] and not s["queue"] and not s["started_marks"] and "the release queue is empty" in s["log"], (s["started"], s["queue"]))
s = fast("q-deploy-by-hand", merge="ok", files=QF(["25"], started=["25"]), units="25")
check("queue: a release started by hand (not in the queue file) starts nothing from the queue when it is deployed", s["rc"] == 0 and not s["started"] and s["queue"] == ["25"] and s["started_marks"] == ["25"], (s["started"], s["queue"]))
s = fast("q-none", merge="ok", units="")
check("no queue: a release starts nothing and its report says nothing of a queue", s["rc"] == 0 and not s["started"] and "queue" not in s["msg"].replace("merge queue", "") and not s["queue"], (s["started"], s["msg"]))

# a queued PR whose checks fail, that conflicts or that GitHub removes from its merge queue is reported as ever and skipped: the queue goes on and the others start
s = scenario("q-skip-checks", merge="ok", checks="fail", files=QF(["23", "25"], started=["23"]), units="")
check("queue: a queued PR whose checks fail is FAILED at checks as ever, never enqueued, and skipped: the next queued PR starts",
      s["rc"] == 1 and not s["deployed"] and not enqueues(s) and "FAILED at checks: a check failed: suites=fail" in s["log"] and "FAILED at checks: a check failed: suites=fail" in s["msg"]
      and "skipped in the release queue" in s["msg"] and s["started"] == ["25"] and s["queue"] == ["25"] and s["started_marks"] == ["25"] and not s["paused"]
      and "skipped PR #23: failed at checks before its merge" in s["qlog"], (s["rc"], s["started"], s["msg"], s["qlog"]))
s = scenario("q-skip-conflict", merge="ok", mergeable="CONFLICTING", files=QF(["23", "25"], started=["23"]), units="")
check("queue: a queued PR that conflicts is FAILED at mergeable as ever and skipped: the next one starts", s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["started"] == ["25"] and not s["paused"], (s["started"], s["msg"]))
s = scenario("q-skip-removed", merge="ok", gq="queued,open,open", gq_reason="The merge group failed its required checks", files=QF(["23", "25", "35"], started=["23", "25"]), units="25")
check("queue: a queued PR GitHub removes from its merge queue is FAILED at merge queue with GitHub's reason before any deploy, skipped, and the queue goes on (35 starts), not paused",
      s["rc"] == 1 and not s["deployed"] and not s["deploys"] and "FAILED at merge queue: removed from the merge queue: The merge group failed its required checks" in s["msg"] and "skipped in the release queue" in s["msg"]
      and s["started"] == ["35"] and s["queue"] == ["25", "35"] and not s["paused"] and "skipped PR #23: failed at merge queue before its merge" in s["qlog"], (s["rc"], s["started"], s["queue"], s["msg"], s["qlog"]))
s = scenario("q-skip-by-hand", merge="ok", checks="fail", files=QF(["25"], started=["25"]), units="25")
check("queue: a failure of a release that is not in the queue starts nothing from it, and its report says nothing of a queue", s["rc"] == 1 and not s["started"] and "queue" not in s["msg"].replace("merge queue", "") and s["queue"] == ["25"], (s["started"], s["msg"]))

# main's run fails for a merged release: the queue pauses, and the rollback and the red report run as ever
s = fast("q-main-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", files=QF(["23", "25", "35"], started=["23"]), units="")
check("queue: main's run fails after the deploy at the merge: rolled back and reported as ever, and the queue is paused (the waiting PRs had started at the deploy)",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["started"] == ["25", "35"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and "PR #23 failed at main's tests after its merge" in s["paused"] and s["queue"] == ["25", "35"]
      and "the release queue is paused with 2 queued (25 35): release.sh queue --resume once main is fixed" in red(s)[0], (s["deploys"], s["started"], s["paused"], s["msgs"]))
sp = scenario("q-paused-next", reuse=s, pr="25", merge="ok", units="")
check("queue: a pause stops a release the queue had started before it (25, started at 23's deploy) before it enqueues: FAILED at queue paused, nothing enqueued, no hand-off, still first in the queue and no longer marked as running",
      sp["rc"] == 1 and "pr merge 25" not in sp["gh"] and sp["deploys"] == s["deploys"] and "FAILED at queue paused: the release queue is paused (PR #23 failed at main's tests after its merge" in sp["msg"]
      and "stopped before its merge, still first in the release queue" in sp["msg"] and sp["started"] == ["25", "35"] and sp["queue"] == ["25", "35"] and sp["started_marks"] == ["35"]
      and "PR #25 stopped by the pause before its merge: first in the queue" in sp["qlog"] and "PR #23 failed" in sp["paused"], (sp["rc"], sp["started"], sp["queue"], sp["started_marks"], sp["msg"], sp["log"][-400:]))
sp = scenario("q-paused-hand", merge="ok", files={**QF(["25"], started=["25"]), "releases/queue.paused": PAUSED}, units="25")
check("queue: a release started by hand while the queue is paused is not the queue's: it deploys as ever and starts nothing; the pause and the queue stay",
      sp["rc"] == 0 and sp["deployed"] and not sp["started"] and sp["queue"] == ["25"] and sp["paused"] == PAUSED, (sp["rc"], sp["started"], sp["queue"], sp["paused"]))
sp = q("q-add-paused", "37", reuse=s)
check("queue: a PR added while it is paused waits; nothing starts", sp["rc"] == 0 and sp["started"] == ["25", "35"] and sp["queue"] == ["25", "35", "37"] and "is paused" in sp["out"], (sp["started"], sp["out"]))
sp = q("q-list-paused", "--list", reuse=s)
check("queue --list says it is paused and why", "paused: PR #23 failed at main's tests after its merge" in sp["out"] and "release queue, in order: 25 35 37" in sp["out"], sp["out"])
sp = q("q-resume", "--resume", reuse=s)
check("queue --resume: the pause ends, and the queued releases that are not running (killed, or stopped by the pause) start again, then the waiting ones",
      sp["rc"] == 0 and not sp["paused"] and sp["started"][-3:] == ["25", "35", "37"] and sp["queue"] == ["25", "35", "37"] and "resumed" in sp["qlog"] and "PR #35 was started but its release is not running: it starts again" in sp["out"], (sp["started"], sp["queue"], sp["out"]))
s = scenario("q-old-path-main-fail", merge="ok", main="fail", live=NOTLIVE, files=QF(["23", "25"], started=["23"]), units="")
check("queue: main's run fails with the gate closed (merged, not deployed): FAILED at main's tests as ever, nothing started, the queue paused; the failed PR leaves the queue",
      s["rc"] == 1 and not s["deployed"] and "FAILED at main's tests" in s["msg"] and "merged, not deployed" in s["msg"] and not s["started"] and s["queue"] == ["25"]
      and "PR #23 failed at main's tests after its merge" in s["paused"], (s["deployed"], s["started"], s["paused"], s["msg"]))
s = fast("q-main-unknown", merge="ok", main="replaced", files=QF(["23", "25"], started=["23"]), units="", extra={"RELEASE_CAP_MAIN": "60"})
check("queue: a main run that cannot be read after the deploy is no failure of the code: reported as ever, the queue not paused (the next one started at the deploy)",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, main's run was not read" in red(s)[0] and not s["paused"] and s["started"] == ["25"], (s["deploys"], s["paused"], s["msgs"]))
s = scenario("q-old-path-main-unknown", merge="ok", runs="[]", files=QF(["23", "25", "35"], started=["23"]), units="", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("queue: with the gate closed a main run that cannot be read in time (merged, not deployed) is no failure: FAILED as ever, but the queue is NOT paused, the merged PR leaves it, and the waiting ones start",
      s["rc"] == 1 and not s["deployed"] and "no finished run on main covers 0106c0d" in s["msg"] and "merged, not deployed" in s["msg"] and not s["paused"]
      and "the release queue goes on" in s["msg"] and s["started"] == ["25", "35"] and s["queue"] == ["25", "35"], (s["paused"], s["started"], s["queue"], s["msg"]))

# the rollback takes out riders (releases deployed on top): they are merged and stay on main, so they are not queued again; the report and the log name them
s = fast("q-riders", merge="ok", main="fail", heads=f"{BASE},{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other;0107c0d Merge pull request #37 from agent/more", files=QF(["23", "44"], started=["23"]), units="")
RIDER_NOTE = "rolled back with it, merged and not live: #35 #37; they go live with the next release once main is fixed, or ./deploy.sh once main's tip run is green"
check("queue: the PRs a rollback took out with the failed one (35, 37) are not queued again (they are merged: release.sh N would fail at pr state): the queue keeps only the one that was waiting (44), the failed PR is gone from it",
      s["rc"] == 1 and "PR #35 was rolled back with #23's failure" in "\n".join(s["msgs"]) and s["queue"] == ["44"] and "PR #23 failed at main's tests after its merge" in s["paused"]
      and "the release queue is paused with 1 queued (44)" in red(s)[0], (s["queue"], s["paused"], s["msgs"][-1]))
check("…the failed PR's report names them with how they go live, and the queue's log says they are not queued again; each one's own message says the same",
      RIDER_NOTE in red(s)[0] and "PR #35 was rolled back with PR #23: merged and not live, not queued again" in s["qlog"] and "PR #37 was rolled back with PR #23" in s["qlog"] and "back at the front" not in s["qlog"]
      and sum("it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" in m for m in s["msgs"]) == 2 and not any("release it again" in m for m in s["msgs"]), (s["qlog"], s["msgs"]))
s2 = q("q-riders-resume", "--resume", reuse=s)
check("queue --resume after that: the one that was waiting (44, started at the deploy and not running now) is released again, the riders are not started", s2["rc"] == 0 and not s2["paused"] and s2["started"] == ["44", "44"] and s2["queue"] == ["44"] and s2["started_marks"] == ["44"], (s2["started"], s2["queue"], s2["out"]))
s = fast("q-no-riders", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", files=QF(["23", "25"], started=["23"]), units="")
check("queue: a rollback that took nothing else out says nothing of riders", s["rc"] == 1 and "rolled back with it" not in red(s)[0], red(s)[0])

# the pause is on disk while the rollback holds the deploy lock, so a release that gets the lock after it finds it
s = fast("q-pause-first", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", files=QF(["23", "25", "35"], started=["23"]), units="")
check("queue: a rollback writes the pause before its deploy runs (the lock is held and is let go after it), and the pause names the step",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["paused_at_rollback"] == "present" and "PR #23 failed at main's tests after its merge" in s["paused"]
      and "written before the deploy lock was let go" in s["qlog"], (s["paused_at_rollback"], s["paused"], s["qlog"]))
s = fast("q-pause-first-plain", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
check("no queue: a plain release.sh N whose rollback runs writes no pause at all", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["paused_at_rollback"] == "absent" and not s["paused"], (s["paused_at_rollback"], s["paused"]))
s = fast("q-pause-first-deploy", merge="ok", deploy_fail="1", files=QF(["23", "25"], started=["23"]), units="")
check("queue: a deploy that fails after the merge pauses the queue before the lock is let go too (the queue's log says so), and the report says it is paused",
      s["rc"] == 1 and "FAILED at deploy" in red(s)[0] and "PR #23 failed at deploy after its merge" in s["paused"] and "PR #23 failed at deploy after its merge (written before the deploy lock was let go)" in s["qlog"]
      and "the release queue is paused" in red(s)[0], (s["paused"], s["qlog"], s["msgs"]))

# a recovery rollback (a release process ended before main's run was read) of a PR the queue started pauses the queue before it takes the deploy lock
QLOG_a = "2026-11-02T00:00:00Z started PR #26 (release.sh queue); 2 in the queue\n"
seen = []
s = fast("q-lock-wait-rollback", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, hold="until-waiting", lockhook=lambda d: seen.append((d / "releases/queue.paused").exists()),
         files={**QF([]), "releases/queue.log": QLOG_a}, units="")
check("queue: a rollback of a PR the queue started pauses it before it takes the deploy lock: the pause is on disk when the lock held by another release is let go",
      s["rc"] == 0 and seen == [True] and s["deploys"][0] == f"rollback {GOOD}" and "PR #26 failed at main's tests after its merge" in s["paused"], (seen, s["deploys"], s["paused"], s["log"][-500:]))
s = fast("q-recover-plain", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, files=QF(["25"], started=["25"]), units="25")
check("queue: a release that recovers a PR 26 the queue did not start (the queue runs another PR, its log has no start of 26) rolls it back as ever and pauses nothing",
      s["rc"] == 0 and s["deploys"][0] == f"rollback {GOOD}" and not s["paused"] and s["queue"] == ["25"] and s["started_marks"] == ["25"] and s["paused_at_rollback"] == "absent", (s["paused"], s["queue"], s["msgs"]))
s = fast("q-recover-started", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, files=QF(["26"], started=["26"]), units="26")
check("queue: …and one the started file names (26, started by the queue and not yet deployed) pauses it",
      s["rc"] == 0 and s["deploys"][0] == f"rollback {GOOD}" and "PR #26 failed at main's tests after its merge" in s["paused"] and s["paused_at_rollback"] == "present", (s["paused"], s["deploys"], s["msgs"]))

# a failure of a release the queue did not start pauses nothing
s = fast("q-plain-main-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
check("no queue: a plain release.sh N whose main run fails is rolled back and reported as ever and leaves no paused file", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and not s["paused"] and "release queue" not in red(s)[0] and not (s["dir"] / "releases/queue.paused").exists(), (s["paused"], s["msgs"]))
s = scenario("q-plain-old-path-fail", merge="ok", main="fail", live=NOTLIVE)
check("no queue: a plain release.sh N whose main run fails with the gate closed leaves no paused file", s["rc"] == 1 and "merged, not deployed" in s["msg"] and not (s["dir"] / "releases/queue.paused").exists(), s["msg"])
s = fast("q-hand-main-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", files=QF(["25"], started=["25"]), units="25")
check("queue: a release started by hand (the queue runs another) whose main run fails is rolled back as ever and does not pause the queue", s["rc"] == 1 and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and not s["paused"] and s["queue"] == ["25"] and "release queue" not in red(s)[0], (s["paused"], s["queue"], s["msgs"]))

# a queued release that is killed (its unit gone) is still in the queue file: listed, and --resume starts it again
s = q("q-killed-list", "--list", files=QF(["23", "25"], started=["23"]), units="")
check("queue --list: a killed queued release is still listed (first), and the output says its release is not running and that --resume starts it again; the waiting one is told apart",
      s["rc"] == 0 and "release queue, in order: 23 25" in s["out"] and "PR #23: started by the queue but its release is not running" in s["out"] and "release.sh queue --resume starts it again" in s["out"] and "PR #25: waiting" in s["out"], s["out"])
s2 = q("q-killed-resume", "--resume", reuse=s)
check("queue --resume: the killed release is started again, and the waiting one starts with it", s2["rc"] == 0 and s2["started"] == ["23", "25"] and s2["queue"] == ["23", "25"] and s2["started_marks"] == ["23", "25"], (s2["started"], s2["queue"], s2["out"]))

# a queued release picks what the sessions need from its PR's files, as any release does (the queue passes no flag)
s = fast("q-pick-recycle", merge="ok", pickfiles="docs/a.md,client/hooks/session-start.sh", files=QF(["23"], started=["23"]), units="")
check("queue: a queued PR that changes the start-loaded hook gets a recycle (recycle-due on the PR), reported green, with no warning",
      s["rc"] == 0 and "recycle-due" in s["msg"] and "session pick: recycle (from client/hooks/session-start.sh)" in s["log"] and "WARNING" not in s["log"] + s["msg"] and "--release" in s["msg"], (s["log"][-500:], s["msg"]))
s = fast("q-pick-per-call", merge="ok", pickfiles="docs/a.md,client.py,pages.py", files=QF(["23"], started=["23"]), units="")
check("queue: a queued PR that changes only files run fresh at each call picks nothing: no recycle, green", s["rc"] == 0 and "recycle-due" not in s["msg"] and "session pick: nothing" in s["log"] and "--release" in s["msg"], (s["log"][-300:], s["msg"]))

finish()
