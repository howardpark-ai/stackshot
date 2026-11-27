"""Answer-frame check (a browser; run by .github/workflows/answer-frame.yml, not in the suite loop). The routes and what the pages say are tests/answer_frame_scenario.py; this is what only a
browser shows. It starts the server in-process over HTTPS on localhost with a temporary config and fixture data (no live store, no network beyond this machine), and two parent pages on other
origins (two more ports): one the config lists, one it does not. A browser signed in with the board's cookie then checks that:

  - the listed parent gets the frame's messages, with exactly the contract's fields: on load, the height (and no scroll inside the frame at that height), the state and whether the note box has focus;
  - at 390 px wide nothing scrolls sideways, in every state the frame can show;
  - a pick and Send record exactly one answer, from the click and from Ctrl+Enter; a send that fails says so and records nothing; a pick on a rewritten question records nothing;
  - two frames of one item share the pick, the note, the send under way and how it ended;
  - the parent's refresh and theme are taken from the parent window at a listed origin and from nobody else;
  - a parent that is not listed cannot frame it, nor a listed parent that is itself framed by an unlisted page;
  - signed out it shows only the link to the item, which opens in a new tab, and it reads again once signed in.

    tests/run-suite answer_frame_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    ANSWER_FRAME_SHOTS=<folder> also saves a screenshot of each state there."""
import http.server, json, logging, os, pathlib, re, socket, ssl, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="framechk-"); T = pathlib.Path(tmp)
SHOTS = os.environ.get("ANSWER_FRAME_SHOTS", "")
EMAIL = "oliver@example.org"

subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout", str(T / "tls.key"), "-out", str(T / "tls.crt")], check=True, capture_output=True)
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); TLS.load_cert_chain(str(T / "tls.crt"), str(T / "tls.key"))
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BOARD = f"https://localhost:{PORT}"

