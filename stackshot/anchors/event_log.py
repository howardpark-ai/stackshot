"""event_log.py: the hub's record of the events on pull requests it saw, read by the server's last-activity pass (`server._event_activity_tick`).

The same idea as merge_log.py (a file of the hub's own, one small line per event, nothing for a session to receive, no read of GitHub of its own), for the other events that are visible activity
on a pull request: a CI result (a failure, or passing again after one: what the hub already reports), a comment by a person, a review (a review or a review comment), and a merge. `Hub.emit`, the
funnel every event passes, appends the line. The merge log stays as it is and keeps its own readers; this is a second file, `events.jsonl`, so a server that predates it never reads a line of
another kind as a merge.

One line per kind of event: {"ts": when the hub saw it, "repo": "owner/repo" as the anchor names it, "n": the pull request's number, "kind": ci_failed | ci_passed | comment | review | merged,
"refs": ["board#N", ...] the board ids the pull request's body names, when the event carried them (at most 10)}. The pass reads it from a byte offset it keeps and ties each line to the open items
with merge_tie, as a merge is tied. A burst that joins several types in one event (a merge and a comment) is one line for each kind.

Left out on purpose: a comment or review by a bot (a login ending in "[bot]"; the hub drops its own account's upstream), a CI event on a repository's notifications with no pull request, and any
event the hub cannot name a pull request for. Not here: a commit or push, which the hub does not emit (a later part adds it).

Pure apart from the files: no server import, no clock read (the caller passes `now`)."""
from __future__ import annotations

import json
import os
import reprlib
from pathlib import Path
from typing import Any

from stackshot.anchors import merge_log as _ml
from stackshot.core import config as _cfg

# The hub's event types (core.GH_TYPES) that are activity, and the kind each is filed as.
KIND_OF = {"ci_failed": "ci_failed", "ci_passed": "ci_passed", "comment": "comment", "review": "review", "review_comment": "review", "pr_merged": "merged"}
KINDS = frozenset(KIND_OF.values())
PERSONS_ONLY = frozenset({"comment", "review"})      # the kinds a bot's login is dropped from
MAX_REFS = _ml.MAX_REFS


def path() -> Path:
    return _cfg.state("events.jsonl")


def offset_path() -> Path:
    return _cfg.state("event-activity.json")


def shown(x: Any) -> str:
    """A bounded look at anything for a log line (reprlib limits the depth and each part, so a huge or hostile line never builds a huge string); never raises."""
    try:
        return reprlib.repr(x)[:160]
    except Exception:  # noqa: BLE001
        return f"<{x.__class__.__name__}>"


def kinds_of(etype: Any) -> list[str]:
    """The kinds of activity the hub's event type names (several types are joined with "+"), each once, in the order given."""
    out: list[str] = []
    for t in str(etype or "").split("+"):
        k = KIND_OF.get(t.strip())
        if k and k not in out:
            out.append(k)
    return out


def _bot(login: str) -> bool:
    return login.strip().lower().endswith("[bot]")


def only_bots(who: Any) -> bool:
    """Is every login `who` names a bot's? `who` is one login, or several joined with ", "; empty or "someone" names none, so it is not."""
    names = [w.strip() for w in str(who or "").split(",") if w.strip()]
    return bool(names) and all(_bot(w) for w in names)


def lines_for(anchor: str, url: str, etype: Any, who: Any, body_refs: Any, now: float) -> list[dict[str, Any]]:
    """The lines for an event, [] when it is no activity or names no pull request. A comment or review whose every author is a bot is left out."""
    kinds = kinds_of(etype)
    if not kinds:
        return []
    repo, n = _ml.pull_of(anchor, url)
    if not repo or n <= 0:
        return []
    refs = [str(r) for r in (body_refs or []) if _ml._REF_OK.fullmatch(str(r))][:MAX_REFS]
    return [{"ts": round(float(now), 3), "repo": repo, "n": n, "kind": k, "refs": refs} for k in kinds if not (k in PERSONS_ONLY and only_bots(who))]


def note(anchor: str, url: str, etype: Any, who: Any, body_refs: Any, now: float) -> int:
    """The hub's call for each event: a line for each kind of activity it is. → how many lines were written."""
    rows = lines_for(anchor, url, etype, who, body_refs, now)
    for row in rows:
        _ml.append(row, path())
    return len(rows)


def normal(row: dict[str, Any]) -> dict[str, Any]:
    """A line as the server uses it: merge_log.normal's shape plus "kind". Raises ValueError or TypeError for a line of the wrong shape (a hand edit, a torn write that still parsed, a kind that
    is none of KINDS): the caller skips it, logs it and moves on."""
    out = _ml.normal(row)
    kind = str(row["kind"])
    if kind not in KINDS:
        raise ValueError(f"not an event kind: {kind[:30]!r}")
    return {**out, "kind": kind}


def read(offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """The lines from byte `offset` on and the offset after the last whole line (merge_log.read on this file): a line still being written waits, a torn or unparseable one is skipped, a file
    shorter than `offset` is read from its start, a missing one reads as nothing."""
    return _ml.read(offset, path())


def size() -> int:
    try:
        return path().stat().st_size
    except OSError:
        return 0


def load_offset() -> int | None:
    """Where in the log the server's pass stopped (a byte offset), None for a pass that has never run on this state directory (or a state file that cannot be read)."""
    try:
        with open(offset_path(), encoding="utf-8") as f:
            v = json.load(f).get("offset")
        return int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    except Exception:  # noqa: BLE001  — a missing or torn state file is a pass that starts at the beginning
        return None


def save_offset(offset: int) -> bool:
    """Keep the offset (written beside, then moved over, so a stop in the middle leaves the old one). → whether it was kept; a failure is the caller's to log."""
    try:
        p = offset_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"offset": int(offset)}) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:  # noqa: BLE001
        return False
