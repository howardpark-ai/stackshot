# Installing stackshot (board alone): procedure for an AI agent (draft v0.3)

You are a Claude Code agent on the user's Linux box. Follow this file in order. Last checked against the `main` that carries this file (its git log names the commit). Line numbers cite that tree: a later commit moves them, so find the function or message named beside a cite when a number is off. `TODO(verify)` marks what the code could not confirm: check it live and tell the user what you found.
The same procedure for the human reader is [board-alone-guide.md](board-alone-guide.md). The full reference is [INSTALL.md](../INSTALL.md).

## 0. Goal and done-condition

Goal: a working stackshot instance for one person, on this box, reachable over public HTTPS, with claude.ai and Claude Code both using it.

Done when all of these hold. Check each yourself, then report.

1. `./stackshot doctor` prints `all good` and exits 0.
2. `curl -sf https://<base>/healthz` answers, and `https://<base>/.well-known/oauth-authorization-server` returns JSON.
3. A claude.ai chat can call the connector `Stackshot` tool `brief` (the user checks this: hand-off H3).
4. In Claude Code, the tools `mcp__claude_ai_Stackshot__create`, `__update`, `__complete`, `__brief`, `__get` exist, and `create` made a first item that the board page and the data repository show.
5. The data repository has a pushed `main` on its private remote.

Out of scope (mention only as later options): sala, gbrain, a hooks/rulebook layer, anchor-hub, other client machines, the daily audit, the GitHub item mirror, the Cloudflare portal. Leave them off.

## 1. Rules for you

- Never print, echo, log or commit a secret. `oauth.env`, `client.token`, `client-tokens/*`, `ui-session.key` hold secrets. To inspect them, count matches or test file mode. Never `cat` them.
- Never put a secret in a command line. The user types secrets into `oauth.env` in an editor (hand-off H1).
- Do not edit files inside `~/stackshot`. `deploy.sh` refuses a dirty checkout (deploy.sh). The config lives in `~/.config/stackshot/`.
- Do not use `STACKSHOT_AUTH=off` on this instance. It is for local tests (stackshot.example.toml, `[auth] mode`).
- Do not kill `claude` processes by name. Other sessions may be running.
- Use `systemctl --user`, never `sudo`, except where this file says root is needed once (lingering).
- Do not enable optional features (see the settings table). Do not run `./stackshot setup --force` on an installed box: it rewrites the config (stackshot).
- At a hand-off, stop, tell the user exactly what to do, and end your turn. Continue after they reply.

## 2. Facts

| Item | Value | Source |
|---|---|---|
| Code checkout | `~/stackshot` (clone of the repository) | server.py refuses a bare start elsewhere |
| Clone URL | `https://github.com/howardpark-ai/stackshot`, branch `main` (public: a plain clone works, no access request and no git credentials) | `git ls-remote` shows `refs/heads/main` |
| Config file | `~/.config/stackshot/stackshot.toml`, or `$STACKSHOT_CONFIG` | stackshot |
| Secrets dir | `~/.config/stackshot/` (mode 0700) | stackshot |
| Secret files | `oauth.env`, `ui-session.key` (server makes it on first start), `client.token`, `client.url`, `clients.json`, `client-tokens/<host>.token` | stackshot |
| Required env key names (in `oauth.env`) | `STACKSHOT_GOOGLE_CLIENT_ID`, `STACKSHOT_GOOGLE_CLIENT_SECRET` | server.py |
| Optional env key name | `STACKSHOT_PORTAL_TOKEN` (portal only; leave unset). Old spelling `BOARD_MCP_*` still read | server.py |
| State dir | `~/.local/state/stackshot/` (ledger, inbox, routing; services log to journald) | stackshot.example.toml `[paths] state` |
| Data repo | `~/stackshot-data/` (`board-data/`, `board.md`, `RULES.md`, `session-names.tsv`, `pages/`) | stackshot |
| Pages | `~/stackshot-data/pages/projects/<slug>.md` (inside the data repo by default) | stackshot |
| Server bind | `127.0.0.1:8020`, MCP at `/mcp`, health at `/healthz` | example `[server]`; deploy.sh |
| Google redirect URI | `<base_url>/auth/callback` | stackshot |
| Connector URL | `<base_url>/mcp` | stackshot |
| OAuth metadata | `<base_url>/.well-known/oauth-authorization-server` | stackshot |
| Board sign-in callback | `<base_url>/ui/callback` (no extra Google URI needed) | server.py: the comment block above `_ui_open`, and `_ui_redirect_uri` |
| claude.ai callbacks | already in `[auth] allowed_client_redirect_uris` | example `[auth]` |
| Units (always) | `stackshot.service`, `stackshot-reload.path`, `stackshot-reload.service`, `stackshot-puller.service`, in `~/.config/systemd/user/` | install.sh |
| Units (off by default) | `anchor-hub.service`, `stackshot-portal-sync.service` (+ drop-in), `stackshot-audit.{service,timer}` | install.sh |
| Server command | `uv run --locked --script ~/stackshot/server.py` | units/stackshot.service.in:15 |
| Python | system `python3` 3.12+ (CLI, hooks, puller at `/usr/bin/python3`); server 3.12+ via uv | stackshot; server.py; units/stackshot-puller.service.in |
| Connector name | `Stackshot` (set on claude.ai) | [INSTALL.md](../INSTALL.md) step 5 |
| Claude Code tool names | `mcp__claude_ai_Stackshot__<tool>` | [INSTALL.md](../INSTALL.md) step 5 |
| Tools (12) | `brief get create update confirm complete anchors route message sessions rules bump_versions` | tests/tool_text.snapshot.json |
| Hooks written | 4 entries in `~/.claude/settings.json`: SessionStart, UserPromptSubmit, PostToolUse (matcher `mcp__.*`), Stop; scripts in `~/stackshot/client/hooks/` | stackshot |
| Router | server runs `claude -p` (login shell, `--model sonnet`) for notices | example `[router]` |
| Config reload | automatic on save (`stackshot-reload.path`); restart-only keys listed in `config.py` RESTART_ONLY | `RESTART_ONLY` in config.py |

