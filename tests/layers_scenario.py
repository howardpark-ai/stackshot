"""Scenario test for the layers of the package (Tue Nov 10th 2026) — the import graph of stackshot/ read with the ast module, no import is executed, no server, no network.

The package has four layers (CONTRIBUTING.md, *Layout and dependencies*) and imports that point down only:

    surface   web/
    service   service/                                                             (sits between the surface and the domain)
    domain    model/ waits/ projects/ router/ anchors/ fleet/ github/ notify/      (notify/ not yet existing)
    core      core/

audit/, tools/ and the command line (cli.py, __main__.py) sit outside the layers: they may import any layer, and nothing below the surface imports them
(web/ reads audit/ today; paths.py is the one root module every layer may import).

This suite starts with what already holds: it measures the package's imports with the AST (every `import` and `from ... import`, relative ones resolved,
those inside a function body too, and `__import__("stackshot....")` or `importlib.import_module("stackshot....")` with a literal argument) and fails
  * on an import from a lower layer to a higher one that ALLOWED_TODAY does not list, and on a listed file that imports more names of a module than its entry says;
  * on an import of audit/, tools/, the command line or a root module from core/, the domain packages or service/ (beyond paths.py);
  * on an import of anything but the bare package in paths.py itself, which every layer may import.
ALLOWED_TODAY is the measured list of what points the wrong way today, keyed by the importing file and the module it imports, each with its count of imported names (`from a import b, c` counts two) and the
structure change that removes it; an entry whose import is gone must be deleted (or its count lowered), so the list only shrinks. The packages named in
CONTRIBUTING.md's first principle must be exactly the ones in LAYERS and UNLAYERED below.
A literal relative `import_module(".render", "stackshot.web")` is resolved against its literal package argument.
Not seen: an import whose argument is not a literal string (a name, a format), a relative import_module whose package is not a literal, and a name reached by
attribute from a module that imported it.

    tests/run-suite layers        → exit 0 / 1"""
import ast, os, pathlib, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:900]}")

# the layers, top to bottom: a module may import a module of its own layer or a lower one, never a higher one
LAYERS = [("surface", ("web",)),
          ("service", ("service",)),
          ("domain", ("model", "waits", "projects", "router", "anchors", "fleet", "github", "notify")),      # notify/ not yet existing
          ("core", ("core",))]
RANK = {area: len(LAYERS) - i for i, (_, areas) in enumerate(LAYERS) for area in areas}      # higher number = higher layer
LAYER = {area: name for name, areas in LAYERS for area in areas}
UNLAYERED = ("audit", "tools")          # reports and tools that read the package; with the command line they sit outside the layers
ROOT_OK = ("stackshot", "stackshot.paths")      # the root modules a layer below the surface may import: the package itself and paths.py

# What points the wrong way today (measured Tue Nov 10th 2026): (importing file, module it imports) → (how many imported names, the structure change
# that removes it). The two in core/config.py and the one in projects/project_restore.py are lazy imports inside a function; model/ask_read's is at module level.
ALLOWED_TODAY = {
    ("stackshot/core/config.py", "stackshot.github.ghsync"): (1, "the passes move to service/: stall_item_answers, which reads an item through github/ghsync, leaves core/ with the stall pass for service/stall.py"),
    ("stackshot/core/config.py", "stackshot.waits.stall"): (2, "the passes move to service/: stall_auth and stall_notes, which call waits/stall, leave core/ with the stall pass for service/stall.py"),
    ("stackshot/model/ask_read.py", "stackshot.web.render"): (1, "the domain moves: the ask's parser (web/render.parse_ask) moves under model/ with the ask rules"),
    ("stackshot/projects/project_restore.py", "stackshot.web.whatschanged"): (1, "the domain moves: the day wording (web/whatschanged.day_words) moves down to core/ beside the clock"),
}


def module_map(root):
    """{dotted module: (path relative to the checkout, is a package's __init__)} for every .py under root/stackshot"""
    out = {}
    for p in sorted((pathlib.Path(root) / "stackshot").rglob("*.py")):
        parts = list(p.relative_to(root).with_suffix("").parts)
        init = parts[-1] == "__init__"
        if init: parts.pop()
        out[".".join(parts)] = (p.relative_to(root).as_posix(), init)
    return out

