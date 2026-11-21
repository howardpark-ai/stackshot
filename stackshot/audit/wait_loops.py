"""wait_loops.py: the minute walk over the board's waits for a loop (item A waits on B and B waits on A, or a longer ring), and the notice that breaks it.

A ring of waits stops every item in it: each one is waiting for the next, so none can go first, and only the backstop day of one of them ends it, days later. The write path refuses a new `after` that would close a
ring, but a wait written in a step's words, two writes that cross, or an older link are not seen by that test. The minute set (service/runner.py, `loop_tick`) walks every link of every open item here, once a minute,
and tells the movers of the items in a ring the moment one stands.

  loop_pass(now, items, store, env, dry)    the walk and the notice → {"skipped": why} or {"items", "links", "loops", "fresh", "repeats", "sent", "found"}
  read_raw(store)                           {id: (status, after ids, words ids, last write)} of the store, a file read again only when its size or time changed; the walk reads no item whole, and only a ring reads the store whole
  log_count(since, until)                   how many loops were found in [since, until) (the weekly report's line)

What counts as a link, how the rings are found and which link is the newest is waits/wait_loop.py's (read only, pure). Here is what the server adds:

  * the age of a link. The record keeps no time for an `after`, so the walk keeps one: the first time it saw the link (`<paths.state>/audit/wait-links.json`), or the last write of the item that holds it when that is
    earlier (a link already standing when the walk first sees it was written no later than that write, so a restart or a first run never makes an old link look new). The newest link of a ring is the one to break.
  * what is told. One finding per item in the ring (category `wait-loop`), to its mover, through the filing pass's own delivery (`audit_run.deliver_findings`: the mover, else the project's builder or -main agent, a held note for a front agent). It names the ring, the newest link and what
    ends it. A ring that stands is told once and again only on the audit's re-tell cadence (`[audit] remind_hours`, then the builder, then the -main agent: `split_sent`), never every minute and never because
    its items were written; a ring that changes (an item joins it or leaves it, a link moves to other items) has another fingerprint and is told at once. Nothing is told while a daily run is in progress.
  * the record, `<paths.state>/audit/wait-loops.json`, shaped like the filing pass's (`started`, `finished`, `findings` with their `sent` stamps), rewritten when it changes; a ring found for the first time is also one row of
    `<paths.state>/audit/wait-loops-log.jsonl` (kept 60 days), which the weekly report counts.
  * a cap: at most LOOP_CAP findings are sent in one pass (the rest are sent by the next one, a minute later); a store with nothing that waits on an item reads no item and writes nothing.

The walk only reads the board; the one thing it changes is what it writes in its own record files and the messages it sends. It stands still, as the filing pass does, while the audit is off or in agent mode (the tick checks).
Stdlib plus the repo's modules."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.audit import audit as _audit
from stackshot.audit import audit_run as _ar
from stackshot.core import config as _cfg
from stackshot.waits import wait_loop as _wl
from stackshot.waits import watchers as _watch

CATEGORY = "wait-loop"
RECORD_FILE = "wait-loops.json"          # the pass's record: findings with their send stamps, as filing.json
LINKS_FILE = "wait-links.json"           # {"src>dst": when the walk first saw the link (or an earlier time)}
LOG_FILE = "wait-loops-log.jsonl"        # one row per ring found: {"at", "fp", "items"}
LOG_DAYS = 60                            # the weekly report looks at most two weeks back; the log keeps this long
LOOP_CAP = 20                            # findings sent in one pass at most (the rest the next minute)
_ID = re.compile(r"[a-z]\d+")
_CACHE: dict[str, dict[str, tuple[tuple[int, int], tuple[str, tuple[str, ...], tuple[str, ...], float]]]] = {}      # store folder → {id: ((mtime_ns, size), row)}: a file is read again only when it changed


def _record_path() -> Path:
    return _audit.state_dir() / RECORD_FILE


def _links_path() -> Path:
    return _audit.state_dir() / LINKS_FILE


def _log_path() -> Path:
    return _audit.state_dir() / LOG_FILE


def shown(gid: str) -> str:
    return f"board#{gid[1:]}" if _ID.fullmatch(gid or "") else str(gid)


def by_shown_of(status: dict[str, str]) -> dict[str, str]:
    """{shown id (board#N): item id} of items whose status is given ({id: status}). Items of two letters can share a number (an item of the issue letter and one of another letter): `board#N` is the one the board itself names by
    it, the issue letter's (ghsync.norm), whatever its status (a closed one is a wait that has ended, never a different item); with none of that letter, an open item wins, then the lowest letter. Both the walk and
    the delivery look an id up through this, so the item a finding names is the one the walk found."""
    from stackshot.github import ghsync as _gh  # noqa: PLC0415
    issue = _gh.letter()
    best: dict[str, tuple[bool, bool, str]] = {}
    out: dict[str, str] = {}
    for g, st in status.items():
        k = shown(g)
        rank = (g[:1] != issue, st != "open", g)
        if k not in best or rank < best[k]:
            best[k], out[k] = rank, g
    return out


def row_of(item: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...], float]:
    """(status, after ids, words ids, last write) of one item: what the walk keeps of it."""
    from stackshot.tools import board_report as _br  # noqa: PLC0415
    after, words = _wl.reads(item)
    try:
        wrote = float(_br._last_write(item))
    except Exception:  # noqa: BLE001  (an item with no readable time is of unknown age)
        wrote = 0.0
    return str(item.get("status") or ""), after, words, wrote


def raw_of(items: dict[str, dict[str, Any]]) -> tuple[dict[str, tuple[str, tuple[str, ...], tuple[str, ...], float]], dict[str, str]]:
    """The walk's rows and the shown-id map of items already read (a caller that holds the store, a test)."""
    return {g: row_of(it) for g, it in items.items() if isinstance(it, dict)}, by_shown_of({g: str(it.get("status") or "") if isinstance(it, dict) else "" for g, it in items.items()})


def read_raw(store: Path | None = None) -> tuple[dict[str, tuple[str, tuple[str, ...], tuple[str, ...], float]], dict[str, str]]:
    """The rows of every item file of the store and the shown-id map. A file is parsed again only when its size or modification time is not the one the last walk saw, so a quiet board costs one listing and
    one stat per item; a file that cannot be read or parsed is left out (as `next_report.load_all` leaves it)."""
    folder = store or _cfg.path("paths", "store")
    cache = _CACHE.setdefault(str(folder), {})
    raw: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], float]] = {}
    for p in sorted(folder.glob("*/*.json")):
        gid = p.parent.name + p.stem
        if not _ID.fullmatch(gid):
            continue
        try:
            st = p.stat()
            sig = (st.st_mtime_ns, st.st_size)
            hit = cache.get(gid)
            if hit is not None and hit[0] == sig:
                raw[gid] = hit[1]
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            raw[gid] = row = row_of(d)
            cache[gid] = (sig, row)
    for gone in [g for g in cache if g not in raw]:
        del cache[gone]
    return raw, by_shown_of({g: r[0] for g, r in raw.items()})


