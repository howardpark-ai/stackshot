"""released_live.py: what is live in a checkout, read from git, and the pull requests anchored to an item.

The release settle (service/released.py) and the step proofs (service/proofs.py) read the same facts: the last-good commit that release.sh records, the checkout's HEAD, the merge commits of a repository
(this one, or a configured one in [released.repos], which may be on another machine and is then read over ssh), whether a merge is passed and live, the pull requests anchored to each item, and whether an item that names a release is left alone (on hold, or waiting on someone
else). They are read here, kept by commit (`proof_git`: a commit never changes, so a pass with the same commits costs no git call), and shared by the two passes and the event waits.

What it still reaches in server.py comes through `Hooks` in service/checks_hooks.py, looked up when it runs. A suite that replaces a function of this module sets it here.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

from pathlib import Path
import contextlib
import ipaddress
import os
import re
import secrets
import shlex
import socket
import subprocess
import time
from typing import Any, Callable, Iterator

from fastmcp.exceptions import ToolError

from stackshot import paths as _paths
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _session_label
from stackshot.model.ids import _norm_id
from stackshot.service import writes as _writes
from stackshot.service.checks_hooks import hooks as _hooks
from stackshot.waits import handover as _hv


RELEASED_MERGE = re.compile(r"^Merge pull request #(\d+) from ")
COMMIT_REF = re.compile(r"[0-9a-f]{7,64}|HEAD")      # what is taken for a commit: no other word a client sent reaches git


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


SSH_CONNECT = 5          # seconds ssh is given to reach the machine of a checkout that is on another one
REMOTE_SECONDS = 10      # what one ssh session runs on that machine is ended there after this long, so nothing stays behind when this side stops waiting
READ_SECONDS = 20        # all the ssh sessions and git commands that read one [released.repos] checkout in one request, write or pass, together: a report is answered well within the minute its client waits


class Unread(Exception):
    """A [released.repos] checkout gave no answer, so nothing is known of it: not a "no", and nothing is kept."""


class NoLog(dict):
    """What merged_prs gives when the log of this checkout fails: no merges, and proof_git does not keep it."""


class Reads:
    """What one request, write or pass has read of the [released.repos] checkouts (reading)."""

    def __init__(self) -> None:
        self.left: dict[str, float] = {}      # checkout → the seconds its commands have left of READ_SECONDS
        self.silent: set[str] = set()         # the ssh hosts, as the entries write them, that gave no answer: not asked again
        self.prs: dict[str, tuple[str, dict[int, tuple[str, float]]]] = {}      # repository → what foreign_prs found: read once
        self.answers: dict[tuple[str, tuple[str, ...]], subprocess.CompletedProcess[str]] = {}      # (checkout, git args) → an answer foreign_ahead has, which foreign_git gives without asking again


@contextlib.contextmanager
def reading() -> "Iterator[Reads]":
    """One request, write or pass of this thread (also a decorator of the function that is one): its reads of the [released.repos] checkouts share each checkout's time limit, leave a machine that gave no
    answer alone and read each repository's merges once. A block inside another joins it, and nothing of it is kept for the next one. What it has read is on service/writes.py (RELEASED_READS), with the
    other flags of a write."""
    outer = getattr(_writes.RELEASED_READS, "now", None)
    _writes.RELEASED_READS.now = outer or Reads()
    try:
        yield _writes.RELEASED_READS.now
    finally:
        _writes.RELEASED_READS.now = outer


def own_machine(host: str) -> bool:
    """Is `host` surely this machine, so that its checkout is read directly: this machine's own name, whole or short, "localhost", or a loopback address. A name that only begins like ours (the same first
    label under another domain) and a host written with a user are asked over ssh. Nothing is looked up. Stricter than agentbox.is_this_box: here a wrong yes counts a checkout that may run nothing."""
    h = host.lower()
    me = socket.gethostname().lower()
    if h in (me, me.split(".")[0], "localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def where(co: "_cfg.RemoteCheckout") -> tuple[str, str]:
    """How a checkout whose entry names a machine is reached now: (the word ssh takes as its host, the path as it is sent there), or ("", the path here) for a host that is this machine (own_machine).
    Raises OSError when the entry's host cannot be named (a role word whose lookup does not answer)."""
    host = _cfg.ssh_target(co.ssh)
    if not host:
        raise OSError(f"no host is known for {co.ssh!r}")
    if own_machine(host):
        return "", os.path.expanduser(co.path)
    return host, (co.path[2:] or ".") if co.path.startswith("~/") else co.path      # ssh starts in the home folder there, so "~/x" is sent as "x"


