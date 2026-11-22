"""Scenario test for the server's request log and its summary command — a throwaway state directory, a fake clock, local sockets only; no live store, no network.

The log is a pure ASGI wrapper around the HTTP app (web/requestlog.py) that writes one JSON line per request into rotated day files (core/requestlog.py); `stackshot requests summary` reads them back (tools/request_summary.py). Covers:

  1  fields        one line per request with ts, method, route, status, ms, bytes and caller; the route is the template (path parameters by name, a catch-all as /{name}, a client verb as /client/{other} unless a handler took it, no match as (unmatched)); a machine noted by a route is the caller
  2  redaction     a request with a sign-in query string (code, state, txn_id), a Cookie, an Authorization header, a body and a secret path parameter leaves none of it in the file, and no query string at all
  3  errors        an unhandled exception is a 500 line with err (its type and where it was raised, never its message, whatever secret the message holds) and the exception still reaches the server
  4  streaming     a streamed response reaches the client chunk by chunk through a real server (the first chunk arrives before the last is produced), ms covers the whole stream, bytes is its size
  5  events         a start line (pid, mode) at the server's start and a stop line at a clean shutdown
  6  mcp_route      through a real streamable-HTTP server and the FastMCP client: a tool call is route tool:<name> with its sender as the caller, other messages are mcp:<method>; no argument is in the file
  7  write_failure a log that cannot be written never fails a request, and says so on stderr once in ten minutes
  8  files         one file per UTC day; a finished day is gzipped at the next day's first write; a file more than 90 days old is deleted (fake clock), the 90th day's is kept; a half-written last line is not joined to the next
  9  summary       exact percentiles, the slowest calls, the 5xx count and error rate, --since/--until as dates, date-times, offsets and 90m/24h/7d, the timezone printed, --route, --json, an empty range, a missing directory,
                   a half-written line, a gz file and a cut-short gz file; the program is registered in the command line; the default directory and zone are the instance's
  10 wiring        the real server: the route hook is the first tool middleware, http_app is served inside the wrapper, and a client token's machine reaches the line as its caller
  11 cost          the middleware's own time per request and the size of a day's file (printed)

    tests/run-suite requestlog        → exit 0 / 1"""
import asyncio, contextlib, datetime as dt, gzip, io, json, logging, os, re, subprocess, sys, pathlib, threading, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="reqlog-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("STACKSHOT_READ_ONLY", None)
for d in ("store/a", "store/g", "fleet/a", "state/hub", "wiki/projects", "transcripts/-home-x", "secrets"): (T / d).mkdir(parents=True)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
import httpx, uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route
from stackshot.core import requestlog as RL
from stackshot.web import requestlog as WR
from stackshot.tools import request_summary as RS

DAY = 86400.0
def epoch(s):   # "2026-11-20T23:59:59" (UTC) -> epoch seconds
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()
class Clock:
    def __init__(self, t=0.0): self.t = t
    def __call__(self): return self.t
def lines(path):
    p = pathlib.Path(path)
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as fh: return [json.loads(x) for x in fh.read().splitlines() if x.strip()]
def all_text(d):
    out = b""
    for p in sorted(pathlib.Path(d).glob("*")):
        raw = p.read_bytes(); out += gzip.decompress(raw) if p.name.endswith(".gz") else raw
    return out.decode("utf-8", "replace")
def fresh(name, **kw):
    d = T / name; d.mkdir()
    ck = Clock(epoch("2026-11-22T09:36:53") + 0.123); kw.setdefault("threaded", False)
    return d, ck, RL.RequestLog(d, **{"clock": ck, **kw})
def run(coro): return asyncio.run(coro)

# ------------------------------------------------------------------ a small app with the routes the checks need
EV = threading.Event(); GOT = {}
async def signin(request): return PlainTextResponse("welcome")
async def answer(request):
    body = await request.body(); WR.note(request, caller="box-a"); return JSONResponse({"n": len(body)})
async def slow(request): await asyncio.sleep(0.05); return PlainTextResponse("late")
async def boom(request): raise ValueError("failed with Bearer SECRETBEARER99 at http://h.example/x?code=SECRETCODE77 " + "z" * 400)
async def client_what(request): return PlainTextResponse(request.path_params["what"])
SHAPES = [
    subprocess.CalledProcessError(1, ["git", "push", "https://x-access-token:ghs_TOPSECRET2@github.com/o/r.git"]),
    RuntimeError("headers {'Authorization': 'Token TOPSECRET3'}"),
    RuntimeError("headers {'cookie': 'session=TOPSECRET5; ui=1'}"),
    RuntimeError("bad config password=TOPSECRET6 token=TOPSECRET7"),
    RuntimeError("https://h.example/cb#access_token=TOPSECRET9"),
    ValueError('JSONDecodeError at {"password": "TOPSECRET8"}'),
    RuntimeError("fatal: unable to access 'https://user:TOPSECRET13@h.example/r.git/'"),
    KeyError("TOPSECRET14"),
    OSError(13, "TOPSECRET15 denied"),
    RuntimeError("Cookie: ui=TOPSECRET16; Authorization: Basic VE9QU0VDUkVUMTc= " + "z" * 400),
]
async def raise_route(request): raise SHAPES[int(request.path_params["i"])]
async def app_503(request): return PlainTextResponse("TOPSECRET18 body", status_code=503)
async def stream(request):
    async def gen():
        yield b"one"
        for _ in range(100):
            if EV.is_set(): break
            await asyncio.sleep(0.05)
        GOT["early"] = EV.is_set(); await asyncio.sleep(0.3); yield b"two"
    return StreamingResponse(gen())
