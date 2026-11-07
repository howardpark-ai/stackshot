# Installing stackshot

stackshot is a coordination board for one person and their Claude sessions: a web board, a claude.ai
connector (MCP) that every Claude Code and claude.ai session writes through, a set of hooks that keep
the project pages current, and, optionally, anchor-hub, which watches external things (Slack, Notion,
Drive, Gmail, GitHub) and drops one-line notices into the right session.

This is what a second person types, in order. Everything here runs as your own user on one Linux box
with systemd (the *server box*). Other machines where you run Claude Code get a small client later
(step 7).

## 0. What you bring

| You need | Why | Notes |
|---|---|---|
| A Linux box with systemd and a user account | the services run as systemd user units under your account; no `sudo` | they need lingering to keep running after you log out and to start at boot. On systemd 255 or later (Ubuntu 24.04, for one) your account may switch it on for itself without root (polkit allows `set-self-linger`), so setup does it; only where polkit refuses does setup print the one command root runs once, `sudo loginctl enable-linger <user>`. The README's [Scope](README.md#scope) section says which setups are supported |
| `git`, `curl`, `uv`, Python 3.12+ | code, units, the publisher's pushes | `uv` installs its own Python for the server; the small tools run on `/usr/bin/python3`. Optional: `npm`, for the latest Claude Code version in the Machines panel (without it the panel shows `?`); `gh`, only for a `github-release:` package in `[machines_panel]` or anchor-hub's GitHub receiver |
| A public HTTPS name that reaches `127.0.0.1:8020` on the box | claude.ai and other machines must reach the connector | a Cloudflare tunnel, Caddy, nginx, Tailscale Funnel: your choice. If anchor-hub will take webhooks, also forward a second name or path to `127.0.0.1:8010` |
| A Google account, and a Google Cloud project where you can create an OAuth client | sign-in for the connector and the board | the client is created in step 3 from a URI that setup prints |
| A Claude plan with claude.ai connectors (Pro, Max, Team, Enterprise) and Claude Code | the sessions that use the board | |
| A git repository for the data, and git credentials on the box that can push to it | the board's items and markdown are committed and pushed after every change | can be private and empty; the publisher pushes as your user, so set up its credentials (an ssh key or a credential helper) before step 2. An empty repository needs one first push by hand, `git -C ~/stackshot-data push -u origin main` (after `git -C ~/stackshot-data remote add origin <url>`): the publisher fetches `origin main` before it pushes, and on a remote with no `main` that fetch fails, so it never pushes anything. `publish.git = false` keeps everything local instead |

You do not need gbrain, Postgres, sala, Cloudflare Access, or anything outside this repository.

## 1. Get the code

For a fresh install, clone the public repository. It is public, so a plain clone works: no access request and no git credentials:

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
cd ~/stackshot
```

A clone you will commit from (not one that only runs the service) also turns on the repository's git hooks, once:
`git config core.hooksPath .githooks`. They refuse a commit message or a push that carries the instance owner's data;
`install.sh` does not change git configuration, so this is yours to run. The hooks also run the machine-wide hook of the same
name when one is installed (in the user's global `core.hooksPath` first, else in `${XDG_CONFIG_HOME:-$HOME/.config}/git/hooks`), and skip it otherwise. CONTRIBUTING.md, "Commit and PR text", has the rest.

## 2. Set up

```bash
./stackshot setup
```

`setup` asks for the handful of values that are yours and derives the rest:

- your name as the board should say it, and your timezone;
- the public base URL (`https://board.example.com`);
- the Google account emails allowed to sign in;
- the subject prefixes your items start with (`[work] `, `[home] `), comma-separated; each is normalised to end in
  one space;
- where the data repository lives (default `~/stackshot-data`) and where the project pages live
  (default `~/stackshot-data/pages`).

