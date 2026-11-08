"""Scenario test: stackshot runs with no fleet tool (an earlier release took sala's names out of the code; this shows the rest). A real
server process on a free port the test picks (never 8010), a temp config made from stackshot.example.toml, a temp state dir and a
temp HOME, and a PATH from which every directory holding a `sala` is taken out. Nothing of the host is read or written.

Covers: the example config names no fleet tool (every [fleet], [client], [said] and [project_agent] key that release added is empty,
and no value in the file says sala); the server comes up and answers /healthz 200; through the client, a board read (brief), an item
filed (post question), post state refusing as retired, and a recycle marked due, all work; a recycle-due call prints no fleet-tool hint
(its usage line and its refusal for a pull request no item covers); the item page and the project page give session names as plain
text, with no link, even beside a decoy fleet-tool store of links on disk (session_links is empty, so it is not read); nothing tries
to run `sala`: the whole run is done twice, once on a PATH with no sala at all and once on a PATH whose only `sala` is a tripwire
that records any call (it must record none). The server is stopped in the test's own teardown, and its port is free again after; its
TMPDIR is a folder of the run's own, so what a stopped server leaves (a router call's folder) goes with the test's, never to the system's /tmp.

    tests/run-suite sala_absent        → exit 0 / 1"""
import json, os, pathlib, re, shutil, socket, subprocess, sys, tempfile, time, tomllib, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="salaabsent-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]
        if p != 8010: return p

# ---- 0. the example config names no fleet tool
ex = tomllib.loads(EXAMPLE)
KEYS = (("fleet", "tool_name"), ("fleet", "recycle_when_idle"), ("fleet", "operator_session"), ("client", "session_view"), ("client", "session_links"),
        ("client", "lanes_file"), ("client", "limit_file"), ("client", "recycle_env_prefix"), ("said", "injected_marker"), ("project_agent", "form_senders"))
check("the example config: every fleet-tool key is empty", all(ex[s][k] in ("", []) for s, k in KEYS), {f"{s}.{k}": ex[s][k] for s, k in KEYS if ex[s][k] not in ("", [])})
def values(o):
    if isinstance(o, dict):
        for v in o.values(): yield from values(v)
    elif isinstance(o, list):
        for v in o: yield from values(v)
    else: yield o
check("the example config: no value in it says sala", not [v for v in values(ex) if "sala" in str(v).lower()], [v for v in values(ex) if "sala" in str(v).lower()])

# ---- the PATH: every directory holding a sala is taken out
def has_sala(d): return os.access(os.path.join(d, "sala"), os.X_OK) and os.path.isfile(os.path.join(d, "sala"))
CLEAN_PATH = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not has_sala(d))
check("the test's PATH has no sala", shutil.which("sala", path=CLEAN_PATH) is None, shutil.which("sala", path=CLEAN_PATH))

def edit(text, *subs):
    for pat, rep in subs:
        text, n = re.subn(pat, rep, text); assert n == 1, pat
    return text

