"""Home count cards check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Serves the real app (the board at the root, the sign-in cookie) on a free
local port from fixture data (no live store, no network) and measures the five count cards on the home page in Chromium:

  - at 1280, 800 and 390 px, light and dark, with the side panel open and closed (pinned beside the page at 800 px and up, a drawer under it), every card is exactly 60 px tall
    (getBoundingClientRect), all five alike, whatever the width of the column the page leaves;
  - no label wraps (each is one line) and none is cut: the label's text fits its box;
  - the label "Queued for release" is shown in full where the cards' column is wide enough and as "Queued" where it is not, by the column's width (a container query on the
    cards' nav), not the window's; the column, the cards' size and the wording are the same with the panel closed as with it pinned (a closed panel's column is capped to the pinned one's);
  - the fifth card is Closed: the items closed in the last 14 days, the number alone on the top line and, on the label line right after the word "Closed", the count of closes not cleared yet
    as green text "N new" (where the label line is too narrow for it, beside the number instead, the word never dropped; nothing at 0), also 60 px tall, with the count inside the card and not cut, in four cases (3 new of 40 closed, 12 new of 123,
    123 new of 130, none new), at 1280, 800 and 390 px and in a 120 px card;
  - the word "new" is never dropped: at 360, 480, 640, 768, 960, 1024, 1280 and 1440 px windows in 100, 110 and 125% zoom (the window's CSS width is the width over the zoom), the panel open and closed, with a closed count and a
    new count of one to four digits each way, and again with a long invented stand-in for the word (the catalog's home.new_word), the Closed card shows the word whole (not display:none, not clipped, nothing over it), the badge inside the card
    and clear of the number and the label, every card 60 px tall; HCARD_ONLY_NEWWORD=1 runs this part alone;
  - nothing runs past the screen's width;
  - the header and panel layout of every page (home, an item, a project, Projects, Closed, Search, runners), at 1280, 1010, 1000 and 390 px (1010: with a classic scrollbar a pinned panel's column is under 680 px and a closed one's over it), with the panel pinned and closed, without and with a classic
    15 px scrollbar (a taller page in a browser that keeps its scrollbars): the cards' column, every card's width and the third card's wording are the same pinned and closed; the title (the h1) of every page
    but home starts 32 px under the header, as home's first section does; the panel's left border is drawn from the top of the page (the pixels at the panel's left edge, from y = 0 down, are the line's colour:
    a 1 px line 56 px tall continues it through the buttons' band) and the drawer on a phone starts at y = 0; scrolled 1000 px down a taller page at 1280 px the panel and the line, the sticky header,
    the reload and Back to top buttons keep their place in the window (the root element is a size container; a layout-contained box would become the containing block of fixed boxes);
  - a long page and a short one keep the same width: in a browser that keeps its classic scrollbars, at 1280 px with the panel open and closed, the cards' column, the main column, the header, the title and the panel have the same left edge and width on both
    (the shared stylesheet's scrollbar-gutter: stable on the root element); on a phone (390 px, mobile emulation: the scrollbar is drawn over the page) there is no scrollbar room on either and nothing changes.

  - the item page lines up with home: at 1280, 1010 and 1000 px, the panel pinned and closed, with and without a classic scrollbar, its column (the main box), the cards' two outer edges, the search box and the title
    have home's left and right edges (the item page's body column was wider than home's, so it sat 20 px to the left with the panel pinned and 46 px with it closed).

    tests/run-suite hcard_height_check     → exit 0 / 1
    HCARD_HEIGHT_SHOTS=<dir> keeps a screenshot of each state (once per machine, the browser itself: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, struct, subprocess, sys, threading, time, zlib

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="hcardchk-"); T = pathlib.Path(tmp)       # removed when the process ends, whatever the end (tests/_scratch.py)
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
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1    # the Audit section is drawn
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
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.web import server
import uvicorn
server._publish = lambda: None
COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="critical", lifespan="on"))
th = threading.Thread(target=srv.run, daemon=True); th.start()
for _ in range(100):
    try: socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close(); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("the app did not start")

from stackshot.web import landed as ld
SHOTS = os.environ.get("HCARD_HEIGHT_SHOTS", "")
if SHOTS: pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True)
def shot(pg, name):
    if SHOTS: pg.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"))
def fixture(n_closed, n_new):
    """The store holds n_closed items closed in the last 14 days (done), n_new of them with a close the owner has not cleared (a landed record); the kept home draw is dropped so the next load shows them."""
    for f in (T / "store/a").glob("*.json"): f.unlink()
    for f in (T / "state").glob("landed.json*"): f.unlink()
    now = time.time()
    for i in range(1, n_closed + 1):
        ts = now - i * 900
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] A finished piece of work number {i}", "description": "- done", "status": "completed", "updated": ts, "state_updated": ts, "confirmed": ts,
                                                         "metadata": {"owner": A, "project": "projects/alpha", "outcome": "done", "reason": f"piece {i} shipped"}}))
        if i <= n_new: ld.record(f"a{i}", ts, "done", "alpha-main", "projects/alpha")
    for i in range(n_closed + 1, n_new + 1):        # more closes not cleared than closed in 14 days: older closes (the record keeps them 60 days; the New section reads their items from the store)
        ts = now - 20 * 86400 - i * 900
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] An older piece of work number {i}", "description": "- done", "status": "completed", "updated": ts, "state_updated": ts, "confirmed": ts,
                                                         "metadata": {"owner": A, "project": "projects/alpha", "outcome": "done", "reason": f"piece {i} shipped"}}))
        ld.record(f"a{i}", ts, "done", "alpha-main", "projects/alpha")
    server._board_home_drop()
MEASURE = """() => {
  const nav = document.querySelector('nav#counts'), cs = [...nav.querySelectorAll('a.hcard')];
  const shown = (e) => { const r = document.createRange(), more = e.querySelector('.more'), cut = more && more.getBoundingClientRect().width <= 1; r.selectNodeContents(e); const nw = e.querySelector('i.hnew'); if (cut) r.setEndBefore(more); if (nw && getComputedStyle(nw).position === 'absolute') r.setEndBefore(nw); return [...r.getClientRects()].filter(q => q.width > 0); };    // the text on show: the short form leaves the clipped rest out
  const natural = (e) => { const c = e.cloneNode(true), m = c.querySelector('.more'); if (m) m.removeAttribute('class'); c.style.cssText = 'position:absolute;visibility:hidden;width:auto;white-space:nowrap;overflow:visible'; e.parentNode.appendChild(c); const w = c.getBoundingClientRect().width; c.remove(); return w; };
  return {navw: Math.round(nav.getBoundingClientRect().width * 10) / 10, sw: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth,
    cards: cs.map(a => { const r = a.getBoundingClientRect(), sp = a.querySelector('span'), more = sp.querySelector('.more'), lines = new Set(shown(sp).map(q => Math.round(q.top))),
        b = a.querySelector('b').getBoundingClientRect(), bd = a.querySelector('i.hnew'), br = bd ? bd.getBoundingClientRect() : null, em = bd ? bd.querySelector('em').getBoundingClientRect() : null, spr = sp.getBoundingClientRect(),
        tn = [...sp.childNodes].find(x => x.nodeType === 3), lr = document.createRange(); if (tn) lr.selectNodeContents(tn);
      return {label: [...sp.childNodes].filter(x => !(x.nodeType === 1 && x.matches('i.hnew'))).map(x => x.textContent).join('').trim(), num: a.querySelector('b').textContent, bfs: getComputedStyle(a.querySelector('b')).fontSize, h: r.height, top: Math.round(r.top), left: r.left, right: r.right, lines: lines.size, nat: Math.round(natural(sp) * 10) / 10, room: Math.round((sp.clientWidth) * 10) / 10,
              cut: sp.scrollWidth > sp.clientWidth + 0.5, short: more ? more.getBoundingClientRect().width <= 1 : null,
              inNum: !!a.querySelector('b i'), cw: r.width - 2 * parseFloat(getComputedStyle(a).borderLeftWidth) - 2 * parseFloat(getComputedStyle(a).paddingLeft), badge: bd ? {text: bd.textContent, word: em.width > 1, left: br.left, right: br.right, top: br.top, bottom: br.bottom, cut: br.right > r.right - 1 || br.left < r.left || br.top < r.top || br.bottom > r.bottom || em.width <= 1, color: getComputedStyle(bd).color, border: getComputedStyle(bd).borderTopWidth, lblRight: tn ? lr.getBoundingClientRect().right : null, lblTop: tn ? lr.getBoundingClientRect().top : null, lblBottom: tn ? lr.getBoundingClientRect().bottom : null, numRight: b.right, numTop: b.top, numBottom: b.bottom} : null}; })};
}"""
SHORT_PX = 680     # the column width (the cards' nav) under which the card says "Queued": the same number as the container query in ui/render.py
WORD_PX = (79, 85, 92, 98)  # the card's content width up to which the count "3 new" moves up beside the number, by the count's digits (one, two, three, four or more): the same numbers as the container queries in ui/render.py
def png_px(path, pts):
    """The (r, g, b) of the screenshot's pixels at pts [(x, y)] (an 8-bit PNG as Chromium writes it; no image library on the box)."""
    d = open(path, "rb").read(); pos = 8; idat = b""
    while pos < len(d):
        n, t = struct.unpack(">I4s", d[pos:pos + 8]); body = d[pos + 8:pos + 8 + n]; pos += 12 + n
        if t == b"IHDR": w, h, _bd, ct = struct.unpack(">IIBB", body[:10])
        if t == b"IDAT": idat += body
    bpp = {2: 3, 6: 4}[ct]; raw = zlib.decompress(idat); stride = w * bpp; rows = []; prev = bytearray(stride); i = 0
    for _y in range(h):
        f = raw[i]; line = bytearray(raw[i + 1:i + 1 + stride]); i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0; b = prev[x]; c = prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c); line[x] = (line[x] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        rows.append(line); prev = line
    return [tuple(rows[y][x * bpp:x * bpp + 3]) for x, y in pts]
def settle(pg, ms=250): pg.wait_for_timeout(ms)
seen = {}
CASES = (("new", 40, 3), ("many", 123, 12), ("wide", 130, 123), ("none", 7, 0))      # (name, closed in 14 days, closes not cleared yet): the count shown, two digits, three digits, hidden
from playwright.sync_api import sync_playwright
try:
  with sync_playwright() as p:
    try: br = p.chromium.launch(args=["--enable-features=OverlayScrollbar"])       # overlay scrollbars (a phone, a Mac), hidden here: with the flag a scrollbar-gutter reserves nothing, as there (headless Chromium's hidden scrollbars alone still reserve it)
    except Exception as e:
        print("no browser (once per machine: uvx playwright@1.63.0 install chromium):", str(e)[:160]); srv.should_exit = True; sys.exit(2)
    for case, n_closed, n_new in (() if os.environ.get("HCARD_ONLY_NEWWORD") else CASES):
        fixture(n_closed, n_new)
        for w in (1280, 800, 390):
            for scheme in ("light", "dark"):
                for panel in ("open", "closed"):
                    tag = f"{case} {w} {scheme} panel {panel}"
                    ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme)
                    ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
                    pg = ctx.new_page(); pg.goto(BOARD + "/"); settle(pg)
                    if w >= 800:
                        check(f"{tag}: the panel starts pinned", pg.evaluate("document.body.classList.contains('panel-pin')"))
                        if panel == "closed": pg.click("#panel-open"); pg.mouse.move(w // 2, 500); settle(pg, 500)
                    elif panel == "open": pg.click("#panel-open"); settle(pg, 400)
                    vis = pg.evaluate("getComputedStyle(document.getElementById('panel')).visibility") == "visible"
                    check(f"{tag}: the panel is {panel}", vis == (panel == "open"), vis)
                    m = pg.evaluate(MEASURE); cs = m["cards"]; seen[tag] = m
                    hs = [c["h"] for c in cs]
                    check(f"{tag}: five cards, every one 60 px tall", len(cs) == 5 and all(abs(h - 60) < 0.01 for h in hs), hs)
                    check(f"{tag}: no label wraps or is cut", all(c["lines"] == 1 and not c["cut"] for c in cs), [(c["label"], c["lines"], c["cut"]) for c in cs])
                    q, cl = cs[2], cs[4]; full = m["navw"] > SHORT_PX
                    check(f"{tag}: Queued for release is {'in full' if full else 'the short form'} at a column of {m['navw']} px", q["label"] == "Queued for release" and q["short"] == (not full), q)
                    check(f"{tag}: nothing runs past the screen", m["sw"] <= m["vw"] and all(c["right"] <= w + 0.5 for c in cs), (m["sw"], m["vw"]))
                    bd = cl["badge"]
                    check(f"{tag}: the last card is Closed with the 14-day count {n_closed}", cl["label"] == "Closed" and cl["num"] == str(n_closed), cl)
                    if n_new:
                        inner = cl["cw"]                                          # the card's content width, which the container queries measure
                        up = inner <= WORD_PX[min(len(str(n_new)), 4) - 1]          # the label line is too narrow for the count: it sits on the number line, beside the number
                        check(f"{tag}: the count reads '{n_new} new' in green text, whole, the word with it, inside the card and not cut, {'beside the number (the label line is too narrow)' if up else 'on the label line, right after Closed'} (content {inner:.0f} px)",
                              bd and not cl["inNum"] and bd["text"] == f"{n_new} new" and bd["word"] and not bd["cut"] and bd["right"] <= cl["right"] - 1 and bd["left"] >= cl["left"] and bd["border"] == "0px" and bd["color"] != "rgba(0, 0, 0, 0)"
                              and ((bd["left"] >= bd["numRight"] - 0.5 and bd["bottom"] <= bd["numBottom"] + 3 and bd["top"] >= cl["top"]) if up else
                                   (bd["left"] >= bd["lblRight"] - 0.5 and bd["top"] >= bd["numBottom"] - 1 and abs(bd["top"] - bd["lblTop"]) <= 3)), cl)
                    else:
                        check(f"{tag}: no badge when no close is new", bd is None, cl)
                    print(f"  {tag}: column {m['navw']} px, card {cl['right'] - cl['left']:.0f} px (content {cl['cw']:.0f}), line {cl['nat']} px, heights {hs}, rows at {sorted({c['top'] for c in cs})}, queued {'Queued' if q['short'] else 'Queued for release'}, closed {cl['num']} ({cl['bfs']}) count {bd and bd['text']} (word {bd and bd['word']})")
                    shot(pg, f"hcards-{case}-{w}-{scheme}-panel-{panel}"); ctx.close()
    # the word "new" is never dropped, whatever the width: the Closed card, the count "N new" (in the word the page says it with, the catalog's home.new_word; a long invented stand-in too, as a longer translation would be), at eight window widths
    # (360 to 1440 px) in three browser zooms (a window of w px at zoom z has w / z CSS px and z device pixels to the CSS pixel), the panel open and closed, a closed count and a new count of one to four digits: the word is shown (not
    # display:none, not clipped away, nothing covering it), the whole badge is inside the card and clear of the number and the label, and every card is 60 px tall with its label on one line
    from stackshot.web import i18n as ui_i18n
    NEW_WORD0 = ui_i18n.EN["home.new_word"]
    NEWWORD = """() => {
      const R = e => e.getBoundingClientRect(), cards = [...document.querySelectorAll('#counts a.hcard')], cl = cards[4], r = R(cl), i = cl.querySelector('i.hnew');
      const base = {heights: cards.map(a => R(a).height), n: cards.length, vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth};
      if (!i) return {...base, hnew: false};
      const em = i.querySelector('em'), ci = getComputedStyle(i), ce = getComputedStyle(em), ri = R(i), re = R(em), b = cl.querySelector('b'), rb = R(b), sp = cl.querySelector('span'), tn = [...sp.childNodes].find(x => x.nodeType === 3);
      const lr = document.createRange(); lr.selectNodeContents(tn); const l = lr.getBoundingClientRect(), hit = el => el === em || el === i || i.contains(el);
      const hide = [...document.querySelectorAll('#panel, #panel-scrim, #panel-edge')].map(e => [e, e.style.visibility]); hide.forEach(x => x[0].style.visibility = 'hidden');    // an open drawer covers the card: look through it
      const probe = [[re.left + 1, re.top + re.height / 2], [re.left + re.width / 2, re.top + re.height / 2], [re.right - 1, re.top + re.height / 2]].map(p => hit(document.elementFromPoint(p[0], p[1]))); hide.forEach(x => x[0].style.visibility = x[1]);
      const meet = (p, q) => p.left < q.right - 0.5 && q.left < p.right - 0.5 && p.top < q.bottom - 0.5 && q.top < p.bottom - 0.5;
      return {...base, hnew: true, text: i.textContent, word: em.textContent.trim(), display: ci.display, visibility: ci.visibility, opacity: ci.opacity, eDisplay: ce.display, eVisibility: ce.visibility, eClip: ce.clipPath, eW: re.width, eH: re.height,
              up: ci.position === 'absolute', inside: ri.left >= r.left && ri.right <= r.right - 1 && ri.top >= r.top && ri.bottom <= r.bottom, inView: ri.left >= 0 && ri.right <= base.vw, probe: probe,
              clearOfNumber: !meet(ri, rb), clearOfLabel: !meet(ri, l), labelLines: Math.round(l.height / 14) , labelCut: sp.scrollWidth > sp.clientWidth + 0.5, numCut: rb.right > r.right - 1 || rb.left < r.left, fs: ci.fontSize, bfs: getComputedStyle(b).fontSize,
              side: ci.position === 'absolute' ? (ri.left >= rb.right - 0.5 ? 'beside the number' : 'overlaps') : (ri.left >= l.right - 0.5 && Math.abs(ri.top - l.top) <= 3 ? 'on the label line' : 'misplaced')};
    }"""
    ZOOMS = (1.0, 1.1, 1.25); NW_WIDTHS = (360, 480, 520, 560, 600, 640, 768, 960, 1024, 1280, 1440)      # 481 to 600 px is where five cards share the row and a card's content is narrowest
    NW_CASES = ((40, 2), (5, 3), (42, 12), (123, 123), (1234, 1234), (1234, 3), (7, 1234))          # (closed in 14 days, closes not cleared yet): one to four digits each way
    LONG_STANDIN = "fresh and unread"          # an invented English stand-in for a longer word (16 characters, as a longer translation of "new" might be)
    nw_seen = {}
    for word, cases in (("new", NW_CASES), (LONG_STANDIN, ((5, 3), (123, 123), (1234, 1234), (1234, 3)))):
        ui_i18n.EN["home.new_word"] = " " + word          # the catalog's word, in this run
        for n_closed, n_new in cases:
            fixture(n_closed, n_new)
            for w in NW_WIDTHS:
                for z in ZOOMS:
                    for panel in ("open", "closed"):
                        cssw = round(w / z); tag = f"new word '{word}' {n_closed} closed / {n_new} new, window {w} px at {round(z * 100)}% ({cssw} css px), panel {panel}"
                        ctx = br.new_context(viewport={"width": cssw, "height": 900}, device_scale_factor=z)
                        ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
                        pg = ctx.new_page(); pg.goto(BOARD + "/"); settle(pg, 150)
                        if cssw >= 800:
                            if panel == "closed": pg.click("#panel-open"); pg.mouse.move(cssw // 2, 500); settle(pg, 400)
                        elif panel == "open": pg.click("#panel-open"); settle(pg, 350)
                        m = pg.evaluate(NEWWORD); nw_seen[tag] = m
                        want = {"text": m["text"] == f"{n_new} {word}", "word": m["word"] == word, "shown": m["display"] != "none" and m["visibility"] == "visible" and m["opacity"] == "1", "em shown": m["eDisplay"] != "none" and m["eVisibility"] == "visible" and m["eClip"] == "none",
                                "em size": m["eW"] > 1 and m["eH"] > 1, "nothing covers or clips it": all(m["probe"]), "inside the card": m["inside"], "inside the screen": m["inView"], "clear of the number": m["clearOfNumber"], "clear of the label": m["clearOfLabel"],
                                "number whole": not m["numCut"], "label whole": not m["labelCut"], "badge at least 9 px": float(m["fs"][:-2]) >= 8.99 or word != "new", "place": m["side"] in ("beside the number", "on the label line"), "one label line": m["labelLines"] <= 1} if m["hnew"] else {"badge drawn": False}
                        check(f"{tag}: the word is shown, whole, inside the card ({m.get('side')}), clear of the number and the label", all(want.values()), ([k for k, v in want.items() if not v], m.get("fs"), m.get("bfs"), m.get("probe")))
                        check(f"{tag}: five cards, every one 60 px tall, nothing past the screen", m["n"] == 5 and all(abs(h - 60) < 0.01 for h in m["heights"]) and m["sw"] <= m["vw"], (m["heights"], m["sw"], m["vw"]))
                        if SHOTS and word == "new" and (n_closed, n_new) == (40, 2) and w == 960 and z == 1.1 and panel == "closed":
                            pg.locator("header.top").screenshot(path=str(pathlib.Path(SHOTS) / "closed-card-960-110.png"))
                        ctx.close()
    ui_i18n.EN["home.new_word"] = NEW_WORD0
    n_up = sum(1 for m in nw_seen.values() if m.get("side") == "beside the number"); n_line = sum(1 for m in nw_seen.values() if m.get("side") == "on the label line")
    check("the matrix reaches both arrangements: the count beside the number where the label line is too narrow and on the label line where it fits", n_up > 0 and n_line > 0, (n_up, n_line))
    print(f"  new word matrix: {len(nw_seen)} windows, {n_up} with the count beside the number, {n_line} on the label line")
    if os.environ.get("HCARD_ONLY_NEWWORD"):      # a quick run of this part alone
        print(f"{len(ran) - len(fails)}/{len(ran)} checks passed"); srv.should_exit = True; sys.exit(1 if fails else 0)
    # the page the Closed card links to: titled Closed, with New (the badge's count) and Last 14 days (the big number); the old Landed address lands on it
    fixture(40, 3)
    for w in (1280, 390):
        for scheme in ("light", "dark"):
            tag = f"closed page {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme)
            ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
            pg = ctx.new_page(); pg.goto(BOARD + "/"); settle(pg); href = pg.get_attribute("a.hcard:last-child", "href")
            pg.click("a.hcard:last-child"); settle(pg, 400)
            d = pg.evaluate("""() => ({path: location.pathname, h1: document.querySelector('h1').textContent, title: document.title, heads: [...document.querySelectorAll('h2.lsec')].map(h => h.textContent.replace(/\\s+/g, ' ').trim()),
                                       rows: document.querySelectorAll('#new li.lrow').length, last: document.querySelectorAll('#completed li').length, sw: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth})""")
            check(f"{tag}: the card goes to /closed, titled Closed, with the sections New 3 and Last 14 days 40 (the badge and the big number), no sideways scroll",
                  href == "/closed" and d["path"] == "/closed" and d["h1"] == "Closed" and d["title"].startswith("Closed") and d["heads"] == ["New 3", "Last 14 days 40"] and d["rows"] == 3 and d["last"] == 25 and d["sw"] <= d["vw"], (href, d))
            shot(pg, f"closed-page-{w}-{scheme}")
            pg.goto(BOARD + "/landed?page=2"); settle(pg, 300)
            check(f"{tag}: the old /landed?page=2 address ends on /closed?page=2", pg.evaluate("location.pathname + location.search") == "/closed?page=2" and pg.evaluate("document.querySelector('h1').textContent") == "Closed", pg.url)
            ctx.close()
    # the same window, panel open and closed: the cards keep the size and the wording they have with the panel pinned (the closed panel's column is capped to the pinned one's, ui/render.py)
    for w_ in (1280, 800):
        o_, c_ = seen[f"new {w_} light panel open"], seen[f"new {w_} light panel closed"]
        check(f"{w_} px: same window: the column, every card's width and the third card's wording are the same with the panel open and closed",
              o_["navw"] == c_["navw"] and [c["h"] for c in o_["cards"]] == [c["h"] for c in c_["cards"]] and [c["right"] - c["left"] for c in o_["cards"]] == [c["right"] - c["left"] for c in c_["cards"]]
              and o_["cards"][2]["short"] == c_["cards"][2]["short"], (o_["navw"], c_["navw"]))
    check("800 px: the label is the short form with the panel open and with it closed (the pinned panel narrows the column; closed, the cards keep that size)",
          seen["new 800 light panel open"]["cards"][2]["short"] is True and seen["new 800 light panel closed"]["cards"][2]["short"] is True)
    check("the badge is the same card height with and without it: 60 px in all three cases", all(c["h"] == 60 for t, m_ in seen.items() for c in m_["cards"]))

    # the layout of every page: cards, title spacing and the panel's border, pinned and closed, with and without a classic scrollbar
    fixture(40, 3)
    (T / "store/a/41.json").write_text(json.dumps({"id": "41", "subject": "[work] An open piece of work", "description": "- do it", "status": "open", "updated": time.time() - 900, "state_updated": time.time() - 900, "confirmed": time.time() - 900,
                                                  "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step"}})); server._board_home_drop()
    PAGES = {"home": "/", "item": "/items/a41", "project": "/projects/alpha", "Projects": "/projects", "Closed": "/closed", "Search": "/search?q=piece", "runners": "/runners"}
    LAYOUT = """() => {
      const R = e => e.getBoundingClientRect(), q = s => document.querySelector(s), nav = q('nav#counts'), cs = [...nav.querySelectorAll('a.hcard')], pn = q('#panel'), hd = q('header.top');
      const first = q('main > header.top + h1, main > header.top + p.pjback') || q('main > section[id], main > details.fold[id]'), pb = getComputedStyle(document.body, '::after'), more = cs[2].querySelector('.more');
      return {navw: R(nav).width, edges: [R(q('main')).left, R(q('main')).right, R(nav).left, R(nav).right, R(cs[0]).left, R(cs[4]).right, R(q('header.top .sbox')).left, R(q('header.top .sbox')).right, R(q('main > header.top + h1, main > h1') || q('main > section[id], main > details.fold[id]')).left], cardw: cs.map(a => R(a).width), short: more.getBoundingClientRect().width <= 1, gap: R(first).top - R(hd).bottom, h1: first.tagName === 'H1' || first.matches('p.pjback'), sb: innerWidth - document.documentElement.clientWidth,
              panelLeft: R(pn).left, panelTop: R(pn).top, panelVis: getComputedStyle(pn).visibility, vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth,
              line: {display: pb.display, position: pb.position, top: pb.top, right: pb.right, width: pb.width, height: pb.height, z: pb.zIndex, bg: pb.backgroundColor}};
    }"""
    brc = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])       # a browser that keeps its (classic, 15 px) scrollbars
    seenL = {}
    for sbar, brx in (("no scrollbar", br), ("classic scrollbar", brc)):
        for w in (1280, 1010, 1000, 390):
            for name, path in PAGES.items():
                for panel in ("open", "closed"):
                    tag = f"layout {name} {w} px, {sbar}, panel {panel}"
                    ctx = brx.new_context(viewport={"width": w, "height": 700}); ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
                    pg = ctx.new_page(); pg.goto(BOARD + path); settle(pg)
                    pg.evaluate("document.body.style.minHeight = '3000px'"); settle(pg, 150)       # taller than the window: a classic scrollbar shows where the browser keeps it
                    pinned = pg.evaluate("document.body.classList.contains('panel-pin')")
                    if w >= 800 and pinned != (panel == "open"): pg.click("#panel-open"); pg.mouse.move(w // 2, 400); settle(pg, 500)
                    elif w < 800 and panel == "open": pg.click("#panel-open"); settle(pg, 400)
                    m = pg.evaluate(LAYOUT); seenL[(sbar, w, name, panel)] = m
                    check(f"{tag}: the browser shows {'a classic scrollbar' if sbar != 'no scrollbar' else 'no scrollbar'} ({m['sb']} px)", (m["sb"] > 0) == (sbar != "no scrollbar"), m["sb"])
                    check(f"{tag}: the title starts 32 px under the header ({'the h1' if name != 'home' else 'the first section'})", abs(m["gap"] - 32) < 0.6 and m["h1"] == (name != "home"), (m["gap"], m["h1"]))
                    check(f"{tag}: nothing runs past the screen's width", m["sw"] <= m["vw"], (m["sw"], m["vw"]))
                    if panel == "open":
                        ys = [0, 5, 30, 55, 56, 100, 400]; x = round(m["panelLeft"]); shotp = T / f"lay-{len(seenL)}.png"; pg.screenshot(path=str(shotp))
                        px = png_px(str(shotp), [(x, y) for y in ys]); bgpx = png_px(str(shotp), [(x - 40, 5)])[0]
                        check(f"{tag}: the panel is shown and its left border is drawn from y = 0 to the bottom (the pixels at its left edge, x = {x}, from the top down, all the line's colour, not the page's)",
                              m["panelVis"] == "visible" and len(set(px)) == 1 and px[0] != bgpx, (m["panelVis"], px, bgpx))
                        if w >= 800:
                            ln = m["line"]; right = float(ln["right"][:-2]) if ln["right"].endswith("px") else None
                            check(f"{tag}: the line above the panel is fixed at the top, 1 px wide, 56 px tall and at the panel's own left edge ({m['panelLeft']:.0f})",
                                  ln["display"] == "block" and ln["position"] == "fixed" and ln["top"] == "0px" and ln["width"] == "1px" and ln["height"] == "56px" and right is not None and abs(m["vw"] - right - 1 - m["panelLeft"]) < 0.6 and abs(m["panelTop"] - 56) < 0.6, ln)
                        else:
                            check(f"{tag}: the drawer starts at the top of the page and carries no line of its own", abs(m["panelTop"]) < 0.6 and m["line"]["display"] != "block" and m["line"]["position"] != "fixed", (m["panelTop"], m["line"]))
                    ctx.close()
    for sbar in ("no scrollbar", "classic scrollbar"):
        for w in (1280, 1010, 1000):
            for name in PAGES:
                o_, c_ = seenL[(sbar, w, name, "open")], seenL[(sbar, w, name, "closed")]
                check(f"layout {name} {w} px, {sbar}: the cards' column, every card's width and the third card's wording are the same with the panel pinned and closed",
                      abs(o_["navw"] - c_["navw"]) < 0.6 and all(abs(a - b) < 0.6 for a, b in zip(o_["cardw"], c_["cardw"])) and o_["short"] == c_["short"], (o_["navw"], c_["navw"], o_["short"], c_["short"]))
    # the item page lines up with home: its column (the main box), the header's cards and search box, and its first section's left edge are where home's are (the item page's body column was wider than home's
    # and sat 20 px to the left with the panel pinned, 46 px with it closed); desktop widths, the panel pinned and closed, with and without a classic scrollbar
    for sbar in ("no scrollbar", "classic scrollbar"):
        for w in (1280, 1010, 1000):
            for panel in ("open", "closed"):
                hm, it = seenL[(sbar, w, "home", panel)]["edges"], seenL[(sbar, w, "item", panel)]["edges"]
                check(f"layout item vs home {w} px, {sbar}, panel {panel}: the item page's column, cards and search box have home's left and right edges (main {it[0]:.0f}-{it[1]:.0f} / home {hm[0]:.0f}-{hm[1]:.0f}); its title starts at home's left edge",
                      all(abs(a - b) < 0.6 for a, b in zip(hm[:8], it[:8])) and abs(hm[8] - it[8]) < 0.6, (hm, it))
    for k in ((s_, w_, n_) for s_ in ("no scrollbar", "classic scrollbar") for w_ in (1280, 1010, 1000) for n_ in ("home", "item")):
        print(f"  layout {k}: column pinned {seenL[k + ('open',)]['navw']:.1f} px, closed {seenL[k + ('closed',)]['navw']:.1f} px; third card {'Queued' if seenL[k + ('open',)]['short'] else 'Queued for release'} / {'Queued' if seenL[k + ('closed',)]['short'] else 'Queued for release'}")
    # scrolled: the root element is a size container (html{container:page/inline-size}); a layout-contained box would be the containing block of position:fixed descendants, and a fixed box would then scroll away with the page
    SCROLLED = """() => {
      const R = e => e.getBoundingClientRect(), q = s => document.querySelector(s), cs = e => getComputedStyle(e);
      const t = q('#totop'), rl = q('#reload');
      return {y: Math.round(scrollY), vh: innerHeight, panel: R(q('#panel')).top, panelVis: cs(q('#panel')).visibility, header: R(q('header.top')).top, sticky: cs(q('header.top')).position,
              reload: [R(rl).top, R(rl).bottom, R(rl).right], totop: [R(t).top, R(t).bottom, R(t).right, cs(t).display, cs(t).bottom, cs(t).position], themeTop: R(q('header.top .theme')).top, pbtnTop: R(q('#panel-open')).top};
    }"""
    for name, path in PAGES.items():
        for panel in ("open", "closed"):
            tag = f"scrolled {name} 1280 px, panel {panel}"
            ctx = br.new_context(viewport={"width": 1280, "height": 700}); ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
            pg = ctx.new_page(); pg.goto(BOARD + path); settle(pg)
            pg.evaluate("document.querySelector('main').style.minHeight = '3000px'"); settle(pg, 150)       # the main column is taller than the window (the sticky header stays inside it)
            if pg.evaluate("document.body.classList.contains('panel-pin')") != (panel == "open"): pg.click("#panel-open"); pg.mouse.move(640, 400); settle(pg, 500)
            top0 = pg.evaluate(SCROLLED); pg.evaluate("window.scrollTo(0, 1000)"); settle(pg, 400); top1 = pg.evaluate(SCROLLED)
            check(f"{tag}: the page scrolled to 1000", top0["y"] == 0 and top1["y"] == 1000, (top0["y"], top1["y"]))
            check(f"{tag}: the panel keeps its place in the window (top {top0['panel']:.0f} px before and after) and is {'shown' if panel == 'open' else 'hidden'}", top1["panel"] == top0["panel"] == 56 and top1["panelVis"] == ("visible" if panel == "open" else "hidden"), (top0["panel"], top1["panel"], top1["panelVis"]))
            check(f"{tag}: the header still sticks (position sticky, top 0 in the window) and its theme and panel buttons stay at their place", top1["sticky"] == "sticky" and top1["header"] == 0 and top1["themeTop"] == top0["themeTop"] and top1["pbtnTop"] == top0["pbtnTop"], (top1["sticky"], top1["header"], top0["themeTop"], top1["themeTop"]))
            check(f"{tag}: the reload button keeps its place in the window", top1["reload"] == top0["reload"], (top0["reload"], top1["reload"]))
            tt = top1["totop"]
            check(f"{tag}: Back to top is shown, fixed, inside the window and at its CSS offset from the window's bottom ({tt[4]})", tt[3] != "none" and tt[5] == "fixed" and 0 <= tt[0] and tt[1] <= top1["vh"] and abs(top1["vh"] - tt[1] - float(tt[4][:-2])) < 1, tt)
            if panel == "open":
                x = round(pg.evaluate("document.getElementById('panel').getBoundingClientRect().left")); shotp = T / f"scr-{name}.png"; pg.screenshot(path=str(shotp))
                px = png_px(str(shotp), [(x, y) for y in (0, 30, 55, 56, 100, 400, 690)]); bgpx = png_px(str(shotp), [(x - 40, 5)])[0]
                check(f"{tag}: after scrolling, the panel's left border is still drawn from y = 0 to the bottom of the window (the line above the panel, 56 px, is fixed to the window)", len(set(px)) == 1 and px[0] != bgpx, (px, bgpx))
            ctx.close()
    # a long page and a short one keep the same width: the shared stylesheet reserves the classic scrollbar's width on the root element (scrollbar-gutter: stable), so a page that scrolls loses nothing a short one keeps;
    # a phone draws its scrollbar over the page (mobile emulation here), so there is nothing to reserve and nothing changes
    GUTTER = """() => {
      const R = e => e.getBoundingClientRect(), q = s => document.querySelector(s), box = e => e ? [R(e).left, R(e).width] : null;
      return {sb: innerWidth - document.documentElement.clientWidth, gutter: getComputedStyle(document.documentElement).scrollbarGutter, scrolls: document.documentElement.scrollHeight > innerHeight,
              nav: box(q('nav#counts')), main: box(q('main')), header: box(q('header.top')), h1: box(q('main h1') || q('main section[id], main details.fold[id]')), panel: box(q('#panel')), sw: document.documentElement.scrollWidth, vw: document.documentElement.clientWidth};
    }"""
    seenG = {}
    for w, mobile in ((1280, False), (390, True)):
        for name, path in PAGES.items():
            for panel in ("open", "closed"):
                for length in ("short", "long"):
                    tag = f"gutter {name} {w} px{' (phone)' if mobile else ''}, panel {panel}, {length} page"
                    ctx = brc.new_context(viewport={"width": w, "height": 5000 if length == "short" else 700}, is_mobile=mobile, has_touch=mobile)
                    ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
                    pg = ctx.new_page(); pg.goto(BOARD + path); settle(pg)
                    if length == "long": pg.evaluate("document.body.style.minHeight = '3000px'"); settle(pg, 150)
                    if w >= 800 and pg.evaluate("document.body.classList.contains('panel-pin')") != (panel == "open"): pg.click("#panel-open"); pg.mouse.move(w // 2, 400); settle(pg, 500)
                    elif w < 800 and panel == "open": pg.click("#panel-open"); settle(pg, 400)
                    m = pg.evaluate(GUTTER); seenG[(w, name, panel, length)] = m
                    check(f"{tag}: the page {'scrolls' if length == 'long' else 'does not scroll'}", m["scrolls"] == (length == "long"), m["scrolls"])
                    check(f"{tag}: nothing runs past the screen's width", m["sw"] <= m["vw"], (m["sw"], m["vw"]))
                    ctx.close()
                s_, l_ = seenG[(w, name, panel, "short")], seenG[(w, name, panel, "long")]
                tag = f"gutter {name} {w} px{' (phone)' if mobile else ''}, panel {panel}"
                if mobile: check(f"{tag}: the phone draws its scrollbar over the page (none takes room), long and short", s_["sb"] == 0 and l_["sb"] == 0, (s_["sb"], l_["sb"]))
                else: check(f"{tag}: the long page shows a classic scrollbar (15 px) and the root element asks for a stable gutter", l_["sb"] == 15 and l_["gutter"].startswith("stable"), (l_["sb"], l_["gutter"]))
                check(f"{tag}: the cards' column, the main column, the header, the title and the panel have the same left edge and width on the short page and the long one",
                      all((s_[k] is None) == (l_[k] is None) and (s_[k] is None or all(abs(a - b) < 0.6 for a, b in zip(s_[k], l_[k]))) for k in ("nav", "main", "header", "h1", "panel")), (s_, l_))
    for name in ("home", "runners"):
        print(f"  gutter {name} 1280 px, panel open: main {seenG[(1280, name, 'open', 'short')]['main']} short / {seenG[(1280, name, 'open', 'long')]['main']} long")
    brc.close()
    br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
