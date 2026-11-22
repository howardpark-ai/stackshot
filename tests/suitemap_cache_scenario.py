"""Scenario test for the index cache of tests/suitemap.py (Fri Nov 20th 2026) — a throwaway git repo of a few tiny modules, no live store, no network.

`select` and `audit` index the code of two revisions (Names). The index is built from a record of each file (made in one pass over its tree, kept by the
git blob id) and kept per revision (by tree id) in a folder of files, so a call that finds them reads instead of parsing. This suite checks that the shortcut
changes nothing and cannot hurt: the record is what the old pass over every node found; a hit is the build; a damaged, truncated, old-version or foreign
entry is rebuilt; the same content at two paths shares a record and a changed file misses; a write is all or nothing; two calls at once build once and a holder
that died blocks nobody; the folder stays inside its bound; the cache switched off gives the same index and leaves nothing behind.

`warm` builds and keeps the index of a revision ahead of the first select (what release.sh starts after a merge): it is kept, loaded by the next call, a no-op when kept already or with the cache off,
never kept incomplete, and reads the records of the files that did not change. A head that was cheap to build (Names skip_cheap) is not kept, a costly or warmed one is, and select prints the same
with no cache, a cold folder, a warmed one and a branch over it.

    tests/run-suite suitemap_cache        → exit 0 / 1"""
import ast, collections, errno, json, os, pathlib, pickle, re, subprocess, sys, textwrap, time, zlib, hashlib
SCR = os.path.dirname(os.path.abspath(__file__))
import _scratch
tmp = _scratch.mkdtemp(prefix="suitemapcache-"); T = pathlib.Path(tmp)
R = T / "repo"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

def git(*a): return subprocess.run(["git", "-C", str(R), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout
def write(rel, text): p = R / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
def commit(msg): git("add", "-A"); git("commit", "-qm", msg); return git("rev-parse", "HEAD").strip()

# [fixtures]
FIX = {
    "cfgmod.py": '''
        NAME = "x"

        def configure(v):
            return v
    ''',
    "pkg/__init__.py": '''
        from .core import Core
        from . import util
    ''',
    "pkg/util.py": '''
        ONE = 1

        def helper(x):
            return x + ONE

        class Helper:
            size = 2
    ''',
    "pkg/core.py": '''
        import os
        import cfgmod as _c
        from pkg.util import helper, Helper as H
        from .util import ONE
        try:
            from fastjson import loads
        except ImportError:
            from json import loads
        LIMIT = helper(3)

        class Core:
            def run(self):
                return _c.NAME + os.sep + str(H.size) + str(ONE) + str(loads("1"))
    ''',
    # one file at two paths: the same blob, a different package each
    "a/__init__.py": '"""a package"""\n',
    "b/__init__.py": '"""a package"""\n',
    "a/z.py": "ONE = 1\n",
    "b/z.py": "ONE = 2\n",
    "a/m.py": "from . import z\nVAL = z.ONE\n",
    "b/m.py": "from . import z\nVAL = z.ONE\n",
    # the module-level statements, one kind of each (the table GOLD_STMTS pins what the old pass made of them)
    "stm.py": '''
        """the module doc"""
        import os
        import cfgmod
        from pkg import util
        X = 1
        Y = X + len("a")
        Z = early()
        def early():
            return 1
        W = early()
        V = later()
        def later():
            return 2
        @unknown_deco
        def decorated():
            return 3
        class C:
            A = frozenset({1})
            B = early()
        class D:
            A = cfgmod.NAME
            B = os.system("x")
            E = util.ONE
        cfgmod.configure(1)
        print("x")
        N: int = cfgmod.NAME
        N += 1
        util.ONE = cfgmod.NAME
        if __name__ == "__main__":
            print(X)
    ''',
    # reads that no name shows, and reads of a module's names
    "dynmod.py": '''
        import cfgmod
        import importlib.util

        def a(n):
            return getattr(cfgmod, n)

        def b():
            return vars(cfgmod)

        def c():
            return importlib.util.spec_from_file_location("x", "pkg/util.py")

        def d():
            return __import__("pkg.util")

        def e():
            return list(globals())

        def f(o, n):
            return getattr(o, n)
    ''',
    # a file whose reading of the repo depends on what it imports as: built with its path and the repo, not kept as a record
    "vol.py": '''
        from inspect import getdoc as gd

        def f():
            return gd(f)

        def g():
            return 1
    ''',
    "imp.py": '''
        from importlib import import_module

        def load(n):
            return import_module(n)
    ''',
    "lit.py": '''
        m = __import__("cfgmod")
        n = m.NAME
    ''',
    "post.py": '''
        from __future__ import annotations
        from typing import Iterable

        def typed(x: Iterable[int]) -> int:
            return 0
    ''',
    "attrs.py": '''
        class Conf:
            LIMIT = 3
            NAME = "n"

            def get(self):
                return self.LIMIT

        def dyn(o, n):
            return getattr(o, n)
    ''',
    "bad.py": "def (:\n",
    "tests/a_scenario.py": '''
        import cfgmod
        from pkg import util
        print(cfgmod.NAME, util.ONE)
    ''',
    "bin/tool": '''
        #!/usr/bin/env python3
        import cfgmod
        print(cfgmod.NAME)
    ''',
}
FIELDS = ("path", "mod", "ok", "refs", "stmts", "functions", "classes", "effect_targets", "postponed", "import_ids", "import_seq", "narrow", "docreads",
          "dropped", "froms_all", "froms", "aliases", "defined", "open_names", "repo_tops")
# a revision's index, as JSON, from a fresh process (SCENARIO_SUITEMAP names the module: main's tool reads the same way); argv: revision, code to run first
DUMP = r'''
import sys, os, json
sys.path.insert(0, os.environ["SCENARIO_TESTS"])
s = __import__(os.environ.get("SCENARIO_SUITEMAP", "suitemap"))
rev, patch, fields = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
exec(patch)
def norm(x):
    if isinstance(x, (set, frozenset)): return sorted((norm(i) for i in x), key=repr)
    if isinstance(x, dict): return sorted(([norm(k), norm(v)] for k, v in x.items()), key=repr)
    if isinstance(x, (list, tuple)): return [norm(i) for i in x]
    return x
N = s.Names(rev)
out = {"repo": norm(set(N.repo)), "escaped": norm(N.escaped), "blind": N.blind, "order": list(N.files), "files": {}, "built": globals().get("CNT", [0, 0])[0], "builds": globals().get("CNT", [0, 0])[1]}
for f, m in N.files.items():
    out["files"][f] = {k: norm(getattr(m, k)) for k in fields}
m = N.files.get("pkg/core.py")
out["text"] = {k: norm(getattr(m, k)) for k in ("text", "body_of", "ddoc", "pdoc")} if m else None
print(json.dumps(out))
'''
COUNT = '''
CNT = [0, 0]   # records built, indexes built
_bf = s.build_facts
def _count(*a, **k):
    if len(a) < 2 and not k.get("ctx"): CNT[0] += 1   # a file built for its path and the repo (volatile) is no record
    return _bf(*a, **k)
s.build_facts = _count
_bn = s.Names.build
def _built(self, rev, cache):
    CNT[1] += 1
    return _bn(self, rev, cache)
s.Names.build = _built
'''
# [end fixtures]

R.mkdir(); git("init", "-q", "-b", "main")
for rel, text in FIX.items(): write(rel, text)
C1 = commit("one")
write("pkg/util.py", "ONE = 5\n\ndef helper(x):\n    return x + ONE\n\nclass Helper:\n    size = 2\n")   # one file changed: one record is new
C2 = commit("two")
for rel in ("a/__init__.py", "a/z.py", "a/m.py"): write("c/" + rel[2:], (R / rel).read_text(encoding="utf-8"))
C3 = commit("three")   # a package that is the same three blobs as a: no record is new, the index is not the same
distinct = len({git("rev-parse", f"{C1}:{p}").strip() for p in FIX if p.endswith(".py")})
TREE = {c: git("rev-parse", c + "^{tree}").strip() for c in (C1, C2, C3)}

ENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "SUITEMAP_", "GITHUB_", "SCENARIO_"))}
ENV.update(SCENARIO_TESTS=SCR, SUITEMAP_ROOT=str(R), HOME=str(T / "home"), XDG_CACHE_HOME=str(T / "xdg"), STACKSHOT_TEST_LAUNCHER="")   # no test launcher here, whatever the machine has configured
ALL = ",".join(FIELDS)
def cdir(name): return str(T / ("cd-" + name))
def dump(rev, name, env=None, patch="", fields=ALL, timeout=90):
    """the index of a revision from a fresh process, with the cache folder of `name`: (the JSON as a dict or None, stderr)"""
    e = dict(ENV); e["SUITEMAP_CACHE_DIR"] = cdir(name); e.update(env or {})
    r = subprocess.run([sys.executable, "-c", DUMP, rev, patch, fields], capture_output=True, text=True, env=e, cwd=str(R), timeout=timeout)
    try: return json.loads(r.stdout), r.stderr
    except ValueError: return None, r.stdout + r.stderr
def entries(name, kind=""): return sorted(e for e in os.listdir(cdir(name)) if e.startswith(kind)) if os.path.isdir(cdir(name)) else []

# in-process, for what needs no process of its own: the module as the suites run it
sys.path.insert(0, SCR); os.environ["SUITEMAP_ROOT"] = str(R)
import suitemap as s

# ---------------------------------------------------------------- the record is what the old pass over every node found
tests_py = sorted(pathlib.Path(SCR).glob("*.py"))[:60] + [R / p for p in FIX if p.endswith(".py") and p != "bad.py"]
trees = []
for p in tests_py:
    try: trees.append(ast.parse(p.read_text(encoding="utf-8")))
    except (SyntaxError, ValueError, OSError): pass
same_walk = all(len(a) == len(b) and all(x is y for x, y in zip(a, b)) for a, b in ((s.walk_nodes(t), list(ast.walk(t))) for t in trees))
check("CACHE 1 walk_nodes gives the nodes of ast.walk, the same objects in the same order, on every file of the checkout's tests and of the fixtures", same_walk and len(trees) > 40, len(trees))
names = [n for t in trees for n in ast.walk(t) if isinstance(n, (ast.Name, ast.Attribute))]
check("CACHE 2 chain_of is dotted split into its parts, and None where dotted is None, on every name and attribute of those files",
      all((s.chain_of(n) is None and s.dotted(n) is None) or ".".join(s.chain_of(n)) == s.dotted(n) for n in names) and len(names) > 5000, len(names))

def ref_links(tree, mod, path, repo):
    """aliases, froms and froms_all as the old pass over every node made them"""
    aliases, froms, froms_all = {}, {}, collections.defaultdict(list)
    pkg = mod if path.endswith("/__init__.py") else mod.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname: aliases[a.asname] = a.name
                else: aliases[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join([*up, base] if base else up)
            for a in node.names:
                local = a.asname or a.name
                if f"{base}.{a.name}" in repo: aliases[local] = f"{base}.{a.name}"
                else: froms[local] = (base, a.name); froms_all[local].append((base, a.name))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            c = node.value
            if isinstance(c, ast.Call) and s.dotted(c.func) in ("__import__", "importlib.import_module") and c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str):
                aliases[node.targets[0].id] = c.args[0].value
    return aliases, froms, froms_all

