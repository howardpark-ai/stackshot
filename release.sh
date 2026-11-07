#!/usr/bin/env bash
# release.sh — merge a PR and deploy it, detached: the builder (example-engineer) starts it and leaves, and the result comes back as one
# stackshot message to the project. Runs on the server box, in the production checkout.
#
# How to run it (what a session does):
#   - Run one plain `release.sh N` per command. It starts its own unit and returns at once.
#   - Wait for its log (`<state>/releases/pr-N.log`, a line with ` done: ` or ` FAILED `) in a run_in_background shell with `timeout`.
#   - Never chain waiters that start the next release when the previous log says done: a failed step stops every later one with no report.
#   - For several PRs, queue them: `release.sh queue N [N...]`. Each queued release starts the next one itself when it is deployed (it then only waits on main's run),
#     a queued PR that fails before its merge (its checks, a conflict) is reported and skipped, and a failed main run for a merged one pauses the queue (THE RELEASE QUEUE below).
#   - With the merge queue in mode on (host file; THE MERGE QUEUE, ON below), two or more queued PRs (at most 4 at a time, release.sh's own number) are released together by the queue (`release.sh --group N N...`, which the release queue starts itself):
#     one deploy and one `done:` line per PR; one queued PR is released alone, as without the queue.
#   - A PR whose branch is behind main is brought up to date first (gh pr update-branch, a merge), its own tests are waited for on the new head, and it deploys at the merge;
#     when that merge conflicts only on the generated tests/tool_text.snapshot.json, release.sh regenerates it itself and pushes (2a' below);
#     main's full run never blocks a release, it follows the deploy. Watch it with `release.sh --status N`: the log's newest line says what is waited for.
#   - A PR behind main whose changed files and main's new commits' changed files share no test group (tools/retest_skip.py, from the suite map main's run publishes) is NOT retested:
#     it merges with its last green checks and deploys at the merge; the log and the report name the two file sets (2a'' below). Anything else is retested, as above.
#   - Auto mode also refuses a loop of release.sh runs.
#
#   ./release.sh <pr> [--recycle | --no-recycle]
#                                 start: a transient user unit (stackshot-release-<pr>) runs the steps below; prints the unit
#                                 and the log path, returns at once. After a green deploy the release picks what the running agent
#                                 sessions need from the files the merged PR changed (THE SESSION PICK below; the table and the code
#                                 behind it: docs/session-reload.md): nothing, a notice or a recycle, the highest need winning, except that a recycle with a notice among the files does both. A
#                                 recycle: the open items anchored to this PR wait for one (client.py recycle-due --pr), never a new
#                                 item; with none anchored, the fleet tool is asked for one once the box is idle ([fleet]
#                                 recycle_when_idle; unset: nothing is asked). A notice: [fleet] notice_cmd (stopped after 60 s, which counts as not sent) is run with one
#                                 argument appended, "<title> — <summary>" (newlines and tabs as spaces, cut to 400 characters) (unset: the log says no notice command is set, and the
#                                 release goes on). --recycle forces a recycle whatever the files say; --no-recycle forces
#                                 nothing. A change to a tool or its parameters is a notice, never a recycle: a recycle does not
#                                 deliver it, claude.ai refreshes its cached tool list on its own within about a day.
#                                 The log and the one report say what was picked and from which files
#   ./release.sh --pick <pr>      dry run: print the pick for that PR's changed files (one GitHub read), and each file's need; nothing else
#   ./release.sh --pick-files <file>...
#                                 dry run: the same for the files named (paths relative to the checkout); no GitHub call
#   ./release.sh --status [<pr>]  the unit's state and the log's tail (the latest release when no pr is given)
#   ./release.sh queue N [N...]   add PRs to the release queue (<paths.state>/releases/queue), in order; a PR queued already stays where it is. A PR with a failing, cancelled or timed-out check row is refused (exit 1, the rows printed, nothing queued), and so is one whose rows cannot be read. When no queued release is
#                                 running (and the queue is not paused) the first one starts at once, as `release.sh N`, and stays in the queue until it is deployed (a killed one is still
#                                 listed, and --resume starts it again); after that each queued release starts the next one when it reaches "deployed" (the point after which it only
#                                 waits on main's run). A queued PR that fails before its merge (its checks fail, it conflicts, it is closed, a lock is not had) is reported as any failure
#                                 is, and skipped: the queue goes on with the next. A failure after the merge (main's run failing for it, merged and not deployed or rolled back; its
#                                 deploy failing) of a release the queue started pauses the queue: no new release starts, a release the queue had started already but not merged stops at
#                                 "queue paused" and stays first in the queue, the PRs a rollback took out stay merged on main and are named in the report (the next release's merge deploys them), the rollback and the red report run as always. A plain
#                                 `release.sh N` that fails pauses nothing, and neither does a main run that could not be read. A queued release picks what the sessions need from its PR's files, as any release does.
#   ./release.sh queue --list     the queued PRs in order (the running one first), whether the queue is paused and why, and the queued release that is running
#   ./release.sh queue --drop N   take PR N out of the queue (a release already started is not stopped)
#   ./release.sh queue --resume   after a pause, once main is fixed: the queue goes on (the next queued PR starts unless a queued release is still running)
#   ./release.sh --run <pr> [--recycle | --no-recycle]
#                                 the steps themselves (what the unit runs):
#                                 1. the PR is open and mergeable; 2. its checks pass (waits up to 50 min for a pending or queued one: the CI runners take one job at a time);
#                                 2a. BEHIND MAIN? (the owner's rule: main's full run never blocks a release): when the checks have passed and main's tip (fetched
#                                 with the PR head) is not in that head's history, the branch is brought up to date instead of waiting for main's full run (a long run; in a burst of PRs only the first would be up to date). One release at a time does this, under an exclusive flock on
#                                 <paths.state>/releases/update.lock (UPDATE_LOCK_WAIT, by default 3 rounds x (50 min + 3 min) + the 15 min of the deploy lock = 174 min; past it the
#                                 release fails "update lock" before anything is merged), taken before the deploy lock and held up to the merge, so releases that both need an
#                                 update take turns and do not keep invalidating each other's. A PR that is up to date from the start takes no update lock (it does not wait behind
#                                 another release's CI), so its merge can still land on main during a round: the updating release then takes another round, or after 3 the old
#                                 path, which is safe. When it has the lock it reads the PR again: closed fails it, a head pushed meanwhile has its tests waited for, and a branch that is
#                                 up to date by then is not updated. A round: `gh pr update-branch`
#                                 (main is merged into the branch; no rebase, no force push); the PR head is read every 10 s until it moves (up to 3 min); then the PR's own
#                                 tests on the new head are waited for (polled every POLL_PR s, 60, for up to 50 min like step 2, with a "waiting for the PR's tests" line in the log every 5
#                                 min, which is what --status shows; a failed or cancelled check fails at once, whichever it is; a pass needs the `suites` check to be reported and,
#                                 in GitHub's check-runs of that very commit, completed and successful: a pass still read from the old head is pending); then main's tip is looked at again: if it moved meanwhile
#                                 (another merge) the next round updates again and waits again, 3 rounds at most (RELEASE_UPDATE_ROUNDS), then the old path (3b) with the
#                                 reason in the log. An update-branch that errors (a conflict with main) fails the release "update-branch", and tests that fail on the
#                                 new head fail it "pr tests"; neither falls back to the old path. The merge is pinned to the tested head, which is the updated head. The update lock is let go
#                                 when the merge is made, so the next release updates on top of it while this one deploys;
#                                 2a'. A CONFLICT THAT IS ONLY THE GENERATED TOOL-TEXT SNAPSHOT is mended instead of failing (regen_snapshot, tools/snapshot_regen.py): two PRs that both change tool text
#                                 conflict on tests/tool_text.snapshot.json and on nothing else, and the by-hand fix is always the same. When update-branch errors, or the first look at the PR says
#                                 CONFLICTING, this fetches main and the PR head (git only: no GitHub call), merges main into the head in a temporary worktree of its own (removed on every way out), and,
#                                 only if the snapshot is the SOLE conflicted path, takes main's snapshot, runs `python3 tools/tool_text.py update` then `check`, commits the merge and pushes it to the PR
#                                 branch (a plain push: a branch its author pushed to meanwhile is refused, never forced). The log says so in one line, the PR head is read until it moves, and the wait for
#                                 the PR's tests on the new head goes on as after update-branch. Any other conflicted path, a clean local merge, a failed update or check, a refused push, a cross-repository PR
#                                 or no helper: the release fails exactly as before, the reason in one more log line. At most RELEASE_REGEN_MAX (2) times in a release, so it cannot loop;
#                                 2a''. NO RETEST WHEN NOTHING COULD DIFFER (skip_retest, tools/retest_skip.py): before 2a updates the branch, this asks whether the retest could find anything the PR's
#                                 first run did not. The PR's changed files (merge base..head) and the files main's new commits changed (merge base..main's tip) are read against the suite map main's
#                                 measured run publishes (the artifact `suitemap` of tests.yml: for each suite, the files and the Python files it reads). The retest is skipped only when no suite reads
#                                 both a file the PR changed and a file main changed, no file is changed by both sides, and every changed file is known to the map. A map that is missing, unreadable,
#                                 older than 2 days, of a commit that is not in main's history (or published by a run of another commit), or with a suite that has no clean measurement (a suite that failed only when measured keeps its earlier clean one as a carry, which counts unless it is older than 2 days or of a commit outside main's history; the drift is counted from its commit), an unknown file (new since the map),
#                                 a file changed since the map's commit (it counts as main's side), a diff that adds or changes an import, a call that loads, runs or reads a file or a string that looks like a
#                                 repository path (the map cannot show a dependency a change adds), or, on either side, a change to the CI workflow, release.sh, deploy.sh, the test runner (tests/run-suite,
#                                 tests/pyproject.toml, tests/uv.lock, tests/suitemap.py), the map's own tool, any *.lock file, a `# /// script` block, or the files of the checks outside the suites (tool-text,
#                                 clean-text): the retest, exactly as 2a, the reason in the log ("retest needed: ...").
#                                 When it skips, no update-branch and no wait: the release merges the PR head its checks passed on (pinned, as always) and, under the same conditions as 2c, deploys at the merge
#                                 (a merge release.sh made this way is not entered in the fast-ok ledger: the tree was not the one tested). The decision is made again under the deploy lock, on the tip then
#                                 (main may have moved), and the merge must still be exactly the tip and the head (else the old path). The log line and the report name both file sets. Main's full run
#                                 after the deploy checks everything and rolls back as ever. RELEASE_SKIP_DISJOINT=0 turns it off; RELEASE_SUITEMAP=<file> reads a map from a file (the tests);
#                                 2b. the deploy lock: merge and deploy run under an exclusive flock on <paths.state>/releases/deploy.lock,
#                                 waited for up to 15 min (DEPLOY_LOCK_WAIT, seconds); past that the release fails "deploy lock" before
#                                 anything is merged (simple pushes should not wait behind another
#                                 heavy release). Two releases never deploy at once, and the wait for checks happens before and outside
#                                 the lock, so no release waits for another one's CI. The lock is released when deploy.sh returns;
#                                 fd 9 is closed for every child (a service a deploy leaves behind never inherits it). Only release.sh
#                                 takes it: a deploy.sh run by hand does not. Every merge is pinned: --match-head-commit <the head the
#                                 checks ran on: the PR head read at the start, or the updated head after 2a>, so a push after the checks cannot ride in on the merge;
#                                 2c. UP TO DATE?: still under the lock, main's tip, fetched
#                                 together with the PR's head, must be an ancestor of the head the checks ran on (git merge-base --is-ancestor;
#                                 GitHub's mergeStateStatus says BEHIND only when the branch rule "require branches to be up to date" is on,
#                                 so it is not something to rely on). A head that contains main's tip merges into exactly the tree its checks
#                                 ran on, so those checks are the merge's checks. A branch that is behind was brought up to date in 2a, and the head it is checked on is the updated one. The fast path
#                                 also needs (fast_gate): (a) the live checkout is AT main's tip, so everything on main is deployed already and
#                                 nothing merged-and-waiting (an old-path release's merge, a commit just rolled back) rides along; behind it
#                                 only by commits that docs-merge.sh itself accepts (docs, comments, runner settings; they are never deployed
#                                 by a release, so the live checkout stays behind after each one) counts as at the tip: its allow-list is read
#                                 out of that script (DOCS_MERGE_SCRIPT, default [paths] docs_merge_script; one list, not
#                                 two; unreadable: fails closed). Each commit's diff is read unquoted with fixed prefixes (core.quotePath=false,
#                                 --no-ext-diff --no-renames), and the checker's exit code is not trusted alone: its summary line must say
#                                 files=N refused=0 with N the number of "diff --git" headers (a quoted header it cannot parse, or a checker that
#                                 does not know the subcommand, otherwise reads as docs-only).
#                                 RIDE-ALONG (main's full run never blocks a release:
#                                 one release on the old path left the live checkout behind main, so every later release failed (a) too and waited for a main run):
#                                 a merge that release.sh made on a passing PR check counts as at the tip as well. When a release merges a PR whose head contained main's tip (2c) and
#                                 main's tip is then exactly the merge of that tip and the head (merge_commit), the merge commit goes into the ledger <paths.state>/releases/fast-ok.json
#                                 (RELEASE_LEDGER; written whole by temp file and rename, under flock on fast-ok.json.lock, at the merge, under the deploy lock), whether this release
#                                 deploys at the merge or, (a) or (b) failing, takes the old path. (a) then passes when every first-parent commit between the live HEAD and main's tip is such a
#                                 ledger merge (the commits it brings in are its PR's own, whose checks ran on that head) or docs-only as above; the ledger merges need no docs-merge.sh. A merge
#                                 of the old path because its branch was not up to date (3 update rounds used up, an update that could not be read) is not in the ledger: it merged on checks
#                                 that did not run on main's tip, so it still blocks (a) until its own release deploys it. The ride-along deploy contains the ledger merges and main's run for its
#                                 merge covers them; (b) and the pending-verify records still apply to the whole range. A failed main run removes what it takes out: a rollback drops the failing
#                                 merge and every merge between the last-good commit and the live checkout from the ledger before it resets (so a rolled-back commit, still on main, never rides
#                                 along), and an old-path release whose covering run failed drops its merge; when the ledger cannot be edited (the lock, the write) the whole file is removed, and
#                                 one that is not a ledger (unparseable, wrong shape) is never written over and never trusted: (a) then counts docs-only merges alone, as before. Entries
#                                 older than 30 days, and all but the newest 200, are dropped on a write, and so is every entry that is an ancestor of the live HEAD (deployed already) or of the last-good
#                                 commit; (a) counts only entries that descend from the live checkout. An old-path release whose own run fails while its merge is LIVE (a release rode along on it and
#                                 deployed on top of it) is not "merged, not deployed": it takes the rollback of a fast deploy, with the rider, and reports "LIVE via ride-along, rolled back to <sha>".
#                                 Known limit: a merge that is never recorded (the old path because its branch was not up to date) blocks the releases behind it until its own release deploys it. (b) no commit after the last-good one has a FAILED run on main (read from
#                                 GitHub's list of runs, page after page, up to 10 of 100, until a run at or before the last-good commit; empty,
#                                 crashed or never reaching it: unreadable, the old path; so is a run in the range cancelled after its job started,
#                                 while one cancelled while queued was replaced and does not count; main_green, which only looks for a run that covers the merge, skips both); a pending run does not count: back-to-back releases
#                                 stay fast, and if the first one's run fails both are rolled back; and a last-good commit to roll back to
#                                 ($LOGDIR/last-good; first use: the live HEAD, when its run on main passed). The record is read, compared and
#                                 written under flock on last-good.lock; one it cannot read (not a sha, a commit this checkout does not know) is
#                                 never overwritten, it is told to the keeper and the old path runs. When any condition fails the old path
#                                 (3b) runs, and the log says which;
#                                 3. `gh pr merge --merge` (no --delete-branch); when that call errors (a GitHub 504 after the
#                                 merge went through), the PR's state is read again for up to
#                                 about 50 s: MERGED carries on as a clean merge (the error goes into the report),
#                                 anything else fails "merge" with the original error. Then the head branch: the open PRs based on it
#                                 (`gh pr list --base`) are retargeted to main (`gh pr edit --base main`, one log line each), and the branch is
#                                 deleted best-effort; a PR that cannot be listed or retargeted keeps the branch and the log says why
#                                 (GitHub closes a PR whose base is deleted), the release goes on;
#                                 3a. FAST PATH, up to date, and origin/main's tip is the merge of the tip that was checked and the pinned head:
#                                 4. ./deploy.sh pinned to the merge commit at once (DEPLOY_TO; units, restarts, /healthz), the lock let go, the
#                                 session pick (its recycle or notice) and the one report (green) follow the deploy, "main's full run follows"; then main's run for
#                                 the merge commit is waited for (main_green post: a run on it or on a later commit that contains it, see "Main's tests" below), outside the lock. Just before deploy.sh
#                                 runs (production changes at its fast-forward, and the restarts and healthz take up to 180 s) a pending-verify
#                                 record (commit, PR, time) goes under <paths.state>/releases/pending-verify/, its flock held by this process; a
#                                 failed deploy clears it with its red report, and it is removed when the watch concludes. A release that is killed in between leaves it with the
#                                 lock free, and the next release to start (before anything else) reads that commit's main run once: pass ->
#                                 last-good; fail -> the rollback and red report a live watch would make, for that PR (the record stays unless
#                                 the rollback reached a verdict: a lock timeout keeps it); still pending, only cancelled runs, or no run found / GitHub
#                                 unreadable (never a verdict) -> kept, and no fast path until it is read (after two hours: unknown, a red report). Records are taken oldest deploy first. Fail, unknown and pending refuse the fast path for the release that found them. Main's run for the merge commit itself:
#                                   pass: "main's tests passed on <sha>" in the log, the commit goes to last-good, the check that it is still
#                                   in the live checkout and the record done under the deploy lock (a rollback cannot land between them); a note on the run (a selection
#                                   miss, a suite that failed only when measured) goes to the keeper as a second message;
#                                   fail: ROLLED BACK. Under the lock again, ./deploy.sh goes back to the last-good commit (DEPLOY_ROLLBACK=1
#                                   DEPLOY_TO=<it>, run by this script with the lock held; deploy.sh checks it, and runs the good tree's own
#                                   deploy logic) and the red report is "FAILED at main's tests: rolled back to <sha>", which reaches the builder.
#                                   It names the failing run, the merges since the last good commit when there are several, the unit and timer
#                                   files the rolled-back commits added (left installed, to disable by hand), whether a recycle had been flagged,
#                                   and that a rollback does not undo data or state changes the commits made. Every other merge between the last good commit
#                                   and the live checkout is taken out too, those deployed before the failing one (their runs still waiting)
#                                   and those on top: each PR gets its own red message ("rolled back with #A's failure; it is merged but not live;
#                                   it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green") and a marker, so that its own run, when it ends, says "passed, but not
#                                   live" (and does not touch the last-good record: it also needs the merge to be in the live checkout,
#                                   checked with git, not by the marker alone). Not rolled back, and the report says so: the live checkout no
#                                   longer contains the failing commit; a newer commit whose run on main passed contains it (never roll back past
#                                   a newer good commit); no readable last-good commit. A run that could not be read (no run on a commit that contains the merge
#                                   passed or failed, a cancelled run counting as none) within WAIT_MAIN of a covering run's start or CAP_MAIN of the merge
#                                   is not a failure: deployed, not rolled back, red report (check by hand). Main keeps the failing merge: fix forward or revert;
#                                 3b. OLD PATH (still not up to date after the 3 update-branch rounds of 2a, (a) or (b) above, no readable last-good commit, a fetch that failed, or a tip that moved between the check and
#                                 the merge): main's tests. A PR runs only the suites its change reaches, so
#                                 the deploy waits for a run on main that covers the PR's merge commit M, where every suite runs: a run on M or on
#                                 a later commit that contains it (several PRs merged close together: a run cancelled by a newer push is
#                                 not a failure, and the run on a later commit decides); up to WAIT_MAIN (90 min by default, for a slow run on a loaded host) counted from when that run starts, and 3 h at most
#                                 from the merge; its suites failing stops here, merged and not deployed (main_green below, the rule in full). The wait looks at main's runs every POLL_MAIN s (60) and the reads are shared between the releases on the box for GH_TTL s (45), so six releases waiting on one run cost what one does. The deploy lock is let go for that
#                                 wait and taken again for the deploy, so a release waiting on main never holds another one's deploy (a lock still
#                                 held after 15 min then fails "deploy lock": merged, not deployed). 4. ./deploy.sh pinned to the commit main's
#                                 tests passed on (DEPLOY_TO: fast-forward to the newest commit that contains M whose run passed, never to a tip with no passing run);
#                                 5. one message to projects/example: green or red, the PR, the commit, what was restarted, what the session
#                                 pick chose and from which files, the log path.
#                                 A green one goes with --release green (the turn rule's second build): the
#                                 server logs it, rules it merged as `stackshot (auto)`, comments on the items anchored to the PR
#                                 and leaves it on the routing page (a project the router is not live for: lists it in the keeper's
#                                 daily digest); a red one, or a green one whose recycle could not be asked for, whose notice command
#                                 failed or whose changed files could not be read, is delivered to the project, where the router rules it, as before. A note on main's run makes the report go to the keeper
#                                 instead of green (the old path), or goes to the keeper as the second message (the fast path).
#                                 6. once main's full run passed on the merge and it is recorded as the last good commit (the fast path after its watch;
#                                 the old path after its deploy; a pending-verify record read as passed), `client.py released --pr <url> --sha <merge>`.
#                                 The server refuses, writing nothing, unless the PR is merged and its merge commit is in $LAST_GOOD and in the
#                                 checkout's HEAD, so a main run still going or a rollback settles nothing. Only a release step counts: one that says it
#                                 releases the PR ("release PR #N", "release #N", or "release" before its URL; never "not release", "don't release" or
#                                 "pre-release"), on an item anchored to the PR or naming its URL. A step is a pure release only when nothing follows
#                                 the release phrase or only a short parenthetical naming nothing to do ("(in its turn)", "(after #7)"); anything
#                                 else after it is a follow-up, so nothing is ticked or closed and the mover is told once. A step that only mentions
#                                 the PR (investigate, review, verify, another repository's PR) is never ticked and never closes the item. An item
#                                 whose only open steps are that release is closed, outcome done, by the server, with no session turn; one with any
#                                 other open step gets the release step ticked and its mover one real notice (none when every other open step
#                                 releases another PR; a rerun never sends it twice):
#                                 "PR #N is live; its step is ticked; the item's other open steps remain". Held items and items whose needs name a decision or a session other than the mover are left alone, the log
#                                 saying why. A call that fails or is refused is a log line.
#
# THE MERGE QUEUE, SHADOW (docs/mq.md in salamander). salamander has `salamander mq`, a merge queue of its own for a repository that cannot use GitHub's (one that cannot use it). It is switched per host by the host file ~/.config/mergequeue/<owner>__<repo>.toml (XDG_CONFIG_HOME honoured), key `mode = "off" | "shadow" | "on"`. No file, or `off`, is today's behaviour exactly:
# nothing of the queue is called (the one thing read is the host file itself, and only when it exists). The repository's own rules are .github/mergequeue.toml (the check that must pass is `suites`, tests.yml's job on a `queue/**` push; branch prefix queue/main/).
#   shadow: right after this release has read the PR (open and mergeable, before it waits for the PR's checks) it also runs `salamander mq add <pr>`, under a short timeout (RELEASE_MQ_ADD_TIMEOUT, 20 s).
#           The queue builds each waiting PR as an entry on the ones ahead of it (a chain), tests the entries with the repository's own workflow and journals what it WOULD merge; in shadow it merges nothing, posts no status and no
#           comment, so the old path stays the only thing that merges and deploys. The PR is added BEFORE the old path decides, on purpose: once the old path has merged a PR the queue can no longer
#           test it (its first read finds it merged). When this release ends (an exit trap, whichever way it ends) it writes what it did (<state>/releases/mq-shadow/pr-N-<run>.old, <run> = epoch and pid, so a rerun keeps its own) and starts a transient unit,
#           stackshot-mq-shadow-<pr>-<run> (`release.sh --mq-compare <pr> <run>`), which waits for the queue's verdict (`salamander mq wait`: a read of the queue's state file, up to RELEASE_MQ_WAIT_CAP, 5 h) and appends
#           ONE line to the release log: "merge queue (shadow): PR #N: agree|DISAGREE|no comparison ...". A disagreement is the old path merging what the queue would not (or merging it, main's run then failing
#           it while the queue's group passed), or refusing (checks, a conflict) what the queue would have merged. A queue with no verdict (this includes the queue ejecting a PR only because it "left the group before the merge" after the old path merged it: the real merge closed it under the group, so that is not a disagreement and counts as neither agree nor DISAGREE; a real eject reason such as a failed check or a conflict stays one), a release that stopped before it decided (a lock, a pause, a closed
#           PR), a deploy that failed after the merge (it says nothing about the PR), a `salamander mq:` error from the queue (a host file, say) and a PR the old path merged before the queue read it are "no comparison". Words a log waiter looks for (` FAILED`, ` done:`) are softened in what the line quotes. The release itself never waits for the queue.
#           A missing `salamander`, an `mq add` that errors or times out, a unit that does not start: one log line, the release goes on unchanged and is held up by the timeout at most.
#   on:     the queue merges, routed by COUNT of the PRs waiting in the release queue (THE MERGE QUEUE, ON below, where run_group is): ONE PR waiting is released alone by the old path exactly as in mode off, with no call to
#           `salamander mq` at all (and both of its shortcuts); TWO OR MORE (at most 4, MQ_HANDOFF_MAX) go to the queue together through `salamander mq add`/`wait` (one chain entry each, stacked and tested at once) and are deployed once. The host file must also say `deploy_lock = "<this script's deploy lock>"`
#           (<state>/releases/deploy.lock): without it, or with another file, mode on is refused ("FAILED at mq mode", before the PR is touched), because that lock is what keeps the queue's merge push out of a lone release's
#           merge and deploy. salamander's own `ON_OPEN` switch must be open as well (until then `salamander mq add` refuses mode on and a hand-off fails at "mq add" with its message, pausing the release queue).
#   a host file that does not read (bad TOML, an unknown mode) is one log line and the old path, as off.
#
# THE SESSION PICK (what the running agent sessions need after a release, read from the files the merged PR changed, as deploy.sh reads the
# restarts from the files a fast-forward changed). One map, session_need below; docs/session-reload.md has the table and the code behind each line.
#   recycle  a file a session loads once, at its start, and never reads again while it runs (the SessionStart hook): only a restart delivers it,
#            so the existing recycle path runs (recycle-due on the PR's items, else [fleet] recycle_when_idle)
#   notice   a rule or wording sessions should know about, read fresh where it is used (the tools' text, the write rules the server enforces,
#            the audit's rubric): nothing to reload, so [fleet] notice_cmd is run with one argument appended,
#            "<title> — <summary>" (newlines and tabs as spaces, cut to 400 characters); unset, the log says no notice command is set and the release goes on (still green); a command that fails or times out (60 s) is not green
#   nothing  everything else: server-only code (deploy.sh restarts the services, the puller included), docs, tests, and a script run fresh at
#            each call (the per-call hooks, client.py, pages.py, the stackshot CLI, the reboot hooks)
# The highest need among the files wins, but a notice is never lost to a recycle: when files need a recycle and some file also needs a notice, the recycle runs and the notice is sent too (a recycle does not deliver a notice's change); the pick reads "recycle + notice". The files come from GitHub (repos/<repo>/pulls/<pr>/files, every page) after the deploy; a read that
# fails picks nothing, says so, and the report goes without --release green so the keeper sees it. --recycle and --no-recycle skip the read.
#
# THE CI-RUN POLLER. salamander runs one resident poller (a systemd service of its own) that keeps the newest 30 workflow runs of this repo in a file,
# ~/.local/state/salamander/ci-runs/<owner>__<repo>.json, and `salamander ci-runs <owner/repo> [--sha SHA] [--max-age 120]` reads it (exit 0 fresh,
# 3 no file, 4 stale, 5 unreadable; docs/ci-runs.md in salamander's checkout). Both waits of this script, the PR's checks (wait_pr_checks, step 2 and the rounds of 2a) and main's
# run for the merge (main_green, polled every POLL_MAIN s), first ask it (ci_going: `salamander ci-runs howardpark-ai/stackshot --sha <sha> --max-age 120`). When the file is fresh
# and lists a workflow run of that commit that has not completed (queued or in progress), the cycle makes NO GitHub call (no `gh pr checks`, no git fetch, no `gh run list`/`view`)
# and the wait goes on exactly as a pending check would make it; the log says so (a line at the start and every 5 min). The file can only make a release WAIT, never pass or fail one,
# as in salamander's own release.sh: when the poller shows the run completed, when no run of the sha is listed (the file is a window of 30 runs, so a missing sha proves nothing and is never
# a failure), when the file is missing, stale or unreadable (exit 3, 4, 5, or any other), or when salamander is not on PATH, the cycle does the GitHub read it always did, and that read
# alone decides pass or fail. So a failing job is noticed when the poller shows the run completed (a minute or two after it fails), not the moment it fails. The main wait keeps
# only main's push runs of the merge commit (what run_state reads). The fast path, the ride-along ledger and WAIT_MAIN / CAP_MAIN are untouched: a run the poller shows going counts for
# WAIT_MAIN as a run from run_state does (same run id). RELEASE_CIRUNS_MAX_AGE (120 s; 0 = never ask the poller) is its knob.
# The PR-checks wait that does ask GitHub looks every POLL_PR s (RELEASE_POLL_PR, 60; it was 20) through gh_cached, which shares the answer between the releases on the box for GH_TTL s (45)
# in <state>/releases/gh-cache like run_state's reads, keyed by the PR head too, so a wait without a fresh poller file costs a third of what it did.
#
# A change no test can exercise (docs, Markdown, comment-only lines, CI workflow runner/concurrency settings) does not come here:
# it merges at once with the config repo's docs-merge.sh (CONTRIBUTING.md, step 4).
# A lock is an open file descriptor: git, gh, python3 and sleep run through functions that close 5-9 (and the client, the fleet tool and deploy.sh through
# redirects), so a child that outlives its command (git gc --auto) never holds the deploy lock or a pending-verify record's.
# release.sh is replaced by the deploy it runs: every arm of the dispatch at the end ends in an explicit exit, so bash never reads on from a stale offset.
# The message is sent with client.py (this box's token) after the deploy, when the server is back; a deploy whose server
# never answers again leaves the message unsent and the log tells the story (`--status`). Log: <paths.state>/releases/pr-<n>.log
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
# A lock is an open file descriptor, and a child that outlives its command (git gc --auto, a client, a service) keeps it open and so keeps the lock held. These commands
# are the ones that run while a lock is held, so each runs without the descriptors: 5 (the update lock), 6 (a pending record being recovered), 7 (this release's pending record), 8 (last-good.lock), 9 (the deploy lock).
git() { command git "$@" 5>&- 6>&- 7>&- 8>&- 9>&-; }
gh() { command gh "$@" 5>&- 6>&- 7>&- 8>&- 9>&-; }
python3() { command python3 "$@" 5>&- 6>&- 7>&- 8>&- 9>&-; }
sleep() { command sleep "$@" 5>&- 6>&- 7>&- 8>&- 9>&-; }
REPO="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
LOGDIR="$(python3 config.py state releases)"; mkdir -p "$LOGDIR"
WAIT_CHECKS="${RELEASE_WAIT_CHECKS:-3000}"   # seconds a PR's checks may stay pending (50 min); the knob lets the tests prove the give-up on a short cap, one scenario pins this default
MERGEABLE_WAIT="${RELEASE_WAIT_MERGEABLE:-180}"   # seconds GitHub may say mergeable UNKNOWN (it recomputes after main moves) before the release gives up; read every 10 s
LOCK_FILE="${DEPLOY_LOCK_FILE:-$LOGDIR/deploy.lock}"      # next to the other release state; DEPLOY_LOCK_FILE / DEPLOY_LOCK_WAIT let the tests point elsewhere
LOCK_WAIT="${DEPLOY_LOCK_WAIT:-900}"                      # seconds: a deploy takes seconds to a few minutes (healthz waits up to 180 s), so 15 min is a stuck one
UPDATE_LOCK_FILE="${UPDATE_LOCK_FILE:-$LOGDIR/update.lock}"   # one release at a time brings its branch up to date, waits for the PR's tests on it and merges; UPDATE_LOCK_FILE / UPDATE_LOCK_WAIT let the tests point elsewhere
UPDATE_ROUNDS="${RELEASE_UPDATE_ROUNDS:-3}"              # update-branch rounds at most: main moving during each of them sends the release to the old path
UPDATE_LOCK_WAIT="${UPDATE_LOCK_WAIT:-$((UPDATE_ROUNDS * (WAIT_CHECKS + MERGEABLE_WAIT) + LOCK_WAIT))}"   # seconds a release may wait for that lock: what the holder can take, UPDATE_ROUNDS rounds of (the wait for the PR's tests + the wait for the head to move) and then the deploy lock (3 x (50 + 3) + 15 = 174 min); past that it fails "update lock" before anything is merged
SKIP_DISJOINT="${RELEASE_SKIP_DISJOINT:-1}"               # 2a'': 0 retests every PR that is behind main, as before this existed
RETEST_SKIP="${RELEASE_RETEST_SKIP:-$HERE/tools/retest_skip.py}"   # the helper that reads the suite map against the two sides' changed files; RELEASE_RETEST_SKIP lets the tests point at a stub
SUITEMAP_FILE="${RELEASE_SUITEMAP:-}"                    # a map file to read instead of the published artifact (the tests); the downloaded map is kept in $LOGDIR/suitemap by artifact id
REGEN_MAX="${RELEASE_REGEN_MAX:-2}"                      # snapshot regenerations (2a') at most in one release: a second conflict after the first push may be a real one, and a loop is never the answer
SNAPSHOT_REGEN="${RELEASE_SNAPSHOT_REGEN:-$HERE/tools/snapshot_regen.py}"   # the helper that mends a conflict on tests/tool_text.snapshot.json alone; RELEASE_SNAPSHOT_REGEN lets the tests point at a stub
TESTS_CHECK="${RELEASE_TESTS_CHECK:-suites}"             # the PR check (the job of tests.yml) that must be reported on an updated head before its verdict counts: a quick check alone must not read as a pass
WAIT_MAIN="${RELEASE_WAIT_MAIN:-5400}"   # seconds a covering run of main may be going (main_green: counted from when it starts, status in_progress). 90 min: main's full run, every suite measured, can be slow on a loaded host, so 60 min (3600) let a slow run end a release
CAP_MAIN="${RELEASE_CAP_MAIN:-10800}"    # seconds from the merge, at most, that main_green waits for a run that covers it (3 h): a run queued behind others uses none of WAIT_MAIN, this keeps it from waiting forever
NOTICE_TIMEOUT="${RELEASE_NOTICE_TIMEOUT:-60}"   # seconds [fleet] notice_cmd may take (notice_send): past it the command is stopped and the notice counts as not sent, so the report loses its green flag and the next release starts
WAIT_STEPS="${RELEASE_WAIT_STEPS:-600}"  # seconds a run of main that is completed and green may stay without the conclusion of its "run every suite, measured" step (main_green: GitHub fills in the step results some time after the job reports completed, and release.sh once read a run in that gap and failed a green one). 10 min: the gap has been seconds to a minute; past it the step results never came and the release fails as before. Counted on the clock from the first look that saw the gap; no extra GitHub call, the reads are the POLL_MAIN ones
POLL_MAIN="${RELEASE_POLL_MAIN:-60}"     # seconds between two looks at main's runs while main_green waits (a run can take a long time, and every look costs GitHub REST calls from one shared hourly budget; polling every 20 s with several releases waiting could spend it)
POLL_PR="${RELEASE_POLL_PR:-60}"         # seconds between two looks at a PR's checks while wait_pr_checks waits (every look is GitHub calls from one shared hourly budget; a PR's tests take a while). The read is shared between the releases on the box for GH_TTL s, like main's
GH_CACHE="$LOGDIR/gh-cache"              # main's run list and each run's view, kept for GH_TTL s and shared by every release on this box, so releases waiting on the same run ask GitHub once between them
GH_TTL="${RELEASE_GH_TTL:-45}"           # seconds an answer of those reads is reused (0 = never; the tests set it). A run the list says is completed and cancelled needs no run view at all
LEDGER="${RELEASE_LEDGER:-$LOGDIR/fast-ok.json}"   # the merges release.sh itself made on a passing PR check and an up-to-date head (the ride-along ledger, see fast_gate (a)); read without a lock (it is replaced whole), written under flock on $LEDGER.lock
PENDING_DIR="$LOGDIR/pending-verify"      # one record per fast deploy whose main run is not read yet: a watch that is killed leaves it, the next release start finishes the job
PENDING_FILE=""; pv_block=""
LAST_GOOD="$LOGDIR/last-good"            # the newest commit whose run on main passed: what a failing main run rolls back to; one sha, written by record_good
QUEUE="$LOGDIR/queue"                    # the release queue (release.sh queue): PR numbers, one a line, in order; $QUEUE.lock its flock, $QUEUE.driver the PR whose release starts the next, $QUEUE.paused why it is paused, $QUEUE.log what it did

