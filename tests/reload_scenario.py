"""Scenario test for the config reload (board): stackshot.toml applied with SIGHUP instead of a restart — fixture data in a
temp dir, no live store, no network.

In process: config.reload() takes a valid change and every reader sees it at its next read (no restart, no module constant
left behind); a TOML syntax error, a refused key ([units] scope = "system") and a missing file keep the running config; a
RESTART_ONLY key is reported and keeps its running value; derived values (the board page's stale threshold, the page-dirs regex, the
nag wording) follow the new file. Then the real path: a server started on a free port re-reads the file on SIGHUP, publishes
the board once, logs a broken file and a restart-only key, and keeps serving through all of it. Last, the start: it binds its
port before its passes (a second server on a held port exits without a state write, the running one's roles.json untouched),
and a run outside the production checkout with no STACKSHOT_CONFIG is refused before it reads the store.

    tests/run-suite reload        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, signal, socket, subprocess, sys, tempfile, time, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="reloadtest-"); T = pathlib.Path(tmp)
CONF = T / "stackshot.toml"
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("fleet_names", f"{tmp}/session-names.tsv"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"),
                 (r"(?m)^debounce_seconds = 5", "debounce_seconds = 1"),
                 (r"(?m)^panel = true", "panel = false")):      # a server this suite starts never reads GitHub for the Runners panel
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
BASE = toml
CONF.write_text(BASE, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=str(CONF), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "RULES.md").write_text("# rules\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

def edit(text, *subs):
    for pat, rep in subs:
        text, n = re.subn(pat, rep, text); assert n == 1, pat
    return text

def reload_with(text):
    """Write the file, reload, → (result, what reload logged)."""
    CONF.write_text(text, encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = config.reload()
    return out, err.getvalue()

from stackshot.core import config; from stackshot.projects import pages; from stackshot.fleet import clients; from stackshot.fleet import fleet; from stackshot.web import server
from stackshot.web.ui import render as ui_render
from stackshot.anchors.anchorhub import core as hubcore

# ---- 1. a valid change: every reader sees it at its next read, nothing restarted
before = (server._page_slack(), clients._online(), fleet._grace(), server._publish_every(), ui_render._stale_s(), hubcore._quiet_max())
check("before: the example's values", before == (300, 600.0, 600.0, 600.0, 900, 10800), before)
check("before: plain flavor, the default page dirs", config.page_flavor() == "plain" and pages.norm("x") == "projects/x" and "edit " in server._page_how(), server._page_how())
LIVE = edit(BASE, (r"(?m)^slack_seconds = 300", "slack_seconds = 120"), (r"(?m)^online_minutes = 10", "online_minutes = 3"),
            (r"(?m)^every_minutes = 10", "every_minutes = 4"), (r'(?m)^flavor = "plain"', 'flavor = "gbrain"'),
            (r'(?m)^dirs = \["projects", "ops"\]', 'dirs = ["areas", "systems"]'), (r"(?m)^quiet_max_hold = 10800", "quiet_max_hold = 600"),
            (r"(?m)^ui_open = true", "ui_open = false"), (r"(?m)^waiting_minutes = 60", "waiting_minutes = 30"))
cfg_was = config.CFG
out, log = reload_with(LIVE)
check("valid: reload returns the live keys that changed", out == sorted(["page_rule.slack_seconds", "client.online_minutes", "publish.every_minutes", "pages.flavor",
                                                                         "pages.dirs", "anchor_hub.quiet_max_hold", "auth.ui_open", "pilot.waiting_minutes"]), out)
check("valid: CFG is a new dict, swapped whole", config.CFG is not cfg_was and config.get("page_rule", "slack_seconds") == 120)
check("valid: nothing logged for a clean reload", log == "", log)
after = (server._page_slack(), clients._online(), fleet._grace(), server._publish_every(), hubcore._quiet_max())
check("valid: the server, clients, fleet and anchor-hub read the new values at once", after == (120, 180.0, 180.0, 240.0, 600), after)
check("valid: [auth] ui_open is read at each request", server._ui_open() is False)
check("derived: the board page's stale threshold follows [publish] every_minutes", ui_render._stale_s() == 360 and ui_render._every_m() == 4.0, ui_render._stale_s())
check("derived: the page-dirs regex and a bare slug follow [pages] dirs", config.page_dirs_re() == "(?:areas|systems)" and pages.norm("x") == "areas/x"
      and re.fullmatch(config.page_dirs_re() + r"/[\w./-]+", "systems/box") and not re.fullmatch(config.page_dirs_re() + r"/[\w./-]+", "projects/box"), pages.norm("x"))
check("derived: the nag's wording follows [pages] flavor", server._page_how().startswith("dated line → add_timeline_entry") and config.page_flavor() == "gbrain", server._page_how())
out, log = reload_with(LIVE)
check("valid, unchanged: an empty list, nothing logged", out == [] and log == "", (out, log))

# a live file that still carries the retired [idle] stuck_to key is read as it is: the key is ignored, with no warning and no refusal
OLDKEY = edit(LIVE, (r"(?m)^hours = 4", 'stuck_to = "home-old"\nhours = 4'))
out, log = reload_with(OLDKEY)
check("retired key: a file that still has [idle] stuck_to loads, the key is only listed as changed, nothing reads it and nothing is logged", out == ["idle.stuck_to"] and log == "" and not hasattr(server, "_stuck_to") and server._fleet_builder() == (config.get("fleet", "operator_session") or ""), (out, log))
check("retired key: config.py check accepts the file too", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True).returncode == 0, None)
out, log = reload_with(LIVE)

# ---- 2. an invalid file keeps the running config, and says why
running = config.CFG
out, log = reload_with(LIVE.replace("[publish]", "[publish", 1))
check("bad TOML: refused (None), CFG untouched", out is None and config.CFG is running and server._page_slack() == 120, out)
check("bad TOML: the log names the file and the parse error", "config reload: " in log and str(CONF) in log and "TOMLDecodeError" in log and "kept" in log, log)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True)
check("bad TOML: config.py check refuses it too", r.returncode != 0, r.returncode)
out, log = reload_with(LIVE + '\n[units]\nscope = "system"\n')
check("failed check ([units] scope = system): refused, CFG untouched", out is None and config.CFG is running and config.get("units", "scope") is None, out)
check("failed check: the log carries config.py check's refusal line", "refused, the running config is kept" in log and '[units] scope = "system"' in log and "removed;" in log, log)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True)
check("failed check: config.py check refuses the same file", r.returncode == 1 and '[units] scope = "system"' in (r.stderr + r.stdout), (r.returncode, r.stderr[-200:]))
CONF.unlink(); err = io.StringIO()
with contextlib.redirect_stderr(err): out = config.reload()
check("missing file: refused, CFG untouched", out is None and config.CFG is running and "FileNotFoundError" in err.getvalue(), err.getvalue())

# ---- 3. a RESTART_ONLY key: reported, never applied
RS = edit(LIVE, (r"(?m)^port = 8020", "port = 9999"), (r'(?m)^owner = "the owner"', 'owner = "Someone Else"'),
          (r'(?m)^store = "[^"]*"', f'store = "{tmp}/elsewhere"'), (r'(?m)^at = \["05:00", "20:00"\]', 'at = "06:30"'),
          (r"(?m)^call_days = 1", "call_days = 2"), (r"(?m)^slack_seconds = 120", "slack_seconds = 90"))
out, log = reload_with(RS)
check("restart-only: only the live key is applied", out == ["page_rule.slack_seconds"] and server._page_slack() == 90, out)
check("restart-only: the running values stay in CFG", config.get("server", "port") == 8020 and config.get("instance", "owner") == "the owner"
      and str(config.path("paths", "store")) == f"{tmp}/store" and config.audit_at() == ["05:00", "20:00"] and config.freshness_days()["call_days"] == 1.0,
      (config.get("server", "port"), config.get("instance", "owner"), config.path("paths", "store")))
check("restart-only: what was wired at import agrees with CFG", server.OWNER == "the owner" and server.STORE == T / "store")
for k in ("instance.owner", "paths.store", "freshness.call_days"):
    check(f"restart-only: {k} is logged as waiting for the restart", f"config reload: {k} changed: takes effect at the next restart\n" in log, log)
for k in ("audit.at", "server.port"):
    check(f"restart-only: {k}, which the units carry, says install.sh too", f"config reload: {k} changed: takes effect at the next restart (after ./install.sh units)\n" in log, log)
check("restart-only: PENDING lists them", sorted(config.PENDING) == ["audit.at", "freshness.call_days", "instance.owner", "paths.store", "server.port"], config.PENDING)
out, log = reload_with(RS)
check("restart-only, unchanged file: still pending, said again, nothing applied", out == [] and "server.port changed" in log and len(config.PENDING) == 5, (out, log))
out, log = reload_with(edit(RS, (r'(?m)^\[portal\]', '[portal]\nextra = 1')))
check("restart-only: a whole section ([portal]) is covered, a new key in it too", out == [] and config.get("portal", "extra") is None
      and "portal.extra changed: takes effect at the next restart (after ./install.sh units)" in log, log)
out, log = reload_with(LIVE)
check("restart-only: back to the running values, nothing pending or logged", out == ["page_rule.slack_seconds"] and config.PENDING == [] and log == "", (out, config.PENDING, log))
out, log = reload_with(edit(LIVE, (r'(?m)^portal_identity = .*\n', "")))
check("restart-only: a key removed from the file keeps its running value too", out == [] and config.get("auth", "portal_identity") == "" and "auth.portal_identity changed" in log, log)
out, log = reload_with(edit(LIVE, (r'(?m)^operator_session = ""', 'operator_session = "sala-master"')))
check("a live key in a section that has restart-only keys is applied", out == ["fleet.operator_session"] and config.get("fleet", "operator_session") == "sala-master", out)

# ---- 4. the real path: a server on a free port, SIGHUP, no restart
CONF.write_text(BASE, encoding="utf-8"); config.reload()
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
SRV = edit(BASE, (r"(?m)^port = 8020", f"port = {PORT}"), (r"(?m)^every_minutes = 10", "every_minutes = 1440"))   # the timer publish never lands in the test
CONF.write_text(SRV, encoding="utf-8")
errf = open(T / "server.err", "w+")
proc = subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/web/server.py")], stdout=subprocess.DEVNULL, stderr=errf, cwd=STACK,
                        env={**os.environ, "STACKSHOT_CONFIG": str(CONF), "STACKSHOT_AUTH": "off"})
def up(timeout=60.0, port=None, p=None):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port or PORT}/healthz", timeout=2) as r:
                return r.status == 200
        except Exception:
            if (p or proc).poll() is not None: return False
            time.sleep(0.3)
    return False
def logged(text, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        errf.seek(0); body = errf.read()
        if text in body: return True
        time.sleep(0.2)
    errf.seek(0); return False
def hup(text):
    CONF.write_text(text, encoding="utf-8"); proc.send_signal(signal.SIGHUP)
try:
    check("server: up on its port", up(), (T / "server.err").read_text()[-600:])
    site = T / "board.md"
    check("server: no board published before the reload (the timer waits for its mark)", not site.exists())
    hup(edit(SRV, (r'(?m)^flavor = "plain"', 'flavor = "gbrain"')))
    check("server SIGHUP, valid: the change is logged as applied", logged("config reload: pages.flavor\n"), (T / "server.err").read_text()[-600:])
    end = time.time() + 20
    while time.time() < end and not site.exists(): time.sleep(0.3)
    check("server SIGHUP, valid: the board is published once", site.exists() and site.read_text(encoding="utf-8").startswith("# stackshot"))
    check("server SIGHUP, valid: still the same process, still serving", proc.poll() is None and up(5))
    hup(edit(SRV, (r"(?m)^\[server\]", "[server")))
    check("server SIGHUP, bad TOML: logged, the running config kept", logged("not loaded, the running config is kept: TOMLDecodeError") and logged("config reload: failed, nothing changed"))
    check("server SIGHUP, bad TOML: still serving", proc.poll() is None and up(5))
    hup(edit(SRV, (r'(?m)^flavor = "plain"', 'flavor = "gbrain"'), (r'(?m)^host = "127.0.0.1"', 'host = "0.0.0.0"')))
    check("server SIGHUP, restart-only: logged as waiting for the restart", logged("config reload: server.host changed: takes effect at the next restart")
          and logged("config reload: no live setting changed; waiting for a restart: server.host"), (T / "server.err").read_text()[-800:])
    check("server SIGHUP, restart-only: still serving on the address it bound", proc.poll() is None and up(5))
    check("server: no traceback in its log", "Traceback" not in (T / "server.err").read_text(), (T / "server.err").read_text()[-1200:])
finally:
    proc.terminate()
    try: proc.wait(10)
    except subprocess.TimeoutExpired: proc.kill()

# ---- 5. the start takes its port before the store (a worktree run with no config rewrote the live roles.json
# before it found the port taken). Each fixture's registry names a keeper, so a start that ran its passes writes roles.json.
def fixture(name, port, home=None):
    """A store and state of their own under T/name, its config at `home`'s ~/.config/stackshot (or T/name/stackshot.toml) → (config, root)."""
    root = T / name
    for d in ("store/a", "fleet/a", "secrets", "touch", "brain/projects"): (root / d).mkdir(parents=True)   # no state dir: a start that reaches the store creates it
    (root / "store/projects.json").write_text(json.dumps({"pages": {"projects/x": {"session": "x-keeper"}}}))
    (root / "store/next-id").write_text("10"); (root / "store/anchors.json").write_text("{}"); (root / "RULES.md").write_text("# rules\n")
    conf = (home / ".config/stackshot/stackshot.toml") if home else root / "stackshot.toml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(edit(SRV.replace(tmp, str(root)), (rf"(?m)^port = {PORT}$", f"port = {port}")), encoding="utf-8")
    return conf, root
