# Installing stackshot as your own board (draft v0.3)

Written for a technical reader who has never seen stackshot, and for the Claude Code assistant that helps them.
Scope: the board alone. Last checked against the `main` that carries this file (its git log names the commit).
Lines marked `TODO(verify)` are things the code could not confirm. Check them on the real box.
The same procedure for the AI assistant is [board-alone-guide-for-ai.md](board-alone-guide-for-ai.md). The full reference is [INSTALL.md](../INSTALL.md).

## 1. What stackshot is

stackshot is a task board for one person and the Claude sessions that work for them.

- A **board item** is one human-level thing: a deliverable a session owns, a decision you must make, a blocker on someone outside, or a handoff. Working steps (read, edit, run) never go on the board.
- Every item has a **mover**. That is the session (or you) whose turn it is.
- An item can be waiting on **you** (`needs: decision`) or on someone **outside** (`needs: external`). Otherwise its mover can act.
- Every item belongs to a **project**. A project usually has a **project page**: a markdown file with a `Current state` and a `Timeline`. The page is where a fresh session picks the work up. The page is optional: a project can be made with no page at all (see section 4).
- The page rule: a board change on a project that has a page is the page's to account for. By default the server charges the page's keeper (the agent the page lists) and the router passes it the page update; the hooks remind the session that owes it at its next prompt. With `[pilot] writer_owes_page = true` the writing session owes it itself, and after `[page_rule] grace_minutes` (30) the server refuses its next state-changing write until the page is updated. On a one-session install no other agent keeps the page, so the update is yours to make.
- Sessions use the board through one **connector** (an MCP server). It works from claude.ai chats and from Claude Code on your machines. Its tools are `brief`, `get`, `create`, `update`, `confirm`, `complete`, `anchors`, `route`, `message`, `sessions`, `rules` and `bump_versions`.
- You see the same board in a browser at your own address. It is a web page plus a `board.md` file committed to git.

Everything runs as your own user on one Linux box. No `sudo`, except one optional command (see the checklist).

## 2. What you need before starting

Tick each line before step 1.

- [ ] A Linux box with systemd. You log in as an ordinary user. Python 3.12 or newer is the system `python3` (check: `python3 --version`).
- [ ] `git`, `curl` and `uv` installed. `uv` fetches Python 3.12 for the server by itself.
- [ ] Lingering for your user. User services need it to survive logout and to start at boot. Setup tries to switch it on. If it cannot, it prints one command for root: `sudo loginctl enable-linger <your user>`.
- [ ] A public HTTPS name (for example `board.example.com`) that forwards to `127.0.0.1:8020` on the box. A tunnel, Caddy, nginx or similar. Your choice. You set it up in step 9.
- [ ] A Google account, and a Google Cloud project where you can create an OAuth client (step 6).
- [ ] A claude.ai plan that allows custom connectors (Pro, Max, Team or Enterprise).
- [ ] Claude Code installed on the box and signed in with that claude.ai account. The server's router runs `claude -p` as you.
- [ ] A **private** git repository for the board data, and git credentials on the box that can push to it (an ssh key or a credential helper). Create the repo on GitHub now. Do not add a README or any file to it (see step 5).

Not needed: gbrain, Postgres, sala, Cloudflare Access, or any other repository.

## 3. Install, step by step

Run each command on the server box, as your own user.

### Step 1. Get the code

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
```

The repository is public, so a plain clone works: you need no access request and no git credentials for it. Clone it to `~/stackshot`. The server refuses a bare start from any other folder (the units set the config path themselves, so the services do not care).

Do not edit files inside this folder. The update script refuses to run if tracked files changed.

### Step 2. Go into the checkout

```bash
cd ~/stackshot
```

### Step 3. Run setup

```bash
./stackshot setup
```

Setup asks for these. The defaults are in brackets.

- Your name as the board should say it (your Linux user name).
- Your timezone.
- The public base URL, for example `https://board.example.com`. Use the final public name now. The default is the local address.
- The Google emails allowed to sign in, comma-separated. Give at least one. With none, the server will not start.
- Subject prefixes, comma-separated, for example `[work] ,[home] `. Every item subject must start with one. The default is `[todo] `.
- Where the data repository lives (default `~/stackshot-data`).
- Where the project pages live (default `~/stackshot-data/pages`, inside the data repository).