def ref_refs(src, mod, aliases, froms, froms_all, repo):
    """the keys each scope reads, as the old `read` found them (class rule C1: no attribute keys), from one pass over every node"""
    body_of, _, _, tree, _ = s.scopes(src)
    def lit(call):
        if isinstance(call, ast.Call) and s.dotted(call.func) in ("__import__", "importlib.import_module") and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            return call.args[0].value
    def keys(node):
        if isinstance(node, ast.Call):
            m = lit(node); return {(m, "*")} if m else set()
        d = s.dotted(node)
        if not d: return set()
        chain = d.split("."); out = {(mod, chain[0])}; m = None
        if chain[0] in froms: out.update(froms_all[chain[0]])
        elif chain[0] in aliases: m = aliases[chain[0]]
        if m is not None:
            rest = chain[1:]
            while rest and f"{m}.{rest[0]}" in repo: m = f"{m}.{rest[0]}"; rest = rest[1:]
            out.add((m, rest[0]) if rest else (m, "<module>"))
            if len(rest) > 1: out.add(("~", m, tuple(rest)))
        return out
    refs = collections.defaultdict(set)
    for node in ast.walk(tree):
        sc, ks = None, set()
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            sc, ks = body_of[node.lineno], keys(node)
            if node.id == "globals": ks = ks | {(mod, "*")}
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            sc, ks = body_of[node.lineno], (keys(node) if s.dotted(node) else set())
            routes_ = node.attr in s.ROUTE_ATTRS
            if node.attr in s.ENUMERATE_ATTRS or routes_: ks = ks | {("*", s.ENUMERATE)}
            if routes_: ks = ks | {("*", s.ENUMERATE_R)}
        elif isinstance(node, ast.Call):
            f = s.dotted(node.func)
            if f == "getattr" and node.args and (len(node.args) < 2 or not isinstance(node.args[1], ast.Constant)):
                ks = {(m, "*") for m, n in keys(node.args[0]) if n == "<module>"}
            elif f in ("vars", "dir", "inspect.getmembers") and node.args:
                ks = {(m, "*") for m, n in keys(node.args[0]) if n == "<module>"}
            elif f and (f in s.DYN_LOAD or f.split(".")[-1] in s.DYN_LOAD):
                lits = [a.value for a in ast.walk(node) if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.endswith(".py")]
                ks = {(m, "*") for m in repo if lits and m.split(".")[-1] == os.path.basename(lits[-1]).removesuffix(".py")} or {("*", "*")}
            else:
                m = lit(node); ks = {(m, "*")} if m else set()
            sc = body_of[node.lineno]
        if sc is not None and ks: refs[sc] |= ks
    return {k: v for k, v in refs.items()}

os.environ["SUITEMAP_CLASS_RULE"] = "C1"   # no attribute keys: what the reference pass knows
repo = s.Repo({s.modname(p) for p in FIX if p.endswith(".py") and not s.SUITE_RE.match(p) and p != "bad.py"})
checked, link_bad, ref_bad = 0, [], []
for p in sorted(FIX):
    if not p.endswith(".py") or p == "bad.py" or s.SUITE_RE.match(p): continue
    src = (R / p).read_text(encoding="utf-8")
    facts = s.build_facts(src)
    if facts.get("volatile"): facts = s.build_facts(src, (p, repo))
    m = s.ModNames(p, facts, repo, None)
    tree = ast.parse(src)
    a, f, fa = ref_links(tree, s.modname(p), p, repo)
    if (m.aliases, m.froms, dict(m.froms_all)) != (a, f, dict(fa)): link_bad.append(p)
    if p not in ("attrs.py", "post.py") and {k: set(v) for k, v in m.refs.items()} != ref_refs(src, s.modname(p), a, f, fa, repo): ref_bad.append(p)
    checked += 1
os.environ.pop("SUITEMAP_CLASS_RULE")
check("CACHE 3 a record replayed for a file's own path and the repo has the aliases, the names taken from a module and every source of a name the old pass over every node made (relative imports, a try/except fallback, __import__)",
      not link_bad and checked > 12, (link_bad, checked))
check("CACHE 4 …and the keys every scope reads that the old pass found: names, attributes, getattr and vars of a module, a module loaded by path, __import__, globals()", not ref_bad, ref_bad)

# the statements of stm.py as main's per-pass index made them (read from it, not from this change)
GOLD_STMTS = [list(r) for r in [(1, "bind", ["__doc__"], []), (2, "bind", ["os"], []), (3, "import-repo", ["cfgmod"], ["cfgmod"]), (4, "import-repo", ["util"], ["pkg.util"]), (5, "bind", ["X"], []),
 (6, "bind", ["Y"], [["*", ".a"], ["stm", "X"], ["stm", "len"]]), (7, "effect", ["Z"], []), (8, "bind", ["early"], []), (10, "bind", ["W"], [["stm", "early"]]),
 (11, "effect", ["V"], []), (12, "bind", ["later"], []), (14, "effect", ["decorated"], [["stm", "unknown_deco"]]),
 (17, "bind", ["C"], [["stm", "A"], ["stm", "B"], ["stm", "early"], ["stm", "frozenset"]]),
 (20, "effect", ["D"], [["*", ".NAME"], ["*", ".ONE"], ["*", ".system"], ["*", ".x"], ["cfgmod", "<module>"], ["cfgmod", "NAME"], ["stm", "A"], ["stm", "B"], ["stm", "cfgmod"]]),
 (24, "effect-mod", [], [["*", ".configure"], ["cfgmod", "<module>"], ["cfgmod", "configure"], ["stm", "cfgmod"]]), (25, "effect", [], [["*", ".x"]]),
 (26, "bind", ["N"], [["*", ".NAME"], ["cfgmod", "<module>"], ["cfgmod", "NAME"], ["stm", "cfgmod"], ["stm", "int"]]), (27, "bind", ["N"], [["stm", "N"]]),
 (28, "bind", [["pkg.util", "ONE"]], [["*", ".NAME"], ["*", ".ONE"], ["cfgmod", "<module>"], ["cfgmod", "NAME"], ["stm", "cfgmod"]]), (29, "main", [], [["*", ".__main__"]])]]
base1, err = dump(C1, "base1", env={"SUITEMAP_CACHE": "0"})
check("CACHE 5 the fixture index is made (the baseline of what follows, with the cache off)", base1 is not None and "pkg/core.py" in base1["files"], err[-300:])
got = [[st[0], st[2], st[3], st[4]] for st in base1["files"]["stm.py"]["stmts"]] if base1 else None
check("CACHE 6 the module-level statements of one file of each kind come out as the old pass made them (bind, effect, effect-mod, import-repo, main; a call of a function defined later is an effect, of one defined above a bind; a class body that fails at its impure call keeps what it read before it)",
      got == GOLD_STMTS, got)
vol = base1["files"]["vol.py"] if base1 else {}
check("CACHE 7 a file that reads a docstring through an alias made by `from inspect import getdoc as gd` (built with its path and the repo, not kept as a record) has the scope of the read, as before",
      vol.get("docreads") == ["f"], vol.get("docreads"))
check("CACHE 8 a file that has a name `import_module` taken from importlib is built the same way and still holds its read", base1 and base1["files"]["imp.py"]["froms"] == [["import_module", ["importlib", "import_module"]]], base1 and base1["files"]["imp.py"]["froms"])
check("CACHE 9 a file that does not parse is in the index as one that does not (nothing read, nothing bound)", base1 and base1["files"]["bad.py"]["ok"] is False and base1["files"]["bad.py"]["refs"] == [], base1 and base1["files"]["bad.py"])
att = base1["files"]["attrs.py"] if base1 else {}
check("CACHE 10 under rule C2 a plain class's literal assignments are narrowed to their attribute (LIMIT, NAME) and a getattr by a name that is no literal reads every attribute (`.*`) of a name the scope took",
      att.get("narrow") == [[2, ["LIMIT"]], [3, ["NAME"]]] and ["dyn", [["*", ".*"], ["attrs", "getattr"], ["attrs", "n"], ["attrs", "o"]]] in att.get("refs", []), att)
check("CACHE 11 a script with a python shebang that is no .py file is read for the names it uses (cfgmod.NAME escapes nothing here: the index is not blind)", base1 and base1["blind"] is False, base1 and base1["blind"])

# ---------------------------------------------------------------- a hit is the build
d1, err = dump(C1, "hit", patch=COUNT)
d2, err2 = dump(C1, "hit", patch=COUNT)
same = lambda x, y: x is not None and y is not None and {k: v for k, v in x.items() if k not in ("built", "builds")} == {k: v for k, v in y.items() if k not in ("built", "builds")}
check("CACHE 12 the first call with an empty folder builds (a record for each distinct file) and keeps the index of the tree; the second finds it: the same index, nothing built and nothing parsed",
      same(d1, base1) and same(d2, base1) and d1["built"] >= distinct and d1["builds"] == 1 and d2["built"] == 0 and d2["builds"] == 0 and entries("hit", "tree-") == ["tree-" + TREE[C1]], (d1 and d1["built"], d2 and d2["built"], entries("hit", "tree-"), err[-200:], err2[-200:]))
check("CACHE 13 the folder holds one record for each distinct file content of the revision, kept under the blob id of the file", len(entries("hit", "facts-")) >= distinct - 1 and all(len(e) == len("facts-") + 40 for e in entries("hit", "facts-")), (len(entries("hit", "facts-")), distinct))
for e in entries("hit", "tree-"): os.unlink(os.path.join(cdir("hit"), e))
d3, err3 = dump(C1, "hit", patch=COUNT)
check("CACHE 14 with the tree's entry gone and the records kept, the index is assembled from the records alone: the same index, no record built", same(d3, base1) and d3["built"] == 0 and entries("hit", "tree-"), (d3 and d3["built"], err3[-200:]))
check("CACHE 15 a changed file's content is a miss for itself only: the next revision builds exactly one record (the changed pkg/util.py) and its index is what the cache off makes",
      (lambda x, y: same(x, y) and x["built"] == 1)(dump(C2, "hit", patch=COUNT)[0], dump(C2, "off2", env={"SUITEMAP_CACHE": "0"})[0]), None)
d4 = dump(C3, "hit", patch=COUNT)[0]
off3 = dump(C3, "off3", env={"SUITEMAP_CACHE": "0"})[0]
check("CACHE 16 the same content at another path shares the record: a revision that adds a package of three files already held builds no record, and the index of the new paths is what the cache off makes",
      same(d4, off3) and d4["built"] == 0 and "c/m.py" in d4["files"], d4 and d4["built"])
am, bm = (base1["files"][p] for p in ("a/m.py", "b/m.py")) if base1 else (None, None)
d4m = d4["files"] if d4 else {}
check("CACHE 17 …and one blob in two packages is replayed for each place: `from . import z` is the module a.z in a/m.py, b.z in b/m.py and c.z in c/m.py",
      base1 and am["aliases"] == [["z", "a.z"]] and bm["aliases"] == [["z", "b.z"]] and d4m["c/m.py"]["aliases"] == [["z", "c.z"]], (am and am["aliases"], bm and bm["aliases"]))
check("CACHE 18 a file's text, scopes and docstring lines are read from its blob when asked (a changed file needs them), the same from a warm cache as from a build",
      d2 and d2["text"] and d2["text"] == base1["text"] and len(d2["text"]["text"]) > 10, d2 and d2["text"] and list(d2["text"]))

# ---------------------------------------------------------------- an entry that cannot be trusted is rebuilt
def fresh(name):
    """a folder holding the index of C1 and its records (a copy of the folder `hit` made before the changes above)"""
    import shutil
    shutil.rmtree(cdir(name), ignore_errors=True); os.makedirs(cdir(name))
    dump(C1, name)
    return cdir(name)
