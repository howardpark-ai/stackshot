"""Scenario test for the page explainers: text that says what a section is or how something works sits behind the one "?" control (ui/explain.py), never on the page itself.
Fixture data, the pages through Starlette's test client and the board's renderers, no live store, no network. People and addresses are made up.

The script runs in node against a small fake document built from the component's own markup; no browser runs here, so the drawn layout is tests/explain_check.py's, which CI runs.

Covers:
  * the markup: the button's name and state, its description pointing at the popup, the text and the name escaped, in the request's language;
  * every page with the board's chrome carries the script once and the style, and no two explainers on a page share a key;
  * the script: a tap opens and a second tap closes; hover opens and leaving closes, unless a click pinned it; keyboard focus opens and tabbing away closes; Escape closes it
    and nothing else, and leaves Escape alone when nothing is open; a tap outside closes; one is open at a time; the popup stays inside the window and inside a clipping
    ancestor, and goes above the button when there is no room below; an open popup survives the home page's in-place update;
  * the explainers that left the pages (MOVED, one row per "?"): each is in its popup, and no page drawn here shows any of them outside a popup. A new explainer gets a row.

    tests/run-suite explain        → exit 0 / 1"""
import datetime, html, json, logging, os, pathlib, re, shutil, subprocess, sys, time
from html.parser import HTMLParser

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="xpl-"); T = pathlib.Path(tmp)
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
A = "22222222-2222-4222-8222-222222222222"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
now0 = time.time()
def item(i, subject, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "- A thing\n- It lives here\n- Finished when it works", "status": status,
        "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step", **meta}}))
item(1, "[work] item one")
DAY = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
LINES = [{"kind": "time", "until": DAY(3)}, {"kind": "relay", "event": "the lease"}]
def waiting(i, **meta): item(i, f"[work] item {i}", hold=True, needs=[], post_wake_mover="alpha-main", **meta)
for i, mode in ((2, "all"), (3, "any")): waiting(i, wait_kind="list", wait_mode=mode, until=DAY(5), waits=LINES, watch={"set_at": now0 - 3600})
waiting(4, wait_kind="relay", ask_by=DAY(5), wait_event="the lease", party="the landlord", chases=[{"at": now0 - 600, "by": "alpha-main", "note": "asked again"}])
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

from stackshot.web import search
from stackshot.web import server
from stackshot.web import i18n
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.ui import explain as xp
from stackshot.web.ui import render as r2
from stackshot.web.ui import runners as ui_runners
from stackshot.anchors import anchors as _anc
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))


