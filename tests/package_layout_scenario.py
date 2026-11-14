"""Scenario test for the package layout (stackshot/<area>/<module>.py) and for the forwarders at the old root paths — no server, no network.

The code lives in the `stackshot` package. Every root forwarder of the moved modules is gone but four (PLUGIN_FORWARDERS below), which older copies of the stackshot plugin still name. Covers:
  * exactly those four forwarders: any other file outside the package and the tests that holds a `_TARGET = "stackshot...."` line fails the suite, and so does any other `.py` file at the checkout's root
  * each of the four reaches its module (the same module object, state shared), keeps its mode and runs the module's main as a script
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
# The four root forwarders that stay, the one explicit list: installed copies of the stackshot plugin older than 0.1.7 still run `$S/pages.py` and `$S/push.py` and import `config.py` and `connectors.py` from the
# checkout's root, and with these gone the page gate and four other guards would go silently off in a pane that was not relaunched. The list goes (and CONTRIBUTING.md's Forwarders paragraph with it) in a follow-up
# once no installed plugin copy is older than 0.1.7 and every pane has been relaunched.
PLUGIN_FORWARDERS = ("pages.py", "push.py", "config.py", "connectors.py")
KEEP = set(PLUGIN_FORWARDERS)
def unexpected(found, keep):
    """the forwarders that should not be there and the kept ones that are gone"""
    return sorted(set(found) ^ set(keep))
# the `_TARGET` line of a forwarder: either quote, spaces around the `=`, and a trailing comment all still make a forwarder
TARGET_RX = re.compile(r"""^_TARGET\s*=\s*(?P<q>["'])(?P<t>stackshot[\w.]*)(?P=q)\s*(?:#.*)?$""", re.M)
FWD = {}      # old path (relative) -> target module
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "stackshot", "tests"}
for f in sorted(ROOT.rglob("*.py")):
    rel = f.relative_to(ROOT)
    if _SKIP_DIRS & set(rel.parts[:-1]): continue
    m = TARGET_RX.search(f.read_text(encoding="utf-8"))
    if m:
        FWD[rel.as_posix()] = m.group("t")
check("the forwarders are exactly the four of PLUGIN_FORWARDERS: no file outside the package and the tests holds a `_TARGET = \"stackshot....\"` line but those", len(KEEP) == 4 and not unexpected(FWD, KEEP) and all(FWD[k].startswith("stackshot.") for k in KEEP), unexpected(FWD, KEEP))
rootpy = sorted(f.name for f in ROOT.glob("*.py"))
check("... and no other .py file at the root (a root script is a forwarder or a program that belongs in the package)", rootpy == sorted(KEEP), unexpected(rootpy, KEEP))
check("a fifth root forwarder (and the loss of a kept one) is seen by that rule", unexpected(list(KEEP) + ["server.py"], KEEP) == ["server.py"] and unexpected(sorted(KEEP)[1:], KEEP) == [sorted(KEEP)[0]] and unexpected(KEEP, ()) == sorted(KEEP))

# a forwarder is a forwarder however its line is written (single quotes, a trailing comment, no spaces): each of these files would be a fifth one
fifth = {"a.py": '_TARGET = "stackshot.core.x"\n', "b.py": "_TARGET = 'stackshot.core.x'\n", "c.py": '_TARGET = "stackshot.core.x"  # moved\n', "d.py": "_TARGET='stackshot.core.x' # moved\n", "e.py": 'import sys\n_TARGET = "stackshot.core.x"\nsys.exit(0)\n'}
seen = {k: bool(TARGET_RX.search(v)) for k, v in fifth.items()}
check("a forwarder whose _TARGET line has single quotes, a trailing comment or no spaces is still seen, and a line that names no package module is not", all(seen.values()) and not TARGET_RX.search('_TARGET = "elsewhere.x"\n') and not TARGET_RX.search('# _TARGET = "stackshot.core.x"\n') and unexpected([k for k, v in seen.items() if v] + sorted(KEEP), KEEP) == sorted(fifth), seen)