tree_entry = lambda d: os.path.join(d, "tree-" + TREE[C1])
def damage(name, how):
    d = fresh(name); p = tree_entry(d); raw = open(p, "rb").read(); ver = s.cache_version()
    if how == "truncated": open(p, "wb").write(raw[: len(raw) * 2 // 5])
    elif how == "empty": open(p, "wb").write(b"")
    elif how == "garbage": open(p, "wb").write(os.urandom(300))
    elif how == "bytes flipped": b = bytearray(raw); b[len(b) // 2] ^= 0xFF; b[len(b) // 3] ^= 0xFF; open(p, "wb").write(bytes(b))
    elif how == "tampered, checksum kept":   # a valid entry of the right version whose data was changed, behind the checksum of the old data
        n = len(s.CACHE_MAGIC); body = zlib.compress(pickle.dumps((ver, {"repo": [], "files": {}, "escaped": [], "blind": False})), 1)
        open(p, "wb").write(raw[: n + 32].replace(raw[n:n + 32], raw[n:n + 32]) + body)
    elif how == "old version":
        data = s.IndexCache(d).get("tree", TREE[C1]); s.IndexCache(d, version="an older tool").put("tree", TREE[C1], data)
    elif how == "a class in it":   # a checksum and a version that are right, and a function in the data: no entry of ours holds one
        body = zlib.compress(pickle.dumps((ver, os.getcwd)), 1)
        open(p, "wb").write(s.CACHE_MAGIC + hashlib.blake2b(body, digest_size=32).digest() + body)
    return d
for how in ("truncated", "empty", "garbage", "bytes flipped", "tampered, checksum kept", "old version", "a class in it"):
    d = damage("dmg", how)
    x, e1 = dump(C1, "dmg", patch=COUNT)
    try: again = s.IndexCache(d).get("tree", TREE[C1])
    except Exception as ex: again = repr(ex)
    check(f"CACHE 19 a tree entry that is {how} is no failure and no answer: the index is rebuilt (the same as the cache off), the entry is made again and holds the real index",
          same(x, base1) and isinstance(again, dict) and again.get("files") and "pkg/core.py" in again["files"], (x and x["built"], e1[-300:]))
d = fresh("dmg2"); fp = next((os.path.join(d, e) for e in sorted(os.listdir(d)) if e.startswith("facts-")), None)
if fp: open(fp, "wb").write(open(fp, "rb").read()[:30])
if os.path.exists(tree_entry(d)): os.unlink(tree_entry(d))
x, e1 = dump(C1, "dmg2", patch=COUNT)
check("CACHE 20 a record that is truncated is rebuilt, and only that one (one record built), and the index is the same", same(x, base1) and x["built"] == 1, (x and x["built"], e1[-300:]))

# ---------------------------------------------------------------- the entry file is written whole or not at all
d = str(T / "atomic"); os.makedirs(d)
c = s.IndexCache(d, version="v1"); K = "a" * 40
c.put("facts", K, {"n": 1})
real_replace = os.replace
def boom(a, b): raise OSError("no space left")
os.replace = boom
try: c.put("facts", K, {"n": 2}); c.put("facts", "b" * 40, {"n": 3})
finally: os.replace = real_replace
check("CACHE 21 a write that fails before the rename leaves the old entry whole, no entry where there was none and no leftover file: an entry is the old data or the new, never a part",
      c.get("facts", K) == {"n": 1} and c.get("facts", "b" * 40) is None and sorted(os.listdir(d)) == ["facts-" + K], sorted(os.listdir(d)))
c.put("facts", K, {"n": 2})
check("CACHE 22 …and a write that succeeds replaces it whole, and the entry carries the checksum that reads back (the data is what was written)", c.get("facts", K) == {"n": 2} and not [e for e in os.listdir(d) if e.startswith(".tmp-")], sorted(os.listdir(d)))
check("CACHE 23 a key that is not a git object id is no entry (it cannot name a path)", (c.put("facts", "../x" + "0" * 40, {"n": 1}), c.get("facts", "../x" + "0" * 40))[1] is None and sorted(os.listdir(d)) == ["facts-" + K], sorted(os.listdir(d)))

# ---------------------------------------------------------------- the version
v = str(T / "version"); os.makedirs(v)
c1, c2 = s.IndexCache(v, version="one"), s.IndexCache(v, version="two")
c1.put("facts", K, {"n": 1})
check("CACHE 24 an entry made by another version is a miss and is removed (the next put makes it), and one of the same version is a hit", c1.get("facts", K) == {"n": 1} and c2.get("facts", K) is None and not os.path.exists(c1.path("facts", K)), os.listdir(v))
vers = {}
for rule in ("C2", "C1"):
    os.environ["SUITEMAP_CLASS_RULE"] = rule; s._CACHE_VERSION = None; vers[rule] = s.cache_version()
os.environ.pop("SUITEMAP_CLASS_RULE"); s._CACHE_VERSION = None
vers["annotation"] = (lambda: (os.environ.__setitem__("SUITEMAP_ANNOTATION_RULE", "N1"), s.cache_version())[1])(); os.environ.pop("SUITEMAP_ANNOTATION_RULE"); s._CACHE_VERSION = None
vers["route"] = (lambda: (os.environ.__setitem__("SUITEMAP_ROUTE_RULE", "R1"), s.cache_version())[1])(); os.environ.pop("SUITEMAP_ROUTE_RULE"); s._CACHE_VERSION = None
base_v = s.cache_version()
check("CACHE 25 the version is this file's bytes, the Python and the rules that shape a record: another class, annotation or route rule is another version (an index made under C1 is no answer under C2), the same rules are the same",
      len({vers["C2"], vers["C1"], vers["annotation"], vers["route"]}) == 4 and vers["C2"] == base_v and s.cache_version() == base_v, vers)
x1 = dump(C1, "rules1", env={"SUITEMAP_CLASS_RULE": "C1"}, patch=COUNT)[0]
x2 = dump(C1, "rules1", patch=COUNT)[0]
check("CACHE 26 a folder made under rule C1 is no answer under C2: the C2 call builds again, and its index is what the cache off makes under C2", same(x2, base1) and x1 and x1["built"] >= distinct and x2["built"] >= distinct, (x1 and x1["built"], x2 and x2["built"]))

# ---------------------------------------------------------------- two calls at once build once; a holder that died holds nothing
CHILD = ("import sys, os, time; sys.path.insert(0, os.environ['SCENARIO_TESTS']); import suitemap as s; c = s.IndexCache(sys.argv[1], version='v'); fd = c.acquire(sys.argv[2], 5); "
         "print('held' if fd is not None else 'not held', flush=True); time.sleep(float(sys.argv[3]))")
SLOW = '''
import time
_bb = s.Names.build
def _slow(self, rev, cache):
    open(os.environ["SCENARIO_COUNT"], "a").write("b\\n")
    time.sleep(2.0)
    return _bb(self, rev, cache)
s.Names.build = _slow
'''
cnt = T / "builds"; cnt.write_text("")
os.makedirs(cdir("par"), exist_ok=True)
procs = []
for i in range(2):
    e = dict(ENV); e.update(SUITEMAP_CACHE_DIR=cdir("par"), SCENARIO_COUNT=str(cnt))
    procs.append(subprocess.Popen([sys.executable, "-c", DUMP, C1, SLOW, ALL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e, cwd=str(R)))
outs = [p.communicate(timeout=90) for p in procs]
got = []
for o, _ in outs:
    try: got.append(json.loads(o))
    except ValueError: got.append(None)
check("CACHE 27 two calls for the same revision at the same time build it once (the second waits for the lock and reads what the first made), and both have the index the cache off makes",
      cnt.read_text().count("b") == 1 and all(same(g, base1) for g in got), (cnt.read_text(), [o[1][-200:] for o in outs]))

os.makedirs(cdir("lock"), exist_ok=True); os.makedirs(cdir("live"), exist_ok=True)
hold = subprocess.Popen([sys.executable, "-c", CHILD, cdir("lock"), "dead", "25"], stdout=subprocess.PIPE, text=True, env=ENV)
try:
    held = hold.stdout.readline().strip()
    other = s.IndexCache(cdir("lock"), version="v")
    t0 = time.monotonic(); blocked = other.acquire("dead", 0.4); waited = time.monotonic() - t0
    hold.kill(); hold.wait()
    t0 = time.monotonic(); fd = other.acquire("dead", 10); took = time.monotonic() - t0
    if fd is not None: os.close(fd)
finally:
    hold.kill(); hold.wait()
check("CACHE 28 a lock held by a live process is waited for, and a process that died (killed here) holds nothing: the next call has the lock at once", held == "held" and blocked is None and waited >= 0.35 and fd is not None and took < 2, (held, blocked, waited, fd, took))
hold = subprocess.Popen([sys.executable, "-c", CHILD, cdir("live"), "tree-" + TREE[C1], "25"], stdout=subprocess.PIPE, text=True, env=ENV)
try:
    held = hold.stdout.readline().strip()
    t0 = time.monotonic()
    x, e1 = dump(C1, "live", patch=COUNT + "\ns.CACHE_LOCK_WAIT = 0.3\n", timeout=60)
    took = time.monotonic() - t0
finally:
    hold.kill(); hold.wait()
check("CACHE 29 a call whose wait runs out (the holder is alive and slow) builds the index itself and has the index the cache off makes, after about the wait and not the holder's time", held == "held" and same(x, base1) and x["built"] >= distinct and took < 20, (held, took, e1[-300:]))
cc = s.IndexCache(cdir("lock2"), version="v") if os.makedirs(cdir("lock2"), exist_ok=True) is None else None
with cc.lock("n", 5) as g1:
    with cc.lock("n", 0.2) as g2: pass
check("CACHE 30 lock() holds for the body and says whether it has the lock: the first caller True, a second within its wait False, and the lock is free again after", g1 is True and g2 is False and cc.acquire("n", 1) is not None, (g1, g2))

# ---------------------------------------------------------------- the size bound
e = str(T / "evict"); os.makedirs(e)
ev = s.IndexCache(e, version="v", max_bytes=3200)
keys = [f"{i:040x}" for i in range(8)]
now = time.time()
for i, k in enumerate(keys):
    ev.put("facts", k, os.urandom(500).hex())
    os.utime(ev.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
old_tmp, new_tmp = os.path.join(e, ".tmp-old_0001"), os.path.join(e, ".tmp-new_0001")
open(old_tmp, "w").write("x"); open(new_tmp, "w").write("x"); os.utime(old_tmp, (now - 3 * 86400, now - 3 * 86400))
before = sum(os.path.getsize(os.path.join(e, n)) for n in os.listdir(e))
ev.get("facts", keys[0])   # used just now: the oldest by its write is the newest by its use
ev.trim()
left = sorted(n for n in os.listdir(e) if n.startswith("facts-"))
size = sum(os.path.getsize(os.path.join(e, n)) for n in left)
check("CACHE 31 a folder over its bound is trimmed to under it, the entries used longest ago first: the oldest write that was read just now stays, the next oldest goes, the newest stay",
      before > 3200 and size <= 3200 and "facts-" + keys[0] in left and "facts-" + keys[1] not in left and "facts-" + keys[7] in left, (before, size, left))
check("CACHE 32 …and the leftover of a write that died a day ago goes with it while a fresh temporary file stays", not os.path.exists(old_tmp) and os.path.exists(new_tmp), os.listdir(e))
big = s.IndexCache(str(T / "evict2"), version="v", max_bytes=10 ** 9) if os.makedirs(str(T / "evict2")) is None else None
big.put("facts", keys[0], "x"); big.trim()
check("CACHE 33 a folder under its bound is left as it is, and the bound is a constant of the tool, stated (CACHE_MAX_BYTES)", os.path.exists(big.path("facts", keys[0])) and 0 < s.CACHE_MAX_BYTES <= 1 << 30, s.CACHE_MAX_BYTES)

# ---------------------------------------------------------------- off is the same index and nothing kept
off, err = dump(C1, "offdir", env={"SUITEMAP_CACHE": "0"})
check("CACHE 34 with SUITEMAP_CACHE=0 the index is what the cache gives and nothing is read or written (the folder is not even made)", same(off, base1) and not os.path.exists(cdir("offdir")), (os.path.exists(cdir("offdir")), err[-200:]))
bad = subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), "list"], capture_output=True, text=True, env={**ENV, "SUITEMAP_CACHE": "2"}, cwd=str(R))
good = subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), "list"], capture_output=True, text=True, env={**ENV, "SUITEMAP_CACHE": "0"}, cwd=str(R))
check("CACHE 35 a value of SUITEMAP_CACHE that is neither 0 nor 1 is an error when a command starts, as a rule's is, and 0 is not", bad.returncode != 0 and "SUITEMAP_CACHE" in bad.stderr and good.returncode == 0, (bad.returncode, bad.stderr[-200:], good.returncode))
dump(C1, "unused", env={"SUITEMAP_CACHE_DIR": "", "XDG_CACHE_HOME": str(T / "xdg"), "HOME": str(T / "home")})
check("CACHE 36 without SUITEMAP_CACHE_DIR the folder is stackshot/suitemap under $XDG_CACHE_HOME, and never inside the checkout", os.path.isdir(T / "xdg" / "stackshot" / "suitemap") and any(n.startswith("tree-") for n in os.listdir(T / "xdg" / "stackshot" / "suitemap"))
      and not [p for p in R.rglob("*") if p.name.startswith(("tree-", "facts-", "lock-"))], os.listdir(T / "xdg") if (T / "xdg").exists() else None)
unw = T / "readonly"; unw.mkdir()
unw.chmod(0o500)
try:
    ro, err = dump(C1, "ro", env={"SUITEMAP_CACHE_DIR": str(unw / "inner")})
finally:
    unw.chmod(0o700)
check("CACHE 37 a cache folder that cannot be made is no failure: the index is the same, built without it", same(ro, base1) or os.geteuid() == 0, err[-300:])

# ---------------------------------------------------------------- what a version, an entry, a trim and a lock must not do
import errno
real_file, real_version = s.__file__, sys.version
try:
    copy = T / "suitemap_edited.py"
    copy.write_bytes(pathlib.Path(real_file).read_bytes() + b"\n# a rule edited\n")
    s.__file__ = str(copy); s._CACHE_VERSION = None; v_edit = s.cache_version()
    s.__file__ = real_file; s._CACHE_VERSION = None; v_same = s.cache_version()
    sys.version = real_version + " (another build)"; s._CACHE_VERSION = None; v_py = s.cache_version()
