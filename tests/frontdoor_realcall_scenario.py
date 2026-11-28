"""Scenario test for what keeps a front door working across a release: the real-call check (stackshot/frontdoor/check.py), deploy.sh's restarts of the front
door's units and its use of that check, and the command that copies the board's machine token into the front door's token file (stackshot/frontdoor/boardtoken.py).

Real processes on loopback ports in a temp folder: one board (stackshot/web/server.py), the front door and the sign-in service (with the environment the
`server` extra installs, which is also what the check runs in), and the splitter: a stand-in proxy that routes as the rendered Caddyfile does, and, with a
`caddy` on PATH, the rendered Caddyfile in it too. systemctl is a stub; deploy.sh runs for real in a throwaway checkout of a throwaway origin, with systemctl,
uv, curl and install.sh stubbed. Nothing of an installed instance is read.

Covers: every part passes with a real tool call; with the board down each fails although the front door still answers an initialize; a token the board does not
know, a token check refused by design (accept_portal_token off) and arguments or a config that allow no check; no secret in any output; --installed takes the
units that are turned on and --wait waits for them; the token is not sent over plain http to another machine and no proxy of the environment is used.
deploy.sh: which units a change restarts, the front door restarted with the board only where it is turned on, a running splitter only for its own files, the
check run after the health check and its failure failing the deploy. The token command: writes the file in one step, readable by its owner only, says
unchanged, --check, the older name, every refusal, never a value in its output; after a new token and a board restart the front door's calls pass again with no
restart of its own.

    tests/run-suite frontdoor_realcall     → exit 0 / 1"""
import http.client, http.server, json, os, pathlib, re, secrets, shlex, shutil, signal, socket, stat, subprocess, sys, threading, time, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch, _instance, _server_env

T = pathlib.Path(_scratch.mkdtemp(prefix="frontcall-"))
fails, ran, skipped = [], [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

ALICE = "alice@example.invalid"
IDENTITY, VERIFY = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
TOKEN, NEW_TOKEN, WRONG = secrets.token_urlsafe(36), secrets.token_urlsafe(36), secrets.token_urlsafe(36)
SECRETS = (IDENTITY, VERIFY, TOKEN, NEW_TOKEN, WRONG)
OUTPUTS = []          # everything any command of the run printed: no secret may be in it


# ---------------------------------------------------------------- files and processes
def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: f.write(value + "\n")
    os.chmod(path, 0o600); return str(path)

def free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks: s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks: s.close()

INIT = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
def raw(url, headers=None, method="GET"):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    req = urllib.request.Request(url, data=INIT if method == "POST" else None, headers=h, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except (urllib.error.URLError, OSError): return 0

def _die_with_parent():
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)       # PR_SET_PDEATHSIG
    except Exception:       # noqa: BLE001
        pass

PROCS = []
class Proc:
    """One server process: start it, wait until it answers, stop it by its PID."""
    def __init__(self, name, argv, env, cwd, port, up=(200,)):
        self.name, self.argv, self.env, self.cwd, self.port, self.up, self.p = name, argv, env, str(cwd), port, up, None
        self.err = T / f"{name}.err"; PROCS.append(self)
    def start(self, timeout=150):
        with open(self.err, "ab") as err:
            self.p = subprocess.Popen(self.argv, env=self.env, cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=err, stderr=err, preexec_fn=_die_with_parent)
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None: return False
            if raw(f"http://127.0.0.1:{self.port}/healthz") in self.up: return True
            time.sleep(0.2)
        return False
    def stop(self):
        if self.p is None or self.p.poll() is not None: return
        self.p.terminate()
        try: self.p.wait(25)
        except subprocess.TimeoutExpired: self.p.kill(); self.p.wait(15)
    def tail(self):
        try: return self.err.read_text(errors="replace")[-900:]
        except OSError: return ""

def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith(("STACKSHOT_", "BOARD_MCP_", "XDG_", "COVERAGE_")) and not k.lower().endswith("_proxy") or k in ("STACKSHOT_XLOCK_STRICT", "COVERAGE_PROCESS_START", "COVERAGE_FILE")}

(T / "home").mkdir(); (T / "tmp").mkdir()
def own_env(**more): return {**clean_env(), "PYTHONPATH": STACK, "HOME": str(T / "home"), "TMPDIR": str(T / "tmp"), **more}


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):          # a client that hangs up mid-connection is not a finding; anything else is printed
        if not isinstance(sys.exc_info()[1], ConnectionError): super().handle_error(request, client_address)


