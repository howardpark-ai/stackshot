"""keeper_reads.py — what a later stage can gate on before it removes the old keeper forms: a gauge of the keepers only an old form names, and a per-site record of the readers that can still answer a keeper question from one.

The keeper is a mark on one agent (keeper.py). The old forms are a page's own name line (`display-name:`, the registry's `session` with the role "name"), an `agent:` line, the `legacy_session` and
`legacy_role` a mark took the place of, and the role `keeper` of a name-line session in roles.json. Two things are kept, in one small file:

    <state>/keeper-reads.json   {"schema": 1, "epoch": <random id, made when the file is created>, "since": <ISO>, "flushed": <ISO of the last successful write>, "restarted": <ISO, only after a damaged file was replaced>, "refused": <ISO, only after a gauge was refused by a flush that could not compute it again>,
                                 "legacy": {"count": N, "keys": [<up to 50 page keys>], "at": <ISO of when it was computed: the reader compares it with now>, "gen": <whole number>, "epoch": <the file's epoch>},
                                 "sites": {<site>: {"last": <ISO of the last read>, "keys": [<distinct row keys read, at most 200>]}}}
    stackshot keeper-reads      prints the gauge, each instrumented site (last read in the instance's timezone, distinct keys), the readers that stay, and a loud line when nothing is being recorded

  * The gauge is the number of registry rows whose `keeper_source` is `legacy` (only an old form names the keeper), with their page keys; `projects.sync` refreshes it each time it runs. Zero means every
    keeper is a mark or derived.
  * A site is a reader that answers a keeper question from an old form that decides the row's keeper (`keeper_source` legacy: no mark on the row or its project), a removal candidate: the kind of read and the function
    that made it ("old form as the keeper <- anchors.notice_name"). A site counts each distinct row key once between two writes of a process, so volume (a registry build re-reads every row) cannot hide a quiet week; a read where a
    mark answers is never counted, and each gauge written drops the keys a site holds that are not rows of it, so right after a process writes a gauge its sites hold only rows of that gauge (none at zero). A process remembers a key it counted only until the write that put it in the file (a key another process pruned from the file is counted again by the next read, not suppressed by a memory of an older file). The readers of the project's name, its agent-name prefix and its scope read the name line by design and
    are not instrumented (`BY_DESIGN`); they stay after the keeper moves to marks.

The file is the only thing a process writes, at most once a minute (a timer on a daemon thread when the process makes no other call) and when it ends, by one atomic write under a lock on a lock file beside it, taken without waiting: a lock another process holds skips this
write and the counts stay in memory for the next one, so a read never waits on a file; only the write at the end of the process waits for it, up to two seconds, because there is no next one. A write that fails (no state folder, a read-only standby, a full disk) is kept for the next try and never changes
what a read answers; the file's `flushed` time says when a write last succeeded, so a counter that cannot write does not look like a week of no reads. The gauge carries a generation, a whole number that grows by one with every gauge written, and an epoch, a random id the file gets from the moment it is created (a file created again after it was removed, or replaced after damage, has a new epoch, with or without a gauge; a file a previous version wrote has none until its first gauge is written). A publisher reads `snapshot()`, the (epoch, generation) on disk, BEFORE it computes its rows, and its gauge is written only if the file still holds exactly that pair when the write is made, which is checked again under the lock; a refused gauge is computed again from the registry as it is then and offered once more (bounded: one retry, made outside the lock and with no sleep). So an older publisher that flushes last, a file removed or replaced since, and a process that is slow between reading and writing do not put a gauge computed from older rows over a newer one by the compare, whatever the clocks say (the time in `at` is never compared between publishers; the reader compares it with now). A refusal in a flush that could not compute the rows again (the timer's, a read's, the one at exit, a sync whose retry was refused, or a sync given its registry) leaves the file's gauge as it is and is written down as `refused`: the gauge in the file, written by an earlier flush that may be this process's own, may be the one from older rows, nothing says which is newer, so while `refused` stands (any text, an empty one too) the gauge is unknown (a loud line in the report, status 2) and the next gauge written clears it; a process that recorded one writes its next gauge at once, so the unknown ends at the next sync. A refused gauge that is computed again is written at once, not at the next minute. The stamp of no file (a missing or damaged one) is ABSENT, which a file that exists never matches, so a zero computed against no file is not accepted over a file made again by a writer that gave it no epoch. What is not guaranteed: a process that computed rows from an older registry and only then took its snapshot can still publish one stale gauge (after a refusal on record too: a refusal leaves the epoch and generation as they are), which the next sync replaces; a later stage that removes the old forms recomputes the legacy rows from the live record and does not trust the gauge alone. One flush runs at a time in a process: the flush at exit waits for one the timer started
(and a failed write removes its own temporary file, named by the process and a counter, never one another writer made; a temporary file left by a writer that was killed is swept by the next write, under the lock, once it is more than a minute old). The wait before the next write is measured on the monotonic clock, so a wall clock that steps back delays nothing. A damaged file is replaced and the old one kept once as `keeper-reads.json.bad`: a malformed value at any level, a number that is not finite (an `Infinity` or a `1e999` anywhere, extra fields included) or not a whole number where one is due, a gauge with no `count` or no list of keys, or a count below the number of keys it lists, a file nested deeper than it ever is or larger than a counter file can be. A damaged gauge is unknown, never zero, and so is a gauge computed more than GAUGE_STALE seconds ago, one with no readable time, or one dated ahead of the clock by more than GAUGE_AHEAD seconds (its publisher has stopped, or the clock stepped; the file's heartbeat, which any process's read moves, does not say the gauge is current). A document a caller hands to `count_of` is checked as the file is, and the report and the exit status of `stackshot keeper-reads` read the clock once, so a gauge at the edge of the bound is current in both or in neither. What a process had counted when it was killed (a stop signal runs no exit hook), or when the lock stayed held for more than two seconds at its exit, is lost. Stdlib only at load: the config and the standby test are imported where the file is written."""
from __future__ import annotations

