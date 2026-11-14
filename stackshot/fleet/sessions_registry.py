"""sessions_registry.py — the permanent session id (the design doc).

The fleet tool gives every Claude session one id that never changes (a UUID, the "permanent id"), whatever its name or transcript is, and publishes a
registry of them beside the heartbeat files stackshot already reads (clients.py session_links):

  <session_links>/<letter>/session-registry.json
      {"schema": 1, "machine": "a", "written": <ISO Z>, "sessions": {<permanent id>: {id, name, aliases: [...], project, project_key, role,
       lane, model, effort, pane, cwd, state: "live" | "retired", created, retired_at, transcripts: [{id, machine, at, why}]}}}
  Retired rows stay for good. A fresh start of a session adds a transcript to its row; a rename changes `name` (the old one may stay as an alias).

Until now stackshot keyed sessions by pane name or by Claude transcript id (item owner, needs, keepers, inbox holds), and a fresh start left
an owner pointing at a finished transcript. This module is the one lookup that turns any of those into the permanent id:

  resolve(x)         a permanent id, a name, an alias or a transcript id → ONE permanent id, or None ("cannot tell"). Never a pick between rows:
                     zero rows, or more than one, is None. For a name or alias, a string that rows both live and retired carry belongs to the
                     live row when exactly one row is live; of several live rows the one whose CURRENT name it is, if only one, else None.
  display_name(x)    the current name of the session x resolves to, or None
  delivery(x)        the address the delivery code understands: a permanent id → the session's current name when that name is this live session's alone,
                     else its latest transcript id; anything else as it came
  same(a, b)         True/False when both sides resolve (compared as permanent ids), None when either cannot be told (the caller uses its old rule)
  expand(keys)       the keys plus the permanent id each resolves to (a set; for the keys of a line: it may be addressed by any of its names)
  expand_flag(keys)  the keys of a flag file (a hold or a release list) plus the permanent id of each entry that names its session as it is now: its
                     current name, its permanent id or a transcript id. An old name (an alias, a retired row's) stays just that name, so a hold on it
                     never reaches the session that carries the id under another name

The file is read again only when it changes (inode, mtime, size). A file that stops reading (torn, mid-rewrite) is served from its last good
read for up to STALE seconds (30 minutes, counted from the first failed read), then dropped; a file that is missing, or reads but is another schema, is not stood in for. With no
registry every lookup is None, so nothing downstream changes from what it did before the registry existed. Never raises.
The helpers at the end tell a session's name for a reference (`_session_label`), the name a project page lists it under (`_role_name`), the form an item stores it in (`_store_ref`) and whether two stored references name one session (`_same_sess`), and read the heartbeat index by transcript id or by permanent id (`_sessions_index`, `_Index`).
Stdlib only; config.py, fleet.py and liveness.py (and clients.py for the directory) are its imports, the same as anchors.py."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.fleet import fleet as _fleet
from stackshot.fleet import liveness as _lv

SCHEMA = 1
FILE = "session-registry.json"
TTL = 1.0                       # s: how long a look at the directory (its listing and stat) is trusted; a board render asks thousands of times
STALE = 1800.0                  # s: how long the last good read of a file stands in for it when it stops reading (the tool rewriting it, a torn write)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LOCK = threading.Lock()


class _Reg:
    """One read of the registry, indexed: rows by permanent id; permanent ids by transcript id; permanent ids by name and by alias."""
    __slots__ = ("rows", "by_transcript", "by_name", "memo", "stale_until")

    def __init__(self) -> None:
        self.stale_until = float("inf")                # monotonic time after which a file served from its last good read must be dropped
        self.memo: dict[str, str | None] = {}          # resolve(): input → result, for as long as this read stands
        self.rows: dict[str, dict[str, Any]] = {}
        self.by_transcript: dict[str, set[str]] = {}
        self.by_name: dict[str, set[str]] = {}


_CACHE: dict[str, Any] = {"dir": None, "sig": None, "reg": _Reg(), "at": -1e9}
_GOOD: dict[str, list[Any]] = {}      # path → [its rows at the last good read, monotonic time of the FIRST failed read since (None while it reads)]: stands in while the file does not read


def _dir() -> Path | None:
    """The directory the fleet tool's store lives in: [client] session_links, exactly as clients.py reads it (None when set empty, or when the
    configuration cannot be read)."""
    try:
        from stackshot.fleet import clients as _clients
        return _clients._links_dir()
    except Exception:  # noqa: BLE001
        return None


def _files(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*/" + FILE) if len(p.parent.name) == 1)


def _text(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def _read_rows(p: Path) -> dict[str, Any] | None:
    """The `sessions` map of one registry file; {} for a file that reads but is not schema 1 (a deliberate change of format is not a failed read,
    so the last good rows do not stand in for it); None when it does not read (missing, torn, not JSON)."""
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001  — a file that does not read says nothing
        return None
    return d["sessions"] if isinstance(d, dict) and d.get("schema") == SCHEMA and isinstance(d.get("sessions"), dict) else {}


def _build(files: list[Path]) -> _Reg:
    """Index the registry files. A file that stops reading (a torn write, the tool rewriting it) is served from its last good read for up to STALE
    seconds, then dropped. Never raises: a row that does not fit the shape is skipped."""
    reg = _Reg()
    now = time.monotonic()
    for p in files:
        key = str(p)
        rows = _read_rows(p)
        if rows is not None:
            _GOOD[key] = [rows, None]
        else:
            g = _GOOD.get(key)
            if g is not None and g[1] is None:
                g[1] = now                                 # the window runs from the first failed read, not from the last good one
            if g is None or now - g[1] >= STALE:
                _GOOD.pop(key, None)
                continue
            rows = g[0]
            reg.stale_until = min(reg.stale_until, g[1] + STALE)
        for k, row in rows.items():
            try:
                if not isinstance(row, dict):
                    continue
                sid = _text(row.get("id")) or _text(k)
                sid = sid.lower() if _UUID.match(sid.lower()) else sid
                if not sid or sid in reg.rows:
                    continue
                trs = row.get("transcripts") if isinstance(row.get("transcripts"), list) else []
                als = row.get("aliases") if isinstance(row.get("aliases"), list) else []
                row = {**row, "id": sid, "transcripts": trs, "aliases": als}
                reg.rows[sid] = row
                for t in trs:
                    tid = _text(t.get("id") if isinstance(t, dict) else t).lower()
                    if tid:
                        reg.by_transcript.setdefault(tid, set()).add(sid)
                for n in dict.fromkeys(n for n in [_text(row.get("name")), *[_text(a) for a in als]] if n):
                    reg.by_name.setdefault(n, set()).add(sid)
            except Exception:  # noqa: BLE001
                continue
    return reg


def load() -> _Reg:
    """The registry as last read (re-read when a file in the directory changed; the directory is looked at every TTL seconds, not on
    every call). Never raises; an empty _Reg when there is none."""
    try:
        return _load()
    except Exception:  # noqa: BLE001
        return _CACHE["reg"] if isinstance(_CACHE.get("reg"), _Reg) else _Reg()


def _load() -> _Reg:
    now = time.monotonic()
    if 0 <= now - _CACHE["at"] < TTL and now < _CACHE["reg"].stale_until:
        return _CACHE["reg"]
    d = _dir()
    if d is None:
        _CACHE.update(dir=None, sig=None, reg=_Reg(), at=now)
        return _CACHE["reg"]
    files: list[Path] = []
    try:
        files = _files(d)
    except OSError:
        pass
    sig_l = []
    for p in files:
        try:
            st = p.stat()
            sig_l.append((str(p), st.st_ino, st.st_mtime_ns, st.st_size))
        except OSError:
            sig_l.append((str(p), None, None, None))       # listed but not statable: still handed to _build, which falls back to the last good read
    sig = tuple(sig_l)
    with _LOCK:
        _CACHE["at"] = now
        if _CACHE["dir"] == str(d) and _CACHE["sig"] == sig and now < _CACHE["reg"].stale_until:
            return _CACHE["reg"]
        reg = _build(files) if files else _Reg()
        if not files:
            _GOOD.clear()
        _CACHE.update(dir=str(d), sig=sig, reg=reg)
        return reg


def reset() -> None:
    """Forget the last look: the next call reads the directory again (a test that rewrites the file at once)."""
    _CACHE["at"] = -1e9
    _CACHE["sig"] = None


def available() -> bool:
    """Does the registry hold any session (a cheap test before work that only matters when it does)."""
    return bool(load().rows)


def is_perm_id(x: Any) -> bool:
    """Is `x` exactly a permanent id the registry holds (a retired row's included)."""
    s = _text(x).lower()
    return bool(s) and s in load().rows


def resolve(x: Any) -> str | None:
    """Any reference to a session (permanent id, transcript id, name or alias) → its permanent id; None when zero rows or more than one fit."""
    s = _text(x)
    if not s:
        return None
    reg = load()
    if not reg.rows:
        return None
    if s in reg.memo:
        return reg.memo[s]
    if len(reg.memo) > 20000:                  # inputs are items' and callers' strings: a bound, never reached by a board
        reg.memo.clear()
    out = reg.memo[s] = _resolve(reg, s)
    return out


def _resolve(reg: _Reg, s: str) -> str | None:
    low = s.lower()
    if low in reg.rows:
        return low
    if _UUID.match(low):                       # a transcript id: names are never uuid-shaped
        ids = reg.by_transcript.get(low) or ()
        return next(iter(ids)) if len(ids) == 1 else None
    ids = reg.by_name.get(s) or ()
    if len(ids) == 1:
        return next(iter(ids))
    live = [i for i in ids if reg.rows[i].get("state") == "live"]
    if len(live) > 1:                                  # one live row whose CURRENT name it is beats live rows that keep it only as an alias
        live = [i for i in live if _text(reg.rows[i].get("name")) == s]
    return live[0] if len(live) == 1 else None


def explain(x: Any) -> tuple[str | None, str]:
    """resolve(x) with the reason it did not: (permanent id, "") or (None, why). For the migration's summary."""
    s = _text(x)
    sid = resolve(s)
    if sid:
        return sid, ""
    reg = load()
    if not reg.rows:
        return None, "no session registry to resolve it against"
    if not s:
        return None, "empty"
    if s.startswith("cse_"):
        return None, "a cloud or Cowork session (not in the fleet tool's registry)"
    low = s.lower()
    if _UUID.match(low):
        n = len(reg.by_transcript.get(low) or ())
        return None, f"{n} sessions list this transcript id" if n > 1 else "an id no registry session carries"
    ids = reg.by_name.get(s) or ()
    if len(ids) > 1:
        live = sum(1 for i in ids if reg.rows[i].get("state") == "live")
        return None, f"ambiguous: {len(ids)} sessions carry the name ({live} live)"
    return None, "a name no registry session carries"


def row(x: Any) -> dict[str, Any] | None:
    """The registry row of the session x resolves to (a copy), None when it resolves to none."""
    sid = resolve(x)
    return dict(load().rows[sid]) if sid else None


def _row(x: Any) -> dict[str, Any] | None:
    """row() without the copy: the registry's own dict, to be read and not changed."""
    sid = resolve(x)
    return load().rows[sid] if sid else None


def display_name(x: Any) -> str | None:
    """The current name of the session x resolves to; None when it resolves to none (the caller shows what is stored)."""
    r = _row(x)
    return (_text(r.get("name")) or None) if r else None


def transcripts(x: Any) -> list[str]:
    """The transcript ids of the session x resolves to, oldest first (by the row's own `at`; the row's order for a tie)."""
    r = _row(x)
    if not r:
        return []
    ts = [t for t in (r.get("transcripts") or []) if isinstance(t, dict) and _text(t.get("id"))]
    ts.sort(key=lambda t: _text(t.get("at")))
    return [_text(t["id"]).lower() for t in ts]


def names_of(x: Any) -> list[str]:
    """The names the session x resolves to goes by, current name first, then its aliases (the old names the tool kept): [] when it resolves to none."""
    r = _row(x)
    if not r:
        return []
    out = [_text(r.get("name")), *[_text(a) for a in (r.get("aliases") if isinstance(r.get("aliases"), list) else [])]]
    return list(dict.fromkeys(n for n in out if n))


def delivery(x: Any) -> str:
    """The address push and the inbox understand: a pane is addressed by name or transcript id, never by the permanent id that outlives both. A permanent id
    → the session's current name only when that name belongs to this session alone (it resolves back to this id) and the row is live; else
    the row's latest transcript id (a twin name or a retired row's name could land on another session); a row with neither → as it came.
    Anything that is not a permanent id, as it came."""
    s = _text(x)
    low = s.lower()
    if low and _UUID.match(low):
        r = load().rows.get(low)
        if r:
            nm = _text(r.get("name"))
            if nm and r.get("state") == "live" and resolve(nm) == low:
                return nm
            ts = transcripts(low)
            if ts:
                return ts[-1]
    return s


def same(a: Any, b: Any) -> bool | None:
    """True/False when both resolve (compared as permanent ids); None when either cannot be told, so the caller keeps its old comparison."""
    ra, rb = resolve(a), resolve(b)
    if ra is None or rb is None:
        return None
    return ra == rb


def expand(keys: Any) -> set[str]:
    """`keys` (names and ids as a flag file lists them) plus the permanent id each resolves to."""
    out = {str(k).strip() for k in keys if str(k).strip()}
    for k in list(out):
        sid = resolve(k)
        if sid:
            out.add(sid)
    return out


def expand_flag(keys: Any) -> set[str]:
    """`keys` as a hold or release list names them, plus the permanent id of each entry that names its session as it is NOW (its current name, its
    permanent id, a transcript id). An entry that is only an old name of a session (an alias, or the name of a retired row) adds nothing: the
    session that carries that id under another name was never held. A line addressed to the old name itself still matches it literally."""
    out = {str(k).strip() for k in keys if str(k).strip()}
    reg = load()
    for k in list(out):
        sid = resolve(k)
        if sid and (k.lower() == sid or _UUID.match(k.lower()) or _text(reg.rows[sid].get("name")) == k):
            out.add(sid)
    return out


def all_names() -> dict[str, str]:
    """permanent id → current name of every row (retired ones too: an old item still names its owner)."""
    return {i: _text(r.get("name")) for i, r in load().rows.items() if _text(r.get("name"))}


def _session_label(value: str) -> str:
    """The human name for a session reference: the name the fleet tool's registry gives the session now (a stored permanent id, an old transcript id or
    an old name all read as the name in use), else the heartbeat name, else the value itself."""
    v = str(value or "")
    n = display_name(v) if v else None
    if n:
        return n
    x = _sessions_index().get(v) or {}
    return str(x.get("name") or v)


def _role_name(roles: dict[str, Any], who: str, *extra: str) -> str:
    """The name a project page lists `who` under, as `roles` (anchors.session_roles) has it: who as given, its name now, the old names the fleet tool
    kept for it (a page may still list the name before a rename), then any `extra`. "" when no page lists it."""
    who = str(who or "").strip()
    if not who:
        return ""
    sid = resolve(who)

    def mine(n: str) -> bool:        # a name the registry gives this session counts only when it resolves back to it: a retired row never takes a live row's entry by alias
        return not sid or n == who or n in extra or resolve(n) == sid
    return next((n for n in (who, _session_label(who), *names_of(who), *extra) if n and n in roles and mine(n)), "")


def _store_ref(value: str) -> str:
    """The form a session reference is stored in on an item: its permanent id when the registry resolves it, else the value unchanged."""
    v = str(value or "").strip()
    return resolve(v) or v if v else v


def _same_sess(a: str, b: str) -> bool:
    """Do two stored references name one session? As permanent ids when the registry resolves both, else as the strings stand."""
    t = same(a, b)
    return (a == b) if t is None else t


class _Index(dict):
    """The heartbeat index (transcript UUID → row) that also answers for a permanent session id: a lookup (get, [], in) by an id the registry
    holds finds the row of that session's present transcript (the running one, else the latest seen), its name the registry's. Iteration
    (items, values, keys) is the heartbeat's own and lists each session once, by transcript."""
    unreadable: list[str] = []      # the machines whose sessions.json could not be read when the index was built (`_sessions_index` sets it): the index is partial then
    def _via(self, k: Any) -> dict[str, Any] | None:
        if not isinstance(k, str) or not is_perm_id(k):
            return None
        best = None
        for t in transcripts(k):
            r = dict.get(self, t)
            if r is not None and (best is None or (_lv.running(r), str(r.get("seen", ""))) >= (_lv.running(best), str(best.get("seen", "")))):
                best = r
        if best is None:
            return None
        return {**best, "name": display_name(k) or best.get("name")}
    def __missing__(self, k: Any) -> dict[str, Any]:
        r = self._via(k)
        if r is None:
            raise KeyError(k)
        return r
    def get(self, k: Any, default: Any = None) -> Any:
        return dict.get(self, k) if dict.__contains__(self, k) else (self._via(k) or default)
    def __contains__(self, k: Any) -> bool:
        return dict.__contains__(self, k) or self._via(k) is not None


def _sessions_index() -> dict[str, dict[str, Any]]:
    """transcript UUID → {name, url, seen, machine} from every machine's live heartbeat (fleet.py; out of git). A permanent session
    id looks up the same way (see _Index). `.unreadable` on the result lists the machines whose sessions.json could not be read (fleet.sessions_unreadable): the index is partial then, and a session missing from it
    may be on one of those machines, not gone."""
    out = _Index()
    out.unreadable = _fleet.sessions_unreadable()
    for L in _fleet.letters():
        for k, v in _fleet.read(L, "sessions").items():
            if isinstance(v, dict) and not dict.__contains__(out, k): out[k] = {"machine": L, **v}
    return out
