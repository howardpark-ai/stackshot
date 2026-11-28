"""Scenario test for tools/prepush and its part of .githooks/pre-push: a throwaway repository holding the real tools
(clean_text, retired_terms, tool_text), with stand-ins for the suite runner and the suite map, which only record how they were
called. Each mistake a check exists for is planted on a branch and the command must fail on it; the clean branch must pass.

    tests/run-suite prepush   (or python3: stdlib and git only)   → exit 0 / 1"""
import importlib.machinery, importlib.util, os, pathlib, shutil, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch
T = pathlib.Path(_scratch.mkdtemp(prefix="prepush-"))
R = T / "repo"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(T), "XDG_CONFIG_HOME": str(T / "xdg"), "LANG": "C.UTF-8",
       "TMPDIR": str(T), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
       "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
       "CALLS": str(T / "calls"), "CLEAN_TEXT_DENY": "zeppelin"}   # a made-up word for the text check to refuse

def git(*args):
    r = subprocess.run(["git", *args], cwd=R, env=ENV, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()

def write(name, text, mode=None):
    p = R / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")
    if mode: p.chmod(mode)

def commit(msg="Change the notes"):
    git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
    return git("rev-parse", "HEAD")

def branch(name):
    git("checkout", "-q", "-f", "-B", name, "main"); git("clean", "-qfd")
    (T / "calls").write_text("")

def run(*args, **env):
    r = subprocess.run([sys.executable, str(R / "tools/prepush"), *args], cwd=T, env={**ENV, **env}, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr

def calls():
    return (T / "calls").read_text().splitlines()

def line(out, name):
    return next((x for x in out.splitlines() if x[5:].startswith(name) and x[:4] in ("ok  ", "FAIL")), "")[:4]

sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("prepush", os.path.join(STACK, "tools", "prepush"))
prepush = importlib.util.module_from_spec(importlib.util.spec_from_loader("prepush", loader)); loader.exec_module(prepush)
WHOLE = prepush.WHOLE_TREE
check("every whole-tree suite is a suite of this repository", all(os.path.isfile(os.path.join(SCR, f"{n}_scenario.py")) for n in WHOLE), WHOLE)

# ---- the fixture: main, with origin/main at the same commit
R.mkdir()
git("init", "-q", "-b", "main")
for f in ("tools/prepush", "tools/clean_text.py", "tools/retired_terms.py", "tools/tool_text.py", ".githooks/pre-push", ".githooks/chain-global"):
    (R / f).parent.mkdir(parents=True, exist_ok=True); shutil.copy(os.path.join(STACK, f), R / f)
write("tests/retired_terms.toml", '[[term]]\nretired = "gizmo"\nuse = "widget"\n\n[[scan]]\nfiles = ["docs/*.md"]\n')
write("tests/tool_text.snapshot.json", "{}\n")
SERVER = '@mcp.tool()\ndef hello(name: str) -> str:\n    return "hello " + name\n'
write("stackshot/web/server.py", SERVER)
write("docs/notes.md", "A widget.\n")
write("tests/suitemap.py", """import os, sys
open(os.environ["CALLS"], "a").write("select " + " ".join(sys.argv[2:]) + "\\n")
print("suitemap: CI map of main abc", file=sys.stderr)
print(os.environ.get("PICK", "alpha tool_text"))
sys.exit(int(os.environ.get("PICK_EXIT", "0")))
""")
write("tests/run-suite", '#!/bin/sh\necho "suite $1" >>"$CALLS"\n[ "$1" != "${BAD:-}" ] || { echo "FAIL a planted check"; echo "0/1"; exit 1; }\necho "1/1 checks passed"\n', 0o755)
for n in WHOLE: write(f"tests/{n}_scenario.py", "")
base = commit("Start the fixture")
git("update-ref", "refs/remotes/origin/main", base)

# ---- a clean branch
branch("fix/clean"); write("docs/notes.md", "Two widgets.\n"); commit()
rc, out = run()
check("a clean branch passes", rc == 0 and "every check that ran passed" in out, (rc, out))
check("it names what it ran", "ran 4 check(s): commit and PR text, retired terms, tool text, suite pick" in out, out)
check("it names what is left: the whole-tree suites, the picked ones and the PR text",
      "left to you:" in out and f"run -T 600 {' '.join(WHOLE)}\n" in out and "run -T 600 alpha\n" in out and "--title and --body-file" in out, out)
check("without --suites no suite runs, and the pick is asked for the branch's own change", calls() == [f"select --base {base} --to HEAD"], calls())
(T / "body.md").write_text("Counts the widgets.\n")
rc, out = run("--title", "Count the widgets", "--body-file", "body.md")
check("with a title and a body nothing about PR text is left", rc == 0 and "--title and --body-file" not in out, (rc, out))
rc, out = run("--title", "Fix the zeppelin row", "--body-file", "body.md")
check("a PR title with a denied word fails", rc == 1 and line(out, "commit and PR text") == "FAIL", (rc, out))
(T / "bad.md").write_text("See the zeppelin.\n")
rc, out = run("--body-file", "bad.md")
check("a PR body with a denied word fails", rc == 1 and line(out, "commit and PR text") == "FAIL", (rc, out))
rc, out = run("--body-file", "no-such.md")
check("a body file that is not there fails", rc == 1 and line(out, "PR body file") == "FAIL", (rc, out))

# ---- each planted mistake
branch("fix/msg"); commit("Fix the zeppelin row")
rc, out = run()
check("a commit message with a denied word fails", rc == 1 and line(out, "commit and PR text") == "FAIL" and "FAILED: commit and PR text" in out, (rc, out))

branch("fix/word"); write("docs/notes.md", "A gizmo.\n"); commit()
rc, out = run()
check("a retired word fails, naming the line", rc == 1 and line(out, "retired terms") == "FAIL" and "docs/notes.md:1" in out, (rc, out))
check("the other checks still run after a failure", line(out, "tool text") == "ok  " and line(out, "suite pick") == "ok  ", out)

branch("fix/tool"); write("stackshot/web/server.py", SERVER.replace('"hello "', '"hi "')); commit()
rc, out = run()
check("a tool body changed with the snapshot unchanged fails", rc == 1 and line(out, "tool text") == "FAIL" and "server.py:hello" in out, (rc, out))
(T / "body.md").write_text("tool-text: unchanged: only the greeting inside moved\n")
rc, out = run("--body-file", "body.md")
check("the PR body's tool-text line lets it pass", rc == 0 and line(out, "tool text") == "ok  ", (rc, out))

# ---- the pick
branch("fix/pick"); commit()
rc, out = run(PICK="all")
check("a pick of every suite is said, not turned into a command", rc == 0 and "the pick is every suite" in out and " run -T 600 all" not in out, (rc, out))
rc, out = run(PICK_EXIT="1")
check("a pick that cannot be made fails", rc == 1 and line(out, "suite pick") == "FAIL" and "could not be made" in out, (rc, out))

# ---- could not run
os.remove(R / "tools/retired_terms.py")
rc, out = run()
check("a tool that is missing fails as could not run", rc == 1 and line(out, "retired terms") == "FAIL" and "could not run" in out, (rc, out))
branch("fix/base"); commit()
rc, out = run("--base", "origin/nothing")
check("no base: nothing is checked and the command fails", rc == 1 and "nothing was checked" in out, (rc, out))
rc, out = run("--suites", "--hook")
check("--suites with --hook is wrong usage", rc == 2, (rc, out))

# ---- --suites
branch("fix/suites"); commit()
rc, out = run("--suites")
check("--suites runs every whole-tree suite through the runner", rc == 0 and calls()[1:] == [f"suite {n}" for n in WHOLE], (rc, calls(), out))
check("and leaves only the other picked suites", "run -T 600 alpha\n" in out and "the whole-tree suites," not in out, out)
rc, out = run("--suites", BAD="neutral_install")
check("a failing suite fails the command and shows its failing check once", rc == 1 and line(out, "suite neutral_install") == "FAIL" and out.count("a planted check") == 1
      and line(out, "suite suitemap") == "ok  ", (rc, out))
os.remove(R / "tests/tool_text_scenario.py")
rc, out = run("--suites")
check("a whole-tree suite that is missing fails as could not run", rc == 1 and line(out, "suite tool_text") == "FAIL" and "could not run" in out, (rc, out))

# ---- the extra check
branch("fix/extra"); commit()
rc, out = run()
check("no extra check unless the setting holds one", "extra check" not in out, out)
rc, out = run(STACKSHOT_PREPUSH_EXTRA='echo "seen $PREPUSH_BASE"')
check("the extra check runs with the fork point", rc == 0 and f"seen {base}" in out, (rc, out))
rc, out = run(STACKSHOT_PREPUSH_EXTRA="exit 3")
check("a failing extra check fails the command", rc == 1 and line(out, "extra check") == "FAIL", (rc, out))
rc, out = run(STACKSHOT_PREPUSH_EXTRA="no-such-command-here")
check("an extra check that cannot run fails the command", rc == 1 and line(out, "extra check") == "FAIL", (rc, out))
rc, out = run("--hook", STACKSHOT_PREPUSH_EXTRA="exit 3")
check("--hook runs the retired-terms lint only", rc == 0 and "extra check" not in out and "tool text" not in out and not any(c.startswith("suite ") for c in calls()), (rc, calls(), out))

# ---- the pre-push hook
def push(sha, ref="refs/heads/fix/x"):
    r = subprocess.run([str(R / ".githooks/pre-push"), "origin", "none"], cwd=R, env=ENV, capture_output=True, text=True, timeout=120,
                       input=f"{ref} {sha} {ref} {'0' * 40}\n")
    return r.returncode, r.stdout + r.stderr

branch("fix/hook"); good = commit()
rc, out = push(good)
check("the hook passes a clean checked-out commit", rc == 0 and "ok   retired terms" in out and calls() == [], (rc, out))
write("docs/notes.md", "A gizmo.\n"); bad = commit()
rc, out = push(bad)
check("the hook refuses a push of the checked-out commit that holds a retired word", rc == 1 and "FAIL retired terms" in out and "tools/prepush --hook failed" in out, (rc, out))
rc, out = push(good)
check("another commit than the checked-out one: the hook says the lint was not run", rc == 0 and "lint was not run" in out and "retired terms" not in out.replace("retired-terms", ""), (rc, out))
rc, out = push("0" * 40)
check("a delete runs no lint", rc == 0 and "prepush" not in out, (rc, out))

if fails: print(f"{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: prepush, {len(ran)} checks"); sys.exit(0)