def _read_json(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_json(p: Path, d: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def stamps(edges: dict[tuple[str, str], str], raw: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], float]], now: float, seen: dict[str, Any]) -> dict[str, float]:
    """When each link was written, as far as the walk can say: {"src>dst": epoch}. A link already in `seen` keeps its time; a new one gets `now`, or the last write of the item that holds it when that is earlier (and known)."""
    out: dict[str, float] = {}
    for (s, d) in edges:
        k = f"{s}>{d}"
        v = seen.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[k] = float(v)
        else:
            wrote = raw.get(s, ("", (), (), 0.0))[3]
            out[k] = min(now, wrote) if wrote > 0 else now
    return out


def _when(ts: float) -> str:
    d = dt.datetime.fromtimestamp(float(ts), _cfg.tz())
    return f"{_watch.day_words(d.date())} {d:%H:%M}"


def ring_text(lp: "_wl.Loop") -> str:
    """The ring in words: the items in the order they wait, back to the first."""
    ids = [shown(lk.src) for lk in lp.links]
    return " → ".join([*ids, ids[0]])


def newest_text(lp: "_wl.Loop", at: float) -> str:
    lk = lp.newest
    how = "an after link" if lk.form == _wl.AFTER else "a step that waits in words"
    own = f"{shown(lk.src)}'s wait on itself" if lk.src == lk.dst else f"{shown(lk.src)}'s wait on {shown(lk.dst)}"
    return f"{own} ({how}, written {_when(at)})"


