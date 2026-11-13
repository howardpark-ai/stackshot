#!/usr/bin/env python3
"""tools/test_trim_report.py - the weekly size report of a repository's test suites. Read-only, standard library only.

Run it from a checkout (or pass --root). It prints a short plain-text report, keeps the run as one JSON record in a state file, and
compares it with the previous run's record:

    python3 tools/test_trim_report.py [--root DIR] [--repo NAME] [--map FILE | --fetch [--github OWNER/REPO]]
                                      [--config FILE] [--state-dir DIR] [--dry-run] [--json] [--no-open] [--client PROGRAM]

What it measures, per run:
  * suites       the files tests/<name>_scenario.py (what `tests/suitemap.py list` lists).
  * test lines   the lines of those files that start (after indentation) with `check(`, `ck(`, `assert ` or `self.assert...(`: the
                 suites' own check helper and plain asserts, one count per statement line. A comment, a `def check(` and a call that
                 starts with anything else are not counted. It is a size measure, not a coverage measure: stable between runs, cheap.
  * serial minutes, slowest suites   from the suite map's plain seconds per suite (`suites.<name>.seconds`, the file tests/suitemap.py
                 writes to .suitemap/map.json on main and CI keeps as the `suitemap` artifact): no second store of durations. A
                 suite the map has no time for is counted as untimed, and a time that is negative, not a finite number or above a year
                 (31,622,400 seconds) is ignored with a note naming the suite. Where the map comes from, first that applies:
                   --fetch         the `suitemap` artifact of the newest successful push run of tests.yml on main, downloaded with
                                   `gh` into a temporary folder that is removed again (two GitHub calls; --github names the
                                   repository, default: the origin remote). CI keeps that artifact for 7 days, so a week with no
                                   push to main leaves nothing to fetch. It wins over --map;
                   --map FILE      this file;
                   otherwise       <root>/.suitemap/map.json.
                 With no readable map the minutes are reported as n/a, the two minute thresholds are not checked, and the report says why.
  * since the previous run   suites added and deleted by name, test lines added and deleted (per suite, the rise or fall of its
                 count; a new suite adds all its lines, a deleted one deletes all).

Thresholds. Four keys, read from a small TOML file, `--config FILE` or `${XDG_CONFIG_HOME:-~/.config}/stackshot/test-trim.toml`; keys at
the top of the file apply to every repository, and a table named after the repository (`[stackshot]`) overrides them for it:

    max_suites            number of suites
    max_serial_minutes    the suites' times added up
    max_suite_minutes     the slowest single suite
    max_test_line_growth  test lines gained since the previous run, scaled down to a week when the gap is longer than a week

A key the file names that is none of these four (a mistyped `max_suite`) is not used: a `warning: unknown key <name> in <file>` line
goes to stderr for each, and the exit status is unchanged. A value that is not a number from 0 to 10**12 (a boolean, a string, nan, inf, a
negative or a huge one), a file that is not UTF-8 text, a pipe in place of a file (also one with a writer: `--config /dev/stdin` is refused; a config is a file) and one nested too deep are config problems, exit 2.

The defaults are placeholders that never trigger: set the real values from the measured medians. When a value is above its limit the
report ends with `TRIGGER: <which>` lines (one per threshold, in the order above) and the same lines are kept in the state file. This
tool cleans nothing up; a trigger is the cue for a cleanup pass (a deep scan for duplicate or obsolete suites), which is not part of this
report, and the report asks for it by opening ONE builder item for the repository, through the client's `post item-open` route (the mover and
project are the config keys `item_project` and `item_mover`, strings at the top of the config file or in the repository's table; the description names the repository, each threshold passed with its value and limit, and the
state file). No trigger, no call. The item's marker is `test_trim:<repo>/<short name of each trigger, in the order above, joined by />`
(`test_trim:stackshot/suites/growth`): the same triggers give the same marker, so a weekly run that finds the item still open files nothing new
(the route answers the open item), and a trigger that was not in the set before gives another marker, so another item. `--no-open` (and
`--dry-run`, which writes nothing) prints what would be sent and calls nothing. The call is made once, never retried: a refusal or a client
that cannot be run prints its text on stderr and the status is 3, after the report was printed. The state file is written after the call; when
the item was not opened it records the triggers as owed (`open_pending`) and the next run asks for them again together with its own, so a growth
trigger does not vanish because its baseline moved on. A debt is cleared by the call that opens (or answers) the item; a `--no-open` run sends nothing, so it records its own triggers as owed together with any earlier debt.
`--client PROGRAM` names the client program (default: stackshot/fleet/client.py of the checkout this tool is in, run with this Python).

State file: `${XDG_STATE_HOME:-~/.local/state}/stackshot/test-trim/<repo>.json` (--state-dir replaces the folder), written
atomically (a temporary file in the same folder, then a rename). A previous record that cannot be used (not JSON, another format or
repository, a missing or wrong-typed field, a time without a UTC offset, a count that is not a non-negative whole number) is started
over from with a one-line note, and this run's record replaces it. --dry-run prints the report and writes nothing; --json prints the
record instead of the text. `--now ISO` sets the clock, for tests.

Exit status: 0 the report was made (triggers included, and their item opened or answered, or not sent for --no-open), 1 the state folder or
file cannot be written, 2 a usage, config or checkout problem, 3 the report was made but the item was not opened. SIGTERM ends the run cleanly (the download folder is removed first; status 143)."""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import glob
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import tomllib