async def site(request):
    name = request.path_params["name"]
    return PlainTextResponse("file") if name in ("board.css", "items/12.html") else PlainTextResponse("no", status_code=404)
def make_app(catch_all=True):
    routes = [Route("/signin", signin), Route("/items/{key}/answer", answer, methods=["POST"]), Route("/slow", slow), Route("/boom", boom), Route("/raise/{i}", raise_route), Route("/err503", app_503), Route("/client/{what}", client_what), Route("/stream", stream)]
    return Starlette(routes=routes + ([Route("/{name:path}", site)] if catch_all else []))
def serve(app):
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(200):
        if srv.started: break
        time.sleep(0.05)
    return srv, th, port
def stop(srv, th): srv.should_exit = True; th.join(15)

# ------------------------------------------------------------------ 1 fields, 2 redaction, 3 errors
d, ck, log = fresh("a")
app = WR.RequestLogMiddleware(make_app(), requests=log)
SECRETS = ("SECRETCODE123", "SECRETSTATE456", "SECRETTXN789", "SECRETCOOKIE", "SECRETBEARER", "SECRETBODY", "SECRETKEY99", "SECRETPATH", "SECRETUA", "SECRETUAUA")
async def drive():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        r = {}
        r["signin"] = await c.get("/signin?code=SECRETCODE123&state=SECRETSTATE456&txn_id=SECRETTXN789&keep=1", headers={"Cookie": "ui=SECRETCOOKIE", "Authorization": "Bearer SECRETBEARER", "User-Agent": "SECRETUA/1"})
        r["answer"] = await c.post("/items/SECRETKEY99/answer", content=b'{"password":"SECRETBODY"}')
        r["slow"] = await c.get("/slow")
        r["css"] = await c.get("/board.css"); r["item"] = await c.get("/items/12.html"); r["miss"] = await c.get("/nothing/SECRETPATH?x=SECRETUAUA")
        r["what"] = await c.get("/client/poll"); r["whatbad"] = await c.get("/client/SECRETKEY99")
        r["boom"] = await c.get("/boom")
        return r
R_ = run(drive()); recs = lines(d / "requests-2026-11-22.jsonl"); recs_a = recs
by = lambda route: [x for x in recs if x.get("route") == route]
sg = by("/signin")
check("fields: one line per request", len(recs) == 9, len(recs))
check("fields: the first line's keys", sg and set(sg[0]) == {"ts", "method", "route", "status", "ms", "bytes", "caller"}, sg)
check("fields: ts is UTC with milliseconds", sg and sg[0]["ts"] == "2026-11-22T09:36:53.123Z", sg and sg[0]["ts"])
check("fields: method, status, bytes, anon caller", sg and sg[0]["method"] == "GET" and sg[0]["status"] == 200 and sg[0]["bytes"] == len("welcome") and sg[0]["caller"] == "anon", sg)
check("fields: ms is a number of milliseconds", sg and isinstance(sg[0]["ms"], float) and 0 <= sg[0]["ms"] < 500, sg)
check("fields: a slow handler's ms includes its time", by("/slow") and 50 <= by("/slow")[0]["ms"] < 2000, by("/slow"))
check("fields: path parameter by name, caller the route noted", by("/items/{key}/answer") and by("/items/{key}/answer")[0]["caller"] == "box-a", recs)
check("fields: a catch-all is /{name} whatever its first folder, a hit and a miss alike, never its name", len(by("/{name}")) == 3 and {x["status"] for x in by("/{name}")} == {200, 404} and not [x for x in recs if x["route"].startswith("/items/{name")], recs)
check("fields: a client verb nobody took is /client/{other}, whatever the verb", len(by("/client/{other}")) == 2 and not [x for x in recs if x["route"] in ("/client/poll", "/client/{what}")], recs)
text = all_text(d)
check("redaction: no sign-in value, cookie, authorization, body, user agent or secret path parameter in the file", not [s for s in SECRETS if s in text], [s for s in SECRETS if s in text])
check("redaction: no query string at all", not [x for x in recs_a if "?" in x["route"]] and "keep=1" not in text and "x=SECRET" not in text, text[:300])
check("redaction: the request still got its answer", R_["signin"].text == "welcome" and R_["answer"].json() == {"n": len('{"password":"SECRETBODY"}')}, R_["answer"].text)
bm = by("/boom"); text_after = all_text(d)
ERR_RX = re.compile(r"^(\w+) at ([\w.]+):(\w+):(\d+)$")
check("errors: a 500 line with err: the type and where it was raised, nothing it says", bm and bm[0]["status"] == 500 and ERR_RX.match(bm[0]["err"]) and ERR_RX.match(bm[0]["err"]).group(1) == "ValueError" and ERR_RX.match(bm[0]["err"]).group(3) == "boom", bm)
check("errors: the message and its secrets are not in err or anywhere in the file", bm and "SECRETBEARER99" not in text_after and "SECRETCODE77" not in text_after and "failed with" not in text_after and "zzzz" not in text_after, bm)
check("errors: a request that did not fail has no err", "err" not in sg[0])
async def boom_raises():
    got = []
    async def send(m): got.append(m)
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    scope = {"type": "http", "method": "GET", "path": "/boom", "query_string": b"", "headers": [], "http_version": "1.1", "scheme": "http", "server": ("t", 80), "client": ("c", 1), "root_path": ""}
    try:
        await app(scope, receive, send); return "returned"
    except ValueError as e:
        return "raised"
check("errors: the exception still reaches the server", run(boom_raises()) == "raised")
d3, _, log3 = fresh("e")
app3 = WR.RequestLogMiddleware(make_app(), requests=log3)
async def shapes():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app3, raise_app_exceptions=False), base_url="http://t") as c:
        for i in range(len(SHAPES)): await c.get(f"/raise/{i}?token=TOPSECRET19", headers={"Authorization": "Bearer TOPSECRET20", "Cookie": "s=TOPSECRET21"})
        return await c.get("/err503")
