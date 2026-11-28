# Files on a memo-box note

The files a person attaches to a note on an item: where they are kept, the limits, the routes, what a session is told and when they are removed.

## What the server does

- A file is uploaded alone, before the note is sent: `POST /items/{key}/files?name=<file name>` with the file as the request body. The request is checked as an answer is (signed in to the board, the board's own origin, the page's token for that item in the `X-Answer-Token` header). The answer is `201 {id, name, size, type}` (`type` is `image` or `file`, read from the file's first bytes, never from its name). The file waits as pending on the item.
- The note is sent as before (`POST /items/{key}/answer`) with `files=<ids>` in the form (one field with the ids separated by commas, or the field repeated). The files move from pending to the item, and the note's record on the item carries `files: [{id, name, size, type}]`. A note of files alone, with no words, is a comment. A bad list (more than four, an id twice, an id that is not waiting on this item) is refused with 400 and nothing is written; the files stay waiting.
- `GET /items/{key}/files/{id}/{name}` sends a file to a person signed in to the board; `GET /client/items/{key}/files/{id}/{name}` sends it to a machine that presents its client token (`Authorization: Bearer ...`). Only a file on one of the item's answers is sent. It is always an attachment of type `application/octet-stream` with `X-Content-Type-Options: nosniff` and a sandbox policy: the browser never renders it, whatever it is.

## Limits

| Limit | Value | Answer |
|---|---|---|
| One file | 10 MB | 413 "files are limited to 10 MB" |
| One image (png, jpeg, gif, webp, by its first bytes) | 5 MB | 413 "images are limited to 5 MB" |
| Files on one note | 4 | 400 |
| Uploads waiting on one item | 8 | 400 |
| All memo files on the server, pending ones included | 100 MB | 507 |

An image is kept as it was uploaded, so a larger one is refused, not shrunk. The constants are in `stackshot/service/memo_files.py`. An upload is written to disk in pieces and is refused as soon as it passes its limit (the declared length is read first); a refused or cut-off upload leaves nothing.

## Where they are kept

Under `<paths.state>/memo-files`, never in the item store (the store is published). `pending/<item>/<id>/<name>` holds an upload not sent yet; `<item>/<id>/<name>` holds a sent file. The name is cleaned (no directory part, no control character, at most 120 characters); a name ending `.tmp` or `.lock` gets `.bin` after it. An upload in progress is `upload.tmp`.

## What a session is told

The notice line of the note ends with `[files: name (size), ...]`. `get` shows the same on the answer line and a `files:` block with the address of each file for a machine to fetch with its token. The History of the item names the files.

## Removal

The daily timer `stackshot-memo-files-clean` (04:20, installed by `./install.sh units`; an install run with `STACKSHOT_READ_ONLY=1` leaves it out and removes an installed one, and the program itself does nothing on a standby, whose environment says so or whose store carries the copy job's `.synced-at` marker) runs `stackshot memo-files-clean` (`--dry-run` says what it would remove). It removes the files of an item 30 days after the item closed (the item's `state_updated`, else `updated`) when the newest of its files is 30 days old too, and any upload never sent after 24 hours. An open item, an item that cannot be read or is not in the store keeps its files.

## The standby

The standby copy carries the files with the state directory (see [standby-copy.md](standby-copy.md)). An upload in progress is a `*.tmp` file, which the copy leaves out, so a slow upload never makes a copy retry. A sent file does not change again, so the copy's locks do not wait for it. `standby-push` sends the whole copy every 5 minutes, unchanged files included; the 100 MB cap bounds that. A read-only standby refuses an upload (503) like any other write.