class Tree(HTMLParser):
    """Markup as nested {tag, attrs, text, kids}: what the node half builds its fake elements from."""
    VOID = {"meta", "link", "input", "br", "img", "hr", "col", "source", "path", "circle"}
    def __init__(self, s):
        super().__init__(); self.root = {"tag": "#root", "attrs": {}, "text": "", "kids": []}; self.open = [self.root]; self.feed(s); self.close()
    def handle_starttag(self, tag, attrs):
        n = {"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "text": "", "kids": []}; self.open[-1]["kids"].append(n)
        if tag not in self.VOID: self.open.append(n)
    def handle_startendtag(self, tag, attrs): self.open[-1]["kids"].append({"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "text": "", "kids": []})
    def handle_endtag(self, tag):
        for i in range(len(self.open) - 1, 0, -1):
            if self.open[i]["tag"] == tag: del self.open[i:]; break
    def handle_data(self, data): self.open[-1]["text"] += data

# ---- 1. the markup
m = xp.explain("a-b", 'Says <b> "how" & why.', 'The "<list>"')
t = Tree(m).root["kids"]
w = t[0] if t else {"attrs": {}, "kids": []}
btn, pop = (w["kids"] + [{"attrs": {}, "kids": [], "text": "", "tag": ""}] * 2)[:2]
check("one wrapper keyed by the explainer, holding the button and the popup", len(t) == 1 and w["attrs"] == {"class": "xp", "data-xp": "a-b"} and [btn["tag"], pop["tag"]] == ["button", "span"] and len(w["kids"]) == 2, m)
check("the button: type=button, named for what it explains, closed, controlling and described by the popup, its ? hidden from a screen reader",
      btn["attrs"] == {"type": "button", "class": "xp-b", "id": "xpb-a-b", "aria-label": 'About The "<list>"', "aria-expanded": "false", "aria-controls": "xp-a-b", "aria-describedby": "xp-a-b"}
      and [(k["tag"], k["attrs"], k["text"]) for k in btn["kids"]] == [("span", {"aria-hidden": "true"}, "?")], btn)
check("the popup: a hidden, focusable tooltip holding the text as text", pop["attrs"] == {"class": "xp-pop", "id": "xp-a-b", "role": "tooltip", "tabindex": "-1", "hidden": ""}
      and pop["text"] == 'Says <b> "how" & why.' and not pop["kids"], pop)
check("no bare title attribute: the text is in the page", "title=" not in m, m)
(T / "loc").mkdir()
(T / "loc/ko.json").write_text(json.dumps({"explain.about": "[x:About {what}]"}), encoding="utf-8")
from stackshot.core import config as _cfg
_cfg.CFG.setdefault("ui", {})["locale_dir"] = str(T / "loc")
with i18n.use("ko"): mk = xp.explain("k", "text", "Thing")
_cfg.CFG["ui"].pop("locale_dir")
check("the button's name is in the request's language", 'aria-label="[x:About Thing]"' in mk, mk)
check("a heading and its explainer sit side by side: the button is not inside the heading", xp.head("<h2>Runs</h2>", m).startswith('<div class="xp-head xp-h2"><h2>Runs</h2><span class="xp"') and xp.head("<h2>Runs</h2>", m).endswith("</span></div>"))
check("the line takes the heading's level, a heading with a class too", xp.head('<h1>T</h1>', m).startswith('<div class="xp-head xp-h1">') and xp.head('<h2 class="lsec">T</h2>', m).startswith('<div class="xp-head xp-h2">'))

# ---- 2. every page carries the script and the style
PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("projects", "/projects"), ("closed", "/closed"), ("audits", "/audits"), ("search", "/search?q=item"),
         ("runners", "/runners"), ("probe", "/probe/sala-link")]
pages = {}
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    for n, p in PAGES:
        r = c.get(p, headers={"host": "board.example.org"})
        pages[n] = r.text
        check(f"{n}: drawn", r.status_code == 200, (r.status_code, r.text[:300]))
for n, h in pages.items():
    check(f"{n}: the explainer script once, at the end of the body, and its style", h.count(xp.SCRIPT) == 1 and h.find(xp.SCRIPT) > h.rfind("</main>") and ".xp-pop[hidden]{display:none}" in h, h.count(xp.SCRIPT))
    keys = re.findall(r'<span class="xp" data-xp="([^"]*)"', h)
    check(f"{n}: no two explainers share a key", len(keys) == len(set(keys)), keys)

# ---- 3. what left the pages stays off them
# the "?" (its key; "/…" tells two states of one key apart) -> the catalog keys of the text it holds, and the drawn page that shows it
MOVED = {"projects": ("projects", ["projects.note"]), "closed-new": ("closed", ["closed.new_help"]), "closed-last14": ("closed", ["closed.last14_note"]),
         "audit-groups": ("audits", ["audit.groups_help", "audit.note_logged"]), "audit-runs": ("audits", ["audit.runs_hint"]),
         **{f"audit-group-{k[len('audit.desc.'):]}": ("audits", [k]) for k in i18n.EN if k.startswith("audit.desc.")},
         "runners": ("runners, in use", ["runners.sub", "runners.checks"]), "routing": ("project", ["routing.help_pilot"]), "routing/plain": ("project, not ruled", ["routing.help_plain"]),
         "wait-list": ("item, all of a list", ["wait.list.help_all"]), "wait-list/any": ("item, any of a list", ["wait.list.help_any"]),
         "wait-backstop": ("item, all of a list", ["wait.list.help_backstop"]), "wait-chases": ("item, a relay wait", ["wait.chase_help"])}
def board(): return r2.Board(str(T / "store"))
drawn = dict(pages)
drawn["item, all of a list"] = board().item_html("a2"); drawn["item, any of a list"] = board().item_html("a3"); drawn["item, a relay wait"] = board().item_html("a4")
real_root, real_enabled = _anc.pilot_root, ui_runners.enabled
try:
    _anc.pilot_root = lambda *a, **k: ""
    drawn["project, not ruled"] = board().routing_html("projects/alpha")
    ui_runners.enabled = lambda: True      # a board with runners, before the first read: nothing is read from GitHub
    drawn["runners, in use"] = ui_runners.page_html(board(), {"ts": 0, "errors": {}, "failed": [], "runners": [], "switch": {}, "stale": False, "pending": True, "refreshing": False, "age_s": 0})
finally:
    _anc.pilot_root, ui_runners.enabled = real_root, real_enabled
POP = re.compile(r'<span class="xp-pop" id="xp-([^"]*)"[^>]*>([^<]*)</span>')
def inline(h):
    """The words a page draws outside every popup (and outside its style and scripts)."""
    h = POP.sub(" ", re.sub(r"(?s)<(style|script)[^>]*>.*?</\1>", " ", h))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
def said(key): return ".+?".join(re.escape(part) for part in re.split(r"\{[a-z_]+\}", i18n.EN[key]))      # the English text, any value in each of its fields
for row, (where, keys) in MOVED.items():
    pops = {k: html.unescape(v) for k, v in POP.findall(drawn[where])}
    text = pops.get(row.split("/")[0], "")
    check(f'{row}: its text is behind its "?" ({where})', all(re.search(said(k), text) for k in keys), (keys, sorted(pops), text))
    for k in keys:
        back = [n for n, h in drawn.items() if re.search(said(k), inline(h))]
        check(f"{row}: {k} is drawn outside a popup on no page", not back, back)
check("an empty New section still says so on the page", i18n.EN["closed.new_none"] in inline(pages["closed"]), inline(pages["closed"])[:600])
_had = dict(_cfg.CFG.get("audit", {})); _cfg.CFG.setdefault("audit", {})["pattern_review"] = "off"
try:
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c: off = c.get("/audits", headers={"host": "board.example.org"}).text
finally:
    _cfg.CFG["audit"].clear(); _cfg.CFG["audit"].update(_had)
check("a findings log that is off is a warning, so it stays on the page", i18n.EN["audit.note_log_off"] in inline(off) and 'id="xp-audit-groups"' in off, inline(off)[:600])

# ---- 4. the script, in node
HARNESS = r"""
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const [js, tree] = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let active = null, timers = [];
const listeners = {};
class El {
  constructor(tag, attrs) { this.tagName = tag.toUpperCase(); this.attrs = attrs || {}; this.kids = []; this.parentElement = null; this.style = {}; this.rect = {left: 0, top: 0, width: 0, height: 0};
    this.hidden = 'hidden' in this.attrs; this.overflowX = 'visible'; this.keyboard = false; }
  add(k) { k.parentElement = this; this.kids.push(k); return k; }
  get classList() { const c = (this.attrs.class || '').split(' '); return {contains: x => c.includes(x)}; }
  get firstElementChild() { return this.kids[0]; }
  get lastElementChild() { return this.kids[this.kids.length - 1]; }
  get isConnected() { for (let n = this; n; n = n.parentElement) if (n === html) return true; return false; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  contains(n) { for (; n; n = n.parentElement) if (n === this) return true; return false; }
  closest(s) { assert(s[0] === '.', s); for (let n = this; n; n = n.parentElement) if (n.classList.contains(s.slice(1))) return n; return null; }
  matches(s) { assert(s === ':focus-visible', s); return this.keyboard; }
  focus() { if (active === this) return; const was = active; active = this; if (was) fire('focusout', was, {relatedTarget: this}); fire('focusin', this); }
  get offsetWidth() { const m = parseFloat(this.style.maxWidth); return Math.min(isNaN(m) ? 1e9 : m, 320); }
  get offsetHeight() { return 60; }
  getBoundingClientRect() { const r = this.rect; return {left: r.left, top: r.top, width: r.width, height: r.height, right: r.left + r.width, bottom: r.top + r.height}; }
}
const html = new El('html'), body = html.add(new El('body'));
html.clientWidth = 360;
const walk = (n, f) => { f(n); n.kids.forEach(k => walk(k, f)); };
const document = {documentElement: html, body, get activeElement() { return active || body; },
  querySelector(s) { const m = /^\.xp\[data-xp="([^"]*)"\]$/.exec(s); assert(m, s); let got = null; walk(html, n => { if (!got && n.classList.contains('xp') && n.attrs['data-xp'] === m[1]) got = n; }); return got; },
  addEventListener(t, f, cap) { (listeners[t] = listeners[t] || []).push([f, !!cap]); }};
const winl = {};
const window = {innerHeight: 700, getComputedStyle: n => ({overflowX: n.overflowX}), addEventListener(t, f) { winl[t] = f; }};
function fire(type, target, props) {
  let stopped = false, prevented = false;
  const e = Object.assign({type, target, preventDefault() { prevented = true; }, stopPropagation() { stopped = true; }}, props || {});
  const l = listeners[type] || [];
  for (const cap of [true, false]) { for (const [f, c] of l) if (c === cap) f(e); if (stopped) break; }
  return {prevented, stopped};
}
const flush = () => { const t = timers; timers = []; t.forEach(f => f()); };
function build(n, into) { const e = into.add(new El(n.tag, Object.assign({}, n.attrs))); n.kids.forEach(k => build(k, e)); return e; }
function make(key, left, top, into) {
  const t = JSON.parse(JSON.stringify(tree).split('KEY').join(key)), w = build(t, into || body);
  w.rect = {left, top, width: 36, height: 36}; w.firstElementChild.rect = {left, top, width: 36, height: 36}; return w;
}
let panelEscapes = 0;
const sb = {document, window, setTimeout: f => timers.push(f), String, Math, isNaN, parseFloat};
vm.createContext(sb); vm.runInContext(js, sb);
document.addEventListener('keydown', e => { if (e.key === 'Escape') panelEscapes++; });      // the side panel's own Escape, a bubbling listener as in the page
const out = {};
const check = (name, ok, got) => { out[name] = ok ? true : String(JSON.stringify(got)); };
const A = make('a', 100, 100), B = make('b', 300, 100), outside = body.add(new El('div', {}));
const state = w => [w.lastElementChild.hidden, w.firstElementChild.attrs['aria-expanded']];
const open = w => !w.lastElementChild.hidden && w.firstElementChild.attrs['aria-expanded'] === 'true';
const shut = w => w.lastElementChild.hidden && w.firstElementChild.attrs['aria-expanded'] === 'false';
const glyph = w => w.firstElementChild.firstElementChild;
const over = (w, from, kind) => fire('pointerover', glyph(w), {pointerType: kind || 'mouse', relatedTarget: from || outside});
const leave = (w, to, kind) => fire('pointerout', glyph(w), {pointerType: kind || 'mouse', relatedTarget: to || outside});
function tap(w) {      // a finger: the pointer events, then the focus some browsers give a tapped button (never keyboard focus), then the click
  const b = w.firstElementChild; over(w, outside, 'touch'); b.keyboard = false; b.focus(); fire('pointerup', glyph(w), {pointerType: 'touch'}); leave(w, outside, 'touch'); return fire('click', glyph(w));
}
const away = () => { fire('pointerup', outside, {pointerType: 'touch'}); if (active) { const was = active; active = null; fire('focusout', was, {relatedTarget: null}); } flush(); };
const esc = (props) => fire('keydown', document.activeElement, Object.assign({key: 'Escape'}, props || {}));

check('starts closed', shut(A) && shut(B), state(A));
over(A, outside, 'touch'); check('a touch passing over opens nothing', shut(A), state(A)); leave(A, outside, 'touch');
const first = tap(A); flush(); check('a tap opens', open(A), state(A)); check('...and does nothing else (inside a link or a summary)', first.prevented, first);
tap(A); flush(); check('a second tap closes', shut(A), state(A));
tap(A); fire('pointerup', A.lastElementChild, {}); A.lastElementChild.focus(); flush(); check('a tap on the popup keeps it', open(A), state(A));
away(); check('a tap outside closes', shut(A), state(A));
tap(A); fire('pointerup', outside, {}); check('...also with the focus nowhere near (a browser that does not focus a tapped button)', shut(A), state(A)); away();

over(A); check('the mouse over it opens', open(A), state(A));
leave(A, A.lastElementChild); check('...and moving onto the popup keeps it', open(A), state(A));
leave(A); check('...and leaving closes', shut(A), state(A));
over(A); fire('click', glyph(A)); leave(A); check('a click pins it: leaving keeps it', open(A), state(A));
over(A); leave(A); check('...and passing over again does not unpin it', open(A), state(A));
over(A); fire('click', glyph(A)); check('...a second click closes it', shut(A), state(A));
over(A, glyph(A)); check('...and moving within the button does not reopen it', shut(A), state(A)); leave(A);

A.firstElementChild.keyboard = true; A.firstElementChild.focus(); check('keyboard focus opens', open(A), state(A));
fire('click', A.firstElementChild); check('...Enter (a click) keeps it open, pinned', open(A), state(A));
fire('click', A.firstElementChild); check('...Enter again closes', shut(A), state(A));
active = null; A.firstElementChild.focus(); active = outside; fire('focusout', A.firstElementChild, {relatedTarget: outside}); flush(); check('tabbing away closes', shut(A), state(A)); active = null;

A.firstElementChild.focus(); const e1 = esc(); check('Escape closes it', shut(A), state(A)); check('...and nothing else hears that Escape', e1.stopped && e1.prevented && panelEscapes === 0, [e1, panelEscapes]);
const e2 = esc(); check('with nothing open, Escape goes on to the page', !e2.stopped && !e2.prevented && panelEscapes === 1, [e2, panelEscapes]);
fire('click', A.firstElementChild); const e3 = esc({isComposing: true}); check('an Escape that cancels an input method composition is left alone', open(A) && !e3.stopped, state(A));
A.lastElementChild.focus(); A.firstElementChild.keyboard = true; esc(); flush(); check('Escape from inside the popup closes it and puts the focus on its button, without reopening it', shut(A) && active === A.firstElementChild, [state(A), active && active.tagName]); away();

tap(A); tap(B); check('one is open at a time', shut(A) && open(B), [state(A), state(B)]); away();
tap(A); over(B); check('...also when the next one opens on hover', shut(A) && open(B), [state(A), state(B)]); leave(B); away();

// where the popup goes: the wrapper's left plus the popup's own offset is its place in the window
const at = w => ({left: w.rect.left + parseFloat(w.lastElementChild.style.left), top: w.rect.top + parseFloat(w.lastElementChild.style.top), width: w.lastElementChild.offsetWidth});
for (const [name, x] of [['left', 0], ['middle', 160], ['right', 324]]) {
  const w = make('p-' + name, x, 100); tap(w); const p = at(w);
  check('at 360 px the popup of a button at the ' + name + ' stays inside the window, under the button', p.left >= 8 && p.left + p.width <= 352 && p.width === 320 && p.top === 136, p); away(); }
html.clientWidth = 280; const N = make('narrow', 200, 100); tap(N); check('a narrower window narrows the popup', at(N).left === 8 && at(N).width === 264, at(N)); away();
html.clientWidth = 1280; const M = make('mid', 600, 100); tap(M); check('with room, it is centered under the button', at(M).left === 458, at(M));
M.rect.left = 1240; M.firstElementChild.rect.left = 1240; winl.resize(); check('a resize places it again', at(M).left === 952, at(M)); away();
const low = make('low', 100, 660); tap(low); check('near the bottom it goes above the button', at(low).top === 600, at(low)); away();
const clip = body.add(new El('div', {})); clip.overflowX = 'auto'; clip.rect = {left: 1000, top: 0, width: 280, height: 700};
const C = make('clipped', 1010, 100, clip); tap(C); check('inside an ancestor that clips, it stays inside that', at(C).left === 1008 && at(C).width === 264, at(C)); away();

// the in-place update: the block holding the open explainer is replaced by a fresh copy
const block = body.add(new El('section', {})); let S = make('s', 100, 100, block);
function swap(keep) {
  const had = active && block.contains(active); const old = block.kids.pop();
  if (had) { const was = active; fire('focusout', was, {relatedTarget: null}); active = null; }      // a browser may say focusout while it removes the focused node
  old.parentElement = null; let fresh = null; if (keep) { fresh = make('s', 100, 100, block); if (had) { fresh.firstElementChild.keyboard = false; fresh.firstElementChild.focus(); } }
  fire('stackshot:swapped', body); flush(); return fresh; }
tap(S); S = swap(true); check('an open popup survives the in-place update, placed again', open(S) && S.lastElementChild.style.top === '36px', state(S));
leave(S); check('...still pinned', open(S), state(S));
tap(S); check('...and a tap still closes it', shut(S), state(S)); away();
S = swap(true); check('a closed one stays closed through an update', shut(S), state(S));
S.firstElementChild.keyboard = true; S.firstElementChild.focus(); S = swap(true); check('one opened by the keyboard survives it too, with the focus', open(S) && active === S.firstElementChild, state(S)); away();
tap(S); swap(false); const n0 = panelEscapes; esc(); check('an explainer the update removed is forgotten: Escape goes on to the page', panelEscapes === n0 + 1, panelEscapes - n0);
process.stdout.write(JSON.stringify(out));
"""
if shutil.which("node"):
    tree = Tree(xp.explain("KEY", "text", "Thing")).root["kids"][0]
    (T / "h.js").write_text(HARNESS, encoding="utf-8"); (T / "in.json").write_text(json.dumps([xp.JS, tree]), encoding="utf-8")
    nr = subprocess.run(["node", str(T / "h.js"), str(T / "in.json")], capture_output=True, text=True, timeout=60)
    try: res = json.loads(nr.stdout)
    except ValueError: res = None
    check("node ran the explainer script", res is not None and len(res) >= 30, (nr.stdout[:300], nr.stderr[-1500:]))
    for name, ok in (res or {}).items(): check(f"script: {name}", ok is True, ok)
else:
    check("node is available for the script's checks", False)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed", flush=True)
os._exit(1 if fails else 0)
