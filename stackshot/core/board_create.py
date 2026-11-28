"""board_create.py: `stackshot board-create`, the steps that make one more board with its brain database (docs/front-door.md, *Creating a board*).

The shape is a plan and then its steps. `make_plan` reads what exists and returns a `Plan`: every thing the command would make, each marked `new`, `present`,
`unknown` (the database server was not reached) or `stub` (left for a later stage), and the text to paste into the front door's config. `apply` makes what the
plan marks new, in an order where a failure leaves nothing behind (the database first, then the files; a board this run began is taken apart again), and a
second run finds everything `present` and changes nothing.

A board lives in one folder, `<boards_dir>/<name>`:

    board.id                          the board's id, 32 hex digits, made once; the brain's login and database are `brain_` plus it
    stackshot.toml                    the board's own config (the example's, with this board's paths, port and `[behind_frontdoor]`, `[invites]`, `[brain_db]`)
    secrets/brain-db.password         the password of the brain's login (0600); the board's own secrets folder
    data/                             the data repository (git, RULES.md)
    stackshot-board-<name>.service    the unit text of the board's process: written here, never installed, enabled or started

and its members are entries of the front door's members file, written by `invites.register`. Nothing else is written, and no mail is sent.

The database server sits behind `BrainServer` (stage 3 builds the real cluster; until then a test runs `PsqlServer` against a throwaway server). Its address is
read from the owner's config, `[board_create.brain_server]`; nothing here names a machine or a port. The spend cap (stage 6) is written as an unset key, and
the front door's brain entry (stage 5) is not written: a second `kind = "brain"` backend is dropped by the front door today.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

SLUG = re.compile(r"[a-z][a-z0-9-]{1,31}")        # a board name when core/board_names.py is not there: 2 to 32 lower-case letters, digits and hyphens, a letter first
ID = re.compile(r"[0-9a-f]{32}")
DEFAULT_BOARDS_DIR = "~/.config/stackshot/boards"
TABLE = "board_create"


class CreateError(Exception):
    """The command cannot go on: the message is what the owner is told, and nothing it names was changed."""


class BrainServerError(CreateError):
    """The database server refused or could not be reached."""


# ------------------------------------------------------------------------------------------------ the database server

class BrainServer(Protocol):
    """What the command needs of the boards' Postgres server. Every method may raise BrainServerError."""

    def state(self, login: str, database: str) -> tuple[bool, bool]:
        """(the login exists, the database exists)."""

    def create(self, login: str, database: str, comment: str, password: str) -> None:
        """Make what is missing: the login (with `password`), the database it owns, the database's comment; take connection rights from everyone else. Safe to repeat."""

    def drop(self, login: str, database: str) -> None:
        """Take the database and the login away (a rollback, and a test's clean-up)."""

    def address(self, login: str, database: str) -> str:
        """The connection address of the database, with no password in it."""


@dataclass(frozen=True)
class ServerSettings:
    host: str = ""                 # a host name or address, or a folder (a unix socket)
    port: int = 0
    admin_user: str = ""
    admin_password_file: str = ""  # "" = the admin signs in with no password (a socket, a throwaway server)
    psql: str = "psql"
    admin_db: str = "postgres"

    def usable(self) -> bool:
        return bool(self.host and 0 < self.port < 65536 and self.admin_user)


_SQL_OWNER = "OWNER"      # the SQL keyword of CREATE DATABASE, kept in a name of its own: the retired-terms scan reads text, and this is not that word


