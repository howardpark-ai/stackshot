"""Scenario test for the layers of the package (Tue Nov 10th 2026) — the import graph of stackshot/ read as text, no import side effects, no server, no network.

The server structure plan (CONTRIBUTING.md, *Layers*) has four layers and imports that point down only:

    surface   web/                                                                 (service/ sits between them once it exists)
    service   service/                                                             (not yet existing)
    domain    model/ waits/ projects/ router/ anchors/ fleet/ github/ notify/
    core      core/

This suite starts with what already holds: it measures the package's imports with the AST (every `import` and `from ... import`, relative ones resolved,
those inside a function body too) and fails on an import from a lower layer to a higher one that ALLOWED_TODAY does not list. ALLOWED_TODAY is the
measured list of what points the wrong way today, each with the work of the plan that removes it; an entry whose import is gone must be deleted, so the list
only shrinks. Packages outside the layers (audit/, tools/ and the root modules cli, paths, __main__) are neither checked as importers nor as targets.
Imports of a module by a string (importlib) are not seen; there is none in the layered packages.

    tests/run-suite layers        → exit 0 / 1"""
import ast, os, pathlib, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:900]}")

# the layers, top to bottom: a module may import a module of its own layer or a lower one, never a higher one
LAYERS = [("surface", ("web",)),
          ("service", ("service",)),
          ("domain", ("model", "waits", "projects", "router", "anchors", "fleet", "github", "notify")),
          ("core", ("core",))]
RANK = {area: len(LAYERS) - i for i, (_, areas) in enumerate(LAYERS) for area in areas}      # higher number = higher layer
LAYER = {area: name for name, areas in LAYERS for area in areas}
UNLAYERED = ("audit", "tools")          # reports and tools that read the package; not part of the layers

