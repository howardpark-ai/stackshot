#!/usr/bin/env python3
"""tools/clean_text.py: commit messages, branch names, PR titles and PR bodies carry none of the instance owner's data.

Standard library only (Python 3.12+). CI runs it on every pull request (.github/workflows/clean-text.yml); a person or a
commit-msg hook can run it on a message file or a branch name. CONTRIBUTING.md ("Commit and PR text") states the rule.

What is checked, line by line:
  * generic patterns built in (they are no one's data): a board item id (board#N, board-tmp-<name>#N), a link to a
    board site's items/<n> path (a URL with a host);
  * attribution lines, which this public repository refuses (a push cannot be taken back, and GitHub keeps every pull
    request ref): a `Co-Authored-By:` trailer of any author, a `Claude-Session:` trailer, a claude.ai/claude.com session
    URL, and the "Generated with/by/using Claude" footer. A hit prints its kind and line number and does not repeat the line;
  * the deny list: Python regexes, one per line, case-insensitive, read from the environment variable CLEAN_TEXT_DENY
    (in CI the repository secret of that name, given to this one step only: a secret is masked in the logs, a variable
    is not), else the per-user file ${XDG_CONFIG_HOME:-$HOME/.config}/stackshot/clean-text-deny (for the git hooks and a
    person running the check). The list names the instance's machines, sessions, domains and owner, so it is the owner's
    data and is never written into the repository. Neither one (a fork's pull request gets no secret): only the generic
    patterns run, and the output says so in one line (not a failure). A deny pattern is never printed, and neither is the
    text of a line it hit: a hit names the field, the line number and the pattern's line number in the list ("deny pattern 3").
No line is exempt: every line of every field is read by the generic patterns, the attribution patterns and the deny list
alike. The one exception is the four commits of ATTRIBUTION_EXEMPT_SHAS (old commits on main with a Co-Authored-By line, met
only when a push walks all history), exempt from the attribution patterns alone. In CI only the pull request's own commits are
read (base..head), so older commits on main are never looked at.
The standard merge subjects ("Merge branch 'main' into <branch>", "Merge pull request #N from <owner>/<branch>", and
`git pull`'s "Merge branch '<x>' of <url> into <branch>") are skipped as the first line of a commit message, except that
the branch names in them are checked as branch names (the owner and the URL are not) and that the attribution patterns
read the whole subject.

    python3 tools/clean_text.py --message-file F [--message-file G ...]   # a commit message file
    python3 tools/clean_text.py --message-stdin                            # a commit message on standard input
    python3 tools/clean_text.py --branch NAME                              # a branch name
    python3 tools/clean_text.py --title TEXT --body-file F                 # a PR title and body, before opening the PR
    python3 tools/clean_text.py --commits BASE..HEAD                       # every commit message of a range (git is run in the cwd)
    python3 tools/clean_text.py --new-commits SHA [--remote NAME]          # commits of SHA that remote NAME lacks (no NAME: all of them)
    python3 tools/clean_text.py --from-env                                 # CI: PR_TITLE, PR_BODY, PR_BRANCH, BASE_REV, HEAD_SHA
The git hooks in .githooks/ (core.hooksPath, see CONTRIBUTING.md) run it before a commit is made and before a push (and also run the machine-wide hook of the same name, when one is installed: the global core.hooksPath first, then the XDG hooks directory).
The modes combine. Exit 0: clean; 1: something matched; 2: the call itself is wrong (a bad deny pattern, an unreadable file,
a git failure).
"""
import argparse, os, re, subprocess, sys, urllib.parse, warnings

# (label, regex). Generic: nothing here is specific to one instance.
GENERIC = [
    ("board item id (board#N)", re.compile(r"board#\d+", re.I)),                     # no left boundary: _board#N and xboard#N count
    ("board item id (board-tmp-<name>#N)", re.compile(r"board-tmp-[a-z0-9-]+#\d+", re.I)),
    ("link to a board item (host/items/N)", re.compile(r"https?://[^\s/]+/items/\d+", re.I)),
]

