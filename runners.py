"""runners.py — the CI runners page (redesigned): every CI runner GitHub lists for the repos, by machine, each idle, running,
disabled or offline, and a Disable / Enable button on every fleet machine.

  GET /runners        the page "CI runners": count cards (Runners, Running, Idle, Disabled, Offline) and one row per machine (every machine the runners' labels name):
                      the machine's name, its state ("on · 2 of 4 busy", "disabling · 1 job finishing", "disabled") and its button in a 168 px column, and its runners beside it. A runner on
                      a repo's own list shows the repo as a small tag when the page has more than one list (an organization's shared runners are tagged "<org> (shared)"). Running: the
                      job's repo, its PR (linked) or branch, how long it has run. A runner disabled on purpose is "disabled" ("disabled on box-a", "held for stackshot on box-b"); offline is
                      GitHub listing the runner offline although it was not disabled, for 5 minutes or more (a red mark and a red count card); a shorter gap is a runner restarting between
                      jobs (drawn "restarting" with the idle dot, no red, counted as idle). Since when it is offline is `off_since` on its row, kept with the snapshot and cleared when it is online again. The page fetches /runners.json every 30 s and swaps its table.
  GET /runners.json   {ts, errors, runners: [...], counts, html}: the same snapshot as data, and the table as HTML (the one rendering both use).
  POST /runners/switch   (server.py) the button: box + action (off = Disable, on = Enable) + the page's token → switch_box() below runs pool-mode.sh for that machine.

Where the facts come from (read only; nothing here changes the pool except the button):
  GitHub   Where a repo's runners live is read from GitHub, not from config: GET /repositories/<id> (or /repos/<owner>/<repo>) gives owner.login and owner.type, kept
           [runners] owner_cache_s (600 s) so an owner change is picked up within minutes. The repo's own runners are GET <repo>/actions/runners (/repositories/<id>/actions/runners
           for a repo with an entry in [runners.ids]); when the owner is an Organization, its runners too: GET /orgs/<owner>/actions/runners (once per org, however many repos it owns),
           tagged "<org> (shared)" because an org runner serves every repo of the org. A runner listed twice (same id and name) shows once. A user-owned repo has repo-level runners only.
           Runner groups are not read: on GitHub Free an org has the Default group alone, which serves all its repos. A paid org that restricts a group to some repos would
           need /orgs/<org>/actions/runner-groups here. A token that cannot read the org's runners (403/404) leaves the page with what was read and one plain line naming the missing permission.
           The machine of a runner comes from its labels (_box_of), so a new machine needs no config. For a busy runner
           GET .../actions/runs?status=in_progress, then each run's /jobs until every busy runner has its job (job.runner_name): the run gives
           head_branch and pull_requests, the job started_at (a busy org runner is looked for in the runs of every configured repo). The token is ghsync.token() (never printed or logged). The whole snapshot is cached for
           [runners] cache_s (25 s) in this process, so many viewers never multiply the calls, and jobs are fetched only when some runner is busy.
           A busy runner's job is told at the two ends of a job too, where GitHub's lists lag the runner by seconds: a run still queued holds the job (one list of at most MAX_QUEUED queued runs,
           asked only for a runner still unmatched), a job GitHub lists as completed while the runner is still busy is "finishing job…", and a runner no run names is told by what the previous snapshot
           had it doing: idle there → "starting job…", on a job there → "finishing job…" (that job's PR or branch carried over); the run's name stands in when there is no PR or branch to link. After
           GAP_S (180 s) of such a gap, with no previous snapshot, or for a mismatch that was one already, it reads "job not found".
  Stale while revalidate: /runners, /runners.json (and the pages in ui/runners.py) never build in the request. serve() hands back the last snapshot at once with its age, whether a rebuild is running (`refreshing`) and, only
           when no rebuild is on its way (the last one read nothing, one has overrun past OVERRUN x build_s, or none could start), `stale`; a snapshot that is merely old while a healthy rebuild runs is drawn
           at full strength and the page asks again within seconds. When the snapshot is older than cache_s serve() starts ONE background rebuild (snapshot()'s single flight, shared with the side panel), so GitHub
           and ssh are asked no more often than before. With nothing read yet the answer is `pending` and the page asks again every 3 s. The last snapshot is kept in <paths.state>/runners-snapshot.json
           (a temp file renamed over the old one; never the error of a build that read nothing) and taken back by restore() at server start, so a restart draws the table at once.
  switch   pool-mode.sh's state (a script you provide), read for every machine that has a runner: on the machine this server runs on ([runners] local_box) the files
           [runners] mode_file / hold_file (a missing mode = on) and gate_file (the units the gate stopped); on any other machine over ssh, cached [runners] ssh_cache_s (120 s) per box,
           the machines read in parallel. The ssh host is [runners.ssh_hosts] for the box, else the box's own name when it is a fleet machine (pool-mode.sh reaches a fleet machine with
           `ssh <box>` too). A WSL box answers the powershell -EncodedCommand call of pool-mode.sh's `status` action (a missing mode = off), a Linux box (such as
           spare-box) the shell form of the same (a missing mode = on); the first read tries powershell, a "command not found" tries the shell form, and the answer is remembered.
           A box that cannot be reached reads "box not reachable". A box whose mode is off is "disabled": a job already running finishes, then the machine takes no new job.
  The button: switch_box(box, action) runs, on the machine this server runs on, `bash <[runners] switch_script> <off|on> <box>` (pool-mode.sh, which itself reaches a remote
           machine over `ssh <box>`; no channel of its own here) with an argument list (never a shell string), a minimal environment, its own session and a timeout of [runners] switch_timeout_s;
           the box must be one of fleet.names() or a [runners] boxes entry that [runners.ssh_hosts] names (spare-box is not in the sala fleet; switch_boxes); the result text goes back to the page. Without [runners] switch_script there is no button.
  The board's side panel: a Runners section, one card per machine, a line per repo `<label> <active>/<online>` (peek, counts, label below). The panel
  is drawn on every board render, so it never waits on GitHub or ssh: peek() hands back the last snapshot at once and, when it is missing or older than
  panel_refresh_s (120 s), starts one background rebuild through snapshot()'s single flight. The /runners pages keep cache_s (25 s) for their own rebuilds (serve()).
  A repo is found by GitHub's numeric repository ID when [runners.ids] gives one (`name = <id>`): the ID survives a transfer to another owner, owner/name does not. The
  page's links to github.com still need owner/name: a running job's links take `repository.full_name` from the run GitHub already returned for it (no extra call), else
  [runners] owner + the name (GitHub redirects a transferred repo's old address).
Optional: a board that uses no self-hosted runners lists no repo in [runners] repos (or has no [runners] table). enabled() is then False: nothing is read (no GitHub call, no ssh, no thread, no saved
  snapshot taken back), the page says plainly that the board does not use CI runners and the side panel has no Runners section. The same holds when a clean read finds no runner at all (unused()).
Pure of the server: server.py serves the routes and the board's header links /runners. Tests replace _get, _read_local, _ssh and _now."""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import config as _cfg
import fleet as _fleet
import ghsync as _gh
import ghbudget as _gb   # the hourly ledger of GitHub calls shared with the mirror and anchor-hub

DEFAULTS: dict[str, Any] = {
    "owner": "",             # the GitHub owner of the repos below; "" = none set (a repo with no ID then reads "set [runners] owner"). no default holds a person's login
    "repos": [],             # the repos whose runners are read; an instance lists its own
    "boxes": [],             # the machine rows; shown in the Machines panel's order, one it does not list after those, in this order (any other machine a runner's labels name gets a row after these)
    "cache_s": 25,
    "owner_cache_s": 600,    # a repo's owner (user or organization) is kept this long: an owner change shows within this time
    "role_labels": [],       # more labels that name a role, not a machine (heavy, light and pool are built in), so they never become a machine row
    "panel": True,          # false: the side panel never starts a background read (it still shows a snapshot the /runners page made)
    "panel_refresh_s": 120,  # the side panel (peek) starts a background rebuild only when the snapshot is older than this; the /runners page keeps cache_s
    "local_box": "",         # the machine this server runs on: its CI switch is read from the files below; "" = none (every box then reads "switch not read")
    "state_dir": "~/.config/build-pool",   # where pool-mode.sh keeps its mode and hold files, on this box and (read over ssh) on every other box
    "mode_file": "",         # "" = <state_dir>/mode
    "hold_file": "",         # "" = <state_dir>/hold
    "gate_file": "/var/lib/build-pool/halted",
    "ssh_enabled": True,
    "ssh_hosts": {},         # box -> the ssh host that reaches its CI switch; a fleet machine not listed is reached as `ssh <box>`, as pool-mode.sh does
    "ssh_cache_s": 120,
    "ssh_timeout_s": 12,
    "build_s": 20,           # the whole rebuild (GitHub and ssh) is given this long
    "call_s": 8,             # one GitHub call at most this long (and never longer than what is left of build_s)
    "switch_script": "",     # the path of pool-mode.sh (a script you provide); "" = no Disable / Enable buttons, and the route refuses
    "switch_timeout_s": 90,  # one button press (pool-mode.sh, with its ssh calls and its GitHub listing) is stopped after this long
}
MAX_RUNS = 30            # in-progress runs looked at for a busy runner's job
MAX_PAGES = 5            # pages of 100 runners per repo or org
MAX_QUEUED = 5           # queued runs looked at (only when a busy runner is still without its job after the in-progress runs): a job just picked up can still sit in a queued run
OFFLINE_GRACE_S = 300.0  # an offline runner that nothing disabled is a fault only once it has stayed offline this long (5 minutes): a runner that runs one job and restarts is listed offline by GitHub for a short while between jobs
GAP_S = 180.0            # a job's start or end gap ("starting job…", "finishing job…") is told this long; a busy runner with no job after that is a real mismatch ("job not found")
# Labels that never name a machine: the ones GitHub puts on a self-hosted runner, and the pool's role tags (compared in lower case).
_GH_LABELS = frozenset({"self-hosted", "linux", "windows", "macos", "x64", "arm64", "arm"})
_ROLE_LABELS = frozenset({"heavy", "light", "pool"})
ORG_MARK = "/*"          # a column key ending in this is an organization's shared runners: "<login>/*"


