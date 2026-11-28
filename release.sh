#!/usr/bin/env bash
# release.sh — enqueue a PR in GitHub's merge queue (or, when the host file says mode on, hand it to salamander's merge queue, `salamander mq`) and deploy what the queue merges, detached: the builder (example-engineer) starts it and leaves, and the result comes back as one
# stackshot message to the project. Runs on the server box, in the production checkout.
#
# GitHub tests and merges; release.sh enqueues, deploys main and watches main's full run. The branch ruleset on main requires the merge queue (tests.yml runs on `merge_group`): GitHub
# builds each entry on main's tip and on the entries ahead of it, runs the checks on exactly that tree, and fast-forwards main to it, so what it merges is what was tested. A failing
# entry is removed and the ones behind it are rebuilt without it. Nothing pushes to main directly while the ruleset is active.
#
# How to run it (what a session does):
#   - Run one plain `release.sh N` per command. It starts its own unit and returns at once.
#   - Wait for its log (`<state>/releases/pr-N.log`, a line with ` done: ` or ` FAILED `) in a run_in_background shell with `timeout`.
#   - Never chain waiters that start the next release when the previous log says done: a failed step stops every later one with no report.
#   - For several PRs, queue them: `release.sh queue N [N...]`. Every queued release starts at once (at most 4 at a time, release.sh's own number; the next waiting PR starts when one is deployed),
#     so the PRs reach GitHub's merge queue together and are tested together; the deploy lock serializes the deploys. A queued PR that fails before its merge (its checks, a conflict, removed from the merge queue)
#     is reported and skipped, and a failed main run for a merged one pauses the queue (THE RELEASE QUEUE below).
#   - With the salamander merge queue in mode on (host file; THE TWO MERGE QUEUES below) the release queue starts one thing at a time: two or more queued PRs (at most 4 at a time, release.sh's own number) are released together by that queue
#     (`release.sh --group N N...`, which the release queue starts itself): one deploy and one `done:` line per PR; one queued PR is released alone. GitHub's queue is the default (no host file, or mode off).
#   - A PR whose branch is behind main is not touched: the merge queue builds it on main's tip. A PR that conflicts with main only on the generated tests/tool_text.snapshot.json is mended (2a below).
#     Watch a release with `release.sh --status N`: the log's newest line says what is waited for.
#   - With [release] deploy_ssh set, a release copies its last-good record to the server box itself; after a copy that failed, `release.sh --copy-record` does it now (4c-record). It also tells that box that it runs (4c-running).
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
#   ./release.sh --group N N...   mode on only (THE TWO MERGE QUEUES below): two or more different PRs (at most 4) released as one group through salamander's merge queue; starts the unit stackshot-release-<first> and returns at once. The release queue starts it itself when two or more PRs wait
#   ./release.sh queue N [N...]   add PRs to the release queue (<paths.state>/releases/queue), in order; a PR queued already stays where it is. A PR with a failing, cancelled or timed-out check row is refused (exit 1, the rows printed, nothing queued), and so is one whose rows cannot be read. Every queued release that is not running starts at once, up to 4 running at a time (one is running from its start until it is
#                                 deployed, the point after which it only waits on main's run; it stays in the queue file until then, so a killed one is still listed and --resume starts it again); each queued release that reaches "deployed" leaves the queue and starts the next waiting one. A queued PR that fails before its merge (its checks fail, it conflicts, it is closed, GitHub removes it from the merge queue, a lock is not had) is reported as any failure
#                                 is, and skipped: the queue goes on. A failure after the merge (main's run failing for it, merged and not deployed or rolled back; its deploy failing) of a release the queue started pauses the queue: no new release starts, a release the queue had started already but not enqueued stops at
#                                 "queue paused" and stays first in the queue, the PRs a rollback took out stay merged on main and are named in the report (the next release's deploy carries them), the rollback and the red report run as always. A plain
#                                 `release.sh N` that fails pauses nothing, and neither does a main run that could not be read. A queued release picks what the sessions need from its PR's files, as any release does.
#   ./release.sh queue --list     the queued PRs in order, each running, waiting or started but not running, whether the queue is paused and why
#   ./release.sh queue --drop N   take PR N out of the queue (a release already started is not stopped, and a PR already in GitHub's merge queue stays there: the CLI cannot remove it)
#   ./release.sh queue --resume   after a pause, once main is fixed: the queue goes on (waiting PRs start up to the cap, and a queued release that was started but is no longer running starts again)
#   ./release.sh hold --minutes N --by NAME --why TEXT
#                                 hold every release's deploy for N minutes (1 to 120), for work on the server that a deploy's restarts must not fall into (THE HOLD below). Waits for the deploy under way
#                                 first, so when it returns none is running. The same NAME again replaces its own hold (a new end, a new reason); another NAME is refused while one stands
#   ./release.sh hold --status    who holds releases, until when and why, or that nothing does
#   ./release.sh hold --end       end the hold now: the releases waiting for it go on
#   ./release.sh --run <pr> [--recycle | --no-recycle]
#                                 the steps themselves (what the unit runs):
#                                 1. the PR is open and mergeable;
#                                 1a. THE CODEX REVIEW (a two-week trial, codex_review_start): for a PR that is still open (a rerun on a merged PR skips it), right before the wait for the checks, `salamander codex-review <owner/repo> <pr>` is started in a
#                                 transient user unit of its own (systemd-run, salamander-codex-review-<pr>-<epoch>, its output appended to <state>/releases/codex-review-<pr>.log), so it outlives this release; with no user manager it is started
#                                 detached with setsid nohup instead, which stays in this release's unit (cgroup), so there a stop or the time limit of the release ends it too. When the systemd-run call itself times out (20 s) the unit may have started, so the detached start follows too (a second start waits on salamander's per-PR lock, then finds the done marker and posts nothing, unless the first review failed without one). It is never waited for; it has a model other than ours review the PR read-only and post the result on it as a comment. It cannot change this release's result or timing: the
#                                 call's own failure, a hang or a non-zero exit are nobody's here, and the log gets one line saying how it was started or why not (SALA_CODEX_REVIEW off, false, no or 0, any case, surrounding whitespace ignored, in this release's environment, [release]
#                                 codex_review = false, salamander not on PATH). The unit gets PATH, XDG_STATE_HOME, SALA_CONFIG, SALA_CODEX_REVIEW and the other SALA_CODEX_* variables that are set in this release's environment. A group release
#                                 (THE TWO MERGE QUEUES, run_group) does not start it;
#                                 2. its checks pass (waits up to 50 min for a pending or queued one: the CI runners take one job at a time);
#                                    The checks pass only with the tests job ($TESTS_CHECK, the required check) among them: GitHub refuses to enqueue a PR without it, whatever the other checks say.
#                                    A workflow run of the PR that stays `queued` for more than 30 min (RELEASE_ORPHAN_QUEUED, seconds) with NO jobs (`gh run view <id> --json jobs`) never starts and cannot be cancelled or rerun (GitHub bug), and it has no
#                                    check runs: the required check stays missing. The PR wait replaces such a PR check run, once per step, by `gh pr close` then `gh pr reopen` (the head stays, no commit); the wait clock restarts once, the
#                                    log line names the run(s). The merge queue wait does not replace a merge_group run: one of the current group's fails the release at once (merge queue), naming it and saying what to do by hand, and the PR
#                                    stays queued. Taking the PR out of the queue and putting it back would need proof that the removal was this release's own, and GitHub cannot give it (every gh write here is the same account), so a PR
#                                    someone else took out could be put back, merged and deployed. Only the NEWEST run of each workflow counts (of the PR head's pull_request runs; of this PR's merge_group runs since its queue entry (GitHub's
#                                    enqueuedAt: a rerun finds an entry an earlier release made), the newest being the current group's): an older run is superseded, and a run replaced once never counts again; a run's age is its attempt's
#                                    (startedAt). It counts only while it blocks (the wait has not passed) and nothing else is going: a newest run in progress, or queued for less than the cap, or one with a job, counts for nothing (the close
#                                    would cancel it). A run that is an orphan only after the replacement fails the release naming its run id. Just before the close the PR is read again: it must be OPEN on the head waited on and not handed
#                                    to the salamander merge queue (otherwise the release fails and nothing is closed). The release reopens only a close GitHub answered for its own call (gh pr close returned, not saying the PR was closed
#                                    already), however the release ends after that (the exit trap). A close call that errored or never answered, and a PR a rerun finds CLOSED, are never reopened by a release: GitHub does not say whose call
#                                    closed a PR, and the message says how to reopen it by hand. A gh error replaces nothing. What is not covered: docs/development.md.
#                                 2a. A CONFLICT THAT IS ONLY THE GENERATED TOOL-TEXT SNAPSHOT is mended instead of failing (regen_snapshot, tools/snapshot_regen.py): two PRs that both change tool text
#                                 conflict on tests/tool_text.snapshot.json and on nothing else, and the by-hand fix is always the same. When the first look at the PR says CONFLICTING, or GitHub removed the PR
#                                 from the merge queue and the PR conflicts with main now, this fetches main and the PR head (git only: no GitHub call), merges main into the head in a temporary worktree of its own
#                                 (removed on every way out), and, only if the snapshot is the SOLE conflicted path, takes main's snapshot, runs `python3 tools/tool_text.py update` then `check`, commits the merge and pushes it to the PR
#                                 branch (a plain push: a branch its author pushed to meanwhile is refused, never forced). The log says so in one line, the PR head is read until it moves, the PR's tests on the new head are waited for
#                                 (the `suites` check must be reported and completed on that very commit) and the PR is enqueued again. Any other conflicted path, a clean local merge, a failed update or check, a refused push, a cross-repository PR
#                                 or no helper: the release fails, the reason in one more log line. At most RELEASE_REGEN_MAX (1) time in a release, so it cannot loop;
#                                 3. ENQUEUE: one GraphQL read decides the way, `repository.mergeQueue(branch:"main")`. Present (the ruleset's queue is on): the PR goes in with the mutation `enqueuePullRequest(pullRequestId, expectedHeadOid)`,
#                                 pinned to the head the checks ran on, so a push after the checks cannot ride in; its required checks have passed (step 2). `gh pr merge` is not used with the queue on: it asks for auto-merge, which this repository does not
#                                 allow (cli/cli#13398), and auto-merge stays off. Absent (the ruleset is off, the way back): `gh pr merge --merge --admin --match-head-commit <head>` (no --delete-branch) merges at once, and the log says so. When GitHub's server fails the call
#                                 (a 5xx, a GraphQL error of type INTERNAL, "something went wrong", a timeout or a reset), the PR's state is read first (queued or merged carries on: the call may have gone through), else the call is made again, up to 4 attempts with waits of 5, 15 and 45 s
#                                 (RELEASE_ENQUEUE_WAITS, a space-separated list, overrides the waits), one log line per retry. A refusal (a 4xx, "not mergeable", "already in the queue", a conflict, a failed required check) is never retried. After the last attempt, and for a refusal, the PR's state is read again for up to about 50 s: queued or merged carries on, anything else fails "merge" with the error of the last call. An answer that cannot be read fails "merge";
#                                 3a. WAIT FOR THE MERGE: GraphQL `pullRequest { state mergeCommit { oid } mergeQueueEntry { state position } }`, read every POLL_QUEUE s (60) for up to QUEUE_WAIT (RELEASE_QUEUE_WAIT, 3 h), the log saying where the PR is in the queue every 5 min (one read is
#                                 one GitHub call from the hour's shared budget, so it is not polled faster; the first looks after the call come every 10 s until the entry shows, QUEUE_GRACE, 3 min). MERGED: the merge commit GitHub made is the one to deploy. A PR that was in the queue and is not any more, and is not merged
#                                 (GitHub confirms it on a second read 10 s later, and three more reads 10 s apart find it still not MERGED): the reason GitHub gave is read from the timeline (`RemovedFromMergeQueueEvent` dated at or after the enqueue call: an older event is an earlier enqueue's),
#                                 and the release fails "merge queue" with it before any deploy, the queue of releases going on with the others (a skip: the PR is not merged). A PR that shows MERGED on any of those reads is merged: the release goes on.
#                                 Only a removal for a conflict with main that is only the snapshot (2a) is mended and enqueued again. A PR closed meanwhile fails "pr state"; one still in the queue after QUEUE_WAIT fails "merge queue" (it may merge later: rerun release.sh N to carry on from the merge; the next release's deploy carries it too).
#                                 A RERUN ON A MERGED PR (an earlier release was killed, or gave up after QUEUE_WAIT, and GitHub merged the PR later) carries on from the merge: it reads the merge commit and goes to the deploy gate, the deploy, main's run, the last-good record and the report.
#                                 Nothing says such a merge came through the queue, so the gate is closed for it (4b) and the deploy waits for main's tests (4d).
#                                 Then the head branch: the open PRs based on it (`gh pr list --base`) are retargeted to main (`gh pr edit --base main`, one log line each), and the branch is
#                                 deleted best-effort; a PR that cannot be listed or retargeted keeps the branch and the log says why (GitHub closes a PR whose base is deleted), the release goes on;
#                                 4. the deploy lock: the deploy runs under an exclusive flock on <paths.state>/releases/deploy.lock, waited for up to 15 min (DEPLOY_LOCK_WAIT, seconds); past that the release fails "deploy lock":
#                                 merged, not deployed (./deploy.sh by hand once it is free). Two releases never deploy at once, and the waits for GitHub happen before and outside the lock, so no release waits for another one's CI. The lock is released when
#                                 deploy.sh returns; fd 9 is closed for every child (a service a deploy leaves behind never inherits it). Only release.sh takes it: a deploy.sh run by hand does not;
#                                 4a. ALREADY LIVE: when the live checkout contains the merge (a release that merged after this one's merge deployed past it, or deploy.sh was run by hand) there is nothing to deploy: the log says so, the session pick,
#                                 the report and main's run for the merge follow as after a deploy, and the report says "already live";
#                                 4b. DEPLOY GATE (deploy_gate): GitHub's merge queue ran every suite, plainly, for the merge group on the tree it made (a merge_group run: tests.yml's shards, then the check that every suite ran once and none failed), so the merge deploys at once only when the queue made it
#                                 (the enqueue went through the mutation: with the ruleset off the plain merge call merged it, and a rerun on a merged PR does not know, so both wait for main's tests, 4d) and what lies between the live checkout and the merge is not known to be bad:
#                                 (a) the live checkout is an ancestor of the merge (deploy.sh fast-forwards; commits between them are merges of the queue or docs-only merges), (b) there is a last-good commit to roll back to ($LOGDIR/last-good, below) that is in the live history, and (c) no commit after it
#                                 up to main's tip (a later member of the same merge group included) has a FAILED run on main (read from GitHub's list of runs, page after page, up to 10 of 100, until a run at or before the last-good commit; empty, crashed or never reaching it: unreadable; so is a run in the range cancelled after its job started,
#                                 while one cancelled while queued was replaced and does not count); a pending run does not count: back-to-back releases stay fast, and if the first one's run fails both are rolled back. A pending-verify record of a killed release (below) that is not read yet
#                                 closes the gate too, and so does a paused release queue (a rollback, or a failed deploy, of a release the queue started pauses it). The record is read, compared and written under flock on last-good.lock; one it cannot read (not a sha, a commit this checkout does not know) is never overwritten, it is told to the keeper and the gate stays closed. First use: the live HEAD, when its run on main passed.
#                                 When the gate is closed (a failed or unreadable run since the last good commit, as after a rollback, until a pass on a newer commit records itself) the release waits for main's tests before it deploys (4d), the reason in the log.
#                                 A release the queue started that finds the queue paused when it gets the deploy lock (a rollback paused it while the release waited: a late member of the merge group) does not deploy: it fails "queue paused", merged and not deployed, and leaves the queue; the next release's deploy carries it;
#                                 4c. ./deploy.sh pinned to the merge commit (DEPLOY_TO; units, restarts, /healthz), the lock let go, the session pick (its recycle or notice) and the one report (green) follow the deploy, "main's full run follows"; then main's run for the merge
#                                 commit is waited for (main_green post: a run on it or on a later commit that contains it, see "Main's tests" below), outside the lock. Just before deploy.sh runs (production changes at its fast-forward, and the restarts and healthz take up to 180 s) a pending-verify
#                                 record (commit, PR, time) goes under <paths.state>/releases/pending-verify/, its flock held by this process; a failed deploy clears it with its red report, and it is removed when the watch concludes. A release that is killed in between leaves it with the
#                                 lock free, and the next release to start (before anything else) reads that commit's main run once: pass -> last-good; fail -> the rollback and red report a live watch would make, for that PR (the record stays unless
#                                 the rollback reached a verdict: a lock timeout keeps it); still pending, only cancelled runs, or no run found / GitHub unreadable (never a verdict) -> kept, and the gate stays closed until it is read (after two hours: unknown, a red report).
#                                 Records are taken oldest deploy first. Main's run for the merge commit itself:
#                                   pass: "main's tests passed on <sha>" in the log, the commit goes to last-good, the check that it is still
#                                   in the live checkout and the record done under the deploy lock (a rollback cannot land between them); a note on the run (a step that failed
#                                   besides the suites step; the selection audit and the measured-only failures are notes of suitemap-refresh.yml's runs now, not of main's) goes to the keeper as a second message;
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
#                                 4d. MAIN'S TESTS FIRST (only when the deploy gate is closed, or the live checkout cannot fast-forward to the merge cleanly): a PR runs only the suites its change reaches, so the deploy waits for a run on main that covers the PR's merge
#                                 commit M, where every suite runs: a run on M or on a later commit that contains it (several PRs merged close together: a run cancelled by a newer push is not a failure, and the run on a later commit decides); up to WAIT_MAIN
#                                 (90 min by default, for a slow run on a loaded host) counted from when that run starts, and 3 h at most from the merge; its suites failing stops here, merged and not deployed (main_green below, the rule in full).
#                                 The wait looks at main's runs every POLL_MAIN s (60) and the reads are shared between the releases on the box for GH_TTL s (45), so six releases waiting on one run cost what one does. The deploy lock is let go for that
#                                 wait and taken again for the deploy, so a release waiting on main never holds another one's deploy (a lock still held after 15 min then fails "deploy lock": merged, not deployed). Then ./deploy.sh pinned to the commit main's
#                                 tests passed on (DEPLOY_TO: the newest commit that contains M whose run passed, never a tip with no passing run);
#                                 4c-ssh. WHERE deploy.sh RUNS (deploy_run): [release] deploy_ssh unset (the default) = in this checkout, as above. Set to a host (the server runs on another box than release.sh): the deploy, and the rollback, run
#                                 `ssh -o BatchMode=yes -o ConnectTimeout=15 <host> 'cd ~/stackshot && DEPLOY_TO=<sha> ./deploy.sh'` instead (a rollback inside `flock <that host's deploy lock> env DEPLOY_ROLLBACK=1 ...`, since deploy.sh wants the lock held where it runs),
#                                 its output in the log and its exit status the deploy's (an ssh that fails is a failed deploy). Then this checkout, which the gate, the live check and the rollback read as the live one, follows (follow_local): git merge --ff-only to the
#                                 deployed commit (git reset --keep for a rollback), and stackshot-puller.service is restarted when the move touched the puller's files; stackshot.service and the other units are never started here. A checkout with local
#                                 changes, or one that cannot move, is a failed release (the server is live at the commit, this checkout is not): the queue is paused and the red report says so, and `release.sh queue --resume` goes on once the checkout is clean
#                                 (a rollback that this checkout could not follow keeps its own red report, with that line added);
#                                 4c-record. THE SERVER BOX'S COPY OF THE LAST-GOOD RECORD (record_sync, only with [release] deploy_ssh): the server runs on that host and reads ITS OWN <state>/releases/last-good, so the record made here is copied
#                                 there over the same ssh: before step 6 asks the server (so after the deploy that put the commit there) and when a release or a group release ends, however it ends (a rollback, a failed deploy and a failed check
#                                 included). The copy is whatever this record holds at that moment, read under $LAST_GOOD.sync.lock so a later copy never carries an older value: a commit record_good wrote, so one whose run on main passed. The host
#                                 writes it only for a commit its checkout knows (it fetches main once when it does not: a record can be ahead of the deploy), and never over a later one: under its flock on its own last-good.lock, a record there that
#                                 already holds this commit and more stays, said in the log (to move that box's record back, delete the file there). The whole ssh is cut after RELEASE_RECORD_TIMEOUT s (90), the command there 20 s before that. A copy that fails is a log line
#                                 and one message to report_to, never a failed release; every later copy tries again, and `release.sh --copy-record` does it by hand. Unset (one box): no copy, no ssh, no lock file;
#                                 4c-running. THE SERVER BOX IS TOLD THAT THE RELEASE RUNS (running_start, running_end, only with [release] deploy_ssh): the server holds a step as busy and labels an item Queued for release while a release runs, which on
#                                 one box it reads from this unit and its log. Over the same ssh a release (a group release: under its lead, as its unit is named) sends an entry when it starts and every RELEASE_RUNNING_BEAT s (60), with the end of
#                                 its log and that log's age, and one marked ended as it exits (core/release_running.py). An entry counts for 300 s there, so a release that died without a word holds nothing for long. Each send is cut after
#                                 RELEASE_RUNNING_LIMIT s (20), and the command there after that less the connect and 2 s. The sends before the end run beside the release and never delay it; a send that fails never fails it (a line in
#                                 <state>/releases/running-publish.log, said once; a last word that fails is a line in the release log). Unset (one box): no process, no ssh, no file;
#                                 4e. THE PICKER'S INDEX (suitemap_warm_start, `--warm`): right after a deploy (not after a release that found its merge already live), [release] suitemap_warm_cmd is started on the deployed
#                                 commit in a transient user unit of its own (stackshot-suitemap-warm-<sha>, output <state>/releases/suitemap-warm-<sha>.log) and never waited for: the unit runs `release.sh --warm <sha>`,
#                                 which makes a worktree of the commit, runs the command in it (one at a time, stopped after RELEASE_WARM_TIMEOUT, 1800 s) and removes the worktree. The command is the test runner's: it sends the
#                                 tree to the box that picks suites and runs `python3 tests/suitemap.py warm` there, so the index of main's new tip is built right after the merge and the first `select` after it loads it.
#                                 Nothing runs on this box but the command; nothing retries; unset: the log says so and the release goes on; a command that is missing, fails or hangs is a log line and never a failed release;
#                                 5. one message to [release] report_to (default projects/example): green or red, the PR, the commit, what was restarted, what the session
#                                 pick chose and from which files, the log path.
#                                 A green one goes with --release green (the turn rule's second build): the
#                                 server logs it, rules it merged as `stackshot (auto)`, comments on the items anchored to the PR
#                                 and leaves it on the routing page (a project the router is not live for: lists it in the keeper's
#                                 daily digest); a red one, or a green one whose recycle could not be asked for, whose notice command
#                                 failed or whose changed files could not be read, is delivered to the project, where the router rules it, as before. A note on main's run goes to the keeper as the second message
#                                 (or makes the report go to the keeper instead of green when main's tests came first, 4d).
#                                 6. once main's full run passed on the merge and it is recorded as the last good commit (after the watch of 4c; after the deploy of 4d; a pending-verify record read as passed), `client.py released --pr <url> --sha <merge>`.
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
# THE TWO MERGE QUEUES. A PR is merged by one of two queues, chosen per host by the host file ~/.config/mergequeue/<owner>__<repo>.toml (XDG_CONFIG_HOME honoured), key `mode = "off" | "shadow" | "on"`, read by mq_host_mode (and by
# `salamander mq status --repo <owner/repo>`). GitHub's merge queue is the default: no host file, mode off, shadow (a mode this script no longer runs) and a file that does not read all use it, steps 3 and 3a above. Mode `on` uses salamander's own
# merge queue (docs/mq.md in salamander; the repository's own rules are .github/mergequeue.toml, the check that must pass is `suites`, tests.yml's job on a `queue/**` push; branch prefix queue/main/); that is the way back to the salamander mq hand-off
# when GitHub's queue cannot be used. Neither is retired.
#   off (default): run() as described above: enqueuePullRequest, wait for the merge, deploy. The release queue starts every waiting PR at once (up to 4 running).
#   on:     the salamander merge queue merges, routed by COUNT of the PRs waiting in the release queue (THE TWO MERGE QUEUES, run_group, below): ONE PR waiting is released alone by run() (no call to `salamander mq`; mode on assumes the GitHub ruleset's queue on main is off, so enqueue_pr merges it
#           at once with the plain merge call (--admin), its other steps unchanged); TWO OR MORE (at most 4, MQ_HANDOFF_MAX) go to the queue together through `salamander mq add`/`wait` (one chain entry each, stacked and
#           tested at once) and are deployed once. The release queue starts ONE of these at a time in mode on (the queue's merge push and a deploy are serialized by the deploy lock); in mode off it starts up to 4 releases at once. The host file must also say
#           `deploy_lock = "<this script's deploy lock>"` (<state>/releases/deploy.lock): without it, or with another file, mode on is refused ("FAILED at mq mode", before the PR is touched), because that lock is what keeps the queue's merge push out of a
#           release's deploy. salamander's own `ON_OPEN` switch must be open as well (until then `salamander mq add` refuses mode on and a hand-off fails at "mq add" with its message, pausing the release queue).
# Not restored from before the GitHub queue: the shadow mode (a comparison unit, `--mq-compare`), the fast-ok ledger and the retest skip (the salamander group deploys through the same deploy gate as a GitHub-queue release).
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
# 3 no file, 4 stale, 5 unreadable; docs/ci-runs.md in salamander's checkout). Both CI waits of this script, the PR's checks (wait_pr_checks, step 2 and after a snapshot regeneration) and main's
# run for the merge (main_green, polled every POLL_MAIN s), first ask it (ci_going: `salamander ci-runs howardpark-ai/stackshot --sha <sha> --max-age 120`). When the file is fresh
# and lists a workflow run of that commit that has not completed (queued or in progress), the cycle makes NO GitHub call (no `gh pr checks`, no git fetch, no `gh run list`/`view`, no look for an orphaned run)
# and the wait goes on exactly as a pending check would make it; the log says so (a line at the start and every 5 min). Only the newest run of each workflow is looked at (an older one is superseded), and for
# the PR's checks a run queued for RELEASE_ORPHAN_QUEUED s is not taken as going: the file cannot show its jobs, so it may be an orphan, and the GitHub read decides (the orphan look, step 2). The file can only make a release WAIT, never pass or fail one,
# as in salamander's own release.sh: when the poller shows the run completed, when no run of the sha is listed (the file is a window of 30 runs, so a missing sha proves nothing and is never
# a failure), when the file is missing, stale or unreadable (exit 3, 4, 5, or any other), or when salamander is not on PATH, the cycle does the GitHub read it always did, and that read
# alone decides pass or fail. So a failing job is noticed when the poller shows the run completed (a minute or two after it fails), not the moment it fails. The main wait keeps
# only main's push runs of the merge commit (what run_state reads). A run the poller shows going counts for
# WAIT_MAIN as a run from run_state does (same run id). RELEASE_CIRUNS_MAX_AGE (120 s; 0 = never ask the poller) is its knob. The wait for the merge queue does not use it (the merge group's runs are not main's push runs): it reads GraphQL.
# The PR-checks wait that does ask GitHub looks every POLL_PR s (RELEASE_POLL_PR, 60; it was 20) through gh_cached, which shares the answer between the releases on the box for GH_TTL s (45)
# in <state>/releases/gh-cache like run_state's reads, keyed by the PR head too, so a wait without a fresh poller file costs a third of what it did.
#
# A change no test can exercise (docs, Markdown, comment-only lines, CI workflow runner/concurrency settings) does not come here: it merges with the config repo's docs-merge.sh (CONTRIBUTING.md, step 4).
# That script runs `gh pr merge --delete-branch`, which GitHub refuses on a branch with the merge queue on: docs-merge.sh has to change (it lives in another repo and is not changed here), and once the ruleset is active a docs PR goes through the queue as any PR does.
# A lock is an open file descriptor: git, gh, python3 and sleep run through functions that close 6-9 (and the client, the fleet tool and deploy.sh through
# redirects), so a child that outlives its command (git gc --auto) never holds the deploy lock or a pending-verify record's.
# release.sh is replaced by the deploy it runs: every arm of the dispatch at the end ends in an explicit exit, so bash never reads on from a stale offset.
# The message is sent with client.py (this box's token) after the deploy, when the server is back; a deploy whose server
# never answers again leaves the message unsent and the log tells the story (`--status`). Log: <paths.state>/releases/pr-<n>.log
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
# A lock is an open file descriptor, and a child that outlives its command (git gc --auto, a client, a service) keeps it open and so keeps the lock held. These commands
# are the ones that run while a lock is held, so each runs without the descriptors: 6 (a pending record being recovered), 7 (this release's pending record), 8 (last-good.lock), 9 (the deploy lock).
git() { command git "$@" 6>&- 7>&- 8>&- 9>&-; }
gh() { command gh "$@" 6>&- 7>&- 8>&- 9>&-; }
python3() { command python3 "$@" 6>&- 7>&- 8>&- 9>&-; }
sleep() { command sleep "$@" 6>&- 7>&- 8>&- 9>&-; }
REPO="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
LOGDIR="$(python3 stackshot/core/config.py state releases)"; mkdir -p "$LOGDIR"
REPORT_TO="$(python3 -c 'from stackshot.core import config; print(config.release_report_to())' 2>/dev/null)"; REPORT_TO="${REPORT_TO:-projects/example}"   # [release] report_to: where tell() sends the report of a release; the stand-in page when unset (or when this config.py predates the key)
DEPLOY_SSH="$(python3 -c 'from stackshot.core import config; print((getattr(config, "release_deploy_ssh", lambda: "")() or "").strip())' 2>/dev/null)" || DEPLOY_SSH=""   # [release] deploy_ssh: the host deploy.sh runs on, over ssh; "" (the default, a config.py without the key or one that does not run) = deploy here
WAIT_CHECKS="${RELEASE_WAIT_CHECKS:-3000}"   # seconds a PR's checks may stay pending (50 min); the knob lets the tests prove the give-up on a short cap, one scenario pins this default
ORPHAN_QUEUED="${RELEASE_ORPHAN_QUEUED:-1800}"   # seconds a workflow run may stay `queued` with an empty job list before the wait for the PR's checks replaces it, or the wait for the merge queue fails on it (30 min): GitHub can leave such a run for days, and it cannot be cancelled or rerun; the knob lets the tests prove it on a short cap, one scenario pins this default
orphan_done=" "   # ids of the runs already replaced in this release (a replaced run stays listed as queued: it never counts again, even while it is still the newest of its workflow)
orphan_prior=""   # a rerun's: the run ids of an earlier release's close call (its marker), passed over at this release's FIRST look only: once the PR was reopened GitHub can list them as the newest a moment longer, but
                  # that close may never have taken effect (a signal during the call, an error), and then the run is still the one that holds the wait: the next look, 5 min later, judges it as any run
