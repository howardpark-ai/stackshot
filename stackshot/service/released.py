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

This module also holds what release.sh's report is read with: the pull-request key of a URL (`_pr_key`, `_pr_items`, `_PR_URL`), this checkout's own repository (`_own_repo`, the list `_OWN_REPO` a suite seeds), and the
green report that goes log-only (`_release_green`, `_release_green_ok`, `AUTO_RULER`, `_RELEASE_SENDER`).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.github import ghsync as _gh
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _norm_id
from stackshot.router import routing as _routing
from stackshot.service import event_waits as _evwaits
from stackshot.service import messaging as _messaging
from stackshot.service import proofs as _proofs
from stackshot.service import released_live as _live
from stackshot.service import stall as _stallsvc
from stackshot.service import store as _svcstore
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


# ----------------------------------------------------------------------------- pull-request keys
_PR_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)


def _pr_key(url: str) -> str:
    """A GitHub pull request URL → "owner/repo#n" (lower-cased; /files, a query or a fragment after it ignored), or "". The repo goes through
    [github.moved] (config.canon_repo), so an old-owner URL and a new-owner URL of one pull request give the same key."""
    m = _PR_URL.search(url or "")
    return f"{_cfg.canon_repo(m.group(1))}#{m.group(2)}" if m else ""


def _pr_items(refs: list[str]) -> dict[str, list[str]]:
    """The open items an anchor is scoped to, for each PR URL in `refs` → {the anchor's URL: [item ids]}. A project-wide
    anchor names no item and does not count."""
    keys = {_pr_key(r) for r in refs if _pr_key(r)}
    out: dict[str, list[str]] = {}
    for entries in _anc.load().values():
        for e in entries:
            k = _pr_key(str(e.get("url") or ""))
            if not k or not e.get("items") or k not in keys:
                continue
            for g in e["items"]:
                try:
                    gid = _norm_id(g)
                    if _svcstore._load(gid).get("status") == "open" and gid not in out.setdefault(e["url"], []):
                        out[e["url"]].append(gid)
                except ToolError:
                    continue
    return {u: gs for u, gs in out.items() if gs}


# ----------------------------------------------------------------------------- automatic rulings
# The turn rule's second build: a green release.sh result is routine, so it is
# no longer delivered. The server logs it (a routing line marked log_only, no recipient), rules it `merged` itself as
# AUTO_RULER, and leaves a comment on the open items anchored to the PR. It stays on the project's routing page: the daily digest to the
# keeper is gone with the old routing. A red result (failed, rolled back) is delivered as before, and a
# green one that cannot take the log-only path is delivered too.
# The third build: anchor-hub logs the fleet's own routine PR events the same
# way ([pilot] own_repos; anchorhub/core.py emit), ruled `merged` by AUTO_RULER. A held item that waits on the anchor is still
# released by such a line (_wakes.anchor_pass), as a ruling would release it.
AUTO_RULER = _routing.AUTO_RULER   # "stackshot (auto)", shared with anchor-hub, which rules the fleet's own routine PR events (the third build)

_RELEASE_SENDER = "release"     # release.sh's own label (its tell()); no other sender's message takes the log-only path
_OWN_REPO: list[str] = []


def _own_repo() -> str:
    """This checkout's GitHub repository, "owner/repo" lower-cased, from its origin remote as release.sh reads it (read once
    per process); "" when there is none or git cannot say, and then no release result goes log-only."""
    if not _OWN_REPO:
        try:
            url = subprocess.run(["git", "-C", str(_live.HERE), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            url = ""
        m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
        _OWN_REPO.append(m.group(1).lower() if m else "")
    return _OWN_REPO[0]


def _release_green_ok(sender: str, pr: str) -> bool:
    """Only release.sh's own green report goes log-only: the sender is exactly
    `release` and `pr` is a pull request of this repository. A green flag from any other sender, or with no PR, a garbage one
    or another repository's, is delivered as before, so no script can have its message silently logged."""
    k = _pr_key(pr)
    own = _cfg.canon_repo(_own_repo())     # k is canonical already (_pr_key): both sides through [github.moved], so origin old / PR new match, and the reverse
    return sender == _RELEASE_SENDER and bool(k) and bool(own) and k.rsplit("#", 1)[0] == own


def _release_green(to: str, text: str, sender: str, machine: str, pr: str) -> str | None:
    """A green release.sh result (POST /client/message with release=green): log-only. The line goes into the project's
    routing log with no recipient and log_only, is ruled `merged` by AUTO_RULER at once, and the open items anchored to the
    PR (_pr_items) get the server's comment; it stays on the project's routing page. Nothing is delivered and no page is
    owed. An item waiting on the PR is untouched here: its `pr_merged` check closes it on the check pass, and that close
    releases the items `after` it, as any close does. → the reply, or None when this result cannot go log-only (not a page of the
    registry, not release.sh's own report of a PR of this repo: _release_green_ok), which the caller then delivers as before."""
    if not _release_green_ok(sender, pr):
        return None
    key = to.strip().rstrip("/")
    if key.endswith(".md"):
        key = key[:-3]
    if not re.match(_cfg.page_dirs_re() + "/", key) or key not in _anc.registry():
        return None
    if not _anc.pilot_root(key):
        return None
    who = f"{sender} (a script on {machine})"
    gist = _svcstore._shown_ids(text.strip())
    nid = _routing.record(key, kind="message", to="", label=f"message to {key}", who=who, text=gist, url=pr,
                          target="project-wide", pilot=True, log_only=True, reason="log-only: a green release")
    _routing.rule(nid, "merged", reason="log-only: a green release, ruled automatically", by=AUTO_RULER)
    commented = []
    note = "released: " + _clip_line(re.sub(r"^\[release\]\s*", "", gist), 400)
    for g in dict.fromkeys(g for gs in _pr_items([pr]).values() for g in gs):
        try:
            _writes.save(g, _svcstore._load(g), note=note)       # unchanged: the server's note in the History; no clock moves, no page owed
            commented.append(g)
        except Exception as e:  # noqa: BLE001  — a comment that fails never fails the log line
            print(f"release: {g} not commented: {e}", file=sys.stderr, flush=True)
    try:
        _messaging.MSG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "from": sender, "auth": f"machine:{machine}", "to": key,
                                "outcome": "log-only", "error": "", "text": gist}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _hooks().publish()
    return (f"logged, not delivered (a green release is log-only): notice {nid} on {key}, ruled merged by {AUTO_RULER}; it stays on the routing page"
            + (f"; commented on {', '.join(_gh.shown(g) for g in commented)}" if commented else ""))
