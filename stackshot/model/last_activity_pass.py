"""last_activity_pass.py: the data change that fills `metadata.last_activity` for the open items that have no record yet (tools/last_activity_backfill.py runs it).

The record (last_activity.py) is stamped by every save and by the hub's event pass from the day it shipped, so an item nobody has touched since carries none and its On agent row can say nothing about it. This pass
works the record out from what the item's History already holds, with the same kinds of signal and the same newest-wins rule, and stores it. It writes `metadata.last_activity` and nothing else: no clock, no mover, no
needs, no state, no step, no History line (the file is replaced whole under the item lock with a sha256 check, as the stamp, retire and until passes do).

Where the time comes from (`signals`):
  the item's own History, the store's git versions of its file replayed oldest first: each version against the one before it goes through the very function a save goes through (`last_activity.save_signals`, which
  asks `progress.moved`): a step marked done or dropped, a state change, a pull request recorded as merged, and the first version as the item being created. Whether a version was someone's write about the work
  (progress.moved's `real`) is read from the item's own `activity` clock, which a real write moves and the server's bookkeeping leaves: a version whose clock is later than what the version before it read as
  (activity.at) was real. The version's time is its own (`updated` or `confirmed`, else the commit's); a version of the file on disk the store has not committed yet is the last one.
  the hub's logs of pull request events, merge log and event log, tied to the item as the live pass ties them (`server._merge_tied`, the same anchors, bodies and words), each at the time the hub saw it.
The record is the newest of them; of two at the same time the later given wins. Nothing is made up: an item whose History cannot be read, or holds a time ahead of the clock, is refused and listed.

What it leaves alone: an item that already has a record (one that reads; a torn one, or one stamped further ahead of the clock than last_activity.SKEW_S, is no record and is replaced, its old value kept in the undo
entry), a closed item, an item with no History to read.

The refused class (`CLASS_HISTORY`): the History cannot be read (the store is outside git, git did not answer, a version does not parse or is missing) or holds a time ahead of the clock (more than SKEW_S: a clock that
jumped; a time inside it is read as now, as everywhere). Those items are refused, named in the output with the reason, and left as they are: the record is not guessed from a History that cannot be trusted. A hub log
line stamped more than SKEW_S ahead is dropped as the live pass drops it (a torn line), and says nothing against the item.

Pure functions of dicts and the git store, and `one` / `undo_one` / `write_op`, which take `S`, the server module (the item lock, the file helpers and the refusal shape are the migration route's own)."""
from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.model import activity as _activity
from stackshot.model import ids as _ids
from stackshot.model import last_activity as _la

KEY = _la.FIELD                       # the one key the pass writes
ENTRY_KEYS = frozenset({KEY})         # what an undo entry's before and after may name
ENTRY_FIELDS = frozenset(("item", "before", "after", "history", "dropped"))      # an undo entry (history and dropped stay empty: the pass adds no History line; the fields keep the shape of the other passes' files)
CLASS_HISTORY = "unreadable_history"  # the refused class: the item's History cannot be read, or holds a time ahead of the clock
GIT_TIMEOUT_S = 20


