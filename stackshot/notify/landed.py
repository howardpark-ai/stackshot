"""landed.py — the Landed list's rules: the closes of agents that the owner did not make, and which of them he has cleared (until cleared).

An item an agent finishes and closes never reached him unless his words were on it (that is the For you list, foryou.py, hidden). This is the other half: every close
whose outcome is done or dropped and that he did not make himself is one record here; the board's header counts the uncleared ones ("Landed N", muted at 0) and links to the Landed page
(render.Board.landed_html, GET /landed), which lists them. Like a phone's notifications, an entry stays until he clears it (a Clear button per line, Clear all at the top); opening the page clears nothing.

Why a store of its own and not the For you rows: a For you row is made only for a WATCHED item (his words on it, or his flag), has no outcome or closer as fields (only one line of text), and leaves the
list when seen; this set is every close of an agent, with its outcome and closer, and keeps each until he clears it. The For you list is unchanged and stays hidden (render._SHOW_FOR_YOU).

What is stored, in one small JSON file in the state dir (<state>/landed.json), written atomically by service/landed.py (which owns the file, its lock and the clock):

  closes  {gid: {ts, outcome, by, project, cleared}}   ONE record per item: its latest close.
            ts       the close's own clock (the item's state_updated, whole seconds): the close's identity, "<gid>:<ts>" is what a "clear" names
            outcome  done | dropped (a superseded, unrecorded or any other close is not landed)
            by       who closed it, as the writer was stored (a session id or name; the page resolves it to the name in use); "" = the server's own close (a done check)
            project  the item's project page key when it closed
            cleared  when he cleared it (epoch), 0 = still on the list. A cleared record stays in the file until it is KEEP_DAYS old, so the same close recorded twice cannot bring it back.
            (the former `seen` field is read and ignored: opening the page once marked an entry seen, which he never meant as clearing, so it is on the list again; the next write drops the field)

A Clear can be undone while the Landed page is open: `unclear` restores a cleared record by its key when it is still the same close and inside the KEEP_DAYS window; the page keeps the cleared line, dimmed, with an Undo until it is reloaded.
A reopened item loses its record (it has not landed any more); when it closes again that is a new record, uncleared, whatever happened to the first. A record is kept KEEP_DAYS (60) after its close: every uncleared close of those 60 days is listed and counted, the count and the page reading the same records (render.Board.landed_rows).

This module is the rules only, on plain dicts: it reads no file and no clock (the callers pass `now`), so the store, the lock and the file that does not parse are service/landed.py's. Stdlib only."""
from __future__ import annotations

import json
from typing import Any

OUTCOMES = ("done", "dropped")
KEEP_DAYS = 60              # a record is dropped this long after its close; an uncleared close is listed and counted for all of it (it stays until he clears it)


def parse(text: str) -> dict[str, dict[str, Any]]:
    """The records in the text of a landed file. ValueError when the text is not a landed list (it does not parse, or is not an object with a `closes` object); a record that is not
    a record, or has a ts that is no number, is skipped."""
    d = json.loads(text)
    if not isinstance(d, dict) or not isinstance(d.get("closes", {}), dict):
        raise ValueError("not a landed list")
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


def dump(closes: dict[str, dict[str, Any]]) -> str:
    """The text of a landed file."""
    return json.dumps({"closes": closes}, ensure_ascii=False, indent=1) + "\n"


def key(gid: str, ts: int | float) -> str:
    """A close's identity: the item and the clock of its close. A "clear" names closes by it, so a close that lands between a page's reading and the click is never cleared unread."""
    return f"{gid}:{int(ts)}"


def with_record(d: dict[str, dict[str, Any]], gid: str, ts: int, outcome: str, by: str, project: str, now: float) -> dict[str, dict[str, Any]] | None:
    """The records with an agent's close of an item (uncleared; the item's earlier record, if any, is replaced) and the records older than KEEP_DAYS dropped → the new records;
    None when the same close is on the list already (the same close recorded twice). `d` is not changed."""
    if gid in d and d[gid]["ts"] == ts:
        return None
    out = dict(d)
    out[gid] = {"ts": ts, "outcome": outcome, "by": str(by or ""), "project": str(project or ""), "cleared": 0.0}
    cut = now - KEEP_DAYS * 86400.0
    return {g: r for g, r in out.items() if r["ts"] >= cut}


def without(d: dict[str, dict[str, Any]], gid: str) -> dict[str, dict[str, Any]] | None:
    """The records without an item (it is open again, or was closed by him: it has not landed any more) → None when it has none. `d` is not changed."""
    if gid not in d:
        return None
    out = dict(d)
    del out[gid]
    return out


def listed(d: dict[str, dict[str, Any]], now: float, keep_days: float = KEEP_DAYS) -> list[dict[str, Any]]:
    """The closes on the list, newest first: [{gid, ts, outcome, by, project, cleared}]. Every close he has not cleared, of the last `keep_days` (60)."""
    keep_cut = now - keep_days * 86400.0
    out = [{"gid": g, **r} for g, r in d.items() if r["ts"] >= keep_cut and not r["cleared"]]
    return sorted(out, key=lambda r: (-r["ts"], r["gid"]))


def clear(d: dict[str, dict[str, Any]], keys: list[str] | None, now: float) -> int:
    """Clear closes in `d`: those named by `keys` (key(gid, ts)), or every uncleared one when `keys` is None. A key whose close has been replaced since (the item closed again) clears nothing.
    → how many were cleared (`d` is changed in place)."""
    want = None if keys is None else set(keys)
    n = 0
    for g, r in d.items():
        if r["cleared"] == 0 and (want is None or key(g, r["ts"]) in want):
            r["cleared"] = now
            n += 1
    return n


def unclear(d: dict[str, dict[str, Any]], keys: list[str], now: float) -> int:
    """Undo a Clear (the Landed page's temporary Undo): the closes of `d` named by `keys` (key(gid, ts)) that are cleared, that still hold the very close the key names (an item that closed again since has a new record,
    so the old key restores nothing) and that are still inside the KEEP_DAYS window go back to uncleared. An unknown key, an uncleared record and a record past the window do nothing.
    → how many were restored (`d` is changed in place)."""
    want = set(keys)
    cut = now - KEEP_DAYS * 86400.0
    n = 0
    for g, r in d.items():
        if r["cleared"] and r["ts"] >= cut and key(g, r["ts"]) in want:
            r["cleared"] = 0.0
            n += 1
    return n
