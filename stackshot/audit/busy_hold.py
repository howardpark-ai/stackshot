"""busy_hold.py: what of the mover's own is running on an item right now, for the refusal of a hold on an item that is being moved (service/gates.py `gate_busy_hold`).

An item its mover is moving is not paused: a hold says "nothing happens here until ...", which is false while a subagent of the mover builds it. The gate asks this module one question,
`live_work(gid, mover, ...)`: is a running subagent of `mover` tied to THIS item? It answers with the words the refusal uses (`your subagent "<description>"`), or "" for nothing.

The proof is the one the hourly audit uses (audit/hourly.py, audit/subagent_tie.py): the subagent's own record on this box, a running one whose description (else its brief) names the item or a pull request
anchored to it, read against every open item the mover has, so a subagent that works on another item of the mover is not tied to this one. Nothing is read from GitHub. A main CI run of an
anchored pull request and the release queue file are NOT read as proof: the server records the events of a pull request when they end (a CI result, a merge: model/last_activity.py), never that a run is in flight, and an event record is no proof
of one running, so a refusal on it would rest on a guess; the release script's own unit is the proof of a running release (below).

A second proof: a release of a pull request tied to THIS item that is running (`live_release`). release.sh runs each release as the user unit stackshot-release-<n>.service and it stays active from its checks through
the merge queue, the merge, the deploy and main's run, so "that unit is active" is "a release of PR n is running" (the unit list web/ui/releasing.py `release_units` reads for the board's Queued for release label; the caller passes it in). The pull request is
tied to the item by three things only (an anchor scoped to the item, an open step's URL, `PR #n` or stored proof, the status line of an open step), never to every item and never by free text (the description, a done step or a mention elsewhere ties nothing); an anchored pull request with no running
unit never counts, and a pull request that none of those names ties nothing (a false negative, never a false refusal). A running unit with a log that has not been written for `RELEASE_FRESH_S`
is a release that is stuck, so it counts for nothing and the mover is never trapped. Nothing is read from GitHub; no log is read while no unit runs.

Unknown is never a refusal: a mover whose subagents cannot be read (`subagent_tie.Unreadable`, a transcript this box does not hold, a sessions index that cannot be read), a subagent whose files cannot be read,
a running subagent that names no item, and any failure of the check itself all answer "". The callers are injected (`subagents`, `anchored`, `items`) so this module reads no server state and a suite can give
fakes. Stdlib plus the repo's modules."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import subagent_tie as _tie
from stackshot.core import config as _cfg
from stackshot.model import steps as _steps

DESC_MAX = 80      # characters of a subagent's description the refusal quotes
RELEASE_WORDS = "your release of PR #"      # what the words of a running release begin with: service/gates.py `BUSY_RELEASE_PREFIX` is the same string (the gate picks the release refusal by it; gates.py imports no audit/ module, so each side holds it and the suite compares them)
RELEASE_FRESH_S = 15 * 60.0      # a release unit counts while its log was written within this long: a release in mode off writes at least every 5 minutes (the longest gap seen was 13), so an older log is a stuck release
LOG_TAIL_BYTES = 8192      # of a release's log at most this much of its end is read for the stage
STAGE_LINES = 4      # the stage is read from the newest of this many timestamped lines of the log that names one


def _quoted(sub: dict[str, Any]) -> str:
    """The subagent as the refusal names it: its description in quotes, one line, clipped; "" when it has none (its brief alone tied it)."""
    d = " ".join(str(sub.get("description") if "description" in sub else sub.get("text") or "").split())
    if not d:
        return "your subagent"
    d = d if len(d) <= DESC_MAX else d[: DESC_MAX - 1].rstrip() + "…"
    return f'your subagent "{d}"'


def live_work(gid: str, mover: str, *, subagents: Callable[[str], list[dict[str, Any]]], items: Callable[[], dict[str, dict[str, Any]]],
              anchored: Callable[[], dict[str, Any]], same: Callable[[Any, Any], bool], shown: Callable[[str], str]) -> str:
    """The words for what is running on item `gid` that `mover` runs ("your subagent "<description>"" ), "" when nothing is or nothing can be told.
    `subagents(mover)` → the mover's running subagents (`service/audit_ticks.py` `_mover_subagents`: raises `subagent_tie.Unreadable` or anything else when they cannot be read); `items()` → every stored item by id;
    `anchored()` → {item id: the pull requests ("owner/repo#n") anchored to it}; `same(a, b)` → whether two names are one session; `shown(id)` → the id as the board writes it."""
    try:
        subs = [s for s in (subagents(mover) or []) if isinstance(s, dict) and not s.get("unreadable")]
        if not subs:
            return ""      # none running (or none that can be read): nothing is claimed, and the items are not even loaded
        all_items = items()
        anch = anchored() or {}
        cands = {gid: (shown(gid), anch.get(gid, ()))}
        for g, it in all_items.items():      # the mover's other open items: a subagent that names one of them (its description first) is at work on that one, not on this
            if g == gid or (it or {}).get("status") != "open":
                continue
            try:
                _it, _meta, _after, mover2 = _ac._item_view(all_items, g)
                if mover2 and same(mover2, mover):
                    cands[g] = (shown(g), anch.get(g, ()))
            except Exception:  # noqa: BLE001  — an item that cannot be read is no other item of the mover's
                continue
        for s in subs:
            if gid in _tie.tied_to(s, cands):
                return _quoted(s)
        return ""
    except Exception:  # noqa: BLE001  — unknown (Unreadable included) is never a refusal
        return ""


_LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:]+Z (.*)$")      # a line release.sh's `say` wrote: its time, then the words (a line of a command's own output has no time)
_STAGES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"in the merge queue \(([A-Z_]+)(?: position (\d+))?\)"), lambda m: m.group(0)),
    (re.compile(r"^enqueued: the merge queue accepted"), lambda m: "enqueued in the merge queue"),
    (re.compile(r"^(?:waiting for the PR's tests|checks on [0-9a-f]{7,40}\b)"), lambda m: "waiting on the PR's checks" if m.group(0).startswith("waiting") else m.group(0)),
    (re.compile(r"^merged\b(?: by the merge queue)?"), lambda m: m.group(0)),
    (re.compile(r"^deploying\b"), lambda m: "deploying"),
    (re.compile(r"^main's run (\d+)\b"), lambda m: m.group(0)),
)


def stage_of(text: str) -> str:
    """The stage of a release one line of its log names, in the log's own words: "in the merge queue (QUEUED position 1)", "waiting on the PR's checks", "checks on <sha>", "merged by the merge queue", "deploying", "main's run <id>"; "" for a line that names none."""
    t = " ".join(str(text or "").split())
    for rx, say in _STAGES:
        m = rx.search(t)
        if m:
            return say(m)
    return ""