class RunnersError(Exception):
    """A GitHub or switch read that failed; the text is safe to show (no token, no URL query). `code` is GitHub's HTTP status when it answered with one."""
    def __init__(self, msg: str = "", code: int | None = None):
        super().__init__(msg)
        self.code = code


def conf(key: str) -> Any:
    v = _cfg.get("runners", key)
    v = DEFAULTS[key] if v is None else v
    if key in ("mode_file", "hold_file") and not str(v).strip():
        return str(conf("state_dir")).rstrip("/") + "/" + key[:-5]
    return v


def _repos() -> list[str]:
    return [str(r) for r in conf("repos")]


def enabled() -> bool:
    """Whether this board uses the Runners feature: [runners] repos lists at least one repo. No [runners] table, or an empty list, is off: nothing is read and nothing is drawn."""
    return bool(_repos())


def unused(snap: dict[str, Any]) -> bool:
    """A snapshot that read cleanly and found no runner at all (no error, no failed list, not the placeholder before the first read): the page and the side panel treat the
    feature as not in use, as when it is off. A read that failed is not this: its error is shown."""
    return not snap.get("runners") and not snap.get("failed") and not snap.get("errors") and not snap.get("pending")


def _ids() -> dict[str, int]:
    """[runners.ids]: repo name (as in [runners] repos) → GitHub's numeric repository ID, an int or a digit string; a bad entry is ignored (that repo is found by name)."""
    m = _cfg.get("runners", "ids")
    out: dict[str, int] = {}
    for k, v in (m.items() if isinstance(m, dict) else ()):
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v > 0 or isinstance(v, str) and v.strip().isdigit() and int(v) > 0:
            out[str(k)] = int(v)
    return out


def _api(repo: str) -> str:
    """The REST prefix of a repo's calls: /repositories/<id> when its ID is configured, else /repos/<owner>/<repo>."""
    rid = _ids().get(repo)
    if rid:
        return f"/repositories/{rid}"
    owner = str(conf("owner") or "").strip()
    if not owner:
        raise RunnersError(f"{repo}: no GitHub owner set; add owner = \"<login>\" (or an ID for the repo under [runners.ids]) to the [runners] section")
    return f"/repos/{owner}/{repo}"


def _boxes() -> list[str]:
    return [str(b) for b in conf("boxes")]


def _now() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


def _left(dl: float) -> float:
    """Seconds left of the build's deadline; RunnersError when there are none."""
    t = dl - _mono()
    if t <= 0.2:
        raise RunnersError("out of time")
    return t


# ----------------------------------------------------------------------------- GitHub
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed: urllib would send the Authorization header on to wherever it points. The 3xx comes back as the answer."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_ETAGS: dict[str, tuple[str, Any]] = {}      # a GET path -> (its ETag, the answer): what _get sends back as If-None-Match; guarded by _ELOCK
_ELOCK = threading.Lock()
_ETAGS_MAX = 100


def _open(req: urllib.request.Request, timeout: float) -> Any:
    return _OPENER.open(req, timeout=timeout)


def _get(path: str, timeout: float = 8) -> Any:
    """GET <api>/<path> as JSON with the server's GitHub login. The one place that talks to GitHub: tests replace it."""
    tok = _gh.token()
    if not tok:
        raise RunnersError("no GitHub token (gh auth login on this box, or [github] token_file)")
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "stackshot-runners"}
    with _ELOCK:
        known = _ETAGS.get(path)
    if known:                                           # the last answer's ETag; a 304 is not counted against the 5,000 an hour
        headers["If-None-Match"] = known[0]
    req = urllib.request.Request(_gh.api_url() + path, headers=headers)
    where = path.split("?", 1)[0]
    held = _gb.wait(_gb.READ, _gh.read_budget())              # the host's one hourly ledger of GitHub calls (ghbudget.py); the page shows the hold as an error and tries again on its next build
    if held > 0:
        raise RunnersError(f"GitHub reads are held by the hourly cap ({_gh.read_budget()}); they resume in {_gb.held_words(held)}")
    try:
        with _open(req, timeout) as r:
            _gb.note(_gb.READ)                                 # a 200 counts against the token
            out = json.loads(r.read().decode("utf-8"))
            hdr = getattr(r, "headers", None)
            _gh.note_rate(hdr, getattr(r, "status", 200))
            tag = str(hdr.get("ETag") or "") if hdr is not None else ""
        if tag:
            with _ELOCK:
                _ETAGS[path] = (tag, copy.deepcopy(out))
                while len(_ETAGS) > _ETAGS_MAX:
                    _ETAGS.pop(next(iter(_ETAGS)))
        return out
    except urllib.error.HTTPError as e:
        _gh.note_rate(e.headers, e.code)
        if e.code == 304 and known:                           # unchanged: free, and not in the ledger
            return copy.deepcopy(known[1])
        _gb.note(_gb.READ)                                     # any other answer GitHub counted
        raise RunnersError(f"GitHub answered {e.code} for {where}", e.code) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RunnersError(f"GitHub not reachable for {where} ({e.__class__.__name__})") from None


_OWNERS: dict[str, tuple[float, str, str]] = {}      # a repo's REST prefix → (when read, owner.login, owner.type); guarded by _LOCK
_OWNER_FAIL: dict[str, tuple[float, str]] = {}       # a repo's REST prefix → (when its owner read failed, the safe text); guarded by _LOCK
OWNER_FAIL_S = 60.0                                  # a failed owner read is kept this long
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")          # a GitHub login: it goes into a URL path, so nothing else is accepted


def _owner_of(repo: str, dl: float) -> tuple[str, str]:
    """(owner.login, owner.type) of a configured repo, from GET /repositories/<id> (or /repos/<owner>/<repo>): nothing about the owner is configured, and a repo moved to
    another owner, or from a user to an organization, is followed. Kept [runners] owner_cache_s; when a re-read fails the older answer is used rather than none."""
    key = _api(repo)
    with _LOCK:
        hit = _OWNERS.get(key)
        bad = _OWNER_FAIL.get(key)
    if hit and _now() - hit[0] < float(conf("owner_cache_s")):
        return hit[1], hit[2]
    if bad and _now() - bad[0] < OWNER_FAIL_S:           # a failed read is not repeated for a minute: a hanging GitHub would eat every build's time on owner reads
        if hit:
            return hit[1], hit[2]
        raise RunnersError(bad[1])
    try:
        d = _get(key, min(float(conf("call_s")), _left(dl)))
        o = d.get("owner") if isinstance(d, dict) else None
        login, typ = (str(o.get("login") or ""), str(o.get("type") or "")) if isinstance(o, dict) else ("", "")
        if not _LOGIN.fullmatch(login):
            raise RunnersError(f"GitHub's answer for {repo} named no usable account")
    except RunnersError as e:
        with _LOCK:
            _OWNER_FAIL[key] = (_now(), str(e))
        if hit:
            return hit[1], hit[2]
        raise
    with _LOCK:
        _OWNERS[key] = (_now(), login, typ)
        _OWNER_FAIL.pop(key, None)
    return login, typ


def _list_at(prefix: str, what: str, dl: float) -> list[dict[str, Any]]:
    """Every runner at <prefix>/actions/runners (prefix: a repo's REST prefix or /orgs/<login>), paginated; `what` names it in an error."""
    out: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        d = _get(f"{prefix}/actions/runners?per_page=100&page={page}", min(float(conf("call_s")), _left(dl)))
        rs = d.get("runners") if isinstance(d, dict) else None
        if not isinstance(rs, list):
            raise RunnersError(f"GitHub's runner list for {what} had an unexpected shape")
        out += [r for r in rs if isinstance(r, dict)]
        if not rs or len(out) >= int(d.get("total_count") or 0):
            break
    return out


