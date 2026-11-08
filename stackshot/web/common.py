"""common.py: the pieces of the server that more than one part of it reads, with no state in them: the owner's name, what an item's needs list holds, and a line of free text cut for a notice.

server.py is being split into one module per area (CONTRIBUTING.md, Layout). A module of an area cannot import server.py, which is the program that imports the area, so what two
areas share lives here, below both, and server.py imports each name back: `server.<name>` stays the one name its callers and the tests use. Nothing here is something a test replaces; a name a
test sets on the server module (a function the writes call) stays in server.py until the areas that read it move with it. The store's path is not here but in store.py, where the tests set it."""
from __future__ import annotations

import re
from typing import Any

from stackshot.anchors import anchors as _anc
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


def _needs_store(meta: dict[str, Any], needs: list[str]) -> None:
    """Write a needs list into an item's metadata (the key goes when the list is empty)."""
    if needs:
        meta["needs"] = list(needs)
    else:
        meta.pop("needs", None)


def _canon_needs(needs: list[str], nm: dict[str, str] | None = None) -> list[str]:
    """The stored order: decision, external, then the sessions as given, each once (a session by its canonical id)."""
    out, seen = [], set()
    for k in _NEEDS_KINDS:
        if any(x.lower() == k for x in needs):
            out.append(k)
    for x in needs:
        if x.lower() in _NEEDS_KINDS:
            continue
        key = _anc.canonical(x, nm) if nm is not None else x
        if key not in seen:
            seen.add(key); out.append(x)
    return out


# Matchers that blank what is not plain text before an id is read: a fenced block, an inline code span, and the merge queue's group numbers.
_CODE_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1[ \t]*$|\Z)", re.M | re.S)
_CODE_SPAN = re.compile(r"(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")
# The merge queue numbers its groups g1, g2, … and a release log line carries them, in the forms "group g7", "split from g7" and
# "[g7]". g<n> is also the store id of an issue-numbered item (board#N), so a relayed release line would name an unrelated item.
# Those forms alone are blanked from a text before ids are read or shown; a bare g7, a "[g7](link)" and every other form still name.
_MQ_GROUP = re.compile(r"(?i:\b(?:group|split[ \t]+from))[ \t]+(?i:g)\d+(?![\w\-/\\]|\.\w)|\[(?i:g)\d+\](?![(\[])")


def _without_mq_groups(text: str) -> str:
    """`text` with each merge-queue group number ("group g7", "split from g7", "[g7]") blanked out (each character but a newline turned into \\0)."""
    return _MQ_GROUP.sub(lambda m: re.sub(r"[^\n]", "\0", m.group(0)), str(text or ""))