finally:
    s.__file__, sys.version = real_file, real_version; s._CACHE_VERSION = None
check("CACHE 38 an edit of suitemap.py itself is another version (an index made by the old rules is no answer to the new), and the same file is the same", v_edit != base_v and v_same == base_v, (v_edit, v_same, base_v))
check("CACHE 39 another Python (its ast may read a file differently) is another version", v_py != base_v and v_py != v_edit, (v_py, base_v))
gd = str(T / "glob"); os.makedirs(gd)
cg = s.IndexCache(gd, version="v")
def forge(data):
    body = zlib.compress(pickle.dumps(("v", data)), 1)
    with open(cg.path("facts", K), "wb") as f: f.write(s.CACHE_MAGIC + hashlib.blake2b(body, digest_size=32).digest() + body)
forge({"n": 1}); plain = cg.get("facts", K)
forge(range(3)); named = cg.get("facts", K)
check("CACHE 40 an entry with a good magic, checksum and version that names a global (a class, a function) is no entry and is removed, while the same made of plain data is read", plain == {"n": 1} and named is None and not os.path.exists(cg.path("facts", K)), (plain, named))
write("bin/tool", "#!/usr/bin/env python3\ndef broken(:\n")   # a script that does not parse: the index is blind (any function may be reached by it)
C4 = commit("four")
b1, e1 = dump(C4, "blind", patch=COUNT); b2, e2 = dump(C4, "blind", patch=COUNT); b0, e0 = dump(C4, "blind0", env={"SUITEMAP_CACHE": "0"})
check("CACHE 41 an index that is blind (a script that does not parse) is blind when read back from its tree entry, and is what the build made", b0 and b0["blind"] is True and b1 and b1["blind"] is True and b2 and b2["builds"] == 0 and b2["blind"] is True and same(b1, b0) and same(b2, b0),
      (b0 and b0["blind"], b1 and b1["blind"], b2 and (b2["builds"], b2["blind"]), (e0 + e1 + e2)[-200:]))
fo = str(T / "foreign"); os.makedirs(fo)
fx = s.IndexCache(fo, version="v", max_bytes=3200)
precious = os.path.join(fo, "precious.txt"); open(precious, "w").write("p" * 5000); os.utime(precious, (now - 5000, now - 5000))
os.makedirs(os.path.join(fo, "sub")); open(os.path.join(fo, "sub", "x"), "w").write("y" * 5000)
for i, k in enumerate(keys):
    fx.put("facts", k, os.urandom(500).hex()); os.utime(fx.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
fx.trim()
own = sorted(n for n in os.listdir(fo) if n.startswith("facts-"))
check("CACHE 42 a trim over the bound removes entries of the cache only: a file of another kind in the folder (older, and larger than the bound) and a folder survive, and the entries are still brought under the bound",
      os.path.exists(precious) and os.path.exists(os.path.join(fo, "sub", "x")) and 0 < len(own) < len(keys) and sum(os.path.getsize(os.path.join(fo, n)) for n in own) <= 3200, (sorted(os.listdir(fo)), own))
ld = str(T / "nolock"); os.makedirs(ld)
cn = s.IndexCache(ld, version="v")
real_flock = s.fcntl.flock
def no_lock(fd, op): raise OSError(errno.ENOLCK, "No locks available")
t0 = time.monotonic()
s.fcntl.flock = no_lock
try:
    got = cn.acquire("n", 3)
finally:
    s.fcntl.flock = real_flock
took = time.monotonic() - t0
check("CACHE 43 a file system that cannot lock (flock fails with ENOLCK) is no holder: the call gives up the lock at once and builds, and does not wait the wait out", got is None and took < 1.5, (got, took))
rel, err = dump(C1, "unused-rel", env={"SUITEMAP_CACHE_DIR": "relcache", "XDG_CACHE_HOME": "relxdg"})
home_cache = T / "home" / ".cache" / "stackshot" / "suitemap"
check("CACHE 44 a relative SUITEMAP_CACHE_DIR or XDG_CACHE_HOME is ignored, as the XDG base directory spec has it (the cache is in ~/.cache, and nothing is made beside the checkout's own files)",
      same(rel, base1) and home_cache.is_dir() and any(n.startswith("tree-") for n in os.listdir(home_cache)) and not (R / "relcache").exists() and not (R / "relxdg").exists(), (err[-200:], os.listdir(T / "home") if (T / "home").exists() else None))
check("CACHE 45 the folder the cache makes is private to its user (mode 0700)", (os.stat(cdir("hit")).st_mode & 0o777) == 0o700, oct(os.stat(cdir("hit")).st_mode & 0o777))

os.environ["SUITEMAP_CACHE_DIR"] = cdir("hit")
try:
    warm = s.Names(C1)
finally:
    os.environ.pop("SUITEMAP_CACHE_DIR")
sets = [v for m in warm.files.values() for v in m.refs.values()]
sets += [x for m in warm.files.values() for st in m.stmts for x in st[3:5]] + [m.dropped for m in warm.files.values()]
check("CACHE 46 an index read from its tree entry holds its key sets (the names a scope reads, a statement binds and reads, a file drops) as frozen sets, as a build makes them: nothing can change one in place",
      len(sets) > 20 and all(isinstance(v, frozenset) for v in sets), (len(sets), [type(v).__name__ for v in sets if not isinstance(v, frozenset)][:3]))

# ---------------------------------------------------------------- the bound, what the trim may touch, and what an entry may be
import resource, stat as statmod
def sizeof(folder, test=lambda n: True): return sum(os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder) if test(n) and os.path.isfile(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n)))
def with_dir(folder, fn):
    """fn() with SUITEMAP_CACHE_DIR set to folder in this process (and the bound as it is now)"""
    os.environ["SUITEMAP_CACHE_DIR"] = folder
    try: return fn()
    finally: os.environ.pop("SUITEMAP_CACHE_DIR")
# end to end: Names over a folder that is over its bound brings it back under it through its own save, trimming records AND tree entries, oldest use first
os.makedirs(T / "e2e-size")
with_dir(str(T / "e2e-size"), lambda: s.Names(C1))
real_size = sizeof(str(T / "e2e-size"))
bound = real_size + 3000
os.makedirs(T / "e2e")
pre = s.IndexCache(str(T / "e2e"), version=s.cache_version())
old_facts, old_trees = [f"{i:040x}" for i in range(100, 108)], [f"{i:040x}" for i in range(200, 208)]
for i, (kf, kt) in enumerate(zip(old_facts, old_trees)):
    pre.put("facts", kf, os.urandom(300).hex()); pre.put("tree", kt, os.urandom(300).hex())
    for kind, k in (("facts", kf), ("tree", kt)): os.utime(pre.path(kind, k), (now - 5000 + i, now - 5000 + i))
before_e2e = sizeof(str(T / "e2e"))
real_max, s.CACHE_MAX_BYTES = s.CACHE_MAX_BYTES, bound
try:
    with_dir(str(T / "e2e"), lambda: s.Names(C1))
finally:
    s.CACHE_MAX_BYTES = real_max
left_f, left_t = [k for k in old_facts if os.path.exists(pre.path("facts", k))], [k for k in old_trees if os.path.exists(pre.path("tree", k))]
check("CACHE 47 a run that saves an index into a folder over its bound brings the folder back under it (the save trims, in a real run), the records and the tree entries both, the entries used longest ago first",
      before_e2e + real_size > bound and sizeof(str(T / "e2e")) <= bound and len(left_f) < len(old_facts) and len(left_t) < len(old_trees) and os.path.exists(os.path.join(str(T / "e2e"), "tree-" + TREE[C1])),
      (before_e2e, real_size, bound, sizeof(str(T / "e2e")), left_f, left_t))
# a trim keeps what is not its own: names that only look like entries, a hidden file, a folder, and a link is itself removed while what it points at stays
fo2 = str(T / "foreign2"); os.makedirs(fo2); outside = T / "outside"; outside.mkdir(); (outside / "precious").write_text("p" * 5000); (outside / "dir").mkdir(); (outside / "dir" / "inner").write_text("i")
fx2 = s.IndexCache(fo2, version="v", max_bytes=3200)
keep = ["facts-zzzz", "facts-", "tree-" + "A" * 40, "facts-" + "0" * 39, "xfacts-" + "1" * 40, "tree-" + "2" * 40 + ".bak", ".hidden-keep", "other-" + "3" * 40]
for n in keep:
    open(os.path.join(fo2, n), "w").write("f" * 300); os.utime(os.path.join(fo2, n), (now - 9000, now - 9000))
