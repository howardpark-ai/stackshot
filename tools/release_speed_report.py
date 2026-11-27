#!/usr/bin/env python3
"""tools/release_speed_report.py - the weekly release-speed report: how long each stage of a pull request's way to live takes. Makes no model call.

It reads the release logs `release.sh` keeps (`<state>/releases/pr-<N>.log`, lines that start with an ISO UTC time) and, from GitHub, the
merged pull requests and the pull-request check runs of the window. Run it weekly from the machine that has the release logs:

    python3 tools/release_speed_report.py [--github OWNER/REPO] [--repo NAME] [--logs DIR] [--days N]
                                          [--config FILE] [--state-dir DIR] [--dry-run] [--json] [--no-open] [--client PROGRAM]

The window is the last 7 days (`--days`), a rolling one: a pull request counts when its release reached `done:` (live) inside it. The stages, in
minutes, each with its count (n), median, p90 and worst (a stage a log or GitHub cannot give for a pull request leaves that pull request out of
that stage only; the worst pull request is named):

  open -> checks green     the PR's creation time to the moment its last required check run turned green on the final head: GitHub's runs
                           (the latest run of each workflow on the head, all green: the latest finish time), else the log's `checks pass`
  checks green -> queued   to the log's `enqueued` line of the release that went live: the hand-off to the release and any failed earlier
                           attempt of it are in this stage
  queued -> merged         `enqueued` to `merged` (the merge queue's own tests)
  merged -> live           `merged` to `done:` (the deploy and its health check)
  live -> main's check     `done:` to the log's `main's tests passed|pass` line (it does not block the release)
  open -> live             the PR's creation to `done:`: the number the first flag watches

A value below zero (a clock or a log out of order) is dropped from its stage and counted in a note.

Same-commit flakes, counted in the window, once each:
  * merge queue   an entry removed because the merge group failed its checks, whose head was later merged by the queue unchanged (the log);
  * PR runs       a workflow that failed on a head and later succeeded on the same head (GitHub's pull-request runs; a re-run of one run
                  shows only its last attempt there and is not seen);
  * main's run    a release whose log says the main run `failed only when measured, then passed plainly (flaky?)`, once per release.

Flags. Two keys, read from a small TOML file, `--config FILE` or `${XDG_CONFIG_HOME:-~/.config}/stackshot/release-speed.toml`; keys at the top
apply to every repository, a table named after the repository (`[stackshot]`) overrides them for it:

    max_open_to_live_median_minutes   default 60: flagged when the open -> live median is above it
    max_same_commit_flakes            default 4: flagged when the count is above it (5 or more)

plus `item_project` and `item_mover`, strings, where a flag's item goes and who moves it. A mistyped key warns on stderr (`warning: unknown key`);
a limit that is not a number from 0 to 10**12 (a boolean, a string, nan, inf, a negative), a file that is not UTF-8 text, a pipe or a device in place of
a file and one nested too deep are config problems, exit 2. A flag is a `FLAG: <which>` line at the end of the report and in the state file, and it
opens ONE item for the repository through the client's `post item-open` route (the same call, the same debt and the same rules as the test-trim
report's: no flag, no call; the call is made once and never retried; a failed call is owed again to the next weekly run, `open_pending`). The marker
is `release_speed:<repo>/<median|flakes>`: the same flags give the same marker, so an item still open is answered, not filed again. `--no-open` (and
`--dry-run`) prints what would be sent and calls nothing; `--client PROGRAM` names another client program.

State file: `${XDG_STATE_HOME:-~/.local/state}/stackshot/release-speed/<repo>.json` (--state-dir replaces the folder), written atomically; it is
what the next run compares with (the open -> live median and the flake count of the previous run). A previous record that cannot be used is started
over from with a one-line note. A window with no release in it leaves the previous record as it was, with one exception: an owed item that is paid in
such a run is removed from it (`open_pending`). --dry-run prints the report and writes nothing; --json prints the record instead of the text.
`--now ISO` sets the clock, for tests.

GitHub is asked for: one `gh pr list` (the merged pull requests of the window) and the pull-request runs of the window in day-long slices of 100 a
page (about 10 to 40 calls for a week; a slice GitHub cuts at 1000 is halved). With no `gh`, no login or an answer that cannot be read, the stages
that need GitHub are left out with a note, the flake count is the log's alone, and the status is 4. A run's stages are only what that run measured.
When the pull request list itself cannot be read, the last measured open -> live median is kept apart in the record, `open_to_live_kept`
({"median", "generated": when it was measured}): only a later "since the previous run" line uses it, saying it is from an earlier run and when; it
raises no flag and goes into no item. When the list is read and only the runs cannot be, the run's own numbers stand and nothing is kept.

Exit status: 0 the report was made (a flag included, and its item opened or answered, or not sent for --no-open), 1 the state folder or file cannot
be written, 2 a usage, config or logs-folder problem, 3 the report was made but the item was not opened, 4 the report was made but there was
nothing to report (no release in the window) or GitHub could not be read (3 wins when both happen, and both are on stderr)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_trim_report as TR       # the one place the item call, the config reader and the atomic state file are written; this report uses them as they are

FORMAT = 1
Fail = TR.Fail
DEFAULTS = {"max_open_to_live_median_minutes": 60, "max_same_commit_flakes": 4}
SHORT = {"max_open_to_live_median_minutes": "median", "max_same_commit_flakes": "flakes"}
ITEM_KEYS = TR.ITEM_KEYS
OPEN_KIND = "release_speed"
OPEN_SENDER = "release-speed-report"
STAGES = [("open_to_green", "PR open -> checks green"), ("green_to_queued", "checks green -> queued"), ("queued_to_merged", "queued -> merged"),
          ("merged_to_live", "merged -> live"), ("live_to_main", "live -> main's check"), ("open_to_live", "PR open -> live")]
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (.*)$")
START = re.compile(r"release of PRs? (#\d+(?: #\d+)*) starts in \S+(?: \(([^)]*)\))?")     # release.sh: one PR's start, or a group's "PRs #N #M" (every member's log has it)
CHECKS_PASS = re.compile(r"(checks pass|the PR's tests pass on the (?:updated|pushed) head)\b")
ENQUEUED = re.compile(r"enqueued: ")
MERGED = re.compile(r"merged( |$)")
DONE = re.compile(r"done: ")
MAIN_PASS = re.compile(r"main's tests (passed on|pass at) ")
FAILED = re.compile(r"(PR #\d+ )?FAILED at ")
QUEUE_FAIL = re.compile(r"FAILED at merge queue: removed from the merge queue: the merge group failed")
ENQ_HEAD = re.compile(r"enqueued: the merge queue accepted the head ([0-9a-f]+)")
MAIN_FLAKY = re.compile(r"main's run: .*failed only when measured, then passed plainly")
RUNS_PAGE = 100
RUNS_CAP = 1000            # GitHub returns at most this many results of one query
RUNS_PAGES_MAX = 60        # calls one run of the report may make for the runs, whatever GitHub answers


# ---------------------------------------------------------------- the release logs
def parse_stamp(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def read_segments(path: str, slug: str | None, notes: list[str]) -> list[dict]:
    """the releases in one pr-<N>.log: [{"pr", "start", "events": [(time, text)]}], one per `release of PR #N starts` line, of the repository `slug`"""
    segs: list[dict] = []
    cur = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = STAMP.match(line.rstrip("\n"))
                if not m:
                    continue                                   # the output blocks of a deploy carry no time
                try:
                    ts = parse_stamp(m.group(1))
                except ValueError:
                    continue
                s = START.match(m.group(2))
                if s:
                    cur = {"pr": int(s.group(1).split()[0][1:]), "start": ts, "events": [], "slug": s.group(2)}
                    segs.append(cur)
                if cur is not None:
                    cur["events"].append((ts, m.group(2)))
    except OSError as e:
        notes.append(f"the log {path} cannot be read: {e.strerror or e}")
        return []
    return [s for s in segs if slug is None or s["slug"] is None or s["slug"] == slug]


def first(events: list, pat: re.Pattern, after: dt.datetime | None = None):
    for ts, msg in events:
        if (after is None or ts >= after) and pat.match(msg):
            return ts
    return None


def analyse(seg: dict) -> dict:
    """the milestones of one release, None for the one its log does not have"""
    ev = seg["events"]
    enq = first(ev, ENQUEUED)
    merged = first(ev, MERGED)
    done = first(ev, DONE)
    stop = enq or merged or done
    checks = [ts for ts, msg in ev if CHECKS_PASS.match(msg) and (stop is None or ts <= stop)]
    return {"start": seg["start"], "checks_pass": checks[-1] if checks else None, "enqueued": enq, "merged": merged, "done": done,
            "main_pass": first(ev, MAIN_PASS, done) if done else None}


def queue_flakes(events: list) -> int:
    """entries the merge queue removed because the group failed, whose head was merged by the queue later unchanged, over all releases of one PR"""
    cur = None
    heads: list[tuple[str, str]] = []
    for _ts, msg in events:
        m = ENQ_HEAD.match(msg)
        if m:
            cur = m.group(1)
        elif cur and QUEUE_FAIL.match(msg):
            heads.append((cur, "fail"))
            cur = None
        elif cur and msg.startswith("merged by the merge queue as "):
            heads.append((cur, "ok"))
            cur = None
    return len({h for i, (h, o) in enumerate(heads) if o == "fail" and any(h2 == h and o2 == "ok" for h2, o2 in heads[i + 1:])})


def collect(logdir: str, slug: str | None, lo: dt.datetime, hi: dt.datetime, notes: list[str]) -> dict:
    """{"live": {pr: milestones}, "not_live": [pr], "failed_attempts": n, "queue_flakes": n, "main_flakes": n} for the releases in the window"""
    out = {"live": {}, "not_live": [], "failed_attempts": 0, "queue_flakes": 0, "main_flakes": 0}
    try:
        names = sorted(n for n in os.listdir(logdir) if re.fullmatch(r"pr-\d+\.log", n))
    except OSError as e:
        raise Fail(f"cannot read the release logs folder {logdir}: {e.strerror or e}")
    for name in names:
        segs = read_segments(os.path.join(logdir, name), slug, notes)
        pr = int(name[3:-4])
        mine = [s for s in segs if any(lo <= ts <= hi for ts, _ in s["events"][:1]) or any(lo <= ts <= hi and DONE.match(m) for ts, m in s["events"])]
        if not mine:
            continue
        live = None
        for s in mine:
            m = analyse(s)
            if m["done"] is not None and lo <= m["done"] <= hi:
                live = m
            if any(FAILED.match(msg) for _ts, msg in s["events"]) and lo <= s["start"] <= hi:
                out["failed_attempts"] += 1
            if lo <= s["start"] <= hi and any(MAIN_FLAKY.match(msg) for _ts, msg in s["events"]):
                out["main_flakes"] += 1
        out["queue_flakes"] += queue_flakes([e for s in mine for e in s["events"] if lo <= e[0] <= hi])
        if live is not None:
            out["live"][pr] = live
        else:
            out["not_live"].append(pr)
    return out


# ---------------------------------------------------------------- GitHub
def gh_json(*args: str):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise ValueError("the gh command is not installed")
    except subprocess.SubprocessError as e:
        raise ValueError(f"gh did not finish: {e}")
    if r.returncode != 0:
        raise ValueError(f"gh {args[0]} failed: {' '.join((r.stderr or r.stdout).split())[:200]}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise ValueError(f"gh {args[0]} printed something that is not JSON")


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_prs(slug: str, since: dt.datetime) -> dict[int, dict]:
    """{number: {"created", "merged", "head"}} of the pull requests merged since `since` (one call; a day of slack, the window is cut in code)"""
    rows = gh_json("pr", "list", "--repo", slug, "--state", "merged", "--search", f"merged:>={(since - dt.timedelta(days=1)).strftime('%Y-%m-%d')}",
                   "--limit", "1000", "--json", "number,createdAt,mergedAt,headRefOid")
    if not isinstance(rows, list):
        raise ValueError("gh pr list did not print a list")
    out = {}
    for r in rows:
        try:
            out[int(r["number"])] = {"created": dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")), "head": str(r.get("headRefOid") or ""),
                                     "merged": dt.datetime.fromisoformat(r["mergedAt"].replace("Z", "+00:00")) if r.get("mergedAt") else None}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def fetch_runs(slug: str, lo: dt.datetime, hi: dt.datetime, budget: list[int]) -> list[dict]:
    """the pull-request workflow runs created between lo and hi, in slices of a day (a slice GitHub reports above its 1000 result cut is halved); `budget` is the calls left"""
    out: list[dict] = []

    def slice_(a: dt.datetime, b: dt.datetime) -> None:
        got: list[dict] = []
        total = 0
        for page in range(1, RUNS_CAP // RUNS_PAGE + 1):
            if budget[0] <= 0:
                raise ValueError(f"more than {RUNS_PAGES_MAX} calls for the runs: the window is too busy to read")
            budget[0] -= 1
            d = gh_json("api", f"repos/{slug}/actions/runs?event=pull_request&per_page={RUNS_PAGE}&page={page}&created={iso(a)}..{iso(b)}")
            if not isinstance(d, dict) or not isinstance(d.get("workflow_runs"), list):
                raise ValueError("gh api printed no workflow_runs list")
            total = d.get("total_count") if isinstance(d.get("total_count"), int) else len(d["workflow_runs"])
            got.extend(r for r in d["workflow_runs"] if isinstance(r, dict))
            if len(d["workflow_runs"]) < RUNS_PAGE or len(got) >= total:
                break
            if total > RUNS_CAP and (b - a) > dt.timedelta(minutes=30):
                break                       # the first page already says the slice is over the cut: halve it, do not page through what is cut anyway
        if total > RUNS_CAP and (b - a) > dt.timedelta(minutes=30):
            mid = a + (b - a) / 2
            slice_(a, mid)
            slice_(mid + dt.timedelta(seconds=1), b)
        else:
            out.extend(got)

    a = lo
    while a < hi:
        b = min(a + dt.timedelta(days=1) - dt.timedelta(seconds=1), hi)
        slice_(a, b)
        a = b + dt.timedelta(seconds=1)
    seen, uniq = set(), []
    for r in out:
        if r.get("id") not in seen:
            seen.add(r.get("id"))
            uniq.append(r)
    return uniq


def when(s) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def green_times(runs: list[dict]) -> dict[str, dt.datetime]:
    """{head sha: when its last required workflow turned green}: the latest run of each workflow on the head, all of them done and not failed; the latest finish time"""
    by_head: dict[str, dict[str, dict]] = {}
    for r in runs:
        head, name, created = r.get("head_sha"), r.get("name"), when(r.get("created_at"))
        if not (isinstance(head, str) and isinstance(name, str) and created):
            continue
        cur = by_head.setdefault(head, {}).get(name)
        if cur is None or created > cur["_c"]:
            by_head[head][name] = dict(r, _c=created)
    out = {}
    for head, flows in by_head.items():
        if all(f.get("status") == "completed" and f.get("conclusion") in ("success", "skipped", "neutral") for f in flows.values()):
            ends = [when(f.get("updated_at")) for f in flows.values()]
            if ends and all(ends):
                out[head] = max(ends)
    return out


def run_flakes(runs: list[dict]) -> int:
    """(head, workflow) pairs where a run failed and a later run of the same workflow on the same head succeeded"""
    seq: dict[tuple, list[tuple[dt.datetime, str]]] = {}
    for r in runs:
        c = when(r.get("created_at"))
        if c and isinstance(r.get("head_sha"), str) and isinstance(r.get("name"), str) and r.get("status") == "completed":
            seq.setdefault((r["head_sha"], r["name"]), []).append((c, str(r.get("conclusion"))))
    n = 0
    for lst in seq.values():
        lst.sort()
        concl = [x[1] for x in lst]
        if any(c == "failure" and "success" in concl[i + 1:] for i, c in enumerate(concl)):
            n += 1
    return n


# ---------------------------------------------------------------- the numbers
def quantile(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    i = int(k)
    return xs[i] if i + 1 >= len(xs) else xs[i] + (xs[i + 1] - xs[i]) * (k - i)


def minutes(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    return (b - a).total_seconds() / 60 if a and b else None


def stage_values(pr: int, m: dict, gh: dict | None, greens: dict[str, dt.datetime]) -> dict[str, float | None]:
    created = gh["created"] if gh else None
    green = greens.get(gh["head"]) if gh and gh.get("head") else None
    green = green or m["checks_pass"]
    merged = m["merged"] or (gh["merged"] if gh else None)
    return {"open_to_green": minutes(created, green), "green_to_queued": minutes(green, m["enqueued"]), "queued_to_merged": minutes(m["enqueued"], merged),
            "merged_to_live": minutes(merged, m["done"]), "live_to_main": minutes(m["done"], m["main_pass"]), "open_to_live": minutes(created, m["done"])}


def summarize(live: dict[int, dict], prs: dict[int, dict], greens: dict[str, dt.datetime], notes: list[str]) -> dict:
    per: dict[str, list[tuple[float, int]]] = {k: [] for k, _ in STAGES}
    negative = 0
    for pr, m in sorted(live.items()):
        for k, v in stage_values(pr, m, prs.get(pr), greens).items():
            if v is None:
                continue
            if v < 0 or not math.isfinite(v):
                negative += 1
                continue
            per[k].append((v, pr))
    if negative:
        notes.append(f"{negative} stage value{'s' if negative != 1 else ''} below zero (a clock or a log out of order) left out")
    out = {}
    for k, _label in STAGES:
        xs = [v for v, _ in per[k]]
        if xs:
            worst = max(per[k])
            out[k] = {"n": len(xs), "median": round(statistics.median(xs), 1), "p90": round(quantile(xs, 0.9), 1), "worst": round(worst[0], 1), "worst_pr": worst[1]}
        else:
            out[k] = {"n": 0, "median": None, "p90": None, "worst": None, "worst_pr": None}
    return out


# ---------------------------------------------------------------- config and state
def config_path(arg: str | None) -> str:
    if arg:
        return arg
    base = os.environ.get("XDG_CONFIG_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "stackshot", "release-speed.toml")


def state_home() -> str:
    base = os.environ.get("XDG_STATE_HOME") or ""
    return base if os.path.isabs(base) else os.path.join(os.path.expanduser("~"), ".local", "state")


def default_state_dir() -> str:
    return os.path.join(state_home(), "stackshot", "release-speed")


def default_logs_dir() -> str:
    return os.path.join(state_home(), "stackshot", "releases")


def load_limits(path: str, repo: str, explicit: bool, dest: dict) -> dict:
    t: dict = dict(DEFAULTS)
    try:
        data = TR.read_config(path)
    except FileNotFoundError:
        if explicit:
            raise Fail(f"config file {path} does not exist")
        return t
    except OSError as e:
        raise Fail(f"cannot read config file {path}: {e.strerror or e}")
    except tomllib.TOMLDecodeError as e:
        raise Fail(f"config file {path} is not valid TOML: {e}")
    except UnicodeDecodeError:
        raise Fail(f"config file {path} is not UTF-8 text")
    except RecursionError:
        raise Fail(f"config file {path} is nested too deeply to read")
    except ValueError as e:
        raise Fail(f"config file {path} cannot be read: {e}")
    for k, v in data.items():
        if isinstance(v, dict):
            for k2 in v:
                if k2 not in DEFAULTS and k2 not in ITEM_KEYS:
                    print(f"warning: unknown key {k2} in {path} (table [{k}])", file=sys.stderr)
        elif k not in DEFAULTS and k not in ITEM_KEYS:
            print(f"warning: unknown key {k} in {path}", file=sys.stderr)
    for source in (data, data.get(repo) if isinstance(data.get(repo), dict) else {}):
        for k, v in source.items():
            if k in DEFAULTS:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= TR.THRESHOLD_MAX:
                    raise Fail(f"config file {path}: {k} must be a number from 0 to {TR.THRESHOLD_MAX}, got {str(v)[:40]!r}")
                t[k] = v if v != 0 else type(v)(0)
            elif k in ITEM_KEYS:
                if not isinstance(v, str) or not TR.ITEM_NAME.fullmatch(v):
                    raise Fail(f"config file {path}: {k} must be a name of letters, digits and . _ / - (at most 80 characters), got {str(v)[:40]!r}")
                dest[k] = v
    return t


def read_previous(path: str, repo: str) -> tuple[dict | None, str | None]:
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, RecursionError) as e:
        return None, f"the previous record {path} cannot be read ({e.__class__.__name__}); starting over"
    ok = isinstance(rec, dict) and type(rec.get("format")) is int and rec["format"] == FORMAT and rec.get("repo") == repo and isinstance(rec.get("stages"), dict) \
        and isinstance(rec.get("flakes"), dict) and isinstance(rec.get("generated"), str)
    if ok:
        g = when(rec["generated"])
        ok = g is not None and g.tzinfo is not None
    if not ok:
        return None, f"the previous record {path} is not of this tool's format or repository; starting over"
    return rec, None


def prev_number(prev: dict | None, *path):
    cur = prev
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) and 0 <= cur <= TR.THRESHOLD_MAX else None     # nan, inf and a huge integer fail the range


def kept_of(record: dict | None) -> dict | None:
    """the record's `open_to_live_kept` as {"median", "generated"}; None when it has none that can be used"""
    med = prev_number(record, "open_to_live_kept", "median")
    if med is None:
        return None
    t = when(record["open_to_live_kept"].get("generated"))
    return None if t is None or t.tzinfo is None else {"median": med, "generated": t.isoformat(timespec="seconds")}