FORMAT = 1
SUITE_GLOB = "tests/*_scenario.py"
SUITE_NAME = re.compile(r"(\w+)_scenario\.py$")
TEST_LINE = re.compile(r"^\s*(?:assert\b|(?:check|ck)\(|self\.assert\w*\()")
SLOWEST = 8
COUNT_MAX = 10 ** 12      # a count above this is not a test-line count; it would also overflow the float arithmetic
LIST_MAX = 20            # names listed per added/deleted line of the report
SECONDS_MAX = 366 * 86400    # a suite time above a year is no suite time; it would also run the minute sums towards infinity
THRESHOLD_MAX = COUNT_MAX    # a limit above this is no limit anyone set; it keeps the comparisons and the state file's numbers plain
# Placeholders that never trigger. They are replaced by the measured medians in the config file, not by editing this table.
DEFAULTS = {"max_suites": 1_000_000, "max_serial_minutes": 1_000_000.0, "max_suite_minutes": 1_000_000.0, "max_test_line_growth": 1_000_000}
FOLLOW_UP = "Follow-up: a deep scan for duplicate or obsolete suites (not part of this report)."
ITEM_KEYS = ("item_project", "item_mover")   # where a trigger's item is filed and who moves it: set in the config file, never in this public code
ITEM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,79}")
OPEN_KIND = "test_trim"
OPEN_SENDER = "test-trim-report"
OPEN_LINE_MAX = 118                          # the route takes a bullet of 120 characters, "- " included
OPEN_TIMEOUT = 120                           # seconds the one call may take
SHORT = {"max_suites": "suites", "max_serial_minutes": "serial", "max_suite_minutes": "slowest", "max_test_line_growth": "growth"}


class Fail(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- measuring
def count_test_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if TEST_LINE.match(line))


def measure_suites(root: str) -> dict[str, int]:
    """{suite name: test lines} for every tests/<name>_scenario.py under root"""
    out: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(glob.escape(root), SUITE_GLOB))):
        m = SUITE_NAME.search(os.path.basename(path))
        if not m:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                out[m.group(1)] = count_test_lines(f.read())
        except OSError as e:
            raise Fail(f"cannot read {path}: {e.strerror or e}")
    return out