def _list_runners(repo: str, dl: float) -> list[dict[str, Any]]:
    return _list_at(_api(repo), repo, dl)


def _org_error(login: str, e: Exception) -> str:
    """The one plain line for an organization whose runners could not be read. 403/404 mean the token cannot see them: name the permission."""
    if isinstance(e, RunnersError) and e.code in (403, 404):
        return (f"{login}: the organization's shared runners could not be read; the server's GitHub token lacks the permission "
                f"(fine-grained token: organization \"Self-hosted runners: read\"; classic token: admin:org read), or GitHub is limiting the token (a rate limit or SSO also answers 403)")
    return f"{login}: the organization's shared runners could not be read ({_say(e)})"


def _jobs_of(repo: str, busy: set[str], dl: float, found: dict[str, dict[str, Any]], ended: dict[str, dict[str, Any]] | None = None,
             status: str = "in_progress", limit: int = MAX_RUNS) -> None:
    """Fills `found`: runner name → {run, job, repo} for the busy runners: the runs of `status` (in progress; or queued, where a job just picked up can still sit), each run's
    jobs until every busy runner is matched or the build's time is out (RunnersError; what was found stays in `found`). A job of a busy runner that GitHub already lists as
    completed (the runner is still closing it down) goes to `ended`, the latest one per runner, when the caller passes it."""
    d = _get(f"{_api(repo)}/actions/runs?status={status}&per_page={limit}", min(float(conf("call_s")), _left(dl)))
    for run in (d.get("workflow_runs") if isinstance(d, dict) else None) or []:
        if busy <= set(found):
            break
        if not isinstance(run, dict):
            continue
        jd = _get(f"{_api(repo)}/actions/runs/{run.get('id')}/jobs?filter=latest&per_page=100", min(float(conf("call_s")), _left(dl)))
        for job in (jd.get("jobs") if isinstance(jd, dict) else None) or []:
            if not isinstance(job, dict):
                continue
            nm = job.get("runner_name")
            if nm not in busy or nm in found:
                continue
            if job.get("status") == "in_progress":
                found[nm] = {"run": run, "job": job, "repo": repo}
            elif job.get("status") == "completed" and ended is not None:
                was = ended.get(nm)
                if was is None or _epoch(job.get("completed_at")) > _epoch(was["job"].get("completed_at")):
                    ended[nm] = {"run": run, "job": job, "repo": repo}


def _epoch(s: Any) -> float:
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _github_url(u: Any) -> str:
    """A link GitHub gave, kept only when it is an https github.com address (never a javascript: or other scheme)."""
    u = str(u or "")
    return u if re.fullmatch(r"https://github\.com/[\w./%-]+", u) else ""


def _job_info(repo: str, hit: dict[str, Any] | None, phase: str = "") -> dict[str, Any]:
    """The job a busy runner is on. `repo` is the runner's own column; the job's repo is the one whose runs held it (an org runner takes jobs of any repo).
    `phase` is "" for a job GitHub lists as running, "finishing" for one it lists as completed while the runner is still closing it down; no hit at all is "lost" (the page
    says "job not found"). `run` is the run's name, `gap` when a starting or finishing gap began."""
    if not hit:
        return {"repo": "" if repo.endswith(ORG_MARK) else repo, "full": "", "pr": 0, "branch": "", "url": "", "started": 0.0, "run": "", "phase": "lost", "gap": 0.0}
    run, job = hit["run"], hit["job"]
    repo = str(hit.get("repo") or repo)
    prs = []
    for p in (run.get("pull_requests") or []):
        n = p.get("number") if isinstance(p, dict) else None
        if isinstance(n, int) and n > 0:
            prs.append(n)
    rr = run.get("repository")
    full = str(rr.get("full_name") or "") if isinstance(rr, dict) else ""
    return {"repo": repo, "full": full if re.fullmatch(r"[\w.-]+/[\w.-]+", full) else "", "pr": prs[0] if prs else 0, "branch": str(run.get("head_branch") or ""),
            "url": _github_url(run.get("html_url") or job.get("html_url")), "started": _epoch(job.get("started_at") or run.get("run_started_at")),
            "run": _clean_text(" ".join(str(run.get("display_title") or run.get("name") or "").split()), 100), "phase": phase, "gap": 0.0}


def _gap_job(col: str, before: dict[str, Any] | None, before_ts: float | None, now: float) -> dict[str, Any]:
    """The job of a busy runner that no run names. GitHub's lists lag the runner by seconds at both ends of a job, so the previous snapshot says which gap this is: the runner
    was idle or offline there → "starting"; it was on a job there → "finishing" that job (its details carried over). A gap already told for GAP_S, a previous snapshot that is
    missing or older than GAP_S, and a mismatch that was one already → "lost" (the page says "job not found")."""
    lost = _job_info(col, None)
    if before is None or before_ts is None or now - before_ts > GAP_S:
        return lost
    if before.get("state") != "running":
        return {**lost, "phase": "starting", "gap": now}
    pj = before.get("job")
    if not isinstance(pj, dict):
        return lost
    ph = str(pj.get("phase") or "")
    if ph == "lost" or (not ph and not (pj.get("pr") or pj.get("branch") or pj.get("started"))):
        return lost
    gap_phase = ph in ("starting", "finishing")
    since = float(pj.get("gap") or before_ts) if gap_phase else now
    if gap_phase and now - since > GAP_S:
        return lost
    return {**{k: pj.get(k, lost[k]) for k in lost}, "started": 0.0, "phase": ph if gap_phase else "finishing", "gap": since}      # the old job's start is not carried: the gap is not time on a job


def _box_of(r: dict[str, Any]) -> str:
    """The machine a runner is on, with no config. A registration carries its machine as a label (box-a, box-b, …) beside GitHub's own
    labels (self-hosted, Linux, X64, …) and the pool's role tags (heavy, light, pool); those are dropped and what is left names the machine:
      1. a label the runner's name starts with (`box-a-light-2` → box-a): a name and a label that agree are the surest;
      2. a [runners] boxes machine the name starts with: a label can go stale (a runner can carry another box's label), the name was typed by the installer;
      3. a label that is a [runners] boxes machine;
      4. the only label left, whatever it is: a machine nobody listed gets a row of its own;
      5. with several unknown labels left, the name's prefix before `-<n>` / `-light-<n>`, else the first label;
    and "other" when nothing is left and the name says nothing."""
    name = str(r.get("name") or "")
    skip = _GH_LABELS | _ROLE_LABELS | {str(x).lower() for x in (conf("role_labels") or [])}
    cands: list[str] = []
    for x in (r.get("labels") or []):
        lb = str(x.get("name") or "").strip() if isinstance(x, dict) else ""
        if lb and lb.lower() not in skip and lb not in cands:
            cands.append(lb)
    named = [c for c in cands if name.startswith(c + "-")]
    if named:
        return max(named, key=len)
    named = [b for b in _boxes() if name.startswith(b + "-")]
    if named:
        return max(named, key=len)
    known = [b for b in _boxes() if b in cands]
    if known:
        return known[0]
    if len(cands) == 1:
        return cands[0]
    if cands:
        pre = re.sub(r"(?:-light)?-\d+$", "", name)
        return pre if pre and pre != name else cands[0]
    return "other"


# ----------------------------------------------------------------------------- the CI switch
def _words(text: str, repos: list[str]) -> set[str]:
    return {w for w in re.split(r"[\s,]+", text.lower()) if w in repos}


def _read_local() -> dict[str, Any]:
    """The switch on this box (the host): mode file (missing = on; only `off` is off), hold file (missing = none), the units the gate stopped (names, or None when the file is missing);
    `since` is when the mode file last changed (epoch seconds, 0 when it has none)."""
    def text(key: str) -> str | None:
        try:
            with open(os.path.expanduser(str(conf(key))), "rb") as f:
                return f.read(4096).decode("utf-8", "replace")
        except OSError:
            return None
    mode, hold, gate = text("mode_file"), text("hold_file"), text("gate_file")
    w = (mode or "").split()
    try:
        since = os.path.getmtime(os.path.expanduser(str(conf("mode_file")))) if mode is not None else 0.0
    except OSError:
        since = 0.0
    return {"ok": True, "mode": "off" if w and w[0].lower() == "off" else "on", "held": sorted(_words(hold or "", _repos())), "since": since,
            "gate": None if gate is None else [ln.strip() for ln in gate.splitlines() if ln.strip()]}


def _remote_dir() -> list[str]:
    """[runners] state_dir as path parts under the home folder of a box read over ssh ("~/.config/build-pool" -> [".config", "build-pool"]). Only plain path characters are kept;
    anything else (or a path outside the home folder) reads as the default, so no config value can put shell text into the remote command."""
    d = str(conf("state_dir")).strip()
    ok = re.fullmatch(r"~/[\w.-]+(?:/[\w.-]+)*", d) and ".." not in d.split("/")
    return (d if ok else DEFAULTS["state_dir"])[2:].split("/")


