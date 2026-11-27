"""Item brief check (a browser; run by .github/workflows/brief.yml, not in the suite loop). The route and what the pages say are tests/brief_scenario.py; this is what only a browser
shows. It starts the server in-process over HTTPS on localhost with a temporary config and fixture data (no live store, no network beyond this machine). A browser signed in with the
board's cookie then checks that:

  - on a wide screen a row opens in a panel on the right (address ?item=<key>), the lists stay beside it, Escape and Back close it, the list keeps its scroll, j and k step;
  - a pick and a note are one draft with the row's, survive closing, the live refresh and a changed item; a send records one answer and moves on; a send that fails records nothing;
  - at 390 px it is a bottom sheet that fits, closes by a drag, the dimmed page and Back, and keeps the answer box in view;
  - the "?" shows its words on hover, focus and tap; the full screen page fits and carries the draft there;
  - without the script, and when a brief cannot be read, a row leads to the item's page.

    tests/run-suite brief_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    BRIEF_SHOTS=<folder> also saves screenshots there."""
import json, logging, os, pathlib, re, socket, ssl, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="briefchk-"); T = pathlib.Path(tmp)
SHOTS = os.environ.get("BRIEF_SHOTS", "")
EMAIL = "oliver@example.org"

subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout", str(T / "tls.key"), "-out", str(T / "tls.crt")], check=True, capture_output=True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BOARD = f"https://localhost:{PORT}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
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
ASK = "Decide: whether to ship the next version of the sample app · Recommend: ship · Stakes: the users wait another week otherwise · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release window", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature for this version", "recommended": False}]
DESC = "\n".join(f"- background fact number {n}: the sample app has a part that this line describes in a few words" for n in range(1, 9))
LONG = "https://example.org/" + "averyveryveryunbrokenaddress" * 5


def item(i, ask=ASK, opts=OPTS, description=DESC, subject=None, **meta):
    m = {"owner": OWNER, "project": "projects/alpha", "next": "the next step", **meta}
    if ask: m.update(needs=["decision"], ask=ask)
    if opts: m["options"] = opts
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] {subject or f'sample question a{i}'}", "description": description, "status": "open",
                                                     "updated": now - 3600 - i, "state_updated": now - 3600 - i, "confirmed": now - 3600, "metadata": m}))


for i in range(1, 7):
    item(i, answers=[{"ts": now - 90000, "kind": "decision", "choice": "Wait", "text": "not this week", "via": "board"}] if i == 1 else [])
item(7, ask=None, opts=None, state="your-step", step="run the one line `true`", needs=["home-here"])
LONG_ITEM = dict(ask=f"Decide: whether {LONG} · Recommend: yes · Stakes: {LONG} · By: no date", subject="an item with " + LONG, description=f"- {LONG}\n\n```\n{LONG}\n```",
                 opts=[{"label": "A" * 60, "line": LONG, "recommended": True}, {"label": "B", "line": LONG, "recommended": False}])
item(8, **LONG_ITEM)
for i in range(10, 40): item(i, ask=None, opts=None, subject=f"work under way a{i}")
(T / "store/next-id").write_text("60"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")


def git(*a): subprocess.run(["git", "-C", str(T / "store"), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)


git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn
from stackshot.web import server, board_home
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.service import answer as answer_svc, telling
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.auth import signin as _signin
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
answer_svc._answer_deliver = lambda *a, **k: []


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def answers(i): return [a for a in (rd(i).get("metadata") or {}).get("answers") or [] if a.get("kind") == "decision" and a.get("ts", 0) > now]


def rewrite(i, **meta):
    """another session changes an item, and the next read of the home draws it anew"""
    time.sleep(1.2)                          # the page's stamp counts whole seconds
    d = rd(i); d["metadata"].update(meta); d["updated"] = d["state_updated"] = time.time()
    (T / f"store/a/{i}.json").write_text(json.dumps(d)); git("add", "-A"); git("commit", "-q", "-m", f"change a{i}")
    board_home._board_home_drop()


fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"), flush=True)
    if not cond: fails.append(name)


srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="warning", lifespan="on", ssl_certfile=str(T / "tls.crt"), ssl_keyfile=str(T / "tls.key")))
th = threading.Thread(target=srv.run, daemon=True); th.start()