# each of the four reaches its module: the same module object (state and monkeypatching are shared), a body of no code, and the file mode and shebang it had
missing = [k for k in sorted(KEEP) if not (ROOT / (FWD.get(k, "x").replace(".", "/") + ".py")).is_file()]
check("every kept forwarder names a module of the package that exists, and no two name the same one", not missing and len(set(FWD.get(k) for k in KEEP)) == len(KEEP), missing)
body = [k for k in sorted(KEEP) if (ROOT / k).is_file() and (ROOT / k).read_text(encoding="utf-8").count("\n") > 40]
check("a forwarder holds no code: none is longer than a screen", not body, body)
probe = ("import importlib, sys\nsys.path.insert(0, %r)\nbad = []\nfor old, new in %r:\n    try:\n        a = importlib.import_module(old); b = importlib.import_module(new)\n        if a is not b: bad.append((old, new, 'not the same object'))\n"
         "    except BaseException as e:\n        bad.append((old, new, type(e).__name__ + ': ' + str(e)[:120]))\nimport config\nfrom stackshot.core import config as c2\nconfig.CFG['x_probe'] = 1\nprint(repr(bad), c2.CFG.get('x_probe') == 1)\n") % (STACK, [(k[:-3], FWD.get(k, "")) for k in sorted(KEEP)])
(T / "probe.py").write_text(probe)
rc, out, err = run([sys.executable, str(T / "probe.py")])
check("importing each by its old name gives the package's module object, and a change through the old name is seen through the new one", rc == 0 and out.strip() == "[] True", (rc, out[-900:], err[-600:]))
EXEC = ["pages.py", "push.py"]
bad = [f for f in EXEC if not os.access(ROOT / f, os.X_OK) or not (ROOT / f).read_text(encoding="utf-8").startswith("#!")]
check("pages.py and push.py, executable programs before the move, stay executable with their shebang", not bad, bad)
for old in sorted(KEEP):
    target = FWD.get(old, "stackshot.none")
    r1 = run([sys.executable, str(ROOT / old), "--help"], cwd="/")
    r2 = run([sys.executable, "-c", f"import sys, runpy; sys.path.insert(0, {STACK!r}); sys.argv = [{target!r}, '--help']; runpy.run_module({target!r}, run_name='__main__', alter_sys=True)"], cwd="/")
    check(f"python3 {old} --help prints what the module prints and exits the same", r1[0] == r2[0] and r1[1] == r2[1] and (r1[1] or r1[2]), (r1, r2))
rc, out, err = run([sys.executable, "-I", str(ROOT / "config.py"), "path"], cwd="/")
check("python3 -I config.py path (isolated mode, another directory) still runs", rc == 0 or "usage" in out + err, (rc, out, err))

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

