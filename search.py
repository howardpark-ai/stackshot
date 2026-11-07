"""search.py — the board's search (the design: docs/design, its build plan "Step 3", Search).

One box on every page (the board, a project page, an item page) and one results page at /search?q=…, over four kinds of text:

  item     the subject, the goal, the description, the next lines and the ask of every item (open or closed), found by its id as well (48)
  history  the item page's History: one entry per change (the lines Board.item_events draws), at most 600 characters each
  project  the Current state of every active project page (read from the pages checkout, [paths] brain; never from gbrain on the request path)
  session  the session names the board reads (the fleet tool's registry), with their machine, project and role

A result links the item or the page; a session result links the fleet tool's view the way the board does (Board.sess_href: only while the
session has a live pane, else the name stays text). No model call: SQLite's FTS5 (stdlib), unicode61 with the diacritics folded, a prefix match on
every word typed (a run of Hangul or Kana syllables is one word to unicode61, so a stem finds the same word with a particle glued on). A query shorter than two characters finds nothing.
That prefix match is `query`'s, which no page uses now. The board uses `words`, `find` and `snippets` below over the same index: every typed unit as a case-insensitive substring, "quoted text" as one unit, as the fleet tool's search has it (ui/search.py).

Where the index lives: <[paths] state>/search/index.db, derived data, rebuilt from the store (a schema change drops it and builds it again, a missing
or unwritable file falls back to an in-memory database; FTS5 missing from the SQLite build falls back to a LIKE scan over the same table).
How it stays current: every item file's (mtime, size) is stamped beside its rows (the History is git-derived, so the item file is all there is to stamp); `sync(board)` re-indexes the items whose stamp moved, drops the ones gone (never more than a tenth of the stamps in one pass:
a Board that read part of the store drops nothing), re-reads a project page whose file changed and the session names when they change. The server calls
`touch(gid)` from its one item save (an item written is re-indexed within seconds by the background loop, at nice 10), the results page syncs before it answers
(so a write is never missed; it writes the item's text only, the History is the thread's: the page never waits on git), and the loop also runs every few minutes and
once at start (the first build indexes the History of every item, a git read each, in chunks, newest first, the lock held for the database only). An item whose
History came back empty (a git timeout) is indexed by its text, stamped as owed, and tried again after RETRY_AFTER; a damaged index file is dropped and built again.
Stdlib only; render.py is imported inside functions (it imports this module for the box)."""
from __future__ import annotations

import contextlib
import hashlib
import html as H
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import config as _cfg
import readonly as _ro      # on a read-only standby copy the index lives in memory only (no file, no directory in the state dir)

SCHEMA = 1                   # a change to the tables or to what is indexed bumps it: the next start drops the index and builds it again
MIN_CHARS = 2                # a query shorter than this finds nothing
MAX_Q = 200                  # characters of a query read
MAX_TERMS = 8                # words of a query read
LIMIT = 25                   # results shown per kind
CAP = {"item": 20000, "history": 600, "project": 12000, "session": 400}   # characters indexed per row
REQUEST_ITEMS = 8            # items a results page indexes before it answers (the history of one is a git read): a first build is the thread's
CHUNK = 10                   # items indexed per call while the first build runs (the lock is let go between chunks, so a page never waits long)
EVERY = 300.0                # seconds between the loop's own syncs (a safety net; a write wakes it at once)
RETRY_AFTER = 600.0          # seconds before an item that failed (its History came back empty, or its write failed) is tried again
STALL = 3                    # chunks in a row that index nothing end a build pass
PAUSE = 0.2                  # seconds between the chunks of a build
DROP_MAX = 0.10              # a pass drops at most this share of the stamps of one kind (and DROP_FLOOR of them whatever the share): see _guard_drop
DROP_FLOOR = 5
DEBOUNCE = 2.0               # seconds a write waits before the loop re-indexes it (a burst of saves is one pass)
KINDS = ("item", "history", "project", "session")
TITLES = {"item": "Items", "history": "History", "project": "Projects", "session": "Sessions"}

