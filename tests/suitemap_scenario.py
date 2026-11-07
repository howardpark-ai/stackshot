"""Scenario test for tests/suitemap.py, the suite selection of CI (Tue Oct 27th 2026) — a throwaway git repo
with four tiny suites, no live store, no network.

The repo is measured for real (coverage, and strace when it is on the box and this process is not already traced: a
process has one tracer, so on main, where this suite itself runs under strace, the file half is checked on a written log
instead). Then each rule is checked against a commit made for it: a function body reaches the suites that ran it, the
module level every suite that ran the file, a comment only the suites that read the file as text, a data file the suites
that opened it, the harness all; and the audit reports a suite the earlier map skipped.

    tests/run-suite suitemap        → exit 0 / 1"""
import importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile, textwrap
SCR = os.path.dirname(os.path.abspath(__file__))
import _scratch
tmp = _scratch.mkdtemp(prefix="suitemaptest-"); T = pathlib.Path(tmp)
R = T / "repo"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

def git(*a): return subprocess.run(["git", "-C", str(R), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout
def write(rel, text): p = R / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(text).lstrip("\n"))
def commit(msg): git("add", "-A"); git("commit", "-qm", msg); return git("rev-parse", "HEAD").strip()

R.mkdir()
git("init", "-q", "-b", "main")
(R / "tests").mkdir(); shutil.copy(os.path.join(SCR, "suitemap.py"), R / "tests" / "suitemap.py")
# the suites run with this interpreter, which has coverage: the stand-in for tests/run-suite's shared environment
write("tests/run-suite", f"""
    #!/bin/sh
    here=$(cd "$(dirname "$0")" && pwd)
    exec {sys.executable} "$here/${{1}}_scenario.py"
""")
os.chmod(R / "tests/run-suite", 0o755)
write("mod.py", '''
    """a module"""
    import functools
    import cfgmod as _c
    from typing import Annotated
    from pydantic import Field
    LIMIT = 3
    ANN = str
    _P = Annotated[str, Field(min_length=1)]
    _DEF = "a"
    REG = []

    def deco(fn):
        @functools.wraps(fn)
        def w(*a): return fn(*a)
        return w

    def f():
        return LIMIT + 1

    def g():
        return "g"

    def typed(x: ANN) -> ANN:
        return x

    def h():
        return "h"

    @deco
    def tool():
        """the tool's description, read at import by deco"""
        return 1

    class K:
        size = 2
        def m(self, x: _P = _DEF):
            return self.size
        @staticmethod
        def s():
            """a static method's docstring"""
            return 7

    class Registry:
        def __init__(self):
            self.entries = {}
        def tool(self, desc):
            def add(fn):
                self.entries[fn.__name__] = desc
                return fn
            return add
        def list_tools(self):
            return sorted(self.entries.items())

    reg = Registry()

    @reg.tool(desc="hands back five")
    def handler():
        return 5
''')
write("cfgmod.py", 'NAME = "x"\n\ndef configure(v):\n    return v\n')
# a manual check (no suite runs it): its import-time call into cfgmod reads mod.LIMIT, which must not take cfgmod.py whole
write("tests/w_check.py", '''
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import cfgmod, mod
    cfgmod.configure(mod.LIMIT)
''')
write("data.txt", "one\n")
write("helper.sh", "#!/bin/sh\necho helped\n")
write("README.md", "docs\n")
write("docs/guide.md", "a guide\n")
write("x.py.lock", "lock\n")
write(".gitignore", "__pycache__/\n")   # as the checkout's: the bytecode measure compiles is never committed
# a: runs f and K.m, reads data.txt; b: runs g in-process and h in a subprocess, runs helper.sh; c: reads mod.py as text and
# lists docs/ (a, b and z list the checkout and tests/ too: the import machinery lists every sys.path directory it searches)
write("tests/a_scenario.py", '''
    import os, sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
    import mod
    assert mod.f() == 4 and mod.K().m() == 2 and mod.K.s() == 7 and mod.handler() == 5 and mod.typed('t') == 't'
    assert open(os.path.join(ROOT, "data.txt")).read()
''')
write("tests/b_scenario.py", '''
    import os, subprocess, sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
    import mod
    assert mod.g() == "g" and mod._c.NAME == "x" and mod.reg.list_tools()
    assert subprocess.run([sys.executable, "-c", "import mod; assert mod.h() == 'h'"], cwd=ROOT).returncode == 0
    assert subprocess.run(["sh", os.path.join(ROOT, "helper.sh")], capture_output=True).returncode == 0
    os._exit(0)
''')
# z only imports mod: it is reached by a change with effects at import, by nothing else
write("tests/z_scenario.py", '''
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import mod
''')
write("tests/c_scenario.py", '''
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert "def f" in open(os.path.join(ROOT, "mod.py")).read() and os.listdir(os.path.join(ROOT, "docs"))
''')
base = commit("base")

def traced():
    try: return int(next(l for l in open("/proc/self/status") if l.startswith("TracerPid:")).split()[1]) != 0
    except Exception: return True
use_strace = shutil.which("strace") is not None and not traced()
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "SUITEMAP_", "GITHUB_"))}
ENV.update(SUITEMAP_ROOT=str(R), SUITEMAP_STRACE="1" if use_strace else "0")
def tool(*a, env=None):
    return subprocess.run([sys.executable, str(R / "tests/suitemap.py"), *a], capture_output=True, text=True, env={**ENV, **(env or {})}, cwd=str(R))

r = tool("list")
check("list: the four suites, sorted", r.stdout.split() == ["a", "b", "c", "z"], (r.stdout, r.stderr))
MAP = T / "map.json"
r = tool("measure", "--map", str(MAP), "-T", "120")
check("measure: every suite passes measured and the map is written", r.returncode == 0 and MAP.exists(), (r.stdout, r.stderr[-1500:]))
m = json.loads(MAP.read_text()) if MAP.exists() else {"suites": {}, "commit": ""}
S = m["suites"]
check("map: of the measured commit, all three suites clean", m["commit"] == base and all(S.get(s, {}).get("ok") for s in "abcz"), m.get("commit"))
check("map: a ran f and K.m and the module level, not g or h", {"", "f", "K.m"} <= set(S.get("a", {}).get("py", {}).get("mod.py", [])) and not {"g", "h"} & set(S.get("a", {}).get("py", {}).get("mod.py", [])), S.get("a"))
check("map: b ran g, and h in its subprocess (coverage follows the child)", {"g", "h"} <= set(S.get("b", {}).get("py", {}).get("mod.py", [])), S.get("b"))
check("map: c never imported mod.py", "mod.py" not in S.get("c", {}).get("py", {}), S.get("c"))
if use_strace:
    check("map (strace): a opened data.txt, b ran helper.sh, c read mod.py whole",
          "data.txt" in S["a"].get("files", []) and "helper.sh" in S["b"].get("files", []) and "mod.py" in S["c"].get("whole", []), (S["a"], S["b"], S["c"]))
    check("map (strace): c listed docs/; a, b and z the checkout (the import machinery searching sys.path)",
          "docs" in S["c"].get("dirs", []) and all("" in S[x].get("dirs", []) for x in "abz"), {x: S[x].get("dirs") for x in "abcz"})
    check("map (strace): a and b import mod.py, which is not a text read for them", "mod.py" not in S["a"].get("whole", []) + S["b"].get("whole", []), (S["a"].get("whole"), S["b"].get("whole")))