It needs a real terminal. In a script, pass every answer as a flag and add `--yes` (see `./stackshot setup -h`). `./stackshot setup --no-systemd` skips the user-services part (item 5 below) and says how to install the units later: use it on a box where `systemctl --user` is out of reach, then run `./install.sh units --start` when it is.

Setup then does this, in order, and says so as it goes:

1. Writes `~/.config/stackshot/stackshot.toml`, a full copy of the example config with your values.
2. Creates the data repository (branch `main`, one commit), a short `RULES.md`, and a first page `projects/getting-started.md`.
3. Creates the secrets folder `~/.config/stackshot/` (mode 0700) and an `oauth.env` with two empty keys.
4. Mints a client token for this box.
5. Installs the user services (server, config watcher, puller) and starts the puller. It does not start the server yet.
6. Prints two addresses you need next: the Google redirect URI (`<base>/auth/callback`) and the connector URL (`<base>/mcp`).

Keep those two addresses. If it printed a lingering warning, run the `sudo` command it shows, once.

### Step 4. Make the board page ask for sign-in

By default the board page is open to anyone who can reach the address, because the design expects an access proxy in front of it. You do not have one. Switch the board's own Google sign-in on:

```bash
sed -i 's/^ui_open = true/ui_open = false/' ~/.config/stackshot/stackshot.toml
```

Check it:

```bash
grep -n '^ui_open' ~/.config/stackshot/stackshot.toml
```

Good result: one line, `ui_open = false`. This setting is read live. No restart is needed. It needs no extra redirect URI at Google.

### Step 5. Connect the data repository to your private repo

Add the remote. Use your own repo URL.

```bash
git -C ~/stackshot-data remote add origin <your-private-repo-url>
```

Push once yourself.

```bash
git -C ~/stackshot-data push -u origin main
```

Do not skip this. The publisher fetches `origin main` before it pushes anything. On an empty remote that fetch fails, and the publisher then quietly never pushes. The first push by hand creates `main` on the remote and sets the upstream.

If you want to keep everything local for now, set `[publish] git = false` in the config instead.

### Step 6. Create the Google OAuth client (you do this in your browser)

In the Google Cloud console, open your project, then APIs & Services, then Credentials.

1. Set up the OAuth consent screen if the project has none. The server asks for the scopes `openid` and your email address only.
2. Create credentials, then OAuth client ID, type **Web application**.
3. Under Authorized redirect URIs add exactly the address setup printed: `https://board.example.com/auth/callback`, with your own name.
4. Create it and keep the page with the client ID and the client secret open.

`TODO(verify)`: exact console labels and whether a consent screen in "Testing" status needs your account added as a test user.

### Step 7. Put the client ID and secret into `oauth.env`

Open the file in your editor. Do not paste the secret into a shell command.

```bash
"${EDITOR:-nano}" ~/.config/stackshot/oauth.env
```

Fill in both values, one per line, no quotes needed:

```
STACKSHOT_GOOGLE_CLIENT_ID=<the client id>
STACKSHOT_GOOGLE_CLIENT_SECRET=<the client secret>
```

Save. The file is mode 0600. Do not commit it or paste it into chat.

### Step 8. Start the server with doctor

```bash
./stackshot doctor
```

`doctor` prints a checklist. Each line starts with `ok`, `warn` or `missing`. With both OAuth values and an allowed email set, and the server not running, it starts the server and waits for it.

Good result at this point: the server answers `/healthz`, and the user services are `active`. Two lines still say `missing` until the next steps: "OAuth metadata reachable" (the HTTPS front) and "Claude Code hooks ... 0 of 4". The command exits 1 for now. That is expected. It also exits 1 when it could not run a unit check (for example the user manager was out of reach), and it then says so as a warning rather than printing `all good`.

### Step 9. Set up the HTTPS front (you do this)

Point your tunnel or reverse proxy at `127.0.0.1:8020`, under the name you gave as the base URL. Use any tool you like.

Check it from a browser on another machine. Open:

