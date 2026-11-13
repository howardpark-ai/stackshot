# Development

What this page covers: how a change is made, tested and released, what running sessions need after a release, and how to run a local server. Back to the [README](../README.md).

How a change is made, tested and released is in [CONTRIBUTING.md](../CONTRIBUTING.md): a branch in its own worktree, a pull
request against `main`, and `release.sh` on the server box, which puts the PR in GitHub's merge queue and runs `deploy.sh` on what the queue merges. The test suites are
`tests/*_scenario.py` on fixture data, run with `tests/run-suite <name>`: a pull request runs the suites its change reaches, GitHub's merge queue runs every suite on the tree it makes, and main's push stamps that run
(`.github/workflows/tests.yml`, CONTRIBUTING.md *Suite selection*). While `release.sh` waits for a PR's checks or for main's run, each cycle first asks sala's CI-run poller (`salamander ci-runs howardpark-ai/stackshot --sha <sha> --max-age 120`, a file read): a fresh file that lists a run of the commit still queued or in progress makes the cycle wait with no GitHub call; a completed run, a commit the file does not list, a missing, stale or unreadable file, or no `salamander` on PATH sends it to the GitHub read it always made, which alone decides pass or fail (`RELEASE_CIRUNS_MAX_AGE`, 0 = never ask the poller). The PR-checks wait looks every `RELEASE_POLL_PR` (60 s) and shares its read between releases for `RELEASE_GH_TTL` (45 s), like main's wait. A change to what a tool takes, says or returns brings its text with it
(`tests/tool_text.snapshot.json`, refreshed by `python3 tools/tool_text.py update`; the gates, among them the reviewer's read before the merge, for which `tools/text_check.py pack` gathers the text and the diff by hand (no CI job calls a model), are in CONTRIBUTING.md, *The tool-text gates*).
**What the running sessions need after a release** is picked by `release.sh` from the files the merged PR changed, as `deploy.sh` picks the restarts:
**nothing** (server-only code, docs, tests, a script run fresh at each call such as a per-call hook or `stackshot/fleet/client.py`), a **notice** (a rule or wording sessions
should know about but need not reload: the tools' text, the write rules the server enforces, the audit's rubric; `release.sh` runs
`[fleet] notice_cmd` with one argument appended ("<title> — <summary>"), and with none set says so in the log and goes on), or a **recycle** (a file a session
loads once, at its start, such as the SessionStart hook: the open items anchored to the PR wait for a recycle, else `[fleet] recycle_when_idle` is asked).
The highest need wins, except that a recycle with a notice among the files does both ("recycle + notice"). `--recycle` forces a recycle, `--no-recycle` forces nothing. The log and the one report say what was picked and from which files.
The map is `session_need` in `release.sh`; the table, with the code that shows how a session reads each file, is [docs/session-reload.md](session-reload.md).
`release.sh --pick <pr>` and `release.sh --pick-files <file>...` print the pick and do nothing else.
Releases go through GitHub's merge queue: `release.sh` enqueues the PR once its checks pass, waits until GitHub has merged it, deploys the merge and watches main's run (the queue's full run, stamped). Several PRs are released through the release queue (`release.sh queue N [N...]`: every waiting PR's release starts at once, four at a time, so the PRs reach GitHub's merge queue together), and the full measured run is split into six shards: both are in CONTRIBUTING.md (*Several PRs go in the release queue*, *Suite selection*).
For a local server without sign-in:
`STACKSHOT_AUTH=off uv run --extra server stackshot server`, then `curl localhost:8020/healthz`.

The code font is D2Coding (Naver, SIL Open Font License 1.1), vendored in `fonts/` and served by the server itself at `/fonts/D2Coding-Regular.woff2`
(public, versioned by `?v=`, kept a year); `fonts/README.md` has its source, the conversion and how to replace it.
