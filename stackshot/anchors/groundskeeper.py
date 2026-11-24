"""groundskeeper.py: the anchors' daily pass. A pass with no model call that runs once a calendar day on the server box, from the audit tick (service/audit_ticks.py, `_anchor_daily_tick`), in three parts:

  A. acts     the sweep's five rules (anchors/anchor_sweep.py `sweep`) over the whole store once, for what the ten-minute tick has not got to (an event the anchors service missed while it was down, a backlog larger than
              one tick's `[anchor_hub] sweep_per_tick`): the cap of that call is DAILY_CAP, a daily figure of its own. Everything else is the sweep's, untouched: its guards (a status or position that is old or missing removes
              nothing, the mass-removal hold of rule 5, the sparing of an anchor an open item waits on), the anchors lock, the equality check under it, the routing-log line with the call that restores each entry and
              `<state>/anchor-removed.jsonl`. When something was removed, `tell` (the audit's builder, `[audit] builder`) gets one line; when nothing was, nobody is told.
  B. reports  never removes: the same anchor on two or more pages; a `[anchor_hub] direct` entry whose session is retired or not in the session registry; an anchor that has had no event for SILENT_DAYS days. One
              file, `<state>/anchor-daily/report-<day>.json` (kept REPORT_DAYS days), and one summary line on a routing log, when there is anything to say; no notice to anyone. What cannot be told (a session registry that
              cannot be read, a status file that is old or missing) is said once in the report as "cannot tell", never guessed from.
  C. bounds   the files that only grow, inside the state folder and nowhere else, never through a symbolic link, and only the names it lists: the held notice texts of the router (`router/held/<id>.json`) older than
              HELD_DAYS days; the anchors service's `unbound.log`, rotated once per ISO week (`unbound.log.<year>-W<week>`) with UNBOUND_KEEP rotated files kept; the reports above past REPORT_DAYS days; and
              `router/shadow.jsonl`, which no code of the server writes (the router's shadow mode is gone; only a test harness makes it), once it is SHADOW_DAYS days old.

The gate: at most one run per calendar day of the instance's timezone. The day is written to `<state>/anchor-daily/last-run` only when all three parts ran without an error; a part that raises is one stderr line, the
others still run, and the next audit tick (ten minutes later) runs the day again (every part is idempotent: a second run removes nothing, finds the same report, and rotates nothing twice in a week). One run at a time:
a lock (core/xlock.py, `anchor-daily`) taken without waiting, so a tick that finds the pass running does nothing. Never raises into the audit tick. A read-only copy does nothing.

Stdlib, anchor_sweep.py, anchors.py, core/, fleet/ (the session registry, the anchors service's state folder) and router/routing.py only: no process is started and no model is called."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
import sys
import time
from typing import Any, Callable

from stackshot.anchors import anchor_sweep as _sw
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import xlock as _xlock
from stackshot.fleet import inbox as _inbox      # FLAGS: the anchors service's state folder, where it keeps unbound.log
from stackshot.fleet import sessions_registry as _sr
from stackshot.router import routing as _routing

DAILY_CAP = 500                      # the most entries part A removes in one run (the ten-minute tick's own cap is `[anchor_hub] sweep_per_tick`, 50): a day's backlog goes at once, a runaway still stops
SILENT_DAYS = 60                     # part B: an anchor with no event for this long (counted from its last event, or from when it was added, or when the service's record began, whichever is latest) is reported
HELD_DAYS = 30                       # part C: a held notice text older than this goes (the routing log reads back no further: routing.KEEP_DAYS)
REPORT_DAYS = 30                     # part C: this many daily reports are kept
SHADOW_DAYS = 30                     # part C: shadow.jsonl, which nothing writes, goes when it is this old
UNBOUND_KEEP = 8                     # part C: rotated copies of unbound.log kept (one a week, so about two months)
DIR = "anchor-daily"                 # <state>/anchor-daily/: the day marker and the reports
MARK = "last-run"                    # the marker: the day (YYYY-MM-DD, instance zone) of the last run that ended without an error
LOCK = "anchor-daily"                # the lock's name (core/xlock.py: <state>/anchor-daily.lock)
UNBOUND = "unbound.log"              # in the anchors service's state folder (fleet/inbox.py FLAGS): an event on an anchor no session is bound to, one line each
LABEL = "anchor daily report"
_NID = re.compile(r"^[0-9a-f]{6}\.json$")                       # router/held/<notice id>.json (routing.record mints six hex digits)
_REPORT = re.compile(r"^report-(\d{4}-\d{2}-\d{2})\.json$")
_ROTATED = re.compile(r"^unbound\.log\.\d{4}-W\d{2}$")


def _say(msg: str) -> None:
    print(f"anchor daily: {msg}", file=sys.stderr, flush=True)


def _day(now: float) -> str:
    """The calendar day of `now` in the instance's timezone."""
    return dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%Y-%m-%d")


