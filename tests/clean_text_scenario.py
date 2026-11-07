#!/usr/bin/env python3
"""Scenario test for tools/clean_text.py: commit messages, branch names, PR titles and PR bodies carry none of the instance owner's data.
Fixture data only: a throwaway git repository in a scratch folder (global git config off), the script run as a subprocess with an
environment built from scratch (so a CLEAN_TEXT_DENY of the host never reaches it), and its functions imported for the line rules.

Covers: clean text passes; a board id (all written forms, and a link to an items/<n> path) in a title, a body, a branch name, a
commit message and a message file fails, and the output names the field and the line; a deny pattern from CLEAN_TEXT_DENY fails by
its line number ("deny pattern 3", blank lines counted) and the log never echoes the pattern; case-insensitive matching; a bad deny
regex is a configuration error that names the line only; the Co-Authored-By and Claude-Session trailers, the Claude Code footer and
the session URL line are skipped, and text added to such a line is not; GitHub's own merge subjects are skipped on the first line only;
an empty or unset variable runs the generic patterns alone and says so in one line; --from-env checks the commits of base..head only
(an old commit before the base and a merge of the base branch into the PR bring nothing in) and the title, body and branch from the
environment; the local modes (--message-file, --branch, --title with --body-file, --commits).
Also: a deny hit prints the field and line number but never the line or the pattern; a bad or empty-matching deny pattern is a
configuration error by index only; the board-N form and a hostless /items/N path are no longer patterns; `git pull`'s merge subject
is skipped; a commit message holding \\x1e or \\x1f or bytes that are not UTF-8 is read whole; the deny list comes from
CLEAN_TEXT_DENY, else from $XDG_CONFIG_HOME/stackshot/clean-text-deny; the tracked git hooks (.githooks/commit-msg and
.githooks/pre-push, core.hooksPath) refuse a commit, a branch name and a push, in a repository and in a linked worktree.
Also: only a Claude or Anthropic Co-Authored-By trailer (with the Anthropic noreply address) is exempt, a person's is checked; a merge
subject's branch names are checked though the subject is skipped; board#N counts inside a word (_, x, dash) and
board-tmp-<name>#N takes digits and hyphens in the name; commit-msg reads "#" lines of a -m message but not git's "# On branch" status
lines or anything below the scissors line; pre-push checks the commits the remote being pushed to lacks (a commit only another remote
has is checked; a push by URL maps to its remote; an unknown URL checks all history).

    tests/run-suite clean_text   (or python3, stdlib only)   → exit 0 / 1"""
import importlib.util, os, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="cleantext-")
SCRIPT = os.path.join(STACK, "tools", "clean_text.py")
spec = importlib.util.spec_from_file_location("clean_text", SCRIPT); ct = importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

BASE_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "LANG": "C.UTF-8",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

def tool(args, deny=None, extra=None, cwd=None, stdin=None):
    env = dict(BASE_ENV)
    if deny is not None: env["CLEAN_TEXT_DENY"] = deny
    env.update(extra or {})
    r = subprocess.run([sys.executable, SCRIPT, *args], env=env, cwd=cwd or tmp, capture_output=True, input=stdin if stdin is not None else b"", timeout=60)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, env=BASE_ENV, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()

def write(name, text):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f: f.write(text)
    return p

CLEAN_BODY = "Wrap the handoff row on narrow screens.\n\nThe table no longer overflows below 400 px.\n"
AN = "noreply@" + "anthropic.com"        # built here so the tree holds no literal address
TRAILERS = (f"Co-Authored-By: Claude Opus 5.5 <{AN}>\n"
            "Claude-Session: https://claude.ai/code/session_01AbCdEf\n")
FOOTER = ("\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)\n\n"
          "https://claude.ai/code/session_01AbCdEf\n")

# ---- 1. clean text passes, in every mode
rc, out = tool(["--title", "Wrap the handoff row", "--body-file", write("body-ok.md", CLEAN_BODY), "--branch", "fix/handoff-row-wrap"])
check("clean title, body and branch pass", rc == 0 and "ok" in out, (rc, out))
rc, out = tool(["--message-file", write("msg-ok.txt", "Wrap the handoff row\n\n" + CLEAN_BODY + "\n" + TRAILERS)])
check("clean message with trailers passes", rc == 0, (rc, out))
rc, out = tool([])
check("no input is a usage error", rc == 2, (rc, out))

# ---- 2. generic patterns, each field
for label, args in (("title", ["--title", "Fix the row (board#9044)"]),
                    ("body", ["--body-file", write("body-bad.md", "Fine.\nSee board#9046 for why.\n")]),
                    ("branch", ["--branch", "fix/board#7-row"]),
                    ("message", ["--message-file", write("msg-bad.txt", "Subject\n\nrefs board-tmp-boxa#9\n")])):
    rc, out = tool(args)
    check(f"a board id in the {label} fails", rc == 1 and f"FAIL {label}" in out and "board item id" in out, (rc, out))
check("the offending line is printed", "See board#9046 for why." in tool(["--body-file", os.path.join(tmp, "body-bad.md")])[1])
for text, what in (("see board-tmp-boxa#2", "temporary id"), ("https://board.example.invalid/items/57", "items link"),
                   ("BOARD#9", "upper case"), ("Board#9 again", "mixed case"),
                   ("see _board#5", "an underscore before board"), ("see xboard#5", "a letter before board"),
                   ("Anchor the dashboard#2 element", "a word ending in board (the price of no left boundary)"),
                   ("see board-tmp-boxa-2#7", "a temporary id with a digit and a hyphen in its name"),
                   ("see board-tmp-a1#7", "a temporary id with a digit in its name")):
    rc, out = tool(["--title", text])
    check(f"generic: {what}", rc == 1, (rc, out))
