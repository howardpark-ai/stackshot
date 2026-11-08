"""Scenario test for the package layout (stackshot/<area>/<module>.py) and the forwarders at the old root paths — no server, no network.

The code lives in the `stackshot` package; every module that moved keeps a forwarder at its old path until Sun Nov 22nd 2026, so units, hooks, allow rules and scripts that name
the old path keep working. Covers:
  * every forwarder names a module that exists, imports as that very module object (state and monkeypatching are shared), and keeps its old file mode and shebang
  * a forwarder started as a script runs the module's main (same output as `python3 -m <module>`), also in isolated mode and from another directory
  * the puller's forwarder: the VERSION line an older puller reads, and the namespace an older puller's reload (runpy.run_path) takes main() from
  * ui/ and anchorhub/ keep importing by their old names, to the same module objects
  * no module of the package imports a flat name or edits sys.path; client, puller, config and push import only the standard library
  * the command line: `python3 -m stackshot`, bin/stackshot, and a program run as `stackshot <program>`
  * pyproject.toml, the entry point and uv.lock; no lock of a suite

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

# ---- the forwarders, found as files: a forwarder is a file with a `_TARGET = "stackshot...."` line
FWD = {}      # old path (relative) -> target module
for sub in ("", "tools", "ui", "anchorhub"):
    d = ROOT / sub if sub else ROOT
    for f in sorted(d.glob("*.py")):
        m = re.search(r'^_TARGET = "(stackshot[\w.]*)"$', f.read_text(encoding="utf-8"), re.M)
        if m:
            FWD[f"{sub}/{f.name}" if sub else f.name] = m.group(1)
check("the forwarders are there: one at the old path of each moved module", len(FWD) >= 140, len(FWD))

missing = []
for old, target in FWD.items():
    rel = target.replace(".", "/")
    if not ((ROOT / (rel + ".py")).is_file() or (ROOT / rel / "__init__.py").is_file()):
        missing.append((old, target))
check("every forwarder names a module of the package that exists", not missing, missing)

dup = [t for t in set(FWD.values()) if list(FWD.values()).count(t) > 1]
check("no two forwarders name the same module", not dup, dup)

body = [(old, t) for old, t in FWD.items() if (ROOT / old).read_text(encoding="utf-8").count("\n") > 40]
check("a forwarder holds no code: none is longer than a screen", not body, body)

# ---- importing by the old name gives the module object of the package (a child process: the old names must not leak into this one)
# not these three: importing one needs a dependency the suites do not have or an instance (their forwarders are run as scripts by the units, which the checks below cannot start)
SKIP = {"anchor-hub-google-auth.py", "server.py", "tools/make_icons.py"}
names = [(old[:-3].replace("/", "."), t) for old, t in FWD.items() if not old.endswith("/__init__.py") and old not in SKIP]
probe = "import importlib, sys\nsys.path.insert(0, %r)\nbad = []\nfor old, new in %r:\n    try:\n        a = importlib.import_module(old); b = importlib.import_module(new)\n        if a is not b: bad.append((old, new, 'not the same object'))\n    except BaseException as e:\n        bad.append((old, new, type(e).__name__ + ': ' + str(e)[:120]))\nprint(repr(bad))\n" % (STACK, names)
(T / "probe.py").write_text(probe)
rc, out, err = run([sys.executable, str(T / "probe.py")])
check("importing a module by its old name gives the package's module object (also ui.* and anchorhub.*)", rc == 0 and out.strip() == "[]", (rc, out[-900:], err[-600:]))

probe2 = ("import sys\nsys.path.insert(0, %r)\nimport config, ui, anchorhub\nfrom stackshot.core import config as c2\nimport ui.render as r\nfrom stackshot.web.ui import render as r2\n"
          "config.CFG['x_probe'] = 1\nprint(config is c2, c2.CFG.get('x_probe') == 1, r is r2, ui.PREFIX == '', ui.under('/x') == '/x')\n") % STACK
(T / "probe2.py").write_text(probe2)
rc, out, err = run([sys.executable, str(T / "probe2.py")])
check("state is shared: a change through the old name is seen through the new one; the old ui package still answers PREFIX and under()", rc == 0 and out.split()[:4] == ["True"] * 4, (rc, out, err[-400:]))

# ---- modes and shebangs: what was executable stays executable, with its shebang
EXEC = ["anchor-hub-google-auth.py", "anchor-hub.py", "client.py", "pages.py", "push.py", "server.py", "tools/handoff_repair.py", "tools/migrate_model.py", "tools/model_guard_report.py"]
bad = [f for f in EXEC if f in FWD and not os.access(ROOT / f, os.X_OK)]
check("a forwarder of a program that was executable is executable", not bad and all(f in FWD for f in EXEC), bad or [f for f in EXEC if f not in FWD])
badsh = [f for f in EXEC if f in FWD and not (ROOT / f).read_text(encoding="utf-8").startswith("#!")]
check("... and starts with its shebang", not badsh, badsh)
UV = ["server.py", "anchor-hub.py", "anchor-hub-google-auth.py", "audit.py", "publish.py", "ghmigrate.py", "tools/make_icons.py", "tools/migrate_model.py", "tools/close_marks_backfill.py", "tools/rulebook_scan.py"]
nohdr = [f for f in UV if not (ROOT / f).read_text(encoding="utf-8").count("# /// script") == 1 or not (ROOT / (f + ".lock")).is_file()]
check("the ten forwarders that units start as `uv run --locked --script` keep their inline metadata and their lock", not nohdr, nohdr)
moved_hdr = [str(p.relative_to(ROOT)) for p in (ROOT / "stackshot").rglob("*.py") if "# /// script" in p.read_text(encoding="utf-8")]
check("... and the moved copies carry none (one dependency list: pyproject.toml)", not moved_hdr, moved_hdr)

# ---- started as a script: the module's main runs
for old in ("held.py", "config.py", "tools/board_report.py", "pages.py"):
    target = FWD[old]
    r1 = run([sys.executable, str(ROOT / old), "--help"], cwd="/")
    # the module run the way a forwarder runs it (the checkout must be on the path)
    r2 = run([sys.executable, "-c", f"import sys, runpy; sys.path.insert(0, {STACK!r}); sys.argv = [{target!r}, '--help']; runpy.run_module({target!r}, run_name='__main__', alter_sys=True)"], cwd="/")
    check(f"python3 {old} --help prints what the module prints and exits the same", r1[0] == r2[0] and r1[1] == r2[1] and (r1[1] or r1[2]), (r1, r2))
rc, out, err = run([sys.executable, "-I", str(ROOT / "config.py"), "path"], cwd="/")
check("python3 -I config.py path (isolated mode, another directory) still runs", rc == 0 or "usage" in out + err, (rc, out, err))
for old in ("tools/cap_words.py", "tools/project.py"):
    rc, out, err = run([sys.executable, str(ROOT / old), "--help"], cwd="/")
    check(f"{old} --help runs from another directory", rc == 0 and (out + err).strip() != "", (rc, out[-200:], err[-300:]))

# ---- the real files run as scripts too (python3 stackshot/<area>/<name>.py), and as the old path's target
rc, out, err = run([sys.executable, str(ROOT / "stackshot/fleet/client.py"), "--help"], cwd="/")
check("python3 stackshot/fleet/client.py runs as a script (the package finds the checkout itself)", rc == 0 or "usage" in (out + err).lower(), (rc, out[-200:], err[-300:]))

# ---- the puller
pf = (ROOT / "puller.py").read_text(encoding="utf-8")
real = (ROOT / "stackshot/fleet/puller.py").read_text(encoding="utf-8")
va = re.search(r'^VERSION\s*=\s*"([^"]+)"', pf, re.M); vb = re.search(r'^VERSION\s*=\s*"([^"]+)"', real, re.M)
check("puller.py's VERSION line (read as text by an older puller and the provisioning script) equals the package's", va and vb and va.group(1) == vb.group(1), (va and va.group(1), vb and vb.group(1)))
probe3 = ("import runpy, sys\nsys.path.insert(0, %r)\nns = runpy.run_path(%r, run_name='puller_reloaded')\nprint(callable(ns.get('main')), ns.get('VERSION'), callable(ns.get('_entry')))\n") % (STACK, str(ROOT / "puller.py"))
(T / "probe3.py").write_text(probe3)
rc, out, err = run([sys.executable, str(T / "probe3.py")])
check("an older puller's reload (runpy.run_path of puller.py) gets main() and the VERSION in the namespace it takes", rc == 0 and out.split()[:1] == ["True"] and out.split()[1:2] == [va.group(1)], (rc, out, err[-500:]))
dv = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); from stackshot.fleet import puller; print(puller.disk_version(), puller.VERSION, puller.HERE == {STACK!r}); print(sorted(puller._RELOAD_FILES))"], capture_output=True, text=True, env=ENV, cwd="/")
check("the package's puller reads its own VERSION on disk and runs from the checkout", dv.returncode == 0 and dv.stdout.split("\n")[0].split() == [vb.group(1), vb.group(1), "True"], (dv.stdout, dv.stderr[-400:]))

# ---- the modules of the package: no flat imports, no sys.path edits (except the script bootstrap)
flat = {old[:-3].split("/")[-1] for old in FWD if "/" not in old} | {"ui", "anchorhub"}
tools_flat = {old[:-3].split("/")[-1] for old in FWD if old.startswith("tools/")}
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
rc2, out2, err2 = run([sys.executable, str(ROOT / "pages.py"), "--help"], cwd="/")
check("stackshot pages --help prints what pages.py prints", rc == rc2 and out == out2 and out.strip(), ((rc, out[:100], err[:200]), (rc2, out2[:100])))
rc, out, err = run([str(ROOT / "bin/stackshot"), "client", "mint", "--help"], cwd="/")
check("stackshot client mint is the setup command, not the client program", "mint" in (out + err).lower() and "usage: stackshot" in (out + err), (rc, out[-300:], err[-300:]))
sys.path.insert(0, STACK)
from stackshot import cli
progs = [n for n, (m, _) in cli.PROGRAMS.items() if not (ROOT / m.replace(".", "/")).with_suffix(".py").is_file()]
check("every program of the command line names a module that exists", not progs, progs)

# ---- the project
import tomllib
pp = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
check("pyproject.toml: the entry point stackshot is stackshot.cli:main, and the base install has no dependencies", pp["project"]["scripts"]["stackshot"] == "stackshot.cli:main" and pp["project"]["dependencies"] == [], pp["project"])
check("... the suites' dependencies are the `tests` group, the rest are extras", "tests" in pp["dependency-groups"] and {"server", "anchor-hub", "icons"} <= set(pp["project"]["optional-dependencies"]), pp.get("dependency-groups"))
check("uv.lock is at the root and there is no lock under tests/", (ROOT / "uv.lock").is_file() and not list((ROOT / "tests").glob("*.lock")) and not (ROOT / "tests/uv.lock").exists() and not (ROOT / "tests/pyproject.toml").exists())

print(("ok" if not fails else "FAILED") + f": package layout scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