def release_log(n: int) -> "tuple[float, str] | None":
    """The log release.sh keeps of the release of PR `n` (<state>/releases/pr-<n>.log) → (when it was last written, the end of it), None when there is none or it cannot be read."""
    try:
        p = Path(_cfg.state("releases", f"pr-{int(n)}.log"))
        with open(p, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
            mtime = p.stat().st_mtime
        return mtime, tail
    except Exception:  # noqa: BLE001  — a log that cannot be read is unknown
        return None


def _stage(tail: str) -> str:
    """The stage in the end of a log: the newest of its last `STAGE_LINES` timestamped lines that names one, "" when none does."""
    stamped = [m.group(1) for m in (_LOG_STAMP.match(ln) for ln in str(tail or "").splitlines()) if m]
    for text in reversed(stamped[-STAGE_LINES:]):
        s = stage_of(text)
        if s:
            return s
    return ""


_PR_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_PR_NUM = re.compile(r"(?<![\w/#.-])(?:PR|pull request)\s*#(\d+)(?!\d)", re.I)      # "PR #12", "pull request #12" (the number written with its #: a bare "PR 12" or "#12" ties nothing)
_OTHER_PR = re.compile(r"[\w.-]+/[\w.-]+\s+(?:PR|pull request)\s*#\d+", re.I)      # "owner/repo PR #12": that repository's, taken out before the words are read


def named_prs(text: str, own: str, canon: Callable[[str], str]) -> set[int]:
    """The numbers of this repository's (`own`, already through `canon`) pull requests a line names: its URL, or `PR #n` / `pull request #n` (a number without a repository is this repository's only). Nothing else ties: not a
    bare `#n`, not `PR n`, not another repository's pull request."""
    t = str(text or "")
    out = {int(n) for r, n in _PR_URL.findall(t) if canon(r) == own}
    out.update(int(n) for n in _PR_NUM.findall(_OTHER_PR.sub(" ", _PR_URL.sub(" ", t))))
    return out


def work_prs(meta: dict[str, Any], own: str, canon: Callable[[str], str]) -> set[int]:
    """The pull requests the status line of an OPEN step names (the open work line: `work=` writes it, steps.tag_of reads it; a line whose state is done belongs to a ticked step and is skipped)."""
    out: set[int] = set()
    for c in _steps.view(meta, keeper=str(meta.get("owner") or "")):
        if c.get("status") != _steps.OPEN:
            continue
        t = _steps.tag_of(c)
        if t and t["state"] != "done":
            out |= named_prs(t["text"], own, canon)
    return out


def tied_releases(gid: str, running: set[int], *, anchored: Callable[[], dict[str, Any]], item: Callable[[str], dict[str, Any]], own_repo: Callable[[], str], canon: Callable[[str], str],
                  step_prs: Callable[[dict[str, Any]], Any]) -> set[int]:
    """The pull requests of this repository, of the ones whose release unit runs (`running`), that are tied to item `gid` by one of three things and nothing else: an anchor scoped to the item; an OPEN step of the item that
    names it (its URL, `PR #n`, or its stored proof: `step_prs`, releasing.step_prs, which reads open steps only); the status line of an open step (`work_prs`). Free text never ties: the description, a done or dropped step and a
    pull request only mentioned somewhere else are not read, so a refusal is never a wrong one (an item that names its pull request nowhere passes: a missed refusal). A pull request of another repository never counts,
    whatever its number: the units are this repository's. Raises what its callers raise."""
    own = canon(own_repo() or "")
    if not own:
        return set()
    it = item(gid) or {}
    meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
    out: set[int] = set()
    for k in (anchored() or {}).get(gid) or ():
        repo, _, n = str(k).rpartition("#")
        if n.isdigit() and canon(repo) == own and int(n) in running:
            out.add(int(n))
    out |= {int(n) for n in (step_prs(meta) or ()) if str(n).isdigit() and int(n) in running}
    out |= work_prs(meta, own, canon) & running
    return out


def _since(age: float) -> str:
    m = int(max(age, 0) // 60)
    return "under a minute ago" if m < 1 else f"{m} min ago"


def live_release(gid: str, *, units: Callable[[], Any], anchored: Callable[[], dict[str, Any]], item: Callable[[str], dict[str, Any]], own_repo: Callable[[], str],
                 canon: Callable[[str], str], step_prs: Callable[[dict[str, Any]], Any], log: Callable[[int], "tuple[float, str] | None"],
                 now: Callable[[], float]) -> str:
    """The words for a release of a pull request tied to item `gid` that is running ("your release of PR #12 is running on it (unit stackshot-release-12.service, its log written 3 min ago, in the merge queue (QUEUED position 1))"),
    "" when none is or none can be told. Running = the unit `stackshot-release-<n>.service` is active (`units()`, web/ui/releasing.py `release_units`: one systemctl call, an empty set on any failure) AND its log was written within
    `RELEASE_FRESH_S` (a unit whose log is older, or missing, is stuck or unknown: the mover is not held for it). The pull request is tied to the item by `tied_releases`; the stage is the log's own words when its last lines
    name one (`stage_of`). Nothing runs on a box with no unit (a failover box has none), and then no log is read at all. With several, the one written to most recently is named. The units carry no owner, so the proof is of the item, not of its mover.
    Every input is passed in, so a suite gives fakes. Unknown (a failure of any input) is "", never a refusal."""
    try:
        running = {int(n) for n in (units() or ())}
        if not running:
            return ""      # no release anywhere: nothing is read, no log and no item
        tied = tied_releases(gid, running, anchored=anchored, item=item, own_repo=own_repo, canon=canon, step_prs=step_prs)
        t_now = now()
        best: "tuple[float, int, str] | None" = None
        for n in sorted(tied):
            try:
                got = log(n)
            except Exception:  # noqa: BLE001  — a log that cannot be read is unknown: another tied release may still be told
                continue
            if not got:
                continue
            age = t_now - float(got[0])
            if age >= RELEASE_FRESH_S:
                continue      # the unit runs but its log has not moved for a quarter of an hour: stuck, never a refusal
            if best is None or age < best[0]:
                best = (age, n, _stage(got[1]))
        if best is None:
            return ""
        age, n, stage = best
        read = f"unit stackshot-release-{n}.service, its log written {_since(age)}" + (f", {stage}" if stage else "")
        return f"{RELEASE_WORDS}{n} is running on it ({read})"
    except Exception:  # noqa: BLE001  — unknown is never a refusal
        return ""
