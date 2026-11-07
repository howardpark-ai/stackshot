#!/usr/bin/env python3
"""Scenario test for tools/clean_text.py: commit messages, branch names, PR titles and PR bodies carry none of the instance owner's data.
Fixture data only: a throwaway git repository in a scratch folder (global git config off), the script run as a subprocess with an
environment built from scratch (so a CLEAN_TEXT_DENY of the host never reaches it), and its functions imported for the line rules.

Covers: clean text passes; a board id (all written forms, and a link to an items/<n> path) in a title, a body, a branch name, a
commit message and a message file fails, and the output names the field and the line; a deny pattern from CLEAN_TEXT_DENY fails by
its line number ("deny pattern 3", blank lines counted) and the log never echoes the pattern; case-insensitive matching; a bad deny
regex is a configuration error that names the line only; attribution lines are refused in a commit message and in a PR body (a
Co-Authored-By trailer of any author, a Claude-Session trailer, a claude.ai/code session URL, the Claude Code footer), with or without
a deny list, while prose that only names the trailer and an ordinary commit pass; GitHub's own merge subjects are skipped on the first line only;
an empty or unset variable runs the generic patterns alone and says so in one line; --from-env checks the commits of base..head only
(an old commit before the base and a merge of the base branch into the PR bring nothing in) and the title, body and branch from the
environment; the local modes (--message-file, --branch, --title with --body-file, --commits).
Also: a deny hit prints the field and line number but never the line or the pattern; a bad or empty-matching deny pattern is a
configuration error by index only; the board-N form and a hostless /items/N path are no longer patterns; `git pull`'s merge subject
is skipped; a commit message holding \\x1e or \\x1f or bytes that are not UTF-8 is read whole; the deny list comes from
CLEAN_TEXT_DENY, else from $XDG_CONFIG_HOME/stackshot/clean-text-deny; the tracked git hooks (.githooks/commit-msg and
.githooks/pre-push, core.hooksPath) refuse a commit, a branch name and a push, in a repository and in a linked worktree.
Also: no attribution line is exempt from the deny list either; a commit before the base that carries such lines brings nothing into a PR's
check; a merge subject's branch names are checked though the subject is skipped; board#N counts inside a word (_, x, dash) and
board-tmp-<name>#N takes digits and hyphens in the name; commit-msg reads "#" lines of a -m message but not git's "# On branch" status
lines or anything below the scissors line; pre-push checks the commits the remote being pushed to lacks (a commit only another remote
has is checked; a push by URL maps to its remote; an unknown URL checks all history).
Also: both hooks run the machine-wide hook of the same name (the user's global core.hooksPath, else $XDG_CONFIG_HOME/git/hooks) when it is executable, with the same arguments
and, for pre-push, the same standard input; either one failing refuses, both run; a hook that is absent, not executable, or a link to
the repo's own hook is skipped.

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
# The attribution lines the tool refuses are built from parts here, so no scan of this file's text (nor any grep for them) hits a literal line.
AN = "noreply@" + "anthropic.com"
CO = "Co-Authored-" + "By"
CS = "Claude-" + "Session"
SESS = "sess" + "ion_"                      # split, so this file holds no session id or session URL in any spelling
SID = SESS + "01AbCdEf"
CAI = "claude" + ".ai"
SURL = f"https://{CAI}/code/{SID}"
GEN = "Generated " + "with [Claude " + "Code](https://claude.com/claude-" + "code)"
TRAILERS = f"{CO}: Claude Opus 5.5 <{AN}>\n{CS}: {SURL}\n"
FOOTER = f"\U0001F916 {GEN}\n\n{SURL}\n"
ATTRIBUTION = {   # each refused shape: what, the line
    "a Claude Co-Authored-By trailer": f"{CO}: Claude Opus 5.5 <{AN}>",
    "an Anthropic Co-Authored-By trailer": f"{CO}: Anthropic <{AN}>",
    "a person's Co-Authored-By trailer": f"{CO}: Jane Doe <jane@example.invalid>",
    "a Co-Authored-By trailer in lower case": f"{CO.lower()}: someone <a@example.invalid>",
    "a Co-Authored-By trailer with no address": f"{CO}: Claude",
    "an indented Co-Authored-By trailer": f"   {CO}: Claude <{AN}>",
    "a quoted Co-Authored-By trailer": f"> {CO}: Claude <{AN}>",
    "a Claude-Session trailer": f"{CS}: {SURL}",
    "a Claude-Session trailer with another value": f"{CS}: abc",
    "a session URL on its own line": SURL,
    "a session URL inside prose": f"see {SURL} for the run",
    "a session URL in an angle link": f"<{SURL}>",
    "the generated-with footer": GEN,
    "the generated-with footer with its robot": f"\U0001F916 {GEN}",
    "the generated-with footer in lower case": GEN.lower(),
    "a generated-with line with no link": "Generated " + "with Claude Code",
    "a Co-Authored-By trailer with a space before the colon": f"{CO} : Claude <{AN}>",
    "a Co-Authored-By trailer after a dash bullet": f"- {CO}: Claude <{AN}>",
    "a Co-Authored-By trailer after a number and a dot": f"1. {CO}: Claude <{AN}>",
    "a Co-Authored-By trailer after a number and a bracket": f"2) {CO}: Claude <{AN}>",
    "a Co-Authored-By trailer after a round bullet": f"\u2022 {CO}: Claude <{AN}>",
    "a Co-Authored-By trailer in bold": f"**{CO}:** Claude <{AN}>",
    "a Co-Authored-By trailer in upper case": f"{CO.upper()}: Claude <{AN}>",
    "a Claude-Session trailer with a space before the colon": f"{CS} : {SURL}",
    "a Claude-Session trailer in lower case": f"{CS.lower()}: abc",
    "a Claude-Session trailer in upper case": f"{CS.upper()}: abc",
    "a session URL on a www host": f"https://www.{CAI}/code/{SID}",
    "a session URL in mixed case": "https://Claude.AI/" + "Code/Session_01AbCdEf",
    "a session URL followed by a full stop": SURL + ".",
    "a session URL followed by a comma": f"{SURL}, then more",
    "a session URL inside round brackets": f"({SURL})",
    "a session URL inside square brackets": f"[{SURL}]",
    "a session URL inside a markdown link": f"[the run]({SURL})",
    "a session URL with a port": f"https://{CAI}:443/code/{SID}",
    "a session URL with a trailing dot on the host": f"https://{CAI}./code/{SID}",
    "a session URL with a doubled slash": f"https://{CAI}//code/{SID}",
    "a session URL with a percent-encoded path": f"https://{CAI}/%63ode/{SID}",
    "a session URL with a percent-encoded slash-free host path": f"https://{CAI}/%63%6f%64%65/{SID}",
    "a Claude-Session trailer with a space before the colon and a plain value": f"{CS} : abc",
    "a Claude-Session trailer after other text on the line": f"note {CS}: abc",
    # the code-session path of claude.ai with no session_ in it, so only the path pattern can catch these
    "a code-session path with a port and no session id": "https://claude.ai:443/" + "code/abc123",
    "a code-session path with a trailing dot on the host and no session id": "https://claude.ai./" + "code/abc123",
    "a code-session path with a doubled slash and no session id": "https://claude.ai//" + "code/abc123",
    "a code-session path with a percent-encoded letter and no session id": f"https://{CAI}/%63ode/abc123",
    "a code-session path fully percent-encoded and no session id": f"https://{CAI}/%63%6f%64%65/abc123",
    "the generated-with footer with bold on the name only": "Generated " + "with **Claude** " + "Code",
    "a claude.ai URL that holds session_ elsewhere": f"https://{CAI}/some/other/path?id={SID}",
    "a claude.com URL that holds session_": f"https://claude.com/some/path/{SID}",
    "the generated-with footer with the name in bold": "Generated " + "with **Claude " + "Code**",
    "the generated-with footer with the name in backticks": "Generated " + "with `Claude " + "Code`",
    "the generated-with footer with a bold link text": "Generated " + "with [**Claude " + "Code**](https://claude.com/claude-" + "code)",
    "the generated-with footer with a bracket and no link": "Generated " + "with [Claude " + "Code]",
    "a generated-by footer": "Generated " + "by Claude " + "Code",
    "a generated-using footer": "Generated " + "using Claude " + "Code",
    "the generated-with footer in upper case": GEN.upper(),
    "the product link alone": "[Claude " + "Code](https://claude.com/claude-" + "code)",
    "the product link in a claude.ai spelling": "https://claude.ai/claude-" + "code",
}

# ---- 1. clean text passes, in every mode
rc, out = tool(["--title", "Wrap the handoff row", "--body-file", write("body-ok.md", CLEAN_BODY), "--branch", "fix/handoff-row-wrap"])
check("clean title, body and branch pass", rc == 0 and "ok" in out, (rc, out))
rc, out = tool(["--message-file", write("msg-ok.txt", "Wrap the handoff row\n\n" + CLEAN_BODY + "\nSigned-off-by: A Dev <dev@example.invalid>\n")])
check("an ordinary commit message passes (with a sign-off trailer)", rc == 0 and "ok" in out, (rc, out))
rc, out = tool(["--message-file", write("msg-ok2.txt", "Document the Co-Authored-" + "By rule\n\nThe Claude-" + "Session trailer and the session links are refused; a pull request body says it in words.\n")])
check("prose that only names a trailer passes", rc == 0, (rc, out))
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

# ---- 5. attribution lines are refused everywhere, with or without a deny list; nothing is exempt
for what, line in ATTRIBUTION.items():
    for field, args in (("message", ["--message-file", write("at-m.txt", "Wrap the row\n\nWhy it wraps.\n\n" + line + "\n")]),
                        ("body", ["--body-file", write("at-b.md", CLEAN_BODY + "\n" + line + "\n")])):
        rc, out = tool(args)
        check(f"{what} in a {field} is refused", rc == 1 and f"FAIL {field}" in out and "refused" in out and "line " in out, (rc, out))
    rc, out = tool(["--title", line])
    check(f"{what} in a title is refused", rc == 1 and "FAIL title" in out, (rc, out))
# a hit names its kind and its place and never repeats the line, so a refused session URL is not copied into a public log
for what, line in ATTRIBUTION.items():
    marked = line + " zq9x7"
    for field, args in (("message", ["--message-file", write("nx-m.txt", "Wrap the row\n\n" + marked + "\n")]),
                        ("body", ["--body-file", write("nx-b.md", CLEAN_BODY + "\n" + marked + "\n")]),
                        ("title", ["--title", marked])):
        rc, out = tool(args)
        check(f"{what} in a {field}: the log does not repeat the line", rc == 1 and "zq9x7" not in out and SESS + "01" not in out and "FAIL" in out, (rc, out))
rc, out = tool(["--message-file", write("nx2.txt", f"S\n\n{CS}: {SURL} board#5 zq9x7\n")])
check("a board id on an attribution line: both are reported and the line is not repeated", rc == 1 and "board item id" in out and "Claude-Session" in out and "zq9x7" not in out, (rc, out))
rc, out = tool(["--message-file", write("nx3.txt", "S\n\nSee board#5 for why.\n")])
check("a board id alone still prints its line", "See board#5 for why." in out, (rc, out))

# a merge subject is skipped for the deny list, but its attribution is not; a merge-looking line anywhere but line 1 is not skipped at all
for subj, what in ((f"Merge branch 'x' of {SURL} into fix/y", "a pull's url"),
                   (f"Merge branch 'x' of https://{CAI}/%63ode/{SID} into fix/y", "an encoded url"),
                   (f"Merge pull request #1 from {CAI}/code/{SESS}01", "the owner of a pull request merge"),
                   ("Merge pull request #1 from claude.ai/" + "code/x", "a code path as the owner"),
                   (f"Merge branch 'main' into fix/{CAI}/code/{SESS}01", "the into-branch")):
    rc, out = tool(["--message-file", write("mgs.txt", subj + "\n")])
    check(f"merge subject: a session URL in {what} is refused", rc == 1 and "FAIL message" in out and SESS + "01" not in out, (rc, out))
rc, out = tool(["--message-file", write("mgs2.txt", "Merge branch 'main' into fix/x\n")])
check("merge subject: a plain subject still passes", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("mgs3.txt", "Fix the row\n\nMerge branch 'main' into fix/board#3\n")])
check("a merge subject on line 3 is not skipped (its branch name is read as ordinary text)", rc == 1 and "line 3" in out and "board item id" in out, (rc, out))
rc, out = tool(["--message-file", write("mgs4.txt", f"Fix the row\n\nMerge branch 'x' of {SURL} into fix/y\n")])
check("a merge subject on line 3 holding a session URL is refused on line 3", rc == 1 and "line 3" in out and SESS + "01" not in out, (rc, out))
rc, out = tool(["--message-file", write("mgs5.txt", f"Fix the row\n\nMerge pull request #1 from some-owner/fix/board#6\n")])
check("a pull-request merge subject on line 3 is not skipped", rc == 1 and "line 3" in out, (rc, out))
rc, out = tool(["--title", f"Merge branch 'x' of {SURL} into fix/y"])
check("a merge-subject-shaped title with a session URL is refused", rc == 1, (rc, out))

# the exempt set: four full shas, attribution only
check("the exempt set holds four full lower-case shas", len(ct.ATTRIBUTION_EXEMPT_SHAS) == 4 and all(len(x) == 40 and x == x.lower() and set(x) <= set("0123456789abcdef") for x in ct.ATTRIBUTION_EXEMPT_SHAS), ct.ATTRIBUTION_EXEMPT_SHAS)
trailer_msg = f"Old change\n\n{CO}: Claude Opus 5.5 <{AN}>\n"
check("check_field: without the exemption a trailer is a hit", len(ct.check_field("c", trailer_msg, [], True)) == 1)
check("check_field: with the exemption the trailer passes", ct.check_field("c", trailer_msg, [], True, True) == [])
check("check_field: the exemption does not cover a board id on the same commit", [h[3] for h in ct.check_field("c", trailer_msg + "refs board#5\n", [], True, True)] == ["board item id (board#N)"])
dl, _ = ct.load_deny("old change")
check("check_field: the exemption does not cover the deny list", [h[3] for h in ct.check_field("c", trailer_msg, dl, True, True)] == ["deny pattern 1"])
check("check_field: the exemption switches off every attribution pattern of that commit, a session URL line included", len(ct.check_field("c", trailer_msg + SURL + "\n", [], True, True)) == 0)
check("commit_field exempts by the full sha only", ct.commit_field(sorted(ct.ATTRIBUTION_EXEMPT_SHAS)[0], "m")[3] is True
      and ct.commit_field(sorted(ct.ATTRIBUTION_EXEMPT_SHAS)[0][:10], "m")[3] is False and ct.commit_field("0" * 40, "m")[3] is False)

# the workflow reads the PR's own commits: base..head, never all history
wf = open(os.path.join(STACK, ".github", "workflows", "clean-text.yml"), encoding="utf-8").read()
check("the workflow runs --from-env with the base branch as the base revision", 'BASE_REV="origin/$BASE_REF" uv run --no-project python tools/clean_text.py --from-env' in wf, wf)
check("the workflow takes the head from the pull request and the base from its base ref", "HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in wf and "BASE_REF: ${{ github.event.pull_request.base.ref || 'main' }}" in wf)
check("the workflow fetches the whole history so base..head can be read", "fetch-depth: 0" in wf)
check("the workflow never walks all history (no --new-commits, no bare --commits)", "--new-commits" not in wf and "--commits" not in wf)

msg = "Subject\n\n" + CLEAN_BODY + "\n" + TRAILERS + FOOTER
rc, out = tool(["--message-file", write("m1.txt", msg)])
check("a message with the trailers, footer and session URL is refused on every one of those lines", rc == 1 and out.count("FAIL message") == 5, (rc, out))
rc, out = tool(["--message-file", write("m1b.txt", msg)], deny=SID + "\nnoreply\nclaude")
check("a deny list does not exempt them: they are refused, and the deny list is read on them without echoing the line", rc == 1 and "deny pattern" in out and "refused" in out and SID not in out, (rc, out))
rc, out = tool(["--body-file", write("b1.md", CLEAN_BODY + "\n" + FOOTER)])
check("a PR body ending with the footer and the session URL is refused", rc == 1 and out.count("FAIL body") == 2, (rc, out))
rc, out = tool(["--message-file", write("m2.txt", f"S\n\n{CS}: {SURL} board#5\n")])
check("a board id on an attribution line is reported too", rc == 1 and "board item id" in out and "Claude-Session" in out, (rc, out))
rc, out = tool(["--message-file", write("m3f.txt", f"S\n\n{CO}: Claude Sonnet 5.5 <{AN}>\n{CO}: Jane Doe <jane@example.invalid>\n")])
check("every trailer is reported on its own line", rc == 1 and "line 3" in out and "line 4" in out, (rc, out))
rc, out = tool(["--message-file", write("m3g.txt", f"S\n\nbody {CO}: kept inline\n")])
check("the words inside a sentence are not a trailer", rc == 0, (rc, out))
rc, out = tool(["--message-file", write("m4.txt", "Fix the row\n\nSigned-off-by: A <a@example.invalid>\nboard#7\n")])
check("other trailers are not skipped", rc == 1, (rc, out))
for text, what in (("Explain the claude.ai connector setup", "claude.ai alone"), ("A session of the claude code client", "the words claude code in prose"),
                   ("Pass Claude the file", "the name Claude"), ("Numbers generated with Claude 3 are not comparable", "generated with a model name"),
                   ("Generated with care by the build", "generated with something else"), ("Docs for the claude.ai/code feature", "a bare claude.ai/code mention with no slash after"), ("Reads the https://claude.ai/chat/abc page title", "a chat link is not a code session link")):
    rc, out = tool(["--title", text])
    check(f"attribution patterns do not misfire: {what}", rc == 0, (rc, out))

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
commit("An old commit before the rule\n\n" + TRAILERS.strip(), "a.txt")          # in main's history, with attribution lines: never checked
git(repo, "checkout", "-q", "-b", "fix/handoff-row-wrap")
commit("Wrap the handoff row\n\nWrapped so the table fits.", "b.txt")
commit("Cover the narrow case", "c.txt")
git(repo, "checkout", "-q", "main")
commit("Another change on main", "d.txt")                  # main moved on after the branch was made
git(repo, "checkout", "-q", "fix/handoff-row-wrap")
git(repo, "merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into fix/handoff-row-wrap")
head = git(repo, "rev-parse", "HEAD")
ENV_OK = {"PR_TITLE": "Wrap the handoff row", "PR_BODY": CLEAN_BODY, "PR_BRANCH": "fix/handoff-row-wrap",
          "BASE_REV": "main", "HEAD_SHA": head}
rc, out = tool(["--from-env"], extra=ENV_OK, cwd=repo)
check("--from-env: a clean PR passes; old history (even with attribution lines) and a merge of the base branch bring nothing in", rc == 0 and "4 field(s)" not in out and "ok" in out, (rc, out))
check("--from-env: title, body, branch and the PR's own commits were checked (3 + 3 commits)", "6 field(s)" in out, out)
old_sha = git(repo, "rev-list", "--max-parents=0", "main")
check("(setup) the old commit on main really carries the attribution lines", CO in git(repo, "log", "-1", "--format=%B", old_sha), old_sha)
rc, out = tool(["--commits", f"{old_sha}^!"], cwd=repo)
check("(setup) checked on its own, that old commit is refused", rc == 1, (rc, out))
rc, out = tool(["--from-env"], extra={**ENV_OK, "PR_BODY": CLEAN_BODY + "\n" + FOOTER}, cwd=repo)
check("--from-env: a PR body with the footer and session URL fails", rc == 1 and out.count("FAIL body") == 2, (rc, out))
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
final_head = git(repo, "rev-parse", "HEAD")
rc, out = tool(["--from-env"], extra={**ENV_OK, "HEAD_SHA": git(repo, "rev-parse", "HEAD")}, cwd=repo)
short = git(repo, "rev-parse", "--short=10", "HEAD")
check("--from-env: a board id in a commit message fails and names the commit", rc == 1 and f"FAIL commit {short}" in out and "refs board#9012" in out, (rc, out))
git(repo, "reset", "-q", "--hard", "HEAD~1")
commit("Add a trailer\n\n" + TRAILERS.strip(), "f.txt")
rc, out = tool(["--from-env"], extra={**ENV_OK, "HEAD_SHA": git(repo, "rev-parse", "HEAD")}, cwd=repo)
short = git(repo, "rev-parse", "--short=10", "HEAD")
check("--from-env: a commit the PR adds with attribution lines fails and names the commit", rc == 1 and out.count(f"FAIL commit {short}") == 3 and "line 3" in out and "line 4" in out, (rc, out))
rc, out = tool(["--commits", "main..HEAD"], cwd=repo)
check("--commits: the same commit is refused in a local run", rc == 1 and f"FAIL commit {short}" in out, (rc, out))
git(repo, "reset", "-q", "--hard", final_head)
rc, out = tool(["--from-env"], deny="cover the narrow", extra=ENV_OK, cwd=repo)
check("--from-env: a deny hit in an earlier commit is found", rc == 1 and "FAIL commit" in out and "deny pattern 1" in out and "cover the narrow" not in out, (rc, out))
rc, out = tool(["--commits", "main..HEAD"], cwd=repo)
check("--commits checks a range", rc == 1 and "FAIL commit" in out, (rc, out))
rc, out = tool(["--commits", "nope..HEAD"], cwd=repo)
check("--commits with a bad range is a call error", rc == 2, (rc, out))

# ---- 8. the line rules, imported
cl = ct.numbered_lines("a\n" + TRAILERS + "b\n")
check("numbered_lines gives every line, none marked as exempt, numbered from 1", cl == [(1, "a"), (2, f"{CO}: Claude Opus 5.5 <{AN}>"), (3, f"{CS}: {SURL}"), (4, "b"), (5, "")], cl)
check("numbered_lines leaves out a standard merge subject on a message only", ct.numbered_lines("Merge branch 'main' into fix/x\nbody", True) == [(2, "body")] and ct.numbered_lines("Merge branch 'main' into fix/x", False) == [(1, "Merge branch 'main' into fix/x")])
check("no allow-list is left in the tool", not hasattr(ct, "ALLOWED_LINES") and not hasattr(ct, "classified_lines"))
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
check("commit-msg: a message with a Co-Authored-By and a Claude-Session trailer is refused and nothing is committed", rc != 0 and count(hk) == n0 and "refused" in out and "line 3" in out and "line 4" in out, (rc, out))
for what, line in ATTRIBUTION.items():
    rc, out = hcommit(hk, "a.txt", "Fix the row\n\n" + line)
    check(f"commit-msg: {what} is refused", rc != 0 and count(hk) == n0 and "refused" in out, (rc, out))
rc, out = hcommit(hk, "a.txt", "Fix the row\n\nThe row wraps below 400 px.")
check("commit-msg: an ordinary message passes", rc == 0 and count(hk) == n0 + 1 and "not available" in out, (rc, out))
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
hgit(hk, "checkout", "-q", "-b", "attrib", parent)
rc, out = hcommit(hk, "att.txt", "Add the row\n\n" + TRAILERS.strip(), "--no-verify")
check("(setup) a commit with attribution lines made with --no-verify", rc == 0, (rc, out))
attrib = git(hk, "rev-parse", "HEAD")
rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib} refs/heads/attrib {ZERO}"])
check("pre-push: a new branch holding a commit with attribution lines is refused, naming the commit", rc == 1 and f"FAIL commit {attrib[:10]}" in out and "refused" in out, (rc, out))
# an old attributed commit: named by its full sha in the (scratch copy of the) tool's exempt set it passes; any other sha is refused
rc, out = hcommit(hk, "att2.txt", "Add another row\n\n" + TRAILERS.strip(), "--no-verify")
attrib2 = git(hk, "rev-parse", "HEAD")
rc, out = hcommit(hk, "att3.txt", "Add a third row\n\nrefs board#8\n\n" + TRAILERS.strip(), "--no-verify")
attrib3 = git(hk, "rev-parse", "HEAD")
hk_tool = os.path.join(hk, "tools", "clean_text.py")
tool_text = open(hk_tool, encoding="utf-8").read()
marker = "ATTRIBUTION_EXEMPT_SHAS = frozenset({\n"
check("(setup) the exempt set can be patched in the scratch copy", tool_text.count(marker) == 1)
def exempt_only(*shas):
    with open(hk_tool, "w", encoding="utf-8") as f: f.write(tool_text.replace(marker, marker + "".join(f'    "{x}",\n' for x in shas)))
try:
    exempt_only(attrib)
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib} refs/heads/attrib {ZERO}"])
    check("pre-push: an old commit named in the exempt set passes the walk of all history", rc == 0 and "FAIL" not in out, (rc, out))
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib2} refs/heads/attrib {ZERO}"])
    check("pre-push: the exempt commit passes but the next attributed commit is refused, and only it", rc == 1 and f"FAIL commit {attrib2[:10]}" in out and f"FAIL commit {attrib[:10]}" not in out, (rc, out))
    exempt_only(attrib[:10])
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib} refs/heads/attrib {ZERO}"])
    check("pre-push: a short sha in the exempt set exempts nothing", rc == 1 and f"FAIL commit {attrib[:10]}" in out, (rc, out))
    exempt_only(attrib, attrib2, attrib3)
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib3} refs/heads/attrib {ZERO}"])
    check("pre-push: an exempt commit is still read for a board id and the deny list", rc == 1 and f"FAIL commit {attrib3[:10]}" in out and "board item id" in out and f"FAIL commit {attrib2[:10]}" not in out
          and "Co-Authored" not in out and "Claude-Session" not in out, (rc, out))
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib2} refs/heads/attrib {ZERO}"])
    check("pre-push: two exempt commits pass together", rc == 0, (rc, out))
    rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib2} refs/heads/attrib {attrib}"])
    check("pre-push: an update range holding only an exempt commit passes", rc == 0, (rc, out))
finally:
    with open(hk_tool, "w", encoding="utf-8") as f: f.write(tool_text)
rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib} refs/heads/attrib {parent}"])
check("pre-push: with the real exempt set the same commit is refused again", rc == 1 and f"FAIL commit {attrib[:10]}" in out, (rc, out))
rc, out = hrun(hk, "pre-push", [f"refs/heads/attrib {attrib} refs/heads/attrib {ZERO}"], args=("nowhere", "git@example.invalid:o/r.git"))
check("pre-push: a push by a URL no remote has walks all history and refuses the attributed commit", rc == 1 and f"FAIL commit {attrib[:10]}" in out, (rc, out))
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

# ---- 12. the hooks also run the machine-wide hook of the same name (chain-global: the user's global core.hooksPath, else
# $XDG_CONFIG_HOME/git/hooks), when it exists and is executable
# HOME, XDG_CONFIG_HOME and GIT_CONFIG_GLOBAL point into the scratch folder, so the real machine's hook and config are never read here. A stand-in hook records what
# it was given (its arguments, its standard input, the message file it was handed) under GX_LOG and exits with a chosen status.
GX = os.path.join(tmp, "gx"); GXH = os.path.join(GX, "git", "hooks"); GXLOG = os.path.join(tmp, "gx-log")
GXTMP = os.path.join(tmp, "gx-tmp")           # the hooks' TMPDIR: nothing may stay in it
os.makedirs(GXLOG); os.makedirs(GXTMP)
GENV = {**BASE_ENV, "HOME": os.path.join(tmp, "gx-home"), "XDG_CONFIG_HOME": GX, "GX_LOG": GXLOG, "TMPDIR": GXTMP}
HENV = GENV                                   # hgit, hrun and hcommit above read this name at call time
def stand_in(hook, code, executable=True, d=None, log=None):
    d = d or GXH; log = log or GXLOG
    os.makedirs(d, exist_ok=True); os.makedirs(log, exist_ok=True)
    p = os.path.join(d, hook)
    if os.path.lexists(p): os.remove(p)
    body = '#!/bin/sh\necho ran >> "%s/%s.ran"\nprintf "%%s\\n" "$@" > "%s/%s.args"\n' % (log, hook, log, hook)
    body += 'cp "$1" "%s/commit-msg.msg"\n' % log if hook == "commit-msg" else 'cat > "%s/pre-push.stdin"\n' % log
    body += "exit %d\n" % code
    with open(p, "w") as f: f.write(body)
    os.chmod(p, 0o755 if executable else 0o644)
def stand_in_clear():
    shutil.rmtree(GXLOG, ignore_errors=True); os.makedirs(GXLOG)
def seen(name, log=None):
    p = os.path.join(log or GXLOG, name)
    if not os.path.exists(p): return None
    with open(p, encoding="utf-8") as f: return f.read()
def stand_in_remove():
    shutil.rmtree(GX, ignore_errors=True); stand_in_clear()

hg = os.path.join(tmp, "hg"); os.makedirs(hg)
git(hg, "init", "-q", "-b", "main")
os.makedirs(os.path.join(hg, "tools"))
shutil.copy(SCRIPT, os.path.join(hg, "tools", "clean_text.py"))
shutil.copytree(HOOKS_SRC, os.path.join(hg, ".githooks"))
git(hg, "config", "core.hooksPath", ".githooks")
git(hg, "add", "-A"); git(hg, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "Add the hooks")
CLEAN, DIRTY = "Fix the row", "Fix the row (board#5)"

# 1. no machine-wide hook directory: as before
stand_in_remove()
g0 = count(hg)
rc, out = hcommit(hg, "a.txt", CLEAN)
check("global hook: none present, a clean commit passes as before", rc == 0 and count(hg) == g0 + 1, (rc, out))
rc, out = hcommit(hg, "b.txt", DIRTY)
check("global hook: none present, a dirty commit is refused as before", rc != 0 and "board item id" in out and "machine-wide" not in out and count(hg) == g0 + 1, (rc, out))
tip = git(hg, "rev-parse", "HEAD")
rc, out = hrun(hg, "pre-push", [f"refs/heads/ok {tip} refs/heads/ok {ZERO}"])
check("global hook: none present, pre-push passes a clean push as before", rc == 0, (rc, out))
rc, out = hrun(hg, "pre-push", [f"refs/heads/main {tip} refs/heads/fix/board#3 {ZERO}"])
check("global hook: none present, pre-push refuses a dirty branch name as before", rc == 1 and "FAIL branch" in out and "machine-wide" not in out, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")

# 2. executable, exits 0: still passes, and it got the same arguments and standard input
stand_in("commit-msg", 0); stand_in("pre-push", 0); stand_in_clear()
g1 = count(hg)
rc, out = hcommit(hg, "c.txt", CLEAN + "\n\nA second line.")
args = seen("commit-msg.args")
check("global hook: exit 0 and a clean message, the commit goes through", rc == 0 and count(hg) == g1 + 1, (rc, out))
check("global hook: commit-msg got the message file as its one argument", args is not None and len(args.splitlines()) == 1 and args.strip().endswith("COMMIT_EDITMSG"), args)
check("global hook: commit-msg saw the whole message", (seen("commit-msg.msg") or "").startswith(CLEAN + "\n\nA second line."), seen("commit-msg.msg"))
msgfile = os.path.join(tmp, "gx-COMMIT_EDITMSG")
with open(msgfile, "w", encoding="utf-8") as f: f.write("Fix the row\n\n# On branch some-branch\nA line.\n")
stand_in_clear()
r = subprocess.run([os.path.join(hg, ".githooks", "commit-msg"), msgfile], cwd=hg, env=HENV, capture_output=True, timeout=60)
check("global hook: commit-msg is given the original file, git's template lines included (the repo hook strips them for its own check only)",
      r.returncode == 0 and seen("commit-msg.args") == msgfile + "\n" and "# On branch some-branch" in (seen("commit-msg.msg") or ""), (r.returncode, seen("commit-msg.args"), seen("commit-msg.msg")))
tip = git(hg, "rev-parse", "HEAD")
stand_in_clear()
lines = [f"refs/heads/ok {tip} refs/heads/ok {ZERO}", f"refs/heads/two {tip} refs/heads/two {ZERO}"]
rc, out = hrun(hg, "pre-push", lines, args=("origin", "ssh://example.invalid/r.git"))
check("global hook: exit 0, pre-push passes", rc == 0, (rc, out))
check("global hook: pre-push got the remote name and URL", seen("pre-push.args") == "origin\nssh://example.invalid/r.git\n", seen("pre-push.args"))
check("global hook: pre-push got the same lines on standard input", seen("pre-push.stdin") == "".join(l + "\n" for l in lines), seen("pre-push.stdin"))
hgit(hg, "branch", "-q", "dirty", "HEAD~1"); hgit(hg, "checkout", "-q", "dirty")
rc, out = hcommit(hg, "d.txt", DIRTY, "--no-verify")
dirty = git(hg, "rev-parse", "HEAD"); hgit(hg, "checkout", "-q", "main")
stand_in_clear()
rc, out = hrun(hg, "pre-push", [f"refs/heads/dirty {dirty} refs/heads/dirty {ZERO}"])
check("global hook: the repo's own check still reads the same lines (a dirty commit is refused with the hook at 0)", rc == 1 and f"FAIL commit {dirty[:10]}" in out, (rc, out))
check("global hook: it also got those lines", f"refs/heads/dirty {dirty} refs/heads/dirty {ZERO}\n" == seen("pre-push.stdin"), seen("pre-push.stdin"))
bare = os.path.join(tmp, "gx-remote.git"); os.makedirs(bare)
git(bare, "init", "-q", "--bare", "-b", "main")
git(hg, "remote", "add", "origin", bare)
stand_in_clear()
rc, out = hgit(hg, "push", "-q", "origin", "main")
check("global hook: a real push passes, the hook got the remote name, the URL and the pushed ref",
      rc == 0 and seen("pre-push.args") == f"origin\n{bare}\n" and f"refs/heads/main {git(hg, 'rev-parse', 'main')} refs/heads/main {ZERO}" in (seen("pre-push.stdin") or ""), (rc, out, seen("pre-push.args"), seen("pre-push.stdin")))

# 3. executable, exits 1, the repo's own check passes: refused
stand_in("commit-msg", 1); stand_in("pre-push", 1); stand_in_clear()
g2 = count(hg)
rc, out = hcommit(hg, "e.txt", CLEAN)
check("global hook: exit 1 with a clean message, the commit is refused and says which hook", rc != 0 and count(hg) == g2 and "machine-wide" in out and seen("commit-msg.ran") is not None, (rc, out))
tip = git(hg, "rev-parse", "HEAD")
rc, out = hrun(hg, "pre-push", [f"refs/heads/ok {tip} refs/heads/ok {ZERO}"])
check("global hook: exit 1 with a clean push, pre-push is refused and says which hook", rc == 1 and "machine-wide" in out and seen("pre-push.ran") is not None, (rc, out))
rc, out = hgit(hg, "push", "-q", "origin", "main:refs/heads/by-hook")
check("global hook: a real push is refused and the remote has no such branch", rc != 0 and "by-hook" not in git(bare, "branch"), (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")

# 4. exits 0, the repo's own check fails: refused
stand_in("commit-msg", 0); stand_in("pre-push", 0); stand_in_clear()
g3 = count(hg)
rc, out = hcommit(hg, "f.txt", DIRTY)
check("global hook: exit 0 but the repo's check fails, the commit is refused", rc != 0 and "board item id" in out and count(hg) == g3 and seen("commit-msg.ran") is not None, (rc, out))
rc, out = hrun(hg, "pre-push", [f"refs/heads/main {tip} refs/heads/fix/board#3 {ZERO}"])
check("global hook: exit 0 but the repo's check fails, the push is refused", rc == 1 and "FAIL branch" in out and seen("pre-push.ran") is not None, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")

# 5. present but not executable: ignored, no error
stand_in("commit-msg", 1, executable=False); stand_in("pre-push", 1, executable=False); stand_in_clear()
g4 = count(hg)
rc, out = hcommit(hg, "g.txt", CLEAN)
check("global hook: not executable, the commit passes and the file is not run", rc == 0 and count(hg) == g4 + 1 and seen("commit-msg.ran") is None and "machine-wide" not in out, (rc, out))
rc, out = hcommit(hg, "h.txt", DIRTY)
check("global hook: not executable, the repo's check still refuses", rc != 0 and "board item id" in out and seen("commit-msg.ran") is None, (rc, out))
tip = git(hg, "rev-parse", "HEAD")
rc, out = hrun(hg, "pre-push", [f"refs/heads/ok {tip} refs/heads/ok {ZERO}"])
check("global hook: not executable, pre-push passes and the file is not run", rc == 0 and seen("pre-push.ran") is None and "machine-wide" not in out, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")

# 6. both fail: both ran, and the exit is non-zero
stand_in("commit-msg", 1); stand_in("pre-push", 1); stand_in_clear()
g5 = count(hg)
rc, out = hcommit(hg, "i.txt", DIRTY)
check("global hook: both fail on a commit, both ran and the output shows both refusals",
      rc != 0 and count(hg) == g5 and seen("commit-msg.ran") is not None and "board item id" in out and "machine-wide" in out, (rc, out))
rc, out = hrun(hg, "pre-push", [f"refs/heads/main {tip} refs/heads/fix/board#3 {ZERO}"])
check("global hook: both fail on a push, both ran and the exit is non-zero",
      rc == 1 and seen("pre-push.ran") is not None and "FAIL branch" in out and "machine-wide" in out, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")

# the machine-wide hook being this very hook (a link to it) is not run again: no recursion
stand_in_remove(); os.makedirs(GXH)
for h in ("commit-msg", "pre-push"): os.symlink(os.path.join(hg, ".githooks", h), os.path.join(GXH, h))
rc, out = hcommit(hg, "j.txt", CLEAN)
check("global hook: a link to the repo's own commit-msg is skipped (no recursion), the commit passes", rc == 0, (rc, out))
rc, out = hcommit(hg, "k.txt", DIRTY)
check("global hook: a link to the repo's own commit-msg is skipped, the repo's check still refuses", rc != 0 and "board item id" in out, (rc, out))
rc, out = hrun(hg, "pre-push", [f"refs/heads/ok {tip} refs/heads/ok {ZERO}"])
check("global hook: a link to the repo's own pre-push is skipped (no recursion)", rc == 0, (rc, out))
stand_in_remove()
# the user's global core.hooksPath comes first (a leading ~ expanded), before the XDG directory
GXALT = os.path.join(GENV["HOME"], "alt-hooks"); GXDECOY = os.path.join(tmp, "gx-decoy-log")
GXCFG = os.path.join(tmp, "gx-gitconfig")
with open(GXCFG, "w") as f: f.write("[core]\n\thooksPath = ~/alt-hooks\n")
stand_in_remove(); shutil.rmtree(GXDECOY, ignore_errors=True)
HENV = {**GENV, "GIT_CONFIG_GLOBAL": GXCFG}
stand_in("commit-msg", 1, log=GXDECOY); stand_in("pre-push", 1, log=GXDECOY)           # the XDG directory: must not be used now
stand_in("commit-msg", 0, d=GXALT); stand_in("pre-push", 0, d=GXALT)
g6 = count(hg)
rc, out = hcommit(hg, "l.txt", CLEAN)
check("global core.hooksPath: its hook runs (~ expanded), the XDG directory is not used, the clean commit passes",
      rc == 0 and count(hg) == g6 + 1 and seen("commit-msg.ran") is not None and seen("commit-msg.ran", GXDECOY) is None, (rc, out))
check("global core.hooksPath: commit-msg got the message file as its one argument", len((seen("commit-msg.args") or "").splitlines()) == 1 and (seen("commit-msg.args") or "").strip().endswith("COMMIT_EDITMSG"), seen("commit-msg.args"))
lines = [f"refs/heads/ok {tip} refs/heads/ok {ZERO}"]
rc, out = hrun(hg, "pre-push", lines, args=("origin", "ssh://example.invalid/r.git"))
check("global core.hooksPath: pre-push got the same arguments and standard input, the XDG directory is not used",
      rc == 0 and seen("pre-push.args") == "origin\nssh://example.invalid/r.git\n" and seen("pre-push.stdin") == lines[0] + "\n" and seen("pre-push.ran", GXDECOY) is None, (rc, out, seen("pre-push.args"), seen("pre-push.stdin")))
stand_in("commit-msg", 1, d=GXALT); stand_in("pre-push", 1, d=GXALT)
rc, out = hcommit(hg, "m.txt", CLEAN)
check("global core.hooksPath: its hook exits 1, the commit is refused", rc != 0 and count(hg) == g6 + 1 and "machine-wide" in out, (rc, out))
rc, out = hrun(hg, "pre-push", lines)
check("global core.hooksPath: its hook exits 1, the push is refused", rc == 1 and "machine-wide" in out, (rc, out))
rc, out = hcommit(hg, "m.txt", DIRTY)
check("global core.hooksPath: both fail on a commit, both ran", rc != 0 and "board item id" in out and "machine-wide" in out, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")
# a global core.hooksPath that names the repo's own hook directory is the very same file: skipped, no loop
with open(GXCFG, "w") as f: f.write("[core]\n\thooksPath = %s\n" % os.path.join(hg, ".githooks"))
rc, out = hcommit(hg, "n.txt", CLEAN)
check("global core.hooksPath naming the repo's own hooks: skipped (no recursion), the commit passes", rc == 0, (rc, out))
rc, out = hcommit(hg, "o.txt", DIRTY)
check("global core.hooksPath naming the repo's own hooks: the repo's check still refuses", rc != 0 and "board item id" in out, (rc, out))
rc, out = hrun(hg, "pre-push", lines)
check("global core.hooksPath naming the repo's own hooks: pre-push passes (no recursion)", rc == 0, (rc, out))
hgit(hg, "reset", "-q", "--hard", "HEAD")
HENV = GENV; stand_in_remove(); shutil.rmtree(GXALT, ignore_errors=True)
check("global hook: pre-push leaves no temporary file behind, pass or fail", os.listdir(GXTMP) == [], os.listdir(GXTMP))

if fails: print(f"{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: clean_text, {len(ran)} checks"); sys.exit(0)