def _week(now: float) -> str:
    y, w, _d = dt.datetime.fromtimestamp(now, _cfg.tz()).isocalendar()
    return f"{y}-W{w:02d}"


def _iso(s: Any) -> float | None:
    """A time the anchors service wrote (`2026-11-24 10:00:00` in the instance zone, or with an offset or Z) as epoch seconds, None when it reads as no time."""
    try:
        d = dt.datetime.fromisoformat(str(s or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=_cfg.tz())).timestamp()


# ---------- the day marker ----------
def _dir_path() -> Any:
    return _cfg.state(DIR)


def marker() -> str:
    """The day of the last complete run, "" when there is none or the file cannot be read."""
    try:
        return (_dir_path() / MARK).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_file(path: Any, text: str) -> None:
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _mark(day: str) -> None:
    _write_file(_dir_path() / MARK, day + "\n")


# ---------- part A ----------
def _told(removed: list[dict[str, Any]]) -> str:
    """The one line the builder gets: how many entries went, by which rule, and where the restore lines are."""
    by: dict[str, int] = {}
    for o in removed:
        by[o["rule"]] = by.get(o["rule"], 0) + 1
    n = len(removed)
    return (f"[stackshot] The daily anchor pass removed {n} anchor entr{'y' if n == 1 else 'ies'} that the ten-minute sweep had not yet ("
            + ", ".join(f"{r}: {c}" for r, c in sorted(by.items())) + "). Each is a log-only line on its project's routing log with the call that puts it back, and whole in "
            + f"{_cfg.state(_sw.REMOVED)}. No reply is owed.")


def pass_a(now: float, tell: Callable[[str], Any] | None = None, reader: Any = None, reg: Any = None) -> list[dict[str, Any]]:
    """Part A: the sweep over the whole store, at most DAILY_CAP entries → the entries removed. Its own guards decide what it may remove (see the module's docstring); `reader` and `reg` are for tests. A failed `tell` is a line on stderr: the removal is saved and the next run would find nothing to tell."""
    removed = _sw.sweep(now, reader=reader, reg=reg, limit=DAILY_CAP)
    if removed and tell is not None:
        try:
            tell(_told(removed))
        except Exception as e:  # noqa: BLE001
            _say(f"the builder was not told of {len(removed)} removals: {e.__class__.__name__}: {e}")
    return removed


# ---------- part B ----------
def _direct() -> dict[str, str]:
    """[anchor_hub] direct: anchor id → the session its events go to. A value "none" (the log-only value) names no session and is left out."""
    v = _cfg.get("anchor_hub", "direct") or {}
    if not isinstance(v, dict):
        return {}
    out = {}
    for k, x in v.items():
        k, x = str(k).strip(), str(x).strip()
        if k and x and x.lower() != "none":
            out[_anc.anchor_id(k) or k] = x
    return out


