#!/usr/bin/env bash
# release.sh — enqueue a PR in GitHub's merge queue and deploy what the queue merges, detached: the builder (example-engineer) starts it and leaves, and the result comes back as one
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
#   - A PR whose branch is behind main is not touched: the merge queue builds it on main's tip. A PR that conflicts with main only on the generated tests/tool_text.snapshot.json is mended (2a below).
#     Watch a release with `release.sh --status N`: the log's newest line says what is waited for.
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
#   ./release.sh queue N [N...]   add PRs to the release queue (<paths.state>/releases/queue), in order; a PR queued already stays where it is. A PR with a failing, cancelled or timed-out check row is refused (exit 1, the rows printed, nothing queued), and so is one whose rows cannot be read. Every queued release that is not running starts at once, up to 4 running at a time (one is running from its start until it is
#                                 deployed, the point after which it only waits on main's run; it stays in the queue file until then, so a killed one is still listed and --resume starts it again); each queued release that reaches "deployed" leaves the queue and starts the next waiting one. A queued PR that fails before its merge (its checks fail, it conflicts, it is closed, GitHub removes it from the merge queue, a lock is not had) is reported as any failure
#                                 is, and skipped: the queue goes on. A failure after the merge (main's run failing for it, merged and not deployed or rolled back; its deploy failing) of a release the queue started pauses the queue: no new release starts, a release the queue had started already but not enqueued stops at
#                                 "queue paused" and stays first in the queue, the PRs a rollback took out stay merged on main and are named in the report (the next release's deploy carries them), the rollback and the red report run as always. A plain
#                                 `release.sh N` that fails pauses nothing, and neither does a main run that could not be read. A queued release picks what the sessions need from its PR's files, as any release does.
#   ./release.sh queue --list     the queued PRs in order, each running, waiting or started but not running, whether the queue is paused and why
#   ./release.sh queue --drop N   take PR N out of the queue (a release already started is not stopped, and a PR already in GitHub's merge queue stays there: the CLI cannot remove it)
#   ./release.sh queue --resume   after a pause, once main is fixed: the queue goes on (waiting PRs start up to the cap, and a queued release that was started but is no longer running starts again)
#   ./release.sh --run <pr> [--recycle | --no-recycle]
#                                 the steps themselves (what the unit runs):
#                                 1. the PR is open and mergeable; 2. its checks pass (waits up to 50 min for a pending or queued one: the CI runners take one job at a time);
#                                 2a. A CONFLICT THAT IS ONLY THE GENERATED TOOL-TEXT SNAPSHOT is mended instead of failing (regen_snapshot, tools/snapshot_regen.py): two PRs that both change tool text
#                                 conflict on tests/tool_text.snapshot.json and on nothing else, and the by-hand fix is always the same. When the first look at the PR says CONFLICTING, or GitHub removed the PR
#                                 from the merge queue and the PR conflicts with main now, this fetches main and the PR head (git only: no GitHub call), merges main into the head in a temporary worktree of its own
#                                 (removed on every way out), and, only if the snapshot is the SOLE conflicted path, takes main's snapshot, runs `python3 tools/tool_text.py update` then `check`, commits the merge and pushes it to the PR
#                                 branch (a plain push: a branch its author pushed to meanwhile is refused, never forced). The log says so in one line, the PR head is read until it moves, the PR's tests on the new head are waited for
#                                 (the `suites` check must be reported and completed on that very commit) and the PR is enqueued again. Any other conflicted path, a clean local merge, a failed update or check, a refused push, a cross-repository PR
#                                 or no helper: the release fails, the reason in one more log line. At most RELEASE_REGEN_MAX (1) time in a release, so it cannot loop;
#                                 3. ENQUEUE: `gh pr merge --merge --match-head-commit <the head the checks ran on>` (no --delete-branch), so a push after the checks cannot ride in. On a branch the ruleset requires the merge queue for, this adds the PR to
#                                 the queue once its required checks have passed (they have: step 2). It does not use auto-merge (the repository does not allow it), which is why step 2 waits for green first. When the call errors (a GitHub 504 after
#                                 the PR was queued or merged), the PR's state is read again for up to about 50 s: queued or merged carries on, anything else fails "merge" with the original error. With the ruleset off the same call merges at once, and the log says the PR was merged without the queue;
#                                 3a. WAIT FOR THE MERGE: GraphQL `pullRequest { state mergeCommit { oid } mergeQueueEntry { state position } }`, read every POLL_QUEUE s (60) for up to QUEUE_WAIT (RELEASE_QUEUE_WAIT, 3 h), the log saying where the PR is in the queue every 5 min (one read is
#                                 one GitHub call from the hour's shared budget, so it is not polled faster; the first looks after the call come every 10 s until the entry shows, QUEUE_GRACE, 3 min). MERGED: the merge commit GitHub made is the one to deploy. A PR that was in the queue and is not any more, and is not merged
#                                 (GitHub confirms it on a second read 10 s later): the reason GitHub gave is read from the timeline (`RemovedFromMergeQueueEvent`), and the release fails "merge queue" with it before any deploy, the queue of releases going on with the others (a skip: the PR is not merged).
#                                 Only a removal for a conflict with main that is only the snapshot (2a) is mended and enqueued again. A PR closed meanwhile fails "pr state"; one still in the queue after QUEUE_WAIT fails "merge queue" (it may merge later: the next release's deploy carries it).
#                                 Then the head branch: the open PRs based on it (`gh pr list --base`) are retargeted to main (`gh pr edit --base main`, one log line each), and the branch is
#                                 deleted best-effort; a PR that cannot be listed or retargeted keeps the branch and the log says why (GitHub closes a PR whose base is deleted), the release goes on;
#                                 4. the deploy lock: the deploy runs under an exclusive flock on <paths.state>/releases/deploy.lock, waited for up to 15 min (DEPLOY_LOCK_WAIT, seconds); past that the release fails "deploy lock":
#                                 merged, not deployed (./deploy.sh by hand once it is free). Two releases never deploy at once, and the waits for GitHub happen before and outside the lock, so no release waits for another one's CI. The lock is released when
#                                 deploy.sh returns; fd 9 is closed for every child (a service a deploy leaves behind never inherits it). Only release.sh takes it: a deploy.sh run by hand does not;
#                                 4a. ALREADY LIVE: when the live checkout contains the merge (a release that merged after this one's merge deployed past it, or deploy.sh was run by hand) there is nothing to deploy: the log says so, the session pick,
#                                 the report and main's run for the merge follow as after a deploy, and the report says "already live";
#                                 4b. DEPLOY GATE (deploy_gate): the merge was tested by GitHub on the tree it made, so it deploys at once when what lies between the live checkout and the merge is not known to be bad: (a) the live checkout is an ancestor of
#                                 the merge (deploy.sh fast-forwards; commits between them are merges of the queue or docs-only merges, all tested), (b) there is a last-good commit to roll back to ($LOGDIR/last-good, below) that is in the live history, and (c) no commit after it
#                                 has a FAILED run on main (read from GitHub's list of runs, page after page, up to 10 of 100, until a run at or before the last-good commit; empty, crashed or never reaching it: unreadable; so is a run in the range cancelled after its job started,
#                                 while one cancelled while queued was replaced and does not count); a pending run does not count: back-to-back releases stay fast, and if the first one's run fails both are rolled back. A pending-verify record of a killed release (below) that is not read yet
#                                 closes the gate too. The record is read, compared and written under flock on last-good.lock; one it cannot read (not a sha, a commit this checkout does not know) is never overwritten, it is told to the keeper and the gate stays closed. First use: the live HEAD, when its run on main passed.
#                                 When the gate is closed (a failed or unreadable run since the last good commit, as after a rollback, until a pass on a newer commit records itself) the release waits for main's tests before it deploys (4d), the reason in the log;
#                                 4c. ./deploy.sh pinned to the merge commit (DEPLOY_TO; units, restarts, /healthz), the lock let go, the session pick (its recycle or notice) and the one report (green) follow the deploy, "main's full run follows"; then main's run for the merge
#                                 commit is waited for (main_green post: a run on it or on a later commit that contains it, see "Main's tests" below), outside the lock. Just before deploy.sh runs (production changes at its fast-forward, and the restarts and healthz take up to 180 s) a pending-verify
#                                 record (commit, PR, time) goes under <paths.state>/releases/pending-verify/, its flock held by this process; a failed deploy clears it with its red report, and it is removed when the watch concludes. A release that is killed in between leaves it with the
#                                 lock free, and the next release to start (before anything else) reads that commit's main run once: pass -> last-good; fail -> the rollback and red report a live watch would make, for that PR (the record stays unless
#                                 the rollback reached a verdict: a lock timeout keeps it); still pending, only cancelled runs, or no run found / GitHub unreadable (never a verdict) -> kept, and the gate stays closed until it is read (after two hours: unknown, a red report).
#                                 Records are taken oldest deploy first. Main's run for the merge commit itself:
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
#                                 4d. MAIN'S TESTS FIRST (only when the deploy gate is closed, or the live checkout cannot fast-forward to the merge cleanly): a PR runs only the suites its change reaches, so the deploy waits for a run on main that covers the PR's merge
#                                 commit M, where every suite runs: a run on M or on a later commit that contains it (several PRs merged close together: a run cancelled by a newer push is not a failure, and the run on a later commit decides); up to WAIT_MAIN
#                                 (90 min by default, for a slow run on a loaded host) counted from when that run starts, and 3 h at most from the merge; its suites failing stops here, merged and not deployed (main_green below, the rule in full).
#                                 The wait looks at main's runs every POLL_MAIN s (60) and the reads are shared between the releases on the box for GH_TTL s (45), so six releases waiting on one run cost what one does. The deploy lock is let go for that
#                                 wait and taken again for the deploy, so a release waiting on main never holds another one's deploy (a lock still held after 15 min then fails "deploy lock": merged, not deployed). Then ./deploy.sh pinned to the commit main's
#                                 tests passed on (DEPLOY_TO: the newest commit that contains M whose run passed, never a tip with no passing run);
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
# and lists a workflow run of that commit that has not completed (queued or in progress), the cycle makes NO GitHub call (no `gh pr checks`, no git fetch, no `gh run list`/`view`)
# and the wait goes on exactly as a pending check would make it; the log says so (a line at the start and every 5 min). The file can only make a release WAIT, never pass or fail one,
# as in salamander's own release.sh: when the poller shows the run completed, when no run of the sha is listed (the file is a window of 30 runs, so a missing sha proves nothing and is never
# a failure), when the file is missing, stale or unreadable (exit 3, 4, 5, or any other), or when salamander is not on PATH, the cycle does the GitHub read it always did, and that read
# alone decides pass or fail. So a failing job is noticed when the poller shows the run completed (a minute or two after it fails), not the moment it fails. The main wait keeps
# only main's push runs of the merge commit (what run_state reads). A run the poller shows going counts for
# WAIT_MAIN as a run from run_state does (same run id). RELEASE_CIRUNS_MAX_AGE (120 s; 0 = never ask the poller) is its knob. The wait for the merge queue does not use it (the merge group's runs are not main's push runs): it reads GraphQL.
# The PR-checks wait that does ask GitHub looks every POLL_PR s (RELEASE_POLL_PR, 60; it was 20) through gh_cached, which shares the answer between the releases on the box for GH_TTL s (45)
# in <state>/releases/gh-cache like run_state's reads, keyed by the PR head too, so a wait without a fresh poller file costs a third of what it did.
#
# A change no test can exercise (docs, Markdown, comment-only lines, CI workflow runner/concurrency settings) does not come here:
# it merges at once with the config repo's docs-merge.sh (CONTRIBUTING.md, step 4).
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
LOGDIR="$(python3 config.py state releases)"; mkdir -p "$LOGDIR"
REPORT_TO="$(python3 -c 'import config; print(config.release_report_to())' 2>/dev/null)"; REPORT_TO="${REPORT_TO:-projects/example}"   # [release] report_to: where tell() sends the report of a release; the stand-in page when unset (or when this config.py predates the key)
WAIT_CHECKS="${RELEASE_WAIT_CHECKS:-3000}"   # seconds a PR's checks may stay pending (50 min); the knob lets the tests prove the give-up on a short cap, one scenario pins this default
MERGEABLE_WAIT="${RELEASE_WAIT_MERGEABLE:-180}"   # seconds GitHub may say mergeable UNKNOWN (it recomputes after main moves) before the release gives up; read every 10 s
LOCK_FILE="${DEPLOY_LOCK_FILE:-$LOGDIR/deploy.lock}"      # next to the other release state; DEPLOY_LOCK_FILE / DEPLOY_LOCK_WAIT let the tests point elsewhere
LOCK_WAIT="${DEPLOY_LOCK_WAIT:-900}"                      # seconds: a deploy takes seconds to a few minutes (healthz waits up to 180 s), so 15 min is a stuck one
REGEN_MAX="${RELEASE_REGEN_MAX:-1}"                      # snapshot regenerations (2a) at most in one release: a second conflict after the first push may be a real one, and a loop is never the answer
SNAPSHOT_REGEN="${RELEASE_SNAPSHOT_REGEN:-$HERE/tools/snapshot_regen.py}"   # the helper that mends a conflict on tests/tool_text.snapshot.json alone; RELEASE_SNAPSHOT_REGEN lets the tests point at a stub
TESTS_CHECK="${RELEASE_TESTS_CHECK:-suites}"             # the PR check (the job of tests.yml) that must be reported on a regenerated head before its verdict counts: a quick check alone must not read as a pass
QUEUE_WAIT="${RELEASE_QUEUE_WAIT:-10800}"   # seconds a PR may stay in GitHub's merge queue before the release gives up waiting (3 h: an entry's checks time out after 60 min, and a PR behind a failure is rebuilt and tested again)
POLL_QUEUE="${RELEASE_POLL_QUEUE:-60}"      # seconds between two reads of the PR's merge-queue state while wait_merged waits (every read is a GitHub call from one shared hourly budget)
QUEUE_GRACE="${RELEASE_QUEUE_GRACE:-180}"   # seconds after the enqueue call that GitHub may take to show the entry (eventually consistent); read every 10 s meanwhile, past it a PR that never showed is a failure
START_MAX=4                                 # queued releases running at once (release.sh queue): release.sh's own number, not a setting
WAIT_MAIN="${RELEASE_WAIT_MAIN:-5400}"   # seconds a covering run of main may be going (main_green: counted from when it starts, status in_progress). 90 min: main's full run, every suite measured, can be slow on a loaded host, so 60 min (3600) let a slow run end a release
CAP_MAIN="${RELEASE_CAP_MAIN:-10800}"    # seconds from the merge, at most, that main_green waits for a run that covers it (3 h): a run queued behind others uses none of WAIT_MAIN, this keeps it from waiting forever
NOTICE_TIMEOUT="${RELEASE_NOTICE_TIMEOUT:-60}"   # seconds [fleet] notice_cmd may take (notice_send): past it the command is stopped and the notice counts as not sent, so the report loses its green flag and the next release starts
WAIT_STEPS="${RELEASE_WAIT_STEPS:-600}"  # seconds a run of main that is completed and green may stay without the conclusion of its "run every suite, measured" step (main_green: GitHub fills in the step results some time after the job reports completed, and release.sh once read a run in that gap and failed a green one). 10 min: the gap has been seconds to a minute; past it the step results never came and the release fails as before. Counted on the clock from the first look that saw the gap; no extra GitHub call, the reads are the POLL_MAIN ones
POLL_MAIN="${RELEASE_POLL_MAIN:-60}"     # seconds between two looks at main's runs while main_green waits (a run can take a long time, and every look costs GitHub REST calls from one shared hourly budget; polling every 20 s with several releases waiting could spend it)
POLL_PR="${RELEASE_POLL_PR:-60}"         # seconds between two looks at a PR's checks while wait_pr_checks waits (every look is GitHub calls from one shared hourly budget; a PR's tests take a while). The read is shared between the releases on the box for GH_TTL s, like main's
GH_CACHE="$LOGDIR/gh-cache"              # main's run list and each run's view, kept for GH_TTL s and shared by every release on this box, so releases waiting on the same run ask GitHub once between them
GH_TTL="${RELEASE_GH_TTL:-45}"           # seconds an answer of those reads is reused (0 = never; the tests set it). A run the list says is completed and cancelled needs no run view at all
PENDING_DIR="$LOGDIR/pending-verify"      # one record per deploy whose main run is not read yet: a watch that is killed leaves it, the next release start finishes the job
PENDING_FILE=""; pv_block=""
LAST_GOOD="$LOGDIR/last-good"            # the newest commit whose run on main passed: what a failing main run rolls back to; one sha, written by record_good
QUEUE="$LOGDIR/queue"                    # the release queue (release.sh queue): PR numbers, one a line, in order; $QUEUE.lock its flock, $QUEUE.started the PRs whose release the queue started, $QUEUE.paused why it is paused, $QUEUE.log what it did
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
    out="$(salamander ci-runs "$REPO" --sha "$sha" --max-age "$CIRUNS_MAX_AGE" 2>/dev/null 6>&- 7>&- 8>&- 9>&-)" || return 1
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

