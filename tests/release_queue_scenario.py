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

The two merge queues (section 18): GitHub's merge queue is the default; the salamander merge queue (`salamander mq`) is used when the host file says `mode = "on"` and names the deploy lock.
Mode on: one PR waiting is released alone by run() (no `salamander mq` call, the marker and deploy_lock guards), two or more (at most 4) go to the salamander queue together as a group release
(`--group` / `--run-group`: hand-off, per-PR waits, adopt/eject/fail cases, the deploy at the merge, the failures after it). Off, shadow, absent and bad host files all use GitHub's queue.

    tests/run-suite release_queue        → exit 0 / 1"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
from _release_harness import *
def gl(s): return s["gh"].splitlines()
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
check("after the fast deploy: the step results never arrive (the run concluded success): given up after RELEASE_WAIT_STEPS, the run counts as green: no rollback, no red report, recorded as the last good commit, a WARNING in the log",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["sleeps"] == ["20"] * 3 and s["lastgood"] == MERGE
      and "WARNING: main's run 7 on 0106c0d concluded success but GitHub never filled in its step results in 1 min: counted as green (not rolled back)" in s["log"], (s["rc"], s["deploys"], s["sleeps"], s["msgs"], s["log"]))
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

# ---- 17. the review of the first version: a late member of a merge group, after a rollback paused the queue, does not deploy onto a main that is red
def pause_while_waiting(d): (d / "releases/queue.paused").write_text(PAUSED)   # a rollback of another release wrote the pause while this one waited for the deploy lock
s = fast("q-late-member", hold="until-waiting", lockhook=pause_while_waiting, files=QF(["25"], started=["25"]), units="25", pr="25")
check("queue: a release the queue started that finds the queue paused when it gets the deploy lock does not deploy: FAILED at queue paused, merged and not deployed, and it leaves the queue (the pause stays as it was)",
      s["rc"] == 1 and not s["deploys"] and not s["deployed"] and "FAILED at queue paused" in s["msg"] and "merged and not deployed" in s["msg"] and "release queue" in s["msg"] and s["queue"] == [] and s["paused"] == PAUSED
      and "PR #25 is merged and was not deployed: the queue is paused" in s["qlog"] and not s["started"], (s["rc"], s["msg"], s["queue"], s["paused"], s["qlog"]))
check("queue: …before it waits for main's tests (the pause is read as soon as the lock is had, not only at the end of that wait)", "run-view" not in s["order"], s["order"])
check("queue: …and the lock is let go and no report child inherited it", lock_free(s), s["client_fd9"])
s = fast("q-late-member-main-wait", files=QF(["25"], started=["25"]), units="25", pr="25", pause_at_run=PAUSED, main="pass", lastgood=LATER)
check("queue: a release the queue started whose pause comes while it waits for main's tests (the gate was closed for another reason) does not deploy either: FAILED at queue paused, merged and not deployed",
      s["rc"] == 1 and not s["deploys"] and "run-view" in s["order"] and "FAILED at queue paused" in s["msg"] and "merged and not deployed" in s["msg"] and s["queue"] == [] and s["paused"] == PAUSED, (s["rc"], s["order"], s["msg"], s["queue"], s["paused"], s["deploys"]))
s = fast("q-late-live", hold="until-waiting", lockhook=pause_while_waiting, files=QF(["25"], started=["25"]), units="25", pr="25", heads=f"{NEWER},{NEWER}")
check("queue: a release whose merge is live already (4a) has nothing to deploy, so the pause does not stop it: it reports as ever", s["rc"] == 0 and "already live" in s["log"] and "queue paused" not in s["msg"], (s["rc"], s["log"], s["msg"]))
s = fast("q-late-hand", hold="until-waiting", lockhook=pause_while_waiting)
check("a release started by hand that finds the queue paused at the lock is not refused, but the gate is closed by the pause: it waits for main's tests, then deploys",
      s["rc"] == 0 and s["order"][0] == "run-view" and s["deploys"] == [MERGE] and "not deployed at the merge yet: the release queue is paused (PR #22 failed at main's tests after its merge" in s["log"], (s["order"], s["log"]))
s = fast("q-gate-paused", files={"releases/queue.paused": PAUSED})
check("gate: a paused release queue closes the deploy gate on its own (everything else open)", s["rc"] == 0 and s["order"][0] == "run-view" and "the release queue is paused" in s["log"], (s["order"], s["log"]))
s = fast("q-failed-deploy-first", deploy_fail="1", files=QF(["23", "25"], started=["23"]), units="")
s2 = fast("q-after-failed-deploy", pr="25", reuse=s, files={})
check("queue: a failed deploy pauses the queue, and the pause closes the gate of the next release (started by hand here): it waits for main's tests before it deploys",
      s["rc"] == 1 and "PR #23 failed at deploy after its merge" in s["paused"] and s2["rc"] == 0 and "not deployed at the merge yet: the release queue is paused (PR #23 failed at deploy" in s2["log"], (s["paused"], s2["rc"], s2["log"][-600:]))
