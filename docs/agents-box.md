# The agents' box over ssh

What this page covers: running the server on another box than the agents' sessions: the one optional `[agents_box]` setting, what the server then runs and reads on the agents' box over ssh, how a box that does not answer is handled, how the audit learns an agent is busy or idle without reading that box, and what is not routed.

By default the server and the agents (the Claude Code panes and the fleet tool that runs them) share one box, and everything the server asks of the agents' side is a local command or a local file. With `[agents_box] ssh = "<host>"` the server may run on a different box: the commands it runs on the agents' side and the files it reads there go through one small module, `stackshot/core/agentbox.py`, over ssh. With the setting unset (the default) the module does nothing: every command and file is local and nothing changes on a single box. The agents' own box ignores the setting when it names that machine (a configuration file read by both boxes: its own name or short name, `localhost`, or a name or address that resolves to a loopback one such as `127.0.0.1`), and the puller never uses it.

## The settings

All keys are in `[agents_box]` of the server's config file. Every one except `ssh` is optional and read at use (a reload applies it).

| Key | Default | Meaning |
|---|---|---|
| `ssh` | unset | The agents' box as ssh takes it: a name, an alias of `~/.ssh/config`, `user@host`, or a host word, `host:<role>`, which the `[hosts]` lookup turns into one of these ([Host words](configuration.md#host-words-naming-a-machine-by-its-role); a word it cannot resolve is tried as written and fails visibly). Unset = one box, and so is a value that names this machine (its own name or short name, a loopback name or address): it is read as local. The server's user needs a key that logs in there with no prompt. |
| `ssh_options` | `[]` | Extra ssh arguments, one word each (`["-i", "~/.ssh/key", "-p", "2222"]`). They come after ours, so none of them can turn BatchMode off. |
| `connect_timeout` | `5` | Seconds ssh waits to connect. |
| `timeout` | `20` | Seconds one call (a copy of files, a lookup, a transcript read) may take. |
| `cache_seconds` | `5` | How long a copy of the box's files, and a lookup of transcripts, is trusted before the box is asked again. |
| `retry_seconds` | `15` | After a call failed to connect, the box is not asked again, for any file or lookup, for this long; readers keep the last copy meanwhile. Then one call goes through for everyone. |
| `stale_seconds` | `120` | How long the last copy of the pane registry, the prompt stamps and the lane record stands in for a box that no longer answers; then those files read as absent, as if they were not there (unknown, never "gone"). The session registry, the session links and the lane-names file are not dropped: see below. |
| `registry_max_age` | `86400` | The oldest copy of the session registry and links the `said` check goes by (a day); an older one, or none, and the write is refused with the reason. |
| `max_file_bytes` | `8388608` | A file larger than this is left out of a copy (and logged). |
| `path_prepend` | `"~/.local/bin"` | Added in front of `PATH` for a command run over ssh (a non-interactive shell has no `~/.local/bin`); `~` is the agents' box's home. |
| `prompts_dir` | `"~/.local/state/stackshot/prompts"` | Where the prompt hook on the agents' box writes its stamps. |
| `mirror_dir` | `<paths.state>/agentbox` | Where the copies of the box's files are kept on the server's box (folders mode 0700, files 0600). |

A path the server's configuration names under the server's own home (`[client] session_links = "~/.local/state/…"`) is read under the agents' box's home: `~` there means the agents' box.

## What runs on the agents' box

