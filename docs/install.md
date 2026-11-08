# Install

What this page covers: the three install commands in one place, with a pointer to the full walk-through. Back to the [README](../README.md).

[INSTALL.md](../INSTALL.md) walks a second person from an empty Linux box to the first item, with three commands as the steps:
`./stackshot setup` writes the config, the data repository, the secrets and the units; `./stackshot doctor` checks the instance and starts the server once the Google OAuth client is filled in; `./stackshot client install` adds the Claude Code hooks (on another machine it also stores the machine's token and starts its puller). `doctor` counts a page hook as present when it is in `~/.claude/settings.json` or in the `hooks/hooks.json` of the enabled stackshot Claude Code plugin (`stackshot@<marketplace>` in `enabledPlugins`, found through `~/.claude/plugins/installed_plugins.json`); a plugin that is installed but disabled does not count.
Between them come the Google OAuth client, the HTTPS front and the claude.ai connector; the Windows client is described in [docs/windows.md](windows.md).
