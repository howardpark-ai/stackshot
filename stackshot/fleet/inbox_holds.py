"""inbox_holds.py — holds on a session's inbox, kept through the client API as well as through the files.

A fleet tool that relaunches a pane holds that pane's inbox first, so a line the puller hands out in that moment is not accepted by a process that is going away
(inbox.take skips a held key). A tool on the server's own box writes `held-<source>.txt` in the state's anchor-hub folder (one file for each of the two sources, `hub` and `msg`);
inbox.py and push.py read it. A tool on ANOTHER box cannot, so the same hold is a call to the server:

    POST /client/inbox-hold     {"keys": ["<uuid>", "<name>"], "kinds": ["msg", "hub"], "minutes": 10}
    POST /client/inbox-release  {"keys": [...], "kinds": [...]}
    GET  /client/inbox-holds    [?key=<key>]        what is held, one row for each (kind, key, file family)
    GET  /client/inbox-waiting  ?key=<name>[,<uuid>] does a line wait for that session, by kind

The calls write their OWN file, `held-api-<source>.txt`, under their own lock, and never read-modify-write a file another tool writes: the server's readers (inbox.py, push.py) count a key
as held when it is in the API's file or in `held-<source>.txt` or in a reboot's resume's `held-resume-<source>.txt`. Each hold made through the call carries a time, kept in <state>/anchor-hub/holds-api.json,
and expires: after `minutes` (1 to 1440, else [client] inbox_hold_minutes, 10; that setting 0 = never) the key is taken out of the API's file by sweep() (the server's minute tick), so a relaunch that
died and never released leaves nothing held for good. Holding again is a refresh. A key in the other tool's file or the resume's is listed with `origin` file or resume; it is never expired
or touched here, and a release that names it says so (`held_elsewhere`):
that tool lifts its own holds.
Stdlib only, as inbox.py."""
from __future__ import annotations

try:
    import fcntl
except ModuleNotFoundError:      # Windows has no flock: the file lock below is then not taken (a module the puller's box may import must load there)
    fcntl = None  # type: ignore[assignment]
import json
import logging
import os
import time
from typing import Any

from stackshot.core import config as _cfg
from stackshot.fleet import inbox as _inbox

log = logging.getLogger("stackshot.inbox")
LEDGER_NAME = "holds-api.json"       # {"<kind>": {"<key>": {"since": epoch, "expires": epoch | 0}}} in the state's anchor-hub folder: the times of the keys in the API's own files
MAX_KEYS = 20
MAX_KEY = 200
MAX_MINUTES = 1440.0                 # a hold lasts a day at most
DEFAULT_MINUTES = 10.0               # the fleet tool's own stale-hold limit
MAX_FILE_KEYS = 500                  # keys in one of the API's files: every inbox.take and push.paused reads the whole file


class HoldRefused(ValueError):
    """A hold the module will not make (the API's file would pass MAX_FILE_KEYS, or a key cannot be written): the message is the reason, api_hold answers it as a 400."""


class LedgerError(ValueError):
    """The times file is there but is not what this module wrote (unparsable, or not the shape of one)."""


def _flags():
    return _inbox.FLAGS               # read at each call: a suite points it elsewhere


class _locked:
    """One writer at a time for the API's hold files and their times (a read-modify-write of small files only this module writes)."""
    def __enter__(self):
        _flags().mkdir(parents=True, exist_ok=True)
        self.f = open(_flags() / ".holds-api.lock", "w")
        if fcntl is not None:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        if fcntl is not None:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def default_minutes() -> float:
    """[client] inbox_hold_minutes as a number of minutes: 0 = until released (the operator's own choice); a value that is negative, not a finite number or a bool is the default (10); above a day it is a day."""
    import math
    v = _cfg.get("client", "inbox_hold_minutes", default=DEFAULT_MINUTES)
    try:
        m = DEFAULT_MINUTES if isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return DEFAULT_MINUTES
    if not math.isfinite(m) or m < 0:
        return DEFAULT_MINUTES
    return min(m, MAX_MINUTES)