import atexit
import datetime as dt
import itertools
import json
import math
import os
import sys
import threading
import time

FILE = "keeper-reads.json"
EVERY = 60.0                      # seconds between two writes of one process; a process that lives less writes once, when it ends
SCHEMA = 1
KEYS_PER_SITE = 200               # distinct row keys kept per site
GAUGE_KEYS = 50                   # page keys listed with the gauge
EXIT_WAIT = 2.0                   # seconds the flush at process exit waits for the lock (a write holds it a few milliseconds)
STALE = 86400.0                   # a file written longer ago than this is reported as not recording
GAUGE_AHEAD = 5.0                 # a gauge dated further ahead of the clock than this (seconds; the writer is the same host, and `at` has one-second resolution) is unknown, not current
GAUGE_STALE = 300.0               # a gauge computed longer ago than this (five minutes, several syncs: the runner syncs about once a minute, counted from the end of a round, and a sync writes the gauge at once) is unknown, not its count
TMP_STALE = 60.0                  # a temporary file of the counter older than this, found under the lock, was left by a writer that was killed
RAW_SHOWN = 40                    # the report shows at most this many characters of a refusal record that is not a time
RETRIES = 1                       # a refused gauge is computed again and offered once more, no more
ABSENT = (None, -1)               # the stamp of no file (missing, or damaged and so replaced by the next write): no file that exists has it, a file without an epoch or a gauge is (None, 0)

# the readers that stay: they read the name line to name the project, its agent-name prefix or its scope, never to say who keeps it
BY_DESIGN = (
    "keeper.name_line, read for the project's name, its agent-name prefix and its scope: projects._name_prefixes, projects._fields_row, projects.all_fields, projects._entry_scope, projects.name_line, "
    "the top-project name lookup in projects.py, project_registry._overlay",
    "the name checks of project_verbs (derive_entry, _name_taken): a project's name is its page's `display-name:`",
)

# readers of an old form that are not instrumented, because nothing at the read says whether the old form decided: they stay until the readers are removed (the gauge is what says no row needs them)
UNTIL_REMOVED = (
    "keeper.names_of: a row's `legacy_session` exists only under a mark, so it is never what names the keeper",
    "pages.keeper_of: reads a page's own lines, and a mark lives in the project record, which it does not see",
    "keeper.fields and the page row built in project_verbs: they run on rows the record has not been laid over yet",
)

QUIET = ("the gauge at zero says no row's keeper depends on an old form; a week with no read at a site above says those readers were not asked for any row the gauge still counts; the readers listed below as not counted are not covered")

