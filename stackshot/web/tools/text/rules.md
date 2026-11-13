## description rules
{{OWNER}}'s standing rules — the rulebook every Claude Code session on the owner's machines loads through CLAUDE.md
({{RULES_NAME}}, git-synced). A session that did not load it at start (cloud, Cowork) calls this once at the start of
a task and follows it; a session that has it does not. profile="cowork" (default) = the Cowork view: CLI-only sections
replaced by their Cowork equivalents, incident notes stripped; profile="full" = the whole file. The rulebook parts
named in config (skill files that CLI sessions load through hooks) are appended after the rulebook, each under "##
Part: <name>".

## description rules_resource
{{OWNER}}'s standing rules ({{RULES_NAME}}, git-synced), with the rulebook parts named in config appended

## description bump_versions
Refresh the latest-available versions (npm claude-code, gbrain releases) and republish the board now. Installed
versions come from each machine's heartbeat (the fleet tool pushes it before calling this after a CLI update). `host`
is accepted and ignored.
