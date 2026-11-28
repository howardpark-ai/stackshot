"""Canvas check (a browser; run by .github/workflows/canvas.yml, not in the suite loop). The routes, the headers and the store are tests/canvas_scenario.py; this is what only a browser shows: that
the headers and the frame's sandbox do keep a stored page apart from the board. It starts the server in-process over HTTPS on localhost with a temporary config and fixture data (no live store, no
network beyond this machine), and a second server on another port, which is another origin. A browser signed in with the board's cookie then checks that:

  - the shell's frame shows the imported page, and a version opens from the history control, at 390 px with nothing scrolling sideways;
  - the page, in the frame and opened as a tab of its own, has an opaque origin: no cookie, no storage, no reach into the shell, and no request to the board (fetch, XHR, beacon, socket, image, form,
    popup), so the item it aims at is unchanged;
  - the frame cannot send itself or the shell's window to another origin: the other server gets nothing;
  - the frame sent to /ui/logout, and the page's own tab sent there, sign nobody out;
  - a reload and a board address inside the frame: what they show is printed; neither writes anything nor sends the browser to sign in;
  - a page on another origin cannot frame it;
  - a page of `data-tip` spans gets the shared tooltip, which opens on a click, never on hover alone, and closes on a second click, a click outside or Esc, inside the screen; a page with no link color
    gets the default one.

    tests/run-suite canvas_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    CANVAS_SHOTS=<folder> also saves screenshots there."""
import base64, hashlib, http.server, json, logging, os, pathlib, re, socket, ssl, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="canvaschk-"); T = pathlib.Path(tmp)
SHOTS = os.environ.get("CANVAS_SHOTS", "")
EMAIL = "oliver@example.org"

subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout", str(T / "tls.key"), "-out", str(T / "tls.crt")], check=True, capture_output=True)
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); TLS.load_cert_chain(str(T / "tls.crt"), str(T / "tls.key"))
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BOARD = f"https://localhost:{PORT}"
OUTSIDE_GOT = []        # every request the other origin received


class Quiet(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):      # a browser drops a connection it opened ahead of need, and says so about the self-signed certificate: no finding of this check
        if not isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError)): super().handle_error(request, client_address)


class Outside(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        OUTSIDE_GOT.append(self.path)
        body = (f'<!doctype html><title>outside</title><body>outside<iframe src="{BOARD}/canvas/1/raw"></iframe>' if self.path.startswith("/framer") else "<!doctype html><title>outside</title><body>outside").encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


OUT_SRV = Quiet(("127.0.0.1", 0), Outside); OUT_SRV.daemon_threads = True
OUT_SRV.socket = TLS.wrap_socket(OUT_SRV.socket, server_side=True, do_handshake_on_connect=False)
threading.Thread(target=OUT_SRV.serve_forever, daemon=True).start()
OUTSIDE = f"https://localhost:{OUT_SRV.server_address[1]}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                 (r'(?m)^import = false', 'import = true')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] zebraword item", "description": "Background words.", "status": "open", "updated": now - 3600, "state_updated": now - 3600,
                                              "confirmed": now - 3600, "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step"}}))
