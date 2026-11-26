"""Scenario test for the board's token check for the sign-in service (`GET /frontdoor/verify`, `web/routes/door_verify.py`, the `verify_secret_file` key of `[behind_frontdoor]`).

Offline and hermetic, one process: made-up config tables, a stand-in `mcp` whose `custom_route` collects the route and whose `auth.verify_token` answers from a table (the real provider's Google call is not
made here: the board scenario and the live probe cover that the provider is the board's own), and the route's endpoint called with a request built by hand. No port, no store.

Covers:
  * the settings: the key alone turns the check on and nothing else (no identity check, no members); a value that is no path is not "off" and is told; a file group or others can read is told; the table
    that is no table answers no check and says so; `Settings` keeps the old keys' meaning (a table without the key reads as before);
  * `check_verify`: a header signed under the verify secret passes inside the replay window; none, another secret, an altered one, an old one, one dated ahead, an empty value, the identity secret
    (a different file) and a signed identity of a person (a value that is not the check's own) are each refused with the sentence, and no sentence holds a secret; a secret that cannot be read refuses;
    a rotated secret applies to the next call;
  * the route: only on a board that offers the check (otherwise nothing is registered); the gate comes before the token (a bad header answers 403 whatever the bearer is, and the library is not called);
    a good token is 200 with the address in lower case and `via`, and nothing else; the portal's token says `portal`; no bearer, an empty one, `Basic` and an unknown token are 401 `invalid_token`;
    a token with no address is 401; a check that raises is 503, never 401; a board with no auth object answers 404 to a signed request; every answer is `no-store`; no answer holds the token.

    tests/run-suite frontdoor_verify       -> exit 0 / 1"""
import asyncio, json, os, sys, tempfile, tomllib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch

from stackshot.core import behind_door as door, frontdoor_identity as ident
from stackshot.web.routes import door_verify as route

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))


T = _scratch.mkdtemp(prefix="doorverify-")
SECRET, OTHER, IDSECRET = "verify-secret-0123456789abcdef", "another-secret-0123456789abc", "identity-secret-0123456789abcd"


def secret_file(name, value, mode=0o600):
    p = os.path.join(T, name)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.chmod(p, mode)
    return p


VFILE, IFILE = secret_file("verify.key", SECRET), secret_file("identity.key", IDSECRET)
cfgd = tomllib.loads
sign = lambda secret=SECRET, who=door.VERIFY_WHO, now=None: ident.sign(secret.encode(), who, now=now)
TABLE = f'[behind_frontdoor]\nverify_secret_file = "{VFILE}"\nidentity_max_age_seconds = 120\n'
CFG = cfgd(TABLE)

# ---- 1. the settings
s, n = door.parse(cfgd('[behind_frontdoor]\nverify_secret_file = "/v"\n'))
check("settings: the key alone offers the check and checks no identity and reads no members", s.verify and s.verify_file == "/v" and not s.identity and not s.members and n == [], (s, n))
s, n = door.parse(cfgd('[behind_frontdoor]\nidentity_secret_file = "/k"\nmembers_file = "/m"\nboard_name = "main"\n'))
check("settings: a table without the key offers no check", not s.verify and s.verify_file == "" and n == [], (s, n))
check("settings: no table at all offers none", door.parse(cfgd("[auth]\nmode = 'off'\n"))[0] == door.Settings() and not door.Settings().verify)
s, n = door.parse(cfgd("[behind_frontdoor]\nverify_secret_file = 5\n"))
check("settings: a verify_secret_file that is no path still offers the check (never off) and the notes say it answers none", s.verify and s.verify_file == "" and any("answers no token check" in x for x in n), (s, n))
s, n = door.parse(cfgd("behind_frontdoor = 3\n"))
check("settings: a table that is no table offers the check, and the notes say so", s.verify and any("answers no token check" in x for x in n), (s, n))
pub = secret_file("pub.key", "a-group-readable-secret-0123456789", 0o644)
n = door.notes(cfgd(f'[behind_frontdoor]\nverify_secret_file = "{pub}"\n'))
check("settings: a verify secret group or others can read is told", any("verify_secret_file" in x and pub in x for x in n), n)
check("settings: a good file has nothing to tell", door.notes(CFG) == [], door.notes(CFG))