# ---- no caller outside the package names a root script (the four forwarders that stay are for the plugin's older copies, not for this checkout: no exemption, every module name of the package is searched for)
# The scan covers every tracked file but the package, the docs (a prose mention is reported by hand, not failed) and this suite's own fixtures: the units, scripts, hooks and workflow, and the suites themselves.
# A caller is (a) a path that ends in `<module>.py` and does not run inside the package (`$REPO/client.py`, `~/stackshot/config.py`, `$(dirname "$0")/../server.py`, `<checkout>/anchor-hub.py`), or a
# bare `<module>.py` that follows a run word (`python3 server.py`, `exec server.py`, `--script server.py`); (b) an import statement of a root module, at the start of a line or after `;` or a quote
# (`python3 -c "import config"`, a heredoc's `import config`, `from render import x`), or a real import in a .py file. A comment line names things and runs nothing.
PKG = ROOT / "stackshot"
PKG_DIRS = {d.name for d in PKG.rglob("*") if d.is_dir() and d.name != "__pycache__"}
# the module names that had a file at the root or in tools/ (the 143 forwarders of the move; frozen, so a later module of the package that happens to share a common word, `app`, is no caller)
FORMER = """
    activity anchor-hub anchor-hub-google-auth anchor_scope anchorhub anchors archive_empty_projects ask_leaves ask_read audit audit_checks audit_overview audit_run
    backfill_contact backfill_step_proof board_report brains bullet_text call_log cap_words cimd client clients close_marks_backfill close_repair cloud cold_call
    colorcombos compare_pair_reads config connectors contact dated_wait draft drop_renamed_pending event_waits fleet foryou front_step ghbudget ghmigrate ghsync goal_pass
    handoff handoff_repair handover held home inbox interp item_project item_project_pass itempage ladder landed lanes legacy_owner liveness make_icons migrate_model
    migrate_project_record migration model model_guard_report model_guards mover_state next_backfill next_report next_rules nextlines note_read open_item_text
    option_labels owner_steps page_agent_report page_debt page_keeper pages pr_state project project_archive project_id_report project_registry project_verbs projects
    publish puller push quiet readonly rebullet rebullet_descriptions refusal_report registry_report rename_page renamed_agents render reports restore_close_descriptions
    retire_fields retire_fields_report retired_inputs router router_live routing rulebook_scan runner runners said search self_wait server server_fixes session_ids
    sessions_registry silence stall stamp_phase states step_commands step_proof steps successor ui uiprefs versions wait_end waiting watchers whatschanged work
""".split()
assert len(FORMER) == len(set(FORMER)) >= 130
NAMES = sorted(set(FORMER) | {n.replace("_", "-") for n in FORMER if "_" in n}, key=len, reverse=True)
FORMER_SET = set(FORMER)
_N = "|".join(re.escape(n) for n in NAMES)
PATH_RX = re.compile(r"(?P<dir>(?:[^\s\"'`=(){}|;,<>]*/)+)(?P<mod>" + _N + r")\.py\b(?!\.lock)")
_OPT = r"(?:-[XW]\s+\S+\s+|--(?:project|directory|python|with|extra|group)\s+\S+\s+|--?[\w-]+(?:=\S+)?\s+)*"      # `-X utf8`, `--locked`, `--project "$HERE"`, `-u` in front of the script
RUN_RX = re.compile(r"(?:\bpython3?(?:\.\d+)?|--script|\bexec|\$PY|\buv run)\s+" + _OPT + r"[\"']?(?:\./)?(?P<mod>" + _N + r")\.py\b(?!\.lock)")
IMP_RX = re.compile(r"(?:^|[;'\"`(]|\s;)\s*(?:import\s+(?P<imp>[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)|from\s+(?P<frm>[\w.]+)\s+import\b)")
CTX_RX = re.compile(r"sys\.executable|subprocess|Popen|check_output|runpy|spec_from_file_location|\bpython3?\b|os\.path\.join|Path\(|\b(?:STACK|ROOT|SCR|HERE)\b\s*[/,]|\bexec\b")
def _in_package(d: str) -> bool:
    """is `d` (the folders in front of a module file, `.../stackshot/core/`) a folder of the package?"""
    segs = [x for x in d.split("/") if x]
    if "stackshot" not in segs: return False
    rest = segs[len(segs) - segs[::-1].index("stackshot"):]
    return bool(rest) and all(x in PKG_DIRS for x in rest)
