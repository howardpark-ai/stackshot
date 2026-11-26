# The standby-copy command

What this page covers: `stackshot standby-copy`, one consistent copy of a running server's data for a [standby](read-only-standby.md): where it runs, what it locks, what it copies and leaves out, the manifest, and `--verify` on the receiving side. Back to the [README](../README.md).

```
stackshot standby-copy [--out DIR] [--extra DIR]... [--lock-timeout SECONDS] [--max-hold SECONDS] [--output-timeout SECONDS]
stackshot standby-copy --verify DIR
```

The first form runs on the server box. It writes a tar stream to standard output, or the same tree into `--out DIR` (a directory that is not there yet or is empty; it is made beside `DIR` and renamed into place whole). The second form checks a received copy and runs anywhere: it reads no config.

It refuses, with exit 3 and one line:

- on a box that is not the server box: `[release] deploy_ssh` names another one; or it names none and `[server] box` is false, or is unset on a box without the pages checkout (`[paths] brain`);
- on a read-only standby (`STACKSHOT_READ_ONLY=1`);
- with `[locks] cross_process = false`, since the running server then cannot be kept out;
- when the stream would go to a terminal, or to the journal (the stream `$JOURNAL_STREAM` names, or a socket of the journal's).

One run at a time (the lock is a file in the runtime directory, so for each user): while an earlier run is still live (a receiver that takes its output slowly, say), a new one exits 1 and stages nothing.

## How the picture is made

1. A first copy of the three folders goes into a new 0700 staging directory under the runtime directory (`$XDG_RUNTIME_DIR`, else `/run/user/<uid>`), with no lock held.
2. The locks are taken: the publish lock, the project record's lock, every [store lock](server-passes.md) in its order (the wake pass, the item lock, the pending answers, the For you list, the Landed list, the held hand-back lines, the page-debt ledger, the stall record, the anchors file, the machine anchors), the lock of each push queue that is there (the `queue` and `queue-msg` folders that `fleet/push.py` keeps under the state dir) and the lock of the item id counter (`next-id`). The publish lock is waited for with nothing else held. All the locks after it share one wait, two seconds in all and never past `--max-hold`; then every lock is let go and they are taken again.
3. Under the locks, every file that is new, changed or recently written is copied again, pass after pass, until a whole pass finds nothing to do. A `*.log` or `*.jsonl` file is read there once: one written within the 2 seconds before that read, or changing while it is read, may be in the middle of a line and is cut after its last newline; any other is kept whole, a last line without a newline included. Lines added after the read belong to the next copy.
4. The locks are let go. Only then are the extra directories copied, the files hashed and the output written.

The server's writes wait during steps 2 and 3. On a made-up instance of about 9,800 files and 380 MB, with a writer at work, thirty runs held the locks for 57 to 102 ms, about 70 ms in the middle (340 to 429 ms without the first copy of step 1); the time grows with the number of files and with what changes between steps 1 and 3. Each run prints the figure and writes it into the manifest, with the attempts it gave up while a lock was not free (how many, and how long they held locks in all and at most).

The anchors' daily pass has a lock of its own (`anchor-daily`) that only keeps two passes apart and is held for a whole pass; the command does not take it.

### Writers with locks of their own

The passes of step 3 end only when nothing changed, so, logs aside, the copy is the three folders as they stood at one moment under the locks. A file that is written whole (to a temporary file, then renamed over the old one) is in the copy as it was at that moment, whether or not its writer is kept out.

- The **push queue** appends its lines in place, so a copy could hold part of one: the command takes the queues' locks.
- The **inbox** (`inbox/` in the state dir), the **client rows** (`clients/` there) and the **caller keys** (in the settings folder) have locks too, which the command does not take: each of their records is written whole. Where one change spans two files (a delivered line removed and then its lease dropped; the client state saved and then the views made from it; a key put on the approved list and then taken off the pending one), a copy can fall between the two. That is what the server finds after a crash at the same point, and it reads it correctly: a lease with no line runs out, the views are made again on the next pass, and the key is approved (its pending entry runs out).
- One file there, `clients/advertised-commit`, is rewritten in place with no lock at all; its reader takes it only when it holds a whole commit id.
- **Logs** are appended to with no lock: each is as it stood when it was read (step 3 says where one is cut).

## What is copied

| Folder in the copy | Source | Left out |
|---|---|---|
| `state/` | `[paths] state` | at its top: `site/` (the version files the server writes again; a static file put there by hand does not travel), `tmp/` (the scratch of the atomic writes), `search/` (the search index, built again from the store) and the hand-made `backup-*.tar.gz` files |
| `store/` | `[paths] store` | `.git`; the standby's `.synced-at` marker |
| `settings/` | `[paths] secrets` | this box's own client files: `client.token`, `client.url`, `stackshot.toml`, `plugin.json`, `test-launcher`, `clean-text-deny` |
| `extra/<n>/` | `--extra`, `[standby_copy] extra_dirs` | nothing |

In the first three, lock files (`*.lock`, `lock`) and temporary files (`*.tmp`) are left out too. A link to a file is copied as that file. A link to a directory, a dangling link and a special file are not copied; the command names the first ten, the manifest lists all of them under `skipped`, and `--verify` names them again. A state dir or a store with nothing to copy fails the run: that would not be a copy of a server.

**Extra directories** are for data written outside the store locks, such as the sign-in library's own client store. Each is copied after the locks are let go, until a scan before the copy and a scan after it find the same sizes and times (six tries). One that never settles, is not there, or overlaps one of the three folders fails the run.

## The output

Every directory is mode 0700 and every file 0600 (0700 for a file its owner could execute); the stream names no user. `manifest.json` comes last in the stream, so a stream cut short has no whole manifest. A file that standard output is redirected to is made 0600 before anything is written, whatever the umask the shell made it by.

| Manifest key | Holds |
|---|---|
| `format` | `1` |
| `time` | when the picture was taken (UTC) |
| `code_commit` | the commit of the code that took it (`null` when it cannot be read) |
| `board_head` | the head commit of `[paths] repo`, read under the publish lock (`null` only with `[publish] git = false`) |
| `next_id` | the item id counter |
| `lock_hold_ms` | how long the locks were held, from the publish lock on |
| `lock_attempts_abandoned` | the attempts given up while a lock was not free: `count`, `held_ms` in all, `longest_ms` |
| `roots`, `extra` | the source directory of each folder of the copy |
| `skipped` | what was not copied, and why |
| `dirs`, `files` | every directory; every file with its `sha256` and `size` |

## On the receiving side

Unpack into a new, empty directory, then run `stackshot standby-copy --verify DIR` on it before anything uses it. It exits 1 on a changed, missing or extra file or directory, on a link or special file, and on a manifest that is missing, cut short or malformed. It shows that the copy is the one the manifest describes, not who sent it: the transport has to see to that. It also names what the manifest says was not copied (a linked directory, for one), which does not change its answer.

The copy holds none of the server box's own client files. A receiver that replaces a whole folder puts its own box's client files (the six names in the table) back in place itself.

## When it fails

Exit 1, with one line that names what failed, and nothing that counts as a copy:

- a lock not free within `--lock-timeout` (default 60 s);
- locks that would be held longer than `--max-hold` (default 30 s, counted from the publish lock, the read of the board's head included);
- output that is not written within `--output-timeout` (default 600 s), so a receiver that stalls cannot keep a staged copy around for ever;
- an earlier run still live;
- a folder that changes in every pass, an extra directory that never settles, a folder that is not there, a state dir or store with nothing to copy, a full disk.

Each of the three time limits is a finite number of seconds above 0; anything else is a usage error (exit 2). A signal ends the run with 128 + its number. Messages hold names and counts, never a file's content.

The staging directory, and the half-made tree beside the target of `--out`, are removed on every one of these ways out. A run that is killed outright (`SIGKILL`, the out-of-memory killer) leaves them, settings files included, and a later run removes them: the staging directories in the runtime directory and, with `--out`, the `.<name>.standby-copy-partial-<8 characters>` directories beside its target. It removes only a directory with such a name that its own user owns, that is mode 0700, that no process holds, and that has nothing at its top but `state`, `store`, `settings`, `extra` and `manifest.json` (an empty one only once it is ten minutes old). Anything else stays. One left beside a target that no later run writes next to stays too, until it is removed by hand.

The staging directory holds the whole copy, so the runtime directory needs room for it: it is usually held in memory and sized as a share of it.
