"""standby_copy.py: `stackshot standby-copy`, one consistent copy of a running server's data, for a standby (docs/standby-copy.md describes it).

    stackshot standby-copy [--out DIR] [--extra DIR]... [--lock-timeout SECONDS] [--max-hold SECONDS] [--output-timeout SECONDS]
    stackshot standby-copy --verify DIR

The first form runs on the server box only. It writes a tar stream to standard output, or the same tree into DIR with `--out`: `state/` ([paths] state), `store/` ([paths] store), `settings/` ([paths] secrets),
`extra/<n>/` (the directories of `--extra` and `[standby_copy] extra_dirs`) and, last, `manifest.json`. The second form checks a received copy against its manifest.

How the picture is made, in order:
  1. a first copy of the three folders into a private staging directory under the runtime directory, with no lock held, so that the next step has little left to do;
  2. the locks: the publish lock, the project record's lock, the store locks (LOCKS, in the order of core/xlock.py), the push queue's and the item id counter's;
  3. under them, every file that is new, changed or recently written is copied again, pass after pass, until a whole pass finds nothing to do. A `*.log` or `*.jsonl` file is appended to all the time, so it
     is read again under the locks; one written within 2 s before that read, or changing during it, is cut after its last newline, any other is kept whole;
  4. the locks are let go; the extra directories are copied (each until a scan before and a scan after its copy match), the files are hashed and the output is written.

Left out: in the state dir `site/` (the version files the server writes again; a static file put there by hand does not travel), `tmp/` (the scratch of the atomic writes), `search/` (the search index,
built again from the store) and the hand-made `backup-*.tar.gz` files; `.git` and the standby's `.synced-at` marker in the store; this box's own client files in the settings folder (CLIENT_FILES); lock
files and `*.tmp` files everywhere but in an extra directory. A link to a file is copied as that file; a link to a directory, a dangling link and a special
file are not copied and are listed in the manifest under `skipped`.

One run at a time in a runtime directory, and the output has a time limit, so a receiver that stalls never leaves staged copies piling up.

Messages name files and count them; they never hold a file's content. Exit codes: 0 done; 1 failed (no lock in time, a folder that kept changing or holds nothing, an earlier run still live, a write error or one too slow,
a copy that does not match); 2 usage; 3 refused (not the server box, a read-only standby, the cross-process locks off, a terminal or the journal for the stream); 128 + n stopped by signal n.

Stdlib only at import: the config is read only by the form that takes the copy, so `--verify` runs on a box that holds none of the server's settings."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, BinaryIO, Callable, Iterator, NamedTuple

try:
    import fcntl
except ModuleNotFoundError:      # Windows: no flock, and the server does not run there
    fcntl = None  # type: ignore[assignment]

from stackshot import paths as _paths

FORMAT = 1
MANIFEST = "manifest.json"
# every store lock of the package, in the order core/xlock.py gives them (the anchors file and the machine anchors stand outside it: nothing is taken while either is held, so they come last)
LOCKS = ("wake", "item", "answers", "for-you", "landed", "handback-held", "ledger", "stall", "anchors", "machine-anchors")
# `anchor-daily` is not a store lock: it keeps two daily passes apart, is held for a whole pass (its reads of other boxes included) and is taken without waiting. The files the pass changes are covered by the locks above and by the passes of step 3.
LOCKS_NOT_TAKEN = ("anchor-daily",)
STATE_DIRS_LEFT_OUT = ("site", "tmp", "search")      # top level of the state dir: the served version files, the scratch of the atomic writes, the search index
STATE_FILES_LEFT_OUT = ("backup-*.tar.gz",)          # top level of the state dir
QUEUE_DIRS = ("queue", "queue-msg")                 # the push queues, folders of push.A (fleet/push.py): their lines are appended in place under `<dir>/.lock`, which is taken too
ROOT_NAMES = ("state", "store", "settings")          # the three folders, as the output names them
SERVER_FOLDERS = ("state", "store")                  # a copy in which one of these holds no file is not a copy of a server
STORE_MARKER = ".synced-at"                          # top level of the store: the standby's copy job touches its own
CLIENT_FILES = ("client.token", "client.url", "stackshot.toml", "plugin.json", "test-launcher", "clean-text-deny")      # top level of the settings folder: each box keeps its own
LOG_SUFFIXES = (".log", ".jsonl")
STAGE_PREFIX = "stackshot-standby-copy-"
PARTIAL_MARK = ".standby-copy-partial-"             # --out writes into `.<name><mark><8 characters>` beside the target
RUN_LOCK = "stackshot-standby-copy.lock"            # in the runtime directory, held for a whole run
STALE_AFTER = 600                 # seconds: an empty leftover directory this old that no process holds is removed (a younger one may be about to be locked)
LOCK_TIMEOUT = 60.0               # seconds to get all the locks
LOCK_SLICE = 2.0                  # seconds, in all, to get every lock after the publish lock while others are held; then all are let go and taken again
MAX_HOLD = 30.0                   # seconds the locks may be held, from the publish lock on
OUTPUT_TIMEOUT = 600.0            # seconds to write the output
JOURNAL_SOCKETS = "/run/systemd/journal/"          # a standard output connected to a socket there is the journal
PASSES = 20                       # passes under the locks before a folder counts as never settling
EXTRA_TRIES = 6
RACY_NS = 2_000_000_000           # a file written this shortly before the first copy read it is copied again under the locks, whatever its size and times say; a log written this shortly ago may be mid-line
LOG_WHOLE_BELOW = 1 << 20         # a log this small is copied whole again under the locks; a larger one gets the lines written since the first copy
TAIL = 1 << 16                    # bytes compared before lines are added to the first copy of a log
CHUNK = 1 << 20
SIGNALS = ("SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT")


class CopyError(Exception):
    """The copy failed: the message is what is printed."""


class Refused(CopyError):
    """This box or this call may not take the copy."""


class Stopped(BaseException):
    """A signal asked the run to stop. Not an Exception: nothing on the way out may swallow it."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class Sig(NamedTuple):
    """What says a file is the one that was copied."""
    dev: int
    ino: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _sig(st: os.stat_result) -> Sig:
    return Sig(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class Entry(NamedTuple):
    """One staged file: the source's signature as it was read, the bytes kept, and whether it may stand without another read while the signature holds."""
    sig: Sig
    kept: int
    trusted: bool


class Tree:
    """One folder to copy, and what of it is staged."""

    def __init__(self, name: str, src: str, stage: str, left_out: Callable[[str, str, bool], bool]) -> None:
        self.name, self.src, self.left_out = name, src, left_out
        self.dst = os.path.join(stage, name)
        self.staged: dict[str, Entry] = {}
        self.dirs: set[str] = set()
        self.skipped: dict[str, str] = {}
        self.other_roots: set[tuple[int, int]] = set()      # another folder of this copy that lies inside this one is copied once, as itself


def _say(text: str) -> None:
    print("standby-copy: " + text.encode("utf-8", "backslashreplace").decode("utf-8"), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------- what is left out
def _temp_or_lock(name: str, is_dir: bool) -> bool:
    return name.endswith(".tmp") or (not is_dir and (name in ("lock", ".lock") or name.endswith(".lock")))


def left_out(root: str) -> Callable[[str, str, bool], bool]:
    """The rule of one of the three folders: (path inside it, name, is a directory) -> left out?"""
    def rule(rel: str, name: str, is_dir: bool) -> bool:
        top = rel == name
        if _temp_or_lock(name, is_dir):
            return True
        if root == "state":
            return top and (name in STATE_DIRS_LEFT_OUT if is_dir else any(fnmatch.fnmatchcase(name, p) for p in STATE_FILES_LEFT_OUT))
        if root == "store":
            return name == ".git" or (top and name == STORE_MARKER)
        return top and name in CLIENT_FILES
    return rule


def nothing_left_out(rel: str, name: str, is_dir: bool) -> bool:
    return False


# ---------------------------------------------------------------------------- scanning and copying
def scan(tree: Tree) -> tuple[dict[str, tuple[Sig, int]], set[str]]:
    """The folder as it is now: ({path: (signature, mode)} of its files, {its directories}); `tree.skipped` is set to what cannot be copied."""
    files: dict[str, tuple[Sig, int]] = {}
    dirs: set[str] = set()
    skipped: dict[str, str] = {}
    todo = [("", tree.src)]
    while todo:
        base, path = todo.pop()
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except (FileNotFoundError, NotADirectoryError):
            if not base:
                raise CopyError(f"the folder {tree.src} is not there") from None
            continue                      # gone since its parent was read: the next pass sees it
        for e in entries:
            rel = f"{base}/{e.name}" if base else e.name
            link = e.is_symlink()
            try:
                st = os.stat(e.path)
            except OSError as err:
                if link:
                    if not tree.left_out(rel, e.name, False):
                        skipped[rel] = "a link that leads nowhere"
                    continue
                if isinstance(err, FileNotFoundError):
                    continue
                raise
            is_dir = stat.S_ISDIR(st.st_mode)
            if tree.left_out(rel, e.name, is_dir):
                continue
            if is_dir:
                if link:
                    skipped[rel] = "a link to a directory"
                elif (st.st_dev, st.st_ino) not in tree.other_roots:
                    dirs.add(rel)
                    todo.append((rel, e.path))
            elif stat.S_ISREG(st.st_mode):
                files[rel] = (_sig(st), st.st_mode)
            else:
                skipped[rel] = "not a regular file"
    tree.skipped = skipped
    return files, dirs


def _pour(src: int, dst: int, start: int, end: int, check: Callable[[], None]) -> int:
    """Copy the bytes of `src` from `start` to `end` to the same place in `dst`; -> where the copy ended (short of `end` when the file is)."""
    at = start
    while at < end:
        check()
        chunk = os.pread(src, min(CHUNK, end - at), at)
        if not chunk:
            break
        view = memoryview(chunk)
        while view:
            n = os.pwrite(dst, view, at)
            at += n
            view = view[n:]
    return at


def _after_last_line(fd: int, length: int) -> int:
    """The length of the file's whole lines: up to and with its last newline."""
    at = length
    while at > 0:
        step = min(TAIL, at)
        i = os.pread(fd, step, at - step).rfind(b"\n")
        if i >= 0:
            return at - step + i + 1
        at -= step
    return 0


def copy_file(src: str, dst: str, *, log: bool, have: Entry | None, locked: bool, check: Callable[[], None]) -> Entry | None:
    """Stage one file -> its entry, or None when it changed while it was read (the caller reads it again). A log is taken as it is at the open; one written within RACY_NS, or changed while it was read, may be
    in the middle of a line and is cut after its last newline, and one that has been quiet longer is kept whole."""
    started = time.time_ns()
    fd = os.open(src, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        sig = _sig(st)
        out = os.open(dst, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            start = 0
            if log and have is not None and have.kept > LOG_WHOLE_BELOW and (have.sig.dev, have.sig.ino) == (sig.dev, sig.ino) and sig.size >= have.kept:
                n = min(TAIL, have.kept)
                if os.pread(fd, n, have.kept - n) == os.pread(out, n, have.kept - n):
                    start = have.kept             # only the lines written since: the file is the same one and still ends the first copy the same way
            os.ftruncate(out, start)
            end = _pour(fd, out, start, sig.size, check)
            moved = end != sig.size or _sig(os.fstat(fd)) != sig
            if log and (moved or sig.mtime_ns > started - RACY_NS):
                end = _after_last_line(out, end)
                os.ftruncate(out, end)
            elif moved and not log:
                return None
            os.fchmod(out, 0o700 if st.st_mode & 0o100 else 0o600)
        finally:
            os.close(out)
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
        # trusted: read under the locks, or (not a log) last written well before the first copy read it, so a later write cannot leave the same signature
        return Entry(sig, end, locked or (not log and sig.ctime_ns < started - RACY_NS))
    finally:
        os.close(fd)


def _stands(have: Entry | None, sig: Sig, log: bool) -> bool:
    """May the staged copy stay as it is? A log cut under the locks stays while it is the same file and no shorter: lines added later are not part of this picture."""
    if have is None or not have.trusted:
        return False
    if log:
        return (have.sig.dev, have.sig.ino) == (sig.dev, sig.ino) and sig.size >= have.sig.size
    return have.sig == sig


def sync(tree: Tree, *, locked: bool, check: Callable[[], None]) -> list[str]:
    """One pass: make the staged copy of `tree` what a scan finds now -> the paths it had to touch."""
    files, dirs = scan(tree)
    os.makedirs(tree.dst, mode=0o700, exist_ok=True)
    touched: list[str] = []
    for rel in [r for r in tree.staged if r not in files]:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(tree.dst, rel))
        del tree.staged[rel]
        touched.append(rel)
    for rel in sorted(tree.dirs - dirs, reverse=True):
        shutil.rmtree(os.path.join(tree.dst, rel), ignore_errors=True)
        touched.append(rel)
    for rel in sorted(dirs - tree.dirs):
        os.makedirs(os.path.join(tree.dst, rel), mode=0o700, exist_ok=True)
        touched.append(rel)
    tree.dirs = dirs
    for rel in sorted(files):
        check()
        sig, _ = files[rel]
        log = rel.endswith(LOG_SUFFIXES)
        have = tree.staged.get(rel)
        if locked and _stands(have, sig, log):
            continue
        dst = os.path.join(tree.dst, rel)
        try:
            got = copy_file(os.path.join(tree.src, rel), dst, log=log, have=have, locked=locked, check=check)
        except (FileNotFoundError, NotADirectoryError):
            got = None
        touched.append(rel)
        if got is None:
            tree.staged.pop(rel, None)
            with contextlib.suppress(FileNotFoundError):
                os.remove(dst)
        else:
            tree.staged[rel] = got
    return touched


def settle(trees: list[Tree], check: Callable[[], None]) -> None:
    """Passes under the locks until one finds nothing to do: the staged copy is then the folders as they stand."""
    touched: list[str] = []
    for _ in range(PASSES):
        touched = [f"{t.name}/{r}" for t in trees for r in sync(t, locked=True, check=check)]
        if not touched:
            return
    names = ", ".join(touched[:5]) + (f" and {len(touched) - 5} more" if len(touched) > 5 else "")
    raise CopyError(f"the folders kept changing under the locks ({PASSES} passes): {names}")


def _shape(files: dict[str, tuple[Sig, int]], dirs: set[str]) -> tuple[dict[str, tuple[int, int]], set[str]]:
    return {r: (s.size, s.mtime_ns) for r, (s, _) in files.items()}, dirs


def copy_settled(tree: Tree) -> None:
    """An extra directory, written outside the locks: copied until a scan before the copy and a scan after it find the same sizes and times, EXTRA_TRIES times at most."""
    pause = 0.1
    for attempt in range(EXTRA_TRIES):
        shutil.rmtree(tree.dst, ignore_errors=True)
        tree.staged, tree.dirs = {}, set()
        before = _shape(*scan(tree))
        os.makedirs(tree.dst, mode=0o700)
        for rel in sorted(before[1]):
            os.makedirs(os.path.join(tree.dst, rel), mode=0o700, exist_ok=True)
        whole = True
        for rel in sorted(before[0]):
            try:
                got = copy_file(os.path.join(tree.src, rel), os.path.join(tree.dst, rel), log=False, have=None, locked=False, check=lambda: None)
            except (FileNotFoundError, NotADirectoryError):
                got = None
            if got is None or (got.sig.size, got.sig.mtime_ns) != before[0][rel]:
                whole = False
                break
            tree.staged[rel] = got
        if whole and _shape(*scan(tree)) == before:
            tree.dirs = before[1]
            return
        if attempt < EXTRA_TRIES - 1:
            time.sleep(pause)
            pause = min(pause * 2, 1.0)
    raise CopyError(f"the extra directory {tree.src} did not settle in {EXTRA_TRIES} tries")


# ---------------------------------------------------------------------------- the locks
class _Busy(Exception):
    """One lock was not had in its time."""


def _flock(path: str, how: int, deadline: float, name: str, *, create: bool = True) -> Callable[[], None]:
    """A flock on `path` taken by `deadline` -> the call that lets it go."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | (os.O_CREAT if create else 0), 0o644)
    try:
        pause = 0.001
        while True:
            try:
                fcntl.flock(fd, how | fcntl.LOCK_NB)
                return lambda: os.close(fd)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _Busy(name) from None
                time.sleep(pause)
                pause = min(pause * 2, 0.02)
    except BaseException:
        os.close(fd)
        raise


def _gave_up(abandoned: list[float]) -> str:
    """The measure of the attempts that were given up, for a message: "" when there were none."""
    if not abandoned:
        return ""
    return f"; attempts given up: {len(abandoned)}, holding locks {_ms(sum(abandoned))} ms in all, {_ms(max(abandoned))} ms at most"


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


@contextlib.contextmanager
def held_locks(cfg: Any, xlock: Any, queues: list[str], next_id: str, timeout: float, max_hold: float, head: Callable[[float], str | None], abandoned: list[float]) -> Iterator[tuple[float, str | None]]:
    """Every lock of the picture, or none: -> (when the publish lock was had, the board's head read under it). The publish lock comes first and is waited for with nothing else held (a publish may be at a
    slow push). All the locks after it share one wait: LOCK_SLICE in all, and never past `max_hold` from the publish lock. Past it everything is let go and taken again, so that two processes that take two
    locks the other way round never stop each other and no writer waits long behind an attempt that fails. Each attempt given up adds the seconds it held a lock to `abandoned`. CopyError after `timeout`."""
    deadline = time.monotonic() + timeout
    pause = 0.1
    while True:
        release: list[Callable[[], None]] = []
        since: float | None = None
        try:
            try:
                os.makedirs(str(cfg.state()), exist_ok=True)
                release.append(_flock(str(cfg.state("publish.lock")), fcntl.LOCK_EX, deadline, "publish"))
                since = time.monotonic()
                commit = head(max_hold)
                rest = min(deadline, time.monotonic() + LOCK_SLICE, since + max_hold)      # one wait for all that follow
                release.append(_flock(str(cfg.state("project-record.lock")), fcntl.LOCK_EX, rest, "project-record"))
                for name in LOCKS:
                    lock = xlock.XLock(name)
                    try:
                        got = lock.acquire(timeout=max(0.0, rest - time.monotonic()))
                    except xlock.LockUnavailable as e:
                        raise CopyError(str(e)) from None
                    if not got:
                        raise _Busy(name)
                    release.append(lock.release)
                for q in queues:
                    if os.path.isdir(q):             # no directory, no queue: the command makes none
                        release.append(_flock(os.path.join(q, ".lock"), fcntl.LOCK_EX, rest, "push " + os.path.basename(q)))
                if os.path.exists(next_id):      # the id counter has a lock of its own, on the file: no id is given out while the picture is made, so it is never behind an item in it
                    release.append(_flock(next_id, fcntl.LOCK_SH, rest, "next-id", create=False))
            except _Busy as busy:
                while release:
                    release.pop()()
                if since is not None:
                    abandoned.append(time.monotonic() - since)
                if time.monotonic() >= deadline:
                    raise CopyError(f"the {busy} lock was not free within {timeout:g} s{_gave_up(abandoned)}") from None
                time.sleep(min(pause, max(0.0, deadline - time.monotonic())))
                pause = min(pause * 2, 1.0)
                continue
            yield since, commit
            return
        finally:
            while release:
                release.pop()()


# ---------------------------------------------------------------------------- signals and the staging directory
def _signals() -> list[int]:
    return [getattr(signal, n) for n in SIGNALS if hasattr(signal, n)]


def _stop(signum: int, frame: Any) -> None:
    for s in _signals():
        signal.signal(s, signal.SIG_IGN)      # one stop is enough: a second signal must not cut the cleanup short
    raise Stopped(signum)


@contextlib.contextmanager
def _signals_held() -> Iterator[None]:
    old = signal.pthread_sigmask(signal.SIG_BLOCK, _signals())
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def runtime_dir() -> str:
    d = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(os.environ.get("STACKSHOT_RUNTIME_BASE") or "/run/user", str(os.getuid()))
    if not os.path.isdir(d):
        raise CopyError(f"there is no runtime directory for the staging copy: {d} is not there (set XDG_RUNTIME_DIR)")
    return d


def _remove_leftover(path: str) -> None:
    """Remove `path`, a directory with a name of ours, when a run that was killed outright left it: a real directory of this user, mode 0700, that no process holds, with nothing at its top but what a copy
    puts there. An empty one is removed only once it is STALE_AFTER old (a run makes its directory a moment before it locks it, and puts nothing in it before)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return
    try:
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            return
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inside = set(os.listdir(fd))
        if not inside <= {*ROOT_NAMES, "extra", MANIFEST} or (not inside and time.time() - st.st_mtime < STALE_AFTER):
            return
        shutil.rmtree(path)
        _say(f"removed what an earlier run left: {path}")
    except OSError:
        return
    finally:
        os.close(fd)


def sweep_stale(base: str) -> None:
    """The staging copies killed runs left in the runtime directory."""
    for name in os.listdir(base):
        if name.startswith(STAGE_PREFIX):
            _remove_leftover(os.path.join(base, name))


def sweep_partials(parent: str) -> None:
    """The half-made trees killed runs of --out left in `parent`: only names of exactly the form write_dir makes."""
    ours = re.compile(r"\..+" + re.escape(PARTIAL_MARK) + r"[a-z0-9_]{8}", re.DOTALL)
    try:
        names = os.listdir(parent)
    except OSError:
        return          # no such directory yet, or one that cannot be listed: the write says what is wrong
    for name in names:
        if ours.fullmatch(name):
            _remove_leftover(os.path.join(parent, name))


@contextlib.contextmanager
def time_limit(seconds: float, message: str) -> Iterator[None]:
    """CopyError(message) when the block is still running after `seconds`, a write that blocks included (SIGALRM)."""
    def late(signum: int, frame: Any) -> None:
        raise CopyError(message)
    old = signal.signal(signal.SIGALRM, late)
    try:
        signal.setitimer(signal.ITIMER_REAL, min(seconds, 1e8))
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


@contextlib.contextmanager
def private_dir(parent: str, prefix: str) -> Iterator[str]:
    """A new 0700 directory, locked while it is in use and removed on the way out, a signal's way included (unless it was renamed into place by then)."""
    path, fd = "", -1

    def remove() -> None:
        with _signals_held():
            if path and os.path.lexists(path):
                shutil.rmtree(path)
    try:
        with _signals_held():
            path = tempfile.mkdtemp(prefix=prefix, dir=parent)
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield path
    finally:
        try:
            remove()
        except Stopped:      # the signal came just as the removal began: later ones are ignored (_stop), so this removal runs to its end
            remove()
            raise
        finally:
            if fd >= 0:
                os.close(fd)


@contextlib.contextmanager
def staging(base: str, out_dir: str | None) -> Iterator[str]:
    """The run's staging directory. One run at a time in `base`: a run that is still live (a receiver that takes its output slowly) keeps the next one from staging a second copy beside it. What killed runs
    left is removed first."""
    path = os.path.join(base, RUN_LOCK)
    fd = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CopyError(f"an earlier run is still live (it holds {path}): nothing was started") from None
        sweep_stale(base)
        if out_dir is not None:
            sweep_partials(os.path.dirname(out_dir))
        with private_dir(base, STAGE_PREFIX) as stage:
            yield stage
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------- the manifest and the output
def _digest(path: str) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def contents(trees: list[Tree]) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, str]]]:
    """(directories, {file: {sha256, size}}, what was skipped) of the staged copy, by the paths the output has."""
    dirs: set[str] = set()
    files: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for t in trees:
        parts = t.name.split("/")
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        dirs.update(f"{t.name}/{r}" for r in t.dirs)
        for rel in t.staged:
            sha, size = _digest(os.path.join(t.dst, rel))
            files[f"{t.name}/{rel}"] = {"sha256": sha, "size": size}
        skipped += [{"path": f"{t.name}/{r}", "reason": why} for r, why in sorted(t.skipped.items())]
    return sorted(dirs), dict(sorted(files.items())), skipped