def last_measured(prev: dict | None) -> dict | None:
    """the last measured open -> live median the previous record knows, as {"median", "generated": when it was measured}: its own measured stage, else what it kept"""
    med = prev_number(prev, "stages", "open_to_live", "median")
    if med is None:
        return kept_of(prev)
    return {"median": med, "generated": when(prev["generated"]).isoformat(timespec="seconds")}


# ---------------------------------------------------------------- the report
def num(x) -> str:
    return "n/a" if x is None else f"{x:,.1f}".rstrip("0").rstrip(".")


def evaluate(th: dict, rec: dict) -> list[dict]:
    out = []
    med = rec["stages"]["open_to_live"]["median"]
    if med is not None and med > th["max_open_to_live_median_minutes"]:
        out.append({"key": "max_open_to_live_median_minutes", "limit": th["max_open_to_live_median_minutes"], "value": med,
                    "line": f"FLAG: open_to_live_median: {num(med)} min > {num(th['max_open_to_live_median_minutes'])}"})
    n = rec["flakes"]["total"]
    if n > th["max_same_commit_flakes"]:
        out.append({"key": "max_same_commit_flakes", "limit": th["max_same_commit_flakes"], "value": n,
                    "line": f"FLAG: same_commit_flakes: {n} > {num(th['max_same_commit_flakes'])}"})
    return out