run(shapes()); text3 = all_text(d3); r3 = lines(d3 / "requests-2026-11-22.jsonl"); rz = [x for x in r3 if x["route"] == "/raise/{i}"]
check("errors: every shape of a secret in an exception message is kept out of the file (URL userinfo, Token and Basic, cookie, key=value, a fragment, a JSON body, a quoted URL, an argument)", not re.findall(r"TOPSECRET\d+|ghs_|VE9QU0|x-access-token|password|JSONDecode|h\.example", text3), re.findall(r"TOPSECRET\d+|ghs_|VE9QU0|x-access-token|password|JSONDecode|h\.example", text3))
check("errors: each shape is one 500 line with its type and the place it was raised", len(rz) == len(SHAPES) and all(x["status"] == 500 and ERR_RX.match(x.get("err", "")) and ERR_RX.match(x["err"]).group(3) == "raise_route" for x in rz) and [ERR_RX.match(x["err"]).group(1) for x in rz] == [type(e).__name__ for e in SHAPES], rz)
check("errors: the place is a module, a function and a line number of the raising code", all(int(ERR_RX.match(x["err"]).group(4)) > 0 and ERR_RX.match(x["err"]).group(2) for x in rz), rz[:1])
a5 = [x for x in r3 if x["route"] == "/err503"]
check("errors: a 5xx the app answered itself has err `status <n>`, not its body", a5 and a5[0]["status"] == 503 and a5[0]["err"] == "status 503" and "TOPSECRET18" not in text3, a5)
d2, _, log2 = fresh("a2")
app2 = WR.RequestLogMiddleware(make_app(catch_all=False), requests=log2)
async def miss2():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as c: return await c.get("/zzz/SECRETPATH2?q=SECRETUAUA")
run(miss2()); r2 = lines(d2 / "requests-2026-11-22.jsonl")
check("fields: a path no route took is (unmatched), its name is not kept", r2 and r2[0]["route"] == "(unmatched)" and r2[0]["status"] == 404 and "SECRETPATH2" not in all_text(d2), r2)

# the method is one of the standard seven or OTHER: a raw request line can carry any token
dm, _, logm = fresh("mm")
async def one_call(scope, receive, send): await send({"type": "http.response.start", "status": 405, "headers": []}); await send({"type": "http.response.body", "body": b"no"})
appm = WR.RequestLogMiddleware(one_call, requests=logm)
async def methods():
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(m): pass
    for m in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "METHMARK", "get", "FOO", "G" * 40, "", "CONNECT"):
        await appm({"type": "http", "method": m, "path": "/x", "query_string": b"", "headers": []}, receive, send)
run(methods()); rm = [x["method"] for x in lines(dm / "requests-2026-11-22.jsonl")]
check("fields: the method is one of the standard seven, else OTHER (a raw token, lower case, 40 characters, none)", rm == ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] + ["OTHER"] * 6 and "METHMARK" not in all_text(dm) and "GGGG" not in all_text(dm), rm)

# ------------------------------------------------------------------ 4 streaming, 5 events (a real server)
d, ck, log = fresh("s", clock=time.time)
srv, th, port = serve(WR.RequestLogMiddleware(make_app(), requests=log))
t0 = time.time(); EV.clear(); GOT.clear()
chunks = []
try:
    with httpx.stream("GET", f"http://127.0.0.1:{port}/stream", timeout=20) as resp:
        it = resp.iter_raw(); first = next(it); t_first = time.time() - t0; EV.set()
        chunks = [first, *it]
finally:
    stop(srv, th)
day_file = sorted(d.glob("requests-*.jsonl"))[0]; recs = lines(day_file); st = [x for x in recs if x.get("route") == "/stream"]
check("streaming: the first chunk reaches the client before the last is produced", chunks and chunks[0] == b"one" and GOT.get("early") is True and t_first < 3, (chunks, GOT, t_first))
check("streaming: all of it arrives", b"".join(chunks) == b"onetwo", chunks)
check("streaming: ms is the whole stream and bytes its size", st and st[0]["ms"] >= 300 and st[0]["bytes"] == 6 and st[0]["status"] == 200, st)
ev = [x for x in recs if x.get("kind")]
check("events: a start line at the server's start with the pid and the mode", ev and ev[0]["kind"] == "start" and ev[0]["pid"] == os.getpid() and ev[0].get("mode") == "inline", ev)
check("events: a stop line at a clean shutdown, last", ev and ev[-1]["kind"] == "stop" and ev[-1]["pid"] == os.getpid() and recs[-1]["kind"] == "stop", recs[-1])

# ------------------------------------------------------------------ 6 the MCP endpoint, through the tool layer
from fastmcp import FastMCP, Client
d, ck, log = fresh("m", clock=time.time)
WR._LOG = log
mini = FastMCP("mini")
mini.add_middleware(WR.RequestRoute())
@mini.tool
def update(item_id: str, sender: str = "") -> str:
    return "done"
@mini.tool
def get(item_id: str) -> str:
    return "got"