_LOCK = threading.Lock()
_PENDING: dict[str, list] = {}    # site -> [last read (epoch), set of new keys]
_SEEN: dict[str, set] = {}        # site -> the keys counted since this process's last write (a key written leaves it: the file is what says a key is counted)
_LAST: dict[str, float] = {}      # site -> the monotonic time of the last read this process recorded
_STATE: dict = {"flushed": time.monotonic(), "hooked": False, "gauge": None, "gauge_at": 0.0, "gauge_base": ABSENT, "fresh": False, "refused": False, "recorded": False, "beat": False, "timer": None}
_NAMES = itertools.count(1)       # the counter in the names of this process's temporary files
_DEADLINE = time.monotonic        # the wait for the file's lock is timed on the real monotonic clock
_WRITE = threading.Lock()         # one flush at a time in this process: the flush at exit waits for one the timer started
MAX_DEPTH = 16                    # the deepest nesting a counter file has is 4; a file nested deeper is damaged
MAX_BYTES = 4 * 1024 * 1024       # and one larger than this is not a counter file


def note(kind: str, key: str, up: int = 2) -> None:
    """Count one read that answered a keeper question from an old form: `kind` names the form, `key` the registry row (a page key) or the session it read, and the site is `kind` and the function `up` frames above
    this call (2: the caller of the helper that notes, 1: the function that notes itself). A key already counted since this process's last write only moves the site's last-read time, and that at most once a minute (the minute is the monotonic clock's). Never raises
    and never waits on a file in the cases that matter: the due write is skipped when another process holds the file's lock."""
    try:
        f = sys._getframe(up)
        site = f"{kind} <- {str(f.f_globals.get('__name__') or '?').rsplit('.', 1)[-1]}.{f.f_code.co_name}"
        now = time.time(); tick = time.monotonic(); key = str(key or "")
        with _LOCK:
            seen = _SEEN.setdefault(site, set())
            new = key not in seen
            if new:
                seen.add(key)
            if new or tick - _LAST.get(site, -math.inf) >= EVERY:
                _LAST[site] = tick
                e = _PENDING.setdefault(site, [now, set()])
                e[0] = now
                if new:
                    e[1].add(key)
            due = bool(_PENDING) and tick - _STATE["flushed"] >= EVERY
            hook = not _STATE["hooked"]
            if hook:
                _STATE["hooked"] = True
        if hook:
            atexit.register(_at_exit)
        if due:
            flush()
        else:
            _arm()
    except Exception:  # noqa: BLE001 — a count never changes an answer
        pass


def snapshot() -> tuple:
    """The (epoch, generation) the file holds now: the file's epoch (None for one a previous version wrote and no gauge has been written to since) and the generation of its gauge (0 for none); ABSENT, which no file that exists has, for no file or an
    unreadable one. A publisher takes this BEFORE it computes the rows of its gauge and hands it to `gauge`, which is written only while the file still holds exactly this pair. Never raises."""
    try:
        d, problem = load()
        return ABSENT if problem else _stamp_of(d)
    except Exception:  # noqa: BLE001
        return ABSENT


def gauge(keys, base: tuple | None = None, again=None, _tries: int = 0) -> None:
    """The rows whose keeper only an old form names (`keeper_source` legacy), by page key: set by the publisher each time it runs. `base` is the `snapshot()` the publisher took before it computed `keys` (taken here when it is not
    given, which is later than the rows and so a weaker promise); the gauge is written with the next flush (at once when the set changed), and only while the file still holds that (epoch, generation), checked again under the file's lock.
    A gauge the lock check refused is computed again by `again()` (a function that reads the registry now and returns the keys, or None when it has none to give; called after a new `snapshot()` and outside the file's lock) and offered once more: at most RETRIES times. Never raises."""
    try:
        ks = sorted({str(k) for k in keys})
        base = snapshot() if base is None else (base[0], base[1])
        with _LOCK:
            changed = _STATE["gauge"] != ks
            _STATE["gauge"] = ks; _STATE["gauge_at"] = time.time(); _STATE["gauge_base"] = base; _STATE["fresh"] = True; _STATE["refused"] = False; _STATE["beat"] = True
            due = changed or _tries > 0 or _STATE["recorded"] or time.monotonic() - _STATE["flushed"] >= EVERY       # a retry is written at once: the refused flush just before it moved the minute, and a corrected gauge does not wait for the next one; the same while this process has recorded a refusal (the gauge is unknown until a gauge is written, so the next sync writes at once)
            hook = not _STATE["hooked"]
            if hook:
                _STATE["hooked"] = True
        if hook:
            atexit.register(_at_exit)
        if due:
            flush()
        else:
            _arm()
        if again is not None and _tries < RETRIES:
            with _LOCK:
                refused = _STATE["refused"]; _STATE["refused"] = False
            if refused:
                again_base = snapshot()
                more = again()
                if more is not None:                  # None: nothing to compute from (an empty registry), so nothing is published
                    gauge(more, again_base, again, _tries + 1)
    except Exception:  # noqa: BLE001
        pass


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_of(lg) -> int:
    """The generation of a gauge of the file: 0 for none, or for a gauge a previous version wrote (it had no generation, and its time is never compared)."""
    g = lg.get("gen") if isinstance(lg, dict) else None
    return g if _is_int(g) else 0