def cookie():
    return {"name": _signin._UI_COOKIE, "value": _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "domain": "localhost", "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "Lax"}


def row(i): return f"li.irow.hrow:has(a.ir-link[href='/items/a{i}'])"


def shot(pg, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True); pg.wait_for_timeout(300); pg.screenshot(path=str(pathlib.Path(SHOTS, name + ".png")))


def loaded(pg, i):
    pg.wait_for_selector(f"#brief article.bitem[data-key='a{i}']", timeout=10000)


def open_(pg, i, how="a.ir-link"):
    pg.click(f"{row(i)} {how}"); loaded(pg, i)


def closed(pg):
    pg.wait_for_selector("#brief", state="hidden", timeout=5000)


def home(pg, query=""):
    pg.goto(BOARD + "/" + query); pg.wait_for_selector(f"{row(12)} .bopen", state="attached", timeout=10000)
    pg.evaluate("() => { document.querySelector('#agents-at-work > details').open = true }")      # the list of items under way starts closed


def poll(pg, until=None):
    """bring the page back to the front as a person does, until `until` (a JavaScript test) holds"""
    for _ in range(5):
        pg.wait_for_timeout(2100)                # the page asks for the stamp at most every two seconds
        pg.evaluate("() => window.dispatchEvent(new Event('focus'))")
        if not until: return
        try:
            pg.wait_for_function(until, timeout=2500); return
        except Exception:  # noqa: BLE001  — the next try asks again; the caller's own wait reports a miss
            pass


def state(pg):
    """what the panel and the page hold now"""
    return pg.evaluate("""() => { const p = document.getElementById('brief'), f = p.querySelector('form.ianswer'), c = f && f.querySelector('input[name=choice]:checked'),
        t = f && f.querySelector('textarea'), b = f && f.querySelector('button[name=act]'), o = p.querySelector('.bpicked');
        return {open: !p.hidden, url: location.pathname + location.search, pick: c ? c.value : '', note: t ? t.value : '', send: b ? !b.disabled : null, picked: o ? o.textContent : '',
                y: window.scrollY, inside: p.contains(document.activeElement), current: [...document.querySelectorAll('li.irow.is-open a.ir-link')].map(a => a.getAttribute('href'))} }""")


def rowstate(pg, i):
    return pg.evaluate("""(s) => { const li = document.querySelector(s), f = li.querySelector('form.hanswer'), c = f && f.querySelector('input[name=choice]:checked'), t = f && f.querySelector('textarea');
        return {form: !!f, pick: c ? c.value : '', note: t ? t.value : '', sent: li.classList.contains('sent'), hidden: f ? f.hidden : null, text: li.innerText} }""", row(i))


def visible(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); return !e.hidden && e.getClientRects().length > 0 && getComputedStyle(e).visibility === 'visible' ? 'visible' : 'hidden' }", sel)


