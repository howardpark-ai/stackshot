"""ids.py: item ids and the places an id is read from: an id as a session writes it → the store's (`_norm_id`, `_bare_id_ok`, `_GID`), an item's address on the board (`_ITEM_KEY`, `_ITEM_PATH`, `_item_gid`),
and the ids named in a free text: the matchers that blank what is not plain text before an id is read (`_CODE_FENCE`, `_CODE_SPAN`, `_QUOTED`, the merge queue's group numbers `_MQ_GROUP` with `_without_mq_groups`,
and `_plain_text`), and the matcher of an id written as a plain word (`_ID_FORM`, `_ID_END`, `_ITEM_REF`).

A domain module: it takes text and ids in and gives ids and text out, with no store and no clock (what asks the store whether an item exists stays with the store's readers: `_shown_ids` in service/store.py,
`_item_refs` in server.py). `_item_url` reads the board's URL, which core/instance.py holds."""
from __future__ import annotations

import re

from fastmcp.exceptions import ToolError

from stackshot.core import call_log as _calls
from stackshot.core import instance as _inst
from stackshot.github import ghsync as _gh

_GID = re.compile(r"^([a-z])#?(\d+)$")


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


def _bare_id_ok(status: str | None) -> bool:
    """An update reads a bare item number unless it closes the item (status=completed): a close takes the same shown id the complete tool does."""
    return str(status or "").strip().lower() != "completed"


def _norm_id(item_id: str | int, bare: bool = False) -> str:
    """An id as a session writes it → the store's: a store id, c1; board#N and #7 → the issue-numbered item (ghsync.norm);
    board-tmp-<machine>#3 and board-tmp-<machine>-3 → l3, the temporary id of an item created while GitHub was down or the hour's writes were spent; a
    migrated or re-keyed item's old id → its id now (the alias map). `bare=True` (the id of get, confirm and an update that does not close, the item a call is about) also reads a plain number N
    as board#N and notes the correction; anywhere else (complete, an update with status=completed, after, items, a link) a bare number stays a bad id, since a close or a link is not undone by a resend."""
    s = str(item_id).strip().lower()
    g = _gh.norm(s)
    if not g and bare and re.fullmatch(r"[0-9]+", s):            # a bare number is the issue number of a board item: board#N (ASCII digits only: int() takes them all)
        g = _gh.norm(f"board#{int(s)}")
        if g:
            _calls.fixed("item-id", f"item {s} read as {_gh.shown(g)}")
    if not g:
        m = _GID.match(s)
        if not m:
            raise ToolError(f"bad item id {item_id!r} — ids read board#<n> (a temporary one {_gh.local_prefix()}#<n>), or <letter><n> for an older item")
        g = f"{m.group(1)}{m.group(2)}"
    return _gh.resolve(g)


_ITEM_KEY = r"([a-z][0-9]+|[1-9][0-9]*|board-tmp-[a-z0-9-]*[a-z0-9]-[1-9][0-9]*)"
_ITEM_PATH = re.compile(r"items/" + _ITEM_KEY + r"(\.html|/)?")   # /items/<gid>: a lowercase letter and digits,
                                                                 # an issue-numbered item's bare number (/items/<n> is board#N), or a
                                                                 # temporary id's board-tmp-<machine>-<n>


def _item_gid(raw: str) -> str:
    """The id part of an /items/<…> address → the store's id now, "" when it names no item form: a temporary id's address →
    l<n> (another machine's prefix is no item), /items/<n> → g<n>, a migrated or re-keyed item's old id → its id now."""
    g = (_gh.norm(raw) if raw.startswith("board-tmp-") else _gh.norm("board#" + raw) if raw.isdigit() else raw)
    return _gh.resolve(g) if g else ""


# Only an id written as a plain word names the receiver (after misfires on items the receiver was not working:
# a test name quoted in a brief, "a close by …", and the token "1 g7@1700000000" in a format example). Not a plain word: an
# id in backticks (inline code or a fenced block), an id inside quotes (" " “ ” ‘ ’, or a '…' pair), an id with something glued
# on (an @, /, _, letter or digit right after it; anything before it but a space or an opening ( [ { < * , ; · — –). Sentence
# punctuation right after it still counts (. , ; : ) ] } ! ? … * · — – and a possessive 's), and so does a markdown link,
# [board#N](…/items/<n>). A bare mention in prose still names (the same day, a sala handover's "Context: board#N carried …"):
# the text's shape cannot tell a passing mention from a handover, so a message that cites an item only for context writes the
# id in backticks.
_ID_FORM = r"(board#\d+|board-tmp-[a-z0-9-]+[#-]\d+|[a-z]\d+)"
_ID_END = r"(?=$|[\s.,;:!?)\]}*…·—–]|['’]s(?!\w))"
_ITEM_REF = re.compile(r"(?<![^\s(\[{<*,;·—–])" + _ID_FORM + _ID_END + r"|/items/(board-tmp-[a-z0-9-]+-\d+|[a-z]?\d+)" + _ID_END, re.I | re.M)
_QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|(?<![\w'’])'(?=\S)(?:[^'\n]|'(?=\w))*?(?<=\S)'(?!\w)")


def _plain_text(text: str) -> str:
    """A message with its code (fenced blocks, inline spans) and quoted spans blanked out (each character but a newline turned
    into \\0, so what stays keeps its place and nothing reads as glued to a space)."""
    blank = lambda m: re.sub(r"[^\n]", "\0", m.group(0))
    return _QUOTED.sub(blank, _CODE_SPAN.sub(blank, _CODE_FENCE.sub(blank, str(text or ""))))


def _item_url(gid: str) -> str:
    """An item's page: <board_url>/items/<gid>, an issue-numbered one's at /items/<n>, a temporary id's at
    /items/board-tmp-<machine>-<n> (ghsync.href_id)."""
    base = _inst.BOARD_URL.rstrip("/")
    return f"{base}/items/{_gh.href_id(gid)}" if base else ""
