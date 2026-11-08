"""Scenario test for the tool-text gates (tools/tool_text.py, whatschanged.py) — fixture data, a throwaway config, a throwaway git repo; no live store, no network.

Covers: the committed snapshot (tests/tool_text.snapshot.json) is exactly what the server registers now (a tool's name, parameters, description as served, the
labels of the lines it returns, the connector's instructions and resources) — and when it is not, the failure prints a readable diff and the one command that
refreshes it; the snapshot is stable (sorted keys, normalised whitespace, the same twice); the label scan on small sources (what counts as a label and what
does not); every output helper the list names exists; the touched-tool check on a throwaway repository (a changed body with the snapshot unchanged fails unless
the PR body says `tool-text: unchanged: <reason>`; the snapshot changing with it, a comment, a docstring, a non-helper, passes; the fork point, not the moved
tip, is the base); the summary of a change (tools added or removed, parameters added, removed, renamed or changed, description and label changes); the mark
of a release (the first start keeps a copy and seeds the history, a start with the text unchanged records nothing, one with a change records the generated
line, which the brief carries for 7 days and then not).

    tests/run-suite tool_text        → exit 0 / 1"""
import copy, datetime as dt, json, os, pathlib, subprocess, sys, tempfile, textwrap
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, os.path.join(STACK, "tools")); sys.path.insert(0, STACK)
import _scratch
SCRATCH = pathlib.Path(_scratch.mkdtemp(prefix="tooltexttest-base-")); tempfile.tempdir = str(SCRATCH); os.environ["TMPDIR"] = str(SCRATCH)   # every scratch file of this run, and of the commands it starts, goes under BASE; the last check asserts BASE is empty again
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

import tool_text as tt
live = tt.live_snapshot()              # imports server.py on a throwaway config (state under its temp dir)
import ast; from stackshot.web import server; from stackshot.web import whatschanged as wc
kept = tt.stored()

# ================================================================= 1. the snapshot is the live text
rep = tt.check_report(live, kept)
check("the committed snapshot is what the server registers now (otherwise: the diff and `python3 tools/tool_text.py update`)", not rep, "\n".join(rep[:30]))
raw = (pathlib.Path(STACK) / tt.SNAPSHOT_REL).read_text(encoding="utf-8")
check("the file is the rendering of its own data: sorted keys, two-space indent, one trailing newline", raw == tt.render(json.loads(raw)), raw[-200:])
check("a second live reading is the same text (the snapshot does not depend on the run)", tt.render(tt.live_snapshot()) == tt.render(live))
names = {t.name for t in __import__("asyncio").run(server.mcp.list_tools())}
check("every registered tool is in the snapshot, and nothing else", set(live["tools"]) == names and {"get", "brief", "create", "update", "message", "complete"} <= names, (sorted(live["tools"]), sorted(names)))
check("every description is one normalised line and starts as served (the rules lead for all but rules)", all(" ".join(t["description"].split()) == t["description"] and t["description"] for t in live["tools"].values()) and all(t["description"].startswith("If your session did not load") for n, t in live["tools"].items() if n != "rules"))
cr = live["tools"]["create"]["parameters"]
check("a parameter carries its type, whether it is required, its description and its default: create's subject is required, sender and mover are not", cr["subject"] == {"type": "string", "required": True, "description": ""} and cr["sender"]["required"] is False and cr["sender"]["default"] == "" and "mover" in cr and cr["options"]["type"] == "array<object> | string | null", cr.get("subject"))
check("the connector's instructions and its rules resource are in the snapshot", live["instructions"].startswith("stackshot") and "stackshot://rules" in live["resources"], live["resources"])
lab = {t: live["tools"][t].get("labels") for t in tt.LABELLED}
check("get, brief, create, update, message and complete carry labels, the other tools none", all(k in live["tools"][t] for t in tt.LABELLED for k in ("labels",)) and not any("labels" in v for n, v in live["tools"].items() if n not in tt.LABELLED), {t: len(v or []) for t, v in lab.items()})
want_get = {"mover:", "then:", "state:", "next:", "needs:", "ask:", "after:", "observers:", "model:", "outcome:", "reason:", "wait failed:", "undelivered notices:", "project:", "due:", "wake:", "priority:"}
check("get's labels are the fixed prefixes of the lines it returns (mover:, then:, state:, next:, needs: …), read from every branch of the helpers", want_get <= set(lab["get"]), sorted(want_get - set(lab["get"])))
check("the notice-only labels are not required of create, update and complete, but project: and reason: (which an item also has) still are", {"ruling:", "sender:"} <= tt.get_only_labels() and not ({"project:", "reason:"} & tt.get_only_labels()) and {"project:", "reason:"} <= set(lab["create"]) & set(lab["update"]) & set(lab["complete"]), sorted(tt.get_only_labels()))
check("owner: is not a label (the creator is no line at all), and create, update and complete return get's lines", "owner:" not in lab["get"] and set(lab["get"]) - tt.get_only_labels() <= set(lab["create"]) and set(lab["get"]) - tt.get_only_labels() <= set(lab["update"]) and set(lab["get"]) - tt.get_only_labels() <= set(lab["complete"]), (sorted(set(lab["get"]) - set(lab["create"])),))
check("brief adds its own labels (mover gone:, pages owed:); message returns no labelled line", {"mover gone:", "waits no watcher owns:", "pages owed:"} <= set(lab["brief"]) and lab["message"] == [], lab["brief"])
names_ok = tt.labels_by_tool()
check("every output helper in HELPERS is defined (a renamed or removed one fails loudly, naming the list)", set(names_ok) == set(tt.HELPERS) and names_ok["get"] == lab["get"], None)
tools_ast = tt.tool_functions(ast.parse((pathlib.Path(STACK) / "stackshot" / "web" / "server.py").read_text(encoding="utf-8")))
check("the touched check finds every registered tool function by its @mcp.tool decorator", len(tools_ast) == len(names) and "stackshot_brief" in tools_ast and "stackshot_complete" in tools_ast, sorted(tools_ast))