class StandIn:
    """A proxy that routes as units/stackshot-splitter.Caddyfile.in does: the client's identity headers dropped, /frontdoor* 404, the MCP path checked by the
    sign-in service and sent to the front door with the checked identity, everything else to the board."""
    def __init__(self, port, board, door, signin, identity="x-forwarded-user"):
        drop = {identity, "x-forwarded-user", "x-verified-user", "x-stackshot-identity", "x-stackshot-verify"}
        hop = {"connection", "keep-alive", "transfer-encoding", "content-length", "host", "te", "upgrade", "trailer", "proxy-authorization", "proxy-authenticate"}
        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def say(self, code, headers=(), body=b""):
                self.send_response(code)
                for k, v in headers: self.send_header(k, v)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def to(self, where, method, path, headers, body):
                c = http.client.HTTPConnection("127.0.0.1", where, timeout=30)
                try:
                    c.request(method, path, body=body, headers=headers)
                    r = c.getresponse()
                    return r.status, [(k, v) for k, v in r.getheaders() if k.lower() not in hop | {"date", "server"}], r.read()
                except OSError:
                    return 502, [], b""
                finally:
                    c.close()
            def do_any(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
                path = self.path.split("?")[0]
                headers = {k: v for k, v in self.headers.items() if k.lower() not in drop | hop}
                if path == "/frontdoor" or path.startswith("/frontdoor/"): return self.say(404)
                if path == "/mcp" or path.startswith("/mcp/"):
                    code, got, text = self.to(signin, "GET", "/verify", headers, None)
                    if not 200 <= code < 300: return self.say(code, got, text)
                    if self.command == "GET": return self.say(405)      # no stream of server messages through the stand-in
                    headers[identity] = dict((k.lower(), v) for k, v in got).get("x-verified-user", "")
                    return self.say(*self.to(door, self.command, self.path, headers, body))
                return self.say(*self.to(board, self.command, self.path, headers, body))
            do_GET = do_POST = do_DELETE = do_PUT = do_any
        self.port = port
        self.srv = Server(("127.0.0.1", port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def stop(self): self.srv.shutdown(); self.srv.server_close()


# ---------------------------------------------------------------- one instance: board, front door, sign-in service, splitter, all from one config
bport, dport, sport, lport, soff_port, loff_port, caddy_port, dead_port, echo_port, echo_split_port = free_ports(10)
ROOT = T / "instance"
for d in ("store/a", "state", "secrets", "touch", "brain/projects", "fleet/a"): (ROOT / d).mkdir(parents=True)
MEMBERS = ROOT / "members.json"; MEMBERS.write_text(json.dumps({ALICE: {"boards": ["main"], "emails": [ALICE]}}))
write_private(ROOT / "identity.key", IDENTITY); write_private(ROOT / "verify.key", VERIFY)
OAUTH = ROOT / "secrets/oauth.env"
def oauth(token, name="STACKSHOT_PORTAL_TOKEN"):
    write_private(OAUTH, f"STACKSHOT_GOOGLE_CLIENT_ID=client.example.invalid\nSTACKSHOT_GOOGLE_CLIENT_SECRET=made-up-value\n{name}={token}")
oauth(TOKEN)
TOKEN_FILE = ROOT / "door/main.token"

def board_toml():
    toml = _instance.base_toml()
    toml = re.sub(r'(?m)^process = "inline"', 'process = "unit"', toml, count=1)
    toml = re.sub(r'(?m)^session_links = ".*"', 'session_links = ""', toml, count=1); assert 'session_links = ""' in toml
    for key, val in (("repo", ROOT), ("store", ROOT / "store"), ("markdown", ROOT / "board.md"), ("brain", ROOT / "brain"), ("state", ROOT / "state"), ("secrets", ROOT / "secrets"),
                     ("project_touch", ROOT / "touch"), ("fleet_names", ROOT / "names.tsv"), ("rules", ROOT / "RULES.md"), ("claude_credentials", ROOT / "none.json")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"'), (r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"),
                     (r"(?m)^port = 8020", f"port = {bport}"), (r"(?m)^every_minutes = 10", "every_minutes = 1440"), (r"(?m)^panel = true", "panel = false"),
                     (r'(?m)^portal_identity = ""', f'portal_identity = "{ALICE}"')):
        toml, n = re.subn(pat, rep, toml, count=1); assert n == 1, pat
    return toml
BOARD_TOML = board_toml()
def config(name, signin=sport, splitter=lport, accept=True, door=True, extra="", backend_url=None, behind=True, signin_table=True, splitter_table=True):
    """The instance's one config file, as the board, the front door, the sign-in service, the check and the token command all read it."""
    t = BOARD_TOML
    if behind: t += f'\n[behind_frontdoor]\nidentity_secret_file = "{ROOT}/identity.key"\nmembers_file = "{MEMBERS}"\nboard_name = "main"\nverify_secret_file = "{ROOT}/verify.key"\n'
    if door: t += (f'\n[frontdoor]\nlisten_port = {dport}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{ROOT}/identity.key"\nmembers_file = "{MEMBERS}"\n'
                   f'\n[[frontdoor.backends]]\nname = "main"\nurl = "{backend_url or f"http://127.0.0.1:{bport}/mcp"}"\ntoken_file = "{TOKEN_FILE}"\n')
    if signin_table: t += (f'\n[frontdoor_signin]\nlisten_port = {signin}\nboard_verify_url = "http://127.0.0.1:{bport}/frontdoor/verify"\nverify_secret_file = "{ROOT}/verify.key"\n'
                           f'cache_seconds = 0\ntimeout_seconds = 5\naccept_portal_token = {"true" if accept else "false"}\n')
    if splitter_table: t += f'\n[frontdoor_splitter]\nlisten_port = {splitter}\ncaddy = "{shutil.which("caddy") or "/usr/bin/caddy"}"\n'
    p = ROOT / name; p.write_text(t + extra, encoding="utf-8"); return str(p)
(ROOT / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(ROOT / "fleet/a/sessions.json").write_text("{}"); (ROOT / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(ROOT / "store/next-id").write_text("10"); (ROOT / "store/anchors.json").write_text("{}")
(ROOT / "store/projects.json").write_text(json.dumps({"pages": {}}))
CFG = config("stackshot.toml")
CFG_OFF = config("signin-off.toml", signin=soff_port, splitter=loff_port, accept=False)

# the token command, run with the system's python3 (it needs no extra), as a person would after a new token
SYSPY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
def boardtoken(*args, cfg=CFG, argv=None, env=None):
    r = subprocess.run(argv or [SYSPY, "-m", "stackshot.frontdoor.boardtoken", *args], cwd=STACK, env={**own_env(STACKSHOT_CONFIG=cfg), **(env or {})}, capture_output=True, text=True, timeout=60)
    OUTPUTS.append(r.stdout + r.stderr); return r

# ---------------------------------------------------------------- the token command, part 1: the first copy
r = boardtoken("--check")
check("token --check, no file yet: exit 1 and the reason", r.returncode == 1 and "board main:" in r.stdout and str(TOKEN_FILE) in r.stdout, (r.returncode, r.stdout, r.stderr[-600:]))
check("token --check writes nothing", not TOKEN_FILE.exists() and not TOKEN_FILE.parent.exists())
r = subprocess.run(["sh", "-c", 'umask 000; exec "$@"', "sh", SYSPY, "-m", "stackshot.frontdoor.boardtoken"], cwd=STACK, env=own_env(STACKSHOT_CONFIG=CFG), capture_output=True, text=True, timeout=60)
OUTPUTS.append(r.stdout + r.stderr)
check("token: writes the front door's token file for this machine's own board, with no --board", r.returncode == 0 and "board main: wrote the board's machine token of" in r.stdout and TOKEN_FILE.read_text() == TOKEN + "\n",
      (r.returncode, r.stdout, r.stderr[-600:]))
check("token: the new file is readable by its owner only, whatever the umask", stat.S_IMODE(TOKEN_FILE.stat().st_mode) == 0o600 and stat.S_IMODE(TOKEN_FILE.parent.stat().st_mode) & 0o077 == 0,
      (oct(TOKEN_FILE.stat().st_mode), oct(TOKEN_FILE.parent.stat().st_mode)))
check("token: no temporary file is left beside it", sorted(p.name for p in TOKEN_FILE.parent.iterdir()) == ["main.token"], sorted(p.name for p in TOKEN_FILE.parent.iterdir()))
ino = TOKEN_FILE.stat().st_ino
r = boardtoken("--board", "main")
check("token again: unchanged, the file not rewritten", r.returncode == 0 and "unchanged" in r.stdout and TOKEN_FILE.stat().st_ino == ino, (r.returncode, r.stdout, r.stderr[-300:]))
r = boardtoken("--check")
check("token --check after the copy: exit 0", r.returncode == 0 and "holds the board's machine token" in r.stdout, (r.returncode, r.stdout))

# ---------------------------------------------------------------- start the instance
server = _server_env.python(STACK, T / "server-env")
board = Proc("board", [sys.executable, os.path.join(STACK, "stackshot/web/server.py")], own_env(STACKSHOT_CONFIG=CFG, STACKSHOT_FLEET_DIR=str(ROOT / "fleet"), STACKSHOT_AUTH="google"), ROOT, bport)
door = Proc("door", [server, "-m", "stackshot.frontdoor"], own_env(STACKSHOT_CONFIG=CFG), T / "tmp", dport, up=(200, 503))
signin = Proc("signin", [server, "-m", "stackshot.frontdoor.signin"], own_env(STACKSHOT_CONFIG=CFG), T / "tmp", sport)
signin_off = Proc("signin-off", [server, "-m", "stackshot.frontdoor.signin"], own_env(STACKSHOT_CONFIG=CFG_OFF), T / "tmp", soff_port)
# systemctl for --installed: enabled/<unit> and active/<unit> hold the answers; no-manager = no user manager
UNITS = T / "unitstate"; (UNITS / "enabled").mkdir(parents=True); (UNITS / "active").mkdir()
(T / "bin").mkdir()
(T / "bin/systemctl").write_text(f'''#!/bin/sh
u=""; for a; do u="$a"; done
case "$*" in
  *show-environment*) [ ! -f {UNITS}/no-manager ] || exit 1; exit 0 ;;
  *is-enabled*) if [ -f {UNITS}/enabled/$u ]; then cat {UNITS}/enabled/$u; exit 0; fi; echo disabled; exit 1 ;;
  *is-active*) if [ -f {UNITS}/active/$u ]; then cat {UNITS}/active/$u; exit 0; fi; echo inactive; exit 3 ;;
esac
exit 0
'''); (T / "bin/systemctl").chmod(0o755)
def turned_on(enabled=(), active=(), failed=()):
    for d in ("enabled", "active"):
        for p in (UNITS / d).iterdir(): p.unlink()
    (UNITS / "no-manager").unlink(missing_ok=True)
    for u in enabled: (UNITS / "enabled" / f"stackshot-{u}.service").write_text("enabled\n")
    for u in active: (UNITS / "active" / f"stackshot-{u}.service").write_text("active\n")
    for u in failed: (UNITS / "active" / f"stackshot-{u}.service").write_text("failed\n")

def check_argv(*args): return [server, "-m", "stackshot.frontdoor.check", *args]
def check_env(cfg=CFG, **more): return own_env(STACKSHOT_CONFIG=cfg, PATH=f"{T}/bin:" + os.environ.get("PATH", ""), **more)
def run(*args, cfg=CFG, **env):
    r = subprocess.run(check_argv(*args), cwd=STACK, env=check_env(cfg, **env), capture_output=True, text=True, timeout=240)
    OUTPUTS.append(r.stdout + r.stderr); return r.returncode, r.stdout + r.stderr
def last(out): return out.strip().splitlines()[-1] if out.strip() else ""
D, S, L = f"http://127.0.0.1:{dport}", f"http://127.0.0.1:{sport}", f"http://127.0.0.1:{lport}"
splitters = []

try:
    for p in (board, door, signin, signin_off):
        check(f"setup: {p.name} starts", p.start(), p.tail())
    splitters.append(StandIn(lport, bport, dport, sport)); splitters.append(StandIn(loff_port, bport, dport, soff_port))
    if fails: raise SystemExit

    # a start says where its time went: one line before the app serves
    m = re.search(r"(?m)^start timing: (\d+\.\d) s before serving: (.+)$", board.err.read_text(errors="replace"))
    check("the board's start prints one timing line with its total and its laps", m is not None and float(m.group(1)) > 0, board.tail())

    # ------------------------------------------------------------ each part by address
    rc, out = run("--door", D)
    check("--door: a tool call on the board passes", rc == 0 and "ok: front door: tool call sessions answered on board main" in out and last(out) == "front door check: passed (front door)", (rc, out))
    rc, out = run("--door", D + "/mcp", "--board", "main", "--as", ALICE)
    check("--door with the MCP path, --board and --as: passes", rc == 0, (rc, out))
    rc, out = run("--door", D, "--as", "nobody@example.invalid")
    check("--door as someone who is no member: fails", rc == 1 and last(out).startswith("front door check: FAILED: front door: the tool call sessions on board main"), (rc, out))
    rc, out = run("--signin", S)
    check("--signin: health, a request with no token refused, the machine token accepted", rc == 0 and "the token check of board main's machine token answered 200" in out, (rc, out))
    rc, out = run("--splitter", L)
    check("--splitter: a tool call with the machine token goes through the check and the front door", rc == 0 and "tool call sessions answered on board main through the sign-in check and the front door" in out, (rc, out))
    rc, out = run("--door", D, "--signin", S, "--splitter", L + "/mcp")
    check("all three by address", rc == 0 and last(out) == "front door check: passed (sign-in service, front door, splitter)", (rc, out))
    rc, out = run("--splitter", L, HTTP_PROXY=f"http://127.0.0.1:{dead_port}", http_proxy=f"http://127.0.0.1:{dead_port}", ALL_PROXY=f"http://127.0.0.1:{dead_port}", NO_PROXY="")
    check("a proxy in the environment is not used", rc == 0, (rc, out))

    # --door with several boards calls each one: a second board the running front door does not serve
    TWO = ROOT / "two-members.json"; TWO.write_text(json.dumps({ALICE: {"boards": ["main", "second"], "emails": [ALICE]}}))
    two = pathlib.Path(config("two-boards.toml", extra=f'\n[[frontdoor.backends]]\nname = "second"\nurl = "http://127.0.0.1:{bport}/mcp"\ntoken_file = "{TOKEN_FILE}"\n'))
    two.write_text(two.read_text().replace(f'members_file = "{MEMBERS}"', f'members_file = "{TWO}"'))
    rc, out = run("--door", D, cfg=str(two))
    check("--door with two boards neither of which is the only own one: the second is called too, and its refusal fails the check",
          rc == 1 and "the tool call sessions on board second" in out, (rc, out))

    # a server behind the splitter whose error quotes the request back: the token is cut out of what the check prints
    (T / "echo.py").write_text("""import sys
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
mcp = FastMCP("echo")
@mcp.tool
def sessions(board: str = "") -> str:
    raise ToolError("refused: you sent " + get_http_headers(include_all=True).get("authorization", "nothing"))
mcp.run(transport="http", host="127.0.0.1", port=int(sys.argv[1]), show_banner=False)
""")
    echo = Proc("echo", [server, str(T / "echo.py"), str(echo_port)], own_env(), T / "tmp", echo_port, up=(404,))
    check("setup: the quoting server starts", echo.start(), echo.tail())
    splitters.append(StandIn(echo_split_port, bport, echo_port, sport))
    rc, out = run("--splitter", f"http://127.0.0.1:{echo_split_port}")
    check("an error that quotes the request: fails, with the token cut out of it", rc == 1 and "was answered with an error: refused: you sent Bearer [token]" in out and TOKEN not in out, (rc, out))
    echo.stop()

    # a splitter that lets things through is caught
    class Open(http.server.BaseHTTPRequestHandler):
        answers = {}
        def log_message(self, *a): pass
        def do_any(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            code = self.answers.get(self.path, 200)
            self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
        do_GET = do_POST = do_any
    srv = Server(("127.0.0.1", 0), Open); threading.Thread(target=srv.serve_forever, daemon=True).start()
    O = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        rc, out = run("--splitter", O)
        check("a splitter that answers a call carrying only the identity header: fails", rc == 1 and "carries the identity header and no token was answered 200, not 401" in out, (rc, out))
        Open.answers = {"/mcp": 401}
        rc, out = run("--splitter", O)
        check("a splitter that passes the board's token check path on: fails", rc == 1 and "/frontdoor/verify was answered 200, not 404" in out, (rc, out))
        Open.answers = {"/mcp": 401, "/frontdoor/verify": 404}
        rc, out = run("--splitter", O)
        check("a splitter that routes as set but answers no tool call: fails", rc == 1 and "the tool call sessions on board main did not get through" in out, (rc, out))
        Open.answers = {}
        rc, out = run("--signin", O)
        check("a sign-in service that accepts a request with no token: fails", rc == 1 and "a token check that carries no token was answered 200, not 401" in out, (rc, out))
        rc, out = run("--door", O)
        check("a front door that answers 200 and no tool call: fails", rc == 1 and "did not get through" in out, (rc, out))
    finally:
        srv.shutdown(); srv.server_close()

    # ------------------------------------------------------------ accept_portal_token off
    rc, out = run("--signin", f"http://127.0.0.1:{soff_port}", cfg=CFG_OFF)
    check("accept_portal_token off, --signin: 403 is what is wanted", rc == 0 and "answered 403 (refused as set: accept_portal_token is off)" in out, (rc, out))
    rc, out = run("--splitter", f"http://127.0.0.1:{loff_port}", cfg=CFG_OFF)
    check("accept_portal_token off, --splitter: fails, since no tool call can be made", rc == 1 and "no tool call can be made through the splitter" in out, (rc, out))
    turned_on(enabled=("frontdoor", "signin", "splitter"))
    rc, out = run("--installed", cfg=CFG_OFF)
    check("accept_portal_token off, --installed: the splitter's routes pass and the missing tool call is said", rc == 0 and "no tool call can be made through the splitter" in out and "the 403 came through" in out, (rc, out))
    rc, out = run("--splitter", L, cfg=CFG_OFF)
    check("a config that says off against a service that accepts: fails", rc == 1, (rc, out))
    rc, out = run("--signin", f"http://127.0.0.1:{soff_port}")
    check("a config that says on against a service that refuses: fails, with both numbers", rc == 1 and "was answered 403, not 200" in out, (rc, out))

    # ------------------------------------------------------------ --installed
    turned_on()
    rc, out = run("--installed")
    check("--installed, no unit turned on: nothing to check, exit 0", rc == 0 and "nothing to check: no front door unit is enabled or running" in out, (rc, out))
    turned_on(enabled=("frontdoor", "signin"), active=("splitter",))
    rc, out = run("--installed")
    check("--installed: every part that is enabled or running is checked", rc == 0 and last(out) == "front door check: passed (sign-in service, front door, splitter)", (rc, out))
    turned_on(active=("frontdoor",))
    rc, out = run("--installed")
    check("--installed: only what is turned on", rc == 0 and last(out) == "front door check: passed (front door)", (rc, out))
    turned_on(enabled=("frontdoor",)); (UNITS / "no-manager").write_text("")
    rc, out = run("--installed")
    check("--installed without a user manager: fails, since which parts run is unknown", rc == 1 and "cannot reach the user manager" in out, (rc, out))
    turned_on(enabled=("frontdoor",))
    rc, out = run("--installed", cfg=config("no-door.toml", door=False))
    check("--installed with a unit on and no [frontdoor] table: fails and names the unit", rc == 1 and "stackshot-frontdoor.service turned on" in out and "no [frontdoor] table" in out, (rc, out))
    turned_on(enabled=("signin",))
    rc, out = run("--installed", cfg=config("no-signin.toml", signin_table=False))
    check("--installed with the sign-in unit on and no table: fails", rc == 1 and "the config has no [frontdoor_signin] table" in out, (rc, out))
    turned_on(active=("splitter",))
    rc, out = run("--installed", cfg=config("undone.toml", splitter=bport))
    check("--installed with a splitter running that the config no longer allows: fails and says to turn it off", rc == 1 and "the config allows no splitter" in out and "disable --now stackshot-splitter.service" in out, (rc, out))
    turned_on(active=("signin",))
    rc, out = run("--installed", cfg=config("no-behind.toml", behind=False))
    check("--installed, the config's board with no verify secret: the sign-in service's health only, and it says so", rc == 0 and "its token check was not tried" in out, (rc, out))

    # a failed unit: checked while it is enabled, left alone once it is not (`disable --now` leaves the failed state behind)
    turned_on(failed=("signin", "frontdoor", "splitter"))
    rc, out = run("--installed")
    check("--installed, every unit failed and none enabled: nothing to check, exit 0", rc == 0 and "nothing to check: no front door unit is enabled or running" in out, (rc, out))
    turned_on(enabled=("frontdoor",), failed=("signin",))
    rc, out = run("--installed", cfg=config("failed-off.toml", signin=dead_port))
    check("--installed: a failed unit that is not enabled is not checked beside one that is", rc == 0 and last(out) == "front door check: passed (front door)", (rc, out))
    turned_on(enabled=("signin",), failed=("signin",))
    rc, out = run("--installed", cfg=config("failed-on.toml", signin=dead_port))
    check("--installed: a failed unit that is enabled is checked, and fails the check", rc == 1 and last(out).startswith("front door check: FAILED: sign-in service: "), (rc, out))

    # no board can be told to be this machine's own: what needs no board's token is checked, and the line says what was not tried
    def two_boards(name, main=None, other="https://other.example.invalid/mcp", **kw):
        return config(name, backend_url=main, extra=f'\n[[frontdoor.backends]]\nname = "second"\nurl = "{other}"\ntoken_file = "{ROOT}/door/second.token"\n', **kw)
    far_two = two_boards("far-two.toml", main="https://board.example.invalid/mcp")
    own_two = two_boards("own-two.toml", other=f"http://127.0.0.1:{bport}/mcp")
    for label, cfg in (("two boards elsewhere", far_two), ("two boards on this machine's port", own_two)):
        turned_on(enabled=("signin", "splitter"))
        rc, out = run("--installed", cfg=cfg)
        check(f"--installed, {label}: passes, and both parts say the token was not tried and what would have it tried",
              rc == 0 and "ok: sign-in service: /healthz 200 and a request with no token refused; no board's machine token was tried: none of the [[frontdoor.backends]] boards can be told" in out
              and "ok: splitter: routes as set; no tool call was tried: none of the [[frontdoor.backends]] boards can be told" in out and "give exactly one of them a loopback url on [server] port" in out
              and "--board" not in out and last(out) == "front door check: passed (sign-in service, splitter)", (rc, out))
        for flag, url in (("--signin", S), ("--splitter", L)):
            rc, out = run(flag, url, cfg=cfg)
            check(f"{flag} by address, {label}: not checked, and --board is the remedy", rc == 2 and "name one with --board" in out, (rc, out))
    rc, out = run("--signin", S, cfg=config("one-elsewhere.toml", backend_url="https://board.example.invalid/mcp"))
    check("--signin, one board listed and not on this machine's port: it is the one meant", rc == 0 and "the token check of board main's machine token answered 200" in out, (rc, out))
    rc, out = run("--signin", S, "--board", "main", cfg=own_two)
    check("--signin by address with --board among several: that board's token is tried", rc == 0 and "the token check of board main's machine token answered 200" in out, (rc, out))
    turned_on(enabled=("signin",))
    rc, out = run("--installed", cfg=two_boards("one-own.toml"))
    check("--installed, one of two boards this machine's own: its token is tried", rc == 0 and "the token check of board main's machine token answered 200" in out, (rc, out))
    srv = Server(("127.0.0.1", 0), Open); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for label, part, answers, word in (("a splitter that lets the identity header through", "splitter", {}, "carries the identity header and no token was answered 200, not 401"),
                                           ("a splitter that passes the token check path on", "splitter", {"/mcp": 401}, "/frontdoor/verify was answered 200, not 404"),
                                           ("a sign-in service that accepts no token", "signin", {}, "a token check that carries no token was answered 200, not 401")):
            Open.answers = answers
            turned_on(enabled=(part,))
            rc, out = run("--installed", cfg=two_boards("untold-open.toml", main="https://board.example.invalid/mcp", **{part: srv.server_address[1]}))
            check(f"--installed, no board told apart: {label} still fails", rc == 1 and word in out, (rc, out))
        # a front door that serves no board
        brain = config("brain-only.toml", door=False, extra=f'\n[frontdoor]\nlisten_port = {srv.server_address[1]}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{ROOT}/identity.key"\n'
                       f'members_file = "{MEMBERS}"\n\n[[frontdoor.backends]]\nname = "notes"\nkind = "brain"\nurl = "https://notes.example.invalid/mcp"\ntoken_file = "{TOKEN_FILE}"\n')
        Open.answers = {}; turned_on(enabled=("frontdoor",))
        rc, out = run("--installed", cfg=brain)
        check("--installed, a front door with no board: its health route, and it says no tool call was tried", rc == 0 and "ok: front door: /healthz 200; no tool call was tried: no [[frontdoor.backends]] board is listed" in out, (rc, out))
        Open.answers = {"/healthz": 503}
        rc, out = run("--installed", cfg=brain)
        check("--installed, a front door with no board whose health route is not 200: fails", rc == 1 and "front door: /healthz answered 503, not 200" in out, (rc, out))
    finally:
        Open.answers = {}; srv.shutdown(); srv.server_close()

    # ------------------------------------------------------------ no check possible: exit 2
    for label, args, cfg, word in (
            ("no [frontdoor] table", ("--door", D), config("nodoor2.toml", door=False), "no [frontdoor] table"),
            ("an unknown board", ("--door", D, "--board", "elsewhere"), CFG, "no [[frontdoor.backends]] board is named 'elsewhere'"),
            ("an address that is no URL", ("--door", "127.0.0.1:1"), CFG, "an address is http(s)://host[:port]"),
            ("an address with a user name", ("--splitter", "http://u:p@127.0.0.1:1"), CFG, "an address is http(s)://host[:port]"),
            ("the token over plain http to another machine (splitter)", ("--splitter", "http://example.invalid:8020"), CFG, "not sent over plain http to example.invalid"),
            ("the token over plain http to another machine (sign-in)", ("--signin", "http://192.0.2.1:8031"), CFG, "not sent over plain http to 192.0.2.1")):
        rc, out = run(*args, cfg=cfg)
        check(f"not checked, exit 2: {label}", rc == 2 and "front door check: not checked: " in out and word in out, (rc, out))
    for args in ((), ("--installed", "--door", D), ("--installed", "--board", "main"), ("--signin", S, "--as", ALICE)):
        rc, out = run(*args)
        check(f"arguments {' '.join(args) or '(none)'}: refused, exit 2", rc == 2 and "usage:" in out, (rc, out))

    # ------------------------------------------------------------ a token the board does not know
    write_private(TOKEN_FILE, WRONG)
    rc, out = run("--signin", S)
    check("a wrong token in the token file, --signin: fails and says whose it is", rc == 1 and "was answered 401, not 200 (401: the board does not know the token in the front door's token file)" in out, (rc, out))
    rc, out = run("--splitter", L)
    check("a wrong token, --splitter: fails", rc == 1 and "did not get through" in out, (rc, out))
    rc, out = run("--door", D)
    check("a wrong token, --door: the call is answered with an error", rc == 1 and "FAILED: front door:" in out, (rc, out))
    TOKEN_FILE.unlink()
    rc, out = run("--signin", S)
    check("no token file: fails, naming it", rc == 1 and str(TOKEN_FILE) in out, (rc, out))
    boardtoken()

    # ------------------------------------------------------------ the board down
    board.stop()
    check("board down: the front door still answers an initialize, which is why a health route is not enough", raw(D + "/mcp", {"x-forwarded-user": ALICE}, "POST") == 200 and raw(D + "/healthz") in (200, 503),
          (raw(D + "/mcp", {"x-forwarded-user": ALICE}, "POST"), raw(D + "/healthz")))
    for flag, url, word in (("--door", D, "the tool call sessions on board main"), ("--signin", S, "not 401"), ("--splitter", L, "/healthz answered")):
        rc, out = run(flag, url)
        check(f"board down, {flag}: fails", rc == 1 and last(out).startswith("front door check: FAILED: ") and word in out, (rc, out))
    turned_on(enabled=("frontdoor", "signin", "splitter"))
    rc, out = run("--installed")
    check("board down, --installed: every part is tried and the last line names each failure", rc == 1 and all(f"{n}: " in last(out) for n in ("sign-in service", "front door", "splitter")), (rc, out))
    began = time.monotonic(); rc, out = run("--installed", "--wait", "5")
    check("--wait: gives up after the time given", rc == 1 and 5 <= time.monotonic() - began < 120, (rc, time.monotonic() - began, out[-300:]))

    # ------------------------------------------------------------ --wait: parts that come up while it waits
    waiting = subprocess.Popen(check_argv("--installed", "--wait", "120"), cwd=STACK, env=check_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(4)
        check("--wait: still waiting while the board is down", waiting.poll() is None, waiting.poll())
        check("setup: the board starts again", board.start(), board.tail())
        out = waiting.communicate(timeout=150)[0]; OUTPUTS.append(out)
        check("--wait: passes once everything answers", waiting.returncode == 0 and "front door check: passed" in out and "FAILED" not in out, (waiting.returncode, out))
    finally:
        if waiting.poll() is None: waiting.kill(); waiting.wait(20)
    door.stop()
    rc, out = run("--door", D)
    check("the front door down: fails", rc == 1, (rc, out))
    check("setup: the front door starts again", door.start(), door.tail())

    # ------------------------------------------------------------ a new machine token: restart the board, copy, call
    oauth(NEW_TOKEN); board.stop(); check("setup: the board restarts with the new token", board.start(), board.tail())
    rc, out = run("--door", D)
    check("a new token, the board restarted, not copied yet: the front door's call is refused", rc == 1, (rc, out))
    r = boardtoken("--check")
    check("token --check says the copy is old", r.returncode == 1 and "does not hold the board's machine token" in r.stdout, (r.returncode, r.stdout))
    ino = TOKEN_FILE.stat().st_ino
    r = boardtoken(argv=[server, "-m", "stackshot", "frontdoor-token"])
    check("`stackshot frontdoor-token` copies the new token, as a new file moved over the old one", r.returncode == 0 and TOKEN_FILE.read_text() == NEW_TOKEN + "\n" and TOKEN_FILE.stat().st_ino != ino
          and stat.S_IMODE(TOKEN_FILE.stat().st_mode) == 0o600, (r.returncode, r.stdout, r.stderr[-600:]))
    rc, out = run("--door", D, "--signin", S, "--splitter", L)
    check("after the copy every part passes, the front door not restarted", rc == 0, (rc, out))

    # ------------------------------------------------------------ the rendered Caddyfile in a real Caddy
    if shutil.which("caddy"):
        cfg = config("real-caddy.toml", splitter=caddy_port)
        croot = T / "caddy"; croot.mkdir()
        rr = subprocess.run([os.path.join(STACK, "install.sh"), "render", "stackshot-splitter.Caddyfile", "--config", cfg], env=own_env(), capture_output=True, text=True, timeout=120)
        (croot / "Caddyfile").write_text(rr.stdout)
        caddy = Proc("caddy", [shutil.which("caddy"), "run", "--config", str(croot / "Caddyfile"), "--adapter", "caddyfile"],
                     own_env(XDG_CONFIG_HOME=str(croot / "config"), XDG_DATA_HOME=str(croot / "data")), croot, caddy_port)
        check("real Caddy: starts with the rendered Caddyfile", rr.returncode == 0 and caddy.start(60), (rr.stderr[-400:], caddy.tail()))
        rc, out = run("--splitter", f"http://127.0.0.1:{caddy_port}", cfg=cfg)
        check("real Caddy: --splitter passes with a tool call through it", rc == 0 and "through the sign-in check and the front door" in out, (rc, out, caddy.tail()))
        turned_on(enabled=("frontdoor", "signin", "splitter"))
        rc, out = run("--installed", cfg=cfg)
        check("real Caddy: --installed passes", rc == 0, (rc, out))
        board.stop()
        rc, out = run("--splitter", f"http://127.0.0.1:{caddy_port}", cfg=cfg)
        check("real Caddy, board down: fails", rc == 1, (rc, out))
        caddy.stop()
    else:
        skipped.append("the check through a real Caddy (no caddy on this machine's PATH)")
except SystemExit:
    pass
finally:
    for p in PROCS: p.stop()
    for s in splitters: s.stop()

# ---------------------------------------------------------------- the token command, part 2: names, targets and refusals
def fresh(token_line):
    write_private(OAUTH, token_line)
    if TOKEN_FILE.exists() or TOKEN_FILE.is_symlink(): TOKEN_FILE.unlink()
def kept(): return TOKEN_FILE.read_text() if TOKEN_FILE.exists() else None
fresh(f"BOARD_MCP_PORTAL_TOKEN={TOKEN}"); r = boardtoken()
check("token: the older name is read", r.returncode == 0 and kept() == TOKEN + "\n", (r.returncode, r.stderr))
fresh(f"BOARD_MCP_PORTAL_TOKEN={WRONG}\nSTACKSHOT_PORTAL_TOKEN={TOKEN}"); r = boardtoken()
check("token: the STACKSHOT_ name is preferred, as the board prefers it", r.returncode == 0 and kept() == TOKEN + "\n", (r.returncode, r.stderr))
fresh(f'# STACKSHOT_PORTAL_TOKEN={WRONG}\nSTACKSHOT_PORTAL_TOKEN="{TOKEN}"\nSTACKSHOT_PORTAL_TOKEN={WRONG}'); r = boardtoken()
check("token: a commented line is skipped, quotes are taken off, the first line of a name counts", r.returncode == 0 and kept() == TOKEN + "\n", (r.returncode, r.stderr))
env_wins = secrets.token_urlsafe(36); SECRETS += (env_wins,)
fresh(f"STACKSHOT_PORTAL_TOKEN={TOKEN}"); r = boardtoken(env={"STACKSHOT_PORTAL_TOKEN": env_wins})
check("token: copies the token of the file, not one set in its own environment", r.returncode == 0 and kept() == TOKEN + "\n", (r.returncode, r.stderr))
def refused(name, word, args=(), cfg=CFG, line=None):
    if line is not None: fresh(line)
    before = kept(); r = boardtoken(*args, cfg=cfg)
    check(f"token refuses {name}: exit 2, the reason, nothing written", r.returncode == 2 and r.stderr.startswith("nothing copied: ") and word in r.stderr and kept() == before and r.stdout == "", (r.returncode, r.stdout, r.stderr))
refused("an oauth.env with no token", "names no machine token", line="STACKSHOT_GOOGLE_CLIENT_ID=x")
refused("an empty token", "names no machine token", line="STACKSHOT_PORTAL_TOKEN=")
short = "shorttoken-" + secrets.token_hex(8); assert len(short) < 32; SECRETS += (short,)
refused("a token the board would not accept (under 32 characters)", "cannot be used", line=f"STACKSHOT_PORTAL_TOKEN={short}")
refused("a token with a space", "cannot be used", line=f"STACKSHOT_PORTAL_TOKEN={TOKEN} and more")
OAUTH.unlink(); refused("no oauth.env", "cannot be read")
fresh(f"STACKSHOT_PORTAL_TOKEN={TOKEN}")
refused("an unknown board", "no [[frontdoor.backends]] board is named 'elsewhere'", args=("--board", "elsewhere"))
refused("a config with no [frontdoor] table", "no [frontdoor] table", cfg=config("t-nodoor.toml", door=False))
refused("no board of this machine and no --board", "no [[frontdoor.backends]] board is this machine's own", cfg=config("t-far.toml", backend_url="https://board.example.invalid/mcp"))
for label, url in (("elsewhere", "https://board.example.invalid/mcp"), ("on this machine at another port", f"http://127.0.0.1:{dead_port}/mcp")):
    fresh(f"STACKSHOT_PORTAL_TOKEN={TOKEN}"); write_private(TOKEN_FILE, WRONG)       # that board's own token, which must stay
    for args in (("--board", "main"), ("--board", "main", "--check")):
        refused(f"{' '.join(args)} for a board {label}, and leaves its token file as it was", "board main is not this machine's own board", args=args, cfg=config("t-far2.toml", backend_url=url))
OAUTH.unlink()
refused("a named board that is not this machine's own before oauth.env is read", "is not this machine's own board", args=("--board", "main"), cfg=config("t-far2.toml", backend_url="https://board.example.invalid/mcp"))
fresh(f"STACKSHOT_PORTAL_TOKEN={TOKEN}")
two = f'\n[[frontdoor.backends]]\nname = "second"\nurl = "http://localhost:{bport}/mcp"\ntoken_file = "{ROOT}/door/second.token"\n'
refused("two boards of this machine and no --board", "more than one", cfg=config("t-two.toml", extra=two))
def with_backend(name, body):
    return config(name, door=False, extra=f'\n[frontdoor]\nlisten_port = {dport}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{ROOT}/identity.key"\nmembers_file = "{MEMBERS}"\n'
                                          f'\n[[frontdoor.backends]]\nname = "main"\nurl = "http://127.0.0.1:{bport}/mcp"\n{body}')
write_private(ROOT / "cid", "client-id-value"); write_private(ROOT / "cs", "client-secret-" + secrets.token_hex(12))
refused("a board reached with OAuth client credentials", "OAuth client credentials", cfg=with_backend("t-oauth.toml", f'oauth = {{ client_id_file = "{ROOT}/cid", client_secret_file = "{ROOT}/cs" }}\n'))
for label, target in (("oauth.env itself", OAUTH), ("the identity secret", ROOT / "identity.key"), ("the verify secret", ROOT / "verify.key"), ("the members file", MEMBERS)):
    before = target.read_bytes()
    r = boardtoken(cfg=with_backend("t-shared.toml", f'token_file = "{target}"\n'))
    check(f"token refuses a token_file that is {label}, and leaves it as it was", r.returncode == 2 and "give the token a file of its own" in r.stderr and target.read_bytes() == before, (r.returncode, r.stderr))
alias = ROOT / "alias-of-identity"; alias.symlink_to(ROOT / "identity.key")
r = boardtoken(cfg=with_backend("t-alias.toml", f'token_file = "{alias}"\n'))
check("token refuses a link to another secret", r.returncode == 2 and (ROOT / "identity.key").read_text() == IDENTITY + "\n", (r.returncode, r.stderr))
# a link stays a link
fresh(f"STACKSHOT_PORTAL_TOKEN={TOKEN}")
elsewhere = ROOT / "elsewhere"; elsewhere.mkdir(); real = elsewhere / "real.token"; write_private(real, WRONG); TOKEN_FILE.symlink_to(real)
r = boardtoken()
check("token: a token_file that is a link stays a link, and the file it leads to is replaced", r.returncode == 0 and TOKEN_FILE.is_symlink() and real.read_text() == TOKEN + "\n" and sorted(p.name for p in elsewhere.iterdir()) == ["real.token"],
      (r.returncode, r.stderr, sorted(p.name for p in elsewhere.iterdir())))
TOKEN_FILE.unlink()
# a file others can read holds the right value: replaced by a private one
write_private(TOKEN_FILE, TOKEN); TOKEN_FILE.chmod(0o644)
r = boardtoken("--check"); check("token --check: a file others can read does not count as held", r.returncode == 1, (r.returncode, r.stdout))
r = boardtoken(); check("token: such a file is replaced by a private one", r.returncode == 0 and stat.S_IMODE(TOKEN_FILE.stat().st_mode) == 0o600 and kept() == TOKEN + "\n", (r.returncode, r.stderr))
if os.geteuid() != 0:
    write_private(TOKEN_FILE, WRONG); TOKEN_FILE.parent.chmod(0o500)
    try:
        refused("a folder that cannot be written", "cannot be written")
        check("token: a failed write leaves no temporary file", sorted(p.name for p in TOKEN_FILE.parent.iterdir()) == ["main.token"], sorted(p.name for p in TOKEN_FILE.parent.iterdir()))
    finally:
        TOKEN_FILE.parent.chmod(0o700)
else:
    skipped.append("the unwritable folder (running as root)")
TOKEN_FILE.unlink(missing_ok=True); TOKEN_FILE.mkdir()
r = boardtoken(); check("token: a directory at the token file's path is refused, and no temporary file is left", r.returncode == 2 and TOKEN_FILE.is_dir() and not list(TOKEN_FILE.parent.glob(".token-*")), (r.returncode, r.stderr))
TOKEN_FILE.rmdir()

leaks = [i for i, o in enumerate(OUTPUTS) if any(s in o for s in SECRETS)]
check(f"no secret in any of the {len(OUTPUTS)} outputs of the checks and the token command", len(OUTPUTS) > 60 and not leaks, (len(OUTPUTS), leaks))
logs = "".join(p.tail() for p in PROCS)
check("no secret in the services' logs", not any(s in logs for s in SECRETS))

# ---------------------------------------------------------------- deploy.sh
GENV = {**{k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}
def g(*a, cwd=None): return subprocess.run(["git", *a], cwd=cwd, env=GENV, capture_output=True, text=True, check=True).stdout.strip()
DP = T / "deploy"; DP.mkdir()
g("init", "-q", "--bare", "-b", "main", str(DP / "origin.git")); g("clone", "-q", str(DP / "origin.git"), str(DP / "box")); BOX = DP / "box"
(BOX / "units").mkdir(); (BOX / "stackshot/core").mkdir(parents=True)
shutil.copy(os.path.join(STACK, "deploy.sh"), BOX / "deploy.sh")
(BOX / "stackshot/core/config.py").write_text('import sys\ndef runner_process(): return "inline"\nif sys.argv[1:] == ["get", "server.port"]: print("1")\n')
(BOX / "units/scope.sh").write_text('server_ctl() { echo "server_ctl $*" >> "$RT_LOG"; }\nxdg_repair() { :; }\nstandby() { false; }\n')
(BOX / "install.sh").write_text('#!/bin/sh\necho "install.sh $*" >> "$RT_LOG"\n'); (BOX / "install.sh").chmod(0o755)
g("add", "-A", cwd=BOX); g("commit", "-qm", "base", cwd=BOX); BASE = g("rev-parse", "HEAD", cwd=BOX)
(DP / "bin").mkdir()
(DP / "bin/systemctl").write_text('''#!/bin/sh
echo "systemctl $*" >> "$RT_LOG"
u=""; for a; do u="$a"; done
case "$*" in
  *is-enabled*) case " $RT_ENABLED " in *" $u "*) echo enabled; exit 0 ;; esac; echo disabled; exit 1 ;;
  *is-active*) case " $RT_ACTIVE " in *" $u "*) echo active; exit 0 ;; esac; case " $RT_FAILED " in *" $u "*) echo failed; exit 3 ;; esac; echo inactive; exit 3 ;;
  *" restart "*) case " $RT_RESTART_FAILS " in *" $u "*) exit 1 ;; esac ;;
esac
exit 0
''')
(DP / "bin/uv").write_text('''#!/bin/sh
echo "uv $*" >> "$RT_LOG"
case "$*" in *stackshot.frontdoor.check*) echo "front door check: $RT_CHECK_SAYS"; echo "to stderr" >&2; exit "$RT_CHECK_RC" ;; esac
echo published
''')
(DP / "bin/curl").write_text('#!/bin/sh\necho "curl $*" >> "$RT_LOG"\n')
for n in ("systemctl", "uv", "curl"): (DP / "bin" / n).chmod(0o755)
SV, DOOR_U, SIGN_U, SPLIT_U = "stackshot.service", "stackshot-frontdoor.service", "stackshot-signin.service", "stackshot-splitter.service"
FU = (DOOR_U, SIGN_U, SPLIT_U)
runs = 0
def deploy(files, installed=FU, enabled=(), active=(), failed=(), restart_fails=(), check_rc=0, dry=False, wait=None):
    """The real deploy.sh on a change of `files` → (exit code, output, the stubs' log)."""
    global runs
    runs += 1
    g("reset", "-q", "--hard", BASE, cwd=BOX)
    for f in files:
        (BOX / f).parent.mkdir(parents=True, exist_ok=True); (BOX / f).write_text(f"changed for run {runs}\n")
    g("add", "-A", cwd=BOX); g("commit", "-qm", "change", cwd=BOX); g("push", "-q", "-f", "origin", "HEAD:main", cwd=BOX); g("reset", "-q", "--hard", BASE, cwd=BOX)
    home = DP / f"home{runs}"; (home / ".config/systemd/user").mkdir(parents=True)
    for u in installed: (home / ".config/systemd/user" / u).write_text("[Service]\n")
    log = DP / f"log{runs}"
    env = {**GENV, "PATH": f"{DP}/bin:" + os.environ.get("PATH", ""), "HOME": str(home), "RT_LOG": str(log), "RT_ENABLED": " ".join(enabled), "RT_ACTIVE": " ".join(active), "RT_FAILED": " ".join(failed),
           "RT_RESTART_FAILS": " ".join(restart_fails), "RT_CHECK_RC": str(check_rc), "RT_CHECK_SAYS": "passed (stub)" if check_rc == 0 else "FAILED: front door: stub says no"}
    env.pop("DEPLOY_FRONT_WAIT", None)
    if wait is not None: env["DEPLOY_FRONT_WAIT"] = wait
    r = subprocess.run(["bash", str(BOX / "deploy.sh"), *(["--dry-run"] if dry else [])], cwd=BOX, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr, log.read_text().splitlines() if log.exists() else []
def planned(out):
    got = [l for l in out.splitlines() if l.startswith("restarts:")]
    return None if len(got) != 1 else [u for u in got[0].split()[1:] if u != "none"]
def restarted(log): return [l.split()[-1] for l in log if (l.startswith("systemctl --user restart ") or l.startswith("server_ctl restart "))]
def checks(log): return [l for l in log if "stackshot.frontdoor.check" in l]
CODE = ("stackshot/frontdoor/door.py",)

for label, kw, files, want in (
        ("a server change, all turned on and the splitter running", dict(enabled=FU, active=FU), CODE, [SV, DOOR_U, SIGN_U]),
        ("a server change, the door and the sign-in service running but not enabled", dict(active=(DOOR_U, SIGN_U)), CODE, [SV, DOOR_U, SIGN_U]),
        ("a server change, enabled but stopped", dict(enabled=(DOOR_U, SIGN_U)), CODE, [SV, DOOR_U, SIGN_U]),
        ("a server change, one failed and enabled", dict(enabled=(SIGN_U,), failed=(SIGN_U,)), CODE, [SV, SIGN_U]),
        ("a server change, one failed and not enabled", dict(failed=(SIGN_U,)), CODE, [SV]),
        ("the sign-in unit file, failed and not enabled", dict(failed=(SIGN_U,)), ("units/stackshot-signin.service.in",), []),
        ("the front door's unit file, failed and enabled", dict(enabled=(DOOR_U,), failed=(DOOR_U,)), ("units/stackshot-frontdoor.service.in",), [DOOR_U]),
        ("a server change, installed and never turned on", dict(), CODE, [SV]),
        ("a server change, turned on but not installed", dict(installed=(), enabled=FU, active=FU), CODE, [SV]),
        ("the front door's unit file", dict(enabled=FU, active=FU), ("units/stackshot-frontdoor.service.in",), [DOOR_U]),
        ("the sign-in unit file", dict(enabled=FU, active=FU), ("units/stackshot-signin.service.in",), [SIGN_U]),
        ("the splitter's unit file, running", dict(enabled=FU, active=FU), ("units/stackshot-splitter.service.in",), [SPLIT_U]),
        ("the splitter's Caddyfile, running", dict(active=(SPLIT_U,)), ("units/stackshot-splitter.Caddyfile.in",), [SPLIT_U]),
        ("the splitter's Caddyfile, enabled and stopped: never started", dict(enabled=(SPLIT_U,)), ("units/stackshot-splitter.Caddyfile.in",), []),
        ("the splitter's Caddyfile, failed", dict(failed=(SPLIT_U,)), ("units/stackshot-splitter.Caddyfile.in",), []),
        ("the splitter's Caddyfile, enabled and failed: never started", dict(enabled=(SPLIT_U,), failed=(SPLIT_U,)), ("units/stackshot-splitter.Caddyfile.in",), []),
        ("a doc", dict(enabled=FU, active=FU), ("docs/a.md",), [])):
    rc, out, log = deploy(files, dry=True, **kw)
    check(f"deploy plan: {label}: {want or 'nothing'}", rc == 0 and planned(out) == want, (rc, out[-500:]))
    rc, out, log = deploy(files, **kw)
    check(f"deploy: {label}: restarts exactly those", rc == 0 and restarted(log) == want and not [l for l in log if re.search(r"systemctl --user (start|enable)\b.*stackshot-(frontdoor|signin|splitter)", l)], (rc, restarted(log), out[-500:]))

rc, out, log = deploy(CODE, enabled=FU, active=FU)
ck = checks(log)
check("deploy: the check runs once, with the server extra of the checkout, --installed and 90 s of waiting",
      rc == 0 and ck == [f"uv run --project {BOX} --locked --extra server python -m stackshot.frontdoor.check --installed --wait 90"], (rc, ck, out[-500:]))
at = lambda frag: next((i for i, l in enumerate(log) if frag in l), -1)
check("deploy: the check comes after the restarts, the health check and the republish", -1 < at(f"restart {SV}") < at(f"restart {DOOR_U}") < at("curl ") < at("stackshot publish") < at("frontdoor.check"), log)
check("deploy: reset-failed goes before each front door restart", all(-1 < at(f"reset-failed {u}") < at(f"restart {u}") for u in (DOOR_U, SIGN_U)), log)
check("deploy: what the check printed is in the deploy's output, indented", "\n  front door check: passed (stub)" in out and "\n  to stderr" in out, out)
rc, out, log = deploy(CODE, enabled=FU, active=FU, check_rc=1)
check("deploy: a failed check fails the deploy, with its words and the closing line", rc == 1 and "front door check: FAILED: front door: stub says no" in out and "the front door check failed after the deploy" in out
      and "healthz ok" in out, (rc, out[-700:]))
rc, out, log = deploy(CODE, enabled=FU, active=FU, check_rc=2)
check("deploy: a check that could not run (exit 2) fails the deploy too", rc == 1 and "the front door check failed after the deploy" in out, (rc, out[-500:]))
rc, out, log = deploy(("docs/a.md",), active=(SPLIT_U,), check_rc=1)
check("deploy: with a front door unit on, the check runs even when nothing of the front door restarted", rc == 1 and len(checks(log)) == 1, (rc, checks(log), out[-500:]))
for u in FU:
    rc, out, log = deploy(CODE, enabled=(u,), check_rc=1)
    check(f"deploy: {u} alone turned on is enough for the check", rc == 1 and len(checks(log)) == 1, (rc, checks(log), out[-300:]))
rc, out, log = deploy(CODE, check_rc=1)
check("deploy: no unit turned on: no check, the deploy as before", rc == 0 and checks(log) == [] and "front door" not in out, (rc, checks(log), out[-500:]))
rc, out, log = deploy(CODE, failed=FU, check_rc=1)
check("deploy: every unit failed and none enabled: none is reset or restarted, and no check", rc == 0 and checks(log) == [] and restarted(log) == [SV]
      and not [l for l in log if re.search(r"(reset-failed|restart|start|enable) .*stackshot-(frontdoor|signin|splitter)", l)], (rc, log, out[-500:]))
for u in FU:
    rc, out, log = deploy(("docs/a.md",), enabled=(u,), failed=(u,), check_rc=1)
    check(f"deploy: {u} failed and enabled is enough for the check", rc == 1 and len(checks(log)) == 1, (rc, checks(log), out[-300:]))
rc, out, log = deploy(CODE, installed=(), enabled=FU, active=FU, check_rc=1)
check("deploy: no front door unit installed: no check and no systemctl question about one", rc == 0 and checks(log) == [] and not [l for l in log if "frontdoor" in l or "signin" in l or "splitter" in l], (rc, log))
rc, out, log = deploy(CODE, enabled=FU, active=FU, restart_fails=(DOOR_U,), check_rc=0)
check("deploy: a front door restart that fails is a warning, the others still restart, and the check decides", rc == 0 and f"WARNING: {DOOR_U} could not be restarted" in out and SIGN_U in restarted(log) and len(checks(log)) == 1, (rc, out[-700:]))
rc, out, log = deploy(CODE, enabled=FU, active=FU, restart_fails=(DOOR_U,), check_rc=1)
check("deploy: a failed restart and a failed check: the deploy fails", rc == 1, (rc, out[-500:]))
for wait, want in (("7", "7"), ("0", "0"), ("soon", "90"), ("", "90"), ("-3", "90")):
    rc, out, log = deploy(CODE, enabled=FU, active=FU, wait=wait)
    check(f"deploy: DEPLOY_FRONT_WAIT={wait!r} waits {want} s", len(checks(log)) == 1 and checks(log)[0].endswith(f"--installed --wait {want}"), checks(log))

for s in skipped: print(f"skipped: {s}", flush=True)
if fails and not os.environ.get("KEEP_SCRATCH"):
    for p in PROCS:
        if p.tail().strip(): print(f"--- {p.name} log tail ---\n{p.tail()}", flush=True)
print(("ok" if not fails else "FAILED") + f": front door real-call scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "") + (f", {len(skipped)} part skipped" if skipped else ""), flush=True)
sys.exit(1 if fails else 0)
