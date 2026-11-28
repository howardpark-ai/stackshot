"""canvas.py: canvases, the pages an agent shares with the board's owner: where they are served, how they are kept, and `POST /client/canvas-import`, the one way a page gets in (docs/canvas.md).

A canvas has a number, a current page and versions (the pages the current one replaced, each under an id that is the time it was replaced). Nothing here writes a page of its own: until the board
creates and edits canvases itself, they come from the import, which keeps another store's numbers, version ids, bytes and times.

The store, `<paths.state>/canvas/` (the board's state folder, outside git; the standby copy takes it whole, under the lock `canvas`):

    counter                 the highest number ever given here, as text; a new number comes after it and after the highest folder
    <number>/canvas.json    the record: {"schema": 1, "number", "title", "item" (the store's id, or null), "current": {"sha256", "bytes", "modified", "session"} or null,
                            "versions": [{"id", "sha256", "bytes", "modified", "session", and for a version a revision or an undo made: "title", "item" (the record's, as the page had them)}, ...] oldest first}
    <number>/<sha256>.html  one page's bytes, written once under their own hash

A file is written whole to a temporary file beside it, flushed to disk and renamed over the old one, and the record is written after the bytes it names, so a reader (which takes no lock) sees a page that is
all there or the one before it. Nothing is ever removed: bytes a record no longer names stay on disk.

The import takes one page a call, `{"number", "version" (null for the current page, else the version's id), "content" (base64), "bytes", "sha256", "modified" (epoch seconds)}` and, each optional,
`"session"` (who wrote it), `"counter"` (the highest number the sending store ever gave) and, with the current page only, `"title"` and `"item"`. It answers `{"ok": true, "number", "version", "result",
"sha256"}`, `result` one of added | unchanged | updated | replaced. A rerun is safe: the same content is skipped unless the call's time is newer (then the record takes its time and what it sends), different
content replaces the current page only when its time is newer, and a version never changes. Everything is checked before anything is written. It is off unless `[canvas] import` is true.

A service module: it imports core and the model only. The routes that serve a canvas are web/routes/canvas.py, the headers they leave with web/canvas_guard.py."""
from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import xlock as _xlock
from stackshot.model.ids import _norm_id

PATH = "/canvas"                      # the one place the address is written: <board>/canvas/<number>[/versions/<id>], and /raw after either for the page itself
VERB = "canvas-import"                # the /client/<verb> of the import
SCHEMA = 1
MAX_BYTES = 5 * 1024 * 1024           # one page
MAX_BODY = MAX_BYTES * 4 // 3 + 65536     # one import call: a page of MAX_BYTES in base64 and the fields around it
RECORD_MAX = 4 * 1024 * 1024          # a record is read no further than this
TITLE_MAX, SESSION_MAX = 200, 100
NUMBER = r"[1-9][0-9]{0,9}"
VERSION_ID = r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z"
_KEYS = frozenset(("number", "version", "content", "bytes", "sha256", "modified", "title", "item", "session", "counter"))
OFF = "refused: the canvas import is off ([canvas] import = false). The operator turns it on to move pages in and off after"
_LOCK = _xlock.XLock("canvas")        # round the read, change and writes of one import; outside the lock order: nothing else is taken while it is held


class Unreadable(RuntimeError):
    """A record that is there and cannot be read as one: nothing is served from it and nothing is written over it."""


class _Refused(ValueError):
    def __init__(self, why: str, status: int = 400):
        super().__init__(why)
        self.status = status


def root() -> Path:
    return _cfg.state("canvas")