def scan_text(name: str, text: str) -> list:
    """the lines of `text` (a file called `name`) that run or import a root script of a deleted forwarder: [(line number, text)]"""
    out = []
    for i, l in enumerate(text.splitlines(), 1):
        if l.lstrip().startswith("#"): continue
        # in a .py file a path in a label, a docstring or a message is prose; it is a caller where the line builds or runs a path
        paths = not name.endswith(".py") or CTX_RX.search(l)
        hit = bool(RUN_RX.search(l)) or bool(paths and any(not _in_package(m.group("dir")) for m in PATH_RX.finditer(l)))
        if not hit:
            for m in IMP_RX.finditer(l):
                mods = [x.strip().split()[0].split(".")[0] for x in m.group("imp").split(",")] if m.group("imp") else [m.group("frm").split(".")[0]]
                if any(x in FORMER_SET for x in mods) and not re.search(r"\bfrom\s+\w+\.py\b", l): hit = True
        if hit: out.append((i, l.strip()[:110]))
    if name.endswith(".py"):
        try: tree = ast.parse(text)
        except SyntaxError: tree = None
        for n in ast.walk(tree) if tree else ():
            mods = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else [n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
            if any(x in FORMER_SET for x in mods): out.append((n.lineno, "import " + ",".join(mods)))
    return out
# the scan must see what it is for: each of these is a caller, each of the last four is not (a bug in a pattern fails here, not in a review)
MUST = [("u.sh", 'exec python3 "$(dirname "$0")/../server.py"'), ("u.sh", "python3 $REPO/client.py get brief"), ("u.sh", "~/stackshot/config.py get a.b"), ("u.sh", "ExecStart=/usr/bin/python3 @CHECKOUT@/puller.py"),
        ("u.sh", "python3 - <<'E'\nimport config\nE"), ("u.sh", "python3 -c \"import json; from render import x\""), ("t.py", 'subprocess.run([sys.executable, "-c", "import config"])'),
        ("t.py", 'r = run("from stackshot.core import x; import ghsync as G; G.f()")'), ("t.py", "import server\n"), ("u.sh", "uv run --script anchor-hub.py status"), ("u.sh", "ssh h '<checkout>/anchor-hub-google-auth.py x'"),
        ("u.sh", "python3 tools/cap_words.py --help"), ("t.py", 'p = ["python3", "x/ui/render.py"]'), ("t.py", "import ui.render"),
        ("u.sh", "uv run --locked server.py"), ("u.sh", "python3 -X utf8 server.py"), ("u.sh", 'uv run --project "$HERE" --locked client.py get x'), ("u.sh", "python3 -u -X utf8 -W error ./publish.py bump")]
MUSTNOT = [("u.sh", 'python3 "$HERE/stackshot/core/config.py" get a'), ("u.sh", "# python3 server.py"), ("t.py", "from stackshot.web import server\nimport json"), ("u.sh", "python3 -m stackshot.tools.cap_words --help"),
           ("t.py", 'cmd = "from stackshot.core import config; print(config.CFG)"'), ("u.sh", "python3 ~/stackshot/stackshot/fleet/client.py get x"), ("t.py", "from fastmcp.server.auth import cimd"), ("u.sh", "`pages.py` reads the page"),
           ("u.sh", "uv run --locked stackshot publish publish"), ("u.sh", "python3 -X utf8 stackshot/web/server.py"), ("u.sh", "uv run --project \"$HERE\" --locked python tests/x_scenario.py")]
missed = [t for n, t in MUST if not scan_text(n, t)]; wrong = [t for n, t in MUSTNOT if scan_text(n, t)]
check("the scan for callers of a root script catches each shape it is for (a path outside the package, a bare name after a run word, a -c import, a heredoc import, an import in a suite)", not missed, missed)
check("... and leaves the package's own paths, a comment, a module of the package and prose alone", not wrong, wrong)
SCAN_SKIP = {"tests/package_layout_scenario.py", "uv.lock"}
SCAN_DIRS = {"stackshot", "docs", "fonts", "icons", "shared", ".git", ".venv", "__pycache__", "node_modules", ".suitemap"}
callers, scanned = [], 0
for p in sorted(ROOT.rglob("*")):
    rel = p.relative_to(ROOT).as_posix()
    if SCAN_DIRS & set(p.relative_to(ROOT).parts) or rel in SCAN_SKIP or not p.is_file() or p.suffix in (".png", ".svg", ".woff2", ".js", ".json", ".md", ".txt", ".lock", ".pyc"): continue
    try: text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError): continue
    scanned += 1
    callers += [f"{rel}:{n}: {t}" for n, t in scan_text(rel, text)]
check("the scan reads the checkout's scripts, units, hooks, workflow and suites (not an empty set)", scanned > 150, scanned)
check("no unit, script, hook, workflow or suite of the checkout runs a root script or imports a root module by its old name", not callers, callers[:12])

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