## 3. Settings

### Set (by `setup` flags or one edit)

| Key | Value | How |
|---|---|---|
| `[instance] owner` | the user's first name | `--owner` |
| `[instance] timezone` | an IANA name | `--tz` |
| `[instance] board_url`, `[auth] base_url`, `[client] url` | the final public HTTPS base URL, no trailing slash | `--base-url` (restart-only; get it right first) |
| `[auth] allowed_emails` | the Google emails that may sign in; at least one | `--emails` (empty list breaks server start, server.py) |
| `[subject] prefixes` | the user's prefixes, each ending in a space | `--prefixes` |
| `[paths] repo/store/markdown/rules/brain/fleet_names` | derived from `--data` and `--pages` | `--data`, `--pages` |
| `[server] port` | 8020 unless taken | `--port` |
| `[auth] ui_open` | `false` | `sed` after setup (step 3). Default `true` serves the board page to anyone who reaches the URL (server.py: the comment block above `_ui_open`, and `_ui_guard`) |

Do not pass `--yes` unless every answer is given as a flag. `--yes` fills gaps with defaults. An empty `--emails` is the usual gap (stackshot).

### Leave at the neutral defaults (stackshot.example.toml)

| Key | Default | Why leave it |
|---|---|---|
| `[pages] flavor` | `"plain"` | Sessions edit `<paths.brain>/<key>.md`, commit and push. `"gbrain"` needs gbrain |
| `[pages] dirs` | `["projects"]` | Keep `[registries.projects] match` in step if you change it |
| `[gbrain] mirror_url` | `""` (setup blanks it) | No gbrain |
| `[publish] git` | `true` | Needs the remote and first push (step 4). `false` keeps everything local |
| `[page_rule] mode / grace_minutes` | `"refuse"` / `30` | A session that owes a page 30 minutes gets its next state-changing write refused (server.py). Under the default `[pilot] writer_owes_page = false` a board change is charged to the page's keeper and the router passes it on, so the writer is not the one refused |
| `[pilot] writer_owes_page` | `false` | `true` makes the writing session owe the page update itself (refused after `grace_minutes`); the keeper is charged only after that. Leave it off unless the user asks |
| `[wait_guard] enabled` | `true` | A bare `wake`, or a `next` line whose step is dated later than today, on your own item needs `wait_reason` (not a `wake` with `hold=true` and `wait_basis`); one model call (the `[router]` command) may refuse it when the step could be done now. It lets the write through when the call fails. `[wait_guard] enabled = false` turns it off. Live |
| `[stall] enabled` | `true` | Moves an open item on when its mover session is idle past `minutes`. Needs `[model] handoff`. It leaves alone a pane the CLI's registry does not show, and its last rung (one message to the fleet's builder) needs `[fleet] operator_session`, which a board-alone install leaves empty (stall.py header) |
| `[ladder] enabled` | `false` | The one-ladder rework of the hand-off and stall ladders. Leave off |
| `[board_check] mode` | `"off"` | Optional later: `"note"` or `"block"` |
| `[audit] enabled` | `false` | No daily audit timer |
| `[github] sync` | `false` | No GitHub item mirror |
| `[anchor_hub] enabled` | `false` | No anchor-hub unit |
| `[portal] account_id` | `""` | No portal-sync unit |
| `[router] *` | defaults | Needs Claude Code signed in on the box |
| `[machines_panel] latest_lookups` | `true` | Asks npm for the latest Claude Code version. Shows `?` without `npm` |
| `[runners]` | empty | Lists nothing until `owner` and `repos` are set |
| `[fleet] *`, `[steps] *`, `[terminal] *` | empty | No fleet tool |
| `[client] session_links / session_view / lanes_file` | `""` | No fleet tool |

