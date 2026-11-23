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
the hold raises `LockUnavailable`, naming the lock file and the error, because a hold that does not keep the other process out is a lost update waiting to happen.

Strict. `strict` is off in production (the default, so the single-process server is never broken by a lock rule: a hold that cannot have its file falls back and says so) and on wherever the tests run (`tests/run-suite` sets `STACKSHOT_XLOCK_STRICT=1`; the variable is read once at import, and the module flag can be set by a test). With it on, a lock used in a way the rules below forbid raises at once instead of being logged: a lock file that cannot be had raises `LockUnavailable`, and a lock taken while a lock that must come after it is held raises `LockOrderError` (the order is ORDER below, the one in the next paragraph), whatever the timing, so a swapped nesting fails the first time it runs and not when two processes meet. Both are `RuntimeError`s on purpose: neither is an `OSError`, so a broad `except OSError` around a store write cannot swallow a refused hold, and a pass that catches `Exception` logs it and tries again at the next tick, with nothing written. Releasing a lock the thread does not hold raises `RuntimeError` whatever `strict` says.
A holder that never lets go is not waited on in silence: a waiter writes a line naming the lock after 30 seconds and again every 60 seconds; it never gives up on its own (a timed acquire gives up at its own deadline).
An acquire with no time limit blocks in the kernel's flock, so it is woken when the holder lets go (a poll would starve behind a holder that takes the lock again at once), and a watchdog thread, which holds nothing, writes the line; only a timed acquire polls.
The lock file is opened after the front lock is taken (a thread that only waits on the front lock holds no descriptor), with its retries: a try that may not wait (`blocking=False`) is not retried with a pause, and a timed one retries only inside its deadline. The descriptor is closed on every path that does not end in a hold (a refused try, a timeout, an error, an interrupt), and the thread lock is given back on every one. The descriptor is opened close-on-exec, so no child process inherits a flock. A filesystem that refuses a flock on a read-only descriptor (NFS) takes the same fallback as a lock file that cannot be had.

`[locks] cross_process = false` turns the flock off for the run (restart-only, config.RESTART_ONLY): every `XLock` is then its front thread lock and nothing else; so is every one on the read-only standby, which writes nothing.

Order. The locks that nest are always taken in one order, so two processes never wait on each other: the wake pass (`wake`) first, then the item lock (`item`), then the pending answers (`answers`), then
the For you list (`for-you`), the Landed list (`landed`) and the held hand-back lines (`handback-held`); the page-debt ledger (`ledger`) and the stall record (`stall`) are taken after the item lock, and the machine
anchors (`machine-anchors`) alone. No path takes the wake pass while it holds the item lock (the order is wake, then item; with `strict` on a lock out of order raises, and a recorder in tests/xlock_scenario.py fails on item before wake, on answers before item and on any pair taken in both orders). A new `XLock` that nests with these takes its place in that order and in docs/server-passes.md."""
from __future__ import annotations

import errno
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ModuleNotFoundError:      # Windows: the puller reaches this module through agentbox and has no flock; every XLock is then its front thread lock (enabled() is false)
    fcntl = None  # type: ignore[assignment]

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

strict = os.environ.get("STACKSHOT_XLOCK_STRICT", "").strip().lower() in ("1", "true", "yes", "on")      # off unless the environment says so (tests/run-suite does): see the docstring, "Strict"
ORDER = {"wake": 0, "item": 1, "answers": 2, "for-you": 3, "landed": 3, "handback-held": 3, "ledger": 3, "stall": 3}      # a lock may be taken while holding one that has the same number or a lower one, never a higher one; a name not listed (machine-anchors, a test's) is outside the order
FALLBACK_LOG_EVERY = 60.0       # seconds: one stderr line per lock for the holds that fell back
WAIT_LOG_FIRST = 30.0           # seconds a waiter waits before it says so, then every WAIT_LOG_EVERY
WAIT_LOG_EVERY = 60.0
_TRANSIENT = {errno.EMFILE, errno.ENFILE, errno.EINTR, errno.EAGAIN, errno.ENOMEM}      # the lock file is tried again for these, and not for a permission or a path that will not change
_RETRIES = 4
_RETRY_PAUSE = 0.025


class LockUnavailable(RuntimeError):
    """The lock file of an XLock could not be had while `xlock.strict` is on: the hold is refused, not made on the thread lock alone. `errno` is the error's (0 when it had none). Not an OSError: a broad `except OSError` must not swallow it."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.errno = code


class LockOrderError(RuntimeError):
    """A lock was taken while a lock that must come after it was held (ORDER), with `xlock.strict` on."""


_HELD = threading.local()       # the names of the XLocks this thread holds, outermost first (read by the order check)


def _held() -> list[str]:
    return _HELD.__dict__.setdefault("names", [])


def holds(name: str) -> bool:
    """Does the calling thread hold the XLock named `name` now? (a code that must not start a slow call under a lock asks; nothing is taken)."""
    return name in _held()


def enabled() -> bool:
    """[locks] cross_process, read at each first hold (the key is restart-only, so it stays as the process started with it): False only when it is set to false.
    The read-only standby never takes the flock either: it writes nothing, and its backstop refuses a lock file's creation."""
    return fcntl is not None and _cfg.get("locks", "cross_process", default=True) is not False and not _ro.is_read_only()


