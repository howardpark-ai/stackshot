#!/usr/bin/env python3
"""tools/retest_skip.py — release.sh's catch-up decision: may a PR that is behind main skip the retest?

A PR whose checks passed but whose branch is behind main used to be brought up to date (main merged into it) and its tests waited for
again, a long wait, up to 3 rounds. The suite map that main's measured run keeps (tests/suitemap.py: for each suite, the files and
the Python files it reads) says when that wait cannot find anything the first run did not. release.sh calls:

    python3 tools/retest_skip.py --repo DIR --head SHA --main SHA (--map FILE | --slug ORG/REPO [--cache DIR]) [--max-age SECS]

The two sides are the PR's changed files (merge base..head) and the files main's new commits changed (merge base..main's tip). The retest is
skipped only when ALL of these hold; anything else, and anything this cannot read, retests as before:

    1. a usable map: it loads, the format is the one this reads, its file half was measured (strace on), every suite has a clean
       measurement, it is not older than --max-age (172800 s), and its commit is main's tip or in its history (a map of a commit that is not
       on main, or one this checkout does not have, is stale). A suite that failed only when measured (the slow release suite does, by timing
       out under strace and coverage) keeps its last clean measurement beside the new one as `carry`: that stands in for the clean one when it is
       not older than --max-age and the commit it was made at is in main's history; a suite with no usable carry refuses the map;
    2. neither side changes the harness or a check outside the suites (the ALWAYS set below): .github/, release.sh, deploy.sh, tests/run-suite, tests/pyproject.toml,
       tests/uv.lock, tests/suitemap.py, tools/retest_skip.py (the CI workflow, the release and the test runner read these); any `*.lock` file and any `# /// script` block of a Python
       file (the workflow's first step checks every script's lock against its inline metadata, which no suite does); tools/tool_text.py and
       tests/tool_text.snapshot.json (the tool-text job; what they read besides these, server.py and the tool functions and output helpers HELPERS names, needs no entry of its
       own: a change that matters there also changes the snapshot, which always retests); tools/clean_text.py (the clean-text workflow). The test tests/release_queue_scenario.py (13k) holds the list to every tools/ and tests/ file the workflows name;
    3. no file is changed by both sides;
    4. no change adds a dependency the map cannot show. The map's read sets are those of the map's commit, so a change that makes a file load, run or read another one is
       invisible to it. Either side's diff, in any Python file (and in a shell script, its added lines), that adds or changes an import or from line, a call of importlib, __import__,
       import_module, subprocess, os.system and its kin, exec, eval, compile, open, a read_text/read_bytes, a load (tomllib, json), a listing, glob, walk, existence or stat call
       (listdir, scandir, iterdir, glob, rglob, exists, is_file, is_dir, stat ...), or a string that looks like a repository path (a file name with an extension, anything with a slash,
       any string with a `*` or `?`, and a name at the repository's root: a top-level directory or file such as Makefile or LICENSE; docstrings are not read), retests; so does a Python
       file this cannot parse;
    5. main's side is also every file changed between the map's commit and main's tip (the drift since the map was measured; since the commit of its carry for a carried suite), with the same checks and the same reads: a file the map's
       commit did not have is unknown;
    6. every changed file is known: some suite reads it in the map, or it was in the map's commit tree (a file no suite reads is known,
       and reaches no suite); a file that is neither (new since the map, or a path the map has never seen) is unknown; for a carried suite, so is a file absent from the tree of its
       carry's commit that the suite does not list (it may read it by a listing of its directory, which a measurement from before the file existed cannot show);
    7. no suite reads both a file the PR changed and a file main's side changed. A suite reads a file when the map lists it (the
       Python files it ran, the files it opened, statted, ran or looked for, the Python files it read as text), and
       tests/<suite>_scenario.py is read by that suite; a file added or deleted is also read by the suites that listed its directory.

stdout, last line: `skip: <both file sets and why>` (exit 0) or `retest: <why>` (exit 1). Exit 2: the check failed itself (any exception that is not a reason to retest, caught in
main(): the line `retest: the check failed itself (...)` is printed, the traceback is on stderr); a usage error of the command line also exits 2. The caller treats anything but exit 0
with a `skip: ` line as "retest". The published map is used only when the run that published it ran on the map's own commit (the artifact's workflow run head sha equals the map's commit). Only git and, with --slug, `gh api` (two calls at most: the list of artifacts named suitemap, and
the newest one's zip when --cache does not hold it already) are run. The map comes from the artifact `suitemap` that main's run publishes (tests.yml)."""
from __future__ import annotations

