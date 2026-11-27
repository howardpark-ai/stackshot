# The page rule, the client hooks and the board check

What this page covers: the page debt a state-changing write records, the four hook verbs on each machine, and the board check at the end of a turn. Back to the [README](../README.md).

**The page rule and the client hooks.** Every item names a project page (`projects/<slug>` or `infra/<slug>`) in a
directory of markdown files with frontmatter. A state-changing write (a create, a complete, or an update of
description, next, needs, status or due) records a debt against the writing session. The debt settles by itself once
the page is newer than the write. No board write is refused or held for a debt: a session that has owed a page longer than
`[page_rule] grace_minutes` has its next state-changing write go through, and the reply carries one line that names the page and
says it is still owed until its Current state is edited and, where pages are written through gbrain, the server has seen that
edit (`_owing_note` in `stackshot/web/page_debts.py`). The debt itself stays: it is still in the ledger, in the
brief and in pages owed, and the audit's page call and the reminders work as before. The check reads a local copy of the pages (a git read, never a call to the notes store). A copy that a timer pulls only every few minutes lags an edit by that long, so when the copy leaves a debt open the server also fetches the checked-out branch's upstream into a ref of its own, `refs/stackshot/page-upstream`, and reads the fetched commit (`stackshot/projects/page_upstream.py`): an edit that has reached the remote can settle the debt before the copy is pulled. Nothing else in the copy moves (no working tree, branch, remote-tracking ref or `FETCH_HEAD`), and there is nothing to set up: the fetch uses the upstream git already has, as the account the server runs as. At most one fetch a copy is begun every 20 s and it is ended after 30 s; after a failed fetch the time to the next doubles with each failure in a row, up to 5 minutes, and a lock file on that ref older than 5 minutes, which a fetch ended outright can leave, is removed. A fetch begun before an edit reached the remote does not hold it, and the next one begins no sooner than 20 s after that fetch began (longer while fetches fail), so a read until then still says the page is owed. A board write never waits for a fetch: the one it begins is read by a later reply. A client box's `nag` sends the time it needs the edit by (`page-ts?key=<page>&since=<epoch>`), and only that read waits for the fetch, 3 s at most from its start. With no upstream, a remote that cannot be reached or a read-only standby, the debt settles when the copy has caught up; the first of a row of failed fetches is said on the server's stderr. A read of the repository that fails or takes too long settles nothing, in the copy and in the fetched commit alike: the debt stays, and after a read of the fetched commit fails it is not read again for 30 s (so a repository that keeps failing costs one read, not four for every debtor at every settle). A ledger that cannot be read (a write cut short) is never written over: it is moved aside as `ledger.json.unreadable-<time>` in the state folder, the server's stderr says so once, and the debts that can be read from it are kept. A hook that runs on the server box itself reads the copy alone. On each machine, `stackshot/projects/pages.py` runs as four Claude Code hooks: `touch` (PostToolUse on
the connector's write tools) remembers the write, `nag` (UserPromptSubmit) reminds the session at every prompt while the
page is owed, `check` (Stop) runs the board check below, and `keeper` (SessionStart) shows a page's keeper the current
state of its pages. The Stop hook asks nothing about pages: the end-of-turn page question (`Page: no change, <reason>`)
was retired, and with it `[page_gate] mode` and `block_after`. The hook scripts live
in this repository under `client/hooks/`: `project-page.sh <verb>` forwards to `stackshot/projects/pages.py`, and `session-start.sh` prints
the board's brief and then the keeper's pages. `bin/stackshot client install` wires the four of them into
`~/.claude/settings.json`. A machine with no puller uses three more hook verbs of `stackshot/fleet/client.py`: `register`, `seen` and
`drain`.

**The board check at the end of a turn.** With `[board_check] mode = "block"`, `check` (Stop) also asks about the board.
A turn that did real work (a board or other connector write, a message to another session, or a shell command that
commits, pushes, opens or merges a PR, or runs `deploy.sh` or `release.sh`) while its session owns open items it neither
updated nor confirmed is asked once to update them, `confirm` them, or say there is no change. The answer can be in the
turn's own final message: `Board: no change, <reason>` covers every such item, `Board <id>: no change, <reason>` one
item, a bare `Board:` line followed by one bullet per item (`- <id>: no change, <reason>`) several, and the reason is at
least three words (the same line in the instance's own language, set under `[keywords.pages]` `board_label` and `no_change`, reads the same). Parked items are never asked
about. The hook gets the session's open items with one read of the client API (`items?key=<session>`), only on a turn
that wrote something; when the server does not answer, nothing is asked. With `mode = "note"` the same question does not
hold the turn: `check` keeps it in the session's state and `nag` says it at the next prompt as one line (`Board question
unanswered last turn: <items>. Answer it in the reply.`), which saves the extra model request a block costs. The turn's
first write also gets the question early, as hook context, so the reply can carry the lines; a call made inside a subagent
(its hook input carries `agent_id`) is never asked, since the open items are the calling session's (in-process
teammates carry `agent_id` too and are skipped alike). The note kept for the next prompt is that one line only when the
full question really went out that turn as hook context (the session's state keeps a separate `early_asked` mark for
it, set only when text was returned; a turn whose early call found no items, nothing due or no server answer leaves
none); otherwise the note is the full question. The page debt is said
at every prompt while it is owed, whatever the board check's mode: in full the first time, and after that, while the same
change stands and the full text is under 2 hours old, as one line `still owed: <page> (<item>, <HH:MM>)`.