WR.install(mini)
check("mcp_route: install makes http_app return the wrapper", isinstance(mini.http_app(path="/mcp"), WR.RequestLogMiddleware))
srv, th, port = serve(mini.http_app(path="/mcp"))
async def mcp_calls():
    async with Client(f"http://127.0.0.1:{port}/mcp") as c:
        await c.list_tools()
        await c.call_tool("update", {"item_id": "SECRETITEM1", "sender": "tester-1"})
        await c.call_tool("get", {"item_id": "SECRETITEM2"})
        for odd in ("has spaces", "<b>x</b>", "x" * 200, "\u00fcn\u00ef-c\u00f6de", "Upper-Case"):          # a sender that is no session name's shape
            await c.call_tool("update", {"item_id": "SECRETITEM3", "sender": odd})
        for name, args in (("nosuchtool_SECRETNAME", {"sender": "made-up-label"}), ("get", {"item_id": "SECRETITEM4", "sender": "refused-label"})):      # a made-up tool; a refused argument
            try: await c.call_tool(name, args)
            except Exception: pass
try:
    run(mcp_calls())
finally:
    stop(srv, th)
recs = lines(sorted(d.glob("requests-*.jsonl"))[0]); rt = [x for x in recs if not x.get("kind")]
tc = [x for x in rt if x["route"] == "tool:update"]
check("mcp_route: a tool call is tool:<name>, its sender the caller", len(tc) == 6 and [x for x in tc if x["caller"] == "tester-1"] and all(x["status"] == 200 and x["method"] == "POST" for x in tc), rt)
check("mcp_route: a call with no sender, and a call refused for an argument it does not take, are anon", [x["caller"] for x in rt if x["route"] == "tool:get"] == ["anon", "anon"], rt)
check("mcp_route: a known tool with a valid sender names it, with an odd one (spaces, markup, 200 characters, unicode, upper case) is anon", sorted(x["caller"] for x in rt if x["route"] == "tool:update") == ["anon"] * 5 + ["tester-1"], [x["caller"] for x in rt if x["route"] == "tool:update"])
check("mcp_route: a made-up tool and its sender: tool:{other}, anon", [x["caller"] for x in rt if x["route"] == "tool:{other}"] == ["anon"], rt)
check("mcp_route: no odd sender text reaches the file", not [t for t in ("made-up-label", "refused-label", "has spaces", "<b>", "x" * 50, "\u00fcn", "Upper-Case") if t in all_text(d)], all_text(d)[:300])
check("mcp_route: other messages are mcp:<method>", any(x["route"] == "mcp:tools/list" for x in rt) and any(x["route"] == "mcp:server/discover" for x in rt), [x["route"] for x in rt])
check("mcp_route: a tool name the server does not have is tool:{other}, its name is not kept", [x["route"] for x in rt if x["route"].startswith("tool:") and x["route"] not in ("tool:update", "tool:get")] == ["tool:{other}"] and "SECRETNAME" not in all_text(d), [x["route"] for x in rt])
check("mcp_route: no argument reaches the file", "SECRETITEM" not in all_text(d), all_text(d)[:300])
check("mcp_route: every request has a route that is not the bare endpoint for a call", not [x for x in rt if x["route"] == "/mcp" and x["method"] == "POST"], rt)
WR._LOG = None

# ------------------------------------------------------------------ 7 a log that cannot be written
bad = T / "notadir"; bad.write_text("a file where the directory should be")
mono = Clock(1000.0)
logw = RL.RequestLog(bad / "requests", clock=Clock(epoch("2026-11-22T00:00:00")), mono=mono, threaded=False)
appw = WR.RequestLogMiddleware(make_app(), requests=logw)
async def three():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appw), base_url="http://t") as c: return [(await c.get("/signin")).status_code for _ in range(3)]
err_io = io.StringIO()
with contextlib.redirect_stderr(err_io): codes = run(three())
check("write_failure: the requests are answered", codes == [200, 200, 200], codes)
check("write_failure: one stderr line for three failed writes", err_io.getvalue().count("request log: not written") == 1, err_io.getvalue())
mono.t += 601
err_io = io.StringIO()
with contextlib.redirect_stderr(err_io): run(three())
check("write_failure: again after ten minutes", err_io.getvalue().count("request log: not written") == 1, err_io.getvalue())
mono.t += 5
err_io = io.StringIO()
with contextlib.redirect_stderr(err_io): run(three())
check("write_failure: and not before", err_io.getvalue() == "", err_io.getvalue())
logw.close()

# ------------------------------------------------------------------ 8 files, gzip, retention, a half-written line
d, ck, log = fresh("f")
ck.t = epoch("2026-11-20T23:59:59.500"); log.write({"method": "GET", "route": "/a", "status": 200, "ms": 1.0, "bytes": 1, "caller": "anon"})
ck.t = epoch("2026-11-21T00:00:01.000"); log.write({"method": "GET", "route": "/b", "status": 200, "ms": 2.0, "bytes": 1, "caller": "anon"})
names = sorted(p.name for p in d.iterdir())
check("files: one file per UTC day, a finished day gzipped", names == ["requests-2026-11-20.jsonl.gz", "requests-2026-11-21.jsonl"], names)
check("files: the gzipped day holds its line, the new day its own", lines(d / "requests-2026-11-20.jsonl.gz")[0]["route"] == "/a" and lines(d / "requests-2026-11-21.jsonl")[0]["route"] == "/b")
check("files: the line sits in its own day by its ts", lines(d / "requests-2026-11-20.jsonl.gz")[0]["ts"] == "2026-11-20T23:59:59.500Z" and lines(d / "requests-2026-11-21.jsonl")[0]["ts"] == "2026-11-21T00:00:01.000Z")
check("files: no leftover temp file", not [p for p in d.iterdir() if p.name.endswith(".tmp")])
d, ck, log = fresh("r")
today = dt.date(2026, 11, 22)
old = lambda n: (today - dt.timedelta(days=n)).isoformat()
for n in (101, 95, 91):
    (d / f"requests-{old(n)}.jsonl").write_text('{"ts":"x"}\n')