# ================================================================= 2. a failing check: readable, with the refresh command
chg = copy.deepcopy(live)
chg["tools"]["get"]["description"] = chg["tools"]["get"]["description"].replace("Read one item by id", "Fetch one item by id", 1)
chg["tools"]["create"]["parameters"]["sender"]["required"] = True
del chg["tools"]["create"]["parameters"]["mover"]
chg["tools"]["create"]["parameters"]["lead"] = {"type": "string", "required": False, "description": "who leads"}
chg["tools"]["get"]["labels"] = [x for x in chg["tools"]["get"]["labels"] if x != "then:"] + ["holder:"]
chg["tools"]["extra"] = {"description": "new", "parameters": {}}
del chg["tools"]["rules"]
chg["instructions"] += " More."
rep = tt.check_report(chg, kept)
text = "\n".join(rep)
check("a differing registry fails with the command that refreshes the snapshot", f"python3 tools/tool_text.py update" in text and rep[0].startswith("The tools' text differs"), text[:300])
check("…and a readable diff: the words that changed in a description, with their neighbours", "[-Read-] {+Fetch+} one item by id" in text, text[:1500])
check("…naming each: tool get, parameter lead ADDED, parameter mover REMOVED, sender required, labels gone then:, new holder:, tool extra ADDED, tool rules REMOVED, the instructions",
      all(x in text for x in ("tool get:", "parameter lead: ADDED", "parameter mover: REMOVED", "parameter sender: required false -> true", "labels gone: then:", "labels new: holder:", "tool extra: ADDED", "tool rules: REMOVED", "instructions changed")), text[:2500])
check("a missing snapshot says so and gives the same command", "python3 tools/tool_text.py update" in "\n".join(tt.check_report(live, None)))
check("the same text again reads as no difference", tt.check_report(copy.deepcopy(live), copy.deepcopy(live)) == [])

