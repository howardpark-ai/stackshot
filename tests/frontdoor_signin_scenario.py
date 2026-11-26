"""tests/frontdoor_signin_scenario.py: the sign-in service of the front door (`stackshot/frontdoor/signin.py`, config `core/frontdoor_signin_config.py`).

Offline and hermetic, one process: a stand-in board on a loopback port (it answers `GET /frontdoor/verify` as the real board's route does: it checks the signed header first and
answers 403 to a request that has none, then reads the bearer from a table), the service itself as an ASGI app called in this process, and one scratch folder (tests/_scratch.py).
No Caddy, no real board: `tests/frontdoor_signin_run_scenario.py` runs the real parts.

Covers:
  * the settings: every key read, each wrong value told in the config notes and read as its default, the keys the service cannot start without, the members file taken from `[frontdoor]`
    when the table names none, the notes reaching `core/config.notes`, `--check` and the exit codes of the start;
  * the answer: a member's token is 200 with the one header `X-Verified-User` holding the member's key; the address is lower-cased; a second address or an alias of the same person gives the
    same key; an address no member holds goes on as the identity (lower case) and is not refused; the answer has no body and is not cacheable;
  * membership is the service's own check: whatever else a board's 200 says, the identity comes from the members file, and an address that is no member's sign-in address but is written as a
    key of the file is 403 with no identity, never passed on as that member;
  * the start is refused when the verify secret is the same file as an identity secret the config names (links resolved) or holds the same value, when one of them cannot be read or none is
    named, with `--check` and without;
  * a request with no bearer, another scheme, an empty or an over-long one, or a token the board refuses is 401, with the board's own WWW-Authenticate text passed on word for word (and none
    when the board sent none); the board's 401 never carries an identity, whatever its body says;
  * fail closed: the board's 403, 404, 400, 429, any 5xx (and a bearer that is not ASCII is no bearer: it is never sent), a redirect, a body that is no JSON, names no address or a bad one, an answer that never ends or arrives a byte at a time (a total
    deadline), a board that cannot be reached, a secret that is missing, loose or short, a members file that cannot be read, an identity that cannot be put in a header, a board that accepts a
    request with no token: each is 503 with no identity header, never 200 and never 401, and it is not remembered;
  * the cache: a 200 of the board is reused for `cache_seconds` under a hash of the token and not longer; another token (even one sharing a long prefix) is never served from it; a refusal
    and a failure are never kept; it is bounded; `cache_seconds = 0` turns it off; an unreadable secret or members file is an outage with a token in the cache too;
  * what is sent to the board: the caller's bearer as it came, a header signed with the secret read now (a rotated secret applies to the next request), nothing else of the caller's request;
  * what is never echoed: an identity header the client sends (of any of the names in use) is not the answer's, nor any other header of the request; no token, secret or address is in the log.

    tests/run-suite frontdoor_signin       -> exit 0 / 1"""
import asyncio, hashlib, json, logging, os, pathlib, re, socket, subprocess, sys, tempfile, threading, time, tomllib, traceback
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch

import httpx
from stackshot.core import behind_door as door, config as cfgmod, frontdoor_files as ffiles, frontdoor_identity as ident, frontdoor_signin_config as sc
from stackshot.frontdoor import signin

tmp = _scratch.mkdtemp(prefix="signin-"); T = pathlib.Path(tmp)
fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""), flush=True)


# ------------------------------------------------------------------------------------------------ files
def secret_file(name, value, mode=0o600):
    p = T / name
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.chmod(p, mode)
    return str(p)


SECRET, NEW_SECRET = "verify-secret-0123456789abcdef", "rotated-secret-0123456789abcdef"
SFILE = secret_file("verify.key", SECRET)
IDENTITY = "identity-secret-0123456789abcdef"      # the secret the front door signs a caller's identity with: never the verify secret
IFILE = secret_file("identity.key", IDENTITY)
MEMBERS = T / "members.json"
KEY_A, KEY_B, KEY_D, KEY_E = "alice@example.invalid", "bob@example.invalid", "dana", "café@example.invalid"
MEMBER_RECORDS = {
    KEY_A: {"boards": ["main", "side"], "emails": ["alice@example.invalid", "Alice.Alt@Example.Invalid"]},         # one person, two addresses (one written in mixed case)
    KEY_D: {"boards": ["main"], "aliases": ["DD"], "emails": ["dana.one@example.invalid", "dana.two@example.invalid"]},     # a member named by a plain name
    KEY_B: ["side"],                                                                                                 # the older list form: the key is the one address
    KEY_E: {"boards": ["main"], "emails": ["cafe.person@example.invalid"]},                                          # a key that cannot be a header value
}
MEMBERS.write_text(json.dumps(MEMBER_RECORDS))
BOARD_WWW = 'Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://board.example.invalid/.well-known/oauth-protected-resource/mcp"'

LOGS: list[str] = []


class Capture(logging.Handler):
    def emit(self, record):
        LOGS.append(record.getMessage())


for name in ("", "stackshot.frontdoor.signin"):
    lg = logging.getLogger(name); lg.setLevel(logging.INFO); lg.addHandler(Capture())