def render(rec: dict, prev: dict | None, days: float | None, notes: list[str]) -> str:
    p = rec["prs"]
    L = [f"release-speed report: {rec['repo']} (last {rec['window_days']:g} days)"]
    if not p["live"] and not p["not_live"]:
        L.append("releases in the window: none")
    else:
        L.append(f"live: {p['live']} pull requests; started and not live: {p['not_live']}; failed release attempts: {p['failed_attempts']}")
        L.append(f"{'stage (minutes)':26} {'n':>4} {'median':>8} {'p90':>8} {'worst':>8}")
        for k, label in STAGES:
            s = rec["stages"][k]
            L.append(f"{label:26} {s['n']:>4} {num(s['median']):>8} {num(s['p90']):>8} {num(s['worst']):>8}" + (f"  (PR #{s['worst_pr']})" if s["worst_pr"] else ""))
    f = rec["flakes"]
    L.append(f"same-commit flakes: {f['total']} (merge queue {f['merge_queue']}, PR runs {f['pr_runs'] if f['pr_runs'] is not None else 'n/a'}, main's run {f['main_run']})")
    if prev is not None and days is not None:
        a, b = prev_number(prev, "stages", "open_to_live", "median"), rec["stages"]["open_to_live"]["median"]
        fa = prev_number(prev, "flakes", "total")
        before, old = num(a), kept_of(prev)
        if a is None and old:
            before = f"{num(old['median'])} (from an earlier run, measured {old['generated']})"
        L.append(f"since the previous run ({days:.1f} days ago): open -> live median {before} -> {num(b)} min; same-commit flakes {num(fa)} -> {f['total']}")
    elif prev is None:
        L.append("since the previous run: none kept, this run is the baseline")
    L.extend(f"note: {n}" for n in notes)
    L.extend(t["line"] for t in rec["triggers"])
    return "\n".join(L)


