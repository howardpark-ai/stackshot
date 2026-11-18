"""keeper_reads.py — what a later stage can gate on before it removes the old keeper forms: a gauge of the keepers only an old form names, and a per-site record of the readers that can still answer a keeper question from one.

The keeper is a mark on one agent (keeper.py). The old forms are a page's own name line (`display-name:`, the registry's `session` with the role "name"), an `agent:` line, the `legacy_session` and
`legacy_role` a mark took the place of, and the role `keeper` of a name-line session in roles.json. Two things are kept, in one small file:

    <state>/keeper-reads.json   {"schema": 1, "since": <ISO>, "flushed": <ISO of the last successful write>, "restarted": <ISO, only after a damaged file was replaced>,
                                 "legacy": {"count": N, "keys": [<up to 50 page keys>], "at": <ISO of when it was computed, for display>, "gen": <whole number>},
                                 "sites": {<site>: {"last": <ISO of the last read>, "keys": [<distinct row keys read, at most 200>]}}}
    stackshot keeper-reads      prints the gauge, each instrumented site (last read in the instance's timezone, distinct keys), the readers that stay, and a loud line when nothing is being recorded

  * The gauge is the number of registry rows whose `keeper_source` is `legacy` (only an old form names the keeper), with their page keys; `projects.sync` refreshes it each time it runs. Zero means every
    keeper is a mark or derived.
  * A site is a reader that answers a keeper question from an old form that decides the row's keeper (`keeper_source` legacy: no mark on the row or its project), a removal candidate: the kind of read and the function
    that made it ("old form as the keeper <- anchors.notice_name"). A site counts each distinct row key once per process, so volume (a registry build re-reads every row) cannot hide a quiet week; a read where a
    mark answers is never counted, and each gauge written drops the keys a site holds that are not rows of it (from the process's own memory of what it has counted too, so a row that is legacy again is counted again when it is read), so right after a process writes a gauge its sites hold only rows of that gauge (none at zero). The readers of the project's name, its agent-name prefix and its scope read the name line by design and
    are not instrumented (`BY_DESIGN`); they stay after the keeper moves to marks.

The file is the only thing a process writes, at most once a minute (a timer on a daemon thread when the process makes no other call) and when it ends, by one atomic write under a lock on a lock file beside it, taken without waiting: a lock another process holds skips this
write and the counts stay in memory for the next one, so a read never waits on a file; only the write at the end of the process waits for it, up to two seconds, because there is no next one. A write that fails (no state folder, a read-only standby, a full disk) is kept for the next try and never changes
what a read answers; the file's `flushed` time says when a write last succeeded, so a counter that cannot write does not look like a week of no reads. The gauge carries a generation, a whole number that grows by one with every gauge written; a publisher notes the generation on disk when it computes its gauge and writes it only if no gauge has been written since (it
reads the generation again under the lock), so an older publisher that flushes last never puts its gauge over a newer one, whatever the clocks say (the time in `at` is for display only and is never compared). One flush runs at a time in a process: the flush at exit waits for one the timer started
(and a failed write removes its temporary file). A damaged file is replaced and the old one kept once as `keeper-reads.json.bad`: a malformed value at any level, a number that is not finite or not a whole number where one is due, a file nested deeper than it ever is or larger than a counter file can be. What a process had counted when it was killed (a stop signal runs no exit hook), or when the lock stayed held for more than two seconds at its exit, is lost. Stdlib only at load: the config and the standby test are imported where the file is written."""
from __future__ import annotations

import atexit
import datetime as dt
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
_SEEN: dict[str, set] = {}        # site -> the keys this process has counted
_LAST: dict[str, float] = {}      # site -> the last read this process recorded
_STATE: dict = {"flushed": time.time(), "hooked": False, "gauge": None, "gauge_at": 0.0, "gauge_base": 0, "fresh": False, "beat": False, "wrote": None, "timer": None}
_WRITE = threading.Lock()         # one flush at a time in this process: the flush at exit waits for one the timer started
MAX_DEPTH = 16                    # the deepest nesting a counter file has is 4; a file nested deeper is damaged
MAX_BYTES = 4 * 1024 * 1024       # and one larger than this is not a counter file


