"""Scenario test for the scripts of a live switch to the front door (tools/frontdoor_{preflight,snapshot,cutover,undo}.py and their shared frontdoor_switch.py).
Every program they run is a stand-in in a temp folder: systemctl, curl, git, ss, journalctl, the checkout's install.sh and release.sh and the Python that runs
the front door's own checks. The stand-ins can be slow, systemctl refuses a unit that is not installed, curl gives up at its --max-time and the journal has
the lines of the board's current run apart from older ones. PATH holds the stand-ins and nothing else of the host (tar and env are reached through links), HOME is a temp folder, no port is
opened and no unit of the host is read or touched. The stand-in systemctl keeps the units' state, reads STACKSHOT_CONFIG from the installed unit files and
their drop-ins at a daemon-reload, and the stand-in curl answers from that state: a board holds the port its config says, and not while the splitter holds it.

Covers: each script's refusals and usage errors; each line of the pre-flight; the snapshot's files, modes, read-backs and member counts, that it keeps an
existing key and prints no secret, and that a dry run writes nothing; each check of the cut-over before the restart (it stops, restarts nothing and says how to
undo) and after it (the board comes back on its old port on the saved config by itself, also on a signal and when the window runs out; the window starts at the
restart); the MANUAL lines and the exit codes; the way back on the saved config and on a reverted one, what it leaves for a person on every end, and when it
does not complete; the cut-over's window over both, from the first restart to the end of the way back; signals before the restart, after it and during a way
back; one run at a time; the saved copy of a kept switch; data folders reached through links; the members list as the board reads it. No run commits or
pushes, and no run touches the board's data.

    tests/run-suite frontdoor_switch        → exit 0 / 1"""
import concurrent.futures, datetime as dt, json, os, pathlib, re, shlex, shutil, signal, subprocess, sys, tarfile, time, traceback
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance

T = pathlib.Path(_scratch.mkdtemp(prefix="frontdoorswitch-"))
TOOLS = pathlib.Path(STACK, "tools")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[-1800:]}" if got is not None else ""), flush=True)

PUBLIC = "https://board.example.invalid"
TOKEN = "t0ken-" + "a1b2c3d4" * 5
BOARD, MINUTE, SYNC, SPLIT = "stackshot.service", "stackshot-minute.service", "stackshot-portal-sync.service", "stackshot-splitter.service"
DOOR, SIGNIN = "stackshot-frontdoor.service", "stackshot-signin.service"
RESTORE = (BOARD, MINUTE, SYNC)
WAITING = "config reload: server.port changed: takes effect at the next restart (after ./install.sh units)"
NEEDED = "e7b4353d3be4a0e5219c8f01cce16f563f6083f9"

# ---------------------------------------------------------------- the stand-ins: one program, told apart by the name it is run under
FAKE = r'''
import fcntl, json, os, pathlib, sys, time, tomllib
W = pathlib.Path(os.environ["FAKE_WORLD"])
name = NAME; args = sys.argv[1:]
HOME = pathlib.Path(os.environ["HOME"])
UNITS = HOME / ".config/systemd/user"

def read():
    return json.loads((W / "state.json").read_text())
def write(s):
    (W / "state.tmp").write_text(json.dumps(s)); os.replace(W / "state.tmp", W / "state.json")
def log(line):
    with open(W / "calls.log", "a") as f: f.write(line + "\n")
def take(s, key):
    """True when a fault named `key` is due: the faults count down, -1 stays for ever."""
    n = s["faults"].get(key, 0)
    if n > 0: s["faults"][key] = n - 1
    return n != 0

def unit_config(unit):
    """STACKSHOT_CONFIG as systemd would read it: the unit file, then its drop-ins in name order, the last assignment winning."""
    value = None
    files = [UNITS / unit] + sorted((UNITS / (unit + ".d")).glob("*.conf"))
    for f in files:
        if not f.is_file(): continue
        for line in f.read_text().splitlines():
            if not line.startswith("Environment="): continue
            v = line[len("Environment="):]
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            v = v.replace("%%", "%")
            if v.startswith("STACKSHOT_CONFIG="): value = v.split("=", 1)[1]
    return value

def table(path):
    try:
        with open(path, "rb") as f: return tomllib.load(f)
    except Exception: return None

def start(s, unit):
    u = s["units"].setdefault(unit, {"enabled": False, "active": False})
    cfg = table(s["loaded"].get(unit) or unit_config(unit) or "")
    u["config"] = s["loaded"].get(unit) or unit_config(unit)
    u["active"] = True; u["failed"] = False
    if unit == "stackshot.service":
        port = (cfg or {}).get("server", {}).get("port")
        sp = s["units"].get("stackshot-splitter.service", {})
        if cfg is None or (sp.get("active") and sp.get("port") == port):
            u["active"] = False; u["failed"] = True
        u["port"] = port
        u["guarded"] = "identity_secret_file" in (cfg or {}).get("behind_frontdoor", {})
        for other, p in (("stackshot-frontdoor.service", 8030), ("stackshot-signin.service", 8031)):
            o = s["units"].get(other)
            if o and (o.get("enabled") or o.get("active")): o["active"] = True; o["port"] = p
    if unit == "stackshot-splitter.service":
        cfg = table(s["config"])
        u["port"] = (cfg or {}).get("frontdoor_splitter", {}).get("listen_port")

def answer(s, port, path):
    sp = s["units"].get("stackshot-splitter.service", {})
    board = s["units"].get("stackshot.service", {})
    if sp.get("active") and sp.get("port") == port:
        if not (board.get("active") and board.get("port") == 8021): return "502"
        return "200" if path == "/healthz" else "401"
    if board.get("active") and board.get("port") == port:
        if path == "/healthz": return "200"
        return "403" if board.get("guarded") else "401"
    for unit in ("stackshot-frontdoor.service", "stackshot-signin.service"):
        u = s["units"].get(unit, {})
        if u.get("active") and u.get("port") == port: return "200"
    return "000"

lock = open(W / "lock", "a"); fcntl.flock(lock, fcntl.LOCK_EX)
s = read()

def done(rc=0, out="", err="", sleep=0):
    write(s); fcntl.flock(lock, fcntl.LOCK_UN)
    if sleep: time.sleep(sleep)
    if out: print(out, flush=True)
    if err: print(err, file=sys.stderr, flush=True)
    sys.exit(rc)

if name == "systemctl":
    a = [x for x in args if x != "--user"]
    log("systemctl " + " ".join(a))
    verb = a[0]; names = [x for x in a[1:] if not x.startswith("-")]
    if verb == "list-units":
        if take(s, "list-units"): done(1, err="Failed to connect to bus")
        done(0, "\n".join(f"{n} loaded active running x" for n in s["releases"]))
    # a slow job: systemctl waits for it, and a caller that gives up leaves it to systemd. "later ..." is slow only once something was restarted
    slow = s["sleep"].get(" ".join(a), 0) or (s["restarted"] and s["sleep"].get("later " + " ".join(a), 0)) or 0
    if verb == "show":
        if take(s, "show"): done(1, err="Failed to connect to bus")
        done(0, s["invocation"])
    if verb == "daemon-reload":
        if take(s, "daemon-reload"): done(1, err="Failed to reload daemon")
        s["loaded"] = {u: unit_config(u) for u in ("stackshot.service", "stackshot-minute.service", "stackshot-portal-sync.service")}
        done(sleep=slow)
    if verb == "reset-failed": done()
    if verb == "is-active":
        u = s["units"].get(names[0], {})
        state = "active" if u.get("active") else "failed" if u.get("failed") else "inactive"
        if names[0] == s.get("stuck"): state = "failed"""
        done(0 if state == "active" else 3, state)
    if verb == "is-enabled":
        on = s["units"].get(names[0], {}).get("enabled")
        done(0 if on else 1, "enabled" if on else "disabled")
    bad = [n for n in names if take(s, f"{verb} {n}")]
    gone = [n for n in names if verb in ("restart", "enable") and not (UNITS / n).is_file()]
    for n in names:
        if n in bad or n in gone: continue
        if verb == "restart": s["restarted"] = True; s.setdefault("restart_at", time.time()); start(s, n)
        elif verb == "enable":
            u = s["units"].setdefault(n, {}); u["enabled"] = True
            if "--now" in a: start(s, n)
        elif verb == "disable":
            u = s["units"].setdefault(n, {}); u["enabled"] = n == s.get("keeps_enabled")
            if "--now" in a: u["active"] = False; u["failed"] = False
        else: done(64, err=f"unknown verb {verb}")
    done(5 if gone else 1 if bad else 0, err="".join(f"Job for {n} failed." for n in bad) + "".join(f"Failed to {verb} {n}: Unit {n} not found." for n in gone), sleep=slow)

if name == "curl":
    method = args[args.index("-X") + 1]; url = args[-1]
    log(f"curl {method} {url}")
    with open(W / "curl.jsonl", "a") as f: f.write(json.dumps(args) + "\n")
    limit = float(args[args.index("--max-time") + 1]) if "--max-time" in args else None
    m = url.split("://", 1)[1]; host, _, path = m.partition("/")
    port = 8020 if url.startswith("https://") else int(host.rsplit(":", 1)[1])
    where = ("public" if url.startswith("https://") else str(port)) + " /" + path
    code = answer(s, port, "/" + path)
    sleep = 0; late = False
    for f in s["http"]:
        if f["at"] == where and f["times"] != 0 and (not f.get("after_restart") or s["restarted"]):
            f["times"] -= 1
            code = f.get("code") or code; sleep = f.get("sleep", 0)
            if f.get("until"): sleep = max(0, s["restart_at"] + f["until"] - time.time())
            late = f.get("late", False)
            break
    if limit is not None and sleep > limit and not late: sleep, code = limit, "000"
    done(0 if code != "000" else 7, code, sleep=sleep)

if name == "git":
    d = None
    if args[:1] == ["-C"]: d, args = args[1], args[2:]
    log("git " + " ".join(args))
    if args[:2] == ["log", "--oneline"]: done(0, "abc1234 the newest commit")
    if args[0] == "merge-base": done(0 if s["has_merge"] and args[2] == s["needed"] else 1)
    if args[0] == "rev-parse": done(1, err="fatal: no HEAD") if take(s, "rev-parse") else done(0, "0123456789abcdef0123456789abcdef01234567")
    if args[0] == "pull":
        if take(s, "pull"): done(1, err="fatal: Not possible to fast-forward, aborting.")
        pending = W / "pending.toml"
        if pending.is_file(): pathlib.Path(s["config"]).write_bytes(pending.read_bytes())
        done(0, "Updating")
    done(64, err="a git command no script may run")

if name == "ss":
    if take(s, "ss"): done(1, err="ss: cannot")
    done(0, "\n".join(f"LISTEN 0 128 127.0.0.1:{p} 0.0.0.0:*" for p in s["ports"]))

if name == "journalctl":
    log("journalctl " + " ".join(args))
    if take(s, "journalctl"): done(1, err="no journal")
    named = [x for x in args if x.startswith("_SYSTEMD_INVOCATION_ID=")]
    lines = (s["journal"] if named == ["_SYSTEMD_INVOCATION_ID=" + s["invocation"]] else []) if named else s["old_journal"] + s["journal"]
    done(0, "\n".join(lines))

if name == "tar":
    log("tar " + args[0])
    listing = args[0].startswith("-t")
    key = "tar-list" if listing else "tar-make"
    rc = s["faults"].get(key, 0)
    if not listing and s["faults"].get("tar-drop"): args = [*args[:2], "--exclude=item.json", *args[2:]]      # an archive that lacks a file, tar content
    write(s); fcntl.flock(lock, fcntl.LOCK_UN)
    import subprocess
    r = subprocess.run([s["tar"], *args], env={**os.environ, "PATH": s["real_path"]})
    sys.exit(rc or r.returncode)

if name == "install.sh":
    log("install.sh " + " ".join(args))
    if take(s, "install"): done(1, err="install.sh: refused")
    cfg = os.environ["STACKSHOT_CONFIG"]
    UNITS.mkdir(parents=True, exist_ok=True)
    for u in ("stackshot.service", "stackshot-minute.service", "stackshot-portal-sync.service", "stackshot-frontdoor.service", "stackshot-signin.service", "stackshot-splitter.service"):
        if u not in s["no_unit"]: (UNITS / u).write_text(f"[Service]\nEnvironment=STACKSHOT_CONFIG={cfg}\n")
    (UNITS / "stackshot.service.d").mkdir(exist_ok=True)
    (UNITS / "stackshot.service.d/portal-sync.conf").write_text("[Unit]\nWants=stackshot-portal-sync.service\n")
    s["loaded"] = {u: unit_config(u) for u in ("stackshot.service", "stackshot-minute.service", "stackshot-portal-sync.service")}
    s.update(s.get("on_install", {}))                  # something that happens while the units are installed
    done(sleep=s["sleep"].get("install", 0) or (s["restarted"] and s["sleep"].get("later install", 0)) or 0)

if name == "release.sh":
    log("release.sh " + " ".join(args))
    if args == ["hold", "--status"]: done(0, s["hold"])
    if args == ["queue", "--list"]: done(1, err="no queue") if take(s, "queue") else done(0, s["queue"])
    if args == ["hold", "--end"]:
        if take(s, "hold-end"): done(1, err="release.sh: cannot end")
        s["hold"] = "no hold on releases"; done(0, "the hold is ended")
    done(64, err="unknown release.sh call")

if name == "fakepy":
    log("py " + " ".join(args if args[0] != "-c" else ["-c"]))
    if args[0] == "-c" and "config.notes()" in args[1]:
        # it runs in the checkout: the config it is pointed at has to be reachable from there
        if take(s, "notes") or not os.path.isfile(os.environ["STACKSHOT_CONFIG"]): done(1, err="the config did not load")
        s_notes = s["notes_after"] if s["notes_after"] is not None and (table(s["config"]) or {}).get("server", {}).get("port") == 8021 else s["notes"]
        done(0, "\n".join(s_notes), err="warning: a word on stderr that is no note")
    if args[:3] == ["-m", "stackshot.core.config", "check"]:
        log("checked " + os.environ["STACKSHOT_CONFIG"])
        done(1, err="config: a refused key") if take(s, "load") else done()
    if args[:3] == ["-m", "stackshot.frontdoor.boardtoken", "--check"]:
        done(1, "board main: token_file does not hold the board's machine token") if take(s, "boardtoken") else done(0, "board main: holds the token")
    if args[:3] == ["-m", "stackshot.frontdoor.check", "--installed"]:
        sp = s["units"].get("stackshot-splitter.service", {})
        log(f"installed-check wait={args[args.index('--wait') + 1]} splitter={'on' if sp.get('active') and sp.get('enabled') else 'off'}")
        (W / "in-installed-check").touch()
        if s.get("lose"): os.unlink(s["lose"])
        if s.get("reverts"): pathlib.Path(s["config"]).write_text(s["reverts"])      # the revert is pulled while the checks run
        if take(s, "installed"): done(1, "FAIL splitter: a client identity header was not refused")
        done(0, "front door check: passed", sleep=s["sleep"].get("installed", 0))
    done(64, err="unknown python call")

done(64, err=f"no stand-in for {name}")
'''
(T / "fake.py").write_text(FAKE, encoding="utf-8")
REAL = {n: shutil.which(n) for n in ("tar", "env")}
assert all(REAL.values()), REAL