say() { echo "$(date -u +%FT%TZ) $*"; }
tell() {  # one message to the project; never fails the run. Extra arguments go to client.py (--release green --pr <url>)
    local text="$1"; shift
    python3 client.py message "$REPORT_TO" "$text" --sender release "$@" >/dev/null 2>&1 9>&- 7>&- 6>&- || say "message not sent: $text"
}
released() {  # $1 = a PR, $2 = its merge commit: main's full run passed on it and it is in $LAST_GOOD. The server settles the open items with a release step
               # for the PR (client.py released; refused unless the merge is in last-good and HEAD): an item whose only open steps are that release is closed, done,
               # with no session turn; one with another open step has the release step ticked and its mover told once, a real notice (the green report is log-only).
               # Never fails the run; what it did, and why an item was left alone, is a log line
    local out
    if out="$(python3 client.py released --pr "https://github.com/$REPO/pull/$1" --sha "$2" 2>&1 9>&- 8>&- 7>&- 6>&-)"; then say "items of PR #$1: $(echo "$out" | sed 's/^stackshot: //' | paste -sd ';' -)"
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
#   bounds it: past it the run fails as it did before ("finished successfully, but its step results never arrived"), and the post caller rolls back like any failure. A run whose job itself did not
#   succeed, with the suites step missing, still fails at once.
# Two callers:
#   main_green pre <M>     before a deploy whose gate is closed (4d at the top): its suites failing stops the release (merged, not deployed: fix forward); every suite
#                          passing deploys, and what else the run found (a suite that failed only when measured and passed plainly, the audit's
#                          selection miss, a later step that failed) goes in the report, which then goes to the keeper instead of green.
#                          The commit it passed on is left in $verified and the deploy is pinned to it (DEPLOY_TO), never to a newer tip with no passing run:
#                          a merge another release lands meanwhile is deployed by that release, after its own run.
#   main_green post <M>    after the deploy at the merge: M is the one deployed, whatever main's tip is by now. It never
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
deploy_gate() {   # $1 = the merge commit M, under the deploy lock. The merge queue tested M on the tree it made, so M deploys at once when what lies between the live checkout and M is not known to be bad:
                  # (a) the live checkout is an ancestor of M (deploy.sh fast-forwards to it; the commits on the way are merges of the queue, each tested, or docs-only merges); (b) a last-good commit to roll back to is recorded and in the live history;
                  # (c) no commit after the last good one has a failed run on main, up to M. A run still pending is fine: back-to-back releases stay fast, and a failure of the first rolls both back. No pending-verify record is unread.
                  # Sets $good (the last good commit to roll back to), or $gate_why and returns 1: the caller waits for main's tests before it deploys (4d)
    local cur st rid verdict rsha detail bad rg cn; cur="$(git rev-parse HEAD)"; gate_why=""
    [ -z "$pv_block" ] || { gate_why="$pv_block"; return 1; }
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
    bad="$(failed_runs "$good" "$1")"
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
            bs="$(printf '%s\n' "${others[@]}" | grep -oE 'Merge pull request #[0-9]+' | grep -oE '[0-9]+' | tr '\n' ' ')"
        fi
    fi
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
    fail "main's tests" "${live_later:+LIVE via a later deploy, }rolled back to ${good:0:7} · $mg_why$covered$removed$units; a rollback does not undo data or state changes the rolled-back commits made; main still holds the failing merge, fix forward or revert it · $recyc"
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

# ---- GitHub's merge queue (steps 3 and 3a at the top). release.sh enqueues with `gh pr merge` and only reads the queue's state; it never removes a PR from it (the CLI cannot).
ghq_read() {   # $1 = the PR. Its state and its merge-queue entry in one GraphQL call: sets $gq_state (OPEN | MERGED | CLOSED), $gq_oid (the merge commit, "" until there is one) and $gq_entry ("" when the PR is not in the
               # merge queue, else "<STATE> <position>"). 1 when GitHub's answer cannot be read
    local out
    out="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){state mergeCommit{oid} mergeQueueEntry{state position}}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null)" || return 1
    out="$(echo "$out" | python3 -c '
import json, sys
try:
    p = json.load(sys.stdin)["data"]["repository"]["pullRequest"]
    e = p.get("mergeQueueEntry") or {}
    pos = e.get("position")
    print(p["state"], (p.get("mergeCommit") or {}).get("oid") or "-", e.get("state") or "-", "-" if pos is None else pos)
except Exception: sys.exit(1)' 2>/dev/null)" || return 1
    local es ep; read -r gq_state gq_oid es ep <<< "$out"
    [ -n "$gq_state" ] || return 1
    [ "$gq_oid" != "-" ] || gq_oid=""
    if [ "$es" = "-" ] || [ -z "$es" ]; then gq_entry=""; else gq_entry="$es position $ep"; fi
}
ghq_reason() {   # $1 = the PR. The reason GitHub gave for the PR's latest removal from the merge queue (the timeline's RemovedFromMergeQueueEvent), into $gq_reason. 1 when the timeline has no such event yet, or cannot be read
    local out
    out="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){timelineItems(last:5,itemTypes:[REMOVED_FROM_MERGE_QUEUE_EVENT]){nodes{... on RemovedFromMergeQueueEvent{reason createdAt}}}}}}' \
        -f o="${REPO%%/*}" -f n="${REPO##*/}" -F p="$1" 2>/dev/null)" || return 1
    # words a log waiter looks for (" FAILED ", " done: ") are softened in what GitHub says
    gq_reason="$(echo "$out" | python3 -c '
import json, sys
try: nodes = [x for x in json.load(sys.stdin)["data"]["repository"]["pullRequest"]["timelineItems"]["nodes"] if x]
except Exception: sys.exit(1)
if not nodes: sys.exit(1)
print(" ".join((nodes[-1].get("reason") or "no reason given").split())[:300].replace(" FAILED ", " failed ").replace(" done: ", " done "))' 2>/dev/null)" || return 1
}
wait_merged() {   # after the enqueue call, in run(): reads the PR until it is MERGED (0, the merge commit in $mergeoid) or has left the merge queue without merging (1, GitHub's reason in $removed_why). A PR closed meanwhile, or still
                  # waiting after QUEUE_WAIT, fails the release. The reads are every POLL_QUEUE s once the entry shows (every 10 s before, for QUEUE_GRACE: GitHub shows a new entry a moment late); one that cannot be read is waited out like
                  # a pending one. Leaving the queue is believed on the second read, 10 s after the first (the entry can vanish a moment before the PR shows merged). Sets $via_queue (1 once the entry was seen). Runs inside run()
    local t0 now waited said=0 seen=0 absent=0 unread=0 poll=10 tries
    t0="$(date +%s)"; mergeoid=""; removed_why=""; gq_state=""; gq_oid=""; gq_entry=""
    while :; do
        now="$(date +%s)"; waited=$((now - t0))
        if ghq_read "$pr"; then
            unread=0
            case "$gq_state" in
                MERGED)
                    if [[ "$gq_oid" =~ ^[0-9a-f]{7,64}$ ]]; then
                        mergeoid="$gq_oid"
                        if [ "$via_queue" = 1 ]; then say "merged by the merge queue as ${mergeoid:0:7}, $((waited/60)) min after the enqueue"
                        else say "merged as ${mergeoid:0:7} without the merge queue (the PR was never in it: the ruleset is off, or it was merged at the enqueue call)"; merge_note="$merge_note; merged without the merge queue (the ruleset may be off)"; fi
                        return 0
                    fi
                    say "GitHub says the PR is merged but has no merge commit to give yet; reading again" ;;
                CLOSED) fail "pr state" "the PR was closed while it waited for the merge queue" ;;
                *)
                    if [ -n "$gq_entry" ]; then
                        seen=1; via_queue=1; absent=0; poll="$POLL_QUEUE"
                        [ $((now - said)) -lt 300 ] || { said=$now; say "in the merge queue ($gq_entry): $((waited/60)) min since the enqueue, up to $((QUEUE_WAIT/60)) min; reading it every $POLL_QUEUE s"; }
                    elif [ $seen = 1 ] || [ $waited -ge "$QUEUE_GRACE" ]; then   # it was in the queue, or never showed: not there on this read
                        absent=$((absent+1))
                        if [ $absent -ge 2 ]; then   # and not there, not merged, ten seconds later: it was removed
                            gq_reason=""; for tries in 1 2 3; do ghq_reason "$pr" && break; [ $tries = 3 ] || sleep 10; done
                            if [ -n "${gq_reason:-}" ]; then removed_why="removed from the merge queue: $gq_reason"
                            elif [ $seen = 1 ]; then removed_why="left the merge queue, and GitHub's timeline gives no reason (no removal event)"
                            else fail "merge queue" "the PR did not show in the merge queue within $((QUEUE_GRACE/60)) min of the enqueue call and is not merged (the call said it was accepted)"; fi
                            say "$removed_why"; return 1
                        fi
                        sleep 10; continue
                    fi ;;
            esac
        else
            unread=$((unread+1)); [ $((now - said)) -lt 300 ] || { said=$now; say "GitHub's answer about the PR could not be read ($unread read(s) in a row); trying again"; }
        fi
        [ $waited -lt "$QUEUE_WAIT" ] || fail "merge queue" "still $([ -n "$gq_entry" ] && echo "in the merge queue ($gq_entry)" || echo "not merged") $((waited/60)) min after the enqueue, which is as long as this release waits; the PR may still merge, and the next release's deploy carries it"
        sleep "$poll"
    done
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
q_is_started() { [ -n "${1:-}" ] && q_started_list | grep -qx "$1"; }
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
q_start_next() {   # under the lock: the release of every waiting PR (not started yet), in order, until START_MAX queued releases are running. A PR stays in the queue file until it is deployed. One that cannot be
                   # started is logged and taken out. $1 = who asks (for the log)
    local n out live=0 started=0 s; local -a gone=()
    if [ -f "$QUEUE.paused" ]; then say "the release queue is paused ($(head -1 "$QUEUE.paused")): no release started; release.sh queue --resume goes on"; return 0; fi
    q_read
    if [ "${#q[@]}" -eq 0 ]; then rm -f "$QUEUE.started"; say "the release queue is empty: nothing more to start"; return 0; fi
    for n in "${q[@]}"; do if q_is_started "$n" && q_alive "$n"; then live=$((live+1)); fi; done
    for n in "${q[@]}"; do
        q_is_started "$n" && continue   # started already (running, or killed: --resume clears the mark and starts it again)
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
queue_after_fail() {   # fail(): what the failure does to the queue, by $q_fail (skip: before the merge; held: stopped by the pause before the enqueue; pause: after the merge; none). Sets $q_note for the report
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
        none) [ $qstart = 1 ] || return 0   # a main run that was not read is no failure of the code: not paused. The PR is merged, so it leaves the queue and the waiting ones start
              q_handoff "ended with main's run not read"; q_note="; the release queue goes on (main's run not being read is not a failure of the code)" ;;
    esac
}
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