def note(kind: str, key: str, up: int = 2) -> None:
    """Count one read that answered a keeper question from an old form: `kind` names the form, `key` the registry row (a page key) or the session it read, and the site is `kind` and the function `up` frames above
    this call (2: the caller of the helper that notes, 1: the function that notes itself). A key already counted in this process only moves the site's last-read time, and that at most once a minute. Never raises
    and never waits on a file in the cases that matter: the due write is skipped when another process holds the file's lock."""
    try:
        f = sys._getframe(up)
        site = f"{kind} <- {str(f.f_globals.get('__name__') or '?').rsplit('.', 1)[-1]}.{f.f_code.co_name}"
        now = time.time(); key = str(key or "")
        with _LOCK:
            seen = _SEEN.setdefault(site, set())
            new = key not in seen
            if new:
                seen.add(key)
            if new or now - _LAST.get(site, 0.0) >= EVERY:
                _LAST[site] = now
                e = _PENDING.setdefault(site, [now, set()])
                e[0] = now
                if new:
                    e[1].add(key)
            due = bool(_PENDING) and now - _STATE["flushed"] >= EVERY
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


def gauge(keys) -> None:
    """The rows whose keeper only an old form names (`keeper_source` legacy), by page key: set by the publisher each time it runs, with the generation the file holds at that moment (a gauge is written only if no other
    has been written since) and the time it was computed (for display). Written with the next flush, at once when the set changed. Never raises."""
    try:
        ks = sorted({str(k) for k in keys})
        base = _disk_gen()
        with _LOCK:
            changed = _STATE["gauge"] != ks
            _STATE["gauge"] = ks; _STATE["gauge_at"] = time.time(); _STATE["gauge_base"] = base; _STATE["fresh"] = True; _STATE["beat"] = True
            due = changed or time.time() - _STATE["flushed"] >= EVERY
            hook = not _STATE["hooked"]
            if hook:
                _STATE["hooked"] = True
        if hook:
            atexit.register(_at_exit)
        if due:
            flush()
        else:
            _arm()
    except Exception:  # noqa: BLE001
        pass


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_of(lg) -> int:
    """The generation of a gauge of the file: 0 for none, or for a gauge a previous version wrote (it had no generation, and its time is never compared)."""
    g = lg.get("gen") if isinstance(lg, dict) else None
    return g if _is_int(g) else 0


def _disk_gen() -> int:
    """The generation of the gauge the file holds now (0 when there is none or the file cannot be read)."""
    try:
        return _gen_of(load()[0].get("legacy"))
    except Exception:  # noqa: BLE001
        return 0


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
            _STATE["timer"] = _after(EVERY - (time.time() - _STATE["flushed"]), _tick)
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


def _doc_of(text: str) -> dict:
    """The counter file's content, or ValueError when it is not one: every level is checked (the sites, each site's last read and keys, the gauge), so a malformed value is a damaged file and not a crash later."""
    if len(text) > MAX_BYTES or not _depth_ok(text):
        raise ValueError("not a counter file (too large or nested too deeply)")
    try:
        d = json.loads(text, parse_constant=_no_constant)
    except RecursionError:
        raise ValueError("nested too deeply") from None
    if not (isinstance(d, dict) and isinstance(d.get("sites", {}), dict)):
        raise ValueError("not a counter file")
    for k in ("since", "flushed", "restarted"):
        if k in d and not isinstance(d[k], str):
            raise ValueError(f"{k} is not a time")
    for name, v in d.get("sites", {}).items():
        if not (isinstance(v, dict) and isinstance(v.get("last", ""), str) and (v.get("keys") is None or _is_str_list(v["keys"]))):
            raise ValueError(f"site {str(name)[:60]} is malformed")
    lg = d.get("legacy")
    if lg is not None and not (isinstance(lg, dict) and _is_int(lg.get("count", 0)) and (lg.get("keys") is None or _is_str_list(lg["keys"])) and isinstance(lg.get("at", ""), str)
                                                  and (lg.get("gen") is None or _is_int(lg["gen"])) and (lg.get("stamp") is None or _is_num(lg["stamp"]))):
        raise ValueError("the gauge is malformed")
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
    deadline = time.monotonic() + wait
    if not (_WRITE.acquire(timeout=wait) if wait > 0 else _WRITE.acquire(blocking=False)):
        if not wait:
            _arm()
        return False
    try:
        return _flush(deadline)
    finally:
        _WRITE.release()