orphan_erred=""   # set when this release's close call errored and GitHub still showed the PR open after it: a close it shows later may be that call's, and is not called someone else's
gq_since=""   # ghq_read: the second the PR's merge-queue entry was made (GitHub's enqueuedAt), "" with no entry
MERGEABLE_WAIT="${RELEASE_WAIT_MERGEABLE:-180}"   # seconds GitHub may say mergeable UNKNOWN (it recomputes after main moves) before the release gives up; read every 10 s
LOCK_FILE="${DEPLOY_LOCK_FILE:-$LOGDIR/deploy.lock}"      # next to the other release state; DEPLOY_LOCK_FILE / DEPLOY_LOCK_WAIT let the tests point elsewhere
LOCK_WAIT="${DEPLOY_LOCK_WAIT:-900}"                      # seconds: a deploy takes seconds to a few minutes (healthz waits up to 180 s), so 15 min is a stuck one
REGEN_MAX="${RELEASE_REGEN_MAX:-1}"                      # snapshot regenerations (2a) at most in one release: a second conflict after the first push may be a real one, and a loop is never the answer
SNAPSHOT_REGEN="${RELEASE_SNAPSHOT_REGEN:-$HERE/tools/snapshot_regen.py}"   # the helper that mends a conflict on tests/tool_text.snapshot.json alone; RELEASE_SNAPSHOT_REGEN lets the tests point at a stub
TESTS_CHECK="${RELEASE_TESTS_CHECK:-suites}"             # the PR check (the job of tests.yml, the required one) that must be reported before a verdict of the checks counts: a quick check alone must not read as a pass
QUEUE_WAIT="${RELEASE_QUEUE_WAIT:-10800}"   # seconds a PR may stay in GitHub's merge queue before the release gives up waiting (3 h: an entry's checks time out after 60 min, and a PR behind a failure is rebuilt and tested again)
POLL_QUEUE="${RELEASE_POLL_QUEUE:-60}"      # seconds between two reads of the PR's merge-queue state while wait_merged waits (every read is a GitHub call from one shared hourly budget)
QUEUE_GRACE="${RELEASE_QUEUE_GRACE:-180}"   # seconds after the enqueue call that GitHub may take to show the entry (eventually consistent); read every 10 s meanwhile, past it a PR that never showed is a failure
START_MAX=4                                 # queued releases running at once (release.sh queue): release.sh's own number, not a setting
WAIT_MAIN="${RELEASE_WAIT_MAIN:-5400}"   # seconds a covering run of main may be going (main_green: counted from when it starts, status in_progress). 90 min: main's full run, every suite plainly in six shards, can be slow on a loaded host, so 60 min (3600) let a slow run end a release
CAP_MAIN="${RELEASE_CAP_MAIN:-10800}"    # seconds from the merge, at most, that main_green waits for a run that covers it (3 h): a run queued behind others uses none of WAIT_MAIN, this keeps it from waiting forever
WARM_TIMEOUT="${RELEASE_WARM_TIMEOUT:-1800}"   # seconds [release] suitemap_warm_cmd may run (warm_run), and a second warm waits for the first: a build of the index is a minute on the box that does it
NOTICE_TIMEOUT="${RELEASE_NOTICE_TIMEOUT:-60}"   # seconds [fleet] notice_cmd may take (notice_send): past it the command is stopped and the notice counts as not sent, so the report loses its green flag and the next release starts
WAIT_STEPS="${RELEASE_WAIT_STEPS:-600}"  # seconds a run of main that is completed and green may stay without the conclusion of its "run every suite, measured" step (main_green: GitHub fills in the step results some time after the job reports completed, and release.sh once read a run in that gap and failed a green one). 10 min: the gap has been seconds to a minute; past it the step results never came and the run counts as green on its own conclusion (success), with a warning in the log and the report, never a rollback (a run that concluded failure fails at once). Counted on the clock from the first look that saw the gap; no extra GitHub call, the reads are the POLL_MAIN ones
POLL_MAIN="${RELEASE_POLL_MAIN:-60}"     # seconds between two looks at main's runs while main_green waits (a run can take a long time, and every look costs GitHub REST calls from one shared hourly budget; polling every 20 s with several releases waiting could spend it)
POLL_PR="${RELEASE_POLL_PR:-60}"         # seconds between two looks at a PR's checks while wait_pr_checks waits (every look is GitHub calls from one shared hourly budget; a PR's tests take a while). The read is shared between the releases on the box for GH_TTL s, like main's
GH_CACHE="$LOGDIR/gh-cache"              # main's run list and each run's view, kept for GH_TTL s and shared by every release on this box, so releases waiting on the same run ask GitHub once between them
GH_TTL="${RELEASE_GH_TTL:-45}"           # seconds an answer of those reads is reused (0 = never; the tests set it). A run the list says is completed and cancelled needs no run view at all
PENDING_DIR="$LOGDIR/pending-verify"      # one record per deploy whose main run is not read yet: a watch that is killed leaves it, the next release start finishes the job
PENDING_FILE=""; pv_block=""
LAST_GOOD="$LOGDIR/last-good"            # the newest commit whose run on main passed: what a failing main run rolls back to; one sha, written by record_good
RECORD_TIMEOUT="${RELEASE_RECORD_TIMEOUT:-90}"   # seconds the copy of $LAST_GOOD to [release] deploy_ssh may take (record_sync): the 15 s connect, a 30 s fetch over there and the write fit inside; past it the ssh is stopped and the copy counts as failed
SYNC_WHO=""; SYNC_TOLD=""                # record_sync's message: which release it names, and whether this process has sent it (one a process)
RUN_BEAT="${RELEASE_RUNNING_BEAT:-60}"      # [release] deploy_ssh: seconds between two entries a release sends the server box to say it runs (4c-running); an entry counts 300 s there (core/release_running.py EXPIRE_S)
RUN_LIMIT="${RELEASE_RUNNING_LIMIT:-20}"    # seconds one such send may take in all (a 10 s connect and at most 8 s of the command there fit inside); past it the ssh is stopped
RUN_PID=""; RUN_PR=""; RUN_LOG=""           # the process that sends them (running_start), and what it sends
HOLD_FILE="$LOGDIR/hold"                 # release.sh hold: the end (epoch seconds), who and why, one a line; while it stands no release deploys (THE HOLD)
HOLD_MAX_MIN=120                         # the longest one hold lasts: release.sh's own number, not a setting, so a forgotten hold cannot stall releases for long
POLL_HOLD="${RELEASE_POLL_HOLD:-10}"     # seconds between two looks at a hold a release waits for
QUEUE="$LOGDIR/queue"                    # the release queue (release.sh queue): PR numbers, one a line, in order; $QUEUE.lock its flock, $QUEUE.started the PRs whose release the queue started, $QUEUE.paused why it is paused, $QUEUE.log what it did
MQ_ON_ADD_TIMEOUT="${RELEASE_MQ_ON_ADD_TIMEOUT:-60}"   # seconds `salamander mq add` may take in mode on (it starts the queue's driver unit, and a refusal is an answer, so a slow one is an error: THE TWO MERGE QUEUES at the top)
MQ_WAIT_CAP="${RELEASE_MQ_WAIT_CAP:-18000}"       # seconds a group release waits for the salamander merge queue's verdicts (5 h: a queue run takes up to 100 min, and a PR behind a failure in the chain is tested again after the restack)
MQ_HANDOFF_MAX=4                                  # PRs handed to the salamander merge queue in one hand-off (mode on): release.sh's own number, not a setting of the rules file; the chain tests those entries at once and the rest stay in release.sh's queue for the next hand-off
MQ_SLICE="${RELEASE_MQ_SLICE:-300}"                # seconds one `salamander mq wait` of a group release may block before the release looks at whether the queue is paused or blocked (mode on)
MQ_HANDED="$LOGDIR/mq-on"                         # mode on: one marker file per PR handed to the salamander merge queue (pr-N), so a release of one PR can refuse a PR the queue holds without calling the queue
CIRUNS_MAX_AGE="${RELEASE_CIRUNS_MAX_AGE:-120}"   # how old salamander's CI-run poller file may be and still be believed about a run that is going (salamander ci-runs --max-age); 0 = never ask it
# ci_going <sha> <any|main>: 0, and one line on stdout "<run id> <running|queued> <what it saw>", when salamander's CI-run poller (`salamander ci-runs`, read from a file: no GitHub call)
# is fresh and lists a workflow run of <sha> that has not completed. `main` keeps the push runs of main only (what run_state reads); `any` every run of the commit (a PR's checks).
# Only the newest run of each workflow (and event) counts: an older one is superseded (a replaced orphan stays listed as queued for ever). For `any`, a run queued for ORPHAN_QUEUED s
# does not count either: the file cannot show its jobs, so it may be an orphan, which only the GitHub read and the orphan look can tell.
# Every other case returns 1 and the caller asks GitHub, which alone decides pass or fail: salamander not on PATH, exit 3 (no file for this repo), 4 (stale), 5 (unreadable), 2 or any
# other, a run of the sha completed or not listed at all (the file is a window of the repo's 30 newest runs, so a missing sha proves nothing), output that is not JSON.
ci_going() {
    local sha="${1:-}" kind="${2:-any}" out now
    [ "$CIRUNS_MAX_AGE" -gt 0 ] 2>/dev/null || return 1
    command -v salamander >/dev/null 2>&1 || return 1
    [[ "$sha" =~ ^[0-9a-f]{7,64}$ ]] || return 1
    now="$(date +%s)"
    out="$(salamander ci-runs "$REPO" --sha "$sha" --max-age "$CIRUNS_MAX_AGE" 2>/dev/null 6>&- 7>&- 8>&- 9>&-)" || return 1
    KIND="$kind" SHA="$sha" NOW="$now" CAP="$ORPHAN_QUEUED" python3 -c '
import calendar, json, os, sys, time
try:
    d = json.loads(sys.stdin.read()); sha = os.environ["SHA"]
    mine = [r for r in d["runs"] if (r.get("head_sha") or "").startswith(sha) or sha.startswith(r.get("head_sha") or "-")]
    if os.environ["KIND"] == "main": mine = [r for r in mine if r.get("event") == "push"]
    new = {}
    for r in mine:
        k = (r.get("name"), r.get("event"))
        if k not in new or (r.get("created_at") or "", r.get("id") or 0) > (new[k].get("created_at") or "", new[k].get("id") or 0): new[k] = r
    def old_queued(r):
        return os.environ["KIND"] == "any" and r.get("status") == "queued" and bool(r.get("created_at")) and int(os.environ["NOW"]) - calendar.timegm(time.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")) >= int(os.environ["CAP"])
    going = [r for r in new.values() if r.get("status") != "completed" and not old_queued(r)]
    if not going: sys.exit(1)
    r = going[0]
    print("%s %s %d of %d run(s) of %s not completed (poller file %ds old)" % (r.get("id"), "running" if r.get("status") == "in_progress" else "queued", len(going), len(new), sha[:7], max(0, int(time.time() - float(d["updated"])))))
except Exception:
    sys.exit(1)' <<< "$out"
}

say() { echo "$(date -u +%FT%TZ) $*"; }
tell() {  # one message to the project; never fails the run. Extra arguments go to client.py (--release green --pr <url>)
    local text="$1"; shift
    python3 stackshot/fleet/client.py message "$REPORT_TO" "$text" --sender release "$@" >/dev/null 2>&1 9>&- 7>&- 6>&- || say "message not sent: $text"
}
released() {  # $1 = a PR, $2 = its merge commit: main's full run passed on it and it is in $LAST_GOOD. The server settles the open items with a release step
               # for the PR (client.py released; refused unless the merge is in last-good and HEAD): an item whose only open steps are that release is closed, done,
               # with no session turn; one with another open step has the release step ticked and its mover told once, a real notice (the green report is log-only).
               # Never fails the run; what it did, and why an item was left alone, is a log line
    local out
    record_sync   # deploy_ssh: the server reads its own copy of the record, so it has to have it before it is asked
    if out="$(python3 stackshot/fleet/client.py released --pr "https://github.com/$REPO/pull/$1" --sha "$2" 2>&1 9>&- 8>&- 7>&- 6>&-)"; then say "items of PR #$1: $(echo "$out" | sed 's/^stackshot: //' | paste -sd ';' -)"
    else say "the items of PR #$1 were not settled: $(echo "$out" | tail -1 | sed 's/^stackshot: //')"; fi
    return 0
}
codex_review_start() {  # $1 = a PR that was just read as open: start `salamander codex-review <repo> <pr>` (a read-only review by another model, posted on the PR as a comment) and say in one log line how it was started or why not.
                        # A trial that must never touch the release: nothing waits for it, its output goes to <state>/releases/codex-review-<pr>.log (never into this release's), and every way of failing here (a missing tool, an unwritable log,
                        # a spawn that errors or hangs: the systemd-run call is cut at 20 s) is swallowed, so this function returns 0 whatever happens. It gets a transient user unit of its own, because this release runs in one and systemd
                        # ends a unit's whole cgroup when its main process exits, which would cut a review that outlives the release; the unit has none of the release's environment but what is passed with --setenv. With no user manager
                        # (systemd-run fails) it is started with setsid nohup instead, holding none of the locks (fds 4 to 9) nor the pipe to the log's tee (fd 3 where bash puts it): setsid gives it a session of its own, but it stays in this unit's
                        # cgroup, so there a stop or the time limit of the release ends the review with it (the one path where it does not outlive the release). A systemd-run call that timed out (status 124, or 137 when it needed the KILL
                        # after the 2 s grace) may have started the unit, and with a wedged user bus it may never submit one: so the setsid start follows there too, as for a plain failure, and the log line says both may run. A second start
                        # is harmless: salamander's codex-review takes one flock per PR and keeps a done marker per repo, PR and commit, so it waits, then finds the marker and posts nothing, unless the first review failed without one (a refusal, an empty answer, a usage-limit message, a timeout or a non-zero exit leaves none, so the second runs its own review and can post it). Off by SALA_CODEX_REVIEW (off,
                        # false, no or 0, any case, surrounding whitespace ignored: the words [release] codex_review takes) in this release's environment, or [release] codex_review = false; also skipped when salamander is not on PATH
    local pr="$1" why="" cfg="" sal="" v="" unit="" rc=0 crlog="$LOGDIR/codex-review-$1.log" sw="${SALA_CODEX_REVIEW:-}"; local -a senv=()
    sw="${sw#"${sw%%[![:space:]]*}"}"; sw="${sw%"${sw##*[![:space:]]}"}"   # trimmed, as the config key is (str(v).strip())
    case "$sw" in
        [Oo][Ff][Ff]|[Ff][Aa][Ll][Ss][Ee]|[Nn][Oo]|0) why="SALA_CODEX_REVIEW=$sw" ;;
    esac
    if [ -z "$why" ]; then
        sal="$(command -v salamander 2>/dev/null)" || sal=""
        if [ -z "$sal" ]; then why="salamander is not on PATH"
        else
            cfg="$(python3 -c 'from stackshot.core import config; print("on" if getattr(config, "release_codex_review", lambda: True)() else "off")' 2>/dev/null)" || cfg=""   # a config.py without the key, or one that does not run, reads as on
            [ "$cfg" != off ] || why="[release] codex_review is off"
        fi
    fi
    if [ -n "$why" ]; then say "codex review of PR #$pr not started: $why"; return 0; fi
    unit="salamander-codex-review-$pr-$(date +%s)"
    for v in PATH XDG_STATE_HOME SALA_CONFIG SALA_CODEX_REVIEW SALA_CODEX_BIN SALA_CODEX_HOME SALA_CODEX_MAX_DIFF SALA_CODEX_TIMEOUT SALA_CODEX_PUBLIC_SCAN SALA_CODEX_SCAN_TIMEOUT; do
        [ -n "${!v+x}" ] && senv+=("--setenv=$v=${!v}")   # what salamander reads from its environment; the unit has only these
    done
    timeout -k 2 20 systemd-run --user --quiet --collect --unit "$unit" -p "StandardOutput=append:$crlog" -p "StandardError=append:$crlog" "${senv[@]}" \
        "$sal" codex-review "$REPO" "$pr" </dev/null >/dev/null 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- || rc=$?
    if [ "$rc" = 0 ]; then
        say "codex review of PR #$pr started in its own unit $unit (output $crlog); the release does not wait for it"
    elif ( setsid nohup "$sal" codex-review "$REPO" "$pr" </dev/null >>"$crlog" 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- & ) 2>/dev/null; then
        if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then   # timed out: the unit may have started too; a second start waits on salamander's per-PR lock, then finds the done marker and posts nothing, unless the first review failed without one
            say "codex review of PR #$pr: systemd-run did not answer within 20 s (status $rc), so unit $unit may have started; the review was also started detached (a second start waits on the per-PR lock, then finds the done marker and posts nothing, unless the first review failed without one; output $crlog); the detached one stays in the release's cgroup, so a stop of the release ends it, and the release does not wait for it"
        else
            say "codex review of PR #$pr started detached, no user unit (systemd-run failed; output $crlog); it stays in the release's cgroup, so a stop of the release ends it, and the release does not wait for it"
        fi
    elif [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
        say "codex review of PR #$pr: systemd-run did not answer within 20 s (status $rc), so unit $unit may have started; the detached start failed too"
    else
        say "codex review of PR #$pr not started: neither systemd-run nor setsid could start it"
    fi
    return 0
}
suitemap_warm_start() {  # $1 = the commit this release just deployed (the live checkout's HEAD): start [release] suitemap_warm_cmd on it (`release.sh --warm`, below) and say in one log line how, or why not.
                         # The suite picker's index of that commit is built where picks are made, so the first `tests/suitemap.py select` after a merge loads it (tests/suitemap.py warm). It is a courtesy that must
                         # never touch the release: nothing waits for it, its output goes to <state>/releases/suitemap-warm-<sha>.log, and every way of failing here (no command set, a spawn that errors or hangs: the
                         # systemd-run call is cut at 10 s) is swallowed, so this function returns 0 whatever happens. It runs in a transient user unit of its own, because this release runs in one and systemd ends a
                         # unit's whole cgroup when its main process exits; with no user manager (systemd-run fails) it is started with setsid nohup, holding none of the locks (fds 4 to 9), and then a stop of the
                         # release ends it with it. Nothing retries: a warm that failed is the next pick's own build, as it was before there was one. Never on this box's own CPU: the command is the test runner's
                         # (it sends the tree to the box that picks suites); this function and `--warm` start no test and no suitemap call themselves
    local sha="$1" unit="" wlog="$LOGDIR/suitemap-warm-${1:0:12}.log" rc=0 cmd0=""
    cmd0="$(python3 -c 'from stackshot.core import config; print((getattr(config, "release_suitemap_warm", lambda: [])() or [""])[0])' 2>/dev/null)" || cmd0=""   # a config.py without the key, or one that does not run, reads as none
    if [ -z "$cmd0" ]; then say "suitemap warm: no [release] suitemap_warm_cmd is set, nothing started"; return 0; fi
    [[ "$sha" =~ ^[0-9a-f]{7,64}$ ]] || { say "suitemap warm: no commit to build the index of: nothing started"; return 0; }
    unit="stackshot-suitemap-warm-${sha:0:12}"
    timeout -k 2 10 systemd-run --user --quiet --collect --unit "$unit" -p WorkingDirectory="$HERE" -p "StandardOutput=append:$wlog" -p "StandardError=append:$wlog" \
        --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --warm "$sha" </dev/null >/dev/null 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- || rc=$?
    if [ "$rc" = 0 ]; then
        say "suitemap warm: started $unit for ${sha:0:7} (output $wlog); the release does not wait for it"
    elif [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
        say "suitemap warm: systemd-run did not answer within 10 s (status $rc), so unit $unit may have started; not started again (output $wlog); the release does not wait for it"
    elif ( setsid nohup "$HERE/release.sh" --warm "$sha" </dev/null >>"$wlog" 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- & ) 2>/dev/null; then
        say "suitemap warm: systemd-run failed (status $rc); started detached, no user unit, for ${sha:0:7} (output $wlog); the release does not wait for it"
    else
        say "suitemap warm: not started for ${sha:0:7}: neither systemd-run nor setsid could start it"
    fi
    return 0
}
WARM_WT=""
warm_clean() {  # the checkout `--warm` made, removed on every way out
    [ -z "$WARM_WT" ] || { git -c core.hooksPath=/dev/null worktree remove --force "$WARM_WT/tree" >/dev/null 2>&1; rm -rf -- "$WARM_WT"; git worktree prune >/dev/null 2>&1; }
    return 0
}
warm_run() {  # `release.sh --warm <sha>` (what suitemap_warm_start's unit runs): [release] suitemap_warm_cmd, as the config gives it, run from a checkout of <sha> made for it (a worktree: no copy of the repository)
              # and removed after, one at a time (a second waits for the first for up to WARM_TIMEOUT s), stopped after WARM_TIMEOUT s. Always 0: what it says goes to the log, and nothing reads its status
    local sha="$1" rc=0; local -a cmd
    mapfile -t cmd < <(python3 -c 'from stackshot.core import config; print("\n".join(getattr(config, "release_suitemap_warm", lambda: [])()))' 2>/dev/null)
    if [ -z "${cmd[0]:-}" ]; then say "suitemap warm ${sha:0:7}: no [release] suitemap_warm_cmd is set"; return 0; fi
    if ! command -v "${cmd[0]}" >/dev/null 2>&1; then say "suitemap warm ${sha:0:7}: ${cmd[0]} is not on PATH: nothing run"; return 0; fi
    if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then say "suitemap warm ${sha:0:7}: that commit is not in this checkout: nothing run"; return 0; fi
    exec 8>"$LOGDIR/suitemap-warm.lock" 2>/dev/null || { say "suitemap warm ${sha:0:7}: the lock file cannot be opened: nothing run"; return 0; }
    flock -w "$WARM_TIMEOUT" 8 || { say "suitemap warm ${sha:0:7}: another warm still ran after ${WARM_TIMEOUT}s: skipped"; return 0; }
    WARM_WT="$(mktemp -d "$LOGDIR/suitemap-warm.XXXXXX")" || { WARM_WT=""; say "suitemap warm ${sha:0:7}: no scratch folder: nothing run"; return 0; }
    trap warm_clean EXIT
    if ! git -c core.hooksPath=/dev/null worktree add --quiet --detach "$WARM_WT/tree" "$sha" >/dev/null 2>&1; then say "suitemap warm ${sha:0:7}: the checkout could not be made: nothing run"; return 0; fi
    say "suitemap warm ${sha:0:7}: running ${cmd[*]} in a checkout of it"
    ( cd "$WARM_WT/tree" && exec timeout -k 10 "$WARM_TIMEOUT" "${cmd[@]}" </dev/null 6>&- 7>&- 8>&- 9>&- ); rc=$?
    case $rc in
        0) say "suitemap warm ${sha:0:7}: done" ;;
        124|137) say "suitemap warm ${sha:0:7}: stopped after ${WARM_TIMEOUT}s" ;;
        *) say "suitemap warm ${sha:0:7}: the command failed (status $rc): nothing was kept, the next pick builds its own index" ;;
    esac
    return 0
}
idle_recycle() {  # ask the fleet tool for a recycle once the box is idle: [fleet] recycle_when_idle, the reason appended; 1 when none is set or it failed
    local -a cmd
    mapfile -t cmd < <(python3 -c 'from stackshot.core import config; print("\n".join(config.recycle_when_idle()))' 2>/dev/null)
    [ "${#cmd[@]}" -gt 0 ] && [ -n "${cmd[0]}" ] && command -v "${cmd[0]}" >/dev/null 2>&1 && "${cmd[@]}" "$1" >/dev/null 2>&1 6>&- 7>&- 8>&- 9>&-
}
notice_send() {  # [fleet] notice_cmd with ONE argument appended: "<title> — <summary>", a newline or tab turned into a space and the whole cut to 400 characters
                 # (ending in "…" when cut), the most a fleet notice takes. 0 sent · 1 no command set · 2 the command failed or is not found
                 # · 3 it did not finish within NOTICE_TIMEOUT seconds (it is stopped: a hung command must not hold the report and the queue's next release)
    local -a cmd; local nrc text
    mapfile -t cmd < <(python3 -c 'from stackshot.core import config; print("\n".join(config.notice_cmd()))' 2>/dev/null)
    [ "${#cmd[@]}" -gt 0 ] && [ -n "${cmd[0]}" ] || return 1
    command -v "${cmd[0]}" >/dev/null 2>&1 || return 2
    text=$(python3 -c 'import sys
t = (sys.argv[1] + " \u2014 " + sys.argv[2]).replace("\r", " ").replace("\n", " ").replace("\t", " ")
if len(t) > 400: t = t[:399] + "\u2026"
sys.stdout.buffer.write(t.encode("utf-8", "surrogateescape"))' "$1" "$2") || return 2
    timeout -k 5 "$NOTICE_TIMEOUT" "${cmd[@]}" "$text" >/dev/null 2>&1 6>&- 7>&- 8>&- 9>&-; nrc=$?
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
        stackshot/model/next_rules.py|stackshot/model/model_guards.py|stackshot/model/owner_steps.py|stackshot/model/bullet_text.py)
            printf 'notice\ta write rule the server enforces on a session'"'"'s writes, read fresh at each write' ;;
        audit_rubric.txt)
            printf 'notice\tthe rubric the daily audit judges a session'"'"'s items by, read at each audit' ;;
        client/hooks/*|stackshot/fleet/client.py|stackshot/projects/pages.py|stackshot/cli.py|bin/stackshot|reboot-hooks/*)
            printf 'nothing\ta script or CLI run fresh at each call' ;;
        stackshot/web/tools/text/*.md)
            printf 'nothing\tthe tools'"'"' text files, server-side (a changed sentence changes the snapshot too, which carries the notice; deploy.sh restarts the server)' ;;
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

# THE HOLD. `release.sh hold --minutes N --by NAME --why TEXT` keeps every release from deploying for a short, named time: work on the server that restarts the board (a change of how it is
# reached, say) must not have a deploy's restarts in the middle of it. It is checked where every deploy of a release passes, under the deploy lock (take_lock: a release by hand or from the
# queue, a group, a rollback): a release that finds a hold lets the lock go, says who holds it and why (its log, and one message), waits, and takes the lock again once the hold is over.
# So a release still merges its PR while held, and stops before its deploy; a rollback waits too. `hold` writes the file under the same lock, so no release's deploy is running once it
# returns. A hold ends by `hold --end` or by its own end, 120 minutes at most; a file there that does not read as a hold holds for 120 minutes from its last change, and says so.
# deploy.sh run by hand does not look at it. With [release] deploy_ssh the hold is taken where release.sh runs.
hold_read() {   # 1 when there is no hold file. Else 0, with $hd_state (active | expired), $hd_by, $hd_why and $hd_until (epoch seconds)
    local line="" mtime cap   # line starts set: a read that fails at once (a folder at that path) leaves it, and set -u would end the script
    hd_state=""; hd_by=""; hd_why=""; hd_until=""
    [ -e "$HOLD_FILE" ] || return 1
    mtime="$(stat -c %Y "$HOLD_FILE" 2>/dev/null)" || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            until=*) hd_until="${line#*=}" ;;
            by=*) hd_by="${line#*=}" ;;
            why=*) hd_why="${line#*=}" ;;
        esac
    done 2>/dev/null < "$HOLD_FILE"
    cap=$((mtime + HOLD_MAX_MIN * 60))
    if [[ "$hd_until" =~ ^[0-9]{1,12}$ ]] && [ -n "$hd_by" ] && [ -n "$hd_why" ]; then
        [ "$hd_until" -le "$cap" ] || hd_until=$cap
    else
        hd_until=$cap; hd_by="unknown"; hd_why="the file $HOLD_FILE does not read as a hold"
    fi
    if [ "$hd_until" -gt "$(date +%s)" ]; then hd_state=active; else hd_state=expired; fi
    return 0
}
hold_end_at() { date -u -d "@$hd_until" +%FT%TZ; }
hold_line() {   # the hold hold_read found, in words
    echo "held by $hd_by until $(hold_end_at) ($(( (hd_until - $(date +%s) + 59) / 60 )) min left): $hd_why" | mq_plain
}
hold_note() {   # one line where a release is started or listed, when a hold stands; never fails
    ! hold_read || [ "$hd_state" != active ] || say "note: releases are $(hold_line). A release merges its PR and then waits before its deploy (release.sh hold --end ends the hold)"
    return 0
}
hold_cmd() {   # release.sh hold --minutes N --by NAME --why TEXT | --status | --end
    local use="usage: release.sh hold --minutes N --by NAME --why TEXT | hold --status | hold --end" mins="" by="" why="" until_s replaced=""
    case "${1:-}" in
        --status)
            [ $# -eq 1 ] || { echo "$use" >&2; return 2; }
            if ! hold_read; then echo "no hold on releases"
            elif [ "$hd_state" = active ]; then echo "releases are $(hold_line)"
            else echo "no hold on releases: the one by $hd_by ended at $(hold_end_at) ($hd_why)"; fi
            return 0 ;;
        --end)
            [ $# -eq 1 ] || { echo "$use" >&2; return 2; }
            if ! hold_read; then echo "no hold on releases"; return 0; fi
            rm -f "$HOLD_FILE" || { echo "the hold could not be ended: $HOLD_FILE cannot be removed; it stands until $(hold_end_at)" >&2; return 1; }
            if [ "$hd_state" = active ]; then echo "hold ended: it was held by $hd_by until $(hold_end_at): $hd_why"
            else echo "no hold on releases: the one by $hd_by had ended at $(hold_end_at); its file is removed"; fi
            return 0 ;;
    esac
    while [ $# -gt 0 ]; do
        [ $# -ge 2 ] || { echo "$use" >&2; return 2; }
        case "$1" in
            --minutes) mins="$2" ;;
            --by) by="$2" ;;
            --why) why="$2" ;;
            *) echo "$use" >&2; return 2 ;;
        esac
        shift 2
    done
    { [ -n "$mins" ] && [ -n "${by//[[:space:]]/}" ] && [ -n "${why//[[:space:]]/}" ]; } || { echo "$use (all three are needed)" >&2; return 2; }
    { [[ "$mins" =~ ^[1-9][0-9]{0,2}$ ]] && [ "$mins" -le "$HOLD_MAX_MIN" ]; } || { echo "release.sh hold: --minutes is a whole number from 1 to $HOLD_MAX_MIN" >&2; return 2; }
    { [[ "$by" != *[[:cntrl:]]* ]] && [[ "$why" != *[[:cntrl:]]* ]] && [ "${#by}" -le 80 ] && [ "${#why}" -le 200 ]; } ||
        { echo "release.sh hold: --by is one line of 80 characters at most, --why one of 200 at most" >&2; return 2; }
    mkdir -p "$(dirname "$LOCK_FILE")" "$LOGDIR"
    exec 9>>"$LOCK_FILE" || { exec 9>&-; echo "not held: cannot open the lock file $LOCK_FILE" >&2; return 1; }
    if ! flock -n 9; then echo "a deploy is under way: waiting for it, up to $LOCK_WAIT s"
        flock -w "$LOCK_WAIT" 9 || { exec 9>&-; echo "not held: another deploy held the lock $LOCK_FILE for more than $LOCK_WAIT s" >&2; return 1; }; fi
    if hold_read && [ "$hd_state" = active ]; then
        [ "$hd_by" = "$by" ] || { echo "not held: releases are already $(hold_line) (release.sh hold --end ends it)" >&2; exec 9>&-; return 1; }
        replaced=" (your earlier hold is replaced)"
    fi
    until_s=$(( $(date +%s) + mins * 60 ))
    { printf 'until=%s\nby=%s\nwhy=%s\n' "$until_s" "$by" "$why" > "$HOLD_FILE.$$" && mv -f "$HOLD_FILE.$$" "$HOLD_FILE"; } ||
        { rm -f "$HOLD_FILE.$$"; exec 9>&-; echo "not held: could not write $HOLD_FILE" >&2; return 1; }
    exec 9>&-
    hold_read || { echo "not held: $HOLD_FILE cannot be read back" >&2; return 1; }
    echo "releases are $(hold_line)$replaced. No release deploys until then; release.sh hold --end lets them go on sooner"
}
take_lock() {  # the deploy lock on fd 9 (exec: this shell's own), waited for up to LOCK_WAIT; $1 says what was done when it fails. A hold (THE HOLD) is waited out first, without the lock
    local told=""
    mkdir -p "$(dirname "$LOCK_FILE")"
    while :; do
        exec 9>>"$LOCK_FILE" || { exec 9>&-; fail "deploy lock" "cannot open the lock file $LOCK_FILE"; }
        if ! flock -n 9; then [ -n "$told" ] || say "another release holds the deploy lock; waiting up to $((LOCK_WAIT/60)) min ($LOCK_WAIT s)"   # a waiter on a hold takes the lock for a moment: not said again
            flock -w "$LOCK_WAIT" 9 || { exec 9>&-; fail "deploy lock" "another deploy held the lock $LOCK_FILE for more than $LOCK_WAIT s; $1"; }; fi
        hold_read || break
        if [ "$hd_state" = expired ]; then
            say "$(echo "the hold on releases by $hd_by ended at $(hold_end_at) ($hd_why): going on" | mq_plain)"; rm -f "$HOLD_FILE" || say "its file $HOLD_FILE could not be removed"
            break
        fi
        exec 9>&-
        if [ "$told" != "$hd_until $hd_by $hd_why" ]; then
            told="$hd_until $hd_by $hd_why"
            say "releases are $(hold_line). Waiting before the deploy; release.sh hold --end lets it go on"
            tell "[release] ${SYNC_WHO:-a release} waits before its deploy: releases are $(hold_line). release.sh hold --end lets it go on"
        fi
        sleep "$POLL_HOLD"
    done
    say "deploy lock taken"
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
#   again at the next POLL_MAIN poll, with no GitHub call beyond the ones a pending run costs, and decides when the step shows. Both callers (pre: the wait before a deploy whose gate is closed; post: after the
#   deploy at the merge, which rolls back on "fail") treat it as pending, never as a failure. WAIT_STEPS (RELEASE_WAIT_STEPS, 600 s = 10 min, counted on the clock from the first look that saw the gap on that run)
#   bounds it: past it the run counts as GREEN on its own conclusion (it concluded success, and a job that succeeded has every step succeeded; only GitHub's step list is missing), with a WARNING line in the log and the
#   report going to the keeper ("finished successfully, but its step results never arrived ... counted as green"), never a rollback: a green main was once rolled back on this gap (PR 48, run 42442246277). A run whose job
#   itself did not succeed (conclusion failure), with the suites step missing, still fails at once.
# Two callers:
#   main_green pre <M>     before a deploy whose gate is closed (4d at the top): its suites failing stops the release (merged, not deployed: fix forward); every suite
#                          passing deploys, and what else the run found (a later step that failed; the audit's selection miss and a suite that failed only when measured are found by suitemap-refresh.yml now, and the code below still reads them should a run of tests.yml carry them) goes in the report, which then goes to the keeper instead of green.
#                          The commit it passed on is left in $verified and the deploy is pinned to it (DEPLOY_TO), never to a newer tip with no passing run:
#                          a merge another release lands meanwhile is deployed by that release, after its own run.
#   main_green post <M>    after the deploy at the merge: M is the one deployed, whatever main's tip is by now. It never
#                          fails the release; it returns 0 (the run passed; $audit_note holds what else it found) or 1, with $mg_kind
#                          "fail" (its suites failed: the caller rolls back) or "unknown" (no run passed or failed in time; a cancelled run is the same as none): that one does not roll back,
#                          and $mg_why, $mg_rid and $mg_rsha (the run, and the commit it ran on, which can be a newer one covering several merges).
# A pass writes the commit to $LAST_GOOD (record_good). tests.yml's step name "run every suite, measured" is read here (and "audit the selection", which tests.yml no longer has: the audit moved to suitemap-refresh.yml, and a run without that step reads as one with no audit finding).
# The name is kept though nothing is measured in tests.yml any more: it is a step of the `suites` job; on main that job runs after the `proof`, the `shards` plan and the `measure` matrix (main's plain run, split across runners) and its "run every suite, measured" passes only when
# every shard passed and `tests/suitemap.py complete` found every suite once, none failed (or, when the proof job found the merge queue's green run of the same commit, at once, saying so), so a failed shard reads here as a failed suites step. The shards' steps have other names.
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
    flaky = []                        # tests/suitemap.py measure warns when a suite fails only when measured (a run of suitemap-refresh.yml; not one of tests.yml any more)
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
    tell "[release] PR #$pr: the last-good record $LAST_GOOD holds '$(head -c 80 "$LAST_GOOD" 2>/dev/null | tr -d '\n')', which is not a commit this checkout knows. It is left alone, and releases wait for main's run before they deploy until it is fixed: delete the file to start again from the deployed HEAD"
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
# record_sync (4c-record): copy $LAST_GOOD to the host [release] deploy_ssh names, whose server reads its own copy (service/released_live.py). Called before client.py released and when a release ends. 0 that host holds the record, or there is
# nothing to copy (deploy_ssh unset: this box's file is the one the server reads; or no record yet). 1 it does not: a log line, and one message a process. It never changes this box's record and never fails a release.
# The record is read inside the flock on $LAST_GOOD.sync.lock, held until the host has answered, so of two releases of this box the later write is never the older record. Over there the write is atomic and only for a commit that checkout knows,
# so the server never reads a record it cannot resolve. It is never moved back there either: under that box's flock on its last-good.lock, a record that is a later commit than this one (another release box's, or this copy arriving after a newer
# one) stays, which counts as copied and is said in the log. The whole command there is cut 20 s before this ssh is (its 15 s connect and the 5 s of timeout -k fit), so it does not outlive a copy that was given up.
record_sync() {
    [ -n "$DEPLOY_SSH" ] || return 0
    local out rc=0
    out="$( (
        flock -w "$((RECORD_TIMEOUT + 30))" 5 || { echo "$LAST_GOOD.sync.lock was not free"; exit 1; }
        read_good; case $? in 1) exit 0 ;; 2) echo "$LAST_GOOD holds something this checkout cannot read as a commit"; exit 1 ;; esac
        [[ "$DEPLOY_SSH" =~ ^[A-Za-z0-9_][A-Za-z0-9._@:-]*$ ]] || { echo "[release] deploy_ssh = \"$DEPLOY_SSH\" is not an ssh host name"; exit 1; }
        c="\"$good^{commit}\""
        script='{ git cat-file -e '"$c"' 2>/dev/null || { timeout 30 git fetch --quiet origin main >/dev/null 2>&1; git cat-file -e '"$c"' 2>/dev/null; } || { echo "the checkout there does not have that commit, and a fetch of main there did not bring it"; exit 1; }; } && d="$(python3 stackshot/core/config.py state releases)" && mkdir -p "$d" && exec 8>>"$d/last-good.lock" && { flock -w 10 8 || { echo "the record there stayed locked"; exit 1; }; } && { cur="$(cat "$d/last-good" 2>/dev/null)"; if [ "$cur" != '"$good"' ] && echo "$cur" | grep -Eqx "[0-9a-f]{7,64}" && git merge-base --is-ancestor '"$good"' "$cur" 2>/dev/null; then echo "newer-there $cur"; else printf "%s\n" '"$good"' > "$d/last-good.$$" && mv -f "$d/last-good.$$" "$d/last-good" || { rm -f "$d/last-good.$$"; echo "the record could not be written there"; exit 1; }; fi; }'   # it goes to that box inside single quotes, so it holds none
        there=$(( RECORD_TIMEOUT > 21 ? RECORD_TIMEOUT - 20 : 1 ))   # the seconds the whole command may take there
        cmd="cd ~/stackshot && exec timeout -k 5 $there sh -c '$script'"
        said="$(timeout -k 5 "$RECORD_TIMEOUT" ssh -o BatchMode=yes -o ConnectTimeout=15 "$DEPLOY_SSH" "$cmd" </dev/null 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-)" || { rc=$?; echo "${good:0:7} was not written there (exit status $rc): $(echo "$said" | tail -1)"; exit 1; }
        newer="$(echo "$said" | sed -n 's/^newer-there \([0-9a-f]*\)$/\1/p' | tail -1)"
        if [ -n "$newer" ]; then echo "it holds a newer one, ${newer:0:7}, which stays (here: ${good:0:7})"; else echo "${good:0:7}"; fi
    ) 2>&1 5>>"$LAST_GOOD.sync.lock" )" || rc=$?
    out="$(echo "$out" | tail -1)"
    if [ $rc -eq 0 ]; then [ -z "$out" ] || say "last-good record on $DEPLOY_SSH: $out"; return 0; fi
    say "the last-good record was NOT copied to $DEPLOY_SSH: $out"
    [ -n "$SYNC_TOLD" ] || { SYNC_TOLD=1
        tell "[release] $SYNC_WHO: the last-good record was NOT copied to the server box ($DEPLOY_SSH): $out. Until it is, the server reads an older record and settles nothing merged after it. A later copy in this or the next release tries again; $HERE/release.sh --copy-record does it now, and client.py sweep-released then settles what was refused"; }
    return 1
}
# running_start, running_end (4c-running): with [release] deploy_ssh the server is on another box, where this release's unit and log are not, so the release tells that box it runs (core/release_running.py). running_start starts the process that
# says so now and every RUN_BEAT s until this shell is gone; it holds none of the release's descriptors and writes to a file of its own, never to the release log (whose age says whether the release moves). running_end, as the release exits, stops
# that process and says once that the release ended. Neither fails the release, and running_start waits for nothing; running_end waits RUN_LIMIT s at most, after everything else the release does.
running_start() {   # $1 = the PR, $2 = its release log
    [[ "$DEPLOY_SSH" =~ ^[A-Za-z0-9_][A-Za-z0-9._@:-]*$ ]] || return 0   # unset: one box, nothing to tell; not a host name: record_sync says so when the release ends
    RUN_PR="$1"; RUN_LOG="$2"
    ( exec python3 stackshot/core/release_running.py beat "$RUN_PR" "$RUN_LOG" "$DEPLOY_SSH" --parent $$ --every "$RUN_BEAT" --limit "$RUN_LIMIT" ) </dev/null >>"$LOGDIR/running-publish.log" 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- &
    RUN_PID=$!
}
running_end() {
    [ -n "$RUN_PID" ] || return 0
    local why
    kill "$RUN_PID" 2>/dev/null; wait "$RUN_PID" 2>/dev/null; RUN_PID=""   # gone, with any send of its own, before the last word: what a send of it still does over there is older than the last word and changes nothing
    why="$(python3 stackshot/core/release_running.py end "$RUN_PR" "$RUN_LOG" "$DEPLOY_SSH" --limit "$RUN_LIMIT" </dev/null 2>&1 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&-)" ||
        say "$DEPLOY_SSH was not told that this release ended ($(echo "$why" | tail -1 | mq_plain)): it may count it as running for up to 5 more minutes"
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
        if sha in rng and r.get("conclusion") == "cancelled":   # the deploy gate stays careful: cancelled while queued (no step ran) was replaced by a newer run; after its job started it says nothing, so unknown
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
# deploy_run <sha> [rollback]: the deploy step (and the rollback), with the lock held by the caller; its output is deploy.sh's, its status deploy.sh's. [release] deploy_ssh unset: ./deploy.sh here, as ever.
# Set: the same deploy.sh, with the same variables, runs on that host in ~/stackshot over `ssh -o BatchMode=yes -o ConnectTimeout=15`; a rollback there takes the host's own deploy lock around it (deploy.sh refuses a rollback unless the lock is held
# where it runs, and the lock this release holds is a file on this box). A deploy that succeeded is followed by follow_local, whose status (FOLLOW_SKIPPED_RC) is deploy_run's: the server is live, this checkout is not at the commit.
FOLLOW_SKIPPED_RC=75
deploy_run() {
    local sha="$1" rb="${2:-}" cmd rc=0
    if [ -z "$DEPLOY_SSH" ]; then
        if [ -n "$rb" ]; then DEPLOY_LOCK_FILE="$LOCK_FILE" DEPLOY_ROLLBACK=1 DEPLOY_TO="$sha" ./deploy.sh; else DEPLOY_TO="$sha" ./deploy.sh; fi
        return
    fi
    [[ "$DEPLOY_SSH" =~ ^[A-Za-z0-9_][A-Za-z0-9._@:-]*$ ]] || { echo "deploy refused: [release] deploy_ssh = \"$DEPLOY_SSH\" is not an ssh host name"; return 1; }
    [[ "$sha" =~ ^[0-9a-f]{40,64}$ ]] || { echo "deploy refused: $sha is not a full commit id"; return 1; }
    if [ -n "$rb" ]; then cmd='cd ~/stackshot && L="$(python3 stackshot/core/config.py state releases)/deploy.lock" && mkdir -p "$(dirname "$L")" && exec flock "$L" env DEPLOY_LOCK_FILE="$L" DEPLOY_ROLLBACK=1 DEPLOY_TO='"$sha"' ./deploy.sh'
    else cmd='cd ~/stackshot && DEPLOY_TO='"$sha"' ./deploy.sh'; fi
    echo "deploying on $DEPLOY_SSH over ssh ([release] deploy_ssh)"
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$DEPLOY_SSH" "$cmd" </dev/null || rc=$?
    if [ $rc -ne 0 ]; then [ $rc -ne $FOLLOW_SKIPPED_RC ] || rc=1; return $rc; fi   # a deploy.sh that exits with the follow's own status is a plain failure
    follow_local "$sha" "$rb"
}
# follow_local <sha> [rollback]: after a deploy on another box, this checkout (the one release.sh runs in, which the gate and the rollback read as the live one) goes to the same commit: git merge --ff-only, or git reset --keep for
# a rollback; never the server's units. The puller runs from this checkout: it is restarted only when the move touched its files (deploy.sh's puller list), the rest it reloads on its own. A move that cannot be made (local changes, or the git
# command fails) returns FOLLOW_SKIPPED_RC with its reason as the last line of the output: the server is live at the commit and this checkout, which the gate, the live check and the rollback read as the live one, is not, so the caller pauses
# the release queue and reports red (a rollback keeps its own red report and adds the line). A puller that cannot be restarted stays a WARNING line and returns 0.
follow_local() {
    local sha="$1" rb="${2:-}" files rc=0
    if [ -n "$(git status --porcelain --untracked-files=no 2>&1)" ]; then echo "  this checkout ($HERE) has local changes, so it was not moved to ${sha:0:7}; the server is live there: git -C $HERE merge --ff-only ${sha:0:7} (reset --keep for a rollback) once it is clean"; return $FOLLOW_SKIPPED_RC; fi
    files="$(git diff --name-only HEAD "$sha" 2>/dev/null)"
    if [ -n "$rb" ]; then git reset --keep --quiet "$sha" || rc=$?; else git merge --ff-only --quiet "$sha" || rc=$?; fi
    if [ $rc -ne 0 ]; then echo "  this checkout ($HERE) could not be moved to ${sha:0:7} (exit status $rc); the server is live there: git -C $HERE merge --ff-only ${sha:0:7} (reset --keep for a rollback)"; return $FOLLOW_SKIPPED_RC; fi
    echo "  local: this checkout is at ${sha:0:7}"
    if grep -qE '^(stackshot/fleet/(puller|client)\.py|stackshot/core/(config|retired_inputs)\.py|stackshot/(__init__|__main__|paths)\.py|units/stackshot-puller\.service\.in)$' <<< "$files"; then
        if systemctl --user restart stackshot-puller.service >/dev/null 2>&1; then echo "  local: restarted stackshot-puller.service"
        else echo "  WARNING: stackshot-puller.service could not be restarted here: systemctl --user restart stackshot-puller.service"; fi
    fi
    ! grep -qE '^units/stackshot-puller\.service\.in$' <<< "$files" || echo "  local: the puller's unit file changed; ./install.sh puller here installs it"
    return 0
}
# follow_why <sha> <deploy_run's output>: the red report's words when the deploy on $DEPLOY_SSH succeeded and follow_local could not move this checkout. The release ends here (main's run is not watched, so nothing rolls the deploy back and
# this release records nothing as the last good commit: its fast path's record (record_pass_live) only takes a commit this checkout contains, and it never gets there), and the queue was paused by the caller.
follow_why() {
    echo "the server ($DEPLOY_SSH) is live at ${1:0:7} but this checkout could not follow ($(echo "$2" | tail -1 | sed 's/^ *//')); it is at $(git rev-parse --short HEAD), and this release does not watch main's run, so a failure there rolls nothing back: release.sh queue --resume goes on once the checkout is clean"
}
deploy_gate() {   # $1 = the merge commit M, $2 = 1 when the merge came through GitHub's merge queue (else 0), $3 = why not, under the deploy lock. The merge queue ran the suites its selection picked on the tree it made (a merge_group run, not
                  # every suite), so M deploys at once only when the queue made it and what lies between the live checkout and M is not known to be bad:
                  # (a) the live checkout is an ancestor of M (deploy.sh fast-forwards to it; the commits on the way are merges of the queue, each tested on its tree, or docs-only merges); (b) a last-good commit to roll back to is recorded and in the
                  # live history; (c) no commit after the last good one has a failed run on main, up to main's tip (a later member of the same merge group counts: its failure is a failure of the line M is on). A run still pending is fine:
                  # back-to-back releases stay fast, and a failure of the first rolls both back. No pending-verify record is unread, and the release queue is not paused (a rollback or a failed deploy of a queue-started release pauses it).
                  # Sets $good (the last good commit to roll back to), or $gate_why and returns 1: the caller waits for main's tests before it deploys (4d)
    local cur st rid verdict rsha detail bad rg cn tip; cur="$(git rev-parse HEAD)"; gate_why=""
    [ "${2:-0}" = 1 ] || { gate_why="${3:-the merge did not come through the merge queue}"; return 1; }
    [ -z "$pv_block" ] || { gate_why="$pv_block"; return 1; }
    [ ! -f "$QUEUE.paused" ] || { gate_why="the release queue is paused ($(head -1 "$QUEUE.paused"))"; return 1; }
    git merge-base --is-ancestor "$cur" "$1" || { gate_why="(a) the live checkout (${cur:0:7}) is not an ancestor of the merge ${1:0:7}: deploy.sh could not fast-forward to it"; return 1; }
    read_good; rg=$?
    if [ $rg = 2 ]; then gate_why="the last-good record is unreadable"; record_unreadable; return 1
    elif [ $rg = 1 ]; then   # first use: the deployed HEAD is the last good commit when its run on main passed
        st="$(run_state "$cur")"; read -r rid verdict rsha detail <<< "$st"
        if [ "$verdict" != pass ]; then gate_why="(b) no last-good commit is recorded and the run on main for the deployed ${cur:0:7} is not known to have passed (${verdict:-no run found}), so there is nothing to roll back to"; return 1; fi
        record_good "$cur" || { gate_why="(b) the deployed ${cur:0:7} could not be recorded as the last good commit"; return 1; }
        good="$cur"; say "no last-good commit was recorded: seeded with the deployed ${cur:0:7}, whose run $rid on main passed"
    fi
    git merge-base --is-ancestor "$good" "$cur" || { gate_why="(b) the last-good commit ${good:0:7} is not in the deployed history (${cur:0:7})"; return 1; }
    tip="$(git rev-parse origin/main 2>/dev/null)"; [ -n "$tip" ] || tip="$1"   # main's tip after the fetch: later merges of the group are in the range
    bad="$(failed_runs "$good" "$tip")"
    if [ "$(echo "$bad" | tail -1)" != ok ]; then
        cn="$(echo "$bad" | grep '^cancelled ' | head -1)"
        if [ -n "$cn" ]; then gate_why="(c) a commit after the last good one (${good:0:7}) has a run on main cancelled after its job started (${cn#cancelled } as run and commit): unknown, not vouched for"
        else gate_why="(c) the runs on main since the last good commit ${good:0:7} cannot be read, or do not reach it"; fi
        return 1
    fi
    bad="$(echo "$bad" | sed '$d' | head -1)"
    if [ -n "$bad" ]; then gate_why="(c) a commit after the last good one (${good:0:7}) has a failed run on main (run ${bad%% *} on ${bad#* })"; return 1; fi
    return 0
}
record_pass_live() {   # $1 = a commit deployed at the merge whose main run passed. Under the deploy lock (a rollback holds it for the reset, so none lands between the check and the record):
                       # 0 it is in the live checkout and is recorded as the last good commit; 1 it is not (rolled back meanwhile): nothing recorded; 2 the lock was not had in $LOCK_WAIT s: not recorded, told
    local rc=0
    exec 9>>"$LOCK_FILE" || { exec 9>&-; return 2; }
    flock -w "$LOCK_WAIT" 9 || { exec 9>&-; return 2; }
    if git merge-base --is-ancestor "$1" HEAD; then record_good "$1" || true; else rc=1; fi
    exec 9>&-; return $rc
}
mg_stop() {   # $1 = fail|unknown, $2 = why. Before the deploy it fails the release; after the deploy at the merge it returns 1 for the caller to decide
    mg_kind="$1"; mg_why="$2"
    if [ "$mg_mode" != post ]; then
        [ "$1" != unknown ] || q_fail=none   # a main run that could not be read is not a failure of the code: it ends this release as before, but does not pause the release queue
        fail "main's tests" "$2: merged, not deployed"
    fi
    return 1
}
main_green() {   # $1 = pre|post, $2 = M, the merge commit of the release; the rule is in the comment above run_state
    local mg_mode="${1:-pre}" m="${2:-}" steps_run="" steps_start=0 steps_waited=0 steps_gap=0 ci_line="" ci_st="" ci_what="" ci_said=0 t0 now waited=0 run_start=0 run_waited=0 fetch_since="" fetch_waited=0 cur_run="" out rid verdict rsha detail err via="" by="" cnote="" cn_said=0 pn_said=0
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
        if [ "$verdict" = pending ] && [ "$detail" = steps ]; then   # the run is completed and green but GitHub has not filled in its step results yet: read again at the next poll, WAIT_STEPS at most (from the first look that saw the gap on this run); past it the run counts as green on its own conclusion (success), with a warning: never a failure
            [ "$rid" = "$steps_run" ] || { steps_run="$rid"; steps_start=$now; say "main's run $rid on ${rsha:0:7} is completed and green, but GitHub has not filled in its step results yet: reading it again every $POLL_MAIN s, for $((WAIT_STEPS/60)) min at most"; }
            steps_waited=$((now - steps_start))
            [ $steps_waited -lt $WAIT_STEPS ] || { steps_gap=1; verdict=pass; detail="finished successfully, but its step results never arrived in $((steps_waited/60)) min: no conclusion for \"run every suite, measured\", so the suites step was not read"
                say "WARNING: main's run $rid on ${rsha:0:7} concluded success but GitHub never filled in its step results in $((steps_waited/60)) min: counted as green (not rolled back); the suites step itself could not be read"; }
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
                if [ "$steps_gap" = 1 ]; then
                    audit_note="; main's run concluded success and is counted as green, but $detail (https://github.com/$REPO/actions/runs/$rid)"
                    say "main's run: $detail: counted as green, the report goes to the keeper"
                elif [ -n "$detail" ]; then
                    audit_note="; every suite passed on main, but $detail (https://github.com/$REPO/actions/runs/$rid)"
                    say "main's run: $detail: the report goes to the keeper"
                fi
                return 0 ;;
            fail) mg_rid="$rid"; mg_rsha="$rsha"
                  by=""; [ "$rsha" = "$m" ] || by="; ${rsha:0:7} is the oldest commit after the merge ${m:0:7} whose run failed, and no run on ${m:0:7} or between them passed, so that run decided it"
                  if [ "$mg_mode" = pre ] && git merge-base --is-ancestor "$m" HEAD; then
                      # the merge waited for its own run (the deploy gate was closed), but a release deployed on top of it meanwhile and the live checkout contains it now. It is LIVE, not
                      # "merged, not deployed": the same rollback as after a deploy at the merge, which takes the later deploy out with it; its own run would only find out up to an hour later
                      verified="$m"; mg_kind=fail; live_later=1
                      mg_why="a release deployed on top of this merge while it waited for its run, so it went live with that one and was not only merged; the run on main for ${rsha:0:7} failed ($detail; https://github.com/$REPO/actions/runs/$rid)$by"
                      say "main's run failed on ${m:0:7}, which is live through a later release's deploy: rolling it back"
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
verify_pending() {   # $1 = a stale record's file, $2 = the commit, $3 = its PR, $4 = when it was deployed (epoch): one look at the commit's main run (no waiting). Sets $pv_block while the deploy gate must stay closed
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
        say "$pv_block: the deploy gate stays closed until it is read"; return 0
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
                 say "$pv_block: the deploy gate stays closed until it is read" ;;   # the record stays
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
recover_pending() {   # a record whose lock is free belongs to a release process that is gone: finish its main-run check first (fail, unknown: red report, the deploy gate stays closed; pass: recorded)
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
regen_snapshot() {   # 2a: $1 = the step it is for (mergeable | removed). A PR that conflicts with main on the generated tests/tool_text.snapshot.json alone is mended here: tools/snapshot_regen.py merges
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
tests_on_head() {   # 0 when the tests job ($TESTS_CHECK) has a completed, successful check run on $headsha itself (GitHub's check-runs of that commit); anything else, or unreadable: 1
    gh api "repos/$REPO/commits/$headsha/check-runs?per_page=100" 2>/dev/null | NEED="$TESTS_CHECK" python3 -c '
import json,os,sys
try: runs = json.load(sys.stdin)["check_runs"]
except Exception: sys.exit(1)
sys.exit(0 if any(r.get("name") == os.environ["NEED"] and r.get("status") == "completed" and r.get("conclusion") == "success" for r in runs) else 1)'
}
gh_cached() {   # $1 = a salt (the PR head the answer is about), then gh's arguments. The answer of the last GH_TTL s (any release on this box asked it; <state>/releases/gh-cache, the folder run_state uses) is reused; only a successful, non-empty answer is kept; a failed call prints nothing on stdout (gh's error goes to stderr) and returns its status
    SALT="$1" GH_CACHE="$GH_CACHE" GH_TTL="$GH_TTL" python3 -c '
import hashlib, os, subprocess, sys, time
a = sys.argv[1:]; CD, TTL = os.environ.get("GH_CACHE", ""), float(os.environ.get("GH_TTL") or 0)
f = os.path.join(CD, hashlib.sha1("\0".join((*a, os.environ["SALT"])).encode()).hexdigest()) if CD and TTL > 0 else ""
if f:
    try:
        if time.time() - os.stat(f).st_mtime < TTL: sys.stdout.write(open(f, encoding="utf-8").read()); sys.exit(0)
    except OSError: pass
r = subprocess.run(["gh", *a], capture_output=True, text=True)
if r.returncode != 0: sys.stderr.write(r.stderr); sys.exit(r.returncode)
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
orphan_scan() {   # $1 = pr (this head's pull_request runs) | queue (this PR's merge_group runs). Prints the ids of the orphans (pr: to replace; queue: to fail on), one per line, or nothing. Only the NEWEST run of each workflow is judged: an older one is
                  # superseded by it, whatever its state (a ghost of an earlier release, close and reopen or group is never taken for the run that holds the wait). The newest runs are replaced only when every one that is
                  # not completed is `queued` for at least ORPHAN_QUEUED s with an EMPTY job list (one view each): a newest run that is going, younger, or has a job (even a queued one) replaces nothing, since the new run would
                  # cancel it. A run already replaced (orphan_done) is passed over. A run's age is its attempt's (startedAt: a rerun attempt of an old run is as young as the rerun; createdAt when it is missing).
                  # Any answer GitHub does not give (a gh error, a reply that is not as expected) replaces nothing.
                  # pr: the runs of this very head (--commit). queue: the runs of this PR's groups (gh-readonly-queue/main/pr-<n>-...) created at or after the PR's queue entry (GitHub's enqueuedAt, $gq_since: a rerun
                  # finds an entry an earlier release made; this enqueue call's second, $enq_epoch, while no entry was read), less ORPHAN_SLACK s for the clock of GitHub against this host's; the newest of them is
                  # the current group's (a group rebuilt after a failure ahead of it gets a new run)
    local list ids id view ORPHAN_SLACK=120
    if [ "$1" = pr ]; then list="$(gh run list --event pull_request --commit "$headsha" --repo "$REPO" --json databaseId,status,createdAt,startedAt,workflowName --limit 30 2>/dev/null)" || return 0
    else list="$(gh run list --event merge_group --repo "$REPO" --json databaseId,status,createdAt,startedAt,headBranch,workflowName --limit 50 2>/dev/null)" || return 0; fi
    ids="$(echo "$list" | KIND="$1" PR="$pr" CAP="$ORPHAN_QUEUED" NOW="$(date +%s)" DONE="$orphan_done" ENQ="${gq_since:-${enq_epoch:-0}}" SLACK="$ORPHAN_SLACK" python3 -c '
import datetime, json, os, sys
E = os.environ
def sec(x): return int(datetime.datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp())
try:
    now, cap, done, new = int(E["NOW"]), int(E["CAP"]), E["DONE"].split(), {}
    for r in json.load(sys.stdin):
        t = sec(r["createdAt"])
        if E["KIND"] == "queue" and ("/pr-" + E["PR"] + "-" not in (r.get("headBranch") or "") or t < int(E["ENQ"]) - int(E["SLACK"])): continue
        k = r.get("workflowName") or ""
        if k not in new or (t, int(r["databaseId"])) > new[k][0]: new[k] = ((t, int(r["databaseId"])), r)
    ids = []
    for (t, i), r in new.values():
        if r.get("status") == "completed" or str(i) in done: continue
        if r.get("status") != "queued" or now - sec(r.get("startedAt") or r["createdAt"]) < cap: sys.exit()
        ids.append(str(i))
    print("\n".join(sorted(ids, key=int)))
except Exception: pass' 2>/dev/null)"
    for id in $ids; do
        [[ "$id" =~ ^[0-9]+$ ]] || return 0
        view="$(gh run view "$id" --repo "$REPO" --json jobs,status,createdAt,startedAt 2>/dev/null)" || return 0
        echo "$view" | NOW="$(date +%s)" CAP="$ORPHAN_QUEUED" python3 -c '
import datetime, json, os, sys
try:
    r = json.load(sys.stdin)
    t = int(datetime.datetime.strptime(r.get("startedAt") or r["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp())
    ok = r.get("status") == "queued" and isinstance(r.get("jobs"), list) and len(r["jobs"]) == 0 and int(os.environ["NOW"]) - t >= int(os.environ["CAP"])
except Exception: ok = False
sys.exit(0 if ok else 1)' 2>/dev/null || return 0
    done
    [ -z "$ids" ] || echo "$ids"
}
orphan_names() {   # $1 = the run ids, space separated -> $on_txt ("run 4001" | "runs 4001, 4002"), $on_has (has | have), $on_be (is | are)
    local n=($1)
    if [ ${#n[@]} -eq 1 ]; then on_txt="run $1"; on_has=has; on_be=is; else on_txt="runs ${1// /, }"; on_has=have; on_be=are; fi
}
orphan_said() {   # $1 = the run ids (space separated: one replacement covers all of them), $2 = what replaces them. Every id is recorded: a replaced run stays listed as queued and is never replaced twice
    local i on_txt on_has on_be; orphan_names "$1"
    say "$on_txt $on_has been queued for more than $((ORPHAN_QUEUED/60)) min with no jobs: GitHub never starts such a run and it cannot be cancelled or rerun; replacing it with a new run ($2), once"
    for i in $1; do orphan_done="$orphan_done$i "; done
}
# A release reopens only a PR it KNOWS it closed: GitHub answered its own close call (gh pr close returned, not saying the PR was closed already). GitHub cannot say whose call closed a PR (every gh write here is the
# same account, and a release cannot tell its writes from another's), so a close call that errored or never answered, and a PR a rerun finds CLOSED, are never reopened by a release: the log says how to do it by hand.
orphan_open=""      # a PR this release closed (its close call answered) and has not reopened yet: the exit trap reopens it, with no read first, however the release ends
orphan_closing=""   # a PR whose close call is under way (set right before it, cleared once the release knows what the call did: its answer, or the reads after an error): a release that ends then (a signal can land
                    # after GitHub took the close and before gh answers) cannot tell whether its call closed the PR, and the exit trap reopens nothing and says so. The marker file under the state dir
                    # ($LOGDIR/orphan-reopen-<pr>, "<epoch> <head> <run ids>": the second before the close call, the runs it replaces) outlives a release that ends with the PR maybe closed by it: a rerun that finds
                    # the PR CLOSED names it in its failure, one that finds it open passes over those runs at its first look only (orphan_prior)
orphan_look() {   # $1 = the PR. GitHub's word on it now, one line "<STATE> <head oid>"; nothing when the answer cannot be read
    gh pr view "$1" --repo "$REPO" --json state,headRefOid 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin); print(d["state"], d.get("headRefOid") or "-")
except Exception: pass' 2>/dev/null
}
orphan_inq() {   # $1 = the PR. Its merge-queue entry as GitHub has it now: "<STATE> <position>", or "-" when the PR is in no merge queue; nothing, status 1, when the answer cannot be read (a reply without the field
                 # included). Its own query, not ghq_read: the merge queue wait's globals stay as they are
    gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){mergeQueueEntry{state position}}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null | python3 -c '
import json, sys
try:
    e = json.load(sys.stdin)["data"]["repository"]["pullRequest"]["mergeQueueEntry"]
    print("-" if e is None else "%s position %s" % (e["state"], e.get("position")))
except Exception: sys.exit(1)' 2>/dev/null
}
orphan_reopen() {   # $1 = the PR. Reopens it (4 tries, 5 s apart). 0 when GitHub took it: the marker and $orphan_open are cleared
    local try
    for try in 1 2 3 4; do
        if gh pr reopen "$1" --repo "$REPO" >/dev/null 2>&1; then rm -f "$LOGDIR/orphan-reopen-$1"; orphan_open=""; return 0; fi
        [ $try = 4 ] || sleep 5
    done
    return 1
}
orphan_settled() {   # $1 = the PR, $2 = the seconds between reads. orphan_look up to three times: the first answer that is not OPEN (GitHub can show a close a moment after the call that made it), else the last OPEN one;
                     # nothing when no read gave an answer
    local try now last=""
    for try in 1 2 3; do
        now="$(orphan_look "$1")"
        case "$now" in
            OPEN\ *) last="$now" ;;
            ?*) echo "$now"; return 0 ;;
        esac
        [ $try = 3 ] || sleep "$2"
    done
    [ -z "$last" ] || echo "$last"
}
TRAP_LOG="" TRAP_OUT="" TRAP_TEE=""   # run(): the PR's log, what the shell's stdout is once it goes to the log's tee (the pipe, from /proc), and that tee's pid
trap_out() {   # first in run()'s EXIT trap. gh, git, python3 and sleep are functions here, so a call like `gh ... >/dev/null 2>&1` redirects the shell's own stdout while it runs, and a signal that lands then runs
               # the trap with it still redirected: its lines would be lost. A stop of the whole unit (systemctl stop signals every process of it) can end the tee too, and a write to its pipe would then end the shell
               # (SIGPIPE) before the rest of the trap. So SIGPIPE is ignored from here on, and when stdout is not the tee's pipe, or the tee is gone, the trap writes to the log file itself
    trap '' PIPE
    [ -n "$TRAP_LOG" ] || return 0
    if [ "$(readlink "/proc/$$/fd/1" 2>/dev/null)" != "$TRAP_OUT" ] || { [ -n "$TRAP_TEE" ] && [ ! -e "/proc/$TRAP_TEE/fd/0" ]; }; then exec >>"$TRAP_LOG" 2>&1; fi
}
orphan_exit() {   # in the EXIT trap (after trap_out): a release that ends (a failure, a signal) between its close call and the reopen would leave the PR closed. A close this release knows it made (orphan_open) is reopened
                  # here, 3 tries, with no read first (there is nothing to ask GitHub: the close is this call's, and a read that fails must not keep it closed); a release that ended during its close call (orphan_closing)
                  # cannot tell whether that call closed the PR, and reopens nothing. Each outcome is logged, and the marker stays while the PR may be closed by this release; none is a new failure
    local try pn
    if [ -n "$orphan_open" ]; then
        pn="$orphan_open"; orphan_open=""; orphan_closing=""
        for try in 1 2 3; do
            if gh pr reopen "$pn" --repo "$REPO" >/dev/null 2>&1; then rm -f "$LOGDIR/orphan-reopen-$pn"; say "PR #$pn, closed by this release to replace a run queued with no jobs, is reopened on the way out"; return 0; fi
            [ $try = 3 ] || sleep 3
        done
        say "PR #$pn, closed by this release to replace a run queued with no jobs, could not be reopened on the way out (3 tries): it is CLOSED. Reopen it by hand (gh pr reopen $pn), then run release.sh $pn again"
    elif [ -n "$orphan_closing" ]; then
        pn="$orphan_closing"; orphan_closing=""
        say "this release ended during its call to close PR #$pn (to replace a run queued with no jobs), before it could tell what that call did: whether it closed the PR cannot be told (GitHub does not say whose call closed a PR), so it is not reopened. If PR #$pn is CLOSED and no one else closed it, reopen it by hand (gh pr reopen $pn), then run release.sh $pn again"
    fi
    return 0
}
orphan_pr() {   # in wait_pr_checks: PR check runs that are orphans are replaced by closing and reopening the PR (the head stays; no commit), once for all of them. $1 = the step, $2 = 1 when this step replaced runs already. 0: replaced (the wait clock restarts), 1: no orphan
    local ids now out inq on_txt on_has on_be mk="$LOGDIR/orphan-reopen-$pr" done0="$orphan_done"
    orphan_done="$orphan_done$orphan_prior"; ids="$(orphan_scan pr | tr '\n' ' ')"; ids="${ids% }"
    orphan_done="$done0"; orphan_prior=""   # a rerun's marker runs: passed over at this first look only
    [ -n "$ids" ] || return 1
    orphan_names "$ids"
    # only a newest run that is not recorded gets here (the replacement's own runs supersede the replaced ones): one queued with no jobs after the replacement is a second failure of GitHub, not the first one again
    [ "$2" != 1 ] || fail "$1" "$on_txt $on_be queued with no jobs again, after the PR was closed and reopened once for the same reason; GitHub is not starting this PR's runs (it cannot be cancelled or rerun). To try again, close and reopen the PR by hand (gh pr close $pr, then gh pr reopen $pr) or push a new commit to it, then run release.sh $pr again"
    # the PR as GitHub has it right before the close: one closed or merged during the wait is not this release's to close (nor to reopen), and a moved head is not the head waited on (closing would cancel its runs)
    now="$(orphan_look "$pr")"
    case "$now" in
        "OPEN $headsha") ;;
        OPEN\ *) fail "$1" "the PR's head moved to $(echo "$now" | cut -d' ' -f2 | cut -c1-7) while this release waited for the checks of ${headsha:0:7} (where $on_txt $on_be queued with no jobs); nothing was closed: run release.sh $pr again for the new head" ;;
        "") say "$on_txt $on_be queued with no jobs, but GitHub's answer about the PR's state and head cannot be read; nothing is closed, looked at again in 5 min"; return 1 ;;
        *) # a close call of this release that errored at an earlier look, with the PR still open on three reads after it (orphan_erred), may be the close GitHub shows now: it is not called someone else's
           [ -z "$orphan_erred" ] || [ "${now%% *}" != CLOSED ] || fail "pr state" "the PR is CLOSED. This release's call to close it at an earlier look errored and GitHub still showed the PR open after it: whether that call closed it cannot be told (GitHub does not say whose call closed a PR), so it is not reopened. If no one else closed it, reopen it by hand (gh pr reopen $pr), then run release.sh $pr again"
           fail "pr state" "the PR is ${now%% *}: it was closed or merged while this release waited for its checks; this release did not close it and does not reopen it" ;;
    esac
    mq_line_check   # a group release may have handed the PR to the salamander merge queue while this release waited (as before the enqueue): that queue's PR is not this release's to close
    # a PR in GitHub's merge queue (a rerun finds it there; an earlier release enqueued it) is not closed: closing would take it out of the queue, and the release never does that. Nothing is closed on an answer it cannot read
    inq="$(orphan_inq "$pr")" || inq=""
    case "$inq" in
        -) ;;
        "") say "$on_txt $on_be queued with no jobs, but GitHub's answer about the PR's merge queue entry cannot be read; nothing is closed, looked at again in 5 min"; return 1 ;;
        *) fail "$1" "$on_txt $on_be queued with no jobs, and PR #$pr is in the merge queue ($inq): closing it to replace $([ "$on_be" = is ] && echo it || echo them) would take it out of the queue, which this release does not do (GitHub cannot tell it whether a removal was its own or someone else's), so nothing was closed. If the PR merges from the queue, run release.sh $pr again (it deploys a merged PR); to replace the run instead, remove PR #$pr from the merge queue on GitHub, then run release.sh $pr again" ;;
    esac
    echo "$(date +%s) $headsha $ids" > "$mk"   # before the close: a release that ends with the PR maybe closed by it leaves it for a rerun (which names it, and never reopens the PR)
    orphan_closing="$pr"   # until gh answers, this release cannot tell whether its call closed the PR (a signal can land after GitHub took the close): the exit trap reopens nothing and says so
    if out="$(gh pr close "$pr" --repo "$REPO" 2>&1 >/dev/null)"; then
        # gh exits 0 on a PR that is closed already, saying so ("! Pull request <repo>#<n> (<title>) is already closed"): someone else closed it after the look above; this release did not, and reopens nothing
        case "$out" in *"Pull request "*"#$pr ("*") is already closed"*)
            orphan_closing=""; rm -f "$mk"
            fail "pr state" "the PR was closed by someone else right before this release's close call (gh says it is already closed): this release did not close it and does not reopen it" ;;
        esac
        orphan_open="$pr"; orphan_closing=""   # GitHub answered this call: the close is this release's, and the exit trap reopens it however the release ends from here
    else
        # the call can have closed the PR and still errored (a timeout after the fact), and GitHub can show the close a moment late: asked up to three times. orphan_closing stays set through the reads: a
        # release that ends during them cannot tell what its call did either, and the exit trap says so
        now="$(orphan_settled "$pr" 10)"
        orphan_closing=""
        case "$now" in
            OPEN\ *) rm -f "$mk"; orphan_erred=1; say "$on_txt $on_be queued with no jobs, but closing the PR to replace it failed (GitHub shows it open); the wait goes on"; return 1 ;;
            # closed after a call that errored, or not known: GitHub does not say whose call closed a PR, so this call's close cannot be told from someone else's, and nothing is reopened (the marker stays for a rerun)
            CLOSED\ *) fail "pr state" "closing PR #$pr to replace $on_txt errored, and the PR is CLOSED: whether this release's call closed it cannot be told (GitHub does not say whose call closed a PR), so it is not reopened. If no one else closed it, reopen it by hand (gh pr reopen $pr), then run release.sh $pr again" ;;
            "") fail "$1" "closing PR #$pr to replace $on_txt errored, and GitHub's answer about its state cannot be read: it is not reopened. If the PR is CLOSED and no one else closed it, reopen it by hand (gh pr reopen $pr), then run release.sh $pr again" ;;
            *) rm -f "$mk"; fail "pr state" "closing the PR to replace $on_txt errored, and the PR is ${now%% *}: nothing is reopened" ;;
        esac
    fi
    orphan_said "$ids" "closing and reopening PR #$pr on the same head ${headsha:0:7}"
    orphan_reopen "$pr" && return 0
    orphan_open=""   # the four tries are done and the message says how to reopen it; the marker stays for a rerun
    fail "$1" "$on_txt $on_has been queued with no jobs, the PR was closed to replace $([ "$on_has" = has ] && echo it || echo them), but it cannot be reopened: PR #$pr is CLOSED (reopen it by hand: gh pr reopen $pr, then run release.sh $pr again)"
}
wait_pr_checks() {   # $1 = the step a failure is named for (checks: the first wait; pr tests: the wait on an updated head), $2 = quiet|progress, $3 = what the log says on a pass. Waits up to WAIT_CHECKS, polled every POLL_PR s (60)
    local step="$1" mode="$2" okmsg="$3" waited=0 checks verdict ci_line going orph_at=-1 orph_n=0
    while :; do
      # salamander's CI-run poller lists a run of this head still going: nothing to ask GitHub this cycle, the wait goes on exactly as a pending check would make it. Only "still going" comes from
      # the file; a finished run, none listed, no file, a stale or unreadable one, or no salamander all fall to the GitHub read below, which alone gives a pass or a fail.
      going=0
      if ci_line="$(ci_going "$headsha" any)"; then
        checks="[]"; verdict=pending; going=1
        [ $((waited % 300)) -ne 0 ] || say "checks on ${headsha:0:7}: ${ci_line#* * }; waiting on the ci-runs file, no GitHub call"
      else
        # shared for GH_TTL s, keyed by the head too (an updated head is a new answer). gh's "no checks reported" (it exits 1 then) is an answer: no check yet, as when every run of the head is queued with no jobs;
        # any other failure is no answer (unread below): the wait goes on as for a pending check, and no orphan look comes of it
        if checks="$(gh_cached "$headsha" pr checks "$pr" --repo "$REPO" --json name,bucket 2>&1)"; then :
        elif [[ "${checks,,}" == *"no checks reported"* ]]; then checks="[]"
        else checks=""; fi
        # a failed or cancelled check fails at once (whichever it is); a pass needs the tests job (NEED): the required check, without which GitHub refuses the enqueue whatever the other checks say
        # (a quick check alone must not read as a pass on a new head, and a tests run queued with no jobs reports no check at all)
        verdict="$(echo "$checks" | NEED="$TESTS_CHECK" python3 -c '
import json,os,sys
try:
    cs=json.load(sys.stdin); assert isinstance(cs, list) and all(isinstance(c, dict) for c in cs)
except Exception: print("unread"); sys.exit()   # the read failed, or its answer is not the rows
if not cs: print("none"); sys.exit()   # nothing reported yet
b={c["bucket"] for c in cs}
if "fail" in b or "cancel" in b: print("fail"); sys.exit()
if os.environ.get("NEED") and os.environ["NEED"] not in {c["name"] for c in cs}: print("none"); sys.exit()   # the tests job not yet among the checks
print("pending" if "pending" in b else "pass")')"
        # gh pr checks can still be reading the old head for a moment after an update: the tests job's run on this very commit must have passed (the check-runs of the commit)
        if [ "$verdict" = pass ] && [ "$mode" = progress ] && ! tests_on_head; then verdict=pending; fi
      fi
        case "$verdict" in
            pass) say "$okmsg"; return 0 ;;
            none) [ "$mode" = progress ] || [ $((waited % 300)) -ne 0 ] || say "no $TESTS_CHECK check reported yet" ;;   # every 5 min, as the other lines of a wait (a run held for hours would write it every cycle)
            unread) [ "$mode" = progress ] || [ $((waited % 300)) -ne 0 ] || say "the checks of ${headsha:0:7} cannot be read this cycle (gh pr checks failed); the wait goes on" ;;
            fail) fail "$step" "a check failed: $(echo "$checks" | python3 -c 'import json,sys; print(", ".join(c["name"]+"="+c["bucket"] for c in json.load(sys.stdin) if c["bucket"] in ("fail","cancel")))')" ;;
        esac
        # --status shows the log's tail: while the wait goes on the newest line says what is waited for, at most 5 min old
        [ "$mode" != progress ] || [ $((waited % 300)) -ne 0 ] || say "waiting for the PR's tests on ${headsha:0:7} ($(case "$verdict" in none) echo "not reported yet" ;; unread) echo "not read this cycle" ;; *) echo "$verdict" ;; esac)); $((waited/60)) min of up to $((WAIT_CHECKS/60))"
        # a run of this head queued with no jobs for ORPHAN_QUEUED s never starts: the PR is closed and reopened for a new run, once per step; the wait clock restarts once with it. Looked for at the start and then every 5 min,
        # on a cycle whose checks read GitHub answered (the wait has not passed: the tests job is missing or a check pending; a read that failed says nothing about now, and no write comes of it); never while the
        # poller shows a newest run going (that run would be cancelled; the cycle makes no GitHub call)
        if [ $going = 0 ] && [ "$verdict" != unread ] && { [ $orph_at -lt 0 ] || [ $((waited - orph_at)) -ge 300 ]; }; then
            orph_at=$waited
            if orphan_pr "$step" "$orph_n"; then orph_n=1; waited=0; orph_at=0; sleep "$POLL_PR"; continue; fi
        fi
        [ $waited -lt $WAIT_CHECKS ] || fail "$step" "still pending after $((WAIT_CHECKS/60)) min"
        sleep "$POLL_PR"; waited=$((waited+POLL_PR))
    done
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
    local m="$verified" now good rg rsha="${mg_rsha:-$verified}" why_not="" recyc covered="" removed="" units="" out rc byhand b bs=""
    case "$recycle:$rc_note" in
        --recycle:*"recycle NOT marked"*) recyc="no recycle was flagged (it could not be asked for)" ;;
        --recycle:*) recyc="a recycle was already flagged for this PR's items before the failure; it delivered files that are now rolled back" ;;
        *) recyc="no recycle was flagged" ;;
    esac
    [ -z "${recovered:-}" ] || recyc="whether a recycle was flagged for this PR is not known (the release process that deployed it ended before main's run was read), nor whether a notice was sent"
    [ -z "${NOTICE_SENT:-}" ] || recyc="$recyc; a notice about this release had already gone out, and a rollback does not take it back"
    q_pause_now "main's tests"   # before the deploy lock is taken, and so before it is let go: a queued release waiting on the lock must find the pause when it gets it
    read_good   # only for the words of the by-hand command; the record is read again under the lock
    byhand="by hand, in $HERE: flock $LOCK_FILE env DEPLOY_ROLLBACK=1 DEPLOY_TO=${good:-<the last good commit, in $LAST_GOOD>} ./deploy.sh (deploy.sh refuses a rollback unless the lock is held)"
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
    if [ -n "$good" ]; then   # the reset goes to the last good commit: it takes out every release in last-good..live, the ones deployed before this one (their runs still waiting) as well as the ones on top
        local -a others=(); local e
        merges_between "$good" "$now"
        for e in "${merges_arr[@]}"; do [ "${e%% *}" = "$m" ] || others+=("$e"); done
        if [ "${#others[@]}" -gt 0 ]; then
            removed="; the rollback also takes out the other merges between ${good:0:7} and the live checkout (releases deployed before it whose runs were still waiting, and on top of it): $(printf '%s\n' "${others[@]}" | short_merges)"
            # relies on the merge queue's merge method being "merge": each PR then lands as a "Merge pull request #N" commit (squash or rebase would leave no such subject)
            bs="$(printf '%s\n' "${others[@]}" | grep -oE 'Merge pull request #[0-9]+' | grep -oE '[0-9]+' | tr '\n' ' ')"
        fi
    fi
    if [ -n "$bs" ] && [ -n "${prs[*]-}" ]; then local nb="" rb; for rb in $bs; do case " ${prs[*]} " in *" $rb "*) ;; *) nb="$nb$rb " ;; esac; done; bs="$nb"; fi   # a group's own members are not riders ("rolled back with" themselves); $prs is run_group's (unset in a lone release)
    if [ -n "$why_not" ]; then
        exec 9>&-; pending_clear; [ -z "${RB_DONE:-}" ] || : > "$RB_DONE"   # a verdict was reached (not rolled back, and the report says why)
        fail "main's tests" "$mg_why: NOT rolled back, $why_not; deployed at ${m:0:7}$covered · $recyc"
    fi
    # unit and timer files the rolled-back commits added stay installed (a rollback does not disable anything): named in the report
    units="$(git diff --diff-filter=A --name-only "$good" "$now" -- units/ 2>/dev/null | grep -E '\.(service|timer|path|socket)\.in$' | sed -E 's#.*/##; s/\.in$//' | paste -sd, - | sed 's/,/, /g')"
    out="$(deploy_run "$good" rollback 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
    follow_note=""
    if [ -n "$DEPLOY_SSH" ] && [ $rc -eq $FOLLOW_SKIPPED_RC ]; then   # deploy_ssh: the server is rolled back, this checkout could not follow (the queue is paused already, above)
        rc=0; follow_note="; the server is rolled back to ${good:0:7} but this checkout is at $(git rev-parse --short HEAD) and could not follow ($(echo "$out" | tail -1 | sed 's/^ *//')): release.sh queue --resume goes on once it is clean"
    fi
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
    fail "main's tests" "${live_later:+LIVE via a later deploy, }rolled back to ${good:0:7} · $mg_why$covered$removed$units; a rollback does not undo data or state changes the rolled-back commits made; main still holds the failing merge, fix forward or revert it$follow_note · $recyc"
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