def _roster() -> tuple[Any, str]:
    """(the session registry, "") when every file of it reads and it holds sessions · (None, why) when it cannot be relied on: none configured, a file that does not read (the registry module then stands a last good read in for it), or no session at all."""
    d = _sr._dir()
    if d is None:
        return None, "no session registry is configured"
    try:
        files = _sr._files(d)
    except OSError as e:
        return None, f"the session registry folder cannot be listed ({e.__class__.__name__})"
    if not files:
        return None, "the session registry has no file"
    for p in files:
        if _sr._read_rows(p) is None:
            return None, f"the session registry file {p.parent.name}/{_sr.FILE} cannot be read"
    _sr.reset()
    reg = _sr.load()
    return (reg, "") if reg.rows else (None, "the session registry holds no session")


def _target(value: str, reg: Any) -> str:
    """"" when the session `value` names is registered and not retired (or cannot be judged: a cloud session id, a name two live sessions carry) · "retired" · "not registered"."""
    v = value.strip()
    sid = _sr.resolve(v)
    if sid:
        return "retired" if reg.rows[sid].get("state") == "retired" else ""
    if v.startswith("cse_"):
        return ""                                   # a cloud session is no row of the fleet tool's registry, and says nothing here
    ids = reg.by_name.get(v) or reg.by_transcript.get(v.lower()) or set()
    if not ids:
        return "not registered"
    return "retired" if all(reg.rows[i].get("state") == "retired" for i in ids) else ""      # several rows: retired only when every one is


