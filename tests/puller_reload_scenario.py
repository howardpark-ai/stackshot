"""Scenario test for the puller's self-reload (puller 8; stdlib only, no server, no network, no live checkout): a helper that
runs for days (Windows: pythonw under a scheduled task) notices that its checkout's VERSION differs from the one it loaded and
runs the new code itself, so provision's "puller N running, checkout has M" never waits for a hand restart.

Covers: the VERSION line read from the file (never imported); a changed VERSION triggers a reload and the same one does not;
a missing, unparseable or non-compiling file (or sibling module) means no reload; the rate limit (RELOAD_MIN_GAP, one log line
per reason); end to end on a copy of the checkout in a temp dir: the loop returns RELOAD between two polls, the entry point
runs the new file with fresh modules, exactly once, and a VERSION that changes again at once is held back; a reload that cannot
be loaded is logged and recorded, and the old code goes on (a second request for the same files ends the run with 1).

    tests/run-suite puller_reload     → exit 0 / 1"""
import contextlib, io, os, pathlib, re, runpy, shutil, sys, tempfile, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = pathlib.Path(_scratch.mkdtemp(prefix="pullerreload-"))
os.environ["STACKSHOT_URL"] = "http://127.0.0.1:1"      # never contacted: every poll below is a stub
_t = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")      # a failed reload is recorded in <paths.state>: a temp one, never the host's
_t, _n = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', _t); assert _n == 1
(tmp / "stackshot.toml").write_text(_t, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = str(tmp / "stackshot.toml")
os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))

PULL = pathlib.Path("stackshot/fleet/puller.py"); CLIF = pathlib.Path("stackshot/fleet/client.py"); SAIDF = pathlib.Path("stackshot/model/said.py")
def checkout(name: str, version: str) -> pathlib.Path:
    """A copy of the checkout's package in its own directory, the puller's VERSION set to `version`."""
    d = tmp / name; d.mkdir()
    shutil.copytree(pathlib.Path(STACK, "stackshot"), d / "stackshot", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(pathlib.Path(STACK, "stackshot.example.toml"), d / "stackshot.example.toml")   # config.py loads its defaults from beside the checkout when no ~/.config/stackshot/stackshot.toml exists (CI)
    set_version(d, version)
    return d
def set_version(d, version):
    p = d / PULL; s = p.read_text(encoding="utf-8")
    s, n = re.subn(r'(?m)^VERSION = "[^"]*"', f'VERSION = "{version}"', s); assert n == 1
    p.write_text(s, encoding="utf-8")
def load(d):
    """The copy's puller.py run as a module (its HERE is the copy's directory)."""
    for m in [m for m in sys.modules if (m == "stackshot" or m.startswith("stackshot.")) and m != "stackshot.fleet.puller"]:      # as a fresh process: the copy imports its own modules, not the repo's already imported ones
        sys.modules.pop(m, None)
    return runpy.run_path(str(d / PULL), run_name="puller_under_test")
def quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **k)
    return r, out.getvalue(), err.getvalue()

sys.path.insert(0, STACK)
from stackshot.fleet import puller as real
check("the repo's puller has a VERSION on its own VERSION line", real.disk_version() == real.VERSION and real.VERSION.isdigit(), (real.disk_version(), real.VERSION))

# ---- 1. reading the VERSION: text, never an import
d = checkout("read", "41"); sys.modules.pop("puller_under_test", None)
check("disk_version reads the VERSION line", real.disk_version(str(d / PULL)) == "41")
(d / PULL).write_text('import sys\nsys.exit(99)\nVERSION = "5"\nVERSION   =   "6"\n', encoding="utf-8")
check("disk_version only reads (the file's code is never run) and takes the line at the start of a line", real.disk_version(str(d / PULL)) == "5")
(d / PULL).write_text("# VERSION = 7\n  VERSION = '8'\nx = 1\n", encoding="utf-8")
check("a file with no VERSION line of the repo's form reads as unparseable", real.disk_version(str(d / PULL)) == "")
(d / PULL).write_bytes(b"\xff\xfe\x00garbage\x00")
check("a binary file reads as unparseable", real.disk_version(str(d / PULL)) == "")
check("a missing file reads as unparseable", real.disk_version(str(tmp / "nowhere" / "puller.py")) == "")

# ---- 2. when a reload is due
def due(d, loaded, now=None):
    return quiet(real.reload_due, loaded, str(d), now)
