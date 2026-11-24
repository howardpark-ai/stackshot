"""Scenario test for release.sh --run: the enqueue in GitHub's merge queue, the wait for GitHub's merge, and the deploy of what it merged.
No network, no real gh, git or deploy: release.sh is copied into a temp dir beside stub config.py, client.py and deploy.sh,
and gh, git and sleep are stubs on a fake PATH (tests/_release_harness.py).

The enqueue and the wait (sections 1 to 9): a clean enqueue (the GraphQL mutation enqueuePullRequest with expectedHeadOid = the head, pinned, no fd 9, chosen because repository.mergeQueue(branch:"main") shows a queue; a plain `gh pr merge` there would ask for auto-merge, which the repository does not allow) is followed by reads of the PR's merge-queue
state (GraphQL: state, mergeCommit, mergeQueueEntry) every 60 s until it is MERGED, and the release deploys the commit GitHub made. The first reads come every 10 s until the entry shows (3 min of grace), a read
that fails is waited out, a PR that never shows or stays past the limit fails "merge queue", a PR closed meanwhile fails "pr state", with no queue on main (the ruleset is
off, the rollback case) the plain `gh pr merge --merge --admin --match-head-commit <head>` is the call, and the deploy waits for main's tests, since no merge_group run tested that merge. A PR that leaves the queue without merging is believed on the second read, the reason GitHub gave (the timeline's RemovedFromMergeQueueEvent)
goes into the failure, and nothing is deployed. A merge call that errors (a 504) after the PR was queued or merged carries on; one that leaves the PR plainly open fails "merge" with the call's error.
A conflict that is only the generated tool-text snapshot is mended once, before the enqueue or after a removal from the queue (the stub of tools/snapshot_regen.py answers; its own decisions are
tested in snapshot_regen_scenario.py), the PR's tests are waited for on the new head, and the PR is enqueued again. The head branch (a stacked PR closed when its base merged): the open PRs
based on it are retargeted to main first and only then is the branch deleted. --recycle, mergeable UNKNOWN (read again every 10 s for 3 min), CONFLICTING, the front door and --help.

The deploy lock: the deploy runs under an exclusive flock (the deploy stub sees it held, fd 9 closed in it, free again at the end); a lock held elsewhere is waited for, or, past the timeout, fails
"deploy lock" with the PR merged and not deployed; the waits for GitHub are outside the lock; two releases sharing one lock file never deploy at the same time.

Main's tests (section 11): when the deploy gate is closed, the run on main that covers the merge is waited for, polled every 20 s here, and the deploy goes to the commit that run passed on (DEPLOY_TO);
its suites failing stops the release merged and not deployed; a selection miss alone deploys and reports to the keeper; a run cancelled is skipped and a later run on a commit that contains the merge covers it; no run in
time fails; the lock is let go for the wait. deploy.sh's pin (section 12), on a real throwaway checkout: DEPLOY_TO fast-forwards to that commit and no further, an unknown one or one off origin/main is refused, a run
by hand goes to origin/main's tip, a fetch that fails is tried again.

The deploy gate (sections 13 to 13c): GitHub tested the merge on the tree it made, so it deploys at once, with main's full run read after the deploy and a rollback to the last good commit on a failure, when
(a) the live checkout is an ancestor of the merge, (b) a last-good commit is recorded and in the live history, (c) no commit after it has a failed run on main (read page after page until the last-good commit's run). A run that is still
pending is no reason to wait. Anything else closes the gate: main's tests first (section 11). The live checkout already containing the merge is a no-op deploy that still reports. The last-good record is read, compared and written under
a lock file; one it cannot read is never overwritten (told, gate closed). A rollback takes out every other merge between the last good commit and the live checkout: each PR gets its own message and a marker, and its
own run says "passed, but not live"; the report says a rollback does not undo data or state. A deploy that replaces release.sh under the running script is read from nothing it appends. The pending-verify record
(written before deploy.sh, read by the next release to start after a kill) and the fourth review's cases: none is a verdict until the cap (3 h), a recovery rollback that never ran keeps its record, startup_failure counts as failed,
no command that can leave a child behind holds a lock descriptor.

The session pick (section 16) and the report's destination (report_to).

The Codex review trial (section 18): for a PR still open, `salamander codex-review <repo> <pr>` is started in a user unit of its own (detached with setsid when systemd-run fails) before the wait for the checks and never waited for, with the SALA_ variables set in the release's environment passed on; a merged or closed PR, a dry run, salamander missing or the review switched off (SALA_CODEX_REVIEW off, false, no or 0 in any case, [release] codex_review) start none, and a review that fails or hangs changes neither the release's result nor its duration; a systemd-run call that times out (it may have started the unit) gets the detached start as well; the caller's own SALA_CODEX_*, SALA_CONFIG and XDG_STATE_HOME never reach a scenario.

    tests/run-suite release        → exit 0 / 1  (the release queue and the CI-run poller are release_queue_scenario.py: tests/run-suite release_queue)"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
from _release_harness import *
check("release.sh parses", subprocess.run(["bash", "-n", os.path.join(STACK, "release.sh")]).returncode == 0)
# a measured run sets COVERAGE_PROCESS_START for this process; what release.sh and its stubs start must not inherit it (every Python start would load coverage: a measured run took three times a plain one)
import _release_harness as _h
_dump = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-envdump-")) / "env"
_held = {k: os.environ.get(k) for k in ("COVERAGE_PROCESS_START", "COVERAGE_FILE")}; _env0 = _h.ENV0
try:   # a plain run has no coverage variable: set two in this process, take ENV0 again as the import does, and run one scenario (what its gh stub is started in) and the git environment the same way
    os.environ["COVERAGE_PROCESS_START"] = "/nonexistent/rc"; os.environ["COVERAGE_FILE"] = "/nonexistent/data"
    _h.ENV0 = _h._env0()
    scenario("envdump", merge="ok", gq="queued,queued,merged", envdump=str(_dump))
    _stub_env = _dump.read_text() if _dump.exists() else ""
    _git_env = subprocess.run(["env"], env=_h._genv(), capture_output=True, text=True).stdout
finally:
    _h.ENV0 = _env0
    for k, v in _held.items(): os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
check("harness: release.sh's stubs (scenario()) and the git calls (genv) are started without the COVERAGE_ variables of a measured run, and keep the rest",
      "RT_DIR=" in _stub_env and "COVERAGE_" not in _stub_env and "GIT_AUTHOR_NAME=t" in _git_env and "COVERAGE_" not in _git_env
      and _h.without_coverage({"COVERAGE_PROCESS_START": "x", "COVERAGE_FILE": "y", "PATH": "p"}) == {"PATH": "p"}, ([l.split("=")[0] for l in _stub_env.splitlines() if l.startswith("COVERAGE_")], [l.split("=")[0] for l in _git_env.splitlines() if l.startswith("COVERAGE_")], "RT_DIR=" in _stub_env, "GIT_AUTHOR_NAME=t" in _git_env))
# the caller's own SALA_CODEX_*, SALA_CONFIG and XDG_STATE_HOME (a shell with the review switched off, say) must not reach a scenario: ENV0 leaves them out, and a scenario that sets one itself (extra=) still gets its own value
_callers = {"SALA_CODEX_REVIEW": "off", "SALA_CODEX_BIN": "from-shell-codex", "SALA_CONFIG": "/nonexistent/from-shell-salamander.cfg", "XDG_STATE_HOME": "/nonexistent/from-shell-state"}
_held2 = {k: os.environ.get(k) for k in _callers}
try:
    os.environ.update(_callers)
    _h.ENV0 = _h._env0()
    _callenv = scenario("shell-env", merge="ok", checks="pending,pass")
    _callenv_x = scenario("shell-env-extra", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": "on", "SALA_CONFIG": "/example/own.cfg", "XDG_STATE_HOME": "/example/own-state"})
    _callenv_keys = set(_h.ENV0) & set(_callers)
    _callenv_other = {k for k in os.environ if k not in ("SALA_CONFIG", "XDG_STATE_HOME") and not k.startswith(("SALA_CODEX_", "COVERAGE_"))} - set(_h.ENV0)   # what the caller has that ENV0 lost, apart from those
finally:
    _h.ENV0 = _env0
    for k, v in _held2.items(): os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
check("harness: ENV0 leaves out SALA_CONFIG, XDG_STATE_HOME and every SALA_CODEX_* variable of the caller, and keeps the rest of its environment",
      not _callenv_keys and not _callenv_other and "PATH" in _h._env0() and _h.without_caller_sala({"SALA_CODEX_X": "1", "SALA_OTHER": "2", "XDG_CONFIG_HOME": "c", "XDG_STATE_HOME": "s", "SALA_CONFIG": "f"}) == {"SALA_OTHER": "2", "XDG_CONFIG_HOME": "c"},
      (_callenv_keys, _callenv_other))
check("a caller with SALA_CODEX_REVIEW=off, SALA_CODEX_BIN, SALA_CONFIG and XDG_STATE_HOME set still gets the review started with none of them (the scenario decides)",
      _callenv["rc"] == 0 and _callenv["codex"] == ["codex-review example-owner/stackshot 23"] and len(_callenv["sysrun"]) == 1 and "SALA_" not in _callenv["sysrun"][0] and "/nonexistent/" not in _callenv["sysrun"][0]
      and not any("from-shell" in l for l in _callenv["codex_env"]) and "not started" not in _callenv["log"], (_callenv["rc"], _callenv["codex"], _callenv["sysrun"], _callenv["codex_env"], _callenv["log"]))
check("...and a scenario's own `extra` values win over the caller's: they are what the unit is handed",
      _callenv_x["codex"] == ["codex-review example-owner/stackshot 23"] and all(f" --setenv={kv} " in _callenv_x["sysrun"][0] for kv in ("SALA_CODEX_REVIEW=on", "SALA_CONFIG=/example/own.cfg", "XDG_STATE_HOME=/example/own-state"))
      and "from-shell" not in _callenv_x["sysrun"][0], (_callenv_x["sysrun"], _callenv_x["codex_env"]))
R = "example-owner/stackshot"
ENQUEUE = f"id=PRNODE23 h={HEADSHA}"   # the enqueue mutation the stub saw: the PR's node id and the head it is pinned to
MERGE_SHORT = "0106c0d"
def gl(s): return s["gh"].splitlines()
def at_gh(s, line): return gl(s).index(line) if line in gl(s) else -1
def at_has(s, frag): return next((i for i, l in enumerate(gl(s)) if frag in l), -1)   # the first gh call whose line holds the text

# ---- 1. a clean run through the merge queue: enqueue, two reads of the queue, the merge, the deploy and the green report
s = scenario("clean", merge="ok", gq="queued,queued,merged")
check("clean: exits 0 and deploys", s["rc"] == 0 and s["deployed"], s["out"])
check("clean: one enqueue call, pinned to the head it read, with no --delete-branch and no --auto", enqueues(s) == [ENQUEUE] and "--delete-branch" not in s["gh"] and "--auto" not in s["gh"], s["gh"])
check("clean: three reads of the queue's state, two sleeps of 60 s between them", s["gq_reads"] == 3 and s["sleeps"] == ["60", "60"], (s["gq_reads"], s["sleeps"]))
check("clean: the log says it enqueued, where the PR stands in the queue, that the queue merged it and when",
      at(s["log"], "checks pass", "enqueued: the merge queue accepted the head abc1234", "in the merge queue (QUEUED position 1)", "merged by the merge queue as 0106c0d, 2 min after the enqueue", "deploy lock taken"), s["log"])
check("clean: the green report, no word about an error or a missing queue", "merged and deployed" in s["msg"] and "errored" not in s["msg"] and "without the merge queue" not in s["msg"] and "main at 0106c0d" in s["msg"], s["msg"])
check("clean: main's tests are read before the deploy (the gate is closed here: nothing recorded as good, so main's run first), then the report",
      s["order"][:3] == ["run-view", f"deploy:{MERGE}", "client:message"], s["order"])
check("clean: the state reads are GraphQL calls, one per cycle, carrying the PR number", s["gq_args"] and all("graphql" in a and "p=23" in a.replace("-F ", "") for a in s["gq_args"]), s["gq_args"])
check("clean: the green report goes with --release green and the PR's URL (the server logs it, rules it, digests it)",
      s["msg"].startswith("message | projects/example | [release] PR #23 merged and deployed") and s["msg"].rstrip("\n").endswith(GREEN_ARGS), s["msg"])
RELEASED_ARGS = "released | --pr | https://github.com/example-owner/stackshot/pull/23 | --sha | "
check("clean (main's tests first): once it is live the server is asked to settle the PR's items, once, after the green report, naming the merge",
      len(s["released"]) == 1 and s["released"][0] == RELEASED_ARGS + MERGE
      and "items of PR #23: closed a1" in s["log"] and s["log"].index("done: ") < s["log"].index("items of PR #23"), (s["released"], s["log"]))
check("clean: no branch call besides the one lookup (the branch is already gone)", len(refchecks(s)) == 1 and not deletes(s), s["gh"])
s = scenario("clean-released-fails", merge="ok", released="fail")
check("the items call fails: a log line, the release still exits 0 with its green report", s["rc"] == 0 and "the items of PR #23 were not settled: closed a1" in s["log"]
      and s["msg"].rstrip("\n").endswith(GREEN_ARGS), (s["rc"], s["log"]))

# ---- 1b. merged at once, without the queue (the ruleset is off: the rollback path of the queue, or a repository without it)
s = scenario("noqueue", merge="ok", gq="merged", mq="off")
check("merged at the plain merge call with no queue on the branch: deploys, and says so in the log and in the report",
      s["rc"] == 0 and s["deployed"] and not s["sleeps"] and "merged as 0106c0d by the plain merge call, not the merge queue" in s["log"] and "merged without the merge queue (the ruleset is off)" in s["msg"], (s["out"], s["log"], s["msg"]))
s = scenario("merged-nocommit", merge="ok", gq="queued,mergednocommit,merged")
check("GitHub says merged but has no merge commit to give yet: read again, the deploy goes to the commit it then gives",
      s["rc"] == 0 and s["deployed"] and "has no merge commit to give yet; reading again" in s["log"] and s["deploy_to"] == MERGE, (s["log"], s["deploy_to"]))
s = scenario("merge-oid", merge="ok", gq="queued,merged", merge_oid=NEWER, runs=json.dumps([{"databaseId": 7, "headSha": NEWER}]))
check("the deploy and main's run are about the commit GitHub made, whatever it is", s["rc"] == 0 and s["deploy_to"] == NEWER and "merged by the merge queue as 0107c0d" in s["log"], (s["log"], s["deploy_to"]))

# ---- 2. the enqueue call errors (a 504) after the PR was queued or merged: carry on; the PR still plainly open: fail "merge"
s = scenario("recovered-queued", merge="fail", gq="queued,merged", branch="present")
check("504, the PR reads queued on the next read: carries on, deploys and reports green, the report naming the error",
      s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "the enqueue call errored (HTTP 504: We couldn't respond to your request in time.) but the PR was OPEN, in the merge queue (QUEUED position 1)" in s["msg"]
      and "FAILED" not in s["msg"], (s["out"], s["msg"]))
check("504: the log says the call errored and the PR is in the queue; the head branch still there is deleted",
      "the enqueue call errored: HTTP 504" in s["log"] and "carrying on" in s["log"] and deletes(s) == [f"api -X DELETE repos/{R}/git/refs/heads/agent/topic"] and "deleted the head branch agent/topic" in s["log"], (s["log"], s["gh"]))
s = scenario("recovered-merged", merge="fail", gq="merged")
check("504, the PR reads MERGED already: carries on, deploys, the report names the error", s["rc"] == 0 and s["deployed"] and "the enqueue call errored" in s["msg"] and "but the PR was MERGED" in s["msg"], (s["out"], s["msg"]))
s = scenario("recovered-late", merge="fail", gq="open,open,queued,merged")
check("504, the PR shows in the queue on the third read (GitHub's answer is eventually consistent): two sleeps of 10 s, then it carries on",
      s["rc"] == 0 and s["deployed"] and s["sleeps"][:2] == ["10", "10"], (s["sleeps"], s["out"]))
s = scenario("open", merge="fail", gq="open", branch="present")
check("504 and the PR stays plainly open: exits 1, never deploys", s["rc"] == 1 and not s["deployed"], s["out"])
check("504 and open: FAILED at merge with the original error's last line, no deploy report",
      "PR #23 FAILED at merge: HTTP 504: We couldn't respond to your request in time." in s["msg"] and "merged and deployed" not in s["msg"], s["msg"])
check("504 and open: six reads over five 10 s sleeps (about 50 s), one enqueue call", s["gq_reads"] == 6 and s["sleeps"] == ["10"] * 5 and len(enqueues(s)) == 1, (s["gq_reads"], s["sleeps"]))
check("504 and open: the branch is left alone, the red report goes without --release", not refchecks(s) and not deletes(s) and s["msg"].rstrip("\n").endswith("| --sender | release") and "--release" not in s["msg"], (s["gh"], s["msg"]))

# ---- 3. MERGED, but the branch deletion fails: still green; the branch already gone; a cross-repository PR
s = scenario("delfail", merge="ok", branch="present", delete="fail")
check("deletion fails: still exits 0, deploys and reports green, the log says the branch is still there",
      s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "the head branch agent/topic is still there" in s["log"], (s["out"], s["log"]))
s = scenario("gone", merge="ok", branch="absent")
check("branch gone: green, the ref looked up once, no delete", s["rc"] == 0 and "merged and deployed" in s["msg"] and len(refchecks(s)) == 1 and not deletes(s), (s["gh"], s["msg"]))
s = scenario("cross", merge="ok", branch="present", cross="1")
check("cross-repository: green, no branch call at all", s["rc"] == 0 and "merged and deployed" in s["msg"] and not refchecks(s) and not deletes(s), (s["gh"], s["msg"]))

# ---- 3b. stacked PRs (GitHub closes a stacked PR when its base merges and the base branch is deleted): they are retargeted to main BEFORE the branch is deleted
LIST = f"pr list --repo {R} --base agent/topic --state open --limit 100 --json number"; DEL = f"api -X DELETE repos/{R}/git/refs/heads/agent/topic"
E_a, E_b = f"pr edit 32 --repo {R} --base main", f"pr edit 28 --repo {R} --base main"
s = scenario("stacked", merge="ok", gq="queued,merged", stacked="32,28", branch="present")
check("stacked: exits 0, deploys, reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"], (s["out"], s["msg"]))
check("stacked: both PRs are retargeted to main, after the enqueue and BEFORE the branch delete (order asserted)", 0 <= at_has(s, "enqueuePullRequest") < at_gh(s, LIST) < at_gh(s, E_a) < at_gh(s, E_b) < at_gh(s, DEL), s["gh"])
check("stacked: one log line per PR, then the deletion", "PR #32 was based on agent/topic: retargeted to main" in s["log"] and "PR #28 was based on agent/topic: retargeted to main" in s["log"]
      and "deleted the head branch agent/topic" in s["log"] and s["log"].index("PR #28 was based") < s["log"].index("deleted the head branch"), s["log"])
check("stacked: exactly one delete", deletes(s) == [DEL], s["gh"])
s = scenario("stacked-recovered", merge="fail", gq="queued,merged", stacked="32", branch="present")
check("stacked, the merge call errored but the PR was queued: the same order (retarget, then delete)", s["rc"] == 0 and s["deployed"] and 0 <= at_gh(s, LIST) < at_gh(s, E_a) < at_gh(s, DEL), (s["out"], s["gh"]))
s = scenario("unstacked", merge="ok", branch="present")
check("no stacked PR: green, the list is asked once, no retarget, the branch is deleted", s["rc"] == 0 and s["deployed"] and gl(s).count(LIST) == 1 and not any(l.startswith("pr edit") for l in gl(s))
      and deletes(s) == [DEL] and at_gh(s, LIST) < at_gh(s, DEL) and "retarget" not in s["log"], (s["gh"], s["log"]))
s = scenario("unstacked-gone", merge="ok", branch="absent")
check("no stacked PR and the branch already gone: no retarget, no delete", s["rc"] == 0 and not any(l.startswith("pr edit") for l in gl(s)) and not deletes(s), s["gh"])
s = scenario("stacked-cross", merge="ok", stacked="32", branch="present", cross="1")
check("cross-repository: no list, no retarget, no delete", s["rc"] == 0 and LIST not in gl(s) and not any(l.startswith("pr edit") for l in gl(s)) and not deletes(s), s["gh"])
s = scenario("retarget-fails", merge="ok", stacked="32,28", branch="present", retarget_fail="32")
check("a failed retarget: the release still deploys and reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "FAILED" not in s["msg"], (s["out"], s["msg"]))
check("a failed retarget: the other PR is still retargeted, the branch is NOT deleted (no lookup, no delete call)", E_b in gl(s) and not deletes(s) and not refchecks(s), s["gh"])
check("a failed retarget: the log says which PR failed and why, and that the branch is kept",
      "PR #32 was based on agent/topic: retargeting it to main failed (GraphQL: Could not resolve to a PullRequest" in s["log"] and "PR #28 was based on agent/topic: retargeted to main" in s["log"]
      and "the head branch agent/topic is kept: deleting it would close the PRs #32 still based on it" in s["log"] and "deleted the head branch" not in s["log"], s["log"])
s = scenario("list-fails", merge="ok", list="fail", branch="present")
check("a list that cannot be read: green, no retarget, the branch is kept and the log says why", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and not deletes(s) and not any(l.startswith("pr edit") for l in gl(s))
      and "the head branch agent/topic is kept: the open PRs based on it could not be listed (HTTP 502: bad gateway)" in s["log"], (s["gh"], s["log"]))

# ---- 4. leaving the queue without merging, and the other ways the wait ends badly: nothing is deployed, the failure names the reason
s = scenario("removed", merge="ok", gq="queued,open,open", gq_reason="The merge group failed its required checks: suites (shard 2/4)", branch="present")
check("removed from the queue: exits 1, FAILED at merge queue with GitHub's reason, nothing deployed, the branch left alone",
      s["rc"] == 1 and not s["deployed"] and "PR #23 FAILED at merge queue: removed from the merge queue: The merge group failed its required checks: suites (shard 2/4)" in s["msg"]
      and not refchecks(s) and not deletes(s) and "merged and deployed" not in s["msg"], (s["msg"], s["out"]))
check("removed: believed on the second read (10 s after the first) and three more reads of the PR for MERGED, 10 s apart, the reason read once, the red report goes without --release", s["sleeps"] == ["60", "10", "10", "10", "10"] and s["gq_reads"] == 6 and s["gq_reason_reads"] == 1
      and "--release" not in s["msg"] and "removed from the merge queue: The merge group" in s["log"], (s["sleeps"], s["gq_reads"], s["gq_reason_reads"]))
s = scenario("removed-flap", merge="ok", gq="queued,open,merged")
check("the entry vanishes a moment before the PR shows merged: not a removal, deployed", s["rc"] == 0 and s["deployed"] and "FAILED" not in s["log"] and s["sleeps"] == ["60", "10"], (s["log"], s["sleeps"]))
s = scenario("removed-noreason", merge="ok", gq="queued,open,open", gq_reason="none")
check("removed and the timeline has no event yet: three tries 10 s apart, then FAILED at merge queue saying GitHub gives no reason",
      s["rc"] == 1 and not s["deployed"] and "PR #23 FAILED at merge queue: left the merge queue, and GitHub's timeline gives no reason (no removal event)" in s["msg"] and s["gq_reason_reads"] == 3, (s["msg"], s["gq_reason_reads"]))
s = scenario("removed-reason-late", merge="ok", gq="queued,open,open", gq_reason="fail")
check("the timeline cannot be read: the same, the failure is still the removal", s["rc"] == 1 and "FAILED at merge queue: left the merge queue" in s["msg"] and s["gq_reason_reads"] == 3, (s["msg"], s["gq_reason_reads"]))
s = scenario("removed-words", merge="ok", gq="queued,open,open", gq_reason="the run FAILED and then done: nothing")
check("GitHub's words cannot fake a log waiter's markers (' FAILED ', ' done: ') in the log", s["rc"] == 1 and "removed from the merge queue: the run failed and then done nothing" in s["log"], s["log"])
s = scenario("never-shows", merge="ok", gq="open", gq_reason="none")
check("accepted but never shown in the queue and not merged: read every 10 s for the 3 min of grace, then FAILED at merge queue naming it",
      s["rc"] == 1 and not s["deployed"] and "PR #23 FAILED at merge queue: the PR did not show in the merge queue within 3 min of the enqueue call and is not merged" in s["msg"] and s["sleeps"][:3] == ["10", "10", "10"], (s["msg"], s["sleeps"][:4]))
s = scenario("never-shows-removed", merge="ok", gq="open", gq_reason="the PR conflicts with main")
check("never shown, and the timeline names a removal: that reason", s["rc"] == 1 and "FAILED at merge queue: removed from the merge queue: the PR conflicts with main" in s["msg"], s["msg"])
s = scenario("closed", merge="ok", gq="queued,closed")
check("closed while it waited: FAILED at pr state, nothing deployed", s["rc"] == 1 and not s["deployed"] and "PR #23 FAILED at pr state: the PR was closed while it waited for the merge queue" in s["msg"], s["msg"])
s = scenario("wait-limit", merge="ok", gq="queued", extra={"RELEASE_QUEUE_WAIT": "300"})
check("still in the queue at the limit: FAILED at merge queue naming the limit, saying the PR may still merge later and to rerun release.sh 23 (a rerun on the merged PR carries on from the merge); five sleeps of 60 s; nothing deployed",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["60"] * 5 and "PR #23 FAILED at merge queue: still in the merge queue (QUEUED position 1) 5 min after the enqueue, which is as long as this release waits; the PR may still merge later: rerun release.sh 23 to carry on from the merge" in s["msg"], (s["msg"], s["sleeps"]))
s = scenario("wait-limit-default", merge="ok", gq="queued", extra={"RELEASE_QUEUE_WAIT": "10800", "RELEASE_POLL_QUEUE": "3600"})
check("the 3 h limit itself (the default RELEASE_QUEUE_WAIT, read every hour here to keep the run short): FAILED at merge queue after 180 min, the text says to rerun release.sh 23, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and "180 min after the enqueue" in s["msg"] and "rerun release.sh 23" in s["msg"], (s["msg"], s["sleeps"]))
s = scenario("wait-default", merge="ok", gq="queued,merged")
check("the default limit is 3 h and the default read every 60 s (the log line names both)", "up to 180 min; reading it every 60 s" in s["log"], s["log"])
s = scenario("unreadable", merge="ok", gq="fail,fail,queued,merged")
check("GitHub's answer cannot be read twice: waited out like a pending one, at the slow poll (60 s) from the first unreadable read on (a 403/429 is a wait, not a reason to ask again in 10 s), then the wait goes on; one log line, not one per read",
      s["rc"] == 0 and s["deployed"] and s["sleeps"][:2] == ["60", "60"] and s["log"].count("could not be read") == 1, (s["sleeps"], s["log"]))
s = scenario("unreadable-backoff", merge="ok", gq="queued,fail,queued,merged")
check("an entry seen in the queue, then an unreadable answer: the poll stays at 60 s (never back to 10 s); the whole wait is 60 s sleeps", s["rc"] == 0 and s["deployed"] and set(s["sleeps"][:3]) == {"60"}, (s["sleeps"], s["log"]))
s = scenario("unreadable-first", merge="ok", gq="fail,queued,merged")
check("an unreadable first answer (before the entry shows): the next read is 60 s later, not 10 s", s["rc"] == 0 and s["deployed"] and s["sleeps"][:1] == ["60"], (s["sleeps"], s["log"]))
s = scenario("garbage", merge="ok", gq="garbage,merged")
check("an answer that is not JSON counts as unreadable (waited out at the slow poll)", s["rc"] == 0 and s["deployed"] and s["sleeps"][:1] == ["60"], (s["sleeps"], s["out"]))
s = scenario("unreadable-forever", merge="ok", gq="fail", extra={"RELEASE_QUEUE_WAIT": "120"})
check("never readable: FAILED at merge queue after the limit, not a hang", s["rc"] == 1 and "FAILED at merge queue: still not merged 2 min after the enqueue" in s["msg"], (s["msg"], s["sleeps"]))

# ---- 5. a conflict that is only the generated tool-text snapshot: mended once (before the enqueue, or after a removal for a conflict), the PR's tests waited for on the new head, enqueued again
rg = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-regenstub-")); dirs.append(rg)
REGEN_STUB = rg / "snapshot_regen.py"
REGEN_STUB.write_text('''import os, sys
d = os.environ["RT_DIR"]
open(d + "/regen.log", "a").write(" ".join(sys.argv[1:]) + "\\n")
print("snapshot_regen: stub details on stderr", file=sys.stderr)
print(os.environ.get("RT_REGEN", "declined: no answer"))
sys.exit(0 if os.environ.get("RT_REGEN", "").startswith("pushed ") else 1)
''')
RGX = {"RELEASE_SNAPSHOT_REGEN": str(REGEN_STUB)}
def regen_calls(s): return (s["dir"] / "regen.log").read_text().splitlines() if (s["dir"] / "regen.log").exists() else []
ENQ_H1 = f"id=PRNODE23 h={H1}"
# the first look says CONFLICTING: the helper is asked, GitHub is read again (every 10 s) until the head moved and it has recomputed, the PR's tests on the new head are waited for, then it is enqueued
s = scenario("regen-first", merge="ok", mergeable="CONFLICTING,UNKNOWN,MERGEABLE", prheads=f"{HEADSHA},{H1},{H1}", regen=f"pushed {H1}", checks="pass,pending,pass", extra=RGX)
check("CONFLICTING at the first look and the helper pushes a merge: the helper ran once with the repo, the PR's branch and the head it was given, then the PR's tests on the new head, then the enqueue on the new head",
      s["rc"] == 0 and s["deployed"] and regen_calls(s) == [f"--repo {s['dir']}/box --branch=agent/topic --head {HEADSHA}"] and enqueues(s) == [ENQ_H1] and "FAILED" not in s["log"] and not red(s)
      and at(s["log"], "the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 1)",
             f"the only conflicted path was tests/tool_text.snapshot.json: took main's, regenerated it (tool_text.py update, check passed), and pushed the merge {H1} to agent/topic",
             "mergeable: after the snapshot regeneration GitHub says MERGEABLE (head d00d100)", "the PR's tests pass on the pushed head d00d100", "enqueued: the merge queue accepted the head d00d100"), (s["rc"], regen_calls(s), s["log"], s["gh"]))
check("the regeneration costs no GitHub call of its own: only pr, api and run calls, no update-branch", all(l.split()[0] in ("pr", "api", "run") for l in gl(s)) and "update-branch" not in s["gh"] and "snapshot" not in s["gh"], s["gh"])
check("the helper's details (its stderr) reach the log", "snapshot_regen: stub details on stderr" in s["log"], s["log"])
s = scenario("regen-first-quiet", merge="ok", mergeable="CONFLICTING,UNKNOWN,MERGEABLE", prheads=f"{HEADSHA},{H1},{H1}", regen=f"pushed {H1}", checks="lint,lint,pass", extra=RGX)
check("a quick check alone (lint) is not a pass on the regenerated head: waits until the tests job passed, then enqueues", s["rc"] == 0 and s["deployed"] and enqueues(s) == [ENQ_H1] and s["gh"].count("pr checks") >= 3, (s["rc"], s["log"]))
s = scenario("regen-first-still", merge="ok", mergeable="CONFLICTING", prheads=f"{HEADSHA},{H1}", regen=f"pushed {H1}", extra=RGX)
check("pushed, but GitHub still says CONFLICTING after the time it is given: FAILED at mergeable, nothing enqueued", s["rc"] == 1 and not enqueues(s) and "FAILED at mergeable: GitHub says CONFLICTING" in s["log"], (s["rc"], s["log"]))
s = scenario("regen-declined", merge="ok", mergeable="CONFLICTING", regen="declined: the conflict is not only the snapshot: src/server.py", extra=RGX)
check("CONFLICTING and the helper declines: the failure is the one of a conflict without the helper (same words, red report, nothing enqueued), the helper's reason in the log",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub says CONFLICTING: the PR has a conflict with main" in s["msg"] and not enqueues(s) and len(regen_calls(s)) == 1
      and "the snapshot is not regenerated: declined: the conflict is not only the snapshot: src/server.py" in s["log"] and s["sleeps"] == [], (s["rc"], s["log"]))
s = scenario("regen-nohelper", merge="ok", mergeable="CONFLICTING")
check("CONFLICTING and no helper file (a checkout from before it): the same failure, the log says so", s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and "snapshot_regen.py is missing" in s["log"], (s["rc"], s["log"]))
s = scenario("regen-cross", merge="ok", mergeable="CONFLICTING", cross="1", regen=f"pushed {H1}", extra=RGX)
check("a cross-repository PR is never pushed to: the helper is not run, the failure is the old one", s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and not regen_calls(s) and "cross-repository True" in s["log"], (s["rc"], s["log"]))
s = scenario("regen-nofetch", merge="ok", mergeable="CONFLICTING", prfetch_fail="1", regen=f"pushed {H1}", extra=RGX)
check("the fetch of main and the PR head fails: the helper is not run, the failure is the old one", s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and not regen_calls(s) and "cannot fetch main and the PR head from origin" in s["log"], (s["rc"], s["log"]))
# removed from the queue for a conflict that is only the snapshot (main moved while the PR waited): mended, tests on the new head, enqueued again, and merged by the second round
s = scenario("regen-removed", merge="ok", gq="queued,open,open,open,open,open,queued,merged", gq_reason="merge_conflict", mergeable="MERGEABLE,CONFLICTING,MERGEABLE", prheads=f"{HEADSHA},{HEADSHA},{H1}",
             regen=f"pushed {H1}", checks="pass,pass,pending,pass", extra=RGX)
check("removed from the queue and the PR now conflicts only on the snapshot: mended, the PR's tests waited for on the new head, enqueued again on that head, merged, deployed",
      s["rc"] == 0 and s["deployed"] and enqueues(s) == [ENQUEUE, ENQ_H1] and s["mq_reads"] == 2 and len(regen_calls(s)) == 1 and "FAILED" not in s["log"] and not red(s)
      and at(s["log"], "removed from the merge queue: a merge conflict with main", "the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration 1 of 1)",
             "the PR's tests pass on the regenerated head d00d100", "enqueueing the PR again on the regenerated head d00d100", "enqueued: the merge queue accepted the head d00d100", "merged by the merge queue as 0106c0d"), (s["rc"], s["log"], enqueues(s)))
s = scenario("regen-removed-declined", merge="ok", gq="queued,open,open", gq_reason="a merge conflict with main", mergeable="MERGEABLE,CONFLICTING", regen="declined: the conflict is not only the snapshot: src/server.py", extra=RGX)
check("removed for a conflict the helper declines: FAILED at merge queue with GitHub's reason and the conflict, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge queue: removed from the merge queue: a merge conflict with main; GitHub says CONFLICTING: the PR has a conflict with main" in s["msg"] and len(enqueues(s)) == 1, (s["msg"], s["log"]))
s = scenario("regen-removed-bound", merge="ok", gq="queued,open,open,queued,open,open", gq_reason="a merge conflict with main", mergeable="MERGEABLE,CONFLICTING,MERGEABLE,CONFLICTING",
             prheads=f"{HEADSHA},{HEADSHA},{H1},{H1}", regen=f"pushed {H1}", extra=RGX)
check("removed for a conflict a second time: the helper is not asked again (once per release), FAILED at merge queue naming the bound",
      s["rc"] == 1 and len(regen_calls(s)) == 1 and len(enqueues(s)) == 2 and "was regenerated 1 time(s) in this release already (RELEASE_REGEN_MAX=1); not again" in s["log"] and "FAILED at merge queue" in s["msg"], (s["rc"], s["log"]))
s = scenario("regen-removed-checks-fail", merge="ok", gq="queued,open,open", gq_reason="a merge conflict with main", mergeable="MERGEABLE,CONFLICTING,MERGEABLE", prheads=f"{HEADSHA},{HEADSHA},{H1}",
             regen=f"pushed {H1}", checks="pass,fail", extra=RGX)
check("the PR's tests fail on the regenerated head: FAILED at pr tests, no second enqueue", s["rc"] == 1 and "FAILED at pr tests: a check failed: suites=fail" in s["msg"] and len(enqueues(s)) == 1, (s["rc"], s["msg"]))
s = scenario("regen-removed-nothing", merge="ok", gq="queued,open,open", gq_reason="the merge group failed its checks", mergeable="MERGEABLE", extra=RGX, regen=f"pushed {H1}")
check("removed for a failed check and the PR is mergeable: the helper is not asked, FAILED at merge queue with the reason", s["rc"] == 1 and not regen_calls(s) and "FAILED at merge queue: removed from the merge queue: the merge group failed its checks" in s["msg"], (s["rc"], s["msg"]))
s = scenario("regen-removed-closed", merge="ok", gq="queued,open,open", gq_reason="closed", viewstate="OPEN,CLOSED")
check("removed and the PR was closed meanwhile: FAILED at pr state naming the reason", s["rc"] == 1 and "FAILED at pr state: removed from the merge queue: closed; the PR is CLOSED" in s["msg"], s["msg"])

# ---- 6. --recycle: a green release whose recycle is marked stays green; one whose recycle could not be asked for is delivered
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

# ---- 7. every enqueue is pinned to the head commit that was read, and the lock does not reach gh
for nm, args, kw in (("pin-normal", (), {}), ("pin-recycle", ("--recycle",), {}), ("pin-other-head", (), {"head": "0123456789abcdef0123456789abcdef01234567"})):
    s = scenario(nm, args=args, merge="ok", **kw)
    want = kw.get("head", HEADSHA)
    check(f"{nm}: the enqueue mutation is pinned to the head it read (expectedHeadOid {want[:7]}) and to the PR's node id", s["rc"] == 0 and enqueues(s) == [f"id=PRNODE23 h={want}"] and not plain_merges(s) and not s["wrong_calls"], (s["gh"], s["enqueue_args"]))
    check(f"{nm}: the enqueue call gets no fd 9", s["merge_fd9"] == "closed", s["merge_fd9"])
s = scenario("pin-moved", merge="fail", gq="open")
check("the head moved after the read (the pinned enqueue is refused): never deploys, FAILED at merge", s["rc"] == 1 and not s["deployed"] and "FAILED at merge" in s["msg"], s["msg"])
s = scenario("lock-closed-after-deploy", args=("--recycle",), merge="ok", recycle_due="fail", idle="sala recycle --when-idle")
check("lock: no child after the deploy (recycle, idle recycle, report) inherits fd 9", s["rc"] == 0 and s["client_fd9"] and set(s["client_fd9"]) == {"closed"}, s["client_fd9"])
s = scenario("lock-closed-deploy-fails", merge="ok", deploy_fail="1")
check("lock: a failed deploy releases the lock before the failure report", s["rc"] == 1 and "FAILED at deploy" in s["msg"] and s["client_fd9"] == ["closed"], (s["msg"], s["client_fd9"]))

# ---- 8. mergeable UNKNOWN (GitHub recomputes after main moves): read again every 10 s for up to 3 min
s = scenario("mergeable-unknown-then-ok", merge="ok", mergeable="UNKNOWN,UNKNOWN,MERGEABLE")
check("mergeable UNKNOWN then MERGEABLE: goes on, enqueues and deploys, reports green", s["rc"] == 0 and s["deployed"] and "merged and deployed" in s["msg"] and "FAILED" not in s["msg"], (s["out"], s["msg"]))
check("mergeable UNKNOWN then MERGEABLE: one line says it waits, three reads, two 10 s sleeps",
      s["log"].count("mergeable UNKNOWN") == 1 and "every 10 s for up to 3 min" in s["log"] and s["gh"].count("state,mergeable") == 3 and s["sleeps"][:2] == ["10", "10"], (s["log"], s["sleeps"]))
s = scenario("mergeable-unknown-throughout", merge="ok", mergeable="UNKNOWN")
check("mergeable UNKNOWN throughout: exits 1, FAILED at mergeable naming UNKNOWN and the time, nothing enqueued, nothing deployed",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub still says UNKNOWN after 3 min" in s["msg"] and not enqueues(s) and not s["deployed"], (s["msg"], s["out"]))
check("mergeable UNKNOWN throughout: 19 reads over 18 sleeps of 10 s (3 min), the wait logged once", s["gh"].count("state,mergeable") == 19 and s["sleeps"] == ["10"] * 18 and s["log"].count("mergeable UNKNOWN") == 1, (s["gh"].count("state,mergeable"), s["sleeps"]))
s = scenario("mergeable-conflicting", merge="ok", mergeable="CONFLICTING")
check("mergeable CONFLICTING: fails at once at mergeable naming CONFLICTING, no wait, nothing enqueued",
      s["rc"] == 1 and "PR #23 FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["gh"].count("state,mergeable") == 1 and not s["sleeps"]
      and "mergeable UNKNOWN" not in s["log"] and not enqueues(s) and not s["deployed"], (s["msg"], s["sleeps"]))
s = scenario("mergeable-conflicting-after-unknown", merge="ok", mergeable="UNKNOWN,CONFLICTING")
check("mergeable UNKNOWN then CONFLICTING: fails at mergeable as soon as it reads CONFLICTING", s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["gh"].count("state,mergeable") == 2 and s["sleeps"] == ["10"], (s["msg"], s["sleeps"]))
s = scenario("pr-closed", merge="ok", viewstate="CLOSED")
check("a PR closed before the release starts: FAILED at pr state, nothing enqueued", s["rc"] == 1 and "FAILED at pr state: the PR is CLOSED" in s["msg"] and not enqueues(s), s["msg"])
s = scenario("checks-fail", merge="ok", checks="fail")
check("a failed check: FAILED at checks before any enqueue", s["rc"] == 1 and "FAILED at checks: a check failed: suites=fail" in s["msg"] and not enqueues(s), s["msg"])
s = scenario("checks-pending", merge="ok", checks="pending,pending,pass")
check("checks pending: the enqueue waits for them, polled every 20 s here", s["rc"] == 0 and s["deployed"] and s["sleeps"][:2] == ["20", "20"] and at(s["log"], "checks pass", "enqueued"), (s["sleeps"], s["log"]))

# ---- 9. the front door: --quick is gone (docs-merge.sh covers it), and an unknown option is refused before any gh call
for nm, args in (("front-quick", ("--quick",)), ("front-unknown-option", ("--fast",))):
    s = scenario(nm, args=args, front=True, merge="ok")
    check(f"{nm}: refused with exit 2 and the usage line, nothing called, nothing deployed, no message",
          s["rc"] == 2 and "usage: release.sh <pr> [--recycle | --no-recycle]" in s["out"] and not s["gh"] and not s["deployed"] and not s["msg"], (s["rc"], s["out"], s["gh"]))
RULES = ("Run one plain `release.sh N` per command", "pr-N.log", "` done: ` or ` FAILED `", "run_in_background", "Never chain waiters", "refuses a loop of release.sh",
         "queue them: `release.sh queue N [N...]`", "the merge queue builds it on main's tip")
check("front door: the usage line is followed by the rules for running it (one plain command, wait on the log, no chained waiters, auto mode and loops) and what happens to a branch behind main",
      all(t in s["out"] for t in RULES) and "set -uo pipefail" not in s["out"], s["out"])
home = subprocess.run(["bash", os.path.join(STACK, "release.sh"), "--help"], capture_output=True, text=True)
check("--help: exits 2, starts at the header, carries the same rules and the steps, and stops before the code",
      home.returncode == 2 and home.stdout.startswith("# release.sh") and all(t in home.stdout for t in RULES) and "3a. WAIT FOR THE MERGE" in home.stdout
      and "4b. DEPLOY GATE" in home.stdout and "update.lock" not in home.stdout and "update-branch" not in home.stdout
      and "set -uo pipefail" not in home.stdout and "read_view" not in home.stdout, (home.returncode, home.stdout[:300]))
# ---- 10. the deploy lock
s = scenario("lock-held-by-release", merge="ok")
check("lock: the deploy runs with the lock held by the release, fd 9 closed in it", s["rc"] == 0 and s["lock_during"] == "held" and s["fd9"] == "closed", (s["lock_during"], s["fd9"], s["out"]))
check("lock: taken after the checks pass and after GitHub has merged the PR (the waits for GitHub are outside it)", 0 <= s["log"].index("checks pass") < s["log"].index("merged by the merge queue as") < s["log"].index("deploy lock taken"), s["log"])
lockfile = s["dir"] / "releases/deploy.lock"
check("lock: the file is in the release state dir", lockfile.exists())
if lockfile.exists():
    lk = open(lockfile, "a")
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); freed = True
    except OSError: freed = False
    lk.close(); check("lock: free again after the release", freed)
s = scenario("lock-timeout", merge="ok", hold=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("lock held elsewhere past the timeout: exits 1, FAILED at deploy lock, merged and not deployed, nothing deployed",
      s["rc"] == 1 and "PR #23 FAILED at deploy lock: another deploy held the lock" in s["msg"] and "merged, not deployed" in s["msg"] and len(merges(s)) == 1 and not s["deployed"], (s["msg"], s["out"]))
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
s = scenario("main-late-never", merge="ok", main="late", extra={"RELEASE_WAIT_STEPS": "60"})
check("completed and green (conclusion success) but the step results never come: after RELEASE_WAIT_STEPS (60 s here, three 20 s polls) the run counts as green, never a failure: deploys, exit 0, nothing rolled back",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 3 and "FAILED" not in s["msg"] + s["log"] and "rolling back" not in s["log"], (s["rc"], s["sleeps"], s["msg"], s["log"]))
check("…a WARNING line in the log says the step results never arrived and the run is counted as green, and the report goes to the keeper (not green) saying so",
      "WARNING: main's run 7 on 0106c0d concluded success but GitHub never filled in its step results in 1 min: counted as green (not rolled back)" in s["log"]
      and "counted as green, but finished successfully, but its step results never arrived in 1 min" in s["msg"] and "--release" not in s["msg"], (s["log"], s["msg"]))
s = scenario("main-late-rerun", merge="ok", main="late,late,pending,pending,pending,pending,late,late,pass", extra={"RELEASE_WAIT_STEPS": "60"})
check("the gap is seen, the run goes back to running for longer than RELEASE_WAIT_STEPS (a re-run keeps its run id), then completes with the gap again: a fresh wait starts, it does not fail at once on the old start; the wait line is logged twice",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 8 and s["log"].count("has not filled in its step results yet") == 2 and "never arrived" not in s["out"] + s["log"] and "WARNING" not in s["log"], (s["rc"], s["sleeps"], s["log"]))
s = scenario("main-late-default-cap", merge="ok", main="late", extra={"RELEASE_WAIT_STEPS": ""})
check("the default cap is 10 min: 30 polls of 20 s, then the run counts as green with the step results never arrived in 10 min", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 30 and "never arrived in 10 min" in s["msg"] and "rolling back" not in s["log"], (len(s["sleeps"]), s["msg"]))
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
s = scenario("main-older-run", merge="ok", runs=json.dumps([{"databaseId": 6, "headSha": BASE}]), extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("only a run of an older commit (it does not contain the merge): never read as green for it; no run in time, merged and not deployed, both limits named",
      s["rc"] == 1 and not s["deployed"] and "run view 7" not in s["gh"]
      and "no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 1 min): merged, not deployed" in s["msg"]
      and f"merge-base --is-ancestor {MERGE} {BASE}" in (s["dir"] / "git.log").read_text(), (s["msg"], s["gh"]))
s = scenario("main-none", merge="ok", runs="[]", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("no run on main shows up in time: fails at main's tests, merged and not deployed", s["rc"] == 1 and not s["deployed"]
      and "no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min)" in s["msg"] and "merged, not deployed" in s["msg"] and s["sleeps"] == ["20"] * 3, (s["msg"], s["sleeps"]))
check("no run on main in time: the lock is free after, and the red report got no fd 9", lock_free(s), s["client_fd9"])
s = scenario("main-fetch-race", merge="ok", fetch_fails="2")
check("main's fetch fails twice (racing another release's fetch in the checkout): retried after 2 s each, then deployed",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["2", "2"] and s["deploy_to"] == "0106c0de0106c0de0106c0de0106c0de0106c0de", (s["log"], s["sleeps"]))
s = scenario("main-fetch-down", merge="ok", fetch_fails="999", extra={"RELEASE_WAIT_MAIN": "60"})
check("main cannot be fetched after the merge: three tries over two 2 s sleeps, then FAILED at deploy, merged and not deployed, the lock free",
      s["rc"] == 1 and not s["deployed"] and "FAILED at deploy: the PR is merged as 0106c0d, but main cannot be fetched from origin to deploy it (merged, not deployed; ./deploy.sh by hand)" in s["msg"]
      and s["sleeps"] == ["2", "2"] and lock_free(s), (s["msg"], s["sleeps"]))
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
# stackshot/core/config.py, units/scope.sh, install.sh and curl are stubs, and the commits change only text files, so nothing restarts
def run_alarm(cmd, timeout, **kw):
    """subprocess.run with an alarm of its own: a run that is not over in `timeout` seconds is stopped and answers rc -999 with what it printed, so a wait that does not end is a failed check, never a hung or crashed suite."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw); return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        return -999, "".join(x.decode() if isinstance(x, bytes) else (x or "") for x in (e.stdout, e.stderr)) + f"\n[the run did not end in {timeout} s]"