# ---- 2. the check of one signed header
ok = door.check_verify(sign(), CFG)
check("check: a header signed under the verify secret passes", ok.who == door.VERIFY_WHO and not ok.refusal, ok)
for label, value, want in (
        ("no header", None, door.NO_VERIFY), ("an empty header", "", door.NO_VERIFY), ("a blank header", "   ", door.NO_VERIFY),
        ("another secret", sign(OTHER), door.BAD_VERIFY),
        ("the identity secret (a different file)", sign(IDSECRET), door.BAD_VERIFY),
        ("a person's signed identity (not the check's own words)", sign(who="alice@example.test"), door.BAD_VERIFY),
        ("an old one (400 s, window 120 s)", sign(now=__import__("time").time() - 400), door.BAD_VERIFY),
        ("one dated 300 s ahead", sign(now=__import__("time").time() + 300), door.BAD_VERIFY),
        ("a signature cut short", sign()[:-1], door.BAD_VERIFY),
        ("not a signed value", "v1.nonsense", door.BAD_VERIFY)):
    r = door.check_verify(value, CFG)
    check(f"check: {label} is refused with the sentence, which tells no secret", r.who == "" and r.refusal == want and SECRET not in r.refusal and OTHER not in r.refusal, r)
v = sign(); p = v.split(".")
r = door.check_verify(".".join([p[0], ident._b64(b"someone-else"), p[2], p[3]]), CFG)
check("check: an altered identity under the old signature is refused", r.refusal == door.BAD_VERIFY, r)
r = door.check_verify(sign(now=__import__("time").time() - 100), CFG)
check("check: a header 100 s old passes inside the 120 s window", r.who == door.VERIFY_WHO, r)
missing = cfgd(f'[behind_frontdoor]\nverify_secret_file = "{T}/none.key"\n')
r = door.check_verify(sign(), missing)
check("check: a secret that is missing refuses every request with its own sentence", r.refusal == door.NO_VERIFY_SECRET and "none.key" not in r.refusal, r)
r = door.check_verify(sign(), cfgd(f'[behind_frontdoor]\nverify_secret_file = "{pub}"\n'))
check("check: a secret group or others can read is not used", r.refusal == door.NO_VERIFY_SECRET, r)
secret_file("verify.key", OTHER)
check("check: a rotated secret applies to the next request, the old header is refused and the new one passes",
      door.check_verify(sign(), CFG).refusal == door.BAD_VERIFY and door.check_verify(sign(OTHER), CFG).who == door.VERIFY_WHO)
secret_file("verify.key", SECRET)

# ---- 3. the route
class Token:
    def __init__(self, claims): self.claims = claims; self.token = "x"


class Auth:
    def __init__(self, table): self.table, self.calls = table, []

    async def verify_token(self, token):
        self.calls.append(token)
        got = self.table.get(token)
        if isinstance(got, Exception):
            raise got
        return got


class Mcp:
    def __init__(self, auth): self.auth, self.routes = auth, {}

    def custom_route(self, path, methods):
        def deco(fn):
            self.routes[(path, tuple(methods))] = fn
            return fn
        return deco


TABLE_OF_TOKENS = {
    "good-google": Token({"email": "Alice@Example.Test", "sub": "1", "name": "Alice", "picture": "p"}),
    "good-portal": Token({"email": "owner@example.test", "via": "portal"}),
    "no-address": Token({"sub": "2"}),
    "empty-address": Token({"email": "  "}),
    "boom": RuntimeError("Google is down: https://secret.example/token=abc"),
}


def call(mcp, headers, path="/frontdoor/verify"):
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [(k.lower().encode(), v.encode("latin-1")) for k, v in headers.items()], "server": ("127.0.0.1", 1), "scheme": "http"}
    fn = mcp.routes[("/frontdoor/verify", ("GET",))]
    resp = asyncio.run(fn(Request(scope)))
    return resp.status_code, resp.body.decode(), {k.lower(): v for k, v in resp.headers.items()}


def offered(table_cfg, auth):
    """A board's route table under the config `table_cfg` (the running config is replaced for the call)."""
    saved = door.settings
    door.settings = lambda cfg=None: saved(table_cfg)
    try:
        m = Mcp(auth); route.register(m); return m
    finally:
        door.settings = saved