def _ps_status() -> str:
    """The read-only half of pool-mode.sh's `status` action for a WSL box: the same two lines, nothing written."""
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$d = Join-Path $env:USERPROFILE '" + "\\".join(_remote_dir()) + "'",
        "$f = Join-Path $d 'mode'",
        "if (Test-Path $f) { 'mode file: ' + (Get-Content -Raw $f).Trim() } else { 'mode file: missing (= off)' }",
        "$h = Join-Path $d 'hold'",
        "if (Test-Path $h) { $t = ([string](Get-Content -Raw $h)).Trim(); 'hold file: ' + $(if ($t) { $t } else { 'none' }) } else { 'hold file: none' }",
    ]) + "\n"


def _sh_status() -> str:
    """The same two lines for a Linux box (such as spare-box): pool-mode.sh's own `status` text for the mode file, and the hold file too."""
    d = "$HOME/" + "/".join(_remote_dir())
    return ("f=\"" + d + "/mode\"; if [ -f \"$f\" ]; then echo \"mode file: $(tr -d '\\r\\n' < \"$f\")\"; else echo \"mode file: missing (= on)\"; fi; "
            "h=\"" + d + "/hold\"; if [ -f \"$h\" ]; then t=$(tr -d '\\r' < \"$h\" | tr '\\n' ' '); echo \"hold file: ${t:-none}\"; else echo \"hold file: none\"; fi")


def _ps_command() -> str:
    return "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(_ps_status().encode("utf-16-le")).decode("ascii")


# What the page may say about a failed read: only these fixed forms, never ssh's own stderr or any text from the box.
_DETAIL = re.compile(r"ssh exit \d{1,3}|ssh timed out|ssh could not start|unexpected answer")
FLAVORS = ("ps", "sh")   # how a box answers the status call: powershell (WSL boxes) or a POSIX shell (Linux boxes)


def _ssh(host: str, timeout: float, flavor: str = "ps") -> str:
    """stdout of the status script run on `host` over ssh with key auth only (no prompt), in the powershell form (flavor "ps") or the shell form ("sh"); RunnersError ("ssh exit N",
    "ssh timed out", "ssh could not start") when ssh or the script fails. Tests replace it."""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=no", "-o", "ControlPath=none",
                            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2", "--", host, _ps_command() if flavor == "ps" else _sh_status()],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RunnersError("ssh timed out") from None
    except (OSError, subprocess.SubprocessError):
        raise RunnersError("ssh could not start") from None
    if r.returncode != 0:
        raise RunnersError(f"ssh exit {r.returncode}")
    return r.stdout.replace("\r", "").replace("\0", "")


def _parse_wsl(out: str) -> dict[str, Any]:
    mode = hold = None
    for ln in out.splitlines():
        if ln.startswith("mode file:"):
            mode = ln.split(":", 1)[1].strip().lower()
        elif ln.startswith("hold file:"):
            hold = ln.split(":", 1)[1].strip()
    if mode is None:
        raise RunnersError("unexpected answer")
    on = ("(= on)" in mode) if mode.startswith("missing") else mode == "on"       # "missing (= on)" (a Linux box) / "missing (= off)" (a WSL box): the file is absent, the box's own default stands
    return {"ok": True, "mode": "on" if on else "off", "held": sorted(_words(hold or "", _repos())), "gate": None, "since": 0.0}


_SSH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SSH_LOCK = threading.Lock()          # guards the dicts around it, never held across an ssh call
_BOX_LOCKS: dict[str, threading.Lock] = {}      # one read of a box at a time (a second asker waits for the first and takes its answer); boxes are read in parallel
_FLAVOR: dict[str, str] = {}          # box -> the flavor that answered last


def fleet_boxes() -> list[str]:
    """The machines of the fleet (fleet.names() values, sorted): the only names the Disable / Enable button and the ssh fallback accept. [] when the fleet state cannot be read."""
    try:
        return sorted({str(n) for n in _fleet.names().values() if n})
    except Exception:  # noqa: BLE001  — an unreadable fleet state leaves no machine to switch
        return []


def switch_boxes() -> list[str]:
    """The machines the Disable / Enable button acts on: the fleet's machines, plus a box that [runners] boxes lists and [runners.ssh_hosts] names (a machine outside the sala
    fleet, such as spare-box, that has its ssh host written down). Sorted. Any other name is refused by the button, the route and switch_box alike."""
    hosts = conf("ssh_hosts")
    extra = {str(b) for b, h in (hosts.items() if isinstance(hosts, dict) else ()) if h and str(b) in _boxes() and _BOX_NAME.fullmatch(str(b))}
    return sorted(set(fleet_boxes()) | extra)


def _own_name() -> str:
    import socket
    try:
        return socket.gethostname().split(".")[0]
    except OSError:
        return ""


def _ssh_host(box: str) -> str:
    """The ssh host that reaches a box: [runners.ssh_hosts], else the box's own name when it is a fleet machine other than this one (pool-mode.sh runs `ssh <box>`); "" = none."""
    host = (conf("ssh_hosts") or {}).get(box)
    if host:
        return str(host)
    return box if box in fleet_boxes() and box != _own_name() else ""


def _read_remote(box: str, host: str, timeout: float) -> dict[str, Any]:
    """One status read over ssh. The remembered flavor first (powershell for a box not yet seen); a "command not found" (exit 127, or 1 from a Windows shell) or an answer that is not the
    status lines tries the other flavor, and the one that answered is remembered. The last error is raised."""
    first = _FLAVOR.get(box, "ps")
    order = [first] + [f for f in FLAVORS if f != first]
    err: RunnersError | None = None
    for fl in order:
        try:
            res = _parse_wsl(_ssh(host, timeout, fl))
        except RunnersError as e:
            err = e
            if str(e) in ("ssh exit 127", "ssh exit 1", "unexpected answer") and fl != order[-1]:
                continue
            raise
        with _SSH_LOCK:
            _FLAVOR[box] = fl
        return res
    raise err or RunnersError("unexpected answer")


def forget_switch(box: str) -> None:
    """Drop the cached read of a box's switch (after a button press), so the next snapshot reads it afresh."""
    with _SSH_LOCK:
        _SSH_CACHE.pop(box, None)


def _switch(box: str, dl: float) -> dict[str, Any]:
    """The switch of one box: {ok, mode, held, gate, since} or {ok: False, why: 'unreachable'|'unread', detail}. A remote box is read over ssh, cached per box."""
    local = str(conf("local_box") or "")
    if local and box == local:
        return _read_local()
    host = _ssh_host(box)
    if not conf("ssh_enabled") or not host:
        return {"ok": False, "why": "unread"}
    ttl = float(conf("ssh_cache_s"))
    with _SSH_LOCK:
        lock = _BOX_LOCKS.setdefault(box, threading.Lock())
    with lock:
        with _SSH_LOCK:
            hit = _SSH_CACHE.get(box)
        if hit and _now() - hit[0] < (ttl if hit[1].get("ok") else min(ttl, 60)):
            return hit[1]
        left = dl - _mono()
        if left < 2:
            return {"ok": False, "why": "unread", "detail": "out of time"}
        try:
            res = _read_remote(box, host, min(float(conf("ssh_timeout_s")), left))
        except RunnersError as e:
            d = str(e)
            res = {"ok": False, "why": "unreachable", "detail": d if _DETAIL.fullmatch(d) else "ssh failed"}
        with _SSH_LOCK:
            _SSH_CACHE[box] = (_now(), res)
        return res


def _why_offline(box: str, repo: str, name: str, sw: dict[str, Any], off_for: float | None = None) -> tuple[str, str]:
    """(kind, text) for an offline runner: switch (disabled / held / stopped by the gate), unreachable, unread, restarting, or fault. `off_for` is how long (seconds) the runner has been
    offline, as far as the snapshots know; the last case only is judged by it: offline for less than OFFLINE_GRACE_S is "restarting" (normal between two jobs of a runner that restarts after each
    one), at or past it, or with no time given, a fault."""
    if not sw.get("ok"):
        if sw.get("why") == "unreachable":
            return "unreachable", f"box not reachable ({sw.get('detail') or 'ssh failed'})"
        return "unread", "switch not read" + (" (no time left)" if sw.get("detail") else " (no ssh to this box)")
    if sw["mode"] == "off":
        return "switch", f"disabled on {box}"
    if repo in sw["held"]:
        return "switch", f"held for {repo} on {box}"
    if any(f".{name}." in g or g == name for g in (sw.get("gate") or [])):
        return "switch", f"stopped by the CI gate on {box}"
    if off_for is not None and off_for < OFFLINE_GRACE_S:
        return "restarting", f"offline for {_dur(off_for)}"
    return "fault", "offline, and the CI switch did not disable it"


def _publish_s() -> float:
    """[publish] every_minutes in seconds (10 minutes when absent or unreadable), the interval of the timer publish whose board render asks the side panel for a rebuild (render.py's _every_m reads the same key)."""
    try:
        m = float(_cfg.get("publish", "every_minutes", default=10) or 10)
    except (TypeError, ValueError):
        m = 10.0
    return max(m, 1.0) * 60