def _flush(deadline: float) -> bool:
    with _LOCK:
        take = {s: [e[0], set(e[1])] for s, e in _PENDING.items()}; _PENDING.clear()
        gauge_now = _STATE["gauge"]; gauge_at = _STATE["gauge_at"]; gauge_base = _STATE["gauge_base"]; fresh = _STATE["fresh"]; _STATE["fresh"] = False; beat = _STATE["beat"]; _STATE["beat"] = False; _STATE["flushed"] = time.time()
    if not take and gauge_now is None and not beat:
        return True
    tmp = None
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
                    if time.monotonic() >= deadline:
                        raise OSError("locked by another process")
                    time.sleep(0.005)
            try:
                d, restarted = {}, ""
                try:
                    d = _doc_of(p.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    pass
                except ValueError:         # damaged: keep it once as .bad, start again, say so in the file
                    os.replace(p, p.with_name(p.name + ".bad"))
                    d, restarted = {}, _iso(time.time())
                sites = d.get("sites") if isinstance(d.get("sites"), dict) else {}
                for site, (last, keys) in take.items():
                    s = sites.get(site) if isinstance(sites.get(site), dict) else {}
                    have = [str(k) for k in (s.get("keys") or []) if isinstance(k, str)]
                    sites[site] = {"last": max(str(s.get("last") or ""), _iso(last)), "keys": sorted(set(have) | keys)[:KEYS_PER_SITE]}
                out = {"schema": SCHEMA, "since": str(d.get("since") or "") or _iso(time.time()), "flushed": _iso(time.time()), "sites": sites}
                if restarted or d.get("restarted"):
                    out["restarted"] = restarted or str(d["restarted"])
                held = d.get("legacy") if isinstance(d.get("legacy"), dict) else None
                wrote_gen = None; dropped: dict = {}
                if gauge_now is not None and ((fresh and _gen_of(held) <= gauge_base) or held is None):      # a gauge computed since the last write, and none written since it was computed (or no gauge in the file at all): it is the newest
                    wrote_gen = _gen_of(held) + 1
                    out["legacy"] = {"count": len(gauge_now), "keys": gauge_now[:GAUGE_KEYS], "at": _iso(gauge_at), "gen": wrote_gen}
                    rows = set(gauge_now)
                    for site, v in sites.items():        # a site's keys are rows of the gauge: the keys of rows that have since got a mark (or agents) go with them
                        kept = [k for k in (v.get("keys") or []) if k in rows]
                        dropped[site] = {k for k in (v.get("keys") or []) if k not in rows} | {k for k in take.get(site, [0, set()])[1] if k not in rows}
                        v["keys"] = kept
                elif held:                          # nothing new to publish, or another process has written a gauge since this one was computed: the file's stays
                    out["legacy"] = held
                tmp = p.with_name("." + p.name + ".tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(out, indent=1, sort_keys=True)); fh.flush(); os.fsync(fh.fileno())
                os.replace(tmp, p)
                tmp = None
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
        with _LOCK:
            if wrote_gen is not None:
                _STATE["gauge_base"] = max(_STATE["gauge_base"], wrote_gen)
            for site, ks in dropped.items():          # a pruned key leaves the process's memory of what it counted too: it is counted again when it is read again under a gauge that lists the row
                if site in _SEEN:
                    _SEEN[site] -= ks
        return True
    except Exception:  # noqa: BLE001 — put the counts back: the next flush adds them
        if tmp is not None:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass
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
        except ValueError:
            return "?"
    def age(s: str):
        try:
            return now - dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
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
    if not problem:
        lg = d.get("legacy")
        if isinstance(lg, dict):
            n = lg.get("count") if _is_int(lg.get("count")) else 0
            keys = [str(k) for k in (lg.get("keys") or [])]
            out.append(f"legacy keepers: {n} registry row(s) whose keeper only an old form names (as of {when(str(lg.get('at') or ''))})" + (": " + ", ".join(keys) + (", ..." if n > len(keys) else "") if keys else ""))
        else:
            out.append("legacy keepers: not yet known (the publisher has not written the gauge)")
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
    ap = argparse.ArgumentParser(prog="stackshot keeper-reads", description="the keepers only an old form names, and the readers that can still answer a keeper question from one (read only)")
    ap.add_argument("--json", action="store_true", help="the state file's own content")
    a = ap.parse_args(argv)
    d, problem = load()
    print(json.dumps(d, indent=1, sort_keys=True) if a.json else "\n".join(report(d, problem)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