def _num(v: Any) -> float:
    """A stored time or clock as a number: 0.0 for anything that is not one. A bool (True is 1.0 to float()), a numeric string ("123" is 123.0), NaN and infinity are no time, as `last_activity.clean` reads them."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    try:
        f = float(v)
    except (OverflowError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def vtime(v: dict[str, Any]) -> float:
    """A stored version's own time: the later of its `updated` and `confirmed` clocks (the History's rule, render.py _vtime), 0.0 when it has neither."""
    return max(_num(v.get("updated")), _num(v.get("confirmed")))


# ---------------------------------------------------------------------------------------------------------------- the History: the store's git versions of an item's file
_LOG: dict[str, Any] = {"key": None, "commits": {}, "problem": ""}      # the store's whole log, read once per head commit: {item file (relative to the store): [(sha, commit time, path in the repository)], oldest first}
_LOG_LOCK = threading.Lock()


def _git(store: Path, *args: str, inp: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(store), *args], input=inp, capture_output=True, timeout=GIT_TIMEOUT_S)


def store_log(store: Path) -> tuple[dict[str, list[tuple[str, int, str]]], str]:
    """The log of the whole store folder, grouped by file: {file relative to the store: [(commit, commit time, path in the repository)] oldest first}, "" or why it cannot be read. One walk of the repository for every item
    (a walk per item costs seconds each on a store of thousands of commits), kept while the head commit is the same. Never `--follow`: its copy detection takes the file of another, similar item for a rename and brings that
    item's History in (the small item files of one store look alike); a file that was renamed has the History it has under its present name."""
    try:
        head = _git(store, "rev-parse", "HEAD")
        if head.returncode:
            return {}, f"the store's git did not answer (exit {head.returncode}: not a repository, or no commit)"
        key = f"{Path(store).resolve()}@{head.stdout.decode().strip()}"
        with _LOG_LOCK:
            if _LOG["key"] == key:
                return _LOG["commits"], _LOG["problem"]
            pre = _git(store, "rev-parse", "--show-prefix")
            lg = _git(store, "log", "--no-renames", "--name-only", "--format=%x01%H%x09%ct", "--", ".")
            if pre.returncode or lg.returncode:
                return {}, f"the store's git did not answer the log (exit {lg.returncode or pre.returncode})"
            prefix = pre.stdout.decode().strip()
            by: dict[str, list[tuple[str, int, str]]] = {}
            for chunk in lg.stdout.decode("utf-8", "replace").split("\x01")[1:]:
                header, _, rest = chunk.partition("\n")
                sha, _, ct = header.partition("\t")
                if not sha:
                    return {}, "a line of the store's git log names no commit"
                for path in (x.strip() for x in rest.splitlines() if x.strip()):
                    by.setdefault(path[len(prefix):] if path.startswith(prefix) else path, []).append((sha, int(ct or 0), path))
            for v in by.values():
                v.reverse()
            _LOG.update(key=key, commits=by, problem="")
            return by, ""
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {}, f"the store's git could not be read ({e.__class__.__name__})"


def git_versions(store: Path, rel: str, log: dict[str, list[tuple[str, int, str]]] | None = None) -> tuple[list[tuple[float, dict[str, Any]]], str]:
    """The versions of the item file `rel` (relative to the store folder) at every commit of the store's git that touched it, oldest first → ([(commit time, version)], "") or ([], why it cannot be read). Strict where the
    History page is forgiving: a store outside git, a git that fails or times out, a version that is missing from the repository or is not a JSON object is a problem, not a version left out, because a missing
    version could hold the newest activity. A file git has never seen gives no commits and no problem (the caller has the file on disk). `log`: the store's log (`store_log`), read here when omitted."""
    try:
        if log is None:
            log, why = store_log(store)
            if why:
                return [], why
        commits = log.get(rel, [])
        out: list[tuple[float, dict[str, Any]]] = []
        if commits:
            buf = _git(store, "cat-file", "--batch", inp="".join(f"{sha}:{path}\n" for sha, _c, path in commits).encode()).stdout
            i = 0
            for sha, ct, _path in commits:
                nl = buf.find(b"\n", i)
                if nl < 0:
                    return [], f"the store's git gave fewer versions than commits (stopped at {sha[:8]})"
                hdr = buf[i:nl].split()
                i = nl + 1
                if len(hdr) < 3 or hdr[1] != b"blob":
                    return [], f"the version at commit {sha[:8]} is missing from the store's git"
                n = int(hdr[2])
                body = buf[i:i + n]
                i += n + 1
                try:
                    v = json.loads(body)
                except (ValueError, RecursionError):
                    return [], f"the version at commit {sha[:8]} does not read as JSON"
                if not isinstance(v, dict):
                    return [], f"the version at commit {sha[:8]} is not an item"
                out.append((float(ct), v))
        return out, ""
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return [], f"the store's git could not be read ({e.__class__.__name__})"


