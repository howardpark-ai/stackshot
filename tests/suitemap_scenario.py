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
    from typing import Annotated, Iterable
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
        deep()
        return "g"

    def deep():
        """the helper's docstring"""
        return 1

    def documented():
        """the text a suite reads"""
        return 0

    def inline(): """an inline docstring"""; return 2

    def typed(x: ANN) -> ANN:
        return x

    def typed2(x: Iterable[int]) -> int:
        return 0

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
# a module with postponed annotations (Imports and annotations, Thu Nov 12th 2026). Each typing name is annotation-only in one place, so an edit of the import line
# tells which kind of annotation counts: Iterable (a parameter), Sequence (a return), Mapping (a local variable), Collection (a method's parameter), Iterator
# (a parameter of pg, which z hands to typing.get_type_hints: the def's name is used as a value), Optional (a class-level field, which stays a read). Counter is
# only re-exported (z reads pmod.Counter), deque and OrderedDict are read in code (pq run by b, pa run by a), json in pj (z); `chain` is read by pu in code
# that tolerates its absence (a suite runs it), so adding the name to an import line must reach that suite; CAP is a default, SIZE a decorator argument,
# ANN2 an annotation-only constant.
write("pmod.py", '''
    """a module with postponed annotations"""
    from __future__ import annotations
    import json
    from collections import Counter, OrderedDict, deque
    from functools import lru_cache
    from typing import Collection, Iterable, Iterator, Mapping, Optional, Sequence

    CAP = 5
    SIZE = 8
    ANN2 = str

    def pa(items: Iterable[int], opt: Optional[str] = None) -> int:
        return len(OrderedDict(enumerate(items)))

    def pr(x: int) -> Sequence[int]:
        return [x]

    def pl(x: int):
        seen: Mapping[str, int] = {}
        return seen

    def pd(n: int = CAP, kind: ANN2 = "k"):
        return n

    @lru_cache(maxsize=SIZE)
    def pc(x: int) -> int:
        return x

    def pq():
        return deque([1])

    def pj():
        return json.dumps({})

    def pg(x: Iterator[int]) -> int:
        return 1

    def pu():
        try:
            return list(chain([1], [2]))
        except NameError:
            return []

    class PK:
        note: Optional[int] = None
        def pm(self, x: Collection[str]) -> int:
            return 1
''')
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
    import mod, pmod
    assert mod.f() == 4 and mod.K().m() == 2 and mod.K.s() == 7 and mod.handler() == 5 and mod.typed('t') == 't' and mod.inline() == 2 and mod.typed2([1]) == 0
    assert pmod.pa([1]) == 1 and pmod.pr(1) == [1] and pmod.pl(1) == {} and pmod.pd() == 5 and pmod.pc(2) == 2 and pmod.pu() == [] and pmod.PK().pm([]) == 1
    assert open(os.path.join(ROOT, "data.txt")).read()
''')
write("tests/b_scenario.py", '''
    import os, subprocess, sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
    import mod, pmod
    assert mod.g() == "g" and mod._c.NAME == "x" and mod.reg.list_tools() and list(pmod.pq()) == [1]
    assert subprocess.run([sys.executable, "-c", "import mod; assert mod.h() == 'h'"], cwd=ROOT).returncode == 0
    assert subprocess.run(["sh", os.path.join(ROOT, "helper.sh")], capture_output=True).returncode == 0
    os._exit(0)
''')
# z only imports mod and reads one docstring: it is reached by a change with effects at import, by nothing else (and by an edit of that docstring)
write("tests/z_scenario.py", '''
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import mod, pmod, typing
    assert mod.documented.__doc__
    assert pmod.pj() == "{}" and pmod.Counter and pmod.pg(iter([])) == 1 and typing.get_type_hints(pmod.pg)["return"] is int
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
# ---- Docstrings (Wed Nov 11th 2026): the docstring of an undecorated module-level function is not code; deep() is run by b (through g), named by nobody;
# documented() is never run, and z reads its __doc__; the K.s case above and the decorated one are the rule's other side
out, err, _ = sel_after(lambda: sub("mod.py", "the helper's docstring", "the helper's new docstring"), "undecorated docstring")
check("DOC1 a docstring-only change of an undecorated function reaches the text reader alone, not the suite that ran it (b, through g)", out.split() == ["c"] and "1 docstring(s) alone" in err, (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "the helper's docstring", "the helper's new\n    docstring over\n    two lines"), "undecorated multi-line docstring")
check("DOC2 a docstring that grows to several lines is the same: the text reader alone", out.split() == ["c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "the helper's docstring", "the helper's new docstring"), "undecorated docstring, old rule")
out_d1 = tool("select", "--map", str(MAP), "--to", git("rev-parse", "HEAD").strip(), env={"SUITEMAP_DOCSTRING_RULE": "D1"}).stdout.split()
check("DOC3 SUITEMAP_DOCSTRING_RULE=D1 gives the old answer for the same change (b ran deep)", out_d1 == ["b", "c"], out_d1)
out, err, _ = sel_after(lambda: sub("mod.py", "the text a suite reads", "the text a suite reads, changed"), "docstring read by a suite")
check("DOC4 a docstring a suite reads (z: mod.documented.__doc__) reaches that suite by the name, though no suite ran the body", out.split() == ["c", "z"], (out, err))
out_d1 = tool("select", "--map", str(MAP), "--to", git("rev-parse", "HEAD").strip(), env={"SUITEMAP_DOCSTRING_RULE": "D1"}).stdout.split()
check("DOC5 ...which the old rule missed (it chose the text reader alone: nothing ran documented())", out_d1 == ["c"], out_d1)
def doc_and_code():
    sub("mod.py", "the helper's docstring", "the helper's new docstring"); sub("mod.py", "    return 1\n\ndef documented", "    return 11\n\ndef documented")
out, err, _ = sel_after(doc_and_code, "docstring and code")
check("DOC6 a docstring and a line of the function's code in one change select as before: the suites that ran it (b)", out.split() == ["b", "c"], (out, err))
def doc_and_sig():
    sub("mod.py", "the helper's docstring", "the helper's new docstring"); sub("mod.py", "def deep():", "def deep(x=0):")
out, err, _ = sel_after(doc_and_sig, "docstring and signature")
check("DOC7 a docstring and the def line together select as before (b ran it)", out.split() == ["b", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "an inline docstring", "a new inline docstring"), "inline docstring")
check("DOC8 a docstring that shares its line with the def and with a statement is body, not docstring: selected as before (the def line is a line of the body's, so every suite that imported the module ran it)",
      out == "all" and "docstring(s) alone" not in err, (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "a static method's docstring", "a static method's other docstring"), "method docstring, again")
check("DOC9 a method's docstring is selected as before (a method has no name a suite reads by): a", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "the tool's description", "the tool's other description"), "decorated docstring, again")
check("DOC10 a decorated function's docstring is still the decorator's read: every suite that ran the file", out == "all", (out, err))
# the readers no suite shows by name: a synthetic map where a ran a function that reads __doc__ (or registers a function), as if the base had it
def doc_reader(code):
    def edit():
        sub("mod.py", "the helper's docstring", "the helper's new docstring"); sub("mod.py", "def documented():", code + "\n\ndef documented():")
    return edit
def with_ran(scope):
    mm = json.loads(MAP.read_text()); mm["suites"]["a"]["py"]["mod.py"] = sorted({*mm["suites"]["a"]["py"]["mod.py"], scope}); P = T / f"map-{scope}.json"; P.write_text(json.dumps(mm)); return P
for what, code, scope in (("an attribute __doc__", "def describe(fn):\n    return fn.__doc__", "describe"),
                          ("inspect.getdoc", "def describe(fn):\n    import inspect\n    return inspect.getdoc(fn)", "describe"),
                          ("getattr(fn, '__doc__')", "def describe(fn):\n    return getattr(fn, '__doc__')", "describe"),
                          ("an alias of getdoc", "from inspect import getdoc as gd\n\n\ndef describe(fn):\n    return gd(fn)", "describe"),
                          ("a registry's add_tool", "def register(srv, fn):\n    srv.add_tool(fn)", "register"),
                          ("mcp.tool()(fn) as a call", "def register(srv, fn):\n    return srv.tool()(fn)", "register")):
    git("checkout", "-q", "-B", f"t{len(ran)}", base); doc_reader(code)(); head = commit("docstring and a doc reader")
    r = tool("select", "--map", str(with_ran(scope)), "--to", head); r0 = tool("select", "--map", str(MAP), "--to", head)
    check(f"DOC11 a docstring-only change reaches the suite that ran code reading a docstring ({what}); with no suite running it, the text reader alone",
          r.stdout.split() == ["a", "c"] and r0.stdout.split() == ["c"], (r.stdout, r.stderr[-300:], r0.stdout))
# a suite that reads names wide (getattr(mod, <variable>)) is not a reader of one docstring by that: w1 and w2 (which reads a docstring) are not chosen, w3 names deep()
git("checkout", "-q", "-B", f"t{len(ran)}", base)
for nm, extra in (("w1", ""), ("w2", "\nprint(mod.f.__doc__)"), ("w3", "\nmod.deep()")):
    write(f"tests/{nm}_scenario.py", "import sys\nimport mod\ngetattr(mod, sys.argv[0])" + extra + "\n")
wide_head = commit("wide readers")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import suitemap as s; N = (s.Names(sys.argv[1]),); "
                    "print(' '.join(sorted(s.doc_readers(N, {('mod', 'deep')}))))", wide_head], capture_output=True, text=True, env=ENV, cwd=str(R))
