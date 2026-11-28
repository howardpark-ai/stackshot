"""Scenario test for `stackshot board-create` (stackshot/core/board_create.py, cli.py cmd_board_create; docs/front-door.md, *Creating a board*). Offline and hermetic: fixture
files in a scratch folder, example.com addresses, a stand-in for the database server and, where PostgreSQL can be started, a throwaway server on a unix socket in the scratch folder.

Covers:
  * the name: the floor rule, and what board_names.validate says when that module is there;
  * the plan: every line, `new` on an empty tree, nothing written by planning, the text for the front door's config, an unset server marked `unknown`;
  * a run: the folder's files and modes, the id and the login named from it, the database made once with the board's name as its comment, the config parses and carries
    the board's port, name and members, the data repository has its first commit, the members land in the members file as invite entries;
  * a repeat changes nothing (every file, the members file and the server's calls are the same) and its plan says there is nothing to do; a new member is added alone;
  * refusals: another port for an existing board, a held login without its password file, a server not set or not reached (nothing is made), a members file that is
    not there;
  * a failing database step and a failing file step leave nothing behind (no folder, no login, no members), and a second run then succeeds;
  * the command through the CLI: the dry run writes nothing, `--yes` makes the board, the exit codes, and that no program that sends mail is touched;
  * PsqlServer against a real throwaway server when one can be started: state, create twice, the comment, connection rights, drop, and that an error never holds the password.

    tests/run-suite board_create         -> exit 0 / 1"""
import contextlib, hashlib, io, json, os, pathlib, re, shutil, socket, stat, subprocess, sys, tomllib, traceback

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance

tmp = _scratch.mkdtemp(prefix="boardcreate-"); T = pathlib.Path(tmp)
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
HOME = T / "home"; HOME.mkdir()
os.environ["HOME"] = str(HOME)
for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"): os.environ[k] = os.devnull


def owner_toml(extra=""):
    toml = _instance.apply(_instance.base_toml())
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    return toml + extra


MEMBERS = T / "members.json"
BOARDS = T / "boards"
OWNER_CFG = T / "owner.toml"
OWNER_CFG.write_text(owner_toml(f'\n[frontdoor]\nidentity_secret_file = "{T}/identity.key"\nmembers_file = "{MEMBERS}"\n'
                                f'[board_create]\nboards_dir = "{BOARDS}"\n'), encoding="utf-8")
os.environ["STACKSHOT_CONFIG"] = str(OWNER_CFG)


def reset_members():
    MEMBERS.write_text(json.dumps({"zed": {"boards": ["main"], "emails": ["zed@example.com"]}}), encoding="utf-8"); MEMBERS.chmod(0o640)


reset_members()

from stackshot.core import board_create as bc, invites
from stackshot import cli

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]} ... {str(got)[-700:]}" if got is not None else ""), flush=True)


