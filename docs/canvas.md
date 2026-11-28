# Canvases

What this page covers: a canvas, a page an agent shares with the board's owner: its addresses, what a reader sees, what keeps the page apart from the board, where it is kept, and the import that moves pages in. Back to the [README](../README.md).

The code is `stackshot/service/canvas.py` (the store and the import), `stackshot/service/canvas_write.py` (the commands), `stackshot/service/canvas_page.py` (what a page is checked for and given), `stackshot/web/tools/canvas.py` (the `canvas` tool), `stackshot/web/routes/canvas.py` (the read routes), `stackshot/web/ui/canvas.py` (the shell) and `stackshot/web/canvas_guard.py` (the headers). The tests are `tests/canvas_scenario.py` (the routes), `tests/canvas_write_scenario.py` (the commands), `tests/canvas_page_scenario.py` (the page checks) and `tests/canvas_check.py` (a browser; CI runs it).

The board reads canvases, takes them from another store and, once `[canvas] write` is true, creates and edits them with the `canvas` tool ([the commands](#the-canvas-tool)). Writes stay off until the import has moved the pages in, since two stores would give out the same numbers.

## Addresses

| Address | What it is |
|---|---|
| `/canvas/<n>` | the canvas on its current page |
| `/canvas/<n>/versions/<id>` | one version: the page as it was until the time its id names (`20261101T080000.000001Z`, UTC) |
| `/canvas/<n>/raw`, `/canvas/<n>/versions/<id>/raw` | the page itself, as saved, with [what it is given](#what-a-page-is-given) when it needs it |

The address is written in one place, `PATH` in `service/canvas.py`. All of them are behind the board's [sign-in](asks-and-answers.md). A browser opening a shell signed out is sent to sign in and back. The raw address answers a signed-out request with a plain 401, since it is read inside a frame. Only GET and HEAD are answered; anything else is refused with 405 (503 on a [standby copy](read-only-standby.md), which serves the reads).

## What a reader sees

The shell is a page of the board's own with no script: a way back to the board, the canvas's number and title, a link to its item when it has one, one history control that lists the versions newest first by the time each was replaced, and the page in a frame. Changing version loads another shell. The bar is never written into a stored page, so the raw address gives the page alone, as it was saved, plus [what a page is given when it needs it](#what-a-page-is-given).

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

## The canvas tool

One MCP tool, `canvas`, with `action` = `add | update | history | undo | list`. It is the same store as the import, so a canvas written here and one moved in read alike.

| Action | What it does | Reply |
|---|---|---|
| `add` (`page`, `title`) | saves the page under the next number (after the counter and after the highest folder) | the address on the first line, `result: added`, a `notice:` line for each thing worth fixing |
| `update` (`number`, `page`, `title`) | a revision: the page replaces the current one, and the page it replaces is kept as a version whose id is the time of the replacement (always newer than the newest id); the same page again changes nothing; an unknown number is refused | the address, `result: replaced` or `result: unchanged`, the notices |
| `undo` (`number`) | the newest version is the page again, with the title and item it had, and the page it replaces is kept as a version with its own, so a second undo goes back | the address, `result: restored <id>` |
| `history` (`number`) | the versions, newest first: id, size, who wrote it | one line each, or `canvas N has no earlier version` |
| `list` | the canvases that have a page: number, size, age, address, title | one line each, or `no canvases` |

`add`, `update` and `undo` are refused while `[canvas] write` is not true, and on a [standby copy](read-only-standby.md); `history` and `list` always answer. A revision is always `update`: a new `add` gives a new number and a new address, so a link to the old one would keep showing the old page.

A page is refused, with nothing saved, when it is empty, over 5 MiB, not UTF-8 or holds a NUL byte, when a title is over 200 characters, or when its first part holds no link to an item: a clickable `<a href="<board>/items/N">` (the board's own address, [instance] board_url), within the first 2000 characters once the head, comments, styles and scripts are left out. A `data-href`, a `<link>`, an anchor that is hidden or inside a title, textarea, noscript or template does not count; the first link found names the canvas's item. The bare text `board#N` is not a link. The canvas's item is the one the link names.

A **notice** is not a refusal: the page is saved and the reply says what to fix. It is given for a decision page, a page whose item needs the owner's decision, when its visible text is longer than one screen (about 1200 characters) or its first line has no question (a `?`) or no recommendation (the word `recommend`). The link to the item is not counted as text.

## What a page is given

The stored page is never changed. The raw address serves it with two additions, each made once at the end of the page's head and only when the page needs it (`canvas_page.served`):

- **A link color**, when the page has links and no style rule gives a link a color (`a`, `a:link` or `a:visited` in a selector, with a `color`; a rule for `a:hover`, `a:focus` or `a:active` alone does not count): `:where(a:link,a:visited){color:#2f72de}`, a color with a contrast of 4.5 or more on white and on black. A page that sets a dark background of its own on `html`, `body` or `:root` (a plain color, or in a `prefers-color-scheme: dark` query) gets `#8ab4f8` there instead, whichever of the two reads better on it. The rule has no specificity, so any rule of the page's own wins over it.
- **A tooltip**, when the page has an element with `data-tip="..."` and no script of its own that mentions `data-tip`. A click (a tap on a phone) opens the text under the element and a second click on it closes it; a click elsewhere or Esc closes it too, and another tip's click moves it there. It never opens on hover alone. The text is put in as text, never as markup, and an element that takes no focus is given `tabindex="0"`, so Enter or Space open it from the keyboard. The page's own script and style are allowed by the page's policy; nothing else is.

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