with gzip.open(d / f"requests-{old(100)}.jsonl.gz", "wt") as g: g.write('{"ts":"x"}\n')
(d / f"requests-{old(90)}.jsonl").write_text('{"ts":"x"}\n'); (d / f"requests-{old(3)}.jsonl").write_text('{"ts":"x"}\n'); (d / "notes.txt").write_text("keep")
FOREIGN = ["other-2020-01-01.jsonl", "requests-2020-01-01.jsonl.bak", "Requests-2020-01-01.jsonl", "requests-2020-01-01.jsonl.gz.tmp", "old-requests-2020-01-01.jsonl.gz"]
for n_ in FOREIGN: (d / n_).write_text("keep")
(d / "requests-2020-01-02.jsonl.gz").mkdir()                          # a folder named like a day's file: left alone
ck.t = epoch("2026-11-22T12:00:00")
with contextlib.redirect_stderr(io.StringIO()): log.write({"method": "GET", "route": "/a", "status": 200, "ms": 1.0, "bytes": 1, "caller": "anon"})
left = sorted(p.name for p in d.iterdir())
check("files: a file more than 90 days old is deleted, plain or gzipped", not [n for n in left if any(old(k) in n for k in (101, 100, 95, 91))], left)
check("files: the 90th day is kept (gzipped), the recent day is gzipped, today's is plain, other files stay", left == sorted(["notes.txt", f"requests-{old(90)}.jsonl.gz", f"requests-{old(3)}.jsonl.gz", "requests-2026-11-22.jsonl", *FOREIGN, "requests-2020-01-02.jsonl.gz"]), left)
check("files: a file that only looks like a day's log (another prefix, suffix or case, a folder) is never touched, however old", all((d / n_).exists() for n_ in [*FOREIGN, "requests-2020-01-02.jsonl.gz"]) and (d / "requests-2020-01-02.jsonl.gz").is_dir(), left)
d, ck, log = fresh("t", threaded=True)
(d / "requests-2026-11-01.jsonl").write_text('{"ts":"x"}\n')
ck.t = epoch("2026-11-22T12:00:00"); log.write({"method": "GET", "route": "/a", "status": 200, "ms": 1.0, "bytes": 1, "caller": "anon"})
log.maintenance.join(10)
check("files: the clean-up runs in a thread of its own and finishes", (d / "requests-2026-11-01.jsonl.gz").exists() and not (d / "requests-2026-11-01.jsonl").exists() and log.maintenance is not None and not log.maintenance.is_alive())
d, ck, log = fresh("h")
(d / "requests-2026-11-22.jsonl").write_text('{"ts":"2026-11-22T00:00:00.000Z","route":"/old","ms":1,"status":200}\n{"ts":"2026-11-22T00:00:01.0')
ck.t = epoch("2026-11-22T12:00:00"); log.write({"method": "GET", "route": "/new", "status": 200, "ms": 3.0, "bytes": 1, "caller": "anon"}); log.close()
got = list(RL.read(d, epoch("2026-11-22T00:00:00"), epoch("2026-11-23T00:00:00")))
check("files: a half-written last line is not joined to the next, the reader skips it", [x["route"] for x in got] == ["/old", "/new"], got)
rd = list(RL.read(d, epoch("2026-11-22T11:00:00"), epoch("2026-11-22T13:00:00")))
check("files: the reader keeps only the range", [x["route"] for x in rd] == ["/new"], rd)

# ------------------------------------------------------------------ 9 the summary
d, ck, log = fresh("sum")
def put(t, route, ms, status=200, **kw):
    ck.t = epoch(t) if isinstance(t, str) else t
    log.write({"method": kw.pop("method", "GET"), "route": route, "status": status, "ms": ms, "bytes": 10, "caller": kw.pop("caller", "anon"), **kw})
base = "2026-11-21T15:"      # 00:xx in Asia/Seoul on the 22nd
for i, ms in enumerate(range(10, 101, 10)): put(f"{base}{i:02d}:00", "/p1", float(ms))
for i, ms in enumerate(range(1, 21)): put(f"{base}{20 + i:02d}:00", "/p2", float(ms), caller="box-a")
put(f"{base}45:00", "/p3", 5.0, 500, err="KeyError: 'x'"); put(f"{base}46:00", "/p4", 250.0, caller="slowpoke"); put(f"{base}47:00", "/p4", 175.0)
put(f"{base}30:30", "/p5", 7.0, 503); put(f"{base}31:30", "/p5", 9.0, 200, err="RuntimeError: x")
ck.t = epoch(f"{base}00:30"); log.write({"kind": "start", "pid": 77, "head": "abc1234", "mode": "inline"})
log.close()
recs_all = list(RL.read(d, epoch("2026-11-21T00:00:00"), epoch("2026-11-23T00:00:00")))
S = RS.summarize(recs_all, top=3)
rowof = lambda r: next(x for x in S["routes"] if x["route"] == r)
check("summary: p1 exact (n=10: p50 the 5th, p95 the 10th, max)", (rowof("/p1")["count"], rowof("/p1")["p50"], rowof("/p1")["p95"], rowof("/p1")["max"]) == (10, 50.0, 100.0, 100.0), rowof("/p1"))
check("summary: p2 exact (n=20: p50 the 10th, p95 the 19th)", (rowof("/p2")["count"], rowof("/p2")["p50"], rowof("/p2")["p95"], rowof("/p2")["max"]) == (20, 10.0, 19.0, 20.0), rowof("/p2"))
check("summary: one request is its own p50 and p95", (rowof("/p3")["p50"], rowof("/p3")["p95"], rowof("/p3")["errors5xx"]) == (5.0, 5.0, 1), rowof("/p3"))
check("summary: 5xx count per route", rowof("/p5")["errors5xx"] == 1 and rowof("/p1")["errors5xx"] == 0, S["routes"])
check("summary: routes by count, busiest first", [x["route"] for x in S["routes"]][:2] == ["/p2", "/p1"], [x["route"] for x in S["routes"]])
check("summary: totals and the error rate (a 5xx or a line with err)", S["requests"] == 35 and S["errors"] == 3 and abs(S["error_rate"] - 3 / 35) < 1e-9, (S["requests"], S["errors"]))
check("summary: the slowest calls, longest first, --top of them", [x["ms"] for x in S["slowest"]] == [250.0, 175.0, 100.0] and S["slowest"][0]["caller"] == "slowpoke", S["slowest"])
check("summary: the starts of the range", [(x["kind"], x["pid"], x["head"]) for x in S["events"]] == [("start", 77, "abc1234")], S["events"])
def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = RS.main(list(args))
    return rc, out.getvalue(), err.getvalue()
