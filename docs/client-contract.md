# The client contract

What this page covers: what a machine needs from stackshot, setup-run reports, permanent session ids, filing a question and reading the answer, the client item and For you routes, a pane waiting in its terminal, the agent state the fleet's session manager pushes (the route and what it keeps), a gap in a scheduled job, a hook's catch of a turn that signed off with no question, a failed run of a scheduled job, an item a script opens for a background agent, an item a script keeps in step with a condition, the anchors a hook adds for a pull request or an issue, a caller's own key, and pushing the agent state with the script client (the `post agent-state` verb). Back to the [README](../README.md).

A machine where Claude Code runs needs three things from stackshot, and no copy of the config:

- **A machine token.** `bin/stackshot client mint <machine>` on the server box writes it to
  `<secrets>/client-tokens/<machine>.token`; the server keeps only its hash. On the machine,
  `bin/stackshot client install --url <base URL> --token-file <file>` stores it at `~/.config/stackshot/client.token`,
  beside `client.url` (one line, the server's address).
- **The puller.** One `stackshot/fleet/puller.py` per machine: a user unit on Linux (`install.sh puller` renders
  `stackshot-puller.service`, and `client install` installs and starts it), a scheduled task on Windows. It delivers
  notices and messages and reports the machine's sessions and liveness. From puller 8 it reloads itself when the
  `VERSION` in its checkout's `stackshot/fleet/puller.py` differs from the one it loaded (see docs/windows.md), so a checkout update needs
  no hand restart.
- **The hooks.** The four scripts in `client/hooks/`, wired into `~/.claude/settings.json` by `bin/stackshot client install`
  (SessionStart, UserPromptSubmit, Stop, and PostToolUse on the connector's `create`, `update` and `complete`).

The connector itself is per account, added once on claude.ai. See [INSTALL.md steps 6 and 7](../INSTALL.md#6-claude-code-on-the-server-box)
for the server box and for another machine.

## Reporting a setup run

A machine that provisions itself (a Windows PC at logon and daily) reports how each run ended, so a failed step shows
on that machine's column of the board's Machines panel. The provisioning script calls, with the machine's own token:

```
stackshot/fleet/client.py setup-result --ok
stackshot/fleet/client.py setup-result --failed --step "<step name>" [--reason "<short text>"]
```

It prints one line and exits 0 when the server recorded the result, 1 when it was refused or not reached (the script
decides what that means for its run; nothing is retried). Underneath it is one authenticated write:

- `POST /client/setup-result`, `Authorization: Bearer <machine token>`, body
  `{"ok": true}` or `{"ok": false, "step": "<step name>", "reason": "<short text>"}`.
- `ok` is a JSON boolean. A failed run must name its `step` (400 otherwise; an ok run keeps none); `reason` is optional. Whitespace is
  collapsed; `step` keeps 120 characters, `reason` 500.
- The machine is the token's, never the body's. The server stamps the time it received the result and keeps the latest
  one per machine, replacing the one before: `{"at": "<UTC ISO>", "ok", "step", "reason"}`, answered back as
  `{"machine": "<machine>", "setup": {…}}`.

On the board, a failed last run is a card at the foot of the machine's column: **setup · failed ✗**, then the step's
name; the reason and the time are in its tooltip. A good run shows nothing on the card. The next result replaces the last, so a fixed step clears the card at the next run.

**Update attempts.** The poll's machine facts (`POST /client/poll`, `facts`) may carry `updates`, a list of
`{"what", "from", "to", "ok", "at", "reason"}` (`at`: an ISO time or an epoch), for the helper's own updates and the
CLI's. The server keeps the last list a poll sent (at most 20 entries; a poll without the key leaves it as it was). When
the latest attempt listed for a `what` has `"ok": false`, the machine's column shows **update · failed ✗**, then the
`what` and the version it tried; the reason and the time are in the tooltip, the same way. An attempt without a boolean
`ok` counts as neither. The exception is the box's own checkout (`what` = `stackshot checkout`): when the machine's view holds its
reported commit (`stackshot`) and it is the server's commit, the failed attempt is not drawn (the box is where it should be).

## Permanent session ids

The fleet tool gives every session an id that never changes (the permanent id, a UUID) and publishes `<letter>/session-registry.json` in the directory
`client.session_links` names. With that file, `stackshot/fleet/sessions_registry.py` turns any reference to a session (a permanent id, a name, an alias, a
Claude transcript id) into one permanent id, or into nothing when it cannot tell (a name two sessions carry, an id it does not list: it never
picks). An open item stores its creator (`metadata.owner`), its needs entries and its observers as the permanent id where it resolves, and everything people read
(`get`, `brief`, the board, the item page, the GitHub mirror, the client API) shows the session's current name, so a rename or a fresh start
changes nothing stored. Where a session is compared (needs gates, mover checks, who sent a write) the two sides are compared as permanent ids
when both resolve, and by the old rule otherwise. A message, a notice or an inbox line addressed to a permanent id goes to the session by the name
it has now, and the inbox line keeps the permanent id it was put for, so a poll finds the session whatever name or transcript it carries when it asks. Without the file (missing, unreadable, another schema) nothing changes from before. `roles.json` keeps its name keys and gains an
`ids` map (name → permanent id). Each entry also carries `live` (additive): whether `sala sessions --json` lists the name as a session, or as an alias of one (a session keeps the names it had before a rename); the server reads sala once per build with a 4-second limit, and leaves the field out of every entry when sala cannot be read (no `[client] session_links` store, an error, a slow read). A name-line (`keeper`) entry is `retired: true` when its page has user-facing agents or its own `status` is a finished one, and a name held by several pages takes an unfinished page over a finished one. Every tool that takes a session (`sender`, `owner`, `needs`, `observers`, `to`) accepts a permanent id.

The one-time move of what is already stored: `python3 stackshot/fleet/session_ids.py migrate --dry-run` (read-only) says what it would change and what it
keeps (and why). The command never writes an item. `migrate --request` writes `<state>/session-ids-migrate.request`, and the server applies
the move at its next start, before it starts any writer thread or serves a request (so nothing else writes an item meanwhile). The request is consumed
even when the registry is unreadable at that start (nothing is done): fix the registry and request again. It rewrites the creator (`metadata.owner`), needs and
observers of open items only (a closed item is a record of its time and is never touched), and writes
`<state>/session-ids-undo-<UTC time>.json` (gid, field, old, new) before it changes the first item. `python3 stackshot/fleet/session_ids.py rollback <undo file>`
asks the same way (the request names the undo file) and the server puts each field back where it still holds what the migration wrote. A
failure is logged and the start goes on. A second request changes nothing. `roles.json` is written by the server's own roles sync, and the
inbox hold lists belong to the fleet tool: neither is rewritten by the migration, and stackshot only reads the hold lists (a line may be a name, a
transcript id or a permanent id). The command is refused outside the production checkout without `$STACKSHOT_CONFIG`.

The board page leaves out an agent whose `live` flag in `roles.json` is false (sala lists no session of it), on a project page's Sessions section and on the index, where an agent that still owns an open item stays. A name `roles.json` does not know, and a file written while sala could not be read, hide nothing. The agents of a finished project (its page status is one of `[project_scopes] retired_statuses`) sit in a `finished` group that starts closed. The project picker's listing is unchanged.

## Filing a question and reading the answer

A script that hits a question only the owner can answer (a headless `claude -p` run, a watcher) files it as a board item and
reads the answer later, from a shell, with the machine's token:

```
echo "<the question, a few lines>" | stackshot/fleet/client.py post question --project <key|id|slug> --ask "Decide: … · Recommend: … · Stakes: … · By: …" \
    --subject "<subject>" --request-id <token> [--option "<label>=<line>" ...] [--recommended <label>] [--sender <script label>]
stackshot/fleet/client.py get answer board#<n>
```

`post question` prints the new item's id (`board#N`) and exits 0; a refusal, or a server it cannot reach, is one line on stderr and exit 1.
Underneath it is one authenticated write:

- `POST /client/question`, `Authorization: Bearer <machine token>`, body `{"project", "ask", "text", "subject", "request_id", "sender"?, "options"?}`
  (`options`: `[{"label", "line", "recommended"}]`). `project` is an id, a page key or a bare slug of a page in the registry (404
  unknown, 400 ambiguous). The item is open, `needs` = `decision`, with the ask and the options, filed under the project's page,
  and owned by the project's front agent, its `-main` agent first, else the first front agent by name (409 when the page and its hub
  list none).
- `text` becomes the description, one `- ` bullet per line (a marker it already carries is not doubled), each clipped to
  `[description] line_max` characters as it reads (at a word outside any link and any naked URL, with an ellipsis; a line that is empty after
  its marker is skipped: the create gate judges it like any create). More non-blank lines
  than `[description] max_lines` less one, or more than 8000 characters, is a 400 saying so, and the script shortens it. The
  description ends with the bullet `- Filed by <sender> (a script on <machine>)`, so the item page and the GitHub issue body show
  the owner who filed it. `sender` (default `stackshot/fleet/client.py`) is also kept in
  the item's `filed_by`; the machine is the token's.
- `subject` is required (400 without it, naming the instance's subject prefixes): there is no default prefix, since a question filed
  under the wrong one lands in the wrong place on the board; the create gate then checks the prefix as for the tool.
- `request_id` is required (400 without it; one line of at most 120 characters) and makes the write idempotent per `(machine, sender,
  request_id)`: the server keeps the item in its request map (`<state>/requests.json`, where a tool create's `request_id` lives), and
  the same triple again answers the same item (`"repeat": true`, the same id printed, exit 0) and files nothing. If that item has since
  been removed, the call files a new one. **the fleet tool passes one per parked question**, the same token each time that question is filed
  again, with the same `--sender`.
- It is the create tool's own code (`create_item` in `stackshot/service/create.py`): the subject prefix, the ask's form, the options (2 to 6, exactly
  one recommended), one question per ask (its answers are the options) with a design it approves linked in the ask, the project page, the GitHub mirror and the page-debt rules apply as to a session, and a
  refusal is the tool's text (400). A script owes no page, and the owner is charged none: the page debt goes to the page's keeper
  (a page's own agent that is not a front agent, else the hub's or the scope's general `-main` agent) to no one when the page has none, and to no one when the keeper is the owner itself, so a burst of
  questions cannot block the owner's own board writes. The owner is told nothing; it finds the item in its queue.
- `GET /client/answer?key=board#<n>` returns the owner's answer on the item as one line, `<kind>` TAB `<chosen option's label>` TAB
  `<text>` TAB `<when>`, or an empty body while he has not answered. It is his newest `decision` (he answered the item), even when he
  commented after it; only when he has decided nothing, his newest `comment`. **A caller resumes only on `decision`** and keeps waiting on
  a `comment`. The label is empty when he picked none; line breaks in the text are ` / `; `<when>` is when he gave it, an ISO time in the
  instance's timezone. The line does not say which question it answers: an item answered before the question was filed on it returns
  that answer, so a caller files a fresh item per question. Older letter-and-number ids work. Like `brief` and `items`, it is not scoped to a machine.
- Exit codes. `stackshot/fleet/client.py get answer` prints the line (nothing when empty) and exits 0, or exits 1 with the reason on stderr: no id
  given (usage; the server's own answer to an empty key is 400), an id that names no item or is not an item id (404), no token on the
  machine (401), or a server not reached (`[0]`). It never reads the project record, so it has no 503. `stackshot/fleet/client.py post question` exits 1
  on a refusal (400 the tool's checks, the missing subject or request id, a text over the limits; 404 no such project; 409 no front
  agent), on no token or a server not reached, and on 503 when the project record cannot be read right now (nothing was filed).
- `GET /client/items?key=<session>` returns `{"items": [{gid, shown, subject, needs, state and state_fields (only for an item that stores a state), next, state_updated, confirmed, updated, held, list, mover, expected_by, wait, overdue (these three are kept so that a reader written against them does not break and are always empty: `expected_by` null, `wait` "", `overdue` null; they go in a later release), step, roles, …}]}`:
  the open items the session moves, takes after the owner's answer or is named in (the board check's read). `list` is the home page's list the item is in, one of
  `"your-move"` (alive, the owner moves it), `"agents"` (alive, a session moves it) or `"waiting"` (waiting on a time, an anchor, another item or a relay), from `home.list_of` on the item
  model's reading. It is never empty: an item the page cannot place (a dead or unreadable one) is `"agents"`, as `home.classify` puts it, so the fleet tool's items sheet groups exactly as the page does.
- `GET /client/item-record?key=<item id>`, `GET /client/open-records?key=<session>` and `GET /client/anchors-record` (`stackshot/fleet/client.py get item-record <id>`, `get open-records <session>`, `get anchors-record`; `tests/client_scenario.py`) return the board's own files, parsed and nothing else done to them, for a hook on a box whose server runs elsewhere and so has no store of its own that stays current. `item-record` is `{"id": the store's id now, "shown": "board#N", "record": the item's file (subject, status, metadata with its steps, phase, mover and wait fields), "anchors": [the anchors that name the item]}`, an item open or closed; 400 a bad id, 404 an id that names no item, 503 when the item's file or the anchors file does not read. `open-records` is `{"session", "total", "truncated", "unreadable": [ids], "items": [<the item-record answer, each>]}` for the open items `items` lists for the same key, at most 300 and about 4 MB (`truncated` says when it left some out; `unreadable` names an item whose file stopped reading during the call, while a file already corrupt before it is skipped by the view and is in neither list), 400 a bad key. `anchors-record` is `{"anchors": {<project key>: [{url, items, added, by}]}, "truncated"}`, `{}` without a file, 503 when it does not read. The gate is the same machine-token gate as the other reads and is unchanged (401 without a token; no other credential opens them), but the reach is wider: any minted machine token can read the full stored record of any item, a closed one too, and the whole anchors map, since a token is scoped to no item and no machine. `puller-and-inbox.md` has the shapes in full.
- `GET /client/projects-record` (`stackshot/fleet/client.py get projects-record`; `tests/client_scenario.py`) returns the project record alone: exactly the value `GET /client/state-files` carries under `projects` (the published `projects.json`, one JSON object as the server holds it), for a caller that needs only that and not the other files `state-files` bundles with it. Both reads build it from the same function, so they cannot differ. 503 when the file is not there, does not read or is no object (never an empty stand-in). The gate is the machine-token gate of the other reads, unchanged (401 without a token; no other credential opens it), and the reach is no wider than `state-files` already has.
- `GET /client/for-you` returns `{"generated", "rows": [{id, kind, item, project, what, url, urgent, ts, when, slacked}], "flags": {"board#N": "watch" | "mute"}}`
  (rows newest first; an item with no flag is in neither).
- `GET /client/project-activity` (`client.py project-activity [--json]`; `stackshot/service/project_activity.py`; `tests/project_activity_scenario.py`) returns `{"projects": {"<project key>": {"anchor": <epoch|null>, "owner": <epoch|null>}}}` (no cache; reads only), for a script that decides whether a project is quiet.
  `anchor` is the whole second of the project's newest anchor notice from outside: a line of kind `anchor` in the project's routing log, delivered or held for the router. Not counted: a routine event on the fleet's own repository (filed `log_only`), a log-only direct anchor, the hub's own warning that an anchor cannot be read, and the board notices and messages (other kinds of line). The hub's receivers drop the owner's own posts (Slack, GitHub comments) and a bot's message on a Slack direct anchor before the log, but nothing else: a bot's comment or a CI notice on a watched pull request reaches it, and the log does not say who posted. So `anchor` can count a post no person made: it over-counts activity, the safe direction for a script deciding whether a project is quiet.
  `owner` is the whole second of the owner's newest input, the newer of two records: his board actions (an entry of an item's `metadata.answers`, any item open or closed, `via` board or github: an answer, a decision, a Done, a note, a comment; not `via` mail, which is the server settling a step on a mail he sent) and his front-chat messages (the stamp file `<state>/prompts/<session id>` written on each of his prompts, counted for the project of the session when it is a front agent; a background agent's or an unlisted session's stamp is not counted; the only session of a project with no `agents:` map counts as its front agent). The stamps are read only from this server's own state: a front agent whose pane runs on another machine leaves none here, so its chat is not seen. An audit, a router ruling, a notice and a message between agents are in neither record.
  A sub-page counts for the project that owns it; a time more than five minutes ahead of the clock is left out; a project with neither time has no row, so a project that is not listed has had neither. The client prints one line `<project key> <anchor|-> <owner|->` per row, or the object with `--json`, exit 1 with the reason on stderr (nothing on stdout) when the server cannot be asked or refuses, so a failure is never read as an empty answer. The server itself answers 503 with the reason, not a smaller answer, when it cannot read what it needs: the page registry (the sub-page mapping and the roles read it) when any time was found, or the roles or the stamp folder when stamps exist; a stamp folder that does not exist is no stamps.
- `GET /client/agent-name?key=<project>&names=<a,b,c>` (or one `name=`) tells whether `post project-agent` would take each name as a new agent of the project, and writes nothing: no sender, no lock,
  the same machine token as the other reads. `key` is an id, a page key or a bare slug; `names` is comma separated, each stripped, at most 20 and at least one (400 otherwise, with a plain line).
  200 `{"project": <the project's id>, "key": <its page key>, "results": [{"name", "valid", "code", "reason"}], "first_free", "prefixes"}`: one result per name in the order asked, `code` one of
  `ok`, `format` (the name's shape), `prefix` (it does not start with the project's name), `clash` (it belongs to another project, case-folded), `listed` (the project already lists it), `pending`
  (a pending entry holds it), `hub` (the page is a sub-page or has a `hub:` line), `hidden` (the project is not listed), `retired` (its page status is a retired one); `reason` is the text the register
  gives for it, and empty for `ok`. `hub`, `hidden` and `retired` are told for every name. `first_free` is the first name in the order asked that is valid, or null; `prefixes` are what the project's names
  must start with. The register is the final word: this read applies its checks one at a time and reserves nothing, so a caller registers the name it picked next. A name already listed is not valid here
  (the register changes nothing for it only when side and mandate match), and a name a pending entry holds is told held whoever asks. 404 an unknown project, 400 an ambiguous one, 401 no token,
  503 the project record cannot be read. `stackshot/fleet/client.py get agent-name <project> <name> [<name> ...]` prints the JSON and exits 0 whenever the call answers, even when every name is invalid.
- `POST /client/for-you/seen`, `Authorization: Bearer <machine token>`, body `{"id": <row id, a whole number from 1> | "all", "sender": "<label>"}`.
  200 `{"ok": true, "seen": [<ids that left the list>], "rows": [<the rows still unseen, as in GET /client/for-you>]}` (`"all"` on an empty list is 200 with
  `"seen": []`). 400 a body that is not an object, a `sender` that is not one line of at most 80 characters, or an `id` that is neither; 401 no or an unknown
  token; 403 the caller is not the web form (`sender` not in `form_senders`, or the token's machine not in `form_machines`; a `bg_senders` label is not the web form); 404 an id that is no row on the
  list (never made, or already seen).
- `POST /client/items/{key}/watch`, the same token, body `{"state": "watch" | "mute" | "default", "sender": "<label>"}`. `{key}` is an item as shown
  (`board%23N` in the path, or `N`) or its store id, read the way the other client routes read an id. 200 `{"ok": true, "item": "board#N", "state": "<the
  new state>", "flags": {<the whole map, as in GET /client/for-you>}}` (`default` removes the flag). 400 a bad `state` or `sender`; 401; 403 as above; 404 an unknown item.

## A pane waiting in its terminal

When a session's permission prompt cannot be answered by a hook (a question to the owner, a guarded file, plan mode), the pane waits in its terminal. The fleet tool (sala) tells stackshot,
so the owner has a row in Your move that links the pane, and the row goes when the pane stops waiting:

```
stackshot/fleet/client.py post terminal-prompt open  --session <name|id> --question "<one line>" --sender <label>     # prints the item id, exit 0
stackshot/fleet/client.py post terminal-prompt clear --session <name|id> --sender <label>                             # exit 0, also when nothing is open
```

Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/terminal-prompt`, `Authorization: Bearer <machine token>`, body
`{"action": "open" | "clear", "session", "sender", "question"?}` (200 `{item, session, project, repeat}` for open, `{session, cleared: [ids]}` for clear; 400 a check or a refusal; 409 no project with a front agent to file under).

- **One open item per session**, marked `metadata.terminal_prompt` = the session's name as the registry has it. The session is matched through the sala registry (`stackshot/fleet/sessions_registry.py`), so a name, an
  old name (an alias), a sala id and a transcript id reach one item. The item: subject `<session> is waiting for your answer in its terminal` (with the instance's prefix of the project's scope, else `[subject] fallback_prefix`, else its first prefix),
  priority p1, the owner the mover, state `your-step` with the step `Answer <session>'s question in its terminal` (one line, no command), and one next line, `<owner>: open <the pane's address> and answer: `<question>``.
  The address is `[client] session_view` with the name url-quoted, else no link: the pane is named in words ("the pane of <name>"). It is filed under the session's project (the registry row's `project_key`, else its `project`) when that
  project lists a front agent, else under `projects/example-two`; the project's `-main` agent is its creator and takes it after the owner (`then`, as `post question` files), the script is recorded as the creator (`<label> via a script on <machine>`).
- **The question** is one line of at most 200 characters (`--question`; 400 otherwise, and the client refuses it before sending). It stands in next as a code span, because the next guards read prose and the pane's
  words are no wait or step of the item's (a backtick in it becomes an apostrophe); a line over `[metadata.next] line_max` (the address does not count) has the question cut at a word with an ellipsis.
  The guard on alarming words does not judge it (the route sets what `post question` sets).
- **A second `open` for a session** that has an open item changes its next line and files nothing (`repeat: true`, the same id); the same question again writes nothing. After a `clear`, an `open` files a new item.
- **`clear`** closes the session's open item: outcome `done`, reason `the pane stopped waiting`, the end state in `outcome_text`, the description unchanged. None open is a no-op (200, `cleared: []`).
- **The row owes no page and tells no session.** It is a notification that opens and closes with the pane: the writes set `TERMINAL_ROW` (`stackshot/service/writes.py`), so no page debt is charged to the script, the mover or the page's keeper, the router
  gets no notice of it, and the close is told to no one (the `tell_*` notices return nothing). Otherwise it is the normal write path: `create_item`, then `_update` for the state, and `_update` to close, with every gate.
  The create sets no step, so the state is a second write; if it is refused, the item is closed again as dropped, never left half made.
- A deploy restarts `stackshot.service` (`stackshot/web/server.py` changed) and `stackshot-puller.service` (`stackshot/fleet/client.py` changed); a session runs `stackshot/fleet/client.py` fresh at each call, so no recycle is needed for it ([docs/session-reload.md](session-reload.md)).

## The agent state the fleet's session manager pushes

The audit needs to know whether a registered agent is busy (its pane in a turn, or a subagent running) or idle, and the server cannot read that where the agents run. The fleet's session manager pushes it, once per run of its
heartbeat (about every five minutes), the whole fleet in one body that REPLACES the last snapshot. One authenticated write, `POST /client/agent-state`, `Authorization: Bearer <machine token>`, the body

```
{"schema": 1, "written": <epoch s>,
 "agents": {"<registered agent name>": {"state": "busy" | "idle" | "unknown", "since": <epoch s>, "why": "<one line>", "pane": "turn" | "idle" | "shell" | "sleeping", "read": true | false,
                                        "subagents": [{"id", "description", "brief" (its first 2048 characters), "at": <epoch s>, "quiet"?: true, "unreadable"?: true}]}}}
```

The sender decides the state: busy is a pane in a turn or any running subagent, idle is a pane that is idle, showing a shell or sleeping with no running subagent, unknown (with `read` false) is what it could not tell. The
subagents are the detail a line says and the audit ties to an item by name. 200 `{"ok": true, "agents": N}`; 400 with a one-line reason for a wrong schema, a body that is no JSON object, an agent entry that is malformed or a body over
1,000,000 bytes, and the previous snapshot stays; 401 without the machine token; 503 on a read-only standby copy or when the file cannot be written. The client script posts it: `client.py post agent-state --file <path>`, which sends the file's bytes as the body.

- **One snapshot for the fleet.** The server keeps ONE snapshot and each push replaces all of it, so every sender for a fleet pushes the whole fleet, never a part. An agent absent from the last snapshot reads unknown (fail closed): nothing is flagged and nothing is handed on for it.
- **An older push is ignored.** A push whose `written` is older than the stored snapshot's changes nothing and answers 200 `{"ok": true, "ignored": "older"}`; an equal or newer one replaces it. A stored snapshot dated more than five minutes ahead of the server's clock never makes a push count as older. For a sender whose clock is 0 to 5 minutes ahead, its pushes are accepted and a correct sender's older `written` is ignored until the true time reaches it, at most about five minutes after the fast sender stops. A `written` of zero or less is refused with 400. When more than one sender pushes, the last accepted push replaces the whole snapshot, so one sender should cover the whole fleet.
- **Numbers and text.** A time (`written`, `since`, `at`) must be a finite number no larger than 1e12 (a huge integer or a past-the-bound time is 400 with a reason), and no text may hold a lone surrogate (400 as well); the old snapshot stays and no temporary file is left. A body of exactly 1,000,000 bytes is stored, one byte more is 400.

- **One file.** The snapshot is `<paths.state>/agent-state.json` (the body as normalised, with `received`, the server's clock at the push), written whole to a temporary file and renamed over the last one, so a reader never sees half of one. It is
  outside the store and the fleet folders, so a push every few minutes republishes nothing.
- **How the audit reads it** (`stackshot/audit/agent_state.py`): `busy` or `idle` only when the snapshot is no older than 15 minutes (`MAX_AGE_S`) and not dated more than five minutes ahead of the clock, names the agent, and its entry has `read` true and a state of busy or idle.
  Anything else (no snapshot, a torn file, a stale one, an agent it does not list, `read` false, an unknown state) is unknown, never idle: the audit writes its unknown line, flags nothing and hands nothing on. A busy agent's subagents are
  the ones the entry lists; an idle agent has none. The reader trusts `state` and does not count the subagents again.

## A gap in a scheduled job

sala's job-gap watcher (`sala job check`) finds a timer or service of the host that is not in git or has no `X-Model-Lane`. Each gap is one board item, keyed by the unit and the gap's code, moved by the builder of the
repository that holds the job's script, and closed by the watcher itself once the gap is fixed (it used to be one message per gap, with nothing to close):

```
stackshot/fleet/client.py post job-gap open  <timer> <code> --repo <owner/name> [--detail "<text>"] [--sender <label>]   # prints the item id, exit 0
stackshot/fleet/client.py post job-gap clear <timer> <code> [--sender <label>]                                           # prints the closed id; exit 0, also when nothing is open
```

`<code>` is one of `no-description`, `no-lane`, `bad-lane`, `not-git`, `git-differs` (any lower-case word is taken, with its own name in the subject). Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated
write, `POST /client/job-gap`, `Authorization: Bearer <machine token>`, body `{"action": "open" | "clear", "timer", "code", "repo"?, "detail"?, "sender"?}` (200 `{item, timer, code, project, mover, owner, repeat, fallback}` for open,
`{timer, code, cleared: [ids], note}` for clear; 400 a check or a refusal, an unknown repo included, with the known ones named; 409 no project page or no front agent to file under).

- **The repo is mapped to its project page** by `[job_gap.repos]` (`"owner/name" = "<page key>"`; the default, when the table is absent, is none: an instance lists the repos it files job-gap items for). Names are compared as the other repository checks do (case, `[github.moved]`). A repo the table does not list is a 400 that names the ones it does.
- **One open item per (timer, code)**, marked `metadata.job_gap` = `<timer>: <code>`. Subject `<prefix> <timer>: <the gap>` (the scope prefix of the project, else `[subject] fallback_prefix`, else the first prefix; a long unit name is cut so the subject is never refused), p2, filed
  through `create_item` (every gate applies). The **mover is the project's builder** (`_builder_agent`: the background agent whose mandate builds), who is named in needs and told once, at the create, by the needs notice; the **creator
  is the project's `-main` agent** (a front agent is not woken). `next` is `<builder>: <the fix for the code>` (put the unit file in the repo with an `X-Model-Lane=` line, linked from there), and the description bullets say the gap, the
  fix and who opened it. A project with no builder moves the item by its `-main` agent, and the item, the answer (`fallback: true`) and the client (a line on stderr) say so.
- **No mentions.** A unit name takes an `@` only between letters or digits (`job@1.service`), so it can never start a GitHub mention; an `@` in `--detail` or `--sender` is broken with a zero-width space (`_no_ping`, as the
  other GitHub-bound text), so the mirror pings no one. A code outside the five known ones gets a neutral fix line ("see the watcher's report"), not a guess.
- **A repeat `open` of an open (timer, code)** changes nothing and answers the existing item (`repeat: true`). After a `clear`, an `open` files a new item.
- **`clear`** closes the open item: outcome `done`, a one-line reason within `[close] reason_max`, the end state in `outcome_text`, the description unchanged. None open is a no-op (200, `cleared: []`, a note that says so).
- **The sender** is the script's own label, under the terminal prompt's gate: at most 80 characters on one line and never the owner's name (400); none given is `stackshot/fleet/client.py`. There is no allow-list of labels (the machine token is the
  proof), so no config change is needed for sala's label `unit-gaps`. The item records `<label> via a script on <machine>`.
- **The row owes no page.** It sets `TERMINAL_ROW` as the terminal prompt does (no page debt for the script, the builder or the keeper, no router notice, a close told to no one) and the guard on alarming words does not judge the
  watcher's text; the builder's notice at the create is the one thing sent. `tool-text`: a client call only, no MCP tool changes.

## A hook's catch of a turn that signed off with no question

A front agent's hook can tell that a turn which a trigger started (a notice, a message, a script's line) ended with a no-ask phrase ("nothing needed from you", "no action"), where the turn should have said something or asked. The hook posts each such **catch**; the server keeps one line per catch and the audit reports the counts per source and day.

```
stackshot/fleet/client.py post catch - < catch.json                                  # the fields as one JSON object on stdin; prints ok (or duplicate), exit 0
stackshot/fleet/client.py post catch --hook <name> --id <id> --t <ISO time with offset> --pane <session> --kind <kind> [--sender <raw sender>] [--outcome <text>] [--first <text>]
```

Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/catch`, `Authorization: Bearer <machine token>` (a machine token is enough; a missing or unknown token is a 401), body `{"hook", "id", "t", "pane", "kind", "sender", "outcome", "first"}`, every value text (200 `{ok, duplicate, id, source, project, day, told}`; 400 `{error}` naming the field, as the other script routes do; 503 the line could not be written, and a replay of the id is safe).

- **The fields.** `hook` the hook's name (at most 80 characters), `id` the catch's own id (200), `t` the time of the catch, ISO 8601 **with its offset or Z** (a time with no offset is refused, never guessed at; so is one before Jan 1st 2020 or more than two days ahead of the server's clock), `pane` the front agent that signed off (120), `kind` how the turn that began it was started: `notice`, `message`, `script` or any other word (40), `sender` the raw sender of that turn (300), `outcome` what the hook did (120), `first` the first words of the reply. `hook`, `id`, `t`, `pane` and `kind` are required; the others may be empty. A value over its limit, or with any character that is not printable (a control character, a tab, a line or paragraph separator such as U+2028, U+2029 or U+0085, a no-break space), is a 400. `first` is the exception: it is folded to one line and **clipped to 200 characters**, never refused for its length. Other keys of the body are ignored.
- **One line per id.** The line goes to `<paths.state>/catches/<YYYY-MM>.jsonl`, the month of the catch's day (modelled on the call log). A second post of an id already in that month's file writes nothing and answers 200 with `duplicate: true`, so a hook that retries after a lost answer counts once. The id is looked for in the month file of `t`'s day only, so a retry must send the same `t` (a hook keeps it with the id); the same id with a `t` in another month is a new catch.
- **The server adds three fields.** `day`: the day of `t` in the instance timezone (`[instance] timezone`), so a catch at 23:30 UTC is the next day's in a zone ahead of it. `project`: the project page of the pane's agent in the roles registry, else of the sender, else empty. `source`, worked out here from the raw sender, the kind and the registry, never taken from the hook: `router notice` (kind `notice`, `router` or `router-notice`, in any case, with a space or an underscore for the dash), `script` (kind `script`, or a sender that says it is a script), `stackshot message` (a sender that is the instance's own name, `[instance] name`, alone or followed by a space and more: `stackshot`, `stackshot audit`; `stackshot-builder` and `stackshotx` are not), `background-agent hand-back` (a sender the registry lists as a background agent), `front peer` (one it lists as a front agent), `other` (anything else). The first rule that fits wins, in that order.
- **One held word to the builder.** The first catch of an hour (the UTC hour of `t`, so an hour that a clock change repeats counts as two) for one pane and sender sends the project's builder one fyi: a single line of fixed words and the catch's fields (square brackets and `needs:` taken out of them, so a hook's text can never carry the owner's mark), saying what was caught and when, the time in the instance timezone. It is held for the builder's next turn and starts none; it is never pushed, so a builder whose hook does not fetch held lines, or a hold that fails, gets nothing. At most 10 such fyis go to one builder in an hour of the clock, whatever the panes and senders (counted in memory, so a restart counts again). A project with no builder, a send that could not be held or one over the cap loses nothing (the line is written first); the answer's `told` names the builder it was held for, empty otherwise.
- **The count.** `stackshot/tools/catch_report.py` (`stackshot audit catches`) reads the lines, see [audit.md](audit.md).

## A failed run of a scheduled job

A scheduled job that ends a run in failure reports it, and its next successful run says so, so the failure is ONE board item for the project's builder that closes by itself. The job's failure hook calls the first verb, a success hook the second; neither takes a `--sender` (the label is `job alert`, the item's creator reads `job alert (a script on <machine>)`):

```
stackshot/fleet/client.py job-failed <unit> <host> <ISO-Z time of the failing run> <project>   # prints the item id, exit 0
stackshot/fleet/client.py job-ok     <unit> <host> <ISO-Z time of the successful run>          # prints the id it closed, nothing when none was open, exit 0
```

`<unit>` is the systemd unit's name (`nightly.service`), `<host>` the machine's name, the time an ISO time in UTC (`2026-11-23T02:15:00Z`; one instant is kept in one spelling, so `:00Z` and `:00.000Z` are the same run, and a time more than 5 minutes past the server's clock is a 400 that says the machine's clock is ahead of the server's by that many minutes), `<project>` a project page key, a `scope/project` label or a single `-` for a unit with none. The arguments are positional; a `-` is a value, never an option. Exit 1 prints the reason on stderr (a usage line on misuse); a caller that must not fail on a failed post ignores the status, and re-sends a `job-ok` that was refused or lost. Underneath each is one authenticated write, `Authorization: Bearer <machine token>`, the machine found by the token as for every client write:

```
POST /client/job-failed   {"unit", "host", "time", "project"}  ->  200 {item, unit, host, project, mover, owner, action: opened | added | seen, failures, fallback}
POST /client/job-ok       {"unit", "host", "time"}             ->  200 {unit, host, closed: [ids as shown], note}
```

400 a check or a refusal (a key outside the body's keys, a malformed unit, host, time or project, or the tool's own text for the item); 409 no front agent to file under, a project key or label that names several pages (send its full key), or no general project to file a job with no project under (the instance has no `[job_alert] fallback_project` set, or it names no page); 503 the project record cannot be read. All four fields are text.

- **One open item per unit and host, read from the item itself.** The item is marked `metadata.job_alert` = `<unit> on <host>`, and the failed runs' times (the newest 20), their count, the unit, the host and the note on where it was filed are in its metadata too, so a restart of the server loses nothing. A failure while an item with the mark is open adds the run's time and counts it (`action: added`) and files nothing; a time the item already holds counts once (`action: seen`), so a call sent twice is one failure; a failure after the close opens a new item, unless its time is no later than the success that closed the last item (the close keeps that time in `metadata.closed_by_ok_at`): a retry or a call that came late is `seen` on that closed item and opens nothing. Unit and host are matched exactly, case-sensitive, so the failure hook and the success hook must send the same host string (`Host-A` and `host-a` are two jobs).
- **The mover is the project's builder**: the background agent whose mandate builds (`_builder_agent`, the lookup the job-gap route uses), named in needs and told once, at the create; the creator is the project's `-main` agent (its first front agent). A project with no builder is moved by that `-main` agent, and the item, the answer (`fallback: true`) and the client (a line on stderr) say so.
- **The project text is resolved in this order:** the instance's own map `[job_alert.projects]` (a label such as `acme/widgets` to a page key, `"acme/widgets" = "projects/acme-widgets"`; read at each call, and a key that names no page falls through), then the text as a page key or bare slug (a slug that names two pages is a 409 naming both), then, for a `scope/project` label, the one top-level page whose `display-name:` line is the label with its `/` made `-` (`acme/widgets` is the page named `acme-widgets`), and last the general project below. The name match is case-insensitive and considers only active pages of `type: project`: a page whose status is done, completed, merged, archived or retired, and a page of another type such as a note, is not a candidate, so a finished page that shares the name does not make the label ambiguous, and a label that only such pages carry goes to the general project. Two active pages of the name are a 409 naming both; the instance pins the label to one of them in `[job_alert.projects]` (the 409 says so). A label found by the map or by the name is said so in the item's note.
- **A job with no project, or an unknown one, goes to the general project's builder.** A `-`, and a project that none of those finds, are filed under the page `[job_alert] fallback_project` names (the code names none: an instance sets its own general project, for example `ops/general`), and the item's description says so. With none set, or a page the registry does not have, the call is a 409 that names the setting: a 409 means the instance has no `[job_alert] fallback_project` set (or it names no page).
- **The item's text is plain.** Subject `<prefix> <unit> failed on <host>` (the scope prefix of the project, as for the job-gap route; a long unit name is cut so the subject is never refused), p2. Description bullets, remade from the metadata at every failure: which job on which machine, how many failed runs since the item opened, the time of each of the newest three runs (in the instance's timezone), where it was filed when that is not the job's own project, what to do (read the job's journal on that machine, fix the cause; the next successful run closes the item) and who opened it. `next` is `<mover>: read the journal of <unit> on <host>, fix the cause; the next successful run closes this item`.
- **`job-ok` closes the open item** through the update tool's own close: outcome `done`, the run's time in the reason (within `[close] reason_max`) and in `outcome_text`. With no open item for the unit and host it is a 200 that does nothing (`closed` empty), so it may be sent on every success and twice for one. A time older than the latest failed run the item holds is also left alone (the note says why): a success sent late, after a newer failure opened the item, says nothing about that failure.
- **The row owes no page and tells no front agent.** It sets `TERMINAL_ROW` as the other script routes do; the builder's notice at the create is the one thing sent. The alarming-words guard does not judge the job's text. `tool-text`: a client call only, no MCP tool changes. Code: `stackshot/service/job_alert.py`; tests: `tests/script_post_kinds_scenario.py`.

## An item a script opens for a background agent

A timer's script that finds work for a project's background agent (a weekly size report that went past a threshold, for one) asks for one board item of that work. The route is narrow on purpose, so it is not a general way to file items:

```
stackshot/fleet/client.py post item-open <marker> --project <key|id|slug> --subject "<action and object>" --mover <agent> --step "<agent>: <what it does>" --line "<fact>" [--line "<fact>" ...] [--sender <label>]   # prints the item id, exit 0
```

Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/item-open`, `Authorization: Bearer <machine token>`, body `{"marker", "project", "subject", "description": [lines], "step", "mover", "sender"?}` (200 `{item, marker, project, mover, owner, repeat, fallback}`;
400 a check or a refusal, with the tool's own text; 404 no such project; 409 no front agent to file under; 503 the project record cannot be read). A key outside those seven is a 400 that names it: there is no way to set needs, owner, priority, an ask or a date.

- **A front-only project** (`anchors.front_only`: no builder) whose page lists no `background:` agent (the fallback is `not back and front_only`) has none to hold the item, so the item is with the project's `-main` agent (its first front agent), as for the job-gap route: the `mover` and the `<mover>: ` start of `step` the script wrote are still required, the step keeps its words and starts with the `-main` agent's name instead, nothing is named in needs, the description gets one more line before the attribution (`<key> lists no background agent, so this is with <agent>, its front agent`; so one fewer line is left for the caller, and a list too long for that is a 400, never cut), the item is marked `metadata.item_open_fallback`, and the answer carries `fallback: true`. A project that lists a background agent is as before: the mover must be one of them (`fallback: false`).
- **The marker** is `<kind>:<what>` (`test_trim:stackshot`): a lower-case kind of at most 40 characters, a colon, then at most 80 characters of letters, digits and `_ . - /`, no spaces. The item is marked `metadata.item_open` = the marker.
- **One open item per marker and project, read from the store.** A marker belongs to its project: the same marker on another project is another item, and a call never answers or shows another project's item. While an item with the marker is open on the project, a repeat call answers it (`repeat: true`) and files nothing; once it is closed, the next call files a new item. The caller keeps no state.
- **A cap of 10 open items per project.** A project holds at most 10 open items filed by this route; a call that would file an 11th is a 400 that says the cap and that an open item must close first (a marker that changes on every run is the usual cause). Closed items do not count, and a repeat of an open marker is always answered and never counts as new.
- **The mover must be listed.** It has to be a background agent under `background:` on the project's own page; a front agent, the owner, another project's agent or a made-up name is a 400 that names the agents the page lists. It is named in needs and told once, at the create.
- **The step** is one line that starts with the mover's name and a colon, and says what the mover does. It is the item's one `next` line.
- **The subject** is the action and its object. The server puts the project scope's prefix before it (the scope's prefix, else `[subject] fallback_prefix`, else the first prefix); every instance prefix the caller wrote at the start is taken off when it is a prefix of its own (a space, the end of the text or another prefix follows it; `[home]-style fix` keeps its bracket word), and the scope's goes on once; a subject that is nothing but instance prefixes is a 400. A subject over `[subject] max_length` is cut at the last word that fits, with ` …` after it, and the reply says so; with no word after the scope prefix that fits, the create tool's gate refuses it.
- **The description** is bullets, a list of lines (or one text of lines). At most `[description] max_lines` less one lines, each at most `[description] line_max` characters as a bullet; too many or too long is a 400 and nothing is cut. The server adds the last bullet, `Opened by <sender> (a script on a client machine)`, so no host name reaches the item or its GitHub issue. An `@name` in a line is broken with a zero-width space, so the mirror pings no one.
- **The sender** is the script's own label: one word of letters, digits and `_ . -`, at most 60 characters (so the attribution line fits its limit), never the owner's name; none given is `client.py`. There is no allow-list of labels (the machine token is the proof).
- **Filed like any item, except what judges a session's write.** The create goes through `create_item`, the create tool's own code, so its subject, description, next and project-page gates apply. A script's write skips the Goal-bullet check (a description needs no `Goal:` bullet), the line a session's reply carries about a page it still owes, and the checks that an item has an open step and that a front agent's step has a waker (the route requires the step itself); it also sets `TERMINAL_ROW` (`stackshot/service/writes.py`) as the other script routes do, which owes no page and skips the owner-step check. The project's `-main` agent is the creator (a front agent is not woken).
  `tool-text`: a client call only, no MCP tool changes.

## An item a script keeps in step with a condition

A timer's script that checks a condition only the person can put right (a plugin sync that fell behind, for one) opens ONE board item for him while the condition holds, rewrites its description on every run that still finds it, and closes it when a later run finds the condition gone. The item's mover is the person, its `then` is an agent of the project, and his one step is the script's text:

```
stackshot/fleet/client.py post item-sync <marker> open --project <key|id|slug> --subject "<action and object>" --mover <the person> --then <agent> --step "<what he does>" --line "<fact>" [--line "<fact>" ...] [--sender <label>]
stackshot/fleet/client.py post item-sync <marker> refresh --line "<fact>" [--line "<fact>" ...] [--sender <label>]
stackshot/fleet/client.py post item-sync <marker> close [--reason "<why>"] [--sender <label>]
```

Each call prints one line and exits 0: `<item> opened`, `<item> refreshed`, `<item> closed`, `<item> left open: open steps of others remain` (a close that found another writer's step still open, below), or `no open item for <marker>; nothing was refreshed` (`closed` after a close), a no-op that is not an error. Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/item-sync`, `Authorization: Bearer <machine token>`, body `{"action": "open" | "refresh" | "close", "marker", "sender"?, ...}` with `project`, `subject`, `description` (a list of lines), `step`, `mover` and `then` for an open, `description` for a refresh and an optional `reason` for a close. The answer is 200 `{item, marker, action: opened | refreshed | closed | left-open | none, project, mover, then, owner, repeat}` (`none` carries `item: ""` and a `note`, `left-open` an item and a `note`); 400 a check or a refusal, with the tool's own text; 404 no such project; 409 no front agent to file under; 503 the project record cannot be read. A key the action does not take is a 400 that names it: there is no way to set needs, an ask, a priority or a date.

- **The marker** is `<kind>:<what>`, in the form `item-open` takes (`plugin_sync:stackshot`), and it is the item's only key: the item is marked `metadata.item_sync` = the marker. `refresh` and `close` carry no project, so a marker names one open item at a time across the instance. An `open` for a marker that is open on another project is a 400 that names that project.
- **What the machine token can do here.** It can open items of this route, and refresh or close an item that carries this route's mark. It cannot touch any other item through it: an item filed any other way (the create tool, `question`, `terminal-prompt`, `job-gap`, `item-open`) carries no `item_sync` mark, so no marker finds it, and a refresh or close for such a marker is the no-op above. It cannot reopen, move, hand off, add a step to or answer an item, and it cannot change a closed item.
- **`open`** files the item through `create_item`, the create tool's own code, so the create tool's subject and next gates, the project page and the GitHub mirror all apply and a refusal is the tool's text (400). The description's line count and line length are checked by the route with `item-open`'s own pre-checks (refused and never cut), whose text is the route's, not the board's. The mover must be the person the instance names (any other name is a 400), the `then` an agent the project's page lists (a front or a background agent; another name is a 400 that lists them), the creator the project's `-main` agent (its first front agent). The `step` is one line that says what he does; his name goes before it and one the caller wrote is not doubled. Like the terminal prompt's row, the create sets no step, so the state is a second write (`your-step`, with his step the one open step of the checklist); if that write is refused (a step the board's step gates refuse), the item is closed again as dropped, never left half made, and the answer is the board's text; an item a crash left with no state (his step still open, the state not yours) is made whole by the next `open` of its marker, and one he has answered is left as it is.
- **One open item per marker.** While an item with the marker is open, a repeat `open` is a `refresh` (`repeat: true`) and files nothing: the subject, step, mover and `then` it carries are ignored. Once the item is closed an `open` files a new one (the condition recurs). A project holds at most 10 open items of this route; a call that would file an 11th is a 400 that says the cap and that an open item must close first (a repeat or a refresh never counts).
- **`refresh`** rewrites the description of the marker's open item and nothing else: not his step, the mover, the `then`, the subject or a closed item. A script's write is not judged by the Goal-first rule that judges a session's description (the board's way with every script row, as for `item-open`): the first bullet need not state a goal, and a prose line passes as one bullet. The description is bullets, a list of lines or one text of lines, under `item-open`'s rules: at most `[description] max_lines` less one lines, each at most `[description] line_max` characters as a bullet, refused and never cut; the server adds the last line, `- Opened by <label> (a script on a client machine)`. With no open item for the marker it is a 200 that does nothing.
- **`close`** completes the marker's open item through the update tool's own close: outcome `done`, a one-line reason within `[close] reason_max` (`--reason`; the default, `the script saw the condition (<marker>) is gone`, says the script saw it gone, and it is what the History shows), and the end state in `outcome_text`, with the description unchanged. His open step is ticked by the close (the checklist keeps it as done, by the script). **A close never settles another writer's step.** While any step other than his is open on the item (the agent that took it after his Done added a follow-up, or a second agent added a step), the close ticks nothing and completes nothing: the item is left open and the answer is `<item> left open: open steps of others remain` (action `left-open`, exit 0). The board lets only his answer tick his step, so the script does not tick it on its own, and it tells nobody the condition is gone: a script that sees `left-open` may `refresh` with a line saying the condition cleared, so what he and the agents read is true. What ends the wait depends on his step. While his step is still open, a close completes the item on the first run after the others have marked their steps. After he has answered Done, a session cannot mark the last open step of an item without completing the item itself, so the agent that holds it completes it, and the script's next close finds nothing and says so (the no-op below); until then every run answers `left-open` and exits 0, and nothing in the route ends that wait. With no open item for the marker it is a 200 that does nothing. `refresh` and a repeat `open` keep rewriting the description while the item is open, also after he has answered and an agent holds it. **Locks.** The route takes its own lock for every call (two opens of one marker file one item); a refresh, a close and a repeat `open` also hold the board's item lock from the look to the write, so a session's close cannot land between them. A new item's create is made without the board's item lock, because it reaches GitHub for the item number, and no other writer of the board waits for that.
- **The subject** is the action and its object; the server puts the project scope's prefix before it, as for `item-open`. **The sender** is the script's own label (one word, at most 60 characters, never the person's name; default `client.py`).
- **The row owes no page and tells no session.** It sets `TERMINAL_ROW` (`stackshot/service/writes.py`) as the other script routes do: no page debt for the script or the page's keeper, no notice to the `then` agent at the create. `_ITEMSYNC_LOCK` makes the look for an open item and the write one step, so two calls for one marker file one item.
  `tool-text`: a client call only, no MCP tool changes. Code: `stackshot/service/item_sync.py`; tests: `tests/item_open_scenario.py`.

## Anchors a hook adds for a pull request or an issue

A plugin hook on a client machine that has just seen a session make a pull request or an issue adds its anchor, so the board watches it, the way a session's `anchors` tool call with `add` does. The route is the tool's add and nothing else

```
stackshot/fleet/client.py post anchor-add - < anchors.json     # one JSON object on stdin; prints the server's text (the project's anchors, as the tool lists them), exit 0
```

Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/anchor-add`, `Authorization: Bearer <machine token>` (a missing or unknown token is a 401), body

```
{"project": "projects/<slug>", "add": ["https://github.com/<owner>/<repo>/pull/<n>"], "items": ["<item id>"], "sender": "<the session or script>"}
```

and the answer is 200 `{"result": "<the tool's text>"}`; 400 `{"error": "<reason>"}` for a body that does not fit and for a refusal of the tool; 401 without a machine token; 403 for a caller that holds a key's pass instead of a machine token (a pass opens only the New session form's calls, as for every verb here that is not one of them); 503 on a read-only standby copy, which answers every write so.

- **Pull requests and issues only.** Each URL in `add` must be exactly `https://github.com/<owner>/<repo>/pull/<number>` or `https://github.com/<owner>/<repo>/issues/<number>`: no query, fragment, trailing text, whitespace, newline or NUL, and `.` or `..` as the owner or the repo is refused (a name that merely starts or ends with a dot, such as `.github`, is a name and is taken). Anything else is a 400 whose text says that only pull request and issue URLs are accepted here. The machine token proves a machine, not the owner, and the other shapes the `anchors` tool takes (a Gmail query or thread, a Slack channel, a Drive file, a Notion page, a repository's notifications or releases) make the server read mail, chat or files and send notices to a keeper, so they stay with the tool.
- **The same function as the tool.** The route calls the code the `anchors` tool runs (`stackshot/web/tools/anchors.py`, `_anchors`) with `remove` empty, so the tool's own checks hold and its text is the answer: a project that names no page or more than one, an item that does not exist, one that is completed ("scope an anchor to open items, or leave it project-wide") and one that belongs to another project. A refusal of the tool is a 400 with the tool's own text.
- **The body.** `project` is required text of at most 200 characters (the page key, `projects/<slug>` or `infra/<slug>`, or the bare slug). `add` is required: a list of 1 to 10 URLs of at most 300 characters each. `items` is optional, a list of at most 20 item ids; with none (or an empty list) the anchors are project-wide, with some each anchor is scoped to those open items, and adding a URL again with more items widens its scope (the tool's union), adding it project-wide makes it project-wide, and a scoped add never narrows a project-wide anchor. The caps count what was received: a repeated URL or id counts each time. `sender` is required text. Any other key is ignored, except `remove`.
- **Adding only.** A body with a `remove` that is not empty is a 400 and changes nothing: a client route never takes an anchor away. Removing and listing stay with the `anchors` tool.
- **Who added it.** The machine token proves the machine and the body names the session, as for the other script routes: the stored anchor records `<sender> via a script on <machine>`. The sender is the caller's own word, not proved by the token. It is made one plain line first: whitespace runs collapse to one space and every control, bidi and zero-width character, and the Hangul fillers and the braille blank, is taken out; what is left is at most 80 characters, else a 400.
  `tool-text`: a client call only, no MCP tool changes. Code: `stackshot/web/routes/client_api.py` (`_client_anchor_add`); tests: `tests/client_scenario.py`.

## A caller's own key

A caller (the fleet tool) may be trusted by a key of its own instead of by the machine it runs on. Machine tokens stay as they are for the machine routes; what changes is how the New session form's calls
(`post project-agent`, `post project-agent-rename`, `post project-agent-retire`, the For you list's two writes and the color tool's `/client/colors/combos` routes) prove who sends them. The gate
(`_form_call` in `stackshot/service/projects.py`) takes either a live pass of an approved key (below) or, as before, a `sender` label in `[project_agent] form_senders` from a machine in
`form_machines`; the host lists go once every caller holds a key. Nothing else of `/client` opens to a pass: any other verb answers 403 `{"error": "a pass opens only the New session form's calls: ..."}`.

**The key.** An Ed25519 key pair the caller makes and keeps. The server keeps the public half, as `public_key` (its 32 raw bytes in base64url without padding, 43 characters) and knows it by its
fingerprint: the SHA-256 of those 32 bytes in hex, 64 characters stored, the first 16 shown. A key is `pending` until the owner approves it, `approved` after, and gone when revoked; a pending key is
trusted for nothing. Files in `<secrets>`: `keys-pending.json` (at most 5 keys, at most 3 of them from one source address, each kept 7 days) and `keys.json` (the approved ones), beside `clients.json`, 0600. A pending key keeps a short keyed hash of the
address it came from (a secret the server holds in `<secrets>/keys-source.key`, 0600), never the address.

**`POST /keys/enroll`**, no token, JSON body at most 8 KB: `{"public_key": "<43 characters>", "label": "<what the key is for>", "sender": "<the label its calls carry>"}`. `label` is at most 80
characters of letters, digits, spaces and `_ , + -`, `sender` at most 80 of letters, digits and `_ -` (both start with a letter or digit; no character that makes markup, a link or a mention, since both are
written on the board item, and so no `.`: the board makes a link of a bare domain such as `login.example.com`; both are shown in code spans there). A call's own `sender` is then the key's or starts with it and a `-` (a key enrolled as `sala` speaks as `sala-web` and `sala-retire`).
200 `{"state": "pending" | "approved", "fingerprint": "<64 hex>", "short": "<first 16>", "item": "board#N" | ""}`; the same key again answers its state and changes nothing; `item` is the item of a pending key, and is `""` for a key that is already approved (the answer says `approved`, never which item the key had). 400 a body that is not an object
or a key, label or sender that is not as above, or a weak key (not in its canonical form, no point of the curve, or a point of small order such as the identity); 413 a body over 8 KB; 429 more than 10 enrolls in 10 minutes from the caller's source address (or 300 from all addresses together), 5 keys already waiting, or 3 already waiting from that address (`retry_after` in seconds on the rate limit, with the `Retry-After` header);
503 a read-only standby copy, or a key file the server cannot read (it writes nothing over a file it cannot parse; the owner repairs or moves it). A new pending key raises one board item on the project `[caller_keys] item_project` names (ask: whether the key may call as its sender; options Approve and Reject, Reject
recommended; its Stakes part says that approving gives the key the whole New session form (registering an agent, renaming, retiring, the For you list) and every sender label that starts with its own and a `-`), filed under that project's front agent as a script's decision item; with no project set, or none that lists a front agent, no item is raised (`item` is `""`) and the command line below is the way.

**Approving.** The owner's answer Approve on the item approves the key and Reject deletes it; either takes effect at the next enroll, or at the key's own next claim (the server looks at the item then, by the id kept on the key's entry, so no
hook is needed and no request makes it scan the store), and the item is closed with the result. Neither the pending limit nor a rate limit stands in the owner's way: `keys approve`, `keys revoke` and a Reject on the item free a place at once. On the server box: `stackshot client keys list` (state, first 16 fingerprint characters, sender, label, item), `stackshot client keys approve <fingerprint>`, `stackshot client keys revoke
<fingerprint>` (an approved or a pending key; its passes stop at once). A fingerprint is typed with at least its first 8 characters, as many as name one key. A key approved on the command line has its item closed at
its first claim; the item of a key that is gone is closed by the next enroll that comes at least a minute after the last such look.

**An accepted limit.** The five places for waiting keys are open to any caller, and enroll carries no proof that the caller holds the private key. So a caller with no right to ask can hold all five for their 7 days (from a few addresses, three of them from each), and a new caller cannot enroll while they are held: its enroll answers 429. The owner clears the places with Reject on a key's board item or with `stackshot client keys revoke <fingerprint>`; callers whose keys are approved are not affected, since they need no place.

**`POST /keys/pass`**, no token, body `{"claim": "<compact JWS>"}` (at most 2048 characters): the claim is `<header>.<payload>.<signature>`, each part base64url without padding, the header `{"alg": "EdDSA"}`,
the signature Ed25519 over the ASCII text `<header>.<payload>` made with the key. The payload: `iss` the key's fingerprint (64 lowercase hex), `aud` the board's address (`[instance] board_url`, as written or
its origin), `iat` and `exp` in seconds since the epoch (numbers), `jti` a one-time id of 8 to 128 printable characters. The server refuses a claim whose life (`exp - iat`) is over 60 seconds or not
positive, whose `iat` is more than 60 seconds from its own clock, that has expired, or whose `jti` it has seen from that key in the last minutes. 200 `{"pass": "ssp_...", "expires_in": 600, "fingerprint", "sender"}`:
an opaque token, valid 10 minutes, kept in memory only (a server restart ends every pass, and the caller trades again), at most 20 live per key. The signature is checked before any limit is applied, and so are the claim's audience, its times and its jti. Until a signature has verified, the answer is the same for every fingerprint: a claim whose signature is not the named key's is 403 `state` `unknown` whether the key is approved, still waiting or not known to the server, so a caller with no right cannot find out which fingerprints exist or wait. Only a claim signed with the key itself is told more: `pending` for a key still waiting, the reason (401) when a claim of an approved key is stale, for another board or used. a claim that is fresh, for this board and unused is
never turned away because of other callers, and is limited per key (30 a minute); nothing but such a claim, signed with that key, counts there. A request that does not get that far (unreadable, an unknown key, a signature that is not the key's,
or a signed claim that is expired, for another board or already used, which anyone who has seen it can send again) is
limited per source address (60 a minute), and all such requests together by a high ceiling (600 a minute) that a single address cannot use up. The source address is the connection's, as the server reads it (the peer, or the client the
proxy in front of it names in `X-Forwarded-For` when that proxy is on the same box); a header the caller sends itself is never taken for it, an IPv4-mapped IPv6 address counts as the IPv4 address it carries, and any other IPv6 address counts by its /64. 400 a claim that is no compact JWS or whose parts are not JSON
objects (a part nested too deep for the parser included); 401 a header that is not EdDSA or an `iss` that is not a fingerprint (nothing is looked up for these), and, for a claim whose signature verified, an `aud` that is not this board, a missing or bad `iat`, `exp` or `jti` (a number that is not finite or is past a trillion seconds is bad), a life or clock
fault, an expired claim or a reused `jti` (`error` says which); 403 a key that is not approved, or a signature that is not the named key's (`state`: `unknown`; `pending` only for a claim signed with the key that is still waiting); 429 a limit above; 503 a standby copy, no `[instance]
board_url`, or no `cryptography` package on the server (the signature library its other dependencies bring).

**Using the pass.** `Authorization: Bearer <pass>` on a form call, where a machine token went. The server reads it as the caller `pass:<fingerprint>`, which is a form call when the key is still approved and the
call's `sender` is the key's label or starts with it and a `-`; a key revoked after the pass was given fails the next call. A pass whose call is not the form's (for `post project-agent`: a `sender` the key does not cover, including a session
id) is 403, never the session-id branch of that verb. A call with neither a valid token nor a valid pass is 401.

**`stackshot/fleet/client.py` with a pass.** When the environment variable `STACKSHOT_CLIENT_PASS` holds a value (blanks around it are dropped; unset, empty or only blanks changes nothing), `client.get` and `client.post`
send it as `Authorization: Bearer <value>` in place of the machine token for that process's calls, and do not read `<secrets>/client.token`. The caller sets it on the form's calls only (`post project-agent`,
`post project-agent-rename`, `post project-agent-retire`), after trading its claim at `POST /keys/pass`; a pass opens nothing else, and a read or write the server does not open to a pass answers 401 or 403 as for any other
caller. The client sends the value as it is, whether or not it starts with `ssp_`, and leaves every decision to the server. It never prints, logs or writes the value: an error text of the client has it taken out
(`<pass>`), and a failure to build the request with it says only that detail is withheld while `STACKSHOT_CLIENT_PASS` is in use. A pass lasts 10 minutes, so the caller trades again and sets the variable again for a later call.

  `tool-text`: client calls only, no MCP tool changes. Code: `stackshot/fleet/caller_keys.py` (the files), `stackshot/service/caller_pass.py` (enroll, claim, pass, the gate), the routes in
  `stackshot/web/routes/client_api.py`; tests: `tests/client_scenario.py` (its caller_keys part).

## Pushing the agent state with the script client

The fleet's session manager pushes its snapshot of which registered agents are busy and which idle (`POST /client/agent-state`) with the script client, from a file it has written:

```
stackshot/fleet/client.py post agent-state --file <path>      # prints the server's {"ok": true, "agents": N}, exit 0
```

The file is the whole body and goes to the server byte for byte, never parsed or re-encoded by the client. The route is for a machine's token only and refuses a caller's pass; the verb sends this machine's token, as every verb does, unless `STACKSHOT_CLIENT_PASS` is set in its environment, in which case it sends that value instead and the route refuses it, so a session manager leaves that variable unset. It reads only a regular file (a link to one is followed): a folder, a pipe or a device is refused with "not a regular file" without being read, so a path that would block never hangs the client. A file that is missing, unreadable, not a regular file, or over 1,000,000 bytes (the server's limit), and an empty `--file` value, are refused with one line on stderr and exit 1, and nothing is sent; control characters in a path are collapsed to spaces in that line. Any answer but 200 prints the server's one-line reason (or, when the answer has none, the status and the first 200 characters of its body) on stderr and exits 1, as does a server that is not reached (`[0]`) or a machine with no token. The machine's token is taken out of any text the client prints. Code: `stackshot/fleet/client.py`; tests: `tests/client_scenario.py` (its client part).
