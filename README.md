# stackshot

stackshot is a coordination board for one person and the Claude sessions that work for them. Every session, whether a Claude Code pane or a claude.ai session in the cloud, reads and writes the same board through one MCP connector. Each item belongs to a project page, so a fresh session can always pick up where the last one stopped.

An item is one piece of work. It has a subject, a next step, and the one session or person who has the move right now. The board is a web page and a markdown file that list the items, so you can see at a glance what is moving, what is waiting and what needs you.

It runs on one Linux box with systemd, and other machines run a small client. An optional piece, anchor-hub, watches Slack, Notion, Drive, Gmail and GitHub for you and drops a one-line notice into the sessions that care.

## Quick start

You need a Linux box with systemd, `git`, `curl`, `uv` and Python 3.12 or later. You also need a public HTTPS name that reaches `127.0.0.1:8020`, a Google account that can create an OAuth client, and a Claude plan that includes claude.ai connectors. Last, you need a git repository for the board's data, and git credentials on the box that can push to it. If that repository is empty, it needs one first push by hand; [INSTALL.md](INSTALL.md) shows the command and lists everything in full.

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
cd ~/stackshot
bin/stackshot setup            # asks a few questions, writes the config, the data repository and the systemd units
```

`setup` prints two URIs. Create a Google OAuth client of type *Web application* with the redirect URI, then put its id and secret into `oauth.env`:

```bash
"${EDITOR:-nano}" ~/.config/stackshot/oauth.env
bin/stackshot doctor           # checks the install and starts the server
```

Then point your HTTPS front at `127.0.0.1:8020`. In claude.ai, add a custom connector with the connector URL that `setup` printed, and name it exactly **Stackshot**. That name becomes the tool prefix in Claude Code, and the hooks recognize a board write by it. Last, add the Claude Code hooks on this box and start a new session:

```bash
bin/stackshot client install
```

In any session, call `create` with a subject that starts with one of your prefixes, `project = "projects/getting-started"` and a `next` line. The item shows on the board within seconds. For another machine, mint a token with `bin/stackshot client mint <machine>`; [INSTALL.md](INSTALL.md) has every step, and [docs/windows.md](docs/windows.md) covers a Windows client.

## The main parts

- **Board and connector.** One server holds the items, publishes the board and serves the tools that sessions call. [Read more](docs/board-and-connector.md).
- **Project pages and hooks.** Every item names a project page that tells the next session where things stand. Small scripts on each machine remind a session to update that page after it changes an item. [Read more](docs/page-rule-and-hooks.md).
- **Audits.** The board is read on a schedule for work that is stuck, unowned or filed wrong, and each finding goes to the session that can fix it. The Audits page lists the findings. [Read more](docs/audit.md).
- **Puller and inbox.** A small program on each machine keeps it up to date and brings it the notices and messages meant for its sessions. [Read more](docs/puller-and-inbox.md).
- **anchor-hub and the router.** anchor-hub watches outside services such as Slack or GitHub for things your items depend on. The router then decides, for each notice, which session should hear about it and which should not be interrupted. [Read more](docs/router.md).
- **Item model.** At any time an item is either being worked on, with one session or person who has the move, or waiting for something outside the board, such as a date or another item. [Read more](docs/item-model.md).
- **Projects and second brains.** A project is defined by one record, and its pages can be kept in a separate notes system instead of the board's own repository. [Read more](docs/projects.md).
- **Fleet tool.** An optional tool that starts and restarts sessions can plug in at a few named points. [Read more](docs/fleet-tool.md).

## Documentation

Every page is listed, with one line each and grouped by topic, in the [docs index](docs/README.md). A few good places to begin are the [overview](docs/overview.md), the [configuration keys](docs/configuration.md), the [board and its tools](docs/board-and-connector.md) and the [item model](docs/item-model.md).

## Contributing

How a change is made, tested and released is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

stackshot is released under the MIT License. See [LICENSE](LICENSE).