_LOCK = threading.RLock()
_CON: sqlite3.Connection | None = None
_FTS = True                  # False: the LIKE fallback (a test turns it off; a SQLite build without FTS5 does)
_FORCE: set[str] = set()     # items touched by a save: re-indexed whatever their stamp says (two writes inside one clock tick keep one stamp)
_WAKE = threading.Event()
_FAILED: dict[str, float] = {}   # item → when its History last failed to read or its write failed: not tried again before RETRY_AFTER
_PARTIAL: set[str] = set()       # items written without their History (the results page never reads it): the thread owes it


# ----------------------------------------------------------------------------- the database
def _db_path() -> Path:
    return _cfg.state("search", "index.db")


def _fts_ok(con: sqlite3.Connection) -> bool:
    try:
        con.execute("create virtual table temp._probe using fts5(a)")
        con.execute("drop table temp._probe")
        return True
    except sqlite3.Error:
        return False


def _open(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)   # autocommit: a write is its own BEGIN … COMMIT
    con.execute("pragma busy_timeout=30000")
    con.execute("pragma journal_mode=wal")
    con.execute("pragma synchronous=normal")              # with the WAL: a power cut loses the last writes, never the file; the index is derived data
    con.execute("select count(*) from sqlite_master")     # a file that is not a database fails here, not at the first write
    return con


def _create(con: sqlite3.Connection) -> None:
    """The tables, dropped first: the index is derived data. `doc` is one table for the four kinds: kind, key (an item's id, a page key, a session
    name), sub (what the kind shows beside it: an event's kind, a machine), ts (an event's time) are stored; title and body are searched."""
    for t in ("doc", "stamp", "meta"):
        con.execute(f"drop table if exists {t}")
    if _FTS:
        con.execute("create virtual table doc using fts5(kind unindexed, key unindexed, sub unindexed, ts unindexed, title, body, tokenize='unicode61 remove_diacritics 2')")
    else:
        con.execute("create table doc(kind text, key text, sub text, ts real, title text, body text)")
        con.execute("create index doc_k on doc(kind, key)")
    con.execute("create table stamp(kind text, key text, sig text, primary key(kind, key))")
    con.execute("create table meta(k text primary key, v text)")
    con.execute(f"pragma user_version={SCHEMA}")


def _con() -> sqlite3.Connection:
    global _CON, _FTS
    with _LOCK:
        if _CON is not None:
            return _CON
        con = None
        for attempt in (() if _ro.is_read_only() else (0, 1)):    # standby: no index file at all, the database below is :memory:
            try:
                p = _db_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                con = _open(str(p))
                break
            except (OSError, sqlite3.Error) as e:
                if attempt == 0 and _corrupt(e):                  # a damaged file is replaced, once
                    print(f"search: {e.__class__.__name__}: {e}; the index file is made again", file=sys.stderr, flush=True)
                    _unlink_db()
                    continue
                print(f"search: {e.__class__.__name__}: {e}; the index is in memory this run", file=sys.stderr, flush=True)
                break
        if con is None:
            con = _open(":memory:")
        if _FTS and not _fts_ok(con):
            _FTS = False
            print("search: this SQLite has no FTS5; the index is a LIKE scan", file=sys.stderr, flush=True)
        mode = "fts5" if _FTS else "like"
        try:
            ok = (con.execute("pragma user_version").fetchone()[0] == SCHEMA
                  and con.execute("select v from meta where k='mode'").fetchone() == (mode,))
        except sqlite3.Error:
            ok = False
        if not ok:
            _create(con)
            con.execute("insert into meta values('mode', ?)", (mode,))
        _CON = con
        return con


def reset() -> None:
    """Close the database and forget the process state (tests, and a config change of the state directory)."""
    global _CON, _STANDBY_AT
    _STANDBY_AT = 0.0
    with _LOCK:
        if _CON is not None:
            try:
                _CON.close()
            except sqlite3.Error:
                pass
        _CON = None
        _FORCE.clear(); _FAILED.clear(); _PARTIAL.clear()