def _stamp_of(d) -> tuple:
    """The (epoch, generation) of a document of the file: the epoch is the file's (or its gauge's, for a file a previous version wrote) and None when there is none; the generation is 0 without a gauge."""
    lg = d.get("legacy") if isinstance(d, dict) else None
    e = d.get("epoch") if isinstance(d, dict) else None
    if not (isinstance(e, str) and e) and isinstance(lg, dict): e = lg.get("epoch")
    return (e if isinstance(e, str) and e else None, _gen_of(lg))


def _path():
    from stackshot.core import config as _cfg
    return _cfg.state(FILE)


def _after(delay: float, fn):
    """Run `fn` once after `delay` seconds on a daemon thread (a process never waits for it at its end); the started timer, which has `cancel`."""
    t = threading.Timer(max(0.0, delay), fn)
    t.daemon = True
    t.start()
    return t


def _arm() -> None:
    """Make sure what waits (a count, or the gauge's heartbeat) is written when the minute since the last write is up, without another call: one timer at a time. Never raises."""
    try:
        with _LOCK:
            if _STATE["timer"] is not None or not (_PENDING or _STATE["beat"]):
                return
            _STATE["timer"] = _after(EVERY - (time.monotonic() - _STATE["flushed"]), _tick)
    except Exception:  # noqa: BLE001
        with _LOCK:
            _STATE["timer"] = None


def _tick() -> None:
    """The timer's flush: what a process counted and then left alone is written when its minute is up."""
    with _LOCK:
        _STATE["timer"] = None
    flush()


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _no_constant(name: str):
    raise ValueError(f"{name} is not a number")


def _finite(text: str) -> float:
    """A float of the file: one that does not fit (a `1e999` reads as infinity) is damage like `Infinity`, wherever it stands, extra fields included, because the next write would put `Infinity` in the file."""
    v = float(text)
    if not math.isfinite(v):
        raise ValueError(f"{text[:20]} is not a finite number")
    return v


def _depth_ok(text: str) -> bool:
    """True when the brackets of `text` nest no deeper than MAX_DEPTH (strings skipped)."""
    depth = 0; in_str = False; esc = False
    for c in text:
        if in_str:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
        elif c == '"': in_str = True
        elif c in "[{":
            depth += 1
            if depth > MAX_DEPTH: return False
        elif c in "]}": depth -= 1
    return True


def _native(v) -> bool:
    """True when `v` holds only what JSON reads back as it is: dicts with string keys, lists, strings, numbers that are finite, booleans and None. A tuple, a set or a key that is not a string is converted by JSON, so a check of the converted copy says nothing about it."""
    if isinstance(v, dict):
        return all(isinstance(k, str) and _native(x) for k, x in v.items())
    if isinstance(v, list):
        return all(_native(x) for x in v)
    if isinstance(v, float):
        return math.isfinite(v)
    return v is None or type(v) in (str, int, bool)


def _doc_of(text: str) -> dict:
    """The counter file's content, or ValueError when it is not one: every level is checked (the sites, each site's last read and keys, the gauge), so a malformed value is a damaged file and not a crash later."""
    if len(text) > MAX_BYTES or not _depth_ok(text):
        raise ValueError("not a counter file (too large or nested too deeply)")
    try:
        d = json.loads(text, parse_constant=_no_constant, parse_float=_finite)
    except RecursionError:
        raise ValueError("nested too deeply") from None
    return _check(d)