os.makedirs(os.path.join(fo2, "facts-" + "4" * 40)); os.makedirs(os.path.join(fo2, "lock-adir"))
os.symlink(str(outside / "precious"), os.path.join(fo2, "facts-" + "5" * 40)); os.symlink(str(outside / "dir"), os.path.join(fo2, "tree-" + "6" * 40)); os.symlink(str(outside / "gone"), os.path.join(fo2, ".tmp-dangling"))
for n in ("facts-" + "5" * 40, "tree-" + "6" * 40, ".tmp-dangling"): os.utime(os.path.join(fo2, n), (now - 3 * 86400, now - 3 * 86400), follow_symlinks=False)
for i, k in enumerate(keys):
    fx2.put("facts", k, os.urandom(500).hex()); os.utime(fx2.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
fx2.trim()
check("CACHE 48 a trim over the bound keeps a file that only looks like an entry (non-hex, 39 digits, upper case, another suffix or prefix), a hidden file, a folder named like an entry or a lock, and its own entries are still brought under the bound",
      all(os.path.exists(os.path.join(fo2, n)) for n in keep + ["facts-" + "4" * 40, "lock-adir"]) and sizeof(fo2, lambda n: re.fullmatch(r"facts-[0-9a-f]{40}", n) is not None) <= 3200, sorted(os.listdir(fo2)))
check("CACHE 49 …and a link named like an entry (or a dead temporary link) is removed itself while its target, a file and a folder outside, stays whole",
      not os.path.lexists(os.path.join(fo2, "facts-" + "5" * 40)) and not os.path.lexists(os.path.join(fo2, "tree-" + "6" * 40)) and not os.path.lexists(os.path.join(fo2, ".tmp-dangling"))
      and (outside / "precious").read_text() == "p" * 5000 and (outside / "dir" / "inner").read_text() == "i", sorted(os.listdir(fo2)))
fo3 = str(T / "linksize"); os.makedirs(fo3)
fx3 = s.IndexCache(fo3, version="v", max_bytes=3200)
for i, k in enumerate(keys[:3]): fx3.put("facts", k, os.urandom(300).hex())
os.symlink(str(outside / "precious"), os.path.join(fo3, "tree-" + "7" * 40)); os.makedirs(os.path.join(fo3, "facts-" + "a" * 40))   # a big file behind a link, and a folder (4 kB on its own): neither counts
fx3.trim()
check("CACHE 50 a link named like an entry counts for itself and not for the file it points at, and a folder named like one counts for nothing: a folder of entries under its bound is not trimmed because of them", all(os.path.exists(fx3.path("facts", k)) for k in keys[:3]), sorted(os.listdir(fo3)))
fo4 = str(T / "target"); os.makedirs(fo4)
fx4 = s.IndexCache(fo4, version="v", max_bytes=3200)
for i, k in enumerate(keys):
    fx4.put("facts", k, os.urandom(500).hex()); os.utime(fx4.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
fx4.trim()
check("CACHE 51 a trim goes down to 80% of the bound and not only to it (so the next save does not trim again), and keeps the newest", 0 < sizeof(fo4) <= 0.8 * 3200 and os.path.exists(fx4.path("facts", keys[7])), (sizeof(fo4), sorted(os.listdir(fo4))))
# the leftovers: a temporary file of put is what the trim cleans, a day old; a lock file nobody holds goes, a held one stays
fo5 = str(T / "stale"); os.makedirs(fo5)
fx5 = s.IndexCache(fo5, version="v", max_bytes=10 ** 9)
made = []
real_mk = s.tempfile.mkstemp
def spy(*a, **k):
    fd, path = real_mk(*a, **k); made.append(os.path.basename(path)); return fd, path
s.tempfile.mkstemp = spy
try: fx5.put("facts", keys[0], {"n": 1})
finally: s.tempfile.mkstemp = real_mk
twin = os.path.join(fo5, made[0]); open(twin, "w").write("x"); os.utime(twin, (now - 3 * 86400, now - 3 * 86400))
hidden = os.path.join(fo5, ".not-ours"); open(hidden, "w").write("x"); os.utime(hidden, (now - 3 * 86400, now - 3 * 86400))
LK = ("tree-" + "a" * 40, "tree-" + "b" * 40, "facts-" + "c" * 40)   # the lock names a build is given (kind and id)
stale_lock, fresh_lock, held_lock = (os.path.join(fo5, "lock-" + n) for n in LK)
open(stale_lock, "w").close(); open(fresh_lock, "w").close()
held_fd = fx5.acquire(LK[2], 1)
for pth in (stale_lock, held_lock): os.utime(pth, (now - 3 * 86400, now - 3 * 86400))
fx5.trim()
kept_while_held = os.path.exists(held_lock)
os.close(held_fd); fx5.trim()
check("CACHE 52 a temporary file as put names it, a day old, is removed by the trim (put's name and the trim's go together), and a hidden file that is not put's stays",
      made and made[0].startswith(".tmp-") and not os.path.exists(twin) and os.path.exists(hidden), (made, sorted(os.listdir(fo5))))
check("CACHE 53 a lock file a day old that nobody holds is removed, a fresh one stays, and one that is held stays however old (and goes when let go)",
      not os.path.exists(stale_lock) and os.path.exists(fresh_lock) and kept_while_held and not os.path.exists(held_lock), (os.path.exists(stale_lock), os.path.exists(fresh_lock), kept_while_held, os.path.exists(held_lock)))
# acquire: a lock file taken away and made again between our open and our lock is not ours; no descriptor is left behind; a link is not followed
lk = s.IndexCache(str(T / "lockrace"), version="v"); os.makedirs(lk.dir)
lock_path = os.path.join(lk.dir, "lock-r"); state = {"n": 0}; real_flock = s.fcntl.flock
def racing(fd, op):
    state["n"] += 1
    if state["n"] == 1: os.unlink(lock_path); open(lock_path, "w").close()
    return real_flock(fd, op)
s.fcntl.flock = racing
try: got = lk.acquire("r", 2)
finally: s.fcntl.flock = real_flock
same_file = got is not None and os.fstat(got).st_ino == os.stat(lock_path).st_ino
if got is not None: os.close(got)
check("CACHE 54 a lock file replaced by another between our open and our flock is not taken: the lock is the file that is there now (a second try)", same_file and state["n"] == 2, (got, state))
import gc
def fds(): gc.collect(); return len(os.listdir("/proc/self/fd"))
fds0 = fds(); hold = lk.acquire("h", 1)
for _ in range(20): lk.acquire("h", 0)   # held by us on another descriptor: not obtained, and nothing left open
def err_lock(fd, op): raise OSError(errno.ENOLCK, "no locks")
s.fcntl.flock = err_lock
try:
    for _ in range(20): lk.acquire("e", 3)
finally: s.fcntl.flock = real_flock
os.close(hold)
check("CACHE 55 a lock that is held, or fails with an error, leaves no descriptor open (twenty tries each)", fds() <= fds0, (fds0, fds()))
errs = []
for code in (errno.ENOLCK, errno.EACCES, errno.EOPNOTSUPP, errno.EIO):
    def fail_with(fd, op, code=code): raise OSError(code, "x")
    s.fcntl.flock = fail_with
    t0 = time.monotonic()
    try: got = lk.acquire("e", 3)
    finally: s.fcntl.flock = real_flock
    errs.append((code, got, time.monotonic() - t0))
check("CACHE 56 whatever error the lock fails with (ENOLCK, EACCES, EOPNOTSUPP, EIO) it is no holder: no lock and no wait", all(g is None and t < 1.5 for _, g, t in errs), errs)
dang = os.path.join(lk.dir, "lock-dangling"); os.symlink(str(outside / "made-by-lock"), dang)
check("CACHE 57 a lock file that is a link is not followed (a dead link would make a file outside the folder): no lock, nothing made", lk.acquire("dangling", 1) is None and not (outside / "made-by-lock").exists(), os.listdir(str(outside)))
# an entry is a regular file of a sane size that inflates to a sane size: a link to /dev/zero, a pipe, a bomb is no entry and costs nothing
gd2 = str(T / "planted"); os.makedirs(gd2)
os.symlink("/dev/zero", os.path.join(gd2, "facts-" + "8" * 40)); os.mkfifo(os.path.join(gd2, "facts-" + "9" * 40))
CHILD_PLANT = ("import sys, os, resource; sys.path.insert(0, os.environ['SCENARIO_TESTS']); import suitemap as s; resource.setrlimit(resource.RLIMIT_AS, (1500 << 20, 1500 << 20)); "
               "c = s.IndexCache(sys.argv[1], version='v'); print([c.get('facts', k) for k in ('8' * 40, '9' * 40)])")
try:
    pr = subprocess.run([sys.executable, "-c", CHILD_PLANT, gd2], capture_output=True, text=True, env={**ENV, "SUITEMAP_CACHE": "1"}, timeout=60)
    plant = (pr.returncode, pr.stdout.strip(), pr.stderr[-200:])
except subprocess.TimeoutExpired:
    plant = ("timeout",)
check("CACHE 58 a link to /dev/zero and a pipe named like entries are no entries: no read of them (a memory limit holds), no wait, no failure", plant[:2] == (0, "[None, None]"), plant)
cl = s.IndexCache(str(T / "linked"), version="v"); os.makedirs(cl.dir); cl.put("facts", K, {"n": 7})
os.rename(cl.path("facts", K), os.path.join(cl.dir, "elsewhere")); os.symlink(os.path.join(cl.dir, "elsewhere"), cl.path("facts", K))
check("CACHE 59 a link named like an entry is no entry even when it leads to a good one (an entry is a file of the folder, not what a link says)", cl.get("facts", K) is None, cl.get("facts", K))
real_cap = s.CACHE_ENTRY_MAX
bd = str(T / "bomb"); os.makedirs(bd); cb = s.IndexCache(bd, version="v")
try:
    s.CACHE_ENTRY_MAX = 1 << 20
    cb.put("facts", K, "0" * (4 << 20)); cb.put("tree", K, os.urandom(2 << 20))
    got_inflate, got_file = cb.get("facts", K), cb.get("tree", K)
    s.CACHE_ENTRY_MAX = real_cap
    ok_after = cb.get("facts", K) is None   # it was removed as no entry
    cb.put("facts", K, "0" * (4 << 20)); fine = cb.get("facts", K) == "0" * (4 << 20)
finally:
    s.CACHE_ENTRY_MAX = real_cap
check("CACHE 60 an entry that inflates to more than an entry may be (a bomb) and one that is a file bigger than that are no entries, and one within the bound is read", got_inflate is None and got_file is None and ok_after and fine, (got_inflate is None, got_file is None, ok_after, fine))
# the folder: made private; an existing one of the default place made private too (if ours), one the user named is left; no home is no cache; a read-only one is no cache
mx = T / "xdgmode"; (mx / "stackshot" / "suitemap").mkdir(parents=True); (mx / "stackshot" / "suitemap").chmod(0o755)
nm = T / "named755"; nm.mkdir(); nm.chmod(0o755)
real_env = dict(os.environ)
try:
    os.environ.pop("SUITEMAP_CACHE_DIR", None); os.environ["XDG_CACHE_HOME"] = str(mx); c_default = s.IndexCache.open()
    os.environ["SUITEMAP_CACHE_DIR"] = str(nm); c_named = s.IndexCache.open()
finally:
    os.environ.clear(); os.environ.update(real_env)
check("CACHE 61 a cache folder of the default place that exists with a wider mode is made private (0700), one the user named is left as it is",
      c_default is not None and (os.stat(mx / "stackshot" / "suitemap").st_mode & 0o777) == 0o700 and c_named is not None and (os.stat(nm).st_mode & 0o777) == 0o755, (oct(os.stat(mx / "stackshot" / "suitemap").st_mode & 0o777), oct(os.stat(nm).st_mode & 0o777)))
nohome = T / "nohome"; nohome.mkdir(); here = os.getcwd(); real_eu = s.os.path.expanduser
try:
    os.chdir(nohome); os.environ.pop("SUITEMAP_CACHE_DIR", None); os.environ.pop("XDG_CACHE_HOME", None)
    s.os.path.expanduser = lambda p: p   # no home directory found: "~" stays "~"
    c_nohome = s.IndexCache.open()
finally:
    s.os.path.expanduser = real_eu; os.chdir(here); os.environ.clear(); os.environ.update(real_env)
check("CACHE 62 with no home directory found the cache is off (not a folder named ~ in the directory the call runs in)", c_nohome is None and os.listdir(str(nohome)) == [], (c_nohome, os.listdir(str(nohome))))
rod = T / "readonly2"; rod.mkdir(); roc = s.IndexCache(str(rod), version="v"); roc.put("facts", K, {"n": 1}); rod.chmod(0o500)
try: c_ro = with_dir(str(rod), s.IndexCache.open)
finally: rod.chmod(0o700)
check("CACHE 63 a folder that is readable and not writable (a restored cache, a read-only mount) is no cache at all, its entries are not served", c_ro is None or os.geteuid() == 0, c_ro)

# ---------------------------------------------------------------- nothing is kept from a call in which git failed
real_git, real_run = s.git, s.subprocess.run
UTIL = git("rev-parse", f"{C1}:pkg/util.py").strip(); TOOL = git("rev-parse", f"{C1}:bin/tool").strip()
def names_with(folder, git_fn=None, run_fn=None, rev=C1):
    """s.Names(rev) in this process over the folder, with git (s.git) or the processes it starts (s.subprocess.run) replaced; the real ones are back after"""
    s.git, s.subprocess.run = git_fn or real_git, run_fn or real_run
    try: return with_dir(folder, lambda: s.Names(rev))
    finally: s.git, s.subprocess.run = real_git, real_run
def kept(folder, kind): return sorted(e for e in os.listdir(folder) if e.startswith(kind + "-")) if os.path.isdir(folder) else []
def batch_answer(wanted, change):
    """a stand-in for subprocess.run: a `git cat-file --batch` that asks for the blob `wanted` (None: any) is answered by change(ids, stdout) -> (stdout, returncode); the rest runs for real"""
    seen = []
    def run(cmd, *a, **k):
        r = real_run(cmd, *a, **k)
        if isinstance(cmd, list) and "cat-file" in cmd and "--batch" in cmd and (wanted is None or wanted in k["input"].decode().split()):
            ids = k["input"].decode().split(); out, rc = change(ids, r.stdout); seen.append(ids)
            return subprocess.CompletedProcess(cmd, rc, out, r.stderr)
        return r
    run.seen = seen
    return run
def parse_answer(ids, data):
    """[(header, body or None)] of a batch answer, in the order of the ids asked for"""
    rows, i = [], 0
    for _ in ids:
        nl = data.index(b"\n", i); head = data[i:nl]; i = nl + 1
        if head.split()[1:2] == [b"blob"]: n = int(head.split()[2]); rows.append((head, data[i:i + n])); i += n + 1
        else: rows.append((head, None))
    return rows
def build_answer(rows): return b"".join(h + b"\n" + (b + b"\n" if b is not None else b"") for h, b in rows)
def damaged(name, run):
    d_ = str(T / ("gitfail-" + name)); os.makedirs(d_)
    return d_, names_with(d_, run_fn=run)

full_dir = str(T / "gitfail-full"); os.makedirs(full_dir)
full_names = names_with(full_dir)
full_files, full_facts = sorted(full_names.files), kept(full_dir, "facts")
d64 = str(T / "gitfail-ls"); os.makedirs(d64)
bad64 = names_with(d64, git_fn=lambda *a, **k: None if a and a[0] == "ls-tree" else real_git(*a, **k))
none_kept = not kept(d64, "tree")
good64 = names_with(d64)
check("CACHE 64 a call whose git listing of the revision fails has an index, as before (nothing is in it), and keeps nothing of it: no tree entry; the next call, with git well, builds the full index and keeps it",
      not bad64.files and none_kept and sorted(good64.files) == full_files and kept(d64, "tree") == ["tree-" + TREE[C1]], (len(bad64.files), none_kept, len(good64.files), kept(d64, "tree")))
check("CACHE 65 a complete build keeps its index under the tree id", kept(full_dir, "tree") == ["tree-" + TREE[C1]] and len(full_files) > 10, (kept(full_dir, "tree"), len(full_files)))
asked = []
names_with(full_dir, git_fn=lambda *a, **k: (asked.append(a[0]), real_git(*a, **k))[1])
check("CACHE 66 …and a second call reads it: git is asked for the tree id and not for the listing", "ls-tree" not in asked and "rev-parse" in asked, asked)

def drop_blob(target):
    def change(ids, data):
        rows = parse_answer(ids, data)
        return build_answer([((f"{i} missing".encode(), None) if i == target else row) for i, row in zip(ids, rows)]), 0
    return change
d, n = damaged("missing", batch_answer(UTIL, drop_blob(UTIL)))
check("CACHE 67 a .py blob git cannot give: the call has the index without that file (as before), and keeps no tree entry and no record of it (the records of the others are kept)",
      "pkg/util.py" not in n.files and "pkg/core.py" in n.files and not kept(d, "tree") and "facts-" + UTIL not in kept(d, "facts") and len(kept(d, "facts")) == len(full_facts) - 1,
      (kept(d, "tree"), len(kept(d, "facts")), len(full_facts)))
good67 = names_with(d)
check("CACHE 68 …and the next call, with git well, builds the file's record and the full index and keeps them", sorted(good67.files) == full_files and kept(d, "tree") == ["tree-" + TREE[C1]] and "facts-" + UTIL in kept(d, "facts"), (kept(d, "tree"), len(kept(d, "facts"))))
def cut_last(ids, data):   # git ended in the middle of the last blob
    rows = parse_answer(ids, data); h, b = rows[-1]
    return build_answer(rows[:-1]) + h + b"\n" + b[: len(b) // 2], 0
run_cut = batch_answer(None, cut_last)
d, n = damaged("cut", run_cut); last = run_cut.seen[0][-1]
check("CACHE 69 an answer of git cut short in the last blob: the call has its index, and keeps no tree entry and no record of the cut blob", not kept(d, "tree") and "facts-" + last not in kept(d, "facts") and len(kept(d, "facts")) < len(full_facts), (last, kept(d, "tree"), len(kept(d, "facts"))))
def other_bytes(ids, data):   # another text of the same length under UTIL's id (what a replacement ref does)
    return build_answer([((h, b"#" * len(b)) if i == UTIL else (h, b)) for i, (h, b) in zip(ids, parse_answer(ids, data))]), 0
d, n = damaged("replaced", batch_answer(UTIL, other_bytes))
check("CACHE 70 a blob whose bytes are not the object its id names (another object stands in for it): the call serves what git gave, and keeps no tree entry and no record of it",
      "pkg/util.py" in n.files and not kept(d, "tree") and "facts-" + UTIL not in kept(d, "facts") and len(kept(d, "facts")) == len(full_facts) - 1, (kept(d, "tree"), len(kept(d, "facts"))))
d, n = damaged("rc", batch_answer(None, lambda ids, data: (data, 1)))
check("CACHE 71 a git that ends with an error, whatever it printed before, makes the call's records and index its own: nothing is kept", not kept(d, "tree") and not kept(d, "facts"), (kept(d, "tree"), len(kept(d, "facts"))))
d, n = damaged("script", batch_answer(TOOL, drop_blob(TOOL)))
check("CACHE 72 a script blob git cannot give: no tree entry (the index the call has is built as before)", not kept(d, "tree") and "pkg/core.py" in n.files, (kept(d, "tree"), len(n.files)))
def grep_fails(cmd, *a, **k):
    if isinstance(cmd, list) and "grep" in cmd: return subprocess.CompletedProcess(cmd, 2, "", "fatal: bad")
    return real_run(cmd, *a, **k)
d, n = damaged("grep", grep_fails)
good73 = names_with(d)
check("CACHE 73 a search for the scripts that fails makes the index blind for this call and keeps no tree entry (a blind index is no answer for the tree: the next call, with git well, is not blind and keeps its index)",
      n.blind is True and good73.blind is False and kept(d, "tree") == ["tree-" + TREE[C1]], (n.blind, good73.blind, kept(d, "tree")))

def ghost_script(cmd, *a, **k):   # the search names a file the listing does not have, whose blob git cannot give either
    r = real_run(cmd, *a, **k)
    if isinstance(cmd, list) and "grep" in cmd: return subprocess.CompletedProcess(cmd, r.returncode, r.stdout + f"{TREE[C1]}:bin/ghost\n", r.stderr)
    return r
d, n = damaged("ghost", ghost_script)
check("CACHE 74 a script the search names and git cannot give the blob of: no tree entry (the index the call has is built as before)", not kept(d, "tree") and "pkg/core.py" in n.files and n.blind is False, (kept(d, "tree"), n.blind))

# the cheap ones: what a trim removes, a read that follows nothing, the folder of a link, a short memory, a failed removal, the modes
fo7 = str(T / "foreign3"); os.makedirs(fo7); fx7 = s.IndexCache(fo7, version="v", max_bytes=10 ** 9)
LOCKH, TMPH = "lock-tree-" + "d" * 40, ".tmp-abcd1234"
lnk_live, lnk_dead = "lock-facts-" + "e" * 40, "lock-tree-" + "f" * 40
names7 = ["lock-notes", ".tmp-notes", LOCKH + ".bak", "lock-tree-" + "1" * 39, "lock-tree-" + "1" * 65, "lock-tree-" + "g" * 40, ".tmp-abcdefghi", ".tmp-abcdefg", "lock-other-" + "1" * 40, "lock-"]
for nm_ in names7 + [TMPH, LOCKH]: open(os.path.join(fo7, nm_), "w").write("mine"); os.utime(os.path.join(fo7, nm_), (now - 3 * 86400, now - 3 * 86400))
os.symlink(str(outside / "precious"), os.path.join(fo7, lnk_live)); os.symlink(str(outside / "gone2"), os.path.join(fo7, lnk_dead))
for nm_ in (lnk_live, lnk_dead): os.utime(os.path.join(fo7, nm_), (now - 3 * 86400, now - 3 * 86400), follow_symlinks=False)
fx7.trim()
check("CACHE 75 a trim removes the stale files of the cache by the names the cache gives them, and no other: a lock- or .tmp- file of someone else a day old (lock-notes, .tmp-notes, a name a character short or long, with a suffix or of another kind) stays, while put's temporary name and a lock name as acquire is given go",
      all(os.path.exists(os.path.join(fo7, nm_)) for nm_ in names7) and not os.path.exists(os.path.join(fo7, TMPH)) and not os.path.exists(os.path.join(fo7, LOCKH)), sorted(os.listdir(fo7)))
check("CACHE 76 …and a link named like a lock file, a day old, live or dead, is removed itself (the file it leads to stays whole, and nothing is made where the dead one led)",
      not os.path.lexists(os.path.join(fo7, lnk_live)) and not os.path.lexists(os.path.join(fo7, lnk_dead)) and (outside / "precious").read_text() == "p" * 5000 and not (outside / "gone2").exists(), sorted(os.listdir(fo7)))

os.utime(outside / "precious", (1000, 1000))
fo8 = str(T / "utime"); os.makedirs(fo8); c8 = s.IndexCache(fo8, version="v"); c8.put("facts", K, {"n": 1})
real_utime = os.utime
def swap_then_touch(path, *a, **k):   # the entry is taken away and a link to a file outside put in its place, between the read and the touch
    os.rename(path, path + ".moved"); os.symlink(str(outside / "precious"), path)
    return real_utime(path, *a, **k)
os.utime = swap_then_touch
try: got8 = c8.get("facts", K)
finally: os.utime = real_utime
check("CACHE 77 the touch that says an entry was used is made on the entry and never through a link put in its place meanwhile: the file the link leads to keeps its time", got8 == {"n": 1} and int(os.stat(outside / "precious").st_mtime) == 1000, (got8, os.stat(outside / "precious").st_mtime))

# a call short of memory (an address-space limit): a small entry is read without a buffer the size an entry may have, and a memory error is a miss that leaves the entry
CHILD_MEM = ("import sys, os, resource; sys.path.insert(0, os.environ['SCENARIO_TESTS']); import suitemap as s; c = s.IndexCache(sys.argv[1], version='v'); c.put('facts', '5' * 40, {'n': 1}); "
             "vm = int([l for l in open('/proc/self/status') if l.startswith('VmSize')][0].split()[1]) << 10; resource.setrlimit(resource.RLIMIT_AS, (vm + (64 << 20), vm + (64 << 20))); print(c.get('facts', '5' * 40))")
gd8 = str(T / "mem"); os.makedirs(gd8)
pr8 = subprocess.run([sys.executable, "-c", CHILD_MEM, gd8], capture_output=True, text=True, env={**ENV, "SUITEMAP_CACHE": "1"}, timeout=60)
check("CACHE 78 a small valid entry is read by a call that has only 64 MB of address space to spare (no buffer of the size an entry may have is made for it)", pr8.returncode == 0 and pr8.stdout.strip() == "{'n': 1}", (pr8.returncode, pr8.stdout, pr8.stderr[-300:]))
c9 = s.IndexCache(str(T / "oom"), version="v"); os.makedirs(c9.dir); c9.put("facts", K, {"n": 1}); real_fd, real_dco = os.fdopen, s.zlib.decompressobj
def oom(*a, **k): raise MemoryError()
os.fdopen = oom
try: m1 = c9.get("facts", K)
finally: os.fdopen = real_fd
s.zlib.decompressobj = oom
try: m2 = c9.get("facts", K)
finally: s.zlib.decompressobj = real_dco
check("CACHE 79 a memory error while an entry is read, or inflated, is a miss and not an error, and it does not make the entry a damaged one: it is still there and reads when memory is", m1 is None and m2 is None and c9.get("facts", K) == {"n": 1}, (m1, m2))

lk_real = T / "xdglink-real"; lk_real.mkdir(); lk_real.chmod(0o755); lk_home = T / "xdglink"; (lk_home / "stackshot").mkdir(parents=True); os.symlink(str(lk_real), str(lk_home / "stackshot" / "suitemap"))
try:
    os.environ.pop("SUITEMAP_CACHE_DIR", None); os.environ["XDG_CACHE_HOME"] = str(lk_home); c_link = s.IndexCache.open()
finally:
    os.environ.clear(); os.environ.update(real_env)
check("CACHE 80 a default folder that is a link to another folder is used, and the folder it leads to is left as it is (not made 0700)", c_link is not None and (os.stat(lk_real).st_mode & 0o777) == 0o755, (c_link, oct(os.stat(lk_real).st_mode & 0o777)))
ow = T / "xdgother"; (ow / "stackshot" / "suitemap").mkdir(parents=True); (ow / "stackshot" / "suitemap").chmod(0o755); real_uid = os.getuid
try:
    os.environ.pop("SUITEMAP_CACHE_DIR", None); os.environ["XDG_CACHE_HOME"] = str(ow); os.getuid = lambda: real_uid() + 1; c_other = s.IndexCache.open()
finally:
    os.getuid = real_uid; os.environ.clear(); os.environ.update(real_env)
check("CACHE 81 a default folder that belongs to another user is not changed (the user whose it is makes it private) and is used as it is", c_other is not None and (os.stat(ow / "stackshot" / "suitemap").st_mode & 0o777) == 0o755, (c_other, oct(os.stat(ow / "stackshot" / "suitemap").st_mode & 0o777)))

# an entry that cannot be removed (another user's file in a shared folder) stops counting: the trim does not remove the user's own entries to make up for it
datas = [os.urandom(500).hex() for _ in keys]
def made_folder(name):
    d_ = str(T / name); os.makedirs(d_); fx_ = s.IndexCache(d_, version="v", max_bytes=3200)
    for i, (k, dt) in enumerate(zip(keys, datas)): fx_.put("facts", k, dt); os.utime(fx_.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
    return d_, fx_
d_ok, fx_ok = made_folder("unl-ok"); fx_ok.trim(); alive_ok = {k for k in keys if os.path.exists(fx_ok.path("facts", k))}
d_nu, fx_nu = made_folder("unl-fail"); real_unlink = os.unlink; stuck = fx_nu.path("facts", keys[0])
def refuse(pth, *a, **k):
    if os.fspath(pth) == stuck: raise PermissionError(errno.EPERM, "not yours")
    return real_unlink(pth, *a, **k)
os.unlink = refuse
try: fx_nu.trim()
finally: os.unlink = real_unlink
alive_nu = {k for k in keys if os.path.exists(fx_nu.path("facts", k))}
check("CACHE 82 an entry that cannot be removed stops counting toward the bound: the trim removes as many of the others as it would with that one gone, and not one more",
      0 < len(alive_ok) < len(keys) - 1 and alive_nu == alive_ok | {keys[0]}, (sorted(alive_ok), sorted(alive_nu)))

# the modes: a lock file and an entry are the user's alone, whatever the umask
old_um = os.umask(0)
try:
    md = s.IndexCache(str(T / "modes"), version="v"); os.makedirs(md.dir); mfd = md.acquire("tree-" + "a" * 40, 1); md.put("facts", K, {"n": 1})
    lock_mode, entry_mode = os.fstat(mfd).st_mode & 0o777, os.stat(md.path("facts", K)).st_mode & 0o777
    os.close(mfd)
finally: os.umask(old_um)
check("CACHE 83 a lock file and an entry are readable and writable by their user alone (0600), with a umask that would let anyone", lock_mode == 0o600 and entry_mode == 0o600, (oct(lock_mode), oct(entry_mode)))

util_bytes = subprocess.run(["git", "-C", str(R), "cat-file", "blob", UTIL], capture_output=True).stdout
obj = b"blob %d\0" % len(util_bytes) + util_bytes
r256 = T / "sha256repo"; r256.mkdir()
mk = subprocess.run(["git", "-C", str(r256), "init", "-q", "--object-format=sha256"], capture_output=True)
id256 = subprocess.run(["git", "-C", str(r256), "hash-object", "--stdin"], input=util_bytes, capture_output=True).stdout.decode().strip() if mk.returncode == 0 else None
check("CACHE 84 an object id is checked against the bytes it names, whatever the repo hashes with (sha1 or sha256: the length of the id says), and an id of another length, or other bytes, is no match",
      s.is_object(UTIL, obj) and not s.is_object(UTIL, obj + b"x") and not s.is_object("0" * 40, obj) and not s.is_object(UTIL[:39], obj) and (id256 is None or (len(id256) == 64 and s.is_object(id256, obj) and not s.is_object(id256, obj + b"x"))),
      (UTIL, id256))

# ---------------------------------------------------------------- the index is built from the tree it is kept under
MOVING, T1 = "moving", TREE[C1]
used = []
def moving_git(*a, **k):   # a ref that answers tree T1 when asked for its tree, and gives the content of another commit (C3) to every call that names it
    used.append(a)
    if a[:3] == ("rev-parse", "--verify", "--quiet") and a[3].startswith(MOVING): return T1 + "\n"
    return real_git(*[x.replace(MOVING, C3) for x in a], **k)
def moving_run(cmd, *a, **k): return real_run([C3 if x == MOVING else x for x in cmd] if isinstance(cmd, list) else cmd, *a, **k)
d85 = str(T / "moving"); os.makedirs(d85)
n85 = names_with(d85, git_fn=moving_git, run_fn=moving_run, rev=MOVING)
e85 = s.IndexCache(d85, version=s.cache_version()).get("tree", T1)
by_name = [a for a in used if any(MOVING in x for x in a) and a[:3] != ("rev-parse", "--verify", "--quiet")]
check("CACHE 85 a revision that is a moving ref (it answers tree T1 and gives the content of another commit to a call that names it) is built from T1: the entry under T1 holds T1's files, no git call names the ref after its tree is known",
      sorted(n85.files) == full_files and e85 is not None and sorted(e85["files"]) == full_files and "c/m.py" not in e85["files"] and not by_name, (sorted(n85.files)[-3:], e85 and sorted(e85["files"])[-3:], by_name[:3]))
d86 = str(T / "notree"); os.makedirs(d86)
n86 = names_with(d86, git_fn=lambda *a, **k: None if a[:3] == ("rev-parse", "--verify", "--quiet") else real_git(*a, **k))
check("CACHE 86 a revision with no tree id is built as it is given and kept nowhere (no tree entry), and has the index it had", sorted(n86.files) == full_files and not kept(d86, "tree"), (len(n86.files), kept(d86, "tree")))

# a volatile file (its text is read again, for its path and the repo): read with the same checks as a blob of any index
VOLB = git("rev-parse", f"{C1}:vol.py").strip()
d87 = str(T / "vol-replace"); os.makedirs(d87)
names_with(d87)
c87 = s.IndexCache(d87, version=s.cache_version()); good87 = c87.get("tree", T1)
os.unlink(c87.path("tree", T1))   # the records stay: the volatile file's record is a hit, so no batch of the call asks for its text first
other = subprocess.run(["git", "-C", str(R), "hash-object", "-w", "--stdin"], input=b"def g():\n    return 2\n", capture_output=True).stdout.decode().strip()
git("replace", VOLB, other)
try: n87 = names_with(d87)
finally: git("replace", "-d", VOLB)
left87 = kept(d87, "tree")
names_with(d87); again87 = c87.get("tree", T1)
check("CACHE 87 a volatile file whose blob a replacement ref stands in for (its record cached) is served to the call and keeps no tree entry; the next call, without the ref, keeps the entry a good build makes",
      "vol.py" in n87.files and not left87 and good87 is not None and again87 == good87, (left87, again87 == good87))

# an answer of git that stops before a header is not an exception: the blobs from there on are left out, and nothing of the call is kept
d, n = damaged("empty-batch", batch_answer(None, lambda ids, data: (b"", 0)))
check("CACHE 88 a git that answers nothing to a batch of blobs: the call still has an index (without the files of that batch), no tree entry and no record", not kept(d, "tree") and not kept(d, "facts") and "pkg/core.py" not in n.files, (kept(d, "tree"), len(kept(d, "facts"))))
def cut_in_header(ids, data): return build_answer(parse_answer(ids, data)[:-1]) + b"deadbeef ", 0   # the last header is cut, before its end of line
run_hdr = batch_answer(UTIL, cut_in_header)
d, n = damaged("cut-header", run_hdr); last_h = run_hdr.seen[0][-1]
check("CACHE 89 an answer cut in the last header: the blobs before it are served and kept, the last one is left out (no record), and no tree entry is kept", not kept(d, "tree") and "facts-" + last_h not in kept(d, "facts") and len(kept(d, "facts")) == len(full_facts) - 1, (kept(d, "tree"), len(kept(d, "facts")), len(full_facts)))

# an empty listing, a failure in the first of several batches, a tree with no script, a blob that is not UTF-8
d = str(T / "gitfail-emptyls"); os.makedirs(d)
n = names_with(d, git_fn=lambda *a, **k: "" if a and a[0] == "ls-tree" else real_git(*a, **k))
check("CACHE 90 a revision git lists with no row at all has an empty index for the call and keeps no tree entry (nothing tells it from a failure that printed nothing)", not n.files and not kept(d, "tree"), (len(n.files), kept(d, "tree")))
py_rows = [(f, b) for f, t, b in s.listing(C1) if f.endswith(".py") and t == "blob"]
first_unique = next(b for f, b in py_rows if [x for _, x in py_rows].count(b) == 1)
real_batch, s.FACTS_BATCH = s.FACTS_BATCH, 2
try: d, n = damaged("chunk1", batch_answer(first_unique, drop_blob(first_unique)))
finally: s.FACTS_BATCH = real_batch
check("CACHE 91 a failure in the first of several batches of blobs is not forgotten by the next ones: the call has its index and keeps no tree entry", len(py_rows) > 4 and not kept(d, "tree") and len(n.files) == len(full_files) - 1, (len(py_rows), kept(d, "tree"), len(n.files)))
d, n = damaged("noscript", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1, "", "") if isinstance(cmd, list) and "grep" in cmd else real_run(cmd, *a, **k))
check("CACHE 92 a search for scripts that finds none (git grep ends with 1: no match) is no failure: the index is complete and kept", kept(d, "tree") == ["tree-" + T1] and n.blind is False, (kept(d, "tree"), n.blind))
odd = {"latin1": b"x = '\xe9'\n", "bad utf-8": b"y = 1\n# \xff\xfe\n", "crlf": b"z = 1\r\nw = 2\r\n", "nul": b"v = 1\n\0\n"}
odd_ids = {k: subprocess.run(["git", "-C", str(R), "hash-object", "-w", "--stdin"], input=v, capture_output=True).stdout.decode().strip() for k, v in odd.items()}
uns = set(); got_odd = s.blob_texts(list(odd_ids.values()), uns)
check("CACHE 93 a blob that is not UTF-8 text (latin-1, invalid bytes, CRLF, a NUL) is hashed as the bytes git gave and is sure: it is read and kept like any other", set(got_odd) == set(odd_ids.values()) and not uns, (sorted(uns), len(got_odd)))

# the trim: an entry another user's in a sticky folder is not counted, in whatever order the entries are
SX = lambda mode, uid: os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0))
STICKY, PLAIN = SX(0o41777, 7), SX(0o40755, 7)
can = getattr(s.IndexCache, "can_remove", None)
truth = can and [can(SX(0o100600, 1000), STICKY, 1000), can(SX(0o100600, 5), SX(0o41777, 1000), 1000), can(SX(0o100600, 5), STICKY, 0), can(SX(0o100600, 5), STICKY, 1000), can(SX(0o100600, 5), PLAIN, 1000)]
check("CACHE 94 in a sticky folder a file goes for the user whose it is, the user whose the folder is and root, and not for another; in a folder that is not sticky it goes for any user", truth == [True, True, True, False, True], truth)
def folder_of(name, ks, bound):
    d_ = str(T / name); os.makedirs(d_); fx_ = s.IndexCache(d_, version="v", max_bytes=bound)
    for i, (k, dt) in enumerate(zip(ks, datas)): fx_.put("facts", k, dt); os.utime(fx_.path("facts", k), (now - 1000 + i * 10, now - 1000 + i * 10))
    return d_, fx_
one = os.path.getsize(fx_ok.path("facts", keys[7])); bound94 = int(one * 5.5)
d_ref, fx_ref = folder_of("stuck-ref", keys[:7], bound94); fx_ref.trim(); alive_ref = {k for k in keys[:7] if os.path.exists(fx_ref.path("facts", k))}
d_st, fx_st = folder_of("stuck-new", keys, bound94)
newest_m = now - 1000 + 70; real_can = can
if can: s.IndexCache.can_remove = staticmethod(lambda st, folder, uid: abs(st.st_mtime - newest_m) > 0.01)
try: fx_st.trim()
finally:
    if real_can: s.IndexCache.can_remove = staticmethod(real_can)
alive_st = {k for k in keys if os.path.exists(fx_st.path("facts", k))}
check("CACHE 95 an entry the user cannot remove that is the newest of the folder is not counted either: the trim removes as many of the others as it would with that entry not there, and no more",
      0 < len(alive_ref) < 7 and alive_st == alive_ref | {keys[7]}, (sorted(alive_ref), sorted(alive_st)))

# a volatile file whose blob git cannot give (its record cached): left out, as any file whose blob is missing, and nothing of the call is kept
d97 = str(T / "vol-missing"); os.makedirs(d97)
names_with(d97)
os.unlink(s.IndexCache(d97, version=s.cache_version()).path("tree", T1))
d, n = d97, names_with(d97, run_fn=batch_answer(VOLB, drop_blob(VOLB)))
check("CACHE 96 a volatile file whose blob git cannot give is left out of the call's index, which is served as before, and keeps no tree entry (the other files are built as they are)", "vol.py" not in n.files and "pkg/core.py" in n.files and not kept(d, "tree"), (sorted(n.files)[-3:], kept(d, "tree")))

# ---------------------------------------------------------------- warm: the index of a revision built and kept ahead of the first select (what runs after a merge to main)
import argparse, contextlib, io
def warm_cli(rev, name, env=None, timeout=90):
    """`suitemap.py warm --rev <rev>` in a process of its own, with the cache folder of `name`"""
    e = dict(ENV); e["SUITEMAP_CACHE_DIR"] = cdir(name); e.update(env or {})
    return subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), "warm", "--rev", rev], capture_output=True, text=True, env=e, cwd=str(R), timeout=timeout)
