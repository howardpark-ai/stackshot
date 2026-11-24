#!/usr/bin/env python3
"""Scenario test for tools/text_check.py: the reading pack a reviewer reads before a tool-text change merges (no model call; no workflow job runs it). Fixture data only:
a throwaway repository. No network.

Covers: a change that touches nothing gives the `nothing to read` line; what the pack holds (the affected tools' snapshot text, the diff, the changed functions,
whether the PR changed the snapshot); the diff cut to its cap with the hunks of the changed tools kept first and the cut said; the tool text cut at tool boundaries (whole
tools kept in sorted order, the ones left out named with where their text is and how to raise the limit, nothing cut mid-tool; no tool, a limit of 0 or 1 and a negative limit; sizes counted in
characters, not bytes, on non-ASCII text) and the cap checked per tool (the biggest at most 90% of it), never as the total of the real snapshot's twelve tools; the command line (the `run` command that
called a model is gone); the real server's tool names and helpers; and that no workflow job calls a model or signs in to AWS (the model job, the OIDC sign-in and the
AWS variables are gone, the deterministic jobs stay) and that CONTRIBUTING, the README and the docs say so.

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
def W(rel, text):
    (R / rel).parent.mkdir(parents=True, exist_ok=True); (R / rel).write_text(text)
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
GET = '''
def _fmt(a):
    # a comment
    return "mover: " + a
'''      # the output helper `_fmt`, in the file the real HELPERS table lists it in (web/tools/get.py)
SNAP = {"format": 1, "tools": {"x": {"description": "Make an x. a: the thing. b: the count (default 1).", "parameters": {"a": {"type": "string", "required": True, "description": ""}, "b": {"type": "integer", "required": False, "default": 1, "description": "the count"}}},
                               "y": {"description": "Return y", "parameters": {}},
                               "get": {"description": "Read an item", "parameters": {}, "labels": ["mover:", "state:"]}}}
(R / "tests").mkdir(); W("stackshot/web/server.py", SERVER); W("stackshot/web/tools/get.py", GET); W("stackshot/model/states.py", "def words(i):\n    return 'state: ' + i\n")
(R / "tests" / "tool_text.snapshot.json").write_text(tt.render(SNAP))
g("add", "-A"); g("commit", "-qm", "base")
BASE = g("rev-parse", "HEAD")
def variant(name, server=None, snap=None, states=None, get=None):
    g("checkout", "-q", "-b", name, BASE)
    if server is not None: W("stackshot/web/server.py", server)
    if snap is not None: (R / "tests" / "tool_text.snapshot.json").write_text(tt.render(snap))
    if states is not None: W("stackshot/model/states.py", states)
    if get is not None: W("stackshot/web/tools/get.py", get)
    g("commit", "-qam", name, "--allow-empty")
    return g("rev-parse", "HEAD")
H_PARAM = variant("param", SERVER.replace("def stackshot_x(a, b=1):", "def stackshot_x(a, b=2, c=None):"))        # a tool function changed: x
H_HELPER = variant("helper", get=GET.replace('return "mover: " + a', 'return "keeper: " + a'))                      # an output helper: get, brief, create, update, complete
H_COMMENT = variant("comment", get=GET.replace("# a comment", "# another comment"))                                   # nothing relevant
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
      "Tools the change reaches: x\n" in user and "Make an x." in user and "Return y" not in user and "Read an item" not in user and "-def stackshot_x(a, b=1):" in user and "+def stackshot_x(a, b=2, c=None):" in user and "stackshot/web/server.py:stackshot_x" in user, user[:900])
check("...and says the snapshot was not changed by the PR", "did not change tests/tool_text.snapshot.json" in user)
user = pack(H_HELPER)
check("a changed output helper reaches every tool that lists it (an absent one is said), here get, brief, create, update and complete", "Tools the change reaches: brief, complete, create, get, update\n" in user and "(not in the snapshot)" in user and "Read an item" in user and '+    return "keeper: " + a' in user, user[:700])
user = pack(H_SNAP)
check("the text is the head's: a PR that edits the snapshot is read against its own edit, and the pack says so", "Make an x; c is new." in user and "Make an x. a: the thing" not in user and "also changed tests/tool_text.snapshot.json" in user, user[:600])

# a tool's text file (web/tools/text/<module>.md): its change reaches the tools of its module, the shared file's every tool, and its hunks lead the diff
g("checkout", "-q", "-b", "textfile", BASE); W(f"{tt.TEXT_DIR}/x.md", "## description x\nMake an x.\n"); g("add", "-A"); g("commit", "-qm", "textfile")
H_TEXT = g("rev-parse", "HEAD")
user = pack(H_TEXT)
check("a new text file reaches the tool of its name, and its lines are in the diff", "Tools the change reaches: x\n" in user and f"{tt.TEXT_DIR}/x.md:text" in user and "+Make an x." in user, user[:700])
check("a text file reaches the tools its module registers when the module is given (update.md: update and confirm)", tc.affected_tools([f"{tt.TEXT_DIR}/update.md:text"], "", "", {"update": {"update", "confirm"}}) == ["confirm", "update"], tc.affected_tools([f"{tt.TEXT_DIR}/update.md:text"], "", "", {"update": {"update", "confirm"}}))
check("the shared text file reaches every tool", set(tc.affected_tools([f"{tt.TEXT_SHARED}:text"], "", "")) >= set(tt.HELPERS), tc.affected_tools([f"{tt.TEXT_SHARED}:text"], "", ""))
check("a text file that names no tool and no module reaches none", tc.affected_tools([f"{tt.TEXT_DIR}/nothing.md:text"], "", "") == [])

# ================================================================= 3. size caps and the order hunks are kept in
BIG = SERVER.replace("def _other(a):\n    return a", "def _other(a):\n    return a\n" + "".join(f"def _filler{i}(a):\n    return {i} * a  # {'padding ' * 20}\n" for i in range(400)))
BIG = BIG.replace("def stackshot_x(a, b=1):", "def stackshot_x(a, b=2, c=None):")
H_BIG = variant("big", BIG)
full = tc.fit_diff(R, BASE, H_BIG, ["stackshot/web/server.py:stackshot_x"], 10_000_000)
cut = tc.fit_diff(R, BASE, H_BIG, ["stackshot/web/server.py:stackshot_x"], 3_000)
check("the unlimited diff is large and a capped one stays within the cap plus its notice", len(full) > 30_000 and len(cut) < 3_600, (len(full), len(cut)))
check("…the hunk that overlaps the changed tool function is kept first, and the cut is said", "b=2, c=None" in cut and "1 of 2 hunks omitted to fit the size limit" in cut, cut[-300:])
user = pack(H_BIG, max_diff=3_000, max_text=500)
check("the whole pack is bounded by the caps (diff, tool text) plus a fixed frame", len(user) < 3_000 + 500 + 1_500, len(user))
check("the tool text is cut at its cap and says so, naming the tool, when even the first tool alone is longer than the cap", "[tool text cut at 50 characters: x]" in tc.fit_text(SNAP, ["x"], 50) and "[tool text cut" not in tc.fit_text(SNAP, ["x"], 50_000))
_real = json.loads(pathlib.Path(STACK, "tests", "tool_text.snapshot.json").read_text(encoding="utf-8"))
_RT = sorted(_real["tools"])
_alone = {t: len(tc.fit_text(_real, [t], 10 ** 9)) for t in _RT}               # each tool's own size as JSON, uncut
_big = max(_alone, key=_alone.get)
_total = sum(_alone.values())

# the cap bounds one pack, not the twelve tools together: so what is checked is each tool alone, never their sum
def _notice(text):
    return "[tool text cut" in text or "[tools left out" in text
check("every one of the real snapshot's tools fits the cap alone, uncut (a tool whose own text passes MAX_TEXT is cut off in its pack: trim that tool's text, in stackshot/web/tools/text/<module>.md, then run `python3 tools/tool_text.py update`)",
      len(_RT) > 5 and all(_alone[t] <= tc.MAX_TEXT for t in _RT),
      {t: f"{_alone[t]} characters alone, the cap MAX_TEXT in tools/text_check.py is {tc.MAX_TEXT}" for t in _RT if _alone[t] > tc.MAX_TEXT})
_room = tc.MAX_TEXT - _alone[_big]
def _holds_one(size, cap):
    """The cap only has to hold ONE tool uncut: the biggest at most 90% of it (a bound of half the cap was a cliff that got the cap raised again)."""
    return 10 * size <= 9 * cap
check("the bound on the biggest tool: 90% of the cap passes exactly, one character more fails, and 60% (over half) passes, so half the cap is no bound",
      _holds_one(90, 100) and not _holds_one(91, 100) and _holds_one(99_000, 165_000) and not _holds_one(148_501, 165_000) and _holds_one(60, 100) and _holds_one(148_500, 165_000))
check(f"the biggest tool of the real snapshot is at most 90% of the cap, so the cap holds one tool uncut with some room (measured: {_big} is {_alone[_big]} of {tc.MAX_TEXT} characters, {100 * _alone[_big] / tc.MAX_TEXT:.1f}%, room {_room})",
      _holds_one(_alone[_big], tc.MAX_TEXT),f"{_big} is {_alone[_big]} characters alone, {100 * _alone[_big] / tc.MAX_TEXT:.1f}% of the cap MAX_TEXT ({tc.MAX_TEXT}), room {_room}; the most allowed is {9 * tc.MAX_TEXT // 10}: trim {_big}'s text (stackshot/web/tools/text/<module>.md, then `python3 tools/tool_text.py update`)")
check("the pack of any one tool of the real snapshot is uncut and names nothing left out", all(not _notice(tc.fit_text(_real, [t], tc.MAX_TEXT)) and json.loads(tc.fit_text(_real, [t], tc.MAX_TEXT)) == {t: _real["tools"][t]} for t in _RT))

def _parts(text):
    """(the JSON part parsed, the tools named as left out, the notice lines) of a pack's tool text."""
    body, _, rest = text.partition("\n[")
    notes = ("[" + rest).split("\n") if rest else []
    left = [n for line in notes if line.startswith("[tools left out to fit ") for n in line.rstrip("]").split(": ", 1)[1].split(", ")]
    try:
        return json.loads(body), left, notes
    except ValueError:                                         # a tool cut in the middle: the kept part is no JSON; the checks fail on it, they do not crash
        return {"<the kept part is not valid JSON>": body[-60:]}, left, notes