(T / "store/next-id").write_text("30"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")


def git(*a): subprocess.run(["git", "-C", str(T / "store"), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)


git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn
from stackshot.web import server
from stackshot.web.auth import signin as _signin
from stackshot.service import canvas as _canvas
_signin._auth_mode = lambda: "oauth"          # the board's own sign-in on

# the stored page: its own script tries everything, then writes down what happened
PROBE = """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>probe</title><body><h1>probe page</h1><a id="blank" href="__BOARD__/?from=blank" target="_blank">window</a><pre id="out"></pre><script>
(async () => {
  const B = '__BOARD__', r = {};
  const t = async (k, f) => { try { r[k] = String(await Promise.race([f(), new Promise((_, no) => setTimeout(() => no(new Error('timeout')), 3000))])) } catch (e) { r[k] = 'refused:' + e.name } };
  await t('origin', () => self.origin);
  await t('cookie', () => document.cookie);
  await t('storage', () => localStorage.length);
  await t('session', () => sessionStorage.length);
  if (parent !== self) { await t('parent', () => parent.document.title); await t('top', () => top.location.href); }
  await t('fetch', () => fetch(B + '/items/a1?from=probe', {credentials: 'include'}).then(x => x.status));
  await t('post', () => fetch(B + '/items/a1/answer?from=probe', {method: 'POST', mode: 'no-cors', credentials: 'include', body: new URLSearchParams({act: 'comment', answer: 'from the canvas'})}).then(x => x.status));
  await t('xhr', () => new Promise((ok, no) => { const x = new XMLHttpRequest(); x.onload = () => ok(x.status); x.onerror = () => no(new TypeError('x')); x.open('GET', B + '/items/a1?from=probe'); x.send() }));
  await t('beacon', () => navigator.sendBeacon(B + '/audit/now?from=probe', 'x'));
  await t('socket', () => new Promise((ok, no) => { const s = new WebSocket(B.replace('https', 'wss') + '/x?from=probe'); s.onopen = () => ok('open'); s.onerror = () => no(new TypeError('x')) }));
  await t('image', () => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok('loaded'); i.onerror = () => no(new TypeError('x')); i.src = B + '/favicon.svg?from=probe' }));
  await t('popup', () => window.open(B + '/?from=probe'));
  const f = document.createElement('form'); f.method = 'post'; f.action = B + '/items/a1/answer?from=probe';
  f.innerHTML = '<input name="act" value="comment"><input name="answer" value="from the canvas">'; document.body.appendChild(f); f.submit();
  await new Promise(ok => setTimeout(ok, 500));
  document.getElementById('out').textContent = JSON.stringify(r);
})();
</script></body>""".replace("__BOARD__", BOARD)
OLD = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>probe</title><body><h1>the older page</h1></body>'
VID = "20261101T080000.000001Z"


def put(content, version=None, number=1, **more):
    data = content.encode()
    code, out = _canvas.post("testbox", {"number": number, "version": version, "content": base64.b64encode(data).decode(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "modified": now, **more})
    assert code == 200, (code, out)


put(OLD, VID)
put(PROBE, title="A canvas with a rather long title that has to fit a narrow phone screen", item="a1")
TIPS = """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>tips</title><body style="min-height:600px"><p id="p">A <span id="t1" data-tip="the first meaning">first idea</span> and a <span id="t2" data-tip="the second meaning">second idea</span>,
<a id="lnk" href="#nowhere">a link</a>.</p></body>"""
put(TIPS, number=2)

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"), flush=True)
    if not cond: fails.append(name)


def shot(pg, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True); pg.wait_for_timeout(300); pg.screenshot(path=str(pathlib.Path(SHOTS, name + ".png")))


GOT = []      # (method, path with its query, the request carried the sign-in cookie) of every request the board received
APP = server.mcp.http_app()


async def logged(scope, receive, send):
    if scope["type"] in ("http", "websocket"):
        cookie = dict(scope.get("headers") or []).get(b"cookie", b"")
        q = scope.get("query_string", b"").decode()
        GOT.append((scope.get("method", "WS"), scope["path"] + ("?" + q if q else ""), _signin._UI_COOKIE.encode() in cookie))
    await APP(scope, receive, send)


srv = uvicorn.Server(uvicorn.Config(logged, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on", ssl_certfile=str(T / "tls.crt"), ssl_keyfile=str(T / "tls.key")))
th = threading.Thread(target=srv.run, daemon=True); th.start()


def cookie():
    return {"name": _signin._UI_COOKIE, "value": _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "domain": "localhost", "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "Lax"}


def item_untouched():
    m = json.loads((T / "store/a/1.json").read_text())
    return not (m.get("metadata") or {}).get("answers") and "from the canvas" not in json.dumps(m)


def run(br):
    ctx = br.new_context(viewport={"width": 390, "height": 800}, ignore_https_errors=True)
    ctx.add_cookies([cookie()])
    signed_in = lambda: any(c["name"] == _signin._UI_COOKIE and c["value"] for c in ctx.cookies())
    pages = []
    ctx.on("page", lambda p: pages.append(p))
    pg = ctx.new_page(); errors = []; pg.on("pageerror", lambda e: errors.append(str(e)))
    inner = lambda: pg.query_selector("iframe").content_frame()
    # waited for by selector: a waited-for function would be compiled in the page, whose policy allows no eval
    probes = lambda frame: (frame.wait_for_selector("#out:not(:empty)", state="attached", timeout=40000), json.loads(frame.inner_text("#out")))[1]
    def reads(frame):
        try: return frame.inner_text("body", timeout=3000)[:200].replace("\n", " ")
        except Exception as e: return f"(unreadable: {type(e).__name__})"

    def open_shell(path="/canvas/1"):
        pg.goto(BOARD + path); pg.wait_for_load_state("load")
        pg.evaluate("() => { window.refused = []; document.addEventListener('securitypolicyviolation', e => window.refused.push(e.violatedDirective + ' ' + e.blockedURI)) }")
        return inner()

    def apart(label, r, framed):
        want_refused = ("cookie", "storage", "session", "fetch", "post", "xhr", "socket", "image") + (("parent", "top") if framed else ())
        check(f"{label}: an opaque origin", r.get("origin") == "null", r)
        check(f"{label}: no cookie, storage, reach into another document or request to the board", all(str(r.get(k, "")).startswith("refused:") for k in want_refused), r)
        check(f"{label}: no popup", r.get("popup") == "null", r)
        check(f"{label}: the board received none of its requests", not [g for g in GOT if "from=probe" in g[1]], [g for g in GOT if "from=probe" in g[1]])
        check(f"{label}: the item it aimed at is unchanged", item_untouched())

    # ---- 1. the shell and the frame
    frame = open_shell()
    r = probes(frame)
    check("the frame shows the imported page, loaded with the sign-in", "probe page" in frame.inner_text("body") and ("GET", "/canvas/1/raw", True) in GOT, [g for g in GOT if "canvas" in g[1]])
    apart("in the frame", r, True)
    wide = pg.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    box = pg.query_selector("summary").bounding_box()
    check("at 390 px nothing scrolls sideways and the history control is a finger's size", wide[0] <= wide[1] and box["width"] >= 44 and box["height"] >= 44 and box["x"] + box["width"] <= 390, (wide, box))
    shot(pg, "01-shell")
    before = len(pages)
    frame.click("#blank"); pg.wait_for_timeout(800)
    check("a link that asks for a new window opens none", len(pages) == before and not [g for g in GOT if "from=blank" in g[1]], [p.url for p in pages])

    # ---- 2. versions are switched in the shell
    pg.click("summary"); shot(pg, "02-history")
    pg.click(f'a[href="/canvas/1/versions/{VID}"]'); pg.wait_for_load_state("load")
    inner().wait_for_selector("h1")
    check("a version opens from the history control, in a new shell", pg.url == f"{BOARD}/canvas/1/versions/{VID}" and inner().inner_text("h1") == "the older page" and ("GET", f"/canvas/1/versions/{VID}/raw", True) in GOT, pg.url)
    pg.click('a[href="/canvas/1"]'); pg.wait_for_load_state("load"); inner().wait_for_selector("h1")
    check("…and the current page again", pg.url == BOARD + "/canvas/1" and inner().inner_text("h1") == "probe page", pg.url)

    # ---- 3. the frame cannot leave the origin
    pg.wait_for_timeout(200)
    reach = ctx.new_page(); reach.goto(OUTSIDE + "/reach"); reach.close()
    check("(the other origin answers, so silence from it means something)", "/reach" in OUTSIDE_GOT, OUTSIDE_GOT)
    for label, script in (("by its own location", "u => { location.href = u + '/leak-location?d=text' }"),
                          ("by a link", "u => { const a = document.createElement('a'); a.href = u + '/leak-link?d=text'; document.body.appendChild(a); a.click() }"),
                          ("by a refresh tag", "u => { const m = document.createElement('meta'); m.httpEquiv = 'refresh'; m.content = '0;url=' + u + '/leak-meta?d=text'; document.head.appendChild(m) }"),
                          ("by the shell's window", "u => { try { top.location.href = u + '/leak-top?d=text' } catch (e) {} }")):
        frame = open_shell(); probes(frame)
        frame.evaluate(script, OUTSIDE); pg.wait_for_timeout(1500)
        leaked = [p for p in OUTSIDE_GOT if p.startswith("/leak")]
        check(f"the page cannot send text to another origin {label}", not leaked and pg.url == BOARD + "/canvas/1", (leaked, pg.url, pg.evaluate("() => window.refused")))
        print("      refused: " + json.dumps(pg.evaluate("() => window.refused"))[:300], flush=True)

    # ---- 4. the frame sent to board addresses
    frame = open_shell(); probes(frame)
    n = len(GOT)
    frame.evaluate("u => { location.href = u }", BOARD + "/ui/logout"); pg.wait_for_timeout(1500)
    check("the frame sent to /ui/logout signs nobody out", [g for g in GOT[n:] if g[1] == "/ui/logout"] != [] and signed_in(), (GOT[n:], ctx.cookies()))
    for label, script in (("a reload inside the frame", "() => { location.reload() }"), ("a board address inside the frame", f"() => {{ location.href = '{BOARD}/items/a1' }}")):
        frame = open_shell(); probes(frame)
        n = len(GOT)
        frame.evaluate(script); pg.wait_for_timeout(2500)
        seen = [g for g in GOT[n:] if "favicon" not in g[1]]
        print(f"      {label}: the board received (method, path, with the sign-in cookie) {seen}; the frame reads: {reads(inner())!r}", flush=True)
        check(f"{label} leaves the shell, the sign-in and the item as they were", pg.url == BOARD + "/canvas/1" and signed_in() and item_untouched() and not [g for g in seen if g[0] != "GET" or g[1].startswith("/ui/callback")], (pg.url, seen))
    frame = open_shell(); probes(frame)
    pg.reload(); pg.wait_for_load_state("load")
    r = probes(inner())
    check("a reload of the shell shows the page again", "probe page" in inner().inner_text("body") and r.get("origin") == "null", r)

    # ---- 5. the page opened as a tab of its own
    del GOT[:]
    tab = ctx.new_page(); tab.goto(BOARD + "/canvas/1/raw")
    r = probes(tab.main_frame)
    check("the raw address opens the page for a signed-in reader", "probe page" in tab.inner_text("body"), tab.inner_text("body")[:200])
    apart("as its own tab", r, False)
    tab.evaluate("u => { location.href = u }", BOARD + "/ui/logout"); tab.wait_for_timeout(1500)
    check("its tab sent to /ui/logout signs nobody out", ("GET", "/ui/logout", True) in GOT and signed_in(), (GOT[-5:], ctx.cookies()))
    tab.close()

    # ---- 6. another origin cannot frame it
    other = ctx.new_page(); other.goto(OUTSIDE + "/framer"); other.wait_for_timeout(1500)
    texts = []
    for f in other.frames[1:]:
        try: texts.append(f.inner_text("body", timeout=2000))
        except Exception as e: texts.append(f"({type(e).__name__})")
    check("a page of another origin cannot frame it: its frame shows neither the page nor the board's own answer", texts and not any("probe page" in t or "signed out" in t for t in texts), texts)
    other.close()

    # ---- 6b. the shared tooltip and the default link color of a page that sets neither
    frame = open_shell("/canvas/2")
    frame.wait_for_selector("#t1")
    bubble = lambda: frame.query_selector_all("[data-canvas-tip-bubble]")
    frame.hover("#t1"); pg.wait_for_timeout(300)
    check("a tip does not open on hover alone", bubble() == [], len(bubble()))
    frame.click("#t1"); pg.wait_for_timeout(200)
    check("a click opens the tip with its text", len(bubble()) == 1 and bubble()[0].inner_text() == "the first meaning", [b.inner_text() for b in bubble()])
    shot(pg, "03-tip")
    frame.click("#t1"); pg.wait_for_timeout(200)
    check("a second click closes it", bubble() == [], len(bubble()))
    frame.click("#t1"); frame.click("#t2"); pg.wait_for_timeout(200)
    check("a click on another tip moves it there", len(bubble()) == 1 and bubble()[0].inner_text() == "the second meaning", [b.inner_text() for b in bubble()])
    frame.click("body", position={"x": 370, "y": 500}); pg.wait_for_timeout(200)
    check("a click outside closes it", bubble() == [], len(bubble()))
    frame.click("#t1"); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Escape closes it", bubble() == [], len(bubble()))
    box = (frame.click("#t1"), frame.query_selector("[data-canvas-tip-bubble]").bounding_box())[1]
    check("the tip stays inside a 390 px screen", box["x"] >= 0 and box["x"] + box["width"] <= 390, box)
    color = frame.evaluate("() => getComputedStyle(document.getElementById('lnk')).color")
    check("a link of a page with no link color is drawn in the default one", color == "rgb(47, 114, 222)", color)

    # ---- 7. signed out
    out = br.new_context(viewport={"width": 390, "height": 800}, ignore_https_errors=True)
    o = out.new_page(); resp = o.goto(BOARD + "/canvas/1/raw")
    check("signed out, the page's address shows nothing of it", resp.status == 401 and "probe page" not in o.inner_text("body"), (resp.status, o.inner_text("body")[:200]))
    out.close(); ctx.close()
    check("no script error on the shell or in its frame", errors == [], errors)


try:
    for _ in range(200):
        if srv.started: break
        time.sleep(0.05)
    if not srv.started: print("the test server did not start"); sys.exit(1)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        try: run(br)
        finally: br.close()
except Exception as e:
    import traceback; traceback.print_exc(); fails.append(f"stopped: {type(e).__name__}")
finally:
    srv.should_exit = True; th.join(timeout=10)
    OUT_SRV.shutdown(); OUT_SRV.server_close()

print(("ok" if not fails else "FAILED") + f": canvas check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