def _member(name: str, st: os.stat_result, kind: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = stat.S_IMODE(st.st_mode) & 0o700
    info.mtime = st.st_mtime
    info.size = st.st_size if kind == tarfile.REGTYPE else 0
    return info


def to_journal(fd: int) -> bool:
    """Is `fd` a stream to the journal: the one systemd names in $JOURNAL_STREAM (device:inode), or a socket connected to one of the journal's own?"""
    st = os.fstat(fd)
    if os.environ.get("JOURNAL_STREAM") == f"{st.st_dev}:{st.st_ino}":
        return True
    if not stat.S_ISSOCK(st.st_mode):
        return False
    try:
        with socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            peer = sock.getpeername()
    except OSError:
        return False
    return os.fsdecode(peer).startswith(JOURNAL_SOCKETS) if isinstance(peer, (str, bytes)) else False


def private_file(fd: int) -> None:
    """A file standard output was redirected to is made 0600 before anything is written: the stream holds the settings folder, and the shell made the file by the caller's umask."""
    if stat.S_ISREG(os.fstat(fd).st_mode):
        try:
            os.fchmod(fd, 0o600)
        except OSError as e:
            raise CopyError(f"the file standard output goes to could not be made private (0600): {e.strerror}") from None


def write_tar(stage: str, dirs: list[str], files: list[str], out: BinaryIO) -> None:
    """The staged tree as a tar stream, the manifest last: a stream cut short has no whole manifest. On any failure standard output goes to the null device, so that nothing more is written or waited for."""
    try:
        tar = tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT, encoding="utf-8")
        for name in dirs:
            tar.addfile(_member(name, os.stat(os.path.join(stage, name)), tarfile.DIRTYPE))
        for name in [*files, MANIFEST]:
            path = os.path.join(stage, name)
            with open(path, "rb") as f:
                tar.addfile(_member(name, os.fstat(f.fileno()), tarfile.REGTYPE), f)
        tar.close()
        out.flush()
    except BaseException:
        with contextlib.suppress(OSError, ValueError):
            null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null, out.fileno())
            os.close(null)
        raise


