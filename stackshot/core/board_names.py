"""board_names.py: the rule a board's name must pass, because the name becomes the first segment of the board's web address (`/<name>/items/N`).

    valid(name)   → the reason the name is refused, or None when it can be a board's name

The rule: lower-case ASCII letters, digits and hyphens, 2 to 32 characters, starting with a letter. Names compare lower-case, so `Canvas` is
refused as the reserved word `canvas` (the reserved check comes first, so the reason says so). A name in RESERVED is refused: it is the first
path segment of a route the server or the edge already answers, so a board with that name would be shadowed by it or would shadow it.

RESERVED is the first path segment of every route the board's server registers (tests/board_names_scenario.py builds the real app's route table
and fails when a route's first segment is missing here, so a later route cannot silently take a board's name), the front door's and the edge's own
paths, and the words kept for pages and areas that are still to come. Nothing here reads a config or a file: the names in use (`main`, `brain`, ...)
pass the rule, so no running board is refused.

Callers: the front door's config load (`frontdoor/config.py`, each backend's name), a board's `[behind_frontdoor] board_name` (`core/behind_door.py`),
and through that the config notes `stackshot doctor` prints.
"""
from __future__ import annotations

import re

SLUG = re.compile(r"[a-z][a-z0-9-]{1,31}")

# The first path segment of the routes of the board's server (its pages, its client API, its sign-in and OAuth routes, its static files), of the
# front door and of the edge in front of them, and the words kept for what comes next. Lower-case, as names compare.
RESERVED = frozenset({
    # the board's pages and API
    "items", "canvas", "mockup", "client", "files", "search", "closed", "projects", "runners", "audits", "audit", "for-you", "landed", "prefs",
    "routing", "frontdoor", "static", "fonts", "favicon.svg", "manifest.webmanifest", "apple-touch-icon.png", "answer-tokens", "colors", "index.html",
    "keys", "probe", "render-stamp", "runners.json", "infra", "hook",
    # the edge's and the sign-in's own paths
    ".well-known", "well-known", "authorize", "token", "register", "consent", "auth", "join", "mcp", "healthz", "ui", "login", "verify",
    # kept: the my-boards list, the API prefix and the words a later page will want
    "api", "boards", "admin", "new",
})


def _page_dirs() -> set[str]:
    """The first part of each configured page directory (`[pages] dirs`): the board's page route serves `/<dir>/<slug>`, so a board cannot have such a name. Read at the call; none when no config is loaded."""
    try:
        from stackshot.core import config as _cfg      # at the call: the config module reads others of core/
        return {d.split("/", 1)[0].lower() for d in _cfg.page_dirs()}
    except Exception:
        return set()


def valid(name: object) -> str | None:
    """The reason `name` cannot be a board's name, or None when it can."""
    if not isinstance(name, str):
        return f"a board's name is text, not {type(name).__name__}"
    shown = repr(name[:40]) + ("..." if len(name) > 40 else "")
    if name.lower() in RESERVED:
        return f"the board name {shown} is reserved: it is the first part of a web address the server already answers, so a board cannot have it"
    if name.lower() in _page_dirs():
        return f"the board name {shown} is reserved: it is a page directory of [pages] dirs, which the server answers at /{name.lower()}/<page>, so a board cannot have it"
    if not SLUG.fullmatch(name):
        return (f"the board name {shown} is not allowed: use 2 to 32 lower-case letters, digits and hyphens, starting with a letter "
                f"(it is the first part of the board's web address)")
    return None