MQ_ADD_TIMEOUT="${RELEASE_MQ_ADD_TIMEOUT:-20}"   # seconds `salamander mq add` may take in shadow mode before the release goes on without it (THE MERGE QUEUE, SHADOW above)
MQ_WAIT_CAP="${RELEASE_MQ_WAIT_CAP:-18000}"       # seconds the detached comparison waits for the queue's verdict (5 h: a queue run takes up to 100 min, and a PR behind a failure in the chain is tested again after the restack)
MQ_ON_ADD_TIMEOUT="${RELEASE_MQ_ON_ADD_TIMEOUT:-60}"   # seconds `salamander mq add` may take in mode on (it starts the queue's driver unit, and a refusal is an answer, so a slow one is an error: THE MERGE QUEUE, ON below)
MQ_HANDOFF_MAX=4                                  # PRs handed to the queue in one hand-off (mode on): release.sh's own number, not a setting of the rules file; the chain tests those entries at once and the rest stay in release.sh's queue for the next hand-off
MQ_SLICE="${RELEASE_MQ_SLICE:-300}"                # seconds one `salamander mq wait` of a group release may block before the release looks at whether the queue is paused or blocked (mode on)
MQ_HANDED="$LOGDIR/mq-on"                         # mode on: one marker file per PR handed to the queue (pr-N), so the old path can refuse a PR the queue holds without calling the queue
MQ_DIR="$LOGDIR/mq-shadow"                        # what each shadow release did, one file per RUN (pr-N-<epoch>-<pid>.old, so a rerun of the PR keeps its own), for the comparison unit to read
MQ_PR=""; MQ_RUN=""; MQ_MERGED=0; MQ_FAIL=""                 # globals, not run()'s locals: the exit trap reads them after run() has returned
CIRUNS_MAX_AGE="${RELEASE_CIRUNS_MAX_AGE:-120}"   # how old salamander's CI-run poller file may be and still be believed about a run that is going (salamander ci-runs --max-age); 0 = never ask it
# ci_going <sha> <any|main>: 0, and one line on stdout "<run id> <running|queued> <what it saw>", when salamander's CI-run poller (`salamander ci-runs`, read from a file: no GitHub call)
# is fresh and lists a workflow run of <sha> that has not completed. `main` keeps the push runs of main only (what run_state reads); `any` every run of the commit (a PR's checks).
# Every other case returns 1 and the caller asks GitHub, which alone decides pass or fail: salamander not on PATH, exit 3 (no file for this repo), 4 (stale), 5 (unreadable), 2 or any
# other, a run of the sha completed or not listed at all (the file is a window of the repo's 30 newest runs, so a missing sha proves nothing), output that is not JSON.
ci_going() {
    local sha="${1:-}" kind="${2:-any}" out
    [ "$CIRUNS_MAX_AGE" -gt 0 ] 2>/dev/null || return 1
    command -v salamander >/dev/null 2>&1 || return 1
    [[ "$sha" =~ ^[0-9a-f]{7,64}$ ]] || return 1
    out="$(salamander ci-runs "$REPO" --sha "$sha" --max-age "$CIRUNS_MAX_AGE" 2>/dev/null 5>&- 6>&- 7>&- 8>&- 9>&-)" || return 1
    KIND="$kind" SHA="$sha" python3 -c '
import json, os, sys, time
try:
    d = json.loads(sys.stdin.read()); sha = os.environ["SHA"]
    mine = [r for r in d["runs"] if (r.get("head_sha") or "").startswith(sha) or sha.startswith(r.get("head_sha") or "-")]
    if os.environ["KIND"] == "main": mine = [r for r in mine if r.get("event") == "push"]
    going = [r for r in mine if r.get("status") != "completed"]
    if not going: sys.exit(1)
    r = going[0]
    print("%s %s %d of %d run(s) of %s not completed (poller file %ds old)" % (r.get("id"), "running" if r.get("status") == "in_progress" else "queued", len(going), len(mine), sha[:7], max(0, int(time.time() - float(d["updated"])))))
except Exception:
    sys.exit(1)' <<< "$out"
}