m_none = offered(cfgd("[auth]\nmode = 'off'\n"), Auth({}))
check("route: a board with no verify key registers nothing", m_none.routes == {}, m_none.routes)
m_id = offered(cfgd('[behind_frontdoor]\nidentity_secret_file = "/k"\n'), Auth({}))
check("route: a board that checks identities but names no verify key registers nothing", m_id.routes == {}, m_id.routes)
auth = Auth(TABLE_OF_TOKENS)
m = offered(CFG, auth)
check("route: a board with the key registers GET /frontdoor/verify, and only that", list(m.routes) == [("/frontdoor/verify", ("GET",))], list(m.routes))

# `door.settings`/`check_verify` read the running config: point them at the made-up table for the calls
saved_settings, saved_check = door.settings, door.check_verify
door.settings = lambda cfg=None: saved_settings(CFG)
door.check_verify = lambda value, cfg=None, now=None: saved_check(value, CFG, now)
try:
    H = lambda tok="good-google", signed=True, extra=None: {**({door.VERIFY_HEADER: sign()} if signed else {}), **({"Authorization": f"Bearer {tok}"} if tok is not None else {}), **(extra or {})}
    st, body, hd = call(m, H())
    check("route: a good token is 200 with the address in lower case, who signed in by Google, and nothing else", st == 200 and json.loads(body) == {"email": "alice@example.test", "via": "google"}, (st, body))
    check("route: the answer is no-store and holds no token", hd.get("cache-control") == "no-store" and "good-google" not in body, (hd, body))
    st, body, _ = call(m, H("good-portal"))
    check("route: the portal's machine token says via portal", st == 200 and json.loads(body) == {"email": "owner@example.test", "via": "portal"}, (st, body))
    st, body, hd = call(m, H("nope"))
    check("route: an unknown token is 401 invalid_token, no-store", st == 401 and json.loads(body) == {"error": "invalid_token"} and hd.get("cache-control") == "no-store", (st, body, hd))
    for label, hdrs in (("no Authorization header", H(None)), ("an empty bearer", H("")), ("a Basic header", H(None, extra={"Authorization": "Basic Zm9vOmJhcg=="}))):
        n0 = len(auth.calls)
        st, body, _ = call(m, hdrs)
        check(f"route: {label} is 401 invalid_token and the library is not asked", st == 401 and json.loads(body) == {"error": "invalid_token"} and len(auth.calls) == n0, (st, body))
    for tok in ("no-address", "empty-address"):
        st, body, _ = call(m, H(tok))
        check(f"route: a token the library accepts but names no address ({tok}) is 401", st == 401 and json.loads(body) == {"error": "invalid_token"}, (st, body))
    st, body, hd = call(m, H("boom"))
    check("route: a check that raises is 503 unavailable, never 401, and says nothing of why", st == 503 and json.loads(body) == {"error": "unavailable"} and "secret.example" not in body and hd.get("cache-control") == "no-store", (st, body))
    n0 = len(auth.calls)
    for label, hdrs in (("no signed header", H(signed=False)), ("another secret", H(extra={door.VERIFY_HEADER: sign(OTHER)})), ("an old one", H(extra={door.VERIFY_HEADER: sign(now=__import__("time").time() - 400)})), ("a blank one", H(extra={door.VERIFY_HEADER: " "}))):
        st, body, hd = call(m, hdrs)
        check(f"route: {label} is 403 with a sentence whatever the bearer is, and the library is not asked", st == 403 and body.startswith("refused: ") and "good-google" not in body and hd.get("cache-control") == "no-store", (st, body))
    check("route: no refused request reached the token check", len(auth.calls) == n0, auth.calls[n0:])
    m_noauth = offered(CFG, None)
    m_noauth.auth = None
    st, body, _ = call(m_noauth, H())
    check("route: a board with no auth object answers a signed request 404, and says nothing of tokens", st == 404 and "token" not in body, (st, body))
    st, body, _ = call(m_noauth, H(signed=False))
    check("route: ...and an unsigned one 403 first", st == 403, (st, body))
finally:
    door.settings, door.check_verify = saved_settings, saved_check

if fails:
    print(f"\n{len(fails)} failures in {len(ran)} checks"); sys.exit(1)
print(f"ok: front door verify route scenario, {len(ran)} checks")