# ---- the command itself: check passes on the committed file, fails on a changed copy, update writes a copy that check then passes
T = pathlib.Path(_scratch.mkdtemp(prefix="tooltexttest-"))
run = lambda *a, **kw: subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "tool_text.py")), *a], capture_output=True, text=True, cwd=kw.get("cwd", T), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
r = run("check")
check("`tool_text.py check` exits 0 on the committed snapshot", r.returncode == 0 and r.stdout.startswith("ok:"), (r.returncode, r.stdout[-300:], r.stderr[-300:]))
bad = T / "bad.json"; d = json.loads(raw); d["tools"]["brief"]["description"] += " Changed."; d["tools"]["get"]["labels"].append("zzz:"); bad.write_text(tt.render(d))
r = run("check", "--snapshot", str(bad))
check("…and exits 1 on a changed copy, printing the diff and the refresh command", r.returncode == 1 and "tool brief:" in r.stdout and "labels gone: zzz:" in r.stdout and "python3 tools/tool_text.py update" in r.stdout, (r.returncode, r.stdout[-600:]))
r = run("update", "--snapshot", str(bad)); r2 = run("check", "--snapshot", str(bad))
check("…and `update` rewrites it so that check passes, byte for byte the committed file", r.returncode == 0 and r2.returncode == 0 and bad.read_text() == raw, (r.stdout, r2.stdout[-200:]))

# ================================================================= 3. the label scan on small sources
def lab_of(src, fn="f"):
    return sorted(tt.labels_of(tt.functions(ast.parse(textwrap.dedent(src)))[fn]))
check("a label is the lowercase words an f-string or a literal starts with, up to a colon followed by a space, a newline or the end", lab_of('''
    def f(x):
        out = [f"mover: {x}", "then: " + x, "next:\\n" + x, f"creator: {x}", "wait failed:", f"after:{x}"]''') == ["after:", "creator:", "mover:", "next:", "then:", "wait failed:"])
check("…at each line start inside a literal, and after a leading newline", lab_of('''
    def f(x):
        a = "first line\\nsecond: here\\nthird"
        b = f"\\ncreator check: {x}"''') == ["creator check:", "second:"])
check("not a label: a sentence, a capital word, five words, a url, a colon inside a word, text after a placeholder", lab_of('''
    def f(x):
        a = ["Refused: no", "It reads: yes", "one two three four five: six", f"see https://x.y/z: now", f"{x} then: no", "a:b", f"mid {x} label: x"]''') == [])
check("not counted: a docstring, a string statement, a raise, a print to stderr, a literal inside a placeholder", lab_of('''
    def f(x):
        """docstring: no"""
        "statement: no"
        print(f"log: no", file=sys.stderr)
        if x: raise ToolError(f"refused: no")
        return f"head {'inside: no' + x} tail"''') == [])
check("a loop's own constants expand: f\"{k}: …\" in `for k in (\"a\", \"b\")`; the one `x if k == \"b\" else f\"{k}: …\"` takes out is gone", lab_of('''
    def f(m):
        for k in ("a", "b", "c"):
            out.append(f"special: {m[k]}" if k == "b" else f"{k}: {m[k]}")''') == ["a:", "c:", "special:"])
check("…but a comprehension's own k is not that loop's, and a computed iterable gives none", lab_of('''
    def f(m, rows):
        for k in ("a", "b"):
            out.extend(f"{k}: {v}" for k, v in rows)
        for j in rows:
            out.append(f"{j}: {m[j]}")''') == [])
check("the scan finds `mover:` and `then:` in the real helpers, with no `owner:`", {"then:", "mover:"} <= set(lab["get"]) and "owner:" not in lab["get"])

# ================================================================= 4. the touched-tool check, on a throwaway repository
R = T / "repo"; R.mkdir()
def W(rel, text):
    (R / rel).parent.mkdir(parents=True, exist_ok=True); (R / rel).write_text(text)