# ---- the merge queue, shadow (THE MERGE QUEUE, SHADOW at the top). Nothing in this block fails or holds up a release, except that mq_host_mode saying `on` refuses it.
mq_host_mode() {   # prints off | shadow | on, or "bad: <why>". No host file is off. The file and the default folder are the ones salamander reads
    local f="${XDG_CONFIG_HOME:-$HOME/.config}/mergequeue/${REPO//\//__}.toml"
    [ -e "$f" ] || { echo off; return 0; }
    python3 -c '
import sys
try:
    import tomllib
    with open(sys.argv[1], "rb") as fh: d = tomllib.load(fh)
    m = d.get("mode", "off")
    print(m if m in ("off", "shadow", "on") else "bad: mode %r is not off, shadow or on" % (m,))
except Exception as e:
    print("bad: " + (str(e).splitlines() or [type(e).__name__])[0][:120])' "$f" 2>/dev/null || echo "bad: cannot read $f"
}
mq_host_key() {   # $1 = a string key of the host file: its value, nothing when the file or the key is missing or does not read
    local f="${XDG_CONFIG_HOME:-$HOME/.config}/mergequeue/${REPO//\//__}.toml"
    [ -e "$f" ] || return 0
    python3 -c '
import sys
try:
    import tomllib
    with open(sys.argv[1], "rb") as fh: v = tomllib.load(fh).get(sys.argv[2], "")
    print(v if isinstance(v, str) else "")
except Exception: pass' "$f" "$1" 2>/dev/null
}
mq_landing() {   # $1 = the head commit of a PR the merge queue merged and GitHub names no merge commit for: prints the commit of origin/main's first-parent line that brought it in. The queue merges each PR into its entry with
                 # `merge --no-ff` and pushes the entry head to main by fast-forward, so a PR head is only the second parent of its merge commit: the earliest first-parent commit of main that has the head in its ancestry is the PR's landing commit.
                 # A head that is on the first-parent line itself (a PR merged by fast-forward) is its own landing commit. Nothing is printed when the head is not a known commit or is not in main. Needs main fetched
    local full fp land
    full="$(git rev-parse --verify --quiet "$1^{commit}" 2>/dev/null)"; [[ "$full" =~ ^[0-9a-f]{40,64}$ ]] || return 0
    fp="$(git rev-list --first-parent origin/main 2>/dev/null)"
    if grep -qx -- "$full" <<<"$fp"; then printf '%s\n' "$full"; return 0; fi   # a here-string, not a pipe: under pipefail a grep that stops at its match could end the writer with SIGPIPE on a long list
    land="$(git rev-list --first-parent --ancestry-path "$full..origin/main" 2>/dev/null | tail -n 1)"
    [[ "$land" =~ ^[0-9a-f]{40,64}$ ]] && printf '%s\n' "$land"
    return 0
}
mq_on_check() {   # mode on, both paths: 0 when the host file names the deploy lock this script takes (deploy_lock = $LOCK_FILE); else 1 with $mq_why. The queue's merge push takes THAT file, without waiting, and
                  # this script holds it from its own merge to the end of its deploy, so this is what keeps the queue from merging while a lone PR is mid-merge or deploying, and a group deploy from overlapping a push
    local dl; dl="$(mq_host_key deploy_lock)"
    if [ -z "$dl" ]; then mq_why="the host file ${XDG_CONFIG_HOME:-~/.config}/mergequeue/${REPO//\//__}.toml has no deploy_lock: in mode on it must say deploy_lock = \"$LOCK_FILE\", the lock this script takes, or the queue could merge while a release is merging or deploying; nothing was merged"; return 1; fi
    [ "$(realpath -m "$dl" 2>/dev/null)" = "$(realpath -m "$LOCK_FILE" 2>/dev/null)" ] || { mq_why="the host file's deploy_lock is $dl, not the lock this script takes ($LOCK_FILE): the queue and the releases would not exclude each other; set deploy_lock = \"$LOCK_FILE\"; nothing was merged"; return 1; }
}
mqh_set() { mkdir -p "$MQ_HANDED" && printf '%s\n' "$(date -u +%FT%TZ) handed to the merge queue by the group release led by PR #${lead:-?}" > "$MQ_HANDED/pr-$1"; }
mqh_clear() { rm -f "$MQ_HANDED/pr-$1"; }
mq_shadow_add() {   # $1 = the PR. Shadow mode: queue it next to the old path and arrange the comparison for when this release ends. Always returns 0
    local n="$1" out rc
    command -v salamander >/dev/null 2>&1 || { say "merge queue (shadow): salamander is not on PATH, so PR #$n was not queued and there is nothing to compare; the release goes on"; return 0; }
    out="$(timeout "$MQ_ADD_TIMEOUT" salamander mq add "$n" --repo "$REPO" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
    out="$(printf '%s' "$out" | tail -n 1 | cut -c1-160)"
    if [ $rc -eq 0 ]; then
        MQ_PR="$n"; MQ_RUN="$(date +%s)-$$"; MQ_MERGED=0; MQ_FAIL=""; trap mq_shadow_finish EXIT
        say "merge queue (shadow): PR #$n queued (${out:-no output}); the queue merges nothing in shadow, and when this release ends its verdict is compared with what this release did, one line in this log"
    elif [ $rc -eq 124 ]; then say "merge queue (shadow): salamander mq add took more than ${MQ_ADD_TIMEOUT}s, so PR #$n was not queued; the release goes on"
    else say "merge queue (shadow): salamander mq add exited $rc (${out:-no output}), so PR #$n was not queued; the release goes on"; fi
    return 0
}
mq_shadow_finish() {   # the exit trap of a release that queued its PR: write what the old path did and start the unit that compares it with the queue's verdict. Keeps the release's exit status
    local rc=$? kind text out f="$MQ_DIR/pr-$MQ_PR-$MQ_RUN.old" env_args=()
    trap - EXIT
    if [ $rc -eq 0 ]; then kind=merged; text="merged, live, main's tests passed"
    elif [ "$MQ_MERGED" = 1 ]; then
        case "$MQ_FAIL" in
            *"was not read"*) kind=undecided; text="merged, then $MQ_FAIL" ;;
            "deploy: "*|"deploy lock: "*) kind=deploy-failed; text="merged, then $MQ_FAIL" ;;   # the deploy (healthz included) or its lock: says nothing about the PR's tests
            *) kind=merged-failed; text="merged, then ${MQ_FAIL:-it stopped (exit $rc)}" ;;
        esac
    else
        case "$MQ_FAIL" in
            "checks: "*|"pr tests: "*|"mergeable: "*|"update-branch: "*) kind=refused; text="refused before the merge at $MQ_FAIL" ;;
            "") kind=undecided; text="ended (exit $rc) before it decided" ;;
            *) kind=undecided; text="stopped at $MQ_FAIL" ;;
        esac
    fi
    text="$(printf '%s' "$text" | tr '\n\t' '  ' | cut -c1-300 | mq_plain)"
    if mkdir -p "$MQ_DIR" 2>/dev/null && printf '%s\t%s\n' "$kind" "$text" > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f" 2>/dev/null; then
        [ -z "${XDG_CONFIG_HOME:-}" ] || env_args+=("--setenv=XDG_CONFIG_HOME=$XDG_CONFIG_HOME")
        [ -z "${XDG_STATE_HOME:-}" ] || env_args+=("--setenv=XDG_STATE_HOME=$XDG_STATE_HOME")
        if out="$(timeout 20 systemd-run --user --quiet --collect --unit "stackshot-mq-shadow-$MQ_PR-$MQ_RUN" -p WorkingDirectory="$HERE" --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "${env_args[@]}" \
                  "$HERE/release.sh" --mq-compare "$MQ_PR" "$MQ_RUN" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; then
            say "merge queue (shadow): PR #$MQ_PR: the comparison runs as stackshot-mq-shadow-$MQ_PR-$MQ_RUN and logs here once the queue has a verdict (this release: $kind, $text)"
        else say "merge queue (shadow): the comparison unit did not start ($(printf '%s' "$out" | tail -n 1 | cut -c1-120)); the queue's own verdict is in salamander mq status"; fi
    else say "merge queue (shadow): could not write $f, so no comparison"; fi
    exit $rc
}
MQ_LEFT_GROUP='left the group before the merge'   # the queue's reason when the PR was closed, changed or moved under its group: after the old path merged the PR it is the old path's own merge, so the queue never reached a verdict
mq_plain() {   # stdin to stdout: the words a waiter on a release log looks for (` FAILED `, ` done: `) made harmless, so a PR title in a queue line never reads as a release's result
    sed -e 's/ FAILED/ failed/g' -e 's/ done:/ done/g'
}
mq_compare() {   # release.sh --mq-compare <pr> <run>: wait for the queue's verdict on the PR and log one line against what its release did, appended to that release's log. Exit 0 unless called wrongly
    local pr="${1:-}" run="${2:-}" log old kind text out rc q res line qerr=0
    [[ "$pr" =~ ^[0-9]+$ ]] && [[ "$run" =~ ^[0-9]+-[0-9]+$ ]] || { echo "usage: release.sh --mq-compare <pr> <run>" >&2; return 2; }
    log="$LOGDIR/pr-$pr.log"; old="$MQ_DIR/pr-$pr-$run.old"; exec >> "$log" 2>&1
    [ -s "$old" ] || { say "merge queue (shadow): PR #$pr: no record of what its release did ($old), so nothing to compare"; return 0; }
    IFS=$'\t' read -r kind text < "$old"
    command -v salamander >/dev/null 2>&1 || { say "merge queue (shadow): PR #$pr: salamander is not on PATH, so nothing to compare"; return 0; }
    out="$(timeout $((MQ_WAIT_CAP + 30)) salamander mq wait "$pr" --repo "$REPO" --timeout "$MQ_WAIT_CAP" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
    line="$(printf '%s' "$out" | tail -n 1 | cut -c1-200 | mq_plain)"; text="$(printf '%s' "$text" | mq_plain)"
    ! printf '%s\n' "$out" | grep -q '^salamander mq: ' || qerr=1   # salamander's own error (a host file, a state file), not a verdict on the PR, even when it exits 1
    case $rc in 0|3) q=pass ;; 1) q=fail ;; *) q=none; [ $rc -ne 124 ] || line="no verdict within ${MQ_WAIT_CAP}s" ;; esac
    if [ $qerr = 1 ]; then kind=-; q=-; res="no comparison: salamander mq reported an error, not a verdict on the PR"; fi
    case "$kind/$q" in
        -/-) ;;
        merged/pass) res="agree: the old path merged it and the queue's group passed" ;;
        merged-failed/fail)
            if printf '%s' "$line" | grep -Eqi "$MQ_LEFT_GROUP"; then res="no comparison: no verdict, the real merge closed the PR before the queue's group finished"
            else res="agree: the old path merged it and main's tests then failed it, and the queue would not have merged it either"; fi ;;
        refused/fail) res="agree: the old path refused it and the queue would not have merged it either" ;;
        merged/fail)
            if printf '%s' "$line" | grep -Eqi 'pull request is (merged|closed)|already in main'; then res="no comparison: the old path merged the PR before the queue read it"
            elif printf '%s' "$line" | grep -Eqi "$MQ_LEFT_GROUP"; then res="no comparison: no verdict, the real merge closed the PR before the queue's group finished"
            else res="DISAGREE: the old path merged it, the queue would not have"; fi ;;
        refused/pass) res="DISAGREE: the old path refused it, the queue would have merged it" ;;
        merged-failed/pass) res="DISAGREE: the old path merged it and main's tests then failed it, the queue's group passed" ;;
        undecided/*) res="no comparison: the old path did not decide on the PR" ;;
        deploy-failed/*) res="no comparison: the old path merged it but its deploy failed, which says nothing about the PR's tests" ;;
        *) res="no comparison: the queue gave no verdict" ;;
    esac
    say "merge queue (shadow): PR #$pr: $res. Old path: $text. Queue (salamander mq wait, exit $rc): ${line:-no output}"
    return 0
}

say() { echo "$(date -u +%FT%TZ) $*"; }
tell() {  # one message to the project; never fails the run. Extra arguments go to client.py (--release green --pr <url>)
    local text="$1"; shift
    python3 client.py message projects/example "$text" --sender release "$@" >/dev/null 2>&1 9>&- 7>&- 6>&- 5>&- || say "message not sent: $text"
}
released() {  # $1 = a PR, $2 = its merge commit: main's full run passed on it and it is in $LAST_GOOD. The server settles the open items with a release step
               # for the PR (client.py released; refused unless the merge is in last-good and HEAD): an item whose only open steps are that release is closed, done,
               # with no session turn; one with another open step has the release step ticked and its mover told once, a real notice (the green report is log-only).
               # Never fails the run; what it did, and why an item was left alone, is a log line
    local out
    if out="$(python3 client.py released --pr "https://github.com/$REPO/pull/$1" --sha "$2" 2>&1 9>&- 8>&- 7>&- 6>&- 5>&-)"; then say "items of PR #$1: $(echo "$out" | sed 's/^stackshot: //' | paste -sd ';' -)"
    else say "the items of PR #$1 were not settled: $(echo "$out" | tail -1 | sed 's/^stackshot: //')"; fi
    return 0
}
idle_recycle() {  # ask the fleet tool for a recycle once the box is idle: [fleet] recycle_when_idle, the reason appended; 1 when none is set or it failed
    local -a cmd
    mapfile -t cmd < <(python3 -c 'import config; print("\n".join(config.recycle_when_idle()))' 2>/dev/null)
    [ "${#cmd[@]}" -gt 0 ] && [ -n "${cmd[0]}" ] && command -v "${cmd[0]}" >/dev/null 2>&1 && "${cmd[@]}" "$1" >/dev/null 2>&1 6>&- 7>&- 8>&- 9>&-
}
notice_send() {  # [fleet] notice_cmd with ONE argument appended: "<title> — <summary>", a newline or tab turned into a space and the whole cut to 400 characters
                 # (ending in "…" when cut), the most a fleet notice takes. 0 sent · 1 no command set · 2 the command failed or is not found
                 # · 3 it did not finish within NOTICE_TIMEOUT seconds (it is stopped: a hung command must not hold the report and the queue's next release)
    local -a cmd; local nrc text
    mapfile -t cmd < <(python3 -c 'import config; print("\n".join(config.notice_cmd()))' 2>/dev/null)
    [ "${#cmd[@]}" -gt 0 ] && [ -n "${cmd[0]}" ] || return 1
    command -v "${cmd[0]}" >/dev/null 2>&1 || return 2
    text=$(python3 -c 'import sys
t = (sys.argv[1] + " \u2014 " + sys.argv[2]).replace("\r", " ").replace("\n", " ").replace("\t", " ")
if len(t) > 400: t = t[:399] + "\u2026"
sys.stdout.buffer.write(t.encode("utf-8", "surrogateescape"))' "$1" "$2") || return 2
    timeout -k 5 "$NOTICE_TIMEOUT" "${cmd[@]}" "$text" >/dev/null 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-; nrc=$?
    case $nrc in 0) return 0 ;; 124|137) return 3 ;; *) return 2 ;; esac
}

# session_need <path> → one line, "<need><TAB><why>": the need of one changed file for the running sessions (THE SESSION PICK above). The one map:
# a file not named here is "nothing". docs/session-reload.md keeps the table in step with it (tests/release_scenario.py reads both).
session_need() {
    case "$1" in
        client/hooks/session-start.sh)
            printf 'recycle\tthe SessionStart hook: what it prints enters a session once, at its start' ;;
        tests/tool_text.snapshot.json)
            printf 'notice\tthe tools'"'"' text: a session learned the tools when it connected, and a recycle does not deliver a change (claude.ai refreshes its tool list within about a day)' ;;
        next_rules.py|model_guards.py|owner_steps.py|bullet_text.py)
            printf 'notice\ta write rule the server enforces on a session'"'"'s writes, read fresh at each write' ;;
        audit_rubric.txt)
            printf 'notice\tthe rubric the daily audit judges a session'"'"'s items by, read at each audit' ;;
        client/hooks/*|client.py|pages.py|stackshot|reboot-hooks/*)
            printf 'nothing\ta script or CLI run fresh at each call' ;;
        *.md|docs/*)
            printf 'nothing\tdocs' ;;
        tests/*)
            printf 'nothing\ttests' ;;
        *)
            printf 'nothing\tserver-side, or not read by a session (deploy.sh restarts what it must)' ;;
    esac
}
# list_files <file>...: the first 6 of them, comma-separated, and how many more
list_files() {
    local -a l=("$@"); local more=0 out
    [ ${#l[@]} -le 6 ] || more=$(( ${#l[@]} - 6 ))
    out="$(IFS=,; echo "${l[*]:0:6}" | sed 's/,/, /g')"; [ $more = 0 ] || out="$out and $more more"
    printf '%s' "$out"
}
# pick_session: the changed files on stdin, one a line → PICK (nothing | notice | recycle: the highest need), PICK_NOTICE (1 when any file needs a notice: a recycle does
# not deliver what a notice carries, so a pick of recycle with PICK_NOTICE=1 does both), PICK_FROM (the files of the highest need, the first 6 and how many more; with both,
# the recycle files and then "notice from" the notice files), NOTICE_FROM (the notice files), PICK_TABLE (one line per file: need, path, why)
pick_session() {
    local f line need why rank=0 r n=0; PICK=nothing; PICK_FROM=""; PICK_TABLE=""; PICK_NOTICE=0; NOTICE_FROM=""
    local -a top=() nfiles=()
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        line="$(session_need "$f")"; need="${line%%$'\t'*}"; why="${line#*$'\t'}"
        PICK_TABLE+="$(printf '  %-8s %s  (%s)' "$need" "$f" "$why")"$'\n'
        case "$need" in recycle) r=2 ;; notice) r=1; nfiles+=("$f") ;; *) r=0 ;; esac
        if [ $r -gt $rank ]; then rank=$r; PICK="$need"; top=(); fi
        [ $r -eq $rank ] && top+=("$f")
        n=$((n+1))
    done
    PICK_FROM="$(list_files "${top[@]}")"
    if [ ${#nfiles[@]} -gt 0 ]; then
        PICK_NOTICE=1; NOTICE_FROM="$(list_files "${nfiles[@]}")"
        [ "$PICK" != recycle ] || PICK_FROM="$PICK_FROM; notice from $NOTICE_FROM"
    fi
    [ $n -gt 0 ] || PICK_FROM="no changed file"
}
pick_label() {  # the pick as the log, the report and the dry run say it: "recycle + notice" when the files need both
    if [ "$PICK" = recycle ] && [ "${PICK_NOTICE:-0}" = 1 ]; then echo "recycle + notice"; else echo "$PICK"; fi
}
pr_files() {  # the files PR $1 changed, one a line, every page (GitHub lists up to 3,000)
    gh api "repos/$REPO/pulls/$1/files?per_page=100" --paginate --jq '.[].filename'
}

take_lock() {  # the deploy lock on fd 9 (exec: this shell's own), waited for up to LOCK_WAIT; $1 says what was done when it fails
    mkdir -p "$(dirname "$LOCK_FILE")"; exec 9>>"$LOCK_FILE" || { exec 9>&-; fail "deploy lock" "cannot open the lock file $LOCK_FILE"; }
    if ! flock -n 9; then say "another release holds the deploy lock; waiting up to $((LOCK_WAIT/60)) min ($LOCK_WAIT s)"
        flock -w "$LOCK_WAIT" 9 || { exec 9>&-; fail "deploy lock" "another deploy held the lock $LOCK_FILE for more than $LOCK_WAIT s; $1"; }; fi
    say "deploy lock taken"
}
take_update_lock() {  # the update lock on fd 5, waited for up to UPDATE_LOCK_WAIT; held until the merge is made. Taken before the deploy lock, never while holding it
    mkdir -p "$(dirname "$UPDATE_LOCK_FILE")"; exec 5>>"$UPDATE_LOCK_FILE" || { exec 5>&-; fail "update lock" "cannot open the lock file $UPDATE_LOCK_FILE"; }
    if ! flock -n 5; then say "another release holds the update lock (it is bringing its branch up to date, waiting for its tests or merging); waiting up to $((UPDATE_LOCK_WAIT/60)) min ($UPDATE_LOCK_WAIT s)"
        flock -w "$UPDATE_LOCK_WAIT" 5 || { exec 5>&-; fail "update lock" "another release held the update lock $UPDATE_LOCK_FILE for more than $UPDATE_LOCK_WAIT s; nothing was merged (release.sh $pr again once it is free)"; }; fi
    say "update lock taken"
}

# Main's tests (covering runs). A PR runs only the suites its change reaches, so its green checks do
# not mean every suite passed: the full run is the one on main that covers the merge, where every suite runs. Main's workflow runs one run at
# a time and cancels a queued run when a newer push arrives, so the run on the merge commit M can be cancelled and a later run, on a commit
# that contains M, is the one that tests it (several PRs merged close together: the first's and the last's
# runs can be cancelled while the middle one's passes on its own commit, and every release then waits for the run on the newest commit instead
# and may fail at its limit, although the middle one could have deployed at once).
#   THE RULE. M is the merge commit of the release. The runs that count are the main push runs on a commit C with M an ancestor of C or M itself
#   (git merge-base --is-ancestor M C), oldest commit first (their place on main, not the run id: a re-run of an older commit has a later id). A cancelled run is skipped, not a failure. Walk them until the first that has not
#   passed: a run still queued or in progress means wait (unless an earlier one passed), a failed run is the end. The release is satisfied by the
#   newest run that passed before that stop, and deploys to its commit C. When the first non-passed run failed and no run on M's own commit or
#   between M and it passed, the release fails, judged by the oldest commit that failed (the log names its run). When one passed before it, the
#   failure is a later commit's, not this release's, and the pass decides (the log says which failure it ignored). A pass after a failure
#   is not looked for: the oldest failure bounds it.
#   TIME. WAIT_MAIN (90 min) counts from when a covering run starts (status in_progress, first seen at a poll; a different run going starts it again), read off the clock (date +%s), not counted in polls, not
#   from the merge: a run queued behind another waits for its turn without using it up. CAP_MAIN (3 h) counts from the merge, so a release never
#   waits forever (nothing covering ever runs, or only cancelled runs). The log line at the end of a wait that gave up names both.
#   STEP RESULTS. A run passes when it is completed and the step "run every suite, measured" concluded success; that step concluding anything else (a failure, skipped, cancelled) fails it at
#   once. GitHub fills in a job's step results some time after the run reports completed (a release can read main's run in that gap, saw no conclusion for the step and failed a green
#   run). So a run that is completed with conclusion success whose suites step has no conclusion yet (missing, empty, or the step absent) is pending ("step results not filled in yet"): it is read
#   again at the next POLL_MAIN poll, with no GitHub call beyond the ones a pending run costs, and decides when the step shows. Both callers (pre: the old path before the deploy; post: after the fast
#   deploy, which rolls back on "fail") treat it as pending, never as a failure. WAIT_STEPS (RELEASE_WAIT_STEPS, 600 s = 10 min, counted on the clock from the first look that saw the gap on that run)
#   bounds it: past it the run fails as it did before ("finished successfully, but its step results never arrived"), and the post caller rolls back like any failure. A run whose job itself did not
#   succeed, with the suites step missing, still fails at once.
# Two callers:
#   main_green pre <M>     the old path, before the deploy: its suites failing stops the release (merged, not deployed: fix forward); every suite
#                          passing deploys, and what else the run found (a suite that failed only when measured and passed plainly, the audit's
#                          selection miss, a later step that failed) goes in the report, which then goes to the keeper instead of green.
#                          The commit it passed on is left in $verified and the deploy is pinned to it (DEPLOY_TO), never to a newer tip with no passing run:
#                          a merge another release lands meanwhile is deployed by that release, after its own run.
#   main_green post <M>    after the fast deploy: M is the one deployed, whatever main's tip is by now. It never
#                          fails the release; it returns 0 (the run passed; $audit_note holds what else it found) or 1, with $mg_kind
#                          "fail" (its suites failed: the caller rolls back) or "unknown" (no run passed or failed in time; a cancelled run is the same as none): that one does not roll back,
#                          and $mg_why, $mg_rid and $mg_rsha (the run, and the commit it ran on, which can be a newer one covering several merges).
# A pass writes the commit to $LAST_GOOD (record_good). tests.yml's step names "run every suite, measured" and "audit the selection" are read here.
# Both are steps of the `suites` job; on main that job runs after the `shards` plan and the `measure` matrix (main's measured run, split across runners) and its "run every suite, measured" passes only when
# every shard passed and their merged map holds every suite once, so a failed shard reads here as a failed suites step. The shards' steps have other names.
run_state() {   # $1 = M. Prints "<run> pending <sha> running|queued", "<run> pass <sha> [what else it found]", "<run> fail <sha> <why>", "<run> cancelled <sha>" (only cancelled runs cover M) or
                # "none" (no run covers it yet; "pending ... steps" is a run that is completed and green whose suites step has no conclusion yet); <sha> is the commit of the run that decided it. The rule is in the comment above. A line on stderr (the log) says which run decided when it is not the run on M itself
    TIP="$1" REPO="$REPO" GH_CACHE="$GH_CACHE" GH_TTL="$GH_TTL" python3 -c '
import functools, hashlib, json, os, subprocess, sys, time
R, M = os.environ["REPO"], os.environ["TIP"]
CD, TTL = os.environ.get("GH_CACHE", ""), float(os.environ.get("GH_TTL") or 0)
def gh(*a, salt=""):              # an answer from the last GH_TTL s (any release on this box asked it) is reused; only a successful, non-empty answer is kept. salt: the attempt number of the run, so a re-run is a new key
    f = os.path.join(CD, hashlib.sha1("\0".join((*a, str(salt))).encode()).hexdigest()) if CD and TTL > 0 else ""
    if f:
        try:
            if time.time() - os.stat(f).st_mtime < TTL: return open(f, encoding="utf-8").read()
        except OSError: pass
    r = subprocess.run(["gh", *a], capture_output=True, text=True)
    if r.returncode != 0: return ""
    if f and r.stdout.strip():
        try:
            os.makedirs(CD, mode=0o700, exist_ok=True); t = f + ".%d.tmp" % os.getpid()
            open(t, "w", encoding="utf-8").write(r.stdout); os.replace(t, f)
            for n in os.listdir(CD):          # entries older than an hour go: the folder stays a few files
                q = os.path.join(CD, n)
                if time.time() - os.stat(q).st_mtime > 3600: os.unlink(q)
        except OSError: pass
    return r.stdout
def js(t, d):
    try: return json.loads(t)
    except Exception: return d
def look(row):                        # (state, detail, jobs, bad steps) of one run; row = its entry in the run list
    rid = row["databaseId"]
    if row.get("status") == "completed" and row.get("conclusion") == "cancelled": return "cancelled", "", [], []   # the list says it: no run view (3 calls) for a run that only a re-run changes
    v = js(gh("run", "view", str(rid), "--repo", R, "--json", "status,conclusion,jobs", salt=row.get("attempt") or ""), {})
    jobs = v.get("jobs") or []
    if v.get("conclusion") == "cancelled": return "cancelled", "", jobs, []    # replaced while queued, or cancelled after its job started: it says nothing about the tests
    if v.get("status") != "completed": return "pending", "running" if v.get("status") == "in_progress" else "queued", jobs, []
    steps = {s["name"]: s.get("conclusion") for j in jobs for s in j.get("steps") or []}
    bad = [f"{n}={c}" for n, c in steps.items() if c not in ("success", "skipped", None, "")]
    if steps.get("run every suite, measured") in (None, "") and v.get("conclusion") == "success":   # GitHub fills in the step results of a job some time after the run reports completed, so a finished, green run whose suites step has no conclusion yet is read again, not failed (main_green gives up after WAIT_STEPS)
        return "pending", "steps", jobs, []
    if steps.get("run every suite, measured") != "success":
        return "fail", ", ".join(bad) or "no suites step, conclusion " + str(v.get("conclusion")), jobs, bad
    return "pass", "", jobs, bad
runs = js(gh("run", "list", "--repo", R, "--workflow", "tests.yml", "--branch", "main", "--event", "push", "--limit", "20",
             "--json", "databaseId,headSha,status,conclusion,attempt"), [])
passed = stop = cancelled = None
def anc(a, b): return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0
def order(x, y):                      # by place on main, not by run id: a re-run of an older commit gets a later id and keeps its place
    if x["headSha"] != y["headSha"]:
        if anc(x["headSha"], y["headSha"]): return -1
        if anc(y["headSha"], x["headSha"]): return 1
    return x["databaseId"] - y["databaseId"]
cov = [r for r in runs if anc(M, r["headSha"])]   # the runs on commits that contain M (an older commit, or one not fetched yet, is not one)
for r in sorted(cov, key=functools.cmp_to_key(order)):   # oldest commit first
    st, detail, jobs, bad = look(r)
    if st == "cancelled": cancelled = r; continue
    if st == "pass": passed = (r, jobs, bad); continue
    stop = (r, st, detail); break     # the first run that has not passed: one still going, or a failure
if stop and stop[1] == "fail" and not passed:
    r = stop[0]
    if r["headSha"] != M:
        print("the run %s on %s decided: the oldest commit that failed after the merge %s, and no run on %s or between them passed" % (r["databaseId"], r["headSha"][:7], M[:7], M[:7]), file=sys.stderr)
    print(r["databaseId"], "fail", r["headSha"], stop[2])
elif passed:
    r, jobs, bad = passed
    if stop and stop[1] == "fail":
        print("the run %s on %s failed after the pass on %s: judged by the oldest commit that failed, which is not this release, so the pass on %s decides" % (stop[0]["databaseId"], stop[0]["headSha"][:7], r["headSha"][:7], r["headSha"][:7]), file=sys.stderr)
    flaky = []                        # tests/suitemap.py measure warns when a suite fails only when measured
    for j in jobs:
        jid = j.get("databaseId")
        for a in js(gh("api", f"repos/{R}/check-runs/{jid}/annotations"), []) if jid else []:
            m = a.get("message") or ""
            if a.get("annotation_level") == "warning" and " failed only when measured" in m:
                flaky.append(m.split(" failed only when measured")[0])
    found = []
    if flaky:
        found.append(", ".join(flaky) + " failed only when measured, then passed plainly (flaky?)")
    if "audit the selection=failure" in bad:
        found.append("the selection audit found a miss: the selection rules need a look")
    other = [b for b in bad if not b.startswith("audit the selection=")]
    if other:
        found.append("also failed: " + ", ".join(other))
    print(r["databaseId"], "pass", r["headSha"], "; ".join(found))
elif stop:
    print(stop[0]["databaseId"], "pending", stop[0]["headSha"], stop[2])
elif cancelled:
    print(cancelled["databaseId"], "cancelled", cancelled["headSha"])
else:
    print("none")'
}

read_good() {   # the last-good record into $good. 0 read; 1 none recorded (empty); 2 the record holds something unreadable (not a sha, or a commit this checkout does not know)
    local g; g="$(cat "$LAST_GOOD" 2>/dev/null)"; good=""
    [ -n "$g" ] || return 1
    { [[ "$g" =~ ^[0-9a-f]{7,64}$ ]] && git cat-file -e "$g^{commit}" 2>/dev/null; } || return 2
    good="$g"
}
record_unreadable() {   # the record is never overwritten when it cannot be read (it may name a newer commit than any this checkout has): said to the keeper
    say "$LAST_GOOD holds something this checkout cannot read as a commit; left alone"
    tell "[release] PR #$pr: the last-good record $LAST_GOOD holds '$(head -c 80 "$LAST_GOOD" 2>/dev/null | tr -d '\n')', which is not a commit this checkout knows. It is left alone, and releases take the old path (main's run first) until it is fixed: delete the file to start again from the deployed HEAD"
}
record_good() {   # $1 = a commit main's run passed on. Read, compare and write under flock on $LAST_GOOD.lock; atomic; never back to an older commit.
    local rc          # 2: the record is unreadable (left alone, told); 3: the lock could not be had; 4: the write failed; the last two are told as well
    (
        flock -w 30 8 || exit 3
        cur="$(cat "$LAST_GOOD" 2>/dev/null)"
        if [ -n "$cur" ]; then
            { [[ "$cur" =~ ^[0-9a-f]{7,64}$ ]] && git cat-file -e "$cur^{commit}" 2>/dev/null; } || exit 2
            git merge-base --is-ancestor "$1" "$cur" 2>/dev/null && exit 0
        fi
        printf '%s\n' "$1" > "$LAST_GOOD.$$" && mv -f "$LAST_GOOD.$$" "$LAST_GOOD" || { rm -f "$LAST_GOOD.$$"; exit 4; }
    ) 8>>"$LAST_GOOD.lock"; rc=$?
    case $rc in
        0) return 0 ;;
        2) record_unreadable ;;
        3) say "could not take $LAST_GOOD.lock"; tell "[release] PR #$pr: could not take $LAST_GOOD.lock within 30 s, so ${1:0:7}, whose run on main passed, is not recorded as the last good commit" ;;
        *) say "could not write $LAST_GOOD"; tell "[release] PR #$pr: could not write $LAST_GOOD, so ${1:0:7}, whose run on main passed, is not recorded as the last good commit" ;;
    esac
    return $rc
}
failed_runs() {   # the main push runs that FAILED on a commit in $1..$2: "<run> <sha>" per line and a last line "ok"; "unreadable" when GitHub's answer cannot be read, its pages (up to 10 of 100
                  # runs, newest first) do not reach a run at or before $1, or a run in the range was cancelled after its job started (a "cancelled <run> <sha>" line before it: unknown); a caller takes anything but a last line "ok" (empty, a crash) as unreadable too
    FROM="$1" TIP="$2" REPO="$REPO" python3 -c '
import json, os, subprocess
def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None
good, tip, R = os.environ["FROM"], os.environ["TIP"], os.environ["REPO"]
rng = sh("git", "rev-list", good + ".." + tip)
if rng is None: print("unreadable"); raise SystemExit
rng = set(rng.split()); fails = []; reached = False
for page in range(1, 11):
    try: runs = json.loads(sh("gh", "api", f"repos/{R}/actions/workflows/tests.yml/runs?branch=main&event=push&per_page=100&page={page}"))["workflow_runs"]
    except Exception: print("unreadable"); raise SystemExit
    if not runs: break
    for r in runs:
        sha = r.get("head_sha")
        if sha in rng and r.get("conclusion") in ("failure", "timed_out", "startup_failure"): fails.append(str(r["id"]) + " " + sha)
        if sha in rng and r.get("conclusion") == "cancelled":   # the fast path stays careful: cancelled while queued (no step ran) was replaced by a newer run; after its job started it says nothing, so unknown
            v = sh("gh", "run", "view", str(r["id"]), "--repo", R, "--json", "status,conclusion,jobs")
            try: started = any(j.get("steps") for j in (json.loads(v).get("jobs") or []))
            except Exception: print("unreadable"); raise SystemExit
            if started: print("cancelled", r["id"], sha); print("unreadable"); raise SystemExit
        if sha and (sha == good or subprocess.run(["git", "merge-base", "--is-ancestor", sha, good], capture_output=True).returncode == 0): reached = True
    if reached: break
if not reached: print("unreadable")
else:
    for f in fails: print(f)
    print("ok")'
}
# The fast-ok ledger (the owner's rule: main's full run never blocks a release): the merge commits release.sh itself made on a passing PR check, on a head that contained the main tip it merged
# onto (2c), main's tip being exactly the merge of that tip and the head afterwards (merge_commit). fast_gate (a) counts the live checkout as at the tip when everything between it and the
# tip is such a merge or docs-only. A merge of the old path because the branch was not up to date does not qualify (its checks did not run on main's tip), and a merge that a failed run
# took out does not stay: a rollback, or a failed run on the old path, removes the entries it takes out. One JSON file {"v": 1, "merges": {"<sha>": {"pr": N, "epoch": T}}}, replaced
# whole (temp file and rename). A file that is not that shape is never written over and never trusted: the gate behaves as it did before the ledger.
LEDGER_PY='
import json, os, re, sys, time
op, path, *args = sys.argv[1:]
try:
    if os.path.exists(path):
        d = json.load(open(path)); m = d["merges"]
        isint = lambda x: isinstance(x, int) and not isinstance(x, bool)
        if not (d.get("v") == 1 and isinstance(m, dict) and all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", k) and isinstance(v, dict) and isint(v.get("epoch")) and isint(v.get("pr")) for k, v in m.items())): raise ValueError("shape")
    else: m = {}
except Exception: sys.exit(2)
if op == "read":
    print("\n".join(m)); sys.exit(0)
if op == "add":
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", args[0]): sys.exit(4)
    m[args[0]] = {"pr": int(args[1]), "epoch": int(time.time())}
else:
    for sha in args: m.pop(sha, None)
for sha in os.environ.get("LEDGER_PRUNE", "").split(): m.pop(sha, None)      # the merges already deployed or at or before the last good commit: the caller found them
now = int(time.time())
for sha in [k for k, v in m.items() if now - v["epoch"] > 30 * 86400]: del m[sha]      # a merge a month behind the tip is not one: kept small
for sha in sorted(m, key=lambda k: m[k]["epoch"])[:-200]: del m[sha]
tmp = "%s.%d" % (path, os.getpid())     # created here, with the flock held by the caller for as long as this runs
try:
    with open(tmp, "w") as f: json.dump({"v": 1, "merges": m}, f, indent=1); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
except Exception:
    try: os.unlink(tmp)
    except OSError: pass
    sys.exit(4)'
ledger_read() {   # the recorded merges, one full sha per line, on stdout. 0 readable (no file is an empty ledger); 1 the file exists and cannot be read as a ledger
    [ -e "$LEDGER" ] || return 0
    python3 -c "$LEDGER_PY" read "$LEDGER" 9>&- 7>&- 6>&- || return 1
}
ledger_edit() {   # $1 = add (then $2 = the merge commit, $3 = its PR) | drop (then the commits to take out). Under flock on $LEDGER.lock (fd 8; the deploy lock is held as well at the merge and at a rollback), atomic.
                  # Every write also takes out the entries that are no use any more: a merge that is an ancestor of the live HEAD (deployed already) or of the last-good commit
    local rc      # 0 done; 2 the file is unreadable (left alone); 3 the lock could not be had; 4 the write failed
    mkdir -p "$(dirname "$LEDGER")" 2>/dev/null
    (
        flock -w 30 8 || exit 3
        local prune="" lg e ents=""; lg="$(cat "$LAST_GOOD" 2>/dev/null)"; [[ "$lg" =~ ^[0-9a-f]{7,64}$ ]] || lg=""
        [ ! -e "$LEDGER" ] || ents="$(python3 -c "$LEDGER_PY" read "$LEDGER" 9>&- 7>&- 6>&-)" || ents=""   # unreadable: the edit below says so (exit 2) and writes nothing
        for e in $ents; do   # a commit this checkout does not know is kept (not provably old)
            if git merge-base --is-ancestor "$e" HEAD 2>/dev/null || { [ -n "$lg" ] && git merge-base --is-ancestor "$e" "$lg" 2>/dev/null; }; then prune="$prune $e"; fi
        done
        LEDGER_PRUNE="$prune" python3 -c "$LEDGER_PY" "$1" "$LEDGER" "${@:2}" 9>&- 7>&- 6>&-
    ) 8>>"$LEDGER.lock"; rc=$?
    return $rc
}
ledger_add() {   # $1 = a merge commit made on a passing PR check and an up-to-date head, $2 = its PR. Never fails the release: what is not recorded just does not ride along
    ledger_edit add "$1" "$2"; case $? in
        0) say "recorded the merge ${1:0:7} in the fast-ok ledger (the PR's checks passed on a head that contained main's tip): a later release may count the live checkout as at the tip while it is not deployed" ;;
        2) say "the fast-ok ledger $LEDGER cannot be read as a ledger; left alone, nothing rides along until it is fixed (delete the file to start again)" ;;
        *) say "the merge ${1:0:7} could not be recorded in the fast-ok ledger $LEDGER; it will not ride along" ;;
    esac
}
ledger_drop() {   # the commits a failed run or a rollback takes out. When they cannot be taken out (the lock, the write) the whole ledger goes: nothing rides along rather than a failed commit
    local n=$#
    [ "$n" -gt 0 ] || return 0
    ledger_edit drop "$@"; case $? in
        0) ;;
        2) say "the fast-ok ledger $LEDGER cannot be read as a ledger; left alone, nothing rides along until it is fixed (delete the file to start again)" ;;
        *) rm -f "$LEDGER"; say "could not take $n commit(s) out of the fast-ok ledger $LEDGER: the ledger is removed, so nothing rides along until releases fill it again" ;;
    esac
}
fm_pysrc() {   # docs-merge.sh's own checker (its allow-list of what no test can exercise: docs, comments, runner settings), read out of the script, so that there is one list and not two
    local f="${DOCS_MERGE_SCRIPT:-$(python3 config.py get paths.docs_merge_script 2>/dev/null || true)}"; f="${f/#\~/$HOME}"; [ -n "$f" ] && [ -r "$f" ] || return 1
    awk '/^PYSRC=\$\(cat <<.PYEOF.$/ {on=1; next} /^PYEOF$/ {on=0} on' "$f"
}
docs_only_between() {   # $1 = the live HEAD, $2 = main's tip: every commit on the way is one docs-merge.sh would have merged without CI (and so nothing a test could fail on rides along). Fails closed
                        # $3 (optional) = the fast-ok ledger's merges, space-separated full shas: one of them on the way is accepted without the checker (its PR's checks ran on a head that contained the tip it merged onto,
                        # and the commits it brings in are its PR's own). Sets $ride_n, how many of those there were
    ride_n=0
    git merge-base --is-ancestor "$1" "$2" || return 1
    local -a cs; mapfile -t cs < <(git rev-list --first-parent --reverse "$1..$2" 2>/dev/null)
    [ "${#cs[@]}" -gt 0 ] && [ "${#cs[@]}" -le 20 ] || return 1
    local src="" tmp="" c rc=0 n
    for c in "${cs[@]}"; do   # paths unquoted
        case " ${3:-} " in *" $c "*) ride_n=$((ride_n+1)); continue ;; esac
        if [ -z "$tmp" ]; then   # the first commit that needs the checker: its allow-list is read now, so a run of ledger merges alone needs no docs-merge.sh
            src="$(fm_pysrc)"; { [ -n "$src" ] && [[ "$src" == *"def diff_check"* ]]; } || { rc=1; break; }
            tmp="$(mktemp -d)" || { rc=1; break; }
        fi
        # paths unquoted (core.quotePath=false) and the prefixes fixed, whatever the config: the checker's regex reads "diff --git a/<path> b/<path>" and skips any other header
        git -c core.quotePath=false diff --no-color --no-ext-diff --no-renames --src-prefix=a/ --dst-prefix=b/ "$c^1" "$c" > "$tmp/diff" 2>/dev/null || { rc=1; break; }
        n="$(grep -c '^diff --git ' "$tmp/diff")"
        # do not trust the exit code alone (an unknown subcommand exits 0 doing nothing): its own summary line must say it saw every file in the diff and refused none
        python3 -I -c "$src" diff-check "$tmp/diff" "$REPO" "$c" "$tmp" > "$tmp/out" 2>&1 || { rc=1; break; }
        { [ "$n" -ge 1 ] && grep -qx "files=$n refused=0" "$tmp/out"; } || { rc=1; break; }
    done
    [ -z "$tmp" ] || rm -rf "$tmp"; return $rc
}
fast_gate() {   # $1 = main's tip ($base). What a deploy at the merge may carry along is only the PR (the coordinator's review): (a) the live checkout is at main's
                # tip, so everything on main is deployed already, nothing merged and waiting on its run (an old-path release) and no rolled-back commit rides along (behind it only by merges
                # release.sh made itself on a passing PR check and an up-to-date head, the fast-ok ledger, or by docs-only merges, counts as at the tip); and (b) no
                # commit after the last good one has a failed run on main. A run still pending is fine: back-to-back releases stay fast, and a failure of the first rolls both back.
                # Sets $good (the last good commit to roll back to), or $fast_why
    local cur st rid verdict rsha detail bad rg cn led=""; cur="$(git rev-parse HEAD)"
    [ -z "$pv_block" ] || { fast_why="$pv_block"; return 1; }
    if [ "$cur" != "$1" ]; then   # behind by documentation-only merges (docs-merge.sh's allow-list) is as good as at the tip: they are not deployed by a release and nothing can fail on them;
        # so are the merges release.sh made on a passing PR check and an up-to-date head (the ledger): the PR's checks vouched for them as they do for a deploy at the merge, and main's run for this
        # release's merge covers them. A ledger that cannot be read is no ledger (a fail-closed fall back to docs-only alone, as before)
        led="$(ledger_read)" || { led=""; say "the fast-ok ledger $LEDGER cannot be read as a ledger: no ride-along, only docs-only merges count"; }
        local k keep=""; for k in $led; do git merge-base --is-ancestor "$cur" "$k" 2>/dev/null && keep="$keep $k"; done   # only a merge that descends from the live checkout can be on the way to the tip
        led="$keep"
        if docs_only_between "$cur" "$1" "$led"; then
            if [ "$ride_n" -gt 0 ]; then say "the live checkout (${cur:0:7}) is behind main's tip ${1:0:7} only by $ride_n merge(s) release.sh made on a passing PR check and an up-to-date head (the fast-ok ledger), and by merges docs-merge.sh accepts, if any; they ride along"
            else say "the live checkout (${cur:0:7}) is behind main's tip ${1:0:7} only by merges docs-merge.sh accepts (docs, comments, runner settings); they ride along"; fi
        else fast_why="(a) the live checkout (${cur:0:7}) is not at main's tip ${1:0:7}: something merged and not deployed yet (a release waiting on its run, or a commit rolled back) would ride along, and it is neither a merge of the fast-ok ledger nor docs-only"; return 1; fi
    fi
    read_good; rg=$?
    if [ $rg = 2 ]; then fast_why="the last-good record is unreadable"; record_unreadable; return 1
    elif [ $rg = 1 ]; then   # first use: the deployed HEAD is the last good commit when its run on main passed
        st="$(run_state "$cur")"; read -r rid verdict rsha detail <<< "$st"
        if [ "$verdict" != pass ]; then fast_why="no last-good commit is recorded and the run on main for the deployed ${cur:0:7} is not known to have passed (${verdict:-no run found}), so there is nothing to roll back to"; return 1; fi
        record_good "$cur" || { fast_why="the deployed ${cur:0:7} could not be recorded as the last good commit"; return 1; }
        good="$cur"; say "no last-good commit was recorded: seeded with the deployed ${cur:0:7}, whose run $rid on main passed"
    fi
    git merge-base --is-ancestor "$good" "$cur" || { fast_why="the last-good commit ${good:0:7} is not in the deployed history (${cur:0:7})"; return 1; }
    bad="$(failed_runs "$good" "$1")"
    if [ "$(echo "$bad" | tail -1)" != ok ]; then
        cn="$(echo "$bad" | grep '^cancelled ' | head -1)"
        if [ -n "$cn" ]; then fast_why="(b) a commit after the last good one (${good:0:7}) has a run on main cancelled after its job started (${cn#cancelled } as run and commit): unknown, not vouched for"
        else fast_why="(b) the runs on main since the last good commit ${good:0:7} cannot be read, or do not reach it"; fi
        return 1
    fi
    bad="$(echo "$bad" | sed '$d' | head -1)"
    if [ -n "$bad" ]; then fast_why="(b) a commit after the last good one (${good:0:7}) has a failed run on main (run ${bad%% *} on ${bad#* })"; return 1; fi
}
record_pass_live() {   # $1 = a commit deployed at the merge whose main run passed. Under the deploy lock (a rollback holds it for the reset, so none lands between the check and the record):
                       # 0 it is in the live checkout and is recorded as the last good commit; 1 it is not (rolled back meanwhile): nothing recorded; 2 the lock was not had in $LOCK_WAIT s: not recorded, told
    local rc=0
    exec 9>>"$LOCK_FILE" || { exec 9>&-; return 2; }
    flock -w "$LOCK_WAIT" 9 || { exec 9>&-; return 2; }
    if git merge-base --is-ancestor "$1" HEAD; then record_good "$1" || true; else rc=1; fi
    exec 9>&-; return $rc
}
mg_stop() {   # $1 = fail|unknown, $2 = why. Before the deploy it fails the release; after the fast deploy it returns 1 for the caller to decide
    mg_kind="$1"; mg_why="$2"
    if [ "$mg_mode" != post ]; then
        [ "$1" != unknown ] || q_fail=none   # a main run that could not be read is not a failure of the code: it ends this release as before, but does not pause the release queue
        fail "main's tests" "$2: merged, not deployed"
    fi
    return 1
}
main_green() {   # $1 = pre|post, $2 = M, the merge commit of the release; the rule is in the comment above run_state
    local mg_mode="${1:-pre}" m="${2:-}" steps_run="" steps_start=0 steps_waited=0 ci_line="" ci_st="" ci_what="" ci_said=0 t0 now waited=0 run_start=0 run_waited=0 fetch_since="" fetch_waited=0 cur_run="" out rid verdict rsha detail err via="" by="" cnote="" cn_said=0 pn_said=0
    t0="$(date +%s)"   # the waits are read off the clock, not counted in sleeps: a poll takes time too, so 3 h is 3 h
    mg_kind=""; mg_why=""; mg_rid=""; mg_rsha=""; mg_notlive=""
    [[ "$m" =~ ^[0-9a-f]{7,64}$ ]] || { mg_stop unknown "no merge commit to look for on main"; return 1; }
    while :; do
        now="$(date +%s)"; waited=$((now - t0))
        if ci_line="$(ci_going "$m" main)"; then
            # salamander's CI-run poller lists main's push run of M still going: no fetch and no GitHub call this cycle, the run is pending exactly as run_state would say (its id is the
            # run's databaseId, so the WAIT_MAIN clock below goes on across a switch between the two). A completed run, none listed, no file, a stale or unreadable one, or no salamander:
            # the read below, which alone decides pass or fail.
            read -r rid ci_st ci_what <<< "$ci_line"; verdict=pending; rsha="$m"; detail="$ci_st"; via=""; cnote=""
            [ $((now - ci_said)) -lt 300 ] || { ci_said=$now; say "main's run $rid on ${m:0:7}: $ci_what; waiting on the ci-runs file, no GitHub call"; }
        else
        if ! err="$(git fetch --quiet origin main 2>&1)"; then   # another release's fetch in this checkout can race this one (git: "incorrect old value
            err="$(echo "$err" | tail -1 | sed -E 's#//[^/@]*@#//#')"   # provided"); that, or a network blip, is waited out like a pending run
            [ -n "$fetch_since" ] || fetch_since=$now; fetch_waited=$((now - fetch_since))
            [ $fetch_waited -lt $WAIT_MAIN ] || { mg_stop unknown "cannot fetch main from origin for $((WAIT_MAIN/60)) min (${err:-git said nothing})"; return 1; }
            say "cannot fetch main from origin (${err:-git said nothing}); trying again in 20 s"
            sleep 20; continue
        fi
        fetch_since=""
        out="$(run_state "$m")"
        read -r rid verdict rsha detail <<< "$out"
        via=""; [ "$rsha" = "$m" ] || via=", on ${rsha:0:7}, which contains ${m:0:7}"
        cnote=""
        fi
        if [ "$verdict" = pending ] && [ "$detail" = steps ]; then   # the run is completed and green but GitHub has not filled in its step results yet: read again at the next poll, WAIT_STEPS at most (from the first look that saw the gap on this run); past it, a failure like any other, so the ride-along and rollback handling below apply
            [ "$rid" = "$steps_run" ] || { steps_run="$rid"; steps_start=$now; say "main's run $rid on ${rsha:0:7} is completed and green, but GitHub has not filled in its step results yet: reading it again every $POLL_MAIN s, for $((WAIT_STEPS/60)) min at most"; }
            steps_waited=$((now - steps_start))
            [ $steps_waited -lt $WAIT_STEPS ] || { verdict=fail; detail="finished successfully, but its step results never arrived in $((steps_waited/60)) min: no conclusion for \"run every suite, measured\""; }
        else steps_run=""   # any other state ends the gap: a re-run keeps the run id, so a later gap on it starts a fresh wait, never from the old start
        fi
        case "$verdict" in
            pass)
                if [ "$mg_mode" = post ]; then
                    record_pass_live "$m"; case $? in   # the check that it is live and the record, in one hold of the deploy lock
                        1) mg_notlive="no longer in the live checkout"; [ ! -f "$ROLLED_MARK" ] || mg_notlive="rolled back with $(cat "$ROLLED_MARK")"   # a rollback (this release's or another's) took it out while it waited for its run: it passed, it is not live
                           rm -f "$ROLLED_MARK"
                           say "main's tests passed on ${m:0:7} (run $rid$via), but it is not live: $mg_notlive"
                           return 0 ;;
                        2) say "main's tests passed on ${m:0:7} (run $rid$via), but the deploy lock was not free for $LOCK_WAIT s: not recorded as the last good commit"
                           tell "[release] PR #$pr: main's tests passed on ${m:0:7}, but the deploy lock was not free for $LOCK_WAIT s, so it is not recorded as the last good commit (the next pass on a newer commit records it)" ;;
                    esac
                    rm -f "$ROLLED_MARK"   # a marker left from before it was released again is stale
                    say "main's tests passed on ${m:0:7} (run $rid$via)"
                else
                    say "main's tests pass at ${rsha:0:7} (run $rid$via)"; verified="$rsha"
                    [ "$rsha" = "$m" ] || say "deploying ${rsha:0:7}, the newest commit containing the merge ${m:0:7} whose run passed"
                    record_good "$rsha"
                fi
                if [ -n "$detail" ]; then
                    audit_note="; every suite passed on main, but $detail (https://github.com/$REPO/actions/runs/$rid)"
                    say "main's run: $detail: the report goes to the keeper"
                fi
                return 0 ;;
            fail) mg_rid="$rid"; mg_rsha="$rsha"
                  ledger_drop "$m"   # a merge whose run failed never rides along; the rollback of a fast deploy takes out the rest
                  by=""; [ "$rsha" = "$m" ] || by="; ${rsha:0:7} is the oldest commit after the merge ${m:0:7} whose run failed, and no run on ${m:0:7} or between them passed, so that run decided it"
                  if [ "$mg_mode" = pre ] && git merge-base --is-ancestor "$m" HEAD; then
                      # the merge waited for its own run on the old path, but a release deployed at its merge on top of it (it rode along) and the live checkout contains it now. It is LIVE, not
                      # "merged, not deployed": the same rollback as after a fast deploy, which takes the rider out with it; its own run would only find out up to an hour later
                      verified="$m"; mg_kind=fail; live_ride=1
                      mg_why="a release deployed on top of this merge while it waited for its run, so it went live with that one and was not only merged; the run on main for ${rsha:0:7} failed ($detail; https://github.com/$REPO/actions/runs/$rid)$by"
                      say "main's run failed on ${m:0:7}, which is live via a ride-along: rolling it back"
                      rollback   # never returns
                  fi
                  mg_stop fail "the run on main for ${rsha:0:7} failed ($detail; https://github.com/$REPO/actions/runs/$rid)$by"; return 1 ;;
            pending) if [ "$detail" = running ]; then   # the limit counts from the start of the run going: a different one going starts it again
                         [ "$rid" = "$cur_run" ] || { cur_run="$rid"; run_start=$now; }
                         run_waited=$((now - run_start))
                         # a covering run going, read from GitHub (the ci-runs arm above has its own line, so it is left out here): this arm used to log nothing, so after a cancelled run on M the log stayed
                         # silent for as long as the later run took. A line every 5 min, like the canceled line below. Not "no GitHub call": each look here reads main's run list from GitHub (a cached read inside GH_TTL), and the line says so
                         [ -n "$ci_line" ] || [ $((now - pn_said)) -lt 300 ] || { pn_said=$now; say "main's run $rid is running${via:-, on ${m:0:7}} ($((run_waited/60)) min so far); waiting for it to finish, reading main's runs from GitHub every $POLL_MAIN s"; }
                     fi ;;
            cancelled) cnote="; the run $rid on ${rsha:0:7} was cancelled and no later run covers ${m:0:7}"
                       # only cancelled runs cover M (a newer push to main cancelled them): this arm used to log nothing, so the log was silent until a later run appeared.
                       # A line every 5 min, like the ci-runs line above. Not "no GitHub call": each look here reads main's run list from GitHub (a cached read inside GH_TTL), and the line says so
                       [ $((now - cn_said)) -lt 300 ] || { cn_said=$now; say "main's runs covering ${m:0:7} were canceled (run $rid on ${rsha:0:7}, the newest one); waiting for a later main run that contains it, reading main's runs from GitHub every $POLL_MAIN s"; } ;;
        esac
        if [ $waited -ge $CAP_MAIN ] || [ $run_waited -ge $WAIT_MAIN ]; then   # one line names both limits
            mg_stop unknown "no finished run on main covers ${m:0:7} after $((waited/60)) min since the merge (the cap is $((CAP_MAIN/60)) min) and $((run_waited/60)) min since a covering run started (the limit is $((WAIT_MAIN/60)) min)$cnote"; return 1
        fi
        sleep $POLL_MAIN
    done
}

pending_set() {   # $1 = the commit deployed at the merge, $2 = its PR. A record under $PENDING_DIR, and its flock (fd 7) held for as long as this process lives: when the process is killed the lock is gone, which is how the next start knows
    mkdir -p "$PENDING_DIR" 2>/dev/null; PENDING_FILE="$PENDING_DIR/pr-$2"
    if exec 7>>"$PENDING_FILE" && flock -w 2 7; then printf 'sha=%s\npr=%s\nepoch=%s\ntime=%s\n' "$1" "$2" "$(date +%s)" "$(date -u +%FT%TZ)" > "$PENDING_FILE"
    else exec 7>&-; PENDING_FILE=""; say "cannot write the pending-verify record under $PENDING_DIR: a kill of this release before main's run is read would go unreported"
        tell "[release] PR #$2: could not write the pending-verify record under $PENDING_DIR, so if this release is killed before main's run for ${1:0:7} is read, nothing will report it"; fi
}
pending_clear() { [ -z "$PENDING_FILE" ] || { rm -f "$PENDING_FILE"; exec 7>&-; PENDING_FILE=""; }; }
verify_pending() {   # $1 = a stale record's file, $2 = the commit, $3 = its PR, $4 = when it was deployed (epoch): one look at the commit's main run (no waiting). Sets $pv_block while the fast path must not run
    local out rid verdict rsha detail age=$(( $(date +%s) - ${4:-0} )) lg="$LOGDIR/pr-$3.log" why
    say "PR #$3 was deployed at the merge as ${2:0:7} and its release process ended before main's run was read: looking at that run now"
    echo "$(date -u +%FT%TZ) its release process ended before main's run was read; the release of PR #$pr looked at it" >> "$lg"
    git fetch --quiet origin main 2>/dev/null || true
    out="$(run_state "$2")"; read -r rid verdict rsha detail <<< "$out"
    local old=0; [ "$age" -le "$CAP_MAIN" ] || old=1   # the cap (3 h): the longest a live release waits for a covering run, so a record older than that has no watch left to come back
    if [ "$verdict" = cancelled ]; then verdict=""; out="the run $rid on ${rsha:0:7} was cancelled and no later run covers it"; fi   # a cancelled run says nothing: read like no run yet
    if [ "$verdict" = pending ] && [ $old = 1 ]; then verdict=""; out="still pending after $((age/60)) min"; fi
    if [ -z "$verdict" ] && [ $old = 0 ]; then   # "none": no run yet, or GitHub could not be read: never a final verdict, kept like a pending one until the same age
        pv_block="the deploy of PR #$3 at ${2:0:7} has not been verified (its release process ended, and no run for it could be read yet)"
        say "$pv_block: no fast path until it is read"; return 0
    fi
    [ "$out" != none ] || out="no run found for it in $((age/60)) min"
    case "$verdict" in
        pass) record_pass_live "$2"; case $? in
                  0) say "main's tests passed on ${2:0:7} (run $rid): recorded as the last good commit"; released "$3" "$2" ;;
                  1) say "main's tests passed on ${2:0:7} (run $rid); it is not in the live checkout, so nothing recorded" ;;
                  *) say "main's tests passed on ${2:0:7} (run $rid), but the deploy lock was not free: not recorded"; return 0 ;;   # the record stays: the next start tries again
              esac
              [ -z "$detail" ] || tell "[release] PR #$3 deployed at ${2:0:7}; every suite passed on main, but $detail (https://github.com/$REPO/actions/runs/$rid) · log $lg"
              rm -f "$1" ;;
        pending) pv_block="the deploy of PR #$3 at ${2:0:7} has not been verified (its release process ended, and main's run $rid is $([ "$detail" = steps ] && echo "finished, but its step results are not filled in yet" || echo "still going"))"
                 say "$pv_block: no fast path until it is read" ;;   # the record stays
        fail) say "the run on main for ${rsha:0:7} failed ($detail): rolling back as its own release would have"
              local mk="$PENDING_DIR/.done.$$"; rm -f "$mk"
              (   # the same rollback a live watch makes, reporting for that PR; fail() inside it ends only this subshell. It writes $RB_DONE only when it got to a verdict
                  pr="$3"; log="$lg"; ROLLED_MARK="$LOGDIR/pr-$3.rolledback"; verified="$2"; mg_kind=fail; q_fail=pause; mg_rsha="$rsha"; recycle=""; rc_note=""; recovered=1; RB_DONE="$mk"
                  qstart=0; q_started_pr "$3" && qstart=1   # only a PR the queue started pauses it (a plain release.sh N that failed while the queue was in use pauses nothing)
                  mg_why="the run on main for ${rsha:0:7} failed ($detail; https://github.com/$REPO/actions/runs/$rid)"
                  PENDING_FILE=""; rollback
              )
              if [ -e "$mk" ]; then rm -f "$mk" "$1"; pv_block="the deploy of PR #$3 at ${2:0:7} failed main's run (its release process ended before it was read) and was dealt with by this release (see its report)"
              else pv_block="the deploy of PR #$3 at ${2:0:7} failed main's run (its release process ended before it was read) and this release could not roll it back (see its report); the record is kept for the next start"; fi
              say "$pv_block" ;;
        *) pv_block="the deploy of PR #$3 at ${2:0:7} has an unread verdict (its release process ended before main's run was read, and no run could be read: $out)"
           tell "[release] PR #$3 FAILED at main's tests: deployed at ${2:0:7} and NOT rolled back, main's run was not read (its release process ended; $out); look at it · log $lg"; rm -f "$1" ;;
    esac
}
recover_pending() {   # a record whose lock is free belongs to a release process that is gone: finish its main-run check first (fail, unknown: red report, no fast path; pass: recorded)
    local f pv_sha pv_pr pv_epoch k v e; local -a order
    pv_block=""; [ -d "$PENDING_DIR" ] || return 0
    mapfile -t order < <(for f in "$PENDING_DIR"/pr-*; do [ -f "$f" ] || continue; e="$(sed -n 's/^epoch=//p' "$f" | head -1)"; echo "${e:-0} $f"; done | sort -n -k1,1 | cut -d' ' -f2-)
    for f in "${order[@]}"; do   # oldest deploy first
        exec 6<"$f" || continue
        if flock -n 6; then   # held: a live watch, or another start recovering it
            pv_sha=""; pv_pr=""; pv_epoch=""
            while IFS='=' read -r k v; do case "$k" in sha) pv_sha="$v" ;; pr) pv_pr="$v" ;; epoch) pv_epoch="$v" ;; esac; done < "$f"
            if [[ "$pv_sha" =~ ^[0-9a-f]{7,64}$ ]] && [[ "$pv_pr" =~ ^[0-9]+$ ]]; then verify_pending "$f" "$pv_sha" "$pv_pr" "$pv_epoch"; fi
        fi
        exec 6<&-
    done
}
fetch_retry() {   # git fetch of main (and the refs in "$@"), three tries: another release's fetch in this checkout can race it ("incorrect old value provided")
    local try
    for try in 1 2 3; do git fetch --quiet origin main "$@" 2>/dev/null && return 0; [ $try = 3 ] || sleep 2; done
    return 1
}
regen_snapshot() {   # 2a': $1 = the step it is for (mergeable | update-branch). A PR that conflicts with main on the generated tests/tool_text.snapshot.json alone is mended here: tools/snapshot_regen.py merges
                     # main into the PR head in a temporary worktree, and only if that file is the SOLE conflicted path takes main's copy, regenerates it (tool_text.py update, then check), commits the merge and
                     # pushes it to the PR branch (plain push, never forced). 0 = pushed (the caller waits for the head to move); 1 = not done, the reason in the log: the caller fails as it always did.
                     # Bounded by REGEN_MAX per release ($regens). Uses git only (the fetch, the push): no GitHub API call. Runs inside run(): view, pr, regens are its
    local step="$1" branch cross head res
    if [ "$regens" -ge "$REGEN_MAX" ]; then say "$step: the tool-text snapshot was regenerated $regens time(s) in this release already (RELEASE_REGEN_MAX=$REGEN_MAX); not again"; return 1; fi
    [ -f "$SNAPSHOT_REGEN" ] || { say "$step: no snapshot regeneration here ($SNAPSHOT_REGEN is missing)"; return 1; }
    branch="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("headRefName") or "")')"
    cross="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("isCrossRepository") is True)')"
    head="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("headRefOid") or "")')"
    [ -n "$branch" ] && [ "$cross" = False ] && [[ "$head" =~ ^[0-9a-f]{7,64}$ ]] || { say "$step: the snapshot is not regenerated: the PR's branch is not one this repository can push to (branch '$branch', cross-repository $cross)"; return 1; }
    fetch_retry "refs/pull/$pr/head" || { say "$step: the snapshot is not regenerated: cannot fetch main and the PR head from origin"; return 1; }
    regens=$((regens+1))
    say "$step: the PR conflicts with main; looking for a conflict in tests/tool_text.snapshot.json alone (regeneration $regens of $REGEN_MAX): merging main into ${head:0:7} in a temporary worktree"
    res="$(python3 "$SNAPSHOT_REGEN" --repo "$HERE" --branch="$branch" --head "$head" </dev/null)" || true   # stdout (the verdict line) captured; stderr (the helper's details) goes to the log
    res="$(echo "$res" | tail -1)"
    case "$res" in
        "pushed "*) say "$step: the only conflicted path was tests/tool_text.snapshot.json: took main's, regenerated it (tool_text.py update, check passed), and pushed the merge ${res#pushed } to $branch"; return 0 ;;
        *) say "$step: the snapshot is not regenerated: ${res:-no answer from $SNAPSHOT_REGEN}"; return 1 ;;
    esac
}
up_to_date() {   # $1 = pr, $2 = the head its checks ran on. 0 when main's tip is an ancestor of that head: $base is the tip; else $fast_why says why not and $utd_kind is
                 # "behind" (main's tip is read, the head is read, and the head does not contain it: update-branch brings it up to date) or "unknown" (something could not be read)
    base=""; utd_kind="unknown"
    fetch_retry "refs/pull/$1/head" || { fast_why="cannot fetch main and the PR head from origin"; return 1; }
    base="$(git rev-parse --verify --quiet 'origin/main^{commit}')"
    [ -n "$base" ] || { fast_why="cannot read main's tip"; return 1; }
    git cat-file -e "$2^{commit}" 2>/dev/null || { fast_why="the PR head ${2:0:7} is not among the fetched commits (the PR was pushed to since?)"; return 1; }
    git merge-base --is-ancestor "$base" "$2" || { utd_kind=behind; fast_why="the branch is behind main: main's tip ${base:0:7} is not in the history of the PR head ${2:0:7}"; return 1; }
    utd_kind=""
}
tests_on_head() {   # 0 when the tests job ($TESTS_CHECK) has a completed, successful check run on $headsha itself (GitHub's check-runs of that commit); anything else, or unreadable: 1
    gh api "repos/$REPO/commits/$headsha/check-runs?per_page=100" 2>/dev/null | NEED="$TESTS_CHECK" python3 -c '
import json,os,sys
try: runs = json.load(sys.stdin)["check_runs"]
except Exception: sys.exit(1)
sys.exit(0 if any(r.get("name") == os.environ["NEED"] and r.get("status") == "completed" and r.get("conclusion") == "success" for r in runs) else 1)'
}
gh_cached() {   # $1 = a salt (the PR head the answer is about), then gh's arguments. The answer of the last GH_TTL s (any release on this box asked it; <state>/releases/gh-cache, the folder run_state uses) is reused; only a successful, non-empty answer is kept; a failed call prints nothing and returns its status
    SALT="$1" GH_CACHE="$GH_CACHE" GH_TTL="$GH_TTL" python3 -c '
import hashlib, os, subprocess, sys, time
a = sys.argv[1:]; CD, TTL = os.environ.get("GH_CACHE", ""), float(os.environ.get("GH_TTL") or 0)
f = os.path.join(CD, hashlib.sha1("\0".join((*a, os.environ["SALT"])).encode()).hexdigest()) if CD and TTL > 0 else ""
if f:
    try:
        if time.time() - os.stat(f).st_mtime < TTL: sys.stdout.write(open(f, encoding="utf-8").read()); sys.exit(0)
    except OSError: pass
r = subprocess.run(["gh", *a], capture_output=True, text=True)
if r.returncode != 0: sys.exit(r.returncode)
if f and r.stdout.strip():
    try:
        os.makedirs(CD, mode=0o700, exist_ok=True); t = f + ".%d.tmp" % os.getpid()
        open(t, "w", encoding="utf-8").write(r.stdout); os.replace(t, f)
        for n in os.listdir(CD):
            q = os.path.join(CD, n)
            if time.time() - os.stat(q).st_mtime > 3600: os.unlink(q)
    except OSError: pass
sys.stdout.write(r.stdout)' "${@:2}"
}
wait_pr_checks() {   # $1 = the step a failure is named for (checks: the first wait; pr tests: the wait on an updated head), $2 = quiet|progress, $3 = what the log says on a pass. Waits up to WAIT_CHECKS, polled every POLL_PR s (60)
    local step="$1" mode="$2" okmsg="$3" waited=0 checks verdict ci_line
    while :; do
      # salamander's CI-run poller lists a run of this head still going: nothing to ask GitHub this cycle, the wait goes on exactly as a pending check would make it. Only "still going" comes from
      # the file; a finished run, none listed, no file, a stale or unreadable one, or no salamander all fall to the GitHub read below, which alone gives a pass or a fail.
      if ci_line="$(ci_going "$headsha" any)"; then
        checks="[]"; verdict=pending
        [ $((waited % 300)) -ne 0 ] || say "checks on ${headsha:0:7}: ${ci_line#* * }; waiting on the ci-runs file, no GitHub call"
      else
        checks="$(gh_cached "$headsha" pr checks "$pr" --repo "$REPO" --json name,bucket 2>/dev/null)" || checks="[]"   # shared for GH_TTL s, keyed by the head too (an updated head is a new answer)
        # a failed or cancelled check fails at once (whichever it is); only a pass needs the tests job (NEED, progress mode: a quick check alone must not read as a pass on a new head)
        verdict="$(echo "$checks" | NEED="$([ "$mode" = progress ] && echo "$TESTS_CHECK")" python3 -c '
import json,os,sys
cs=json.load(sys.stdin)
if not cs: print("none"); sys.exit()   # nothing reported yet
b={c["bucket"] for c in cs}
if "fail" in b or "cancel" in b: print("fail"); sys.exit()
if os.environ.get("NEED") and os.environ["NEED"] not in {c["name"] for c in cs}: print("none"); sys.exit()   # the tests job not yet among the checks of a new head
print("pending" if "pending" in b else "pass")')"
        # gh pr checks can still be reading the old head for a moment after an update: the tests job's run on this very commit must have passed (the check-runs of the commit)
        if [ "$verdict" = pass ] && [ "$mode" = progress ] && ! tests_on_head; then verdict=pending; fi
      fi
        case "$verdict" in
            pass) say "$okmsg"; return 0 ;;
            none) [ "$mode" = progress ] || say "no checks reported yet" ;;
            fail) fail "$step" "a check failed: $(echo "$checks" | python3 -c 'import json,sys; print(", ".join(c["name"]+"="+c["bucket"] for c in json.load(sys.stdin) if c["bucket"] in ("fail","cancel")))')" ;;
        esac
        # --status shows the log's tail: while the wait goes on the newest line says what is waited for, at most 5 min old
        [ "$mode" != progress ] || [ $((waited % 300)) -ne 0 ] || say "waiting for the PR's tests on ${headsha:0:7} ($([ "$verdict" = none ] && echo "not reported yet" || echo "$verdict")); $((waited/60)) min of up to $((WAIT_CHECKS/60))"
        [ $waited -lt $WAIT_CHECKS ] || fail "$step" "still pending after $((WAIT_CHECKS/60)) min"
        sleep "$POLL_PR"; waited=$((waited+POLL_PR))
    done
}
skip_retest() {   # 2a'': $1 = the PR head its checks passed on; $base = main's tip (up_to_date just read it). 0 with $skip_note when the retest cannot find anything new (no suite reads both what the PR
                  # changed and what main's new commits changed: tools/retest_skip.py), else 1 with $skip_why. Never fails the release: anything it cannot read is a retest
    skip_note=""; skip_why=""
    local out rc src=(--slug "$REPO" --cache "$LOGDIR/suitemap"); [ -z "$SUITEMAP_FILE" ] || src=(--map "$SUITEMAP_FILE")
    if [ "$SKIP_DISJOINT" != 1 ]; then skip_why="RELEASE_SKIP_DISJOINT is off"; say "retest needed for the PR head ${1:0:7} on main's tip ${base:0:7}: $skip_why"; return 1; fi
    out="$(python3 "$RETEST_SKIP" --repo "$HERE" --head "$1" --main "$base" "${src[@]}" </dev/null 2>/dev/null | tail -1)"; rc=$?   # the helper's exit: 0 skip, 1 retest, 2 or a crash: no answer
    case "$rc:$out" in
        0:"skip: "*) skip_note="${out#skip: }"; say "retest skipped for the PR head ${1:0:7} on main's tip ${base:0:7}: $skip_note"; return 0 ;;
        1:"retest: "*) skip_why="${out#retest: }" ;;
        *) skip_why="the check gave no answer (${RETEST_SKIP##*/}, exit $rc)" ;;
    esac
    say "retest needed for the PR head ${1:0:7} on main's tip ${base:0:7}: $skip_why"; return 1
}
bring_up_to_date() {   # The owner's rule: main's full run never blocks a release. The PR's checks passed on $headsha and the branch is behind main: under the update lock, merge main into
                       # the branch (gh pr update-branch: a merge, no force push), wait for the PR's own tests on the new head, and look again; main having moved meanwhile is another round,
                       # UPDATE_ROUNDS at most. Leaves the new head in $headsha and the rounds made in $rounds. Out of rounds, or something unreadable: returns with the reason in $fast_why, the old path.
                       # An update-branch that errors (a conflict) or tests that fail on the new head fail the release (update-branch, pr tests). Runs inside run(): headsha, pr, view are its
    take_update_lock
    local old new waited out
    rounds=0; upd_stop=""
    # the wait for the lock may have been long: the PR may be closed, or pushed to (its checks ran on the head read at the start, so a new head has to be tested too), and main may have moved
    read_view; [ "$state" = OPEN ] || fail "pr state" "the PR is $state"
    new="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"
    [[ "$new" =~ ^[0-9a-f]{7,64}$ ]] || fail "pr view" "no head commit in GitHub's answer after the update lock ($new)"
    if [ "$new" != "$headsha" ]; then
        say "the PR head moved while this release waited for the update lock (${headsha:0:7} -> ${new:0:7}): waiting for the PR's tests on ${new:0:7} (up to $((WAIT_CHECKS/60)) min)"
        headsha="$new"; wait_pr_checks "pr tests" progress "the PR's tests pass on the pushed head ${headsha:0:7}"
    fi
    while :; do
        up_to_date "$pr" "$headsha" && { say "update-branch: the PR head ${headsha:0:7} contains main's tip ${base:0:7}$([ $rounds -gt 0 ] || echo "; no update is needed")"; return 0; }
        if [ "$utd_kind" != behind ]; then upd_stop="the re-check could not be made ($fast_why)"; say "update-branch: stopped after $rounds round(s), $fast_why: the old path (main's run first)"; return 1; fi
        if [ $rounds -ge "$UPDATE_ROUNDS" ]; then upd_stop="main moved again during each of $UPDATE_ROUNDS rounds"; say "update-branch: main moved again during each of $UPDATE_ROUNDS rounds and the branch is behind it still (main's tip ${base:0:7}): the old path (main's run first)"; return 1; fi
        rounds=$((rounds+1)); old="$headsha"
        say "update-branch round $rounds of $UPDATE_ROUNDS: main's tip ${base:0:7} is not in the PR head ${old:0:7}; merging main into the branch (a merge, no force push)"
        if ! out="$(gh pr update-branch "$pr" --repo "$REPO" 2>&1)"; then   # a conflict with main only on the generated tool-text snapshot is mended (2a'); any other failure is the failure it always was
            regen_snapshot update-branch || fail "update-branch" "$(echo "$out" | tail -1); the branch could not be brought up to date, nothing was merged (a conflict with main is for the PR's author to resolve)"
        fi
        waited=0   # GitHub answers 202 and makes the merge commit after: read the PR until its head moves
        while :; do
            read_view; [ "$state" = OPEN ] || fail "pr state" "the PR is $state"
            new="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"
            [[ "$new" =~ ^[0-9a-f]{7,64}$ ]] || fail "update-branch" "no head commit in GitHub's answer after update-branch ($new)"
            [ "$new" = "$old" ] || break
            [ $waited -lt $MERGEABLE_WAIT ] || fail "update-branch" "update-branch was accepted but the PR head is still ${old:0:7} after $((MERGEABLE_WAIT/60)) min"
            sleep 10; waited=$((waited+10))
        done
        headsha="$new"
        say "update-branch round $rounds: the PR head is now ${headsha:0:7}; waiting for the PR's tests on ${headsha:0:7} (up to $((WAIT_CHECKS/60)) min)"
        wait_pr_checks "pr tests" progress "the PR's tests pass on the updated head ${headsha:0:7}"
    done
}
merge_commit() {   # after the merge: origin/main's tip must be the merge of the tip checked ($1) and the pinned head ($2), else main moved in between. Sets $mergesha
    mergesha=""
    fetch_retry || { fast_why="cannot fetch main after the merge"; return 1; }
    local m p1 p2; m="$(git rev-parse origin/main)"; p1="$(git rev-parse "$m^1" 2>/dev/null)"; p2="$(git rev-parse "$m^2" 2>/dev/null)"
    [ "$p1" = "$1" ] && [ "$p2" = "$2" ] || { fast_why="main's tip ${m:0:7} is not the merge of ${1:0:7} and ${2:0:7} (something else landed on main meanwhile)"; return 1; }
    mergesha="$m"
}
merge_oid() {   # $1 = the PR: the merge commit GitHub made, into $mergeoid (the old path looks for main's runs on commits that contain it). When GitHub does not say, main's tip as it is now, said in the log
    local i out; mergeoid=""
    for i in 1 2 3; do
        out="$(gh pr view "$1" --repo "$REPO" --json mergeCommit 2>/dev/null | python3 -c 'import json,sys; print((json.load(sys.stdin).get("mergeCommit") or {}).get("oid") or "")' 2>/dev/null)"
        if [[ "$out" =~ ^[0-9a-f]{7,64}$ ]]; then mergeoid="$out"; return 0; fi
        [ $i = 3 ] || sleep 5
    done
    local err="" try   # main's tip as it is now, but only when it is the merge or after it: a fetch that failed leaves origin/main at an older tip, and that tip's pass proves nothing about this merge
    for try in 1 2 3; do err="$(git fetch --quiet origin main 2>&1)" && { err=""; break; }; [ $try = 3 ] || sleep 2; done
    [ -z "$err" ] || fail "merge commit" "cannot find the merge commit of PR #$1: GitHub did not give it and main cannot be fetched ($(echo "$err" | tail -1 | sed -E 's#//[^/@]*@#//#'))"
    mergeoid="$(git rev-parse origin/main 2>/dev/null)"
    git merge-base --is-ancestor "$headsha" "$mergeoid" 2>/dev/null || fail "merge commit" "cannot find the merge commit of PR #$1: GitHub did not give it, and main's tip ${mergeoid:0:7} does not contain the PR head ${headsha:0:7}, so it is from before the merge"
    say "GitHub did not give the merge commit of PR #$1; looking for main's runs on its tip ${mergeoid:0:7} as it is now (it contains the PR head)"
}
short_merges() {   # lines "<full sha> <subject>" on stdin -> "<7 chars> <subject, 64 chars>; ..." (to read; never compared)
    sed -E 's/^([0-9a-f]{7})[0-9a-f]* /\1 /' | cut -c1-72 | sed 's/$/; /' | tr -d '\n' | sed 's/; $//'
}
merges_between() {   # $1..$2 on main's line: $merges_n of them, $merges_arr as "<full sha> <subject>" (a merge commit's subject names its PR; full, because %h lengthens as the repo grows
                     # and is never compared), $merges_list as "<sha7> <subject>; ..." to read. Not in a subshell: it sets globals
    local -a l; mapfile -t l < <(git log --first-parent --reverse --format='%H %s' "$1..$2" 2>/dev/null)
    merges_n="${#l[@]}"; merges_list=""; merges_arr=("${l[@]}")
    [ "$merges_n" -eq 0 ] || merges_list="$(printf '%s\n' "${l[@]}" | short_merges)"
}
rollback() {   # main's run failed on $verified, deployed at the merge: go back to the last-good commit under the lock, then report. Never returns: fail exits
    local m="$verified" now good rg rsha="${mg_rsha:-$verified}" why_not="" recyc covered="" removed="" units="" out rc byhand b bs="" rm_shas=()
    case "$recycle:$rc_note" in
        --recycle:*"recycle NOT marked"*) recyc="no recycle was flagged (it could not be asked for)" ;;
        --recycle:*) recyc="a recycle was already flagged for this PR's items before the failure; it delivered files that are now rolled back" ;;
        *) recyc="no recycle was flagged" ;;
    esac
    [ -z "${recovered:-}" ] || recyc="whether a recycle was flagged for this PR is not known (the release process that deployed it ended before main's run was read), nor whether a notice was sent"
    [ -z "${NOTICE_SENT:-}" ] || recyc="$recyc; a notice about this release had already gone out, and a rollback does not take it back"
    q_pause_now "main's tests"   # before the deploy lock is taken, and so before it is let go: a queued release waiting on the lock must find the pause when it gets it
    read_good   # only for the words of the by-hand command; the record is read again under the lock
    byhand="by hand, in $HERE: flock $LOCK_FILE env DEPLOY_ROLLBACK=1 DEPLOY_TO=${good:-<the last good commit, in $LAST_GOOD>} ./deploy.sh (deploy.sh refuses a rollback unless the lock is held); then delete the fast-ok ledger $LEDGER, so the rolled-back commits do not ride along on the next release"
    take_lock "main's tests failed on ${m:0:7} ($mg_why) and nothing was rolled back; $byhand"
    now="$(git rev-parse HEAD)"; read_good; rg=$?
    if [ $rg = 1 ]; then why_not="no last-good commit is recorded ($LAST_GOOD)"
    elif [ $rg = 2 ]; then why_not="the last-good record $LAST_GOOD is unreadable"
    elif ! git merge-base --is-ancestor "$m" "$now"; then why_not="the live checkout (${now:0:7}) no longer contains ${m:0:7}: it was rolled back or reset already"
        [ ! -f "$ROLLED_MARK" ] || { why_not="$why_not (rolled back with $(cat "$ROLLED_MARK"))"; rm -f "$ROLLED_MARK"; }
    elif git merge-base --is-ancestor "$m" "$good"; then why_not="a newer commit whose run on main passed, ${good:0:7}, contains ${m:0:7}: never rolled back past a newer good commit"
    elif ! git merge-base --is-ancestor "$good" "$now"; then why_not="the last-good commit ${good:0:7} is not in the live checkout's history (${now:0:7})"
    fi
    if [ -n "$good" ]; then   # what the failing run covers: every merge since the last good commit, one of them is not necessarily this PR's
        merges_between "$good" "$rsha"
        [ "$merges_n" -gt 1 ] && covered="; the failing run covers $merges_n merges since the last good commit ${good:0:7}, the cause may be any of them: $merges_list"
    fi
    if [ -n "$good" ]; then   # the reset goes to the last good commit: it takes out every release in last-good..live, the ones deployed at the merge before this one (their runs still waiting) as well as the ones on top
        local -a others=(); local e
        merges_between "$good" "$now"
        rm_shas=("${merges_arr[@]%% *}")   # every merge the reset takes out, the failing one among them: out of the fast-ok ledger below
        for e in "${merges_arr[@]}"; do [ "${e%% *}" = "$m" ] || others+=("$e"); done
        if [ "${#others[@]}" -gt 0 ]; then
            removed="; the rollback also takes out the other merges between ${good:0:7} and the live checkout (releases deployed before it whose runs were still waiting, and on top of it): $(printf '%s\n' "${others[@]}" | short_merges)"
            bs="$(printf '%s\n' "${others[@]}" | grep -oE 'Merge pull request #[0-9]+' | grep -oE '[0-9]+' | tr '\n' ' ')"
        fi
    fi
    if [ -n "$bs" ] && [ -n "${prs[*]-}" ]; then local nb="" rb; for rb in $bs; do case " ${prs[*]} " in *" $rb "*) ;; *) nb="$nb$rb " ;; esac; done; bs="$nb"; fi   # a group's own members are not riders ("rolled back with" themselves)
    # a commit a failed run took out never rides along on a later release. The failing merge always leaves the fast-ok ledger; when the reset goes ahead so does every merge it takes out
    # (those deployed before it whose runs were still waiting, and those on top). Done before the reset: a failure here empties the ledger, which is the safe side
    if [ -n "$why_not" ]; then ledger_drop "$m"; else ledger_drop "$m" "${rm_shas[@]}"; fi
    if [ -n "$why_not" ]; then
        exec 9>&-; pending_clear; [ -z "${RB_DONE:-}" ] || : > "$RB_DONE"   # a verdict was reached (not rolled back, and the report says why)
        fail "main's tests" "$mg_why: NOT rolled back, $why_not; deployed at ${m:0:7}$covered · $recyc"
    fi
    # unit and timer files the rolled-back commits added stay installed (a rollback does not disable anything): named in the report
    units="$(git diff --diff-filter=A --name-only "$good" "$now" -- units/ 2>/dev/null | grep -E '\.(service|timer|path|socket)\.in$' | sed -E 's#.*/##; s/\.in$//' | paste -sd, - | sed 's/,/, /g')"
    out="$(DEPLOY_LOCK_FILE="$LOCK_FILE" DEPLOY_ROLLBACK=1 DEPLOY_TO="$good" ./deploy.sh 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
    exec 9>&-     # the lock is released here, before the failure report starts a child
    pending_clear   # the verdict is acted on
    [ $rc -eq 0 ] || fail "rollback" "main's tests failed on ${m:0:7} ($mg_why) and the rollback to ${good:0:7} failed: $(echo "$out" | tail -1) (the checkout is at $(git rev-parse --short HEAD)); $byhand"
    say "rolled back to ${good:0:7} ($(git rev-parse --short HEAD))"
    [ -z "${RB_DONE:-}" ] || : > "$RB_DONE"
    for b in $bs; do q_riders="${q_riders:+$q_riders }#$b"; done   # named in the queue's note and log (queue_after_fail, below); they are not queued again: they are merged and stay on main
    for b in $bs; do   # each release the rollback took out hears of it on its own PR, and its own run (still waiting) says so when it ends
        echo "#$pr (main's tests failed on ${m:0:7})" > "$LOGDIR/pr-$b.rolledback"
        echo "$(date -u +%FT%TZ) rolled back with #$pr's failure; it is merged but not live" >> "$LOGDIR/pr-$b.log"
        tell "[release] PR #$b was rolled back with #$pr's failure (main's tests failed on ${m:0:7}, main is live at ${good:0:7}); it is merged but not live; it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green · log $LOGDIR/pr-$b.log"
    done
    [ -z "$units" ] || units="; left installed: $units (the rolled-back commits added them), disable by hand if needed"
    fail "main's tests" "${live_ride:+LIVE via ride-along, }rolled back to ${good:0:7} · $mg_why$covered$removed$units; a rollback does not undo data or state changes the rolled-back commits made; main still holds the failing merge, fix forward or revert it · $recyc"
}