else:
    print("note: strace off (missing, or this process is already traced): the file half is checked on a written log below")
    # the file half of the map as strace would give it, so the selection rules below still have it
    S["a"].update(files=["data.txt"], whole=[], dirs=["", "tests"]); S["b"].update(files=["helper.sh"], whole=[], dirs=["", "tests"])
    S["c"].update(files=[], whole=["mod.py"], dirs=["docs"]); S["z"].update(files=[], whole=[], dirs=["", "tests"])
    m["strace"] = True; MAP.write_text(json.dumps(m))

def sel_after(edit, msg, *, to_base=True):
    """apply an edit on a branch from base, commit it, return what select prints and its reasons"""
    git("checkout", "-q", "-B", f"t{len(ran)}", base)
    edit()
    head = commit(msg)
    r = tool("select", "--map", str(MAP), "--to", head)
    return r.stdout.strip(), r.stderr, head

def sub(rel, a, b):
    p = R / rel; t = p.read_text(); assert a in t, (rel, a); p.write_text(t.replace(a, b, 1))

out, err, _ = sel_after(lambda: sub("mod.py", "return LIMIT + 1", "return LIMIT + 2"), "f body")
check("a function body reaches the suites that ran it (and the text reader)", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", 'return "h"', 'return "h" '), "h body")
check("a function run only in a subprocess still reaches its suite", out.split() == ["b", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "LIMIT = 3", "LIMIT = 4"), "constant")
check("a constant reaches the suites that ran a function reading it (f: a), not every importer, nor through a manual "
      "check's import-time call (tests/w_check.py: no suite runs it)", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "ANN = str", "ANN = int"), "annotation constant")
check("a constant a function header annotates with reaches the suites that call that function (a), not every importer", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "REG = []", "REG = []\nREG.append(1)"), "import-time call")
check("a module-level statement with effects (a call) reaches every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "def h():", "def fresh():\n    return 0\n\n\ndef h():"), "new function")
check("a new function nothing reads reaches no suite by code (only the text reader)", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "def g():", "def g(x=None):"), "signature")
check("a signature change reaches the suites that read the function (b calls mod.g)", out.split() == ["b", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "@deco\ndef tool():", "@deco\ndef tool(x=1):"), "decorated header")
check("a decorated function's header is module level with effects: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", 'desc="hands back five"', 'desc="hands back 5"'), "registered description")
check("a registered function's description (@reg.tool on the module's own object) reaches its caller and what lists the registry",
      out.split() == ["a", "b", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("cfgmod.py", '"x"', '"y"'), "chained constant")
check("a name read through another module's import (mod._c.NAME) reaches the suite that reads it so", out.split() == ["b"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "import cfgmod as _c", "import cfgmod as _c\nimport cfgmod as _c2"), "quiet import")
check("an import of one of ours that only binds names is a binding, not an effect", out.split() == ["c"], (out, err))
HDR = "import cfgmod as _c"
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\n_PARAM = Annotated[str, Field(description='a parameter')]"), "field constant")
check("a tool-parameter constant (Annotated[..., Field(...)]) only binds a name: it reaches its readers, not every importer", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom pathlib import Path\nHERE = Path(__file__).resolve().parent"), "path chain")
check("Path(__file__).resolve().parent only binds a name (the path of the file itself)", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "Field(min_length=1)", "Field(min_length=9)"), "method annotation constant")
check("a constant a method's header annotates with reaches the suites that ran the method (a), not only the text reader", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", '_DEF = "a"', '_DEF = "b"'), "method default")
check("a constant a method's default reads is read when the class body runs: the suites that ran the class (a)", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom pathlib import Path\nTHERE = Path(__file__).parent.joinpath('x').with_suffix('.y').resolve().as_posix()"), "path chain methods")
check("a chain of path methods from Path(__file__) only binds a name", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom pathlib import Path\nUP = Path(__file__).parent.resolve().parents[0].absolute()"), "path subscript")
check("a path chain through an attribute and a subscript only binds a name", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nclass _R:\n    def resolve(self):\n        print('side effect')\n_r = _R()\nV = _r.resolve()"), "resolve on our own object")
check("resolve() on a receiver that is not a path (an instance of our own class) is an effect: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nV = _c.configure(1).joinpath('x')"), "joinpath on a call result")
check("joinpath on the result of a call that is not Path(...) is an effect: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom pathlib import Path\nOUT = Path(__file__).resolve().write_text('x')"), "path write")
check("a Path chain that writes (write_text) is an effect: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom mcp.server.fastmcp import FastMCP\nmcp = FastMCP('x')"), "server object")
check("a FastMCP(...) server object registers the server at import: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nUNKNOWN = frobnicate(1)"), "unknown call")
check("an unknown call in an assignment stays an effect: every suite that ran the file", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", HDR, HDR + "\nfrom pydantic import Field\n_BAD = Field(default=open('x'))"), "field with call")
check("a Field(...) whose arguments hold an impure call stays an effect", out == "all", (out, err))
def new_module():
    write("newmod.py", "def _on():\n    return 1\n\n\nFLAG = _on()\n")
    sub("mod.py", "import cfgmod as _c", "import cfgmod as _c\nimport newmod as _n")
out, err, _ = sel_after(new_module, "new module import")
check("an import of a new module of ours (no suite ran it) reaches every suite that ran the importing file, even if the module "
      "only binds names (its module-level call now runs there)", out == "all" and "mod.py: whole" in err, (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "def g():", "# g says g\ndef g():"), "comment")
check("a comment-only change reaches only the suite that reads the file as text", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "the tool's description", "the tool's new description"), "decorated docstring")
check("a decorated function's docstring is module level (a decorator reads it at import)", out == "all", (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "a static method's docstring", "a static method's new docstring"), "static docstring")
check("a docstring under a decorator that only wraps (@staticmethod) is the function's own body", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "return self.size", "return self.size * 1"), "method body")
check("a method body reaches the suites that ran the method", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "    size = 2", "    size = 2\n    other = 3"), "class body")
check("a class body change reaches what uses the class (a) and what its methods run", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("data.txt", "one", "two"), "data")
check("a data file reaches the suites that opened it", out.split() == ["a"], (out, err))
# a suite that runs other suites as its checks (INNER: scratch runs rename, redact, lead, migration) is selected with them
git("checkout", "-q", "-B", f"t{len(ran)}", base); sub("data.txt", "one", "two"); inner_head = commit("data for inner")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import suitemap as s; s.INNER = {'z': ('a',)}; "
                    "m = s.load_map(sys.argv[1]); sel, why = s.selection(m, m['commit'], sys.argv[2]); print(' '.join(sorted(sel)))", str(MAP), inner_head],
                   capture_output=True, text=True, env=ENV, cwd=str(R))
