"""Scenario test for the test launcher (tests/_launcher.py, used by tests/run-suite and tests/suitemap.py) - no server, no network, no real launcher.

A machine that wants its test runs sent elsewhere names a launcher program in a one-line config file; the plain command then runs through it. Here a
throwaway tree holds copies of run-suite, suitemap.py and _launcher.py beside small suites, a stub `uv` stands in for the shared test environment, and a stub
launcher records what it was called with and runs the command itself (or exits with a chosen code). Covers:
  * no config: a run is local and no launcher is called; a comment-only and an empty file mean none; a missing or not executable launcher is said
    once on stderr and the run is local, with the same output and exit code
  * the call: `<launcher> --git <mode> -- <the command as typed>`, from the caller's directory; `history` for the suites that read git history
    (and suitemap.py's select and audit), `snapshot` for the rest; the config file at its default place under XDG_CONFIG_HOME too
  * the launcher's exit code and the suite's pass through, and stdout is byte-identical to the local run; the stderr note names the launcher
    once and STACKSHOT_TEST_LAUNCHER_QUIET drops it
  * STACKSHOT_TEST_LAUNCHER overrides the file and, empty, switches the launcher off; STACKSHOT_TEST_LAUNCHED stops a second launch, and
    `suitemap.py run` calls run-suite once the launcher has run it without launching again
  * a launcher path with a space and arguments with quotes arrive exactly; suitemap.py's --help, warm, shard, merge and stamp stay local, and the
    subcommands that run or read the tree (run, measure, select, audit, list, plan) go through the launcher

    tests/run-suite launcher        → exit 0 / 1"""
import json, os, pathlib, shlex, shutil, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
import _scratch
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:900]}")

T = pathlib.Path(_scratch.mkdtemp(prefix="launcher-"))
R = T / "tree"; (R / "tests").mkdir(parents=True)
for f in ("run-suite", "_launcher.py", "suitemap.py"):
    shutil.copy(os.path.join(SCR, f), R / "tests" / f)
(R / "tests" / "run-suite").chmod(0o755)
subprocess.run(["git", "init", "-q", "-b", "main", str(R)], check=True)
SUITES = {"pass": ("print('ok: pass suite', sys.argv[1:])", 0), "fail": ("print('FAILED: fail suite', sys.argv[1:])", 1),
          "suitemap": ("print('ok: history suite')", 0), "clean_text": ("print('ok: history suite too')", 0),
          "env": ("print('launched=' + os.environ.get('STACKSHOT_TEST_LAUNCHED', ''))", 0)}
for name, (body, rc) in SUITES.items():
    (R / "tests" / f"{name}_scenario.py").write_text(f"import os, sys\n{body}\nsys.exit({rc})\n")
# a suitemap.py of its own would list `suitemap`, `clean_text`...: the throwaway tree needs the files tracked for `list`
subprocess.run(["git", "-C", str(R), "add", "-A"], check=True)

BIN = T / "bin"; BIN.mkdir()
(BIN / "uv").write_text('#!/bin/sh\nwhile [ $# -gt 0 ] && [ "$1" != env ]; do shift; done\nexec "$@"\n'); (BIN / "uv").chmod(0o755)   # the test environment's stand-in: runs what follows `env`
(BIN / "python").symlink_to(sys.executable)

REC = T / "rec.jsonl"
STUB_SRC = f"""#!{sys.executable}
import json, os, sys
rec = os.environ["STUB_REC"]
n = sum(1 for _ in open(rec)) if os.path.exists(rec) else 0
with open(rec, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "launched": os.environ.get("STACKSHOT_TEST_LAUNCHED")}}) + "\\n")
if n >= 4: sys.exit(99)                  # a launcher that keeps being called is a loop: stop it
if os.environ.get("STUB_EXIT"): sys.exit(int(os.environ["STUB_EXIT"]))
cmd = sys.argv[sys.argv.index("--") + 1:]
os.execvp(cmd[0], cmd)
"""
def stub(path):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(STUB_SRC); path.chmod(0o755); return path
STUB = stub(T / "stub")
CFG = T / "launcher.conf"