def desktop(br, errors):
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}); ctx.add_cookies([cookie()])
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    home(pg)
    check("every row has its button", pg.eval_on_selector_all("li.irow.hrow", "l => l.length > 5 && l.every(x => x.querySelectorAll('.bopen').length === 1)"))
    order = pg.eval_on_selector_all("li.irow.hrow a.ir-link", "l => l.filter(a => a.getClientRects().length).map(a => a.getAttribute('href'))")
    shot(pg, "desktop-home")
    top = "(s) => document.querySelector(s).getBoundingClientRect().top"
    pg.evaluate("(s) => document.querySelector(s).scrollIntoView({block: 'start'})", row(3)); y, at3 = pg.evaluate("() => window.scrollY"), pg.evaluate(top, row(3))
    open_(pg, 3); s = state(pg)
    check("a title opens the panel, the address names the item, the row is marked", s["open"] and s["url"] == "/?item=a3" and s["current"] == ["/items/a3"] and s["inside"], s)
    box = pg.eval_on_selector("#brief", "e => { const r = e.getBoundingClientRect(); return {x: r.x, w: r.width, h: r.height} }")
    pad = pg.eval_on_selector("#layout", "e => parseFloat(getComputedStyle(e).paddingRight)")
    edge = pg.evaluate("() => document.documentElement.clientWidth")      # the window less its scrollbar, where a fixed element's right edge sits
    check("the panel stands on the right and the lists make room for it", abs(box["x"] + box["w"] - edge) < 1 and box["w"] == 560 and box["h"] == 800 and pad >= 559, (box, pad, edge))
    check("nothing scrolls sideways", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
    send = pg.eval_on_selector("#brief button[name=act]", "e => e.getBoundingClientRect().bottom")
    check("Send is in view with nothing picked, and is off", send <= 800 and s["send"] is False and s["picked"] == "Picked: none yet", (send, s))
    check("the inline hint is not drawn", pg.eval_on_selector("#brief .ahint", "e => getComputedStyle(e).display") == "none")
    shot(pg, "desktop-panel")
    check("the lists stay in use: the page is not inert", pg.evaluate("() => !document.querySelector('#layout').inert && document.getElementById('brief-scrim').hidden"))

    # the "?"
    check("the explanation is put away until asked for", visible(pg, "#xp-brief-pick-a3") == "hidden")
    pg.hover("#brief .xp-b"); check("…it shows on hover", visible(pg, "#xp-brief-pick-a3") == "visible")
    tip = pg.eval_on_selector("#xp-brief-pick-a3", "e => { const r = e.getBoundingClientRect(); return [r.left, r.right] }")
    check("…inside the panel", tip[0] >= box["x"] and tip[1] <= 1280, tip)
    shot(pg, "desktop-tooltip")
    pg.keyboard.press("Escape"); check("Escape puts it away and the panel stays", visible(pg, "#xp-brief-pick-a3") == "hidden" and state(pg)["open"])
    pg.mouse.move(5, 5); pg.focus("#brief textarea")
    for _ in range(4):
        pg.keyboard.press("Tab")
        if pg.evaluate("() => document.activeElement.classList.contains('xp-b')"): break
    check("…it shows on keyboard focus", pg.evaluate("() => document.activeElement.classList.contains('xp-b')") and visible(pg, "#xp-brief-pick-a3") == "visible")
    pg.click("#brief .bhead"); check("…and goes when the focus leaves", visible(pg, "#xp-brief-pick-a3") == "hidden")

    # Escape, Back, scroll, focus
    pg.keyboard.press("Escape"); closed(pg); pg.wait_for_function("() => location.search === ''"); s = state(pg)
    check("Escape closes it, the address is the list's again and the focus is back on the row", s["url"] == "/" and s["current"] == [] and pg.evaluate("() => document.activeElement.getAttribute('href')") == "/items/a3", s)
    check("the list kept its place", y > 0 and abs(pg.evaluate(top, row(3)) - at3) <= 4, (y, s["y"], at3, pg.evaluate(top, row(3))))
    open_(pg, 3); pg.go_back(); closed(pg); s = state(pg)
    check("Back closes it, the list in its place", s["url"] == "/" and not s["open"] and abs(pg.evaluate(top, row(3)) - at3) <= 4, (y, s, at3, pg.evaluate(top, row(3))))
    pg.go_forward(); loaded(pg, 3); check("Forward opens it again", state(pg)["url"] == "/?item=a3", state(pg))
    pg.click("#brief [data-bact=close]"); closed(pg); pg.wait_for_function("() => location.search === ''")
    open_(pg, 3, ".bopen"); check("the row's button opens it too", state(pg)["open"])
    at = order.index("/items/a3"); nxt = order[(at + 1) % len(order)].rsplit("/", 1)[1]; after = order[(at + 2) % len(order)].rsplit("/", 1)[1]
    pg.keyboard.press("j"); pg.wait_for_selector(f"#brief article[data-key='{nxt}']"); pg.keyboard.press("j"); pg.wait_for_selector(f"#brief article[data-key='{after}']")
    pg.wait_for_function(f"() => location.search === '?item={after}'")
    check("j steps to the next row", True)
    pg.keyboard.press("k"); pg.wait_for_selector(f"#brief article[data-key='{nxt}']"); pg.wait_for_function(f"() => location.search === '?item={nxt}'")
    pg.go_back(); closed(pg)
    check("one Back leaves the panel after stepping", state(pg)["url"] == "/", state(pg))

    # one draft with the row
    open_(pg, 2)
    pg.click("#brief .acard:has-text('Drop')"); pg.fill("#brief textarea", "a note kept with the pick"); r = rowstate(pg, 2); s = state(pg)
    check("a pick and a note show in the row too", r["form"] and "Drop" in r["pick"] and r["note"] == "a note kept with the pick", r)
    check("the picked line names the pick, Send is on", s["picked"].startswith("Picked: ") and "Drop" in s["picked"] and s["send"], s)
    pg.keyboard.press("Escape")
    check("Escape in the box leaves the box first", state(pg)["open"] and pg.evaluate("() => document.activeElement.id") == "brief", state(pg))
    pg.keyboard.press("Escape"); closed(pg)
    open_(pg, 1); check("another item starts empty", state(pg)["note"] == "" and state(pg)["pick"] == "", state(pg))
    open_(pg, 2); s = state(pg); check("the draft is back when the item is", "Drop" in s["pick"] and s["note"] == "a note kept with the pick" and s["send"], s)
    open_(pg, 1)
    pg.evaluate("(s) => { const t = document.querySelector(s + ' form.hanswer textarea'); t.value = 'typed in the row'; t.dispatchEvent(new Event('input', {bubbles: true})) }", row(1))
    check("what is typed in a row shows in the open item's panel", state(pg)["note"] == "typed in the row", state(pg))
    pg.keyboard.press("Escape"); closed(pg); open_(pg, 1)
    check("…and is there when it is opened again", state(pg)["note"] == "typed in the row", state(pg))
    pg.evaluate("(s) => { const t = document.querySelector(s + ' form.hanswer textarea'); t.value = ''; t.dispatchEvent(new Event('input', {bubbles: true})) }", row(1))

    # the live refresh and a change under an open item
    open_(pg, 5); pg.fill("#brief textarea", "half written"); pg.click("#brief .acard:has-text('Wait')"); pg.evaluate("() => { window.sameDocument = true }")
    rewrite(5, ask=ASK.replace("next version", "rewritten version")); poll(pg, "() => !!document.querySelector('#brief .bchanged')"); pg.wait_for_selector("#brief .bchanged", timeout=10000); s = state(pg)
    check("a change under a half-written answer is told, the answer stays", s["note"] == "half written" and "Wait" in s["pick"] and "rewritten" not in pg.inner_text("#brief"), s)
    shot(pg, "desktop-changed")
    pg.click("#brief .bchanged button"); pg.wait_for_selector("#brief .bchanged", state="detached"); pg.wait_for_function("() => document.querySelector('#brief').innerText.includes('rewritten')"); s = state(pg)
    check("the latest keeps the note and drops the pick made on the old question", s["note"] == "half written" and s["pick"] == "" and answers(5) == [], s)
    open_(pg, 6); rewrite(6, ask=ASK.replace("next version", "second version")); poll(pg, "() => document.querySelector('#brief').innerText.includes('second version')")
    pg.wait_for_function("() => document.querySelector('#brief').innerText.includes('second version')", timeout=10000)
    check("with nothing written the open item is simply drawn anew", pg.query_selector("#brief .bchanged") is None and pg.evaluate("() => window.sameDocument === true"))

    # a draft on an item whose row has no box, while the whole page wants a reload
    home(pg); open_(pg, 10); pg.fill("#brief textarea", "a comment under way"); pg.click("#brief .bhead")
    pg.evaluate("() => { window.sameDocument = true; document.querySelector('meta[name=\"stackshot-shell\"]').content = 'another-frame' }")
    rewrite(11, next="something else now"); poll(pg); pg.wait_for_timeout(2500)
    check("the live refresh does not reload the page over a draft in the panel", pg.evaluate("() => window.sameDocument === true") and state(pg)["note"] == "a comment under way", state(pg))
    pg.fill("#brief textarea", ""); pg.click("#brief .bhead"); rewrite(11, next="and again"); poll(pg, "() => window.sameDocument === undefined")
    pg.wait_for_function("() => window.sameDocument === undefined", timeout=10000)
    check("…and with nothing written it reloads as before, the panel open again", True)
    loaded(pg, 10)

    # sends that write nothing
    home(pg); open_(pg, 4); pg.fill("#brief textarea", "kept when the send fails")
    pg.route("**/items/a4/answer", lambda r: r.abort()); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief .aerr:not([hidden])"); s = state(pg)
    check("a send that cannot reach the board says so and keeps the note", "Nothing sent" in pg.inner_text("#brief .aerr") and s["note"] == "kept when the send fails" and s["send"] and answers(4) == [], (s, pg.inner_text("#brief .aerr")))
    pg.unroute("**/items/a4/answer")
    pg.route("**/items/a4/answer", lambda r: r.fulfill(status=200, content_type="application/json", body='{"sent":"empty"}')); pg.click("#brief button[name=act]")
    pg.wait_for_function("() => document.querySelector('#brief .aerr').textContent.includes('pick an option')"); s = state(pg)
    check("a notice that wrote nothing leaves the box as it is", s["note"] == "kept when the send fails" and pg.query_selector("#brief .bsent") is None and not rowstate(pg, 4)["sent"], s)
    pg.unroute("**/items/a4/answer")
    pg.fill("#brief textarea", ""); pg.click("#brief .acard:has-text('Ship')"); rewrite(4, ask=ASK.replace("next version", "third version")); pg.click("#brief button[name=act]")
    pg.wait_for_selector("#brief .bsent .isent.warn", timeout=10000)
    check("a pick on a question written again records nothing and says so", answers(4) == [] and not rowstate(pg, 4)["sent"], (answers(4), pg.inner_text("#brief .bsent")))

    # a send
    home(pg); open_(pg, 7); shot(pg, "desktop-step")
    open_(pg, 2); pg.click("#brief .acard:has-text('Drop')")
    pg.fill("#brief textarea", "sent from the panel"); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief .bsent .bnext", timeout=10000); s = state(pg)
    check("one answer is recorded, from one click", len(answers(2)) == 1 and "Drop" in str(answers(2)[0].get("choice")) and answers(2)[0].get("text") == "sent from the panel", answers(2))
    r = rowstate(pg, 2)
    check("the row says it was sent and its box is put away", r["sent"] and r["hidden"] in (True, None) and "Sent" in r["text"], r)
    check("the panel says so, with no box left", pg.query_selector("#brief form.ianswer[data-cards]") is None and not pg.is_visible("#brief textarea") and s["inside"], s)
    shot(pg, "desktop-sent")
    pg.click("#brief .bnext"); pg.wait_for_function("() => document.querySelector('#brief article') && document.querySelector('#brief article').getAttribute('data-key') !== 'a2'")
    check("next goes to a question still waiting", state(pg)["open"] and state(pg)["url"] != "/?item=a2", state(pg))
    for _ in range(12):
        pg.wait_for_function("() => !!document.querySelector('#brief article') || document.getElementById('brief').hidden")
        if not state(pg)["open"]: break
        key = pg.eval_on_selector("#brief article", "e => e.getAttribute('data-key')")
        if pg.query_selector("#brief form.ianswer[data-step]"):
            pg.click("#brief button[value=done]")
        else:
            pg.click("#brief .acard >> nth=0"); pg.focus("#brief textarea"); pg.keyboard.press("Control+Enter")
        pg.wait_for_selector("#brief .bnext", timeout=10000); pg.click("#brief .bnext")
        pg.wait_for_function("(k) => { const a = document.querySelector('#brief article'); return document.getElementById('brief').hidden || (!!a && a.getAttribute('data-key') !== k) }", arg=key, timeout=10000)
    check("after the last one the panel closes and says all are answered", not state(pg)["open"] and pg.is_visible("#brief-toast") and "All answered" in pg.inner_text("#brief-toast"), state(pg))
    check("…each answered once", all(len(answers(i)) == 1 for i in (1, 2, 3, 4, 5, 6, 8)), {i: len(answers(i)) for i in range(1, 9)})

    # opening by address; addresses that are not the panel's
    pg.goto(BOARD + "/?item=a12"); loaded(pg, 12); pg.keyboard.press("Escape"); closed(pg)
    check("an address that names an item opens it, and closing stays on the list", state(pg)["url"] == "/", state(pg))
    pg.goto(BOARD + "/?sent=decision&item=a12"); pg.wait_for_timeout(1500)
    check("the address of a row's own send is not the panel's", not state(pg)["open"], state(pg))
    pg.goto(BOARD + "/?item=../x"); pg.wait_for_timeout(800); check("an address that names no item form opens nothing", not state(pg)["open"], state(pg))

    # a new tab, and a brief that cannot be read
    home(pg)
    with ctx.expect_page() as new:
        pg.click(f"{row(12)} a.ir-link", modifiers=["Control"])
    other = new.value; other.wait_for_url(BOARD + "/items/a12", timeout=10000)      # a new tab is about:blank before its first navigation
    check("Ctrl+click opens the item's page in a new tab and no panel", other.url == BOARD + "/items/a12" and not state(pg)["open"], other.url); other.close()
    pg.route("**/items/a13/brief*", lambda r: r.fulfill(status=500, body="broken")); pg.click(f"{row(13)} a.ir-link"); pg.wait_for_url(BOARD + "/items/a13", timeout=10000)
    check("a brief that cannot be read leads to the item's page", True)
    pg.go_back(); pg.wait_for_selector(f"{row(1)} .bopen"); pg.wait_for_timeout(500)
    check("…and Back from there is the list, with no panel", pg.url == BOARD + "/" and not state(pg)["open"], pg.url)
    pg.unroute("**/items/a13/brief*"); ctx.close()


def fullpage(br, errors):
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}); ctx.add_cookies([cookie()])
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    item(40); git("add", "-A"); git("commit", "-q", "-m", "a40"); board_home._board_home_drop()
    home(pg); open_(pg, 40); pg.fill("#brief textarea", "carried to the full page"); pg.click("#brief .acard:has-text('Ship')")
    pg.click("#brief [data-bact=full]"); pg.wait_for_url(BOARD + "/items/a40/brief"); pg.wait_for_selector("#brief-page article")
    pg.wait_for_function("() => document.querySelector('#brief-page textarea').value !== ''", timeout=5000)
    got = pg.evaluate("() => ({t: document.querySelector('#brief-page textarea').value, c: (document.querySelector('#brief-page input[name=choice]:checked') || {}).value, p: document.querySelector('#brief-page .bpicked').textContent})")
    check("full screen keeps the draft", got["t"] == "carried to the full page" and "Ship" in (got["c"] or "") and "Ship" in got["p"], got)
    check("the full page fits", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
    shot(pg, "desktop-full")
    pg.click("#brief-page button[name=act]"); pg.wait_for_url(re.compile(r"/items/a40/brief\?sent=decision$"), timeout=10000); pg.wait_for_selector("#brief-page .bsent .isent.ok")
    check("a send on the full page records one answer and says so there", len(answers(40)) == 1 and answers(40)[0].get("text") == "carried to the full page", answers(40))
    item(42, **LONG_ITEM); git("add", "-A"); git("commit", "-q", "-m", "a42"); board_home._board_home_drop()
    pg.goto(BOARD + "/items/a42/brief"); pg.wait_for_selector("#brief-page article")
    check("long unbroken text does not widen the full page", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")); ctx.close()
    dark = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}, color_scheme="dark"); dark.add_cookies([cookie()])
    pg = dark.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    item(41); git("add", "-A"); git("commit", "-q", "-m", "a41"); board_home._board_home_drop()
    home(pg); open_(pg, 41); shot(pg, "desktop-panel-dark"); dark.close()