check("a suite that runs another suite (INNER) is chosen when its inner suite is: z runs a, a opened the data file", r.stdout.split() == ["a", "z"], (r.stdout, r.stderr[-600:]))
real = (pathlib.Path(SCR) / "scratch_scenario.py").read_text(encoding="utf-8")
sm = importlib.util.spec_from_file_location("suitemap_real", os.path.join(SCR, "suitemap.py")); smod = importlib.util.module_from_spec(sm); sm.loader.exec_module(smod)
named = set(re.findall(r'for name in \(([^)]*)\)', real)[0].replace('"', '').replace(" ", "").split(",")) | {"migration"}
check("INNER's scratch lists exactly the suites scratch_scenario.py runs (its real-suite loop and the migration suite)", set(smod.INNER.get("scratch", ())) == named,
      (smod.INNER, named))
out, err, _ = sel_after(lambda: sub("helper.sh", "helped", "helped!"), "script")
check("a shell script reaches the suites that ran it", out.split() == ["b"], (out, err))
out, err, _ = sel_after(lambda: sub("README.md", "docs", "more docs"), "docs")
check("a doc no suite touches reaches no suite (an empty line)", out == "" and "no suite touches it" in err, (out, err))
out, err, _ = sel_after(lambda: write("docs/new.md", "new\n"), "new doc")
check("a new file in a directory a suite lists reaches that suite (c lists docs/)", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: write("notes/x.md", "x\n"), "new dir")
check("a new file in a directory no measured suite lists: every suite (it may be looked up by a name nobody tried)",
      out == "all" and "no measured suite lists (notes/)" in err, (out, err))
out, err, _ = sel_after(lambda: git("mv", "data.txt", "data2.txt"), "renamed data")
check("a renamed data file: the suites that touched the old path (a) and those that listed either directory (a, b, z)", out.split() == ["a", "b", "z"], (out, err))
out, err, _ = sel_after(lambda: git("rm", "-q", "cfgmod.py"), "deleted module")
check("a deleted module reaches every suite that ran it", out.split() == ["a", "b", "z"], (out, err))
out, err, _ = sel_after(lambda: git("mv", "cfgmod.py", "cfgmod2.py"), "renamed module")
check("a renamed module reaches every suite that ran it under its old name", out.split() == ["a", "b", "z"], (out, err))
out, err, _ = sel_after(lambda: sub("x.py.lock", "lock", "lock2"), "lock")
check("a script's lock reaches no suite (the lock step checks it)", out == "", (out, err))
out, err, _ = sel_after(lambda: sub("tests/b_scenario.py", 'mod.g() == "g"', 'mod.g() == "g" and True'), "suite")
check("a suite's own file runs that suite", out.split() == ["b"], (out, err))
out, err, _ = sel_after(lambda: write("tests/d_scenario.py", "print('d')\n"), "new suite")
check("a new suite runs (it has no measurement yet)", out.split() == ["d"], (out, err))
out, err, _ = sel_after(lambda: write("newmod.py", "def x(): return 1\n"), "new module")
check("a new module no suite imports reaches no suite by itself", out == "", (out, err))
out, err, _ = sel_after(lambda: write("json.py", "x = 1\n"), "shadowing module")
check("a new module named like one the suites import (json) runs all", out == "all" and "'json'" in err, (out, err))
out, err, _ = sel_after(lambda: sub("tests/run-suite", "exec", "exec "), "harness")
check("the harness reaches all", out == "all", (out, err))
out, err, _ = sel_after(lambda: write(".github/workflows/tests.yml", "name: tests\n"), "workflow")
check("the workflow reaches all", out == "all", (out, err))
for rel, edit in (("tests/pyproject.toml", lambda: write("tests/pyproject.toml", "[project]\nname = 't'\n")),
                  ("tests/uv.lock", lambda: write("tests/uv.lock", "version = 1\n")),
                  ("tests/suitemap.py", lambda: sub("tests/suitemap.py", "FORMAT = 1", "FORMAT = 1  # a comment"))):
    out, err, _ = sel_after(edit, rel)
    check(f"the harness's {rel} reaches all, even a comment", out == "all" and "the harness" in err, (out, err))

# no map, a broken map, an unknown commit: all
_, _, head = sel_after(lambda: sub("data.txt", "one", "three"), "data again")
r = tool("select", "--map", str(T / "none.json"), "--to", head)
check("no map: all", r.stdout.strip() == "all", r.stdout)
(T / "bad.json").write_text("{not json")
r = tool("select", "--map", str(T / "bad.json"), "--to", head)
check("an unreadable map: all", r.stdout.strip() == "all", r.stdout)
m2 = dict(m, commit="0" * 40); (T / "gone.json").write_text(json.dumps(m2))
r = tool("select", "--map", str(T / "gone.json"), "--to", head)
check("a map of a commit that does not resolve: all", r.stdout.strip() == "all", (r.stdout, r.stderr))
m3 = json.loads(MAP.read_text()); m3["suites"]["b"]["ok"] = False; (T / "dirty.json").write_text(json.dumps(m3))
r = tool("select", "--map", str(T / "dirty.json"), "--to", head)
check("a suite without a clean measurement always runs", r.stdout.split() == ["a", "b"], (r.stdout, r.stderr))
summ = T / "summary.md"
r = tool("select", "--map", str(MAP), "--to", head, env={"GITHUB_STEP_SUMMARY": str(summ)})
check("select writes its choice and the reasons to the job summary", summ.exists() and "Suites: 1 of 4" in summ.read_text() and "`data.txt`" in summ.read_text(), summ.read_text() if summ.exists() else None)