BASE = {k: v for k, v in os.environ.items() if not k.startswith(("STACKSHOT_TEST_", "STUB_", "SUITEMAP_", "COVERAGE_", "KEEP_SCRATCH"))}
BASE.update(PATH=f"{BIN}:{BASE.get('PATH', '/usr/bin')}", HOME=str(T / "home"), STUB_REC=str(REC), STACKSHOT_TEST_LAUNCHER_FILE=str(T / "no-such-file"),
            TMPDIR=str(T), XDG_CONFIG_HOME=str(T / "xdg"))
(T / "home").mkdir()

def run(cmd, env=None, cfg=None, cwd=None, exit_code=None):
    """(rc, stdout bytes, stderr text, [launcher calls]) of `cmd` in the throwaway tree; cfg is the config file's text (None: no file)"""
    if REC.exists(): REC.unlink()
    e = dict(BASE)
    if cfg is not None:
        CFG.write_text(cfg); e["STACKSHOT_TEST_LAUNCHER_FILE"] = str(CFG)
    if exit_code is not None: e["STUB_EXIT"] = str(exit_code)
    e.update(env or {})
    e = {k: v for k, v in e.items() if v is not None}      # None in env: the variable is left out
    p = subprocess.run(cmd, env=e, cwd=str(cwd or R), capture_output=True, timeout=120)
    calls = [json.loads(l) for l in REC.read_text().splitlines()] if REC.exists() else []
    return p.returncode, p.stdout, p.stderr.decode(errors="replace"), calls

RS = "tests/run-suite"; SM = ["python3", "tests/suitemap.py"]
NOTE = f"running through the test launcher: {shlex.quote(str(STUB))}"
LOCAL = {n: run([RS, n]) for n in ("pass", "fail")}
check("a run with no config is local: its suite ran, no launcher was called, nothing on stderr",
      LOCAL["pass"][:1] == (0,) and b"ok: pass suite" in LOCAL["pass"][1] and LOCAL["pass"][3] == [] and LOCAL["pass"][2] == "" and LOCAL["fail"][0] == 1, LOCAL)

# ---- the call
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n")
check("a config file: the launcher is called once with `--git snapshot -- <the command as typed>`, in the caller's directory",
      len(calls) == 1 and calls[0]["argv"] == ["--git", "snapshot", "--", RS, "pass"] and calls[0]["cwd"] == str(R.resolve()), calls)
check("…the stub ran the suite itself: same exit code and stdout bytes as the local run; the one stderr note names the launcher",
      rc == 0 and out == LOCAL["pass"][1] and err.strip() == NOTE, (rc, out, err))
check("…the launcher's side carries STACKSHOT_TEST_LAUNCHED=1", calls and calls[0]["launched"] == "1", calls)
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHER_QUIET": "1"})
check("STACKSHOT_TEST_LAUNCHER_QUIET=1 drops the stderr note and nothing else changes", rc == 0 and err == "" and out == LOCAL["pass"][1] and len(calls) == 1, (err, calls))
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHER_QUIET": "0"})
check("…a 0 there does not", err.strip() == NOTE, err)
for suite in ("suitemap", "clean_text"):
    rc, out, err, calls = run([RS, suite], cfg=f"{STUB}\n")
    check(f"the {suite} suite reads git history: `--git history`", len(calls) == 1 and calls[0]["argv"][:2] == ["--git", "history"] and rc == 0, (calls, err))
rc, out, err, calls = run([RS, "fail"], cfg=f"{STUB}\n")
check("a failing suite through the launcher: exit 1 and the same stdout as the local run", rc == 1 and out == LOCAL["fail"][1] and len(calls) == 1, (rc, out, calls))
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", exit_code=7)
check("the launcher's own exit code is the run's (a stub that exits 7 without running anything)", rc == 7 and out == b"" and len(calls) == 1, (rc, out, calls))
xdg = T / "xdg" / "stackshot"; xdg.mkdir(parents=True); (xdg / "test-launcher").write_text(f"# the launcher\n\n{STUB}\n")
rc, out, err, calls = run([RS, "pass"], env={"STACKSHOT_TEST_LAUNCHER_FILE": None})
check("no STACKSHOT_TEST_LAUNCHER_FILE: the file is <XDG_CONFIG_HOME>/stackshot/test-launcher, comments and blank lines skipped",
      len(calls) == 1 and calls[0]["argv"][:2] == ["--git", "snapshot"], (calls, err))
