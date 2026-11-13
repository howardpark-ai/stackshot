## description sessions
{{OWNER}}'s Claude sessions and machines, from the live fleet state on the server box — for a session that cannot read
it itself (on another machine, in the cloud, in Cowork). Each session: its name, its link (for a pane, the URL the
fleet tool's store gives it, where one is configured; for a cloud or Cowork session, its claude.ai link; link a
session by it; empty = no link, name it plainly), its machine, and its role where a project page names it (front agent
or background agent of <project>; a front agent takes a message only with {{FOR_OWNER}} on its first line). Each
machine: online or offline, its Claude Code CLI version, and on the box that runs it the {{OPERATOR}} (the session a
recycle or CLI-update cue goes to — from a cloud or Cowork session, relay the cue with message(to=<that name>)), live
or not running. Cloud and Cowork sessions are listed when they own an open board item. name: optional case-insensitive
filter on session names.
