# What a running session reloads

What this page covers: which files a running session picks up on its next call and which only when it starts again. Back to the [README](../README.md).

A release changes files on the server box. Some of them reach a running agent session on its next call; some reach it only when the
session starts again. `release.sh` picks what the sessions need from the files the merged pull request changed, the same way `deploy.sh`
picks which services restart from the files a fast-forward changed. This page is the reasoning behind that pick: which files of this
repository a session loads once, at its start, and which it reads fresh at each use, with the code that shows it.

The map itself is one function, `session_need` in `release.sh`. This table and that function say the same thing; change both together
(`tests/release_scenario.py` reads both and fails when a file the table names has another need in the function).

## The three needs

| Need | When | What `release.sh` does |
|---|---|---|
| **recycle** | A file a session loads once, at its start, and never reads again while it runs. Only a restart of the session delivers a change. | The existing recycle path: the open items anchored to the PR wait for a recycle (`stackshot/fleet/client.py recycle-due --pr`); with none anchored, `[fleet] recycle_when_idle` is asked for one once the box is idle. |
| **notice** | A rule or wording sessions should know about, read fresh where it is used. Nothing needs reloading, but a session that learned the old wording should hear that it changed. | Runs `[fleet] notice_cmd` with one argument appended, "<title> — <summary>" (a newline or tab turned into a space, cut to 400 characters and ending in "…" when cut). Unset: the log says no notice command is set, and the release goes on (still green). A command that fails, is not on `PATH`, or does not finish within 60 seconds (it is stopped) sends the report to the keeper instead of green. |
| **nothing** | Server-only code (the services restart in `deploy.sh`), docs, tests, and a script run fresh at each call. | Nothing for the sessions. |

The highest need among the changed files wins, with one exception: a recycle does not deliver a notice's change (the tools' text and the write rules are read
fresh, never at a session's start), so when some changed files need a recycle and some file also needs a notice, the release does both: the recycle runs as
above and the notice is sent too. The pick then reads `recycle + notice`, in the log, the report and the dry runs. `release.sh <pr> --recycle` forces a recycle and `--no-recycle` forces nothing, whatever the files
say. The log and the one report name the pick and the files it came from. `release.sh --pick <pr>` and `release.sh --pick-files <file>...` print
the pick and each file's need, and do nothing else.

## What a session loads once

Everything a running agent session reads from this repository falls in one of four kinds. Only the first is loaded once, at the session's start.

1. **SessionStart output.** Claude Code runs the SessionStart hook once when a session starts (also on resume and after a compaction) and puts what
   it prints into the session's context. Nothing runs it again. Three things print there: the board's brief (`stackshot/fleet/client.py get brief`, which the server
   composes; on the server box `stackshot/web/publish.py brief` renders it when the server cannot be reached), the keeper's Current state of the pages a session
   keeps (`stackshot/projects/pages.py keeper`: `cmd_keeper`, `inject_text`), and, on a box with no puller, `stackshot/fleet/client.py register`. `client/hooks/session-start.sh` is
   the one script of this repository that wires the first two together, so it is the **recycle** file.
2. **Hooks at every event.** `UserPromptSubmit`, `PostToolUse` and `Stop` spawn their command again for each event, and every script starts a new
   Python process on a file of the checkout (`client/hooks/project-page.sh` runs `stackshot/projects/pages.py nag`, `touch` and `check`; `client/hooks/client.sh` runs
   `stackshot/fleet/client.py drain` and `seen`). A change to those files is in force at the next event of every running session: **nothing** to reload.
3. **The connector.** The MCP connector is the server's HTTP endpoint (`[server] path`, `/mcp` by default), reached through claude.ai; this repository
   has no stdio MCP server and no process a session starts and keeps. A session learns the connector's instructions and tool list when its client
   connects, and claude.ai keeps its own cached copy and refreshes it within about a day (a comment above `_RELAUNCH` in `stackshot/web/server.py` says so), so a
   recycle does not deliver a change to them. `tests/tool_text.snapshot.json` holds that text (`instructions`, `resources`, `tools`) and CI makes every
   change to it change the file: a **notice**. Rules the server enforces at each write are the same kind (the server reads them fresh at each call).
4. **The server's own state.** The services restart in `deploy.sh`, and sessions reach them through the connector or the client API at each call: **nothing**.

What this repository does not contain, and so what no pick here can reach: skills, plugin files and plugin hooks (a plugin is its own repository; its
hooks run `stackshot/projects/pages.py` of this checkout as a new process at each event, so they fall under kind 2, and its SessionStart entry runs `stackshot/projects/pages.py keeper`,
kind 1), a rule file a session loads through its CLAUDE.md (the rulebook the `rules` tool serves is a file outside the checkout, read at each call;
`_rules_text`, `stackshot_rules` in `stackshot/web/server.py`), a status line, and a settings file (`stackshot client install` writes the hook registration into
`~/.claude/settings.json` of a box; see below).

## How the hooks are registered

