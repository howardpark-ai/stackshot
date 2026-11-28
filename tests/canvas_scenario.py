"""Scenario test for canvases: pages an agent shares with the board's owner, kept and served by the board (docs/canvas.md) — fixture data, the HTTP routes
through Starlette's test client, no live store, no network.

Covers: POST /client/canvas-import is refused unless [canvas] import is true, needs a machine token, keeps a page's number, version ids, bytes, hash and times, can be rerun (the same
content is skipped, different content is refused unless newer, a version never changes), and refuses bad input with nothing written; a standby takes no import. Both read routes, /canvas/<n> and
/canvas/<n>/versions/<id>, open an imported page in a shell whose frame is sandboxed with scripts only, and the raw route serves the stored bytes unchanged. Every answer under /canvas and
/mockup, signed in and signed out (pages, redirects, 401, 404, 405, 500, the standby's 503), carries the isolation headers. Creating and editing through /canvas is refused. A page that runs in
the frame has an opaque origin, which no write route of the board accepts. No GET route of the board changes its state, and a request that comes from a canvas neither signs out, renews nor starts a sign-in.
What a browser enforces from these headers is tests/canvas_check.py (CI).

    tests/run-suite canvas        → exit 0 / 1"""
import base64, hashlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="canvastest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
TOKEN = "canvas-test-token-" + "x" * 30


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "agents": {}, "back_agents": {}, "status": "active", "board": [], "board_open": 0}}}))
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item a1", "description": "A thing. It lives here. Finished when it works.", "status": "open",
                                              "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                              "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", "needs": ["decision"],
                                                           "ask": "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"}}))
(T / "secrets/clients.json").write_text(json.dumps({"testbox": {"sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}}))

from starlette.testclient import TestClient
from stackshot.web import server
from stackshot.web import answers as _web_answers
from stackshot.web.auth import signin as _signin
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

FAILS = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"  :: {str(detail)[:600]}"), flush=True)
    if not ok:
        FAILS.append(name)


_signin._auth_mode = lambda: "oauth"          # the board's own sign-in on, [auth] ui_open = false as this config has it
COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))       # an hour left of its days: a visit renews it
AUTH = {"Authorization": "Bearer " + TOKEN}
CANVAS_STORE = T / "state/canvas"