def _check(d) -> dict:
    """`d` itself, or ValueError when it is not a counter file's content: the checks of every level, for a document read from the file and for one a caller hands over."""
    if not (isinstance(d, dict) and isinstance(d.get("sites", {}), dict)):
        raise ValueError("not a counter file")
    for k in ("since", "flushed", "restarted", "refused"):
        if k in d and not isinstance(d[k], str):
            raise ValueError(f"{k} is not a time")
    if "epoch" in d and not (isinstance(d["epoch"], str) and d["epoch"]):
        raise ValueError("epoch is not an id")
    for name, v in d.get("sites", {}).items():
        if not (isinstance(v, dict) and isinstance(v.get("last", ""), str) and (v.get("keys") is None or _is_str_list(v["keys"]))):
            raise ValueError(f"site {str(name)[:60]} is malformed")
    lg = d.get("legacy")
    if lg is not None and not (isinstance(lg, dict) and _is_int(lg.get("count")) and _is_str_list(lg.get("keys")) and len(lg["keys"]) <= lg["count"] and isinstance(lg.get("at", ""), str)
                               and (lg.get("gen") is None or _is_int(lg["gen"])) and (lg.get("epoch") is None or (isinstance(lg["epoch"], str) and lg["epoch"])) and (lg.get("stamp") is None or _is_num(lg["stamp"]))):
        raise ValueError("the gauge is malformed")      # no count, no list of keys, or a count below the keys it lists would read as zero where rows are legacy: damaged, never zero
    return d


def _at_exit() -> None:
    """The flush at the end of the process: there is no next flush, so a flush the timer has started is waited for, and then the file's lock, both within EXIT_WAIT seconds."""
    with _LOCK:
        t = _STATE["timer"]; _STATE["timer"] = None
    if t is not None:
        t.cancel()
    flush(EXIT_WAIT)


def flush(wait: float = 0.0) -> bool:
    """Add what this process counted to the file (and its heartbeat): read it, add, write it back atomically, under a lock on a lock file beside it. The lock is taken without waiting (`wait` 0, every flush while the
    process runs: a read never waits on the file), or for at most `wait` seconds (the flush at exit, which has no next one). One flush runs at a time in a process: a flush that finds another one writing (the timer's)
    returns False at once and takes nothing, except at exit, which waits for it (within `wait`) so the counts it holds are in the file when the process ends. → True when written (or nothing was waiting); False when the write
    failed or another process held the lock: the counts stay for the next flush, and are lost when the process ends first. A damaged file is kept as `.bad` and started again. Never raises."""
    deadline = _DEADLINE() + wait
    if not (_WRITE.acquire(timeout=wait) if wait > 0 else _WRITE.acquire(blocking=False)):
        if not wait:
            _arm()
        return False
    try:
        return _flush(deadline)
    finally:
        _WRITE.release()


def _sweep(p) -> None:
    """Under the file's lock: remove the temporary files of the counter that are more than TMP_STALE old. The lock is what says no live writer of this file is between creating its temporary file and replacing the file with it, so what is left is a
    writer that was killed. Never raises."""
    try:
        now = time.time()
        for q in list(p.parent.glob(f".{p.name}.*.tmp")) + [p.with_name(f".{p.name}.tmp")]:
            try:
                if now - q.stat().st_mtime > TMP_STALE:
                    q.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


