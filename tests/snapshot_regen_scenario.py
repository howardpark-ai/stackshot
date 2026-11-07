"""Scenario test for tools/snapshot_regen.py, the helper release.sh calls when a PR conflicts with main.

Two PRs that both change tool text conflict on tests/tool_text.snapshot.json, a generated file, and on nothing else. The helper merges main into the PR head in a temporary
worktree and decides: the conflicted paths are exactly the snapshot -> take main's copy, `tools/tool_text.py update`, `check`, commit the merge, push it to the PR branch (plain
push); anything else -> decline, push nothing, and release.sh fails as it always did. No GitHub, no network, no real tool_text.py: every case builds a throwaway git world (a bare
"origin", the PR author's clone, a stub tools/tool_text.py that writes the snapshot from tools_src/*.txt) in a scratch folder, and runs the helper as release.sh does.

Covers: a conflict in the snapshot alone is mended and pushed (the origin branch is the merge commit, two parents: the head and main; the snapshot is the union of both sides'
text and passes `check`; the commit message says so; a plain push, origin's main and other branches untouched; the checkout's own files, HEAD and branch untouched; no worktree
and no temp folder left; a commit made with no git identity of its own gets the release identity); the snapshot plus another path in conflict, another path alone, a clean merge and
a head that already contains main are declined with the reason on stdout and nothing pushed; a branch that moved on origin since --head is refused by the plain push (declined, the
newer commit still there); `update` that fails, `check` that fails after it, `update` that changes more than the snapshot: declined, nothing pushed; a bad branch name or head, a
head not in the checkout: declined before anything is made; a SIGTERM while `update` runs ends the helper (exit 143) and takes the worktree and the temp folder with it.

    tests/run-suite snapshot_regen        → exit 0 / 1"""