# Attribution lines are refused in this public repository, whoever the author. They are kept apart from GENERIC because a hit never
# prints its line: the kind of hit and its place are enough, and the check does not repeat a refused session URL in its own output
# (the pull request's title and body are public anyway; the workflow's env header prints them). A trailer counts only at the start of a line, after any quote or list mark a pasted message carries (a bullet, a number
# with a dot or a bracket); what follows the colon is not read, so a trailer of any name and address is refused, and prose that merely
# names the trailer is not. Each pattern is tried on the line as written and with its %XX escapes decoded, so a session URL cannot hide
# behind an encoded path.
class _Footer:
    """The "Generated with/by/using Claude ..." footer line, found by reading the line the way a person does instead of by its
    spellings: HTML tags, markdown links (the link text is kept), bare URLs, markup, punctuation and emoji are stripped, and the line
    is a hit when what is left starts with "generated with", "generated by" or "generated using" and names Claude in the rest of the
    line. A line that merely contains the words further in, as in a sentence about numbers, is not read by this rule; only the
    narrower inline form "Generated with Claude Code" (and the product's link) is refused anywhere in a line. Every repeat here is
    bounded, so a long run of "<" or "[" costs time linear in the line."""
    _tag = re.compile(r"<[^<>]{0,300}>")
    _link = re.compile(r"\[([^\[\]]{0,300})\]\([^()\s]{0,500}\)")
    _url = re.compile(r"(?:https?://|www\.)\S+", re.I)
    _noise = re.compile(r"[\W_]+")
    _start = re.compile(r"^ ?generated (?:with|by|using) (.*)$", re.I)
    _name = re.compile(r"\bclaude\b", re.I)
    # "Generated with Claude Code" inside a longer line (markdown around the name allowed), and the product's link
    _inline = re.compile(r"\bGenerated\s+(?:with|by|using)\s+[\[*_`(]*\s*Claude[\s*_`\]]*Code\b|claude\.(?:com|ai)/claude-code", re.I)

    def search(self, line):
        if self._inline.search(line):
            return True
        if "generated" not in line.lower():                 # the cheap exit for nearly every line
            return False
        text = self._tag.sub(" ", line)
        text = self._link.sub(r"\1", text)
        text = self._url.sub(" ", text)
        text = self._noise.sub(" ", text)
        m = self._start.match(text)
        return bool(m and self._name.search(m.group(1)))


ATTRIBUTION = [
    ("Co-Authored-By trailer (attribution lines are refused)", re.compile(r"^\s*(?:(?:[>*+\u2022-]|\d+[.)])\s*)*Co-Authored-By\s*:", re.I)),
    ("Claude-Session trailer (attribution lines are refused)", re.compile(r"\bClaude-Session\s*:", re.I)),
    # A claude.ai or claude.com URL that holds session_ within 512 characters of the host (the host ends at a non-name character, so
    # "claude.commands.session_start" and "claude.ai-tools/.../session_store.py" are not URLs), and the code-session path of claude.ai
    # with a port, a trailing dot or doubled slashes. The repeat is bounded so a long run of "claude.ai" costs time linear in the line.
    ("claude.ai/code session URL (session links are refused)",
     re.compile(r"claude\.(?:ai|com)(?![\w-])\S{0,512}?session_|claude\.ai\.?(?::\d*)?/+code/", re.I)),
    # the footer: a line that, once markup is stripped, starts "Generated with/by/using" and names Claude, a "Generated with Claude Code"
    # inside a longer line, and the product's link (see _Footer; one label, so a footer line is reported once)
    ("'Generated with Claude' footer (attribution lines are refused)", _Footer()),
]

