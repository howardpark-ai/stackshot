# The client contract

What this page covers: what a machine needs from stackshot, setup-run reports, permanent session ids, filing a question and reading the answer, the client item and For you routes, a pane waiting in its terminal, a gap in a scheduled job, and an item a script opens for a background agent. Back to the [README](../README.md).

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
  one recommended), one decision per ask, the project page, the GitHub mirror and the page-debt rules apply as to a session, and a
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
- `GET /client/for-you` returns `{"generated", "rows": [{id, kind, item, project, what, url, urgent, ts, when, slacked}], "flags": {"board#N": "watch" | "mute"}}`
  (rows newest first; an item with no flag is in neither).
- `POST /client/for-you/seen`, `Authorization: Bearer <machine token>`, body `{"id": <row id, a whole number from 1> | "all", "sender": "<label>"}`.
  200 `{"ok": true, "seen": [<ids that left the list>], "rows": [<the rows still unseen, as in GET /client/for-you>]}` (`"all"` on an empty list is 200 with
  `"seen": []`). 400 a body that is not an object, a `sender` that is not one line of at most 80 characters, or an `id` that is neither; 401 no or an unknown
  token; 403 the caller is not the web form (`sender` not in `form_senders`, or the token's machine not in `form_machines`); 404 an id that is no row on the
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
- **The row owes no page and tells no session.** It is a notification that opens and closes with the pane: the writes set `_TERMINAL_ROW` (`stackshot/web/server.py`), so no page debt is charged to the script, the mover or the page's keeper, the router
  gets no notice of it, and the close is told to no one (the `_tell_*` notices return nothing). Otherwise it is the normal write path: `create_item`, then `_update` for the state, and `_update` to close, with every gate.
  The create sets no step, so the state is a second write; if it is refused, the item is closed again as dropped, never left half made.
- A deploy restarts `stackshot.service` (`stackshot/web/server.py` changed) and `stackshot-puller.service` (`stackshot/fleet/client.py` changed); a session runs `stackshot/fleet/client.py` fresh at each call, so no recycle is needed for it ([docs/session-reload.md](session-reload.md)).

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
- **The row owes no page.** It sets `_TERMINAL_ROW` as the terminal prompt does (no page debt for the script, the builder or the keeper, no router notice, a close told to no one) and the guard on alarming words does not judge the
  watcher's text; the builder's notice at the create is the one thing sent. `tool-text`: a client call only, no MCP tool changes.

## An item a script opens for a background agent

A timer's script that finds work for a project's background agent (a weekly size report that went past a threshold, for one) asks for one board item of that work. The route is narrow on purpose, so it is not a general way to file items:

```
stackshot/fleet/client.py post item-open <marker> --project <key|id|slug> --subject "<action and object>" --mover <agent> --step "<agent>: <what it does>" --line "<fact>" [--line "<fact>" ...] [--sender <label>]   # prints the item id, exit 0
```

Exit 1 prints the reason on stderr (a usage line on misuse). Underneath it is one authenticated write, `POST /client/item-open`, `Authorization: Bearer <machine token>`, body `{"marker", "project", "subject", "description": [lines], "step", "mover", "sender"?}` (200 `{item, marker, project, mover, owner, repeat}`;
400 a check or a refusal, with the tool's own text; 404 no such project; 409 no front agent to file under; 503 the project record cannot be read). A key outside those seven is a 400 that names it: there is no way to set needs, owner, priority, an ask or a date.

- **The marker** is `<kind>:<what>` (`test_trim:stackshot`): a lower-case kind of at most 40 characters, a colon, then at most 80 characters of letters, digits and `_ . - /`, no spaces. The item is marked `metadata.item_open` = the marker.
- **One open item per marker and project, read from the store.** A marker belongs to its project: the same marker on another project is another item, and a call never answers or shows another project's item. While an item with the marker is open on the project, a repeat call answers it (`repeat: true`) and files nothing; once it is closed, the next call files a new item. The caller keeps no state.
- **A cap of 10 open items per project.** A project holds at most 10 open items filed by this route; a call that would file an 11th is a 400 that says the cap and that an open item must close first (a marker that changes on every run is the usual cause). Closed items do not count, and a repeat of an open marker is always answered and never counts as new.
- **The mover must be listed.** It has to be a background agent under `background:` on the project's own page; a front agent, the owner, another project's agent or a made-up name is a 400 that names the agents the page lists. It is named in needs and told once, at the create.
- **The step** is one line that starts with the mover's name and a colon, and says what the mover does. It is the item's one `next` line.
- **The subject** is the action and its object. The server puts the project scope's prefix before it (the scope's prefix, else `[subject] fallback_prefix`, else the first prefix); every instance prefix the caller wrote at the start is taken off and the scope's goes on once. A subject over `[subject] max_length` is refused by the create tool's gate, not cut.
- **The description** is bullets, a list of lines (or one text of lines). At most `[description] max_lines` less one lines, each at most `[description] line_max` characters as a bullet; too many or too long is a 400 and nothing is cut. The server adds the last bullet, `Opened by <sender> (a script on a client machine)`, so no host name reaches the item or its GitHub issue. An `@name` in a line is broken with a zero-width space, so the mirror pings no one.
- **The sender** is the script's own label: one word of letters, digits and `_ . -`, at most 60 characters (so the attribution line fits its limit), never the owner's name; none given is `client.py`. There is no allow-list of labels (the machine token is the proof).
- **Filed like any item, except what judges a session's write.** The create goes through `create_item`, the create tool's own code, so its subject, description, next and project-page gates apply. A script's write skips the Goal-bullet check (a description needs no `Goal:` bullet), the refusal for a writer who owes a page, and the checks that an item has an open step and that a front agent's step has a waker (the route requires the step itself); it also sets `_TERMINAL_ROW` as the other script routes do, which owes no page and skips the owner-step check. The project's `-main` agent is the creator (a front agent is not woken).
  `tool-text`: a client call only, no MCP tool changes.