def detail_of(lp: "_wl.Loop", at: float) -> str:
    n = len(lp.links)
    who = "one item waits on itself" if n == 1 else f"{n} items each wait on the next"
    return f"loop {lp.fingerprint}: {ring_text(lp)}; newest link: {newest_text(lp, at)}; {who}, so none can go first"


def fix_of(lp: "_wl.Loop", gid: str) -> str:
    lk = lp.newest
    how = "clear its `after`" if lk.form == _wl.AFTER else "reword its step as the action to take now"
    if gid == lk.src:
        return f"end your wait on {shown(lk.dst)} ({how}) and say what you do instead"
    return f"{shown(lk.src)}'s mover ends its wait on {shown(lk.dst)} ({how}); if it is gone, end your own wait in the ring"


def findings_of(found: list["_wl.Loop"], items: dict[str, dict[str, Any]], when: dict[str, float]) -> list[dict[str, Any]]:
    """One finding for each item of each ring, in the shape every audit finding has (id, project, owner, mover, category, detail, fix, source). `items` holds the board whole (the mover is read the way the filing pass reads it)."""
    from stackshot.audit import audit_checks as _ac  # noqa: PLC0415
    from stackshot.tools import board_report as _br  # noqa: PLC0415
    from stackshot.tools import next_report as _nr  # noqa: PLC0415
    _br.install_fallback()
    out: list[dict[str, Any]] = []
    for lp in found:
        at = when.get(f"{lp.newest.src}>{lp.newest.dst}", 0.0)
        for lk in lp.links:
            if lk.src not in items:
                continue
            it, meta, _after_open, mover = _ac._item_view(items, lk.src)
            out.append({"id": _nr.shown(lk.src), "project": str(meta.get("project") or ""), "owner": mover, "mover": mover, "category": CATEGORY,
                        "detail": detail_of(lp, at), "fix": fix_of(lp, lk.src), "source": "code"})
    return out


