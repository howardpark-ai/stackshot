"""Scenario test for the tool text, in two parts that each run in a process of their own: the tools' text (the snapshot, the gates and the text files) and the worked examples in it.
Fixture data, throwaway configs, a throwaway git repo; no live store, no network.

Part `text` - the gates and the files, in one process (both read the registry of one throwaway config made by tools/tool_text.py and keep no module state of their own); the two
groups of checks run one after the other, each with its own scratch folder that must be empty again at its end:

  The tool-text gates (tools/tool_text.py, whatschanged.py). Covers: the committed snapshot (tests/tool_text.snapshot.json) is exactly what the server registers now (a tool's name, parameters, description as served, the
  labels of the lines it returns, the connector's instructions and resources) — and when it is not, the failure prints a readable diff and the one command that
  refreshes it; the snapshot is stable (sorted keys, normalised whitespace, the same twice); the label scan on small sources (what counts as a label and what
  does not); every output helper the list names exists; the touched-tool check on a throwaway repository (a changed body with the snapshot unchanged fails unless
  the PR body says `tool-text: unchanged: <reason>`; the snapshot changing with it, a comment, a docstring, a non-helper, passes; the fork point, not the moved
  tip, is the base); the summary of a change (tools added or removed, parameters added, removed, renamed or changed, description and label changes); the mark
  of a release (the first start keeps a copy and seeds the history, a start with the text unchanged records nothing, one with a change records the generated
  line, which the brief carries for 7 days and then not).

  The tools' text files (stackshot/web/tools/text/*.md, read by stackshot/web/tools/textfile.py): fixture files in a temp folder, then the real files.
  Stdlib and the package only, no store, no network. Covers: the section format (a header per section, wrapped lines joined by one space, the `lead` and `trail` flags for an edge space, blank lines between sections but
  never inside one, only comments before the first section, a bad header, an empty or repeated section); the {{NAME}} placeholders (a value, a piece of the same file, a
  late value passed when the text is asked for, a piece of the shared file through the parent, single braces left alone); what fails at load (a placeholder nothing
  defines, a value passed and never used, a late name never used, a section the shared file has too, pieces that refer to each other in a circle); what is asked for
  and not there; the leftovers report (`unused`, `unused_values`); and the real files: every tool module loads, no section of them is a leftover, no shared value is
  unused, and no file carries Hangul, a machine placeholder or the sala name (a fresh install reads them).

Part `examples` - the worked examples in the board tools' text (its own process: it sets up an instance of its own that the server modules read once at import; the self-wait model call is stubbed):

A worked example that the server refuses teaches the wrong call. Each example below is copied from the live tool text (the test first checks that the fragment is in the first
2,048 characters of its tool's description, the part a CLI session keeps), then called as written through the real tool function with only the names swapped for the fixture's
(session, project, item ids, a day inside the wait cap for a placeholder day).

    create   own work · an item that needs the owner's call (ask and options) · a wait on another item · work for the builder
    update   a step done and the next one added · reword · dropped · a work line · a park · a dated wait on your own item · a wait on another item · a description
    complete done · dropped · superseded
    message  a front agent · a plain result to the project · a question and a hand-off to a background agent (the hand-off example must sit in the first 2,048 characters)
    anchors  list · add · add scoped to an item · remove        confirm        route        check=  (create and update)

    tests/run-suite tool_text        -> exit 0 / 1"""
import copy, datetime as dt, importlib, json, logging, os, pathlib, re, subprocess, sys, tempfile, textwrap, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, os.path.join(STACK, "tools")); sys.path.insert(0, STACK); sys.path.insert(0, SCR)

# The two parts set up two different instances (tools/tool_text.py's throwaway config of the example; a base config with the owner, the marks and a store of its own), and the code under test reads its
# config and keeps module state at import: so each part runs in a process of its own (this file started again with `--part <name>`), exactly as the suites did, and the parent adds their counts.
PARTS = ("text", "examples")

def _checker(limit):
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:limit]}" if got is not None else ""))
    return check, fails, ran


