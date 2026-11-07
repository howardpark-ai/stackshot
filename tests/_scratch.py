"""tests/_scratch.py — scratch directories for the suites, removed when the suite ends (Tue Oct 27th 2026).

A folder made with tempfile.mkdtemp and removed by a line at the very end of a suite is left behind by a failing
check, an exception or an early exit, and a run that ends in os._exit never reaches an atexit hook. A suite asks for its
folders here:

    import _scratch
    tmp = _scratch.mkdtemp(prefix="hubtest-")

and they are removed (whatever is in them) when the process ends: on a normal end, a failing check, an exception, sys.exit,
os._exit (wrapped here to remove first), SIGTERM and SIGHUP (a signal the suite has not taken for its own use; coverage.py's
handler in a measured run, is wrapped: removed first, then coverage saves and the process ends by the signal). Only the
process that made a folder removes it, so a forked child that exits does not take its parent's folders away.

Each folder also holds a shared BSD lock (flock) while the process runs, so the hourly systemd-tmpfiles clean-up of old folders in
/tmp (which skips a locked folder and everything below it) cannot take a long-running suite's folder; the lock drops by itself when
the process ends or crashes.

KEEP_SCRATCH=1 in the environment leaves the folders for debugging; the path of each is printed to stderr at the end.

`track(path)` hands over a path the suite made some other way (a folder inside tempfile.gettempdir() whose name the code under
test fixes, say). `cleanup()` removes now what is held. tests/run-suite also gives each run a TMPDIR of its own and removes it
afterwards, which catches what a subprocess of the suite left; this module is what holds when a suite runs without it.
Everything is relative to $TMPDIR (tempfile honours it): nothing here names /tmp.
"""
import atexit, fcntl, os, shutil, signal, sys, tempfile, time

_held = []                 # paths to remove, in the order made
_fds = []                  # one open descriptor per folder, each holding a shared BSD lock (see _lock)
_owner = os.getpid()       # a forked child shares the list: only the process that imported this removes
_KEEP = lambda: os.environ.get("KEEP_SCRATCH", "") not in ("", "0")


def mkdtemp(prefix="scratch-", short=False):
    """tempfile.mkdtemp(prefix=…), removed with everything in it when the process ends. short=True makes it under /tmp, not $TMPDIR, for a
    unix socket's folder when $TMPDIR is deep (a socket path holds 107 bytes; a CI runner's temp folder may be long); removed and locked all the same."""
    return track(tempfile.mkdtemp(prefix=prefix, dir="/tmp" if short else None))


def _lock(path):
    """hold a shared BSD lock (flock) on a folder until the process ends: systemd-tmpfiles skips a folder that holds one, and
    everything below it (tmpfiles.d(5), aging), so an hourly clean-up of old folders in /tmp never takes a running suite's. The lock
    drops by itself when the process ends or crashes (SIGKILL included). The descriptor is close-on-exec and closed in a forked
    child, so a child that outlives the suite does not keep the folder locked."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return                         # not a folder, or already gone
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
    except OSError:
        os.close(fd)
        return
    _fds.append(fd)


def _drop_locks_in_child():
    for fd in _fds:
        try:
            os.close(fd)
        except OSError:
            pass
    _fds.clear()


os.register_at_fork(after_in_child=_drop_locks_in_child)


def track(path):
    """remove `path` (a folder or a file) when the process ends; a folder is locked meanwhile. Returns it unchanged."""
    _held.append(os.path.abspath(path))
    _lock(path)
    return path


def _remove(p):
    """remove one path; while it is still there (a daemon thread of the suite wrote into it meanwhile), try again, 3 times, 50 ms apart"""
    for attempt in range(4):
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass
        if not os.path.lexists(p):
            return
        if attempt < 3:
            time.sleep(0.05)


def cleanup():
    """remove what is held, now. Only in the process that imported this; KEEP_SCRATCH=1 keeps it all."""
    if os.getpid() != _owner:
        return
    keep = _KEEP()
    while _held:
        p = _held.pop()
        if keep:
            try:
                print(f"scratch kept: {p}", file=sys.stderr)
            except (OSError, ValueError):      # a closed or broken stderr must not change how the suite ends
                pass
        else:
            _remove(p)


_real_exit = os._exit


def _exit(code=0):
    try:
        cleanup()
    finally:                           # whatever cleanup does, the process ends with the status it was given
        _real_exit(code)


def _on_signal(signum, frame):
    try:
        cleanup()
    finally:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)   # end the way the signal says, so the parent sees it


def _then(prev):
    def on_signal(signum, frame):
        try:
            cleanup()
        finally:
            prev(signum, frame)        # coverage.py's: saves its data, puts the old handler back and ends by the signal
    return on_signal


atexit.register(cleanup)
os._exit = _exit
for _s in (signal.SIGTERM, signal.SIGHUP):
    try:
        _h = signal.getsignal(_s)
        if _h == signal.SIG_DFL:
            signal.signal(_s, _on_signal)
        elif callable(_h) and (getattr(_h, "__module__", None) or "").startswith("coverage"):   # a measured run (sigterm = true)
            signal.signal(_s, _then(_h))
    except (ValueError, OSError):      # not the main thread
        pass
