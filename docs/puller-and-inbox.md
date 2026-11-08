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
`held-msg.txt`, a paused source), the flag's own lines, and anything in the first minute after the server starts.

**The puller keeps a client box current** (puller 9; the PC's helper is its one service, and it
keeps itself current). Every poll's answer carries what is current (`clients.current`: the server's puller `VERSION` and
checkout commit, and whether that box may update itself). When the box is behind (its checkout is not at the server's
commit and is its ancestor) and idle (no live session in the CLI's registry, no `claude` process: the hooks run from the
checkout under a session, so it is never moved under one), the puller fast-forwards its whole checkout (`git fetch
origin`, `git merge --ff-only` to the server's commit: `stackshot/projects/pages.py`, the hooks and everything else the box runs from it move
with the puller; a dirty checkout is refused and the refusal reported).

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
