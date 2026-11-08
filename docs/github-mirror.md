# The GitHub mirror

What this page covers: mirroring items to GitHub issues, the write and read budgets, temporary ids, the inbound comment reader and anchor-hub conditional reads. Back to the [README](../README.md).

**The GitHub mirror** (`ghsync.py`; slimmed by an earlier change). With `[github] sync` on, the store stays the working copy and every item has an
issue in `[github] issues_repo`, which gives it its number. The server's save calls the hook; a queue on disk (`<state>/github/queue/`)
and a worker thread carry the writes, paced under GitHub's limits, and an outage only delays them. **An issue carries the item's subject
(the title), whether it is open or closed (with the close reason) and its description (the body: a marker line that maps issue to item, the
description, and one footer line linking the item's page), and nothing else** (the store's files are the backup, and
issues are a mirror; people read the board instead). There are no history comments, no labels (`on hold` included), no typed
issue fields (owner, needs, project, priority, due, wake), no blocked-by links, and no Next, Ask, Options, Draft or Outcome in the body. The
store's files are the backup (the publisher pushes them to a repository you choose), and the item page's History is the store's git, with the mirror on
or off. A change to a field the issue does not carry makes no job and so no GitHub call at all (`ghsync.mirrored`, `on_change`); what older
versions wrote to GitHub (comments, labels, field values) stays as it is, nothing is cleaned up. With the mirror on, an `update`, `confirm` or `complete` that names no
`sender` is refused instead of being credited to the item's mover (`client.py recycle-due` names its script). `ghmigrate.py` moves a store's open items onto issues #1 onward (old ids
stay as aliases: `/items/<old id>` redirects); `[github] issue_ids` makes a new item's id its issue number, written
`board#<n>`. A create while GitHub is down, or when the hour's write budget leaves no room within a few seconds (`ghsync.CREATE_WAIT`, so a create never hangs behind a backlog of updates), is not refused: the item gets a temporary id under `[github] local_letter`
(`l1`, `l2`, …, never reused), its create waits in the queue, ahead of every other job, and when GitHub answers or the budget has room the worker creates the issue,
re-keys the item to its number (the old id an alias, `after` lists and anchor scopes following, as in the migration) and
tells the mover the new id. A temporary id is written `board-tmp-<machine>#<n>` (`<machine>` is `[instance] machine`,
e.g. `board#N`) and its page is `/items/board-tmp-<machine>-<n>`, which redirects to the issue-numbered item once
it is re-keyed; the tools read either form, and `l<n>`, as the item. Both switches are off by default.
The merge window: the updates of an issue that already exists wait `[github] merge_seconds` (300) in the queue, counted from the
oldest one, and go out together as one PATCH of the issue (title, body and state). A create, and a close or reopening (with whatever waits beside it), go at
once. The window is read off the jobs' timestamps on disk, so a restart in the middle keeps every pending update. One ledger,
`<state>/github/budget.json` (a file locked with `flock`, shared by the server and anchor-hub), counts every call of the host's one token
in the last hour: writes under `hourly_budget`, reads under `read_budget`, a `304` never. The server's reads (runners page, side
panel, merged-PR checks, the comment reader) and anchor-hub's `gh api` calls are in it. Each call also carries a caller tag (the optional `by` key of the
file, beside the unchanged `w` and `r` lists): `done_check`, `step_proof` and `event_wait` for the three merged-PR readers, `ghsync` for the mirror,
`comments` for the comment reader, `receivers` for anchor-hub, `release` (reserved for the release script's path), and `other` for a call with no tag, an unknown tag, or one a
process from before the tags made. `ghbudget.status()` and `ghbudget.by_caller()` give the hour's counts per caller (`by_caller` in the status, next to the
unchanged `reads`, `writes` and caps; the tags of each kind add up to its total). A file without `by` still reads (every call is `other`).
anchor-hub's GitHub reads and a restart (a restart made every conditional read a full, counted 200, one pass over every anchor and a start-up rescan, which could spend the hour's cap and leave the `github` row at "error"):
anchor-hub keeps its read position in `<state>/anchor-hub/cursors.json` (written aside and replaced, saved each minute and at a clean stop), and
for `github` that holds, besides each anchor's state and CI state, the ETag of each conditional read (per anchor: the issue, the pull request and
the check runs of its newest commit), the repository IDs it has learnt, and the saved resolution of each anchor's board label with the ETag it was
taken at. After a restart every read of an unchanged anchor is a `304`, which costs nothing and needs no body, since what it would have said is
in the saved state; a change during the downtime is a `200`, read against that state and reported. An anchor's ETags are saved only when the pass
has finished with it, so a save in the middle of a read (a clean stop) or after a read that failed keeps the older ETag and the change is read
again after the restart, never answered `304`. ETags saved by another `gh` login, or a section of the file that does not read as expected, are
not used; nor are an anchor's ETags when the saved state has no entry for the anchor (or, for an issue or pull request, no CI state): its first look is a
full read that seeds it. The start-up rescan names an anchor from its saved resolution (a conditional read of its issue, a `304`), and does not ask one that is
closed or merged at all, so the board's label of a finished anchor (its title, its last-activity age) can stay as it was until the next restart after the
anchor changes; the poll drops that saved label when it sees the anchor change. A finished anchor, a merged pull request or a closed issue (its CI, issue and
comments), is read once in 10 passes (10 minutes), staggered by anchor so they do not fall on one pass, instead of every pass: a reopening or a late comment is
seen within 10 passes. A closed pull request that is not merged is not finished (it can be reopened and merged, which must be reported): it is read every pass,
as a `304`; a merge that follows a reopening between two looks is reported as a merge. A restart with the ETags saved costs one counted read (GET /user) and
the reads of what changed; the first start with this code over a file from before it (state but no ETags, and no record of which anchors are merged pull
requests) runs the rescan in full once, reads the open anchors in full, and reads each closed one once as an issue only (no CI), which learns whether it is finished.
The inbound half (phase 3): with the mirror on, a reader thread polls the repo's comments every `[github] poll_seconds` (60 by
default, one GET each; no webhook, since the server sits behind an access proxy), and a comment by `[github] owner_login`
(by default the login the mirror's token belongs to) with no `[author: …]` header (the mirror's older comments carry one) is the owner's own: it is recorded on the
item under `metadata.answers` as `{ts, kind: "comment", text, via: "github", url, comment_id}`, shown in the item page's
history as written on GitHub, and told in one line to the item's mover and to every session named in its needs (a front
agent mover hears it marked for the owner). It clears no needs, changes no status and owes no page; the server's save of it
is not echoed back to the issue. The cursor and the ids delivered live in `<state>/github/comments.json`: a restart delivers
nothing twice, an edit of a delivered comment is not a new one, and the first run starts at "now", never at the history
before the deploy.
The body form (`BODY_FORM`) says which body an issue was last written with. The existing issues are not rewritten in bulk
(that would cost hours of the hourly write cap for no reader's benefit): an issue takes the slim body the next time its subject,
open or closed, or description changes. `[github] backfill_bodies` (off) lets `resync_bodies` sweep the stale ones once, paced, on the background
lane, behind the live writes. The map's `repo` note follows `[github] issues_repo` on its own when the board repo moves: never a hand edit in
the store. With `[github] issues_repo_id` set, every call for the repo addresses it by its numeric id (`/repositories/<id>/...`), so the writes
go on through a move too (GitHub follows a 301 on a read, not on a write); the name still makes the links. Until an earlier change an issue also carried per-change comments (bundled within 10 minutes, the item page's History drawn from them), typed
issue fields and blocked-by links, and the labels `needs:<x>`, `project:<x>` and `on hold`; those writers, their sweeps and the local copy of the
comments (`<state>/github/comments/`, `last.json`, `fields.json`) are gone, and the files they left in the state directory are unread.
