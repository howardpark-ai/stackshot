"""Scenario test for the end of the server-structure series: what web/server.py no longer holds of the write path. The source is read with the ast module; nothing is imported or run.

The write path (create, update, close and the telling of who hears a write) runs from service/. It used to keep its per-write state in thread-locals on the web module and
to reach the notices through hooks. This suite holds what is true now:

  1  flags       no thread-local is made in web/ (a `threading.local` call or reference), the five per-write flags the gates and the services read are on service/writes.py, the telling's four
                 are on service/telling.py, and no other service module makes one
  2  tables      the five hook tables the server installs are installed at import, at the top of the module (not inside a function), once each
  3  values      what a table takes as a plain value (not a function, not a late lookup) is a constant of the module that cannot change after the install, so a copy taken at the install cannot go stale
  4  telling     no table of a service module holds a field that the telling answers: create, gates and update call service/telling.py on the module

    tests/run-suite server_write_free    -> exit 0 / 1"""
import ast, os, pathlib, re, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:900]}")

PKG = pathlib.Path(STACK, "stackshot")
def parse(rel): return ast.parse((PKG / rel).read_text(encoding="utf-8"))
def is_local(n): return isinstance(n, ast.Attribute) and n.attr == "local" and isinstance(n.value, ast.Name) and n.value.id == "threading"
def locals_made(tree):
    """The module-level names assigned a `threading.local()`."""
    return sorted(t.id for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and is_local(n.value.func) for t in n.targets if isinstance(t, ast.Name))

# ---------------------------------------------------------------- 1. flags
in_web = [f"{p.name}:{n.lineno}" for p in sorted(PKG.glob("web/*.py")) for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))) if is_local(n)]
check("1 no thread-local is made or named in web/ (the per-write flags left the server)", not in_web, in_web)
check("1 the flags the gates and the services read are on service/writes.py", locals_made(parse("service/writes.py")) == ["CLOSE_TOOL", "QUESTION", "REFORMAT", "SESSION_NEXT", "TERMINAL_ROW"], locals_made(parse("service/writes.py")))
check("1 the telling's own are on service/telling.py", locals_made(parse("service/telling.py")) == ["CLOSE_WAS", "FRONT_HINT", "HO_STATE", "MENTIONED"], locals_made(parse("service/telling.py")))
others = {p.name: locals_made(ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(PKG.glob("service/*.py")) if p.name not in ("writes.py", "telling.py")}
check("1 no other service module keeps one", not any(others.values()), {k: v for k, v in others.items() if v})

# ---------------------------------------------------------------- 2. tables
SERVER = parse("web/server.py")
TABLES = ("_writes", "_telling", "_create_svc", "_gates", "_update_svc")
installs = [(n, n.value.func.value.id) for n in SERVER.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "install"
            and isinstance(n.value.func.value, ast.Name)]
check("2 the server installs the five tables, each once, at the top of the module", sorted(t for _n, t in installs) == sorted(TABLES), [t for _n, t in installs])
inside = [n.lineno for fn in ast.walk(SERVER) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(fn)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "install" and isinstance(n.func.value, ast.Name) and n.func.value.id in TABLES]
check("2 …and no function of the server installs one (a table is never replaced while the server runs)", not inside, inside)

# ---------------------------------------------------------------- 3. values
def plain_entries(call):
    """The keyword entries of a table's constructor that are a bare name (not a lambda, not a late lookup, not a call)."""
    return [(kw.arg, kw.value.id) for kw in call.keywords if isinstance(kw.value, ast.Name)]
captured = {}
for node, tab in installs:
    args = node.value.args
    if args and isinstance(args[0], ast.Call):
        for field, name in plain_entries(args[0]): captured.setdefault(name, []).append(f"{tab}.{field}")
module_values = {}
for n in SERVER.body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name): module_values[t.id] = n.value
    elif isinstance(n, ast.ImportFrom):
        for a in n.names: module_values[a.asname or a.name] = None
IMMUTABLE = (ast.Constant, ast.Tuple, ast.JoinedStr, ast.BinOp)
unsafe = {name: ast.dump(module_values[name])[:60] for name in captured if name in module_values and module_values[name] is not None and not isinstance(module_values[name], IMMUTABLE)}
missing = sorted(name for name in captured if name not in module_values)
check("3 every value a table captures is defined on the server module", not missing, missing)
check("3 every value a table captures at the install is a string, a tuple or a number (a name defined by an import is its own module's constant), so it cannot change after it", not unsafe, unsafe)
expected = {"_ASK_NONE", "_SUBJECT_TAGGED", "_BASIS_WORDS", "_CHECK_HOW", "_CLOSE_REFUSAL", "_MODEL_PAGE", "OUTCOMES", "_RELAUNCH"}
check("3 the values captured are the eight the tool text and the gates share (a ninth is a decision: say here why it cannot go stale)", set(captured) == expected, sorted(set(captured) ^ expected))

# ---------------------------------------------------------------- 4. telling
telling_public = {n.name for n in parse("service/telling.py").body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} - {"install"}
held = {}
for rel in ("service/create.py", "service/gates.py", "service/update.py"):
    for n in parse(rel).body:
        if isinstance(n, ast.ClassDef) and n.name == "Hooks":
            held[rel] = sorted(a.target.id for a in n.body if isinstance(a, ast.AnnAssign) and isinstance(a.target, ast.Name) and a.target.id in telling_public)
check("4 no table of create, gates or update holds a field named for a telling function (they call service/telling.py on the module)", not any(held.values()), held)
used = {rel: sorted({n.attr for n in ast.walk(parse(rel)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "_telling"}) for rel in ("service/create.py", "service/gates.py", "service/update.py")}
check("4 each of the three services calls the telling on its module, and every name it takes is public there", all(used.values()) and not [a for v in used.values() for a in v if a not in telling_public and not a.isupper() and a not in ("CLOSE_WAS",)], used)

print(f"server write free scenario: {len(ran) - len(fails)}/{len(ran)} checks")
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: server write free scenario, {len(ran)} checks")