rc, out, _ = cli("summary", "--dir", str(d), "--tz", "Asia/Seoul", "--since", "2026-11-22", "--until", "2026-11-22", "--top", "3")
check("summary: the table, slowest, errors, starts and totals print", rc == 0 and re.search(r"/p1 +10 +50\.0 +100\.0 +100\.0 +0", out) and re.search(r"/p2 +20 +10\.0 +19\.0 +20\.0 +0", out) and "slowest calls" in out and "errors: 3" in out and "KeyError: 'x'" in out and "start  pid 77  head abc1234  mode inline" in out and "totals: 35 requests, 3 errors (8.57%)" in out, out)
check("summary: times print in the zone asked (Asia/Seoul: 15:00Z is 00:00 on the 22nd)", "2026-11-22 00:47:00" in out and "(Asia/Seoul)" in out and "2026-11-21 15:47" not in out, out)
rc, out_u, _ = cli("summary", "--dir", str(d), "--tz", "UTC", "--since", "2026-11-21", "--until", "2026-11-21")
check("summary: the same data in UTC prints UTC times and the date range is in that zone", rc == 0 and "2026-11-21 15:47:00" in out_u and "(UTC)" in out_u and "totals: 35 requests" in out_u, out_u)
rc, out_x, _ = cli("summary", "--dir", str(d), "--tz", "Asia/Seoul", "--since", "2026-11-21", "--until", "2026-11-21")
check("summary: a Seoul date does not include the Seoul next morning", rc == 0 and "no requests in range" in out_x, out_x)
rc, out_t, _ = cli("summary", "--dir", str(d), "--tz", "Asia/Seoul", "--since", "2026-11-22T00:47", "--until", "2026-11-22T00:48")
check("summary: a date and time in the zone", "totals: 1 requests" in out_t and "/p4" in out_t, out_t)
rc, out_o, _ = cli("summary", "--dir", str(d), "--tz", "Asia/Seoul", "--since", "2026-11-21T15:46:00Z", "--until", "2026-11-21T15:48:00+00:00")
check("summary: an offset or Z in the text is honored", "totals: 2 requests" in out_o, out_o)
rc, out_r, _ = cli("summary", "--dir", str(d), "--tz", "UTC", "--since", "2026-11-21", "--until", "2026-11-21", "--route", "p4")
check("summary: --route keeps the routes that contain the text", "totals: 2 requests" in out_r and "/p1" not in out_r and "/p4" in out_r, out_r)
rc, out_j, _ = cli("summary", "--dir", str(d), "--tz", "Asia/Seoul", "--since", "2026-11-22", "--until", "2026-11-22", "--top", "2", "--json")
J = json.loads(out_j)
check("summary: --json carries the same", rc == 0 and J["totals"] == {"requests": 35, "errors": 3, "error_rate": round(3 / 35, 6)} and J["range"]["timezone"] == "Asia/Seoul" and J["range"]["since"].endswith("+09:00")
      and [x["ms"] for x in J["slowest"]] == [250.0, 175.0] and J["slowest"][0]["time"] == "2026-11-22T00:46:00.000+09:00" and J["errors"]["count"] == 3 and J["events"][0]["kind"] == "start"
      and {x["route"]: x["p95"] for x in J["routes"]}["/p2"] == 19.0, out_j[:600])
