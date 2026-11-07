"""ui — the board's web pages, at the root address ("/", "/items/<id>", "/closed", "/projects", "/search", "/runners", a project's page), served by the server from the store, behind the sign-in.

The page markup, style and scripts live here: ui/render.py (the home, an item page, a project page, Projects, Closed), the page half of search (ui/search.py) and of runners
(ui/runners.py), ui/kit.py (the state words, the one row every list draws, the type scale) and ui/releasing.py (which pull requests are in the release script's queue).

What the pages share with the rest of the server: the data and logic modules (home, itempage, landed, model, states, fleet, config, ...), search.py's index, runners.py's snapshot
and switch, render.py's markdown, brief and address helpers, the icons, the font and the manifest (static files at their root addresses), and the server's write routes: a form or
fetch on a page posts to the handler, which redirects back to the page.

PREFIX is the one place the path is named, and it is empty: every link, form action, redirect target and fetch address a page carries goes through under(), so an address of a page
is the bare root address. Shared static files keep their root addresses (/favicon.svg, /fonts/..., /manifest.webmanifest, /apple-touch-icon.png).
"""
PREFIX = ""


def under(path: str) -> str:
    """An app address under the prefix: under("/") is "/", under("/closed") is "/closed", under("/items/<n>") is "/items/<n>"."""
    return PREFIX + (path if path.startswith("/") else "/" + path)