def fake_program(path):
    # run_path puts the module's own path in sys.argv[0], so the name the stand-in was run under is handed in
    path.write_text(f"#!{sys.executable} -IS\nimport os, sys, runpy\nrunpy.run_path({str(T / 'fake.py')!r}, init_globals={{'NAME': os.path.basename(sys.argv[0])}}, run_name='__main__')\n"); path.chmod(0o755)


# ---------------------------------------------------------------- configs
def _set(text, table, key, value):
    """`key` of [table] in the example config's text, replaced or added."""
    m = re.search(rf"(?ms)^\[{re.escape(table)}\][^\n]*\n(.*?)(?=^\[|\Z)", text); assert m, table
    body, n = re.subn(rf"(?m)^{key} *=.*$", lambda _: f"{key} = {value}", m.group(1), count=1)
    if not n: body = f"{key} = {value}\n" + body
    return text[:m.start(1)] + body + text[m.end(1):]

BASE = _instance.base_toml()
for tb, k, v in (("instance", "owner", '"Oliver"'), ("instance", "owner_aliases", '["OL", "Boss"]'), ("instance", "timezone", '"UTC"'),
                 ("paths", "repo", '"~/data"'), ("paths", "state", '"~/state"'), ("paths", "secrets", '"~/secrets"'),
                 ("auth", "allowed_emails", '["Person@Example.com", "other@example.com", "third@example.com"]'), ("server", "port", "8020")):
    BASE = _set(BASE, tb, k, v)
assert not re.search(r"(?m)^\[+(frontdoor|behind_frontdoor)", BASE)

def tables(home, port=8020, splitter=8025, switched=False, **change):
    f = home / ".config/stackshot/frontdoor"
    behind = {"verify_secret_file": f'"{f}/verify.key"'}
    if switched:
        behind.update(identity_secret_file=f'"{f}/identity.key"', members_file=f'"{f}/members.json"', board_name='"main"')
    door = {"listen_port": "8030", "identity_header": '"X-Forwarded-User"', "identity_secret_file": f'"{f}/identity.key"', "members_file": f'"{f}/members.json"'}
    backend = {"name": '"main"', "kind": '"board"', "url": f'"http://127.0.0.1:{port}/mcp"', "token_file": f'"{f}/board-token"'}
    signin = {"listen_port": "8031", "board_verify_url": f'"http://127.0.0.1:{port}/frontdoor/verify"', "verify_secret_file": f'"{f}/verify.key"', "accept_portal_token": "true"}
    split = {"listen_port": str(splitter)}
    parts = {"behind_frontdoor": behind, "frontdoor": door, "backend": backend, "frontdoor_signin": signin, "frontdoor_splitter": split}
    for key, value in change.items():
        part, k = key.split("__")
        if value is None: parts[part].pop(k, None)
        else: parts[part][k] = value
    heads = {"behind_frontdoor": "[behind_frontdoor]", "frontdoor": "[frontdoor]", "backend": "[[frontdoor.backends]]", "frontdoor_signin": "[frontdoor_signin]",
             "frontdoor_splitter": "[frontdoor_splitter]"}
    return "".join(f"\n{heads[p]}\n" + "".join(f"{k} = {v}\n" for k, v in kv.items()) for p, kv in parts.items())

# ---------------------------------------------------------------- a world: its own HOME, checkout, config repository and unit state
_n = [0]
class World:
    def __init__(self, config="single", **state):
        _n[0] += 1
        self.dir = T / f"w{_n[0]}-{os.urandom(4).hex()}"
        self.home = self.dir / "home"; self.co = self.dir / "co"; self.repo = self.dir / "conf"; self.bin = self.dir / "bin"; self.backups = self.dir / "backups"
        for d in (self.home / "data", self.home / "state", self.home / "secrets", self.co, self.repo / ".git", self.bin, self.backups): d.mkdir(parents=True)
        (self.home / "data/item.json").write_text('{"title": "before the snapshot"}\n')
        (self.home / "state/ledger.json").write_text("{}\n")
        (self.home / "secrets/oauth.env").write_text(f'# made up\nSTACKSHOT_PORTAL_TOKEN="{TOKEN}"\nOTHER=1\n')
        (self.backups / "board-1.tar.gz").write_text("x")
        for n in ("systemctl", "curl", "git", "ss", "journalctl", "tar", "fakepy"): fake_program(self.bin / n)
        for n in ("install.sh", "release.sh"): fake_program(self.co / n)
        os.symlink(REAL["env"], self.bin / "env")
        os.symlink(sys.executable, self.bin / "python3")              # what a printed command names
        self.config = self.repo / "stackshot.toml"
        self.config.write_text(self.text(config), encoding="utf-8")
        s = {"config": str(self.config), "units": {}, "loaded": {}, "faults": {}, "http": [], "sleep": {}, "releases": [], "ports": [22, 8020], "hold": "no hold on releases",
             "queue": "release queue: empty", "has_merge": True, "needed": NEEDED, "notes": ["note: an old one"], "notes_after": None, "journal": ["boot", WAITING],
             "no_unit": [], "restarted": False, "tar": REAL["tar"], "real_path": os.environ.get("PATH", "/usr/bin:/bin"), "invocation": "0123456789abcdef" * 2, "old_journal": []}
        s.update(state); self.save(s)
        (self.home / ".config/stackshot").mkdir(parents=True, exist_ok=True)     # an instance has it; the scripts' lock goes there
        self.install(*RESTORE)                                        # the units a running board has before any switch
        (self.dir / "calls.log").write_text("")
        self.env = {"HOME": str(self.home), "PATH": str(self.bin), "FAKE_WORLD": str(self.dir), "STACKSHOT_CONFIG": str(self.config), "FRONTDOOR_PUBLIC_URL": PUBLIC,
                    "FRONTDOOR_SWITCH_CHECKOUT": str(self.co), "FRONTDOOR_SWITCH_PYTHON": str(self.bin / "fakepy"), "FRONTDOOR_SWITCH_WINDOW": "300",
                    "FRONTDOOR_SWITCH_CHECK": "0.3", "FRONTDOOR_SWITCH_UNDO_WINDOW": "0.3", "FRONTDOOR_SWITCH_POLL": "0.05", "LANG": "C.UTF-8", "TMPDIR": str(self.dir)}
        self.rollback = self.home / ".config/stackshot/frontdoor-rollback/stackshot.toml"
        self.secrets = self.home / ".config/stackshot/frontdoor"
        self.root = self.home / ".local/share/stackshot-runs/frontdoor-switch"

    def text(self, kind, **change):
        if kind == "single": return BASE
        if kind == "step4": return BASE + tables(self.home)
        base = _set(BASE, "server", "port", "8021")
        port = change.pop("server_port", None)
        if port: base = _set(BASE, "server", "port", port)
        return base + tables(self.home, **{"port": 8021, "splitter": 8020, "switched": True, **change})

    def install(self, *units):
        d = self.home / ".config/systemd/user"; d.mkdir(parents=True, exist_ok=True)
        for u in units: (d / u).write_text(f"[Service]\nEnvironment=STACKSHOT_CONFIG={self.config}\n")

    def state(self): return json.loads((self.dir / "state.json").read_text())
    def save(self, s): (self.dir / "state.json").write_text(json.dumps(s))
    def set(self, **kw): s = self.state(); s.update(kw); self.save(s)
    def fault(self, key, times=-1): s = self.state(); s["faults"][key] = times; self.save(s)
    def slow(self, key, seconds):
        s = self.state(); s["sleep"][key] = seconds; self.save(s)
    def http(self, at, code=None, times=-1, sleep=0, after_restart=True, until=0, late=False):
        s = self.state(); s["http"].append({"at": at, "code": code, "times": times, "sleep": sleep, "after_restart": after_restart, "until": until, "late": late}); self.save(s)
    def calls(self): return (self.dir / "calls.log").read_text().splitlines()
    def clear_calls(self): (self.dir / "calls.log").write_text("")
    def curls(self): return [json.loads(x) for x in (self.dir / "curl.jsonl").read_text().splitlines()]
    def start(self, script, *args):
        """The script as a process of its own, to be sent signals; use as a context: it is ended when the block is left."""
        return Started([sys.executable, str(TOOLS / f"frontdoor_{script}.py"), *map(str, args)], self)
    def run(self, script, *args, env=None, drop=()):
        e = {k: v for k, v in {**self.env, **(env or {})}.items() if k not in drop}
        r = subprocess.run([sys.executable, str(TOOLS / f"frontdoor_{script}.py"), *map(str, args)], env=e, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL, cwd=self.dir)
        return r.returncode, r.stdout + r.stderr
    def files(self):
        """Every file of the world's home and config repository with its content: what a dry run must leave as it is."""
        out = {}
        for top in (self.home, self.repo):
            for p in sorted(top.rglob("*")):
                if p.name != "frontdoor-switch.lock":                 # the writing scripts' own lock
                    out[str(p)] = p.read_bytes() if p.is_file() else None
        return out

    # a world just before the cut-over: the board runs on the step-4 config, door, sign-in and test splitter on, releases held, the switch pushed and not yet pulled
    def ready(self, **pending):
        self.config.write_text(self.text("step4"), encoding="utf-8")
        rc, out = self.run("snapshot", "--expect", "1,2,3", "--apply")
        assert rc == 0, out
        self.snap = next(self.root.iterdir())
        s = self.state()
        s["hold"] = "releases are held by a person until 12:00 (110 min left): front door switch"
        s["units"] = {BOARD: {"enabled": True, "active": True, "port": 8020, "guarded": False}, MINUTE: {"enabled": True, "active": True},
                      DOOR: {"enabled": True, "active": True, "port": 8030}, SIGNIN: {"enabled": True, "active": True, "port": 8031},
                      SPLIT: {"enabled": True, "active": True, "port": 8025}}
        s["loaded"] = {u: str(self.config) for u in RESTORE}
        self.save(s)
        self.install(*RESTORE, DOOR, SIGNIN, SPLIT)
        (self.dir / "pending.toml").write_text(self.text("switched", **pending), encoding="utf-8")
        self.clear_calls()
        return self

    # a world after a cut-over that passed
    def switched(self):
        self.ready()
        rc, out = self.run("cutover", "--snapshot", self.snap, "--apply")
        assert rc == 3, out
        self.clear_calls()
        return self

class Started:
    def __init__(self, argv, w): self.argv, self.w = argv, w
    def __enter__(self):
        self.p = subprocess.Popen(self.argv, env=self.w.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=self.w.dir)
        return self
    def when(self, cond, seconds=60):
        """Wait until cond() holds while the process runs; True when it did."""
        end = time.monotonic() + seconds
        while self.p.poll() is None and time.monotonic() < end:
            if cond(): return True
            time.sleep(0.05)
        return cond()
    def called(self, line): return self.when(lambda: line in self.w.calls())
    def end(self, seconds=60):
        out = self.p.communicate(timeout=seconds)[0]
        return self.p.returncode, out
    def __exit__(self, *_):
        if self.p.poll() is None: self.p.kill(); self.p.communicate(timeout=30)

def acting(calls):
    """The calls that change something."""
    return [c for c in calls if re.match(r"(systemctl (restart|enable|disable|daemon-reload|reset-failed)|install\.sh|release\.sh hold --end|git pull)", c)]
def restarts(calls): return [c for c in calls if c.startswith("systemctl restart")]
def overrides(w): return sorted(w.home.glob(".config/systemd/user/*.d/zz-frontdoor-rollback.conf"))
def bad_git(calls): return [c for c in calls if c.startswith("git ") and not re.match(r"git (log|merge-base|rev-parse|pull --ff-only)", c)]
def line(out, tag, text): return any(l.startswith(tag) and text in l for l in out.splitlines())
def pasteable(out):
    """Every UNDO and KEEP line is a command and nothing else, and no OPTION or OPERATOR line that gives a command has words after it."""
    rows = out.splitlines()
    whole = [l.split(None, 1)[1] for l in rows if l.startswith(("UNDO ", "KEEP "))]
    ends = [l for l in rows if l.startswith(("OPTION ", "OPERATOR ")) and re.search(r"(release\.sh|systemctl|frontdoor_undo\.py|git -C) ", l)]
    return all(shlex.split(c)[0] == "env" and not c.endswith(")") for c in whole) and not [l for l in ends if l.endswith(")")]
