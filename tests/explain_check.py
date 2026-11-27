"""Explainer check (a browser; run by .github/workflows/explain.yml, not in the suite loop). What the "?" control (ui/explain.py) holds and what its script does are
tests/explain_scenario.py; this is what only a browser shows. The board's renderers write fixture pages into a temporary folder (no live store, no network) and the browser opens
the files. It checks that:

  - on a phone (360 px, touch, light and dark) every "?" is a 44 px target that a tap opens and a second tap closes; the popup is whole inside the screen, nothing lies over it,
    its text contrasts with its ground, and the page does not scroll sideways; a tap outside and Escape close it;
  - at 360 and 1280 px no "?" lies over words or a control beside it, so a tap on those opens nothing;
  - the color panel (dark theme, whether the page opened dark or turned dark) holds its note behind a "?"; its popup stays inside the panel, and Escape closes it before the panel;
  - the side panel's Audit card: its script redraws the card the server drew, the "?" included; the popup opens inside the panel and stays open, with the keyboard focus, through a redraw;
  - on a desktop (1280 px) hover opens it, the pointer can move onto the popup, leaving closes it; Tab reaches the button and opens it; Escape closes it;
  - the popup's ground differs between light and dark.

    tests/run-suite explain_check     -> exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    EXPLAIN_SHOTS=<folder> also saves a screenshot of each page with a popup open there."""
import datetime, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="xplchk-"); T = pathlib.Path(tmp)
SHOTS = os.environ.get("EXPLAIN_SHOTS", "")
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml, _n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert _n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, _n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]', toml); assert _n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n", encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "brain/projects", "pages"): (T / d).mkdir(parents=True)
A = "22222222-2222-4222-8222-222222222222"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n")
now = time.time()
DAY = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


def waiting(i, **meta):
    m = {"owner": A, "project": "projects/alpha", "next": "the next step", "hold": True, "needs": [], "post_wake_mover": "alpha-main", **meta}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] item {i}", "description": "- A thing", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": m}))


waiting(2, wait_kind="list", wait_mode="all", until=DAY(5), waits=[{"kind": "time", "until": DAY(3)}, {"kind": "relay", "event": "the lease"}], watch={"set_at": now - 3600})
waiting(4, wait_kind="relay", ask_by=DAY(5), wait_event="the lease", party="the landlord", chases=[{"at": now - 600, "by": "alpha-main", "note": "asked again"}])
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web.ui import render as r2
from stackshot.web.ui import runners as ui_runners

fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


board = lambda: r2.Board(str(T / "store"))
drawn = {"projects": board().projects_html(), "closed": board().landed_html(), "audits": board().audits_html(), "project": board().routing_html("projects/alpha"),
         "list-wait": board().item_html("a2"), "relay-wait": board().item_html("a4")}
ui_runners.enabled = lambda: True      # a board with runners, before the first read: nothing is read from GitHub
drawn["runners"] = ui_runners.page_html(board(), {"ts": 0, "errors": {}, "failed": [], "runners": [], "switch": {}, "stale": False, "pending": True, "refreshing": False, "age_s": 0})
from stackshot.core import config as _cfg
from stackshot.audit import audit, audit_overview
audit_was = dict(_cfg.CFG["audit"])
_cfg.CFG["audit"]["pattern_review"] = "off"
drawn["audits-log-off"] = board().audits_html()
_cfg.CFG["audit"].update(enabled=True, pattern_review="shadow")
card_page = T / "pages" / "audit-card.html"; card_page.write_text(board().html(), encoding="utf-8")      # the home page with the side panel's Audit card drawn
card_status = {**audit.status(), "card": audit_overview.card(time.time())}                             # what GET /audit/status answers for that card
_cfg.CFG["audit"].clear(); _cfg.CFG["audit"].update(audit_was)
FILES = {}
for name, h in drawn.items():
    FILES[name] = T / "pages" / f"{name}.html"; FILES[name].write_text(h, encoding="utf-8")

# the popup of the button with this id: its state, its box, what lies over it, and the contrast of its words with its ground
STATE = r"""id => { const b = document.getElementById(id), p = document.getElementById(b.getAttribute('aria-controls')), r = p.getBoundingClientRect(), s = getComputedStyle(p), br = b.getBoundingClientRect();
  const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => { x = x / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const a = lum(s.color), g = lum(s.backgroundColor), over = [];
  if (!p.hidden) for (const [x, y] of [[r.left + 3, r.top + 3], [r.right - 3, r.top + 3], [r.left + r.width / 2, r.top + r.height / 2], [r.left + 3, r.bottom - 3], [r.right - 3, r.bottom - 3]]) {
    const e = document.elementFromPoint(x, y); if (e !== p) over.push(Math.round(x) + ',' + Math.round(y) + ' ' + (e ? e.tagName + '.' + e.className : 'nothing')); }
  return {at: [br.top, br.bottom, scrollY, document.documentElement.scrollHeight, visualViewport.offsetTop, visualViewport.height, visualViewport.scale, p.style.top, p.offsetParent && p.offsetParent.className],
    open: !p.hidden && s.display !== 'none', expanded: b.getAttribute('aria-expanded'), left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: document.documentElement.clientWidth, vh: innerHeight,
    sw: document.documentElement.scrollWidth, over: over, contrast: (Math.max(a, g) + 0.05) / (Math.min(a, g) + 0.05), ground: s.backgroundColor, words: p.textContent.length, bw: br.width, bh: br.height,
    path: [br.left + br.width / 2, r.top + r.height / 2]}; }"""
