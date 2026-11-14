"""released.py: a live pull request settles the items built for it.

release.sh calls `released` once main's full run has passed on a merge and recorded it as the last-good commit, and `sweep_released` applies the same rule to every pull request merged into last-good. Which
steps count, exactly:
  - only a release step: one whose words say it releases that PR, "release PR #N", "release #N", "release pull request #N", or "release <the PR's URL>";
  - and only on an item anchored to that PR, or one whose description or steps name the PR's URL ("release PR #N" on any other item may be another repository's #N);
  - never a negated one: "do not release PR #N yet", "don't release #N", "pre-release #N".
A release step is pure only when nothing follows the release phrase, or only a short parenthetical naming nothing to do ("(in its turn)", "(after #7)"); anything else after it ("and verify the pages", ", restart x",
" - check prod", "(needs an ok)", "then ...") is a follow-up (when unsure, it is one): the step is not ticked, nothing closes, and the mover is told once.
A step that merely mentions the PR (investigate, review or verify PR #N, another repository's PR) is never ticked and never closes the item. An item whose only open steps are this PR's release closes (outcome done, by
the server, with no session turn); an item with any other open step (a step after it, or another step naming the PR) gets the release step ticked and its mover one real notice ("PR #N is live; its step is ticked;
the item's other open steps remain"), stamped on the item so a rerun never sends a second; when every other open step is itself a pure release of another PR, the step is ticked and nobody is told. Live means passed:
the merge commit must be an ancestor of the last-good commit and of the checkout's HEAD read at call time, so a rollback or a main run still going settles nothing. Held items, items whose needs name a decision or a
session other than the mover, and closed ones are left alone.

The settle of one item is `proofs.proof_item` (service/proofs.py), the readers of git are service/released_live.py. What it still reaches in server.py comes through `Hooks` in service/checks_hooks.py.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import re
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.service import event_waits as _evwaits
from stackshot.service import proofs as _proofs
from stackshot.service import released_live as _live
from stackshot.service import stall as _stallsvc
from stackshot.service import writes as _writes
from stackshot.service.checks_hooks import hooks as _hooks
from stackshot.service.store import _load
from stackshot.waits import event_waits as _ew


def released_item(gid: str, n: int, key: str, live: str, anchored: set[str], dry: bool, now: float) -> dict[str, Any] | None:
    """The release event of proof_item (release.sh's call and the sweep): pull request `key` (#`n`) is live."""
    return _proofs.proof_item(gid, n, key, live, anchored, dry, now, _sp.PR_RELEASED)


def released(pr: str, sha: str = "", dry: bool = False) -> dict[str, Any]:
    """`client.py released --pr <url> --sha <merge>`: release.sh saw main's full run pass on the merge of `pr` and recorded it as last-good. Refused, before
    anything is written, unless `pr` is a pull request of this repository, `sha` is given and holds its merge, and that merge is in last-good and in HEAD
    (read now). A pull request of a repository [released.repos] lists is live when its merge is an ancestor of that checkout's HEAD (`sha` optional: without it the merge is found in the
    checkout's log). Then every open item built for it is settled (released_item). → {"pr", "sha", "items": [rows]}."""
    key = _hooks().pr_key(pr)
    own = _cfg.canon_repo(_hooks().own_repo())
    repo = key.rsplit("#", 1)[0] if key else ""
    foreign = bool(key) and repo != own and _live.released_foreign(repo) is not None
    if not key or (not foreign and (not own or repo != own)):
        raise ToolError(f"Refused: --pr takes a pull request URL of this repository ({own or 'no origin remote'}) or of a repository in [released.repos] ({_live.released_foreign_why()}): https://github.com/<owner>/<repo>/pull/<n> — got {pr!r}")
    n = int(key.rsplit("#", 1)[1])
    shown = _live.pr_shown(key)
    co = _live.released_foreign(repo) if foreign else None
    if not str(sha or "").strip() and not foreign:
        raise ToolError(f"Refused: PR #{n} has no merge commit given (--sha <merge commit>), so it cannot be read as merged and passed; nothing written")
    if foreign:      # the merge is an ancestor of the checkout's HEAD; a sha the caller did not give is found in the checkout's own log
        head = _live.git_commit("HEAD", co)
        full = _live.git_commit(str(sha).strip(), co) if str(sha or "").strip() else head
        if not full:
            raise ToolError(f"Refused: " + (f"the merge commit {str(sha)[:40]!r} of {shown} is not a commit the checkout of {repo} knows" if str(sha or "").strip() else f"the checkout of {repo} cannot be read") + "; nothing written")
    else:
        full = _live.git_commit(str(sha).strip())
        if not full:
            raise ToolError(f"Refused: the merge commit {str(sha)[:40]!r} of PR #{n} is not a commit this checkout knows; nothing written")
    merged = _live.merged_prs(full, limit=50 if str(sha or "").strip() else 3000, **({"cwd": co} if co else {}))
    if n not in merged:
        raise ToolError(f"Refused: {shown} is not merged: {full[:7]} holds no merge commit for it (\"Merge pull request #{n} from …\"); nothing written")
    msha, mct = merged[n]
    if foreign:
        not_live = _live.foreign_live(repo, msha)
        good = head
    else:
        good, head = _live.released_live_base()
        not_live = _live.released_is_live(msha, good, head)
    if not_live:
        raise ToolError(f"Refused: {shown} is not {'passed and ' if not foreign else ''}live: {not_live}; nothing written")
    now = time.time()
    when = f"merged at {msha[:7]} on {_stallsvc.stall_when(mct)}, " + (f"in the checkout at {head[:7]}" if foreign else f"in the last-good commit {good[:7]}")
    anchors = _live.released_anchors()
    rows = []
    with _writes.ITEM_LOCK:
        for gid, _p in _item_files():
            try:
                r = released_item(gid, n, key, when, anchors.get(gid, set()), dry, now)
            except Exception as e:  # noqa: BLE001  — one item that cannot be read or written never stops the others
                print(f"released: {gid} not settled for PR #{n}: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                continue
            if r:
                rows.append(r)
    if not dry and any(r.get("action") in ("closed", "ticked", "told") for r in rows):
        _hooks().publish()
    if not dry:                    # an event wait on this release (or on its merge) is over: its mover hears it live (once: a session the step notice above told about the item is not told again)
        recent = _proofs.told_recent()
        told = {r["item"]: recent[r["item"]] for r in rows if r.get("told") and r.get("item") in recent}
        _evwaits.evwait_hook(_ew.PR_RELEASED, repo, n, f"{shown} is live: {when}", told=told)
        _evwaits.evwait_hook(_ew.PR_MERGED, repo, n, f"{shown} is merged and live: {when}", told=told)
    return {"pr": pr, "sha": msha, "items": rows}


def sweep_released(dry: bool = False) -> dict[str, Any]:
    """`client.py sweep-released [--dry-run]`: the same rule for every pull request whose merge is in the last-good commit and in HEAD (read now).
    → {"head", "good", "items": [rows, each with "pr"]}; `dry` writes and tells nothing."""
    own = _cfg.canon_repo(_hooks().own_repo())
    if not own:
        raise ToolError("Refused: this checkout has no GitHub origin remote, so no pull request can be read as live")
    good, head = _live.released_live_base()
    merged = {n: v for n, v in _live.merged_prs(good).items() if not _live.released_is_live(v[0], good, head)}
    anchors = _live.released_anchors()
    rx = re.compile(r"\brelease\s+(?:(?:PR|pull request)\s*)?#(\d+)(?!\d)|\brelease\s+(?:(?:PR|pull request)\s+)?(https?://github\.com/\S+)", re.I)
    now = time.time()
    rows = []
    with _writes.ITEM_LOCK:
        for gid, _p in _item_files():
            try:
                it = _load(gid)
                if it.get("status") != "open":
                    continue
                meta = it.get("metadata") or {}
                text = "\n".join(s["text"] for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN)
                named = set()
                for m in rx.finditer(text):
                    if m.group(1):
                        named.add(int(m.group(1)))
                    elif (k := _hooks().pr_key(m.group(2))) and k.rsplit("#", 1)[0] == own:
                        named.add(int(k.rsplit("#", 1)[1]))
                for n in sorted(x for x in named if x in merged):
                    sha, ct = merged[n]
                    live = f"merged at {sha[:7]} on {_stallsvc.stall_when(ct)}, in the last-good commit {good[:7]}"
                    r = released_item(gid, n, f"{own}#{n}", live, anchors.get(gid, set()), dry, now)
                    if r:
                        rows.append({**r, "pr": n})
                        if r.get("action") == "closed":
                            break
            except Exception as e:  # noqa: BLE001
                print(f"sweep-released: {gid} not settled: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if not dry and any(r.get("action") in ("closed", "ticked", "told") for r in rows):
        _hooks().publish()
    if not dry:                    # the catch-up of the event waits on a release: the same reading of the checkout
        try:
            _evwaits.evwait_poll()
        except Exception as e:  # noqa: BLE001
            print(f"sweep-released: event waits not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return {"head": head, "good": good, "items": rows}