def files(root): return sorted(str(p.relative_to(root)) for p in root.rglob("*"))
def start(conf, root, env=None):
    e = {**os.environ, "STACKSHOT_CONFIG": str(conf), "STACKSHOT_AUTH": "off", "STACKSHOT_FLEET_DIR": str(root / "fleet")} if env is None else env
    return subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/web/server.py")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, cwd=STACK, env=e)
import shutil
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT2 = s.getsockname()[1]
confA, rootA = fixture("startA", PORT2)
procA = start(confA, rootA)
try:
    check("start, config set: the server comes up on its port", up(port=PORT2, p=procA), "")
    check("start, config set: the passes ran after the bind (roles.json written)", (rootA / "state/roles.json").is_file(), files(rootA))
    # a second server, its own fresh store, on the port A holds: exits at the bind, its store and state untouched
    confB, rootB = fixture("startB", PORT2); beforeB = files(rootB)
    pb = start(confB, rootB)
    try: _o, errB = pb.communicate(timeout=60)
    except subprocess.TimeoutExpired: pb.kill(); _o, errB = pb.communicate()
    check("second server, port held: exits 1 with one line naming the port and the config", pb.returncode == 1 and f"port 127.0.0.1:{PORT2} is taken" in errB
          and str(confB) in errB and "nothing was touched" in errB and "Traceback" not in errB, (pb.returncode, errB[-600:]))
    check("second server, port held: no state dir, no roles.json, the store as it was", not (rootB / "state").exists() and files(rootB) == beforeB, files(rootB))
    # this shape: the same config as the running server; its roles.json and store stay byte for byte
    rolesA = (rootA / "state/roles.json"); was = (rolesA.read_bytes(), rolesA.stat().st_mtime_ns); beforeA = files(rootA / "store")
    pc = start(confA, rootA)
    try: _o, errC = pc.communicate(timeout=60)
    except subprocess.TimeoutExpired: pc.kill(); _o, errC = pc.communicate()
    check("second server, same config: exits 1, the running server's roles.json and store untouched", pc.returncode == 1 and f"port 127.0.0.1:{PORT2} is taken" in errC
          and (rolesA.read_bytes(), rolesA.stat().st_mtime_ns) == was and files(rootA / "store") == beforeA, (pc.returncode, errC[-400:]))
    check("the first server still serves", procA.poll() is None and up(5, port=PORT2, p=procA))
