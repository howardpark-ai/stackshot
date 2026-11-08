"""Scenario test: a fresh install on the example config: stackshot.example.toml
with its paths and port changed and `[instance] owner` set, plain pages (no gbrain) in a throwaway git repo, no fleet tool, auth in its local-test
mode (STACKSHOT_AUTH=off). A real server process on a random 127.0.0.1 port (never 8010) runs in the foreground of this test, in a temp HOME and
TMPDIR of the run's own; it is stopped in the `finally` and its port is free again after. Nothing of the host is read or written.

Covers: the board's main pages (/, an item, a project page, /runners, /landed, a search, the manifest), the client's reads (brief, projects) and the
MCP tool list (every tool's description and parameters, the instructions, the resources) name none of the made-up names (the owner "Alex", the made-up boxes box-a to box-d,
the made-up owner values below) and no fleet tool, and the tool text with `owner = "Alex"` is the tool text with the placeholder, "the owner", replaced; the example config
names no personal value;
a project is made on plain pages (the page file is written, a second make is a 409, not a 502); the gbrain-only tools (rename_page.py, page_keeper.py)
refuse with a message that says why; the router's timeline note and the page-debt store work on the markdown file (PlainIO: a stale revision is
refused, a path outside the checkout is refused, the same note twice is one line); the gbrain command line is a setting.

    tests/run-suite neutral_install        → exit 0 / 1"""
import json, os, pathlib, re, shutil, socket, subprocess, sys, time, tomllib, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="neutral-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
OWNER = "Alex"
# what the board must never say: the made-up names of this suite (word-bounded for the fleet tool: "salad" is no sala)
MADE_UP_OWNER = ["Avery", "ak-orion", "averykline.example"]      # made-up owner, machine and domain
PERSONAL = re.compile(r"box-[a-d]|" + "|".join(re.escape(x) for x in MADE_UP_OWNER))
FLEET = re.compile(r"(?i)(?<![a-z0-9])sala(?:mander)?(?![a-z0-9])")
def leaks(text: str, fleet: bool = True) -> list[str]:
    text = re.sub(r"data:[^\"')\s]{40,}", "data:", text)       # an inlined icon or font is bytes, not text
    text = text.replace(socket.gethostname(), "THISBOX")        # the name of the box the test runs on is the box's, not the install's
    pats = (PERSONAL, FLEET) if fleet else (PERSONAL,)
    return [text[max(0, m.start() - 40):m.end() + 40].replace("\n", " ") for p in pats for m in p.finditer(text)][:4]

def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]
        if p != 8010: return p

def values(o):
    if isinstance(o, dict):
        for v in o.values(): yield from values(v)
    elif isinstance(o, list):
        for v in o: yield from values(v)
    else: yield o

def edit(text, *subs):
    for pat, rep in subs:
        text, n = re.subn(pat, rep, text); assert n == 1, pat
    return text

# ---- 0. the example config, as it ships
ex = tomllib.loads(EXAMPLE)
check("the example config: plain pages, no gbrain command, the owner a placeholder", ex["pages"]["flavor"] == "plain" and ex["gbrain"]["bin"] == "gbrain" and ex["instance"]["owner"] == "the owner", (ex["pages"], ex["gbrain"]))
check("the example config: no value in it names the owner, its machines or a fleet tool", not [v for v in values(ex) if isinstance(v, str) and (PERSONAL.search(v) or FLEET.search(v))],
      [v for v in values(ex) if isinstance(v, str) and (PERSONAL.search(v) or FLEET.search(v))])
check("the name check has teeth: it flags a planted box name and a planted made-up owner, machine and domain",
      bool(leaks("a box-a here", fleet=False)) and all(leaks(x, fleet=False) for x in MADE_UP_OWNER), [leaks(x, fleet=False) for x in MADE_UP_OWNER])