# ---- GitHub's merge queue (steps 3 and 3a at the top). release.sh enqueues (the enqueuePullRequest mutation; the plain `gh pr merge` only when the repository has no queue) and only reads the queue's state; it never removes a PR from it (the CLI cannot).
ghq_read() {   # $1 = the PR. Its state and its merge-queue entry in one GraphQL call: sets $gq_state (OPEN | MERGED | CLOSED), $gq_oid (the merge commit, "" until there is one) and $gq_entry ("" when the PR is not in the
               # merge queue, else "<STATE> <position>"), $gq_since (the epoch second GitHub dates the entry to, its enqueuedAt: an entry an earlier release made is older than this release's enqueue call; "" with no entry). 1 when
               # GitHub's answer cannot be read
    local out
    out="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){state mergeCommit{oid} mergeQueueEntry{state position enqueuedAt}}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null)" || return 1
    out="$(echo "$out" | python3 -c '
import datetime, json, sys
try:
    p = json.load(sys.stdin)["data"]["repository"]["pullRequest"]
    e = p.get("mergeQueueEntry") or {}
    pos = e.get("position")
    try: since = int(datetime.datetime.strptime(e["enqueuedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp())
    except Exception: since = "-"
    print(p["state"], (p.get("mergeCommit") or {}).get("oid") or "-", e.get("state") or "-", "-" if pos is None else pos, since)
except Exception: sys.exit(1)' 2>/dev/null)" || return 1
    local es ep; read -r gq_state gq_oid es ep gq_since <<< "$out"
    [ -n "$gq_state" ] || return 1
    [ "$gq_oid" != "-" ] || gq_oid=""
    [ "$gq_since" != "-" ] || gq_since=""
    if [ "$es" = "-" ] || [ -z "$es" ]; then gq_entry=""; else gq_entry="$es position $ep"; fi
}
ghq_reason() {   # $1 = the PR, $2 = the epoch second the enqueue call was made. The reason GitHub gave for the PR's latest removal from the merge queue (the timeline's RemovedFromMergeQueueEvent) dated at or after that second,
                 # into $gq_reason: an older event belongs to an earlier enqueue of the same PR (one mended and enqueued again) and says nothing about this one. 1 when the timeline has no such event yet, or cannot be read
    local out
    out="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){timelineItems(last:10,itemTypes:[REMOVED_FROM_MERGE_QUEUE_EVENT]){nodes{... on RemovedFromMergeQueueEvent{reason createdAt}}}}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null)" || return 1
    # words a log waiter looks for (" FAILED ", " done: ") are softened in what GitHub says
    gq_reason="$(echo "$out" | SINCE="${2:-0}" python3 -c '
import json, os, sys, datetime
since = int(os.environ["SINCE"])
try: nodes = [x for x in json.load(sys.stdin)["data"]["repository"]["pullRequest"]["timelineItems"]["nodes"] if x]
except Exception: sys.exit(1)
def epoch(x):
    try: return int(datetime.datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00")).timestamp())
    except Exception: return -1   # no date, or one that is not read: not known to be after the enqueue
nodes = sorted((n for n in nodes if epoch(n) >= since), key=epoch)
if not nodes: sys.exit(1)
WORDS = {"failed_checks": "the merge group failed its required checks", "merge_conflict": "a merge conflict with main", "manual": "removed from the queue by hand",
         "branch_protection_failure": "branch protection failed for the merge group"}   # the values GitHub gives (lower case); "merged" stays as it is: it is not a failure
raw = " ".join((nodes[-1].get("reason") or "no reason given").split())[:300]
print(WORDS.get(raw.lower(), raw).replace(" FAILED ", " failed ").replace(" done: ", " done "))' 2>/dev/null)" || return 1
}
ghq_target() {   # $1 = the PR. What enqueue_pr needs: $gq_mq (1 when the repository has a merge queue on main, 0 when it has none: the ruleset is off) and $gq_prid (the PR's node id). 1 when GitHub's answer cannot be read
    local out
    out="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){mergeQueue(branch:"main"){id} pullRequest(number:$p){id}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null)" || return 1
    out="$(echo "$out" | python3 -c '
import json, sys
try:
    r = json.load(sys.stdin)["data"]["repository"]
    print(1 if r.get("mergeQueue") else 0, r["pullRequest"]["id"])
except Exception: sys.exit(1)' 2>/dev/null)" || return 1
    read -r gq_mq gq_prid <<< "$out"
    [[ "$gq_mq" =~ ^[01]$ ]] && [ -n "$gq_prid" ] || { gq_mq=""; return 1; }
}
merged_said() {   # $1 = seconds since the enqueue. The PR is MERGED with its merge commit $gq_oid: it is the one to deploy ($mergeoid), and the log says how it got there
    mergeoid="$gq_oid"
    if [ "$via_queue" = 1 ]; then say "merged by the merge queue as ${mergeoid:0:7}, $(($1/60)) min after the enqueue"
    else say "merged as ${mergeoid:0:7} by the plain merge call, not the merge queue (the ruleset is off)"; merge_note="$merge_note; merged without the merge queue (the ruleset is off)"; fi
}
wait_merged() {   # after the enqueue call, in run(): reads the PR until it is MERGED (0, the merge commit in $mergeoid) or has left the merge queue without merging (1, GitHub's reason in $removed_why). A PR closed meanwhile, or still
                  # waiting after QUEUE_WAIT, fails the release. The reads are every POLL_QUEUE s once the entry shows (every 10 s before, for QUEUE_GRACE: GitHub shows a new entry a moment late); one that cannot be read is waited out like
                  # a pending one. Leaving the queue is believed on the second read, 10 s after the first (the entry can vanish a moment before the PR shows merged), and only after the PR was read for MERGED up to three more times,
                  # 10 s apart, and the timeline for the removal (a merged PR is never reported as removed). $via_queue is the enqueue call's (1: the queue took the PR). Runs inside run()
    local t0 now waited said=0 seen=0 absent=0 unread=0 poll=10 tries orph_at=-1 inq oid on_txt on_has on_be
    t0="$(date +%s)"; mergeoid=""; removed_why=""; gq_state=""; gq_oid=""; gq_entry=""
    while :; do
        now="$(date +%s)"; waited=$((now - t0)); inq=0
        if ghq_read "$pr"; then
            unread=0
            case "$gq_state" in
                MERGED)
                    if [[ "$gq_oid" =~ ^[0-9a-f]{7,64}$ ]]; then
                        merged_said "$waited"; return 0
                    fi
                    say "GitHub says the PR is merged but has no merge commit to give yet; reading again" ;;
                CLOSED) fail "pr state" "the PR was closed while it waited for the merge queue" ;;
                *)
                    if [ -n "$gq_entry" ]; then
                        seen=1; absent=0; poll="$POLL_QUEUE"; inq=1
                        [ $((now - said)) -lt 300 ] || { said=$now; say "in the merge queue ($gq_entry): $((waited/60)) min since the enqueue, up to $((QUEUE_WAIT/60)) min; reading it every $POLL_QUEUE s"; }
                    elif [ $seen = 1 ] || [ $waited -ge "$QUEUE_GRACE" ]; then   # it was in the queue, or never showed: not there on this read
                        absent=$((absent+1))
                        if [ $absent -ge 2 ]; then   # and not there, not merged, ten seconds later: it was removed, unless it shows merged on a later read (GitHub can take that long to say so)
                            for tries in 1 2 3; do
                                sleep 10; waited=$(( $(date +%s) - t0 ))
                                if ghq_read "$pr" && [ "$gq_state" = MERGED ] && [[ "$gq_oid" =~ ^[0-9a-f]{7,64}$ ]]; then merged_said "$waited"; return 0; fi
                            done
                            gq_reason=""; for tries in 1 2 3; do ghq_reason "$pr" "$enq_epoch" && break; [ $tries = 3 ] || sleep 10; done
                            if [ "${gq_reason,,}" = merged ]; then   # the timeline's removal event for the merge itself (reason "merged"): not a failure; the PR reads as merged in a moment
                                for tries in 1 2 3 4 5 6; do
                                    sleep 10; waited=$(( $(date +%s) - t0 ))
                                    if ghq_read "$pr" && [ "$gq_state" = MERGED ] && [[ "$gq_oid" =~ ^[0-9a-f]{7,64}$ ]]; then merged_said "$waited"; return 0; fi
                                done
                                gq_reason="the timeline says the PR left the queue because it merged, but GitHub does not show a merged PR with a merge commit"
                            fi
                            if [ -n "${gq_reason:-}" ]; then removed_why="removed from the merge queue: $gq_reason"
                            elif [ $seen = 1 ]; then removed_why="left the merge queue, and GitHub's timeline gives no reason (no removal event)"
                            else fail "merge queue" "the PR did not show in the merge queue within $((QUEUE_GRACE/60)) min of the enqueue call and is not merged (the call said it was accepted)"; fi
                            say "$removed_why"; return 1
                        fi
                        sleep 10; continue
                    fi ;;
            esac
        else
            unread=$((unread+1)); poll="$POLL_QUEUE"   # an answer GitHub did not give (a 403/429 is a wait) is not asked again in 10 s: the slow poll from the first unreadable read on
            [ $((now - said)) -lt 300 ] || { said=$now; say "GitHub's answer about the PR could not be read ($unread read(s) in a row); trying again"; }
        fi
        # the current group's merge_group run of this PR (the newest since its queue entry) queued with no jobs for ORPHAN_QUEUED s never starts, and the PR may not merge from that group. This release does not replace
        # it: taking the PR out of the queue and putting it back needs proof that the removal was this release's own, and GitHub cannot give it (every gh write here is the same account), so a PR someone else took out
        # meanwhile could be put back, merged and deployed. It fails at once, the PR left in the queue, saying what to do by hand. Looked for every 5 min, only on a read that showed the PR in the queue this cycle (a read
        # that failed says nothing about now), once the entry is that old (GitHub's enqueuedAt: a rerun finds the entry an earlier release made; the enqueue call's second when the entry has none)
        if [ $inq = 1 ] && [ $((now - ${gq_since:-$t0})) -ge "$ORPHAN_QUEUED" ] && { [ $orph_at -lt 0 ] || [ $((waited - orph_at)) -ge 300 ]; }; then
            orph_at=$waited
            oid="$(orphan_scan queue | tr '\n' ' ')"; oid="${oid% }"
            if [ -n "$oid" ]; then
                orphan_names "$oid"
                fail "merge queue" "$on_txt of PR #$pr's merge group $on_has been queued for more than $((ORPHAN_QUEUED/60)) min with no jobs: GitHub never starts such a run and it cannot be cancelled or rerun, so the PR may not merge from this group (GitHub can still build a new one). This release does not take the PR out of the merge queue (GitHub cannot tell it whether a removal was its own or someone else's): the PR is still in the merge queue ($gq_entry), and if it merges from there this release does not deploy it. To replace the run, remove PR #$pr from the merge queue on GitHub, then run release.sh $pr again (it enqueues the PR again); if the PR merges from the queue meanwhile, run release.sh $pr again (it deploys a merged PR)"
            fi
        fi
        [ $waited -lt "$QUEUE_WAIT" ] || fail "merge queue" "still $([ -n "$gq_entry" ] && echo "in the merge queue ($gq_entry)" || echo "not merged") $((waited/60)) min after the enqueue, which is as long as this release waits; the PR may still merge later: rerun release.sh $pr to carry on from the merge (the next release's deploy carries it too)"
        sleep "$poll"
    done
}

# ---- the salamander merge queue (THE TWO MERGE QUEUES at the top): the host file's mode, and what mode on needs. A host file that is absent, says off, says shadow (no longer run) or does not read is GitHub's merge queue.
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
mq_on_check() {   # mode on, both paths ($1 = a PR of this release, for the read of GitHub's merge queue): 0 when the host file names the deploy lock this script takes (deploy_lock = $LOCK_FILE) and GitHub's own merge queue on main is
                  # off; else 1 with $mq_why. The queue's merge push takes THAT file, without waiting, and this script holds it from its deploy gate to the end of its deploy, so the lock keeps the queue's push out of a release's DEPLOY
                  # (and a group deploy from overlapping a push); it does not cover a lone PR's merge, which run() makes before it takes the lock (the marker check and the GitHub-queue check below are what keep the two queues off one PR).
                  # GitHub's queue on as well would be a second queue merging into main beside the salamander one, so mode on refuses it (the ruleset's queue is turned off first, or the mode set to off)
    local dl; dl="$(mq_host_key deploy_lock)"
    if [ -z "$dl" ]; then mq_why="the host file ${XDG_CONFIG_HOME:-~/.config}/mergequeue/${REPO//\//__}.toml has no deploy_lock: in mode on it must say deploy_lock = \"$LOCK_FILE\", the lock this script takes, or the queue could push to main while a release deploys; nothing was merged"; return 1; fi
    [ "$(realpath -m "$dl" 2>/dev/null)" = "$(realpath -m "$LOCK_FILE" 2>/dev/null)" ] || { mq_why="the host file's deploy_lock is $dl, not the lock this script takes ($LOCK_FILE): the queue and the releases would not exclude each other; set deploy_lock = \"$LOCK_FILE\"; nothing was merged"; return 1; }
    [ -n "${1:-}" ] || return 0
    local tries; gq_mq=""; gq_prid=""
    for tries in 1 2 3; do ghq_target "$1" && break; [ $tries = 3 ] || sleep 10; done
    [ -n "$gq_mq" ] || { mq_why="GitHub's answer about the repository's merge queue cannot be read, so it is not known whether GitHub's queue is on as well as the salamander one; nothing was merged"; return 1; }
    [ "$gq_mq" != 1 ] || { mq_why="GitHub's merge queue is on for main (the ruleset's queue) as well as the host file's mode on: two queues would merge into main. Turn the ruleset's queue off, or set the host file's mode to off; nothing was merged"; return 1; }
}
mq_marker_lead() { sed -n 's/.*led by PR #\([0-9][0-9]*\).*/\1/p' "$MQ_HANDED/pr-$1" 2>/dev/null | head -n 1; }   # $1 = a PR with a marker: the lead of the group release that wrote it
mq_group_running() {   # prints the lead of a group release that is running: a live stackshot-release-<lead> named in any marker. The queue's started mark of the lead goes when the queue ejects it (member_fail), the marker of the members stays
    local f ql
    for f in "$MQ_HANDED"/pr-*; do
        [ -e "$f" ] || continue
        ql="$(mq_marker_lead "${f##*/pr-}")"
        if [ -n "$ql" ] && q_alive "$ql"; then printf '%s\n' "$ql"; return 0; fi
    done
    return 1
}
mqh_set() { mkdir -p "$MQ_HANDED" && printf '%s\n' "$(date -u +%FT%TZ) handed to the merge queue by the group release led by PR #${lead:-?}" > "$MQ_HANDED/pr-$1"; }
mqh_clear() { rm -f "$MQ_HANDED/pr-$1"; }
mq_plain() {   # stdin to stdout: the words a waiter on a release log looks for (` FAILED `, ` done: `) made harmless, so a PR title in a queue line never reads as a release's result
    sed -e 's/ FAILED/ failed/g' -e 's/ done:/ done/g'
}

# THE RELEASE QUEUE. Several PRs have to reach GitHub's merge queue together to be tested together, and each release then waits for the merge queue, the deploy lock and main's full run. `release.sh queue N [N...]` records PR numbers
# in order in $QUEUE, and starts the plain `release.sh <pr>` (its own unit) of every waiting one at once, START_MAX (4) running at a time: a PR counts as running from its start until its release is deployed, and a PR
# stays in $QUEUE until then (a killed release is still listed, and --resume starts it again). $QUEUE.started names the PRs whose release the queue started. Each release that reaches "deployed", the point after which it only
# waits on main's run, leaves the queue and starts the next waiting PRs up to the cap. A release that fails BEFORE its merge (checks failed, a conflict, a closed PR, removed from the merge queue, a lock not had) is reported as ever and skipped: it leaves the
# queue and starts the next one at its failure, so the queue goes on. A release the queue started that fails AFTER its merge (main's run failed: merged and not deployed, or rolled back after a deploy at the merge; a deploy that failed;
# the deploy lock not had for the deploy) PAUSES the queue ($QUEUE.paused): no new release starts, a release the queue had started already but not enqueued stops before its enqueue ("queue paused") and stays first in the queue (a PR
# already in GitHub's merge queue is not stopped: the CLI cannot remove it, and its release goes on to the deploy gate), the riders a rollback took out stay merged on main (named in the report and the log, not queued again),
# the existing rollback and report run as they always did, and `release.sh queue --resume` goes on once main is fixed. A plain `release.sh N` writes no pause. A run of main that could
# not be read in time is no failure: no pause (the release leaves the queue, which goes on). The deploy lock serializes the deploys of the releases that run together.
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
q_started_list() { grep -E '^[0-9]+$' "$QUEUE.started" 2>/dev/null; return 0; }   # the PRs whose release the queue started and has not handed off yet
q_is_started() { [ -n "${1:-}" ] && q_started_list | grep -x "$1" >/dev/null; }   # grep reads the list to the end (not -q): under pipefail a grep that stops at its match could end the writer with SIGPIPE
q_mark_started() { echo "$1" >> "$QUEUE.started"; }
q_unmark_started() {   # PR $1 is not one the queue is running (any more)
    [ -f "$QUEUE.started" ] || return 0
    local t="$QUEUE.started.$$"; grep -vx "$1" "$QUEUE.started" > "$t"
    if [ -s "$t" ]; then mv -f "$t" "$QUEUE.started"; else rm -f "$t" "$QUEUE.started"; fi
    return 0
}
q_started_pr() {   # 0 when the queue started PR $1: the started file names it, or the queue's log says it started it (the mark goes at "deployed"; a recovered rollback of the earlier one still belongs to the queue)
    [ -n "${1:-}" ] || return 1
    q_is_started "$1" && return 0
    grep -qF "started PR #$1 (" "$QUEUE.log" 2>/dev/null
}
q_alive() { [ -n "${1:-}" ] && systemctl --user is-active --quiet "stackshot-release-$1.service" 2>/dev/null 4>&- 6>&- 7>&- 8>&- 9>&-; }   # the release unit of PR $1 is running
q_in_queue() { local e; q_read; for e in "${q[@]}"; do [ "$e" != "${1:-}" ] || return 0; done; return 1; }
q_unqueue() {   # under the lock: PR $1 out of the queue file, and no longer one the queue is running
    local e kept=(); q_read
    for e in "${q[@]}"; do [ "$e" = "$1" ] || kept+=("$e"); done
    q=("${kept[@]}"); q_write || return 1; q_unmark_started "$1"
}
q_start_next_on() {   # under the lock, mode on (THE TWO MERGE QUEUES): the release queue starts ONE thing at a time, as it did when the salamander merge queue was its only one, and routes by COUNT at this moment: two or more waiting
                      # (at most MQ_HANDOFF_MAX) go to the salamander merge queue as one group (`release.sh --group`, its unit stackshot-release-<lead>, the lead marked started), one waiting is released alone (`release.sh N`).
                      # Nothing starts while a release the queue started is running; it starts the next one when it is deployed. One that cannot be started is logged and taken out. $1 = who asks (for the log)
    local n out lead cmdword; local -a waiting=() gq=() cmd=()
    q_read
    for n in "${q[@]}"; do if q_is_started "$n" && ! q_alive "$n"; then say "release queue: PR #$n was started by the queue but its release is not running (killed?): nothing else starts; release.sh queue --resume starts it again"; return 0; fi; done
    for n in "${q[@]}"; do if q_is_started "$n" && q_alive "$n"; then say "release queue: PR #$n (started by the queue) is running; it starts the next one when it is deployed (the salamander merge queue is on: one at a time)"; return 0; fi; done
    if lead="$(mq_group_running)"; then say "release queue: the group release led by PR #$lead is running (its PRs are held by the salamander merge queue): nothing else starts; the queue goes on when it ends"; return 0; fi   # its lead may be out of the queue and unmarked already (the queue ejected it), its members are not
    while :; do
        q_read; waiting=()
        for n in "${q[@]}"; do q_is_started "$n" || waiting+=("$n"); done
        if [ "${#waiting[@]}" -eq 0 ]; then say "release queue: nothing to start (${#q[@]} listed, all started already)"; return 0; fi
        lead="${waiting[0]}"
        if [ "${#waiting[@]}" -ge 2 ]; then gq=("${waiting[@]:0:$MQ_HANDOFF_MAX}"); cmd=(--group "${gq[@]}"); else gq=("$lead"); cmd=("$lead"); fi
        q_mark_started "$lead"   # before the start: the release reads it at its start to know that the queue started it
        if out="$("$HERE/release.sh" "${cmd[@]}" 2>&1 </dev/null 4>&- 6>&- 7>&- 8>&- 9>&-)" || [[ "$out" == *"is already running"* ]]; then
            if [ "${#gq[@]}" -ge 2 ]; then
                q_log "started PRs ${gq[*]} as one group through the salamander merge queue ($1); ${#q[@]} in the queue"
                say "release queue: ${#waiting[@]} PRs are waiting (${waiting[*]}) and the salamander merge queue is on: started the group release of ${gq[*]}, led by PR #$lead$([ "${#waiting[@]}" -le "${#gq[@]}" ] || echo "; the others (${waiting[*]:${#gq[@]}}) wait for the next hand-off")"
            else
                q_log "started PR #$lead ($1); ${#q[@]} in the queue"
                say "release queue: started the release of PR #$lead (the salamander merge queue is on and one PR is waiting: released alone)"
            fi
            return 0
        fi
        q_unmark_started "$lead"; q_unqueue "$lead" || return 1   # a start that failed: the lead is skipped and the count is taken again
        q_log "could not start $([ "${#gq[@]}" -ge 2 ] && echo "the group led by ")PR #$lead ($1): $(echo "$out" | tail -1)"; say "release queue: could not start the release led by PR #$lead ($(echo "$out" | tail -1)); PR #$lead skipped"
    done
}
q_start_next() {   # under the lock: the release of every waiting PR (not started yet), in order, until START_MAX queued releases are running. A PR stays in the queue file until it is deployed. One that cannot be
                   # started is logged and taken out. $1 = who asks (for the log)
    local n out live=0 started=0 s; local -a gone=()
    if [ -f "$QUEUE.paused" ]; then say "the release queue is paused ($(head -1 "$QUEUE.paused")): no release started; release.sh queue --resume goes on"; return 0; fi
    q_read
    if [ "${#q[@]}" -eq 0 ]; then rm -f "$QUEUE.started"; say "the release queue is empty: nothing more to start"; return 0; fi
    if [ "$(mq_host_mode)" = on ]; then q_start_next_on "$1"; return $?; fi   # the salamander merge queue: one thing at a time, by count (THE TWO MERGE QUEUES at the top)
    for n in "${q[@]}"; do if q_is_started "$n" && q_alive "$n"; then live=$((live+1)); fi; done
    for n in "${q[@]}"; do
        q_is_started "$n" && continue   # started already (running, or killed: --resume clears the mark and starts it again)
        if [ -e "$MQ_HANDED/pr-$n" ]; then q_log "PR #$n not started ($1): the salamander merge queue holds it (marker $MQ_HANDED/pr-$n)"; say "release queue: PR #$n is held by the salamander merge queue (a group release handed it over, whatever the host file says now): not started alone; release.sh queue --drop $n takes it out of this queue"; continue; fi
        [ "$live" -lt "$START_MAX" ] || break
        q_mark_started "$n"   # before the start: the release reads it at its start to know that the queue started it
        if out="$("$HERE/release.sh" "$n" 2>&1 </dev/null 4>&- 6>&- 7>&- 8>&- 9>&-)" || [[ "$out" == *"is already running"* ]]; then   # its own unit (systemd-run): it outlives this release
            live=$((live+1)); started=$((started+1))
            q_log "started PR #$n ($1); ${#q[@]} in the queue"
            say "release queue: started the release of PR #$n ($live of at most $START_MAX running, ${#q[@]} queued)"
        else
            q_unmark_started "$n"; gone+=("$n")
            q_log "could not start PR #$n ($1): $(echo "$out" | tail -1)"; say "release queue: could not start the release of PR #$n ($(echo "$out" | tail -1)); skipped"
        fi
    done
    for n in "${gone[@]}"; do q_unqueue "$n" || return 1; done
    if [ $started -eq 0 ]; then say "release queue: nothing to start ($live of at most $START_MAX running; ${#q[@]} listed)"; fi
    return 0
}
q_handoff() {   # $1 = why (deployed | skipped at <step>): this release leaves the queue file and the waiting PRs start up to the cap. Only a PR that is in the queue file: a release started by hand starts nothing
    [ -f "$QUEUE" ] || return 0
    q_locked q_handoff_locked "$1"
}
q_handoff_locked() { q_in_queue "$pr" || return 0; q_unqueue "$pr" || return 1; q_start_next "PR #$pr $1"; }   # read again under the lock: another release may have taken it out meanwhile
q_pause_file() {   # under the lock: the pause file, naming the PR and the step
    printf '%s\n' "PR #$pr failed at $1 after its merge, $(date -u +%FT%TZ)" > "$QUEUE.paused"
}
q_pause_now() {   # $1 = the step. Called by rollback() before the deploy lock is taken, so the pause is on disk before the lock is let go and a queued release that waits for the lock finds it
                  # when it gets the lock (fail() writes it only after the lock was let go, and that release would deploy onto a main that is red). Only a queue-started release after its merge; q_pause rewrites it later
    [ "${qstart:-0}" = 1 ] && [ "${q_fail:-}" = pause ] || return 0
    q_locked q_pause_file "$1"; q_log "paused: PR #$pr failed at $1 after its merge (written before the deploy lock was let go)"
}
q_pause() {   # $1 = the step, $2 = the PRs the rollback took out with this one (oldest first). A release failed after its merge: it leaves the queue file and no new release starts until release.sh queue --resume.
              # The riders a rollback took out are merged and stay on main: they are not queued again (release.sh N on a merged PR fails at "pr state"); the next release's deploy carries them once main is green. Logged here
    local r
    q_pause_file "$1"; q_log "paused: PR #$pr failed at $1 after its merge"
    q_unqueue "$pr"
    for r in ${2:-}; do q_log "PR $r was rolled back with PR #$pr: merged and not live, not queued again; it goes live with the next release once main is fixed"; done
}
q_held() {   # under the lock: a release the queue started was stopped by the pause before its enqueue; it stays first in the queue, and is not running any more
    local e dup=0; q_read
    for e in "${q[@]}"; do [ "$e" != "$pr" ] || dup=1; done
    [ $dup = 1 ] || { q=("$pr" "${q[@]}"); q_write; }
    q_unmark_started "$pr"
    q_log "PR #$pr stopped by the pause before its merge: first in the queue"
}
queue_after_fail() {   # fail(): what the failure does to the queue, by $q_fail (skip: before the merge; held: stopped by the pause before the enqueue; pause: after the merge; merged: stopped by a pause already there after the merge; none). Sets $q_note for the report
    q_note=""
    case "${q_fail:-none}" in
        skip) q_in_queue "$pr" || return 0
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
        merged) [ $qstart = 1 ] || return 0   # stopped by a pause that was there already (q_paused_deploy_stop): the PR is merged, so it leaves the queue; the pause is the earlier failure's and is left as it is
              q_locked q_leave_merged; say "release queue: PR #$pr is merged and was not deployed because the queue is paused; release.sh queue --resume once main is fixed"
              q_note="; merged and not deployed because the release queue is paused: release.sh queue --resume once main is fixed" ;;
        none) [ $qstart = 1 ] || return 0   # a main run that was not read is no failure of the code: not paused. The PR is merged, so it leaves the queue and the waiting ones start
              q_handoff "ended with main's run not read"; q_note="; the release queue goes on (main's run not being read is not a failure of the code)" ;;
    esac
}
q_paused_deploy_stop() {   # in run(), under the deploy lock, before a deploy: a pause that came while this release waited (for the lock, or for main's tests) stops a release the queue started. A rollback writes it before it takes the lock
                           # (q_pause_now), so a late member of the same merge group finds it here and does not deploy onto a main that is red. The PR is merged and not deployed: it leaves the queue (the pause stays) and the next release's deploy carries it
    [ "$qstart" = 1 ] && [ -f "$QUEUE.paused" ] || return 0
    exec 9>&-; q_fail=merged
    fail "queue paused" "the release queue was paused ($(head -1 "$QUEUE.paused")) while this release waited to deploy: the PR is merged and not deployed; the next release's deploy carries it once main is fixed, or ./deploy.sh by hand"
}
q_leave_merged() { q_in_queue "$pr" || return 0; q_unqueue "$pr"; q_log "PR #$pr is merged and was not deployed: the queue is paused; it left the queue"; }
q_paused_stop() {   # in run(), before the PR is enqueued: a pause stops a release the queue had started already (it was started before the pause). It fails as a pre-merge skip, reason "queue paused", no hand-off
    [ "$qstart" = 1 ] && [ -f "$QUEUE.paused" ] || return 0
    q_fail=held
    fail "queue paused" "the release queue is paused ($(head -1 "$QUEUE.paused")): this release was started by the queue before the pause and nothing was merged; it is first in the queue again, release.sh queue --resume starts it once main is fixed"
}
queue_cmd() {   # release.sh queue N [N...] | --list | --drop N | --resume
    local n s st
    case "${1:-}" in
        --list)
            q_read
            if [ "${#q[@]}" -eq 0 ]; then echo "release queue: empty"; else echo "release queue, in order: ${q[*]}"; fi
            [ ! -f "$QUEUE.paused" ] || echo "paused: $(head -1 "$QUEUE.paused") (release.sh queue --resume)"
            if hold_read; then
                if [ "$hd_state" = active ]; then echo "on hold: releases are $(hold_line) (release.sh hold --end)"
                else echo "no hold now: the one by $hd_by ended at $(hold_end_at) ($hd_why)"; fi
            fi
            for n in "${q[@]}"; do
                if ! q_is_started "$n"; then st="waiting"
                elif q_alive "$n"; then st="running (its release starts the next waiting one when it is deployed)"
                else st="started by the queue but its release is not running (killed?): release.sh queue --resume starts it again"; fi
                echo "  PR #$n: $st"
            done
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
    hold_note
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
    sys.exit(1)' "$n" 2>&1 6>&- 7>&- 8>&- 9>&-)"; rc=$?
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
    else q_start_next "release.sh queue"; fi
    q_read; echo "release queue, in order: ${q[*]:-(empty)}"
}
queue_drop_locked() {
    local e kept=() hit=0
    q_read
    for e in "${q[@]}"; do if [ "$e" = "$1" ]; then hit=1; else kept+=("$e"); fi; done
    [ $hit = 1 ] || { echo "PR #$1 is not in the release queue"; return 1; }
    if [ -e "$MQ_HANDED/pr-$1" ]; then   # mode on: a group release handed it to salamander's queue; taking it out of this file would not take it out of that one
        local ql st act; ql="$(sed -n 's/.*led by PR #\([0-9][0-9]*\).*/\1/p' "$MQ_HANDED/pr-$1" 2>/dev/null | head -n 1)"
        if q_alive "$ql"; then act=live   # its group release is running: the marker is its own
        elif [ "$(mq_host_mode)" != on ] && [[ "$(mq_host_mode)" != bad:* ]]; then act=gone   # the host file does not say on (any more): nothing reads markers then. A file that does not read (bad: ...) says nothing: mq status decides, and a status that cannot be read refuses
        else
            st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 4>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
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
    q=("${kept[@]}"); q_write || return 1; q_unmark_started "$1"; q_log "dropped PR #$1"
    echo "dropped PR #$1; release queue, in order: ${q[*]:-(empty)}"
}
queue_resume_locked() {
    local s
    if [ -f "$QUEUE.paused" ]; then q_log "resumed (was: $(head -1 "$QUEUE.paused"))"; echo "resumed (it was paused: $(head -1 "$QUEUE.paused"))"; rm -f "$QUEUE.paused"; fi
    q_read
    for s in $(q_started_list); do   # started by the queue, listed still, and not running: killed. It starts again
        if q_in_queue "$s" && ! q_alive "$s"; then q_unmark_started "$s"; q_log "PR #$s was started by the queue but its release is not running: it starts again"; echo "PR #$s was started but its release is not running: it starts again"; fi
    done
    q_start_next "release.sh queue --resume"
}

