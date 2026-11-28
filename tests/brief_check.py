"""Item brief check (a browser; run by .github/workflows/brief.yml, not in the suite loop). The route and what the pages say are tests/brief_scenario.py; this is what only a browser
shows. It starts the server in-process over HTTPS on localhost with a temporary config and fixture data (no live store, no network beyond this machine). A browser signed in with the
board's cookie then checks that:

  - on a wide screen a row opens in a panel on the right (address ?item=<key>), the lists stay beside it, Escape and Back close it, the list keeps its scroll, j and k step;
  - a pick and a note are one draft with the row's, survive closing, the live refresh and a changed item; a send records one answer and moves on; a send that fails records nothing;
  - at 390 and 360 px it is a bottom sheet that fits, closes by a drag, the dimmed page and Back, and keeps the answer box in view;
  - the "?" shows its words on hover, focus and tap; the full screen page fits and carries the draft there;
  - one answer is sent once, from the panel, the item opened again or the row; a send under way on one item leaves the others alone; a failure or a reply that never comes is said;
  - a brief that cannot be read, and an item that cannot be read again after a send, never leave the page; drafts come back after a reload, the detail view and the full screen view,
    and where the browser keeps nothing leaving is asked about; a pick or a note that no longer fits its item is named or held; in the installed app a title opens the panel;
  - each of those fails when its line is taken out of the script as the page serves it (MUTANTS);
  - an item with a canvas shows it in the panel in a sandboxed frame whose own script runs, between the question and the choices, on a wide screen and at 390 px;
  - without the script a row leads to the item's page.

    tests/run-suite brief_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    BRIEF_SHOTS=<folder> also saves screenshots there."""
import hashlib, json, logging, os, pathlib, re, socket, ssl, subprocess, sys, threading, time
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
(T / "store/next-id").write_text("1000"); (T / "store/anchors.json").write_text("{}")
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
    pg.wait_for_selector(f"#brief article.bitem[data-key='a{i}']")


def open_(pg, i, how="a.ir-link"):
    pg.click(f"{row(i)} {how}"); loaded(pg, i)


def closed(pg):
    pg.wait_for_selector("#brief", state="hidden")