# Four commits already on main carry a Co-Authored-By line, from before this rule. A push by a URL no remote has, or to a remote with no
# tracking branch, walks all history ("more, not less", pre-push), so these exact commits, named by full sha, are exempt from the
# ATTRIBUTION patterns only; the deny list and every other generic pattern still read them. The set is closed: naming a sha here
# cannot exempt a new commit, since a sha is fixed by the commit's own content. Main's history is never rewritten.
ATTRIBUTION_EXEMPT_SHAS = frozenset({
    "004575b22737cffeb11494dbdc02e9dec0e96ec9",
    "4e8b0fc3018b7b455ff704e938349d891227d0e6",
    "dd4da4cd38eacb62ce052d0027c074f31246ae61",
    "eb96e2362ae290db94c3e002d7fe82b386073483",
})

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


def numbered_lines(text, is_message=False):
    """[(line number, line)] for the lines of one field. A standard merge subject is left out."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        if i == 0 and is_message and merge_branches(line) is not None:
            continue
        out.append((i + 1, line))
    return out


def attribution_hits(line):
    """The labels of the attribution patterns that hit the line as written or with its %XX escapes decoded."""
    decoded = urllib.parse.unquote(line)
    return [name for name, rx in ATTRIBUTION if rx.search(line) or rx.search(decoded)]


def check_field(label, text, deny, is_message=False, exempt_attribution=False):
    """[(label, line number, line text or None, why)] for every hit of a generic, an attribution or a deny pattern in the field. The
    text of a line a deny or an attribution pattern hit is None: the log never repeats it. exempt_attribution switches off the
    attribution patterns only (the commits in ATTRIBUTION_EXEMPT_SHAS)."""
    hits = []
    if is_message:                       # the subject of a standard merge is skipped, but the branch names in it and its attribution are not
        first = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")[0]
        for name in merge_branches(first) or []:
            hits += check_field(f"{label}, merge subject branch", name, deny, False)
        if merge_branches(first) is not None and not exempt_attribution:
            hits += [(label, 1, None, why) for why in attribution_hits(first)]
    for no, line in numbered_lines(text, is_message):
        deny_hits = [n for n, rx in deny if rx.search(line)]
        attr = [] if exempt_attribution else attribution_hits(line)
        shown = None if deny_hits or attr else line
        for name, rx in GENERIC:
            if rx.search(line):
                hits.append((label, no, shown, name))
        for name in attr:
            hits.append((label, no, None, name))
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
    """[(full sha, message)] for the commits `git log` selects with the revision arguments `revs` (a list, e.g. ["A..B"] or
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
    return [(parts[i].strip(), parts[i + 1]) for i in range(0, len(parts), 2)]


def commit_field(sha, msg):
    """The field of one commit message: labeled with the short sha, exempt from the attribution patterns when the full sha is
    one of ATTRIBUTION_EXEMPT_SHAS."""
    return (f"commit {sha[:10]}", msg, True, sha in ATTRIBUTION_EXEMPT_SHAS)


def trim(line, n=200):
    line = line.strip()
    return line if len(line) <= n else line[: n - 1] + "…"


def run(fields, deny_raw, out=sys.stdout, source=None):
    """fields: [(label, text, is_message[, exempt_attribution])]. Prints the verdict; returns the exit code."""
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
    for label, text, is_message, *exempt in fields:
        hits += check_field(label, text, deny, is_message, bool(exempt and exempt[0]))
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
            fields.append(commit_field(sha, msg))
    if a.new_commits:
        # With a remote name: the commits that remote's tracking branches lack. A commit another remote has does not count as
        # published here. Without one (or a name git would read as a glob): every commit reachable from SHA, the safe direction.
        revs = [a.new_commits]
        if a.remote and not re.search(r"[*?\[\]]", a.remote):
            revs += ["--not", f"--remotes={a.remote}"]
        for sha, msg in commits_in(revs):
            fields.append(commit_field(sha, msg))
    if a.from_env:
        env = os.environ
        fields.append(("title", env.get("PR_TITLE", ""), False))
        fields.append(("body", env.get("PR_BODY", ""), False))
        fields.append(("branch", env.get("PR_BRANCH", ""), False))
        base, head = env.get("BASE_REV", ""), env.get("HEAD_SHA", "")
        if base and head:
            for sha, msg in commits_in([f"{base}..{head}"]):
                fields.append(commit_field(sha, msg))
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
