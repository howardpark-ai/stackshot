## description canvas
Keep and open canvases: HTML pages you share with a reader at <board>/canvas/<n> (a link they open on a desktop or a phone; the board's sign-in guards it). action = add | update | history | undo | list.
add(action="add", page="<html>…", title="…", sender="my-x") saves the page under the next number and answers its address on the first line, then `result: added`, then one `notice:` line for each thing
worth fixing. update(action="update", number=7, page="<html>…", sender="my-x") is a revision: the page replaces page 7 under the same number and address, and the page it replaces is kept as a version;
a revision is always update, never a new add (the reader's link to 7 would keep showing the old design). undo(action="undo", number=7) makes the newest version the page again and keeps the page it
replaces as a version, so a second undo goes back. history(action="history", number=7) lists the versions newest first (id, size, who wrote it); list(action="list") lists the canvases (number, size,
age, address, title). A page is refused, and nothing is saved, when its first part has no link to its item, written as <a href="<board>/items/N">board#N</a> (the bare text board#N is no link), when it is
empty, over {{CAP_MIB}} MiB, not UTF-8 text or holds a NUL byte, or when a title is over {{TITLE_MAX}} characters. The page's own scripts and styles run, but the page cannot read the board, its cookies or the
network. A page with no link color of its own is shown with one that reads on a light and a dark screen; a page that marks words with <span data-tip="…"> gets a tooltip that opens on a click or tap,
closes on a second click, a click outside or Esc, and never opens on hover alone. A decision page is read on a phone: when the item the page links needs a decision, the reply carries a
`notice:` line if the visible text is longer than one screen (about {{SCREEN_CHARS}} characters) or the first line has no question or no recommendation (the page is saved all the same). Saving is
off ([canvas] write) until the pages are moved in from the store that holds them now: the reply says so.

## param action
What to do: add (a new canvas), update (a revision of canvas `number`), history (the versions of `number`), undo (the newest version of `number` is the page again) or list (every canvas).

## param number
The canvas's number, for update, history and undo (add takes none: the board gives it).

## param page
The page's HTML text for add and update: a whole page, UTF-8, with the link to its item in its first part (`<a href="<board>/items/N">board#N</a>`).

## param title
A short name for the canvas (add and update; update keeps the old one when this is empty).

## param sender
Your own session (name or cse_… id), who wrote the page; recorded with each version.