g = lambda *a: subprocess.run(["git", "-C", str(R), *a], capture_output=True, text=True, check=True).stdout.strip()
g("init", "-q", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
SERVER = '''
mcp = None
@mcp.tool(name="x", description="d")
def stackshot_x(a):
    """doc"""
    return _fmt(a)
def _fmt(a):
    # a comment
    return "mover: " + a
def _other(a):
    return a
'''
(R / "tests").mkdir(); W("stackshot/web/server.py", SERVER); W("stackshot/model/states.py", "def words(i):\n    return 'state: ' + i\n"); (R / "tests" / "tool_text.snapshot.json").write_text("{}\n")
g("add", "-A"); g("commit", "-qm", "base")
BASE = g("rev-parse", "HEAD")
def variant(name, server=None, snap=None, states=None):
    g("checkout", "-q", "-b", name, BASE)
    if server is not None: W("stackshot/web/server.py", server)
    if snap is not None: (R / "tests" / "tool_text.snapshot.json").write_text(snap)
    if states is not None: W("stackshot/model/states.py", states)
    g("commit", "-qam", name, "--allow-empty")
    return g("rev-parse", "HEAD")
def touched(head, body="", base=None):
    rc, msg = tt.touched(R, base or BASE, head, body)
    return rc, "\n".join(msg)
rc, m = touched(variant("comment", SERVER.replace("# a comment", "# another comment")))
check("a comment-only change touches nothing", rc == 0 and "touches no tool function" in m, m)
rc, m = touched(variant("doc", SERVER.replace('"""doc"""', '"""other doc"""')))
check("a docstring change is not a body change (the description the snapshot holds is what counts)", rc == 0 and "touches no tool function" in m, m)
rc, m = touched(variant("deco", SERVER.replace('description="d"', 'description="e"')))
check("a decorator change is the snapshot check's, not this one's", rc == 0 and "touches no tool function" in m, m)
rc, m = touched(variant("other", SERVER.replace("def _other(a):\n    return a", "def _other(a):\n    return a + a")))
check("a function that is neither a tool nor an output helper may change", rc == 0 and "touches no tool function" in m, m)
H = variant("helper", SERVER.replace('"mover: " + a', '"then: " + a'))
rc, m = touched(H)
check("an output helper's changed body with the snapshot unchanged fails, naming the function, the two ways out and the refresh command", rc == 1 and "stackshot/web/server.py:_fmt" in m and "tool-text: unchanged: <why" in m and "python3 tools/tool_text.py update" in m, m)
rc, m = touched(H, "Fixes a thing.\n\ntool-text: unchanged: a refactor, every line reads as before\n")
check("…unless the PR body carries `tool-text: unchanged: <reason>`, and the reason is shown", rc == 0 and "a refactor, every line reads as before" in m and "stackshot/web/server.py:_fmt" in m, m)
rc, m = touched(H, "- tool-text: unchanged:   \n")
check("…an empty reason does not count", rc == 1, m)
for ph in ("<reason>", "<why no session reads a difference>", "<reason> <reason>.", "<>", "ab"):
    rc, m = touched(H, f"tool-text: unchanged: {ph}\n")
    check(f"…a placeholder is not a reason: `{ph}` fails, and the message says so", rc == 1 and "placeholder" in m if ph.startswith("<") else rc == 1, m)
rc, m = touched(H, "tool-text: unchanged: <reason> kept as is because a refactor changes nothing")
check("…a reason that has real words around an angle-bracket word still counts", rc == 0, m)
rc, m = touched(H, "tool-text: changed: yes\nsomething tool-text: unchanged: inline does not count")
check("…nor does a line that is not that line", rc == 1, m)
rc, m = touched(H, "TOOL-TEXT: UNCHANGED: upper case is fine")
check("…upper case and a list bullet are fine", rc == 0, m)
H2 = variant("helper-snap", SERVER.replace('"mover: " + a', '"then: " + a'), snap='{"x": 1}\n')
rc, m = touched(H2)
check("the snapshot changing with the helper passes", rc == 0 and "changed with them" in m, m)
T1 = variant("tool", SERVER.replace("return _fmt(a)", "return _fmt(a) + _fmt(a)"))
rc, m = touched(T1)
check("a tool function's changed body with the snapshot unchanged fails (stackshot_x, found by its @mcp.tool decorator)", rc == 1 and "stackshot/web/server.py:stackshot_x" in m, m)
T2 = variant("newtool", SERVER + '\n@mcp.tool(name="y", description="d")\ndef stackshot_y(a):\n    return a\n')
rc, m = touched(T2)
check("a new tool with no snapshot change fails", rc == 1 and "stackshot/web/server.py:stackshot_y" in m, m)
S1 = variant("states", states="def words(i):\n    return 'next: ' + i\n")
rc, m = touched(S1)
check("a helper in another file (states.words) is watched too", rc == 1 and "stackshot/model/states.py:words" in m, m)
g("checkout", "-q", "main"); W("stackshot/web/server.py", SERVER.replace('"mover: " + a', '"later: " + a')); g("commit", "-qam", "main moves on")
MAIN_TIP = g("rev-parse", "HEAD")
rc, m = touched(variant("fork", SERVER.replace("# a comment", "# fork")), base=MAIN_TIP)
check("the base is the fork point: a main that moved on (its own helper change) is not the PR's change", rc == 0, m)
rc, m = tt.touched(R, MAIN_TIP, g("rev-parse", "fork"), "", exact=True); m = "\n".join(m)
check("…while --exact compares the two commits as they are", rc == 1 and "stackshot/web/server.py:_fmt" in m, m)
bf = T / "body.txt"; bf.write_text("tool-text: unchanged: from a file\n")
r = subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "tool_text.py")), "touched", "--repo", str(R), "--base", BASE, "--head", H, "--body-file", str(bf)], capture_output=True, text=True)
r2 = subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "tool_text.py")), "touched", "--repo", str(R), "--base", BASE, "--head", H, "--body-file", str(T / "none.txt")], capture_output=True, text=True)
check("the command: exit 0 with the reason read from --body-file, exit 1 with no body (a missing file is an empty body)", r.returncode == 0 and "from a file" in r.stdout and r2.returncode == 1 and "stackshot/web/server.py:_fmt" in r2.stdout, (r.returncode, r.stdout, r2.returncode, r2.stdout))
wf = (pathlib.Path(STACK) / ".github/workflows/tests.yml").read_text(encoding="utf-8")
body_refs = [l for l in wf.splitlines() if "github.event.pull_request.body" in l and not l.lstrip().startswith("#")]
runs_on = [l.strip() for l in wf.splitlines() if l.strip().startswith("runs-on:")]   # every job runs on ubuntu-latest
check("the workflow runs it on pull_request events only, on GitHub's hosted runners (ubuntu-latest), with the body in an environment variable and never in the shell text",
      "tools/tool_text.py touched" in wf and "github.event_name == 'pull_request'" in wf and len(runs_on) >= 2 and all(r.split("#")[0].strip() == "runs-on: ubuntu-latest" for r in runs_on)
      and len(body_refs) >= 1 and all(r.strip().startswith("PR_BODY:") for r in body_refs), (runs_on, body_refs))