```
https://board.example.com/.well-known/oauth-authorization-server
```

Good result: a page of JSON. Then run doctor again.

```bash
./stackshot doctor
```

Good result: "OAuth metadata reachable" is `ok`. Only the hooks line is still `missing`.

### Step 10. Add the connector in claude.ai (you do this)

1. In claude.ai open Settings, then Connectors, then Add custom connector.
2. Name it exactly **Stackshot**. Claude Code builds its tool names from this name (`mcp__claude_ai_Stackshot__create`, and so on).
3. Paste the connector URL setup printed (`https://board.example.com/mcp`).
4. Connect, and sign in with one of the Google accounts you allowed.

Test: open a new claude.ai chat and ask it to call the Stackshot connector's `brief` tool. Good result: the empty board comes back.

### Step 11. Add the Claude Code hooks

```bash
./stackshot client install
```

It prints a diff, backs up `~/.claude/settings.json` to `settings.json.bak-<timestamp>`, and adds four hook lines (SessionStart, UserPromptSubmit, PostToolUse on MCP tools, Stop). It asks nothing. To look first, run it with `--print`: it writes nothing. If you run the stackshot Claude Code plugin, doctor counts the hooks that plugin carries too (its line says how many came from the plugin).

Start a new Claude Code session. Good result: the connector shows up as `claude.ai Stackshot`, and the brief appears at session start.

Run doctor once more.

```bash
./stackshot doctor
```

Good result: `all good`, exit 0.

### Step 12. Create the first item and see it in claude.ai

In a new Claude Code session, or in a claude.ai chat with the connector, ask for something like this:

> Create a board item with the Stackshot connector. Subject: `[todo] Try the board` (use your own prefix). Project: `projects/getting-started`. Description: one `- ` bullet that opens `Goal:` and states the outcome you want (for example `- Goal: the board shows this first item`); the server refuses a description whose first bullet does not start `Goal:`. Sender and mover: the same short name for this session. Add one `next` line that starts with that session name and a colon.

Good result, all of these:

- The tool call succeeds.
- The board at your base URL shows the item within seconds (sign in with Google if asked).
- A new commit appears in the data repository.
- A page update for `projects/getting-started` is owed. That is the page rule (section 1): by default it is charged to the page's keeper, and with `writer_owes_page = true` to the session that wrote. To settle it, edit `~/stackshot-data/pages/projects/getting-started.md` (its `Current state` and a dated line under `Timeline`), then commit and push. The reply to `create` on a `projects/getting-started` item says so: "pilot project: this change is charged to the router, which passes the page update to the agent that keeps the page". On a one-session install no other agent keeps the page, so do the update yourself.

Then open claude.ai, start a new chat, and ask it to call `brief`. Your first item is in it.

Why the mover is named: the server's default mover is the project's builder, else its `-main` agent, else the session named by the page's `display-name:` line. A fresh page lists no agents, so the default is that `display-name:` session, which nothing answers to on a solo install: `create` without `mover` is not refused, the item is stored with a mover that does not exist, and the stall pass later logs "nobody could take it". (Only a project with no page, `prj_...`, has no name line and is refused with "names no mover".) A bare wait a session sets on its own item (a `wake`, or a `next` step dated later than today) needs a `wait_reason` (a wake with `hold=true` and `wait_basis` does not), and the server may refuse it when one model call judges the step could be done now (`[wait_guard]`, on by default; it lets the write through when the call fails).

## 4. Adding a project

A project is an entry in the board's project record, `project-record.json` in the server's store, with a permanent id (`prj_` and eight hex digits), a name, a scope and a status. A **page is optional**: the entry can point at a page in your pages folder, at a link to another knowledge base, or at nothing.

Make one with `tools/project.py`, run from the checkout on the server box. The flags that apply to every command (`--by LABEL` for who the record names, `--dry-run`, `--json`) go **before** the command name. `--dry-run` shows what would be written and writes nothing.

```bash
cd ~/stackshot
python3 tools/project.py --by you create Acme --scope general
```

That makes a project named `Acme` with no page. Add `--make-page --page projects/acme` to make a page for it, or `--page https://example.com/acme` to point at a page you keep elsewhere. Items can be filed on the project by its id (`prj_...`), and a project with no page gets no page reminders.

