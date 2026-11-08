# stackshot

stackshot is a coordination board for one person and the Claude sessions that work for them. Every session, whether a Claude Code pane or a claude.ai session in the cloud, reads and writes the same board through one MCP connector. Each item belongs to a project page, so a fresh session can always pick up where the last one stopped.

It runs on one Linux box with systemd, and other machines run a small client. An optional piece, anchor-hub, watches Slack, Notion, Drive, Gmail and GitHub for you and drops a one-line notice into the sessions that care.

## Quick start

You need a Linux box with systemd, `git`, `curl`, `uv` and Python 3.12 or later. You also need a public HTTPS name that reaches `127.0.0.1:8020`, a Google account that can create an OAuth client, and a git repository for the board's data. [INSTALL.md](INSTALL.md) lists everything in full.

```bash
git clone https://github.com/howardpark-ai/stackshot ~/stackshot
cd ~/stackshot
./stackshot setup            # asks a few questions, writes the config, the data repository and the systemd units
```

`setup` prints two URIs. Create a Google OAuth client of type *Web application* with the redirect URI, then put its id and secret into `oauth.env`:

```bash
"${EDITOR:-nano}" ~/.config/stackshot/oauth.env
./stackshot doctor           # checks the install and starts the server
```

Then point your HTTPS front at `127.0.0.1:8020`, and add a custom connector in claude.ai with the connector URL that `setup` printed. Last, add the Claude Code hooks on this box and start a new session:

```bash
./stackshot client install
```

In any session, call `create` with a subject that starts with one of your prefixes, `project = "projects/getting-started"` and a `next` line. The item shows on the board within seconds. For another machine, mint a token with `./stackshot client mint <machine>`; [INSTALL.md](INSTALL.md) has every step, and [docs/windows.md](docs/windows.md) covers a Windows client.

## The main parts

- **Board and connector.** One server holds the items, publishes the board and serves the MCP tools. [Read more](docs/board-and-connector.md).
- **Project pages and hooks.** Every item names a page, and hooks on each machine keep it current. [Read more](docs/page-rule-and-hooks.md).
- **Daily audit.** A daily read of the board finds what is stuck or wrong. [Read more](docs/audit.md).
- **Puller and inbox.** Notices and messages reach sessions on other machines. [Read more](docs/puller-and-inbox.md).
- **anchor-hub and the router.** Receivers watch outside things, and the router rules each notice. [Read more](docs/router.md).
- **Item model.** An item is alive with one mover, or waiting for something outside. [Read more](docs/item-model.md).
- **Projects and second brains.** A project is defined by its record, and its pages can live in a second brain. [Read more](docs/projects.md).
- **Fleet tool.** An optional tool that spawns and relaunches sessions plugs in at a few named points. [Read more](docs/fleet-tool.md).

## Documentation

Every page is listed, with one line each, in the [docs index](docs/README.md).

- Start here: [Overview](docs/overview.md), [Scope](docs/scope.md), [Install](docs/install.md), [Windows client](docs/windows.md), [Development](docs/development.md)
- Configuration: [Configuration](docs/configuration.md), [Integrations](docs/configuration-integrations.md), [Keywords](docs/configuration-keywords.md)
- Board and tools: [Board and connector](docs/board-and-connector.md), [Board pages](docs/board-ui.md), [Color tool](docs/color-tool.md), [Asks and answers](docs/asks-and-answers.md), [For you and Closed](docs/for-you-and-closed.md), [Drafts, steps and Next](docs/next-and-steps.md)
- Items and waits: [Item model](docs/item-model.md), [Doing and waiting](docs/waiting-and-doing.md), [Hand-offs](docs/handoffs.md), [Minute runner and filing passes](docs/server-passes.md), [Silence, stall and ladder](docs/stall-and-ladder.md)
- Hooks and audit: [Page rule and hooks](docs/page-rule-and-hooks.md), [Daily audit](docs/audit.md)
- Machines and clients: [Puller and inbox](docs/puller-and-inbox.md), [Machines and sessions](docs/machines-and-sessions.md), [Client contract](docs/client-contract.md), [Fleet tool](docs/fleet-tool.md), [Read-only standby](docs/read-only-standby.md), [Session reload](docs/session-reload.md)
- Integrations: [anchor-hub and the router](docs/router.md), [GitHub mirror](docs/github-mirror.md), [Projects](docs/projects.md), [Second brains](docs/second-brains.md)
- Board alone: [Guide](docs/board-alone-guide.md), [Guide for an AI assistant](docs/board-alone-guide-for-ai.md)

## Contributing

How a change is made, tested and released is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

stackshot is released under the MIT License. See [LICENSE](LICENSE).