Every answer can be passed as a flag (`--owner`, `--tz`, `--base-url`, `--emails`, `--prefixes`,
`--data`, `--pages`, and `--port`, the server's local port: a second person on the same box sets up
under their own account with a port of their own); with `--yes` nothing is asked and the defaults fill the gaps, which is how the
test suite runs it. The questions need a terminal: piped answers are refused. Without `--yes` and with
stdin not a terminal (a pipe, a script), setup stops with exit 2 and says to pass the answers as flags
and add `--yes`.

What it does, in this order, and says as it goes:

1. Writes the config to `$STACKSHOT_CONFIG` when that is set, else to `~/.config/stackshot/stackshot.toml`:
   a complete copy of `stackshot.example.toml` with your values filled in. One file, every key present,
   nothing to merge.
2. Creates the data repository (`git init`, the store, a short `RULES.md` that the connector's `rules`
   tool serves to every session, `session-names.tsv` and the page registry `board-data/projects.json`) and
   the pages directory with a first project page, `projects/getting-started.md`, so the first item has a
   page to belong to. `board.md` appears when the publisher first runs.
3. Creates the secrets directory (`~/.config/stackshot`, mode 0700) and an `oauth.env` with empty
   `STACKSHOT_GOOGLE_CLIENT_ID` and `STACKSHOT_GOOGLE_CLIENT_SECRET`. The server creates its cookie key,
   `ui-session.key`, on first use.
4. Mints this machine's client token, so the box's own Claude Code sessions can read the board.
5. Renders the systemd units (server, config watcher, this box's puller; anchor-hub only with
   `[anchor_hub] enabled = true` and the Cloudflare portal sync only with `[portal] account_id` set, so
   neither on a fresh config), installs and enables them as user units under `~/.config/systemd/user`,
   and starts the puller; the server starts in step 3. Nothing here needs `sudo`. User units need
   lingering, so this step also sees to it: when it is off, `install.sh` runs `loginctl enable-linger <user>` itself. On
   systemd 255 or later polkit lets a user switch lingering on for their own account (`set-self-linger`),
   so this needs no root; elsewhere it tries `sudo -n loginctl enable-linger <user>`, and when neither
   works it prints a WARNING and setup repeats the one command root runs (`sudo loginctl enable-linger
   <user>`) at the end. Until then the units install and run while you are logged in, stop when you log
   out and do not start at boot. With `--no-systemd` this step is skipped and says how to install the units later.

   `systemctl --user` finds your user manager through `XDG_RUNTIME_DIR`, which only a login sets. From
   ssh, the console, `su -` or `sudo -i` nothing is needed. From a shell that is not a login (`sudo -u`,
   `lxc exec --user`, cron) the variable is unset: `stackshot` and `install.sh` then point it at
   `/run/user/<uid>` themselves when that directory exists (your user manager runs: lingering is on, or
   you are logged in elsewhere). When it does not exist, the unit step stops with `` `systemctl --user`
   cannot reach your user manager: export XDG_RUNTIME_DIR=/run/user/$(id -u), or log in (ssh, console,
   su -, sudo -i) ``: run `export XDG_RUNTIME_DIR=/run/user/$(id -u)` once lingering is on, or log in
   one of those ways, and run the step again.
6. Prints the two URIs you need next:

   ```
   Google OAuth redirect URI:   https://board.example.com/auth/callback
   claude.ai connector URL:     https://board.example.com/mcp
   ```

The server is not up yet: `doctor` starts it after step 3. It also needs at least one allowed email.
With `--yes` and no `--emails` the allowed-email list is empty, and `doctor` will not start the server
until one is set in `[auth] allowed_emails`, so pass `--emails`.

## 3. The Google OAuth client

In the Google Cloud console create an OAuth client of type *Web application*, add the printed redirect
URI, then put its id and secret into `oauth.env` with your editor:

```bash
"${EDITOR:-nano}" ~/.config/stackshot/oauth.env
./stackshot doctor
```