def area_of(mod, mods):
    """the first package under stackshot a module sits in ('web' for stackshot.web.server and for stackshot.web), None for the root modules"""
    s = mod.split(".")
    if len(s) == 1 or (len(s) == 2 and not mods[mod][1]): return None
    return s[1]

def imports_of(mod, init, src, mods):
    """the modules of the package a source imports: [(line, dotted module)]; a literal __import__("stackshot.x") or import_module("stackshot.x") counts"""
    pkg = mod if init else mod.rsplit(".", 1)[0] if "." in mod else mod
    found = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            cands = [[a.name] for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg.split(".")
                base = base[:len(base) - (n.level - 1)]
                b = ".".join(base + ([n.module] if n.module else []))
            else:
                b = n.module or ""
            cands = [[f"{b}.{a.name}", b] for a in n.names]      # a name that is a module of the package, else the module it comes from
        elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) \
                and (getattr(n.func, "id", None) in ("__import__", "import_module") or getattr(n.func, "attr", None) == "import_module"):
            v = n.args[0].value
            if v.startswith("."):      # import_module(".render", "stackshot.web"): resolved against the literal package, as a relative import is
                pk = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str) \
                    else next((k.value.value for k in n.keywords if k.arg == "package" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)), None)
                if pk is None: continue
                lv = len(v) - len(v.lstrip(".")); base = pk.split(".")
                v = ".".join(base[:len(base) - (lv - 1)] + ([v[lv:]] if v[lv:] else []))
            cands = [[v]]
        else:
            continue
        for c in cands:
            hit = next((t for t in c if t in mods), None)
            if hit is None and c and c[0].startswith("stackshot."):      # `import stackshot.x.y` of a module the map does not hold: its nearest package
                t = c[0]
                while "." in t and t not in mods: t = t.rsplit(".", 1)[0]
                hit = t if t in mods else None
            if hit: found.append((n.lineno, hit))
    return found

def graph(sources):
    """[(importing file, importing area, line, imported module, imported area)] for every import of the package by itself; sources = {dotted module: (path, is init, text)}"""
    mods = {m: (p, i) for m, (p, i, _) in sources.items()}
    return [(path, area_of(m, mods), line, t, area_of(t, mods))
            for m, (path, init, text) in sources.items() for line, t in imports_of(m, init, text, mods)]

def upward(g):
    """{(importing file, imported module): [lines]} for every import from a layer to a higher one"""
    out = {}
    for path, a, line, t, b in g:
        if a in RANK and b in RANK and RANK[b] > RANK[a]: out.setdefault((path, t), []).append(line)
    return out

def outward(g):
    """{(importing file, imported module): [lines]} for every import of audit/, tools/ or a root module (cli, __main__ ...) from core/, the domain or service/, paths.py aside"""
    out = {}
    for path, a, line, t, b in g:
        if a in RANK and a != "web" and (b is None or b in UNLAYERED) and t not in ROOT_OK: out.setdefault((path, t), []).append(line)
    return out

def paths_imports(g):
    """the modules of the package that paths.py imports, the bare package aside"""
    return {t for path, _, _, t, _ in g if path == "stackshot/paths.py"} - {"stackshot"}

