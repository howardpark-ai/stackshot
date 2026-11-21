"""xlock.py: a re-entrant lock that also keeps other processes out, for the stores a second process may write.

Every lock around a whole-file store (the item lock, the For you list, the Landed list, the held hand-back lines, the page-debt ledger, the pending answers, the machine anchors, the wake pass,
the stall record) was a thread lock, so it only ever kept the threads of one process from reading, changing and rewriting the same file at once. `XLock` keeps what those locks did and adds a flock on a
small file of its own in the state dir (`<paths.state>/<name>.lock`, never in the store, which is committed), so a second process that writes the same files takes turns with the server.

It is a drop-in for the `threading.RLock` it replaces: a context manager, `acquire(blocking=True, timeout=-1)`, `release()` and `_is_owned()`, re-entrant in a thread (a writer that holds it calls another that takes it again). In front of the flock sits a thread
lock of its own: a flock belongs to an open file description, and each hold opens its own, so the flock alone would also keep two threads of one process apart, but a thread that waits on the front lock does
not hold a descriptor, and a thread that already holds it nests with a counter instead of a second flock. A hold takes the front lock first and the flock second, and gives them back in the other order.
There is one `XLock` per name in a process (a second `XLock("item")` is the first): two instances on one file would each open their own descriptor and keep a thread out of its own lock.

A lock file left by a crashed holder is harmless: the flock goes with the process that held it, the file is only the name both sides lock on. The file is opened read-only (a flock needs no write access on a local
Linux filesystem, which the state dir is) and made when it is not there.

When the lock file cannot be had (the state dir unset or not writable, the file made by another user, no descriptor left) the answer depends on `strict`. A transient failure (no descriptor free) is tried again for a moment first.
With `strict` false (the default while the server is the only writer) the hold is the thread lock alone, as before, and a line on stderr says so on every such hold, at most one a minute for each lock. With `strict` true
(a later slice sets it when a second process writes) the hold raises `LockUnavailable`, naming the lock file and the error, because a hold that does not keep the other process out is a lost update waiting to happen.
A holder that never lets go is not waited on in silence: a waiter writes a line naming the lock after 30 seconds and again every 60 seconds; it never gives up on its own (a timed acquire gives up at its own deadline).
An acquire with no time limit blocks in the kernel's flock, so it is woken when the holder lets go (a poll would starve behind a holder that takes the lock again at once), and a watchdog thread, which holds nothing, writes the line; only a timed acquire polls.
The lock file is opened, with its retries, before the front lock is taken, so a pause there holds no other thread up. A filesystem that refuses a flock on a read-only descriptor (NFS) takes the same fallback as a lock file that cannot be had.

`[locks] cross_process = false` turns the flock off for the run (restart-only, config.RESTART_ONLY): every `XLock` is then its front thread lock and nothing else; so is every one on the read-only standby, which writes nothing.

Order. The locks that nest are always taken in one order, so two processes never wait on each other: the wake pass (`wake`) first, then the item lock (`item`), then the pending answers (`answers`), then
the For you list (`for-you`), the Landed list (`landed`) and the held hand-back lines (`handback-held`); the page-debt ledger (`ledger`) and the stall record (`stall`) are taken after the item lock, and the machine
anchors (`machine-anchors`) alone. No path takes the wake pass while it holds the item lock (the order is wake, then item; a recorder in tests/xlock_scenario.py fails on item before wake and on any pair taken in both orders). A new `XLock` that nests with these takes its place in that order and in docs/server-passes.md."""
from __future__ import annotations

import errno
import fcntl
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

strict = False                  # set nowhere yet: a later slice sets it (the minute passes in their own process) and decides what a pass does on LockUnavailable, an OSError subclass that a broad `except OSError` would swallow; then a lock file that cannot be had raises instead of falling back to the thread lock
FALLBACK_LOG_EVERY = 60.0       # seconds: one stderr line per lock for the holds that fell back
WAIT_LOG_FIRST = 30.0           # seconds a waiter waits before it says so, then every WAIT_LOG_EVERY
WAIT_LOG_EVERY = 60.0
_TRANSIENT = {errno.EMFILE, errno.ENFILE, errno.EINTR, errno.EAGAIN, errno.ENOMEM}      # the lock file is tried again for these, and not for a permission or a path that will not change
_RETRIES = 4
_RETRY_PAUSE = 0.025


class LockUnavailable(OSError):
    """The lock file of an XLock could not be had while `xlock.strict` is on: the hold is refused, not made on the thread lock alone."""


def enabled() -> bool:
    """[locks] cross_process, read at each first hold (the key is restart-only, so it stays as the process started with it): False only when it is set to false.
    The read-only standby never takes the flock either: it writes nothing, and its backstop refuses a lock file's creation."""
    return _cfg.get("locks", "cross_process", default=True) is not False and not _ro.is_read_only()


