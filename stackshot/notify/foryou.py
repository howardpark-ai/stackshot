"""foryou.py — the "For you" list's rules: what the owner should see, as rows instead of messages to a front agent.

A notice for the owner (a close with his words on it, a decision asked of him, a due date within a day) used
to reach him as a `[for <owner>]` message to a front agent, which cost that agent a turn and him a place in a chat. It is now a
row in this list: the board's "For you" section shows it newest first, and `client.py get for-you` returns it as JSON for
the fleet tool's items sheet. A message a session sends on purpose with the mark (asking for a decision or a go-ahead) is not touched.

What is stored, in one small JSON file in the state dir (<state>/for-you.json), written atomically by service/foryou.py (which owns the file, its lock and the clock):

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
          for an item that is not watched by default. No flag = the default (notify/foryou_rows.watched).
  keys    {key: epoch} every key ever made, kept 30 days, so a row he marked seen is not made again by the due-date pass
  seq     the last id given

This module is the rules only, on the plain dict the file holds (`{rows, flags, keys, seq}`): it reads no file and no clock (the callers pass `now`), and a function that changes the list changes the
dict it is given in place, for the caller to save. Stdlib only. Nothing here knows what an item is: the rules (which events, which items are watched) are notify/foryou_rows.py's.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

KINDS = ("closed", "reopened", "decision", "check_failed", "due")      # i18n: skip  (the kind ids)
MODES = ("watch", "mute")
MAX_ROWS = 200                 # the list keeps this many rows; the oldest go first
KEYS_DAYS = 30                 # a key is remembered this long after its row was made
SLACK_TRIES = 3                # an urgent row's Slack post is tried this many times in all, then left on the list only
SLACK_AGE = 24 * 3600.0        # …and only while the row is younger than this


def empty() -> dict[str, Any]:
    return {"rows": [], "flags": {}, "keys": {}, "seq": 0}


def salvage_seq(text: str) -> int:
    """The highest row id (or `seq`) that can still be read in a file that no longer parses; 0 when none can."""
    best = 0
    for m in re.finditer(r'"(?:id|seq)"\s*:\s*(\d{1,12})\b', text):
        best = max(best, int(m.group(1)))
    return best


def parse(d: dict[str, Any]) -> dict[str, Any]:
    """The list a decoded file holds: rows of a kind still in KINDS, the flags and keys that are well formed, and `seq` (which still counts the id of a row that was dropped)."""
    out = empty()
    raw = [r for r in d.get("rows") or [] if isinstance(r, dict) and r.get("id") is not None]
    out["rows"] = [r for r in raw if r.get("kind") in KINDS]       # a retired kind (release_failed) goes; `seq` below still counts its id
    out["flags"] = {str(k): str(v) for k, v in (d.get("flags") or {}).items() if str(v) in MODES} if isinstance(d.get("flags"), dict) else {}
    out["keys"] = {str(k): float(v) for k, v in (d.get("keys") or {}).items() if isinstance(v, (int, float))} if isinstance(d.get("keys"), dict) else {}
    try:
        out["seq"] = max(int(d.get("seq") or 0), max([int(r["id"]) for r in raw] or [0]))
    except (TypeError, ValueError):
        out["seq"] = 0
    return out


def dump(d: dict[str, Any]) -> str:
    """The text of the file."""
    return json.dumps(d, ensure_ascii=False, indent=1) + "\n"


# ----------------------------------------------------------------------------- rows
def newest_first(d: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows, newest first."""
    return sorted(d["rows"], key=lambda r: (-float(r.get("ts") or 0), -int(r["id"])))


def add(d: dict[str, Any], *, key: str, kind: str, gid: str = "", item: str = "", project: str = "", what: str, url: str = "", urgent: bool = False,
        ts: float, now: float) -> dict[str, Any] | None:
    """Make a row for an event, at the time `ts`, in `d` → the row, or None when this key already made one (a row marked seen included: it stays seen). `now` is the clock the keys' 30 days are counted from.
    ValueError for a kind that is not one of KINDS."""
    if kind not in KINDS:
        raise ValueError(f"for-you: no such kind {kind!r}")
    if key in d["keys"]:
        return None
    d["seq"] += 1
    row = {"id": d["seq"], "key": key, "ts": ts, "kind": kind, "gid": gid, "item": item, "project": project, "what": str(what),
           "url": url, "urgent": bool(urgent), "slacked": 0, "slack_tries": 0}
    d["rows"].append(row)
    d["rows"] = sorted(d["rows"], key=lambda r: (float(r.get("ts") or 0), int(r["id"])))[-MAX_ROWS:]
    d["keys"][key] = ts
    cut = now - KEYS_DAYS * 86400.0
    d["keys"] = {k: v for k, v in d["keys"].items() if v >= cut}
    return row