# The head branch of a merged PR, deleted the way `gh pr merge --delete-branch` did, but only after the open PRs based on it are retargeted to main: GitHub closes a PR whose base
# branch is deleted, and a closed PR cannot be retargeted (a PR based on another PR's branch is closed when that branch's PR merges). A PR that cannot be
# listed or retargeted keeps the branch (the log says why and what to do); nothing here fails the release. $1 the head branch, $2 isCrossRepository (a fork's branch is never touched).
retarget_and_delete_branch() {
    local head="$1" cross="$2" out nums n kept=""
    [ -n "$head" ] && [ "$cross" = False ] && [ "$head" != main ] || return 0
    if ! out="$(gh pr list --repo "$REPO" --base "$head" --state open --limit 100 --json number 2>&1)" \
       || ! nums="$(echo "$out" | python3 -c 'import json,sys; print(" ".join(str(p["number"]) for p in json.load(sys.stdin)))' 2>/dev/null)"; then
        say "the head branch $head is kept: the open PRs based on it could not be listed ($(echo "$out" | tail -1 | head -c 200)); delete it by hand once no PR is based on it"; return 0
    fi
    for n in $nums; do
        if out="$(gh pr edit "$n" --repo "$REPO" --base main 2>&1)"; then say "PR #$n was based on $head: retargeted to main"
        else say "PR #$n was based on $head: retargeting it to main failed ($(echo "$out" | tail -1 | head -c 200))"; kept="$kept #$n"; fi
    done
    if [ -n "$kept" ]; then say "the head branch $head is kept: deleting it would close the PRs$kept still based on it; retarget them, then delete the branch by hand"; return 0; fi
    if gh api "repos/$REPO/git/ref/heads/$head" >/dev/null 2>&1; then   # best-effort: the branch may be gone already (the repo's own setting), never fails the release
        if gh api -X DELETE "repos/$REPO/git/refs/heads/$head" >/dev/null 2>&1; then say "deleted the head branch $head"
        else say "the head branch $head is still there: its deletion failed, delete it by hand"; fi
    fi
}