d = checkout("due", "9"); NOW = 1_000_000.0
os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None); real._GATED.clear()
check("the same VERSION on disk: no reload", due(d, "9", NOW)[0] is False)
check("a changed VERSION on disk: reload", due(d, "8", NOW)[0] is True)
check("a newer loaded than on disk (a checkout rolled back) is a change too", due(d, "10", NOW)[0] is True)
set_version(d, "9"); good = (d / PULL).read_text(encoding="utf-8")
(d / PULL).write_text("VERSION = \n", encoding="utf-8")
check("a puller.py with no readable VERSION (mid-update): no reload", due(d, "8", NOW)[0] is False)
(d / PULL).unlink()
check("a puller.py that is missing (mid-update): no reload", due(d, "8", NOW)[0] is False)
(d / PULL).write_text(good + "\ndef broken(:\n", encoding="utf-8")
r, out, err = due(d, "8", NOW)
check("a new VERSION in a file that does not compile: no reload, and the log says why once", r is False and "does not compile" in err, err)
r2, _, err2 = due(d, "8", NOW)
check("... and says it once", r2 is False and err2 == "", err2)
(d / PULL).write_text(good, encoding="utf-8")
(d / CLIF).write_text("def broken(:\n", encoding="utf-8")
check("a sibling module (client.py) that does not compile: no reload", due(d, "8", NOW)[0] is False)
shutil.copy(pathlib.Path(STACK, CLIF), d / CLIF)
(d / SAIDF).unlink()
check("a sibling module that is missing: no reload", due(d, "8", NOW)[0] is False)
shutil.copy(pathlib.Path(STACK, SAIDF), d / SAIDF)
check("... and with the files whole again: reload", due(d, "8", NOW)[0] is True)

# ---- 3. the rate limit
gap = real.RELOAD_MIN_GAP; real._GATED.clear()
os.environ["STACKSHOT_PULLER_RELOAD_AT"] = str(NOW - 60)
r, _, err = due(d, "8", NOW)
check("a reload 60 s ago: held back, and logged", r is False and "waiting out" in err, err)
r, _, err = due(d, "8", NOW + 5)
check("held back again: not logged again", r is False and err == "", err)
os.environ["STACKSHOT_PULLER_RELOAD_AT"] = str(NOW - gap + 1)
check("one second short of the gap: still held back", due(d, "8", NOW)[0] is False)
os.environ["STACKSHOT_PULLER_RELOAD_AT"] = str(NOW - gap)
check("after the gap: reload", due(d, "8", NOW)[0] is True)
os.environ["STACKSHOT_PULLER_RELOAD_AT"] = "not a number"
check("an unreadable stamp does not block a reload", due(d, "8", NOW)[0] is True)
os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None)
check("the gap is minutes, not seconds", gap >= 300, gap)

# ---- 4. the loop, end to end on a copy of the checkout
BEFORE = {}
def run_entry(d, loaded_version, on_poll, on_disk=None):
    """Load the copy at `loaded_version`, then run its _entry with the polls stubbed: on_poll(n, ns) → called at each poll with the
    namespace of the code that polls. Returns (rc, polls as [(n, VERSION of the code polling)], reloads, log)."""
    set_version(d, loaded_version); ns = load(d)
    BEFORE["client"] = sys.modules.get("stackshot.fleet.client")   # the module the loaded code holds
    if on_disk: set_version(d, on_disk)         # the file is replaced while the loaded code runs
    polls, loads = [], []
    orig = runpy.run_path
    def spy(path, run_name=None, **k):
        g = orig(path, run_name=run_name, **k)
        if run_name == "puller_reloaded":
            loads.append(g["VERSION"])
            wire(g)
        return g
    def wire(g):
        g = g["main"].__globals__     # run_path returns a copy of the module's globals; the functions run against the live dict
        def once(reg, only, wait, dry=False):
            polls.append(g["VERSION"]); on_poll(len(polls), g); return 0
        g["once"] = once
    wire(ns)
    runpy.run_path = spy
    try:
        rc, out, err = quiet(ns["_entry"], ["puller.py", "--registry", str(d)])
    finally:
        runpy.run_path = orig
    return rc, polls, loads, out + err

def stop_after(n, then=None):
    def on_poll(i, g):
        if then: then(i, g)
        if i >= n: g["_STOP"] = True
    return on_poll

os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None)
d = checkout("same", "9")
rc, polls, loads, log = run_entry(d, "9", stop_after(3))
check("same VERSION on disk: three polls, no reload, a clean stop", rc == 0 and polls == ["9"] * 3 and loads == [], (rc, polls, loads, log))