def version_time(version: str) -> datetime.datetime | None:
    """The moment a version id names, None when `version` is no id."""
    if not re.fullmatch(VERSION_ID, str(version or "")):
        return None
    try:
        return datetime.datetime.strptime(version, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _file(path: Path, limit: int) -> bytes | None:
    """The bytes of a regular file of at most `limit` bytes, opened without following a link; None when there is no such file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise Unreadable(f"{path} is not a regular file")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise Unreadable(f"{path} is over {limit} bytes")
    return data


def read(number: int) -> dict[str, Any] | None:
    """The record of canvas `number`, None when the store has none; Unreadable when the file there is no record of it."""
    path = root() / str(int(number)) / "canvas.json"
    raw = _file(path, RECORD_MAX)
    if raw is None:
        return None
    try:
        rec = json.loads(raw.decode("utf-8"))
        ok = (rec["schema"] == SCHEMA and rec["number"] == int(number) and isinstance(rec["title"], str) and (rec["item"] is None or isinstance(rec["item"], str))
              and (rec["current"] is None or _is_page(rec["current"])) and all(_is_page(v) and version_time(v["id"]) for v in rec["versions"]))
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise Unreadable(f"{path} is not a canvas record")
    return rec


def _is_page(p: Any) -> bool:
    return isinstance(p, dict) and bool(re.fullmatch(r"[0-9a-f]{64}", str(p.get("sha256") or ""))) and isinstance(p.get("modified"), (int, float))


def page(number: int, entry: dict[str, Any]) -> bytes | None:
    """The bytes a record's page entry names, None when they are not on disk."""
    return _file(root() / str(int(number)) / f"{entry['sha256']}.html", MAX_BYTES)


def counter() -> int:
    """The highest number the store says was ever given, 0 for none."""
    raw = _file(root() / "counter", 64)
    if raw is None:
        return 0
    text = raw.decode("ascii", "replace").strip()
    if not re.fullmatch(NUMBER, text):
        raise Unreadable(f"{root() / 'counter'} holds no number")
    return int(text)


def _write(path: Path, data: bytes) -> None:
    """Write `path` whole: a temporary file beside it, flushed to disk, renamed over it, and the folder flushed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def too_large(length: Any) -> str:
    """The refusal (one line) for a body of `length` bytes (an int, or a Content-Length header's text), "" when it is within `MAX_BODY` or cannot be read as a length."""
    try:
        n = int(length)
    except (TypeError, ValueError):
        return ""
    return f"the body is {n} bytes, over the {MAX_BODY}-byte limit" if n > MAX_BODY else ""


def import_on() -> bool:
    """[canvas] import (default false): only a true written as TOML's true turns it on."""
    return _cfg.get("canvas", "import", default=False) is True


def _whole(v: Any, name: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not re.fullmatch(NUMBER, str(v)):
        raise _Refused(f"{name} is a whole number from 1, of at most 10 digits")
    return v


def _text(v: Any, name: str, most: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise _Refused(f"{name} is text")
    out = " ".join("".join(c if c.isprintable() else " " for c in v).split())
    if len(out) > most:
        raise _Refused(f"{name} is at most {most} characters")
    return out


def _checked(body: dict[str, Any]) -> tuple[int, str | None, bytes, dict[str, Any], dict[str, Any]]:
    """The call's number, version id, bytes, page entry and extra fields (title, item, counter), every one checked; _Refused for the first that does not hold."""
    unknown = sorted(str(k)[:40] for k in set(body) - _KEYS)
    if unknown:
        raise _Refused("unknown: " + ", ".join(unknown[:5]))
    number = _whole(body.get("number"), "number")
    if "version" not in body:
        raise _Refused("version = null for the current page, or the version's id")
    version = body["version"]
    if version is not None and (not isinstance(version, str) or version_time(version) is None):
        raise _Refused("version is null or an id of the form 20260101T000000.000000Z")
    content = body.get("content")
    if not isinstance(content, str):
        raise _Refused("content is the page's bytes in base64")
    try:
        data = base64.b64decode(content.encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        raise _Refused("content is not base64") from None
    if not data:
        raise _Refused("the page is empty")
    if len(data) > MAX_BYTES:
        raise _Refused(f"the page is {len(data)} bytes, over the {MAX_BYTES}-byte limit", 413)
    if b"\0" in data:
        raise _Refused("the page holds a NUL byte")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Refused("the page is not UTF-8") from None
    size, digest = body.get("bytes"), hashlib.sha256(data).hexdigest()
    if not isinstance(size, int) or isinstance(size, bool) or size != len(data):
        raise _Refused(f"bytes does not match the content, which is {len(data)} bytes")
    if body.get("sha256") != digest:
        raise _Refused("sha256 does not match the content")
    modified = body.get("modified")
    if not isinstance(modified, (int, float)) or isinstance(modified, bool) or not 0 <= modified < 1e11 or not math.isfinite(modified):
        raise _Refused("modified is the page's time in epoch seconds")
    entry = {"sha256": digest, "bytes": len(data), "modified": modified, "session": _text(body.get("session"), "session", SESSION_MAX)}
    if version is not None and ("title" in body or "item" in body):
        raise _Refused("title and item go with the current page (version null)")
    extra: dict[str, Any] = {}
    title = _text(body.get("title"), "title", TITLE_MAX)
    if title:
        extra["title"] = title
    item = body.get("item")
    if item is not None:
        if not isinstance(item, str):
            raise _Refused("item is an item's id, as text")
        try:
            extra["item"] = _norm_id(item)
        except ToolError as e:
            raise _Refused(str(e)[:200]) from None
    if body.get("counter") is not None:
        extra["counter"] = _whole(body["counter"], "counter")
    return number, version, data, entry, extra


def _store(number: int, version: str | None, data: bytes, entry: dict[str, Any], extra: dict[str, Any]) -> str:
    """Put one checked page in the store (the caller holds the lock) and say what happened; _Refused, with nothing written, for content that may not replace what is there."""
    rec = read(number) or {"schema": SCHEMA, "number": number, "title": "", "item": None, "current": None, "versions": []}
    high = max(counter(), number, extra.get("counter", 0))
    changed = True
    if version is None:
        old = rec["current"]
        fields = {k: extra[k] for k in ("title", "item") if k in extra}
        if old is None:
            result = "added"
        elif entry["modified"] > old["modified"]:
            result = "updated" if entry["sha256"] == old["sha256"] else "replaced"
        elif entry["sha256"] == old["sha256"]:
            result, changed = "unchanged", False
        else:
            raise _Refused(f"canvas {number} holds a different page that is as new or newer: not replaced", 409)
        if changed:
            rec.update(fields, current=entry)
    else:
        old = next((v for v in rec["versions"] if v["id"] == version), None)
        if old is None:
            result = "added"
            rec["versions"] = sorted([*rec["versions"], {"id": version, **entry}], key=lambda v: v["id"])
        elif entry["sha256"] == old["sha256"]:
            result, changed = "unchanged", False
        else:
            raise _Refused(f"canvas {number} holds a different page as version {version}: a version never changes", 409)
    blob = root() / str(number) / f"{entry['sha256']}.html"
    if _file(blob, MAX_BYTES) != data:       # a rerun repairs bytes that are missing or damaged
        _write(blob, data)
    if high > counter():                     # before the record: a number is taken before anything can be seen under it
        _write(root() / "counter", f"{high}\n".encode("ascii"))
    if changed:
        _write(root() / str(number) / "canvas.json", (json.dumps(rec, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return result


def post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`POST /client/canvas-import` -> (status, JSON). `machine` is the token's."""
    _ro.guard("the canvas import")
    if not import_on():
        return 403, {"error": OFF}
    try:
        number, version, data, entry, extra = _checked(body)
        with _LOCK:
            result = _store(number, version, data, entry, extra)
    except _Refused as e:
        return e.status, {"error": str(e)}
    except Unreadable as e:
        return 409, {"error": f"{e}: nothing written over it"}
    print(f"canvas {number}{' version ' + version if version else ''}: {result} by the import ({machine})", flush=True)
    return 200, {"ok": True, "number": number, "version": version, "result": result, "sha256": entry["sha256"]}