`doctor` starts the server when `oauth.env` holds both values and at least one allowed email is set; a
server that is already running is not restarted (after changing `oauth.env` on a running server, run
`systemctl --user restart stackshot.service` yourself). It also reports whether lingering is on, and counts
it missing when it is off: without it the services stop at
logout and do not start at boot. It says whether the data repository has an origin remote. It checks `/healthz` and the OAuth metadata at your
base URL from the box itself, not from outside, so a front that only the box can reach still reports ok;
the outside check is the browser test in step 5. It lists anything still missing. Run it any time
something looks off. Until step 6 it reports the Claude Code hooks missing and exits 1: that is
expected at this point.

## 4. The HTTPS front

Point your tunnel or reverse proxy at `127.0.0.1:8020`. If you will run anchor-hub with webhooks, also
expose `127.0.0.1:8010` under the address you put in `[anchor_hub] hook_url`. `./stackshot doctor`
checks your base URL from the box itself, which does not prove the front works from elsewhere: verify it
from a browser on another machine by opening `<base URL>/.well-known/oauth-authorization-server`, which
answers with JSON once the front is live.

**Decide who may see the board page before you open the front.** `[auth] ui_open` defaults to `true`: the web
board is then served to anyone who can reach the address, because an instance often puts an access proxy
(for example Cloudflare Access) in front of it and lets that decide. Without such a proxy, set `ui_open = false` in
`~/.config/stackshot/stackshot.toml`: the server then asks for the same Google sign-in as the connector and lets in
only the `[auth] allowed_emails`. It needs no second OAuth client and no new redirect URI at Google, and a saved
change is live at once (no restart).

## 5. The claude.ai connector

In claude.ai: Settings, Connectors, Add custom connector. Name it **Stackshot** (it becomes the tool
prefix in Claude Code, `claude.ai Stackshot`, so the tools are `mcp__claude_ai_Stackshot__create`, `__update` and
`__complete`). The PostToolUse hook that `client install` writes runs on every MCP tool (`mcp__.*`); `pages.py` recognizes
a board write by the server's name inside the tool name, and, once `connectors.py build` has written a connector catalog
(`[portal] catalog_file`), by that catalog, which also lets it see a write made inside an MCP portal's Code Mode script.
Paste the connector URL, connect, and sign in with one of the allowed Google accounts. claude.ai's two callback URIs are
already in your config.

Open a new claude.ai chat and ask it to call the connector's `brief` tool. The empty board comes back.

## 6. Claude Code on the server box

```bash
./stackshot client install
```

