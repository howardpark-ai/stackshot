"""merge_progress.py: a merged pull request is progress for the item it is tied to.

An item whose pull request merged has moved, whether or not the merge settles a step: a pull request that is one of several steps never wrote the "merged <ref>" entry of `released_told` (that is the settle path's,
`proofs.proof_item`, and it also tells the mover), so the last-activity record (model/last_activity.py) saw no merge for it. The earliest reliable signal is the hub's merge log (anchors/merge_log.py): `Hub.emit` appends
one line for every merge it sees, from the read it makes anyway, with the board ids the pull request's body names; nothing here reads GitHub. A merge is tied to an item (model/merge_tie.py) by an anchor scoped to it
(never a project-wide one), by its body naming the item, or by the item's own words naming the pull request. The pass stores the key in `metadata.merged_seen` through `writes.save` (activity kind `event`), so
`progress.merges` sees a merge newly recorded and the last-activity record takes it.

`_merge_progress_tick` is the minute pass (a wake-hook entry); `_merge_tied` is the tie the last-activity pass and the event pass share (`_TiedRows` carries its `problem`).

A service module: it reads the store and writes an item only through `writes.save` under the item lock, and it reaches nothing in the surface. A suite that replaces one of these functions sets it on this module (and
`time` here, since this module reads its own clock).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.anchors import merge_log as _mlog
from stackshot.core import config as _cfg
from stackshot.core.instance import NAME
from stackshot.core.store import _item_files
from stackshot.model import activity as _activity
from stackshot.model import holders as _holders
from stackshot.model import merge_tie as _mtie
from stackshot.model import progress as _progress
from stackshot.model import steps as _steps
from stackshot.model.ids import _norm_id
from stackshot.service import item_read as _item_read
from stackshot.service import released_live as _rlive
from stackshot.service import store as _svcstore
from stackshot.service import writes as _writes
from stackshot.waits import stall as _stall
from stackshot.waits import watchers as _watch


_MERGE_PROG_KEEP = 20       # keys kept in an item's merged_seen (as released_told keeps its last 20)
_MERGE_BACKLOG_S = 6 * 3600.0      # a merge older than this is not recorded: the backlog of a day of downtime, or a shorter file read again from its start


def _merge_progress_state_path() -> Path:
    return _cfg.state("merge-progress.json")


def _merge_progress_offset() -> int | None:
    """Where in the hub's merge log the pass stopped (a byte offset), None for a pass that has never run on this state directory."""
    try:
        v = json.load(open(_merge_progress_state_path(), encoding="utf-8")).get("offset")
        return int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    except Exception:  # noqa: BLE001
        return None


def _merge_progress_save(offset: int) -> None:
    try:
        p = _merge_progress_state_path(); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps({"offset": int(offset)}) + "\n", encoding="utf-8"); os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        print(f"merge progress: offset not saved: {e}", file=sys.stderr, flush=True)


def _anchor_repo(url: str) -> str:
    """The GitHub repository ("owner/repo", through [github.moved]) an anchor URL is in (a pull request, a repository's releases or notifications), "" for any other anchor."""
    a = str(_anc.anchor_id(url) or "")
    return _cfg.canon_repo(a[7:].split("#", 1)[0].split("@", 1)[0]) if a.startswith("github:") else ""