# audit: an earlier map that knew nothing of b running g skips b for a change to g; the new map reaches it: a miss
m4 = json.loads(MAP.read_text()); m4["suites"]["b"]["py"]["mod.py"] = [""]; (T / "old.json").write_text(json.dumps(m4))
_, _, head = sel_after(lambda: sub("mod.py", 'return "g"', 'return "g" '), "g body")
r = tool("audit", "--old", str(T / "old.json"), "--new", str(MAP), "--to", head, env={"GITHUB_STEP_SUMMARY": str(summ)})
check("audit: a suite the earlier map skipped and the new one reaches is a miss (exit 1, named)", r.returncode == 1 and "selection miss" in r.stdout and "b" in r.stdout.split("reaches ")[1].split(" by")[0], (r.returncode, r.stdout, r.stderr))
m5 = json.loads(MAP.read_text()); m5["suites"]["z"]["failed"] = True; (T / "broke.json").write_text(json.dumps(m5))
r = tool("audit", "--old", str(MAP), "--new", str(T / "broke.json"), "--to", head)
check("audit: a suite that failed on main and that the choice skipped is a miss by name", r.returncode == 1 and "z failed on main" in r.stdout, (r.returncode, r.stdout, r.stderr))
r = tool("audit", "--old", str(MAP), "--new", str(MAP), "--to", head)
check("audit: the same map, no miss (exit 0)", r.returncode == 0 and "no miss" in r.stderr, (r.returncode, r.stdout, r.stderr))
# a suite that failed only when measured has `ok: false` in the new map: the selection runs it always, which is not a reach of the change
m6 = json.loads(MAP.read_text()); m6["suites"]["z"]["ok"] = False; (T / "unclean.json").write_text(json.dumps(m6))
r = tool("audit", "--old", str(MAP), "--new", str(T / "unclean.json"), "--to", head)
check("audit: a suite with no clean measurement in the new map is no miss (exit 0)", r.returncode == 0 and "no miss" in r.stderr, (r.returncode, r.stdout, r.stderr))
r = tool("audit", "--old", str(T / "old.json"), "--new", str(T / "unclean.json"), "--to", head)
check("audit: …and a real miss beside it is still named, without the unclean suite",
      r.returncode == 1 and r.stdout.split("reaches ")[1].split(" by")[0].split(", ") == ["b"], (r.returncode, r.stdout, r.stderr))
r = tool("audit", "--old", str(T / "none.json"), "--new", str(MAP), "--to", head)
check("audit: no earlier map (the first main run), skipped", r.returncode == 0 and "skipped" in r.stderr, (r.returncode, r.stderr))
# the range is the old map's commit..the push on both sides: a change before the push's `before` (a queued main run replaced
# by a newer one leaves no map of its own) is checked too. Here g changes (the old map skips b for it), then data.txt.
git("checkout", "-q", "-B", "two-pushes", base); sub("mod.py", 'return "g"', 'return "g"  '); commit("g, in a run replaced while queued")
sub("data.txt", "one", "five"); head2 = commit("data, the push that ran")
r = tool("audit", "--old", str(T / "old.json"), "--new", str(MAP), "--to", head2)
check("audit: a change since the old map's commit, before the push's own `before`, is checked (b, for g)",
      r.returncode == 1 and "selection miss" in r.stdout and "b" in r.stdout.split("reaches ")[1].split(" by")[0], (r.returncode, r.stdout, r.stderr))
m7 = json.loads(MAP.read_text()); m7["commit"] = "0" * 40; (T / "nowhere.json").write_text(json.dumps(m7))
r = tool("audit", "--old", str(T / "nowhere.json"), "--new", str(MAP), "--to", head2)
check("audit: an old map whose commit does not resolve fails it (nothing was checked), never 'ran every suite'",
      r.returncode == 1 and "could not check" in r.stdout and "ran every suite" not in r.stderr, (r.returncode, r.stdout, r.stderr))
git("checkout", "-q", "main")

# a later main run with the earlier map: only the suites the change reaches are traced again, the rest keep their files
if use_strace:
    git("checkout", "-q", "-B", "remeasure", base); sub("data.txt", "one", "four"); head = commit("data for a remeasure")
    MAP2 = T / "map2.json"
    r = tool("measure", "--prev", str(MAP), "--map", str(MAP2), "-T", "120")
    m6 = json.loads(MAP2.read_text()) if MAP2.exists() else {"suites": {}}
    check("measure --prev: traces only the suite the change reaches (a), the others keep their file half",
          r.returncode == 0 and "tracing 1 of 4" in r.stderr and m6["suites"].get("b", {}).get("files") == S["b"]["files"]
          and m6["suites"]["b"].get("traced") == S["b"].get("traced") and m6["suites"]["a"].get("traced") != S["a"].get("traced"),
          (r.returncode, r.stderr[-800:], m6["suites"].get("b")))
    git("checkout", "-q", "main")

    # a suite that fails only when measured (the release suite, which timed out at the measuring limit while it passes plainly) is `ok: false`: it keeps its last clean measurement beside the
    # new one as `carry`, with the commit that measurement was made at, and a second such run keeps the same carry (tools/retest_skip.py reads it; the selection above still runs the suite)
    git("checkout", "-q", "-B", "carry", base)
    write("tests/m_scenario.py", '''
        import os, time
        if "COVERAGE_PROCESS_START" in os.environ:   # passes plainly, fails (late: a measured run is slow) under the measurement
            time.sleep(2); raise SystemExit(1)
    ''')
    commit("a suite that fails only when measured")
    prevm = json.loads(MAP.read_text()); prevm["suites"]["m"] = dict(prevm["suites"]["a"]); PREVM = T / "prev-m.json"; PREVM.write_text(json.dumps(prevm))
    MAP3, MAP4 = T / "map3.json", T / "map4.json"
    r = tool("measure", "--prev", str(PREVM), "--map", str(MAP3), "-T", "120", "m")
    m3 = json.loads(MAP3.read_text()) if MAP3.exists() else {"suites": {}}
    e3 = m3["suites"].get("m", {})
    check("measure: a suite that fails only when measured is not ok, passes the plain rerun (exit 0) and carries its earlier clean measurement and the commit it was made at",
          r.returncode == 0 and e3.get("ok") is False and not e3.get("failed") and e3.get("carry", {}).get("at") == base
          and e3["carry"].get("files") == prevm["suites"]["m"]["files"] and e3["carry"].get("py") == prevm["suites"]["m"]["py"] and e3["carry"].get("traced") == prevm["suites"]["m"]["traced"]
          and e3.get("measured_seconds", 0) >= 2 and e3.get("seconds", 9) < e3["measured_seconds"],
          (r.returncode, r.stdout[-600:], r.stderr[-600:], e3))
    r = tool("measure", "--prev", str(MAP3), "--map", str(MAP4), "-T", "120", "m")
    e4 = json.loads(MAP4.read_text())["suites"].get("m", {}) if MAP4.exists() else {}
    check("measure: failing measured again keeps the same carry (the commit of the clean measurement, not of the unclean map)", e4.get("ok") is False and e4.get("carry") == e3.get("carry"), (r.stderr[-400:], e4))
    git("checkout", "-q", "main")

# strace's log, read: threads belong to their process, a Python that left no coverage data is read whole, a split clone
sys.path.insert(0, str(R / "tests")); os.environ["SUITEMAP_ROOT"] = str(R)
import importlib; sm = importlib.import_module("suitemap")
cl = {"ok": True, "py": {"x.py": [""]}, "files": ["f"], "whole": [], "dirs": [""], "traced": "2026-11-02T07:00:00+00:00"}
pv = {"commit": "c" * 40, "suites": {"clean": cl, "bad": {**cl, "ok": False, "carry": {**cl, "at": "d" * 40}}, "bad0": {**cl, "ok": False}, "gone": {**cl, "failed": True},
                                     "nofiles": {k: v for k, v in cl.items() if k != "files"}}}
