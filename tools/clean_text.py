#!/usr/bin/env python3
"""tools/clean_text.py: commit messages, branch names, PR titles and PR bodies carry none of the instance owner's data.

Standard library only (Python 3.12+). CI runs it on every pull request (.github/workflows/clean-text.yml); a person or a
commit-msg hook can run it on a message file or a branch name. CONTRIBUTING.md ("Commit and PR text") states the rule.

What is checked, line by line:
  * generic patterns built in (they are no one's data): a board item id (board#N, board-tmp-<name>#N) and a link to a
    board site's items/<n> path (a URL with a host);
  * the deny list: Python regexes, one per line, case-insensitive, read from the environment variable CLEAN_TEXT_DENY
    (in CI the repository secret of that name, given to this one step only: a secret is masked in the logs, a variable
    is not), else the per-user file ${XDG_CONFIG_HOME:-$HOME/.config}/stackshot/clean-text-deny (for the git hooks and a
    person running the check). The list names the instance's machines, sessions, domains and owner, so it is the owner's
    data and is never written into the repository. Neither one (a fork's pull request gets no secret): only the generic
    patterns run, and the output says so in one line (not a failure). A deny pattern is never printed, and neither is the
    text of a line it hit: a hit names the field, the line number and the pattern's line number in the list ("deny pattern 3").
Lines that are allowed on purpose are not matched against the deny list: the Claude or Anthropic `Co-Authored-By:` trailer (with the Anthropic noreply address; a person's trailer is checked) and the `Claude-Session:` trailer,
the "Generated with [Claude Code]" footer line and a bare claude.ai/code/session URL line (whole lines only: text added to
one is checked). The generic patterns still read them.
The standard merge subjects ("Merge branch 'main' into <branch>", "Merge pull request #N from <owner>/<branch>", and
`git pull`'s "Merge branch '<x>' of <url> into <branch>") are skipped as the first line of a commit message, except that
the branch names in them are checked as branch names (the owner and the URL are not).

    python3 tools/clean_text.py --message-file F [--message-file G ...]   # a commit message file
    python3 tools/clean_text.py --message-stdin                            # a commit message on standard input
    python3 tools/clean_text.py --branch NAME                              # a branch name
    python3 tools/clean_text.py --title TEXT --body-file F                 # a PR title and body, before opening the PR
    python3 tools/clean_text.py --commits BASE..HEAD                       # every commit message of a range (git is run in the cwd)
    python3 tools/clean_text.py --new-commits SHA [--remote NAME]          # commits of SHA that remote NAME lacks (no NAME: all of them)
    python3 tools/clean_text.py --from-env                                 # CI: PR_TITLE, PR_BODY, PR_BRANCH, BASE_REV, HEAD_SHA
The git hooks in .githooks/ (core.hooksPath, see CONTRIBUTING.md) run it before a commit is made and before a push.
The modes combine. Exit 0: clean; 1: something matched; 2: the call itself is wrong (a bad deny pattern, an unreadable file,
a git failure).
"""
import argparse, os, re, subprocess, sys, warnings

# (label, regex). Generic: nothing here is specific to one instance.
GENERIC = [
    ("board item id (board#N)", re.compile(r"board#\d+", re.I)),                     # no left boundary: _board#N and xboard#N count
    ("board item id (board-tmp-<name>#N)", re.compile(r"board-tmp-[a-z0-9-]+#\d+", re.I)),
    ("link to a board item (host/items/N)", re.compile(r"https?://[^\s/]+/items/\d+", re.I)),
]

# The allowed boilerplate, exempt from the deny list. Each pattern is the whole line, so text added to such a line is checked.
ALLOWED_LINES = [
    re.compile(r"^\s*Co-Authored-By:\s+(?:Claude|Anthropic)\b[^<>\n]*<noreply@anthropic\.com>\s*$", re.I),   # a person's trailer is checked
    re.compile(r"^\s*Claude-Session:\s+https://claude\.ai/code/session_[\w-]+\s*$", re.I),
    re.compile(r"^\s*(?:\U0001F916\s*)?Generated with \[Claude Code\]\(https://claude\.(?:com|ai)/claude-code\)\s*$", re.I),
    re.compile(r"^\s*https://claude\.ai/code/session_[\w-]+\s*$", re.I),
]

# GitHub's own merge subjects: only the first line of a message is skipped, and only these exact shapes.
# (regex, the groups that are branch names): the subject is skipped, but its branch names are checked as branch names.
MERGE_SUBJECTS = [
    (re.compile(r"^Merge branch '(?:main|master)' into (\S+)$"), (1,)),
    (re.compile(r"^Merge branch '([^']+)' of \S+(?: into (\S+))?$"), (1, 2)),            # a pull
    (re.compile(r"^Merge remote-tracking branch 'origin/(?:main|master)' into (\S+)$"), (1,)),
    (re.compile(r"^Merge pull request #\d+ from [\w.-]+/(\S+)$"), (1,)),
]


