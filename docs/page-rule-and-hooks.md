# The page rule, the client hooks and the board check

What this page covers: the page debt a state-changing write records, the four hook verbs on each machine, and the board check at the end of a turn. Back to the [README](../README.md).

**The page rule and the client hooks.** Every item names a project page (`projects/<slug>` or `infra/<slug>`) in a
directory of markdown files with frontmatter. A state-changing write (a create, a complete, or an update of
description, next, needs, status or due) records a debt against the writing session. The debt settles by itself once
the page is newer than the write. On each machine, `pages.py` runs as four Claude Code hooks: `touch` (PostToolUse on
the connector's write tools) remembers the write, `nag` (UserPromptSubmit) reminds the session at every prompt while the
page is owed, `check` (Stop) runs the board check below, and `keeper` (SessionStart) shows a page's keeper the current
state of its pages. The Stop hook asks nothing about pages: the end-of-turn page question (`Page: no change, <reason>`)
was retired, and with it `[page_gate] mode` and `block_after`. The hook scripts live
in this repository under `client/hooks/`: `project-page.sh <verb>` forwards to `pages.py`, and `session-start.sh` prints
the board's brief and then the keeper's pages. `./stackshot client install` wires the four of them into
`~/.claude/settings.json`. A machine with no puller uses three more hook verbs of `client.py`: `register`, `seen` and
`drain`.

**The board check at the end of a turn.** With `[board_check] mode = "block"`, `check` (Stop) also asks about the board.
A turn that did real work (a board or other connector write, a message to another session, or a shell command that
commits, pushes, opens or merges a PR, or runs `deploy.sh` or `release.sh`) while its session owns open items it neither
updated nor confirmed is asked once to update them, `confirm` them, or say there is no change. The answer can be in the
turn's own final message: `Board: no change, <reason>` covers every such item, `Board <id>: no change, <reason>` one
item, a bare `Board:` line followed by one bullet per item (`- <id>: no change, <reason>`) several, and the reason is at
least three words (the same line in the instance's own language, set under `[keywords.pages]` `board_label` and `no_change`, reads the same). Items on hold are never asked
about. The hook gets the session's open items with one read of the client API (`items?key=<session>`), only on a turn
that wrote something; when the server does not answer, nothing is asked. With `mode = "note"` the same question does not
hold the turn: `check` keeps it in the session's state and `nag` says it at the next prompt, which saves the extra model
request a block costs. The page debt is said at every prompt while it is owed, whatever the board check's mode.
