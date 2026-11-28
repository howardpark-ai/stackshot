# Canvases

What this page covers: a canvas, a page an agent shares with the board's owner: its addresses, what a reader sees, what keeps the page apart from the board, where it is kept, and the import that moves pages in. Back to the [README](../README.md).

The code is `stackshot/service/canvas.py` (the store and the import), `stackshot/web/routes/canvas.py` (the read routes), `stackshot/web/ui/canvas.py` (the shell) and `stackshot/web/canvas_guard.py` (the headers). The tests are `tests/canvas_scenario.py` (the routes) and `tests/canvas_check.py` (a browser; CI runs it).

The board reads canvases and takes them from another store. It does not create or edit them yet: that comes with the cutover from that store, since two stores would give out the same numbers.

## Addresses

| Address | What it is |
|---|---|
| `/canvas/<n>` | the canvas on its current page |
| `/canvas/<n>/versions/<id>` | one version: the page as it was until the time its id names (`20261101T080000.000001Z`, UTC) |
| `/canvas/<n>/raw`, `/canvas/<n>/versions/<id>/raw` | the page itself, the stored bytes and nothing else |

The address is written in one place, `PATH` in `service/canvas.py`. All of them are behind the board's [sign-in](asks-and-answers.md). A browser opening a shell signed out is sent to sign in and back. The raw address answers a signed-out request with a plain 401, since it is read inside a frame. Only GET and HEAD are answered; anything else is refused with 405 (503 on a [standby copy](read-only-standby.md), which serves the reads).

## What a reader sees

The shell is a page of the board's own with no script: a way back to the board, the canvas's number and title, a link to its item when it has one, one history control that lists the versions newest first by the time each was replaced, and the page in a frame. Changing version loads another shell. The bar is never written into a stored page, so the raw address gives the page alone.

## What keeps a page apart from the board

A canvas is a page somebody else wrote, served from the board's address. It may run its own script; it must not read or change the board.

- The frame is `<iframe sandbox="allow-scripts">`: the page gets an opaque origin, so it has no cookie, no storage and no way to read the shell, and it cannot send a form, open a window or move the shell's window. The shell listens to no message from it.
- Every answer under `/canvas` and `/mockup` gets its headers from one wrapper in front of every route and its sign-in guard, by the path's prefix, so a redirect, a 401, a 404, a 405, a 500 and the standby's 503 have them too. Each has `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.
- The shell (a 200 at one of the first two addresses): `default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; font-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`. `frame-src 'self'` also stops a framed page that tries to send its frame to another site.
- Everything else, the raw page among it: `sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; img-src data:; media-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`. The sandbox in the header holds when the raw address is opened as a tab of its own. No cookie is set there.
- A link or a script can open a board address in the page's own frame or tab. Such a visit is a GET, which changes nothing the board holds (a rebuilt cache aside). `/ui/logout` answers only a person who opens it from the board or types it, and a visit from inside a sandboxed frame neither renews nor starts a sign-in. The audit's start refuses an opaque origin.

## The store

`<paths.state>/canvas/` is in the board's state folder, outside git, and the [standby copy](standby-copy.md) takes it whole, under the lock `canvas`.

```
counter                 the highest number ever given here
<number>/canvas.json    the record: number, title, item, the current page and the versions, each page with its hash, size, time and writing session
<number>/<sha256>.html  one page's bytes, under their own hash
```

Each file is written whole to a temporary file and renamed into place, bytes before the record that names them. Nothing is deleted: bytes a record no longer names stay on disk. An item is optional. One page is at most 5 MiB; the store as a whole has no limit.

## Moving canvases in

`POST /client/canvas-import` with `Authorization: Bearer <machine token>` puts one page into the store under its own number. It answers 403 unless the config says so:

```toml
[canvas]
import = true
```

It sets numbers and replaces pages, so turn it on for the move and off after. The body is one JSON object:

| Key | Value |
|---|---|
| `number` | the canvas's number, a whole number from 1 |
| `version` | `null` for the current page, else the version's id |
| `content` | the page's bytes in base64 (UTF-8, no NUL byte, at most 5 MiB decoded) |
| `bytes`, `sha256` | the page's size and SHA-256, which must match the content |
| `modified` | the page's time, epoch seconds |
| `session` | optional: who wrote the page |
| `counter` | optional: the highest number the sending store ever gave; the board's counter never goes below it |
| `title`, `item` | optional, with the current page only: the title and the item's id (`board#<n>` or a store id) |

The answer is `{"ok": true, "number", "version", "result", "sha256"}`. A rerun is safe:

| What the store holds | The call | `result` |
|---|---|---|
| no such page | any | `added` |
| the same content | same or older time | `unchanged`, nothing rewritten in the record |
| the same content, current page | newer time | `updated`: the record takes the time, session, title and item sent |
| another current page | newer time | `replaced` |
| another current page | same or older time | 409 |
| another page under this version id | any | 409: a version never changes |

400 is a body that does not fit (an unknown key included), 413 one over the cap; nothing is written by a refused call. 401 is a call without a machine token; a standby copy answers 503. A canvas with versions and no current page yet is not served, so a move may send them in any order. Compare each answer's `sha256` with the file you sent. The version ids are not made by the board here: when a current page is replaced, send the version it became under the sending store's id.
