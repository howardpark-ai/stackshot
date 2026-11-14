"""Scenario test for the package layout (stackshot/<area>/<module>.py) and for the absence of forwarders at the old root paths — no server, no network.

The code lives in the `stackshot` package. Every root forwarder of the moved modules is gone, `puller.py` and `client.py` included: nothing is kept. Covers:
  * no forwarder anywhere: a file outside the package and the tests that holds a `_TARGET = "stackshot...."` line fails the suite, and so does any `.py` file at the checkout's root
  * no script at the root or in tools/ carries inline metadata or a lock of its own; the moved copies carry none
  * the package's puller reads its own VERSION line on disk and runs from the checkout; client, puller, config and push import only the standard library
  * no module of the package imports a flat name or edits sys.path
  * the command line: `python3 -m stackshot`, bin/stackshot, and a program run as `stackshot <program>`
  * pyproject.toml, the entry point and uv.lock; no lock of a suite
  * no unit, script, hook or workflow of the checkout runs a root script or imports a root module by its old name (no exemption: every name of a moved module is searched for)

    tests/run-suite package_layout        → exit 0 / 1"""
import ast, importlib, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK); sys.path.insert(0, SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="pkglayout-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:700]}")

ROOT = pathlib.Path(STACK)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
ENV.update(HOME=str(T), XDG_CONFIG_HOME=str(T / "cfg"), XDG_STATE_HOME=str(T / "state"), XDG_DATA_HOME=str(T / "data"), PYTHONDONTWRITEBYTECODE="1")
ENV.pop("STACKSHOT_CONFIG", None)
def run(args, cwd=None, **kw):
    p = subprocess.run(args, capture_output=True, text=True, timeout=120, env=ENV, cwd=cwd or str(T), **kw)
    return p.returncode, p.stdout, p.stderr

# ---- the forwarders, found as files: a forwarder is a file with a `_TARGET = "stackshot...."` line, anywhere in the checkout but the package and the tests
FWD = {}      # old path (relative) -> target module
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "stackshot", "tests"}
for f in sorted(ROOT.rglob("*.py")):
    rel = f.relative_to(ROOT)
    if _SKIP_DIRS & set(rel.parts[:-1]): continue
    m = re.search(r'^_TARGET = "(stackshot[\w.]*)"$', f.read_text(encoding="utf-8"), re.M)
    if m:
        FWD[rel.as_posix()] = m.group(1)
check("there is no forwarder: no file outside the package and the tests holds a `_TARGET = \"stackshot....\"` line", not FWD, sorted(FWD))
rootpy = sorted(f.name for f in ROOT.glob("*.py"))
check("... and no .py file at the root (a root script is a forwarder or a program that belongs in the package)", not rootpy, rootpy)

hdr = [p.relative_to(ROOT).as_posix() for p in list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) if "# /// script" in p.read_text(encoding="utf-8")]
locks = [p.relative_to(ROOT).as_posix() for p in list(ROOT.glob("*.lock")) + list((ROOT / "tools").glob("*.lock")) if p.name != "uv.lock"]
check("no script at the root or in tools/ carries inline metadata or a lock of its own: one dependency list, pyproject.toml and uv.lock", not hdr and not locks, (hdr, locks))
moved_hdr = [str(p.relative_to(ROOT)) for p in (ROOT / "stackshot").rglob("*.py") if "# /// script" in p.read_text(encoding="utf-8")]
check("... and the moved copies carry none (one dependency list: pyproject.toml)", not moved_hdr, moved_hdr)

# ---- the real files run as scripts (python3 stackshot/<area>/<name>.py)
rc, out, err = run([sys.executable, str(ROOT / "stackshot/fleet/client.py"), "--help"], cwd="/")
check("python3 stackshot/fleet/client.py runs as a script (the package finds the checkout itself)", rc == 0 or "usage" in (out + err).lower(), (rc, out[-200:], err[-300:]))

