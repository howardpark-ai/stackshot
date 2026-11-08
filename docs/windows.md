# The Windows client

What this page covers: how a Windows machine joins the board as a client, with its token, its puller and its Claude Code hooks. Back to the [README](../README.md).

A Windows machine where Claude Code runs is a client of the stackshot server, like any other machine: it holds a
machine token, runs one puller (or none, below), and has the page hooks in its Claude Code settings. Its config is
written by `client install` from the instance's own settings, read from the server; the two files below hold the token
and the address.

This page describes what the code supports today. Points marked **to verify** are not covered by the repository's
tests or code and should be checked on a real box before they are relied on.

## What the box needs

- A checkout of this repository (for `stackshot`, `stackshot/fleet/puller.py`, `stackshot/fleet/client.py`, `stackshot/core/config.py`, `stackshot/projects/pages.py` and the hook
  scripts in `client/hooks/`).
- Python 3.11 or later on the box, including `pythonw.exe` for the puller. The puller and the client are stdlib only.
- Git for Windows, with Git Bash reachable as a bare `bash` (for the hooks, below).
- Claude Code, signed in to the account that has the stackshot connector.

## The token, the address and the hooks

On the server box, mint a token for the machine:

```
bin/stackshot client mint <machine>
```

The server keeps only the token's SHA-256; the token itself is written to `<secrets>/client-tokens/<machine>.token`
and never printed (the command prints only the file's path). Carry that file to the Windows box by whatever private
means you use, then run, from the checkout on the box:

```
python stackshot client install --url https://board.example.com --token-file <path to machine.token>
```

It stores the token as `%USERPROFILE%\.config\stackshot\client.token` and the address, one line, as `client.url`
beside it. The directory is `<secrets>` with its default `~/.config/stackshot`, which Python expands to
`%USERPROFILE%` on Windows. The files are written with mode 0600, which does nothing on Windows: the directory is as
private as your user profile. `stackshot/fleet/client.py` looks for the address in `$STACKSHOT_URL`, then `client.url`, then
`[client] url` in the config.

When the box has no config yet (no `%USERPROFILE%\.config\stackshot\stackshot.toml` and no `STACKSHOT_CONFIG`),
`client install` also writes one: the shipped example with the instance's non-secret settings filled in, read from the
server's `config` read with the new token (instance name, title, owner, timezone and board URL, the page flavor and
directories, `paths.brain` as text, the subject prefixes, `[page_gate]`, `[board_check]`, the mirror URL, the connector path). So the
nag on this box prints its times in the instance's timezone (`UTC` unless configured) and words its advice in the
instance's page flavor. A config that is already there is never overwritten. If the server cannot be reached at that
moment, the example's defaults apply (UTC, plain pages) until `client install` runs again.

There is no `systemctl` on Windows, so `client install` skips the puller step (it says so and names the command to
run, `pythonw <checkout>\stackshot/fleet/puller.py` as a scheduled task at logon) and the scheduled task below stays a manual step. It then merges the four hooks into
`%USERPROFILE%\.claude\settings.json` the same way as on Linux: it prints the diff, backs up an existing file to
`settings.json.bak-<timestamp>` and writes. `python stackshot client install --print` shows the hook lines and writes
nothing. The command is covered by the repository's tests on Linux only: running it on Windows is **to verify**.

Check from the box: `python stackshot/fleet/client.py get whoami` answers the machine's name.

For the client API to reach the server from outside, whatever sits in front of the server must let `/client/*` through
with the machine's bearer token. An access proxy that asks for a browser sign-in (Cloudflare Access, for example)
needs a bypass rule for that path.

## The puller as a scheduled task

On Linux the puller is a user unit. On Windows it runs as a scheduled task at logon:

```
pythonw stackshot/fleet/puller.py
```

`pythonw` runs it without a console window. The puller holds a long poll open to the server (about one request a
minute when idle), reports the sessions live on the box from the CLI's registry (`%USERPROFILE%\.claude\sessions`),
and writes each waiting line into the session's named pipe (`\\.\pipe\LOCAL\cc-msg-…`). The pipe's peer token is read
from the sidecar `<pid>.<hash>.key` in the same registry and never leaves the box. The puller checks whether a process
is alive through the Windows API rather than `os.kill`, which would terminate the process on Windows.
The puller starts its own child processes (the CLI version probe, `claude --version`) without a window, so a console
program it runs does not open a terminal on the desktop. Provisioning restarts the task when `VERSION` in `stackshot/fleet/puller.py`
differs from the version the running puller logged, so a change that running pullers must pick up bumps it.

