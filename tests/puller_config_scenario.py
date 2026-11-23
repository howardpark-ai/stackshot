"""Scenario test for the puller reading stackshot.toml again when it changes (puller 13; stdlib only, no server, no network): a client box's puller runs for days, and
a setting switched on in the file (`[client] mirror_server_state`) used to wait for a restart. Once per poll cycle it now compares the file's signature (the file a link
leads to, and the resolved path) with the last one seen and calls config.reload() when it differs.

Covers: an unchanged file calls nothing; a file reached through a link whose target is rewritten in place, replaced by a rename, or whose link is pointed at another file
is reloaded once, and the setting reads the new value at the next gate (mirror_state: off, then on); the log line names the live keys that changed, or says no live setting
changed; a broken file keeps the old config, moves the signature on, logs one line and is not tried again at the next cycle, and the corrected file loads; a file that
vanishes (a dangling link) is skipped with the signature kept and never crashes, and the same content back in a new file is read; a puller file re-run in the same process (runpy, as _entry does) reloads a change made since the config was loaded, once, and another reload (SIGHUP) advances the signature the puller compares with; the loop (main) calls it every cycle, after
the poll and before the mirror, and a failure inside it never reaches the loop; the puller's version moved, so running pullers reload.

Also covers, in the same file (the former windows_import suite; checks 1-5 of the part "windows import", which run first): the modules a Windows box runs, with no server and no network. A Windows machine runs the puller as a scheduled task, and a self-update
reloads it from a fresh checkout. A top-level `import fcntl` (or pwd, grp, termios, resource ...) in any module the puller imports raises ModuleNotFoundError there: the reload fails and the Machines card says "update failed". Each check starts a fresh
interpreter (-I, a filtered environment of its own, so the config checks' environment and modules do not reach it) whose import system refuses those modules the way Windows does (a meta-path finder that raises ModuleNotFoundError for them), then imports the puller and every module it loaded:
  w1  the control: with the finder in place `import fcntl` fails, and a plain interpreter still has it (so the finder is what stops it)
  w2  `import stackshot.fleet.puller` succeeds with the POSIX-only modules refused, and so does every module the import loaded (a module that loads only on a call is the next check's)
  w3  the fleet modules a client box may load beyond the puller (fleet/inbox.py, inbox_holds.py, clients.py, push.py) import too, and their file lock is skipped without fcntl
  w4  stackshot.core.xlock, which the puller reaches through core/agentbox.py, falls back to its thread lock alone without fcntl: `enabled()` is false and an XLock can be taken, nested and released
  w5  with the POSIX-only modules present nothing changed: xlock.enabled() is true and its flock path is the one in use (fcntl is the real module)

    tests/run-suite puller_config     → exit 0 / 1"""
import contextlib, io, os, pathlib, re, runpy, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
sys.path.insert(0, STACK)
tmp = pathlib.Path(_scratch.mkdtemp(prefix="p1491-")); REPO = tmp / "repo"; REPO.mkdir()
os.environ["STACKSHOT_URL"] = "http://127.0.0.1:1"      # a loopback address, never contacted: the mirror answers "local" when it is on, "off" when it is not
base = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
base, n = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', base); assert n == 1
base, n = re.subn(r'(?m)^mirror_server_state = false\b', 'mirror_server_state = OFF', base); assert n == 1
ON, OFF = base.replace("OFF", "true"), base.replace("OFF", "false")
LINK, REAL, OTHER = tmp / "stackshot.toml", REPO / "real.toml", REPO / "other.toml"
REAL.write_text(OFF, encoding="utf-8"); OTHER.write_text(OFF, encoding="utf-8"); LINK.symlink_to(REAL)   # the instance's file is a link into another repository, as on a fleet box
os.environ["STACKSHOT_CONFIG"] = str(LINK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

def windows_import_part():
    """The former windows_import suite: each check runs a fresh isolated interpreter (-I, its own HOME and XDG folders, cwd in its own folder, no STACKSHOT_/COVERAGE_ variables), so nothing the config checks set reaches it."""
    W = tmp / "winimport"; W.mkdir()
    ENV = {k: v for k, v in os.environ.items() if not k.startswith(("COVERAGE_", "STACKSHOT_"))}
    ENV.update(HOME=str(W), XDG_CONFIG_HOME=str(W / "cfg"), XDG_STATE_HOME=str(W / "state"), XDG_DATA_HOME=str(W / "data"), PYTHONDONTWRITEBYTECODE="1")
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
        p = subprocess.run([sys.executable, "-I", "-c", pre + code], env=ENV, cwd=str(W), capture_output=True, text=True, timeout=120)
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

windows_import_part()      # first: its interpreters are independent of this process (isolated, STACKSHOT_* filtered out of their environment)

from stackshot.fleet import puller
cfg = puller._cfg
CALLS = []; real_reload = cfg.reload
def counting_reload():
    CALLS.append(1); return real_reload()
cfg.reload = counting_reload
def rewrite(p, text, bump=True):
    """Rewrite a file in place (same inode), its mtime moved on so a coarse clock cannot hide the change."""
    st = os.stat(p); p.write_text(text, encoding="utf-8")
    if bump: os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
def tick():
    """One config_tick as the loop makes it → (answer, stdout, stderr, reload calls)."""
    CALLS.clear(); o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): r = puller.config_tick()
    return r, o.getvalue(), e.getvalue(), len(CALLS)
