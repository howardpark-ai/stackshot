"""Rendered-line check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Serves the real app (the board at the root, the sign-in cookie) on a free
local port from fixture data (no live store, no network) and loads every page of the new UI that has the header (home, an item, a project, Projects, Closed, Search, runners) in Chromium,
at 1280 and 390 px, light and dark:

  - the "rendered … ago" line (#rendered) is in the header, in the title's row: to the right of the site title, on the title's line, before the count cards (home has it there too, not between
    the cards and the search box any more); once on the page; it carries the stale threshold (data-stale, 900 s) and its title text;
  - it is the muted grey while the page is current (just drawn: "just now") and the warn amber once its age passes data-stale (the page's own clock moved 20 minutes on: the 30-second tick, home's or
    the other pages' script, turns it), and grey again for a stamp 14 minutes old;
  - on desktop it says "rendered <age>" (the word and the age); on a phone the word is left off and the age stays;
  - nothing overflows at 1280 or 390 px: the line is inside the screen, clear of the theme and panel buttons, on one line, and the page has no sideways scroll, also with a long site title (the title wraps,
    the line stays on the title's row and inside the screen);
  - the rest of the header still works: five count cards 60 px tall, the search box, the theme and panel buttons, the header sticky when wide and not on a phone; on home the connection notice, shown,
    is inside the screen and under the buttons; a page without the line (a bare document) breaks nothing in the stamp script.

    tests/run-suite rendered_line_check     → exit 0 / 1
    RENDERED_LINE_SHOTS=<dir> keeps a screenshot of each page at each width (once per machine, the browser itself: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, subprocess, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="rlinechk-"); T = pathlib.Path(tmp)       # removed when the process ends, whatever the end (tests/_scratch.py)
with socket.socket() as s_:
    s_.bind(("127.0.0.1", 0)); PORT = s_.getsockname()[1]
BOARD = f"http://127.0.0.1:{PORT}"
EMAIL = "mina@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/audit", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A = "22222222-2222-4222-8222-222222222222"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "state/anchor-hub/status.json").write_text(json.dumps({"receivers": {"hook-a": {"ok": True, "checked": "2026-10-30 10:00:00"}}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
now0 = time.time()
for i in range(1, 6):
    ts = now0 - i * 900
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] A finished piece of work number {i}", "description": "- done", "status": "completed", "updated": ts, "state_updated": ts, "confirmed": ts,
                                                     "metadata": {"owner": A, "project": "projects/alpha", "outcome": "done", "reason": f"piece {i} shipped"}}))
(T / "store/a/41.json").write_text(json.dumps({"id": "41", "subject": "[work] An open piece of work", "description": "- do it", "status": "open", "updated": now0 - 900, "state_updated": now0 - 900, "confirmed": now0 - 900,
                                              "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step"}}))
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web import app as _wapp
from stackshot.web.auth import signin as _signin
import uvicorn
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="critical", lifespan="on"))
th = threading.Thread(target=srv.run, daemon=True); th.start()
for _ in range(100):
    try: socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close(); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("the app did not start")
_wapp._board_home_drop()

SHOTS = os.environ.get("RENDERED_LINE_SHOTS", "")
if SHOTS: pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True)
def shot(pg, name):
    if SHOTS: pg.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"))
PAGES = {"home": "/", "item": "/items/a41", "project": "/projects/alpha", "Projects": "/projects", "Closed": "/closed", "Search": "/search?q=piece", "runners": "/runners"}
STALE_S = 900       # [publish] every_minutes 10 × 1.5, in seconds: the line's data-stale
MEASURE = """() => {
  const R = e => e.getBoundingClientRect(), q = s => document.querySelector(s), cs = e => getComputedStyle(e), hd = q('header.top');
  const probe = (v) => { const d = document.createElement('i'); d.style.color = 'var(' + v + ')'; document.body.appendChild(d); const c = cs(d).color; d.remove(); return c; };
  const g = q('#rendered'), line = q('header.top .rline'), site = q('header.top .site'), sa = site.querySelector('a'), th = q('#theme'), pb = q('#panel-open'), rw = line.querySelector('.rw');
  const lr = R(line), sr = R(site), ar = R(sa), cards = [...document.querySelectorAll('nav#counts a.hcard')], sbox = q('header.top .sbox');
  const lh = parseFloat(cs(line).lineHeight) || 16, conn = q('#conn');
  return {n: document.querySelectorAll('#rendered').length, inHeader: hd.contains(g), inRow: !!g.closest('.hbar'), text: line.innerText.replace(/\\s+/g, ' ').trim(), word: cs(rw).display !== 'none',
    stale: g.getAttribute('data-stale'), titleAttr: g.getAttribute('title') || '', color: cs(g).color, lineColor: cs(line).color, mut: probe('--mut'), warn: probe('--warn'), old: g.classList.contains('old'),
    lineLeft: lr.left, lineRight: lr.right, lineTop: lr.top, lineBottom: lr.bottom, lineH: lr.height, lineLh: lh, siteRight: ar.right, siteTop: sr.top, siteBottom: sr.bottom, siteH: ar.height,
    themeLeft: R(th).left, pbtnLeft: R(pb).left, pbtnRight: R(pb).right, themeRight: R(th).right, cardsTop: R(q('nav#counts')).top, sboxTop: R(sbox).top,
    cards: cards.map(a => R(a).height), pos: cs(hd).position, sw: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth,
    connBox: conn ? (() => { const r = R(conn); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, shown: cs(conn).display !== 'none'}; })() : null};
}"""
from playwright.sync_api import sync_playwright
def ctx_for(br, w, scheme):
    ctx = br.new_context(viewport={"width": w, "height": 800}, color_scheme=scheme)
    ctx.add_cookies([{"name": _signin._UI_COOKIE, "value": COOKIE, "url": BOARD}])
    return ctx
try:
  with sync_playwright() as p:
    try: br = p.chromium.launch()
    except Exception as e:
        print("no browser (once per machine: uvx playwright@1.63.0 install chromium):", str(e)[:160]); srv.should_exit = True; sys.exit(2)
    for name, path in PAGES.items():
        for w in (1280, 390):
            for scheme in ("light", "dark"):
                tag = f"{name} {w} {scheme}"
                ctx = ctx_for(br, w, scheme); ctx.clock.install()        # the page's clock is ours: a 20-minute-old page is a fast-forward away
                pg = ctx.new_page(); pg.goto(BOARD + path); pg.wait_for_timeout(300)
                m = pg.evaluate(MEASURE)
                check(f"{tag}: #rendered is once on the page, in the header, in the title's row", m["n"] == 1 and m["inHeader"] and m["inRow"], m)
                check(f"{tag}: the line is to the right of the site title, on the title's row, above the count cards and the search box",
                      m["lineLeft"] >= m["siteRight"] - 0.5 and m["lineTop"] >= m["siteTop"] - 1 and m["lineBottom"] <= m["siteBottom"] + 1 and m["lineBottom"] <= m["cardsTop"] and m["cardsTop"] < m["sboxTop"], m)
                check(f"{tag}: it is one line, inside the screen and clear of the theme and panel buttons", m["lineH"] <= m["lineLh"] * 1.6 and m["lineRight"] <= min(m["pbtnLeft"], m["themeLeft"]) + 0.5 and m["lineLeft"] >= 0, m)
                check(f"{tag}: it carries the stale threshold {STALE_S} s and its title text (home: about publishing; the others: when the page was drawn)", m["stale"] == str(STALE_S) and (("re-rendered at least every 10 minutes" in m["titleAttr"] and "older than 15 minutes" in m["titleAttr"]) if name == "home"
                      else (re.fullmatch(r"this page was drawn at \w{3} \w{3} \d+(?:st|nd|rd|th) \d\d:\d\d; reload for the current board", m["titleAttr"]) is not None and "server has not published" not in m["titleAttr"])), (m["stale"], m["titleAttr"]))
                check(f"{tag}: it says the age ({'rendered just now' if w >= 600 else 'just now, without the word rendered'})",
                      m["text"] == ("rendered just now" if w >= 600 else "just now") and m["word"] == (w >= 600), (m["text"], m["word"]))
                check(f"{tag}: grey (the muted colour) while the page is current", m["color"] == m["mut"] and m["lineColor"] == m["mut"] and not m["old"] and m["mut"] != m["warn"], (m["color"], m["mut"], m["warn"]))
                check(f"{tag}: five count cards 60 px tall, the page has no sideways scroll", m["cards"] == [60] * 5 and m["sw"] <= m["vw"], (m["cards"], m["sw"], m["vw"]))
                check(f"{tag}: the header is {'sticky' if w > 600 else 'not sticky'}", m["pos"] == ("sticky" if w > 600 else "relative"), m["pos"])
                check(f"{tag}: the theme and panel buttons are inside the screen", 0 <= m["themeLeft"] and m["themeRight"] <= w and 0 <= m["pbtnLeft"] and m["pbtnRight"] <= m["themeLeft"] + 0.5, m)
                if name == "home":
                    check(f"{tag}: the connection notice is in the header, hidden while the board is current", m["connBox"] is not None and not m["connBox"]["shown"], m["connBox"])
                    pg.evaluate("(() => { const c = document.getElementById('conn'); c.className = 'conn down'; c.hidden = false; })()"); pg.wait_for_timeout(100)
                    c = pg.evaluate(MEASURE)
                    check(f"{tag}: the connection notice, shown, is inside the screen and under the title row and the buttons, the line unmoved",
                          c["connBox"]["shown"] and 0 <= c["connBox"]["left"] and c["connBox"]["right"] <= w and c["sw"] <= c["vw"] and c["connBox"]["bottom"] <= c["cardsTop"] + 0.5 and abs(c["lineLeft"] - m["lineLeft"]) < 40, (c["connBox"], c["cardsTop"]))
                    pg.evaluate("(() => { const c = document.getElementById('conn'); c.className = 'conn'; c.hidden = true; })()")
                shot(pg, f"{name}-{w}-{scheme}")
                # the page's clock 20 minutes on: past data-stale, the line turns amber (home's tick, and _STAMP_JS elsewhere), the text says 20m
                pg.clock.fast_forward("20:00"); pg.wait_for_timeout(200)
                o = pg.evaluate(MEASURE)
                check(f"{tag}: amber (the warn colour) once the page is 20 minutes old, reading 20m ago", o["color"] == o["warn"] and o["old"] and o["text"].endswith("20m ago"), (o["color"], o["warn"], o["old"], o["text"]))
                check(f"{tag}: aged, the line is still beside the title, inside the screen and one line", o["lineLeft"] >= o["siteRight"] - 0.5 and o["lineRight"] <= min(o["pbtnLeft"], o["themeLeft"]) + 0.5 and o["lineH"] <= o["lineLh"] * 1.6 and o["sw"] <= o["vw"], o)
                if scheme == "light":
                    # a stamp 14 minutes old is under the 15-minute threshold: still grey
                    pg.evaluate("document.querySelector('#rendered [data-ts]').setAttribute('data-ts', String(Math.floor(Date.now() / 1000) - 14 * 60))"); pg.clock.fast_forward("00:31"); pg.wait_for_timeout(200)
                    f = pg.evaluate(MEASURE)
                    check(f"{tag}: a stamp 14 minutes old is still grey", f["color"] == f["mut"] and not f["old"] and f["text"].endswith("14m ago"), (f["color"], f["old"], f["text"]))
                    # a long site title: the title wraps in its own box, the line stays on the title's row and inside the screen
                    pg.evaluate("document.querySelector('header.top .site a').lastChild.textContent = 'stackshot of the Example team board and its long name'"); pg.wait_for_timeout(100)
                    l = pg.evaluate(MEASURE)
                    check(f"{tag}: with a long site title the line is inside the screen, clear of the buttons, beside the title (its top inside the title's box), no sideways scroll",
                          l["lineRight"] <= min(l["pbtnLeft"], l["themeLeft"]) + 0.5 and l["lineTop"] >= l["siteTop"] - 1 and l["lineTop"] <= l["siteBottom"] and l["sw"] <= l["vw"], l)
                ctx.close()
    # a page without the line: the stamp script finds nothing and throws nothing
    ctx = ctx_for(br, 1280, "light"); pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BOARD + "/projects"); pg.evaluate("document.getElementById('rendered').remove()")
    pg.evaluate("""() => { const s = document.createElement('script'); s.textContent = [...document.scripts].map(x => x.textContent).filter(t => t.includes("getElementById('rendered')") && t.includes('setInterval(tick,30000)') && t.length < 700)[0]; document.body.appendChild(s); }""")
    pg.wait_for_timeout(200)
    check("a page without the line: the stamp script runs and raises no error", errs == [], errs)
    ctx.close()
    br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
