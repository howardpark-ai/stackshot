"""foryou.py: the For you list's file: one small JSON file in the state dir (<state>/for-you.json), read and written atomically under a lock of its own.

The rules of the list (the kinds of row, what a row holds, how many are kept, the keys, the flags, what the client API returns) are notify/foryou.py's, on the plain dict the file holds, and read no clock;
this module is what reads and writes the file and the clock: `rows`, `add`, `has_key`, `mark_seen`, `seen`, `resolve`, `row_by_id`, `slack_result`, `slack_pending`, `mark_slacked`, `flag`, `flags`,
`set_flag` and `payload`, which the saves (service/foryou_events.py), the Slack hook (service/foryou_slack.py), the routes and the board's render call.

A file that does not parse is moved aside to for-you.json.bad-<epoch> and the list starts empty (ids go on growing). Stdlib only; the server and the renderer share these functions."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.notify import foryou as _fy

_LOCK = threading.RLock()


def path() -> Path:
    return _cfg.state("for-you.json")      # i18n: skip  (a file name)


def _move_aside(p: Path, text: str, why: str) -> dict[str, Any]:
    """The file is there but is not a list this module wrote: keep it as for-you.json.bad-<epoch> for a look, say so on stderr and start
    empty. The sequence number keeps growing (the highest id still readable in the bad file, else the clock), so a row id (which the
    "seen" control and the fleet tool name a row by) is never given twice. The fresh file is written at once, or a second read would start from 0."""
    now = time.time()
    bad = p.with_name(f"{p.name}.bad-{int(now)}")
    n = 1
    while bad.exists():                          # a second bad file within the same second keeps its own name
        n += 1
        bad = p.with_name(f"{p.name}.bad-{int(now)}-{n}")
    try:
        os.replace(p, bad)
        kept = f"moved to {bad.name}"      # i18n: skip  (a stderr log line)
    except OSError as e:
        kept = f"could not be moved aside ({e.__class__.__name__}: {e})"      # i18n: skip  (a stderr log line)
    out = _fy.empty()
    out["seq"] = _fy.salvage_seq(text) or int(now)
    print(f"for-you: {p} {why}; {kept}; starting an empty list (ids go on from {out['seq']})", file=sys.stderr, flush=True)
    try:
        _save(out)
    except OSError:
        pass
    return out


def _load() -> dict[str, Any]:
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _fy.empty()
    except UnicodeDecodeError:
        return _move_aside(p, p.read_bytes().decode("utf-8", "replace"), "is not UTF-8 text")      # i18n: skip  (a stderr log reason)
    except OSError:
        return _fy.empty()
    try:
        d = json.loads(text)
    except ValueError:
        return _move_aside(p, text, "does not parse")      # i18n: skip  (a stderr log reason)
    if not isinstance(d, dict):
        return _move_aside(p, text, "is not a JSON object")      # i18n: skip  (a stderr log reason)
    return _fy.parse(d)


def _save(d: dict[str, Any]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(_fy.dump(d), encoding="utf-8")
    os.replace(tmp, p)


# ----------------------------------------------------------------------------- rows
def rows() -> list[dict[str, Any]]:
    """The rows, newest first."""
    with _LOCK:
        return _fy.newest_first(_load())


def add(*, key: str, kind: str, gid: str = "", item: str = "", project: str = "", what: str, url: str = "", urgent: bool = False,
        ts: float | None = None) -> dict[str, Any] | None:
    """Make a row for an event → the row, or None when this key already made one (a row marked seen included: it stays seen)."""
    if kind not in _fy.KINDS:
        raise ValueError(f"for-you: no such kind {kind!r}")
    when = time.time() if ts is None else float(ts)
    with _LOCK:
        d = _load()
        row = _fy.add(d, key=key, kind=kind, gid=gid, item=item, project=project, what=what, url=url, urgent=urgent, ts=when, now=time.time())
        if row is not None:
            _save(d)
        return row


def has_key(key: str) -> bool:
    with _LOCK:
        return key in _load()["keys"]


def mark_seen(row_id: int | str) -> list[int] | None:
    """The owner has seen a row, or "all": it leaves the list (its key stays, so it is not made again). -> the ids that left, ascending
    (empty for "all" on an empty list); None when the id names no row on the list (never made, or already seen). ValueError when `row_id` is
    neither a whole number nor "all"."""
    want = _fy.row_wanted(row_id)             # ValueError on anything but a whole number
    with _LOCK:
        d = _load()
        gone = _fy.mark_seen(d, want)
        if gone:
            _save(d)
        return gone


def seen(row_id: int | str) -> bool:
    """The owner has seen a row: it leaves the list (its key stays, so it is not made again). "all" clears every row.
    -> True when something was cleared."""
    try:
        return bool(mark_seen(row_id))
    except (TypeError, ValueError):
        return False


def resolve(gid: str, kind: str) -> int:
    """Take the rows of one kind for an item off the list because what they said no longer holds (a decision that was answered or
    whose item closed). → how many went."""
    with _LOCK:
        d = _load()
        n = _fy.resolve(d, gid, kind)
        if n:
            _save(d)
        return n


def row_by_id(row_id: int) -> dict[str, Any] | None:
    with _LOCK:
        return _fy.row_by_id(_load(), row_id)


def slack_result(row_id: int, ok: bool, ts: float | None = None) -> int:
    """One Slack attempt for a row is over: count it (`slack_tries`), and on success stamp `slacked` → the tries so far (0 = no such row)."""
    with _LOCK:
        d = _load()
        tries = _fy.slack_result(d, row_id, ok, time.time() if ts is None else float(ts))
        if tries:
            _save(d)
        return tries


def slack_pending(now: float | None = None) -> list[dict[str, Any]]:
    """The urgent rows whose Slack post has not gone through: younger than SLACK_AGE and tried fewer than SLACK_TRIES times."""
    now = time.time() if now is None else now
    with _LOCK:
        return _fy.slack_pending(_load(), now)


def mark_slacked(row_id: int, ts: float | None = None) -> None:
    with _LOCK:
        d = _load()
        _fy.mark_slacked(d, row_id, time.time() if ts is None else float(ts))
        _save(d)


# ----------------------------------------------------------------------------- the per-item flag
def flag(gid: str) -> str:
    """The owner's setting for an item: "watch", "mute" or "" (the default)."""
    with _LOCK:
        return _load()["flags"].get(gid, "")


def flags() -> dict[str, str]:
    with _LOCK:
        return dict(_load()["flags"])


def set_flag(gid: str, mode: str) -> str:
    """Set an item's flag; "default" (or "") clears it → the flag now ("" = default). ValueError for any other word."""
    mode = _fy.flag_mode(mode)
    with _LOCK:
        d = _load()
        _fy.set_flag(d, gid, mode)
        _save(d)
        return mode


# ----------------------------------------------------------------------------- the client API's reading
def payload(shown_of: Any = None, tz: Any = None, now: float | None = None) -> dict[str, Any]:
    """What `client.py get for-you` returns: {"generated", "rows": [newest first, each with `when` (ISO, the instance zone)],
    "flags": {item as shown: "watch" | "mute"}}. `shown_of` turns a store id into the id a session reads."""
    tz = tz or _cfg.tz()
    return _fy.payload(rows(), flags(), tz, time.time() if now is None else now, shown_of)