def tree_bytes(name, tree): return pathlib.Path(cdir(name), "tree-" + tree).read_bytes() if os.path.exists(os.path.join(cdir(name), "tree-" + tree)) else None

w1 = warm_cli(C1, "warm1")
check("CACHE 97 warm on an empty folder builds the index of the revision and keeps it: exit 0, it says saved, the tree entry and a record of each file are in the folder",
      w1.returncode == 0 and "tree " + TREE[C1][:12] + " saved" in w1.stdout and entries("warm1", "tree-") == ["tree-" + TREE[C1]] and len(entries("warm1", "facts-")) == len(full_facts), (w1.returncode, w1.stdout, w1.stderr[-300:], entries("warm1")))
d97b, e97b = dump(C1, "warm1", patch=COUNT)
check("CACHE 98 the first select-style read of that revision after a warm builds nothing and parses nothing (the index is loaded) and is the index a build with no cache gives", same(d97b, base1) and d97b["built"] == 0 and d97b["builds"] == 0, (d97b and (d97b["built"], d97b["builds"]), e97b[-300:]))
before = (entries("warm1"), tree_bytes("warm1", TREE[C1]))
w2 = warm_cli(C1, "warm1")
check("CACHE 99 warm of a revision that is kept already is a no-op: exit 0, it says so, and the folder (the tree entry's bytes included) is as it was", w2.returncode == 0 and "was kept already" in w2.stdout and (entries("warm1"), tree_bytes("warm1", TREE[C1])) == before, (w2.returncode, w2.stdout, w2.stderr[-300:]))
w3 = warm_cli(C1, "warm-off", env={"SUITEMAP_CACHE": "0"})
check("CACHE 100 warm with the cache switched off is a no-op that is not an error: exit 0, it says there is nothing to do, and no folder is made", w3.returncode == 0 and "nothing to do" in w3.stdout and not os.path.exists(cdir("warm-off")), (w3.returncode, w3.stdout, os.path.exists(cdir("warm-off"))))
w4 = warm_cli("no-such-revision", "warm-none")
check("CACHE 101 warm of a revision this checkout does not have: exit 1, one line says so, nothing is kept", w4.returncode == 1 and "not a revision of this checkout" in w4.stderr and not entries("warm-none"), (w4.returncode, w4.stderr[-300:], entries("warm-none")))