def ssh_argv(host: str, command: list[str]) -> list[str]:
    """The ssh that runs `command` on `host`, never asking for a password and using no shared connection, and ends it there after REMOTE_SECONDS. Every word is quoted for the shell over there."""
    return ["ssh", "-n", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_CONNECT}", "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
            "-o", "ControlMaster=no", "-o", "ControlPath=none", "--", host, shlex.join(["timeout", str(REMOTE_SECONDS), *command])]


def git_argv(args: "tuple[str, ...]", cwd: "Path | _cfg.RemoteCheckout | None" = None) -> list[str]:
    """The command that runs `git args` in this checkout, or in `cwd`. For a checkout on another machine it is the same git, run there over ssh (ssh_argv); a host that is this machine is read here.
    Raises OSError, running nothing, when the entry's host cannot be named (where)."""
    if not isinstance(cwd, _cfg.RemoteCheckout):
        return ["git", "-C", str(cwd or HERE), *args]
    host, there = where(cwd)
    return ssh_argv(host, ["git", "-C", there, *args]) if host else ["git", "-C", there, *args]


def git(*args: str, timeout: float = 30, cwd: "Path | _cfg.RemoteCheckout | None" = None) -> subprocess.CompletedProcess[str]:
    """git in this checkout, or in `cwd`: only a configured checkout ([released.repos]) is ever passed, never a path a client sent. Reads only."""
    return subprocess.run(git_argv(args, cwd), capture_output=True, text=True, timeout=timeout)


def _rev_args(ref: str) -> tuple[str, ...]:
    return ("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")


def _log_args(tip: str, limit: int) -> tuple[str, ...]:
    return ("log", "--first-parent", "--merges", f"-n{limit}", "--format=%H%x09%ct%x09%s", tip)


def _ancestor_args(a: str, b: str) -> tuple[str, ...]:
    return ("merge-base", "--is-ancestor", a, b)


def _within(reads: Reads, co: "Path | _cfg.RemoteCheckout", run: "Callable[[float], subprocess.CompletedProcess[str]]", answers: "tuple[int, ...]") -> subprocess.CompletedProcess[str]:
    """`run(seconds)`, which reads a [released.repos] checkout, within what is left of its READ_SECONDS. Raises Unread when there is no answer: it did not run or did not end in time, or it ended with a
    status that is none of `answers`. A machine that gave none (no connection, or no end in time) is not asked again in the same request, write or pass (reading)."""
    host = co.ssh if isinstance(co, _cfg.RemoteCheckout) else ""
    left = reads.left.get(str(co), READ_SECONDS)
    if left <= 0 or host in reads.silent:
        raise Unread
    began = time.monotonic()
    try:
        r = run(left)
    except Exception:  # noqa: BLE001
        r = None
    reads.left[str(co)] = left - (time.monotonic() - began)
    if r is not None and r.returncode in answers:
        return r
    if host and (r is None or r.returncode in (124, 255)):      # 124: ended over there for its time; 255: ssh's own failure
        reads.silent.add(host)
    raise Unread


def foreign_git(co: "Path | _cfg.RemoteCheckout", *args: str, answers: "tuple[int, ...]" = (0,)) -> subprocess.CompletedProcess[str]:
    """git `args` in a [released.repos] checkout (_within), or the answer this request already has for them (foreign_ahead). Raises Unread when the status is none of `answers`."""
    reads = getattr(_writes.RELEASED_READS, "now", None) or Reads()
    had = reads.answers.get((str(co), args))
    if had is None:
        return _within(reads, co, lambda left: git(*args, timeout=left, cwd=co), answers)
    if had.returncode in answers:
        return had
    raise Unread


_THERE_HEAD = "\0head"      # in the commands of foreign_ahead: the HEAD the shell over there has just read; no path or commit name holds a NUL


