"""memo_files.py: the files a person attaches to a note on an item (the memo box): where they are kept, the limits, the upload, the move of a file to its item, the words that name one and the sweep.

The files are in the state folder (`<paths.state>/memo-files`), never in the item store: the store is pushed to a git repository by the publisher, and a file there would be published. The state folder is
what the 5-minute standby copy and the daily backup carry, so the files travel with them. The folder is never named `site`, `tmp` or `search` (the standby copy leaves those out) nor `backup-*`.

    pending/<item id>/<32 hex>/<safe name>     uploaded, not sent yet: swept after 24 hours (tools/memo_files_clean.py)
    <item id>/<32 hex>/<safe name>             sent with a note: kept until 30 days after the item closed (and 30 days after the file was stored)

While a file is being uploaded it is `upload.tmp` in its folder: the standby copy leaves every `*.tmp` out, so a file that is still growing can never make a copy keep changing under the locks. A name that
would end in `.tmp` or `.lock` once stored gets `.bin` after it, for the same reason (the copy leaves those names out everywhere).

The limits are the constants below (one block). An upload is streamed to disk in pieces and is never held whole; it is refused as soon as its size passes the limit, by the declared Content-Length first. The 100 MB
total counts every file on the server together, the uploads not yet sent too, and is checked again under a lock when an upload is whole, so two uploads that arrive together cannot pass it.

A module of the service layer: it reads the config and the file system only (no item, no lock of the store). An item's record of its files is `metadata.answers[].files`: [{id, name, size, type}], written by service/answer.py."""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

MAX_FILE = 10 * 1024 * 1024          # bytes of one file
MAX_IMAGE = 5 * 1024 * 1024          # bytes of an image (png, jpeg, gif, webp by its first bytes): kept as uploaded, photo location data included, so a bigger one is refused, not shrunk
MAX_FILES = 4                        # files on one note
MAX_TOTAL = 100 * 1024 * 1024        # bytes of every memo file on the server together, pending ones included
PENDING_PER_ITEM = 8                 # uploads waiting for a send, per item (a chip taken off in the page leaves its upload behind until the sweep)
NAME_CHARS = 120
NAME_BYTES = 240                     # a file name is at most 255 bytes on disk
PENDING_HOURS = 24
KEEP_DAYS = 30
PIECE = 1 << 20                      # bytes written at a time
PARTIAL = "upload.tmp"
ROOT_NAME = "memo-files"
PENDING = "pending"

_ID = re.compile(r"[0-9a-f]{32}")
_GID = re.compile(r"[a-z][0-9]+")
_KEEP_CHARS = " ._-()+,@=#"
_QUOTA_LOCK = threading.Lock()