def row_wanted(row_id: int | str) -> int | None:
    """What a "seen" names: None for "all", else the row's number. ValueError when `row_id` is neither a whole number nor "all"."""
    return None if str(row_id) == "all" else int(row_id)


def mark_seen(d: dict[str, Any], want: int | None) -> list[int] | None:
    """The owner has seen a row (`want`, from row_wanted), or all of them (None): it leaves the list in `d` (its key stays, so it is not made again). → the ids that left, ascending
    (empty for "all" on an empty list); None when the id names no row on the list (never made, or already seen)."""
    gone = sorted(int(r["id"]) for r in d["rows"] if want is None or int(r["id"]) == want)
    if not gone and want is not None:
        return None
    if gone:
        d["rows"] = [r for r in d["rows"] if int(r["id"]) not in gone]
    return gone


def resolve(d: dict[str, Any], gid: str, kind: str) -> int:
    """Take the rows of one kind for an item off the list because what they said no longer holds (a decision that was answered or
    whose item closed). → how many went."""
    keep = [r for r in d["rows"] if not (r.get("gid") == gid and r.get("kind") == kind)]
    n = len(d["rows"]) - len(keep)
    if n:
        d["rows"] = keep
    return n


def row_by_id(d: dict[str, Any], row_id: int) -> dict[str, Any] | None:
    for r in d["rows"]:
        if int(r["id"]) == int(row_id):
            return dict(r)
    return None


def slack_result(d: dict[str, Any], row_id: int, ok: bool, ts: float) -> int:
    """One Slack attempt for a row is over: count it (`slack_tries`), and on success stamp `slacked` with `ts` → the tries so far (0 = no such row)."""
    for r in d["rows"]:
        if int(r["id"]) == int(row_id):
            r["slack_tries"] = int(r.get("slack_tries") or 0) + 1
            if ok:
                r["slacked"] = ts
            return r["slack_tries"]
    return 0


def slack_pending(d: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """The urgent rows whose Slack post has not gone through: younger than SLACK_AGE and tried fewer than SLACK_TRIES times."""
    return [dict(r) for r in d["rows"]
            if r.get("urgent") and not r.get("slacked") and int(r.get("slack_tries") or 0) < SLACK_TRIES and now - float(r.get("ts") or 0) < SLACK_AGE]


def mark_slacked(d: dict[str, Any], row_id: int, ts: float) -> None:
    for r in d["rows"]:
        if int(r["id"]) == int(row_id):
            r["slacked"] = ts


# ----------------------------------------------------------------------------- the per-item flag
def flag_mode(mode: Any) -> str:
    """A flag's word as it is stored: "watch", "mute", or "" for the default ("default" or ""). ValueError for any other word."""
    mode = str(mode or "").strip().lower()
    if mode in ("default", ""):
        return ""
    if mode not in MODES:
        raise ValueError(f"for-you: a flag is one of {' | '.join(MODES)} | default")
    return mode


def set_flag(d: dict[str, Any], gid: str, mode: str) -> None:
    """Set an item's flag in `d` to `mode` (from flag_mode); "" clears it."""
    if mode:
        d["flags"][gid] = mode
    else:
        d["flags"].pop(gid, None)


# ----------------------------------------------------------------------------- the client API's reading
def payload(rows: list[dict[str, Any]], flags: dict[str, str], tz: Any, now: float, shown_of: Any = None) -> dict[str, Any]:
    """What `client.py get for-you` returns: {"generated", "rows": [newest first, each with `when` (ISO, the instance zone `tz`)],
    "flags": {item as shown: "watch" | "mute"}}. `rows` and `flags` are as the list holds them; `shown_of` turns a store id into the id a session reads."""
    stamp = lambda t: dt.datetime.fromtimestamp(float(t), tz).isoformat(timespec="seconds")
    out = []
    for r in rows:
        out.append({**{k: r.get(k) for k in ("id", "kind", "item", "project", "what", "url", "urgent", "ts")},
                    "when": stamp(r.get("ts") or 0), "slacked": bool(r.get("slacked"))})
    fl = {(shown_of(g) if shown_of else g): m for g, m in flags.items()}
    return {"generated": stamp(now), "rows": out, "flags": fl}
