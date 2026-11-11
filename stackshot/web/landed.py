"""landed.py — the Landed list: the closes of agents that the owner did not make, and which of them he has cleared (until cleared).

An item an agent finishes and closes never reached him unless his words were on it (that is the For you list, foryou.py, hidden). This is the other half: every close
whose outcome is done or dropped and that he did not make himself is one record here; the board's header counts the uncleared ones ("Landed N", muted at 0) and links to the Landed page
(render.Board.landed_html, GET /landed), which lists them. Like a phone's notifications, an entry stays until he clears it (a Clear button per line, Clear all at the top); opening the page clears nothing.

Why a store of its own and not the For you rows: a For you row is made only for a WATCHED item (his words on it, or his flag), has no outcome or closer as fields (only one line of text), and leaves the
list when seen; this set is every close of an agent, with its outcome and closer, and keeps each until he clears it. The For you list is unchanged and stays hidden (render._SHOW_FOR_YOU).

What is stored, in one small JSON file in the state dir (<state>/landed.json), written atomically:

  closes  {gid: {ts, outcome, by, project, cleared}}   ONE record per item: its latest close.
            ts       the close's own clock (the item's state_updated, whole seconds): the close's identity, "<gid>:<ts>" is what a "clear" names
            outcome  done | dropped (a superseded, unrecorded or any other close is not landed)
            by       who closed it, as the writer was stored (a session id or name; the page resolves it to the name in use); "" = the server's own close (a done check)
            project  the item's project page key when it closed
            cleared  when he cleared it (epoch), 0 = still on the list. A cleared record stays in the file until it is KEEP_DAYS old, so the same close recorded twice cannot bring it back.
            (the former `seen` field is read and ignored: opening the page once marked an entry seen, which he never meant as clearing, so it is on the list again; the next write drops the field)

A Clear can be undone while the Landed page is open: unclear() restores a cleared record by its key when it is still the same close and inside the KEEP_DAYS window; the page keeps the cleared line, dimmed, with an Undo until it is reloaded.
A reopened item loses its record (it has not landed any more); when it closes again that is a new record, uncleared, whatever happened to the first. A record is kept KEEP_DAYS (60) after its close: every uncleared close of those 60 days is listed and counted, the count and the page reading the same records() (render.Board.landed_rows).
A file that does not parse is moved aside to landed.json.bad-<epoch> and the list starts empty. A file that cannot be read (permissions, I/O error) is never written over: record, forget and clear raise, and the readers see an empty list. Stdlib only; the server writes, the renderer reads.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

OUTCOMES = ("done", "dropped")
KEEP_DAYS = 60              # a record is dropped this long after its close; an uncleared close is listed and counted for all of it (it stays until he clears it)
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
        d = json.loads(text)
        if not isinstance(d, dict) or not isinstance(d.get("closes", {}), dict):
            raise ValueError("not a landed list")
    except ValueError:
        bad = p.with_name(f"{p.name}.bad-{int(time.time())}")
        try:
            os.replace(p, bad)
            kept = f"moved to {bad.name}"      # i18n: skip  (a stderr log line)
        except OSError as e:
            kept = f"could not be moved aside ({e.__class__.__name__})"      # i18n: skip  (a stderr log line)
        print(f"landed: {p} does not parse; {kept}; starting an empty list", file=sys.stderr, flush=True)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for gid, r in (d.get("closes") or {}).items():
        if not isinstance(r, dict):
            continue
        try:
            out[str(gid)] = {"ts": int(float(r.get("ts") or 0)), "outcome": str(r.get("outcome") or ""), "by": str(r.get("by") or ""),
                             "project": str(r.get("project") or ""), "cleared": float(r.get("cleared") or 0)}
        except (TypeError, ValueError, OverflowError):      # a hand-edited ts of inf or nan: a bad record like any other
            continue
    return out


def _save(closes: dict[str, dict[str, Any]]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps({"closes": closes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def key(gid: str, ts: int | float) -> str:
    """A close's identity: the item and the clock of its close. A "clear" names closes by it, so a close that lands between a page's reading and the click is never cleared unread."""
    return f"{gid}:{int(ts)}"


def record(gid: str, ts: float, outcome: str, by: str = "", project: str = "") -> bool:
    """An agent closed an item: its record, uncleared (the item's earlier record, if any, is replaced). Nothing for an outcome that does not land. → True when a record was made or replaced."""
    if outcome not in OUTCOMES:
        forget(gid)
        return False
    ts = int(float(ts or 0)) or int(time.time())
    with _LOCK:
        d = _load(strict=True)
        if gid in d and d[gid]["ts"] == ts:
            return False                              # the same close recorded twice
        d[gid] = {"ts": ts, "outcome": outcome, "by": str(by or ""), "project": str(project or ""), "cleared": 0.0}
        cut = time.time() - KEEP_DAYS * 86400.0
        d = {g: r for g, r in d.items() if r["ts"] >= cut}
        _save(d)
        return True


def forget(gid: str) -> bool:
    """The item is open again, or was closed by him: it has not landed (any more). → True when a record went."""
    with _LOCK:
        d = _load(strict=True)
        if gid not in d:
            return False
        del d[gid]
        _save(d)
        return True


def records(now: float | None = None, keep_days: float = KEEP_DAYS) -> list[dict[str, Any]]:
    """The closes on the list, newest first: [{gid, ts, outcome, by, project, cleared}]. Every close he has not cleared, of the last `keep_days` (60)."""
    now = time.time() if now is None else now
    keep_cut = now - keep_days * 86400.0
    with _LOCK:
        out = [{"gid": g, **r} for g, r in _load().items() if r["ts"] >= keep_cut and not r["cleared"]]
    return sorted(out, key=lambda r: (-r["ts"], r["gid"]))


def clear(keys: list[str] | None = None, now: float | None = None) -> int:
    """Clear closes: those named by `keys` (key(gid, ts)), or every uncleared one when `keys` is None. A key whose close has been replaced since (the item closed again) clears nothing. → how many were cleared."""
    now = time.time() if now is None else now
    want = None if keys is None else set(keys)
    with _LOCK:
        d = _load(strict=True)
        n = 0
        for g, r in d.items():
            if r["cleared"] == 0 and (want is None or key(g, r["ts"]) in want):
                r["cleared"] = now
                n += 1
        if n:
            _save(d)
        return n


def unclear(keys: list[str], now: float | None = None) -> int:
    """Undo a Clear (the Landed page's temporary Undo): the closes named by `keys` (key(gid, ts)) that are cleared, that still hold the very close the key names (an item that closed again since has a new record,
    so the old key restores nothing) and that are still inside the KEEP_DAYS window go back to uncleared. An unknown key, an uncleared record and a record past the window do nothing. → how many were restored."""
    now = time.time() if now is None else now
    want = set(keys)
    cut = now - KEEP_DAYS * 86400.0
    with _LOCK:
        d = _load(strict=True)
        n = 0
        for g, r in d.items():
            if r["cleared"] and r["ts"] >= cut and key(g, r["ts"]) in want:
                r["cleared"] = 0.0
                n += 1
        if n:
            _save(d)
        return n
