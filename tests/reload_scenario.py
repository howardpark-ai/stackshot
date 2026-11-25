"""Scenario tests for the config the server reads, in two parts that each run in a process of their own (formerly the suites reload and config_hosts): the reload of stackshot.toml, and the host words a setting may hold in place of a machine's name.

Part `reload` - the config reload (board): stackshot.toml applied with SIGHUP instead of a restart — fixture data in a
temp dir, no live store, no network.

In process: config.reload() takes a valid change and every reader sees it at its next read (no restart, no module constant
left behind); a TOML syntax error, a refused key ([units] scope = "system") and a missing file keep the running config; a
RESTART_ONLY key is reported and keeps its running value; derived values (the board page's stale threshold, the page-dirs regex, the
nag wording) follow the new file. Then the real path: a server started on a free port re-reads the file on SIGHUP, publishes
the board once, logs a broken file and a restart-only key, and keeps serving through all of it. Last, the start: it binds its
port before its passes (a second server on a held port exits without a state write, the running one's roles.json untouched),
and a run outside the production checkout with no STACKSHOT_CONFIG is refused before it reads the store.

Part `config_hosts` - host words (stackshot/core/config.py `host`, `get`, `reload`; [hosts] lookup, timeout, cache_seconds) — a stub lookup command written to a scratch folder, no network, no real machine.

A setting that names a machine may name a role instead, `host:<role>`; the instance says how a role is looked up. The stub logs every call (its arguments) and answers as a mode file says.

Covers: a plain value, a number, a table and a list of plain items come back as they are (the same object); `host:<role>` is resolved at the leaf of get(), each string item of a list is resolved and the plain
ones are kept, a table is not touched even when it holds a host word; `config.host()` resolves one value and returns any other unchanged; the cache (one call for many reads inside cache_seconds, a new one after it,
a role of its own each); a later failed lookup keeps the last good value and is tried again after 5 seconds, not at every read, and a recovery shows; no `[hosts] lookup`, a lookup with no {role}, a command
that is not found, a first lookup that fails, and a lookup that is a host word itself all leave the word as written (never "" and never a guess) and never raise or recurse; what a lookup may print (the first
line, stripped; an empty line, spaces inside, a colon, a leading "-" and a non-zero exit are failures); a lookup that never answers is ended within the timeout and its process is gone, and so is a child it left holding its output (the process group is killed); a lookup that prints without end is cut at 4096 bytes and ended; the lookup runs without
a shell (a template word with shell characters runs nothing, {role} is replaced inside a longer word, `~` is expanded); the role's own characters (a role with a space, a colon, `;`, `$(`, a leading `-` is no
host word and runs nothing); two threads asking one role cause one lookup, and a slow role does not hold up another; one stderr line per failure streak; reload() makes every answer due, clears the failure marks, keeps the last good hosts and takes the new lookup; each of the four
readers resolves (`[project_agent] form_machines` through the form gate's helper, `[steps] bash_host`, `[agents_box] ssh`, `[machines_panel] ssh_hosts`), and `config.py get` on the command line.

The two parts set up two different instances, and each part changes module state of the code under test that the other would meet, so each part runs in a process of its own;
the file runs them one after the other, adds their check counts and exits 1 when a part fails.

    tests/run-suite reload        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("reload", "config_hosts")


# ================================================================ part reload: the config reload, SIGHUP instead of a restart
def part_reload():
    import contextlib, io, json, logging, os, pathlib, re, signal, socket, subprocess, sys, tempfile, time, urllib.request
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="reloadtest-"); T = pathlib.Path(tmp)
    CONF = T / "stackshot.toml"
    toml = _instance.apply(_instance.base_toml())
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
    from stackshot.web import page_debts as _pdebts
    from stackshot.waits import waiting as _wt
    from stackshot.core import instance as _core_instance
    from stackshot.web import publish as _web_publish
    from stackshot.service import fleet_events as fleetev
    from stackshot.web.auth import signin as _signin
    from stackshot.core import store as _core_store
    from stackshot.web.ui import render as ui_render
    from stackshot.anchors.anchorhub import core as hubcore

    # ---- 1. a valid change: every reader sees it at its next read, nothing restarted
    before = (_pdebts._page_slack(), clients._online(), fleet._grace(), _web_publish._publish_every(), ui_render._stale_s(), hubcore._quiet_max())
    check("before: the example's values", before == (300, 600.0, 600.0, 600.0, 900, 10800), before)
    check("before: plain flavor, the default page dirs", config.page_flavor() == "plain" and pages.norm("x") == "projects/x" and "edit " in _pdebts._page_how(), _pdebts._page_how())
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
    after = (_pdebts._page_slack(), clients._online(), fleet._grace(), _web_publish._publish_every(), hubcore._quiet_max())
    check("valid: the server, clients, fleet and anchor-hub read the new values at once", after == (120, 180.0, 180.0, 240.0, 600), after)
    check("valid: [auth] ui_open is read at each request", _signin._ui_open() is False)
    check("derived: the board page's stale threshold follows [publish] every_minutes", ui_render._stale_s() == 360 and ui_render._every_m() == 4.0, ui_render._stale_s())
    check("derived: the page-dirs regex and a bare slug follow [pages] dirs", config.page_dirs_re() == "(?:areas|systems)" and pages.norm("x") == "areas/x"
          and re.fullmatch(config.page_dirs_re() + r"/[\w./-]+", "systems/box") and not re.fullmatch(config.page_dirs_re() + r"/[\w./-]+", "projects/box"), pages.norm("x"))
    check("derived: the nag's wording follows [pages] flavor", _pdebts._page_how().startswith("dated line → add_timeline_entry") and config.page_flavor() == "gbrain", _pdebts._page_how())
    out, log = reload_with(LIVE)
    check("valid, unchanged: an empty list, nothing logged", out == [] and log == "", (out, log))

    # a live file that still carries the retired [idle] stuck_to key is read as it is: the key is ignored, with no warning and no refusal
    OLDKEY = edit(LIVE, (r"(?m)^park_days = 3", 'stuck_to = "home-old"\npark_days = 3'))
    out, log = reload_with(OLDKEY)
    check("retired key: a file that still has [idle] stuck_to loads, the key is only listed as changed, nothing reads it and nothing is logged", out == ["idle.stuck_to"] and log == "" and not hasattr(server, "_stuck_to") and fleetev.fleet_builder() == (config.get("fleet", "operator_session") or ""), (out, log))
    check("retired key: config.py check accepts the file too", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True).returncode == 0, None)
    out, log = reload_with(LIVE)

    # a live file that still carries the keys that timed the computed expected-by date ([waiting] default_days and agent_hours, [idle] hours) loads as it is: nothing reads them, nothing is logged
    OLDEB = edit(LIVE, (r"(?m)^cap_days = 7", "default_days = 3\nagent_hours = 3\ncap_days = 7"), (r"(?m)^park_days = 3", "hours = 4\npark_days = 3"))
    out, log = reload_with(OLDEB)
    check("retired keys: a file that still has [waiting] default_days and agent_hours and [idle] hours loads, they are only listed as changed, and nothing is logged",
          sorted(out) == ["idle.hours", "waiting.agent_hours", "waiting.default_days"] and log == "", (out, log))
    check("retired keys: …the waiting module reads neither (its defaults hold only the cap, the basis weekday and the dated-wait minimum)", set(_wt.DEFAULTS) == {"cap_days", "cap_needs_owner", "basis_weekday", "dated_wait_min_hours"}, sorted(_wt.DEFAULTS))
    check("retired keys: …config.py check accepts the file too", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True).returncode == 0, None)
    out, log = reload_with(LIVE)

    # a live file that still carries the one ladder's retired keys ([ladder] main_hours, the old hand-up's interval, and silence) loads as it is: nothing reads them, nothing is logged
    OLDLAD = edit(LIVE, (r"(?m)^look_minutes = 30", "look_minutes = 30\nmain_hours = 4\nsilence = true"))
    out, log = reload_with(OLDLAD)
    check("retired keys: a file that still has [ladder] main_hours and silence loads, they are only listed as changed, nothing reads them and nothing is logged",
          sorted(out) == ["ladder.main_hours", "ladder.silence"] and log == "" and not hasattr(server, "_ladder_main_hours") and not any("main_hours" in n or "silence" in n for n in config.notes()), (out, log))
    check("retired keys: …config.py check accepts the file too", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True).returncode == 0, None)
    out, log = reload_with(LIVE)

    # ---- 2. an invalid file keeps the running config, and says why
    running = config.CFG
    out, log = reload_with(LIVE.replace("[publish]", "[publish", 1))
    check("bad TOML: refused (None), CFG untouched", out is None and config.CFG is running and _pdebts._page_slack() == 120, out)
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
    RS = edit(LIVE, (r"(?m)^port = 8020", "port = 9999"),
              (r'(?m)^store = "[^"]*"', f'store = "{tmp}/elsewhere"'), (r'(?m)^at = \["05:00", "20:00"\]', 'at = "06:30"'),
              (r"(?m)^call_days = 1", "call_days = 2"), (r"(?m)^slack_seconds = 120", "slack_seconds = 90"))
    RS = _instance.set_person(RS, "Someone Else")
    out, log = reload_with(RS)
    check("restart-only: only the live key is applied", out == ["page_rule.slack_seconds"] and _pdebts._page_slack() == 90, out)
    check("restart-only: the running values stay in CFG", config.get("server", "port") == 8020 and config.get("instance", "owner") == "the owner"
          and str(config.path("paths", "store")) == f"{tmp}/store" and config.audit_at() == ["05:00", "20:00"] and config.freshness_days()["call_days"] == 1.0,
          (config.get("server", "port"), config.get("instance", "owner"), config.path("paths", "store")))
    check("restart-only: what was wired at import agrees with CFG", _core_instance.OWNER == "the owner" and _core_store.STORE == T / "store")
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
    return ran, fails


# ================================================================ part config_hosts: host words: a setting that names a machine may name a role instead
def part_config_hosts():
    import contextlib, io, json, logging, os, pathlib, re, socket, subprocess, sys, threading, time
    import _scratch, _instance
    sys.path.insert(0, STACK)
    tmp = _scratch.mkdtemp(prefix="confighosts-"); T = pathlib.Path(tmp)
    HOME_WAS = os.environ.get("HOME")
    LOG, MODE, SENT = T / "lookup-calls.log", T / "lookup-mode", T / "sentinel"
    STUB, STUB2 = T / "where-is", T / "where-else"
    MODE.write_text("ok")
    STUB.write_text(f'''#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a" >> "{LOG}"; done; echo "--" >> "{LOG}"
case "$(cat "{MODE}")" in
  fail) exit 3;;
  empty) exit 0;;
  blank) echo; echo "host-of-$1"; exit 0;;
  spaces) echo "two words"; exit 0;;
  colon) echo "name:22"; exit 0;;
  dash) echo "-oProxyCommand=x"; exit 0;;
  padded) echo "   host-of-$1   "; exit 0;;
  crlf) printf 'host-of-%s\\r\\nignored\\n' "$1"; exit 0;;
  multi) echo "host-of-$1"; echo "second-line"; exit 0;;
  slow) sleep 0.6; echo "host-of-$1"; exit 0;;
  byrole) if [ "$1" = "slowrole" ]; then sleep 1.5; fi; echo "host-of-$1"; exit 0;;
  hang) echo $$ > "{T}/hang.pid"; exec sleep 60;;
  moved) echo "moved-$1"; exit 0;;
  unicode) echo "hôst"; exit 0;;
  slash) echo "a/b"; exit 0;;
  semi) echo "a;b"; exit 0;;
  at) echo "user@host-1.example.net"; exit 0;;
  big) head -c 5000 /dev/zero | tr '\\0' a; echo; exit 0;;
  flood) echo $$ > "{T}/flood.pid"; exec yes aaaaaaaa;;
  gchild) sleep 60 & echo $! > "{T}/gchild.pid"; wait;;
esac
echo "host-of-$1"
''', encoding="utf-8")
    STUB2.write_text('#!/bin/sh\necho "else-$1"\n', encoding="utf-8")
    for s_ in (STUB, STUB2): s_.chmod(0o755)

    toml = _instance.apply(_instance.base_toml())
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                     ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    toml, n = re.subn(r'(?m)^bash_host = "[^"]*"', 'bash_host = "host:primary"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^form_machines = \[[^\]]*\]', 'form_machines = ["host:primary", "db-primary"]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^ssh_hosts = \[\]', 'ssh_hosts = ["host:spare", "box-d", "host:spare"]', toml); assert n == 1
    CONF = T / "stackshot.toml"
    BASE_TOML = toml
    def write_conf(lookup: str) -> None:
        CONF.write_text(BASE_TOML + f'\n[hosts]\nlookup = "{lookup}"\ntimeout = 5\ncache_seconds = 30\n', encoding="utf-8")
    write_conf(f"{STUB} {{role}}")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=str(CONF), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
    for k in ("STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID"): os.environ.pop(k, None)
    for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
    logging.disable(logging.CRITICAL)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

    from stackshot.core import config as C
    from stackshot.core import agentbox as AB
    from stackshot.fleet import fleet as FL
    from stackshot.model import step_commands as SC
    from stackshot.service import projects as PS

    CLOCK = [1000.0]
    C._host_clock = lambda: CLOCK[0]
    def calls() -> int: return LOG.read_text().count("--\n") if LOG.exists() else 0
    def logged() -> list[list[str]]:
        out, cur = [], []
        for ln in (LOG.read_text().splitlines() if LOG.exists() else []):
            if ln == "--": out.append(cur); cur = []
            else: cur.append(ln)
        return out
    def forget():
        """Every answer and failure gone (what a fresh process knows); config._host_reset keeps the last good hosts, which a reload must."""
        C._HOST_GOOD.clear(); C._HOST_FAILED.clear()
    def fresh(mode="ok", **hosts):
        """Forget every answer, clear the log, set the stub's mode and the [hosts] table the next checks run under (the stub by default)."""
        forget(); LOG.write_text(""); MODE.write_text(mode); CLOCK[0] += 1000
        C.CFG["hosts"] = {"lookup": f"{STUB} {{role}}", "timeout": 5, "cache_seconds": 30, **hosts}
        if "lookup" in hosts and hosts["lookup"] is None: del C.CFG["hosts"]["lookup"]
    def err_of(fn):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf): r = fn()
        return r, buf.getvalue()
    def quiet(fn):
        return err_of(fn)[0]

    try:
        # ---- plain values are left alone
        fresh()
        plain_list = ["box-a", "box-b"]
        C.CFG["zz"] = {"s": "plain", "n": 7, "f": 1.5, "b": True, "l": plain_list, "t": {"inner": "host:web"}, "e": "", "nested": [["host:web"]], "sp": "host web", "pre": "ahost:web", "u": "host"}
        check("a plain string comes back as it is", C.get("zz", "s") == "plain")
        check("a number, a float and a bool come back as they are", (C.get("zz", "n"), C.get("zz", "f"), C.get("zz", "b")) == (7, 1.5, True))
        check("a list of plain items is the same object, untouched", C.get("zz", "l") is plain_list)
        check("a table is returned as it is, a host word inside it untouched (a reader that takes the table whole resolves its own key)", C.get("zz", "t") is C.CFG["zz"]["t"] and C.get("zz", "t") == {"inner": "host:web"})
        check("a list inside a list is not looked into", C.get("zz", "nested") == [["host:web"]])
        check("'host web', 'ahost:web', 'host' and '' are no host words", [C.get("zz", k) for k in ("sp", "pre", "u", "e")] == ["host web", "ahost:web", "host", ""])
        check("a missing key gives the default, unresolved", C.get("zz", "nope", default="host:web") == "host:web")
        check("none of that ran the lookup", calls() == 0, calls())

        # ---- resolved at the leaf
        C.CFG["zz"]["w"] = "host:web"; C.CFG["zz"]["l2"] = ["box-a", "host:web", "host:db-2", 5, "box-a"]
        check("get() resolves a host word at its leaf", C.get("zz", "w") == "host-of-web", C.get("zz", "w"))
        r = C.get("zz", "l2")
        check("each string item of a list is resolved, the plain ones and the non-strings kept in their places", r == ["box-a", "host-of-web", "host-of-db-2", 5, "box-a"], r)
        check("the list in the config was not rewritten", C.CFG["zz"]["l2"][1] == "host:web")
        check("config.host() resolves one value", C.host("host:web") == "host-of-web")
        check("config.host() returns another value unchanged (a string, a number, a list, None)", (C.host("box-a"), C.host(3), C.host(["host:web"]), C.host(None)) == ("box-a", 3, ["host:web"], None))
        check("a host word with whitespace around it is resolved (a reader strips it too)", C.host("  host:web \n") == "host-of-web")
        check("roles are allowed letters, digits, '-', '_' and '.'", C.host("host:A_b-2.c") == "host-of-A_b-2.c")

        # ---- the cache
        fresh()
        for _ in range(20): C.host("host:web")
        check("20 reads inside cache_seconds make one lookup", calls() == 1, calls())
        CLOCK[0] += 29.9; C.host("host:web")
        check("…still one just before the end of cache_seconds", calls() == 1, calls())
        CLOCK[0] += 0.2; C.host("host:web"); C.host("host:web")
        check("…a second one after it (and only one)", calls() == 2, calls())
        C.host("host:db")
        check("each role is cached on its own", calls() == 3 and logged()[-1] == ["db"], logged())
        fresh(cache_seconds=0)
        C.host("host:web"); C.host("host:web")
        check("cache_seconds = 0 looks up at every read", calls() == 2, calls())
        fresh(cache_seconds="x"); C.host("host:web"); C.host("host:web")
        check("a cache_seconds that is not a number reads as the default 30", calls() == 1, calls())

        # ---- a later failure keeps the last good value; the retry spacing
        fresh()
        check("a good first answer", C.host("host:web") == "host-of-web")
        CLOCK[0] += 31; MODE.write_text("fail")
        got, errtxt = err_of(lambda: C.host("host:web"))
        check("the lookup fails after the cache ran out: the last good host still answers", got == "host-of-web" and calls() == 2, (got, calls()))
        check("…with one line on stderr, naming the role and the reason", errtxt.count("\n") == 1 and "'web'" in errtxt and "exit 3" in errtxt and "last good" in errtxt, errtxt)
        CLOCK[0] += 3
        got, errtxt = err_of(lambda: [C.host("host:web") for _ in range(10)][-1])
        check("inside the 5 seconds after a failure no new lookup is made, the last good value answers", got == "host-of-web" and calls() == 2 and errtxt == "", (got, calls(), errtxt))
        CLOCK[0] += 2.5
        got, errtxt = err_of(lambda: C.host("host:web"))
        check("after the 5 seconds the lookup is tried again, fails again, the last good value still stands, and the streak says nothing more", got == "host-of-web" and calls() == 3 and errtxt == "", (got, calls(), errtxt))
        CLOCK[0] += 5.1; MODE.write_text("moved")
        check("when the lookup works again its new answer replaces the old", C.host("host:web") == "moved-web" and calls() == 4)
        CLOCK[0] += 31; MODE.write_text("fail")
        got, errtxt = err_of(lambda: C.host("host:web"))
        check("a failure after a recovery is a new streak, with its own line", got == "moved-web" and errtxt.count("\n") == 1, (got, errtxt))

        # ---- no good value: the word stays as written
        fresh(lookup=None)
        check("no [hosts] lookup: the word is unchanged and nothing runs", C.host("host:web") == "host:web" and C.get("zz", "w") == "host:web" and calls() == 0)
        C.CFG.pop("hosts", None)
        check("no [hosts] table at all: the same", C.host("host:web") == "host:web" and calls() == 0)
        fresh(lookup="")
        check("an empty lookup: unchanged", C.host("host:web") == "host:web" and calls() == 0)
        fresh(lookup=12)
        check("a lookup that is not a string: unchanged", C.host("host:web") == "host:web" and calls() == 0)
        C.CFG["hosts"] = "not a table"
        check("[hosts] that is not a table: unchanged", C.host("host:web") == "host:web")
        fresh("fail")
        got, errtxt = err_of(lambda: C.host("host:web"))
        check("the first lookup fails: the word is unchanged (not '', not a guess)", got == "host:web" and calls() == 1 and errtxt.count("\n") == 1 and "as written" in errtxt, (got, errtxt))
        CLOCK[0] += 2; check("…and is not tried again within 5 seconds", quiet(lambda: C.host("host:web")) == "host:web" and calls() == 1)
        CLOCK[0] += 4; MODE.write_text("ok")
        check("…but is after them, and then resolves", C.host("host:web") == "host-of-web" and calls() == 2)
        fresh(lookup=f"{T}/no-such-command {{role}}")
        check("a command that is not found: unchanged, no exception", quiet(lambda: C.host("host:web")) == "host:web")
        fresh(lookup=f"{STUB} 'unbalanced {{role}}")
        check("a template with an unbalanced quote: unchanged, no exception", quiet(lambda: C.host("host:web")) == "host:web")
        fresh(lookup=f"{STUB} web")
        check("a lookup with no {role} in it is not run", quiet(lambda: C.host("host:web")) == "host:web" and calls() == 0)
        fresh(lookup="host:loop")
        t0 = time.monotonic()
        check("a lookup that is itself a host word neither recurses nor hangs: the word stays", quiet(lambda: C.host("host:web")) == "host:web" and C.get("hosts", "lookup") == "host:loop" and time.monotonic() - t0 < 3)
        fresh(timeout=0)
        check("a timeout of 0 reads as the default 5", C.host("host:web") == "host-of-web")
        fresh(timeout=-2); check("a negative timeout too", C.host("host:web") == "host-of-web")
        fresh(timeout=True); check("and a bool", C.host("host:web") == "host-of-web")

        # ---- what a lookup may print
        for mode, name, want in (("empty", "no output", "host:web"), ("blank", "an empty first line (the host on a later line does not count)", "host:web"),
                                 ("spaces", "a name with a space inside", "host:web"), ("colon", "a name with a colon", "host:web"), ("dash", "a name that starts with '-' (an ssh option)", "host:web"),
                                 ("fail", "a non-zero exit", "host:web"),
                                 ("unicode", "a name with a character outside letters, digits and . _ @ -", "host:web"), ("slash", "a name with a slash", "host:web"), ("semi", "a name with a semicolon", "host:web"),
                                 ("big", "more than 4096 bytes on the first line", "host:web"),
                                 ("at", "user@host.example, the form ssh takes (accepted)", "user@host-1.example.net"),
                                 ("padded", "a first line with spaces around it (taken stripped)", "host-of-web"), ("crlf", "a first line ended by CR LF", "host-of-web"),
                                 ("multi", "more lines after the first (ignored)", "host-of-web")):
            fresh(mode)
            got = quiet(lambda: C.host("host:web"))
            check(f"output: {name}", got == want, got)

        # ---- a lookup that never answers is ended
        fresh("hang", timeout=0.5)
        t0 = time.monotonic(); got, errtxt = err_of(lambda: C.host("host:web")); took = time.monotonic() - t0
        check("a lookup that never answers is a failure within the timeout (bounded time)", got == "host:web" and 0.4 < took < 4, (got, took))
        check("…with its reason on the one stderr line", "no answer in 0.5 s" in errtxt, errtxt)
        pid = (T / "hang.pid").read_text().strip() if (T / "hang.pid").exists() else ""
        check("…and the process it started is gone", pid.isdigit() and not os.path.exists(f"/proc/{pid}"), pid)

        fresh("flood", timeout=5)
        t0 = time.monotonic(); got, errtxt = err_of(lambda: C.host("host:web")); took = time.monotonic() - t0
        check("a lookup that never stops printing is a failure at once (its output is read up to 4096 bytes), not at the timeout", got == "host:web" and took < 3 and "4096 bytes" in errtxt, (got, took, errtxt))
        pid = (T / "flood.pid").read_text().strip() if (T / "flood.pid").exists() else ""
        check("…and the process it started is ended", pid.isdigit() and not os.path.exists(f"/proc/{pid}"), pid)
        fresh("gchild", timeout=0.5)
        t0 = time.monotonic(); got = quiet(lambda: C.host("host:web")); took = time.monotonic() - t0
        gpid = (T / "gchild.pid").read_text().strip() if (T / "gchild.pid").exists() else ""
        gone = False
        for _ in range(40):
            if gpid.isdigit() and not os.path.exists(f"/proc/{gpid}"): gone = True; break
            time.sleep(0.05)
        check("a lookup that left a child holding its output is ended within the timeout, and the child (a grandchild of the server) is ended with it: the whole process group is killed", got == "host:web" and took < 4 and gone, (got, took, gpid, gone))
        if gpid.isdigit() and os.path.exists(f"/proc/{gpid}"):
            try: os.kill(int(gpid), 9)       # by the pid the stub wrote, never by name
            except OSError: pass

        # ---- no shell
        fresh(lookup=f"{STUB} {{role}} ; touch {SENT} && echo x > {SENT} $(touch {SENT}) `touch {SENT}`")
        got = C.host("host:web")
        args = logged()[0] if logged() else []
        check("a template with shell characters runs no shell: the words go to the command as they are, nothing is created", not SENT.exists() and args[:2] == ["web", ";"] and "&&" in args and "$(touch" in args, (args, SENT.exists()))
        check("…and the command's first line still answers", got == "host-of-web", got)
        fresh(lookup=f"{STUB} pre-{{role}}-post")
        C.host("host:web")
        check("{role} is replaced inside a longer word", logged() == [["pre-web-post"]], logged())
        fresh(lookup=f"{STUB} --role={{role}} {{role}}")
        C.host("host:web")
        check("{role} is replaced in every word it stands in", logged() == [["--role=web", "web"]], logged())
        os.environ["HOME"] = tmp
        (T / "bin").mkdir(exist_ok=True); (T / "bin" / "where-is").write_bytes(STUB.read_bytes()); (T / "bin" / "where-is").chmod(0o755)
        fresh(lookup="~/bin/where-is {role}")
        got = C.host("host:web")
        check("a leading ~ is expanded in each word", got == "host-of-web", got)
        for bad in ("host:a b", "host:a:b", "host:", "host:-x", "host:a;touch", f"host:a;touch {SENT}", "host:$(id)", "host:`id`", "host:a|b", "host:a/b", "host:a&b", "host:a\nb", "host: a", "host:é", "HOST:a", "host:a'b", "host:a\"b", "host:a>b"):
            fresh()
            got = C.host(bad)
            check(f"a bad role {bad!r} is no host word: left as written, nothing runs", got == bad and calls() == 0, (got, calls()))
        check("…and no file was created by any of them", not SENT.exists())

        # ---- threads
        fresh("slow")
        out, ths = [], []
        gate = threading.Barrier(8)
        def ask():
            gate.wait(); out.append(C.host("host:web"))
        for _ in range(8): ths.append(threading.Thread(target=ask))
        for t in ths: t.start()
        for t in ths: t.join(20)
        check("eight threads asking one role at once cause one lookup, and all get its answer", calls() == 1 and out == ["host-of-web"] * 8, (calls(), out))
        fresh("byrole")
        res = {}
        def slow_role(): res["slow"] = C.host("host:slowrole")
        t = threading.Thread(target=slow_role); t.start(); time.sleep(0.4)
        t0 = time.monotonic(); fast = C.host("host:quick"); fast_took = time.monotonic() - t0
        t.join(20)
        check("a slow lookup of one role does not hold up another role", fast == "host-of-quick" and fast_took < 1.0 and res.get("slow") == "host-of-slowrole", (fast, fast_took, res))
        fresh("slow")
        out2 = []
        t = threading.Thread(target=lambda: out2.append(C.host("host:web"))); t.start(); time.sleep(0.2)
        t0 = time.monotonic(); during = C.get("zz", "s"); plain_took = time.monotonic() - t0
        t.join(20)
        check("a plain read is not held up by a lookup in progress", during == "plain" and plain_took < 0.3 and out2 == ["host-of-web"], (during, plain_took, out2))
        fresh("fail")
        out3 = []; gate = threading.Barrier(6)
        def ask3():
            gate.wait(); out3.append(quiet(lambda: C.host("host:web")))
        ths = [threading.Thread(target=ask3) for _ in range(6)]
        for t in ths: t.start()
        for t in ths: t.join(20)
        check("six threads asking a role whose lookup fails cause one lookup, and all see the word", calls() == 1 and out3 == ["host:web"] * 6, (calls(), out3))

        # ---- the four readers
        fresh(); C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": ["host:primary", "db-primary"]}
        check("form_machines (the form gate's helper) resolves each item and keeps the plain ones", PS._cfg_names("form_machines", []) == ["host-of-primary", "db-primary"], PS._cfg_names("form_machines", []))
        check("…a caller token of the machine the role names is the form's, one of another is not", PS._form_call("host-of-primary", "form-x") and PS._form_call("db-primary", "form-x") and not PS._form_call("host-b", "form-x"))
        C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": "host:primary"}
        check("…a bare string counts as one item, resolved", PS._cfg_names("form_machines", []) == ["host-of-primary"])
        check("…the default of an unset key is returned as it is", PS._cfg_names("other", ["host-z"]) == ["host-z"])
        bg_sec = {"bg_senders": ["bg-x"], "bg_machines": ["host:primary", "db-primary"], "form_machines": ["db-form"]}
        C.CFG["project_agent"] = dict(bg_sec)
        okc, no = PS._bg_call("host-of-primary", "bg-x", False, ""), PS._bg_call("host-other", "bg-x", False, "")
        check("bg_machines: a host word in it is resolved; a background call from the machine it names is allowed, from another a 403", okc == (True, None) and no[0] is False and no[1] is not None and no[1][0] == 403, (okc, no))
        check("…a plain item of it still matches, and form_machines is not consulted while bg_machines is set", PS._bg_call("db-primary", "bg-x", False, "") == (True, None) and PS._bg_call("db-form", "bg-x", False, "")[0] is False)
        C.CFG["project_agent"] = {"bg_senders": ["bg-x"], "bg_machines": [], "form_machines": ["host:primary", "db-form"]}
        check("an empty bg_machines falls back to form_machines, its host words resolved too", PS._bg_call("host-of-primary", "bg-x", False, "") == (True, None) and PS._bg_call("db-form", "bg-x", False, "") == (True, None) and PS._bg_call("host-other", "bg-x", False, "")[0] is False)
        C.CFG["project_agent"] = {"bg_senders": ["bg-x"], "form_machines": "host:primary"}
        check("…an absent bg_machines the same", PS._bg_call("host-of-primary", "bg-x", False, "") == (True, None))
        fresh(lookup=None); C.CFG["project_agent"] = dict(bg_sec)
        check("…with no lookup the word stays as written and matches no machine's token", PS._bg_call("host-of-primary", "bg-x", False, "")[0] is False and PS._bg_call("host:primary", "bg-x", False, "") == (True, None))
        fresh(lookup=None); C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": ["host:primary", "db-primary"]}
        check("…with no lookup the word stays in the list and matches no machine's token", PS._cfg_names("form_machines", []) == ["host:primary", "db-primary"] and not PS._form_call("host-of-primary", "form-x"))
        fresh(); C.CFG["steps"] = {"owner_shell": "powershell", "bash_host": "host:primary"}
        check("steps.bash_host resolves", SC.bash_host() == "host-of-primary", SC.bash_host())
        C.CFG["steps"]["bash_host"] = " host:primary "
        check("…also with spaces around the word, and the fix text names the resolved host", SC.bash_host() == "host-of-primary" and "host-of-primary" in SC.bash_fix(), SC.bash_fix())
        fresh(lookup=None); C.CFG["steps"] = {"owner_shell": "powershell", "bash_host": "host:primary"}
        check("…with no lookup it reads as the word, never ''", SC.bash_host() == "host:primary")
        fresh(); C.CFG["agents_box"] = {"ssh": "host:agents"}
        check("agents_box.ssh resolves", AB.host() == "host-of-agents" and AB.enabled() is True, AB.host())
        fresh(lookup=f"{STUB2} {{role}}"); C.CFG["agents_box"] = {"ssh": "host:agents"}
        check("…another lookup command, another answer", AB.host() == "else-agents", AB.host())
        me = socket.gethostname()
        fake_me = T / "where-me"; fake_me.write_text(f'#!/bin/sh\necho "{me}"\n'); fake_me.chmod(0o755)
        fresh(lookup=f"{fake_me} {{role}}"); C.CFG["agents_box"] = {"ssh": "host:agents"}
        check("…a role that moved to this very machine reads as one box (local), as its name always did", AB.host() == "" and AB.enabled() is False, AB.host())
        fresh(lookup=None); C.CFG["agents_box"] = {"ssh": "host:agents"}
        check("…with no lookup it stays as written: ssh to it fails visibly, it is never read as local", AB.host() == "host:agents" and AB.enabled() is True)
        fresh(); C.CFG["machines_panel"] = {"ssh_hosts": ["host:spare", "box-d", "host:spare"]}
        check("machines_panel.ssh_hosts resolves item by item (a repeat once)", FL.ssh_host_names() == ["host-of-spare", "box-d"], FL.ssh_host_names())
        check("…and the panel's order lists the resolved name", "host-of-spare" in FL.machines_order({"a": "box-a"}, FL.ssh_host_names()))
        C.CFG["machines_panel"] = {"ssh_hosts": "host:spare"}
        check("…a bare string is one host, resolved", FL.ssh_host_names() == ["host-of-spare"])
        fresh(lookup=None); C.CFG["machines_panel"] = {"ssh_hosts": ["host:spare", "box-d"]}
        check("…with no lookup the word is listed as written (an unreachable card, never a missing one)", FL.ssh_host_names() == ["host:spare", "box-d"])

        # ---- the colors routes look a host word up off the event loop
        import asyncio
        from stackshot.web.routes import ui_api as UI
        fresh(cache_seconds=0); C.CFG["project_agent"] = {"form_senders": ["sala-web"], "form_machines": ["host:primary"]}      # cache_seconds 0: every read of the word runs a lookup, so each gate shows its thread
        seen = []; real_lookup = C._host_lookup
        def spy(*a, **k):
            seen.append(threading.get_ident()); return real_lookup(*a, **k)
        C._host_lookup = spy
        class Req:
            headers = {"authorization": "Bearer x"}
            async def json(self): return {"sender": "sala-web", "name": "n", "values": {}}
        UI._client_machine = lambda auth, request=None: "host-of-primary"
        UI._colors_body = lambda request: asyncio.sleep(0, {"sender": "sala-web"})
        UI._colors_run = lambda op, body, via: (op, via)
        loop_ids = []
        async def drive():
            loop_ids.append(threading.get_ident())
            r1 = await UI._colors_machine(Req(), "list")
            forget(); CLOCK[0] += 1000
            r2 = await UI._colors_machine(Req(), "save")
            return r1, r2
        r1, r2 = asyncio.run(drive())
        UI._client_machine = lambda auth, request=None: "host-other"
        r3 = asyncio.run(UI._colors_machine(Req(), "list"))
        C._host_lookup = real_lookup
        check("a colors call from the machine a role names passes the gate (list, and save with the form's sender)", getattr(r1, "status_code", 200) == 200 and getattr(r2, "status_code", 200) == 200, (r1, r2))
        check("…and a machine the role does not name is a 403", getattr(r3, "status_code", None) == 403, r3)
        check("the host-word lookup of the colors routes ran, and on a worker thread, never on the event loop's", len(seen) >= 4 and loop_ids[0] not in seen, (seen, loop_ids))

        # ---- reload and the command line
        C.reload(); forget(); LOG.write_text(""); MODE.write_text("ok"); CLOCK[0] += 1000
        check("after a reload the config is the file's", C.get("machines_panel", "ssh_hosts") == ["host-of-spare", "box-d", "host-of-spare"] and calls() == 1, (C.get("machines_panel", "ssh_hosts"), calls()))
        CLOCK[0] += 1; C.host("host:spare")
        check("an answer is cached", calls() == 1)
        write_conf(f"{STUB2} {{role}}")
        changed = quiet(C.reload)
        check("a reload of a changed file went through", changed is not None and "hosts.lookup" in changed, changed)
        check("…it made the answers due: the new lookup answers at once, inside cache_seconds", C.host("host:spare") == "else-spare", C.host("host:spare"))
        MODE.write_text("fail"); write_conf(f"{STUB} {{role}}"); quiet(C.reload); CLOCK[0] += 1
        calls_before = calls()
        got = quiet(lambda: C.host("host:spare"))
        check("…a reload makes the answers due, not gone: the next read runs the lookup again, and when it fails the last good host of that same command still answers", calls() == calls_before + 1 and got == "host-of-spare", (got, calls(), calls_before))
        write_conf(f"{STUB2.parent}/where-none {{role}}"); quiet(C.reload); CLOCK[0] += 1
        check("…while a changed lookup command has no answer of its own: another command's last good host is not used, the word stays", quiet(lambda: C.host("host:spare")) == "host:spare")
        MODE.write_text("ok"); write_conf(f"{STUB} {{role}}")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["STACKSHOT_CONFIG"] = str(CONF)
        r = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "get", "steps.bash_host"], capture_output=True, text=True, env=env, timeout=60, cwd=tmp)
        check("`config.py get steps.bash_host` prints the host the word names", r.returncode == 0 and r.stdout.strip() == "host-of-primary", (r.returncode, r.stdout, r.stderr[-300:]))
        r = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "get", "machines_panel.ssh_hosts"], capture_output=True, text=True, env=env, timeout=60, cwd=tmp)
        check("…a list is printed with its words resolved", r.returncode == 0 and json.loads(r.stdout) == ["host-of-spare", "box-d", "host-of-spare"], (r.returncode, r.stdout, r.stderr[-300:]))
    finally:
        if HOME_WAS is None: os.environ.pop("HOME", None)
        else: os.environ["HOME"] = HOME_WAS
        _scratch.cleanup()
    return ran, fails


MARK = "@@reload part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"reload": part_reload, "config_hosts": part_config_hosts}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0) if name == 'reload' else sys.exit(0)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: reload scenario, {total} checks")