def _ledger() -> dict[str, dict[str, dict[str, float]]]:
    """The times of the keys in the API's files. No file → {}. A file that is not a JSON object of the shape this module writes → LedgerError; a read that fails for any other reason (permissions, a disk
    error) is raised as it is, never taken for "no times": a call that saved over a ledger it could not read would leave the other keys' holds with no end."""
    try:
        with open(_flags() / LEDGER_NAME, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:                       # JSONDecodeError, UnicodeDecodeError
        raise LedgerError(f"{LEDGER_NAME} is not JSON: {e}") from e
    if not isinstance(d, dict):
        raise LedgerError(f"{LEDGER_NAME} is not a JSON object")
    out: dict[str, dict[str, dict[str, float]]] = {}
    try:
        for kind, rows in d.items():
            if kind in _inbox.SOURCES:
                if not (isinstance(rows, dict) and all(isinstance(v, dict) for v in rows.values())):
                    raise ValueError(f"{kind} is not a table of rows")
                out[kind] = {str(k): {"since": float(v.get("since") or 0), "expires": float(v.get("expires") or 0)} for k, v in rows.items()}
    except (TypeError, ValueError) as e:
        raise LedgerError(f"{LEDGER_NAME} has a row that is not a time: {e}") from e
    return out


def _ledger_to_write() -> dict[str, dict[str, dict[str, float]]]:
    """The times, for a call that saves them back (the caller holds the lock). A file that is not readable as times is moved aside to `holds-api.json.bad` (kept for a look, one copy) with a log line, and
    the call goes on with no times: every key in the API's files that then has no time is given one (`_adopt`) in the same call, so none of them is left without an end. Any other failure is raised."""
    try:
        return _ledger()
    except LedgerError as e:
        log.error("inbox: %s: moved aside to %s.bad; the keys held through the API get a new time (the setting's minutes)", e, LEDGER_NAME)
        os.replace(_flags() / LEDGER_NAME, _flags() / (LEDGER_NAME + ".bad"))
        return {}


def _adopt(led: dict[str, dict[str, dict[str, float]]], now: float) -> bool:
    """Give a time of `[client] inbox_hold_minutes` from now to each key in the API's files that has none (a hold whose time never reached the ledger, or a ledger that was lost). Nothing when that setting is 0
    (never). → True when a row was added."""
    mins = default_minutes()
    if mins <= 0:
        return False
    added = False
    for kind in _inbox.SOURCES:
        rows = led.setdefault(kind, {})
        for k in _read(_api_path(kind)):
            if k not in rows:
                rows[k] = {"since": now, "expires": now + mins * 60.0}; added = True
    return added


def _save_ledger(d: dict[str, dict[str, dict[str, float]]]) -> None:
    p = _flags() / LEDGER_NAME
    d = {k: v for k, v in d.items() if v}
    if not d:
        try:
            p.unlink()
        except OSError:
            pass
        return
    tmp = _flags() / f".{LEDGER_NAME}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read(path) -> list[str]:
    """The keys of a flag file in file order, read as the server's readers read it (`inbox.lines_of`: whitespace around a key dropped), so `abc ` and `abc` are one key."""
    return _inbox.lines_of(path)


def _write(path, lines: list[str]) -> None:
    data = "".join(f"{ln}\n" for ln in lines).encode("utf-8")        # a key that cannot be encoded raises here, before a temp file exists
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _api_path(kind: str):
    return _flags() / _inbox.held_files(kind)[2]


def _elsewhere(kind: str) -> set[str]:
    """The keys held in the files another tool writes (`held-<source>.txt`, the reboot's resume's `held-resume-<source>.txt`): read only."""
    return {k for f in _inbox.held_files(kind)[:2] for k in _read(_flags() / f)}


def _edit(kind: str, add: list[str], drop: list[str]) -> None:
    """The API's own hold file for the kind with keys added and dropped (the caller holds the lock). Nothing else writes this file, so a read and a replace is enough; no other file is read for it."""
    path = _api_path(kind)
    cur = _read(path)
    new = [k for k in cur if k not in drop] + [k for k in dict.fromkeys(add) if k not in cur and k not in drop]
    if new != cur:
        _write(path, new)


def _kinds(v: Any) -> list[str] | str:
    """The kinds a call names → a list of sources, or the refusal."""
    if v in (None, "", []):
        return list(_inbox.SOURCES)
    if isinstance(v, str):
        v = [v]
    if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)) or any(x not in _inbox.SOURCES for x in v):
        return "kinds = a list of " + " | ".join(_inbox.SOURCES) + ", or left out for both"
    return list(dict.fromkeys(v))