def _carry_s() -> float:
    """How old the previous snapshot may be for an offline mark to be carried from it: 3 times the slowest real rebuild interval, never less than OFFLINE_GRACE_S. Snapshots are rebuilt only when
    something asks: a viewer of /runners (cache_s, 25 s), the side panel at a board render (panel_refresh_s, 120 s, but renders come from the timer publish, [publish] every_minutes, 10 minutes, so
    with nobody viewing /runners the previous snapshot is about 10 minutes old at each rebuild). Like render.py's "last read at" note, the bound is 3 x the largest of these (30 minutes with the
    defaults): a rebuild every 10 minutes carries its marks, so a runner offline for good reaches the fault after OFFLINE_GRACE_S whether or not anyone views the page. A mark from a snapshot older
    than that is dropped and the clock starts again: the runner may have been back online unseen (a page nobody opened for hours, a long restart)."""
    return max(OFFLINE_GRACE_S, 3.0 * max(float(conf("cache_s")), float(conf("panel_refresh_s")), _publish_s()))


def _offline_since(prev_row: dict[str, Any] | None, now: float, prev_ts: float | None = None) -> float:
    """When this offline runner was first seen offline: the mark its row in the previous snapshot carries (the snapshot is also kept in a file, so a quick restart does not lose it), else now.
    The mark is carried only from a snapshot read at most _carry_s() ago: from an older one (a page nobody opened, a long restart) the runner may have been back online unseen, and a clock
    started from it would turn a short gap into a fault at once. A row that was online there has no mark, so a runner that came back online and goes offline again starts a new clock.
    A mark that is not a plausible time is ignored."""
    recent = isinstance(prev_ts, (int, float)) and not isinstance(prev_ts, bool) and 0 <= now - prev_ts <= _carry_s()
    if recent and isinstance(prev_row, dict) and prev_row.get("state") == "offline":
        t = prev_row.get("off_since")
        if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t <= now:
            return float(t)
    return now


# ----------------------------------------------------------------------------- the button
SWITCH_ACTIONS = {"off": "Disable", "on": "Enable"}      # pool-mode.sh's verbs, and the button's words
_SWITCH_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "SSH_AUTH_SOCK", "XDG_RUNTIME_DIR")      # all a pool-mode.sh run needs; none of the server's own settings or secrets
_SWITCH_LOCKS: dict[str, threading.Lock] = {}
_BOX_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
_NOTE_MAX = 800


def switch_script() -> str:
    """The configured pool-mode.sh path (~ expanded); "" when none is set."""
    return os.path.expanduser(str(conf("switch_script") or "").strip())


def switch_enabled() -> bool:
    return bool(switch_script())


def _clean_text(s: str, limit: int = _NOTE_MAX) -> str:
    s = "".join(ch if ch in "\n\t" or ch >= " " else " " for ch in s.replace("\r", ""))
    s = "\n".join(ln.rstrip() for ln in s.strip().splitlines() if ln.strip())
    return s if len(s) <= limit else s[:limit].rstrip() + " …"


def _switch_text(box: str, action: str, ok: bool, note: str = "") -> str:
    if ok and action == "off":
        t = f"{box} is disabled: a job already running finishes, then it takes no new job."
    elif ok:
        t = f"{box} is enabled: it takes jobs again within about 30 s."
    else:
        t = f"{SWITCH_ACTIONS[action]} {box} failed."
    return t + (f"\n{note}" if note else "")