pm = {"suites": {"x": {"seconds": 280, "measured_seconds": 2400}, "y": {"seconds": 1000}, "z": {"seconds": 1000}}}
check("shard plan: a suite that timed out measured is planned by its measured time, not the plain one it was rerun in (it fills a shard alone)",
      sorted(map(sorted, sm.shard_plan(["x", "y", "z"], 2, pm))) == [["x"], ["y", "z"]], sm.shard_plan(["x", "y", "z"], 2, pm))
check("carried: a clean entry is kept with the commit of its map; an unclean one gives up the carry it has; none for one that failed plainly, lacks a file half, has no carry or is unknown",
      sm.carried(pv, "clean") == {**{k: cl[k] for k in sm.CARRY_KEYS}, "at": "c" * 40} and sm.carried(pv, "bad") == {**cl, "at": "d" * 40}
      and all(sm.carried(pv, n) is None for n in ("bad0", "gone", "nofiles", "nosuch")) and sm.carried(None, "clean") is None, [sm.carried(pv, n) for n in pv["suites"]])
log = T / "strace.log"
log.write_text(textwrap.dedent(f"""\
    100 execve("{sys.executable}", ["python", "x"], 0x0 /* 1 vars */) = 0
    100 clone3({{flags=CLONE_VM|CLONE_THREAD|CLONE_SIGHAND, exit_signal=0}} <unfinished ...>
    100 <... clone3 resumed> => {{parent_tid=[101]}}, 88) = 101
    101 openat(AT_FDCWD<{R}>, "mod.py", O_RDONLY|O_CLOEXEC) = 3<{R}/mod.py>
    100 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|SIGCHLD, child_tidptr=0x0) = 200
    200 execve("/usr/bin/python3", ["python3", "-c", "import mod"], 0x0 /* 1 vars */) = 0
    200 newfstatat(AT_FDCWD<{R}>, "{R}/newmod.py", {{st_mode=S_IFREG|0664, st_size=1, ...}}, 0) = 0
    100 newfstatat(AT_FDCWD<{R}>, "data.txt", 0x7ffd, 0) = -1 ENOENT (No such file or directory)
    100 openat(AT_FDCWD<{R}>, "{R}/docs", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 4<{R}/docs>
    100 openat(AT_FDCWD<{R}>, "/etc/passwd", O_RDONLY) = 3</etc/passwd>
"""))
files, whole, dirs, unm = sm.read_strace(str(log), {"mod.py", "newmod.py", "data.txt", "docs/new.md"}, {"", "docs"}, {"100"})
check("strace log: a thread's text read counts for its measured process", "mod.py" in whole, whole)
check("strace log: a Python that left no coverage data (system python3) has its files whole", "newmod.py" in whole and unm == ["200"], (whole, unm))
check("strace log: a failed lookup of a tracked file is a touch, a listed directory is kept, paths outside are not",
      files == {"data.txt"} and dirs == {"docs"}, (files, dirs))
check("scopes: nested functions and methods are named; a def line is its parent's (a method's: the class body, module level)", (lambda b: (b[0][7], b[0][8]))(sm.scopes("def a():\n    x = 1\n    def b():\n        return 2\n    return b\nclass C:\n    def m(self):\n        return 3\n")) == ("", "C.m")
      and sm.scopes("def a():\n    x = 1\n    def b():\n        return 2\n")[0][3] == "a" and sm.scopes("def a():\n    x = 1\n    def b():\n        return 2\n")[0][4] == "a.<locals>.b", None)

# ---- a CI cancel, as the runner does it: SIGINT to the step's top process alone, SIGTERM 7.5 s later, a kill 2.5 s after that
# (actions/runner ProcessInvoker.cs), never to its process group. A checkout of its own with the real tests/run-suite, pyproject and
# lock, so the chain is CI's: exec uv run → suitemap.py → timeout (→ strace) → run-suite → uv → the suite.
import re, signal, time
STEP = "exec uv run --locked --project tests python tests/suitemap.py"
wf = open(os.path.join(SCR, "..", ".github", "workflows", "tests.yml"), encoding="utf-8").read().split("\n")
at = [i for i, l in enumerate(wf) if re.search(r"\bsuitemap\.py (run|measure) ", l)]
last = [next((len(l) - len(l.lstrip()) < len(wf[i]) - len(wf[i].lstrip()) for l in wf[i + 1:] if l.strip()), True) for i in at]
# three steps run a suite: the PR's selection (run), a manual run of named suites (run) and main's measured run (measure)
check("tests.yml: every suite step ends with `exec uv run … suitemap.py run|measure`: without exec, a cancel's signal stops at the step's shell",
      len(at) == 3 and all(re.match(r"\s*(run:\s*)?" + re.escape(STEP) + r" (run|measure) ", wf[i]) for i in at) and all(last), [wf[i] for i in at])