# a tool that grows by 50,000 characters: here the biggest, which sorts last, so it is the one left out of the all-tools pack and the others stay whole
_grown = {**_real, "tools": {**_real["tools"], _big: {**_real["tools"][_big], "description": _real["tools"][_big]["description"] + "x" * 50_000}}}
_kept, _left, _notes = _parts(tc.fit_text(_grown, _RT, tc.MAX_TEXT))
check(f"{_big} (the biggest tool) grown by 50,000 characters: the pack of all tools does not fail, every other tool is in it whole, and the tool left out is named by the one line",
      _total + 50_000 > tc.MAX_TEXT and _left == [_big] and _kept == {t: _real["tools"][t] for t in _RT if t != _big} and len(_notes) == 1, (_left, sorted(_kept), _notes))
check(f"{_big} grown by 50,000 characters is still read in a pack of its own, uncut", not _notice(tc.fit_text(_grown, [_big], tc.MAX_TEXT)) and json.loads(tc.fit_text(_grown, [_big], tc.MAX_TEXT)) == {_big: _grown["tools"][_big]})
_bad = []
for _t in _RT:                                                                # 50,000 characters more in any one tool: whole tools only, each tool in the JSON or named, none both, none neither
    _g = {**_real, "tools": {**_real["tools"], _t: {**_real["tools"][_t], "description": _real["tools"][_t]["description"] + "x" * 50_000}}}
    try:
        _k, _l, _n = _parts(tc.fit_text(_g, _RT, tc.MAX_TEXT))
    except ValueError as e:
        _bad.append((_t, "not valid JSON", str(e))); continue
    if sorted(set(_k) | set(_l)) != _RT or set(_k) & set(_l) or any(_k[o] != _g["tools"][o] for o in _k) or len(_n) != (1 if _l else 0):
        _bad.append((_t, sorted(_k), _l))
    if any(tc.fit_text(_g, [o], tc.MAX_TEXT) != tc.fit_text(_real, [o], tc.MAX_TEXT) for o in _RT if o != _t):
        _bad.append((_t, "another tool's own pack changed"))