# THE RELEASE QUEUE. Releases ran one after another with long idle gaps: each waits for main's full run after its deploy, and the next one was
# started only when the previous unit ended, although nothing stops a release from starting while another waits on main's run. `release.sh queue N [N...]` records PR numbers
# in order in $QUEUE; the release that holds the queue (the driver, $QUEUE.driver) starts the next queued PR's release itself (the plain `release.sh <pr>`, its own unit) when it
# reaches "deployed", the point after which it only waits on main's run; a PR stays in $QUEUE until then (a killed driver is still listed, and --resume starts it again). A release
# that fails BEFORE its merge (checks failed, a conflict, a closed PR, a lock not had) is reported as ever and skipped: it leaves the queue and starts the next one at its failure,
# so the queue goes on. A release the queue started that fails AFTER its merge (main's run failed: merged and not deployed on the old path, or rolled back after a deploy at the merge;
# a deploy that failed; the deploy lock not had for the deploy) PAUSES the queue ($QUEUE.paused): no new release starts, a release the queue had started already but not merged
# stops before its merge ("queue paused": checked after the wait for the checks and around the deploy lock) and stays first in the queue, the riders a rollback took out stay merged on main (named in the report and the log, not queued again),
# the existing rollback and report run as they always did, and `release.sh queue --resume` goes on once main is fixed. A plain `release.sh N` writes no pause. A run of main that could
# not be read in time is no failure: no pause (the release leaves the queue, which goes on).
# The driver: the release the queue last started. A release that finds no live driver (none, or its unit no longer active) is one too, so a killed driver does not stall the queue;
# a release started by hand while a driver lives does not start queued ones (one chain, in order). `release.sh queue` starts the first queued PR at once when no driver lives.
# Every change to the queue is under flock on $QUEUE.lock (fd 4, a subshell's own: 30 s at most) and logged to $QUEUE.log.
q_log() { echo "$(date -u +%FT%TZ) $*" >> "$QUEUE.log"; }
q_locked() {   # "$@" under the queue's flock, in a subshell (it sets nothing outside); 3 when the lock was not had
    mkdir -p "$LOGDIR"
    ( flock -w 30 4 || { say "the queue lock $QUEUE.lock was not free for 30 s"; exit 3; }; "$@" ) 4>>"$QUEUE.lock"
}
q_read() { q=(); [ -f "$QUEUE" ] && mapfile -t q < <(grep -E '^[0-9]+$' "$QUEUE"); return 0; }   # into the array q, in order
q_write() {   # the array q, replaced whole; no file when it is empty
    if [ "${#q[@]}" -eq 0 ]; then rm -f "$QUEUE"; return 0; fi
    printf '%s\n' "${q[@]}" > "$QUEUE.$$" && mv -f "$QUEUE.$$" "$QUEUE" || { rm -f "$QUEUE.$$"; say "could not write the release queue $QUEUE"; return 1; }
}
q_driver() { cat "$QUEUE.driver" 2>/dev/null | grep -E '^[0-9]+$' | head -1; }
q_started_pr() {   # 0 when the queue started PR $1: the driver file names it, or the queue's log says it started it (the driver moves on to the next PR at "deployed"; a recovered rollback of the earlier one still belongs to the queue)
    [ -n "${1:-}" ] || return 1
    [ "$(q_driver)" != "$1" ] || return 0
    grep -qF "started PR #$1 (" "$QUEUE.log" 2>/dev/null
}
q_alive() { [ -n "${1:-}" ] && systemctl --user is-active --quiet "stackshot-release-$1.service" 2>/dev/null 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-; }   # the release unit of PR $1 is running
q_start_next() {   # under the lock: the first queued PR's release is started and becomes the driver; it stays in the queue file until it is deployed (a killed one is still listed, and --resume starts it again).
                   # One that cannot be started is logged and taken out. $1 = who asks (for the log)
    local n out gm; local -a gq
    if [ -f "$QUEUE.paused" ]; then rm -f "$QUEUE.driver"; say "the release queue is paused ($(head -1 "$QUEUE.paused")): no release started; release.sh queue --resume goes on"; return 0; fi
    while :; do
        q_read
        if [ "${#q[@]}" -eq 0 ]; then rm -f "$QUEUE.driver"; say "the release queue is empty: nothing more to start"; return 0; fi
        n="${q[0]}"
        echo "$n" > "$QUEUE.driver"   # before the start: the release reads it at its start to know that the queue started it
        gm=0; if [ "${#q[@]}" -ge 2 ] && [ "$(mq_host_mode)" = on ]; then gm="$MQ_HANDOFF_MAX"; fi   # fewer than two waiting (gm 0): the old path below, one PR at a time
        if [ "$gm" -ge 2 ]; then   # THE MERGE QUEUE, ON: routed by COUNT at this moment. Two or more waiting go to the merge queue as ONE group, the first PR leads (its unit, stackshot-release-<lead>, is the driver)
            gq=("${q[@]:0:$gm}")   # at most MQ_HANDOFF_MAX PRs are handed over at once; the rest stay in the queue for the next hand-off
            if out="$("$HERE/release.sh" --group "${gq[@]}" 2>&1 </dev/null 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-)" || [[ "$out" == *"is already running"* ]]; then
                q_log "started PRs ${gq[*]} as one group through the merge queue ($1); ${#q[@]} in the queue"
                say "release queue: ${#q[@]} PRs are waiting (${q[*]}) and the merge queue is on: started the group release of ${gq[*]}, led by PR #$n$([ "${#q[@]}" -le "${#gq[@]}" ] || echo "; the others (${q[*]:${#gq[@]}}) wait for the next hand-off")"; return 0
            fi
            rm -f "$QUEUE.driver"; q=("${q[@]:1}"); q_write || return 1   # as a lone one that cannot be started: the first is skipped and the count is taken again
            q_log "could not start the group led by PR #$n ($1): $(echo "$out" | tail -1)"; say "release queue: could not start the group release led by PR #$n ($(echo "$out" | tail -1)); PR #$n skipped"; continue
        fi
        if out="$("$HERE/release.sh" "$n" 2>&1 </dev/null 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-)" || [[ "$out" == *"is already running"* ]]; then   # its own unit (systemd-run): it outlives this release
            q_log "started PR #$n ($1); ${#q[@]} in the queue"
            say "release queue: started the release of PR #$n ($((${#q[@]} - 1)) more queued$([ "${#q[@]}" -le 1 ] || echo ": ${q[*]:1}"))"; return 0
        fi
        rm -f "$QUEUE.driver"; q=("${q[@]:1}"); q_write || return 1
        q_log "could not start PR #$n ($1): $(echo "$out" | tail -1)"; say "release queue: could not start the release of PR #$n ($(echo "$out" | tail -1)); skipped"
    done
}
q_mine() {   # 0 when this release ($pr) is the queue's driver, or no driver lives: it is then the one that starts the next
    local d; d="$(q_driver)"
    [ "$d" = "$pr" ] || ! q_alive "$d"
}
q_unqueue() {   # under the lock: PR $1 out of the queue file
    local e kept=(); q_read
    for e in "${q[@]}"; do [ "$e" = "$1" ] || kept+=("$e"); done
    q=("${kept[@]}"); q_write
}
q_handoff() {   # $1 = why (deployed | skipped at <step>): this release leaves the queue file and the next queued PR's release starts, when this release drives the queue and there is one
    q_mine || return 0
    [ -f "$QUEUE" ] || [ -f "$QUEUE.driver" ] || return 0   # no queue in use
    q_locked q_handoff_locked "$1"
}
q_handoff_locked() { q_mine || return 0; q_unqueue "$pr" || return 1; q_start_next "PR #$pr $1"; }   # read again under the lock: another start may have taken over meanwhile
q_pause_file() {   # under the lock: the pause file, naming the PR and the step
    printf '%s\n' "PR #$pr failed at $1 after its merge, $(date -u +%FT%TZ)" > "$QUEUE.paused"
}
q_pause_now() {   # $1 = the step. Called by rollback() before the deploy lock is taken, so the pause is on disk before the lock is let go and a queued release that waits for the lock finds it
                  # when it gets the lock (fail() writes it only after the lock was let go, and that release would merge onto a main that is red). Only a queue-started release after its merge; q_pause rewrites it later
    [ "${qstart:-0}" = 1 ] && [ "${q_fail:-}" = pause ] || return 0
    q_locked q_pause_file "$1"; q_log "paused: PR #$pr failed at $1 after its merge (written before the deploy lock was let go)"
}
q_pause() {   # $1 = the step, $2 = the PRs the rollback took out with this one (oldest first). A release failed after its merge: it leaves the queue file and no new release starts until release.sh queue --resume.
              # The riders a rollback took out are merged and stay on main: they are not queued again (release.sh N on a merged PR fails at "pr state"); the next release's merge deploys them once main is green. Logged here
    local e r kept=()
    q_pause_file "$1"; q_log "paused: PR #$pr failed at $1 after its merge"
    q_read
    for e in "${q[@]}"; do [ "$e" = "$pr" ] || kept+=("$e"); done
    for r in ${2:-}; do q_log "PR $r was rolled back with PR #$pr: merged and not live, not queued again; it goes live with the next release once main is fixed"; done
    q=("${kept[@]}"); q_write
    [ "$(q_driver)" != "$pr" ] || rm -f "$QUEUE.driver"
}
q_held() {   # under the lock: a release the queue started was stopped by the pause before its merge; it stays first in the queue, and no longer drives it
    local e dup=0; q_read
    for e in "${q[@]}"; do [ "$e" != "$pr" ] || dup=1; done
    [ $dup = 1 ] || { q=("$pr" "${q[@]}"); q_write; }
    [ "$(q_driver)" != "$pr" ] || rm -f "$QUEUE.driver"
    q_log "PR #$pr stopped by the pause before its merge: first in the queue"
}
queue_after_fail() {   # fail(): what the failure does to the queue, by $q_fail (skip: before the merge; held: stopped by the pause before the merge; pause: after it; none). Sets $q_note for the report
    local used=0; q_note=""
    { [ -f "$QUEUE" ] || [ -f "$QUEUE.driver" ]; } && used=1
    case "${q_fail:-none}" in
        skip) [ $used = 1 ] && q_mine || return 0
              say "release queue: PR #$pr failed at $1 before its merge: skipped, the queue goes on"; q_log "skipped PR #$pr: failed at $1 before its merge"
              q_handoff "skipped at $1"; q_note="; skipped in the release queue, which goes on" ;;
        held) [ $qstart = 1 ] || return 0   # no hand-off: the queue is paused, so nothing else starts, and this one is not dropped
              q_locked q_held; say "release queue: PR #$pr stopped before its merge, the queue is paused: it stays first in the queue; release.sh queue --resume once main is fixed"
              q_note="; stopped before its merge, still first in the release queue: release.sh queue --resume once main is fixed" ;;
        pause) [ $qstart = 1 ] || return 0   # only a release the queue started pauses it; a plain release.sh N that fails leaves no pause
               q_locked q_pause "$1" "${q_riders:-}"
               say "release queue: paused (PR #$pr failed at $1 after its merge): no new release starts; release.sh queue --resume once main is fixed"
               q_read; q_note="; the release queue is paused$([ "${#q[@]}" -eq 0 ] || echo " with ${#q[@]} queued (${q[*]})"): release.sh queue --resume once main is fixed"
               [ -z "${q_riders:-}" ] || q_note="$q_note; rolled back with it, merged and not live: $q_riders; they go live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" ;;
        none) [ $qstart = 1 ] || return 0   # a main run that was not read is no failure of the code: not paused. The PR is merged, so it leaves the queue, and if it still held the queue the next one starts
              q_locked q_unqueue "$pr"
              if [ "$(q_driver)" = "$pr" ]; then q_handoff "ended with main's run not read"; q_note="; the release queue goes on (main's run not being read is not a failure of the code)"; fi ;;
    esac
}
q_paused_stop() {   # in run(), before anything is merged: a pause stops a release the queue had started already (it was started before the pause). It fails as a pre-merge skip, reason "queue paused", no hand-off
    [ "$qstart" = 1 ] && [ -f "$QUEUE.paused" ] || return 0
    q_fail=held
    fail "queue paused" "the release queue is paused ($(head -1 "$QUEUE.paused")): this release was started by the queue before the pause and nothing was merged; it is first in the queue again, release.sh queue --resume starts it once main is fixed"
}
queue_cmd() {   # release.sh queue N [N...] | --list | --drop N | --resume
    local n d
    case "${1:-}" in
        --list)
            q_read; d="$(q_driver)"
            if [ "${#q[@]}" -eq 0 ]; then echo "release queue: empty"; else echo "release queue, in order: ${q[*]}"; fi
            [ ! -f "$QUEUE.paused" ] || echo "paused: $(head -1 "$QUEUE.paused") (release.sh queue --resume)"
            if [ -n "$d" ] && q_alive "$d"; then echo "driver: PR #$d (its release starts the next queued one when it is deployed)"
            elif [ -n "$d" ] && [ ! -f "$QUEUE.paused" ] && [[ " ${q[*]} " == *" $d "* ]]; then echo "PR #$d was started by the queue but its release is not running (killed?): release.sh queue --resume starts it again"
            elif [ "${#q[@]}" -gt 0 ] && [ ! -f "$QUEUE.paused" ]; then echo "no queued release is running: release.sh queue --resume starts the next"; fi
            return 0 ;;
        --drop)
            [[ "${2:-}" =~ ^[0-9]+$ ]] && [ $# -eq 2 ] || { echo "usage: release.sh queue --drop N" >&2; return 2; }
            q_locked queue_drop_locked "$2"; return $? ;;
        --resume)
            [ $# -eq 1 ] || { echo "usage: release.sh queue --resume" >&2; return 2; }
            q_locked queue_resume_locked; return $? ;;
        ''|-*) echo "usage: release.sh queue N [N...] | queue --list | queue --drop N | queue --resume" >&2; return 2 ;;
    esac
    for n in "$@"; do [[ "$n" =~ ^[0-9]+$ ]] || { echo "release.sh queue: '$n' is not a PR number; usage: release.sh queue N [N...]" >&2; return 2; }; done
    queue_checks_gate "$@" || return 1   # no PR is added when one of them is refused
    q_locked queue_add_locked "$@"
}
queue_checks_gate() {   # $@ = the PR numbers `release.sh queue` was given. 0 when none of them (not queued yet) has a check row that failed, was cancelled or timed out; else 1 with "refused: PR N has failing check rows:" and one line a row
                        # (name, state, link) on stderr, nothing queued. Rows that are pending, skipped or passing do not refuse, matrix shard rows count like any row. A PR whose rows cannot be read (gh fails, or says something that is
                        # not a list of rows) is refused too, with gh's error: never queued blindly. No bypass. The read is one `gh pr checks` per PR, made now (a cached answer could be a minute older than a failure that just came)
    local n e seen=" " dup refused=0 out rc
    q_read
    for n in "$@"; do
        dup=0; for e in "${q[@]}"; do [ "$e" != "$n" ] || dup=1; done
        [[ "$seen" != *" $n "* ]] || dup=1; seen="$seen$n "
        [ $dup = 0 ] || continue   # queued already (it keeps its place, nothing is added) or named twice
        out="$(REPO="$REPO" python3 -c '
import json, os, subprocess, sys
pr, repo = sys.argv[1], os.environ["REPO"]
def unreadable(why): print("refused: PR %s: its check rows could not be read, so it is not queued: %s" % (pr, why)); sys.exit(2)
try: r = subprocess.run(["gh", "pr", "checks", pr, "--repo", repo, "--json", "name,state,bucket,link"], capture_output=True, text=True, timeout=60)
except (OSError, subprocess.SubprocessError) as e: unreadable("%s: %s" % (type(e).__name__, e))
try: rows = json.loads(r.stdout)   # gh exits 8 while a check is pending: the rows it printed still count
except ValueError: rows = None
if not isinstance(rows, list) or not all(isinstance(c, dict) for c in rows):
    err = " ".join((r.stderr or r.stdout or "").split())
    if r.returncode != 0 and "no checks reported" in err.lower(): rows = []   # a PR no check has reported on yet has no failing row
    else: unreadable(err[:300] or "gh exited %d with no rows" % r.returncode)
BAD_STATE = {"FAILURE", "ERROR", "CANCELLED", "CANCELED", "TIMED_OUT", "STARTUP_FAILURE"}
bad = [c for c in rows if c.get("bucket") in ("fail", "cancel") or str(c.get("state") or "").upper() in BAD_STATE]
if bad:
    print("refused: PR %s has failing check rows:" % pr)
    for c in bad: print("  %s  %s  %s" % (c.get("name") or "(no name)", c.get("state") or c.get("bucket") or "?", c.get("link") or "(no link)"))
    sys.exit(1)' "$n" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
        if [ $rc -ne 0 ]; then refused=1; printf '%s\n' "$out" >&2; q_log "refused PR #$n: ${out%%$'\n'*}"; fi
    done
    [ $refused = 0 ] || { echo "nothing was queued: queue again once the PR's checks pass" >&2; return 1; }
    return 0
}
queue_add_locked() {
    local n e dup
    q_read
    for n in "$@"; do
        dup=0; for e in "${q[@]}"; do [ "$e" != "$n" ] || dup=1; done
        if [ $dup = 1 ]; then echo "PR #$n is queued already"; continue; fi
        q+=("$n"); q_log "queued PR #$n"; echo "queued PR #$n"
    done
    q_write || return 1
    if [ -f "$QUEUE.paused" ]; then echo "the release queue is paused ($(head -1 "$QUEUE.paused")): nothing starts until release.sh queue --resume"
    elif q_alive "$(q_driver)"; then echo "PR #$(q_driver) is the queue's running release: it starts the next one when it is deployed"
    else q_start_next "release.sh queue"; fi
    q_read; echo "release queue, in order: ${q[*]:-(empty)}"
}
queue_drop_locked() {
    local e kept=() hit=0
    q_read
    for e in "${q[@]}"; do if [ "$e" = "$1" ]; then hit=1; else kept+=("$e"); fi; done
    [ $hit = 1 ] || { echo "PR #$1 is not in the release queue"; return 1; }
    if [ -e "$MQ_HANDED/pr-$1" ]; then   # THE MERGE QUEUE, ON: a group release handed it to salamander's queue; taking it out of this file would not take it out of that one
        local ql st act; ql="$(sed -n 's/.*led by PR #\([0-9][0-9]*\).*/\1/p' "$MQ_HANDED/pr-$1" 2>/dev/null | head -n 1)"
        if q_alive "$ql"; then act=live   # its group release is running: the marker is its own
        elif [ "$(mq_host_mode)" = off ] || [ "$(mq_host_mode)" = shadow ]; then act=gone   # the host file says off or shadow (any more): the old path does not read markers then. A file that does not read (bad: ...) says nothing: mq status decides, and a status that cannot be read refuses
        else
            st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
            act="$(printf '%s' "$st" | K="$1" python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin); k = int(os.environ["K"])
    print("active" if any(e.get("pr") == k and e.get("state") in ("waiting", "grouped") for e in d.get("queue", [])) else "gone")
except Exception: print("")' 2>/dev/null)"
        fi
        if [ "$act" = gone ]; then rm -f "$MQ_HANDED/pr-$1"; q_log "removed the stale merge queue marker of PR #$1 ($MQ_HANDED/pr-$1): the merge queue no longer holds it"; echo "(the merge queue no longer holds PR #$1; its stale marker $MQ_HANDED/pr-$1 was removed)"
        else
            echo "PR #$1 was handed to the merge queue ($(cut -c1-120 "$MQ_HANDED/pr-$1")): it is not dropped here, the queue may still merge it. salamander mq drop $1 --repo $REPO takes it out of the queue (the group release then reports it); nothing was changed in the release queue. The marker is $MQ_HANDED/pr-$1$([ "$act" = live ] || echo "; it goes by itself once the merge queue no longer holds the PR and this command is run again")"; return 1
        fi
    fi
    q=("${kept[@]}"); q_write || return 1; q_log "dropped PR #$1"
    echo "dropped PR #$1; release queue, in order: ${q[*]:-(empty)}"
}
queue_resume_locked() {
    if [ -f "$QUEUE.paused" ]; then q_log "resumed (was: $(head -1 "$QUEUE.paused"))"; echo "resumed (it was paused: $(head -1 "$QUEUE.paused"))"; rm -f "$QUEUE.paused"; fi
    if q_alive "$(q_driver)"; then echo "PR #$(q_driver) is the queue's running release: it starts the next one when it is deployed"; return 0; fi
    q_start_next "release.sh queue --resume"
}