import glob, json, os, pathlib, signal, subprocess, sys, time
import _scratch
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
HELPER = os.path.join(STACK, "tools", "snapshot_regen.py")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ROOT = pathlib.Path(_scratch.mkdtemp(prefix="snapregen-"))
HOME = ROOT / "home"; HOME.mkdir()
ENV = {"PATH": os.environ["PATH"], "HOME": str(HOME), "XDG_CONFIG_HOME": str(HOME / ".config"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
AUTHOR = ["-c", "user.name=Test Author", "-c", "user.email=author@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

def g(cwd, *args, ok=True):
    r = subprocess.run(["git", "-C", str(cwd), *AUTHOR, *args], capture_output=True, text=True, env=ENV, timeout=60)
    if ok and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} in {cwd}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()

STUB_TOOL_TEXT = r'''#!/usr/bin/env python3
"""a stand-in for tools/tool_text.py: the snapshot is the text of tools_src/*.txt. Knobs (environment): REGEN_TEST_UPDATE_FAIL, REGEN_TEST_CHECK_FAIL, REGEN_TEST_STRAY (update also changes a
tracked file it must not), REGEN_TEST_HANG=<marker file> (update writes the marker and waits)."""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "tests/tool_text.snapshot.json"
def live(): return json.dumps({p.stem: p.read_text().strip() for p in sorted((ROOT / "tools_src").glob("*.txt"))}, indent=1, sort_keys=True) + "\n"
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "update":
    if os.environ.get("REGEN_TEST_HANG"):
        Path(os.environ["REGEN_TEST_HANG"]).write_text("started"); time.sleep(25)
    if os.environ.get("REGEN_TEST_UPDATE_FAIL"): print("update: cannot import the server", file=sys.stderr); sys.exit(1)
    SNAP.write_text(live())
    if os.environ.get("REGEN_TEST_STRAY"): (ROOT / "src/other.py").write_text("stray\n")
elif cmd == "check":
    if os.environ.get("REGEN_TEST_CHECK_FAIL") or SNAP.read_text() != live(): print("check: the snapshot differs from the live text", file=sys.stderr); sys.exit(1)
else:
    sys.exit(2)
'''

def update(wc):   # the author's own refresh of the snapshot, as `python3 tools/tool_text.py update` would
    subprocess.run([sys.executable, "tools/tool_text.py", "update"], cwd=wc, check=True, env=ENV, capture_output=True)

def world(name, pr_other=False, main_other=False, main_tool=True, main_only_docs=False):
    """origin (bare) and the PR author's clone `work`. The PR branch agent/topic changes tools_src/a.txt (and the snapshot, and src/other.py when pr_other); main then changes tools_src/b.txt
    (and the snapshot; src/other.py when main_other). main_tool False: main changes only README (no conflict at all); main_only_docs is the same with the snapshot untouched."""
    w = ROOT / name; w.mkdir()
    origin, wc, tmp = w / "origin.git", w / "work", w / "tmp"; tmp.mkdir()
    g(w, "init", "--bare", "--quiet", "-b", "main", str(origin))
    g(w, "clone", "--quiet", str(origin), str(wc))
    g(wc, "checkout", "--quiet", "-b", "main")
    (wc / "tools").mkdir(); (wc / "tools/tool_text.py").write_text(STUB_TOOL_TEXT); (wc / "tools_src").mkdir(); (wc / "tests").mkdir(); (wc / "src").mkdir()
    (wc / "tools_src/a.txt").write_text("a0\n"); (wc / "tools_src/b.txt").write_text("b0\n"); (wc / "src/other.py").write_text("one\ntwo\nthree\n"); (wc / "README.md").write_text("readme\n")
    update(wc); g(wc, "add", "-A"); g(wc, "commit", "--quiet", "-m", "base"); g(wc, "push", "--quiet", "origin", "main")
    base0 = g(wc, "rev-parse", "HEAD")
    g(wc, "checkout", "--quiet", "-b", "agent/topic")
    (wc / "tools_src/a.txt").write_text("a1\n")
    if pr_other: (wc / "src/other.py").write_text("PR\ntwo\nthree\n")
    update(wc); g(wc, "add", "-A"); g(wc, "commit", "--quiet", "-m", "the PR's change"); g(wc, "push", "--quiet", "origin", "agent/topic")
    head = g(wc, "rev-parse", "HEAD")
    g(wc, "checkout", "--quiet", "main")
    if main_tool:
        (wc / "tools_src/b.txt").write_text("b1\n")
        if main_other: (wc / "src/other.py").write_text("MAIN\ntwo\nthree\n")
        update(wc)
    else:
        (wc / "README.md").write_text("readme, changed on main\n")
    g(wc, "add", "-A"); g(wc, "commit", "--quiet", "-m", "main moves"); g(wc, "push", "--quiet", "origin", "main")
    return {"name": name, "dir": w, "origin": origin, "work": wc, "tmp": tmp, "head": head, "base0": base0, "main": g(wc, "rev-parse", "HEAD")}

def regen(wd, head=None, branch="agent/topic", extra=None, extra_args=()):
    env = {**ENV, "TMPDIR": str(wd["tmp"]), **(extra or {})}
    return subprocess.run([sys.executable, HELPER, "--repo", str(wd["work"]), f"--branch={branch}", "--head", head or wd["head"], *extra_args], capture_output=True, text=True, env=env, timeout=180)

def origin_ref(wd, ref): return g(wd["origin"], "rev-parse", "--verify", "--quiet", ref, ok=False)
def left_over(wd): return sorted(glob.glob(str(wd["tmp"] / "stackshot-regen-*")))
def worktrees(wd): return [l for l in g(wd["work"], "worktree", "list", "--porcelain").splitlines() if l.startswith("worktree ")]
def one_line(r): return len(r.stdout.strip().splitlines()) == 1

check("the helper's file is there and parses", os.path.exists(HELPER) and subprocess.run([sys.executable, "-m", "py_compile", HELPER], capture_output=True).returncode == 0)

# ---- 1. a conflict in the snapshot alone is mended and pushed
wd = world("snap-only")
work_head = g(wd["work"], "rev-parse", "HEAD"); work_branch = g(wd["work"], "branch", "--show-current"); work_status = g(wd["work"], "status", "--porcelain")
trial = ROOT / "snap-only-trial"; subprocess.run(["git", "clone", "--quiet", str(wd["origin"]), str(trial)], env=ENV, check=True, capture_output=True)
g(trial, "checkout", "--quiet", "agent/topic")
g(trial, "merge", "--no-commit", "--no-ff", "origin/main", ok=False)
check("the setup is a real conflict (a plain merge of main into the PR conflicts, on the snapshot only)",
      g(trial, "diff", "--name-only", "--diff-filter=U") == "tests/tool_text.snapshot.json", g(trial, "status", "--short"))
r = regen(wd)
new = origin_ref(wd, "refs/heads/agent/topic")
check("a conflict in the snapshot alone: exit 0 and one stdout line, `pushed <sha>`, the sha being the new tip of the PR's branch on origin", r.returncode == 0 and one_line(r) and r.stdout.strip() == f"pushed {new}" and new != wd["head"], (r.returncode, r.stdout, r.stderr))
parents = g(wd["origin"], "rev-list", "--parents", "-n", "1", new).split()[1:]
check("the pushed commit is a merge of the PR head and main (that parent order), a plain push on top of the head", parents == [wd["head"], wd["main"]], parents)
check("the commit message says what it is", g(wd["origin"], "log", "-1", "--format=%s", new) == "Merge main into agent/topic; regenerate the tool-text snapshot", g(wd["origin"], "log", "-1", "--format=%B", new))
snap = json.loads(g(wd["origin"], "show", f"{new}:tests/tool_text.snapshot.json"))
check("the snapshot in the merge is regenerated from the merged text: both sides' changes (a1 from the PR, b1 from main), no conflict marker",
      snap == {"a": "a1", "b": "b1"} and "<<<<<<<" not in g(wd["origin"], "show", f"{new}:tests/tool_text.snapshot.json"), snap)
check("the merged tree holds both sides' source text", g(wd["origin"], "show", f"{new}:tools_src/a.txt") == "a1" and g(wd["origin"], "show", f"{new}:tools_src/b.txt") == "b1")
check("the commit was made with the release identity (the checkout and the box have none of their own here)", g(wd["origin"], "log", "-1", "--format=%an <%ae>", new) == "stackshot release <release@stackshot.invalid>", g(wd["origin"], "log", "-1", "--format=%an <%ae>", new))
check("origin's main and every other branch are untouched", origin_ref(wd, "refs/heads/main") == wd["main"] and g(wd["origin"], "for-each-ref", "--format=%(refname)").splitlines() == ["refs/heads/agent/topic", "refs/heads/main"])
check("the checkout it was given is untouched (same HEAD, same branch, clean), and no worktree or temp folder is left",
      g(wd["work"], "rev-parse", "HEAD") == work_head and g(wd["work"], "branch", "--show-current") == work_branch and g(wd["work"], "status", "--porcelain") == work_status
      and len(worktrees(wd)) == 1 and not left_over(wd), (worktrees(wd), left_over(wd)))
check("the helper's details go to stderr, not stdout", "snapshot_regen:" in r.stderr and "snapshot_regen:" not in r.stdout, r.stderr)
# the push really was a plain one: the old head is the new commit's first parent, so the branch moved forward (a force would also have moved it; the moved-branch case below shows the refusal)
check("the new tip descends from the old head (fast-forward)", subprocess.run(["git", "-C", str(wd["origin"]), "merge-base", "--is-ancestor", wd["head"], new], env=ENV).returncode == 0)

# ---- 2. other paths in the conflict: declined, nothing pushed
for nm, kw, expect in (("snap-and-other", dict(pr_other=True, main_other=True), "the conflict is not only the snapshot: src/other.py, tests/tool_text.snapshot.json"),
                       ("other-only", dict(pr_other=True, main_other=True, main_tool=False), None)):
    wd = world(nm, **kw)
    if nm == "other-only":   # main changes src/other.py but not the tool text: the snapshot does not conflict, src/other.py does
        g(wd["work"], "checkout", "--quiet", "main"); (wd["work"] / "src/other.py").write_text("MAIN\ntwo\nthree\n"); g(wd["work"], "add", "-A"); g(wd["work"], "commit", "--quiet", "-m", "main edits other"); g(wd["work"], "push", "--quiet", "origin", "main")
        expect = "the conflict is not only the snapshot: src/other.py"
    r = regen(wd)
    check(f"{nm}: declined (exit 1, one stdout line) with the paths named, so release.sh fails as before", r.returncode == 1 and one_line(r) and r.stdout.strip() == f"declined: {expect}", (r.returncode, r.stdout, r.stderr))
    check(f"{nm}: nothing pushed (the PR's branch is where it was), no worktree or temp folder left", origin_ref(wd, "refs/heads/agent/topic") == wd["head"] and len(worktrees(wd)) == 1 and not left_over(wd), (worktrees(wd), left_over(wd)))

# ---- 3. a clean merge, and a head that already contains main: not this tool's job
wd = world("clean", main_tool=False)
r = regen(wd)
check("a merge with no conflict at all is declined (GitHub's update-branch would have worked: something else is wrong), nothing pushed",
      r.returncode == 1 and one_line(r) and "has no conflict" in r.stdout and origin_ref(wd, "refs/heads/agent/topic") == wd["head"] and not left_over(wd), (r.returncode, r.stdout, r.stderr))
wd = world("uptodate")
r = regen(wd, head=wd["main"])
check("a head that already contains main's tip is declined: there is nothing to merge", r.returncode == 1 and one_line(r) and "already: there is nothing to merge" in r.stdout and not left_over(wd), (r.stdout, r.stderr))

# ---- 4. the branch moved on origin since --head: the plain push is refused, the author's newer commit stays
wd = world("moved")
other = wd["dir"] / "other"; g(wd["dir"], "clone", "--quiet", str(wd["origin"]), str(other)); g(other, "checkout", "--quiet", "agent/topic")
(other / "README.md").write_text("the author pushed again\n"); g(other, "add", "-A"); g(other, "commit", "--quiet", "-m", "author pushes"); g(other, "push", "--quiet", "origin", "agent/topic")
moved = origin_ref(wd, "refs/heads/agent/topic")
r = regen(wd)
check("the PR's branch moved since --head: the push is refused (declined), the author's commit is still the tip, no worktree or temp folder left",
      r.returncode == 1 and one_line(r) and "was refused or failed" in r.stdout and origin_ref(wd, "refs/heads/agent/topic") == moved and moved != wd["head"] and len(worktrees(wd)) == 1 and not left_over(wd), (r.stdout, r.stderr, moved))

# ---- 5. the regeneration itself goes wrong
for nm, knob, expect in (("update-fails", "REGEN_TEST_UPDATE_FAIL", "tool_text.py update failed: update: cannot import the server"),
                         ("check-fails", "REGEN_TEST_CHECK_FAIL", "tool_text.py check fails on the regenerated snapshot: check: the snapshot differs from the live text"),
                         ("update-strays", "REGEN_TEST_STRAY", "tool_text.py update changed more than the snapshot: src/other.py")):
    wd = world(nm)
    r = regen(wd, extra={knob: "1"})
    check(f"{nm}: declined with the reason, nothing pushed, no worktree or temp folder left",
          r.returncode == 1 and one_line(r) and r.stdout.strip() == f"declined: {expect}" and origin_ref(wd, "refs/heads/agent/topic") == wd["head"] and len(worktrees(wd)) == 1 and not left_over(wd), (r.returncode, r.stdout, r.stderr))

# ---- 6. inputs it will not act on
wd = world("inputs")
for nm, kw, expect in (("a branch with `..`", dict(branch="agent/../main"), "is not one this tool pushes to"), ("a branch that starts with a dash", dict(branch="-f"), "is not one this tool pushes to"),
                       ("a head that is not a sha", dict(head="HEAD"), "is not a commit sha"), ("a sha the checkout does not have", dict(head="0123456789abcdef0123456789abcdef01234567"), "is not among the commits this checkout has")):
    r = regen(wd, **kw)
    check(f"{nm}: declined before anything is made", r.returncode == 1 and one_line(r) and expect in r.stdout and not left_over(wd) and origin_ref(wd, "refs/heads/agent/topic") == wd["head"], (r.returncode, r.stdout, r.stderr))
r = regen(wd, extra_args=("--base", "origin/nothing"))
check("a base the checkout cannot read: declined", r.returncode == 1 and one_line(r) and "cannot read origin/nothing" in r.stdout, (r.stdout, r.stderr))

# ---- 7. a SIGTERM while `update` runs: the helper ends (143) and takes its worktree and folder with it (a signal to our own child, by its pid)
wd = world("sigterm")
marker = wd["dir"] / "hang-marker"
p = subprocess.Popen([sys.executable, HELPER, "--repo", str(wd["work"]), "--branch", "agent/topic", "--head", wd["head"]], env={**ENV, "TMPDIR": str(wd["tmp"]), "REGEN_TEST_HANG": str(marker)},
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    for _ in range(600):
        if marker.exists() or p.poll() is not None: break
        time.sleep(0.1)
    mid = (len(left_over(wd)), len(worktrees(wd)))
    if p.poll() is None: p.send_signal(signal.SIGTERM)
    try: out, err = p.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate()
finally:
    if p.poll() is None: p.kill(); p.wait()
check("while `update` runs the temporary worktree and its folder exist (the case is real)", marker.exists() and mid == (1, 2), (marker.exists(), mid))
check("a SIGTERM there: exit 143, nothing pushed, and the worktree, its registration and the temp folder are gone",
      p.returncode == 143 and origin_ref(wd, "refs/heads/agent/topic") == wd["head"] and len(worktrees(wd)) == 1 and not left_over(wd), (p.returncode, worktrees(wd), left_over(wd), err[-300:]))

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