def gate():
    puller._MIRROR["at"] = 0.0
    return puller.mirror_state(tmp / "state")
LOGS = lambda out: [l for l in out.splitlines() if "config reload" in l]
try:
    # ---- 1. nothing changed: nothing is called
    check("start: config.py took the signature at import, before the read, and the file reads off", cfg.SIG is not None and cfg.SIG == cfg.signature() and cfg.PATH == LINK and gate() == "off", (cfg.SIG, cfg.PATH))
    r, out, err, calls = tick()
    check("unchanged: no reload, no line", r == "same" and calls == 0 and out == "" and err == "", (r, calls, out, err))
    r, out, err, calls = tick()
    check("unchanged twice: still no reload", r == "same" and calls == 0, (r, calls))

    # ---- 2. the link's target rewritten in place: reloaded once, the next gate sees the setting
    rewrite(REAL, ON)
    r, out, err, calls = tick()
    check("in place: reloaded once", r == "reloaded" and calls == 1, (r, calls, out, err))
    check("in place: the log line names the live key that changed", len(LOGS(out)) == 1 and "puller " in out and "client.mirror_server_state" in out, out)
    check("in place: the next mirror gate reads the new value (off to on, no restart)", cfg.get("client", "mirror_server_state") is True and gate() == "local", gate())
    r, out, err, calls = tick()
    check("in place: the next cycle does not reload again", r == "same" and calls == 0 and out == "", (r, calls, out))

    # ---- 3. a rename over the target (a new inode), the content with the same size as before is still seen
    new = REPO / "real.new"; new.write_text(OFF, encoding="utf-8"); os.replace(new, REAL)
    r, out, err, calls = tick()
    check("replaced by a rename: reloaded once, the setting is off again", r == "reloaded" and calls == 1 and gate() == "off", (r, calls))

    # ---- 4. the link pointed at another file (the target's own content unchanged)
    rewrite(OTHER, ON)
    check("re-pointed: nothing happens until the link moves", tick()[0] == "same")
    LINK.unlink(); LINK.symlink_to(OTHER)
    r, out, err, calls = tick()
    check("re-pointed: reloaded once, the setting reads the other file", r == "reloaded" and calls == 1 and gate() == "local", (r, calls, out))
    LINK.unlink(); LINK.symlink_to(REAL)
    r, out, err, calls = tick()
    check("re-pointed back: reloaded once, off", r == "reloaded" and calls == 1 and gate() == "off", (r, calls))

    # ---- 5. a file that changes without any live setting changing
    rewrite(REAL, OFF + "\n# a comment\n")
    r, out, err, calls = tick()
    check("a comment only: reloaded once and the line says no live setting changed", r == "reloaded" and calls == 1 and "no live setting changed" in out and len(LOGS(out)) == 1, (r, out))

    # ---- 6. a broken file: the old config stays, the signature moves, one line, no retry
    rewrite(REAL, "[client\nmirror_server_state = ")
    before = cfg.CFG
    r, out, err, calls = tick()
    check("broken: the answer is kept and reload was asked once", r == "kept" and calls == 1, (r, calls))
    check("broken: the running config is the same object, the setting is as it was", cfg.CFG is before and cfg.get("client", "mirror_server_state") is False, cfg.CFG.get("client"))
    check("broken: one line from the puller, saying the file did not load", len(LOGS(out)) == 1 and "did not load" in out, out)
    r, out, err, calls = tick()
    check("broken: the next cycle does not try again (no reload call, no line)", r == "same" and calls == 0 and out == "" and err == "", (r, calls, out, err))
    rewrite(REAL, ON)
    r, out, err, calls = tick()
    check("broken, then corrected: the new file loads", r == "reloaded" and calls == 1 and gate() == "local", (r, calls, out))

    # ---- 7. a file that vanishes: skipped, never a crash, the signature kept
    rewrite(REAL, OFF); tick(); sig = cfg.SIG
    REAL.unlink()                                       # the link now dangles: os.stat fails
    r, out, err, calls = tick()
    check("vanished: skipped, no reload, no line, the signature kept", r == "skipped" and calls == 0 and out == "" and cfg.SIG == sig, (r, calls, out))
    check("vanished: the running config still answers", cfg.get("client", "mirror_server_state") is False and gate() == "off")
    r, *_ = tick()
    check("vanished for two cycles: still skipped", r == "skipped")
    REAL.write_text(ON, encoding="utf-8")               # back, as a new file
    r, out, err, calls = tick()
    check("back as a new file: read at once", r == "reloaded" and calls == 1 and gate() == "local", (r, calls, out))
    rewrite(REAL, OFF); tick()

    # ---- 7b. the signature belongs to the config module, which a puller re-run in the same process keeps: a change made since the config was read is seen after the re-run
    rewrite(REAL, OFF); tick()
    rewrite(REAL, ON)                                   # the file changes after the config was loaded and before the puller file is run afresh (a checkout update, the 12 to 13 upgrade)
    again = runpy.run_path(os.path.join(STACK, "stackshot", "fleet", "puller.py"), run_name="puller_under_test")   # as _entry does: the file afresh, stackshot.core.config stays in sys.modules
    CALLS.clear(); o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): r = again["config_tick"]()
    check("re-run: the first tick of the re-run puller reloads once, though the file changed before it started", r == "reloaded" and len(CALLS) == 1 and len(LOGS(o.getvalue())) == 1 and gate() == "local", (r, CALLS, o.getvalue()))
    CALLS.clear()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): r = again["config_tick"]()
    check("re-run: the next tick is the same, no second reload", r == "same" and not CALLS, (r, CALLS))
    rewrite(REAL, OFF)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): cfg.reload()   # something else reloads, as SIGHUP does
    check("another reload (SIGHUP) advances the signature: the puller does not reload again", cfg.SIG == cfg.signature() and tick()[:2] == ("same", "") and gate() == "off", cfg.SIG)

    # ---- 8. the loop: once per cycle, after the poll and before the mirror; a failure inside never reaches it
    seen = []; polls = []
    real = {k: getattr(puller, k) for k in ("once", "reload_due", "keep_current", "sessions", "_mirror_safe", "config_tick")}
    def fake_once(*a, **k):
        polls.append(1)
        if len(polls) == 1: rewrite(REAL, ON)             # the operator switches the setting on during the first poll
        if len(polls) == 3: puller._STOP = True
        return 0
    def fake_mirror():
        seen.append(("mirror", gate_state())); return "done"
    gate_state = lambda: cfg.get("client", "mirror_server_state")
    puller.once, puller.reload_due, puller.keep_current, puller.sessions, puller._mirror_safe = fake_once, (lambda: False), (lambda *a, **k: None), (lambda *a, **k: []), fake_mirror
    CALLS.clear(); o, e = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): rc = puller.main(["puller.py", "--registry", str(tmp / "reg")])
    finally:
        for k, v in real.items(): setattr(puller, k, v)
        puller._STOP = False
    check("loop: three cycles ran and the loop ended in 0", rc == 0 and len(polls) == 3, (rc, polls))
    check("loop: one reload in all (the change of the first poll), seen by the mirror of the same cycle", len(CALLS) == 1 and seen[0] == ("mirror", True) and gate() == "local", (CALLS, seen))
    check("loop: one config line in the log", len(LOGS(o.getvalue())) == 1 and "client.mirror_server_state" in o.getvalue(), o.getvalue())
    rewrite(REAL, OFF); tick()
    cfg.reload = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    rewrite(REAL, ON)
    try: r, out, err, calls = tick()
    finally: cfg.reload = counting_reload
    check("a failure inside the tick is logged and never raised", r == "kept" and "boom" in err, (r, err))
    check("the puller's version moved, so running pullers reload", int(puller.VERSION) >= 13, puller.VERSION)
finally:
    cfg.reload = real_reload

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