# THE MERGE QUEUE, ON (docs/mq.md in salamander, step 5): the release queue above routes by COUNT at the moment it would start a release. One PR waiting takes the old path (run(), unchanged, no call to the queue, with both of its
# shortcuts: a PR already tested on main's tip merges without a new run, and tools/retest_skip.py). Two or more waiting (at most 4, release.sh's own number) go to the merge queue together: `release.sh --group N N...` (unit stackshot-release-<first>, which
# is the queue's driver) runs run_group. It hands them all to the queue in one `salamander mq add`, waits for each (`salamander mq wait N`: exit 0 merged, 1 ejected/failed/dropped with the reason, 2 gave up, not in the
# line or blocked, 3 tested in shadow, 4 replay), then deploys what the queue merged ONCE, with the old path's own steps after its merge: the deploy lock, the fast gate (the queue's merge commits go into the fast-ok ledger first,
# the tested tree being exactly what was merged), ./deploy.sh pinned to the merge, the session pick, one report and one `done:` line per PR, then main's run for the merge with the rollback and the pause. Later work puts the
# two shortcuts inside the queue and removes the count rule.
# HOW THE TWO PATHS EXCLUDE EACH OTHER. (1) The host file's deploy_lock is THIS script's deploy lock (mq_on_check refuses mode on otherwise): the queue's merge push takes it without waiting (busy: tried again next tick), and the old
# path holds it from its own merge to the end of its deploy (on its own wait for main's run it lets it go after the merge, which has happened by then), so the queue never merges while a lone PR
# is mid-merge or deploying, and a group deploy (also under the lock) never overlaps a push. (2) The release queue starts one thing at a time: a group, or a lone release (and, as ever, a lone release hands over at "deployed").
# (3) A PR is never in both: a group release writes a marker per PR (MQ_HANDED/pr-N) before `mq add` and removes it once the queue no longer holds the PR (settled, dropped by `mq drop`, or "not in the line"), and run() in mode on
# refuses a PR with a marker ("mq line"), at its start and again under the deploy lock just before its merge (a hand-run lone release can wait for its checks while a group takes the PR); the group release in turn refuses a PR
# whose own release unit (stackshot-release-N) is running, and `queue --drop` of a PR the queue holds says so. A hand-off is at most MQ_HANDOFF_MAX PRs (4, release.sh's own number: the chain tests those entries at once and merges them one PR at a time, so a larger
# hand-off would leave the first merges undeployed while the later ones wait); the rest stay in release.sh's queue for the next hand-off. Design choices: the deploy waits for EVERY PR of the group to settle (a PR behind a failure is rebuilt and tested again; the chain merges one
# PR a push in line order, and the last merge contains the earlier ones, so one deploy of it covers all); a failed or ejected PR is reported as a failed release of that PR with the queue's reason and the rest still go out; a PR that is
# merged on GitHub already (an earlier run of the group was killed after the queue merged it) is read before `mq add`, deployed with the group and not handed over again. An mq error, a timeout (RELEASE_MQ_WAIT_CAP, 5 h), a queue
# paused or blocked, a `salamander mq:` message, a pause of release.sh's own queue while the group waits: the PRs still open are dropped from the queue (best effort) and reported FAILED, release.sh's queue is PAUSED, and what the
# queue merged BEFORE is deployed all the same (never reported FAILED, but "merged, not live" where it cannot be deployed: only the unresolved PRs are FAILED, and they stay first in release.sh's queue); before any merge the PRs stay first in the queue so --resume tries them again.
# Where a merged PR cannot be deployed (main cannot be fetched, its commit is unknown, the deploy fails) it is reported "merged, not live". A forced --recycle/--no-recycle does not exist for a group: its session pick is made
# from the files of all its PRs.
qg_pause_locked() {   # under the lock: the pause file, the merged PRs out of the queue file (the others stay, first), the driver gone. $1 = the step, $2 = held|pause
    local e m kept=() gone; q_read
    [ -f "$QUEUE.paused" ] || printf '%s\n' "group of PRs ${prs[*]} (led by #$lead): $1 $([ "$2" = pause ] && echo "after the merge queue's merge" || echo "before anything was merged"), $(date -u +%FT%TZ)" > "$QUEUE.paused"   # a pause that is there already keeps its own reason
    for e in "${q[@]}"; do gone=0; for m in "${merged_prs[@]}" ${lost_prs[@]+"${lost_prs[@]}"}; do [ "$e" != "$m" ] || gone=1; done; [ $gone = 1 ] || kept+=("$e"); done
    q=("${kept[@]}"); q_write
    [ "$(q_driver)" != "$lead" ] || rm -f "$QUEUE.driver"
    q_log "paused: the group of PRs ${prs[*]} failed at $1 ($2); merged and out of the queue: ${merged_prs[*]:-none}"
}
qg_held_locked() {   # under the lock: the queue is paused already; the group's driver goes, its PRs stay first in the queue
    [ "$(q_driver)" != "$lead" ] || rm -f "$QUEUE.driver"
    q_log "the group of PRs ${prs[*]} stopped by the pause before any merge: still first in the queue"
}
qg_after_fail() {   # fail() of a group release: what the failure does to the release queue, by $q_fail (held: before any merge, pause it and keep the PRs; hold: it is paused already; pause: after a merge; none: no failure of the code). Sets $q_note
    q_note=""
    [ "$qstart" = 1 ] || return 0   # only a group the release queue started touches it (the driver file names the lead); one run by hand pauses nothing
    case "${q_fail:-none}" in
        held) q_locked qg_pause_locked "$1" held; say "release queue: paused (the group of PRs ${prs[*]} failed at $1 before anything was merged): they stay first in the queue; release.sh queue --resume once it is fixed"
              q_note="; the release queue is paused with them still queued: release.sh queue --resume once it is fixed" ;;
        hold) q_locked qg_held_locked; say "release queue: the group stopped before any merge, the queue is paused: the PRs stay first in the queue"
              q_note="; stopped before any merge, still first in the release queue: release.sh queue --resume once main is fixed" ;;
        pause) q_locked qg_pause_locked "$1" pause; say "release queue: paused (the group of PRs ${prs[*]} failed at $1 after the merge): no new release starts; release.sh queue --resume once main is fixed"
               q_read; q_note="; the release queue is paused$([ "${#q[@]}" -eq 0 ] || echo " with ${#q[@]} queued (${q[*]})"): release.sh queue --resume once main is fixed"
               [ -z "${q_riders:-}" ] || q_note="$q_note; rolled back with it, merged and not live: $q_riders; they go live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" ;;
        none) q_locked qg_unqueue_merged; qg_handoff "ended with main's run not read"; q_note="; the release queue goes on (main's run not being read is not a failure of the code)" ;;
    esac
}
qg_unqueue_merged() { local m; for m in "${merged_prs[@]}"; do q_unqueue "$m" || return 1; done; }   # under the lock
qg_handoff_locked() { q_mine || return 0; local m h; for m in "${prs[@]}"; do for h in ${held_prs[@]+"${held_prs[@]}"}; do [ "$h" != "$m" ] || continue 2; done; q_unqueue "$m" || return 1; done; q_start_next "the group of PRs ${prs[*]} $1"; }
qg_handoff() {   # $1 = why: the group's PRs leave the queue file and the next waiting ones start, when this group release drives the queue (q_mine: $pr is the lead)
    q_mine || return 0
    [ -f "$QUEUE" ] || [ -f "$QUEUE.driver" ] || return 0
    q_locked qg_handoff_locked "$1"
}
run_group() {   # $@ = the PRs of one group, in queue order (two or more, at most MQ_HANDOFF_MAX). See THE MERGE QUEUE, ON above
    local -a prs=("$@") live_prs=("$@") merged_prs=() shas=() held_prs=() addprs=() lost_prs=()
    local ar unk_why=""; local -a unk=()
    local lead="$1" pr="$1" glog="$LOGDIR/group-$1.log" m recycle="" rc_note="" audit_note="" verified="" mg_notlive="" q_fail=held q_note="" q_riders="" qstart=0 out rc title
    local gfailed=0 ROLLED_MARK="$LOGDIR/pr-$1.rolledback" names="" sha restarted fast=0 fast_why="" good="" mergesha="" mergeoid="" abort_step="" abort_why="" pre_note="" premerged="" k unn=""; local -a keep=()
    for m in "${prs[@]}"; do names="${names:+$names }#$m"; done
    exec > >(tee -a "$glog") 2>&1
    gsay() { local l k; l="$(say "$@")"; echo "$l"; for k in "${prs[@]}"; do printf '%s\n' "$l" | mq_plain >> "$LOGDIR/pr-$k.log"; done; }   # progress, into the group log and (the words a waiter looks for made harmless) every PR's own log
    mn() { local k r=""; for k in "${merged_prs[@]}"; do r="${r:+$r }#$k"; done; printf '%s' "$r"; }   # the merged PRs as "#a #b"
    plog() { printf '%s\n' "$(say "$2")" >> "$LOGDIR/pr-$1.log"; }                                                                               # a result line, into one PR's log only
    fail() {   # a failure of the whole group: every PR still open (live_prs: the merged ones too once their deploy is what failed) gets its FAILED line, the release queue is dealt with by $q_fail, one red report
        local k; MQ_FAIL="$1: $2"; say "FAILED at $1: $2"
        for k in "${live_prs[@]}"; do plog "$k" "FAILED at $1: $(printf '%s' "$2" | mq_plain)"; done
        qg_after_fail "$1"
        tell "[release] PRs $names FAILED at $1: $2$q_note · log $glog"
        exit 1
    }
    mq_settle() {   # $1 = a PR: let go of it in the queue (best effort). Its marker goes once the queue no longer holds it: dropped, or "is not in the line" (never added: the add was refused, or it settled already), or no active entry in `mq status`
        local k="$1" o rc st act
        o="$(timeout 20 salamander mq drop "$k" --repo "$REPO" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
        if [ $rc -eq 0 ] || [[ "$o" == *"is not in the line"* ]]; then mqh_clear "$k"; return 0; fi
        st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 5>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
        act="$(printf '%s' "$st" | K="$k" python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin); k = int(os.environ["K"])
    print("active" if any(e.get("pr") == k and e.get("state") in ("waiting", "grouped") for e in d.get("queue", [])) else "gone")
except Exception: print("")' 2>/dev/null)"
        if [ "$act" = gone ]; then mqh_clear "$k"; return 0; fi
        say "PR #$k could not be dropped from the merge queue (salamander mq drop $k: $(printf '%s' "$o" | tail -n 1 | cut -c1-160)): its marker $MQ_HANDED/pr-$k stays, the old path will not take it. salamander mq drop $k by hand, then delete the marker"; return 1
    }
    mq_fail() {   # fail() after the queue is told to let go of every PR that is not merged
        local k
        for k in "${live_prs[@]}"; do
            case " ${merged_prs[*]} " in *" $k "*) continue ;; esac
            mq_settle "$k" || true
        done
        fail "$@"
    }
    wait_abort() {   # $1 = the step, $2 = why: the queue cannot go on (an error, a cap, a pause, a block). The PRs still open are let go of below; what the queue merged already is deployed all the same
        abort_step="$1"; abort_why="$2"
        [ "$1" != "queue paused" ] || [ ${#merged_prs[@]} -gt 0 ] || q_fail=hold   # the release queue is paused already: nothing to pause again
    }
    member_fail() {   # $1 = a PR, $2 = the step, $3 = why: this PR alone failed before its merge (the queue ejected or failed it): a failed release of it, and the rest still go out
        local k keep=() why; why="$(printf '%s' "$3" | mq_plain)"
        for k in "${live_prs[@]}"; do [ "$k" = "$1" ] || keep+=("$k"); done; live_prs=("${keep[@]}")
        say "PR #$1 FAILED at $2: $why"; printf '%s\n' "$(say "FAILED at $2: $why")" >> "$LOGDIR/pr-$1.log"
        mqh_clear "$1"; gfailed=1   # the unit ends 1 when a PR of the group failed, though the others went out
        [ "$qstart" != 1 ] || { q_locked q_unqueue "$1"; q_log "skipped PR #$1: $2 before its merge (group of ${prs[*]})"; }
        tell "[release] PR #$1 FAILED at $2: $why; it was in a merge queue group with ${names}$([ "$qstart" != 1 ] || echo "; skipped in the release queue, which goes on") · log $LOGDIR/pr-$1.log"
    }
    pr_state() {   # $1 = a PR: OPEN, CLOSED or "MERGED <merge commit>" as GitHub says now; nothing when it cannot be read
        gh pr view "$1" --repo "$REPO" --json state,mergeCommit,headRefOid 2>/dev/null 5>&- 6>&- 7>&- 8>&- 9>&- | python3 -c '
import json, sys
d = json.load(sys.stdin); s = d.get("state") or ""
oid = ""
if s == "MERGED":   # the queue merges by fast-forward push, so GitHub may name no merge commit: the PR head is then given as head:<oid>, and the commit on main that brought it in is found once main is fetched (mq_landing)
    oid = (d.get("mergeCommit") or {}).get("oid") or ("head:" + d["headRefOid"] if d.get("headRefOid") else "")
print(s + (" " + oid if oid else ""))' 2>/dev/null
    }
    lose_pr() {   # $1 = a PR the queue merged, $2 = what is known: no commit can be named for it, so this group cannot deploy it: reported merged, not live; the others go on
        local k keep=()
        lost_prs+=("$1"); for k in "${live_prs[@]}"; do [ "$k" = "$1" ] || keep+=("$k"); done; live_prs=("${keep[@]}"); gfailed=1
        plog "$1" "FAILED at merge commit: $2: merged, not live (./deploy.sh by hand)"
        tell "[release] PR #$1 was merged by the merge queue but its merge commit is not known: merged, not live (./deploy.sh by hand once main's tip run is green) · log $LOGDIR/pr-$1.log"
        q_fail=pause; mqh_clear "$1"
    }
    adopt_merged() {   # $1 = a PR the queue gave up on, ejected ("pull request is merged") or has not answered for. Returns 0 when GitHub says it is merged (the queue merged it in a push with the earlier ones, or an earlier run of the group did) and it then goes out
                       # with the group (or is reported merged, not live when no commit can be named for it); 1 when it is not merged; 2 when GitHub's answer cannot be read (twice): the PR is then neither dropped nor called not merged
        local s; s="$(pr_state "$1")"
        if [ -z "$s" ]; then sleep 3; s="$(pr_state "$1")"; fi
        case "$s" in
            "MERGED "*) mqh_clear "$1"; merged_prs+=("$1"); shas+=("${s#MERGED }"); q_fail=pause; gsay "PR #$1 is merged on GitHub although the merge queue gave no merged answer for it: it is deployed with this group"; return 0 ;;
            MERGED) lose_pr "$1" "GitHub says PR #$1 is merged but names no merge commit or head for it"; return 0 ;;
            "") gsay "PR #$1: its state on GitHub could not be read (twice): pr state unreadable, so it is neither dropped from the merge queue nor called not merged"; return 2 ;;
        esac
        return 1
    }
    [ "$(q_driver)" != "$lead" ] || qstart=1   # the release queue started this group (it wrote the driver before the start)
    gsay "release of PRs $names starts in $HERE ($REPO): the merge queue (mode on) tests them as one group and merges it once"
    recover_pending   # a fast deploy of an earlier release whose process ended before main's run was read: looked at first
    local mqmode; mqmode="$(mq_host_mode)"
    [ "$mqmode" = on ] || fail "mq mode" "the host file's merge queue mode is now \"${mqmode#bad: }\", not on, so this group cannot go through the queue; nothing was merged. Set it to on again, or release.sh queue --resume to release the PRs one by one"
    mq_on_check || fail "mq mode" "$mq_why"
    command -v salamander >/dev/null 2>&1 || fail "mq" "salamander is not on PATH, so the merge queue cannot take the group; nothing was merged"
    if [ "$qstart" = 1 ] && [ -f "$QUEUE.paused" ]; then q_fail=hold; fail "queue paused" "the release queue is paused ($(head -1 "$QUEUE.paused")): this group was started by the queue before the pause and nothing was merged; release.sh queue --resume starts it once main is fixed"; fi
    for m in "${prs[@]:1}"; do   # a PR with a release unit of its own running (a lone release, by hand) is not taken: that release may be mid-merge. The lead's own unit is this one
        ! q_alive "$m" || fail "release running" "PR #$m has its own release running (stackshot-release-$m): a PR is never released by both; nothing was merged. Wait for it, or take PR #$m out of the queue (release.sh queue --drop $m)"
    done
    # each PR as GitHub says it now: one that is merged already (an earlier run of this group was killed after the queue merged it) is deployed with the group and not handed to the queue again, which would eject it
    local pst
    for m in "${prs[@]}"; do
        pst="$(pr_state "$m")"
        case "$pst" in
            "MERGED "*) mqh_clear "$m"; merged_prs+=("$m"); shas+=("${pst#MERGED }"); premerged="${premerged:+$premerged }#$m"; gsay "PR #$m is merged already (${pst#MERGED }): it is deployed with this group and not handed to the merge queue again" ;;
            MERGED) member_fail "$m" "pr state" "the PR is merged but GitHub names no merge commit for it: merged, not live (./deploy.sh by hand)" ;;
            CLOSED) member_fail "$m" "pr state" "the PR is closed" ;;
            *) addprs+=("$m") ;;
        esac
    done
    [ -z "$premerged" ] || pre_note="; $premerged had been merged by an earlier run of this group and went out with it"
    [ ${#merged_prs[@]} -eq 0 ] || q_fail=pause
    if [ ${#addprs[@]} -gt 0 ]; then
        for m in "${addprs[@]}"; do mqh_set "$m"; done   # before the add: from here the old path refuses these PRs
        out="$(timeout "$MQ_ON_ADD_TIMEOUT" salamander mq add "${addprs[@]}" --repo "$REPO" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
        if [ $rc -ne 0 ] || printf '%s\n' "$out" | grep -q '^salamander mq: '; then
            wait_abort "mq add" "salamander mq add ${addprs[*]} $([ $rc -eq 124 ] && echo "took more than ${MQ_ON_ADD_TIMEOUT}s" || echo "exited $rc"): $(printf '%s' "$out" | tail -n 2 | tr '\n' ' ' | cut -c1-300)"
        else
            gsay "merge queue: PRs ${addprs[*]} handed over in one call ($(printf '%s' "$out" | tail -n 1 | cut -c1-160 | mq_plain)); waiting for each"
            # one `mq wait` per PR, in slices of MQ_SLICE, up to MQ_WAIT_CAP in all; between slices the release queue's pause and the merge queue's own state are looked at once. A PR that merged, failed or was ejected is settled
            local deadline now left slice line st why_q
            deadline=$(( $(date +%s) + MQ_WAIT_CAP ))
            for m in "${addprs[@]}"; do
                while :; do
                    now="$(date +%s)"; left=$((deadline - now))
                    [ ${#merged_prs[@]} -eq 0 ] || q_fail=pause   # a merge has happened: every failure from here pauses and does not keep the merged PRs queued
                    if [ "$qstart" = 1 ] && [ -f "$QUEUE.paused" ]; then wait_abort "queue paused" "the release queue was paused while this group waited ($(head -1 "$QUEUE.paused")), so it stops waiting for PR #$m"; break 2; fi
                    if [ $left -le 0 ]; then wait_abort "mq wait" "the merge queue gave no verdict on PR #$m within ${MQ_WAIT_CAP}s"; break 2; fi
                    slice=$MQ_SLICE; [ $slice -le $left ] || slice=$left
                    out="$(timeout $((slice + 30)) salamander mq wait "$m" --repo "$REPO" --timeout "$slice" 2>&1 5>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
                    line="$(printf '%s\n' "$out" | grep -m1 -E '^PR [0-9]+[ :]' | cut -c1-300)"   # the verdict line: a line before it on stderr (the driver started again) is not it
                    [ -n "$line" ] || line="$(printf '%s\n' "$out" | head -n 1 | cut -c1-300)"
                    if printf '%s\n' "$out" | grep -q '^salamander mq: '; then   # salamander's own error (a host file, a state file), not a verdict on the PR, even at exit 1
                        wait_abort "mq wait" "salamander mq wait $m: $(printf '%s' "$out" | grep '^salamander mq: ' | head -n 1 | cut -c1-300)"; break 2
                    fi
                    case $rc in
                        0) sha="$(printf '%s' "$line" | sed -n 's/^PR [0-9]* merged: .* at \([0-9a-f]\{7,40\}\)\( \[.*\]\)\{0,1\}$/\1/p')"
                           if [ -z "$sha" ]; then   # the answer names no merge commit: GitHub knows it
                               pst="$(pr_state "$m")"; case "$pst" in "MERGED "*) sha="${pst#MERGED }" ;; esac
                           fi
                           mqh_clear "$m"
                           if [ -z "$sha" ]; then   # merged and cannot be found: not deployed by this group, and said so; the others go on
                               lose_pr "$m" "the merge queue merged PR #$m but neither its answer ($(printf '%s' "$line" | mq_plain)) nor GitHub names the merge commit"
                               break
                           fi
                           merged_prs+=("$m"); shas+=("$sha"); q_fail=pause; gsay "merge queue: $(printf '%s' "$line" | mq_plain)"; break ;;
                        1) adopt_merged "$m"; ar=$?
                           case $ar in 0) ;; 2) unk+=("$m"); unk_why="${unk_why:+$unk_why; }PR #$m: $(printf '%s' "${line:-no reason given}" | mq_plain)" ;;   # unresolved, not failed: it may be merged. Handled with the stop of the queue below (kept first in the release queue, its marker kept, not dropped)
                                       *) member_fail "$m" "merge queue" "the queue did not merge PR #$m: ${line:-no reason given}" ;; esac
                           break ;;   # "pull request is merged": the queue merged it in an earlier push, it is on main
                        2) if printf '%s' "$out" | grep -q 'gave up waiting'; then   # this slice ran out: is the queue still able to merge?
                               st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 5>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
                               why_q="$(printf '%s' "$st" | python3 -c '