def switch_box(box: str, action: str) -> tuple[bool, str]:
    """The Disable / Enable button: runs `bash <switch_script> <off|on> <box>` (pool-mode.sh) on this machine, which flips that machine's CI switch (mode file; pool-mode.sh reaches a remote
    machine over `ssh <box>` itself). An argument list, never a shell string; the box must be a fleet machine or a [runners] boxes entry named in [runners.ssh_hosts] (switch_boxes) and the action
    off or on, checked here again whatever the caller did; a minimal
    environment; its own session, killed as a group after [runners] switch_timeout_s. Returns (ok, text) with text safe to show (our own sentences plus pool-mode.sh's `pool-mode:` lines, cut short,
    control characters dropped; nothing else of its output on success). One call per box at a time. Drops that box's cached read and marks the snapshot out of date, so the page shows the new state at once."""
    if action not in SWITCH_ACTIONS:
        return False, "The action must be off (Disable) or on (Enable)."
    if not _BOX_NAME.fullmatch(box or "") or box not in switch_boxes():
        return False, "That is not a machine of the fleet."
    script = switch_script()
    if not script:
        return False, "The Disable and Enable buttons are not set up on this board ([runners] switch_script is empty)."
    if not os.path.isfile(script):
        return False, "The CI switch script ([runners] switch_script) was not found on this machine."
    with _SSH_LOCK:
        lock = _SWITCH_LOCKS.setdefault(box, threading.Lock())
    if not lock.acquire(blocking=False):
        return False, f"A change for {box} is already running; wait for it to end."
    try:
        timeout = max(5.0, float(conf("switch_timeout_s")))
        env = {k: os.environ[k] for k in _SWITCH_ENV if k in os.environ}
        argv = ["bash", script, action, box]
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", env=env,
                                 cwd=os.path.expanduser("~"), start_new_session=True)
        except (OSError, subprocess.SubprocessError):
            return False, _switch_text(box, action, False, "The CI switch script could not be started.")
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)                 # our own child's group (start_new_session): this stops the script; GNU timeout in pool-mode.sh puts ssh in its own group, so a hung timeout/ssh child outlives the kill until its own 60 s limit
            except OSError:
                pass
            try:
                p.communicate(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            return False, _switch_text(box, action, False, f"It took longer than {int(timeout)} s and was stopped; the machine may or may not have changed: check the page.")
        wrote = any(ln.strip() == f"mode file: {action}" for ln in (out or "").splitlines())
        refused = f"pool-mode: could not {action} {box}" in (err or "")
        ok = p.returncode == 0 or (wrote and not refused)        # the mode file is the switch: a failed GitHub listing after it (exit 1) does not undo it
        lines = [ln for ln in (err or "").splitlines() if ln.startswith("pool-mode:")]
        if ok and p.returncode != 0:
            note = "The switch is set, but pool-mode.sh could not list the organization's runners afterwards (" + (_clean_text("\n".join(lines), 300) or f"exit {p.returncode}") + ")."
        elif ok:
            note = ""
        else:
            note = _clean_text("\n".join(lines) or (err or out or f"exit {p.returncode}"))
        return ok, _switch_text(box, action, ok, note)
    finally:
        lock.release()
        forget_switch(box)
        mark_dirty()


# ----------------------------------------------------------------------------- the snapshot
_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()
_DIRTY = {"gen": 0}      # counts the button presses (mark_dirty); it survives the cache being replaced, so a press that came while a rebuild ran is not lost when that rebuild lands


def reset() -> None:
    """Forget the cached snapshot and the ssh reads (tests)."""
    with _LOCK:
        _CACHE.clear()
        _OWNERS.clear()
        _OWNER_FAIL.clear()
        _PEEK["thread"] = None
        _SERVE["thread"] = None
        _SERVE["since"] = 0.0
        _PEEK["pub"] = None
        if hasattr(_PEEK["retry"], "cancel"):
            _PEEK["retry"].cancel()
        _PEEK["retry"] = None
    with _SSH_LOCK:
        _SSH_CACHE.clear()
        _FLAVOR.clear()
        _BOX_LOCKS.clear()
        _SWITCH_LOCKS.clear()


def mark_dirty() -> None:
    """The cached snapshot is out of date (a button press changed a switch): the next snapshot() and peek() rebuild at once instead of waiting out cache_s."""
    with _LOCK:
        _DIRTY["gen"] += 1
        c = _CACHE.get("snap")
        if c:
            _CACHE["snap"] = {**c, "dirty": True}


def _at(c: dict[str, Any]) -> float:
    """When a cached snapshot was last asked for: its own time, or the later time of a rebuild that read nothing and kept its runners (`checked`), so that rebuild is not repeated at once."""
    return max(float(c["ts"]), float(c.get("checked") or 0))


def _say(e: Exception) -> str:
    """What the page may say of a failure: our own RunnersError text, else only the kind of the exception."""
    return str(e) if isinstance(e, RunnersError) else f"unexpected answer ({e.__class__.__name__})"


def _build(prev: dict[str, Any] | None = None) -> dict[str, Any]:
    """One full read. `prev` is the snapshot before it: a busy runner that no run names yet (or any more) is told apart by what it was doing there (_gap_job)."""
    dl = _mono() + float(conf("build_s"))
    runners: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    failed: list[str] = []                              # lists that could not be read: a repo's name, or "org:<login>" (a jobs-only failure is an error but not a failure of the list)
    listed: list[tuple[str, dict[str, Any]]] = []       # (column key, GitHub's runner) in the order read; a column key is a repo's name, or "<login>/*" for an org's shared runners
    seen: set[tuple[Any, str]] = set()
    orgs: list[str] = []

    def take(col: str, lst: list[dict[str, Any]]) -> None:
        for r in lst:                                   # one runner shows once (same id and name), in the column that read it first: the repo's own before its org's
            k = (r.get("id"), str(r.get("name")))
            if isinstance(r.get("id"), int) and k in seen:
                continue
            seen.add(k)
            listed.append((col, r))

    for repo in _repos():
        owner_err = ""
        try:
            login, typ = _owner_of(repo, dl)
            if typ.lower() == "organization" and login not in orgs:
                orgs.append(login)
        except Exception as e:  # noqa: BLE001  — without the owner only the repo's own runners can be read; the page says so
            owner_err = _say(e)
        try:
            take(repo, _list_runners(repo, dl))
        except Exception as e:  # noqa: BLE001  — whatever shape GitHub's answer had (a cut-off read, a non-dict, a non-numeric count): this repo is an error, the other still shows
            errors[repo] = f"{repo}: {_say(e)}"
            failed.append(repo)
            continue
        if owner_err:
            errors["account:" + repo] = f"{repo}: the account that owns it could not be read ({owner_err}), so an organization's shared runners may be missing"      # a line, never a column (only `failed` makes an unknown cell)
    for login in orgs:                                  # a repo owned by an organization: the org's runners serve it (on GitHub Free the Default runner group, which has every repo)
        try:
            take(login + ORG_MARK, _list_at(f"/orgs/{login}", f"organization {login}", dl))
        except Exception as e:  # noqa: BLE001
            errors["org:" + login] = _org_error(login, e)
            failed.append("org:" + login)
    for col, r in listed:
        on = r.get("status") == "online"
        x: dict[str, Any] = {"name": str(r.get("name") or ""), "repo": col, "box": _box_of(r), "state": ("running" if r.get("busy") else "idle") if on else "offline",
                             "job": None, "kind": "", "reason": "", "disabled": False, "stopping": False}
        runners.append(x)
    # The running jobs. A repo's own runner is looked for in that repo's runs; an org runner (any repo's jobs) in the runs of every repo that read, in config order.
    jobs: dict[str, dict[str, Any]] = {}
    ended: dict[str, dict[str, Any]] = {}               # busy runners' jobs GitHub already lists as completed (the runner is closing them down)
    for repo in _repos():
        busy = {x["name"] for x in runners if x["state"] == "running" and x["repo"] == repo}
        if busy and repo not in failed:
            _find_jobs(repo, busy, dl, jobs, errors, ended)
    shared = {x["name"] for x in runners if x["state"] == "running" and x["repo"].endswith(ORG_MARK)}
    for repo in _repos():
        if shared - set(jobs) and repo not in failed:
            _find_jobs(repo, shared, dl, jobs, errors, ended)
    before = {(x.get("repo"), x.get("name")): x for x in (prev or {}).get("runners") or [] if isinstance(x, dict)}
    mismatch = {k for k, x in before.items() if isinstance(x.get("job"), dict) and x["job"].get("phase") == "lost"}      # already a mismatch: not looked for again in the queued runs
    for repo in _repos():                               # a job just picked up can still sit in a queued run
        want = {x["name"] for x in runners if x["state"] == "running" and x["name"] not in jobs and x["name"] not in ended and (x["repo"], x["name"]) not in mismatch
                and (x["repo"] == repo or x["repo"].endswith(ORG_MARK))}
        if want and repo not in failed:
            _find_jobs(repo, want, dl, jobs, errors, None, "queued", MAX_QUEUED)
    now = _now()
    for x in runners:
        if x["state"] != "running":
            continue
        nm = x["name"]
        end = ended.get(nm)
        if nm in jobs:
            x["job"] = _job_info(x["repo"], jobs[nm])
        elif end and now - _epoch(end["job"].get("completed_at")) <= GAP_S:
            x["job"] = {**_job_info(x["repo"], end, "finishing"), "gap": _epoch(end["job"].get("completed_at"))}
        else:
            x["job"] = _gap_job(x["repo"], before.get((x["repo"], nm)), (prev or {}).get("ts"), now)
    sw = _read_switches(list(dict.fromkeys([x["box"] for x in runners] + _boxes())), dl)       # every machine on the page: its mode says "disabled" for an idle or a running runner too, and a machine with no runner still gets its button
    for x in runners:
        s = sw[x["box"]]
        stops = bool(s.get("ok") and (s["mode"] == "off" or x["repo"] in s["held"]))      # the CI switch is on its way to taking this runner off
        if x["state"] == "offline":
            x["off_since"] = _offline_since(before.get((x["repo"], x["name"])), now, (prev or {}).get("ts"))      # online rows carry no mark: coming back online clears the clock
            x["kind"], x["reason"] = _why_offline(x["box"], x["repo"], x["name"], s, now - x["off_since"])
            x["disabled"] = x["kind"] == "switch"
        else:
            x["disabled"] = stops and x["state"] == "idle"          # an idle runner of a disabled machine is about to go offline; a running one finishes its job first
            x["stopping"] = stops and x["state"] == "running"
    return {"ts": _now(), "errors": errors, "failed": failed, "runners": runners, "switch": sw, "stale": False}


def _read_switches(boxes: list[str], dl: float) -> dict[str, dict[str, Any]]:
    """The switch of each box, read in parallel (a slow ssh to one machine does not hold the others)."""
    def one(b: str) -> dict[str, Any]:
        if b == "other":
            return {"ok": False, "why": "unread"}
        try:
            return _switch(b, dl)
        except Exception:  # noqa: BLE001  — a read that failed any other way is an unread switch, never a broken page
            return {"ok": False, "why": "unread"}
    if len(boxes) <= 1:
        return {b: one(b) for b in boxes}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(boxes))) as ex:
        return dict(zip(boxes, ex.map(one, boxes)))


def _find_jobs(repo: str, busy: set[str], dl: float, jobs: dict[str, dict[str, Any]], errors: dict[str, str], ended: dict[str, dict[str, Any]] | None = None,
               status: str = "in_progress", limit: int = MAX_RUNS) -> None:
    busy = busy - set(jobs)
    if not busy:
        return
    try:
        _jobs_of(repo, busy, dl, jobs, ended, status, limit)
    except Exception as e:  # noqa: BLE001  — the jobs are the garnish: the runners stay, a running one says its job was not found
        errors.setdefault("jobs:" + repo, f"{repo}: the running jobs could not be read ({_say(e)})")      # a line, never a column


def _unread(why: str, stale: bool = False) -> dict[str, Any]:
    """A snapshot of nothing read: every repo's list failed."""
    return {"ts": _now(), "errors": {"all": why}, "failed": _repos(), "runners": [], "stale": stale}


def snapshot(force: bool = False) -> dict[str, Any]:
    """The runners, cached for [runners] cache_s. Single flight: one thread rebuilds (under [runners] build_s, GitHub and ssh together); a thread that
    asks meanwhile gets the previous snapshot at once, marked stale, and waits for the build only when there is no previous one. The result,
    errors included, is cached like any other."""
    with _LOCK:
        c = _CACHE.get("snap")
        if c and not force and not c.get("dirty") and _now() - _at(c) < float(conf("cache_s")):
            return c
        b = _CACHE.get("building")
        if b is not None and _mono() - b["since"] > float(conf("build_s")) + 30:
            b = None                                    # a mark older than build_s + 30 s is abandoned (a build that never came back): a new build may start
        if b is None:
            _CACHE["building"] = mine = {"ev": threading.Event(), "since": _mono()}
            gen0 = _DIRTY["gen"]                        # a button press after this point is not in what this build reads
        elif c:
            return {**c, "stale": True}
    if b is not None:                                   # no previous snapshot: wait for the build in flight (it is bounded by build_s)
        b["ev"].wait(float(conf("build_s")) + float(conf("ssh_timeout_s")) + 5)
        with _LOCK:
            return _CACHE.get("snap") or _unread("the runners could not be read yet", True)
    snap: dict[str, Any] = _unread("the runners could not be read")
    try:
        snap = _build(c)
    except Exception as e:  # noqa: BLE001  — a failure past the per-repo guards: say so, keep the page up
        snap = _unread(_say(e))
    finally:
        built = snap
        snap = _keep_last(c, snap)                      # a rebuild that read nothing does not replace the last good runners
        with _LOCK:
            _CACHE["snap"] = {**snap, "dirty": True} if _DIRTY["gen"] != gen0 else snap       # a press during the build: the next serve() rebuilds again
            if _CACHE.get("building") is mine:          # not a newer build's mark, when this one was given up on
                _CACHE.pop("building", None)
        mine["ev"].set()
    if snap is built:
        _save(snap)
    return snap