run() {
    local pr="$1" recycle="${2:-}" log="$LOGDIR/pr-$1.log" title sha restarted step rc_note="" merge_note="" audit_note="" verified="" ROLLED_MARK="$LOGDIR/pr-$1.rolledback" mg_notlive="" q_fail=skip q_note="" q_riders="" qstart=0
    exec > >(tee -a "$log") 2>&1
    say "release of PR #$pr starts in $HERE ($REPO)"
    ! q_is_started "$pr" || qstart=1   # the queue started this release (it wrote the mark before the start): its pause and its pre-enqueue stop apply to it
    fail() { say "FAILED at $1: $2"; queue_after_fail "$1"; tell "[release] PR #$pr FAILED at $1: $2$q_note · log $log"; exit 1; }
    recover_pending   # a deploy of an earlier release whose process ended before main's run was read (killed, the box restarted): looked at first
    local view state mergeable regens=0 regen_pushed=0 headsha="" mergeoid="" removed_why="" via_queue=0 good="" gate_why="" fast=0 live_now=0 fast_note=""
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
        if [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ]; then
            say "GitHub says mergeable UNKNOWN (it is still computing, as it does after main moves); reading again every 10 s for up to $((MERGEABLE_WAIT/60)) min"
            while [ "$mergeable" = UNKNOWN ] && [ "$state" = OPEN ] && [ $mwaited -lt $MERGEABLE_WAIT ]; do sleep 10; mwaited=$((mwaited+10)); read_view; done
        fi
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
    enqueue_pr() {   # 3. `gh pr merge --merge --match-head-commit <head>`: on a branch the ruleset requires the merge queue for, it adds the PR to the queue (its required checks have passed: step 2). Pinned, so a push after the checks cannot ride in
        local out err i seen=""
        if out="$(gh pr merge "$pr" --repo "$REPO" --merge --match-head-commit "$headsha" 2>&1 9>&-)"; then say "enqueued: gh pr merge accepted the head ${headsha:0:7} ($(echo "$out" | tail -1 | cut -c1-160))"
        else   # the call can error after the PR was queued or merged (a 504, or a PR queued already): GitHub's answer is eventually consistent, so ask again
            err="$(echo "$out" | tail -1)"; say "the merge call errored: $err; reading the PR's state again"
            for i in 1 2 3 4 5 6; do
                if ghq_read "$pr" && { [ "$gq_state" = MERGED ] || [ -n "$gq_entry" ]; }; then seen="${gq_state}${gq_entry:+, in the merge queue ($gq_entry)}"; [ -z "$gq_entry" ] || via_queue=1; break; fi
                [ $i -lt 6 ] && sleep 10
            done
            [ -n "$seen" ] || fail "merge" "$err"
            say "the merge call errored ($err) but the PR is $seen; carrying on"
            merge_note="; the merge call errored ($err) but the PR was $seen"
        fi
    }
    mergeable_stage start
    say "PR #$pr: $title (head ${headsha:0:7})"
    if [ "$regen_pushed" = 1 ]; then wait_pr_checks "pr tests" progress "the PR's tests pass on the pushed head ${headsha:0:7}"   # as after a regeneration below: a quick check alone must not read as a pass on the new head
    else wait_pr_checks checks quiet "checks pass"; fi
    q_paused_stop   # the wait for the checks can be long: a pause that came meanwhile stops this release before it enqueues the PR
    # 3, 3a: enqueue and wait for GitHub to merge. A PR removed from the merge queue for a conflict that is only the snapshot is mended and enqueued again (at most REGEN_MAX times in the release); any other removal fails the release before a deploy
    while :; do
        enqueue_pr
        wait_merged && break
        mergeable_stage removed
        [ "$regen_pushed" = 1 ] || fail "merge queue" "$removed_why"
        wait_pr_checks "pr tests" progress "the PR's tests pass on the regenerated head ${headsha:0:7}"
        q_paused_stop
        say "enqueueing the PR again on the regenerated head ${headsha:0:7}"
    done
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
    if git merge-base --is-ancestor "$mergeoid" "$cur"; then   # 4a
        live_now=1; fast=1; verified="$mergeoid"
        say "already live: the live checkout (${cur:0:7}) contains the merge ${mergeoid:0:7} (a later release deployed past it, or deploy.sh was run by hand); nothing to deploy, main's full run is waited for as after a deploy"
        fast_note="; already live: the live checkout ${cur:0:7} contained the merge when this release took the deploy lock; nothing was deployed here, and main's full run is waited for"
    elif deploy_gate "$mergeoid"; then   # 4b, 4c
        fast=1; verified="$mergeoid"
        say "deploying ${verified:0:7} at once: the merge queue tested it on the tree it made; main's full run follows; ${good:0:7} is the last good commit to go back to"
        fast_note="; deployed at the merge (GitHub's merge queue tested it on the tree it made): main's full run follows and rolls it back to ${good:0:7} on a failure"
        pending_set "$verified" "$pr"   # before deploy.sh: production changes at its fast-forward, and the restarts and healthz take up to 180 s; a kill in there must leave the record
    else   # 4d
        say "not deployed at the merge yet: $gate_why; the deploy waits for main's tests"
        fast_note="; the deploy gate was closed ($gate_why), so the deploy waited for main's tests"
        # main's tests run outside the lock: a release waiting on main's run must not hold another release's deploy,
        # so the lock is let go for the wait and taken again for the deploy
        exec 9>&-
        main_green pre "$mergeoid"
        take_lock "merged, not deployed (./deploy.sh by hand once it is free)"
    fi
    local out="" rc=0
    if [ $live_now = 1 ]; then exec 9>&-; sha="$(git rev-parse --short HEAD)"
    else
        out="$(DEPLOY_TO="$verified" ./deploy.sh 2>&1 9>&- 7>&- 6>&-)"; rc=$?; echo "$out"
        sha="$(git rev-parse --short HEAD)"
        [ $rc -eq 0 ] || q_pause_now "deploy"   # a failed deploy pauses the queue before the lock is let go, as a rollback does
        exec 9>&-     # the lock is released here: the failure report, the recycle step and the message below start children that must not inherit it
    fi
    [ $rc -eq 0 ] || { pending_clear; fail "deploy" "$(echo "$out" | tail -1) (main is merged at $sha; the checkout is at $(git rev-parse --short HEAD))"; }   # reported red here: nothing left to verify
    restarted="$(echo "$out" | sed -n 's/^  restarted //p' | tr '\n' ' ')"; restarted="${restarted:-nothing}"
    if [ $live_now = 1 ]; then say "done: $sha, already live, restarted nothing"; else say "done: $sha, restarted $restarted"; fi
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
    queue) shift; queue_cmd "$@"; exit $? ;;
    ''|-h|--help) sed -n '2,/^set -uo pipefail/{/^set -uo pipefail/!p}' "$0"; exit 2 ;;   # the header comment, up to the first line of code
    *)
        pr="$1"; [[ "$pr" =~ ^[0-9]+$ ]] && [[ "${2:-}" =~ ^(|--recycle|--no-recycle)$ ]] && [ $# -le 2 ] || { echo "usage: release.sh <pr> [--recycle | --no-recycle] | --status [pr] | --run <pr> [--recycle | --no-recycle] | --pick <pr> | --pick-files <file>... | queue N [N...] | queue --list | queue --drop N | queue --resume" >&2; sed -n '/^# How to run it/,/^#   - Auto mode/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
        if systemctl --user is-active --quiet "stackshot-release-$pr.service" 2>/dev/null; then echo "release of PR #$pr is already running (release.sh --status $pr)"; exit 1; fi
        systemd-run --user --quiet --collect --unit "stackshot-release-$pr" -p WorkingDirectory="$HERE" \
            --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" "$HERE/release.sh" --run "$pr" ${2:+"$2"} \
            || { echo "could not start stackshot-release-$pr (systemd-run failed): nothing was started" >&2; exit 1; }     # uv, gh, python3 and the fleet tool as the shell sees them; a start that failed is said so (the queue skips it)
        echo "started stackshot-release-$pr: enqueues PR #$pr in the merge queue when its checks pass, deploys what GitHub merges, picks what the sessions need (${2:-from the files it changed}), and reports to $REPORT_TO · log $LOGDIR/pr-$pr.log"; exit 0 ;;
esac
exit 0