def run_warm(folder, rev=C1, run_fn=None, git_fn=None):
    """s.warm in this process over the folder, with git or the processes it starts replaced: (exit status, its output)"""
    out = io.StringIO()
    s.git, s.subprocess.run = git_fn or real_git, run_fn or real_run
    try:
        with contextlib.redirect_stdout(out):
            rc = with_dir(folder, lambda: s.warm(argparse.Namespace(rev=rev)))
    finally: s.git, s.subprocess.run = real_git, real_run
    return rc, out.getvalue()
d102 = str(T / "warm-gitfail"); os.makedirs(d102)
rc102, out102 = run_warm(d102, run_fn=batch_answer(None, lambda ids, data: (b"", 0)))
check("CACHE 102 a warm in which git gives no file contents keeps nothing (no tree entry, no record) and exits 1: an incomplete index is never kept", rc102 == 1 and not kept(d102, "tree") and not kept(d102, "facts") and "saved" not in out102, (rc102, out102, kept(d102, "tree"), len(kept(d102, "facts"))))
d103 = str(T / "warm-lsfail"); os.makedirs(d103)
rc103, out103 = run_warm(d103, git_fn=lambda *a, **k: None if a and a[0] == "ls-tree" else real_git(*a, **k))
k103 = kept(d103, "tree")
rc103b, out103b = run_warm(d103)
check("CACHE 103 …nor does one whose listing of the tree failed, and the next warm, with git well, builds it and keeps it", rc103 == 1 and not k103 and rc103b == 0 and "saved" in out103b and kept(d103, "tree") == ["tree-" + TREE[C1]], (rc103, k103, rc103b, out103b))
d104 = str(T / "warm-blobs"); os.makedirs(d104)
built = []
real_bf = s.build_facts
def counting_bf(*a, **k):
    if len(a) < 2 and not k.get("ctx"): built.append(1)
    return real_bf(*a, **k)