check("DOC13 a suite that reads names wide is not chosen for a docstring by that (w1, w2), a suite that names the function is (w3)",
      r.stdout.split() == ["w3"], (r.stdout, r.stderr[-600:]))
r = tool("list", env={"SUITEMAP_DOCSTRING_RULE": "x"})
check("DOC12 a value that is not a rule is an error at once", r.returncode != 0 and "SUITEMAP_DOCSTRING_RULE" in (r.stderr + r.stdout), (r.returncode, r.stderr[-200:]))
# ---- Imports and annotations (Thu Nov 12th 2026): see the base pmod.py above for what each name is. I1 and N1 are the old rules: each case that narrows says what
# the old rule chose, so it fails if the rule is reverted; the cases after them are the ones that must NOT narrow.
TY = "from typing import Collection, Iterable, Iterator, Mapping, Optional, Sequence"
CO = "from collections import Counter, OrderedDict, deque"
I1, N1 = {"SUITEMAP_IMPORT_RULE": "I1"}, {"SUITEMAP_ANNOTATION_RULE": "N1"}
def old_rule(head, env): return tool("select", "--map", str(MAP), "--to", head, env=env).stdout.split()
def narrows(tag, what, edit, old_env, old_out, msg):
    out, err, head = sel_after(edit, msg)
    check(f"{tag} {what}: nothing is selected", out == "", (out, err))
    check(f"{tag} ...and the old rule (reverting it) chose {old_out}", old_rule(head, old_env) == old_out, old_rule(head, old_env))
narrows("IMP1", "a name added to an import line that no code reads leaves the names already on the line alone", lambda: sub("pmod.py", CO, CO + ", defaultdict"), I1, ["a", "b", "z"], "imp add")
narrows("IMP2", "a line rewritten with the same names (parenthesised, one a line) changes no binding", lambda: sub("pmod.py", CO, "from collections import (\n    Counter,\n    OrderedDict,\n    deque,\n)"), I1, ["a", "b", "z"], "imp reformat")
narrows("IMP3", "a name moved to a line of its own is the same binding", lambda: sub("pmod.py", CO, "from collections import Counter, OrderedDict\nfrom collections import deque"), I1, ["a", "b", "z"], "imp split")
out, err, _ = sel_after(lambda: sub("pmod.py", CO, "from collections import Counter, OrderedDict"), "imp remove, read in code")
check("IMP4 a name removed from an import line and read in code still reaches what runs that code (pq: b), not the other names' readers", out.split() == ["b"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", CO, "from collections import OrderedDict, deque"), "imp remove, re-exported")
check("IMP5 a name removed and only re-exported (z reads pmod.Counter) reaches the suite that reads it so", out.split() == ["z"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "import json\n", "import json as js\n"), "imp rename")
check("IMP6 a name renamed (json → js) is a name removed and one added: the suite that runs the code reading json (z)", out.split() == ["z"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "import json\n", "import json\nfrom itertools import chain, islice\n"), "imp add, read in code")
check("IMP7 a name added to an import line and read in code (pu: a suite runs it, tolerating the missing name) reaches that suite, and only it", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", CO, "from collections import Counter, OrderedDict\nfrom queue import deque"), "imp resourced")
check("IMP9 a name kept on the line but imported from another module (deque) is a changed binding: the suite that runs the code reading it (b)", out.split() == ["b"], (out, err))
narrows("ANN1", "a name used only in a parameter annotation of a plain def in a postponed file is no read", lambda: sub("pmod.py", TY, TY.replace("Iterable, ", "")), N1, ["a"], "ann param")
narrows("ANN2", "...a return annotation", lambda: sub("pmod.py", TY, TY.replace(", Sequence", "")), N1, ["a"], "ann return")
narrows("ANN3", "...the annotation of a local variable", lambda: sub("pmod.py", TY, TY.replace("Mapping, ", "")), N1, ["a"], "ann local")
narrows("ANN4", "...a method's parameter annotation", lambda: sub("pmod.py", TY, TY.replace("Collection, ", "")), N1, ["a"], "ann method")
narrows("ANN5", "an annotation-only constant (ANN2 = str → int)", lambda: sub("pmod.py", "ANN2 = str", "ANN2 = int"), N1, ["a"], "ann constant")
out, err, _ = sel_after(lambda: sub("pmod.py", TY, TY.replace("Iterator, ", "")), "ann escaped")
check("ANN6 a def whose name is used as a value (z: typing.get_type_hints(pmod.pg)) keeps its annotation names as reads: the suite that does so (z), not a", out.split() == ["z"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", TY, TY.replace("Optional, ", "")), "ann field")
check("ANN7 a name in a class-level annotation (a field a dataclass or a model reads) stays a read: the suite that uses the class (a)", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("mod.py", "from typing import Annotated, Iterable", "from typing import Annotated"), "ann runtime")
check("ANN8 a name used in an annotation of a file WITHOUT postponed annotations is a read (the def evaluates it): the suite that calls the def (a) and the text reader", out.split() == ["a", "c"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "CAP = 5", "CAP = 6"), "ann default")
check("ANN9 a constant a default value reads is a read", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "SIZE = 8", "SIZE = 9"), "ann decorator")
check("ANN10 a constant a decorator reads is a read", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "from functools import lru_cache\n", ""), "ann decorator import")
check("ANN11 the import of a name a decorator reads is a read", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "def pr(x: int) -> Sequence[int]:", "def pr(x: int) -> Sequence[str]:"), "ann signature")
check("ANN12 a change to the def line (an annotation edited) still reaches the suites that call the def", out.split() == ["a"], (out, err))
out, err, _ = sel_after(lambda: sub("pmod.py", "from __future__ import annotations\n", ""), "future import removed")
check("ANN13 postponed annotations turned off takes the file whole (every annotation of it changes meaning)", out.split() == ["a", "b", "z"] and "pmod.py: whole (pmod.py)" in err, (out, err))
for v in ("I", "N"):
    r = tool("list", env={f"SUITEMAP_{'IMPORT' if v == 'I' else 'ANNOTATION'}_RULE": "x"})
    check(f"IMP8 a value that is not a rule is an error at once ({v})", r.returncode != 0 and "_RULE" in (r.stderr + r.stdout), (r.returncode, r.stderr[-200:]))
# the escapes the names rule sees: a def used as a value anywhere (an alias, a decorator, an attribute not called, a string, a script with a python shebang) keeps its annotations
git("checkout", "-q", "-B", f"t{len(ran)}", base)
write("tests/w1_scenario.py", "from pmod import pa as alias\nuse = [alias]\n")
write("tests/w2_scenario.py", "import pmod\nreg = {}\nreg['k'] = pmod.pr\n")
write("tests/w3_scenario.py", "names = ['pl']\n")
write("tests/w4_scenario.py", "import pmod\n@pmod.pd\ndef x(): pass\n")
write("bin/runner", "#!/usr/bin/env python3\nimport pmod\nf = pmod.pc\n")
esc_head = commit("escapes")
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import suitemap as s; N = s.Names(sys.argv[1]); print(' '.join(sorted(N.escaped & set(sys.argv[2:]))), '|', N.blind)",
                    esc_head, "pa", "pr", "pl", "pd", "pc", "pg", "pq", "pj", "pu", "pm", "pdd"], capture_output=True, text=True, env=ENV, cwd=str(R))