# Every job of the two workflows runs on ubuntu-latest.
import yaml
sw = {}
for f in ("tests.yml", "clean-text.yml"):
    text = (pathlib.Path(STACK) / ".github/workflows" / f).read_text(encoding="utf-8"); y = yaml.safe_load(text)
    sw[f] = [(n, j["runs-on"]) for n, j in y["jobs"].items()]
check("every job of tests.yml and clean-text.yml runs on ubuntu-latest",
      all(r == "ubuntu-latest" for rs in sw.values() for n, r in rs)
      and sum(len(rs) for rs in sw.values()) == 5, sw)   # tests.yml: shards (main's shard plan), measure (main's measured run, a matrix), suites, tool-text; one in clean-text.yml

# ================================================================= 5. the generated what-changed line
S = lambda tools, **kw: {"format": 1, "instructions": kw.get("ins", "i"), "resources": kw.get("res", {}), "tools": tools}
P = lambda **kw: {"type": kw.get("type", "string"), "required": kw.get("required", False), "description": kw.get("description", "")}
A = S({"create": {"description": "make", "parameters": {"owner": P(description="who"), "subject": P(required=True), "old": P(type="integer")}, "labels": ["owner:", "next:"]},
       "get": {"description": "read", "parameters": {"item_id": P(required=True)}, "labels": ["next:"]}, "gone": {"description": "x", "parameters": {}}})
