"""event_log.py: the hub's record of the events on pull requests it saw, read by the server's last-activity pass (`server._event_activity_tick`).

The same idea as merge_log.py (a file of the hub's own, one small line per event, nothing for a session to receive, no read of GitHub of its own), for the other events that are visible activity
on a pull request: a CI result (a failure, or a new head that passes, after a failure or after a green head: what the hub already reports), a comment by a person, a review (a review or a review comment), a merge, and a commit (a new head commit of the pull request). `Hub.emit`, the
funnel every event passes, appends the line (and `Hub.record`, for a merge the receiver finds out late: an anchor first read on a pull request that merged within the last day). The merge log stays as it is and keeps its own readers; this is a second file, `events.jsonl`, so a server that predates it never reads a line of
another kind as a merge.

One line per kind of event: {"ts": when the hub saw it, "repo": "owner/repo" as the anchor names it, "n": the pull request's number, "kind": ci_failed | ci_passed | comment | review | merged | commit,
"refs": ["board#N", ...] the board ids the pull request's body names (at most 10), kept for a merge only}. The pass reads it from a byte offset it keeps and ties each line to the open items
with merge_tie, as a merge is tied. A burst that joins several types in one event (a merge and a comment) is one line for each kind.

Only a merge ties through the pull request's body (the rule the merge log has always had). A comment, a review or a CI result ties only through an anchor scoped to the item or the item's own
words: in a public repository anyone can open a pull request whose body names an item and comment on it, and that must not stamp the item. So `refs` of any other kind is never written and is
dropped when a line is read.

Size: small rows (about 100 bytes), read from a saved offset, so the cost of a pass is the new lines only; the file only grows and is not pruned. If the offset is lost or the file is replaced, the pass reads it from its start and takes nothing older than 24 hours (`server._EVENT_ACT_FLOOR_H`).

Who counts (the one filter, in `lines_for`): an event that is not a merge is activity only when the source vouches for it. A comment or a review counts when its author's `author_association` (the field the
payload already holds, no read of its own) is OWNER, MEMBER or COLLABORATOR; CONTRIBUTOR, NONE, FIRST_TIMER, FIRST_TIME_CONTRIBUTOR, MANNEQUIN, any other value and a missing one do not. A CI result counts
when its pull request's head branch is in the repository itself (head repository = base repository in the pull request read), not a fork's; a payload that does not say counts as not. The receiver
(`github.py`) sets `Event.vouched`, the kinds of the event it vouches for; no `vouched` is nothing vouched. A merge is not filtered here (it comes from the merge, and keeps the body tie). Why: on a public
repository anyone can comment, and a fork's pull request runs CI with no say from the repository, so neither is the owner's side moving the item.

The line's time is the event's own (`Event.ts`) when it is there and sane, else the hub's (`event_time`): a backlog read after a restart or a stretch of downtime keeps the time it happened at, and
cannot stamp as now. A time older than FLOOR_H or more than AHEAD_S ahead of the hub's clock is dropped (the rule the server's pass has always had for a line: a stale event is not news, a far-future one
is a torn clock); a time that is absent or cannot be read falls back to the hub's.

A commit is not a GitHub notification (a push sends none), so the receiver (`github.py`) finds it in the pull request read it already makes for every anchored pull request: when the head sha differs from the
one it kept for that pull request, it hands the hub an event of type `pr_commit` stamped at the time it saw the new head (no extra request). Only when the hub was away (its last look at that pull request is older than
ten minutes, or unknown) is the commit read once more for its committer date, which `commit_time` clamps to the window; a read that fails stamps the time the hub saw it. Such an event is `record_only`: recorded here and never delivered
to a session (`Hub.emit` returns after the logs). It counts only from a branch of the repository itself (vouched as a CI result is).

Left out on purpose: a comment or review by a bot (a login ending in "[bot]", or an account the payload types as Bot; the hub drops its own account's comments upstream, so a comment made under that account is never seen), a CI event on a repository's notifications with no pull request, and any
event the hub cannot name a pull request for.

Pure apart from the files: no server import, no clock read (the caller passes `now`)."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from stackshot.anchors import merge_log as _ml
from stackshot.core import config as _cfg

# The hub's event types (core.GH_TYPES) that are activity, and the kind each is filed as.
KIND_OF = {"ci_failed": "ci_failed", "ci_passed": "ci_passed", "comment": "comment", "review": "review", "review_comment": "review", "pr_merged": "merged", "pr_commit": "commit"}
KINDS = frozenset(KIND_OF.values())
PERSONS_ONLY = frozenset({"comment", "review"})      # the kinds a bot's login is dropped from
MAX_REFS = _ml.MAX_REFS
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})      # GitHub's author_association values that are the repository's own side; every other value and a missing one is a stranger's
FLOOR_H = 24.0       # an event older than this is not activity (a day of downtime, or a file read again from its start): the record would only fill with old news
AHEAD_S = 3600.0     # …nor one more than this ahead of the clock (a skew of minutes is allowed; the server's pass reads a line that far ahead as a torn one)
COMMIT_FLOOR_S = FLOOR_H * 3600.0 - 180.0     # after downtime a commit is stamped at its committer date, but never older than this: three minutes inside the window above, more than the server pass's minute plus the time a line waits to be read, so a clamped line is not dropped as old news by the pass's own floor


def path() -> Path:
    return _cfg.state("events.jsonl")


def offset_path() -> Path:
    return _cfg.state("event-activity.json")


def shown(x: Any) -> str:
    """A bounded look at anything for a log line: merge_log.shown with this log's longer cap (160)."""
    return _ml.shown(x, 160)


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


