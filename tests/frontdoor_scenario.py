"""tests/frontdoor_scenario.py: the front door (stackshot/frontdoor/), offline and hermetic.

Three stand-in boards, one stand-in brain (OAuth client credentials, a tool list that depends on the credential's scope) and the front door itself run
in this process on 127.0.0.1 ephemeral ports; the test plays the reverse proxy (it sets the identity header) and the client. Nothing leaves the machine.

    tests/run-suite frontdoor        → exit 0 / 1

Checked: the identity functions (sign/verify: tamper, expiry, a wrong secret); the config notes and the secret-file reader; the list (a board's own schemas
plus an optional `board`; only the caller's backends; no caller → empty); routing and every refusal text; 45 concurrent calls over 3 sessions (no
cross-talk, the caller's identity at the board); the caller's own credentials never at a backend; streaming progress and logs while the call runs; a
backend that is down (a warning, a call error, none answered, /healthz 503); the brain's credential-limited list and the refusal that follows from it;
the composed instructions; the entry point as a subprocess. Every server and the temp folder are removed at the end, pass or fail.
"""
import asyncio, base64, json, os, pathlib, socket, subprocess, sys, threading, time, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch

tmp = _scratch.mkdtemp(prefix="frontdoor-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}: {str(got)[:600]}")

import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from starlette.responses import JSONResponse

from stackshot.core import config as cfgmod, frontdoor_config as fc
from stackshot.frontdoor import app as fdapp, config as fdconf, identity as ident, instructions as fdinstr, provider as fdprov

# ------------------------------------------------------------------------------------------------ files
def secret_file(name, value, mode=0o600):
    p = T / name
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f: f.write(value + "\n")
    os.chmod(p, mode)
    return str(p)

IDENT_SECRET = "identity-secret-0123456789"
ident_file = secret_file("identity.key", IDENT_SECRET)
BOARD_TOK = {n: f"BOARDTOK-{n}-0123456789abcdef" for n in "abc"}
board_tok_file = {n: secret_file(f"board-{n}.token", BOARD_TOK[n]) for n in "abc"}
cid_file = secret_file("brain.cid", "cid-rw"); csec_file = secret_file("brain.csec", "brain-secret-rw-0123456789")
members_path = T / "members.json"
MEMBERS = {"alice": ["a"], "bob": ["a", "b"], "carol": [], "dave": ["b", "brain"], "erin": ["a", "c"], "fred": ["brain"], "gina": ["a", "b", "c", "brain"], "zoe": []}
members_path.write_text(json.dumps(MEMBERS))
CALLER = "CALLER-"          # every credential the test's client sends to the front door starts with this: none may reach a backend

# ------------------------------------------------------------------------------------------------ in-process servers
class Server:
    """An ASGI app on 127.0.0.1:<ephemeral port>, in its own thread; stop() ends it and frees the port."""
    def __init__(self, app, sock=None):
        self.sock = sock or socket.socket();
        if sock is None: self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.srv = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        self.th = threading.Thread(target=lambda: self.srv.run(sockets=[self.sock]), daemon=True)
        self.up = False
    def start(self):
        self.th.start()
        for _ in range(200):
            if self.srv.started: self.up = True; return self
            time.sleep(0.05)
        raise RuntimeError("stand-in server did not start")
    def stop(self):
        if not self.up: return
        self.srv.should_exit = True; self.th.join(15); self.up = False
        try: self.sock.close()
        except OSError: pass
    @property
    def url(self): return f"http://127.0.0.1:{self.port}"

SERVERS = []
RECORDS = []                # one row per request that reached a stand-in's door

class Edge:
    """ASGI wrapper of a stand-in backend: records every request (header kinds, never values) and refuses what does not carry the backend's own credential."""
    def __init__(self, app, name, ok_auth, www_authenticate=None):
        self.app, self.name, self.ok_auth, self.www = app, name, ok_auth, www_authenticate
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        h = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        everything = " ".join(h.values())
        path = scope["path"]
        RECORDS.append({"backend": self.name, "path": path, "method": scope["method"], "caller_cred": CALLER in everything, "cookie": "cookie" in h, "apikey": "x-api-key" in h,
                        "identity": h.get(ident.HEADER), "auth": h.get("authorization", ""), "direct": "x-test-direct" in h})
        open_route = path == "/healthz" or path.startswith("/.well-known") or path == "/token"
        if not open_route and not self.ok_auth(h.get("authorization", "")):
            hdr = [(b"content-type", b"text/plain")] + ([(b"www-authenticate", self.www.encode())] if self.www else [])
            await send({"type": "http.response.start", "status": 401, "headers": hdr}); await send({"type": "http.response.body", "body": b"no"}); return
        await self.app(scope, receive, send)

BOARD_TEXT = {"a": "BOARD A INSTRUCTIONS: use brief first.\nSecond line with  double  spaces.", "b": "BOARD B INSTRUCTIONS: a different text.", "c": None}
BOARD_TEXT["c"] = BOARD_TEXT["a"]          # board c has board a's text: the front door shows one block for both

def make_board(marker):
    m = FastMCP("board-" + marker, instructions=BOARD_TEXT[marker])
    @m.tool
    def brief(project: str = "", limit: int = 5) -> str:
        """The brief of the board (a stand-in)."""
        return f"board-{marker} brief project={project!r} limit={limit}"
    @m.tool
    def get(id: str, fields: list[str] | None = None) -> dict:
        """One item (a stand-in)."""
        return {"board": marker, "id": id, "fields": fields or []}
    @m.tool
    def whoami() -> str:
        """What this board process sees of the caller."""
        h = get_http_headers(include_all=True)
        return json.dumps({"board": marker, "identity": h.get(ident.HEADER), "authorization": h.get("authorization", "")})
    @m.tool
    async def stream(seconds: float, interval: float, ctx: Context) -> str:
        """A long call that reports progress and logs every `interval` seconds."""
        n = max(1, int(seconds / interval))
        for i in range(n):
            await asyncio.sleep(interval)
            await ctx.report_progress(i + 1, n, f"tick {i + 1}")
            await ctx.info(f"board-{marker} tick {i + 1}/{n}")
        return f"board-{marker} streamed {n}"
    @m.tool
    def refuse() -> str:
        """Always fails with the board's own error."""
        raise ToolError("the board says no, with its own words")
    @m.custom_route("/healthz", methods=["GET"])
    async def healthz(request):
        return JSONResponse({"ok": True})
    return m

BRAIN_TEXT = "BRAIN INSTRUCTIONS: search before you answer."
ADMIN_TOOLS = ("admin_stats", "admin_drop")
OAUTH = {"requests": 0, "granted": [], "rotated_id": None}
BRAIN = {}