def write_dir(stage: str, dirs: list[str], files: list[str], target: str) -> None:
    """The staged tree in `target`, made beside it and renamed into place whole."""
    parent, name = os.path.split(target)
    with private_dir(parent, f".{name}{PARTIAL_MARK}") as partial:
        for d in dirs:
            os.makedirs(os.path.join(partial, d), mode=0o700, exist_ok=True)
        for f in [*files, MANIFEST]:
            shutil.copy2(os.path.join(stage, f), os.path.join(partial, f))
        os.rename(partial, target)      # over an empty directory too; one that filled up meanwhile refuses


# ---------------------------------------------------------------------------- taking one
def _inside(path: str, root: str) -> bool:
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _commit(repo: str, limit: float = 10.0) -> str | None:
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "HEAD"], capture_output=True, text=True, timeout=min(10.0, limit))
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def not_the_server_box(cfg: Any) -> str:
    """Why this box may not take the copy, as one line, or "" on the server box. `server_host_refusal` decides where the config names the server host (`[release] deploy_ssh`) or says `[server] box = false`.
    It passes a config that names no host; there the rule is the one the pages are read by (pages.reads_local): `[server] box = true`, or, with the key unset, a box that holds the pages checkout."""
    why = cfg.server_host_refusal()
    named = cfg.get("release", "deploy_ssh")
    if why or (isinstance(named, str) and named.strip()):
        return why
    from stackshot.projects import pages
    if pages.reads_local():
        return ""
    return (f"this box ({socket.gethostname()}) is not the server host: [release] deploy_ssh names none, [server] box is unset and there is no pages checkout at {pages.BRAIN} "
            "(on the server box, name it in deploy_ssh or set [server] box = true)")