def _keep_last(prev: dict[str, Any] | None, snap: dict[str, Any]) -> dict[str, Any]:
    """`snap` when it read something. When it read nothing (every list failed) and there is a previous snapshot with runners: that snapshot's runners, switches and time,
    with only the error line new (it says how old the runners shown are), and `checked` set so the next try waits cache_s as after any other build."""
    if not prev or not prev.get("runners") or snap.get("runners") or not (snap.get("failed") or (snap.get("errors") or {}).get("all")):
        return snap
    say = "; ".join(str(v) for v in (snap.get("errors") or {}).values()) or "the runners could not be read"
    return {**{k: v for k, v in prev.items() if k != "dirty"}, "errors": {"all": f"{say} (showing the runners read {_dur(_now() - prev['ts'])} ago)"},
            "checked": _now(), "stale": False}


# ----------------------------------------------------------------------------- the pages' answer: stale while revalidate
# A page request never builds. serve() hands back the last snapshot at once (read from the file below after a restart) and, when it is due, starts ONE background
# rebuild through snapshot()'s single flight, so the pages draw in milliseconds however slow GitHub and ssh are, and the calls to them are no more frequent than before
# (one rebuild per cache_s at most, shared by every viewer, the side panel's peek included). The answer says honestly how old it is and whether a rebuild is running.
PERSIST = False          # the last snapshot is kept in a file under the state dir across restarts only when this is on: server.py turns it on in __main__ (a test that builds a snapshot writes nothing)
SNAP_FILE = "runners-snapshot.json"
_SERVE: dict[str, Any] = {"thread": None, "since": 0.0}
OVERRUN = 2.0            # a rebuild running longer than this many times build_s (the time one is given, 20 s) has overrun: the page then says it is not refreshed
_ROW_STATES = ("running", "idle", "offline")


def _file() -> Any:
    try:
        return _cfg.state(SNAP_FILE)
    except Exception:  # noqa: BLE001  — no state dir configured: nothing is kept
        return None


def _save(snap: dict[str, Any]) -> None:
    """The snapshot to the file (a temp file in the same folder renamed over the old one, so a reader sees the old answer or the new one, never half a file). A snapshot of nothing
    read (every list failed) is not kept: the last good one stays. Nothing here may break a build."""
    p = _file()
    if not PERSIST or p is None or (not snap.get("runners") and (snap.get("failed") or (snap.get("errors") or {}).get("all"))):
        return
    data = {"version": 1, **{k: snap[k] for k in ("ts", "errors", "failed", "runners", "switch") if k in snap}}
    try:
        import tempfile
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".runners-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001
        pass


def _valid(d: Any) -> bool:
    """A saved snapshot is used only when it has the shape the pages draw from (a file from another version, or damaged, is ignored)."""
    if not isinstance(d, dict) or d.get("version") != 1 or isinstance(d.get("ts"), bool) or not isinstance(d.get("ts"), (int, float)) or not 0 < d["ts"] <= _now() + 300:
        return False
    if not isinstance(d.get("errors"), dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in d["errors"].items()):
        return False
    if not isinstance(d.get("failed"), list) or not all(isinstance(v, str) for v in d["failed"]) or not isinstance(d.get("switch"), dict):
        return False
    rs = d.get("runners")
    return isinstance(rs, list) and all(isinstance(x, dict) and all(isinstance(x.get(k), str) for k in ("name", "repo", "box", "kind", "reason")) and x.get("state") in _ROW_STATES
                                        and (x.get("job") is None or (isinstance(x.get("job"), dict) and "started" in x["job"])) for x in rs)


def restore() -> bool:
    """Server start: take the saved snapshot as the last answer, when there is a usable one and none is cached yet. It is due by its own time, so the first request after a
    restart is answered from it and starts the one rebuild when it is older than cache_s. True when a snapshot was taken."""
    p = _file()
    if p is None or not enabled():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not _valid(d):
        return False
    with _LOCK:
        if _CACHE.get("snap"):
            return False
        _CACHE["snap"] = {"ts": float(d["ts"]), "errors": d["errors"], "failed": d["failed"], "runners": d["runners"], "switch": d["switch"], "stale": False}
    return True


def _serve_run() -> None:
    try:
        snapshot(force=True)
    except Exception:  # noqa: BLE001  — snapshot() guards itself; a thread must not die loudly
        pass
    finally:
        with _LOCK:
            if _SERVE["thread"] is threading.current_thread():      # not a newer thread's, when this one was given up on
                _SERVE["thread"] = None


def _build_since_locked() -> float | None:
    """When the rebuild in flight started (monotonic clock; the caller holds _LOCK): the older of this page's thread and the side panel's, neither one older than build_s + 30 s
    (snapshot() gives those up: a stalled build does not block the rebuilds after it until a restart). None when no rebuild is in flight."""
    t = _SERVE["thread"]
    b = _CACHE.get("building")
    limit = float(conf("build_s")) + 30
    starts = []
    if t is not None and t.is_alive() and _mono() - _SERVE["since"] <= limit:
        starts.append(_SERVE["since"])
    if b is not None and _mono() - b["since"] <= limit:
        starts.append(b["since"])
    return min(starts) if starts else None


def _building_locked() -> bool:
    """A rebuild is in flight (the caller holds _LOCK): this page's thread, or the side panel's."""
    return _build_since_locked() is not None


def serve() -> dict[str, Any]:
    """The snapshot for a page, at once. A copy of the last one with `age_s`, `refreshing` (a rebuild is running) and `stale`, and `pending` with no runners when nothing was ever read
    (the page draws a placeholder and asks again). When the snapshot is older than cache_s (or a button press marked it out of date) and no rebuild runs, starts one in a thread: at most
    one, whoever asks. `stale` (the page dims the table and says "not refreshed since") means the numbers are not about to be replaced: the last rebuild read nothing, the running one
    has overrun (longer than OVERRUN x build_s), or a rebuild was due and none could start. Age alone never makes it stale: a snapshot an idle page left behind is drawn at full
    strength while its rebuild runs."""
    if not enabled():                                   # no repo listed: nothing to read, so no thread and no GitHub call; the pages say the board does not use runners
        return {"ts": _now(), "errors": {}, "failed": [], "runners": [], "switch": {}, "stale": False, "refreshing": False, "age_s": 0}
    with _LOCK:
        c = _CACHE.get("snap")
        due = c is None or bool(c.get("dirty")) or _now() - _at(c) >= float(conf("cache_s"))
        running = _building_locked()
        if due and not running:
            th = threading.Thread(target=_serve_run, name="runners-serve", daemon=True)
            _SERVE["thread"], _SERVE["since"] = th, _mono()
            try:
                th.start()
                running = True
            except Exception:  # noqa: BLE001  — no thread to be had: the pages go on with the last snapshot
                _SERVE["thread"] = None
        since = _build_since_locked()
    if c is None:
        return {"ts": 0, "errors": {}, "failed": [], "runners": [], "switch": {}, "stale": False, "pending": True, "refreshing": running, "age_s": 0}
    age = max(0.0, _now() - c["ts"])
    failed = bool((c.get("errors") or {}).get("all"))            # the last rebuild read nothing (every list failed): the numbers shown are older ones, kept
    overrun = since is not None and _mono() - since > OVERRUN * float(conf("build_s"))
    return {**c, "dirty": False, "age_s": int(age), "refreshing": running, "stale": failed or overrun or (due and not running)}


# ----------------------------------------------------------------------------- the side panel
AUTOSTART = False        # peek() starts a background rebuild only when this is on: server.py turns it on in __main__ (never at import, so a test that renders the board makes no GitHub call)
ON_CHANGE: Any = None    # called (no arguments) when a rebuild peek() started ends with different panel counts; returns True when a publish was scheduled, False when it could not be
                         # (one is running and would not take it). server.py sets it to a wrapper of its debounced publish, so the static board page catches up
RETRY_S = 10.0           # a request the hook turned down (False) is asked again this often…
RETRY_MAX_S = 120.0      # …for this long, then given up quietly (the next publish, at most the idle interval away, draws the panel anyway)
_PEEK: dict[str, Any] = {"thread": None, "pub": None, "retry": None}


def _ask(t0: float) -> None:
    """One request for a republish. True takes the throttle slot (one per panel_refresh_s) and ends the chain; False tries again in RETRY_S until RETRY_MAX_S
    since the first try; an exception or no hook ends the chain without taking the slot. One chain at a time (_PEEK["retry"])."""
    done = True
    try:
        cb = ON_CHANGE
        if cb is not None and cb():
            with _LOCK:
                _PEEK["pub"] = _now()
        elif cb is not None and _mono() - t0 + RETRY_S <= RETRY_MAX_S:
            done = False
            tm = threading.Timer(RETRY_S, _ask, args=(t0,))
            tm.daemon = True
            with _LOCK:
                _PEEK["retry"] = tm
            tm.start()
    except Exception:  # noqa: BLE001  — a failed request for a publish never breaks the rebuild (or the retry chain's thread)
        done = True
    finally:
        if done:
            with _LOCK:
                _PEEK["retry"] = None