# ================================================================ part text, first group: the tool-text gates
def part_gates():
    import _scratch
    _tmp0 = (tempfile.tempdir, os.environ.get("TMPDIR"))   # to put back at the end: the next part makes its scratch folder the same way
    check, fails, ran = _checker(700)
    SCRATCH = pathlib.Path(_scratch.mkdtemp(prefix="tooltexttest-base-")); tempfile.tempdir = str(SCRATCH); os.environ["TMPDIR"] = str(SCRATCH)   # every scratch file of this run, and of the commands it starts, goes under BASE; the last check asserts BASE is empty again

    import tool_text as tt
    live = tt.live_snapshot()              # imports server.py on a throwaway config (state under its temp dir)
    import ast; from stackshot.web import server; from stackshot.web.tools import brief as _wt_brief; from stackshot.web import whatschanged as wc
    from stackshot.core import config as _cfg
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
    check("brief adds its own labels (mover gone:, pages owed:, pages owed by others:); message returns no labelled line", {"mover gone:", "waits no watcher owns:", "pages owed by others:", "pages owed:"} <= set(lab["brief"]) and lab["message"] == [], lab["brief"])
    names_ok = tt.labels_by_tool()
    check("every output helper in HELPERS is defined (a renamed or removed one fails loudly, naming the list)", set(names_ok) == set(tt.HELPERS) and names_ok["get"] == lab["get"], None)
    tools_ast = set()
    for _rel in (tt.SERVER_REL, *tt.TOOL_FILES):
        tools_ast.update(tt.tool_functions(ast.parse((pathlib.Path(STACK) / _rel).read_text(encoding="utf-8"))))
    check("the touched check finds every registered tool function by its mcp.tool registration", len(tools_ast) == len(names) and "stackshot_brief" in tools_ast and "stackshot_complete" in tools_ast, sorted(tools_ast))

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
    (R / "tests").mkdir(); W("stackshot/web/tools/get.py", SERVER); W("stackshot/model/states.py", "def words(i):\n    return 'state: ' + i\n"); (R / "tests" / "tool_text.snapshot.json").write_text("{}\n")
    g("add", "-A"); g("commit", "-qm", "base")
    BASE = g("rev-parse", "HEAD")
    def variant(name, server=None, snap=None, states=None):
        g("checkout", "-q", "-b", name, BASE)
        if server is not None: W("stackshot/web/tools/get.py", server)
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
    check("an output helper's changed body with the snapshot unchanged fails, naming the function, the two ways out and the refresh command", rc == 1 and "stackshot/web/tools/get.py:_fmt" in m and "tool-text: unchanged: <why" in m and "python3 tools/tool_text.py update" in m, m)
    rc, m = touched(H, "Fixes a thing.\n\ntool-text: unchanged: a refactor, every line reads as before\n")
    check("…unless the PR body carries `tool-text: unchanged: <reason>`, and the reason is shown", rc == 0 and "a refactor, every line reads as before" in m and "stackshot/web/tools/get.py:_fmt" in m, m)
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
    check("a tool function's changed body with the snapshot unchanged fails (stackshot_x, found by its @mcp.tool decorator)", rc == 1 and "stackshot/web/tools/get.py:stackshot_x" in m, m)
    T2 = variant("newtool", SERVER + '\n@mcp.tool(name="y", description="d")\ndef stackshot_y(a):\n    return a\n')
    rc, m = touched(T2)
    check("a new tool with no snapshot change fails", rc == 1 and "stackshot/web/tools/get.py:stackshot_y" in m, m)
    S1 = variant("states", states="def words(i):\n    return 'next: ' + i\n")
    rc, m = touched(S1)
    check("a helper in another file (states.words) is watched too", rc == 1 and "stackshot/model/states.py:words" in m, m)
    def text_variant(name, files, base=BASE, snap=None):
        g("checkout", "-q", "-b", name, base)
        for rel, text in files.items(): W(rel, text)
        if snap is not None: (R / "tests" / "tool_text.snapshot.json").write_text(snap)
        g("add", "-A"); g("commit", "-qm", name, "--allow-empty")
        return g("rev-parse", "HEAD")
    TX = f"{tt.TEXT_DIR}/get.md"
    X1 = text_variant("text-new", {TX: "## description get\nRead one item.\n"})
    rc, m = touched(X1)
    check("a tool's text file (web/tools/text/*.md) is watched whole: a new one with the snapshot unchanged fails, naming it as `file:text`", rc == 1 and f"{TX}:text" in m, m)
    rc, m = touched(X1, "tool-text: unchanged: the text moved from Python into text files\n")
    check("…and the PR body's `tool-text: unchanged:` line lets it pass, as for a function", rc == 0 and f"{TX}:text" in m, m)
    X2 = text_variant("text-edit", {TX: "## description get\nRead one item by id.\n"}, base=X1)
    rc, m = touched(X2, base=X1)
    check("a changed word in a text file with the snapshot unchanged fails", rc == 1 and f"{TX}:text" in m, m)
    X3 = text_variant("text-edit-snap", {TX: "## description get\nRead one item by id.\n"}, base=X1, snap='{"x": 2}\n')
    rc, m = touched(X3, base=X1)
    check("…and passes when the snapshot changed with it", rc == 0 and "changed with them" in m, m)
    X4 = text_variant("text-other", {f"{tt.TEXT_DIR}/notes.txt": "not a text file of the tools\n"}, base=X1)
    rc, m = touched(X4, base=X1)
    check("a file in that folder that is not a .md is not watched", rc == 0 and "touches no tool function" in m, m)
    check("text_files_at lists the .md files of a revision and none at a revision before they existed", tt.text_files_at(R, X1) == [TX] and tt.text_files_at(R, BASE) == [], (tt.text_files_at(R, X1), tt.text_files_at(R, BASE)))
    g("checkout", "-q", "main"); W("stackshot/web/tools/get.py", SERVER.replace('"mover: " + a', '"later: " + a')); g("commit", "-qam", "main moves on")
    MAIN_TIP = g("rev-parse", "HEAD")
    rc, m = touched(variant("fork", SERVER.replace("# a comment", "# fork")), base=MAIN_TIP)
    check("the base is the fork point: a main that moved on (its own helper change) is not the PR's change", rc == 0, m)
    rc, m = tt.touched(R, MAIN_TIP, g("rev-parse", "fork"), "", exact=True); m = "\n".join(m)
    check("…while --exact compares the two commits as they are", rc == 1 and "stackshot/web/tools/get.py:_fmt" in m, m)
    bf = T / "body.txt"; bf.write_text("tool-text: unchanged: from a file\n")
    r = subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "tool_text.py")), "touched", "--repo", str(R), "--base", BASE, "--head", H, "--body-file", str(bf)], capture_output=True, text=True)
    r2 = subprocess.run([sys.executable, str(pathlib.Path(STACK, "tools", "tool_text.py")), "touched", "--repo", str(R), "--base", BASE, "--head", H, "--body-file", str(T / "none.txt")], capture_output=True, text=True)
    check("the command: exit 0 with the reason read from --body-file, exit 1 with no body (a missing file is an empty body)", r.returncode == 0 and "from a file" in r.stdout and r2.returncode == 1 and "stackshot/web/tools/get.py:_fmt" in r2.stdout, (r.returncode, r.stdout, r2.returncode, r2.stdout))
    wf = (pathlib.Path(STACK) / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    body_refs = [l for l in wf.splitlines() if "github.event.pull_request.body" in l and not l.lstrip().startswith("#")]
    runs_on = [l.strip() for l in wf.splitlines() if l.strip().startswith("runs-on:")]   # every job runs on ubuntu-latest
    check("the workflow runs it on pull_request events only, on GitHub's hosted runners (ubuntu-latest), with the body in an environment variable and never in the shell text",
          "tools/tool_text.py touched" in wf and "github.event_name == 'pull_request'" in wf and len(runs_on) >= 2 and all(r.split("#")[0].strip() == "runs-on: ubuntu-latest" for r in runs_on)
          and len(body_refs) >= 1 and all(r.strip().startswith("PR_BODY:") for r in body_refs), (runs_on, body_refs))
    # Every job of the three workflows runs on ubuntu-latest.
    import yaml
    sw = {}
    for f in ("tests.yml", "clean-text.yml", "suitemap-refresh.yml"):
        text = (pathlib.Path(STACK) / ".github/workflows" / f).read_text(encoding="utf-8"); y = yaml.safe_load(text)
        sw[f] = [(n, j["runs-on"]) for n, j in y["jobs"].items()]
    check("every job of tests.yml, clean-text.yml and suitemap-refresh.yml runs on ubuntu-latest",
          all(r == "ubuntu-latest" for rs in sw.values() for n, r in rs)
          and sum(len(rs) for rs in sw.values()) == 10, sw)   # tests.yml: proof (main's read of the queue's run), shards (the full run's shard plan), measure (the full run, a matrix), suites, tool-text; one in clean-text.yml; suitemap-refresh.yml: shards, measure, refresh, report

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
    today = dt.datetime.now(_cfg.tz()).date()
    st = _cfg.state()
    st.mkdir(parents=True, exist_ok=True)
    for f in (st / wc.HISTORY, st / wc.RELEASED):
        if f.exists(): f.unlink()
    snap.write_text(tt.render(A)); wc.record(snap, today, st); snap.write_text(tt.render(B)); wc.record(snap, today, st)
    first = [l for l in _wt_brief.stackshot_brief().split("\n") if l.startswith("stackshot changed on")]
    check("the brief tool carries the generated line from the default history under the state dir (and the seeds while they are live)", f"stackshot changed on {wc.day_words(today)}: {want}; see {wc.PAGE}" in first, first)
    src = (pathlib.Path(STACK) / "stackshot" / "web" / "server.py").read_text(encoding="utf-8")
    check("the server's start calls whatschanged.record with the committed snapshot (the mark of a release), and deploy.sh is not part of it", '_wc.record(_paths.ROOT / "tests" / "tool_text.snapshot.json")' in src and "tool_text" not in (pathlib.Path(STACK) / "deploy.sh").read_text(encoding="utf-8"))

    import shutil; shutil.rmtree(T, ignore_errors=True)
    tt.cleanup()
    left = sorted(p.name for p in SCRATCH.iterdir())
    check("a run leaves nothing behind: its scratch folders (the throwaway config, the fixture repository, the commands' own) are all removed at exit", not left, left)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    tempfile.tempdir = _tmp0[0]
    if _tmp0[1] is None: os.environ.pop("TMPDIR", None)
    else: os.environ["TMPDIR"] = _tmp0[1]
    return ran, fails


# ================================================================ part text, second group: the tools' text files
def part_files():
    import _scratch
    check, fails, ran = _checker(700)
    BASE = pathlib.Path(_scratch.mkdtemp(prefix="ttfiles-base-")); tempfile.tempdir = str(BASE)     # all scratch under BASE; the last check asserts it is empty again
    T = pathlib.Path(_scratch.mkdtemp(prefix="ttfiles-"))

    from stackshot.web.tools import textfile as tf


    def put(name, text):
        (T / f"{name}.md").write_text(text, encoding="utf-8")


    def fails_with(name, text, *args, **kw):
        """The message of the TextFileError loading `name` fixture text raises, or None when it loads."""
        put(name, text)
        try:
            tf.load(name, *args, directory=T, **kw)
        except tf.TextFileError as e:
            return str(e)
        return None


    # ================================================================= 1. the section format
    put("a", """# a comment before the first section

## description get
Read one item
by id, wrapped at a space.

## param ITEM
The item id.
## text TAIL trail
ends with a space
## text HEAD lead
 starts with a space
""")
    a = tf.load("a", directory=T)
    check("a description is its lines joined by one space, the header and the comment above the first section are not text", a.description("get") == "Read one item by id, wrapped at a space.", a.description("get"))
    check("a param and a piece are asked for by name, and a section may follow the one before it with no blank line", a.param("ITEM") == "The item id.", a.param("ITEM"))
    check("`trail` ends a text with one space and `lead` starts it with one (a line cannot show an edge space)", a.piece("TAIL") == "ends with a space " and a.piece("HEAD") == "  starts with a space", (a.piece("TAIL"), a.piece("HEAD")))
    for label, text, want in (
            ("a blank line inside a section", "## text X\none\n\ntwo\n", "blank line inside"),
            ("text before the first section", "stray\n## text X\none\n", "before the first section"),
            ("a header with an unknown kind", "## widget X\none\n", "section header reads"),
            ("a header with no name", "## text\none\n", "section header reads"),
            ("an empty section", "## text X\n## text Y\none\n", "is empty"),
            ("a section twice", "## text X\none\n## text X\ntwo\n", "there twice"),
            ("a flag that is not lead or trail", "## text X middle\none\n", "section header reads")):
        m = fails_with("bad", text)
        check(f"{label} does not load", m is not None and want in m, m)

    # ================================================================= 2. placeholders
    put("p", """## text WORD
one
## text BOTH
{{COUNT}} of {{WORD}} and {{LATE}}; a {single} brace and a {{ lone pair stay
## description tool
{{BOTH}}.
""")
    p = tf.load("p", {"COUNT": "3"}, late=("LATE",), directory=T)
    check("a placeholder is replaced by a value, by a piece of the same file or by a late value given when the text is asked for", p.description("tool", LATE="now") == "3 of one and now; a {single} brace and a {{ lone pair stay.", p.description("tool", LATE="now"))
    check("single braces and a lone `{{` are plain text", "{single}" in p.piece("BOTH", LATE="x") and "{{ lone pair" in p.piece("BOTH", LATE="x"))
    check("the same text asked for with another late value is not taken from a cache", p.piece("BOTH", LATE="a") != p.piece("BOTH", LATE="b"))
    try:
        p.piece("BOTH")
        got = None
    except tf.TextFileError as e:
        got = str(e)
    check("a late name left out when the text is asked for fails, naming it", got is not None and "LATE" in got, got)
    try:
        p.piece("BOTH", LATE="x", OTHER="y")
        got = None
    except tf.TextFileError as e:
        got = str(e)
    check("a late value the file does not declare fails", got is not None and "OTHER" in got, got)
    for call in (lambda: p.description("nothing"), lambda: p.param("NOTHING"), lambda: p.piece("NOTHING")):
        try:
            call(); got = None
        except tf.TextFileError as e:
            got = str(e)
        check("asking for a section the file does not hold fails", got is not None and "no " in got, got)

    # ================================================================= 3. what fails at load
    m = fails_with("u1", "## text X\n{{NOWHERE}}\n")
    check("a placeholder no value, piece or late name defines fails at load, naming the section and the placeholder", m is not None and "NOWHERE" in m and "text X" in m, m)
    m = fails_with("u2", "## text X\none\n", {"UNUSED": "1"})
    check("a value that is passed and that no text uses fails at load", m is not None and "UNUSED" in m, m)
    m = fails_with("u3", "## text X\none\n", late=("SPARE",))
    check("a late name that is declared and that no text uses fails at load", m is not None and "SPARE" in m, m)
    m = fails_with("u4", "## text X\n{{Y}}\n## text Y\n{{X}}\n")
    check("pieces that refer to each other in a circle fail at load", m is not None and "circle" in m, m)
    m = fails_with("u5", "## text X\n{{X}}\n")
    check("a piece that names itself fails at load", m is not None and "circle" in m, m)
    check("a value used by a placeholder, and a piece used by another piece, load", fails_with("u6", "## text X\n{{V}} {{Y}}\n## text Y\ny\n", {"V": "1"}) is None)

    # ================================================================= 4. the shared file and the parent
    put("shared", "## text COMMON\nthe common {{N}} words\n## text SPARE\nused by nobody here\n## param WHO\nwho acts\n")
    sh = tf.load("shared", {"N": "7", "NOT_USED_HERE": "x"}, directory=T, common=True)
    put("child", "## description tool\n{{COMMON}} and {{OWN}} and {{N}}\n## text OWN\nown\n")
    c = tf.load("child", directory=T, parent=sh)
    check("a shared value or piece is read through the parent by the child's placeholders, the own piece first", c.description("tool") == "the common 7 words and own and 7", c.description("tool"))
    check("a param of the shared file is asked for through the child", c.param("WHO") == "who acts")
    check("the shared file may hold values that it does not use itself (`common`)", True)
    m = fails_with("dup", "## text COMMON\nagain\n## description tool\nx\n", parent=sh)
    check("a section the shared file has too is refused in a child: say it once", m is not None and "shared file too" in m, m)
    try:
        tf.load("shared", {"N": "7", "UNUSED": "1"}, directory=T)
        got = None
    except tf.TextFileError as e:
        got = str(e)
    check("without `common` an unused value in the shared file fails too", got is not None and "UNUSED" in got, got)

    # ================================================================= 5. the leftovers report
    put("l", "## description a\nuses {{USED}}\n## text USED\nx\n## text DEAD\nnobody names me\n## param NEVER\nnobody asks\n")
    lf = tf.load("l", directory=T)
    lf.description("a")
    check("`unused` lists the sections nothing asks for or names, by kind and name, and not a piece another section names", lf.unused() == ["param NEVER", "text DEAD"], lf.unused())
    check("`unused_values` lists the values no text names", tf.load("shared", {"N": "7", "NOT_USED_HERE": "x"}, directory=T, common=True).unused_values([c]) == ["NOT_USED_HERE"])

    # ================================================================= 6. the real files
    TEXT_DIR = pathlib.Path(STACK, "stackshot", "web", "tools", "text")
    mods = ["anchors", "autonomy", "brief", "canvas", "complete", "create", "get", "invite", "message", "route", "rules", "sessions", "update"]
    check("there is a text file for each tool module and the shared one, and nothing else in the folder", sorted(p.name for p in TEXT_DIR.iterdir()) == sorted([f"{m}.md" for m in mods] + ["shared.md"]), sorted(p.name for p in TEXT_DIR.iterdir()))
    import tool_text as tt
    tt.live_snapshot()          # builds the server on a throwaway config, so every module has asked for its text
    real = {m: importlib.import_module(f"stackshot.web.tools.{m}")._T for m in mods}
    shared = importlib.import_module("stackshot.web.tools.text")._T
    check("every tool module loads its own file", all(isinstance(t, tf.Texts) for t in real.values()))
    dead = {m: t.unused() for m, t in real.items() if t.unused()}
    check("no section of a tool's file is a leftover: each is asked for by its module or named by another section", not dead, dead)
    check("no section of the shared file is a leftover", not shared.unused(list(real.values())), shared.unused(list(real.values())))
    check("no shared value is unused by every file", not shared.unused_values(list(real.values())), shared.unused_values(list(real.values())))
    hangul = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF))) + "]")     # Hangul by code point: the file itself carries none
    text_all = {p.name: p.read_text(encoding="utf-8") for p in TEXT_DIR.glob("*.md")}
    check("no text file carries Hangul, not even as an escape", not [n for n, t in text_all.items() if hangul.search(t) or re.search(r"\\u(?:[1][1-9a-f][0-9a-f]{2}|3[13][0-9a-f]{2}|[a-d][0-9a-f]{3})", t, re.I)], [n for n, t in text_all.items() if hangul.search(t)])
    check("no text file names a machine placeholder or sala (a fresh install reads them)", not [n for n, t in text_all.items() if re.search(r"box-[a-d]\b|salamander|\bsala\b", t, re.I)], [n for n, t in text_all.items() if re.search(r"box-[a-d]\b|salamander|\bsala\b", t, re.I)])
    check("every text file ends with one newline and has no trailing space on a line (a space at an edge is a `lead` or `trail` flag)", all(t.endswith("\n") and not t.endswith("\n\n") and not re.search(r"[ \t]+$", t, re.M) for t in text_all.values()), [n for n, t in text_all.items() if not t.endswith("\n") or t.endswith("\n\n") or re.search(r"[ \t]+$", t, re.M)])

    DEPLOY = pathlib.Path(STACK, "deploy.sh").read_text(encoding="utf-8")
    check("deploy.sh restarts the server for a change of a text file (the files are read at import)", re.search(r"^\s*stackshot/web/tools/text/\*\.md\) server=1(?:; minute=1)? ;;", DEPLOY, re.M) is not None)
    check("release.sh names the text files in session_need (nothing: the snapshot carries the notice), apart from the docs", "stackshot/web/tools/text/*.md)" in pathlib.Path(STACK, "release.sh").read_text(encoding="utf-8"))

    import shutil; shutil.rmtree(T, ignore_errors=True); tt.cleanup()
    left = sorted(p.name for p in BASE.iterdir())
    check("a run leaves nothing behind: its scratch folder is removed at exit", not left, left)
    shutil.rmtree(BASE, ignore_errors=True)
    return ran, fails