def size_bytes() -> int:
    try:
        return _db_path().stat().st_size
    except OSError:
        return 0


# ----------------------------------------------------------------------------- what is indexed
def _clean(text: Any, cap: int) -> str:
    """Free text as indexed: no control characters (\\x02 and \\x03 mark a match in a snippet and must come from nowhere else), cut at `cap`."""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text or "")).strip()
    return t[:cap]


def _plain(html_text: str) -> str:
    """A History line's HTML as the text it reads as."""
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", html_text or "")).split())


@contextlib.contextmanager
def _tx(con: sqlite3.Connection):
    """One write transaction: committed when the block ends, rolled back when it raises (a connection left in a transaction would refuse every later write)."""
    con.execute("begin")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def _put(con: sqlite3.Connection, kind: str, key: str, sub: str, ts: float, title: str, body: str) -> None:
    con.execute("insert into doc(kind, key, sub, ts, title, body) values(?,?,?,?,?,?)", (kind, key, sub, ts, title, body))


def _drop(con: sqlite3.Connection, kinds: tuple[str, ...], key: str) -> None:
    con.execute(f"delete from doc where key=? and kind in ({','.join('?' * len(kinds))})", (key, *kinds))


def _item_sig(r: dict[str, Any]) -> str:
    try:
        st = Path(r["_path"]).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except (OSError, KeyError):
        return "?"