# THE TWO MERGE QUEUES, MODE ON: the release queue (above) routes by COUNT at the moment it would start a release. One PR waiting takes run() (see mq_on_check and the marker check there). Two or more waiting (at most 4, release.sh's own number) go to
# the salamander merge queue together: `release.sh --group N N...` (unit stackshot-release-<first>; the lead is marked started in $QUEUE.started, the others are not) runs run_group. It hands them all to the queue in one `salamander mq add`, waits for each
# (`salamander mq wait N`: exit 0 merged, 1 ejected/failed/dropped with the reason, 2 gave up, not in the line or blocked, 3 tested in shadow, 4 replay), then deploys what the queue merged ONCE, through the same steps as a release through GitHub's
# queue: the deploy lock, deploy_gate (the salamander queue tested exactly the tree it merged), ./deploy.sh pinned to the merge, the session pick, one report and one `done:` line per PR, then main's run for the merge with the rollback and the pause.
# HOW THE TWO PATHS EXCLUDE EACH OTHER. (0) Mode on is refused while GitHub's own merge queue is on for main too (mq_on_check): two queues would merge into main. (1) The host file's deploy_lock is THIS script's deploy lock (mq_on_check refuses mode on otherwise): the queue's merge push takes it without waiting (busy: tried again next tick), and a release holds it from
# its deploy gate to the end of its deploy, so the queue never pushes while a release deploys, and a group deploy (also under the lock) never overlaps a push (a lone PR's merge is made before the lock is taken: the marker check keeps the queues off one PR). The release queue counts a group release as running while any marker names a live stackshot-release-<lead> (the queue's ejecting the lead clears its started mark). (2) The release queue starts one thing at a time in mode on: a group, or a lone release.
# (3) A PR is never in both: a group release writes a marker per PR (MQ_HANDED/pr-N) before `mq add` and removes it once the queue no longer holds the PR (settled, dropped by `mq drop`, or "not in the line"), and run() in EVERY mode refuses a PR with a
# marker ("mq line": a host file changed mid-group does not take the PR out of the salamander queue, and the release queue's plain start skips it too), at its start and again just before it is enqueued (a hand-run release can wait for its checks while a group takes the PR); the group release in turn refuses a PR whose own release unit (stackshot-release-N) is running, and
# `queue --drop` of a PR the queue holds says so. A hand-off is at most MQ_HANDOFF_MAX PRs (4, release.sh's own number: the chain tests those entries at once and merges them one PR at a time, so a larger hand-off would leave the first merges
# undeployed while the later ones wait); the rest stay in release.sh's queue for the next hand-off. Design choices: the deploy waits for EVERY PR of the group to settle (a PR behind a failure is rebuilt and tested again; the chain merges one PR a push in
# line order, and the last merge contains the earlier ones, so one deploy of it covers all); a failed or ejected PR is reported as a failed release of that PR with the queue's reason and the rest still go out; a PR that is merged on GitHub already
# (an earlier run of the group was killed after the queue merged it) is read before `mq add`, deployed with the group and not handed over again. An mq error, a timeout (RELEASE_MQ_WAIT_CAP, 5 h), a queue paused or blocked, a `salamander mq:` message,
# a pause of release.sh's own queue while the group waits: the PRs still open are dropped from the queue (best effort) and reported FAILED, release.sh's queue is PAUSED, and what the queue merged BEFORE is deployed all the same (never reported FAILED,
# but "merged, not live" where it cannot be deployed: only the unresolved PRs are FAILED, and they stay first in release.sh's queue); before any merge the PRs stay first in the queue so --resume tries them again. Where a merged PR cannot be deployed
# (main cannot be fetched, its commit is unknown, the deploy fails) it is reported "merged, not live". A forced --recycle/--no-recycle does not exist for a group: its session pick is made from the files of all its PRs.
qg_pause_locked() {   # under the lock: the pause file, the merged PRs out of the queue file (the others stay, first), the group's lead no longer one the queue is running. $1 = the step, $2 = held|pause
    local e m kept=() gone; q_read
    [ -f "$QUEUE.paused" ] || printf '%s\n' "group of PRs ${prs[*]} (led by #$lead): $1 $([ "$2" = pause ] && echo "after the merge queue's merge" || echo "before anything was merged"), $(date -u +%FT%TZ)" > "$QUEUE.paused"   # a pause that is there already keeps its own reason
    for e in "${q[@]}"; do gone=0; for m in "${merged_prs[@]}" ${lost_prs[@]+"${lost_prs[@]}"}; do [ "$e" != "$m" ] || gone=1; done; [ $gone = 1 ] || kept+=("$e"); done
    q=("${kept[@]}"); q_write
    q_unmark_started "$lead"
    q_log "paused: the group of PRs ${prs[*]} failed at $1 ($2); merged and out of the queue: ${merged_prs[*]:-none}"
}
qg_held_locked() {   # under the lock: the queue is paused already; the group's lead is not running any more, its PRs stay first in the queue
    q_unmark_started "$lead"
    q_log "the group of PRs ${prs[*]} stopped by the pause before any merge: still first in the queue"
}
qg_after_fail() {   # fail() of a group release: what the failure does to the release queue, by $q_fail (held: before any merge, pause it and keep the PRs; hold: it is paused already; pause: after a merge; none: no failure of the code). Sets $q_note
    q_note=""
    [ "$qstart" = 1 ] || return 0   # only a group the release queue started touches it (the started mark names the lead); one run by hand pauses nothing
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
qg_handoff_locked() {   # under the lock: the group's PRs (those the queue could not merge stay, first) leave the queue file, the lead is not running any more, and the next waiting ones start
    if q_in_queue "$lead" && ! q_is_started "$lead"; then return 0; fi   # read again under the lock: the lead is still queued but no longer marked, so a resume took the group over meanwhile (a lead that member_fail already took out of the queue is still ours)
    local m h; for m in "${prs[@]}"; do for h in ${held_prs[@]+"${held_prs[@]}"}; do [ "$h" != "$m" ] || continue 2; done; q_unqueue "$m" || return 1; done
    q_unmark_started "$lead"; q_start_next "the group of PRs ${prs[*]} $1"
}
qg_handoff() {   # $1 = why: the group's PRs leave the queue file and the next waiting ones start, when the release queue started this group
    [ "$qstart" = 1 ] || return 0
    [ -f "$QUEUE" ] || return 0
    q_locked qg_handoff_locked "$1"
}
run_group() {   # $@ = the PRs of one group, in queue order (two or more, at most MQ_HANDOFF_MAX). See THE MERGE QUEUE, ON above
    local -a prs=("$@") live_prs=("$@") merged_prs=() shas=() held_prs=() addprs=() lost_prs=()
    local ar unk_why=""; local -a unk=()
    local lead="$1" pr="$1" glog="$LOGDIR/group-$1.log" m recycle="" rc_note="" audit_note="" verified="" mg_notlive="" q_fail=held q_note="" q_riders="" qstart=0 out rc title
    local gfailed=0 ROLLED_MARK="$LOGDIR/pr-$1.rolledback" names="" sha restarted fast=0 live_now=0 gate_why="" nonq_why="" good="" mergeoid="" abort_step="" abort_why="" pre_note="" premerged="" k unn="" live_names="" live_pr="" live_is=""; local -a keep=()
    for m in "${prs[@]}"; do names="${names:+$names }#$m"; done
    exec > >(tee -a "$glog") 2>&1
    gsay() { local l k; l="$(say "$@")"; echo "$l"; for k in "${prs[@]}"; do printf '%s\n' "$l" | mq_plain >> "$LOGDIR/pr-$k.log"; done; }   # progress, into the group log and (the words a waiter looks for made harmless) every PR's own log
    mn() { local k r=""; for k in "${merged_prs[@]}"; do r="${r:+$r }#$k"; done; printf '%s' "$r"; }   # the merged PRs as "#a #b"
    set_live() { live_names="$(mn)"; case "$live_names" in *" "*) live_pr="PRs $live_names"; live_is=are ;; *) live_pr="PR $live_names"; live_is=is ;; esac; }   # from the merge on, the messages name the PRs this group merged, not every member: a member the queue ejected was never merged
    plog() { printf '%s\n' "$(say "$2")" >> "$LOGDIR/pr-$1.log"; }                                                                               # a result line, into one PR's log only
    fail() {   # a failure of the whole group: every PR still open (live_prs: the merged ones too once their deploy is what failed) gets its FAILED line, the release queue is dealt with by $q_fail, one red report
        local k who="PRs $names"; say "FAILED at $1: $2"
        [ -z "$live_names" ] || who="$live_pr"   # once the merge is settled, only the merged PRs are named
        for k in "${live_prs[@]}"; do plog "$k" "FAILED at $1: $(printf '%s' "$2" | mq_plain)"; done
        qg_after_fail "$1"
        tell "[release] $who FAILED at $1: $2$q_note · log $glog"
        exit 1
    }
    SYNC_WHO="the group release of PRs $names"; trap 'record_sync; running_end' EXIT   # deploy_ssh: however this release ends, the server box gets the record (4c-record) and is told the release ended (4c-running); a subshell does not run it
    running_start "$lead" "$LOGDIR/pr-$lead.log"   # one unit, the lead's, so one entry (4c-running)
    hold_note
    mq_settle() {   # $1 = a PR: let go of it in the queue (best effort). Its marker goes once the queue no longer holds it: dropped, or "is not in the line" (never added: the add was refused, or it settled already), or no active entry in `mq status`
        local k="$1" o rc st act
        o="$(timeout 20 salamander mq drop "$k" --repo "$REPO" 2>&1 4>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
        if [ $rc -eq 0 ] || [[ "$o" == *"is not in the line"* ]]; then mqh_clear "$k"; return 0; fi
        st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 4>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
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
        gh pr view "$1" --repo "$REPO" --json state,mergeCommit,headRefOid 2>/dev/null 4>&- 6>&- 7>&- 8>&- 9>&- | python3 -c '
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
    ! q_is_started "$lead" || qstart=1   # the release queue started this group (it marked the lead before the start)
    gsay "release of PRs $names starts in $HERE ($REPO): the merge queue (mode on) tests them as one group and merges it once"
    recover_pending   # a fast deploy of an earlier release whose process ended before main's run was read: looked at first
    local mqmode; mqmode="$(mq_host_mode)"
    [ "$mqmode" = on ] || fail "mq mode" "the host file's merge queue mode is now \"${mqmode#bad: }\", not on, so this group cannot go through the queue; nothing was merged. Set it to on again, or release.sh queue --resume to release the PRs one by one"
    mq_on_check "$lead" || fail "mq mode" "$mq_why"
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
        out="$(timeout "$MQ_ON_ADD_TIMEOUT" salamander mq add "${addprs[@]}" --repo "$REPO" 2>&1 4>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
        if [ $rc -ne 0 ] || printf '%s\n' "$out" | grep '^salamander mq: ' >/dev/null; then
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
                    out="$(timeout $((slice + 30)) salamander mq wait "$m" --repo "$REPO" --timeout "$slice" 2>&1 4>&- 6>&- 7>&- 8>&- 9>&-)"; rc=$?
                    line="$(printf '%s\n' "$out" | grep -m1 -E '^PR [0-9]+[ :]' | cut -c1-300)"   # the verdict line: a line before it on stderr (the driver started again) is not it
                    [ -n "$line" ] || line="$(printf '%s\n' "$out" | head -n 1 | cut -c1-300)"
                    if printf '%s\n' "$out" | grep '^salamander mq: ' >/dev/null; then   # salamander's own error (a host file, a state file), not a verdict on the PR, even at exit 1
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
                        2) if printf '%s' "$out" | grep 'gave up waiting' >/dev/null; then   # this slice ran out: is the queue still able to merge?
                               st="$(timeout 30 salamander mq status --json --repo "$REPO" 2>/dev/null 4>&- 6>&- 7>&- 8>&- 9>&-)" || st=""
                               why_q="$(printf '%s' "$st" | python3 -c '
