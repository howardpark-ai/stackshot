"""Scenario test for the fold memory: every fold on every page of the board keeps the state its viewer left it in, per browser (ui/render.py `_FOLD_HEAD`, `_FOLD_JS` and the
swap in `_LIVE_JS`): fixture data, the pages through Starlette's test client, no live store, no network. People and addresses are made up.

The pages come from the real renderer; the scripts run in node against a small fake document (a parser for the page's own markup, details elements that fire their toggle
event after an `open` change, a MutationObserver, a localStorage that can be made to throw), so a page's markup, the head script, the body script and the in-place swap are
exercised together as the browser would run them, never read as text.

Covers:
  * the markup: every page that draws the side panel (home, an item, a project, Projects, Closed, Audits, Search) carries the head script once, before its first fold, and the body
    script once, after the panel's markup; a panel section's key is its section id, the same on every page;
  * a toggle writes the key (`stackshot.fold.<data-fold>`: 1 open, 0 closed) for a section of the main column, a scope group inside it and a section of the side panel;
  * a reload applies it: the head script alone applies it before the first paint, the body script alone (a browser without MutationObserver) does too; a section fold renders closed and
    opens on a stored 1, a scope group renders open and closes on a stored 0; a value that is neither leaves the page as drawn; storage that throws leaves the page as drawn and breaks nothing;
  * untouched folds keep the defaults the page renders, whatever else is stored, and an untouched page writes no choice that differs from its defaults;
  * the panel's choice is one key per section that holds on every page: closing Machines on one page kind closes it on all the others;
  * a hash to a section, to a row inside a closed group and to a count's section opens it on load and on hashchange; the hash stays in the address; the open is recorded, so a reload
    without the hash shows it still open; nothing removes a stored key;
  * the live swap: a block swapped in keeps what the viewer left on screen, hands a fold the old block did not have to the stored state, and a fold it swaps in keeps recording;
    the swap's carry-over never writes (a stale tab does not overwrite a newer stored choice); a count card's same-hash click reopens its section, also after a swap replaced the cards.

    tests/run-suite fold_memory        → exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="fmem-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MINA = "mina@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml, _n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert _n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A, X = "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in ((A, "alpha-main"), (X, "alpha-x"))}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
now0 = time.time()
def item(i, subject, owner, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "- A thing\n- It lives here\n- Finished when it works", "status": "open",
        "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"owner": owner, "project": "projects/alpha", "next": "the next step", **meta}}))
item(1, "[work] item one", A)
item(2, "[work] item two", A, mover="back")
item(3, "[work] item three", X)
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.web import search
from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))

PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("projects", "/projects"), ("closed", "/closed"), ("audits", "/audits"), ("search", "/search?q=item")]
PANEL_KEYS = {"machines", "runners", "anchorhub", "audit-panel", "projects-panel"}
html = {}
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    for n, p in PAGES:
        r = c.get(p, follow_redirects=False)
        check(f"the {n} page ({p}) is served", r.status_code == 200, r.status_code)
        html[n] = r.text

# ---- 1. the markup: both scripts on every page that draws the panel
FH, FJ = r2._FOLD_HEAD, r2._FOLD_JS
for n, h in html.items():
    head = h[:h.find("</head>")]
    check(f"{n}: the head script is in the head once, before the first fold, and the body script is on the page once, after the panel's markup",
          h.count(FH) == 1 and FH in head and (h.find('<details class="fold"') < 0 or h.find(FH) < h.find('<details class="fold"'))
          and h.count("<script>" + FJ + "</script>") == 1 and h.find(FJ) > h.find('<aside id="panel"') > 0, (h.count(FH), h.count(FJ)))
fold_keys = lambda h: re.findall(r'<details class="fold" data-fold="([^"]+)"', h)
panel_of = lambda h: h[h.index('<aside id="panel"'):h.index("</aside>", h.index('<aside id="panel"'))]
check("a panel section's key is its section id, the same on every page that draws it",
      all(set(fold_keys(panel_of(h))) <= PANEL_KEYS and "machines" in fold_keys(panel_of(h)) and "projects-panel" in fold_keys(panel_of(h)) for h in html.values()), {n: fold_keys(panel_of(h)) for n, h in html.items()})
check("a page's keys are unique, so one stored value is one fold", all(len(fold_keys(h)) == len(set(fold_keys(h))) for h in html.values()), {n: fold_keys(h) for n, h in html.items()})

# ---- 2. the scripts, run in node against the pages
SIM = r"""
const vm = require('vm'), fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const VOID = new Set(['meta', 'link', 'img', 'br', 'input', 'hr', 'source', 'col', 'area', 'base', 'wbr']);
const out = {};
let queue = [];
class El {
  constructor(tag, attrs) { this.tagName = tag.toUpperCase(); this.tag = tag; this.attrs = attrs; this.children = []; this.parentElement = null; this.nodeType = 1; this._open = 'open' in attrs; this.docRoot = null; }
  get parentNode() { return this.parentElement; }
  get id() { return this.attrs.id || ''; } get className() { return this.attrs.class || ''; }
  get isConnected() { let n = this; while (n.parentElement) n = n.parentElement; return n === curDoc.documentElement; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; } setAttribute(k, v) { this.attrs[k] = String(v); }
  get open() { return this._open; }
  set open(v) { v = !!v; if (v === this._open) return; this._open = v; queue.push(this); }
  matches(sel) { return match(this, sel); }
  closest(sel) { for (let n = this; n; n = n.parentElement) if (match(n, sel)) return n; return null; }
  querySelectorAll(sel) { const r = []; (function w(n) { for (const c of n.children) { if (match(c, sel)) r.push(c); w(c); } })(this); return r; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  contains(o) { for (let n = o; n; n = n.parentElement) if (n === this) return true; return false; }
  appendChild(c) { c.parentElement = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentElement = null; return c; }
  replaceChild(n, o) { const i = this.children.indexOf(o); this.children[i] = n; n.parentElement = this; o.parentElement = null; return o; }
  addEventListener(t, fn) { (this.l = this.l || {})[t] = (this.l[t] || []).concat([fn]); }
  scrollIntoView() {} focus() {}
  clone() { const e = new El(this.tag, Object.assign({}, this.attrs)); e._open = this._open; this.children.forEach(c => e.appendChild(c.clone())); return e; }
}
function match(n, sel) {
  const m = /^([a-z0-9]*)(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/.exec(sel);
  if (!m) throw new Error('selector not supported: ' + sel);
  if (m[1] && n.tag !== m[1]) return false;
  if (m[2] && n.attrs.id !== m[2].slice(1)) return false;
  if (m[3]) for (const c of m[3].slice(1).split('.')) if (!(n.attrs.class || '').split(/\s+/).includes(c)) return false;
  if (m[4]) for (const a of m[4].match(/\[[^\]]+\]/g)) {
    const q = /^\[([\w-]+)(\^=)?(?:"([^"]*)")?\]$/.exec(a); if (!q) throw new Error('attribute selector not supported: ' + a);
    if (!(q[1] in n.attrs)) return false; if (q[2] && !n.attrs[q[1]].startsWith(q[3])) return false;
  }
  return true;
}
function parse(src) {          // the page's markup, without scripts, styles, comments and text: elements only
  src = src.replace(/<!--[\s\S]*?-->/g, '').replace(/<(script|style)\b[\s\S]*?<\/\1>/g, '').replace(/<!doctype[^>]*>/i, '');
  const root = new El('html', {}); const st = [root];
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*))?)*)\s*(\/?)>/g; let m;
  while ((m = re.exec(src))) {
    const tag = m[2].toLowerCase();
    if (m[1]) { for (let i = st.length - 1; i > 0; i--) if (st[i].tag === tag) { st.length = i; break; } continue; }
    const attrs = {}; const ar = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]*)))?/g; let a;
    while ((a = ar.exec(m[3]))) attrs[a[1]] = a[2] !== undefined ? a[2] : a[3] !== undefined ? a[3] : a[4] !== undefined ? a[4] : '';
    if (tag === 'html') { Object.assign(root.attrs, attrs); continue; }
    const e = new El(tag, attrs); st[st.length - 1].appendChild(e);
    if (!VOID.has(tag) && !m[4]) st.push(e);
  }
  return root;
}
let curDoc = null;
const settle = async () => { for (let i = 0; i < 4; i++) { await new Promise(r => setImmediate(r)); const q = queue.splice(0); for (const el of q) fire(el); } };
function fire(el) { if (!curDoc || !el.isConnected) return; (curDoc.listeners.toggle || []).filter(l => l.cap).forEach(l => l.fn({ target: el })); }
function makeStore(throwing) {
  const m = new Map(); const s = { m, getItem: k => { if (throwing) throw new Error('denied'); return m.has(k) ? m.get(k) : null; }, setItem: (k, v) => { if (throwing) throw new Error('denied'); m.set(k, String(v)); }, removeItem: k => { m.delete(k); } };
  s.log = []; const set = s.setItem; s.setItem = (k, v) => { s.log.push([k, String(v)]); set(k, v); }; return s;
}
// load a page the way the browser runs it: an empty document, the head script, the markup inserted piece by piece, then the body script, DOMContentLoaded and load
async function load(name, store, o) {
  o = o || {};
  const tree = parse(data.pages[name]);
  const head = tree.children.find(c => c.tag === 'head'), body = tree.children.find(c => c.tag === 'body');
  const docEl = new El('html', {}); const bodyEl = new El('body', body.attrs); docEl.appendChild(new El('head', {})); docEl.appendChild(bodyEl);
  const doc = { documentElement: docEl, body: bodyEl, listeners: {}, activeElement: bodyEl, readyState: 'loading', observers: [], _pending: [] };
  doc.addEventListener = (t, fn, cap) => { (doc.listeners[t] = doc.listeners[t] || []).push({ fn, cap: !!cap }); };
  doc.getElementById = id => { let r = null; (function w(n) { for (const c of n.children) { if (!r && c.attrs.id === id) r = c; w(c); } })(docEl); return r; };
  doc.querySelectorAll = s => docEl.querySelectorAll(s); doc.querySelector = s => docEl.querySelector(s);
  doc.importNode = n => n.clone();
  curDoc = doc;
  const wl = {}; const loc = { hash: o.hash || '' };
  const ctx = { document: doc, localStorage: store, location: loc, decodeURIComponent, queueMicrotask, Promise, setTimeout, console, listeners: wl };
  ctx.addEventListener = (t, fn) => { (wl[t] = wl[t] || []).push(fn); };
  ctx.window = ctx;
  if (!o.noObserver) ctx.MutationObserver = function (cb) {
    this.cb = cb; this.recs = [];
    this.observe = () => { doc.observers.push(this); }; this.takeRecords = () => this.recs.splice(0); this.disconnect = () => { doc.observers = doc.observers.filter(x => x !== this); };
  };
  const g = vm.createContext(ctx);
  if (!o.noHead) vm.runInContext(data.head, g);
  const insert = (parent, node) => {      // a parser insertion: the observers hear of it in a microtask
    parent.appendChild(node);
    for (const ob of doc.observers) { ob.recs.push({ addedNodes: [node] }); queueMicrotask(() => { const r = ob.recs.splice(0); if (r.length) ob.cb(r, ob); }); }
    (function w(n) { if (n.tag === 'details' && n._open) queue.push(n); n.children.forEach(w); })(node);      // a browser also fires toggle for an open attribute the parser sets
  };
  for (const ch of body.children) { const sub = ch; sub.parentElement = null; insert(bodyEl, sub); await Promise.resolve(); }
  const folds = () => Object.fromEntries(docEl.querySelectorAll('details.fold').map(d => [d.attrs['data-fold'], d.open]));
  const res = { doc, store, ctx: g, folds, docEl, win: ctx, afterHead: folds() };
  if (!o.noBody) vm.runInContext(data.fold, g);
  doc.readyState = 'interactive'; (doc.listeners.DOMContentLoaded || []).forEach(l => l.fn({})); await settle();
  if (!o.noLoad) { (ctx.listeners.load || []).forEach(f => f({})); await settle(); }      // noLoad: the page as it stands once the body script has run, before the load event
  res.hashchange = async h => { loc.hash = h; (ctx.listeners.hashchange || []).forEach(f => f({})); await settle(); };
  res.toggle = async key => { const d = docEl.querySelectorAll('details.fold').find(x => x.attrs['data-fold'] === key); d.open = !d.open; await settle(); return d; };
  res.el = key => docEl.querySelectorAll('details.fold').find(x => x.attrs['data-fold'] === key);
  res.click = async el => { const ev = { target: el }; for (let n = el; n; n = n.parentElement) ((n.l || {}).click || []).forEach(fn => fn(ev)); (doc.listeners.click || []).forEach(l => l.fn(ev)); await settle(); };      // a click bubbling from the element up through its ancestors' listeners to the document's
  return res;
}
const keyOf = k => 'stackshot.fold.' + k;
const PANEL = new Set(data.panel);
(async () => {
  const names = Object.keys(data.pages);
  // defaults: an empty store renders each page as drawn, and writes no choice that differs from it
  out.defaults = {}; out.untouched = {}; out.stored = {};
  for (const n of names) {
    const st = makeStore(false); const r = await load(n, st); const drawn = {};
    parse(data.pages[n]).querySelectorAll('details.fold').forEach(d => drawn[d.attrs['data-fold']] = d.open);
    out.defaults[n] = JSON.stringify(r.folds()) === JSON.stringify(drawn);
    out.untouched[n] = st.log.every(([k, v]) => v === (drawn[k.slice('stackshot.fold.'.length)] ? '1' : '0'));
  }
  // a toggle writes the key and a reload applies it, on each page kind; a panel section and a main-column fold
  out.toggle = {}; out.reload = {}; out.headOnly = {}; out.bodyOnly = {}; out.rest = {}; out.panelShared = {};
  for (const n of names) {
    const st = makeStore(false); const r = await load(n, st);
    const keys = Object.keys(r.folds()); const main = keys.find(k => !PANEL.has(k)); const pan = keys.find(k => PANEL.has(k));
    const picks = [main, pan].filter(Boolean); const before = r.folds(); const want = Object.assign({}, before);
    for (const k of picks) { want[k] = !before[k]; await r.toggle(k); }
    out.toggle[n] = [picks.every(k => st.m.get(keyOf(k)) === (before[k] ? '0' : '1')), !!pan, main || null, pan];
    const r2 = await load(n, st); out.reload[n] = JSON.stringify(r2.folds()) === JSON.stringify(want);
    out.headOnly[n] = JSON.stringify((await load(n, st, { noBody: true })).afterHead) === JSON.stringify(want);
    const rb = await load(n, st, { noHead: true, noObserver: true }); out.bodyOnly[n] = JSON.stringify(rb.folds()) === JSON.stringify(want);
    out.rest[n] = Object.keys(want).filter(k => !picks.includes(k)).every(k => r2.folds()[k] === before[k]);
  }
  // the panel's key holds on every page: close Machines on the first page, every other page kind draws it closed
  {
    const st = makeStore(false); const first = await load(names[0], st); await first.toggle('machines');
    out.panelShared.stored = st.m.get(keyOf('machines')); out.panelShared.pages = {};
    for (const n of names) { const r = await load(n, st); out.panelShared.pages[n] = r.el('machines').open === false && Object.keys(r.folds()).filter(k => PANEL.has(k) && k !== 'machines').every(k => r.folds()[k] === (parse(data.pages[n]).querySelectorAll('details.fold').find(d => d.attrs['data-fold'] === k).open)); }
    const st2 = makeStore(false); const a = await load('item', st2); await a.toggle('projects-panel'); const b = await load('closed', st2);
    out.panelShared.itemToClosed = st2.m.get(keyOf('projects-panel')) === '0' && b.el('projects-panel').open === false;
  }
  // the two kinds and the odd values, on the home page
  {
    const probe = await load('home', makeStore(false)); const f0 = probe.folds();
    const closedSection = Object.keys(f0).find(k => !PANEL.has(k) && !f0[k]), openSection = Object.keys(f0).find(k => !PANEL.has(k) && f0[k] && !k.startsWith('home.'));
    const group = Object.keys(f0).find(k => k.startsWith('home.') && f0[k]);
    out.kinds = { closedSection, openSection, group };
    const st = makeStore(false); st.m.set(keyOf(closedSection), '1'); st.m.set(keyOf(openSection), '0'); if (group) st.m.set(keyOf(group), '0');
    const r = await load('home', st); const f = r.folds();
    out.kinds.closedOpens = f[closedSection] === true; out.kinds.openCloses = f[openSection] === false; out.kinds.groupCloses = group ? f[group] === false : null;
    out.kinds.restDefault = Object.keys(f0).filter(k => ![closedSection, openSection, group].includes(k)).every(k => f[k] === f0[k]);
    const st3 = makeStore(false); st3.m.set(keyOf(closedSection), '0'); st3.m.set(keyOf(openSection), '1'); if (group) st3.m.set(keyOf(group), '1');
    out.kinds.sameAsDefault = JSON.stringify((await load('home', st3)).folds()) === JSON.stringify(f0);
    const st4 = makeStore(false); Object.keys(f0).forEach(k => st4.m.set(keyOf(k), 'maybe')); out.kinds.oddIgnored = JSON.stringify((await load('home', st4)).folds()) === JSON.stringify(f0);
    const st5 = makeStore(true); const r5 = await load('home', st5); out.kinds.throwingKeepsDefaults = JSON.stringify(r5.folds()) === JSON.stringify(f0);
    let threw = false; try { await r5.toggle(closedSection); } catch (e) { threw = true; } out.kinds.throwingToggleOk = !threw && r5.el(closedSection).open === true;
  }
  // the hash: a section, a row inside a closed group (or section), a count's link; it stays, is recorded, and nothing is removed
  {
    const probe = await load('home', makeStore(false)); const f0 = probe.folds();
    const closedSection = Object.keys(f0).find(k => !PANEL.has(k) && !f0[k]);
    const secId = closedSection;      // a main-column section's id is its key
    const st = makeStore(false); st.m.set(keyOf('your-move'), '0'); st.m.set('stackshot.fold.other.page', '1');
    const r = await load('home', st, { hash: '#' + secId });
    out.hash = { opens: r.el(closedSection).open === true, stays: r.win.location.hash === '#' + secId, recorded: st.m.get(keyOf(closedSection)) === '1', yourMoveKept: r.el('your-move').open === false };
    const again = await load('home', st); out.hash.reloadKeepsIt = again.el(closedSection).open === true; out.hash.nothingRemoved = st.m.has('stackshot.fold.other.page') && st.m.get(keyOf('your-move')) === '0';
    out.hash.noRemoveCall = true;
    const pre = await load('home', makeStore(false), { hash: '#' + secId, noLoad: true }); out.hash.opensBeforeLoad = pre.el(closedSection).open === true;
    // a row inside a closed fold
    let target = null, folds = null;
    for (const n of ['home', 'project', 'item']) {
      const t = parse(data.pages[n]); const f = t.querySelectorAll('details.fold');
      for (const d of f) { if (d.open) continue; const row = d.querySelectorAll('li').find(x => x.attrs.id); if (row) { target = [n, row.attrs.id, d.attrs['data-fold']]; break; } }
      if (target) break;
    }
    out.hash.rowTarget = target;
    if (target) { const rr = await load(target[0], makeStore(false), { hash: '#' + target[1] }); out.hash.rowOpens = rr.el(target[2]).open === true;
      const rh = await load(target[0], makeStore(false)); await rh.hashchange('#' + target[1]); out.hash.rowOnHashchange = rh.el(target[2]).open === true; }
    const rc = await load('home', makeStore(false)); await rc.hashchange('#' + closedSection); out.hash.hashchangeOpens = rc.el(closedSection).open === true && rc.win.location.hash === '#' + closedSection;
    const rn = await load('home', makeStore(false), { hash: '#nothing-here' }); out.hash.unknownIgnored = JSON.stringify(rn.folds()) === JSON.stringify(f0);
  }
  // the live swap, run from _LIVE_JS itself: the old block's live state is carried over, a fold the old block did not have gets the stored state, and a swapped-in fold keeps recording
  {
    const st = makeStore(false); st.m.set(keyOf('machines'), '0'); st.m.set(keyOf('grp.new.fold'), '0'); st.m.set(keyOf('grp.new.open'), '1');
    const r = await load('home', st); vm.runInContext(data.swap + ';this.__swap=swap', r.ctx);
    const old = r.docEl.querySelector('#machines'); const parent = old.parentElement;
    await r.toggle('agents-at-work');      // the viewer opens a section the page draws closed (or shuts one drawn open)
    const agentsLive = r.el('agents-at-work').open;
    const fresh = parse(data.pages.home); const nw = fresh.querySelector('#machines');
    const synth = (k, open) => { const d = new El('details', open ? { class: 'fold', 'data-fold': k, open: '' } : { class: 'fold', 'data-fold': k }); d.appendChild(new El('summary', {})); return d; };
    nw.appendChild(synth('grp.new.fold', true)); nw.appendChild(synth('grp.new.open', false));
    out.swap = { before: r.el('machines').open };
    r.ctx.__swap(old, nw); await settle();
    const m = r.el('machines');
    const blk = r.docEl.querySelector('#machines'); out.swap.keepsLive = !!m && m.open === false && blk !== old && blk.parentElement === parent && !old.isConnected;
    out.swap.freshGetsStored = r.el('grp.new.fold').open === false && r.el('grp.new.open').open === true;
    out.swap.storeIntact = st.m.get(keyOf('machines')) === '0' && st.m.get(keyOf('grp.new.fold')) === '0' && st.m.get(keyOf('grp.new.open')) === '1';
    out.swap.otherBlockKept = r.el('agents-at-work').open === agentsLive;
    await r.toggle('machines'); out.swap.keepsRecording = st.m.get(keyOf('machines')) === '1' && r.el('machines').open === true;
    // a block swapped on a page with nothing stored keeps the page's defaults and writes nothing new
    const st2 = makeStore(false); const r2 = await load('home', st2); vm.runInContext(data.swap + ';this.__swap=swap', r2.ctx);
    const n2 = parse(data.pages.home).querySelector('#machines'); const logged = st2.log.length; r2.ctx.__swap(r2.docEl.querySelector('#machines'), n2); await settle();
    out.swap.noStoreNoWrite = st2.log.length === logged && r2.el('machines').open === n2.querySelector('details.fold').open;
  }
  // a stale tab's swap restores the fold's on-screen state without writing: another tab closed it since (stored 0), the swap's restoration toggle fires, and the newer choice stays
  {
    const st = makeStore(false); const r = await load('home', st); vm.runInContext(data.swap + ';this.__swap=swap', r.ctx);
    const wasOpen = r.el('machines').open;      // the panel's Machines renders open and nothing is stored: the tab shows it open
    st.m.set(keyOf('machines'), '0');      // a second tab closes it
    const nw = parse(data.pages.home).querySelector('#machines'); nw.querySelector('details.fold')._open = false;      // the refreshed markup draws it closed, so the carry-over must open it again
    const logged = st.log.length; r.ctx.__swap(r.docEl.querySelector('#machines'), nw); await settle();
    out.stale = { wasOpen, keptOnScreen: r.el('machines').open === true, stored: st.m.get(keyOf('machines')), noWrite: st.log.length === logged };
    await r.toggle('machines'); const afterClose = st.m.get(keyOf('machines')); await r.toggle('machines');
    out.stale.laterTogglesRecord = afterClose === '0' && st.m.get(keyOf('machines')) === '1' && r.el('machines').open === true;
  }
  // the same-hash click on a count card reopens its closed section, on the cards the page drew and on the cards a live swap put in their place
  {
    const st = makeStore(false); const r = await load('home', st, { hash: '#waiting-list' }); vm.runInContext(data.swap + ';this.__swap=swap', r.ctx);
    const card = () => r.docEl.querySelectorAll('a.hcard').find(a => a.attrs.href === '#waiting-list');
    out.card = { hasCard: !!card(), opensOnLoad: r.el('waiting-list').open === true };
    await r.toggle('waiting-list'); const closed1 = r.el('waiting-list').open === false;
    await r.click(card()); out.card.firstClickReopens = closed1 && r.el('waiting-list').open === true;
    const oldCounts = r.docEl.querySelector('#counts'); const nw = parse(data.pages.home).querySelector('#counts'); r.ctx.__swap(oldCounts, nw); await settle();
    const swapped = r.docEl.querySelector('#counts') !== oldCounts && !oldCounts.isConnected;
    await r.toggle('waiting-list'); const closed2 = r.el('waiting-list').open === false;
    await r.click(card()); out.card.afterSwapReopens = swapped && closed2 && r.el('waiting-list').open === true && card().parentElement === r.docEl.querySelector('#counts');
    // a card whose hash is not the current one is left to the browser: its click opens nothing by itself
    await r.toggle('waiting-list'); const other = r.docEl.querySelectorAll('a.hcard').find(a => a.attrs.href === '#your-move'); const ym = r.el('your-move').open; r.win.location.hash = '#waiting-list';
    await r.click(other); out.card.otherLeftAlone = r.el('waiting-list').open === false && r.el('your-move').open === ym;
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""
if not shutil.which("node"):
    check("node is available for the fold simulation", False)
else:
    live = r2._LIVE_JS
    swap_src = live[live.index("function swap(o,n){"):live.index("function apply(t)")]
    head_js = FH[len("<script>"):-len("</script>")]
    payload = json.dumps({"pages": html, "head": head_js, "fold": FJ, "swap": swap_src, "panel": sorted(PANEL_KEYS)})
    sp = subprocess.run(["node", "-e", SIM], input=payload, capture_output=True, text=True, timeout=120)
    if sp.returncode != 0:
        check("the fold simulation runs in node", False, sp.stderr[-900:])
    else:
        o = json.loads(sp.stdout)
        pg = [n for n, _p in PAGES]
        check("untouched: an empty store draws every page as the page renders it", all(o["defaults"][n] for n in pg), o["defaults"])
        check("untouched: a page nobody touched writes no choice that differs from the page's own defaults", all(o["untouched"][n] for n in pg), o["untouched"])
        check("a toggle writes the key (1 open, 0 closed), for a main-column fold and a side-panel section, on every page",
              all(o["toggle"][n][0] and o["toggle"][n][1] for n in pg), o["toggle"])
        check("a reload applies what was left, on every page: the two folds as left, every other fold at its default", all(o["reload"][n] and o["rest"][n] for n in pg), (o["reload"], o["rest"]))
        check("the head script alone applies the stored state before the first paint (nothing waits for the body script)", all(o["headOnly"][n] for n in pg), o["headOnly"])
        check("the body script alone applies it too (a browser without MutationObserver)", all(o["bodyOnly"][n] for n in pg), o["bodyOnly"])
        check("the panel's choice is one key per section: closed on one page, closed on every other page kind (and the other panel sections as drawn)",
              o["panelShared"]["stored"] == "0" and all(o["panelShared"]["pages"].values()) and o["panelShared"]["itemToClosed"], o["panelShared"])
        k = o["kinds"]
        check("a section fold (drawn closed) opens on a stored 1; a section drawn open closes on a stored 0; a scope group (drawn open) closes on a stored 0; every other fold keeps its default",
              k["closedOpens"] and k["openCloses"] and k["groupCloses"] is True and k["restDefault"], k)
        check("a stored value that matches the drawn default, or is neither 1 nor 0, changes nothing", k["sameAsDefault"] and k["oddIgnored"], k)
        check("storage that throws (a private window) leaves the page as drawn, and a toggle then still works and throws nothing", k["throwingKeepsDefaults"] and k["throwingToggleOk"], k)
        hh = o["hash"]
        check("a hash to a section opens it on load, stays in the address and is recorded, so a reload without it shows it still open; the other folds and keys are untouched",
              hh["opens"] and hh["stays"] and hh["recorded"] and hh["reloadKeepsIt"] and hh["yourMoveKept"] and hh["nothingRemoved"], hh)
        check("a hash to a row inside a closed fold opens that fold, on load and on hashchange", hh["rowTarget"] is not None and hh.get("rowOpens") and hh.get("rowOnHashchange"), hh)
        check("a hashchange to a section opens it and keeps the hash; a hash that names nothing changes nothing", hh["hashchangeOpens"] and hh["unknownIgnored"], hh)
        check("a hash opens its section as soon as the body script has run, before the load event (not only after the page has loaded)", hh["opensBeforeLoad"], hh)
        sw = o["swap"]
        check("the live swap (the real function from _LIVE_JS): the old block's on-screen state is kept, a fold the old block did not have gets its stored state, the store is unchanged, other blocks are left alone",
              sw["keepsLive"] and sw["freshGetsStored"] and sw["storeIntact"] and sw["otherBlockKept"], sw)
        check("after a swap a toggle of the swapped-in fold is recorded (the delegated listener), and a swap with nothing stored writes nothing", sw["keepsRecording"] and sw["noStoreNoWrite"], sw)

        st_ = o["stale"]
        check("a swap that restores a fold from a stale on-screen value writes nothing: a second tab's stored 0 stays 0 after the restoration's toggle fires, the fold stays as the viewer sees it, and a later toggle records again",
              st_["wasOpen"] and st_["keptOnScreen"] and st_["stored"] == "0" and st_["noWrite"] and st_["laterTogglesRecord"], st_)
        cd_ = o["card"]
        check("a count card whose hash is the current one reopens its closed section on click, on the cards as drawn and on the cards a live swap put in their place (one delegated handler); another card is left to the browser",
              cd_["hasCard"] and cd_["opensOnLoad"] and cd_["firstClickReopens"] and cd_["afterSwapReopens"] and cd_["otherLeftAlone"], cd_)

# ---- 3. nothing deletes a stored fold key
def sources():
    for root in (pathlib.Path(STACK, "stackshot"), pathlib.Path(STACK, "shared")):
        if root.exists():
            for f in root.rglob("*"):
                if f.suffix in (".py", ".js", ".html") and f.is_file(): yield f
rm = [str(f.relative_to(STACK)) for f in sources() if re.search(r"""removeItem\(\s*['"]stackshot\.fold|localStorage\.clear|\bstackshot\.fold\.['"]\s*\+\s*\w+\s*\)\s*\)""", f.read_text(encoding="utf-8", errors="replace"))]
check("no script of the board removes or clears a stored fold key (a stored choice is kept until the viewer changes it)", rm == [] and "removeItem" not in FJ and "removeItem" not in FH and "localStorage" not in r2._LIVE_JS, rm)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