check("50,000 more characters in any one tool: the pack of all tools holds whole tools only (valid JSON), names the ones it leaves out, and no other tool's own pack changes", not _bad, _bad)

# the cut order on a fixture: whole tools, sorted, the left-out ones named, valid JSON for the rest
def _NOTE(limit, names):
    """The left-out notice as a reader sees it: one line that also says where the omitted text is and how to raise the limit."""
    return f"\n[tools left out to fit {limit} characters (their text is in tests/tool_text.snapshot.json; --max-text-chars raises the limit for one run): {names}]"
def _fx(**sizes):
    return {"format": 1, "tools": {n: {"description": "d" * k, "parameters": {}} for n, k in sizes.items()}}
_f1 = _fx(alpha=200, bravo=200, delta=200, gamma=200, hotel=200)
_lim = len(tc.fit_text(_f1, ["alpha", "bravo"], 10 ** 9))
_out = tc.fit_text(_f1, ["hotel", "bravo", "gamma", "alpha", "delta"], _lim)       # handed in unsorted
_k, _l, _n = _parts(_out)
check("a small limit on a fixture keeps whole tools in sorted order whatever order they are handed in (alpha, bravo), and names the others, sorted, in one line",
      list(_k) == ["alpha", "bravo"] and _k == {n: _f1["tools"][n] for n in ("alpha", "bravo")} and _l == ["delta", "gamma", "hotel"] and _out.endswith(_NOTE(_lim, "delta, gamma, hotel")) and _out.count("\n[") == 1, _out[-300:])