def left_for_a_person(out, hold=True):
    """What a way back on the saved config leaves: the saved copy, the revert and push, the pull, the run that removes the override, the hold."""
    need = [("OPERATOR", "revert the commits"), ("OPERATOR", "push"), ("OPERATOR", "pull it on this machine"), ("OPERATOR", "frontdoor_undo.py --apply")]
    if hold: need.append(("OPERATOR", "release.sh hold --end"))
    return all(line(out, tag, text) for tag, text in need) and "keep releases held" in out

CASES = []
def case(fn): CASES.append(fn); return fn

# ================================================================ calls that cannot be run
@case
def usage():
    w = World()
    for script, args in (("preflight", ["--backup-dir", w.backups]), ("snapshot", []), ("cutover", ["--snapshot", w.dir]), ("undo", [])):
        rc, out = w.run(script, *args, drop=("STACKSHOT_CONFIG",))
        check(f"usage: {script} without STACKSHOT_CONFIG exits 2 and says so", rc == 2 and "STACKSHOT_CONFIG is not set" in out, (rc, out))
        rc, out = w.run(script, *args, env={"STACKSHOT_CONFIG": str(w.dir / "none.toml")})
        check(f"usage: {script} with a STACKSHOT_CONFIG that names no file exits 2", rc == 2 and "names no file" in out, (rc, out))
    rc, out = w.run("preflight")
    check("usage: the pre-flight without a backup folder exits 2", rc == 2 and "--backup-dir" in out, (rc, out))
    rc, out = w.run("preflight", "--backup-dir", w.backups, "--baseline", w.dir / "none")
    check("usage: a baseline that is no file exits 2", rc == 2 and "--baseline names no file" in out, (rc, out))
    rc, out = w.run("preflight", "--backup-dir", w.backups, "--confirm", "anything")
    check("usage: an unknown --confirm name exits 2", rc == 2, (rc, out))
    rc, out = w.run("cutover")
    check("usage: the cut-over needs --snapshot", rc == 2 and "--snapshot" in out, (rc, out))
    rc, out = w.run("cutover", "--snapshot", w.dir / "none")
    check("usage: a --snapshot that is no folder exits 2", rc == 2 and "names no folder" in out, (rc, out))
    for script, args in (("cutover", ["--snapshot", w.dir, "--apply"]), ("undo", ["--apply"])):
        rc, out = w.run(script, *args, drop=("FRONTDOOR_PUBLIC_URL",))
        check(f"usage: {script} --apply without the public address exits 2 and changes nothing", rc == 2 and "FRONTDOOR_PUBLIC_URL" in out and not acting(w.calls()), (rc, out, w.calls()))
    w.rollback.parent.mkdir(parents=True); w.rollback.write_text(BASE)
    for script, args in (("cutover", ["--snapshot", w.dir, "--apply"]), ("undo", ["--apply"])):
        rc, out = w.run(script, *args, env={"STACKSHOT_CONFIG": str(w.rollback)})
        check(f"usage: {script} refuses the saved copy as STACKSHOT_CONFIG", rc == 2 and "saved copy" in out and not acting(w.calls()), (rc, out))

# ================================================================ the pre-flight
ALL_MANUAL = ["go", "token-choice", "ssh", "signed-in", "no-long-call"]
def confirmed(): return [x for n in ALL_MANUAL for x in ("--confirm", n)]

@case
def preflight_pass():
    w = World(ports=[22, 8020])
    before = w.files()
    rc, out = w.run("preflight", "--backup-dir", w.backups)
    check("pre-flight: every automated check passes and the manual lines are left: exit 3", rc == 3 and "FAIL" not in out, (rc, out))
    check("pre-flight: one MANUAL line for each thing only a person sees, and how to confirm them", all(line(out, "MANUAL", f"{n}:") and f"--confirm {n}" in out for n in ALL_MANUAL), out)
    check("pre-flight: without a baseline the config notes are printed, and what uv says on stderr is no note", line(out, "NOTE", "note: an old one") and "no note" not in out, out)
    check("pre-flight: it changes nothing", w.files() == before and not acting(w.calls()), w.calls())
    rc, out = w.run("preflight", "--backup-dir", w.backups, *confirmed())
    check("pre-flight: with every manual line confirmed it exits 0", rc == 0 and not line(out, "MANUAL", ""), (rc, out))
    rc, out = w.run("preflight", "--backup-dir", w.backups, *confirmed()[:-2])
    check("pre-flight: one manual line left unconfirmed exits 3 and names it alone", rc == 3 and line(out, "MANUAL", "no-long-call") and not line(out, "MANUAL", "go:"), (rc, out))
    rc, out = w.run("preflight", env={"FRONTDOOR_BACKUP_DIR": str(w.backups)})
    check("pre-flight: the backup folder may come from FRONTDOOR_BACKUP_DIR", rc == 3, (rc, out))
    base = w.dir / "base.txt"; base.write_text("note: an old one\n")
    rc, out = w.run("preflight", "--backup-dir", w.backups, "--baseline", base)
    check("pre-flight: notes equal to the baseline pass", rc == 3 and line(out, "PASS", "baseline's"), (rc, out))

def preflight_fails(name, row, setup, extra=()):
    def run():
        w = World()
        more = setup(w) or []
        rc, out = w.run("preflight", "--backup-dir", w.backups, *confirmed(), *more)
        check(f"pre-flight refuses: {name}", rc == 1 and line(out, "FAIL", row) and not acting(w.calls()), (rc, out))
    run.__name__ = f"preflight {name}"; CASES.append(run)

preflight_fails("a switched config", "[server] port is 8020", lambda w: w.config.write_text(w.text("switched")) and None)
preflight_fails("a splitter on the board's port", "[frontdoor_splitter] listen_port is not 8020", lambda w: w.config.write_text(BASE + tables(w.home, splitter=8020)) and None)
preflight_fails("a config that already names the identity files", "names no identity_secret_file", lambda w: w.config.write_text(BASE + tables(w.home, switched=True)) and None)
preflight_fails("a config that cannot be read", "the config can be read", lambda w: w.config.write_text("[server\n") and None)
preflight_fails("a checkout without the needed merge", "holds the merge", lambda w: w.set(has_merge=False))
preflight_fails("a release hold", "no release hold", lambda w: w.set(hold="releases are held by a person until 12:00 (100 min left): x"))
preflight_fails("a hold state it cannot read", "no release hold", lambda w: w.set(hold="something else"))
preflight_fails("a release waiting in the queue", "release queue is empty", lambda w: w.set(queue="release queue, in order: #12"))
preflight_fails("a paused queue", "release queue is empty", lambda w: w.set(queue="release queue: empty\npaused: a deploy failed"))
preflight_fails("a queue it cannot list", "release queue is empty", lambda w: w.fault("queue"))
preflight_fails("a release in flight", "no release in flight", lambda w: w.set(releases=["stackshot-release-12.service"]))
preflight_fails("a unit list it cannot read", "no release in flight", lambda w: w.fault("list-units"))
for port in (8021, 8025, 8030, 8031):
    preflight_fails(f"port {port} in use", f"busy: {port}", lambda w, port=port: w.set(ports=[22, port]))
def leave_override(w):
    p = w.home / f".config/systemd/user/{MINUTE}.d/zz-frontdoor-rollback.conf"; p.parent.mkdir(parents=True); p.write_text("x\n")
preflight_fails("an override of an earlier way back", "no override of an earlier way back", leave_override)
preflight_fails("config notes it cannot read", "config notes can be read", lambda w: w.fault("notes"))
def other_baseline(w):
    p = w.dir / "base.txt"; p.write_text("note: another\n"); return ["--baseline", p]
preflight_fails("notes that differ from the baseline", "baseline's", other_baseline)
def old_backup(w):
    t = time.time() - 3 * 86400; os.utime(w.backups / "board-1.tar.gz", (t, t))
preflight_fails("a backup that is not of today", "a backup of today", old_backup)
preflight_fails("an empty backup file", "a backup of today", lambda w: (w.backups / "board-1.tar.gz").write_text("") and None)
preflight_fails("no backup folder", "a backup of today", lambda w: shutil.rmtree(w.backups))
for unit in RESTORE:
    preflight_fails(f"{unit} not installed", f"restart are installed", lambda w, unit=unit: (w.home / ".config/systemd/user" / unit).unlink())

@case
def preflight_help():
    rc, out = World().run("preflight", "--help")
    check("pre-flight: --help says that reading the config notes may sync the checkout's environment", rc == 0 and "may first sync" in " ".join(out.split()), (rc, out))

@case
def seconds_settings():
    w = World().ready()
    before = w.files()
    for name, value in (("FRONTDOOR_SWITCH_WINDOW", "nan"), ("FRONTDOOR_SWITCH_WINDOW", "0"), ("FRONTDOOR_SWITCH_WINDOW", "-5"), ("FRONTDOOR_SWITCH_RESERVE", "soon"),
                        ("FRONTDOOR_SWITCH_CHECK", "nan"), ("FRONTDOOR_SWITCH_UNDO_WINDOW", "-inf"), ("FRONTDOOR_SWITCH_POLL", "0")):
        for script, args in (("cutover", ["--snapshot", w.snap, "--apply"]), ("undo", ["--apply", "--snapshot", w.snap])):
            rc, out = w.run(script, *args, env={name: value})
            check(f"usage: {script} refuses {name}={value} before any change", rc == 2 and name in out and not acting(w.calls()) and w.files() == before, (rc, out))
    for value in ("1000", "inf", "300"):
        rc, out = w.run("cutover", "--snapshot", w.snap, env={"FRONTDOOR_SWITCH_WINDOW": value})
        check(f"a window of {value} s is read as 300 s, 90 of them kept for the way back", "would be 300 s, its last 90 s kept" in out, out)
    rc, out = w.run("cutover", "--snapshot", w.snap, env={"FRONTDOOR_SWITCH_WINDOW": "100", "FRONTDOOR_SWITCH_RESERVE": "400"})
    check("no more than half of the window is kept for the way back", "would be 100 s, its last 50 s kept" in out, out)

@case
def relative_config():
    w = World()
    rc, out = w.run("preflight", "--backup-dir", w.backups, env={"STACKSHOT_CONFIG": "conf/stackshot.toml"})
    check("a STACKSHOT_CONFIG relative to where the script is run reaches the programs it runs from the checkout", rc == 3 and line(out, "PASS", "config notes can be read"), (rc, out))
    w = World().ready()
    rc, out = w.run("cutover", "--snapshot", w.snap, "--apply", env={"STACKSHOT_CONFIG": "conf/stackshot.toml"})
    check("a relative STACKSHOT_CONFIG is printed whole in the undo command", rc == 3 and f"STACKSHOT_CONFIG={w.config} " in out, (rc, out))

@case
def preflight_ss():
    w = World(); w.fault("ss")
    rc, out = w.run("preflight", "--backup-dir", w.backups)
    check("pre-flight: ports it cannot list end the run with exit 2", rc == 2 and "ss cannot list" in out, (rc, out))

# ================================================================ the snapshot and the secrets
@case
def snapshot_dry():
    w = World()
    before = w.files()
    rc, out = w.run("snapshot")
    check("snapshot dry run: exit 0, the plan, nothing written", rc == 0 and line(out, "PLAN", "snapshot") and "dry run: nothing written" in out and w.files() == before and not w.root.exists() and not w.secrets.exists(), (rc, out))
    check("snapshot dry run: says what it would do with each secret file", all(line(out, "PLAN", f"{w.secrets / n}: ") for n in ("identity.key", "verify.key", "board-token", "members.json")), out)
    w.config.write_text(w.text("switched"))
    rc, out = w.run("snapshot")
    check("snapshot dry run: a switched config fails", rc == 1 and line(out, "FAIL", "[server] port is 8020") and not w.root.exists(), (rc, out))