os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None)
d = checkout("changed", "9")
ns0 = load(d); cli0 = sys.modules.get("stackshot.fleet.client")          # the copy's own client module, imported by its puller
check("the copy imports its own modules from its own directory", cli0 is not None and os.path.abspath(cli0.__file__) == str(d / CLIF), getattr(cli0, "__file__", None))
rc, polls, loads, log = run_entry(d, "9", stop_after(2), on_disk="10")
cli1 = sys.modules.get("stackshot.fleet.client")
check("changed VERSION on disk: exactly one reload, and the new code does the polling", rc == 0 and loads == ["10"] and polls == ["10", "10"], (rc, polls, loads, log))
check("the log shows the reload and the new version's polling line (what provision's check reads)", "reloading" in log and "puller 10: polling" in log and "puller 9: polling" not in log.split("reloading")[1], log)
check("the checkout's modules were loaded afresh", cli1 is not None and cli1 is not BEFORE["client"] and os.path.abspath(cli1.__file__) == str(d / CLIF), (BEFORE, cli1))
check("the reload stamps its time for the rate limit", float(os.environ.get("STACKSHOT_PULLER_RELOAD_AT", "0")) > time.time() - 60, os.environ.get("STACKSHOT_PULLER_RELOAD_AT"))

# a file that changes again at once: held back, one reload in all
os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None)
d = checkout("again", "9")
def bump_again(i, g):
    if i == 1: set_version(d, "11")
rc, polls, loads, log = run_entry(d, "9", stop_after(4, bump_again), on_disk="10")
check("rate limit end to end: VERSION changes again right after a reload → no second reload", rc == 0 and loads == ["10"] and polls == ["10"] * 4, (rc, polls, loads, log))
check("... and the log says it waits", "waiting out" in log, log)

# a reload that cannot be loaded is logged and recorded, and the old code resumes (the stub's second answer is the run's result)
import json
def last_attempt():
    return json.loads((tmp / "state/puller-updates.json").read_text(encoding="utf-8"))["attempts"][-1]
def fresh_env():
    os.environ.pop("STACKSHOT_PULLER_RELOAD_AT", None); os.environ.pop("STACKSHOT_PULLER_BAD_RELOAD", None)
fresh_env()
d = checkout("breaks", "9"); ns = load(d)
(d / PULL).write_text("def broken(:\n", encoding="utf-8")
seq = []; first = lambda argv: (seq.append(1), ns["RELOAD"] if len(seq) == 1 else 7)[1]
rc, out, err = quiet(ns["_entry"], ["puller.py"], first=first)
check("a reload that fails to load: the old code resumes (rc is the stub's second answer), the \"reload failed\" line and the traceback are logged", rc == 7 and len(seq) == 2 and "reload failed" in err and "Traceback (most recent call last)" in err and "SyntaxError" in err, (rc, seq, err))
la = last_attempt()
check("... and the failure is recorded, ok false, reason \"reload failed\"", la["ok"] is False and la["reason"].startswith("reload failed: SyntaxError") and la["what"] == "stackshot checkout", la)

# the reloaded main() itself failing at once: the same
fresh_env()
d = checkout("main-breaks", "9"); ns = load(d)
(d / PULL).write_text((d / PULL).read_text(encoding="utf-8").replace("def main(", "def main(argv, _x=None):\n    raise RuntimeError('boom')\ndef _old_main(", 1), encoding="utf-8")
seq = []; first = lambda argv: (seq.append(1), ns["RELOAD"] if len(seq) == 1 else 8)[1]
rc, out, err = quiet(ns["_entry"], ["puller.py"], first=first)
check("the reloaded main() raising at once: the old code resumes, \"reload failed: RuntimeError: boom\" and the traceback are logged", rc == 8 and len(seq) == 2 and "reload failed: RuntimeError: boom" in err and "Traceback (most recent call last)" in err, (rc, seq, err))
la = last_attempt()
check("... and recorded", la["ok"] is False and la["reason"] == "reload failed: RuntimeError: boom", la)

# a RELOAD asked for again while the files are still the marked ones (a commit that changed only pages.py after the failure): no exit, no second load
fresh_env()
d = checkout("pages-only", "9"); ns = load(d)
(d / PULL).write_text("def broken(:\n", encoding="utf-8")
seq = []; first = lambda argv: (seq.append(1), [ns["RELOAD"], ns["RELOAD"], 9][len(seq) - 1])[1]
rc, out, err = quiet(ns["_entry"], ["puller.py"], first=first)
check("RELOAD again for the files that failed to load: the run goes on with the old code (rc is the stub's third answer, never 1), the load tried once", rc == 9 and len(seq) == 3 and err.count("reload failed to load") == 1 and "a reload was asked for, but these files failed to load before" in err, (rc, seq, err))
fresh_env()

shutil.rmtree(tmp, ignore_errors=True)
check("hermetic: nothing here read the host's sala session registry (CI runs on a box that has one)", "sessions_registry" not in sys.modules)
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