check("the limit is inclusive: at exactly the pack's size there is no notice, one character less leaves the last tool out", not _notice(tc.fit_text(_f1, ["alpha", "bravo"], _lim)) and _parts(tc.fit_text(_f1, ["alpha", "bravo"], _lim - 1))[1] == ["bravo"])
_f2 = _fx(alpha=10, bravo=5000, charlie=10)
_k, _l, _n = _parts(tc.fit_text(_f2, ["alpha", "bravo", "charlie"], 1000))
check("a tool too long to fit is left out whole and named, and the small tools after it are still kept (no tool is cut in the middle: the kept part is valid JSON of whole entries)", list(_k) == ["alpha", "charlie"] and _k["alpha"] == _f2["tools"]["alpha"] and _k["charlie"] == _f2["tools"]["charlie"] and _l == ["bravo"] and "[tool text cut" not in "".join(_n), (_k, _l, _n))
_out = tc.fit_text(_f2, ["bravo"], 1000)
check("a single tool longer than the limit alone is the one tool cut inside, with the notice naming it", _out.startswith('{\n "bravo"') and _out.endswith("\n[tool text cut at 1000 characters: bravo]") and len(_out) < 1000 + 60 and "left out" not in _out, _out[-120:])
_out = tc.fit_text(_f2, ["bravo", "charlie"], 1000)
_k, _l, _n = _parts(tc.fit_text(_f2, ["bravo", "charlie"], 1000))
check("...but with a tool that fits beside it, the long one is left out whole and named, never cut (the cut is for a pack where nothing fits)", list(_k) == ["charlie"] and _l == ["bravo"] and "[tool text cut" not in "".join(_n), (_k, _l, _n))
_out = tc.fit_text(_fx(bravo=5000, delta=5000), ["delta", "bravo"], 1000)
check("when nothing fits, the first tool (sorted) is the one cut, naming it, and the other is named as left out", _out.endswith("\n[tool text cut at 1000 characters: bravo]" + _NOTE(1000, "delta")), _out[-160:])
check("a pack that fits is the sorted JSON alone: no notice, the same text as before", tc.fit_text(_f1, ["gamma", "alpha"], 10 ** 6) == json.dumps({n: _f1["tools"][n] for n in ("alpha", "gamma")}, indent=1, sort_keys=True, ensure_ascii=False) and tc.fit_text(_f1, [], 10) == "{}")
check("a tool not in the snapshot is read as `(not in the snapshot)` and counts as a whole tool", _parts(tc.fit_text(_f1, ["alpha", "nosuch"], 10 ** 6))[0]["nosuch"] == "(not in the snapshot)")