def phone(br, errors, scheme):
    n = 50 if scheme == "light" else 51
    item(n); item(n + 5, ask=None, opts=None, state="your-step", step="run the one line `true`", needs=["home-here"])
    git("add", "-A"); git("commit", "-q", "-m", f"a{n}"); board_home._board_home_drop()
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2, color_scheme=scheme); ctx.add_cookies([cookie()])
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    home(pg); shot(pg, f"phone-home-{scheme}")
    reach = pg.eval_on_selector(f"{row(20)} .bopen", "b => { b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(), x = r.x + r.width / 2; return [r.height, [-20, 0, 20].every(d => document.elementFromPoint(x, r.y + r.height / 2 + d) === b)] }")
    check(f"{scheme}: the row's button is small to look at and a full target for a finger", reach[0] < 32 and reach[1], reach)
    pg.evaluate("(s) => document.querySelector(s).scrollIntoView({block: 'center'})", row(20)); y = pg.evaluate("() => window.scrollY")
    pg.tap(f"{row(20)} .bopen"); loaded(pg, 20); pg.keyboard.press("Escape"); closed(pg)
    check(f"{scheme}: the list is where it was after the sheet", y > 0 and abs(pg.evaluate("() => window.scrollY") - y) < 2, (y, pg.evaluate("() => window.scrollY")))
    pg.tap(f"{row(n)} a.ir-link"); loaded(pg, n)
    box = pg.eval_on_selector("#brief", "e => { const r = e.getBoundingClientRect(); return {x: r.x, w: r.width, h: r.height, b: r.bottom} }")
    check(f"{scheme}: a bottom sheet, the full width and most of the height", box["x"] == 0 and box["w"] == 390 and abs(box["h"] - 0.92 * 844) < 2 and abs(box["b"] - 844) < 1, box)
    fit = pg.evaluate("() => { const b = document.querySelector('#brief .bbody'); return [document.documentElement.scrollWidth, b.scrollWidth, b.clientWidth] }")
    check(f"{scheme}: nothing scrolls sideways", fit[0] <= 390 and fit[1] <= fit[2], fit)
    check(f"{scheme}: the page behind is dimmed, still and out of reach", pg.evaluate("() => !document.getElementById('brief-scrim').hidden && document.documentElement.classList.contains('sheet') && document.getElementById('layout').inert && document.getElementById('brief').getAttribute('aria-modal') === 'true'"))
    send = pg.eval_on_selector("#brief button[name=act]", "e => e.getBoundingClientRect().bottom")
    small = pg.eval_on_selector_all("#brief .brief-bar .b, #brief .xp-b", "l => l.filter(e => e.getClientRects().length).map(e => [e.textContent, e.getBoundingClientRect().height]).filter(x => x[1] < 43.9)")
    check(f"{scheme}: Send is in view, the bar's buttons are large enough to tap", send <= 844 and small == [], (send, small))
    shot(pg, f"phone-sheet-{scheme}")
    side = pg.evaluate("() => ['#brief textarea', '#brief button[name=act]'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] })")
    (_, tr, tt, tb), (bl, br_, bt, bb) = side
    check(f"{scheme}: Send stands beside the note box, on its line", tr <= bl and br_ <= 390 and abs((tt + tb) / 2 - (bt + bb) / 2) < 6, side)
    low =pg.eval_on_selector("#brief textarea", "e => e.getBoundingClientRect().height")
    pg.tap("#brief textarea"); pg.wait_for_timeout(300)
    tall = pg.eval_on_selector("#brief textarea", "e => [e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).fontSize)]")
    check(f"{scheme}: the note box is one line until used, with text large enough not to zoom", low < 50 and tall[0] >= 80 and tall[1] >= 16, (low, tall))
    pg.fill("#brief textarea", "\n".join(["a line of the note"] * 8)); grown = pg.eval_on_selector("#brief textarea", "e => e.getBoundingClientRect().height")
    check(f"{scheme}: …and grows with its text", grown > tall[0] + 20, (tall, grown)); pg.fill("#brief textarea", "")
    why = f"#xp-brief-pick-a{n}"
    pg.tap("#brief .xp-b"); pg.wait_for_selector(why, timeout=5000); tip = pg.eval_on_selector(why, "e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] }")
    check(f"{scheme}: a tap on ? shows the words, on the screen", tip[0] >= 0 and tip[1] <= 390 and tip[2] >= 0 and tip[3] <= 844, tip)
    shot(pg, f"phone-tooltip-{scheme}")
    pg.tap("#brief .xp-b"); check(f"{scheme}: a second tap puts them away", visible(pg, why) == "hidden")
    head = pg.eval_on_selector("#brief .bhead", "e => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }")
    pg.mouse.move(*head); pg.mouse.down(); pg.mouse.move(head[0], head[1] + 40, steps=4); pg.mouse.up()
    check(f"{scheme}: a short drag leaves it open", state(pg)["open"])
    pg.mouse.move(*head); pg.mouse.down(); pg.mouse.move(head[0], head[1] + 180, steps=8); pg.mouse.up(); closed(pg)
    check(f"{scheme}: a drag down closes it", pg.evaluate("() => !document.documentElement.classList.contains('sheet') && !document.getElementById('layout').inert"))
    pg.tap(f"{row(n)} .bopen"); loaded(pg, n); pg.touchscreen.tap(195, 20); closed(pg)
    check(f"{scheme}: a tap on the dimmed page closes it", state(pg)["url"] == "/", state(pg))
    pg.tap(f"{row(n)} .bopen"); loaded(pg, n); pg.go_back(); closed(pg)
    check(f"{scheme}: Back closes it", state(pg)["url"] == "/", state(pg))
    pg.goto(BOARD + f"/?item=a{n + 5}"); loaded(pg, n + 5); shot(pg, f"phone-step-{scheme}")
    pg.goto(BOARD + "/?item=a42"); loaded(pg, 42)
    fit = pg.evaluate("() => { const b = document.querySelector('#brief .bbody'); return [document.documentElement.scrollWidth, b.scrollWidth, b.clientWidth] }")
    check(f"{scheme}: long unbroken text stays inside the sheet", fit[0] <= 390 and fit[1] <= fit[2], fit)
    shot(pg, f"phone-long-{scheme}")
    pg.goto(BOARD + "/items/a42/brief"); pg.wait_for_selector("#brief-page article")
    check(f"{scheme}: long unbroken text does not widen the full page", pg.evaluate("() => document.documentElement.scrollWidth") <= 390, pg.evaluate("() => document.documentElement.scrollWidth"))
    pg.goto(BOARD + f"/items/a{n}/brief"); pg.wait_for_selector("#brief-page article"); shot(pg, f"phone-full-{scheme}"); ctx.close()


def noscript(br):
    ctx = br.new_context(ignore_https_errors=True, java_script_enabled=False); ctx.add_cookies([cookie()])
    pg = ctx.new_page(); pg.goto(BOARD + "/"); pg.wait_for_selector("li.irow.hrow a.ir-link")
    check("without the script there is no panel button and no panel", pg.query_selector(".bopen") is None and not pg.is_visible("#brief"))
    pg.click("#agents-at-work > details > summary")
    with ctx.expect_page() as new:
        pg.click(f"{row(12)} a.ir-link")
    other = new.value; other.wait_for_url(BOARD + "/items/a12", timeout=10000)
    check("…a row's title opens the item's page", other.url == BOARD + "/items/a12", other.url); ctx.close()


def run(br):
    errors = []
    desktop(br, errors); fullpage(br, errors); phone(br, errors, "light"); phone(br, errors, "dark"); noscript(br)
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

print(("ok" if not fails else "FAILED") + f": brief check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