s = fast("q-late-tip-after-rollback", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", files=QF(["23", "25"], started=["23"]), units="")
check("queue: after a rollback the pause is on disk before the deploy lock is let go, which is what the late member's check at the lock reads",
      s["rc"] == 1 and s["paused_at_rollback"] == "present", (s["paused_at_rollback"], s["paused"]))

# ---- 18. the two merge queues. GitHub's merge queue is the default (no host file, mode off, shadow, a file that does not read); the host file's `mode = "on"` hands the PRs to salamander's own merge queue (`salamander mq`) instead.
# The release queue then routes by COUNT and starts ONE thing at a time: one PR waiting is a lone release (run(), no call to `salamander mq`), two or more go as ONE group (`salamander mq add N1 N2...`, `mq wait` for each, one deploy of
# the merge through the same deploy gate as a GitHub-queue release, `done:` for each PR). The host file also names the deploy lock this script takes (`deploy_lock`). The fake `salamander mq` answers `mq wait <pr>` per PR from RT_MQ_PRS (mq_prs=).
ON = 'mode = "on"\ndeploy_lock = "@DIR@/releases/deploy.lock"\n'
M1 = "a1a1a1a" + "0" * 33; M2 = "b2b2b2b" + "0" * 33; M3 = "c3c3c3c" + "0" * 33
HIST_G = ",".join([GOOD, BASE, M1, M2, M3])
STRAY = "5757000000000000000000000000000000000057"   # a live checkout that is not in the history: the deploy gate's (a) is closed
MQ_ADD2 = "mq add 23 25 --repo example-owner/stackshot"
def wait_(n, slice_=300): return f"mq wait {n} --repo example-owner/stackshot --timeout {slice_}"
def prlog(s, n): p = s["dir"] / f"releases/pr-{n}.log"; return p.read_text() if p.exists() else ""
def glog(s): p = s["dir"] / "releases/group-23.log"; return p.read_text() if p.exists() else ""
def handed(s): d = s["dir"] / "releases/mq-on"; return sorted(p.name for p in d.iterdir()) if d.is_dir() else []
def started_args(s): p = s["dir"] / "started-args"; return p.read_text().splitlines() if p.exists() else []
GLOG = f"{M2} Merge pull request #25 from agent/two;{M1} Merge pull request #23 from agent/one"
QS = QF(["23", "25"], started=["23"])   # a group of 23 and 25 the release queue started: the lead is marked
def grp(name, prs=("23", "25"), tip=M2, **kw):   # a group release of the PRs, as its unit runs it: the live checkout at BASE (main's tip before the group), the queue merged up to `tip`
    full = [m for m in (M1, M2, M3) if HIST_G.index(m) <= HIST_G.index(tip)]
    opts = dict(raw=["--run-group", *prs], pr=prs[0], mqhost=ON, mq="off", units="", history=HIST_G, live=BASE, live_after=tip, tip=tip, fullshas=",".join(full), files=QF(list(prs), started=[prs[0]]),
                runs=json.dumps([{"databaseId": 7, "headSha": tip}]), mq_prs=",".join(f"{n}=merged@{m[:7]}" for m, n in zip(full, prs)))
    return fast(name, **{**opts, **kw})
def gq_calls(s): return [l for l in s["gh"].splitlines() if "enqueuePullRequest" in l or l.startswith("pr merge")]

# -- a lone PR under mode on: run(), no call to the salamander merge queue; with the GitHub queue off (as mode on assumes) it is merged at once by the plain merge call
s = scenario("on-lone", merge="ok", mqhost=ON, mq="off")
check("mode on, one PR: released alone by run(): merged by the plain merge call (the GitHub ruleset's queue is off), deployed, no `salamander mq` call of any kind, the log says it is released alone",
      s["rc"] == 0 and s["deployed"] and not s["mq"] and plain_merges(s) and not enqueues(s) and "salamander merge queue (mode on): PR #23 is released alone" in s["log"], (s["rc"], s["mq"], s["log"][-500:]))
s = scenario("on-lone-nolock", merge="ok", mqhost='mode = "on"\n', mq="off")
check("mode on without deploy_lock in the host file: refused before anything is touched (FAILED at mq mode, with the line to add), one red report, nothing merged or deployed, no call to the queue",
      s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "deploy_lock" in s["log"] and s["lockfile"].name in s["log"] and not merges(s) and not s["deployed"] and len(red(s)) == 1 and not s["mq"], (s["rc"], s["log"][-500:], s["gh"]))
s = scenario("on-lone-otherlock", merge="ok", mqhost='mode = "on"\ndeploy_lock = "/somewhere/else.lock"\n', mq="off")
check("mode on with a deploy_lock that is not the lock this script takes: refused the same way (the queue's push would not wait for a release), naming both files", s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "/somewhere/else.lock" in s["log"] and not s["deployed"] and not merges(s), (s["rc"], s["log"][-500:]))
s = scenario("on-lone-marker", merge="ok", mqhost=ON, mq="off", files={"releases/mq-on/pr-23": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #26\n"})
check("mode on: a PR a group release handed to the salamander merge queue (its marker) is never merged by run(): FAILED at mq line, naming `salamander mq drop`, nothing merged or deployed, no call to the queue, the marker stays",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and "salamander mq drop 23" in s["log"] and not merges(s) and not s["deployed"] and not s["mq"] and handed(s) == ["pr-23"], (s["rc"], s["log"][-500:], s["gh"]))
s = scenario("on-lone-marker-late", merge="ok", mqhost=ON, mq="off", checks="pending,pass", mark_at_checks="1")
check("mode on: a lone release that was clear at its start and waits for its checks while a group takes its PR: the marker is read again just before the merge: FAILED at mq line, nothing merged, nothing deployed, no call to the queue",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and not merges(s) and not s["deployed"] and not s["mq"] and handed(s) == ["pr-23"], (s["rc"], s["log"][-500:], s["gh"]))
# GitHub's queue is the default: no host file, mode off, shadow, a file that does not read all take the enqueue path and never call `salamander mq`
for nm, host in (("nofile", None), ("off", "off"), ("shadow", "shadow"), ("badmode", 'mode = "sideways"\n'), ("badtoml", "mode = = on\n")):
    s = scenario(f"gh-default-{nm}", merge="ok", gq="queued,merged", mqhost=host)
    check(f"host file {nm}: GitHub's merge queue (the enqueue mutation, then the wait), no plain merge call, no `salamander mq` call",
          s["rc"] == 0 and s["deployed"] and len(enqueues(s)) == 1 and not plain_merges(s) and not s["mq"] and "mq line" not in s["log"] and "mq mode" not in s["log"], (s["rc"], s["log"][-500:], s["mq"]))
    if nm == "shadow": check("host file shadow: the log says the mode is no longer run and GitHub's queue is used", "the host file says shadow" in s["log"], s["log"][:600])
    if nm in ("badmode", "badtoml"): check(f"host file {nm}: the log says the mode does not read and GitHub's queue is used", "does not read" in s["log"], s["log"][:600])
# a marker (a group release handed the PR to the salamander queue) refuses the lone release in EVERY mode: a host file changed mid-group does not take the PR out of that queue
MARK = "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #26\n"
for nm, host in (("nofile", None), ("off", "off"), ("shadow", "shadow"), ("badmode", 'mode = "sideways"\n'), ("on", ON)):
    s = scenario(f"marker-{nm}-dead", merge="ok", gq="queued,merged", mqhost=host, mq="off", files={"releases/mq-on/pr-23": MARK})
    check(f"host file {nm}, the marker's group release not running: FAILED at mq line, nothing merged or enqueued or deployed, no call to the queue, the marker stays, the log says how to clear it (queue --drop 23)",
          s["rc"] == 1 and "FAILED at mq line" in s["log"] and "is not running" in s["log"] and "release.sh queue --drop 23" in s["log"] and not merges(s) and not enqueues(s) and not s["deployed"] and not s["mq"] and handed(s) == ["pr-23"], (s["rc"], s["log"][-600:], s["gh"]))
s = scenario("marker-off-alive", merge="ok", gq="queued,merged", mqhost="off", mq="off", units="26", files={"releases/mq-on/pr-23": MARK})
check("host file off, the marker's group release (PR 26) still running: FAILED at mq line saying to wait for it, nothing merged",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and "stackshot-release-26) is still running" in s["log"] and not merges(s) and not enqueues(s) and not s["deployed"], (s["rc"], s["log"][-600:]))
s = scenario("marker-off-late", merge="ok", gq="queued,merged", mqhost="off", checks="pending,pass", mark_at_checks="1")
check("host file off: a marker that appears while the release waits for its checks is read again just before the enqueue: FAILED at mq line, nothing enqueued",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and not enqueues(s) and not merges(s) and not s["deployed"], (s["rc"], s["log"][-500:], s["gh"]))
# GitHub's own queue on as well as mode on: refused (two queues would merge into main)
s = scenario("on-github-queue-also", merge="ok", gq="queued,merged", mqhost=ON)
check("mode on with the GitHub ruleset's queue also on (a lone PR): FAILED at mq mode naming both queues, nothing enqueued, merged or deployed, no call to the salamander queue, one red report",
      s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "GitHub's merge queue is on for main" in s["log"] and not enqueues(s) and not merges(s) and not s["deployed"] and not s["mq"] and len(red(s)) == 1, (s["rc"], s["log"][-500:], s["gh"]))
s = scenario("on-github-queue-unreadable", merge="ok", mqhost=ON, mq="fail")
check("mode on with GitHub's answer about its merge queue unreadable (three reads): refused as well, nothing merged",
      s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "cannot be read" in s["log"] and not merges(s) and not s["deployed"], (s["rc"], s["log"][-500:]))
s = grp("on-group-github-queue-also", mq="on", mq_prs="")
check("mode on, a group release with GitHub's queue also on: FAILED at mq mode before anything is handed over (no `mq add`), nothing merged or deployed",
      s["rc"] == 1 and "FAILED at mq mode" in s["log"] + glog(s) and "GitHub's merge queue is on for main" in s["log"] + glog(s) and not any("mq add" in l for l in s["mq"]) and not s["deployed"] and handed(s) == [], (s["rc"], glog(s)[-500:], s["mq"]))

# -- the release queue routes by count
s = q("on-q-three", "23", "25", "35", mqhost=ON)
check("release queue, mode on, three waiting: ONE group release for all three, led by the first (marked started, the others are not), started as release.sh --run-group; no PR started alone, no `salamander mq` call from the queue itself",
      s["rc"] == 0 and s["started"] == ["23"] and s["started_marks"] == ["23"] and s["queue"] == ["23", "25", "35"] and len(started_args(s)) == 1 and started_args(s)[0].endswith("/release.sh --run-group 23 25 35")
      and "one group through the salamander merge queue" in s["qlog"] and not s["mq"], (s["rc"], s["started"], s["started_marks"], s["queue"], started_args(s), s["qlog"], s["out"]))
s = q("on-q-two", "23", "25", mqhost=ON)
check("release queue, mode on, two waiting: a group of two", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25"), (s["started"], started_args(s)))
s = q("on-q-five", "23", "25", "35", "36", "37", mqhost=ON)
check("release queue, mode on, five waiting: a group of four (release.sh's own cap), the fifth waits for the next hand-off", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 36") and s["queue"] == ["23", "25", "35", "36", "37"] and "the others (37) wait for the next hand-off" in s["out"], (s["started"], started_args(s), s["out"]))
s = q("on-q-one", "23", mqhost=ON)
check("release queue, mode on, one waiting: a lone release (release.sh --run 23), not a group",
      s["started"] == ["23"] and s["started_marks"] == ["23"] and len(started_args(s)) == 1 and started_args(s)[0].endswith("/release.sh --run 23") and "--run-group" not in started_args(s)[0] and not s["mq"], (s["started"], started_args(s)))
for nm, host in (("shadow", "shadow"), ("off", "off"), ("nofile", None)):
    s = q(f"on-q-three-{nm}", "23", "25", "35", mqhost=host)
    check(f"release queue, host file {nm}, three waiting: GitHub's queue, every PR's release at once (up to four), no group", s["started"] == ["23", "25", "35"] and "--run-group" not in "".join(started_args(s)) and s["started_marks"] == ["23", "25", "35"], (s["started"], started_args(s)))
s = q("on-q-startfail", "23", "25", "35", mqhost=ON, start_fail="23")
check("release queue, mode on: a group whose unit cannot start skips its lead, the count is taken again, and the other two go as a group", s["started"] == ["25"] and started_args(s)[0].endswith("/release.sh --run-group 25 35") and s["queue"] == ["25", "35"] and s["started_marks"] == ["25"]
      and "could not start the release led by PR #23" in s["out"], (s["started"], started_args(s), s["queue"], s["started_marks"], s["out"]))
s = q("on-q-paused", "23", "25", mqhost=ON, files={"releases/queue.paused": PAUSED})
check("release queue, mode on, paused: nothing starts, group or not", s["started"] == [] and "paused" in s["out"], (s["started"], s["out"]))
s = q("on-q-busy", "27", mqhost=ON, units="23", files=QF(["23", "25"], started=["23"]))
check("release queue, mode on, a release the queue started is running: nothing else starts (one at a time), the queued PR waits", s["started"] == [] and s["queue"] == ["23", "25", "27"] and "is running; it starts the next one when it is deployed" in s["out"], (s["started"], s["out"]))
s = q("on-q-killed", "27", mqhost=ON, units="", files=QF(["23", "25"], started=["23"]))
check("release queue, mode on, the started release is not running (killed): nothing else starts, the output says --resume starts it again", s["started"] == [] and "not running (killed?)" in s["out"] and "queue --resume" in s["out"], (s["started"], s["out"]))
s2 = q("on-q-resume", "--resume", mqhost=ON, reuse=s, units="")
check("…and queue --resume then starts the waiting PRs again, the dead lead's mark cleared (a group of the three)", s2["started"] == ["23"] and started_args(s2)[0].endswith("/release.sh --run-group 23 25 27"), (s2["started"], started_args(s2), s2["out"]))
s = q("on-q-list", "--list", mqhost=ON, units="23", files=QF(["23", "25"], started=["23"]))
check("queue --list in mode on shows the lead running and the other waiting", "PR #23: running" in s["out"] and "PR #25: waiting" in s["out"], s["out"])
s = scenario("on-group-door-one", raw=["--group", "23"], mqhost=ON, units="")
check("release.sh --group with one PR: usage, exit 2, nothing started", s["rc"] == 2 and "usage: release.sh --group" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = scenario("on-group-door-five", raw=["--group", "1", "2", "3", "4", "5"], mqhost=ON, units="")
check("release.sh --group with five PRs: refused (four at most), exit 2, nothing started", s["rc"] == 2 and "more than one hand-off" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = scenario("on-rungroup-bad", raw=["--run-group", "23", "x"], mqhost=ON, units="")
check("release.sh --run-group with a word that is not a PR number: usage, exit 2, no queue call", s["rc"] == 2 and "usage: release.sh --run-group" in s["out"] and not s["mq"], (s["rc"], s["out"]))
s = scenario("on-group-door-running", raw=["--group", "23", "25"], mqhost=ON, units="23")
check("release.sh --group while the lead's unit runs: says so, exit 1, nothing started", s["rc"] == 1 and "already running" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = scenario("on-group-door", raw=["--group", "23", "25"], mqhost=ON, units="")
check("release.sh --group 23 25: starts the unit stackshot-release-23 running --run-group 23 25", s["rc"] == 0 and s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25"), (s["rc"], s["out"], started_args(s)))

# -- a group: one `mq add`, a wait for each, one deploy through the deploy gate, a `done:` line per PR
s = grp("on-group-fast")
check("group of two (fast path): ONE `mq add 23 25`, then `mq wait` for each PR in turn, nothing else asked of the queue, no plain merge call and no enqueue",
      s["rc"] == 0 and s["mq"] == [MQ_ADD2, wait_(23), wait_(25)] and not merges(s) and "update-branch" not in s["gh"], (s["rc"], s["mq"], s["gh"], glog(s)[-600:]))
check("group of two (fast path): deployed ONCE, at the later merge commit, pinned (DEPLOY_TO), before main's run is read; the gate says why it deployed at once",
      s["deploys"] == [M2] and s["order"][:2] == [f"deploy:{M2}", "client:message"] and "deploying b2b2b2b at once" in glog(s) and "main's full run follows" in glog(s), (s["deploys"], s["order"], glog(s)[-900:]))
check("group of two: a `done:` line in EACH PR's own log (what a waiter and the board hooks read), the same sha; no FAILED in either",
      all(re.search(r"^.*done: [0-9a-f]{7}, restarted ", prlog(s, n), re.M) for n in (23, 25)) and all("FAILED" not in prlog(s, n) for n in (23, 25)), (prlog(s, 23), prlog(s, 25)))
check("group of two: ONE report per PR, each green on its own (--release green --pr <that PR>), each naming the other, with the fast deploy's note; the deploy ran under the deploy lock, not through fd 9 of its children",
      len(s["msgs"]) == 2 and s["msgs"][0].endswith("--release | green | --pr | https://github.com/example-owner/stackshot/pull/23") and s["msgs"][1].endswith("--pr | https://github.com/example-owner/stackshot/pull/25")
      and "merged by the merge queue in one group with #23 #25" in s["msgs"][0] and "main's full run follows" in s["msgs"][0] and s["locks"] == ["held"] and s["fd9"] == "closed", (s["msgs"], s["locks"], s["fd9"]))
check("group of two: main's run for the merge is read after the deploy and recorded (last good = the merge); the PRs are marked released; the markers are gone, the locks free",
      s["lastgood"] == M2 and len(s["released"]) == 2 and handed(s) == [] and lock_free(s), (s["lastgood"], s["released"], handed(s)))
check("group of two, started by the release queue: both PRs leave the queue file and the lead's mark goes (nothing else waits), nothing is started", s["queue"] == [] and s["started_marks"] == [] and s["started"] == [], (s["queue"], s["started_marks"], s["started"]))
s = grp("on-group-queue", files=QF(["23", "25", "35"], started=["23"]))
check("group started by the release queue with a third PR waiting: both PRs of the group leave the queue, the third starts alone (the count is one) after the deploy", s["rc"] == 0 and s["queue"] == ["35"] and s["started"] == ["35"] and s["started_marks"] == ["35"], (s["queue"], s["started"], s["started_marks"], s["qlog"]))
s = grp("on-group-byhand", files={})
check("a group release run by hand (nothing marked started): the same deploy, it touches nothing in the release queue", s["rc"] == 0 and s["deploys"] == [M2] and not s["started"] and not s["queue"], (s["rc"], s["queue"], s["started"]))
s = grp("on-group-three", prs=("23", "25", "35"), tip=M3)
check("group of three: one `mq add 23 25 35`, three waits, one deploy at the last merge commit, three `done:` lines and three reports",
      s["rc"] == 0 and s["mq"][0] == "mq add 23 25 35 --repo example-owner/stackshot" and len(s["mq"]) == 4 and s["deploys"] == [M3] and all("done: " in prlog(s, n) for n in (23, 25, 35)) and len(s["msgs"]) == 3, (s["mq"], s["deploys"], s["msgs"]))
s = grp("on-group-closed-gate", heads=STRAY, live=STRAY)
check("group of two when the live checkout is not behind the merge in the history (the deploy gate's (a) is closed): not the fast path; main's run for the merge is read BEFORE the single deploy, the reason is in the log",
      s["rc"] == 0 and s["deployed"] and s["order"][0] == "run-view" and "not deployed at the merge yet" in glog(s) and "(a) the live checkout" in glog(s) and all("done: " in prlog(s, n) for n in (23, 25)) and len(s["msgs"]) == 2, (s["order"], s["deploys"], glog(s)[-900:]))
s = grp("on-group-paused-gate", files={**QS, "releases/queue.paused": PAUSED})
check("a pause that is on disk before the group starts: it stops (queue paused) before anything is handed over", s["rc"] == 1 and "FAILED at queue paused" in glog(s) and not s["mq"] and not s["deployed"] and s["queue"] == ["23", "25"], (s["rc"], glog(s)[-400:], s["mq"], s["queue"]))
s = grp("on-group-live", heads=M2, live=M2)
check("group whose merge is live already (a later release deployed past it): nothing is deployed, `done:` says already live in each PR's log, main's full run is still waited for and recorded",
      s["rc"] == 0 and not s["deployed"] and all("already live" in prlog(s, n) and "done: " in prlog(s, n) for n in (23, 25)) and "already live" in s["msgs"][0] and s["lastgood"] == M2, (s["rc"], s["deploys"], glog(s)[-600:], s["msgs"], s["lastgood"]))
s = grp("on-group-pick", pickfiles="docs/a.md,client/hooks/session-start.sh")
check("group of two: ONE session pick from the files of both PRs (the start-loaded hook asks for a recycle), the recycle flagged per PR", s["rc"] == 0 and "session pick: recycle" in glog(s) and s["msg"].count("recycle-due") == 2, (glog(s)[-600:], s["msg"]))

# -- the queue ejects or fails one PR: the rest still go out
s = grp("on-group-eject-second", prs=("23", "25"), tip=M1, mq_prs=f"23=merged@{M1[:7]},25=ejected", files=QF(["23", "25"], started=["23"]))
check("group where the queue ejects the second PR: the first is deployed ONCE at its merge, with its `done:` line; the second is reported as a failed release of its own, with the queue's reason; the exit status is 1 (a PR failed)",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED at merge queue" in prlog(s, 25) and "conflicts with main or with PR #1 ahead of it" in prlog(s, 25) and "done: " not in prlog(s, 25)
      and "FAILED" not in prlog(s, 23), (s["rc"], s["deploys"], prlog(s, 23), prlog(s, 25), glog(s)[-600:]))
check("ejected second PR: one red report for it ([release] PR #25 FAILED at merge queue, naming the reason) and one green for the first; the group's failure pauses nothing and the queue goes on (both leave the queue file)",
      len(s["msgs"]) == 2 and sum("FAILED at merge queue" in m and "PR #25" in m for m in s["msgs"]) == 1 and sum("PR #23 merged and deployed" in m for m in s["msgs"]) == 1 and not s["paused"] and s["queue"] == [], (s["msgs"], s["paused"], s["queue"]))
check("ejected PR: its marker is gone (the queue no longer holds it) and it is not merged by a lone release's path; no `mq drop` was needed", handed(s) == [] and not merges(s) and not any(l.startswith("mq drop") for l in s["mq"]), (handed(s), s["mq"]))
s = grp("on-group-eject-notice", prs=("23", "25"), tip=M1, mq_prs=f"23=merged@{M1[:7]},25=ejected", files=QF(["23", "25"], started=["23"]), pickfiles="next_rules.py", notice="notify")
check("group where the queue ejects the second PR: the live notice names only the merged PR (#23), never the ejected one",
      len(s["notice"]) == 1 and s["notice"][0].startswith("release: stackshot PR #23 \u2014 stackshot PR #23 is live at ") and "#25" not in s["notice"][0], (s["notice"], s["msgs"]))
s = grp("on-group-eject-deploy-fails", prs=("23", "25"), tip=M1, mq_prs=f"23=merged@{M1[:7]},25=ejected", files=QF(["23", "25"], started=["23"]), deploy_fail="1")
check("group where the queue ejects the second PR and the deploy of the first fails: the group's red report names only the merged PR (#23), never the ejected one",
      (lambda d: s["rc"] == 1 and len(d) == 1 and "[release] PR #23 FAILED at deploy" in d[0] and "#25" not in d[0])([m for m in s["msgs"] if "FAILED at deploy" in m]), (s["rc"], s["msgs"]))
# plural-wording guard only: it passes on the code before the merged-names fix too
s = grp("on-group-notice-both", prs=("23", "25"), tip=M2, pickfiles="next_rules.py", notice="notify")
check("group where both PRs merge: the live notice names both, in the plural",
      len(s["notice"]) == 1 and s["notice"][0].startswith("release: stackshot PRs #23 #25 \u2014 stackshot PRs #23 #25 are live at "), s["notice"])
s = grp("on-group-eject-first", tip=M2, prs=("23", "25"), mq_prs=f"23=failed,25=merged@{M2[:7]}", fullshas=M2)
check("group where the queue fails the FIRST PR (its checks failed in the group): the second still goes out, once, with its `done:` line; the first reports the queue's reason", s["rc"] == 1 and s["deploys"] == [M2] and "done: " in prlog(s, 25) and "FAILED at merge queue" in prlog(s, 23) and "required check suites failed" in prlog(s, 23), (s["rc"], s["deploys"], prlog(s, 23), glog(s)[-500:]))
s = grp("on-group-none", mq_prs="23=failed,25=ejected", files=QF(["23", "25", "35"], started=["23"]))
check("group where the queue merges none of them: nothing deployed, both reported failed with their reasons, no pause (they were the PRs' own failures), the queue goes on with the next PR",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge queue" in prlog(s, 23) and "FAILED at merge queue" in prlog(s, 25) and len(red(s)) == 2 and not s["paused"] and s["queue"] == ["35"] and s["started"] == ["35"], (s["rc"], s["msgs"], s["queue"], s["started"], s["paused"]))

# -- any failure of the queue itself ends in a clear line and a pause of the release queue, never a silent drop and never a merge by a lone release's path
def paused_group(s, step):   # the failure is in the log, each PR's log, one red report, the release queue paused with the PRs still first in it, nothing deployed, and a lone release's path merged nothing
    return (s["rc"] == 1 and f"FAILED at {step}" in glog(s) and all(f"FAILED at {step}" in prlog(s, n) for n in (23, 25)) and len(red(s)) == 1 and s["paused"] and not merges(s) and not s["deployed"])
s = grp("on-group-add-refused", mq_add="refused", files=QF(["23", "25", "35"], started=["23"]))
check("mq add refused by salamander (its own `salamander mq:` message, exit 1): FAILED at mq add with the message, the queue paused with all three PRs still queued (first), nothing merged, no unit started for the next, the markers gone",
      paused_group(s, "mq add") and "is not open yet" in glog(s) and s["queue"] == ["23", "25", "35"] and not s["started"] and handed(s) == [], (s["rc"], glog(s)[-600:], s["queue"], s["paused"], handed(s)))
check("mq add refused: the PRs are let go of in the queue (a best-effort `mq drop` each) and told in the red report that `release.sh queue --resume` tries them again", s["mq"][1:] == ["mq drop 23 --repo example-owner/stackshot", "mq drop 25 --repo example-owner/stackshot"] and "queue --resume" in s["msgs"][0], (s["mq"], s["msgs"]))
s = scenario("on-group-after-refused", merge="ok", mqhost=ON, mq="off", reuse=s)
check("…and the same PR released alone afterwards goes through run() (no `mq line` refusal: the markers were cleared although the real `mq drop` of a PR never added exits 1 with `is not in the line`)",
      s["rc"] == 0 and s["deployed"] and "mq line" not in s["log"] and plain_merges(s), (s["rc"], s["log"][-400:]))
s = grp("on-group-add-timeout", mq_add="timeout", extra={"RELEASE_MQ_ON_ADD_TIMEOUT": "1"}, files=QF(["23", "25"], started=["23"]), secs=60)
check("mq add that never answers (cut at RELEASE_MQ_ON_ADD_TIMEOUT): FAILED at mq add, saying it took more than the cap; the release queue paused; nothing merged", paused_group(s, "mq add") and "took more than 1s" in glog(s), (s["rc"], glog(s)[-500:], s["paused"]))
s = grp("on-group-nosal", nosalamander=True, files=QF(["23", "25"], started=["23"]))
check("no salamander on PATH: FAILED at mq, nothing merged, the release queue paused, no marker left", paused_group(s, "mq") and handed(s) == [], (s["rc"], glog(s)[-400:], handed(s)))
s = grp("on-group-wait-error", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", files=QF(["23", "25", "35"], started=["23"]))
check("mq wait fails with salamander's own error AFTER the first PR merged: the merged PR is DEPLOYED all the same (once, at its merge, with its `done:` line and its green report) and never logged FAILED; only the unresolved PR is: FAILED at mq wait with the message, dropped from the merge queue (the merged one is not), one red report for it",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "FAILED at mq wait" in prlog(s, 25) and "state file unreadable" in prlog(s, 25) and "done: " not in prlog(s, 25)
      and "mq drop 25 --repo example-owner/stackshot" in s["mq"] and "mq drop 23 --repo example-owner/stackshot" not in s["mq"] and not merges(s)
      and sum("FAILED at mq wait" in m and "PRs #25" in m for m in s["msgs"]) == 1 and sum("PR #23 merged and deployed" in m for m in s["msgs"]) == 1 and len(red(s)) == 1 and handed(s) == [], (s["rc"], glog(s)[-900:], s["mq"], s["msgs"]))
check("…and the release queue is paused (written before the deploy's lock was let go), the merged PR leaves the queue file, the unresolved one stays first with the one behind it, nothing is started",
      s["paused"] and s["queue"] == ["25", "35"] and s["started"] == [] and "mq wait" in s["paused"], (s["paused"], s["queue"], s["started"]))
s = grp("on-group-notinline", mq_prs="23=notinline,25=notinline", files=QF(["23", "25"], started=["23"]))
check("mq wait says the PR is not in the line (exit 2, not a give-up): FAILED at mq wait, the release queue paused, nothing merged", paused_group(s, "mq wait") and "is not in the line" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-tested", mq_prs="23=tested,25=tested", files=QF(["23", "25"], started=["23"]))
check("mq wait answers the shadow verdict (exit 3: the queue is not in mode on): not a verdict a group can use, FAILED at mq wait, paused, nothing merged", paused_group(s, "mq wait") and "exited 3" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-gaveup-paused", mq_prs="23=gaveup,25=gaveup", mq_status="paused", files=QF(["23", "25"], started=["23"]))
check("a wait slice ran out and the queue says it is paused (mq status): FAILED at mq, with the queue's reason, the PRs dropped, the release queue paused, nothing merged, the markers gone",
      paused_group(s, "mq") and "the merge queue is paused: the merge push failed 5 times" in glog(s) and "mq drop 23 --repo example-owner/stackshot" in s["mq"] and any(l.startswith("mq status --json") for l in s["mq"]) and handed(s) == [], (s["rc"], glog(s)[-600:], s["mq"]))
s = grp("on-group-gaveup-blocked", mq_prs="23=gaveup,25=gaveup", mq_status="blocked", files=QF(["23", "25"], started=["23"]))
check("the same for a queue that is blocked (a bad repo config): FAILED at mq with `blocked: bad repo config`", paused_group(s, "mq") and "blocked: bad repo config" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-gaveup-cap", mq_prs="23=gaveup,25=gaveup", extra={"RELEASE_MQ_WAIT_CAP": "700"}, files=QF(["23", "25"], started=["23"]))
check("a queue that stays healthy but gives no verdict: the wait goes on in slices (each followed by one look at the queue) until RELEASE_MQ_WAIT_CAP, then FAILED at mq wait naming the cap, the PRs dropped, the release queue paused",
      paused_group(s, "mq wait") and "gave no verdict on PR #23 within 700s" in glog(s) and s["mq"].count(wait_(23)) + s["mq"].count(wait_(23, 100)) >= 2 and sum(l.startswith("mq status --json") for l in s["mq"]) >= 2 and "mq drop 25 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-600:], s["mq"]))
s = grp("on-group-drop-fails", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", mq_drop="fail", mq_status="active", files=QF(["23", "25"], started=["23"]))
check("a drop that fails for another reason (the queue state cannot be locked) while `mq status` still lists the PR as active: its marker stays (a lone release's path refuses it) and the log says so, with the command",
      "could not be dropped from the merge queue (salamander mq drop 25: salamander mq: cannot lock the queue state)" in glog(s) and handed(s) == ["pr-25"] and s["paused"], (glog(s)[-600:], handed(s)))
s = scenario("on-group-after-drop-fails", merge="ok", mqhost=ON, mq="off", reuse=s, raw=["--run", "25"], pr="25")
check("... and run() then refuses PR 25 on its marker: nothing merged", s["rc"] == 1 and "FAILED at mq line" in prlog(s, 25) and not merges(s), (s["rc"], s["out"][-300:]))
s = grp("on-group-drop-fails-gone", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", mq_drop="fail", files=QF(["23", "25"], started=["23"]))
check("a drop that fails but `mq status` lists no active entry for the PR: the queue does not hold it, so the marker goes", handed(s) == [] and s["paused"], (glog(s)[-400:], handed(s)))
s = grp("on-group-mode-changed", mqhost="shadow", files=QF(["23", "25"], started=["23"]))
check("the host file went from on to shadow before the group started: FAILED at mq mode, nothing handed to the queue (no `mq` call), the release queue paused with the PRs still first", paused_group(s, "mq mode") and not s["mq"] and "now \"shadow\"" in glog(s), (s["rc"], glog(s)[-400:], s["mq"]))
s = grp("on-group-nolock", mqhost='mode = "on"\n', files=QF(["23", "25"], started=["23"]))
check("the host file lost its deploy_lock: FAILED at mq mode, nothing handed over, the release queue paused", paused_group(s, "mq mode") and not s["mq"] and "deploy_lock" in glog(s), (s["rc"], glog(s)[-400:]))
s = grp("on-group-qpaused", files={**QF(["23", "25"], started=["23"]), "releases/queue.paused": "PR #22 failed at main's tests after its merge\n"})
check("a group the release queue started and a pause that came before it ran: nothing handed to the queue, nothing merged; the PRs stay first in the release queue", s["rc"] == 1 and "FAILED at queue paused" in glog(s) and not s["mq"] and not s["deployed"] and s["queue"] == ["23", "25"], (s["rc"], glog(s)[-400:], s["mq"], s["queue"]))
s = grp("on-group-byhand", mq_add="refused", files={})
check("a group release run by hand (not started by the release queue): the same failure, but it pauses nothing in the release queue", s["rc"] == 1 and "FAILED at mq add" in glog(s) and not s["paused"], (s["rc"], glog(s)[-300:], s["paused"]))

# -- the real wording of salamander's answers (lib/mq/mq_cli.py): the blocked line (exit 2, no "gave up"), exit 4, a driver line on stderr before the verdict, a PR the queue ejects because it is merged already
s = grp("on-group-driverline", mq_driverline="1")
check("a line on stderr before the verdict (`driver started`, printed when `mq wait` had to start the driver again): the verdict is the line that starts with `PR n`, so the merge commit is found and the group deploys",
      s["rc"] == 0 and s["deploys"] == [M2] and "merge queue: PR 23 merged: merged in group g1 at a1a1a1a" in glog(s) and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["deploys"], glog(s)[-600:]))
check("the real `mq add` answer (`PR n: queued` for each PR, then the `mode on: ...` line) is read: the log names the last line", "handed over in one call (mode on: tested groups are merged into main; driver started" in glog(s), glog(s)[:700])
s = grp("on-group-blocked", mq_prs="23=blocked,25=blocked", files=QF(["23", "25"], started=["23"]))
check("the real blocked answer (`PR n is waiting and the queue is blocked: ...`, exit 2 with no `gave up`): FAILED at mq with the queue's reason, the PRs dropped, the release queue paused, nothing merged",
      paused_group(s, "mq") and "the merge queue is blocked" in glog(s) and "bad repo config" in glog(s) and "mq drop 23 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-500:]))
s = grp("on-group-skipped", mq_prs="23=skipped,25=skipped", files=QF(["23", "25"], started=["23"]))
check("exit 4 (a replay that built the group and tested nothing): not a verdict a group can use, FAILED at mq wait naming the exit status, paused, nothing merged", paused_group(s, "mq wait") and "exited 4" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-ejected-merged", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", prstate_after=f"23=MERGED@{M1}")
check("the queue ejects a PR with `pull request is merged` and GitHub says it is merged (the queue merged it in an earlier push of the group): it is on main, so it is deployed with the group, `done:` in both logs, never logged FAILED, not dropped from the queue, no red report",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop 23" not in "\n".join(s["mq"]) and red(s) == [] and handed(s) == [],
      (s["rc"], prlog(s, 23), s["deploys"], s["mq"], s["msgs"]))
s = grp("on-group-ejected-open", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", files=QF(["23", "25"], started=["23"]))
check("…and the same ejection of a PR GitHub still shows open is that PR's failure with the queue's words (as before), the other goes out",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge queue" in prlog(s, 23) and "pull request is merged" in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))

# -- a merge happened, then the queue could not go on: the merged PRs are deployed, only the unresolved ones fail
s = grp("on-group-cap-merged", prs=("23", "25", "35"), tip=M2, mq_prs=f"23=merged@{M1[:7]},25=merged@{M2[:7]},35=gaveup", extra={"RELEASE_MQ_WAIT_CAP": "400"}, files=QF(["23", "25", "35"], started=["23"]))
check("two PRs merged and the third gets no verdict within the cap: the two are deployed once (`done:` in both logs, no FAILED in either), the third alone is reported FAILED at mq wait (dropped from the queue), the release queue is paused with only the third left in it",
      s["rc"] == 1 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "FAILED at mq wait" in prlog(s, 35) and "gave no verdict on PR #35 within 400s" in prlog(s, 35)
      and "mq drop 35 --repo example-owner/stackshot" in s["mq"] and s["paused"] and s["queue"] == ["35"] and s["started"] == [] and len(s["msgs"]) == 3, (s["rc"], s["deploys"], glog(s)[-900:], s["queue"], s["msgs"]))
check("…the reports: green for each merged PR, one red for the third naming the step and that the merged ones were deployed", sum("merged and deployed" in m for m in s["msgs"]) == 2 and sum("PRs #35 FAILED at mq wait" in m and "#23 #25, merged by the same group, are deployed next" in m for m in s["msgs"]) == 1, s["msgs"])
s = grp("on-group-paused-merged", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=gaveup", mq_pauseq="1", files=QF(["23", "25"], started=["23"]))
check("a pause of release.sh's own queue (a lone release rolled back) while the group waits for its second PR, after the first merged: the first is deployed, the second is dropped from the merge queue and reported FAILED at queue paused, stays first in the release queue; the original pause text stands",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "FAILED at queue paused" in prlog(s, 25) and "mq drop 25 --repo example-owner/stackshot" in s["mq"]
      and s["queue"] == ["25"] and s["started"] == [] and s["paused"].startswith("PR #22 failed at the main tests"), (s["rc"], s["deploys"], glog(s)[-700:], s["queue"], s["paused"]))
s = grp("on-group-paused-none", mq_prs="23=gaveup,25=gaveup", mq_pauseq="1", files=QF(["23", "25"], started=["23"]))
check("the same pause with nothing merged yet: FAILED at queue paused, both PRs dropped from the merge queue, nothing merged or deployed, both stay first in the release queue, the lead's mark goes, the pause is the one that was there",
      s["rc"] == 1 and "FAILED at queue paused" in glog(s) and all("FAILED at queue paused" in prlog(s, n) for n in (23, 25)) and not s["deployed"] and not merges(s) and s["queue"] == ["23", "25"] and s["started_marks"] == []
      and s["paused"].startswith("PR #22 failed at the main tests") and handed(s) == [] and "mq drop 23 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-600:], s["queue"], s["started_marks"], s["paused"]))
s = grp("on-group-nosha", mq_prs=f"23=mergednosha,25=merged@{M2[:7]}", prstate_after=f"23=MERGED@{M1}", files=QF(["23", "25"], started=["23"]))
check("an answer that names no merge commit: GitHub is asked for it (state, mergeCommit), and the group deploys at the later one", s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["deploys"], glog(s)[-600:]))
s = grp("on-group-nosha-lost", tip=M2, mq_prs=f"23=mergednosha,25=merged@{M2[:7]}", fullshas=M2, files=QF(["23", "25"], started=["23"]))
check("…and when GitHub cannot name it either: that PR alone is reported merged, not live (FAILED at merge commit, never `done:`), the other is deployed", s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge commit" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " not in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))

# -- a PR merged on GitHub already (an earlier run of the group was killed after the queue merged it): deployed with the group, never handed to the queue again
s = grp("on-group-premerged", tip=M2, prstate=f"23=MERGED@{M1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", files=QF(["23", "25"], started=["23"]))
check("one PR of the group is merged on GitHub already: only the other is handed to the queue (`mq add 25`, one wait), both are deployed once at the later merge commit, both get `done:`, neither is logged FAILED, and the report says the first had been merged by an earlier run",
      s["rc"] == 0 and s["mq"] == ["mq add 25 --repo example-owner/stackshot", wait_(25)] and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "#23 had been merged by an earlier run of this group" in s["msgs"][0] and handed(s) == [], (s["rc"], s["mq"], s["deploys"], s["msgs"]))
s = grp("on-group-premerged-all", tip=M2, prstate=f"23=MERGED@{M1},25=MERGED@{M2}", mq_prs="", files=QF(["23", "25"], started=["23"]))
check("every PR of the group is merged on GitHub already: no call to the queue at all, one deploy of the later merge commit, `done:` for both", s["rc"] == 0 and not s["mq"] and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["mq"], s["deploys"], glog(s)[-500:]))
s = grp("on-group-closed", tip=M1, prstate="25=CLOSED", mq_prs=f"23=merged@{M1[:7]}", files=QF(["23", "25"], started=["23"]))
check("a PR of the group that was closed meanwhile: reported FAILED at pr state on its own, never handed to the queue; the other goes through (`mq add 23`) and is deployed", s["rc"] == 1 and s["mq"][0] == "mq add 23 --repo example-owner/stackshot" and "FAILED at pr state" in prlog(s, 25) and s["deploys"] == [M1] and "done: " in prlog(s, 23), (s["rc"], s["mq"], prlog(s, 25)))

# -- the queue merges a group in one push: a PR whose wait is not reached (a pause, the cap, a queue error) may be on main already
s = grp("on-group-pause-then-merged", mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", files=QF(["23", "25"], started=["23"]))
check("the first PR merged and release.sh's queue was paused right after, the second was merged by the same push: it is read from GitHub before it is dropped, so both are deployed once, `done:` in both logs, none FAILED, no drop of the second, no wait for it, no red report",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and not any("mq drop" in l or "mq wait 25" in l for l in s["mq"]) and red(s) == [] and handed(s) == [],
      (s["rc"], s["deploys"], glog(s)[-800:], s["mq"], s["msgs"]))
check("…and the pause that was there stands; nothing is started behind the group; both leave the release queue", s["paused"].startswith("PR #22 failed at the main tests") and s["started"] == [] and s["queue"] == [], (s["paused"], s["started"], s["queue"]))
s = grp("on-group-error-then-merged", mq_prs=f"23=merged@{M1[:7]},25=error", prstate_after=f"25=MERGED@{M2}", files=QF(["23", "25"], started=["23"]))
check("a `salamander mq:` error on the second wait while GitHub shows it merged: deployed with the first, none FAILED, the unit ends 0",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop 25" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-600:], s["mq"]))
s = grp("on-group-pause-one-merged", prs=("23", "25", "35"), tip=M2, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", files=QF(["23", "25", "35"], started=["23"]))
check("of the two PRs behind the first, one is merged on GitHub and one is not: the merged one is deployed, the other alone is FAILED (dropped from the queue, still first in the release queue), the release queue is paused",
      s["rc"] == 1 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "FAILED at queue paused" in prlog(s, 35) and "mq drop 35 --repo example-owner/stackshot" in s["mq"] and "mq drop 25" not in "\n".join(s["mq"])
      and s["queue"] == ["35"] and s["paused"], (s["rc"], s["deploys"], glog(s)[-700:], s["queue"]))

s = grp("on-group-lost-and-unresolved", mq_prs="23=gaveup", mq_pauseq="1", prstate_after="23=MERGED#-", files=QF(["23", "25"], started=["23"]))
check("the first PR is merged on GitHub with no commit to name (merged, not live), the release queue was paused while the group waited and the second is unresolved: the second is dropped from the merge queue and FAILED, the first is not called unmerged (`nothing was merged` is not said), nothing is deployed",
      s["rc"] == 1 and not s["deploys"] and "merged, not live" in prlog(s, 23) and "FAILED at queue paused" in prlog(s, 25) and "mq drop 25 --repo example-owner/stackshot" in s["mq"] and "nothing was merged" not in glog(s) and "mq drop 23" not in "\n".join(s["mq"]), (s["rc"], glog(s)[-900:], s["mq"]))
check("…the lost PR leaves the release queue file, the unresolved one stays first, the pause that was there stands, nothing is started",
      s["queue"] == ["25"] and s["paused"].startswith("PR #22 failed at the main tests") and s["started"] == [], (s["queue"], s["paused"], s["started"]))

# -- GitHub cannot be read when the group looks at a PR it has no answer for
s = grp("on-group-state-unreadable", tip=M1, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", prstate_failn="99", files=QF(["23", "25"], started=["23"]))
check("the first PR merged, the release queue was paused, and GitHub's state of the second cannot be read (twice, with a pause between): the second is NOT dropped from the merge queue and not called FAILED or not merged, its marker stays, it is reported unresolved with the reason, and the merged first is deployed",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "mq drop" not in "\n".join(s["mq"]) and handed(s) == ["pr-25"] and "pr state unreadable" in prlog(s, 25) and "FAILED" not in prlog(s, 25) and "3" in s["sleeps"], (s["rc"], s["deploys"], glog(s)[-900:], s["mq"], handed(s), s["sleeps"]))
check("…and it stays first in the release queue, which is paused", s["queue"] == ["25"] and s["paused"], (s["queue"], s["paused"]))
s = grp("on-group-state-flaky", mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", prstate_failn="1", files=QF(["23", "25"], started=["23"]))
check("…one failed read is tried again: the second is then found merged and deployed with the first, none FAILED", s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-600:]))

# -- a PR whose state is unknown is unresolved, never FAILED
s = grp("on-group-unknown-nothing", mq_prs="23=gaveup,25=gaveup", mq_pauseq="1", prstate_failn="99", prstate_after="999=OPEN", files=QF(["23", "25"], started=["23"]))
check("the release queue was paused while the group waited, nothing is known to be merged and GitHub cannot be read: neither PR is logged FAILED (each gets the `unresolved ... pr state unreadable` line), neither is dropped from the merge queue, both markers stay, 'nothing was merged' is not claimed, both stay in the release queue",
      s["rc"] == 1 and all("unresolved at queue paused" in prlog(s, n) and "pr state unreadable" in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop" not in "\n".join(s["mq"]) and handed(s) == ["pr-23", "pr-25"]
      and "nothing was merged" not in glog(s) and "no PR is known to be merged" in glog(s) and s["queue"] == ["23", "25"] and not s["deploys"], (s["rc"], glog(s)[-900:], s["mq"], handed(s), s["queue"]))
s = grp("on-group-unknown-ejected", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", prstate_failn="99", prstate_after="999=OPEN", files=QF(["23", "25"], started=["23"]))
check("the queue ejects a PR as merged and GitHub's state of it cannot be read: it is NOT reported FAILED, not dropped, its marker stays, it is logged unresolved (pr state unreadable) and stays first in the release queue (paused); the PR that merged is deployed",
      s["rc"] == 1 and s["deploys"] == [M2] and "done: " in prlog(s, 25) and "unresolved" in prlog(s, 23) and "pr state unreadable" in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "mq drop 23" not in "\n".join(s["mq"]) and handed(s) == ["pr-23"]
      and s["queue"] == ["23"] and s["paused"], (s["rc"], s["deploys"], prlog(s, 23), glog(s)[-700:], s["mq"], handed(s), s["queue"]))
s = grp("on-group-premerged-marker", tip=M2, prstate=f"23=MERGED@{M1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-23": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"})
check("a PR merged by an earlier run of the group that left its marker: the marker is removed when the PR joins the deploy", s["rc"] == 0 and handed(s) == [] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], handed(s)))


# mq_landing on a real repository: the queue's --no-ff merges of three PR branches into a group branch, main moved to the group head by fast-forward
ml = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-landing-")); dirs.append(ml)
mp = ml / "r"; g("init", "-q", "-b", "main", str(mp))
def mcommit(name, text, msg):
    (mp / name).write_text(text); g("add", "-A", cwd=mp); g("commit", "-qm", msg, cwd=mp); return g("rev-parse", "HEAD", cwd=mp)
c0 = mcommit("README.md", "0\n", "live")
heads = {}
for n in ("a", "b", "c"):
    g("checkout", "-q", "-b", "pr-" + n, c0, cwd=mp); heads[n] = mcommit(n + ".py", n + " = 1\n", "work " + n)
g("checkout", "-q", "-b", "group", c0, cwd=mp)
mrg = {}
for n in ("a", "b", "c"):
    g("merge", "-q", "--no-ff", "-m", "Merge pull request #%d from agent/%s" % (ord(n) - 96, n), "pr-" + n, cwd=mp); mrg[n] = g("rev-parse", "HEAD", cwd=mp)
g("update-ref", "refs/remotes/origin/main", mrg["c"], cwd=mp)   # main is fast-forwarded to the group head
(ml / "h.sh").write_text('set -u\neval "$(sed -n \'/^mq_landing() {/,/^}/p\' "$1")"\ncd "$2"\nmq_landing "$3"\n')
def landing(h): return subprocess.run(["bash", str(ml / "h.sh"), os.path.join(STACK, "release.sh"), str(mp), h], env=genv, capture_output=True, text=True, timeout=60).stdout.strip()
check("real git: each PR head of a --no-ff group pushed by fast-forward lands on its own merge commit on main's first-parent line (the earliest one that has the head in its ancestry)", [landing(heads[n]) for n in "abc"] == [mrg[n] for n in "abc"], ([landing(heads[n]) for n in "abc"], mrg))
check("real git: a commit on the first-parent line itself is its own landing commit; a commit that is not in main prints nothing", landing(c0) == c0 and landing("0" * 40) == "", (landing(c0), landing("0" * 40)))

# -- the queue merges by fast-forward push: GitHub may name no merge commit for a PR, its head is on main then
H1 = "d1d1d1d" + "0" * 33; H2 = "d2d2d2d" + "0" * 33; H3 = "d3d3d3d" + "0" * 33   # PR heads: the second parent of the queue's --no-ff merge commits
HIST_H = ",".join([GOOD, BASE, M1, M2, M3, H1, H2, H3])
s = grp("on-group-ff-one", prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", landing=f"{H1}={M2}/{M1}", fullshas=f"{M1},{M2},{H1}", files=QF(["23", "25"], started=["23"]))
check("one PR merged already for which GitHub names no merge commit (the queue pushes the group head by fast-forward): its HEAD is not taken as the sha, the commit of main's first-parent line that brought it in is (the earliest: M1, not the later M2), so both are deployed once at M2, `done:` for both, none FAILED",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and f"rev-list --first-parent --ancestry-path {H1}..origin/main" in s["git"] and "landed on main as a1a1a1a" in glog(s), (s["rc"], s["deploys"], glog(s)[-700:], s["git"][-500:]))
s = grp("on-group-ff-two", prs=("23", "25", "35"), tip=M3, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED#{H2},35=MERGED#{H3}", landing=f"{H2}={M3}/{M2},{H3}={M3}", fullshas=f"{M1},{M2},{M3},{H2},{H3}", files=QF(["23", "25", "35"], started=["23"]))
check("two PRs adopted after the first merged, each with a head and no merge commit: each is resolved to its own landing commit (M2 and M3, one line), the deploy is pinned to M3 (not to a head), all three get `done:`, none FAILED, no drop",
      s["rc"] == 0 and s["deploys"] == [M3] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25, 35)) and "mq drop" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-900:], s["mq"]))
s = grp("on-group-ff-ontheline", tip=M2, history=",".join([GOOD, BASE, H1, M2]), prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", fplist=f"{M2},{H1}", fullshas=f"{H1},{M2}", files=QF(["23", "25"], started=["23"]))
check("a head that is itself on main's first-parent line (merged by fast-forward) is its own landing commit",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)) and "landed on main as d1d1d1d" in glog(s), (s["rc"], s["deploys"], glog(s)[-700:]))
s = grp("on-group-ff-nolanding", prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", fullshas=f"{M1},{M2},{H1}", files=QF(["23", "25"], started=["23"]))
check("…and a head that is not found on main's first-parent line is that PR alone reported merged, not live (FAILED at merge commit), the other is deployed, the lost one leaves the release queue",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge commit" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " in prlog(s, 25) and "23" not in s["queue"], (s["rc"], prlog(s, 23), s["deploys"], s["queue"]))
s = grp("on-group-ff-nolanding-all", prstate=f"23=MERGED#{H1},25=MERGED#{H2}", mq_prs="", fullshas=f"{M1},{M2},{H1},{H2}", files=QF(["23", "25"], started=["23"]))
check("every PR merged but none can be placed on main: nothing is deployed, both are merged, not live, the release queue is paused and both leave its file",
      s["rc"] == 1 and not s["deploys"] and all("merged, not live" in prlog(s, n) for n in (23, 25)) and s["paused"] and s["queue"] == [] and s["started"] == [], (s["rc"], s["deploys"], s["paused"], s["queue"]))
s = grp("on-group-premerged-nothing", tip=M2, prstate="23=MERGED#-,25=OPEN", mq_prs=f"25=merged@{M2[:7]}", fullshas=M2, files=QF(["23", "25"], started=["23"]))
check("…and when GitHub names neither a merge commit nor a head: that PR alone is FAILED at pr state as merged, not live; the other is deployed",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at pr state" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))
s = grp("on-group-nosha-lost-only", tip=M2, mq_prs="23=mergednosha,25=mergednosha", fullshas=M2, files=QF(["23", "25"], started=["23"]))
check("every PR of the group merged but no commit can be named for either: nothing is deployed, both are reported merged, not live, and the release queue is PAUSED (not handed on), the merged PRs out of its file",
      s["rc"] == 1 and not s["deploys"] and all("merged, not live" in prlog(s, n) and "FAILED at merge commit" in prlog(s, n) for n in (23, 25)) and s["paused"] and s["queue"] == [] and s["started"] == [], (s["rc"], s["deploys"], s["paused"], s["queue"], s["started"]))

# -- the hand-off is release.sh's own 4 PRs; no key of the rules file changes it (the queue is a chain, an entry is one PR)
s = q("on-q-chain-nokey", "23", "25", "35", "37", "44", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\n'})
check("chain rules, no other key: five waiting go as a hand-off of the first four, the fifth waits for the next", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37"), (started_args(s), s["out"]))
s = q("on-q-stale-one", "23", "25", "35", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 1\n'})
check("a retired `group_max = 1` left in the rules file is not read: still a hand-off, not the one-at-a-time old path", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35"), (started_args(s), s["out"]))
s = q("on-q-stale-fifty", "23", "25", "35", "37", "44", "45", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 50\ninflight_max = 3\n'})
check("a retired `group_max = 50` is not read either: six waiting go as a hand-off of the first four", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37"), (started_args(s), s["out"]))
s = scenario("on-group-door-stale", raw=["--group", "23", "25", "35"], mqhost=ON, units="", files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 1\n'})
check("release.sh --group with a retired `group_max = 1` in the rules file: not refused (the file is not read for the hand-off size)", "group_max" not in s["out"] and s["rc"] != 2, (s["rc"], s["out"]))

# -- queue --drop of a PR with a stale marker
STALE = "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"
s = q("on-q-drop-stale", "--drop", "25", mqhost=ON, files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": STALE})
check("queue --drop of a PR whose marker is stale (its group release is gone and `mq status` no longer lists the PR): the marker is removed, named, and the PR is dropped as usual",
      s["rc"] == 0 and "stale marker" in s["out"] and "releases/mq-on/pr-25" in s["out"] and "dropped PR #25" in s["out"] and handed(s) == [] and s["queue"] == ["23"], (s["rc"], s["out"], handed(s), s["queue"]))
s = q("on-q-drop-stale-off", "--drop", "25", mqhost='mode = "off"\n', files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": STALE})
check("…the host file no longer on: the marker means nothing, it goes and the PR is dropped", s["rc"] == 0 and "dropped PR #25" in s["out"] and handed(s) == [], (s["rc"], s["out"], handed(s)))
s = q("on-q-drop-live", "--drop", "25", mqhost=ON, units="23", files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": STALE})
check("…but while its group release is running the marker is that release's own: refused, the marker path named, nothing changed",
      s["rc"] == 1 and "releases/mq-on/pr-25" in s["out"] and "dropped PR #25" not in s["out"] and handed(s) == ["pr-25"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], handed(s), s["queue"]))

s = q("on-q-drop-bad-host", "--drop", "25", mqhost='mode = "bogus"\n', mq_status="error", files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": STALE})
check("queue --drop while the host file does not read (a file mid-edit) and `mq status` cannot be read either: the marker is NOT taken for stale, refused, the marker stays",
      s["rc"] == 1 and handed(s) == ["pr-25"] and "dropped PR #25" not in s["out"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], handed(s), s["queue"]))
s = q("on-q-drop-bad-host-gone", "--drop", "25", mqhost='mode = "bogus"\n', files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": STALE})
check("…with a host file that does not read but `mq status` answering that the PR is not held: mq status decides, the marker goes", s["rc"] == 0 and handed(s) == [] and "dropped PR #25" in s["out"], (s["rc"], s["out"], handed(s)))


# -- both paths never handle one PR
s = grp("on-group-unit-running", units="25", files=QF(["23", "25"], started=["23"]))
check("a PR of the group has its own release unit running (a lone release by hand): the group is refused before anything is handed over (FAILED at release running), no call to the queue, nothing merged, the release queue paused",
      paused_group(s, "release running") and not s["mq"] and "stackshot-release-25" in glog(s), (s["rc"], glog(s)[-400:], s["mq"]))
for flag in ("--group", "--run-group"):
    s = scenario("on-dup" + flag, raw=[flag, "23", "23"], mqhost=ON, units="")
    check(f"release.sh {flag} 23 23: the same PR twice is refused (usage, exit 2), nothing started, no call to the queue", s["rc"] == 2 and "different PR numbers" in s["out"] and not s["started"] and not s["mq"], (s["rc"], s["out"]))
s = scenario("on-group-door-toomany", raw=["--group", "23", "25", "35", "37", "44"], mqhost=ON, units="")
check("release.sh --group with more PRs than one hand-off (4, release.sh's own number): refused with the number, nothing started", s["rc"] == 2 and "4 at most" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = q("on-q-five", "23", "25", "35", "37", "44", mqhost=ON)
check("release queue, mode on, five waiting: one hand-off of the first four (release.sh's own 4); the fifth stays queued for the next hand-off",
      s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37") and s["queue"] == ["23", "25", "35", "37", "44"] and "44" in s["out"] and "next hand-off" in s["out"], (s["started"], started_args(s), s["queue"], s["out"]))
s = q("on-q-drop-handed", "--drop", "25", mqhost=ON, mq_status="active", files={**QF(["23", "25"], started=["23"]), "releases/mq-on/pr-25": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"})
check("queue --drop of a PR a group release handed to the merge queue: says so and what to run (salamander mq drop), is not reported as dropped, exit 1, the release queue unchanged",
      s["rc"] == 1 and "handed to the merge queue" in s["out"] and "salamander mq drop 25" in s["out"] and "dropped PR #25" not in s["out"] and "releases/mq-on/pr-25" in s["out"] and handed(s) == ["pr-25"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], s["queue"]))
s = q("on-q-drop-plain", "--drop", "25", mqhost=ON, files=QF(["23", "25"], started=["23"]))
check("queue --drop of a PR that is not with the merge queue: as before", s["rc"] == 0 and "dropped PR #25" in s["out"] and s["queue"] == ["23"], (s["rc"], s["out"], s["queue"]))

# -- after the merge: what a lone release's path does for its own deploy and its own failures
s = grp("on-group-unknown-sha", fullshas="", files=QF(["23", "25"], started=["23"]))
check("a merge commit the checkout cannot name after the fetch: FAILED at merge commit with `merged, not live (./deploy.sh by hand)`, the release queue paused (a merge happened: the merged PRs are out of its file), nothing deployed",
      s["rc"] == 1 and "FAILED at merge commit" in glog(s) and "merged, not live" in glog(s) and s["paused"] and not s["deployed"] and not merges(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-fetch-fails", fetch_fails="9", files=QF(["23", "25"], started=["23"]))
check("main cannot be fetched after the merge: FAILED at merge commit, merged and not deployed, the release queue paused", s["rc"] == 1 and "FAILED at merge commit" in glog(s) and s["paused"] and not s["deployed"], (s["rc"], glog(s)[-400:]))
s = grp("on-group-deploy-fails", deploy_fail="1", files=QF(["23", "25", "35"], started=["23"]))
check("the deploy of the merge fails (healthz): FAILED at deploy, one red report for the group, the release queue paused before the lock is let go, the third PR not started; no `done:` line in either PR's log",
      s["rc"] == 1 and "FAILED at deploy" in glog(s) and s["paused"] and not s["started"] and len(red(s)) == 1 and all("done: " not in prlog(s, n) for n in (23, 25)) and all("FAILED at deploy" in prlog(s, n) for n in (23, 25)), (s["rc"], glog(s)[-500:], s["paused"], s["started"]))
s = grp("on-group-main-fails", main="fail", heads=f"{BASE},{M2}", live=M2, removed=GLOG, covered=GLOG, files=QF(["23", "25"], started=["23"]))
check("main's run fails on the group's merge after the fast deploy: rolled back to the last good commit, FAILED at main's tests, the release queue paused (pause on disk before the lock is let go), the PRs not marked released",
      s["rc"] == 1 and "FAILED at main's tests" in glog(s) and s["deploys"][-1].startswith("rollback") and s["paused"] and s["paused_at_rollback"] == "present" and not s["released"], (s["rc"], s["deploys"], glog(s)[-700:], s["paused"], s["paused_at_rollback"]))
check("…and the rollback names none of the group's own members as a rider (no `PR #23 was rolled back with #23`): no PR is told it was rolled back with itself, and no member gets a rolled-back marker",
      not any("was rolled back with" in m for m in s["msgs"]) and not (s["dir"] / "releases/pr-23.rolledback").exists() and not (s["dir"] / "releases/pr-25.rolledback").exists(), (s["msgs"],))
s = grp("on-group-lock-held", hold="until-waiting", files=QF(["23", "25"], started=["23"]))   # never a fixed second: a measured start can reach the lock after it was let go
check("the deploy lock is held by a lone release (its merge or deploy under way): the group waits for it before its deploy, and the lock is the one the host file names (the queue's push takes the same file)",
      s["rc"] == 0 and "another release holds the deploy lock; waiting" in glog(s) and s["deploys"] == [M2], (s["rc"], glog(s)[-500:]))
src = pathlib.Path(STACK, "release.sh").read_text()
check("the code comment says how the two paths exclude each other (the host file's deploy_lock is the lock this script takes; one thing started at a time; the marker per handed PR)",
      "HOW THE TWO PATHS EXCLUDE EACH OTHER" in src and "deploy_lock" in src.split("HOW THE TWO PATHS EXCLUDE EACH OTHER", 1)[1][:900] and "MQ_HANDED" in src.split("HOW THE TWO PATHS EXCLUDE EACH OTHER", 1)[1][:1800])

# WAIT_MAIN's default and the workflow step that publishes the map
src = pathlib.Path(STACK, "release.sh").read_text(); WF0 = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text()
check("WAIT_MAIN defaults to 5400 s (90 min: main's full run can be slow on a loaded host), with the reason given", 'WAIT_MAIN="${RELEASE_WAIT_MAIN:-5400}"' in src and "90 min" in src.split("WAIT_MAIN=")[1].split("\n")[0])
check("tests.yml publishes the map as an artifact, on main's push run and on a merge-queue entry's run (the entry's map is how main's proof job finds it) and on no other", "name: suitemap\n" in WF0 and "actions/upload-artifact@v4" in WF0 and
      WF0.split("name: publish the map\n")[1].split("- name:")[0].count("github.event_name == 'push'") == 1 and WF0.split("name: publish the map\n")[1].split("- name:")[0].count("github.event_name == 'merge_group'") == 1, "workflow")
STEP = WF0.split("name: publish the map\n")[1].split("- name:")[0]
check("tests.yml: the publishing step never turns main's run red (continue-on-error), a repeated upload of the same name replaces it (overwrite), and the map under the hidden folder .suitemap is uploaded (include-hidden-files)",
      "continue-on-error: true" in STEP and "overwrite: true" in STEP and "include-hidden-files: true" in STEP and "path: .suitemap/map.json" in STEP, STEP)



# -- review of PR 52: a group of the salamander queue and the release queue's two start paths
MK = lambda lead: f"2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #{lead}\n"
# mode on, the queue ejected the lead (its started mark and queue entry went) while the group release is still running: the members' markers say it is alive, nothing else starts
s = q("on-q-lead-ejected", "40", mqhost=ON, units="23", files={**QF(["25", "35"]), "releases/mq-on/pr-25": MK(23), "releases/mq-on/pr-35": MK(23)})
check("release queue, mode on, the group's lead was ejected (no started mark, not in the queue file) but its unit stackshot-release-23 still runs and the members' markers name it: nothing starts, no second group",
      s["started"] == [] and not started_args(s) and "the group release led by PR #23 is running" in s["out"], (s["started"], started_args(s), s["out"]))
s = q("on-q-lead-dead", "40", mqhost=ON, units="", files={**QF(["25", "35"]), "releases/mq-on/pr-25": MK(23), "releases/mq-on/pr-35": MK(23)})
check("…and with the lead's unit gone the markers do not hold the queue back: the waiting PRs start (as before)", s["started"] != [] and "is running" not in s["out"], (s["started"], s["out"]))
# the host file stops saying on mid-group: the plain path must not start lone releases of the PRs the salamander queue holds
s = q("off-q-marked", "40", mqhost="off", units="23", files={**QF(["23", "25", "35"], started=["23"]), "releases/mq-on/pr-25": MK(23), "releases/mq-on/pr-35": MK(23)})
check("release queue, host file switched to off mid-group: the PRs the salamander queue holds (markers) are NOT started alone; the new PR 40 starts; the log says why",
      s["started"] == ["40"] and "PR #25 is held by the salamander merge queue" in s["out"] and "PR #35 is held by the salamander merge queue" in s["out"] and not any(a.endswith(("--run 25", "--run 35")) for a in started_args(s)), (s["started"], started_args(s), s["out"]))


finish()
