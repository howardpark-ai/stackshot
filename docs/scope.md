# Scope

What this page covers: which ways of running stackshot are supported (one person, one server) and which are out of scope. Back to the [README](../README.md).

There are four ways one could imagine running stackshot:

1. One person, one server, one box: the person's own machine, physical or virtual.
2. One server per person on a box that several people share, each person running their own instance under their own account.
3. Several people served by one server process.
4. Several such multi-person servers on one box.

The first is what stackshot is built for and supported for.

The second comes with it by construction. Each person clones the code and runs `./stackshot setup` as themselves, with
`--port` set to a port of their own when the box already has an instance on the default one. Everything an instance owns
then lives under that account: the config in `~/.config/stackshot`, the state in `~/.local/state/stackshot`, the secrets
and machine tokens, the data repository, the Claude Code hooks in `~/.claude/settings.json`, and the systemd user units,
which run in that person's own user manager on their loopback port, behind their own HTTPS hostname. No instance knows
that another exists, and none needs root beyond the one-time `loginctl enable-linger` where the account may not switch
lingering on for itself. Setup refuses a port another account already listens on, and `doctor` says when the port its
config names belongs to someone else, rather than taking that person's server for its own. Every unit is a user unit
(the system scope under `/etc/systemd/system`, of which a box has one, was removed in an earlier change), so nothing an instance
installs is shared with another account. The same goes for anchor-hub's `[anchor_hub] hook_port`, which each person who
enables anchor-hub on a shared box also sets to a port of their own.

This is proven once rather than assumed. `tests/two-users.sh` runs as root in a fresh Ubuntu 24.04 container, creates two
ordinary users without sudo, installs an instance for each as that user, and checks that both servers answer on their own
ports as their own Linux users, that each user's puller and client talk only to that user's server (a token from one is
refused by the other), that `doctor` passes for each, that each user's hooks landed in their own settings, and that
nothing was written outside the two homes. After a restart of the container with nobody logged in, it checks that both
instances came back on their own. The top of the script has the exact commands; it is not part of CI, because it needs
systemd, a container and the network.

The third and fourth are out of scope. Everything in stackshot is keyed to one person: the sign-in allow-list, the items
owned by that person's sessions, their page store, anchor-hub holding their Slack, Notion, Drive, Gmail and GitHub
credentials, the publisher committing as them, and the Machines panel listing their machines. Serving several people from
one process would mean tenancy in the data model, credentials per person for every receiver, an authorization check on
every tool call and an admin surface to manage it all. That is a different product, not a setting of this one. And for
software that holds each person's mail and chat tokens, one isolated instance per person (the second setup, in containers
when there are many people) is the safer way to serve many people anyway.
