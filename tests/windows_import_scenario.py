"""Scenario test for the modules a Windows box runs: the puller (stackshot/fleet/puller.py) must import where the POSIX-only standard-library modules do not exist — no server, no network.

A Windows machine runs the puller as a scheduled task, and a self-update reloads it from a fresh checkout. A top-level `import fcntl` (or pwd, grp, termios, resource ...) in any module the puller imports raises
ModuleNotFoundError there: the reload fails and the Machines card says "update failed". Each check starts a fresh interpreter whose import system refuses those modules the way Windows does (a meta-path finder that raises
ModuleNotFoundError for them), then imports the puller and every module it loaded:
  1  the control: with the finder in place `import fcntl` fails, and a plain interpreter still has it (so the finder is what stops it)
  2  `import stackshot.fleet.puller` succeeds with the POSIX-only modules refused, and so does every module the import loaded (a module that loads only on a call is the next check's)
  3  the fleet modules a client box may load beyond the puller (fleet/inbox.py, inbox_holds.py, clients.py, push.py) import too, and their file lock is skipped without fcntl
  4  stackshot.core.xlock, which the puller reaches through core/agentbox.py, falls back to its thread lock alone without fcntl: `enabled()` is false and an XLock can be taken, nested and released
  5  with the POSIX-only modules present nothing changed: xlock.enabled() is true and its flock path is the one in use (fcntl is the real module)

    tests/run-suite windows_import        -> exit 0 / 1"""
import os, pathlib, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="winimport-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:900]}")

ENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "STACKSHOT_"))}
ENV.update(HOME=str(T), XDG_CONFIG_HOME=str(T / "cfg"), XDG_STATE_HOME=str(T / "state"), XDG_DATA_HOME=str(T / "data"), PYTHONDONTWRITEBYTECODE="1")

PRELUDE = f"""
import sys
sys.path.insert(0, {STACK!r})
import importlib.abc
BLOCKED = {{"fcntl", "pwd", "grp", "termios", "resource", "pty", "syslog"}}
class NoPosix(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
for m in BLOCKED:
    sys.modules.pop(m, None)
sys.meta_path.insert(0, NoPosix())
"""

def run(code, blocked=True):
    pre = PRELUDE if blocked else f"import sys\nsys.path.insert(0, {STACK!r})\n"
    p = subprocess.run([sys.executable, "-I", "-c", pre + code], env=ENV, cwd=tmp, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()

rc, out = run("import fcntl")
rc2, out2 = run("import fcntl; print('has fcntl')", blocked=False)
check("control: the finder refuses fcntl, and an unblocked interpreter has it", rc != 0 and "No module named 'fcntl'" in out and rc2 == 0, (rc, out, rc2, out2))

rc, out = run("""
import stackshot.fleet.puller
mine = sorted(m for m in sys.modules if m == "stackshot" or m.startswith("stackshot."))
bad = []
import importlib
for m in mine:
    try: importlib.import_module(m)
    except ModuleNotFoundError as e: bad.append((m, str(e)))
assert "stackshot.fleet.puller" in mine
print("loaded", len(mine), "bad", bad)
sys.exit(1 if bad else 0)
""")
check("the puller and every module it loaded import with fcntl, pwd, grp, termios, resource, pty and syslog refused", rc == 0 and "bad []" in out, out)

rc, out = run("""
import importlib
for m in ("inbox", "inbox_holds", "clients", "push"):
    mod = importlib.import_module("stackshot.fleet." + m)
    assert mod.fcntl is None, m
print("fleet modules ok")
""")
check("fleet/inbox.py, inbox_holds.py, clients.py and push.py import with fcntl refused", rc == 0 and "fleet modules ok" in out, out)

rc, out = run("""
from stackshot.core import xlock
assert xlock.fcntl is None, xlock.fcntl
assert xlock.enabled() is False
a = xlock.XLock("windows-import-probe")
with a:
    with a:
        assert xlock.holds("windows-import-probe")
assert not xlock.holds("windows-import-probe")
print("thread lock only")
""")
check("xlock without fcntl: enabled() is false and an XLock is taken, nested and released on its thread lock", rc == 0 and "thread lock only" in out, out)

rc, out = run("""
from stackshot.core import xlock
import fcntl
assert xlock.fcntl is fcntl
print("flock path")
""", blocked=False)
check("xlock with fcntl present binds the real module (the POSIX path is unchanged)", rc == 0 and "flock path" in out, out)

print(("ok" if not fails else "FAILED") + f": windows import scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
