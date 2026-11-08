"""ghbudget.py — the one hourly ledger of the GitHub calls this host makes with its token.

One `gh` token on the host serves everything and GitHub gives it 5,000 REST calls an hour. Before this module only the mirror's writes
were counted, in memory (ghsync.GitHub._writes), so a restart forgot them and nothing counted the reads: the runners page, the side
panel, the merged-PR checks, the comment reader, and anchor-hub, which is a service of its own and calls `gh api`. Now every one of
them goes through this ledger:

    <state>/github/budget.json   {"w": [epoch, …], "r": [epoch, …], "by": {"w": {caller: [epoch, …]}, "r": {…}}}  the calls of the last hour, one stamp each
    <state>/github/budget.lock   flock(2) guards the read-modify-write, so the server and anchor-hub (two processes) share it

The shape is a locked state file, not an in-process queue, because anchor-hub cannot reach the server's memory and a socket would be
a second service to keep up; the same file also survives a restart, which the old in-memory deque did not. It is deliberately the
same kind of thing as ratelimit.json: a small file under <state>/github, written by temp file and rename.

Two caps, one ledger: writes ([github] hourly_budget, 250) and reads ([github] read_budget, 1500). A write over its cap sleeps in
ghsync's paced queue until the oldest stamp of the hour expires; a read over its cap is refused at once with the seconds until it
would be allowed (GitHubBudget in ghsync, RunnersError in runners.py, an error in anchor-hub's gh()), because a page or a poll cannot
sleep for minutes: its caller degrades or tries again at its next pass. A 304 (a conditional read answered "unchanged") is never
counted, as GitHub does not count it either; neither is a call that never reached GitHub (no network) nor GET /rate_limit.

Who made a call: every call may carry a caller tag (one of CALLERS: which part of stackshot asked), given as `caller=` to note() and take(), or
for a block of code with `with tag("step_proof"):` (a thread's tag, which the GitHub client reads when its request names none). The tags are
kept beside the stamps, in the optional "by" key, so "w" and "r" mean what they always did and an older reader or writer of the file ignores or drops "by"
without harm. A call with no tag, an unknown tag, or one an older process made is "other": by_caller() counts it as the stamps of the hour that no
tag claims, so the per-caller counts always add up to the totals. Nothing here changes what a cap counts.

Never raises: a ledger that cannot be read or written falls back to the process's own memory for that call (the pre-ledger behaviour).
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from stackshot.core import config as _cfg  # noqa: E402

HOUR = 3600.0
DEFAULT_WRITES = 250        # writes an hour ([github] hourly_budget)
DEFAULT_READS = 1500        # counted reads an hour ([github] read_budget): with the writes, a third of the token's 5,000, the rest left to sessions and CI
LEDGER_NAME = "budget.json"
LOCK_NAME = "budget.lock"
WRITE, READ = "w", "r"
BY = "by"                   # the optional key holding {kind: {caller: [stamps]}}: only callers other than "other" are kept, "other" is what no tag claims
OTHER = "other"
CALLERS = ("done_check", "step_proof", "event_wait", "release", "receivers", "ghsync", "comments", OTHER)   # a tag outside this list is "other" (it bounds the file)

_MEM: dict[str, Any] = {WRITE: [], READ: [], BY: {WRITE: {}, READ: {}}}     # the fallback when the file cannot be used
_MEM_LOCK = threading.Lock()
_TAG = threading.local()    # the calling thread's tag (tag())


def norm(caller: Any) -> str:
    """A caller tag as the ledger keeps it: one of CALLERS, else "other"."""
    c = str(caller or "").strip().lower()
    return c if c in CALLERS else OTHER


def current() -> str:
    """The calling thread's tag set by tag(), "" when there is none."""
    return str(getattr(_TAG, "name", "") or "")


@contextmanager
def tag(caller: str) -> Iterator[None]:
    """Calls made by this thread inside the block are tagged `caller` unless they name their own (the GitHub client reads it when a request passes none).
    Nests: the outer tag is back at the end."""
    before = getattr(_TAG, "name", "")
    _TAG.name = norm(caller)
    try:
        yield
    finally:
        _TAG.name = before


def _int(key: str, default: int) -> int:
    try:
        return max(1, int(_cfg.get("github", key, default=default)))
    except (TypeError, ValueError):
        return default


def write_cap() -> int:
    """[github] hourly_budget: the writes an hour. Live."""
    return _int("hourly_budget", DEFAULT_WRITES)


def read_cap() -> int:
    """[github] read_budget: the counted reads an hour (a 304 is not counted). Live."""
    return _int("read_budget", DEFAULT_READS)