# no tool at all: the empty object, and a limit of 0 or 1 never raises (a negative limit counts as 0, never a slice from the end)
check("no tool and a limit that holds `{}`: the empty object, no notice", tc.fit_text(_f1, [], 2) == "{}" and tc.fit_text(_f1, [], 10 ** 6) == "{}")
for _lm, _head in ((0, ""), (1, "{")):
    try:
        _o = tc.fit_text(_f1, [], _lm)
    except Exception as e:                                     # the old IndexError at left.pop(0)
        _o = f"raised {type(e).__name__}: {e}"
    check(f"no tool and a limit of {_lm}: no error, `{{}}` cut at the limit and the cut said (the same text as before the pack was cut at tool boundaries)", _o == _head + f"\n[tool text cut at {_lm} characters]", _o)
for _lm in (-1, -2, -50):
    try:
        _o = tc.fit_text(_f1, [], _lm)
        _o2 = tc.fit_text(_f1, ["alpha", "bravo"], _lm)
    except Exception as e:
        _o = _o2 = f"raised {type(e).__name__}: {e}"
    check(f"a negative limit ({_lm}) counts as 0: nothing is sliced from the end of the text, with no tool or with tools",
          _o == "\n[tool text cut at 0 characters]" and _o2 == "\n[tool text cut at 0 characters: alpha]" + _NOTE(0, "bravo") and _o2 == tc.fit_text(_f1, ["alpha", "bravo"], 0), (_o, _o2))
_o = tc.fit_text(_f1, ["alpha", "bravo"], 1)
check("a limit of 1 with tools: the first tool cut at one character, the other named as left out", _o == "{\n[tool text cut at 1 characters: alpha]" + _NOTE(1, "bravo"), _o)

# the left-out notice is one line, says where the omitted text is and that --max-text-chars raises the limit
_o = tc.fit_text(_f1, ["alpha", "bravo", "delta"], _lim)
_nl = [x for x in _o.split("\n") if x.startswith("[tools left out")]
check("the left-out notice is a single line that names the snapshot file holding the omitted text and the --max-text-chars switch, and still ends in the tools' names",
      len(_nl) == 1 and "tests/tool_text.snapshot.json" in _nl[0] and "--max-text-chars" in _nl[0] and _nl[0].endswith("): delta]") and _o.count("\n[") == 1, _nl)
check("--max-text-chars raises the limit for a run: the pack text_check builds with a higher cap holds the tool the default left out",
      "delta" not in _parts(tc.fit_text(_f1, ["alpha", "bravo", "delta"], _lim * 2))[1] and "delta" in _parts(tc.fit_text(_f1, ["alpha", "bravo", "delta"], _lim * 2))[0])