import argparse
import ast
import collections
import datetime
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import zipfile

FORMAT = 1                    # tests/suitemap.py FORMAT: a map of another format is not read
MAX_AGE = 172800              # seconds: a map measured longer ago than this is stale (suitemap.py traces every suite's files at least daily)
HARNESS_DIRS = (".github/",)
HARNESS_FILES = ("release.sh", "deploy.sh", "tests/run-suite", "tests/pyproject.toml", "tests/uv.lock", "tests/suitemap.py", "tools/retest_skip.py")
# The checks the workflows run that are not suites (so the suite map knows nothing of what they read): a change to one of these inputs, on either side, retests.
#   tests.yml, first step: every `# /// script` Python file has a current <file>.lock       -> any `*.lock` file, and the script block of any Python file (script_block_changed)
#   tests.yml, tool-text job: tools/tool_text.py over tests/tool_text.snapshot.json
#   clean-text.yml: tools/clean_text.py
CHECK_FILES = {
    "tools/tool_text.py": "the tool-text job of the CI workflow runs",
    "tests/tool_text.snapshot.json": "the tool-text job of the CI workflow compares with",
    "tools/clean_text.py": "the clean-text workflow runs",
}
LOCK_WHY = "the CI workflow's lock check reads"
HARNESS_WHY = "the CI workflow, the release or the test runner reads"
SCRIPT_START, SCRIPT_END = "# /// script", "# ///"      # PEP 723
# what looks like a repository path in a string: a file name with an extension, or something with a slash in it (a directory, a relative path)
EXTS = "py|sh|bash|toml|json|jsonl|md|txt|yml|yaml|lock|cfg|ini|html|js|css|sql|service|timer|conf|csv|tsv"
PATHLIKE = re.compile(rf"^(?:\.{{0,2}}/)?(?:[\w.\-]+/)*[\w.\-]+\.(?:{EXTS})$|^(?:\.{{0,2}}/)?(?:[\w.\-]+/)+[\w.\-]*$")
TOKEN_SPLIT = re.compile(r"""[\s'"=:,;()\[\]{}<>|`$]+""")
CALL_NAMES = {"open", "__import__", "import_module", "exec", "eval", "compile", "Popen", "check_output", "check_call", "read_text", "read_bytes", "spec_from_file_location", "system", "popen",
              "listdir", "scandir", "walk", "iterdir", "glob", "rglob", "iglob", "exists", "isfile", "isdir", "is_file", "is_dir", "stat", "lstat", "load"}   # the last row: listings, globs, existence and stat checks, tomllib/json loads
CALL_ROOTS = {"importlib", "subprocess", "runpy", "pkgutil"}
GLOB_CHARS = ("*", "?")
SHELL_SOURCE = re.compile(r"^\s*(?:source|\.)\s+\S")
SHOWN = 12                    # file names named in the answer per side
ARTIFACT = "suitemap"
PER_PAGE = 100              # the most the artifacts API returns in one page


class Retest(Exception):
    """the answer is `retest: <why>`"""


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode:
        raise Retest(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:160] or r.returncode}")
    return r