def trusted_association(assoc: Any) -> bool:
    """Is a comment's or review's author_association the repository's own side (OWNER, MEMBER, COLLABORATOR)? Anything else, a missing value and a value of another type included, is not."""
    return isinstance(assoc, str) and assoc in TRUSTED_ASSOCIATIONS


def vouched_set(vouched: Any) -> frozenset[str]:
    """The kinds an event's source vouches for: a "+"-joined string ("comment+review") or any collection of kinds; anything else vouches for nothing."""
    if isinstance(vouched, str):
        return frozenset(k.strip() for k in vouched.split("+") if k.strip())
    try:
        return frozenset(str(k) for k in vouched or ())
    except TypeError:
        return frozenset()


def _epoch(ts: Any) -> float | None:
    """An event's own time as epoch seconds: a number, a datetime, or an ISO string (a "Z" or an offset, else the instance's timezone, as the hub writes its own times). None when it cannot be read."""
    try:
        if isinstance(ts, bool) or ts is None:
            return None
        if isinstance(ts, (int, float)):
            v = float(ts)
        else:
            d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
            v = (d if d.tzinfo else d.replace(tzinfo=_cfg.tz())).timestamp()
        return v if math.isfinite(v) and v > 0 else None
    except Exception:  # noqa: BLE001  — a time that cannot be read is an absent one
        return None


def event_time(ts: Any, now: float) -> float | None:
    """When the event happened, for its line: its own time `ts` when it is there and within [now - FLOOR_H, now + AHEAD_S]; the hub's `now` when it is absent or cannot be read; None (drop the
    line) for a readable time outside the window (too old to be news, or too far ahead to be a real clock)."""
    own = _epoch(ts)
    if own is None:
        return float(now)
    return own if now - FLOOR_H * 3600.0 <= own <= now + AHEAD_S else None


def commit_time(date: Any, now: float) -> float | None:
    """When a commit is stamped, after downtime: the committer date the repository holds (`date`, an ISO string) as epoch seconds, never later than `now` (a committer's clock ahead of ours reads as now) and never
    older than COMMIT_FLOOR_S before `now` (inside the window of `event_time`). None only when the date cannot be read: the caller then stamps the time it saw the commit."""
    own = _epoch(date)
    if own is None:
        return None
    return max(min(own, float(now)), float(now) - COMMIT_FLOOR_S)


def lines_for(anchor: str, url: str, etype: Any, who: Any, body_refs: Any, now: float, bot: bool = False, *, vouched: Any = (), ts: Any = None) -> list[dict[str, Any]]:
    """The lines for an event, [] when it is no activity or names no pull request. THE filter on what counts: a comment or review is left out when every author is a bot (`bot`: the payload said the account is
    of type Bot; or every login ends in "[bot]"); a comment, review or CI result is left out unless its kind is in `vouched` (the source vouched for it: an author_association of OWNER, MEMBER or
    COLLABORATOR, a CI result from a branch of the repository itself); a merge is never filtered here. The time is the event's own `ts` (event_time), else `now`; an event whose own time is outside the
    window writes none."""
    kinds = kinds_of(etype)
    if not kinds:
        return []
    repo, n = _ml.pull_of(anchor, url)
    if not repo or n <= 0:
        return []
    at = event_time(ts, now)
    if at is None:
        return []
    ok = vouched_set(vouched)
    refs = [str(r) for r in (body_refs or []) if _ml._REF_OK.fullmatch(str(r))][:MAX_REFS]
    return [{"ts": round(at, 3), "repo": repo, "n": n, "kind": k, "refs": refs if k == "merged" else []} for k in kinds
            if (k == "merged" or k in ok) and not (k in PERSONS_ONLY and (bot or only_bots(who)))]


def note(anchor: str, url: str, etype: Any, who: Any, body_refs: Any, now: float, bot: bool = False, *, vouched: Any = (), ts: Any = None) -> int:
    """The hub's call for each event: a line for each kind of activity it is. → how many lines were written."""
    rows = lines_for(anchor, url, etype, who, body_refs, now, bot, vouched=vouched, ts=ts)
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
    return {**out, "kind": kind, "refs": out["refs"] if kind == "merged" else []}      # only a merge ties through the body


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
