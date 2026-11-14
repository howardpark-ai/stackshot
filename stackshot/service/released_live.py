"""released_live.py: what is live in a checkout, read from git, and the pull requests anchored to an item.

The release settle (service/released.py) and the step proofs (service/proofs.py) read the same facts: the last-good commit that release.sh records, the checkout's HEAD, the merge commits of a repository
(this one, or a configured one in [released.repos]), whether a merge is passed and live, the pull requests anchored to each item, and whether an item that names a release is left alone (on hold, or waiting on someone
else). They are read here, kept by commit (`proof_git`: a commit never changes, so a pass with the same commits costs no git call), and shared by the two passes and the event waits.

What it still reaches in server.py comes through `Hooks` in service/checks_hooks.py, looked up when it runs. A suite that replaces a function of this module sets it here.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot import paths as _paths
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _session_label
from stackshot.model.ids import _norm_id
from stackshot.service.checks_hooks import hooks as _hooks
from stackshot.waits import handover as _hv


RELEASED_MERGE = re.compile(r"^Merge pull request #(\d+) from ")


def released_anchors() -> dict[str, set[str]]:
    """{item id: the keys ("owner/repo#n") of the pull requests anchored to it}."""
    out: dict[str, set[str]] = {}
    for entries in _anc.load().values():
        for e in entries:
            k = _hooks().pr_key(str(e.get("url") or ""))
            if k:
                for g in e.get("items") or []:
                    try:
                        out.setdefault(_norm_id(g), set()).add(k)
                    except ToolError:
                        continue
    return out


HERE = _paths.ROOT      # this checkout: a suite or a one-off tool that points the reads at another checkout sets it here


def git(*args: str, timeout: float = 30, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """git in this checkout, or in `cwd`: only a configured checkout ([released.repos]) is ever passed, never a path a client sent. Reads only."""
    return subprocess.run(["git", "-C", str(cwd or HERE), *args], capture_output=True, text=True, timeout=timeout)


def git_commit(ref: str, cwd: Path | None = None) -> str:
    """`ref` as a full commit sha of this checkout (or of `cwd`), or "" when it is no sha or a commit that checkout does not know."""
    if not re.fullmatch(r"[0-9a-f]{7,64}|HEAD", ref or ""):
        return ""
    try:
        r = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd)
    except Exception:  # noqa: BLE001
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def git_ancestor(a: str, b: str, cwd: Path | None = None) -> bool:
    try:
        return git("merge-base", "--is-ancestor", a, b, cwd=cwd).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def last_good() -> str:
    """The last-good commit release.sh records once main's full run passed on it ($LOGDIR/last-good, LAST_GOOD in release.sh) as a full sha, or "" when none is recorded or readable."""
    try:
        return git_commit(_cfg.state("releases", "last-good").read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return ""


def released_live_base() -> tuple[str, str]:
    """(last-good, HEAD of the checkout read now), both full shas; raises ToolError when either cannot be read."""
    good = last_good()
    if not good:
        raise ToolError(f"Refused: no last-good commit is recorded ({_cfg.state('releases', 'last-good')}), so no merge can be read as passed and live; nothing written")
    head = git_commit("HEAD")
    if not head:
        raise ToolError("Refused: the checkout's HEAD cannot be read, so no merge can be read as live; nothing written")
    return good, head


def released_is_live(sha: str, good: str, head: str) -> str:
    """"" when merge commit `sha` is passed and live (an ancestor of last-good and of HEAD), else why not."""
    if not git_ancestor(sha, good):
        return f"its merge {sha[:7]} is not in the last-good commit {good[:7]} yet (main's full run has not passed on it)"
    if not git_ancestor(sha, head):
        return f"its merge {sha[:7]} is not in the live checkout {head[:7]} (rolled back)"
    return ""


def released_foreign(repo: str) -> Path | None:
    """The checkout [released.repos] names for another repository (through [github.moved]), None when it lists none for it."""
    return _cfg.released_repos().get(_cfg.canon_repo(repo))


def released_foreign_why() -> str:
    """The repositories [released.repos] lists, for the refusal of a pull request of an unlisted one."""
    return ", ".join(sorted(_cfg.released_repos())) or "none is configured"


def foreign_live(repo: str, sha: str) -> str:
    """"" when merge commit `sha` of a configured repository is live: an ancestor of its checkout's HEAD (read now, with a timeout); else why not."""
    co = released_foreign(repo)
    head = git_commit("HEAD", co) if co else ""
    if not head:
        return f"the checkout of {repo} cannot be read"
    if not git_ancestor(sha, head, co):
        return f"its merge {sha[:7]} is not in the live checkout of {repo} ({head[:7]}) yet (not deployed, or rolled back)"
    return ""


def foreign_prs(repo: str) -> tuple[str, dict[int, tuple[str, float]]]:
    """(HEAD, {N: (merge sha, time)}) for a configured repository: the pull requests merged into its checkout's HEAD, kept by commit (proof_git); ("", {}) when it is not listed or cannot be read.
    A merge in HEAD's first-parent history is live by that fact."""
    co = released_foreign(repo)
    head = git_commit("HEAD", co) if co else ""
    return (head, proof_git(("fprs", str(co), head), lambda: merged_prs(head, cwd=co))) if head else ("", {})


def merged_prs(head: str, limit: int = 3000, cwd: Path | None = None) -> dict[int, tuple[str, float]]:
    """The pull requests merged into `head` (its first-parent merge commits "Merge pull request #N from …", the newest `limit`) → {N: (merge sha, commit time)}; {} when git cannot read it."""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head or ""):
        return {}
    try:
        out = git("log", "--first-parent", "--merges", f"-n{limit}", "--format=%H%x09%ct%x09%s", head, cwd=cwd).stdout
    except Exception:  # noqa: BLE001
        return {}
    found: dict[int, tuple[str, float]] = {}
    for ln in out.splitlines():
        parts = ln.split("\t", 2)
        m = RELEASED_MERGE.match(parts[2]) if len(parts) == 3 else None
        if m and int(m.group(1)) not in found:
            found[int(m.group(1))] = (parts[0], float(parts[1] or 0))
    return found


def released_skip(it: dict[str, Any], meta: dict[str, Any], mover: str) -> str:
    """Why an item that names the release is left alone ("" when it is not): on hold, or its needs name a decision or a session other than its mover."""
    if _hooks().is_held(it) or _hooks().hold_flag(it) or _hooks().date_parked(it):
        return "on hold"
    if _hooks().rmod_needs_kind(it) == "call":
        return f"its needs name a decision: it waits on {OWNER}"
    return _hv.skip_reason(meta, mover, lambda a, b: _hooks().same_sess(a, b) or _hooks().session_id(a) == _hooks().session_id(b), _session_label, OWNER)


def pr_shown(key: str) -> str:
    """A pull request as the notices name it: "PR #4" for this repository's, "PR owner/repo#4" for another's (a bare number would read as ours)."""
    repo, _, n = str(key).rpartition("#")
    return f"PR #{n}" if repo == _cfg.canon_repo(_hooks().own_repo()) or not repo else f"PR {key}"


PROOF_GIT: dict[tuple, Any] = {}      # git answers by commit: {("prs", sha): the merges of that commit, ("live", good, head, merge sha): why not live}; a commit never changes, so a pass with the same commits costs no git call


def proof_git(key: tuple, make: Any) -> Any:
    if key not in PROOF_GIT:
        if len(PROOF_GIT) > 6000:
            PROOF_GIT.clear()
        PROOF_GIT[key] = make()
    return PROOF_GIT[key]