def _notify(before: dict[str, Any] | None, after: dict[str, Any] | None) -> None:
    """Ask for a republish when the panel's numbers differ between two snapshots, at most once per panel_refresh_s (a rebuild only starts that often; this holds it even
    so). The slot is taken when the hook says a publish was scheduled; if it says no, the request is repeated every RETRY_S for up to RETRY_MAX_S, one chain at a time."""
    if ON_CHANGE is None or after is None or (before is not None and counts(before) == counts(after)):
        return
    with _LOCK:
        last = _PEEK["pub"]
        if (last is not None and _now() - last < float(conf("panel_refresh_s"))) or _PEEK["retry"] is not None:
            return
        _PEEK["retry"] = True                           # the chain is claimed until _ask ends it
    _ask(_mono())


def _peek_run(before: dict[str, Any] | None = None) -> None:
    try:
        after = snapshot()                              # the single flight: a build already running (the /runners page's) is not doubled; the result, errors included, is cached
        _notify(before, after)
    except Exception:  # noqa: BLE001  — snapshot() guards itself; a thread must not die loudly
        pass
    finally:
        with _LOCK:
            _PEEK["thread"] = None


def peek() -> dict[str, Any] | None:
    """The last snapshot, never built here: None when there is none yet. When it is missing or older than [runners] panel_refresh_s (not cache_s: that one is
    the /runners page's), and AUTOSTART is on and [runners] panel is not false, starts at most one background rebuild (one peek thread at a time, and none while
    snapshot() has a build in flight), so however many page views and renders there are, the panel causes at most one rebuild per panel_refresh_s. When that
    rebuild ends with other counts, ON_CHANGE asks for a republish. Returns at once, whatever GitHub or ssh are doing. None, and no rebuild, when enabled() is False."""
    if not enabled():
        return None                                     # off: no snapshot, no rebuild (the side panel draws no Runners section)
    with _LOCK:
        c = _CACHE.get("snap")
        if c and not c.get("dirty") and _now() - _at(c) < float(conf("panel_refresh_s")):
            return c
        t = _PEEK["thread"]
        if AUTOSTART and conf("panel") and (t is None or not t.is_alive()) and _CACHE.get("building") is None:
            th = threading.Thread(target=_peek_run, args=(c,), name="runners-peek", daemon=True)
            _PEEK["thread"] = th
            try:
                th.start()
            except Exception:  # noqa: BLE001  — no thread to be had: the render goes on with the last snapshot
                _PEEK["thread"] = None
        return c


def label(repo: str) -> str:
    """The short name the panel shows for a repo: [runners.labels], else the repo's own name; for an organization's shared runners ("<login>/*"), the same lookup, else the login."""
    m = _cfg.get("runners", "labels")
    v = m.get(repo) if isinstance(m, dict) else None
    return str(v) if v else (repo[:-len(ORG_MARK)] if repo.endswith(ORG_MARK) else repo)


def _machines(runners: list[dict[str, Any]]) -> list[str]:
    """The rows, in the Machines panel's order (fleet.machines_order: the publisher, the other fleet machines by letter, then the ssh-read hosts): the machines that are
    in [runners] boxes or that a runner's labels named, and "other" (a runner no label or name placed) last when such a runner exists. A machine the Machines panel does not
    list goes after those, in the order it had before: the [runners] boxes in config order, then the other machines the labels named (sorted)."""
    have = {x["box"] for x in runners}
    known = _boxes()
    rows = known + sorted(have - set(known) - {"other"}) + (["other"] if "other" in have else [])
    try:
        order = {n: i for i, n in enumerate(_fleet.machines_order())}
    except Exception:                                    # an unreadable fleet state leaves the old order
        order = {}
    return sorted(rows, key=lambda b: order.get(b, len(order)))      # stable: unlisted machines keep their old order after the listed ones


def _columns(snap: dict[str, Any]) -> list[str]:
    """The columns: the org-shared ones first ("<login>/*", from the runners and from an org whose read failed), then the configured repos. Once an org column exists a repo with
    no runners of its own whose list read did not fail is left out (its jobs run on the org's runners); with none, a column per repo as before. A column comes from the runners
    and from `failed` only: an error about the owner or the running jobs is a line above the table and never makes a column."""
    runners, failed = snap.get("runners") or [], snap.get("failed") or []
    orgs: list[str] = []
    for c in [x["repo"] for x in runners if x["repo"].endswith(ORG_MARK)] + [k[4:] + ORG_MARK for k in failed if k.startswith("org:")]:
        if c not in orgs:
            orgs.append(c)
    have = {x["repo"] for x in runners}
    return orgs + [r for r in _repos() if not orgs or r in have or r in failed]


def counts(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """The panel's numbers from a snapshot: a card per machine (the Machines panel's order; a machine it does not list: [runners] boxes order, then the other machines the labels named, then "other" when such a runner exists), each with a line per
    column that has runners on it (a repo, or an organization's shared runners, `_columns`): online = runners with status online, active = those running a job; none online reads state "offline". A repo whose GitHub
    runner list could not be read (snapshot["failed"]; a failed read of the running jobs does not count) reads "unknown" on every box, since silence would read as
    no runners."""
    runners = snap.get("runners") or []
    failed = set(snap.get("failed") or [])
    out = []
    for b in _machines(runners):
        lines = []
        for r in _columns(snap):
            mine = [x for x in runners if x["box"] == b and x["repo"] == r]
            if not mine:
                if r in failed or (r.endswith(ORG_MARK) and "org:" + r[:-len(ORG_MARK)] in failed):
                    lines.append({"repo": r, "label": label(r), "active": 0, "online": 0, "state": "unknown"})
                continue
            on = [x for x in mine if x["state"] != "offline" or x.get("kind") == "restarting"]      # a runner restarting between jobs counts as online, as on the cards
            lines.append({"repo": r, "label": label(r), "active": sum(1 for x in on if x["state"] == "running"), "online": len(on), "state": "ok" if on else "offline"})
        sw = (snap.get("switch") or {}).get(b) or {}
        card: dict[str, Any] = {"box": b, "lines": lines}
        if sw.get("ok") and sw.get("mode") == "off" and not any(x["box"] == b and x["state"] == "running" for x in runners):
            card["disabled"] = True                           # the machine's CI switch is off and no job is left on it: the panel reads "disabled"
        out.append(card)
    return out


def card_total(card: dict[str, Any]) -> dict[str, str]:
    """One machine's single count for the side panel's one-line card: {"text", "cls"} from a counts() card. The runners of every repo it serves are summed
    (`busy/online`); cls is `idle` (no runner busy: muted), `busy` (some busy: bold) or `full` (every online runner busy: bold amber, new jobs wait). No online runner
    reads `offline`, a read that failed `unknown`, a machine with no line `no runners` (all `idle`); a sum beside a repo that could not be read carries a ` ?`.
    A machine whose CI switch is off with no job left on it reads `disabled` (cls `off`: amber)."""
    lines = card["lines"]
    if card.get("disabled"):
        return {"text": "disabled", "cls": "off"}
    ok = [x for x in lines if x["state"] == "ok"]
    if ok:
        act, on = sum(x["active"] for x in ok), sum(x["online"] for x in ok)
        q = " ?" if any(x["state"] == "unknown" for x in lines) else ""
        return {"text": f"{act}/{on}{q}", "cls": "full" if act >= on else "busy" if act else "idle"}
    if any(x["state"] == "unknown" for x in lines): return {"text": "unknown", "cls": "idle"}
    return {"text": "offline" if lines else "no runners", "cls": "idle"}


# ----------------------------------------------------------------------------- the page


def _dur(s: float) -> str:
    s = max(0, int(s))
    if s < 60:
        return f"{s}s"
    m = s // 60
    return f"{m}m" if m < 60 else f"{m // 60}h {m % 60:02d}m"


def asof_html(snap: dict[str, Any], now: float) -> str:
    """The lines above the table that say how old it is: when it was read and how long ago, whether a rebuild is running now, and, only when no rebuild has landed for longer
    than one takes (snap["stale"], serve()), that it was not refreshed since. Both copies of the page draw it."""
    import datetime as dt
    when = f'{dt.datetime.fromtimestamp(snap["ts"], _cfg.tz()).strftime("%H:%M:%S")} {_cfg.tz_abbr()}'
    age = max(0, int(now - snap["ts"]))
    bits = [f"Updated {when}"] + ([f"{_dur(age)} ago"] if age >= 5 else []) + (["refreshing now"] if snap.get("refreshing") else []) + ["page checks every 30 s"]
    out = f'<p class="sub rasof">{" · ".join(bits)}</p>'
    if snap.get("stale"):
        out += f'<p class="rstale" role="status">not refreshed since {when}</p>'
    return out


def pending_html() -> str:
    """Nothing has been read since the server started and no file was kept: the first read is running; the page asks again every few seconds."""
    return '<p class="sub rasof" role="status">Reading the runners from GitHub and the machines… this fills in by itself.</p>'