def _prepare_item(board: Any, r: dict[str, Any], history: bool) -> dict[str, Any]:
    """What one item's rows will be: no database and no lock (the History is a git read). → {gid, sig, title, body, events, full}.
    `full` is False when the History is not there: not asked for (the results page never waits on git), or empty, which is what a git timeout or error looks like
    (Board.item_events draws at least the item's first version when git answers); the item's own text is written either way and the stamp says the History is owed."""
    import ghsync as _gh
    gid = r["gid"]
    sig = _item_sig(r)                                               # taken before the file is read: a write that lands after it is a later stamp, indexed next time
    try:                                                              # the file as it is now, not the Board's copy (a first build outlives the Board it started with)
        with open(r["_path"], encoding="utf-8") as f:
            cur = json.load(f)
        r = {**r, "subject": cur.get("subject"), "description": cur.get("description"), "metadata": cur.get("metadata") or {}, "status": cur.get("status") or r.get("status")}
    except (OSError, ValueError, KeyError):
        pass
    m = r.get("metadata") or {}
    body = "\n".join(_clean(x, CAP["item"]) for x in (m.get("goal"), r.get("description"), m.get("outcome_text"), m.get("next"), m.get("ask")) if x and str(x).strip())
    shown = _gh.shown(gid)
    ids = shown if shown == gid else f"{shown} {gid}"                # found by its id: board#N and g7 (an older item is both)
    events: list[tuple[float, str, str]] = []
    if history:
        try:
            for ts, kind, html_text in board.item_events(r)[0]:
                txt = _clean(_plain(html_text), CAP["history"])
                if txt:
                    events.append((float(ts), str(kind), txt))
        except Exception as e:  # noqa: BLE001  — the History is an extra: an item the store's git cannot read is still found by its own text
            print(f"search: history of {gid} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return {"gid": gid, "sig": sig, "title": f"{_clean(r.get('subject'), 500)} {ids}", "body": body[:CAP["item"]], "events": events, "full": history and bool(events)}


def _write_item(con: sqlite3.Connection, p: dict[str, Any]) -> None:
    """One item's rows, replacing any it had (the lock is held). A partial one keeps the History rows it had and is stamped `<sig>!`, so the next pass reads the History."""
    gid = p["gid"]
    prev = con.execute("select sig from stamp where kind='item' and key=?", (gid,)).fetchone()
    had_full = prev is not None and not prev[0].endswith("!")        # an item whose History was read once keeps those rows while the new read is owed: it is not partial
    with _tx(con):
        _drop(con, ("item", "history") if p["full"] else ("item",), gid)
        _put(con, "item", gid, "", 0.0, p["title"], p["body"])
        for ts, kind, txt in p["events"] if p["full"] else ():
            _put(con, "history", gid, kind, ts, "", txt)
        con.execute("insert or replace into stamp values('item', ?, ?)", (gid, p["sig"] + ("" if p["full"] else "!")))
    if p["full"]:
        _PARTIAL.discard(gid)
    elif not had_full:
        _PARTIAL.add(gid)


def _guard_drop(what: str, n_gone: int, n_seen: int, have: int) -> bool:
    """May a pass drop `n_gone` of the `have` stamps of one kind, when the Board it reads holds `n_seen` of them? A Board that read a part of the store (it is smaller than the
    stamps by more than DROP_MAX) would otherwise empty the index: the drop is skipped and logged, and the next whole read drops what is really gone. A Board as big as
    the stamps drops whatever has gone (a bulk re-key: old ids out, new in), and so does any drop of DROP_FLOOR or fewer."""
    if n_gone <= DROP_FLOOR or n_seen >= (1 - DROP_MAX) * have:
        return True
    print(f"search: not dropping {n_gone} of {have} {what}: the store read holds {n_seen} (a partial read?); left for a pass that reads it whole", file=sys.stderr, flush=True)
    return False


def sync(board: Any, max_items: int | None = None, skip: set[str] | None = None, history: bool = True) -> dict[str, Any]:
    """Bring the index to the board's store: the items whose file (or issue comments) moved, the project pages, the session names. `max_items` bounds the items indexed in
    this call; `left` is what is still to do. `skip` is the set of items a build pass has failed on (this call adds its own failures to it); an item that failed is not
    tried again for RETRY_AFTER seconds either. `history=False` writes the item's own text and leaves its History to the thread (the results page uses it: it never waits
    on git). The lock is held for the database only, never across the History reads. → {"items" (indexed), "pages", "sessions", "left", "failed": [gids]}."""
    skip = skip if skip is not None else set()
    now = time.time()
    with _LOCK:
        con = _con()
        rows = {r["gid"]: r for r in board.rows}
        stamps = dict(con.execute("select key, sig from stamp where kind='item'").fetchall())
        gone = set(stamps) - set(rows)                               # an item the store no longer holds
        if gone and _guard_drop("items", len(gone), len(rows), len(stamps)):
            for g in gone:
                with _tx(con):
                    _drop(con, ("item", "history"), g)
                    con.execute("delete from stamp where kind='item' and key=?", (g,))
                _PARTIAL.discard(g)
        todo = []
        for g, r in rows.items():
            if g in skip:
                continue
            sig = _item_sig(r)
            if g in _FORCE:
                todo.append(r)
            elif stamps.get(g) != sig and not (not history and stamps.get(g) == sig + "!") and now - _FAILED.get(g, 0.0) >= RETRY_AFTER:
                todo.append(r)
        todo.sort(key=lambda r: float(r.get("updated") or 0), reverse=True)
        batch = todo if max_items is None else todo[:max_items]
    preps: list[dict[str, Any]] = []
    failed: list[str] = []
    for r in batch:                                                    # no lock: a git read each
        try:
            preps.append(_prepare_item(board, r, history))
        except Exception as e:  # noqa: BLE001
            print(f"search: {r['gid']} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            skip.add(r["gid"]); _FAILED[r["gid"]] = now; failed.append(r["gid"])
    done = 0
    with _LOCK:
        con = _con()
        for p in preps:
            g = p["gid"]
            _FORCE.discard(g)
            try:
                _write_item(con, p)
            except Exception as e:  # noqa: BLE001  — one item never stops the rest (a corrupt file is the caller's: _corrupt)
                if _corrupt(e):
                    raise
                print(f"search: {g} not indexed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                skip.add(g); _FAILED[g] = now; failed.append(g)
                continue
            done += 1
            if history and not p["full"]:                              # git said nothing: not stamped as done, tried again after RETRY_AFTER, not by the next chunk
                skip.add(g); _FAILED[g] = now; failed.append(g); _PARTIAL.discard(g)
            elif p["full"]:
                _FAILED.pop(g, None)
            elif not history and not _ro.is_read_only():
                _FORCE.add(g); _WAKE.set()                             # the thread reads its History within seconds (none on a standby: it indexes the text only)
        out: dict[str, Any] = {"items": done, "pages": 0, "sessions": 0, "left": len(todo) - len(batch), "failed": sorted(set(failed))}
        try:
            out["pages"] = _sync_pages(con, board)
        except Exception as e:  # noqa: BLE001  — pages and sessions are extras: the items are indexed whatever they do
            if _corrupt(e):
                raise
            print(f"search: pages not indexed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        try:
            out["sessions"] = _sync_sessions(con, board)
        except Exception as e:  # noqa: BLE001
            if _corrupt(e):
                raise
            print(f"search: sessions not indexed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        con.execute("insert or replace into meta values('built', ?)", ("0" if out["left"] else "1",))
        return out


def _sync_pages(con: sqlite3.Connection, board: Any) -> int:
    """Each active project page's Current state, from the pages checkout (a second brain's page from that brain's own copy, [[brains]]); a page
    whose file is unchanged is left. No checkout (another machine): none."""
    import brains as _brains
    import pages as _pages
    brain = Path(_pages.BRAIN)
    if not brain.is_dir():
        return 0
    stamps = dict(con.execute("select key, sig from stamp where kind='project'").fetchall())
    live: dict[str, tuple[str, dict[str, Any]]] = {}
    for key, info in (board.proj or {}).items():
        if not isinstance(info, dict) or not _pages._active(info):
            continue
        b = _brains.for_key(key)
        try:
            st = ((brain if b.default else b.path) / (key + ".md")).stat()
        except OSError:
            if not b.default and _brains.problem(b):
                stamp = stamps.get(key)       # fail open: a second brain whose copy is away keeps its page indexed as it was
                if stamp:
                    live[key] = (stamp, info)
            continue
        live[key] = (f"{st.st_mtime_ns}:{st.st_size}:{info.get('name') or info.get('title') or ''}", info)
    n = 0
    gone = set(stamps) - set(live)
    if gone and _guard_drop("project pages", len(gone), len(live), len(stamps)):
        for key in gone:
            with _tx(con):
                _drop(con, ("project",), key)
                con.execute("delete from stamp where kind='project' and key=?", (key,))
    for key, (sig, info) in live.items():
        if stamps.get(key) == sig:
            continue
        try:
            state = _clean(_pages.current_state(key, cap=CAP["project"] * 2), CAP["project"])
        except Exception as e:  # noqa: BLE001
            print(f"search: page {key} not indexed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            continue
        with _tx(con):
            _drop(con, ("project",), key)
            _put(con, "project", key, "", 0.0, f"{_clean(info.get('name') or info.get('title') or key, 200)} {key}", state)
            con.execute("insert or replace into stamp values('project', ?, ?)", (key, sig))
        n += 1
    return n


def _sync_sessions(con: sqlite3.Connection, board: Any) -> int:
    """The session names the board reads (its `name:` entries), with the machine, the registry's project and role; rewritten only when they change."""
    import sessions_registry as _sr
    machines = set((board.fleet or {}).values())
    rows: list[tuple[str, str, str]] = []
    for k, v in sorted(board.sess.items()):
        if not k.startswith("name:") or not isinstance(v, dict) or k[5:] in machines:
            continue
        name = _clean(k[5:], 200)
        if not name:
            continue
        mach = _clean((board.fleet or {}).get(v.get("machine")) or str(v.get("machine") or ""), 100)
        try:
            reg = _sr.row(name) or {}
        except Exception:  # noqa: BLE001
            reg = {}
        rows.append((name, mach, _clean(" ".join(str(reg.get(f) or "") for f in ("project", "role")), CAP["session"])))
    sig = hashlib.sha1(repr(rows).encode()).hexdigest()
    cur = con.execute("select sig from stamp where kind='session' and key='*'").fetchone()
    if cur and cur[0] == sig:
        return 0
    have = con.execute("select count(*) from doc where kind='session'").fetchone()[0]
    if have > len(rows) and not _guard_drop("session names", have - len(rows), len(rows), have):
        return 0
    with _tx(con):
        con.execute("delete from doc where kind='session'")
        for name, mach, extra in rows:
            _put(con, "session", name, mach, 0.0, name, f"{mach} {extra}".strip())
        con.execute("insert or replace into stamp values('session', '*', ?)", (sig,))
    return len(rows)


def building() -> bool:
    """True while the index is not whole: items still to index, or items whose History is still to be read."""
    with _LOCK:
        try:
            r = _con().execute("select v from meta where k='built'").fetchone()
        except sqlite3.Error:
            return True
        return not r or r[0] != "1" or bool(_PARTIAL)


def touch(gid: str) -> None:
    """The server's one item save calls this: the item is re-indexed within a few seconds by the loop (never in the writer's own time)."""
    _FORCE.add(str(gid))
    _WAKE.set()


def _board() -> Any:
    import render as _rmod
    return _rmod.Board(str(_cfg.path("paths", "store")))


def _corrupt(e: BaseException) -> bool:
    """Does this error say the index file is damaged (not a database, a malformed image, a table gone), as against a lock or a full disk?"""
    if type(e) is sqlite3.DatabaseError:              # what SQLite's NOTADB and CORRUPT come back as
        return True
    if type(e) is sqlite3.OperationalError:
        return any(w in str(e).lower() for w in ("no such table", "malformed", "not a database", "disk image"))
    return False                                      # a ProgrammingError, an IntegrityError, a lock: a bug or a wait, never a reason to delete the index


def _unlink_db() -> None:
    if _ro.is_read_only():                            # standby: there is no file, and nothing under the state dir is touched
        return
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(_db_path()) + suffix).unlink()
        except OSError:
            pass


def rebuild(why: str = "") -> None:
    """Drop the index file and let the thread build it again (a damaged file: the results page says so meanwhile)."""
    print(f"search: the index is rebuilt ({why})", file=sys.stderr, flush=True)
    with _LOCK:
        reset()
        _unlink_db()
        _FAILED.clear()
        _PARTIAL.clear()
    _WAKE.set()


_STANDBY_LOCK = threading.Lock()
_STANDBY_AT = 0.0


def standby_index(board: Any) -> None:
    """Read-only standby: the loop thread is not started, so the results page builds the in-memory index itself, in full, on the first
    search and again when EVERY seconds have passed (the copy job refreshes the store about that often). The items' own text is indexed, never
    their History (a git read of the copy's store): a search there finds items, projects and sessions, not old history lines."""
    global _STANDBY_AT
    if time.time() - _STANDBY_AT < EVERY:
        return
    with _STANDBY_LOCK:
        if time.time() - _STANDBY_AT < EVERY:
            return
        skip: set[str] = set()
        stalls = 0
        while True:
            r = sync(board, max_items=200, skip=skip, history=False)
            if not r["left"]:
                break
            stalls = 0 if r["items"] else stalls + 1
            if stalls >= STALL:
                break
        _STANDBY_AT = time.time()


def build(make_board: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Index everything that is not indexed, in chunks (the lock is let go between them). An item that fails is left out for the rest of the pass, and a pass that indexes
    nothing STALL chunks running ends."""
    board = (make_board or _board)()
    tot: dict[str, Any] = {"items": 0, "pages": 0, "sessions": 0, "left": 0, "failed": []}
    skip: set[str] = set()
    stalls = 0
    while True:
        r = sync(board, max_items=CHUNK, skip=skip)
        for k in ("items", "pages", "sessions"):
            tot[k] += r[k]
        tot["left"] = r["left"]
        tot["failed"] = sorted(set(tot["failed"]) | set(r["failed"]))
        if not r["left"]:
            return tot
        stalls = 0 if r["items"] else stalls + 1
        if stalls >= STALL:
            print(f"search: {r['left']} items left, no progress in {STALL} chunks; the pass ends", file=sys.stderr, flush=True)
            return tot
        time.sleep(PAUSE)


def loop(make_board: Callable[[], Any] | None = None) -> None:
    """The server's background thread, at nice 10: the first build, then a pass after every touched save (a few seconds later) and every EVERY seconds."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)   # this thread, and the git reads it starts, give way to the server's own work
    except (AttributeError, OSError):
        pass
    while True:
        try:
            build(make_board)
        except Exception as e:  # noqa: BLE001  — the search never stops the server
            print(f"search: pass failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            if _corrupt(e):
                rebuild(f"{e.__class__.__name__}: {e}")
        if _WAKE.wait(EVERY):
            _WAKE.clear()                # before the pause, so a save during it asks for the next pass
            time.sleep(DEBOUNCE)         # a burst of saves is one pass


# ----------------------------------------------------------------------------- the query
def terms(q: str) -> list[str]:
    """The words of a query: runs of letters and digits (Hangul syllables included) of at least MIN_CHARS characters, at most MAX_TERMS."""
    return [t for t in re.findall(r"\w+", str(q or "")[:MAX_Q]) if len(t) >= MIN_CHARS][:MAX_TERMS]


def _like(t: str) -> str:
    return "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _fallback_snippet(title: str, body: str, ts: list[str]) -> str:
    text = body or title
    low = text.lower()
    at = min((low.find(t.lower()) for t in ts if t.lower() in low), default=0)
    a = max(0, at - 40)
    s = ("…" if a else "") + text[a:a + 120] + ("…" if a + 120 < len(text) else "")
    for t in sorted(ts, key=len, reverse=True):
        s = re.sub(re.escape(t), lambda m: "\x02" + m.group(0) + "\x03", s, flags=re.I)
    return s


def query(q: str, limit: int = LIMIT) -> dict[str, list[dict[str, Any]]]:
    """The results by kind, best first: [{"key", "sub", "ts", "snip", "more"}]; `snip` holds \\x02 and \\x03 round each match. A query under MIN_CHARS characters, or
    with no word in it, finds nothing. At most `limit` per kind; the first row of a kind that has more carries more=True."""
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in KINDS}
    q = " ".join(str(q or "").split())
    ts_ = terms(q)
    if len(q) < MIN_CHARS or not ts_:
        return out
    with _LOCK:
        con = _con()
        for kind in KINDS:
            if _FTS:
                expr = " ".join(f'"{t}"*' for t in ts_)
                rows = con.execute("select key, sub, ts, snippet(doc, 5, char(2), char(3), '…', 24) from doc where doc match ? and kind=? "
                                   "order by bm25(doc, 0, 0, 0, 0, 5.0, 1.0), ts desc limit ?", (expr, kind, limit + 1)).fetchall()
            else:
                where = " and ".join("(title like ? escape '\\' or body like ? escape '\\')" for _ in ts_)
                args: list[Any] = [x for t in ts_ for x in (_like(t), _like(t))]
                rows = [(k, s, t, _fallback_snippet(ti, bo, ts_)) for k, s, t, ti, bo in con.execute(
                    f"select key, sub, ts, title, body from doc where kind=? and {where} order by ts desc limit ?", (kind, *args, limit + 1)).fetchall()]
            out[kind] = [{"key": k, "sub": s, "ts": t, "snip": sn, "more": i == 0 and len(rows) > limit} for i, (k, s, t, sn) in enumerate(rows[:limit])]
    return out


# ----------------------------------------------------------------------------- the redesigned page's rule: the fleet tool's plain substring match
# `query` above is the original pages' (a prefix of every word). The board at the root searches by the rule of the fleet tool's search: the query is lower-cased and split on white
# space, "quoted text" stays one unit, and every unit must appear, as a plain case-insensitive substring, somewhere in the same entry. There is no word boundary and no prefix rule:
# "redesign" finds "redesigned", and a quoted phrase must appear as written, contiguously.
# `words` reads the query, `find` returns every row that holds all of them (no ranking: the page orders by time), `snippets` the excerpts of the rows the page shows.


def words(q: str) -> list[str]:
    """The units of a query, lower-cased: "quoted text" is one unit, any other run of non-space characters is one; empty units are dropped. At most MAX_TERMS."""
    out = [(a or b).strip().lower() for a, b in re.findall(r'"([^"]*)"|(\S+)', str(q or "")[:MAX_Q])]
    return [w for w in out if w][:MAX_TERMS]


def unit_count(q: str) -> int:
    """How many units a query holds before `words` cuts it at MAX_TERMS."""
    return sum(1 for a, b in re.findall(r'"([^"]*)"|(\S+)', str(q or "")[:MAX_Q]) if (a or b).strip())


def long_enough(ws: list[str]) -> bool:
    """A query needs a unit of at least MIN_CHARS characters to search at all."""
    return any(len(w) >= MIN_CHARS for w in ws)


def word_rx(ws: list[str]) -> re.Pattern:
    """The pattern that finds the units in a text to mark them, case-insensitive, the longest first."""
    return re.compile("|".join(re.escape(w) for w in sorted(set(ws), key=lambda w: -len(w))) or r"(?!)", re.I)


def _holds(title: str, body: str, ws: list[str]) -> bool:
    """Every unit is a substring of the title or of the body, ignoring case."""
    t, b = str(title or "").lower(), str(body or "").lower()
    return all(w in t or w in b for w in ws)


def find(ws: list[str]) -> list[dict[str, Any]]:
    """Every row that holds every unit (see `words`), all kinds, in no order: [{"kind", "key", "sub", "ts", "rowid"}]. `ts` is the index's own (an event's time; 0.0 for the other kinds,
    whose time the page reads from the board). No snippet is made here: `snippets` makes the excerpts of the few rows a page shows."""
    out: list[dict[str, Any]] = []
    if not ws:
        return out
    with _LOCK:
        con = _con()
        for kind in KINDS:
            rows = [(i, k, s, t) for i, k, s, t, ti, bo in con.execute("select rowid, key, sub, ts, title, body from doc where kind=?", (kind,)).fetchall() if _holds(ti, bo, ws)]
            out += [{"kind": kind, "key": k, "sub": s, "ts": float(t or 0.0), "rowid": i} for i, k, s, t in rows]
    return out


def snippets(ws: list[str], rowids: list[int]) -> dict[int, str]:
    """The excerpt of each row (by rowid), with \x02 and \x03 round each match."""
    out: dict[int, str] = {}
    if not ws or not rowids:
        return out
    marks = ",".join("?" * len(rowids))
    rx = word_rx(ws)
    with _LOCK:
        rows = _con().execute(f"select rowid, title, body from doc where rowid in ({marks})", rowids).fetchall()
    for i, ti, bo in rows:
        text = bo if bo and rx.search(bo) else (ti or bo or "")
        m = rx.search(text)
        a = max(0, (m.start() if m else 0) - 40)
        sn = ("…" if a else "") + text[a:a + 120] + ("…" if a + 120 < len(text) else "")
        out[i] = rx.sub(lambda mm: "\x02" + mm.group(0) + "\x03", sn)
    return out


def page_mtime(key: str) -> float:
    """When a project page's file last changed (its time in a result list); 0.0 when the checkout is not here."""
    import brains as _brains
    import pages as _pages
    try:
        b = _brains.for_key(key)
        return ((Path(_pages.BRAIN) if b.default else b.path) / (key + ".md")).stat().st_mtime
    except OSError:
        return 0.0
