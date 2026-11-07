"""tools/mq_replay_run.py — `mq_replay.py run | report | clean`: replays the cases of tests/mq_replay/cases.json through the real merge queue (`salamander mq`) on practice
branches of the same repository, compares each verdict with what the old release path decided, and removes everything it made.

    python3 tools/mq_replay.py run [--run ID] [--profile build|full] [--cases c01,c05] [--concurrency N] [--resume ID] [--keep] [--detach]
    python3 tools/mq_replay.py report [--run ID]
    python3 tools/mq_replay.py clean (--run ID | --older-than 1d) [--dry-run]

Stdlib only. The queue side is salamander's replay support (docs/mq.md "Replay"): a host key `replay = "/abs/path/replay.json"` makes a queue instance take its rules and the facts
of each PR from that file, so a PR that is long merged can join, and mode is shadow only (nothing is merged, no status, no comment). This tool is the driver around it.

Per case (one thread, up to --concurrency at a time):
  1. push the practice base, `git push <remote> <base sha>:refs/heads/practice/<run>/<case>` (the commit is on the remote already; the PR's own changes are not in it)
  2. write replay.json and the host file in a folder of the case (XDG_STATE_HOME and XDG_CONFIG_HOME point there, so the queue's state, locks and clone are the case's own and the real
     queue's folder is never opened), `salamander mq add <PRs>` and `salamander mq wait <PR>` for each
  3. compare the verdict with the known outcome (match rules below)
  4. in a `finally`, whatever happened: cancel its own CI runs if it did not finish, drop the PRs, wait for the case's driver unit to leave, delete
     `queue/practice/<run>/<case>/*` and `practice/<run>/<case>` with `git push --delete` (git only, no REST), remove the case's folder and clone (--keep keeps them)

Profiles: build = `ci = "skip"` for the cases it runs (a group is built and not pushed, no CI: `mq wait` exits 4, and the tree is checked offline at phase `built`), all cases;
full = `ci = "real"` for the cases that need CI (a merged PR or a group: c01 to c13), the refused ones having shown their refusal in the build profile.

Match rules (the report's `match` column):
  merged PR            real CI: `mq wait` exit 3 (its entry passed); build: exit 4. Where the case records M's tree (a single merged PR) the group head's tree, read in the case's clone, equals it.
  refused PR           exit 1, state ejected, with the same words: `refused: a check failed:` with the same check names, or `refused: conflicts with main` with the same files.
  fails-alone expectation (a PR whose case `expect` field starts with `fails alone`: the old path refused it among others and CI decides) real CI: exit 1 and state failed (the chain drops it on its own,
                       and the entries behind it are rebuilt on the one ahead) while the other PRs of the case pass; build: exit 4 like the others (a failure needs CI).
A row that does not match says which side to look at: the queue, the fixture (the case's recorded facts) or the old path.

The idle gate (the box's CI pool is shared with releases): the run starts only when no `stackshot-release-*.service` user unit is active, the release queue file
(`queue` in the release folder, where release.sh keeps it) is empty and no group of the real merge queue is in flight; it asks again before each case and each poll of a wait. When a release appears it stops starting cases, cancels its own
running CI, drops its PRs, cleans up, marks the case `interrupted` and ends with exit 75; `run --resume ID` runs the cases that are not done. No lock is taken, so a release never waits for a replay.

Safety: every ref this tool pushes or deletes must match ^refs/heads/(queue/)?practice/ (checked in one place, `check_ref`, before any git call); it never pushes `main`, a PR
branch or a tag, never uses the REST API for refs, and never opens the real queue's state folder (the real queue is only asked through `salamander mq status`).

State: `${XDG_STATE_HOME:-~/.local/state}/stackshot/mq-replay/<run>/` holds run.json (the cases and their rows), report.md, run.log and run.lock (flock while a run is alive); the case
folders are under cases/ and gone when each case ends. Exit: 0 every row matches, 1 a row does not match or a case failed, 75 interrupted by a release (resume), 2 usage, 143 SIGTERM.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = ("run", "report", "clean")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
REF_RE = re.compile(r"refs/heads/(?:queue/)?practice/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
SHA_RE = re.compile(r"[0-9a-f]{40}")
RUNID_RE = re.compile(r"(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z")
ZONE = dt.timezone.utc
EXIT_INTERRUPTED = 75
EXIT_WAIT = {"skipped": 4, "tested": 3}
LIVE_PHASES = ("building", "built", "pushed", "testing", "verdict", "merging", "cleaning")      # every phase of a group of the real queue but `done` (salamander lib/mq/mq_state.py PHASES): it uses, or is about to use, the CI pool or the branches
RULE_KEYS = ("required", "pr_required", "suites", "inflight_max", "on_conflict", "conflict_paths", "flaky", "fast_allow", "queue_mode")
CASE_STATES_UNFINISHED = ("pending", "running", "interrupted", "error")
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


class RefGuardError(Exception):
    """a ref this tool would push or delete is not a practice ref"""


class Interrupted(Exception):
    """a release appeared, or the process was asked to end: the case stops, cleans up and stays resumable"""


class CaseError(Exception):
    """a case that cannot give a verdict (the queue would not start, a command failed)"""


def check_ref(ref: str) -> str:
    """the one guard in front of every push and delete: only refs/heads/practice/... and refs/heads/queue/practice/..."""
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref) or any(s.startswith(".") or s.endswith(".lock") for s in ref.split("/")):
        raise RefGuardError(f"refusing to touch {ref!r}: only refs/heads/practice/... and refs/heads/queue/practice/... may be pushed or deleted")
    return ref


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def stamp(epoch: float | None) -> str:
    if not epoch:
        return "-"
    d = dt.datetime.fromtimestamp(epoch, ZONE)
    return f"{d:%a %b} {ordinal(d.day)} {d:%H:%M} UTC"


def run(cmd, *, env=None, cwd=None, timeout=120, input=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout, input=input)


def state_root(override: str | None = None) -> Path:
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "stackshot" / "mq-replay"


def default_logdir() -> Path:
    """the release folder where release.sh keeps its queue file: `python3 config.py state releases` (release.sh's own call; the instance config decides), else the shipped default"""
    try:
        r = run([sys.executable, str(ROOT / "config.py"), "state", "releases"], cwd=str(ROOT), timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(os.path.expanduser("~")) / ".local" / "state" / "stackshot" / "releases"


def real_config_home() -> Path:
    """the config folder of this process's own environment, never a case's"""
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"))


def gh_config_dir() -> Path:
    return Path(os.environ["GH_CONFIG_DIR"]) if os.environ.get("GH_CONFIG_DIR") else real_config_home() / "gh"


def write_json_atomic(path: Path, data) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def run_started_at(root: Path, run_id: str) -> float | None:
    """when a run began: its run.json, else the time its id spells (YYYYMMDDTHHMMSSZ); None when neither says"""
    try:
        return float(json.loads((root / run_id / "run.json").read_text())["started"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    m = RUNID_RE.fullmatch(run_id)
    if m:
        try:
            return dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            return None
    return None


def unit_name(slug: str, rid: str, cid: str) -> str:
    """the driver unit `salamander mq add` starts for one case"""
    return f"mq-{slug.replace('/', '__')}-{rid}-{cid}.service"


def case_of_ref(ref: str) -> str | None:
    m = re.fullmatch(r"refs/heads/(?:queue/)?practice/([^/]+)/([^/]+)(?:/.*)?", ref)
    return m.group(2) if m else None


def run_of_ref(ref: str) -> str | None:
    m = re.fullmatch(r"refs/heads/(?:queue/)?practice/([^/]+)(?:/.*)?", ref)
    return m.group(1) if m else None


def parse_age(text: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhdw])", text.strip())
    if not m:
        raise SystemExit(f"mq_replay: --older-than wants a number and s, m, h, d or w (for example 1d), not {text!r}")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]


# ---------------------------------------------------------------- the remote: pushes and deletes, guarded

class Remote:
    """git against the origin the replay uses. Pushes and deletes go through here only, and `check_ref` runs before git does. The pushes come from a scratch bare repository that
    borrows the checkout's objects (alternates), so the checkout itself gets no remote-tracking ref and no object from this tool."""

    def __init__(self, url: str, workdir: Path, objects_from: str | None = None):
        self.url = url
        self.work = Path(workdir)
        self.lock = threading.Lock()
        if not self.work.exists():
            subprocess.run(["git", "init", "--bare", "--quiet", str(self.work)], check=True, capture_output=True, env=GIT_ENV)
        if objects_from:
            r = run(["git", "-C", objects_from, "rev-parse", "--path-format=absolute", "--git-path", "objects"], env=GIT_ENV)
            if r.returncode == 0 and r.stdout.strip():
                info = self.work / "objects" / "info"
                info.mkdir(parents=True, exist_ok=True)
                (info / "alternates").write_text(r.stdout.strip() + "\n")

    def git(self, *args, timeout=300) -> subprocess.CompletedProcess:
        return run(["git", "-C", str(self.work), *args], env=GIT_ENV, timeout=timeout)

    def ls_heads(self) -> dict[str, str]:
        r = run(["git", "ls-remote", "--heads", self.url], env=GIT_ENV, timeout=120)
        if r.returncode != 0:
            raise CaseError(f"git ls-remote failed: {(r.stderr or r.stdout).strip()[-200:]}")
        out = {}
        for ln in r.stdout.splitlines():
            sha, _, ref = ln.partition("\t")
            if ref:
                out[ref] = sha
        return out

    def practice_refs(self, run_id: str | None = None, case: str | None = None) -> list[str]:
        """the remote's practice refs (of one run, of one case)"""
        out = []
        for ref in sorted(self.ls_heads()):
            m = re.fullmatch(r"refs/heads/(?:queue/)?practice/([^/]+)(?:/([^/]+))?(?:/.*)?", ref)      # [queue/]practice/<run>/<case>/...
            if not m or not REF_RE.fullmatch(ref):
                continue
            if (run_id is not None and m.group(1) != run_id) or (case is not None and m.group(2) != case):
                continue
            out.append(ref)
        return out

    def create(self, sha: str, ref: str) -> None:
        check_ref(ref)
        if not SHA_RE.fullmatch(sha):
            raise CaseError(f"{sha!r} is not a full sha")
        with self.lock:
            if self.git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:      # not in the checkout: ask the remote for it by itself
                f = self.git("fetch", "--quiet", "--no-tags", self.url, sha)
                if f.returncode != 0:
                    raise CaseError(f"{sha[:7]} is in neither the checkout nor the remote ({f.stderr.strip()[-160:]})")
            r = self.git("push", "--quiet", self.url, f"{sha}:{ref}")
        if r.returncode != 0:
            raise CaseError(f"git push of {sha[:7]} to {ref} failed: {(r.stderr or r.stdout).strip()[-200:]}")

    def delete(self, refs: list[str]) -> list[str]:
        """delete refs that exist (git push --delete); → the ones still there afterwards"""
        for ref in refs:
            check_ref(ref)
        if not refs:
            return []
        have = set(self.ls_heads())
        todo = [r for r in refs if r in have]
        for i in range(0, len(todo), 20):
            r = self.git("push", "--quiet", self.url, "--delete", *todo[i:i + 20])
            if r.returncode != 0:
                for one in todo[i:i + 20]:       # one bad ref must not keep the others
                    self.git("push", "--quiet", self.url, "--delete", one)
        left = set(self.ls_heads())
        return [r for r in refs if r in left]


# ---------------------------------------------------------------- the idle gate

class Gate:
    """is the box free of releases? The three signals of the design, all local reads: a running release unit, the release queue file, a real merge-queue group in flight."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = threading.Lock()
        self.stamp = 0.0
        self.cached: list[str] = []

    def raw(self) -> list[str]:
        c, why = self.ctx, []
        try:
            r = run([c.systemctl, "--user", "list-units", "--no-legend", "--plain", "--state=active,activating,reloading", "stackshot-release-*.service"], timeout=30)
            if r.returncode != 0:
                why.append(f"systemctl list-units failed (exit {r.returncode}): cannot tell whether a release is going")
            else:
                for ln in r.stdout.splitlines():
                    f = [x for x in ln.split() if x not in ("●", "*")]
                    if f and f[0].startswith("stackshot-release-") and f[0].endswith(".service"):
                        why.append(f"release unit {f[0]} is running")
        except (OSError, subprocess.TimeoutExpired) as e:
            why.append(f"systemctl is not usable ({type(e).__name__}): cannot tell whether a release is going")
        qf = c.logdir / "queue"
        try:
            lines = [x.strip() for x in qf.read_text().splitlines() if x.strip()]
            if lines:
                why.append(f"the release queue holds {len(lines)} PR(s): {', '.join(lines[:6])}")
        except FileNotFoundError:
            pass
        except OSError as e:
            why.append(f"the release queue file {qf} cannot be read ({type(e).__name__})")
        try:
            r = run([c.salamander, "mq", "status", "--json", "--repo", c.slug], timeout=60)          # this process's own environment: the real queue's folder, read, never written
            if r.returncode != 0:
                why.append(f"`salamander mq status` failed (exit {r.returncode}): cannot tell whether the real merge queue is testing")
            else:
                try:
                    groups = json.loads(r.stdout).get("groups") or []
                except ValueError:
                    groups = None
                if groups is None:
                    why.append("`salamander mq status --json` did not answer JSON: cannot tell whether the real merge queue is testing")
                else:
                    live = [g.get("id", "?") for g in groups if isinstance(g, dict) and g.get("phase") in LIVE_PHASES]
                    if live:
                        why.append(f"the real merge queue has group(s) in flight: {', '.join(live)}")
        except FileNotFoundError:
            pass                         # no salamander here: there is no real queue to ask
        except (OSError, subprocess.TimeoutExpired) as e:
            why.append(f"`salamander mq status` is not usable ({type(e).__name__})")
        return why

    def busy(self) -> list[str]:
        with self.lock:
            if time.time() - self.stamp >= max(0.05, self.ctx.gate_poll / 2):
                self.cached, self.stamp = self.raw(), time.time()
            return list(self.cached)


# ---------------------------------------------------------------- the verdict

def fail_alone_expected(case: dict, p: dict) -> bool:
    """a PR the old path refused among others and whose failure the queue is to find on its own: the case's own `expect` field says so (`fails alone: ...`)"""
    return str(p.get("expect") or "").strip().lower().startswith("fails alone")


def needs_ci(case: dict) -> bool:
    return any(p.get("known_outcome") == "merged" for p in case["prs"]) or case.get("kind") == "group"


def check_names(text: str) -> set[str]:
    return set(re.findall(r"([^\s,=:()]+)=(?:pass|fail|pending|cancel)", text.partition("a check failed:")[2]))


def conflict_files(text: str) -> set[str]:
    m = re.search(r"conflicts with main \(([^)]*)\)", text)
    return {x.strip() for x in m.group(1).split(",") if x.strip()} if m else set()


def reason_matches(expected: str, actual: str) -> tuple[bool, str]:
    if "a check failed:" in expected:
        if "a check failed:" not in actual:
            return False, "the queue's words are not a check failure"
        want, got = check_names(expected), check_names(actual)
        return want == got, f"check names expected {sorted(want)}, got {sorted(got)}"
    if "conflicts with main" in expected:
        if "conflicts with main" not in actual:
            return False, "the queue's words are not a conflict with main"
        want, got = conflict_files(expected), conflict_files(actual)
        if want and want != got:
            return False, f"conflict files expected {sorted(want)}, got {sorted(got)}"
        return True, ""
    return expected.strip() == actual.strip(), "the words differ"


def judge_pr(case: dict, p: dict, r: dict, ci_skip: bool) -> tuple[bool, str, str]:
    """→ (match, what was expected, which side to look at when it does not match)"""
    ex, state, reason = r.get("exit"), r.get("state") or "", r.get("reason") or r.get("text") or ""
    if ex is None or ex == 2:
        return False, "a verdict", f"look at the queue: no verdict ({reason[:100] or 'gave up or blocked'}); rerun the case with --resume"
    if fail_alone_expected(case, p):
        if ci_skip:
            ok = ex == 4
            return ok, "exit 4 (built, no CI: a failure needs CI)", "" if ok else f"look at the queue: expected exit 4 in the build profile, got exit {ex} ({reason[:100]})"
        ok = ex == 1 and state == "failed"
        side = ""
        if not ok:
            side = ("look at CI or the fixture: the PR's entry passed although the PR is known to fail (its fixture leaves the check out so CI decides)" if ex in (3, 4) else
                    f"look at the queue: expected the chain to drop it as failed on its own, got exit {ex} {state} ({reason[:100]})")
        return ok, "exit 1, failed (dropped on its own by the chain)", side
    if p["known_outcome"] == "merged":
        want = 4 if ci_skip else 3
        if ex != want:
            if state == "failed" or (ex == 1 and "failed" in reason):
                side = f"look at CI: the PR's entry failed ({reason[:100]}); compare the run {r.get('link') or ''} with the old path's main run"
            elif ex == 1 and re.search(r"cannot be fetched|not found|head moved|closed|draft", reason):
                side = f"look at the fixture: the recorded facts do not hold ({reason[:100]})"
            elif ex == 1 and "conflicts with main" in reason:
                side = "look at the queue's merge against the old path's: the PR merged clean there (or its on_conflict hook mended it) and conflicts here"
            elif ex == 1:
                side = f"look at the queue: it refused a PR the old path merged ({reason[:100]})"
            else:
                side = f"look at the queue: expected exit {want}, got exit {ex}"
            return False, f"exit {want}", side
        exp_tree = case.get("expected_tree") if len(case["prs"]) == 1 else None
        if exp_tree:
            got = r.get("tree")
            if got != exp_tree:
                return False, f"exit {want} and the group tree = M's tree", (
                    "look at the queue or its on_conflict hook: the group's tree differs from the old merge's"
                    + (" (the case replays the queue-time head, so the hook has to mend the conflict)" if p.get("head_mode") == "queue" else "")
                    + (f"; group tree {got[:7] if got else 'not readable'}, M's {exp_tree[:7]}"))
        return True, f"exit {want}" + (" and the tree = M's" if exp_tree else ""), ""
    # refused
    if ex in (3, 4):
        return False, "refused (exit 1)", "look at the old path or the fixture: the queue accepted a PR the old path refused (are the recorded checks right? is the base right?)"
    if ex != 1 or state not in ("ejected", "failed", "dropped"):
        return False, "refused (exit 1)", f"look at the queue: expected a refusal, got exit {ex} {state}"
    ok, detail = reason_matches(p.get("expected_reason", ""), reason)
    return ok, f"exit 1: {p.get('expected_reason', '?')}", "" if ok else f"look at the queue's words or the fixture: {detail} ({reason[:110]})"


def judge_case(case: dict, ci: str, results: dict) -> tuple[bool, list[str], list[str]]:
    ok_all, parts, notes = True, [], []
    for p in case["prs"]:
        r = results.get(p["pr"]) or {"exit": None}
        ok, expected, side = judge_pr(case, p, r, ci == "skip")
        ok_all &= ok
        state = r.get("state") or "?"
        parts.append(f"#{p['pr']} exit {r.get('exit')} {state}" + (f" [{r['group']}]" if r.get("group") else "") + ("" if r.get("exit") in (3, 4) else f": {(r.get('reason') or r.get('text') or '')[:90]}"))
        if side:
            notes.append(f"#{p['pr']}: {side}")
        elif ok and r.get("tree") and case.get("expected_tree") and len(case["prs"]) == 1:
            notes.append("group tree = M's tree")
        if p.get("head_mode") == "queue":
            notes.append(f"#{p['pr']}: replays the queue-time head")
    return ok_all, parts, notes


# ---------------------------------------------------------------- the report

def cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_report(st: dict) -> str:
    rows, order = st["cases"], st["order"]
    out = [f"# mq replay `{st['run']}`", "",
           f"profile **{st['profile']}** · repo `{st['slug']}` · started {stamp(st.get('started'))}" + (f" · ended {stamp(st['ended'])}" if st.get("ended") else " · not finished"), ""]
    if st.get("stopped"):
        out += [f"**stopped:** {st['stopped']}", ""]
    out += ["| case | PR(s) | head -> base | known outcome (old path) | queue verdict | match | note |", "|---|---|---|---|---|---|---|"]
    counts = {"yes": 0, "NO": 0, "other": 0}
    for cid in order:
        c = rows[cid]
        row = c.get("row")
        status = c["status"]
        if status == "done" and row:
            match = row["match"]
            counts["yes" if match == "yes" else "NO"] += 1
            out.append("| " + " | ".join(cell(x) for x in (cid, row["prs"], row["head_base"], row["known"], row["verdict"], match, row["note"])) + " |")
        else:
            counts["other"] += 1
            meta = c.get("meta") or {}
            out.append("| " + " | ".join(cell(x) for x in (cid, meta.get("prs", ""), meta.get("head_base", ""), meta.get("known", ""), c.get("error") or "not run yet",
                                                         status.upper(), "; ".join(c.get("cleanup_problems") or []) or ("resume with --resume " + st["run"] if status != "error" else "look at run.log"))) + " |")
    out += ["", f"{counts['yes']} of {len(order)} rows match, {counts['NO']} do not, {counts['other']} without a verdict (interrupted, failed or not run)."]
    bad = [cid for cid in order if rows[cid]["status"] == "done" and (rows[cid].get("row") or {}).get("match") != "yes"]
    if bad:
        out += ["", "A `NO` row needs a line saying whether the queue, the fixture or the old path was wrong, and the fix: " + ", ".join(bad) + "."]
    left = [cid for cid in order if rows[cid].get("cleanup_problems")]
    if left:
        out += ["", "**Leftovers:** " + "; ".join(f"{cid}: {', '.join(rows[cid]['cleanup_problems'])}" for cid in left) + f" (`mq_replay.py clean --run {st['run']}`)"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- one run

class Ctx:
    """what the commands share: the remote, the repository's identity, the tools, the folders"""

    def __init__(self, a, root: Path, run_id: str, opts: dict):
        self.run_id, self.root, self.opts = run_id, root, opts
        self.rundir = root / run_id
        self.remote_url, self.slug, self.repo = opts["remote"], opts["slug"], opts["repo"]
        self.owner = self.slug.split("/")[0]
        self.salamander = a.salamander
        self.systemctl, self.gh = a.systemctl, a.gh
        self.logdir = Path(a.logdir) if a.logdir else default_logdir()
        self.gate_poll, self.gate_cap = a.gate_poll, a.gate_cap
        self.case_timeout, self.driver_wait = a.case_timeout, a.driver_wait
        self.settle = a.settle
        self.keep, self.concurrency = a.keep, max(1, a.concurrency)


def derive_slug(remote: str, given: str | None) -> str:
    if given:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", given):
            raise SystemExit(f"mq_replay: --slug wants OWNER/NAME, not {given!r}")
        return given
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", remote or "")
    if not m:
        raise SystemExit(f"mq_replay: cannot derive the repository's owner and name from the remote {remote!r}: pass --slug OWNER/NAME (the owner fills the PRs that record none)")
    return f"{m.group(1)}/{m.group(2)}"


def load_rules(repo: str, ref: str) -> tuple[dict, str]:
    r = run(["git", "-C", repo, "show", f"{ref}:.github/mergequeue.toml"], env=GIT_ENV)
    if r.returncode != 0:
        return {}, f"no .github/mergequeue.toml at {ref} in {repo}: the queue's defaults are used"
    try:
        data = tomllib.loads(r.stdout)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"mq_replay: .github/mergequeue.toml at {ref} is not TOML ({e})")
    return {k: data[k] for k in RULE_KEYS if k in data}, f"rules from {ref}:.github/mergequeue.toml"


class StopFlag:
    """the run's stop request. set() is one attribute assignment, so a signal handler on the main thread can raise it at any point (an Event's set() takes an internal lock that the
    thread's own wait() may hold); waiting is a short-sleep poll"""

    def __init__(self):
        self._on = False

    def is_set(self) -> bool:
        return self._on

    def set(self) -> None:
        self._on = True

    def wait(self, timeout: float) -> bool:
        end = time.time() + timeout
        while not self._on and time.time() < end:
            time.sleep(max(0.0, min(0.1, end - time.time())))
        return self._on


class Replay:
    def __init__(self, a, ctx: Ctx, cases: list[dict], st: dict, fresh: bool):
        self.a, self.ctx, self.cases, self.st = a, ctx, {c["id"]: c for c in cases}, st
        self.profile = st["profile"]
        self.lock = threading.RLock()
        self.stop = StopFlag()
        self.stop_reason = ""
        self.stop_kind = ""
        self.gate = Gate(ctx)
        self.remote = Remote(ctx.remote_url, ctx.rundir / "push.git", ctx.repo)
        self.logf = (ctx.rundir / "run.log").open("a")

    # -- small things
    def say(self, msg: str) -> None:
        line = f"mq_replay: {msg}"
        print(line, file=sys.stderr, flush=True)
        with self.lock:
            self.logf.write(f"{stamp(time.time())} {msg}\n")
            self.logf.flush()

    def save(self) -> None:
        with self.lock:
            write_json_atomic(self.ctx.rundir / "run.json", self.st)
            (self.ctx.rundir / "report.md").write_text(render_report(self.st))

    def trip(self, kind: str, why: str) -> None:
        with self.lock:
            if self.stop.is_set():
                return
            self.stop_kind, self.stop_reason = kind, why
            self.stop.set()
        self.say(f"stopping: {why}")

    def request_stop(self, kind: str, why: str) -> None:
        """for the signal handlers: sets the stop and nothing else (no lock, no file write: the handler runs on the main thread, possibly inside its own save() or say()); the cases
        say it when they notice"""
        if not self.stop.is_set():
            self.stop_kind, self.stop_reason = kind, why
            self.stop.set()

    def check_interrupt(self) -> None:
        if not self.stop.is_set():
            busy = self.gate.busy()
            if busy:
                self.trip("release", busy[0])
        if self.stop.is_set():
            raise Interrupted(self.stop_reason)

    def ci_for(self, case: dict) -> str:
        return "skip" if self.profile == "build" or not needs_ci(case) else "real"

    # -- the idle gate at the start
    def wait_idle(self) -> bool:
        t0, last = time.time(), None
        while True:
            busy = self.gate.busy()
            if not busy:
                return True
            if busy != last:
                self.say("waiting for the box to be idle: " + "; ".join(busy))
                last = busy
            if self.stop.is_set() or time.time() - t0 >= self.ctx.gate_cap:
                return False
            self.stop.wait(self.ctx.gate_poll)

    # -- files of a case
    def case_dir(self, cid: str) -> Path:
        return self.ctx.rundir / "cases" / cid

    def refs_of(self, cid: str) -> tuple[str, str]:
        return f"refs/heads/practice/{self.ctx.run_id}/{cid}", f"refs/heads/queue/practice/{self.ctx.run_id}/{cid}/"

    def replay_doc(self, case: dict) -> dict:
        return build_replay_doc(case, self.ctx.run_id, self.ci_for(case), self.ctx.owner, self.st["rules"])

    def write_case_files(self, case: dict, cdir: Path) -> None:
        (cdir / "state").mkdir(parents=True)
        cfg = cdir / "config" / "mergequeue"
        cfg.mkdir(parents=True)
        rp = cdir / "replay.json"
        rp.write_text(json.dumps(self.replay_doc(case), indent=1, sort_keys=True) + "\n")
        q = lambda s: json.dumps(str(s))          # a TOML basic string for a plain path
        (cfg / f"{self.ctx.slug.replace('/', '__')}.toml").write_text(
            f'mode = "shadow"\nremote = {q(self.ctx.remote_url)}\nclone = {q(cdir / "clone")}\nreplay = {q(rp)}\n')
        real_state = Path(os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")) / "salamander"
        if real_state.is_dir():              # the CI-run poller's files (read only): a wait on a running group then costs no GitHub call
            (cdir / "state" / "salamander").symlink_to(real_state)
        for name, real in (("gh", gh_config_dir()), ("git", real_config_home() / "git")):
            if real.is_dir():                # the case's XDG_CONFIG_HOME hides these from the queue's driver (gh is logged in through hosts.yml there): link the real ones, read only
                (cdir / "config" / name).symlink_to(real)
            elif name == "gh" and not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
                self.say(f"warning: no gh config folder at {real} and no GH_TOKEN: the queue's driver cannot call GitHub")

    def env_of(self, cdir: Path) -> dict:
        return {**os.environ, "XDG_STATE_HOME": str(cdir / "state"), "XDG_CONFIG_HOME": str(cdir / "config")}

    def unit_of(self, cid: str) -> str:
        return unit_name(self.ctx.slug, self.ctx.run_id, cid)

    def mq(self, cdir: Path, *args, timeout=120) -> subprocess.CompletedProcess:
        return run([self.ctx.salamander, "mq", *args, "--repo", self.ctx.slug], env=self.env_of(cdir), timeout=timeout)

    # -- reading what the queue did
    def queue_dir(self, cdir: Path) -> Path:
        return cdir / "state" / "mergequeue" / self.ctx.slug.replace("/", "__")

    def read_state(self, cdir: Path) -> tuple[dict, dict]:
        qd = self.queue_dir(cdir)
        try:
            q = json.loads((qd / "queue.json").read_text())
        except (OSError, ValueError):
            q = {"entries": []}
        groups = {}
        for f in sorted((qd / "groups").glob("g*.json")) if (qd / "groups").is_dir() else []:
            try:
                g = json.loads(f.read_text())
                groups[g["id"]] = g
            except (OSError, ValueError, KeyError):
                pass
        return q, groups

    def inflight_runs(self, cdir: Path) -> list[str]:
        ids = []
        _, groups = self.read_state(cdir)
        for g in groups.values():
            if g.get("phase") in ("pushed", "testing") and not g.get("verdict"):
                run_ = g.get("run") or {}
                rid = run_.get("id") or (re.search(r"/actions/runs/(\d+)", run_.get("url") or "") or [None, None])[1]
                if rid:
                    ids.append(str(rid))
                else:
                    r = run([self.ctx.gh, "run", "list", "-R", self.ctx.slug, "--branch", g["branch"], "--json", "databaseId,status", "--jq",
                             '.[] | select(.status != "completed") | .databaseId'], timeout=60)
                    ids += r.stdout.split() if r.returncode == 0 else []
        return sorted(set(ids))

    def cancel_runs(self, cdir: Path) -> list[str]:
        done = []
        try:
            for rid in self.inflight_runs(cdir):
                r = run([self.ctx.gh, "run", "cancel", rid, "-R", self.ctx.slug], timeout=60)
                self.say(f"gh run cancel {rid}: " + ("done" if r.returncode == 0 else f"exit {r.returncode} {r.stderr.strip()[-100:]}"))
                done.append(rid)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.say(f"cancelling runs failed ({type(e).__name__})")
        return done

    def cancel_branch_runs(self, cid: str, cdir: Path) -> list[str]:
        """cancel the unfinished runs of this case's own queue branches (queue/practice/<run>/<case>/..., from the group records and from the remote), nothing else. GitHub registers a
        run a few seconds after the push: when nothing is found for a branch that was pushed, look once more after `--settle` seconds"""
        qpre = self.refs_of(cid)[1][len("refs/heads/"):]
        _, groups = self.read_state(cdir)
        branches = {g["branch"] for g in groups.values() if isinstance(g.get("branch"), str)}
        branches |= {r[len("refs/heads/"):] for r in self.remote.practice_refs(self.ctx.run_id, cid) if r.startswith("refs/heads/" + qpre)}
        branches = sorted(x for x in branches if x.startswith(qpre))
        done = []
        for attempt in range(2):
            for b in branches:
                r = run([self.ctx.gh, "run", "list", "-R", self.ctx.slug, "--branch", b, "--json", "databaseId,status", "--jq", '.[] | select(.status != "completed") | .databaseId'], timeout=60)
                for rid in (r.stdout.split() if r.returncode == 0 else []):
                    c = run([self.ctx.gh, "run", "cancel", rid, "-R", self.ctx.slug], timeout=60)
                    self.say(f"gh run cancel {rid} ({b}): " + ("done" if c.returncode == 0 else f"exit {c.returncode} {c.stderr.strip()[-100:]}"))
                    done.append(rid)
            settle = getattr(self.ctx, "settle", 0)
            if done or attempt or not branches or settle <= 0:
                break
            time.sleep(settle)
        return done

    # -- waiting
    def wait_pr(self, cdir: Path, pr: int, deadline: float) -> dict:
        cmd = [self.ctx.salamander, "mq", "wait", str(pr), "--timeout", str(max(1, int(deadline - time.time()))), "--repo", self.ctx.slug]
        p = subprocess.Popen(cmd, env=self.env_of(cdir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                try:
                    out, err = p.communicate(timeout=min(self.ctx.gate_poll, 2.0))      # short slices: a SIGTERM is noticed within seconds, the gate is read from its cache
                    break
                except subprocess.TimeoutExpired:
                    self.check_interrupt()
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        if p.returncode is not None and p.returncode < 0:
            # `systemctl stop` and Ctrl-C reach the waiting child together with this process; the handler may not have run yet. Not a verdict either way.
            self.stop.wait(2.0)
            self.check_interrupt()
            raise Interrupted(f"salamander mq wait was ended by signal {-p.returncode}")
        return {"exit": p.returncode, "text": (out or err or "").strip().splitlines()[0] if (out or err) else ""}

    def details(self, case: dict, cdir: Path, results: dict, t_add: float) -> None:
        q, groups = self.read_state(cdir)
        for p in case["prs"]:
            r = results[p["pr"]]
            e = next((x for x in reversed(q.get("entries") or []) if x.get("pr") == p["pr"]), None)
            if e:
                r.update(state=e.get("state"), reason=e.get("reason") or "", group=e.get("group"))
                if e.get("ended") and e.get("added"):
                    r["seconds"] = max(0, int(e["ended"]) - int(e["added"]))
                g = groups.get(e.get("group") or "")
                if g:
                    r["group_head"] = g.get("head")
                    run_ = g.get("run") or {}
                    r["link"] = (g.get("verdict") or {}).get("run_url") or run_.get("url") or ""
                    if g.get("pushed_at") and (g.get("verdict") or {}).get("at"):
                        r["seconds"] = max(0, int(g["verdict"]["at"]) - int(g["pushed_at"]))
                    if case.get("expected_tree") and len(case["prs"]) == 1 and g.get("head"):
                        t = run(["git", "-C", str(cdir / "clone"), "rev-parse", f"{g['head']}^{{tree}}"], env=GIT_ENV)
                        r["tree"] = t.stdout.strip() if t.returncode == 0 else None
            r.setdefault("seconds", int(time.time() - t_add))

    # -- one case
    def sweep(self, cid: str) -> list[str]:
        """delete this case's refs on the remote; → the ones that stay"""
        base, qpre = self.refs_of(cid)
        refs = [r for r in self.remote.practice_refs(self.ctx.run_id, cid) if r == base or r.startswith(qpre)]
        return self.remote.delete(refs)

    def cleanup(self, case: dict, cdir: Path, cancel: bool) -> list[str]:
        cid, problems = case["id"], []

        def step(name, fn):
            try:
                fn()
            except (Exception, subprocess.TimeoutExpired) as e:
                problems.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
        if cancel:
            step("cancel runs", lambda: self.cancel_runs(cdir))

        def drop():
            q, _ = self.read_state(cdir)
            for e in q.get("entries") or []:
                if e.get("state") in ("waiting", "grouped"):
                    self.mq(cdir, "drop", str(e["pr"]))
        step("drop", drop)

        def driver_gone():
            unit, end = self.unit_of(cid), time.time() + self.ctx.driver_wait
            while time.time() < end:
                r = run([self.ctx.systemctl, "--user", "is-active", unit], timeout=20)
                if r.stdout.strip() not in ("active", "activating", "reloading"):
                    return
                time.sleep(min(0.5, max(0.05, self.ctx.gate_poll)))
            self.say(f"{unit} is still running after {self.ctx.driver_wait:g}s: stopping it")
            run([self.ctx.systemctl, "--user", "stop", unit], timeout=60)
            time.sleep(0.2)
        step("driver", driver_gone)
        if cancel:                       # a driver that was still building when the first cancel ran can push its group, and start a run, after it: look again, by branch, now that it is gone
            step("cancel runs of the case's branches", lambda: self.cancel_branch_runs(cid, cdir))

        def refs():
            left = self.sweep(cid)
            if left:
                problems.append("refs left on the remote: " + ", ".join(left))
        step("delete refs", refs)

        def folder():
            if self.ctx.keep:
                self.say(f"--keep: {cdir} stays")
            elif cdir.exists():
                for link in [x for x in list(cdir.glob("state/*")) + list(cdir.glob("config/*")) if x.is_symlink()]:
                    link.unlink()                # the links to the real gh config and poller folders: removed as links, nothing behind them is touched
                shutil.rmtree(cdir)
        step("remove folder", folder)
        return problems

    def run_case(self, cid: str) -> None:
        case, c = self.cases[cid], self.st["cases"][cid]
        cdir = self.case_dir(cid)
        status, err, row, fd, t0 = "error", None, None, -1, time.time()
        with self.lock:
            c["status"], c["started"], c["error"] = "running", t0, None
            c["attempts"] = c.get("attempts", 0) + 1
        self.save()
        try:
            self.say(f"{cid}: start ({self.ci_for(case)} CI, PR(s) {', '.join('#%d' % p['pr'] for p in case['prs'])})")
            left = self.sweep(cid)               # what an earlier attempt of this case left behind (a killed run)
            if left:
                raise CaseError("refs of an earlier attempt cannot be deleted: " + ", ".join(left))
            if cdir.exists():
                shutil.rmtree(cdir)
            cdir.mkdir(parents=True)
            fd = os.open(cdir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            fcntl.flock(fd, fcntl.LOCK_SH)           # a running case's folder is locked (an ageing sweep of temp folders skips it)
            self.check_interrupt()
            self.write_case_files(case, cdir)
            self.remote.create(case["base"], self.refs_of(cid)[0])
            prs = [p["pr"] for p in case["prs"]]
            t_add = time.time()
            r = self.mq(cdir, "add", *map(str, prs))
            if r.returncode != 0:
                raise CaseError(f"salamander mq add exited {r.returncode}: {(r.stderr or r.stdout).strip()[-200:]}")
            deadline = t_add + self.ctx.case_timeout
            results = {}
            for pr in prs:
                results[pr] = self.wait_pr(cdir, pr, deadline)
                self.check_interrupt()               # a stop that arrived while the wait ended is no verdict
            self.details(case, cdir, results, t_add)
            ok, parts, notes = judge_case(case, self.ci_for(case), results)
            row = self.row_of(case, results, ok, parts, notes, t0)
            status = "done"
        except Interrupted as e:
            status, err = "interrupted", str(e)
        except Exception as e:                       # any failure of the case itself: a verdict is not possible, the others go on
            status, err = "error", f"{type(e).__name__}: {str(e)[:300]}"
            self.say(f"{cid}: failed: {err}")
        finally:
            try:
                problems = self.cleanup(case, cdir, cancel=status != "done" or self.stop.is_set())
            finally:
                if fd >= 0:
                    os.close(fd)
            with self.lock:
                c.update(status=status, error=err, row=row, cleanup_problems=problems, ended=time.time())
            self.save()
            self.say(f"{cid}: {status}" + (f" ({err})" if err else "") + (f", match {row['match']}" if row else "") + (f"; cleanup problems: {problems}" if problems else ""))

    def row_of(self, case: dict, results: dict, ok: bool, parts: list, notes: list, t0: float) -> dict:
        prs = case["prs"]
        known = []
        for p in prs:
            if p["known_outcome"] == "merged":
                mr = p.get("main_run") or {}
                known.append(f"#{p['pr']} merged{' ' + p['merge'][:7] if p.get('merge') else ''}" + (f"; main run {mr['run']} {mr.get('result', '')}".rstrip() if mr.get("run") else ""))
            else:
                known.append(f"#{p['pr']} " + (p.get("expected_reason") or "refused") + (" (fails alone expected)" if fail_alone_expected(case, p) else ""))
        mins = max((r.get("seconds") or 0) for r in results.values()) / 60
        links = sorted({r["link"] for r in results.values() if r.get("link")})
        verdict = "; ".join(parts) + f"; {mins:.1f} min" + (f"; {links[0]}" if links else "")
        return {"prs": ", ".join(f"#{p['pr']}" for p in prs), "head_base": head_base(case), "known": "; ".join(known), "verdict": verdict, "match": "yes" if ok else "NO",
                "note": "; ".join(notes), "minutes": round(mins, 1)}


def build_replay_doc(case: dict, run_id: str, ci: str, owner: str, base_rules: dict) -> dict:
    """the replay file of one case (salamander's docs/mq.md "Replay"): the repository's own rules with the practice base and queue branch prefix, run as a chain, the PR facts as the case recorded them;
    a PR that records no owner lives in the repository's own namespace, so the repository's owner fills it"""
    rules = dict(base_rules)
    rules.update(base=f"practice/{run_id}/{case['id']}", queue_prefix=f"queue/practice/{run_id}/{case['id']}/", queue_mode="chain")
    prs = {str(p["pr"]): {"state": "OPEN", "draft": False, "head": p["head"], "branch": p.get("branch") or f"pr-{p['pr']}", "owner": p.get("owner") or owner,
                          "checks": dict(p.get("checks") or {})} for p in case["prs"]}
    return {"version": 1, "run": run_id, "case": case["id"], "ci": ci, "rules": rules, "prs": prs}


def head_base(case: dict) -> str:
    heads = ", ".join(p["head"][:7] for p in case["prs"])
    return f"{heads} -> {case['base'][:7]}"


def meta_of(case: dict) -> dict:
    known = "; ".join(f"#{p['pr']} {p['known_outcome']}" for p in case["prs"])
    return {"prs": ", ".join(f"#{p['pr']}" for p in case["prs"]), "head_base": head_base(case), "known": known}


# ---------------------------------------------------------------- commands

def load_cases(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"mq_replay: cannot read the cases file {path}: {e}")
    if not isinstance(doc, dict) or doc.get("format") != 1 or not isinstance(doc.get("cases"), list):
        raise SystemExit(f"mq_replay: {path} is not a format 1 cases file (run `mq_replay.py build-cases`)")
    for c in doc["cases"]:
        if not isinstance(c.get("id"), str) or not NAME_RE.fullmatch(c["id"]):
            raise SystemExit(f"mq_replay: a case id {c.get('id')!r} in {path} is not usable in a branch name")
        for p in c.get("prs", []):
            if not SHA_RE.fullmatch(str(p.get("head", ""))) or not SHA_RE.fullmatch(str(c.get("base", ""))):
                raise SystemExit(f"mq_replay: {c['id']}: head and base must be full shas")
    return doc["cases"]


def new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def detach(a, run_id: str) -> int:
    root = state_root(a.state_dir)
    argv = [x for x in sys.argv[2:] if x != "--detach"]
    if "--run" not in argv and not any(x.startswith("--run=") for x in argv) and not a.resume:
        argv += ["--run", run_id]
    unit = f"stackshot-mq-replay-{run_id}"
    env = []
    for k in ("PATH", "HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "SSH_AUTH_SOCK", "STACKSHOT_CONFIG", "GH_CONFIG_DIR", "GIT_SSH_COMMAND"):
        if os.environ.get(k):
            env.append(f"--setenv={k}={os.environ[k]}")
    env += [f"--setenv={k}={v}" for k, v in os.environ.items() if k.startswith("MQ_")]
    cmd = ["systemd-run", "--user", "--quiet", "--collect", "--unit", unit, "-p", f"WorkingDirectory={ROOT}", "-p", "TimeoutStopSec=300", *env, "--",
           sys.executable, str(Path(__file__).resolve().parent / "mq_replay.py"), "run", *argv]
    r = run(cmd, timeout=60)
    if r.returncode != 0:
        print(f"mq_replay: could not start {unit} (systemd-run exit {r.returncode}): {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr)
        return 1
    print(f"started {unit} (run {run_id}) · report {root / run_id / 'report.md'} · log {root / run_id / 'run.log'} · systemctl --user status {unit}")
    return 0


def cmd_run(a) -> int:
    root = state_root(a.state_dir)
    resume = a.resume
    if resume and a.run and a.run != resume:
        raise SystemExit("mq_replay: --resume ID and --run ID name different runs")
    run_id = resume or a.run or new_run_id()
    if not NAME_RE.fullmatch(run_id):
        raise SystemExit(f"mq_replay: a run id is [A-Za-z0-9._-] and starts with a letter or digit, not {run_id!r}")
    rundir = root / run_id
    if a.detach:
        return detach(a, run_id)
    if resume and not (rundir / "run.json").is_file():
        raise SystemExit(f"mq_replay: no run {run_id} to resume under {root}")
    if not resume and (rundir / "run.json").exists():
        raise SystemExit(f"mq_replay: run {run_id} exists already (use --resume {run_id}, or another --run)")
    rundir.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(rundir / "run.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f"mq_replay: run {run_id} is running already")
    try:
        return _run_locked(a, root, run_id, resume)
    finally:
        os.close(lock_fd)


def _run_locked(a, root: Path, run_id: str, resume: str | None) -> int:
    rundir = root / run_id
    if resume:
        st = json.loads((rundir / "run.json").read_text())
        opts = st["opts"]
        cases_path = Path(opts["cases_file"])
    else:
        repo = str(Path(a.repo).resolve())
        remote = a.remote or (run(["git", "-C", repo, "remote", "get-url", "origin"], env=GIT_ENV).stdout.strip())
        if not remote:
            raise SystemExit(f"mq_replay: {repo} has no origin remote: pass --remote")
        slug = derive_slug(remote, a.slug)
        cases_path = Path(a.cases_file) if a.cases_file else ROOT / "tests" / "mq_replay" / "cases.json"
        opts = {"repo": repo, "remote": remote, "slug": slug, "cases_file": str(cases_path.resolve())}
    all_cases = load_cases(cases_path)
    by_id = {c["id"]: c for c in all_cases}
    if resume:
        chosen = [cid for cid in st["order"]]
    else:
        want = [x.strip() for x in a.cases.split(",") if x.strip()] if a.cases else None
        if want:
            missing = [x for x in want if x not in by_id]
            if missing:
                raise SystemExit(f"mq_replay: no such case: {', '.join(missing)} (the file has {', '.join(by_id)})")
            chosen = want
        else:
            chosen = [c["id"] for c in all_cases if a.profile == "build" or needs_ci(c)]
        rules, note = load_rules(opts["repo"], a.rules_ref)
        st = {"run": run_id, "profile": a.profile, "started": time.time(), "ended": None, "opts": opts, "slug": opts["slug"], "rules": rules, "rules_note": note,
              "order": chosen, "cases": {cid: {"status": "pending", "attempts": 0, "meta": meta_of(by_id[cid])} for cid in chosen}, "stopped": None}
    ctx = Ctx(a, root, run_id, opts)
    rp = Replay(a, ctx, [by_id[cid] for cid in chosen], st, fresh=not resume)
    st["stopped"] = None
    st["ended"] = None
    rp.save()
    signal.signal(signal.SIGTERM, lambda *_: rp.request_stop("signal", "terminated (SIGTERM)"))
    signal.signal(signal.SIGHUP, lambda *_: rp.request_stop("signal", "terminated (SIGHUP)"))
    signal.signal(signal.SIGINT, lambda *_: rp.request_stop("signal", "interrupted (SIGINT)"))
    todo = [cid for cid in chosen if st["cases"][cid]["status"] in CASE_STATES_UNFINISHED]
    rp.say(f"run {run_id}: profile {st['profile']}, {len(todo)} of {len(chosen)} case(s) to run, {opts['slug']}, {st.get('rules_note', '')}")
    try:
        if todo and not rp.wait_idle():
            if not rp.stop.is_set():
                rp.trip("release", f"the box did not become idle within {ctx.gate_cap:g}s")
        if not rp.stop.is_set():
            with concurrent.futures.ThreadPoolExecutor(max_workers=ctx.concurrency) as pool:
                def work(cid):
                    if rp.stop.is_set():
                        return
                    busy = rp.gate.busy()
                    if busy:
                        rp.trip("release", busy[0])
                        return
                    rp.run_case(cid)
                for f in [pool.submit(work, cid) for cid in todo]:
                    f.result()
    finally:
        if rp.stop.is_set() and rp.stop_kind == "signal":
            rp.say(f"stopping: {rp.stop_reason}")
        left = [cid for cid in chosen if st["cases"][cid]["status"] in CASE_STATES_UNFINISHED]
        with rp.lock:
            st["ended"] = time.time()
            if rp.stop.is_set():
                st["stopped"] = rp.stop_reason
        rp.save()
        shutil.rmtree(rundir / "push.git", ignore_errors=True)
    print(render_report(st), end="")
    print(f"report: {rundir / 'report.md'}")
    if rp.stop.is_set():
        if rp.stop_kind == "signal":
            return 143
        print(f"mq_replay: stopped: {rp.stop_reason}; resume with: python3 {Path(__file__).resolve().parent / 'mq_replay.py'} run --resume {run_id}", file=sys.stderr)
        return EXIT_INTERRUPTED
    errors = [cid for cid in chosen if st["cases"][cid]["status"] == "error" or st["cases"][cid].get("cleanup_problems")]
    nos = [cid for cid in chosen if st["cases"][cid]["status"] == "done" and (st["cases"][cid].get("row") or {}).get("match") != "yes"]
    return 1 if errors or nos or left else 0


def newest_run(root: Path) -> str | None:
    runs = [p for p in root.iterdir() if (p / "run.json").is_file()] if root.is_dir() else []
    return max(runs, key=lambda p: (p / "run.json").stat().st_mtime).name if runs else None


def cmd_report(a) -> int:
    root = state_root(a.state_dir)
    run_id = a.run or newest_run(root)
    if not run_id or not NAME_RE.fullmatch(run_id) or not (root / run_id / "run.json").is_file():
        print(f"mq_replay: no run to report under {root}" + (f" (run {run_id})" if a.run else ""), file=sys.stderr)
        return 2
    st = json.loads((root / run_id / "run.json").read_text())
    text = render_report(st)
    (root / run_id / "report.md").write_text(text)
    print(text, end="")
    return 0


def case_units(systemctl: str, slug: str, rid: str, cids: list[str]) -> list[str]:
    """the running driver units of the cases of one run, by their exact names: run ids may hold `-`, so `mq-<repo>-a-` also starts the units of a run `a-b`"""
    wanted = {unit_name(slug, rid, c) for c in cids}
    if not wanted:
        return []
    r = run([systemctl, "--user", "list-units", "--no-legend", "--plain", "--state=active,activating,reloading", f"mq-{slug.replace('/', '__')}-*.service"], timeout=30)
    if r.returncode != 0:
        return []
    out = []
    for ln in r.stdout.splitlines():
        f = [x for x in ln.split() if x not in ("●", "*")]
        if f and f[0] in wanted:
            out.append(f[0])
    return out


def cmd_clean(a) -> int:
    if bool(a.run) == bool(a.older_than):
        raise SystemExit("mq_replay: clean wants exactly one of --run ID and --older-than AGE")
    root = state_root(a.state_dir)
    if a.run and not NAME_RE.fullmatch(a.run):
        raise SystemExit(f"mq_replay: a run id is [A-Za-z0-9._-], not {a.run!r}")
    age = parse_age(a.older_than) if a.older_than else None
    repo = str(Path(a.repo).resolve())
    remote = a.remote or run(["git", "-C", repo, "remote", "get-url", "origin"], env=GIT_ENV).stdout.strip()
    if not remote:
        raise SystemExit(f"mq_replay: {repo} has no origin remote: pass --remote")
    try:
        slug = derive_slug(remote, a.slug)
    except SystemExit:
        slug = None
        print("mq_replay: no --slug and none derivable from the remote: leftover driver units are not looked for")
    root.mkdir(parents=True, exist_ok=True)
    work = root / f".clean-push-{os.getpid()}.git"
    locks: dict[str, int] = {}
    try:
        rem = Remote(remote, work)
        old = lambda rid: (t := run_started_at(root, rid)) is not None and time.time() - t > age
        picked = lambda rid: rid == a.run if a.run else old(rid)
        all_refs = rem.practice_refs()
        # which runs are chosen: by their refs, and by their folders; a run that holds its lock is alive and is left alone, refs included, whatever its age
        chosen = {run_of_ref(r) for r in all_refs if picked(run_of_ref(r))}
        folders_of = [d for d in (sorted(root.iterdir()) if root.is_dir() else []) if (d / "run.json").is_file() and (a.run == d.name or (age is not None and old(d.name)))]
        chosen |= {d.name for d in folders_of}
        live = set()
        for rid in sorted(chosen):
            if not (root / rid / "run.json").is_file():
                continue
            fd = os.open(root / rid / "run.lock", os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locks[rid] = fd              # held until the end: the run cannot start again under the deletion
            except OSError:
                os.close(fd)
                live.add(rid)
        for rid in sorted(live):
            print(f"run {rid} is running: its branches, units and folders stay")
        refs, skipped = [], set()
        for ref in all_refs:
            rid = run_of_ref(ref)
            if rid in live:
                continue
            if picked(rid):
                refs.append(ref)
            elif not a.run and run_started_at(root, rid) is None:
                skipped.add(rid)
        units = []
        if slug:
            for rid in sorted(chosen - live):
                cids = {c for c in (case_of_ref(r) for r in all_refs if run_of_ref(r) == rid) if c}
                try:
                    cids |= set(json.loads((root / rid / "run.json").read_text()).get("cases") or {})
                except (OSError, ValueError):
                    pass
                units += case_units(a.systemctl, slug, rid, sorted(cids))
        for u in units:
            print(("would stop " if a.dry_run else "stop ") + u)
            if not a.dry_run:
                run([a.systemctl, "--user", "stop", u], timeout=120)
        for ref in refs:
            print(("would delete " if a.dry_run else "delete ") + ref)
        for rid in sorted(skipped):
            print(f"skipped run {rid}: its age is unknown (use --run {rid})")
        left = [] if a.dry_run else rem.delete(refs)
        folders = 0
        for d in folders_of:
            if d.name in live:
                continue
            for sub in ("cases", "push.git"):
                if (d / sub).exists() and not a.dry_run:
                    for link in [x for x in (d / sub).glob("*/state/*") if x.is_symlink()] + [x for x in (d / sub).glob("*/config/*") if x.is_symlink()]:
                        link.unlink()        # the links into the real gh config and poller folders go as links
                    shutil.rmtree(d / sub)
                    folders += 1
        print(f"{len(refs)} ref(s) {'would be ' if a.dry_run else ''}deleted, {len(units)} unit(s) {'would be ' if a.dry_run else ''}stopped, {folders} folder(s) removed"
              + (f"; STILL THERE: {', '.join(left)}" if left else ""))
        return 1 if left or (a.run in live) else 0
    finally:
        for fd in locks.values():
            os.close(fd)
        shutil.rmtree(work, ignore_errors=True)


def add_commands(sub) -> None:
    def common(p):
        p.add_argument("--repo", default=str(ROOT), help="the checkout whose origin, objects and .github/mergequeue.toml are read (never changed); default this one")
        p.add_argument("--remote", help="the remote url the practice branches go to (default the checkout's origin)")
        p.add_argument("--state-dir", help="where runs are kept (default ${XDG_STATE_HOME:-~/.local/state}/stackshot/mq-replay)")
    r = sub.add_parser("run", help="replay the cases through the real merge queue on practice branches and compare the verdicts with the old path's")
    common(r)
    r.add_argument("--run", help="the run id (default the time); the practice branches are practice/<run>/<case>")
    r.add_argument("--profile", choices=("build", "full"), default="build", help="build = no CI for any case (a group is built, not pushed); full = real CI for the cases that need it (default build)")
    r.add_argument("--cases", help="only these cases, comma separated (default: all for build, the CI cases for full)")
    r.add_argument("--cases-file", help="the cases file (default tests/mq_replay/cases.json)")
    r.add_argument("--concurrency", type=int, default=2, help="cases at a time (default 2)")
    r.add_argument("--resume", metavar="ID", help="run the cases of run ID that are not done")
    r.add_argument("--keep", action="store_true", help="keep each case's folder and clone (the practice branches are deleted all the same)")
    r.add_argument("--detach", action="store_true", help="start the run as the user unit stackshot-mq-replay-<run> and return")
    r.add_argument("--slug", help="OWNER/NAME of the repository (default: from a github.com remote url)")
    r.add_argument("--rules-ref", default="origin/main", help="where .github/mergequeue.toml is read from (default %(default)s)")
    r.add_argument("--logdir", help="the release logs' folder, where the release queue file is (default: where release.sh keeps it, `python3 config.py state releases`)")
    r.add_argument("--gate-poll", type=float, default=30.0, help="seconds between looks at the idle gate while waiting (default 30)")
    r.add_argument("--gate-cap", type=float, default=21600.0, help="give up waiting for an idle box after this many seconds (default 6 h)")
    r.add_argument("--case-timeout", type=float, default=14400.0, help="seconds a case may wait for its verdict (default 4 h)")
    r.add_argument("--settle", type=float, default=5.0, help="seconds to wait before looking once more for a CI run of a pushed branch when none was found at the cancel (GitHub registers a run a few seconds after a push; default 5)")
    r.add_argument("--driver-wait", type=float, default=120.0, help="seconds a case's driver unit gets to leave before it is stopped (default 120)")
    r.add_argument("--salamander", default="salamander")
    r.add_argument("--systemctl", default="systemctl")
    r.add_argument("--gh", default="gh")
    p = sub.add_parser("report", help="print the verdict table of a run (the newest by default)")
    p.add_argument("--run")
    p.add_argument("--state-dir")
    c = sub.add_parser("clean", help="delete the practice branches (and the folders) of a run, or of every run older than an age")
    common(c)
    c.add_argument("--run")
    c.add_argument("--older-than", help="an age such as 1d: runs older than that (by run.json, else by the time in the run id)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--slug", help="OWNER/NAME of the repository (default: from a github.com remote url); names the driver units to stop")
    c.add_argument("--systemctl", default="systemctl")


def dispatch(a) -> int:
    return {"run": cmd_run, "report": cmd_report, "clean": cmd_clean}[a.cmd](a)