def raised(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except Exception as e:      # noqa: BLE001
        return e
    return None


class Fake:
    """A stand-in BrainServer: logins and databases in a dict, every call kept, one step made to fail on request."""

    def __init__(self):
        self.roles, self.dbs, self.calls, self.fail_on = {}, {}, [], None

    def _maybe(self, op):
        self.calls.append(op)
        if self.fail_on == op:
            raise bc.BrainServerError(f"the stand-in refused {op}")

    def state(self, login, database):
        self._maybe("state")
        return login in self.roles, database in self.dbs

    def create(self, login, database, comment, password):
        self._maybe("create")
        self.roles.setdefault(login, password)
        self.dbs[database] = {"owner": login, "comment": comment, "public_connect": False}

    def drop(self, login, database):
        self._maybe("drop")
        self.dbs.pop(database, None); self.roles.pop(login, None)

    def address(self, login, database):
        return f"postgresql://{login}@127.0.0.1:5999/{database}"


SERVER = bc.ServerSettings(host="127.0.0.1", port=5999, admin_user="admin")


def settings(server=SERVER):
    return bc.Settings(boards_dir=str(BOARDS), members_file=str(MEMBERS), server=server)


def render(plan, req):
    return cli.board_files(plan, req, tomllib.loads(OWNER_CFG.read_text()), str(MEMBERS))


def tree(root):
    """Every path under root with its mode and content hash: what a repeat must leave as it is."""
    out = {}
    for p in sorted(pathlib.Path(root).rglob("*")):
        if ".git" in p.parts and p.name not in ("HEAD",) and p.is_dir():
            continue
        out[str(p.relative_to(root))] = (stat.S_IMODE(p.stat().st_mode), hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir", p.stat().st_mtime_ns if p.is_file() else 0)
    return out


def make(name="lab", members=("alice@example.com", "bob@example.com"), port=8051, fake=None, st=None, ident=lambda: "a" * 32, sink=None):
    st = st or settings()
    req = bc.Request(name, tuple(members), port)
    plan = bc.make_plan(st, req, fake, ident)
    lines = []
    bc.apply(plan, st, req, fake, lambda p: render(p, req), pathlib.Path(STACK), sink if sink is not None else lines.append)
    return plan


def states(plan):
    return {ln.what: ln.state for ln in plan.lines}


def part_name():
    for good in ("lab", "ab", "a-1", "x" * 32):
        check(f"name: {good!r} is taken", bc.check_name(good) == good)
    for bad in ("", "a", "x" * 33, "Lab", "1lab", "-lab", "lab_x", "la b", "lab/..", "../x", "lab\n"):
        check(f"name: {bad!r} is refused", isinstance(raised(bc.check_name, bad), bc.CreateError))
    import types
    mod = types.ModuleType("stackshot.core.board_names")
    mod.validate = lambda n: (_ for _ in ()).throw(ValueError("taken by the front door")) if n == "main" else n
    sys.modules["stackshot.core.board_names"] = mod
    try:
        e = raised(bc.check_name, "main")
        check("name: board_names.validate has the last word", isinstance(e, bc.CreateError) and "taken by the front door" in str(e), e)
        check("name: and lets a name through", bc.check_name("lab") == "lab")
    finally:
        sys.modules.pop("stackshot.core.board_names", None)


def part_plan():
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    fake = Fake()
    st = settings()
    req = bc.Request("lab", ("alice@example.com", "bob@example.com"), 8051)
    before = sorted(str(p) for p in T.rglob("*"))
    plan = bc.make_plan(st, req, fake, lambda: "b" * 32)
    check("plan: planning writes nothing", before == sorted(str(p) for p in T.rglob("*")) and not BOARDS.exists())
    check("plan: the login and database are brain_ plus the id", plan.login == "brain_" + "b" * 32 and plan.board_id == "b" * 32, plan.login)
    s = states(plan)
    check("plan: everything is new on an empty tree", all(s[k] == "new" for k in ("board id", "config", "data repository", "process", "secret", "brain database", "members")), s)
    check("plan: the later stages are stubs", s["front door entry"] == s["front door brain entry"] == s["spend cap"] == "stub", s)
    text = bc.render_plan(plan)
    check("plan: the text names the login, the unit and the entry", plan.login in text and "stackshot-board-lab.service" in text and "[[frontdoor.backends]]" in text, text)
    check("plan: the text says the unit is not installed", "not installed, enabled or started" in text)
    entry = tomllib.loads(plan.edge)["frontdoor"]["backends"][0]
    check("plan: the front door entry parses", entry["name"] == "lab" and entry["kind"] == "board" and entry["url"] == "http://127.0.0.1:8051/mcp"
          and entry["health_url"] == "http://127.0.0.1:8051/healthz" and entry["token_file"].endswith("/secrets/frontdoor.token"), entry)
    check("plan: no server is asked to make anything", fake.calls and set(fake.calls) == {"state"}, fake.calls)
    none = bc.make_plan(settings(bc.ServerSettings()), req, None, lambda: "b" * 32)
    check("plan: a server that is not set is unknown, not done", states(none)["brain database"] == "unknown" and not none.server_reached and not none.done)
    down = Fake(); down.fail_on = "state"
    d = bc.make_plan(st, req, down, lambda: "b" * 32)
    check("plan: a server that is not reached is unknown and says why", states(d)["brain database"] == "unknown" and "stand-in refused state" in bc.render_plan(d))
    check("plan: a port out of range is refused", isinstance(raised(bc.make_plan, st, bc.Request("lab", ("a@example.com",), 70000), fake), bc.CreateError))
    check("plan: a members file that is not there is unknown", states(bc.make_plan(bc.Settings(str(BOARDS), str(T / "none.json"), SERVER), req, fake))["members"] == "unknown")


def part_run():
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    fake = Fake()
    out = []
    plan = make(fake=fake, sink=out.append)
    home = BOARDS / "lab"
    login = "brain_" + "a" * 32
    check("run: the board's files are there", all((home / f).exists() for f in ("board.id", "stackshot.toml", "secrets/brain-db.password", "data/RULES.md", "data/.git", "stackshot-board-lab.service")),
          sorted(str(p.relative_to(home)) for p in home.rglob("*")))
    check("run: the id file holds the id", (home / "board.id").read_text().strip() == "a" * 32)
    check("run: the secrets are private", stat.S_IMODE((home / "secrets").stat().st_mode) == 0o700 and stat.S_IMODE((home / "secrets/brain-db.password").stat().st_mode) == 0o600
          and stat.S_IMODE(home.stat().st_mode) == 0o700)
    pw = (home / "secrets/brain-db.password").read_text().strip()
    check("run: the password is 32 hex digits and is the login's", re.fullmatch(r"[0-9a-f]{32}", pw) and fake.roles.get(login) == pw)
    check("run: one login and one database, the name as the comment, rights taken from the rest", list(fake.roles) == [login] and fake.dbs == {login: {"owner": login, "comment": "lab", "public_connect": False}}, fake.dbs)
    check("run: no output holds the password", pw not in "\n".join(out))
    cfg = tomllib.loads((home / "stackshot.toml").read_text())
    check("run: the config carries the port, the paths and the members", cfg["server"]["port"] == 8051 and cfg["paths"]["repo"] == str(home / "data") and cfg["paths"]["secrets"] == str(home / "secrets")
          and cfg["auth"]["allowed_emails"] == ["alice@example.com", "bob@example.com"], cfg.get("server"))
    check("run: it is behind the front door as this board", cfg["behind_frontdoor"]["board_name"] == "lab" and cfg["behind_frontdoor"]["members_file"] == str(MEMBERS)
          and cfg["behind_frontdoor"]["identity_secret_file"] == f"{T}/identity.key" and cfg["invites"]["admins"] == ["alice@example.com"], cfg.get("behind_frontdoor"))
    check("run: the brain's address has no password and the cap is unset", cfg["brain_db"]["url"] == fake.address(login, login) and pw not in (home / "stackshot.toml").read_text()
          and "spend_cap_usd_per_day" not in cfg["brain_db"] and "# spend_cap_usd_per_day" in (home / "stackshot.toml").read_text(), cfg["brain_db"])
    git = subprocess.run(["git", "-C", str(home / "data"), "log", "--format=%s"], capture_output=True, text=True)
    check("run: the data repository has its first commit", git.stdout.strip() == "stackshot board-create", git)
    unit = (home / "stackshot-board-lab.service").read_text()
    check("run: the unit text points at the board's config", f"STACKSHOT_CONFIG={home / 'stackshot.toml'}" in unit and "ExecStart=" in unit and "[Install]" in unit)
    m = json.loads(MEMBERS.read_text())
    check("run: both members are on the board as invite entries, the first by the command", m["alice@example.com"]["boards"] == ["lab"] and m["bob@example.com"]["boards"] == ["lab"]
          and m["bob@example.com"]["invited"]["by"] == "alice@example.com" and m["alice@example.com"]["invited"]["by"] == "board-create" and m["zed"]["boards"] == ["main"], m)
    check("run: the registered entries have no mail sent (the command has no such step)", "smtplib" not in sys.modules and "stackshot.fleet.gmail" not in sys.modules)
    check("run: the plan was new throughout", plan.home_is_new)


def part_repeat():
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    fake = Fake()
    make(fake=fake)
    snap, mem, calls = tree(BOARDS), MEMBERS.read_bytes(), list(fake.calls)
    st = settings()
    req = bc.Request("lab", ("alice@example.com", "bob@example.com"), 8051)
    plan = bc.make_plan(st, req, fake)
    check("repeat: the plan says there is nothing to do", plan.done and "nothing to do" in bc.render_plan(plan) and plan.board_id == "a" * 32, states(plan))
    check("repeat: it reads the id it made, not a new one", plan.login == "brain_" + "a" * 32)
    for _ in range(2):
        bc.apply(plan, st, req, fake, lambda p: render(p, req), pathlib.Path(STACK), lambda m: None)
    check("repeat: no file changed, none was added", tree(BOARDS) == snap)
    check("repeat: the members file is the same bytes", MEMBERS.read_bytes() == mem)
    check("repeat: the server was only asked, never told", all(c == "state" for c in fake.calls[len(calls):]), fake.calls[len(calls):])
    plan2 = bc.make_plan(st, bc.Request("lab", ("alice@example.com", "bob@example.com", "carol@example.com"), 8051), fake)
    check("repeat: a member added later is the only thing new", states(plan2)["members"] == "new" and plan2.new_members == ("carol@example.com",) and
          all(v in ("present", "stub") for k, v in states(plan2).items() if k != "members"), (states(plan2), plan2.new_members))
    out = []
    bc.apply(plan2, st, bc.Request("lab", ("alice@example.com", "bob@example.com", "carol@example.com"), 8051), fake, lambda p: ("", ""), pathlib.Path(STACK), out.append)
    check("repeat: the new member is written and the others are left", json.loads(MEMBERS.read_text())["carol@example.com"]["boards"] == ["lab"] and [m for m in out if "member" in m] == ["  member carol@example.com: written"], out)
    check("repeat: the board's own files stayed as they were", tree(BOARDS) == snap)
    # a second board beside the first
    make(name="lab-two", members=("alice@example.com",), port=8052, fake=fake, ident=lambda: "c" * 32)
    check("repeat: a second board has a login and a database of its own", sorted(fake.roles) == ["brain_" + "a" * 32, "brain_" + "c" * 32], sorted(fake.roles))
    check("repeat: and a person on both boards has one entry on both", json.loads(MEMBERS.read_text())["alice@example.com"]["boards"] == ["lab", "lab-two"])


def part_refusals():
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    fake = Fake()
    make(fake=fake)
    st = settings()
    e = raised(bc.make_plan, st, bc.Request("lab", ("alice@example.com",), 8099), fake)
    check("refuse: another port for an existing board", isinstance(e, bc.CreateError) and "another port" in str(e), e)
    held = Fake(); held.roles["brain_" + "d" * 32] = "x"; held.dbs["brain_" + "d" * 32] = {}
    e = raised(bc.make_plan, st, bc.Request("held", ("a@example.com",), 8060), held, lambda: "d" * 32)
    check("refuse: a held login with no password file", isinstance(e, bc.CreateError) and "password" in str(e) and not (BOARDS / "held").exists(), e)
    plan = bc.make_plan(settings(bc.ServerSettings()), bc.Request("other", ("a@example.com",), 8070), None)
    e = raised(bc.apply, plan, settings(bc.ServerSettings()), bc.Request("other", ("a@example.com",), 8070), None, lambda p: ("", ""), pathlib.Path(STACK), lambda m: None)
    check("refuse: no server set, nothing is made", isinstance(e, bc.CreateError) and not (BOARDS / "other").exists(), e)
    down = Fake(); down.fail_on = "state"
    plan = bc.make_plan(st, bc.Request("other", ("a@example.com",), 8070), down)
    e = raised(bc.apply, plan, st, bc.Request("other", ("a@example.com",), 8070), down, lambda p: ("", ""), pathlib.Path(STACK), lambda m: None)
    check("refuse: a server not reached, nothing is made", isinstance(e, bc.CreateError) and not (BOARDS / "other").exists(), e)
    (BOARDS / "lab" / "board.id").write_text("not an id\n")
    e = raised(bc.make_plan, st, bc.Request("lab", ("alice@example.com",), 8051), fake)
    check("refuse: a board.id that is no id", isinstance(e, bc.CreateError) and "board id" in str(e), e)


def part_failures():
    for where in ("create", "render", "git", "unit"):
        shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
        before = MEMBERS.read_bytes()
        fake = Fake()
        st = settings()
        req = bc.Request("lab", ("alice@example.com", "bob@example.com"), 8051)
        plan = bc.make_plan(st, req, fake, lambda: "e" * 32)
        if where == "create":
            fake.fail_on = "create"
            r = lambda p: render(p, req)
        elif where == "render":
            def r(p): raise OSError(28, "No space left on device")
        else:
            r = lambda p: render(p, req)
        real_git, real_unit = bc._git_init, bc.unit_text
        if where == "git":
            bc._git_init = lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "git"))
        if where == "unit":
            bc.unit_text = lambda *a, **k: (_ for _ in ()).throw(OSError(13, "Permission denied"))
        try:
            e = raised(bc.apply, plan, st, req, fake, r, pathlib.Path(STACK), lambda m: None)
        finally:
            bc._git_init, bc.unit_text = real_git, real_unit
        fake.fail_on = None
        check(f"fail {where}: the command says it failed and that it took its work away", isinstance(e, bc.CreateError) and "taken away" in str(e), e)
        check(f"fail {where}: no folder, no login, no database", not (BOARDS / "lab").exists() and not fake.roles and not fake.dbs, (fake.roles, fake.dbs))
        check(f"fail {where}: the members file is untouched", MEMBERS.read_bytes() == before)
        again = make(fake=fake, ident=lambda: "f" * 32)
        check(f"fail {where}: a run after it works", (BOARDS / "lab" / "stackshot.toml").exists() and list(fake.roles) == ["brain_" + "f" * 32] and again.home_is_new)
    # a rerun on an existing board that fails leaves what is there
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    fake = Fake(); make(fake=fake)
    (BOARDS / "lab" / "stackshot-board-lab.service").unlink()
    st = settings(); req = bc.Request("lab", ("alice@example.com", "bob@example.com"), 8051)
    plan = bc.make_plan(st, req, fake)
    real = bc.unit_text
    bc.unit_text = lambda *a, **k: (_ for _ in ()).throw(OSError(13, "Permission denied"))
    try:
        e = raised(bc.apply, plan, st, req, fake, lambda p: render(p, req), pathlib.Path(STACK), lambda m: None)
    finally:
        bc.unit_text = real
    check("fail rerun: an existing board is not taken apart", isinstance(e, bc.CreateError) and "run it again" in str(e) and (BOARDS / "lab" / "stackshot.toml").exists() and fake.dbs, e)
    # a members entry that was written by hand
    shutil.rmtree(BOARDS, ignore_errors=True)
    MEMBERS.write_text(json.dumps({"bob@example.com": ["main"]}))
    fake = Fake()
    e = raised(make, fake=fake)
    check("fail members: a hand-written entry is refused in the invite tool's words, the board stays made", isinstance(e, bc.CreateError) and "already written" in str(e) and "bob@example.com" in str(e)
          and (BOARDS / "lab" / "stackshot.toml").exists(), e)