# every "?" a reader can see, by id
BUTTONS = "() => [...document.querySelectorAll('button.xp-b')].filter(b => b.getClientRects().length && getComputedStyle(b).visibility !== 'hidden').map(b => b.id)"
CENTER = "id => document.getElementById(id).scrollIntoView({block: 'center', behavior: 'instant'})"
inside = lambda s: s["left"] >= -0.5 and s["right"] <= s["vw"] + 0.5 and s["top"] >= -0.5 and s["bottom"] <= s["vh"] + 0.5
WANT = {"projects": 1, "closed": 2, "audits": 13, "audits-log-off": 14, "project": 1, "list-wait": 2, "relay-wait": 1, "runners": 1}      # the fewest "?" each page shows
# the Audit card's status read, answered by the check once it sets window.__AUDIT; every other request fails, as it does for a file
STATUS = r"""window.fetch = u => window.__AUDIT && String(u).startsWith('/audit/status') ? Promise.resolve(new Response(JSON.stringify(window.__AUDIT), {status: 200, headers: {'Content-Type': 'application/json'}}))
  : Promise.reject(new TypeError('offline'));"""
CARD = "() => document.querySelector('#audit .a-txt').innerHTML"
# the card's "?" against the panel and the card's own words
IN_CARD = r"""() => { const r = e => e.getBoundingClientRect(), b = r(document.getElementById('xpb-audit-card')), p = r(document.getElementById('panel')), range = document.createRange(), over = [];
  for (const e of document.querySelectorAll('#audit .lbl, #audit .val, #audit .a-h')) { if (!e.textContent.trim()) continue; range.selectNodeContents(e);
    for (const o of range.getClientRects()) if (o.left < b.right - 0.5 && b.left < o.right - 0.5 && o.top < b.bottom - 0.5 && b.top < o.bottom - 0.5) over.push(e.textContent); }
  return {over: over, button: [b.left, b.right], panel: [p.left, p.right]}; }"""
# each shown "?" button against the words and controls outside every "?": which of them its box lies over. What is fixed to the screen floats over the page and is left out
COVERS = r"""() => { const hit = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const fixed = e => { for (; e; e = e.parentElement) if (getComputedStyle(e).position === 'fixed') return true; return false; };
  const shown = e => !fixed(e) && e.checkVisibility({checkVisibilityCSS: true});      // false inside a closed <details> too
  const things = [], range = document.createRange(), walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t; (t = walk.nextNode());) { const e = t.parentElement; if (!t.textContent.trim() || e.closest('.xp,script,style') || !shown(e)) continue; range.selectNodeContents(t);
    for (const r of range.getClientRects()) if (r.width > 1 && r.height > 1) things.push([r, t.textContent.trim().slice(0, 40)]); }
  for (const e of document.querySelectorAll('a[href],button,input,select,textarea,summary,label')) { if (e.closest('.xp') || !shown(e)) continue;
    for (const r of e.getClientRects()) if (r.width > 1 && r.height > 1) things.push([r, e.tagName + ' ' + (e.textContent || e.name || '').trim().slice(0, 40)]); }
  const bad = []; for (const b of document.querySelectorAll('button.xp-b')) { if (!shown(b)) continue; for (const r of b.getClientRects()) for (const [o, what] of things) if (hit(r, o)) bad.push(b.id + ' over ' + what); }
  return {bad: bad.slice(0, 12), things: things.length}; }"""