check("ESC1 a def used as a value (alias, attribute, string, decorator, a script's shebang, get_type_hints argument) escapes; one only called does not",
      r.stdout.split("|")[0].split() == ["pa", "pc", "pd", "pg", "pl", "pr"] and r.stdout.split("|")[1].strip() == "False", (r.stdout, r.stderr[-600:]))
git("checkout", "-q", "-B", f"t{len(ran)}", base)
write("tests/w1_scenario.py", "from pmod import pa as alias\nuse = [alias]\n"); sub("pmod.py", TY, TY.replace("Iterable, ", "")); head2 = commit("ann param, escaped by an alias")
out3 = tool("select", "--map", str(MAP), "--to", head2).stdout.split()
check("ESC2 the same removal of Iterable that selected nothing (ANN1) selects a once pa is used as a value (w1: an alias of it; w1 has no measurement and runs anyway)",
      out3 == ["a", "w1"], out3)
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
for rel, edit in (("pyproject.toml", lambda: write("pyproject.toml", "[project]\nname = 't'\n")),
                  ("uv.lock", lambda: write("uv.lock", "version = 1\n")),
                  ("tests/suitemap.py", lambda: sub("tests/suitemap.py", "FORMAT = 1", "FORMAT = 1  # a comment"))):
    out, err, _ = sel_after(edit, rel)
    check(f"the harness's {rel} reaches all, even a comment", out == "all" and "the harness" in err, (out, err))

# ---- the example config (Tue Nov 10th 2026): a synthetic map, nothing measured. direct opens stackshot.example.toml itself, fx1 and fx2 read
# it through the link tests/example_base.toml (the fixture suites), other opens data.txt
R_MAIN = R; R = T / "repo2"; R.mkdir()
git("init", "-q", "-b", "main")
EX = '''
    # the example config
    [model]
    guards = true            # a comment
    digest = 5

    # Nothing special here, just prose.
    [runners]
    boxes = ["box-a", "box-b"]

    [runners.ids]

    [router]
    digest_hour = 6

    [pages]
    rules = "~/a/RULES.md"

    [audit]
    enabled = false

    [flags]
    flags = [1]
'''
write("stackshot.example.toml", EX); write("data.txt", "one\n")
for s in ("direct", "fx1", "fx2", "other"): write(f"tests/{s}_scenario.py", "print('x')\n")
os.symlink("../stackshot.example.toml", R / "tests/example_base.toml"); shutil.copy(os.path.join(SCR, "suitemap.py"), R / "tests" / "suitemap.py")
shutil.copy(os.path.join(SCR, "_instance.py"), R / "tests" / "_instance.py")   # the names the selection reads (what apply() sets or appends) are this checkout's own
base2 = commit("base of the example config cases")
def fmap(fixture_path):
    ent = lambda files: {"ok": True, "failed": False, "files": files, "dirs": ["", "tests"], "whole": [], "py": {}, "seconds": 1}
    return {"format": 1, "commit": base2, "strace": True, "suites": {
        "direct": ent(["stackshot.example.toml"]), "fx1": ent([fixture_path]), "fx2": ent([fixture_path, "data.txt"]), "other": ent(["data.txt"])}}
MAP2 = T / "map2.json"; MAP2.write_text(json.dumps(fmap("tests/example_base.toml")))
OLDMAP = T / "oldmap.json"; OLDMAP.write_text(json.dumps(fmap("stackshot.example.toml")))
def ex_sel(edit, msg, *, map_=MAP2, env=None):
    git("checkout", "-q", "-B", f"x{len(ran)}", base2)
    edit()
    head = commit(msg)
    r = tool("select", "--map", str(map_), "--to", head, env={"SUITEMAP_ROOT": str(R), **(env or {})})
    return r.stdout.strip(), r.stderr
def ex_sub(a, b): sub("stackshot.example.toml", a, b)
FIX = ["direct", "fx1", "fx2"]
# The comment, blank-line and reorder cases below pin that a change to the file's text but not to its data is NOT over-selected: they pass with DATA
# emptied (a plain file rule picks only the real-path readers here, the same as the "same data" answer) and fail when a textual change is read as a change.
# The old-map and no-strace cases pin behaviour the rule must leave alone (a map from before the link; a map with no file measurement).
PLAIN = "# Some plain prose about nothing in particular."
def ex_end(extra): write("stackshot.example.toml", textwrap.dedent(EX).lstrip("\n") + extra)
out, err = ex_sel(lambda: ex_sub("[runners]\n", PLAIN + "\n[runners]\n"), "plain comment line")
check("example config: a whole plain-prose comment line added selects the direct readers only (the link readers stay out)", out.split() == ["direct"] and "plain comments" in err, (out, err))
out, err = ex_sel(lambda: ex_sub("[runners]\n", "\n\n[runners]\n"), "blank lines")
check("example config: blank lines only: the direct readers", out.split() == ["direct"], (out, err))
out, err = ex_sel(lambda: ex_sub("# Nothing special here, just prose.\n", ""), "plain comment removed")
check("example config: a plain whole-line comment removed: the direct readers", out.split() == ["direct"], (out, err))
out, err = ex_sel(lambda: ex_sub("# Nothing special here, just prose.\n", PLAIN + " More of it.\n"), "plain comment replaced")
check("example config: a plain whole-line comment replaced by another: the direct readers", out.split() == ["direct"], (out, err))
out, err = ex_sel(lambda: write("stackshot.example.toml", PLAIN + "\n" + textwrap.dedent(EX).lstrip("\n")), "comment above line 1")
check("example config: a plain comment inserted above the first line is a change (cli.py anchors on that line)", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("# the example config\n", PLAIN + "\n"), "first line replaced")
check("example config: a change to the first line is a change, even to plain prose", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("# the example config\n", ""), "first line removed")
check("example config: the first line removed is a change", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("# the example config\n", "# the example config\n\n"), "blank line after the first line")
check("example config: a blank line right after the first line is a change (the hunk starts at old line 1)", out.split() == FIX, (out, err))
for what, line in (("a word of a key (digest)", "# the digest count"), ("a table name (runners)", "# about the runners"), ("a name inside a longer word (digests)", "# the digests count"),
                   ("a `=` (a commented-out sample)", "# digest = 7"), ("a quote", "# the \"digest\" count"), ("a digit", "# every 5 minutes"), ("an underscore", "# a plain_word"),
                   ("a bracket", "# see [model] above")):
    out, err = ex_sel(lambda: ex_sub("[runners]\n", line + "\n[runners]\n"), f"comment: {what}")
    check(f"example config: a comment with {what} is not plain: the fixture readers too", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("guards = true            # a comment", "guards = true            # another comment"), "trailing comment edited")