LOCK_WAIT_S = 2.0           # how long a call waits for the lock before it uses the process's own memory for that call
_WARN_EVERY_S = 60.0
_warned = [0.0]


def _warn(why: str) -> None:
    """One stderr line, at most one a minute: the ledger is not usable and this process counts in its own memory for now."""
    t = time.monotonic()
    if t - _warned[0] >= _WARN_EVERY_S or not _warned[0]:
        _warned[0] = t
        print(f"ghbudget: the shared ledger is not usable ({why}); counting in this process's memory for now", file=sys.stderr, flush=True)


@contextmanager
def _locked() -> Iterator[Path]:
    d = _cfg.state("github")
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(d / LOCK_NAME), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        end = time.monotonic() + LOCK_WAIT_S
        while True:                               # one open file description per call: it excludes the threads of this process as well as the other process
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:       # a holder that does not let go (stuck, or a dead disk): no call waits more than this
                    raise TimeoutError(f"the lock was held for {LOCK_WAIT_S:g} s")
                time.sleep(0.01)
        yield d / LEDGER_NAME
    finally:
        os.close(fd)                              # closing drops the lock


def _num(t: Any) -> bool:
    return isinstance(t, (int, float)) and not isinstance(t, bool)


def _stamps(rows: Any, now: float) -> list[float]:
    rows = rows if isinstance(rows, list) else []          # anything but a list (a number, a string, a dict) is no stamps
    return sorted(float(t) for t in rows if _num(t) and now - HOUR < float(t) <= now + 60)


def _read(p: Path, now: float) -> dict[str, Any]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}                                  # no file, or a torn or unreadable one: a fresh hour, never a failure
    out: dict[str, Any] = {k: _stamps(raw.get(k) if isinstance(raw, dict) else None, now) for k in (WRITE, READ)}
    by = raw.get(BY) if isinstance(raw, dict) else None        # a file from before the tags has no "by": every call in it is "other"
    out[BY] = {}
    for k in (WRITE, READ):
        rows = by.get(k) if isinstance(by, dict) else None
        out[BY][k] = {c: s for c, v in (rows.items() if isinstance(rows, dict) else ()) if c in CALLERS and c != OTHER and (s := _stamps(v, now))}
    return out