# the parent page: it holds the frames, keeps every message it gets (with which frame sent it) and gives a frame the height it asked for
PARENT_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>parent</title>
<style>html,body{margin:0;padding:0;background:#7f7f7f}iframe{display:block;width:100%;border:0;height:40px;margin:0 0 12px}</style></head><body><div id="slot"></div><script>
var BOARD="__BOARD__";window.got=[];
addEventListener('message',function(e){var f=[].find.call(document.querySelectorAll('iframe'),function(x){return x.contentWindow===e.source});
window.got.push({origin:e.origin,frame:f?f.id:'',data:e.data});if(f&&e.origin===BOARD&&e.data&&e.data.kind==='answer-frame')f.style.height=e.data.height+'px'});
function add(id,src){var f=document.createElement('iframe');f.id=id;f.src=src;document.getElementById('slot').appendChild(f)}
function send(id,msg){document.getElementById(id).contentWindow.postMessage(msg,BOARD)}
var q=new URLSearchParams(location.search);if(q.get('frame'))add('f',q.get('frame'));
</script></body></html>"""
# a page that is not the frame's parent and posts to the first frame beside it
POKE_PAGE = """<!doctype html><html><body><script>parent.frames[0].postMessage({source:'x',kind:'answer-frame',v:1,do:'theme',theme:'dark'},'*');document.title='poked'</script></body></html>"""


class Quiet(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):      # a browser drops a connection it opened ahead of need, and says so about the self-signed certificate: no finding of this check
        if not isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError)): super().handle_error(request, client_address)


def parent_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = (POKE_PAGE if self.path.startswith("/poke") else PARENT_PAGE.replace("__BOARD__", BOARD)).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    srv = Quiet(("127.0.0.1", 0), H); srv.daemon_threads = True
    srv.socket = TLS.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"https://localhost:{srv.server_address[1]}"


LISTED_SRV, LISTED = parent_server()
UNLISTED_SRV, UNLISTED = parent_server()

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                 (r'(?m)^answer_frame_origins = \[\]', f'answer_frame_origins = ["{LISTED}", "https://chat.example.com"]')):
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
ASK = "Decide: whether to ship zebraword · Recommend: ship · Stakes: none either way · By: no date"
ASK2 = "Decide: whether to ship the rewritten question · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]
LONG = "https://example.org/" + "averyveryveryunbrokenaddress" * 5


def item(i, ask=ASK, opts=OPTS, **meta):
    m = {"owner": OWNER, "project": "projects/alpha", "next": "the next step", "needs": ["decision"], "ask": ask, **meta}
    if opts: m["options"] = opts
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] titleword a{i}", "description": "Background words.", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": m}))


item(1, draft="a draft to paste\nover two lines\nand a third")
for i in range(2, 8): item(i)
item(8, ask=f"Decide: whether {LONG} · Recommend: yes · Stakes: none · By: no date",
     opts=[{"label": "A" * 60, "line": LONG, "recommended": True}, {"label": "B", "line": LONG, "recommended": False}], draft=LONG)
item(9, opts=None)                                     # Yes and No
item(10); item(11)
STEP = "run the second line"
OLD = {"ts": now - 3 * 86400, "kind": "decision", "choice": "Drop", "via": "board", "ask": ASK}
def off(i, *answers): item(i, ask="", opts=None, needs=[], answers=list(answers))      # nothing to pick, off his move
for i in (12, 14, 15): item(i, ask="", opts=None, needs=[], state="your-step", step=STEP, answers=[OLD])      # on his move for a step, with an older answer
off(13, OLD)
(T / "store/next-id").write_text("30"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")


def git(*a): subprocess.run(["git", "-C", str(T / "store"), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)


git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn
from stackshot.web import server, i18n
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.service import answer as answer_svc, telling
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts, answers as _web_answers
from stackshot.web.auth import signin as _signin
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
answer_svc._answer_deliver = lambda *a, **k: time.sleep(1.0) or []      # a send takes a second, so the state "under way" can be seen


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def answers(i): return [a for a in (rd(i).get("metadata") or {}).get("answers") or [] if a.get("kind") == "decision"]


fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"), flush=True)
    if not cond: fails.append(name)


FIELDS = {"source", "kind", "v", "item", "height", "state", "typing"}
STATES = {"open", "sending", "answered", "changed", "closed", "signed_out"}
seen = []          # every message any parent page got


def msgs(pg, fid="f"):
    return pg.evaluate("(f) => window.got.filter(x => x.frame === f && x.origin === BOARD).map(x => x.data)", fid)


def wait_state(pg, state, fid="f", timeout=10000):
    pg.wait_for_function("([f, s]) => { const m = window.got.filter(x => x.frame === f && x.origin === BOARD); return m.length > 0 && m[m.length - 1].data.state === s }", arg=[fid, state], timeout=timeout)


def inner(pg, fid="f"):
    return pg.query_selector(f"#{fid}").content_frame()


def measure(pg, fid="f"):
    return inner(pg, fid).evaluate("""() => { const d = document.documentElement;
        return {sw: d.scrollWidth, cw: d.clientWidth, sh: d.scrollHeight, ch: d.clientHeight, bh: Math.ceil(document.body.getBoundingClientRect().height)} }""")


def fits(name, pg, fid="f"):
    """once settled: the height told is the content's, the parent's frame of that height scrolls neither way, and it is 390 px wide"""
    pg.wait_for_timeout(500)
    m = measure(pg, fid); told = msgs(pg, fid)[-1]["height"]
    check(f"{name}: 390 px, no sideways scroll", m["cw"] == 390 and m["sw"] <= 390, m)
    check(f"{name}: the height told is the content's, and at that height nothing scrolls inside", told == m["bh"] and m["sh"] <= m["ch"], (told, m))


def look(pg, fid="f"):
    """what the frame's form holds"""
    return inner(pg, fid).evaluate("""() => { const f = document.querySelector('form.hanswer'); if (!f) return null; const c = f.querySelector('input[name=choice]:checked');
        return {pick: c ? c.value : '', note: f.querySelector('textarea').value, send: !f.querySelector('button[name=act]').disabled, busy: f.getAttribute('aria-busy') === 'true'} }""")


def body_text(pg, fid="f"):
    return inner(pg, fid).evaluate("() => document.getElementById('aframe').innerText")


def card(pg, label, fid="f"):
    inner(pg, fid).click(f"form.hanswer .acard:has-text('{label}')")


def press(pg, fid="f"):
    inner(pg, fid).click("form.hanswer button[name=act]")


def shot(pg, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True); pg.wait_for_timeout(300); pg.screenshot(path=str(pathlib.Path(SHOTS, name + ".png")), full_page=True)


srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="warning", lifespan="on", ssl_certfile=str(T / "tls.crt"), ssl_keyfile=str(T / "tls.key")))
th = threading.Thread(target=srv.run, daemon=True); th.start()