rc, out_e, _ = cli("summary", "--dir", str(d), "--tz", "UTC", "--since", "2020-01-01", "--until", "2020-01-02")
check("summary: an empty range says so and exits 0", rc == 0 and "no requests in range" in out_e, out_e)
rc, out_e, _ = cli("summary", "--dir", str(T / "no-such-dir"), "--tz", "UTC", "--since", "7d")
check("summary: a missing directory is an empty range", rc == 0 and "no requests in range" in out_e, out_e)
rc, _, err_b = cli("summary", "--dir", str(d), "--tz", "UTC", "--since", "yesterdayish")
check("summary: a range it cannot read is refused, exit 2", rc == 2 and "yesterdayish" in err_b, (rc, err_b))
# relative times: records written against the real clock
dn = T / "rel"; dn.mkdir(); real = time.time()
lg = RL.RequestLog(dn, clock=Clock(real - 3600), threaded=False); lg.write({"method": "GET", "route": "/near", "status": 200, "ms": 4.0, "bytes": 1, "caller": "anon"}); lg.close()
lg = RL.RequestLog(dn, clock=Clock(real - 30 * 3600), threaded=False); lg.write({"method": "GET", "route": "/far", "status": 200, "ms": 6.0, "bytes": 1, "caller": "anon"}); lg.close()
count = lambda *a: re.search(r"totals: (\d+) requests", cli("summary", "--dir", str(dn), "--tz", "UTC", *a)[1])
n_of = lambda *a: (lambda m: int(m.group(1)) if m else 0)(count(*a))
check("summary: the default range is the last 24 hours", n_of() == 1)
check("summary: 48h reaches both", n_of("--since", "48h") == 2)
check("summary: 90m reaches the near one, 30m neither, 2d the far one", n_of("--since", "90m") == 1 and n_of("--since", "30m") == 0 and n_of("--since", "2d") == 2)
check("summary: --until back from now", n_of("--since", "48h", "--until", "2h") == 1)
check("summary: 24h is 24 hours, not 24 minutes or days", n_of("--since", "25h") == 1 and n_of("--since", "31h") == 2)
# plain, gz, a cut-short gz and a half-written last line in one directory
dg = T / "mix"; dg.mkdir()
row = lambda t, r, ms: json.dumps({"ts": RL.iso(epoch(t)), "method": "GET", "route": r, "status": 200, "ms": ms, "bytes": 1, "caller": "anon"}, separators=(",", ":")) + "\n"
with gzip.open(dg / "requests-2026-11-10.jsonl.gz", "wt") as g: g.write(row("2026-11-10T01:00:00", "/g", 1.0) + row("2026-11-10T01:00:01", "/g", 2.0))
whole = gzip.compress(("".join(row(f"2026-11-12T01:00:{i:02d}", "/cut", 1.0) for i in range(40))).encode())
(dg / "requests-2026-11-12.jsonl.gz").write_bytes(whole[: len(whole) * 6 // 10])
(dg / "requests-2026-11-14.jsonl").write_text(row("2026-11-14T01:00:00", "/plain", 1.0) + row("2026-11-14T01:00:01", "/plain", 3.0) + '{"ts":"2026-11-14T01:00:02.000Z","method":"GET","rou')
rc, out_m, _ = cli("summary", "--dir", str(dg), "--tz", "UTC", "--since", "2026-11-09", "--until", "2026-11-16")
check("summary: plain, gz, a cut-short gz and a half-written last line; a missing day between", rc == 0 and re.search(r"/g +2 ", out_m) and re.search(r"/plain +2 ", out_m) and re.search(r"/cut +\d+ ", out_m) and "KeyError" not in out_m, out_m)
check("summary: the cut-short gz gives what could be read, not all of it", 0 < int(re.search(r"/cut +(\d+) ", out_m).group(1)) < 40, out_m)
# the program is registered, and the default directory and zone are the instance's
from stackshot import cli as stackshot_cli
check("summary: registered as a program of the command line", "requests" in stackshot_cli.PROGRAMS and stackshot_cli.PROGRAMS["requests"][0] == "stackshot.tools.request_summary")
from stackshot.core import config as _cfg
inst = RL.RequestLog(_cfg.state("requests"), clock=Clock(real - 600), threaded=False); inst.write({"method": "GET", "route": "/inst", "status": 200, "ms": 8.0, "bytes": 1, "caller": "anon"}); inst.close()
out, err = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = stackshot_cli.main(["requests", "summary", "--since", "2h"])
check("summary: through `stackshot requests summary`, the default directory is <state>/requests and the zone [instance] timezone", rc == 0 and "/inst" in out.getvalue() and "(Asia/Dubai)" in out.getvalue(), (rc, out.getvalue()[:400], err.getvalue()[:300]))

# ------------------------------------------------------------------ 10 wiring in the real server
from stackshot.web import server
from stackshot.web.routes import client_api as _rt_client
from stackshot.fleet import client as _fclient
mw = server.mcp.middleware
names = [type(m).__name__ for m in mw]; i_ = names.index("RequestRoute") if "RequestRoute" in names else -1
check("wiring: the route hook is the first of the board's tool middleware (only FastMCP's own may come before it)", i_ >= 0 and all(type(m).__module__.startswith("fastmcp") for m in mw[:i_]), names)
check("wiring: the other tool middleware keep their order after it", names[i_ + 1:i_ + 6] == ["_Fingerprint", "_LinkIds", "_RefusalLog", "_ReadOnly", "_RetiredInputs"], names)
check("wiring: the server's http_app is the wrapper around FastMCP's app", isinstance(server.mcp.http_app(path="/mcp"), WR.RequestLogMiddleware) and server.mcp.http_app(path="/mcp").state is not None)
tok = open(_fclient.mint("box-far")).read().strip()
holder = {}; req = types.SimpleNamespace(scope={WR.KEY: holder})
got_m = _rt_client._client_machine("Bearer " + tok, req)
check("wiring: a client token's machine is the caller of its line", got_m == "box-far" and holder == {"caller": "box-far"}, (got_m, holder))
holder.clear(); got_m = _rt_client._client_machine("Bearer " + "x" * 40, req)
check("wiring: a wrong token names no one", got_m == "" and holder == {}, (got_m, holder))
# the client API's real handlers, behind the wrapper: a verb a handler took keeps its name, a guess is /client/{other}, with or without a token, on GET and POST
dcl, _, logcl = fresh("cl")
capp = WR.RequestLogMiddleware(Starlette(routes=[Route("/client/{what}", _rt_client.client_write, methods=["POST"]), Route("/client/{what}", _rt_client.client_api, methods=["GET"])]), requests=logcl)
AUTH = {"Authorization": "Bearer " + tok}
async def client_calls():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=capp, raise_app_exceptions=False), base_url="http://t") as c:
        out = {}
        out["whoami"] = await c.get("/client/whoami", headers=AUTH)
        out["poll"] = await c.post("/client/poll", json={"sessions": [], "wait": 0}, headers=AUTH)
        out["held"] = await c.post("/client/held", json={}, headers=AUTH)
        out["g404"] = await c.get("/client/scannerguess", headers=AUTH); out["p404"] = await c.post("/client/anotherguess", json={}, headers=AUTH)
        out["g401"] = await c.get("/client/scannerguess2"); out["p401"] = await c.post("/client/anotherguess2", json={})
        out["g401k"] = await c.get("/client/whoami")
        return out