def foreign_ahead(co: "Path | _cfg.RemoteCheckout", sha: str, limit: int) -> None:
    """All that a release report asks of a checkout on another machine, in one ssh session: each session costs a connection and a sign-in, which take many seconds on a loaded link, and the report's
    reads share one READ_SECONDS. One shell there reads HEAD, then `sha` (when one is given), the newest `limit` merges of that commit (of HEAD with none) and whether it is an ancestor of that HEAD.
    The answers stay on this request (reading), where git_commit, merged_prs and foreign_live find them; when HEAD holds the commit it holds every merge of its log, so those are answered too.
    `sha` is sent only when it is a commit's name (COMMIT_REF). Nothing is read here outside a request, for a checkout on this machine, or for any other word (git_commit refuses it).
    Raises Unread when the session gives no answer, or not all of its answers."""
    reads = getattr(_writes.RELEASED_READS, "now", None)
    if reads is None or not isinstance(co, _cfg.RemoteCheckout) or (sha and not COMMIT_REF.fullmatch(sha)):
        return
    if sha == "HEAD":
        sha = ""
    commands = [_rev_args("HEAD"), *([_rev_args(sha)] if sha else []), _log_args(sha or _THERE_HEAD, limit), *([_ancestor_args(sha, _THERE_HEAD)] if sha else [])]
    end = f"end-{secrets.token_hex(12)}"      # the line that closes each answer, with its status: made afresh, so nothing a commit's subject says passes for it

    def run(left: float) -> "subprocess.CompletedProcess[str]":
        host, there = where(co)
        if not host:
            return subprocess.CompletedProcess([], 0, "", "")      # this machine: nothing is read ahead, its git commands run one by one
        head, *rest = (" ".join('"$h"' if w == _THERE_HEAD else shlex.quote(w) for w in ("git", "-C", there, *args)) for args in commands)
        script = [f"h=$({head})", "printf " + shlex.quote(f"%s\\n{end} %d\\n") + ' "$h" "$?"']
        for command in rest:
            script += [command, "printf " + shlex.quote(f"\\n{end} %d\\n") + ' "$?"']
        return subprocess.run(ssh_argv(host, ["sh", "-c", "; ".join(script)]), capture_output=True, text=True, timeout=left)

    r = _within(reads, co, run, (0,))
    if not r.args:
        return
    parts = re.split(rf"\n{end} (\d+)\n", r.stdout)
    if len(parts) != 2 * len(commands) + 1:
        raise Unread
    got = [subprocess.CompletedProcess([], int(status), out, "") for out, status in zip(parts[0::2], parts[1::2])]

    def keep(args: "tuple[str, ...]", answer: "subprocess.CompletedProcess[str]") -> None:
        reads.answers[(str(co), args)] = answer

    keep(_rev_args("HEAD"), got[0])
    if sha:
        keep(_rev_args(sha), got[1])
    head, full = got[0].stdout.strip(), got[1 if sha else 0].stdout.strip()
    log = got[2 if sha else 1]
    held = got[3] if sha else subprocess.CompletedProcess([], 0, "", "")      # with no sha the commit is HEAD itself
    keep(_log_args(full, limit), log)      # git_commit judges the two commits: where one of them is no answer, nothing asks for what is kept under it
    keep(_ancestor_args(full, head), held)
    if held.returncode == 0:
        for msha, _when in _merges(log.stdout).values():
            keep(_ancestor_args(msha, head), held)


def git_commit(ref: str, cwd: "Path | _cfg.RemoteCheckout | None" = None) -> str:
    """`ref` as a full commit sha of this checkout (or of `cwd`), or "" when it is no sha or a commit that checkout does not know (for this checkout: also when it cannot be read). A [released.repos]
    checkout (`cwd`) that gives no answer raises Unread."""
    if not COMMIT_REF.fullmatch(ref or ""):
        return ""
    args = _rev_args(ref)
    if cwd is None:
        try:
            r = git(*args)
        except Exception:  # noqa: BLE001
            return ""
    else:
        r = foreign_git(cwd, *args, answers=(0, 1))
    sha = r.stdout.strip()      # anything else printed on the way (a login message of another machine's shell) is no commit
    if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha):
        return sha
    if cwd is not None and (r.returncode != 1 or sha):      # status 1 with nothing printed says there is no such commit there; anything else is no answer
        raise Unread
    return ""


def git_ancestor(a: str, b: str, cwd: "Path | _cfg.RemoteCheckout | None" = None) -> bool:
    try:
        return git(*_ancestor_args(a, b), cwd=cwd).returncode == 0
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


def released_foreign(repo: str) -> "Path | _cfg.RemoteCheckout | None":
    """The checkout [released.repos] names for another repository (through [github.moved]), on this machine or another; None when it lists none for it."""
    return _cfg.released_repos().get(_cfg.canon_repo(repo))


def released_foreign_why() -> str:
    """The repositories [released.repos] lists, for the refusal of a pull request of an unlisted one."""
    return ", ".join(sorted(_cfg.released_repos())) or "none is configured"


