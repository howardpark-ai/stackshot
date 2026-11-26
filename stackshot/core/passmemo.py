"""passmemo.py: what one pass of the minute set works out once.

A pass looks at every open item, and a look at one item asks for things that do not depend on the item: every session's role, the session registry, the fleet's session rows. Asked again
for each item they were recomputed from the files each time, which was most of the minute set's work. Inside `scope()` such a value is computed once and handed to the rest of the pass.

    with passmemo.scope():                  # the runner opens one around each tick; a pass called on its own opens its own, and so does a read that looks at every open item (service/client_reads.py)
        ...
        roles = passmemo.once("roles", build, stamp=files_stamp)

* The memo belongs to the thread that opened the scope and ends with it, so nothing outlives a pass. Outside a scope `once` just calls `build`, as before.
* `stamp` (a function) is asked at every lookup, before the value is built or reused: a value is reused only while the stamp is the one it was built under. A value that reads files gives the
  files' stamps (`filecache.stamp`), so a file written in the middle of the pass is seen by the next call. A value that reads no file leaves it out and holds for the pass.
* A scope inside a scope is the outer one. A thread started by a pass has no scope and works as it did.

Standard library only: every layer may import it."""
from __future__ import annotations

import contextlib
import threading
from typing import Any, Callable, Hashable, Iterator

_LOCAL = threading.local()


@contextlib.contextmanager
def scope() -> Iterator[None]:
    """Open the memo of one pass in this thread (the one already open when there is one); it ends with the block, whatever way the block ends."""
    if getattr(_LOCAL, "memo", None) is not None:
        yield
        return
    _LOCAL.memo = {}
    try:
        yield
    finally:
        _LOCAL.memo = None


def active() -> bool:
    """Is a pass memo open in this thread?"""
    return getattr(_LOCAL, "memo", None) is not None


def once(key: Hashable, build: Callable[[], Any], stamp: "Callable[[], Hashable] | None" = None) -> Any:
    """The value `build()` gives, computed once per pass for `key` and stamp (see the module text); `build()` itself outside a scope. The value is shared by the pass: a caller that changes it copies it first."""
    memo = getattr(_LOCAL, "memo", None)
    if memo is None:
        return build()
    st = stamp() if stamp is not None else None       # taken before the build: a file written during it makes the next lookup build again
    hit = memo.get(key)
    if hit is not None and hit[0] == st:
        return hit[1]
    val = build()
    memo[key] = (st, val)
    return val