def _flush(deadline: float) -> bool:
    with _LOCK:
        take = {s: [e[0], set(e[1])] for s, e in _PENDING.items()}; _PENDING.clear()
        gauge_now = _STATE["gauge"]; gauge_at = _STATE["gauge_at"]; gauge_base = _STATE["gauge_base"]; fresh = _STATE["fresh"]; _STATE["fresh"] = False; beat = _STATE["beat"]; _STATE["beat"] = False; _STATE["flushed"] = time.monotonic()
    if not take and gauge_now is None and not beat:
        return True
    try:
        from stackshot.core import readonly as _ro
        if _ro.is_read_only():
            raise OSError("read only")
        p = _path()
        if not p.parent.is_dir():          # a state folder that is gone (a test's, after its cleanup): nothing is made for a count
            raise OSError("no state folder")
        import fcntl
        with open(str(p) + ".lock", "a") as lk:
            while True:
                try:
                    fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:        # the lock is held: wait for it, within the deadline; any other error cannot clear by waiting and ends the write at once
                    if _DEADLINE() >= deadline:
                        raise OSError("locked by another process")
                    time.sleep(0.005)
            try:
                _sweep(p)
                d, restarted, created = {}, "", False
                try:
                    d = _doc_of(p.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    created = True
                except ValueError:         # damaged: keep it once as .bad, start again, say so in the file
                    os.replace(p, p.with_name(p.name + ".bad"))
                    d, restarted, created = {}, _iso(time.time()), True
                sites = d.get("sites") if isinstance(d.get("sites"), dict) else {}
                for site, (last, keys) in take.items():
                    s = sites.get(site) if isinstance(sites.get(site), dict) else {}
                    have = [str(k) for k in (s.get("keys") or []) if isinstance(k, str)]
                    sites[site] = {"last": max(str(s.get("last") or ""), _iso(last)), "keys": sorted(set(have) | keys)[:KEYS_PER_SITE]}
                out = {"schema": SCHEMA, "since": str(d.get("since") or "") or _iso(time.time()), "flushed": _iso(time.time()), "sites": sites}
                if restarted or d.get("restarted"):
                    out["restarted"] = restarted or str(d["restarted"])
                held = d.get("legacy") if isinstance(d.get("legacy"), dict) else None
                disk = ABSENT if created else _stamp_of(d); refused = False       # a file made now (none before, or a damaged one replaced) is no file: what a publisher saw as none is the only stamp it matches
                epoch = disk[0]                        # the file's epoch: a file made now (none before, or a damaged one replaced) gets its own, whether or not a gauge is written; a file of a previous version gets one with its first gauge
                if epoch is None and created:
                    epoch = os.urandom(8).hex()
                if gauge_now is not None and fresh:
                    if disk == tuple(gauge_base):          # the file still holds the (epoch, generation) the rows were computed against: no gauge was written, and the file was not replaced, since: this one is the newest
                        epoch = epoch or os.urandom(8).hex()
                        out["legacy"] = {"count": len(gauge_now), "keys": gauge_now[:GAUGE_KEYS], "at": _iso(gauge_at), "gen": max(disk[1], 0) + 1, "epoch": epoch}
                        rows = set(gauge_now)
                        for v in sites.values():        # a site's keys are rows of the gauge: the keys of rows that have since got a mark (or agents) go with them
                            v["keys"] = [k for k in (v.get("keys") or []) if k in rows]
                    else:
                        refused = True                  # another gauge (or another file) since: the file's stays, and the publisher is told so it can compute again
                wrote = "legacy" in out
                if "legacy" not in out and held:        # nothing new to publish, or a refused gauge: the file's stays
                    out["legacy"] = held
                if refused:                             # a timer or exit flush has no publisher to compute again (it holds no registry): the refusal is written down, and the gauge reads as unknown (the one in the file may be from older rows) until the next gauge is written
                    out["refused"] = _iso(time.time())
                elif "legacy" not in out or out["legacy"] is held:
                    if "refused" in d: out["refused"] = str(d["refused"])        # kept by a read flush; only a gauge written clears it (a record that is present counts, whatever its text)
                if epoch:
                    out["epoch"] = epoch
                tmp = p.with_name(f".{p.name}.{os.getpid()}.{next(_NAMES)}.tmp")        # this process's own name: nobody else writes it, and only this writer removes it
                try:
                    with open(tmp, "w", encoding="utf-8") as fh:
                        fh.write(json.dumps(out, indent=1, sort_keys=True)); fh.flush(); os.fsync(fh.fileno())
                    os.replace(tmp, p)
                except BaseException:
                    try: tmp.unlink(missing_ok=True)       # inside the lock, before it is released
                    except OSError: pass
                    raise
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
        with _LOCK:
            if refused:
                _STATE["refused"] = True; _STATE["recorded"] = True       # the retry of a sync takes the first; the second stays until a gauge of this process is written, so the next gauge() is due at once
            elif wrote:
                _STATE["recorded"] = False
            for site, (_last, ks) in take.items():        # a key written is the file's to remember: a read after this one is counted again (a key another process pruned from the file is not suppressed by this process's memory)
                if site in _SEEN:
                    _SEEN[site] -= ks
        return True
    except Exception:  # noqa: BLE001 — put the counts back: the next flush adds them
        with _LOCK:
            for site, (last, keys) in take.items():
                e = _PENDING.setdefault(site, [last, set()])
                e[0] = max(e[0], last); e[1] |= keys
            _STATE["beat"] = _STATE["beat"] or beat; _STATE["fresh"] = _STATE["fresh"] or fresh
            if gauge_now is not None and _STATE["gauge"] is None:
                _STATE["gauge"] = gauge_now
        _arm()
        return False


def load() -> tuple[dict, str]:
    """(the file as it is, a problem): the problem is "" when it reads, "missing" when there is no file, else why it cannot be read. The document is empty for a problem."""
    try:
        return _doc_of(_path().read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return {}, "missing"
    except (OSError, ValueError) as e:
        return {}, f"unreadable ({e})"


def _gauge_age(lg, now: float | None = None):
    """Seconds since the gauge was computed (its `at`; a time with no zone is the writer's, UTC), or None when it has no time that reads or is dated ahead of the clock by more than GAUGE_AHEAD (a clock that stepped back, or a wrong one at the write)."""
    try:
        t = dt.datetime.fromisoformat(str(lg.get("at") or "").replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        age = (time.time() if now is None else now) - t.timestamp()
    except (ValueError, AttributeError, OverflowError, OSError):
        return None
    return age if age >= -GAUGE_AHEAD else None


def count_of(d: dict | None = None, problem: str | None = None, now: float | None = None) -> int | None:
    """The gauge's count, or None when it is unknown: a missing or damaged file, a file with no gauge yet, a file that records a refused gauge (until the next gauge written), or a gauge computed more than GAUGE_STALE seconds ago (or with no time that reads), because a gauge that is not being refreshed says nothing about
    the rows now, and the file's heartbeat (any process's read moves it) does not say it is current. Unknown is never zero: a removal gate that reads the gauge treats None as not zero."""
    if d is None:
        d, problem = load()
    elif not problem:
        try:
            _doc_of(json.dumps(d))                  # a document a caller hands over is checked as the file is (size, depth, numbers that are not finite): a damaged gauge is unknown, not zero
            if not _native(d):
                raise ValueError("a value JSON would convert")
            _check(d)                               # and its own values are checked, not a JSON copy of them: what the code reads below is the original
        except (ValueError, TypeError, RecursionError, OverflowError):
            return None
    lg = d.get("legacy") if not problem else None
    if not (isinstance(lg, dict) and _is_int(lg.get("count")) and isinstance(lg.get("keys"), list)):
        return None
    if "refused" in d:
        return None                     # a refusal is on record (any text, an empty one too): the gauge in the file is an earlier flush's, which may be the one from older rows, and nothing says which is newer: unknown until the next gauge written clears it
    age = _gauge_age(lg, now)
    return lg["count"] if age is not None and age <= GAUGE_STALE else None


def read() -> dict:
    """The file as it is ({} for a missing or damaged one), with nothing from this process's unwritten counts."""
    return load()[0]


def report(d: dict | None = None, problem: str | None = None, now: float | None = None) -> list:
    """The lines `stackshot keeper-reads` prints: loud lines first when nothing is being recorded, then the gauge, each instrumented site (last read in the instance's timezone, distinct keys) and the readers that stay."""
    from stackshot.core import config as _cfg
    if d is None:
        d, problem = load()
    problem = problem or ""
    now = time.time() if now is None else now
    tz = _cfg.tz()
    def when(s: str) -> str:
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz).strftime("%a %b %-d %H:%M")
        except (ValueError, OverflowError, OSError):
            return "?"
    def offered(s: str) -> str:
        """The time a refusal was recorded, or the text as it stands in the file (one line, cut) when it is not a time."""
        t = when(s)
        if t != "?":
            return t
        raw = " ".join("".join(c for c in s if c.isprintable() or c.isspace()).split())
        return f'at "{raw[:RAW_SHOWN]}{"..." if len(raw) > RAW_SHOWN else ""}" (not a time)' if raw else "at a time that is not written"
    def age(s: str):
        try:
            return now - dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError, OSError):
            return None
    out = []
    if problem == "missing":
        out.append("NOT RECORDING?  there is no counter file: nothing has been recorded here (a state folder that cannot be written, or a service that has not run); this is not a week of no reads")
    elif problem:
        out.append(f"NOT RECORDING?  the counter file is {problem}: nothing can be told from it")
    else:
        fl = str(d.get("flushed") or "")
        a = age(fl) if fl else None
        if a is None:
            out.append("NOT RECORDING?  the counter file carries no time of a last successful write")
        elif a > STALE:
            out.append(f"NOT RECORDING?  the last successful write was {when(fl)}, more than a day ago: if the service ran since, its writes are failing (the counts below are old)")
        if d.get("restarted"):
            out.append(f"a damaged file was replaced {when(str(d['restarted']))}; the old one is {_path().name}.bad, and the counts below start then")
        if "refused" in d:
            state = "the gauge in the file was written by an earlier flush (possibly this process's, possibly another's) and may be from older rows" if isinstance(d.get("legacy"), dict) else "the file holds no gauge (it was removed or replaced since)"
            out.append(f"NOT RECORDING?  a gauge offered {offered(str(d['refused']))} was refused because another gauge or file had come first, and a flush that could not compute the rows again (a timer, a read, the end of a process, a sync whose retry was refused, or a sync with a registry handed to it) left it so: {state}, so the gauge is unknown until the next gauge is written")
        lg0 = d.get("legacy")
        if isinstance(lg0, dict) and count_of(d, problem, now) is None and (_gauge_age(lg0, now) is None or _gauge_age(lg0, now) > GAUGE_STALE):
            out.append(f"NOT RECORDING?  the gauge was computed {when(str(lg0.get('at') or ''))}, which is more than {GAUGE_STALE / 60:g} minutes ago, has no readable time, or is ahead of the clock: its publisher is not refreshing it, whatever the file's last write says")
    if problem:
        out.append("legacy keepers: gauge unknown (the counter file cannot be read, so the gauge cannot be): this is never zero, and no removal can rest on it")
    else:
        lg = d.get("legacy")
        n = count_of(d, problem, now)
        if n is not None:
            keys = [str(k) for k in (lg.get("keys") or [])]
            out.append(f"legacy keepers: {n} registry row(s) whose keeper only an old form names (as of {when(str(lg.get('at') or ''))})" + (": " + ", ".join(keys) + (", ..." if n > len(keys) else "") if keys else ""))
        elif "refused" in d:
            out.append("legacy keepers: gauge unknown (a refused gauge is on record, see above): this is never zero, and no removal can rest on it")
        elif isinstance(lg, dict):
            out.append(f"legacy keepers: gauge unknown (it was computed {when(str(lg.get('at') or ''))}, which is not a current time): this is never zero, and no removal can rest on it")
        else:
            out.append("legacy keepers: gauge unknown (the publisher has not written the gauge yet): this is never zero, and no removal can rest on it")
        sites = d.get("sites") or {}
        since = when(str(d.get("since") or "")) if d.get("since") else "?"
        out.append(f"removal-candidate readers, since {since} (last write {when(str(d.get('flushed') or ''))}): {len(sites)} site(s) read")
        for site, v in sorted(sites.items(), key=lambda kv: (-len((kv[1] or {}).get("keys") or []), kv[0])):
            out.append(f"{len((v or {}).get('keys') or []):>6} key(s)  last {when(str((v or {}).get('last') or ''))}  {site}")
        out.append(QUIET)
    out.append("readers that stay (the name line names the project, its agent-name prefix and its scope):")
    out.extend("  stays  " + s for s in BY_DESIGN)
    out.append("readers not counted, which stay until the readers are removed:")
    out.extend("  until removed  " + s for s in UNTIL_REMOVED)
    return out


def main(argv: list | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="stackshot keeper-reads", description="the keepers only an old form names, and the readers that can still answer a keeper question from one (read only; exits 2 when the gauge is unknown)")
    ap.add_argument("--json", action="store_true", help="the state file's own content")
    a = ap.parse_args(argv)
    d, problem = load()
    now = time.time()                                                  # one reading of the clock for the report and the status: a gauge at the edge of the bound is current in both or in neither
    print(json.dumps(d, indent=1, sort_keys=True) if a.json else "\n".join(report(d, problem, now)))
    return 0 if count_of(d, problem, now) is not None else 2         # an unknown gauge (a missing, damaged or gauge-less file) is not zero: the status says so to whatever reads it


if __name__ == "__main__":
    sys.exit(main())
