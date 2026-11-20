"""filecache.py: a file that is read often is read and parsed again only when it changed.

`read_json(path)` gives the parsed JSON of a file. The parse is kept under the file's stamp (`stamp`: modification time in nanoseconds, size and inode), so a second look at a file that was
not written costs one stat, not an open and a parse; a file written in between (an atomic rewrite brings a new inode, an in-place one a new time or size) is read again at once. A read
that fails is never kept: the error is the caller's, as with `json.load`, and the next call tries again.

One case is never kept: a file whose stamp is younger than `FRESH_NS`. A clock that ticks in coarse steps can give two writes of the same size one stamp, so a file written a moment ago may
still change without its stamp moving; it is read again on each call until it has aged past the window, then kept.

The object it returns is shared with every other caller of the same file: a caller that changes it takes a copy first (`copy.deepcopy`). Standard library only: every layer may import it."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

FRESH_NS = 200_000_000          # a file written less than this long ago is not kept (see the text above)
MAX_FILES = 2048                # the most files kept; past it the oldest keep goes
_LOCK = threading.Lock()
_KEPT: dict[str, tuple[tuple[int, int, int], Any]] = {}


def stamp(path: "str | os.PathLike[str]") -> "tuple[int, int, int] | None":
    """(mtime_ns, size, inode) of a file; None when it cannot be looked at (absent, no right to it)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def read_json(path: "str | os.PathLike[str]") -> Any:
    """The parsed JSON of the file, as `json.load` gives it (its errors too). Shared and not to be changed by the caller (see the module text)."""
    key = os.fspath(path)
    now = stamp(key)
    if now is not None:
        with _LOCK:
            hit = _KEPT.get(key)
        if hit is not None and hit[0] == now:
            return hit[1]
    with open(key, encoding="utf-8") as f:
        val = json.load(f)
    if now is not None and stamp(key) == now and time.time_ns() - now[0] > FRESH_NS:        # not written while it was read, and old enough that a later write must move its time
        with _LOCK:
            if len(_KEPT) >= MAX_FILES and key not in _KEPT:
                _KEPT.pop(next(iter(_KEPT)), None)
            _KEPT[key] = (now, val)
    return val


def forget() -> None:
    """Drop everything kept (a test's reset)."""
    with _LOCK:
        _KEPT.clear()