def token_scopes():
    a = get_http_headers(include_all=True).get("authorization", "")
    return a[len("Bearer TOK-"):].split(".") if a.startswith("Bearer TOK-") else []

class ScopeList(Middleware):
    """The stand-in brain lists what the credential's scope allows, and (as a real one does) answers an unlisted call as an unknown tool."""
    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        return [t for t in tools if t.name not in ADMIN_TOOLS or "admin" in token_scopes()]
    async def on_call_tool(self, context, call_next):
        if context.message.name in ADMIN_TOOLS and "admin" not in token_scopes(): raise NotFoundError(f"Unknown tool: {context.message.name}")
        return await call_next(context)

def make_brain():
    m = FastMCP("brain", instructions=BRAIN_TEXT)
    @m.tool
    def get_page(slug: str) -> str:
        """Read a page."""
        return f"page {slug}"
    @m.tool
    def put_page(slug: str, content: str) -> str:
        """Write a page."""
        return f"wrote {slug} ({len(content)} chars)"
    @m.tool
    def search(query: str) -> str:
        """Search."""
        return f"hits for {query}"
    @m.tool
    def admin_stats() -> str:
        """Admin only."""
        return "stats"
    @m.tool
    def admin_drop(slug: str) -> str:
        """Admin only."""
        return "dropped"
    m.add_middleware(ScopeList())
    @m.custom_route("/healthz", methods=["GET"])
    async def healthz(request):
        return JSONResponse({"ok": True})
    base = lambda: BRAIN["base"]
    @m.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
    async def prm(request):
        return JSONResponse({"resource": base() + "/mcp", "authorization_servers": [base()], "scopes_supported": ["read", "write", "admin"]})
    @m.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def prm2(request):
        return JSONResponse({"resource": base() + "/mcp", "authorization_servers": [base()], "scopes_supported": ["read", "write", "admin"]})
    @m.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def asm(request):
        return JSONResponse({"issuer": base(), "authorization_endpoint": base() + "/authorize", "token_endpoint": base() + "/token", "response_types_supported": ["code"],
                             "grant_types_supported": ["client_credentials"], "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                             "scopes_supported": ["read", "write", "admin"]})
    @m.custom_route("/token", methods=["POST"])
    async def token(request):
        OAUTH["requests"] += 1
        form = {k: v for k, v in (kv.split("=", 1) for kv in (await request.body()).decode().split("&") if "=" in kv)}
        auth = request.headers.get("authorization", "")
        cid = csec = ""
        if auth.lower().startswith("basic "):
            cid, _, csec = base64.b64decode(auth[6:]).decode().partition(":")
        else:
            cid, csec = form.get("client_id", ""), form.get("client_secret", "")
        known = {"cid-rw": ("brain-secret-rw-0123456789", {"read", "write"}), "cid-admin": ("brain-secret-admin-0123456789", {"read", "write", "admin"})}
        ok = cid in known and known[cid][0] == csec
        if not ok: return JSONResponse({"error": "invalid_client"}, status_code=401)
        asked = sorted(set(form.get("scope", "").replace("+", " ").replace("%20", " ").split()))
        got = sorted(known[cid][1])          # a registered client gets what it was registered for
        OAUTH["granted"].append((cid, asked))
        return JSONResponse({"access_token": "TOK-" + ".".join(got), "token_type": "Bearer", "expires_in": 3600, "scope": " ".join(got)})
    return m

def start_servers():
    out = {}
    for n in "abc":
        srv = Server(Edge(make_board(n).http_app(path="/mcp"), n, lambda a, n=n: a == "Bearer " + BOARD_TOK[n]))
        out[n] = srv; SERVERS.append(srv)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); BRAIN["base"] = f"http://127.0.0.1:{sock.getsockname()[1]}"
    www = f'Bearer resource_metadata="{BRAIN["base"]}/.well-known/oauth-protected-resource/mcp"'
    out["brain"] = Server(Edge(make_brain().http_app(path="/mcp"), "brain", lambda a: a.startswith("Bearer TOK-"), www), sock); SERVERS.append(out["brain"])
    for s in out.values(): s.start()
    return out

def port_free(port):
    s = socket.socket(); s.settimeout(1)
    try: return s.connect_ex(("127.0.0.1", port)) != 0
    finally: s.close()

def http_get(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()

def front_cfg(servers, **over):
    t = {"listen_port": 8999, "identity_header": "X-Forwarded-User", "identity_secret_file": ident_file, "members_file": str(members_path), "health_cache_seconds": 0,
         "preface": "TEST PREFACE: the front door.",
         "backends": [{"name": n, "kind": "board", "url": servers[n].url + "/mcp", "token_file": board_tok_file[n]} for n in "abc"]
                     + [{"name": "brain", "kind": "brain", "url": servers["brain"].url + "/mcp", "oauth": {"client_id_file": cid_file, "client_secret_file": csec_file, "scopes": ["read", "write"]}}]}
    t.update(over)
    return {"frontdoor": t}

# ------------------------------------------------------------------------------------------------ 1. identity: sign / verify (pure)
S1, S2 = b"identity-secret-0123456789", b"another-secret-0123456789"
v = ident.sign(S1, "alice@example.test", now=1000)
check("identity: a signed identity verifies to the same identity", ident.verify(S1, v, now=1010) == "alice@example.test", v)
check("identity: the value is v1.<identity>.<time>.<mac> with nothing readable but the identity", v.count(".") == 3 and v.startswith("v1.") and "alice" not in v, v)
check("identity: a wrong secret does not verify", ident.verify(S2, v, now=1010) is None)
for label, bad in (("the identity swapped", v.replace(v.split(".")[1], base64.urlsafe_b64encode(b"mallory").decode().rstrip("="))), ("the time changed", ".".join([*v.split(".")[:2], "1001", v.split(".")[3]])),
                   ("the mac cut", v[:-4]), ("one hex digit flipped", v[:-1] + ("0" if v[-1] != "0" else "1")), ("no mac", ".".join(v.split(".")[:3])), ("empty", ""), ("garbage", "not a signed value"),
                   ("another version", "v2" + v[2:]), ("extra part", v + ".x")):
    check(f"identity: tampered ({label}) does not verify", ident.verify(S1, bad, now=1010) is None, bad)
check("identity: older than max_age (300 s) does not verify, 299 s does", ident.verify(S1, v, now=1000 + 301) is None and ident.verify(S1, v, now=1000 + 299) == "alice@example.test")
check("identity: a time more than 30 s ahead of the verifier does not verify, 10 s ahead does", ident.verify(S1, v, now=1000 - 31) is None and ident.verify(S1, v, now=1000 - 10) == "alice@example.test")
import hashlib, hmac as _hmac
def forged(version):
    body = f"{version}.{v.split('.')[1]}.1000"
    return f"{body}.{_hmac.new(S1, body.encode(), hashlib.sha256).hexdigest()}"
check("identity: a value with a correct mac under the right secret verifies (the helper forges as sign does)", ident.verify(S1, forged("v1"), now=1010) == "alice@example.test")
check("identity: a correctly signed value of another version does not verify", ident.verify(S1, forged("v2"), now=1010) is None)
check("identity: max_age is the caller's to set", ident.verify(S1, v, now=1100, max_age=50) is None and ident.verify(S1, v, now=1100, max_age=500) == "alice@example.test")
check("identity: None and a non-string never verify", ident.verify(S1, None, now=1000) is None and ident.verify(S1, 5, now=1000) is None)
check("identity: an empty secret verifies nothing", ident.verify(b"", v, now=1010) is None)
check("identity: a value signed with an empty secret verifies against an empty secret no more than against any other",
      ident.verify(b"", f"v1.{v.split('.')[1]}.1000." + _hmac.new(b"", f"v1.{v.split('.')[1]}.1000".encode(), hashlib.sha256).hexdigest(), now=1010) is None)
for label, args in (("an empty secret", (b"", "alice")), ("an empty identity", (S1, "")), ("a blank identity", (S1, "  "))):
    try: ident.sign(*args); check(f"identity: sign refuses {label}", False)
    except ValueError: check(f"identity: sign refuses {label}", True)
check("identity: an identity with symbols round-trips", ident.verify(S1, ident.sign(S1, "a.b+c@example.test/x y", now=5), now=5) == "a.b+c@example.test/x y")
check("identity: the time defaults to the clock", ident.verify(S1, ident.sign(S1, "zed")) == "zed")
check("identity: the header name is the one the docs give", ident.HEADER == "x-stackshot-identity", ident.HEADER)

# ------------------------------------------------------------------------------------------------ 2. config: notes, the settings, the secret-file reader
good = {"identity_header": "X-Forwarded-User", "identity_secret_file": ident_file, "members_file": str(members_path),
        "backends": [{"name": "a", "url": "http://127.0.0.1:1/mcp", "token_file": board_tok_file["a"]},
                     {"name": "brain", "kind": "brain", "url": "http://127.0.0.1:2/mcp", "oauth": {"client_id_file": cid_file, "client_secret_file": csec_file, "scopes": "read write"}}]}
st, notes = fc.parse({"frontdoor": good})
check("config: a good table gives no note", notes == [], notes)
check("config: the settings read (header lower-cased, defaults, backends, scopes)", st.present and st.identity_header == "x-forwarded-user" and st.host == "127.0.0.1" and st.port == 8020 and st.health_cache_seconds == 5
      and [b.name for b in st.backends] == ["a", "brain"] and st.backends[0].health_url == "http://127.0.0.1:1/healthz" and st.backends[1].oauth and st.backends[1].scopes == "read write"
      and st.brain().name == "brain" and [b.name for b in st.boards()] == ["a"], st)
check("config: no [frontdoor] table is no note and not present", fc.parse({}) == (fc.Settings(present=False), []) and fc.notes({}) == [])
check("config: the notes are part of the config's own notes (core/config.notes)", cfgmod.frontdoor_notes({"frontdoor": {**good, "listen_port": "x"}}) != [] and cfgmod.frontdoor_notes({}) == [])
def with_(**kw): return {"frontdoor": {**good, **kw}}
def bad_backend(**kw): return {"frontdoor": {**good, "backends": [{**good["backends"][0], **kw}, good["backends"][1]]}}
CASES = [
    ("listen_port out of range", with_(listen_port=70000), "listen_port"), ("listen_port a string", with_(listen_port="80"), "listen_port"), ("listen_port a bool", with_(listen_port=True), "listen_port"),
    ("listen_host not loopback", with_(listen_host="0.0.0.0"), "not the loopback address"), ("listen_host empty", with_(listen_host=""), "listen_host"),
    ("no identity_header", {"frontdoor": {k: v for k, v in good.items() if k != "identity_header"}}, "no identity_header"),
    ("identity_header Authorization", with_(identity_header="Authorization"), "identity_header"), ("identity_header Cookie", with_(identity_header="cookie"), "identity_header"),
    ("identity_header X-Api-Key", with_(identity_header="X-API-KEY"), "identity_header"), ("identity_header with a space", with_(identity_header="x user"), "identity_header"),
    ("no members_file", {"frontdoor": {k: v for k, v in good.items() if k != "members_file"}}, "no members_file"),
    ("no identity_secret_file", {"frontdoor": {k: v for k, v in good.items() if k != "identity_secret_file"}}, "no identity_secret_file"),
    ("identity_secret_file group-readable", with_(identity_secret_file=secret_file("loose.key", "identity-secret-0123456789", 0o640)), "identity_secret_file"),
    ("health_cache_seconds negative", with_(health_cache_seconds=-1), "health_cache_seconds"), ("health_cache_seconds a string", with_(health_cache_seconds="5"), "health_cache_seconds"),
    ("preface empty", with_(preface="  "), "preface"), ("no backends", with_(backends=[]), "no backends"), ("backends not a list", with_(backends="a"), "backends is not a list"),
    ("backend not a table", with_(backends=["a"]), "is not a table"), ("backend without a name", bad_backend(name=""), "no usable name"), ("backend name with a slash", bad_backend(name="a/b"), "no usable name"),
    ("backend kind unknown", bad_backend(kind="proxy"), "neither"), ("backend url not http", bad_backend(url="ftp://x/mcp"), "url is not an http"),
    ("backend url with a password", bad_backend(url="http://u:p@127.0.0.1/mcp"), "url is not an http"), ("backend health_url bad", bad_backend(health_url="nope"), "health_url"),
    ("backend with both credentials", bad_backend(oauth={"client_id_file": cid_file, "client_secret_file": csec_file}), "both token_file and oauth"),
    ("backend with no credential", bad_backend(token_file=None), "no token_file and no oauth"), ("backend token_file not a path", bad_backend(token_file=7), "token_file is not a path"),
    ("backend token_file loose mode", bad_backend(token_file=secret_file("loose.token", "BOARDTOK-loose-0123456789", 0o644)), "token_file"),
    ("oauth without the secret file", bad_backend(token_file=None, oauth={"client_id_file": cid_file}), "oauth needs client_id_file"), ("oauth scopes a number", bad_backend(token_file=None, oauth={"client_id_file": cid_file, "client_secret_file": csec_file, "scopes": 5}), "scopes"),
    ("a second brain", {"frontdoor": {**good, "backends": [*good["backends"], {**good["backends"][1], "name": "brain2"}]}}, "second brain"),
    ("a repeated name", {"frontdoor": {**good, "backends": [*good["backends"], {**good["backends"][0]}]}}, "repeats the name"),
]
for name, cfg, want in CASES:
    _, ns = fc.parse(cfg)
    check(f"config note: {name} is named", any(want in n for n in ns), ns)
    check(f"config note: {name} reaches core/config.notes", any(want in n for n in cfgmod.notes(cfg)), cfgmod.notes(cfg)[-3:] if isinstance(cfgmod.notes(cfg), list) else None)
st_bad, _ = fc.parse(bad_backend(name="a/b"))
check("config: a wrong backend entry is left out and the others are served", [b.name for b in st_bad.backends] == ["brain"] and fc.blocking(st_bad) == [], st_bad.backends)
check("config: no backend at all, or no identity_header, or no members_file blocks the start", all(fc.blocking(fc.parse(c)[0]) for c in (with_(backends=[]), {"frontdoor": {k: v for k, v in good.items() if k != "identity_header"}}, {"frontdoor": {k: v for k, v in good.items() if k != "members_file"}}, {})))
try: fdconf.load(with_(backends=[])); check("config: load() raises ConfigError when it cannot serve", False)
except fdconf.ConfigError as e: check("config: load() raises ConfigError when it cannot serve", "no usable backend" in str(e), str(e))
check("config: the identity-header and secret-file notes never print a secret value", all(IDENT_SECRET not in n for _, cfg, _ in CASES for n in fc.parse(cfg)[1]))

def err(fn, *a, **k):
    try: fn(*a, **k); return None
    except fdconf.FileError as e: return str(e)
check("secret file: a good file reads (first non-empty line, trimmed)", fdconf.read_secret(ident_file, "x") == IDENT_SECRET)
e = err(fdconf.read_secret, secret_file("g.key", "identity-secret-0123456789", 0o640), "identity_secret_file"); check("secret file: group-readable is refused, and the value is not in the message", e and "identity_secret_file" in e and IDENT_SECRET not in e, e)
e = err(fdconf.read_secret, secret_file("o.key", "identity-secret-0123456789", 0o604), "x"); check("secret file: other-readable is refused", bool(e), e)
e = err(fdconf.read_secret, secret_file("short.key", "short"), "x"); check("secret file: a value under 16 characters is refused", e and "shorter than 16" in e and "short\n" not in e, e)
e = err(fdconf.read_secret, secret_file("empty.key", ""), "x"); check("secret file: an empty file is refused", e and "empty" in e, e)
e = err(fdconf.read_secret, secret_file("ctl.key", "abc\x07defghijklmnopqrstu"), "x"); check("secret file: a control character is refused", e and "non-printable" in e, e)
e = err(fdconf.read_secret, str(T / "nope.key"), "x"); check("secret file: a missing file is refused", bool(e), e)
e = err(fdconf.read_secret, str(T), "x"); check("secret file: a directory is refused", bool(e), e)
big = T / "big.key"; big.write_text("x" * 70000); os.chmod(big, 0o600)
e = err(fdconf.read_secret, str(big), "x"); check("secret file: a file over 64 KiB is refused unread", e and "larger" in e, e)
fifo = T / "fifo.key"; os.mkfifo(fifo, 0o600)
t0 = time.monotonic(); e = err(fdconf.read_secret, str(fifo), "x"); check("secret file: a FIFO is refused at once as not a regular file (no wait for a writer)", e and "not a regular file" in e and time.monotonic() - t0 < 2, (e, time.monotonic() - t0))
mm = T / "m1.json"; mm.write_text(json.dumps({"alice": ["a", " b ", 5, ""], " bob ": "a", "": ["a"], "c": []}))
check("members: read as member -> [names]; a bad value is a member of nothing; a blank name is dropped", fdconf.read_members(str(mm)) == {"alice": ["a", "b"], "bob": [], "c": []}, fdconf.read_members(str(mm)))
mm.write_text("[1]"); e = err(fdconf.read_members, str(mm)); check("members: a file that is not an object is refused", e and "JSON object" in e, e)
mm.write_text("{nope"); e = err(fdconf.read_members, str(mm)); check("members: a file that is not JSON is refused", e and "not valid JSON" in e, e)
mm.write_text("{}"); os.chmod(mm, 0o644); check("members: the members file may be world-readable (it holds names, not secrets)", err(fdconf.read_members, str(mm)) is None)

# ------------------------------------------------------------------------------------------------ the rest runs against live stand-ins
servers = start_servers()
SETTINGS, NOTES = fc.parse(front_cfg(servers))
check("setup: the stand-in front door's own config has no note", NOTES == [], NOTES)
front, door = fdapp.build(SETTINGS)
fd_server = Server(fdapp.asgi_app(front, door)); SERVERS.append(fd_server); fd_server.start()
FRONT = fd_server.url
fdprov.MISS_RECHECK_SECONDS = 0

def proxy_headers(user):
    """What the reverse proxy and the client send for `user`: the identity header the proxy sets, and the client's own credentials, in the three spellings."""
    return {"X-Forwarded-User": user, "authorization": f"Bearer {CALLER}{user}", "x-api-key": CALLER + user, "cookie": f"session={CALLER}{user}"}
def fclient(user, **kw): return Client(StreamableHttpTransport(FRONT + "/mcp", headers=proxy_headers(user)), mode="legacy", **kw)
def direct_board(n): return Client(StreamableHttpTransport(servers[n].url + "/mcp", headers={"authorization": "Bearer " + BOARD_TOK[n], "x-test-direct": "1"}), mode="legacy")
async def call(c, name, args=None): return (await c.call_tool(name, args or {})).content[0].text
async def refusal(c, name, args=None):
    try: await c.call_tool(name, args or {}); return None
    except Exception as e: return str(e)
async def list_text(user):
    try:
        async with fclient(user) as c: return None, [t.name for t in await c.list_tools()]
    except Exception as e: return str(e), None

async def main():
    # ---- 3. the list: one board's schemas plus an optional `board`
    async with direct_board("a") as c: single = {t.name: t for t in await c.list_tools()}
    async with fclient("bob") as c: front_bob = {t.name: t for t in await c.list_tools()}
    async with fclient("alice") as c: front_alice = {t.name: t for t in await c.list_tools()}
    def sans_board(t):
        s = json.loads(json.dumps(t.inputSchema)); s.get("properties", {}).pop("board", None); return s
    ann = lambda t: json.dumps(t.annotations.model_dump() if t.annotations else None, sort_keys=True)
    for who, fl in (("bob (two boards)", front_bob), ("alice (one board)", front_alice)):
        check(f"list: {who} sees exactly one board's tool names", sorted(fl) == sorted(single), (sorted(fl), sorted(single)))
        check(f"list: {who}: every schema is the board's own, apart from the `board` property", all(sans_board(fl[n]) == json.loads(json.dumps(single[n].inputSchema)) for n in single), [n for n in single if sans_board(fl[n]) != single[n].inputSchema])
        check(f"list: {who}: every tool has an optional string `board`", all((fl[n].inputSchema["properties"].get("board") or {}).get("type") == "string" and "board" not in (fl[n].inputSchema.get("required") or []) for n in fl))
        check(f"list: {who}: required lists, descriptions, titles, annotations and output schemas are the board's own",
              all((fl[n].inputSchema.get("required"), fl[n].description, fl[n].title, ann(fl[n]), json.dumps(fl[n].outputSchema, sort_keys=True)) == (single[n].inputSchema.get("required"), single[n].description, single[n].title, ann(single[n]), json.dumps(single[n].outputSchema, sort_keys=True)) for n in single))
    check("list: the `board` property is added once and the board's own properties keep their order", list(front_bob["brief"].inputSchema["properties"]) == ["project", "limit", "board"], list(front_bob["brief"].inputSchema["properties"]))
    check("list: the tool objects the board gave are not changed (a second listing has the same schema)", "board" not in single["brief"].inputSchema["properties"])
    for user, want in (("dave", set(single) | {"get_page", "put_page", "search"}), ("fred", {"get_page", "put_page", "search"}), ("gina", set(single) | {"get_page", "put_page", "search"})):
        e, names = await list_text(user)
        check(f"list: {user} sees the tools of the backends the member is on ({'board+brain' if user != 'fred' else 'brain only'})", names is not None and set(names) == want, (e, names))
    async with fclient("dave") as c: tl = {t.name: t for t in await c.list_tools()}
    check("list: a brain tool carries no `board` property (it is the brain's own schema)", "board" not in tl["get_page"].inputSchema["properties"], tl["get_page"].inputSchema)
    check("list: the brain's admin tools are not in the list (the credential is read and write)", not set(ADMIN_TOOLS) & set(tl), sorted(tl))
    async with Client(StreamableHttpTransport(servers["brain"].url + "/mcp", headers={"authorization": "Bearer TOK-admin.read.write", "x-test-direct": "1"}), mode="legacy") as c: adm = [t.name for t in await c.list_tools()]
    check("list: the same brain lists its admin tools to an admin credential (so the front door's list is the credential's, not a name list)", set(ADMIN_TOOLS) <= set(adm), adm)
    e, names = await list_text("carol"); check("list: a member of no board gets the refusal text", e is not None and "you are not a member of any board." in e, (e, names))
    e, names = await list_text("mallory"); check("list: a caller the members file does not know gets the same refusal", e is not None and "you are not a member of any board." in e, (e, names))
    check("list: a name in the members file that no backend has is no membership", fdprov.Door.backends_of(door, "zed") == [])

    # ---- 4. routing and the refusal texts
    async with fclient("bob") as c:
        ra, rb = json.loads(await call(c, "whoami", {"board": "a"})), json.loads(await call(c, "whoami", {"board": "b"}))
        check("routing: board=a reaches board a, board=b reaches board b", (ra["board"], rb["board"]) == ("a", "b"), (ra, rb))
        check("routing: the other arguments are passed on and `board` is not", await call(c, "brief", {"board": "b", "project": "p", "limit": 3}) == "board-b brief project='p' limit=3")
        check("routing: a structured result comes back as the board gave it", (await c.call_tool("get", {"id": "x1", "board": "a", "fields": ["f"]})).data == {"board": "a", "id": "x1", "fields": ["f"]})
        e = await refusal(c, "whoami"); check("refusal: on two boards, no board", e == "board required: you are on 2 boards (a, b); pass board='<name>' on this call.", e)
        e = await refusal(c, "whoami", {"board": "c"}); check("refusal: a board that exists but is not the caller's", e == "board 'c' is not one of your boards. You are on: a, b.", e)
        e = await refusal(c, "whoami", {"board": "zzz"}); check("refusal: an unknown board gets the same text", e == "board 'zzz' is not one of your boards. You are on: a, b.", e)
        e = await refusal(c, "whoami", {"board": ""}); check("refusal: an empty board counts as none", e == "board required: you are on 2 boards (a, b); pass board='<name>' on this call.", e)
        e = await refusal(c, "whoami", {"board": 7}); check("refusal: a board that is not text is refused in words (not a crash)", e is not None and "board" in e, e)
        check("refusal: the session is still usable after a refusal", json.loads(await call(c, "whoami", {"board": "b"}))["board"] == "b")
        e = await refusal(c, "refuse", {"board": "a"}); check("a board's own tool error reaches the client as the board wrote it", e == "the board says no, with its own words", e)
    async with fclient("alice") as c:
        check("routing: a member of one board needs no `board`", json.loads(await call(c, "whoami"))["board"] == "a")
        e = await refusal(c, "whoami", {"board": "b"}); check("refusal: board=b for a member of a only", e == "board 'b' is not one of your boards. You are on: a.", e)
        e = await refusal(c, "whoami", {"board": "zzz"}); check("refusal: an unknown board for a member of a only", e == "board 'zzz' is not one of your boards. You are on: a.", e)
        e = await refusal(c, "brief", {"board": "b"}); check("refusal: the refusal holds for every board tool", e == "board 'b' is not one of your boards. You are on: a.", e)
    async with fclient("carol") as c:
        e = await refusal(c, "whoami"); check("refusal: a call by a member of no board", e is not None and "you are not a member of any board." in e, e)
    async with fclient("dave") as c:
        check("routing: a member of board b and the brain needs no `board` for a board tool", json.loads(await call(c, "whoami"))["board"] == "b")
        check("routing: a brain tool goes to the brain", await call(c, "search", {"query": "q"}) == "hits for q")
        check("routing: a brain tool takes no board (and one is not passed on)", await call(c, "get_page", {"slug": "s"}) == "page s")
    async with fclient("fred") as c:
        e = await refusal(c, "whoami"); check("refusal: a member of the brain only has no board tool to call", e is not None, e)
        check("routing: a member of the brain only reaches it", await call(c, "get_page", {"slug": "s2"}) == "page s2")
    async with fclient("alice") as c:
        e = await refusal(c, "get_page", {"slug": "s"}); check("refusal: a brain tool for a caller who is not on the brain is not offered", e is not None and "not offered" in e or (e is not None and "not a member" in e), e)

    # ---- 5. the brain: a credential-limited list and the refusal that follows from it
    async with fclient("dave") as c:
        e = await refusal(c, "admin_stats")
        exp = "tool 'admin_stats' is not offered to this connection (its credential is limited to what the tool list shows; admin-scoped tools are not part of it)."
        check("brain: an admin tool is refused with the exact text", e == exp, e)
        e = await refusal(c, "admin_drop", {"slug": "x"}); check("brain: every admin tool is refused the same way", e == exp.replace("admin_stats", "admin_drop"), e)
        e = await refusal(c, "no_such_tool"); check("brain: a tool that does not exist at all is refused the same way", e == exp.replace("admin_stats", "no_such_tool"), e)
        check("brain: the session is usable after the refusals", await call(c, "search", {"query": "again"}) == "hits for again")
    grants = [g for g in OAUTH["granted"]]
    check("brain: the front door got its token by client credentials with the configured scopes", OAUTH["requests"] >= 1 and all(g[1] == ["read", "write"] for g in grants) and grants, (OAUTH, ))
    n_tok = OAUTH["requests"]
    async with fclient("dave") as c:
        for i in range(3): await call(c, "search", {"query": f"q{i}"})
    check("brain: the access token is kept (calls after the first ask for no new token)", OAUTH["requests"] == n_tok, (n_tok, OAUTH["requests"]))
    # the credential changes (admin client files): the next listing offers the admin tools and a call goes through: the refusal is the credential's, not a name list's
    secret_file("brain.cid", "cid-admin"); secret_file("brain.csec", "brain-secret-admin-0123456789")
    async with fclient("dave") as c:
        names = [t.name for t in await c.list_tools()]
        check("brain: a rotated credential applies at the next listing (no restart): the admin tools are now offered", set(ADMIN_TOOLS) <= set(names), names)
        check("brain: and a call of one goes through", await call(c, "admin_stats") == "stats")
    secret_file("brain.cid", "cid-rw"); secret_file("brain.csec", "brain-secret-rw-0123456789")
    async with fclient("dave") as c:
        names = [t.name for t in await c.list_tools()]
        e = await refusal(c, "admin_stats")
        check("brain: back on the read-and-write credential the admin tools are gone again and refused", not set(ADMIN_TOOLS) & set(names) and e is not None and "is not offered to this connection" in e, (names, e))

    # ---- 5b. a member removed from the members file is refused at the next call, on a session that already listed its tools
    members_path.write_text(json.dumps({**MEMBERS, "zoe": ["a", "brain"]}))
    async with fclient("zoe") as c:
        await c.list_tools()
        check("revocation: before the change zoe reaches her board and the brain", json.loads(await call(c, "whoami"))["board"] == "a" and await call(c, "search", {"query": "q"}) == "hits for q")
        members_path.write_text(json.dumps({**MEMBERS, "zoe": ["a"]}))
        e = await refusal(c, "search", {"query": "q"})
        check("revocation: removed from the brain only, the next brain call is refused as not offered (her board still works)", e is not None and "is not offered to this connection" in e and json.loads(await call(c, "whoami"))["board"] == "a", e)
        members_path.write_text(json.dumps(MEMBERS))
        e1, e2 = await refusal(c, "whoami"), await refusal(c, "search", {"query": "q"})
        check("revocation: removed from everything, the next call of either kind is refused as not a member", e1 == "you are not a member of any board." and e2 == "you are not a member of any board.", (e1, e2))
    members_path.write_text(json.dumps(MEMBERS))

    # ---- 6. 45 concurrent calls over 3 sessions
    def user_of(text): return ident.verify(IDENT_SECRET.encode(), json.loads(text)["identity"])
    async def one(c, user, board, expect):
        d = json.loads(await call(c, "whoami", {"board": board} if board else {}))
        return d["board"] == expect and ident.verify(IDENT_SECRET.encode(), d["identity"]) == user and d["authorization"] == "Bearer " + BOARD_TOK[expect]
    async with fclient("bob") as cb, fclient("alice") as ca, fclient("dave") as cd:
        jobs = []
        for i in range(15):
            jobs += [one(cb, "bob", "a", "a"), one(cb, "bob", "b", "b"), one(ca, "alice", None if i % 2 else "a", "a")]
        res = await asyncio.gather(*jobs, return_exceptions=True)
        check("concurrency: 45 calls over 3 sessions each reach the right board with the caller's own identity and the board's own credential", len(res) == 45 and all(r is True for r in res), [r for r in res if r is not True][:3])
        res = await asyncio.gather(*([one(cd, "dave", None, "b") for _ in range(8)] + [one(ca, "alice", "a", "a") for _ in range(8)] + [one(cb, "bob", "b", "b") for _ in range(8)]))
        check("concurrency: three more sessions' worth in parallel stay apart", all(res), res)

    # ---- 7. the caller's own credentials never reach a backend; the identity does
    rows = [r for r in RECORDS if r["path"].startswith("/mcp") and not r["direct"]]
    check("credentials: backends saw requests (the check is not empty)", len(rows) > 100, len(rows))
    check("credentials: 0 requests at any backend's door carried the caller's bearer, X-Api-Key or Cookie", not [r for r in RECORDS if r["caller_cred"]], [r for r in RECORDS if r["caller_cred"]][:2])
    check("credentials: none carried a Cookie or an X-Api-Key at all", not [r for r in RECORDS if r["cookie"] or r["apikey"]])
    check("credentials: every board request carried the front door's own bearer, in the lower-case `authorization` key",
          all(r["auth"] == "Bearer " + BOARD_TOK[r["backend"]] for r in rows if r["backend"] in "abc"), [r for r in rows if r["backend"] in "abc" and r["auth"] != "Bearer " + BOARD_TOK[r["backend"]]][:2])
    check("credentials: every board request carried a signed identity that verifies", all(ident.verify(IDENT_SECRET.encode(), r["identity"]) in MEMBERS for r in rows if r["backend"] in "abc"), [r["identity"] for r in rows if r["backend"] in "abc"][:2])
    check("credentials: the brain was called with its OAuth access token, never a caller's", all(r["auth"].startswith("Bearer TOK-") for r in rows if r["backend"] == "brain" and r["auth"]) and any(r["auth"] for r in rows if r["backend"] == "brain"))

    # ---- 7b. the headers a backend is given, as the front door builds them; the health cache
    from stackshot.frontdoor.backend import Backends
    hdr, auth = door.backends._headers(SETTINGS.backends[0], "alice")
    check("headers: the front door's own bearer is under the lower-case `authorization` key, alone (no capitalised twin)", hdr.get("authorization") == "Bearer " + BOARD_TOK["a"] and [k for k in hdr if k.lower() == "authorization"] == ["authorization"] and auth is None, hdr.keys())
    check("headers: the caller's identity is signed under the identity header", ident.verify(IDENT_SECRET.encode(), hdr.get(ident.HEADER)) == "alice")
    check("headers: only those two headers are set (nothing of the caller's request is copied)", sorted(hdr) == sorted(["authorization", ident.HEADER]), sorted(hdr))
    hdr, auth = door.backends._headers(SETTINGS.backends[3], "alice")
    check("headers: an OAuth backend gets its provider and no static authorization header", "authorization" not in hdr and auth is not None, (sorted(hdr), auth))
    cached = Backends(fc.parse(front_cfg(servers, health_cache_seconds=60))[0])
    n0 = len([r for r in RECORDS if r["backend"] == "a" and r["path"] == "/healthz"])
    await cached.health("a"); await cached.health("a"); n1 = len([r for r in RECORDS if r["backend"] == "a" and r["path"] == "/healthz"])
    await cached.health("a", force=True); n2 = len([r for r in RECORDS if r["backend"] == "a" and r["path"] == "/healthz"])
    check("health: an answer is reused inside health_cache_seconds (one GET for two checks) and a forced check asks again", (n1 - n0, n2 - n1) == (1, 1), (n0, n1, n2))

    # a backend that answers its health URL with a 5xx is reachable and not healthy: it is down for the front door
    import dataclasses, http.server, threading
    class Sick(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
        def log_message(self, *a): pass
    sick = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sick)
    threading.Thread(target=sick.serve_forever, daemon=True).start()
    try:
        st0 = fc.parse(front_cfg(servers))[0]
        st1 = dataclasses.replace(st0, backends=tuple(dataclasses.replace(b, health_url=f"http://127.0.0.1:{sick.server_address[1]}/healthz") if b.name == "a" else b for b in st0.backends))
        h = await Backends(st1).health("a")
        check("health: a backend that answers its health URL with 503 is not ok, and the status is reported", h["ok"] is False and h["status"] == 503, h)
    finally:
        sick.shutdown(); sick.server_close()

    # ---- 8. streaming: progress and log events reach the client while the call runs
    ev, logs = [], []
    async def prog(progress, total, message): ev.append(time.monotonic() - t0)
    async def lh(m): logs.append(time.monotonic() - t0)
    async with fclient("bob", log_handler=lh) as c:
        t0 = time.monotonic(); r = await c.call_tool("stream", {"seconds": 3.0, "interval": 0.6, "board": "b"}, progress_handler=prog); total = time.monotonic() - t0
    check("streaming: the call's result is the board's", r.content[0].text == "board-b streamed 5", r)
    check("streaming: 5 progress events arrived, the first long before the call ended and spread over its length", len(ev) == 5 and ev[0] < 1.4 and ev[-1] - ev[0] > 1.6 and ev[0] < total - 1.5, (ev, total))
    check("streaming: 5 log events arrived the same way", len(logs) == 5 and logs[0] < 1.4 and logs[-1] - logs[0] > 1.6, (logs, total))

    # ---- 9. instructions
    async with fclient("bob") as c: ins = c.initialize_result.instructions or ""
    check("instructions: the config's preface comes first", ins.startswith("TEST PREFACE: the front door."), ins[:120])
    check("instructions: each of the caller's boards' own text is in, verbatim", BOARD_TEXT["a"] in ins and BOARD_TEXT["b"] in ins, ins)
    check("instructions: a board the caller is not on is not in", "BRAIN INSTRUCTIONS" not in ins, ins)
    check("instructions: the text names the caller's backends and the board argument", "You are on: board a, board b." in ins and "`board`" in ins, ins)
    check("instructions: the block of each backend is headed with its name", "--- instructions of board a (verbatim) ---\n" + BOARD_TEXT["a"] in ins and "--- instructions of board b (verbatim) ---\n" + BOARD_TEXT["b"] in ins, ins)
    async with fclient("erin") as c: ins = c.initialize_result.instructions or ""
    check("instructions: two boards with the same text share one block, the text once", "--- instructions of boards a, c (the same text, verbatim) ---\n" + BOARD_TEXT["a"] in ins and ins.count(BOARD_TEXT["a"]) == 1, ins)
    async with fclient("gina") as c: ins = c.initialize_result.instructions or ""
    check("instructions: a caller on the brain gets its text verbatim as well", "--- instructions of brain brain (verbatim) ---\n" + BRAIN_TEXT in ins and BOARD_TEXT["b"] in ins, ins)
    async with fclient("carol") as c: ins = c.initialize_result.instructions or ""
    check("instructions: a caller on no board gets the preface alone", ins == "TEST PREFACE: the front door.", ins)
    check("instructions: kept five minutes", fdinstr.CACHE_SECONDS == 300.0)
    old = BOARD_TEXT["b"]
    async with fclient("bob") as c: ins2 = c.initialize_result.instructions or ""
    check("instructions: a second session inside the five minutes gets the stored text ", old in ins2 and door.instructions._cache["b"][1] == old, (ins2, door.instructions._cache.get("b")))
    door.instructions._cache["b"] = (time.monotonic() - 301, "STALE TEXT")
    async with fclient("bob") as c: ins3 = c.initialize_result.instructions or ""
    check("instructions: after five minutes the text is read live again (the stale copy is replaced)", "STALE TEXT" not in ins3 and old in ins3, ins3)

    # ---- 10. no caller, no identity
    check("no caller: the provider lists nothing when no request is in hand (the server's own start)", await fdprov.DoorProvider(door)._list_tools() == [])
    s, body = http_get(FRONT + "/mcp"); check("no identity: a request to /mcp without the identity header is refused 401", s == 401, (s, body))
    s, body = http_get(FRONT + "/mcp", {"authorization": "Bearer CALLER-x"}); check("no identity: the caller's own credential in place of the identity header gets no more", s == 401, (s, body))
    s, body = http_get(FRONT + "/mcp", {"X-Forwarded-User": "   "}); check("no identity: a blank identity header is refused 401", s == 401, (s, body))
    s, body = http_get(FRONT + "/healthz"); check("no identity: /healthz is open", s == 200, (s, body))
    s, body = http_get(FRONT + "/healthz"); h = json.loads(body)
    check("healthz: all up is 200 with an entry per backend", s == 200 and h["status"] == "ok" and set(h["backends"]) == {"a", "b", "c", "brain"} and all(v["ok"] and v["status"] == 200 for v in h["backends"].values()), (s, body))
    check("healthz: the identity header is not needed and not echoed", "X-Forwarded-User" not in body)

    # ---- 11. a backend that is down
    logw = []
    async def lw(m): logw.append(str(getattr(m, "data", m)))
    servers["b"].stop(); check("degraded: the stopped board's port is freed", port_free(servers["b"].port))
    async with fclient("bob", log_handler=lw) as c:
        names = [t.name for t in await c.list_tools()]
    check("degraded: the list of a caller on a and b still has the tools of a", sorted(names) == sorted(single), names)
    check("degraded: the stopped board is named in a warning to the client, and it is not silent", any("board 'b'" in w and "did not list" in w for w in logw), logw)
    async with fclient("bob") as c:
        e = await refusal(c, "brief", {"board": "b"}); check("degraded: a call to the stopped board says it did not answer", e == "board 'b' did not answer (unreachable). Other boards you are on are unaffected.", e)
        check("degraded: the other board still answers on the same session", (await call(c, "brief", {"board": "a"})).startswith("board-a"))
    e, names = await list_text("dave")
    check("degraded: a caller whose boards are all down gets none answered, but the brain is up so the list holds its tools", e is None and set(names) == {"get_page", "put_page", "search"}, (e, names))
    logw.clear()
    async with fclient("dave", log_handler=lw) as c:
        await c.list_tools(); rr = await refusal(c, "brief")
    check("degraded: dave's board call says unreachable", rr == "board 'b' did not answer (unreachable). Other boards you are on are unaffected.", rr)
    s, body = http_get(FRONT + "/healthz"); h = json.loads(body)
    check("healthz: one backend down is 503 with the per-backend status", s == 503 and h["status"] == "degraded" and h["backends"]["b"]["ok"] is False and h["backends"]["a"]["ok"] and "error" in h["backends"]["b"], (s, body))
    servers["a"].stop(); servers["c"].stop()
    members_path.write_text(json.dumps({**MEMBERS, "hank": ["b"], "ivy": ["a", "b"]}))
    e, names = await list_text("hank")
    check("degraded: every board of the caller down gives the none-answered text", e is not None and "none of your boards answered (b). Check /healthz." in e, (e, names))
    e, names = await list_text("ivy")
    check("degraded: and for two boards it names both", e is not None and "none of your boards answered (a, b). Check /healthz." in e, (e, names))
    async with fclient("alice") as c:
        e = await refusal(c, "brief"); check("degraded: a call to the only board, down, says it did not answer", e is not None and "board 'a' did not answer" in e, e)
    s, body = http_get(FRONT + "/healthz"); h = json.loads(body)
    check("healthz: 503 again with three down, the brain still ok", s == 503 and [k for k, v in h["backends"].items() if v["ok"]] == ["brain"], (s, body))
    members_path.write_text("{broken"); e, names = await list_text("bob")
    check("members: a members file that cannot be read makes nobody a member (never everybody)", e is not None and "you are not a member of any board." in e, (e, names))
    members_path.write_text(json.dumps(MEMBERS))

asyncio.run(main())

# ------------------------------------------------------------------------------------------------ 12. the entry point, as a subprocess (stopped by its PID)
def toml_for(servers_, port, members):
    rows = "\n".join(f'[[frontdoor.backends]]\nname = "{n}"\nurl = "{servers_[n].url}/mcp"\ntoken_file = "{board_tok_file[n]}"\n' for n in "ab")
    return (f'[frontdoor]\nlisten_port = {port}\nidentity_header = "X-Forwarded-User"\nidentity_secret_file = "{ident_file}"\nmembers_file = "{members}"\nhealth_cache_seconds = 0\n\n{rows}')
free = socket.socket(); free.bind(("127.0.0.1", 0)); eport = free.getsockname()[1]; free.close()
cfg_ok = T / "fd-ok.toml"; cfg_ok.write_text(toml_for(servers, eport, members_path))
cfg_bad = T / "fd-bad.toml"; cfg_bad.write_text('[frontdoor]\nidentity_header = "X-Forwarded-User"\n')
env = {**{k: v for k, v in os.environ.items() if not k.startswith("STACKSHOT_")}, "PYTHONPATH": STACK, "STACKSHOT_CONFIG": str(cfg_ok), "TMPDIR": tmp}
def run_main(*args, cfg=cfg_ok, timeout=60):
    return subprocess.run([sys.executable, "-m", "stackshot.frontdoor", *args], env={**env, "STACKSHOT_CONFIG": str(cfg)}, capture_output=True, text=True, timeout=timeout, cwd=tmp)
r = run_main("--check")
check("entry point: --check on a good config exits 0 and names the backends", r.returncode == 0 and "board a" in r.stdout and "board b" in r.stdout and f":{eport}" in r.stdout, (r.returncode, r.stdout, r.stderr[-300:]))
r = run_main("--check", cfg=cfg_bad)
check("entry point: a config that cannot start exits 2 and says why, with no secret in it", r.returncode == 2 and "does not start" in r.stderr and IDENT_SECRET not in r.stderr + r.stdout, (r.returncode, r.stderr[-400:]))
r = run_main("--serve-now")
check("entry point: an argument it does not know exits 2 with the usage", r.returncode == 2 and "usage" in r.stderr, (r.returncode, r.stderr))
proc = subprocess.Popen([sys.executable, "-m", "stackshot.frontdoor"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, cwd=tmp)
try:
    code = body = None
    for _ in range(100):
        if proc.poll() is not None: break
        try: code, body = http_get(f"http://127.0.0.1:{eport}/healthz"); break
        except (urllib.error.URLError, ConnectionError, OSError): time.sleep(0.2)
    check("entry point: `python -m stackshot.frontdoor` serves /healthz on its configured port (a is down, so 503; b is up)", code == 503 and json.loads(body)["backends"]["b"]["ok"] is False, (code, body, proc.poll()))
    code2, _ = http_get(f"http://127.0.0.1:{eport}/mcp") if proc.poll() is None else (None, None)
    check("entry point: and /mcp without the identity header is 401", code2 == 401, code2)
finally:
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(15)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(15)
check("entry point: the process ended when stopped by its PID and its port is free", proc.poll() is not None and port_free(eport), proc.poll())

# ------------------------------------------------------------------------------------------------ the end: every server stopped, every port freed
for s in SERVERS: s.stop()
check("cleanup: every stand-in port is freed", all(port_free(s.port) for s in SERVERS), [s.port for s in SERVERS if not port_free(s.port)])
check("cleanup: the stand-ins' threads ended", not [s for s in SERVERS if s.th.is_alive()])
print(("ok" if not fails else "FAILED") + f": front door scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
