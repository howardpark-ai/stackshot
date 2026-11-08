"""common.py: the pieces of the server that more than one part of it reads, with no state in them: the owner's name, what an item's needs list holds, and a line of free text cut for a notice.

server.py is being split into one module per area (CONTRIBUTING.md, Layout). A module of an area cannot import server.py, which is the program that imports the area, so what two
areas share lives here, below both, and server.py imports each name back: `server.<name>` stays the one name its callers and the tests use. Nothing here is something a test replaces; a name a
test sets on the server module (a function the writes call, the store's path) stays in server.py until the areas that read it move with it."""
from __future__ import annotations

import re
from typing import Any

from stackshot.core import config as _cfg

# Read once, at import: the [instance] settings are among the ones config.RESTART_ONLY keeps for the run.
OWNER = str(_cfg.get("instance", "owner") or "the owner")


_NEEDS_KINDS = ("decision", "external")


def _needs_list(value: Any) -> list[str]:
    """metadata.needs as the list it is since an earlier change: a stored list, or the one word of the form before it ("decision")."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    v = str(value or "").strip()
    return [v] if v else []


def _needs_of(meta: dict[str, Any]) -> list[str]:
    return _needs_list(meta.get("needs"))


def _needs_kinds(meta: dict[str, Any]) -> list[str]:
    return [x.lower() for x in _needs_of(meta) if x.lower() in _NEEDS_KINDS]


def _clip_line(text: str, limit: int = 600) -> str:
    """Free text as one line of a notice: whitespace collapsed, cut at a word before `limit` with an ellipsis."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0] if " " in t[:limit] else t[:limit]
    return cut.rstrip(" ,;:") + " …"
