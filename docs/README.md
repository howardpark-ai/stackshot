# stackshot docs

These pages hold the detail behind the [README](../README.md). Each page starts with one line that says what it covers.

## Start here

- [What stackshot is and how it fits together](overview.md): What stackshot is, how one board write flows through the server, the hooks and the page debt, and what a typical deployment looks like.
- [Scope](scope.md): Which ways of running stackshot are supported (one person, one server) and which are out of scope.
- [Install](install.md): The three install commands in one place, with a pointer to the full walk-through.
- [The Windows client](windows.md): How a Windows machine runs Claude Code as a client: the token, the puller and the hooks.
- [Development](development.md): How a change is made, tested and released, what running sessions need after a release, and how to run a local server.

## Configuration

- [Configuration](configuration.md): The config file, where it is read from, and the keys for the instance, paths, pages, subjects, descriptions, the page rule, the audit, asks, publishing, the GitHub mirror and the scopes.
- [Configuration: project agents, runners, anchor-hub, router, auth and client](configuration-integrations.md): The config keys for project agents, steps, runners, the item model, the Machines panel, gbrain and second brains, anchor-hub, the pilot and router, the For you list, the portal, sign-in and the client.
- [Configuration: keywords for another language](configuration-keywords.md): The `keywords.*` keys that let an instance in another language list its own words, and how a words list is read.

## The board and its tools

- [The board, the publisher and the connector](board-and-connector.md): The server and the publisher, the MCP connector, and every tool the connector offers.
- [The board pages](board-ui.md): How the board pages are drawn: search, the item page, the home lists, rows, cards, buttons, the side panel and the CI runners page.
- [The color tool](color-tool.md): The Colors button that tries a whole dark color combination, and the saved color combinations.
- [Asks and answers on the board](asks-and-answers.md): The board sign-in, how a wrong ask leaves the owner, how the owner answers from an item page, the answer box and the History after a decision.
- [The For you list and the Closed page](for-you-and-closed.md): The list of notices for the owner, Watch and Mute, the Slack post for an urgent row, the machine-token routes of the web form, and the Landed list that is now the Closed page.
- [Drafts, steps and the Next checklist](next-and-steps.md): The draft of a text the owner will send, the one-line step, the Next checklist and its write checks, step proofs and the hand-over of a finished step.

## Items, waits and the server passes

- [The item model and the stored state](item-model.md): The alive and waiting model, the stored phase, retired inputs, the state checks, watchers, fleet-event waits, how a close keeps the description, and the mover that holds every power.
- [Doing, waiting and the clock](waiting-and-doing.md): What doing means, a doing item that only waits for a later day, the goal an item opens with, no clock renewal without progress, on agent versus park, and the blocker a self-set wait must name.
- [Hand-offs, the done check and front agents](handoffs.md): What a front agent may watch, the done check that closes an item when its proof is met, the shared PR-state reader, and when a front agent hears of its item.
- [The minute runner and the filing passes](server-passes.md): The minute set runner, the filing and dates pass, the front-step rule and its write check, the four facts the server files itself, and the wait-end rule.
- [The audit lines, the stall pass and the ladder](stall-and-ladder.md): The readings the audit passes share, the hourly audit line and the idle hand-over, the stall pass, the one ladder of nudges, and how the hand-off record follows the mover.

## Hooks and the audit

- [The page rule, the client hooks and the board check](page-rule-and-hooks.md): The page debt a state-changing write records, the four hook verbs on each machine, and the board check at the end of a turn.
- [The board audits](audit.md): The audits in script and agent mode, the three paces they run at, the Audits page, its checks (page agent lines, project registry, off-map sessions, board checks), the weekly refusal count and how findings reach their mover.

## Machines and clients

- [The puller and the inbox](puller-and-inbox.md): How notices and messages reach a session on another machine, how a client box keeps itself current, and how the machine card is judged.
- [Session links and the Machines panel](machines-and-sessions.md): How the board links to a session, and what the Machines panel shows for each machine and package.
- [The client contract](client-contract.md): What a machine needs from stackshot, setup-run reports, permanent session ids, filing a question and reading the answer, the client item and For you routes, a pane waiting in its terminal, and a gap in a scheduled job.
- [The fleet tool](fleet-tool.md): The points of contact between stackshot and an optional fleet tool: session links, lanes, recycles, spawns, reboots, CLI updates and naming.
- [A read-only standby copy](read-only-standby.md): How a warm second instance runs from a copy of the data and never writes, with one switch for takeover.
- [What a running session reloads](session-reload.md): Which files a release changes reach a running session on its next call, and which only at its start.

## Integrations, projects and brains

- [anchor-hub, the router and the page-debt call](router.md): The receivers that watch external things, the router that rules every notice, the page-debt call, and how a notice is held or answered.
- [The GitHub mirror](github-mirror.md): Mirroring items to GitHub issues, the write and read budgets, temporary ids, the inbound comment reader and anchor-hub conditional reads.
- [Projects: the record first](projects.md): How a project is defined by its record, the project verbs and the table of commands, archived projects, and an item's contact.
- [Second brains](second-brains.md): Projects whose pages live in a second notes brain: routing of new pages, reads and writes, failing open, secrets and thin clients.

## Installing the board alone

- [Installing stackshot as your own board](board-alone-guide.md): A guide for a technical reader who has never seen stackshot.
- [Installing stackshot (board alone), for an AI agent](board-alone-guide-for-ai.md): The same procedure, written for a Claude Code agent on the user's box.

The full install walk-through is [INSTALL.md](../INSTALL.md). How a change is made and released is in [CONTRIBUTING.md](../CONTRIBUTING.md).