# ------------------------------------------------------------------------------------------------ the stand-in board
class Board:
    """GET /frontdoor/verify as a board answers it: a request without the signed header is 403 whatever its bearer; with it, the bearer is looked up in `rules`
    ({token: (status, headers, body)}); a token that is not in the table is 401 with `www`. `mode` makes it hang, drip an answer or redirect."""
    def __init__(self):
        self.secret = SECRET; self.rules = {}; self.seen = []; self.mode = None; self.www = BOARD_WWW
        board = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a): pass

            def do_GET(self):
                v = self.headers.get(door.VERIFY_HEADER)
                auth = self.headers.get("Authorization")
                board.seen.append({"path": self.path, "auth": auth, "verify": v, "sig_ok": ident.verify(board.secret.encode(), v) == door.VERIFY_WHO, "headers": {k.lower(): x for k, x in self.headers.items()}})
                if board.mode == "hang":
                    time.sleep(4)
                if board.mode == "drip":
                    self.send_response(200); self.send_header("Content-Length", "400"); self.end_headers()
                    for _ in range(40):
                        try:
                            self.wfile.write(b" "); self.wfile.flush()
                        except OSError:
                            return
                        time.sleep(0.1)
                    return
                if board.mode == "open":
                    self.reply(200, {}, json.dumps({"email": "alice@example.invalid"}).encode()); return
                if board.mode == "redirect":
                    self.send_response(302); self.send_header("Location", "http://127.0.0.1:1/x"); self.send_header("Content-Length", "0"); self.end_headers(); return
                if not board.seen[-1]["sig_ok"]:
                    self.reply(403, {}, b"refused: the signed header of this request is not accepted"); return
                token = auth.split(" ", 1)[1] if auth and auth.lower().startswith("bearer ") else ""
                rule = board.rules.get(token) if token else None
                if rule is None:
                    self.reply(401, {"WWW-Authenticate": board.www} if board.www else {}, b'{"error": "invalid_token"}'); return
                status, hdrs, body = rule
                self.reply(status, hdrs, body)

            def reply(self, status, hdrs, body):
                self.send_response(status)
                for k, x in hdrs.items():
                    self.send_header(k, x)
                self.send_header("Content-Length", str(len(body))); self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:      # the service gave up on a slow answer
                    pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/frontdoor/verify"
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True); self.th.start()

    def stop(self):
        self.srv.shutdown(); self.srv.server_close(); self.th.join(10)

    def accept(self, token, email, **extra):
        self.rules[token] = (200, {}, json.dumps({"email": email, "via": "google", **extra}).encode())

    def calls(self):
        return len(self.seen)


class Rig:
    """The service as an ASGI app, called in this process: `await rig.get(token)`."""
    def __init__(self, board, **kw):
        base = {"board_verify_url": board.url, "verify_secret_file": SFILE, "members_file": str(MEMBERS), "timeout_seconds": 1.5, "cache_seconds": 5.0}
        self.settings = replace(sc.parse({})[0], present=True, port=1, **{**base, **kw})
        self.app, self.svc = signin.build(self.settings)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://signin.invalid")

    async def get(self, token=None, scheme="Bearer", extra=None, path="/verify", method="GET"):
        h = dict(extra or {})
        if token is not None:
            h["Authorization"] = f"{scheme} {token}"
        return await self.http.request(method, path, headers=h)

    async def close(self):
        await self.http.aclose(); await self.svc.aclose()


def who(r):
    return r.headers.get("x-verified-user")


TOKENS = set()


def tok(name):
    t = f"tok-{name}-" + hashlib.sha256(name.encode()).hexdigest()[:24]
    TOKENS.add(t)
    return t




# ------------------------------------------------------------------------------------------------ 1. the settings
def settings_part():
    s, n = sc.parse({})
    check("settings: no table is not present and says nothing", s == sc.Settings(present=False) and n == [] and sc.notes({}) == [] and sc.blocking(s) == ["the config has no [frontdoor_signin] table"], (s, n))
    cfg = {"frontdoor_signin": {"listen_port": 8123, "board_verify_url": " http://127.0.0.1:8010/frontdoor/verify ", "verify_secret_file": SFILE, "members_file": str(MEMBERS),
                                "identity_secret_file": IFILE, "timeout_seconds": 2.5, "cache_seconds": 7}}
    s, n = sc.parse(cfg)
    check("settings: every key is read (the URL trimmed), and a good table gives no note", (s.port, s.board_verify_url, s.verify_secret_file, s.members_file, s.identity_secret_files, s.timeout_seconds, s.cache_seconds, n, sc.blocking(s))
          == (8123, "http://127.0.0.1:8010/frontdoor/verify", SFILE, str(MEMBERS), (IFILE,), 2.5, 7.0, [], []), (s, n))
    s, n = sc.parse({"frontdoor_signin": {"board_verify_url": "http://127.0.0.1:1/v", "verify_secret_file": SFILE}, "frontdoor": {"members_file": "/the/door/members.json", "identity_secret_file": "/the/door/identity.key"}})
    check("settings: the front door's members_file and identity_secret_file are the defaults, with no note and the defaults of the rest",
          s.members_file == "/the/door/members.json" and s.identity_secret_files == ("/the/door/identity.key",) and (s.port, s.timeout_seconds, s.cache_seconds) == (8021, 5.0, 5.0) and n == [], (s, n))
    three = {"frontdoor_signin": {"board_verify_url": "http://127.0.0.1:1/v", "verify_secret_file": SFILE, "members_file": "/m", "identity_secret_file": "/own.key"},
             "frontdoor": {"identity_secret_file": "/door.key"}, "behind_frontdoor": {"identity_secret_file": "/board.key"}}
    s, _ = sc.parse(three)
    check("settings: every identity secret the config names is kept for the comparison (its own, the front door's, a board's)", s.identity_secret_files == ("/own.key", "/door.key", "/board.key"), s)
    s, _ = sc.parse({**three, "frontdoor": {"identity_secret_file": "/own.key"}, "behind_frontdoor": {}})
    check("settings: ... one path named twice is kept once", s.identity_secret_files == ("/own.key",), s)
    s, n = sc.parse({"frontdoor_signin": {"board_verify_url": "http://127.0.0.1:1/v", "verify_secret_file": SFILE, "members_file": "/own.json"}, "frontdoor": {"members_file": "/the/door.json"}})
    check("settings: its own members_file wins over the front door's", s.members_file == "/own.json", s)
    s, n = sc.parse({"frontdoor_signin": {}})
    check("settings: an empty table cannot start and names each missing key", sc.blocking(s) == ["no usable board_verify_url", "no verify_secret_file", "no members_file", "no identity_secret_file"] and len(n) == 4, (s, n, sc.blocking(s)))
    s, n = sc.parse({"frontdoor_signin": 3})
    check("settings: a table that is no table is present, cannot start and says so", s.present and sc.blocking(s) and any("is not a table" in x for x in n), (s, n))
    ok = {"board_verify_url": "http://127.0.0.1:1/v", "verify_secret_file": SFILE, "members_file": "/m", "identity_secret_file": IFILE}
    for label, extra, want in (("a url with no host", {"board_verify_url": "http:///v"}, "board_verify_url is not an http(s) URL"),
                               ("a url with a password", {"board_verify_url": "http://u:p@127.0.0.1/v"}, "board_verify_url is not an http(s) URL"),
                               ("a url that is no url", {"board_verify_url": 5}, "board_verify_url is not an http(s) URL"),
                               ("a url with a fragment", {"board_verify_url": "http://127.0.0.1/v#x"}, "board_verify_url is not an http(s) URL"),
                               ("a url that is not on the loopback address", {"board_verify_url": "http://board.example.invalid/v"}, "not the loopback address"),
                               ("a port of 0", {"listen_port": 0}, "listen_port"), ("a port that is a string", {"listen_port": "8021"}, "listen_port"), ("a port of 70000", {"listen_port": 70000}, "listen_port"),
                               ("a listen_host", {"listen_host": "0.0.0.0"}, "listen_host is not a key"),
                               ("a timeout of 0", {"timeout_seconds": 0}, "timeout_seconds"), ("a timeout of 61", {"timeout_seconds": 61}, "timeout_seconds"), ("a timeout that is a string", {"timeout_seconds": "5"}, "timeout_seconds"),
                               ("a cache time of -1", {"cache_seconds": -1}, "cache_seconds"), ("a cache time of 61", {"cache_seconds": 61}, "cache_seconds"), ("a cache time that is true", {"cache_seconds": True}, "cache_seconds"),
                               ("a members_file that is no path", {"members_file": 5}, "members_file is not a path"), ("an identity_secret_file that is no path", {"identity_secret_file": 5}, "identity_secret_file is not a path")):
        _, n = sc.parse({"frontdoor_signin": {**ok, **extra}})
        check(f"settings note: {label} is named", any(want in x for x in n), n)
        check(f"settings note: {label} reaches core/config.notes", any(want in x for x in cfgmod.notes({"frontdoor_signin": {**ok, **extra}})), None)
    s, _ = sc.parse({"frontdoor_signin": {**ok, "timeout_seconds": 0, "cache_seconds": 99, "listen_port": 0}})
    check("settings: a refused number reads as its default", (s.timeout_seconds, s.cache_seconds, s.port) == (5.0, 5.0, 8021), s)
    s, n = sc.parse({"frontdoor_signin": {**ok, "cache_seconds": 0, "timeout_seconds": 60}})
    check("settings: 0 cache seconds (off) and 60 timeout seconds are the edges, taken as written", (s.cache_seconds, s.timeout_seconds, n) == (0.0, 60.0, []), (s, n))
    loose = secret_file("loose.key", "loose-secret-0123456789abcdef", 0o644)
    _, n = sc.parse({"frontdoor_signin": {**ok, "verify_secret_file": loose}})
    check("settings note: a secret file group or others can read is named", any("verify_secret_file" in x and loose in x for x in n), n)
    check("settings: the notes name no secret", all(SECRET not in x for x in n))
    _, n = sc.parse({"frontdoor_signin": {**ok, "board_verify_url": "https://board.example.invalid/v"}})
    check("settings note: a remote https board is named without 'clear text'", any("not the loopback address" in x and "clear text" not in x for x in n), n)


