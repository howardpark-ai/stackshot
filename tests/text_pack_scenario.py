#!/usr/bin/env python3
"""Scenario test for tools/text_check.py: the reading pack a reviewer reads before a tool-text change merges (no model call; no workflow job runs it). Fixture data only:
a throwaway repository. No network.

Covers: a change that touches nothing gives the `nothing to read` line; what the pack holds (the affected tools' snapshot text, the diff, the changed functions,
whether the PR changed the snapshot); the diff cut to its cap with the hunks of the changed tools kept first and the cut said; the command line (the `run` command that
called a model is gone); the real server's tool names and helpers; and that no workflow job calls a model or signs in to AWS (the model job, the OIDC sign-in and the
AWS variables are gone, the deterministic jobs stay) and that CONTRIBUTING and the README say so.

    tests/run-suite text_pack        → exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, os.path.join(STACK, "tools")); sys.path.insert(0, SCR)
import _scratch
T = pathlib.Path(_scratch.mkdtemp(prefix="textpacktest-"))
fails = []; ran = [0]
def check(name, cond, got=None):
    ran[0] += 1
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

import text_check as tc
import tool_text as tt


# ================================================================= the throwaway repository
R = T / "repo"; R.mkdir()
g = lambda *a: subprocess.run(["git", "-C", str(R), *a], capture_output=True, text=True, check=True).stdout.strip()
g("init", "-q", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
SERVER = '''
mcp = None
@mcp.tool(name="x", description="d")
def stackshot_x(a, b=1):
    """doc"""
    return _fmt(a)
@mcp.tool(name="y", description="d")
def stackshot_y(a):
    return a
def _fmt(a):
    # a comment
    return "mover: " + a
# pad 1
# pad 2
# pad 3
# pad 4
# pad 5
# pad 6
# pad 7
# pad 8
# pad 9
# pad 10
# pad 11
# pad 12
# pad 13
# pad 14
def _other(a):
    return a
'''
SNAP = {"format": 1, "tools": {"x": {"description": "Make an x. a: the thing. b: the count (default 1).", "parameters": {"a": {"type": "string", "required": True, "description": ""}, "b": {"type": "integer", "required": False, "default": 1, "description": "the count"}}},
                               "y": {"description": "Return y", "parameters": {}},
                               "get": {"description": "Read an item", "parameters": {}, "labels": ["mover:", "state:"]}}}
(R / "tests").mkdir(); (R / "server.py").write_text(SERVER); (R / "states.py").write_text("def words(i):\n    return 'state: ' + i\n")
(R / "tests" / "tool_text.snapshot.json").write_text(tt.render(SNAP))
g("add", "-A"); g("commit", "-qm", "base")
BASE = g("rev-parse", "HEAD")
def variant(name, server=None, snap=None, states=None):
    g("checkout", "-q", "-b", name, BASE)
    if server is not None: (R / "server.py").write_text(server)
    if snap is not None: (R / "tests" / "tool_text.snapshot.json").write_text(tt.render(snap))
    if states is not None: (R / "states.py").write_text(states)
    g("commit", "-qam", name, "--allow-empty")
    return g("rev-parse", "HEAD")
H_PARAM = variant("param", SERVER.replace("def stackshot_x(a, b=1):", "def stackshot_x(a, b=2, c=None):"))        # a tool function changed: x
H_HELPER = variant("helper", SERVER.replace('return "mover: " + a', 'return "keeper: " + a'))                      # an output helper: get, brief, create, update, complete
H_COMMENT = variant("comment", SERVER.replace("# a comment", "# another comment"))                                   # nothing relevant
H_OTHER = variant("other", SERVER.replace("def _other(a):\n    return a", "def _other(a):\n    return a + a"))        # not watched

H_SNAP = variant("withsnap", SERVER.replace("def stackshot_x(a, b=1):", "def stackshot_x(a, b=2, c=None):"), snap={**SNAP, "tools": {**SNAP["tools"], "x": {**SNAP["tools"]["x"], "description": "Make an x; c is new."}}})
def pack(head, **kw):
    return tc.build_pack(R, BASE, head, False, kw.get("max_diff", tc.MAX_DIFF), kw.get("max_text", tc.MAX_TEXT))
def nothing(head):
    try: pack(head); return None
    except tc.NothingToRead as e: return str(e)

# ================================================================= 1. nothing to read
check("a change that touches no tool function and no helper has nothing to read", "no tool function" in (nothing(H_COMMENT) or ""), nothing(H_COMMENT))
check("a function the gate does not watch has nothing to read either", nothing(H_OTHER) is not None, nothing(H_OTHER))

# ================================================================= 2. the pack
user = pack(H_PARAM)
check("a changed tool function: the pack names the tool, carries its snapshot text and the diff, and not the tools it does not reach",
      "Tools the change reaches: x\n" in user and "Make an x." in user and "Return y" not in user and "Read an item" not in user and "-def stackshot_x(a, b=1):" in user and "+def stackshot_x(a, b=2, c=None):" in user and "server.py:stackshot_x" in user, user[:900])
check("...and says the snapshot was not changed by the PR", "did not change tests/tool_text.snapshot.json" in user)
user = pack(H_HELPER)
check("a changed output helper reaches every tool that lists it (an absent one is said), here get, brief, create, update and complete", "Tools the change reaches: brief, complete, create, get, update\n" in user and "(not in the snapshot)" in user and "Read an item" in user and '+    return "keeper: " + a' in user, user[:700])
user = pack(H_SNAP)
check("the text is the head's: a PR that edits the snapshot is read against its own edit, and the pack says so", "Make an x; c is new." in user and "Make an x. a: the thing" not in user and "also changed tests/tool_text.snapshot.json" in user, user[:600])

# ================================================================= 3. size caps and the order hunks are kept in
BIG = SERVER.replace("def _other(a):\n    return a", "def _other(a):\n    return a\n" + "".join(f"def _filler{i}(a):\n    return {i} * a  # {'padding ' * 20}\n" for i in range(400)))
BIG = BIG.replace("def stackshot_x(a, b=1):", "def stackshot_x(a, b=2, c=None):")
H_BIG = variant("big", BIG)
full = tc.fit_diff(R, BASE, H_BIG, ["server.py:stackshot_x"], 10_000_000)
cut = tc.fit_diff(R, BASE, H_BIG, ["server.py:stackshot_x"], 3_000)
check("the unlimited diff is large and a capped one stays within the cap plus its notice", len(full) > 30_000 and len(cut) < 3_600, (len(full), len(cut)))
check("…the hunk that overlaps the changed tool function is kept first, and the cut is said", "b=2, c=None" in cut and "1 of 2 hunks omitted to fit the size limit" in cut, cut[-300:])
user = pack(H_BIG, max_diff=3_000, max_text=500)
check("the whole pack is bounded by the caps (diff, tool text) plus a fixed frame", len(user) < 3_000 + 500 + 1_500, len(user))
check("the tool text is cut at its cap and says so", "[tool text cut at 50 characters]" in tc.fit_text(SNAP, ["x"], 50) and "[tool text cut" not in tc.fit_text(SNAP, ["x"], 50_000))
_real = json.loads(pathlib.Path(STACK, "tests", "tool_text.snapshot.json").read_text(encoding="utf-8"))
_all = tc.fit_text(_real, sorted(_real["tools"]), tc.MAX_TEXT)
_total = len(tc.fit_text(_real, sorted(_real["tools"]), 10 ** 9))     # the uncut size: `_all` stops at the cap, so it cannot say how far past it the text is
_fix = (f"the {len(_real['tools'])} tools' text is {_total} characters as JSON, and the cap MAX_TEXT in tools/text_check.py is {tc.MAX_TEXT}. "
        "A branch behind main can fail on a total that main has already shrunk: merge main first with `gh pr update-branch <N>` (N is the PR's number), "
        "then run `tests/run-suite text_pack` again. Only when it still fails on a branch that has main in it is the text itself too long: shorten it, or raise MAX_TEXT")
check("the real snapshot, all tools together, fits under MAX_TEXT uncut (growth past it fails here, not as a cut-off tool a reader takes for missing)", len(_real["tools"]) > 5 and "[tool text cut" not in _all and len(_all) < tc.MAX_TEXT, _fix)
check("a deleted file or an unreadable revision gives an empty-diff note, not a crash", "no diff" in tc.fit_diff(R, "0" * 40, "1" * 40, ["server.py:stackshot_x"], 1000))

# ================================================================= 4. the command line
def cli(*a):
    return subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "text_check.py")), *a], capture_output=True, text=True)
r = cli("pack", "--repo", str(R), "--base", BASE, "--head", H_PARAM)
check("pack prints the tools, the text and the diff, exit 0", r.returncode == 0 and "Tools the change reaches: x" in r.stdout and "=== tool text" in r.stdout and "=== diff" in r.stdout, (r.returncode, r.stdout[:300], r.stderr))
r = cli("pack", "--repo", str(R), "--base", BASE, "--head", H_COMMENT)
check("pack on an untouched change prints the nothing-to-read line, exit 0", r.returncode == 0 and r.stdout.startswith("nothing to read:"), r.stdout)
r = cli("pack", "--repo", str(R), "--base", BASE, "--head", H_PARAM, "--exact")
check("--exact compares the base itself", r.returncode == 0 and "Tools the change reaches: x" in r.stdout, r.stdout)
r = cli("run", "--repo", str(R), "--base", BASE, "--head", H_PARAM)
check("the `run` command that called a model is gone", r.returncode != 0, r.stdout)
check("the tool_text.touched gate still reads through the shared changed_since (no change in what it says)", tt.touched(R, BASE, H_PARAM, "")[0] == 1 and tt.touched(R, BASE, H_COMMENT, "")[0] == 0, (tt.touched(R, BASE, H_PARAM, ""),))

# ================================================================= 5. tool names, the real HELPERS, the workflow and the docs
src = pathlib.Path(STACK, "server.py").read_text(encoding="utf-8")
names = tc.tool_names(src)
check("the real server's tool functions map to the snapshot's tool names (stackshot_get -> get ...), every one of them in the snapshot", names["stackshot_get"] == "get" and set(names.values()) <= set(_real["tools"]), sorted(set(names.values()) - set(_real["tools"])))
check("a changed shared item-line helper reaches the tools that list it", "get" in tc.affected_tools(["server.py:_mover_lines"], src, src) or tc.affected_tools(["server.py:_mover_lines"], src, src) != [], tc.affected_tools(["server.py:_mover_lines"], src, src))
import yaml
wf_text = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text(encoding="utf-8")
wf = yaml.safe_load(wf_text)
flows = "\n".join(p.read_text(encoding="utf-8") for p in sorted(pathlib.Path(STACK, ".github/workflows").glob("*.yml")))
check("the tests workflow keeps its deterministic jobs and has no model job", set(wf["jobs"]) == {"shards", "measure", "suites", "tool-text"}, sorted(wf["jobs"]))
check("no workflow signs in to AWS, asks for an OIDC token or reads an AWS or model variable or secret",
      not re.search(r"(?i)aws|bedrock|id-token|TOOL_TEXT_MODEL|SALA_REVIEW|anthropic", flows), sorted(set(re.findall(r"(?i)aws|bedrock|id-token|TOOL_TEXT_MODEL|SALA_REVIEW|anthropic", flows))))
check("no job needs the removed job, and the required check `suites` is still a job of the workflow", all("tool-text-model" not in str(j.get("needs", "")) for j in wf["jobs"].values()) and "suites" in wf["jobs"])
mq = pathlib.Path(STACK, ".github/mergequeue.toml").read_text(encoding="utf-8")
check("the merge queue requires `suites` and not the removed job", 'required = ["suites"]' in mq and "tool-text-model" not in mq)
check("the tool-text job still reads the PR body through env and runs the touched gate", "tools/tool_text.py touched" in wf_text and wf["jobs"]["tool-text"]["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}")
src_tc = pathlib.Path(STACK, "tools/text_check.py").read_text(encoding="utf-8")
check("text_check.py has no dependency block, no lock and no model or AWS call", "# /// script" not in src_tc and not pathlib.Path(STACK, "tools/text_check.py.lock").exists() and not re.search(r"(?i)boto3|bedrock|invoke_model", src_tc))
contrib = pathlib.Path(STACK, "CONTRIBUTING.md").read_text(encoding="utf-8"); readme = pathlib.Path(STACK, "README.md").read_text(encoding="utf-8")
check("CONTRIBUTING says the reviewer reads the text before merge, that small changes are skipped, and that text_check.py pack is run by hand and by no workflow",
      "reviewer subagent" in contrib and "Small changes are skipped" in contrib and "text_check.py pack" in contrib and "no workflow runs it" in contrib, None)
check("CONTRIBUTING and the README no longer describe a model check job or its variables", not re.search(r"tool-text-model: ignore|configure-aws|The model check", contrib + readme), None)

print(f"{len(fails)} FAILED of {ran[0]}" if fails else f"ok: text_pack scenario, {ran[0]} checks")
sys.exit(1 if fails else 0)