# ---- main's measured run in shards (Mon Nov 2nd 2026): every suite of this checkout in exactly one shard, with and without a map; the workflow's matrix agrees
import yaml
REAL_ENV = {k: v for k, v in ENV.items() if k != "SUITEMAP_ROOT"}   # the real checkout: the suites CI shards
def real(*a): return subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), *a], capture_output=True, text=True, env=REAL_ENV)
every = real("list").stdout.split()
def plan_of(*extra): return [real("shard", "--of", str(sm.SHARDS), "--index", str(i), *extra).stdout.split() for i in range(sm.SHARDS)]
def once(plan): return sorted(x for p in plan for x in p) == sorted(every) and len(every) > sm.SHARDS
nomap = plan_of()
check(f"shards: with no map, every suite of this checkout is in exactly one of the {sm.SHARDS} shards, and none is empty", once(nomap) and all(nomap), [len(p) for p in nomap])
check("shards: with no map the plan is a stable hash of the name (the same twice)", plan_of() == nomap)
TIMES = T / "times.json"   # measured times for all but the first suite (a new one: counted as the median)
TIMES.write_text(json.dumps({"format": sm.FORMAT, "commit": "f" * 40, "suites": {n: {"seconds": 5 + (i * 37) % 300} for i, n in enumerate(every) if i}}))
timed = plan_of("--map", str(TIMES))
secs = {n: 5 + (i * 37) % 300 for i, n in enumerate(every) if i}; med = sorted(secs.values())[len(secs) // 2]
loads = [sum(secs.get(n, med) for n in p) for p in timed]
check("shards: with a map, every suite is in exactly one shard, and the shards' measured times differ by no more than the longest suite",
      once(timed) and max(loads) - min(loads) <= max(secs.values()), loads)
check("shards: an index outside 0..N-1 is refused", real("shard", "--of", "6", "--index", "6").returncode == 2)
y = yaml.safe_load(open(os.path.join(SCR, "..", ".github", "workflows", "tests.yml"), encoding="utf-8"))
pj, mj, uj = y["jobs"]["shards"], y["jobs"]["measure"], y["jobs"]["suites"]
plan_step = next(st for st in pj["steps"] if st.get("id") == "plan")
measure_step = next(st for st in mj["steps"] if st.get("name") == "run this shard's suites, measured")
suites_steps = [st.get("name") for st in uj["steps"]]
MAIN_PUSH = "github.event_name == 'push' && github.ref == 'refs/heads/main'"
check(f"tests.yml: the measure job runs on a push to main only, after the plan, as a matrix of 0..{sm.SHARDS - 1} with fail-fast off",
      pj["if"].split("#")[0].strip() == MAIN_PUSH and mj["if"].split("#")[0].strip() == MAIN_PUSH and mj["needs"] == "shards"
      and mj["strategy"]["matrix"]["shard"] == list(range(sm.SHARDS)) and mj["strategy"]["fail-fast"] is False, (mj.get("strategy"), mj.get("needs")))
# one plan: made once, in the shards job, from the map, handed on as six outputs; every shard of the matrix runs the list it is given and plans nothing
check(f"tests.yml: the plan is made once, by the shards job: `suitemap.py plan --of {sm.SHARDS}` with the cached map, and its {sm.SHARDS} lists are the job's outputs",
      f"suitemap.py plan --of {sm.SHARDS} " in plan_step["run"] and "--map .suitemap/map.json" in plan_step["run"] and "GITHUB_OUTPUT" in plan_step["run"]
      and pj["outputs"] == {f"shard{i}": "${{ steps.plan.outputs.shard%d }}" % i for i in range(sm.SHARDS)}, (plan_step["run"], pj.get("outputs")))
check("tests.yml: every shard runs the list the plan job gave it (its own output, by the matrix index) and plans nothing: no `suitemap.py shard` or `plan` in the measure job, no map read to choose suites",
      measure_step["env"]["SELECTED"] == "${{ needs.shards.outputs[format('shard{0}', matrix.shard)] }}" and "measure" in measure_step["run"] and "$SELECTED" in measure_step["run"]
      and not any(re.search(r"suitemap\.py (shard|plan)\b", st.get("run", "")) for st in mj["steps"])
      and not any(re.search(r"suitemap\.py (shard|plan)\b", st.get("run", "")) for st in uj["steps"]), (measure_step, [st.get("name") for st in mj["steps"]]))
check("tests.yml: the suites job waits for the plan and the shards and keeps the steps release.sh reads, after the merge of the shards' maps",
      sorted(uj["needs"]) == ["measure", "shards"] and "cancelled()" in uj["if"]
      and suites_steps.index("merge the shards' maps") < suites_steps.index("run every suite, measured") < suites_steps.index("audit the selection"), (uj.get("needs"), suites_steps))
verdict = next(st for st in uj["steps"] if st.get("name") == "run every suite, measured")
check("tests.yml: the verdict step needs the plan, the shards and the merge to have passed",
      all(k in verdict["env"].get(v, "") for k, v in (("needs.shards.result", "PLAN"), ("needs.measure.result", "SHARDS"), ("steps.merge.outcome", "MERGED"))), verdict.get("env"))
# the release queue's branches (Mon Nov 2nd 2026, changed Tue Nov 3rd 2026): a push to queue/** gets a pull request's run (the selection, no shards), as .github/mergequeue.toml's `suites = "select"` says;
# main's push keeps the full measured run. The workflow's `if:` expressions are evaluated for each kind of event, so a workflow and a rules file that disagree fail here.
import tomllib
push_on = y[True]["push"]["branches"]   # YAML 1.1 reads the key `on` as True
save_step = next(st for st in uj["steps"] if st.get("name") == "save the map")
mq = tomllib.load(open(os.path.join(SCR, "..", ".github", "mergequeue.toml"), "rb"))
def holds(expr, event, ref):
    """the value of an `if:` expression of tests.yml for an event and a ref: the subset of the expression language the file uses (== and != on github.event_name and github.ref, startsWith(github.ref, …), &&, ||, parentheses, always(), !cancelled(), and `hashFiles(…) != ''`, taken as true: the map exists)"""
    e = " ".join(str(expr).split("#")[0].replace("${{", " ").replace("}}", " ").split())
    e = e.replace("!cancelled()", "True").replace("always()", "True")
    e = re.sub(r"hashFiles\([^)]*\) != ''", "True", e)
    e = re.sub(r"startsWith\(github\.ref, '([^']*)'\)", lambda m: repr(ref.startswith(m.group(1))), e)
    e = re.sub(r"github\.event_name (==|!=) '([^']*)'", lambda m: repr((event == m.group(2)) == (m.group(1) == "==")), e)
    e = re.sub(r"github\.ref (==|!=) '([^']*)'", lambda m: repr((ref == m.group(2)) == (m.group(1) == "==")), e)
    e = e.replace("&&", " and ").replace("||", " or ")
    if re.sub(r"True|False|and|or|\(|\)|\s", "", e):
        raise ValueError(f"an `if:` outside the subset this test reads: {expr!r} -> {e!r}")
    return eval(e, {"__builtins__": {}})
EVENTS = {"a pull request": ("pull_request", "refs/pull/7/merge"), "a push to main": ("push", "refs/heads/main"),
          "a push to a queue branch": ("push", "refs/heads/queue/main/g1"), "a manual run": ("workflow_dispatch", "refs/heads/some-branch"),
          "a manual run on a queue branch": ("workflow_dispatch", "refs/heads/queue/main/g1")}
MEASURED_ONLY = ["the shards' maps", "merge the shards' maps", "run every suite, measured", "keep the map", "save the map", "publish the map for release.sh", "audit the selection"]
SELECTION, MANUAL = "run the suites the change reaches", "run the suites named, or every suite"
def what_runs(event, ref):
    step = {st.get("name"): holds(st.get("if", "True"), event, ref) for st in uj["steps"]}
    return {"shards": holds(pj.get("if", "True"), event, ref), "measure": holds(mj.get("if", "True"), event, ref), "suites job": holds(uj["if"], event, ref),
            "measured steps": [n for n in MEASURED_ONLY if step[n]], "selection": step[SELECTION], "manual": step[MANUAL]}
def expected(kind, queue_suites):
    """what each kind of event must run: main's push the full measured run; a pull request and a manual run as ever; a queue branch by the rules file's `suites`"""
    if kind == "a push to a queue branch" and queue_suites == "all":   # main's run whole, but the map is saved from main only
        return {"shards": True, "measure": True, "suites job": True, "measured steps": [n for n in MEASURED_ONLY if n != "save the map"], "selection": False, "manual": False}
    if kind == "a push to main":
        return {"shards": True, "measure": True, "suites job": True, "measured steps": MEASURED_ONLY, "selection": False, "manual": False}
    manual = kind.startswith("a manual run")   # on any ref, a queue branch's included: the manual step alone, never the selection too
    return {"shards": False, "measure": False, "suites job": True, "measured steps": [], "selection": not manual, "manual": manual}
check("mergequeue.toml and tests.yml agree on the queue: `suites` is all or select, queue_prefix starts with the `queue/` the push trigger lists and ends with /, and the check mq reads (`required`) is the job named `suites`",
      mq.get("suites") in ("all", "select") and push_on == ["main", "queue/**"] and mq["queue_prefix"].startswith("queue/") and mq["queue_prefix"].endswith("/")
      and "suites" in mq["required"] and "suites" in y["jobs"] and "name" not in uj, (mq.get("suites"), push_on, mq.get("queue_prefix"), mq.get("required")))
# the queue runs as a chain (each PR an entry stacked on the one ahead, all tested at once): the rules file pins it, and carries none of the retired group keys (group_max, bisect), which salamander only warns about
check("mergequeue.toml: the queue runs as a chain, its entries keep the queue/ prefix, and the check mq reads is still `suites`",
      mq.get("queue_mode") == "chain" and mq["queue_prefix"].startswith("queue/") and mq["queue_prefix"].endswith("/") and "suites" in mq["required"] and mq.get("base") == "main", mq)
check("mergequeue.toml: no retired group keys (group_max, bisect), and inflight_max, when set, is mq's 1 to 16",
      "group_max" not in mq and "bisect" not in mq and (("inflight_max" not in mq) or (isinstance(mq["inflight_max"], int) and not isinstance(mq["inflight_max"], bool) and 1 <= mq["inflight_max"] <= 16)), mq)
check("mergequeue.toml: the snapshot-only conflict hook is still there for the chain's build and merge steps (on_conflict, with conflict_paths naming only the generated snapshot)",
      isinstance(mq.get("on_conflict"), str) and "tool_text.py update" in mq["on_conflict"] and mq.get("conflict_paths") == ["tests/tool_text.snapshot.json"], mq)
got = {k: what_runs(*ev) for k, ev in EVENTS.items()}
for kind in EVENTS:
    want = expected(kind, mq["suites"] if kind == "a push to a queue branch" else None)
    check(f"tests.yml runs for {kind} what mergequeue.toml (suites = {mq['suites']!r}) says: shard plan and shards {'yes' if want['shards'] else 'no'}, selection step {'yes' if want['selection'] else 'no'}, measured-run steps {len(want['measured steps'])} of {len(MEASURED_ONLY)}",
          got[kind] == want, (got[kind], want))
check("…the two settings of `suites` expect different runs for a queue branch (so the check above fails when the file and the workflow disagree), and a queue branch with select runs no shard and no measured-run step, only the selection in the `suites` job",
      expected("a push to a queue branch", "select") != expected("a push to a queue branch", "all")
      and (mq["suites"] != "select" or (not got["a push to a queue branch"]["shards"] and got["a push to a queue branch"]["measured steps"] == [] and got["a push to a queue branch"]["selection"])), got["a push to a queue branch"])
def pool(expr, event, ref, hosted_var, hosted_input):
    """the labels a `runs-on:` expression gives: GitHub's && and || return an operand like Python's and/or, so the file's `A && 'x' || B && C && 'y' || 'z'` shape is evaluated as it stands, then fromJSON"""
    e = " ".join(str(expr).replace("${{", " ").replace("}}", " ").split())
    e = re.sub(r"vars\.CI_HOSTED == 'true'", repr(hosted_var), e)
    e = re.sub(r"github\.event_name == '([^']*)'", lambda m: repr(event == m.group(1)), e)
    e = re.sub(r"github\.ref == '([^']*)'", lambda m: repr(ref == m.group(1)), e)
    e = e.replace("inputs.hosted", repr(hosted_input))
    lits = re.findall(r"'[^']*'", e)
    for i, l in enumerate(lits): e = e.replace(l, f"L{i}", 1)
    if e.strip() == "ubuntu-latest": return UBU
    m = re.fullmatch(r"fromJSON\((.*)\)", e)
    if not m: raise ValueError(f"a `runs-on:` outside the shape this test reads: {expr!r}")
    inner = m.group(1).replace("&&", " and ").replace("||", " or ")
    if re.sub(r"True|False|and|or|\(|\)|\s|L\d+", "", inner): raise ValueError(f"a `runs-on:` outside the subset this test reads: {expr!r} -> {inner!r}")
    return json.loads(eval(inner, {"__builtins__": {}}, {f"L{i}": l[1:-1] for i, l in enumerate(lits)}))
UBU, LIGHT, HEAVY = "ubuntu-latest", ["self-hosted", "pool", "light"], ["self-hosted", "pool", "heavy"]
bad = []
for kind, (ev, ref) in EVENTS.items():
    for hv, hi in ((False, False), (True, False), (False, True)):
        if hi and ev != "workflow_dispatch": continue   # the manual input exists on a manual run only
        for jname, job, light in (("shards", pj, True), ("measure", mj, False), ("suites", uj, ev == "push" and ref == "refs/heads/main")):
            want = UBU
            have_pool = pool(job["runs-on"], ev, ref, hv, hi)
            if have_pool != want: bad.append((jname, kind, hv, hi, have_pool, want))
check("tests.yml: the shard plan, the shards and the `suites` job run on ubuntu-latest for every kind of event (the whole `runs-on` expression evaluated)",
      not bad and len(EVENTS) == 5, bad[:3])
check("tests.yml: the map is saved to the cache from main only: a queue branch's commit may be rebased or deleted, and the audit of a later run would not resolve it",
      "github.ref == 'refs/heads/main'" in save_step["if"] and "github.event_name == 'push'" in save_step["if"], save_step.get("if"))
# the plan command: its lines are the lists `shard --index` gives (one plan, however it is asked), with a map, without one, and with a map that is not there (the cache missed)
def plan_lines(*extra):
    r = real("plan", "--of", str(sm.SHARDS), *extra)
    return r.returncode, {l.split("=", 1)[0]: l.split("=", 1)[1].split() for l in r.stdout.splitlines()}
rc0, pl_nomap = plan_lines(); rc1, pl_timed = plan_lines("--map", str(TIMES)); rc2, pl_miss = plan_lines("--map", str(T / "no-such-map.json"))
check(f"plan: {sm.SHARDS} lines shard0..shard{sm.SHARDS - 1}=names, the same lists as `shard --index` gives, with a map and without one",
      rc0 == rc1 == 0 and sorted(pl_nomap) == sorted(pl_timed) == [f"shard{i}" for i in range(sm.SHARDS)]
      and [pl_nomap[f"shard{i}"] for i in range(sm.SHARDS)] == nomap and [pl_timed[f"shard{i}"] for i in range(sm.SHARDS)] == timed, (pl_nomap, nomap))
check("plan: a map that is not there (a cache miss) gives the hash plan, for all six lists alike, every suite in exactly one", rc2 == 0 and pl_miss == pl_nomap and once(list(pl_miss.values())), pl_miss)
(T / "garbage.json").write_text("not json")
check("plan: an unreadable map gives the hash plan too", plan_lines("--map", str(T / "garbage.json"))[1] == pl_nomap)
# merge, in the throwaway repo: its suites split over two shard maps
here = tool("list").stdout.split(); whole = json.loads(MAP.read_text())
def part(names, commit=None, p=None):
    p = T / f"part-{len(list(T.glob('part-*')))}.json"
    p.write_text(json.dumps({**whole, "commit": commit or whole["commit"], "suites": {n: whole["suites"].get(n, {"ok": True, "seconds": 1, "py": {}}) for n in names}})); return str(p)
A, B = part(here[:2]), part(here[2:])
MERGED = T / "merged.json"
r = tool("merge", "--map", str(MERGED), A, B)
check("merge: two shard maps of one commit make one map with every suite", r.returncode == 0 and sorted(json.loads(MERGED.read_text())["suites"]) == sorted(here), (r.stdout, r.stderr))
r = tool("merge", "--map", str(MERGED), A, A, B)
check("merge: a suite in two shards fails it, by name", r.returncode == 1 and "in more than one shard: " + ", ".join(here[:2]) in r.stdout, r.stdout)
r = tool("merge", "--map", str(MERGED), A)
check("merge: a suite in no shard fails it, by name, and the map is still written without it", r.returncode == 1 and "in no shard's map (not measured): " + ", ".join(here[2:]) in r.stdout
      and sorted(json.loads(MERGED.read_text())["suites"]) == sorted(here[:2]), r.stdout)
r = tool("merge", "--map", str(T / "never.json"), A, part(here[2:], commit="0" * 40))
check("merge: maps of two commits are refused and nothing is written", r.returncode == 2 and "not of one commit" in r.stdout and not (T / "never.json").exists(), r.stdout)
K = T / "cancel"; (K / "tests").mkdir(parents=True); MARK = T / "marks"; MARK.mkdir()
for f in ("run-suite", "suitemap.py", "pyproject.toml", "uv.lock"): shutil.copy(os.path.join(SCR, f), K / "tests" / f)
os.chmod(K / "tests/run-suite", 0o755)
SAYS = f"import os, pathlib\npathlib.Path({str(MARK)!r}, '{{0}}').write_text(f\"{{{{os.getpid()}}}} {{{{os.environ['TMPDIR']}}}}\")\n"
(K / "tests/slow_scenario.py").write_text(SAYS.format("slow") + "import time\ntime.sleep(120)\n")
(K / "tests/stubborn_scenario.py").write_text("import signal\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n" + SAYS.format("stubborn") + "import time\ntime.sleep(120)\n")
(K / "tests/after_scenario.py").write_text(SAYS.format("after"))
subprocess.run(["git", "-C", str(K), "init", "-q"], check=True); subprocess.run(["git", "-C", str(K), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(K), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "k"], check=True)
KENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "SUITEMAP_", "GITHUB_", "VIRTUAL_ENV"))}   # UV_PROJECT_ENVIRONMENT stays: the shared one