def log_found(rows: list[dict[str, Any]], now: float) -> None:
    """Append the rings found for the first time (one row each) to the log the weekly report counts; rows older than LOG_DAYS are dropped as it is written. A log that cannot be kept never stops the pass."""
    try:
        p = _log_path()
        keep: list[str] = []
        try:
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    if float(json.loads(ln).get("at") or 0) >= now - LOG_DAYS * 86400:
                        keep.append(ln)
                except (ValueError, AttributeError, TypeError):
                    continue
        except OSError:
            pass
        keep += [json.dumps(r, ensure_ascii=False) for r in rows]
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        print(f"wait loops: log not kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def read_log(since: float = 0.0, until: float | None = None) -> list[dict[str, Any]]:
    """The log's rows with since <= at < until; [] when there is no log (no folder is made to read it)."""
    p = _cfg.state("audit") / LOG_FILE
    out: list[dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
            at = float(r.get("at"))
        except (ValueError, AttributeError, TypeError):
            continue
        if at >= since and (until is None or at < until):
            out.append(r)
    return out


def log_count(since: float, until: float) -> int:
    """How many rings were found in [since, until): the weekly report's count."""
    return len(read_log(since, until))


def loop_pass(*, now: float | None = None, items: dict[str, dict[str, Any]] | None = None, store: Path | None = None, env: Any = None, dry: bool = False) -> dict[str, Any]:
    """Walk the links of every open item for rings and tell the movers of the ones found (the module docstring says how a ring is told and when again). `items` (a caller that has the board) is read as it is,
    else the store is read by `read_raw`. With `dry` nothing is sent or written. → {"skipped": why}, or {"items": open items, "links", "loops": rings now, "fresh": findings sent now, "repeats": findings already told,
    "found": rings new since the last pass, "sent": the messages, "detail": the findings}."""
    from stackshot.tools import next_report as _nr  # noqa: PLC0415
    now = time.time() if now is None else now
    env = env or _ar.Env()
    if not dry and _audit.running(now) is not None:
        return {"skipped": "a daily run is in progress"}
    raw, by_shown = raw_of(items) if items is not None else read_raw(store)
    edges = _wl.links(raw, by_shown)
    n_open = sum(1 for r in raw.values() if r[0] == "open")
    prior = _read_json(_record_path())
    seen_doc = _read_json(_links_path())
    seen = seen_doc.get("seen") if isinstance(seen_doc.get("seen"), dict) else {}
    when = stamps(edges, raw, now, seen)
    if not dry and when != seen:
        try:
            _write_json(_links_path(), {"seen": when})
        except OSError as e:
            print(f"wait loops: link times not kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    found = _wl.loops(edges, lambda s, d: when.get(f"{s}>{d}", 0.0)) if edges else []
    res: dict[str, Any] = {"items": n_open, "links": len(edges), "loops": len(found), "fresh": 0, "repeats": 0, "found": 0, "sent": []}
    if not found and not prior.get("findings"):
        return res
    full = items if items is not None else _nr.load_all(store) if found else {}
    findings = findings_of(found, full, when) if found else []
    full_by_shown = by_shown_of({g: str(it.get("status") or "") if isinstance(it, dict) else "" for g, it in full.items()})
    before = _ar.merged_sent(prior)
    repeats, fresh = _ar.split_sent(findings, full, before, full_by_shown, _ar.tries_before(prior), now, last=lambda _it, _f: 0.0, levels=_ar.levels_before(prior))
    old_fps = {str(f.get("detail") or "").split(":", 1)[0] for f in prior.get("findings") or [] if isinstance(f, dict)}
    res.update(fresh=len(fresh), repeats=len(repeats), found=len([lp for lp in found if f"loop {lp.fingerprint}" not in old_fps]))
    if dry:
        return {**res, "dry": True, "detail": findings}
    held_back = fresh[LOOP_CAP:]
    fresh = fresh[:LOOP_CAP]
    if held_back:
        keep_ids = {id(f) for f in held_back}
        findings = [f for f in findings if id(f) not in keep_ids]
        res.update(fresh=len(fresh), held=len(held_back))
    kept_fps = {str(f.get("detail") or "").split(":", 1)[0] for f in findings}
    new_rings = [lp for lp in found if f"loop {lp.fingerprint}" in kept_fps and f"loop {lp.fingerprint}" not in old_fps]      # a ring is found when its first finding is on the record (a ring the cap held back is found by the pass that records it)
    res["found"] = len(new_rings)
    sent, reached, sending_from = _ar.deliver_findings(env, fresh, f"Wait loop check {_ar._stamp(now)}") if fresh else ([], [], env.clock())
    end = max(env.clock(), now)
    sending_from = max(sending_from, now)
    for f in reached:
        f["sent"], f["sending_from"], f["run_started"] = end, sending_from, now
    _ar.carry_unreached(findings)
    rec = {"started": now, "finished": end, "items_read": n_open, "repeats": len(repeats), "messages": sent,
           "findings": [{k: f[k] for k in ("id", "project", "owner", "category", "mover", "detail", "source", "sent", "sending_from", "run_started", "tries", "lvl") if k in f} for f in findings]}
    quiet = not sent and not held_back and [{k: v for k, v in f.items()} for f in rec["findings"]] == (prior.get("findings") or [])
    try:
        if not quiet:      # a ring that stands and was told leaves its record as it is
            _ar.write_pass_record(_record_path(), rec)
    except OSError as e:
        print(f"wait loops: record not kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if new_rings:
        log_found([{"at": now, "fp": lp.fingerprint, "items": [shown(lk.src) for lk in lp.links]} for lp in new_rings], now)
    return {**res, "sent": sent}