# ---- the puller
real = (ROOT / "stackshot/fleet/puller.py").read_text(encoding="utf-8")
vb = re.search(r'^VERSION\s*=\s*"([^"]+)"', real, re.M)
dv = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); from stackshot.fleet import puller; print(puller.disk_version(), puller.VERSION, puller.HERE == {STACK!r}); print(sorted(puller._RELOAD_FILES))"], capture_output=True, text=True, env=ENV, cwd="/")
check("the package's puller reads its own VERSION on disk and runs from the checkout", dv.returncode == 0 and dv.stdout.split("\n")[0].split() == [vb.group(1), vb.group(1), "True"], (dv.stdout, dv.stderr[-400:]))

# ---- the modules of the package: no flat imports, no sys.path edits (except the script bootstrap)
# the old flat names: every module of the package (a module that moved took its stem from the root), less the standard library's own; and the two packages that moved whole
_stems = {p.stem for p in (ROOT / "stackshot").rglob("*.py") if p.name != "__init__.py" and "__pycache__" not in p.parts}
flat = (_stems - set(sys.stdlib_module_names)) | {"ui", "anchorhub"}
tools_flat = set()
bad_imports, bad_path, nopkg = [], [], []
for p in sorted((ROOT / "stackshot").rglob("*.py")):
    rel = str(p.relative_to(ROOT))
    tree = ast.parse(p.read_text(encoding="utf-8"), rel)
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in flat | tools_flat: bad_imports.append((rel, n.lineno, a.name))
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and n.module.split(".")[0] in flat | tools_flat:
            bad_imports.append((rel, n.lineno, n.module))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("insert", "append") and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "path" and getattr(n.func.value.value, "id", "") == "sys":
            bad_path.append((rel, n.lineno))
    if p.parent.name != "__pycache__" and not (p.parent / "__init__.py").is_file(): nopkg.append(rel)
check("no module of the package imports a module by its old flat name", not bad_imports, bad_imports[:10])
check("no module of the package edits sys.path (a script's bootstrap assigns it once)", not bad_path, bad_path[:10])
check("every folder of the package has an __init__.py", not nopkg, nopkg)

# ---- client, puller, config and push import only the standard library (-S: no site-packages at all)
probe4 = ("import sys\nsys.path.insert(0, %r)\nfrom stackshot.fleet import client, puller, push\nfrom stackshot.core import config\n"
          "out = sorted({m.split('.')[0] for m in sys.modules} - set(sys.stdlib_module_names) - {'stackshot', '__main__'} - set(sys.builtin_module_names))\nprint(out)\n") % STACK
(T / "probe4.py").write_text(probe4)
rc, out, err = run([sys.executable, "-I", "-S", str(T / "probe4.py")])
check("client, puller, push and config import with nothing but the standard library (python3 -I -S)", rc == 0 and out.strip() == "[]", (rc, out, err[-500:]))

# ---- the command line
rc, out, err = run([sys.executable, "-m", "stackshot", "--help"], cwd=STACK)
check("python3 -m stackshot --help lists the programs", rc == 0 and "pages" in out and "programs:" in out, (rc, out[-300:], err[-300:]))
rc, out, err = run([str(ROOT / "bin/stackshot"), "config", "path"], cwd="/")
rc2, out2, err2 = run([sys.executable, str(ROOT / "stackshot/core/config.py"), "path"], cwd="/")
check("bin/stackshot config path runs the config program (same answer as the module)", (rc, out, err) == (rc2, out2, err2), ((rc, out, err), (rc2, out2, err2)))
rc, out, err = run([str(ROOT / "bin/stackshot"), "pages", "--help"], cwd="/")
rc2, out2, err2 = run([sys.executable, str(ROOT / "stackshot/projects/pages.py"), "--help"], cwd="/")
check("stackshot pages --help prints what stackshot/projects/pages.py prints", rc == rc2 and out == out2 and out.strip(), ((rc, out[:100], err[:200]), (rc2, out2[:100])))
rc, out, err = run([str(ROOT / "bin/stackshot"), "client", "mint", "--help"], cwd="/")
check("stackshot client mint is the setup command, not the client program", "mint" in (out + err).lower() and "usage: stackshot" in (out + err), (rc, out[-300:], err[-300:]))
sys.path.insert(0, STACK)
from stackshot import cli
progs = [n for n, (m, _) in cli.PROGRAMS.items() if not (ROOT / m.replace(".", "/")).with_suffix(".py").is_file()]
check("every program of the command line names a module that exists", not progs, progs)