def read_map(path: str) -> tuple[dict[str, float], str, list[str]]:
    """({suite: plain seconds}, commit, suites whose time is unusable) from a suite map file; ValueError says what is wrong with it"""
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except OSError as e:
        raise ValueError(f"cannot read {path}: {e.strerror or e}")
    except RecursionError:
        raise ValueError(f"{path} is nested too deeply to read")
    except ValueError as e:
        raise ValueError(f"{path} is not JSON: {e}")
    if not isinstance(m, dict) or m.get("format") != 1 or not isinstance(m.get("suites"), dict):
        raise ValueError(f"{path} is not a suite map of format 1")
    secs: dict[str, float] = {}
    bad: list[str] = []
    for name, e in m["suites"].items():
        v = e.get("seconds") if isinstance(e, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= SECONDS_MAX:     # false for nan, inf and a negative; no float() of a huge int
            secs[name] = float(v)
        elif isinstance(e, dict) and v is not None:
            bad.append(str(name))
    return secs, str(m.get("commit") or ""), sorted(bad)


def github_slug(root: str) -> str | None:
    try:
        url = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def fetch_map(slug: str, folder: str) -> str:
    """download main's newest suite map artifact into folder; returns the file's path, ValueError says why not"""
    def gh(*args: str) -> str:
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise ValueError("the gh command is not installed")
        except subprocess.SubprocessError as e:
            raise ValueError(f"gh did not finish: {e}")
        if r.returncode != 0:
            raise ValueError(f"gh {args[0]} {args[1]} failed: {(r.stderr or r.stdout).strip()[:200]}")
        return r.stdout
    out = gh("run", "list", "--repo", slug, "--workflow", "tests.yml", "--branch", "main", "--event", "push",
             "--status", "success", "--limit", "1", "--json", "databaseId")
    try:
        runs = json.loads(out)
        run_id = str(runs[0]["databaseId"])
    except (ValueError, IndexError, KeyError, TypeError):
        raise ValueError(f"no successful push run of tests.yml on main for {slug}")
    gh("run", "download", run_id, "--repo", slug, "--name", "suitemap", "--dir", folder)
    for dirpath, _dirs, files in os.walk(folder):
        if "map.json" in files:
            return os.path.join(dirpath, "map.json")
    raise ValueError("the suitemap artifact holds no map.json")


# ---------------------------------------------------------------- config
def config_path(arg: str | None) -> str:
    if arg:
        return arg
    base = os.environ.get("XDG_CONFIG_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "stackshot", "test-trim.toml")


def read_config(path: str) -> dict:
    """the TOML file's data. A config is a file: a pipe is refused (also one with a writer), and so is a terminal, a block device or a socket.
    The path is opened non-blocking so that a pipe with no writer cannot hold the open for ever, and the descriptor is looked at before anything
    is read and closed on every way out."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    f = None
    try:
        mode = os.fstat(fd).st_mode
        if stat.S_ISDIR(mode):
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
        if stat.S_ISFIFO(mode):
            raise Fail(f"config file {path} is a pipe, not a file")
        if not (stat.S_ISREG(mode) or (stat.S_ISCHR(mode) and not os.isatty(fd))):          # a regular file, or a device like /dev/null
            raise Fail(f"config file {path} is not a regular file")
        f = os.fdopen(fd, "rb")                                                           # f owns the descriptor from here
        return tomllib.load(f)
    finally:
        if f is not None:
            f.close()
        else:
            os.close(fd)


def load_thresholds(path: str, repo: str, explicit: bool, dest: dict | None = None) -> dict[str, float]:
    """DEFAULTS, then the file's top-level keys, then its [<repo>] table. A missing default file is no error; a bad value is. The two item keys
    (ITEM_KEYS: strings) are not thresholds: they are put into `dest` when it is given."""
    t: dict = dict(DEFAULTS)
    try:
        data = read_config(path)
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
    except ValueError as e:                     # tomllib's own limit on a number with thousands of digits
        raise Fail(f"config file {path} cannot be read: {e}")
    for k, v in data.items():                   # a table is some repository's; any other key must be one of the four
        if not isinstance(v, dict) and k not in DEFAULTS and k not in ITEM_KEYS:
            print(f"warning: unknown key {k} in {path}", file=sys.stderr)
        if isinstance(v, dict):
            for k2 in v:
                if k2 not in DEFAULTS and k2 not in ITEM_KEYS:
                    print(f"warning: unknown key {k2} in {path} (table [{k}])", file=sys.stderr)
    for source in (data, data.get(repo) if isinstance(data.get(repo), dict) else {}):
        for k, v in source.items():
            if k in DEFAULTS:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= THRESHOLD_MAX:     # false for nan, inf, a negative, a huge int
                    raise Fail(f"config file {path}: {k} must be a number from 0 to {THRESHOLD_MAX}, got {str(v)[:40]!r}")
                t[k] = v if v != 0 else type(v)(0)       # -0.0 is zero: it would otherwise print as a limit of -0
            elif k in ITEM_KEYS:
                if not isinstance(v, str) or not ITEM_NAME.fullmatch(v):
                    raise Fail(f"config file {path}: {k} must be a name of letters, digits and . _ / - (at most 80 characters), got {str(v)[:40]!r}")
                if dest is not None:
                    dest[k] = v
    return t


# ---------------------------------------------------------------- state
def default_state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "stackshot", "test-trim")


def check_state_dir(folder: str) -> None:
    """make the folder and prove a file can be made in it, so a run does not end with nothing kept"""
    try:
        os.makedirs(folder, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=folder, prefix=".probe-")
        os.close(fd)
        os.unlink(probe)
    except OSError as e:
        raise Fail(f"cannot write the state folder {folder}: {e.strerror or e}", 1)


def valid_count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= COUNT_MAX


def record_problem(rec, repo: str) -> str | None:
    """why a parsed previous record cannot be used (one line), or None when every field this tool reads is sound"""
    if not (isinstance(rec, dict) and type(rec.get("format")) is int and rec["format"] == FORMAT):
        return "is not of this tool's format"
    if rec.get("repo") != repo:
        return f"is for repository {str(rec.get('repo'))[:60]!r}, not {repo!r}"
    if not isinstance(rec.get("suites"), dict):
        return "is damaged (suites)"
    if not all(valid_count(v) for v in rec["suites"].values()):
        return "is damaged (a suite's test lines)"
    if not valid_count(rec.get("test_lines")):
        return "is damaged (test_lines)"
    g = rec.get("generated")
    if not isinstance(g, str):
        return "is damaged (generated)"
    try:
        when = dt.datetime.fromisoformat(g)
    except ValueError:
        return "is damaged (generated)"
    if when.tzinfo is None or when.utcoffset() is None:
        return "is damaged (generated has no UTC offset)"
    return None


def read_previous(path: str, repo: str) -> tuple[dict | None, str | None]:
    """(previous record, note): no file is no note; a file that cannot be used is ignored with a one-line note"""
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, RecursionError) as e:
        return None, f"the previous record {path} cannot be read ({e.__class__.__name__}); starting over"
    try:
        why = record_problem(rec, repo)
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
        why = "is damaged"
    if why:
        return None, f"the previous record {path} {why}; starting over"
    return rec, None


def write_state(path: str, rec: dict) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, sort_keys=True, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- the report
def compare(prev: dict | None, cur: dict[str, int]) -> dict:
    if prev is None:
        return {"added_suites": [], "deleted_suites": [], "tests_added": 0, "tests_deleted": 0}
    old = prev["suites"]
    added = sorted(set(cur) - set(old))
    deleted = sorted(set(old) - set(cur))
    up = sum(cur[n] for n in added) + sum(max(0, cur[n] - old[n]) for n in set(cur) & set(old))
    down = sum(old[n] for n in deleted) + sum(max(0, old[n] - cur[n]) for n in set(cur) & set(old))
    return {"added_suites": added, "deleted_suites": deleted, "tests_added": up, "tests_deleted": down}


def num(x: float) -> str:
    return f"{x:,.1f}".rstrip("0").rstrip(".")


def evaluate(th: dict, rec: dict, growth_per_week: float | None) -> list[dict]:
    out = []

    def hit(key: str, value, text: str) -> None:
        out.append({"key": key, "limit": th[key], "value": value, "line": f"TRIGGER: {key}: {text} > {num(th[key])}"})
    if rec["suite_count"] > th["max_suites"]:
        hit("max_suites", rec["suite_count"], f"{rec['suite_count']} suites")
    if rec["serial_minutes"] is not None and rec["serial_minutes"] > th["max_serial_minutes"]:
        hit("max_serial_minutes", rec["serial_minutes"], f"{rec['serial_minutes']:.1f} serial minutes")
    if rec["slowest"]:
        over = [s for s in rec["timed"] if s[1] > th["max_suite_minutes"]]
        if over:
            top = rec["slowest"][0]
            hit("max_suite_minutes", top[1], f"{top[0]} takes {top[1]:.1f} min ({len(over)} over)")
    if growth_per_week is not None and growth_per_week > th["max_test_line_growth"]:
        hit("max_test_line_growth", round(growth_per_week, 1), f"+{growth_per_week:,.0f} test lines per week")
    return out


def names_line(label: str, names: list[str]) -> str:
    shown = ", ".join(names[:LIST_MAX]) + (f", and {len(names) - LIST_MAX} more" if len(names) > LIST_MAX else "")
    return f"  {label}: {shown}"


def render(rec: dict, prev: dict | None, days: float | None, notes: list[str]) -> str:
    L = [f"test-trim report: {rec['repo']}", f"suites: {rec['suite_count']}",
         f"test lines: {rec['test_lines']:,} (check and assert lines)"]
    if rec["serial_minutes"] is None:
        L.append("serial minutes: n/a")
        L.append("slowest suites: n/a")
    else:
        extra = f", {rec['untimed']} untimed" if rec["untimed"] else ""
        L.append(f"serial minutes: {rec['serial_minutes']:.1f} ({len(rec['timed'])} of {rec['suite_count']} suites timed{extra})")
        if rec["slowest"]:
            L.append(f"slowest {len(rec['slowest'])}:")
            L.extend(f"  {i}. {n}  {m:.1f} min" for i, (n, m) in enumerate(rec["slowest"], 1))
    if prev is None:
        L.append("since the previous run: none kept, this run is the baseline")
    else:
        net = rec["test_lines"] - prev["test_lines"]
        L.append(f"since the previous run ({days:.1f} days ago): {len(rec['added_suites'])} suites added, "
                 f"{len(rec['deleted_suites'])} deleted; {rec['tests_added']:,} test lines added, {rec['tests_deleted']:,} deleted (net {net:+,})")
        if rec["added_suites"]:
            L.append(names_line("added", rec["added_suites"]))
        if rec["deleted_suites"]:
            L.append(names_line("deleted", rec["deleted_suites"]))
    L.extend(f"note: {n}" for n in notes)
    if rec["triggers"]:
        L.extend(t["line"] for t in rec["triggers"])
        L.append(FOLLOW_UP)
    return "\n".join(L)


def make_work_folder(work: list[str]) -> str:
    """a temporary folder for the download, listed in work at once: SIGTERM is held back between the two, so it cannot be missed"""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        try:
            folder = tempfile.mkdtemp(prefix="test-trim-")
        except OSError as e:
            raise ValueError(f"cannot make a temporary folder for the download: {e.strerror or e}")
        work.append(folder)
        return folder
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def build(args, now: dt.datetime, work: list[str]) -> tuple[str, dict, str]:
    root = os.path.abspath(args.root)
    suites = measure_suites(root)
    if not suites:
        raise Fail(f"no {SUITE_GLOB} under {root}: run it from a checkout, or pass --root")
    repo = re.sub(r"[^\w.-]", "_", args.repo or os.path.basename(root)) or "repo"
    args.item_dest = {}
    th = load_thresholds(config_path(args.config), repo, bool(args.config), args.item_dest)
    state_dir = args.state_dir or default_state_dir()
    if not args.dry_run:
        check_state_dir(state_dir)
    state_file = os.path.join(state_dir, repo + ".json")
    prev, note = read_previous(state_file, repo)
    notes = [note] if note else []

    secs: dict[str, float] | None = None
    map_commit = ""
    try:
        if args.fetch:
            slug = args.github or github_slug(root)
            if not slug:
                raise ValueError("--fetch needs --github OWNER/REPO, and the origin remote names none")
            map_path = fetch_map(slug, make_work_folder(work))
        else:
            map_path = args.map or os.path.join(root, ".suitemap", "map.json")
        secs, map_commit, bad = read_map(map_path)
        bad = [n for n in bad if n in suites]
        if bad:
            notes.append(f"suite times ignored (negative, not a finite number or above a year), counted as untimed: {', '.join(bad[:LIST_MAX])}"
                         + (f", and {len(bad) - LIST_MAX} more" if len(bad) > LIST_MAX else ""))
    except ValueError as e:
        notes.append(f"no suite times: {e}")

    timed = sorted(((n, round(secs[n] / 60, 2)) for n in suites if secs is not None and n in secs), key=lambda x: (-x[1], x[0]))
    test_lines = sum(suites.values())
    rec = {"format": FORMAT, "repo": repo, "generated": now.isoformat(timespec="seconds"), "suites": suites,
           "suite_count": len(suites), "test_lines": test_lines, "commit": head_commit(root), "map_commit": map_commit or None,
           "serial_minutes": round(sum(m for _, m in timed), 2) if secs is not None else None,
           "untimed": len(suites) - len(timed) if secs is not None else None,
           "timed": timed, "slowest": timed[:SLOWEST] if secs is not None else [], "thresholds": th}
    rec.update(compare(prev, suites))
    days = growth = None
    if prev is not None:
        days = max(0.0, (now - dt.datetime.fromisoformat(prev["generated"])).total_seconds() / 86400)
        net = test_lines - sum(prev["suites"].values())
        growth = net if days <= 7 else net * 7 / days
        rec["growth_per_week"] = round(growth, 1)
    rec["triggers"] = evaluate(th, rec, growth)
    owed = owed_triggers(prev)
    args.item_owed = owed
    args.item_triggers = merge_triggers(owed, rec["triggers"])        # what the item is asked for: the triggers of this run and any an earlier run could not get an item for
    if owed:
        notes.append("an item is still owed for an earlier run's threshold (" + ", ".join(t["key"] for t in owed) + "); it is asked for again below")
    text = render(rec, prev, days, notes)
    rec["notes"] = notes
    return text, rec, state_file


def owed_triggers(prev: dict | None) -> list[dict]:
    """the triggers the previous run could not get an item for (its `open_pending`), read leniently: an entry that is not a threshold of this tool (not a map, a key that is not the name of one) is dropped; `limit` and `value` are only carried through, never computed with"""
    out = []
    pending = (prev or {}).get("open_pending")
    if not isinstance(pending, list):        # absent, or damaged into a number, a string or a map: no debt, and the run goes on
        return out
    for t in pending:
        if isinstance(t, dict) and isinstance(t.get("key"), str) and t["key"] in DEFAULTS and isinstance(t.get("line"), str) and t["line"].startswith("TRIGGER: "):
            out.append({"key": t["key"], "limit": t.get("limit"), "value": t.get("value"), "line": t["line"]})
    return out


def merge_triggers(owed: list[dict], current: list[dict]) -> list[dict]:
    """owed and current triggers, one per threshold (the current run's line wins), in the order of the thresholds"""
    by_key = {t["key"]: t for t in owed}
    by_key.update({t["key"]: t for t in current})
    return [by_key[k] for k in DEFAULTS if k in by_key]


def head_commit(root: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out if re.fullmatch(r"[0-9a-f]{40}", out) else None


# ---------------------------------------------------------------- the item a trigger opens
def fit(text: str, keep_end: bool = False, width: int = OPEN_LINE_MAX) -> str:
    """text as one line of at most `width` characters: cut with `...`, at the end (or at the start for a path, whose tail says most)"""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return "..." + text[-(width - 3):] if keep_end else text[:width - 3] + "..."


def item_marker(repo: str, triggers: list[dict]) -> str:
    """`test_trim:<repo>/<short trigger names>`: stable for a repository and a set of triggers, and valid for the route (at most 80
    characters after the colon, a letter or digit first, then only letters, digits and `_ . - /`)"""
    tail = "/" + "/".join(SHORT.get(t["key"], re.sub(r"[^A-Za-z0-9_.-]", "_", str(t["key"]))) for t in triggers)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", repo)
    if not re.match(r"[A-Za-z0-9]", name):         # the route wants a letter or a digit first: a name that starts with a dot, an underscore, a hyphen or a non-ASCII letter gets a safe prefix
        name = "r" + name
    name = name[: max(1, 80 - len(tail))]
    return f"{OPEN_KIND}:{name}{tail}"


def item_request(repo: str, triggers: list[dict], state_file: str, dest: dict) -> dict:
    """what the one call sends: marker, subject, step and at most 6 description lines of at most OPEN_LINE_MAX characters"""
    shown = state_file
    home = os.path.expanduser("~")
    if home not in ("", "/") and shown.startswith(home + os.sep):
        shown = "~" + shown[len(home):]
    lines = [fit(f"Repository {repo}: the weekly test-trim report passed {len(triggers)} threshold{'s' if len(triggers) != 1 else ''}")]
    lines += [fit(t["line"][len("TRIGGER: "):]) for t in triggers]
    label = "Full numbers: the report's state file "
    lines.append(label + fit(shown, keep_end=True, width=OPEN_LINE_MAX - len(label)))
    return {"marker": item_marker(repo, triggers), "project": dest.get("item_project", ""), "mover": dest.get("item_mover", ""), "sender": OPEN_SENDER,
            "subject": fit(f"Deep-scan the {repo[:30]} test suites"),
            "step": f"{dest.get('item_mover', '')}: run the deep scan for duplicate or obsolete suites in {repo[:30]}, trim what it finds, report",
            "lines": lines}


def client_command(client: str | None) -> list[str]:
    if client:
        return [client]
    return [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stackshot", "fleet", "client.py")]


def request_argv(req: dict) -> list[str]:
    argv = ["post", "item-open", req["marker"], "--project", req["project"], "--subject", req["subject"], "--mover", req["mover"],
            "--step", req["step"], "--sender", req["sender"]]
    for line in req["lines"]:
        argv += ["--line", line]
    return argv


def file_item(req: dict, client: str | None, send: bool) -> dict:
    """the one call: {"sent": False, ...} when nothing is sent, {"sent": True, "item": id} when the client printed an id; Fail(.., 3) when it did not.
    No retry: a failed call is reported, and the next weekly run asks again."""
    out = {"sent": False, "marker": req["marker"], "project": req["project"], "mover": req["mover"], "subject": req["subject"], "step": req["step"], "lines": req["lines"]}
    if not send:
        return out
    if not req["project"] or not req["mover"]:
        raise Fail(f"the item for {req['marker']} was not opened: the config file sets no item_project and item_mover (where the item is filed and who moves it)", 3)
    try:
        r = subprocess.run(client_command(client) + request_argv(req), capture_output=True, text=True, timeout=OPEN_TIMEOUT)
    except OSError as e:
        raise Fail(f"the item for {req['marker']} was not opened: the client cannot be run: {e.strerror or e}", 3)
    except subprocess.TimeoutExpired:
        raise Fail(f"the item for {req['marker']} was not opened: the client did not answer within {OPEN_TIMEOUT} seconds", 3)
    item = r.stdout.strip()
    if r.returncode != 0 or not item or "\n" in item:
        why = " ".join((r.stderr or r.stdout).split())[:600] or f"the client exited {r.returncode} and printed nothing"
        raise Fail(f"the item for {req['marker']} was not opened: {why}", 3)
    out["sent"] = True
    out["item"] = item
    return out


def render_item(res: dict) -> str:
    if res["sent"]:
        return f"item: {res['item']} (marker {res['marker']}; an item still open under that marker is answered, not filed again)"
    L = ["item: not sent (--no-open or --dry-run); it would be:", f"  marker:  {res['marker']}", f"  project: {res['project'] or '(item_project is not set)'}", f"  mover:   {res['mover'] or '(item_mover is not set)'}",
         f"  subject: {res['subject']}", f"  step:    {res['step']}"]
    L.extend(f"  line:    {x}" for x in res["lines"])
    return "\n".join(L)


def on_sigterm(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="test_trim_report.py", description="The weekly size report of a repository's test suites (read-only).")
    ap.add_argument("--root", default=".", help="the checkout to measure (default: the current folder)")
    ap.add_argument("--repo", help="the name the state file and the [table] of the config use (default: the folder's name)")
    ap.add_argument("--map", help="the suite map file with the suites' times (default: <root>/.suitemap/map.json)")
    ap.add_argument("--fetch", action="store_true", help="download main's newest suite map artifact with gh instead of reading a file")
    ap.add_argument("--github", help="OWNER/REPO for --fetch (default: the origin remote)")
    ap.add_argument("--config", help="the thresholds file (default: ${XDG_CONFIG_HOME:-~/.config}/stackshot/test-trim.toml)")
    ap.add_argument("--state-dir", help="the folder of the state files (default: ${XDG_STATE_HOME:-~/.local/state}/stackshot/test-trim)")
    ap.add_argument("--dry-run", action="store_true", help="print the report and write no state")
    ap.add_argument("--json", action="store_true", help="print the record as JSON instead of the text")
    ap.add_argument("--no-open", action="store_true", help="on a trigger, print the item that would be opened and call nothing (--dry-run does the same)")
    ap.add_argument("--client", help="the client program that opens the item (default: stackshot/fleet/client.py of this checkout, run with this Python)")
    ap.add_argument("--now", help="the clock as an ISO time with an offset, for tests")
    args = ap.parse_args(argv)
    work: list[str] = []
    old_term = None
    try:
        old_term = signal.signal(signal.SIGTERM, on_sigterm)    # so the cleanup below also runs when the run is stopped
    except ValueError:                                           # not the main thread: the caller owns its signals
        pass
    try:
        try:
            now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        except ValueError:
            raise Fail(f"--now {args.now!r} is not an ISO time")
        if now.tzinfo is None:
            raise Fail("--now needs an offset, like 2026-01-05T09:00:00+00:00")
        text, rec, state_file = build(args, now, work)
        res = failure = None
        if args.item_triggers:
            try:
                res = file_item(item_request(rec["repo"], args.item_triggers, state_file, args.item_dest), args.client, send=not (args.no_open or args.dry_run))
            except Fail as e:                   # the report is still printed, and the status says the item was not opened
                failure = e
        if failure:
            rec["open_pending"] = args.item_triggers     # the item is still owed: the next run asks again, whatever its own numbers say
        elif args.item_triggers and not (res and res["sent"]):
            rec["open_pending"] = args.item_triggers     # nothing was sent (--no-open): this run's triggers are owed too, with any debt of an earlier run, or the baseline moving on would drop them
        if not args.dry_run:
            try:
                write_state(state_file, rec)         # after the call: the baseline moves on, with the debt recorded in it when the item was not opened
            except OSError as e:
                raise Fail(f"cannot write {state_file}: {e.strerror or e}", 1)
        if args.json:
            print(json.dumps(dict(rec, item_open=res) if res else rec, sort_keys=True))
        else:
            print(text)
            if res:
                print(render_item(res))
        if failure:
            raise failure
        return 0
    except Fail as e:
        print(f"test_trim_report: {e}", file=sys.stderr)
        return e.code
    finally:
        for d in work:
            shutil.rmtree(d, ignore_errors=True)
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)


if __name__ == "__main__":
    sys.exit(main())