def _open(path: Path) -> int:
    """The lock file's descriptor, made when it is not there. One place, so a test can make it fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC, 0o644)


class XLock:
    """A re-entrant lock across threads (a thread lock in front) and processes (a flock on `<paths.state>/<name>.lock` behind it). One instance per name."""

    _by_name: dict[str, "XLock"] = {}
    _by_name_lock = threading.Lock()

    def __new__(cls, name: str) -> "XLock":
        with cls._by_name_lock:
            self = cls._by_name.get(name)
            if self is None:
                self = super().__new__(cls)
                self._ready = False
                cls._by_name[name] = self
            return self

    def __init__(self, name: str) -> None:
        if self._ready:
            return
        self.name = name
        self._t = threading.RLock()
        self._n = 0                      # how many times the thread that holds `_t` has taken it; only that thread reads or writes it
        self._fd: int | None = None      # the flock's descriptor while the outermost hold is held with the flock on
        self._said_at = 0.0              # when the last fallback line was written (the rate limit is best effort across threads: at worst one extra line)
        self._ready = True

    def path(self) -> Path:
        return _cfg.state(self.name + ".lock")

    def _fallback(self, why: BaseException, path: Any) -> tuple[bool, None]:
        """The lock file could not be had: with `strict` the hold is refused (naming the file and the error), else it is the thread lock alone and a line says so (at most one a minute for this lock)."""
        code = getattr(why, "errno", None)
        what = f"{path}: {why.__class__.__name__}: {why}" + (f" (errno {code} {errno.errorcode.get(code, '')})" if code else "")
        if strict:
            raise LockUnavailable(code or 0, f"xlock {self.name}: no lock file, and a second process may write this store: {what}") from why
        now = time.monotonic()
        if now - self._said_at >= FALLBACK_LOG_EVERY or not self._said_at:
            self._said_at = now
            print(f"xlock: {self.name}: no lock file, this hold keeps only this process's threads apart: {what}", file=sys.stderr, flush=True)
        return True, None

    def _fd_for(self) -> tuple[int | None, BaseException | None, Any]:
        """(descriptor, None, path) or (None, the error, path or None): the lock file opened, tried again for a moment on a transient failure."""
        p: Any = None
        for attempt in range(_RETRIES):
            try:
                p = self.path()
                return _open(p), None, p
            except OSError as e:
                if e.errno not in _TRANSIENT or attempt == _RETRIES - 1:
                    return None, e, p
            except Exception as e:      # noqa: BLE001  — the state path unset or unreadable (a KeyError, a ValueError): the same fallback as a file that cannot be had
                return None, e, p
            time.sleep(_RETRY_PAUSE)
        return None, None, p        # not reached

    def _lock_fd(self, fd: int, blocking: bool, deadline: float | None) -> bool:
        """LOCK_EX on `fd`: taken at once when free. Else a non-blocking try gives up at once (`blocking` false); a timed acquire (`deadline`) polls with a short, growing pause until it; an acquire
        with no limit blocks in the kernel, which wakes the waiter at the holder's unlock (a poll starves behind a holder that takes the lock again at once), while a watchdog thread says so
        after 30 s and every 60 s (it holds nothing and is stopped when the lock is taken)."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if not blocking:
                return False
        if deadline is None:
            stop = threading.Event()
            threading.Thread(target=self._watch, args=(stop, time.monotonic()), name=f"xlock-wait-{self.name}", daemon=True).start()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            finally:
                stop.set()
            return True
        started = time.monotonic()
        say_at = started + WAIT_LOG_FIRST
        pause = 0.0005
        while True:
            now = time.monotonic()
            if now >= deadline:
                return False
            if now >= say_at:
                say_at = now + WAIT_LOG_EVERY
                self._say_waiting(now - started)
            time.sleep(max(0.0, min(pause, deadline - now)))
            pause = min(pause * 2, 0.005)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                continue

    def _say_waiting(self, secs: float) -> None:
        print(f"xlock: {self.name}: still waiting for another process to let go of {self.path()} ({int(secs)} s)", file=sys.stderr, flush=True)

    def _watch(self, stop: threading.Event, started: float) -> None:
        """The hung-holder line of a blocked acquire: after WAIT_LOG_FIRST seconds, then every WAIT_LOG_EVERY, until `stop`."""
        delay = WAIT_LOG_FIRST
        while not stop.wait(delay):
            self._say_waiting(time.monotonic() - started)
            delay = WAIT_LOG_EVERY

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        deadline = time.monotonic() + timeout if blocking and timeout >= 0 else None        # one deadline for both stages, as an RLock's one timeout
        if self._t._is_owned():          # this thread holds it already: a nested hold is a count, no descriptor, no wait
            self._t.acquire()
            self._n += 1
            return True
        fd, err, path = None, None, None
        if enabled():
            fd, err, path = self._fd_for()      # before the front lock: the retries' pauses (persistent no-descriptor failure) hold nothing up
            if fd is None:
                self._fallback(err if err is not None else OSError("no lock file"), path)      # raises when strict; else the thread lock alone holds
        try:
            if not self._t.acquire(blocking, -1 if deadline is None else max(0.0, deadline - time.monotonic())):
                self._close(fd)
                return False
        except BaseException:
            self._close(fd)
            raise
        try:
            got = True if fd is None else self._lock_fd(fd, blocking, deadline)
        except OSError as e:             # the flock itself refused (EBADF on a filesystem that needs a descriptor open for writing): the same fallback as a lock file that cannot be had
            self._close(fd)
            fd = None
            try:
                got = self._fallback(e, path)[0]
            except BaseException:
                self._t.release()
                raise
        except BaseException:
            self._close(fd)
            self._t.release()
            raise
        if not got:
            self._close(fd)
            self._t.release()
            return False
        self._fd = fd
        self._n = 1
        return True

    @staticmethod
    def _close(fd: int | None) -> None:
        if fd is not None:
            os.close(fd)

    def release(self) -> None:
        if not self._t._is_owned():           # type: ignore[attr-defined]
            raise RuntimeError("cannot release un-acquired lock")
        self._n -= 1
        try:
            if self._n == 0:
                fd, self._fd = self._fd, None
                if fd is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        os.close(fd)
        finally:
            self._t.release()                 # the front lock goes back whatever the unlock did

    def _is_owned(self) -> bool:
        """Does the calling thread hold it? (what threading.RLock has; the suites ask it)."""
        return self._t._is_owned()            # type: ignore[attr-defined]

    def __enter__(self) -> "XLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