@case
def snapshot_apply():
    w = World()
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: passes and exits 0", rc == 0 and "FAIL" not in out, (rc, out))
    dirs = list(w.root.iterdir()) if w.root.exists() else []
    check("snapshot: one new folder, 700, named by date and time", len(dirs) == 1 and dirs[0].stat().st_mode & 0o777 == 0o700 and re.fullmatch(r"\d{8}-\d{6}", dirs[0].name), dirs)
    d = dirs[0]
    names = sorted(p.name for p in d.iterdir())
    check("snapshot: the archive, the config copy, the commit, the notes and the mark that all passed, all 600", names == ["board.tar.gz", "config-notes.txt", "snapshot-complete", "stackshot-head", "stackshot.toml"]
          and all(p.stat().st_mode & 0o777 == 0o600 for p in d.iterdir()), [(p.name, oct(p.stat().st_mode)) for p in d.iterdir()])
    with tarfile.open(d / "board.tar.gz") as tf: members = tf.getnames()
    check("snapshot: the archive holds the data folders and not the secrets", "data/item.json" in members and "state/ledger.json" in members and not [m for m in members if "oauth" in m], members)
    check("snapshot: the copies hold what they name", (d / "stackshot.toml").read_bytes() == w.config.read_bytes() and (d / "stackshot-head").read_text().startswith("0123456789abcdef")
          and (d / "config-notes.txt").read_text() == "note: an old one\n", (d / "config-notes.txt").read_text())
    check("snapshot: the archive is read back with its listing thrown away", "tar -tzf" in w.calls() and "oauth" not in out and "item.json" not in out, w.calls())
    f = w.secrets
    check("secrets: the folder is 700 and the four files 600", f.stat().st_mode & 0o777 == 0o700 and sorted(p.name for p in f.iterdir()) == ["board-token", "identity.key", "members.json", "verify.key"]
          and all(p.stat().st_mode & 0o777 == 0o600 for p in f.iterdir()), [(p.name, oct(p.stat().st_mode)) for p in f.iterdir()])
    ik = (f / "identity.key").read_text(); vk = (f / "verify.key").read_text()
    check("secrets: two different keys of 48 random bytes", len(ik) == 64 and len(vk) == 64 and ik != vk and "\n" not in ik, (len(ik), len(vk)))
    check("secrets: the board's token is copied", (f / "board-token").read_text().strip() == TOKEN)
    check("secrets: the members file has the owner, the aliases and the addresses in lower case", json.loads((f / "members.json").read_text()) ==
          {"Oliver": {"boards": ["main"], "aliases": ["OL", "Boss"], "emails": ["person@example.com", "other@example.com", "third@example.com"]}}, (f / "members.json").read_text())
    check("secrets: no key, token, address or alias is printed", not [x for x in (ik, vk, TOKEN, "person@example.com", "Boss") if x in out], out)
    check("secrets: without a [frontdoor] table the token check is left for later, and said so", "run it after the config save" in out and not [c for c in w.calls() if "boardtoken" in c], out)
    made = shlex.split(next((l for l in out.splitlines() if l.startswith("undo of the secrets")), ": x").split(": ", 1)[1])
    check("snapshot: it prints how to remove what it made, and the next command", f"rm -r {d}" in out and made[:2] == ["rm", "-f"] and sorted(made[2:]) == sorted(str(p) for p in f.iterdir())
          and f"frontdoor_cutover.py --snapshot {d} --apply" in out, out)
    check("snapshot: the mark names the archive's size", (d / "snapshot-complete").read_text() == f"{(d / 'board.tar.gz').stat().st_size}\n")
    kept = {p.name: p.read_bytes() for p in f.iterdir()}
    (f / "board-token").write_text("an-older-token-" + "z" * 30 + "\n")
    time.sleep(1.1)
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot again: keys and members are kept, the token is copied again, a second folder", rc == 0 and {p.name: p.read_bytes() for p in f.iterdir()} == kept and len(list(w.root.iterdir())) == 2 and line(out, "KEPT", "identity.key"), (rc, out))
    check("snapshot again: no removal of a secret is printed, the run made none", "rm -f" not in out and "undo of the secrets" not in out and "rm -r" in out, out)
    (f / "verify.key").unlink(); time.sleep(1.1)
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot with one secret missing: the printed removal names that file alone", rc == 0 and f"undo of the secrets this run made (a file it kept is not removed): rm -f {f / 'verify.key'}\n" in out, (rc, out))

@case
def snapshot_step4_and_data():
    w = World(config="step4")
    other = w.dir / "elsewhere/board"; other.mkdir(parents=True); (other / "x.json").write_text("{}")
    rc, out = w.run("snapshot", "--data", other, "--data", "data", "--expect", "1,2,3", "--apply", env={"FRONTDOOR_SNAPSHOT_ROOT": str(w.dir / "snaps"), "FRONTDOOR_SECRETS_DIR": str(w.dir / "sec")})
    snaps = list((w.dir / "snaps").iterdir())
    with tarfile.open(snaps[0] / "board.tar.gz") as tf: members = tf.getnames()
    check("snapshot --data: the folders given, one outside home among them, and no other", rc == 0 and "board/x.json" in members and "data/item.json" in members and "state/ledger.json" not in members, (rc, members, out))
    check("snapshot: the root and the secrets folder can be moved by the environment", (w.dir / "sec/identity.key").is_file() and not w.secrets.exists())
    check("snapshot: with a [frontdoor] table the token check runs", [c for c in w.calls() if "boardtoken --check" in c] and line(out, "PASS", "frontdoor-token --check"), out)
    w.fault("boardtoken")
    time.sleep(1.1)
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: a failing token check fails the run", rc == 1 and line(out, "FAIL", "frontdoor-token --check"), (rc, out))

def snapshot_fails(name, row, setup, expect="1,2,3", wrote=True, secrets_started=False):
    def run():
        w = World()
        more = setup(w) or []
        there = sorted(p.name for p in w.secrets.iterdir()) if w.secrets.exists() else []
        rc, out = w.run("snapshot", "--expect", expect, "--apply", *more)
        check(f"snapshot fails: {name}", rc == 1 and line(out, "FAIL", row), (rc, out))
        now = sorted(p.name for p in w.secrets.iterdir()) if w.secrets.exists() else []
        check(f"snapshot fails: {name}: {'the secrets step is not started, and no removal of a secret is printed' if not secrets_started else 'no secret is printed'}",
              (now == there and "secrets step was not started" in out and "rm -f" not in out) if not secrets_started else TOKEN not in out, out)
        check(f"snapshot fails: {name}: no snapshot is marked as passed", not list(w.root.glob("*/snapshot-complete")) or secrets_started, out)
        if not wrote: check(f"snapshot fails: {name}: no snapshot folder", not w.root.exists() or not list(w.root.iterdir()), out)
    run.__name__ = f"snapshot {name}"; CASES.append(run)

snapshot_fails("a switched config", "[server] port is 8020", lambda w: w.config.write_text(w.text("switched")) and None, wrote=False)
snapshot_fails("a data folder that is not there", "state exists", lambda w: shutil.rmtree(w.home / "state"), wrote=False)
snapshot_fails("a snapshot root inside the data", "is not inside", lambda w: w.env.update(FRONTDOOR_SNAPSHOT_ROOT=str(w.home / "state/snaps")), wrote=False)
snapshot_fails("tar failing", "tar of the data folders", lambda w: w.fault("tar-make", 2))
snapshot_fails("an archive that does not read back", "the archive reads back", lambda w: w.fault("tar-list", 2))
snapshot_fails("an archive that lacks a file", "holds the content of the data folders (2 files, 1 not in it", lambda w: w.fault("tar-drop"))
snapshot_fails("a commit it cannot read", "commit can be read", lambda w: w.fault("rev-parse"), wrote=False)
snapshot_fails("config notes it cannot read", "config notes can be read", lambda w: w.fault("notes"), wrote=False)
for expect in ("2,2,3", "1,1,3", "1,2,4"):
    snapshot_fails(f"member counts other than {expect}", "holds 1 member, 2 aliases, 3 addresses (expected", lambda w: None, expect=expect, wrote=False)
snapshot_fails("no oauth.env", "board-token holds", lambda w: (w.home / "secrets/oauth.env").unlink(), secrets_started=True)
snapshot_fails("a short machine token", "board-token holds", lambda w: (w.home / "secrets/oauth.env").write_text("STACKSHOT_PORTAL_TOKEN=short\n") and None, secrets_started=True)
def keys(w, a, b):
    w.secrets.mkdir(parents=True)
    for n, v in (("identity.key", a), ("verify.key", b)):
        (w.secrets / n).write_text(v); (w.secrets / n).chmod(0o600)
snapshot_fails("a kept key that is too short", "identity.key has 31 characters", lambda w: keys(w, "k" * 31, "v" * 40), secrets_started=True)
snapshot_fails("two kept keys that are the same", "identity.key and verify.key differ", lambda w: keys(w, "k" * 40, "k" * 40), secrets_started=True)
def loose(w):
    keys(w, "k" * 32, "v" * 32); (w.secrets / "verify.key").chmod(0o644)
snapshot_fails("a kept key others can read", "verify.key is there and 600", loose, secrets_started=True)
def broken_members(w):
    w.secrets.mkdir(parents=True); (w.secrets / "members.json").write_text("not json"); (w.secrets / "members.json").chmod(0o600)
snapshot_fails("a members file that cannot be read", "can be read by the front door", broken_members, wrote=False)
def other_members(w):
    w.secrets.mkdir(parents=True); (w.secrets / "members.json").write_text('{"Someone": {"boards": ["main"], "aliases": [], "emails": []}}'); (w.secrets / "members.json").chmod(0o600)
snapshot_fails("a members file that is there with other numbers", "holds 1 member, 0 aliases, 0 addresses (expected", other_members, wrote=False)

LISTED = """
[[members]]
name = "Ada"
aliases = ["AL", "AL", "you"]
emails = ["Ada@Example.com"]
agents = ["writer"]

[[members]]
name = "Bo"
aliases = ["B"]
emails = ["bo@example.com", "bo2@example.com"]
"""

@case
def snapshot_listed_members():
    w = World(); w.config.write_text(BASE + LISTED, encoding="utf-8")
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("members: [[members]] is what the board reads, so --expect for the old keys fails before anything is written", rc == 1 and line(out, "FAIL", "holds 2 member, 2 aliases, 3 addresses")
          and not w.secrets.exists() and not w.root.exists(), (rc, out))
    rc, out = w.run("snapshot", "--expect", "2,2,3", "--apply")
    got = json.loads((w.secrets / "members.json").read_text()) if (w.secrets / "members.json").exists() else None
    check("members: the file holds each member of [[members]], as the board reads them", rc == 0 and got ==
          {"Ada": {"boards": ["main"], "aliases": ["AL"], "emails": ["ada@example.com"]}, "Bo": {"boards": ["main"], "aliases": ["B"], "emails": ["bo@example.com", "bo2@example.com"]}}, (rc, got, out))
    check("members: the sessions acting for a member are named as lost behind the front door, and no name or address is printed", line(out, "NOTE", "1 sessions") and "Ada" not in out and "bo@" not in out, out)
    (w.secrets / "members.json").write_text(json.dumps({**got, "Bo": {**got["Bo"], "emails": ["x@example.com", "y@example.com"]}}))
    time.sleep(1.1)
    rc, out = w.run("snapshot", "--expect", "2,2,3", "--apply")
    check("members: a file that is there stays, and a difference from the config is said", rc == 0 and line(out, "NOTE", "differs from what the config gives") and "x@example.com" in (w.secrets / "members.json").read_text(), (rc, out))
    rc, out = w.run("snapshot", "--expect", "2,2,3")
    check("members: a dry run checks the numbers too", rc == 0 and line(out, "PASS", "holds 2 member, 2 aliases, 3 addresses"), (rc, out))

for what, extra, secret in (("a name the front door's headers cannot carry", '\n[[members]]\nname = "Z' + chr(0xe9) + '"\n', chr(0xe9)),
                            ("an address without an @", '\n[[members]]\nname = "Cy"\nemails = ["not-an-address"]\n', "not-an-address")):
    def dropped(extra=extra, secret=secret, what=what):
        w = World(); w.config.write_text(BASE + LISTED + extra, encoding="utf-8")
        rc, out = w.run("snapshot", "--expect", "3,3,3", "--apply")
        check(f"members: {what} is refused before anything is written, with no name printed", rc == 1 and line(out, "FAIL", "the front door reads every entry") and not w.secrets.exists()
              and not w.root.exists() and secret not in out, (rc, out))
    dropped.__name__ = f"members {what}"; CASES.append(dropped)

@case
def members_the_board_refuses():
    w = World(); w.config.write_text(BASE + LISTED + '\n[[members]]\nname = "Cyrus"\naliases = ["AL"]\n', encoding="utf-8")
    rc, out = w.run("snapshot", "--expect", "3,3,3", "--apply")
    check("members: a config the board's own code refuses exits 2 before anything is written, says how to see why, and prints no name or alias", rc == 2 and "stackshot.core.config check" in out
          and not w.secrets.exists() and not w.root.exists() and '"AL"' not in out and "Cyrus" not in out, (rc, out))

@case
def members_one_name_twice():
    w = World(); w.config.write_text(BASE + LISTED + '\n[[members]]\nname = "Ada"\n', encoding="utf-8")
    rc, out = w.run("snapshot", "--expect", "2,1,2", "--apply")
    check("members: two members with one name are refused by the board's own code before anything is written, whatever counts are expected", rc == 2 and "refuses this config" in out
          and not w.secrets.exists() and not w.root.exists(), (rc, out))

@case
def snapshot_links():
    w = World()
    real = w.dir / "disk/boarddata"; real.parent.mkdir(); shutil.move(w.home / "data", real); os.symlink(real, w.home / "data")
    os.symlink(real / "item.json", real / "latest")                 # a link that stays inside
    os.symlink("/nowhere/at/all", w.home / "state/gone")             # a link to nothing holds nothing
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    d = next(w.root.iterdir(), None) if w.root.exists() else None
    members = {m.name: m for m in tarfile.open(d / "board.tar.gz")} if d else {}
    check("snapshot: a data folder that is a link is followed: the archive holds the files", rc == 0 and "boarddata/item.json" in members and members["boarddata/item.json"].isreg() and "state/ledger.json" in members, (rc, list(members), out))
    check("snapshot: it says which folder is behind the link", line(out, "NOTE", f"{w.home / 'data'} is {real}"), out)
    w = World(); out_there = w.dir / "outside"; out_there.mkdir(); (out_there / "kept.json").write_text("{}"); os.symlink(out_there, w.home / "state/extra")
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: a link inside the data that leads outside it is refused before anything is written, with how to list it", rc == 1 and line(out, "FAIL", "no link in the data folders leads outside")
          and "-type l" in out and "kept.json" not in out and not w.root.exists() and not w.secrets.exists(), (rc, out))
    rc, out = w.run("snapshot", "--data", "data", "--data", "state", "--data", out_there, "--expect", "1,2,3", "--apply")
    members = tarfile.open(next(w.root.iterdir()) / "board.tar.gz").getnames() if w.root.exists() else []
    check("snapshot: with the folder the link leads to given too, it passes and holds it", rc == 0 and "outside/kept.json" in members, (rc, members, out))
    w = World(); (w.dir / "one.json").write_text("{}"); os.symlink(w.dir / "one.json", w.home / "data/one")
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: a link to a file outside the data is refused too", rc == 1 and line(out, "FAIL", "(1 do"), (rc, out))

@case
def snapshot_modes():
    w = World()
    w.secrets.mkdir(parents=True); w.secrets.chmod(0o755)
    r = subprocess.run([sys.executable, str(TOOLS / "frontdoor_snapshot.py"), "--expect", "1,2,3", "--apply"], env=w.env, capture_output=True, text=True, timeout=120, cwd=w.dir, preexec_fn=lambda: os.umask(0))
    check("snapshot under an open umask: every folder it makes is closed to others", r.returncode == 0 and all(p.stat().st_mode & 0o077 == 0 for p in [w.root, w.root.parent, w.root.parent.parent, *w.root.rglob("*")]),
          (r.returncode, [(str(p), oct(p.stat().st_mode)) for p in [w.root, w.root.parent, *w.root.rglob("*")]], r.stdout))
    check("snapshot: a secrets folder that was open to others is closed", w.secrets.stat().st_mode & 0o777 == 0o700, oct(w.secrets.stat().st_mode))
    w = World(); w.secrets.mkdir(parents=True); os.symlink(w.dir / "target", w.secrets / "identity.key")
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: a key name that is a link to nothing is kept as it is: nothing is written through it, and the run fails", rc == 1 and (w.secrets / "identity.key").is_symlink() and not (w.dir / "target").exists()
          and line(out, "KEPT", "identity.key"), (rc, out))

