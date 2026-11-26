"""tests/frontdoor_signin_run_scenario.py: the whole sign-in path with real processes: a caller's bearer token, the sign-in service, the board that checks it, the front door, and the
board that records who called; with a real Caddy as the reverse proxy when this machine has one.

Hermetic, with nothing but this machine's loopback (making the `server` environment may fetch what uv has not cached). Under one scratch folder (tests/_scratch.py: locked while the suite runs, removed when it ends, pass or fail) it makes
  * two boards, `main` and `side`, each its own process (`stackshot/web/server.py`) with its own config, store, port, sign-in (Google, a made-up client; its machine token is the
    caller's bearer here, and `[auth] portal_identity` is the address the token stands for), its copy of the signing secret and of the check's secret, and a `[behind_frontdoor]`
    table that checks the signed identity, reads the members file and answers the token check;
  * one front door (`python -m stackshot.frontdoor`) in front of both;
  * two sign-in services (`python -m stackshot.frontdoor.signin`), one asking each board (a token is a board's own, so each service knows one caller; it is the board's machine
    token, so both run with `accept_portal_token = true`), each started with the interpreter of an environment that holds what the `server` extra installs and nothing of the tests
    group (tests/_server_env.py);
  * when `caddy` is on the PATH, one Caddy whose sites are the block docs/front-door.md gives, word for word but for the address and the ports: one site per service, with that
    board's `[auth] base_url` set to the site's address; one more whose board and front door are stand-ins that record each request; and one whose check is a stand-in that answers
    200 with no identity. Without `caddy` the Caddy checks are skipped and the summary says so.
Every port is a free one chosen at run time on 127.0.0.1, every process has a HOME and a TMPDIR of its own inside the scratch folder, a child asks the kernel to end it with this
process (so a killed suite leaves none) and is stopped by its PID. Without Caddy the test plays the reverse proxy: it asks the service as Caddy does and sends the front door the
identity the service answered with.

Proves: the address a board names (its second address, in another case) becomes the member's key, and the boards record that key; each caller reaches her own boards; a bearer the
board refuses is 401 with whatever WWW-Authenticate the board's own check answers with, and one no member holds goes on to the door, which says so; an address that is written as a
member's key and is not among that member's sign-in addresses is 403 although the door would take it; the service does not start on a verify secret that is the identity secret; the
board's machine token is 403 unless the service is set to accept it; a board that is down, a secret that differs and a service that is down are never a 200 and (the first two) never a
401; each part serves again after a restart or a rotation with no other restart; no token, secret or address is in a service's log, nor a query string, a websocket upgrade's included;
through Caddy, a header the client sends itself never becomes the caller, the board's discovery and sign-in paths reach it without a token and name the public address, nothing else
passes unchecked however its path is written, and nothing reaches the front door that the service did not accept.

    tests/run-suite frontdoor_signin_run        -> exit 0 / 1"""
import asyncio, base64, hashlib, http.client, itertools, json, os, pathlib, re, secrets, shutil, signal, socket, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance, _server_env
from stackshot.core import behind_door as door_mod, frontdoor_identity as ident
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

tmp = _scratch.mkdtemp(prefix="signin-run-"); T = pathlib.Path(tmp)
fails, ran, skipped = [], [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""), flush=True)


ALICE, ALICE_ALT, BOB, BOB_SIDE = "alice@example.invalid", "Alice.Alt@Example.Invalid", "bob@example.invalid", "Bob.Side@Example.Invalid"
MAIN, SIDE = "main", "side"
PROJECT = "projects/alpha"
SECRET = secrets.token_urlsafe(24)                    # the front door's signing secret, copied for each board
VERIFY = {MAIN: secrets.token_urlsafe(24), SIDE: secrets.token_urlsafe(24)}      # each board's secret for the sign-in service's check
BEARER = {MAIN: secrets.token_urlsafe(36), SIDE: secrets.token_urlsafe(36)}      # each board's machine token: the caller's bearer here
MEMBERS = {ALICE: {"boards": [MAIN, SIDE], "emails": [ALICE, ALICE_ALT]}, BOB: {"boards": [SIDE], "emails": [BOB, BOB_SIDE]}}
NOT_A_MEMBER = "you are not a member of any board."