def build(args, now: dt.datetime) -> tuple[str, dict, str]:
    slug = args.github or TR.github_slug(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo = re.sub(r"[^\w.-]", "_", args.repo or (slug.split("/")[-1] if slug else "")) or ""
    if not repo:
        raise Fail("no repository name: pass --repo or --github OWNER/REPO (the origin remote names none)")
    if args.days <= 0 or args.days > 366 or not math.isfinite(args.days):
        raise Fail("--days must be a number above 0 and at most 366")
    logdir = args.logs or default_logs_dir()
    args.item_dest = {}
    th = load_limits(config_path(args.config), repo, bool(args.config), args.item_dest)
    state_dir = args.state_dir or default_state_dir()
    if not args.dry_run:
        TR.check_state_dir(state_dir)
    state_file = os.path.join(state_dir, repo + ".json")
    prev, note = read_previous(state_file, repo)
    notes = [note] if note else []

    lo, hi = now - dt.timedelta(days=args.days), now
    logs = collect(logdir, slug, lo, hi, notes)
    prs: dict[int, dict] = {}
    greens: dict[str, dt.datetime] = {}
    pr_run_flakes = None
    args.no_data = None
    kept = None                    # the last measured open -> live median, only for a run that could not read the pull request list
    if not logs["live"] and not logs["not_live"]:
        args.no_data = f"no release in the last {args.days:g} days in {logdir}"
    elif not slug:
        args.no_data = "GitHub was not asked: --github names no repository and the origin remote names none"
    else:
        listed = False
        try:
            prs = fetch_prs(slug, lo)
            listed = True
            runs = fetch_runs(slug, lo - dt.timedelta(days=1), hi, [RUNS_PAGES_MAX])
            greens = green_times(runs)
            pr_run_flakes = run_flakes([r for r in runs if (when(r.get("created_at")) or lo) >= lo])
        except ValueError as e:
            args.no_data = f"no GitHub data: {e}"
            if listed:
                notes.append(f"{args.no_data}: the pull request list was read and the check runs were not, so the check times are the logs' alone and the PR-run flakes are not counted")
            else:
                notes.append(f"{args.no_data}: the stages that start at the PR's creation or need a check run are from the logs alone, and the PR-run flakes are not counted")
                kept = last_measured(prev)
    stages = summarize(logs["live"], prs, greens, notes)
    if kept:
        notes.append(f"open -> live is not measured in this run (the pull request list could not be read): the last measured median, {num(kept['median'])} min, measured "
                     f"{kept['generated']}, is kept for a later comparison only and raises no flag")
    flakes = {"merge_queue": logs["queue_flakes"], "pr_runs": pr_run_flakes, "main_run": logs["main_flakes"],
              "total": logs["queue_flakes"] + (pr_run_flakes or 0) + logs["main_flakes"]}
    rec = {"format": FORMAT, "repo": repo, "github": slug, "generated": now.isoformat(timespec="seconds"), "window_days": args.days,
           "prs": {"live": len(logs["live"]), "not_live": len(logs["not_live"]), "failed_attempts": logs["failed_attempts"]},
           "stages": stages, "flakes": flakes, "thresholds": th}
    if kept:
        rec["open_to_live_kept"] = kept       # never in `stages`: a flag and its item come only from what this run measured
    rec["triggers"] = evaluate(th, rec)
    owed = owed_flags(prev)
    args.item_owed = owed
    args.item_triggers = merge_flags(owed, rec["triggers"])
    if owed:
        notes.append("an item is still owed for an earlier run's flag (" + ", ".join(t["key"] for t in owed) + "); it is asked for again below")
    days = max(0.0, (now - when(prev["generated"])).total_seconds() / 86400) if prev else None
    text = render(rec, prev, days, notes)
    rec["notes"] = notes
    return text, rec, state_file


def owed_flags(prev: dict | None) -> list[dict]:
    out = []
    pending = (prev or {}).get("open_pending")
    if not isinstance(pending, list):
        return out
    for t in pending:
        if isinstance(t, dict) and t.get("key") in DEFAULTS and isinstance(t.get("line"), str) and t["line"].startswith("FLAG: "):
            out.append({"key": t["key"], "limit": t.get("limit"), "value": t.get("value"), "line": t["line"]})
    return out


def merge_flags(owed: list[dict], current: list[dict]) -> list[dict]:
    by_key = {t["key"]: t for t in owed}
    by_key.update({t["key"]: t for t in current})
    return [by_key[k] for k in DEFAULTS if k in by_key]


# ---------------------------------------------------------------- the item a flag opens
def item_request(repo: str, flags: list[dict], rec: dict, state_file: str, dest: dict) -> dict:
    shown = state_file
    home = os.path.expanduser("~")
    if home not in ("", "/") and shown.startswith(home + os.sep):
        shown = "~" + shown[len(home):]
    tail = "/" + "/".join(SHORT[t["key"]] for t in flags)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", repo)
    if not re.match(r"[A-Za-z0-9]", name):
        name = "r" + name
    marker = f"{OPEN_KIND}:{name[: max(1, 80 - len(tail))]}{tail}"
    lines = [TR.fit(f"Repository {repo}: the weekly release-speed report passed {len(flags)} threshold{'s' if len(flags) != 1 else ''}")]
    lines += [TR.fit(t["line"][len("FLAG: "):]) for t in flags]
    timed = [(s["median"], k) for k, s in rec["stages"].items() if k != "open_to_live" and s["median"] is not None]
    if timed:
        top = max(timed)
        lines.append(TR.fit(f"Slowest stage by median: {dict(STAGES)[top[1]]}, {num(top[0])} min"))
    label = "Full numbers: the report's state file "
    lines.append(label + TR.fit(shown, keep_end=True, width=TR.OPEN_LINE_MAX - len(label)))
    mover = dest.get("item_mover", "")
    return {"marker": marker, "project": dest.get("item_project", ""), "mover": mover, "sender": OPEN_SENDER,
            "subject": TR.fit(f"Speed up the {repo[:30]} release path"),
            "step": f"{mover}: find what makes the slowest stage of the release path slow in {repo[:30]}, fix it or report why not",
            "lines": lines}


def render_item(res: dict) -> str:
    if res["sent"]:
        return f"item: {res['item']} (marker {res['marker']}; an item still open under that marker is answered, not filed again)"
    L = ["item: not sent (--no-open or --dry-run); it would be:", f"  marker:  {res['marker']}", f"  project: {res['project'] or '(item_project is not set)'}",
         f"  mover:   {res['mover'] or '(item_mover is not set)'}", f"  subject: {res['subject']}", f"  step:    {res['step']}"]
    L.extend(f"  line:    {x}" for x in res["lines"])
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="release_speed_report.py", description="The weekly release-speed report: how long each stage of a pull request's way to live takes.")
    ap.add_argument("--github", help="OWNER/REPO the pull requests and runs are read from, and the logs are of (default: the origin remote of this checkout)")
    ap.add_argument("--repo", help="the name the state file and the [table] of the config use (default: the repository part of --github)")
    ap.add_argument("--logs", help="the release logs folder (default: ${XDG_STATE_HOME:-~/.local/state}/stackshot/releases)")
    ap.add_argument("--days", type=float, default=7, help="the length of the rolling window (default: 7)")
    ap.add_argument("--config", help="the limits file (default: ${XDG_CONFIG_HOME:-~/.config}/stackshot/release-speed.toml)")
    ap.add_argument("--state-dir", help="the folder of the state files (default: ${XDG_STATE_HOME:-~/.local/state}/stackshot/release-speed)")
    ap.add_argument("--dry-run", action="store_true", help="print the report and write no state")
    ap.add_argument("--json", action="store_true", help="print the record as JSON instead of the text")
    ap.add_argument("--no-open", action="store_true", help="on a flag, print the item that would be opened and call nothing (--dry-run does the same)")
    ap.add_argument("--client", help="the client program that opens the item (default: stackshot/fleet/client.py of this checkout, run with this Python)")
    ap.add_argument("--now", help="the clock as an ISO time with an offset, for tests")
    args = ap.parse_args(argv)
    try:
        try:
            now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        except ValueError:
            raise Fail(f"--now {args.now!r} is not an ISO time")
        if now.tzinfo is None:
            raise Fail("--now needs an offset, like 2026-01-05T09:00:00+00:00")
        text, rec, state_file = build(args, now.astimezone(dt.timezone.utc))
        res = failure = None
        if args.item_triggers:
            try:
                res = TR.file_item(item_request(rec["repo"], args.item_triggers, rec, state_file, args.item_dest), args.client, send=not (args.no_open or args.dry_run))
            except Fail as e:
                failure = e
        if failure or (args.item_triggers and not (res and res["sent"])):
            rec["open_pending"] = args.item_triggers
        empty = rec["prs"]["live"] == 0 and rec["prs"]["not_live"] == 0
        prev, _ = read_previous(state_file, rec["repo"])
        try:
            if not args.dry_run and not empty:
                TR.write_state(state_file, rec)
            elif not args.dry_run and prev is not None and "open_pending" in prev and res and res["sent"]:
                # a window with no release leaves the previous record as it was, but a debt that was paid is cleared in it too
                TR.write_state(state_file, {k: v for k, v in prev.items() if k != "open_pending"})
        except OSError as e:
            raise Fail(f"cannot write {state_file}: {e.strerror or e}", 1)
        if args.json:
            print(json.dumps(dict(rec, item_open=res) if res else rec, sort_keys=True))
        else:
            print(text)
            if res:
                print(render_item(res))
        if args.no_data:
            if failure:
                print(f"release_speed_report: {args.no_data}", file=sys.stderr)
            else:
                raise Fail(args.no_data, 4)
        if failure:
            raise failure
        return 0
    except Fail as e:
        print(f"release_speed_report: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