def part_text():
    ran1, fails1 = part_gates(); ran2, fails2 = part_files()
    return ran1 + ran2, fails1 + fails2


# ================================================================ part examples: the worked examples in the tools' text
def part_examples():
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="examplestest-"); T = pathlib.Path(tmp)
    BOARD = "https://board.example.org"

    def write_toml():
        toml = _instance.apply(_instance.base_toml())
        toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
        for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                         ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
            toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
        toml = _instance.set_person(toml)
        for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                         (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                         (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                         (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
            toml, n = re.subn(pat, rep, toml); assert n == 1, pat
        (T / "stackshot.toml").write_text(toml, encoding="utf-8")


    write_toml()
    (T / "github.token").write_text("test-token\n")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
    OWNER = "00000000-0000-4000-8000-000000000001"
    AGENT = "00000000-0000-4000-8000-000000000002"
    BUILDER = "00000000-0000-4000-8000-000000000003"
    FRONT = "00000000-0000-4000-8000-000000000004"
    now = time.time()
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now},
                                                                                   BUILDER: {"name": "home-builder", "machine": "a", "seen": now},
                                                                                   FRONT: {"name": "home-alpha-main", "machine": "a", "seen": now}}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-agent", "status": "active", "board": [], "board_open": 0,
                                                                                    "agents": {"home-alpha-main": "the front", "home-builder": "builds the code"}, "back_agents": {"home-builder": "builds the code"}}}}))
    DESC = "- Goal: A thing, finished when it works"


    def item(i, status="open", **meta):
        base = {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it"}
        base.update(meta)
        for k in [k for k, v in base.items() if v is None]: base.pop(k)
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                         "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": base}))


    for i in range(1, 60):
        item(i)                                                       # items in the agent's hands, one open step each
    TWO = "home-agent: build it\nhome-agent: ship it"
    (T / "store/next-id").write_text("200"); (T / "store/anchors.json").write_text("{}")
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-alpha\nagents:\n  home-alpha-main: the front\n  background:\n    home-builder: builds the code\n---\n\n# Alpha\n")
    git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
    git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
    logging.disable(logging.INFO)
    check, fails, ran = _checker(900)


    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    def mt(i): return rd(i)["metadata"]


    from stackshot.web import server; from stackshot.waits import self_wait as SW; from stackshot.router import router as R
    from stackshot.router import routing as _routing
    from fastmcp.exceptions import ToolError
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import complete as _wt_complete
    from stackshot.web.tools import create as _wt_create
    from stackshot.web.tools import message as _wt_message
    from stackshot.web.tools import route as _wt_route
    from stackshot.web.tools import text as _wt_text
    from stackshot.web.tools import update as _wt_update
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""        # the page rule is not under test here
    def _no_claude(*a, **k): raise AssertionError("the real model was called")
    R.run_call = _no_claude
    SW._run = lambda message: {"status": "ok", "text": json.dumps({"can_do_now": False, "reason": "the nightly run is still going"})}   # the self-wait check: the step cannot be done now

    SNAP = json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
    CLI_CUT = 2048                       # a CLI session keeps this many characters of a tool description
    TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()      # the instance zone is Asia/Dubai: UTC+4
    D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()


    def groups_of(frags):
        """A call written whole in the text is one list of fragments; a call the text spells in pieces ("the same call with no mover, and needs=…") is a list of groups, each a list of fragments."""
        return [list(g) for g in frags] if any(isinstance(f, (list, tuple)) for f in frags) else [list(frags)]


    def flat(frags):
        return [f for g in groups_of(frags) for f in g]


    def fragment_ok(tool, frags):
        """The example is in the first CLI_CUT characters of the tool's description as written: each group of fragments, joined as the text joins them, whole and in that order."""
        text, at = SNAP[tool]["description"][:CLI_CUT], 0
        for g in groups_of(frags):
            i = text.find(", ".join(g), at)
            if i < 0: return False
            at = i + len(", ".join(g))
        return True


    def kwargs_of(*frags, swap=None):
        """The keyword arguments the fragments spell, as a dict: JSON words read as Python, the text's names swapped for the fixture's."""
        text = ", ".join(frags)
        for old, new in (swap or []) + [("my-x", "home-agent"), ("projects/widgets", "projects/alpha"), ("[work] ", "[home] "),
                                         ("<tomorrow or later, within 7 days, YYYY-MM-DD>", D(1)), ("<day, within 7 days>", D(1)), ("<last day of the window, YYYY-MM-DD>", D(10)), ("<that day>", D(10))]:
            text = text.replace(old, new)
        text = re.sub(r"\btrue\b", "True", text); text = re.sub(r"\bfalse\b", "False", text)
        kw = eval(f"dict({text})", {"__builtins__": {"dict": dict}})
        if isinstance(kw.get("reword"), dict): kw["reword"] = {str(k): v for k, v in kw["reword"].items()}      # JSON keys are strings
        return kw


    def runs(name, tool, frags, fn, *, swap=None, **extra):
        """Check the fragments sit in the description's first CLI_CUT characters, then call the real tool with them."""
        check(f"{name}: the example is in the first {CLI_CUT} characters of {tool}", fragment_ok(tool, frags), ", ".join(flat(frags)))
        try:
            kw = kwargs_of(*flat(frags), swap=swap); kw.update(extra)
            out = fn(**kw)
            check(f"{name}: the server takes the example", True)
            return out
        except ToolError as e:
            check(f"{name}: the server takes the example", False, str(e))
        except Exception as e:
            check(f"{name}: the server takes the example", False, f"{type(e).__name__}: {e}")


    def upd(i, *frags, **kw): return runs(f"update a{i}", "update", frags, lambda **k: _wt_update.stackshot_update(f"a{i}", **k), sender="home-agent", **kw)


    # ---------------------------------------------------------------------------------------------------------------------------------------------------- create
    DEC = ('ask="Decide: whether to approve the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099", '
           'options=[{"label": "Approve", "line": "Approve the schema", "recommended": true}, {"label": "Decline", "line": "Wait a week", "recommended": false}]')
    SUBJ = 'subject="[work] Make the export finish in under a minute"'
    DESC_X = r'description="- Goal: the export finishes in under a minute\n- Problem: the nightly run takes 9 minutes"'
    P = 'project="projects/widgets"'

    out = runs("create: own work", "create", [P, SUBJ, 'sender="my-x"', 'mover="my-x"', DESC_X, 'next="my-x: profile the nightly run"'],
               lambda **k: _wt_create.stackshot_create(**k))
    check("create: own work: written, moved by the sender", bool(out) and "mover: home-agent" in out and "profile the nightly run" in out, out)

    out = runs("create: an item that needs the owner's call", "create",
               [[P, SUBJ, 'sender="my-x"'], [DESC_X, 'next="my-x: profile the nightly run"'], ['needs="decision"', 'then="my-x"'], [DEC]],
               lambda **k: _wt_create.stackshot_create(**k))

    out = runs("create: a step that waits on another item", "create",
               [[P, SUBJ, 'sender="my-x"', 'mover="my-x"', DESC_X], ['next="my-x: ship the export once board#N closes"', 'after=["board#N"]', 'until="<day, within 7 days>"']],
               lambda **k: _wt_create.stackshot_create(**k), swap=[("board#N", "a12")])

    out = runs("create: work for the builder (mover left out)", "create",
               [[P, SUBJ, 'sender="my-x"'], [DESC_X, 'next="my-x: profile the nightly run"']],
               lambda **k: _wt_create.stackshot_create(**k))

    # ---------------------------------------------------------------------------------------------------------------------------------------------------- update
    item(40, next=TWO, owner=AGENT)       # the steps are the agent's own: only the writer of a step rewords it
    item(1, next="home-agent: build it\nhome-agent: test it", owner=AGENT)     # the text's example: steps 1 and 2 open, step 1 finished, step 2 written again as it stands
    upd(1, 'done=[1]', r'next="my-x: test it\nmy-x: open the PR"')
    check("update: done and the next one added", "open the PR" in str(mt(1).get("next")) and "test it" in str(mt(1).get("next")) and "build it" not in str(mt(1).get("next")), mt(1))
    upd(40, 'reword={"2": "my-x: ship the export"}')
    check("update: reword", "ship the export" in str(mt(40).get("next")), mt(40))
    item(41, next=TWO, owner=AGENT)
    upd(41, 'dropped=[2]')
    upd(2, 'work={"text": "PR 83 up", "state": "in progress"}')
    check("update: a step status", "PR 83 up" in json.dumps(mt(2)), mt(2))
    upd(3, 'until="<last day of the window, YYYY-MM-DD>"', 'wait_kind="time"', 'wait_basis="soak ends <that day>"')
    check("update: a park", str(mt(3).get("until", "")).startswith(D(10)) and "hold" not in mt(3), mt(3))
    upd(4, 'until="<tomorrow or later, within 7 days, YYYY-MM-DD>T04:00"', 'wait_reason="the nightly run finishes at 03:00"')
    check("update: a wait until a date on your own item", str(mt(4).get("until", "")).startswith(D(1)), mt(4))
    upd(5, 'after=["board#N"]', 'until="<day, within 7 days>"', swap=[("board#N", "a12")])
    upd(6, DESC_X)
    check("update: a description", "takes 9 minutes" in rd(6)["description"], rd(6)["description"])

    # why the reminder example names a day inside the cap: a far wake with a reason and no wait_basis is refused
    item(9)
    try:
        _wt_update.stackshot_update("a9", sender="home-agent", until="2099-03-02T09:00", wait_reason="the nightly run finishes at 03:00"); check("update: a wake far past the cap without a wait_basis is refused", False)
    except ToolError as e:
        check("update: a wake far past the cap without a wait_basis is refused", "wait_basis" in str(e) or "days" in str(e), str(e))
    check("update: …and the text says a date past the cap needs a wait_basis", "needs a wait_basis" in SNAP["update"]["description"][:CLI_CUT] + SNAP["update"]["parameters"]["until"]["description"])

    # ---------------------------------------------------------------------------------------------------------------------------------------------------- complete
    CLOSE = 'sender="my-x"'
    runs("complete: done", "complete", ['outcome="done"', 'reason="Export shipped in PR 12"', r'outcome_text="- PR 12 merged\n- live on the box"'],
         lambda **k: _wt_complete.stackshot_complete("a7", **k), sender="home-agent")
    check("complete: done: the item is completed", rd(7)["status"] == "completed", rd(7).get("status"))
    item(50)
    runs("complete: dropped", "complete", ['outcome="dropped"', 'reason="No longer needed"', 'outcome_text="- The export moved to another team"'],
         lambda **k: _wt_complete.stackshot_complete("a50", **k), sender="home-agent")
    runs("complete: superseded", "complete", ['outcome="superseded"', 'superseded_by="board#M"', 'reason="Merged into board#M"', 'outcome_text="- Scope moved to board#M"'],
         lambda **k: _wt_complete.stackshot_complete("a51", **k), sender="home-agent", swap=[("board#M", "a52")])

    # ---------------------------------------------------------------------------------------------------------------------------------------------------- message
    # The examples are called through the real function with the text's names swapped for the fixture's. The delivery itself (the hub, a pane) is not under test: a message to a
    # session that is not live is queued, which is a successful reply.
    msg = SNAP["message"]["description"][:CLI_CUT]
    MSGS = [("ask a front agent", 'to="widgets-main", sender="my-x", text="[for the owner]\\nboard#N: decide whether the export ships on Friday; I would ship it."'),
            ("a plain result to the project", 'to="projects/widgets", sender="my-x", text="PR 12 is live", fyi=true'),
            ("a question to a background agent (the id in backticks)", 'to="widgets-builder", sender="my-x", text="Does `board#N` need the export in the nightly run?"'),
            ("a hand-off of a done step (the id as a plain word)", 'to="widgets-builder", sender="my-x", text="board#N: the design is done, build the export"')]
    # a message marked for him starts a front agent's turn only while he is talking with it (or on his ask, service/front_turn.py): stage that, the CLI's registry row of its pane and the stamp of his last prompt
    from stackshot.service import handoff as _handoff
    (T / "cli").mkdir(exist_ok=True); _handoff.CLI_SESSIONS = T / "cli"
    (T / f"cli/{os.getpid()}-home-alpha-main.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": FRONT, "name": "home-alpha-main", "status": "idle", "startedAt": int((now - 7200) * 1000)}))
    (T / "state/prompts").mkdir(parents=True, exist_ok=True); (T / "state/prompts" / FRONT).write_text(f"{time.time() - 60:.0f}\n")
    for what, frag in MSGS:
        check(f"message: {what}: the example is in the first {CLI_CUT} characters", f"message({frag})" in msg, frag)
        out = runs(f"message: {what}", "message", [frag], lambda **k: _wt_message.stackshot_message(**k), swap=[("widgets-main", "home-alpha-main"), ("[for the owner]", _wt_text._FOR_OWNER), ("widgets-builder", "home-builder"), ("board#N", "a12")])
        check(f"message: {what}: the reply says what became of it", bool(out) and out.split()[0].lower().rstrip(":—") in ("delivered", "queued", "held", "inbox", "not"), out)
    check("message: the hand-off sentence and the context-only sentence are both in the first characters",
          "which names the item id, written as a plain word, not in backticks or quotes" in msg and "An item id cited only for context, not handed over, goes in backticks" in msg, msg[-400:])
    check("message: the front-agent example opens with the mark the server asks for", 'text="[for the owner]\\n' in msg, msg[:CLI_CUT])

    # ---------------------------------------------------------------------------------------------------------------------------------------------------- anchors, confirm, route
    P_ = 'project="projects/widgets"'; PR_ = 'add=["https://github.com/acme/widgets/pull/12"]'
    anc = lambda **k: _wt_anchors.stackshot_anchors(**k)
    item(12)
    runs("anchors: list", "anchors", [P_], anc)
    runs("anchors: add one for the project", "anchors", [P_, PR_], anc)
    runs("anchors: scope it to an open item", "anchors", [P_, PR_, 'items=["board#N"]'], anc, swap=[("board#N", "a12")])
    runs("anchors: remove", "anchors", [P_, 'remove=["https://github.com/acme/widgets/pull/12"]'], anc)
    check("anchors: the four examples are written as anchors(...) calls", all(f"anchors({x})" in SNAP["anchors"]["description"][:CLI_CUT] for x in (
          P_, f"{P_}, {PR_}", f'{P_}, {PR_}, items=["board#N"]', f'{P_}, remove=["https://github.com/acme/widgets/pull/12"]')), SNAP["anchors"]["description"][:900])

    item(8)
    runs("confirm", "confirm", ['item_id="board#N", sender="my-x"'], lambda **k: _wt_complete.stackshot_confirm(**k), swap=[("board#N", "a8")])
    check("confirm: the example is written as confirm(...)", 'confirm(item_id="board#N", sender="my-x")' in SNAP["confirm"]["description"][:CLI_CUT])

    nid = _routing.record("projects/alpha", kind="board", to=AGENT, label="board note", who="hub", text="a note for the export work", target="project-wide")
    out = runs("route", "route", ['notice="a1b2c3", ruling="passed", to="my-x", reason="belongs to the export work", sender="my-x"'], lambda **k: _wt_route.stackshot_route(**k),
               swap=[("a1b2c3", nid), ('to="my-x"', 'to="home-builder"')])
    check("route: the example is written as route(...)", 'route(notice="a1b2c3", ruling="passed", to="my-x", reason="belongs to the export work", sender="my-x")' in SNAP["route"]["description"][:CLI_CUT])
    check("route: the reply names the ruling", bool(out) and "ruled" in out and "passed" in out, out)

    # ---- the check= example: it sits in the parameter text of create and update (and in the update description after the first characters), so it is called here with the whole text searched
    item(10)
    CHK = 'next="other-x: build the export", check="pr_merged acme/widgets#12"'
    check("update: the check example is in the parameter text and the description", 'check="pr_merged acme/widgets#12"' in SNAP["update"]["parameters"]["check"]["description"] and 'check="pr_merged acme/widgets#12"' in SNAP["update"]["description"],
          SNAP["update"]["parameters"]["check"]["description"][:300])
    try:
        out = _wt_update.stackshot_update("a10", sender="home-agent", **kwargs_of(CHK, swap=[("other-x", "home-builder")])); check("update a10: the server takes the check example", True)
        check("update a10: the check is stored", "pr_merged" in json.dumps(mt(10)), mt(10))
    except ToolError as e:
        check("update a10: the server takes the check example", False, str(e))

    try:
        out = _wt_create.stackshot_create(sender="home-agent", mover="home-agent", **kwargs_of(P, SUBJ, DESC_X, CHK, swap=[("other-x", "home-builder")])); check("create: the server takes the check example", bool(out) and "created" in out, out)
    except ToolError as e:
        check("create: the server takes the check example", False, str(e))
    check("create: the check example is in the parameter text", 'check="pr_merged acme/widgets#12"' in SNAP["create"]["parameters"]["check"]["description"])

    return ran, fails


MARK = "@@tool_text part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"text": part_text, "examples": part_examples}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as each suite always ended: server.py starts threads of its own, and nothing a thread left behind holds the process (tests/_scratch.py removes the scratch folders first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: tool_text scenario, {total} checks")
