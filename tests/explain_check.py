"""Explainer check (a browser; run by .github/workflows/explain.yml, not in the suite loop). What the "?" control (ui/explain.py) holds and what its script does are
tests/explain_scenario.py; this is what only a browser shows. The board's renderers write fixture pages into a temporary folder (no live store, no network) and the browser opens
the files. It checks that:

  - on a phone (360 px, touch, light and dark) every "?" is a 44 px target that a tap opens, without moving the page, and a second tap closes; the popup is whole inside the screen, nothing lies over it,
    its text contrasts with its ground, and the page does not scroll sideways; a tap outside and Escape close it;
  - at 360 and 1280 px no "?" lies over words or a control beside it, so a tap on those opens nothing;
  - on a phone, scrolled to its end, no page leaves a "?" under a floating button;
  - the color panel (dark theme, whether the page opened dark or turned dark) holds its note behind a "?"; its popup stays inside the panel, and Escape closes it before the panel;
  - on a phone, every explanation a page carries in an attribute (a data-tip or a title on what is not a control: a time's age, a stale sign, a receiver's state, a machine's
    failure, a waiting line's box, the dash of the Audit card) opens by a real tap, whole inside the screen, and a second tap closes it; a control with a title keeps its action;
  - the side panel's Audit card: its script redraws the card the server drew; a dash's popup opens by tap or click, stays open through a redraw, and Escape closes it before the panel;
  - on a short desktop window (1280 x 620), wherever a "?" sits in the pinned side panel (the check puts one in the Audit card), beside or among the floating buttons, no part of its popup is under one;
  - on a desktop (1280 px) hover opens it, the pointer can move onto the popup, leaving closes it; Tab reaches the button and opens it; Escape closes it;
  - the popup's ground differs between light and dark.

    tests/run-suite explain_check     -> exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)
    EXPLAIN_SHOTS=<folder> also saves a screenshot of each page with a popup open there."""
import datetime, json, logging, os, pathlib, re, subprocess, sys, time, zoneinfo
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
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0", "setup": {"ok": False, "step": "tools", "reason": "no room left on the disk"},
    "updates": [{"what": "claude", "from": "1.0.0", "to": "1.1.0", "ok": False, "reason": "the download stopped"}]}))
B = "33333333-3333-4333-8333-333333333333"
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}, B: {"name": "alpha-helper", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "agents": {"alpha-main": "builds", "alpha-helper": "helps"}, "back_agents": {"alpha-helper": "helps"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n")
now = time.time()
DAY = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


def waiting(i, **meta):
    m = {"owner": A, "project": "projects/alpha", "next": "the next step", "hold": True, "needs": [], "mover": "alpha-main", **meta}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] item {i}", "description": "- A thing", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": m}))


waiting(2, wait_kind="list", wait_mode="all", until=DAY(5), waits=[{"kind": "time", "until": DAY(3)}, {"kind": "relay", "event": "the lease"}], watch={"set_at": now - 3600})
waiting(4, wait_kind="relay", ask_by=DAY(5), wait_event="the lease", party="the landlord", chases=[{"at": now - 600, "by": "alpha-main", "note": "asked again"}])
(T / "store/a/5.json").write_text(json.dumps({"id": "5", "subject": "[work] item 5", "description": "- A thing", "status": "open", "updated": now - 90 * 86400,      # open on an agent and long unconfirmed: stale
    "state_updated": now - 90 * 86400, "confirmed": now - 90 * 86400, "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step"}}))