From puller 8 the helper also reloads itself. Each cycle (between two polls) it reads the `VERSION = "N"` line of its own
`stackshot/fleet/puller.py` on disk; when that differs from the VERSION it loaded (a checkout update replaced the file), `main()` returns
`RELOAD` and the entry point runs the file afresh in the same process (`runpy`, the checkout's `client`, `config` and `said`
imported again), so the scheduled task never sees its process end and the log shows the new `puller <v>: polling` line,
which is what provisioning's check reads. The launcher (`puller-run.pyw`) needs no change. A `stackshot/fleet/puller.py` that is missing, has
no `VERSION` line or does not compile (or a `stackshot/fleet/client.py`, `stackshot/core/config.py` or `stackshot/model/said.py` that does not), as in the middle of an
update, means no reload that cycle. A reload happens at most once in 10 minutes (`RELOAD_MIN_GAP`); a held-back reload is
logged once. A puller older than 8 does not do this: it needs the one task restart that provisioning gives it. That first
restart onto 8 comes from provisioning's version check, which an instance's own provisioning may handle: it can miss a lagging puller
when the last `polling` line has scrolled out of its 400-line log window. A change to `_entry`, `_fresh`, `RELOAD` or
`_RELOAD_FILES` itself takes effect only after a real restart of the task.

Useful checks, run with `python` in a console:

- `python stackshot/fleet/puller.py --list`: the sessions the box would report.
- `python stackshot/fleet/puller.py --once`: one poll, then exit (0 fine, 1 a delivery failed, 2 the server was not reached).
- `python stackshot/fleet/puller.py --dry-run`: fetch, print what would be delivered, confirm nothing; then what the puller would update
  now, or why not (below).
- `python stackshot client install --print`: the hook lines `client install` would write to `settings.json`; it writes
  nothing, so it is safe to run before the real install.

The task is not defined in this repository. A working definition is a provisioning step that registers the task, checked on a host:

- Trigger: one logon trigger for the user; the task runs as that user, interactively, at the highest run level.
- Action: the Python install's `pythonw.exe` running `~\.config\stackshot\puller-run.pyw`, a small launcher, with `~\stackshot`
  as the working directory.
- Settings: no stop on battery, no execution time limit, restart on failure 999 times at one minute, and a second
  start while one runs is ignored.
- Log: the launcher sends stdout and stderr to `~\.claude\stackshot-puller.log`. It gets failure lines only; a
  successful poll writes nothing.

The task survives sleep and resume. It stops at sign-out (result `0x40010004`) and starts again at the next sign-in.
With nobody signed in it is Ready, not Running, by design: there are no panes to deliver to. Restart on failure covers
only a failed start, not a crash in the middle of a session.

The server serves a machine from its inbox: a line for a session on the box waits there until the puller asks (while
it is checking in, within seconds; a box that is asleep gets it when it is back). The same check-ins make the machine
online in the Machines panel.

## The puller keeps the box current

Since puller 9 the puller keeps its own `~\stackshot` checkout current; nothing else pulls it. Provisioning only clones a missing
checkout and never pulls it. With every poll the server says what is current (its checkout
commit) and whether this box may update itself (`[client] self_update`, on by default; never the server box's own). When
the box is behind and idle (no live session in `%USERPROFILE%\.claude\sessions`, no `claude.exe` in the task list: the
hooks run from the checkout under a session, so it is never moved under one), the puller fast-forwards the whole of
`~\stackshot` to the server's commit (`git fetch origin`, then `git merge --ff-only`: the puller, `stackshot/projects/pages.py`, the hooks
under `client\hooks` and everything else the box runs from the checkout; a checkout with local changes or commits of its
own is left alone and the refusal reported; the one exception is a clean checkout whose HEAD is not in `origin/main` while the server's commit is (history rewritten, a branch never merged, its own commits): the puller saves the rollback branch `legacy-<first 12 characters of its HEAD>` at that HEAD, and only then `git reset --keep` moves it onto the server's commit, the recovery recorded in the update record; an ignored untracked file that the server's commit tracks refuses the move instead, since git would replace it without a word), then reloads itself the way described above (`RELOAD`, whether or not the
`VERSION` changed, and without the 10-minute hold-back), so the new `stackshot/fleet/puller.py` runs in the same process. Since puller 10 a clean, idle box
also takes the repository address the server publishes (`repo` in the poll's answer) when its origin is another repository (the repo moved;
the new address is fetched from first, and ssh and https forms of one repository are no move); all of it is `git` commands only, the same on
Windows and Linux. The one thing a box cannot do for itself is a move it cannot start: a puller older than 10 whose origin address no longer
answers cannot fetch the update that teaches it to follow, so its `~\stackshot` origin is set once by hand
(`git -C ~\stackshot remote set-url origin <the new address>`); every later move follows by itself. The scheduled
task's instance never ends: an exec would end it, and the task's repetition trigger would start a second puller beside the
orphan. The log shows `puller <v>: the checkout was updated, reloading` and then the new `puller <v>: polling` line, so
provisioning's own `VERSION` check finds the task current.