def _encodable(x: str) -> bool:
    try:
        x.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _keys(v: Any) -> list[str] | str:
    """The keys a call names (a session's transcript id and its name, as the fleet tool holds them) → the list, or the refusal."""
    if isinstance(v, str):
        v = [v]
    if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
        return "keys = a list of the session's keys: its transcript id and its name"
    out = [x.strip() for x in v if x.strip()]
    if not out or len(out) > MAX_KEYS or any(len(x) > MAX_KEY or not x.isprintable() or not _encodable(x) for x in out):
        return f"keys = 1 to {MAX_KEYS} keys, each one line of at most {MAX_KEY} printable characters"
    return list(dict.fromkeys(out))


def hold(keys: list[str], kinds: list[str], minutes: float | None = None, now: float | None = None) -> dict[str, Any]:
    """Hold these keys in these sources' API files, for `minutes` (None = the setting; 0 = until released, which the API's call never asks for). Again for a key held already is a refresh.
    A key another tool holds as well is held here too: it stays held when that tool lifts its own hold, and this call's release lifts only this one.
    The times are saved BEFORE the files are written, so a failure to save leaves nothing held (a key in a file with no time would never expire); a time without its key is dropped by the next sweep.
    Raises HoldRefused when a key cannot be written as UTF-8 or when an API file would pass MAX_FILE_KEYS keys. → {held, expires}: `expires` = when the keys end (None for 0 minutes)."""
    now = time.time() if now is None else now
    mins = default_minutes() if minutes is None else minutes
    exp = now + mins * 60.0 if mins > 0 else 0.0
    if not all(_encodable(k) for k in keys):
        raise HoldRefused("a key is not text that can be written to the hold file")
    with _locked():
        for kind in kinds:
            if len(set(_read(_api_path(kind))) | set(keys)) > MAX_FILE_KEYS:
                raise HoldRefused(f"at most {MAX_FILE_KEYS} keys can be held through the API at one time for {kind}: release some first")
        led = _ledger_to_write()
        for kind in kinds:
            for k in keys:
                led.setdefault(kind, {})[k] = {"since": now, "expires": exp}
        _adopt(led, now)
        _save_ledger(led)
        for kind in kinds:
            _edit(kind, keys, [])
    return {"held": {kind: keys for kind in kinds}, "expires": exp or None}


def release(keys: list[str], kinds: list[str]) -> dict[str, Any]:
    """Take these keys out of these sources' API files. A key held only in a file another tool writes (`held-<source>.txt`, the reboot's resume's `held-resume-<source>.txt`) is left where it is
    and named in `held_elsewhere` (a flat list of keys, only when there is one: that tool lifts its own holds), as is a key that stays held there after this release.
    → {released: {kind: the keys that were in the API's file}, held_elsewhere?: [keys]}."""
    out: dict[str, list[str]] = {}
    other: set[str] = set()
    with _locked():
        led = _ledger_to_write()
        for kind in kinds:
            was = set(_read(_api_path(kind)))
            out[kind] = [k for k in keys if k in was]
            _edit(kind, [], keys)
            for k in keys:
                led.get(kind, {}).pop(k, None)
            other |= _elsewhere(kind)
        _save_ledger(led)
    elsewhere = [k for k in keys if k in other]
    return {"released": out, **({"held_elsewhere": elsewhere} if elsewhere else {})}


def sweep(now: float | None = None) -> list[str]:
    """Take out of the API's files the keys whose time has run out, and drop the times of keys no longer in the file (never a key of another tool's file). A key in the API's file with no time (a ledger
    that was lost, or a hold whose time was never saved) is given one of the setting's minutes from now, and goes when that runs out; with the setting at 0 it is left, as every key with no end is.
    → "kind:key" of each key taken out. Cheap when nothing is held: one stat for each file. The minute tick calls it, so a hold ends up to a minute after its time."""
    now = time.time() if now is None else now
    if not (_flags() / LEDGER_NAME).exists() and not any(_api_path(k).exists() for k in _inbox.SOURCES):
        return []
    gone: list[str] = []
    with _locked():
        led = _ledger_to_write()
        changed = _adopt(led, now)
        for kind in _inbox.SOURCES:
            rows = led.setdefault(kind, {})
            present = set(_read(_api_path(kind)))
            dead = [k for k, v in rows.items() if v["expires"] and v["expires"] <= now and k in present]
            if dead:
                _edit(kind, [], dead)
                gone += [f"{kind}:{k}" for k in dead]
            for k in [k for k in rows if k in dead or k not in present]:
                rows.pop(k); changed = True
        if gone or changed:
            _save_ledger(led)
    for g in gone:
        log.warning("inbox: hold %s expired (made through the client API and never released): taken out of its file", g)
    return gone