@case
def snapshot_tar_changed():
    w = World(); w.fault("tar-make", 1)
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot: tar's exit 1 (a file changed while it was read) passes", rc == 0 and line(out, "PASS", "exit 1"), (rc, out))

@case
def snapshot_usage():
    w = World()
    for args, said in ((["--apply"], "--expect"), (["--expect", "1,2", "--apply"], "three whole numbers"), (["--expect", "1,x,3"], "three whole numbers")):
        rc, out = w.run("snapshot", *args)
        check(f"snapshot usage: {args} exits 2 and writes nothing", rc == 2 and said in out and not w.root.exists() and not w.secrets.exists(), (rc, out))
    w.config.write_text(_set(BASE, "instance", "owner", '""'))
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    check("snapshot usage: a config with nobody to write as a member exits 2 before anything is written", rc == 2 and "owner" in out and not w.root.exists() and not w.secrets.exists(), (rc, out))
    w.config.write_text("[server\n")
    rc, out = w.run("snapshot")
    check("snapshot usage: a config that cannot be read exits 2", rc == 2 and "cannot be read" in out, (rc, out))

# ================================================================ the cut-over
def cut(w, *more, **kw): return w.run("cutover", "--snapshot", w.snap, *more, **kw)

@case
def cutover_dry():
    w = World().ready()
    before = w.files()
    rc, out = cut(w)
    check("cut-over dry run before the pull: the settings that are not there yet fail, nothing is written", rc == 1 and line(out, "FAIL", "[server] port is 8021") and w.files() == before and not acting(w.calls()), (rc, out, w.calls()))
    w.config.write_text(w.text("switched"))
    before = w.files()
    rc, out = cut(w)
    check("cut-over dry run on the switched config: exit 0, the plan, no unit touched", rc == 0 and "dry run: nothing changed" in out and w.files() == before and not acting(w.calls()), (rc, out, w.calls()))
    check("cut-over dry run: lists the manual checks", all(line(out, "PLAN", f"manual afterwards: {n}:") for n in ("portal", "connector", "browser", "tailnet", "polls")), out)

@case
def cutover_pass():
    w = World().ready()
    data = (w.home / "data/item.json").read_bytes()
    rc, out = cut(w, "--apply")
    calls = w.calls()
    check("cut-over: every automated check passes and manual ones are pending: exit 3", rc == 3 and "FAIL" not in out and "MANUAL checks are pending" in out, (rc, out))
    order = [next((i for i, c in enumerate(calls) if c.startswith(p)), -1) for p in ("git pull --ff-only", "install.sh units", "journalctl", f"systemctl disable --now {SPLIT}",
             f"systemctl restart {BOARD} {MINUTE}", f"systemctl enable --now {SPLIT}", f"systemctl restart {SYNC}", "installed-check")]
    check("cut-over: pull, units, journal, splitter off, restart, splitter on, portal sync, installed check, in that order", -1 not in order and order == sorted(order), (order, calls))
    check("cut-over: the installed check runs with the splitter on and waits 90 s", "installed-check wait=90 splitter=on" in calls, calls)
    check("cut-over: the checks it makes", [c for c in calls if c.startswith("curl")] == ["curl GET http://127.0.0.1:8021/healthz", "curl GET http://127.0.0.1:8020/healthz", "curl GET http://127.0.0.1:8021/healthz", "curl GET http://127.0.0.1:8030/healthz",
          "curl GET http://127.0.0.1:8031/healthz", "curl POST http://127.0.0.1:8021/mcp", "curl GET http://127.0.0.1:8020/healthz", "curl POST http://127.0.0.1:8020/mcp",
          f"curl GET {PUBLIC}/healthz", f"curl POST {PUBLIC}/mcp"], calls)
    ident = w.state()["invocation"]
    check("cut-over: the journal of the board's current run is read, for the last five minutes", f"systemctl show --property=InvocationID --value {BOARD}" in calls
          and [c for c in calls if c.startswith("journalctl") and f"_SYSTEMD_INVOCATION_ID={ident} --since -5min" in c], calls)
    check("cut-over: the hold and the releases are asked once more right before the restart", [c for c in calls if c.startswith(("release.sh hold --status", "systemctl list-units", f"systemctl restart {BOARD}", f"systemctl disable --now {SPLIT}"))][-4:-1]
          == [f"systemctl disable --now {SPLIT}", "release.sh hold --status", calls[next(i for i, c in enumerate(calls) if c.startswith("systemctl list-units"))]], calls)
    curls = w.curls()
    waits = [c[c.index("--max-time") + 1] for c in curls if ":8031/" in c[-1]]
    check("cut-over: a health wait asks for no longer than it has left", waits and set(waits) == {"1"}, waits)
    check("cut-over: every request has a time limit of 5 s at most", curls and all("--max-time" in c and 1 <= float(c[c.index("--max-time") + 1]) <= 5 for c in curls), curls)
    check("cut-over: a request to this machine goes past any proxy, one to the public address does not", all(("--noproxy" in c) == c[-1].startswith("http://127.0.0.1:") for c in curls)
          and all(c[c.index("--noproxy") + 1] == "*" for c in curls if "--noproxy" in c), curls)
    check("cut-over: the printed lines can be pasted", pasteable(out) and line(out, "KEEP", "frontdoor_undo.py --apply --drop-saved"), out)
    check("cut-over: the saved config was loaded by the checkout's code before anything", f"checked {w.snap / 'stackshot.toml'}" in calls, calls)
    check("cut-over: a MANUAL line for each check a person makes, the time they are due and the undo command", all(line(out, "MANUAL", f"{n}:") for n in ("portal", "connector", "browser", "tailnet", "polls"))
          and re.search(r"make them by \d\d:\d\d:\d\d UTC", out) and line(out, "UNDO", "frontdoor_undo.py --apply") and f"STACKSHOT_CONFIG={w.config}" in out, out)
    check("cut-over: the saved config is put aside, 600, and no override is written", w.rollback.read_bytes() == (w.snap / "stackshot.toml").read_bytes() and w.rollback.stat().st_mode & 0o777 == 0o600
          and w.rollback.parent.stat().st_mode & 0o777 == 0o700 and not overrides(w), overrides(w))
    check("cut-over: commits and pushes nothing, ends no hold, leaves the data", not bad_git(calls) and "release.sh hold --end" not in calls and (w.home / "data/item.json").read_bytes() == data, calls)
    s = w.state()["units"]
    check("cut-over: the splitter holds 8020, the board 8021", s[SPLIT]["active"] and s[SPLIT]["port"] == 8020 and s[BOARD]["active"] and s[BOARD]["port"] == 8021, s)
    undo = shlex.split(next(l for l in out.splitlines() if l.startswith("UNDO")).split(None, 1)[1])
    r = subprocess.run(undo, env=w.env, capture_output=True, text=True, timeout=120)
    check("cut-over: the printed undo command brings the board back as it stands", r.returncode == 4 and w.state()["units"][BOARD]["port"] == 8020 and w.state()["units"][BOARD]["active"], (r.returncode, r.stdout + r.stderr))

@case
def cutover_window_starts_at_restart():
    w = World().ready(); w.slow("install", 22)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": "20"})
    check("the window starts at the restart: a step before it that takes longer than the whole window takes nothing from it", rc == 3 and "FAIL" not in out, (rc, out))

@case
def cutover_hold_edge():
    w = World().ready(); w.set(hold="releases are held by a person until 12:00 (15 min left): x")
    rc, out = cut(w, "--apply")
    check("cut-over: a hold with exactly 15 minutes left is enough", rc == 3, (rc, out))

for what, change, row in (("the hold ends", {"hold": "no hold on releases"}, "the release hold is still on"), ("a release starts", {"releases": ["stackshot-release-7.service"]}, "still no release is running")):
    def meanwhile(what=what, change=change, row=row):
        w = World().ready(); w.set(on_install=change)
        rc, out = cut(w, "--apply")
        check(f"cut-over: {what} while the units are installed: seen right before the restart, nothing restarted", rc == 1 and line(out, "FAIL", row) and not restarts(w.calls())
              and "STOPPED before the restart" in out, (rc, out))
    meanwhile.__name__ = f"meanwhile {what}"; CASES.append(meanwhile)

def stops(name, row, setup=None, pulled=True, pending=None):
    """A check before the restart that fails: the run stops, restarts nothing, writes no override, and says how to undo."""
    def run():
        w = World().ready(**(pending or {}))
        if setup: setup(w)
        rc, out = cut(w, "--apply")
        calls = w.calls()
        check(f"before the restart, {name}: stops with exit 1", rc == 1 and line(out, "FAIL", row) and "STOPPED before the restart" in out, (rc, out))
        check(f"before the restart, {name}: nothing is restarted or enabled, no override, no way back on its own", not restarts(calls) and not [c for c in calls if c.startswith("systemctl enable")]
              and not [c for c in calls if c.startswith("curl GET http://127.0.0.1:8030")] and "bringing the board back" not in out and not bad_git(calls), (calls, out))
        check(f"before the restart, {name}: prints the undo command with the snapshot", line(out, "UNDO", f"frontdoor_undo.py --apply --snapshot {w.snap}"), out)
        check(f"before the restart, {name}: the printed lines can be pasted", pasteable(out) and line(out, "OPTION", "release.sh hold --end"), out)
        shows = "the config on disk shows the switch" in out
        check(f"before the restart, {name}: says whether the config on disk shows the switch", shows == pulled and (("still a single-user config" in out) != pulled), out)
        if pulled: check(f"before the restart, {name}: names the operator's steps", line(out, "OPERATOR", "revert the config commit") and line(out, "OPERATOR", "./install.sh units"), out)
    run.__name__ = f"stop {name}"; CASES.append(run)

stops("no release hold", "release hold on", lambda w: w.set(hold="no hold on releases"), pulled=False)
stops("a hold with 14 minutes left", "release hold on", lambda w: w.set(hold="releases are held by a person until 12:00 (14 min left): x"), pulled=False)
stops("a hold that says no time left", "release hold on", lambda w: w.set(hold="releases are held by a person: x"), pulled=False)
stops("a release in the queue", "release queue is empty", lambda w: w.set(queue="release queue, in order: #12"), pulled=False)
stops("a release running", "no release is running", lambda w: w.set(releases=["stackshot-release-9.service"]), pulled=False)
stops("a unit list that cannot be read", "no release is running", lambda w: w.fault("list-units"), pulled=False)
stops("no saved config", "single-user config to come back on", lambda w: (w.snap / "stackshot.toml").unlink(), pulled=False)
stops("a saved config that shows the switch", "single-user config to come back on", lambda w: (w.snap / "stackshot.toml").write_text(w.text("switched")) and None, pulled=False)
stops("a saved config this code cannot load", "can load the saved config", lambda w: w.fault("load"), pulled=False)
stops("no list of config notes", "list of config notes", lambda w: (w.snap / "config-notes.txt").unlink(), pulled=False)
stops("no archive", "holds its archive", lambda w: (w.snap / "board.tar.gz").unlink(), pulled=False)
stops("an empty archive", "holds its archive", lambda w: (w.snap / "board.tar.gz").write_bytes(b"") and None, pulled=False)
stops("an override of an earlier way back", "no override of an earlier way back", leave_override, pulled=False)
stops("a pull that fails", "the config is pulled", lambda w: w.fault("pull"), pulled=False)
SETTING_FAULTS = (
    ("server_port", "8022", "[server] port is 8021"),
    ("behind_frontdoor__identity_secret_file", '"/elsewhere"', "identity_secret_file is the front door's"),
    ("behind_frontdoor__members_file", None, "members_file is the front door's"),
    ("behind_frontdoor__board_name", '"other"', "board_name is main"),
    ("backend__url", '"http://127.0.0.1:8020/mcp"', "main is the board on 8021"),
    ("frontdoor_signin__board_verify_url", '"http://127.0.0.1:8020/frontdoor/verify"', "board_verify_url is the board on 8021"),
    ("frontdoor_signin__accept_portal_token", None, "accept_portal_token is answered"),
    ("frontdoor_splitter__listen_port", "8025", "listen_port is 8020"),
)
for key, value, row in SETTING_FAULTS:
    stops(f"a wrong setting ({row})", row, pending={key: value})