def home(pg, clean=False):
    """the home page; `clean`: with no draft left over from the checks before"""
    if clean: pg.evaluate("() => sessionStorage.clear()")
    pg.goto(BOARD + "/"); pg.wait_for_selector(f"{row(12)} .bopen", state="attached")
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
        t = f && f.querySelector('textarea'), b = f && f.querySelector('button[name=act]');
        return {open: !p.hidden, url: location.pathname + location.search, pick: c ? c.value : '', note: t ? t.value : '', send: b ? !b.disabled : null,
                y: window.scrollY, inside: p.contains(document.activeElement), current: [...document.querySelectorAll('li.irow.is-open a.ir-link')].map(a => a.getAttribute('href'))} }""")


def away(pg):
    """a click on the panel's head beside the item's link, which takes the focus off a box"""
    pg.click("#brief .bhead", position={"x": 4, "y": 2})


def rowstate(pg, i):
    return pg.evaluate("""(s) => { const li = document.querySelector(s), f = li.querySelector('form.hanswer'), c = f && f.querySelector('input[name=choice]:checked'), t = f && f.querySelector('textarea');
        return {form: !!f, pick: c ? c.value : '', note: t ? t.value : '', sent: li.classList.contains('sent'), hidden: f ? f.hidden : null, text: li.innerText} }""", row(i))


def visible(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); return !e.hidden && e.getClientRects().length > 0 && getComputedStyle(e).visibility === 'visible' ? 'visible' : 'hidden' }", sel)


def desktop(br, errors):
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}); ctx.add_cookies([cookie()]); ctx.set_default_timeout(10000)
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    home(pg)
    check("every row has its button", pg.eval_on_selector_all("li.irow.hrow", "l => l.length > 5 && l.every(x => x.querySelectorAll('.bopen').length === 1)"))
    pg.click(f"{row(2)} .ir-age"); pg.wait_for_timeout(200)
    got = (pg.eval_on_selector_all(".xt-pop", "l => l.length"), state(pg))
    check("a tap on a row's time opens its explanation, not the panel", got[0] == 1 and not got[1]["open"], got)
    pg.keyboard.press("Escape"); pg.mouse.move(5, 5)
    order = pg.eval_on_selector_all("li.irow.hrow a.ir-link", "l => l.filter(a => a.getClientRects().length).map(a => a.getAttribute('href'))")
    shot(pg, "desktop-home")
    top = "(s) => document.querySelector(s).getBoundingClientRect().top"
    pg.evaluate("(s) => document.querySelector(s).scrollIntoView({block: 'start'})", row(3)); y, at3 = pg.evaluate("() => window.scrollY"), pg.evaluate(top, row(3))
    open_(pg, 3); s = state(pg)
    check("a title opens the panel, the address names the item, the row is marked", s["open"] and s["url"] == "/?item=a3" and s["current"] == ["/items/a3"] and s["inside"], s)
    box = pg.eval_on_selector("#brief", "e => { const r = e.getBoundingClientRect(); return {x: r.x, w: r.width, h: r.height} }")
    pad = pg.eval_on_selector("#layout", "e => parseFloat(getComputedStyle(e).paddingRight)")
    # where a fixed element's right edge sits: the window less the gutter the stylesheet keeps for the scrollbar (clientWidth does not tell: it counts the gutter where scrollbars are hidden)
    edge = pg.evaluate("() => { const p = document.body.appendChild(document.createElement('div')); p.style.cssText = 'position:fixed;top:0;right:0;width:0;height:0'; const x = p.getBoundingClientRect().x; p.remove(); return x }")
    check("the panel stands on the right and the lists make room for it", abs(box["x"] + box["w"] - edge) < 1 and box["w"] == 560 and box["h"] == 800 and pad >= 559, (box, pad, edge))
    check("nothing scrolls sideways", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
    send = pg.eval_on_selector("#brief button[name=act]", "e => e.getBoundingClientRect().bottom")
    check("Send is in view with nothing picked, and is off", send <= 800 and s["send"] is False, (send, s))
    check("the inline hint is not drawn", pg.eval_on_selector("#brief .ahint", "e => getComputedStyle(e).display") == "none")
    shot(pg, "desktop-panel")
    check("the lists stay in use: the page is not inert", pg.evaluate("() => !document.querySelector('#layout').inert && document.getElementById('brief-scrim').hidden"))
    seen = pg.inner_text("#brief")
    check("the panel shows the question, the recommendation, the choices and the item's link, and no heading, background or stakes",
          all(w in seen for w in ("whether to ship the next version", "Recommend", "sample question a3", "Ship it now as it is"))
          and not any(w in seen for w in ("background fact", "another week", "Your answer", "Detail view", "Alpha", "Picked"))
          and pg.eval_on_selector_all("#brief h3, #brief .iask > b", "l => l.length") == 0, seen)
    links = pg.eval_on_selector_all("#brief a[href]", "l => l.filter(a => a.getClientRects().length).map(a => a.getAttribute('href'))")
    check("…with one link to the item's page", links.count("/items/a3") == 1, links)
    said = pg.evaluate("() => { const p = document.getElementById('brief'); return [p.innerText, ...[...p.querySelectorAll('[aria-label],[title],[placeholder]')].flatMap(e => ['aria-label', 'title', 'placeholder'].map(a => e.getAttribute(a) || ''))] }")
    check("…and nowhere the panel's inner name", not any("brief" in w.lower() for w in said), said)

    # the "?" beside the question holds the rest
    check("what bears on the question is put away until asked for", visible(pg, "#xp-brief-more-a3") == "hidden")
    pg.click("#xpb-brief-more-a3")
    more = pg.inner_text("#xp-brief-more-a3"); tip = pg.eval_on_selector("#xp-brief-more-a3", "e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] }")
    check("…its ? shows the stakes and the first lines of the background, a line each", "another week" in more and "number 5" in more and "number 6" not in more and "…" in more and more.count("\n") >= 5, more)
    check("…inside the panel and the window", tip[0] >= box["x"] and tip[1] <= 1280 and tip[2] >= 0 and tip[3] <= 800, tip)
    shot(pg, "desktop-more")
    pg.keyboard.press("Escape"); check("…and Escape puts it away, the panel stays", visible(pg, "#xp-brief-more-a3") == "hidden" and state(pg)["open"])

    # the "?" beside Send
    check("the explanation is put away until asked for", visible(pg, "#xp-brief-pick-a3") == "hidden")
    pg.hover("#xpb-brief-pick-a3"); check("…it shows on hover", visible(pg, "#xp-brief-pick-a3") == "visible")
    tip = pg.eval_on_selector("#xp-brief-pick-a3", "e => { const r = e.getBoundingClientRect(); return [r.left, r.right] }")
    check("…inside the panel", tip[0] >= box["x"] and tip[1] <= 1280, tip)
    shot(pg, "desktop-tooltip")
    pg.keyboard.press("Escape"); check("Escape puts it away and the panel stays", visible(pg, "#xp-brief-pick-a3") == "hidden" and state(pg)["open"])
    pg.mouse.move(5, 5); pg.focus("#brief textarea")
    for _ in range(4):
        pg.keyboard.press("Tab")
        if pg.evaluate("() => document.activeElement.classList.contains('xp-b')"): break
    check("…it shows on keyboard focus", pg.evaluate("() => document.activeElement.classList.contains('xp-b')") and visible(pg, "#xp-brief-pick-a3") == "visible")
    away(pg); check("…and goes when the focus leaves", visible(pg, "#xp-brief-pick-a3") == "hidden")

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
    check("with a pick, Send is on", "Drop" in s["pick"] and s["send"], s)
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
    foot = pg.inner_text("#brief .bfoot")
    check("the latest keeps the note, drops the pick made on the old question and names it", s["note"] == "half written" and s["pick"] == "" and answers(5) == []
          and "The question changed since you picked" in foot and "Wait" in foot, (s, foot))
    open_(pg, 6); rewrite(6, ask=ASK.replace("next version", "second version")); poll(pg, "() => document.querySelector('#brief').innerText.includes('second version')")
    pg.wait_for_function("() => document.querySelector('#brief').innerText.includes('second version')", timeout=10000)
    check("with nothing written the open item is simply drawn anew", pg.query_selector("#brief .bchanged") is None and pg.evaluate("() => window.sameDocument === true"))

    # a draft on an item whose row has no box, while the whole page wants a reload
    home(pg, clean=True); open_(pg, 10); pg.fill("#brief textarea", "a comment under way"); away(pg)
    pg.evaluate("() => { window.sameDocument = true; document.querySelector('meta[name=\"stackshot-shell\"]').content = 'another-frame' }")
    rewrite(11, next="something else now"); poll(pg); pg.wait_for_timeout(2500)
    check("the live refresh does not reload the page over a draft in the panel", pg.evaluate("() => window.sameDocument === true") and state(pg)["note"] == "a comment under way", state(pg))
    pg.fill("#brief textarea", ""); away(pg); rewrite(11, next="and again"); poll(pg, "() => window.sameDocument === undefined")
    pg.wait_for_function("() => window.sameDocument === undefined", timeout=10000)
    check("…and with nothing written it reloads as before, the panel open again", True)
    loaded(pg, 10)

    # sends that write nothing
    home(pg); open_(pg, 4); pg.fill("#brief textarea", "kept when the send fails")
    pg.route("**/items/a4/answer", lambda r: r.abort()); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief .aerr:not([hidden])"); s = state(pg)
    check("a send that gets no reply says it is not known whether it was recorded, and keeps the note", "may or may not have been recorded" in pg.inner_text("#brief .aerr") and s["note"] == "kept when the send fails" and s["send"] and answers(4) == [], (s, pg.inner_text("#brief .aerr")))
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
    pg.evaluate("() => sessionStorage.clear()")
    pg.goto(BOARD + "/?item=a12"); loaded(pg, 12); pg.keyboard.press("Escape"); closed(pg)
    check("an address that names an item opens it, and closing stays on the list", state(pg)["url"] == "/", state(pg))
    pg.goto(BOARD + "/?sent=decision&item=a12"); pg.wait_for_timeout(1500)
    check("the address of a row's own send is not the panel's", not state(pg)["open"], state(pg))
    pg.goto(BOARD + "/?item=../x"); pg.wait_for_timeout(800); check("an address that names no item form opens nothing", not state(pg)["open"], state(pg))

    # a new tab
    home(pg)
    with ctx.expect_page() as new:
        pg.click(f"{row(12)} a.ir-link", modifiers=["Control"])
    other = new.value; other.wait_for_url(BOARD + "/items/a12", timeout=10000)      # a new tab is about:blank before its first navigation
    check("Ctrl+click opens the item's page in a new tab and no panel", other.url == BOARD + "/items/a12" and not state(pg)["open"], other.url); other.close()
    ctx.close()


def fullpage(br, errors):
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}); ctx.add_cookies([cookie()]); ctx.set_default_timeout(10000)
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    item(40); git("add", "-A"); git("commit", "-q", "-m", "a40"); board_home._board_home_drop()
    home(pg); open_(pg, 40); pg.fill("#brief textarea", "carried to the full page"); pg.click("#brief .acard:has-text('Ship')")
    pg.click("#brief [data-bact=full]"); pg.wait_for_url(BOARD + "/items/a40/brief"); pg.wait_for_selector("#brief-page article")
    pg.wait_for_function("() => document.querySelector('#brief-page textarea').value !== ''", timeout=5000)
    got = pg.evaluate("() => ({t: document.querySelector('#brief-page textarea').value, c: (document.querySelector('#brief-page input[name=choice]:checked') || {}).value})")
    check("full screen keeps the draft", got["t"] == "carried to the full page" and "Ship" in (got["c"] or ""), got)
    links = pg.eval_on_selector_all("main.briefpage #brief-page a[href]", "l => l.map(a => a.getAttribute('href'))")
    seen = pg.inner_text("main.briefpage #brief-page")
    check("the full page is as lean: one link to the item's page, no background, no heading", links.count("/items/a40") == 1 and "background fact" not in seen and "Detail view" not in pg.inner_text("body")
          and pg.query_selector("#brief-page h3") is None, (links, seen))
    check("the full page fits", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
    shot(pg, "desktop-full")
    pg.evaluate("() => { window.sameDocument = true }")
    pg.click("#brief-page button[name=act]"); pg.wait_for_selector("#brief-page .bsent .isent.ok")
    check("a send on the full page records one answer and says so there, in the same page", len(answers(40)) == 1 and answers(40)[0].get("text") == "carried to the full page"
          and pg.url == BOARD + "/items/a40/brief" and pg.evaluate("() => window.sameDocument === true"), (answers(40), pg.url))
    item(42, **LONG_ITEM); git("add", "-A"); git("commit", "-q", "-m", "a42"); board_home._board_home_drop()
    pg.goto(BOARD + "/items/a42/brief"); pg.wait_for_selector("#brief-page article")
    check("long unbroken text does not widen the full page", pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")); ctx.close()
    dark = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}, color_scheme="dark"); dark.add_cookies([cookie()])
    pg = dark.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    item(41); git("add", "-A"); git("commit", "-q", "-m", "a41"); board_home._board_home_drop()
    home(pg); open_(pg, 41); shot(pg, "desktop-panel-dark"); dark.close()


def phone(br, errors, scheme, w=390, h=844):
    n = 50 if scheme == "light" else 51
    if w != 390: n += 2
    tag = scheme if w == 390 else f"{scheme}-{w}"
    item(n); item(n + 5, ask=None, opts=None, state="your-step", step="run the one line `true`", needs=["home-here"])
    git("add", "-A"); git("commit", "-q", "-m", f"a{n}"); board_home._board_home_drop()
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": w, "height": h}, is_mobile=True, has_touch=True, device_scale_factor=2, color_scheme=scheme); ctx.add_cookies([cookie()]); ctx.set_default_timeout(10000)
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    home(pg); shot(pg, f"phone-home-{tag}")
    # a row's button lies over none of the row's own words
    over = pg.evaluate("""() => [...document.querySelectorAll('li.irow.hrow')].filter(li => li.getClientRects().length).flatMap(li => {
        const b = li.querySelector('.bopen'); if (!b) return ['a row with no button'];
        const r = b.getBoundingClientRect(), box = li.getBoundingClientRect(), out = r.left < box.left - 1 || r.right > box.right + 1 ? ['outside its row'] : [];
        const walk = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
        for (let t = walk.nextNode(); t; t = walk.nextNode()) { if (b.contains(t) || !t.textContent.trim() || !t.parentElement.checkVisibility()) continue;
            const g = document.createRange(); g.selectNodeContents(t);
            for (const q of g.getClientRects()) if (q.left < r.right - 1 && r.left < q.right - 1 && q.top < r.bottom - 1 && r.top < q.bottom - 1) { out.push('over: ' + t.textContent.trim().slice(0, 60)); break } }
        return out })""")
    check(f"{tag}: the rows' buttons lie over no words, and nothing scrolls sideways", over == [] and pg.evaluate("() => document.documentElement.scrollWidth") <= w, (over[:6], pg.evaluate("() => document.documentElement.scrollWidth")))
    reach = pg.eval_on_selector(f"{row(20)} .bopen", "b => { b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(), x = r.x + r.width / 2; return [r.height, [-20, 0, 20].every(d => document.elementFromPoint(x, r.y + r.height / 2 + d) === b)] }")
    check(f"{tag}: the row's button is small to look at and a full target for a finger", reach[0] < 32 and reach[1], reach)
    pg.evaluate("(s) => document.querySelector(s).scrollIntoView({block: 'center'})", row(20)); y = pg.evaluate("() => window.scrollY")
    pg.tap(f"{row(20)} .bopen"); loaded(pg, 20); pg.keyboard.press("Escape"); closed(pg)
    check(f"{tag}: the list is where it was after the sheet", y > 0 and abs(pg.evaluate("() => window.scrollY") - y) < 2, (y, pg.evaluate("() => window.scrollY")))
    pg.tap(f"{row(n)} a.ir-link"); loaded(pg, n)
    box = pg.eval_on_selector("#brief", "e => { const r = e.getBoundingClientRect(); return {x: r.x, w: r.width, h: r.height, b: r.bottom} }")
    check(f"{tag}: a bottom sheet, the full width and most of the height", box["x"] == 0 and box["w"] == w and abs(box["h"] - 0.92 * h) < 2 and abs(box["b"] - h) < 1, box)
    fit = pg.evaluate("() => { const b = document.querySelector('#brief .bbody'); return [document.documentElement.scrollWidth, b.scrollWidth, b.clientWidth] }")
    check(f"{tag}: nothing scrolls sideways", fit[0] <= w and fit[1] <= fit[2], fit)
    check(f"{tag}: the page behind is dimmed, still and out of reach", pg.evaluate("() => !document.getElementById('brief-scrim').hidden && document.documentElement.classList.contains('sheet') && document.getElementById('layout').inert && document.getElementById('brief').getAttribute('aria-modal') === 'true'"))
    send = pg.eval_on_selector("#brief button[name=act]", "e => e.getBoundingClientRect().bottom")
    small = pg.eval_on_selector_all("#brief .brief-bar .b, #brief .xp-b, #brief .btitle a", "l => l.filter(e => e.getClientRects().length).map(e => [e.textContent, e.getBoundingClientRect().height]).filter(x => x[1] < 43.9)")
    check(f"{tag}: Send is in view, the bar's buttons, each ? and the item's link are large enough to tap", send <= h and small == [], (send, small))
    off = pg.evaluate("""() => [...document.querySelectorAll('#brief .brief-bar .b, #brief button[name=act]')].filter(e => e.getClientRects().length)
        .map(e => { const r = e.getBoundingClientRect(); return [e.textContent, r.left, r.right, r.top, r.bottom] }).filter(x => x[1] < -0.5 || x[2] > innerWidth + 0.5 || x[3] < -0.5 || x[4] > innerHeight + 0.5)""")
    check(f"{tag}: the bar's buttons and Send are wholly on the screen", off == [], off)
    shot(pg, f"phone-sheet-{tag}")
    q = pg.evaluate("""() => { const p = document.querySelector('#brief .bq'), t = p.querySelector(':scope > span').getBoundingClientRect(), b = p.querySelector('.xp-b').getBoundingClientRect(),
        line = parseFloat(getComputedStyle(p).lineHeight); return {gap: b.left - t.right, off: Math.abs(b.top + b.height / 2 - t.top - line / 2), lines: t.height / line} }""")
    check(f"{tag}: the question's lines stay close, and its ? stands beside the first of them", q["gap"] >= -0.5 and q["off"] < 4 and abs(q["lines"] - round(q["lines"])) < 0.05, q)
    side = pg.evaluate("() => ['#brief textarea', '#brief button[name=act]'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] })")
    (_, tr, tt, tb), (bl, br_, bt, bb) = side
    check(f"{tag}: Send stands beside the note box, on its line", tr <= bl and br_ <= w and abs((tt + tb) / 2 - (bt + bb) / 2) < 6, side)
    low = pg.eval_on_selector("#brief textarea", "e => e.getBoundingClientRect().height")
    pg.tap("#brief textarea"); pg.wait_for_timeout(300)
    tall = pg.eval_on_selector("#brief textarea", "e => [e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).fontSize)]")
    check(f"{tag}: the note box is one line until used, with text large enough not to zoom", low < 50 and tall[0] >= 80 and tall[1] >= 16, (low, tall))
    pg.fill("#brief textarea", "\n".join(["a line of the note"] * 8)); grown = pg.eval_on_selector("#brief textarea", "e => e.getBoundingClientRect().height")
    check(f"{tag}: …and grows with its text", grown > tall[0] + 20, (tall, grown)); pg.fill("#brief textarea", "")
    for what, name, words in (("the question's", "more", "another week"), ("Send's", "pick", "write a note")):
        tid, button = f"#xp-brief-{name}-a{n}", f"#xpb-brief-{name}-a{n}"
        pg.tap(button); pg.wait_for_selector(tid, timeout=5000)
        tip = pg.eval_on_selector(tid, "e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] }")
        check(f"{tag}: a tap on {what} ? shows the words, on the screen", words in pg.inner_text(tid) and tip[0] >= 0 and tip[1] <= w and tip[2] >= 0 and tip[3] <= h, (tip, pg.inner_text(tid)))
        shot(pg, f"phone-tooltip-{name}-{tag}")
        pg.tap(button); check(f"{tag}: a second tap puts {what} words away", visible(pg, tid) == "hidden")
    head = pg.eval_on_selector("#brief .bhead", "e => { const r = e.getBoundingClientRect(); return [r.right - 6, r.y + r.height / 2] }")
    pg.mouse.move(*head); pg.mouse.down(); pg.mouse.move(head[0], head[1] + 40, steps=4); pg.mouse.up()
    check(f"{tag}: a short drag leaves it open", state(pg)["open"])
    pg.mouse.move(*head); pg.mouse.down(); pg.mouse.move(head[0], head[1] + 180, steps=8); pg.mouse.up(); closed(pg)
    check(f"{tag}: a drag down closes it", pg.evaluate("() => !document.documentElement.classList.contains('sheet') && !document.getElementById('layout').inert"))
    pg.tap(f"{row(n)} .bopen"); loaded(pg, n); pg.touchscreen.tap(w / 2, 20); closed(pg)
    check(f"{tag}: a tap on the dimmed page closes it", state(pg)["url"] == "/", state(pg))
    pg.tap(f"{row(n)} .bopen"); loaded(pg, n); pg.go_back(); closed(pg)
    check(f"{tag}: Back closes it", state(pg)["url"] == "/", state(pg))
    pg.goto(BOARD + f"/?item=a{n + 5}"); loaded(pg, n + 5); shot(pg, f"phone-step-{tag}")
    tid = f"#xp-brief-more-a{n + 5}"
    pg.tap(f"#xpb-brief-more-a{n + 5}"); pg.wait_for_selector(tid, timeout=5000)
    tip = pg.eval_on_selector(tid, "e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom] }")
    seen = pg.inner_text("#brief .istep .istepbody")
    check(f"{tag}: a step is shown with no heading, its ? beside it opens on the screen",
          "the next step" in seen and "background fact" in pg.inner_text(tid) and pg.query_selector("#brief .istep > b") is None and tip[0] >= 0 and tip[1] <= w and tip[2] >= 0 and tip[3] <= h, (seen, tip))
    shot(pg, f"phone-step-more-{tag}")
    pg.goto(BOARD + "/?item=a42"); loaded(pg, 42)
    fit = pg.evaluate("() => { const b = document.querySelector('#brief .bbody'); return [document.documentElement.scrollWidth, b.scrollWidth, b.clientWidth] }")
    check(f"{tag}: long unbroken text stays inside the sheet", fit[0] <= w and fit[1] <= fit[2], fit)
    shot(pg, f"phone-long-{tag}")
    pg.goto(BOARD + "/items/a42/brief"); pg.wait_for_selector("#brief-page article")
    check(f"{tag}: long unbroken text does not widen the full page", pg.evaluate("() => document.documentElement.scrollWidth") <= w, pg.evaluate("() => document.documentElement.scrollWidth"))
    pg.goto(BOARD + f"/items/a{n}/brief"); pg.wait_for_selector("#brief-page article"); shot(pg, f"phone-full-{tag}"); ctx.close()


def noscript(br):
    ctx = br.new_context(ignore_https_errors=True, java_script_enabled=False); ctx.add_cookies([cookie()])
    pg = ctx.new_page(); pg.goto(BOARD + "/"); pg.wait_for_selector("li.irow.hrow a.ir-link")
    check("without the script there is no panel button and no panel", pg.query_selector(".bopen") is None and not pg.is_visible("#brief"))
    pg.click("#agents-at-work > details > summary")
    with ctx.expect_page() as new:
        pg.click(f"{row(12)} a.ir-link")
    other = new.value; other.wait_for_url(BOARD + "/items/a12", timeout=10000)
    check("…a row's title opens the item's page", other.url == BOARD + "/items/a12", other.url); ctx.close()


# ---- what a person must not lose: each of these runs in a browser of its own, on items of its own, and again with one line of the script taken out (MUTANTS), where it must fail
NEXT = [100]


def fresh(**kw):
    """an item nobody has touched, for one scenario"""
    NEXT[0] += 1; n = NEXT[0]
    item(n, **kw); git("add", "-A"); git("commit", "-q", "-m", f"a{n}"); board_home._board_home_drop()
    return n


def soon(pg, js, arg=None):
    """True once the JavaScript test holds, False when it never does"""
    try:
        pg.wait_for_function(js, arg=arg); return True
    except Exception:  # noqa: BLE001  — the check that follows says what is missing
        return False


def tokened(pg, n):
    """the row's own box is drawn once its token has come"""
    pg.wait_for_function("(s) => { const i = document.querySelector(s + ' form.hanswer input[name=token]'); return !!i && !!i.value }", arg=row(n))