def run_pass(label: str, tripwire: bool) -> None:
    """One whole run on a fixture of its own. tripwire: a `sala` that records its calls is the only one on the PATH."""
    root = T / label; port = free_port(); home = root / "home"
    for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects", "home", "decoy/a", "bin", "tmp"): (root / d).mkdir(parents=True)
    log = root / "sala-calls.log"
    path = CLEAN_PATH
    if tripwire:
        w = root / "bin/sala"; w.write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{log}'\nexit 0\n"); w.chmod(0o755)
        path = f"{root / 'bin'}{os.pathsep}{CLEAN_PATH}"
        check(f"[{label}] the only sala on the PATH is the tripwire", shutil.which("sala", path=path) == str(w), shutil.which("sala", path=path))
    else:
        check(f"[{label}] no sala on the PATH", shutil.which("sala", path=path) is None)
    toml = EXAMPLE
    for key, val in (("repo", str(root)), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"), ("state", f"{root}/state"),
                     ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("fleet_names", f"{root}/session-names.tsv"), ("rules", f"{root}/RULES.md"),
                     ("claude_credentials", f"{root}/none.json"), ("timezone", "Asia/Dubai")):
        toml = edit(toml, (rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"'))
    toml = edit(toml, (r"(?m)^prefixes = .*$", 'prefixes = ["[work] ", "[home] "]'), (r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"),
                (r"(?m)^port = 8020", f"port = {port}"), (r"(?m)^every_minutes = 10", "every_minutes = 1440"), (r"(?m)^panel = true", "panel = false"))   # the Runners panel never reads GitHub from this server. Only the paths and the port: the fleet and client keys stay as the example has them
    conf = root / "stackshot.toml"; conf.write_text(toml, encoding="utf-8")
    cfg = tomllib.loads(toml)
    check(f"[{label}] the config under test: fleet and client keys empty, port {port}", all(cfg[s][k] in ("", []) for s, k in KEYS) and cfg["server"]["port"] == port and port != 8010)
    (root / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    OWNER = "home-sparrow-main"; UUID = "00000000-0000-4000-8000-000000000001"
    (root / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (root / "fleet/a/sessions.json").write_text(json.dumps({UUID: {"name": OWNER, "machine": "a", "url": "", "seen": "x"}}))
    # a fleet tool's store of links on disk, which an instance with session_links = "" must not read
    (root / "decoy/a/sessions.json").write_text(json.dumps({UUID: {"name": OWNER, "machine": "a", "url": f"https://fleet-tool.invalid/#s={OWNER}", "seen": "x"}}))
    (root / "store/next-id").write_text("10"); (root / "store/anchors.json").write_text("{}")
    (root / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item 1", "description": "A thing. It lives here. Done when done.", "status": "open",
                                                      "metadata": {"owner": OWNER, "mover": OWNER, "project": "projects/alpha"}}))
    (root / "brain/projects/alpha.md").write_text("---\ntype: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\nstatus: active\n---\n\n# Alpha\n", encoding="utf-8")
    # TMPDIR is the run's own folder, never dropped: with none, the server's router call made its stackshot-router-* folder in the system /tmp, and the
    # teardown's terminate during a call left it there (box-c, a measured run on a main commit)
    env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_URL", "BOARD_MCP_CONFIG", "CLAUDE_CODE_SESSION_ID")}
    env.update(PATH=path, HOME=str(home), TMPDIR=str(root / "tmp"), STACKSHOT_CONFIG=str(conf), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(root / "fleet"))
    errf = open(root / "server.err", "w+")
    def cli(*args, stdin=None):
        r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/fleet/client.py"), *args], capture_output=True, text=True, timeout=120, env=env, cwd=str(root), input=stdin)
        return r.returncode, r.stdout, r.stderr
    def get(url, timeout=10):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{url}", timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
        except Exception as e: return 0, f"{type(e).__name__}: {e}"
    # the page registry the server reads, made the way the pane gate makes it (pages.py registry, on this config); the client's token, minted for this box
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "registry"], capture_output=True, text=True, timeout=120, env=env, cwd=str(root))
    check(f"[{label}] setup: the page registry is made", r.returncode == 0 and "projects/alpha" in (root / "store/projects.json").read_text(), (r.returncode, r.stdout[-200:], r.stderr[-300:]))
    rc, out, err = cli("mint", socket.gethostname())
    check(f"[{label}] setup: this box's client token is minted, pointing at the test's port", rc == 0 and (root / "secrets/client.url").read_text().strip() == f"http://127.0.0.1:{port}", (rc, out, err, (root / "secrets/client.url").read_text()))
    proc = subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/web/server.py")], stdout=subprocess.DEVNULL, stderr=errf, cwd=str(root), env=env)
    try:
        # ---- 1. up
        st = 0; end = time.time() + 90
        while time.time() < end and proc.poll() is None:
            st, _ = get("/healthz", 2)
            if st == 200: break
            time.sleep(0.3)
        errf.flush(); errf.seek(0)
        check(f"[{label}] the server is up: /healthz answers 200", st == 200, (st, proc.poll(), errf.read()[-800:]))
        if st != 200: return
        if os.path.isdir("/proc"):   # its temporary folders (the router's call runs in one) go with the run's folder, never to the system's /tmp
            try: senv = dict(x.split("=", 1) for x in pathlib.Path(f"/proc/{proc.pid}/environ").read_bytes().decode("utf-8", "replace").split("\0") if "=" in x)
            except OSError: senv = {}
            check(f"[{label}] the server's TMPDIR is the run's own folder", senv.get("TMPDIR") == str(root / "tmp"), senv.get("TMPDIR"))
        # ---- 2. the client: a board read, an item filed and updated
        rc, out, err = cli("get", "brief")
        check(f"[{label}] client: a board read (brief) answers", rc == 0 and out.startswith("Board: 1 open"), (rc, out[:200], err[:200]))
        rc, out, err = cli("post", "question", "--project", "alpha", "--ask", "Decide: whether to ship it · Recommend: ship · Stakes: a day · By: no date", "--subject", "[home] Ship the thing?",
                           "--request-id", f"{label}-1", "--sender", "absent-test", stdin="Ship it now, or wait a day?\n")
        item = out.strip()
        check(f"[{label}] client: an item is filed (post question prints its id)", rc == 0 and re.fullmatch(r"\S+", item) is not None, (rc, out, err))
        rc, out, err = cli("get", "brief")
        check(f"[{label}] client: the board now holds two open items", rc == 0 and out.startswith("Board: 2 open"), (rc, out[:200], err[:200]))
        rc, out, err = cli("post", "state", "--item", item, "--state", "your-step", "--step", "run the thing", "--sender", "absent-test")
        check(f"[{label}] client: post state is retired: it exits 1 and names what to pass through update instead, without a fleet tool", rc == 1 and "retired" in err and "mover=" in err and "sala" not in (out + err).lower(), (rc, out[:300], err[:300]))
        rc, out, err = cli("get", "items", OWNER)
        check(f"[{label}] client: the owner's items read back, the new one among them", rc == 0 and item in out, (rc, out[:500], err[:200]))
        # ---- 3. recycle-due prints no fleet-tool hint
        rc, out, err = cli("recycle-due")
        check(f"[{label}] recycle-due with no argument: its usage line, no fleet-tool hint", rc == 1 and out.startswith("usage: client.py recycle-due --item <id> | --pr <PR url>")
              and "with no item to flag" not in out and "sala" not in (out + err).lower(), (rc, out, err))
        rc, out, err = cli("recycle-due", "--pr", "https://github.com/example/none/pull/1")
        check(f"[{label}] recycle-due for a pull request no item covers: refused, 'next recycle', no fleet command named", rc == 1 and "next recycle" in out
              and "sala" not in (out + err).lower() and "--when-idle" not in out, (rc, out, err))
        rc, out, err = cli("recycle-due", "--item", item)
        check(f"[{label}] recycle-due --item marks the item: it waits for a recycle, no fleet tool named", rc == 0 and "now waits for a recycle" in out and "sala" not in (out + err).lower(), (rc, out, err))
        # ---- 4. a page render gives session names without links
        st, page = get(f"/items/{item}")
        owner_cell = page.split("<dt>Mover</dt><dd>")[1].split("</dd>")[0] if "<dt>Mover</dt><dd>" in page else ""
        check(f"[{label}] the item page renders and names the owner session as plain text", st == 200 and OWNER in owner_cell and "<a " not in owner_cell, (st, owner_cell[:300], page[:200]))
        check(f"[{label}] the item page: no link to a fleet tool, no sala, no decoy link", "fleet-tool.invalid" not in page and "sala" not in page.lower(), [m.group(0) for m in re.finditer(r".{30}sala.{30}", page, re.I)][:3])
        st, page = get("/projects/alpha")
        check(f"[{label}] the project page renders; its session names carry no link", st == 200 and OWNER in page and not re.search(rf'<a [^>]*>\s*{re.escape(OWNER)}', page)
              and "fleet-tool.invalid" not in page and "sala" not in page.lower(), (st, [m.group(0) for m in re.finditer(r".{30}sala.{30}", page, re.I)][:3]))
        # ---- 5. nothing tried to run sala
        errf.flush(); errf.seek(0); logtext = errf.read()
        check(f"[{label}] the server's log: no sala, no traceback", "sala" not in logtext.lower() and "Traceback" not in logtext, logtext[-800:])
        check(f"[{label}] nothing ran sala" + (": the tripwire has no record of a call" if tripwire else ""), not log.exists() or log.read_text() == "", log.read_text() if log.exists() else "")
        check(f"[{label}] the server is still the same process, still serving", proc.poll() is None and get("/healthz", 5)[0] == 200)
    finally:
        proc.terminate()
        try: proc.wait(15)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(10)
        errf.close()
    time.sleep(0.2)
    with socket.socket() as s:
        free = s.connect_ex(("127.0.0.1", port)) != 0
    check(f"[{label}] teardown: the server has exited and its port is free", proc.poll() is not None and free, (proc.poll(), free))

try:
    run_pass("nosala", tripwire=False)
    run_pass("tripwire", tripwire=True)
finally:
    if not fails: shutil.rmtree(tmp, ignore_errors=True)
    else: print(f"kept for inspection: {tmp}")
print(("ok" if not fails else "FAILED") + f": sala-absent scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