## 4. Procedure

For each step: run the command, run the check, compare to the expected result. If it differs, go to section 5 before going on. One command per code block.

### Step 0. Preconditions

Check each. Report anything missing to the user. Do not install system packages without asking.

```bash
python3 --version
```

Expected: 3.12 or newer.

```bash
uv --version
```

Expected: a version. Missing: ask the user to install uv. Do not use `pip install`.

```bash
git --version && curl --version | head -1
```

Expected: both print versions.

```bash
systemctl --user show-environment | head -1
```

Expected: environment lines. If it fails, see T11.

```bash
loginctl show-user "$USER" -p Linger --value
```

Expected: `yes`. If `no`, setup tries to enable it. If it still warns, hand-off H5.

```bash
claude --version
```

Expected: a version. The user must be signed in to Claude Code with the claude.ai account that will own the connector. You cannot verify the sign-in yourself: ask. `TODO(verify)`: a non-interactive check for the sign-in.

Ask the user for these answers before step 2 (setup), and do not guess any of them:

- first name for the board; timezone; the public HTTPS base URL; the Google emails allowed to sign in; subject prefixes; the private data repo URL; whether the default folders are fine.

### Step 1. Clone

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
```

Check:

```bash
git -C ~/stackshot rev-parse --abbrev-ref HEAD
```

Expected: `main`. The repository is public, so the clone needs no access request and no git credentials. If it fails, check the URL and the box's network; do not ask the user for credentials.

### Step 2. Setup

Run it with the user's answers as flags. Example shape (replace every value; do not run this literally):

```bash
cd ~/stackshot && ./stackshot setup --owner "<name>" --tz "<Area/City>" --base-url "https://<host>" --emails "<email1>,<email2>" --prefixes "[work] ,[home] " --yes
```

If a terminal is available to the user, they may instead run `./stackshot setup` and answer the prompts. Without `--yes` and without a terminal it exits 2 (stackshot). If `systemctl --user` is out of reach on this box (T11), add `--no-systemd`: setup skips the units, says how to install them later, and you run `./install.sh units --start` once the user manager answers. The checks after this step that list units then fail until you have.

Check:

```bash
ls ~/.config/stackshot/stackshot.toml ~/stackshot-data/RULES.md ~/stackshot-data/pages/projects/getting-started.md
```

Expected: all three exist.

```bash
git -C ~/stackshot-data log --oneline | head -3
```

Expected: one commit, `stackshot setup`.

```bash
systemctl --user list-unit-files 'stackshot*' --no-legend | cut -d' ' -f1
```

Expected: `stackshot.service`, `stackshot-puller.service`, `stackshot-reload.path`, `stackshot-reload.service`.

```bash
systemctl --user is-active stackshot-puller.service
```

Expected: `active`. The server is not active yet (stackshot).

The output ends with the Google redirect URI and the connector URL. Remember both. Setup ends with a lingering warning if lingering is off: hand-off H5.

### Step 3. Make the board page require sign-in

```bash
sed -i 's/^ui_open = true/ui_open = false/' ~/.config/stackshot/stackshot.toml
```

Check:

```bash
grep -c '^ui_open = false' ~/.config/stackshot/stackshot.toml
```

Expected: `1`. The setting is live (not in RESTART_ONLY). No new redirect URI is needed at Google.

### Step 4. Data repository remote and first push

```bash
git -C ~/stackshot-data remote add origin <private-repo-url>
```

```bash
git -C ~/stackshot-data push -u origin main
```

Check:

```bash
git -C ~/stackshot-data rev-parse --abbrev-ref --symbolic-full-name @{u}
```

Expected: `origin/main`.

Why this is required: `publish.py:65` returns without pushing when `git fetch origin main` fails, and an empty remote has no `main` (publish.py:62-70). A missing upstream makes `rev-list @{u}..HEAD` fail, which the code reads as "nothing to push" (publish.py:63).

If the remote is not wanted yet: set `[publish] git = false` in the config instead and tell the user.

### Step 5. Hand-off H1: Google OAuth client and `oauth.env`

STOP. Tell the user:

> Create a Google OAuth client. In the Google Cloud console: APIs & Services, Credentials, Create credentials, OAuth client ID, type Web application. Under Authorized redirect URIs add exactly `<base>/auth/callback`. Set up the consent screen if asked. Then open `~/.config/stackshot/oauth.env` in your editor and fill `STACKSHOT_GOOGLE_CLIENT_ID=` and `STACKSHOT_GOOGLE_CLIENT_SECRET=`. Do not paste the values into this chat. Tell me when done.

`TODO(verify)`: exact console labels; whether a consent screen in Testing status needs the user added as a test user.

After they reply, check without printing values:

```bash
grep -cE '^STACKSHOT_GOOGLE_CLIENT_(ID|SECRET)=.+' ~/.config/stackshot/oauth.env
```

Expected: `2`.

```bash
stat -c %a ~/.config/stackshot/oauth.env
```

Expected: `600`.

### Step 6. Start the server

```bash
cd ~/stackshot && ./stackshot doctor
```

With both values set, an allowed email set and the server inactive, doctor runs `install.sh units --start` and waits up to 30 s (stackshot). Expected after: `the server answers http://127.0.0.1:8020/healthz` is `ok`; `stackshot.service`, `stackshot-reload.path` and `stackshot-puller.service` are `active`. Still `missing` at this point, and exit 1: the OAuth metadata line (until step 7) and `Claude Code hooks ... 0 of 4` (until step 9). Doctor also exits 1 when a unit check could not run (the user manager out of reach): it prints a warning then, never `all good`.