# the size is counted in characters, never bytes: accented Latin letters (two bytes) and CJK Han characters (three bytes), written as escapes in this source
_acc = "café crème brûlée naïve"
_han = "中文 漢字 今日"
_u1 = {"format": 1, "tools": {"alpha": {"description": _acc, "parameters": {}}, "bravo": {"description": _han, "parameters": {}}, "charlie": {"description": "plain", "parameters": {}}}}
_both = tc.fit_text(_u1, ["alpha", "bravo"], 10 ** 9)
_nc, _nb = len(_both), len(_both.encode("utf-8"))
check("the fixture is non-ASCII: the two tools hold the accented and the CJK characters as themselves, and their size in bytes is over their size in characters", _acc in _both and _han in _both and "\\u" not in _both and _nb > _nc + 10, (_nc, _nb))
_o = tc.fit_text(_u1, ["alpha", "bravo"], _nc)
check("a limit placed exactly on the characters of the pack keeps both non-ASCII tools whole with no notice (a pack sized in bytes would leave one out)", _o == _both and not _notice(_o), (_nc, _nb, _o[-200:]))
_o = tc.fit_text(_u1, ["alpha", "bravo"], _nc - 1)
check("one character less leaves the last tool out and names it, the kept part is the first tool whole", _parts(_o)[0] == {"alpha": _u1["tools"]["alpha"]} and _parts(_o)[1] == ["bravo"], _o[-200:])
_o = tc.fit_text(_u1, ["alpha", "bravo", "charlie"], _nc)
_pk, _pl, _pn = _parts(_o)
check("a limit on the characters of two tools, with a third that does not fit: the two non-ASCII tools are kept and the third is named", set(_pk) == {"alpha", "bravo"} and _pl == ["charlie"], (sorted(_pk), _pl))
_o = tc.fit_text(_u1, ["bravo"], len(tc.fit_text(_u1, ["bravo"], 10 ** 9)) - 3)
check("a single non-ASCII tool cut inside is cut at the limit in characters: the kept text is exactly `limit` characters (not fewer, as a byte count would cut it)", _o.partition("\n[")[0] == tc.fit_text(_u1, ["bravo"], 10 ** 9)[:len(_o.partition("\n[")[0])] and len(_o.partition("\n[")[0]) == len(tc.fit_text(_u1, ["bravo"], 10 ** 9)) - 3, len(_o.partition("\n[")[0]))

# a total far over the cap with each tool within it: no failure, the pack says what it left out
_f3 = _fx(**{f"tool{i:02d}": 20_000 for i in range(12)})
_k, _l, _n = _parts(tc.fit_text(_f3, sorted(_f3["tools"]), tc.MAX_TEXT))
check("twelve tools of 20,000 characters (240,000, far over the cap, each far under it): the pack is within the cap, whole, and names the tools it left out",
      len(tc.fit_text(_f3, sorted(_f3["tools"]), tc.MAX_TEXT).partition("\n[")[0]) <= tc.MAX_TEXT and sorted(_k) + _l == sorted(_f3["tools"]) and 0 < len(_l) < 12 and all(_k[t] == _f3["tools"][t] for t in _k), (len(_k), _l))
