"""filecache.py: a file that is read often is read and parsed again only when it changed.

`read_json(path)` gives the parsed JSON of a file. The parse is kept under the file's stamp (`stamp`: modification time in nanoseconds, size and inode), so a second look at a file that was
not written costs one stat, not an open and a parse; a file written in between (an atomic rewrite brings a new inode, an in-place one a new time or size) is read again at once. A read
that fails is never kept: the error is the caller's, as with `json.load`, and the next call tries again.

One case is never kept: a file whose stamp is younger than `FRESH_NS`. A clock that ticks in coarse steps can give two writes of the same size one stamp, so a file written a moment ago may
still change without its stamp moving; it is read again on each call until it has aged past the window, then kept.

The object it returns is shared with every other caller of the same file: a caller that changes it takes a copy first (`copy.deepcopy`).

`derived(name, files, token, build)` keeps what is worked out from several files (and from settings, the `token`) the same way: under the stamps of the files, so it is built again only when one was written. The same
FRESH_NS rule decides what is kept (a coarse clock is the one assumption: a write always moves a file's time by more than FRESH_NS, or its size or inode), and a writer in this process may `drop` it at once.
Standard library only: every layer may import it."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Hashable, Iterable

FRESH_NS = 200_000_000          # a file written less than this long ago is not kept (see the text above)
MAX_FILES = 2048                # the most files kept; past it the oldest keep goes
_LOCK = threading.Lock()
_KEPT: dict[str, tuple[tuple[int, int, int], Any]] = {}
_DERIVED: dict[Hashable, tuple[Hashable, tuple, Any]] = {}     # name -> (token, the files' stamps, the value built under them)
_GEN = [0]                                                     # counts the drops: a value built while one happened is not kept


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


def derived(name: Hashable, files: "Iterable[str | os.PathLike[str]]", token: Hashable, build: Callable[[], Any]) -> Any:
    """What `build()` gives, kept under `name` while `token` (what else it reads: a path, a setting) and the stamps of `files` (an absent file has the stamp None) are as they were when it was built. A
    stamp is taken before the build and again after it, and a value is kept only when the two agree, no file is younger than FRESH_NS (the rule of `read_json`: its one assumption about the clock) and no
    `drop` came in between. `build` that raises keeps nothing. The value is shared by every caller: a caller that changes it takes a copy first."""
    paths = [os.fspath(f) for f in files]
    before = tuple(stamp(p) for p in paths)
    with _LOCK:
        hit = _DERIVED.get(name)
        gen = _GEN[0]
    if hit is not None and hit[0] == token and hit[1] == before:
        return hit[2]
    val = build()
    now = time.time_ns()
    if tuple(stamp(p) for p in paths) == before and all(s is None or now - s[0] > FRESH_NS for s in before):
        with _LOCK:
            if _GEN[0] == gen:
                _DERIVED[name] = (token, before, val)
    return val


def drop(name: Hashable = None) -> None:
    """Forget what `derived` kept under `name` (all of it with no name): a writer of one of its files calls it at once, so this process never waits on a stamp to see its own write."""
    with _LOCK:
        _GEN[0] += 1
        if name is None:
            _DERIVED.clear()
        else:
            _DERIVED.pop(name, None)


def forget() -> None:
    """Drop everything kept (a test's reset)."""
    with _LOCK:
        _KEPT.clear()
        _DERIVED.clear()
        _GEN[0] += 1
