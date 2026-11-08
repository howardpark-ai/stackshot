# A read-only standby copy

What this page covers: running a second, read-only copy of the board on another machine and taking over from it. Back to the [README](../README.md).

A second stackshot instance can run "warm" on another machine (a standby host) from a copy of the live
board's data directory that a job re-copies every few minutes. The warm instance must never change anything: a
write there would fork the board. `STACKSHOT_READ_ONLY=1` makes it read-only, and one switch makes it read-write
again at takeover.

## The switch

`STACKSHOT_READ_ONLY=1` in the environment of the `stackshot.service` process and of the `anchor-hub.service`
process. Exactly `1` turns it on; `0` or unset is normal mode (so is any other value, `true` and `yes` included). It is read once when the
process starts (`stackshot/core/readonly.py`, `is_read_only()` is the one place every gate asks), so a change needs a restart.

It is an environment variable and not a config key on purpose: the data copy and the config file both come from
the live box, so a key in either would be copied over and the switch would arrive on the live instance, or leave
the standby, with the next copy. The switch belongs to the standby machine itself.

## Start read-only

On the standby, a systemd drop-in for each of the two units that run there:

```
# ~/.config/systemd/user/stackshot.service.d/read-only.conf
[Service]
Environment=STACKSHOT_READ_ONLY=1
```

```
# ~/.config/systemd/user/anchor-hub.service.d/read-only.conf
[Service]
Environment=STACKSHOT_READ_ONLY=1
```

then `systemctl --user daemon-reload` and `systemctl --user restart stackshot.service anchor-hub.service`.

Units that run on the standby: `stackshot.service` and `anchor-hub.service` (standby mode, below). Units that do
NOT get enabled there, because each writes or acts outward:

| Unit | Why not |
|---|---|
| `stackshot-puller.service` | fetches this machine's notices and messages from the server and delivers them to sessions |
| `stackshot-audit.service` and `stackshot-audit.timer` | the daily board audit: runs a model and writes items |
| `stackshot-portal-sync.service` and the drop-in `stackshot.service.d/portal-sync.conf` | re-syncs the MCP portal's copy of the tool list (an outward write) |
| `stackshot-reload.path` and `stackshot-reload.service` | reload on a config change; the standby's config is a copy, and nothing there needs a reload |

`./install.sh units --start` (and `deploy.sh`, which sources `units/scope.sh` as `install.sh` does) installs, enables and starts every unit the config calls for, the ones above included. On the standby do not run it as it is: install the two units, add the drop-ins first, and enable only those two (`systemctl --user enable --now stackshot.service anchor-hub.service`). `scope.sh` is only the shell library those scripts source; it starts nothing itself.

## What the copy job must touch

The data age on `/healthz` and in the banner is the time since the newest modification time among the store
directory's top level (its files, its letter directories and the directory itself) and a marker file. The copy job
should `touch <store>/.synced-at` (the store is `[paths] store`, the `store` directory of the data directory)
after every successful copy, so the age stays low while the live board is quiet. A store that nobody copies into
grows older every second, which is the signal to look at the copy job.

## What the read-only instance does

- **Reads work:** the web pages (home, items, projects, sessions, search, For you, rules) and the MCP read tools
  (`get`, `brief`, `sessions`, `rules`, the `anchors` listing). The home page and `/board.md` are rendered in
  memory from the copy's store; the search index is in memory and holds items, projects and sessions (not item
  History).
- **Every write is refused** with one sentence: `stackshot here is a read-only standby copy (STACKSHOT_READ_ONLY);
  writes go to the live board.` MCP write tools (`create`, `update`, `complete`, `confirm`, `message`, `route`,
  `bump_versions`, and `anchors` with an add or remove) answer it as a tool error. Every web route answers a POST,
  PUT, PATCH or DELETE with HTTP 503 and the same sentence; so does `/audit/now` for any method. `/runners` answers
  the same refusal, since it exists to show live GitHub runs; its Disable / Enable button, `POST /runners/switch`, is refused like any other POST.
- **Backstops under the tool and route level:** the store's write functions (`_save`, `_next_id`, the anchors,
  projects, publish and GitHub-mirror writers) raise, and an audit hook refuses a file write, rename or removal
  under the store, state directory, repository, markdown file, page store and project-touch directory, and a git
  write command started from the process.
- **Nothing runs in the background:** no start-time passes, no runner, publish loop, router,
  runners rebuild, on-disk search index or GitHub mirror, and no delivery to a session, Slack post, gbrain
  write, git commit or push. The server logs one line at start saying so. Nothing is written to the board data
  directory or to `~/.local/state/stackshot`, and a missing state directory is tolerated.
- **Not behind the 503 wrapper:** FastMCP's own `/register`, `/authorize` and `/token` routes, and the OAuth client and token state it
  keeps in its own directory, because signing in on the standby needs them. That state is local to the standby and is not board data.
  For the same reason the web UI's session key, `<secrets>/ui-session.key`, is created on the first Google sign-in on the standby. This is expected, and the key stays local to the standby.
- **Not blocked:** outbound HTTPS in general. Google sign-in for the web UI needs it, so there is no socket-level
  block; the guarantee is that no code path that writes or acts outward is started or reachable.
- **A banner** on every web page: `Read-only standby copy — data as of <time>`.

### /healthz

Normal mode answers as it always did. On the standby the first line is still `ok`, with one more line:

```
ok
read-only: yes; data age: 143s
```

`/healthz?format=json` (and `/healthz.json`) answer on both, public like the plain one:

```
{"ok": true, "read_only": true, "data_age_s": 143, "commit": "0103c0de0103"}
```

`read_only` is `false` on the live instance; `data_age_s` is `null` when the store cannot be read; `commit` is the
short head of the checkout, `null` when it cannot be read.

## anchor-hub on the standby

`anchor-hub.service` runs warm under the same drop-in. With `STACKSHOT_READ_ONLY=1` it starts no receiver (no
Slack socket, no Google, Notion or GitHub poll, no rescan), delivers nothing, pushes nothing and writes nothing to
the board data or its state. It still binds the hook port (`[anchor_hub] hook_port`, default `127.0.0.1:8010`)
and answers every request, any method and any path, with HTTP 503 and the body `standby (STACKSHOT_READ_ONLY)`,
so a port check gets an HTTP answer and a webhook sender is told to retry. SIGTERM stops it, SIGHUP is ignored.

## Promote (takeover)

1. Stop the live instance (or make sure it is down), then make the final copy of the data directory, and
   `touch <store>/.synced-at`.
2. Remove both drop-ins:
   `rm ~/.config/systemd/user/stackshot.service.d/read-only.conf ~/.config/systemd/user/anchor-hub.service.d/read-only.conf`
3. `systemctl --user daemon-reload`
4. `systemctl --user restart stackshot.service anchor-hub.service`: both start as a normal instance (the passes,
   loops and receivers run).
5. `curl -s http://127.0.0.1:8020/healthz` answers `ok` alone, and `?format=json` says `"read_only": false`.
6. Then enable the other units: `stackshot-puller.service`, `stackshot-audit.timer`, and where used
   `stackshot-portal-sync.service` with its drop-in and `stackshot-reload.path`.

To go back to standby, add the drop-ins again, `daemon-reload`, restart, and disable the units in step 6.