check("the example config: every machine and person setting is empty or generic",
      all(ex[s].get(k) in ("", [], {}) for s, k in (("runners", "owner"), ("runners", "boxes"), ("runners", "local_box"), ("steps", "owner_shell"), ("steps", "bash_host"), ("steps", "shell_name"), ("terminal", "fallback_project"),
                                                       ("project_agent", "form_machines"), ("model", "rebullet_machines"), ("model", "migration_machines"), ("model", "migration_senders"),
                                                       ("said", "injected_prefixes"), ("said", "injected_phrases"), ("instance", "owner_aliases"), ("pages", "template_page"), ("pages", "rules_line")))
      and ex["project_scopes"]["order"] == ["general"] and ex["project_scopes"]["default"] == "general", ex.get("project_scopes"))

# ---- the fixture: a fresh install
def sh(*cmd, cwd=None, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=cwd, env=env)
    return r.returncode, r.stdout, r.stderr

def build(label: str, owner: str | None, port: int) -> dict:
    """One install on a folder of its own: config, pages repo, store, fleet dir. → {root, conf, env, home}."""
    root = T / label; home = root / "home"
    for d in ("store/a", "state/anchor-hub", "secrets", "touch", "brain/projects", "home", "bin", "tmp", "fleet/a"): (root / d).mkdir(parents=True)
    toml = EXAMPLE
    for key, val in (("repo", str(root)), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"), ("state", f"{root}/state"),
                     ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("fleet_names", f"{root}/session-names.tsv"), ("rules", f"{root}/RULES.md"),
                     ("claude_credentials", f"{root}/none.json"), ("timezone", "Asia/Dubai")):
        toml = edit(toml, (rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"'))
    toml = edit(toml, (r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"), (r"(?m)^port = 8020", f"port = {port}"),
                (r"(?m)^every_minutes = 10", "every_minutes = 1440"), (r"(?m)^panel = true", "panel = false"))   # the Runners panel never reads GitHub from this server
    if owner is not None: toml = edit(toml, (r'(?m)^owner = "the owner"', f'owner = "{owner}"'))
    conf = root / "stackshot.toml"; conf.write_text(toml, encoding="utf-8")
    (root / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    agent = "general-alpha-main"
    (root / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (root / "fleet/a/sessions.json").write_text(json.dumps({"00000000-0000-4000-8000-000000000001": {"name": agent, "machine": "a", "url": "", "seen": "x"}}))
    (root / "store/next-id").write_text("10"); (root / "store/anchors.json").write_text("{}")
    (root / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[work] item 1", "description": "A thing. It lives here. Done when done.", "status": "open",
                                                      "metadata": {"owner": agent, "mover": agent, "project": "projects/alpha"}}))
    (root / "brain/projects/alpha.md").write_text(f"---\ntype: project\ntitle: Alpha\ndisplay-name: general-alpha\nagents:\n  {agent}: talks to the owner\nstatus: active\n---\n\n# Alpha\n\n## Timeline\n\n- **2026-10-01** | someone — started\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_URL", "BOARD_MCP_CONFIG", "CLAUDE_CODE_SESSION_ID")}
    # no gbrain and no fleet tool on the PATH: a directory holding either is taken out
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not any(os.access(os.path.join(d, n), os.X_OK) and os.path.isfile(os.path.join(d, n)) for n in ("sala", "gbrain"))]
    env.update(PATH=os.pathsep.join(keep), HOME=str(home), TMPDIR=str(root / "tmp"), STACKSHOT_CONFIG=str(conf), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(root / "fleet"))
    # the pages repo: a plain git checkout, the way plain pages are kept
    rc, _o, err = sh("git", "init", "-q", cwd=str(root / "brain"), env=env)
    ok = rc == 0
    rc, _o, err2 = sh("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A", cwd=str(root / "brain"), env=env)
    rc2, _o, err3 = sh("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "pages", cwd=str(root / "brain"), env=env)
    check(f"[{label}] setup: the pages are a git checkout with one commit", ok and rc == 0 and rc2 == 0, (err, err2, err3))
    return {"root": root, "conf": conf, "env": env, "home": home, "agent": agent}

def py(inst: dict, code: str, timeout: int = 120):
    """A python -c in the install's environment, from the checkout. → (rc, stdout, stderr)."""
    return sh(sys.executable, "-c", code, cwd=STACK, env={**inst["env"], "PYTHONPATH": STACK})

TOOLS = r'''
import asyncio, json, logging, sys
logging.disable(logging.WARNING)
import server
tools = {t.name: {"description": t.description, "parameters": t.parameters} for t in asyncio.run(server.mcp.list_tools())}
res = {str(r.uri): [r.name, r.description] for r in asyncio.run(server.mcp.list_resources())}
print(json.dumps({"instructions": server.mcp.instructions, "tools": tools, "resources": res}, sort_keys=True, ensure_ascii=False))
'''

# ---- 1. the MCP tool list: with the owner named, and with the placeholder
port = free_port()
inst = build("alex", OWNER, port)
rc, out, err = py(inst, TOOLS)
check("the MCP tool list renders on the neutral config (12 tools, instructions, resources)", rc == 0 and len(json.loads(out or "{}").get("tools", {})) == 12, (rc, out[:200], err[-500:]))
text_alex = out
check("the MCP tool list names none of the owner's names and no fleet tool", not leaks(text_alex), leaks(text_alex))
check("the MCP tool list names the owner of the config", f"{OWNER}'s task board" in text_alex or f"{OWNER}" in text_alex, text_alex[:200])
dflt = build("placeholder", None, free_port())
rc, text_dflt, err = py(dflt, TOOLS)
check("the same tool list on the placeholder owner renders", rc == 0 and text_dflt, (rc, err[-500:]))
check("the owner's name is the only difference: the tool text with owner = Alex is the placeholder's with \"the owner\" replaced",
      text_alex.replace(OWNER, "the owner") == text_dflt or json.loads(text_alex.replace(OWNER, "the owner")) == json.loads(text_dflt),
      [(a, b) for a, b in zip(sorted(json.loads(text_alex.replace(OWNER, "the owner"))["tools"]), sorted(json.loads(text_dflt)["tools"])) if a != b])

# ---- 2. the settings that were code defaults
rc, out, err = py(inst, "import config as c, rename_page as r, runners, step_commands as s, projects as p; print(c.gbrain_bin(), r.G, c.page_flavor(), c.owner(), c.owner_names(), p.scopes(), p.default_scope(), s.shell_rule())")
check("the neutral settings: gbrain on PATH, plain pages, the owner from [instance], scopes [general], no shell rule",
      rc == 0 and out.split()[:4] == ["gbrain", "gbrain", "plain", OWNER] and "['general'] general" in out and out.strip().endswith("False"), (rc, out, err[-300:]))
rc, out, err = py(inst, "import runners; runners.repos() if hasattr(runners, 'repos') else None; print(runners.DEFAULTS['owner'] == '', runners.DEFAULTS['boxes'] == [], runners.DEFAULTS['local_box'] == '')")
check("the runners page names no owner, no box, no local box by default", rc == 0 and out.strip() == "True True True", (rc, out, err[-300:]))
bin_toml = inst["conf"].read_text(encoding="utf-8").replace('bin = "gbrain"', 'bin = "~/tools/gbrain"', 1)
(inst["root"] / "bin.toml").write_text(bin_toml, encoding="utf-8")
rc, out, err = py({**inst, "env": {**inst["env"], "STACKSHOT_CONFIG": str(inst["root"] / "bin.toml")}}, "import rename_page as r; print(r.G)")
check("[gbrain] bin is a setting: ~ is expanded to the home directory", rc == 0 and out.strip() == f"{inst['home']}/tools/gbrain", (rc, out, err[-300:]))

# ---- 3. plain pages, with no server: the page store, the gbrain-only tools, the router's note
PLAIN = r'''
import json, os, pathlib
import page_debt as pd, router_live as rl, config as c
io = pd.page_io(); out = {"io": type(io).__name__}
body, rev = io.get("projects/alpha")
out["get"] = bool(body and rev and "# Alpha" in body)
out["stale"] = io.put("projects/alpha", body + "\nx\n", "0" * 64)[0]
out["escape_create"] = io.create("../outside", "x")[0]
out["escape_get"] = io.get("../outside")
out["create"] = io.create("projects/beta", "# Beta\n")[0]; out["again"] = io.create("projects/beta", "# Beta\n")[0]
out["put"] = io.put("projects/alpha", body + "\nedited\n", rev)[0]
out["note1"] = rl.add_timeline("projects/alpha", "2026-10-31", "the router ruled", "", "id-1")
out["note2"] = rl.add_timeline("projects/alpha", "2026-10-31", "the router ruled", "", "id-1")
out["missing"] = rl.add_timeline("projects/none", "2026-10-31", "x", "", "id-2")
page = pathlib.Path(c.path("paths", "brain"), "projects/alpha.md").read_text(encoding="utf-8")
out["lines"] = page.count("the router ruled"); out["has_timeline"] = "## Timeline" in page and "edited" in page
out["tmp_left"] = sorted(p.name for p in pathlib.Path(c.path("paths", "brain"), "projects").iterdir() if p.name.endswith(".tmp"))
print(json.dumps(out))
'''
rc, out, err = py(inst, PLAIN)
try: r = json.loads(out.strip().splitlines()[-1])
except Exception: r = {}
check("plain pages: the page store is the markdown files and reads a page with its revision", rc == 0 and r.get("io") == "PlainIO" and r.get("get") is True, (rc, out[-300:], err[-500:]))
check("plain pages: a stale revision is refused, a path outside the checkout is refused", r.get("stale") == "refused" and r.get("escape_create") == "refused" and r.get("escape_get") == [None, None], r)
check("plain pages: create makes a file, a second create says exists, a put with the right revision writes", r.get("create") == "ok" and r.get("again") == "exists" and r.get("put") == "ok", r)
check("plain pages: the router's timeline note is one line on the page however often it is sent, a missing page is a message not an error", r.get("note1") == "" and r.get("note2") == "" and r.get("lines") == 1 and r.get("has_timeline") and r.get("missing"), r)
check("plain pages: no temporary file is left in the checkout", r.get("tmp_left") == [], r)
for name, args in (("stackshot/projects/rename_page.py", ["plan", "projects/alpha=projects/zeta"]), ("stackshot/projects/page_keeper.py", ["plan"])):
    rc, out, err = sh(sys.executable, os.path.join(STACK, name), *args, cwd=STACK, env=inst["env"])
    check(f"plain pages: {name} refuses with a message that says why, no traceback", rc == 1 and out.startswith("FAIL") and "plain" in out and "Traceback" not in err, (rc, out[:300], err[-300:]))
    check(f"plain pages: {name} prints exactly the refusal, one FAIL line and no note", len(out.strip().splitlines()) == 1 and "note:" not in out and not err.strip(), (rc, out[:400], err[-300:]))

# ---- 4. the server
errf = open(inst["root"] / "server.err", "w+")
env = inst["env"]
def cli(*args, stdin=None):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/fleet/client.py"), *args], capture_output=True, text=True, timeout=120, env=env, cwd=str(inst["root"]), input=stdin)
    return r.returncode, r.stdout, r.stderr
def get(url, timeout=10):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{url}", timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
    except Exception as e: return 0, f"{type(e).__name__}: {e}"
r_ = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "registry"], capture_output=True, text=True, timeout=120, env=env, cwd=str(inst["root"]))
check("setup: the page registry is made from the markdown pages", r_.returncode == 0 and "projects/alpha" in (inst["root"] / "store/projects.json").read_text(), (r_.returncode, r_.stdout[-200:], r_.stderr[-300:]))
rc, out, err = cli("mint", socket.gethostname())
check("setup: this box's client token is minted, pointing at the test's port", rc == 0 and (inst["root"] / "secrets/client.url").read_text().strip() == f"http://127.0.0.1:{port}", (rc, out, err))
proc = subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/web/server.py")], stdout=subprocess.DEVNULL, stderr=errf, cwd=str(inst["root"]), env=env)
try:
    st = 0; end = time.time() + 90
    while time.time() < end and proc.poll() is None:
        st, _ = get("/healthz", 2)
        if st == 200: break
        time.sleep(0.3)
    errf.flush(); errf.seek(0)
    check("the server is up on a random local port: /healthz answers 200", st == 200 and port != 8010, (st, proc.poll(), errf.read()[-800:]))
    if st == 200:
        # ---- the client
        rc, out, err = cli("get", "brief")
        check("client: get brief answers for a fresh board and names none of the owner's names", rc == 0 and out.startswith("Board: 1 open") and not leaks(out), (rc, out[:200], err[:200], leaks(out)))
        rc, out, err = cli("get", "projects", "--scope", "all")
        check("client: get projects lists the scope general", rc == 0 and "general" in out and not leaks(out), (rc, out[:300], err[:200]))
        rc, out, err = cli("help")
        check("client: the usage text names no author (it says the owner by the config's name)", not leaks(out + err, fleet=False), leaks(out + err, fleet=False))
        # ---- a project on plain pages
        rc, out, err = cli("post", "project", "--key", "projects/delta", "--scope", "general", "--title", "Delta", "--sender", "neutral-test")
        beta = inst["root"] / "brain/projects/delta.md"
        check("plain pages: post project makes the page file, the project is listed (no gbrain, no 502)", rc == 0 and beta.is_file() and "# Delta" in beta.read_text(encoding="utf-8") and "gbrain" not in out.lower(), (rc, out[:400], err[:300]))
        check("plain pages: the new page names no author and no fleet tool", beta.is_file() and not leaks(beta.read_text(encoding="utf-8")), leaks(beta.read_text(encoding="utf-8")) if beta.is_file() else "no file")
        rc, out, err = cli("post", "project", "--key", "projects/delta", "--scope", "general", "--title", "Delta", "--sender", "neutral-test")
        check("plain pages: making it again is refused as already there, not as a bad gateway", rc != 0 and "already exists" in (out + err) and "502" not in (out + err), (rc, out[:300], err[:300]))
        rc, out, err = cli("post", "project", "--key", "projects/gamma", "--scope", "work", "--title", "G", "--sender", "neutral-test")
        check("a scope the install does not have is refused with the ones it has", rc != 0 and "general" in (out + err), (rc, out[:300], err[:300]))
        # ---- an item filed and read back
        rc, out, err = cli("post", "question", "--project", "alpha", "--ask", "Decide: whether to ship it · Recommend: ship · Stakes: a day · By: no date", "--subject", "[work] Ship the thing?",
                           "--request-id", "neutral-1", "--sender", "neutral-test", stdin="Ship it now, or wait a day?\n")
        item = out.strip()
        check("client: an item is filed on the neutral board", rc == 0 and re.fullmatch(r"\S+", item) is not None, (rc, out, err))
        st, page = get(f"/items/{item}")
        check("the new item's page renders and names none of the owner's names or a fleet tool", st == 200 and not leaks(page) and OWNER in page, (st, leaks(page)))
        # ---- the main pages (a write publishes the board ~5 s later: the first render is waited for)
        end = time.time() + 60
        while time.time() < end and get("/")[0] == 503: time.sleep(0.5)
        for url in ("/", "/items/a1", "/projects/alpha", "/runners", "/landed", "/search?q=thing", "/manifest.webmanifest"):
            st, page = get(url)
            check(f"page {url}: renders (200) and names none of the owner's names or a fleet tool", st == 200 and not leaks(page), (st, leaks(page), page[:120]))
        # ---- the log
        errf.flush(); errf.seek(0); logtext = errf.read()
        check("the server's log: no traceback, no gbrain, no fleet tool, no author", "Traceback" not in logtext and "gbrain" not in logtext.lower() and not leaks(logtext), (logtext[-600:], leaks(logtext)))
        check("the server is still the same process, still serving", proc.poll() is None and get("/healthz", 5)[0] == 200)
finally:
    proc.terminate()
    try: proc.wait(15)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(10)
    errf.close()
time.sleep(0.2)
with socket.socket() as s:
    free = s.connect_ex(("127.0.0.1", port)) != 0
check("teardown: the server has exited and its port is free", proc.poll() is not None and free, (proc.poll(), free))

if not fails: shutil.rmtree(tmp, ignore_errors=True)
else: print(f"kept for inspection: {tmp}")
print(("ok" if not fails else "FAILED") + f": neutral-install scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