The verbs that exist today:

| Command | What it does |
|---|---|
| `create NAME --scope S [--page KEY\|LINK] [--make-page] [--title T]` | A new project. With no `--page` it has no page and none is made. |
| `rename PROJECT NEW_NAME` | The name changes, the id stays, the old name is remembered. |
| `move-page PROJECT NEW_KEY` | Moves the project's page to a new key and points the project at it. Needs `[pages] flavor = "gbrain"`: it refuses on a plain-pages install (the default), because the page-moving tools are gbrain's. |
| `archive PROJECT [--why W]` and `reopen PROJECT` | Sets the status to `archived` and back; the page's `status:` line follows. |
| `agent-add PROJECT NAME (--front\|--back) --mandate M` | Lists an agent (a session name) on the project with a one-line mandate. On a project with a page the listed agent becomes the default mover. On a project with no page it does not: every item needs an explicit `mover`, or `create` is refused with "names no mover". |
| `agent-mandate PROJECT NAME --mandate M` | Changes the one-line mandate of an agent already listed (`agent-add` refuses another mandate for a listed name, and a hand edit of the page's line is overwritten by the next page write). The record changes first, then the page's `agents:` block. |
| `agent-retire PROJECT NAME`, `agent-rename PROJECT OLD NEW` | Take an agent off, or rename its entry. Retiring the last agent of a project with no open item archives it. |
| `mirror PROJECT [--make-page]` | Writes the page's three mirror lines again. |
| `show PROJECT` | Prints the entry. |

`PROJECT` is the id (printed by `create`), the page key or a bare slug. `show` also resolves the project's name or a former name, but `mirror <name>` returned 404 for a page-less project where `show <name>` found it: give `mirror` the id. A key below another page (`projects/acme/notes`) is a sub-page, and sub-pages are never projects.

The record is written first. When the project has a page in your pages folder, the tool then rewrites three lines of the page's frontmatter from the record (`display-name:`, `agents:`, `status:`) and nothing else. A hand edit to those three lines is overwritten by the next write: change them through the verbs. Under `[pages] flavor = "plain"` the page is a markdown file in the pages folder, and neither the tool nor the server commits or pushes it: you do.

The same verbs answer the client API: `python3 ~/stackshot/client.py post project --scope general --name Acme` (or `--key projects/acme` to make the page from the template at once), then `post project-agent`, `post project-agent-mandate`, `post project-agent-rename` and `post project-agent-retire`. The verbs and their flags are listed at the top of `tools/project.py` and in `docs/projects.md` ("Projects: the record first"); `python3 tools/project.py --help` lists only the command names (`<command> -h` shows one command's flags), and `client.py post project -h` prints a one-line usage to stderr and exits 1. There is no verb to delete a project. A project made with no page does not show in `client.py get projects`, and `client.py get project <id>` answers 404 for it; `tools/project.py show <id>` reads it, and items filed on it work with an explicit mover. A page made by hand (a file under the pages folder) is still read by the registry, but it has no record entry until its first verb.

A page file you write yourself starts from `getting-started.md`. The registry refreshes after a write and at least every 10 minutes.

## 5. Using an Obsidian vault for project pages

Project pages are plain markdown files in a git checkout, so an Obsidian vault can be that checkout. You then read and edit pages in Obsidian, and sessions on the server read the same files.

How the pieces move files:

- On the server, sessions edit a page, commit and push.
- The publisher (inside the server) also fetches `origin main` and fast-forwards the data repository before each publish. It does this for the data repository only.
- Your laptop pulls and pushes through git like any other clone.

### Choose a layout

| | A. Separate vault | B. A folder in your main vault |
|---|---|---|
| What it is | A new vault that is a clone of the stackshot data repository. Pages are in its `pages/` folder. | Your existing vault, in its own git repository. The pages are a folder inside it. |
| Server setup | The default. Nothing extra. | Set `paths.brain` to `~/vault/<folder>` in the config, where `~/vault` is a clone of your main vault on the server. On a first install, `./stackshot setup --pages ~/vault/<folder>` writes the same setting. |
| Do laptop edits reach the server? | Yes, by themselves. The publisher fast-forwards the data repository each publish. | Not by themselves. Nothing in stackshot pulls that second repository. You add a pull on the server (below). |
| Extra files in the vault | `board.md`, `RULES.md` and `board-data/` JSON. Obsidian ignores the JSON. `board.md` is a handy read-only view of the board. | None from stackshot. |
| Commit noise | The publisher commits board data every few seconds when the board changes. The vault pulls it. | Page commits only. |

Recommendation: **A**. It has no moving part you have to add. Pick B only if you want pages inside your daily vault and accept one extra timer.

### Layout A: set it up

1. On the laptop, clone your data repository where you want the vault, for example `git clone <your-private-repo-url> ~/StackshotVault`.
2. In Obsidian choose "Open folder as vault" and open that folder.
3. Add `.obsidian/` to a `.gitignore` in that clone, so settings do not get committed into the board data.
4. The pages are in `pages/projects/`.

### Layout B: set it up

1. On the server, clone your main vault, for example to `~/vault`.
2. Make the pages folder: `~/vault/stackshot/projects/`. Keep the folder names in step with `[pages] dirs` (default `["projects"]`) in the config.
3. Set `paths.brain = "~/vault/stackshot"` in `~/.config/stackshot/stackshot.toml`. `paths.brain` is read at start only. Restart the server after changing it: `systemctl --user restart stackshot.service`. Only on a first install, before setup has written a config, can you pass `--pages ~/vault/stackshot` to `./stackshot setup` instead. On a box that already has a config, running setup again exits with code 2 and changes nothing unless you add `--force`, which rewrites the whole config: edit the file instead.
4. Sessions then commit and push into your main vault repository. That repository needs a push credential on the server.
5. Add a job on the server that runs `git -C ~/vault pull --ff-only` every few minutes, so laptop edits arrive. `TODO(verify)`: stackshot has no such job. Write it as a systemd user timer, so it keeps running without any session open.

### Avoid edit conflicts

Two writers share the pages: you in Obsidian, and sessions on the server that commit and push.

- **Pull before you edit.** In Obsidian, run "pull" (with the Obsidian Git plugin: command palette, "Obsidian Git: Pull") before you open a page you will change.
- **Turn on auto-pull in the Obsidian Git community plugin.** Install it from Settings, Community plugins. Set an auto-pull interval of a few minutes and pull on startup. `TODO(verify)`: the exact setting names in the plugin version you install.
- **Commit and push soon after you edit,** or use the plugin's auto commit-and-sync. A long-lived local edit is where conflicts come from.
- **Sessions should pull before they push.** The server's page nag tells sessions to commit and push. Tell your sessions to run `git pull --rebase` first if a push is refused.
- **Edit the body, be careful with the top.** Pages start with a YAML block (`title`, `type`, `status`, `display-name`, and `agents`). The server reads it. Obsidian's Properties editor may rewrite it. `TODO(verify)`: whether it keeps the stackshot parser happy. Prefer editing the text below the block.
- **Edits count only once they reach the server.** The server decides if a page is fresh from its own checkout (the last commit time or the file's modification time). A page edited in Obsidian settles a session's page debt only after it is pulled to the server.
- If a pull stops on a conflict, resolve it in the plugin or in a terminal, then commit and push. Sessions will not do it for you.

## 6. Updating

You receive updates as new commits in the repository.

On the server box:

```bash
cd ~/stackshot
```

See what would happen, without changing anything:

```bash
./deploy.sh --dry-run
```

Apply it:

```bash
./deploy.sh
```

`deploy.sh` does the fetching itself. It fetches `origin main`, fast-forwards, re-renders the services that changed, restarts only the ones the change touches, and waits for `/healthz`. Good result: it ends with `healthz ok at <commit>`.

Two traps:

- **Do not run `git pull` first.** `deploy.sh` decides what to restart by comparing your current commit with `origin/main`. After a manual pull it says "nothing to deploy" and restarts nothing. If you already pulled, run `./install.sh units --start`: it re-renders the units and restarts the server, the config watcher and the puller.
- **Keep the checkout clean.** It refuses with "the production checkout has local changes" if tracked files differ. Your config lives outside the checkout, so you do not need to edit anything in it.

Afterwards, run `./stackshot doctor`.

The repository takes ordinary pull requests, so a clean checkout always fast-forwards to `origin/main`. `deploy.sh` refuses with "does not contain HEAD" only if you made commits in `~/stackshot` yourself. To drop your commits, go back to the last commit of `origin/main` you had, then deploy: `git -C ~/stackshot reset --hard "$(git -C ~/stackshot merge-base HEAD origin/main)"`, then `./deploy.sh`. (Resetting straight to `origin/main` has the same effect as `git pull` first: nothing restarts.)

### Changing the config later

Edit `~/.config/stackshot/stackshot.toml` and save. A watcher reloads the server. A valid file takes effect at once. A broken file is refused with a reason in `journalctl --user -u stackshot.service` (lines starting `config reload:`) and the old config stays. A setting only a start can apply (the server's bind address and port, `[auth]` `mode`, `base_url`, `allowed_client_redirect_uris` and `portal_identity` (not `ui_open` or `allowed_emails`, which are live), every `[paths]` entry, `[ids] letter`, and the text the connector's tool descriptions carry: `[instance]` name, owner, board URL and timezone, `[subject] prefixes`) keeps its running value until you restart. The journal logs `<key> changed: takes effect at the next restart`. `[server] port` and `[instance] timezone` also need `./install.sh units` first, because the units carry them. The full list is `RESTART_ONLY` in `config.py`. Restart with `systemctl --user restart stackshot.service`.

## 7. Left out of this guide

This guide installs the board only. Later options, none needed now:

- **Other machines.** Run Claude Code on a laptop too: `./stackshot client mint <name>` on the server, then `./stackshot client install --url ... --token-file ...` there. See [INSTALL.md](../INSTALL.md), step 7.
- **anchor-hub.** Watches Slack, Notion, Drive, Gmail and GitHub and drops one-line notices into the right session. Off by default.
- **sala.** A tmux session manager for running many long-lived Claude Code sessions. Not required.
- **gbrain.** A Postgres-backed knowledge server that can hold the project pages instead of markdown files. Not required. Pages stay `[pages] flavor = "plain"`.
- **A hooks and rulebook layer.** Your own standing rules and extra hooks for how sessions behave. `RULES.md` in the data repository is the small rulebook the `rules` tool serves.
- Also off by default: the daily board audit, the GitHub mirror of items, the Cloudflare MCP portal sync.

## 8. If something goes wrong

| What you see | Likely cause | Do this |
|---|---|---|
| `doctor` says `oauth.env: 0 of 2 values set` | The file is still empty | Step 7 |
| Server will not start, journal says `auth=google but STACKSHOT_GOOGLE_CLIENT_ID/SECRET not set` | Same | Step 7, then `systemctl --user restart stackshot.service` |
| `doctor` says `OAuth metadata reachable ... missing` | The HTTPS front does not reach port 8020 | Step 9 |
| The board shows nothing new on GitHub | The data repo never got `main` on the remote | Step 5 |
| Google says `redirect_uri_mismatch` | The URI in the Google client differs from `<base>/auth/callback` | Fix it in the Google console, character for character |
| claude.ai refuses to sign in, or says "not allowed on this board" | Your Google email is not in `[auth] allowed_emails` | Add it in the config; it reloads by itself |
| Services stop when you log out | Lingering is off | `sudo loginctl enable-linger <your user>` |
| `systemctl --user` says it cannot reach your user manager | You are in a shell that was not a login | `export XDG_RUNTIME_DIR=/run/user/$(id -u)` or log in again |
| A session is told a project-page update is owed and then refused | The page rule, with `[pilot] writer_owes_page = true` | Edit the page, commit, push, then retry. With the default (`false`) the page's keeper is charged and no write is refused for it |
| A bare wake is refused with "a wait on your own item needs its reason" | `[wait_guard]` | Pass `wait_reason` (at least 15 characters): what the step waits on that is not available now. If nothing blocks the step, do it now |
| `tools/project.py move-page` refuses | A plain-pages install | `move-page` needs `[pages] flavor = "gbrain"`. On plain pages there is no verb for it |