def rowtype(pg, n, text):
    pg.evaluate("([s, v]) => { const t = document.querySelector(s + ' form.hanswer textarea'); t.value = v; t.dispatchEvent(new Event('input', {bubbles: true})) }", [row(n), text])


def rowshut(pg, n):
    return pg.evaluate("(s) => { const f = document.querySelector(s + ' form.hanswer'); return [f.querySelector('button[name=act]').disabled, f.getAttribute('aria-busy')] }", row(n))


def panelsend(pg):
    return pg.evaluate("() => { const b = document.querySelector('#brief button[name=act]'); return b ? [b.disabled, b.textContent] : null }")


def shut_panel(pg):
    """close it, and wait for the history to have gone back before anything else is opened"""
    pg.click("#brief [data-bact=close]"); closed(pg); pg.wait_for_function("() => location.search === ''")


def posts_of(pg):
    sent = []
    pg.on("request", lambda q: sent.append(q.url) if q.method == "POST" and q.url.endswith("/answer") else None)
    return lambda n: len([u for u in sent if u.endswith(f"/items/a{n}/answer")])


ARMED = "() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented }"      # would leaving be asked about
ROW_SEND = "(s) => { const f = document.querySelector(s + ' form.hanswer'); f.querySelector('input[name=choice]').click(); f.requestSubmit(f.querySelector('button[name=act]')) }"
STORED = "() => sessionStorage.getItem('ss-brief-drafts') || ''"