class Refused(Exception):
    """An upload or a send of files that is not taken: `status` is the HTTP status the route answers with and the message is the sentence it says."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def mb(n: int) -> str:
    return f"{n / (1 << 20):g} MB"


def size_words(n: int) -> str:
    """A size as a person reads it: 900 B, 12 KB, 3.4 MB."""
    if n < 1024:
        return f"{n} B"
    if n < 1 << 20:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1 << 20):.1f} MB"


def root() -> Path:
    return _cfg.state(ROOT_NAME)


def valid_id(s: Any) -> bool:
    return isinstance(s, str) and bool(_ID.fullmatch(s))


def valid_gid(s: Any) -> bool:
    return isinstance(s, str) and bool(_GID.fullmatch(s))


def safe_name(name: Any) -> str:
    """A file name that is safe to keep and to put in a header: no directory part (either slash), no control character, only letters, digits and ` ._-()+,@=#` (any script's letters stay), never a leading dot or space,
    at most NAME_CHARS characters and NAME_BYTES bytes (the end kept, so the extension stays), `file` when nothing is left. A name the standby copy would leave out (`*.tmp`, `*.lock`) gets `.bin` after it."""
    s = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    s = "".join(c if (c.isalnum() or c in _KEEP_CHARS) and c.isprintable() else "_" for c in s)
    s = s.strip(" .")
    while len(s) > NAME_CHARS or len(s.encode("utf-8")) > NAME_BYTES:
        stem, dot, ext = s.rpartition(".")
        if dot and 0 < len(ext) <= 12 and stem:
            s = stem[:-1] + "." + ext
        else:
            s = s[:-1]
    s = s.strip(" .") or "file"
    if s.lower().endswith((".tmp", ".lock")) or s.lower() in ("lock", ".lock"):
        s += ".bin"
    return s


def sniff(head: bytes) -> str:
    """The image type of a file's first bytes: image/png, image/jpeg, image/gif or image/webp; "" for anything else (SVG included: it can carry a script, so it is a download like any other file)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _inside(path: Path) -> bool:
    return path.resolve().is_relative_to(root().resolve())


def total_bytes() -> int:
    """Every byte under the memo-files folder (a partial upload counts)."""
    n = 0
    for dirpath, _dirs, files in os.walk(root()):
        for f in files:
            try:
                n += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return n


def _pending_dir(gid: str) -> Path:
    return root() / PENDING / gid


def _single(folder: Path) -> Path | None:
    """The stored file of an id's folder: its one file that is not the partial upload; None when there is none."""
    try:
        names = [e for e in os.listdir(folder) if e != PARTIAL]
    except OSError:
        return None
    if len(names) != 1:
        return None
    p = folder / names[0]
    return p if p.is_file() and not p.is_symlink() else None


class Upload:
    """One upload in progress: `write` the pieces, then `finish`; `abort` (always, in a `finally`) removes whatever is left of it."""

    def __init__(self, gid: str, name: str, declared: int | None) -> None:
        self.gid, self.name = gid, safe_name(name)
        self.id = uuid.uuid4().hex
        self.dir = _pending_dir(gid) / self.id
        self.size = 0
        self.kind = ""
        self.head = b""
        self.limit = MAX_FILE
        self.base = 0
        self.fd = -1
        self.done = False
        if declared is not None and declared > MAX_FILE:
            raise Refused(413, f"files are limited to {mb(MAX_FILE)}")
        self.base = total_bytes()
        if declared is not None and self.base + declared > MAX_TOTAL:
            raise Refused(507, f"the memo files on the server are full ({mb(MAX_TOTAL)} in all); ask for room to be made")
        waiting = len(os.listdir(_pending_dir(gid))) if _pending_dir(gid).is_dir() else 0
        if waiting >= PENDING_PER_ITEM:
            raise Refused(400, f"{waiting} files wait to be sent on this item; send the note first")
        self.declared = declared
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.dir / PARTIAL, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(self.head) < 16:
            self.head += chunk[: 16 - len(self.head)]
            if len(self.head) >= 12 and not self.kind:
                self.kind = sniff(self.head)
                if self.kind:
                    self.limit = MAX_IMAGE
                    if self.declared is not None and self.declared > MAX_IMAGE:
                        raise Refused(413, f"images are limited to {mb(MAX_IMAGE)}")
        if self.size + len(chunk) > self.limit:
            raise Refused(413, f"images are limited to {mb(MAX_IMAGE)}" if self.kind else f"files are limited to {mb(MAX_FILE)}")
        if self.base + self.size + len(chunk) > MAX_TOTAL:
            raise Refused(507, f"the memo files on the server are full ({mb(MAX_TOTAL)} in all); ask for room to be made")
        view = memoryview(chunk)
        while view:
            n = os.write(self.fd, view)
            view = view[n:]
        self.size += len(chunk)

    def finish(self) -> dict[str, Any]:
        """The upload is whole: its record {id, name, size, type}. Refused when the file is empty, or when with it the folder is over the total."""
        if self.size == 0:
            raise Refused(400, "the file is empty")
        if not self.kind:      # fewer than 12 bytes: no image
            self.kind = sniff(self.head)
        if self.kind and self.size > MAX_IMAGE:
            raise Refused(413, f"images are limited to {mb(MAX_IMAGE)}")
        os.close(self.fd)
        self.fd = -1
        with _QUOTA_LOCK:
            if total_bytes() > MAX_TOTAL:
                raise Refused(507, f"the memo files on the server are full ({mb(MAX_TOTAL)} in all); ask for room to be made")
            os.rename(self.dir / PARTIAL, self.dir / self.name)
        self.done = True
        return {"id": self.id, "name": self.name, "size": self.size, "type": "image" if self.kind else "file"}

    def abort(self) -> None:
        """Remove the upload's folder unless it was finished (a refused, failed or dropped upload leaves nothing)."""
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if not self.done:
            shutil.rmtree(self.dir, ignore_errors=True)
            try:
                os.rmdir(_pending_dir(self.gid))      # only when it is empty
            except OSError:
                pass


def records(gid: str, ids: list[str]) -> list[dict[str, Any]]:
    """The records {id, name, size, type} of the pending files `ids` of item `gid`, in that order. Refused (400) for more than MAX_FILES, an id twice, an id that is not 32 hex, or one that is not waiting on this item."""
    if len(ids) > MAX_FILES:
        raise Refused(400, f"at most {MAX_FILES} files go with one note")
    if len(set(ids)) != len(ids):
        raise Refused(400, "the same file is named twice")
    out = []
    for i in ids:
        f = _single(_pending_dir(gid) / i) if valid_id(i) and valid_gid(gid) else None
        if f is None or not _inside(f):
            raise Refused(400, "a file of this note is not there any more; attach it again")
        with open(f, "rb") as fh:
            kind = sniff(fh.read(16))
        out.append({"id": i, "name": f.name, "size": f.stat().st_size, "type": "image" if kind else "file"})
    return out


def commit(gid: str, recs: list[dict[str, Any]]) -> None:
    """Move the files of `recs` (from `records`) from pending to the item: once its note is recorded. A file that cannot be moved is said on stderr (the note stands)."""
    for r in recs:
        src, dst = _pending_dir(gid) / r["id"], root() / gid / r["id"]
        try:
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.rename(src, dst)
        except OSError as e:
            import sys
            print(f"memo files: {gid} {r['id']} not moved: {e.__class__.__name__}", file=sys.stderr, flush=True)
    try:
        os.rmdir(_pending_dir(gid))
    except OSError:
        pass


def words(files: Any) -> str:
    """The files of a note in one line: `a.png (1.2 MB), b.txt (1 KB)`."""
    if not isinstance(files, list):
        return ""
    return ", ".join(f"{f['name']} ({size_words(int(f.get('size') or 0))})" for f in files if isinstance(f, dict) and f.get("name"))


def listing(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Every file recorded on an item's answers, oldest first."""
    out = []
    for a in (item.get("metadata") or {}).get("answers") or []:
        if isinstance(a, dict) and isinstance(a.get("files"), list):
            out += [f for f in a["files"] if isinstance(f, dict) and valid_id(f.get("id"))]
    return out


def path_of(gid: str, item: dict[str, Any], fid: str) -> tuple[Path, dict[str, Any]] | None:
    """The stored file `fid` of `item` and its record, or None: the id is not on the item's list, the file is gone, or its path leaves the folder."""
    if not valid_gid(gid) or not valid_id(fid):
        return None
    rec = next((f for f in listing(item) if f["id"] == fid), None)
    if rec is None:
        return None
    p = _single(root() / gid / fid)
    if p is None or not _inside(p):
        return None
    return p, rec


def delete_for(gid: str) -> bool:
    """Remove every file of item `gid` (its whole folder). → whether there was one."""
    if not valid_gid(gid):
        return False
    d = root() / gid
    if not d.is_dir() or not _inside(d):
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def newest(path: Path) -> float:
    """The latest modification time of a folder and what is in it."""
    t = os.lstat(path).st_mtime
    for dirpath, dirs, files in os.walk(path):
        for n in (*dirs, *files):
            try:
                t = max(t, os.lstat(os.path.join(dirpath, n)).st_mtime)
            except OSError:
                pass
    return t


def sweep(closed_at: Any, now: float | None = None, dry_run: bool = False) -> dict[str, Any]:
    """The daily pass: remove the folders of items closed KEEP_DAYS ago (and whose files are KEEP_DAYS old too) and the uploads pending for PENDING_HOURS. `closed_at(gid)` → the time the item closed (epoch), 0 for an item that is
    open, unreadable or unknown (its files stay: a file is never removed on a doubt). → {"items": [gid…], "pending": [path…], "bytes": the folder's size after, "kept": n items with files}."""
    now = time.time() if now is None else now
    out: dict[str, Any] = {"items": [], "pending": [], "bytes": 0, "kept": 0}
    base = root()
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if d.name == PENDING or not d.is_dir() or d.is_symlink() or not valid_gid(d.name):
            continue
        closed = float(closed_at(d.name) or 0)
        if closed and now - closed >= KEEP_DAYS * 86400 and now - newest(d) >= KEEP_DAYS * 86400 and _inside(d):
            out["items"].append(d.name)
            if not dry_run and float(closed_at(d.name) or 0):      # read again just before the removal: a reopened item keeps its files
                shutil.rmtree(d, ignore_errors=True)
        else:
            out["kept"] += 1
    pend = base / PENDING
    if pend.is_dir():
        for g in sorted(pend.iterdir()):
            if not g.is_dir() or g.is_symlink():
                continue
            for u in sorted(g.iterdir()):
                if u.is_dir() and not u.is_symlink() and now - newest(u) >= PENDING_HOURS * 3600 and _inside(u):
                    out["pending"].append(f"{PENDING}/{g.name}/{u.name}")
                    if not dry_run:
                        shutil.rmtree(u, ignore_errors=True)
            if not dry_run:
                try:
                    os.rmdir(g)
                except OSError:
                    pass
    out["bytes"] = total_bytes()
    return out