dp = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-deploy-")); dirs.append(dp)
g("init", "-q", "--bare", "-b", "main", str(dp / "origin.git")); g("clone", "-q", str(dp / "origin.git"), str(dp / "box"))
bx = dp / "box"; cs = []
(bx / "deploy.sh").write_text("#!/bin/sh\n"); g("add", "-A", cwd=bx); g("commit", "-qm", "c0", cwd=bx); c0 = g("rev-parse", "HEAD", cwd=bx)   # a deploy.sh that predates the rollback's second step
for i in range(1, 5):
    (bx / f"notes{i}.txt").write_text(f"{i}\n")
    if i == 1:   # the real deploy.sh and its stubs are part of the tree from c1 on
        shutil.copy(os.path.join(STACK, "deploy.sh"), bx / "deploy.sh"); (bx / "units").mkdir()
        (bx / "stackshot/core").mkdir(parents=True); (bx / "stackshot/core/config.py").write_text('import sys\nif sys.argv[1:] == ["get", "server.port"]: print("1")\n')
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
if [ "$1" = show ] && [ -n "${{RT_SHOW_LONG:-}}" ]; then   # the file, a pause, then 400 KB more: a reader that stops at its first match closes the pipe on this writer, as one on a long file does
  {shutil.which("git")} "$@"; sleep 1; head -c 400000 /dev/zero | tr '\\0' x; exit