(xdg / "test-launcher").unlink()
(T / "home" / ".config" / "stackshot").mkdir(parents=True); (T / "home" / ".config" / "stackshot" / "test-launcher").write_text(f"{STUB}\n")
rc, out, err, calls = run([RS, "pass"], env={"XDG_CONFIG_HOME": "", "STACKSHOT_TEST_LAUNCHER_FILE": None})
check("…and with XDG_CONFIG_HOME empty, ~/.config/stackshot/test-launcher", len(calls) == 1, (calls, err))
shutil.rmtree(T / "home" / ".config")

# ---- env override and off switch
other = stub(T / "other" / "stub2")
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHER": str(other)})
check("STACKSHOT_TEST_LAUNCHER overrides the file's line", len(calls) == 1 and rc == 0 and shlex.quote(str(other)) in err and shlex.quote(str(STUB)) not in err, (calls, err))
rc, out, err, calls = run([RS, "pass"], env={"STACKSHOT_TEST_LAUNCHER": str(other)})
check("…and works with no file at all", len(calls) == 1 and rc == 0, (calls, err))
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHER": ""})
check("STACKSHOT_TEST_LAUNCHER set to an empty string disables the launcher for the run: local, no note", calls == [] and rc == 0 and out == LOCAL["pass"][1] and err == "", (calls, err))

# ---- the loop guard
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHED": "1"})
check("STACKSHOT_TEST_LAUNCHED=1 never launches again: a local run, no note", calls == [] and rc == 0 and out == LOCAL["pass"][1] and err == "", (calls, err))
rc, out, err, calls = run([RS, "env"], cfg=f"{STUB}\n")
check("a run through the launcher sees STACKSHOT_TEST_LAUNCHED=1 in its suite", b"launched=1" in out and len(calls) == 1, (out, calls))
rc, out, err, calls = run(SM + ["run", "pass"], cfg=f"{STUB}\n")
check("suitemap.py run goes through the launcher once and its run-suite call for the suite stays on the far side (one launcher call in all)",
      rc == 0 and len(calls) == 1 and b"ok: pass suite" in out and calls[0]["argv"] == ["--git", "snapshot", "--", "python3", "tests/suitemap.py", "run", "pass"], (rc, out, err, calls))

# ---- a launcher that cannot be used, and an empty config
BAD = "/nonexistent-dir/launcher"
rc, out, err, calls = run([RS, "pass"], cfg=f"{BAD}\n")
check("a launcher that is not there: one stderr line, a local run with the same stdout and exit code",
      rc == 0 and out == LOCAL["pass"][1] and err.strip() == f"test launcher {BAD} is not executable: running here", (rc, err))
plain = T / "plain"; plain.write_text("#!/bin/sh\nexit 0\n")
rc, out, err, calls = run([RS, "fail"], cfg=f"{plain}\n")
check("a launcher without the execute bit: the same line, and a failing suite's exit code stays",
      rc == 1 and out == LOCAL["fail"][1] and err.strip() == f"test launcher {plain} is not executable: running here", (rc, err))
rc, out, err, calls = run(SM + ["run", "pass"], cfg=f"{BAD}\n")
check("suitemap.py run with a launcher that is not there: the line is said once for the whole run, the suite still runs",
      rc == 0 and b"ok: pass suite" in out and err.count("is not executable") == 1, (rc, err))
for label, text in (("a comment-only file", "# nothing here\n   # nor here\n"), ("an empty file", ""), ("a file of blank lines", "\n  \n")):
    rc, out, err, calls = run([RS, "pass"], cfg=text)
    check(f"{label} means no launcher: local, silent", calls == [] and rc == 0 and out == LOCAL["pass"][1] and err == "", (calls, err))
rc, out, err, calls = run([RS, "pass"], cfg=f"{STUB}\nnot-used\n")
check("only the first line of the file counts", len(calls) == 1 and "not-used" not in err, (calls, err))

# ---- words
spaced = stub(T / "dir with space" / "my stub")
line = shlex.join([str(spaced), "x y", "it's", 'say "hi"'])
rc, out, err, calls = run([RS, "pass", "a b", "it's", "-k", "foo"], cfg=f"{line}\n")
check("a launcher path with a space, and words with a space, a single and a double quote, arrive exactly (POSIX splitting), then the command as typed with its own arguments exactly",
      len(calls) == 1 and calls[0]["argv"] == ["x y", "it's", 'say "hi"', "--git", "snapshot", "--", RS, "pass", "a b", "it's", "-k", "foo"] and rc == 0, (calls, err))
