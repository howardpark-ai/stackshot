"""Decision-pick check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Starts the server in-process on 127.0.0.1 with a temporary
config and fixture data (no live store, no network), signs a browser in with the board's cookie, and answers decisions that list options, on the home page and on the item page:

  - a card picked with a note typed reaches the item with both (the stored answer holds the choice and the text), with two options and with three (lettered);
  - a live refresh of the home page between the pick and Send leaves the picked card and the note where they are;
  - a refresh that is already on its way when the card is picked (and whose page differs in its frame, as after a deploy) does not reload the page under the pick;
  - Ctrl+Enter in the box sends the pick too.

    tests/run-suite decision_pick_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, sys, tempfile, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pickchk-"); T = pathlib.Path(tmp)
EMAIL = "oliver@example.org"
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BASE}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BASE}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS2 = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
OPTS3 = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}, {"label": "Drop", "line": "Drop it", "recommended": False}]
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "A thing. It lives here. Done when it works.",
                                                     "status": "open", "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", **meta}}))
def decision(i, opts): item(i, needs=["decision"], ask=ASK, options=opts)
for i in (1, 3, 5, 6, 7): decision(i, OPTS2)        # a two-card pair each, one per scenario
for i in (2, 4, 8): decision(i, OPTS3)              # three options, lettered
(T / "store/next-id").write_text("30"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
import subprocess
def git(*a): subprocess.run(["git", "-C", str(T / "store"), *a], check=True, capture_output=True)
git("init", "-q"); git("config", "user.email", "t@example.org"); git("config", "user.name", "t"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web import render; from stackshot.web import board_home
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.routes import board_pages as _rt_board
from stackshot.web.auth import signin as _signin
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
server._answer_deliver = lambda *a, **k: []
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def last(i): return ((rd(i).get("metadata") or {}).get("answers") or [{}])[-1]

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {got}"))
    if not cond: fails.append(name)

srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
th = threading.Thread(target=srv.run, daemon=True); th.start()
for _ in range(200):
    if srv.started: break
    time.sleep(0.05)
if not srv.started: print("the test server did not start"); sys.exit(1)

COOKIE = {"name": _signin._UI_COOKIE, "value": _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "url": BASE}
from playwright.sync_api import sync_playwright
def redraw(bump=None):
    """make the server draw its home again, a second later than the page in the browser (the page's stamp is whole seconds), after `bump()` changed something"""
    time.sleep(1.1)
    if bump: bump()
    with _rt_board._BOARD_HOME_LOCK: board_home._BOARD_HOME["html"] = None; board_home._BOARD_HOME["at"] = 0; board_home._BOARD_HOME["failed"] = 0
    assert _rt_board._board_home()           # drawn now, so the stamp the page polls is the new one
ROW = "li#task-a-{} form.hanswer"
def home(pg, i):
    pg.goto(BASE + "/"); pg.wait_for_selector(ROW.format(i) + "[data-cards]:not([hidden])", timeout=8000); pg.wait_for_timeout(300)
def pick(pg, i, label, note):
    f = ROW.format(i); pg.click(f"{f} .acard:has-text('{label}')"); pg.fill(f"#atext-a{i}", note); pg.wait_for_timeout(100)
def state(pg, i):
    return pg.evaluate("""(f) => { const q = document.querySelector(f); const c = q && q.querySelector('input[name=choice]:checked');
        return q && {choice: c && c.value, text: q.querySelector('textarea').value, dis: q.querySelector('button[name=act]').disabled}; }""", ROW.format(i))
def poll(pg): pg.wait_for_timeout(2200); pg.evaluate("window.dispatchEvent(new Event('focus'))"); pg.wait_for_timeout(1500)
def sent(pg, sel):
    with pg.expect_navigation(timeout=8000): pg.click(sel)
    pg.wait_for_timeout(300)
try:
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        ctx = br.new_context(viewport={"width": 1000, "height": 1400}); ctx.add_cookies([COOKIE]); pg = ctx.new_page()

        # 1 home, two options: a card and a note, Send
        home(pg, 1); pick(pg, 1, "Wait", "isn't a daily audit enough here?")
        sent(pg, ROW.format(1) + " button[name=act]")
        a = last(1); check("home, two options: the card and the note are both stored", a.get("choice") == "Wait" and a.get("text") == "isn't a daily audit enough here?", a)

        # 2 home, three options (lettered)
        home(pg, 2); pick(pg, 2, "Drop", "a note on the pick")
        sent(pg, ROW.format(2) + " button[name=act]")
        a = last(2); check("home, three options: the card and the note are both stored", a.get("choice") == "Drop" and a.get("letter") == "C" and a.get("text") == "a note on the pick", a)

        # 3 a live refresh between the pick and Send
        home(pg, 3); pick(pg, 3, "Wait", "typed before the refresh")
        redraw(lambda: item(20, needs=["decision"], ask=ASK, options=OPTS2)); poll(pg)
        s = state(pg, 3); check("a refresh between the pick and Send keeps the card, the note and an enabled Send", s and s["choice"] == "Wait" and s["text"] == "typed before the refresh" and s["dis"] is False, s)
        sent(pg, ROW.format(3) + " button[name=act]")
        a = last(3); check("after that refresh the card and the note are both stored", a.get("choice") == "Wait" and a.get("text") == "typed before the refresh", a)

        # 4 a refresh before the pick (the section is swapped in place), then the pick, the note and Send
        home(pg, 4); redraw(lambda: item(21, needs=["decision"], ask=ASK, options=OPTS2)); poll(pg)
        pg.wait_for_selector("li#task-a-21 form.hanswer[data-cards]:not([hidden])", timeout=8000)
        pick(pg, 4, "Ship", "picked after the refresh")
        sent(pg, ROW.format(4) + " button[name=act]")
        a = last(4); check("a refresh before the pick: the card and the note are both stored", a.get("choice") == "Ship" and a.get("letter") == "A" and a.get("text") == "picked after the refresh", a)

        # 5 Ctrl+Enter in the box
        home(pg, 5); pick(pg, 5, "Ship", "sent by the keyboard")
        with pg.expect_navigation(timeout=8000): pg.press("#atext-a5", "Control+Enter")
        a = last(5); check("Ctrl+Enter sends the card with the note", a.get("choice") == "Ship" and a.get("text") == "sent by the keyboard", a)

        # 6 a refresh already under way (and a frame that differs, as after a deploy) when the card is picked: no reload under the pick
        home(pg, 6)
        pg.evaluate("""() => { window.__marker = 'same page'; const of = window.fetch; window.__held = false; window.__rel = null;
            window.fetch = function(u, o) { const a = arguments; if (o && o.headers && o.headers.Accept === 'text/html') { window.__held = true;
                return new Promise(res => { window.__rel = () => of.apply(window, a).then(r => r.text()).then(t => res(new Response(t.replace(/(<meta name="stackshot-shell" content=")[^"]*/, '$1changed'), {status: 200}))) }) }
              return of.apply(window, a) } }""")      # the refresh's page fetch waits here, and when it is let go it brings a page whose frame differs
        redraw(lambda: item(22, needs=["decision"], ask=ASK, options=OPTS2)); pg.wait_for_timeout(2200); pg.evaluate("window.dispatchEvent(new Event('focus'))"); pg.wait_for_timeout(1500)
        check("the refresh is under way (its page fetch is waiting)", pg.evaluate("window.__held") is True)
        pick(pg, 6, "Wait", "picked while the refresh was on its way")
        pg.evaluate("window.__rel && window.__rel()"); pg.wait_for_timeout(2500)
        s = state(pg, 6); mark = pg.evaluate("window.__marker")
        check("a refresh under way when the card is picked does not reload the page under the pick", mark == "same page" and s and s["choice"] == "Wait" and s["text"] == "picked while the refresh was on its way", (mark, s))

        # 7 item page: a card and a note, Send
        pg.goto(BASE + "/items/a7"); pg.wait_for_selector("form.ianswer[data-cards]", timeout=8000)
        pg.click("form.ianswer .acard:has-text('Wait')"); pg.fill("#atext", "on the item page"); pg.wait_for_timeout(100)
        with pg.expect_navigation(timeout=8000): pg.click("form.ianswer button[name=act]")
        pg.wait_for_timeout(300)
        a = last(7); check("item page, two options: the card and the note are both stored", a.get("choice") == "Wait" and a.get("text") == "on the item page", a)
        pg.goto(BASE + "/items/a8"); pg.wait_for_selector("form.ianswer[data-cards]", timeout=8000)
        pg.click("form.ianswer .acard:has-text('Drop')"); pg.fill("#atext", "three options here"); pg.wait_for_timeout(100)
        with pg.expect_navigation(timeout=8000): pg.press("#atext", "Control+Enter")
        pg.wait_for_timeout(300)
        a = last(8); check("item page, three options, Ctrl+Enter: the card and the note are both stored", a.get("choice") == "Drop" and a.get("letter") == "C" and a.get("text") == "three options here", a)
        ctx.close(); br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)
print(f"ok: decision-pick check, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