import json, sys
d = json.load(sys.stdin); p = d.get("paused"); b = d.get("blocked")
print(("paused: " + str(p.get("reason", ""))) if p else ("blocked: " + str(b.get("reason", ""))) if b else "")' 2>/dev/null)"
                               [ -z "$why_q" ] || { wait_abort "mq" "the merge queue is $why_q, so PR #$m cannot be merged"; break 2; }
                               continue
                           fi
                           if printf '%s' "$out" | grep -q 'the queue is blocked'; then wait_abort "mq" "the merge queue is blocked ($(printf '%s' "$line" | mq_plain)), so PR #$m cannot be merged"; break 2; fi
                           wait_abort "mq wait" "salamander mq wait $m: $line"; break 2 ;;
                        *) wait_abort "mq wait" "salamander mq wait $m exited $rc ($(printf '%s' "$line" | mq_plain)): not a verdict the release can use"; break 2 ;;
                    esac
                done
            done
        fi
    fi
    if [ -z "$abort_step" ] && [ ${#unk[@]} -gt 0 ]; then abort_step="pr state"; abort_why="GitHub's state of the PRs the merge queue ejected could not be read to check whether they are merged anyway ($unk_why)"; fi   # handled below like any other stop of the queue
    local -a un=()
    if [ -n "$abort_step" ]; then   # the queue could not go on: the PRs still open are let go of; what it merged before is deployed below, and the release queue is paused
        unk=()   # read again below
        for k in "${live_prs[@]}"; do   # the queue merges a group in one push: a PR whose wait was not reached may be on main already, and is deployed, never failed
            case " ${merged_prs[*]} " in *" $k "*) continue ;; esac
            adopt_merged "$k"; ar=$?
            case $ar in 0) ;; 2) un+=("$k"); unk+=("$k") ;; *) un+=("$k") ;; esac
        done
        if [ ${#un[@]} -eq 0 ]; then abort_step=""; say "the merge queue could not go on ($abort_why), but every PR of the group is merged on GitHub: nothing is left to drop"; fi
    fi
    if [ -n "$abort_step" ]; then
        local unk_note="" dep_note="" lostn=""
        for k in "${un[@]}"; do
            unn="${unn:+$unn }#$k"
            case " ${unk[*]:-} " in *" $k "*) continue ;; esac   # its state is unknown: it is not dropped (it may be merged), and keeps its marker
            mq_settle "$k" || true
        done
        [ ${#unk[@]} -eq 0 ] || unk_note="; PRs ${unk[*]} were not dropped from the merge queue and keep their markers: their state on GitHub could not be read (pr state unreadable), check them by hand (gh pr view, salamander mq status)"
        if [ ${#merged_prs[@]} -eq 0 ] && [ ${#lost_prs[@]} -eq 0 ]; then
            local -a keep_live=()   # fail() writes FAILED for every PR still live: not for those whose state is unknown (they may be merged); they get their unresolved line first
            for k in "${live_prs[@]}"; do
                case " ${unk[*]:-} " in *" $k "*) plog "$k" "unresolved at $abort_step: $(printf '%s' "$abort_why" | mq_plain); pr state unreadable: not dropped from the merge queue, marker kept" ;; *) keep_live+=("$k") ;; esac
            done
            live_prs=(${keep_live[@]+"${keep_live[@]}"})
            fail "$abort_step" "$abort_why; $([ ${#unk[@]} -eq 0 ] && echo "the PRs still open were dropped from the merge queue (best effort); nothing was merged" || echo "no PR is known to be merged")$unk_note"
        fi
        for k in "${un[@]}"; do
            case " ${unk[*]:-} " in *" $k "*) plog "$k" "unresolved at $abort_step: $(printf '%s' "$abort_why" | mq_plain); pr state unreadable: not dropped from the merge queue, marker kept" ;;
                                    *) plog "$k" "FAILED at $abort_step: $(printf '%s' "$abort_why" | mq_plain); dropped from the merge queue, not merged" ;; esac
        done
        for k in "${lost_prs[@]}"; do lostn="${lostn:+$lostn }#$k"; done
        if [ ${#merged_prs[@]} -gt 0 ]; then dep_note="PRs $(mn), merged by the same group, are deployed next"; else dep_note="PRs $lostn were merged by the queue but this group cannot deploy them (merged, not live)"; fi
        held_prs=("${un[@]}"); live_prs=("${merged_prs[@]}"); gfailed=1
        say "FAILED at $abort_step: $abort_why; PRs $unn $([ ${#unk[@]} -gt 0 ] || echo "dropped from the merge queue and ")not merged$unk_note; $dep_note"
        tell "[release] PRs $unn FAILED at $abort_step: $abort_why; they $([ ${#unk[@]} -gt 0 ] && echo "are" || echo "were dropped from the merge queue and are") not merged$unk_note$([ "$qstart" != 1 ] || echo ", still first in the release queue (release.sh queue --resume once it is fixed)"); $dep_note · log $glog"
        if [ "$abort_step" != "queue paused" ] && [ "$qstart" = 1 ]; then   # release.sh's queue is paused now, before the deploy (the pause text names the group, not one failed PR); a pause that is there already stands
            q_locked qg_pause_locked "$abort_step" pause; say "release queue: paused (the group of PRs ${prs[*]} could not go on at $abort_step after the merge queue's merge): no new release starts; release.sh queue --resume once it is fixed"
        fi
        q_fail=pause
    fi
    if [ ${#merged_prs[@]} -eq 0 ]; then   # nothing merged: every PR was reported failed on its own; the release queue goes on with what is behind them
        gsay "the merge queue gave this group no merged PR to deploy ($names); nothing to deploy"
        if [ ${#lost_prs[@]} -gt 0 ]; then merged_prs=("${lost_prs[@]}"); qg_after_fail "merge commit"; exit 1; fi   # merged and not live: the queue is paused (they leave it) and does not hand on
        qg_handoff "ended with none of them merged"; exit 1
    fi
    q_fail=pause   # from here a failure is one of merged PRs
    # ---- what the queue merged goes out together. The merge commit is the one every other is an ancestor of (the chain merges one PR a push, each on top of the last)
    fetch_retry || fail "merge commit" "the merge queue merged $(mn) but main cannot be fetched to find its merge commit; merged, not live (./deploy.sh by hand)"
    local s7 c T="" M="" ok i hd land; local -a fulls=() uniq
    for i in "${!merged_prs[@]}"; do   # a PR GitHub named no merge commit for (head:<oid>) is found on main now that main is fetched
        case "${shas[$i]}" in head:*) ;; *) continue ;; esac
        hd="${shas[$i]#head:}"; land="$(mq_landing "$hd")"
        if [ -n "$land" ]; then gsay "PR #${merged_prs[$i]}: GitHub names no merge commit; its head ${hd:0:7} landed on main as ${land:0:7}"; shas[$i]="$land"
        else lose_pr "${merged_prs[$i]}" "GitHub names no merge commit for PR #${merged_prs[$i]} and its head ${hd:0:7} is not on main's first-parent line"; unset "merged_prs[$i]" "shas[$i]"; fi
    done
    merged_prs=(${merged_prs[@]+"${merged_prs[@]}"}); shas=(${shas[@]+"${shas[@]}"})
    if [ ${#merged_prs[@]} -eq 0 ]; then gsay "none of the merged PRs can be deployed by this group ($names)"; merged_prs=("${lost_prs[@]}"); qg_after_fail "merge commit"; exit 1; fi
    mapfile -t uniq < <(printf '%s\n' "${shas[@]}" | sort -u)
    for s7 in "${uniq[@]}"; do
        c="$(git rev-parse --verify --quiet "$s7^{commit}" 2>/dev/null)"
        [[ "$c" =~ ^[0-9a-f]{40,64}$ ]] || fail "merge commit" "the merge queue's merge commit $s7 is not a commit this checkout knows after fetching main (or the abbreviation is ambiguous); merged, not live (./deploy.sh by hand)"
        fulls+=("$c")
    done
    T="$(git rev-parse origin/main 2>/dev/null)"
    for c in "${fulls[@]}"; do
        ok=1; for k in "${fulls[@]}"; do git merge-base --is-ancestor "$k" "$c" || ok=0; done
        [ $ok = 0 ] || { M="$c"; break; }
    done
    [ -n "$M" ] || fail "merge commit" "the merge commits the queue reported (${uniq[*]}) are not in one line; merged, not live (./deploy.sh by hand)"
    git merge-base --is-ancestor "$M" "$T" || fail "merge commit" "the merge commit ${M:0:7} is not in main's history (tip ${T:0:7}); merged, not live (./deploy.sh by hand)"
    gsay "merged by the merge queue: $(mn) at ${M:0:7} (main's tip ${T:0:7}); deploying them once"
    take_lock "merged, not live (./deploy.sh by hand once it is free)"
    # the queue's merge commits (first-parent "Merge pull request #N" of the merged PRs between the live checkout and the merge) go into the fast-ok ledger: each was tested as part of the exact tree that was merged
    # (the group's run on the queue branch), which is what the ledger vouches for, so fast_gate (a) counts the live checkout as at the tip while they are not deployed yet
    local cur subj cc num; cur="$(git rev-parse HEAD)"
    while read -r cc subj; do
        case "$subj" in "Merge pull request #"*) num="${subj#Merge pull request #}"; num="${num%% *}"; case " ${merged_prs[*]} " in *" $num "*) ledger_add "$cc" "$num" ;; esac ;; esac
    done < <(git log --first-parent --format='%H %s' "$cur..$M" 2>/dev/null)
    local why_fast="the merge queue tested exactly this tree (its group's run on the queue branch)" fast_note=""
    if fast_gate "$T"; then fast=1; say "the live checkout is what main was before the group (or behind it only by merges that ride along): deploying at the merge; ${good:0:7} is the last good commit to go back to"
    else say "not deployed at the merge: $fast_why; the deploy waits for main's tests (the old path)"; fi
    if [ $fast = 1 ]; then
        verified="$M"; say "deploying ${verified:0:7} at once: $why_fast; main's full run follows"
        fast_note="; deployed at the merge ($why_fast): main's full run follows and rolls it back to ${good:0:7} on a failure"
        pending_set "$verified" "$pr"   # before deploy.sh: production changes at its fast-forward; a kill in there must leave the record
    else
        exec 9>&-   # the wait for main's run is outside the lock, as on the old path
        main_green pre "$M"
        take_lock "merged, not live (./deploy.sh by hand once it is free)"
    fi
    out="$(DEPLOY_TO="$verified" ./deploy.sh 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
    sha="$(git rev-parse --short HEAD)"
    [ $rc -eq 0 ] || q_pause_now "deploy"   # a failed deploy pauses the queue before the lock is let go, as on the old path
    exec 9>&-
    [ $rc -eq 0 ] || { pending_clear; fail "deploy" "$(echo "$out" | tail -1) (main is merged at $sha; the checkout is at $(git rev-parse --short HEAD)): merged, not live"; }
    restarted="$(echo "$out" | sed -n 's/^  restarted //p' | tr '\n' ' ')"; restarted="${restarted:-nothing}"
    say "done: $sha, restarted $restarted"
    for m in "${merged_prs[@]}"; do plog "$m" "done: $sha, restarted $restarted"; done   # the line a waiter and the board hooks look for, in each PR's own log
    # THE SESSION PICK for the whole group: the highest need among the files of all its PRs (a forced --recycle does not exist here)
    local pf="" pfa pk_note="" pk_files_ok=1 nt_note="" nrc=0 nsum="nothing to reload" flagged=0 rd
    for m in "${merged_prs[@]}"; do
        if pfa="$(pr_files "$m" 2>"$LOGDIR/pick-err-$lead")"; then pf="$pf$pfa"$'\n'; else pk_files_ok=0; pk_note="the files of PR #$m could not be read ($(tail -1 "$LOGDIR/pick-err-$lead" 2>/dev/null | cut -c1-160))"; fi
    done
    rm -f "$LOGDIR/pick-err-$lead"
    if [ $pk_files_ok = 1 ]; then pick_session <<< "$pf"; printf '%s' "$PICK_TABLE"; else PICK=nothing; PICK_NOTICE=0; PICK_FROM="$pk_note; release.sh --pick <pr> shows what it would have been"; fi
    say "session pick: $(pick_label) (from $PICK_FROM)"
    pk_note="; sessions: $(pick_label) (from $PICK_FROM)"
    recycle=""; [ "$PICK" = recycle ] && recycle=--recycle
    NOTICE_SENT=""
    if [ "${PICK_NOTICE:-0}" = 1 ]; then
        [ "$recycle" != --recycle ] || nsum="a recycle does not deliver it"
        notice_send "release: stackshot PRs $names" "stackshot PRs $names are live at $sha; what sessions are told changed in $NOTICE_FROM; $nsum" || nrc=$?
        case $nrc in
            0) nt_note="; notice: sent with [fleet] notice_cmd"; NOTICE_SENT=1 ;;
            1) nt_note="; notice: none sent, no [fleet] notice_cmd is set" ;;
            3) nt_note="; notice NOT sent: [fleet] notice_cmd timed out after ${NOTICE_TIMEOUT}s and was stopped" ;;
            *) nt_note="; notice NOT sent: [fleet] notice_cmd failed or is not on PATH" ;;
        esac
        say "${nt_note#; }"; rc_note="$nt_note"
    fi
    if [ "$recycle" = --recycle ]; then   # flag the items the PRs serve; with none flagged, the fleet tool is asked once for a recycle when the box is idle
        for m in "${merged_prs[@]}"; do
            if rd="$(python3 client.py recycle-due --pr "https://github.com/$REPO/pull/$m" 2>&1)"; then flagged=1; rc_note="$rc_note; recycle (PR #$m): $(echo "$rd" | sed 's/^stackshot: //' | paste -sd ';' -)"; fi
        done
        if [ $flagged = 1 ]; then :
        elif idle_recycle "release: stackshot PRs $names"; then rc_note="$rc_note; recycle: no item flagged, so the fleet tool was asked for one once the box is idle"
        else rc_note="$rc_note; recycle NOT marked: no item was flagged and the fleet tool could not be asked"; fi
        say "recycle: ${rc_note#; }"
    fi
    local green_ok=1
    case "$rc_note" in *"recycle NOT marked"*|*"notice NOT sent"*) green_ok=0 ;; esac
    [ $pk_files_ok = 1 ] || green_ok=0
    [ -z "$audit_note" ] || green_ok=0
    for m in "${merged_prs[@]}"; do   # one report per PR, each green on its own (--release green --pr), so every PR's items settle
        title="$(gh pr view "$m" --repo "$REPO" --json title 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "")' 2>/dev/null)"
        local -a green=(); [ $green_ok = 1 ] && green=(--release green --pr "https://github.com/$REPO/pull/$m")
        tell "[release] PR #$m merged and deployed — ${title:-PR #$m} — main at $sha, restarted: $restarted, healthz ok; merged by the merge queue in one group with $(mn)$pre_note$fast_note$audit_note$pk_note$rc_note · log $LOGDIR/pr-$m.log" "${green[@]}"
    done
    qg_handoff deployed   # deployed: the group's PRs leave the queue file (those the queue could not merge stay, first) and the next waiting ones start
    if [ $fast = 0 ]; then for m in "${merged_prs[@]}"; do released "$m" "$verified"; done; return $gfailed; fi   # the old path deployed only after main's tests passed on the merge: it is live now
    # after a deploy at the merge: main's full run for that commit, outside the lock; a pass is a log line, a failure rolls back (rollback() reports the lead and each rider it took out)
    if main_green post "$verified"; then
        pending_clear
        if [ -n "$mg_notlive" ]; then
            tell "[release] PRs $names: main's tests passed on ${verified:0:7}, but it is not live ($mg_notlive); it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green · log $glog"
            return $gfailed
        fi
        [ -z "$audit_note" ] || tell "[release] PRs $names deployed at ${verified:0:7}${audit_note} · log $glog"
        for m in "${merged_prs[@]}"; do released "$m" "$verified"; done
        return $gfailed
    fi
    case "$mg_kind" in
        fail) rollback ;;
        *) pending_clear; q_fail=none; fail "main's tests" "$mg_why: deployed at ${verified:0:7} and NOT rolled back, main's run was not read; look at it" ;;
    esac
}

