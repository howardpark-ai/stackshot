"""canvas_write.py: the canvas commands, the writes and reads on top of the store in service/canvas.py (docs/canvas.md): add, update, history, undo and list.

    add(text, ...)        a new canvas under the next number (after the counter and after the highest folder, so a number is never given twice); the page is checked and the canvas's item is the one its link names
    update(n, text, ...)  a revision: the page replaces the current one under the same number, and the page it replaces is kept as a version, its id the time it was replaced
    undo(n, ...)          the newest version is the current page again; the page it replaces is kept as a version, so a second undo goes back
    history(n), listing() the versions of one canvas newest first, and the canvases

A page is saved only when it holds, in its first part, a link to an item (`href="<board>/items/N"`, canvas_page.item_link), is text (UTF-8, no NUL byte, not empty, at most MAX_BYTES). A decision page that
is long or opens without a question and a recommendation is saved all the same, with a notice in the answer (canvas_page.notices). Writes are off until `[canvas] write` is true (they stay off until the
import has moved the pages in, since two stores would give out the same numbers); the reads are never off. Each write is one stretch under the store's lock, the bytes written before the record that names
them, as the import does. The same store, record and files as the import: a canvas written here and one moved in read alike.

A service module: it imports core, the model and canvas.py (the store) and canvas_page.py (the page checks)."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.model.ids import _norm_id
from stackshot.service import canvas as _c
from stackshot.service import canvas_page as _page

WRITE_OFF = "the canvas writes are off ([canvas] write = false) until the pages are moved in; the reads (history, list) work"
_EMPTY = {"schema": _c.SCHEMA, "title": "", "item": None, "current": None, "versions": []}


def write_on() -> bool:
    """[canvas] write (default false): only a true written as TOML's true turns it on."""
    return _cfg.get("canvas", "write", default=False) is True


def board() -> str:
    return str(_cfg.get("instance", "board_url") or "").strip().rstrip("/")


def address(number: int) -> str:
    return f"{board()}{_c.PATH}/{number}"


def _refuse(why: str) -> ToolError:
    return ToolError("Refused: " + why)


def _number(n: Any) -> int:
    try:
        return _c._whole(n, "number")
    except _c._Refused as e:
        raise _refuse(str(e)) from None


def _read(number: int) -> dict[str, Any]:
    try:
        rec = _c.read(number)
    except _c.Unreadable as e:
        raise _refuse(f"{e}: nothing written over it") from None
    if rec is None:
        raise _refuse(f"no canvas {number}: a new canvas is add")
    return rec


def _checked(text: Any, title: Any) -> tuple[bytes, str, str]:
    """The page's bytes, its title and the id of the item its link names; a refusal for the first thing that does not hold."""
    if not isinstance(text, str) or not text.strip():
        raise _refuse("the page is empty: pass page=<the page's HTML text>")
    if "\0" in text:
        raise _refuse("the page holds a NUL byte")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise _refuse("the page is not UTF-8 text") from None
    if len(data) > _c.MAX_BYTES:
        raise _refuse(f"the page is {len(data)} bytes, over the {_c.MAX_BYTES}-byte limit")
    try:
        name = _c._text(title, "title", _c.TITLE_MAX)
    except _c._Refused as e:
        raise _refuse(str(e)) from None
    base = board()
    if not base:
        raise _refuse("this board has no address ([instance] board_url), so a page has no item link to check")
    found = _page.item_link(text, base)
    if found is None:
        raise _refuse(f'the page has no item link in its first part: open it with <a href="{base}/items/N">board#N</a>, the link to the item it is for (the text board#N alone is not a link)')
    return data, name, _norm_id(f"board#{found}")


def _is_decision(item: str) -> bool:
    """True when the item the page is for is one that needs a decision; an item that cannot be read is no decision."""
    from stackshot.service.store import _load
    try:
        needs = (_load(item).get("metadata") or {}).get("needs") or []
    except Exception:      # noqa: BLE001  (a missing or unreadable item: no notice, the page is saved all the same)
        return False
    return "decision" in needs


def _notices(text: str, item: str) -> list[str]:
    return _page.notices(text, board(), _is_decision(item))


def _now(rec: dict[str, Any]) -> tuple[float, str]:
    """The time of a write and the id of the version it makes: that time, and always newer than any version the record holds."""
    t = time.time()
    stamp = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    ids = [v["id"] for v in rec["versions"]]
    top = max(ids, default="")
    vid = stamp.strftime("%Y%m%dT%H%M%S.%fZ")
    while vid <= top:
        stamp += datetime.timedelta(microseconds=1)
        vid = stamp.strftime("%Y%m%dT%H%M%S.%fZ")
    return t, vid


def _item_of(data: bytes, fallback: str | None) -> str | None:
    """The item the page's own link names, `fallback` when it names none (a page moved in, an old version without an item)."""
    found = _page.item_link(data.decode("utf-8", "replace"), board()) if board() else None
    return _norm_id(f"board#{found}") if found is not None else fallback


def _highest_folder() -> int:
    return max((int(p.name) for p in _c.root().iterdir() if p.is_dir() and re.fullmatch(_c.NUMBER, p.name)), default=0) if _c.root().is_dir() else 0