def cancel(suite, first, then=None, cmd="run -T 600", env=None):
    """start CI's step for `suite` then `after`, signal its top process as the runner does once the suite runs; what was left"""
    for m in MARK.iterdir(): m.unlink()
    p = subprocess.Popen(["bash", "-c", f"{STEP} {cmd} {suite} after"], cwd=K, env={**KENV, **(env or {})},
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    end = time.time() + 120
    while not (MARK / suite).exists() and time.time() < end and p.poll() is None: time.sleep(0.1)
    time.sleep(0.3)
    pid, scratch = (MARK / suite).read_text().split() if (MARK / suite).exists() else ("0", "")
    os.kill(p.pid, first); t0 = time.time(); still = None
    if then:
        time.sleep(2); still = p.poll() is None and os.path.exists(f"/proc/{pid}"); os.kill(p.pid, then); t0 = time.time()
    try: rc = p.wait(timeout=20)
    except subprocess.TimeoutExpired: rc = None
    secs = time.time() - t0
    gone = pid != "0" and not os.path.exists(f"/proc/{pid}")
    if not gone and pid != "0": os.kill(int(pid), signal.SIGKILL)       # a failed check leaves nothing running
    if rc is None: p.kill(); p.wait()
    return {"pid": pid, "rc": rc, "secs": round(secs, 2), "gone": gone, "left": bool(scratch) and os.path.exists(scratch),
            "after": (MARK / "after").exists(), "still": still, "out": (p.stdout.read() or "")[-600:]}

c = cancel("slow", signal.SIGINT)
check("a CI cancel (SIGINT to the step's uv alone): the suite and run-suite end within the runner's 7.5 s, run-suite's folder is gone, no further suite runs",
      c["pid"] != "0" and c["rc"] == 130 and c["secs"] < 7.5 and c["gone"] and not c["left"] and not c["after"] and "stopped by SIGINT" in c["out"], c)
c = cancel("stubborn", signal.SIGINT, signal.SIGTERM)
check("a suite that ignores SIGINT: the runner's SIGTERM ends it, cleanup included (5 s, twice the runner's 2.5, for a busy box), and no further suite runs",
      c["pid"] != "0" and c["still"] is True and c["rc"] is not None and c["secs"] < 5 and c["gone"] and not c["left"] and not c["after"], c)
FAKE = T / "faketimeout"; FAKE.mkdir()   # a timeout that dies on a signal and passes nothing on: its suite runs in the background
(FAKE / "timeout").write_text('#!/bin/sh\nshift 3\n"$@" &\nwait\n'); os.chmod(FAKE / "timeout", 0o755)
c = cancel("slow", signal.SIGINT, env={"PATH": f"{FAKE}:{KENV['PATH']}"})
check("a timeout that dies on the cancel's SIGINT without passing it on: the last TERM to the suite's group still ends it, cleanup included",
      c["pid"] != "0" and c["rc"] == 130 and c["secs"] < 7.5 and c["gone"] and not c["left"] and not c["after"], c)
if use_strace:
    c = cancel("slow", signal.SIGINT, cmd="measure -T 600 --map m.json")
    check("a cancel of the measured run (strace inside timeout, which blocks fatal signals): the traced suite still ends at once and cleans up",
          c["pid"] != "0" and c["rc"] == 130 and c["secs"] < 7.5 and c["gone"] and not c["left"] and not c["after"] and not (K / "m.json").exists(), c)
else:
    print("suitemap: the measured run's cancel is not checked here: strace is missing, or this run is already traced", file=sys.stderr)

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": suitemap scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