rc, out, err, calls = run([RS, "pass"], cfg=f'{STUB} "unclosed\n')
check("a line that cannot be split is said as not executable and the run is local", calls == [] and rc == 0 and "is not executable: running here" in err, (calls, err))
rc, out, err, calls = run([RS, "pass"], cfg=f'{STUB} "$(touch {T}/injected)" \'`touch {T}/injected`\' $HOME\n')
check("a launcher line is words only: no command substitution or expansion, and they reach the launcher as they are",
      not (T / "injected").exists() and len(calls) == 1 and calls[0]["argv"][:3] == [f"$(touch {T}/injected)", f"`touch {T}/injected`", "$HOME"], (calls, err))

# ---- suitemap.py
rc, out, err, calls = run(SM + ["--help"], cfg=f"{STUB}\n")
check("suitemap.py --help stays local", rc == 0 and calls == [] and b"usage" in out.lower(), (rc, calls))
rc, out, err, calls = run(SM + ["run", "--bogus"], cfg=f"{STUB}\n")
check("…and so does a bad command line", rc == 2 and calls == [], (rc, calls))
rc, out, err, calls = run(SM, cfg=f"{STUB}\n")
check("…and no subcommand", rc == 2 and calls == [], (rc, calls))
TREE_ARGS = {"run": ["pass"], "measure": ["--map", "m.json", "pass"], "measure --prev": ["--map", "m.json", "--prev", "old.json", "pass"], "select": ["--map", "m.json"], "audit": ["--old", "a", "--new", "b", "--to", "c"],
             "list": [], "plan": ["--of", "3"]}
for label, extra in TREE_ARGS.items():
    sub = label.split()[0]
    mode = "snapshot" if (sub, extra) == ("run", ["pass"]) else "history"       # only a run of suites that read no history can do with the files alone
    py = ["uv", "run", "--locked", "--only-group", "tests", "python"] if sub == "measure" else ["python3"]
    rc, out, err, calls = run(SM + [sub, *extra], cfg=f"{STUB}\n", exit_code=5)
    check(f"suitemap.py {label} goes through the launcher with `--git {mode}`, as typed, and takes the launcher's exit code",
          rc == 5 and len(calls) == 1 and calls[0]["argv"] == ["--git", mode, "--", *py, "tests/suitemap.py", sub, *extra] and calls[0]["cwd"] == str(R.resolve()), (rc, calls, err))
for sub, extra, mode in (("run", ["suitemap"], "history"), ("run", ["pass", "clean_text"], "history"), ("run", [], "history"), ("measure", ["--map", "m", "suitemap"], "history"),
                         ("plan", ["--of", "2", "--only", "pass"], "history")):
    rc, out, err, calls = run(SM + [sub, *extra], cfg=f"{STUB}\n", exit_code=5)
    check(f"suitemap.py {sub} {' '.join(extra)}: `--git {mode}`", len(calls) == 1 and calls[0]["argv"][:2] == ["--git", mode], (calls, err))
for sub, extra in (("warm", []), ("shard", ["--of", "2", "--index", "0"]), ("merge", ["--map", "m", "s"]), ("stamp", ["--map", "m", "--sha", "x"])):
    rc, out, err, calls = run(SM + [sub, *extra], cfg=f"{STUB}\n", exit_code=5)
    check(f"suitemap.py {sub} stays local", calls == [], (rc, calls, err))
rc, out, err, calls = run(SM + ["list"])
check("suitemap.py with no config is local: no launcher called, the tree's suites listed, nothing on stderr", calls == [] and rc == 0 and out.decode().split() == sorted(SUITES) and err == "", (rc, out, err, calls))
rc, out, err, calls = run(SM + ["list"], cfg=f"{STUB}\n", env={"STACKSHOT_TEST_LAUNCHER": ""})
check("suitemap.py list with the launcher switched off lists the tree's suites here",
      calls == [] and rc == 0 and out.decode().split() == sorted(SUITES), (rc, out, err))