def _save(p: Path, d: dict[str, Any]) -> None:
    """Written by temp file and rename; each list keeps only its newest 4 x cap stamps (a runaway caller cannot grow the file without bound)."""
    keep = {WRITE: 4 * write_cap(), READ: 4 * read_cap()}
    tenth = lambda t: math.floor(t * 10) / 10       # down to a tenth of a second, never up: a stamp must not land ahead of the clock (a rounded-up one made the next wait "an hour and 0.05 s")
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    out: dict[str, Any] = {k: [tenth(t) for t in d[k][-keep[k]:]] for k in (WRITE, READ)}
    by = d.get(BY) or {}
    out[BY] = {k: {c: [tenth(t) for t in v[-keep[k]:]] for c, v in (by.get(k) or {}).items() if v} for k in (WRITE, READ)}
    tmp.write_text(json.dumps(out) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _txn(now: float, fn: Callable[[dict[str, Any]], Any], save: bool) -> Any:
    """fn(the ledger of the last hour), under the lock; saved when `save`. The process's own memory for this call when the file cannot be used
    (an unwritable folder, a lock held too long), with one rate-limited stderr line."""
    try:
        with _locked() as p:
            d = _read(p, now)
            out = fn(d)
            if save:
                _save(p, d)
            return out
    except Exception as e:  # noqa: BLE001  -- a ledger never breaks a call
        _warn(f"{type(e).__name__}: {e}"[:160])
        with _MEM_LOCK:
            for k in (WRITE, READ):
                _MEM[k] = [t for t in _MEM[k] if now - HOUR < t]
                _MEM[BY][k] = {c: kept for c, v in _MEM[BY][k].items() if (kept := [t for t in v if now - HOUR < t])}
            out = fn(_MEM)
            return out


def _wait(d: dict[str, Any], kind: str, cap: int, now: float) -> float:
    rows = d[kind]
    if len(rows) < cap:
        return 0.0
    return max(1.0, rows[len(rows) - cap] + HOUR - now)        # the call is allowed once the (count - cap + 1)th oldest stamp is an hour old


def count(kind: str, now: float | None = None) -> int:
    """The counted calls of a kind (WRITE or READ) in the last hour."""
    now = time.time() if now is None else now
    return int(_txn(now, lambda d: len(d[kind]), False))


def wait(kind: str, cap: int | None = None, now: float | None = None) -> float:
    """Seconds until one more call of this kind is allowed; 0.0 when there is room now. Records nothing."""
    now = time.time() if now is None else now
    c = (write_cap() if kind == WRITE else read_cap()) if cap is None else int(cap)
    return float(_txn(now, lambda d: _wait(d, kind, c, now), False))


def _add(d: dict[str, Any], kind: str, now: float, caller: str) -> None:
    d[kind].append(now)
    if caller != OTHER:
        d.setdefault(BY, {WRITE: {}, READ: {}}).setdefault(kind, {}).setdefault(caller, []).append(now)


def _tag_of(caller: str | None) -> str:
    """The tag a call is kept under: the one it names, else its thread's (tag()), else "other"."""
    return norm(caller) if caller else (current() or OTHER)


def note(kind: str, now: float | None = None, caller: str | None = None) -> None:
    """One call of this kind made (and answered by GitHub, a 304 excepted): into the ledger, under `caller` (one of CALLERS; none given: the thread's tag, else "other")."""
    now = time.time() if now is None else now
    who = _tag_of(caller)
    _txn(now, lambda d: _add(d, kind, now, who), True)


def take(kind: str, cap: int | None = None, now: float | None = None, caller: str | None = None) -> float:
    """Reserve one call atomically: 0.0 and the stamp recorded when there is room, else the seconds to wait (nothing recorded).
    What a write does before it is sent. `caller` as in note()."""
    now = time.time() if now is None else now
    c = (write_cap() if kind == WRITE else read_cap()) if cap is None else int(cap)
    who = _tag_of(caller)

    def go(d: dict[str, Any]) -> float:
        w = _wait(d, kind, c, now)
        if w <= 0:
            _add(d, kind, now, who)
        return w
    return float(_txn(now, go, True))


def _by_caller(d: dict[str, Any]) -> dict[str, dict[str, int]]:
    """{"reads": {caller: n}, "writes": {caller: n}} of one hour's ledger: the tagged callers that made a call, and "other" (the stamps no tag claims, so the
    callers add up to the total) when there is one."""
    out: dict[str, dict[str, int]] = {}
    for kind, name in ((READ, "reads"), (WRITE, "writes")):
        tagged = {c: len(v) for c, v in sorted((d.get(BY) or {}).get(kind, {}).items()) if v}
        rest = len(d[kind]) - sum(tagged.values())
        if rest > 0:
            tagged[OTHER] = rest
        out[name] = tagged
    return out


def by_caller(now: float | None = None) -> dict[str, dict[str, int]]:
    """The last hour's counted calls by caller: {"reads": {"step_proof": 12, "other": 40}, "writes": {...}}; each kind's numbers add up to its count()."""
    now = time.time() if now is None else now
    return _txn(now, _by_caller, False)


def status(now: float | None = None) -> dict[str, Any]:
    """{"writes": n, "write_cap": c, "reads": n, "read_cap": c, "by_caller": {"reads": {caller: n}, "writes": {caller: n}}} for the last hour."""
    now = time.time() if now is None else now
    w, r, by = _txn(now, lambda d: (len(d[WRITE]), len(d[READ]), _by_caller(d)), False)
    return {"writes": int(w), "write_cap": write_cap(), "reads": int(r), "read_cap": read_cap(), "by_caller": by}


def peek(now: float | None = None) -> dict[str, Any] | None:
    """status() for a page that must stay cheap: lock-free (the file is replaced by rename, so a read sees a whole one), no folder made, nothing
    written, and the process's memory not consulted. None when there is no ledger file yet. The counts may lag a call that is being written."""
    now = time.time() if now is None else now
    p = _cfg.state("github", LEDGER_NAME)
    if not p.exists():
        return None
    try:
        d = _read(p, now)
    except Exception:  # noqa: BLE001  -- a page never fails for a ledger
        return None
    return {"writes": len(d[WRITE]), "write_cap": write_cap(), "reads": len(d[READ]), "read_cap": read_cap(), "by_caller": _by_caller(d)}


def calls_line(now: float | None = None) -> str:
    """The one line the signed-in pages show: "github calls this hour: writes n/cap, reads n/cap" ("" when there is no ledger yet)."""
    b = peek(now)
    return "" if b is None else f"github calls this hour: writes {b['writes']}/{b['write_cap']}, reads {b['reads']}/{b['read_cap']}"


def held_words(wait_s: float) -> str:
    """The seconds of a held read as a person reads them ("about 12 min"; never a bare number a log reader could take for an HTTP code)."""
    m = int((float(wait_s) + 59) // 60)
    return f"about {m} min" if m > 1 else "under a minute"