def merge_branches(line):
    """None when the line is not a standard merge subject, else the branch names it holds."""
    for rx, groups in MERGE_SUBJECTS:
        m = rx.match(line)
        if m:
            return [m.group(g) for g in groups if m.group(g)]
    return None


def load_deny(raw):
    """([(line number, compiled regex)], [(line number, reason)]) from the text of CLEAN_TEXT_DENY. A pattern that does not
    compile, or that matches the empty string (it would hit every line), is reported by its number only: neither the pattern
    nor the compiler's message (which can quote it) is kept."""
    deny, bad = [], []
    for n, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            with warnings.catch_warnings():          # a FutureWarning would name the source line, not the pattern, but stay quiet
                warnings.simplefilter("ignore")
                rx = re.compile(line, re.I)
        except (re.error, OverflowError, RecursionError, ValueError):
            bad.append((n, "is not a valid regex"))
            continue
        if rx.search(""):
            bad.append((n, "matches the empty string"))
            continue
        deny.append((n, rx))
    return deny, bad


def classified_lines(text, is_message=False):
    """[(line number, line, allowed)] for the lines of one field: allowed is True for the boilerplate lines, which only the
    generic patterns still look at (a board id typed into a trailer name is still one), never the deny list. A standard
    merge subject is left out."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        if i == 0 and is_message and merge_branches(line) is not None:
            continue
        out.append((i + 1, line, any(p.match(line) for p in ALLOWED_LINES)))
    return out


def check_field(label, text, deny, is_message=False):
    """[(label, line number, line text or None, why)] for every hit of a generic or a deny pattern in the field. The text of a
    line a deny pattern hit is None: the log never repeats it."""
    hits = []
    if is_message:                       # the subject of a standard merge is skipped, but the branch names in it are not
        first = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")[0]
        for name in merge_branches(first) or []:
            hits += check_field(f"{label}, merge subject branch", name, deny, False)
    for no, line, allowed in classified_lines(text, is_message):
        deny_hits = [] if allowed else [n for n, rx in deny if rx.search(line)]
        shown = None if deny_hits else line
        for name, rx in GENERIC:
            if rx.search(line):
                hits.append((label, no, shown, name))
        for n in deny_hits:
            hits.append((label, no, None, f"deny pattern {n}"))
    return hits


def read_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        print(f"clean-text: cannot read {path}: {e.__class__.__name__}", file=sys.stderr)
        raise SystemExit(2)


def deny_file():
    """The per-user deny file, ${XDG_CONFIG_HOME:-$HOME/.config}/stackshot/clean-text-deny (one regex per line). It is never in
    the repository. A relative XDG_CONFIG_HOME is ignored, as the XDG base directory specification says."""
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "stackshot", "clean-text-deny")


def deny_source():
    """(raw deny text, where it came from) : CLEAN_TEXT_DENY when it holds anything, else the deny file when there is one,
    else ("", None). The name of the file is not secret; its content is never printed."""
    raw = os.environ.get("CLEAN_TEXT_DENY", "")
    if raw.strip():
        return raw, "CLEAN_TEXT_DENY"
    path = deny_file()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(), path
    except FileNotFoundError:
        return "", None
    except OSError as e:
        print(f"clean-text: cannot read the deny file {path}: {e.__class__.__name__}", file=sys.stderr)
        raise SystemExit(2)


def commits_in(revs):
    """[(short sha, message)] for the commits `git log` selects with the revision arguments `revs` (a list, e.g. ["A..B"] or
    ["SHA", "--not", "--remotes=origin"]), newest first. `git log -z` ends each record with a NUL, which a commit message cannot hold,
    so the output is read as alternating sha and message and no byte of a message can fake a boundary. The bytes are decoded
    with errors="replace" (a message need not be UTF-8)."""
    rng = " ".join(revs)
    try:
        r = subprocess.run(["git", "log", "-z", "--format=%H%x00%B", *revs], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        err = (getattr(e, "stderr", b"") or b"").decode("utf-8", "replace").strip().splitlines()
        print(f"clean-text: git log {rng} failed: {err[0] if err else e.__class__.__name__}", file=sys.stderr)
        raise SystemExit(2)
    parts = r.stdout.decode("utf-8", "replace").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2 or not all(re.fullmatch(r"[0-9a-f]{40,64}", parts[i].strip()) for i in range(0, len(parts), 2)):
        print(f"clean-text: git log {rng} gave output that could not be read", file=sys.stderr)
        raise SystemExit(2)
    return [(parts[i].strip()[:10], parts[i + 1]) for i in range(0, len(parts), 2)]


def trim(line, n=200):
    line = line.strip()
    return line if len(line) <= n else line[: n - 1] + "…"


def run(fields, deny_raw, out=sys.stdout, source=None):
    """fields: [(label, text, is_message)]. Prints the verdict; returns the exit code."""
    deny, bad = load_deny(deny_raw)
    for n, why in bad:
        print(f"clean-text: deny pattern {n} {why}; fix {source or 'the deny list'}", file=out)
    if bad:
        return 2
    if deny:
        print(f"clean-text: generic patterns and {len(deny)} deny pattern(s)", file=out)
    else:
        print("clean-text: the deny list was not available (CLEAN_TEXT_DENY is empty or unset and there is no deny file; "
              "a fork's pull request gets no secret): only the generic patterns ran", file=out)
    hits = []
    for label, text, is_message in fields:
        hits += check_field(label, text, deny, is_message)
    for label, no, line, why in hits:
        print(f"FAIL {label}, line {no}: " + (f"{trim(line)!r}  <- {why}" if line is not None else why), file=out)
    if hits:
        print(f"clean-text: {len(hits)} problem(s) in {len({h[0] for h in hits})} field(s). The rule is in CONTRIBUTING.md, "
              f"'Commit and PR text': write the change in plain engineering terms; the link to a board item lives on the board.", file=out)
        return 1
    print(f"clean-text: ok ({len(fields)} field(s) checked)", file=out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--message-file", action="append", default=[], metavar="F", help="a commit message file (repeatable)")
    ap.add_argument("--message-stdin", action="store_true", help="a commit message read from standard input")
    ap.add_argument("--branch", action="append", default=[], metavar="NAME", help="a branch name (repeatable)")
    ap.add_argument("--title", metavar="TEXT", help="a PR title")
    ap.add_argument("--body-file", metavar="F", help="a PR body file")
    ap.add_argument("--commits", metavar="RANGE", help="check every commit message of a git range, run in the cwd (BASE..HEAD)")
    ap.add_argument("--new-commits", metavar="SHA", help="check every commit message reachable from SHA that the remote given by --remote does not have (a new branch about to be pushed); without --remote, every commit reachable from SHA")
    ap.add_argument("--remote", metavar="NAME", help="with --new-commits: the remote being pushed to; commits on its remote-tracking branches are skipped, those only other remotes have are checked")
    ap.add_argument("--from-env", action="store_true", help="CI: read PR_TITLE, PR_BODY, PR_BRANCH, BASE_REV, HEAD_SHA from the environment")
    a = ap.parse_args(argv)

    fields = []
    for p in a.message_file:
        fields.append((f"message {os.path.basename(p)}", read_file(p), True))
    if a.message_stdin:
        fields.append(("message", sys.stdin.buffer.read().decode("utf-8", "replace"), True))
    for b in a.branch:
        fields.append(("branch", b, False))
    if a.title is not None:
        fields.append(("title", a.title, False))
    if a.body_file:
        fields.append(("body", read_file(a.body_file), False))
    if a.commits:
        for sha, msg in commits_in([a.commits]):
            fields.append((f"commit {sha}", msg, True))
    if a.new_commits:
        # With a remote name: the commits that remote's tracking branches lack. A commit another remote has does not count as
        # published here. Without one (or a name git would read as a glob): every commit reachable from SHA, the safe direction.
        revs = [a.new_commits]
        if a.remote and not re.search(r"[*?\[\]]", a.remote):
            revs += ["--not", f"--remotes={a.remote}"]
        for sha, msg in commits_in(revs):
            fields.append((f"commit {sha}", msg, True))
    if a.from_env:
        env = os.environ
        fields.append(("title", env.get("PR_TITLE", ""), False))
        fields.append(("body", env.get("PR_BODY", ""), False))
        fields.append(("branch", env.get("PR_BRANCH", ""), False))
        base, head = env.get("BASE_REV", ""), env.get("HEAD_SHA", "")
        if base and head:
            for sha, msg in commits_in([f"{base}..{head}"]):
                fields.append((f"commit {sha}", msg, True))
        else:
            print("clean-text: BASE_REV or HEAD_SHA is not set: the commits were not checked", file=sys.stderr)
            return 2
    if not fields and not (a.commits or a.new_commits):      # a range that holds no commit is a clean input, not a missing one
        ap.print_usage(sys.stderr)
        return 2
    raw, source = deny_source()
    return run(fields, raw, source=source)


if __name__ == "__main__":
    sys.exit(main())
