"""releasing.py — which pull requests are in the release script's queue, for the redesigned pages' "Queued for release" label.

The signal is release.sh's own transient unit. `release.sh <pr>` (and each release the queue starts) runs `release.sh --run <pr>` as the user unit
stackshot-release-<pr>.service and it stays until that release ends (a deploy and main's run after it, a failure, a stop): waiting for the update lock,
for its checks, for the deploy lock, for main's run. So "a release for this PR is started and has not ended" is "that unit is active", one `systemctl
--user list-units` call: no log parsing, no GitHub call. (The queue file, <state>/releases/queue, lists PRs that may not have started yet, so it is not the
signal; a PR that is only listed there has no unit and stays where it was.) The units are release.sh's for this repository, so a pull request of another
repository with the same number does not count: an anchor names its repository, and only this checkout's counts (own_repo).

An item is linked to a pull request three ways, any one is enough (Board.queued_release_ids reads the first from the anchors of every project's page, the others from the item):
  1. an anchor scoped to the item that is the PR's URL;
  2. an open step's proof (metadata.step_proof) naming pr_released or pr_merged of the PR;
  3. an open step's words (next or checklist) that link the PR's URL or say "PR #N" / "pull request #N". Done and dropped steps and the description do not count: they say what was, not what is next.
So a builder's step "release [PR #12](…)" puts its item in the section while PR #12's release unit runs, with no anchor needed.

Read once per page render (Board.queued_release_ids); an answer that cannot be had (no systemctl, no user bus, a timeout) is "nothing queued": a page never
fails or waits on it."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.model import step_proof as _sp   # a step's stored proof ("pr_released owner/repo#n") and the kinds of event it names
from stackshot.model import steps as _steps     # the checklist behind an item's next: which steps are open

_UNIT_RX = re.compile(r"\bstackshot-release-(\d+)\.service\b")
_PR_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_PR_NUM = re.compile(r"(?<![\w/#.-])(?:PR|pull request)\s*#(\d+)(?!\d)", re.I)   # "PR #12", "pull request #12"
_OTHER_PR = re.compile(r"[\w.-]+/[\w.-]+\s+(?:PR|pull request)\s*#\d+", re.I)   # "owner/repo PR #12": that repository's, taken out before the words are read
_OWN: list[str] = []
_ROOT = _paths.ROOT


def _run(argv: list[str]) -> str:
    """Run `argv`, its stdout, no shell. Replaced by a test with a stub."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout


def release_units() -> set[int]:
    """The pull request numbers whose release unit is running now: active (started and running) or activating."""
    try:
        out = _run(["systemctl", "--user", "list-units", "--plain", "--no-legend", "--no-pager", "--state=active,activating", "stackshot-release-*.service"])
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(n) for n in _UNIT_RX.findall(str(out or ""))}


def own_repo() -> str:
    """This checkout's GitHub repository, "owner/repo" through [github.moved] (config.canon_repo), from its origin remote as release.sh reads it; "" when it cannot be had. Read once per process."""
    if not _OWN:
        try:
            url = subprocess.run(["git", "-C", str(_ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            url = ""
        m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
        _OWN.append(_cfg.canon_repo(m.group(1)) if m else "")
    return _OWN[0]


def pr_of(url: str) -> int:
    """The number of this repository's pull request a URL names, 0 for any other address (another repository's pull request, an issue, a page)."""
    m = _PR_URL.search(str(url or ""))
    if not m or not own_repo() or _cfg.canon_repo(m.group(1)) != own_repo():
        return 0
    return int(m.group(2))


def queued_items(scoped: dict[str, list[str]], rows: list[dict] | None = None) -> set[str]:
    """The ids of the items linked to a pull request whose release is in the queue. `scoped`: item id → the anchor URLs scoped to it (Board.scoped_urls); `rows`: the open items, whose open steps
    link a pull request too (step_prs). One systemctl read; the steps are read only when some release is running."""
    prs = release_units()
    if not prs:
        return set()
    out = {str(g) for g, urls in scoped.items() if any(pr_of(u) in prs for u in urls)}
    for r in rows or []:
        if r.get("status") != "completed" and str(r.get("gid")) not in out and step_prs(r.get("metadata")) & prs:
            out.add(str(r["gid"]))
    return out


def step_prs(meta: dict | None, keeper: str = "") -> set[int]:
    """The numbers of this repository's pull requests an item's open steps are about: a step's stored proof (pr_released or pr_merged of this repository's PR), or its words linking the PR's URL or saying "PR #N". Only open steps count."""
    m = meta if isinstance(meta, dict) else {}
    proofs = m.get("step_proof") if isinstance(m.get("step_proof"), dict) else {}
    own = own_repo()
    out: set[int] = set()
    for s in _steps.view(m, keeper=keeper or str(m.get("owner") or "")):
        if s["status"] != _steps.OPEN:
            continue
        text = str(s["text"] or "")
        kind, ref = _sp.read_stored(proofs.get(_steps.key(text)))
        repo, _, num = ref.rpartition("#")
        if kind in _sp.KINDS and num.isdigit() and own and _cfg.canon_repo(repo) == own:
            out.add(int(num))
        out.update(n for n in (pr_of(u) for u in re.findall(r"https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+", text, re.I)) if n)
        if own:
            out.update(int(n) for n in _PR_NUM.findall(_OTHER_PR.sub(" ", text)))
    return out