# ------------------------------------------------------------------------------------------------ 2. the answer
async def answer_part(board):
    r = Rig(board)
    try:
        board.accept(tok("alice"), "alice@example.invalid"); board.accept(tok("alice-upper"), "ALICE@Example.INVALID"); board.accept(tok("alice-alt"), "Alice.Alt@Example.Invalid")
        board.accept(tok("dana"), "Dana.Two@Example.Invalid"); board.accept(tok("bob"), "bob@example.invalid"); board.accept(tok("stranger"), "Stranger@Example.Invalid")
        board.accept(tok("cafe"), "cafe.person@example.invalid"); board.accept(tok("carol"), "Carol@Example.Invalid", via="portal")
        n0 = board.calls()
        x = await r.get(tok("alice"))
        check("answer: a member's token is 200 with the member's key in X-Verified-User and nothing else", x.status_code == 200 and who(x) == KEY_A and x.content == b"" and "www-authenticate" not in x.headers, (x.status_code, dict(x.headers)))
        check("answer: the answer is not cacheable", x.headers.get("cache-control") == "no-store", dict(x.headers))
        check("answer: the board was asked once, at the check's own path, with the bearer exactly as it came and a header signed for it",
              board.calls() == n0 + 1 and board.seen[-1]["path"] == "/frontdoor/verify" and board.seen[-1]["auth"] == "Bearer " + tok("alice") and board.seen[-1]["sig_ok"], board.seen[-1])
        x = await r.get(tok("alice-upper"))
        check("answer: an address in capitals is the same person (case-folded)", x.status_code == 200 and who(x) == KEY_A, (x.status_code, who(x)))
        x = await r.get(tok("alice-alt"))
        check("answer: a second address of the same person (written in mixed case in the file) is the same member key", x.status_code == 200 and who(x) == KEY_A, (x.status_code, who(x)))
        x = await r.get(tok("dana"))
        check("answer: a member named by a plain name is answered by that name, whichever of her addresses signed in", x.status_code == 200 and who(x) == KEY_D, (x.status_code, who(x)))
        x = await r.get(tok("bob"))
        check("answer: a member in the older list form (the key is the address) is answered by the key", x.status_code == 200 and who(x) == KEY_B, (x.status_code, who(x)))
        x = await r.get(tok("stranger"))
        check("answer: an address no member holds is not refused: it goes on as the identity, in lower case", x.status_code == 200 and who(x) == "stranger@example.invalid", (x.status_code, who(x)))
        x = await r.get(tok("carol"))
        check("answer: the board's `via` makes no difference, and a person no member holds is passed on in lower case", x.status_code == 200 and who(x) == "carol@example.invalid", (x.status_code, who(x)))
        x = await r.get(tok("cafe"))
        check("answer: a member key that cannot be a header value (not ASCII) is an outage, never a 200", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        for scheme in ("bearer", "BEARER"):
            x = await r.get(tok("alice"), scheme=scheme)
            check(f"answer: the scheme word is read without regard to case ({scheme})", x.status_code == 200 and who(x) == KEY_A, (x.status_code, who(x)))
        # a person removed from the members file is passed on as an address (the file is read at each request, the cache or not)
        MEMBERS.write_text(json.dumps({KEY_B: ["side"]}))
        x = await r.get(tok("alice"))
        check("answer: the members file is read at each request: a member taken out of it (and cached) is passed on as her address", x.status_code == 200 and who(x) == "alice@example.invalid", (x.status_code, who(x)))
        MEMBERS.write_text(json.dumps({KEY_A: {"boards": ["main"], "emails": ["alice@example.invalid"]}}))
        x = await r.get(tok("alice"))
        check("answer: ... and one put back is her key again", x.status_code == 200 and who(x) == KEY_A, (x.status_code, who(x)))
        MEMBERS.write_text(json.dumps(MEMBER_RECORDS))
        # a key written with a stray space or capital letters does not change the answer's case: the key is the file's
        MEMBERS.write_text(json.dumps({"Alice@Example.Invalid": {"boards": ["main"]}}))
        x = await r.get(tok("alice"))
        check("answer: a key written in capitals that is its own address is answered as the file writes it", x.status_code == 200 and who(x) == "Alice@Example.Invalid", (x.status_code, who(x)))
        MEMBERS.write_text(json.dumps(MEMBER_RECORDS))
        # a 200 of the board is authentication, never membership: the service decides that from the members file
        board.accept(tok("claims"), "stranger@example.invalid", member=True, identity=KEY_A, user=KEY_A, boards=["main"])
        x = await r.get(tok("claims"))
        check("membership: what else a board's 200 says changes nothing: the identity comes from the members file", x.status_code == 200 and who(x) == "stranger@example.invalid", (x.status_code, who(x)))
        old = "pat@old.example.invalid"
        board.accept(tok("pat-old"), "Pat@Old.Example.Invalid"); board.accept(tok("pat-new"), "pat@new.example.invalid")
        MEMBERS.write_text(json.dumps({old: {"boards": ["main"], "emails": ["pat@new.example.invalid"]}}))
        x = await r.get(tok("pat-new"))
        check("membership: a member written as an old address is answered by that key for the address her emails hold", x.status_code == 200 and who(x) == old, (x.status_code, who(x)))
        x = await r.get(tok("pat-old"))
        check("membership: an address that is no member's sign-in address and is written as a member's key is 403 with no identity, never passed on as that member",
              x.status_code == 403 and who(x) is None and "www-authenticate" not in x.headers and x.headers.get("cache-control") == "no-store" and "@" not in x.text and "not passed on" in x.text, (x.status_code, dict(x.headers), x.text))
        MEMBERS.write_text(json.dumps({old: {"boards": ["main"], "emails": [old, "pat@new.example.invalid"]}}))
        x = await r.get(tok("pat-old"))
        check("membership: ... that refusal is not remembered: with the address among her emails the next request is hers", x.status_code == 200 and who(x) == old, (x.status_code, who(x)))
        MEMBERS.write_text(json.dumps({"Quinn@Example.Invalid": {"boards": ["main"], "emails": ["quinn@new.example.invalid"]}, "quinn@example.invalid": ["side"]}))
        board.accept(tok("quinn"), "quinn@example.invalid")
        x = await r.get(tok("quinn"))
        check("membership: an address written as a key that is dropped as another key's other case is 403 too (the front door still looks it up)", x.status_code == 403 and who(x) is None, (x.status_code, dict(x.headers)))
        MEMBERS.write_text(json.dumps(MEMBER_RECORDS))
        x = await r.get(tok("alice"), method="POST")
        check("answer: only GET is answered (POST is 405)", x.status_code == 405 and who(x) is None, x.status_code)
        x = await r.get(tok("alice"), path="/other")
        check("answer: another path is 404", x.status_code == 404 and who(x) is None, x.status_code)
    finally:
        await r.close()


# ------------------------------------------------------------------------------------------------ 3. 401, passed on
async def refusal_part(board):
    r = Rig(board)
    try:
        n0 = board.calls()
        x = await r.get()
        check("401: no Authorization header is 401 with the board's own WWW-Authenticate text, word for word, and no identity", x.status_code == 401 and x.headers.get("www-authenticate") == BOARD_WWW and who(x) is None, (x.status_code, dict(x.headers)))
        check("401: ... the board was asked once (to take its text), with no bearer, and its answer holds the invalid_token error only", board.calls() == n0 + 1 and board.seen[-1]["auth"] is None and board.seen[-1]["sig_ok"] and x.json() == {"error": "invalid_token"}, (board.seen[-1], x.text))
        check("401: the answer is not cacheable", x.headers.get("cache-control") == "no-store", dict(x.headers))
        x = await r.get(tok("unknown"))
        check("401: a token the board does not know is 401 with the board's text, and the board saw the bearer", x.status_code == 401 and x.headers.get("www-authenticate") == BOARD_WWW and who(x) is None and board.seen[-1]["auth"] == "Bearer " + tok("unknown"), (x.status_code, dict(x.headers)))
        for label, kw in (("a Basic header", {"token": "Zm9vOmJhcg==", "scheme": "Basic"}), ("an empty bearer", {"token": "", "scheme": "Bearer"}), ("a token that is too long", {"token": "x" * 5000}),
                          ("a token with a control character", {"token": "ab\tcd"}), ("a token with a space", {"token": "ab cd"}), ("a token that is not ASCII", {"token": "töken"})):
            n0 = board.calls()
            try:
                x = await r.get(**kw)
            except Exception as e:      # noqa: BLE001  (a header the client library will not write is not a request)
                check(f"401: {label} reaches no service (the client refuses to write it: {type(e).__name__})", True); continue
            check(f"401: {label} is treated as no bearer: 401 with the board's text, and the board saw no Authorization", x.status_code == 401 and x.headers.get("www-authenticate") == BOARD_WWW and who(x) is None
                  and board.calls() == n0 + 1 and board.seen[-1]["auth"] is None, (x.status_code, dict(x.headers), board.seen[-1]["auth"]))
        board.www = ""
        x = await r.get(tok("unknown"))
        check("401: a board's 401 with no WWW-Authenticate gives a 401 with none (nothing is made up here)", x.status_code == 401 and "www-authenticate" not in x.headers and who(x) is None, (x.status_code, dict(x.headers)))
        board.www = 'Bearer realm="x"\r\nSet-Cookie: a=b'.replace("\r\n", " ") + "\x01"
        x = await r.get(tok("unknown"))
        check("401: a WWW-Authenticate text with a control character is not passed on", x.status_code == 401 and "www-authenticate" not in x.headers, dict(x.headers))
        board.www = "Bearer " + "a" * 3000
        x = await r.get(tok("unknown"))
        check("401: an over-long WWW-Authenticate text is not passed on", x.status_code == 401 and "www-authenticate" not in x.headers, dict(x.headers))
        board.www = BOARD_WWW
        board.rules[tok("evil-401")] = (401, {"WWW-Authenticate": BOARD_WWW}, json.dumps({"email": "alice@example.invalid"}).encode())
        x = await r.get(tok("evil-401"))
        check("401: a 401 whose body names an address never carries an identity", x.status_code == 401 and who(x) is None, (x.status_code, dict(x.headers)))
        board.www = 'Bearer resource_metadata="https://another.example.invalid/x"'
        x = await r.get()
        check("401: the text is the board's at that moment, not one held here (a changed text is passed on)", x.headers.get("www-authenticate") == board.www, dict(x.headers))
        board.www = BOARD_WWW
    finally:
        await r.close()


# ------------------------------------------------------------------------------------------------ 4. fail closed
async def outage_part(board):
    r = Rig(board)
    try:
        for status in (400, 403, 404, 429, 500, 501, 502, 503, 504, 599, 301):
            for body in (b"", json.dumps({"email": "alice@example.invalid"}).encode()):
                t = tok(f"s{status}{len(body)}")
                board.rules[t] = (status, {"Location": "http://127.0.0.1:1/"} if status == 301 else {"WWW-Authenticate": BOARD_WWW} if status >= 500 else {}, body)
                x = await r.get(t)
                check(f"fail closed: the board's {status}{' with an address in its body' if body else ''} is 503, no identity, no WWW-Authenticate, never 200 or 401",
                      x.status_code == 503 and who(x) is None and "www-authenticate" not in x.headers and x.headers.get("cache-control") == "no-store", (x.status_code, dict(x.headers)))
        for label, body in (("a body that is no JSON", b"<html>not json</html>"), ("JSON that is a list", b"[1,2]"), ("JSON with no email", b'{"via": "google"}'), ("an email that is a number", b'{"email": 5}'),
                            ("an empty email", b'{"email": ""}'), ("a blank email", b'{"email": "   "}'), ("an email with no @", b'{"email": "alice"}'), ("an email with a space inside", b'{"email": "al ice@example.invalid"}'),
                            ("an email with a control character", b'{"email": "alice\\n@example.invalid"}'), ("an over-long email", json.dumps({"email": "a" * 300 + "@example.invalid"}).encode()),
                            ("an empty body", b"")):
            t = tok("body-" + re.sub(r"[^a-z]+", "-", label))
            board.rules[t] = (200, {}, body)
            x = await r.get(t)
            check(f"fail closed: a 200 with {label} is 503, never 200", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        # a bearer that is not ASCII is no bearer: it is refused here and never sent, whatever a board's token check would answer to it
        x = await r.http.request("GET", "/verify", headers={"Authorization": b"Bearer t\xc3\xb6ken-0123456789"})
        check("5xx: a bearer that is not ASCII, sent as bytes, is refused with no identity and is never sent to the board", x.status_code == 401 and who(x) is None and board.seen[-1]["auth"] is None, (x.status_code, dict(x.headers), board.seen[-1]["auth"]))
        # the board refusing the signed header (a secret that differs): the board's 403 is an outage, and says nothing of the token
        board.secret = NEW_SECRET
        t = tok("alice"); board.accept(t, "alice@example.invalid")
        x = await r.get(t)
        check("fail closed: a board that holds another secret (it answers 403 to the signed header) is 503", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        x = await r.get()
        check("fail closed: ... and a request with no token is 503 then too, not a 401 the board did not give", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        board.secret = SECRET
        # a board that accepts a check which carries no token is not trusted
        board.mode = "open"
        x = await r.get()
        check("fail closed: a board that answers 200 to a check with no token does not make a request with no token a member's", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        board.mode = None
        # timeouts and unreachable
        board.mode = "hang"
        t0 = time.monotonic(); x = await r.get(tok("alice")); dt = time.monotonic() - t0
        check("fail closed: a board that never answers is 503 within the timeout (1.5 s), not held for the board's 4 s", x.status_code == 503 and who(x) is None and dt < 3.0, (x.status_code, dt))
        board.mode = "drip"
        t0 = time.monotonic(); x = await r.get(tok("alice")); dt = time.monotonic() - t0
        check("fail closed: a board that answers a byte at a time is given up on at the total deadline, not at each read", x.status_code == 503 and who(x) is None and dt < 3.0, (x.status_code, dt))
        board.mode = "redirect"
        x = await r.get(tok("alice"))
        check("fail closed: a redirect is not followed and is 503", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
        board.mode = None
        x = await r.get(tok("alice"))
        check("fail closed: and the next request after those is served (nothing is remembered of a failure)", x.status_code == 200 and who(x) == KEY_A, (x.status_code, dict(x.headers)))
    finally:
        await r.close()
    dead = Board(); url = dead.url; dead.stop()
    r = Rig(board, board_verify_url=url)
    try:
        x = await r.get(tok("alice"))
        check("fail closed: a board that cannot be reached is 503, never 401", x.status_code == 503 and who(x) is None and "www-authenticate" not in x.headers, (x.status_code, dict(x.headers)))
        x = await r.get()
        check("fail closed: ... a request with no token too", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
    finally:
        await r.close()


async def files_part(board):
    t = tok("alice"); board.accept(t, "alice@example.invalid")
    for label, path in (("missing", str(T / "no-such.key")), ("readable by others", secret_file("g.key", "group-secret-0123456789abcdef", 0o644)), ("too short", secret_file("short.key", "short")),
                        ("empty", secret_file("empty.key", "")), ("a directory", str(T))):
        r = Rig(board, verify_secret_file=path)
        try:
            n0 = board.calls()
            x = await r.get(t); y = await r.get()
            check(f"fail closed: a verify secret that is {label} is 503 for a token and for none, and the board is not asked", x.status_code == 503 and y.status_code == 503 and who(x) is None and who(y) is None and board.calls() == n0, (x.status_code, y.status_code))
            h = await r.get(path="/healthz")
            check(f"fail closed: a verify secret that is {label} makes /healthz 503", h.status_code == 503 and h.json() == {"status": "degraded"}, (h.status_code, h.text))
        finally:
            await r.close()
    for label, write in (("missing", None), ("not JSON", "{broken"), ("a list", "[1]")):
        p = T / "m2.json"
        if write is not None:
            p.write_text(write)
        elif p.exists():
            p.unlink()
        r = Rig(board, members_file=str(p))
        try:
            x = await r.get(t)
            check(f"fail closed: a members file that is {label} is 503 (an address is never passed on past a file that cannot be read)", x.status_code == 503 and who(x) is None, (x.status_code, dict(x.headers)))
            y = await r.get()
            check(f"fail closed: ... but a request with no token is still the board's 401 (the file is not needed to refuse it)", y.status_code == 401 and who(y) is None, y.status_code)
            h = await r.get(path="/healthz")
            check(f"fail closed: a members file that is {label} makes /healthz 503", h.status_code == 503, h.status_code)
        finally:
            await r.close()
    r = Rig(board)
    try:
        h = await r.get(path="/healthz"); n0 = board.calls()
        check("healthz: 200 when the secret and the members file can be read", h.status_code == 200 and h.json() == {"status": "ok"} and board.calls() == n0, (h.status_code, h.text))
    finally:
        await r.close()
    # a secret that becomes unreadable while the service runs, with the token in the cache
    r = Rig(board, verify_secret_file=secret_file("flip.key", SECRET))
    try:
        x = await r.get(t)
        os.chmod(T / "flip.key", 0o644)
        n0 = board.calls(); y = await r.get(t)
        check("fail closed: a token in the cache is still an outage when the secret can no longer be read, and the board is not asked", x.status_code == 200 and y.status_code == 503 and who(y) is None and board.calls() == n0, (x.status_code, y.status_code))
        os.chmod(T / "flip.key", 0o600)
        y = await r.get(t)
        check("fail closed: ... and served again when it can", y.status_code == 200 and who(y) == KEY_A, y.status_code)
    finally:
        await r.close()
    # a rotated secret applies at the next request: the board holds the new one first (403 to the old), then the file does
    r = Rig(board, verify_secret_file=secret_file("rot.key", SECRET), cache_seconds=0)
    try:
        board.secret = NEW_SECRET
        x = await r.get(t)
        secret_file("rot.key", NEW_SECRET)
        y = await r.get(t)
        check("secret: a rotated secret applies to the next request: refused (503) while the files differ, served when they agree, with no restart", x.status_code == 503 and y.status_code == 200 and who(y) == KEY_A, (x.status_code, y.status_code))
        board.secret = SECRET
    finally:
        await r.close()


# ------------------------------------------------------------------------------------------------ 5. the cache
async def cache_part(board):
    A, B = tok("shared-prefix-0123456789-A"), tok("shared-prefix-0123456789-B")
    board.accept(A, "alice@example.invalid")
    now = [1000.0]
    signin.CLOCK = lambda: now[0]
    r = Rig(board, cache_seconds=5.0)
    try:
        n0 = board.calls()
        x = await r.get(A); y = await r.get(A)
        check("cache: the same token twice asks the board once and is 200 both times with the same member", x.status_code == y.status_code == 200 and who(x) == who(y) == KEY_A and board.calls() == n0 + 1, (board.calls() - n0, who(x), who(y)))
        now[0] += 4.9
        z = await r.get(A)
        check("cache: ... still reused 4.9 s later (window 5 s)", z.status_code == 200 and board.calls() == n0 + 1, board.calls() - n0)
        now[0] += 0.2
        z = await r.get(A)
        check("cache: ... asked again after the window", z.status_code == 200 and board.calls() == n0 + 2, board.calls() - n0)
        keys = list(r.svc.cache)
        check("cache: an entry is keyed by the SHA-256 of the token: the token is in no key", keys == [hashlib.sha256(A.encode()).hexdigest()] and all(A not in k for k in keys), keys)
        # a token the board refuses is never served from another's entry, even one that shares a long prefix with it
        x = await r.get(B)
        check("cache: another token (sharing a long prefix) is not served from the first's entry: the board refuses it (401)", x.status_code == 401 and who(x) is None, (x.status_code, dict(x.headers)))
        # a refusal is not remembered: the board accepts B a moment later
        board.accept(B, "dana.one@example.invalid")
        y = await r.get(B)
        check("cache: a refusal is never remembered: the same token accepted by the board a moment later is 200", y.status_code == 200 and who(y) == KEY_D, (y.status_code, dict(y.headers)))
        # a failure is not remembered
        C = tok("c-outage"); board.rules[C] = (500, {}, b"x")
        x = await r.get(C); board.accept(C, "bob@example.invalid"); y = await r.get(C)
        check("cache: a failure (the board's 500) is never remembered", x.status_code == 503 and y.status_code == 200 and who(y) == KEY_B, (x.status_code, y.status_code))
        # an accepted token that the board then refuses is refused as soon as the window ends, and an outage after it is an outage
        D = tok("d-revoked"); board.accept(D, "alice@example.invalid")
        x = await r.get(D); del board.rules[D]
        y = await r.get(D)
        now[0] += 5.1
        z = await r.get(D)
        check("cache: a token revoked at the board is served for the window at most, then refused (401)", x.status_code == 200 and y.status_code == 200 and z.status_code == 401 and who(z) is None, (x.status_code, y.status_code, z.status_code))
        check("cache: ... and the refusal left no entry", hashlib.sha256(D.encode()).hexdigest() not in r.svc.cache)
        board.rules[D] = (503, {}, b"")
        E = tok("e-cached"); board.accept(E, "alice@example.invalid"); x = await r.get(E); now[0] += 5.1
        board.rules[E] = (500, {}, b"")
        y = await r.get(E)
        check("cache: after the window a board that fails is an outage (503), not the old answer", x.status_code == 200 and y.status_code == 503 and who(y) is None, (x.status_code, y.status_code))
        # inside the window the first answer stands, whatever the board would say now
        F = tok("f"); board.accept(F, "alice@example.invalid"); await r.get(F)
        board.accept(F, "dana.one@example.invalid")
        x = await r.get(F)
        check("cache: inside the window the answer of the cache is the first answer (the board is not asked again)", who(x) == KEY_A, who(x))
    finally:
        await r.close()
    # bounded
    old = signin.MAX_ENTRIES; signin.MAX_ENTRIES = 3
    r = Rig(board, cache_seconds=50.0)
    try:
        ts = [tok(f"bound{i}") for i in range(6)]
        for t in ts:
            board.accept(t, "alice@example.invalid"); await r.get(t)
        check("cache: at most MAX_ENTRIES entries are kept (3 of 6)", len(r.svc.cache) == 3, len(r.svc.cache))
        check("cache: ... the newest ones", list(r.svc.cache) == [hashlib.sha256(t.encode()).hexdigest() for t in ts[-3:]], list(r.svc.cache))
        n0 = board.calls(); await r.get(ts[0])
        check("cache: ... an evicted token is asked again", board.calls() == n0 + 1, board.calls() - n0)
        now[0] += 60
        for i in range(3):
            t = tok(f"later{i}"); board.accept(t, "alice@example.invalid"); await r.get(t)
        check("cache: entries past their time are dropped when another is made (3 entries, none of the old)", len(r.svc.cache) == 3 and all(v[0] > now[0] for v in r.svc.cache.values()), [v[0] - now[0] for v in r.svc.cache.values()])
    finally:
        signin.MAX_ENTRIES = old
        await r.close()
    # off
    r = Rig(board, cache_seconds=0)
    try:
        A2 = tok("off"); board.accept(A2, "alice@example.invalid")
        n0 = board.calls(); await r.get(A2); await r.get(A2)
        check("cache: cache_seconds = 0 turns it off: the board is asked every time and nothing is kept", board.calls() == n0 + 2 and not r.svc.cache, (board.calls() - n0, len(r.svc.cache)))
    finally:
        await r.close()
    # real clock
    signin.CLOCK = time.monotonic
    r = Rig(board, cache_seconds=0.5)
    try:
        G = tok("g-real"); board.accept(G, "alice@example.invalid")
        n0 = board.calls(); await r.get(G); await r.get(G); time.sleep(0.7); await r.get(G)
        check("cache: with the real clock, 0.5 s: two requests inside it ask once, one after it asks again", board.calls() == n0 + 2, board.calls() - n0)
    finally:
        await r.close()


# ------------------------------------------------------------------------------------------------ 6. what is sent, what is echoed
async def echo_part(board):
    r = Rig(board, cache_seconds=0)
    try:
        t = tok("alice"); board.accept(t, "alice@example.invalid")
        forged = ident.sign(SECRET.encode(), "alice@example.invalid")
        spoof = {"X-Verified-User": "mallory@example.invalid", "X-Forwarded-User": "mallory@example.invalid", "X-Stackshot-Identity": forged, "X-Stackshot-Verify": "v1.forged.1.00",
                 "X-Forwarded-Uri": "/mcp?access_token=QUERYSECRET", "X-Forwarded-Method": "POST", "Cookie": "session=COOKIESECRET", "X-Api-Key": "APIKEYSECRET"}
        x = await r.get(t, extra=spoof)
        answers = [x]
        check("spoof: an identity header the client sends is not the answer's: the answer is the board's person", x.status_code == 200 and who(x) == KEY_A and "x-forwarded-user" not in x.headers, dict(x.headers))
        sent = board.seen[-1]["headers"]
        check("spoof: the board is sent the service's own signature, not the client's, and none of the client's other headers", sent["x-stackshot-verify"] != spoof["X-Stackshot-Verify"] and board.seen[-1]["sig_ok"]
              and not {"x-verified-user", "x-forwarded-user", "x-stackshot-identity", "x-forwarded-uri", "x-forwarded-method", "cookie", "x-api-key"} & set(sent), sorted(sent))
        x = await r.get(None, extra=spoof); answers.append(x)
        check("spoof: no bearer with a spoofed identity header is 401, and the answer carries no identity", x.status_code == 401 and who(x) is None and "x-forwarded-user" not in x.headers, dict(x.headers))
        x = await r.get(tok("unknown"), extra=spoof); answers.append(x)
        check("spoof: a refused token with a spoofed identity header is 401 with none", x.status_code == 401 and who(x) is None, dict(x.headers))
        board.rules[tok("e500")] = (500, {}, b"")
        x = await r.get(tok("e500"), extra=spoof); answers.append(x)
        check("spoof: an outage with a spoofed identity header is 503 with none", x.status_code == 503 and who(x) is None, dict(x.headers))
        said = [rr.text + " " + " ".join(rr.headers.values()) for rr in answers]
        check("spoof: no answer (200, 401, 503), in a header or its body, repeats what the request sent", len(said) == 4 and not [w for w in ("mallory", "QUERYSECRET", "COOKIESECRET", "APIKEYSECRET", "forged") for a in said if w in a], said)
        # the header is signed afresh for each request, with the word the board checks
        n0 = board.calls(); await r.get(t); await r.get(t)
        check("sent: each request carries a header signed with the secret as of now (the board verified every one)", board.calls() == n0 + 2 and all(s["sig_ok"] for s in board.seen[-2:]), [s["sig_ok"] for s in board.seen][-4:])
    finally:
        await r.close()


# ------------------------------------------------------------------------------------------------ 7. the start
def start_part():
    cfgdir = T / "start"; (cfgdir / "home").mkdir(parents=True)
    def run(toml, *args, timeout=120):
        p = cfgdir / "stackshot.toml"; p.write_text(toml)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("STACKSHOT_", "BOARD_MCP_", "XDG_"))}
        env.update(HOME=str(cfgdir / "home"), STACKSHOT_CONFIG=str(p), PYTHONPATH=STACK)
        return subprocess.run([sys.executable, "-m", "stackshot.frontdoor.signin", *args], env=env, cwd=str(cfgdir), capture_output=True, text=True, timeout=timeout)
    base = f'[frontdoor_signin]\nlisten_port = 8123\nboard_verify_url = "http://127.0.0.1:8010/frontdoor/verify"\nverify_secret_file = "{SFILE}"\nmembers_file = "{MEMBERS}"\n'
    good = base + f'identity_secret_file = "{IFILE}"\n'
    r = run(good, "--check")
    check("start: --check of a good config prints what would run (port, board, header, no secret) and exits 0", r.returncode == 0 and "127.0.0.1:8123" in r.stdout and "http://127.0.0.1:8010/frontdoor/verify" in r.stdout
          and "X-Verified-User" in r.stdout and SECRET not in r.stdout + r.stderr, (r.returncode, r.stdout, r.stderr[-300:]))
    r = run('[frontdoor_signin]\nlisten_port = 8123\n', "--check")
    check("start: a config that lacks what the service cannot start without exits 2, names each, prints no secret", r.returncode == 2 and "no usable board_verify_url" in r.stderr and "no verify_secret_file" in r.stderr and "no members_file" in r.stderr
          and "no identity_secret_file" in r.stderr, (r.returncode, r.stderr[-300:]))
    r = run('[frontdoor]\nlisten_port = 8123\n', "--check")
    check("start: a config with no [frontdoor_signin] table exits 2 and says so", r.returncode == 2 and "[frontdoor_signin]" in r.stderr, (r.returncode, r.stderr[-300:]))
    r = run(good, "--nonsense")
    check("start: an argument it does not know is exit 2 with the usage", r.returncode == 2 and "usage" in r.stderr, (r.returncode, r.stderr[-300:]))
    r = run(good.replace("8123", "99999"), "--check")
    check("start: a note for a wrong value goes to standard error and the default is used", r.returncode == 0 and "note: [frontdoor_signin] listen_port" in r.stderr and "127.0.0.1:8021" in r.stdout, (r.returncode, r.stdout, r.stderr[-300:]))
    # the verify secret is a secret of its own
    same_value = secret_file("copy.key", "  " + SECRET + "  \nsecond line")
    link = T / "linked.key"; link.symlink_to(SFILE)
    chain = T / "chained.key"; chain.symlink_to(link)
    hard = T / "hard.key"; os.link(SFILE, hard)
    def refused_start(label, toml, want):
        r = run(toml, "--check")
        said = r.stdout + r.stderr
        check(f"secrets: {label}: the service does not start (exit 2), says why, and prints no secret", r.returncode == 2 and "does not start" in r.stderr and want in r.stderr and SECRET not in said and IDENTITY not in said, (r.returncode, r.stderr[-300:]))
    for label, path in (("the identity secret is the verify secret's own path", SFILE), ("the identity secret is a link to the verify secret", str(link)), ("the identity secret is a link to a link to it", str(chain)),
                        ("the identity secret is a hard link to it", str(hard))):
        refused_start(label, base + f'identity_secret_file = "{path}"\n', "are the same file")
    refused_start("the verify secret is a link to the identity secret", base.replace(f'verify_secret_file = "{SFILE}"', f'verify_secret_file = "{link}"') + f'identity_secret_file = "{SFILE}"\n', "are the same file")
    refused_start("another file holds the same value", base + f'identity_secret_file = "{same_value}"\n', "hold the same value")
    refused_start("the front door's identity secret holds the same value", base + f'[frontdoor]\nidentity_secret_file = "{same_value}"\n', "hold the same value")
    refused_start("the front door's identity secret is a link to the same file", base + f'[frontdoor]\nidentity_secret_file = "{link}"\n', "are the same file")
    refused_start("its own differs and the front door's is the same value", good + f'[frontdoor]\nidentity_secret_file = "{same_value}"\n', "hold the same value")
    refused_start("a board's identity secret holds the same value", good + f'[behind_frontdoor]\nidentity_secret_file = "{same_value}"\n', "hold the same value")
    refused_start("no identity secret is named", base, "no identity_secret_file")
    refused_start("the identity secret is missing", base + f'identity_secret_file = "{T}/no-identity.key"\n', "identity_secret_file")
    refused_start("the identity secret cannot be used (others can read it)", base + f'identity_secret_file = "{secret_file("open-identity.key", IDENTITY, 0o644)}"\n', "identity_secret_file")
    refused_start("the verify secret is missing", good.replace(f'verify_secret_file = "{SFILE}"', f'verify_secret_file = "{T}/no-verify.key"'), "verify_secret_file")
    r = run(base + f'[frontdoor]\nidentity_secret_file = "{IFILE}"\n', "--check")
    check("secrets: with the front door's identity secret another file and value, the service could start", r.returncode == 0, (r.returncode, r.stderr[-300:]))
    # serving refuses as --check does: it never listens
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); free = sock.getsockname()[1]
    try:
        r = run(base.replace("8123", str(free)) + f'identity_secret_file = "{same_value}"\n', timeout=30)
        got = (r.returncode, r.stderr[-300:])
    except subprocess.TimeoutExpired:      # it is serving (run() ends it)
        got = ("still running", "")
    check("secrets: serving (no --check) refuses the same way and never listens", got[0] == 2 and "hold the same value" in got[1], got)


# ------------------------------------------------------------------------------------------------ run
SECTIONS = []


def section(name, fn, *a):
    try:
        res = fn(*a)
        if asyncio.iscoroutine(res):
            asyncio.run(res)
    except BaseException as e:      # noqa: BLE001  (a section that stops on an exception is a failed run that says where: it is never counted as the checks it did not make)
        traceback.print_exc()
        fails.append(f"crash: {name}: {type(e).__name__}"); print(f"CRASH {name}: {type(e).__name__}: {str(e)[:300]}", flush=True)


def main():
    board = Board()
    try:
        section("settings", settings_part)
        section("answer", answer_part, board)
        section("refusals", refusal_part, board)
        section("outages", outage_part, board)
        section("files", files_part, board)
        section("cache", cache_part, board)
        section("echo", echo_part, board)
        section("start", start_part)
        blob = "\n".join(LOGS)
        check("log: the service logged (so the next checks mean something): a request is named by a hash of its token", len(LOGS) > 20 and re.search(r"token [0-9a-f]{8}\b", blob) is not None, len(LOGS))
        leaked = [t for t in TOKENS | {SECRET, NEW_SECRET, "QUERYSECRET", "COOKIESECRET", "APIKEYSECRET", "mallory"} if t in blob]
        check("log: no token, secret, query, cookie or key of a request is in any log line", not leaked, leaked)
        check("log: no address (the board's, the member's key) is in any log line", "@" not in blob and "example.invalid" not in blob, [l for l in LOGS if "@" in l or "example.invalid" in l][:3])
        check("log: the tag of a token is the first 8 hex digits of its SHA-256", signin.tag("abc") == hashlib.sha256(b"abc").hexdigest()[:8])
        check("log: the verify secret's path is named in a file fault, its value never", any("verify_secret_file" in l for l in LOGS) and SECRET not in blob)
    finally:
        board.stop()


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:      # noqa: BLE001
        traceback.print_exc(); fails.append(f"crash: the run: {type(e).__name__}")
    print(("ok" if not fails else "FAILED") + f": sign-in service scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""), flush=True)
    sys.exit(1 if fails else 0)