def _merge_rows(rows: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    """The lines worth acting on: each parsed on its own (merge_log.normal), so a line of the wrong shape (a hand edit, a torn write that still parsed) is logged and skipped and the offset moves on
    past it; and only those younger than `_MERGE_BACKLOG_S` (six hours), on every pass. A merge from the backlog of a day of downtime would be recorded at the time of the save, which would move
    the item's clocks for work that happened long ago: it is no news now, so it is not recorded."""
    out: list[dict[str, Any]] = []
    floor = now - _MERGE_BACKLOG_S
    for row in rows:
        try:
            r = _mlog.normal(row)
        except Exception as e:  # noqa: BLE001
            print(f"merge progress: line skipped ({e.__class__.__name__}: {str(e)[:80]}): {_mlog.shown(row)}", file=sys.stderr, flush=True)      # the class, the first of the message and a bounded look, never str(row): a line can nest deeper than str() can follow
            continue
        if r["ts"] >= floor:
            out.append(r)
    return out


class _TiedRows(list):
    """`_merge_tied`'s answer: the list of (line, key, tied), plus `problem`, why the anchors could not be read ("" = they were). The live passes log it and carry on with the other ties; the last-activity backfill
    (`last_activity_pass.ties`) reports it as a ties problem, so its apply refuses instead of filling an item without the ties its anchors would give."""
    problem: str = ""


def _merge_tied(rows: list[dict[str, Any]], now: float) -> list[tuple[dict[str, Any], str, dict[str, str]]]:
    """For each merge line the open items on the stall ladder it is tied to: [(line, "owner/repo#n", {item id: why})]. The items are read once for all lines; one that cannot be read is logged and left out.
    The anchors that cannot be read are logged and the other ties (the pull request's body, the item's own words) are still made; the answer's `problem` says so (`_TiedRows`)."""
    scoped = _rlive.released_anchors()
    texts: dict[str, str] = {}
    projects: dict[str, str] = {}
    for gid, _p in _item_files():
        try:
            it = _svcstore._load(gid)
            if it.get("status") != "open":
                continue
            meta = it.get("metadata") or {}
            cl = _steps.view(meta, keeper=str(meta.get("owner") or ""))
            if _stall.not_due(it, now, lambda i_: _item_read._after_open(i_.get("metadata") or {})) or _holders._is_held(it):
                continue      # the board shows it waiting, held or in the owner's lane: not on the stall ladder, and a stray mention must not reset its silence clock
            # the item's own words: its description, its steps, the status tag of each open step (a tag is where a session writes "PR 136 released; PR 137 in review", often before the step's text says it) and the lines of `next`
            tags = [t["text"] for t in (_steps.tag_of(c) for c in cl if c.get("status") == _steps.OPEN) if t]      # an open step's tag only: a done or dropped step keeps its tag, and a stale "PR 137 released" must not tie a later merge
            texts[gid] = "\n".join([str(it.get("description") or ""), *(c["text"] for c in cl), *tags, str(meta.get("next") or "")])
            projects[gid] = str(meta.get("project") or "")
        except Exception as e:  # noqa: BLE001
            print(f"merge progress: {gid} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    problem = ""
    try:
        pages = _mtie.repo_pages(_anc.load(), _anchor_repo)
    except Exception as e:  # noqa: BLE001
        pages = {}
        problem = f"the anchors could not be read ({e.__class__.__name__}: {str(e)[:120]})"
        print(f"merge progress: anchors not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    out = _TiedRows()
    out.problem = problem
    for row in rows:
        key = f"{_cfg.canon_repo(str(row['repo']))}#{int(row['n'])}"
        body: list[str] = []
        for ref in row.get("refs") or []:
            try:
                g = _norm_id(str(ref))
            except Exception:      # an id that names no item (another machine's temporary id, a word that only looks like an id)
                continue
            if g in texts and g not in body:
                body.append(g)
        tied = _mtie.tied(key, body, {g: ks for g, ks in scoped.items() if g in texts}, texts, projects, pages, _cfg.canon_repo)
        out.append((row, key, tied))
    return out


def _merge_progress_tick(now: float | None = None) -> list[str]:
    """The pass: read the hub's merge log from where it stopped, and for each open item a merged pull request is tied to (merge_tie.tied) add the pull request to the item's `merged_seen` and save it,
    which the last-activity record takes (progress.merges). On every pass a line that is malformed is logged and skipped, and one older than six hours is skipped (`_merge_rows`: the
    backlog of a day of downtime, or a shorter file read again from its start, would record merges long past), a pull request an item holds already is not saved again, and an item that is closed or that the board shows waiting
    or held is left alone. An item that cannot be read or saved is logged and skipped: the others are saved and the offset is stored, so one bad item does not abort the pass every minute. → the ids saved."""
    if _watch.holding():
        return []
    now = time.time() if now is None else now
    off = _merge_progress_offset()
    rows, new = _mlog.read(off or 0)      # an offset past the end of the file (replaced or shrunk) reads from its start
    rows = _merge_rows(rows, now)
    if not rows:
        if new != off:
            _merge_progress_save(new)
        return []
    saved: list[str] = []
    try:
        ties = _merge_tied(rows, now)
    except Exception as e:  # noqa: BLE001  — a read that failed as a whole: the offset stays where it was, and the next pass reads the lines again
        print(f"merge progress: items not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    for row, key, tied in ties:
        for gid, how in tied.items():
            try:
                with _writes.ITEM_LOCK:
                    it = _svcstore._load(gid)
                    meta = it.get("metadata")
                    if it.get("status") != "open" or not isinstance(meta, dict):
                        continue
                    seen = [str(x) for x in (meta.get(_progress.SEEN) or []) if str(x)]
                    if key in seen:
                        continue
                    meta[_progress.SEEN] = [*seen, key][-_MERGE_PROG_KEEP:]
                    what = f"{_rlive.pr_shown(key)} merged, and {_mtie.HOW[how]}: that is progress on the item"
                    _stall.note(meta, now, what)      # the History line
                    it["metadata"] = meta
                    it["updated"] = now      # as the event save of the settle path does (proofs.proof_item)
                    _writes.save(gid, it, note=f"{NAME}: {what}", activity=_activity.EVENT)
                    if gid not in saved:
                        saved.append(gid)
                    print(f"merge progress: {gid} moved by {key} ({how})", file=sys.stderr, flush=True)
            except Exception as e:  # noqa: BLE001  — one item that cannot be read or saved never stops the others
                print(f"merge progress: {gid} not saved for {key}: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    _merge_progress_save(new)
    return saved
