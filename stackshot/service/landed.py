"""landed.py: the Landed list's file: one small JSON file in the state dir (<state>/landed.json), read and written atomically under a lock of its own.

The rules of the list (what a record holds, how long it is kept, what clearing and undoing do, the file's text) are notify/landed.py's, on plain dicts, and read no clock; this module is what reads and
writes the file and the clock: `record`, `forget`, `records`, `clear` and `unclear`, which the saves (service/foryou_events.py), the board's render and the Landed page's buttons call.

A file that does not parse is moved aside to landed.json.bad-<epoch> and the list starts empty. A file that cannot be read (permissions, I/O error) is never written over: record, forget and clear raise,
and the readers see an empty list. Stdlib only; the server writes, the renderer reads."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.notify import landed as _ld

_LOCK = threading.RLock()


def path() -> Path:
    return _cfg.state("landed.json")


def _load(strict: bool = False) -> dict[str, dict[str, Any]]:
    """The records. A missing file is an empty list. A file that cannot be read (EACCES, EIO, EMFILE...) is an error the writers must not write over: with `strict` it is raised (record, forget and
    clear load so, and leave the file as it is); without it (the readers: the board's render) the list reads empty and the error is a stderr line."""
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        if strict:
            raise
        print(f"landed: {p} cannot be read ({e.__class__.__name__}: {e}); the list reads empty", file=sys.stderr, flush=True)
        return {}
    except UnicodeDecodeError:
        text = "\x00"                      # not text: handled as a file that does not parse
    try:
        return _ld.parse(text)
    except ValueError:
        bad = p.with_name(f"{p.name}.bad-{int(time.time())}")
        try:
            os.replace(p, bad)
            kept = f"moved to {bad.name}"      # i18n: skip  (a stderr log line)
        except OSError as e:
            kept = f"could not be moved aside ({e.__class__.__name__})"      # i18n: skip  (a stderr log line)
        print(f"landed: {p} does not parse; {kept}; starting an empty list", file=sys.stderr, flush=True)
        return {}


def _save(closes: dict[str, dict[str, Any]]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(_ld.dump(closes), encoding="utf-8")
    os.replace(tmp, p)


def record(gid: str, ts: float, outcome: str, by: str = "", project: str = "") -> bool:
    """An agent closed an item: its record, uncleared (the item's earlier record, if any, is replaced). Nothing for an outcome that does not land. → True when a record was made or replaced."""
    if outcome not in _ld.OUTCOMES:
        forget(gid)
        return False
    ts = int(float(ts or 0)) or int(time.time())
    with _LOCK:
        d = _ld.with_record(_load(strict=True), gid, ts, outcome, by, project, time.time())
        if d is None:
            return False                              # the same close recorded twice
        _save(d)
        return True


def forget(gid: str) -> bool:
    """The item is open again, or was closed by him: it has not landed (any more). → True when a record went."""
    with _LOCK:
        d = _ld.without(_load(strict=True), gid)
        if d is None:
            return False
        _save(d)
        return True


def records(now: float | None = None, keep_days: float = _ld.KEEP_DAYS) -> list[dict[str, Any]]:
    """The closes on the list, newest first: [{gid, ts, outcome, by, project, cleared}]. Every close he has not cleared, of the last `keep_days` (60)."""
    now = time.time() if now is None else now
    with _LOCK:
        d = _load()
    return _ld.listed(d, now, keep_days)


def clear(keys: list[str] | None = None, now: float | None = None) -> int:
    """Clear closes: those named by `keys` (notify/landed.key(gid, ts)), or every uncleared one when `keys` is None. A key whose close has been replaced since (the item closed again) clears nothing. → how many were cleared."""
    now = time.time() if now is None else now
    with _LOCK:
        d = _load(strict=True)
        n = _ld.clear(d, keys, now)
        if n:
            _save(d)
        return n


def unclear(keys: list[str], now: float | None = None) -> int:
    """Undo a Clear (the Landed page's temporary Undo): see notify/landed.unclear. → how many were restored."""
    now = time.time() if now is None else now
    with _LOCK:
        d = _load(strict=True)
        n = _ld.unclear(d, keys, now)
        if n:
            _save(d)
        return n