fi
exec {shutil.which("git")} "$@"
'''); (dp / "bin/git").chmod(0o755)
def deploy(to=None, fetch_fails=None):
    e = {**genv, "PATH": f"{dp}/bin:" + os.environ.get("PATH", "")}; e.pop("DEPLOY_TO", None)
    if to: e["DEPLOY_TO"] = to
    if fetch_fails: e["RT_FETCH_FAILS"] = str(fetch_fails); (dp / "fetches").unlink(missing_ok=True)
    rc_, text_ = run_alarm(["bash", str(bx / "deploy.sh")], 60, cwd=bx, env=e)
    return rc_, text_, g("rev-parse", "HEAD", cwd=bx)
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
    rc_, text_ = run_alarm((["flock", str(LOCKF)] if locked else []) + cmd, 60, cwd=bx, env=e)
    return rc_, text_, g("rev-parse", "HEAD", cwd=bx)
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
rc, out, head = rollback(cs[2], extra={"RT_SHOW_LONG": "1"})
check("deploy.sh DEPLOY_ROLLBACK=1 when `git show` of the target's deploy.sh keeps writing for a second after the marker line (400 KB more): the marker is found, no false \"predates\" refusal, the rollback goes through (the check reads the whole file, so the pipe is never closed on git show)",
      rc == 0 and head == cs[2] and "predates the rollback's second step" not in out and f"rolling back {c7[:7]} to {cs[2][:7]}" in out, (rc, out))
g("reset", "-q", "--hard", c7, cwd=bx)
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
# an ignored file (a __pycache__/*.pyc the interpreter wrote) under a path the target tracks as a file is no clash: a reset removes it; a file that is not ignored still refuses
with open(bx / ".git/info/exclude", "a") as f_: f_.write("__pycache__/\n")
(bx / "é/__pycache__").mkdir(parents=True); (bx / "é/__pycache__/m.cpython-312.pyc").write_bytes(b"\0")
rc, out, head = rollback(c8)
check("deploy.sh rollback: an ignored é/__pycache__/m.pyc where the target tracks a file é is no clash: the rollback runs and goes back to the target",
      rc == 0 and head == c8 and "an untracked file stands" not in out and f"rolling back {c9[:7]} to {c8[:7]}" in out, (rc, out))
g("reset", "-q", "--hard", c9, cwd=bx)
(bx / "é").mkdir(); (bx / "é/__pycache__").mkdir(); (bx / "é/__pycache__/m.cpython-312.pyc").write_bytes(b"\0"); (bx / "é/real.txt").write_text("untracked, not ignored\n")
rc, out, head = rollback(c8)
check("deploy.sh rollback: the same folder with a file that is not ignored beside the .pyc: refused, named (the .pyc is not), HEAD unmoved, both files untouched",
      rc == 1 and head == c9 and "an untracked file stands where the target commit tracks a path" in out and "é/real.txt" in out and "m.cpython" not in out
      and (bx / "é/real.txt").exists() and (bx / "é/__pycache__/m.cpython-312.pyc").exists(), (rc, out))
(bx / "é/real.txt").unlink(); (bx / "é/__pycache__/m.cpython-312.pyc").unlink(); (bx / "é/__pycache__").rmdir(); (bx / "é").rmdir()

# ---- 13. release on PR pass: a PR whose checks passed on a head that contains main's tip deploys at the merge; main's full run
# follows, outside the lock, and a failure rolls back to the last good commit. The git stub's history is linear, oldest first: HIST.

s = fast("fast-pass", merge="ok")
check("up to date: deploys the merge commit at once, pinned to it, and main's run is read after the deploy, never before",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view"], (s["rc"], s["deploys"], s["order"], s["out"]))
check("up to date: the log says why, then that main's tests passed on the commit, after the done line",
      "merged by the merge queue as 0106c0d" in s["log"] and "deploying 0106c0d at once: the merge queue ran the suites its selection picked for the merge group on the tree it made (not every suite); main's full run follows; 600d000 is the last good commit to go back to" in s["log"]
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
s = fast("fast-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
check("up to date, main fails: deploys the merge, then rolls back to the last good commit (a rollback deploy), in that order",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"]
      and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view", f"deploy:{GOOD}", "client:message"], (s["rc"], s["deploys"], s["order"], s["out"]))
check("main fails: the rollback runs under the lock (taken again), and nothing is left holding it", s["locks"] == ["held", "held"] and lock_free(s) and s["log"].count("deploy lock taken") == 2, (s["locks"], s["log"]))
check("main fails: FAILED at main's tests: rolled back to the sha, red (no --release), after the green deploy report",
      len(s["msgs"]) == 2 and s["msgs"][0].endswith(GREEN_ARGS) and "FAILED at main's tests: rolled back to 600d000 · the run on main for 0106c0d failed (run every suite, measured=failure;" in s["msgs"][1]
      and "--release" not in s["msgs"][1] and s["msgs"][1].endswith("| --sender | release"), s["msgs"])
check("main fails: the report says main still holds the merge and that no recycle was flagged",
      "main still holds the failing merge, fix forward or revert it" in s["msgs"][1] and "no recycle was flagged" in s["msgs"][1], s["msgs"][1])
s = fast("fast-fail-notice", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", pickfiles="stackshot/model/next_rules.py", notice="notify")
check("main fails after a notice went out: the rollback report says in one line that the notice had gone out and is not taken back",
      "notice: sent" in s["msgs"][0] and len(s["notice"]) == 1 and "no recycle was flagged; a notice about this release had already gone out, and a rollback does not take it back" in red(s)[0], (s["notice"], s["msgs"]))
s = fast("fast-fail-notice-unset", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", pickfiles="stackshot/model/next_rules.py")
check("main fails when no notice was sent (no command set): the rollback report does not claim one", "no recycle was flagged" in red(s)[0] and "a notice about this release" not in red(s)[0], red(s))
s = fast("fast-fail-notice-failed", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", pickfiles="stackshot/model/next_rules.py", notice="notify", notice_fail="1")
check("main fails when the notice command failed: the rollback report does not claim a notice went out", "a notice about this release" not in red(s)[0], red(s))
s = fast("fast-fail-mixed", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", pickfiles="client/hooks/session-start.sh,stackshot/model/next_rules.py", notice="notify")
check("main fails after a recycle and a notice: the rollback report names both",
      "a recycle was already flagged for this PR's items before the failure" in red(s)[0] and "a notice about this release had already gone out" in red(s)[0], red(s))
check("main fails: the last good record is unchanged", s["lastgood"] == GOOD, s["lastgood"])
check("main fails: no item is settled (the server is never asked)", s["released"] == [] and "items of PR" not in s["log"], (s["released"], s["log"]))
s = fast("fast-fail-several", merge="ok", main8="fail", runs=json.dumps([{"databaseId": 8, "headSha": LATER}]), heads=f"{BASE},{BASE},{LATER}",
         covered="9aaaaaa Merge pull request #26 from x/y;0106c0d Merge pull request #23 from agent/topic;5ec0000 Merge pull request #25 from z")
check("the failing run covers several merges since the last good commit: the report says so and names them",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "the failing run covers 3 merges since the last good commit 600d000" in red(s)[0]
      and "9aaaaaa Merge pull request #26" in red(s)[0] and "0106c0d Merge pull request #23" in red(s)[0] and "5ec0000 Merge pull request #25" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-ontop", merge="ok", main="fail", heads=f"{BASE},{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other")
check("another release deployed a commit on top meanwhile (the live checkout still contains the failing one): rolled back, the report names what the rollback also removes",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "rolled back to 600d000" in red(s)[0]
      and "the rollback also takes out the other merges between 600d000 and the live checkout" in red(s)[0] and "5ec0000 Merge pull request #35" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-newer-good", merge="ok", main="fail", heads=f"{BASE},{BASE},{NEWER}", newgood=NEWER)
check("a newer commit whose run on main passed is recorded and deployed meanwhile: never rolled back past it, said in the report, nothing deployed after the merge",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "FAILED at main's tests" in red(s)[0] and "NOT rolled back, a newer commit whose run on main passed, 0107c0d, contains 0106c0d: never rolled back past a newer good commit" in red(s)[0]
      and "rolled back to" not in red(s)[0] and s["lastgood"] == NEWER and lock_free(s), (s["deploys"], s["msgs"], s["lastgood"]))
s = fast("fast-fail-gone", merge="ok", main="fail", heads=f"{BASE},{BASE},{GOOD}")
check("the live checkout no longer contains the failing commit (rolled back by hand, say): nothing to roll back, said in the report",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, the live checkout (600d000) no longer contains 0106c0d" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-rbfail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", rollback_fail="1")
check("the rollback deploy itself fails: FAILED at rollback, naming the commit to go back to by hand; the lock is free",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at rollback: main's tests failed on 0106c0d" in red(s)[0]
      and "rollback to 600d000 failed: rollback: healthz did not answer" in red(s)[0] and f"flock {s['lockfile']} env DEPLOY_ROLLBACK=1 DEPLOY_TO={GOOD} ./deploy.sh" in red(s)[0] and lock_free(s), (s["deploys"], s["msgs"]))
s = fast("fast-fail-lock", merge="ok", main="fail", grab=True, grab_on="fail", heads=f"{BASE},{BASE},{MERGE}", extra={"DEPLOY_LOCK_WAIT": "1"})
check("main fails but the lock is held elsewhere past the timeout: FAILED at deploy lock, nothing rolled back, the report says how to do it by hand",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "FAILED at deploy lock: another deploy held the lock" in red(s)[0] and "nothing was rolled back; by hand, in " in red(s)[0]
      and f"flock {s['lockfile']} env DEPLOY_ROLLBACK=1 DEPLOY_TO={GOOD} ./deploy.sh (deploy.sh refuses a rollback unless the lock is held)" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-fail-recycle", args=("--recycle",), merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
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

# the gate is closed, or the live checkout already holds the merge
s = fast("gate-diverged", merge="ok", heads=B2)
check("(a) the live checkout holds a commit the merge does not (it is not an ancestor of the merge): the gate is closed, main's tests first, the reason in the log, no deploy at the merge",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and "(a) the live checkout (ba5e200) is not an ancestor of the merge 0106c0d" in s["log"]
      and "the deploy waits for main's tests" in s["log"] and "main's full run follows" not in s["msgs"][0] and s["released"] == [RELEASED_ARGS + MERGE], (s["order"], s["log"]))
s = fast("gate-live", merge="ok", heads=NEWER)
check("the live checkout already contains the merge (a later release deployed past it): nothing is deployed, the log and the report say \"already live\", the report is green, main's run is read and the pass recorded",
      s["rc"] == 0 and not s["deployed"] and s["deploys"] == [] and s["order"] == ["client:message", "run-view"] and "already live: the live checkout (0107c0d) contains the merge 0106c0d" in s["log"]
      and "done: 0106c0d, already live, restarted nothing" in s["log"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "merged and already live" in s["msgs"][0]
      and "restarted: nothing" in s["msgs"][0] and "nothing was deployed here" in s["msgs"][0]
      and "main's tests passed on 0106c0d (run 7)" in s["log"] and s["lastgood"] == MERGE and s["released"] == [RELEASED_ARGS + MERGE] and lock_free(s), (s["order"], s["log"], s["msgs"], s["lastgood"]))
check("already live: the deploy lock was taken for the check and let go before the report, and no pending-verify record was written", s["lock_at_live"] and s["client_fd9"] and set(s["client_fd9"]) == {"closed"} and s["pending_files"] == [], (s["lock_at_live"], s["pending_files"]))
s = fast("gate-live-fail", merge="ok", main="fail", heads=NEWER)
check("already live and main's run for the merge fails: rolled back like any deploy at the merge (the live checkout contains the failing commit)",
      s["rc"] == 1 and s["deploys"] == [f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0], (s["deploys"], s["msgs"]))

# the merge call errors (a 504) and the PR is in the queue or merged: carries on, on the gate's path as on the other
s = fast("fast-a", merge="fail", gq="queued,merged", branch="present")
check("the enqueue call errors (504) and the PR reads queued: carries on, deploys the merge commit at once, reports the error, then main passes",
      s["rc"] == 0 and s["deploys"] == [MERGE] and "the enqueue call errored (HTTP 504: We couldn't respond to your request in time.) but the PR was OPEN, in the merge queue (QUEUED position 1)" in s["msgs"][0]
      and "deployed at the merge" in s["msgs"][0] and "main's tests passed on 0106c0d" in s["log"] and deletes(s) == [f"api -X DELETE repos/{R}/git/refs/heads/agent/topic"], (s["deploys"], s["sleeps"], s["msgs"]))
s = fast("fast-open", merge="fail", gq="open")
check("the enqueue call errors and the PR stays plainly open: FAILED at merge, nothing deployed, no main wait", s["rc"] == 1 and not s["deployed"] and "FAILED at merge" in red(s)[0] and "run-view" not in s["order"], (s["msgs"], s["order"]))

# the last-good record: seeded on first use from the deployed HEAD when its main run passed; read for the rollback; written by a pass, never moved back
s = fast("fast-seed", merge="ok", lastgood="", main="pass,fail", heads=f"{BASE},{BASE},{MERGE}")
check("no record yet: seeded from the live HEAD (main's tip) when its run on main passed, and that record is what a failing main run rolls back to",
      s["rc"] == 1 and "seeded with the deployed ba5e000, whose run 7 on main passed" in s["log"] and s["deploys"] == [MERGE, f"rollback {BASE}"] and s["lastgood"] == BASE
      and "rolled back to ba5e000" in red(s)[0], (s["log"], s["deploys"], s["lastgood"]))
s = fast("fast-noseed", merge="ok", lastgood="", main="fail,pass")
check("no record, and the live HEAD's run on main did not pass: nothing to roll back to, so the old path (main's run first); its pass writes the record",
      s["rc"] == 0 and s["order"] == ["run-view", "run-view", f"deploy:{MERGE}", "client:message"] and "there is nothing to roll back to" in s["log"] and s["lastgood"] == MERGE, (s["order"], s["log"], s["lastgood"]))

# ---- 13b. what the fast path may carry along (the coordinator's review): the live HEAD is main's tip (a), and no failed run since the last good commit (b);
# a run still pending is no reason to wait, so back-to-back releases stay fast
FAILED_SHA = "fa11ed0000000000000000000000000000000000"
s = fast("fast-failed-run", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "failure"}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) a commit between the last good one and main's tip has a FAILED run on main: the old path, the run named in the log",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and f"(c) a commit after the last good one (600d000) has a failed run on main (run 5 on {FAILED_SHA})" in s["log"], (s["order"], s["log"]))
s = fast("fast-failed-run-outside", merge="ok", range="", runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "failure"}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) a failed run on a commit outside last-good..main's tip does not matter: the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}", (s["order"], s["log"]))
s = fast("fast-runs-unreadable", merge="ok", runs="not json", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("(b) GitHub's list of runs cannot be read: nothing can be vouched for, the old path", "(c) the runs on main since the last good commit 600d000 cannot be read" in s["log"] and not s["deploys"], (s["log"], s["deploys"]))
s = fast("fast-pending-base", merge="ok", range=BASE, runs=json.dumps([{"databaseId": 6, "headSha": BASE, "conclusion": None}, {"databaseId": 7, "headSha": MERGE}]))
check("(b) main's tip has a run that is still pending (no conclusion yet): not a failure, the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}", (s["order"], s["log"]))

# two up-to-date PRs back to back, the first's run still pending when the second arrives: both are deployed at the merge (A waits for its run until B has deployed)
pair2 = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-b2b-")); dirs.append(pair2)
lk2 = {"DEPLOY_LOCK_FILE": str(pair2 / "deploy.lock"), "RT_TRACE": str(pair2 / "trace"), "DEPLOY_LOCK_WAIT": "60"}
res2 = {}
ta = threading.Thread(target=lambda: res2.update(a=fast("b2b-a", merge="ok", extra={**lk2, "RT_VIEW_AFTER": str(pair2 / "b-deployed"), "RT_VIEWING_MARK": str(pair2 / "a-waits")})))
tb = threading.Thread(target=lambda: res2.update(b=fast("b2b-b", merge="ok", merge_oid=NEWER, head=NEWPR, base=MERGE, heads=MERGE, history=",".join([GOOD, BASE, MERGE, NEWPR, NEWER]), tips=NEWER,
                                                        range=MERGE, runs=json.dumps([{"databaseId": 8, "headSha": NEWER}]), extra={**lk2, "RT_DEPLOYED_MARK": str(pair2 / "b-deployed")})))
ta.start()
for _ in range(600):   # B starts only once A has deployed and waits on its run
    if (pair2 / "a-waits").exists(): break
    threading.Event().wait(0.05)
tb.start(); ta.join(); tb.join()
a, b = res2.get("a"), res2.get("b")
check("two up-to-date PRs back to back, the first's run still pending: both deploy at the merge, A's before B's, A's run is read only after B has deployed; both green",
      a and b and a["rc"] == 0 and b["rc"] == 0 and a["deploys"] == [MERGE] and b["deploys"] == [NEWER] and a["order"] == [f"deploy:{MERGE}", "client:message", "run-view"]
      and b["order"][0] == f"deploy:{NEWER}" and "deploying 0107c0d at once" in b["log"] and "main's full run follows" in b["msgs"][0],
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
s = fast("fast-fail-ontop2", merge="ok", main="fail", heads=f"{BASE},{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other;0107c0d Merge pull request #37 from agent/more")
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
s = fast("fast-rolled-back-fail", merge="ok", main="fail", marker="#26 (main's tests failed on abc1234)", heads=f"{BASE},{BASE},{BASE}")
check("a release already rolled back by another's failure whose own run then fails: nothing more to roll back, and the report says it was rolled back with #26",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, the live checkout (ba5e000) no longer contains 0106c0d: it was rolled back or reset already (rolled back with #26 (main's tests failed on abc1234))" in red(s)[0], (s["deploys"], s["msgs"]))
s = fast("fast-cancelled", merge="ok", main7="cancelled", heads=f"{BASE},{BASE},{MERGE}", extra={"RELEASE_CAP_MAIN": "60"})
check("main's only run cancelled (after its job started, the job limit or by hand), after a deploy at the merge, no later run: waited for until the cap, then unknown: no rollback, a red report naming the cancelled run",
      s["rc"] == 1 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] * 3
      and "FAILED at main's tests: no finished run on main covers 0106c0d after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 90 min); the run 7 on 0106c0d was cancelled and no later run covers 0106c0d" in red(s)[0]
      and "deployed at 0106c0d and NOT rolled back" in red(s)[0] and "rolled back to" not in red(s)[0], (s["deploys"], s["msgs"], s["sleeps"]))
s = fast("fast-fail-words", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", newunits="units/stackshot-foo.timer.in,units/stackshot-foo.service.in,units/notes.md")
check("the red rollback report says a rollback does not undo data or state changes, and names the unit and timer files the rolled-back commits added as left installed",
      s["rc"] == 1 and "a rollback does not undo data or state changes the rolled-back commits made" in red(s)[0]
      and "left installed: stackshot-foo.timer, stackshot-foo.service (the rolled-back commits added them), disable by hand if needed" in red(s)[0], red(s))
s = fast("fast-fail-nounits", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
check("no unit added: the report has no 'left installed' part", "left installed" not in red(s)[0] and s["rc"] == 1, red(s))
s = scenario("record-not-back", merge="ok", lastgood=NEWER, history=f"{MERGE},{NEWER}")
check("a pass on an older commit than the record never moves it back", s["rc"] == 0 and s["lastgood"] == NEWER, s["lastgood"])
s = scenario("record-written", merge="ok")
check("a pass on main writes the commit it passed on, one sha, atomically (no temp file left, only the lock file beside it)", s["rc"] == 0 and s["lastgood"] == "0106c0de0106c0de0106c0de0106c0de0106c0de"
      and sorted(p.name for p in (s["dir"] / "releases").iterdir() if p.name.startswith("last-good")) == ["last-good", "last-good.lock"], s["lastgood"])

# the removed releases come from the last good commit up to the live checkout, not from the failing merge up: releases deployed BEFORE it (their runs still waiting) go too
s = fast("fast-removed-below", merge="ok", main="fail", heads=f"{BASE},{BASE},{LATER}",
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
for nm, mk in (("fast", fast), ("old", scenario)):
    s = mk(f"exit-{nm}", clobber="1", merge="ok")
    check(f"({nm} path) release.sh replaced by the deploy: the running script reads nothing from the new bytes and exits cleanly", s["rc"] == 0 and not (s["dir"] / "stale-read").exists() and s["deployed"], (s["rc"], s["out"]))

# ---- 13e. the rollback, the live check and the pending-verify record
# the rollback's lists are full shas (%H), never an abbreviation that lengthens with the repository
s = fast("fast-removed-full", merge="ok", main="fail", heads=f"{BASE},{BASE},{LATER}", removed=f"{MERGE} Merge pull request #23 from agent/topic;5ec0000 Merge pull request #35 from agent/other")
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
      s["rc"] == 0 and "deploying 0106c0d at once" not in s["log"] and f"(c) a commit after the last good one (600d000) has a run on main cancelled after its job started (5 {FAILED_SHA}" in s["log"], (s["order"], s["log"]))
s = fast("fast-replaced-run", merge="ok", range=FAILED_SHA, runs=json.dumps([{"databaseId": 5, "headSha": FAILED_SHA, "conclusion": "cancelled"}, {"databaseId": 7, "headSha": MERGE}]), main5="replaced")
check("(b) a run in the range cancelled while queued (no step ran) was replaced by a newer run: not a reason, the fast path", s["rc"] == 0 and "deploying 0106c0d at once" in s["log"] and "not up to date" not in s["log"], (s["order"], s["log"]))

# a fast deploy leaves a pending-verify record, held by the live release; it is gone when the watch concludes
s = fast("pv-live", merge="ok")
check("a fast deploy writes a pending-verify record, its lock held by the running release while it waits on main's run, and clears it when the run passes",
      s["rc"] == 0 and s["pending_at_view"] == ["pr-23:locked"] and s["pending_files"] == [], (s["pending_at_view"], s["pending_files"]))
s = scenario("pv-live-old", merge="ok")
check("the old path writes none", s["rc"] == 0 and s["pending_at_view"] == [] and s["pending_files"] == [], (s["pending_at_view"], s["pending_files"]))
s = fast("pv-live-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}")
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
      s["deploys"] == [f"rollback {GOOD}", MERGE] and "not deployed at the merge yet: the deploy of PR #26 at ba5e000 failed main's run" in s["log"], (s["deploys"], s["log"]))
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
check("…a fail is a red report for the killed PR, a rollback to the last good commit, the record gone; the new release itself carries on",
      s2["rc"] == 0 and s2["deploys"][:2] == [MERGE, f"rollback {GOOD}"] and any("PR #23 FAILED at main's tests: rolled back to 600d000" in m for m in red(s2)) and s2["pending_files"] == [], (s2["deploys"], s2["msgs"], s2["pending_files"]))

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
s = scenario("pv-old-nodeploy-record", merge="ok")
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

# ---- 16. the session pick: what the running sessions need, from the files the merged PR changed (nothing, a notice or a recycle; the highest wins)
def recycled(s): return "recycle-due | --pr" in s["msg"]
def pick_reads(s): return [l for l in s["gh"].splitlines() if l.startswith("api repos/example-owner/stackshot/pulls/23/files")]
s = scenario("pick-server-only", merge="ok", pickfiles="server.py,render.py,docs/windows.md,tests/release_scenario.py", notice="notify")
check("pick: a server-only PR (code, docs, tests) picks nothing: no recycle, no notice, green, the log and report name the pick and the files",
      s["rc"] == 0 and s["deployed"] and not recycled(s) and not s["notice"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS)
      and "session pick: nothing (from server.py, render.py, docs/windows.md, tests/release_scenario.py)" in s["log"]
      and "sessions: nothing (from server.py, render.py" in s["msgs"][0] and len(pick_reads(s)) == 1, (s["log"], s["msgs"], s["gh"]))
s = scenario("pick-per-call-hook", merge="ok", pickfiles="client/hooks/project-page.sh,client/hooks/client.sh,stackshot/fleet/client.py,stackshot/projects/pages.py", notice="notify")
check("pick: a per-call hook script and the client CLI pick nothing (each call runs them afresh)",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and "session pick: nothing (from client/hooks/project-page.sh" in s["log"]
      and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
s = scenario("pick-start-loaded", merge="ok", pickfiles="server.py,docs/windows.md,client/hooks/session-start.sh", notice="notify")
check("pick: a file loaded at the session's start picks a recycle, over nothing: recycle-due on the PR, no notice, green",
      s["rc"] == 0 and recycled(s) and not s["notice"] and "session pick: recycle (from client/hooks/session-start.sh)" in s["log"]
      and "sessions: recycle (from client/hooks/session-start.sh)" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
check("pick: the log lists each changed file with its need", all(t in s["log"] for t in ("recycle  client/hooks/session-start.sh", "nothing  docs/windows.md", "nothing  server.py")), s["log"])
# a PR that needs a recycle and also a notice does both: a recycle does not deliver a notice's change (the tools' text, the write rules)
s = scenario("pick-mixed", merge="ok", pickfiles="server.py,stackshot/model/next_rules.py,client/hooks/session-start.sh,tests/tool_text.snapshot.json", notice="notify --all")
check("pick: files that need a recycle and a notice do both: recycle-due on the PR, and [fleet] notice_cmd run with the notice files only, green",
      s["rc"] == 0 and recycled(s) and s["notice"][0] == "--all" and len(s["notice"]) == 2 and s["notice"][1].startswith("release: stackshot PR #23: a change \u2014 ")
      and "stackshot/model/next_rules.py, tests/tool_text.snapshot.json" in s["notice"][1] and "session-start.sh" not in s["notice"][1] and "a recycle does not deliver it" in s["notice"][1]
      and "session pick: recycle + notice (from client/hooks/session-start.sh; notice from stackshot/model/next_rules.py, tests/tool_text.snapshot.json)" in s["log"]
      and "sessions: recycle + notice (from client/hooks/session-start.sh; notice from stackshot/model/next_rules.py" in s["msgs"][0]
      and "notice: sent" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
check("pick: the log lists the notice file and the recycle file with their needs", all(t in s["log"] for t in ("recycle  client/hooks/session-start.sh", "notice   stackshot/model/next_rules.py", "nothing  server.py")), s["log"])
s = scenario("pick-mixed-notice-fails", merge="ok", pickfiles="client/hooks/session-start.sh,stackshot/model/next_rules.py", notice="notify", notice_fail="1")
check("pick: a failed notice beside a recycle still runs the recycle, and the report goes to the keeper instead of green",
      s["rc"] == 0 and recycled(s) and len(s["notice"]) == 1 and "notice NOT sent" in s["msgs"][0] and "recycle: " in s["msgs"][0] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-mixed-notice-unset", merge="ok", pickfiles="client/hooks/session-start.sh,stackshot/model/next_rules.py")
check("pick: a recycle with a notice and no [fleet] notice_cmd set runs the recycle, says no notice command is set, and stays green",
      s["rc"] == 0 and recycled(s) and "notice: none sent, no [fleet] notice_cmd is set" in s["msgs"][0] and "recycle: " in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
# a notice command that never finishes is stopped at the timeout (RELEASE_NOTICE_TIMEOUT, 60 s by default): not sent, no green, and the report still goes out
s = scenario("pick-notice-hangs", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify", notice_hang="1", extra={"RELEASE_NOTICE_TIMEOUT": "1"}, secs=60)
check("pick: a notice command that hangs is stopped at the timeout: the log says it timed out, the report goes out without the green flag, the release finishes",
      s["rc"] == 0 and s["deployed"] and len(s["msgs"]) == 1 and "notice NOT sent: [fleet] notice_cmd timed out after 1s" in s["msgs"][0] and "--release" not in s["msgs"][0]
      and "notice NOT sent: [fleet] notice_cmd timed out after 1s" in s["log"], (s["rc"], s["log"], s["msgs"]))
check("pick: the hung notice command is gone (stopped, not left running)", s["notice_pid"].isdigit() and not os.path.exists(f"/proc/{s['notice_pid']}"), s["notice_pid"])
check("pick: the notice timeout is 60 s by default", 'NOTICE_TIMEOUT="${RELEASE_NOTICE_TIMEOUT:-60}"' in pathlib.Path(STACK, "release.sh").read_text(), "")
# a hostile title reaches the notice command as one argument, verbatim, and runs nothing
HOSTILE = "it's \"quoted\" `touch PWNED_bt` $(touch PWNED_cmd) $HOME ${HOME} ; touch PWNED_semi & \\n *"
s = scenario("pick-notice-hostile-title", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify --all", title=HOSTILE)
leftovers = [str(q) for base in (s["dir"], s["dir"] / "box", pathlib.Path.cwd()) for q in base.glob("PWNED_*")]
check("pick: a hostile title (quotes, backticks, $(...), $HOME) reaches [fleet] notice_cmd inside its one text argument, verbatim apart from the joiner, and nothing in it runs",
      s["rc"] == 0 and s["notice"][:1] == ["--all"] and len(s["notice"]) == 2 and s["notice"][1].startswith(f"release: stackshot PR #23: {HOSTILE} \u2014 stackshot PR #23 is live at ")
      and "$HOME" in s["notice"][1] and len(s["notice"][1]) <= 400 and not leftovers, (s["notice"], leftovers, s["log"]))
# the fleet notice command takes one text argument of at most 400 characters with no newline or tab: the title and summary are joined, flattened and cut
s = scenario("pick-notice-flatten", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify", title="line one\nline two\tcell\r\nline three")
check("pick: a newline or tab in the title becomes a space, and the one argument has none left",
      s["rc"] == 0 and len(s["notice"]) == 1 and s["notice"][0].startswith("release: stackshot PR #23: line one line two cell  line three \u2014 stackshot PR #23 is live at ")
      and not any(c in s["notice"][0] for c in "\n\t\r"), (s["notice"], s["log"]))
LONG = "long title " + "x" * 600
s = scenario("pick-notice-cut", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify", title=LONG)
check("pick: a notice longer than 400 characters is cut to exactly 400, ending in an ellipsis, and the release stays green",
      s["rc"] == 0 and len(s["notice"]) == 1 and len(s["notice"][0]) == 400 and s["notice"][0].endswith("x\u2026") and s["notice"][0].startswith("release: stackshot PR #23: long title xxx")
      and "notice: sent" in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
s = scenario("pick-notice-fits", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify")
check("pick: a notice of 400 characters or fewer is not cut and has no ellipsis", s["rc"] == 0 and len(s["notice"]) == 1 and len(s["notice"][0]) <= 400 and not s["notice"][0].endswith("\u2026"), s["notice"])
s = scenario("pick-rules-text", merge="ok", pickfiles="server.py,stackshot/model/next_rules.py,audit_rubric.txt", notice="notify --all")
check("pick: a rules-text file picks a notice: [fleet] notice_cmd runs with one argument appended (title and summary joined), no recycle, green",
      s["rc"] == 0 and not recycled(s) and s["notice"][0] == "--all" and len(s["notice"]) == 2 and s["notice"][1].startswith("release: stackshot PR #23: a change \u2014 stackshot PR #23 is live at ")
      and "stackshot/model/next_rules.py, audit_rubric.txt" in s["notice"][1] and "\n" not in s["notice"][1]
      and "session pick: notice (from stackshot/model/next_rules.py, audit_rubric.txt)" in s["log"] and "notice: sent" in s["msgs"][0] and s["msgs"][0].endswith(GREEN_ARGS), (s["notice"], s["log"], s["msgs"]))
s = scenario("pick-tool-text", merge="ok", pickfiles="server.py,tests/tool_text.snapshot.json", notice="notify")
check("pick: a change to the tools' text is a notice, never a recycle", s["rc"] == 0 and not recycled(s) and len(s["notice"]) == 1 and "session pick: notice (from tests/tool_text.snapshot.json)" in s["log"], (s["log"], s["notice"]))
s = scenario("pick-notice-unset", merge="ok", pickfiles="audit_rubric.txt")
check("pick: a notice with no [fleet] notice_cmd set logs that none is set and does not fail the release (still green)",
      s["rc"] == 0 and s["deployed"] and "notice: none sent, no [fleet] notice_cmd is set" in s["log"] and not s["notice"]
      and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "FAILED" not in s["log"], (s["log"], s["msgs"]))
s = scenario("pick-notice-fails", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="notify", notice_fail="1")
check("pick: a notice command that fails does not fail the release, and the report goes to the keeper instead of green",
      s["rc"] == 0 and len(s["notice"]) == 1 and "notice NOT sent" in s["msgs"][0] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-notice-missing", merge="ok", pickfiles="stackshot/model/model_guards.py", notice="no-such-notice-tool")
check("pick: a notice command not on PATH is told the same way", s["rc"] == 0 and "notice NOT sent" in s["msgs"][0] and "--release" not in s["msgs"][0], s["msgs"])
s = scenario("pick-override-recycle", args=("--recycle",), merge="ok", pickfiles="server.py", notice="notify")
check("--recycle forces a recycle on a server-only PR, and the files are not read",
      s["rc"] == 0 and recycled(s) and not s["notice"] and not pick_reads(s) and "session pick: recycle (from forced by --recycle)" in s["log"], (s["log"], s["gh"]))
s = scenario("pick-override-no-recycle", args=("--no-recycle",), merge="ok", pickfiles="client/hooks/session-start.sh,stackshot/model/next_rules.py", notice="notify")
check("--no-recycle forces nothing on a PR that would pick a recycle: no recycle, no notice, no read, green",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and not pick_reads(s) and "session pick: nothing (from forced by --no-recycle)" in s["log"]
      and s["msgs"][0].endswith(GREEN_ARGS), (s["log"], s["msgs"]))
s = scenario("pick-files-unreadable", merge="ok", pickfiles="fail", notice="notify")
check("pick: files that cannot be read pick nothing, say so, and the report goes to the keeper instead of green",
      s["rc"] == 0 and not recycled(s) and not s["notice"] and "could not be read (HTTP 502: bad gateway)" in s["log"] and "--release" not in s["msgs"][0], (s["log"], s["msgs"]))
s = scenario("pick-front-both", args=("--recycle", "--no-recycle"), front=True, merge="ok")
check("front door: two overrides are refused with the usage line", s["rc"] == 2 and "usage: release.sh <pr> [--recycle | --no-recycle]" in s["out"] and not s["gh"], s["out"])

# the dry runs: the pick and each file's need, nothing else (no merge, no deploy, no message)
s = scenario("pick-dry-files", raw=["--pick-files", "server.py", "client/hooks/session-start.sh", "stackshot/model/next_rules.py"])
check("--pick-files: prints the pick and each file's need, calls nothing, deploys nothing, sends nothing; a recycle with a notice reads \"recycle + notice\"",
      s["rc"] == 0 and "session pick for the files named: recycle + notice (from client/hooks/session-start.sh; notice from stackshot/model/next_rules.py)" in s["out"] and "notice   stackshot/model/next_rules.py" in s["out"]
      and not s["gh"] and not s["deployed"] and not s["msg"] and not os.path.exists(s["dir"] / "releases/pr-23.log"), s["out"])
# the root forwarders are deleted: a PR that deletes them tells no session (their package files carry the need)
s = scenario("pick-dry-deleted-forwarders", raw=["--pick-files", "next_rules.py", "model_guards.py", "owner_steps.py", "bullet_text.py", "pages.py", "client.py", "puller.py"])
check("--pick-files: a deleted root forwarder (next_rules.py ...) needs nothing; only the package's own file is a notice",
      s["rc"] == 0 and "session pick for the files named: nothing" in s["out"] and "notice " not in s["out"].replace("session pick", ""), s["out"])
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
s = scenario("report-to-set-red", merge="fail", gq="open", report_to=REPORTS)
check("report_to: a failed release reports to the configured page too, once", s["rc"] != 0 and len(s["msgs"]) == 1 and s["msgs"][0].startswith(f"message | {REPORTS} | ") and "projects/example |" not in s["msg"], (s["rc"], s["msg"]))
s = scenario("report-to-unset", merge="ok")
check("report_to: unset (the config gives nothing), the report goes to the stand-in page", len(s["msgs"]) == 1 and s["msgs"][0].startswith("message | projects/example | [release] PR #23"), s["msg"])
for nm, kw, want in (("unset", {}, "projects/example"), ("set", {"report_to": REPORTS}, REPORTS)):
    s = scenario(f"start-{nm}", front=True, units="", **kw)
    check(f"report_to ({nm}): the line printed when a release starts names the page the report will go to", s["rc"] == 0 and f"and reports to {want} · log " in s["out"] and (nm == "set") == (want != "projects/example") and (nm != "set" or "projects/example ·" not in s["out"]), s["out"])

# ---- 17. the review of the first version. The way in is decided by what GitHub says about the branch (repository.mergeQueue): the enqueuePullRequest mutation with the queue on, the plain merge call with it off. The stub refuses the
# wrong call (wrong_calls): a plain `gh pr merge` with the queue on asks for auto-merge, which this repository does not allow (cli/cli#13398); the mutation with no queue is refused too.
s = scenario("mq-on", gq="queued,merged")
check("queue on: the mutation enqueuePullRequest is the only way in (the PR's node id, the head it is pinned to), one read of mergeQueue, no plain merge, no auto-merge, and the stub saw no wrong call",
      s["rc"] == 0 and enqueues(s) == [ENQUEUE] and not plain_merges(s) and s["mq_reads"] == 1 and not s["wrong_calls"] and "--auto" not in s["gh"], (s["gh"], s["enqueue_args"], s["wrong_calls"]))
s = scenario("mq-off", mq="off")
check("queue off (the ruleset is off, the way back): `gh pr merge --merge --admin --match-head-commit <head>`, pinned (--admin: a green PR reads BLOCKED under the bot-only ruleset), and no mutation; the stub saw no wrong call",
      s["rc"] == 0 and plain_merges(s) == [f"pr merge 23 --repo {R} --merge --admin --match-head-commit {HEADSHA}"] and not enqueues(s) and s["mq_reads"] == 1 and not s["wrong_calls"], (s["gh"], s["wrong_calls"]))
check("queue off: the log says the PR was merged at once without the queue, and the report says it",
      at(s["log"], "no merge queue on main (the ruleset is off): merged at once", "merged as 0106c0d by the plain merge call, not the merge queue") and "merged without the merge queue (the ruleset is off)" in s["msg"], (s["log"], s["msg"]))
check("queue off: no merge_group run tested that merge, so the deploy waits for main's tests, whatever the gate would say, and the log says why",
      s["deploys"] == [MERGE] and s["order"][:2] == ["run-view", f"deploy:{MERGE}"] and "not deployed at the merge yet: the PR was merged by the plain merge call: the repository has no merge queue on main" in s["log"] and " at once: the merge queue ran" not in s["log"],
      (s["order"], s["log"]))
s = fast("mq-off-gate-open", mq="off")
check("queue off, the deploy gate otherwise open (last good in the history, no failed run): the deploy still waits for main's tests, and nothing is deployed at the merge",
      s["rc"] == 0 and s["order"][0] == "run-view" and "not deployed at the merge yet: the PR was merged by the plain merge call" in s["log"] and " at once: the merge queue ran" not in s["log"] and not s["wrong_calls"], (s["order"], s["log"]))
s = fast("mq-on-gate-open", gq="queued,merged")
check("queue on, the gate open: the deploy is at once, and the words say what ran there: the suites the selection picked for the merge group, not every suite; main's full run follows",
      s["order"][0] == f"deploy:{MERGE}" and "the merge queue ran the suites its selection picked for the merge group on the tree it made (not every suite); main's full run follows" in s["log"]
      and "GitHub's merge queue ran the selected suites on the tree it made, not every suite" in s["msg"], (s["order"], s["log"], s["msg"]))
s = scenario("mq-read-fails", mq="fail")
check("the read of the repository's queue fails three times: FAILED at merge, nothing is merged or enqueued, no guess about the way in",
      s["rc"] == 1 and not s["deployed"] and not merges(s) and s["mq_reads"] == 3 and s["sleeps"] == ["10", "10"] and "FAILED at merge: GitHub's answer about the repository's merge queue and the PR cannot be read" in s["msg"], (s["msg"], s["sleeps"], s["mq_reads"]))
s = scenario("mq-read-garbage", mq="garbage")
check("an answer about the queue that is not JSON is unreadable too", s["rc"] == 1 and not merges(s) and "FAILED at merge" in s["msg"], s["msg"])
s = scenario("enqueue-red", enqueue="red", gq="open")
check("the mutation is refused because a required check is red (GitHub's words, as a staged queue gave them): FAILED at merge with that text in the report, after reading the PR again; nothing deployed, nothing on the timeline read",
      s["rc"] == 1 and not s["deployed"] and 'FAILED at merge: Pull request has failing required statuses and Pull request Required status check "suites" is failing.' in s["msg"] and s["gq_reads"] == 6 and s["gq_reason_reads"] == 0, (s["msg"], s["gq_reads"]))
s = scenario("enqueue-ref", enqueue="ref", gq="open")
check("the mutation is refused by a ref rule (an error on the call only, nothing on the PR's timeline): FAILED at merge with GitHub's text, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge: Pull request Cannot update this protected ref." in s["msg"] and s["gq_reason_reads"] == 0 and "gh: " not in s["msg"], (s["msg"],))
s = scenario("mq-off-504", mq="off", merge="fail", gq="merged")
check("queue off, the plain merge call errors (504) after the PR was merged: read again, merged, carried on, and the report says the call errored",
      s["rc"] == 0 and s["deployed"] and "the merge call errored" in s["log"] and "but the PR is MERGED; carrying on" in s["log"] and not s["wrong_calls"], (s["log"], s["wrong_calls"]))

# 3. a PR that left the queue and shows MERGED on a later read is merged, not removed; the removal reason is an event of this enqueue
s = scenario("removed-then-merged", gq="queued,open,open,merged")
check("the entry is gone on two reads and the PR then shows MERGED: merged, deployed, no 'removed' and no timeline read (it used to fail at pr state with no deploy)",
      s["rc"] == 0 and s["deployed"] and "merged by the merge queue as 0106c0d" in s["log"] and "removed from the merge queue" not in s["log"] and "FAILED" not in s["log"] and s["gq_reason_reads"] == 0 and s["gq_reads"] == 4, (s["rc"], s["log"], s["gq_reads"]))
s = scenario("removed-for-good", gq="queued,open", gq_reason="the merge group failed its checks")
check("removed and still not MERGED on the three reads after the second: FAILED at merge queue with the reason, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge queue: removed from the merge queue: the merge group failed its checks" in s["msg"] and s["gq_reads"] >= 5, (s["msg"], s["gq_reads"]))
s = scenario("removed-stale-event", gq="queued,open", gq_reason="the merge group failed its checks", gq_stale="an earlier enqueue was removed: a conflict")
check("an older removal event listed after this enqueue's is not the reason: the one dated after the enqueue is",
      s["rc"] == 1 and "removed from the merge queue: the merge group failed its checks" in s["msg"] and "an earlier enqueue" not in s["msg"], s["msg"])
s = scenario("removed-only-stale-event", gq="queued,open", gq_reason="none", gq_stale="an earlier enqueue was removed: a conflict")
check("only an event dated before the enqueue: it says nothing about this removal, so the failure says GitHub gave no reason, and the old text is not used",
      s["rc"] == 1 and "GitHub's timeline gives no reason" in s["msg"] and "an earlier enqueue" not in s["msg"] and s["gq_reason_reads"] == 3, (s["msg"], s["gq_reason_reads"]))
s = scenario("removed-event-before-enqueue", gq="queued,open", gq_reason="a removal an hour before the enqueue", gq_reason_age="3600")
check("an event dated an hour before the enqueue is not this removal's either", s["rc"] == 1 and "GitHub's timeline gives no reason" in s["msg"] and "an hour before" not in s["msg"], s["msg"])

# 4. a rerun on a PR GitHub merged after the earlier release ended: it carries on from the merge
s = scenario("rerun-merged", viewstate="MERGED")
check("a rerun on a merged PR carries on from the merge: no enqueue, no read of the queue, no wait for checks; the gate is closed (nothing says the merge came through the queue), so main's tests first, then the deploy, the report and the items",
      s["rc"] == 0 and s["deployed"] and not merges(s) and s["mq_reads"] == 0 and "pr checks" not in s["gh"] and s["order"][:2] == ["run-view", f"deploy:{MERGE}"]
      and "is merged already, as 0106c0d: carrying on from the merge" in s["log"] and "not deployed at the merge yet: the PR was merged before this release started" in s["log"]
      and "FAILED" not in s["log"] and "done: " in s["log"] and len(s["released"]) == 1 and s["released"][0].endswith(MERGE), (s["rc"], s["log"], s["order"], s["released"]))
check("a rerun on a merged PR: one green report that says it carried on from the merge", len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "carried on from the merge 0106c0d" in s["msgs"][0], s["msgs"])
s = fast("rerun-merged-gate-open", viewstate="MERGED")
check("a rerun on a merged PR with the gate otherwise open: still not deployed at the merge", s["rc"] == 0 and s["order"][0] == "run-view" and "at once" not in s["log"], (s["order"], s["log"]))
s = fast("rerun-merged-main-fails", viewstate="MERGED", main="fail", heads=f"{BASE},{BASE}", live=NOTLIVE)
check("a rerun on a merged PR whose main run fails: merged and not deployed, red, like any release", s["rc"] == 1 and not s["deployed"] and "FAILED at main's tests" in s["msg"], s["msg"])
s = scenario("rerun-merged-no-commit", viewstate="MERGED", gq="mergednocommit")
check("a merged PR GitHub gives no merge commit for: FAILED at pr state after three reads, nothing deployed", s["rc"] == 1 and not s["deployed"] and "FAILED at pr state: the PR is merged, but GitHub gives no merge commit" in s["msg"] and s["sleeps"] == ["10", "10"], (s["msg"], s["sleeps"]))
s = fast("rerun-merged-live", viewstate="MERGED", heads=f"{NEWER},{NEWER}")
check("a rerun on a merged PR that a later deploy carried already: nothing to deploy, and the report says it is already live", s["rc"] == 0 and not s["deploys"] and "already live" in s["log"], (s["log"], s["deploys"]))


# GitHub's removal reasons (lower case, as a staged queue gave them) are said in words; "merged" is the merge itself, not a failure
for ri, (reason, words) in enumerate([("failed_checks", "the merge group failed its required checks"), ("merge_conflict", "a merge conflict with main"), ("manual", "removed from the queue by hand"),
                      ("branch_protection_failure", "branch protection failed for the merge group")]):
    s = scenario(f"reasonenum-{ri}", merge="ok", gq="queued,open,open", gq_reason=reason)
    check(f"removal reason {reason}: FAILED at merge queue, said in words ({words}), nothing deployed", s["rc"] == 1 and not s["deployed"] and f"FAILED at merge queue: removed from the merge queue: {words}" in s["msg"] and reason not in s["msg"], (s["msg"],))
s = scenario("reason-merged", merge="ok", gq="queued,open,open,open,open,open,open,merged", gq_reason="merged")
check("a removal event with reason merged is the merge itself: the PR is read again until it shows merged, then deployed; no failure",
      s["rc"] == 0 and s["deployed"] and "FAILED" not in s["log"] and "merged by the merge queue as 0106c0d" in s["log"] and not red(s), (s["rc"], s["log"], s["sleeps"]))
s = scenario("reason-merged-never", merge="ok", gq="queued,open", gq_reason="merged")
check("a removal event with reason merged but the PR never shows merged: FAILED at merge queue, with that said, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge queue: removed from the merge queue: the timeline says the PR left the queue because it merged, but GitHub does not show a merged PR" in s["msg"], (s["msg"],))
s = scenario("entry-states", merge="ok", gq="queued,awaiting,unmergeable,merged")
check("the entry goes QUEUED, AWAITING_CHECKS, UNMERGEABLE (seen on a conflict) and the PR then merges: each is still in the queue, read every 60 s, never a removal; deployed",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["60", "60", "60"] and "removed" not in s["log"], (s["sleeps"], s["log"]))
s = scenario("removed-merged-late", merge="ok", gq="queued,open,open,open,open,open,merged", gq_reason="failed_checks", viewstate="OPEN,MERGED")
check("the PR shows MERGED only on the read after it was called removed: not a failure at pr state; carried on from the merge (gate closed, main's tests first), deployed, one green report that says so",
      s["rc"] == 0 and s["deployed"] and "FAILED" not in s["log"] and "shows merged now, as 0106c0d, after it was read as removed from the merge queue" in s["log"] and s["order"][0] == "run-view"
      and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "showed merged after it was read as removed from the merge queue" in s["msgs"][0], (s["rc"], s["log"], s["order"], s["msgs"]))
s = scenario("rerun-merged-unknown", viewstate="MERGED", mergeable="UNKNOWN")
check("a rerun on a merged PR whose mergeable reads UNKNOWN (what GitHub gives after a merge) is not a problem: carried on from the merge", s["rc"] == 0 and "carried on from the merge" in s["msgs"][0], (s["rc"], s["msgs"]))

# 5. the gate: clause (a) the live checkout is an ancestor of the merge, clause (b) the last-good commit is in the live history, (c) up to main's tip
s = fast("gate-a-diverged", heads="d1e00000000000000000000000000000000000d1")
check("gate (a): a live checkout that is not an ancestor of the merge (a commit the history does not hold): closed, the reason names (a), main's tests first",
      s["rc"] == 0 and s["order"][0] == "run-view" and "not deployed at the merge yet: (a) the live checkout (d1e0000) is not an ancestor of the merge 0106c0d" in s["log"], (s["order"], s["log"]))
s = fast("gate-b-newer-good", lastgood=LATER)
check("gate (b): a last-good commit that is not in the live history (it is newer than the live checkout): closed, the reason names (b), main's tests first",
      s["rc"] == 0 and s["order"][0] == "run-view" and "not deployed at the merge yet: (b) the last-good commit 5ec0000 is not in the deployed history (ba5e000)" in s["log"], (s["order"], s["log"]))
LATER_FAIL = json.dumps([{"databaseId": 9, "headSha": LATER, "conclusion": "failure"}, {"databaseId": 7, "headSha": MERGE}])
s = fast("gate-c-later-tip", range=MERGE, range_tip=f"{MERGE},{LATER}", tip=LATER, runs=LATER_FAIL)
check("gate (c) reads up to main's tip: a failed run on a later member of the merge group closes the gate (it used to read only up to the merge)",
      s["rc"] == 0 and s["order"][0] == "run-view" and f"not deployed at the merge yet: (c) a commit after the last good one (600d000) has a failed run on main (run 9 on {LATER})" in s["log"], (s["order"], s["log"]))
s = fast("gate-c-later-tip-ok", range=MERGE, range_tip=f"{MERGE},{LATER}", tip=LATER, runs=json.dumps([{"databaseId": 9, "headSha": LATER}, {"databaseId": 7, "headSha": MERGE}]))
check("gate (c): a later tip whose run is pending or passed does not close it", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}", s["order"])

# --status: the log's newest line says what is waited for, the unit's state is systemd's
sd = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-status-")); dirs.append(sd)
(sd / "bin").mkdir(); (sd / "bin/systemctl").write_text("#!/bin/sh\necho active\n"); (sd / "bin/systemctl").chmod(0o755)   # the unit is running; never the host's systemctl
sres = {}
tp = threading.Thread(target=lambda: sres.update(s=scenario("status", reuse={"dir": sd}, gq="queued,queued,merged", park_gq="2")))
tp.start()
try:
    for _ in range(600):
        if (sd / "parked").exists(): break
        threading.Event().wait(0.05)
    st = subprocess.run(["bash", str(sd / "box/release.sh"), "--status", "23"], env={**ENV0, "PATH": f"{sd}/bin:" + os.environ.get("PATH", ""), "RT_DIR": str(sd)}, capture_output=True, text=True, timeout=60)
    st0 = subprocess.run(["bash", str(sd / "box/release.sh"), "--status"], env={**ENV0, "PATH": f"{sd}/bin:" + os.environ.get("PATH", ""), "RT_DIR": str(sd)}, capture_output=True, text=True, timeout=60)
finally:
    (sd / "unpark").touch(); tp.join()
stl = st.stdout.rstrip("\n").splitlines()
check("--status of a release waiting in the merge queue: the unit is active and the newest log line says where the PR stands",
      st.returncode == 0 and stl[0] == "unit stackshot-release-23: active" and "in the merge queue (QUEUED position 1)" in stl[-1], st.stdout)
check("--status with no number: the latest release", st0.returncode == 0 and st0.stdout == st.stdout, (st0.stdout, st.stdout))
check("--status: the same release then finishes with the deploy", sres.get("s") and sres["s"]["rc"] == 0 and sres["s"]["deploys"] == [MERGE], sres.get("s") and sres["s"]["out"])
st = subprocess.run(["bash", str(sd / "box/release.sh"), "--status", "99"], env={**ENV0, "PATH": f"{sd}/bin:" + os.environ.get("PATH", ""), "RT_DIR": str(sd)}, capture_output=True, text=True, timeout=60)
check("--status of a release with no log: the unit's state and nothing else", st.returncode == 0 and st.stdout.strip() == "unit stackshot-release-99: active", st.stdout)


wf = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text()
check("the step names main_green reads are tests.yml's own", all(f"- name: {n}\n" in wf for n in ("run every suite, measured", "audit the selection")))

# ---- 12b. deploy.sh's restart plan for the package layout: the real deploy.sh, --dry-run, in a throwaway checkout of a throwaway origin;
# the plan is what a change between two commits restarts (the units start the server and the hub through the project's pinned dependencies and stackshot/cli.py)
pl = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-plan-")); dirs.append(pl)
g("init", "-q", "--bare", "-b", "main", str(pl / "origin.git")); g("clone", "-q", str(pl / "origin.git"), str(pl / "box"))
pbx = pl / "box"
STUB_CONFIG = ('import os, sys\n'      # what deploy.sh asks config.py: the port (a script), runner_process() (an import, read from RT_RUNNER: "unit" when unset, an error for "boom" = a config that cannot be read) and state() (the runner's files, RT_STATE)
               'from pathlib import Path\n'
               'def runner_process():\n    v = os.environ.get("RT_RUNNER") or "unit"\n    if v == "boom": raise RuntimeError("the config cannot be read")\n    return v\n'
               'def state(*parts): return Path(os.environ["RT_STATE"], *parts)\n'
               'if sys.argv[1:] == ["get", "server.port"]: print("1")\n')
STUB_SCOPE = 'server_ctl() { echo "server_ctl $*" >> "${RT_LOG:-/dev/null}"; }\nxdg_repair() { :; }\nstandby() { [ "${RT_STANDBY:-}" = 1 ]; }\n'      # units/scope.sh without systemd: the server's control logs, and a standby is RT_STANDBY=1
def stub_tree(b, template):
    """The files of a throwaway checkout that deploy.sh reads: its own deploy.sh, a config.py stub, the runner's file module (the real one: the heartbeat check reads what the runner writes through it) and a scope.sh and install.sh stub.
    `template`: the minute unit's template is in the tree (a commit from after the unit was added) or not (from before)."""
    shutil.copy(os.path.join(STACK, "deploy.sh"), b / "deploy.sh"); (b / "units").mkdir(exist_ok=True); (b / "stackshot/core").mkdir(parents=True, exist_ok=True); (b / "stackshot/core/config.py").write_text(STUB_CONFIG)
    for m in ("runner_files", "filecache", "readonly"): shutil.copy(os.path.join(STACK, f"stackshot/core/{m}.py"), b / f"stackshot/core/{m}.py")
    (b / "units/scope.sh").write_text(STUB_SCOPE)
    (b / "install.sh").write_text('#!/bin/sh\necho "install.sh $*" >> "${RT_LOG:-/dev/null}"\nif [ "$1" = minute-off ]; then [ -n "${RT_OFF_FAILS:-}" ] && exit 1; rm -f "$HOME/.config/systemd/user/stackshot-minute.service"; fi\nexit 0\n'); (b / "install.sh").chmod(0o755)
    if template: (b / "units/stackshot-minute.service.in").write_text("[Unit]\n")
stub_tree(pbx, template=False)
g("add", "-A", cwd=pbx); g("commit", "-qm", "older base: before the minute unit", cwd=pbx); pold = g("rev-parse", "HEAD", cwd=pbx)
(pbx / "units/stackshot-minute.service.in").write_text("[Unit]\n")
g("add", "-A", cwd=pbx); g("commit", "-qm", "base", cwd=pbx); pbase = g("rev-parse", "HEAD", cwd=pbx)
S_, H_, P_, M_ = "stackshot.service", "anchor-hub.service", "stackshot-puller.service", "stackshot-minute.service"
HOME_NONE, HOME_MIN = pl / "home-none", pl / "home-minute"      # the plan looks at the home folder for the minute unit: one with no unit (the default: nothing of it in any plan) and one with it installed
HOME_NONE.mkdir(); (HOME_MIN / ".config/systemd/user").mkdir(parents=True); (HOME_MIN / ".config/systemd/user" / M_).write_text("[Service]\n")
def plan(*files, home=HOME_NONE, rollback=False, runner="", standby=False, old=False):
    g("reset", "-q", "--hard", pbase, cwd=pbx)
    for f in files:
        (pbx / f).parent.mkdir(parents=True, exist_ok=True); (pbx / f).write_text(f"{f} changed\n")
    g("add", "-A", cwd=pbx); g("commit", "-qm", "change " + " ".join(files), cwd=pbx); g("push", "-q", "-f", "origin", "HEAD:main", cwd=pbx)
    env = {**genv, "PATH": os.environ.get("PATH", ""), "HOME": str(home), "RT_RUNNER": runner, "RT_STANDBY": "1" if standby else ""}
    if rollback: env.update(DEPLOY_ROLLBACK="1", DEPLOY_TO=pold if old else pbase)       # a dry run of the rollback's first step, from the changed commit back to the base: the same files differ, the other way round
    else: g("reset", "-q", "--hard", pbase, cwd=pbx)
    r = subprocess.run(["bash", str(pbx / "deploy.sh"), "--dry-run"], cwd=pbx, env=env, capture_output=True, text=True, timeout=60)
    g("reset", "-q", "--hard", pbase, cwd=pbx)
    return r.returncode, [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("restarts:")], r.stdout + r.stderr
# the table of deploy.sh: one row per rule of its file map (a pattern of each case line, and the exclusions of the *.py default), what a change restarts, as the set of units (the server is always first when it is in the plan)
for what, files, want in (("pyproject.toml alone", ("pyproject.toml",), {S_, H_}), ("uv.lock alone", ("uv.lock",), {S_, H_}),
                          ("stackshot/cli.py", ("stackshot/cli.py",), {S_, H_}), ("an icon (the server only)", ("icons/a.png",), {S_}), ("a doc only", ("docs/notes.md",), set()),
                          ("stackshot/__init__.py: every program starts through it", ("stackshot/__init__.py",), {S_, H_, P_}), ("stackshot/__main__.py", ("stackshot/__main__.py",), {S_, H_, P_}),
                          ("stackshot/paths.py", ("stackshot/paths.py",), {S_, H_, P_}), ("stackshot/core/config.py: the puller reads it too", ("stackshot/core/config.py",), {S_, H_, P_}),
                          ("stackshot/fleet/puller.py: the puller only", ("stackshot/fleet/puller.py",), {P_}), ("stackshot/fleet/client.py: the puller only", ("stackshot/fleet/client.py",), {P_}),
                          ("stackshot/fleet/push.py: the hub only", ("stackshot/fleet/push.py",), {H_}),
                          ("stackshot/anchors/anchor_hub.py: the hub only", ("stackshot/anchors/anchor_hub.py",), {H_}),
                          ("stackshot/anchors/anchors.py: the server and the hub", ("stackshot/anchors/anchors.py",), {S_, H_}), ("a module of the server (stackshot/web/server.py)", ("stackshot/web/server.py",), {S_}),
                          ("a suite (tests/x_scenario.py)", ("tests/x_scenario.py",), set()), ("a module the server never runs (stackshot/projects/rename_page.py)", ("stackshot/projects/rename_page.py",), set()),
                          ("units/anchor-hub.service.in: the hub only", ("units/anchor-hub.service.in",), {H_}), ("units/stackshot-puller.service.in: the puller only", ("units/stackshot-puller.service.in",), {P_}),
                          ("units/stackshot.service.in: the server only", ("units/stackshot.service.in",), {S_}), ("units/stackshot-reload.path: the server only", ("units/stackshot-reload.path",), {S_}), ("install.sh: the server only", ("install.sh",), {S_}),
                          ("stackshot/core/retired_inputs.py: the server and the puller (client.py imports it)", ("stackshot/core/retired_inputs.py",), {S_, P_}),
                          ("stackshot/anchors/merge_log.py: the server and the hub", ("stackshot/anchors/merge_log.py",), {S_, H_}), ("stackshot/anchors/event_log.py: the server and the hub", ("stackshot/anchors/event_log.py",), {S_, H_}),
                          ("a font (the server only)", ("fonts/code.woff2",), {S_}), ("shared/colortool.js (the server only)", ("shared/colortool.js",), {S_}), ("a tools text file (stackshot/web/tools/text/brief.md: the server only)", ("stackshot/web/tools/text/brief.md",), {S_}),
                          ("stackshot/anchors/anchorhub/x.py: the hub only", ("stackshot/anchors/anchorhub/x.py",), {H_}),
                          ("stackshot/projects/project_registry.py: the server and the hub", ("stackshot/projects/project_registry.py",), {S_, H_}), ("stackshot/projects/projects.py: the server and the hub", ("stackshot/projects/projects.py",), {S_, H_}),
                          ("stackshot/fleet/fleet.py: the server and the hub", ("stackshot/fleet/fleet.py",), {S_, H_}), ("stackshot/fleet/liveness.py: the server and the hub", ("stackshot/fleet/liveness.py",), {S_, H_}),
                          ("stackshot/router/routing.py: the server and the hub", ("stackshot/router/routing.py",), {S_, H_}), ("stackshot/fleet/inbox.py: the server and the hub", ("stackshot/fleet/inbox.py",), {S_, H_}),
                          ("stackshot/fleet/sessions_registry.py: the server and the hub", ("stackshot/fleet/sessions_registry.py",), {S_, H_}), ("stackshot/core/interp.py: the server and the hub", ("stackshot/core/interp.py",), {S_, H_}),
                          ("stackshot/projects/page_keeper.py: nothing (a one-off script)", ("stackshot/projects/page_keeper.py",), set()), ("stackshot/anchors/anchor_hub_google_auth.py: nothing (a one-off script)", ("stackshot/anchors/anchor_hub_google_auth.py",), set())):
    rc, got, out = plan(*files)
    units = got[0].split()[1:] if got and got[0] != "restarts: none" else []
    check(f"deploy.sh plan: {what} restarts exactly {sorted(want) or 'nothing'}, the server first", rc == 0 and len(got) == 1 and set(units) == want and len(units) == len(want) and (not units or S_ not in units or units[0] == S_), (rc, got, out[-300:]))

# the minute runner's unit (stackshot-minute.service): in the plan, and restarted, only when its unit file is installed (install.sh installs it only with [runner] process = "unit"), by the files the server restarts for
# (not its own unit file or its reload watcher's), install.sh and its own unit; right after the server
def plan_units(*files, **kw):
    rc, got, out = plan(*files, **kw)
    return rc, (got[0].split()[1:] if got and got[0] != "restarts: none" else []), got, out
for what, files, want in (("stackshot/web/minute.py", ("stackshot/web/minute.py",), [S_, M_]), ("a module of the server (stackshot/web/server.py)", ("stackshot/web/server.py",), [S_, M_]),
                          ("pyproject.toml (the unit runs through the locked project environment)", ("pyproject.toml",), [S_, M_, H_]), ("uv.lock", ("uv.lock",), [S_, M_, H_]), ("stackshot/cli.py (the unit starts the program through it)", ("stackshot/cli.py",), [S_, M_, H_]),
                          ("stackshot/core/config.py", ("stackshot/core/config.py",), [S_, M_, H_, P_]), ("stackshot/__init__.py", ("stackshot/__init__.py",), [S_, M_, H_, P_]), ("stackshot/paths.py", ("stackshot/paths.py",), [S_, M_, H_, P_]),
                          ("stackshot/core/retired_inputs.py", ("stackshot/core/retired_inputs.py",), [S_, M_, P_]), ("stackshot/anchors/merge_log.py", ("stackshot/anchors/merge_log.py",), [S_, M_, H_]),
                          ("stackshot/anchors/event_log.py", ("stackshot/anchors/event_log.py",), [S_, M_, H_]), ("stackshot/projects/projects.py", ("stackshot/projects/projects.py",), [S_, M_, H_]),
                          ("an icon", ("icons/a.png",), [S_, M_]), ("a font", ("fonts/code.woff2",), [S_, M_]), ("shared/colortool.js", ("shared/colortool.js",), [S_, M_]),
                          ("a tools text file", ("stackshot/web/tools/text/brief.md",), [S_, M_]), ("install.sh", ("install.sh",), [S_, M_]),
                          ("units/stackshot-minute.service.in: the minute unit only, not the server", ("units/stackshot-minute.service.in",), [M_]),
                          ("units/stackshot.service.in: the server only, the minute unit does not depend on it", ("units/stackshot.service.in",), [S_]),
                          ("units/stackshot-reload.path: the server only", ("units/stackshot-reload.path",), [S_]), ("units/stackshot-reload.service.in: the server only", ("units/stackshot-reload.service.in",), [S_]),
                          ("units/anchor-hub.service.in: the hub only", ("units/anchor-hub.service.in",), [H_]), ("units/stackshot-puller.service.in: the puller only", ("units/stackshot-puller.service.in",), [P_]),
                          ("stackshot/fleet/puller.py: the puller only", ("stackshot/fleet/puller.py",), [P_]), ("stackshot/anchors/anchor_hub.py: the hub only", ("stackshot/anchors/anchor_hub.py",), [H_]),
                          ("a suite (tests/x_scenario.py)", ("tests/x_scenario.py",), []), ("a doc only", ("docs/notes.md",), []), ("a one-off script (stackshot/projects/page_keeper.py)", ("stackshot/projects/page_keeper.py",), [])):
    rc, units_, got, out = plan_units(*files, home=HOME_MIN)
    check(f"deploy.sh plan, minute unit installed: {what} restarts exactly {want or 'nothing'}, in that order (the minute unit right after the server)", rc == 0 and len(got) == 1 and units_ == want, (rc, got, out[-300:]))
    rc, units_, got, out = plan_units(*files, home=HOME_NONE)
    check(f"deploy.sh plan, no minute unit installed: {what} restarts {[u for u in want if u != M_] or 'nothing'}, the minute unit never", rc == 0 and len(got) == 1 and units_ == [u for u in want if u != M_], (rc, got, out[-300:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, rollback=True)
check("deploy.sh --dry-run of a rollback (DEPLOY_ROLLBACK=1 DEPLOY_TO=<older commit>), minute unit installed: the same plan, the minute unit right after the server", rc == 0 and units_ == [S_, M_] and "rolling back" in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_NONE, rollback=True)
check("deploy.sh --dry-run of a rollback, no minute unit: the server only", rc == 0 and units_ == [S_] and "rolling back" in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("units/stackshot-minute.service.in", home=HOME_MIN, rollback=True)
check("deploy.sh --dry-run of a rollback of the minute unit's own file: it alone", rc == 0 and units_ == [M_], (rc, got, out[-300:]))

OLD_DEPLOY = '#!/bin/sh\n# a deploy.sh from before the minute unit: it knows the rollback hand-off (DEPLOY_ROLLED_BACK_FROM) and nothing of the unit\necho "old deploy.sh ran from=${DEPLOY_ROLLED_BACK_FROM:-none}" >> "$RT_LOG"\n[ -z "${RT_OLD_FAILS:-}" ] || exit 1\nexit 0\n'
def real_deploy(files, home, rollback=False, tripped=False, runner="", standby=False, predates=False, active="active", beat="fresh", off_fails=False, wait=None, mainpid=4242, beatpid=None, old_fails=False, timeout=120):
    """The real deploy.sh, run for real (not --dry-run) in a throwaway checkout, with systemctl, the server's control, install.sh, uv and curl stubs that log to one file → (rc, stdout, the log's lines).
    The home is a copy (the stub install.sh removes the minute unit's file there, as the real one does). `predates`: the rollback's target has no template of the minute unit and an older deploy.sh (a stub that only logs).
    The systemctl stub answers is-active for the minute unit with `active` ("active", "inactive", "failed"), its MainPID with `mainpid`, and writes its heartbeat (status.json under RT_STATE/minute) at its restart as `beat` says: "fresh", "none" or
    "stale" (an hour old), as the process `beatpid` (the MainPID by default). `old_fails`: the older deploy.sh of a `predates` rollback exits 1. A run that is not over in `timeout` seconds is stopped and returns rc -999 (a failed check, not a hung suite)."""
    d = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-mdeploy-")); dirs.append(d)
    g("init", "-q", "--bare", "-b", "main", str(d / "origin.git")); g("clone", "-q", str(d / "origin.git"), str(d / "box")); b = d / "box"
    stub_tree(b, template=not predates)
    if predates: (b / "deploy.sh").write_text(OLD_DEPLOY); (b / "deploy.sh").chmod(0o755)
    g("add", "-A", cwd=b); g("commit", "-qm", "base", cwd=b); base = g("rev-parse", "HEAD", cwd=b)
    if predates:      # the change adds the unit's template and the current deploy.sh: a rollback from it goes back to a tree without either
        shutil.copy(os.path.join(STACK, "deploy.sh"), b / "deploy.sh"); (b / "units/stackshot-minute.service.in").write_text("[Unit]\n")
    for f in files:
        (b / f).parent.mkdir(parents=True, exist_ok=True); (b / f).write_text(f"{f} changed\n")
    g("add", "-A", cwd=b); g("commit", "-qm", "change", cwd=b); g("push", "-q", "origin", "HEAD:main", cwd=b)
    if not rollback: g("reset", "-q", "--hard", base, cwd=b)
    (d / "bin").mkdir(); h = d / "home"; shutil.copytree(home, h)
    # the start limit, as systemd keeps it: after it tripped (RT_TRIP exists) a restart of the minute unit is refused until reset-failed has cleared it, and reset-failed on a unit that is not failed exits 1, as the real one does
    # ("Unit ... not loaded"); a restart of the minute unit starts a runner that writes its heartbeat as RT_BEAT says
    systemctl = ('echo "systemctl $*" >> "$RT_LOG"\n'
                 'case "$*" in\n'
                 '  *reset-failed*stackshot-minute*) if [ -e "$RT_TRIP" ]; then rm -f "$RT_TRIP"; else echo "Unit stackshot-minute.service not loaded." >&2; exit 1; fi ;;\n'
                 '  *restart*stackshot-minute*) [ -e "$RT_TRIP" ] && { echo "Start request repeated too quickly." >&2; exit 1; }\n'
                 '     mkdir -p "$RT_STATE/minute"; case "$RT_BEAT" in\n'
                 '       fresh) python3 -c \'import json, os, sys, time; open(sys.argv[1], "w").write(json.dumps({"pid": int(os.environ["RT_BEATPID"]), "heartbeat": time.time(), "ticks": []}))\' "$RT_STATE/minute/status.json" ;;\n'
                 '       stale) python3 -c \'import json, os, sys, time; open(sys.argv[1], "w").write(json.dumps({"pid": int(os.environ["RT_BEATPID"]), "heartbeat": time.time() - 3600, "ticks": []}))\' "$RT_STATE/minute/status.json" ;;\n'
                 '     esac ;;\n'
                 '  *"show -p MainPID"*stackshot-minute*) echo "$RT_MAINPID" ;;\n'
                 '  *is-active*stackshot-minute*) echo "$RT_ACTIVE"; [ "$RT_ACTIVE" = active ] || exit 3 ;;\n'
                 'esac\nexit 0')
    if tripped: (d / "tripped").write_text("")
    for n, body in (("systemctl", systemctl), ("uv", 'echo "uv $*" >> "$RT_LOG"; echo published'), ("curl", "exit 0")):
        (d / "bin" / n).write_text("#!/bin/sh\n" + body + "\n"); (d / "bin" / n).chmod(0o755)
    env = {**genv, "PATH": f"{d}/bin:" + os.environ.get("PATH", ""), "HOME": str(h), "RT_LOG": str(d / "log"), "RT_TRIP": str(d / "tripped"), "RT_RUNNER": runner, "RT_STANDBY": "1" if standby else "",
           "RT_STATE": str(d / "state"), "RT_ACTIVE": active, "RT_BEAT": beat, "RT_OFF_FAILS": "1" if off_fails else "", "DEPLOY_MINUTE_WAIT": str(wait if wait is not None else 20),
           "RT_MAINPID": str(mainpid), "RT_BEATPID": str(mainpid if beatpid is None else beatpid), "RT_OLD_FAILS": "1" if old_fails else ""}
    cmd = ["bash", str(b / "deploy.sh")]
    if rollback: env.update(DEPLOY_ROLLBACK="1", DEPLOY_TO=base, DEPLOY_LOCK_FILE=str(d / "deploy.lock")); cmd = ["flock", str(d / "deploy.lock")] + cmd
    rc_, text_ = run_alarm(cmd, timeout, cwd=b, env=env)
    real_deploy.last = (b, base)
    return rc_, text_, (d / "log").read_text().splitlines() if (d / "log").exists() else [], (h / ".config/systemd/user" / M_).exists()
def at(log, line): return log.index(line) if line in log else -1
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN)
check("deploy.sh, minute unit installed, a code change: the server is restarted, then the minute unit through the user manager, and the health check and the republish follow",
      rc == 0 and 0 <= at(log, "server_ctl restart stackshot.service") < at(log, f"systemctl --user restart {M_}") and "healthz ok" in out, (rc, log, out[-300:]))
check("...and says so in that order, after the units were reinstalled", 0 <= out.find("restarted stackshot.service") < out.find(f"restarted {M_}") and out.count(f"restarted {M_}") == 1 and "healthz ok" in out
      and 0 <= at(log, "install.sh units --force-host") < at(log, "server_ctl restart stackshot.service"), (out, log))
check("deploy.sh reinstalls the units with --force-host and never a bare `install.sh units`: it runs on the server host, and a refusal of the server-host check after the merge and before the restart would leave the deploy half done",
      "install.sh units --force-host" in log and "install.sh units" not in log, log)
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_NONE)
check("deploy.sh, no minute unit installed, the same change: the server restarted, nothing asked about the minute unit, nothing said about it", rc == 0 and "server_ctl restart stackshot.service" in log
      and not any("minute" in l for l in log) and "stackshot-minute" not in out, (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("units/stackshot-minute.service.in",), HOME_MIN)
check("deploy.sh, minute unit installed, only its unit file changed: the minute unit restarted, the server not (no republish either)", rc == 0 and f"systemctl --user restart {M_}" in log
      and not any(l.startswith("server_ctl restart") or l.startswith("uv run") for l in log), (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True)
check("deploy.sh rollback (both steps), minute unit installed: the good tree's own deploy.sh restarts the server and then the minute unit, and checks health", rc == 0 and out.count("rolling back") == 2
      and 0 <= at(log, "server_ctl restart stackshot.service") < at(log, f"systemctl --user restart {M_}") and "healthz ok" in out, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_NONE, rollback=True)
check("deploy.sh rollback, no minute unit installed: the server only", rc == 0 and "server_ctl restart stackshot.service" in log and not any("minute" in l for l in log), (rc, log, out[-300:]))

# the start limit: once it has tripped, systemd refuses a restart ("Start request repeated too quickly") until reset-failed has cleared the count, and the deploy runs under set -e
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, tripped=True)
check("deploy.sh, minute unit past its start limit: reset-failed comes right before the restart, so the restart works and the deploy runs on to the health check and the republish",
      rc == 0 and 0 <= at(log, "server_ctl restart stackshot.service") < at(log, f"systemctl --user reset-failed {M_}") < at(log, f"systemctl --user restart {M_}")
      and "restarted " + M_ in out and "healthz ok" in out and "republished" in out, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN)
check("deploy.sh, minute unit not tripped: reset-failed is run all the same (it does nothing to a unit that has not failed), once, before the restart", rc == 0 and log.count(f"systemctl --user reset-failed {M_}") == 1
      and at(log, f"systemctl --user reset-failed {M_}") < at(log, f"systemctl --user restart {M_}"), (rc, log))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, tripped=True)
check("deploy.sh rollback, minute unit past its start limit: the same, reset-failed then restart, and the rollback finishes", rc == 0 and at(log, f"systemctl --user reset-failed {M_}") < at(log, f"systemctl --user restart {M_}") and "healthz ok" in out, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_NONE, tripped=True)
check("deploy.sh, no minute unit installed: no reset-failed either", rc == 0 and not any("reset-failed" in l for l in log), (rc, log))
# [runner] process back at "inline" with the unit still installed (install.sh is about to remove it): not in the plan, not restarted, not reset
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, runner="inline")
check("deploy.sh --dry-run, unit installed but [runner] process reads inline: the plan has the server only", rc == 0 and units_ == [S_], (rc, got, out[-300:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, runner="unit")
check("deploy.sh --dry-run, unit installed and [runner] process reads unit: the server and the minute unit", rc == 0 and units_ == [S_, M_], (rc, got, out[-300:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, runner="inline", rollback=True)
check("deploy.sh --dry-run of a rollback, unit installed but the setting reads inline: the server only", rc == 0 and units_ == [S_], (rc, got, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, runner="inline", tripped=True)
check("deploy.sh, unit installed but [runner] process reads inline: the server restarted, no reset-failed and no restart of the minute unit (it would be refused or pointless: install.sh removes it)",
      rc == 0 and "server_ctl restart stackshot.service" in log and not any("minute" in l and ("reset-failed" in l or "restart" in l) for l in log) and "stackshot-minute" not in out.replace("install.sh units", "").replace("note: stackshot-minute.service is installed", ""), (rc, log, out[-300:]))

# a deploy that flips [runner] process back to inline with the unit installed (the setting is read at a start only): install.sh removes the unit, and a server started at "unit" runs no runner of its own. A docs-only change restarts
# nothing by its files, and would leave the box with no runner: the server is restarted in this same deploy, in the plan and in the run alike (never left to a later deploy)
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, runner="inline")
check("deploy.sh --dry-run, a docs-only change, unit installed, setting read as inline: the server is in the plan (the runner it started without must come back), with a note that says why", rc == 0 and units_ == [S_]
      and "note: stackshot-minute.service is installed but [runner] process reads \"inline\": install.sh removes it, and the server restarts in this deploy" in out, (rc, got, out[-400:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, runner="unit")
check("...control: the same change at unit restarts nothing, no note", rc == 0 and units_ == [] and "note:" not in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_NONE, runner="inline")
check("...control: no unit installed at inline restarts nothing, no note (nothing observable changes at the default)", rc == 0 and units_ == [] and "note:" not in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, runner="inline", rollback=True)
check("...a rollback's plan too", rc == 0 and units_ == [S_] and "note: stackshot-minute.service is installed" in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, runner="inline", standby=True)
check("...on a standby too (install.sh removes the unit at inline wherever the box stands)", rc == 0 and units_ == [S_], (rc, got, out[-300:]))
dry_plan = plan_units("docs/notes.md", home=HOME_MIN, runner="inline")[2]
rc, out, log, gone = real_deploy(("docs/notes.md",), HOME_MIN, runner="inline")
check("deploy.sh, a docs-only change, unit installed, setting read as inline: the server IS restarted, after install.sh units (which removes the unit) and with the health check and the republish after it; the runner of the real run is the dry run's plan",
      rc == 0 and 0 <= at(log, "install.sh units --force-host") < at(log, "server_ctl restart stackshot.service") and "healthz ok" in out and "republished" in out and [l for l in out.splitlines() if l.startswith("restarts:")] == dry_plan and log.count("server_ctl restart stackshot.service") == 1 and out.count("restarted stackshot.service") == 1
      and not any("minute" in l and ("restart" in l or "reset-failed" in l or "is-active" in l) for l in log), (rc, log, out[-500:], dry_plan))
rc, out, log, gone = real_deploy(("docs/notes.md",), HOME_MIN, runner="unit")
check("...control, real: at unit the same change restarts no unit and says nothing of a swap", rc == 0 and not any(l.startswith("server_ctl restart") for l in log) and "note:" not in out, (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("docs/notes.md",), HOME_NONE, runner="inline")
check("...control, real: no unit at inline restarts nothing and asks systemctl nothing", rc == 0 and not any(l.startswith("server_ctl restart") for l in log) and not any(l.startswith("systemctl") for l in log) and "note:" not in out, (rc, log, out[-300:]))

# a standby (STACKSHOT_READ_ONLY=1 in the environment of the server's unit): install.sh removes the minute unit there, so it is not in the plan and not restarted, whatever the files say
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, standby=True)
check("deploy.sh --dry-run, unit installed, the box is a read-only standby: the server only (the unit is on its way out)", rc == 0 and units_ == [S_], (rc, got, out[-300:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, standby=True)
check("deploy.sh --dry-run, a docs-only change on a standby at unit: nothing restarts (the standby has no runner to replace)", rc == 0 and units_ == [] and "note:" not in out, (rc, got, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, standby=True)
check("deploy.sh, unit installed on a standby: the server restarted, the minute unit neither reset nor restarted nor looked at", rc == 0 and "server_ctl restart stackshot.service" in log and not any("minute" in l and l.startswith("systemctl") for l in log), (rc, log, out[-300:]))

# a config that cannot be read counts as "unit": install.sh decides, and deploy.sh keeps the runner it has (a restart is harmless, a missing one is not)
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, runner="boom")
check("deploy.sh --dry-run, unit installed, [runner] process cannot be read (a config that fails to load): read as unit, the server and the minute unit in the plan", rc == 0 and units_ == [S_, M_], (rc, got, out[-300:]))
rc, units_, got, out = plan_units("docs/notes.md", home=HOME_MIN, runner="boom")
check("...and no swap is planned for it (an unreadable config is not 'inline'): a docs-only change restarts nothing", rc == 0 and units_ == [] and "note:" not in out, (rc, got, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, runner="boom")
check("deploy.sh, [runner] process cannot be read: the minute unit is restarted after the server, as at unit", rc == 0 and 0 <= at(log, "server_ctl restart stackshot.service") < at(log, f"systemctl --user restart {M_}"), (rc, log, out[-300:]))

# a rollback to a commit from before the unit: that commit's own deploy.sh (the second step) knows nothing of the unit and would never stop it, and the older server's inline runner comes up with its restart: so the first step
# stops, disables and removes the unit (install.sh minute-off) BEFORE it hands over
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, rollback=True, old=True)
check("deploy.sh --dry-run of a rollback to a commit from before the unit, unit installed: the server only (the unit is not restarted: it goes), with a note that names the removal and what then runs the runner",
      rc == 0 and units_ == [S_] and "note: " in out and "predates stackshot-minute.service, whose removal this deploy runs first (install.sh minute-off)" in out and "the older server's runner starts with its restart" in out, (rc, got, out[-500:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_NONE, rollback=True, old=True)
check("...with no unit installed there is nothing to remove: the same plan as ever, no note", rc == 0 and units_ == [S_] and "predates" not in out, (rc, got, out[-300:]))
rc, units_, got, out = plan_units("stackshot/web/minute.py", home=HOME_MIN, rollback=True)
check("...control: a rollback to a commit that has the unit takes no such step and says no such thing", rc == 0 and units_ == [S_, M_] and "predates" not in out, (rc, got, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, predates=True)
check("deploy.sh rollback to a commit from before the unit, unit installed: install.sh minute-off runs FIRST, then the older commit's own deploy.sh (which restarts the server and knows no unit); the unit file is gone, and the new deploy.sh never restarts or looks at it",
      rc == 0 and 0 <= at(log, "install.sh minute-off") < next((i for i, l in enumerate(log) if l.startswith("old deploy.sh ran from=")), -1) and not gone
      and not any(l.startswith("systemctl") and "minute" in l for l in log) and "removal this deploy runs first" in out, (rc, log, out[-500:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, predates=True, off_fails=True)
box, base_sha = real_deploy.last
check("...a minute-off that fails stops the rollback with the checkout untouched: nonzero exit, the reason on stderr, the older deploy.sh never run, the unit file still there (a runner still exists), HEAD still the newer commit",
      rc != 0 and "rollback stopped: stackshot-minute.service could not be stopped; the checkout is unchanged" in out and not any(l.startswith("old deploy.sh ran") for l in log) and gone
      and g("rev-parse", "HEAD", cwd=box) != base_sha, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_NONE, rollback=True, predates=True)
check("...no unit installed: no minute-off, the older deploy.sh runs", rc == 0 and not any("minute-off" in l for l in log) and any(l.startswith("old deploy.sh ran") for l in log), (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True)
check("...control: a rollback to a commit that has the unit never calls minute-off", rc == 0 and not any("minute-off" in l for l in log), (rc, log))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN)
check("...control: a plain deploy never calls minute-off", rc == 0 and not any("minute-off" in l for l in log), (rc, log))

# the unit is Type=simple: a restart that succeeds and a /healthz that answers say nothing of the runner. After the health check (and the republish), for a unit this deploy restarted, deploy.sh waits a bounded time for the unit to
# be active and for a heartbeat of the unit's own process that is newer than the restart. A runner that does not show is a WARNING line and the deploy still exits 0, like a failed republish: the server runs the new code by then, and a
# nonzero exit reads to release.sh as "merged, not live" (it pauses its queue). Every run here has an alarm of its own (real_deploy's timeout): a wait that does not end is a failed check, never a hung suite
WARN = "WARNING: stackshot-minute.service"
def warned(out, state, seen, wait):      # the one WARNING line: the unit, its state, what was seen of the heartbeat, the wait, and the commands to run
    return (out.count(WARN) == 1 and f"{WARN} is {state} and shows no runner heartbeat after the restart ({seen}; waited up to {wait} s)" in out
            and "systemctl --user status stackshot-minute.service" in out and "journalctl --user -u stackshot-minute.service" in out and "stackshot doctor" in out and "running (heartbeat seen)" not in out)
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN)
check("deploy.sh, minute unit restarted and its runner writes its heartbeat: the check passes and says so, after the health check and the republish; the deploy exits 0, no warning",
      rc == 0 and 0 <= out.find("healthz ok") < out.find("republished") < out.find("stackshot-minute.service: running (heartbeat seen)") and at(log, f"systemctl --user restart {M_}") < at(log, f"systemctl --user is-active {M_}")
      and WARN not in out, (rc, log, out[-400:]))
t0 = time.monotonic()
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="none", wait=3, timeout=45)
check("deploy.sh, the unit is active but the runner never writes a heartbeat: after the bounded wait ONE warning line names the unit, its state, that no heartbeat was seen, the wait and where to look, AND THE DEPLOY EXITS 0 (the server's steps are done, "
      "the republish before the warning)", rc == 0 and warned(out, "active", "no heartbeat record", 3) and 0 <= out.find("healthz ok") < out.find("republished") < out.find(WARN) and log.count(f"systemctl --user is-active {M_}") >= 2
      and time.monotonic() - t0 < 40, (rc, log, out[-600:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="stale", wait=3, timeout=45)
check("deploy.sh, a heartbeat that is older than the restart (a runner of before it) does not count: the same warning, naming its age, exit 0", rc == 0 and out.count(WARN) == 1 and "the last heartbeat is " in out and " s old, from before the restart" in out
      and "running (heartbeat seen)" not in out, (rc, log, out[-500:]))
t0 = time.monotonic()
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, active="failed", beat="none", wait=60, timeout=45)
check("deploy.sh, the unit is failed after the restart: the wait ends at once (not the full bound), the warning names the state, exit 0", rc == 0 and out.count(WARN) == 1 and f"{WARN} is failed and shows no runner heartbeat" in out
      and time.monotonic() - t0 < 30 and log.count(f"systemctl --user is-active {M_}") == 1, (rc, log, out[-400:], time.monotonic() - t0))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, active="inactive", beat="fresh", wait=3, timeout=45)
check("deploy.sh, a heartbeat but a unit that is not active (inactive): not running, the warning says the unit is not active, exit 0", rc == 0 and out.count(WARN) == 1 and f"{WARN} is inactive and shows no runner heartbeat" in out
      and "the unit is not active" in out and "running (heartbeat seen)" not in out, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, beat="none", wait=3, timeout=45)
check("deploy.sh rollback (the second step restarts the unit): the same check, the same warning, and the rollback still exits 0", rc == 0 and warned(out, "active", "no heartbeat record", 3) and out.count("rolling back") == 2, (rc, log, out[-400:]))
# a heartbeat has to be the unit's own: the pid of the record is the unit's MainPID or below it (`uv run` is the main process, the runner its child); a record of any other process (the old runner in its last seconds, the
# inline runner of a server) is not this unit's, however fresh
kids = []
def kid(): kids.append(subprocess.Popen(["sleep", "300"])); return kids[-1].pid
try:
    other = kid()
    rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="fresh", beatpid=other, wait=3, timeout=45)
    check("deploy.sh, a fresh heartbeat from another process than the unit's (its pid is not the MainPID and not below it): does not count, the warning names the pid, exit 0", rc == 0 and out.count(WARN) == 1
          and f"is from pid {other}, not from this unit" in out and "running (heartbeat seen)" not in out, (rc, log, out[-500:]))
    rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="fresh", mainpid=os.getpid(), beatpid=other, wait=3, timeout=45)
    check("...control: the same heartbeat counts when the pid is a child of the unit's MainPID (uv run keeps its own process as the parent of the runner)", rc == 0 and WARN not in out and "running (heartbeat seen)" in out, (rc, log, out[-500:]))
    rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="fresh", mainpid=0, wait=3, timeout=45)
    check("...and a unit with no MainPID (0) has no runner to match: the warning, exit 0", rc == 0 and out.count(WARN) == 1 and "not from this unit" in out, (rc, log, out[-400:]))
finally:
    for k in kids: k.kill(); k.wait()
# DEPLOY_MINUTE_WAIT=0 looks once and does not wait
t0 = time.monotonic()
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="none", wait=0, timeout=45)
check("deploy.sh with DEPLOY_MINUTE_WAIT=0 and no heartbeat: one look (one is-active), no wait, the warning says 0 s, exit 0", rc == 0 and warned(out, "active", "no heartbeat record", 0) and log.count(f"systemctl --user is-active {M_}") == 1
      and time.monotonic() - t0 < 30, (rc, log, out[-400:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="fresh", wait=0, timeout=45)
check("...and with a heartbeat already there, that one look passes", rc == 0 and WARN not in out and "running (heartbeat seen)" in out and log.count(f"systemctl --user is-active {M_}") == 1, (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, beat="fresh", wait="x y", timeout=45)
check("...and a DEPLOY_MINUTE_WAIT that is not a number falls back to the default and never fails the deploy", rc == 0 and "running (heartbeat seen)" in out, (rc, log, out[-300:]))
# at inline, and whenever the unit is not restarted here, there is no check and no wait
for what, files, kw in (("[runner] process reads inline (the unit goes)", ("stackshot/web/minute.py",), dict(runner="inline")), ("no unit installed", ("stackshot/web/minute.py",), dict(home=HOME_NONE)),
                        ("a change the unit does not restart for (the server's own unit file)", ("units/stackshot.service.in",), dict()), ("a standby", ("stackshot/web/minute.py",), dict(standby=True))):
    kw = {"home": HOME_MIN, **kw}; t0 = time.monotonic()
    rc, out, log, gone = real_deploy(files, beat="none", active="failed", wait=60, timeout=45, **kw)
    check(f"deploy.sh, {what}: no is-active, no wait for a heartbeat, no warning, exit 0", rc == 0 and not any("is-active" in l for l in log) and "heartbeat" not in out and WARN not in out and time.monotonic() - t0 < 30, (rc, log, out[-300:]))
# the rollback to a commit from before the unit: the unit is removed first and the older deploy.sh does the rest; if that fails the unit is gone with no runner in its place, and the step says so and what to run
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, predates=True, old_fails=True)
check("deploy.sh rollback to a commit from before the unit, the unit removed, then the older deploy.sh fails: the exit is nonzero (its own), and ONE warning says the unit is gone, the server may have no runner, and what to run (./install.sh units, "
      "systemctl --user restart stackshot.service)", rc == 1 and not gone and out.count("WARNING: the rollback to ") == 1 and "failed after stackshot-minute.service was removed, so the server may be running with no runner" in out and "./install.sh units" in out
      and "systemctl --user restart stackshot.service" in out and any(l.startswith("old deploy.sh ran") for l in log), (rc, log, out[-600:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_MIN, rollback=True, predates=True)
check("...control: when the older deploy.sh succeeds there is no such warning and the exit is 0", rc == 0 and "WARNING: the rollback" not in out and not gone, (rc, log, out[-300:]))
rc, out, log, gone = real_deploy(("stackshot/web/minute.py",), HOME_NONE, rollback=True, predates=True, old_fails=True)
check("...control: with no unit to remove, a failing older deploy.sh has no such warning (it was never this step's doing)", rc == 1 and "WARNING: the rollback" not in out, (rc, log, out[-300:]))

# ---- 18. the Codex review trial: `salamander codex-review <repo> <pr>` is started, in a user unit of its own, for a PR that is still open, and nothing about the release depends on it
CODEX_LINE = f"codex-review {R} 23"
def outcome(s): return str((s["rc"], s["msgs"], s["sleeps"], s["deploys"], s["order"], s["released"], s["lastgood"])).replace(str(s["dir"]), "@DIR")   # what a release is, apart from its log: none of it may move with the review (a scenario's own folder is in its messages)
def codex_wait(s, name, secs=20):   # the review stub is detached: wait for the file it writes last
    end = time.monotonic() + secs
    while time.monotonic() < end and not (s["dir"] / name).exists(): time.sleep(0.05)
    return (s["dir"] / name).exists()
def own_session(s):   # the review's process: a session leader of its own, no standard input, and open above fd 2 only its own script and its log (no lock, no pipe of the release, the log's tee included)
    return (len(s["codex_sid"]) == 2 and s["codex_sid"][0] == s["codex_sid"][1] and s["codex_in"] == "/dev/null"
            and all(t.endswith(("/bin/salamander", "codex-review-23.log")) for t in (x.split("=", 1)[1] for x in s["codex_fds"]) if t))
base = scenario("codex-base", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": "off"})
check("codex review off by SALA_CODEX_REVIEW=off: not started, no systemd-run, one log line says why, the release is as ever",
      base["rc"] == 0 and base["codex"] == [] and base["sysrun"] == [] and "codex review of PR #23 not started: SALA_CODEX_REVIEW=off" in base["log"] and base["deployed"], (base["rc"], base["codex"], base["log"]))
s = scenario("codex-open", merge="ok", checks="pending,pass")
lines = s["log"].splitlines()
at = next((i for i, l in enumerate(lines) if "codex review of PR #23 started" in l), -1)
check("an open PR: `salamander codex-review <repo> <pr>` is started once, with the repo and the PR number, and the log says so, naming the unit and the output file",
      s["rc"] == 0 and s["codex"] == [CODEX_LINE] and at > 0 and re.search(r"started in its own unit salamander-codex-review-23-\d+ \(output \S+/releases/codex-review-23\.log\); the release does not wait for it", lines[at]), (s["rc"], s["codex"], s["log"]))
check("...after the line that names the PR and before the wait for its checks, so the review runs while the checks are waited for",
      "PR #23:" in lines[at - 1] and next((i for i, l in enumerate(lines) if l.endswith(" checks pass")), -1) > at, lines[:6])
check("...it is started in a transient user unit of its own (systemd-run --user --quiet --collect --unit salamander-codex-review-<pr>-<epoch>), its output and errors appended to the review's log, and the command is salamander's by its full path",
      len(s["sysrun"]) == 1 and re.fullmatch(r"--user --quiet --collect --unit salamander-codex-review-23-\d+ -p StandardOutput=append:\S+/releases/codex-review-23\.log -p StandardError=append:\S+/releases/codex-review-23\.log "
                                             rf"(--setenv=\S+ )+{re.escape(str(s['dir']))}/bin/salamander codex-review {re.escape(R)} 23", s["sysrun"][0]), s["sysrun"])
check("...which has the PATH of the release and none of the SALA_ variables that are not set there", " --setenv=PATH=" in s["sysrun"][0] and "SALA_" not in s["sysrun"][0] and not any(l.startswith("SALA_") for l in s["codex_env"]) and any(l.startswith("PATH=") for l in s["codex_env"]), (s["sysrun"], s["codex_env"]))
check("...a session of its own, no standard input, no lock and no pipe of the release", own_session(s), (s["codex_sid"], s["codex_in"], s["codex_fds"]))
check("...and the release itself is the release of a PR with no review: same exit status, messages, waits, deploys, order and records",
      outcome(s) == outcome(base), (outcome(s), outcome(base)))
s = scenario("codex-env", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": "on", "SALA_CODEX_TIMEOUT": "77", "SALA_CODEX_BIN": "codex-x", "SALA_CONFIG": "/example/salamander.cfg", "XDG_STATE_HOME": "/example/state"})
check("the SALA_CODEX_* variables (SALA_CODEX_REVIEW included), SALA_CONFIG and XDG_STATE_HOME that are set in the release's environment are passed to the unit with --setenv, and reach the review",
      s["rc"] == 0 and len(s["sysrun"]) == 1 and all(f" --setenv={kv} " in s["sysrun"][0] for kv in ("SALA_CODEX_REVIEW=on", "SALA_CODEX_TIMEOUT=77", "SALA_CODEX_BIN=codex-x", "SALA_CONFIG=/example/salamander.cfg", "XDG_STATE_HOME=/example/state"))
      and "SALA_CODEX_HOME" not in s["sysrun"][0] and all(kv in s["codex_env"] for kv in ("SALA_CODEX_REVIEW=on", "SALA_CODEX_TIMEOUT=77", "SALA_CODEX_BIN=codex-x", "SALA_CONFIG=/example/salamander.cfg", "XDG_STATE_HOME=/example/state")), (s["sysrun"], s["codex_env"]))
for word in ("off", "OFF", "Off", "false", "FALSE", "False", "no", "NO", "0"):
    s = scenario(f"codex-off-{word}", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": word})
    check(f"SALA_CODEX_REVIEW={word} in the release's environment: not started, no unit, one log line says why, the release is the same as the one with the review off",
          s["codex"] == [] and s["sysrun"] == [] and f"codex review of PR #23 not started: SALA_CODEX_REVIEW={word}\n" in s["log"] and outcome(s) == outcome(base), (s["codex"], s["sysrun"], s["log"]))
for raw_word, trimmed in ((" off ", "off"), ("\toff", "off"), ("False \n", "False")):   # surrounding whitespace is ignored, as the config key's value is (str(v).strip())
    s = scenario(f"codex-off-ws-{trimmed}-{len(raw_word)}", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": raw_word})
    check(f"SALA_CODEX_REVIEW={raw_word!r} (surrounding whitespace): read as {trimmed!r}, not started, one log line says why",
          s["codex"] == [] and s["sysrun"] == [] and f"codex review of PR #23 not started: SALA_CODEX_REVIEW={trimmed}\n" in s["log"] and outcome(s) == outcome(base), (s["codex"], s["sysrun"], s["log"]))
s = scenario("codex-on-ws", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": " on "})
check("SALA_CODEX_REVIEW=' on ' is not an off word either: the unit is asked for (the stub cannot carry a value with spaces into the review itself, so only the call is read)",
      len(s["sysrun"]) == 1 and "not started" not in s["log"] and "started in its own unit" in s["log"], (s["sysrun"], s["log"]))
for word in ("on", "yes", "1"):
    s = scenario(f"codex-on-{word}", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": word})
    check(f"SALA_CODEX_REVIEW={word} is not an off word: the review is started, and the unit is given the value", s["codex"] == [CODEX_LINE] and len(s["sysrun"]) == 1 and f" --setenv=SALA_CODEX_REVIEW={word} " in s["sysrun"][0], (s["codex"], s["sysrun"]))
s = scenario("codex-nounit", merge="ok", checks="pending,pass", sysrun="fail")
check("no user manager (systemd-run fails): the review is started detached instead (setsid nohup), the log says which way, and the release is the same",
      s["rc"] == 0 and len(s["sysrun"]) == 1 and s["codex"] == [CODEX_LINE] and re.search(r"codex review of PR #23 started detached, no user unit \(systemd-run failed; output \S+/releases/codex-review-23\.log\); it stays in the release's cgroup, so a stop of the release ends it, and the release does not wait for it", s["log"])
      and outcome(s) == outcome(base), (s["rc"], s["sysrun"], s["codex"], s["log"]))
check("...a session of its own there too, no standard input, no lock and no pipe of the release", own_session(s), (s["codex_sid"], s["codex_in"], s["codex_fds"]))
for what, mode, rc_ in (("times out (status 124)", "timeout", "124"), ("needs the KILL after the grace (status 137)", "kill", "137")):
    s = scenario(f"codex-cut-{mode}", merge="ok", checks="pending,pass", sysrun=mode)
    check(f"a systemd-run call that {what}, after the unit did start: both starts happen (one systemd-run call, two codex-review starts, the unit's and the detached one), the log says so, and the release is the same",
          s["rc"] == 0 and len(s["sysrun"]) == 1 and s["codex"] == [CODEX_LINE, CODEX_LINE] and re.search(rf"codex review of PR #23: systemd-run did not answer within 20 s \(status {rc_}\), so unit salamander-codex-review-23-\d+ may have started; the review was also started detached \(a second start waits on the per-PR lock, then finds the done marker and posts nothing, unless the first review failed without one; output \S+/releases/codex-review-23\.log\); the detached one stays in the release's cgroup, so a stop of the release ends it, and the release does not wait for it", s["log"])
          and "not started" not in s["log"] and "started detached, no user unit" not in s["log"] and outcome(s) == outcome(base), (s["rc"], s["sysrun"], s["codex"], s["log"]))
s = scenario("codex-merged", viewstate="MERGED")
check("a PR already merged (a rerun): not started, and no line about it: the step is only for an open PR", s["rc"] == 0 and s["codex"] == [] and s["sysrun"] == [] and "codex review" not in s["log"], (s["codex"], s["log"]))
s = scenario("codex-closed", viewstate="CLOSED")
check("a PR that is closed: the release fails \"pr state\" as before and the review is not started", s["rc"] == 1 and s["codex"] == [] and s["sysrun"] == [] and "codex review" not in s["log"], (s["codex"], s["msg"]))
s = scenario("codex-no-salamander", merge="ok", checks="pending,pass", nosalamander=True)
check("salamander not on PATH: skipped, one log line says why, and the release is the same as the one with the review off",
      s["codex"] == [] and s["sysrun"] == [] and "codex review of PR #23 not started: salamander is not on PATH" in s["log"] and outcome(s) == outcome(base), (s["codex"], s["log"], outcome(s), outcome(base)))
s = scenario("codex-config-off", merge="ok", checks="pending,pass", codex_cfg="off")
check("[release] codex_review = false: skipped with a line that names the key; the release is the same", s["codex"] == [] and s["sysrun"] == [] and "codex review of PR #23 not started: [release] codex_review is off" in s["log"] and outcome(s) == outcome(base), (s["codex"], s["log"]))
for cfg, what in (("missing", "a config.py that predates the key"), ("crash", "a config.py that does not run")):
    s = scenario(f"codex-config-{cfg}", merge="ok", checks="pending,pass", codex_cfg=cfg)
    check(f"{what} reads as on: the review is started and the release is the same", s["rc"] == 0 and s["codex"] == [CODEX_LINE] and outcome(s) == outcome(base), (s["rc"], s["codex"], s["log"]))
s = scenario("codex-off-env-wins", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": "off"}, codex_cfg="crash")
check("SALA_CODEX_REVIEW=off is decided before the config is read", s["codex"] == [] and "SALA_CODEX_REVIEW=off" in s["log"], (s["codex"], s["log"]))
for how, kw in (("its own unit", {}), ("no unit", {"sysrun": "fail"})):
    s = scenario(f"codex-fail-{how[:2]}", merge="ok", checks="pending,pass", codex="fail", **kw)
    check(f"a review that errors out (output on both streams, exit 7), started in {how}: the release has the same result as without it, and the error stays in the review's file",
          s["codex"] == [CODEX_LINE] and outcome(s) == outcome(base) and "cannot start the review" in s["codex_out"] and "cannot start the review" not in s["out"], (s["rc"], s["codex"], s["codex_out"], s["out"][:300]))
    s = scenario(f"codex-hang-{how[:2]}", merge="ok", checks="pending,pass", codex="hang", **kw)
    hung_at_end = (s["codex_hung"], s["codex_done"])
    (s["dir"] / "codex.release").write_text("")
    check(f"a review that hangs, started in {how}: the release ends with the same result, long before the review could (it was still running when the release returned), and its output pipe was not held",
          s["codex"] == [CODEX_LINE] and hung_at_end == (True, False) and outcome(s) == outcome(base) and s["secs"] < 30, (s["codex"], hung_at_end, s["secs"], outcome(s)))
    check("...and when it is let go it ends by itself (nothing of it was left waiting on the release)", codex_wait(s, "codex.done"), os.listdir(s["dir"]))
s = scenario("codex-hang-red", merge="ok", checks="fail", codex="hang")
(s["dir"] / "codex.release").write_text("")
check("a release that fails (a red check) while a review hangs fails the same way as one with the review off",
      s["codex"] == [CODEX_LINE] and s["rc"] == 1 and "FAILED at checks" in s["msg"] and s["secs"] < 30, (s["rc"], s["msg"], s["secs"]))
s = scenario("codex-pick", raw=["--pick", "23"], pickfiles="server.py")
check("--pick (a dry run) starts no review", s["rc"] == 0 and s["codex"] == [] and s["sysrun"] == [], s["codex"])
s = scenario("codex-pick-files", raw=["--pick-files", "server.py"])
check("--pick-files (a dry run) starts no review", s["rc"] == 0 and s["codex"] == [] and s["sysrun"] == [], s["codex"])

# ---- 17. the picker's index after a deploy: [release] suitemap_warm_cmd is started on the deployed commit, detached and in a unit of its own, and is never a reason to fail or to delay a release
# The command is the test runner's (it sends the tree to the box that picks suites): release.sh runs nothing of the picker itself. `warmcmd` (tests/_release_harness.py) stands for it.
WARM = "warmcmd --git history"
WSHA = re.compile(r"--unit stackshot-suitemap-warm-([0-9a-f]{12}) .* --warm ([0-9a-f]{40})$")
wbase = scenario("warm-none", merge="ok", checks="pending,pass", extra={"SALA_CODEX_REVIEW": "off"})
check("no [release] suitemap_warm_cmd: nothing is started (no systemd-run call for it, no command), one log line says so, and the release is as ever",
      wbase["rc"] == 0 and wbase["deployed"] and wbase["warm_sysrun"] == [] and wbase["warm"] == [] and "suitemap warm: no [release] suitemap_warm_cmd is set, nothing started" in wbase["log"], (wbase["rc"], wbase["warm_sysrun"], wbase["log"]))
s = scenario("warm-ok", merge="ok", checks="pending,pass", warm=WARM, extra={"SALA_CODEX_REVIEW": "off"})
m = WSHA.search(s["warm_sysrun"][0]) if len(s["warm_sysrun"]) == 1 else None
check("a release that deployed starts the command once, in a transient user unit named for the deployed commit, which runs `release.sh --warm <that commit>` in the release's own folder, its output in a log of its own, a PATH that holds ~/.local/bin; the log says so",
      s["rc"] == 0 and s["deployed"] and m is not None and m.group(2) == s["deploys"][-1] and m.group(1) == m.group(2)[:12] and f"-p WorkingDirectory={s['dir']}/box " in s["warm_sysrun"][0]
      and f"-p StandardOutput=append:{s['dir']}/releases/suitemap-warm-{m.group(1)}.log " in s["warm_sysrun"][0] and "--setenv=PATH=" in s["warm_sysrun"][0] and "/.local/bin" in s["warm_sysrun"][0]
      and f"suitemap warm: started stackshot-suitemap-warm-{m.group(1)} for {m.group(2)[:7]}" in s["log"], (s["rc"], s["warm_sysrun"], s["deploys"], s["log"][-600:]))
check("…the command ran once, with the words the config gave it, in a checkout of the commit made for it (a worktree under the release's folder), holding none of the lock descriptors (6 to 9), and the unit's log says it ran and was done",
      len(s["warm"]) == 1 and re.fullmatch(rf"{re.escape(str(s['dir']))}/releases/suitemap-warm\.\w+/tree\|--git history", s["warm"][0]) and s["warm_fds"] == ["closed6", "closed7", "closed8", "closed9"]
      and "running warmcmd --git history in a checkout of it" in s["warm_log"] and s["warm_log"].rstrip().endswith(": done"), (s["warm"], s["warm_fds"], s["warm_log"]))
check("…the checkout is removed when the command is done: no folder is left under the release's folder, and git was asked to add the worktree detached at the commit and to remove it",
      s["warm_dirs"] == [] and "worktree add --quiet --detach " in s["git"] and re.search(r"worktree remove --force \S+/suitemap-warm\.\w+/tree", s["git"]) and m.group(2) in s["git"], (s["warm_dirs"], s["git"][-500:]))
check("…it is started after the deploy and the \"done:\" line (the deploy, the lock and the report are the release's own), and the release is the same as the one without the command",
      re.search(r"done: \w+, restarted[^\n]*\n[^\n]*suitemap warm: started", s["log"]) and outcome(s) == outcome(wbase) and lock_free(s), (outcome(s), outcome(wbase)))
s = fast("warm-live", merge="ok", heads=NEWER, warm=WARM)
check("a release that found its merge already live deployed nothing: the index is not started (the release that deployed it did)", s["rc"] == 0 and not s["deployed"] and s["warm_sysrun"] == [] and s["warm"] == [] and "suitemap warm" not in s["log"], (s["warm_sysrun"], s["log"]))
s = scenario("warm-fail-before", merge="ok", checks="fail", warm=WARM, extra={"SALA_CODEX_REVIEW": "off"})
check("a release that fails before the deploy starts nothing", s["rc"] == 1 and not s["deployed"] and s["warm_sysrun"] == [] and s["warm"] == [], (s["rc"], s["warm_sysrun"]))
for how, kw, line in (("fails (exit 7, output on both streams)", {"warmmode": "fail"}, "the command failed (status 7): nothing was kept, the next pick builds its own index"),
                      ("is not on PATH", {"warm": "nonesuch --x"}, "nonesuch is not on PATH: nothing run")):
    s = scenario(f"warm-cmd-{kw.get('warmmode', 'missing')}", merge="ok", checks="pending,pass", **{"warm": WARM, **kw}, extra={"SALA_CODEX_REVIEW": "off"})
    check(f"a command that {how}: one line in the unit's log says so, the checkout is gone, and the release is the same as the one without it (green, deployed, the same reports)",
          s["rc"] == 0 and outcome(s) == outcome(wbase) and line in s["warm_log"] and s["warm_dirs"] == [] and "boom" not in s["out"] and "boom" not in s["msg"], (s["rc"], s["warm_log"], s["warm_dirs"]))
s = scenario("warm-sysrun-fail", merge="ok", checks="pending,pass", warm=WARM, warm_sysrun="fail", extra={"SALA_CODEX_REVIEW": "off"})
check("no user manager (systemd-run fails): the command is started detached instead, once, the log says so, and the release is the same",
      s["rc"] == 0 and len(s["warm_sysrun"]) == 1 and len(s["warm"]) == 1 and re.search(r"suitemap warm: systemd-run failed \(status 1\); started detached, no user unit, for \w{7} \(output \S+/releases/suitemap-warm-\w{12}\.log\); the release does not wait for it", s["log"])
      and s["warm_log"].rstrip().endswith(": done") and outcome(s) == outcome(wbase), (s["rc"], s["warm_sysrun"], s["warm"], s["log"][-500:]))
for kind, rc_ in (("timeout", "124"), ("kill", "137")):
    s = scenario(f"warm-sysrun-{kind}", merge="ok", checks="pending,pass", warm=WARM, warm_sysrun=kind, extra={"SALA_CODEX_REVIEW": "off"})
    check(f"a systemd-run call that is cut at 10 s (status {rc_}) after the unit did start: the unit's one start is the only one (the command runs once), the log says it may have started, and the release is the same",
          s["rc"] == 0 and len(s["warm_sysrun"]) == 1 and len(s["warm"]) == 1 and re.search(rf"suitemap warm: systemd-run did not answer within 10 s \(status {rc_}\), so unit stackshot-suitemap-warm-\w{{12}} may have started; not started again", s["log"])
          and outcome(s) == outcome(wbase), (s["rc"], s["warm_sysrun"], s["warm"], s["log"][-500:]))
for cfg, what in (("missing", "a config.py that predates the key"), ("crash", "a config.py that does not run")):
    s = scenario(f"warm-cfg-{cfg}", merge="ok", checks="pending,pass", warm=WARM, warm_cfg=cfg, extra={"SALA_CODEX_REVIEW": "off"})
    check(f"{what} reads as no command: nothing is started and the release is the same", s["rc"] == 0 and s["warm_sysrun"] == [] and s["warm"] == [] and "suitemap warm: no [release] suitemap_warm_cmd is set, nothing started" in s["log"] and outcome(s) == outcome(wbase), (s["rc"], s["log"][-300:]))
s = scenario("warm-hang", merge="ok", checks="pending,pass", warm=WARM, warmmode="hang", extra={"SALA_CODEX_REVIEW": "off"})
alive = s["warm_alive"]
check("a command that does not end: the release is over and green while it still runs (the release does not wait for it), the unit's log is not at its end, and neither the deploy lock nor any other lock is held by it",
      s["rc"] == 0 and outcome(s) == outcome(wbase) and alive and "running warmcmd" in s["warm_log"] and ": done" not in s["warm_log"] and lock_free(s) and s["warm_fds"] == ["closed6", "closed7", "closed8", "closed9"], (s["rc"], alive, s["warm_log"], s["warm_fds"]))
wl, wlines, wdirs = warm_finish(s)
check("…and when it ends the unit says done and removes the checkout", wl.rstrip().endswith(": done") and wdirs == [] and len(wlines) == 1, (wl, wdirs, wlines))
s = scenario("warm-slow", merge="ok", checks="pending,pass", warm=WARM, warmmode="slow", extra={"SALA_CODEX_REVIEW": "off", "RELEASE_WARM_TIMEOUT": "2"})
check("a command that never ends is stopped after RELEASE_WARM_TIMEOUT: the log says so, the checkout is removed, nothing of it is left running, and the release is the same",
      s["rc"] == 0 and outcome(s) == outcome(wbase) and re.search(r": stopped after 2s", s["warm_log"]) and s["warm_dirs"] == [] and not s["warm_alive"], (s["rc"], s["warm_log"], s["warm_dirs"], s["warm_alive"]))
s = scenario("warm-direct", raw=["--warm", MERGE], warm=WARM)
check("release.sh --warm <commit> (what the unit runs) runs the command in a checkout of that commit and ends 0, whatever the command did",
      s["rc"] == 0 and len(s["warm"]) == 1 and f"suitemap warm {MERGE[:7]}: done" in s["out"] and s["warm_dirs"] == [], (s["rc"], s["out"][-300:], s["warm"]))
s = scenario("warm-direct-fail", raw=["--warm", MERGE], warm=WARM, warmmode="fail")
check("…a command that fails still ends it 0 (the unit is the release's own, a failed warm is a log line)", s["rc"] == 0 and f"suitemap warm {MERGE[:7]}: the command failed (status 7)" in s["out"], (s["rc"], s["out"][-300:]))
s = scenario("warm-direct-none", raw=["--warm", MERGE])
check("…with no command set it runs nothing and ends 0", s["rc"] == 0 and s["warm"] == [] and "no [release] suitemap_warm_cmd is set" in s["out"], (s["rc"], s["out"][-300:]))
for what, argv in (("no commit", ["--warm"]), ("a word that is not a commit", ["--warm", "main"]), ("a short word", ["--warm", "abc12"]), ("an extra argument", ["--warm", MERGE, "x"])):
    s = scenario("warm-usage-" + what.split()[-1], raw=argv, warm=WARM)
    check(f"release.sh --warm with {what}: usage, exit 2, the command is not run", s["rc"] == 2 and "usage: release.sh --warm <commit>" in s["out"] and s["warm"] == [] and s["warm_sysrun"] == [], (s["rc"], s["out"]))
s = scenario("warm-pick", raw=["--pick", "23"], pickfiles="server.py", warm=WARM)
check("--pick (a dry run) starts no index build", s["rc"] == 0 and s["warm_sysrun"] == [] and s["warm"] == [], s["warm_sysrun"])

# ---- 19. where deploy.sh runs: [release] deploy_ssh. Unset: here, as ever. Set to a host: the deploy and the rollback run there over `ssh -o BatchMode=yes <host>` (stub: tests/_release_harness.py SSH), its exit status is the deploy's,
# and this checkout follows to the same commit (a fast-forward, a reset --keep for a rollback), with the puller restarted only when its files changed. A follow that is skipped or fails (local changes, a failed git move) is a red release, the queue paused, the last good record untouched. The git stub's history is linear; RT_LOCALDIFF names the files of the move.
SSHH = "deploy-host"
SSH_FWD = f"-o BatchMode=yes -o ConnectTimeout=15 {SSHH} cd ~/stackshot && DEPLOY_TO={MERGE} ./deploy.sh"
SSH_RB = (f'-o BatchMode=yes -o ConnectTimeout=15 {SSHH} cd ~/stackshot && L="$(python3 stackshot/core/config.py state releases)/deploy.lock" && mkdir -p "$(dirname "$L")" && '
          f'exec flock "$L" env DEPLOY_LOCK_FILE="$L" DEPLOY_ROLLBACK=1 DEPLOY_TO={GOOD} ./deploy.sh')
def ssh_calls(s): return (s["dir"] / "ssh.log").read_text().splitlines() if (s["dir"] / "ssh.log").exists() else []
def restarts(s): return [l for l in ((s["dir"] / "systemctl.log").read_text().splitlines() if (s["dir"] / "systemctl.log").exists() else []) if " restart " in f" {l} "]
s = fast("ssh-unset", merge="ok", localdiff="stackshot/fleet/puller.py")
check("deploy_ssh unset: the deploy runs here (one deploy, pinned), no ssh call, this checkout is not moved and nothing is restarted: a one-box install is as before",
      s["rc"] == 0 and s["deploys"] == [MERGE] and ssh_calls(s) == [] and "merge --ff-only" not in s["git"] and "reset --keep" not in s["git"] and restarts(s) == [] and "over ssh" not in s["out"], (s["rc"], s["deploys"], ssh_calls(s), s["git"][-300:]))
s = fast("ssh-unset-rb", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", localdiff="stackshot/fleet/puller.py")
check("deploy_ssh unset: a rollback is also local, under the lock, no ssh call", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["locks"] == ["held", "held"] and ssh_calls(s) == [] and "reset --keep" not in s["git"], (s["rc"], s["deploys"], s["locks"], ssh_calls(s)))
s = scenario("ssh-cfg-missing", merge="ok", checks="pending,pass", deploy_ssh=SSHH, deploy_ssh_cfg="missing", extra={"SALA_CODEX_REVIEW": "off"})
check("a config.py that predates the key reads as unset: the deploy runs here", s["rc"] == 0 and s["deployed"] and ssh_calls(s) == [], (s["rc"], ssh_calls(s)))
s = fast("ssh-fwd", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py,docs/x.md")
check("deploy_ssh set: the deploy is one ssh call, BatchMode and a 15 s connect timeout, the host, the checkout there and DEPLOY_TO pinned to the merge; deploy.sh ran once, on the far side of it",
      s["rc"] == 0 and ssh_calls(s) == [SSH_FWD] and s["deploys"] == [MERGE] and "deploying on deploy-host over ssh" in s["out"], (s["rc"], ssh_calls(s), s["deploys"], s["out"][-400:]))
check("deploy_ssh set: this checkout fast-forwards to the merge, and only the puller is restarted (its file changed), nothing else",
      f"merge --ff-only --quiet {MERGE}" in s["git"] and restarts(s) == ["--user restart stackshot-puller.service"] and "  local: restarted stackshot-puller.service" in s["out"], (s["git"][-300:], restarts(s), s["out"][-400:]))
check("deploy_ssh set: the report still names what the deploy restarted on the server, not the local puller, and is green",
      len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "restarted: stackshot.service" in s["msgs"][0] and "stackshot-puller" not in s["msgs"][0], s["msgs"])
check("deploy_ssh set: the deploy ran under the lock of this release, and the lock is free after it", s["locks"] == ["held"] and lock_free(s), (s["locks"],))
s = fast("ssh-fwd-nopuller", merge="ok", deploy_ssh=SSHH, localdiff="docs/x.md,stackshot/web/render.py")
check("deploy_ssh set, the move touches none of the puller's files: the checkout follows and nothing is restarted here",
      s["rc"] == 0 and f"merge --ff-only --quiet {MERGE}" in s["git"] and restarts(s) == [] and "  local: this checkout is at 0106c0d" in s["out"], (s["rc"], restarts(s), s["out"][-300:]))
s = fast("ssh-fwd-unit", merge="ok", deploy_ssh=SSHH, localdiff="units/stackshot-puller.service.in")
check("deploy_ssh set, the puller's unit file changed: the puller restarts and the log says the unit is not reinstalled here",
      s["rc"] == 0 and restarts(s) == ["--user restart stackshot-puller.service"] and "the puller's unit file changed; ./install.sh puller here installs it" in s["out"], (restarts(s), s["out"][-300:]))
s = fast("ssh-fwd-restartfail", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/client.py", restart_rc="1")
check("deploy_ssh set, the puller cannot be restarted: one WARNING line, the release is still green (the server is live)", s["rc"] == 0 and "WARNING: stackshot-puller.service could not be restarted here" in s["out"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS), (s["rc"], s["out"][-300:], s["msgs"]))
s = fast("ssh-fwd-dirty", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", dirty=" M release.sh")
check("deploy_ssh set, this checkout has a local change: it is not moved and not restarted, the server is live and the release is red: one report that says the server is live at the merge and this checkout could not follow, and `release.sh queue --resume`",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "merge --ff-only" not in s["git"] and restarts(s) == [] and len(red(s)) == 1 and "FAILED at deploy" in red(s)[0] and "(deploy-host) is live at 0106c0d but this checkout could not follow" in red(s)[0]
      and "has local changes, so it was not moved to 0106c0d" in red(s)[0] and "release.sh queue --resume goes on once the checkout is clean" in red(s)[0] and "merged, not live" not in red(s)[0] and lock_free(s), (s["rc"], s["deploys"], s["msgs"], s["out"][-400:]))
check("deploy_ssh set, the follow was skipped: nothing is recorded as the last good commit (the record is still the old one), the release does not go on to watch main's run, and the report is not green",
      s["lastgood"] == GOOD and "main's tests" not in s["out"] and not any(m.endswith(GREEN_ARGS) for m in s["msgs"]), (s["lastgood"], s["out"][-300:], s["msgs"]))
s = fast("ssh-fwd-movefail", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", move_fail="1")
check("deploy_ssh set, the fast-forward here fails: no puller restart, the same red report (the server is live at the merge, this checkout could not follow, the exit status), nothing recorded as last good",
      s["rc"] == 1 and len(red(s)) == 1 and "is live at 0106c0d but this checkout could not follow" in red(s)[0] and "could not be moved to 0106c0d (exit status 128)" in red(s)[0] and restarts(s) == [] and s["lastgood"] == GOOD and not any(m.endswith(GREEN_ARGS) for m in s["msgs"]),
      (s["rc"], s["out"][-300:], restarts(s), s["msgs"]))
s = scenario("ssh-fwd-dirty-4d", merge="ok", checks="pending,pass", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", dirty=" M release.sh", extra={"SALA_CODEX_REVIEW": "off"})
check("deploy_ssh set, the deploy waited for main's tests (no fast deploy) and this checkout cannot follow: the same red report, not green",
      s["rc"] == 1 and s["deploys"] == [s["deploy_to"]] and len(red(s)) == 1 and "is live at" in red(s)[0] and "could not follow" in red(s)[0] and not any(m.endswith(GREEN_ARGS) for m in s["msgs"]) and "merge --ff-only" not in s["git"], (s["rc"], s["deploys"], s["msgs"], s["out"][-400:]))
s = fast("ssh-fail", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", ssh_fail="1")
check("deploy_ssh set, the ssh fails (255): the deploy failed, merged and not live, with ssh's own last line; this checkout is not moved and nothing is restarted",
      s["rc"] == 1 and s["deploys"] == [] and len(red(s)) == 1 and "Connection timed out" in red(s)[0] and "merge --ff-only" not in s["git"] and restarts(s) == [] and lock_free(s), (s["rc"], s["deploys"], s["msgs"], s["git"][-200:]))
s = fast("ssh-deploy-fail", merge="ok", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", deploy_fail="1")
check("deploy_ssh set, deploy.sh itself fails over there: its exit status and last line come back (red), and this checkout is not moved",
      s["rc"] == 1 and s["deploys"] == [MERGE] and len(red(s)) == 1 and "healthz did not answer" in red(s)[0] and "merge --ff-only" not in s["git"] and restarts(s) == [], (s["rc"], s["deploys"], s["msgs"], s["git"][-200:]))
s = fast("ssh-badhost", merge="ok", deploy_ssh="-oProxyCommand=evil")
check("deploy_ssh that is not a host name (an option): the deploy is refused before any ssh call, merged and not live",
      s["rc"] == 1 and ssh_calls(s) == [] and s["deploys"] == [] and len(red(s)) == 1 and "is not an ssh host name" in red(s)[0], (s["rc"], ssh_calls(s), s["msgs"]))
s = fast("ssh-rb", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py")
check("deploy_ssh set, main fails: the rollback is a second ssh call, DEPLOY_ROLLBACK=1 and DEPLOY_TO the last good commit, inside a flock of the far side's own deploy lock",
      s["rc"] == 1 and ssh_calls(s) == [SSH_FWD, SSH_RB] and s["deploys"] == [MERGE, f"rollback {GOOD}"], (s["rc"], ssh_calls(s), s["deploys"], s["out"][-500:]))
check("deploy_ssh set, main fails: deploy.sh over there saw its lock held (the far side's, which it checks), and no lock is left held on either side",
      s["locks"] == ["held", "held"] and (s["dir"] / "remote/releases/deploy.lock").exists() and file_free(s["dir"] / "remote/releases/deploy.lock") and lock_free(s), (s["locks"], file_free(s["dir"] / "remote/releases/deploy.lock")))
check("deploy_ssh set, main fails: this checkout goes back to the last good commit with a reset --keep (never a hard reset), the puller restarts, and the red report is as for a local rollback",
      f"reset --keep --quiet {GOOD}" in s["git"] and "reset --hard" not in s["git"] and len(restarts(s)) == 2 and "FAILED at main's tests: rolled back to 600d000" in red(s)[0], (s["git"][-300:], restarts(s), red(s)))
s = fast("ssh-rb-fail", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", rollback_fail="1")
check("deploy_ssh set, the rollback over there fails: the red report says the rollback failed with deploy.sh's last line, and this checkout is not reset",
      s["rc"] == 1 and "the rollback to 600d000 failed" in red(s)[-1] and "rollback: healthz did not answer" in red(s)[-1] and "reset --keep" not in s["git"], (s["rc"], red(s), s["git"][-200:]))

s = fast("ssh-rb-dirty", merge="ok", main="fail", heads=f"{BASE},{BASE},{MERGE}", deploy_ssh=SSHH, localdiff="stackshot/fleet/puller.py", reset_fail="1")
check("deploy_ssh set, main fails, the rollback ran over there but this checkout cannot follow (the reset fails): the server is rolled back, the report is red as for a rollback and says this checkout could not follow, and the queue pause is the rollback's own",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0] and "but this checkout is at" in red(s)[0] and "could not be moved to 600d000 (exit status 128)" in red(s)[0]
      and "release.sh queue --resume goes on once it is clean" in red(s)[0] and "main still holds the failing merge" in red(s)[0] and lock_free(s), (s["rc"], s["deploys"], red(s)))

long = [f"{n} ({k})" for n, k in POLLS if k > MAX_POLLS]
check(f"no scenario polls more than {MAX_POLLS} times (one that waits main's run out to the 3 h cap: pass RELEASE_CAP_MAIN, as most do)", not long, long)

finish()
