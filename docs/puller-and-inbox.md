# The puller and the inbox

What this page covers: how notices and messages reach a session on another machine, how a client box keeps itself current, and how the machine card is judged. Back to the [README](../README.md).

**The puller and the inbox.** A notice or message for a session on another machine waits in the server's inbox
(`stackshot/fleet/inbox.py`). Each machine runs one `stackshot/fleet/puller.py`, which holds a long poll open to the server with its machine token,
reports the sessions live on that machine (from the CLI's own registry, `~/.claude/sessions`; the router's own `claude -p` call, which runs in a `stackshot-router-*` temporary directory, is not a session and is skipped), writes each waiting line
into the session's inbox (a unix socket on Linux, a named pipe on Windows) and confirms it. The poll is also the
machine's sign of life. `stackshot/fleet/client.py` mints and revokes machine tokens on the server box and reads the board from any box.
`stackshot/fleet/push.py` puts the lines into the inbox and delivers on the server box itself what the inbox does not serve: a pane
here over its local socket, a cloud session with `claude --cloud`. The server box reaches into no other machine.
A line is for a session by its permanent id (code finds a session by its permanent
id, names are for people): `inbox.put` resolves whatever the sender wrote (a permanent id, a name, an alias, a transcript id) to the
permanent id of a live registry session and stores it on the line (`pid`; `name` stays for display), and a poll offers the line to
the live transcript that carries that id (`inbox._carriers`: the transcript the registry lists under it, else the one whose
server-kept name resolves to it; the newest registration wins when two carry it). A relaunch with a new transcript, a rename or the
CLI's placeholder name therefore strands nothing. A line with no permanent id (a name the registry does not know, a registry that is
down, a line stored before an earlier change) is matched as before: by the id it was addressed to, else by the name the server kept for the
session (never the name its puller reports: a relaunched pane reports the CLI's placeholder), the newest registration winning when two live
sessions carry one name. A line that still waits `[client] inbox_flag_minutes` (default 5) for a session that is running, on a
machine whose puller checks in, is reported once, with the likeliest reason, to the running pane that sent it and to the fleet's
keeper (`inbox.new_overdue`, the clients' tick). Not reported: a line held on purpose (a relaunch hold in
`held-msg.txt` or `held-resume-msg.txt`, a paused source), the flag's own lines, and anything in the first minute after the server starts.

**Three hold files per source** (beside the pause flags `paused-<src>.json` in the state folder; `<src>` is `hub` or `msg`). `held-<src>.txt` is written by another tool (the fleet tool's
relaunch hold), `held-api-<src>.txt` by the client API's hold call ([Holds on a session's inbox](inbox-holds.md)) and `held-resume-<src>.txt` by a reboot's resume (`reboot-hooks/reboot-queue.py resume`: the sessions it could not verify, and the keys an earlier resume held that this one
neither verified nor found queued); each writer replaces only its own file, so none erases another's holds. The resume never writes `held-<src>.txt`, and it leaves a key no session
row names anywhere (not a fleet heartbeat, not the session registry) out of its file: such a key is a retired session, and the resume's one JSON line lists it as `retired_sessions`. When the session registry has no rows at all (its folder missing or unreadable) nothing is called retired: only a fleet heartbeat row can tell then, and every other key stays held. Every reader takes the **union** of the three: `inbox.blocked` (so `inbox.take` and
`inbox.deliberate`) and `push.paused` hold a session's lines and queue when its key (the address, the transcript id, the name or the permanent
id) is in any of the three. A missing or empty file lists nothing. The reason text and the journal line name the file the key was found in, or all that hold it.