finally:
    procA.terminate()
    try: procA.wait(10)
    except subprocess.TimeoutExpired: procA.kill()
# a run from this checkout (not the production one) with no STACKSHOT_CONFIG: refused before it reads the store. The HOME is a
# temp one whose ~/.config/stackshot/stackshot.toml points at a fixture, so even a broken guard never reaches a live store.
HD = T / "homeD"
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT3 = s.getsockname()[1]
confD, rootD = fixture("startD", PORT3, home=HD); beforeD = files(rootD)
envD = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG")}
envD.update(HOME=str(HD), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(rootD / "fleet"))
pd = start(confD, rootD, env=envD)
try: _o, errD = pd.communicate(timeout=60)
except subprocess.TimeoutExpired: pd.kill(); _o, errD = pd.communicate()
check("no STACKSHOT_CONFIG outside the production checkout: exits 2, saying to set it", pd.returncode == 2 and "STACKSHOT_CONFIG is unset" in errD
      and "not the production checkout" in errD and str(confD) in errD and "Traceback" not in errD, (pd.returncode, errD[-600:]))
check("no STACKSHOT_CONFIG: no state dir, the store as it was", not (rootD / "state").exists() and files(rootD) == beforeD, files(rootD))
check("server.py names the production checkout once, and _serve hands uvicorn the socket bound at start",
      pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8").count('PRODUCTION_CHECKOUT = "~/stackshot"') == 1
      and '"sockets": [_LISTEN]' in pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8"))

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": reload scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
os._exit(1 if fails else 0)