CL = run(client_calls()); rcl = lines(sorted(dcl.glob("requests-*.jsonl"))[0]); rts = [(x["route"], x["status"]) for x in rcl if not x.get("kind")]
check("client verbs: the known ones keep their name: a read, a poll, a write the handler answered 400", ("/client/whoami", 200) in rts and ("/client/poll", 200) in rts and any(r == "/client/held" for r, _ in rts), (rts, [(k, v.status_code) for k, v in CL.items()]))
check("client verbs: guesses on GET and POST, 404 or 401, all collapse to one route", sorted(st for r, st in rts if r == "/client/{other}") == [401, 401, 401, 404, 404] and not any("guess" in r for r, _ in rts), rts)
check("client verbs: no guess is in the file, the known verbs' caller is the machine", "guess" not in all_text(dcl) and [x["caller"] for x in rcl if x.get("route") == "/client/whoami" and x["status"] == 200] == ["box-far"], all_text(dcl)[:400])
check("client verbs: template alone never keeps the verb, whatever the status", {WR.template("/client/anything", {"what": "anything"}, st, True) for st in (200, 204, 301, 401, 404, 500)} == {"/client/{other}"})
from stackshot.core import readonly as _ro
_was = _ro.is_read_only
try:
    _ro.is_read_only = lambda: True
    probe = FastMCP("probe"); WR.install(probe)
    check("wiring: install does nothing on a read-only standby copy", not isinstance(probe.http_app(path="/mcp"), WR.RequestLogMiddleware))
finally:
    _ro.is_read_only = _was

# the day is read under the lock: a writer that waited for it uses the clock of its own turn, so a line never reopens a day that was gzipped meanwhile
held = []
dl = T / "lockclock"; dl.mkdir()
lock_log = RL.RequestLog(dl, clock=lambda: (held.append(lock_log._lock.locked()), epoch("2026-11-22T00:00:01"))[1], threaded=False)
lock_log.write({"route": "/a", "status": 200}); lock_log.write({"route": "/b", "status": 200}); lock_log.close()
check("files: the clock is read while the lock is held", held and all(held), held)

# ------------------------------------------------------------------ 11 cost and size (printed)
class Bare:
    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]}); await send({"type": "http.response.body", "body": b"ok"})
async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
async def send_null(m): return None
def scope(): return {"type": "http", "method": "GET", "path": "/client/items", "query_string": b"a=1", "headers": [], "path_params": {"what": "items"}, "endpoint": print}
async def bench(app, n):
    t = time.perf_counter()
    for _ in range(n): await app(scope(), receive, send_null)
    return (time.perf_counter() - t) / n * 1e6
dc = T / "cost"; dc.mkdir()
N = 20000
bare_us = run(bench(Bare(), N))
nowrite_us = run(bench(WR.RequestLogMiddleware(Bare(), requests=types.SimpleNamespace(write=lambda r: None)), N))
full_us = run(bench(WR.RequestLogMiddleware(Bare(), requests=RL.RequestLog(dc)), N))
print(f"COST per request: bare app {bare_us:.1f} us; wrapper without the file write {nowrite_us - bare_us:.1f} us over it; wrapper with the line written {full_us - bare_us:.1f} us over it")
check("cost: the wrapper adds well under a millisecond per request", full_us - bare_us < 1000, (bare_us, full_us))
# a day at the measured mix of routes (about 26,000 requests): plain and gzipped size
import random
random.seed(7)
mix = [("/client/items", "GET", "demo-a", 0.37), ("/", "GET", "anon", 0.24), ("/client/poll", "POST", "demo-b", 0.14), ("tool:update", "POST", "my-session-a", 0.075), ("/client/roles", "GET", "demo-a", 0.04),
       ("/client/held", "POST", "demo-b", 0.02), ("/healthz", "GET", "anon", 0.012), ("/client/item-facts", "GET", "demo-a", 0.012), ("/receivers.json", "GET", "anon", 0.01), ("/audit/status", "GET", "anon", 0.007), ("/render-stamp", "GET", "anon", 0.007), ("tool:get", "POST", "my-session-b", 0.067)]
dd = T / "size"; dd.mkdir(); csz = Clock(epoch("2026-11-01T00:00:00")); big = RL.RequestLog(dd, clock=csz, threaded=False)
for i in range(26000):
    csz.t += 86400 / 26000; r = random.random(); acc = 0.0
    for route, method, caller, w in mix:
        acc += w
        if r < acc: break
    big.write({"method": method, "route": route, "status": 200 if random.random() > 0.002 else 500, "ms": round(random.lognormvariate(2.2, 0.9), 1), "bytes": int(random.lognormvariate(7.5, 1.2)), "caller": caller})
big.close(); csz.t += 86400; big2 = RL.RequestLog(dd, clock=csz, threaded=False); big2.write({"kind": "x"}); big2.close()
plain = len(gzip.open(dd / "requests-2026-11-01.jsonl.gz", "rt").read().encode())
gz = (dd / "requests-2026-11-01.jsonl.gz").stat().st_size
print(f"SIZE a day of 26000 requests: {plain / 1e6:.2f} MB plain, {gz / 1e6:.2f} MB gzipped; 90 days gzipped about {gz * 90 / 1e6:.0f} MB")
check("cost: 90 days of such days, gzipped, stay well under 300 MB", gz * 90 < 300e6 and gz < plain / 3, (plain, gz))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