# ...and through build_pack, on a branch whose snapshot is that large
H_FAT = variant("fat", get=GET.replace('return "mover: " + a', 'return "keeper: " + a'), snap={"format": 1, "tools": {n: {"description": "d" * 50_000, "parameters": {}} for n in ("complete", "create", "get", "update")}})
user = pack(H_FAT)
_k, _l, _n = _parts(user.split("=== tool text (the snapshot at the head) ===\n", 1)[1].split("\n\n=== diff", 1)[0])
check("a pack through build_pack on a tool-text change whose five tools total over the cap does not fail: whole tools, the rest named", "Tools the change reaches: brief, complete, create, get, update\n" in user and set(_k) | set(_l) == {"brief", "complete", "create", "get", "update"} and _l and "(not in the snapshot)" in user and f"to fit {tc.MAX_TEXT} characters" in user, (sorted(_k), _l))
check("a deleted file or an unreadable revision gives an empty-diff note, not a crash", "no diff" in tc.fit_diff(R, "0" * 40, "1" * 40, ["stackshot/web/server.py:stackshot_x"], 1000))

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
src = "\n".join(pathlib.Path(STACK, f).read_text(encoding="utf-8") for f in ("stackshot/web/server.py", *tt.TOOL_FILES))   # the tools are registered in web/tools/*.py
names = tc.tool_names(src)
check("the real server's tool functions map to the snapshot's tool names (stackshot_get -> get ...), every one of them in the snapshot", names["stackshot_get"] == "get" and set(names.values()) <= set(_real["tools"]), sorted(set(names.values()) - set(_real["tools"])))
check("a changed shared item-line helper reaches the tools that list it", "get" in tc.affected_tools(["stackshot/web/tools/notes.py:_mover_lines"], src, src) or tc.affected_tools(["stackshot/web/tools/notes.py:_mover_lines"], src, src) != [], tc.affected_tools(["stackshot/web/tools/notes.py:_mover_lines"], src, src))
import yaml
wf_text = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text(encoding="utf-8")
wf = yaml.safe_load(wf_text)
flows = "\n".join(p.read_text(encoding="utf-8") for p in sorted(pathlib.Path(STACK, ".github/workflows").glob("*.yml")))
check("the tests workflow keeps its deterministic jobs and has no model job", set(wf["jobs"]) == {"proof", "shards", "measure", "suites", "tool-text"}, sorted(wf["jobs"]))
check("no workflow signs in to AWS, asks for an OIDC token or reads an AWS or model variable or secret",
      not re.search(r"(?i)aws|bedrock|id-token|TOOL_TEXT_MODEL|SALA_REVIEW|anthropic", flows), sorted(set(re.findall(r"(?i)aws|bedrock|id-token|TOOL_TEXT_MODEL|SALA_REVIEW|anthropic", flows))))
check("no job needs the removed job, and the required check `suites` is still a job of the workflow", all("tool-text-model" not in str(j.get("needs", "")) for j in wf["jobs"].values()) and "suites" in wf["jobs"])
mq = pathlib.Path(STACK, ".github/mergequeue.toml").read_text(encoding="utf-8")
check("the merge queue requires `suites` and not the removed job", 'required = ["suites"]' in mq and "tool-text-model" not in mq)
check("the tool-text job still reads the PR body through env and runs the touched gate", "tools/tool_text.py touched" in wf_text and wf["jobs"]["tool-text"]["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}")
src_tc = pathlib.Path(STACK, "tools/text_check.py").read_text(encoding="utf-8")
check("text_check.py has no dependency block, no lock and no model or AWS call", "# /// script" not in src_tc and not pathlib.Path(STACK, "tools/text_check.py.lock").exists() and not re.search(r"(?i)boto3|bedrock|invoke_model", src_tc))
contrib = pathlib.Path(STACK, "CONTRIBUTING.md").read_text(encoding="utf-8"); import _docs; readme = pathlib.Path(STACK, "README.md").read_text(encoding="utf-8") + _docs.pages()
check("CONTRIBUTING says the reviewer reads the text before merge, that small changes are skipped, and that text_check.py pack is run by hand and by no workflow",
      "reviewer subagent" in contrib and "Small changes are skipped" in contrib and "text_check.py pack" in contrib and "no workflow runs it" in contrib, None)
check("CONTRIBUTING, the README and the docs no longer describe a model check job or its variables", not re.search(r"tool-text-model: ignore|configure-aws|The model check", contrib + readme), None)

print(f"{len(fails)} FAILED of {ran[0]}" if fails else f"ok: text_pack scenario, {ran[0]} checks")
sys.exit(1 if fails else 0)