def fetch_map(slug, cache):
    """the newest map artifact main's run published: (its JSON text, the head sha of the run that published it). Raises Retest when it cannot be had"""
    # every push publishes one (queue branches too), so main's can sit behind a run of other branches': ask for the API's largest page, not the first few
    try:
        r = subprocess.run(["gh", "api", f"repos/{slug}/actions/artifacts?name={ARTIFACT}&per_page={PER_PAGE}"], capture_output=True, text=True, timeout=60)
        arts = json.loads(r.stdout)["artifacts"] if r.returncode == 0 else None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        arts = None
    if arts is None:
        raise Retest("the suite map cannot be listed (gh api failed or answered something else)")
    art = next((a for a in arts if not a.get("expired") and (a.get("workflow_run") or {}).get("head_branch") == "main"), None)
    if art is None:
        raise Retest("no suite map is published (no unexpired artifact named suitemap from a run on main)")
    aid, sha = art.get("id"), (art.get("workflow_run") or {}).get("head_sha")
    if not isinstance(aid, int):
        raise Retest("the suite map's artifact has no id")
    path = os.path.join(cache, f"suitemap-{aid}.json") if cache else ""
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read(), sha
    try:
        z = subprocess.run(["gh", "api", f"repos/{slug}/actions/artifacts/{aid}/zip"], capture_output=True, timeout=180)
        if z.returncode:
            raise Retest("the suite map cannot be downloaded (gh api failed)")
        with zipfile.ZipFile(io.BytesIO(z.stdout)) as zf:
            text = zf.read("map.json").decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError, subprocess.TimeoutExpired):
        raise Retest("the suite map's download is not a zip holding map.json")
    if cache:   # kept by artifact id, written whole; the older ones go
        try:
            os.makedirs(cache, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".suitemap-", dir=cache)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            for n in os.listdir(cache):
                if n.startswith("suitemap-") and n.endswith(".json") and os.path.join(cache, n) != path:
                    os.unlink(os.path.join(cache, n))
        except OSError:
            pass   # a cache that cannot be written costs a download next time, nothing else
    return text, sha


UNCHECKED = object()   # published_commit when the map came from a file: nothing to compare with


def clean_entry(e):
    return isinstance(e, dict) and e.get("ok") and not e.get("failed") and all(isinstance(e.get(k), list) for k in ("files", "whole", "dirs")) and isinstance(e.get("py"), dict)