`bin/stackshot client install` writes the registration into `~/.claude/settings.json` (`hook_entries`, `merge_hooks`, `cmd_client_install` in `stackshot/cli.py`;
`bin/stackshot client install --print` shows it without writing). The entries are `bash <checkout>/client/hooks/<script> <verb>` commands:

| Event | Command | With `--no-puller` also |
|---|---|---|
| `SessionStart` | `session-start.sh` | `client.sh register` |
| `UserPromptSubmit` | `project-page.sh nag` | `client.sh drain` |
| `PostToolUse` (matcher `mcp__.*`, every MCP tool) | `project-page.sh touch` | |
| `Stop` | `project-page.sh check` | `client.sh seen` |

Claude Code reads the registration when a session starts. A box that runs the stackshot plugin has its hooks in the plugin's own `hooks.json` and
none from `client install`; they run the same `stackshot/projects/pages.py` verbs of this checkout. Either way a change to the registration (`hook_entries`,
`HOOK_SIGNS`, `CONNECTOR_TOOLS` in `stackshot/cli.py`) reaches a box only when `bin/stackshot client install` runs there again, and a release does not run
it: release such a change with `--recycle` once the boxes are reinstalled.

## How a session reads each file

| File (pattern) | How a session reads it | What a change needs | The code that shows it |
|---|---|---|---|
| `client/hooks/session-start.sh` | The SessionStart hook, kind 1: what it prints (the brief, then the keeper's Current state) enters the context when the session starts and never again. | recycle | `hook_entries` (`SessionStart`) in `stackshot`; the script itself |
| `tests/tool_text.snapshot.json` | The connector's instructions and tools' text (names, parameters, descriptions, returned-line labels), kind 3. A session learns them when its client connects, and claude.ai's cached copy is refreshed on its own within about a day. The brief carries a what-changed line for 7 days after the server starts on a new snapshot. | notice | `record` in `stackshot/web/whatschanged.py`; `live_snapshot` in `tools/tool_text.py`; CONTRIBUTING.md, *The tool-text gates* |
| `stackshot/model/next_rules.py`, `stackshot/model/model_guards.py`, `stackshot/model/owner_steps.py`, `stackshot/model/bullet_text.py` | The write rules the server enforces on a session's creates and updates (who takes a next line, the item model's guards, the steps the server adds and ticks on a checklist, the bullet form). Imported by the server, so `deploy.sh` restarts it; checked at each write, so nothing in a session reloads, but a session that writes by the old rule meets a refusal. | notice | `import next_rules` and `_gate_model` in `stackshot/web/server.py`; `*.py` in the restart map of `deploy.sh` |
| `audit_rubric.txt` | The rubric the daily audit judges a session's items by. Read by the audit's own process at each run. | notice | `RUBRIC` and `judge` in `stackshot/audit/audit_run.py` |
| `client/hooks/client.sh`, `client/hooks/project-page.sh`, `client/hooks/_python.sh` | Per-event hooks, kind 2 (`UserPromptSubmit`, `PostToolUse`, `Stop`, and `register`, `seen`, `drain` without a puller). Each event spawns the script again, which sources `_python.sh` and starts a new Python process. | nothing | `hook_entries` in `stackshot`; the `exec` line of each script |
| `stackshot/fleet/client.py` | The client CLI, a new process at each call (by the hooks, by `session-start.sh`, by a session's own shell). Its start-time verbs (`get brief`, `register`) print or post once per session start, so a changed verb is met by the next session that starts, which is no reason to restart one. The long-running puller imports it, and `deploy.sh` restarts the puller when it changes. | nothing | `hook` and `main` in `stackshot/fleet/client.py`; `import client` in `stackshot/fleet/puller.py`; the `stackshot/fleet/client.py` case of the restart map in `deploy.sh` |
| `stackshot/projects/pages.py` | The page gate: `nag`, `touch` and `check` run per event by the hooks. Its `keeper` verb is SessionStart output (kind 1); a changed keeper text reaches each session at its next start, which is no reason to restart one. | nothing | `cmd_nag`, `cmd_touch`, `cmd_check`, `cmd_keeper`, `inject_text` in `stackshot/projects/pages.py` |
| `stackshot` | The setup CLI, run by hand. It writes the hook registration, which a session reads at its start, but a release does not run it (see *How the hooks are registered*). | nothing | `hook_entries`, `merge_hooks`, `cmd_client_install` |
| `reboot-hooks/*` | Run by the fleet tool at each step of a reboot. | nothing | the header of `reboot-hooks/stackshot-hook` |
| `stackshot/web/server.py` and every other server module, `units/*`, `install.sh`, `icons/*`, `fonts/*`, `*.lock` | Server-side, kind 4. Sessions reach it through the connector or the client API at each call; `deploy.sh` restarts what loads it. | nothing | the restart map in `deploy.sh` |
| `*.md`, `docs/*` | Docs. | nothing | |
| `tests/*` (other than the snapshot above) | Tests. | nothing | |

A file the map does not name is **nothing**. A new file a session loads at its start (a new SessionStart hook, a file such a hook reads, a skill or
plugin file added to this repository, a status line) belongs in `session_need` as a recycle in the same pull request that adds it.
