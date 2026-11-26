# The standby-copy command

What this page covers: `stackshot standby-copy`, one consistent copy of a running server's data for a [standby](read-only-standby.md): where it runs, what it locks, what it copies and leaves out, the manifest, and `--verify` on the receiving side. Back to the [README](../README.md).

```
stackshot standby-copy [--out DIR] [--extra DIR]... [--lock-timeout SECONDS] [--max-hold SECONDS]
stackshot standby-copy --verify DIR
```

The first form runs on the server box. It writes a tar stream to standard output, or the same tree into `--out DIR` (a directory that is not there yet or is empty; it is made beside `DIR` and renamed into place whole). The second form checks a received copy and runs anywhere: it reads no config.

It refuses, with exit 3 and one line:

- on a box that is not the server box: `[release] deploy_ssh` names another one; or it names none and `[server] box` is false, or is unset on a box without the pages checkout;
- on a read-only standby (`STACKSHOT_READ_ONLY=1`);
- with `[locks] cross_process = false`, since the running server then cannot be kept out;
- when the stream would go to a terminal.

## How the picture is made

1. A first copy of the three folders goes into a new 0700 staging directory under the runtime directory (`$XDG_RUNTIME_DIR`, else `/run/user/<uid>`), with no lock held.
2. The locks are taken: the publish lock, the project record's lock, every [store lock](server-passes.md) in its order (the wake pass, the item lock, the pending answers, the For you list, the Landed list, the held hand-back lines, the page-debt ledger, the stall record, the anchors file, the machine anchors) and the lock of the item id counter (`next-id`). The publish lock is waited for with nothing else held. Each later one is waited for two seconds at most; then all are let go and taken again.
3. Under the locks, every file that is new, changed or recently written is copied again, pass after pass, until a whole pass finds nothing to do. A `*.log` or `*.jsonl` file is cut once there, at its last whole line; lines added after that belong to the next copy.
4. The locks are let go. Only then are the extra directories copied, the files hashed and the output written.

The server's writes wait during steps 2 and 3. On a made-up instance of about 9,700 files and 380 MB, with a writer at work, the locks were held for 53 to 58 ms (325 to 357 ms without the first copy of step 1); the time grows with the number of files and with what changes between steps 1 and 3. Each run prints the figure and writes it into the manifest.

The anchors' daily pass has a lock of its own (`anchor-daily`) that only keeps two passes apart and is held for a whole pass; the command does not take it.

Not every file the server writes is under a store lock (the inbox, the client rows, the push queue, the caller keys and the logs, for example). Each such file arrives whole, and the passes of step 3 repeat until none changed under them, but a writer of those is not kept out.

## What is copied

| Folder in the copy | Source | Left out |
|---|---|---|
| `state/` | `[paths] state` | at its top: `site/` (the version files the server writes again; a static file put there by hand does not travel), `tmp/` (the scratch of the atomic writes), `search/` (the search index, built again from the store) and the hand-made `backup-*.tar.gz` files |
| `store/` | `[paths] store` | `.git`; the standby's `.synced-at` marker |
| `settings/` | `[paths] secrets` | this box's own client files: `client.token`, `client.url`, `stackshot.toml`, `plugin.json`, `test-launcher`, `clean-text-deny` |
| `extra/<n>/` | `--extra`, `[standby_copy] extra_dirs` | nothing |

In the first three, lock files (`*.lock`, `lock`) and temporary files (`*.tmp`) are left out too. A link to a file is copied as that file. A link to a directory, a dangling link and a special file are not copied; the command names them and the manifest lists them under `skipped`.

**Extra directories** are for data written outside the store locks, such as the sign-in library's own client store. Each is copied after the locks are let go, until a scan before the copy and a scan after it find the same sizes and times (six tries). One that never settles, is not there, or overlaps one of the three folders fails the run.

## The output

Every directory is mode 0700 and every file 0600 (0700 for a file its owner could execute); the stream names no user. `manifest.json` comes last in the stream, so a stream cut short has no whole manifest.

| Manifest key | Holds |
|---|---|
| `format` | `1` |
| `time` | when the picture was taken (UTC) |
| `code_commit` | the commit of the code that took it (`null` when it cannot be read) |
| `board_head` | the head commit of `[paths] repo`, read under the publish lock (`null` only with `[publish] git = false`) |
| `next_id` | the item id counter |
| `lock_hold_ms` | how long the locks were held |
| `roots`, `extra` | the source directory of each folder of the copy |
| `skipped` | what was not copied, and why |
| `dirs`, `files` | every directory; every file with its `sha256` and `size` |

## On the receiving side

Unpack into a new, empty directory, then run `stackshot standby-copy --verify DIR` on it before anything uses it. It exits 1 on a changed, missing or extra file or directory, on a link or special file, and on a manifest that is missing, cut short or malformed. It shows that the copy is the one the manifest describes, not who sent it: the transport has to see to that.

The copy holds none of the server box's own client files. A receiver that replaces a whole folder puts its own box's client files (the six names in the table) back in place itself.

## When it fails

Exit 1, with one line that names what failed, and nothing that counts as a copy: a lock not free within `--lock-timeout` (default 60 s), a copy under the locks longer than `--max-hold` (default 30 s), a folder that changes in every pass, an extra directory that never settles, a folder that is not there, a full disk. A signal ends the run with 128 + its number. The staging directory is removed on every one of these ways out; one left by a run that was killed outright is removed by a later run, once it is ten minutes old and no process holds it. Messages hold names and counts, never a file's content.

The staging directory holds the whole copy, so the runtime directory needs room for it: it is usually held in memory and sized as a share of it.