def run_cli(*argv, server=None):
    out, err = io.StringIO(), io.StringIO()
    real = bc.PsqlServer
    if server is not None:
        bc.PsqlServer = lambda s: server
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(["board-create", *argv])
            except SystemExit as e:
                code = e.code
    finally:
        bc.PsqlServer = real
    return code, out.getvalue() + err.getvalue()


def part_cli():
    shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
    served = f'\n[board_create.brain_server]\nhost = "127.0.0.1"\nport = 5999\nadmin_user = "admin"\n'
    OWNER_CFG.write_text(OWNER_CFG.read_text() + served)
    fake = Fake()
    code, out = run_cli("lab", "Alice@Example.com", "bob@example.com", "--port", "8051", server=fake)
    check("cli: the dry run exits 0, prints the plan and writes nothing", code == 0 and "[new" in out and "dry run: nothing was written" in out and not BOARDS.exists() and not fake.roles, (code, out))
    code, out = run_cli("lab", "alice@example.com", "bob@example.com", "--port", "8051", "--yes", server=fake)
    check("cli: --yes makes the board and says what is left to the owner", code == 0 and "is made" in out and "Nothing is started and nothing was sent" in out and (BOARDS / "lab/stackshot.toml").exists(), (code, out))
    snap, mem = tree(BOARDS), MEMBERS.read_bytes()
    code, out = run_cli("lab", "alice@example.com", "bob@example.com", "--port", "8051", "--yes", server=fake)
    check("cli: a second run says there is nothing to do and changes nothing", code == 0 and "nothing to do" in out and tree(BOARDS) == snap and MEMBERS.read_bytes() == mem, (code, out))
    code, out = run_cli("Bad_Name", "alice@example.com", "--port", "8052", server=fake)
    check("cli: a bad name exits 2", code == 2 and "not a board name" in out and not (BOARDS / "Bad_Name").exists(), (code, out))
    code, out = run_cli("other", "not-an-address", "--port", "8052", server=fake)
    check("cli: a bad address exits 2", code == 2 and "not an address" in out, (code, out))
    code, out = run_cli("lab", "alice@example.com", "--port", "9000", "--yes", server=fake)
    check("cli: another port for an existing board is a failure", code == 1 and "another port" in out, (code, out))
    code, out = run_cli("other", "alice@example.com", "--port", "8052", "--yes", server=Fake())
    check("cli: a second board is made beside it", code == 0 and (BOARDS / "other/stackshot.toml").exists(), (code, out))
    code, out = run_cli("third", "alice@example.com")
    check("cli: --port is required", code == 2, (code, out))
    # no server set
    OWNER_CFG.write_text(OWNER_CFG.read_text().replace(served, ""))
    code, out = run_cli("fourth", "alice@example.com", "--port", "8053")
    check("cli: with no server set the dry run says unknown and exits 0", code == 0 and "[unknown" in out and "no database server is set" in out, (code, out))
    code, out = run_cli("fourth", "alice@example.com", "--port", "8053", "--yes")
    check("cli: with no server set --yes makes nothing and exits 1", code == 1 and not (BOARDS / "fourth").exists(), (code, out))
    # the config the command writes is the board's own, and the code reads it
    cfgfile = BOARDS / "lab/stackshot.toml"
    r = subprocess.run([sys.executable, "-m", "stackshot.core.config", "get", "behind_frontdoor.board_name"],
                       capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": str(cfgfile)}, cwd=STACK)
    check("cli: the board's config is read by the code as this board's", r.returncode == 0 and r.stdout.strip() == "lab", (r.returncode, r.stdout, r.stderr[-400:]))


# ---------------------------------------------------------------- the real server, when one can be started
def find_pg():
    for d in [*(os.environ.get("PATH", "").split(":")), *sorted(pathlib.Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)]:
        if d and os.path.exists(os.path.join(d, "initdb")) and os.path.exists(os.path.join(d, "pg_ctl")):
            return str(d)
    return None


def part_psql():
    bindir = find_pg()
    psql = shutil.which("psql") or (os.path.join(bindir, "psql") if bindir and os.path.exists(os.path.join(bindir, "psql")) else None)
    if not bindir or not psql or os.geteuid() == 0:
        print("skipped: no PostgreSQL server can be started here (initdb, pg_ctl and psql, not as root); PsqlServer is covered by the stand-in only")
        return
    data, sock = T / "pgdata", T / "pgsock"
    sock.mkdir(); port = 54000 + os.getpid() % 900
    run = lambda *a, **k: subprocess.run(a, capture_output=True, text=True, **k)
    r = run(os.path.join(bindir, "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "--no-sync")
    check("psql: the throwaway server is initialised", r.returncode == 0, r.stderr[-400:])
    if r.returncode:
        return
    started = False
    try:
        r = run(os.path.join(bindir, "pg_ctl"), "-D", str(data), "-w", "-t", "60", "-l", str(T / "pg.log"), "-o", f"-c listen_addresses='' -c unix_socket_directories={sock} -p {port} -c fsync=off", "start")
        started = r.returncode == 0
        check("psql: the throwaway server starts", started, (r.stderr + r.stdout)[-400:] + (T / "pg.log").read_text()[-400:] if (T / "pg.log").exists() else "")
        if not started:
            return
        srv = bc.PsqlServer(bc.ServerSettings(host=str(sock), port=port, admin_user="postgres", psql=psql))
        a, b = "brain_" + "1" * 32, "brain_" + "2" * 32
        check("psql: nothing exists at first", srv.state(a, a) == (False, False))
        srv.create(a, a, "lab", "p" * 32)
        srv.create(a, a, "lab", "p" * 32)
        srv.create(b, b, "other", "q" * 32)
        check("psql: login and database are there after two creates", srv.state(a, a) == (True, True) and srv.state(b, b) == (True, True))

        def q(sql):
            return run(psql, "-X", "-tA", "-h", str(sock), "-p", str(port), "-U", "postgres", "-d", "postgres", "-c", sql).stdout.strip()
        check("psql: the board's name is the comment", q(f"SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = '{a}'") == "lab")
        check("psql: the login owns its database", q(f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '{a}'") == a)
        check("psql: its own login may connect, the other board's may not", q(f"SELECT has_database_privilege('{a}', '{a}', 'CONNECT')") == "t"
              and q(f"SELECT has_database_privilege('{b}', '{a}', 'CONNECT')") == "f")
        check("psql: the address has no password", "p" * 32 not in srv.address(a, a) and srv.address(a, a).startswith(f"postgresql://{a}@"))
        srv.drop(a, a)
        check("psql: drop takes both away and the other board stays", srv.state(a, a) == (False, False) and srv.state(b, b) == (True, True))
        srv.drop(a, a)
        e = raised(bc.PsqlServer(bc.ServerSettings(host=str(sock), port=port, admin_user="nobody-here", psql=psql)).create, "x" + a, "x" + a, "lab", "s" * 32)
        check("psql: an error is a BrainServerError and never holds the password", isinstance(e, bc.BrainServerError) and "s" * 32 not in str(e), e)
        e = raised(bc.PsqlServer(bc.ServerSettings(host=str(sock), port=port + 1, admin_user="postgres", psql=psql)).state, a, a)
        check("psql: a port with no server is a BrainServerError", isinstance(e, bc.BrainServerError), e)
        e = raised(bc.PsqlServer(bc.ServerSettings(host=str(sock), port=port, admin_user="postgres", psql="/no/such/psql")).state, a, a)
        check("psql: a missing program is a BrainServerError", isinstance(e, bc.BrainServerError) and "not found" in str(e), e)
        # the whole command on the real server
        shutil.rmtree(BOARDS, ignore_errors=True); reset_members()
        st = bc.Settings(str(BOARDS), str(MEMBERS), bc.ServerSettings(host=str(sock), port=port, admin_user="postgres", psql=psql))
        make(st=st, fake=bc.PsqlServer(st.server), ident=lambda: "9" * 32)
        again = bc.make_plan(st, bc.Request("lab", ("alice@example.com", "bob@example.com"), 8051), bc.PsqlServer(st.server))
        check("psql: the command's run on the real server is complete and a repeat is done", again.done and again.login == "brain_" + "9" * 32, states(again))
    finally:
        if started:
            run(os.path.join(bindir, "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop")


try:
    for part in (part_name, part_plan, part_run, part_repeat, part_refusals, part_failures, part_cli, part_psql):
        try:
            part()
        except Exception:      # noqa: BLE001
            check(f"{part.__name__} ran to its end", False, traceback.format_exc()[-1500:])
finally:
    pass

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