def sc_double(pg, say):
    a, b, c = fresh(), fresh(), fresh()
    count = posts_of(pg); home(pg); tokened(pg, a); held = []
    pg.route(f"**/items/a{a}/answer", lambda r: held.append(r))
    open_(pg, a); pg.click("#brief .acard:has-text('Drop')"); pg.click("#brief button[name=act]")
    soon(pg, "() => document.querySelector('#brief button[name=act]').disabled")
    shut = rowshut(pg, a)
    say("a send under way from the panel shuts the row's Send", shut == [True, "true"], shut)
    say("…and leaving the page is asked about while it is", pg.evaluate(ARMED))
    shut_panel(pg); open_(pg, a); got = panelsend(pg)
    say("…the item opened again has its Send shut and says it is sending", bool(got) and got[0] and "Sending" in got[1], got)
    pg.evaluate("""(s) => { const r = document.querySelector(s + ' form.hanswer'), p = document.querySelector('#brief form.ianswer'); r.requestSubmit(); if (p) p.requestSubmit();
        for (const f of [r, p]) { const t = f && f.querySelector('textarea'); if (t) t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true})) } }""", row(a))
    pg.wait_for_timeout(500)
    say("…and no way of sending it again makes a second request", count(a) == 1 and len(held) == 1, (count(a), len(held)))
    held[0].continue_(); soon(pg, "() => !!document.querySelector('#brief .bsent .bnext')")
    say("one answer is recorded", len(answers(a)) == 1, answers(a))
    say("…and then leaving is not asked about", not pg.evaluate(ARMED))
    # the other way round: the row's own Send first (its request held here, so it stays under way), then the panel
    shut_panel(pg); tokened(pg, b)
    rowheld = []
    pg.route(f"**/items/a{b}/answer", lambda r: rowheld.append(r))
    pg.evaluate(ROW_SEND, row(b)); soon(pg, "(s) => !!document.querySelector(s + ' form.hanswer[aria-busy]')", row(b))
    pg.focus(f"{row(b)} a.ir-link"); pg.keyboard.press("Enter"); loaded(pg, b); got = panelsend(pg)      # by key: a row sending is dimmed and takes no pointer (data-sending), so a click would land on the list
    say("a send under way from a row shuts the panel's Send", bool(got) and got[0] and "Sending" in got[1], got)
    pg.evaluate("() => document.querySelector('#brief form.ianswer').requestSubmit()"); pg.wait_for_timeout(500)
    say("…and the panel sends nothing", count(b) == 1 and len(rowheld) == 1, (count(b), len(rowheld)))
    rowheld[0].abort()
    # a row's own send, to its end: the page it comes back as ends that draft
    home(pg); tokened(pg, c)
    with pg.expect_navigation():
        pg.evaluate(ROW_SEND, row(c))
    pg.wait_for_selector("p.isent"); kept = pg.evaluate(STORED)
    say("a row's own send records once and leaves no draft of it", len(answers(c)) == 1 and f'"a{c}"' not in kept, (answers(c), kept))