Independent check:

```bash
curl -sf http://127.0.0.1:8020/healthz
```

Expected: `ok` on the first line.

### Step 7. Hand-off H2: HTTPS front

STOP. Tell the user:

> Point your tunnel or reverse proxy at `127.0.0.1:8020` under `<base>`. Any tool is fine. Then open `<base>/.well-known/oauth-authorization-server` in a browser on another machine: it should show JSON. Tell me when done.

You cannot set up DNS or the front yourself. After they reply:

```bash
curl -sf https://<host>/.well-known/oauth-authorization-server | head -c 200
```

Expected: JSON text. Doctor checks this from the box only (stackshot); the user's browser test is the outside check.

```bash
cd ~/stackshot && ./stackshot doctor
```

Expected: the metadata line is `ok`. Only the hooks line is `missing`.

### Step 8. Hand-off H3: claude.ai connector

STOP. Tell the user:

> In claude.ai: Settings, Connectors, Add custom connector. Name it exactly `Stackshot`. URL: `<base>/mcp`. Connect and sign in with one of the allowed Google accounts. Then open a new claude.ai chat and ask it to call the Stackshot connector's `brief` tool. The empty board should come back. Tell me what you see.

Do not continue until the user confirms. Check on the server side:

```bash
journalctl --user -u stackshot.service -n 30 --no-pager
```

Expected: no tracebacks; sign-in lines are fine.

### Step 9. Claude Code hooks

```bash
cd ~/stackshot && ./stackshot client install
```

It prints a diff, writes `~/.claude/settings.json.bak-<timestamp>`, adds four hooks, and restarts the puller. Check:

```bash
grep -c 'client/hooks' ~/.claude/settings.json
```

Expected: `4` or more (one per hook entry). If the user runs the stackshot Claude Code plugin, doctor counts the hooks that plugin carries as well, and its hooks line says how many came from it; then `grep` here can print fewer than 4 while doctor is satisfied.

```bash
cd ~/stackshot && ./stackshot doctor
```

Expected: `all good`, exit 0.

The new tool list reaches Claude Code only in a new session. Tell the user to start one (hand-off H4). In that session, `ToolSearch` for `Stackshot` should list the tools. If it lists only `authenticate` stubs, the connector is not signed in for Claude Code: the user must complete the sign-in from the Claude Code `/mcp` menu. `TODO(verify)`: exact flow.

### Step 10. First item and first page edit