stops("a config note outside the baseline", "no config note outside the baseline", lambda w: w.set(notes_after=["note: an old one", "note: a new one"]))
stops("config notes that cannot be read", "no config note outside the baseline", lambda w: w.fault("notes"))
stops("a token the front door does not hold", "holds the board's machine token", lambda w: w.fault("boardtoken"))
stops("install.sh failing", "units rendered and installed", lambda w: w.fault("install"))
def no_unit(unit):
    def setup(w):
        w.set(no_unit=[unit]); (w.home / ".config/systemd/user" / unit).unlink(missing_ok=True)
    return setup
for unit in (BOARD, MINUTE, SYNC, DOOR, SIGNIN, SPLIT):
    stops(f"{unit} not installed", "every unit", no_unit(unit))
stops("a journal with no waiting key", "waits for the next restart", lambda w: w.set(journal=["boot"]))
stops("a waiting line of an earlier run alone", "waits for the next restart", lambda w: w.set(journal=["boot"], old_journal=[WAITING]))
stops("a waiting line about another key alone", "waits for the next restart", lambda w: w.set(journal=["config reload: behind_frontdoor changed: takes effect at the next restart (x)"]))
stops("a board whose current run systemd cannot name", "waits for the next restart", lambda w: w.fault("show"))
stops("a snapshot that is not marked as passed", "passed every check of its own run", lambda w: (w.snap / "snapshot-complete").unlink(), pulled=False)
stops("an archive of another size than the mark's", "passed every check of its own run", lambda w: (w.snap / "board.tar.gz").write_bytes(b"cut short") and None, pulled=False)
stops("a journal that cannot be read", "waits for the next restart", lambda w: w.fault("journalctl"))
stops("a board that stopped answering", "still answers on 8020", lambda w: w.http("8020 /healthz", "500", after_restart=False))
stops("a splitter that does not stop", "splitter is disabled and stopped", lambda w: w.fault(f"disable {SPLIT}"))
stops("a splitter that stops and stays enabled", "splitter is disabled and stopped", lambda w: w.set(keeps_enabled=SPLIT))

@case
def failed_tar_is_not_cut_over():
    w = World(config="step4"); w.fault("tar-make", 2)
    rc, out = w.run("snapshot", "--expect", "1,2,3", "--apply")
    snap = next(w.root.iterdir())
    w.set(hold="releases are held by a person until 12:00 (110 min left): x"); w.clear_calls()
    rc2, out2 = w.run("cutover", "--snapshot", snap, "--apply")
    check("a snapshot whose tar failed is refused by the cut-over", rc == 1 and rc2 == 1 and line(out2, "FAIL", "passed every check of its own run") and not restarts(w.calls())
          and "frontdoor_cutover.py" not in out, (rc, rc2, out2))

@case
def cutover_twice():
    w = World().switched()
    before = w.state()["units"]
    rc, out = cut(w, "--apply")
    check("cut-over run again after the switch: stops first, touches no unit, the splitter keeps serving", rc == 1 and line(out, "FAIL", "the board has not moved yet") and "needs no second cut-over" in out
          and not acting(w.calls()) and w.state()["units"] == before and "the config on disk shows the switch" not in out, (rc, out, w.calls()))
    rc, out = cut(w)
    check("cut-over dry run after the switch: the same stop", rc == 1 and "would stop at: the board has not moved yet" in out and not acting(w.calls()), (rc, out))

@case
def cutover_note_and_baseline():
    w = World().ready()
    (w.dir / "pending.toml").write_text(_set(w.text("switched"), "instance", "board_url", '"https://new.example.invalid"'))
    w.set(notes_after=[])
    rc, out = cut(w, "--apply")
    check("cut-over: a note that went away is no surprise", rc == 3, (rc, out))
    check("cut-over: names settings outside the switch that differ from the saved config, never their values", line(out, "NOTE", "[instance] board_url") and "new.example.invalid" not in out, out)

def comes_back(name, row, setup, env=None):
    """A check after the restart that fails: the board comes back by itself on its old port on the saved config."""
    def run():
        w = World().ready()
        setup(w)
        data = w.home / "data/item.json"; data.write_text('{"title": "written after the snapshot"}\n')
        switched_text = (w.dir / "pending.toml").read_bytes()
        rc, out = cut(w, "--apply", env=env)
        check(f"after the restart, {name}: leaves every step for a person, each line pasteable", left_for_a_person(out) and pasteable(out), out)
        s = w.state()["units"]; calls = w.calls()
        stopped = [l for l in out.splitlines() if l.startswith("stopped: ")]
        check(f"after the restart, {name}: exit 4, stopped at that check", rc == 4 and stopped and row in stopped[0] and "bringing the board back now" in out, (rc, out))
        check(f"after the restart, {name}: the board runs on its old port on the saved config, the splitter off", s[BOARD]["active"] and s[BOARD]["port"] == 8020 and s[BOARD]["config"] == str(w.rollback)
              and not s[SPLIT]["active"] and not s[SPLIT]["enabled"], (s, out))
        check(f"after the restart, {name}: all three units read the saved config", len(overrides(w)) == 3 and all(s[u]["config"] == str(w.rollback) for u in RESTORE), (overrides(w), s))
        check(f"after the restart, {name}: says the revert is left, with the command", "THE BOARD IS BACK" in out and line(out, "OPERATOR", "revert the commits") and line(out, "OPERATOR", "frontdoor_undo.py --apply")
              and line(out, "OPERATOR", "pull --ff-only"), out)
        check(f"after the restart, {name}: no data is touched and it says so; the config is not edited, nothing committed or pushed, the hold stays",
              "no data was restored or removed" in out and data.read_text().endswith('after the snapshot"}\n') and w.config.read_bytes() == switched_text and not bad_git(calls)
              and not [c for c in calls if c.startswith(("tar -x", "release.sh hold --end"))] and "keep releases held" in out, (calls, out))
    run.__name__ = f"back {name}"; CASES.append(run)

comes_back("the board's restart failing", "the board and the minute runner are restarted", lambda w: w.fault(f"restart {BOARD}", 1))
comes_back("the minute runner's restart failing", "the board and the minute runner are restarted", lambda w: w.fault(f"restart {MINUTE}", 1))
for port in (8021, 8030, 8031):
    comes_back(f"no health on {port}", f"answers on {port} (healthz)", lambda w, port=port: w.http(f"{port} /healthz", "503"))
comes_back("a board that lets a call without the front door in", "refuses a call without the front door", lambda w: w.http("8021 /mcp", "200", times=1))
comes_back("the splitter not starting", "the splitter is enabled and started", lambda w: w.fault(f"enable {SPLIT}", 1))
comes_back("the portal sync's restart failing", "the portal sync is restarted", lambda w: w.fault(f"restart {SYNC}", 1))
comes_back("the installed check failing", "check --installed` passes", lambda w: w.fault("installed", 1))
comes_back("no health through the splitter", "the board answers on 8020", lambda w: w.http("8020 /healthz", "502", times=1, sleep=0.4))
comes_back("no refusal on 8020", "refused on 8020", lambda w: w.http("8020 /mcp", "200", times=1))
comes_back("no public health", "the public address answers", lambda w: w.http("public /healthz", "500", times=1, sleep=0.4))
comes_back("no public refusal", "refused on the public address", lambda w: w.http("public /mcp", "200", times=1))
def slow(w, key, seconds):
    s = w.state(); s["sleep"][key] = seconds; w.save(s)
comes_back("a check that outlives the window", "check --installed` passes", lambda w: slow(w, "installed", 60), env={"FRONTDOOR_SWITCH_WINDOW": "16"})
comes_back("the checks' time running out with every check green", "the 7 s the checks have from the restart are over", lambda w: w.http("public /mcp", times=1, until=7.4, late=True),
           env={"FRONTDOOR_SWITCH_WINDOW": "14", "FRONTDOOR_SWITCH_CHECK": "20"})

comes_back("the public address slow to answer on the way back, inside the window", "check --installed` passes",
           lambda w: (w.fault("installed", 1), w.http("public /healthz", until=6)))

@case
def one_signal_is_enough():
    code = ("import signal, sys; sys.path.insert(0, sys.argv[1]); import frontdoor_switch as fs, frontdoor_cutover as c\n"
            "for s in fs.SIGNALS: signal.signal(s, c._interrupt)\n"
            "try: c._interrupt(signal.SIGTERM, None)\n"
            "except c.Interrupted as e: print('asked', e)\n"
            "print('later ones ignored', all(signal.getsignal(s) == signal.SIG_IGN for s in fs.SIGNALS))\n")
    r = subprocess.run([sys.executable, "-c", code, str(TOOLS)], env=World().env, capture_output=True, text=True, timeout=60)
    check("signals: once one has asked the cut-over to end, every later one is ignored from that moment", "asked SIGTERM" in r.stdout and "later ones ignored True" in r.stdout, (r.stdout, r.stderr))

def bounded(name, row, setup, rc_wanted=4, window=20, reserve=10, spare=6, env=None):
    """From the first restart to the end of the run, the way back included, stays within the window (a few seconds of process starts aside),
    however slow a program is: every one is held to what is left."""
    def run():
        w = World().ready(); setup(w)
        began = time.time()
        rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": str(window), "FRONTDOOR_SWITCH_RESERVE": str(reserve), "FRONTDOOR_SWITCH_UNDO_WINDOW": "200", **(env or {})})
        first = w.state().get("restart_at", began)
        took = time.time() - first
        check(f"window, {name}: ends within the window from the first restart", took <= window + spare, (took, out))
        check(f"window, {name}: exit {rc_wanted}, the failure named", rc == rc_wanted and line(out, "FAIL", row), (rc, out))
        check(f"window, {name}: the board is on its old port", w.state()["units"][BOARD]["port"] == 8020, (w.state()["units"], out))
        check(f"window, {name}: what is left for a person is printed", left_for_a_person(out) and pasteable(out), out)
    run.__name__ = f"window {name}"; CASES.append(run)

LONG = 150
bounded("the restart of the board and the minute runner hangs", "the board and the minute runner are restarted", lambda w: w.slow(f"restart {BOARD} {MINUTE}", LONG))
bounded("enabling the splitter hangs", "the splitter is enabled and started", lambda w: w.slow(f"enable --now {SPLIT}", LONG))
bounded("the portal sync's restart hangs", "the portal sync is restarted", lambda w: w.slow(f"restart {SYNC}", LONG))
bounded("a health answer never comes", "the front door answers on 8030", lambda w: w.http("8030 /healthz", sleep=LONG), env={"FRONTDOOR_SWITCH_CHECK": "200"})
def in_the_way_back(w, *keys):
    w.slow("installed", 60)
    for k in keys: w.slow(k, LONG)
bounded("the checks use all their time and then the way back's restart of the board hangs", f"restarted {BOARD}", lambda w: in_the_way_back(w, f"restart {BOARD}"), rc_wanted=5)
bounded("stopping the splitter hangs in the way back", "check --installed` passes", lambda w: (w.fault("installed", 1), w.slow(f"later disable --now {SPLIT}", LONG)))
bounded("reading the unit files again hangs in the way back", "systemd read the unit files again", lambda w: (w.fault("installed", 1), w.slow("daemon-reload", LONG)), rc_wanted=5)
bounded("every restart of the way back hangs", f"restarted {MINUTE}", lambda w: in_the_way_back(w, f"restart {BOARD}", f"restart {MINUTE}"), rc_wanted=5)
def reverted_install_hangs():
    w = World().ready(); w.set(reverts=w.text("single")); w.fault("installed", 1); w.slow("later install", LONG)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": "20", "FRONTDOOR_SWITCH_RESERVE": "10"})
    took = time.time() - w.state()["restart_at"]
    check("window, install.sh hangs in a way back on a reverted config: ended in its share, the board restarted and answering", took <= 26 and rc == 5 and line(out, "FAIL", "units rendered and installed")
          and line(out, "PASS", "answers on 8020"), (rc, took, out))
CASES.append(reverted_install_hangs)

@case
def saved_copy_cannot_be_stored():
    w = World().switched(); shutil.rmtree(w.rollback.parent); w.rollback.parent.write_text("in the way")
    rc, out = undo(w, "--apply", "--snapshot", w.snap)
    check("undo: a saved copy that cannot be put in place ends the run with every step for a person", rc == 5 and line(out, "FAIL", "the saved single-user config is in place") and left_for_a_person(out) and pasteable(out)
          and line(out, "UNDO", f"--apply --snapshot {w.snap}"), (rc, out))

for reverted, left in ((False, left_for_a_person), (True, lambda out: line(out, "OPERATOR", "release.sh hold --end") and line(out, "OPTION", "stop the front door"))):
    def broken(reverted=reverted, left=left):
        w = World().switched()
        if reverted: w.config.write_text(w.text("single"))
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import frontdoor_switch as fs, frontdoor_undo as u\n"
                "def boom(*a, **k): raise RuntimeError('a bug in the middle')\n"
                "fs.systemctl = boom\n"
                "sys.exit(u.main(['--apply']))")
        r = subprocess.run([sys.executable, "-c", code, str(TOOLS)], env=w.env, capture_output=True, text=True, timeout=120, cwd=w.dir)
        out = r.stdout + r.stderr
        check(f"undo ({'reverted' if reverted else 'saved'} config): an error of its own in the middle exits 5 with the undo and every step for a person", r.returncode == 5 and "a bug in the middle" in out
              and line(out, "UNDO", "--apply") and left(out) and pasteable(out), (r.returncode, out))
    broken.__name__ = f"undo error {reverted}"; CASES.append(broken)