This adds four hook lines to `~/.claude/settings.json` (SessionStart, UserPromptSubmit, Stop, and
PostToolUse on the connector's write tools), each pointing at a script in the checkout's
`client/hooks/`; it also (re)starts this box's puller. There is no confirmation prompt: it prints the diff, backs up
`settings.json` to `settings.json.bak-<timestamp>`, and writes; a line already present is not added
twice. To look first, `--print` prints the lines for you to add by hand and writes
nothing. Start a new Claude Code session: the connector appears as `claude.ai Stackshot`, the brief is
injected at start, and a board write that leaves its page untouched is nagged at the next prompt, for the session
that owes that page (see step 8). If you run the stackshot Claude Code plugin, `doctor` counts the hooks that
plugin carries as well as the four above, and its hooks line says how many came from the plugin.

The page gate nags: a page debt is said at the next prompt, and again at every prompt while it is owed;
nothing is held. The Stop hook asks nothing about pages. It holds a turn only for the board check, which is
off until you set `[board_check] mode` (README, "The board check at the end of a turn"). The hooks read the
config at each run, so no restart is needed.

## 7. Another machine

On the server box, mint a token for it and copy the file over:

```bash
./stackshot client mint laptop          # writes ~/.config/stackshot/client-tokens/laptop.token
```

A name that already has a token is refused, so a second `mint` cannot silently cut off the machine
that holds it; `client mint laptop --rotate` replaces it, and the old file stops working at once.

On the machine (Linux with systemd; Windows per `docs/windows.md`; on macOS, untested, `client install`
stores the token and adds the hooks but only prints how to run the puller):

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
cd ~/stackshot
./stackshot client install --url https://board.example.com --token-file ~/Downloads/laptop.token
```

It stores the token and URL under `~/.config/stackshot`, installs and starts the puller (which fetches
notices and messages for the sessions on that machine), and adds the same four hooks. On a machine with
no config of its own (and no `STACKSHOT_CONFIG`) it also writes `~/.config/stackshot/stackshot.toml`
from the instance's settings, read from the server (timezone, page flavor and directories, subject
prefixes, the page gate, the mirror URL; nothing secret), so the hooks there speak in your timezone and
flavor; an existing config is never touched. The puller there is a user unit too, so lingering applies
as in step 2: `install.sh` switches it on when it may, otherwise warns with the command root runs once
on that machine (`sudo loginctl enable-linger <user>`); without it the puller stops at logout.

Pages are read through the server's client API, so the machine needs no copy of the pages directory.
When a session there owes a page, the nag names it as `<key>.md` "in a checkout of the pages
repository, which this machine has none of": edit it in such a checkout (on the server box, or a clone
anywhere), commit and push; with `[pages] flavor = "gbrain"` the nag names gbrain's tools instead.

`./stackshot doctor` works there too. A machine with no `oauth.env` and no installed `stackshot.service`
is a client machine, and doctor says so on its first line. It then checks only this machine's half:
the config, the client token, that the server answers `client.py get whoami` for that token (and with
which machine name), lingering and the puller when the puller's unit is installed, and the four hooks.
It never checks or starts the server's units there. A unit check it could not run (the user manager
out of reach) is a warning, and doctor then exits 1 rather than reporting "all good".

A machine where no puller runs can pass `--no-puller`: `client install` then adds three more hooks
(`client.py register` on SessionStart, `drain` on UserPromptSubmit, `seen` on Stop), so its sessions
register themselves and fetch what waits for them at each prompt.

## 8. The first item

In any session: call `create` with a subject that starts with one of your prefixes, `project =
"projects/getting-started"`, and a `next` line. The board at your base URL shows it within seconds,
the data repository has a commit, and a page update is owed for `projects/getting-started`: that is the page
rule, and `RULES.md` says how it works. By default (`[pilot] writer_owes_page = false`) the page's keeper is
charged and the router passes it the update; with `writer_owes_page = true` the session that wrote owes it and,
after `[page_rule] grace_minutes`, its next state-changing write is refused until the page is committed. The
owing session's next prompt carries the nag. A project made with no page owes none (see "Adding a project").

## Adding a project

A project is an entry in `project-record.json` in the store, keyed by a permanent id (`prj_` and eight hex
digits). Its page is optional: the entry may point at a page of this instance, at a link to another knowledge
base, or at nothing. Make one from the checkout (global flags go before the command):

```bash
python3 tools/project.py --by you create Acme --scope general
```

That project has no page and none is made; add `--make-page --page projects/acme` for a page, or
`--page https://example.com/acme` for a pointer. The other commands are `rename`, `move-page` (needs
`[pages] flavor = "gbrain"`, so it refuses on plain pages), `archive` and `reopen`, `agent-add`, `agent-retire`,
`agent-rename`, `mirror` and `show`; `--dry-run` writes nothing. `README.md` ("Projects: the record first")
has the table (so does the docstring at the top of `tools/project.py`; `--help` lists only the command names, and `<command> -h` the flags). The client API has the same verbs as `client.py post project`, `post project-agent`, `post project-agent-rename` and `post project-agent-retire`; `client.py post project -h` prints only a one-line usage. Each verb writes the record
first and then, for a project with a page here, three lines of the page's frontmatter (`display-name:`,
`agents:`, `status:`). On plain pages the server writes a page file into `paths.brain` and does not commit or
push it. A project with a page and an agent (`agent-add`) gets a default mover from that agent. A project with no page does not: every item filed on it needs an explicit mover, or `create` is refused with "names no mover".