run() {
    local pr="$1" recycle="${2:-}" log="$LOGDIR/pr-$1.log" title sha restarted step rc_note="" merge_note="" audit_note="" verified="" ROLLED_MARK="$LOGDIR/pr-$1.rolledback" mg_notlive="" q_fail=skip q_note="" q_riders="" qstart=0
    exec > >(tee -a "$log") 2>&1
    say "release of PR #$pr starts in $HERE ($REPO)"
    [ "$(q_driver)" != "$pr" ] || qstart=1   # the queue started this release (it wrote the driver before the start): its pause and its pre-merge stops apply to it
    fail() { MQ_FAIL="$1: $2"; say "FAILED at $1: $2"; queue_after_fail "$1"; tell "[release] PR #$pr FAILED at $1: $2$q_note · log $log"; exit 1; }
    recover_pending   # a fast deploy of an earlier release whose process ended before main's run was read (killed, the box restarted): looked at first
    local mqmode; mqmode="$(mq_host_mode)"   # THE MERGE QUEUE, SHADOW: off (no host file) changes nothing below
    case "$mqmode" in
        off|shadow) ;;
        on) # THE MERGE QUEUE, ON: a lone PR (this release: one PR waiting, or released by hand) takes this path exactly as in mode off, with no call to the queue at all. Only two things differ: the host file must name the
            # deploy lock this script takes (mq_on_check: it is what keeps the queue's merge push out of this release's merge and deploy), and a PR the queue holds is never merged here (the marker of a group release, MQ_HANDED)
            mq_on_check || fail "mq mode" "$mq_why"
            [ ! -e "$MQ_HANDED/pr-$pr" ] || fail "mq line" "PR #$pr was handed to the merge queue ($(cut -c1-120 "$MQ_HANDED/pr-$pr")) and may still be in its line: the old path would merge what the queue also holds; nothing was merged. release.sh queue --resume goes on with its group release, or take the PR out of the queue (salamander mq drop $pr) and delete $MQ_HANDED/pr-$pr"
            say "merge queue (on): PR #$pr is released alone, by this release's own path; the queue is not used for it" ;;
        *) say "merge queue: the host file does not read (${mqmode#bad: }); the merge queue is not used and this release goes the old way"; mqmode=off ;;
    esac
    local view state mergeable regens=0 regen_pushed=0   # regen_pushed: 1 once the mergeable stage pushed a regenerated snapshot merge; regens: snapshot regenerations made so far in this release (2a', bounded by REGEN_MAX)
    read_view() {   # the PR as GitHub says it now: $view, $title, $state, $mergeable
        view="$(gh pr view "$pr" --repo "$REPO" --json state,mergeable,title,headRefName,isCrossRepository,headRefOid 2>&1)" || fail "pr view" "$(echo "$view" | tail -1)"
        title="$(echo "$view" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["title"])')"
        state="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"; mergeable="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["mergeable"])')"
    }
    read_view
    # GitHub recomputes mergeable for a little while after main moves and says UNKNOWN meanwhile (a PR can fail on it right after another merge):
    # read again every 10 s for up to MERGEABLE_WAIT (3 min). CONFLICTING, or UNKNOWN when the time is up, fails; so does a PR that is no longer open.
    if [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ]; then
        say "GitHub says mergeable UNKNOWN (it is still computing, as it does after main moves); reading again every 10 s for up to $((MERGEABLE_WAIT/60)) min"
        local mwaited=0
        while [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ] && [ $mwaited -lt $MERGEABLE_WAIT ]; do sleep 10; mwaited=$((mwaited+10)); read_view; done
    fi
    [ "$state" = OPEN ] || fail "pr state" "the PR is $state"
    if [ "$mergeable" = CONFLICTING ]; then   # 2a': a conflict that is only the generated tool-text snapshot is mended here, then GitHub is read until it has the new head and has recomputed; anything else falls to the case below as before
        local oldh; oldh="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"
        if regen_snapshot mergeable; then
            regen_pushed=1   # the head is a new commit: its checks are waited on like an updated head's (the tests job must be among them and have passed), not as the quiet first wait
            local rwaited=0
            while :; do
                sleep 10; rwaited=$((rwaited+10)); read_view; [ "$state" = OPEN ] || break
                if [ "$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')" != "$oldh" ] && [ "$mergeable" != UNKNOWN ] && [ "$mergeable" != CONFLICTING ]; then break; fi
                [ $rwaited -lt $MERGEABLE_WAIT ] || break
            done
            [ "$state" = OPEN ] || fail "pr state" "the PR is $state"
            say "mergeable: after the snapshot regeneration GitHub says $mergeable (head $(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"][:7])'))"
        fi
    fi
    case "$mergeable" in
        MERGEABLE) ;;
        CONFLICTING) fail "mergeable" "GitHub says CONFLICTING: the PR has a conflict with main" ;;
        UNKNOWN) fail "mergeable" "GitHub still says UNKNOWN after $((MERGEABLE_WAIT/60)) min: it has not finished computing whether the PR merges; run release.sh again" ;;
        *) fail "mergeable" "GitHub says $mergeable" ;;
    esac
    local headsha; headsha="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"
    [[ "$headsha" =~ ^[0-9a-f]{7,64}$ ]] || fail "pr view" "no head commit in GitHub's answer ($headsha)"
    say "PR #$pr: $title (head ${headsha:0:7})"
    [ "$mqmode" != shadow ] || mq_shadow_add "$pr"   # before the old path decides: once it has merged the PR the queue could no longer test it
    local fast=0 utd=0 base="" good="" fast_why="" mergesha="" fast_note="" mergeoid="" rounds=0 utd_kind="" upd_note="" upd_stop="" skipped=0 sk=0 skip_note="" skip_why="" why_fast="the PR's checks passed on a branch up to date with main"
    if [ "$regen_pushed" = 1 ]; then wait_pr_checks "pr tests" progress "the PR's tests pass on the pushed head ${headsha:0:7}"   # as after update-branch: a quick check alone must not read as a pass on the new head
    else wait_pr_checks checks quiet "checks pass"; fi
    q_paused_stop   # the wait for the checks can be long: a pause that came meanwhile stops this release before it touches the PR's branch or merges it
    # Not up to date (the owner's rule: main's full run never blocks a release): the PR's checks passed, but its branch is behind main, so it would take the old path and
    # wait for main's full run (a long run; in a burst of PRs only the first would be up to date). Bring it up to date instead: update-branch, the PR's own tests on
    # the new head, and the fast path after. Releases that both need an update take turns (the update lock, held up to the merge), so they do not keep invalidating each other's;
    # a PR that is up to date from the start takes no update lock, so its merge can still land on main during a round: that sends the updating release to another round, or after 3 to the old path (safe).
    if ! up_to_date "$pr" "$headsha" && [ "$utd_kind" = behind ]; then
        if skip_retest "$headsha"; then skipped=1; upd_note="; the branch was behind main and was NOT retested: its last green checks stand, because no test group reads both what the PR changed and what main's new commits changed ($skip_note)"
        elif bring_up_to_date; then
            if [ $rounds -gt 0 ]; then upd_note="; the branch was behind main: release.sh brought it up to date with update-branch ($rounds round(s)) and the PR's tests passed on the new head ${headsha:0:7}"
            else upd_note="; the branch was behind main when its checks passed, but needed no update once this release had the update lock (head ${headsha:0:7})"; fi
        elif [ $rounds -gt 0 ]; then upd_note="; the branch was brought up to date with update-branch ($rounds round(s), the PR's tests passed on ${headsha:0:7}) but then $upd_stop, so it took the old path"
        else upd_note="; the branch was behind main, but the update did not start ($upd_stop), so it took the old path"; fi
    fi
    # merge and deploy take the deploy lock, so two releases never deploy at once; the wait for checks above is outside it. fd 9 is closed for every
    # child of the merge and the deploy (a service a deploy leaves behind must never inherit the lock); it is released when deploy.sh returns.
    q_paused_stop   # again, after the update and its tests, before the deploy lock
    take_lock "nothing was merged (release.sh $pr again once it is free)"
    q_paused_stop   # and once more: the wait for the lock can be long, and nothing is merged yet
    # THE MERGE QUEUE, ON: a group release may have handed this PR to the queue while this release waited for its checks or for the lock (a hand-run lone release races a group that includes it): looked at again, under the lock, just before the merge
    [ "$mqmode" != on ] || [ ! -e "$MQ_HANDED/pr-$pr" ] || fail "mq line" "PR #$pr was handed to the merge queue while this release waited ($(cut -c1-120 "$MQ_HANDED/pr-$pr")); nothing was merged here. The group release reports it"
    # Release on PR pass: a PR whose checks passed on a head that contains main's tip merges into the very tree those checks ran on,
    # so it deploys at the merge; main's full run follows and rolls it back on a failure. Anything else keeps the old path (main's run first).
    # utd: the PR's checks ran on a head that contains main's tip (2c). That alone makes the merge a fast-ok one (recorded after the merge, see below), whether or not fast_gate lets it deploy at the merge.
    if up_to_date "$pr" "$headsha"; then utd=1; if fast_gate "$base"; then fast=1; say "up to date: the PR head ${headsha:0:7} contains main's tip ${base:0:7}, which is what is live; ${good:0:7} is the last good commit to go back to"; fi; fi
    # 2a'': the retest was skipped before the lock; main may have moved meanwhile, so the decision is made again on the tip as it is now. A merge made this way is not entered in the ledger (utd stays 0): the tree was not the one tested.
    if [ $utd = 0 ] && [ $skipped = 1 ]; then
        if [ "$utd_kind" = behind ] && skip_retest "$headsha"; then sk=1; why_fast="the PR's last green checks stand, because no test group reads both what the PR changed and what main's new commits changed"
            if fast_gate "$base"; then fast=1; say "no retest: $why_fast; main's tip ${base:0:7} is what is live; ${good:0:7} is the last good commit to go back to"; fi
        else skip_why="${skip_why:-$fast_why}"; fast_why="${fast_why:+$fast_why; }the retest skip no longer holds: $skip_why"; skipped=0; upd_note="; the branch was behind main and its retest was skipped, but then $skip_why, so it took the old path"; fi
    fi
    [ $fast = 1 ] || say "not up to date for a deploy at the merge: $fast_why; the deploy waits for main's tests (the old path)"
    local out; if out="$(gh pr merge "$pr" --repo "$REPO" --merge --match-head-commit "$headsha" 2>&1 9>&-)"; then say "merged"
    else   # the call can error after the merge went through (a 504): GitHub's answer is eventually consistent, so ask again
        local err; err="$(echo "$out" | tail -1)"; say "the merge call errored: $err; reading the PR's state again"
        local i after merged_at="" merged_full=""
        for i in 1 2 3 4 5 6; do
            after="$(gh pr view "$pr" --repo "$REPO" --json state,mergeCommit 2>/dev/null)" && merged_full="$(echo "$after" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if d.get("state")=="MERGED": print((d.get("mergeCommit") or {}).get("oid") or "unknown")' 2>/dev/null)" && merged_at="${merged_full:0:7}"
            [ -n "$merged_at" ] && break
            [ $i -lt 6 ] && sleep 10
        done
        [ -n "$merged_at" ] || fail "merge" "$err"
        say "the merge call errored ($err) but the PR is merged at $merged_at; carrying on as a clean merge"
        [[ "$merged_full" =~ ^[0-9a-f]{7,64}$ ]] && mergeoid="$merged_full"
        merge_note="; the merge call errored ($err) but the PR was merged at $merged_at"
    fi
    exec 5>&-   # the merge is made: the next release may bring its branch up to date on top of it
    MQ_MERGED=1   # for the shadow comparison: from here the old path has merged the PR
    q_fail=pause   # from here a failure is one of a merged release: it pauses the release queue (before the merge it was skipped and the queue went on)
    # the head branch goes after the merge, never with it: the open PRs based on it are retargeted to main first (one is closed when the PR it was based on merges)
    retarget_and_delete_branch "$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("headRefName") or "")')" \
        "$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("isCrossRepository") is True)')"
    if [ $utd = 1 ] || [ $sk = 1 ]; then   # the merge must be the head on the tip that was checked, else it is not the tree the checks ran on
        if merge_commit "$base" "$headsha"; then [ $sk = 1 ] || ledger_add "$mergesha" "$pr"   # a merge of a head that contained the tip, and nothing landed between: a later release may ride along on it
        elif [ $fast = 1 ]; then fast=0; say "not deployed at the merge: $fast_why; the deploy waits for main's tests (the old path)"; fi
    fi
    if [ $fast = 1 ]; then   # still under the lock: deploy the merge commit now, main's run is waited for after the deploy and outside the lock
        verified="$mergesha"; say "deploying ${verified:0:7} at once: $why_fast; main's full run follows"
        fast_note="; deployed at the merge ($why_fast): main's full run follows and rolls it back to ${good:0:7} on a failure"
        pending_set "$verified" "$pr"   # before deploy.sh: production changes at its fast-forward, and the restarts and healthz take up to 180 s; a kill in there must leave the record
    else
        # main's tests run outside the lock: a release waiting on main's run must not hold another release's deploy,
        # so the lock is let go for the wait and taken again for the deploy
        exec 9>&-
        [ -n "$mergeoid" ] || merge_oid "$pr"
        main_green pre "$mergeoid"
        take_lock "merged, not deployed (./deploy.sh by hand once it is free)"
    fi
    out="$(DEPLOY_TO="$verified" ./deploy.sh 2>&1 9>&- 7>&- 6>&-)"; local rc=$?; echo "$out"
    sha="$(git rev-parse --short HEAD)"
    [ $rc -eq 0 ] || q_pause_now "deploy"   # a failed deploy pauses the queue before the lock is let go, as a rollback does
    exec 9>&-     # the lock is released here: the failure report, the recycle step and the message below start children that must not inherit it
    [ $rc -eq 0 ] || { pending_clear; fail "deploy" "$(echo "$out" | tail -1) (main is merged at $sha; the checkout is at $(git rev-parse --short HEAD))"; }   # reported red here: nothing left to verify
    restarted="$(echo "$out" | sed -n 's/^  restarted //p' | tr '\n' ' ')"; restarted="${restarted:-nothing}"
    say "done: $sha, restarted $restarted"
    # THE SESSION PICK: what the running sessions need, from the files the PR changed (or the override). recycle keeps its old meaning below
    # (--recycle: the recycle step runs, and the rollback report says one was flagged)
    local pk_note="" pk_files_ok=1
    case "$recycle" in
        --recycle) PICK=recycle; PICK_NOTICE=0; PICK_FROM="forced by --recycle" ;;
        --no-recycle) PICK=nothing; PICK_NOTICE=0; PICK_FROM="forced by --no-recycle" ;;
        *)  local pf
            local perr="$LOGDIR/pick-err-$pr"
            if pf="$(pr_files "$pr" 2>"$perr")"; then pick_session <<< "$pf"; printf '%s' "$PICK_TABLE"
            else pk_files_ok=0; PICK=nothing; PICK_NOTICE=0; PICK_FROM="the PR's changed files could not be read ($(tail -1 "$perr" 2>/dev/null | cut -c1-160)); release.sh --pick $pr shows what it would have been"; fi
            rm -f "$perr" ;;
    esac
    say "session pick: $(pick_label) (from $PICK_FROM)"
    pk_note="; sessions: $(pick_label) (from $PICK_FROM)"
    recycle=""; [ "$PICK" = recycle ] && recycle=--recycle
    local nt_note=""
    NOTICE_SENT=""
    if [ "${PICK_NOTICE:-0}" = 1 ]; then   # a rule or wording sessions should know about: told. Alone it needs no reload; with a recycle it is told as well, since a recycle does not deliver it
        local nrc=0 nsum="nothing to reload"; [ "$recycle" != --recycle ] || nsum="a recycle does not deliver it"
        notice_send "release: stackshot PR #$pr: $title" "stackshot PR #$pr is live at $sha; what sessions are told changed in $NOTICE_FROM; $nsum" || nrc=$?
        case $nrc in
            0) nt_note="; notice: sent with [fleet] notice_cmd"; NOTICE_SENT=1 ;;
            1) nt_note="; notice: none sent, no [fleet] notice_cmd is set" ;;
            3) nt_note="; notice NOT sent: [fleet] notice_cmd timed out after ${NOTICE_TIMEOUT}s and was stopped" ;;
            *) nt_note="; notice NOT sent: [fleet] notice_cmd failed or is not on PATH" ;;
        esac
        say "${nt_note#; }"
        rc_note="$nt_note"
    fi
    if [ "$recycle" = --recycle ]; then   # flag the item the PR serves; a recycle is never an item of its own
        local url="https://github.com/$REPO/pull/$pr" rd
        if rd="$(python3 client.py recycle-due --pr "$url" 2>&1)"; then rc_note="; recycle: $(echo "$rd" | sed 's/^stackshot: //' | paste -sd ';' -)"
        elif idle_recycle "release: stackshot PR #$pr: $title"; then
            rc_note="; recycle: no item flagged ($(echo "$rd" | tail -1 | sed 's/^stackshot: //' | cut -c1-160)), so the fleet tool was asked for one once the box is idle"
        else rc_note="; recycle NOT marked: $(echo "$rd" | tail -1)"; fi
        rc_note="$rc_note (a recycle delivers what a session loads once, at its start, the SessionStart hook; not a tool or schema change, which claude.ai picks up within about a day)"
        say "recycle: ${rc_note#; recycle: }"
        rc_note="$nt_note$rc_note"   # the notice's words stay in the report beside the recycle's
    fi
    local green=(--release green --pr "https://github.com/$REPO/pull/$pr")   # log-only on the server, ruled automatically (the turn rule's second build)
    case "$rc_note" in *"recycle NOT marked"*|*"notice NOT sent"*) green=() ;; esac   # a recycle that could not be asked for, or a notice that failed, is not green: delivered as before
    [ $pk_files_ok = 1 ] || green=()                                          # nor is a pick made blind (the PR's files unreadable): the keeper looks
    [ -z "$audit_note" ] || green=()                                          # nor is a selection miss on main: the keeper looks at the rules
    tell "[release] PR #$pr merged and deployed — $title — main at $sha, restarted: $restarted, healthz ok$merge_note$upd_note$fast_note$audit_note$pk_note$rc_note · log $log" "${green[@]}"
    q_handoff deployed   # deployed: from here this release only waits on main's run (the fast path) or is done (the old path), so the next queued PR's release starts now
    [ $fast = 1 ] || { released "$pr" "${mergeoid:-$verified}"; return 0; }   # the old path deployed only after main's tests passed on the merge: it is live now
    # after a deploy at the merge: main's full run for that commit, outside the lock. A pass is a log line (the report went out with the deploy);
    # what else the run found goes to the keeper; a failure rolls back; a run that could not be read in time rolls nothing back
    if main_green post "$verified"; then
        pending_clear
        if [ -n "$mg_notlive" ]; then   # another release's failure rolled this one back while it waited: it passed, and is not live
            tell "[release] PR #$pr: main's tests passed on ${verified:0:7}, but it is not live ($mg_notlive); it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green · log $log"
            return 0
        fi
        [ -z "$audit_note" ] || tell "[release] PR #$pr deployed at ${verified:0:7}${audit_note} · log $log"
        released "$pr" "$verified"   # main's tests passed on the live merge: the items built for the PR are settled
        return 0
    fi
    case "$mg_kind" in
        fail) rollback ;;
        *) pending_clear; q_fail=none; fail "main's tests" "$mg_why: deployed at ${verified:0:7} and NOT rolled back, main's run was not read; look at it" ;;   # not read is not a failure: the queue is not paused
    esac
}

case "${1:-}" in
    --run) [ -n "${2:-}" ] && [[ "${3:-}" =~ ^(|--recycle|--no-recycle)$ ]] || { echo "usage: release.sh --run <pr> [--recycle | --no-recycle]" >&2; exit 2; }; run "$2" "${3:-}"; exit $? ;;
    --pick|--pick-files)   # dry run: the session pick and each file's need, nothing else (no unit, no merge, no message)
        if [ "$1" = --pick ]; then
            [[ "${2:-}" =~ ^[0-9]+$ ]] && [ $# -eq 2 ] || { echo "usage: release.sh --pick <pr> | --pick-files <file>..." >&2; exit 2; }
            pf="$(pr_files "$2")" || { echo "the files of PR #$2 could not be read from GitHub" >&2; exit 1; }
            what="PR #$2"
        else
            [ $# -ge 2 ] || { echo "usage: release.sh --pick <pr> | --pick-files <file>..." >&2; exit 2; }
            shift; pf="$(printf '%s\n' "$@")"; what="the files named"
        fi
        pick_session <<< "$pf"
        echo "session pick for $what: $(pick_label) (from $PICK_FROM)"; printf '%s' "$PICK_TABLE"; exit 0 ;;   # an exit in every arm: a deploy replaces this very file, and bash must not read on from a stale offset
    --status)
        pr="${2:-}"; [ -n "$pr" ] || pr="$(ls -t "$LOGDIR"/pr-*.log 2>/dev/null | head -1 | sed -E 's/.*pr-([0-9]+)\.log/\1/')"
        [ -n "$pr" ] || { echo "no release yet"; exit 0; }
        echo "unit stackshot-release-$pr: $(systemctl --user is-active "stackshot-release-$pr.service" 2>/dev/null || echo finished)"
        tail -n 15 "$LOGDIR/pr-$pr.log" 2>/dev/null; exit 0 ;;
    --run-group) shift; [ $# -ge 2 ] && ! printf '%s\n' "$@" | grep -qvE '^[0-9]+$' && [ -z "$(printf '%s\n' "$@" | sort | uniq -d)" ] || { echo "usage: release.sh --run-group <pr> <pr> [<pr>...]  (two or more different PR numbers)" >&2; exit 2; }; run_group "$@"; exit $? ;;   # the steps themselves (what the group's unit runs; THE MERGE QUEUE, ON)
    --group)   # mode on: the PRs the release queue holds, released as one group through the merge queue (what the queue starts when two or more wait). Starts the unit and returns at once, as `release.sh N` does
        shift; [ $# -ge 2 ] && ! printf '%s\n' "$@" | grep -qvE '^[0-9]+$' && [ -z "$(printf '%s\n' "$@" | sort | uniq -d)" ] || { echo "usage: release.sh --group <pr> <pr> [<pr>...]  (two or more different PR numbers; needs the merge queue in mode on)" >&2; exit 2; }
        [ $# -le "$MQ_HANDOFF_MAX" ] || { echo "release.sh --group: $# PRs are more than one hand-off ($MQ_HANDOFF_MAX at most, release.sh's own number): hand over $MQ_HANDOFF_MAX at most" >&2; exit 2; }
        if systemctl --user is-active --quiet "stackshot-release-$1.service" 2>/dev/null; then echo "release of PR #$1 is already running (release.sh --status $1)"; exit 1; fi
        systemd-run --user --quiet --collect --unit "stackshot-release-$1" -p WorkingDirectory="$HERE" \
            --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --run-group "$@" \
            || { echo "could not start stackshot-release-$1 (systemd-run failed): nothing was started" >&2; exit 1; }
        echo "started stackshot-release-$1: hands the PRs $* to the merge queue as one group, deploys what it merges once, and reports to projects/example · log $LOGDIR/group-$1.log (and each PR's pr-N.log)"; exit 0 ;;
    queue) shift; queue_cmd "$@"; exit $? ;;
    --mq-compare) mq_compare "${2:-}" "${3:-}"; exit $? ;;   # the unit a shadow release starts when it ends (THE MERGE QUEUE, SHADOW)
    ''|-h|--help) sed -n '2,/^set -uo pipefail/{/^set -uo pipefail/!p}' "$0"; exit 2 ;;   # the header comment, up to the first line of code
    *)
        pr="$1"; [[ "$pr" =~ ^[0-9]+$ ]] && [[ "${2:-}" =~ ^(|--recycle|--no-recycle)$ ]] && [ $# -le 2 ] || { echo "usage: release.sh <pr> [--recycle | --no-recycle] | --status [pr] | --run <pr> [--recycle | --no-recycle] | --pick <pr> | --pick-files <file>... | queue N [N...] | queue --list | queue --drop N | queue --resume | --group N N..." >&2; sed -n '/^# How to run it/,/^#   - Auto mode/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
        if systemctl --user is-active --quiet "stackshot-release-$pr.service" 2>/dev/null; then echo "release of PR #$pr is already running (release.sh --status $pr)"; exit 1; fi
        systemd-run --user --quiet --collect --unit "stackshot-release-$pr" -p WorkingDirectory="$HERE" \
            --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --run "$pr" ${2:+"$2"} \
            || { echo "could not start stackshot-release-$pr (systemd-run failed): nothing was started" >&2; exit 1; }     # uv, gh, python3 and the fleet tool as the shell sees them; a start that failed is said so (the queue skips it)
        echo "started stackshot-release-$pr: merges PR #$pr when its checks pass, deploys, picks what the sessions need (${2:-from the files it changed}), and reports to projects/example · log $LOGDIR/pr-$pr.log"; exit 0 ;;
esac
exit 0