def take(out_dir: str | None, extras: list[str], lock_timeout: float, max_hold: float, output_timeout: float, stream: BinaryIO | None) -> str:
    """One copy, to `out_dir` or to `stream` -> the line that says what it holds."""
    if fcntl is None:
        raise Refused("this system has no cross-process locks: the server box is a Linux box")
    from stackshot.core import config as cfg
    from stackshot.core import readonly
    from stackshot.core import xlock
    if readonly.is_read_only():
        raise Refused("this is a read-only standby copy (STACKSHOT_READ_ONLY): take the copy on the live server box")
    why = not_the_server_box(cfg)
    if why:
        raise Refused(why)
    if not xlock.enabled():
        raise Refused("[locks] cross_process is false: with the cross-process locks off the running server cannot be kept out, so no consistent picture can be made")
    if out_dir is None:
        assert stream is not None
        private_file(stream.fileno())
    xlock.strict = True      # a lock that cannot be had fails the copy, never a hold on the thread lock alone
    roots = dict(zip(ROOT_NAMES, (str(cfg.state()), str(cfg.path("paths", "store")), str(cfg.secrets()))))
    for label, p in roots.items():
        if not os.path.isdir(p):
            raise CopyError(f"the {label} folder {p} is not there")
    if len({os.path.realpath(p) for p in roots.values()}) != len(roots):
        raise CopyError("the state, store and settings folders must be three different directories")
    extra: list[str] = []
    for p in [str(x) for x in cfg.paths("standby_copy", "extra_dirs")] + [os.path.expanduser(x) for x in extras]:
        p = os.path.abspath(p)
        if not os.path.isdir(p):
            raise CopyError(f"the extra directory {p} is not there")
        for label, root in roots.items():
            if _inside(p, root) or _inside(root, p):
                raise CopyError(f"the extra directory {p} overlaps the {label} folder {root}")
        if os.path.realpath(p) not in [os.path.realpath(q) for q in extra]:
            extra.append(p)
    sources = [*roots.values(), *extra]
    base = runtime_dir()
    for s in sources:
        if _inside(base, s):
            raise CopyError(f"the runtime directory {base} lies inside {s}, which the command copies")
    if out_dir is not None:
        out_dir = os.path.abspath(out_dir)
        if os.path.lexists(out_dir) and (os.path.islink(out_dir) or not os.path.isdir(out_dir) or os.listdir(out_dir)):
            raise CopyError(f"{out_dir} is there already and is not an empty directory")
        for s in sources:
            if _inside(out_dir, s):
                raise CopyError(f"{out_dir} lies inside {s}, which the command copies")
    repo = str(cfg.path("paths", "repo"))

    def board_head(limit: float) -> str | None:
        started = time.monotonic()
        got = _commit(repo, limit)
        if got is None and time.monotonic() - started >= limit:
            raise CopyError(f"the board's head commit was not read in {repo} within the {max_hold:g} s the locks may be held")
        if got is None and cfg.get("publish", "git", default=True):
            raise CopyError(f"the board's head commit could not be read in {repo}")
        return got

    from stackshot.fleet import push
    queues = [os.path.join(push.A, d) for d in QUEUE_DIRS]
    abandoned: list[float] = []
    with staging(base, out_dir) as stage:
        trees = [Tree(name, path, stage, left_out(name)) for name, path in roots.items()]
        for t in trees:
            for other in trees:
                if other is not t:
                    st = os.stat(other.src)
                    t.other_roots.add((st.st_dev, st.st_ino))
        for t in trees:
            sync(t, locked=False, check=lambda: None)
        next_id = os.path.join(roots["store"], "next-id")
        with held_locks(cfg, xlock, queues, next_id, lock_timeout, max_hold, board_head, abandoned) as (since, head):
            stop_at = since + max_hold

            def check() -> None:
                if time.monotonic() >= stop_at:
                    raise CopyError(f"the copy under the locks did not finish within {max_hold:g} s of the first lock{_gave_up(abandoned)}")
            next(t for t in trees if t.name == "store").staged.pop("next-id", None)      # rewritten in place: always read again under its lock
            settle(trees, check)
            for t in trees:
                if t.name in SERVER_FOLDERS and not t.staged:
                    raise CopyError(f"the {t.name} folder {t.src} holds nothing to copy: this would not be a copy of a server")
            taken = dt.datetime.now(dt.timezone.utc)
        held_ms = _ms(time.monotonic() - since)
        extra_trees = [Tree(f"extra/{i}", p, stage, nothing_left_out) for i, p in enumerate(extra)]
        for t in extra_trees:
            copy_settled(t)
        dirs, files, skipped = contents([*trees, *extra_trees])
        counter = ""
        if "store/next-id" in files:
            with open(os.path.join(stage, "store", "next-id"), "rb") as f:
                counter = f.read(64).decode("ascii", "replace").strip()
        manifest = {"format": FORMAT, "time": taken.strftime("%Y-%m-%dT%H:%M:%SZ"), "code_commit": _commit(str(_paths.ROOT)), "board_head": head,
                    "next_id": int(counter) if counter.isascii() and counter.isdigit() else None, "lock_hold_ms": held_ms,
                    "lock_attempts_abandoned": {"count": len(abandoned), "held_ms": _ms(sum(abandoned)), "longest_ms": _ms(max(abandoned, default=0.0))},
                    "roots": roots, "extra": [{"dir": t.name, "source": t.src} for t in extra_trees], "skipped": skipped, "dirs": dirs, "files": files}
        if manifest["code_commit"] is None:
            _say(f"the code commit could not be read in {_paths.ROOT}: the manifest says null")
        fd = os.open(os.path.join(stage, MANIFEST), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            json.dump(manifest, f, indent=1)
        with time_limit(output_timeout, f"the output was not written within {output_timeout:g} s"):
            if out_dir is not None:
                write_dir(stage, dirs, list(files), out_dir)
            else:
                assert stream is not None
                write_tar(stage, dirs, list(files), stream)
    for s in skipped[:10]:
        _say(f"not copied ({s['reason']}): {s['path']}")
    return (f"{len(files)} files, {sum(v['size'] for v in files.values())} bytes; locks held {held_ms} ms{_gave_up(abandoned)}; {len(skipped)} entries not copied" + (f"; written to {out_dir}" if out_dir else ""))


# ---------------------------------------------------------------------------- checking a copy
def _relative(name: Any) -> bool:
    return isinstance(name, str) and bool(name) and "\0" not in name and name != MANIFEST and all(p not in ("", ".", "..") for p in name.split("/"))


def verify(target: str) -> tuple[int, list[str], list[dict[str, str]]]:
    """A received copy against its manifest -> (the files the manifest lists, what does not match, what the manifest says was not copied). CopyError when there is no manifest that can be read."""
    if not os.path.isdir(target):
        raise CopyError(f"{target} is not a directory")
    path = os.path.join(target, MANIFEST)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise CopyError(f"{path} is not a regular file")
            manifest = json.loads(f.read())
    except OSError as e:
        raise CopyError(f"{path} cannot be read: {e.strerror}") from None
    except (ValueError, RecursionError):
        raise CopyError(f"{path} is not a whole manifest") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise CopyError(f"{path} is not a manifest of format {FORMAT}")
    files, dirs, skipped = manifest.get("files"), manifest.get("dirs"), manifest.get("skipped")
    if (not isinstance(skipped, list) or not all(isinstance(s, dict) and isinstance(s.get("path"), str) and isinstance(s.get("reason"), str) for s in skipped)
            or not isinstance(files, dict) or not isinstance(dirs, list) or not all(map(_relative, files)) or not all(map(_relative, dirs))
            or not all(isinstance(v, dict) and isinstance(v.get("sha256"), str) and isinstance(v.get("size"), int) for v in files.values())):
        raise CopyError(f"{path} is malformed")
    found_files: set[str] = set()
    found_dirs: set[str] = set()
    bad: list[str] = []
    todo = [("", target)]
    while todo:
        base, at = todo.pop()
        with os.scandir(at) as it:
            for e in it:
                rel = f"{base}/{e.name}" if base else e.name
                if e.is_dir(follow_symlinks=False):
                    found_dirs.add(rel)
                    todo.append((rel, e.path))
                elif e.is_file(follow_symlinks=False):
                    if rel != MANIFEST:
                        found_files.add(rel)
                else:
                    bad.append(f"neither a file nor a directory: {rel}")
    wanted_dirs = set(dirs)
    bad += [f"missing: {r}" for r in sorted(set(files) - found_files)]
    bad += [f"extra: {r}" for r in sorted(found_files - set(files))]
    bad += [f"missing directory: {r}" for r in sorted(wanted_dirs - found_dirs)]
    bad += [f"extra directory: {r}" for r in sorted(found_dirs - wanted_dirs)]
    for rel in sorted(set(files) & found_files):
        sha, size = _digest(os.path.join(target, rel))
        if size != files[rel]["size"] or sha != files[rel]["sha256"]:
            bad.append(f"changed: {rel}")
    return len(files), bad, skipped


# ---------------------------------------------------------------------------- the command
def _seconds(text: str) -> float:
    """A time limit from the command line: a finite number of seconds above 0 (`nan` compares false with every deadline and would wait for ever)."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number of seconds above 0")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One consistent copy of the server's data (the state dir, the board store, the settings folder), as a tar stream on standard output or in a directory; "
                                             "--verify checks a received copy. See docs/standby-copy.md.")
    ap.add_argument("--out", metavar="DIR", help="write the tree into DIR (not there yet, or empty) instead of a tar stream")
    ap.add_argument("--extra", metavar="DIR", action="append", default=[], help="a further directory to copy, written outside the locks; may be given again; [standby_copy] extra_dirs adds to it")
    ap.add_argument("--lock-timeout", metavar="SECONDS", type=_seconds, default=LOCK_TIMEOUT, help=f"fail when the locks are not all free within this time (default {LOCK_TIMEOUT:g})")
    ap.add_argument("--max-hold", metavar="SECONDS", type=_seconds, default=MAX_HOLD, help=f"fail when the locks would be held longer than this, counted from the first one (default {MAX_HOLD:g})")
    ap.add_argument("--output-timeout", metavar="SECONDS", type=_seconds, default=OUTPUT_TIMEOUT, help=f"fail when the output is not written within this time (default {OUTPUT_TIMEOUT:g})")
    ap.add_argument("--verify", metavar="DIR", help="check the copy in DIR against its manifest; exit 1 on a changed, missing or extra file; the entries the copy left out are named")
    a = ap.parse_args(argv)
    try:
        if a.verify is not None:
            if a.out is not None or a.extra:
                ap.error("--verify takes no --out and no --extra")
            count, bad, skipped = verify(a.verify)
            for s in skipped[:50]:
                _say(f"not in the copy ({s['reason']}): {s['path']}")
            if len(skipped) > 50:
                _say(f"and {len(skipped) - 50} more entries not in the copy: the manifest lists them under skipped")
            for line in bad[:50]:
                _say(line)
            if bad:
                _say(f"the copy does not match its manifest: {len(bad)} differences")
                return 1
            _say(f"verified: {count} files match the manifest")
            return 0
        if a.out is None and sys.stdout.isatty():
            raise Refused("standard output is a terminal: send the stream to a pipe or a file, or use --out DIR")
        stream = sys.stdout.buffer
        if a.out is None and to_journal(stream.fileno()):
            raise Refused("standard output is the journal: send the stream to a pipe or a file, or use --out DIR")
        old = {s: signal.signal(s, _stop) for s in _signals()}
        try:
            with contextlib.redirect_stdout(sys.stderr):      # whatever an import or a library prints must not land in the stream
                _say(take(a.out, a.extra, a.lock_timeout, a.max_hold, a.output_timeout, stream if a.out is None else None))
        finally:
            for s, handler in old.items():
                signal.signal(s, handler)
        return 0
    except Stopped as e:
        _say(f"stopped by signal {e.signum}: nothing here is a whole copy")
        return 128 + e.signum
    except Refused as e:
        _say(f"refused: {e}")
        return 3
    except CopyError as e:
        _say(f"failed: {e}")
        return 1
    except OSError as e:      # the name and the system's own words, never a content
        _say(f"failed: {e.strerror or e.__class__.__name__}" + (f": {e.filename}" if e.filename else ""))
        return 1
    except Exception as e:  # noqa: BLE001  — the kind only: a message may quote what was read
        tb = e.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        _say(f"failed: {e.__class__.__name__}" + (f" at {os.path.basename(tb.tb_frame.f_code.co_filename)} line {tb.tb_lineno}" if tb else ""))
        return 1


if __name__ == "__main__":
    sys.exit(main())