## Optional pieces

- **anchor-hub.** Fill `[anchor_hub]` (`enabled = true`, `hook_url`) and create
  `~/.config/stackshot/anchor-hub/env` (one `NAME=value` per line) with the tokens of the receivers you want:
  Slack (create the app from `anchor-hub-slack-manifest.json`, Socket Mode on; `SLACK_USER_TOKEN` is the
  user token and `SLACK_APP_TOKEN` the app-level token), Notion (`NOTION_TOKEN`, an integration token;
  `NOTION_HOOK_TOKEN` is optional, and without it Notion is polled instead of pushed), Google Drive and
  Gmail (set `[anchor_hub] google_oauth_envs` to `{ <label> = "<path to an oauth.env>" }`, the file holding
  `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`, then run `anchor-hub-google-auth.py <label>`
  once per account), GitHub (the `gh` login you already have). Then run `./install.sh units --start`, which
  installs and starts the unit (and restarts the server): `doctor` only starts units while the server is
  down, so on a running instance it does not.
  Each receiver is independent; a missing token only disables that one.
- **A warm standby on a second machine.** `STACKSHOT_READ_ONLY=1` (a systemd drop-in on `stackshot.service` and
  `anchor-hub.service`) makes an instance read-only, for a board whose data directory is copied over from the
  live one: every write is refused, nothing runs in the background, and removing the drop-in and restarting
  promotes it. Which units stay off, what the copy job touches and the promotion steps are in
  [`docs/read-only-standby.md`](docs/read-only-standby.md).
- **A fleet operator.** If one session on the server box operates the others (relaunches them, runs
  cues), name it in `[fleet] operator_session`; the connector's `sessions` tool then shows it to cloud
  sessions as the one to hand fleet work to. Nothing else changes.
- **A Cloudflare MCP portal.** Fill `[portal]` and the portal's callback URI in
  `[auth] allowed_client_redirect_uris`, then run `./install.sh units --start`: it installs the sync unit
  that pushes the tool list to the portal after every server restart, and restarts the server so the
  sync runs once. `doctor` only starts units while the server is down, so on a running instance it does
  not.
- **Your own page store.** The pages directory can be any git checkout of markdown with YAML
  frontmatter (`title`, `display-name`, `agents`, `board`, `status`), under `projects/` and `infra/`, or the
  directory names you set in `[pages] dirs` (keep `[registries.projects] match` in step with it). An instance can point it at the GitHub mirror of a
  gbrain brain; `[pages] flavor = "gbrain"` switches the nag texts to gbrain's tools, `"plain"` (the
  default) tells sessions to edit the file and commit.

## Updating

```bash
cd ~/stackshot && ./deploy.sh
```

fast-forwards to `origin/main`, re-renders the units that changed, restarts only the affected
services (with `systemctl --user`) and waits for
`/healthz`. `./stackshot doctor` afterwards is a good habit. The checkout's `origin` must be a repository
that carries `main` (the one you cloned in step 1): without it, deploy refuses with
`cannot fetch main from origin (…)` and changes nothing.

Run `./deploy.sh` on its own; do not `git pull` first. deploy.sh decides what to restart by comparing the checkout's
current commit with `origin/main`. After a manual `git pull` (or `git merge`) the two are equal, so it prints
`already at origin/main; nothing to deploy` and restarts nothing: the old code keeps running. If that has happened,
`./install.sh units --start` re-renders the units and restarts the server, the config watcher, the puller and (when
enabled) anchor-hub; the board is republished by the publisher's next run, within ten minutes.

### Changing the config