def replay(versions: list[tuple[float, dict[str, Any]]], now: float) -> tuple[list[dict[str, Any]], str]:
    """The signals of an item's History: the versions oldest first, each against the one before (`last_activity.save_signals`, whose `real` is read from the item's `activity` clock) → (the signals, "") or
    ([], why the History cannot be trusted). A version stamped more than SKEW_S ahead of `now` is the refused class (a clock that jumped: its time is not a time that happened); one ahead by less is read as `now`.
    A version with no time of its own takes the time of its commit; one with neither is also a problem."""
    out: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for ct, v in versions:
        t = vtime(v) or ct
        if t <= 0:
            return [], "a version of the item has no time of its own and none from its commit"
        if t > now + _la.SKEW_S:
            return [], f"a version of the item is stamped ahead of the clock (more than {int(_la.SKEW_S // 60)} minutes): its History is not trusted"
        real = prev is None or _num(v.get(_activity.FIELD)) > _activity.at(prev)
        out += _la.save_signals(prev, v, min(t, now), real)
        prev = v
    return out, ""


def tie_signals(rows: list[dict[str, Any]], tied: list[tuple[dict[str, Any], str, dict[str, str]]], now: float) -> dict[str, list[dict[str, Any]]]:
    """The signals of the hub's logged events by item: `tied` is the server's `_merge_tied(rows, now)` (each line with the items it is tied to); a line is one signal of the kind event_log gives it (a merge-log line is a
    merge), at the time the hub saw it; a line stamped more than SKEW_S ahead of `now` is torn and dropped, as the live pass drops it."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row, _key, ids in sorted(tied, key=lambda t: _num(t[0].get("ts"))):
        if _num(row.get("ts")) > now + _la.SKEW_S:
            continue
        cand = _la.pr_candidate(str(row.get("kind") or "merged"), row["n"], row["ts"], now)
        if cand is None:
            continue
        for gid in ids:
            out.setdefault(gid, []).append(cand)
    return out


def newest(signals: list[dict[str, Any]], now: float) -> dict[str, Any] | None:
    """The record the signals give: the newest, the later given of two at the same time; None when there are none."""
    return _la.record(None, signals, now)


# ---------------------------------------------------------------------------------------------------------------- the server's side: the ops `lastact` and `unlastact`
def pr_rows(S: Any, now: float) -> tuple[list[dict[str, Any]], list[str]]:
    """The hub's two logs read whole, each line on its own (a line of the wrong shape is skipped, as the live pass skips it): the merge log's merges and the event log's events, as `_merge_tied` takes them
    → (the rows, the problems): a log that could not be read at all is a problem (a missing log reads as no lines, not a problem)."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for name, source, normal, kind in (("merge log", S._mlog, S._mlog.normal, "merged"), ("event log", S._elog, S._elog.normal, "")):
        try:
            got, _off = source.read(0)
        except Exception as e:  # noqa: BLE001  — a log that cannot be read is reported; the caller decides (the dry run warns, the real pass refuses)
            problems.append(f"the {name} was not read ({e.__class__.__name__}: {str(e)[:120]})")
            continue
        for r in got:
            try:
                n = normal(r)
            except Exception:  # noqa: BLE001  — a line of the wrong shape
                continue
            rows.append({**n, "kind": n.get("kind") or kind})
    return rows, problems


def ties(S: Any, now: float) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """The logged pull request events tied to the open items → (signals by item id, "") or ({}, why the logs or the items could not be read). The server's `_merge_tied`: anchors scoped to the item, a merge's body, the
    item's own words; an item that waits or is held is not on the ladder and gets none. Not swallowed: without the ties an item is filled from its History alone, and a pull request event newer than that would be
    left out of its record, so the dry run warns and the real pass refuses (`write_op`) until they read."""
    try:
        rows, problems = pr_rows(S, now)
        if problems:
            return {}, "; ".join(problems)
        return (tie_signals(rows, S._merge_tied(rows, now), now) if rows else {}), ""
    except Exception as e:  # noqa: BLE001
        return {}, f"the events could not be tied to the items ({e.__class__.__name__}: {str(e)[:120]})"


