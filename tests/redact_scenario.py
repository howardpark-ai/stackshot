"""Scenario test for the access-log redaction (server.py `_RedactCodes`) — fixture data, no network.

uvicorn's access log records the request path with its query string; the OAuth routes carry one-time sign-in values in `code`,
`state` and `txn_id`. Covers: the value of each of those three parameters is logged as `[redacted]` on any route (the callbacks,
/authorize, the consent page), the name, the path and the other parameters kept; a URL with none of them, or with one of the
names only inside another name or a value, is unchanged; a record of another shape passes untouched; the filter sits on
uvicorn.access at import and is still there after uvicorn configures its logging, so a line logged the way uvicorn logs it comes
out redacted through uvicorn's own access formatter.

    tests/run-suite redact        → exit 0 / 1"""
import io, json, logging, os, pathlib, re, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="redacttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off"); os.environ.pop("STACKSHOT_FLEET_DIR", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

import server
FMT = '%s - "%s %s HTTP/%s" %d'                          # uvicorn.protocols.http.*_impl: access_logger.info(FMT, ...)
def rec(msg, args):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)
def run(path):
    r = rec(FMT, ("127.0.0.1:5555", "GET", path, "1.1", 200))
    kept = server._RedactCodes().filter(r)
    return kept, r.getMessage()

for path, want in (("/auth/callback?state=x&code=4/0Asecret&scope=email", "/auth/callback?state=[redacted]&code=[redacted]&scope=email"),
                   ("/ui/callback?code=abc&state=y", "/ui/callback?code=[redacted]&state=[redacted]"),
                   ("/consent?txn_id=T0pS3cret", "/consent?txn_id=[redacted]"),
                   ("/consent?a=1&txn_id=T0pS3cret&b=2", "/consent?a=1&txn_id=[redacted]&b=2"),
                   ("/authorize?response_type=code&client_id=x&state=S3cret&code_challenge=c&code_challenge_method=S256&redirect_uri=http://h/cb",
                    "/authorize?response_type=code&client_id=x&state=[redacted]&code_challenge=c&code_challenge_method=S256&redirect_uri=http://h/cb"),
                   ("/x?code=a=b&state=", "/x?code=[redacted]&state=[redacted]"),
                   ("/mcp", "/mcp"),
                   ("/client/items?key=home-sparrow-main&ids=g1,g2", "/client/items?key=home-sparrow-main&ids=g1,g2"),
                   ("/authorize?response_type=code&client_id=x", "/authorize?response_type=code&client_id=x"),
                   ("/x?statement=1&mycode=2&txn_ids=3&code_challenge=4", "/x?statement=1&mycode=2&txn_ids=3&code_challenge=4"),
                   ("/x?next=/y?code", "/x?next=/y?code")):
    kept, msg = run(path)
    check(f"{path} → {want}", kept is True and msg == f'127.0.0.1:5555 - "GET {want} HTTP/1.1" 200', msg)
for secret in ("4/0Asecret", "T0pS3cret", "S3cret"):
    kept, msg = run(f"/x?code={secret}&state={secret}&txn_id={secret}&other=ok")
    check(f"the value {secret} is nowhere in the line, the other parameter is", secret not in msg and "other=ok" in msg, msg)
r = rec("plain message with code=abc in it", None); kept = server._RedactCodes().filter(r)
check("a record of another shape passes untouched", kept is True and r.getMessage() == "plain message with code=abc in it" and r.args is None, r.getMessage())
r = rec("%s %s", ("a?code=1", "b")); server._RedactCodes().filter(r)
check("a two-argument record is not taken for an access line", r.getMessage() == "a?code=1 b", r.getMessage())

acc = logging.getLogger("uvicorn.access")
check("the filter is installed on uvicorn.access at import", any(isinstance(f, server._RedactCodes) for f in acc.filters), acc.filters)
import uvicorn, uvicorn.logging
uvicorn.Config(server.mcp.http_app(), log_level="info")    # what mcp.run() does before serving: uvicorn's dictConfig
check("…and is still there once uvicorn has configured its logging", any(isinstance(f, server._RedactCodes) for f in acc.filters), acc.filters)
buf = io.StringIO(); h = logging.StreamHandler(buf); h.setFormatter(uvicorn.logging.AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
acc.addHandler(h)
acc.info(FMT, "127.0.0.1:5555", "GET", "/auth/callback?state=x&code=4/0Asecret&scope=email", "1.1", 302)
out = buf.getvalue().strip()
check("a line logged the way uvicorn logs it comes out redacted through uvicorn's access formatter", out == '127.0.0.1:5555 - "GET /auth/callback?state=[redacted]&code=[redacted]&scope=email HTTP/1.1" 302 Found', out)

print(("ok" if not fails else "FAILED") + f": redact scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