def listing(key: str = "", now: float | None = None) -> dict[str, Any]:
    """What is held: {holds: [{kind, key, origin: api | file | resume, since, expires}]}, one row for each kind, key and file family that holds it: `api` = the API's own file (`held-api-<source>.txt`, with `since` and
    `expires` as epochs, null for a key with no time), `file` = the other tool's `held-<source>.txt`, `resume` = a reboot's resume's `held-resume-<source>.txt`. `key` narrows to one key."""
    now = time.time() if now is None else now
    try:
        led = _ledger()
    except LedgerError:
        led = {}                                   # a read changes nothing: the rows then show no times
    rows: list[dict[str, Any]] = []
    for kind in _inbox.SOURCES:
        plain, resume, api = (_read(_flags() / f) for f in _inbox.held_files(kind))
        for k in dict.fromkeys(api):
            t = led.get(kind, {}).get(k)
            rows.append({"kind": kind, "key": k, "origin": "api", "since": t["since"] if t else None, "expires": (t["expires"] or None) if t else None})
        rows += [{"kind": kind, "key": k, "origin": "file", "since": None, "expires": None} for k in dict.fromkeys(plain)]
        rows += [{"kind": kind, "key": k, "origin": "resume", "since": None, "expires": None} for k in dict.fromkeys(resume)]
    if key:
        rows = [r for r in rows if r["key"] == key]
    return {"holds": rows, "now": now}


def waiting(keys: list[str]) -> dict[str, Any]:
    """Does a line wait in the inbox for the session these keys name (its name, its transcript id): a line whose address (`to`), transcript id, name or permanent id equals one of them. Held or not it counts, as
    it does for a fleet tool deciding whether a pane may sleep. → {keys, hub, msg, waiting, held: {hub, msg}}, `held` = a key is in any of the three hold files of that source"""
    want = set(keys)
    n = {s: 0 for s in _inbox.SOURCES}
    for it in _inbox._items():
        if any(str(it.get(f) or "") in want for f in ("to", "uuid", "name", "pid")):
            n[it["src"] if it.get("src") in n else "msg"] += 1
    held = {s: any(want & set(_read(_flags() / f)) for f in _inbox.held_files(s)) for s in _inbox.SOURCES}
    return {"keys": keys, **n, "waiting": any(n.values()), "held": held}


def api_hold(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /client/inbox-hold body {keys, kinds?, minutes?} → (status, JSON). `minutes` is above 0 and at most 1440, or left out for the setting's: a hold made by the call always has an end (0 is refused)."""
    keys, kinds = _keys(body.get("keys")), _kinds(body.get("kinds"))
    if isinstance(keys, str):
        return 400, {"error": keys}
    if isinstance(kinds, str):
        return 400, {"error": kinds}
    minutes = None
    if body.get("minutes") not in (None, ""):
        try:
            minutes = -1.0 if isinstance(body["minutes"], bool) else float(body["minutes"])
        except (TypeError, ValueError):
            minutes = -1.0
        if not (0.0 < minutes <= MAX_MINUTES):
            return 400, {"error": f"minutes = more than 0 and at most {int(MAX_MINUTES)} (a hold always ends: 0 is refused), or left out for the setting's {default_minutes():g}"}
    try:
        return 200, hold(keys, kinds, minutes)
    except HoldRefused as e:
        return 400, {"error": str(e)}


def api_release(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /client/inbox-release body {keys, kinds?} → (status, JSON)."""
    keys, kinds = _keys(body.get("keys")), _kinds(body.get("kinds"))
    if isinstance(keys, str):
        return 400, {"error": keys}
    if isinstance(kinds, str):
        return 400, {"error": kinds}
    return 200, release(keys, kinds)