def pass_b_findings(now: float, store: Any = None, reader: Any = None) -> dict[str, Any]:
    """Part B's reading, no write and no removal → {"duplicates": [{anchor, pages}], "direct": {"checked", "problems": [{anchor, session, why}], "cannot_tell"}, "silent": {"days", "anchors": [{page, url, days}], "cannot_tell"}}."""
    store = _anc.load() if store is None else store
    rd = reader if reader is not None else _sw.Reader.load()
    where: dict[str, list[str]] = {}
    ents: list[tuple[str, dict[str, Any]]] = []
    for page, _i, e in _sw._entries(store):
        ents.append((page, e))
        pages = where.setdefault(_sw.anchor_key(e["url"]), [])
        if page not in pages:
            pages.append(page)
    dups = [{"anchor": k, "pages": sorted(v)} for k, v in sorted(where.items()) if len(v) >= 2]
    direct: dict[str, Any] = {"checked": 0, "problems": [], "cannot_tell": ""}
    want = _direct()
    if want:
        reg, why = _roster()
        if reg is None:
            direct["cannot_tell"] = why
        else:
            direct["checked"] = len(want)
            for a, s in sorted(want.items()):
                bad = _target(s, reg)
                if bad:
                    direct["problems"].append({"anchor": a, "session": s, "why": bad})
    silent: dict[str, Any] = {"days": SILENT_DAYS, "anchors": [], "cannot_tell": ""}
    if not rd.status_fresh(now):
        silent["cannot_tell"] = "the anchors service's status file is old, missing or unreadable"
    else:
        began = _iso(getattr(rd, "history_since", ""))
        for page, e in ents:
            aid = _anc.anchor_id(_anc.split_fragment(e["url"])[0]) or ""
            if not aid:
                continue                                  # a url the anchors service has no reader for gets no event, whatever its age
            last = _iso(rd.reading(aid).status.get("last"))
            since = max(last or 0.0, e["added"] or 0.0, 0.0 if last else (began or 0.0))      # no event on record: the entry's own age, and how long the service's record goes back
            if since and now - since >= SILENT_DAYS * 86400:
                silent["anchors"].append({"page": page, "url": e["url"], "days": int((now - since) // 86400)})
    return {"duplicates": dups, "direct": direct, "silent": silent}


def _summary(f: dict[str, Any], path: Any) -> str:
    """The one routing-log line: counts only, and where the whole report is (the log keeps 300 characters of a line)."""
    bits = []
    if f["duplicates"]:
        bits.append(f"{len(f['duplicates'])} on two or more pages")
    if f["direct"]["problems"]:
        bits.append(f"{len(f['direct']['problems'])} direct entries to a retired or unregistered session")
    if f["silent"]["anchors"]:
        bits.append(f"{len(f['silent']['anchors'])} with no event for {SILENT_DAYS} days")
    for k, what in (("direct", "direct entries"), ("silent", "silent anchors")):
        if f[k]["cannot_tell"]:
            bits.append(f"{what} not checked")
    return "daily anchor report, nothing removed: " + "; ".join(bits) + f". Report: {path}"


def pass_b(now: float, day: str, store: Any = None, reader: Any = None) -> dict[str, Any]:
    """Part B: read, write the day's report file and, when there is something to say and the day has no report yet, one summary line on a routing log (the page of the first finding, else the first page of the store). → the findings."""
    f = pass_b_findings(now, store, reader)
    path = _dir_path() / f"report-{day}.json"
    first = not path.exists()
    _write_file(path, json.dumps({"day": day, "at": now, **f}, ensure_ascii=False, indent=1) + "\n")
    anything = f["duplicates"] or f["direct"]["problems"] or f["silent"]["anchors"] or f["direct"]["cannot_tell"] or f["silent"]["cannot_tell"]
    if anything and first:
        st = _anc.load() if store is None else store
        page = (f["duplicates"][0]["pages"][0] if f["duplicates"] else f["silent"]["anchors"][0]["page"] if f["silent"]["anchors"] else next(iter(sorted(str(k) for k in st)), "") if isinstance(st, dict) else "")
        if page:
            text = _summary(f, path)
            _routing.record_auto(page, "archived", text, kind="anchor", label=LABEL, who=_sw.AUTO, text=text)
        else:
            _say(_summary(f, path))
    return f


# ---------- part C ----------
def _open(parts: tuple[str, ...]) -> int | None:
    """A descriptor for the folder `parts` below the state folder, opened one name at a time without following a link (the state folder itself may be a link the install made: it is the root). None when any
    of them is missing, is not a folder or is a link."""
    try:
        fd = os.open(str(_cfg.state()), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    for p in parts:
        try:
            nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            os.close(fd)
            return None
        os.close(fd)
        fd = nfd
    return fd


def _regular(fd: int, name: str) -> "os.stat_result | None":
    """The stat of `name` in the folder `fd`, itself and not what a link would point to; None when it is not there or is anything but a plain file."""
    try:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _sweep_names(parts: tuple[str, ...], match: Callable[[str], bool], old: Callable[[str, "os.stat_result"], bool]) -> list[str]:
    """Delete the plain files of the folder `parts` whose name `match` accepts and `old` calls old → the names deleted."""
    fd = _open(parts)
    if fd is None:
        return []
    gone = []
    try:
        for name in sorted(os.listdir(fd)):
            if not match(name):
                continue
            st = _regular(fd, name)
            if st is not None and old(name, st):
                os.unlink(name, dir_fd=fd)
                gone.append(name)
    finally:
        os.close(fd)
    return gone


def _unbound_parts() -> tuple[str, ...] | None:
    try:
        rel = os.path.relpath(str(_inbox.FLAGS), str(_cfg.state()))
    except ValueError:
        return None
    parts = tuple(p for p in rel.split(os.sep) if p)
    return None if not parts or ".." in parts else parts       # a folder outside the state folder is none of this pass's


def _rotate_unbound(now: float) -> dict[str, Any]:
    """unbound.log → unbound.log.<ISO week> once a week (when no file of this week's name exists yet and the log holds something), then all but the newest UNBOUND_KEEP rotated files deleted."""
    out = {"rotated": "", "deleted": []}
    parts = _unbound_parts()
    fd = _open(parts) if parts else None
    if fd is None:
        return out
    try:
        st = _regular(fd, UNBOUND)
        to = f"{UNBOUND}.{_week(now)}"
        if st is not None and st.st_size > 0 and not _exists(fd, to):
            os.rename(UNBOUND, to, src_dir_fd=fd, dst_dir_fd=fd)
            out["rotated"] = to
        names = sorted(n for n in os.listdir(fd) if _ROTATED.match(n) and _regular(fd, n) is not None)
        for n in names[:max(0, len(names) - UNBOUND_KEEP)]:
            os.unlink(n, dir_fd=fd)
            out["deleted"].append(n)
    finally:
        os.close(fd)
    return out


def _exists(fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _report_old(name: str, today: dt.date) -> bool:
    """Is the report file `name` REPORT_DAYS days old or more by the day in its name? A name that holds no real date is not old."""
    try:
        return (today - dt.date.fromisoformat(_REPORT.match(name).group(1))).days >= REPORT_DAYS
    except ValueError:
        return False


def pass_c(now: float, day: str) -> dict[str, Any]:
    """Part C: the files kept within bounds (the module's docstring has each) → what was removed or rotated. Each of the four is its own try: one that fails is a line on stderr, and the pass reports the failure at its end."""
    out: dict[str, Any] = {"held": [], "unbound": {"rotated": "", "deleted": []}, "reports": [], "shadow": []}
    errors = []
    today = dt.date.fromisoformat(day)

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001
            errors.append(name)
            _say(f"{name} not bounded: {e.__class__.__name__}: {e}")

    step("held", lambda: _sweep_names(("router", "held"), lambda n: bool(_NID.match(n)), lambda n, st: now - st.st_mtime >= HELD_DAYS * 86400))
    step("unbound", lambda: _rotate_unbound(now))
    step("reports", lambda: _sweep_names((DIR,), lambda n: bool(_REPORT.match(n)),
                                         lambda n, st: _report_old(n, today)))
    step("shadow", lambda: _sweep_names(("router",), lambda n: n == "shadow.jsonl", lambda n, st: now - st.st_mtime >= SHADOW_DAYS * 86400))
    if errors:
        raise RuntimeError("not bounded: " + ", ".join(errors))
    return out


# ---------- the run ----------
def run(now: float | None = None, tell: Callable[[str], Any] | None = None, reader: Any = None, reg: Any = None) -> dict[str, Any] | None:
    """The day's pass, once → {"day", "removed": [..], "report": {..}, "bounded": {..}, "failed": [parts that raised]} · None when it did nothing (a read-only copy, a run in progress, today already done).
    The day is marked only when no part failed. Never raises."""
    try:
        if _ro.is_read_only():
            return None
        now = time.time() if now is None else float(now)
        day = _day(now)
        lock = _xlock.XLock(LOCK)
        if not lock.acquire(blocking=False):
            return None
        try:
            if marker() == day:
                return None
            out: dict[str, Any] = {"day": day, "removed": [], "report": {}, "bounded": {}, "failed": []}
            for key, name, fn in (("removed", "a", lambda: pass_a(now, tell, reader, reg)), ("report", "b", lambda: pass_b(now, day, None, reader)), ("bounded", "c", lambda: pass_c(now, day))):
                try:
                    out[key] = fn()
                except Exception as e:  # noqa: BLE001  — one part never stops the others
                    out["failed"].append(name)
                    _say(f"part {name} skipped: {e.__class__.__name__}: {e}")
            if not out["failed"]:
                try:
                    _mark(day)
                except Exception as e:  # noqa: BLE001
                    out["failed"].append("mark")
                    _say(f"the day was not marked, the next tick runs it again: {e.__class__.__name__}: {e}")
            return out
        finally:
            lock.release()
    except Exception as e:  # noqa: BLE001
        _say(f"not run: {e.__class__.__name__}: {e}")
        return None