def _open(path: Path) -> int:
    """The lock file's descriptor, made when it is not there. One place, so a test can make it fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        os.set_inheritable(fd, False)       # pinned: a child process (git, a hook) must never inherit a lock descriptor and so hold the lock past its holder
    except BaseException:       # an interrupt too: the descriptor is closed on any way out, since nothing else holds it yet
        os.close(fd)
        raise
    return fd


class XLock:
    """A re-entrant lock across threads (a thread lock in front) and processes (a flock on `<paths.state>/<name>.lock` behind it). One instance per name."""

    _by_name: dict[str, "XLock"] = {}
    _by_name_lock = threading.Lock()

    def __new__(cls, name: str) -> "XLock":
        with cls._by_name_lock:
            self = cls._by_name.get(name)
            if self is None:
                self = super().__new__(cls)
                self.name = name
                self._t = threading.RLock()
                self._n = 0                      # how many times the thread that holds `_t` has taken it; only that thread reads or writes it
                self._fd: int | None = None      # the flock's descriptor while the outermost hold is held with the flock on
                self._said_at = 0.0              # when the last fallback line was written (the rate limit is best effort across threads: at worst one extra line)
                cls._by_name[name] = self        # published last: a thread that looks the name up finds it whole
            return self

    def __init__(self, name: str) -> None:
        pass                                     # everything is set in __new__, before the instance is published

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

    def _fd_for(self, blocking: bool = True, deadline: float | None = None) -> tuple[int | None, BaseException | None, Any]:
        """(descriptor, None, path) or (None, the error, path or None): the lock file opened, tried again for a moment on a transient failure. A try that may not wait (`blocking` false) is not
        tried again (a pause would be a wait), and a timed one is tried again only while its deadline has not come."""
        p: Any = None
        for attempt in range(_RETRIES):
            try:
                p = self.path()
                return _open(p), None, p
            except OSError as e:
                if e.errno not in _TRANSIENT or attempt == _RETRIES - 1 or not blocking:
                    return None, e, p
                if deadline is not None and time.monotonic() + _RETRY_PAUSE >= deadline:
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
            dog = threading.Thread(target=self._watch, args=(stop, time.monotonic()), name=f"xlock-wait-{self.name}", daemon=True)
            try:
                dog.start()
                fcntl.flock(fd, fcntl.LOCK_EX)
            finally:
                stop.set()                  # the watchdog is stopped whatever the flock did, and waited for (it wakes at once), so none outlives the wait
                if dog.is_alive():
                    dog.join(2.0)
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

    def _order_check(self) -> None:
        """With `strict` on: raise LockOrderError when a lock that must come after this one is held by the thread (ORDER)."""
        mine = ORDER.get(self.name)
        if mine is None:
            return
        for h in _held():
            theirs = ORDER.get(h)
            if theirs is not None and theirs > mine:
                raise LockOrderError(f"xlock {self.name} taken while {h} is held: the order is {' then '.join(sorted(ORDER, key=lambda k: (ORDER[k], k)))} (the lower number first)")

    def _take(self, blocking: bool, deadline: float | None) -> bool:
        """With the front lock held: the flock, or the fallback. Sets `_fd`. → whether the hold is made; the front lock is the caller's to give back when it is not (or on an error)."""
        fd, path = None, None
        if enabled():
            fd, err, path = self._fd_for(blocking, deadline)
            if fd is None:
                self._fallback(err if err is not None else OSError("no lock file"), path)      # raises when strict; else the thread lock alone holds
                self._fd = None
                return True
        try:
            got = self._lock_fd(fd, blocking, deadline) if fd is not None else True
        except OSError as e:             # the flock itself refused (EBADF on a filesystem that needs a descriptor open for writing): the same fallback as a lock file that cannot be had
            self._close(fd)
            fd = None
            got = self._fallback(e, path)[0]      # raises when strict (the descriptor is closed already)
        except BaseException:
            self._close(fd)
            raise
        if not got:
            self._close(fd)
            return False
        self._fd = fd
        return True

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        deadline = time.monotonic() + timeout if blocking and timeout >= 0 else None        # one deadline for both stages, as an RLock's one timeout
        if self._t._is_owned():          # this thread holds it already: a nested hold is a count, no descriptor, no wait
            self._t.acquire()
            self._n += 1
            return True
        if strict:
            self._order_check()          # before anything is held or waited for
        if not self._t.acquire(blocking, -1 if deadline is None else max(0.0, deadline - time.monotonic())):
            return False
        try:
            got = self._take(blocking, deadline)
        except BaseException:
            self._t.release()            # the front lock goes back on every way out that is not a hold (an error, an interrupt, a refusal)
            raise
        if not got:
            self._t.release()
            return False
        self._n = 1
        _held().append(self.name)
        return True

    @staticmethod
    def _close(fd: int | None) -> None:
        """Close a descriptor this hold opened; a close that fails (the descriptor is gone either way) never keeps the caller from giving the front lock back."""
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def release(self) -> None:
        if not self._t._is_owned():           # type: ignore[attr-defined]
            raise RuntimeError("cannot release un-acquired lock")
        self._n -= 1
        try:
            if self._n == 0:
                names = _held()
                if self.name in names:
                    names.pop(len(names) - 1 - names[::-1].index(self.name))
                fd, self._fd = self._fd, None
                if fd is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        self._close(fd)
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