def has_record(meta_item: dict[str, Any], now: float) -> bool:
    """Does the item carry a record that reads (not torn, not further ahead of `now` than the skew)?"""
    return _la.read(meta_item, now) is not None


def one(S: Any, gid: str, dry: bool = False, tied: dict[str, list[dict[str, Any]]] | None = None, now: float | None = None, git_store: Path | None = None) -> dict[str, Any]:
    """Fill the record of one open item → {"item", "action": set | same | kept | moved | refused | would_set, "why", "class", "before", "after", "history", "dropped", "sha256_before", "kind", "what", "at", "clamped"}
    (before and after = {"last_activity": value}, None = absent). Worked out HERE under the item lock from the file as it stands. `same`: the item already has a record. `kept`: no signal in its History (listed, nothing
    made up). `refused`: closed or unreadable (`class` is CLASS_HISTORY for a History that cannot be read or is ahead of the clock). `moved`: a writer that takes no lock wrote the item between the read and the
    replace; its write stands. `dry`: nothing is written. `tied`: the logged events by item (`ties`; computed when omitted). `git_store`: the folder whose git holds the History (default: the server's store)."""
    shown = S._gh.shown(gid)
    now = time.time() if now is None else now
    store = Path(git_store) if git_store is not None else Path(S._store.STORE)
    blank = {"before": {}, "after": {}, "history": "", "dropped": [], "class": ""}
    try:
        committed: list[tuple[float, dict[str, Any]]] = []
        why = ""
        p0 = S._path(gid)
        if p0.exists():
            try:
                rel = str(p0.resolve().relative_to(Path(S._store.STORE).resolve()))
            except ValueError:
                rel = ""
            committed, why = git_versions(store, rel) if rel else ([], "the item file is outside the store")      # before the lock: git is slow, the History only grows, and the file on disk is read again under the lock
        with S._ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown)
            if refusal is not None:
                return {**refusal, **blank}
            h0 = S._stamp_sha(data)
            if has_record(raw, now):
                return {"item": shown, "action": "same", "why": "it already has a record", **blank, "sha256_before": h0}
            if why:
                return {"item": shown, "action": "refused", "why": f"History unreadable: {why}", **blank, "class": CLASS_HISTORY, "sha256_before": h0}
            from stackshot.core import config as _cfg, legacy_owner as _lo  # noqa: PLC0415
            legacy = _lo.name_from_owner(_cfg.owner())      # an old commit keeps the old needs value for good: it reads as `decision`, as the History page reads it
            versions = [(ct, _lo.history_version(v, legacy)) for ct, v in committed]
            if not versions or versions[-1][1] != _lo.history_version(raw, legacy):
                versions.append((p.stat().st_mtime, _lo.history_version(raw, legacy)))      # the file as it stands: the server commits on a debounce, so the newest write may not be in git yet
            sigs, bad = replay(versions, now)
            if bad:
                return {"item": shown, "action": "refused", "why": f"History unreadable: {bad}", **blank, "class": CLASS_HISTORY, "sha256_before": h0}
            rec = newest(sigs + list((tied or {}).get(gid, ())), now)
            if rec is None:
                return {"item": shown, "action": "kept", "why": "its History holds no activity to record (nothing is made up)", **blank, "sha256_before": h0}
            meta = raw["metadata"]
            out = {"item": shown, "before": {KEY: meta.get(KEY)}, "after": {KEY: rec}, "history": "", "dropped": [], "class": "", "sha256_before": h0, "kind": rec["kind"], "what": rec["what"], "at": rec["at"], "clamped": rec["at"] >= now}      # clamped: the time is "now" (a version a little ahead of the clock reads as now), so it moves with the clock and a plan does not compare it
            if rec["at"] > now + _la.SKEW_S:      # cannot happen (every signal is read no later than `now`); the pass states it, so a future time is never written whatever a later edit does
                return {**out, "action": "refused", "why": "the time found is ahead of the clock: not written", "class": CLASS_HISTORY}
            if dry:
                return {**out, "action": "would_set", "why": "the record would be filled from the History"}
            if not S._stamp_write(p, raw, h0, {KEY: rec}):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run fills it"}
        return {**out, "action": "set", "why": "the record filled from the History"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"last activity pass: {gid} not filled: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one this pass writes ("" = fine)."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass changed"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the last-activity pass writes" if extra else ""


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's record back: `w` = {item, before, after} (the value as it was, None = absent, and as the pass left it). Under the item lock, if the item holds `after` it gets `before` (None drops the key)
    → `set`; if it already holds `before` → `same`; anything else (the record moved on since: a later save or event wrote a newer one) → `kept`, untouched. A closed item is `kept`. Running it again is a no-op."""
    if not isinstance(w, dict):
        return S._migrate_refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _ids._norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return S._migrate_refuse(str(w.get("item") or "?"), str(e))
    shown = S._gh.shown(gid)
    extra = [k for k in w if k not in ENTRY_FIELDS]
    if extra:
        return S._migrate_refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before, after, history and dropped only")
    before, after = w.get("before"), w.get("after")
    for side in (before, after):
        why = entry_problem(side)
        if why:
            return S._migrate_refuse(shown, why)
    if set(before) != set(after):
        return S._migrate_refuse(shown, "before and after name the same keys")
    try:
        with S._ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            now = {KEY: raw["metadata"].get(KEY)}
            out = {"item": shown, "before": before, "after": after, "history": "", "dropped": [], "sha256_before": h0}
            if raw.get("status") != "open":
                return {**out, "action": "kept", "why": f"it was closed since the pass ({raw.get('status')}): left as it is", "now": now}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the record it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds another record than the pass left (a later save or event wrote a newer one): left as it is", "now": now}
            if not S._stamp_write(p, raw, h0, {KEY: before[KEY]}):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the record put back"}
    except Exception as e:  # noqa: BLE001
        print(f"last activity pass: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op lastact {items: [id, …], pass_id?, dry?} | unlastact {items: [{item, before, after}, …], pass_id?} (at most S._MIGRATE_BATCH): the last-activity pass over the open items. No begin and no hold: each item
    is worked out and written under its own lock (`one`). `dry` (lastact only) writes nothing and answers what each item would get. One publish at the end when anything was written. A real `lastact` is refused whole when the hub's logs cannot be read (`ties`); a dry one answers with `ties_problem` set. → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it writes metadata.last_activity and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > S._MIGRATE_BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {S._MIGRATE_BATCH} " + ("item ids" if op == "lastact" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not S._PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "lastact":
        raise ToolError("Refused: dry goes with lastact only")
    results: list[dict[str, Any]] = []
    now = time.time()
    tied, tie_problem = ties(S, now) if op == "lastact" else ({}, "")      # the logs read once for the batch
    if tie_problem and not dry:
        raise ToolError(f"Refused: the hub's logs of pull request events could not be read ({tie_problem}): without them an item is filled from its History alone and a newer event would be left out of its record. Nothing is written; run it again when they read")
    for it in items:
        if op == "unlastact":
            results.append(undo_one(S, it))
            continue
        try:
            gid = _ids._norm_id(str(it or ""))
        except ToolError as e:
            results.append(S._migrate_refuse(str(it or "?"), str(e)))
            continue
        results.append(one(S, gid, dry=dry, tied=tied, now=now))
    if any(r["action"] == "set" for r in results):
        S._publish()
    if pid and not dry:
        S._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results, **({"ties_problem": tie_problem} if tie_problem else {})}