Every command goes through `agentbox.argv(cmd)`: `ssh -T -o BatchMode=yes -o ConnectTimeout=… -- <host> sh -c '<script>'`, where every word of the command is shell-quoted, and anything with user text (a model call's message, the text of a Slack post) goes on standard input. So does the request of the box's own small program (the paths, the words a transcript line must hold, a message id): the remote command line holds the program's name and nothing of what a user wrote. No pty, never an interactive prompt; the command also runs under `timeout` on the box, so giving up here ends it there. An ssh that cannot connect exits 255, which the callers read as "the box did not answer": a plain reason is logged, the call is treated as a call that could not start, and the box is counted as down for `retry_seconds`.

- The fleet tool's session list (`sessions --json`, which gives the roles their `live` field).
- The router's model calls, which are also the audit's, the page-debt call's and every other thin call (`[router] command`, on `[audit] lane` when one is set): run in an empty temporary directory made on the box and removed there.
- `[for_you] slack_command`: the command runs on the box with the text on its standard input.

Not run by the server, so not routed: `[fleet] recycle_when_idle` and `notice_cmd` are text the sessions are told to run (and what the release script runs), and `[anchor_hub] direct_answer` is a line added to a notice for the session to run. They run on the agents' box because the session that runs them is there.

## What is read on the agents' box

A directory the server read is read from a local copy instead: one ssh call (a small program on the box that globs, reads and returns the files) refreshes everything one reader needs at most every `cache_seconds`, files whose time and size did not change are not rewritten, and every file is moved into place whole. The reader's code is the code it was.

- The fleet tool's store, `[client] session_links`: `<letter>/sessions.json` (the links) and `<letter>/session-registry.json` (the permanent ids), one call for both.
- The lane record, `[client] lanes_file`, with `lane-default` beside it, and the lane-names file (`STACKSHOT_LANE_NAMES`, else its default path).
- The CLI's own registry of live panes, `~/.claude/sessions/*.json`. The box drops the rows whose process is gone before it sends them, so a copy holds live panes only (as of the last copy). This feeds the pane's status and idle time and the hand-off checks. The audit's reading of an agent as busy or idle is not from it: see *The audit's agent state* below.
- The prompt stamps, `[agents_box] prompts_dir`, which the presence check reads.

Transcripts are too large to copy. The `said` check (`[said] transcripts`, `<root>/*/<session id>.jsonl`) finds the transcript on the agents' box and has the box return only the lines that can matter; the check on those lines is the same. A session that has no transcript on the box is stored unchecked, as a session whose transcript the server cannot see always was. A box that does not answer is not "no transcript": the write is refused with the reason (and the reason is logged), never stored unchecked without a word. The same holds when the session is given by name and the copy of the session registry that resolves it is missing or older than `registry_max_age`: the write is refused, not stored unchecked. The same lookup answers whether a transcript id was ever a session before a message to it is refused.

No ssh call is made while a write of an item holds the item lock: a slow or silent box would otherwise hold up every write of every item for as long as the call takes. The `said` lookups (the copy of the session registry and the transcripts) are made first, before the lock is taken (`update.said_preread`, which runs the gate once without effect and keeps the answers for that write); the gate under the lock reads only those answers and the copy already held, and a lookup the write did not make beforehand is a refusal with the plain reason ("send the call again"), never an ssh call. A box that does not answer therefore costs the one write that needed it, not the board. A copy of the registry that left a file out for being larger than `max_file_bytes` is no whole registry: the `said` check refuses on it, naming the file, rather than resolve a name from the rest. An empty answer to a transcript lookup (a session the box has no file for) is kept for `cache_seconds` like any other.

## A box that does not answer

Every call has a time limit. The first call that cannot connect (ssh's exit 255, a timeout) marks the box as down for the whole mirror, not for one folder: for `retry_seconds` every other read and lookup is answered from what is held, at once, without waiting for a timeout of its own, and then one call (the probe) goes through for all of them. The log says it in one line when the box goes down (`agents box: …`) and one when it answers again, not one per folder; a script that failed or a file that was left out is logged separately, at most once a minute for the same text, and does not count as down.

What a reader gets while the box is silent depends on what the copy is for:

- Pane liveness (the CLI's registry of live panes) and the prompt stamps are served from the last copy for `stale_seconds`; after that they are dropped and read as absent. Absent reads as unknown there (no pane row, no stamp: nothing can be told, and the checks that need a pane wait or fall back to the rules that need none), never as a pane that is gone.
- The session registry, the session links and the lane-names file are kept: they are served from the last good copy however long the box is silent (flagged once in the log as served stale), so a session name keeps resolving. A check that must not go by an old one refuses instead: the `said` check refuses a write when the registry copy was never made (the box has not answered since the server started) or is older than `registry_max_age` (24 hours), saying why, and never stores the quote unchecked; a name the copy does not hold, asked while the box does not answer (or while a copy is being made and its outcome is not yet known: the check waits for it), is refused too, with the plain line that the box could not be reached and to send the call again. The lane record is not kept: it is a copy that stands for `stale_seconds` and is then dropped, so the lane check says it cannot be made rather than answer from an old record.
- Commands that cannot start report that: a model call is a call that did not start and is retried by its caller, a Slack post counts as not posted and is tried again.

## The audit's agent state

The hourly audit, the idle hand-over and the guard that refuses a park on an item being moved need to know whether the mover is at work: its pane in a turn, or a subagent running. The server does not read that from its own
box, whichever box the agents are on: no pane registry, no transcript, no ssh and no copy of a transcript. The machine that runs the panes tells it. About every five minutes the fleet's session manager pushes the whole fleet in
one body, `POST /client/agent-state` with the machine token of every `/client` write ([the client contract](client-contract.md#the-agent-state-the-fleets-session-manager-pushes)), and the server keeps the last one in
`<paths.state>/agent-state.json`. The server keeps one snapshot, each push replaces all of it, so every sender for a fleet pushes the whole fleet and an agent absent from it reads unknown (fail closed); a push older than the stored one is ignored (a stored snapshot more than five minutes ahead of the server's clock never makes a push count as older; one 0 to 5 minutes ahead does, until the true time reaches it). A `written` of zero or less is refused with 400. When more than one sender pushes, the last accepted push replaces the whole snapshot, so one sender should cover the whole fleet. The audit asks that snapshot for a registered agent's state (`stackshot/audit/agent_state.py`): `busy`, `idle` or `unknown`.

It is unknown, never idle, whenever the snapshot cannot say: none was ever pushed, the file does not read, the newest is older than 15 minutes (`agent_state.MAX_AGE_S`: three pushes missed), the agent is not in it, its entry
was not read (`read` false) or its state is unknown. An unknown mover gets the audit's unknown line (`audit_unknown`): nothing is flagged and nothing is handed on. So an agent on another box than the server reads right as soon
as the manager there pushes, and reads unknown, never idle, while it does not. Nothing here is a setting: the server needs no name of the agents' box for it and `[agents_box]` is not read for it. The same snapshot is what lets the audit hand an idle front agent's own open step to a free background agent of its project, and, where none is free, start the front agent's own turn ([the ladder page](stall-and-ladder.md)): only a fresh, read `idle` (for a background agent to take an item, or a front agent to be started) counts, and the prompt stamps it checks for the owner's presence are the ones copied from this box (`prompts_dir` above); a stamp folder it cannot read starts nothing.

## Not routed

These still read the server's own box and, with the setting on, find nothing there; each treats that as it treats a session it cannot see:

- `service/pane_recovery.py` (a transcript's last error): it reads such a pane as unknown, and the puller on the agents' box already reports `stopped` for its own panes. The audit's subagent reading is no longer one of these: it reads no pane and no transcript of its own, only the snapshot and the sessions index's name of an agent (next section).
- `fleet/push.py` (a pane's socket and the cloud send) and the `stackshot` command line, which keep to the box they run on.
- `tools/rulebook_scan.py` and `fleet/connectors.py`, which read the rule files, skills and the CLI's configuration of the box they run on.
- `projects/pages.py`, whose `session_name` fallback reads the live fleet store under the server's own fleet folder and the CLI's registry (`~/.claude/sessions/*.json`) of the box it runs on: with the setting on and nothing there it gives no name, as for a session it cannot see.