def foreign_live(repo: str, sha: str) -> str:
    """"" when merge commit `sha` of a configured repository is live: an ancestor of its checkout's HEAD (read in this request, with a time limit); else why not. A checkout that gives no answer
    "cannot be read"."""
    co = released_foreign(repo)
    cannot = f"the checkout of {repo} cannot be read"
    if not co:
        return cannot
    try:
        head = git_commit("HEAD", co)
        if not head:
            return cannot
        code = foreign_git(co, *_ancestor_args(sha, head), answers=(0, 1)).returncode      # yes or no; any other end is no answer
    except Unread:
        return cannot
    return "" if code == 0 else f"its merge {sha[:7]} is not in the live checkout of {repo} ({head[:7]}) yet (not deployed, or rolled back)"


def foreign_prs(repo: str) -> tuple[str, dict[int, tuple[str, float]]]:
    """(HEAD, {N: (merge sha, time)}) for a configured repository: the pull requests merged into its checkout's HEAD, kept by commit (proof_git); ("", {}) when it is not listed or cannot be read.
    A merge in HEAD's first-parent history is live by that fact. Read once in a request, write or pass (reading), and HEAD afresh in the next, so a deploy and a rollback both show."""
    key = _cfg.canon_repo(repo)
    reads = getattr(_writes.RELEASED_READS, "now", None)
    if reads is not None and key in reads.prs:
        return reads.prs[key]
    out: "tuple[str, dict[int, tuple[str, float]]]" = ("", {})
    co = released_foreign(repo)
    try:
        head = git_commit("HEAD", co) if co else ""
        if head:
            out = (head, proof_git(("fprs", str(co), head), lambda: merged_prs(head, cwd=co)))
    except Unread:
        pass
    if reads is not None:
        reads.prs[key] = out
    return out


def foreign_prs_locked(repo: str) -> tuple[str, dict[int, tuple[str, float]]]:
    """foreign_prs for the write gate, which holds the item lock: what this write read before the lock (reading). With no such read, a checkout on this machine is read now and one with `ssh` is not
    (("", {}): the wait is stored and the catch-up reads it later), so no ssh call is made while every other write waits."""
    reads = getattr(_writes.RELEASED_READS, "now", None)
    if (reads is None or _cfg.canon_repo(repo) not in reads.prs) and isinstance(released_foreign(repo), _cfg.RemoteCheckout):
        return "", {}
    return foreign_prs(repo)


def merged_prs(head: str, limit: int = 3000, cwd: "Path | _cfg.RemoteCheckout | None" = None) -> dict[int, tuple[str, float]]:
    """The pull requests merged into `head` (its first-parent merge commits "Merge pull request #N from …", the newest `limit`) → {N: (merge sha, commit time)}; {} when it is no sha, or git cannot read
    this checkout (then a NoLog, which proof_git does not keep). A [released.repos] checkout (`cwd`) whose log fails, part of it printed or not, raises Unread."""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head or ""):
        return {}
    args = _log_args(head, limit)
    if cwd is not None:
        out = foreign_git(cwd, *args).stdout
    else:
        try:
            r = git(*args)
        except Exception:  # noqa: BLE001
            return NoLog()
        if r.returncode != 0:
            return NoLog()
        out = r.stdout
    return _merges(out)


def _merges(out: str) -> dict[int, tuple[str, float]]:
    """The output of _log_args → {N: (merge sha, commit time)}, the newest merge of each pull request."""
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
        return "parked"
    if _hooks().rmod_needs_kind(it) == "call":
        return f"its needs name a decision: it waits on {OWNER}"
    return _hv.skip_reason(meta, mover, lambda a, b: _hooks().same_sess(a, b) or _hooks().session_id(a) == _hooks().session_id(b), _session_label, OWNER)


def pr_shown(key: str) -> str:
    """A pull request as the notices name it: "PR #4" for this repository's, "PR owner/repo#4" for another's (a bare number would read as ours)."""
    repo, _, n = str(key).rpartition("#")
    return f"PR #{n}" if repo == _cfg.canon_repo(_hooks().own_repo()) or not repo else f"PR {key}"


PROOF_GIT: dict[tuple, Any] = {}      # git answers by commit: {("prs", sha): the merges of that commit, ("live", good, head, merge sha): why not live}; a commit never changes, so a pass with the same commits costs no git call


_NOT_KEPT = object()


def proof_git(key: tuple, make: Any) -> Any:
    """The answer kept for `key`, else `make()`, which is kept unless it is a failed log (NoLog; a read that raises keeps nothing either). The answer in hand is returned, never a second look into the
    table: another thread may have emptied it."""
    kept = PROOF_GIT.get(key, _NOT_KEPT)
    if kept is not _NOT_KEPT:
        return kept
    found = make()
    if not isinstance(found, NoLog):
        if len(PROOF_GIT) > 6000:
            PROOF_GIT.clear()
        PROOF_GIT[key] = found
    return found
