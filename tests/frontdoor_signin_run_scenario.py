"""tests/frontdoor_signin_run_scenario.py: the whole sign-in path with real processes: a caller's bearer token, the sign-in service, the board that checks it, the front door, and the
board that records who called; with a real Caddy as the reverse proxy when this machine has one.

Hermetic: nothing but this machine's loopback. Under one scratch folder (tests/_scratch.py: locked while the suite runs, removed when it ends, pass or fail) it makes
  * two boards, `main` and `side`, each its own process (`stackshot/web/server.py`) with its own config, store, port, sign-in (Google, a made-up client; its machine token is the
    caller's bearer here, and `[auth] portal_identity` is the address the token stands for), its copy of the signing secret and of the check's secret, and a `[behind_frontdoor]`
    table that checks the signed identity, reads the members file and answers the token check;
  * one front door (`python -m stackshot.frontdoor`) in front of both;
  * two sign-in services (`python -m stackshot.frontdoor.signin`), one asking each board (a token is a board's own, so each service knows one caller);
  * when `caddy` is on the PATH, one Caddy with a site per service: `forward_auth` to the service, `copy_headers X-Verified-User>X-Forwarded-User`, then the front door. Without it the
    Caddy checks are skipped and the summary says so.
Every port is a free one chosen at run time on 127.0.0.1, every process has a HOME and a TMPDIR of its own inside the scratch folder, a child asks the kernel to end it with this
process (so a killed suite leaves none) and is stopped by its PID. Without Caddy the test plays the reverse proxy: it asks the service as Caddy does and sends the front door the
identity the service answered with.

Proves: the address a board names (its second address, in another case) becomes the member's key, and the boards record that key; each caller reaches her own boards; a bearer the
board refuses is 401 with whatever WWW-Authenticate the board's own check answers with, and one no member holds goes on to the door, which says so; an address that is written as a
member's key and is not among that member's sign-in addresses is 403 although the door would take it; the service does not start on a verify secret that is the identity secret; a board that is down, a secret that
differs and a service that is down are never a 200 and (the first two) never a 401; each part serves again after a restart or a rotation with no other restart; no token, secret or
address is in a service's log; through Caddy, a header the client sends itself never becomes the caller, and nothing reaches the front door that the service did not accept.

    tests/run-suite frontdoor_signin_run        -> exit 0 / 1"""
import asyncio, itertools, json, os, pathlib, re, secrets, shutil, signal, socket, subprocess, sys, time, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance
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


def build_board(label, port, identity):
    """One board's instance on a folder of its own; → the Proc. `identity` is the address its machine token stands for."""
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


def build_signin(board, port, board_port):
    root = T / f"signin-{board}"; root.mkdir()
    write_secret(root / "verify.key", VERIFY[board])
    (root / "stackshot.toml").write_text(f'[frontdoor_signin]\nlisten_port = {port}\nboard_verify_url = "http://127.0.0.1:{board_port}/frontdoor/verify"\n'
                                         f'verify_secret_file = "{root}/verify.key"\nmembers_file = "{MEMBERS_FILE}"\nidentity_secret_file = "{T}/door/identity.key"\ncache_seconds = 1\ntimeout_seconds = 5\n')
    ROOT["signin-" + board] = root
    return Proc("signin-" + board, [sys.executable, "-m", "stackshot.frontdoor.signin"], own_env(root, STACKSHOT_CONFIG=str(root / "stackshot.toml")), root, port)


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
                r = subprocess.run([sys.executable, "-m", "stackshot.frontdoor.signin", *args], env=env, cwd=str(root), capture_output=True, text=True, timeout=60, preexec_fn=_die_with_parent)
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


