"""requestlog.py: the server's request log, one JSON line per HTTP request, kept as rotated files, and the reader the summary command uses.

The files are `<state>/requests/requests-YYYY-MM-DD.jsonl`, one per UTC day. A line is a request, or a server event:

    {"ts":"2026-11-22T09:36:53.123Z","method":"POST","route":"tool:update","status":200,"ms":41.7,"bytes":812,"caller":"my-session"}
    {"ts":"...","method":"GET","route":"/client/items","status":500,"ms":3.2,"bytes":21,"caller":"anon","err":"KeyError at stackshot.web.routes.x:handler:42"}
    {"ts":"...","kind":"start","pid":123,"head":"abc1234","mode":"inline"}              the server came up
    {"ts":"...","kind":"stop","pid":123}                                                the server went down cleanly

`ts` is when the request finished (UTC, milliseconds); `ms` is its whole time, from the first byte in to the last byte out. Nothing of a request's content is kept: no query string, header, cookie, token, body or address
(web/requestlog.py decides what reaches this file; this module writes what it is given).

Retention: at the first write of a day (and at the start) every finished day's file is gzipped to `.jsonl.gz` and a file more than KEEP_DAYS days old is deleted, in a thread of its own, so a request never waits for it.
A write that fails never fails the request: one line on stderr, at most once in ten minutes.

Stdlib only; the clock and the directory are arguments, so a test runs it with a fake clock."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

KEEP_DAYS = 90                 # a day's file older than this many days is deleted
WARN_EVERY = 600.0             # seconds between two stderr lines about a write that failed
NAME_RX = re.compile(r"^requests-(\d{4}-\d{2}-\d{2})\.jsonl(\.gz)?$")


def iso(t: float) -> str:
    """Epoch seconds → UTC ISO text with milliseconds and a Z, the form of `ts`."""
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _day(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")


def _day_date(name: str) -> dt.date | None:
    m = NAME_RX.match(name)
    try:
        return dt.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def maintain(directory: Path, today: dt.date, keep_days: int = KEEP_DAYS) -> None:
    """Gzip every finished day's plain file (a day before `today`) and delete the files more than `keep_days` days old. Safe to run twice and
    after a stop in the middle: the gzip is written beside its name and moved into place, and a plain file whose `.gz` exists is just removed."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    for name in names:
        d = _day_date(name)
        if d is None:
            continue
        p = Path(directory) / name
        try:
            if (today - d).days > keep_days:
                p.unlink()
            elif d < today and not name.endswith(".gz"):
                gz = p.with_name(name + ".gz")
                if not gz.exists():
                    tmp = p.with_name(name + ".gz.tmp")
                    with open(p, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as out:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                    os.replace(tmp, gz)
                p.unlink()
        except OSError as e:
            print(f"request log: {name} not kept up: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


class RequestLog:
    """The writer: `write(record)` appends one line to today's file under one lock and never raises."""

    def __init__(self, directory: Path | str, *, clock: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 keep_days: int = KEEP_DAYS, threaded: bool = True) -> None:
        self.dir = Path(directory)
        self.clock, self.mono, self.keep_days, self.threaded = clock, mono, keep_days, threaded
        self._lock = threading.Lock()
        self._day = ""
        self._fh: Any = None
        self._warned = -WARN_EVERY * 2
        self.maintenance: threading.Thread | None = None      # the last maintenance thread (a test joins it)

    def _open(self, day: str) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = self.dir / f"requests-{day}.jsonl"
        fh = open(p, "a", buffering=1, encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600))
        if os.path.getsize(p) > 0:                                       # a last line a crash left half written: the next line starts on its own
            with open(p, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != b"\n":
                    fh.write("\n")
        self._fh, self._day = fh, day
        today = dt.date.fromisoformat(day)
        if self.threaded:
            self.maintenance = threading.Thread(target=maintain, args=(self.dir, today, self.keep_days), name="requestlog-maintain", daemon=True)
            self.maintenance.start()
        else:
            maintain(self.dir, today, self.keep_days)

    def write(self, record: dict[str, Any]) -> None:
        """Append `record` with its `ts` (this clock's now) first. A failure is one stderr line per ten minutes, never an exception."""
        try:
            with self._lock:
                now = self.clock()                    # read under the lock: a writer that waited for it must not use a day that has ended since (its line would reopen a file already gzipped)
                line = json.dumps({"ts": iso(now), **record}, separators=(",", ":"), ensure_ascii=True) + "\n"
                day = _day(now)
                if self._fh is None or day != self._day:
                    self._open(day)
                self._fh.write(line)
        except Exception as e:  # noqa: BLE001  — a log line is never worth a failed request
            try:
                with self._lock:
                    if self._fh is not None:
                        try:
                            self._fh.close()
                        except OSError:
                            pass
                        self._fh = None                         # the next write opens the file again
                    t = self.mono()
                    if t - self._warned >= WARN_EVERY:
                        self._warned = t
                        print(f"request log: not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
                self._day = ""


# ---------------------------------------------------------------------------- reading

def _files(directory: Path, first: dt.date, last: dt.date) -> list[Path]:
    """The day files from `first` to `last` (UTC days, both included), oldest first; a day with a plain and a gzipped file reads the gzipped one only if the plain is gone."""
    found: dict[dt.date, list[Path]] = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    for name in names:
        d = _day_date(name)
        if d is not None and first <= d <= last:
            found.setdefault(d, []).append(Path(directory) / name)
    out: list[Path] = []
    for d in sorted(found):
        out.extend(sorted(found[d], key=lambda p: p.name.endswith(".gz")))       # the plain file first (it holds what was written after a gzip that was stopped)
    return out


def read(directory: Path | str, since: float, until: float) -> Iterator[dict[str, Any]]:
    """Every record whose `ts` is in [since, until) (epoch seconds), oldest day first. A missing day, a half-written last line, a line that is not a JSON object and a
    gzip file cut short are skipped, never an error; what could be read of them is yielded."""
    first = dt.datetime.fromtimestamp(since, dt.timezone.utc).date()
    last = dt.datetime.fromtimestamp(max(until - 0.001, since), dt.timezone.utc).date()
    for p in _files(Path(directory), first, last):
        opener = gzip.open if p.name.endswith(".gz") else open
        try:
            with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    t = parse_ts(rec.get("ts"))
                    if t is not None and since <= t < until:
                        rec["_t"] = t
                        yield rec
        except (OSError, EOFError):
            continue


def parse_ts(s: Any) -> float | None:
    """`ts` text → epoch seconds, None when it is not one."""
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