for text, what in (("Add a board column to the dashboard", "the word board"), ("Order #5 of the items list", "# and items without the id shape"),
                    ("Raise the cap to 100 items/page", "items/ followed by a word"), ("Support board-style layout", "board- without digits"), ("branch board-7-ui", "board-N is no longer a pattern"), ("GET /items/5 returns the row", "a path without a host"), ("see /items/57", "a bare path"), ("API: GET https-less /items/5", "words around a path"), ("The board # 5 column", "a space after the board word")):
    rc, out = tool(["--title", text])
    check(f"generic does not misfire: {what}", rc == 0, (rc, out))

# ---- 3. the deny list from the environment
DENY = "zebra-host\\d+\n\nacme-[a-z]+\n^mulberry/"
rc, out = tool(["--title", "Move to zebra-host2 now"], deny=DENY)
check("a deny pattern fails", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--title", "Thanks to ACME-corp"], deny=DENY)
check("deny matching is case-insensitive and numbered by line (blank lines count)", rc == 1 and "deny pattern 3" in out, (rc, out))
rc, out = tool(["--branch", "mulberry/fix"], deny=DENY)
check("a deny pattern with an anchor", rc == 1 and "deny pattern 4" in out, (rc, out))
rc, out = tool(["--title", "Move to zebra-host2 now", "--branch", "ok/x"], deny=DENY)
for secret in ("zebra-host\\d+", "acme-[a-z]+", "^mulberry/"):
    check(f"the log does not echo the deny pattern {secret!r}", secret not in out, out)
check("the summary line counts the deny patterns", "3 deny pattern(s)" in out, out)
rc, out = tool(["--title", "Plain text"], deny=DENY)
check("clean text passes with a deny list", rc == 0 and "3 deny pattern(s)" in out, (rc, out))
rc, out = tool(["--title", "x"], deny="fine\nsecretfrag(unclosed[")
check("a bad deny regex is a configuration error naming only its line", rc == 2 and "deny pattern 2" in out, (rc, out))
check("no fragment of a bad deny regex appears in the output", not any(f in out for f in ("secretfrag", "unclosed", "(", "[", "unterminated", "missing")), out)
rc, out = tool(["--title", "x"], deny="fine\n" + "(" * 5000 + "a" + ")" * 5000)
check("a deeply nested deny regex is a configuration error, not a crash", rc == 2 and "Traceback" not in out and "deny pattern 2" in out, (rc, out))
for pat, what in (("a*", "a star"), ("x?", "an optional"), ("(?:)", "an empty group"), ("^", "an anchor alone")):
    rc, out = tool(["--title", "anything"], deny=f"fine\n{pat}")
    check(f"a deny pattern that matches the empty string is a configuration error by index ({what})", rc == 2 and "deny pattern 2 matches the empty string" in out and pat not in out.replace("pattern 2", ""), (rc, out))
rc, out = tool(["--title", "Move to zebra-host2 now"], deny="zebra-host\\d+")
check("a deny hit does not need the generic patterns", rc == 1 and "deny pattern 1" in out and "board" not in out.split("\n")[1].lower(), (rc, out))
check("a deny hit names the field and the line number", "FAIL title, line 1: deny pattern 1" in out, out)
check("a deny hit never prints the line", "zebra-host2" not in out and "Move to" not in out, out)
rc, out = tool(["--body-file", write("deny-body.md", "ok\nfine\nMove to zebra-host2 now\n")], deny="zebra-host\\d+")
check("a deny hit in a body names line 3 and prints no text", rc == 1 and "FAIL body, line 3: deny pattern 1" in out and "zebra" not in out and "Move to" not in out, (rc, out))
rc, out = tool(["--title", "Move zebra-host2 for board#5"], deny="zebra-host\\d+")
check("a generic hit on a line a deny pattern also hit hides the line text", rc == 1 and "board item id" in out and "deny pattern 1" in out and "zebra" not in out and "Move" not in out, (rc, out))
rc, out = tool(["--title", "Raise the board#5 limit"])
check("a generic hit still prints its line", rc == 1 and "Raise the board#5 limit" in out, (rc, out))

# ---- 4. empty or unset variable: generic only, said in one line
for how, deny in (("unset", None), ("empty", ""), ("blank lines", "\n  \n")):
    rc, out = tool(["--title", "Plain text zebra-host2"], deny=deny)
    one = [l for l in out.splitlines() if "CLEAN_TEXT_DENY" in l]
    check(f"{how} variable: passes on generic patterns and says so in one line", rc == 0 and len(one) == 1 and "generic" in one[0] and "not available" in one[0], (rc, out))
    rc, out = tool(["--title", "board#5"], deny=deny)
    check(f"{how} variable: the generic patterns still fail", rc == 1, (rc, out))

# ---- 5. allowed lines are skipped, anything added to them is not
msg = "Subject\n\n" + CLEAN_BODY + "\n" + TRAILERS + FOOTER
rc, out = tool(["--message-file", write("m1.txt", msg)], deny="session_01AbCdEf\nnoreply\nclaude")
check("trailers, footer and session URL line are exempt from the deny list (even for a deny list that would hit them)", rc == 0, (rc, out))
rc, out = tool(["--body-file", write("b1.md", CLEAN_BODY + "\n" + FOOTER)], deny="claude")
check("a PR body ends with the footer and the session URL", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("m2.txt", "S\n\nClaude-Session: https://claude.ai/code/session_01AbCdEf board#5\n")])
check("text added to a trailer line is checked", rc == 1, (rc, out))
rc, out = tool(["--message-file", write("m3.txt", "S\n\nCo-Authored-By: Someone board#5 <a@example.invalid>\n")])
check("a board id in a Co-Authored-By name is checked", rc == 1, (rc, out))
rc, out = tool(["--message-file", write("m3b.txt", f"S\n\nCo-Authored-By: Claude board#5 <{AN}>\n")])
check("the generic patterns still read a Claude trailer", rc == 1 and "board item id" in out, (rc, out))
# only the Claude/Anthropic trailer is exempt: a person's trailer, or a Claude name with another address, is ordinary text
rc, out = tool(["--message-file", write("m3c.txt", "S\n\nCo-Authored-By: Jane Doe <jane@example.invalid>\n")], deny="jane")
check("a person's Co-Authored-By trailer is checked against the deny list", rc == 1 and "line 3: deny pattern 1" in out and "jane" not in out.lower(), (rc, out))
rc, out = tool(["--message-file", write("m3d.txt", "S\n\nCo-Authored-By: Jane Doe <jane@example.invalid>\n")], deny="example\\.invalid")
check("a private address in a Co-Authored-By trailer is checked", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--message-file", write("m3e.txt", "S\n\nCo-Authored-By: Claude <helper@example.invalid>\n")], deny="example\\.invalid")
check("a Claude name with another address is not exempt", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--message-file", write("m3f.txt", f"S\n\nCo-Authored-By: Claude Sonnet 5.5 <{AN}>\nCo-Authored-By: Jane Doe <jane@example.invalid>\n")], deny="jane")
check("a Claude trailer beside a person's: only the person's line is checked", rc == 1 and "line 4: deny pattern 1" in out and "line 3" not in out, (rc, out))
rc, out = tool(["--message-file", write("m3g.txt", f"S\n\nco-authored-by: claude opus 5.5 <{AN.upper()}>\n")], deny="claude|anthropic|noreply")
check("the Claude trailer is matched without regard to case", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("m3h.txt", f"S\n\nCo-Authored-By: Claude <{AN}> and Jane Doe <jane@example.invalid>\n")], deny="jane")
check("a Claude trailer with a second person on the line is checked", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--body-file", write("b2.md", "Generated with [Claude Code](https://claude.com/claude-code) for board#5\n")])
check("text added to the footer line is checked", rc == 1, (rc, out))
rc, out = tool(["--body-file", write("b3.md", "see https://claude.ai/code/session_01AbCdEf and board#5\n")])
check("a session URL inside other text is checked", rc == 1, (rc, out))
rc, out = tool(["--message-file", write("m4.txt", "Fix the row\n\nSigned-off-by: A <a@example.invalid>\nboard#7\n")])
check("other trailers are not skipped", rc == 1, (rc, out))

# ---- 6. GitHub's merge subjects
for subj in ("Merge branch 'main' into fix/handoff-row-wrap", "Merge pull request #13 from some-owner/fix/handoff-row-wrap",
             "Merge remote-tracking branch 'origin/main' into fix/x",
             "Merge branch 'feature' of https://example.invalid/r.git into fix/x", "Merge branch 'main' of github.com:o/r",
             "Merge branch 'handoff-work' of https://example.invalid/some-owner/r into fix/handoff"):
    rc, out = tool(["--message-file", write("mg.txt", subj + "\n")], deny="some-owner|example|zzz")      # owner and URL are skipped; branch names are read
    check(f"merge subject skipped (owner and URL not read): {subj[:45]}", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("mg4.txt", "Merge branch 'feature' of https://example.invalid/r.git into fix/x\n\nzebra-host9 board#5\n")], deny="example")
check("a pull-merge message's body is still checked", rc == 1 and "line 3" in out, (rc, out))
# the subject is skipped, but the branch names in it are checked as branch names
for subj, what in (("Merge branch 'board#9045-thing' of https://example.invalid/r.git into fix/x", "the merged-in branch of a pull"),
                   ("Merge branch 'main' of https://example.invalid/r.git into fix/board#3", "the into-branch of a pull"),
                   ("Merge branch 'main' into fix/board#3", "the into-branch of a merge of main"),
                   ("Merge remote-tracking branch 'origin/main' into fix/board-tmp-boxa#4", "the into-branch of a remote-tracking merge"),
                   ("Merge pull request #13 from some-owner/fix/board#6-row", "the head branch of a pull request merge")):
    rc, out = tool(["--message-file", write("mgb.txt", subj + "\n")])
    check(f"merge subject: a board id in {what} fails", rc == 1 and "merge subject branch" in out and "board item id" in out, (rc, out))
rc, out = tool(["--message-file", write("mgb2.txt", "Merge branch 'mulberry-work' of https://example.invalid/r.git into fix/x\n")], deny="mulberry")
check("merge subject: a deny word in the merged-in branch fails, by pattern number and without text", rc == 1 and "FAIL message mgb2.txt, merge subject branch, line 1: deny pattern 1" in out and "mulberry" not in out, (rc, out))
rc, out = tool(["--message-file", write("mgb3.txt", "Merge branch 'main' into fix/mulberry-row\n")], deny="mulberry")
check("merge subject: a deny word in the into-branch fails", rc == 1 and "merge subject branch" in out and "mulberry" not in out, (rc, out))
rc, out = tool(["--message-file", write("mgb4.txt", "Merge pull request #13 from mulberry/fix/row\n")], deny="mulberry")
check("merge subject: the owner of a pull request merge is still skipped", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("mgb5.txt", "Merge branch 'main' of github.com:mulberry/r\n")], deny="mulberry")
check("merge subject: a pull from main with no into-branch has no branch field to read", rc == 0, (rc, out))
check("merge_branches names the branches of each subject form",
      ct.merge_branches("Merge branch 'a/b' of https://example.invalid/r.git into c/d") == ["a/b", "c/d"]
      and ct.merge_branches("Merge branch 'main' into c/d") == ["c/d"]
      and ct.merge_branches("Merge pull request #3 from o/c/d") == ["c/d"]
      and ct.merge_branches("Merge branch 'main' of u") == ["main"]
      and ct.merge_branches("Fix the row") is None)
rc, out = tool(["--message-file", write("mg5.txt", "Merge branch 'feature' of https://example.invalid/r.git into fix/x and board#5\n")])
check("a pull-merge subject with extra text is not skipped", rc == 1, (rc, out))
rc, out = tool(["--message-file", write("mg2.txt", "Merge branch 'main' into fix/x\n\nfix board#5\n")])
check("a merge message's body is still checked", rc == 1, (rc, out))
rc, out = tool(["--message-file", write("mg3.txt", "Merge branch 'board#9045-thing' into fix/x\n")])
check("a merge of another branch is not skipped", rc == 1, (rc, out))
rc, out = tool(["--title", "Merge branch 'main' into fix/handoff"], deny="handoff")
check("the merge subject skip is for commit messages, not a title", rc == 1, (rc, out))

# ---- 7. a PR in a real repository: --from-env and --commits
repo = os.path.join(tmp, "repo"); os.makedirs(repo)
git(repo, "init", "-q", "-b", "main")
def commit(msg, name):
    with open(os.path.join(repo, name), "w") as f: f.write(msg)
    git(repo, "add", name); git(repo, "commit", "-q", "-m", msg)
commit("An old commit before the rule", "a.txt")          # in main's history: never checked
git(repo, "checkout", "-q", "-b", "fix/handoff-row-wrap")
commit("Wrap the handoff row\n\n" + TRAILERS.strip(), "b.txt")
commit("Cover the narrow case", "c.txt")
git(repo, "checkout", "-q", "main")
commit("Another change on main", "d.txt")                  # main moved on after the branch was made
git(repo, "checkout", "-q", "fix/handoff-row-wrap")
git(repo, "merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into fix/handoff-row-wrap")
head = git(repo, "rev-parse", "HEAD")
ENV_OK = {"PR_TITLE": "Wrap the handoff row", "PR_BODY": CLEAN_BODY + "\n" + FOOTER, "PR_BRANCH": "fix/handoff-row-wrap",
          "BASE_REV": "main", "HEAD_SHA": head}
rc, out = tool(["--from-env"], extra=ENV_OK, cwd=repo)
check("--from-env: a clean PR passes; old history and a merge of the base branch bring nothing in", rc == 0 and "4 field(s)" not in out and "ok" in out, (rc, out))
check("--from-env: title, body, branch and the PR's own commits were checked (3 + 3 commits)", "6 field(s)" in out, out)
for key, val, label in (("PR_TITLE", "Fix it (board#8)", "title"), ("PR_BODY", "Fine\nboard-tmp-x#3\n", "body"), ("PR_BRANCH", "fix/board#9-row", "branch")):
    rc, out = tool(["--from-env"], extra={**ENV_OK, key: val}, cwd=repo)
    check(f"--from-env: a bad {label} fails", rc == 1 and f"FAIL {label}" in out, (rc, out))
rc, out = tool(["--from-env"], extra={**ENV_OK, "PR_BODY": ""}, cwd=repo)
check("--from-env: an empty body is fine", rc == 0, (rc, out))
rc, out = tool(["--from-env"], extra={k: v for k, v in ENV_OK.items() if k != "PR_BODY"}, cwd=repo)
check("--from-env: an unset body is fine", rc == 0, (rc, out))
rc, out = tool(["--from-env"], extra={k: v for k, v in ENV_OK.items() if k != "BASE_REV"}, cwd=repo)
check("--from-env without a base is a call error", rc == 2, (rc, out))
commit("Final touch\n\nrefs board#9012", "e.txt")
rc, out = tool(["--from-env"], extra={**ENV_OK, "HEAD_SHA": git(repo, "rev-parse", "HEAD")}, cwd=repo)
short = git(repo, "rev-parse", "--short=10", "HEAD")
check("--from-env: a board id in a commit message fails and names the commit", rc == 1 and f"FAIL commit {short}" in out and "refs board#9012" in out, (rc, out))
rc, out = tool(["--from-env"], deny="cover the narrow", extra=ENV_OK, cwd=repo)
check("--from-env: a deny hit in an earlier commit is found", rc == 1 and "FAIL commit" in out and "deny pattern 1" in out and "cover the narrow" not in out, (rc, out))
rc, out = tool(["--commits", "main..HEAD"], cwd=repo)
check("--commits checks a range", rc == 1 and "FAIL commit" in out, (rc, out))
rc, out = tool(["--commits", "nope..HEAD"], cwd=repo)
check("--commits with a bad range is a call error", rc == 2, (rc, out))

# ---- 8. the line rules, imported
cl = ct.classified_lines("a\n" + TRAILERS + "b\n" + FOOTER)
check("classified_lines marks the allowed lines", [l for _, l, ok in cl if ok] == [f"Co-Authored-By: Claude Opus 5.5 <{AN}>", "Claude-Session: https://claude.ai/code/session_01AbCdEf", "\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)", "https://claude.ai/code/session_01AbCdEf"] and [l for _, l, ok in cl if not ok][:2] == ["a", "b"], cl)
check("classified_lines numbers the lines from 1", [n for n, _, _ in cl][:3] == [1, 2, 3], cl)
dl, bad = ct.load_deny("a\n\n(")
check("load_deny numbers by line and keeps no text of a bad pattern", [n for n, _ in dl] == [1] and len(bad) == 1 and bad[0][0] == 3 and bad[0][1] == "is not a valid regex", (dl, bad))
dl, bad = ct.load_deny("ok\nx*\n(?:)\nb")
check("load_deny reports a pattern matching the empty string by number", [n for n, _ in dl] == [1, 4] and bad == [(2, "matches the empty string"), (3, "matches the empty string")], (dl, bad))
dl, bad = ct.load_deny("[" * 3 + "\n" + "(" * 20000)
check("load_deny survives a regex the compiler cannot take", dl == [] and [n for n, _ in bad] == [1, 2], (dl, bad))

# ---- 9. a message the old record splitting could be fooled by, and a message that is not UTF-8
repo2 = os.path.join(tmp, "repo2"); os.makedirs(repo2)
git(repo2, "init", "-q", "-b", "main")
def commit2(msg_bytes, name):
    with open(os.path.join(repo2, name), "w") as f: f.write(name)
    mf = os.path.join(tmp, "cm-" + name)
    with open(mf, "wb") as f: f.write(msg_bytes)
    git(repo2, "add", name); git(repo2, "commit", "-q", "-F", mf)
commit2(b"Base commit\n", "base.txt")
base2 = git(repo2, "rev-parse", "HEAD")
commit2(b"fine subject\x1ezebra-host9 hidden after a record separator\n", "rs.txt")
commit2(b"another\x1fzebra-host8 after a unit separator\n", "us.txt")
rc, out = tool(["--commits", f"{base2}..HEAD"], deny=DENY, cwd=repo2)
check("a record separator (\\x1e) in a message does not hide the rest of the message", rc == 1 and "line 1: deny pattern 1" in out and out.count("FAIL commit") == 2, (rc, out))
commit2(b"Caf\xe9 caf\xe9 \xff\xfe not utf-8\n", "latin.txt")
rc, out = tool(["--commits", f"{base2}..HEAD"], deny=DENY, cwd=repo2)
check("a message that is not UTF-8 does not crash the check", "Traceback" not in out and rc == 1 and out.count("FAIL commit") == 2, (rc, out))
commit2(b"\xff\xfe zebra-host7 in a non-UTF-8 message\n", "latin2.txt")
rc, out = tool(["--commits", f"{base2}..HEAD"], deny=DENY, cwd=repo2)
check("a deny word in a non-UTF-8 message is found", "Traceback" not in out and rc == 1 and out.count("FAIL commit") == 3, (rc, out))
rc, out = tool(["--commits", f"{base2}..{base2}"], deny=DENY, cwd=repo2)
check("a range with no commit is clean", rc == 0, (rc, out))
mfile = write("nonutf.txt", "")
with open(mfile, "wb") as f: f.write(b"Subject \xff\xfe\n\nbody \xe9\n")
rc, out = tool(["--message-file", mfile], deny=DENY)
check("a non-UTF-8 message file is read, not a crash", rc == 0 and "Traceback" not in out, (rc, out))
with open(mfile, "wb") as f: f.write(b"Subject \xff\xfe\n\nzebra-host3 \xe9\n")
rc, out = tool(["--message-file", mfile], deny=DENY)
check("a deny word in a non-UTF-8 message file is found", rc == 1 and "line 3: deny pattern 1" in out and "Traceback" not in out, (rc, out))
rc, out = tool(["--message-stdin"], deny=DENY, stdin=b"Subject\n\nzebra-host3 \xff\n")
check("a message on standard input is checked", rc == 1 and "FAIL message, line 3: deny pattern 1" in out, (rc, out))

# ---- 10. where the deny list comes from: the variable, else the per-user file, never the tree
xdg = os.path.join(tmp, "xdg"); os.makedirs(os.path.join(xdg, "stackshot"))
denyfile = os.path.join(xdg, "stackshot", "clean-text-deny")
with open(denyfile, "w") as f: f.write("\nzebra-host\\d+\n\n\nacme-[a-z]+\n")
rc, out = tool(["--title", "Move to zebra-host2"], extra={"XDG_CONFIG_HOME": xdg})
check("the deny file is read when the variable is unset (numbered by its lines)", rc == 1 and "deny pattern 2" in out and "2 deny pattern(s)" in out and "zebra" not in out, (rc, out))
rc, out = tool(["--title", "Move to zebra-host2"], deny="", extra={"XDG_CONFIG_HOME": xdg})
check("the deny file is read when the variable is empty", rc == 1 and "deny pattern 2" in out, (rc, out))
rc, out = tool(["--title", "Move to zebra-host2 and mulberry"], deny="mulberry", extra={"XDG_CONFIG_HOME": xdg})
check("the variable wins over the deny file", rc == 1 and "deny pattern 1" in out and "deny pattern 2" not in out, (rc, out))
rc, out = tool(["--title", "Plain"], extra={"XDG_CONFIG_HOME": xdg})
check("a clean text passes with the deny file", rc == 0 and "2 deny pattern(s)" in out, (rc, out))
home2 = os.path.join(tmp, "home2"); os.makedirs(os.path.join(home2, ".config", "stackshot"))
with open(os.path.join(home2, ".config", "stackshot", "clean-text-deny"), "w") as f: f.write("acme-[a-z]+\n")
rc, out = tool(["--title", "Thanks to acme-corp"], extra={"HOME": home2})
check("with no XDG_CONFIG_HOME the file is under $HOME/.config", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--title", "Thanks to acme-corp"], extra={"HOME": home2, "XDG_CONFIG_HOME": "relative/dir"})
check("a relative XDG_CONFIG_HOME is ignored", rc == 1 and "deny pattern 1" in out, (rc, out))
rc, out = tool(["--title", "Plain"], extra={"XDG_CONFIG_HOME": os.path.join(tmp, "no-such-dir")})
check("no variable and no file: generic patterns only, said once, not a failure", rc == 0 and "not available" in out, (rc, out))
with open(denyfile, "w") as f: f.write("fine\nsecretfrag(unclosed[\n")
rc, out = tool(["--title", "x"], extra={"XDG_CONFIG_HOME": xdg})
check("a bad pattern in the deny file is a configuration error naming the file's line", rc == 2 and "deny pattern 2" in out and "secretfrag" not in out and "unclosed" not in out, (rc, out))

# ---- 11. the tracked git hooks (core.hooksPath = .githooks), in a repository and in a linked worktree
import shutil
HOOKS_SRC = os.path.join(STACK, ".githooks")
check("the hooks are tracked and executable", all(os.access(os.path.join(HOOKS_SRC, h), os.X_OK) for h in ("commit-msg", "pre-push")), os.listdir(HOOKS_SRC) if os.path.isdir(HOOKS_SRC) else None)
HENV = {**BASE_ENV, "XDG_CONFIG_HOME": os.path.join(tmp, "hk-xdg")}   # no deny file here: generic patterns only, unless a test writes one
def hgit(repo, *args, stdin=None, env=None):
    r = subprocess.run(["git", *args], cwd=repo, env=env or HENV, capture_output=True, input=stdin, timeout=60)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
def hrun(repo, hook, lines, env=None, args=("origin", "none")):
    r = subprocess.run([os.path.join(repo, ".githooks", hook), *args], cwd=repo, env=env or HENV, capture_output=True,
                       input=("".join(l + "\n" for l in lines)).encode(), timeout=60)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
ZERO = "0" * 40

hk = os.path.join(tmp, "hk"); os.makedirs(hk)
git(hk, "init", "-q", "-b", "main")
os.makedirs(os.path.join(hk, "tools"))
shutil.copy(SCRIPT, os.path.join(hk, "tools", "clean_text.py"))
shutil.copytree(HOOKS_SRC, os.path.join(hk, ".githooks"))
git(hk, "config", "core.hooksPath", ".githooks")
git(hk, "add", "-A"); git(hk, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "Add the hooks")
def count(repo): return int(git(repo, "rev-list", "--count", "HEAD"))
def hcommit(repo, name, msg, *flags):
    with open(os.path.join(repo, name), "w") as f: f.write(name)
    hgit(repo, "add", name)
    return hgit(repo, "commit", "-q", *flags, "-m", msg)
n0 = count(hk)
rc, out = hcommit(hk, "a.txt", "Fix the row (board#5)")
check("commit-msg: a message with a board id is refused and nothing is committed", rc != 0 and "board item id" in out and "line 1" in out and count(hk) == n0, (rc, out))
rc, out = hcommit(hk, "a.txt", "Fix the row\n\nSee https://board.example.invalid/items/12 for why.")
check("commit-msg: a link to an items path is refused", rc != 0 and count(hk) == n0, (rc, out))
rc, out = hcommit(hk, "a.txt", "Fix the row\n\n" + TRAILERS.strip())
check("commit-msg: a clean message with trailers passes", rc == 0 and count(hk) == n0 + 1 and "not available" in out, (rc, out))
rc, out = hcommit(hk, "b.txt", "Fix again (board#6)", "--no-verify")
check("commit-msg: --no-verify skips it", rc == 0 and count(hk) == n0 + 2, (rc, out))
hgit(hk, "reset", "-q", "--hard", "HEAD~1")
# "#" lines: `git commit -m` keeps them in the message, so they are checked
n2 = count(hk)
rc, out = hcommit(hk, "h.txt", "Fix the row\n\n# see board#5")
check("commit-msg: a '#' line of a -m message is checked (it stays in the message)", rc != 0 and "board item id" in out and count(hk) == n2, (rc, out))
rc, out = hcommit(hk, "h.txt", "# board#5 first")
check("commit-msg: a '#' subject is checked", rc != 0 and count(hk) == n2, (rc, out))
rc, out = hcommit(hk, "h.txt", "Fix the row\n\n#7 is the row number")
check("commit-msg: a '#' line without a board id passes", rc == 0 and count(hk) == n2 + 1, (rc, out))
hgit(hk, "reset", "-q", "--hard", "HEAD~1")
# the editor template: git's own status lines ("# On branch X") are not message text, but any other "#" line is
hgit(hk, "checkout", "-q", "-b", "fix/board#3-x")
with open(os.path.join(tmp, "tmpl.txt"), "w") as f: f.write("Fix the row\n")
with open(os.path.join(hk, "c.txt"), "w") as f: f.write("c")
hgit(hk, "add", "c.txt")
editor = write("fake-editor.sh", '#!/bin/sh\ncat "$1"\nprintf "\\nAn edit.\\n" >> "$1"\n')    # prints the file it was given, then edits it
os.chmod(editor, 0o755)
cat_env = {**HENV, "GIT_EDITOR": editor}
rc, out = hgit(hk, "commit", "-q", "-t", os.path.join(tmp, "tmpl.txt"), env=cat_env)
check("commit-msg: git's '# On branch X' line in the editor template is not checked (and the line was really there)",
      rc == 0 and "# On branch fix/board#3-x" in out, (rc, out))
hgit(hk, "reset", "-q", "--hard", "HEAD~1")
with open(os.path.join(tmp, "tmpl2.txt"), "w") as f: f.write("Fix the row\n\n# see board#5\n")
with open(os.path.join(hk, "c.txt"), "w") as f: f.write("c")
hgit(hk, "add", "c.txt")
rc, out = hgit(hk, "commit", "-q", "-t", os.path.join(tmp, "tmpl2.txt"), env=cat_env)
check("commit-msg: another '#' line in the editor template is checked", rc != 0 and "board item id" in out, (rc, out))
hgit(hk, "reset", "-q", "--hard", "HEAD")
hgit(hk, "checkout", "-q", "main"); hgit(hk, "branch", "-q", "-D", "fix/board#3-x")
# direct runs of the hook on a crafted message file: the status lines and everything below the scissors line are not message text
def hmsg(text):
    p = os.path.join(tmp, "COMMIT_EDITMSG")
    with open(p, "w", encoding="utf-8") as f: f.write(text)
    r = subprocess.run([os.path.join(hk, ".githooks", "commit-msg"), p], cwd=hk, env=HENV, capture_output=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
SCISSORS = "# ------------------------ >8 ------------------------"
DIFF = "diff --git a/x b/x\n+++ b/x\n+the row for board#5\n"
rc, out = hmsg(f"Fix the row\n\n{SCISSORS}\n# Do not modify or remove the line above.\n# Everything below it will be ignored.\n{DIFF}")
check("commit-msg: a diff below the scissors line is not checked", rc == 0, (rc, out))
rc, out = hmsg(f"Fix the row\n\nthe row for board#5\n{SCISSORS}\n{DIFF}")
check("commit-msg: the same text above the scissors line is checked", rc != 0 and "line 3" in out, (rc, out))
rc, out = hmsg(f"Fix the row\n\n# On branch fix/board#3\n# Your branch is ahead of 'origin/fix/board#3' by 1 commit.\n# HEAD detached at fix/board#3\n")
check("commit-msg: git's own branch status lines are not checked", rc == 0, (rc, out))
rc, out = hmsg(f"Fix the row\n\n# On the branch fix/board#3 we tried it\n")
check("commit-msg: a '#' line that only resembles a status line is checked", rc != 0, (rc, out))
rc, out = hmsg(f"Fix the row\n\n# ----- >8 ----- board#5\n")
check("commit-msg: a '#' line that only resembles the scissors line is checked", rc != 0, (rc, out))
# the deny list from the per-user file
os.makedirs(os.path.join(tmp, "hk-xdg", "stackshot"))
with open(os.path.join(tmp, "hk-xdg", "stackshot", "clean-text-deny"), "w") as f: f.write("zebra-host\\d+\n")
n1 = count(hk)
rc, out = hcommit(hk, "d.txt", "Move to zebra-host4")
check("commit-msg: the deny file is read; the hit names the pattern's line, not its text", rc != 0 and "deny pattern 1" in out and "zebra" not in out and count(hk) == n1, (rc, out))
rc, out = hcommit(hk, "d.txt", "Move the host")
check("commit-msg: a clean message passes with the deny file and says so", rc == 0 and "1 deny pattern(s)" in out, (rc, out))
rc, out = hgit(hk, "commit", "-q", "--amend", "-m", "Move to zebra-host4")
check("commit-msg: an amend is checked too", rc != 0, (rc, out))
hgit(hk, "reset", "-q", "--hard", "HEAD")

# pre-push, driven directly with crafted stdin
tip = git(hk, "rev-parse", "HEAD"); parent = git(hk, "rev-parse", "HEAD~1")
rc, out = hrun(hk, "pre-push", [f"refs/heads/fix/ok {tip} refs/heads/fix/ok {ZERO}"])
check("pre-push: a clean new branch passes", rc == 0, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/main {tip} refs/heads/fix/board#3 {ZERO}"])
check("pre-push: a branch named for a board id is refused", rc == 1 and "FAIL branch" in out and "board item id" in out and "refused" in out, (rc, out))
hgit(hk, "branch", "-q", "dirty", parent)
hgit(hk, "checkout", "-q", "dirty")
rc, out = hcommit(hk, "e.txt", "Dirty commit for board#9", "--no-verify")
check("(setup) a dirty commit made with --no-verify", rc == 0, (rc, out))
dirty = git(hk, "rev-parse", "HEAD")
rc, out = hrun(hk, "pre-push", [f"refs/heads/dirty {dirty} refs/heads/dirty {ZERO}"])
check("pre-push: a new branch holding a dirty commit is refused, naming the commit", rc == 1 and f"FAIL commit {dirty[:10]}" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/dirty {dirty} refs/heads/dirty {parent}"])
check("pre-push: an update with a dirty commit in remote..local is refused", rc == 1 and f"FAIL commit {dirty[:10]}" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/dirty {parent} refs/heads/dirty {dirty}"])
check("pre-push: the commit the remote already has is not read again", rc == 0, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/dirty {dirty} refs/heads/dirty {'1' * 40}"])
check("pre-push: a remote tip this clone does not have falls back to the commits no remote branch has", rc == 1 and f"FAIL commit {dirty[:10]}" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"(delete) {ZERO} refs/heads/fix/board#3 {dirty}"])
check("pre-push: a delete is skipped", rc == 0 and "FAIL" not in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/main {tip} refs/heads/fix/ok {ZERO}", f"refs/heads/dirty {dirty} refs/heads/dirty {ZERO}"])
check("pre-push: every ref is checked, one bad ref refuses the push", rc == 1, (rc, out))
rc, out = hrun(hk, "pre-push", [])
check("pre-push: no refs, nothing to check", rc == 0, (rc, out))
hgit(hk, "checkout", "-q", "main")

# pre-push through a real push to a local bare repository
bare = os.path.join(tmp, "remote.git"); os.makedirs(bare)
git(bare, "init", "-q", "--bare", "-b", "main")
git(hk, "remote", "add", "origin", bare)
rc, out = hgit(hk, "push", "-q", "origin", "main")
check("a real push of clean history passes", rc == 0 and "main" in git(bare, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", "origin", "dirty")
check("a real push of a dirty commit is refused and the remote has no such branch", rc != 0 and "FAIL commit" in out and "dirty" not in git(bare, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", "--no-verify", "origin", "dirty")
check("a real push with --no-verify goes through (CI is the backstop)", rc == 0 and "dirty" in git(bare, "branch"), (rc, out))
hgit(hk, "checkout", "-q", "-b", "fix/next", "dirty")          # the dirty commit is on the remote now: only new commits are read
rc, out = hcommit(hk, "f.txt", "A clean follow-up")
rc, out = hgit(hk, "push", "-q", "origin", "fix/next")
check("a real push reads only the commits the remote does not have", rc == 0 and "fix/next" in git(bare, "branch"), (rc, out))
hgit(hk, "checkout", "-q", "-b", "fix/board#2-row", "main")
rc, out = hcommit(hk, "g.txt", "Another clean commit")
rc, out = hgit(hk, "push", "-q", "origin", "fix/board#2-row")
check("a real push of a branch named for a board id is refused", rc != 0 and "FAIL branch" in out and "fix/board#2-row" not in git(bare, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", "origin", ":fix/next")
check("a real branch delete is not refused", rc == 0 and "fix/next" not in git(bare, "branch"), (rc, out))

# the push is checked against the remote it goes to: the dirty commit is on origin's tracking branches, which says nothing about
# a second remote (here "public"), nor about a URL no remote has
bare2 = os.path.join(tmp, "public.git"); os.makedirs(bare2)
git(bare2, "init", "-q", "--bare", "-b", "main")
bare3 = os.path.join(tmp, "other.git"); os.makedirs(bare3)
git(bare3, "init", "-q", "--bare", "-b", "main")
git(hk, "remote", "add", "public", bare2)
check("(setup) origin has the dirty commit on a tracking branch", dirty in git(hk, "rev-list", "--remotes=origin"), git(hk, "branch", "-r"))
hgit(hk, "checkout", "-q", "fix/next")                        # holds the dirty commit and a clean follow-up
rc, out = hgit(hk, "push", "-q", "public", "fix/next")
check("scope: a new branch pushed to a second remote is checked although origin has the dirty commit", rc != 0 and f"FAIL commit {dirty[:10]}" in out and "fix/next" not in git(bare2, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", "origin", "fix/next:refs/heads/fix/scoped")
check("scope: the same new branch pushed to origin passes (origin has those commits)", rc == 0 and "fix/scoped" in git(bare, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", bare, "fix/next:refs/heads/fix/by-url")
check("scope: a push by the URL of origin counts as a push to origin", rc == 0 and "fix/by-url" in git(bare, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", bare2, "fix/next:refs/heads/fix/by-url")
check("scope: a push by the URL of the second remote is checked as a push to it", rc != 0 and f"FAIL commit {dirty[:10]}" in out and "fix/by-url" not in git(bare2, "branch"), (rc, out))
rc, out = hgit(hk, "push", "-q", bare3, "fix/next")
check("scope: a push by a URL no remote has checks every commit reachable (more, not less)", rc != 0 and f"FAIL commit {dirty[:10]}" in out and "fix/next" not in git(bare3, "branch"), (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/fix/next {git(hk, 'rev-parse', 'fix/next')} refs/heads/fix/next {ZERO}"], args=("public", "none"))
check("scope: the hook run for the second remote refuses", rc == 1 and "FAIL commit" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/fix/next {git(hk, 'rev-parse', 'fix/next')} refs/heads/fix/next {ZERO}"], args=("origin", "none"))
check("scope: the hook run for origin passes", rc == 0, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/fix/next {git(hk, 'rev-parse', 'fix/next')} refs/heads/fix/next {ZERO}"], args=("nowhere", "none"))
check("scope: the hook run for a name and URL no remote has checks everything", rc == 1 and "FAIL commit" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/fix/next {git(hk, 'rev-parse', 'fix/next')} refs/heads/fix/next {ZERO}"], args=("nowhere", bare))
check("scope: a URL argument that is origin's URL is taken as origin", rc == 0, (rc, out))
rc, out = tool(["--new-commits", dirty], cwd=hk)
check("--new-commits without --remote checks every commit reachable from the sha", rc == 1 and f"FAIL commit {dirty[:10]}" in out, (rc, out))
rc, out = tool(["--new-commits", dirty, "--remote", "origin"], cwd=hk)
check("--new-commits --remote skips what that remote's tracking branches have", rc == 0, (rc, out))
rc, out = tool(["--new-commits", dirty, "--remote", "o*"], cwd=hk)
check("--new-commits with a glob in the remote name checks everything (the scope is dropped)", rc == 1, (rc, out))
hgit(hk, "checkout", "-q", "main")

# a linked worktree finds the repository's own root, and the hooks run there
wt = os.path.join(tmp, "hk-wt")
git(hk, "worktree", "add", "-q", "-b", "fix/in-worktree", wt, "main")
rc, out = hcommit(wt, "w.txt", "Worktree commit (board#7)")
check("a linked worktree: commit-msg refuses a board id", rc != 0 and "board item id" in out, (rc, out))
rc, out = hcommit(wt, "w.txt", "Worktree commit")
check("a linked worktree: a clean commit passes", rc == 0, (rc, out))
rc, out = hgit(wt, "push", "-q", "origin", "fix/in-worktree:refs/heads/fix/board#8")
check("a linked worktree: pre-push refuses a board-id branch name", rc != 0 and "FAIL branch" in out, (rc, out))
rc, out = hgit(wt, "push", "-q", "origin", "fix/in-worktree")
check("a linked worktree: pre-push passes a clean push", rc == 0, (rc, out))

if fails: print(f"{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: clean_text, {len(ran)} checks"); sys.exit(0)