Edit `stackshot.toml` and save: nothing else to run. `stackshot-reload.path` sees the file change and
`stackshot-reload.service` runs `systemctl --user reload` on the server and anchor-hub, which sends each a
SIGHUP; each re-reads the file and checks it as `python3 config.py check` does. What happens next, in the
journal (`journalctl --user -u stackshot.service`, lines starting `config reload:`):

- **A valid file** is live at once: the next tool call, gate, render or delivery reads the new value, and the
  server publishes the board once.
- **A broken file** (a TOML syntax error, a removed mode) is refused with the reason; the service keeps
  running on the config it had.
- **A setting only a start can apply** is logged as `<key> changed: takes effect at the next restart` and
  keeps its running value until then: the bind address (`[server]`), the OAuth setup (`[auth]` mode, base_url,
  allowed_client_redirect_uris, portal_identity), every `[paths]` entry, `[ids] letter`, the text written
  into the tool descriptions (`[instance]` name, owner, board_url, timezone, `[subject] prefixes`,
  `[fleet] operator_label`, `[freshness]`) and anchor-hub's receiver setup (`[anchor_hub]` hook_url, hook_port,
  slack_team, self_emails, gmail_topics). `[server] port`, `[instance] timezone`, `[anchor_hub] enabled`,
  `[audit] enabled` and `at`, and `[portal]` also need `./install.sh units` first, since the units carry
  them. The list is `RESTART_ONLY` in `config.py`; `systemctl --user restart stackshot.service` (and
  `anchor-hub.service`) applies them.

Code is not watched: `./deploy.sh` restarts what a change touches. A reload by hand is
`systemctl --user reload stackshot.service`.

### An instance installed in the system scope

Earlier releases could install the server's units under `/etc/systemd/system` (`[units] scope = "system"`). That
option is gone: the units are user units, and a config that still says `scope = "system"` (or names one of the
removed `[client]` modes: `reads`, `sessions`, `delivery`, `liveness` at a value other than `api`, `client`, `inbox`,
`puller`) is refused by `config.py`, so `install.sh`, `deploy.sh`, `doctor` and the reboot hooks stop with one line
naming the key; `install.sh units` also refuses while a system-scope `stackshot.service` is enabled or running. Such an
instance moves to user units **before** updating, with the previous release's section
"Moving an instance from system to user scope" (a section of that release's INSTALL.md, which this repository does not keep),
then updates as above. The keys themselves may stay in the config at their one remaining value (`doctor` lists them as
obsolete) or be dropped; the system unit files left disabled on disk are harmless and `doctor` notes them.

## Where things are

| | Path | Set by |
|---|---|---|
| config | `~/.config/stackshot/stackshot.toml` | setup, then you; on another machine `client install` writes it once from the server's settings |
| secrets | `~/.config/stackshot/` (`oauth.env`, `ui-session.key`, `client.token`, `client-tokens/`, `anchor-hub/`) | setup, you, `client mint` |
| state | `~/.local/state/stackshot/` (ledger, inbox, routing, cimd cache); the services log to journald | the services |
| data | `~/stackshot-data/` (store, `board.md`, `RULES.md`, `pages/`) | the publisher and you |
| units | `~/.config/systemd/user/`: `stackshot.service`, `stackshot-reload.service` (reloads the server and anchor-hub when the config file changes: SIGHUP, no restart), `stackshot-reload.path` (the watcher that triggers it), `stackshot-puller.service`, and with their options `stackshot-portal-sync.service`, the portal drop-in `stackshot.service.d/portal-sync.conf` and `anchor-hub.service` | `install.sh` via setup |
| hooks | `~/stackshot/client/hooks/` (in the checkout; `client.sh` for a machine with `--no-puller`) | the repository; `client install` wires them |

A typical deployment is described in the README: one server box, further client machines, a gbrain brain as the page store,
an access proxy in front, and sala as the fleet operator.