# ------------------------------------------------------------------------------------------------ files and processes
def write_secret(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.chmod(path, 0o600)
    return str(path)


def free_ports(n):
    """n distinct free ports on 127.0.0.1, all held together until every one is chosen."""
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


INIT = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'


def raw(url, headers=None, method="GET", body=None):
    """(status, {header: value}, text) of one plain request; status 0 and the error's name when nothing answers."""
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    req = urllib.request.Request(url, data=(body or INIT) if method == "POST" else None, headers=h, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(4000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, {}, type(e).__name__


def _die_with_parent():
    """Runs in the child before its program starts: the kernel ends the child (SIGTERM) when this process ends, killed or not."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)       # PR_SET_PDEATHSIG
    except Exception:       # noqa: BLE001  (a platform without it: the suite's `finally` stops every child itself)
        pass


class Proc:
    """One server process: start it, wait until it answers, stop it by its PID."""
    def __init__(self, name, argv, env, cwd, port, up_path="/healthz", up_status=(200,)):
        self.name, self.argv, self.env, self.cwd, self.port, self.path, self.up = name, argv, env, str(cwd), port, up_path, up_status
        self.err_path = T / f"{name}.err"; self.p = None

    def start(self, timeout=150):
        with open(self.err_path, "ab") as err:
            self.p = subprocess.Popen(self.argv, env=self.env, cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=err, stderr=err, preexec_fn=_die_with_parent)
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None:
                return False
            if raw(f"http://127.0.0.1:{self.port}{self.path}")[0] in self.up:
                return True
            time.sleep(0.3)
        return False

    def stop(self):
        """Ends the process by its PID (SIGTERM, then SIGKILL after 25 s); → its exit code, or None when it was not running."""
        if self.p is None or self.p.poll() is not None:
            return None
        self.p.terminate()
        try:
            self.p.wait(25)
        except subprocess.TimeoutExpired:
            self.p.kill(); self.p.wait(15)
        return self.p.returncode

    def running(self):
        return self.p is not None and self.p.poll() is None

    def log(self):
        try:
            return self.err_path.read_text(errors="replace")
        except OSError:
            return ""

    def tail(self):
        return self.log()[-700:]


def clean_env():
    """The environment of a child: this one without anything of a stackshot instance, of the user's directories or of an HTTP proxy."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("STACKSHOT_", "BOARD_MCP_", "XDG_")) and not k.lower().endswith("_proxy") or k == "STACKSHOT_XLOCK_STRICT"}


def own_env(root, **more):
    for d in ("home", "tmp"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return {**clean_env(), "PYTHONPATH": STACK, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), **more}


MEMBERS_FILE = T / "door" / "members.json"
ROOT, URL = {}, {}


def write_members(d):
    MEMBERS_FILE.write_text(json.dumps(d))


def build_board(label, port, identity, public=None):
    """One board's instance on a folder of its own; → the Proc. `identity` is the address its machine token stands for, `public` the address its own sign-in is reached at
    (`[auth] base_url`) when a proxy passes those paths to it."""
    root = T / label
    for d in ("store/a", "state", "secrets", "touch", "brain/projects", "fleet/a", "home", "tmp"):
        (root / d).mkdir(parents=True)
    toml = _instance.base_toml()
    toml = re.sub(r'(?m)^process = "inline"', 'process = "unit"', toml, count=1)         # the server starts no runner thread
    toml = re.sub(r'(?m)^session_links = ".*"', 'session_links = ""', toml, count=1)
    assert 'session_links = ""' in toml
    for key, val in (("repo", root), ("store", root / "store"), ("markdown", root / "board.md"), ("brain", root / "brain"), ("state", root / "state"), ("secrets", root / "secrets"),
                     ("project_touch", root / "touch"), ("fleet_names", root / "names.tsv"), ("rules", root / "RULES.md"), ("claude_credentials", root / "none.json")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"'), (r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"),
                     (r"(?m)^port = 8020", f"port = {port}"), (r"(?m)^every_minutes = 10", "every_minutes = 1440"), (r"(?m)^panel = true", "panel = false"),
                     (r'(?m)^portal_identity = ""', f'portal_identity = "{identity}"')):
        toml, n = re.subn(pat, rep, toml, count=1); assert n == 1, pat
    if public:
        toml, n = re.subn(r'(?ms)^(\[auth\]\n(?:(?!\[)[^\n]*\n)*?base_url = )"[^"]*"', rf'\g<1>"{public}"', toml); assert n == 1, "auth.base_url"
    write_secret(root / "identity.key", SECRET); write_secret(root / "verify.key", VERIFY[label])
    toml += (f'\n[behind_frontdoor]\nidentity_secret_file = "{root}/identity.key"\nmembers_file = "{MEMBERS_FILE}"\nboard_name = "{label}"\n'
             f'verify_secret_file = "{root}/verify.key"\n')
    (root / "stackshot.toml").write_text(toml, encoding="utf-8")
    (root / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    (root / "fleet/a/sessions.json").write_text("{}"); (root / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (root / "store/next-id").write_text("10"); (root / "store/anchors.json").write_text("{}")
    (root / "store/projects.json").write_text(json.dumps({"pages": {PROJECT: {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow",
                                                                                "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
    (root / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    env = own_env(root, STACKSHOT_CONFIG=str(root / "stackshot.toml"), STACKSHOT_FLEET_DIR=str(root / "fleet"), STACKSHOT_AUTH="google",
                  STACKSHOT_GOOGLE_CLIENT_ID="client.example.invalid", STACKSHOT_GOOGLE_CLIENT_SECRET="made-up-" + secrets.token_hex(8), STACKSHOT_PORTAL_TOKEN=BEARER[label])
    ROOT[label] = root
    return Proc(label, [sys.executable, os.path.join(STACK, "stackshot/web/server.py")], env, root, port)


def build_signin(board, port, board_port, python):
    root = T / f"signin-{board}"; root.mkdir()
    write_secret(root / "verify.key", VERIFY[board])
    (root / "stackshot.toml").write_text(f'[frontdoor_signin]\nlisten_port = {port}\nboard_verify_url = "http://127.0.0.1:{board_port}/frontdoor/verify"\n'
                                         f'verify_secret_file = "{root}/verify.key"\nmembers_file = "{MEMBERS_FILE}"\nidentity_secret_file = "{T}/door/identity.key"\ncache_seconds = 1\ntimeout_seconds = 5\n'
                                         f'accept_portal_token = true\n')
    ROOT["signin-" + board] = root
    return Proc("signin-" + board, [python, "-m", "stackshot.frontdoor.signin"], own_env(root, STACKSHOT_CONFIG=str(root / "stackshot.toml")), root, port)


# ------------------------------------------------------------------------------------------------ calls
async def _quiet(message):
    """The log lines a front door sends its client are not this suite's output."""


async def _call(url, headers, args):
    try:
        async with Client(StreamableHttpTransport(url, headers=headers), log_handler=_quiet) as c:
            r = await c.call_tool("anchors", args)
            return "ok", (r.content[0].text if r.content else "")
    except ToolError as e:
        return "refused", str(e)
    except Exception as e:      # noqa: BLE001  (a transport that is refused or does not answer)
        return "error", f"{type(e).__name__}: {str(e)[:200]}"


COUNTER = itertools.count(1)


def add(url, headers, board=None):
    """An anchor added through `url` with `headers`; → (its address, "ok"/"refused"/"error", the text)."""
    u = f"https://github.com/example-owner/example-repo/pull/{next(COUNTER)}"
    kind, text = asyncio.run(_call(url, headers, {"project": PROJECT, "add": [u], **({"board": board} if board else {})}))
    return u, kind, text


def recorded(board):
    """{url: who} of the anchors a board's store holds for the project: what the board itself wrote."""
    d = json.loads((ROOT[board] / "store/anchors.json").read_text())
    return {e["url"]: e.get("by") for e in d.get(PROJECT, [])}


def ask(board, token=None, extra=None):
    """What the proxy asks the sign-in service of `board`, with the caller's headers."""
    h = dict(extra or {})
    if token is not None:
        h["Authorization"] = "Bearer " + token
    return raw(URL["signin-" + board], h)


def board_check(board, token=None):
    """The board's own token check asked directly, as the service asks it."""
    h = {door_mod.VERIFY_HEADER: ident.sign(VERIFY[board].encode(), door_mod.VERIFY_WHO)}
    if token is not None:
        h["Authorization"] = "Bearer " + token
    return raw(URL["verify-" + board], h)


def proxied(board, token, extra=None, tool_board=None):
    """The test as the reverse proxy: ask the service; on 200 send the door the identity it answered with (and the caller's own Authorization, which stops at the door)."""
    st, hd, _ = ask(board, token, extra)
    if st != 200:
        return None, f"sign-in {st}", None
    return add(URL["door"], {"X-Forwarded-User": hd["x-verified-user"], "Authorization": "Bearer " + token}, tool_board)


# ------------------------------------------------------------------------------------------------ the checks
def played_proxy_checks():
    for board, want in ((MAIN, ALICE), (SIDE, BOB)):
        st, hd, body = ask(board, BEARER[board])
        check(f"service {board}: the board's token is 200 with the member's key (the board names {'her second address' if board == MAIN else 'his second address'}, in another case)",
              st == 200 and hd.get("x-verified-user") == want and body == "", (st, hd, body))
    for tool_board in (MAIN, SIDE):
        u, kind, text = proxied(MAIN, BEARER[MAIN], tool_board=tool_board)
        check(f"played proxy: alice's token reaches {tool_board} through the door and the board records her by her member key", kind == "ok" and recorded(tool_board).get(u) == ALICE, (kind, text))
    u, kind, text = proxied(SIDE, BEARER[SIDE])
    check("played proxy: bob's token reaches his one board, which records him", kind == "ok" and recorded(SIDE).get(u) == BOB, (kind, text))
    u, kind, text = proxied(SIDE, BEARER[SIDE], tool_board=MAIN)
    check("played proxy: bob cannot reach a board that is not his", kind == "refused" and "board 'main' is not one of your boards" in text and u not in recorded(MAIN), (kind, text))
    st, hd, _ = ask(MAIN, BEARER[MAIN], {"X-Verified-User": BOB, "X-Forwarded-User": BOB})
    check("service: a header the client sends itself is not the identity: alice's token stays alice", st == 200 and hd.get("x-verified-user") == ALICE and "x-forwarded-user" not in hd, (st, hd))


def refusal_checks():
    for label, token in (("no bearer", None), ("a token the board does not know", secrets.token_urlsafe(30)), ("the other board's token", BEARER[SIDE])):
        st, hd, body = ask(MAIN, token)
        bst, bhd, _ = board_check(MAIN, token)
        check(f"service: {label} is 401 where the board's own check says 401, with no identity", st == 401 == bst and "x-verified-user" not in hd and "invalid_token" in body, (st, bst, hd, body))
        check(f"service: {label}: the WWW-Authenticate text is the board's own, or none when the board's check answers with none", hd.get("www-authenticate") == bhd.get("www-authenticate"), (hd.get("www-authenticate"), bhd.get("www-authenticate")))
    odd = "töken-" + secrets.token_urlsafe(20)      # sent as latin-1 bytes
    bst = board_check(MAIN, odd)[0]
    st, hd, _ = ask(MAIN, odd)
    print(f"note: the board's own token check answers a bearer that is not ASCII with {bst}", flush=True)
    check("5xx: a bearer that is not ASCII, which the board's check does not accept, is refused by the service with no identity", bst != 200 and st == 401 and "x-verified-user" not in hd, (bst, st, hd))
    for label, spaced in (("a second space", " " + BEARER[MAIN]), ("a tab", "\t" + BEARER[MAIN])):
        bst = board_check(MAIN, spaced)[0]
        st, hd, _ = ask(MAIN, spaced)
        check(f"bearer: a good token after {label} is 401 at the board's check and at the service, with no identity", bst == st == 401 and "x-verified-user" not in hd, (bst, st, hd))


def member_checks():
    write_members({ALICE: MEMBERS[ALICE]})
    try:
        time.sleep(1.2)
        st, hd, _ = ask(SIDE, BEARER[SIDE])
        check("service: an address no member holds is not refused: it goes on in lower case", st == 200 and hd.get("x-verified-user") == BOB_SIDE.lower(), (st, hd))
        u, kind, text = proxied(SIDE, BEARER[SIDE])
        check("played proxy: ... and the front door tells that person they are not a member; nothing is written", kind == "refused" and NOT_A_MEMBER in text and u not in recorded(SIDE), (kind, text))
    finally:
        write_members(MEMBERS)
    st, hd, _ = ask(SIDE, BEARER[SIDE])
    check("service: the member put back is her key again at the next request", st == 200 and hd.get("x-verified-user") == BOB, (st, hd))
    old = BOB_SIDE.lower()      # a member listed under the very address the token stands for, whose sign-in addresses no longer hold it
    write_members({ALICE: MEMBERS[ALICE], old: {"boards": [SIDE], "emails": ["someone.new@example.invalid"]}})
    try:
        time.sleep(1.2)
        u, kind, text = add(URL["door"], {"X-Forwarded-User": old, "Authorization": "Bearer " + BEARER[SIDE]})
        check("membership: the front door matches keys exactly: told that identity, it would take the caller for that member, and the board records the member",
              kind == "ok" and recorded(SIDE).get(u) == "someone.new@example.invalid", (kind, recorded(SIDE).get(u), text[:200]))
        st, hd, _ = ask(SIDE, BEARER[SIDE])
        check("membership: the board's check accepts the token, and the service still refuses to pass the address on as that member (403, no identity)", st == 403 and "x-verified-user" not in hd and board_check(SIDE, BEARER[SIDE])[0] == 200, (st, hd))
    finally:
        write_members(MEMBERS)


def secret_checks(procs):
    root = ROOT["signin-" + MAIN]
    shared = write_secret(root / "shared.key", SECRET)      # the front door's identity secret, given to the service as its verify secret
    toml = (root / "stackshot.toml").read_text()
    assert f'verify_secret_file = "{root}/verify.key"' in toml
    for label, path in (("the same value", shared), ("a link to the same file", str(root / "linked.key"))):
        if path.endswith("linked.key"):
            os.symlink(T / "door/identity.key", path)
        (root / "shared.toml").write_text(toml.replace(f'verify_secret_file = "{root}/verify.key"', f'verify_secret_file = "{path}"'))
        env = {**procs["signin-" + MAIN].env, "STACKSHOT_CONFIG": str(root / "shared.toml")}
        for args in (["--check"], []):
            try:
                r = subprocess.run([*procs["signin-" + MAIN].argv, *args], env=env, cwd=str(root), capture_output=True, text=True, timeout=60, preexec_fn=_die_with_parent)
                got = (r.returncode, r.stdout[-200:] + r.stderr[-300:])
            except subprocess.TimeoutExpired:      # it is serving (run() ends it)
                got = ("still running", "")
            check(f"secrets: a verify secret that is {label} as the identity secret: {'--check' if args else 'serving'} exits 2 and prints no secret",
                  got[0] == 2 and "does not start" in got[1] and SECRET not in got[1], got)


def outage_checks(procs):
    main = procs[MAIN]
    check("outage: the board is stopped by its PID", main.stop() is not None and port_free(main.port), main.tail())
    time.sleep(1.2)      # past the service's cache
    for label, token in (("alice's token", BEARER[MAIN]), ("no token", None)):
        st, hd, _ = ask(MAIN, token)
        check(f"outage: with the board down, {label} is 503 with no identity, never 200 and never 401", st == 503 and "x-verified-user" not in hd and "www-authenticate" not in hd, (st, hd))
    st, _, _ = raw(URL["signin-health-" + MAIN])
    check("outage: the service itself is up", st == 200, st)
    check("outage: the board starts again", main.start(), main.tail())
    st, hd, _ = ask(MAIN, BEARER[MAIN])
    check("outage: the first request after the board is back is served", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))
    svc = procs["signin-" + MAIN]
    check("restart: the service is stopped by its PID and nothing answers", svc.stop() is not None and port_free(svc.port) and ask(MAIN, BEARER[MAIN])[0] == 0, svc.tail())
    check("restart: it starts again", svc.start(), svc.tail())
    st, hd, _ = ask(MAIN, BEARER[MAIN])
    check("restart: and serves the first request", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))
    new = secrets.token_urlsafe(24)
    write_secret(ROOT["signin-" + MAIN] / "verify.key", new); time.sleep(1.2)
    st, hd, _ = ask(MAIN, BEARER[MAIN])
    check("rotation: the service holds the new check secret and the board the old: 503, never 401", st == 503 and "x-verified-user" not in hd, (st, hd))
    write_secret(ROOT[MAIN] / "verify.key", new); VERIFY[MAIN] = new
    st, hd, _ = ask(MAIN, BEARER[MAIN])
    check("rotation: they agree: served at the next request with no restart", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))


def caddy_checks(procs):
    for board, want in ((MAIN, ALICE), (SIDE, BOB)):
        u, kind, text = add(URL["caddy-" + board], {"Authorization": "Bearer " + BEARER[board]}, MAIN if board == MAIN else None)
        where = MAIN if board == MAIN else SIDE
        check(f"caddy: {want.split('@')[0]}'s token through Caddy, the service and the door: {where} records the member's key", kind == "ok" and recorded(where).get(u) == want, (kind, text))
    for name in ("X-Forwarded-User", "X-Verified-User", "x-forwarded-user"):
        u, kind, text = add(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], name: BOB}, SIDE)
        check(f"caddy: a {name} the client sends itself is not the caller: the board records the token's member", kind == "ok" and recorded(SIDE).get(u) == ALICE, (kind, text, recorded(SIDE).get(u)))
    for label, headers in (("no bearer", {}), ("no bearer and a spoofed identity", {"X-Forwarded-User": ALICE, "X-Verified-User": ALICE}),
                           ("a bad bearer and a spoofed identity", {"Authorization": "Bearer " + secrets.token_urlsafe(30), "X-Forwarded-User": ALICE})):
        st, hd, body = raw(URL["caddy-" + MAIN], headers, method="POST")
        own = ask(MAIN, headers.get("Authorization", "").partition(" ")[2] or None)
        check(f"caddy: {label} is answered with the service's 401, its body and its WWW-Authenticate, and never reaches the door",
              st == 401 and "invalid_token" in body and "no identity" not in body and hd.get("www-authenticate") == own[1].get("www-authenticate"), (st, hd, body))
        u, kind, text = add(URL["caddy-" + MAIN], headers, MAIN)
        check(f"caddy: {label}: a tool call writes nothing", kind != "ok" and u not in recorded(MAIN), (kind, text))
    main = procs[MAIN]
    main.stop(); time.sleep(1.2)
    st, hd, body = raw(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, method="POST")
    u, kind, text = add(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, SIDE)
    check("caddy: with the board down Caddy answers the service's 503 (never 401, never the door), and a tool call writes nothing", st == 503 and "cannot check this token" in body and kind != "ok" and u not in recorded(SIDE), (st, body, kind, text))
    check("caddy: the board starts again", main.start(), main.tail())
    svc = procs["signin-" + MAIN]
    svc.stop()
    st, hd, body = raw(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, method="POST")
    u, kind, text = add(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, SIDE)
    check("caddy: with the service down Caddy answers an error (502), nothing reaches the door", st == 502 and kind != "ok" and u not in recorded(SIDE), (st, body, kind, text))
    check("caddy: the service starts again", svc.start(), svc.tail())
    u, kind, text = add(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN]}, MAIN)
    check("caddy: and the next call is served", kind == "ok" and recorded(MAIN).get(u) == ALICE, (kind, text))


def machine_token_checks(procs, caddy):
    """The bearer of these services is a board's machine token: without `accept_portal_token` it is refused, by the real board's own answer."""
    svc = procs["signin-" + MAIN]
    path = ROOT["signin-" + MAIN] / "stackshot.toml"
    toml = path.read_text()
    assert toml.count("accept_portal_token = true\n") == 1
    try:
        for label, text in (("with no accept_portal_token", toml.replace("accept_portal_token = true\n", "")), ("with accept_portal_token = false", toml.replace("accept_portal_token = true\n", "accept_portal_token = false\n"))):
            svc.stop(); path.write_text(text)
            check(f"machine token: the service starts {label}", svc.start(), svc.tail())
            st, hd, body = ask(MAIN, BEARER[MAIN])
            check(f"machine token: {label} the real board's machine token is 403 with no identity", st == 403 and "x-verified-user" not in hd and "machine token" in body and board_check(MAIN, BEARER[MAIN])[0] == 200, (st, hd, body))
            if caddy:
                st, hd, body = raw(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, method="POST")
                u, kind, text = add(URL["caddy-" + MAIN], {"Authorization": "Bearer " + BEARER[MAIN], "X-Forwarded-User": ALICE}, MAIN)
                check(f"machine token: {label} Caddy answers that 403 and a tool call writes nothing", st == 403 and "machine token" in body and kind != "ok" and u not in recorded(MAIN), (st, body, kind, text))
    finally:
        svc.stop(); path.write_text(toml)
        check("machine token: the service starts with it switched on again", svc.start(), svc.tail())
    st, hd, _ = ask(MAIN, BEARER[MAIN])
    check("machine token: switched on, it is the member's sign-in", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))


# ------------------------------------------------------------------------------------------------ the documented Caddy block
def documented_block():
    """The Caddy block docs/front-door.md gives for the sign-in service, word for word."""
    text = pathlib.Path(STACK, "docs/front-door.md").read_text(encoding="utf-8")
    section = text.split("\n## The sign-in service\n", 1)[1].split("\n## ", 1)[0]
    blocks = [b for b in re.findall(r"(?ms)^```[a-z]*\n(.*?)^```$", section) if "forward_auth" in b]
    assert len(blocks) == 1, f"{len(blocks)} Caddy blocks in the section"
    return blocks[0]


def site(port, signin_port, door_port, board_port):
    """The documented block as a site of this run: its address and its three ports replaced, and a path that says Caddy is up."""
    text = documented_block()
    head = "mcp.example.com {\n"
    assert text.count(head) == 1, head
    text = text.replace(head, f'http://127.0.0.1:{port} {{\n\tbind 127.0.0.1\n\thandle /caddy-up {{\n\t\trespond "up" 200\n\t}}\n')
    for documented, actual in (("127.0.0.1:8021", signin_port), ("127.0.0.1:8020", door_port), ("127.0.0.1:8010", board_port)):
        assert documented in text, f"the documented block names {documented}"
        text = text.replace(documented, f"127.0.0.1:{actual}")
    return text


class Recorder:
    """A stand-in upstream: it records each request (method, the request target as it arrived, the headers) and answers 200 with its own name."""
    def __init__(self, name):
        self.name = name; self.seen = []
        rec = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a): pass

            def any(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                rec.seen.append((self.command, self.requestline.split(" ")[1], [(k.lower(), v) for k, v in self.headers.items()]))      # (self.path has its leading slashes merged)
                body = rec.name.encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_GET = do_POST = do_HEAD = do_OPTIONS = any

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):      # a connection the proxy ends
                pass

        self.srv = Server(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True); self.th.start()

    def stop(self):
        self.srv.shutdown(); self.srv.server_close(); self.th.join(10)


def exact(port, target, headers=None, method="GET", body=None):
    """(status, {header: value}, text) of one request whose target is sent exactly as written; a redirect is not followed."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        c.putrequest(method, target, skip_accept_encoding=True)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        if method == "POST":
            c.putheader("Content-Length", str(len(body or b"")))
        c.endheaders(body or None)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read(20000).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException) as e:
        return 0, {}, type(e).__name__
    finally:
        c.close()


# the board's own sign-in: what reaches it with no token
PASSED = ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp", "/.well-known/openid-configuration", "/authorize", "/authorize?response_type=code&state=%2F..%2Fmcp",
          "/token", "/register", "/consent?txn_id=abc", "/auth/callback?code=x&state=y")
# everything else, however it is written: through the check, and to the front door only
CHECKED = ("/mcp", "/", "/frontdoor/verify", "/ui/login", "/ui/callback", "/auth", "/auth/callbackx", "/auth/callback/x", "/authorizex", "/authorize/", "/authorize/x", "/authorize;x", "/authorize%3F", "/token/revoke", "/consent/x",
           "/.well-known", "/.well-known/", "/.Well-Known/oauth-authorization-server", "/.WELL-KNOWN/oauth-protected-resource/mcp", "/Authorize", "/TOKEN", "/Register", "/Consent", "/Auth/Callback",
           "/%61uthorize", "/%2e%77ell-known/x", "/.well-known%2Foauth-authorization-server", "/auth%2Fcallback", "/.well-known/%2e%2e/mcp", "/.well-known/%2E%2E/%6Dcp", "/.well-known/..%2fmcp", "/.well-known/x%2f..%2f..%2fmcp",
           "/.well-known/../mcp", "/.well-known/./../mcp", "/.well-known/x/../../mcp", "/.well-known/..", "/.well-known/x/..;/mcp", "/.well-known/..%5Cmcp", "/.well-known//x", "//.well-known/oauth-authorization-server", "//authorize",
           "/./authorize", "/mcp/../authorize", "/x/../authorize", "/authorize/../mcp", "/token%2F..%2Fmcp", "/mcp/.well-known/oauth-protected-resource", "/x/authorize", "/mcp?next=/authorize", "/mcp?x=/.well-known/y")


def block_checks(port, board, door):
    """The documented block with a stand-in board and a stand-in front door behind it, and the real sign-in service of `main` as its check."""
    spoof = {"X-Forwarded-User": BOB, "x-forwarded-user": BOB}
    for target in PASSED:
        for method in ("GET", "POST"):
            board.seen.clear(); door.seen.clear()
            st, _, body = exact(port, target, {"X-Forwarded-User": BOB}, method)
            got = [(m, t) for m, t, _ in board.seen]
            check(f"paths: {method} {target} reaches the board with no token, as it was written, and the front door gets nothing", st == 200 and body == "board" and got == [(method, target)] and not door.seen, (st, body, got, door.seen[:1]))
            check(f"paths: {method} {target}: the identity header a client sends does not reach the board", all("x-forwarded-user" not in dict(h) for _, _, h in board.seen) and len(board.seen) == 1, [h for _, _, h in board.seen])
    for target in CHECKED:
        board.seen.clear(); door.seen.clear()
        st, hd, body = exact(port, target, spoof)
        check(f"paths: {target} with no token is the service's 401, and neither the board nor the front door gets anything", st == 401 and "invalid_token" in body and not board.seen and not door.seen, (st, body[:80], board.seen[:1], door.seen[:1]))
        board.seen.clear(); door.seen.clear()
        st, _, body = exact(port, target, {"Authorization": "Bearer " + BEARER[MAIN], **spoof})
        who = [v for m, t, h in door.seen for k, v in h if k == "x-forwarded-user"]
        check(f"paths: {target} with a good token goes to the front door only, as it was written, with the service's identity and no other", st == 200 and body == "door" and [t for _, t, _ in door.seen] == [target] and who == [ALICE] and not board.seen,
              (st, body[:80], [t for _, t, _ in door.seen], who, board.seen[:1]))


def no_identity_checks(port, door):
    """A check that answers 200 and names nobody: whatever the Caddy version, an identity the client sends is gone before the front door. (What arrives in its place depends on the
    version: nothing, an empty header, or the unfilled placeholder, which names no member.)"""
    for label, headers in (("X-Forwarded-User", {"X-Forwarded-User": BOB}), ("x-forwarded-user", {"x-forwarded-user": BOB}), ("two of them", {"X-Forwarded-User": BOB, "X-FORWARDED-USER": ALICE})):
        door.seen.clear()
        st, _, _ = exact(port, "/mcp", headers)
        who = [v for _, _, h in door.seen for k, v in h if k == "x-forwarded-user"]
        check(f"identity: with a check that names nobody, a client's own {label} does not reach the front door", st == 200 and len(door.seen) == 1 and not any("@" in v for v in who), (st, len(door.seen), who))


def discovery_checks(port, board_port):
    """The real board behind the documented block: its discovery and sign-in paths answer with no token and name the public address."""
    base = f"http://127.0.0.1:{port}"
    st, _, body = exact(port, "/.well-known/oauth-protected-resource/mcp")
    d = json.loads(body) if st == 200 else {}
    check("discovery: the protected resource metadata comes with no token and names the public address and its /mcp", d.get("resource") == base + "/mcp" and [str(x).rstrip("/") for x in d.get("authorization_servers") or []] == [base], (st, body[:300]))
    st, _, body = exact(port, "/.well-known/oauth-authorization-server")
    d = json.loads(body) if st == 200 else {}
    check("discovery: the authorization server metadata comes with no token and every endpoint is at the public address", str(d.get("issuer", "")).rstrip("/") == base and [d.get(k) for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")]
          == [base + "/authorize", base + "/token", base + "/register"], (st, body[:400]))
    redirect = "https://claude.ai/api/mcp/auth_callback"
    reg = json.dumps({"redirect_uris": [redirect], "client_name": "run check", "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}).encode()
    st, _, body = exact(port, "/register", {"Content-Type": "application/json"}, "POST", reg)
    client = json.loads(body).get("client_id") if st in (200, 201) else None
    check("sign-in: a client registers at the board through Caddy with no token", bool(client), (st, body[:300]))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(secrets.token_urlsafe(48).encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({"response_type": "code", "client_id": client or "", "redirect_uri": redirect, "code_challenge": challenge, "code_challenge_method": "S256", "state": "s1"})
    st, hd, body = exact(port, "/authorize?" + query)
    where = hd.get("location", "")
    check("sign-in: /authorize sends the new client on to the board's consent page at the public address", st in (302, 303, 307) and where.startswith(base + "/consent"), (st, where[:200], body[:200]))
    st, _, body = exact(port, where[len(base):]) if where.startswith(base) else (0, {}, "")
    check("sign-in: the consent page is the board's, with no token", st == 200 and "<form" in body.lower(), (st, body[:200]))
    for method, target, headers, data in (("POST", "/token", {"Content-Type": "application/x-www-form-urlencoded"}, b"grant_type=authorization_code&code=none&client_id=none"), ("GET", "/auth/callback?code=x&state=y", {}, None)):
        st, _, body = exact(port, target, headers, method, data)
        direct = exact(board_port, target, headers, method, data)
        check(f"sign-in: {method} {target.split('?')[0]} with no token is answered by the board, as it answers directly", st == direct[0] and st not in (0, 502, 503) and "the sign-in service" not in body and body[:60] == direct[2][:60], (st, direct[0], body[:200], direct[2][:200]))
    www = board_check(MAIN)[1].get("www-authenticate")
    if www:
        st, hd, _ = exact(port, "/mcp", {}, "POST", INIT)
        check("discovery: the 401 on /mcp names the metadata at the public address", st == 401 and f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"' in hd.get("www-authenticate", ""), (st, hd.get("www-authenticate")))


def upgrade(port, target, headers):
    """The status of a request that asks for a websocket upgrade (0: no status line came)."""
    lines = [f"GET {target} HTTP/1.1", f"Host: 127.0.0.1:{port}", "Connection: Upgrade", "Upgrade: websocket", "Sec-WebSocket-Version: 13", "Sec-WebSocket-Key: " + base64.b64encode(secrets.token_bytes(16)).decode(),
             *(f"{k}: {v}" for k, v in headers.items()), "", ""]
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
            sock.sendall("\r\n".join(lines).encode("latin-1"))
            first = sock.makefile("rb").readline().split()
        return int(first[1]) if len(first) > 1 else 0
    except OSError:
        return 0


def query_checks(caddy):
    """A query string on a request, which the proxy's check keeps from the caller's own: it is read by nothing and written nowhere. → the marker it carried."""
    marker = "query-" + secrets.token_urlsafe(18)
    query = f"?access_token={marker}&login_hint={ALICE}"
    st, hd, _ = raw(URL["signin-" + MAIN] + query, {"Authorization": "Bearer " + BEARER[MAIN]})
    check("service: a query string changes nothing: the answer is the bearer's", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))
    port = int(URL["signin-" + MAIN].split(":")[2].split("/")[0])
    st = upgrade(port, "/verify" + query, {"Authorization": "Bearer " + BEARER[MAIN]})
    check("service: a request that asks for a websocket upgrade is answered as any other", st == 200, st)
    st = upgrade(port, "/verify" + query, {})
    check("service: ... and with no token is 401", st == 401, st)
    if caddy:
        st, _, _ = raw(URL["caddy-" + MAIN] + query, {}, method="POST")
        check("caddy: a token in the query string is not a credential: 401", st == 401, st)
        st = upgrade(int(URL["caddy-" + MAIN].split(":")[2].split("/")[0]), "/mcp" + query, {})
        check("caddy: a websocket upgrade with a token in the query string is 401 too", st == 401, st)
    return marker


def log_checks(procs, marker):
    blob = procs["signin-" + MAIN].log() + procs["signin-" + SIDE].log()
    check("log: the services logged requests by a hash of the token", len(re.findall(r"token [0-9a-f]{8}\b", blob)) >= 6, blob[-600:])
    secret_values = [*BEARER.values(), *VERIFY.values(), SECRET]
    check("log: no token or secret is in a service's log", not any(v in blob for v in secret_values), [v[:4] for v in secret_values if v in blob])
    check("log: no address is in a service's log", "example.invalid" not in blob.lower(), [ln for ln in blob.splitlines() if "example.invalid" in ln.lower()][:3])
    check("log: nothing of a request's query string is in a service's log", marker not in blob and "access_token" not in blob, [ln for ln in blob.splitlines() if marker in ln or "access_token" in ln][:3])


# ------------------------------------------------------------------------------------------------ the run
PROCS = []


def main():
    caddy = shutil.which("caddy")
    ports = free_ports(9)
    door_port, main_port, side_port, sa_port, sb_port, ca_port, cb_port, rc_port, nc_port = ports
    check("setup: distinct free loopback ports, none a well-known one of an instance", len(set(ports)) == len(ports) and all(p > 1024 and p not in (8010, 8020, 8021) for p in ports))
    (T / "door").mkdir(); write_members(MEMBERS)
    server = _server_env.python(STACK, T / "server-env")
    r = subprocess.run([server, "-c", "import httpx"], cwd=str(T), capture_output=True, text=True, timeout=120)
    check("setup: the services run with the `server` extra's packages and not the tests group's (httpx, which only that group names, is not there)", r.returncode != 0 and "No module named 'httpx'" in r.stderr, (r.returncode, r.stderr[-300:]))
    procs = {MAIN: build_board(MAIN, main_port, ALICE_ALT, f"http://127.0.0.1:{ca_port}" if caddy else None), SIDE: build_board(SIDE, side_port, BOB_SIDE, f"http://127.0.0.1:{cb_port}" if caddy else None)}
    URL.update({MAIN: f"http://127.0.0.1:{main_port}/mcp", SIDE: f"http://127.0.0.1:{side_port}/mcp", "door": f"http://127.0.0.1:{door_port}/mcp",
                "verify-main": f"http://127.0.0.1:{main_port}/frontdoor/verify", "verify-side": f"http://127.0.0.1:{side_port}/frontdoor/verify"})
    for board, port, bport in ((MAIN, sa_port, main_port), (SIDE, sb_port, side_port)):
        procs["signin-" + board] = build_signin(board, port, bport, server)
        URL["signin-" + board] = f"http://127.0.0.1:{port}/verify"; URL["signin-health-" + board] = f"http://127.0.0.1:{port}/healthz"
    write_secret(T / "door/identity.key", SECRET)
    rows = "".join(f'\n[[frontdoor.backends]]\nname = "{n}"\nurl = "{URL[n]}"\ntoken_file = "{write_secret(T / "door" / (n + ".token"), BEARER[n])}"\n' for n in (MAIN, SIDE))
    (T / "door/stackshot.toml").write_text(f'[frontdoor]\nlisten_port = {door_port}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{T}/door/identity.key"\n'
                                           f'members_file = "{MEMBERS_FILE}"\n{rows}')
    procs["door"] = Proc("door", [sys.executable, "-m", "stackshot.frontdoor"], own_env(T / "door", STACKSHOT_CONFIG=str(T / "door/stackshot.toml")), T / "door", door_port, up_status=(200, 503))
    stand_ins = {}
    if caddy:
        root = T / "caddy"; root.mkdir()
        stand_ins.update({n: Recorder(n) for n in ("board", "door", "auth")})
        sites = (site(ca_port, sa_port, door_port, main_port), site(cb_port, sb_port, door_port, side_port),
                 site(rc_port, sa_port, stand_ins["door"].port, stand_ins["board"].port), site(nc_port, stand_ins["auth"].port, stand_ins["door"].port, stand_ins["board"].port))
        (root / "Caddyfile").write_text("{\n\tadmin off\n\tauto_https off\n}\n" + "".join(sites))
        print("note: " + subprocess.run([caddy, "version"], capture_output=True, text=True, timeout=60).stdout.strip(), flush=True)
        env = own_env(root, XDG_CONFIG_HOME=str(root / "home/config"), XDG_DATA_HOME=str(root / "home/data"))
        procs["caddy"] = Proc("caddy", [caddy, "run", "--config", str(root / "Caddyfile"), "--adapter", "caddyfile"], env, root, ca_port, up_path="/caddy-up", up_status=(200, 401))      # 401 too: a block whose lines run out of order asks the check first, and what a caller then gets is checked below
        URL.update({"caddy-main": f"http://127.0.0.1:{ca_port}/mcp", "caddy-side": f"http://127.0.0.1:{cb_port}/mcp"})
    PROCS.extend(procs.values())
    try:
        for p in PROCS:
            check(f"setup: {p.name} starts on its own port", p.start(), p.tail())
        if fails:
            return
        r = subprocess.run([*procs["signin-main"].argv, "--check"], env=procs["signin-main"].env, cwd=str(ROOT["signin-main"]), capture_output=True, text=True, timeout=120)
        check("setup: the service's own check names the board it asks and no secret", r.returncode == 0 and f":{main_port}/frontdoor/verify" in r.stdout and VERIFY[MAIN] not in r.stdout + r.stderr, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        secret_checks(procs)
        played_proxy_checks()
        refusal_checks()
        member_checks()
        outage_checks(procs)
        machine_token_checks(procs, caddy)
        if caddy:
            caddy_checks(procs)
            discovery_checks(ca_port, main_port)
            block_checks(rc_port, stand_ins["board"], stand_ins["door"])
            no_identity_checks(nc_port, stand_ins["door"])
        else:
            skipped.append("the real Caddy checks (no caddy on this machine's PATH)")
        log_checks(procs, query_checks(caddy))
        www = board_check(MAIN)[1].get("www-authenticate")
        print(f"note: the board's own token check answers a request with no bearer with WWW-Authenticate: {www!r}", flush=True)
        check("end: nothing the run did made a process stop by itself", all(p.running() for p in PROCS), [(p.name, p.p.poll(), p.tail()) for p in PROCS if not p.running()])
    finally:
        for p in PROCS:
            p.stop()
        for r in stand_ins.values():
            r.stop()
    check("end: every process has ended and every port is free", all(not p.running() and port_free(p.port) for p in PROCS), [p.port for p in PROCS if not port_free(p.port)])


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:      # noqa: BLE001  (a crash is a failed run that says where, never a silent exit)
        import traceback; traceback.print_exc()
        fails.append(f"crash: the run stopped with {type(e).__name__}")
        for p in PROCS:
            p.stop()
    if fails and not os.environ.get("KEEP_SCRATCH"):
        for p in PROCS:
            if p.tail().strip():
                print(f"--- {p.name} log tail ---\n{p.tail()}", flush=True)
    for s in skipped:
        print(f"skipped: {s}", flush=True)
    print(("ok" if not fails else "FAILED") + f": front door sign-in run scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "") + (f", {len(skipped)} part skipped" if skipped else ""), flush=True)
    sys.exit(1 if fails else 0)