# What points the wrong way today (measured Tue Nov 10th 2026): (importing file, layer-area it imports) → the work of the server structure plan that removes it.
# Three of the four are lazy imports inside a function (config's two and project_restore's); the last two are the only ones from the domain up to web/.
ALLOWED_TODAY = {
    ("stackshot/core/config.py", "github"): "work 5 (passes): stall_item_answers, which reads an item through github/ghsync, leaves core/ with the stall pass for service/stall.py",
    ("stackshot/core/config.py", "waits"): "work 5 (passes): stall_auth, which calls waits/stall, leaves core/ with the stall pass for service/stall.py",
    ("stackshot/model/ask_read.py", "web"): "work 6 (domain moves): the ask's parser (web/render.parse_ask) moves under model/ with the ask rules",
    ("stackshot/projects/project_restore.py", "web"): "work 6 (domain moves): the day wording (web/whatschanged.day_words) moves down to core/ beside the clock",
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
    """the modules of the package a source imports: [(line, dotted module)]"""
    pkg = mod if init else mod.rsplit(".", 1)[0] if "." in mod else mod
    found = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            cands = [[(a.name)] for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg.split(".")
                base = base[:len(base) - (n.level - 1)]
                b = ".".join(base + ([n.module] if n.module else []))
            else:
                b = n.module or ""
            cands = [[f"{b}.{a.name}", b] for a in n.names]      # a name that is a module of the package, else the module it comes from
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

def upward(sources):
    """{(importing file, area imported): [(line, imported module)]} for every import from a layer to a higher one; sources = {dotted module: (path, is init, text)}"""
    mods = {m: (p, i) for m, (p, i, _) in sources.items()}
    out = {}
    for m, (path, init, text) in sources.items():
        a = area_of(m, mods)
        if a not in RANK: continue
        for line, t in imports_of(m, init, text, mods):
            b = area_of(t, mods)
            if b in RANK and RANK[b] > RANK[a]:
                out.setdefault((path, b), []).append((line, t))
    return out

# ---- the checker itself, on a small package of its own: an upward import is found whatever its form
fake = {"stackshot": ("stackshot/__init__.py", True, ""),
        "stackshot.paths": ("stackshot/paths.py", False, ""),
        "stackshot.core": ("stackshot/core/__init__.py", True, ""),
        "stackshot.core.low": ("stackshot/core/low.py", False, "import json\nfrom stackshot import paths\nfrom . import peer\n\ndef f():\n    from stackshot.web import page\n"),
        "stackshot.core.peer": ("stackshot/core/peer.py", False, "import stackshot.model.rules\n"),
        "stackshot.model": ("stackshot/model/__init__.py", True, ""),
        "stackshot.model.rules": ("stackshot/model/rules.py", False, "from stackshot.core import low\nfrom ..web import page as p\nfrom stackshot.audit import report\n"),
        "stackshot.web": ("stackshot/web/__init__.py", True, ""),
        "stackshot.web.page": ("stackshot/web/page.py", False, "from stackshot.model import rules\nfrom stackshot.core.low import f\n"),
        "stackshot.audit": ("stackshot/audit/__init__.py", True, ""),
        "stackshot.audit.report": ("stackshot/audit/report.py", False, "from stackshot.web import page\n")}
got = upward(fake)
check("the checker finds an upward import in a function body, a relative one, a plain `import a.b` and a from-import of a module",
      set(got) == {("stackshot/core/low.py", "web"), ("stackshot/core/peer.py", "model"), ("stackshot/model/rules.py", "web")}, got)
check("... and not a downward one, one inside a layer, or one from or to a package outside the layers", ("stackshot/web/page.py", "model") not in got and ("stackshot/audit/report.py", "web") not in got, got)

# ---- the package
sources = {}
for m, (path, init) in module_map(STACK).items():
    sources[m] = (path, init, (pathlib.Path(STACK) / path).read_text(encoding="utf-8"))
real_mods = {m: (p, i) for m, (p, i, _) in sources.items()}
found = upward(sources)
check("the scan reads the whole package: over 150 modules, and a few hundred imports between layered areas", len(sources) > 150 and sum(1 for m, (p, i, t) in sources.items() if area_of(m, real_mods) in RANK for _ in imports_of(m, i, t, real_mods)) > 300, len(sources))

areas = sorted({area_of(m, real_mods) for m in sources} - {None})
check("every package under stackshot/ is a named layer or listed outside the layers (a new package says where it stands)", all(a in RANK or a in UNLAYERED for a in areas), [a for a in areas if a not in RANK and a not in UNLAYERED])

LAYER_OF_FILE = {p: LAYER[area_of(m, real_mods)] for m, (p, _, _) in sources.items() if area_of(m, real_mods) in RANK}
def new_between(src_layer, dst_layers):
    return {k: v for k, v in found.items() if k not in ALLOWED_TODAY and LAYER_OF_FILE[k[0]] == src_layer and LAYER[k[1]] in dst_layers}
check("core/ imports nothing from the domain or web layers, beyond ALLOWED_TODAY", not new_between("core", ("domain", "service", "surface")), new_between("core", ("domain", "service", "surface")))
check("the domain packages import nothing from web/ or service/, beyond ALLOWED_TODAY", not new_between("domain", ("service", "surface")), new_between("domain", ("service", "surface")))
check("service/ imports nothing from web/", not new_between("service", ("surface",)), new_between("service", ("surface",)))
check("no import points up from a lower layer to a higher one that ALLOWED_TODAY does not list", not {k: v for k, v in found.items() if k not in ALLOWED_TODAY}, {k: v for k, v in found.items() if k not in ALLOWED_TODAY})
check("ALLOWED_TODAY lists only imports that still exist: an entry whose import is gone is deleted (the list only shrinks)", all(k in found for k in ALLOWED_TODAY), [k for k in ALLOWED_TODAY if k not in found])
check("ALLOWED_TODAY is exactly what the scan finds today (every entry names the work that removes it)", set(found) == set(ALLOWED_TODAY) and all(ALLOWED_TODAY.values()), sorted(set(found) ^ set(ALLOWED_TODAY)))

print(("ok" if not fails else "FAILED") + f": layers scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
