"""foryou.py — the "For you" list: what the owner should see, as rows instead of messages to a front agent.

A notice for the owner (a close with his words on it, a decision asked of him, a due date within a day) used
to reach him as a `[for <owner>]` message to a front agent, which cost that agent a turn and him a place in a chat. It is now a
row in this list: the board's "For you" section shows it newest first, and `client.py get for-you` returns it as JSON for
the fleet tool's items sheet. A message a session sends on purpose with the mark (asking for a decision or a go-ahead) is not touched.

What is stored, in one small JSON file in the state dir (<state>/for-you.json), written atomically:

  rows    [{id, key, ts, kind, gid, item, project, what, url, urgent, slacked, slack_tries}], oldest first, at most MAX_ROWS
            id       a number that only grows (the "seen" control and the fleet tool name a row by it)
            key      "<gid>:<kind>:<discriminator>": one event makes one row, however often it is seen again
            kind     closed | reopened | decision | check_failed | due
            item     the item as a session reads it
            what     one line: what happened
            url      the item's page (absolute when the board's address is known)
            urgent   true for a due date within 24 h: also posted once to Slack
            slacked  when the Slack post was made (epoch), 0 = not posted
            slack_tries  how many times the post was tried (a failed one is tried again on a later pass, SLACK_TRIES in all)
A file that does not parse is moved aside to for-you.json.bad-<epoch> and the list starts empty (ids go on growing).
A row whose kind is no longer in KINDS (a `release_failed` row of before an earlier change) is dropped when the file is read, so it leaves the list
and the next write removes it from the file.
  flags   {gid: "watch" | "mute"}: the owner's own setting for an item, made on its page. mute = no rows for it; watch = rows
          for an item that is not watched by default. No flag = the default (server._foryou_watched).
  keys    {key: epoch} every key ever made, kept 30 days, so a row he marked seen is not made again by the due-date pass
  seq     the last id given

Stdlib only; the server and the renderer share these helpers. Nothing here knows what an item is: the rules (which events, which
items are watched) are the server's.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

KINDS = ("closed", "reopened", "decision", "check_failed", "due")
MODES = ("watch", "mute")
MAX_ROWS = 200                 # the list keeps this many rows; the oldest go first
KEYS_DAYS = 30                 # a key is remembered this long after its row was made
_LOCK = threading.RLock()


def path() -> Path:
    return _cfg.state("for-you.json")


def _empty() -> dict[str, Any]:
    return {"rows": [], "flags": {}, "keys": {}, "seq": 0}


def _salvage_seq(text: str) -> int:
    """The highest row id (or `seq`) that can still be read in a file that no longer parses; 0 when none can."""
    import re
    best = 0
    for m in re.finditer(r'"(?:id|seq)"\s*:\s*(\d{1,12})\b', text):
        best = max(best, int(m.group(1)))
    return best


def _move_aside(p: Path, text: str, why: str) -> dict[str, Any]:
    """The file is there but is not a list this module wrote: keep it as for-you.json.bad-<epoch> for a look, say so on stderr and start
    empty. The sequence number keeps growing (the highest id still readable in the bad file, else the clock), so a row id (which the
    "seen" control and the fleet tool name a row by) is never given twice. The fresh file is written at once, or a second read would start from 0."""
    import sys
    now = time.time()
    bad = p.with_name(f"{p.name}.bad-{int(now)}")
    n = 1
    while bad.exists():                          # a second bad file within the same second keeps its own name
        n += 1
        bad = p.with_name(f"{p.name}.bad-{int(now)}-{n}")
    try:
        os.replace(p, bad)
        kept = f"moved to {bad.name}"
    except OSError as e:
        kept = f"could not be moved aside ({e.__class__.__name__}: {e})"
    out = _empty()
    out["seq"] = _salvage_seq(text) or int(now)
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
        return _empty()
    except UnicodeDecodeError:
        return _move_aside(p, p.read_bytes().decode("utf-8", "replace"), "is not UTF-8 text")
    except OSError:
        return _empty()
    try:
        d = json.loads(text)
    except ValueError:
        return _move_aside(p, text, "does not parse")
    if not isinstance(d, dict):
        return _move_aside(p, text, "is not a JSON object")
    out = _empty()
    raw = [r for r in d.get("rows") or [] if isinstance(r, dict) and r.get("id") is not None]
    out["rows"] = [r for r in raw if r.get("kind") in KINDS]       # a retired kind (release_failed) goes; `seq` below still counts its id
    out["flags"] = {str(k): str(v) for k, v in (d.get("flags") or {}).items() if str(v) in MODES} if isinstance(d.get("flags"), dict) else {}
    out["keys"] = {str(k): float(v) for k, v in (d.get("keys") or {}).items() if isinstance(v, (int, float))} if isinstance(d.get("keys"), dict) else {}
    try:
        out["seq"] = max(int(d.get("seq") or 0), max([int(r["id"]) for r in raw] or [0]))
    except (TypeError, ValueError):
        out["seq"] = 0
    return out


def _save(d: dict[str, Any]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


# ----------------------------------------------------------------------------- rows
def rows() -> list[dict[str, Any]]:
    """The rows, newest first."""
    with _LOCK:
        return sorted(_load()["rows"], key=lambda r: (-float(r.get("ts") or 0), -int(r["id"])))


def add(*, key: str, kind: str, gid: str = "", item: str = "", project: str = "", what: str, url: str = "", urgent: bool = False,
        ts: float | None = None) -> dict[str, Any] | None:
    """Make a row for an event → the row, or None when this key already made one (a row marked seen included: it stays seen)."""
    if kind not in KINDS:
        raise ValueError(f"for-you: no such kind {kind!r}")
    now = time.time() if ts is None else float(ts)
    with _LOCK:
        d = _load()
        if key in d["keys"]:
            return None
        d["seq"] += 1
        row = {"id": d["seq"], "key": key, "ts": now, "kind": kind, "gid": gid, "item": item, "project": project, "what": str(what),
               "url": url, "urgent": bool(urgent), "slacked": 0, "slack_tries": 0}
        d["rows"].append(row)
        d["rows"] = sorted(d["rows"], key=lambda r: (float(r.get("ts") or 0), int(r["id"])))[-MAX_ROWS:]
        d["keys"][key] = now
        cut = time.time() - KEYS_DAYS * 86400.0
        d["keys"] = {k: v for k, v in d["keys"].items() if v >= cut}
        _save(d)
        return row


def has_key(key: str) -> bool:
    with _LOCK:
        return key in _load()["keys"]


def mark_seen(row_id: int | str) -> list[int] | None:
    """The owner has seen a row, or "all": it leaves the list (its key stays, so it is not made again). -> the ids that left, ascending
    (empty for "all" on an empty list); None when the id names no row on the list (never made, or already seen). ValueError when `row_id` is
    neither a whole number nor "all"."""
    all_ = str(row_id) == "all"
    if not all_:
        want = int(row_id)             # ValueError on anything but a whole number
    with _LOCK:
        d = _load()
        gone = sorted(int(r["id"]) for r in d["rows"] if all_ or int(r["id"]) == want)
        if not gone and not all_:
            return None
        if gone:
            d["rows"] = [r for r in d["rows"] if int(r["id"]) not in gone]
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
        keep = [r for r in d["rows"] if not (r.get("gid") == gid and r.get("kind") == kind)]
        n = len(d["rows"]) - len(keep)
        if n:
            d["rows"] = keep
            _save(d)
        return n


SLACK_TRIES = 3                # an urgent row's Slack post is tried this many times in all, then left on the list only
SLACK_AGE = 24 * 3600.0        # …and only while the row is younger than this


def row_by_id(row_id: int) -> dict[str, Any] | None:
    with _LOCK:
        for r in _load()["rows"]:
            if int(r["id"]) == int(row_id):
                return dict(r)
    return None


def slack_result(row_id: int, ok: bool, ts: float | None = None) -> int:
    """One Slack attempt for a row is over: count it (`slack_tries`), and on success stamp `slacked` → the tries so far (0 = no such row)."""
    with _LOCK:
        d = _load()
        for r in d["rows"]:
            if int(r["id"]) == int(row_id):
                r["slack_tries"] = int(r.get("slack_tries") or 0) + 1
                if ok:
                    r["slacked"] = time.time() if ts is None else float(ts)
                _save(d)
                return r["slack_tries"]
    return 0


def slack_pending(now: float | None = None) -> list[dict[str, Any]]:
    """The urgent rows whose Slack post has not gone through: younger than SLACK_AGE and tried fewer than SLACK_TRIES times."""
    now = time.time() if now is None else now
    with _LOCK:
        return [dict(r) for r in _load()["rows"]
                if r.get("urgent") and not r.get("slacked") and int(r.get("slack_tries") or 0) < SLACK_TRIES and now - float(r.get("ts") or 0) < SLACK_AGE]


def mark_slacked(row_id: int, ts: float | None = None) -> None:
    with _LOCK:
        d = _load()
        for r in d["rows"]:
            if int(r["id"]) == int(row_id):
                r["slacked"] = time.time() if ts is None else float(ts)
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
    mode = str(mode or "").strip().lower()
    if mode in ("default", ""):
        mode = ""
    elif mode not in MODES:
        raise ValueError(f"for-you: a flag is one of {' | '.join(MODES)} | default")
    with _LOCK:
        d = _load()
        if mode:
            d["flags"][gid] = mode
        else:
            d["flags"].pop(gid, None)
        _save(d)
        return mode


# ----------------------------------------------------------------------------- the client API's reading
def payload(shown_of: Any = None, tz: Any = None, now: float | None = None) -> dict[str, Any]:
    """What `client.py get for-you` returns: {"generated", "rows": [newest first, each with `when` (ISO, the instance zone)],
    "flags": {item as shown: "watch" | "mute"}}. `shown_of` turns a store id into the id a session reads."""
    tz = tz or _cfg.tz()
    stamp = lambda t: dt.datetime.fromtimestamp(float(t), tz).isoformat(timespec="seconds")
    out = []
    for r in rows():
        out.append({**{k: r.get(k) for k in ("id", "kind", "item", "project", "what", "url", "urgent", "ts")},
                    "when": stamp(r.get("ts") or 0), "slacked": bool(r.get("slacked"))})
    fl = {(shown_of(g) if shown_of else g): m for g, m in flags().items()}
    return {"generated": stamp(time.time() if now is None else now), "rows": out, "flags": fl}