B = copy.deepcopy(A)
check("no change reads as an empty summary", wc.summarize(A, B) == "")
B["tools"]["create"]["parameters"]["sender"] = B["tools"]["create"]["parameters"].pop("owner")
B["tools"]["create"]["parameters"]["mover"] = P(); B["tools"]["create"]["parameters"]["then"] = P()
del B["tools"]["create"]["parameters"]["old"]
B["tools"]["create"]["parameters"]["subject"]["description"] = "the subject"
B["tools"]["create"]["description"] = "make it"
B["tools"]["create"]["labels"] = ["creator:", "next:"]
B["tools"]["get"]["labels"] = ["mover:", "next:", "then:"]
B["tools"]["new"] = {"description": "n", "parameters": {}}; del B["tools"]["gone"]
want = "new tools new; tools removed gone; create: parameters added mover/then, parameter removed old, parameter owner renamed sender, parameters changed subject (description), description changed, lines added creator:, lines removed owner:; get: lines added mover:/then:"
check("the summary names tools added and removed, and per tool parameters added, removed, renamed (same shape, new name) and changed, the description, the labels", wc.summarize(A, B) == want, wc.summarize(A, B))
check("…the connector's instructions and resources", wc.summarize(S({}), S({}, ins="j")) == "the connector's instructions changed" and wc.summarize(S({}), S({}, res={"r": {}})) == "resources changed")
many = S({f"t{i:02d}": {"description": "a", "parameters": {}} for i in range(12)}); many2 = S({f"t{i:02d}": {"description": "b", "parameters": {}} for i in range(12)})
check("a long change names eight tools and counts the rest", wc.summarize(many, many2).endswith("t07: description changed; and 4 more") and wc.summarize(many, many2).count("description changed") == 8, wc.summarize(many, many2))

state = T / "state"; snap = T / "snap.json"
snap.write_text(tt.render(A))
d0 = dt.date(2026, 11, 20)
r0 = wc.record(snap, d0, state)
check("the first start keeps a copy of the snapshot and seeds the history with the two hand-written entries", "first start" in r0 and json.loads((state / wc.RELEASED).read_text()) == A and json.loads((state / wc.HISTORY).read_text()) == wc.SEED, r0)
r1 = wc.record(snap, d0, state)
check("a start with the text unchanged records nothing", "as at the last start" in r1 and json.loads((state / wc.HISTORY).read_text()) == wc.SEED, r1)
snap.write_text(tt.render(B))
r2 = wc.record(snap, d0, state)
hist = json.loads((state / wc.HISTORY).read_text())
check("a start after a change appends the generated line, dated that day, and keeps the new copy", len(hist) == 3 and hist[-1] == {"date": "2026-11-20", "text": want} and json.loads((state / wc.RELEASED).read_text()) == B, (r2, hist[-1:]))
check("…and the same snapshot at the next start adds nothing", wc.record(snap, d0, state) and len(json.loads((state / wc.HISTORY).read_text())) == 3)
snap.write_text("not json")
r3 = wc.record(snap, d0, state)
check("an unreadable snapshot is said, never raised, and leaves the state as it was", "no snapshot to compare" in r3 and json.loads((state / wc.RELEASED).read_text()) == B and len(json.loads((state / wc.HISTORY).read_text())) == 3, r3)
(state / wc.RELEASED).write_text("{broken")
snap.write_text(tt.render(B)); r4 = wc.record(snap, d0, state)
check("a damaged copy is taken again from the snapshot without losing the history", "first start" in r4 and len(json.loads((state / wc.HISTORY).read_text())) == 3 and json.loads((state / wc.RELEASED).read_text()) == B, r4)
# the state files: private (0600), no temp litter on a failed write, a released copy of the wrong shape rebuilt, and a record that fails half way adds no second entry
st2 = T / "state2"
snap.write_text(tt.render(A)); wc.record(snap, d0, st2)
check("the history and the released copy are written 0600", {(st2 / n).stat().st_mode & 0o777 for n in (wc.HISTORY, wc.RELEASED)} == {0o600}, [oct((st2 / n).stat().st_mode & 0o777) for n in (wc.HISTORY, wc.RELEASED)])
(st2 / wc.RELEASED).write_text("[1, 2]"); snap.write_text(tt.render(B)); r5 = wc.record(snap, d0, st2)
check("a released copy that is a JSON list is treated as absent: rebuilt from the snapshot, the history kept, no failure at this start or the next",
      "first start" in r5 and json.loads((st2 / wc.RELEASED).read_text()) == B and json.loads((st2 / wc.HISTORY).read_text()) == wc.SEED and "as at the last start" in wc.record(snap, d0, st2), r5)