import json, sys
d = json.load(sys.stdin); p = d.get("paused"); b = d.get("blocked")
print(("paused: " + str(p.get("reason", ""))) if p else ("blocked: " + str(b.get("reason", ""))) if b else "")' 2>/dev/null)"
                               [ -z "$why_q" ] || { wait_abort "mq" "the merge queue is $why_q, so PR #$m cannot be merged"; break 2; }
                               continue
                           fi
                           if printf '%s' "$out" | grep 'the queue is blocked' >/dev/null; then wait_abort "mq" "the merge queue is blocked ($(printf '%s' "$line" | mq_plain)), so PR #$m cannot be merged"; break 2; fi
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
    set_live
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
    set_live
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
    # the same gate as a release through GitHub's queue (deploy_gate): the salamander merge queue tested exactly the tree it merged (its group's run on the queue branch), so M deploys at once when the live checkout is behind it,
    # a last-good commit is recorded and nothing since it failed on main; a closed gate waits for main's tests. M already in the live checkout (a later release deployed past it) deploys nothing
    local cur; cur="$(git rev-parse HEAD)"
    local why_fast="the merge queue tested exactly this tree (its group's run on the queue branch)" fast_note=""
    if git merge-base --is-ancestor "$M" "$cur"; then
        live_now=1; fast=1; verified="$M"
        say "already live: the live checkout (${cur:0:7}) contains the merge ${M:0:7} (a later release deployed past it, or deploy.sh was run by hand); nothing to deploy, main's full run is waited for as after a deploy"
        fast_note="; already live: the live checkout ${cur:0:7} contained the merge when this group took the deploy lock; nothing was deployed here, and main's full run is waited for"
    elif deploy_gate "$M" 1 ""; then
        fast=1; verified="$M"; say "deploying ${verified:0:7} at once: $why_fast; main's full run follows; ${good:0:7} is the last good commit to go back to"
        fast_note="; deployed at the merge ($why_fast): main's full run follows and rolls it back to ${good:0:7} on a failure"
        pending_set "$verified" "$pr"   # before deploy.sh: production changes at its fast-forward; a kill in there must leave the record
    else
        say "not deployed at the merge yet: $gate_why; the deploy waits for main's tests"
        fast_note="; the deploy gate was closed ($gate_why), so the deploy waited for main's tests"
        exec 9>&-   # the wait for main's run is outside the lock, as for a release alone
        main_green pre "$M"
        take_lock "merged, not live (./deploy.sh by hand once it is free)"
    fi
    out=""; rc=0
    if [ $live_now = 1 ]; then exec 9>&-; sha="$(git rev-parse --short HEAD)"; restarted=nothing
    else
        out="$(deploy_run "$verified" 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
        sha="$(git rev-parse --short HEAD)"
        [ $rc -eq 0 ] || q_pause_now "deploy"   # a failed deploy (or one this checkout could not follow, deploy_ssh) pauses the queue before the lock is let go, as for a release alone
        exec 9>&-
        [ -z "$DEPLOY_SSH" ] || [ $rc -ne $FOLLOW_SKIPPED_RC ] || { pending_clear; fail "deploy" "$(follow_why "$verified" "$out")"; }
        [ $rc -eq 0 ] || { pending_clear; fail "deploy" "$(echo "$out" | tail -1) (main is merged at $sha; the checkout is at $(git rev-parse --short HEAD)): merged, not live"; }
        restarted="$(echo "$out" | sed -n 's/^  restarted //p' | tr '\n' ' ')"; restarted="${restarted:-nothing}"
    fi
    if [ $live_now = 1 ]; then say "done: $sha, already live, restarted nothing"; else say "done: $sha, restarted $restarted"; fi
    [ $live_now = 1 ] || suitemap_warm_start "$verified"   # what was deployed is main's tip: its picker index is built where picks are made, detached, never waited for
    for m in "${merged_prs[@]}"; do plog "$m" "done: $sha, $([ $live_now = 1 ] && echo "already live, ")restarted $restarted"; done   # the line a waiter and the board hooks look for, in each PR's own log
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
        notice_send "release: stackshot $live_pr" "stackshot $live_pr $live_is live at $sha; what sessions are told changed in $NOTICE_FROM; $nsum" || nrc=$?
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
            if rd="$(python3 stackshot/fleet/client.py recycle-due --pr "https://github.com/$REPO/pull/$m" 2>&1)"; then flagged=1; rc_note="$rc_note; recycle (PR #$m): $(echo "$rd" | sed 's/^stackshot: //' | paste -sd ';' -)"; fi
        done
        if [ $flagged = 1 ]; then :
        elif idle_recycle "release: stackshot $live_pr"; then rc_note="$rc_note; recycle: no item flagged, so the fleet tool was asked for one once the box is idle"
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
        tell "[release] PR #$m $([ $live_now = 1 ] && echo "merged and already live" || echo "merged and deployed") — ${title:-PR #$m} — main at $sha, restarted: $restarted, healthz ok; merged by the merge queue in one group with $(mn)$pre_note$fast_note$audit_note$pk_note$rc_note · log $LOGDIR/pr-$m.log" "${green[@]}"
    done
    qg_handoff deployed   # deployed: the group's PRs leave the queue file (those the queue could not merge stay, first) and the next waiting ones start
    if [ $fast = 0 ]; then for m in "${merged_prs[@]}"; do released "$m" "$M"; done; return $gfailed; fi   # deployed only after main's tests passed on the merge: it is live now
    # after a deploy at the merge: main's full run for that commit, outside the lock; a pass is a log line, a failure rolls back (rollback() reports the lead and each rider it took out)
    if main_green post "$verified"; then
        pending_clear
        if [ -n "$mg_notlive" ]; then
            tell "[release] $live_pr: main's tests passed on ${verified:0:7}, but it is not live ($mg_notlive); it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green · log $glog"
            return $gfailed
        fi
        [ -z "$audit_note" ] || tell "[release] $live_pr deployed at ${verified:0:7}${audit_note} · log $glog"
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
    TRAP_TEE="${!:-}"; TRAP_LOG="$log"; TRAP_OUT="$(readlink "/proc/$$/fd/1" 2>/dev/null)"   # for trap_out ($!: the tee, the process substitution just started)
    say "release of PR #$pr starts in $HERE ($REPO)"
    ! q_is_started "$pr" || qstart=1   # the queue started this release (it wrote the mark before the start): its pause and its pre-enqueue stop apply to it
    fail() { say "FAILED at $1: $2"; queue_after_fail "$1"; tell "[release] PR #$pr FAILED at $1: $2$q_note · log $log"; exit 1; }
    SYNC_WHO="PR #$pr"; trap 'trap_out; orphan_exit; record_sync; running_end' EXIT   # its lines go to the log (trap_out); a PR this release closed to replace an orphaned run and has not reopened is reopened (orphan_exit); deploy_ssh: however this release ends, the server box gets the record (4c-record) and is told the release ended (4c-running); a subshell does not run it
    running_start "$pr" "$log"
    hold_note
    recover_pending   # a deploy of an earlier release whose process ended before main's run was read (killed, the box restarted): looked at first
    local mqmode; mqmode="$(mq_host_mode)"   # THE TWO MERGE QUEUES: only `on` changes this release (off, shadow, no file and a file that does not read are GitHub's queue, below)
    mq_line_check() {   # every mode: a PR the salamander merge queue holds (the marker of a group release) is never merged here, whatever the host file says now (a mode changed mid-group does not take the PR out of that queue)
        [ -e "$MQ_HANDED/pr-$pr" ] || return 0
        local ql how; ql="$(mq_marker_lead "$pr")"
        if [ -n "$ql" ] && q_alive "$ql"; then how="its group release (PR #$ql, stackshot-release-$ql) is still running: wait for it"
        else how="its group release ${ql:+(PR #$ql) }is not running: if salamander mq status --repo $REPO no longer lists the PR, release.sh queue --drop $pr removes the stale marker (or delete $MQ_HANDED/pr-$pr); otherwise salamander mq drop $pr --repo $REPO takes it out of the queue, and release.sh queue --resume goes on with the group release"; fi
        fail "mq line" "PR #$pr was handed to the salamander merge queue ($(cut -c1-120 "$MQ_HANDED/pr-$pr")) and may still be in its line: merging it here would merge what the queue also holds; nothing was merged. $how"
    }
    case "$mqmode" in
        on) # THE TWO MERGE QUEUES: a PR released alone in mode on (one PR waiting in the release queue, or released by hand) takes this path with no call to the salamander merge queue. Two things differ: the host file must name the
            # deploy lock this script takes (mq_on_check: it is what keeps the queue's merge push out of this release's deploy), and a PR the queue holds is never merged here (the marker of a group release, MQ_HANDED)
            mq_on_check "$pr" || fail "mq mode" "$mq_why"
            say "salamander merge queue (mode on): PR #$pr is released alone, by this release's own path; the queue is not called for it" ;;
        off) ;;
        shadow) say "the host file says shadow, a mode this script no longer runs: GitHub's merge queue is used as with off" ;;
        *) say "the host file's merge queue mode does not read (${mqmode#bad: }): GitHub's merge queue is used as with off" ;;
    esac
    mq_line_check
    local view state mergeable regens=0 regen_pushed=0 headsha="" mergeoid="" removed_why="" via_queue=0 nonq_why="" resumed=0 enq_epoch=0 good="" gate_why="" fast=0 live_now=0 fast_note=""
    read_view() {   # the PR as GitHub says it now: $view, $title, $state, $mergeable
        view="$(gh pr view "$pr" --repo "$REPO" --json state,mergeable,title,headRefName,isCrossRepository,headRefOid 2>&1)" || fail "pr view" "$(echo "$view" | tail -1)"
        title="$(echo "$view" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["title"])')"
        state="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"; mergeable="$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["mergeable"])')"
    }
    view_head() { echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])'; }
    mergeable_stage() {   # $1 = start | removed. 1. The PR is open and mergeable. GitHub recomputes mergeable for a little while after main moves and says UNKNOWN meanwhile (a PR can fail on it right after another merge):
                          # read again every 10 s for up to MERGEABLE_WAIT (3 min). CONFLICTING, or UNKNOWN when the time is up, fails; so does a PR that is no longer open. 2a: a conflict that is only the generated tool-text
                          # snapshot is mended here, then GitHub is read until it has the new head and has recomputed ($regen_pushed = 1: the caller waits for the tests on the new head); anything else fails as before.
                          # In "removed" mode GitHub took the PR out of the merge queue ($removed_why): a PR that is mergeable and was not mended is for the caller to fail with that reason
        local step=mergeable why="" oldh mwaited=0 rwaited=0
        [ "$1" != removed ] || { step="merge queue"; why="$removed_why; "; }
        regen_pushed=0
        read_view
        if [ "$1" = start ] && [ -e "$LOGDIR/orphan-reopen-$pr" ]; then   # an earlier release of this PR called to close it to replace a run queued with no jobs (the marker) and did not reopen it. A rerun never reopens it:
                                                                          # GitHub does not say whose call closed a PR, so a CLOSED PR fails, naming that close and how to reopen it by hand (the marker stays)
            [ "$state" != CLOSED ] || fail "pr state" "the PR is CLOSED. An earlier release of it called to close it to replace a run queued with no jobs ($LOGDIR/orphan-reopen-$pr) and did not reopen it; a release does not reopen a PR it cannot prove it closed itself (GitHub does not say whose call closed a PR). If no one else closed it since, reopen it by hand (gh pr reopen $pr), then run release.sh $pr again"
            # open again (reopened by hand) or merged: the runs that close was to replace (the marker's) are passed over at this release's first look only (orphan_prior): GitHub can list them as the newest a
            # moment after a reopen, but the close may never have taken effect, and then such a run is the one that still holds the wait
            local rid; for rid in $(cut -s -d' ' -f3- "$LOGDIR/orphan-reopen-$pr" 2>/dev/null); do [[ "$rid" =~ ^[0-9]+$ ]] && orphan_prior="$orphan_prior$rid "; done
            rm -f "$LOGDIR/orphan-reopen-$pr"
        fi
        if [ "$1" = start ] && [ "$state" = MERGED ]; then resumed=1; return 0; fi   # a rerun on a merged PR (4 below)
        if [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ]; then
            say "GitHub says mergeable UNKNOWN (it is still computing, as it does after main moves); reading again every 10 s for up to $((MERGEABLE_WAIT/60)) min"
            while [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ] && [ $mwaited -lt $MERGEABLE_WAIT ]; do sleep 10; mwaited=$((mwaited+10)); read_view; done
        fi
        if [ "$1" = removed ] && [ "$state" = MERGED ]; then resumed=1; return 0; fi   # the PR shows merged only now, after it was read as removed from the queue: GitHub's answer came late; the caller carries on from the merge
        [ "$state" = OPEN ] || fail "pr state" "${why}the PR is $state"
        if [ "$mergeable" = CONFLICTING ]; then   # 2a
            oldh="$(view_head)"
            if regen_snapshot "$1"; then
                regen_pushed=1   # the head is a new commit: its checks are waited on like a regenerated head's (the tests job must be among them and have passed), not as the quiet first wait
                while :; do
                    sleep 10; rwaited=$((rwaited+10)); read_view; [ "$state" = OPEN ] || break
                    if [ "$(view_head)" != "$oldh" ] && [ "$mergeable" != UNKNOWN ] && [ "$mergeable" != CONFLICTING ]; then break; fi
                    [ $rwaited -lt $MERGEABLE_WAIT ] || break
                done
                [ "$state" = OPEN ] || fail "pr state" "${why}the PR is $state"
                say "mergeable: after the snapshot regeneration GitHub says $mergeable (head $(view_head | cut -c1-7))"
            fi
        fi
        case "$mergeable" in
            MERGEABLE) ;;
            CONFLICTING) fail "$step" "${why}GitHub says CONFLICTING: the PR has a conflict with main" ;;
            UNKNOWN) fail "$step" "${why}GitHub still says UNKNOWN after $((MERGEABLE_WAIT/60)) min: it has not finished computing whether the PR merges; run release.sh again" ;;
            *) fail "$step" "${why}GitHub says $mergeable" ;;
        esac
        headsha="$(view_head)"
        [[ "$headsha" =~ ^[0-9a-f]{7,64}$ ]] || fail "pr view" "no head commit in GitHub's answer ($headsha)"
    }
    enqueue_pr() {   # 3. What GitHub says about the branch decides how the PR goes in: `repository.mergeQueue(branch:"main")` present (the ruleset's queue is on) -> the GraphQL mutation enqueuePullRequest, pinned to the head the checks
                     # ran on (expectedHeadOid), so a push after the checks cannot ride in; absent (the ruleset is off, the way back) -> `gh pr merge --merge --admin --match-head-commit <head>`, which merges at once. `gh pr merge` is never used with
                     # the queue on: it would ask for auto-merge, which this repository does not allow (cli/cli#13398). $via_queue says which way it went; $enq_epoch is the second of the call, for the removal event
        local out tries waits att=1 attmax why seen   # the waits (seconds) between the attempts at the enqueue call: one more attempt than waits; RELEASE_ENQUEUE_WAITS overrides the list (the tests give it "0 0 0")
        read -r -a waits <<< "${RELEASE_ENQUEUE_WAITS:-5 15 45}"
        attmax=$((${#waits[@]} + 1))
        gq_mq=""; gq_prid=""
        for tries in 1 2 3; do ghq_target "$pr" && break; [ $tries = 3 ] || sleep 10; done
        [ -n "$gq_mq" ] || fail "merge" "GitHub's answer about the repository's merge queue and the PR cannot be read, so it is not known whether the PR goes into the queue or is merged at once"
        enq_epoch="$(date +%s)"; gq_since=""   # the entry's own second comes with the next read of it (enq_failed's, for a PR that is in the queue already)
        if [ "$gq_mq" = 1 ]; then
            via_queue=1
            while :; do
                if out="$(gh api graphql -f query='mutation($id:ID!,$h:GitObjectID!){enqueuePullRequest(input:{pullRequestId:$id,expectedHeadOid:$h}){mergeQueueEntry{state position}}}' -f id="$gq_prid" -f h="$headsha" 2>&1 9>&-)" \
                   && echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if not d.get("errors") and (d.get("data") or {}).get("enqueuePullRequest") else 1)' 2>/dev/null; then
                    say "enqueued: the merge queue accepted the head ${headsha:0:7}"; break
                fi
                why="$(enq_transient "$out")"   # GitHub's server failed (5xx, INTERNAL, "something went wrong", a timeout or a reset), as against a refusal; empty for a refusal
                # gh prints the error body on stdout and its message on stderr: the report gets GitHub's messages (a red check, a ref rule), or the last line when there is no body
                out="$(echo "$out" | python3 -c '
import json, sys
lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
msgs = []
for l in lines:
    try: msgs += [e.get("message", "") for e in (json.loads(l).get("errors") or [])]
    except Exception: pass
print("; ".join(m for m in msgs if m) or (lines[-1] if lines else "no answer"))' 2>/dev/null)"
                # a refusal, or the last attempt: as before (enq_failed reads the PR's state again and fails with the error)
                if [ -z "$why" ] || [ $att -ge $attmax ]; then enq_failed "$out"; break; fi
                # the call may have gone through before it failed (a timeout, a reset, a 504): the PR's state is read before another call
                if ghq_read "$pr" && { [ "$gq_state" = MERGED ] || [ -n "$gq_entry" ]; }; then
                    seen="${gq_state}${gq_entry:+, in the merge queue ($gq_entry)}"
                    say "the enqueue call errored: $out; reading the PR's state again"
                    say "the enqueue call errored ($out) but the PR is $seen; carrying on"
                    merge_note="$merge_note; the enqueue call errored ($out) but the PR was $seen"; break
                fi
                say "merge queue call answered $why; retrying in ${waits[$((att - 1))]} s (attempt $((att + 1)) of $attmax)"
                sleep "${waits[$((att - 1))]}"; att=$((att + 1))
            done
        else
            # --admin: with the bot-only ruleset active and main not excluded from it, a green PR reads BLOCKED and a plain `gh pr merge` fails with "the base branch policy prohibits the merge";
            # --admin lets the bot merge a green PR, and GitHub still refuses a failing or pending one, so the required check holds. --match-head-commit keeps the head pin
            via_queue=0; nonq_why="the PR was merged by the plain merge call: the repository has no merge queue on main (the ruleset is off), so no merge_group run tested the merge"
            if out="$(gh pr merge "$pr" --repo "$REPO" --merge --admin --match-head-commit "$headsha" 2>&1 9>&-)"; then say "no merge queue on main (the ruleset is off): merged at once, the plain merge call accepted the head ${headsha:0:7} ($(echo "$out" | tail -1 | cut -c1-160))"
            else enq_failed "$(echo "$out" | tail -1)"; fi
        fi
    }
    enq_transient() {   # $1 = what the enqueue call printed (stdout and stderr). A short reason when GitHub's server failed and the same call may work a moment later: a 5xx, a GraphQL error of type INTERNAL, "something went wrong", a timeout, a reset or a cut connection.
                        # Empty (nothing is retried) for anything else: a 4xx, "not mergeable", "already in the queue", a conflict, a failed required check, a ref rule, an answer that says nothing
        echo "$1" | python3 -c '
import re, sys
t = sys.stdin.read(); low = t.lower()
if re.search(r"http 4\d\d|not mergeable|already|conflict|failing|required status|protected ref|not enabled", low): sys.exit(0)   # a refusal first: its text may hold a transient word too
if re.search(r"\"type\"\s*:\s*\"internal\"", low): print("a GraphQL INTERNAL error"); sys.exit(0)
m = re.search(r"http (5\d\d)", low)
if m: print("HTTP " + m.group(1)); sys.exit(0)
for pat, name in (("something went wrong", "an error (something went wrong)"), ("timed out|timeout|deadline exceeded", "a timeout"), ("connection reset|connection refused|broken pipe|unexpected eof|\\beof\\b|tls handshake", "a cut connection"),
                  ("bad gateway|service unavailable|gateway time-?out", "a gateway error")):
    if re.search(pat, low): print(name); sys.exit(0)' 2>/dev/null
    }
    enq_failed() {   # $1 = the call's last line. The call can error after the PR was queued or merged (a 504, or a PR queued already): GitHub's answer is eventually consistent, so ask again
        local err="$1" i seen="" what; what="$([ "$gq_mq" = 1 ] && echo enqueue || echo merge)"
        say "the $what call errored: $err; reading the PR's state again"
        for i in 1 2 3 4 5 6; do
            if ghq_read "$pr" && { [ "$gq_state" = MERGED ] || [ -n "$gq_entry" ]; }; then seen="${gq_state}${gq_entry:+, in the merge queue ($gq_entry)}"; break; fi
            [ $i -lt 6 ] && sleep 10
        done
        [ -n "$seen" ] || fail "merge" "$err"
        say "the $what call errored ($err) but the PR is $seen; carrying on"
        merge_note="$merge_note; the $what call errored ($err) but the PR was $seen"
    }
    resume_merged() {   # 4. A rerun on a PR GitHub merged after the earlier release ended (killed, or QUEUE_WAIT passed), or a PR that showed merged only after it was read as removed from the queue ($1 = late): the merge commit is read and the
                        # release carries on from the merge, at the deploy gate. Nothing says the merge came through the queue, so the gate stays closed (nonq_why) and the deploy waits for main's tests
        local tries
        for tries in 1 2 3; do
            if ghq_read "$pr" && [ "$gq_state" = MERGED ] && [[ "$gq_oid" =~ ^[0-9a-f]{7,64}$ ]]; then break; fi
            gq_oid=""; [ $tries = 3 ] || sleep 10
        done
        [ -n "$gq_oid" ] || fail "pr state" "the PR is merged, but GitHub gives no merge commit for it to carry on from"
        mergeoid="$gq_oid"; via_queue=0
        if [ "${1:-}" = late ]; then
            nonq_why="the PR showed merged only after it was read as removed from the merge queue, so the merge is not known to have come through it"
            say "PR #$pr: $title shows merged now, as ${mergeoid:0:7}, after it was read as removed from the merge queue: carrying on from the merge (the deploy gate, the deploy, main's run, the report)"
            merge_note="$merge_note; the PR showed merged after it was read as removed from the merge queue: carried on from the merge ${mergeoid:0:7}"
        else
            nonq_why="the PR was merged before this release started (an earlier release ended first), so it is not known to have come through the merge queue"
            say "PR #$pr: $title is merged already, as ${mergeoid:0:7}: carrying on from the merge (the deploy gate, the deploy, main's run, the report)"
            merge_note="$merge_note; the PR was merged before this release started: carried on from the merge ${mergeoid:0:7}"
        fi
    }
    mergeable_stage start
    if [ $resumed = 1 ]; then resume_merged   # 4: merged already
    else
    say "PR #$pr: $title (head ${headsha:0:7})"
    codex_review_start "$pr"   # step 1a: the PR was just read as open; the review is started here, before the wait for the checks, and never waited for
    if [ "$regen_pushed" = 1 ]; then wait_pr_checks "pr tests" progress "the PR's tests pass on the pushed head ${headsha:0:7}"   # as after a regeneration below: a quick check alone must not read as a pass on the new head
    else wait_pr_checks checks quiet "checks pass"; fi
    q_paused_stop   # the wait for the checks can be long: a pause that came meanwhile stops this release before it enqueues the PR
    mq_line_check   # a group release may have handed this PR to the salamander merge queue while this release waited for its checks (a hand-run release races a group that includes it): looked at again just before the merge
    # 3, 3a: enqueue and wait for GitHub to merge. A PR removed from the merge queue for a conflict that is only the snapshot is mended and enqueued again (at most REGEN_MAX times in the release); any other removal fails the release before a deploy
    while :; do
        enqueue_pr
        wait_merged && break
        mergeable_stage removed
        if [ $resumed = 1 ]; then resume_merged late; break; fi
        [ "$regen_pushed" = 1 ] || fail "merge queue" "$removed_why"
        wait_pr_checks "pr tests" progress "the PR's tests pass on the regenerated head ${headsha:0:7}"
        q_paused_stop
        say "enqueueing the PR again on the regenerated head ${headsha:0:7}"
    done
    fi
    q_fail=pause   # from here a failure is one of a merged release: it pauses the release queue (before the merge it was skipped and the queue went on)
    # the head branch goes after the merge, never with it: the open PRs based on it are retargeted to main first (one is closed when the PR it was based on merges)
    retarget_and_delete_branch "$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("headRefName") or "")')" \
        "$(echo "$view" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("isCrossRepository") is True)')"
    fetch_retry || fail "deploy" "the PR is merged as ${mergeoid:0:7}, but main cannot be fetched from origin to deploy it (merged, not deployed; ./deploy.sh by hand)"
    git cat-file -e "$mergeoid^{commit}" 2>/dev/null || fail "deploy" "the PR is merged as ${mergeoid:0:7}, but that commit is not among the commits fetched from main (merged, not deployed; look at main by hand)"
    # 4. the deploy takes the deploy lock, so two releases never deploy at once; the waits above are outside it. fd 9 is closed for every
    # child of the deploy (a service a deploy leaves behind must never inherit the lock); it is released when deploy.sh returns.
    take_lock "merged, not deployed (./deploy.sh by hand once it is free)"
    local cur; cur="$(git rev-parse HEAD)"
    git merge-base --is-ancestor "$mergeoid" "$cur" || q_paused_deploy_stop   # a release that deploys nothing (4a) is not stopped by a pause
    if git merge-base --is-ancestor "$mergeoid" "$cur"; then   # 4a
        live_now=1; fast=1; verified="$mergeoid"
        say "already live: the live checkout (${cur:0:7}) contains the merge ${mergeoid:0:7} (a later release deployed past it, or deploy.sh was run by hand); nothing to deploy, main's full run is waited for as after a deploy"
        fast_note="; already live: the live checkout ${cur:0:7} contained the merge when this release took the deploy lock; nothing was deployed here, and main's full run is waited for"
    elif deploy_gate "$mergeoid" "$via_queue" "$nonq_why"; then   # 4b, 4c
        fast=1; verified="$mergeoid"
        say "deploying ${verified:0:7} at once: the merge queue ran the suites its selection picked for the merge group on the tree it made (not every suite); main's full run follows; ${good:0:7} is the last good commit to go back to"
        fast_note="; deployed at the merge (GitHub's merge queue ran the selected suites on the tree it made, not every suite): main's full run follows and rolls it back to ${good:0:7} on a failure"
        pending_set "$verified" "$pr"   # before deploy.sh: production changes at its fast-forward, and the restarts and healthz take up to 180 s; a kill in there must leave the record
    else   # 4d
        say "not deployed at the merge yet: $gate_why; the deploy waits for main's tests"
        fast_note="; the deploy gate was closed ($gate_why), so the deploy waited for main's tests"
        # main's tests run outside the lock: a release waiting on main's run must not hold another release's deploy,
        # so the lock is let go for the wait and taken again for the deploy
        exec 9>&-
        main_green pre "$mergeoid"
        take_lock "merged, not deployed (./deploy.sh by hand once it is free)"
        q_paused_deploy_stop   # a rollback during the wait for main's tests paused the queue
    fi
    local out="" rc=0
    if [ $live_now = 1 ]; then exec 9>&-; sha="$(git rev-parse --short HEAD)"
    else
        out="$(deploy_run "$verified" 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
        sha="$(git rev-parse --short HEAD)"
        [ $rc -eq 0 ] || q_pause_now "deploy"   # a failed deploy (or one this checkout could not follow, deploy_ssh) pauses the queue before the lock is let go, as a rollback does
        exec 9>&-     # the lock is released here: the failure report, the recycle step and the message below start children that must not inherit it
    fi
    [ -z "$DEPLOY_SSH" ] || [ $rc -ne $FOLLOW_SKIPPED_RC ] || { pending_clear; fail "deploy" "$(follow_why "$verified" "$out")"; }
    [ $rc -eq 0 ] || { pending_clear; fail "deploy" "$(echo "$out" | tail -1) (main is merged at $sha; the checkout is at $(git rev-parse --short HEAD))"; }   # reported red here: nothing left to verify
    restarted="$(echo "$out" | sed -n 's/^  restarted //p' | tr '\n' ' ')"; restarted="${restarted:-nothing}"
    if [ $live_now = 1 ]; then say "done: $sha, already live, restarted nothing"; else say "done: $sha, restarted $restarted"; fi
    [ $live_now = 1 ] || suitemap_warm_start "$verified"   # what was deployed is main's tip: its picker index is built where picks are made, detached, never waited for
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
        if rd="$(python3 stackshot/fleet/client.py recycle-due --pr "$url" 2>&1)"; then rc_note="; recycle: $(echo "$rd" | sed 's/^stackshot: //' | paste -sd ';' -)"
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
    local what="merged and deployed"; [ $live_now = 0 ] || what="merged and already live"
    tell "[release] PR #$pr $what — $title — main at $sha, restarted: $([ $live_now = 1 ] && echo nothing || echo "$restarted"), healthz ok$merge_note$fast_note$audit_note$pk_note$rc_note · log $log" "${green[@]}"
    q_handoff deployed   # deployed: from here this release only waits on main's run (4c) or is done (4d), so the next waiting PRs start now
    [ $fast = 1 ] || { released "$pr" "${mergeoid:-$verified}"; return 0; }   # 4d deployed only after main's tests passed on the merge: it is live now
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
    --warm) [[ "${2:-}" =~ ^[0-9a-f]{7,64}$ ]] && [ $# -eq 2 ] || { echo "usage: release.sh --warm <commit>" >&2; exit 2; }; warm_run "$2"; exit 0 ;;   # the unit suitemap_warm_start starts
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
    --run-group) shift; [ $# -ge 2 ] && ! printf '%s\n' "$@" | grep -vE '^[0-9]+$' >/dev/null && [ -z "$(printf '%s\n' "$@" | sort | uniq -d)" ] || { echo "usage: release.sh --run-group <pr> <pr> [<pr>...]  (two or more different PR numbers)" >&2; exit 2; }; run_group "$@"; exit $? ;;   # the steps themselves (what the group's unit runs; THE MERGE QUEUE, ON)
    --group)   # mode on: the PRs the release queue holds, released as one group through the merge queue (what the queue starts when two or more wait). Starts the unit and returns at once, as `release.sh N` does
        shift; [ $# -ge 2 ] && ! printf '%s\n' "$@" | grep -vE '^[0-9]+$' >/dev/null && [ -z "$(printf '%s\n' "$@" | sort | uniq -d)" ] || { echo "usage: release.sh --group <pr> <pr> [<pr>...]  (two or more different PR numbers; needs the merge queue in mode on)" >&2; exit 2; }
        [ $# -le "$MQ_HANDOFF_MAX" ] || { echo "release.sh --group: $# PRs are more than one hand-off ($MQ_HANDOFF_MAX at most, release.sh's own number): hand over $MQ_HANDOFF_MAX at most" >&2; exit 2; }
        if systemctl --user is-active --quiet "stackshot-release-$1.service" 2>/dev/null; then echo "release of PR #$1 is already running (release.sh --status $1)"; exit 1; fi
        systemd-run --user --quiet --collect --unit "stackshot-release-$1" -p WorkingDirectory="$HERE" \
            --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --run-group "$@" \
            || { echo "could not start stackshot-release-$1 (systemd-run failed): nothing was started" >&2; exit 1; }
        hold_note
        echo "started stackshot-release-$1: hands the PRs $* to the merge queue as one group, deploys what it merges once, and reports to $REPORT_TO · log $LOGDIR/group-$1.log (and each PR's pr-N.log)"; exit 0 ;;
    queue) shift; queue_cmd "$@"; exit $? ;;
    hold) shift; hold_cmd "$@"; exit $? ;;   # THE HOLD (above take_lock)
    --copy-record)   # [release] deploy_ssh: copy the last-good record to the server box now (4c-record; a release does it on its own: this is for a copy that failed with no release coming)
        [ $# -eq 1 ] || { echo "usage: release.sh --copy-record" >&2; exit 2; }
        [ -n "$DEPLOY_SSH" ] || { echo "nothing to copy: [release] deploy_ssh is unset, so the server reads this box's record"; exit 0; }
        [ -s "$LAST_GOOD" ] || { echo "nothing to copy: no last-good record in $LAST_GOOD"; exit 0; }
        SYNC_TOLD=1; record_sync; exit $? ;;   # by hand: the output is the report, no message
    ''|-h|--help) sed -n '2,/^set -uo pipefail/{/^set -uo pipefail/!p}' "$0"; exit 2 ;;   # the header comment, up to the first line of code
    *)
        pr="$1"; [[ "$pr" =~ ^[0-9]+$ ]] && [[ "${2:-}" =~ ^(|--recycle|--no-recycle)$ ]] && [ $# -le 2 ] || { echo "usage: release.sh <pr> [--recycle | --no-recycle] | --status [pr] | --run <pr> [--recycle | --no-recycle] | --pick <pr> | --pick-files <file>... | queue N [N...] | queue --list | queue --drop N | queue --resume | hold --minutes N --by NAME --why TEXT | hold --status | hold --end | --group N N... | --copy-record" >&2; sed -n '/^# How to run it/,/^#   - Auto mode/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
        if systemctl --user is-active --quiet "stackshot-release-$pr.service" 2>/dev/null; then echo "release of PR #$pr is already running (release.sh --status $pr)"; exit 1; fi
        systemd-run --user --quiet --collect --unit "stackshot-release-$pr" -p WorkingDirectory="$HERE" \
            --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --run "$pr" ${2:+"$2"} \
            || { echo "could not start stackshot-release-$pr (systemd-run failed): nothing was started" >&2; exit 1; }     # uv, gh, python3 and the fleet tool as the shell sees them; a start that failed is said so (the queue skips it)
        hold_note
        echo "started stackshot-release-$pr: enqueues PR #$pr in the merge queue when its checks pass, deploys what GitHub merges, picks what the sessions need (${2:-from the files it changed}), and reports to $REPORT_TO · log $LOGDIR/pr-$pr.log"; exit 0 ;;
esac
exit 0