def query_checks(caddy):
    """A query string on a request, which the proxy's check keeps from the caller's own: it is read by nothing and written nowhere. → the marker it carried."""
    marker = "query-" + secrets.token_urlsafe(18)
    query = f"?access_token={marker}&login_hint={ALICE}"
    st, hd, _ = raw(URL["signin-" + MAIN] + query, {"Authorization": "Bearer " + BEARER[MAIN]})
    check("service: a query string changes nothing: the answer is the bearer's", st == 200 and hd.get("x-verified-user") == ALICE, (st, hd))
    if caddy:
        st, _, _ = raw(URL["caddy-" + MAIN] + query, {}, method="POST")
        check("caddy: a token in the query string is not a credential: 401", st == 401, st)
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
    ports = free_ports(7)
    door_port, main_port, side_port, sa_port, sb_port, ca_port, cb_port = ports
    check("setup: distinct free loopback ports, none a well-known one of an instance", len(set(ports)) == len(ports) and all(p > 1024 and p not in (8010, 8020, 8021) for p in ports))
    (T / "door").mkdir(); write_members(MEMBERS)
    procs = {MAIN: build_board(MAIN, main_port, ALICE_ALT), SIDE: build_board(SIDE, side_port, BOB_SIDE)}
    URL.update({MAIN: f"http://127.0.0.1:{main_port}/mcp", SIDE: f"http://127.0.0.1:{side_port}/mcp", "door": f"http://127.0.0.1:{door_port}/mcp",
                "verify-main": f"http://127.0.0.1:{main_port}/frontdoor/verify", "verify-side": f"http://127.0.0.1:{side_port}/frontdoor/verify"})
    for board, port, bport in ((MAIN, sa_port, main_port), (SIDE, sb_port, side_port)):
        procs["signin-" + board] = build_signin(board, port, bport)
        URL["signin-" + board] = f"http://127.0.0.1:{port}/verify"; URL["signin-health-" + board] = f"http://127.0.0.1:{port}/healthz"
    write_secret(T / "door/identity.key", SECRET)
    rows = "".join(f'\n[[frontdoor.backends]]\nname = "{n}"\nurl = "{URL[n]}"\ntoken_file = "{write_secret(T / "door" / (n + ".token"), BEARER[n])}"\n' for n in (MAIN, SIDE))
    (T / "door/stackshot.toml").write_text(f'[frontdoor]\nlisten_port = {door_port}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{T}/door/identity.key"\n'
                                           f'members_file = "{MEMBERS_FILE}"\n{rows}')
    procs["door"] = Proc("door", [sys.executable, "-m", "stackshot.frontdoor"], own_env(T / "door", STACKSHOT_CONFIG=str(T / "door/stackshot.toml")), T / "door", door_port, up_status=(200, 503))
    if caddy:
        root = T / "caddy"; root.mkdir()
        site = lambda port, sport: (f"http://127.0.0.1:{port} {{\n\tbind 127.0.0.1\n\thandle /caddy-up {{\n\t\trespond \"up\" 200\n\t}}\n\thandle {{\n\t\tforward_auth 127.0.0.1:{sport} {{\n"
                                    f"\t\t\turi /verify\n\t\t\tcopy_headers X-Verified-User>X-Forwarded-User\n\t\t}}\n\t\treverse_proxy 127.0.0.1:{door_port}\n\t}}\n}}\n")
        (root / "Caddyfile").write_text("{\n\tadmin off\n\tauto_https off\n}\n" + site(ca_port, sa_port) + site(cb_port, sb_port))
        env = own_env(root, XDG_CONFIG_HOME=str(root / "home/config"), XDG_DATA_HOME=str(root / "home/data"))
        procs["caddy"] = Proc("caddy", [caddy, "run", "--config", str(root / "Caddyfile"), "--adapter", "caddyfile"], env, root, ca_port, up_path="/caddy-up")
        URL.update({"caddy-main": f"http://127.0.0.1:{ca_port}/mcp", "caddy-side": f"http://127.0.0.1:{cb_port}/mcp"})
    PROCS.extend(procs.values())
    try:
        for p in PROCS:
            check(f"setup: {p.name} starts on its own port", p.start(), p.tail())
        if fails:
            return
        r = subprocess.run([sys.executable, "-m", "stackshot.frontdoor.signin", "--check"], env=procs["signin-main"].env, cwd=str(ROOT["signin-main"]), capture_output=True, text=True, timeout=120)
        check("setup: the service's own check names the board it asks and no secret", r.returncode == 0 and f":{main_port}/frontdoor/verify" in r.stdout and VERIFY[MAIN] not in r.stdout + r.stderr, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        secret_checks(procs)
        played_proxy_checks()
        refusal_checks()
        member_checks()
        outage_checks(procs)
        if caddy:
            caddy_checks(procs)
        else:
            skipped.append("the real Caddy checks (no caddy on this machine's PATH)")
        log_checks(procs, query_checks(caddy))
        www = board_check(MAIN)[1].get("www-authenticate")
        print(f"note: the board's own token check answers a request with no bearer with WWW-Authenticate: {www!r}", flush=True)
        check("end: nothing the run did made a process stop by itself", all(p.running() for p in PROCS), [(p.name, p.p.poll(), p.tail()) for p in PROCS if not p.running()])
    finally:
        for p in PROCS:
            p.stop()
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