def sc_apart(pg, say):
    a, b = fresh(), fresh()
    home(pg); held = []
    pg.route(f"**/items/a{a}/answer", lambda r: held.append(r))
    open_(pg, a); pg.click("#brief .acard:has-text('Drop')"); pg.click("#brief button[name=act]"); soon(pg, "() => document.querySelector('#brief button[name=act]').disabled")
    open_(pg, b); pg.click("#brief .acard:has-text('Ship')"); got = panelsend(pg)
    say("a send under way on one item leaves another's Send on", bool(got) and not got[0], got)
    pg.click("#brief button[name=act]"); soon(pg, "() => !!document.querySelector('#brief .bsent .bnext')")
    say("…which records its own answer", len(answers(b)) == 1 and answers(a) == [], (answers(a), answers(b)))
    held[0].fulfill(status=403, content_type="text/plain", body="refused for this check")
    soon(pg, "() => !document.getElementById('brief-toast').hidden")
    told = pg.inner_text("#brief-toast")
    say("the send that failed is told, with its item, though another is open", "refused for this check" in told and f"a{a}" in told and state(pg)["url"] == f"/?item=a{b}", (told, state(pg)))
    pg.wait_for_timeout(4600)
    say("…and the line stays until it is acted on", pg.is_visible("#brief-toast"))
    pg.click("#brief-toast button.main"); loaded(pg, a); s = state(pg)
    why = pg.inner_text("#brief .aerr")
    say("…its button opens the item, which says why and keeps the pick", "refused for this check" in why and "Drop" in s["pick"] and s["send"], (why, s))


def sc_timeout(pg, say):
    n = fresh(); pg.clock.install(); home(pg); held = []
    pg.route(f"**/items/a{n}/answer", lambda r: held.append(r))
    open_(pg, n); pg.fill("#brief textarea", "kept when no reply comes"); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief button[name=act]:disabled")
    pg.clock.fast_forward(31000); pg.wait_for_selector("#brief .aerr:not([hidden])"); s = state(pg); why = pg.inner_text("#brief .aerr")
    say("a send with no reply ends after its time, says it is not known whether it was recorded, and keeps the note",
        "may or may not have been recorded" in why and s["note"] == "kept when no reply comes" and s["send"] and answers(n) == [], (why, s))