s.build_facts = counting_bf
try:
    rc104a, _ = run_warm(d104, C1); n_first = len(built); del built[:]
    rc104b, out104b = run_warm(d104, C2); n_next = len(built)
finally: s.build_facts = real_bf
check("CACHE 104 a warm of the revision after a change reads the records of the files that did not change and builds only the one that did: one record is built, and both revisions are kept",
      rc104a == 0 and rc104b == 0 and n_first >= distinct - 1 and n_next == 1 and kept(d104, "tree") == sorted(["tree-" + TREE[C1], "tree-" + TREE[C2]]), (rc104a, rc104b, n_first, n_next, kept(d104, "tree")))

# a head (select's second index) that was cheap to make is not kept: Names skip_cheap
def idx(n):
    def nm(x):
        if isinstance(x, (set, frozenset)): return sorted((nm(i) for i in x), key=repr)
        if isinstance(x, dict): return sorted(([nm(k), nm(v)] for k, v in x.items()), key=repr)
        if isinstance(x, (list, tuple)): return [nm(i) for i in x]
        return x
    return json.dumps({f: {k: nm(getattr(m, k)) for k in FIELDS} for f, m in n.files.items()}, sort_keys=True, default=repr)
def names_skip(folder, rev, git_fn=None, run_fn=None, cheap=None):
    s.git, s.subprocess.run = git_fn or real_git, run_fn or real_run
    old_cheap = s.CHEAP_PARSE
    if cheap is not None: s.CHEAP_PARSE = cheap
    try: return with_dir(folder, lambda: s.Names(rev, skip_cheap=True))
    finally: s.git, s.subprocess.run, s.CHEAP_PARSE = real_git, real_run, old_cheap
os.environ["SUITEMAP_CACHE"] = "0"
try: ref2 = idx(s.Names(C2))
finally: os.environ.pop("SUITEMAP_CACHE")
d105 = str(T / "skip-cheap"); os.makedirs(d105)
run_warm(d105, C1)
n105 = names_skip(d105, C2)
check("CACHE 105 a head whose build parsed few files (one changed since the kept revision) is not kept: its tree entry is not written, the one record it needed is, and the index is the index with no cache",
      n105.kept == "not kept" and n105.parsed == 1 and kept(d105, "tree") == ["tree-" + TREE[C1]] and ("facts-" + git("rev-parse", f"{C2}:pkg/util.py").strip()) in kept(d105, "facts") and idx(n105) == ref2, (n105.kept, n105.parsed, kept(d105, "tree")))
n105b = names_skip(d105, C2)
check("CACHE 106 …a second call for it is the same (nothing is read from or written to the tree entries), and costs the one blob's record, not a parse", n105b.kept == "not kept" and n105b.parsed == 0 and kept(d105, "tree") == ["tree-" + TREE[C1]] and idx(n105b) == ref2, (n105b.kept, n105b.parsed))
d107 = str(T / "skip-costly"); os.makedirs(d107)
n107 = names_skip(d107, C1, cheap=0)
n107b = names_skip(d107, C1, cheap=0)
check("CACHE 107 a head whose build parsed more files than the bound is kept as any index is: saved the first time, loaded the second, the same index", n107.kept == "saved" and n107b.kept == "loaded" and kept(d107, "tree") == ["tree-" + TREE[C1]] and idx(n107) == idx(n107b), (n107.kept, n107b.kept, kept(d107, "tree")))
d108 = str(T / "skip-cold"); os.makedirs(d108)
n108 = names_skip(d108, C1)
check("CACHE 108 …and the bound is a count of files parsed: the fixture's whole checkout (a dozen files, under the bound) built from nothing is not kept either, though every record of it is", n108.kept == "not kept" and n108.parsed >= distinct - 1 and not kept(d108, "tree") and len(kept(d108, "facts")) == len(full_facts), (n108.kept, n108.parsed, kept(d108, "tree")))
d109 = str(T / "skip-incomplete"); os.makedirs(d109)
n109 = names_skip(d109, C1, cheap=0, run_fn=batch_answer(None, lambda ids, data: (b"", 0)))
check("CACHE 109 a head whose build was incomplete (git gave no file contents) is never kept, however many files it parsed: no tree entry, the call has the index it could make, and it says it was incomplete", n109.kept == "incomplete" and not kept(d109, "tree"), (n109.kept, kept(d109, "tree")))
d110 = str(T / "skip-loaded"); os.makedirs(d110)
run_warm(d110, C2)
n110 = names_skip(d110, C2)
check("CACHE 110 a head whose tree is kept already (warmed after its merge) is loaded, whatever the bound: no parse, the same index", n110.kept == "loaded" and n110.parsed == 0 and idx(n110) == ref2, (n110.kept, n110.parsed))

# select, end to end, in a second repository that has suites: what a cold folder, a warmed one and no cache print is the same
R2 = T / "repo2"; R2.mkdir()
def git2(*a): return subprocess.run(["git", "-C", str(R2), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout
def write2(rel, text): p = R2 / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
def commit2(msg): git2("add", "-A"); git2("commit", "-qm", msg); return git2("rev-parse", "HEAD").strip()
git2("init", "-q", "-b", "main")
for rel, text in FIX.items(): write2(rel, text)
write2("tests/one_scenario.py", "print('one')\n"); write2("tests/two_scenario.py", "print('two')\n")
D1 = commit2("one")
write2("pkg/util.py", "ONE = 5\n\ndef helper(x):\n    return x + ONE\n\nclass Helper:\n    size = 2\n")
D2 = commit2("two")
write2("pkg/util.py", "ONE = 6\n\ndef helper(x):\n    return x + ONE\n\nclass Helper:\n    size = 3\n"); write2("a/z.py", "ONE = 7\n")
D3 = commit2("branch: two files")
MAP = T / "map.json"
MAP.write_text(json.dumps({"format": s.FORMAT, "commit": D1, "strace": True, "suites": {
    "one": {"ok": True, "seconds": 3, "py": {}, "whole": ["pkg/util.py", "a/z.py"], "files": [], "dirs": []},
    "two": {"ok": True, "seconds": 3, "py": {}, "whole": [], "files": [], "dirs": []}}}))
def sel(to, name, env=None):
    e = dict(ENV); e.update(SUITEMAP_ROOT=str(R2), SUITEMAP_CACHE_DIR=cdir(name)); e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), "select", "--map", str(MAP), "--to", to], capture_output=True, text=True, env=e, cwd=str(R2), timeout=120)
    return r.returncode, r.stdout, sorted(l for l in r.stderr.splitlines() if not l.startswith("suitemap: parse"))
def warm2(rev, name):
    e = dict(ENV); e.update(SUITEMAP_ROOT=str(R2), SUITEMAP_CACHE_DIR=cdir(name))
    return subprocess.run([sys.executable, os.path.join(SCR, "suitemap.py"), "warm", "--rev", rev], capture_output=True, text=True, env=e, cwd=str(R2), timeout=120)
off2, off3 = sel(D2, "sel-off", {"SUITEMAP_CACHE": "0"}), sel(D3, "sel-off", {"SUITEMAP_CACHE": "0"})
cold2, cold3 = sel(D2, "sel-cold"), sel(D3, "sel-cold")
check("CACHE 111 select on a head that changes one file, and on one that changes two, prints the same suites, notes and status with a cold folder as with no cache (and the change reaches the suite that reads the file whole, not the one that does not)",
      off2 == cold2 and off3 == cold3 and off2[0] == 0 and "one" in off2[1].split() and "two" not in off2[1].split() and "one" in off3[1].split() and "two" not in off3[1].split(), (off2, cold2, off3, cold3))
check("CACHE 112 …the cold call kept main's index (the map's commit, which every pull request shares) and not the head's, which was cheap to make; its records are kept", entries("sel-cold", "tree-") == ["tree-" + git2("rev-parse", D1 + "^{tree}").strip()] and entries("sel-cold", "facts-"), entries("sel-cold"))
wm = warm2(D2, "sel-warm")
wm1 = warm2(D1, "sel-warm")
before_sel = entries("sel-warm")
warm2_ = sel(D2, "sel-warm"); warm3 = sel(D3, "sel-warm")
after_sel = entries("sel-warm")
two_trees = sorted("tree-" + git2("rev-parse", c + "^{tree}").strip() for c in (D1, D2))
check("CACHE 113 select after a warm of the new main and of the map's commit prints the same as with no cache, on that revision and on a branch of two files over it; the trees kept are the two the warms made (the branch's is not added), and a call costs at most the records of the blobs the branch changed",
      wm.returncode == 0 and wm1.returncode == 0 and warm2_ == off2 and warm3 == off3 and [e for e in after_sel if e.startswith("tree-")] == two_trees and set(before_sel) <= set(after_sel) and len(after_sel) - len(before_sel) <= 2,
      (wm.returncode, wm.stderr[-200:], warm2_, warm3, before_sel, after_sel))

# [final]
print(("ok" if not fails else "FAILED") + f": suitemap cache scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
