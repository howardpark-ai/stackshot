"""Scenario test for the end of the server-structure series: what web/server.py no longer holds of the write path. The source is read with the ast module; nothing is imported or run.

The write path (create, update, close and the telling of who hears a write) runs from service/. It used to keep its per-write state in thread-locals on the web module and
to reach the notices through hooks. This suite holds what is true now:

  1  flags       no thread-local is made in web/ (a `threading.local` call or reference), the five per-write flags the gates and the services read are on service/writes.py, the telling's four
                 are on service/telling.py, and no other service module makes one
  2  tables      the fourteen hook tables the server installs (the item readers', the For you rows', the save steps' and the owner's words', the write path's four, the telling's, the minute set's, the wake passes', the hand-off passes', the stall pass's, the done check's and the page-debt call's, the migrations' and the fleet events') are installed at import, at the top of the module (not inside a function), once each
  3  values      what a table takes as a plain value (not a function, not a late lookup) is a constant of the module that cannot change after the install, so a copy taken at the install cannot go stale; a late
                 lookup (`_late("name")`, a call) is a lookup by name made when the hook runs, so it captures nothing, and each one must name a function or value the server module defines; a late lookup on an
                 owner module (`_late_in(module, "name")`) is the same lookup on that module, and must name a function or value that module defines
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
TABLES = ("_writes", "_telling", "_create_svc", "_gates", "_update_svc", "_runner", "_wake_hooks", "_handoff_hooks", "_stall_hooks", "_checks_hooks", "_passes_hooks", "_foryou_hooks", "_save_hooks", "_item_read")
installs = [(n, n.value.func.value.id) for n in SERVER.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "install"
            and isinstance(n.value.func.value, ast.Name)]
check("2 the server installs the fourteen tables, each once, at the top of the module", sorted(t for _n, t in installs) == sorted(TABLES), [t for _n, t in installs])
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
# A late lookup is a call, not a bare name, so `plain_entries` leaves it out: it takes no copy at the install. What it can still get wrong is a name the server no longer defines (the hook would then fail when it runs):
# every `_late("name")` of every table, the minute set's and the wake passes' included, must name a def, a value or an import of the server module, and every `_late_in(module, "name")` a def or value of the owner module.
server_defs = {n.name for n in SERVER.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} | set(module_values)
owner_files = {(a.asname or a.name): "/".join(n.module.split(".")[1:] + [a.name]) + ".py" for n in SERVER.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("stackshot.") for a in n.names}
def late_call(v):
    """(owner alias or None, name) of a late lookup, else None."""
    if isinstance(v, ast.Call) and isinstance(v.func, ast.Name):
        if v.func.id == "_late" and v.args and isinstance(v.args[0], ast.Constant): return (None, v.args[0].value)
        if v.func.id == "_late_in" and len(v.args) == 2 and isinstance(v.args[0], ast.Name) and isinstance(v.args[1], ast.Constant): return (v.args[0].id, v.args[1].value)
    return None
late_names = {}; late_owned = {}
for node, tab in installs:
    for kw in (node.value.args[0].keywords if node.value.args and isinstance(node.value.args[0], ast.Call) else []):
        lc = late_call(kw.value)
        if lc and lc[0] is None: late_names.setdefault(lc[1], []).append(f"{tab}.{kw.arg}")
        elif lc: late_owned.setdefault(lc, []).append(f"{tab}.{kw.arg}")
check("3 every late lookup of every table names something the server module defines", bool(late_names) and not [n for n in late_names if n not in server_defs], sorted(n for n in late_names if n not in server_defs))
def owner_defs(alias):
    rel = owner_files.get(alias)
    if rel is None or not (PKG / rel).exists(): return None
    tree = parse(rel)
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} | {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
owner_missing = sorted(f"{a}.{n}" for (a, n) in late_owned if (owner_defs(a) is None or n not in owner_defs(a)))
check("3 every late lookup on an owner module (`_late_in`) names a module the server imports and something that module defines", bool(late_owned) and not owner_missing, owner_missing)
check("3 the publish functions, the page rule's refusal and its owed-writer test are looked up on their owner modules (a suite that replaces one there reaches every table), never on the server",
      {n for (a, n) in late_owned if a == "_pubmod"} == {"_publish", "_publish_now", "_publish_every"} and {n for (a, n) in late_owned if a == "_pdebts"} == {"_refuse_if_owing", "_writer_owes"}
      and not {"_publish", "_publish_now", "_publish_every", "_refuse_if_owing", "_writer_owes"} & set(late_names), (sorted(late_owned), sorted(late_names)))
runner_tab = next((n.value.args[0] for n, t in installs if t == "_runner"), None)
is_late = lambda v: late_call(v) is not None
runner_plain = [kw.arg for kw in runner_tab.keywords if not is_late(kw.value)] if isinstance(runner_tab, ast.Call) else ["no table"]
check("3 the minute set's table holds only late lookups (a tick function replaced on the server is the one the table calls), never a value copied at the install", not runner_plain, runner_plain)
wake_tab = next((n.value.args[0] for n, t in installs if t == "_wake_hooks"), None)
wake_plain = [kw.arg for kw in wake_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(wake_tab, ast.Call) else ["no table"]
check("3 the wake passes' table holds only late lookups and lambdas (a function replaced on the server is the one the passes call), never a value copied at the install", not wake_plain, wake_plain)
handoff_tab = next((n.value.args[0] for n, t in installs if t == "_handoff_hooks"), None)
handoff_plain = [kw.arg for kw in handoff_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(handoff_tab, ast.Call) else ["no table"]
check("3 the hand-off passes' table holds only late lookups and lambdas (a function replaced on the server is the one the passes call), never a value copied at the install", not handoff_plain, handoff_plain)
stall_tab = next((n.value.args[0] for n, t in installs if t == "_stall_hooks"), None)
stall_plain = [kw.arg for kw in stall_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(stall_tab, ast.Call) else ["no table"]
check("3 the stall pass's table holds only late lookups and lambdas (a function replaced on the server is the one the pass calls), never a value copied at the install", not stall_plain, stall_plain)
checks_tab = next((n.value.args[0] for n, t in installs if t == "_checks_hooks"), None)
checks_plain = [kw.arg for kw in checks_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(checks_tab, ast.Call) else ["no table"]
check("3 the done check's table holds only late lookups and lambdas (a function replaced on the server is the one the passes call), never a value copied at the install", not checks_plain, checks_plain)
passes_tab = next((n.value.args[0] for n, t in installs if t == "_passes_hooks"), None)
passes_plain = [kw.arg for kw in passes_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(passes_tab, ast.Call) else ["no table"]
check("3 the page-debt, migration and fleet-event table holds only late lookups and lambdas (a function replaced on the server is the one the passes call), never a value copied at the install", not passes_plain, passes_plain)
save_tab = next((n.value.args[0] for n, t in installs if t == "_save_hooks"), None)
save_plain = [kw.arg for kw in save_tab.keywords if not is_late(kw.value) and not isinstance(kw.value, ast.Lambda)] if isinstance(save_tab, ast.Call) else ["no table"]
check("3 the save steps' table holds only late lookups and lambdas (a function replaced on its owner is the one the steps call), never a value copied at the install", not save_plain, save_plain)
expected = {"_ASK_NONE", "_BASIS_WORDS", "_CLOSE_REFUSAL", "_MODEL_PAGE", "OUTCOMES", "_RELAUNCH"}
check("3 the values captured are the six the tool text and the gates share (an eighth is a decision: say here why it cannot go stale)", set(captured) == expected, sorted(set(captured) ^ expected))

# ---------------------------------------------------------------- 4. telling
telling_public = {n.name for n in parse("service/telling.py").body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} - {"install"}
held = {}
for rel in ("service/create.py", "service/gates.py", "service/update.py", "service/runner.py", "service/wake_hooks.py", "service/handoff_hooks.py", "service/stall_hooks.py", "service/checks_hooks.py", "service/passes_hooks.py", "service/save_hooks.py"):
    for n in parse(rel).body:
        if isinstance(n, ast.ClassDef) and n.name == "Hooks":
            held[rel] = sorted(a.target.id for a in n.body if isinstance(a, ast.AnnAssign) and isinstance(a.target, ast.Name) and a.target.id in telling_public)
check("4 no table of create, gates, update, the runner, the wake passes, the hand-off passes, the stall pass, the done check, the page-debt call, the migrations, the fleet events or the save steps holds a field named for a telling function (they call service/telling.py on the module)", not any(held.values()), held)
used = {rel: sorted({n.attr for n in ast.walk(parse(rel)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "_telling"}) for rel in ("service/create.py", "service/gates.py", "service/update.py", "service/runner.py", "service/wakes.py", "service/watching.py", "service/event_waits.py", "service/handoff.py", "service/handoff_cold.py", "service/stall.py", "service/ladder.py", "service/stall_tick.py", "service/checks.py", "service/proofs.py", "service/page_debt.py", "service/migrations.py", "service/fleet_events.py")}
check("4 each of the seventeen services calls the telling on its module, and every name it takes is public there", all(used.values()) and not [a for v in used.values() for a in v if a not in telling_public and not a.isupper() and a not in ("CLOSE_WAS",)], used)

print(f"server write free scenario: {len(ran) - len(fails)}/{len(ran)} checks")
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: server write free scenario, {len(ran)} checks")