def no_health(w):
    w.fault("installed", 1); w.http("8020 /healthz", "000", after_restart=True)
def never_back():
    w = World().ready(); no_health(w)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": "16", "FRONTDOOR_SWITCH_RESERVE": "8", "FRONTDOOR_SWITCH_UNDO_WINDOW": "200"})
    took = time.time() - w.state()["restart_at"]
    check("window, the board never answers in the way back: the wait ends with the window", rc == 5 and took <= 22 and line(out, "FAIL", "the board answers on 8020"), (rc, took, out))
CASES.append(never_back)

@case
def way_back_within_budget():
    w = World().ready(); w.fault("installed", 1); w.slow(f"restart {BOARD}", 2)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": "60", "FRONTDOOR_SWITCH_RESERVE": "30"})
    calls = w.calls()
    check("way back: a slow restart inside its share of the window is waited for", rc == 4 and line(out, "PASS", f"restarted {BOARD}"), (rc, out))
    check("way back: it says how long after the first restart the board answered", re.search(r"(?m)^\d+ s after the first restart \(the window is 60 s\)$", out), out)
    check("way back: inside a window the portal sync is asked for and not waited for", f"systemctl restart --no-block {SYNC}" in calls and line(out, "PASS", f"restart of {SYNC} asked for, not waited for"), (calls, out))
    after = calls[calls.index(f"systemctl restart {BOARD}"):]
    order = [next((i for i, c in enumerate(after) if c.startswith(p)), -1) for p in (f"systemctl restart {BOARD}", "curl GET http://127.0.0.1:8020/healthz", f"systemctl is-active {BOARD}",
             f"systemctl restart {MINUTE}", f"systemctl restart --no-block {SYNC}", f"curl GET {PUBLIC}/healthz")]
    check("way back: the board and its answer come before the other units", -1 not in order and order == sorted(order), (order, after))

@case
def cutover_retries():
    w = World().ready()
    w.http("8021 /healthz", "503", times=2); w.http("8021 /mcp", "502", times=1); w.http("public /mcp", "000", times=1)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_CHECK": "20"})
    check("cut-over: a service still starting is asked again", rc == 3, (rc, out))
    w = World().ready()
    w.http("8021 /mcp", "200", times=1)
    rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_CHECK": "20"})
    check("cut-over: a call that is let in is final at once, not asked again", rc == 4 and len([c for c in w.calls() if c == "curl POST http://127.0.0.1:8021/mcp"]) == 1, (rc, out))

ENDING = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGUSR1, signal.SIGUSR2)
for sig in ENDING:
    def signalled(sig=sig):
        w = World().ready(); slow(w, "installed", 90)
        with w.start("cutover", "--snapshot", w.snap, "--apply") as run:
            reached = run.when((w.dir / "in-installed-check").exists)
            run.p.send_signal(sig)
            rc, out = run.end()
        s = w.state()["units"]
        check(f"{sig.name} after the restart brings the board back", reached and rc == 4 and sig.name in out and s[BOARD]["active"] and s[BOARD]["port"] == 8020 and len(overrides(w)) == 3, (rc, out))
    signalled.__name__ = f"signal {sig.name}"; CASES.append(signalled)

    def signalled_early(sig=sig):
        w = World().ready(); slow(w, "install", 4)
        with w.start("cutover", "--snapshot", w.snap, "--apply") as run:
            reached = run.called("install.sh units")
            run.p.send_signal(sig)
            rc, out = run.end()
        check(f"{sig.name} before the restart stops the run: nothing restarted, the undo printed", reached and rc == 1 and sig.name in out and "STOPPED before the restart" in out
              and not restarts(w.calls()) and line(out, "UNDO", "--snapshot"), (rc, out))
    signalled_early.__name__ = f"early signal {sig.name}"; CASES.append(signalled_early)

    def signalled_in_the_way_back(sig=sig):
        w = World().ready(); w.fault("installed", 1); w.slow("daemon-reload", 2)
        with w.start("cutover", "--snapshot", w.snap, "--apply") as run:
            reached = run.called("systemctl daemon-reload")
            for _ in range(3): run.p.send_signal(sig); time.sleep(0.1)
            rc, out = run.end()
        s = w.state()["units"]
        check(f"{sig.name} during the automatic way back does not cut it short", reached and rc == 4 and s[BOARD]["active"] and s[BOARD]["port"] == 8020 and "THE BOARD IS BACK" in out, (rc, out))
    signalled_in_the_way_back.__name__ = f"way back signal {sig.name}"; CASES.append(signalled_in_the_way_back)

    def signalled_hand_run(sig=sig):
        w = World().switched(); w.slow("daemon-reload", 2)
        with w.start("undo", "--apply") as run:
            reached = run.called("systemctl daemon-reload")
            run.p.send_signal(sig)
            rc, out = run.end()
        s = w.state()["units"]
        check(f"{sig.name} after the splitter stopped does not cut a person's run of the undo short", reached and rc == 4 and s[BOARD]["active"] and s[BOARD]["port"] == 8020 and left_for_a_person(out), (rc, out))
    signalled_hand_run.__name__ = f"undo signal {sig.name}"; CASES.append(signalled_hand_run)

@case
def one_run_at_a_time():
    w = World().ready(); w.slow("install", 12)
    with w.start("cutover", "--snapshot", w.snap, "--apply") as run:
        reached = run.called("install.sh units")
        refused = {script: w.run(script, *args) for script, args in (("undo", ["--apply", "--snapshot", w.snap]), ("cutover", ["--snapshot", w.snap, "--apply"]),
                                                                    ("snapshot", ["--expect", "1,2,3", "--apply"]), ("undo", ["--apply", "--drop-saved"]))}
        dry = w.run("undo", "--snapshot", w.snap)
        acted = [c for c in w.calls() if c.startswith("install.sh")]
        rc, out = run.end()
    check("one run at a time: while a cut-over writes, no other writing run starts", reached and all(r == 1 and "another run of the switch's scripts holds" in o and f"process {run.p.pid}" in o for r, o in refused.values()) and len(acted) == 1, (refused, acted))
    check("one run at a time: a dry run still reads", dry[0] == 0, dry)
    check("one run at a time: the first run ends as ever", rc == 3, (rc, out))
    rc, out = w.run("undo", "--apply")
    check("one run at a time: the lock goes with its run", rc == 4, (rc, out))

@case
def cutover_closed_output():
    w = World().ready(); w.fault("installed", 1); slow(w, "install", 0.5)
    p = subprocess.Popen([sys.executable, str(TOOLS / "frontdoor_cutover.py"), "--snapshot", str(w.snap), "--apply"], env=w.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=w.dir)
    try:
        p.stdout.close()                        # the reader is gone, as with a dropped terminal
        p.wait(timeout=90)
    finally:
        if p.poll() is None: p.kill(); p.wait(30)
    s = w.state()["units"]
    check("a reader that went away does not stop the run or the way back", p.returncode == 4 and s[BOARD]["port"] == 8020 and s[BOARD]["active"], (p.returncode, s))

def incomplete(name, row, setup):
    def run():
        w = World().ready(); w.fault("installed", 1)
        setup(w)
        rc, out = cut(w, "--apply", env={"FRONTDOOR_SWITCH_WINDOW": "20"})        # a board that does not come back is waited for to the window's end
        check(f"the way back does not complete, {name}: exit 5, says a person is needed and how to go on", rc == 5 and row in out and "THE WAY BACK IS NOT COMPLETE" in out and line(out, "UNDO", "frontdoor_undo.py --apply"), (rc, out))
        check(f"the way back does not complete, {name}: every step still to be done is printed, pasteable", left_for_a_person(out) and pasteable(out) and str(w.rollback) in out, out)
        check(f"the way back does not complete, {name}: the undo with the snapshot's config is printed", line(out, "UNDO", f"--apply --snapshot {w.snap}") and w.rollback.is_file(), out)
    run.__name__ = f"incomplete {name}"; CASES.append(run)

incomplete("the board does not come back", "FAIL    the board answers on 8020", lambda w: w.http("8020 /healthz", "000", after_restart=True))
incomplete("daemon-reload failing", "FAIL    systemd read the unit files again", lambda w: w.fault("daemon-reload", 1))
@case
def blocked_after_checks():
    w = World().ready(); w.fault("installed", 1)
    p = w.home / f".config/systemd/user/{MINUTE}.d"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text("a file where the folder goes\n")
    rc, out = cut(w, "--apply")
    check("the way back does not complete when an override cannot be written: exit 5, the others are still written and the board restarted",
          rc == 5 and line(out, "FAIL", f"override written for {MINUTE}") and w.state()["units"][BOARD]["port"] == 8020 and len(restarts(w.calls())) >= 4, (rc, out))

@case
def saved_copy_lost():
    w = World().ready(); w.fault("installed", 1)
    w.set(lose=str(w.rollback))                 # the saved copy goes away between the restart and the way back
    rc, out = cut(w, "--apply")
    check("the way back with no saved config left: exit 5, refused, and what to do is said", rc == 5 and line(out, "REFUSE", "no config the board can come back on") and f"disable --now {SPLIT}" in out
          and left_for_a_person(out) and pasteable(out) and line(out, "UNDO", f"--apply --snapshot {w.snap}"), (rc, out))

# ================================================================ the undo
def undo(w, *more, **kw): return w.run("undo", *more, **kw)

@case
def undo_dry():
    w = World().switched(); before = w.files()
    rc, out = undo(w)
    check("undo dry run on the switched config: the plan for the saved config, nothing changed", rc == 0 and line(out, "PLAN", "override") and str(w.rollback) in out and "no data would be restored" in out and w.files() == before and not acting(w.calls()), (rc, out))
    w.config.write_text(w.text("single")); before = w.files()
    rc, out = undo(w, "--end-hold")
    check("undo dry run on a reverted config: the plan, with the hold's end", rc == 0 and line(out, "PLAN", "./install.sh units") and line(out, "PLAN", "hold --end") and not line(out, "PLAN", "override") and w.files() == before and not acting(w.calls()), (rc, out))

@case
def undo_refuses():
    w = World(config="switched")
    before = w.files()
    rc, out = undo(w)
    check("undo dry run with no config to come back on: refused, exit 1", rc == 1 and line(out, "REFUSE", "no config") and w.files() == before, (rc, out))
    rc, out = undo(w, "--apply")
    check("undo with the switched config and no saved one: refused, nothing changed, says what to do", rc == 1 and line(out, "REFUSE", "there is no file") and f"disable --now {SPLIT}" in out and not acting(w.calls()) and w.files() == before, (rc, out, w.calls()))
    check("undo refused: every step is printed, pasteable", left_for_a_person(out) and pasteable(out), out)
    snap = w.dir / "snap"; snap.mkdir(); (snap / "stackshot.toml").write_text(w.text("switched"))
    rc, out = undo(w, "--apply", "--snapshot", snap)
    check("undo refuses a snapshot whose config shows the switch", rc == 1 and line(out, "REFUSE", "not a single-user config") and not acting(w.calls()), (rc, out))

@case
def undo_saved_then_reverted():
    w = World().switched()
    w.rollback.unlink()
    rc, out = undo(w, "--apply", "--snapshot", w.snap, "--end-hold")
    s = w.state()
    check("undo with --snapshot on the switched config: back on the saved config, exit 4", rc == 4 and s["units"][BOARD]["port"] == 8020 and s["units"][BOARD]["active"] and w.rollback.read_bytes() == (w.snap / "stackshot.toml").read_bytes(), (rc, out))
    check("undo on the saved config: MANUAL lines, no data touched, the hold is not ended", line(out, "MANUAL", "portal:") and line(out, "MANUAL", "browser:") and "no data was restored or removed" in out
          and "release.sh hold --end" not in w.calls() and line(out, "NOTE", "--end-hold was not done") and s["hold"].startswith("releases are held"), (out, w.calls()))
    check("undo on the saved config: install.sh is not run, the splitter is off first", "install.sh units" not in w.calls() and w.calls()[0] == f"systemctl disable --now {SPLIT}", w.calls())
    check("undo on the saved config: the override says why it is there and names the saved copy", overrides(w) and all(f'Environment="STACKSHOT_CONFIG={w.rollback}"' in p.read_text() and "frontdoor_undo.py" in p.read_text() for p in overrides(w)), [p.read_text() for p in overrides(w)])
    rc, out = undo(w, "--apply")
    check("undo run again before the revert: the same, exit 4", rc == 4 and w.state()["units"][BOARD]["port"] == 8020, (rc, out))
    # the operator reverts and pulls; a later change of the config is there too
    w.config.write_text(w.text("single")); w.clear_calls()
    rc, out = undo(w, "--apply")
    s = w.state()
    check("undo on the reverted config: exit 3, the board on the instance's config again", rc == 3 and s["units"][BOARD]["port"] == 8020 and s["units"][BOARD]["config"] == str(w.config), (rc, s["units"][BOARD], out))
    check("undo on the reverted config: the override and the saved copy are removed, the board's own drop-in stays", not overrides(w) and not w.rollback.exists()
          and (w.home / f".config/systemd/user/{BOARD}.d/portal-sync.conf").is_file() and not (w.home / f".config/systemd/user/{MINUTE}.d").exists(), list(w.home.rglob("*.conf")))
    calls = w.calls()
    order = [next((i for i, c in enumerate(calls) if c.startswith(p)), -1) for p in (f"systemctl disable --now {SPLIT}", "systemctl daemon-reload", "install.sh units", f"systemctl restart {BOARD}", "curl GET http://127.0.0.1:8020/healthz", f"systemctl restart {MINUTE}", f"systemctl restart {SYNC}", f"curl GET {PUBLIC}/healthz")]
    check("undo on the reverted config: splitter off, override away, units, restarts, checks, in order", -1 not in order and order == sorted(order), (order, calls))
    check("undo: a unit that hit its start limit is reset before each restart", all(f"systemctl reset-failed {u}" in calls and calls.index(f"systemctl reset-failed {u}") < calls.index(f"systemctl restart {u}") for u in RESTORE), calls)
    check("undo on the reverted config: manual lines, the optional steps, the hold left", line(out, "MANUAL", "portal:") and line(out, "OPTION", "stop the front door") and line(out, "OPTION", "hold --end") and "release.sh hold --end" not in calls and pasteable(out), out)
    rc, out = undo(w, "--apply", "--end-hold")
    check("undo twice, with --end-hold: exit 3 and the hold is ended", rc == 3 and w.state()["hold"] == "no hold on releases" and line(out, "PASS", "release hold ended"), (rc, out))
    w.clear_calls()
    rc, out = undo(w, "--apply", "--end-hold")
    check("undo --end-hold with no hold: nothing to end", rc == 3 and line(out, "PASS", "no release hold to end") and "release.sh hold --end" not in w.calls(), (rc, out))