check("example config: a trailing comment edited on a code line selects the fixture readers (a suite's regex takes the whole line)", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5  # x"), "trailing comment added")
check("example config: a trailing comment added to a code line selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("guards = true            # a comment", "guards = true\t# a comment"), "tab before comment")
check("example config: spaces turned into a tab before a trailing comment select the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: write("stackshot.example.toml", EX.replace("guards = true            # a comment\n    digest = 5\n", "digest = 5\n    guards = true            # a comment\n")), "reordered")
check("example config: two lines of a table in another order select the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5\nnew_key = 1"), "key added")
check("example config: a key added, whatever its name, selects the fixture readers (where it lands and what a suite patches are not predictable)", out.split() == FIX and "changed" in err, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5\nbrand_new_key = 1"), "unrelated key")
check("example config: an unrelated key with a name of its own: the fixture readers too", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end('\n[a_new_feature]\nswitch = 1\n'), "unrelated table")
check("example config: an unrelated table added: the fixture readers too", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end("\nzz_end = 1\n"), "key at the end")
check("example config: a key at the end of the file (it lands in the last table) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5\ndirect = {}"), "inline table")
check("example config: an inline table added (a name a suite patches, and a value the old name check skipped) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end('\n[units]\nscope = "user"\n'), "units table")
check("example config: a [units] table added (set by hand in suites, in no constant) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end("\n[units]\n"), "empty units table")
check("example config: an empty [units] table selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("# the example config\n", "# the example config\nlive = true\n"), "uncommented sample")
check("example config: an uncommented sample line (a key added) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("guards = true", "guards = false"), "flipped")
check("example config: an existing setting changed selects the direct readers and the fixture readers (fx1, fx2), not the others", out.split() == FIX and "changed" in err, (out, err))
out, err = ex_sel(lambda: ex_sub("digest_hour = 6", "digest_hour = 7"), "digest hour")
check("example config: another existing setting changed: the same", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub('boxes = ["box-a", "box-b"]', 'boxes = ["box-a", "box-b", "box-c"]'), "list grown")
check("example config: a list that grew selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5\n", ""), "key removed")
check("example config: a key removed selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[runners.ids]\n", ""), "empty table removed")
check("example config: an empty table removed selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5\nrules = \"~/x/RULES.md\""), "rules added under [model]")
check("example config: a key named like one the example holds elsewhere selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end('\n[job_gap.repos]\n"example-owner/ops-hub" = "ops/general"\n'), "job_gap.repos added")
check("example config: a table apply() appends ([job_gap.repos]; declared twice it is a parse error) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end('\n[[router.watch]]\npage = "p"\n'), "router.watch added")
check("example config: an array of tables apply() appends ([[router.watch]]) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_end('\n[project_scopes.by_tag]\nops = "ops"\n'), "by_tag added")
check("example config: a table apply() appends, under a parent the example does not hold, selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[pages]\n", "[pages]\ndirs = [\"x\"]\n"), "pages.dirs added")
check("example config: a key apply() sets (pages.dirs) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[audit]\n", "[audit]\nretries = 3\n"), "key under a pinned table")
check("example config: a key right under a table a suite's pattern anchors on ([audit]) selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[audit]\n", "[audit]\n" + PLAIN + "\n"), "plain comment under a pinned header")
check("example config: a plain comment right under a pinned header ([audit]) is a change (a pattern takes the header line and the next as one text)", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[audit]\n", "[audit]\n\n"), "blank line under a pinned header")
check("example config: a blank line right under a pinned header is a change", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[audit]\nenabled = false", "[audit]\nenabled = false\n" + PLAIN), "plain comment after the first key of a pinned table")
check("example config: a plain comment after the first key of a pinned table stays at the direct readers", out.split() == ["direct"], (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5\nbroken = ["), "unparseable new")
check("example config: a text that does not parse (new) selects every suite", out == "all" and "does not parse" in err, (out, err))
git("checkout", "-q", "-B", "broken", base2); ex_sub("digest = 5", "digest = 5\nbroken = ["); broken = commit("broken base")
fixed_map = T / "broken.json"; fixed_map.write_text(json.dumps({**json.loads(MAP2.read_text()), "commit": broken}))
git("checkout", "-q", "-B", "fixed", broken); ex_sub("broken = [\n", ""); fixed = commit("fixed")
r = tool("select", "--map", str(fixed_map), "--to", fixed, env={"SUITEMAP_ROOT": str(R)})
check("example config: a text that does not parse (old) selects every suite", r.stdout.strip() == "all" and "does not parse" in r.stderr, (r.stdout, r.stderr))
def link_edit():
    os.remove(R / "tests/example_base.toml"); os.symlink("../data.txt", R / "tests/example_base.toml")
out, err = ex_sel(link_edit, "link moved")
check("example config: a change to the link tests/example_base.toml selects every suite", out == "all" and "link" in err, (out, err))
out, err = ex_sel(lambda: (ex_sub("[runners]\n", PLAIN + "\n[runners]\n"), sub("data.txt", "one", "two")), "comment and data")
check("example config: a plain comment beside another file's change selects the direct readers and the other file's (fx2, other open data.txt)",
      out.split() == ["direct", "fx2", "other"], (out, err))
out, err = ex_sel(lambda: ex_sub("digest = 5", "digest = 5.0"), "int to float")
check("example config: 5 to 5.0 selects the fixture readers", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("guards = true", "guards = 1"), "bool to int")
check("example config: true to 1 selects the fixture readers", out.split() == FIX, (out, err))
A1 = {"SUITEMAP_EXAMPLE_RULE": "A1"}
r = tool("list", env={"SUITEMAP_EXAMPLE_RULE": "A-1"})
check("example config: a bad SUITEMAP_EXAMPLE_RULE is refused at the start of any command, `list` included (the check in main(), not only where a rule reads it)",
      r.returncode != 0 and "A1" in r.stderr and "A2" in r.stderr and r.stdout.strip() == "", (r.returncode, r.stdout, r.stderr[-300:]))
for bad in ("A-1", "a3", "off"):
    r = tool("select", "--map", str(MAP2), "--to", "HEAD", env={"SUITEMAP_ROOT": str(R), "SUITEMAP_EXAMPLE_RULE": bad})
    check(f"example config: SUITEMAP_EXAMPLE_RULE={bad} is an error that names A1 and A2, not a silent A2", r.returncode != 0 and "A1" in r.stderr and "A2" in r.stderr and r.stdout.strip() == "", (r.returncode, r.stdout, r.stderr[-300:]))
r = tool("select", "--map", str(MAP2), "--to", "HEAD", env={"SUITEMAP_ROOT": str(R), "SUITEMAP_EXAMPLE_RULE": " a1 "})
check("example config: the switch is read without case or spaces (a1)", r.returncode == 0, (r.returncode, r.stderr[-300:]))
out, err = ex_sel(lambda: ex_sub("[runners]\n", PLAIN + "\n[runners]\n"), "plain comment, A1", env=A1)
check("example config (switch A1): even a plain comment selects the fixture readers (no cheap case)", out.split() == FIX and "rule A1" in err, (out, err))
out, err = ex_sel(lambda: ex_sub("guards = true", "guards = false"), "flipped, A1", env=A1)
check("example config (switch A1): a changed setting selects the same as under A2", out.split() == FIX, (out, err))
out, err = ex_sel(lambda: ex_sub("[runners]\n", PLAIN + "\n[runners]\n"), "plain comment, old map", map_=OLDMAP)
# pins the change-over: on a map made before the link (every suite opens the real path) nothing is lost while the rule waits for main's next measurement
check("example config: on a map from before the link (every suite opens the real path) a comment still selects all of them, as before", out.split() == ["direct", "fx1", "fx2"], (out, err))
out, err = ex_sel(lambda: ex_sub("[runners]\n", PLAIN + "\n[runners]\n"), "plain comment, no strace", map_={**json.loads(MAP2.read_text()), "strace": False})
check("example config: a map without the file measurement selects every suite, as for any data file", out == "all", (out, err))

# ---- the edits of the delta review, on the real example config and the real tests/_instance.py: each of E1-E4 and E6-E9 breaks the fixture suites
# (run by hand on a scratch copy: audits_page, button_set, install, orange, server_fixes, wait_end ... fail on E1/E7; stall on E2; 141 of 148 on E3;
# all of them on E8/E9/E6), so each must select the fixture readers; E5 and E10 break nothing and stay at the direct readers
R = T / "repo3"; R.mkdir()
git("init", "-q", "-b", "main")
REAL_EX = (pathlib.Path(SCR).parent / "stackshot.example.toml").read_text(encoding="utf-8")
write_raw = lambda rel, text: (R / rel).parent.mkdir(parents=True, exist_ok=True) or (R / rel).write_text(text, encoding="utf-8")
write_raw("stackshot.example.toml", REAL_EX); write_raw("data.txt", "one\n")
for s in ("direct", "fx1", "fx2", "other"): write(f"tests/{s}_scenario.py", "print('x')\n")
os.symlink("../stackshot.example.toml", R / "tests/example_base.toml")
shutil.copy(os.path.join(SCR, "suitemap.py"), R / "tests" / "suitemap.py"); shutil.copy(os.path.join(SCR, "_instance.py"), R / "tests" / "_instance.py")
base3 = commit("real example config")
m3 = json.loads(MAP2.read_text()); m3["commit"] = base3; MAP4 = T / "map4.json"; MAP4.write_text(json.dumps(m3))
def cur(): return (R / "stackshot.example.toml").read_text(encoding="utf-8")
def put(text): write_raw("stackshot.example.toml", text)
def real_sel(edit, msg, env=None):
    git("checkout", "-q", "-B", f"r{len(ran)}", base3)
    edit()
    head = commit(msg)
    r = tool("select", "--map", str(MAP4), "--to", head, env={"SUITEMAP_ROOT": str(R), **(env or {})})
    return r.stdout.strip(), r.stderr
def after_line(prefix, new_lines):
    ls = cur().split("\n"); i = next(k for k, l in enumerate(ls) if l.startswith(prefix))
    put("\n".join(ls[:i + 1] + new_lines + ls[i + 1:]))
def swap(a, b):
    assert cur().count(a) == 1, a; put(cur().replace(a, b, 1))
def e7():
    ls = cur().split("\n"); a_i = next(k for k, l in enumerate(ls) if l.startswith("[audit]")); en = ls[a_i + 1]
    mode_i = next(k for k in range(a_i, len(ls)) if ls[k].startswith("mode = "))
    assert en.startswith("enabled = false"); put("\n".join(ls[:a_i + 1] + ls[a_i + 2:mode_i + 1] + [en] + ls[mode_i + 1:]))
def e8():
    ls = cur().split("\n"); i = ls.index("[registries.projects]")
    ls[i:i + 3] = ["[registries]", "projects.key = " + ls[i + 1].split("=", 1)[1].split("#")[0].strip(), "projects.match = " + ls[i + 2].split("=", 1)[1].strip()]
    put("\n".join(ls))
REAL_PLAIN = "# Some plain prose about nothing in particular."
for word in ("git", "ssh", "cap"):
    out, err = real_sel(lambda: swap("[router]  ", f"# the {word} thing\n[router]  "), f"real: comment with {word}")
    check(f"real example: a plain comment holding the short key word {word!r} selects the fixture readers (whole-word test, not only the 4-letter substring)", out.split() == FIX, (out, err))
out, err = real_sel(lambda: put(REAL_PLAIN + "\n" + cur()), "real: comment above line 1")
check("real example: a plain comment inserted above the first line selects the fixture readers (cli.py anchors on it)", out.split() == FIX, (out, err))
first = REAL_EX.split("\n", 1)[0]
out, err = real_sel(lambda: put(REAL_EX.replace(first, REAL_PLAIN, 1)), "real: line 1 changed")
check("real example: a change to the first line selects the fixture readers", out.split() == FIX, (out, err))
out, err = real_sel(lambda: swap("[router]  ", REAL_PLAIN + "\n[router]  "), "real: comment")
check("real example: a plain comment line away from a pinned header stays at the direct readers", out.split() == ["direct"], (out, err))
out, err = real_sel(lambda: put(cur().rstrip("\n") + "\n\n" + REAL_PLAIN + "\n"), "real: comment and blank lines at the end")
check("real example: a plain comment and blank lines at the end of the file stay at the direct readers", out.split() == ["direct"], (out, err))
out, err = real_sel(lambda: after_line("[model] ", [REAL_PLAIN]), "real: comment under [model]")
check("real example: a plain comment right under a header that no suite anchors on stays at the direct readers", out.split() == ["direct"], (out, err))
out, err = real_sel(lambda: swap("[router]  ", REAL_PLAIN + "\n[router]  "), "real: comment, A1", env={"SUITEMAP_EXAMPLE_RULE": "A1"})
check("real example (switch A1): the same plain comment selects the fixture readers", out.split() == FIX, (out, err))
def trailing_tab(prefix):
    ls = cur().split("\n"); i = next(k for k, l in enumerate(ls) if l.startswith(prefix)); code, _, cm = ls[i].partition("#")
    ls[i] = code.rstrip() + "\t#" + cm; put("\n".join(ls))
def uncomment(sample):
    swap("# " + sample, sample)
for name, edit in (("E1 a plain comment line right under [audit]", lambda: after_line("[audit]", [REAL_PLAIN])),
                   ("E1 a blank line right under [audit]", lambda: after_line("[audit]", [""])),
                   ("E1 a plain comment line right under [anchor_hub]", lambda: after_line("[anchor_hub]", [REAL_PLAIN])),
                   ("E2 an extra space before = in [stall]", lambda: swap("max_pause_hours = 4", "max_pause_hours  = 4")),
                   ("E3 an extra space before = in [paths] repo", lambda: swap('repo = "~/stackshot-data"', 'repo  = "~/stackshot-data"')),
                   ("E4 a new [[foo.bar]] row with a repo key", lambda: put(cur().rstrip("\n") + '\n\n[[foo.bar]]\nrepo = "x"\n')),
                   ("E5 an unrelated key in an unrelated table", lambda: put(cur().rstrip("\n") + "\n\n[a_new_feature]\nswitch = 1\n")),
                   ("E6 a new multi-line value in [instance]", lambda: after_line("[instance]", ["zzz = [", "[1],", "]"])),
                   ("E7 enabled moved below mode in [audit]", e7),
                   ("E8 [registries.projects] rewritten as dotted keys", e8),
                   ("E9 [ runners.ssh_hosts ] with spaces in the brackets", lambda: swap("[runners.ssh_hosts] ", "[ runners.ssh_hosts ] ")),
                   ("E10 a key added after owner_aliases", lambda: after_line("owner_aliases = []", ["unrelated_after_aliases = 1"])),
                   ("E10 a key added after rules", lambda: after_line("rules = ", ["unrelated_after_rules = 1"])),
                   ("F1 a trailing comment on port = 8020", lambda: swap("\nport = 8020\n", "\nport = 8020  # x\n")),
                   ("F1 a trailing comment on hook_port = 8010", lambda: swap("\nhook_port = 8010\n", "\nhook_port = 8010 # x\n")),
                   ("F1 a tab before the comment on cap_needs_owner", lambda: trailing_tab("cap_needs_owner = true")),
                   ("F2 a first line # session_view = \"\"", lambda: put('# session_view = ""\n' + cur())),
                   ("F3 direct = {} added in [model]", lambda: after_line("[model] ", ["direct = {}"])),
                   ("F3 a [units] table added", lambda: put(cur().rstrip("\n") + "\n\n[units]\n")),
                   ("F3 a [units] table with scope = user added", lambda: put(cur().rstrip("\n") + '\n\n[units]\nscope = "user"\n')),
                   ("F4 zz_end = 1 at the end of the file", lambda: put(cur().rstrip("\n") + "\nzz_end = 1\n")),
                   ("F4 zz_gate = 1 under [page_gate]", lambda: after_line("[page_gate]", ["zz_gate = 1"])),
                   ("F4 the sample # paused_until uncommented", lambda: uncomment("paused_until = ")),
                   ("F4 the sample # pause_item uncommented", lambda: uncomment("pause_item = ")),
                   ("F4 the sample # live = true uncommented", lambda: uncomment("live = true"))):
    out, err = real_sel(edit, name)
    check(f"real example: {name} selects the fixture readers", out.split() == FIX, (out, err))
R = R_MAIN
# what apply() touches, run for real: every setting it sets and every table it appends is a name the selection knows (the names come from the constants
# of tests/_instance.py, so a new line in apply() that changes something the constants do not list fails here)
sys.path.insert(0, SCR)
import _instance
MLS = 'a = """\nx\n\ny\n"""\nb = 1\n'
check("layout_only: a blank line inside a multi-line string is content, not layout", not smod.layout_only(MLS, MLS.replace("x\n\ny", "x\n\n\ny"), set(), set()))
check("layout_only: a '#' line inside a multi-line string is content, not a comment", not smod.layout_only(MLS, MLS.replace("x\n", "x\n# plain\n"), set(), set()))
check("layout_only: a blank line outside the string is layout", smod.layout_only(MLS, MLS + "\n\n", set(), set()))
names = smod.names_from_source((pathlib.Path(SCR) / "_instance.py").read_text(encoding="utf-8"))
check("apply(): the selection reads the names from tests/_instance.py", names is not None and len(names[0]) > 20 and names[1] == set(_instance.PINNED_TABLES), names and len(names[0]))
if names:
    before = smod.toml_items(_instance.base_toml())
    # the example text itself, as apply() would find it without the table it appends: apply(x) minus TABLES is what it patched
    after = smod.toml_items(_instance.apply(_instance.base_toml(), gbrain=True, owner=True, login=True, keywords=True))
    touched = sorted(p for p, v in after - before if v != "{}")
    uncovered = [p for p in touched if not any(p == t or p.startswith(t + ".") for t in names[0] if t)]
    check("apply(): every setting it changes and every table it appends is covered by a name the selection knows", touched and not uncovered, uncovered)
    check("apply(): the tables it appends are all in the names (job_gap.repos, router.watch, project_scopes.by_prefix)",
          {"job_gap.repos", "router.watch", "router.quiet", "project_scopes.by_prefix", "project_scopes.by_tag"} <= names[0], names[0])
src = (pathlib.Path(SCR) / "_instance.py").read_text(encoding="utf-8")
bad_pinned = re.sub(r"(?m)^PINNED_TABLES = .*$", 'PINNED_TABLES = "audit"', src)
check("apply(): PINNED_TABLES as a bare string is refused, not read as a set of letters", bad_pinned != src and smod.names_from_source(bad_pinned) is None, bad_pinned != src)
check("apply(): PINNED_TABLES as a list of strings is read", smod.names_from_source(re.sub(r"(?m)^PINNED_TABLES = .*$", 'PINNED_TABLES = ["audit"]', src)) is not None)
# a suite's pattern that anchors on a table's header line names that table in PINNED_TABLES
anchored = set()
for f in sorted(pathlib.Path(SCR).glob("*_scenario.py")):
    anchored |= set(re.findall(r"\(\?m\)\^\(\\\[(\w+)\\\]", f.read_text(encoding="utf-8")))
check("apply(): every table a suite's pattern anchors on the header of is in PINNED_TABLES", anchored and anchored <= set(_instance.PINNED_TABLES), (anchored, _instance.PINNED_TABLES))

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
    # new one as `carry`, with the commit that measurement was made at, and a second such run keeps the same carry (the retest skip that read it is gone; the selection above still runs the suite)
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
STEP = "exec uv run --locked --only-group tests python tests/suitemap.py"
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
# release.sh can use either of two merge queues: GitHub's (the default; its entries are the `merge_group` event) or salamander's own (`salamander mq`, used when the host file says mode on; its entry branches are queue/**). Neither is retired, and both get the same run.
# The salamander queue's branches (Mon Nov 2nd 2026, changed Tue Nov 3rd 2026): a push to queue/** gets a pull request's run (the selection, no shards), as .github/mergequeue.toml's `suites = "select"` says;
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
          "a push to a queue branch": ("push", "refs/heads/queue/main/g1"), "a manual run": ("workflow_dispatch", "refs/heads/some-branch"),   # a push to a queue branch: the salamander merge queue's entry branch
          "a manual run on a queue branch": ("workflow_dispatch", "refs/heads/queue/main/g1"),
          "a merge-queue entry": ("merge_group", "refs/heads/gh-readonly-queue/main/pr-7-0123456789abcdef0123456789abcdef01234567")}   # GitHub's merge queue (the default one release.sh uses): its own branch, not a push
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
    # a merge-queue entry (merge_group) is a pull request's run too: the selection in the `suites` job, no shards, no measured-run step (falls out below)
    manual = kind.startswith("a manual run")   # on any ref, a queue branch's included: the manual step alone, never the selection too
    return {"shards": False, "measure": False, "suites job": True, "measured steps": [], "selection": not manual, "manual": manual}
check("mergequeue.toml and tests.yml agree on the queue: `suites` is all or select, queue_prefix starts with the `queue/` the push trigger lists and ends with /, and the check mq reads (`required`) is the job named `suites`",
      mq.get("suites") in ("all", "select") and push_on == ["main", "queue/**"] and mq["queue_prefix"].startswith("queue/") and mq["queue_prefix"].endswith("/")
      and "suites" in mq["required"] and "suites" in y["jobs"] and "name" not in uj, (mq.get("suites"), push_on, mq.get("queue_prefix"), mq.get("required")))
# the salamander queue runs as a chain (each PR an entry stacked on the one ahead, all tested at once): the rules file pins it, and carries none of the retired group keys (group_max, bisect), which salamander only warns about
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
      not bad and len(EVENTS) == 6, bad[:3])
# GitHub's native merge queue (merge_group): the same run as a queue/** push (evaluated above: no shards, no measured-run step, the selection; `suites` reports), plus what the event itself needs
MG = "a merge-queue entry"
mg_on = y[True].get("merge_group")
check("merge_group: tests.yml triggers on it with types checks_requested, and the entry's branch (gh-readonly-queue/…) is not in the push list (a push trigger too would run every entry twice)",
      isinstance(mg_on, dict) and mg_on.get("types") == ["checks_requested"] and not any("gh-readonly-queue" in b for b in push_on) and push_on == ["main", "queue/**"], (mg_on, push_on))
check("merge_group: it runs what a queue/** push runs (select: the suites job with the selection step; no shard plan, no shards, no map kept, saved, published or audited)",
      got[MG] == got["a push to a queue branch"] == {"shards": False, "measure": False, "suites job": True, "measured steps": [], "selection": True, "manual": False}, (got[MG], got["a push to a queue branch"]))
check("merge_group: the `suites` job (the check main requires) runs for it and keeps its name, whatever the skipped shard jobs (`!cancelled()` lets a skipped need through)",
      got[MG]["suites job"] and "cancelled()" in uj["if"] and "name" not in uj and not got[MG]["shards"] and not got[MG]["measure"], (uj.get("if"), uj.get("name")))
cache_step = next(st for st in uj["steps"] if st.get("name") == "the suite map")
check("merge_group: the map's cache key falls through the PR's base commit to the entry's base_sha, then to the earlier head, and the restore falls back to the newest map (the entry's base_sha may have no map of its own)",
      cache_step["with"]["key"] == "suitemap-${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}" and cache_step["with"]["restore-keys"].strip() == "suitemap-", cache_step["with"])
conc = y["concurrency"]
check("merge_group: the concurrency group holds the ref (each entry has its own branch, so entries never share a group) and cancel-in-progress is true for a pull_request only: an entry's run is never cancelled by another",
      "github.ref" in conc["group"] and "github.workflow" in conc["group"]
      and holds(conc["cancel-in-progress"], *EVENTS["a pull request"]) is True and all(holds(conc["cancel-in-progress"], *EVENTS[k]) is False for k in EVENTS if k != "a pull request"), conc)
pr_jobs = [n for n in y["jobs"] if n not in ("shards", "measure", "suites")]   # the jobs that read the pull request (today tool-text)
check("merge_group: every job that reads the pull request is skipped for a merge-queue entry (its `if:` evaluated for the event: skipped counts as passing), as for a queue/** push",
      pr_jobs and all(holds(y["jobs"][n].get("if", "True"), *EVENTS[MG]) is False for n in pr_jobs), {n: y["jobs"][n].get("if") for n in pr_jobs})
# the whole of the run, not only the steps named above: every step of `suites` (by position and name: the unnamed ones too) and every other job, evaluated for the event. A merge-queue entry must match a queue/** push in each
def whole_run(event, ref):
    steps = {f"{i}: {st.get('name') or st.get('uses') or st.get('run', '')[:30]}": holds(st.get("if", "True"), event, ref) for i, st in enumerate(uj["steps"])}
    jobs = {n: holds(j.get("if", "True"), event, ref) for n, j in y["jobs"].items()}
    return jobs, steps
wr_mg, wr_q = whole_run(*EVENTS[MG]), whole_run(*EVENTS["a push to a queue branch"])
check("merge_group: every job and every step of the `suites` job (the `if:` of each evaluated, the whole set: the lock check, the map restore, the checkout …) runs for a merge-queue entry exactly when it runs for a queue/** push",
      wr_mg == wr_q and len(wr_mg[1]) >= 10 and any(k.endswith("the suite map") for k in wr_mg[1]) and any("lock is present" in k for k in wr_mg[1]),
      [(k, wr_mg[0][k], wr_q[0].get(k)) for k in wr_mg[0] if wr_mg[0][k] != wr_q[0].get(k)] + [(k, v, wr_q[1].get(k)) for k, v in wr_mg[1].items() if v != wr_q[1].get(k)])
named_events = set(re.findall(r"github\.event_name\s*(?:==|!=)\s*'([^']*)'", open(os.path.join(SCR, "..", ".github", "workflows", "tests.yml"), encoding="utf-8").read()))
check("merge_group: every event name the file's expressions test for is one it triggers on, and merge_group is among them (a queue run is told apart from main's in the file, not left to fall through)",
      named_events <= {"push", "pull_request", "merge_group", "workflow_dispatch"} and "merge_group" in named_events, named_events)
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
for f in ("run-suite", "suitemap.py"): shutil.copy(os.path.join(SCR, f), K / "tests" / f)
for f in ("pyproject.toml", "uv.lock"): shutil.copy(os.path.join(SCR, "..", f), K / f)
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

# ---- the docstring tripwire (Wed Nov 11th 2026). A docstring-only change of an undecorated function selects by name (tests/suitemap.py, *Docstrings*): that
# is sound while nothing reaches a function by a variable name and reads its docstring, or registers it somewhere that builds a description from it. The
# checkout's Python (every .py file and every script with a python shebang, under the root) is scanned for the common forms that do either; the number of
# uses of each form in each file is pinned below, so a new use, in a file that already has one or not, fails this scenario until its author has looked at
# whether the selection still reaches it and then pins it with the reason. The tripwire selects nothing: it only makes a new use fail here.
# Not covered, and said so in tests/suitemap.py: vars(fn)["__doc__"], operator.attrgetter("__doc__"), an eval or exec string, and a registry applied by
# another call shape (typer or click `command()(f)` applied through a variable, a framework we do not use today).
import ast, collections
DOC_REG = {"add_tool", "command", "add_api_route", "tool", "resource", "prompt", "from_function", "add_resource", "add_prompt"}
DOC_NAMES = ("getdoc", "getmembers", "get_docstring", "render_doc")
def doc_forms(src):
    """the docstring-reading and docstring-registering forms a Python source uses, each with the number of its uses"""
    out = collections.Counter()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Attribute) and n.attr in ("__doc__",) + DOC_NAMES:
            out[n.attr] += 1
        elif isinstance(n, ast.Name) and n.id in DOC_NAMES + ("pydoc", "doctest"):
            out[n.id] += 1
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in ("pydoc", "doctest"):
                    out[a.name.split(".")[0]] += 1
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] in ("pydoc", "doctest"):
                out[n.module.split(".")[0]] += 1
            for a in n.names:
                if a.name in DOC_NAMES:
                    out[a.name] += 1
                if a.name == "*":
                    out["import *"] += 1
                if a.name in DOC_REG:
                    out[f"import {a.name}"] += 1
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "getattr" and any(isinstance(a, ast.Constant) and a.value == "__doc__" for a in n.args):
                out["getattr __doc__"] += 1
            if isinstance(f, ast.Name) and f.id == "help":
                out["help("] += 1
            if isinstance(f, ast.Attribute) and f.attr in DOC_REG:
                out[f".{f.attr}("] += 1
            if isinstance(f, ast.Name) and f.id in DOC_REG - {"tool", "command", "resource", "prompt"}:
                out[f"{f.id}("] += 1
            if isinstance(f, ast.Call) and isinstance(f.func, ast.Name) and f.func.id in DOC_REG:
                out[f"{f.func.id}()("] += 1
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Attribute) and d.attr in DOC_REG:
                    out[f"@.{d.attr}"] += 1
                elif isinstance(d, ast.Name) and d.id in DOC_REG - {"command", "resource", "prompt"}:
                    out[f"@{d.id}"] += 1
    return out
# (file, form): (number of uses, why the rule covers them). A module's own docstring (`client.__doc__`, `prj.__doc__`) is read by name and is not part of the rule.
DOCUSE_ALLOW = {
    ("stackshot/web/server.py", ".tool("): (12, "the @mcp.tool(...) decorators: a decorated function keeps the old rule (its docstring is a decorator's read)"),
    ("stackshot/web/server.py", ".resource("): (1, "the @mcp.resource decorator: a decorated function keeps the old rule"),
    ("tests/audit_run_scenario.py", ".prompt("): (3, "AR.prompt(...) is the audit's own function that builds a text, not a registry"),
    ("tests/release_queue_scenario.py", "import *"): (1, "the release harness's own helpers; no function of the checkout is read through them by a docstring"),
    ("tests/release_scenario.py", "import *"): (1, "the release harness's own helpers; no function of the checkout is read through them by a docstring"),
    ("tests/event_wait_scenario.py", "__doc__"): (2, "client.__doc__ twice, a module docstring: read by name, unchanged rule"),
    ("tests/locale_pages_scenario.py", "__doc__"): (1, "i18n.__doc__, a module docstring: read by name, unchanged rule"),
    ("tests/model_scenario.py", "__doc__"): (1, "server.stackshot_get.__doc__, a decorated tool: unchanged rule"),
    ("tests/project_record_scenario.py", "__doc__"): (1, "prj.__doc__, a module docstring: read by name, unchanged rule"),
    ("tests/question_scenario.py", "__doc__"): (2, "client.__doc__ (module, by name) and server._pilot_charge.__doc__ (a function it names: the name rule selects the suite)"),
    ("tests/rebullet_scenario.py", "__doc__"): (1, "rd_tool.__doc__, a module docstring: read by name, unchanged rule"),
    ("tests/released_scenario.py", "__doc__"): (5, "client.__doc__ five times, a module docstring: read by name, unchanged rule"),
    ("tests/retired_inputs_scenario.py", "__doc__"): (1, "_client.__doc__, a module docstring: read by name, unchanged rule"),
    ("tests/step_proof_scenario.py", "__doc__"): (2, "client.__doc__ twice, a module docstring: read by name, unchanged rule"),
    ("tests/terminal_prompt_scenario.py", "__doc__"): (2, "client.__doc__ (module, by name) and server._terminal_prompt.__doc__ (a function it names: the name rule selects the suite)"),
}
def doc_uses(files):
    """(file, form, uses found, uses pinned) for every form of {path: source} whose number of uses is not the number the allow list pins"""
    out = []
    for f, src in sorted(files.items()):
        found = doc_forms(src)
        for x in sorted(set(found) | {x for (g, x) in DOCUSE_ALLOW if g == f}):
            pinned = DOCUSE_ALLOW.get((f, x), (0, ""))[0]
            if found.get(x, 0) != pinned:
                out.append((f, x, found.get(x, 0), pinned))
    return out
CK = os.path.dirname(SCR)
scan, scan_bad = {}, []
for dp_, dirs_, names_ in os.walk(CK):
    dirs_[:] = sorted(d_ for d_ in dirs_ if not d_.startswith(".") and d_ not in ("__pycache__", "node_modules"))
    for nm_ in sorted(names_):
        fp_ = os.path.join(dp_, nm_)
        try:
            with open(fp_, "rb") as fh_:
                head_ = fh_.read(200)
            if nm_.endswith(".py") or (head_.startswith(b"#!") and b"python" in head_.split(b"\n")[0]):
                scan[os.path.relpath(fp_, CK)] = open(fp_, encoding="utf-8").read()
                doc_forms(scan[os.path.relpath(fp_, CK)])
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            scan_bad.append(os.path.relpath(fp_, CK))
drift = doc_uses(scan)
check("TRIPWIRE every Python file of the checkout can be read and parsed (an unreadable one is a use nobody looked at)", not scan_bad, scan_bad)
check("TRIPWIRE the use of every form that reads or registers a docstring is the pinned number on the allow list (DOCUSE_ALLOW): a changed count "
      "(" + "; ".join(f"{f}: {x} used {n}x, pinned {k}" for f, x, n, k in drift) + ") is a new or a removed use: look at the new use, does suite selection "
      "(tests/suitemap.py, *Docstrings*) still reach a suite that reads that function's docstring after a docstring-only change? Then pin the new count with a one-line reason",
      not drift, drift)
check("TRIPWIRE every allow list entry names a file the scan reads", all(f in scan for f, _ in DOCUSE_ALLOW), [f for f, _ in DOCUSE_ALLOW if f not in scan])
for what, code, form in (("getattr(x, '__doc__')", "d = getattr(m.f, '__doc__')", "getattr __doc__"), ("x.__doc__", "d = fns[name].__doc__", "__doc__"),
                         ("inspect.getdoc", "import inspect\nd = inspect.getdoc(f)", "getdoc"), ("an alias of getdoc", "from inspect import getdoc as gd\nd = gd(f)", "getdoc"),
                         ("inspect.getmembers", "import inspect\nm = inspect.getmembers(mod)", "getmembers"),
                         ("help(getattr(m, n))", "help(getattr(m, n))", "help("), ("ast.get_docstring", "import ast\nd = ast.get_docstring(node)", "get_docstring"),
                         ("from ast import get_docstring", "from ast import get_docstring\nd = get_docstring(node)", "get_docstring"),
                         ("pydoc.render_doc", "import pydoc\nt = pydoc.render_doc(f)", "render_doc"), ("import pydoc", "import pydoc\nt = pydoc.render_doc(f)", "pydoc"),
                         ("doctest", "import doctest\ndoctest.testmod(mod)", "doctest"), ("from X import *", "from mod import *", "import *"),
                         ("add_tool", "srv.add_tool(f)", ".add_tool("), ("a bare add_tool", "from srv import add_tool\nadd_tool(f)", "add_tool("),
                         (".command(", "app.command()(f)", ".command("), ("add_api_route", "app.add_api_route('/x', f)", ".add_api_route("),
                         (".tool(", "mcp.tool()(f)", ".tool("), ("a bare tool()(f)", "from reg import tool\ntool()(f)", "tool()("),
                         ("from reg import tool", "from reg import tool\ntool(f)", "import tool"), ("@mcp.tool without parentheses", "@mcp.tool\ndef f(x):\n    return 1", "@.tool"),
                         ("@tool without parentheses", "@tool\ndef f(x):\n    return 1", "@tool")):
    flagged = [x for _f, x, _n, _k in doc_uses({"tests/new_scenario.py": code})]
    check(f"TRIPWIRE fires on a new use: {what} in a new suite", form in flagged, flagged)
real_q = "tests/question_scenario.py"
check("TRIPWIRE a new use in a file that already has an entry for that form fails (getattr(m, n).__doc__ appended to question_scenario.py)",
      doc_uses({real_q: scan[real_q]}) == [] and doc_uses({real_q: scan[real_q] + "\ndef zz(m, n): return getattr(m, n).__doc__\n"}) == [(real_q, "__doc__", 3, 2)],
      doc_uses({real_q: scan[real_q] + "\ndef zz(m, n): return getattr(m, n).__doc__\n"}))
check("TRIPWIRE a removed use fails too, so the pinned count is never stale (one client.__doc__ taken out of question_scenario.py)",
      doc_uses({real_q: scan[real_q].replace("help_text = client.__doc__", "help_text = ''", 1)}) == [(real_q, "__doc__", 1, 2)],
      doc_uses({real_q: scan[real_q].replace("help_text = client.__doc__", "help_text = ''", 1)}))
check("TRIPWIRE stays quiet on the listed uses and on a bare module __doc__ (print(__doc__))",
      doc_uses({f: scan[f] for f, _ in DOCUSE_ALLOW}) == [] and doc_uses({"tests/new_scenario.py": "print(__doc__)"}) == [])

# ---- the annotation tripwire (Thu Nov 12th 2026). The names of a plain def's annotations are no read in a file with postponed annotations while that def's name is
# only ever called (tests/suitemap.py, *Imports and annotations*): nothing then evaluates them. That holds while nothing fetches a function by a variable name and hands
# it to a reader of annotations. The scan above lists the Python of the checkout; the forms that evaluate or carry annotations are pinned per file below, so a new use
# fails this scenario until its author has looked at whether the def it reaches keeps its annotations as reads. The tripwire selects nothing.
# Not covered: an eval or exec string, vars(fn)["__annotations__"] by a computed key, a framework that evaluates annotations of a plain function it finds by a variable name.
ANN_NAMES = ("get_type_hints", "get_annotations", "__annotations__", "annotationlib", "TypeAdapter", "create_model", "validate_call", "update_wrapper", "__wrapped__", "wraps")
def ann_forms(src):
    """the forms that evaluate, copy or inspect annotations a Python source uses, each with the number of its uses"""
    out = collections.Counter()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Attribute) and n.attr in ANN_NAMES:
            out[n.attr] += 1
        elif isinstance(n, ast.Name) and n.id in ANN_NAMES:
            out[n.id] += 1
        elif isinstance(n, ast.Import):
            out["annotationlib"] += sum(a.name.split(".")[0] == "annotationlib" for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            out["annotationlib"] += (n.module or "").split(".")[0] == "annotationlib"
            for a in n.names:
                if a.name in ANN_NAMES:
                    out[a.name] += 1
        elif isinstance(n, ast.keyword) and n.arg == "eval_str":
            out["eval_str"] += 1
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("getattr", "hasattr", "setattr") \
                and any(isinstance(a, ast.Constant) and a.value in ("__annotations__", "__wrapped__") for a in n.args):
            out["getattr of __annotations__ or __wrapped__"] += 1
    return +out
ANNUSE_ALLOW = {
    ("stackshot/web/server.py", "wraps"): (2, "functools.wraps twice: a decorator's wrapper, and the update tool's own signature kept visible; the function it copies from (_update_unlocked) is used as a value there, so its annotation names stay reads"),
    ("tests/read_only_scenario.py", "getattr of __annotations__ or __wrapped__"): (2, "hasattr(endpoint, '__wrapped__') twice: whether a route is wrapped, nothing is evaluated"),
}
def ann_uses(files):
    """(file, form, uses found, uses pinned) for every form of {path: source} whose number of uses is not the number the allow list pins"""
    out = []
    for f, src in sorted(files.items()):
        found = ann_forms(src)
        for x in sorted(set(found) | {x for (g, x) in ANNUSE_ALLOW if g == f}):
            pinned = ANNUSE_ALLOW.get((f, x), (0, ""))[0]
            if found.get(x, 0) != pinned:
                out.append((f, x, found.get(x, 0), pinned))
    return out
drift = ann_uses(scan)
check("TRIPWIRE the use of every form that evaluates, copies or inspects annotations is the pinned number on the allow list (ANNUSE_ALLOW): a changed count "
      "(" + "; ".join(f"{f}: {x} used {n}x, pinned {k}" for f, x, n, k in drift) + ") is a new or a removed use: look at it, can it reach a plain function by a variable name that "
      "the names rule (tests/suitemap.py, *Imports and annotations*) took to be only called? Then pin the new count with a one-line reason", not drift, drift)
check("TRIPWIRE every annotation allow list entry names a file the scan reads", all(f in scan for f, _ in ANNUSE_ALLOW), [f for f, _ in ANNUSE_ALLOW if f not in scan])
for what, code, form in (("typing.get_type_hints", "import typing\nh = typing.get_type_hints(f)", "get_type_hints"), ("from typing import get_type_hints", "from typing import get_type_hints\nh = get_type_hints(f)", "get_type_hints"),
                         ("inspect.get_annotations", "import inspect\nh = inspect.get_annotations(f)", "get_annotations"), ("fn.__annotations__", "a = fns[name].__annotations__", "__annotations__"),
                         ("inspect.signature(eval_str=True)", "import inspect\ns = inspect.signature(f, eval_str=True)", "eval_str"), ("annotationlib", "import annotationlib\nannotationlib.get_annotations(f)", "annotationlib"),
                         ("from annotationlib import X", "from annotationlib import get_annotations\nget_annotations(f)", "annotationlib"), ("a pydantic TypeAdapter", "from pydantic import TypeAdapter\nTypeAdapter(f)", "TypeAdapter"),
                         ("create_model", "from pydantic import create_model\ncreate_model('M')", "create_model"), ("validate_call", "from pydantic import validate_call\nvalidate_call(f)", "validate_call"),
                         ("functools.update_wrapper", "import functools\nfunctools.update_wrapper(g, f)", "update_wrapper"), ("functools.wraps", "import functools\nh = functools.wraps(f)(g)", "wraps"),
                         ("g.__wrapped__", "x = g.__wrapped__", "__wrapped__"), ("getattr(f, '__annotations__')", "a = getattr(f, '__annotations__')", "getattr of __annotations__ or __wrapped__")):
    flagged = [x for _f, x, _n, _k in ann_uses({"tests/new_scenario.py": code})]
    check(f"TRIPWIRE fires on a new use of an annotation reader: {what} in a new suite", form in flagged, flagged)
real_s = "stackshot/web/server.py"
check("TRIPWIRE a new use in a file that already has an entry for that form fails (one more functools.wraps appended to server.py)",
      ann_uses({real_s: scan[real_s]}) == [] and ann_uses({real_s: scan[real_s] + "\nimport functools\nz = functools.wraps(len)\n"}) == [(real_s, "wraps", 3, 2)],
      ann_uses({real_s: scan[real_s] + "\nimport functools\nz = functools.wraps(len)\n"}))
check("TRIPWIRE stays quiet on the listed uses and on a bare function def (def f(x: int) -> int)",
      ann_uses({f: scan[f] for f, _ in ANNUSE_ALLOW}) == [] and ann_uses({"tests/new_scenario.py": "def f(x: int) -> int:\n    return x"}) == [])

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": suitemap scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