In the new session, call `create` with:

- `subject`: starts with one of the configured prefixes, at most 80 characters
- `description`: 1 to 8 lines, each starting `- `, at most 120 characters (no `resolved:` or `done:` words); the first bullet opens `Goal:` and states the outcome wanted (the subject names the same outcome, "Make X work when Y", never the symptom "X fails when Y"); a symptom goes in a later bullet that opens `Problem:`
- `project`: `projects/getting-started`
- `sender`: a short stable name for this session
- `mover`: the same name. A fresh page lists no agents, so the default mover (`_fallback_mover` in server.py: the project's builder, else its `-main` agent, else the page's `display-name:` session) is the `display-name:` session, which nothing answers to on a solo install. `create` without `mover` is not refused there (observed on a fresh install): the item gets that nonexistent mover and the stall pass logs "nobody could take it". Only a page-less project (`prj_...`) is refused ("names no mover")
- `next`: one line per step, each starting with `<name>: `

Expected: the call succeeds and returns an id.

Check all three:

```bash
python3 ~/stackshot/client.py get brief | head -20
```

Expected: the item is listed.

```bash
git -C ~/stackshot-data log --oneline | head -3
```

Expected: a `board:` commit within about 10 seconds (debounce 5 s: example `[publish]`).

```bash
git -C ~/stackshot-data status --short | head
```

Expected: no unpushed board commits after a minute (`git -C ~/stackshot-data rev-list --count @{u}..HEAD` prints `0`).

The create may leave a page owed (the page rule: section 3, `[page_rule]` and `[pilot] writer_owes_page`). With the defaults the debt is the page's keeper's, and the reply to `create` on a `projects/getting-started` item carries the line `(pilot project: this change is charged to the router, which passes the page update to the agent that keeps the page)`; a bare scratch page with no `display-name:` or `agents:` lines carried no such line. On a one-session install no other agent keeps the page, so do the page update yourself, once: edit `~/stackshot-data/pages/projects/getting-started.md`: update `## Current state` and add a dated line under `## Timeline` (`- **YYYY-MM-DD** | <session> — <what happened>`). Then commit and push from `~/stackshot-data`. If the push is refused, `git pull --rebase` first.

Check with `get` that `mover:` shows your session. If a message or notice stays "held: no agent can take it", see T21.

## 5. Hand-offs (summary)

| ID | The human does | You then |
|---|---|---|
| H0 | Gives the box a credential for the private data repo (the code repository is public and needs none) | Retry step 4 |
| H1 | Creates the Google OAuth client with the redirect URI, fills `oauth.env` in an editor | Step 5 checks, then step 6 |
| H2 | Sets up DNS and the HTTPS front to `127.0.0.1:8020` | Step 7 checks |
| H3 | Adds the claude.ai connector named `Stackshot`, signs in, tests `brief` | Step 9 |
| H4 | Starts a new Claude Code session | Step 10 |
| H5 | Runs `sudo loginctl enable-linger <user>` if setup could not | Re-run `loginctl show-user "$USER" -p Linger --value`, expect `yes` |

## 6. Troubleshooting (real failure points in the code)