The helper has no part in the Claude CLI: it never updates the CLI and the server's poll answer says nothing about CLI
versions (the puller only reports the installed version, `claude --version`, as it always did). The CLI is updated by the machine's own
provisioning.

Idle means no live session and no CLI process. `claude.exe` is also Claude Desktop, so the helper counts only a `claude.exe` whose
path is the CLI it resolves for `claude --version` (CIM, with wmic as the fallback; the router's own call is skipped); if neither
tool answers, the box counts as busy and the log says why. Idle is asked again right before the merge, and a box that became busy
in the meantime is left alone without a failure being recorded.

Before the merge the helper compiles the target's `stackshot/fleet/puller.py`, `stackshot/fleet/client.py`, `stackshot/core/config.py`, `stackshot/model/said.py` and the modules of the checkout
they import, from git, and refuses a commit that does not compile, leaving the checkout where it was. A merge that fails, or whose
result does not compile, is rolled back to the old commit, so the next attempt does not meet a half-merged tree. A reload that
does not load (an import error that compiling cannot see) does not end the task's process: the log shows the traceback, the
attempt is recorded as failed (`reload failed`), those files are not tried again, and the running puller carries on until the
checkout changes.

A target commit is tried once, then again after 1 h, 4 h and daily; each attempt, ok or failed with its reason, is
written to `%USERPROFILE%\.local\state\stackshot\puller-updates.json` and reported to the server with the next poll
(`facts.updates`), where the machine's card shows a failed one only while the box's reported commit (`facts.stackshot`) is not the server's: a box that is where it should be shows green by itself, whatever put it there. A checkout moved to the server's commit by hand is also settled on the next poll with one ok attempt (`already at the server's commit`); do not edit `puller-updates.json` for that. `python stackshot/fleet/puller.py --dry-run` prints what the puller would update
now, or why not (a live session, the backoff). To switch it off for one box, set `self_update = false` under `[client]`
in `%USERPROFILE%\.config\stackshot\stackshot.toml`.

## The hooks

The page gate is `stackshot/projects/pages.py`, run by four hooks in `%USERPROFILE%\.claude\settings.json`: `touch` on PostToolUse
(matcher `mcp__.*`: every MCP tool, so a board write made on the direct connector or inside an MCP portal's Code Mode
script is seen alike; `stackshot/fleet/connectors.py` tells them apart), `nag` on UserPromptSubmit, `check` on Stop and,
on SessionStart, `session-start.sh`, which prints the board's brief and then runs `keeper`. The scripts are in this
repository under `client/hooks/`: `project-page.sh <verb>` forwards to `stackshot/projects/pages.py`, and both source `_python.sh`.
`client install` writes each hook as

```
bash <checkout as C:/…>/client/hooks/<script> [<verb>]
```

with the checkout path in forward slashes, single-quoted when it holds a space or another character the shell would
split on; `session-start.sh` takes no verb. Whether Claude Code on Windows runs that line as written is **to verify**.

Two Windows traps:

- A bare `bash` must resolve to Git Bash. With WSL enabled but unused, `C:\Windows\System32\bash.exe` comes first on
  the PATH and the hooks run in the wrong shell. Put `C:\Program Files\Git\bin` on the PATH and make sure nothing
  ahead of it provides another `bash.exe`.
- The hooks need a Python 3.11 or later. `_python.sh` tries `$STACKSHOT_PYTHON`, then `python3`, `python` and
  `py -3`, and takes the first that runs and is 3.11 or later, so the Microsoft Store alias, which fails that test, is
  passed over. Set `STACKSHOT_PYTHON` when the right Python is none of those. With no suitable Python the hooks do
  nothing and exit 0.

A box with no puller can use the three hook verbs of `stackshot/fleet/client.py` instead: `register` on SessionStart, `seen` on Stop,
and `drain` on UserPromptSubmit, which prints what waits in the server's inbox with the prompt. Each answers within a
few seconds and never fails the hook. `client install --no-puller` wires them through `client/hooks/client.sh` beside
the four page hooks (and installs no puller); `--print --no-puller` shows all seven. The three extra entries it adds:

```json
{
  "SessionStart":     [{"hooks": [{"type": "command", "command": "bash <checkout>/client/hooks/client.sh register", "timeout": 10}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash <checkout>/client/hooks/client.sh drain", "timeout": 10}]}],
  "Stop":             [{"hooks": [{"type": "command", "command": "bash <checkout>/client/hooks/client.sh seen", "timeout": 10}]}]
}
```

Whether these run cleanly under Git Bash on Windows is **to verify**.