def cookie():
    return {"name": _signin._UI_COOKIE, "value": _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "domain": "localhost", "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "Lax"}


def run(br):
    errors = []
    def context(signed_in=True, **kw):
        ctx = br.new_context(viewport={"width": 390, "height": 900}, ignore_https_errors=True, **kw)
        if signed_in: ctx.add_cookies([cookie()])
        return ctx
    def parent(ctx, *frames, origin=LISTED):
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e))); pg.goto(origin + "/")
        for fid, path in frames: pg.evaluate("([i, s]) => add(i, s)", [fid, BOARD + path])
        return pg
    def done(pg):
        seen.extend(pg.evaluate("window.got.filter(x => x.origin === BOARD).map(x => x.data)")); pg.close()
    ctx = context()

    # ---- 1. the messages, the size, the note box
    pg = parent(ctx, ("f", "/items/a2/answer-frame?theme=light")); wait_state(pg, "open")
    first = msgs(pg)[0]
    check("on load: the contract's message from the board's origin", set(first) == FIELDS and first["source"] == "stackshot" and first["kind"] == "answer-frame" and first["v"] == 1 and first["item"] == "a2"
          and first["state"] == "open" and first["typing"] is False and isinstance(first["height"], int) and first["height"] > 100, first)
    fits("open", pg); shot(pg, "01-open-light")
    check("open: nothing picked, Send disabled", look(pg) == {"pick": "", "note": "", "send": False, "busy": False}, look(pg))
    check("open: no title or background of the item", "titleword" not in body_text(pg) and "Background words" not in body_text(pg), body_text(pg))
    box = "form.hanswer textarea"
    inner(pg).click(box); pg.wait_for_timeout(300)
    check("the note box focused: typing true", msgs(pg)[-1]["typing"] is True, msgs(pg)[-1])
    small = msgs(pg)[-1]["height"]
    inner(pg).fill(box, "\n".join(f"line {n} of a long note" for n in range(25))); pg.wait_for_timeout(500)
    tall = msgs(pg)[-1]["height"]
    check("a long note grows the frame", tall > small + 200, (small, tall)); fits("a long note", pg)
    inner(pg).fill(box, "short"); pg.wait_for_timeout(500)
    check("…and it shrinks again with the note", msgs(pg)[-1]["height"] <= small + 40, (small, msgs(pg)[-1]["height"])); fits("a short note again", pg)
    inner(pg).evaluate("() => document.activeElement.blur()"); pg.wait_for_timeout(300)
    check("the note box left: typing false", msgs(pg)[-1]["typing"] is False, msgs(pg)[-1])

    # ---- 2. the parent's two requests
    theme = lambda: inner(pg).evaluate("() => [document.documentElement.getAttribute('data-theme'), getComputedStyle(document.body).backgroundColor]")
    light = theme()
    ASKD = {"source": "parent-page", "kind": "answer-frame", "v": 1, "do": "theme", "theme": "dark"}
    for what, m in (("no source", {k: v for k, v in ASKD.items() if k != "source"}), ("another kind", {**ASKD, "kind": "other"}), ("another version", {**ASKD, "v": 2}),
                    ("another theme", {**ASKD, "theme": "blue"}), ("a string", "theme dark")):
        pg.evaluate("(m) => send('f', m)", m); pg.wait_for_timeout(150)
        check(f"a message with {what} is ignored", theme() == light, theme())
    for origin in (UNLISTED, LISTED):
        pg.evaluate("(s) => add('poke', s)", origin + "/poke"); pg.wait_for_timeout(1200)
        check(f"a message from a frame beside it ({'an unlisted' if origin == UNLISTED else 'the listed'} origin) is ignored: it is not the parent window", theme() == light, theme())
        pg.evaluate("() => document.getElementById('poke').remove()")
    pg.evaluate("(m) => send('f', m)", ASKD); pg.wait_for_timeout(300)
    dark = theme()
    check("the parent's theme is taken, whatever source it names", light[0] == "light" and dark[0] == "dark" and dark[1] != light[1], (light, dark)); shot(pg, "02-open-dark")
    card(pg, "Drop"); inner(pg).fill(box, "kept over a refresh"); mine = look(pg)
    item(2, next="another next step")
    pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"}); pg.wait_for_timeout(1500)
    check("refresh with the question unchanged: the pick and the note stay, still open", look(pg) == mine and msgs(pg)[-1]["state"] == "open" and mine["pick"] and mine["send"], (mine, look(pg)))
    item(2, ask=ASK2)
    pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"}); wait_state(pg, "changed")
    t = body_text(pg)
    check("refresh with the question rewritten: changed, a board link and nothing to press", i18n.EN["frame.changed"] in t and "rewritten" not in t and "zebraword" not in t
          and inner(pg).query_selector("form, input, button, textarea") is None and inner(pg).get_attribute("#aframe a", "href") == "/items/a2", t)
    fits("changed", pg); shot(pg, "03-changed")
    check("…nothing was recorded", answers(2) == [], answers(2))
    inner(pg).evaluate("() => location.reload()"); wait_state(pg, "open")
    check("a reload of the frame shows the new question", "rewritten" in body_text(pg), body_text(pg))
    done(pg)

    # ---- 3. two frames of one item: one pick, one note, one send, one result
    pg = parent(ctx, ("f", "/items/a1/answer-frame")); wait_state(pg, "open")
    card(pg, "Ship"); inner(pg).fill("form.hanswer textarea", "typed in the first")
    pg.evaluate("(s) => add('g', s)", BOARD + "/items/a1/answer-frame"); wait_state(pg, "open", "g"); pg.wait_for_timeout(800)
    check("a second frame opened later takes the pick and the note", look(pg, "g") == look(pg) and look(pg, "g")["note"] == "typed in the first" and look(pg, "g")["pick"], (look(pg), look(pg, "g")))
    card(pg, "Drop", "g"); inner(pg, "g").fill("form.hanswer textarea", "changed in the second"); pg.wait_for_timeout(500)
    check("a pick and a note in the second reach the first", look(pg) == look(pg, "g") and look(pg)["note"] == "changed in the second" and "Drop" in look(pg)["pick"], (look(pg), look(pg, "g")))
    card(pg, "Drop"); pg.wait_for_timeout(500)
    check("a pick taken back is taken back in both", look(pg)["pick"] == "" and look(pg, "g")["pick"] == "", (look(pg), look(pg, "g")))
    card(pg, "Drop"); pg.wait_for_timeout(500)
    other = parent(ctx, ("f", "/items/a3/answer-frame")); wait_state(other, "open")
    check("a frame of another item takes nothing of it", look(other) == {"pick": "", "note": "", "send": False, "busy": False}, look(other)); done(other)
    pg.bring_to_front()
    shot(pg, "04-two-frames-picked")
    inner(pg, "g").click("details summary .dlab"); pg.wait_for_timeout(500); fits("the draft opened", pg, "g")
    press(pg); wait_state(pg, "sending", "f", 5000); wait_state(pg, "sending", "g", 5000)
    check("a send under way: both frames say so and neither can be pressed", look(pg)["busy"] and look(pg, "g")["busy"] and not look(pg)["send"] and not look(pg, "g")["send"], (look(pg), look(pg, "g")))
    wait_state(pg, "answered", "f"); wait_state(pg, "answered", "g"); pg.wait_for_timeout(800)
    a = answers(1)
    check("one pick and Send record exactly one answer, the card and the note", len(a) == 1 and a[0].get("choice") == "Drop" and a[0].get("text") == "changed in the second" and a[0].get("via") == "board", a)
    for fid in ("f", "g"):
        t = body_text(pg, fid)
        check(f"answered, frame {fid}: the recorded answer, nothing to press", "Drop" in t and "changed in the second" in t and inner(pg, fid).query_selector("form, input, button, textarea") is None, t)
        fits(f"answered, frame {fid}", pg, fid)
        states = [m["state"] for m in msgs(pg, fid)]
        order = [s for n, s in enumerate(states) if n == 0 or states[n - 1] != s]
        check(f"frame {fid} told the parent open, sending, answered", order == ["open", "sending", "answered"], order)
    shot(pg, "05-answered")
    done(pg)

    # ---- 4. a send that fails, then Ctrl+Enter
    pg = parent(ctx, ("f", "/items/a3/answer-frame")); wait_state(pg, "open")
    card(pg, "Wait"); inner(pg).fill("form.hanswer textarea", "held through a failure")
    ctx.route("**/items/a3/answer", lambda route: route.abort())
    press(pg); inner(pg).wait_for_selector("#afmsg .isent.warn", timeout=8000); pg.wait_for_timeout(500)
    t = body_text(pg)
    check("a failed send: open again, said in words, the pick and the note kept, nothing recorded", msgs(pg)[-1]["state"] == "open" and i18n.EN["js.answer.nothing_sent"].split("{")[0].strip() in t
          and look(pg)["pick"] and look(pg)["note"] == "held through a failure" and look(pg)["send"] and answers(3) == [], (t, look(pg), answers(3)))
    fits("a failed send", pg); shot(pg, "06-failed-send")
    ctx.unroute("**/items/a3/answer")
    inner(pg).click("form.hanswer textarea"); inner(pg).press("form.hanswer textarea", "Control+Enter"); wait_state(pg, "answered")
    a = answers(3)
    check("Ctrl+Enter sends the pick and the note, once", len(a) == 1 and a[0].get("choice") == "Wait" and a[0].get("text") == "held through a failure", a)
    check("…and the box that had focus is gone: typing false", msgs(pg)[-1]["typing"] is False, msgs(pg)[-1])
    done(pg)

    pg = parent(ctx, ("f", "/items/a10/answer-frame")); wait_state(pg, "open")      # sent, and the frame cannot read the item again
    ctx.route("**/items/a10/answer-frame?**", lambda route: route.abort())
    card(pg, "Wait"); press(pg); wait_state(pg, "answered"); pg.wait_for_timeout(500)
    t = body_text(pg)
    answered_by = i18n.EN["frame.answered_by"].split("{")[0].strip()      # only a page read from the server draws it
    check("sent, the reading after it failed: answered, said once, nothing about his queue", len(answers(10)) == 1 and t.count(i18n.EN["frame.sent"]) == 1 and answered_by not in t and "queue" not in t, (answers(10), t))
    ctx.unroute("**/items/a10/answer-frame?**"); done(pg)
    pg = parent(ctx, ("f", "/items/a11/answer-frame")); wait_state(pg, "open")      # nothing recorded, and the frame cannot read the item again
    ctx.route("**/items/a11/answer-frame?**", lambda route: route.abort())
    card(pg, "Ship"); item(11, ask=ASK2); press(pg); wait_state(pg, "changed"); pg.wait_for_timeout(500)
    t = body_text(pg)
    check("a stale pick, the reading after it failed: changed, and the notice says nothing was sent", answers(11) == [] and i18n.EN["frame.changed"] in t and i18n.EN["sent.stale_home"] in t, (answers(11), t))
    ctx.unroute("**/items/a11/answer-frame?**"); done(pg)

    # ---- 5. the question rewritten under a pick; answered on the board; taken off his move
    pg = parent(ctx, ("f", "/items/a4/answer-frame")); wait_state(pg, "open")
    card(pg, "Ship"); item(4, ask=ASK2); press(pg); wait_state(pg, "changed")
    check("a pick on a question rewritten since it was shown records nothing and says changed", answers(4) == [] and i18n.EN["frame.changed"] in body_text(pg) and i18n.EN["sent.stale_home"] in body_text(pg), (answers(4), body_text(pg)))
    fits("a stale send", pg); shot(pg, "07-stale-send"); done(pg)
    pg = parent(ctx, ("f", "/items/a5/answer-frame")); wait_state(pg, "open")
    board = ctx.new_page(); board.goto(BOARD + "/items/a5"); board.click("form.ianswer .acard:has-text('Wait')")
    with board.expect_response(lambda r: r.url.endswith("/items/a5/answer"), timeout=10000): board.click("form.ianswer button[name=act]")
    board.close()
    pg.bring_to_front(); pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"}); wait_state(pg, "answered")
    check("answered on the board: the parent's refresh shows it answered", len(answers(5)) == 1 and "Wait" in body_text(pg), (answers(5), body_text(pg))); done(pg)
    pg = parent(ctx, ("f", "/items/a6/answer-frame")); wait_state(pg, "open")
    item(6, opts=None, needs=[], ask="")
    pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"}); wait_state(pg, "closed")
    check("taken off his move: closed, a line and a board link", i18n.EN["frame.closed"] in body_text(pg) and inner(pg).query_selector("form, input, button") is None, body_text(pg))
    fits("closed", pg); shot(pg, "08-closed"); done(pg)

    # ---- 5b. the refresh of a frame that has drawn no question
    def reread(pg, i):      # the parent's refresh, waited for to the frame's own read of the item and the time to draw it; the address it read
        with pg.expect_response(lambda r: f"/items/a{i}/answer-frame?" in r.url, timeout=8000) as got:
            pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"})
        pg.wait_for_timeout(500); return got.value.url
    pg = parent(ctx, ("f", "/items/a12/answer-frame")); wait_state(pg, "closed")
    off(12, OLD); url = reread(pg, 12)
    check("first drawn closed, the item then off his move: the refresh sends its time and stays closed", "since=" in url and msgs(pg)[-1]["state"] == "closed" and answered_by not in body_text(pg), (url, body_text(pg)))
    off(12, OLD, {**OLD, "ts": time.time(), "choice": "Ship"}); reread(pg, 12); wait_state(pg, "answered")
    check("...an answer recorded since is shown", "Ship" in body_text(pg), body_text(pg)); done(pg)
    pg = parent(ctx, ("f", "/items/a13/answer-frame")); wait_state(pg, "answered")
    url = reread(pg, 13)
    check("first drawn answered: the refresh sends no time and the answer stays", "since=" not in url and msgs(pg)[-1]["state"] == "answered" and answered_by in body_text(pg), (url, body_text(pg))); done(pg)
    pg = parent(ctx, ("f", "/items/a15/answer-frame")); wait_state(pg, "closed")
    unread = {**OLD, "ts": time.time(), "choice": "Ship"}
    item(15, ask=ASK2, answers=[OLD, unread]); reread(pg, 15); wait_state(pg, "open")
    off(15, OLD, unread); reread(pg, 15); wait_state(pg, "closed")
    check("a question drawn after an answer the frame never read, then taken off: closed, that answer not shown", answered_by not in body_text(pg), body_text(pg)); done(pg)
    lapse = context(); pg = parent(lapse, ("f", "/items/a14/answer-frame")); wait_state(pg, "closed")
    inner(pg).evaluate("() => { window.drawnClosed = true }")
    lapse.clear_cookies(); reread(pg, 14); wait_state(pg, "signed_out")
    off(14, OLD); lapse.add_cookies([cookie()]); reread(pg, 14); wait_state(pg, "closed")
    check("first drawn closed, the sign-in run out and back: it reads again without loading anew, the older answer not shown", answered_by not in body_text(pg) and inner(pg).evaluate("() => window.drawnClosed === true"), body_text(pg))
    done(pg); lapse.close()

    # ---- 6. long words; the device's theme
    pg = parent(ctx, ("f", "/items/a8/answer-frame")); wait_state(pg, "open"); fits("long unbroken words", pg)
    inner(pg).click("details summary .dlab"); pg.wait_for_timeout(500); fits("a long unbroken draft, opened", pg); shot(pg, "09-long-words"); done(pg)
    shades = []
    for scheme in ("light", "dark"):
        c2 = context(color_scheme=scheme); pg = parent(c2, ("f", "/items/a9/answer-frame")); wait_state(pg, "open")
        shades.append(inner(pg).evaluate("() => getComputedStyle(document.body).backgroundColor")); fits(f"Yes and No, a {scheme} device", pg); shot(pg, f"10-yes-no-{scheme}"); done(pg); c2.close()
    check("with no theme asked the frame follows the device", shades == [light[1], dark[1]], (shades, light, dark))

    # ---- 7. who may frame it
    path = "/items/a9/answer-frame"
    pg = ctx.new_page(); said = []; pg.on("console", lambda m: said.append(m.text))
    pg.goto(UNLISTED + "/"); pg.evaluate("(s) => add('f', s)", BOARD + path); pg.wait_for_timeout(3000)
    drawn = [f for f in pg.frames if f.url.startswith(BOARD) and f.query_selector("#aframe")]
    check("an unlisted parent cannot frame it: nothing drawn, no message, and the browser names frame-ancestors", drawn == [] and pg.evaluate("window.got") == [] and any("frame-ancestors" in s for s in said), (drawn, pg.evaluate("window.got"), said))
    pg.close()
    pg = ctx.new_page(); said = []; pg.on("console", lambda m: said.append(m.text))
    from urllib.parse import quote
    pg.goto(UNLISTED + "/"); pg.evaluate("(s) => add('mid', s)", LISTED + "/?frame=" + quote(BOARD + path, safe="")); pg.wait_for_timeout(3000)
    mid = pg.query_selector("#mid").content_frame()
    drawn = [f for f in pg.frames if f.url.startswith(BOARD) and f.query_selector("#aframe")]
    check("nor a listed parent that an unlisted page frames", drawn == [] and mid.evaluate("window.got") == [] and any("frame-ancestors" in s for s in said), (drawn, mid.evaluate("window.got"), said))
    pg.close()
    check("nothing was recorded by any of it", answers(9) == [], answers(9))
    ctx.close()

    # ---- 8. signed out, then signed in
    out = context(signed_in=False)
    pg = parent(out, ("f", "/items/a7/answer-frame")); wait_state(pg, "signed_out")
    t = body_text(pg)
    check("signed out: a link to the item and no word of it", i18n.EN["frame.signed_out"] in t and "zebraword" not in t and "Ship" not in t and "titleword" not in t and inner(pg).query_selector("form, input, button, textarea") is None, t)
    fits("signed out", pg); shot(pg, "11-signed-out")
    with out.expect_page() as popup:
        inner(pg).click("#aframe a")
    tab = popup.value
    tab.wait_for_load_state("domcontentloaded")
    check("its link opens the item on the board in a new tab, and the parent stays", tab.url.startswith(BOARD) and pg.url.startswith(LISTED) and msgs(pg)[-1]["state"] == "signed_out", (tab.url, pg.url))
    tab.close()
    inner(pg).evaluate("() => { window.drawnSignedOut = true }")
    out.add_cookies([cookie()]); pg.bring_to_front(); inner(pg).evaluate("() => window.dispatchEvent(new Event('focus'))"); wait_state(pg, "open"); pg.wait_for_timeout(500)
    check("signed in meanwhile: coming back to the frame loads it again, with the question", "zebraword" in body_text(pg) and look(pg)["send"] is False and inner(pg).evaluate("() => window.drawnSignedOut === undefined"), body_text(pg))
    card(pg, "Ship"); inner(pg).fill("form.hanswer textarea", "kept over a sign-in that ran out")
    out.clear_cookies(); press(pg); wait_state(pg, "signed_out"); pg.wait_for_timeout(500)
    check("a sign-in that ran out before Send: signed out, nothing recorded", answers(7) == [] and "zebraword" not in body_text(pg), (answers(7), body_text(pg)))
    out.add_cookies([cookie()]); pg.evaluate("(m) => send('f', m)", {**ASKD, "do": "refresh"}); wait_state(pg, "open"); pg.wait_for_timeout(500)
    check("…signed in again, the pick and the note are still there, the old notice gone", look(pg)["note"] == "kept over a sign-in that ran out" and "Ship" in look(pg)["pick"] and look(pg)["send"] and inner(pg).query_selector("#afmsg .isent") is None, look(pg))
    press(pg); wait_state(pg, "answered")
    check("…and it can be answered from there", len(answers(7)) == 1 and answers(7)[0].get("choice") == "Ship" and answers(7)[0].get("text") == "kept over a sign-in that ran out", answers(7))
    done(pg); out.close()

    # ---- every message of the run
    check("every message held exactly the contract's fields and a contract state", seen and all(set(m) == FIELDS and m["state"] in STATES and m["source"] == "stackshot" and m["v"] == 1 and isinstance(m["typing"], bool) and isinstance(m["height"], int) for m in seen),
          [m for m in seen if set(m) != FIELDS or m["state"] not in STATES][:3])
    all_text = json.dumps(seen)
    tokens = [_web_answers._answer_token(EMAIL, f"a{i}") for i in range(1, 16)]
    check("no message held a word of an item, an answer or a token", not any(w in all_text for w in ("zebraword", "titleword", "rewritten", "typed", "changed in the second", "held through", "Drop", "Ship", *tokens)), all_text[:400])
    check("no script error on any page", errors == [], errors)


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
    for s in (LISTED_SRV, UNLISTED_SRV): s.shutdown(); s.server_close()

print(("ok" if not fails else "FAILED") + f": answer frame check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
