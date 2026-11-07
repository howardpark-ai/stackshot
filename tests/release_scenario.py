"""Scenario test for release.sh --run: the merge step when `gh pr merge` errors although the merge went through (main is
already at the merge commit: the release carries on to deploy instead of stopping at "merge").
No network, no real gh, git or deploy: release.sh is copied into a temp dir beside stub config.py, client.py and deploy.sh,
and gh, git and sleep are stubs on a fake PATH.

Covers: a clean merge deploys and reports with no recheck; a merge call that errors while the PR reads MERGED (after a
retry) carries on to deploy and report green, the report naming the error and the short merge commit, and deletes the head
branch when it is still there; a deletion that fails, or a branch already gone, never fails the release; a cross-repository
PR's branch is left alone; a PR still OPEN after every recheck fails "merge" with the original error, never deploys, and the
rechecks span about 50 s (six reads, five sleeps of 10 s). The green report goes with --release green and the PR's URL (the
server logs it and rules it), the red one without; a --recycle release whose recycle could not be asked for
(recycle-due refused and sala refusing too: a stub, never the host's sala) goes without it as well.

The head branch (a stacked PR closed when its base merged): the merge no longer deletes it. The open PRs based on it are listed
(gh pr list --base) and retargeted to main (gh pr edit --base main) first, one log line each, and only then is the branch deleted (the
order of the gh calls is asserted); no stacked PR changes nothing but the extra list call; a retarget or a list that fails keeps the branch,
says why in the log, and neither fails nor stops the release.

The deploy lock: merge and deploy run under an exclusive flock (the deploy stub sees it held, fd 9 closed in it,
and it is free again at the end); a lock held elsewhere is waited for and then the release goes on, or, past the timeout, fails
"deploy lock" before anything is merged; the lock is released as soon as the deploy returns (no report or recycle child inherits it);
the wait for checks is outside the lock (a held lock does not stop a release still waiting on its checks); two releases sharing one
lock file never run their deploys at the same time. Every merge is pinned to the PR head the release read (--match-head-commit),
and gh pr merge gets no fd 9.

Main's tests before the deploy: the run on main that covers the merge is waited for, polled every 20 s; its suites failing
stops the release merged and not deployed; a selection miss alone deploys and reports to the keeper; a run cancelled (replaced while
queued, or after its job started) is skipped and a later run on a commit that contains the merge covers it (section 14); no run in time fails; the
deploy lock is let go for the wait (another release deploys meanwhile) and taken again for the deploy, where a lock held past
the timeout fails "deploy lock", merged and not deployed, fd 9 closed before the report; a run of an older commit never counts for
the tip; the deploy is pinned to the commit main's run passed on (DEPLOY_TO), so with two releases on one lock, B merging and
deploying while A waits, each deploys its own verified commit. deploy.sh's pin, on a real throwaway checkout: DEPLOY_TO fast-forwards
to that commit and no further, one the checkout already contains is nothing to do, an unknown one or one off origin/main is
refused, and a run by hand still goes to origin/main's tip. A fetch that fails, as one racing another release's fetch in the same
checkout does, is tried again: main_green waits it out at its 20 s poll (git's error in the log) and fails only when the whole wait
is spent; deploy.sh tries five times.

Release on PR pass: a PR whose head contains main's tip (the up-to-date test: git merge-base --is-ancestor,
after fetching main and the PR head) and for which a last good commit is recorded deploys the merge commit at once, under the lock, with
the --recycle step and the green report right after; main's run for it is then waited for with the lock free. A pass is a log line and
the last-good record (seeded on first use from the deployed HEAD when its run passed, atomic, never moved back); what else the run found
goes to the keeper as a second message. A failing run rolls back to the last good commit under the lock again (deploy.sh
DEPLOY_ROLLBACK=1 DEPLOY_TO=<it>), and the red report "FAILED at main's tests: rolled back to <sha>" names the merges the run covers when
there are several, a commit another release deployed on top, and whether a recycle was flagged; no rollback (said in the report) when the
live checkout no longer contains the failing commit or a newer commit whose run passed contains it; a rollback deploy that fails, or a lock
that cannot be had, is reported with the command to run by hand; a run that cannot be read in time rolls nothing back. Not up to date, no
record to roll back to, a PR head that cannot be fetched, or main having moved between the check and the merge: the old path, the reason
in the log. The merge-call-error path (504) works on both. deploy.sh's rollback, on the real throwaway checkout: only with DEPLOY_ROLLBACK=1 and
a DEPLOY_TO older than HEAD; a deploy without it still never moves backward.

What the fast path may carry along (a) the live HEAD is main's tip, so a rolled-back commit still on main, or an old-path
release merged and waiting on its run, is never swept in (behind it only by commits docs-merge.sh accepts, read from that script, counts as at
the tip); (b) no failed run on main after the last good commit, read page after page until the last good commit's run (empty, crashed or not
reaching it: the old path); a pending one is no reason to wait (two PRs back to back both go fast). The last-good record is read, compared and written under a lock file; one it cannot read is never
overwritten (told, old path); a failed write is told. A rollback takes out every other merge between the last good commit and the live checkout: each PR gets its own message and a
marker, so that its own run says "passed, but not live" (and, checked with git, does not become the last good commit); a run cancelled is skipped, and one that is the only run is unknown after the cap, not rolled back
(section 14); the report says a rollback does not undo data or state and names the unit files left installed. deploy.sh's
rollback is refused unless the deploy lock is held, no tracked file is changed and no untracked file stands where the target tracks a path, at a commit on origin/main, only for the value 1,
and to a commit whose deploy.sh has the second step; it resets, then the target's own deploy.sh does the rest. A deploy that replaces
release.sh under the running script is read from nothing it appends (every case arm ends in an explicit exit).
Third review: the docs-only diff is read unquoted and must be summarised as files=N refused=0 for every header (a non-ASCII file, a checker that does not
know diff-check); the rollback's lists are full shas; a passed merge is checked live and recorded under the deploy lock; a run cancelled after its job
started is unknown for (b); the clash check reads NUL-separated names and refuses when git fails; a fast deploy leaves a pending-verify record that the next
release to start (a killed watch) reads: pass recorded, fail rolled back and reported, unknown reported, pending kept.
mergeable (a PR can read UNKNOWN right after another merge): UNKNOWN is read again every 10 s for up to 3 min (logged once), then MERGEABLE goes
on; UNKNOWN throughout fails "mergeable" naming UNKNOWN and the 3 min; CONFLICTING fails at once. The usage and --help carry the four rules for running a release.
Fourth review: the record is written before deploy.sh; none (no run, GitHub unreadable) is kept until the cap (3 h); a recovery rollback that never ran keeps its
record; no command that can leave a child behind holds a lock descriptor; records oldest first; startup_failure counts as failed.

A branch behind main (section 13g, Oliver: main's full run never blocks a release): release.sh brings it up to date (gh pr update-branch, a merge, never a
rebase) under the update lock (one release at a time from the update to the merge; a second waits, and fails "update lock" past the timeout), waits for the PR's own tests on the
new head (the suites check must be reported; capped like the first wait, a progress line every 5 min), and deploys at the merge on the fast path; main moving meanwhile is another
round (3 at most, then the old path with the reason in the log); a conflict is FAILED at update-branch, failing tests FAILED at pr tests, neither falls back; --status shows the
newest log line of a release parked on the tests. The update lock's default wait is 3 x (50 + 3 min) + 15 min; a failed check (any) fails the wait at once while a
pass needs suites completed and successful in the check-runs of the new head's own commit (a pass read from the old head is pending); after the lock the PR is read again (a head pushed
meanwhile has its tests waited for, an up-to-date branch is not updated); a re-check that cannot fetch is told as such; fd 5 is closed in gh, git and client.py, and the lock is held
at the update and the merge and free at the deploy.

A conflict that is only the generated tool-text snapshot (section 13i: several releases failed on it in one day): where update-branch errors, or the first look says
CONFLICTING, release.sh asks tools/snapshot_regen.py (a stub here; its own decisions are tested in snapshot_regen_scenario.py) to merge main into the PR head, take main's snapshot,
regenerate it and push the merge; on "pushed" the release goes back to the PR's tests on the new head, on anything else it fails exactly as before, the helper's reason added to the log.
At most RELEASE_REGEN_MAX (2) per release, never for a cross-repository PR or when the fetch fails, run under the update lock with fd 5 closed in it, and no GitHub call of its own.


    tests/run-suite release        → exit 0 / 1  (the later sections are release_queue_scenario.py: tests/run-suite release_queue)"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
from _release_harness import *
check("release.sh parses", subprocess.run(["bash", "-n", os.path.join(STACK, "release.sh")]).returncode == 0)

# ---- 1. a clean merge: deploy and the green report, no recheck, no branch call
s = scenario("clean", merge="ok")
check("clean: exits 0 and deploys", s["rc"] == 0 and s["deployed"], s["out"])
check("clean: the green report, without a word about an error", "merged and deployed" in s["msg"] and "errored" not in s["msg"] and "main at 0106c0d" in s["msg"], s["msg"])
check("clean: no recheck, no sleep, the branch looked up once (already gone: no delete)", "state,mergeCommit" not in s["gh"] and not s["sleeps"] and len(refchecks(s)) == 1 and not deletes(s), (s["gh"], s["sleeps"]))
check("clean: the green report goes with --release green and the PR's URL (the server logs it, rules it, digests it)",
      s["msg"].startswith("message | projects/example | [release] PR #23 merged and deployed") and s["msg"].rstrip("\n").endswith(GREEN_ARGS), s["msg"])
RELEASED_ARGS = "released | --pr | https://github.com/example-owner/stackshot/pull/23 | --sha | "
check("clean (the old path): main's tests passed before the deploy, so once it is live the server is asked to settle the PR's items, once, after the green report, naming the merge",
      len(s["released"]) == 1 and s["released"][0].startswith(RELEASED_ARGS) and all(c in "0123456789abcdef" for c in s["released"][0][len(RELEASED_ARGS):]) and len(s["released"][0]) > len(RELEASED_ARGS) + 6
      and "items of PR #23: closed a1" in s["log"] and s["log"].index("done: ") < s["log"].index("items of PR #23"), (s["released"], s["log"]))
s = scenario("clean-released-fails", merge="ok", released="fail")
check("the items call fails: a log line, the release still exits 0 with its green report", s["rc"] == 0 and "the items of PR #23 were not settled: closed a1" in s["log"]
      and s["msg"].rstrip("\n").endswith(GREEN_ARGS), (s["rc"], s["log"]))

# ---- 2. the merge call errors, the PR reads MERGED on the second read: carry on, report the error, delete the leftover branch
s = scenario("recovered", merge="fail", after="merged", merged_from="2", branch="present")
check("recovered: exits 0 and deploys", s["rc"] == 0 and s["deployed"], s["out"])
check("recovered: the green report names the error's last line and the short merge commit",
      "merged and deployed" in s["msg"] and "the merge call errored (HTTP 504: We couldn't respond to your request in time.) but the PR was merged at 0106c0d" in s["msg"]
      and "FAILED" not in s["msg"], s["msg"])
check("recovered: the log says the call errored and the PR is merged", "the merge call errored" in s["log"] and "merged at 0106c0d; carrying on" in s["log"], s["log"])
check("recovered: two reads, one 10 s sleep between them", s["gh"].count("state,mergeCommit") == 2 and s["sleeps"] == ["10"], (s["gh"], s["sleeps"]))
check("recovered: the head branch still there is deleted", deletes(s) == ["api -X DELETE repos/example-owner/stackshot/git/refs/heads/agent/topic"]
      and "deleted the head branch agent/topic" in s["log"], s["gh"])

# ---- 3. MERGED, but the branch deletion fails: still green
s = scenario("delfail", merge="fail", after="merged", branch="present", delete="fail")
check("deletion fails: still exits 0, deploys and reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"], (s["out"], s["msg"]))
check("deletion fails: the log says the branch is still there", "the head branch agent/topic is still there" in s["log"], s["log"])
check("deletion fails: MERGED on the first read, no sleep", not s["sleeps"], s["sleeps"])

# ---- 4. MERGED and the branch already gone: no delete call
s = scenario("gone", merge="fail", after="merged", branch="absent")
check("branch gone: green, the ref looked up once, no delete", s["rc"] == 0 and "merged and deployed" in s["msg"] and len(refchecks(s)) == 1 and not deletes(s), (s["gh"], s["msg"]))

# ---- 5. a cross-repository PR: its branch lives in the fork, never touched here
s = scenario("cross", merge="fail", after="merged", branch="present", cross="1")
check("cross-repository: green, no branch call at all", s["rc"] == 0 and "merged and deployed" in s["msg"] and not refchecks(s) and not deletes(s), (s["gh"], s["msg"]))

# ---- 5b. stacked PRs (GitHub closes a stacked PR when its base merges and the base branch is deleted): they are retargeted to main BEFORE the branch is deleted
def gl(s): return s["gh"].splitlines()
def at_gh(s, line): return gl(s).index(line) if line in gl(s) else -1
R = "example-owner/stackshot"; LIST = f"pr list --repo {R} --base agent/topic --state open --limit 100 --json number"; DEL = f"api -X DELETE repos/{R}/git/refs/heads/agent/topic"
MERGE_LINE = f"pr merge 23 --repo {R} --merge --match-head-commit {HEADSHA}"
E_a, E_b = f"pr edit 32 --repo {R} --base main", f"pr edit 28 --repo {R} --base main"
s = scenario("stacked", merge="ok", stacked="32,28", branch="present")
check("stacked: exits 0, deploys, reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"], (s["out"], s["msg"]))
check("stacked: the merge does not delete the branch (no --delete-branch)", MERGE_LINE in gl(s) and not any("--delete-branch" in l for l in gl(s)), s["gh"])
check("stacked: both PRs are retargeted to main, after the merge and BEFORE the branch delete (order asserted)",
      0 <= at_gh(s, MERGE_LINE) < at_gh(s, LIST) < at_gh(s, E_a) < at_gh(s, E_b) < at_gh(s, DEL), s["gh"])
check("stacked: one log line per PR, then the deletion", "PR #32 was based on agent/topic: retargeted to main" in s["log"] and "PR #28 was based on agent/topic: retargeted to main" in s["log"]
      and "deleted the head branch agent/topic" in s["log"] and s["log"].index("PR #28 was based") < s["log"].index("deleted the head branch"), s["log"])
check("stacked: exactly one delete", deletes(s) == [DEL], s["gh"])
s = scenario("stacked-recovered", merge="fail", after="merged", stacked="32", branch="present")
check("stacked, the merge call errored but merged: the same order (retarget, then delete)",
      s["rc"] == 0 and s["deployed"] and 0 <= at_gh(s, LIST) < at_gh(s, E_a) < at_gh(s, DEL), (s["out"], s["gh"]))

s = scenario("unstacked", merge="ok", branch="present")
check("no stacked PR: green, the list is asked once, no retarget, the branch is deleted as before",
      s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and gl(s).count(LIST) == 1 and not any(l.startswith("pr edit") for l in gl(s))
      and deletes(s) == [DEL] and at_gh(s, LIST) < at_gh(s, DEL) and "retarget" not in s["log"], (s["gh"], s["log"]))
s = scenario("unstacked-gone", merge="ok", branch="absent")
check("no stacked PR and the branch already gone: no retarget, no delete", s["rc"] == 0 and not any(l.startswith("pr edit") for l in gl(s)) and not deletes(s), s["gh"])
s = scenario("stacked-cross", merge="ok", stacked="32", branch="present", cross="1")
check("cross-repository: no list, no retarget, no delete", s["rc"] == 0 and LIST not in gl(s) and not any(l.startswith("pr edit") for l in gl(s)) and not deletes(s), s["gh"])

s = scenario("retarget-fails", merge="ok", stacked="32,28", branch="present", retarget_fail="32")
check("a failed retarget: the release still deploys and reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "FAILED" not in s["msg"], (s["out"], s["msg"]))
check("a failed retarget: the other PR is still retargeted, the branch is NOT deleted (no lookup, no delete call)",
      E_b in gl(s) and not deletes(s) and not refchecks(s), s["gh"])
check("a failed retarget: the log says which PR failed and why, and that the branch is kept",
      "PR #32 was based on agent/topic: retargeting it to main failed (GraphQL: Could not resolve to a PullRequest" in s["log"] and "PR #28 was based on agent/topic: retargeted to main" in s["log"]
      and "the head branch agent/topic is kept: deleting it would close the PRs #32 still based on it" in s["log"] and "deleted the head branch" not in s["log"], s["log"])
s = scenario("list-fails", merge="ok", list="fail", branch="present")
check("a list that cannot be read: green, no retarget, the branch is kept and the log says why",
      s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and not deletes(s) and not any(l.startswith("pr edit") for l in gl(s))
      and "the head branch agent/topic is kept: the open PRs based on it could not be listed (HTTP 502: bad gateway)" in s["log"], (s["gh"], s["log"]))

# ---- 6. the merge call errors and the PR stays OPEN: fail at merge with the original error, never deploy
s = scenario("open", merge="fail", after="open", branch="present")
check("still open: exits 1, never deploys", s["rc"] == 1 and not s["deployed"], s["out"])
check("still open: FAILED at merge with the original error's last line",
      "PR #23 FAILED at merge: HTTP 504: We couldn't respond to your request in time." in s["msg"] and "merged and deployed" not in s["msg"], s["msg"])
check("still open: six reads over five 10 s sleeps (about 50 s)", s["gh"].count("state,mergeCommit") == 6 and s["sleeps"] == ["10"] * 5, (s["gh"], s["sleeps"]))
check("still open: the branch is left alone", not refchecks(s) and not deletes(s), s["gh"])
check("still open: the red report goes as before, with no --release (delivered to the keeper)",
      s["msg"].rstrip("\n").endswith("| --sender | release") and "--release" not in s["msg"], s["msg"])

# ---- 7. --recycle: a green release whose recycle is marked stays green; one whose recycle could not be asked for is delivered
s = scenario("recycle", args=("--recycle",), merge="ok")
msg = [l for l in s["msg"].splitlines() if l.startswith("message |")]
check("recycle marked: green, with --release green", s["rc"] == 0 and len(msg) == 1 and msg[0].endswith(GREEN_ARGS) and "recycle-due | --pr" in s["msg"], s["msg"])
s = scenario("recycle-not-marked", args=("--recycle",), merge="ok", recycle_due="fail", idle="sala recycle --when-idle")
msg = [l for l in s["msg"].splitlines() if l.startswith("message |")]
check("recycle NOT marked: the report says so and goes without --release, so the keeper gets it as before",
      s["rc"] == 0 and len(msg) == 1 and "recycle NOT marked" in msg[0] and "--release" not in msg[0] and msg[0].endswith("| --sender | release")
      and "recycle --when-idle" in s["dir"].joinpath("sala.log").read_text(), s["msg"])
s = scenario("recycle-no-fleet-tool", args=("--recycle",), merge="ok", recycle_due="fail")
msg = [l for l in s["msg"].splitlines() if l.startswith("message |")]
check("recycle NOT marked with no [fleet] recycle_when_idle: the same report, and no fleet command is run",
      s["rc"] == 0 and len(msg) == 1 and "recycle NOT marked" in msg[0] and not s["dir"].joinpath("sala.log").exists(), s["msg"])


# ---- 8. every merge is pinned to the head commit that was read, and the lock does not reach gh
for nm, args, kw in (("pin-normal", (), {}), ("pin-recycle", ("--recycle",), {}), ("pin-other-head", (), {"head": "0123456789abcdef0123456789abcdef01234567"})):
    s = scenario(nm, args=args, merge="ok", **kw)
    want = kw.get("head", HEADSHA)
    check(f"{nm}: gh pr merge is pinned to the head it read (--match-head-commit {want[:7]})",
          s["rc"] == 0 and f"pr merge 23 --repo example-owner/stackshot --merge --match-head-commit {want}" in s["gh"].splitlines(), s["gh"])
    check(f"{nm}: gh pr merge gets no fd 9", s["merge_fd9"] == "closed", s["merge_fd9"])
s = scenario("pin-moved", merge="fail", after="open")
check("the head moved after the read (the pinned merge is refused): never deploys, FAILED at merge", s["rc"] == 1 and not s["deployed"] and "FAILED at merge" in s["msg"], s["msg"])

s = scenario("lock-closed-after-deploy", args=("--recycle",), merge="ok", recycle_due="fail", idle="sala recycle --when-idle")
check("lock: no child after the deploy (recycle, idle recycle, report) inherits fd 9", s["rc"] == 0 and s["client_fd9"] and set(s["client_fd9"]) == {"closed"}, s["client_fd9"])
s = scenario("lock-closed-deploy-fails", merge="ok", deploy_fail="1")
check("lock: a failed deploy releases the lock before the failure report", s["rc"] == 1 and "FAILED at deploy" in s["msg"] and s["client_fd9"] == ["closed"], (s["msg"], s["client_fd9"]))

# ---- 8b. mergeable UNKNOWN (GitHub recomputes after main moves): read again every 10 s for up to 3 min
s = scenario("mergeable-unknown-then-ok", merge="ok", mergeable="UNKNOWN,UNKNOWN,MERGEABLE")
check("mergeable UNKNOWN then MERGEABLE: goes on, merges and deploys, reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "FAILED" not in s["msg"], (s["out"], s["msg"]))
check("mergeable UNKNOWN then MERGEABLE: one line says it waits, three reads, two 10 s sleeps",
      s["log"].count("mergeable UNKNOWN") == 1 and "every 10 s for up to 3 min" in s["log"] and s["gh"].count("state,mergeable") == 3 and s["sleeps"][:2] == ["10", "10"], (s["log"], s["sleeps"]))
s = scenario("mergeable-unknown-throughout", merge="ok", mergeable="UNKNOWN")
check("mergeable UNKNOWN throughout: exits 1, FAILED at mergeable naming UNKNOWN and the time, nothing merged, nothing deployed",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub still says UNKNOWN after 3 min" in s["msg"] and not merges(s) and not s["deployed"], (s["msg"], s["out"]))
check("mergeable UNKNOWN throughout: 19 reads over 18 sleeps of 10 s (3 min), the wait logged once",
      s["gh"].count("state,mergeable") == 19 and s["sleeps"] == ["10"] * 18 and s["log"].count("mergeable UNKNOWN") == 1, (s["gh"].count("state,mergeable"), s["sleeps"]))
s = scenario("mergeable-conflicting", merge="ok", mergeable="CONFLICTING")
check("mergeable CONFLICTING: fails at once at mergeable naming CONFLICTING, no wait, nothing merged",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["gh"].count("state,mergeable") == 1 and not s["sleeps"]
      and "mergeable UNKNOWN" not in s["log"] and not merges(s) and not s["deployed"], (s["msg"], s["sleeps"]))
s = scenario("mergeable-conflicting-after-unknown", merge="ok", mergeable="UNKNOWN,CONFLICTING")
check("mergeable UNKNOWN then CONFLICTING: fails at mergeable as soon as it reads CONFLICTING",
      s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["gh"].count("state,mergeable") == 2 and s["sleeps"] == ["10"], (s["msg"], s["sleeps"]))

# ---- 9. the front door: --quick is gone (docs-merge.sh covers it), and an unknown option is refused before any gh call
for nm, args in (("front-quick", ("--quick",)), ("front-unknown-option", ("--fast",))):
    s = scenario(nm, args=args, front=True, merge="ok")
    check(f"{nm}: refused with exit 2 and the usage line, nothing called, nothing deployed, no message",
          s["rc"] == 2 and "usage: release.sh <pr> [--recycle | --no-recycle]" in s["out"] and not s["gh"] and not s["deployed"] and not s["msg"], (s["rc"], s["out"], s["gh"]))
RULES = ("Run one plain `release.sh N` per command", "pr-N.log", "` done: ` or ` FAILED `", "run_in_background", "Never chain waiters", "refuses a loop of release.sh",
         "behind main is brought up to date first (gh pr update-branch, a merge)", "main's full run never blocks a release")   # the new path
check("front door: the usage line is followed by the rules for running it (one plain command, wait on the log, no chained waiters, auto mode and loops) and the path of a branch behind main",
      all(t in s["out"] for t in RULES) and "set -uo pipefail" not in s["out"], s["out"])
home = subprocess.run(["bash", os.path.join(STACK, "release.sh"), "--help"], capture_output=True, text=True)
check("--help: exits 2, starts at the header, carries the same four rules and the steps, and stops before the code",
      home.returncode == 2 and home.stdout.startswith("# release.sh") and all(t in home.stdout for t in RULES) and "4. ./deploy.sh pinned" in home.stdout
      and "2a. BEHIND MAIN?" in home.stdout and "update.lock" in home.stdout and 'fails the release "update-branch"' in home.stdout
      and "set -uo pipefail" not in home.stdout and "read_view" not in home.stdout, (home.returncode, home.stdout[:300]))
# ---- 10. the deploy lock
s = scenario("lock-held-by-release", merge="ok")
check("lock: the deploy runs with the lock held by the release, fd 9 closed in it", s["rc"] == 0 and s["lock_during"] == "held" and s["fd9"] == "closed", (s["lock_during"], s["fd9"], s["out"]))
check("lock: taken after the checks pass, before the merge", 0 <= s["log"].index("checks pass") < s["log"].index("deploy lock taken") < s["log"].index("merged"), s["log"])
lockfile = s["dir"] / "releases/deploy.lock"
check("lock: the file is in the release state dir", lockfile.exists())
if lockfile.exists():
    lk = open(lockfile, "a")
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); freed = True
    except OSError: freed = False
    lk.close(); check("lock: free again after the release", freed)
s = scenario("lock-timeout", merge="ok", hold=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("lock held elsewhere past the timeout: exits 1, FAILED at deploy lock, nothing merged, nothing deployed",
      s["rc"] == 1 and "PR #23 FAILED at deploy lock: another deploy held the lock" in s["msg"] and not merges(s) and not s["deployed"], (s["msg"], s["out"]))
check("lock held elsewhere: the log says it waits", "another release holds the deploy lock; waiting" in s["log"], s["log"])
check("lock timeout: the red report is delivered (no --release)", "--release" not in s["msg"], s["msg"])
s = scenario("lock-released-in-time", merge="ok", hold="until-waiting", extra={"DEPLOY_LOCK_WAIT": "30"})
check("lock held for a moment: the release waits, then merges and deploys", s["rc"] == 0 and s["deployed"] and "waiting" in s["log"] and "merged and deployed" in s["msg"], (s["out"], s["log"]))
# 150 polls of stub gh and sleep: under strace on a busy box that took past 120 s (a measured run on box-c)
s = scenario("lock-outside-checks", merge="ok", hold=True, checks="pending", extra={"DEPLOY_LOCK_WAIT": "1", "RELEASE_WAIT_CHECKS": "300"})
check("the wait for checks is outside the lock: a held lock does not matter to a release still waiting on its checks (it fails at checks, after the 5 min of fake sleeps on a short RELEASE_WAIT_CHECKS)",
      s["rc"] == 1 and "FAILED at checks: still pending after 5 min" in s["msg"] and len(s["sleeps"]) == 15 and "deploy lock" not in s["log"], (s["msg"], len(s["sleeps"])))

# two releases, one lock file: their deploys never overlap (each stub deploy takes one real second and records start and end)
trace = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-trace-")); dirs.append(trace)
shared = {"DEPLOY_LOCK_FILE": str(trace / "deploy.lock"), "RT_TRACE": str(trace / "trace"), "DEPLOY_LOCK_WAIT": "60"}
res = []
th = [threading.Thread(target=lambda i=i: res.append(scenario(f"serial{i}", merge="ok", extra=shared))) for i in range(2)]
[t.start() for t in th]; [t.join() for t in th]
tr = [l.split()[0] for l in (trace / "trace").read_text().splitlines()] if (trace / "trace").exists() else []
check("two releases on one lock: both deploy and report green", len(res) == 2 and all(r["rc"] == 0 and r["deployed"] for r in res), [r["out"] for r in res])
check("two releases on one lock: the deploys never overlap (start, end, start, end)", tr == ["start", "end", "start", "end"], tr)

# ---- 11. main's tests: a PR runs only the suites its change reaches, so the deploy waits for main's run of the tip
s = scenario("main-green", merge="ok")
check("main green: the run on main for the tip is looked up and read before the deploy", s["rc"] == 0 and s["deployed"]
      and "run list --repo example-owner/stackshot --workflow tests.yml --branch main --event push" in s["gh"] and "run view 7" in s["gh"]
      and "main's tests pass at 0106c0d (run 7)" in s["log"] and s["msg"].rstrip("\n").endswith(GREEN_ARGS), (s["gh"], s["log"], s["msg"]))
check("main green: the deploy is pinned to the commit main's tests passed on (DEPLOY_TO)", s["deploy_to"] == "0106c0de0106c0de0106c0de0106c0de0106c0de", s["deploy_to"])
s = scenario("main-pending", merge="ok", main="pending,pending,pass")
check("main still running: polled every 20 s until it finishes, then deployed", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"], (s["sleeps"], s["out"]))
# the wait looks every 60 s by default (the suite sets 20), and the reads are shared between releases for RELEASE_GH_TTL s
s = scenario("main-pending-default-poll", merge="ok", main="pending,pending,pass", extra={"RELEASE_POLL_MAIN": ""})
check("main still running: the default look is every 60 s", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["60", "60"], (s["sleeps"], s["out"]))
s = scenario("main-pending-cached", merge="ok", main="pending,pass", extra={"RELEASE_GH_TTL": "300", "RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("main's runs are read once inside RELEASE_GH_TTL: three polls, one run list and one run view, the answer reused",
      s["sleeps"] == ["20"] * 3 and s["gh"].count("run list --repo") == 1 and s["gh"].count("run view 7") == 1, (s["sleeps"], s["gh"]))
s1 = scenario("main-shared-1", merge="ok", main="pass", extra={"RELEASE_GH_TTL": "300"})
n1 = s1["gh"].count("run view 7")
s2 = scenario("main-shared-2", merge="ok", main="fail", reuse=s1, extra={"RELEASE_GH_TTL": "300"})
check("a second release on the same box reads what the first read: no new run list or run view inside the TTL, so it agrees with it",
      n1 == 1 and s2["gh"].count("run view 7") == 1 and s2["gh"].count("run list --repo") == 1 and (s1["dir"] / "releases/gh-cache").is_dir(), (s2["gh"], n1))
s = scenario("main-empty-list", merge="ok", runs="", extra={"RELEASE_GH_TTL": "300", "RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("an empty answer is not kept: three sleeps, four looks, four run lists, and the cache holds only the PR checks answer", s["sleeps"] == ["20"] * 3 and s["gh"].count("run list --repo") == 4 and len(list((s["dir"] / "releases/gh-cache").glob("*"))) == 1, (s["sleeps"], s["gh"]))
s = scenario("main-cache-private", merge="ok", main="pass", extra={"RELEASE_GH_TTL": "300"})
check("the cache folder is private to the user (mode 700)", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777) == "0o700", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777))
s = scenario("main-pending-default-ttl-larger", merge="ok", main="pending,pass", extra={"RELEASE_GH_TTL": "900", "RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("a TTL larger than the old cancelled-run one (600 s) is not cut short: still one run view in three polls", s["gh"].count("run view 7") == 1, s["gh"])
s = scenario("main-fail", merge="ok", main="fail", live=NOTLIVE)   # live: the checkout is at an older commit; the stub would otherwise say the merge is in it
check("main's suites fail: exits 1, never deploys, FAILED at main's tests naming the step, merged and not deployed, red",
      s["rc"] == 1 and not s["deployed"] and "FAILED at main's tests: the run on main for 0106c0d failed (run every suite, measured=failure;" in s["msg"]
      and "merged, not deployed" in s["msg"] and "--release" not in s["msg"], (s["msg"], s["out"]))
check("main's suites fail: the lock is free after, and the red report got no fd 9", lock_free(s), s["client_fd9"])
check("main's suites fail on the old path: no item is settled", s["released"] == [] and "items of PR" not in s["log"], (s["released"], s["log"]))
# a run that is completed and green whose suites step has no conclusion yet is pending, not a failure (release.sh read the run in that gap and failed the PR)
s = scenario("main-late", merge="ok", main="late,late,pass")
check("completed and green but the suites step has no conclusion yet: pending, read again at the next two polls, then the step shows success and the release deploys",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"] and "main's tests pass at 0106c0d (run 7)" in s["log"] and "FAILED" not in s["msg"]
      and s["log"].count("has not filled in its step results yet") == 1, (s["rc"], s["sleeps"], s["log"], s["msg"]))
check("…the wait made no GitHub call beyond a pending run's: one run list and one run view per poll (three of each, GH_TTL 0)", s["gh"].count("run view 7") == 3 and s["gh"].count("run list --repo") == 3, s["gh"])
s = scenario("main-late-absent", merge="ok", main="lateabsent,lateabsent,pass")
check("completed and green with no step in the job at all: pending as well, then passes", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"], (s["sleeps"], s["log"]))
s = scenario("main-late-never", merge="ok", main="late", live=NOTLIVE, extra={"RELEASE_WAIT_STEPS": "60"})
check("completed and green but the step results never come: gives up after RELEASE_WAIT_STEPS (60 s here, three 20 s polls), fails with a message that says the step results never arrived, merged and not deployed",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 3
      and "FAILED at main's tests: the run on main for 0106c0d failed (finished successfully, but its step results never arrived in 1 min: no conclusion for \"run every suite, measured\"" in s["msg"]
      and "merged, not deployed" in s["msg"], (s["rc"], s["sleeps"], s["msg"]))
s = scenario("main-late-rerun", merge="ok", main="late,late,pending,pending,pending,pending,late,late,pass", extra={"RELEASE_WAIT_STEPS": "60"})
check("the gap is seen, the run goes back to running for longer than RELEASE_WAIT_STEPS (a re-run keeps its run id), then completes with the gap again: a fresh wait starts, it does not fail at once on the old start; the wait line is logged twice",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 8 and s["log"].count("has not filled in its step results yet") == 2 and "never arrived" not in s["out"] + s["log"], (s["rc"], s["sleeps"], s["log"]))
s = scenario("main-late-default-cap", merge="ok", main="late", live=NOTLIVE, extra={"RELEASE_WAIT_STEPS": ""})
check("the default cap is 10 min: 30 polls of 20 s, then the step results never arrived in 10 min", s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 30 and "never arrived in 10 min" in s["msg"], (len(s["sleeps"]), s["msg"]))
s = scenario("main-late-real-fail", merge="ok", main="fail", live=NOTLIVE, extra={"RELEASE_WAIT_STEPS": "60"})
check("a completed suites step that failed for real fails at once: no sleep, the step named, never read as a gap",
      s["rc"] == 1 and not s["deployed"] and not s["sleeps"] and "run every suite, measured=failure" in s["msg"] and "never arrived" not in s["msg"], (s["sleeps"], s["msg"]))
s = scenario("main-jobfail-nosteps", merge="ok", main="jobfail", live=NOTLIVE, extra={"RELEASE_WAIT_STEPS": "60"})
check("a run whose job failed with no suites step is still a failure at once, as before (only a green run is given time)",
      s["rc"] == 1 and not s["deployed"] and not s["sleeps"] and "no suites step, conclusion failure" in s["msg"], (s["sleeps"], s["msg"]))
s = scenario("main-miss", merge="ok", main="miss")
check("a selection miss alone (every suite passed, the audit failed): deploys, says so, and the report goes to the keeper, not green",
      s["rc"] == 0 and s["deployed"] and "every suite passed on main, but the selection audit found a miss" in s["msg"] and "--release" not in s["msg"], s["msg"])
s = scenario("main-savefail", merge="ok", main="savefail")
check("every suite passed on main but a later step failed (the map's cache): deploys, names the step, report to the keeper",
      s["rc"] == 0 and s["deployed"] and "every suite passed on main, but also failed: save the map=failure" in s["msg"] and "--release" not in s["msg"], s["msg"])
TWO_RUNS = json.dumps([{"databaseId": 7, "headSha": "0106c0de0106c0de0106c0de0106c0de0106c0de"}, {"databaseId": 8, "headSha": "0107c0de0107c0de0107c0de0107c0de0107c0de"}])
s = scenario("main-replaced", merge="ok", runs=TWO_RUNS, main7="replaced")
check("the merge's own run replaced while queued (cancelled, no job started): the newer run on a commit that contains it covers it, and the deploy goes to that commit",
      s["rc"] == 0 and s["deployed"] and "run view 8" in s["gh"] and "main's tests pass at 0107c0d (run 8, on 0107c0d, which contains 0106c0d)" in s["log"]
      and s["deploy_to"] == "0107c0de0107c0de0107c0de0107c0de0107c0de" and not s["sleeps"], (s["gh"], s["log"], s["deploy_to"]))
s = scenario("main-cancelled", merge="ok", runs=TWO_RUNS, main7="cancelled")
check("the merge's run cancelled after its job started (the job limit): not a failure either; the later run that contains it decides, no wait",
      s["rc"] == 0 and s["deployed"] and "main's tests pass at 0107c0d (run 8, on 0107c0d, which contains 0106c0d)" in s["log"] and not s["sleeps"], (s["msg"], s["log"]))
check("a covering run passed: the lock is free after, and the report got no fd 9", lock_free(s), s["client_fd9"])
s = scenario("main-flaky", merge="ok", ann=json.dumps([{"annotation_level": "warning", "message": "Node.js 20 is deprecated."},
                                                         {"annotation_level": "warning", "message": "search failed only when measured; it passes plainly. The map runs it on every PR until a clean measurement."}]))
check("a suite that failed only when measured on main and passed plainly: deploys, names it in the report, which goes to the keeper",
      s["rc"] == 0 and s["deployed"] and "every suite passed on main, but search failed only when measured, then passed plainly" in s["msg"]
      and "Node.js" not in s["msg"] and "--release" not in s["msg"] and "api repos/example-owner/stackshot/check-runs/907/annotations" in s["gh"], (s["msg"], s["gh"]))
s = scenario("main-lock-gap", merge="ok", main="pending,pass")
check("the deploy lock is free while main's run is waited for, and held again for the deploy",
      s["rc"] == 0 and s["deployed"] and (s["dir"] / "lock_at_view").read_text().split() == ["free", "free"] and s["lock_during"] == "held"
      and s["log"].count("deploy lock taken") == 2, ((s["dir"] / "lock_at_view").read_text() if (s["dir"] / "lock_at_view").exists() else None, s["lock_during"], s["log"]))
s = scenario("main-moved", merge="ok", runs=TWO_RUNS, tips="0106c0de0106c0de0106c0de0106c0de0106c0de,0107c0de0107c0de0107c0de0107c0de0107c0de", main8="pending")
check("main moves while the tip's run is going: the release is about its own merge, so its own passing run deploys it at once, pinned to the merge, never waiting for the new tip's run",
      s["rc"] == 0 and s["deployed"] and "main's tests pass at 0106c0d (run 7)" in s["log"] and not s["sleeps"] and s["deploy_to"] == "0106c0de0106c0de0106c0de0106c0de0106c0de", (s["log"], s["deploy_to"], s["sleeps"]))
s = scenario("main-older-run", merge="ok", tips="0107c0de0107c0de0107c0de0107c0de0107c0de", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("only a run of an older commit (it does not contain the merge): never read as green for it; no run in time, merged and not deployed, both limits named",
      s["rc"] == 1 and not s["deployed"] and "run view 7" not in s["gh"]
      and "no finished run on main covers 0107c0d after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 1 min): merged, not deployed" in s["msg"]
      and "merge-base --is-ancestor 0107c0de0107c0de0107c0de0107c0de0107c0de 0106c0de0106c0de0106c0de0106c0de0106c0de" in (s["dir"] / "git.log").read_text(), (s["msg"], s["gh"]))
s = scenario("main-none", merge="ok", runs="[]", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("no run on main shows up in time: fails at main's tests, merged and not deployed", s["rc"] == 1 and not s["deployed"]
      and "no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min)" in s["msg"] and "merged, not deployed" in s["msg"] and s["sleeps"] == ["20"] * 3, (s["msg"], s["sleeps"]))
check("no run on main in time: the lock is free after, and the red report got no fd 9", lock_free(s), s["client_fd9"])
s = scenario("main-fetch-race", merge="ok", fetch_fails="2")
check("main's fetch fails twice (racing another release's fetch in the checkout): waited out, git's error in the log, then deployed",
      s["rc"] == 0 and s["deployed"] and s["log"].count("cannot fetch main from origin (error: fetching ref refs/remotes/origin/main failed: incorrect old value provided); trying again in 20 s") == 2
      and s["sleeps"] == ["20", "20"] and s["deploy_to"] == "0106c0de0106c0de0106c0de0106c0de0106c0de", (s["log"], s["sleeps"]))
s = scenario("main-fetch-down", merge="ok", fetch_fails="999", extra={"RELEASE_WAIT_MAIN": "60"})
check("main cannot be fetched for the whole wait: fails at main's tests with git's error, merged and not deployed, the lock free",
      s["rc"] == 1 and not s["deployed"] and "FAILED at main's tests: cannot fetch main from origin for 1 min (error: fetching ref refs/remotes/origin/main failed: incorrect old value provided): merged, not deployed" in s["msg"]
      and s["sleeps"] == ["20"] * 3 and lock_free(s), (s["msg"], s["sleeps"]))
s = scenario("main-relock-timeout", merge="ok", grab=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("main green, then the lock held elsewhere past the timeout: exits 1, FAILED at deploy lock, merged and not deployed, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and merges(s) and "FAILED at deploy lock: another deploy held the lock" in s["msg"]
      and "merged, not deployed (./deploy.sh by hand once it is free)" in s["msg"] and s["log"].count("deploy lock taken") == 1, (s["msg"], s["log"]))
check("the second lock timing out: fd 9 is closed before the red report, and the lock is free after", lock_free(s), s["client_fd9"])

# two releases on one lock file: B merges and deploys while A waits on main's run; A then deploys exactly the commit its own run passed on
pair = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-pair-")); dirs.append(pair)
lk = {"DEPLOY_LOCK_FILE": str(pair / "deploy.lock"), "RT_TRACE": str(pair / "trace"), "DEPLOY_LOCK_WAIT": "60"}
res = {}
ta = threading.Thread(target=lambda: res.update(a=scenario("pair-a", merge="ok", extra={**lk, "RT_VIEW_AFTER": str(pair / "b-deployed"),
                                                                                    "RT_VIEWING_MARK": str(pair / "a-waits")})))
tb = threading.Thread(target=lambda: res.update(b=scenario("pair-b", merge="ok", tips="0107c0de0107c0de0107c0de0107c0de0107c0de", runs=json.dumps([{"databaseId": 8, "headSha": "0107c0de0107c0de0107c0de0107c0de0107c0de"}]),
                                                           extra={**lk, "RT_DEPLOYED_MARK": str(pair / "b-deployed")})))
ta.start()
for _ in range(600):   # B starts only once A has merged, let the lock go and waits on main's run
    if (pair / "a-waits").exists(): break
    threading.Event().wait(0.05)
tb.start(); ta.join(); tb.join()
a, b = res.get("a"), res.get("b")
tr = [l.split() for l in (pair / "trace").read_text().splitlines()] if (pair / "trace").exists() else []
check("two releases: B merges and deploys while A waits on main's run (the lock free for it), then A deploys; both green",
      a and b and a["rc"] == 0 and b["rc"] == 0 and [x[0] for x in tr] == ["start", "end", "start", "end"] and tr[0][1] == str(b["dir"]) and tr[2][1] == str(a["dir"])
      and (a["dir"] / "lock_at_view").read_text().split() == ["free"], (tr, a and a["out"], b and b["out"]))
check("two releases: each deploy is pinned to the commit its own main run passed on, never the newer tip the other merged",
      a and b and a["deploy_to"] == "0106c0de0106c0de0106c0de0106c0de0106c0de" and b["deploy_to"] == "0107c0de0107c0de0107c0de0107c0de0107c0de", (a and a["deploy_to"], b and b["deploy_to"]))

# ---- 12. deploy.sh's pin: the real deploy.sh in a throwaway checkout of a throwaway origin, four commits on main;
# config.py, units/scope.sh, install.sh and curl are stubs, and the commits change only text files, so nothing restarts
dp = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-deploy-")); dirs.append(dp)
g("init", "-q", "--bare", "-b", "main", str(dp / "origin.git")); g("clone", "-q", str(dp / "origin.git"), str(dp / "box"))
bx = dp / "box"; cs = []
(bx / "deploy.sh").write_text("#!/bin/sh\n"); g("add", "-A", cwd=bx); g("commit", "-qm", "c0", cwd=bx); c0 = g("rev-parse", "HEAD", cwd=bx)   # a deploy.sh that predates the rollback's second step
for i in range(1, 5):
    (bx / f"notes{i}.txt").write_text(f"{i}\n")
    if i == 1:   # the real deploy.sh and its stubs are part of the tree from c1 on
        shutil.copy(os.path.join(STACK, "deploy.sh"), bx / "deploy.sh"); (bx / "units").mkdir()
        (bx / "config.py").write_text('import sys\nif sys.argv[1:] == ["get", "server.port"]: print("1")\n')
        (bx / "units/scope.sh").write_text('server_ctl() { :; }\nxdg_repair() { :; }\n')
        (bx / "install.sh").write_text("#!/bin/sh\n"); (bx / "install.sh").chmod(0o755)
    g("add", "-A", cwd=bx); g("commit", "-qm", f"c{i}", cwd=bx); cs.append(g("rev-parse", "HEAD", cwd=bx))
g("push", "-q", "origin", "HEAD:main", cwd=bx); g("reset", "-q", "--hard", cs[1], cwd=bx)   # deployed at c2; origin/main at c4
(dp / "bin").mkdir(); (dp / "bin/curl").write_text("#!/bin/sh\nexit 0\n"); (dp / "bin/curl").chmod(0o755)   # /healthz answers at once
(dp / "bin/git").write_text(f'''#!/bin/sh
if [ "$1" = fetch ] && [ -n "${{RT_FETCH_FAILS:-}}" ]; then   # the first RT_FETCH_FAILS fetches fail, as one racing another fetch in the checkout does
  n=$(( $(cat "{dp}/fetches" 2>/dev/null || echo 0) + 1 )); echo $n > "{dp}/fetches"
  [ $n -gt "$RT_FETCH_FAILS" ] || {{ echo "error: fetching ref refs/remotes/origin/main failed: incorrect old value provided" >&2; exit 1; }}
fi
if [ "$1" = ls-tree ] && [ -n "${{RT_LSTREE_FAILS:-}}" ]; then echo "fatal: injected failure" >&2; exit 128; fi
exec {shutil.which("git")} "$@"
'''); (dp / "bin/git").chmod(0o755)
def deploy(to=None, fetch_fails=None):
    e = {**genv, "PATH": f"{dp}/bin:" + os.environ.get("PATH", "")}; e.pop("DEPLOY_TO", None)
    if to: e["DEPLOY_TO"] = to
    if fetch_fails: e["RT_FETCH_FAILS"] = str(fetch_fails); (dp / "fetches").unlink(missing_ok=True)
    r = subprocess.run(["bash", str(bx / "deploy.sh")], cwd=bx, env=e, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr, g("rev-parse", "HEAD", cwd=bx)
rc, out, head = deploy(cs[2])
check("deploy.sh DEPLOY_TO=<c3>, origin/main at c4: fast-forwards to c3 exactly, not to the tip", rc == 0 and head == cs[2] and f"deploying {cs[1][:7]}..{cs[2][:7]}" in out, (rc, out))
rc, out, head = deploy(cs[1])
check("deploy.sh DEPLOY_TO=<c2> with the checkout at c3 (a later release deployed past it): exits 0, already contains it, HEAD unmoved",
      rc == 0 and head == cs[2] and f"already contains {cs[1][:7]} (DEPLOY_TO) (at {cs[2][:7]}" in out, (rc, out))
rc, out, head = deploy(cs[2])
check("deploy.sh DEPLOY_TO=<the checkout's own commit>: already at it, nothing to deploy", rc == 0 and head == cs[2] and "already at" in out, (rc, out))
rc, out, head = deploy("0123456789abcdef0123456789abcdef01234567")
check("deploy.sh DEPLOY_TO=<an unknown sha>: refused, exit 1, HEAD unmoved", rc == 1 and head == cs[2] and "deploy refused: DEPLOY_TO=0123456789abcdef0123456789abcdef01234567 is not a commit this checkout knows" in out, (rc, out))
side = subprocess.run(["git", "commit-tree", cs[2] + "^{tree}", "-p", cs[2], "-m", "side"], cwd=bx, env=genv, capture_output=True, text=True).stdout.strip()
rc, out, head = deploy(side)
check("deploy.sh DEPLOY_TO=<a commit not on origin/main>: refused, exit 1, HEAD unmoved", rc == 1 and head == cs[2] and "is not on origin/main" in out, (rc, out))
rc, out, head = deploy()
check("deploy.sh run by hand (no DEPLOY_TO): fast-forwards to origin/main's tip as before", rc == 0 and head == cs[3] and "healthz ok" in out, (rc, out))
g("clone", "-q", str(dp / "origin.git"), str(dp / "src"))
def land(n):   # one more commit on origin's main, from another clone
    (dp / f"src/notes{n}.txt").write_text(f"{n}\n"); g("add", "-A", cwd=dp / "src"); g("commit", "-qm", f"c{n}", cwd=dp / "src"); g("push", "-q", "origin", "HEAD:main", cwd=dp / "src")
    return g("rev-parse", "HEAD", cwd=dp / "src")
c5 = land(5)
rc, out, head = deploy(c5, fetch_fails=2)
check("deploy.sh: its fetch fails twice (racing a release's fetch outside the lock), then works: deploys", rc == 0 and head == c5 and (dp / "fetches").read_text().strip() == "3", (rc, out))
c6 = land(6)
rc, out, head = deploy(c6, fetch_fails=99)
check("deploy.sh: the fetch fails five times: refused as before (no raw git error), HEAD unmoved",
      rc == 1 and head == c5 and "deploy refused: cannot fetch main from origin (" in out and "incorrect old value" not in out and (dp / "fetches").read_text().strip() == "5", (rc, out))

# DEPLOY_ROLLBACK: the only way back. The checkout is at c5 here (c6 is on origin/main, not deployed). A rollback runs under the deploy lock
# (flock <file> deploy.sh, as by hand), on a clean checkout, from a commit on origin/main, to an older commit whose own deploy.sh knows the second step.
LOCKF = dp / "deploy.lock"
def rollback(to=None, locked=True, rb="1", extra=None):
    e = {**genv, "PATH": f"{dp}/bin:" + os.environ.get("PATH", ""), "DEPLOY_ROLLBACK": rb, "DEPLOY_LOCK_FILE": str(LOCKF), **(extra or {})}; e.pop("DEPLOY_TO", None)
    if to: e["DEPLOY_TO"] = to
    cmd = ["bash", str(bx / "deploy.sh")]
    r = subprocess.run((["flock", str(LOCKF)] if locked else []) + cmd, cwd=bx, env=e, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr, g("rev-parse", "HEAD", cwd=bx)
rc, out, head = rollback(cs[2], locked=False)
check("deploy.sh DEPLOY_ROLLBACK=1 without the deploy lock held: refused, HEAD unmoved, the by-hand command is in the answer",
      rc == 1 and head == c5 and "a rollback needs the deploy lock held; by hand: flock " in out and f"{LOCKF} env DEPLOY_ROLLBACK=1 DEPLOY_TO=<sha> ./deploy.sh" in out, (rc, out))
rc, out, head = rollback()
check("deploy.sh DEPLOY_ROLLBACK=1 with no DEPLOY_TO: refused, HEAD unmoved", rc == 1 and head == c5 and "DEPLOY_ROLLBACK needs DEPLOY_TO" in out, (rc, out))
rc, out, head = rollback(cs[2], rb="true")
check("deploy.sh DEPLOY_ROLLBACK=true (only the value 1 counts): a plain deploy, so DEPLOY_TO behind HEAD is nothing to deploy and HEAD does not move",
      rc == 0 and head == c5 and "already contains" in out and "rolling back" not in out, (rc, out))
rc, out, head = rollback(c6)
check("deploy.sh DEPLOY_ROLLBACK=1 to a commit that is not older than HEAD: refused, HEAD unmoved", rc == 1 and head == c5 and "is not older than HEAD" in out, (rc, out))
def land_rm(name):   # a commit on origin's main that deletes a tracked file, from the other clone
    g("rm", "-q", name, cwd=dp / "src"); g("commit", "-qm", "rm1", cwd=dp / "src"); g("pull", "-q", "--rebase", "origin", "main", cwd=dp / "src"); g("push", "-q", "origin", "HEAD:main", cwd=dp / "src")
    return g("rev-parse", "HEAD", cwd=dp / "src")
g("pull", "-q", "origin", "main", cwd=dp / "src")
c7 = land_rm("notes1.txt")
rc, out, head = deploy(c7)
check("deploy.sh: forward to a commit that deletes notes1.txt (c6 rides along)", rc == 0 and head == c7 and not (bx / "notes1.txt").exists(), (rc, out))
# the checkout is at c7 now; the rollback target cs[2] (c3) tracks notes1.txt, which c7 deleted
(bx / "notes1.txt").write_text("untracked, but the target tracks this path\n")
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 with an untracked file at a path the target commit tracks: refused (a reset would overwrite it), HEAD unmoved, the file untouched",
      rc == 1 and head == c7 and "an untracked file stands where the target commit tracks a path" in out and "notes1.txt" in out
      and (bx / "notes1.txt").read_text().startswith("untracked"), (rc, out))
rc, out, head = deploy(cs[2])
check("deploy.sh without DEPLOY_ROLLBACK: an untracked file is no matter (as before)", rc == 0 and head == c7 and "already contains" in out, (rc, out))
(bx / "notes1.txt").unlink()
(bx / "notes5.txt").write_text("tracked at HEAD, edited\n")
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 with a tracked file changed (unstaged): refused as before, HEAD unmoved", rc == 1 and head == c7 and "has local changes" in out, (rc, out))
g("add", "-A", cwd=bx)
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 with a tracked file changed (staged): refused as before, HEAD unmoved", rc == 1 and head == c7 and "has local changes" in out, (rc, out))
g("reset", "-q", "--hard", c7, cwd=bx)
(bx / "local.txt").write_text("a commit of the checkout's own\n"); g("add", "-A", cwd=bx); g("commit", "-qm", "local", cwd=bx)
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 when HEAD is not on origin/main (a local commit): refused, HEAD unmoved", rc == 1 and head != c7 and "a rollback starts from a commit on origin/main" in out, (rc, out))
g("reset", "-q", "--hard", c7, cwd=bx)
rc, out, head = rollback(c0)
check("deploy.sh DEPLOY_ROLLBACK=1 to a commit whose deploy.sh predates the second step: refused before anything moves, HEAD unmoved",
      rc == 1 and head == c7 and "predates the rollback's second step" in out, (rc, out))
(bx / ".claude").mkdir(); (bx / ".claude/settings.local.json").write_text("{}\n")   # what this box has: an untracked directory no commit knows
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 with an untracked file outside the target tree (.claude/): runs, goes back to the target, the file survives, what it takes out is listed",
      rc == 0 and head == cs[2] and f"rolling back {c7[:7]} to {cs[2][:7]}" in out and f"{cs[3][:7]} c4" in out and f"{c5[:7]} c5" in out and f"{c7[:7]} rm1" in out
      and (bx / ".claude/settings.local.json").exists(), (rc, out))
check("deploy.sh rollback: the checked-out (good) tree's own deploy.sh finishes the job (the second step runs from the reset tree), and health is checked",
      out.count("rolling back") == 2 and "healthz ok" in out, out)
rc, out, head = rollback(cs[2])
check("deploy.sh DEPLOY_ROLLBACK=1 to the commit it is at: nothing to deploy", rc == 0 and head == cs[2] and "already at" in out, (rc, out))
rc, out, head = deploy(cs[3])
check("deploy.sh without DEPLOY_ROLLBACK still only moves forward: DEPLOY_TO=<c4> from c3 fast-forwards", rc == 0 and head == cs[3] and f"deploying {cs[2][:7]}..{cs[3][:7]}" in out, (rc, out))
rc, out, head = deploy(cs[2])
check("deploy.sh without DEPLOY_ROLLBACK and DEPLOY_TO older than HEAD: still nothing to deploy, HEAD unmoved", rc == 0 and head == cs[3] and "already contains" in out, (rc, out))

# the clash check reads NUL-separated, unquoted names: a non-ASCII path is caught; a git that fails refuses
def land_files(add=(), rm=(), msg="x"):   # one commit on origin's main from the other clone: files added (names may be non-ASCII), files removed
    g("pull", "-q", "origin", "main", cwd=dp / "src")
    for f in add: (dp / "src" / f).write_text("x\n")
    for f in rm: g("rm", "-q", f, cwd=dp / "src")
    g("add", "-A", cwd=dp / "src"); g("commit", "-qm", msg, cwd=dp / "src"); g("push", "-q", "origin", "HEAD:main", cwd=dp / "src")
    return g("rev-parse", "HEAD", cwd=dp / "src")
c8 = land_files(add=["é", "ü.txt"], msg="add non-ASCII"); c9 = land_files(rm=["é", "ü.txt"], msg="remove them")
rc, out, head = deploy(c9)
check("deploy.sh: forward to a commit that removes two files with non-ASCII names", rc == 0 and head == c9 and not (bx / "é").exists(), (rc, out))
(bx / "é").mkdir(); (bx / "é/z").write_text("untracked\n")
rc, out, head = rollback(c8)
check("deploy.sh rollback: an untracked é/z where the target tracks a file é (non-ASCII, a folder over a file): refused, named, HEAD unmoved, the file untouched",
      rc == 1 and head == c9 and "an untracked file stands where the target commit tracks a path" in out and "é/z" in out and (bx / "é/z").exists(), (rc, out))
(bx / "é/z").unlink(); (bx / "é").rmdir(); (bx / "ü.txt").write_text("untracked\n")
rc, out, head = rollback(c8)
check("deploy.sh rollback: an untracked ü.txt (non-ASCII) at a path the target tracks: refused, named, HEAD unmoved",
      rc == 1 and head == c9 and "ü.txt" in out and (bx / "ü.txt").exists(), (rc, out))
rc, out, head = rollback(c8, extra={"RT_LSTREE_FAILS": "1"})
check("deploy.sh rollback: git ls-tree failing is a refusal, never 'no clash'; HEAD unmoved", rc == 1 and head == c9 and "cannot tell whether an untracked file stands where the target commit tracks a path" in out, (rc, out))
(bx / "ü.txt").unlink()

# ---- 13. release on PR pass: a PR whose checks passed on a head that contains main's tip deploys at the merge; main's full run
# follows, outside the lock, and a failure rolls back to the last good commit. The git stub's history is linear, oldest first: HIST.

s = fast("fast-pass", merge="ok")
check("up to date: deploys the merge commit at once, pinned to it, and main's run is read after the deploy, never before",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view"], (s["rc"], s["deploys"], s["order"], s["out"]))
check("up to date: the log says why, then that main's tests passed on the commit, after the done line",
      "up to date: the PR head abc1234 contains main's tip ba5e000" in s["log"] and "deploying 0106c0d at once" in s["log"]
      and 0 <= s["log"].index("done: ") < s["log"].index("main's tests passed on 0106c0d (run 7)"), s["log"])
check("up to date: one green report at the deploy, saying main's run follows",
      len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "deployed at the merge" in s["msgs"][0] and "main's full run follows" in s["msgs"][0], s["msgs"])
check("up to date: the deploy ran with the lock held, and the wait for main's run with the lock free", s["lock_during"] == "held" and lock_views(s) == ["free"] and lock_free(s), (s["lock_during"], lock_views(s)))
check("up to date: the branch is not updated and no sleep", "update-branch" not in s["gh"] and "pr update" not in s["gh"] and not s["sleeps"], (s["gh"], s["sleeps"]))
check("up to date: main's pass is written as the last good commit", s["lastgood"] == MERGE, s["lastgood"])
check("up to date: main's pass on the live merge asks the server to settle the PR's items, naming the merge, after the pass is logged",
      s["released"] == [RELEASED_ARGS + MERGE] and s["log"].index("main's tests passed on 0106c0d") < s["log"].index("items of PR #23: closed a1"), (s["released"], s["log"]))
s = fast("fast-pending", merge="ok", main="pending,pending,pass")
check("up to date: the lock is never held across the wait for main's run (three looks at the run, all free), polled every 20 s",
      s["rc"] == 0 and lock_views(s) == ["free"] * 3 and s["sleeps"] == ["20", "20"] and s["order"][0] == f"deploy:{MERGE}", (lock_views(s), s["sleeps"], s["order"]))

# main's run fails: rolled back to the last good commit, under the lock, reported red to the builder
s = fast("fast-fail", merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("up to date, main fails: deploys the merge, then rolls back to the last good commit (a rollback deploy), in that order",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"]
      and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view", f"deploy:{GOOD}", "client:message"], (s["rc"], s["deploys"], s["order"], s["out"]))
check("main fails: the rollback runs under the lock (taken again), and nothing is left holding it", s["locks"] == ["held", "held"] and lock_free(s) and s["log"].count("deploy lock taken") == 2, (s["locks"], s["log"]))
check("main fails: FAILED at main's tests: rolled back to the sha, red (no --release), after the green deploy report",
      len(s["msgs"]) == 2 and s["msgs"][0].endswith(GREEN_ARGS) and "FAILED at main's tests: rolled back to 600d000 · the run on main for 0106c0d failed (run every suite, measured=failure;" in s["msgs"][1]
      and "--release" not in s["msgs"][1] and s["msgs"][1].endswith("| --sender | release"), s["msgs"])
check("main fails: the report says main still holds the merge and that no recycle was flagged",
      "main still holds the failing merge, fix forward or revert it" in s["msgs"][1] and "no recycle was flagged" in s["msgs"][1], s["msgs"][1])
s = fast("fast-fail-notice", merge="ok", main="fail", heads=f"{BASE},{MERGE}", pickfiles="next_rules.py", notice="notify")
check("main fails after a notice went out: the rollback report says in one line that the notice had gone out and is not taken back",
      "notice: sent" in s["msgs"][0] and len(s["notice"]) == 1 and "no recycle was flagged; a notice about this release had already gone out, and a rollback does not take it back" in red(s)[0], (s["notice"], s["msgs"]))
s = fast("fast-fail-notice-unset", merge="ok", main="fail", heads=f"{BASE},{MERGE}", pickfiles="next_rules.py")
check("main fails when no notice was sent (no command set): the rollback report does not claim one", "no recycle was flagged" in red(s)[0] and "a notice about this release" not in red(s)[0], red(s))
s = fast("fast-fail-notice-failed", merge="ok", main="fail", heads=f"{BASE},{MERGE}", pickfiles="next_rules.py", notice="notify", notice_fail="1")
check("main fails when the notice command failed: the rollback report does not claim a notice went out", "a notice about this release" not in red(s)[0], red(s))
s = fast("fast-fail-mixed", merge="ok", main="fail", heads=f"{BASE},{MERGE}", pickfiles="client/hooks/session-start.sh,next_rules.py", notice="notify")
check("main fails after a recycle and a notice: the rollback report names both",
      "a recycle was already flagged for this PR's items before the failure" in red(s)[0] and "a notice about this release had already gone out" in red(s)[0], red(s))
check("main fails: the last good record is unchanged", s["lastgood"] == GOOD, s["lastgood"])
check("main fails: no item is settled (the server is never asked)", s["released"] == [] and "items of PR" not in s["log"], (s["released"], s["log"]))
s = fast("fast-fail-several", merge="ok", main8="fail", runs=json.dumps([{"databaseId": 8, "headSha": LATER}]), heads=f"{BASE},{LATER}",
         covered="9aaaaaa Merge pull request #26 from x/y;0106c0d Merge pull request #23 from agent/topic;5ec0000 Merge pull request #25 from z")
check("the failing run covers several merges since the last good commit: the report says so and names them",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "the failing run covers 3 merges since the last good commit 600d000" in red(s)[0]
      and "9aaaaaa Merge pull request #26" in red(s)[0] and "0106c0d Merge pull request #23" in red(s)[0] and "5ec0000 Merge pull request #25" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-ontop", merge="ok", main="fail", heads=f"{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other")
check("another release deployed a commit on top meanwhile (the live checkout still contains the failing one): rolled back, the report names what the rollback also removes",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "rolled back to 600d000" in red(s)[0]
      and "the rollback also takes out the other merges between 600d000 and the live checkout" in red(s)[0] and "5ec0000 Merge pull request #35" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-newer-good", merge="ok", main="fail", heads=f"{BASE},{NEWER}", newgood=NEWER)
check("a newer commit whose run on main passed is recorded and deployed meanwhile: never rolled back past it, said in the report, nothing deployed after the merge",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "FAILED at main's tests" in red(s)[0] and "NOT rolled back, a newer commit whose run on main passed, 0107c0d, contains 0106c0d: never rolled back past a newer good commit" in red(s)[0]
      and "rolled back to" not in red(s)[0] and s["lastgood"] == NEWER and lock_free(s), (s["deploys"], s["msgs"], s["lastgood"]))
s = fast("fast-fail-gone", merge="ok", main="fail", heads=f"{BASE},{GOOD}")
check("the live checkout no longer contains the failing commit (rolled back by hand, say): nothing to roll back, said in the report",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, the live checkout (600d000) no longer contains 0106c0d" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-rbfail", merge="ok", main="fail", heads=f"{BASE},{MERGE}", rollback_fail="1")
check("the rollback deploy itself fails: FAILED at rollback, naming the commit to go back to by hand; the lock is free",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at rollback: main's tests failed on 0106c0d" in red(s)[0]
      and "rollback to 600d000 failed: rollback: healthz did not answer" in red(s)[0] and f"flock {s['lockfile']} env DEPLOY_ROLLBACK=1 DEPLOY_TO={GOOD} ./deploy.sh" in red(s)[0] and lock_free(s), (s["deploys"], s["msgs"]))
s = fast("fast-fail-lock", merge="ok", main="fail", grab=True, grab_on="fail", heads=f"{BASE},{MERGE}", extra={"DEPLOY_LOCK_WAIT": "1"})
check("main fails but the lock is held elsewhere past the timeout: FAILED at deploy lock, nothing rolled back, the report says how to do it by hand",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "FAILED at deploy lock: another deploy held the lock" in red(s)[0] and "nothing was rolled back; by hand, in " in red(s)[0]
      and f"flock {s['lockfile']} env DEPLOY_ROLLBACK=1 DEPLOY_TO={GOOD} ./deploy.sh (deploy.sh refuses a rollback unless the lock is held)" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-recycle", args=("--recycle",), merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("--recycle: the recycle step and the green report come right after the fast deploy, before main's run; the rollback report says a recycle was flagged",
      s["order"] == [f"deploy:{MERGE}", "client:recycle-due", "client:message", "run-view", f"deploy:{GOOD}", "client:message"]
      and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS) and "a recycle was already flagged for this PR's items before the failure" in red(s)[0], (s["order"], s["msgs"]))

# what else main's run found goes to the keeper as a second message; a run that cannot be read does not roll back
s = fast("fast-miss", merge="ok", main="miss")
check("up to date, main passes with a selection miss: the deploy report is green, a second message to the keeper (no --release) carries the miss",
      s["rc"] == 0 and s["deploys"] == [MERGE] and len(s["msgs"]) == 2 and s["msgs"][0].endswith(GREEN_ARGS) and "--release" not in s["msgs"][1]
      and "every suite passed on main, but the selection audit found a miss" in s["msgs"][1], s["msgs"])
s = fast("fast-unknown", merge="ok", runs="[]", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("main's run never shows up in time: not a failure, so deployed and NOT rolled back; the red report says so and names both limits",
      s["rc"] == 1 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] * 3 and lock_free(s)
      and "FAILED at main's tests: no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 1 min): deployed at 0106c0d and NOT rolled back" in red(s)[0], (s["deploys"], s["msgs"], s["sleeps"]))
s = fast("fast-deploy-fail", merge="ok", deploy_fail="1")
check("the fast deploy fails: FAILED at deploy as before, main's run is not waited for, no rollback", s["rc"] == 1 and s["deploys"] == [MERGE] and "FAILED at deploy" in red(s)[0]
      and "run-view" not in s["order"] and lock_free(s), (s["deploys"], s["order"], s["msgs"]))

# the merge-call error path still works on the fast path
s = fast("fast-a", merge="fail", after="merged", merged_from="2", branch="present")
check("up to date, the merge call errors (504) and the PR reads MERGED on the second read: carries on, deploys the merge commit at once, reports the error, then main passes",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["sleeps"] == ["10"] and "the merge call errored (HTTP 504: We couldn't respond to your request in time.) but the PR was merged at 0106c0d" in s["msgs"][0]
      and "deployed at the merge" in s["msgs"][0] and "main's tests passed on 0106c0d" in s["log"] and deletes(s) == ["api -X DELETE repos/example-owner/stackshot/git/refs/heads/agent/topic"], (s["deploys"], s["sleeps"], s["msgs"]))
s = fast("fast-open", merge="fail", after="open")
check("up to date, the merge call errors and the PR stays open: FAILED at merge, nothing deployed, no main wait", s["rc"] == 1 and not s["deployed"] and "FAILED at merge" in red(s)[0] and "run-view" not in s["order"], (s["msgs"], s["order"]))

# not up to date, or anything the fast path cannot vouch for: the old path (main's run first), with the reason in the log
# (a branch that is behind main is no longer a reason for the old path: release.sh brings it up to date first, section 13g; the old path is its fallback after 3 rounds)
s = fast("fast-moved", merge="ok", p1="0ddba11000000000000000000000000000000000")
check("main moved between the check and the merge (the merge commit's first parent is not the tip that was checked): the old path, the reason in the log",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "not deployed at the merge: main's tip 0106c0d is not the merge of ba5e000 and abc1234 (something else landed on main meanwhile)" in s["log"], (s["order"], s["log"]))
s = fast("fast-prfetch", merge="ok", prfetch_fail="1")
check("the PR head cannot be fetched (three tries, 2 s apart, before the lock and again under it): the old path, the reason in the log, and the branch is not updated (it is not known to be behind)",
      s["rc"] == 0 and s["sleeps"] == ["2", "2", "2", "2"] and "update-branch" not in s["gh"]
      and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "cannot fetch main and the PR head from origin" in s["log"], (s["sleeps"], s["order"], s["log"]))
s = fast("fast-nobase", merge="ok", base="")
check("main's tip cannot be read: the old path", s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "cannot read main's tip" in s["log"], (s["order"], s["log"]))

# the last-good record: seeded on first use from the deployed HEAD when its main run passed; read for the rollback; written by a pass, never moved back
s = fast("fast-seed", merge="ok", lastgood="", main="pass,fail", heads=f"{BASE},{MERGE}")
check("no record yet: seeded from the live HEAD (main's tip) when its run on main passed, and that record is what a failing main run rolls back to",
      s["rc"] == 1 and "seeded with the deployed ba5e000, whose run 7 on main passed" in s["log"] and s["deploys"] == [MERGE, f"rollback {BASE}"] and s["lastgood"] == BASE
      and "rolled back to ba5e000" in red(s)[0], (s["log"], s["deploys"], s["lastgood"]))
s = fast("fast-noseed", merge="ok", lastgood="", main="fail,pass")
check("no record, and the live HEAD's run on main did not pass: nothing to roll back to, so the old path (main's run first); its pass writes the record",
      s["rc"] == 0 and s["order"] == ["run-view", "run-view", f"deploy:{MERGE}", "client:message"] and "there is nothing to roll back to" in s["log"] and s["lastgood"] == MERGE, (s["order"], s["log"], s["lastgood"]))

# ---- 13b. what the fast path may carry along (the coordinator's review): the live HEAD is main's tip (a), and no failed run since the last good commit (b);
# a run still pending is no reason to wait, so back-to-back releases stay fast
s = fast("fast-after-rollback", merge="ok", heads=GOOD)
check("(a) after a rollback main still holds the failing commit and the live HEAD is behind it: an up-to-date PR is not deployed at the merge (it would redeploy the failing commit): the old path, the reason in the log",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout (600d000) is not at main's tip ba5e000" in s["log"]
      and "main's full run follows" not in s["msgs"][0], (s["order"], s["log"]))
s = fast("fast-swept-x", merge="ok", heads=GOOD, runs=json.dumps([{"databaseId": 6, "headSha": BASE}, {"databaseId": 7, "headSha": MERGE}]), main6="pending")
check("(a) an old-path release X, merged and still waiting on its own run, is not swept in by another PR's deploy at the merge: the live HEAD is behind main's tip, so the old path, and only main's run for the PR's own tip is read",
      s["rc"] == 0 and s["deploys"] == [MERGE] and "(a) the live checkout" in s["log"] and "run view 6" not in s["gh"] and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"], (s["gh"], s["order"], s["log"]))
FAILED_SHA = "fa11ed0000000000000000000000000000000000"
s = fast("fast-failed-run", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "failure"}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) a commit between the last good one and main's tip has a FAILED run on main: the old path, the run named in the log",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and f"(b) a commit after the last good one (600d000) has a failed run on main (run 5 on {FAILED_SHA})" in s["log"], (s["order"], s["log"]))
s = fast("fast-failed-run-outside", merge="ok", range="", runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "failure"}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) a failed run on a commit outside last-good..main's tip does not matter: the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}", (s["order"], s["log"]))
s = fast("fast-runs-unreadable", merge="ok", runs="not json", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("(b) GitHub's list of runs cannot be read: nothing can be vouched for, the old path", "(b) the runs on main since the last good commit 600d000 cannot be read" in s["log"] and not s["deploys"], (s["log"], s["deploys"]))
s = fast("fast-pending-base", merge="ok", range=BASE, runs=json.dumps([{"databaseId": 6, "headSha": BASE, "conclusion": None}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) main's tip has a run that is still pending (no conclusion yet): not a failure, the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}", (s["order"], s["log"]))

# two up-to-date PRs back to back, the first's run still pending when the second arrives: both are deployed at the merge (A waits for its run until B has deployed)
pair2 = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-b2b-")); dirs.append(pair2)
lk2 = {"DEPLOY_LOCK_FILE": str(pair2 / "deploy.lock"), "RT_TRACE": str(pair2 / "trace"), "DEPLOY_LOCK_WAIT": "60"}
res2 = {}
ta = threading.Thread(target=lambda: res2.update(a=fast("b2b-a", merge="ok", extra={**lk2, "RT_VIEW_AFTER": str(pair2 / "b-deployed"), "RT_VIEWING_MARK": str(pair2 / "a-waits")})))
tb = threading.Thread(target=lambda: res2.update(b=fast("b2b-b", merge="ok", head=NEWPR, base=MERGE, heads=MERGE, history=",".join([GOOD, BASE, MERGE, NEWPR, NEWER]), tips=NEWER,
                                                        range=MERGE, runs=json.dumps([{"databaseId": 8, "headSha": NEWER}]), extra={**lk2, "RT_DEPLOYED_MARK": str(pair2 / "b-deployed")})))
ta.start()
for _ in range(600):   # B starts only once A has deployed and waits on its run
    if (pair2 / "a-waits").exists(): break
    threading.Event().wait(0.05)
tb.start(); ta.join(); tb.join()
a, b = res2.get("a"), res2.get("b")
check("two up-to-date PRs back to back, the first's run still pending: both deploy at the merge, A's before B's, A's run is read only after B has deployed; both green",
      a and b and a["rc"] == 0 and b["rc"] == 0 and a["deploys"] == [MERGE] and b["deploys"] == [NEWER] and a["order"] == [f"deploy:{MERGE}", "client:message", "run-view"]
      and b["order"][0] == f"deploy:{NEWER}" and "up to date: the PR head b0b0000 contains main's tip 0106c0d, which is what is live" in b["log"] and "main's full run follows" in b["msgs"][0],
      (a and (a["order"], a["out"]), b and (b["order"], b["log"], b["out"])))

# ---- 13c. the last-good record: read, compared and written under a lock; never overwritten when unreadable; a failed write is told
s = fast("fast-badrecord", merge="ok", lastgood="not a sha")
check("the record holds something that is not a sha: left alone, told to the keeper, and the release takes the old path",
      s["rc"] == 0 and s["lastgood"] == "not a sha" and s["order"][:2] == ["client:message", "run-view"] and f"deploy:{MERGE}" in s["order"]
      and any("the last-good record" in m and "'not a sha'" in m and "--release" not in m for m in s["msgs"]) and "the last-good record is unreadable" in s["log"], (s["lastgood"], s["order"], s["msgs"], s["log"]))
UNKNOWN = "0123abc000000000000000000000000000000000"
s = fast("fast-unknownrecord", merge="ok", lastgood=UNKNOWN, nohead=UNKNOWN)
check("the record names a commit this checkout does not know (it may be newer than anything here): never overwritten by main's pass, told, the old path",
      s["rc"] == 0 and s["lastgood"] == UNKNOWN and f"deploy:{MERGE}" in s["order"] and s["order"].index("run-view") < s["order"].index(f"deploy:{MERGE}")
      and sum("the last-good record" in m for m in s["msgs"]) >= 2, (s["lastgood"], s["order"], s["msgs"]))
s = scenario("record-lock", merge="ok")
check("the record is written under a lock file next to it (flock), and no temp file is left", s["rc"] == 0 and s["lastgood"] == MERGE and (s["dir"] / "releases/last-good.lock").exists()
      and sorted(p.name for p in (s["dir"] / "releases").iterdir() if p.name.startswith("last-good")) == ["last-good", "last-good.lock"], sorted(p.name for p in (s["dir"] / "releases").iterdir()))
s = scenario("record-writefail", merge="ok", pre_lockdir="1")
check("a record that cannot be written (its lock file is unusable here: a folder): the release carries on and the keeper is told", s["rc"] == 0 and s["deployed"]
      and any("could not write" in m and "is not recorded as the last good commit" in m and "--release" not in m for m in s["msgs"]), (s["rc"], s["msgs"]))

# ---- 13d. a rollback and the releases it takes out; a cancelled run; the words of the report
s = fast("fast-fail-ontop2", merge="ok", main="fail", heads=f"{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other;0107c0d Merge pull request #37 from agent/more")
check("a rollback takes out releases deployed on top: each one's PR gets its own red message, and a marker for its own run",
      s["rc"] == 1 and "PR #35 was rolled back with #23's failure" in "\n".join(s["msgs"]) and "PR #37 was rolled back with #23's failure" in "\n".join(s["msgs"])
      and "it is merged but not live; it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" in "\n".join(s["msgs"])
      and all("--release" not in m for m in s["msgs"][1:]) and len(s["msgs"]) == 4 and "FAILED at main's tests: rolled back to 600d000" in s["msgs"][-1]
      and (s["dir"] / "releases/pr-35.rolledback").exists() and (s["dir"] / "releases/pr-37.rolledback").exists()
      and "rolled back with #23's failure" in (s["dir"] / "releases/pr-35.log").read_text(), (s["msgs"], sorted(p.name for p in (s["dir"] / "releases").iterdir())))
check("…and the failing release's own report names them", "the rollback also takes out the other merges between 600d000 and the live checkout" in s["msgs"][-1] and "5ec0000 Merge pull request #35 from agent/other; 0107c0d Merge pull request #37" in s["msgs"][-1], s["msgs"][-1])
s = fast("fast-rolled-back-pass", merge="ok", marker="#26 (main's tests failed on abc1234)", live=BASE)
check("a release rolled back by another's failure while it waited: its own run passes, and it says 'passed, but not live' (not green); the last-good record does not move, the marker is gone",
      s["rc"] == 0 and any("main's tests passed on 0106c0d, but it is not live (rolled back with #26 (main's tests failed on abc1234)); it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" in m and "--release" not in m for m in s["msgs"])
      and "but it is not live: rolled back with #26" in s["log"] and s["lastgood"] == GOOD and not (s["dir"] / "releases/pr-23.rolledback").exists(), (s["msgs"], s["lastgood"], s["log"]))
s = fast("fast-rolled-back-fail", merge="ok", main="fail", marker="#26 (main's tests failed on abc1234)", heads=f"{BASE},{BASE}")
check("a release already rolled back by another's failure whose own run then fails: nothing more to roll back, and the report says it was rolled back with #26",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, the live checkout (ba5e000) no longer contains 0106c0d: it was rolled back or reset already (rolled back with #26 (main's tests failed on abc1234))" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-cancelled", merge="ok", main7="cancelled", heads=f"{BASE},{MERGE}", extra={"RELEASE_CAP_MAIN": "60"})
check("main's only run cancelled (after its job started, the job limit or by hand), after a deploy at the merge, no later run: waited for until the cap, then unknown: no rollback, a red report naming the cancelled run",
      s["rc"] == 1 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] * 3
      and "FAILED at main's tests: no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 90 min); the run 7 on 0106c0d was cancelled and no later run covers 0106c0d" in red(s)[0]
      and "deployed at 0106c0d and NOT rolled back" in red(s)[0] and "rolled back to" not in red(s)[0], (s["deploys"], s["msgs"], s["sleeps"]))
s = fast("fast-fail-words", merge="ok", main="fail", heads=f"{BASE},{MERGE}", newunits="units/stackshot-foo.timer.in,units/stackshot-foo.service.in,units/notes.md")
check("the red rollback report says a rollback does not undo data or state changes, and names the unit and timer files the rolled-back commits added as left installed",
      s["rc"] == 1 and "a rollback does not undo data or state changes the rolled-back commits made" in red(s)[0]
      and "left installed: stackshot-foo.timer, stackshot-foo.service (the rolled-back commits added them), disable by hand if needed" in red(s)[0], red(s))
s = fast("fast-fail-nounits", merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("no unit added: the report has no 'left installed' part", "left installed" not in red(s)[0] and s["rc"] == 1, red(s))
s = scenario("record-not-back", merge="ok", lastgood=NEWER, history=f"{MERGE},{NEWER}")
check("a pass on an older commit than the record never moves it back", s["rc"] == 0 and s["lastgood"] == NEWER, s["lastgood"])
s = scenario("record-written", merge="ok")
check("a pass on main writes the commit it passed on, one sha, atomically (no temp file left, only the lock file beside it)", s["rc"] == 0 and s["lastgood"] == "0106c0de0106c0de0106c0de0106c0de0106c0de"
      and sorted(p.name for p in (s["dir"] / "releases").iterdir() if p.name.startswith("last-good")) == ["last-good", "last-good.lock"], s["lastgood"])

# the removed releases come from the last good commit up to the live checkout, not from the failing merge up: releases deployed BEFORE it (their runs still waiting) go too
s = fast("fast-removed-below", merge="ok", main="fail", heads=f"{BASE},{LATER}",
         removed=f"9aaaaaa Merge pull request #26 from x/y;{MERGE} Merge pull request #23 from agent/topic;5ec0000 Merge pull request #35 from agent/other")
allm = "\n".join(s["msgs"])
check("a rollback also takes out a release deployed BEFORE the failing merge (its run still waiting): its PR gets the red message and a marker; the failing PR's own message is its report, not a second one",
      s["rc"] == 1 and "PR #26 was rolled back with #23's failure" in allm and "PR #35 was rolled back with #23's failure" in allm and "PR #23 was rolled back" not in allm
      and (s["dir"] / "releases/pr-26.rolledback").exists() and (s["dir"] / "releases/pr-35.rolledback").exists() and not (s["dir"] / "releases/pr-23.rolledback").exists()
      and "9aaaaaa Merge pull request #26" in s["msgs"][-1] and "0106c0d Merge pull request #23" not in s["msgs"][-1].split("the rollback also takes out")[-1], (s["msgs"], sorted(p.name for p in (s["dir"] / "releases").iterdir())))
s = fast("fast-chain-a", merge="ok", marker="#26 (main's tests failed on abc1234)", live=BASE)
check("(chain) B's run failed first and rolled A out: A's later pass is 'passed, but not live', never green, and does not become the last good commit",
      s["rc"] == 0 and any("but it is not live (rolled back with #26" in m and "--release" not in m for m in s["msgs"]) and s["lastgood"] == GOOD, (s["msgs"], s["lastgood"]))
s = fast("fast-chain-nomarker", merge="ok", live=BASE)
check("(chain) no marker, but the merge is no longer in the live checkout: the same report, from git alone; the last good commit does not move",
      s["rc"] == 0 and any("but it is not live (no longer in the live checkout)" in m and "--release" not in m for m in s["msgs"]) and s["lastgood"] == GOOD and "but it is not live: no longer in the live checkout" in s["log"], (s["msgs"], s["lastgood"], s["log"]))
s = fast("fast-chain-live", merge="ok", marker="#26 (stale)")
check("(chain) the merge is in the live checkout, a stale marker notwithstanding: the pass counts, green as ever, the marker is removed",
      s["rc"] == 0 and s["lastgood"] == MERGE and not (s["dir"] / "releases/pr-23.rolledback").exists() and not any("not live" in m for m in s["msgs"]), (s["msgs"], s["lastgood"]))

# (a) behind main's tip only by what docs-merge.sh merges without CI (docs, comments, runner settings): the fast path, the allow-list read from docs-merge.sh itself
for fm in ("fake", "real"):
    if fm == "real" and not os.path.exists(REAL_DM): continue
    s = fast(f"fast-docs-{fm}", merge="ok", heads=f"{GOOD},{BASE}", docs=BASE, diff=MD, fm=fm)
    check(f"(a, {fm} docs-merge.sh) the live checkout is behind main's tip only by a docs merge: the fast path, said in the log",
          s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "only by merges docs-merge.sh accepts" in s["log"] and "(a) the live checkout" not in s["log"], (s["order"], s["log"]))
    s = fast(f"fast-code-{fm}", merge="ok", heads=f"{GOOD},{BASE}", docs=BASE, diff=CODE, fm=fm)
    check(f"(a, {fm} docs-merge.sh) the commit in between changes code: the old path, the reason in the log",
          s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout (600d000) is not at main's tip ba5e000" in s["log"], (s["order"], s["log"]))
s = fast("fast-docs-nofm", merge="ok", heads=f"{GOOD},{BASE}", docs=BASE, diff=MD)
check("(a) docs-merge.sh cannot be read: fails closed, the old path", s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout" in s["log"], (s["order"], s["log"]))
s = fast("fast-docs-nocommits", merge="ok", heads=f"{GOOD},{BASE}", docs="", diff=MD, fm="fake")
check("(a) the live checkout is not an ancestor-with-commits of main's tip (nothing to check): the old path", s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"], (s["order"], s["log"]))

# (b) pages of runs until the last good commit's run; empty or crashed output is unreadable
s = fast("fast-runs-page2", merge="ok", runs=json.dumps([{"databaseId": 7, "headSha": MERGE}]), noreach=True, runs_2=json.dumps([GOOD_RUN]))
check("(b) the run list reaches the last good commit on its second page: read, the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "page=2" in s["gh"], (s["order"], s["log"]))
s = fast("fast-runs-noreach", merge="ok", runs=json.dumps([{"databaseId": 7, "headSha": MERGE}]), noreach=True)
check("(b) the runs never reach the last good commit: the old path, the reason in the log", s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "do not reach it" in s["log"], (s["order"], s["log"]))
s = fast("fast-runs-empty", merge="ok", runs="", noreach=True, extra={"RELEASE_CAP_MAIN": "60"})
check("(b) an empty answer: unreadable, the old path (nothing deployed at the merge)", not s["deploys"] and "cannot be read, or do not reach it" in s["log"], (s["order"], s["log"]))
s = fast("fast-runs-crash", merge="ok", extra={"RT_GH_API_FAIL": "1"}, noreach=True)
check("(b) the call for the runs fails: unreadable, the old path", s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "cannot be read, or do not reach it" in s["log"], (s["order"], s["log"]))

# a deploy replaces release.sh under the running script: nothing it appends is ever read (every arm ends in an explicit exit)
for nm, kw in (("fast", dict(merge="ok")), ("old", dict(merge="ok", base=""))):
    s = fast(f"exit-{nm}", clobber="1", **kw)
    check(f"({nm} path) release.sh replaced by the deploy: the running script reads nothing from the new bytes and exits cleanly", s["rc"] == 0 and not (s["dir"] / "stale-read").exists() and s["deployed"], (s["rc"], s["out"]))

# ---- 13e. the third review
QUOTED = MD + '\ndiff --git "a/\\353\\271\\204.py" "b/\\353\\271\\204.py"\nnew file mode 100644\n--- /dev/null\n+++ "b/\\353\\271\\204.py"\n@@ -0,0 +1 @@\n+x = 1'
for fm in ("fake", "real"):
    if fm == "real" and not os.path.exists(REAL_DM): continue
    s = fast(f"fast-docs-quoted-{fm}", merge="ok", heads=f"{GOOD},{BASE}", docs=BASE, diff=QUOTED, fm=fm)
    check(f"(a, {fm} docs-merge.sh) a docs file plus a code file with a quoted (non-ASCII) header: the checker's file count is short of the diff's, so the old path",
          s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout (600d000) is not at main's tip" in s["log"], (s["order"], s["log"]))
check("(a) the diff is read unquoted, with fixed prefixes, whatever the config says", "-c core.quotePath=false diff --no-color --no-ext-diff --no-renames --src-prefix=a/ --dst-prefix=b/" in s["git"], s["git"])
s = fast("fast-docs-nosub", merge="ok", heads=f"{GOOD},{BASE}", docs=BASE, diff=MD, fm="nosub")
check("(a) a checker that does not know diff-check exits 0 and says nothing: not trusted, the old path (its summary line must say files=N refused=0)",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout" in s["log"], (s["order"], s["log"]))

# the same function against a real repository and the real git: a non-ASCII code file is a file the checker sees (unquoted), a docs-only commit passes
hd = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-docsonly-")); dirs.append(hd)
repo = hd / "r"; g("init", "-q", "-b", "main", str(repo)); shas = []
for n, files in enumerate((["README.md"], ["README.md", "例.py"], ["README.md"])):
    for f in files: (repo / f).write_text(f"{n}\n")
    g("add", "-A", cwd=repo); g("commit", "-qm", f"c{n}", cwd=repo); shas.append(g("rev-parse", "HEAD", cwd=repo))
(hd / "fm.sh").write_text(FAKE_FM); (hd / "fm-nosub.sh").write_text(FAKE_FM_NOSUB)
(hd / "h.sh").write_text('set -u\nREPO=x\neval "$(sed -n \'/^fm_pysrc() {/,/^fast_gate() {/p\' "$1" | sed \'$d\')"\ncd "$2"\ndocs_only_between "$3" "$4"\n')
def dob(fmscript, a, b):
    return subprocess.run(["bash", str(hd / "h.sh"), os.path.join(STACK, "release.sh"), str(repo), a, b], env={**genv, "DOCS_MERGE_SCRIPT": fmscript}, capture_output=True, text=True, timeout=60).returncode
check("docs_only_between on a real repository: a commit adding a non-ASCII-named code file is not docs-only", dob(str(hd / "fm.sh"), shas[0], shas[1]) == 1)
check("docs_only_between on a real repository: a commit that changes only README.md is docs-only", dob(str(hd / "fm.sh"), shas[1], shas[2]) == 0)
check("docs_only_between on a real repository: a checker that does not know diff-check passes nothing", dob(str(hd / "fm-nosub.sh"), shas[1], shas[2]) == 1)
if os.path.exists(REAL_DM):
    check("docs_only_between on a real repository, the real docs-merge.sh: the non-ASCII code file is refused, README.md alone passes",
          dob(REAL_DM, shas[0], shas[1]) == 1 and dob(REAL_DM, shas[1], shas[2]) == 0)

# the rollback's lists are full shas (%H), never an abbreviation that lengthens with the repository
s = fast("fast-removed-full", merge="ok", main="fail", heads=f"{BASE},{LATER}", removed=f"{MERGE} Merge pull request #23 from agent/topic;5ec0000 Merge pull request #35 from agent/other")
check("the rollback reads the merges between last-good and the live checkout as full shas (--format=%H) and names a PR other than the failing one by its short sha",
      "log --first-parent --reverse --format=%H %s" in s["git"] and "--format=%h" not in s["git"] and "PR #35 was rolled back" in "\n".join(s["msgs"]) and "PR #23 was rolled back" not in "\n".join(s["msgs"]), (s["git"], s["msgs"]))

# a passed merge is checked live and recorded under the deploy lock; the lock not had in time leaves it unrecorded, told
s = fast("fast-pass-lock", merge="ok")
check("the check that a passed merge is live, and its record, happen with the deploy lock held", s["rc"] == 0 and s["lock_at_live"] == ["held"] and s["lastgood"] == MERGE and lock_free(s), (s["lock_at_live"], s["lastgood"]))
s = fast("fast-pass-locktimeout", merge="ok", grab=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("the deploy lock not free in time at main's pass: not recorded as the last good commit, told to the keeper, the release still ends well",
      s["rc"] == 0 and s["lastgood"] == GOOD and any("deploy lock was not free for 1 s" in m and "not recorded as the last good commit" in m and "--release" not in m for m in s["msgs"]), (s["rc"], s["lastgood"], s["msgs"], s["log"]))

# failed_runs: a run cancelled after its job started is unknown, as run_state reads it; one cancelled while queued was replaced
s = fast("fast-cancelled-run", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "cancelled"}, {"databaseId": 7, "headSha": MERGE}]), main5="cancelled")
check("(b) a run in the range cancelled after its job started is unknown, not clean: the old path, said in the log",
      s["rc"] == 0 and "deploying 0106c0d at once" not in s["log"] and f"(b) a commit after the last good one (600d000) has a run on main cancelled after its job started (5 {FAILED_SHA}" in s["log"], (s["order"], s["log"]))
s = fast("fast-replaced-run", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "cancelled"}, {"databaseId": 7, "headSha": MERGE}]), main5="replaced")
check("(b) a run in the range cancelled while queued (no step ran) was replaced by a newer run: not a reason, the fast path", s["rc"] == 0 and "deploying 0106c0d at once" in s["log"] and "not up to date" not in s["log"], (s["order"], s["log"]))

# a fast deploy leaves a pending-verify record, held by the live release; it is gone when the watch concludes
s = fast("pv-live", merge="ok")
check("a fast deploy writes a pending-verify record, its lock held by the running release while it waits on main's run, and clears it when the run passes",
      s["rc"] == 0 and s["pending_at_view"] == ["pr-23:locked"] and s["pending_files"] == [], (s["pending_at_view"], s["pending_files"]))
s = fast("pv-live-old", merge="ok", base="")
check("the old path writes none", s["rc"] == 0 and s["pending_at_view"] == [] and s["pending_files"] == [], (s["pending_at_view"], s["pending_files"]))
s = fast("pv-live-fail", merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("a failing run: the record is cleared once the rollback has been acted on", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["pending_files"] == [], (s["pending_files"], s["deploys"]))

# a stale record (its release process is gone) is looked at by the next release to start
s = fast("pv-stale-pass", merge="ok", runs=RUNS67, pending=PEND, main6="pass")
check("a stale record whose commit's main run passed: recorded as the last good commit (under the lock), the record gone, no block on the fast path",
      s["rc"] == 0 and "PR #26 was deployed at the merge as ba5e000 and its release process ended before main's run was read" in s["log"] and "main's tests passed on ba5e000 (run 7): recorded as the last good commit" in s["log"]
      and s["deploys"] == [MERGE] and s["pending_files"] == [] and s["lastgood"] == MERGE and s["lock_at_live"][0] == "held", (s["log"], s["deploys"], s["pending_files"], s["lastgood"]))
check("a stale record whose run passed: the server settles that PR's items too, then this release's own",
      s["released"] == ["released | --pr | https://github.com/example-owner/stackshot/pull/26 | --sha | " + BASE, RELEASED_ARGS + MERGE], s["released"])
s = fast("pv-stale-fail-noitems", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE)
check("a stale record whose run failed: its PR's items are not settled", not any("/pull/26 " in x for x in s["released"]), s["released"])
s = fast("pv-stale-fail", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE)
check("a stale record whose commit's main run failed: rolled back as a live watch would, a red report for that PR, the record gone",
      s["rc"] == 0 and s["deploys"][0] == f"rollback {GOOD}" and red(s) and "PR #26 FAILED at main's tests: rolled back to 600d000" in red(s)[0] and "the run on main for ba5e000 failed" in red(s)[0]
      and "whether a recycle was flagged for this PR is not known" in red(s)[0] and s["pending_files"] == [], (s["deploys"], s["msgs"], s["pending_files"]))
check("…and the release that found it takes the old path (the fast path refused, the reason in the log) and deploys its own merge, pinned",
      s["deploys"] == [f"rollback {GOOD}", MERGE] and "not up to date for a deploy at the merge: the deploy of PR #26 at ba5e000 failed main's run" in s["log"], (s["deploys"], s["log"]))
s = fast("pv-stale-unknown", merge="ok", runs=json.dumps([{"databaseId": 7, "headSha": MERGE}]), pending={"sha": NEWER, "pr": "26", "age": 3600 * 4})
check("a stale record whose commit's main run cannot be found after the cap (3 h): a red report for that PR (look at it, not rolled back), the record gone, the fast path refused",
      s["rc"] == 0 and len(red(s)) == 1 and "PR #26 FAILED at main's tests: deployed at 0107c0d and NOT rolled back, main's run was not read" in red(s)[0] and s["pending_files"] == []
      and s["deploys"] == [MERGE] and s["order"][0] != f"deploy:{MERGE}" and "has an unread verdict" in s["log"], (s["msgs"], s["order"], s["log"]))
RUNS67N = json.dumps([{"databaseId": 6, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}])   # the record's commit NEWER has only run 6, which no later run covers
s = fast("pv-stale-cancelled", merge="ok", runs=RUNS67N, pending={"sha": NEWER, "pr": "26"}, main6="cancelled")
check("a stale record whose only run was cancelled (a cancelled run says nothing, covering runs apart): kept like an unread one, the fast path refused, no red report yet",
      s["rc"] == 0 and not red(s) and s["pending_files"] == ["pr-26"] and "has not been verified" in s["log"] and s["deploys"] == [MERGE] and s["order"][0] != f"deploy:{MERGE}", (s["msgs"], s["deploys"], s["pending_files"], s["log"]))
s = fast("pv-stale-cancelled-old", merge="ok", runs=RUNS67N, pending={"sha": NEWER, "pr": "26", "age": 3600 * 4}, main6="cancelled")
check("...and past the cap (3 h) it is unknown: a red report naming the cancelled run (not rolled back), the record gone",
      s["rc"] == 0 and len(red(s)) == 1 and "NOT rolled back, main's run was not read" in red(s)[0] and "the run 6 on 0107c0d was cancelled and no later run covers it" in red(s)[0]
      and s["pending_files"] == [] and s["deploys"] == [MERGE], (s["msgs"], s["deploys"], s["pending_files"]))
s = fast("pv-stale-cancelled-covered", merge="ok", runs=RUNS67, pending=PEND, main6="cancelled")
check("a stale record whose own run was cancelled but a later run on a commit that contains it passed: that pass verifies it (recorded, record gone), no red report",
      s["rc"] == 0 and not red(s) and s["pending_files"] == [] and "main's tests passed on ba5e000 (run 7): recorded as the last good commit" in s["log"], (s["msgs"], s["log"], s["pending_files"]))
s = fast("pv-stale-pending", merge="ok", runs=RUNS67, pending=PEND, main6="pending")
check("a stale record whose run is still going: kept for the next start, the fast path refused meanwhile",
      s["rc"] == 0 and s["pending_files"] == ["pr-26"] and not red(s) and "has not been verified" in s["log"] and s["order"][0] != f"deploy:{MERGE}", (s["pending_files"], s["log"], s["order"]))
s = fast("pv-stale-old", merge="ok", runs=RUNS67, pending={**PEND, "age": 3600 * 4}, main6="pending")
check("a stale record whose run is still pending after the cap (3 h) is unknown: a red report, the record gone",
      s["rc"] == 0 and s["pending_files"] == [] and red(s) and "main's run was not read" in red(s)[0] and "still pending after 240 min" in red(s)[0], (s["msgs"], s["pending_files"]))
s = fast("pv-held", merge="ok", runs=RUNS67, pending={**PEND, "held": True}, main6="fail")
check("a record whose lock a live process holds is another release's running watch: left alone, no block on the fast path",
      s["rc"] == 0 and "ended before main's run was read" not in s["log"] and s["deploys"] == [MERGE] and s["order"][0] == f"deploy:{MERGE}" and s["pending_files"] == ["pr-26"], (s["log"], s["deploys"], s["pending_files"]))

# a release killed (SIGKILL, the whole process group) while it waits on main's run after the fast deploy: the next release to start finishes the job
sk = fast("pv-kill", merge="ok", kill_at=True)
lock_gone = False
lk = open(sk["dir"] / "releases/pending-verify/pr-23", "a") if sk["pending_files"] else None
for _ in range(100):   # the kernel lets go of a killed process's lock a moment after the kill
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); lock_gone = True; break
    except OSError: time.sleep(0.05)
if lk: lk.close()
check("a release killed while it waits on main's run leaves its record, with the commit, the PR and the time, and no process holds its lock",
      sk["rc"] != 0 and sk["deploys"] == [MERGE] and sk["pending_files"] == ["pr-23"] and f"sha={MERGE}" in (sk["dir"] / "releases/pending-verify/pr-23").read_text() and lock_gone, (sk["rc"], sk["pending_files"], sk["deploys"]))
s2 = fast("pv-kill-2", merge="ok", pr="25", reuse=sk, main7="pass")
check("…and the next release to start reads that commit's main run first: a pass is recorded as the last good commit, the record gone",
      s2["rc"] == 0 and "PR #23 was deployed at the merge as 0106c0d and its release process ended" in s2["log"] and "main's tests passed on 0106c0d (run 7): recorded as the last good commit" in s2["log"]
      and s2["pending_files"] == [] and s2["lastgood"] == MERGE, (s2["log"], s2["pending_files"], s2["lastgood"]))
sk = fast("pv-kill-f", merge="ok", kill_at=True)
s2 = fast("pv-kill-f2", merge="ok", pr="25", reuse=sk, main7="pass,fail,pass", heads=MERGE)
check("…a fail is a red report for the killed PR, a rollback to the last good commit, the record gone; the new release itself carries on (old path)",
      s2["rc"] == 0 and s2["deploys"] == [MERGE, f"rollback {GOOD}", MERGE] and any("PR #23 FAILED at main's tests: rolled back to 600d000" in m for m in red(s2)) and s2["pending_files"] == [], (s2["deploys"], s2["msgs"], s2["pending_files"]))

# ---- 13f. the fourth review
def reap(s):   # the background children a scenario started end by themselves; do not wait for them
    for pid in s["bgpids"]:
        try: os.kill(pid, 9)
        except OSError: pass

s = fast("pv-before-deploy", merge="ok")
check("the pending-verify record is written and locked BEFORE deploy.sh runs (production changes at its fast-forward), and deploy.sh does not inherit the lock",
      s["rc"] == 0 and s["pending_at_deploy"] == ["pr-23:locked"] and s["fd7"] == "closed" and s["pending_files"] == [], (s["pending_at_deploy"], s["fd7"], s["pending_files"]))
s = fast("pv-deploy-fails", merge="ok", deploy_fail="1")
check("a fast deploy that fails is reported red there and its record is cleared (nothing to verify)", s["rc"] == 1 and s["pending_at_deploy"] == ["pr-23:locked"] and s["pending_files"] == [] and "FAILED at deploy" in s["log"], (s["pending_at_deploy"], s["pending_files"], s["log"]))
s = fast("pv-old-nodeploy-record", merge="ok", base="")
check("the old path writes no record before its deploy either", s["rc"] == 0 and s["pending_at_deploy"] == [], s["pending_at_deploy"])

# "none" is not a verdict
s = fast("pv-stale-none-young", merge="ok", runs=json.dumps([{"databaseId": 7, "headSha": MERGE}]), pending={"sha": NEWER, "pr": "26"})
check("a stale record whose commit has no run yet, or whose run list could not be read: kept like a pending one, no red report, the fast path refused",
      s["rc"] == 0 and s["pending_files"] == ["pr-26"] and not red(s) and "no run for it could be read yet" in s["log"] and s["order"][0] != f"deploy:{MERGE}", (s["pending_files"], s["msgs"], s["log"]))
s = fast("pv-stale-none-old", merge="ok", runs=json.dumps([{"databaseId": 7, "headSha": MERGE}]), pending={"sha": NEWER, "pr": "26", "age": 3600 * 4})
check("…and after the cap (3 h) it is unknown: a red report (look at it, not rolled back), the record gone",
      s["rc"] == 0 and s["pending_files"] == [] and len(red(s)) == 1 and "PR #26 FAILED at main's tests: deployed at 0107c0d and NOT rolled back, main's run was not read" in red(s)[0] and "no run found for it in 240 min" in red(s)[0], (s["msgs"], s["pending_files"]))
# the cap stays well above the record's age (PEND: 60 s, plus release.sh's start): a record older than RELEASE_CAP_MAIN is given up on, so a cap of
# 60 made the verdict hang on whether the start crossed a second (main's run for 1010101); 600 is 30 polls
s = fast("pv-stale-gh-down", merge="ok", runs="not json", pending=PEND, extra={"RELEASE_CAP_MAIN": "600"})
check("a stale record while GitHub's run list cannot be read: kept, no verdict", s["pending_files"] == ["pr-26"] and not any("PR #26 FAILED" in m for m in s["msgs"]), (s["pending_files"], s["msgs"]))

# a recovery rollback that never ran keeps its record and does not claim a rollback
s = fast("pv-stale-locktimeout", merge="ok", runs=RUNS67, pending=PEND, main6="fail", hold=True, extra={"DEPLOY_LOCK_WAIT": "1"}, heads=BASE)
check("a recovery rollback that could not take the deploy lock: the record is kept, the report is the lock failure (nothing rolled back), and the log does not say it was dealt with",
      s["pending_files"] == ["pr-26"] and s["deploys"] == [] and any("PR #26 FAILED at deploy lock" in m and "nothing was rolled back" in m for m in s["msgs"])
      and "could not roll it back" in s["log"] and "was dealt with" not in s["log"], (s["pending_files"], s["deploys"], s["msgs"], s["log"]))

# the nits
order = [{"sha": BASE, "pr": "58", "age": 600}, {"sha": BASE, "pr": "26", "age": 100}]
s = fast("pv-order", merge="ok", runs=RUNS67, pending=order, main6="pass")
check("stale records are taken oldest deploy first, not in name order", s["log"].index("PR #58 was deployed") < s["log"].index("PR #26 was deployed"), s["log"])
s = fast("pv-set-fails", merge="ok", pending={"sha": BASE, "pr": "23", "held": True})
check("a record that cannot be locked (2 s) is told to the keeper, the release goes on",
      s["rc"] == 0 and s["deploys"] == [MERGE] and any("could not write the pending-verify record" in m and "--release" not in m for m in s["msgs"]), (s["rc"], s["msgs"]))
s = fast("fast-startup-failure", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "startup_failure"}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) a startup_failure run counts as failed, as run_state counts it: the old path", s["rc"] == 0 and f"has a failed run on main (run 5 on {FAILED_SHA})" in s["log"], s["log"])

# no lock outlives the release through a child that outlives its command
s = fast("fd-bg", merge="ok", bg="1")
free = lock_free(s); reap(s)
check("a background child spawned by git, gh or the client does not hold the deploy lock after the release", s["rc"] == 0 and len(s["bgpids"]) >= 3 and free, (s["rc"], s["bgpids"], free))
sk = fast("fd-bg-kill", merge="ok", kill_at=True, bg="1")
lock_gone = False; lk = open(sk["dir"] / "releases/pending-verify/pr-23", "a") if sk["pending_files"] else None
for _ in range(60 if lk else 0):
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); lock_gone = True; break
    except OSError: time.sleep(0.05)
if lk: lk.close()
dl = lock_free(sk); reap(sk)
check("…nor the pending-verify record's lock, after the release is killed (the children are alive: they started their own sessions)", len(sk["bgpids"]) >= 3 and lock_gone and dl, (sk["bgpids"], lock_gone, dl))

# ---- 13g. a branch behind main (Oliver: main's full run never blocks a release). Before, a PR behind main fell to the old path and waited for main's full run
# (a long wait), so in a burst only the first PR was fast. Now release.sh brings it up to date (gh pr update-branch, a merge), waits for the PR's own tests on the new head and
# deploys at the merge; main having moved meanwhile is another round (3 at most, then the old path); a conflict or failing tests fail the release. One release at a time, under the update lock.

# behind, update, the PR's tests pass, fast deploy
s = fast("upd-pass", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending,pass")
check("behind: update-branch (a merge, no --rebase), then the deploy at the merge, pinned to the new head, main's run read after the deploy",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == ["update-branch", f"deploy:{MERGE}", "client:message", "run-view"]
      and UPD_LINE in s["gh"].splitlines() and "--rebase" not in s["gh"]
      and f"pr merge 23 --repo example-owner/stackshot --merge --match-head-commit {H1}" in s["gh"].splitlines(), (s["rc"], s["order"], s["gh"], s["out"]))
check("behind: the PR's tests are polled every 20 s on the new head (one pending read), the log tells each step in order",
      s["sleeps"] == ["20"] and at(s["log"], "checks pass", "update lock taken", "update-branch round 1 of 3: main's tip ba5e000 is not in the PR head abc1234",
                                   "the PR head is now d00d100; waiting for the PR's tests on d00d100 (up to 50 min)", "waiting for the PR's tests on d00d100 (pending); 0 min of up to 50",
                                   "the PR's tests pass on the updated head d00d100", "update-branch: the PR head d00d100 contains main's tip ba5e000", "deploy lock taken",
                                   "up to date: the PR head d00d100 contains main's tip ba5e000, which is what is live", "deploying 0106c0d at once", "done: ", "main's tests passed on 0106c0d"), (s["sleeps"], s["log"]))
check("behind: one green report at the deploy, naming the update and that main's run follows; the last good commit moves to the merge",
      len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "brought it up to date with update-branch (1 round(s))" in s["msgs"][0] and "main's full run follows" in s["msgs"][0]
      and s["lastgood"] == MERGE, (s["msgs"], s["lastgood"]))
check("behind: the update lock is taken before the deploy lock, the deploy ran under the deploy lock, and nothing holds either at the end",
      s["lock_during"] == "held" and lock_free(s) and upd_lock_free(s) and s["log"].index("update lock taken") < s["log"].index("deploy lock taken"), (s["log"], s["lock_during"]))
check("behind: the update lock is held while gh updates the branch and merges and is let go at the merge (free in the deploy); fd 5 is closed in gh (update-branch, merge), git and client.py",
      s["ulock"] == ["held", "held", "free"] and s["upd_fd5"] == "closed" and s["merge_fd5"] == "closed" and s["git_fd5"] and set(s["git_fd5"]) == {"closed"}
      and s["client_fd5"] and set(s["client_fd5"]) == {"closed"}, (s["ulock"], s["upd_fd5"], s["merge_fd5"], set(s["git_fd5"]), s["client_fd5"]))
check("behind: the pass on the new head is confirmed in the check-runs of that very commit", f"api repos/example-owner/stackshot/commits/{H1}/check-runs?per_page=100" in s["gh"].splitlines(), s["gh"])
s = fast("upd-pass-stale", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass", checkruns="none,none,pass")
check("behind: gh pr checks says pass at once, but the tests job has no passed run on the new head yet (a pass read from the old head): pending, two polls, then the deploy",
      s["rc"] == 0 and s["sleeps"] == ["20", "20"] and s["deploys"] == [MERGE] and s["gh"].count("/check-runs?per_page=100") == 3 and at(s["log"], "waiting for the PR's tests on d00d100 (pending)", "the PR's tests pass on the updated head d00d100"), (s["sleeps"], s["gh"], s["log"]))
s = fast("upd-pass-quiet", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,lint,lint,pass")
check("behind: a quick check alone on the new head is no verdict: the tests job (suites) must be reported, so the release waits (two more reads) before it merges",
      s["rc"] == 0 and s["sleeps"] == ["20", "20"] and s["deploys"] == [MERGE] and s["gh"].count("pr checks") == 4, (s["sleeps"], s["gh"], s["log"]))

# behind, update, main moves meanwhile (a merge from outside the lock), a second update, pass
HIST_2 = ",".join([GOOD, HEADSHA, BASE, H1, B2, H2, *TAIL])
s = fast("upd-moves", merge="ok", history=HIST_2, bases=f"{BASE},{BASE},{B2}", base=B2, heads=B2, prheads=f"{HEADSHA},{HEADSHA},{H1},{H2}", p2=H2)
check("behind, main moves during the wait: updated again and waited for again (two rounds), then the fast deploy of the merge, pinned to the second head",
      s["rc"] == 0 and s["gh"].count(UPD_LINE) == 2 and s["order"] == ["update-branch", "update-branch", f"deploy:{MERGE}", "client:message", "run-view"] and s["deploys"] == [MERGE]
      and at(s["log"], "update-branch round 1 of 3: main's tip ba5e000", "update-branch round 2 of 3: main's tip ba5e200 is not in the PR head d00d100",
             "the PR's tests pass on the updated head d00d200", "up to date: the PR head d00d200 contains main's tip ba5e200")
      and f"--match-head-commit {H2}" in s["gh"] and "(2 round(s))" in s["msgs"][0], (s["order"], s["log"], s["gh"], s["out"]))

# main moves during every round: three rounds, then the old path, the reason in the log
HIST_3 = ",".join([GOOD, HEADSHA, BASE, H1, B2, H2, B3, H3, B4, *TAIL])
s = fast("upd-3-rounds", merge="ok", history=HIST_3, bases=f"{BASE},{BASE},{B2},{B3},{B4}", base=B4, prheads=f"{HEADSHA},{HEADSHA},{H1},{H2},{H3}", p2=H3)
check("main moves during each of 3 rounds: three update-branch calls and no fourth, then the old path (main's run first, then the deploy), the reason in the log",
      s["rc"] == 0 and s["gh"].count(UPD_LINE) == 3 and s["order"] == ["update-branch"] * 3 + ["run-view", f"deploy:{MERGE}", "client:message"] and s["deploys"] == [MERGE]
      and at(s["log"], "update-branch round 3 of 3", "update-branch: main moved again during each of 3 rounds and the branch is behind it still (main's tip ba5e400): the old path (main's run first)",
             "not up to date for a deploy at the merge: the branch is behind main", "(the old path)", "merged", "main's tests pass at 0106c0d")
      and f"--match-head-commit {H3}" in s["gh"], (s["order"], s["log"], s["gh"]))
check("the 3 rounds then the old path: the report says the branch was updated but then main moved again during each of the rounds, it is not the fast path's, and the merge's pass is the last good commit",
      len(s["msgs"]) == 1 and "brought up to date with update-branch (3 round(s)" in s["msgs"][0] and "but then main moved again during each of 3 rounds, so it took the old path" in s["msgs"][0]
      and "main's full run follows" not in s["msgs"][0] and s["lastgood"] == MERGE and lock_free(s) and upd_lock_free(s), (s["msgs"], s["lastgood"]))

# update-branch errors (a conflict): FAILED at update-branch, never the old path, nothing merged
s = fast("upd-conflict", merge="ok", history=HIST_B, update="fail")
check("update-branch conflicts: exit 1, FAILED at update-branch with GitHub's words, in the log and as the red report; nothing merged, nothing deployed, no fallback to the old path",
      s["rc"] == 1 and "FAILED at update-branch: HTTP 422: merge conflict between base and head" in s["log"] and len(red(s)) == 1 and "FAILED at update-branch: HTTP 422: merge conflict between base and head" in red(s)[0]
      and "--release" not in s["msgs"][0] and not merges(s) and not s["deployed"] and "run-view" not in s["order"] and s["gh"].count(UPD_LINE) == 1 and "the old path" not in s["log"]
      and lock_free(s) and upd_lock_free(s), (s["rc"], s["msgs"], s["log"], s["gh"]))
s = fast("upd-head-stuck", merge="ok", history=HIST_B)
check("update-branch is accepted but the PR head never moves: FAILED at update-branch after 3 min of reads every 10 s, nothing merged",
      s["rc"] == 1 and "FAILED at update-branch: update-branch was accepted but the PR head is still abc1234 after 3 min" in s["log"] and s["sleeps"] == ["10"] * 18 and not merges(s) and not s["deployed"], (s["sleeps"], s["log"]))

# A conflict that is only the generated tool-text snapshot (section 13i): tools/snapshot_regen.py decides and pushes (stubbed here: its own test is snapshot_regen_scenario.py);
# release.sh runs it where update-branch errors or GitHub says CONFLICTING, and goes back to the PR's tests on the new head. The stub answers RT_REGEN ("pushed <sha>" or "declined: <why>").
rg = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-regenstub-")); dirs.append(rg)
REGEN_STUB = rg / "snapshot_regen.py"
REGEN_STUB.write_text('''import os, sys
d = os.environ["RT_DIR"]
import fcntl
lf = open(os.environ.get("UPDATE_LOCK_FILE", d + "/releases/update.lock"), "a")
try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(lf, fcntl.LOCK_UN); lock = "free"
except OSError: lock = "held"
open(d + "/regen.log", "a").write(" ".join(sys.argv[1:]) + " | update lock " + lock + " | fd5 " + ("open" if os.path.lexists("/proc/%d/fd/5" % os.getpid()) else "closed") + "\\n")
print("snapshot_regen: stub details on stderr", file=sys.stderr)
print(os.environ.get("RT_REGEN", "declined: no answer"))
sys.exit(0 if os.environ.get("RT_REGEN", "").startswith("pushed ") else 1)
''')
RGX = {"RELEASE_SNAPSHOT_REGEN": str(REGEN_STUB)}
def regen_calls(s): return (s["dir"] / "regen.log").read_text().splitlines() if (s["dir"] / "regen.log").exists() else []
s = fast("regen-update", merge="ok", history=HIST_1, update="fail", prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending,pass", regen=f"pushed {H1}", extra=RGX)
check("update-branch conflicts but the helper pushes a merge: no FAILED, the helper ran once with the repo, the PR's branch and the head it was given, under the update lock with fd 5 closed in it; then the PR's tests on the new head and the fast deploy",
      s["rc"] == 0 and s["deploys"] == [MERGE] and regen_calls(s) == [f"--repo {s['dir']}/box --branch=agent/topic --head {HEADSHA} | update lock held | fd5 closed"]
      and s["gh"].count(UPD_LINE) == 1 and f"--match-head-commit {H1}" in s["gh"] and "FAILED" not in s["log"] and not red(s)
      and at(s["log"], "update-branch round 1 of 3", "update-branch: the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 2)",
             f"update-branch: the only conflicted path was tests/tool_text.snapshot.json: took main's, regenerated it (tool_text.py update, check passed), and pushed the merge {H1} to agent/topic",
             "the PR head is now d00d100; waiting for the PR's tests on d00d100", "the PR's tests pass on the updated head d00d100", "up to date: the PR head d00d100 contains main's tip ba5e000", "deploying 0106c0d at once")
      and lock_free(s) and upd_lock_free(s), (s["rc"], regen_calls(s), s["log"], s["gh"]))
check("the regeneration costs no GitHub call of its own: the gh calls are those of an ordinary update (one update-branch, the views and checks), nothing else",
      all(l.split()[0] in ("pr", "api", "run") for l in s["gh"].splitlines()) and "snapshot" not in s["gh"] and s["gh"].count("pr update-branch") == 1, s["gh"])
check("the helper's details (its stderr) reach the log", "snapshot_regen: stub details on stderr" in s["log"], s["log"])

s = fast("regen-update-declined", merge="ok", history=HIST_B, update="fail", regen="declined: the conflict is not only the snapshot: src/server.py, tests/tool_text.snapshot.json", extra=RGX)
check("update-branch conflicts and the helper declines (another path conflicts too): the failure is exactly the one of a conflict without the helper (same words, same exit, red report, nothing merged), with the helper's reason in the log",
      s["rc"] == 1 and "FAILED at update-branch: HTTP 422: merge conflict between base and head; the branch could not be brought up to date, nothing was merged (a conflict with main is for the PR's author to resolve)" in s["log"]
      and len(red(s)) == 1 and not merges(s) and not s["deployed"] and "run-view" not in s["order"] and s["gh"].count(UPD_LINE) == 1 and len(regen_calls(s)) == 1
      and "update-branch: the snapshot is not regenerated: declined: the conflict is not only the snapshot: src/server.py, tests/tool_text.snapshot.json" in s["log"]
      and lock_free(s) and upd_lock_free(s), (s["rc"], s["log"], s["msgs"]))
s = fast("upd-conflict-nohelper", merge="ok", history=HIST_B, update="fail")
check("update-branch conflicts and there is no helper file (a checkout from before it): the same failure, the log says so, nothing else changes",
      s["rc"] == 1 and "FAILED at update-branch: HTTP 422: merge conflict between base and head; the branch could not be brought up to date" in s["log"] and "snapshot_regen.py is missing" in s["log"]
      and not merges(s) and not s["deployed"] and s["gh"].count(UPD_LINE) == 1, (s["rc"], s["log"]))
s = fast("regen-update-cross", merge="ok", history=HIST_B, update="fail", cross="1", regen=f"pushed {H1}", extra=RGX)
check("a cross-repository PR is never pushed to: the helper is not run, the failure is the old one",
      s["rc"] == 1 and "FAILED at update-branch: HTTP 422" in s["log"] and not regen_calls(s) and "cross-repository True" in s["log"], (s["rc"], s["log"]))
s = fast("regen-update-nofetch", merge="ok", history=HIST_B, update="fail", prfetch_fail="1", prfetch_from="3", regen=f"pushed {H1}", extra=RGX)   # the first two fetches (up_to_date's, then its look again under the update lock) work, the helper's own (the third) fails
check("the fetch of main and the PR head fails: the helper is not run, the failure is the old one",
      s["rc"] == 1 and "FAILED at update-branch: HTTP 422" in s["log"] and not regen_calls(s) and "cannot fetch main and the PR head from origin" in s["log"], (s["rc"], s["log"]))

# bounded: main moves during every round and every update-branch conflicts, so the helper is asked each round; RELEASE_REGEN_MAX (2) of them are made, the third conflict fails as before
s = fast("regen-bound", merge="ok", history=HIST_3, update="fail", bases=f"{BASE},{BASE},{B2},{B3},{B4}", base=B4, prheads=f"{HEADSHA},{HEADSHA},{H1},{H2},{H3}", p2=H3, regen=f"pushed {H1}", extra=RGX)
check("the helper is run at most twice per release: two regenerations (rounds 1 and 2), then the third conflict says so and fails at update-branch exactly as before; no merge, no deploy",
      s["rc"] == 1 and len(regen_calls(s)) == 2 and s["gh"].count(UPD_LINE) == 3 and not merges(s) and not s["deployed"]
      and "update-branch: the tool-text snapshot was regenerated 2 time(s) in this release already (RELEASE_REGEN_MAX=2); not again" in s["log"]
      and "FAILED at update-branch: HTTP 422: merge conflict between base and head; the branch could not be brought up to date" in s["log"]
      and "(regeneration 1 of 2)" in s["log"] and "(regeneration 2 of 2)" in s["log"] and "(regeneration 3" not in s["log"], (s["rc"], regen_calls(s), s["log"]))
s = fast("regen-bound-one", merge="ok", history=HIST_3, update="fail", bases=f"{BASE},{BASE},{B2},{B3},{B4}", base=B4, prheads=f"{HEADSHA},{HEADSHA},{H1},{H2},{H3}", p2=H3, regen=f"pushed {H1}",
         extra={**RGX, "RELEASE_REGEN_MAX": "1"})
check("RELEASE_REGEN_MAX=1: one regeneration, the second conflict fails", s["rc"] == 1 and len(regen_calls(s)) == 1 and "(RELEASE_REGEN_MAX=1); not again" in s["log"], (s["rc"], regen_calls(s), s["log"]))

# the first look at the PR says CONFLICTING (before any update): the helper is asked, GitHub is read again (every 10 s) until the head moved and it has recomputed, then the release goes on
s = scenario("regen-mergeable", merge="ok", mergeable="CONFLICTING,UNKNOWN,MERGEABLE", prheads=f"{HEADSHA},{H1},{H1}", regen=f"pushed {H1}", extra=RGX)
check("mergeable CONFLICTING and the helper pushes: no FAILED; GitHub is read every 10 s until the head moved and mergeable is not UNKNOWN or CONFLICTING (3 reads, 2 sleeps), then the release goes on to the PR's tests on the new head and deploys",
      s["rc"] == 0 and s["deployed"] and s["sleeps"][:2] == ["10", "10"] and len(regen_calls(s)) == 1 and regen_calls(s)[0].startswith(f"--repo {s['dir']}/box --branch=agent/topic --head {HEADSHA} |")
      and s["gh"].count("state,mergeable") >= 3 and "FAILED" not in s["log"]
      and at(s["log"], "mergeable: the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 2)", "mergeable: the only conflicted path was tests/tool_text.snapshot.json",
             "mergeable: after the snapshot regeneration GitHub says MERGEABLE (head d00d100)", "PR #23: a change (head d00d100)"), (s["rc"], s["sleeps"], regen_calls(s), s["log"]))
s = scenario("regen-mergeable-quiet", merge="ok", mergeable="CONFLICTING,UNKNOWN,MERGEABLE", prheads=f"{HEADSHA},{H1},{H1}", regen=f"pushed {H1}", checks="lint,lint,pass", extra=RGX)
check("mergeable CONFLICTING, the helper pushes, and only a quick check (lint) is reported on the new head: not a pass, the release keeps waiting (two more reads) until suites is reported, and names it as the PR's tests on the pushed head",
      s["rc"] == 0 and s["deployed"] and s["gh"].count("pr checks") == 3 and s["sleeps"][2:4] == ["20", "20"] and "FAILED" not in s["log"]
      and at(s["log"], "mergeable: after the snapshot regeneration GitHub says MERGEABLE (head d00d100)", "waiting for the PR's tests on d00d100", "the PR's tests pass on the pushed head d00d100"), (s["rc"], s["sleeps"], s["gh"], s["log"]))
check("mergeable CONFLICTING, the helper pushes: the pass on the pushed head is confirmed in the check-runs of that very commit before the merge",
      f"api repos/example-owner/stackshot/commits/{H1}/check-runs?per_page=100" in s["gh"].splitlines(), s["gh"])
s = scenario("regen-mergeable-still",merge="ok", mergeable="CONFLICTING", prheads=f"{HEADSHA},{H1}", regen=f"pushed {H1}", extra=RGX)
check("mergeable CONFLICTING, the helper pushes, but GitHub still says CONFLICTING after 3 min: FAILED at mergeable as before (one regeneration only)",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and len(regen_calls(s)) == 1 and s["sleeps"] == ["10"] * 18 and not merges(s) and not s["deployed"], (s["rc"], s["sleeps"], s["msg"]))
s = scenario("regen-mergeable-declined", merge="ok", mergeable="CONFLICTING", regen="declined: the conflict is not only the snapshot: src/server.py", extra=RGX)
check("mergeable CONFLICTING and the helper declines: FAILED at mergeable with the old words at once, no wait, nothing merged",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub says CONFLICTING: the PR has a conflict with main" in s["msg"] and s["gh"].count("state,mergeable") == 1 and not s["sleeps"]
      and len(regen_calls(s)) == 1 and "mergeable: the snapshot is not regenerated: declined: the conflict is not only the snapshot: src/server.py" in s["log"] and not merges(s) and not s["deployed"], (s["rc"], s["log"], s["msg"]))

# the PR's tests fail (or never finish) on the updated head
s = fast("upd-tests-fail", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending,fail")
check("the PR's run fails on the updated head: FAILED at pr tests naming the check, red report, nothing merged or deployed; the locks are free",
      s["rc"] == 1 and "FAILED at pr tests: a check failed: suites=fail" in s["log"] and len(red(s)) == 1 and "FAILED at pr tests: a check failed: suites=fail" in red(s)[0] and "--release" not in s["msgs"][0]
      and not merges(s) and not s["deployed"] and "FAILED at checks" not in s["log"] and lock_free(s) and upd_lock_free(s), (s["rc"], s["msgs"], s["log"]))
s = fast("upd-tests-toolfail", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,toolfail")
check("another check (tool-text) fails on the new head while suites is still queued: FAILED at pr tests at once, naming it, without waiting for suites",
      s["rc"] == 1 and "FAILED at pr tests: a check failed: tool-text=fail" in s["log"] and "suites=" not in s["log"].split("FAILED at pr tests")[1] and not s["sleeps"] and not merges(s) and not s["deployed"], (s["sleeps"], s["log"]))
s = fast("upd-tests-cap", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending", extra={"RELEASE_WAIT_CHECKS": "600"})
check("the wait for the PR's tests is capped like the first one (10 min of 20 s polls, 30 sleeps; the default is 50 min), with a progress line every 5 min for --status; then FAILED at pr tests",
      s["rc"] == 1 and "FAILED at pr tests: still pending after 10 min" in s["log"] and len(s["sleeps"]) == 30 and s["log"].count("min of up to 10") == 3 and not merges(s), (len(s["sleeps"]), s["log"][-600:]))

# a head pushed while the release waited for the update lock: its tests are waited for; already up to date, no update is made; still behind, it is updated on top
HX = "d00d9000000000000000000000000000000000d9"
s = fast("upd-pushed-uptodate", merge="ok", history=",".join([GOOD, HEADSHA, BASE, HX, *TAIL]), prheads=f"{HEADSHA},{HX}", p2=HX, checks="pass,pending,pass")
check("a head pushed while waiting for the lock (and already containing main's tip): its tests are waited for, no update-branch, the merge is pinned to the pushed head, fast deploy",
      s["rc"] == 0 and UPD_LINE not in s["gh"] and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] and f"--match-head-commit {HX}" in s["gh"]
      and at(s["log"], "update lock taken", "the PR head moved while this release waited for the update lock (abc1234 -> d00d900)", "the PR's tests pass on the pushed head d00d900",
             "update-branch: the PR head d00d900 contains main's tip ba5e000; no update is needed", "up to date: the PR head d00d900")
      and "needed no update once this release had the update lock" in s["msgs"][0], (s["log"], s["gh"], s["msgs"]))
s = fast("upd-pushed-behind", merge="ok", history=",".join([GOOD, HEADSHA, HX, BASE, H1, *TAIL]), prheads=f"{HEADSHA},{HX},{H1}", p2=H1, checks="pass,pass,pending,pass")
check("a head pushed while waiting for the lock that is still behind main: its tests first, then one update on top of it",
      s["rc"] == 0 and s["gh"].count(UPD_LINE) == 1 and at(s["log"], "the PR head moved while this release waited", "the PR's tests pass on the pushed head d00d900", "update-branch round 1 of 3: main's tip ba5e000 is not in the PR head d00d900")
      and f"--match-head-commit {H1}" in s["gh"] and s["deploys"] == [MERGE], (s["log"], s["gh"]))
# the re-check after the rounds cannot read (the fetch fails): the report says so, not "main moved on"
s = fast("upd-recheck-fetch", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, prfetch_fail="1", prfetch_from="3")
check("the re-check after a round cannot fetch: the old path, and the report says the re-check could not be made, not that main moved on",
      s["rc"] == 0 and s["gh"].count(UPD_LINE) == 1 and s["order"] == ["update-branch", "run-view", f"deploy:{MERGE}", "client:message"]
      and "update-branch: stopped after 1 round(s), cannot fetch main and the PR head from origin: the old path" in s["log"]
      and "then the re-check could not be made (cannot fetch main and the PR head from origin), so it took the old path" in s["msgs"][0]
      and "main moved" not in s["msgs"][0], (s["order"], s["log"], s["msgs"]))

# two releases contend: the update, the wait and the merge of one finish before the other's update starts
ud = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-update-")); dirs.append(ud)
ushared = {"UPDATE_LOCK_FILE": str(ud / "update.lock"), "DEPLOY_LOCK_FILE": str(ud / "deploy.lock"), "RT_UTRACE": str(ud / "trace"), "UPDATE_LOCK_WAIT": "60", "DEPLOY_LOCK_WAIT": "60"}
ures = {}
def uthread(k): ures[k] = fast(f"upd-lock-{k}", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, extra=ushared)
ta = threading.Thread(target=uthread, args=("a",)); tb = threading.Thread(target=uthread, args=("b",))
ta.start()
for _ in range(600):   # B starts once A's update-branch is running (it takes 2 real seconds in the stub), so B meets the lock held
    if (ud / "trace").exists(): break
    threading.Event().wait(0.05)
tb.start(); ta.join(); tb.join()
ua, ub = ures.get("a"), ures.get("b")
utr = (ud / "trace").read_text().splitlines() if (ud / "trace").exists() else []
check("two behind releases on one update lock: both go through, and one's update-branch and merge come before the other's update-branch (never interleaved)",
      ua and ub and ua["rc"] == 0 and ub["rc"] == 0 and len(utr) == 4 and [l.split()[0] for l in utr] == ["update-branch", "merge", "update-branch", "merge"]
      and utr[0].split()[1] == utr[1].split()[1] and utr[2].split()[1] == utr[3].split()[1] and utr[0].split()[1] != utr[2].split()[1], (utr, ua and ua["out"], ub and ub["out"]))
check("two behind releases: the second says it waits for the update lock, the first does not, and both deploy their merge",
      bool(ua and ub) and "another release holds the update lock (it is bringing its branch up to date, waiting for its tests or merging); waiting up to 120 min (7200 s)" not in ua["log"]
      and "another release holds the update lock" not in ua["log"] and "another release holds the update lock" in ub["log"] and "update lock taken" in ub["log"]
      and ua["deploys"] == [MERGE] and ub["deploys"] == [MERGE], (ua and ua["log"], ub and ub["log"]))
check("two behind releases: nothing holds the update lock or the deploy lock after", file_free(ud / "update.lock") and file_free(ud / "deploy.lock"))
ul = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-updtimeout-")); dirs.append(ul)
uheld = open(ul / "update.lock", "w"); fcntl.flock(uheld, fcntl.LOCK_EX)   # another release is bringing its branch up to date, and stays at it past the timeout
try: s = fast("upd-lock-timeout", merge="ok", history=HIST_B, extra={"UPDATE_LOCK_FILE": str(ul / "update.lock"), "UPDATE_LOCK_WAIT": "1"})
finally: uheld.close()
check("the update lock held elsewhere past the timeout: FAILED at update lock before anything is merged or updated (release.sh again once it is free)",
      s["rc"] == 1 and "FAILED at update lock: another release held the update lock" in s["log"] and "release.sh 23 again once it is free" in s["log"]
      and UPD_LINE not in s["gh"] and not merges(s) and not s["deployed"], (s["rc"], s["log"]))

# the default wait for the update lock is what its holder can take: 3 x (50 + 3 min) + 15 min = 174 min (10440 s); the lock is released while the second release waits, and it goes through
ud2 = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-updwait-")); dirs.append(ud2); (ud2 / "releases").mkdir()
held2 = open(ud2 / "releases/update.lock", "w"); fcntl.flock(held2, fcntl.LOCK_EX)
def unhold2():
    try:
        end = time.time() + 60; lg = ud2 / "releases/pr-23.log"
        while time.time() < end and "another release holds the update lock" not in (lg.read_text() if lg.exists() else ""): time.sleep(0.05)
        time.sleep(0.3)
    finally: fcntl.flock(held2, fcntl.LOCK_UN)
t2 = threading.Thread(target=unhold2); t2.start()
try: s = fast("upd-lock-default-wait", merge="ok", reuse={"dir": ud2}, history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1)
finally: t2.join(); held2.close()
check("the update lock's default wait is 3 x (50 + 3 min) + 15 min: the log says 174 min (10440 s), and the release goes on when the lock is let go",
      s["rc"] == 0 and "waiting up to 174 min (10440 s)" in s["log"] and s["deploys"] == [MERGE] and upd_lock_free(s), (s["rc"], s["log"]))

# --status shows what the release waits for: the newest log line of a release parked on the PR's tests
sd = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-status-")); dirs.append(sd)
(sd / "bin").mkdir(); (sd / "bin/systemctl").write_text("#!/bin/sh\necho active\n"); (sd / "bin/systemctl").chmod(0o755)   # the unit is running; never the host's systemctl
sres = {}
tp = threading.Thread(target=lambda: sres.update(s=fast("upd-status", merge="ok", reuse={"dir": sd}, history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending,pass", park_at="2")))
tp.start()
try:
    for _ in range(600):
        if (sd / "parked").exists(): break
        threading.Event().wait(0.05)
    st = subprocess.run(["bash", str(sd / "box/release.sh"), "--status", "23"], env={**os.environ, "PATH": f"{sd}/bin:" + os.environ.get("PATH", ""), "RT_DIR": str(sd)}, capture_output=True, text=True, timeout=60)
finally:
    (sd / "unpark").touch(); tp.join()
stl = st.stdout.rstrip("\n").splitlines()
check("--status of a release waiting for the PR's tests on the updated head: the unit is active and the newest log line says what is waited for",
      st.returncode == 0 and stl[0] == "unit stackshot-release-23: active" and "waiting for the PR's tests on d00d100" in stl[-1] and "update-branch round 1 of 3" in st.stdout, st.stdout)
check("--status: the same release then finishes with the deploy", sres.get("s") and sres["s"]["rc"] == 0 and sres["s"]["deploys"] == [MERGE], sres.get("s") and sres["s"]["out"])

# ---- 16. the session pick: what the running sessions need, from the files the merged PR changed (nothing, a notice or a recycle; the highest wins)
def recycled(s): return "recycle-due | --pr" in s["msg"]
def pick_reads(s): return [l for l in s["gh"].splitlines() if l.startswith("api repos/example-owner/stackshot/pulls/23/files")]
s = scenario("pick-server-only", merge="ok", pickfiles="server.py,render.py,docs/windows.md,tests/release_scenario.py", notice="notify")
check("pick: a server-only PR (code, docs, tests) picks nothing: no recycle, no notice, green, the log and report name the pick and the files",
      s["rc"] == 0 and s["deployed"] and not recycled(s) and not s["notice"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS)
      and "session pick: nothing (from server.py, render.py, docs/windows.md, tests/release_scenario.py)" in s["log"]
      and "sessions: nothing (from server.py, render.py" in s["msgs"][0] and len(pick_reads(s)) == 1, (s["log"], s["msgs"], s["gh"]))
s = scenario("pick-per-call-hook", merge="ok", pickfiles="client/hooks/project-page.sh,client/hooks/client.sh,client.py,pages.py", notice="notify")
check("pick: a per-call hook script and the client CLI pick nothing (each call runs them afresh)",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and "session pick: nothing (from client/hooks/project-page.sh" in s["log"]
      and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
s = scenario("pick-start-loaded", merge="ok", pickfiles="server.py,docs/windows.md,client/hooks/session-start.sh", notice="notify")
check("pick: a file loaded at the session's start picks a recycle, over nothing: recycle-due on the PR, no notice, green",
      s["rc"] == 0 and recycled(s) and not s["notice"] and "session pick: recycle (from client/hooks/session-start.sh)" in s["log"]
      and "sessions: recycle (from client/hooks/session-start.sh)" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
check("pick: the log lists each changed file with its need", all(t in s["log"] for t in ("recycle  client/hooks/session-start.sh", "nothing  docs/windows.md", "nothing  server.py")), s["log"])
# a PR that needs a recycle and also a notice does both: a recycle does not deliver a notice's change (the tools' text, the write rules)
s = scenario("pick-mixed", merge="ok", pickfiles="server.py,next_rules.py,client/hooks/session-start.sh,tests/tool_text.snapshot.json", notice="notify --all")
check("pick: files that need a recycle and a notice do both: recycle-due on the PR, and [fleet] notice_cmd run with the notice files only, green",
      s["rc"] == 0 and recycled(s) and s["notice"][0] == "--all" and len(s["notice"]) == 2 and s["notice"][1].startswith("release: stackshot PR #23: a change \u2014 ")
      and "next_rules.py, tests/tool_text.snapshot.json" in s["notice"][1] and "session-start.sh" not in s["notice"][1] and "a recycle does not deliver it" in s["notice"][1]
      and "session pick: recycle + notice (from client/hooks/session-start.sh; notice from next_rules.py, tests/tool_text.snapshot.json)" in s["log"]
      and "sessions: recycle + notice (from client/hooks/session-start.sh; notice from next_rules.py" in s["msgs"][0]
      and "notice: sent" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
check("pick: the log lists the notice file and the recycle file with their needs", all(t in s["log"] for t in ("recycle  client/hooks/session-start.sh", "notice   next_rules.py", "nothing  server.py")), s["log"])
s = scenario("pick-mixed-notice-fails", merge="ok", pickfiles="client/hooks/session-start.sh,next_rules.py", notice="notify", notice_fail="1")
check("pick: a failed notice beside a recycle still runs the recycle, and the report goes to the keeper instead of green",
      s["rc"] == 0 and recycled(s) and len(s["notice"]) == 1 and "notice NOT sent" in s["msgs"][0] and "recycle: " in s["msgs"][0] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-mixed-notice-unset", merge="ok", pickfiles="client/hooks/session-start.sh,next_rules.py")
check("pick: a recycle with a notice and no [fleet] notice_cmd set runs the recycle, says no notice command is set, and stays green",
      s["rc"] == 0 and recycled(s) and "notice: none sent, no [fleet] notice_cmd is set" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
# a notice command that never finishes is stopped at the timeout (RELEASE_NOTICE_TIMEOUT, 60 s by default): not sent, no green, and the report still goes out
s = scenario("pick-notice-hangs", merge="ok", pickfiles="model_guards.py", notice="notify", notice_hang="1", extra={"RELEASE_NOTICE_TIMEOUT": "1"}, secs=60)
check("pick: a notice command that hangs is stopped at the timeout: the log says it timed out, the report goes out without the green flag, the release finishes",
      s["rc"] == 0 and s["deployed"] and len(s["msgs"]) == 1 and "notice NOT sent: [fleet] notice_cmd timed out after 1s" in s["msgs"][0] and "--release" not in s["msgs"][0]
      and "notice NOT sent: [fleet] notice_cmd timed out after 1s" in s["log"], (s["rc"], s["log"], s["msgs"]))
check("pick: the hung notice command is gone (stopped, not left running)", s["notice_pid"].isdigit() and not os.path.exists(f"/proc/{s['notice_pid']}"), s["notice_pid"])
check("pick: the notice timeout is 60 s by default", 'NOTICE_TIMEOUT="${RELEASE_NOTICE_TIMEOUT:-60}"' in pathlib.Path(STACK, "release.sh").read_text(), "")
# a hostile title reaches the notice command as one argument, verbatim, and runs nothing
HOSTILE = "it's \"quoted\" `touch PWNED_bt` $(touch PWNED_cmd) $HOME ${HOME} ; touch PWNED_semi & \\n *"
s = scenario("pick-notice-hostile-title", merge="ok", pickfiles="model_guards.py", notice="notify --all", title=HOSTILE)
leftovers = [str(q) for base in (s["dir"], s["dir"] / "box", pathlib.Path.cwd()) for q in base.glob("PWNED_*")]
check("pick: a hostile title (quotes, backticks, $(...), $HOME) reaches [fleet] notice_cmd inside its one text argument, verbatim apart from the joiner, and nothing in it runs",
      s["rc"] == 0 and s["notice"][:1] == ["--all"] and len(s["notice"]) == 2 and s["notice"][1].startswith(f"release: stackshot PR #23: {HOSTILE} \u2014 stackshot PR #23 is live at ")
      and "$HOME" in s["notice"][1] and len(s["notice"][1]) <= 400 and not leftovers, (s["notice"], leftovers, s["log"]))
# the fleet notice command takes one text argument of at most 400 characters with no newline or tab: the title and summary are joined, flattened and cut
s = scenario("pick-notice-flatten", merge="ok", pickfiles="model_guards.py", notice="notify", title="line one\nline two\tcell\r\nline three")
check("pick: a newline or tab in the title becomes a space, and the one argument has none left",
      s["rc"] == 0 and len(s["notice"]) == 1 and s["notice"][0].startswith("release: stackshot PR #23: line one line two cell  line three \u2014 stackshot PR #23 is live at ")
      and not any(c in s["notice"][0] for c in "\n\t\r"), (s["notice"], s["log"]))
LONG = "long title " + "x" * 600
s = scenario("pick-notice-cut", merge="ok", pickfiles="model_guards.py", notice="notify", title=LONG)
check("pick: a notice longer than 400 characters is cut to exactly 400, ending in an ellipsis, and the release stays green",
      s["rc"] == 0 and len(s["notice"]) == 1 and len(s["notice"][0]) == 400 and s["notice"][0].endswith("x\u2026") and s["notice"][0].startswith("release: stackshot PR #23: long title xxx")
      and "notice: sent" in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
s = scenario("pick-notice-fits", merge="ok", pickfiles="model_guards.py", notice="notify")
check("pick: a notice of 400 characters or fewer is not cut and has no ellipsis", s["rc"] == 0 and len(s["notice"]) == 1 and len(s["notice"][0]) <= 400 and not s["notice"][0].endswith("\u2026"), s["notice"])
s = scenario("pick-rules-text", merge="ok", pickfiles="server.py,next_rules.py,audit_rubric.txt", notice="notify --all")
check("pick: a rules-text file picks a notice: [fleet] notice_cmd runs with one argument appended (title and summary joined), no recycle, green",
      s["rc"] == 0 and not recycled(s) and s["notice"][0] == "--all" and len(s["notice"]) == 2 and s["notice"][1].startswith("release: stackshot PR #23: a change \u2014 stackshot PR #23 is live at ")
      and "next_rules.py, audit_rubric.txt" in s["notice"][1] and "\n" not in s["notice"][1]
      and "session pick: notice (from next_rules.py, audit_rubric.txt)" in s["log"] and "notice: sent" in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
s = scenario("pick-tool-text", merge="ok", pickfiles="server.py,tests/tool_text.snapshot.json", notice="notify")
check("pick: a change to the tools' text is a notice, never a recycle", s["rc"] == 0 and not recycled(s) and len(s["notice"]) == 1 and "session pick: notice (from tests/tool_text.snapshot.json)" in s["log"], (s["log"], s["notice"]))
s = scenario("pick-notice-unset", merge="ok", pickfiles="audit_rubric.txt")
check("pick: a notice with no [fleet] notice_cmd set logs that none is set and does not fail the release (still green)",
      s["rc"] == 0 and s["deployed"] and "notice: none sent, no [fleet] notice_cmd is set" in s["log"] and not s["notice"]
      and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "FAILED" not in s["log"], (s["log"], s["msgs"]))
s = scenario("pick-notice-fails", merge="ok", pickfiles="model_guards.py", notice="notify", notice_fail="1")
check("pick: a notice command that fails does not fail the release, and the report goes to the keeper instead of green",
      s["rc"] == 0 and len(s["notice"]) == 1 and "notice NOT sent" in s["msgs"][0] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-notice-missing", merge="ok", pickfiles="model_guards.py", notice="no-such-notice-tool")
check("pick: a notice command not on PATH is told the same way", s["rc"] == 0 and "notice NOT sent" in s["msgs"][0] and "--release" not in s["msgs"][0], s["msgs"])
s = scenario("pick-override-recycle", args=("--recycle",), merge="ok", pickfiles="server.py", notice="notify")
check("--recycle forces a recycle on a server-only PR, and the files are not read",
      s["rc"] == 0 and recycled(s) and not s["notice"] and not pick_reads(s) and "session pick: recycle (from forced by --recycle)" in s["log"], (s["log"], s["gh"]))
s = scenario("pick-override-no-recycle", args=("--no-recycle",), merge="ok", pickfiles="client/hooks/session-start.sh,next_rules.py", notice="notify")
check("--no-recycle forces nothing on a PR that would pick a recycle: no recycle, no notice, no read, green",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and not pick_reads(s) and "session pick: nothing (from forced by --no-recycle)" in s["log"]
      and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
s = scenario("pick-files-unreadable", merge="ok", pickfiles="fail", notice="notify")
check("pick: files that cannot be read pick nothing, say so, and the report goes to the keeper instead of green",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and "could not be read (HTTP 502: bad gateway)" in s["log"] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-front-both", args=("--recycle", "--no-recycle"), front=True, merge="ok")
check("front door: two overrides are refused with the usage line", s["rc"] == 2 and "usage: release.sh <pr> [--recycle | --no-recycle]" in s["out"] and not s["gh"], s["out"])

# the dry runs: the pick and each file's need, nothing else (no merge, no deploy, no message)
s = scenario("pick-dry-files", raw=["--pick-files", "server.py", "client/hooks/session-start.sh", "next_rules.py"])
check("--pick-files: prints the pick and each file's need, calls nothing, deploys nothing, sends nothing; a recycle with a notice reads \"recycle + notice\"",
      s["rc"] == 0 and "session pick for the files named: recycle + notice (from client/hooks/session-start.sh; notice from next_rules.py)" in s["out"] and "notice   next_rules.py" in s["out"]
      and not s["gh"] and not s["deployed"] and not s["msg"] and not os.path.exists(s["dir"] / "releases/pr-23.log"), s["out"])
s = scenario("pick-dry-pr", raw=["--pick", "23"], pickfiles="server.py,audit_rubric.txt")
check("--pick <pr>: one read of the PR's files, prints the pick, nothing else",
      s["rc"] == 0 and "session pick for PR #23: notice (from audit_rubric.txt)" in s["out"] and len(pick_reads(s)) == 1
      and s["gh"].count("\n") == 1 and not s["deployed"] and not s["msg"], (s["out"], s["gh"]))
s = scenario("pick-dry-pr-unreadable", raw=["--pick", "23"], pickfiles="fail")
check("--pick <pr>: an unreadable PR exits 1 and says so", s["rc"] == 1 and "could not be read" in s["out"] and not s["deployed"], s["out"])
s = scenario("pick-dry-usage", raw=["--pick"])
check("--pick with no PR: exit 2 and the usage", s["rc"] == 2 and "usage: release.sh --pick <pr>" in s["out"], s["out"])

# the table in docs/session-reload.md and session_need say the same thing: every file the table names outright has the need its row says
doc = pathlib.Path(STACK, "docs/session-reload.md").read_text()
rows = [l for l in doc.split("## How a session reads each file", 1)[1].splitlines() if l.startswith("| `")]
named = []
for l in rows:
    cells = [c.strip() for c in l.strip("|").split("|")]
    need = next((n for n in ("recycle", "notice", "nothing") if n in cells[2].lower()), None)
    named += [(f, need) for f in __import__("re").findall(r"`([^`* ]+)`", cells[0])]
s = scenario("pick-doc-table", raw=["--pick-files", *[f for f, _ in named]])
got = {ln.split()[1]: ln.split()[0] for ln in s["out"].splitlines()[1:] if ln.strip()}
off = [(f, n, got.get(f)) for f, n in named if got.get(f) != n]
check("docs/session-reload.md: every file its table names has the need session_need gives it", len(named) >= 10 and not off, off or named)

# ---- the report's destination is a setting: [release] report_to, the stand-in page when it is unset
REPORTS = "projects/example-reports"
s = scenario("report-to-set", merge="ok", report_to=REPORTS)
check("report_to: a configured page receives the green report (the same arguments), and the stand-in page receives nothing",
      len(s["msgs"]) == 1 and s["msgs"][0].startswith(f"message | {REPORTS} | [release] PR #23 merged and deployed") and s["msgs"][0].rstrip("\n").endswith(GREEN_ARGS) and "projects/example |" not in s["msg"], s["msg"])
s = scenario("report-to-set-red", merge="fail", after="open", report_to=REPORTS)
check("report_to: a failed release reports to the configured page too, once", s["rc"] != 0 and len(s["msgs"]) == 1 and s["msgs"][0].startswith(f"message | {REPORTS} | ") and "projects/example |" not in s["msg"], (s["rc"], s["msg"]))
s = scenario("report-to-unset", merge="ok")
check("report_to: unset (the config gives nothing), the report goes to the stand-in page", len(s["msgs"]) == 1 and s["msgs"][0].startswith("message | projects/example | [release] PR #23"), s["msg"])
for nm, kw, want in (("unset", {}, "projects/example"), ("set", {"report_to": REPORTS}, REPORTS)):
    s = scenario(f"start-{nm}", front=True, units="", **kw)
    check(f"report_to ({nm}): the line printed when a release starts names the page the report will go to", s["rc"] == 0 and f"and reports to {want} · log " in s["out"] and (nm == "set") == (want != "projects/example") and (nm != "set" or "projects/example ·" not in s["out"]), s["out"])
    s = scenario(f"start-group-{nm}", raw=["--group", "23", "24"], units="", **kw)
    check(f"report_to ({nm}): so does the line printed when a group starts", s["rc"] == 0 and f"and reports to {want} · log " in s["out"] and (nm != "set" or "projects/example ·" not in s["out"]), s["out"])

wf = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text()
check("the step names main_green reads are tests.yml's own", all(f"- name: {n}\n" in wf for n in ("run every suite, measured", "audit the selection")))

long = [f"{n} ({k})" for n, k in POLLS if k > MAX_POLLS]
check(f"no scenario polls more than {MAX_POLLS} times (one that waits main's run out to the 3 h cap: pass RELEASE_CAP_MAIN, as most do)", not long, long)

finish()