# ---- a tree with no repository: suites() must say so, not list nothing (a run of nothing passes)
NOGIT = T / "nogit"; (NOGIT / "tests").mkdir(parents=True); shutil.copy(R / "tests" / "suitemap.py", NOGIT / "tests"); shutil.copy(R / "tests" / "_launcher.py", NOGIT / "tests")
(NOGIT / "tests" / "pass_scenario.py").write_text("print('ok')\n")
for sub, extra in (("list", []), ("plan", ["--of", "3"])):
    rc, out, err, calls = run(["python3", "tests/suitemap.py", sub, *extra], cwd=NOGIT, env={"SUITEMAP_ROOT": str(NOGIT), "GIT_CEILING_DIRECTORIES": str(T)})
    check(f"suitemap.py {sub} in a tree with no repository fails loudly: exit 2, one line on stderr, nothing on stdout",
          rc == 2 and out == b"" and err.count("no suites found") == 1 and err.count("\n") == 1, (rc, out, err))

# ---- the example launcher of docs/development.md, extracted from it, with stand-in rsync and ssh: every argument reaches the far side as it was typed
doc = (pathlib.Path(SCR).parent / "docs" / "development.md").read_text(encoding="utf-8")
blocks = [b for b in doc.split("```sh\n")[1:] if b.startswith("#!/bin/bash\n# /usr/local/bin/test-launcher")]
check("docs/development.md holds the example launcher", len(blocks) == 1, len(blocks))
if blocks:
    ex = T / "example-launcher"; ex.write_text(blocks[0].split("```")[0]); ex.chmod(0o755)
    FAR = T / "far"; (FAR / "work" / "tree").mkdir(parents=True); EB = T / "ebin"; EB.mkdir()
    (EB / "rsync").write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$STUB_RSYNC"\nexit ${STUB_RSYNC_RC:-0}\n'); (EB / "rsync").chmod(0o755)     # STUB_RSYNC_RC: the copy's exit status
    (EB / "ssh").write_text('#!/bin/sh\necho called >> "$STUB_SSH"\nshift\ncd "$STUB_FAR" && exec dash -c "$*"\n'); (EB / "ssh").chmod(0o755)     # ssh hands the words to the far login shell as one string; dash, the plainest one, stands in for it
    SHOW = [sys.executable, "-c", "import json, os, sys; print(json.dumps([os.environ.get('STACKSHOT_TEST_LAUNCHED'), sys.argv[1:]]))"]
    ARGS = ["it's", "x;echo INJECTED", "$HOME", "*", "", 'say "hi"', "a b", "-x", "--", "back\\slash", "multi\nline", "\ud55c\uae00", "\ud55c\uae00 it's\nx"]
    RSYNC = T / "rsync.log"
    EENV = {"PATH": f"{EB}:{BASE['PATH']}", "STUB_FAR": str(FAR), "STUB_RSYNC": str(RSYNC), "STUB_SSH": str(T / "ssh.log")}
    for mode in ("snapshot", "history"):
        RSYNC.write_text("")
        rc, out, err, calls = run([str(ex), "--git", mode, "--", *SHOW, *ARGS], env=EENV)
        check(f"the docs' example launcher ({mode}): arguments with a quote, a semicolon, $HOME, a glob, an empty word, spaces, dashes, a backslash, a newline and Korean words arrive exactly through a dash far login shell, the loop guard with them",
              rc == 0 and json.loads(out) == ["1", ARGS] and len(out.decode().splitlines()) == 1, (rc, out, err))
        check(f"…and it syncs the tree {'without' if mode == 'snapshot' else 'with'} .git in {mode} mode", ("--exclude=.git" in RSYNC.read_text()) == (mode == "snapshot"), RSYNC.read_text())
    for mode in ("snapshot", "history"):
        MARK = T / f"far-ran-{mode}"; (T / "ssh.log").write_text("")
        rc, out, err, calls = run([str(ex), "--git", mode, "--", sys.executable, "-c", "import sys; open(sys.argv[1], 'w').close()", str(MARK)], env={**EENV, "STUB_RSYNC_RC": "23"})
        check(f"the docs' example launcher ({mode}): a copy that fails (rsync exits 23) is never run on: the command does not run, ssh is not called, the exit code is 23",
              rc == 23 and not MARK.exists() and (T / "ssh.log").read_text() == "", (rc, MARK.exists(), (T / "ssh.log").read_text(), err))
    RSYNC.write_text("")
    rc, out, err, calls = run([str(ex), "--", *SHOW, "1"], env=EENV)
    check("…and with no --git it is a snapshot run", rc == 0 and json.loads(out) == ["1", ["1"]] and "--exclude=.git" in RSYNC.read_text(), (rc, out, err))

print(("ok" if not fails else "FAILED") + f": launcher scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