def _save(rec: dict[str, Any], data: bytes | None, high: int | None = None) -> None:
    """Write the bytes, the counter (a number is taken before anything can be seen under it) and then the record; the caller holds the lock."""
    number = rec["number"]
    if data is not None:
        blob = _c.root() / str(number) / f"{hashlib.sha256(data).hexdigest()}.html"
        if _c._file(blob, _c.MAX_BYTES) != data:
            _c._write(blob, data)
    if high is not None and high > _c.counter():
        _c._write(_c.root() / "counter", f"{high}\n".encode("ascii"))
    _c._write(_c.root() / str(number) / "canvas.json", (json.dumps(rec, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def _entry(data: bytes, when: float, session: str) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "modified": when, "session": session}


def _writes(what: str) -> None:
    try:
        _ro.guard(what)
    except _ro.ReadOnlyError as e:
        raise _refuse(str(e)) from None
    if not write_on():
        raise _refuse(WRITE_OFF)


def add(text: str, title: str = "", session: str = "") -> tuple[int, str, list[str]]:
    """A new canvas: (its number, "added", the notices)."""
    _writes("a canvas write")
    data, name, item = _checked(text, title)
    who = _c._text(session, "session", _c.SESSION_MAX)
    notices = _notices(text, item)
    try:
        with _c._LOCK:
            number = max(_c.counter(), _highest_folder()) + 1
            when = time.time()
            rec = {**_EMPTY, "number": number, "title": name, "item": item, "current": _entry(data, when, who), "versions": []}
            _save(rec, data, high=number)
    except _c.Unreadable as e:
        raise _refuse(f"{e}: nothing written over it") from None
    print(f"canvas {number}: added by {who or 'a session'}", flush=True)
    return number, "added", notices


def update(number: Any, text: str, title: str = "", session: str = "") -> tuple[int, str, list[str]]:
    """A revision of canvas `number`: (its number, "replaced" or "unchanged", the notices)."""
    _writes("a canvas write")
    number = _number(number)
    data, name, item = _checked(text, title)
    who = _c._text(session, "session", _c.SESSION_MAX)
    notices = _notices(text, item)
    with _c._LOCK:
        rec = _read(number)
        old = rec["current"]
        if old is None:
            raise _refuse(f"canvas {number} has no current page yet: nothing to revise")
        when, vid = _now(rec)
        entry = _entry(data, when, who)
        if entry["sha256"] == old["sha256"]:
            result = "unchanged"
            changed = (name and name != rec["title"]) or item != rec["item"]
            rec.update({"title": name or rec["title"], "item": item})
            if changed:
                _save(rec, None)
        else:
            result = "replaced"
            rec["versions"] = [*rec["versions"], {"id": vid, **old, "title": rec["title"], "item": rec["item"]}]
            rec.update({"title": name or rec["title"], "item": item, "current": entry})
            _save(rec, data)
    print(f"canvas {number}: {result} by {who or 'a session'}", flush=True)
    return number, result, notices


def undo(number: Any, session: str = "") -> tuple[int, str, list[str]]:
    """The newest version of canvas `number` is its page again: (its number, "restored <id>", [])."""
    _writes("a canvas write")
    number = _number(number)
    who = _c._text(session, "session", _c.SESSION_MAX)
    with _c._LOCK:
        rec = _read(number)
        if not rec["versions"]:
            raise _refuse(f"canvas {number} has no earlier version to restore")
        back = max(rec["versions"], key=lambda v: v["id"])
        try:
            data = _c.page(number, back)
        except _c.Unreadable as e:
            raise _refuse(f"{e}: nothing written over it") from None
        if data is None:
            raise _refuse(f"the bytes of version {back['id']} of canvas {number} are not on disk: nothing changed")
        when, vid = _now(rec)
        old = rec["current"]
        rec["versions"] = [v for v in rec["versions"] if v["id"] != back["id"]]
        if old is not None:
            rec["versions"].append({"id": vid, **old, "title": rec["title"], "item": rec["item"]})
        # the record's title and item go back with the page: the ones saved with the version, else the item the page's own link names
        rec["title"] = back["title"] if isinstance(back.get("title"), str) else rec["title"]
        rec["item"] = back["item"] if "item" in back and (back["item"] is None or isinstance(back["item"], str)) else _item_of(data, rec["item"])
        rec["current"] = _entry(data, when, who or str(back.get("session") or ""))
        _save(rec, data)
    print(f"canvas {number}: restored {back['id']} by {who or 'a session'}", flush=True)
    return number, f"restored {back['id']}", []


def history(number: Any) -> list[dict[str, Any]]:
    """The versions of canvas `number`, newest first."""
    rec = _read(_number(number))
    return sorted(rec["versions"], key=lambda v: v["id"], reverse=True)


def listing() -> list[dict[str, Any]]:
    """Every canvas with a current page, in number order, as {number, title, bytes, modified}; a record that cannot be read is left out."""
    out = []
    for n in sorted(int(p.name) for p in (_c.root().iterdir() if _c.root().is_dir() else []) if p.is_dir() and re.fullmatch(_c.NUMBER, p.name)):
        try:
            rec = _c.read(n)
        except _c.Unreadable:
            continue
        if rec and rec["current"]:
            out.append({"number": n, "title": rec["title"], "bytes": rec["current"].get("bytes", 0), "modified": rec["current"]["modified"]})
    return out