def use_carry(name, e, repo, main, max_age, now):
    """suite `name` has no clean measurement: (its entry made whole from the carry the map kept, the commit the carry was made at). The entry is the union of the carry and
    what the unclean run measured (a timed-out run measured part of it). Raises Retest when there is no carry, or one that is not sound"""
    c = e.get("carry") if isinstance(e, dict) and not e.get("failed") else None
    if not (isinstance(c, dict) and all(isinstance(c.get(k), list) for k in ("files", "whole", "dirs")) and isinstance(c.get("py"), dict) and isinstance(c.get("at"), str) and c["at"]):
        raise Retest(f"the suite map has no clean measurement of suite {name}")
    try:
        t = datetime.datetime.fromisoformat(c["traced"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        age = (now or datetime.datetime.now(datetime.timezone.utc)) - t
    except (KeyError, ValueError, TypeError):
        raise Retest(f"the suite map has no clean measurement of suite {name}, and says no time its earlier one was made")
    if age.total_seconds() > max_age:
        raise Retest(f"the suite map has no clean measurement of suite {name}, and its earlier one is stale: made {int(age.total_seconds() // 3600)} h ago (more than {max_age // 3600} h)")
    at = c["at"]
    if git(repo, "cat-file", "-e", f"{at}^{{commit}}", check=False).returncode or git(repo, "merge-base", "--is-ancestor", at, main, check=False).returncode:
        raise Retest(f"the suite map has no clean measurement of suite {name}, and its earlier one is of commit {at[:7]}, which is not in main's history here")
    sets = {k: sorted(set(c[k]) | (set(e[k]) if isinstance(e.get(k), list) else set())) for k in ("files", "whole", "dirs")}
    py = {**c["py"], **(e["py"] if isinstance(e.get("py"), dict) else {})}
    return {**e, **sets, "py": py, "ok": True}, at


def load_map(text, repo, main, max_age, now=None, published_commit=UNCHECKED):
    try:
        m = json.loads(text)
    except ValueError:
        raise Retest("the suite map is not JSON")
    if not (isinstance(m, dict) and m.get("format") == FORMAT and isinstance(m.get("suites"), dict) and m["suites"] and isinstance(m.get("commit"), str)):
        raise Retest("the suite map is of another format, or empty")
    if not m.get("strace"):
        raise Retest("the suite map has no file measurement (no strace)")
    carried = {}   # suite -> the commit its carried measurement was made at
    for name, e in m["suites"].items():
        if not clean_entry(e):
            m["suites"][name], carried[name] = use_carry(name, e, repo, main, max_age, now)
    m["carried"] = carried
    try:
        t = datetime.datetime.fromisoformat(m["measured"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        age = (now or datetime.datetime.now(datetime.timezone.utc)) - t
    except (KeyError, ValueError, TypeError):
        raise Retest("the suite map says no time it was measured")
    if age.total_seconds() > max_age:
        raise Retest(f"the suite map is stale: measured {int(age.total_seconds() // 3600)} h ago (more than {max_age // 3600} h)")
    c = m["commit"]
    if published_commit is not UNCHECKED and published_commit != c:
        raise Retest(f"the suite map says it is of commit {c[:7]}, but the run that published it was on {str(published_commit)[:7] if published_commit else 'a commit GitHub did not name'}")
    if git(repo, "cat-file", "-e", f"{c}^{{commit}}", check=False).returncode or git(repo, "merge-base", "--is-ancestor", c, main, check=False).returncode:
        raise Retest(f"the suite map is stale: its commit {c[:7]} is not in main's history here")
    return m


def changed(repo, a, b):
    """[(status, path)] of a..b, one row per path (renames as a delete and an add)"""
    out = git(repo, "diff", "--name-status", "--no-renames", "-z", a, b).stdout.split("\0")
    out = [x for x in out if x != ""]
    return list(zip(out[0::2], out[1::2]))


def always_reason(path):
    """why a change to `path` is always a retest (the harness, the checks outside the suites), else None"""
    if path.startswith(HARNESS_DIRS) or path in HARNESS_FILES:
        return HARNESS_WHY
    if path.endswith(".lock"):
        return LOCK_WHY
    return CHECK_FILES.get(path)


def blob(repo, rev, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""


def kind(path, text):
    """py, sh or None: by the name, else (a file with no extension) by its first line"""
    ext = os.path.splitext(path)[1]
    if ext == ".py":
        return "py"
    if ext in (".sh", ".bash"):
        return "sh"
    if ext:
        return None
    first = text.split("\n", 1)[0]
    if first.startswith("#!"):
        return "py" if "python" in first else "sh" if re.search(r"\b(?:ba|z|da)?sh\b", first) else None
    return None


def script_block(text):
    """the lines of the first `# /// script` block (to the end of the file when it is not closed), else ()"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.rstrip() == SCRIPT_START:
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip() == SCRIPT_END:
                    return tuple(lines[i:j + 1])
            return tuple(lines[i:])
    return ()


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def looks_like_path(tok, roots):
    """a token that names a repository path: a file name with an extension, something with a slash, a glob (a `*` or `?`), or a name at the repository's root (a top-level directory or file)"""
    return bool(tok) and (bool(PATHLIKE.match(tok)) or any(c in tok for c in GLOB_CHARS) or tok in roots)


def py_dependencies(text, roots=frozenset()):
    """a Counter of what a Python source could make load, run or read another file: its import statements, the calls that load, run or read ('call'), and the strings that look like a
    repository path ('path'). A docstring is not read. Raises SyntaxError"""
    tree = ast.parse(text)
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
    c = collections.Counter()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            c["import", ast.dump(n)] += 1
        elif isinstance(n, ast.Call):
            d = dotted(n.func)
            if d and (d[0] in CALL_ROOTS or d[-1] in CALL_NAMES or (d[0] == "os" and len(d) > 1 and d[-1].startswith(("exec", "spawn")))):
                c["call", ast.dump(n)] += 1
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            for tok in TOKEN_SPLIT.split(n.value):
                if looks_like_path(tok, roots):
                    c["path", tok] += 1
    return c


KIND_WHY = {"import": "an import", "call": "a call that loads, runs or reads a file", "path": "a string that looks like a repository path"}


def added_dependency(repo, old, new, path, roots=frozenset()):
    """why the change of `path` from revision `old` to `new` adds a dependency the suite map cannot show, else None. A Python file that cannot be parsed is a reason too"""
    nt = blob(repo, new, path)
    if not nt:
        return None      # deleted (or empty): nothing is added
    ot = blob(repo, old, path)
    k = kind(path, nt)
    if k == "py":
        try:
            added = py_dependencies(nt, roots) - (py_dependencies(ot, roots) if ot else collections.Counter())
        except SyntaxError:
            return f"{path} cannot be read as Python"
        if added:
            return f"{path} adds or changes {' and '.join(sorted({KIND_WHY[a] for a, _ in added}))}"
    elif k == "sh":
        old_lines = collections.Counter(ot.splitlines())
        for ln in nt.splitlines():
            if old_lines[ln] > 0:
                old_lines[ln] -= 1
                continue
            code = ln.strip()
            if not code or code.startswith("#"):
                continue
            if SHELL_SOURCE.match(code) or any(looks_like_path(t, roots) for t in TOKEN_SPLIT.split(code)):
                return f"{path} adds or changes a line that sources or names a file"
    return None


def script_block_changed(repo, old, new, path):
    """a `# /// script` block (PEP 723) that differs between the two revisions of a Python file"""
    return path.endswith(".py") and script_block(blob(repo, old, path)) != script_block(blob(repo, new, path))


def shown(paths):
    p = sorted(paths)
    return ", ".join(p[:SHOWN]) + (f" and {len(p) - SHOWN} more" if len(p) > SHOWN else "")


def decide(repo, head, main, mapfile_text, max_age=MAX_AGE, now=None, published_commit=UNCHECKED):
    """the answer line; Retest is raised for every reason to retest"""
    m = load_map(mapfile_text, repo, main, max_age, now, published_commit)
    S = m["suites"]
    mc = m["commit"]
    mb = git(repo, "merge-base", main, head).stdout.strip()
    if not mb:
        raise Retest("the PR and main have no merge base")
    pr, mn = changed(repo, mb, head), changed(repo, mb, main)
    if not mn:
        raise Retest("main has no new commits since the merge base: nothing to catch up on")
    # main's side is what main's new commits changed AND what changed between the map's commit and main's tip: the map's read sets are those of its commit, so all of it counts as news
    # A carried suite's read sets are those of the commit its carry was made at, which is older: the drift is counted from there too.
    bases = tuple(dict.fromkeys((mc, *m["carried"].values())))
    side_main = list(mn)
    for b in bases:
        side_main += [r for r in changed(repo, b, main) if r not in side_main]
    roots = frozenset(n for rev in (*bases, head, main) for n in git(repo, "ls-tree", "--name-only", "-z", rev).stdout.split("\0") if n)   # the repository's top-level names
    sides = (("the PR", pr, ((mb, head),)), ("main's side", side_main, tuple(dict.fromkeys(((mb, main), *((b, main) for b in bases))))))
    for side, rows, _ in sides:
        for _, p in rows:
            why = always_reason(p)
            if why:
                raise Retest(f"{side} changes {p}, which {why}")
    for side, rows, revs in sides:
        for st, p in rows:
            if st != "D":
                for old, new in revs:
                    if script_block_changed(repo, old, new, p):
                        raise Retest(f"{side} changes the `# /// script` block of {p}, which {LOCK_WHY}")
    for side, rows, revs in sides:
        for st, p in rows:
            if st != "D":
                for old, new in revs:
                    why = added_dependency(repo, old, new, p, roots)
                    if why:
                        raise Retest(f"{side}: {why}, a dependency the suite map of {mc[:7]} cannot show")
    both = {p for _, p in pr} & {p for _, p in mn}
    if both:
        raise Retest(f"both sides change {shown(both)}")
    read = {s: set(e["py"]) | set(e["files"]) | set(e["whole"]) | {f"tests/{s}_scenario.py"} for s, e in S.items()}
    in_tree = set(git(repo, "ls-tree", "-r", "--name-only", "-z", mc).stdout.split("\0")) - {""}

    # A carried suite's read sets are those of the commit its carry was made at: a file added since then is in the map's tree, yet neither the carry nor the unclean run could have listed it,
    # so a suite that reads it (a listing of its directory, a glob) is not known to. A change to such a file, on either side, is unknown unless the carried suite lists it.
    carried_trees = {at: set(git(repo, "ls-tree", "-r", "--name-only", "-z", at).stdout.split("\0")) - {""} for at in set(m["carried"].values())}

    def reached(rows):
        hit, unknown = {}, []
        for st, p in rows:
            by = {s for s, r in read.items() if p in r}
            if (not by and p not in in_tree) or any(p not in carried_trees[at] and p not in read[s] for s, at in m["carried"].items()):
                unknown.append(p)
                continue
            if st in ("A", "D"):
                by |= {s for s, e in S.items() if os.path.dirname(p) in e["dirs"]}
            hit[p] = hit.get(p, set()) | by
        return hit, unknown

    ph, pu = reached(pr)
    mh, mu = reached(side_main)
    if pu or mu:
        raise Retest(f"unknown to the suite map of {mc[:7]}{' (or new since the earlier measurement of a suite that failed only when measured)' if m['carried'] else ''}: {shown(set(pu) | set(mu))}")
    shared = set().union(*ph.values()) & set().union(*mh.values()) if ph and mh else set()
    if shared:
        pf = sorted(p for p, s in ph.items() if s & shared)
        mf = sorted(p for p, s in mh.items() if s & shared)
        raise Retest(f"suite(s) {shown(shared)} read both what the PR changed ({shown(pf)}) and what main's side changed ({shown(mf)})")
    n = git(repo, "rev-list", "--count", f"{mb}..{main}").stdout.strip()
    older = {p for _, p in side_main} - {p for _, p in mn}
    return (f"skip: no suite reads both sides (map of {mc[:7]}); the PR changed {len(pr)} file(s): {shown({p for _, p in pr}) or 'none'}; "
            f"main's {n} new commit(s) since {mb[:7]} changed {len(mn)} file(s): {shown({p for _, p in mn})}"
            + (f"; {len(older)} more file(s) changed since the map's commit: {shown(older)}" if older else "")
            + (f"; suite(s) {shown(m['carried'])} failed only when measured, so their reads are those of an earlier clean measurement ({shown({c[:7] for c in m['carried'].values()})})" if m["carried"] else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--main", required=True)
    ap.add_argument("--map", help="a map file (the tests use this); else --slug fetches the newest published one")
    ap.add_argument("--slug", help="ORG/REPO whose artifact `suitemap` is read with gh api")
    ap.add_argument("--cache", help="a folder that keeps the downloaded map by artifact id")
    ap.add_argument("--max-age", type=int, default=MAX_AGE)
    a = ap.parse_args()
    try:
        published = UNCHECKED
        if a.map:
            try:
                with open(a.map, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                raise Retest("the suite map file cannot be read")
        elif a.slug:
            text, published = fetch_map(a.slug, a.cache)
        else:
            raise Retest("no suite map was given")
        print(decide(a.repo, a.head, a.main, text, a.max_age, published_commit=published))
        return 0
    except Retest as e:
        print(f"retest: {e}")
        return 1
    except Exception as e:      # a bug in this check, or something it did not foresee: no answer to trust, said plainly, exit 2 (release.sh retests)
        traceback.print_exc(file=sys.stderr)
        print(f"retest: the check failed itself ({type(e).__name__}: {str(e)[:160]})")
        return 2


if __name__ == "__main__":
    sys.exit(main())