# ---- the checker itself, on a small package of its own: an upward import is found whatever its form
fake = {"stackshot": ("stackshot/__init__.py", True, ""),
        "stackshot.paths": ("stackshot/paths.py", False, "import stackshot\nfrom stackshot.web import page\n"),
        "stackshot.cli": ("stackshot/cli.py", False, "from stackshot.web import page\n"),
        "stackshot.core": ("stackshot/core/__init__.py", True, ""),
        "stackshot.core.low": ("stackshot/core/low.py", False, "import json\nfrom stackshot import paths\nfrom . import peer\n\ndef f():\n    from stackshot.web import page\n"),
        "stackshot.core.peer": ("stackshot/core/peer.py", False, "import stackshot.model.rules\n"),
        "stackshot.core.dyn": ("stackshot/core/dyn.py", False, "import importlib\nx = __import__('stackshot.web.page')\ny = importlib.import_module('stackshot.model.rules')\nz = __import__('json')\nw = importlib.import_module(name)\nv = importlib.import_module('.page', 'stackshot.web')\nu = importlib.import_module('.page', name)\nt = importlib.import_module('.page', package='stackshot.web')\ns = importlib.import_module('.page', package=name)\n"),
        "stackshot.core.multi": ("stackshot/core/multi.py", False, "from stackshot.web.page import f, g\n"),
        "stackshot.core.out": ("stackshot/core/out.py", False, "from stackshot.tools import cap\nfrom stackshot import cli\nimport stackshot.audit.report\nfrom stackshot import paths\n"),
        "stackshot.model": ("stackshot/model/__init__.py", True, ""),
        "stackshot.model.rules": ("stackshot/model/rules.py", False, "from stackshot.core import low\nfrom ..web import page as p\nfrom stackshot.service import write\n"),
        "stackshot.service": ("stackshot/service/__init__.py", True, ""),
        "stackshot.service.write": ("stackshot/service/write.py", False, "from stackshot.web import page\nfrom stackshot.model import rules\nfrom stackshot.core import low\n"),
        "stackshot.web": ("stackshot/web/__init__.py", True, ""),
        "stackshot.web.page": ("stackshot/web/page.py", False, "from stackshot.model import rules\nfrom stackshot.core.low import f\nfrom stackshot.audit import report\nfrom stackshot.service import write\n"),
        "stackshot.tools": ("stackshot/tools/__init__.py", True, ""),
        "stackshot.tools.cap": ("stackshot/tools/cap.py", False, "from stackshot.core import low\n"),
        "stackshot.audit": ("stackshot/audit/__init__.py", True, ""),
        "stackshot.audit.report": ("stackshot/audit/report.py", False, "from stackshot.web import page\n")}
fg = graph(fake)
got = upward(fg)
check("the checker finds an upward import in a function body, a relative one, a plain `import a.b`, a from-import of a module, and a literal __import__ or import_module (a relative one too, its package positional or by keyword)",
      set(got) == {("stackshot/core/low.py", "stackshot.web.page"), ("stackshot/core/peer.py", "stackshot.model.rules"), ("stackshot/core/dyn.py", "stackshot.web.page"),
                   ("stackshot/core/dyn.py", "stackshot.model.rules"), ("stackshot/model/rules.py", "stackshot.web.page"), ("stackshot/core/multi.py", "stackshot.web.page"),
                   ("stackshot/service/write.py", "stackshot.web.page"), ("stackshot/model/rules.py", "stackshot.service.write")}, got)
check("... a `from a import b, c` counts both names, so a listed file cannot add a name unseen", got[("stackshot/core/multi.py", "stackshot.web.page")] == [1, 1], got.get(("stackshot/core/multi.py", "stackshot.web.page")))
check("... the layer order is exercised: service/ reaching web/ and the domain reaching service/ point up, web/ reaching service/ and service/ reaching the domain or core point down",
      ("stackshot/service/write.py", "stackshot.web.page") in got and ("stackshot/model/rules.py", "stackshot.service.write") in got
      and ("stackshot/web/page.py", "stackshot.service.write") not in got and not any(k[0] == "stackshot/service/write.py" and k[1] != "stackshot.web.page" for k in got), got)
check("... and not a downward one, one inside a layer, one from or to a package outside the layers, a non-package __import__ or a non-literal import_module",
      ("stackshot/web/page.py", "stackshot.model.rules") not in got and ("stackshot/audit/report.py", "stackshot.web.page") not in got and ("stackshot/cli.py", "stackshot.web.page") not in got
      and len([k for k in got if k[0] == "stackshot/core/dyn.py"]) == 2 and got[("stackshot/core/dyn.py", "stackshot.web.page")] == [2, 6, 8], got)
out = outward(fg)
check("the checker finds an import of tools/, the command line or audit/ from a layer below the surface, and lets paths.py and web/'s own use of audit/ be",
      set(out) == {("stackshot/core/out.py", "stackshot.tools.cap"), ("stackshot/core/out.py", "stackshot.cli"), ("stackshot/core/out.py", "stackshot.audit.report")}, out)

check("the checker finds what paths.py imports of the package, the bare package aside", paths_imports(fg) == {"stackshot.web.page"}, paths_imports(fg))

