---
name: verify-stackshot
description: Prove a change to stackshot on a running app. Starts a scratch instance (fixture data, a local port, nothing leaving the machine), drives its MCP tools and web pages over real HTTP and prints a transcript with a PASS or FAIL line. Use when a pull request's "Done when" check is about what a tool or a page does, or before saying that a change to either works.
---

# Verify stackshot on a running instance

Two surfaces: the MCP tools (what a session uses) and the web pages (what a person reads and answers). One command launches an instance, checks it, drives it and takes it down; no server is left running. The map of what to drive is [features/README.md](features/README.md).

## Launch

From the root of the checkout under test:

```sh
evidence="${XDG_STATE_HOME:-$HOME/.local/state}/stackshot/verify"; mkdir -p "$evidence"
log="$evidence/$(git rev-parse --short HEAD)-all.log"
tests/run-suite verify_app_check all > "$log" 2>&1; echo "exit=$?"; cat "$log"
```

`tests/run-suite` builds the shared test environment on its first run (it needs `uv`). Where a machine sends its test runs elsewhere ([docs/development.md](../../../docs/development.md#sending-test-runs-to-another-machine)), the runner does that itself. A journey file must be among the files sent, so keep it out of ignored folders.

Ready is the line `ready: http://127.0.0.1:<port>` followed by the doctor's `ok` lines. The instance:

- the fixture of the front door suite (`tests/frontdoor_board_scenario.py`): project `projects/alpha` with the session `sparrow`, one open item `a1`, a one-line rulebook;
- its own config, store, state, secrets and `HOME` in scratch folders, on a free port, so runs side by side do not share anything;
- `[auth]` off (the MCP endpoint and the pages are open), plus one made-up address signed in with a cookie the run signs with the instance's own key, because the page forms ask for a signed-in viewer;
- `[publish] git` off, the GitHub mirror off, no inherited `STACKSHOT_*` setting;
- a guard in the process that refuses, and lists at the end, every connection off the loopback and every program the server tries to start, except a git that reads the scratch folders or the checkout.

## Doctor

Read only. Run it first when anything looks off; every run also does it before the journeys, and drives nothing if it fails.

```sh
tests/run-suite verify_app_check doctor
```

It checks that the code under test is this checkout's, the config and its paths are the scratch ones, publishing and the mirror are off, `/healthz` answers, the MCP endpoint lists the tools, the signed-in viewer is accepted (and a signed-out one gets no forms), and the guard refuses an outside address.

## Drive

```sh
tests/run-suite verify_app_check item answer pages        # any of them, in this order; `all` is the three
tests/run-suite verify_app_check --journey <file.py>      # a file that defines journey(app)
```

A journey gets `app` and uses only the paths a user has:

| Handle | What it does |
|---|---|
| `app.call(tool, **args)` | a tool call over HTTP; returns `(ok, text)`, a refusal being `ok = False` |
| `app.tools()` | the tool names the endpoint lists |
| `app.page(path, signed=True)` | GET; returns `(status, page)` with `page.text` (visible text), `page.forms`, `page.form("ianswer")` |
| `app.shows(name, page, *words)` | checks each word is in the visible text and prints its surroundings |
| `app.post_form(path, fields, origin=None, signed=True)` | a form POST as a browser sends it; returns `(status, headers, text)` |
| `app.item(key)`, `app.items()` | the stored record and the stored files: the second view of a write |
| `app.check(name, cond, got=None)` | one check; `got` is printed when it fails |

## Prove a pull request

1. Write each "Done when" check about a tool or a page as checks in a journey: in the journey of the feature the change touches (they stay as coverage), or, when only this pull request needs them, in a file of their own passed with `--journey`. Commit whatever the check names.
2. Show that the check can fail. Make a worktree of the base (`git worktree add <dir> <base>`), copy this branch's `tests/verify_app_check.py` and the journey file into it, and run the same command there. It must FAIL on the named check, for the reason the change is about; a crash or a failed doctor proves nothing.
3. Run it on the head. It must PASS.

That pair, red on the base and green on the head, is the main proof of a change's behaviour, in place of mutation testing. Mutation testing stays useful for parsers, validators and state machines, where the inputs matter more than one path through the app.

A "Done when" line names the command and the result, for example: ``tests/run-suite verify_app_check --journey tests/<file>.py` ends `verify_app_check: PASS` on the head and fails the check "<name>" on the base`.

A journey file:

```python
from verify_app_check import created, sample

def journey(app):
    key = created(app, **sample("page is read"), next="sparrow: read the page", mover="sparrow")
    if key:
        status, page = app.page(f"/items/{key}")
        app.check("the item page answers", status == 200, status)
        app.shows("the item page", page, "read the page")
```

Not proven here: anything the pages' scripts do (the browser checks named in [CONTRIBUTING.md](../../../CONTRIBUTING.md) and CI), the real sign-in, the server's start-time passes and background threads, the runners and the router, delivery of messages to sessions, GitHub, and a deploy or release.

## Evidence

The run's output is the evidence: each call (`mcp>`), request (`http>`) and form (`form>`), the first lines of each reply, the page text around each match, every `ok` and `FAIL`, what the guard refused, the teardown line and the last line:

```text
verify_app_check: PASS|FAIL journeys=<names> checks=<n> failed=<m>
```

Exit status 0 is a pass, 1 a failure, 2 a command line that was not understood. Save the output outside the checkout, in `${XDG_STATE_HOME:-~/.local/state}/stackshot/verify/` (the Launch command does): no cleanup touches that folder, and it outlives the worktrees. Quote the command, the commit, the checks that matter and the last line. The log carries the folder paths of the machine that ran it, so quote lines and do not paste the whole file into a public place.

Use the real path: a journey calls tools and sends requests, and does not call the server's functions to set up the state it then reads. Check what a write left behind (`app.item`) as well as what the reply says. If the fixture lacks something a journey needs, let it fail and note why in the feature file; do not weaken the journey.

## Cleanup

The run cleans up itself, pass or fail: it stops its server and removes its scratch folders, which are locked while it runs (`tests/_scratch.py`, `tests/run-suite`). It prints `server stopped: yes; scratch folders removed: yes`; a `NO` fails the run. Never stop anything by process name. Remove the base worktree you made (`git worktree remove <dir>`).

## Helpers

`tests/verify_app_check.py` is the whole harness, run only through `tests/run-suite verify_app_check ...`. Its name ends `_check`, so it is a manual check that CI does not run. It builds on the front door suite's `setup` and `serve`.

When a journey changes, change its feature file in the same pull request.