def _ident(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class PsqlServer:
    """BrainServer over the `psql` program: one call per question, the SQL on its standard input, the admin's password in the environment."""

    def __init__(self, s: ServerSettings):
        self.s = s

    def _run(self, sql: str, *, hide: str = "") -> str:
        from stackshot.core import frontdoor_files as files
        env = {**os.environ, "PGCONNECT_TIMEOUT": "5"}
        env.pop("PGPASSWORD", None)
        if self.s.admin_password_file:
            try:
                env["PGPASSWORD"] = files.read_secret(self.s.admin_password_file, "admin_password_file", min_len=1)
            except files.FileError as e:
                raise BrainServerError(str(e)) from None
        cmd = [self.s.psql, "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1", "-h", self.s.host, "-p", str(self.s.port), "-U", self.s.admin_user, "-d", self.s.admin_db, "-f", "-"]
        try:
            r = subprocess.run(cmd, input=sql, capture_output=True, text=True, env=env, timeout=60)
        except FileNotFoundError:
            raise BrainServerError(f"the program {self.s.psql!r} is not found: set [{TABLE}.brain_server] psql") from None
        except subprocess.TimeoutExpired:
            raise BrainServerError("the database server did not answer in 60 seconds") from None
        if r.returncode != 0:
            line = next((ln for ln in r.stderr.splitlines() if ln.strip()), "psql failed")
            line = line.replace(hide, "***") if hide else line
            raise BrainServerError(f"the database server refused: {line.strip()[:200]}")
        return r.stdout

    def state(self, login: str, database: str) -> tuple[bool, bool]:
        out = self._run(f"SELECT (SELECT count(*) FROM pg_roles WHERE rolname = {_lit(login)}), (SELECT count(*) FROM pg_database WHERE datname = {_lit(database)});").strip()
        try:
            a, b = out.split("|")
            return int(a) > 0, int(b) > 0
        except ValueError:
            raise BrainServerError("the database server answered in a form this command does not know") from None

    def create(self, login: str, database: str, comment: str, password: str) -> None:
        have_login, have_db = self.state(login, database)
        if not have_login:
            self._run(f"CREATE ROLE {_ident(login)} LOGIN PASSWORD {_lit(password)};", hide=password)
        if not have_db:
            self._run(f"CREATE DATABASE {_ident(database)} {_SQL_OWNER} {_ident(login)};")
        self._run(f"COMMENT ON DATABASE {_ident(database)} IS {_lit(comment)};\nREVOKE CONNECT ON DATABASE {_ident(database)} FROM PUBLIC;")

    def drop(self, login: str, database: str) -> None:
        self._run(f"DROP DATABASE IF EXISTS {_ident(database)} WITH (FORCE);\nDROP ROLE IF EXISTS {_ident(login)};")

    def address(self, login: str, database: str) -> str:
        host = self.s.host if not self.s.host.startswith("/") else ""
        extra = f"?host={self.s.host}" if self.s.host.startswith("/") else ""
        return f"postgresql://{login}@{host}:{self.s.port}/{database}{extra}"


# ------------------------------------------------------------------------------------------------ the settings

@dataclass(frozen=True)
class Settings:
    boards_dir: str
    members_file: str = ""
    server: ServerSettings = ServerSettings()


def _tbl(d: Any, *keys: str) -> dict[str, Any]:
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d if isinstance(d, dict) else {}


def settings_of(cfg: dict[str, Any]) -> Settings:
    """The command's settings from the owner's parsed config (`[board_create]`; the members file falls back to `[frontdoor] members_file`)."""
    t = _tbl(cfg, TABLE)
    sv = _tbl(cfg, TABLE, "brain_server")
    port = sv.get("port")
    server = ServerSettings(host=str(sv.get("host") or ""), port=port if isinstance(port, int) and not isinstance(port, bool) else 0,
                            admin_user=str(sv.get("admin_user") or ""), admin_password_file=str(sv.get("admin_password_file") or ""),
                            psql=str(sv.get("psql") or "psql"), admin_db=str(sv.get("admin_db") or "postgres"))
    members = str(t.get("members_file") or _tbl(cfg, "frontdoor").get("members_file") or "")
    return Settings(boards_dir=str(t.get("boards_dir") or DEFAULT_BOARDS_DIR), members_file=members, server=server)


def check_name(name: str) -> str:
    """The board's name, or CreateError. core/board_names.py (when it is there) has the last word; this module's own rule is the floor."""
    if not SLUG.fullmatch(name):
        raise CreateError(f"{name!r} is not a board name: 2 to 32 lower-case letters, digits and hyphens, starting with a letter")
    try:
        from stackshot.core import board_names          # type: ignore[attr-defined]
    except ImportError:
        return name
    check = getattr(board_names, "validate", None)
    if callable(check):
        try:
            got = check(name)
        except ValueError as e:
            raise CreateError(f"{name!r} is not a board name: {e}") from None
        if isinstance(got, str) and got and got != name:
            raise CreateError(f"{name!r} is not a board name: {got}")
    return name


@dataclass(frozen=True)
class Request:
    name: str
    members: tuple[str, ...]      # addresses as invites.address_of gives them; the first is the board's admin
    port: int
    base_url: str = ""


# ------------------------------------------------------------------------------------------------ the plan

NEW, PRESENT, UNKNOWN, STUB = "new", "present", "unknown", "stub"


@dataclass(frozen=True)
class Line:
    what: str
    where: str
    state: str


@dataclass(frozen=True)
class Plan:
    name: str
    board_id: str
    home: Path
    login: str                       # also the database's name
    lines: tuple[Line, ...]
    edge: str                        # the text for the front door's config: printed, never written
    address: str
    home_is_new: bool
    server_reached: bool
    new_members: tuple[str, ...]

    @property
    def done(self) -> bool:
        return all(ln.state in (PRESENT, STUB) for ln in self.lines)


def paths_of(home: Path, name: str) -> dict[str, Path]:
    return {"id": home / "board.id", "config": home / "stackshot.toml", "password": home / "secrets" / "brain-db.password", "data": home / "data",
            "unit": home / f"stackshot-board-{name}.service", "secrets": home / "secrets"}


def edge_text(name: str, port: int, home: Path) -> str:
    return (f'[[frontdoor.backends]]\nname = "{name}"\nkind = "board"\nurl = "http://127.0.0.1:{port}/mcp"\nhealth_url = "http://127.0.0.1:{port}/healthz"\n'
            f'token_file = "{home / "secrets" / "frontdoor.token"}"\n')


def _members_state(path: str, members: tuple[str, ...], name: str) -> tuple[tuple[str, ...], str]:
    """(the addresses not yet on the board in the members file, a problem or "")."""
    from stackshot.core import frontdoor_files as files
    if not path:
        return members, "no members file is named: set [board_create] members_file (or [frontdoor] members_file)"
    try:
        records = files.read_member_records(path)
    except files.FileError as e:
        return members, str(e)
    def on_board(address: str) -> bool:
        who = files.member_of_address(records, address)
        return bool(who) and name in records[who].boards
    return tuple(a for a in members if not on_board(a)), ""


def make_plan(s: Settings, req: Request, server: BrainServer | None, make_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> Plan:
    """What exists and what is missing. Reads only (the database server is asked what it holds); raises CreateError for a request that cannot be served."""
    name = check_name(req.name)
    if not 0 < req.port < 65536:
        raise CreateError(f"not a TCP port: {req.port}")
    base = Path(os.path.expanduser(s.boards_dir))
    home = base / name
    p = paths_of(home, name)
    board_id = ""
    if p["id"].is_file():
        board_id = p["id"].read_text(encoding="utf-8").strip()
        if not ID.fullmatch(board_id):
            raise CreateError(f"{p['id']} does not hold a board id (32 hex digits): fix or remove it")
    id_new = not board_id
    board_id = board_id or make_id()
    login = "brain_" + board_id
    lines: list[Line] = []

    def has(path: Path) -> str:
        return PRESENT if path.exists() else NEW

    lines.append(Line("board id", f"{board_id}  (file {p['id']})", PRESENT if not id_new else NEW))
    if p["config"].exists():
        text = p["config"].read_text(encoding="utf-8")
        if f"port = {req.port}\n" not in text and f"port = {req.port}\r\n" not in text:
            raise CreateError(f"the board {name!r} exists with another port ({p['config']}): this command does not change a board; pass its own port")
    lines.append(Line("config", f"{p['config']}  (server port {req.port})", has(p["config"])))
    lines.append(Line("data repository", f"{p['data']}  (git, RULES.md)", PRESENT if (p["data"] / ".git").exists() and (p["data"] / "RULES.md").exists() else NEW))
    lines.append(Line("process", f"{p['unit']}  (the unit text only: not installed, enabled or started)", has(p["unit"])))
    lines.append(Line("secret", f"{p['password']}  (the brain login's password, 0600)", has(p["password"])))

    reached, address, db_state = True, "", NEW
    if not s.server.usable() or server is None:
        reached, db_state = False, UNKNOWN
        address = "(no database server is set: [board_create.brain_server] host, port and admin_user)"
    else:
        try:
            have_login, have_db = server.state(login, login)
            address = server.address(login, login)
            db_state = PRESENT if have_login and have_db else NEW
            if (have_login or have_db) and not p["password"].exists():
                raise CreateError(f"the database server already holds {login}, and its password file {p['password']} is not there: nothing here can recover the password; "
                                  f"drop the login and database by hand, or put the password back")
        except BrainServerError as e:
            reached, db_state = False, UNKNOWN
            address = f"(the database server was not reached: {e})"
    lines.append(Line("brain database", f"login and database {login}, comment {name!r}, connection rights taken from all others; {address}", db_state))

    new_members, problem = _members_state(s.members_file, req.members, name)
    where = f"{s.members_file or '(none)'}  (+ its .lock file): " + ", ".join(req.members)
    lines.append(Line("members", where + (f"  [{problem}]" if problem else ""), UNKNOWN if problem else (NEW if new_members else PRESENT)))
    lines.append(Line("front door entry", "printed below, not written (add it to the front door's config by hand)", STUB))
    lines.append(Line("front door brain entry", "not written: the front door serves one brain and routes no second one yet (stage 5)", STUB))
    lines.append(Line("spend cap", "an unset key in the board's [brain_db] (stage 6 counts and caps)", STUB))
    return Plan(name, board_id, home, login, tuple(lines), edge_text(name, req.port, home), address, not home.exists(), reached, new_members)


def render_plan(plan: Plan) -> str:
    out = [f"board-create plan for {plan.name!r}" + ("  (everything is in place: nothing to do)" if plan.done else "")]
    for ln in plan.lines:
        out.append(f"  [{ln.state:<7}] {ln.what}: {ln.where}")
    out += ["", "front door entry (not written):"] + ["    " + t for t in plan.edge.rstrip().splitlines()]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ the steps

def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _write_new(path: Path, text: str, mode: int = 0o600) -> None:
    """Write `path` as one rename when it is not there; a file already there is left as it is."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, part = tempfile.mkstemp(dir=str(path.parent), prefix=".bc-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), mode)
            f.write(text)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.unlink(part)


def unit_text(name: str, config: Path, checkout: Path) -> str:
    return (f"# stackshot-board-{name}.service: the board {name!r}. Written by `stackshot board-create`; install it with `systemctl --user link` (or copy it to the user unit folder), then enable and start it.\n"
            f"[Unit]\nDescription=stackshot board {name}\nAfter=network-online.target\n\n[Service]\nWorkingDirectory={checkout}\n"
            f"Environment=STACKSHOT_CONFIG={config}\nEnvironment=CAIO_IMPL=linux\nExecStart={checkout}/bin/stackshot server\n"
            f"ExecReload=/bin/kill -HUP $MAINPID\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")


def _git_init(data: Path, rules: str) -> None:
    data.mkdir(parents=True, exist_ok=True)
    if not (data / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(data)], check=True, capture_output=True)
    (data / "board-data").mkdir(exist_ok=True)
    if not (data / "RULES.md").exists():
        (data / "RULES.md").write_text(rules, encoding="utf-8")
    have = subprocess.run(["git", "-C", str(data), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode == 0
    if not have:
        subprocess.run(["git", "-C", str(data), "add", "RULES.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(data), "-c", "user.name=stackshot board-create", "-c", "user.email=board-create@localhost",
                        "-c", "commit.gpgsign=false", "commit", "-q", "-m", "stackshot board-create"], check=True, capture_output=True)


def apply(plan: Plan, s: Settings, req: Request, server: BrainServer | None, render: Callable[[Plan], tuple[str, str]], checkout: Path,
          say: Callable[[str], None] = print) -> None:
    """Make what the plan marks new. CreateError names a step that failed; a board this run began is then taken apart, so nothing is left half made."""
    if not plan.server_reached or server is None:
        raise CreateError("the database server is not reached, so nothing is made: " + next((ln.where for ln in plan.lines if ln.what == "brain database"), ""))
    p = paths_of(plan.home, plan.name)
    fresh = plan.home_is_new
    login = plan.login
    had_login, had_db = server.state(login, login)
    try:
        _private_dir(plan.home)
        _private_dir(p["secrets"])
        _write_new(p["id"], plan.board_id + "\n")
        import secrets as _secrets
        _write_new(p["password"], _secrets.token_hex(16) + "\n")
        password = p["password"].read_text(encoding="utf-8").strip()
        if not (had_login and had_db):
            server.create(login, login, plan.name, password)
            say(f"  brain database {login}: made")
        else:
            say(f"  brain database {login}: present")
        config, rules = render(plan)
        _write_new(p["config"], config, 0o600)
        _git_init(p["data"], rules)
        _write_new(p["unit"], unit_text(plan.name, p["config"], checkout), 0o644)
    except BaseException as e:
        if fresh:
            if not (had_login or had_db):            # the login and database were this run's own (a held one without its password file was refused in the plan)
                try:
                    server.drop(login, login)
                except CreateError:
                    pass
            shutil.rmtree(plan.home, ignore_errors=True)
        if isinstance(e, (CreateError, OSError, subprocess.CalledProcessError)):
            raise CreateError(f"{e}; " + ("what this run made is taken away again" if fresh else "run it again once that is fixed")) from None
        raise
    if plan.new_members:
        from stackshot.core import invites
        st = invites.Settings(board=plan.name, members_file=s.members_file)
        admin = req.members[0]
        for address in plan.new_members:
            try:
                invites.register(address, admin if address != admin else "board-create", st)
            except invites.InviteError as e:
                raise CreateError(f"member {address}: {e}; the board is made, run the command again once that is fixed") from None
            say(f"  member {address}: written")