rc, out, err = run([str(ROOT / "bin/stackshot"), "ghmigrate", "-h"], cwd="/")
check("stackshot <program> -h prints the usage line under the name typed (`stackshot ghmigrate`), not `python3 -m <module>`", rc == 0 and out.startswith("usage: stackshot ghmigrate "), (rc, out[:200], err[-200:]))
check("... and the parser class is the stock one again once the program has run", "stackshot" not in __import__("argparse").ArgumentParser.__init__.__code__.co_names)

# ---- no caller outside the package names a root script (there are no forwarders left, and no exemption: every module name of the package is searched for)
# a caller is a command that runs a root script, or a python -c that imports a root module, in a file that is not a test or the package; a comment line names things and runs nothing
FWD_NAMES = sorted(flat)
CALLER_FILES = [p for p in ROOT.rglob("*") if p.is_file() and not any(s in p.relative_to(ROOT).parts[:1] for s in ("stackshot", "tests", ".git", ".venv", "docs", "ui", "fonts", "icons", "shared"))
                and p.suffix in ("", ".sh", ".in", ".py", ".yml", ".toml") and p.name != "uv.lock"]
_N = "|".join(re.escape(n) for n in FWD_NAMES)
RUNS = re.compile(r"(?:\$CHECKOUT|\$HERE|\$\{HERE\}|@CHECKOUT@)(?:/\.\.)?/(?:tools/)?(?:" + _N + r")\.py\b(?!\.lock)|(?:python3?|--script|exec|\$PY)\s+\"?(?:\./)?(?:tools/)?(?:" + _N + r")\.py\b(?!\.lock)")
IMPORTS = re.compile(r"python3? -c .*(?:['\"]|;\s*)(?:import|from) (" + "|".join(re.escape(n) for n in FWD_NAMES) + r")\b")
callers = []
for p in CALLER_FILES:
    try: lines = p.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError): continue
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("#"): continue
        if RUNS.search(l) or IMPORTS.search(l): callers.append(f"{p.relative_to(ROOT)}:{i}: {l.strip()[:110]}")
check("no unit, script, hook or workflow of the checkout runs a root forwarder or imports a root module by its old name", not callers, callers[:8])

# ---- an argument that is not a command never starts the hub (anchor-hub -h used to start one)
rc, out, err = run([str(ROOT / "bin/stackshot"), "anchor-hub", "-h"], cwd="/")
check("stackshot anchor-hub -h prints its usage and exits 0 (it does not start a hub)", rc == 0 and "stackshot anchor-hub status" in out, (rc, out[:200], err[-300:]))
rc, out, err = run([str(ROOT / "bin/stackshot"), "anchor-hub", "frobnicate"], cwd="/")
check("... and a word that is no command is refused with exit 2", rc == 2 and "unknown command" in err, (rc, out[:200], err[-300:]))

# ---- the project
import tomllib
pp = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
check("pyproject.toml: the entry point stackshot is stackshot.cli:main, and the base install has no dependencies", pp["project"]["scripts"]["stackshot"] == "stackshot.cli:main" and pp["project"]["dependencies"] == [], pp["project"])
check("... the suites' dependencies are the `tests` group, the rest are extras", "tests" in pp["dependency-groups"] and {"server", "anchor-hub", "icons"} <= set(pp["project"]["optional-dependencies"]), pp.get("dependency-groups"))
check("uv.lock is at the root and there is no lock under tests/", (ROOT / "uv.lock").is_file() and not list((ROOT / "tests").glob("*.lock")) and not (ROOT / "tests/uv.lock").exists() and not (ROOT / "tests/pyproject.toml").exists())

print(("ok" if not fails else "FAILED") + f": package layout scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
