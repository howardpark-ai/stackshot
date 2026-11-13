"""Answer-and-Back check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Starts the
server in-process on 127.0.0.1 with a temporary config and fixture data (no live store, no network, the mirror off, nobody
told), signs a browser in with the board's cookie, and drives the real flow in Chromium:

  - board → item page → an option's card and Send (with a note in the box): the answer is recorded, the page lands on the item with
    its "Sent" notice, history.length is what it was before the answer (the answer replaced the page, it did not stack one),
    and Back lands on the board;
  - while the request runs, every button of the form is disabled and the form is aria-busy;
  - a refused answer (a stale token) shows the server's words under the buttons, the text stays in the box, the buttons come
    back, and the page and its history are unchanged;
  - without script the form is still the plain POST and its 303: the answer is recorded and Back shows the item page
    before the answer (one entry more), as it always did;
  - the step form of a your-step item (the note box with Done and Send note): Send note is greyed on a blank box with its hint as the
    title and enabled once there is text; Ctrl+Enter in the box means Done and the notice says the note went along; after a refused post
    the form is put back as its box says (the page's resync), the text kept;
  - an item page restored from the back-forward cache reloads (a synthetic pageshow with persisted; and whether Chromium here
    restored it from that cache at all, reported, not required: headless Chromium may not use the cache for a no-store page).

    tests/run-suite answer_back_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, sys, tempfile, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="answerback-"); T = pathlib.Path(tmp)
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
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "A thing. It lives here. Done when it works.",
                                                     "status": "open", "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", **meta}}))
for i in (1, 2, 3, 4, 6): item(i, needs=["decision"], ask=ASK, options=OPTS)
item(5)
for i in (7, 8): item(i, state="your-step", step="Call the office and say done")
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
import subprocess
def git(*a): subprocess.run(["git", "-C", str(T / "store"), *a], check=True, capture_output=True)
git("init", "-q"); git("config", "user.email", "t@example.org"); git("config", "user.name", "t"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn; from stackshot.web import server
from stackshot.service import telling
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

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

COOKIE = {"name": server._UI_COOKIE, "value": server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "url": BASE}
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        def tab(js=True):
            ctx = br.new_context(java_script_enabled=js, viewport={"width": 412, "height": 900}); ctx.add_cookies([COOKIE]); return ctx, ctx.new_page()

        # 1. with script: the answer replaces the page; Back goes to the board
        ctx, pg = tab()
        pg.goto(BASE + "/"); pg.goto(BASE + "/items/a1"); h0 = pg.evaluate("history.length")
        pg.fill("#atext", "with a note"); pg.click('label.acard:has(input[value="Ship"])'); pg.click('button[name="act"][value="answer"]'); pg.wait_for_url(BASE + "/items/a1?sent=decision")
        m1 = rd(1)["metadata"]; h1 = pg.evaluate("history.length")
        check("script: the option's answer is recorded with the box's note", [(a.get("choice"), a.get("text")) for a in m1.get("answers", [])] == [("Ship", "with a note")] and "decision" not in m1.get("needs", []), m1)
        check("script: the page lands on the item with its notice", "Sent: your answer is on the item" in pg.text_content("p.isent.ok") , pg.url)
        check("script: history.length is unchanged by the answer (the page was replaced, not stacked)", h1 == h0, (h0, h1))
        pg.go_back(); pg.wait_for_load_state()
        check("script: Back lands on the board", pg.url == BASE + "/", pg.url)
        ctx.close()

        # 2. the buttons are disabled while the request runs
        real = server._answer
        server._answer = lambda *a: (time.sleep(1.0), real(*a))[1]
        ctx, pg = tab()
        pg.goto(BASE + "/"); pg.goto(BASE + "/items/a2")
        pg.click('label.acard:has(input[value="Wait"])'); pg.click('button[name="act"][value="answer"]', no_wait_after=True); pg.wait_for_timeout(250)
        st = pg.evaluate("[[...document.querySelectorAll('form.ianswer button')].map(b => b.disabled), document.querySelector('form.ianswer').hasAttribute('aria-busy')]")
        check("script: while the request runs every button is disabled and the form is aria-busy", all(st[0]) and len(st[0]) == 1 and st[1], st)
        pg.wait_for_url(BASE + "/items/a2?sent=decision"); server._answer = real
        pg.go_back(); pg.wait_for_load_state()
        check("script: …and Back from there lands on the board too", pg.url == BASE + "/", pg.url)
        ctx.close()

        # 3. a refusal shows inline, the form left as it was
        ctx, pg = tab()
        pg.goto(BASE + "/"); pg.goto(BASE + "/items/a3"); h0 = pg.evaluate("history.length")
        pg.evaluate("document.querySelector('form.ianswer input[name=token]').value = 'stale'")
        pg.fill("#atext", "keep this text"); pg.click('button[name="act"][value="answer"]')
        pg.wait_for_selector("p.aerr:not([hidden])")
        err, txt, dis = pg.text_content("p.aerr"), pg.input_value("#atext"), pg.evaluate("[...document.querySelectorAll('form.ianswer button')].some(b => b.disabled)")
        check("script: a refused answer shows the server's words inline", err.startswith("Nothing sent: refused: the form's token does not match"), err)
        check("script: …the text stays in the box, the buttons come back, the page and its history are unchanged, nothing written",
              txt == "keep this text" and not dis and pg.url == BASE + "/items/a3" and pg.evaluate("history.length") == h0 and "answers" not in rd(3)["metadata"],
              (txt, dis, pg.url, "answers" in rd(3)["metadata"]))
        ctx.close()

        # 4. without script: the plain POST and 303, as before
        ctx, pg = tab(js=False)
        pg.goto(BASE + "/"); pg.goto(BASE + "/items/a4")
        pg.click('label.acard:has(input[value="Ship"])'); pg.click('button[name="act"][value="answer"]'); pg.wait_for_url(BASE + "/items/a4?sent=decision")
        check("no script: the plain form records the answer and lands on the item with its notice",
              [a.get("choice") for a in rd(4)["metadata"].get("answers", [])] == ["Ship"] and "Sent: your answer is on the item" in pg.text_content("p.isent.ok"), pg.url)
        pg.go_back(); pg.wait_for_load_state()
        check("no script: Back shows the item page before the answer (the entry the script replaces)", pg.url == BASE + "/items/a4", pg.url)
        ctx.close()

        # 5. back-forward cache: an item page restored from it reloads
        ctx, pg = tab()
        pg.goto(BASE + "/items/a5"); pg.evaluate("window.__kept = 1")
        with pg.expect_navigation():
            pg.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
        nav = pg.evaluate("[performance.getEntriesByType('navigation')[0].type, window.__kept === 1]")
        check("bfcache: a pageshow with persisted reloads the item page", nav == ["reload", False], nav)
        pg.evaluate("window.__kept = 1"); pg.goto(BASE + "/"); pg.go_back(); pg.wait_for_load_state(); pg.wait_for_timeout(300)
        nav = pg.evaluate("[performance.getEntriesByType('navigation')[0].type, window.__kept === 1]")
        print(f"note bfcache in this Chromium: Back to the item page → navigation type {nav[0]!r}"
              + (" (restored from the cache, then reloaded by the page)" if nav[0] == "reload" else " (fetched afresh: this browser did not keep the page in the cache)" if nav[0] == "back_forward" else ""))
        check("bfcache: Back to an item page never shows the cached copy as it was", nav[1] is False, nav)

        # 6. Ctrl+Enter sends the box's main button: Enter alone and an IME composition do not
        ctx, pg = tab()
        pg.goto(BASE + "/items/a6")
        posts = []
        pg.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        pg.click("#atext"); pg.keyboard.type("first line"); pg.keyboard.press("Enter"); pg.keyboard.type("second line"); pg.wait_for_timeout(300)
        check("ctrl+enter: Enter alone makes a new line and sends nothing", pg.input_value("#atext") == "first line\nsecond line" and not posts and "answers" not in rd(6)["metadata"], (pg.input_value("#atext"), posts))
        ime = pg.evaluate("""() => { const t = document.getElementById('atext'); return [t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, isComposing: true, bubbles: true, cancelable: true})),
            t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', metaKey: true, keyCode: 229, bubbles: true, cancelable: true}))] }""")
        pg.wait_for_timeout(400)
        check("ctrl+enter: Ctrl+Enter during an IME composition sends nothing", ime == [True, True] and not posts and "answers" not in rd(6)["metadata"], (ime, posts))
        tt = pg.evaluate("document.querySelector('form.ianswer button[name=act]').title")
        check("ctrl+enter: the Send button carries the key as its hover title", tt in ("Ctrl+Enter", "\u2318+Enter"), tt)
        pg.keyboard.press("Control+Enter"); pg.wait_for_url(BASE + "/items/a6?sent=decision")
        a6 = rd(6)["metadata"].get("answers", [])
        check("ctrl+enter: Ctrl+Enter in the box sends it as Send does: the text is recorded as his answer and the page lands on the item with its notice",
              [a.get("text") for a in a6] == ["first line\nsecond line"] and "Sent: your answer is on the item" in pg.text_content("p.isent.ok"), a6)
        ctx.close()

        # 7. the step form (a your-step item): Send note is greyed on a blank box with its hint and Done is not; Ctrl+Enter means Done; a failed post puts Send note back as the box says
        HINT = "Write a note to send it"
        ctx, pg = tab()
        pg.goto(BASE + "/items/a7")
        sn = lambda: pg.evaluate("(() => { const b = document.querySelector('form.ianswer button[value=note]'), d = document.querySelector('form.ianswer button[value=done]'); return [b.disabled, b.title, d.disabled] })()")
        check("step form: on a blank box Send note is disabled and says why in its title, and Done is enabled", sn() == [True, HINT, False], sn())
        pg.click("#atext"); pg.keyboard.type("   "); pg.wait_for_timeout(100)
        check("step form: a box of blanks counts as blank", sn() == [True, HINT, False], sn())
        pg.keyboard.type("a word"); pg.wait_for_timeout(100)
        check("step form: with text in the box Send note is enabled and its hint title is gone", sn() == [False, "", False], sn())
        pg.fill("#atext", ""); pg.wait_for_timeout(100)
        check("step form: emptying the box greys Send note again with its hint", sn() == [True, HINT, False], sn())
        pg.fill("#atext", "line one"); pg.wait_for_timeout(100)
        tt = pg.evaluate("document.querySelector('form.ianswer button[name=act]').title")
        check("step form: the first button of the form (Done) carries the key as its hover title", tt in ("Ctrl+Enter", "\u2318+Enter"), tt)
        pg.keyboard.press("Control+Enter"); pg.wait_for_url(re.compile(r".*/items/a7\?sent=donenote.*"))
        a7 = rd(7)["metadata"]
        check("step form: Ctrl+Enter in the box means Done: the step is finished and the note goes along (notice: your note went along)",
              "your note went along" in pg.text_content("p.isent.ok") and a7.get("state") != "your-step" and any(("line one" in json.dumps(a)) for a in a7.get("answers", [])), (pg.text_content("p.isent"), a7))
        ctx.close()

        # a failed post (a stale token): the form comes back as the box says: blank, Send note greyed with its hint; with text, Send note enabled
        ctx, pg = tab()
        pg.goto(BASE + "/items/a8")
        pg.evaluate("document.querySelector('form.ianswer input[name=token]').value = 'stale'")
        pg.click('button[name="act"][value="done"]'); pg.wait_for_selector("p.aerr:not([hidden])")
        check("step form: a refused Done on a blank box shows the server's words, and Send note is greyed again with its hint (Done is back)",
              pg.text_content("p.aerr").startswith("Nothing sent: refused") and sn() == [True, HINT, False] and "answers" not in rd(8)["metadata"], (pg.text_content("p.aerr"), sn()))
        pg.fill("#atext", "keep me"); pg.wait_for_timeout(100)
        pg.click('button[name="act"][value="note"]'); pg.wait_for_selector("p.aerr:not([hidden])")
        pg.wait_for_function("!document.querySelector('form.ianswer').hasAttribute('aria-busy')")
        check("step form: a refused Send note with text keeps the text, puts both buttons back (Send note enabled, no title), and writes nothing",
              pg.input_value("#atext") == "keep me" and sn() == [False, "", False] and "answers" not in rd(8)["metadata"] and rd(8)["metadata"].get("state") == "your-step", (pg.input_value("#atext"), sn(), rd(8)["metadata"]))
        ctx.close()
        br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)
print(f"ok: answer back check, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