grounds = {}

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try: br = p.chromium.launch()
    except Exception as e:
        print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
    for scheme in ("light", "dark"):
        for name, path in FILES.items():
            tag = f"{name} 360 {scheme}"
            ctx = br.new_context(viewport={"width": 360, "height": 760}, color_scheme=scheme, has_touch=True, is_mobile=True); pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(path.as_uri()); pg.wait_for_timeout(100)
            ids = pg.evaluate(BUTTONS)
            check(f"{tag}: at least {WANT[name]} explainers show", len(ids) >= WANT[name], ids)
            c = pg.evaluate(COVERS); check(f"{tag}: no ? lies over words or a control", c["things"] > 5 and not c["bad"], c)
            for n, i in enumerate(ids):
                pg.evaluate(CENTER, i); before = pg.evaluate(STATE, i)["at"]; pg.tap(f"#{i}"); pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                ok = s["open"] and s["expanded"] == "true" and s["words"] > 0 and inside(s) and not s["over"] and s["sw"] <= 360
                check(f"{tag}: {i}: a tap opens it, whole inside the screen, nothing over it, no sideways scroll", ok, {"before": before, **s})
                if not ok and SHOTS:
                    os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"fail-{name}-{i}-{scheme}.png"))
                check(f"{tag}: {i}: a 44 px target, and words that contrast with their ground", s["bw"] >= 43.5 and s["bh"] >= 43.5 and s["contrast"] >= 4.5, s)
                grounds.setdefault(scheme, set()).add(s["ground"])
                if n == 0 and SHOTS:
                    os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"{name}-360-{scheme}.png"))
                pg.tap(f"#{i}"); pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                check(f"{tag}: {i}: a second tap closes it", not s["open"] and s["expanded"] == "false", s)
            if ids:
                i = ids[0]; pg.evaluate(CENTER, i); pg.tap(f"#{i}"); pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                y = s["bottom"] + 40 if s["bottom"] + 40 < s["vh"] else max(1, s["top"] - 40)
                was = s["open"]; pg.touchscreen.tap(2, y); pg.wait_for_timeout(50)
                check(f"{tag}: a tap outside closes it", was and not pg.evaluate(STATE, i)["open"], (was, pg.evaluate(STATE, i)))
                pg.evaluate(CENTER, i); pg.tap(f"#{i}"); pg.wait_for_timeout(30); was = pg.evaluate(STATE, i)["open"]; pg.keyboard.press("Escape"); pg.wait_for_timeout(30)
                check(f"{tag}: Escape closes it", was and not pg.evaluate(STATE, i)["open"], was)
            check(f"{tag}: no script error", not errs, errs)
            ctx.close()
        for name, path in FILES.items():
            tag = f"{name} 1280 {scheme}"
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(path.as_uri()); pg.wait_for_timeout(100)
            ids = pg.evaluate(BUTTONS)
            c = pg.evaluate(COVERS); check(f"{tag}: no ? lies over words or a control", c["things"] > 5 and not c["bad"], c)
            for i in ids:
                pg.evaluate(CENTER, i); pg.hover(f"#{i}"); pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                check(f"{tag}: {i}: hover opens it, whole inside the window, nothing over it", s["open"] and inside(s) and not s["over"], s)
                pg.mouse.move(*s["path"], steps=12); pg.wait_for_timeout(30)      # straight down (or up) from the button, which the popup spans
                check(f"{tag}: {i}: the pointer moves onto the popup and it stays", pg.evaluate(STATE, i)["open"], pg.evaluate(STATE, i))
                pg.mouse.move(1, 1); pg.wait_for_timeout(30)
                check(f"{tag}: {i}: leaving closes it", not pg.evaluate(STATE, i)["open"])
            if ids:
                i = ids[0]; pg.goto(path.as_uri()); pg.wait_for_timeout(100)
                for _ in range(120):
                    pg.keyboard.press("Tab")
                    if pg.evaluate("() => document.activeElement && document.activeElement.id") == i: break
                pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                check(f"{tag}: Tab reaches the first one and opens it", s["open"] and s["expanded"] == "true" and inside(s), s)
                if SHOTS: pg.screenshot(path=os.path.join(SHOTS, f"{name}-1280-{scheme}.png"))
                pg.keyboard.press("Escape"); pg.wait_for_timeout(30)
                check(f"{tag}: Escape closes it and focus stays on the button", not pg.evaluate(STATE, i)["open"] and pg.evaluate("() => document.activeElement.id") == i)
            ctx.close()
    # the color panel: the tool builds it only for a dark page, at once or when the page turns dark
    for width, first in ((360, "dark"), (360, "light"), (1280, "dark")):
        tag = f"colors {width}, opened {first}"; touch = width < 600
        ctx = br.new_context(viewport={"width": width, "height": 760}, color_scheme=first, has_touch=touch, is_mobile=touch); pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(FILES["projects"].as_uri()); pg.wait_for_timeout(100)
        if first == "light":
            check(f"{tag}: no panel yet", pg.evaluate("() => !document.getElementById('ct-pop')"))
            pg.emulate_media(color_scheme="dark"); pg.wait_for_timeout(300)
        check(f"{tag}: the panel's note is behind a ? and no longer under its buttons", pg.evaluate("() => !!document.querySelector('#ct-pop>.ct-foot>.xp #xpb-colors') && !document.querySelector('#ct-pop>p.ct-small')"),
              pg.evaluate("() => { const p = document.getElementById('ct-pop'); return p ? p.lastElementChild.outerHTML.slice(0, 400) : 'no panel'; }"))
        # the tool's button sits in the side panel, which a phone keeps shut: the check presses the button's own handler, then works inside the open panel
        opened = pg.evaluate("() => { const b = document.getElementById('ct-btn'), p = document.getElementById('ct-pop'); if (!b || !p) return false; b.click(); return !p.hidden; }")
        check(f"{tag}: the color panel opens", opened)
        if opened:
            press = pg.tap if touch else pg.click
            pg.evaluate(CENTER, "xpb-colors"); press("#xpb-colors"); pg.wait_for_timeout(50); s = pg.evaluate(STATE, "xpb-colors")
            box = pg.evaluate("() => { const r = document.getElementById('ct-pop').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; }")
            check(f"{tag}: its ? opens inside the panel, nothing over it", s["open"] and s["words"] > 0 and not s["over"] and s["left"] >= box[0] - 0.5 and s["right"] <= box[1] + 0.5
                  and s["top"] >= box[2] - 0.5 and s["bottom"] <= box[3] + 0.5, (s, box))
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"colors-{width}-{first}.png"))
            shown = "() => !document.getElementById('ct-pop').hidden"
            pg.keyboard.press("Escape"); pg.wait_for_timeout(50); check(f"{tag}: Escape closes the ? and leaves the panel", s["open"] and not pg.evaluate(STATE, "xpb-colors")["open"] and pg.evaluate(shown))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(50); check(f"{tag}: the next Escape closes the panel", not pg.evaluate(shown))
        check(f"{tag}: no script error", not errs, errs)
        ctx.close()
    # the side panel's Audit card: its "?" as the server draws it and as the card's script redraws it from the status
    for scheme in ("light", "dark"):
        for width in (360, 1280):
            tag = f"audit card {width} {scheme}"; touch = width < 600; i = "xpb-audit-card"
            ctx = br.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, has_touch=touch, is_mobile=touch); ctx.add_init_script(STATUS); pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(card_page.as_uri()); pg.wait_for_timeout(200)
            if touch: pg.click("#panel-open"); pg.wait_for_timeout(300)
            def redraw(status):
                pg.evaluate("s => { window.__AUDIT = s; document.dispatchEvent(new Event('stackshot:poll')); }", status); pg.wait_for_timeout(250)
            served = pg.evaluate(CARD)
            pg.evaluate("() => document.querySelector('#audit .a-txt').replaceChildren()"); redraw(card_status)
            check(f"{tag}: the script draws the card the server drew, its ? included", i in served and pg.evaluate(CARD) == served, (served[-700:], pg.evaluate(CARD)[-700:]))
            pg.evaluate(CENTER, i)
            if touch: pg.tap(f"#{i}")
            else:
                for _ in range(200):
                    pg.keyboard.press("Tab")
                    if pg.evaluate("() => document.activeElement && document.activeElement.id") == i: break
            pg.wait_for_timeout(50); s = pg.evaluate(STATE, i); c = pg.evaluate(IN_CARD)
            check(f"{tag}: it opens whole inside the panel, nothing over it", s["open"] and s["words"] > 0 and inside(s) and not s["over"] and s["right"] - s["left"] > 100 and s["left"] >= c["panel"][0] - 0.5 and s["right"] <= c["panel"][1] + 0.5, (s, c))
            check(f"{tag}: the ? lies over none of the card's words and stays inside the panel", not c["over"] and c["button"][0] >= c["panel"][0] and c["button"][1] <= c["panel"][1] and (s["bw"] >= 43.5 or not touch), (c, s))
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"audit-card-{width}-{scheme}.png"))
            changed = json.loads(json.dumps(card_status)); changed["card"]["groups"][0]["found"] = 7; redraw(changed); s = pg.evaluate(STATE, i)
            check(f"{tag}: a redraw with a new count keeps the popup open and in its place", pg.evaluate("() => [...document.querySelectorAll('#audit .a-n')].some(e => e.textContent === '7')") and s["open"] and inside(s), s)
            if not touch:
                check(f"{tag}: ...and the keyboard focus on its button", pg.evaluate("() => document.activeElement.id") == i, pg.evaluate("() => document.activeElement.tagName"))
                pg.keyboard.press("Escape"); pg.wait_for_timeout(30); redraw(card_status); s = pg.evaluate(STATE, i)
                check(f"{tag}: one closed with Escape stays closed through a redraw, still focused", not s["open"] and pg.evaluate("() => document.activeElement.id") == i, s)
            check(f"{tag}: no script error", not errs, errs)
            ctx.close()
    br.close()
check("the popup's ground differs between light and dark", grounds.get("light") and grounds.get("dark") and not grounds["light"] & grounds["dark"], grounds)
print(("ok" if not fails else "FAILED") + f": explainer check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