def tree(*roots):
    """{path: hash} of every file under the instance's folders; lock files and the request log (a line for every request) left out."""
    out = {}
    for base in roots or ("state", "store", "secrets", "brain"):
        for p in sorted((T / base).rglob("*")):
            if p.is_file() and not p.name.endswith(".lock") and not str(p.relative_to(T)).startswith("state/requests/"):
                out[str(p.relative_to(T))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


V1, V2 = "20261101T080000.000001Z", "20261102T093000.500000Z"
PAGE = ('<!doctype html><meta name="viewport" content="width=device-width"><title>Plan</title><body data-m="current">' + chr(0xE9) + '<script>1</script></body>').encode()
OLD1 = b'<!doctype html><title>Plan</title><body data-m="first">one</body>'
OLD2 = b'<!doctype html><title>Plan</title><body data-m="second">two</body>'
T0 = 1790000000.25


def sha(b):
    return hashlib.sha256(b).hexdigest()


def body(content=PAGE, number=7, version=None, modified=T0, **more):
    d = {"number": number, "version": version, "content": base64.b64encode(content).decode(), "bytes": len(content), "sha256": sha(content), "modified": modified}
    d.update(more)
    return d


# ---- every answer under /canvas and /mockup
RAW_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; "
           "img-src data:; media-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
SHELL_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; font-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
SEEN = []


def headers_ok(label, r, shell=False):
    got = {k: r.headers.get_list(k) for k in ("content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy", "cache-control")}
    want = {"content-security-policy": [SHELL_CSP if shell else RAW_CSP], "x-frame-options": ["SAMEORIGIN"], "x-content-type-options": ["nosniff"],
            "referrer-policy": ["no-referrer"], "cache-control": ["no-store"]}
    check(f"headers: {label} ({r.status_code}) carries the isolation headers, once each", got == want, got)
    if not shell:
        check(f"headers: {label} ({r.status_code}) sets no cookie", "set-cookie" not in r.headers, r.headers.get("set-cookie"))
    SEEN.append(r.status_code)


with TestClient(server.mcp.http_app(), base_url=BOARD, raise_server_exceptions=False) as c:
    def req(method, path, cookie=COOKIE, headers=None, **kw):
        c.cookies.clear()
        if cookie:
            c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.request(method, path, headers=headers or {}, follow_redirects=False, **kw)

    def get(path, cookie=COOKIE, headers=None):
        return req("GET", path, cookie, headers)

    def post(b, headers=AUTH, **kw):
        return req("POST", "/client/canvas-import", None, headers, json=b, **kw)

    # ---------------------------------------------------------------- 1. the import is off by default
    before = tree()
    r = post(body())
    check("import: off by default, refused with 403", r.status_code == 403 and "[canvas] import" in r.text, (r.status_code, r.text))
    check("import: refused while off, nothing written", not CANVAS_STORE.exists() or not changed(before, tree()), changed(before, tree()))
    for value in ("true", "false", 1, 0):
        _cfg.CFG.setdefault("canvas", {})["import"] = value
        r = post(body())
        check(f"import: [canvas] import = {value!r} is not true, so it stays off", r.status_code == 403, (r.status_code, r.text))
    _cfg.CFG["canvas"]["import"] = True
    r = post(body(), headers={})
    check("import: no machine token, 401", r.status_code == 401, r.status_code)
    r = post(body(), headers={"Authorization": "Bearer " + "y" * 40})
    check("import: a wrong token, 401", r.status_code == 401, r.status_code)

    # ---------------------------------------------------------------- 2. bad input writes nothing
    big = b"a" * (5 * 1024 * 1024 + 1)
    drop = lambda b, k: {x: y for x, y in b.items() if x != k}
    BAD = [("number zero", body(number=0)), ("number as text", body(number="7")), ("number true", body(number=True)), ("number of 11 digits", body(number=10 ** 10)),
           ("number missing", drop(body(), "number")), ("version missing", drop(body(), "version")), ("version not an id", body(version="x")),
           ("version of no real date", body(version="20261301T000000.000000Z")), ("version with a path", body(version="../../x")),
           ("content not base64", {**body(), "content": "***"}), ("content not text", {**body(), "content": 5}), ("content empty", body(content=b"")),
           ("content with a NUL", body(content=b"<p>\x00</p>")), ("content not UTF-8", body(content=b"<p>\xff\xfe</p>")), ("content over 5 MiB", body(content=big)),
           ("byte count wrong", {**body(), "bytes": len(PAGE) + 1}), ("byte count missing", drop(body(), "bytes")), ("hash wrong", {**body(), "sha256": "0" * 64}),
           ("hash missing", drop(body(), "sha256")), ("time missing", drop(body(), "modified")), ("time as text", body(modified="yesterday")),
           ("time negative", body(modified=-1)), ("time true", body(modified=True)), ("item not an id", body(item="nonsense")), ("item not text", body(item=5)),
           ("title not text", body(title=["x"])), ("title too long", body(title="t" * 201)), ("session too long", body(session="s" * 101)),
           ("counter not a number", body(counter="40")), ("counter negative", body(counter=-1)), ("an unknown key", body(vesion=V1)),
           ("a title on a version", body(content=OLD1, version=V1, title="Plan")), ("an item on a version", body(content=OLD1, version=V1, item="a1"))]
    before = tree()
    for label, b in BAD:
        r = post(b)
        check(f"import: bad input refused ({label})", r.status_code in (400, 413) and r.headers.get("content-type", "").startswith("application/json") and r.json().get("error"), (r.status_code, r.text[:200]))
    r = req("POST", "/client/canvas-import", None, {**AUTH, "Content-Type": "application/json"}, content=b"{" + b" " * (8 * 1024 * 1024))
    check("import: a body over the cap is refused with 413", r.status_code == 413, (r.status_code, r.text[:200]))
    for label, raw in (("not JSON", b"{nope"), ("a list", b"[1]")):
        r = req("POST", "/client/canvas-import", None, {**AUTH, "Content-Type": "application/json"}, content=raw)
        check(f"import: bad input refused ({label})", r.status_code == 400, (r.status_code, r.text[:200]))
    check("import: nothing at all written by any refused call", not changed(before, tree()), changed(before, tree()))

    # ---------------------------------------------------------------- 3. a sample set keeps numbers and version ids
    r = post(body(content=OLD1, version=V1, modified=T0 - 200, session="home-here"))
    check("import: a version may come before the current page", r.status_code == 200 and r.json().get("result") == "added", (r.status_code, r.text))
    check("import: a number with versions and no current page is not served", get("/canvas/7").status_code == 404 and get(f"/canvas/7/versions/{V1}").status_code == 404)
    r = post(body(title="Release plan", item="a1", session="home-here"))
    check("import: the current page is added", r.status_code == 200 and r.json() == {"ok": True, "number": 7, "version": None, "result": "added", "sha256": sha(PAGE)}, (r.status_code, r.text))
    r = post(body(content=OLD2, version=V2, modified=T0 - 100))
    check("import: a second version is added", r.status_code == 200 and r.json().get("version") == V2, (r.status_code, r.text))
    big_ok = b"<p>" + b"a" * (5 * 1024 * 1024 - 3)
    r = post(body(content=big_ok, number=3, item="a12"))
    check("import: a page of exactly 5 MiB is taken", r.status_code == 200, (r.status_code, r.text[:200]))
    r = post(body(content=OLD1, number=12, counter=40))
    check("import: a page with no item", r.status_code == 200, (r.status_code, r.text))
    try:
        rec = json.loads((CANVAS_STORE / "7/canvas.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        rec = {"error": str(e)}
    check("store: the record keeps the number, title, item, times, writer, hashes and version ids",
          rec.get("number") == 7 and rec.get("title") == "Release plan" and rec.get("item") == "a1"
          and rec.get("current") == {"sha256": sha(PAGE), "bytes": len(PAGE), "modified": T0, "session": "home-here"}
          and rec.get("versions") == [{"id": V1, "sha256": sha(OLD1), "bytes": len(OLD1), "modified": T0 - 200, "session": "home-here"},
                                      {"id": V2, "sha256": sha(OLD2), "bytes": len(OLD2), "modified": T0 - 100, "session": ""}], rec)
    kept = {p.name: p.read_bytes() for p in (CANVAS_STORE / "7").glob("*.html")} if CANVAS_STORE.exists() else {}
    check("store: each content is kept byte for byte under its hash", kept == {sha(x) + ".html": x for x in (PAGE, OLD1, OLD2)}, sorted(kept))
    counter = (CANVAS_STORE / "counter").read_text().strip() if (CANVAS_STORE / "counter").is_file() else ""
    check("store: the counter holds the highest number ever given, the imported one included", counter == "40", counter)
    r = post(body(content=OLD1, number=2, counter=5))
    check("store: the counter never goes down", r.status_code == 200 and (CANVAS_STORE / "counter").read_text().strip() == "40", (r.status_code, r.text))
    check("store: it is outside the board's git store", not any("canvas" in k for k in tree("store")))

    # ---------------------------------------------------------------- 4. a rerun
    before = tree()
    for label, b in (("current", body(title="Release plan", item="a1", session="home-here")), ("version", body(content=OLD1, version=V1, modified=T0 - 200, session="home-here"))):
        r = post(b)
        check(f"rerun: the same {label} is skipped", r.status_code == 200 and r.json().get("result") == "unchanged", (r.status_code, r.text))
    for label, b in (("older", body(content=OLD2, modified=T0 - 1)), ("as old", body(content=OLD2, modified=T0)), ("a changed version", body(content=OLD2, version=V1, modified=T0 + 999))):
        r = post(b)
        check(f"rerun: different content is refused ({label})", r.status_code == 409 and r.json().get("error"), (r.status_code, r.text))
    check("rerun: skipped and refused calls write nothing", not changed(before, tree()), changed(before, tree()))
    newer = b"<p>newer</p>"
    r = post(body(content=newer, number=12, modified=T0 + 10, title="Twelve"))
    check("rerun: newer content replaces the current page", r.status_code == 200 and r.json().get("result") == "replaced", (r.status_code, r.text))
    check("rerun: the replaced bytes are still on disk", (CANVAS_STORE / "12" / (sha(OLD1) + ".html")).is_file())
    check("rerun: the new page is served", get("/canvas/12/raw").content == newer)
    r = post(body(content=newer, number=12, modified=T0 + 20, title="Twelve", item="a1"))
    check("rerun: the same content with a newer time updates the record", r.status_code == 200 and r.json().get("result") == "updated" and 'href="/items/a1"' in get("/canvas/12").text, (r.status_code, r.text))

    # ---------------------------------------------------------------- 5. the read routes
    r = get("/canvas/7")
    frames = re.findall(r"<iframe\b[^>]*>", r.text)
    check("link: /canvas/<n> opens the imported page", r.status_code == 200 and len(frames) == 1 and 'src="/canvas/7/raw"' in frames[0], (r.status_code, frames))
    check("shell: the frame is sandboxed with scripts only", len(frames) == 1 and re.findall(r'sandbox="([^"]*)"', frames[0]) == ["allow-scripts"], frames)
    check("shell: the number, the title, the item's link, the way back to the board", all(x in r.text for x in ("Canvas 7", "Release plan", 'href="/items/a1"', 'href="/"')), r.text[-1500:])
    hrefs = re.findall(r'href="(/canvas/7/versions/[^"]+)"', r.text)
    check("shell: one history control listing the versions, newest first, with their times", r.text.count("<details") == 1 and hrefs == [f"/canvas/7/versions/{V2}", f"/canvas/7/versions/{V1}"]
          and "Until Sun Nov 1st" in r.text and "12:00" in r.text, (hrefs, r.text[-1500:]))
    check("shell: no script of its own, fits a phone", "<script" not in r.text and 'name="viewport"' in r.text)
    headers_ok("the shell", r, shell=True)
    r = get(f"/canvas/7/versions/{V1}")
    check("link: /canvas/<n>/versions/<id> opens the imported version", r.status_code == 200 and f'src="/canvas/7/versions/{V1}/raw"' in r.text and 'href="/canvas/7"' in r.text
          and 'sandbox="allow-scripts"' in r.text, (r.status_code, r.text[-1500:]))
    headers_ok("a version's shell", r, shell=True)
    r = req("HEAD", "/canvas/7")
    check("shell: HEAD answers", r.status_code == 200, r.status_code)
    headers_ok("the shell, HEAD", r, shell=True)
    r = get("/canvas/12")
    check("shell: a canvas with no version has no history control", r.status_code == 200 and "<details" not in r.text, r.status_code)
    for path, want in (("/canvas/7/raw", PAGE), (f"/canvas/7/versions/{V1}/raw", OLD1), (f"/canvas/7/versions/{V2}/raw", OLD2), ("/canvas/3/raw", big_ok)):
        r = get(path, headers={"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin"})
        check(f"raw: {path} is the stored bytes, nothing added", r.status_code == 200 and r.content == want and r.headers.get("content-type") == "text/html; charset=utf-8", (r.status_code, r.headers.get("content-type"), r.content[:80]))
        headers_ok(path, r)
    headers_ok("raw, HEAD", req("HEAD", "/canvas/7/raw"))

    # ---------------------------------------------------------------- 6. the headers on everything else
    MISSING = ("/canvas", "/canvas/", "/canvas/0", "/canvas/abc", "/canvas/07", "/canvas/99", "/canvas/99/raw", "/canvas/7/", "/canvas/7/versions", "/canvas/7/versions/x",
               "/canvas/7/versions/20991231T000000.000000Z", "/canvas/7/versions/20991231T000000.000000Z/raw", "/canvas/7/nope", "/canvas/7/canvas.json",
               f"/canvas/7/{sha(PAGE)}.html", "/mockup", "/mockup/7", "/mockup/7/raw", BOARD + "//canvas/7/x", "/canv%61s/99")      # a doubled slash is written whole: alone it would be read as a host name
    for path in MISSING:
        r = get(path)
        check(f"routes: {path} serves nothing", r.status_code == 404 and b"data-m" not in r.content, (r.status_code, r.content[:80]))
        headers_ok(path, r)
    PAGES = ("/canvas/7", f"/canvas/7/versions/{V1}", "/canvas/7/raw", f"/canvas/7/versions/{V1}/raw", "/canvas", "/canvas/99", "/mockup/7", "/canvas/7/nope")
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        before = tree()
        for path in PAGES[:4]:
            r = req(method, path, headers={"Origin": BOARD}, content=b"<p>mine</p>")
            check(f"writes: {method} {path} is refused", r.status_code == 405 and r.headers.get("allow") == "GET, HEAD" and (method == "OPTIONS" or "cutover" in r.text), (r.status_code, r.text[:100]))
            headers_ok(f"{method} {path}", r)
        for path in PAGES[4:]:
            r = req(method, path, headers={"Origin": BOARD}, content=b"x")
            check(f"writes: {method} {path} is refused", r.status_code in (404, 405), r.status_code)
            headers_ok(f"{method} {path}", r)
        check(f"writes: {method} under /canvas changes nothing", not changed(before, tree()), changed(before, tree()))
    for path in PAGES:
        for label, h in (("a browser", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}), ("a frame", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"}), ("a script", {"Sec-Fetch-Mode": "cors"})):
            for cookie in (None, "forged.cookie"):
                r = get(path, cookie=cookie, headers=h)
                check(f"signed out: {path} ({label}) shows no page", r.status_code in (302, 401, 404) and b"data-m" not in r.content and b"Release plan" not in r.content, (r.status_code, r.content[:80]))
                if path.endswith("/raw"):
                    check(f"signed out: {path} ({label}) is a plain 401, never a redirect inside the frame", r.status_code == 401 and "location" not in r.headers, (r.status_code, r.headers.get("location")))
                headers_ok(f"signed out {path} ({label})", r)
    r = get("/canvas/7", cookie=None, headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
    check("signed out: a browser opening a canvas is sent to sign in and back", r.status_code == 302 and r.headers.get("location") == "/ui/login?next=%2Fcanvas%2F7", (r.status_code, r.headers.get("location")))
    try:
        from stackshot.service import canvas as _canvas
        real = _canvas.read

        def boom(*a, **k):
            raise RuntimeError("forced")

        _canvas.read = boom
        try:
            for path in ("/canvas/7", "/canvas/7/raw"):
                r = get(path)
                check(f"500: {path} fails closed", r.status_code == 500, r.status_code)
                headers_ok(f"500 {path}", r)
        finally:
            _canvas.read = real
    except ImportError as e:
        check("500: a failing canvas route carries the headers", False, e)

    # ---------------------------------------------------------------- 7. the standby serves reads and takes no write
    _ro._RO = True
    try:
        before = tree()
        r = post(body(content=b"<p>s</p>", number=20))
        check("standby: the import is refused", r.status_code == 503, (r.status_code, r.text[:100]))
        r = get("/canvas/7/raw")
        check("standby: the raw page is served unchanged, no banner", r.status_code == 200 and r.content == PAGE, (r.status_code, r.content[:120]))
        headers_ok("standby raw", r)
        r = get("/canvas/7")
        check("standby: the shell is served", r.status_code == 200 and 'src="/canvas/7/raw"' in r.text, r.status_code)
        headers_ok("standby shell", r, shell=True)
        r = req("POST", "/canvas/7", headers={"Origin": BOARD})
        check("standby: a write under /canvas is refused", r.status_code == 503, r.status_code)
        headers_ok("standby write", r)
        check("standby: nothing written", not changed(before, tree()), changed(before, tree()))
    finally:
        _ro._RO = False

    # ---------------------------------------------------------------- 8. a page in the frame cannot write the board
    routes = [(getattr(x, "path", ""), set(getattr(x, "methods", None) or ())) for x in c.app.routes]
    fill = lambda p: p.replace("{name:path}", "x").replace("{key}", "a1").replace("{n}", "7").replace("{id}", V1).replace("{what}", "message").replace("{key:path}", "projects/alpha")
    writes = sorted({fill(p) for p, m in routes if m & {"POST", "PUT", "PATCH", "DELETE"} and p not in ("/mcp",) and not p.startswith("/keys/")})
    check("opaque origin: the board's write routes are found", len(writes) >= 8 and "/items/a1/answer" in writes, writes)
    FRAME = {"Origin": "null", "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
    token = _web_answers._answer_token(EMAIL, "a1")
    before = tree()
    for path in writes:
        r = req("POST", path, headers=FRAME, data={"act": "answer", "answer": "from a canvas", "token": token, "on": "1", "lang": "en"})
        check(f"opaque origin: POST {path} is refused", r.status_code >= 400, (r.status_code, r.text[:100]))
    check("opaque origin: no write route changed anything", not changed(before, tree()), changed(before, tree()))

    # ---------------------------------------------------------------- 9. no board GET changes state
    def gets():
        out = set()
        for p, m in routes:
            if "GET" not in m or p == "/mcp":
                continue
            if p == "/{name:path}":
                out |= {"/" + x for x in ("items/a1", "items/1", "projects/alpha", "board.md", "receivers.json", "healthz", "healthz.json", "versions.json", "favicon.svg", "manifest.webmanifest", "nothing", "canvas/7/x")}
            else:
                u = fill(p)
                out.add(u)
                if p == "/search":
                    out.add(u + "?q=item")
        return sorted(out)

    urls = gets()
    check("GET: the board's GET routes are found", len(urls) >= 25 and {"/", "/ui/logout", "/ui/login", "/canvas/7", "/canvas/7/raw", "/items/a1/answer-frame", "/audit/now"} <= set(urls), urls)
    BROWSER = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "cross-site"}       # a canvas open as its own tab sending its window to a board address
    before = tree()
    for u in urls:
        for h in ({"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"}, BROWSER):
            for q in ("", "?next=/&act=1&q=a&on=1"):
                if q and "?" in u:
                    continue
                r = get(u + q, headers=h)
                cookies = r.headers.get_list("set-cookie")
                if h["Sec-Fetch-Dest"] == "iframe":
                    check(f"GET from a frame: {u + q} sets no cookie", not cookies, cookies)
                else:
                    check(f"GET from another origin: {u + q} does not drop the sign-in", not any(x.startswith(_signin._UI_COOKIE + "=") and ("Max-Age=0" in x or '=""' in x) for x in cookies), cookies)
    time.sleep(2)       # a draw or a refresh a GET started in a thread has finished
    CACHES = re.compile(r"^state/(search/|runners-snapshot)")      # derived files, rebuilt from the board or its runners: no page, item, answer or setting
    moved = [k for k in changed(before, tree()) if not CACHES.match(k)]
    check("GET: no GET route changed the board's state", not moved, moved)

    # ---------------------------------------------------------------- 10. the sign-in routes, as a person and as a canvas reach them
    OWN = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"}
    dropped = lambda r: any(x.startswith(_signin._UI_COOKIE + "=") for x in r.headers.get_list("set-cookie"))
    for label, h in (("a canvas frame", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"}), ("a canvas tab", BROWSER),
                     ("a frame on the board", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}),
                     ("a picture", {"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image", "Sec-Fetch-Site": "cross-site"}),
                     ("another site's link", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "same-site"})):
        r = get("/ui/logout", headers=h)
        check(f"sign-out: refused from {label}", r.status_code == 403 and not dropped(r), (r.status_code, r.headers.get_list("set-cookie")))
    for label, h in (("typed in the browser", OWN), ("a link on the board", {**OWN, "Sec-Fetch-Site": "same-origin"}), ("a browser or tool that sends no such headers", {})):
        r = get("/ui/logout", headers=h)
        check(f"sign-out: works when {label}", r.status_code == 200 and dropped(r), (r.status_code, r.headers.get_list("set-cookie")))
    real_client = _signin._ui_client_id
    asked = []
    _signin._ui_client_id = lambda: asked.append(1) or "board-client"
    try:
        r = get("/ui/login", cookie=None, headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"})
        check("sign-in: a frame starts none (401, no cookie, no client)", r.status_code == 401 and not r.headers.get_list("set-cookie") and not asked, (r.status_code, r.headers.get_list("set-cookie"), asked))
        r = get("/ui/login", cookie=None, headers={**OWN, "Sec-Fetch-Site": "cross-site"})
        check("sign-in: a link from elsewhere opened as a page still signs in", r.status_code == 302 and r.headers.get_list("set-cookie") and asked, (r.status_code, asked))
    finally:
        _signin._ui_client_id = real_client
    r = get("/", headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"})
    check("renewal: a board page opened by a canvas frame does not renew the sign-in", not dropped(r), r.headers.get_list("set-cookie"))
    for label, h in (("a person", OWN), ("a link from elsewhere", {**OWN, "Sec-Fetch-Site": "cross-site"}), ("a frame on a sibling address", {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-site"})):
        r = get("/items/a1", headers=h)
        check(f"renewal: a visit by {label} renews the sign-in as before", r.status_code == 200 and dropped(r), (r.status_code, r.headers.get_list("set-cookie")))
    check("headers: the refusals a canvas address can give were all met", {200, 302, 401, 404, 405, 500, 503} <= set(SEEN), sorted(set(SEEN)))

print(f"\n{len(FAILS)} failed" + ("" if not FAILS else ": " + "; ".join(FAILS[:40])), flush=True)
sys.stdout.flush()
os._exit(1 if FAILS else 0)
