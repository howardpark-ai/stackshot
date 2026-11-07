"""pr_state.py: the one reader of a pull request's state for the server (merged, closed without a merge, open, or unreadable).

Three parts of the server ask GitHub whether a pull request is merged: the done check (`pr_merged <ref>`), the step proof (a step that
waits on a merge) and the event wait (`pr_merged` / `pr_released` waits). Each kept its own record of the answer (checks.json, step-proof.json,
and a dict in memory), so a pull request that all three named was read three times in one window. `merged()` is the one reader behind
`server._pr_merged`: every call, whichever part makes it, looks first in ONE process-wide record store and reads GitHub only when the answer
there is older than the pace ([check] github_minutes). The caller's own dict (`gh_st`) is still filled with the record, because that dict is what
the caller persists (checks.json, step-proof.json) and what `server._check_dead` reads; it is a view of the shared record, never a second read.

What stays as it was, for every caller: the return value `(merged, error)`; the record's fields (`next`, `back`, `err`, `merged`, `seen`, `dead`);
the pace (one GET per PR every github_minutes); the backoff (doubling from the pace, at most `backoff_max`, or what GitHub asked for) when GitHub is
down or the budget is spent; a refusal (404, a token that cannot read the repo) tried again at the normal pace; a closed-unmerged PR carrying
`dead`. The conditional request (ETag, a 304 is free and not counted) is the GitHub client's own cache (ghsync.GitHub, `etag=True`), one per
client and process; this module asks for it on every read. The ledger tag of the read (ghbudget: done_check, step_proof, event_wait) is the
caller's, set around the call as before (`with ghbudget.tag(...)`): the client reads the thread's tag.

The shared store is in memory: a restart starts it empty, and the first caller then falls back on its own persisted record (the fresher of the two
wins), so a restart reads no more than it did. Two threads asking for the same PR at once (a request thread and the runner) make one read: the
second waits for the first and takes its answer.

Not in here: release.sh, anchorhub/github.py, the receivers, ghsync's mirror and the comment reader (they are separate processes or readers, and
their own pull request reads stay as they are).

    tests/run-suite pr_state        → exit 0 / 1"""
from __future__ import annotations

import threading
from typing import Any, Callable

import ghsync as _gh

_SHARED: dict[str, dict[str, Any]] = {}      # canonical "owner/repo#n" → its record: the one cache of the process
_LOCKS: dict[str, threading.Lock] = {}       # one lock per ref: the reads of one PR take turns, the reads of two PRs do not; never pruned (a lock is tiny, and dropping one a thread holds or is about to take would let a second read of the same PR run at once)
_GUARD = threading.Lock()                    # the two dicts above
_KEEP = 2000                                 # records kept at most; past it the ones whose next read is furthest back go


def reset() -> None:
    """Forget every shared record (a restart does; the scenarios do between sections)."""
    with _GUARD:
        _SHARED.clear()


def _lock(ref: str) -> threading.Lock:
    with _GUARD:
        lk = _LOCKS.get(ref)
        if lk is None:
            lk = _LOCKS[ref] = threading.Lock()
        return lk


def _rec(d: Any) -> dict[str, Any]:
    return d if isinstance(d, dict) else {}


def _nxt(rec: dict[str, Any]) -> float:
    try:
        return float(rec.get("next") or 0)
    except (TypeError, ValueError):
        return 0.0


def _best(ref: str, gh_st: dict[str, Any]) -> dict[str, Any]:
    """The newer of the caller's own record and the shared one (the later `next` is the later read, or the later backoff); the shared one on a tie. "Newer" compares the stored `next`, so after a restart a persisted backoff record in the caller's dict can outrank a newer shared success."""
    own = _rec(gh_st.get(ref))
    with _GUARD:
        shared = _rec(_SHARED.get(ref))
    return own if _nxt(own) > _nxt(shared) else shared or own


def fresh(ref: str, gh_st: dict[str, Any], now: float) -> bool:
    """True while a read of `ref` costs nothing now: a record, the caller's or the shared one, is still inside its pace."""
    return _nxt(_best(ref, gh_st)) > now


def known(ref: str) -> dict[str, Any]:
    """A copy of the shared record of `ref`, {} when none."""
    with _GUARD:
        return dict(_rec(_SHARED.get(ref)))


def _store(ref: str, rec: dict[str, Any]) -> None:
    with _GUARD:
        _SHARED[ref] = dict(rec)
        if len(_SHARED) > _KEEP:
            for k in sorted(_SHARED, key=lambda k: _nxt(_SHARED[k]))[: len(_SHARED) - _KEEP]:
                if k != ref:
                    _SHARED.pop(k, None)


def merged(ref: str, now: float, gh_st: dict[str, Any], client_for: Callable[[str], Any], every: float, backoff_max: float = 3600.0) -> tuple[bool, str]:
    """→ (the PR `ref` ("owner/repo#n", already in its current name) is merged, the error). One GET per PR every `every` seconds across all callers: the answer
    is kept in the shared store and in `gh_st` (the caller's own dict). GitHub down or rate-limited backs off (doubling, at most `backoff_max`, or what GitHub
    asked for); a refusal is an error tried again at the normal pace. `client_for(repo)` is the ghsync client that reads that repo's pull requests. A closed PR
    that was not merged carries `dead` in its record, which `server._check_dead` and the event wait read."""
    with _lock(ref):
        rec = _best(ref, gh_st)
        if rec and _nxt(rec) > now:
            if gh_st.get(ref) is not rec:
                gh_st[ref] = dict(rec)       # the shared answer, handed to the caller's dict (it persists it and reads `dead` from it)
            return bool(rec.get("merged")), str(rec.get("err") or "")
        repo, _, n = ref.partition("#")
        try:
            c = client_for(repo)       # the issues repo's client with [github] issues_repo_id set reads /repositories/<id>/pulls/<n>; any other repo by its name
            r = c.request("GET", c.repo_path(f"/pulls/{int(n)}") if getattr(c, "repo_id", 0) else f"/repos/{repo}/pulls/{int(n)}", etag=True)   # a PR nobody touched answers 304, which is not counted
        except _gh.GitHubDown as e:
            back = min(max(2.0 * float(rec.get("back") or 0), every, 60.0), backoff_max)
            rec = {"next": now + max(back, float(getattr(e, "retry_after", 0) or 0)), "back": back, "err": str(e) if isinstance(e, _gh.GitHubBudget) else f"GitHub did not answer ({e})", "merged": False}
        except _gh.GitHubError as e:
            rec = {"next": now + every, "back": 0.0, "err": f"GitHub refused the read ({e})", "merged": False}
        else:
            ok = isinstance(r, dict) and bool(r.get("merged") or r.get("merged_at"))
            rec = {"next": now + every, "back": 0.0, "err": "", "merged": ok, "seen": now}
            if isinstance(r, dict) and r.get("state") == "closed" and not ok:     # closed unmerged: the check can never pass (the owner's one rule)
                rec["dead"] = "its pull request was closed without being merged"
        gh_st[ref] = rec
        _store(ref, rec)
        return bool(rec["merged"]), str(rec["err"])