**A queued notice is checked before it is delivered** (`stackshot/fleet/stale_notice.py`). A stall reminder, a wake, "a wait ended" and a hand-off that
was not taken are true when sent, and a session that is away (or a box that was moved) takes them hours or weeks later. Both queues that hold a
notice for a session that cannot take it yet, the per-session queue `push.py --flush` delivers (the `queue-msg/<session>.jsonl` files of the hub's state directory) and
the inbox (`inbox.take`), pass the lines through `stale_notice.screen` right before handing them out. Only the server's own notices are screened (a line that opens with
`[stackshot]` and has one of those shapes; a message another session wrote opens `[stackshot message]` and is never touched). A screened line is
dropped, with a journal line, when it is older than `[client] stale_notice_hours` (default 6; `0` turns the expiry off), when every item it names has
closed, when every item it names has been parked again since (stall, wake and hand-off notices say the item is the recipient's to move now), or when
every item it names has another session as its mover (the recipient is not its mover, its `then` or a session in its needs; an item the owner moves, or no one, keeps its notices, since they go to the project's builder). Of several lines of the same kind about the same items only the newest is delivered. An age expiry also
reaches a line no session can take (a retired session's queue), where the items are not read. What the screen cannot read (an item that is
missing, a recipient it cannot tell from the mover) is delivered as before.

**The puller keeps a client box current** (puller 9; the PC's helper is its one service, and it
keeps itself current). Every poll's answer carries what is current (`clients.current`: the server's puller `VERSION` and
checkout commit, and whether that box may update itself). When the box is behind (its checkout is not at the server's
commit and is its ancestor) and idle (no live session in the CLI's registry, no `claude` process: the hooks run from the
checkout under a session, so it is never moved under one), the puller fast-forwards its whole checkout (`git fetch
origin`, `git merge --ff-only` to the server's commit: `stackshot/projects/pages.py`, the hooks and everything else the box runs from it move
with the puller; a dirty checkout is refused and the refusal reported).

**A box whose server is on another machine can keep the server's state files current** (puller 12, `[client] mirror_server_state`, off by default). The hooks and tools on a client box read some of the server's published files straight from the state folder: `roles.json`, `projects.json`, the fleet view (`clients/fleet/<letter>/machine.json` and `sessions.json`), `site/versions.json` and `clients/advertised-commit`. When the server runs on that same box it keeps them itself; when it runs elsewhere they would age without a word. With the setting on, the puller reads `GET /client/roles` and `GET /client/state-files` (`client.py get state-files`: `{host, generated, projects, fleet, versions, advertised_commit}`, behind the machine token like every client read) after each successful poll, at most every 30 seconds, and writes each file by a temporary file in the same folder and a rename, in the shape and under the name the readers expect. A file whose text is already what the server sent is left alone. A read that fails, an empty answer or one without the expected keys leaves the old file as it is (one log line when it starts failing, one when it works again), never an empty file.

- **A box that is the server writes nothing.** Two independent tests, either of which stops the mirror: the server address is loopback, or the host the answer names is this box's own. Holding a copy of the secrets file (`<secrets>/clients.json`) is not a test: it decides nothing. A stop is logged once.
- **`roles.json` is rewritten at every pass**, unchanged or not, and is the server's own text, `generated` included. A reader that checks only the file's modification time therefore sees a fresh file while the puller still reaches the server, and is not warned when the server itself has stalled: the file's own `generated` field is the server's, and is the one to read for that.
- **A letter leaves the local fleet view only when two fetches in a row lack it** (one pass can be a torn read of a machine's `sessions.json` on the server, which leaves the letter out of that answer), never when the view came empty. Each folder is removed on its own: the mirrored files go, a folder holding anything else stays, and an error on one folder does not stop the others (logged once).
- **A standby box** ([read-only standby](read-only-standby.md)) pointed at the live server with the setting on has its own state folder mirrored over. The content is the live server's own and harmless: it is what a reader on that box needs to see. (A standby keeps a copy of the secrets file so it can take over; that does not stop the mirror. A box whose server address is not loopback and whose server answer names another host mirrors, whether or not it holds that copy.)
- **Who can read it.** `state-files` shows every machine's fleet row and the failure reasons of their setup to any machine token. That is already the gate for the other client reads (`registry`, `roles`), so it widens nothing.

Tests: `tests/puller_mirror_scenario.py`.

**A box whose server is on another machine can read items as the live board has them** (three client reads, `stackshot/service/client_reads.py`; `tests/client_scenario.py`). A hook there that opened the item files of a local copy of the board's store read a copy that goes stale; these reads give the server's own files, parsed and nothing else done to them (no state derived, no wording changed), so a reader written against the store's layout takes the `record` of each answer as the file it used to open, and `anchors` as the entries of the anchors file it used to open beside it.

- `client.py get item-record <id>` is one item's record, open or closed: `{"id", "shown", "record", "anchors"}` (`id` the store's id now, an old id of a migrated item is read through the alias map; `shown` is `board#N`; `record` the item's file, with its checklist `metadata.steps`; `anchors` the anchors that name the item, each once as the model's own reader gives it: `url`, `items`, `added`, `by`, `page` the page that holds it and `pages` every page that does; a project-wide anchor names no item, `[]` for none). A bad id is 400, an id that names no item 404, and 503 when the item's file or the anchors file is there and does not read (never an answer with the anchors left off).
- `client.py get open-records <session>` is the records of the open items the session moves, takes after an answer or is named on, in one call: `{"session", "total", "truncated", "unreadable", "items": [{"id", "shown", "record", "anchors"}]}`, each row as `get item-record` gives it. The selection is the one `get items <session>` makes (the same function picks both), so an item in any state (held, waiting, after another) is in it and a closed item is not. The answer holds at most 300 records and about 4 MB; `total` is how many open items the session has and `truncated` is true when some were left out. `unreadable` lists the ids of items whose file does not read at the moment of this call (left out of `items`); a file that was already corrupt when the call began is skipped by the view that picks the items, so it is neither in `items` nor in `unreadable` (and `get item-record` on that id answers 503). A bad key is 400; 503 when the anchors file does not read.
- `client.py get anchors-record` is the anchors map as its file holds it: `{"anchors": {<project key>: [{"url", "items", "added", "by"}]}, "truncated"}`, `{}` when there is no file, 503 when the file does not read. Past about 4 MB the projects after that point are left out and `truncated` is true.

*Who can read it.* The gate of the other client reads, unchanged: a machine token (`Authorization: Bearer`, any minted machine's), else 401; a revoked token, a Basic or cookie credential and a token in the query string are 401. These reads do widen what a machine token can see: any minted machine token can now read the full stored record of any item, a closed one too, and the whole anchors map, because the token is not scoped to an item or a machine (as for `items` and `answer`, which show less). What the answers hold is what the item page and the `get` tool show of an item (its text, steps, history, hand-offs, answers and anchors) and no credential: the server's tokens, the clients' hashes and the sign-in records are not in an item file or the anchors file.

**A box follows the server through a repo move and a history rewrite** (puller 10), with no hand step. The poll's answer also carries
`repo`, the canonical address of the repository (`clients.repo_url`: the server checkout's origin as https with no user or password, or
`[client] repo_url`). A *clean, idle* box (no tracked edit, no merge, rebase, cherry-pick, revert or bisect in progress, no live session,
no `claude` process) whose origin is another repository (the comparison ignores scheme, user, port, case and `.git`, so ssh and https
forms of one repository are no move) fetches from the new address first, into a private ref namespace (`refs/stackshot-incoming/*`, removed
afterwards), and only an address that answers **and holds the server's commit** is set (`git remote set-url origin`) and carried over to
`refs/remotes/origin/*`; an address that does not answer, or holds another history, leaves the box and its remote-tracking refs as they were
and is the attempt's reason (`repo address <url>: git fetch: …`, or `… does not hold the server's commit <short>`). That failure is tried
again only after a backoff keyed on the address (once, then after 1 h, 4 h, then daily, the same as every other failed update), an
authentication error included, so a poll makes no network call in between and the card keeps the stored reason. A
clean, idle box whose HEAD is not in `origin/main` while the server's commit is (history rewritten, a branch never merged, the box's own
commits) saves a rollback branch `legacy-<first 12 characters of its HEAD>` at the old HEAD, reads it back, and only then moves to the
server's commit with `git reset --keep`: nothing is lost (the old commits stay on the branch, which is the safety net for any clean, idle
box that moves off a HEAD of its own) and nothing is ever `reset --hard`. A
branch that cannot be saved refuses the move before any reset. git's `reset --keep` and a fast-forward would replace an *ignored* untracked
file that the server's commit tracks without a word, and no commit holds it, so before the rollback branch or any move the puller compares
`git ls-files --others --ignored --exclude-standard` with `git diff --name-only HEAD <server commit>`: a file in both (or a folder of
ignored files where the target has a file) refuses the move, names the file in the attempt's reason (`untracked ignored file(s) in the way:
<file>`) and leaves the box red until the file is moved or removed. A box with uncommitted work or an operation in progress, or a busy box, is
refused and left as it was, red on its card. A box ahead of the server's commit on main (HEAD in `origin/main`) is left alone. Each
`legacy-*` branch stays until someone deletes it.

**The machine card is judged by where the box is.** The Machines card shows an update failure for the box's own checkout only
while the box's reported commit (`facts.stackshot`, kept on `machine.json` as `stackshot`) is not the server's commit
(`ui.render.machine_alerts`): red for a failed latest attempt while they differ, clear the moment they match, whoever or whatever put the
box there (a later attempt, a swap for a fresh clone, a hand fix). With either commit unknown the last attempt decides, as before; other
packages' attempts (`what` other than `stackshot checkout`) are judged by their last attempt.

**What the server advertises, and a box stranded off main.** The commit the server advertises is its checkout's HEAD only while `origin/main` (as last fetched) contains it: a checkout switched to an unmerged branch keeps advertising the last commit it advertised (kept in `<state>/clients/advertised-commit`; origin/main's own commit when it has none) and logs one warning line, so no box follows a branch that main will not contain. A box that did follow one anyway, or whose history was rewritten (HEAD is not in `origin/main`, tested first against the local ref with no network call, and fetched only when that says off main, while the advertised commit is) and is clean is put back on the advertised commit as described above (rollback branch first, then `git reset --keep`), the recovery recorded as an attempt (`recovered: left <commit>, which is not in origin/main (saved as legacy-<commit>)`) and under `recovered` in `puller-updates.json`; a dirty checkout is still refused (the older `moved` list in that file is kept for the record and no longer decides). A target commit is tried once, then
again after 1 h, 4 h and daily; after every checkout update the puller reloads itself (the reload described above, on Linux
and Windows alike, whether or not the `VERSION` changed: the new file runs in the same process, so a user unit or the scheduled
task's instance never ends). Every attempt is reported with the
next poll as `facts.updates`, `[{what: "stackshot checkout", from, to, ok, at, reason}]` (the last 10, oldest first; `from`
and `to` the commits' first 12 characters; `at` in UTC; `reason` empty on success), beside `facts.stackshot` (the box's
checkout commit in full, kept on the machine's record like its CLI version); the Machines panel keeps the attempts and
draws a failed one on the machine's column only while the box is not at the server's commit (see above). The target is compiled from git before the tree is touched (the puller's files and the modules they import; a commit that does not
compile is refused), idle is asked again right before the merge, a failed merge is rolled back to the old commit, and a reload
that does not load is recorded as failed and the running puller carries on. A checkout that reaches the server's commit some other way (swapped for a fresh clone, moved there by hand) is settled on the next poll with one ok attempt (`already at the server's commit`), so an older failure stops showing; `puller-updates.json` is never edited for that. On Windows only the CLI's own `claude.exe` counts as a
claude process, not Claude Desktop's; a process check that cannot answer counts as busy. `[client] self_update = false` switches it off: in the server's config for
every box (the server never says yes to its own box: `deploy.sh` keeps that checkout), in a box's own config for that box.
`stackshot/fleet/puller.py --dry-run` prints what the box would update now, or why not. Until this, sala kept a Windows box's `~\stackshot`
current: its heartbeat fast-forwarded the checkout to `origin/main` every round, and its watchdog provisioned a lagging box
over ssh (`stackshot/fleet/client.py puller-lag`, still served for the panel); both retire on sala's side, replaced by this. The helper has no
part in the Claude CLI (it only reports the installed version): the machine's own provisioning step updates it.

**A line for a name that is no live session is not left in a queue** (`stackshot/fleet/retired_recipient.py`, called by `push.py` and by the message relay). A message or notice sent to a retired agent, to an old name of a renamed session,
or to a session whose every pane has been gone longer than `[client] dead_after_minutes` on a machine that is online, used to wait in `queue-msg/<name>.jsonl` for a session that never came back. It now goes to
the project the name belongs to (the page that lists the name, else the page whose project name the session name starts with: the rule the message tool names a refused recipient's project by), recorded for the project's router
exactly as a message to the page key is, and the router picks the receiver. When no page that has another agent can be told (the name belongs to no project, or it is the project's only agent), the line goes back to its
sender saying the receiver is retired, or, when the sender is a script (the server's own name, a label such as `<job> (a script on <machine>)`), is only written to the journal. The sender is told either way:
`push.py` prints one line that begins `queued (retired: <name>, <why>; …` and says who got the line, and the message tool's reply begins `'<name>' is retired (<why>), so this went to its project '<key>' instead — held for the router …`.
The router's own deliveries are never readdressed (it would rule its own pass again), a name no heartbeat has seen is called retired only for a line that has waited longer than `[client] dead_after_minutes` (a pane started a minute ago is in no heartbeat yet), a hub-source line
(`queue/`) and a line held for a reboot's pause are queued as before, and a fleet view that is partial or does not read says nothing about any name: the line is queued as before. Every readdressed or returned line is one line of
`queue-msg-retired.jsonl` in the hub's state directory (id, name, reason, what was done, the notice id).

The lines such names had already left behind are cleaned once: `python3 stackshot/fleet/retired_recipient.py sweep [--queue DIR]` is the dry run (it prints the counts per name and per action and writes nothing), and `sweep --apply` does it.
A stale notice (`stale_notice.screen`: its item closed, parked again or moved to another session, older than `[client] stale_notice_hours`, or repeated by a newer one) is dropped, every other line of a gone name is readdressed or returned as above,
a line of a name with a live session stays, the queue file is moved to `archive/` in the hub's state directory (never deleted), and each dropped, readdressed or returned line is journalled with its id. A run cut off before it moved a file does not repeat the lines the journal already has.

**A sleeping session stays present** (`liveness.sleeping`, `clients.sleeping_sessions`). The fleet tool may put a session that has been idle for a while to sleep: its process ends, its pane stays, and it wakes by itself when a line is routed to it. A sleeper
is in no puller's poll, so it would be marked gone after the grace, refused a message after `[client] dead_after_minutes` and forgotten after `[client] session_horizon_days`. The fleet tool marks it in the store `[client] session_links` names
(`<letter>/sessions.json`, the file the links are read from) with a `sleeping` key on the session's row, the ISO time it went to sleep; a session that wakes has no key. Stackshot only reads the key: it never writes it, wakes nobody and touches no inbox file; a message to a sleeper is written
exactly as one to a running pane, and the fleet tool's own watch wakes the session for it. While the key is a non-empty string the session's row in the view carries it as `sleeping` and is never `gone`: not at the first poll without it (a `gone` stamp set before the key was read is lifted at the next check-in or tick),
not at the hook TTL, not at the horizon. It counts as present for every send and every item check: `liveness.pane_dead`, `liveness.session_down` and the retired-recipient test answer "" for it, so a message to it is queued, never readdressed to its project, and an item it moves is not called stalled for its sleep.
It is not live for idle time (`liveness.idle_live` is false: it has no turn to count). The sessions tool lists it as `sleeping since <time>` and not as "not running". A number, an empty or a blank string, or a boolean in the key is no mark: the session follows the normal rules.
When the key goes, the normal rules start from that moment (gone from the next check-in, present for the grace; the session's `seen` follows the mark while it is there, so a hook-only session's TTL starts from the last pass that saw it asleep). Without `[client] session_links` nothing is read and nothing changes.

A line that waits in the inbox for a sleeper is still flagged after `[client] inbox_flag_minutes` (`inbox.alive` holds for it, so a wake that stalls for long does not go unseen), in its own words: `inbox.why` says the session is asleep and has not been woken yet, the sender's flag says
"though the session is asleep" and not "runs", and the keeper's line names a late wake among the usual causes (`inbox.asleep`, `fleet_events.inbox_flag_tick`). A name a sleeper and a running pane both carry resolves to nobody in `fleet.by_name`, as two running namesakes do.