def sc_failed_load(pg, say):
    n = fresh(); home(pg); tokened(pg, n); rowtype(pg, n, "typed before the read failed")
    pg.evaluate("() => { window.sameDocument = true }")
    broken = re.compile(rf"/items/a{n}/brief$")
    pg.route(broken, lambda r: r.fulfill(status=500, body="broken")); pg.click(f"{row(n)} a.ir-link")
    soon(pg, "() => !!document.querySelector('#brief .bfail')"); pg.wait_for_timeout(500)
    got = pg.evaluate("""() => ({same: window.sameDocument === true, url: location.pathname + location.search, text: (document.querySelector('#brief .bfail') || {}).innerText || '',
        link: (document.querySelector('#brief .bfail a') || {getAttribute: () => ''}).getAttribute('href')})""")
    say("a brief that cannot be read stays on the list and says so", got["same"] and got["url"] == f"/?item=a{n}" and "This item could not be read." in got["text"], got)
    say("…with a way to try again and a link to the item's page", "Try again" in got["text"] and got["link"] == f"/items/a{n}", got)
    say("…and the row keeps what was typed", rowstate(pg, n)["note"] == "typed before the read failed", rowstate(pg, n))
    shot(pg, "desktop-failed")
    pg.unroute(broken); pg.click("#brief .bretry"); loaded(pg, n)
    say("…Try again reads it, the draft in its box", state(pg)["note"] == "typed before the read failed", state(pg))
    # recorded, and then the item cannot be read again
    m = fresh(); home(pg); open_(pg, m); pg.evaluate("() => { window.sameDocument = true }")
    again = re.compile(rf"/items/a{m}/brief(\?.*)?$")      # every read of it from here on: the read after the send, and any the live refresh asks for
    pg.route(again, lambda r: r.fulfill(status=500, body="broken"))
    pg.route("**/render-stamp", lambda r: r.fulfill(status=500, body="held back"))      # the lists stay as they are, so the row below is the one that was marked
    pg.click("#brief .acard:has-text('Ship')"); pg.click("#brief button[name=act]")
    soon(pg, "() => !!document.querySelector('#brief .bretry')")
    text = pg.inner_text("#brief"); r = rowstate(pg, m)
    say("a send recorded on an item that then cannot be read says it was sent, in the same page",
        "Sent. The item could not be read again." in text and pg.evaluate("() => window.sameDocument === true") and state(pg)["url"] == f"/?item=a{m}" and len(answers(m)) == 1, (text, answers(m)))
    say("…leaves no box to send it twice, and marks the row", pg.query_selector("#brief textarea") is None and r["sent"], r)
    pg.unroute(again); pg.click("#brief .bretry"); soon(pg, "() => !document.querySelector('#brief .bretry')")
    soon(pg, "() => document.querySelector('#brief').innerText.includes('Sent')")
    say("…and reads it on asking, still saying it was sent", pg.query_selector("#brief .bretry") is None and pg.query_selector("#brief article.bitem .bsent .isent.ok") is not None, pg.inner_text("#brief"))


def sc_drafts(pg, say):
    n = fresh(); home(pg); open_(pg, n); pg.click("#brief .acard:has-text('Drop')"); pg.fill("#brief textarea", "kept across the pages"); away(pg)
    kept = lambda s: s["note"] == "kept across the pages" and "Drop" in s["pick"]
    onpage = "() => { const t = document.querySelector('#brief-page textarea'), c = document.querySelector('#brief-page input[name=choice]:checked'); return [t ? t.value : '', c ? c.value : ''] }"
    pg.reload(); loaded(pg, n); s = state(pg)
    say("a reload brings the draft back to the panel", kept(s), s)
    tokened(pg, n); r = rowstate(pg, n)
    say("…and to the row", r["note"] == "kept across the pages" and "Drop" in r["pick"], r)
    say("…and with the draft kept, leaving is not asked about", not pg.evaluate(ARMED))
    pg.click("#brief .btitle a"); pg.wait_for_url(BOARD + f"/items/a{n}"); pg.go_back(); loaded(pg, n); s = state(pg)
    say("the item's link and Back keep it", kept(s), s)
    pg.click("#brief [data-bact=full]"); pg.wait_for_url(BOARD + f"/items/a{n}/brief"); pg.wait_for_selector("#brief-page article"); got = pg.evaluate(onpage)
    say("Full screen shows it", got[0] == "kept across the pages" and "Drop" in got[1], got)
    pg.fill("#brief-page textarea", "kept across the pages, and changed there"); pg.reload(); pg.wait_for_selector("#brief-page article"); got = pg.evaluate(onpage)
    say("…keeps it over a reload", got[0] == "kept across the pages, and changed there" and "Drop" in got[1], got)
    pg.go_back(); loaded(pg, n); soon(pg, "() => document.querySelector('#brief textarea').value.endsWith('changed there')"); s = state(pg)
    say("…and Back to the panel shows what was written there", s["note"] == "kept across the pages, and changed there" and "Drop" in s["pick"], s)


def sc_no_storage(pg, say):
    pg.add_init_script("""(() => { const real = Storage.prototype.setItem; Storage.prototype.setItem = function (k, v) {
        if (String(k).startsWith('ss-brief-')) throw new DOMException('full', 'QuotaExceededError'); return real.call(this, k, v) } })()""")
    n = fresh(); home(pg); open_(pg, n)
    say("where the browser keeps nothing: with nothing written, leaving is not asked about", not pg.evaluate(ARMED))
    pg.fill("#brief textarea", "only in this page")
    say("…and with a draft it is", pg.evaluate(ARMED))
    pg.fill("#brief textarea", "")
    say("…until the draft is gone", not pg.evaluate(ARMED))


def sc_lost_pick(pg, say):
    n = fresh(); home(pg); open_(pg, n); pg.click("#brief .acard:has-text('Drop')"); pg.fill("#brief textarea", "a note on the first question")
    shut_panel(pg)
    rewrite(n, ask=ASK.replace("next version", "other version")); open_(pg, n)
    soon(pg, "() => { const e = document.querySelector('#brief .aerr'); return !!e && !e.hidden && e.textContent.includes('The question changed since you picked') }")
    s = state(pg); foot = pg.inner_text("#brief .bfoot")
    say("a pick dropped because the question changed is named under Send",
        "The question changed since you picked" in foot and "Drop" in foot and s["pick"] == "" and s["note"] == "a note on the first question", (foot, s))
    told = pg.evaluate("(s) => (document.querySelector(s + ' .bnote') || {}).textContent || ''", row(n))
    say("…and on the row", "Drop" in told, told)
    shot(pg, "desktop-lost-pick")
    pg.click("#brief .acard:has-text('Wait')"); soon(pg, "() => document.querySelector('#brief .aerr').hidden")
    say("…and a new pick puts the line away", pg.eval_on_selector("#brief .aerr", "e => e.hidden") and pg.query_selector(f"{row(n)} .bnote") is None)


def sc_held(pg, say):
    n = fresh(ask=None, opts=None, state="your-step", step="run the one line `true`", needs=["home-here"])
    home(pg); open_(pg, n); pg.fill("#brief textarea", "a note on the old step")
    rewrite(n, state="", step="", needs=["decision"], ask=ASK, options=OPTS)
    pg.click("#brief button[value=done]")
    soon(pg, "() => !!document.querySelector('#brief .bheld')")
    held = pg.evaluate("() => { const h = document.querySelector('#brief .bheld'); return h ? [h.querySelector('code').textContent, [...h.querySelectorAll('button')].map(b => b.textContent)] : null }")
    say("Done with a note on a step that is gone records nothing; the note that fits no box is held, offered with Copy and Put it in the box",
        bool(held) and held[0] == "a note on the old step" and "Put it in the box" in held[1] and "Discard" in held[1] and len(held[1]) >= 3 and answers(n) == [], (held, answers(n)))
    say("…and is not put in the decision's box by itself", state(pg)["note"] == "", state(pg))
    shot(pg, "desktop-held")
    pg.reload(); loaded(pg, n)
    say("…a reload keeps it held", pg.query_selector("#brief .bheld code") is not None and pg.inner_text("#brief .bheld code") == "a note on the old step")
    pg.click("#brief .bheld .buse"); soon(pg, "() => !document.querySelector('#brief .bheld')"); s = state(pg)
    say("…Put it in the box does so", s["note"] == "a note on the old step" and pg.query_selector("#brief .bheld") is None, s)
    # a comment that was being written when the item became a question
    m = fresh(ask=None, opts=None); home(pg); open_(pg, m); pg.fill("#brief textarea", "only a comment"); away(pg)
    rewrite(m, needs=["decision"], ask=ASK, options=OPTS); pg.evaluate("() => document.dispatchEvent(new CustomEvent('stackshot:newer', {detail: 424242}))")
    soon(pg, "() => !!document.querySelector('#brief .bchanged')"); pg.click("#brief .bchanged button"); soon(pg, "() => !!document.querySelector('#brief .bheld')")
    s = state(pg)
    say("a comment under way does not move into a decision's box", s["note"] == "" and pg.query_selector("#brief .bheld code") is not None and pg.inner_text("#brief .bheld code") == "only a comment", s)
    pg.click("#brief .bheld .bdrop")
    say("…and Discard drops it", soon(pg, "() => !document.querySelector('#brief .bheld')") and "only a comment" not in pg.evaluate(STORED), pg.evaluate(STORED))