| # | Symptom | Cause | Source | Fix |
|---|---|---|---|---|
| T1 | `setup` exits 2: "stdin is not a terminal" | No tty and no `--yes` | stackshot | Pass flags and `--yes` |
| T2 | `setup` exits 2: "exists; setup leaves it alone" | Config already written | stackshot | Run `doctor`. Use `--force` only to rewrite on purpose |
| T3 | `setup` exits 2: "port 8020 is taken on this box by <user>" | Another account's server | stackshot | `--port <free port>` |
| T4 | `setup` exits 2: "not a timezone this Python knows" | Bad `--tz` | stackshot | Use an IANA name |
| T5 | Server will not start: `auth=google but STACKSHOT_GOOGLE_CLIENT_ID/SECRET not set (env file ...)` | `oauth.env` empty or wrong key names | server.py | Step 5 checks; restart: `systemctl --user restart stackshot.service` |
| T6 | Server crashes at start with `IndexError` in `_auth` | `[auth] allowed_emails` is empty | server.py | Add an email; doctor refuses to start it in this case |
| T7 | Server exits 1: "port 127.0.0.1:8020 is taken" | A second server or another program | server.py | `ss -ltnp \| grep 8020`; change `[server] port`, then `./install.sh units --start` |
| T8 | Server exits 2: "STACKSHOT_CONFIG is unset and ... is not the production checkout" | Started by hand from outside `~/stackshot` | server.py | Use the unit, or export `STACKSHOT_CONFIG` |
| T9 | Data repo never reaches the remote; no error | Empty remote has no `main`, so the publisher's fetch fails and it returns silently | publish.py:62-70 | Step 4: `git push -u origin main` by hand |
| T10 | Board page opens for anyone with the URL | `[auth] ui_open = true` (default) | server.py: the comment block above `_ui_open`, and `_ui_email`/`_ui_guard` | Step 3 |
| T11 | `systemctl --user` "cannot reach your user manager" | Shell is not a login session; no `XDG_RUNTIME_DIR` | stackshot; units/scope.sh:19 | `export XDG_RUNTIME_DIR=/run/user/$(id -u)` or log in with ssh/console |
| T12 | Units stop at logout or are missing after reboot | Lingering off | install.sh; stackshot | H5 |
| T13 | `deploy.sh` says "cannot fetch main from origin" | No `origin`, origin unreachable, or no `main` | deploy.sh | Check `git -C ~/stackshot remote -v` and that the URL is reachable |
| T14 | `deploy.sh`: "the production checkout has local changes" | A tracked file was edited in `~/stackshot` | deploy.sh | `git -C ~/stackshot diff --stat`; undo your edits. The config is outside the checkout |
| T15 | `deploy.sh`: "does not contain HEAD" | Local commits in `~/stackshot` (the repository takes ordinary pull requests, so `origin/main` only moves forward) | deploy.sh | Ask the user before discarding them, then `git -C ~/stackshot reset --hard "$(git -C ~/stackshot merge-base HEAD origin/main)"` and `./deploy.sh`. Not `reset --hard origin/main`: that leaves nothing to deploy (T16) |
| T16 | `deploy.sh` says "already at origin/main; nothing to deploy" after an update the user expected | `git pull` was run first, so HEAD already equals `origin/main` and no restart is planned | deploy.sh | Run `./install.sh units --start` (re-renders the units, restarts `stackshot.service`, `stackshot-reload.path`, `stackshot-puller.service` and, if enabled, `anchor-hub.service`). Next time run only `./deploy.sh` |
| T17 | `deploy.sh`: "healthz did not answer within 180 s" | Server failed to start after the update | deploy.sh | `journalctl --user -u stackshot.service -n 80 --no-pager` |
| T18 | A session is refused: "you owe a project-page update" | Page rule with `[pilot] writer_owes_page = true`: owed longer than `grace_minutes` (30) | server.py; example `[page_rule]` | Edit the page, commit, push, retry |
| T19 | `create` refused: "subject must start with one of [...]", a description line "is not a `- ` bullet", or "the description must open with its goal" | Gate texts | server.py | Fix the call. Read `rules` for the shape |
| T20 | `create` refused: "metadata.project ... names no page" | The page file does not exist or the registry is stale | server.py | Create `pages/projects/<slug>.md`; `python3 ~/stackshot/pages.py registry` |
| T21 | Notice shows as waiting; router log says "no agent can take it" | Page and scope list no user-facing agent | router_live.py:494-495 | `TODO(verify)` whether a solo install ever produces one. Fix: list an agent in the page's `agents:` frontmatter, or set `[router] general_general` |
| T22 | Router calls time out or fail | `claude` not on the login-shell PATH, not signed in, or slow | example `[router]` (`command`, `timeout_seconds`, `login_shell`); router.py:146 (timeout_seconds), router.py:1180 (login_shell) | Run `bash -lc 'claude --version'` as the user; sign in. The notice is retried then passed to a `-main` agent (router_live.py:18-19) |
| T23 | Claude Code lists only `authenticate` stubs for the connector | Connector not signed in for the CLI | n/a | Hand-off H3, then a new session. `TODO(verify)` |
| T24 | New connector tools or parameters do not appear after an update | claude.ai caches the tool list for about a day | README, "A new tool or parameter" | Wait, or call the new form through a portal. Not needed for a board-alone setup |
| T25 | Config edit seems ignored | Restart-only key | `RESTART_ONLY` in config.py; [INSTALL.md](../INSTALL.md) "Changing the config" | `systemctl --user restart stackshot.service`; for `[server] port`/`[instance] timezone` run `./install.sh units` first |
| T26 | A page edited in an Obsidian vault does not settle a session's page debt | Freshness is read from the server's checkout (last commit time or file mtime) | pages.py:423-437 | The server must pull that repo. The default layout (pages inside the data repo) is pulled by the publisher at publish.py:80-81. A separate pages repo is not pulled by anything: add a timer |
| T27 | `update` refused: "a wait on your own item needs its reason" | `[wait_guard]`: a bare `wake`, or a `next` line whose step is dated later than today, with no `wait_reason`. A `wake` together with `hold=true` and `wait_basis` is not judged and needs none (seen accepted on a scratch instance); neither is a wait on another item (`after`), on the owner or an outside party (`needs`) | self_wait.py, example `[wait_guard]` | Pass `wait_reason=<what the step waits on that is not available now, at least 15 characters>`. If nothing blocks the step, do it now. A refusal that says the step could be done now came from one model call: it is not a server fault |
| T28 | `tools/project.py move-page` refuses | A plain-pages install: the page-moving tools (rename_page.py, page_keeper.py) refuse under `[pages] flavor = "plain"` | tests/neutral_install_scenario.py:222 | There is no verb for it on plain pages. Do not switch the flavor |

