#!/usr/bin/env python3
"""tools/mq_replay.py — the cases the merge queue (`salamander mq`) is tested on by replaying past pull requests whose outcome is known.

The queue is tried on about twenty PRs the old release path (release.sh) already decided: merged ones must come out of the queue as a passing group
whose tree is the tree of the old merge; refused ones must be refused for the same reason. This file holds the first step, `build-cases`: it reads the release
logs and git history and writes tests/mq_replay/cases.json, which is checked in, so the cases outlive the logs (logs are not kept for ever).

    python3 tools/mq_replay.py build-cases [--repo DIR] [--logdir DIR] [--out FILE] [--main-ref origin/main] [--remote URL] [--repo-owner LOGIN]
                                           [--trigger SHA] [--selection FILE] [--verify fetch|local|none] [--strict]
    python3 tools/mq_replay.py build-cases --check [--repo DIR] [--cases FILE] [--main-ref origin/main] [--remote URL]
                                           [--verify local|fetch|none] [--allow-missing] [--strict]

`--repo-owner LOGIN` is the repository's own owner login (default: read from a github.com remote url); a PR whose head branch is in that namespace records no `owner`,
and the build refuses to write an owner it cannot derive: it stops with exit 2. `--cases FILE` is the
file `--check` verifies (default tests/mq_replay/cases.json).

Stdlib only. The checkout is read with `git -C DIR` and never changed: no checkout, no switch, no push, no fetch into it; only refs it already has are read (the
caller fetches origin first). Scratch (a temp folder, locked with flock while it runs, removed on every way out, a SIGTERM included) holds two bare repositories:
one empty, where each sha that main's history does not hold is fetched from the remote by itself (`git fetch <remote> <sha>`, depth 1), and one that borrows the
checkout's objects (alternates) and receives git's own writes, so `git merge-tree --write-tree` leaves nothing in the checkout.

How a past PR is reproduced (the rules, in this order):

  * Merged PR: base = M^1 for M the merge commit; head = the head the old path merged, with release.sh's own `Merge branch 'main' into ...` commits peeled off
    (M^2, then ^1 while the subject starts that way), so the queue does the merge of main itself. A selection entry may ask for `"head": "queue"`: the head the
    attempt started with (the log's `(head <sha>)`), for a PR whose old path mended a conflict by a merge of its own.
  * Refused attempt: base = main's first-parent tip before the time of the log's `FAILED at ...` line (`git rev-list -1 --first-parent --before=<time>`);
    head = the attempt's `(head <sha>)` (or, when that line is missing, the sha of `merging main into <sha>`; the `(head ...)` line wins when both are there). Only a refusal with a queue equivalent is kept: a check
    failure (`a check failed: X=fail`, expected `refused: a check failed: X=fail`, and the check states are the fixture) or a conflict with main (`refused:
    conflicts with main (<files>)`); `still pending`, `UNKNOWN`, deploy and merge errors have none and are dropped.
  * A group: the PRs were queued within minutes of each other, on one tip. The group base is main's tip named by the earliest `main's tip <sha>` line of the
    group's attempts. Main's tip at the first attempt's start is older than that: a release waits for its PR's checks first (tens of minutes), and only then
    reads main, which has moved on meanwhile. The old path judged the PRs against the tip of that first line and retested on every later tip (each later
    `main's tip` line is such a retest), so the earliest line is the tip the group was first tried against, and the later lines are not the base. Without any
    such line the base is main's first-parent tip before the earliest attempt start; the selection's `group_base` overrides both. Each PR keeps its own base
    (M^1 or the refusal's) beside it.
  * Only a case whose base contains the commit that made `queue/**` run the workflow (--trigger, 0101010) can run CI, so others are dropped.
  * Every sha must exist: one that main's history holds is read there; any other (a refused attempt's head, often not the PR's final one) is fetched by itself from
    the remote. A case with a sha that is not recoverable (the log names none, it is ambiguous or unknown, or the remote does not give it) is dropped, and the drop
    is printed and recorded under "dropped".

Per PR the file records: pr, attempt, known_outcome (merged | refused), head, queue_head, base, branch and owner (from the PR's `Merge pull request #N from owner/branch`
commit, else the log; no `owner` key means the repository's own owner, so the file names no login of the instance), checks (the states the PR showed: pass | fail | pending | cancel, exactly), and for a merged PR the merge commit, its tree and main's run
(result, run id, the covering commit, suites that failed only when measured); for a refused one the stage, the log's words, the expected queue reason, the
conflict files and the time of the refusal. `offline_merge` is what `git merge-tree` says of head into the PR's base (clean, equal to M's tree, conflicted files):
a merged PR that merges clean must have M's tree (unless its head is the queue-time one, `head_mode` "queue", which lacks what the author pushed later). A case has id, kind (merged | refused | group), prs, base and expected_tree (M's tree for a single merged case).

`--check` reads cases.json and verifies it against git without writing anything: the shape, every sha present (`--verify local`, the default, reads the checkout;
`fetch` also fetches the missing ones by sha; `--allow-missing` turns a missing sha into a warning), and for each PR that the merge-tree of head and base is what
the file says, and for a merged PR that merges clean equal to M's tree. It checks shas and trees, not how a base was derived (the group and refusal base
rules are applied by `build-cases` only). Exit 0 / 1 (a failed check or, with --strict, a drop) / 2 (usage, or the logs cannot be read)."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))      # tools/ holds the sibling module mq_replay_run
FORMAT = 1
TRIGGER = "0101010"                      # the commit that made tests.yml run on `queue/**`
VALID_STATES = ("pass", "fail", "pending", "cancel")
SCRATCH_PREFIX = "mq-replay-"
PEEL_SUBJECT = "Merge branch 'main' into"
FETCH_TIMEOUT = 180

# The cases chosen from the release logs (the data of each is regenerated from the logs and git; this table only says which attempts). [pr, attempt] is
# the PR's n-th `release of PR #N starts` (from 0). "head": "queue" = the head the attempt started with; "group_base" = an explicit group base;
# "fixture": {"<pr>": "omit"} = the PR shows no checks, so CI decides (the failing-alone case).
SELECTION = [
    {"id": "c01", "prs": [[9, 0]]},
    {"id": "c02", "prs": [[23, 0]]},
    {"id": "c03", "prs": [[18, 0]]},
    {"id": "c04", "prs": [[20, 0]]},
    {"id": "c05", "prs": [[15, 0]]},
    {"id": "c06", "prs": [[6, 0]]},
    {"id": "c07", "prs": [[7, 0]]},
    {"id": "c08", "prs": [[5, 0]], "head": "queue"},
    {"id": "c09", "prs": [[12, 1]]},
    {"id": "c10", "prs": [[2, 0]]},
    {"id": "c11", "prs": [[19, 0]]},
    {"id": "c12", "prs": [[21, 0], [22, 0], [4, 0]]},
    {"id": "c13", "prs": [[11, 0], [10, 0]], "fixture": {"10": "omit"},
     "note": "the refused PR shows no checks, so CI decides: expect the PR to fail on its own and the other PR to pass"},
    {"id": "c14", "prs": [[13, 0]]},
    {"id": "c15", "prs": [[1, 1]]},
    {"id": "c16", "prs": [[14, 1]]},
    {"id": "c17", "prs": [[16, 0]]},
    {"id": "c18", "prs": [[3, 0]]},
    {"id": "c19", "prs": [[17, 0]]},
    {"id": "c20", "prs": [[8, 0]]},
]


class Drop(Exception):
    """a case (or a PR of it) that cannot be built: the reason is printed and recorded"""


def log(msg: str) -> None:
    print(f"mq_replay: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- git and scratch

GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def git(repo: str | Path, *args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, env={**GIT_ENV, **(env or {})})


def out(repo, *args, **kw) -> str | None:
    """stdout of a git command that succeeded, else None"""
    r = git(repo, *args, **kw)
    return r.stdout.strip() if r.returncode == 0 else None


@contextlib.contextmanager
def scratch():
    """a temp folder locked with flock while it runs (systemd-tmpfiles ageing skips a locked folder), removed on every way out"""
    path = tempfile.mkdtemp(prefix=SCRATCH_PREFIX)
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        fcntl.flock(fd, fcntl.LOCK_SH)
        yield Path(path)
    finally:
        if fd >= 0:
            os.close(fd)
        shutil.rmtree(path, ignore_errors=True)


class Repo:
    """the checkout read-only, plus the two scratch repositories (see the module text)"""

    def __init__(self, repo: str, main_ref: str, remote: str | None, tmp: Path):
        self.repo = str(repo)
        self.main_ref = main_ref
        self.remote = remote
        objs = out(self.repo, "rev-parse", "--path-format=absolute", "--git-path", "objects")
        if objs is None:
            raise SystemExit(f"mq_replay: {repo} is not a git checkout")
        self.work = tmp / "work.git"            # borrows the checkout's objects; git's writes (merge-tree) land here
        self.empty = tmp / "empty.git"          # nothing in it: a sha fetched here was served by the remote
        for d in (self.work, self.empty):
            subprocess.run(["git", "init", "--bare", "--quiet", str(d)], check=True, capture_output=True, env=GIT_ENV)
        (self.work / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (self.work / "objects" / "info" / "alternates").write_text(objs + "\n")
        self.main_tip = out(self.repo, "rev-parse", "--verify", "--quiet", f"{main_ref}^{{commit}}")

    def full(self, ref: str) -> str | None:
        """a full commit sha for an abbreviation or a ref (None when unknown or ambiguous)"""
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", ref) and not ref.startswith(("origin/", "refs/")):
            return None
        return out(self.repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")

    def has(self, sha: str) -> bool:
        return git(self.repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    def on_main(self, sha: str) -> bool:
        return self.main_tip is not None and git(self.repo, "merge-base", "--is-ancestor", sha, self.main_tip).returncode == 0

    def is_ancestor(self, a: str, b: str) -> bool:
        return git(self.repo, "merge-base", "--is-ancestor", a, b).returncode == 0

    def tree(self, sha: str) -> str | None:
        return out(self.repo, "rev-parse", f"{sha}^{{tree}}")

    def parents(self, sha: str) -> list[str]:
        r = out(self.repo, "rev-list", "--parents", "-n", "1", sha)
        return r.split()[1:] if r else []

    def subject(self, sha: str) -> str:
        return out(self.repo, "log", "-1", "--format=%s", sha) or ""

    def base_before(self, iso: str) -> str | None:
        """main's first-parent tip before a time (ISO, Z)"""
        return out(self.repo, "rev-list", "-1", "--first-parent", f"--before={iso}", self.main_ref) or None

    def merge_commit_of(self, pr: int) -> tuple[str, str] | None:
        """(sha, subject) of the first-parent merge commit `Merge pull request #N from ...` on main"""
        r = out(self.repo, "log", "--first-parent", "--extended-regexp", f"--grep=^Merge pull request #{pr} from ", "-n", "1", "--format=%H%x09%s", self.main_ref)
        if not r:
            return None
        h, _, s = r.partition("\t")
        return h, s

    def merge_tree(self, base: str, head: str) -> dict | None:
        """git's merge of head into base, no commit: {"clean", "tree", "conflicts"}; None when git cannot (an object is missing)"""
        r = git(self.work, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, head)
        if r.returncode not in (0, 1):
            return None
        lines = r.stdout.splitlines()
        if not lines:
            return None
        conf = []
        for ln in lines[1:]:
            if not ln:
                break
            conf.append(ln)
        return {"clean": r.returncode == 0, "tree": lines[0], "conflicts": sorted(conf)}

    def fetch_by_sha(self, sha: str) -> bool:
        """prove the remote serves `sha` by itself: fetched into the empty repository, depth 1. The commit is also fetched into the work repository."""
        if not self.remote:
            return False
        r = subprocess.run(["git", "-C", str(self.empty), "fetch", "--quiet", "--no-tags", "--depth=1", self.remote, sha], capture_output=True, text=True,
                           timeout=FETCH_TIMEOUT, env=GIT_ENV)
        if r.returncode != 0 or git(self.empty, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            return False
        # the work repository gets the commit too (for merge-tree): the shallow cut is dropped, its parents are in the checkout
        subprocess.run(["git", "-C", str(self.work), "fetch", "--quiet", "--no-tags", "--depth=1", self.remote, sha], capture_output=True, text=True,
                       timeout=FETCH_TIMEOUT, env=GIT_ENV)
        with contextlib.suppress(OSError):
            (self.work / "shallow").unlink()
        return True


# ---------------------------------------------------------------- the logs

LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (.*)$")
START_RE = re.compile(r"^release of PR #(\d+) starts")
HEAD_RE = re.compile(r"^PR #(\d+): .* \(head ([0-9a-f]{7,40})\)$")
MERGING_RE = re.compile(r"merging main into ([0-9a-f]{7,40}) in a temporary worktree")
LEDGER_RE = re.compile(r"recorded the merge ([0-9a-f]{7,40}) in the fast-ok ledger")
MAINRUN_RE = re.compile(r"^main's tests pass(?:ed)? (?:on|at) ([0-9a-f]{7,40}) \(run (\d+)(?:, on ([0-9a-f]{7,40}), which contains ([0-9a-f]{7,40}))?\)")
FLAKY_RE = re.compile(r"^main's run: (.+?) failed only when measured, then passed plainly")
FAILED_RE = re.compile(r"^FAILED at ([^:]+): (.*)$")
DELETED_RE = re.compile(r"^deleted the head branch (\S+)")
TIP_RE = re.compile(r"main's tip ([0-9a-f]{7,40})")
CONFLICT_FILES_RE = re.compile(r"declined: the conflict is not only the snapshot: (.+)$")



def parse_log(path: Path) -> list[dict]:
    """the attempts of one release log: one per `release of PR #N starts`"""
    attempts: list[dict] = []
    cur = None
    for raw in path.read_text(errors="replace").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue                      # a continuation (the deploy list, the file table)
        ts, t = m.groups()
        if START_RE.match(t):
            cur = {"start": ts, "head": None, "merging": None, "merged": False, "merge": None, "stage": None, "words": None, "failed_at": None, "main_result": None,
                   "main_run": None, "main_on": None, "flaky": [], "checks_pass": False, "branch": None, "conflict_files": [], "tip": None, "tip_at": None}
            attempts.append(cur)
            continue
        if cur is None:
            continue
        mh = HEAD_RE.match(t)
        if mh and cur["head"] is None:
            cur["head"] = mh.group(2)
        mi = MERGING_RE.search(t)
        if mi and cur["merging"] is None:
            cur["merging"] = mi.group(1)
        if t == "checks pass" or t.startswith("the PR's tests pass"):
            cur["checks_pass"] = True
        if t == "merged":
            cur["merged"] = True
        ml = LEDGER_RE.search(t)
        if ml:
            cur["merge"] = ml.group(1)
        md = DELETED_RE.match(t)
        if md:
            cur["branch"] = md.group(1)
        mf = FAILED_RE.match(t)
        if mf and cur["stage"] is None:
            cur["stage"], cur["words"], cur["failed_at"] = mf.group(1), mf.group(2), ts
            if cur["stage"] == "main's tests":
                cur["main_result"] = "fail"
        mc = CONFLICT_FILES_RE.search(t)
        if mc and not cur["conflict_files"]:
            cur["conflict_files"] = sorted(p.strip() for p in mc.group(1).split(","))
        mt = TIP_RE.search(t)
        if mt and cur["tip"] is None and "main's tests" not in t:
            cur["tip"], cur["tip_at"] = mt.group(1), ts
        mr = MAINRUN_RE.match(t)
        if mr:
            cur["main_result"], cur["main_run"], cur["main_on"] = "pass", int(mr.group(2)), mr.group(3) or mr.group(1)
        mk = FLAKY_RE.match(t)
        if mk:
            cur["flaky"] = [s.strip() for s in mk.group(1).split(",")]
    return attempts


def check_states(words: str) -> dict[str, str] | None:
    """`a check failed: suites=pending, tool-text=pass` -> {"suites": "pending", "tool-text": "pass"}; None when the words are not that, ValueError for a state outside the four"""
    m = re.match(r"a check failed: (.+)$", words)
    if not m:
        return None
    states = {}
    for part in m.group(1).split(","):
        name, _, state = part.strip().partition("=")
        if not name or state not in VALID_STATES:
            raise ValueError(f"check state {part.strip()!r} is none of {'|'.join(VALID_STATES)}")
        states[name] = state
    return states


# ---------------------------------------------------------------- building

class Ctx:
    def __init__(self, repo: Repo, logdir: Path, trigger: str, repo_owner: str | None = None):
        self.repo, self.logdir, self.trigger, self.repo_owner = repo, logdir, trigger, repo_owner
        self.logs: dict[int, list[dict]] = {}

    def attempt(self, pr: int, n: int) -> dict:
        if pr not in self.logs:
            p = self.logdir / f"pr-{pr}.log"
            if not p.is_file():
                raise Drop(f"#{pr}: no release log {p.name} in {self.logdir}")
            self.logs[pr] = parse_log(p)
        if n >= len(self.logs[pr]):
            raise Drop(f"#{pr}: the log has {len(self.logs[pr])} attempt(s), no attempt {n}")
        return self.logs[pr][n]

    def resolve(self, what: str, abbr: str | None) -> str:
        if not abbr:
            raise Drop(f"{what}: no sha recoverable from the log")
        full = self.repo.full(abbr)
        if not full:
            raise Drop(f"{what}: {abbr} is not a commit this checkout knows (or is ambiguous)")
        return full


def pr_origin(ctx: Ctx, pr: int, log_branch: str | None) -> tuple[str | None, str | None]:
    """(owner, branch) of the PR's head branch: from its `Merge pull request #N from owner/branch` commit, else the log's `deleted the head branch`"""
    mc = ctx.repo.merge_commit_of(pr)
    if mc:
        m = re.match(rf"Merge pull request #{pr} from ([^/\s]+)/(\S+)", mc[1])
        if m:
            return m.group(1), m.group(2)
    return None, log_branch


def build_pr(ctx: Ctx, pr: int, n: int, sel: dict) -> dict:
    r = ctx.repo
    a = ctx.attempt(pr, n)
    what = f"#{pr} attempt {n}"
    rec: dict = {"pr": pr, "attempt": n}
    omit = (sel.get("fixture") or {}).get(str(pr)) == "omit"
    queue_head = a["head"] or a["merging"]
    if a["merged"]:
        mfull = ctx.resolve(f"{what}: the merge commit", a["merge"]) if a["merge"] else None
        found = r.merge_commit_of(pr)
        if mfull is None:
            if not found:
                raise Drop(f"{what}: merged, but the log names no merge commit and main has no `Merge pull request #{pr}`")
            mfull = found[0]
        if not r.subject(mfull).startswith(f"Merge pull request #{pr} from "):
            raise Drop(f"{what}: {mfull[:7]} is not the merge of #{pr} (subject {r.subject(mfull)!r})")
        ps = r.parents(mfull)
        if len(ps) != 2:
            raise Drop(f"{what}: {mfull[:7]} has {len(ps)} parent(s), not a merge of a head into a base")
        base, peeled = ps[0], 0
        head = ps[1]
        while r.subject(head).startswith(PEEL_SUBJECT):
            pp = r.parents(head)
            if not pp:
                raise Drop(f"{what}: peeling reached a commit with no parent")
            head, peeled = pp[0], peeled + 1
        qh = ctx.resolve(f"{what}: the head", queue_head) if queue_head else None
        if sel.get("head") == "queue":
            if not qh:
                raise Drop(f"{what}: the selection wants the queue-time head, the log names none")
            head = qh
        rec.update(known_outcome="merged", head=head, head_mode="queue" if sel.get("head") == "queue" else "peeled", queue_head=qh, base=base, merge=mfull,
                   merge_tree=r.tree(mfull), peeled=peeled)
        run = {"result": a["main_result"], "run": a["main_run"], "on": r.full(a["main_on"]) or a["main_on"] if a["main_on"] else None, "flaky": a["flaky"]}
        rec["main_run"] = run
        rec["checks"] = {} if omit else ({"suites": "pass"} if a["checks_pass"] else {})
    else:
        if a["stage"] is None:
            raise Drop(f"{what}: neither merged nor refused in the log (no FAILED line)")
        head = ctx.resolve(f"{what}: the head", queue_head)
        stage, words = a["stage"], a["words"]
        try:
            states = check_states(words)
        except ValueError as e:
            raise Drop(f"{what}: {e}") from None
        conflict = states is None and stage in ("update-branch", "mergeable") and re.search(r"conflict", words, re.I) and "UNKNOWN" not in words
        if states is None and not conflict:
            raise Drop(f"{what}: FAILED at {stage}: {words[:70]}... has no queue equivalent")
        base = r.base_before(a["failed_at"])
        if not base:
            raise Drop(f"{what}: main has no first-parent commit before {a['failed_at']}")
        rec.update(known_outcome="refused", head=head, queue_head=head, base=base, base_rule=f"main's first-parent tip before {a['failed_at']}", refused_at=a["failed_at"],
                   stage=stage, reason=words)
        if states is not None:
            rec["expected_reason"] = "refused: " + words
            rec["conflict_files"] = []
            rec["checks"] = {} if omit else states
        else:
            files = a["conflict_files"]
            rec["expected_reason"] = "refused: conflicts with main" + (f" ({', '.join(files)})" if files else "")
            rec["conflict_files"] = files
            rec["checks"] = {} if omit else ({"suites": "pass"} if a["checks_pass"] else {})
    if omit:
        rec["checks_note"] = "left out on purpose: the PR shows no checks, so CI decides"
        if rec["known_outcome"] == "refused":      # the log's reason is not what the queue is expected to say: CI decides, and the chain drops the PR on its own
            rec.pop("expected_reason", None)
            rec["expect"] = "fails alone: this PR is dropped as failed on its own and the others pass"
    owner, branch = pr_origin(ctx, pr, a["branch"])
    if owner != ctx.repo_owner:           # no `owner` key = the head branch lives in the repository's own namespace (the common case; a fork's owner is named)
        rec["owner"] = owner
    rec["branch"] = branch
    return rec


def offline(r: Repo, rec: dict) -> dict | None:
    mt = r.merge_tree(rec["base"], rec["head"])
    if mt is None:
        return None
    res = {"clean": mt["clean"], "conflicts": mt["conflicts"] if not mt["clean"] else []}
    if rec["known_outcome"] == "merged":
        res["tree_equals_merge"] = mt["clean"] and mt["tree"] == rec["merge_tree"]
    return res


def build_case(ctx: Ctx, sel: dict) -> dict:
    r = ctx.repo
    cid = sel["id"]
    prs = [build_pr(ctx, pr, n, sel) for pr, n in sel["prs"]]
    group = len(prs) > 1
    if group:
        if sel.get("group_base"):
            base = ctx.resolve(f"{cid}: group_base", sel["group_base"])
        else:
            tips = sorted((x["tip_at"], x["tip"]) for x in (ctx.attempt(pr, n) for pr, n in sel["prs"]) if x["tip"])
            if tips:                      # main's tip as the old path first saw it for the group (its `retest needed ... on main's tip X` line)
                base = ctx.resolve(f"{cid}: the group's tip", tips[0][1])
            else:
                first = min(ctx.attempt(pr, n)["start"] for pr, n in sel["prs"])
                base = r.base_before(first)
                if not base:
                    raise Drop(f"{cid}: no first-parent commit of main before {first}")
    else:
        base = prs[0]["base"]
    if not r.is_ancestor(ctx.trigger, base):
        raise Drop(f"{cid}: the base {base[:7]} does not contain the trigger {ctx.trigger[:7]} (queue/** does not run CI there)")
    case = {"id": cid, "kind": "group" if group else prs[0]["known_outcome"], "prs": prs, "base": base}
    if not group:
        case["known_outcome"] = prs[0]["known_outcome"]
        case["expected_tree"] = prs[0].get("merge_tree")
    if sel.get("note"):
        case["note"] = sel["note"]
    return case


def shas_of(case: dict) -> set[str]:
    s = {case["base"]}
    for p in case["prs"]:
        s |= {p["head"], p["base"], p.get("queue_head") or p["head"], p.get("merge") or p["head"]}
    return s


def verify_case(r: Repo, case: dict, mode: str) -> None:
    for sha in sorted(shas_of(case)):
        if r.on_main(sha):
            continue                      # main's history is the remote's ref: it serves it
        if mode == "none":
            continue
        if mode == "fetch":
            if not r.fetch_by_sha(sha):
                raise Drop(f"{case['id']}: the remote does not serve {sha[:7]} by sha")
        elif not r.has(sha):
            raise Drop(f"{case['id']}: {sha[:7]} is not in the checkout")


def add_offline(r: Repo, case: dict) -> list[str]:
    warn = []
    for p in case["prs"]:
        o = offline(r, p)
        p["offline_merge"] = o
        if o is None:
            warn.append(f"{case['id']} #{p['pr']}: git cannot merge-tree {p['head'][:7]} into {p['base'][:7]} (an object is missing)")
        elif p["known_outcome"] == "merged" and o["clean"] and not o["tree_equals_merge"] and p["head_mode"] == "peeled":
            warn.append(f"{case['id']} #{p['pr']}: merges clean but the tree is not M's ({p['merge'][:7]})")
        elif p["known_outcome"] == "merged" and not o["clean"]:
            warn.append(f"{case['id']} #{p['pr']}: conflicts with its base ({', '.join(o['conflicts'])}): the queue's on_conflict hook has to mend it")
    return warn


def cmd_build(a) -> int:
    logdir = Path(a.logdir or os.environ.get("STACKSHOT_LOGDIR") or Path.home() / ".local/state/stackshot/releases")
    if not logdir.is_dir():
        log(f"no release log folder {logdir}")
        return 2
    selection = json.loads(Path(a.selection).read_text()) if a.selection else SELECTION
    remote = a.remote or out(a.repo, "remote", "get-url", "origin")
    with scratch() as tmp:
        r = Repo(a.repo, a.main_ref, remote, tmp)
        if r.main_tip is None:
            log(f"{a.main_ref} is unknown in {a.repo}: fetch origin first")
            return 2
        trig = r.full(a.trigger)
        if not trig:
            log(f"the trigger commit {a.trigger} is unknown in {a.repo}")
            return 2
        mo = re.search(r"github\.com[:/]([^/:\s]+)/", remote or "")
        owner = a.repo_owner or (mo.group(1) if mo else None)
        if not owner:
            log(f"the repository's owner login is unknown (the remote {remote!r} is no github.com url): pass --repo-owner LOGIN, so the file records an `owner` only for a fork")
            return 2
        ctx = Ctx(r, logdir, trig, owner)
        cases, dropped, warns = [], [], []
        for sel in selection:
            try:
                case = build_case(ctx, sel)
                verify_case(r, case, a.verify)
                warns += add_offline(r, case)
                cases.append(case)
            except Drop as e:
                dropped.append({"id": sel["id"], "prs": [p for p, _ in sel["prs"]], "reason": str(e)})
                log(f"DROPPED {sel['id']}: {e}")
        doc = {"format": FORMAT, "trigger": trig, "cases": cases, "dropped": dropped}
        outp = Path(a.out) if a.out else ROOT / "tests" / "mq_replay" / "cases.json"
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    for w in warns:
        log(f"note: {w}")
    print(f"{'id':4} {'kind':8} {'PR(s)':22} outcome")
    for c in cases:
        print(f"{c['id']:4} {c['kind']:8} {','.join('#%d' % p['pr'] for p in c['prs']):22} " + "/".join(p["known_outcome"] for p in c["prs"]))
    print(f"{len(cases)} case(s) written to {outp}; {len(dropped)} dropped")
    return 1 if (dropped and a.strict) else 0


# ---------------------------------------------------------------- --check

PR_KEYS = ("pr", "attempt", "known_outcome", "head", "base", "checks", "offline_merge")
SHA_RE = re.compile(r"[0-9a-f]{40}")


def cmd_check(a) -> int:
    path = Path(a.cases) if a.cases else ROOT / "tests" / "mq_replay" / "cases.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        log(f"cannot read {path}: {e}")
        return 2
    problems: list[str] = []
    warns: list[str] = []
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list) or doc.get("format") != FORMAT:
        log(f"{path} is not a format {FORMAT} cases file")
        return 1
    with scratch() as tmp:
        remote = a.remote or out(a.repo, "remote", "get-url", "origin")
        r = Repo(a.repo, a.main_ref, remote, tmp)
        for c in cases:
            cid = c.get("id", "?")
            for k in ("id", "kind", "prs", "base"):
                if k not in c:
                    problems.append(f"{cid}: key {k} missing")
            if c.get("kind") not in ("merged", "refused", "group"):
                problems.append(f"{cid}: kind {c.get('kind')!r}")
            if not SHA_RE.fullmatch(str(c.get("base", ""))):
                problems.append(f"{cid}: base is not a full sha")
            for p in c.get("prs", []):
                lab = f"{cid} #{p.get('pr')}"
                miss = [k for k in PR_KEYS if k not in p]
                if miss:
                    problems.append(f"{lab}: keys missing: {', '.join(miss)}")
                    continue
                if p["known_outcome"] not in ("merged", "refused"):
                    problems.append(f"{lab}: known_outcome {p['known_outcome']!r}")
                for k in ("head", "base") + (("merge",) if p["known_outcome"] == "merged" else ()):
                    if not SHA_RE.fullmatch(str(p.get(k, ""))):
                        problems.append(f"{lab}: {k} is not a full sha")
                bad = [f"{n}={s}" for n, s in p["checks"].items() if s not in VALID_STATES]
                if bad:
                    problems.append(f"{lab}: check states outside {'|'.join(VALID_STATES)}: {', '.join(bad)}")
                if p["known_outcome"] == "refused" and not (p.get("expected_reason") or p.get("expect")):
                    problems.append(f"{lab}: a refused PR needs expected_reason (or expect, for a PR whose checks are left out)")
                if p.get("expect") and p.get("expected_reason"):
                    problems.append(f"{lab}: expect and expected_reason together (a PR with left-out checks has no expected reason)")
            if problems and any(x.startswith(cid + ":") or x.startswith(cid + " ") for x in problems):
                continue
            # git
            for sha in sorted(shas_of(c)):
                if a.verify == "none" or r.has(sha):
                    continue
                if a.verify == "fetch" and r.fetch_by_sha(sha):
                    continue
                (warns if a.allow_missing else problems).append(f"{cid}: {sha[:7]} is not available")
            for p in c["prs"]:
                lab = f"{cid} #{p['pr']}"
                if not (r.has(p["head"]) and r.has(p["base"])):
                    continue
                o = offline(r, p)
                if o is None:
                    (warns if a.allow_missing else problems).append(f"{lab}: git cannot merge-tree head into base")
                    continue
                rec = p["offline_merge"]
                for k in o:
                    if rec.get(k) != o[k]:
                        problems.append(f"{lab}: offline_merge.{k} is {rec.get(k)!r} in the file, git says {o[k]!r}")
                if p["known_outcome"] == "merged":
                    if r.has(p["merge"]) and r.tree(p["merge"]) != p.get("merge_tree"):
                        problems.append(f"{lab}: merge_tree is not the tree of {p['merge'][:7]}")
                    if o["clean"] and o["tree_equals_merge"] is not True and p.get("head_mode") != "queue":
                        problems.append(f"{lab}: head merges clean into base but the tree is not M's")
                elif p.get("conflict_files") and not o["clean"] and o["conflicts"] != sorted(p["conflict_files"]):
                    warns.append(f"{lab}: the conflict files git finds ({', '.join(o['conflicts'])}) differ from the log's ({', '.join(p['conflict_files'])})")
            if len(c["prs"]) == 1 and c["prs"][0]["known_outcome"] == "merged" and c.get("expected_tree") != c["prs"][0].get("merge_tree"):
                problems.append(f"{cid}: expected_tree is not the merge's tree")
    for w in warns:
        log(f"warning: {w}")
    for p in problems:
        log(f"FAIL {p}")
    print(f"{len(cases)} case(s) checked: {len(problems)} problem(s), {len(warns)} warning(s)")
    return 1 if problems or (doc.get("dropped") and a.strict) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-cases", help="write tests/mq_replay/cases.json from the release logs and git history, or verify it with --check")
    b.add_argument("--repo", default=str(ROOT), help="the checkout whose history is read (never changed); default this one")
    b.add_argument("--logdir", help="the release logs (default $STACKSHOT_LOGDIR, else ~/.local/state/stackshot/releases)")
    b.add_argument("--out", help="the cases file to write (default tests/mq_replay/cases.json)")
    b.add_argument("--cases", help="with --check: the cases file to verify (default tests/mq_replay/cases.json)")
    b.add_argument("--main-ref", default="origin/main", help="main as the checkout knows it (the caller fetched it)")
    b.add_argument("--remote", help="where shas are fetched from (default the checkout's origin url)")
    b.add_argument("--repo-owner", help="the repository's own owner login (default: from a github.com remote url); a PR whose head branch is in it records no `owner`")
    b.add_argument("--trigger", default=TRIGGER, help="the commit a base must contain to run CI on queue/** (default %(default)s)")
    b.add_argument("--selection", help="a JSON file of selection entries instead of the built-in 20")
    b.add_argument("--verify", choices=("fetch", "local", "none"), default=None, help="how a sha main's history does not hold is verified (build: fetch; --check: local)")
    b.add_argument("--check", action="store_true", help="verify the cases file against git, write nothing")
    b.add_argument("--allow-missing", action="store_true", help="--check: a sha the checkout lacks is a warning")
    b.add_argument("--strict", action="store_true", help="exit 1 when a case was dropped (build) or the file lists drops (--check)")
    import mq_replay_run                       # run | report | clean (tools/mq_replay_run.py)
    mq_replay_run.add_commands(sub)
    a = ap.parse_args()
    if a.cmd in mq_replay_run.COMMANDS:
        return mq_replay_run.dispatch(a)
    if a.verify is None:
        a.verify = "local" if a.check else "fetch"
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))      # the scratch folder goes with the process
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(129))
    return cmd_check(a) if a.check else cmd_build(a)


if __name__ == "__main__":
    sys.exit(main())