def sc_older_read(pg, say):
    n = fresh(); home(pg); open_(pg, n); late = []
    plain = re.compile(rf"/items/a{n}/brief$")
    pg.route(plain, lambda r: late.append((r, r.fetch())))
    pg.evaluate("() => document.dispatchEvent(new CustomEvent('stackshot:newer', {detail: 987654}))")
    for _ in range(40):
        if late: break
        pg.wait_for_timeout(100)
    pg.click("#brief .acard:has-text('Drop')"); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief .bsent .bnext")
    late[0][0].fulfill(response=late[0][1]); pg.wait_for_timeout(700)
    say("an older read that lands late does not put the item back", pg.query_selector("#brief .bsent .isent.ok") is not None and pg.query_selector("#brief form.ianswer[data-cards]") is None, pg.inner_text("#brief"))
    pg.unroute(plain)
    rewrite(n, needs=["decision"], ask=ASK.replace("next version", "later version"), options=OPTS)
    pg.evaluate("() => document.dispatchEvent(new CustomEvent('stackshot:newer', {detail: 987655}))")
    soon(pg, "() => !!document.querySelector('#brief form.ianswer[data-cards]')")
    say("an item that asks again drops the last answer's notice", pg.query_selector("#brief form.ianswer[data-cards]") is not None and pg.query_selector("#brief .bsent") is None, pg.inner_text("#brief"))


def sc_standalone(pg, say):
    pg.add_init_script("Object.defineProperty(Navigator.prototype, 'standalone', {configurable: true, get: () => true})")
    n = fresh(); home(pg); tokened(pg, n); rowtype(pg, n, "typed before the tap")
    link = f"{row(n)} a.ir-link"
    say("this check runs as the installed app, on a link that asks for a new tab", pg.evaluate("() => navigator.standalone === true") and pg.get_attribute(link, "target") == "_blank", pg.get_attribute(link, "target"))
    pg.evaluate("() => { window.sameDocument = true }"); pg.click(link); pg.wait_for_timeout(1500)
    got = pg.evaluate("() => ({same: window.sameDocument === true, url: location.pathname + location.search, open: !!document.querySelector('#brief:not([hidden])')})")
    say("in the installed app a title opens the panel, in the same page", got == {"same": True, "url": f"/?item=a{n}", "open": True}, got)
    loaded(pg, n)
    say("…with what was typed in the row", state(pg)["note"] == "typed before the tap", state(pg))
    pg.click("#brief .btitle a"); pg.wait_for_url(BOARD + f"/items/a{n}"); pg.go_back(); loaded(pg, n)
    say("…and the item's link and Back keep it", state(pg)["note"] == "typed before the tap", state(pg))
    pg.evaluate("() => { const a = document.body.appendChild(document.createElement('a')); a.id = 'other-link'; a.href = '/items/a12'; a.target = '_blank'; a.textContent = 'another'; a.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:99' }")
    pages = len(pg.context.pages); pg.click("#other-link"); pg.wait_for_url(BOARD + "/items/a12")
    say("…and any other such link still opens in the app's own window", len(pg.context.pages) == pages, len(pg.context.pages))


def sc_leftover(pg, say):
    home(pg); open_(pg, 15); pg.fill("#brief textarea", "left on an item with no box on its row")
    say("a draft in the open panel holds the live refresh", pg.evaluate("() => ssBrief.draft()"))
    shut_panel(pg)
    say("…and holds nothing once its box is no longer on the page", not pg.evaluate("() => ssBrief.draft()"))
    open_(pg, 15)
    say("…while the draft itself is kept", state(pg)["note"] == "left on an item with no box on its row", state(pg))


def sc_next_folded(pg, say):
    n, _ = fresh(), fresh(); home(pg); open_(pg, n); pg.click("#brief .acard:has-text('Ship')"); pg.click("#brief button[name=act]"); pg.wait_for_selector("#brief .bsent .bnext")
    pg.evaluate("(s) => document.querySelectorAll('#your-move li.irow.hrow').forEach(li => { if (!li.matches(s)) li.style.display = 'none' })", row(n))
    pg.click("#brief .bnext")
    went = soon(pg, "(k) => { const a = document.querySelector('#brief article'); return !!a && a.getAttribute('data-key') !== k }", f"a{n}")
    say("next goes on to a question in a folded part of the list instead of saying all are answered", went and state(pg)["open"], state(pg))


def sc_redrawn_tip(pg, say):
    n = fresh(); home(pg); open_(pg, n); tid, button = f"#xp-brief-more-a{n}", f"#xpb-brief-more-a{n}"
    pg.click(button)
    rewrite(n, ask=ASK.replace("next version", "newer version"))
    pg.evaluate("() => document.dispatchEvent(new CustomEvent('stackshot:newer', {detail: 313131}))")
    soon(pg, "() => document.querySelector('#brief').innerText.includes('newer version')")
    say("a ? left open stays open when the item is drawn anew", visible(pg, tid) == "visible", pg.inner_text("#brief"))
    pg.click(button); say("…and one click puts it away", visible(pg, tid) == "hidden")
    pg.click(button); pg.evaluate("() => history.back()"); closed(pg); open_(pg, n)
    say("…and one left open when the panel was left is not open when the item is opened again", visible(pg, tid) == "hidden", state(pg))