@case
def undo_keeps_tables_note():
    w = World().switched(); w.config.write_text(w.text("step4"))
    rc, out = undo(w, "--apply")
    check("undo with only the cut-over reverted: runs, and names the tables still in the config", rc == 3 and line(out, "NOTE", "tables of the switch are still in the config") and "frontdoor_splitter" in out, (rc, out))

@case
def undo_differences():
    w = World().switched()
    w.config.write_text(_set(_set(w.text("switched"), "instance", "board_url", '"https://new.example.invalid"'), "auth", "allowed_emails", '["new@example.com"]'))
    rc, out = undo(w, "--apply")
    check("undo on the saved config names what differs outside the switch, never a value", rc == 4 and any(l.startswith("NOTE") and l.endswith("until the revert: [auth] allowed_emails, [instance] board_url") for l in out.splitlines())
          and "new@example.com" not in out and "new.example.invalid" not in out, (rc, out))
    w.config.write_text("[server\n")
    rc, out = undo(w, "--apply")
    check("undo comes back on the saved config when the pulled one cannot be read", rc == 4 and "cannot be read, so it was not compared" in out and w.state()["units"][BOARD]["port"] == 8020, (rc, out))

def undo_incomplete(name, row, setup, reverted=True, extra=()):
    def run():
        w = World().switched()
        if reverted: w.config.write_text(w.text("single"))
        setup(w)
        rc, out = undo(w, "--apply", *extra)
        where = "reverted" if reverted else "saved"
        check(f"undo ({where} config), {name}: exit 5, the failed step named, a person needed", rc == 5 and line(out, "FAIL", row) and "THE WAY BACK IS NOT COMPLETE" in out and "no data was restored" in out, (rc, out))
        again = "--apply" + (" --end-hold" if "--end-hold" in extra else "")
        check(f"undo ({where} config), {name}: what is still to be done is printed, pasteable", pasteable(out) and any(l.startswith("UNDO") and l.endswith(again) for l in out.splitlines())
              and (left_for_a_person(out) if not reverted else line(out, "OPERATOR", "release.sh hold --end") and line(out, "OPTION", "stop the front door")), out)
        if name != "ending the hold":
            check(f"undo ({where} config), {name}: the saved copy is kept", w.rollback.is_file() and (str(w.rollback) in out), out)
        else:                                       # the way back itself passed on the reverted config before the hold was asked to end
            check(f"undo ({where} config), {name}: the saved copy is removed, the way back having passed", not w.rollback.is_file(), out)
        if name != "ending the hold":
            check(f"undo ({where} config), {name}: every unit is still restarted and checked", len(restarts(w.calls())) == 3 and [c for c in w.calls() if c.startswith(f"curl GET {PUBLIC}")], w.calls())
    run.__name__ = f"undo {name} {reverted}"; CASES.append(run)

for reverted in (True, False):
    undo_incomplete("the splitter not stopping", "the splitter is disabled and stopped", lambda w: w.fault(f"disable {SPLIT}"), reverted)
    for unit in RESTORE:
        undo_incomplete(f"{unit} not restarting", f"restarted {unit}", lambda w, unit=unit: w.fault(f"restart {unit}"), reverted)
    undo_incomplete("no health on 8020", "the board answers on 8020", lambda w: w.http("8020 /healthz", "500"), reverted)
    undo_incomplete("no public health", "the public address answers", lambda w: w.http("public /healthz", "500"), reverted)
undo_incomplete("install.sh failing", "units rendered and installed", lambda w: w.fault("install"))
undo_incomplete("ending the hold", "release hold ended", lambda w: w.fault("hold-end"), extra=("--end-hold",))
@case
def undo_unit_not_running():
    w = World().switched(); w.config.write_text("[server]\nport = 8020\n")
    w.set(stuck=BOARD)                          # something answers on the port while the board's unit is not running
    rc, out = undo(w, "--apply")
    check("undo: an answer on the port while the board's unit is not running is no success", rc == 5 and line(out, "FAIL", f"{BOARD} is running") and line(out, "PASS", "answers on 8020"), (rc, out))

@case
def undo_after_failed_cutover_stop():
    w = World().ready(); w.fault("boardtoken")
    rc, out = cut(w, "--apply")
    cmd = shlex.split(next(l for l in out.splitlines() if l.startswith("UNDO")).split(None, 1)[1])
    r = subprocess.run(cmd, env=w.env, capture_output=True, text=True, timeout=120)
    check("the undo command a stopped run prints works: the board on the saved config", r.returncode == 4 and w.state()["units"][BOARD]["port"] == 8020 and w.state()["units"][BOARD]["config"] == str(w.rollback), (r.returncode, r.stdout + r.stderr))

for unit in RESTORE:
    def missing_unit(unit=unit):
        w = World().switched(); (w.home / ".config/systemd/user" / unit).unlink()
        rc, out = undo(w, "--apply")
        check(f"undo (saved config), {unit} not installed: its restart fails, a person is needed", rc == 5 and line(out, "FAIL", f"restarted {unit}") and "not found" in out, (rc, out))
    missing_unit.__name__ = f"undo missing {unit}"; CASES.append(missing_unit)

@case
def undo_hand_run_waits():
    w = World().switched(); w.slow(f"restart {SYNC}", 1)
    rc, out = undo(w, "--apply")
    check("undo run by a person: the portal sync's restart is waited for", rc == 4 and f"systemctl restart {SYNC}" in w.calls() and line(out, "PASS", f"restarted {SYNC}") and "after the first restart" not in out, (rc, out))

@case
def kept_switch():
    w = World().switched(); before = w.files()
    rc, out = undo(w, "--drop-saved")
    check("drop-saved dry run: says what it would remove, removes nothing", rc == 0 and line(out, "PLAN", "remove the saved copy") and w.files() == before, (rc, out))
    rc, out = undo(w, "--apply", "--drop-saved", drop=("FRONTDOOR_PUBLIC_URL",))
    check("drop-saved: the saved copy of a kept switch is removed, no unit touched", rc == 0 and not w.rollback.exists() and not acting(w.calls()) and "--snapshot DIR" in out, (rc, out, w.calls()))
    rc, out = undo(w, "--apply", "--drop-saved")
    check("drop-saved again: nothing to remove", rc == 0 and line(out, "PASS", "there is no saved copy"), (rc, out))
    rc, out = undo(w, "--apply")
    check("after it the undo asks for the snapshot", rc == 1 and line(out, "REFUSE", "there is no file") and not acting(w.calls()), (rc, out))
    rc, out = undo(w, "--apply", "--snapshot", w.snap)
    check("and with the snapshot it brings the board back", rc == 4 and w.state()["units"][BOARD]["port"] == 8020, (rc, out))
    rc, out = undo(w, "--apply", "--drop-saved")
    check("drop-saved is refused while an override makes a unit read the copy", rc == 1 and line(out, "REFUSE", "through an override") and w.rollback.is_file() and pasteable(out), (rc, out))
    for more in (["--snapshot", w.snap], ["--end-hold"]):
        rc, out = undo(w, "--apply", "--drop-saved", *more)
        check(f"drop-saved goes alone, not with {more[0]}", rc == 2 and w.rollback.is_file(), (rc, out))

@case
def old_saved_copy():
    w = World().switched(); old = time.time() - 25 * 3600; os.utime(w.rollback, (old, old))
    rc, out = undo(w)
    check("an old saved copy no unit reads: a dry run refuses it", rc == 1 and line(out, "REFUSE", "hours old"), (rc, out))
    rc, out = undo(w, "--apply")
    check("an old saved copy no unit reads is refused, nothing changed, the snapshot asked for", rc == 1 and line(out, "REFUSE", "25 hours old") and "--snapshot DIR" in out and not acting(w.calls()), (rc, out))
    rc, out = undo(w, "--apply", "--snapshot", w.snap)
    check("with the snapshot named the way back runs", rc == 4, (rc, out))
    os.utime(w.rollback, (old, old))
    rc, out = undo(w, "--apply")
    check("an old saved copy the units already read is the one", rc == 4, (rc, out))
    w = World().switched(); young = time.time() - 23 * 3600; os.utime(w.rollback, (young, young))
    rc, out = undo(w, "--apply")
    check("a saved copy of less than a day is taken", rc == 4, (rc, out))

@case
def saved_folder_closed():
    w = World().switched(); w.rollback.unlink(); w.rollback.parent.chmod(0o755)
    rc, out = undo(w, "--apply", "--snapshot", w.snap)
    check("the folder of the saved copy is closed to others", rc == 4 and w.rollback.parent.stat().st_mode & 0o777 == 0o700 and w.rollback.stat().st_mode & 0o777 == 0o600, (rc, oct(w.rollback.parent.stat().st_mode)))

@case
def private_files():
    sys.path.insert(0, str(TOOLS))
    import frontdoor_switch as fs
    d = T / f"private-{os.urandom(4).hex()}"; d.mkdir()
    (d / "there").write_text("first")
    try: fs.new_private(d / "there", b"second"); got = "written"
    except FileExistsError: got = "refused"
    check("a new private file never replaces one", got == "refused" and (d / "there").read_text() == "first", got)
    os.symlink(d / "target", d / "link")
    try: fs.new_private(d / "link", b"x"); got = "written"
    except FileExistsError: got = "refused"
    check("and is not written through a link", got == "refused" and not (d / "target").exists(), got)
    fs.new_private(d / "new", b"whole"); fs.write_private(d / "there", b"replaced")
    check("both leave a file of mode 600 and no temporary one", (d / "new").read_bytes() == b"whole" and (d / "there").read_bytes() == b"replaced" and sorted(p.name for p in d.iterdir()) == ["link", "new", "there"]
          and all((d / n).stat().st_mode & 0o777 == 0o600 for n in ("new", "there")), list(d.iterdir()))
    real = fs.os.fsync
    def broken(fd): raise OSError("disk")
    fs.os.fsync = broken
    try:
        try: fs.new_private(d / "half", b"x" * 10); got = "written"
        except OSError: got = "refused"
    finally:
        fs.os.fsync = real
    check("a write that fails leaves nothing behind", got == "refused" and not (d / "half").exists() and not [p for p in d.iterdir() if p.name.startswith(".tmp-")], list(d.iterdir()))

@case
def units_of_code():
    sys.path.insert(0, str(TOOLS))
    import frontdoor_switch as fs, frontdoor_undo as un
    check("the override quotes a path as systemd reads it", un.override_text(pathlib.Path('/a b/100%/q"x\\y')).splitlines()[-1] == 'Environment="STACKSHOT_CONFIG=/a b/100%%/q\\"x\\\\y"')
    check("the exit codes are six different numbers", sorted([fs.OK, fs.FAILED, fs.CANNOT, fs.PENDING, fs.ROLLED_BACK, fs.INCOMPLETE]) == [0, 1, 2, 3, 4, 5])
    check("the window is 300 s, 90 of them kept for the way back, and the needed hold 15 min", fs.WINDOW_SECONDS == 300 and fs.RESERVE_SECONDS == 90 and fs.MIN_HOLD_MINUTES == 15)
    class Left:
        def __init__(self, s): self.s = s
        def left(self): return self.s
    lim = fs.Limits(None)
    check("a person's run of the undo keeps each program's own limit", (lim.act(), lim.read(), lim.install(), lim.restart()) == (120, 120, 300, 120))
    shares = {left: (lambda x: (x.act(), x.read(), x.install(), x.restart()))(fs.Limits(Left(left))) for left in (90, 12, -3)}
    check("inside the cut-over's window each program gets a share of what is left, never less than 5 s of a 300 s window", shares == {90: (15, 5, 45, 75), 12: (12, 5, 6, 5), -3: (5, 5, 5, 5)}, shares)
    answers = (fs.Limits(Left(40)).answers().left(), fs.Limits(Left(-3)).answers().left())
    check("the board's answers get what is left of the window, and 5 s when nothing is", 39 < answers[0] <= 40 and 4 < answers[1] <= 5, answers)

# ================================================================ run them
def guarded(fn):
    began = time.monotonic()
    try: fn()
    except Exception: check(f"{fn.__name__}: the case ran to its end", False, traceback.format_exc())
    if os.environ.get("FRONTDOOR_SCENARIO_TIMES") and time.monotonic() - began > 15: print(f"slow: {time.monotonic() - began:.0f} s {fn.__name__}", flush=True)

with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
    list(pool.map(guarded, CASES))

print(("ok" if not fails else "FAILED") + f": front door switch scenario, {len(ran)} checks in {len(CASES)} cases" + (f", {len(fails)} failed" if fails else ""), flush=True)
sys.exit(1 if fails else 0)