# ---- the package
sources = {}
for m, (path, init) in module_map(STACK).items():
    sources[m] = (path, init, (pathlib.Path(STACK) / path).read_text(encoding="utf-8"))
real_mods = {m: (p, i) for m, (p, i, _) in sources.items()}
g = graph(sources)
found = upward(g)
check("the scan reads the whole package: over 150 modules, and a few hundred imports between layered areas", len(sources) > 150 and sum(1 for _, a, _, _, b in g if a in RANK and b in RANK) > 300, len(sources))

areas = sorted({area_of(m, real_mods) for m in sources} - {None})
check("every package under stackshot/ is a named layer or listed outside the layers (a new package says where it stands)", all(a in RANK or a in UNLAYERED for a in areas), [a for a in areas if a not in RANK and a not in UNLAYERED])

LAYER_OF_FILE = {p: LAYER[area_of(m, real_mods)] for m, (p, _, _) in sources.items() if area_of(m, real_mods) in RANK}
AREA_OF_MODULE = {t: b for _, _, _, t, b in g}
def new_between(src_layer, dst_layers):
    return {k: v for k, v in found.items() if k not in ALLOWED_TODAY and LAYER_OF_FILE[k[0]] == src_layer and LAYER[AREA_OF_MODULE[k[1]]] in dst_layers}
check("core/ imports nothing from the domain or web layers, beyond ALLOWED_TODAY", not new_between("core", ("domain", "service", "surface")), new_between("core", ("domain", "service", "surface")))
check("the domain packages import nothing from web/ or service/, beyond ALLOWED_TODAY", not new_between("domain", ("service", "surface")), new_between("domain", ("service", "surface")))
check("service/ imports nothing from web/", not new_between("service", ("surface",)), new_between("service", ("surface",)))
unlisted = {k: v for k, v in found.items() if k not in ALLOWED_TODAY}
check("no import points up from a lower layer to a higher one that ALLOWED_TODAY does not list", not unlisted, unlisted)
more = {k: (len(found[k]), ALLOWED_TODAY[k][0], found[k]) for k in ALLOWED_TODAY if k in found and len(found[k]) > ALLOWED_TODAY[k][0]}
check("... and a listed file does not import more names of the same module than its entry says", not more, more)
stale = {k: (len(found.get(k, ())), ALLOWED_TODAY[k][0]) for k in ALLOWED_TODAY if len(found.get(k, ())) < ALLOWED_TODAY[k][0]}
check("ALLOWED_TODAY lists only imports that still exist: an entry whose import is gone is deleted, or its count lowered (the list only shrinks)", not stale, stale)
check("ALLOWED_TODAY is exactly what the scan finds today (every entry names the work that removes it)",
      {k: len(v) for k, v in found.items()} == {k: v[0] for k, v in ALLOWED_TODAY.items()} and all(v[1] for v in ALLOWED_TODAY.values()), sorted(set(found) ^ set(ALLOWED_TODAY)))
o = outward(g)
check("core/, the domain packages and service/ import nothing of audit/, tools/, the command line or a root module (paths.py aside)", not o, o)

pi = paths_imports(g)
check("paths.py, the one root module every layer may import, imports nothing of the package but the bare package", not pi, sorted(pi))

# ---- the rulebook and the suite name the same packages: the first principle of CONTRIBUTING.md
contrib = pathlib.Path(STACK, "CONTRIBUTING.md").read_text(encoding="utf-8")
lines = contrib.split("\n")
start = next((i for i, l in enumerate(lines) if l.startswith("1. **Four layers")), None)
end = next((i for i in range(start + 1, len(lines)) if re.match(r"\d+\. \*\*", lines[i])), len(lines)) if start is not None else 0
named = set(re.findall(r"`(\w+)/`", "\n".join(lines[start:end]))) if start is not None else set()
want = set(RANK) | set(UNLAYERED)
check("the packages CONTRIBUTING.md's first principle (its whole paragraph) names are exactly the suite's layers and the packages outside them", start is not None and named == want,
      f"principle 1 found: {start is not None}; names in CONTRIBUTING but not in the suite: {sorted(named - want)}; in the suite but not named in CONTRIBUTING: {sorted(want - named)}")

print(("ok" if not fails else "FAILED") + f": layers scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