SCENARIOS = (sc_double, sc_apart, sc_timeout, sc_failed_load, sc_drafts, sc_no_storage, sc_lost_pick, sc_held, sc_older_read, sc_standalone, sc_leftover, sc_next_folded, sc_redrawn_tip)
# (what is taken out, the text as the page serves it, what it becomes, the scenario, the check of it that must then fail)
MUTANTS = (
    ("no form is locked during a send", "function lock(f,v){", "function lock(f,v){return;", sc_double, "…the item opened again has its Send shut and says it is sending"),
    ("the rows are not locked during a send", "all('li.irow.hrow').forEach(function(li){var r=rowForm(li),k=keyOf(li);if(r&&k)l.push([k,r])});", "", sc_double, "a send under way from the panel shuts the row's Send"),
    ("the installed app takes a title link itself", "if(window.ssBrief&&ssBrief.takes(a))return;", "", sc_standalone, "in the installed app a title opens the panel, in the same page"),
    ("a failed read leaves for the item's page", "function failed(me){", "function failed(me){location.assign(page(me.k));return;", sc_failed_load, "a brief that cannot be read stays on the list and says so"),
    ("drafts are not stored", "if(stored)try{if(Object.keys(D).length)", "if(0)try{if(Object.keys(D).length)", sc_drafts, "a reload brings the draft back to the panel"),
    ("a dropped pick is not named", "){d.x=d.l||d.c;d.c=''}save()}", "){d.c=''}save()}", sc_lost_pick, "a pick dropped because the question changed is named under Send"),
    ("a note that fits no box is not set aside", "function stash(d){", "function stash(d){return;", sc_held,
     "Done with a note on a step that is gone records nothing; the note that fits no box is held, offered with Copy and Put it in the box"),
    ("an older read is drawn when it lands", "if(cur!==me||me.n!==n||SENDING[me.k])return;var old", "if(cur!==me)return;var old", sc_older_read, "an older read that lands late does not put the item back"),
    ("a redraw forgets an open ?", "\ndocument.dispatchEvent(new Event('stackshot:redrawn'))}", "}", sc_redrawn_tip, "a ? left open stays open when the item is drawn anew"),
    ("a closed panel keeps its ? open", "V.innerHTML='';document.dispatchEvent(new Event('stackshot:redrawn'));", "V.innerHTML='';", sc_redrawn_tip,
     "…and one left open when the panel was left is not open when the item is opened again"),
)


def play(br, scenario, patch=None):
    """one scenario in a browser context of its own: (its checks, the script errors, whether the patch found its text)"""
    ctx = br.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800}); ctx.add_cookies([cookie()]); ctx.set_default_timeout(4000 if patch else 10000)
    said, errs, found = [], [], []
    if patch:
        def serve(route):
            if route.request.resource_type != "document" or route.request.method != "GET": return route.fallback()
            res = route.fetch(); body = res.text()
            if patch[0] in body: found.append(True)
            route.fulfill(response=res, body=body.replace(patch[0], patch[1]))
        ctx.route("**/*", serve)
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    try:
        scenario(pg, lambda what, holds, got=None: said.append((what, bool(holds), got)))
    except Exception as e:  # noqa: BLE001  — a scenario that stops is a failed check, and the others still run
        said.append((f"{scenario.__name__} ran to its end", False, f"{type(e).__name__}: {str(e)[:600]}"))
    finally:
        try:
            pg.unroute_all(behavior="ignoreErrors"); ctx.unroute_all(behavior="ignoreErrors")
        finally:
            ctx.close()
    return said, errs, bool(found)


def scenarios(br, errors):
    for scenario in SCENARIOS:
        said, errs, _ = play(br, scenario); errors.extend(errs)
        for what, holds, got in said: check(what, holds, got)


def mutants(br):
    global SHOTS
    kept, SHOTS = SHOTS, None      # a patched page's screen would be saved over the real one of the same name
    try:
        for what, old, new, scenario, target in MUTANTS:
            said, errs, found = play(br, scenario, (old, new))
            failed = [name for name, holds, _ in said if not holds]
            broken = [e for e in errs if "SyntaxError" in e]      # a script that does not parse would fail everything and prove nothing
            check(f"mutant caught: {what}", found and not broken and target in failed, {"found": found, "script": broken, "failed": failed, "checks": len(said)})
    finally:
        SHOTS = kept


def canvasview(br, errors):
    """an item with a canvas: the panel shows the canvas in a sandboxed frame, between the question and the choices, and keeps both in reach; the page's own script runs in it"""
    item(9)
    page = (f'<!doctype html><title>t</title><a href="{BOARD}/items/9">{"board" + "#" + "9"}</a><h1 id="cv">canvasword</h1><p>a mockup page</p>'
            '<script>document.getElementById("cv").textContent="ranword"</script>').encode()
    sha = hashlib.sha256(page).hexdigest(); cdir = T / "state/canvas/4"; cdir.mkdir(parents=True); (cdir / f"{sha}.html").write_bytes(page)
    (cdir / "canvas.json").write_text(json.dumps({"schema": 1, "number": 4, "title": "a mockup", "item": "a9", "current": {"sha256": sha, "bytes": len(page), "modified": now - 60, "session": "x"}, "versions": []}))
    git("add", "-A"); git("commit", "-q", "-m", "a9 and its canvas"); board_home._board_home_drop()
    for name, size in (("desktop", {"width": 1280, "height": 800}), ("phone", {"width": 390, "height": 844})):
        ctx = br.new_context(ignore_https_errors=True, viewport=size); ctx.add_cookies([cookie()]); ctx.set_default_timeout(10000)
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
        home(pg); open_(pg, 9)
        try:
            pg.frame_locator("#brief iframe").locator("#cv").filter(has_text="ranword").wait_for()
            ran_in_frame = True
        except Exception:  # noqa: BLE001  (the check below says it)
            ran_in_frame = False
        check(f"{name}: the canvas is drawn in the panel and the page's own script runs in it", ran_in_frame and pg.eval_on_selector_all("#brief iframe", "l => l.length") == 1)
        panel = pg.eval_on_selector("#brief", "e => { const r = e.getBoundingClientRect(); return {x: r.x, r: r.right} }")
        fr = pg.eval_on_selector("#brief iframe", "e => { const r = e.getBoundingClientRect(); return {x: r.x, r: r.right, h: r.height, sandbox: e.getAttribute('sandbox')} }")
        check(f"{name}: the frame is sandboxed with scripts only, inside the panel's width and tall enough to read", fr["sandbox"] == "allow-scripts" and fr["x"] >= panel["x"] and fr["r"] <= panel["r"] + 1 and fr["h"] >= 300, (panel, fr))
        text = pg.inner_text("#brief")
        check(f"{name}: the panel's own text has the question, the recommendation, the choices and the item's link, and none of the canvas's words",
              all(w in text for w in ("whether to ship the next version", "Recommend", "sample question a9", "Ship it now as it is")) and "canvasword" not in text and "ranword" not in text, text)
        order = pg.evaluate("() => { const q = document.querySelector('#brief .bq'), f = document.querySelector('#brief iframe'), c = document.querySelector('#brief .acard'); "
                            "return [q.compareDocumentPosition(f) & 4, f.compareDocumentPosition(c) & 4] }")
        check(f"{name}: the canvas stands after the question and before the choices", order == [4, 4], order)
        check(f"{name}: a link under it opens the canvas page, and nothing scrolls sideways", pg.eval_on_selector_all("#brief a[href='/canvas/4']", "l => l.length") == 1
              and pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
        shot(pg, f"{name}-panel-canvas")
        ctx.close()


def run(br):
    errors = []
    desktop(br, errors); fullpage(br, errors); phone(br, errors, "light"); phone(br, errors, "dark"); phone(br, errors, "light", 360, 740)
    scenarios(br, errors); mutants(br); noscript(br); canvasview(br, errors)
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