## 7. Using the board afterwards

You operate the board only through the connector tools, `mcp__claude_ai_Stackshot__*` in Claude Code. Do not edit the files under `~/stackshot-data/board-data/` by hand: the server is the only writer (README, "The board and the publisher"). Do not call the GitHub API for items: sync is off.

Start each session by reading the brief. The SessionStart hook injects it. Call `brief` again for the full list, and `rules` for the rulebook (`~/stackshot-data/RULES.md`).

| To do this | Call | Notes |
|---|---|---|
| See everything open | `brief` | Counts and every open item in full |
| Read one item | `get` with `item_id` | Shows `mover:`, `needs:`, `after:`, History |
| Make an item | `create` with `subject`, `description`, `project`, `sender`, `next` | Required: `subject`, `description`, `project`. Always pass `sender` |
| Change an item | `update` with `item_id`, `sender`, the fields to change | `next` is a checklist: mark your done lines `done=[n]`, dropped ones `dropped=[n]`. Update `description` to the live state |
| Mark an item still true | `confirm` with `item_id`, `sender` | Sets the freshness clock only. No page is owed |
| Finish an item | `complete` with `item_id`, `reason`, `sender` | Items are never deleted |
| Wait on the user | `update` with `needs=decision` and an `ask` line | `Decide: ... · Recommend: ... · Stakes: ... · By: ...`, one line, at most 240 characters. A decision about a design links its mockup (a `https://claude.ai/artifact/…` page) in the Decide part as `[mockup](url)`; a write that links it only in the description, `next` or options is refused. A decision is a choice he makes between options: a Decide part that opens with what, which, how, who, when, where or why lists its options (the Recommend part should name the recommended option's label) or is reworded as a yes/no (`Decide: whether to …`), else the write is refused. A thing he does himself (run a command, set a switch, confirm he did it) is not a decision: use `update` with `step=<his action>` alone (no `state`), which the board ticks when he says it is done; `step="none"` withdraws it; an ask that only asks whether he has done it, or Yes/No over the action of his own `next` lines, is refused |
| Wait on another item | `update` with `after=["<that item's id>"]` and `supplies=<one line: what that item gives this one>` | `supplies` alone, with `after`, sets the item blocked on that item. `step` and `supplies` are alternatives: pass one, not both |
| Wait on someone outside | `update` with `needs=external` | |
| See live sessions | `sessions` | |

Rules that apply on every write:

- Item = human-level: a deliverable, a decision, a blocker, a handoff. Never a working step.
- Subject starts with a configured prefix, at most 80 characters. `description` is 1 to 8 short `- ` bullets of at most 120 characters, live state only; its first bullet opens `Goal:` with the outcome wanted (a create or a replaced description without it is refused), a symptom goes under a later `Problem:` bullet.
- `due` only from a real deadline, `YYYY-MM-DD` in the instance timezone.
- Every `next` line opens with who takes it (`<session>: ...`). A line naming no one is refused.
- After a write that changes state (create, complete, or update of description, next, needs, status or due) on an item whose project has a page, update that page in the same turn when it is yours to update (the page's keeper, or the writer when `[pilot] writer_owes_page = true`): rewrite `Current state` where it changed, add a dated line under `Timeline`, commit and push. The hooks remind the session that owes it at the next prompt. A project with no page owes none.
- A bare wake or a dated `next` step on your own item carries `wait_reason` (T27); a wake with `hold=true` and `wait_basis` does not.
- Read the project page before acting on an item.
- New project: use the verbs, not a hand-made file (section 7a below). A project needs no page.

### 7a. Project verbs

A project is an entry in `project-record.json` (store folder), keyed by an id `prj_<8 hex>`, written record first; then, when the project has a page in this instance's page store, three lines of the page's frontmatter (`display-name:`, `agents:`, `status:`) are written from the record. A page pointer is optional: it may be a page key, a link to another knowledge base, or nothing (README, "Projects: the record first"; project_verbs.py). Run the verbs from the checkout, `python3 ~/stackshot/tools/project.py [--by <label>] [--dry-run] [--json] <command> ...`: the global flags go before the command (after it argparse refuses them, exit 2). Each ran on a scratch instance for this guide, except where a row says otherwise.

| Command | Effect | Result seen |
|---|---|---|
| `create NAME --scope S [--page KEY\|LINK] [--make-page] [--title T]` | New project; with no `--page` it has no page and none is made | Made `prj_...` with no page (a name alone); also run with `--page https://example.com/x` |
| `rename PROJECT NEW_NAME` | Name changes, id stays | Not run |
| `move-page PROJECT NEW_KEY` | rename_page.py copy then stub, then the record | Refused on plain pages (T28); needs `[pages] flavor = "gbrain"`; `TODO(verify)` on a gbrain box |
| `archive PROJECT [--why W]` / `reopen PROJECT` | status `archived` and back; the page's `status:` follows | `--dry-run archive` run; archive run on a project with a page: its `status:` line changed |
| `agent-add PROJECT NAME (--front\|--back) --mandate M` | Lists an agent; on a project with a page writes the `agents:` block | Run on a project with no page and on one with a page. On the page-less project it did NOT give a default mover: `create` with `project=prj_...` and no `mover` was refused ("names no mover"), and worked with `mover=<name>`. On the project with a page (agent listed in its `agents:` block, after the registry refreshed) `create` with no `mover` worked |
| `agent-retire PROJECT NAME`, `agent-rename PROJECT OLD NEW` | Takes an agent off the map, or renames it; retiring the last agent of a project with no open item archives it | Not run |
| `mirror PROJECT [--make-page]` | Writes the three mirror lines again | Not run |
| `show PROJECT` | The entry and what the registry reads | Run |

`PROJECT` is an id (printed by `create`), a page key or a bare slug; `show` also resolves the name or a former name, but `mirror <name>` returned 404 for a page-less project where `show <name>` found it, so pass `mirror` an id, page key or slug. A sub-page (`projects/<slug>/<sub>`) is never a project: `create` refuses it, and archive, reopen and move-page refuse it naming its top-level project. The verbs and their flags are listed at the top of `tools/project.py` (`--help` lists only the command names, `<command> -h` the flags). The client API has the same verbs: `client.py post project --scope S (--key projects/<slug> | --name N [--page KEY|LINK] [--make-page true|false])`, then `post project-agent`, `post project-agent-rename`, `post project-agent-retire` (the last two need `--sender` a label in `[project_agent] form_senders` and a token from a machine in `form_machines`, else 403). `post project --key ...` makes the page from the `[pages] template_page` page unless `--make-page false`; on plain pages it writes the file into `paths.brain` and does not commit or push it: do that from `~/stackshot-data`. A key or name some project already has is a 409.

An item can be filed on a project by its id (`project=prj_...`), also for one with no page. A project with no page is absent from `client.py get projects` and `client.py get project <prj_id>` answers 404 for it (the registry is built from pages), though `tools/project.py show <prj_id>` reads it and an item filed on it works with an explicit `mover`. There is no verb that deletes a project. Hand-made page files are still read by the registry and get a record entry at their first verb.

Reads from a shell on the box, with the box's own token: `python3 ~/stackshot/client.py get brief`, `get whoami`, `get items <session>`, `get rules`.

## 8. Updating

```bash
cd ~/stackshot && ./deploy.sh --dry-run
```

Expected: the commits listed and `restarts: ...`.

```bash
cd ~/stackshot && ./deploy.sh
```

Expected: ends with `healthz ok at <commit>` (deploy.sh). Do not run `git pull` first (T16). Then:

```bash
cd ~/stackshot && ./stackshot doctor
```

Expected: `all good`. New units are installed by the deploy itself (`./install.sh units`, deploy.sh).

## 9. Report to the user when done

Say: the base URL, the board URL, the connector name and URL, where the config and secrets live (paths only), which hand-offs you needed, which `TODO(verify)` items you resolved and how, and what is left out of scope.
