"""common.py: the pieces of the server that more than one part of it reads, with no state in them: the instance's name and the owner's, and a line of free text cut for a notice (what an item's needs list holds is model/needs.py's, the matchers that read item ids are model/ids.py's).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). A module of an area cannot import server.py, which is the program that imports the area, so what two
areas share lives here, below both, and server.py imports each name back: `server.<name>` stays the one name its callers and the tests use. Nothing here is something a test replaces; a name a
test sets on the server module (a function the writes call) stays in server.py until the areas that read it move with it. The store's path is not here but in store.py, where the tests set it."""
from __future__ import annotations

import re

from stackshot.core import config as _cfg

# Read once, at import: the [instance] settings are among the ones config.RESTART_ONLY keeps for the run.
OWNER = str(_cfg.get("instance", "owner") or "the owner")
NAME = str(_cfg.get("instance", "name") or "stackshot")


def _clip_line(text: str, limit: int = 600) -> str:
    """Free text as one line of a notice: whitespace collapsed, cut at a word before `limit` with an ellipsis."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0] if " " in t[:limit] else t[:limit]
    return cut.rstrip(" ,;:") + " …"
