"""Scenario test for the puller reading stackshot.toml again when it changes (puller 13; stdlib only, no server, no network): a client box's puller runs for days, and
a setting switched on in the file (`[client] mirror_server_state`) used to wait for a restart. Once per poll cycle it now compares the file's signature (the file a link
leads to, and the resolved path) with the last one seen and calls config.reload() when it differs.

Covers: an unchanged file calls nothing; a file reached through a link whose target is rewritten in place, replaced by a rename, or whose link is pointed at another file
is reloaded once, and the setting reads the new value at the next gate (mirror_state: off, then on); the log line names the live keys that changed, or says no live setting
changed; a broken file keeps the old config, moves the signature on, logs one line and is not tried again at the next cycle, and the corrected file loads; a file that
vanishes (a dangling link) is skipped with the signature kept and never crashes, and the same content back in a new file is read; a puller file re-run in the same process (runpy, as _entry does) reloads a change made since the config was loaded, once, and another reload (SIGHUP) advances the signature the puller compares with; the loop (main) calls it every cycle, after
the poll and before the mirror, and a failure inside it never reaches the loop; the puller's version moved, so running pullers reload.

    tests/run-suite puller_config     → exit 0 / 1"""
import contextlib, io, os, pathlib, re, runpy, sys
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