snap.write_text(tt.render(A))
_real_replace = os.replace
def _replace_fails_for_released(src, dst, *a, **k):
    if os.path.basename(str(dst)) == wc.RELEASED: raise OSError("disk full")
    return _real_replace(src, dst, *a, **k)
os.replace = _replace_fails_for_released
try:
    try: wc.record(snap, d0, st2); failed = False
    except OSError: failed = True
finally:
    os.replace = _real_replace
check("a write that fails raises and leaves no temp file behind", failed and sorted(p.name for p in st2.iterdir()) == sorted([wc.HISTORY, wc.RELEASED]), sorted(p.name for p in st2.iterdir()))
h1 = json.loads((st2 / wc.HISTORY).read_text())
r6 = wc.record(snap, d0, st2)
h2 = json.loads((st2 / wc.HISTORY).read_text())
check("the history was written before the copy failed, and the retry adds no second entry for the same change that day; the copy is then current",
      len(h1) == 3 and h2 == h1 and json.loads((st2 / wc.RELEASED).read_text()) == A, (len(h1), len(h2), r6))
home = state / wc.HISTORY
check("the line shows on its day and for 7 days, and is gone on the 8th; the seeds (a fixed date) show for 7 days",
      wc.lines(d0, home) == [f"stackshot changed on Fri Nov 20th: {want}; see {wc.PAGE}"] and wc.lines(d0 + dt.timedelta(days=7), home) and not wc.lines(d0 + dt.timedelta(days=8), home)
      and len(wc.lines(dt.date(2099, 3, 3), home)) == 2 and len(wc.lines(dt.date(2099, 3, 10), home)) == 2 and not wc.lines(dt.date(2099, 3, 11), home), wc.lines(d0, home))
# the brief carries it: the server's default history path is <paths.state>/tool_text.history.json
wc.PATH = None
today = dt.datetime.now(server._cfg.tz()).date()
st = server._cfg.state()
st.mkdir(parents=True, exist_ok=True)
for f in (st / wc.HISTORY, st / wc.RELEASED):
    if f.exists(): f.unlink()
snap.write_text(tt.render(A)); wc.record(snap, today, st); snap.write_text(tt.render(B)); wc.record(snap, today, st)
first = [l for l in server.stackshot_brief().split("\n") if l.startswith("stackshot changed on")]
check("the brief tool carries the generated line from the default history under the state dir (and the seeds while they are live)", f"stackshot changed on {wc.day_words(today)}: {want}; see {wc.PAGE}" in first, first)
src = (pathlib.Path(STACK) / "stackshot" / "web" / "server.py").read_text(encoding="utf-8")
check("the server's start calls whatschanged.record with the committed snapshot (the mark of a release), and deploy.sh is not part of it", '_wc.record(_paths.ROOT / "tests" / "tool_text.snapshot.json")' in src and "tool_text" not in (pathlib.Path(STACK) / "deploy.sh").read_text(encoding="utf-8"))

import shutil; shutil.rmtree(T, ignore_errors=True)
tt.cleanup()
left = sorted(p.name for p in SCRATCH.iterdir())
check("a run leaves nothing behind: its scratch folders (the throwaway config, the fixture repository, the commands' own) are all removed at exit", not left, left)
shutil.rmtree(SCRATCH, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": tool_text scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