seen = lambda ago: (datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Dubai")) - datetime.timedelta(seconds=ago)).strftime("%Y-%m-%d %H:%M:%S")
(T / "state/anchor-hub").mkdir()
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": "x", "anchors": {}, "receivers": {"github": {"ok": True, "checked": seen(30)},
    "google": {"ok": False, "error": "mail: the connection closed", "checked": seen(9000)}}}))
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
         "list-wait": board().item_html("a2"), "relay-wait": board().item_html("a4"), "stale-item": board().item_html("a5")}
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
  return {open: !p.hidden && s.display !== 'none', expanded: b.getAttribute('aria-expanded'), left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: document.documentElement.clientWidth, vh: innerHeight,
    sw: document.documentElement.scrollWidth, over: over, contrast: (Math.max(a, g) + 0.05) / (Math.min(a, g) + 0.05), ground: s.backgroundColor, words: p.textContent.length, bw: br.width, bh: br.height,
    path: [br.left + br.width / 2, r.top + r.height / 2]}; }"""
# every "?" a reader can see, by id
BUTTONS = "() => [...document.querySelectorAll('button.xp-b')].filter(b => b.getClientRects().length && getComputedStyle(b).visibility !== 'hidden').map(b => b.id)"
CENTER = "id => document.getElementById(id).scrollIntoView({block: 'center', behavior: 'instant'})"
# scrolled to its end, where a reader can scroll no further: the "?" a floating button lies over there
AT_END = r"""() => { scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'});
  return [...document.querySelectorAll('button.xp-b')].filter(b => { if (!b.getClientRects().length) return false; const r = b.getBoundingClientRect(),
    t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return t && t.closest('#totop, .fab'); }).map(b => b.id); }"""
# where the page was as the finger came down, after whatever scrolling the tap itself needed to reach the button
FINGER = "() => addEventListener('pointerdown', () => { window.__y = scrollY; }, true)"
inside = lambda s: s["left"] >= -0.5 and s["right"] <= s["vw"] + 0.5 and s["top"] >= -0.5 and s["bottom"] <= s["vh"] + 0.5
WANT = {"stale-item": 0, "projects": 3, "closed": 2, "audits": 13, "audits-log-off": 14, "project": 1, "list-wait": 2, "relay-wait": 1, "runners": 1}      # the fewest "?" each page shows
# the Audit card's status read, answered by the check once it sets window.__AUDIT; every other request fails, as it does for a file
STATUS = r"""window.fetch = u => window.__AUDIT && String(u).startsWith('/audit/status') ? Promise.resolve(new Response(JSON.stringify(window.__AUDIT), {status: 200, headers: {'Content-Type': 'application/json'}}))
  : Promise.reject(new TypeError('offline'));"""
CARD = "() => document.querySelector('#audit .a-txt').innerHTML"
# the "?" with this id moved to a height in the side panel: the card pushed down by an empty block above it, as more cards would, or the panel scrolled
PUT = r"""([i, y]) => { const p = document.getElementById('panel'); if (!document.getElementById(i)) document.querySelector('#audit .a-txt').appendChild(window.stackshotExplain(i.slice(4), 'A dash means the group keeps no findings log.', 'Help'));
  const b = document.getElementById(i), card = b.closest('#audit'); let s = document.getElementById('xchk-space');
  if (!s) { s = document.createElement('div'); s.id = 'xchk-space'; card.parentNode.insertBefore(s, card); const room = document.createElement('div'); room.style.height = '1000px'; p.appendChild(room); }      // room to scroll
  s.style.height = '0px'; p.scrollTop = 0; const d = y - b.getBoundingClientRect().bottom; if (d > 0) s.style.height = d + 'px'; else p.scrollTop = -d; return b.getBoundingClientRect().bottom; }"""
# that popup against the floating buttons: every point of a grid over it that something else is drawn on; and whether, straight below its "?", it would meet a button
CLEAR = r"""i => { const b = document.getElementById(i), p = document.getElementById(b.getAttribute('aria-controls')), q = e => e.getBoundingClientRect(), r = q(p), br = q(b), n = q(document.getElementById('panel')), under = [];
  if (!p.hidden) for (let y = r.top + 4; y <= r.bottom - 4; y += 4) for (let x = r.left + 4; x <= r.right - 4; x += 4) { const e = document.elementFromPoint(x, y); if (e !== p) under.push([Math.round(x), Math.round(y), e ? e.tagName + '#' + e.id : 'nothing']); }
  const fabs = [...document.querySelectorAll('#totop, .fab')].map(q).filter(f => f.width);
  return {open: !p.hidden, under: under.slice(0, 8), left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: document.documentElement.clientWidth, vh: innerHeight, button: [br.left, br.right, br.top, br.bottom],
    panel: [n.left, n.right], fabs: fabs.map(f => [f.left, f.top, f.bottom]), met: fabs.some(f => f.left < n.right - 8 && f.top < br.bottom + r.height && br.bottom < f.bottom)}; }"""
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
# the explanations a page carries in an attribute, on what is not a control, that a reader can see: each marked with a number, with the text a tap should show
TIPS = r"""inPanel => { const CTL = 'a[href],button,input,select,textarea,label,summary,iframe,.xp', words = h => { let t = h.getAttribute('data-tip'); if (t === null) t = h.getAttribute('title'); if (!t) return '';
    const u = h.parentElement && h.parentElement.closest('[data-xt-also]'), m = u && u.getAttribute('title'); return m ? t + '\n' + m : t; };
  document.querySelectorAll('details').forEach(d => d.open = true); document.querySelectorAll('[data-xchk]').forEach(e => e.removeAttribute('data-xchk'));
  return [...document.querySelectorAll('[data-tip],[title]')].filter(e => !!e.closest('#panel') === inPanel && !e.closest(CTL) && words(e) && e.checkVisibility({checkVisibilityCSS: true}) && e.getBoundingClientRect().width)
    .filter(e => !e.hasAttribute('data-xt-also'))      // the rendered line is covered by its time, whose popup carries the line's words too
    .map((e, n) => { e.setAttribute('data-xchk', n); return {n: n, text: words(e), kind: (e.closest('#rendered') ? '#rendered ' : '') + e.tagName + '.' + (e.getAttribute('class') || '')}; }); }"""
# an explanation a tap cannot reach, since it sits inside a control (a data-tip is never a control's own name)
SHUT_IN = "() => [...document.querySelectorAll('[data-tip]')].filter(e => e.closest('a[href],button,label,summary')).map(e => e.outerHTML.slice(0, 200))"
# a point of that element, scrolled to the middle, where the element itself (not one with its own explanation inside it, a control or anything over it) is what a finger meets:
# of those points the one farthest from anything inside it that takes a tap of its own, since a phone's browser moves a tap onto such a target close by
POINT = r"""n => { const CTL = 'a[href],button,input,select,textarea,label,summary,iframe,.xp', e = document.querySelector('[data-xchk="' + n + '"]'); e.scrollIntoView({block: 'center', behavior: 'instant'});
  const others = [...e.querySelectorAll('[data-tip],[title],' + CTL)].map(o => o.getBoundingClientRect()), far = (x, y) => Math.min(1e9, ...others.map(r => Math.hypot(Math.max(r.left - x, 0, x - r.right), Math.max(r.top - y, 0, y - r.bottom))));
  let best = null; for (const r of e.getClientRects()) for (const fy of [0.5, 0.25, 0.75, 0.1, 0.9]) for (const fx of [0.5, 0.25, 0.75, 0.05, 0.95]) { const x = r.left + r.width * fx, y = r.top + r.height * fy, t = document.elementFromPoint(x, y);
    if (t && t.closest('[data-tip],[title]') === e && !t.closest(CTL) && (!best || far(x, y) > best.far)) best = {x: x, y: y, far: far(x, y), cursor: getComputedStyle(t).cursor}; }
  if (best) return best; const r = e.getBoundingClientRect(), t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {x: null, at: [r.left, r.top, r.width, r.height], meets: t ? t.tagName + '#' + t.id + '.' + t.getAttribute('class') : 'nothing'}; }"""
# the popup a tap opened: how many, its words, its box, what lies over it, and the element's own CSS tooltip
TAPPED = r"""n => { const all = [...document.querySelectorAll('.xt-pop')], p = all[0], e = document.querySelector('[data-xchk="' + n + '"]'); if (!p) return {count: 0};
  const r = p.getBoundingClientRect(), s = getComputedStyle(p), over = [];
  for (const [x, y] of [[r.left + 3, r.top + 3], [r.right - 3, r.top + 3], [r.left + r.width / 2, r.top + r.height / 2], [r.left + 3, r.bottom - 3], [r.right - 3, r.bottom - 3]]) {
    const h = document.elementFromPoint(x, y); if (h !== p) over.push(Math.round(x) + ',' + Math.round(y) + ' ' + (h ? h.tagName + '.' + h.className : 'nothing')); }
  return {count: all.length, text: p.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: document.documentElement.clientWidth, vh: innerHeight, over: over, sw: document.documentElement.scrollWidth,
    wb: s.wordBreak, ow: s.overflowWrap, after: e ? getComputedStyle(e, '::after').content : ''}; }"""
# the "?" beside the Queued for release fold: the middle of its mark against the heading's line, and the heading's words clear of the button
QUEUED = r"""() => { const h = document.querySelector('#queued-release h2'), b = document.getElementById('xpb-queued-release').getBoundingClientRect(), r = h.getBoundingClientRect(), g = document.createRange(); g.selectNodeContents(h);
  return {h2: [r.top, r.bottom], mid: (b.top + b.bottom) / 2, button: [b.left, b.top, b.right, b.bottom], clear: [...g.getClientRects()].every(w => w.right <= b.left || w.width >= r.width - 1)}; }"""
grounds = {}
kinds = set(); rendered_said = ""

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try: br = p.chromium.launch()
    except Exception as e:
        print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
    for scheme in ("light", "dark"):
        for name, path in FILES.items():
            tag = f"{name} 360 {scheme}"
            ctx = br.new_context(viewport={"width": 360, "height": 760}, color_scheme=scheme, has_touch=True, is_mobile=True); pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(path.as_uri()); pg.wait_for_timeout(100); pg.evaluate(FINGER)
            ids = pg.evaluate(BUTTONS)
            check(f"{tag}: at least {WANT[name]} explainers show", len(ids) >= WANT[name], ids)
            c = pg.evaluate(COVERS); check(f"{tag}: no ? lies over words or a control", c["things"] > 5 and not c["bad"], c)
            under = pg.evaluate(AT_END); check(f"{tag}: at the page's end no ? is under a floating button", not under, under)
            for n, i in enumerate(ids):
                pg.evaluate(CENTER, i); pg.tap(f"#{i}"); pg.wait_for_timeout(30); s = pg.evaluate(STATE, i)
                moved = pg.evaluate("() => scrollY - window.__y")
                check(f"{tag}: {i}: opening it leaves the page where it was", abs(moved) <= 1, moved)
                check(f"{tag}: {i}: a tap opens it, whole inside the screen, nothing over it, no sideways scroll",
                      s["open"] and s["expanded"] == "true" and s["words"] > 0 and inside(s) and not s["over"] and s["sw"] <= 360, s)
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
    # every explanation in an attribute, tapped with a finger: in the page, then in the side panel opened over it
    for scheme in ("light", "dark"):
        for name, path in [*FILES.items(), ("home", card_page)]:
            tag = f"tips {name} 360 {scheme}"
            ctx = br.new_context(viewport={"width": 360, "height": 760}, color_scheme=scheme, has_touch=True, is_mobile=True, reduced_motion="reduce"); ctx.add_init_script(STATUS); pg = ctx.new_page(); errs = []      # no slide to wait for
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(path.as_uri()); pg.wait_for_timeout(200)
            shut_in = pg.evaluate(SHUT_IN); check(f"{tag}: no data-tip sits inside a control", not shut_in, shut_in)
            for in_panel in (False, True):
                if in_panel:
                    if not pg.evaluate("() => !!document.getElementById('panel-open')"): continue
                    # no slide: a point taken mid-slide scrolls the page sideways
                    pg.add_style_tag(content="#panel{transition:none!important}"); pg.click("#panel-open"); pg.wait_for_timeout(100)
                for t in pg.evaluate(TIPS, in_panel):
                    what = f"{tag}: {'panel ' if in_panel else ''}{t['n']} {t['kind']}"
                    at = pg.evaluate(POINT, t["n"]); check(f"{what}: a finger can reach it, and it says it takes a tap", at["x"] is not None and at["cursor"] == "pointer", (at, t))
                    if at["x"] is None: continue
                    pg.touchscreen.tap(at["x"], at["y"]); pg.wait_for_timeout(40); got = pg.evaluate(TAPPED, t["n"])
                    ok = got["count"] == 1 and got["text"] == t["text"] and inside(got) and not got["over"] and got["sw"] <= 360
                    check(f"{what}: a tap opens its text, whole inside the screen, nothing over it", ok, (got, t))
                    if ok:
                        kinds.add(t["kind"])
                        if name == "home" and t["kind"].startswith("#rendered"): rendered_said = got["text"]
                        check(f"{what}: one popup only, no CSS tooltip beside it, words kept whole", got["after"] in ("none", "normal") and got["wb"] == "keep-all" and got["ow"] == "anywhere", got)
                    if SHOTS and ok and t["n"] == 0:
                        os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"tip-{name}-{'panel-' if in_panel else ''}360-{scheme}.png"))
                    pg.touchscreen.tap(at["x"], at["y"]); pg.wait_for_timeout(40); got = pg.evaluate(TAPPED, t["n"])
                    check(f"{what}: a second tap closes it", got["count"] == 0, got)
            if name == "home":      # the "?" of the Queued for release list: on its heading's line, at the right, and a tap opens it
                pg.evaluate("() => document.getElementById('panel-close').click()"); pg.wait_for_timeout(50)
                pg.evaluate(CENTER, "xpb-queued-release"); q = pg.evaluate(QUEUED); pg.tap("#xpb-queued-release"); pg.wait_for_timeout(50); s = pg.evaluate(STATE, "xpb-queued-release")
                check(f"{tag}: the Queued for release ? sits on its heading's line and clear of its words", q["h2"][0] <= q["mid"] <= q["h2"][1] and q["clear"], q)
                check(f"{tag}: ...and a tap opens it, whole inside the screen, nothing over it", s["open"] and inside(s) and not s["over"] and s["sw"] <= 360, s)
                if SHOTS: os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"queued-360-{scheme}.png"))
            check(f"{tag}: no script error", not errs, errs)
            ctx.close()
    check("the rendered line's own words open under its time", "re-rendered" in rendered_said, rendered_said)
    for need in ("#rendered SPAN.tip", "SPAN.iwarn", "SPAN.iwarn stw", "SPAN.wbox", "DIV.mf", "DIV.pc rcv warn", "SPAN.lbl st warn", "SPAN.rtag", "SPAN.val a-n a-none"):
        check(f"a real tap opened at least one of: {need}", any(k == need or k.startswith(need + " ") for k in kinds), sorted(kinds))
    print("tapped open: " + ", ".join(sorted(kinds)), flush=True)
    # a control that carries a title keeps what a tap on it does, and opens no popup
    ctx = br.new_context(viewport={"width": 360, "height": 760}, has_touch=True, is_mobile=True); ctx.add_init_script(STATUS); pg = ctx.new_page(); pg.goto(card_page.as_uri()); pg.wait_for_timeout(200)
    link = 'a.hcard[href^="#"][title]'
    check("a count card with a title is there to tap", pg.evaluate("s => !!document.querySelector(s)", link))
    if pg.evaluate("s => !!document.querySelector(s)", link):
        want = pg.get_attribute(link, "href"); pg.tap(link); pg.wait_for_timeout(100)
        check("a link with a title: the tap follows it, and no popup opens", pg.evaluate("() => location.hash") == want and not pg.evaluate("() => document.querySelectorAll('.xt-pop').length"), (want, pg.evaluate("() => location.hash")))
    theme = pg.evaluate("() => { const b = document.querySelector('button#theme[title]'); return b ? b.getAttribute('title') : null }")
    check("the theme button is there to tap", theme is not None)
    if theme is not None:
        pg.evaluate("() => scrollTo(0, 0)"); pg.tap("button#theme"); pg.wait_for_timeout(100)
        now_says = pg.get_attribute("button#theme", "title")
        check("a button with a title: the tap presses it, and no popup opens", now_says != theme and not pg.evaluate("() => document.querySelectorAll('.xt-pop').length"), (theme, now_says))
    ctx.close()
    # the side panel's Audit card: as the server draws it and as the card's script redraws it from the status, and the popup of a dash
    for scheme in ("light", "dark"):
        for width in (360, 1280):
            tag = f"audit card {width} {scheme}"; touch = width < 600; i = "#audit .a-none"
            ctx = br.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme, has_touch=touch, is_mobile=touch, reduced_motion="reduce"); ctx.add_init_script(STATUS); pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(card_page.as_uri()); pg.wait_for_timeout(200)
            if touch: pg.click("#panel-open"); pg.wait_for_timeout(350)
            def redraw(status):
                pg.evaluate("s => { window.__AUDIT = s; document.dispatchEvent(new Event('stackshot:poll')); }", status); pg.wait_for_timeout(250)
            served = pg.evaluate(CARD)
            pg.evaluate("() => document.querySelector('#audit .a-txt').replaceChildren()"); redraw(card_status)
            check(f"{tag}: the script draws the card the server drew, its dashes included", served.count("a-none") == 2 and pg.evaluate(CARD) == served, (served[-700:], pg.evaluate(CARD)[-700:]))
            check(f"{tag}: the card ends on its last group's row, no line of its own for the dash", pg.evaluate("() => document.querySelector('#audit .a-txt').lastElementChild.classList.contains('a-n')"), served[-300:])
            target = pg.locator(i).first; target.scroll_into_view_if_needed()
            target.tap() if touch else target.click()
            pg.wait_for_timeout(50); got = pg.evaluate(TAPPED, -1); panel = pg.evaluate("() => { const r = document.getElementById('panel').getBoundingClientRect(); return [r.left, r.right]; }")
            check(f"{tag}: the dash's text opens, whole inside the window, nothing over it", got["count"] == 1 and "findings log" in got["text"] and inside(got) and not got["over"], (got, panel))
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"audit-card-{width}-{scheme}.png"))
            changed = json.loads(json.dumps(card_status)); changed["card"]["groups"][0]["found"] = 7; redraw(changed); got = pg.evaluate(TAPPED, -1)
            check(f"{tag}: a redraw with a new count keeps the popup open", pg.evaluate("() => [...document.querySelectorAll('#audit .a-n')].some(e => e.textContent === '7') && document.querySelector('#audit .a-none').hasAttribute('data-xt-open')")
                  and got["count"] == 1 and inside(got), got)
            shown = "() => { const r = document.getElementById('panel').getBoundingClientRect(); return r.left < innerWidth - 1 && r.right > 1 && getComputedStyle(document.getElementById('panel')).visibility !== 'hidden'; }"
            pg.keyboard.press("Escape"); pg.wait_for_timeout(350)
            check(f"{tag}: Escape closes the popup and leaves the panel", pg.evaluate(TAPPED, -1)["count"] == 0 and pg.evaluate(shown))
            if touch:
                target = pg.locator(i).first; target.tap(); pg.wait_for_timeout(50); was = pg.evaluate(TAPPED, -1)["count"]; pg.tap("#panel-close"); pg.wait_for_timeout(400)
                check(f"{tag}: closing the panel takes the popup along", was == 1 and pg.evaluate(TAPPED, -1)["count"] == 0, was)
            check(f"{tag}: no script error", not errs, errs)
            ctx.close()
    # the pinned side panel on a short desktop window: the floating buttons are drawn over its lower right, where the Audit card's "?" and its popup can be
    for scheme in ("light", "dark"):
        i = "xpb-audit-card"
        ctx = br.new_context(viewport={"width": 1280, "height": 620}, color_scheme=scheme); ctx.add_init_script(STATUS); pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(card_page.as_uri()); pg.wait_for_timeout(200)
        check(f"pinned panel {scheme}: it is pinned, and under the floating buttons' layer",
              pg.evaluate("() => document.body.classList.contains('panel-pin') && +getComputedStyle(document.getElementById('panel')).zIndex < +getComputedStyle(document.getElementById('totop')).zIndex"))
        for y, among in ((300, False), (480, False), (501, False), (560, True), (600, True)):
            tag = f"pinned panel {scheme}, ? ending at {y}"
            got = pg.evaluate(PUT, [i, y]); check(f"{tag}: the ? is put there", abs(got - y) <= 1, got)
            if among: pg.evaluate("i => document.getElementById(i).click()", i)      # a button lies over the "?" itself: the keyboard still reaches it
            else: pg.hover(f"#{i}")
            pg.wait_for_timeout(50); s = pg.evaluate(CLEAR, i)
            check(f"{tag}: its popup is whole inside the window and the panel, no part of it under a floating button",
                  s["open"] and inside(s) and not s["under"] and s["left"] >= s["panel"][0] - 0.5 and s["right"] <= s["panel"][1] + 0.5 and len(s["fabs"]) == 2, s)
            if y > 400: check(f"{tag}: straight below the ? it would have met a button", s["met"] or among, s)
            if SHOTS and y in (501, 560):
                os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, f"pinned-panel-{y}-{scheme}.png"))
            if among: pg.evaluate("i => document.getElementById(i).click()", i)
            else:
                pg.mouse.move((s["button"][0] + s["button"][1]) / 2, (s["top"] + s["bottom"]) / 2, steps=12); pg.wait_for_timeout(30)
                check(f"{tag}: the pointer moves onto the popup and it stays", pg.evaluate(CLEAR, i)["open"], pg.evaluate(CLEAR, i))
                pg.mouse.move(1, 1)
            pg.wait_for_timeout(30)
            check(f"{tag}: it closes again", not pg.evaluate(CLEAR, i)["open"])
        check(f"pinned panel {scheme}: no script error", not errs, errs)
        ctx.close()
    br.close()
check("the popup's ground differs between light and dark", grounds.get("light") and grounds.get("dark") and not grounds["light"] & grounds["dark"], grounds)
print(("ok" if not fails else "FAILED") + f": explainer check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
