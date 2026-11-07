"""Scenario test for the color tool: the shared source shared/colortool.js, stackshot's side of it (ui/colortool.py, hooked into ui/render.py's _APP_HEAD and _FAB_PAIR, with the mount in the side panel) and the pages
rendered straight from the Board, no server, no network, no browser (the library runs in node over a stub page where node is installed; the button and the panel in a browser are tests/phone_width_check.py's).

The tool lets the person who uses the board try a whole dark color combination: 14 fields (page background, cards, lines, body text, muted text, text and links, button outlines, solid fills, text on solid fills, disabled fill and text,
small label fill, text and outline), five presets, and saved combinations, in THIS browser (the applied look) and on the server (the saved list). Covers:
  * the pages: on each of the nine pages the board serves (home, an item page, a project page, Projects, Closed and its second page, Search with and without a query, Runners) the library is inline once, verbatim, in the head
    after the theme script and before the page's own first style, with the settings and the call that applies the stored look; the init call is at the end of the body; the mount is one empty element at the end of the side panel;
    the markup of the tool itself is drawn by the script, never by the server;
  * the shared source: its first line is the version line, ColorTool.version is that number, no templating placeholder, no closing tag or comment opener (it is inlined in a script element), no name of an app, a person or a machine,
    a header that says it is shared and pinned as a verbatim copy; stackshot inlines the file's text and nothing else;
  * the requests: the library has one fetch, to the saved list's address from the page's own origin (the address comes from the settings), a GET or a POST of JSON and nothing else; no cookie, no form, no link; one localStorage key and
    every call on it; applyStored and init make no request in node; no other file names the tool;
  * the fields: resolve() (nothing set is exactly the shipped dark theme; Cards and Lines follow a set background by 4% and 10% of the body text, a field set wins, nothing is derived at the shipped background), norm() (invalid, shipped and
    default values dropped), apply() (the custom properties and classes each field sets, in node over a stub page; Live now and a saved copy of it apply nothing; the status colors and --orange are never set); the dark theme only;
  * the rules: the label rule covers every shipped selector that paints the orange label (and fails loudly when a new one appears), the disabled rule covers every shipped disabled button look it replaces (opacity gone, busy and pressed kept)
    and nothing else, and no shipped rule is edited;
  * the contrast gate, recomputed with tests/_colors.py in Python and compared with the library's own numbers: every preset passes every REFUSE pair, the WARN list of each preset is exactly the expected one (Live now: the shipped idle Send's
    disabled pair; Radix: its white label), the edge of the background gate (#303030 passes, #313131 is refused) and, for every background that passes it, all six REFUSE pairs; a stored value that fails the gate is cleared at load;
  * a second app: the same file with other settings (its own storage key, property names, shipped values given by a function, onApply, isDark, no saved list and no preview, and the "warn" gate) in the same node page as stackshot's: its
    look is applied under its own names, Reset and Live now take off everything set through onApply too, onApply runs on every apply (stored = {} included) after the tracked properties were removed, a function for the shipped values is
    called on every apply and never cached, isDark is asked on every apply and at init, the "warn" gate turns the REFUSE pairs into warnings with their ratio and never refuses, stores no refusal and never clears a stored look, and the
    two apps do not touch each other's properties;
  * what the tests of the other files rely on: the pages without the tool's script blocks (tests/_colors.py without_colortool) carry none of the preset colors, and no source file names the retired temporary feature.

    tests/run-suite color_trial        → exit 0 / 1"""
import json, logging, math, os, pathlib, re, shutil, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch, _instance, _colors as C

tmp = _scratch.mkdtemp(prefix="colortool-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
HERE = "00000000-0000-4000-8000-000000000001"
now = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
def item(i, subject, status="open", **meta):
    su = now - 3 * H
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A thing. It lives here.", "status": status, "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": HERE, "project": "projects/alpha", **meta}}))
item(1, "[home] ask with options", needs=["decision"], ask="Decide: whether to ship · Recommend: ship · Stakes: none · By: no date",
     options=[{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}], mover="Oliver", then="home-other", next="Oliver: decide")
item(3, "[home] agent item", mover="home-other", next="home-other: x", needs=["home-other"])
item(5, "[home] closed one", status="completed", outcome="done", reason="shipped", mover=None)
(T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from ui import render, search as s2, runners as n2, colortool as ct, kit
import search as sm
Bd = lambda: render.Board(f"{tmp}/store", now=None)
sm.sync(Bd())
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
SNAP = {"ts": now, "errors": {}, "failed": [], "runners": [{"box": "box-a", "repo": "acme/widget", "state": "idle", "name": "box-a-1", "kind": "", "reason": "", "job": None}]}
PAGES = {"home": Bd().html(), "item": Bd().item_html("a1", answer=BOX), "project": Bd().routing_html("projects/alpha"), "Projects": Bd().projects_html(), "Closed": Bd().landed_html(),
         "Closed (page 2)": Bd().landed_html(page=2), "Search": s2.results_html(Bd(), "item"), "Search (no query)": s2.results_html(Bd(), ""), "Runners": n2.page_html(Bd(), SNAP)}

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

LIB = pathlib.Path(STACK, "shared", "colortool.js").read_text(encoding="utf-8")
SRCT = {p: pathlib.Path(STACK, p).read_text(encoding="utf-8") for p in ("ui/colortool.py", "ui/render.py", "README.md", "deploy.sh")}
m_css = re.search(r"var CSS = \[(.*?)\]\.join\('\\n'\);", LIB, re.S)
CSS_LIB = "\n".join(re.findall(r"'((?:[^'\\]|\\.)*)'", m_css.group(1))) if m_css else ""

# ---- 1. the shared source
check("the file starts with its version line, /* colortool v2 */, and ColorTool.version is that number", LIB.split("\n", 1)[0] == "/* colortool v2 */" and "var VERSION = 2;" in LIB and "version: VERSION" in LIB, LIB[:40])
check("the file has no templating placeholder (no __NAME__ to fill in), no closing tag and no comment opener (it is inlined in a script element)", not re.search(r"__[A-Za-z0-9]+__", LIB) and "</" not in LIB and "<!--" not in LIB)
# the words a shared file must not carry: the apps that pin a copy, and a person and machines of the fixtures
NAMES = re.compile("|".join(["stackshot", "salamander", r"\bsala\b", "oliver", r"\bbox-[a-z]\b"]), re.I)
check("the file names no app, person or machine (it is one source for more than one app)", not NAMES.search(LIB), NAMES.findall(LIB)[:3])
hdr = LIB[:LIB.index("(function () {")]
check("its header says it is the shared source, that another app pins a verbatim copy, that it changes only with a version bump and its consumers are told; it lists the entries and every cfg field",
      "SHARED SOURCE" in hdr and "VERBATIM" in hdr and "version bump" in hdr and "tell the apps that pin a copy" in hdr and all(w in hdr for w in ("applyStored(cfg)", "init(cfg)", "remount(mount", "engine(cfg)"))
      and all(re.search(rf"^ \*   {f}\s", hdr, re.M) for f in ("storageKey", "shipped", "vars", "onApply", "isDark", "gate", "css", "mount", "preview", "api")), hdr[:300])
check("the file defines window.ColorTool with version, applyStored, init, remount and engine, and nothing else on window", re.search(r"window\.ColorTool = \{\s*version: VERSION,\s*applyStored:.*?init:.*?remount:.*?engine:", LIB, re.S) is not None and LIB[len(hdr):].count("window.ColorTool") == 1)
check("stackshot inlines the file's text, whole and unchanged, and nothing of the tool is written in ui/colortool.py (it reads the file)", ct.LIB == LIB and ct.LIB in ct.HEAD and "shared" in SRCT["ui/colortool.py"] and "colortool.js" in SRCT["ui/colortool.py"]
      and "applyStored" not in SRCT["ui/colortool.py"].split('"""', 2)[2].replace("ColorTool.applyStored(window.stackshotColors)", ""), None)
check("deploy.sh restarts the server for a change under shared/ (the file is read at import)", re.search(r"^\s*shared/\*\) server=1 ;;", SRCT["deploy.sh"], re.M) is not None)
import ast
imports = sorted(n.names[0].name for n in ast.parse(SRCT["ui/colortool.py"]).body if isinstance(n, ast.Import)) + sorted(n.module for n in ast.parse(SRCT["ui/colortool.py"]).body if isinstance(n, ast.ImportFrom))
check("ui/colortool.py parses and imports only json, pathlib and the board's address helper (ui.under)", imports == ["json", "pathlib", "ui"], imports)

# ---- 2. the markup on every page
check("the page set is the board's: home, an item page, a project page, Projects, Closed (two pages), Search (with and without a query), Runners", len(PAGES) == 9 and all(len(p) > 5000 for p in PAGES.values()), {k: len(v) for k, v in PAGES.items()})
for nm, pg in PAGES.items():
    head, body = pg.split("</head>", 1)
    check(f"{nm}: the library is inline once, verbatim, in the head, after the theme script and before the page's own first <style>; the settings and ColorTool.applyStored follow it",
          pg.count("/* colortool v2 */") == 1 and LIB in head and head.find("stackshot-theme") > 0 and head.find("stackshot-theme") < head.find("/* colortool v2 */") < head.find("window.stackshotColors=") < head.find("ColorTool.applyStored(window.stackshotColors);") < head.find("<style>")
          and "<style>" not in ct.HEAD and ":root{--bg:" in head[head.find("<style>"):head.find("<style>") + 3000], pg.count("/* colortool v2 */"))
    check(f"{nm}: the init call is at the end of the body, after Back to top; the page carries no markup of the tool (no button, no panel: the script draws them)",
          body.count("ColorTool.init(window.stackshotColors);") == 1 and body.find('id="totop"') < body.find("ColorTool.init(") < body.rfind("</body>") and 'id="ct-btn"' not in pg and 'id="ct-pop"' not in pg and 'class="ct-' not in pg, None)
    check(f"{nm}: one empty mount at the end of the side panel, after its sections, with the gap element before it (the tool draws the button there)",
          pg.count('id="panel-colors"') == 1 and pg.count('id="panel-colors-gap"') == 1 and re.search(r'<div id="panel-colors-gap" aria-hidden="true"></div><div id="panel-colors"></div>', pg) is not None
          and pg.find('<aside id="panel"') < pg.find('id="panel-colors"') < pg.find("</aside>", pg.find('id="panel-colors"')) and pg.find('id="panel-colors"') > pg.rfind("<section", 0, pg.find('id="panel-colors"')), pg.count('id="panel-colors"'))
    check(f"{nm}: with the tool's script blocks cut out no trace of the tool is left in the page", "ColorTool" not in C.without_colortool(pg) and "stackshotColors" not in C.without_colortool(pg) and "colortool" not in C.without_colortool(pg), None)
check("the hooks in ui/render.py: the import, _APP_HEAD += HEAD, _FAB_PAIR += BODY, the mount in _panel_frame, and the panel keeps its peek open while the tool's panel is open",
      "from ui import colortool as _ct" in SRCT["ui/render.py"] and "_APP_HEAD += _ct.HEAD" in SRCT["ui/render.py"] and "_FAB_PAIR += _ct.BODY" in SRCT["ui/render.py"] and 'id="panel-colors"' in SRCT["ui/render.py"]
      and "document.querySelector('.ct-pop:not([hidden])')" in SRCT["ui/render.py"], None)

# ---- 3. the requests
CFG_ONLY = ct.CFG_JS
ALL_TOOL = LIB + "\n" + CFG_ONLY
FORBID = ["XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "document.cookie", "<form", "action=", "href=", "src=", "<img", "<link", "@import", "url(", "import(", "location", "navigator.", "postMessage", "indexedDB", "sessionStorage"]
check("the tool and its settings carry no cookie, form, link, image, import or address, and use no XHR, beacon, socket or stream: " + ", ".join(FORBID), not [w for w in FORBID if w in ALL_TOOL], [w for w in FORBID if w in ALL_TOOL])
check("the library has exactly one fetch, to the saved list's address from the page's own origin (credentials same-origin, no-store), a GET or a POST of JSON and nothing else",
      LIB.count("fetch(") == 1 and "fetch(API + path, { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store'" in LIB and "mode:" not in LIB and "http://" not in LIB and "https://" not in LIB
      and len(re.findall(r"\bcall\('", LIB)) == 3 and "call('/delete', { id: id })" in LIB and "call('', { name: name, values: v })" in LIB and "call('').then(function (d) { keepEnd(function () { draw(d); }); }" in LIB, LIB.count("fetch("))
check("the address the library calls comes from the settings (cfg.api), which stackshot gives as the saved list's route under the board's prefix; the delete is that address plus /delete",
      ct.API == "/colors/combos" and '"api": "/colors/combos"' not in CFG_ONLY and 'api:"/colors/combos"' in CFG_ONLY and "var API = cfg.api" in LIB and "/colors" not in LIB, None)
check("the list is read once when the panel opens (list() in open), written only by Save (POST) and Delete (POST /delete after a second tap); applying a saved combination and Reset send nothing",
      "if (on) { fold(foldRead(), false); refresh(); list(); place(); toEnd(); }" in LIB and LIB.count("list()") == 2 and "function useNow(id)" in LIB and "call(" not in LIB.split("function useNow(id)")[1].split("function delNow")[0]
      and "call(" not in LIB.split("$('ct-reset')")[1].split("});")[0], None)
calls = re.findall(r"localStorage\.(\w+)\(([^)]*)\)", LIB)
check("the library uses localStorage through two sets of three calls, getItem / setItem / removeItem: one on the key of the settings (the look) and one on that key plus ':fields' (whether the Fields fold is open, absent when closed, read and written inside try)",
      sorted(c[0] for c in calls) == ["getItem", "getItem", "removeItem", "removeItem", "setItem", "setItem"] and sorted(c[1].strip().split(",")[0] for c in calls) == ["FOLD"] * 3 + ["KEY"] * 3 and "KEY = cfg.storageKey" in LIB and "var FOLD = KEY + ':fields';" in LIB
      and "function foldRead() { try { return localStorage.getItem(FOLD) === '1'; } catch (e) { return false; } }" in LIB, calls)
check("the one key is stackshot's own, stackshot-color-trial, written in its settings and nowhere in the library; no other part of the page uses it", ct.KEY == "stackshot-color-trial" and f'storageKey:"{ct.KEY}"' in CFG_ONLY and ct.KEY not in LIB and "stackshot.fold." not in ALL_TOOL)
others = [p for p in ("server.py", "client.py", "router.py", "publish.py", "readonly.py", "push.py", "config.py", "ui/search.py", "ui/runners.py", "ui/kit.py", "ui/__init__.py")
          if re.search(r"colortool|stackshotColors|ct-btn|color-trial", pathlib.Path(STACK, p).read_text(encoding="utf-8"))]
check("no route, handler or other module names the tool or its key (server.py and the page modules are untouched by it; the saved list's routes are colorcombos.py's)", not others, others)
check("ui/colortool.py has no route, request or cookie code (the saved list is the library's fetch)", not re.search(r"\b(?:route|Response|Cookie|requests|httpx|urllib|socket|subprocess|open)\b", re.sub(r'""".*?"""', "", SRCT["ui/colortool.py"].split("CSS = ")[0], flags=re.S)), None)
css = Bd()._css()
check("the Board's own stylesheet carries nothing of the tool but the five dark tokens of the small labels and the disabled buttons (and the rules that read them): no --orange-text, --orange-solid or --on-solid, no ct- class", not re.search(r"orange-text|orange-solid|on-solid|\.ct[-.{ ]|ct-on|ct-wl|ct-lab|ct-dis|color-trial", css), None)

# ---- 4. the library in node over a stub page
tk = C.resolved(css)["dark"]
SH = ct.SHIPPED
def mixp(top, base, p):
    """The library's blend (each channel x*p/100 + y*(100-p)/100, rounded half up), which is what color-mix and an opacity give up to a level; tests/_colors.py's mix rounds half to even."""
    t_, b_ = top.lstrip("#"), base.lstrip("#")
    return "#" + "".join("%02x" % math.floor(int(t_[i:i + 2], 16) * p / 100 + int(b_[i:i + 2], 16) * (100 - p) / 100 + 0.5) for i in (0, 2, 4))
check("the shipped values stackshot gives the tool are the stylesheet's own: --bg --card --line --fg --mut --ibd --orange (text and solid) --on-acc", (SH["bg"], SH["card"], SH["line"], SH["fg"], SH["mut"], SH["ibd"], SH["link"], SH["solid"], SH["onsolid"])
      == (tk["--bg"], tk["--card"], tk["--line"], tk["--fg"], tk["--mut"], tk["--ibd"], tk["--orange"], tk["--orange"], tk["--on-acc"]), (SH, tk))
check("the shipped values that follow others are the stylesheet's own dark tokens: the small labels' fill, text and outline (--lab-bg --lab-fg --lab-bd) and the disabled fill and text (--dis-bg --dis-fg); the label fill and outline are the dark brown #3a2619 and the label text the orange",
      (SH["labbg"], SH["labfg"], SH["labbd"], SH["disbg"], SH["disfg"], SH["ifill"]) == (tk["--lab-bg"], tk["--lab-fg"], tk["--lab-bd"], tk["--dis-bg"], tk["--dis-fg"], tk["--ifill"])
      and SH["labbg"] == SH["labbd"] == "#3a2619" and SH["labfg"] == tk["--orange"], (SH, tk))

import shutil as _sh
HAVE_NODE = bool(_sh.which("node"))
check("node is installed (the library is run over a stub page here)", HAVE_NODE)
res = {}
def js(v): return json.dumps(v)
STACK_SETUP = ct.CFG_JS + "ColorTool.applyStored(window.stackshotColors);var T=ColorTool.engine(window.stackshotColors);"
FAKE_SHIP = {"bg": "#101820", "card": "#18222c", "line": "#2a3642", "fg": "#e8eef4", "mut": "#9fb0c0", "link": "#4aa3ff", "ibd": "#7f90a0", "solid": "#2f7fd6", "onsolid": "#ffffff",
             "labbg": "#173046", "labfg": "#4aa3ff", "labbd": "#4aa3ff", "disbg": "#2a3a4a", "disfg": "#9fb0c0", "ifill": "#22303c"}
FAKE_ALT = {**FAKE_SHIP, "bg": "#0c1218", "card": "#141c24"}
def fake_cfg(name, key, gate=None, extra=""):
    """The settings of a second app, as JavaScript: its own property names, a function for the shipped values (counting its calls and what the page held when it was called), an onApply that logs
    what it saw, an isDark of its own, no saved list and no preview."""
    return ("window.%(n)sLog={ship:0,sees:[],on:[],dark:0};window.%(n)sDark=true;window.%(n)sShip=%(s)s;" % {"n": name, "s": js(FAKE_SHIP)}
            + "window.%(n)s={storageKey:%(k)s,shipped:function(){window.%(n)sLog.ship++;window.%(n)sLog.sees.push(propsNow());return window.%(n)sShip},"
              "vars:{bg:['--page'],card:['--panel','--panel-2'],line:['--rule'],fg:['--ink'],mut:['--ink-2'],link:['--accent'],ibd:['--edge'],solid:['--cta']},"
              "onApply:function(r,s,set,add,t){window.%(n)sLog.on.push({stored:Object.keys(s).sort(),before:propsNow()});if(s.solid){set('--on-cta',r.onsolid);set('--cta-hover',t.mix('#000000',r.solid,14));add('fake-solid')}},"
              "isDark:function(){window.%(n)sLog.dark++;return window.%(n)sDark}%(g)s%(x)s};" % {"n": name, "k": js(key), "g": (",gate:%s" % js(gate)) if gate else "", "x": extra})
if HAVE_NODE:
    harness = T / "colortool_harness.js"
    harness.write_text("""const vm = require('vm'), fs = require('fs');
const lib = fs.readFileSync(process.argv[2], 'utf8'), cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8')), out = [];
for (const c of cases) {
  const props = {}, cls = new Set(), data = {}, snaps = {}; let fetches = 0, created = 0;
  for (const k of Object.keys(c.data || {})) data[k] = c.data[k];
  const root = {style: {setProperty: (k, v) => { props[k] = v; }, removeProperty: k => { delete props[k]; }}, classList: {add: x => cls.add(x), remove: x => cls.delete(x)}, getAttribute: a => a === 'data-theme' ? c.theme : null};
  const mq = c.mq === undefined ? c.theme === 'dark' : c.mq;
  const sb = {document: {documentElement: root, readyState: 'complete', querySelector: () => null, head: {appendChild() {}}, createElement: () => { created++; return {}; }}, localStorage: {getItem: k => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, removeItem: k => { delete data[k]; }},
              matchMedia: () => ({matches: mq, addEventListener() {}}), fetch: () => { fetches++; return Promise.reject(new Error('no network')); }};
  sb.window = sb; sb.propsNow = () => Object.keys(props).sort(); sb.snap = n => { snaps[n] = {props: Object.assign({}, props), cls: [...cls].sort()}; return n; };
  vm.createContext(sb); let val = null, err = null;
  try { vm.runInContext(lib, sb); vm.runInContext(c.setup || '', sb); if (c.expr) val = JSON.parse(vm.runInContext('JSON.stringify(' + c.expr + ')', sb)); } catch (e) { err = String(e && e.stack || e).slice(0, 600); }
  out.push({name: c.name, props, cls: [...cls].sort(), data, snaps, fetches, created, val, err});
}
console.log(JSON.stringify(out));
""", encoding="utf-8")
    cases = []
    def case(name, stored=None, theme="dark", expr=None, setup=STACK_SETUP, data=None, mq=None):
        d = dict(data or {})
        if stored is not None: d[ct.KEY] = json.dumps(stored)
        c = {"name": name, "theme": theme, "data": d, "expr": expr, "setup": setup}
        if mq is not None: c["mq"] = mq
        cases.append(c)
    PRE_NODE = "Object.keys(T.PRE).map(function(id){var n=T.norm(T.PRE[id]),r=T.resolve(n);return {id:id,n:n,r:r,refuse:T.refuse(r),warn:T.warn(r,n),again:T.norm(T.resolve(n))}})"
    case("constants", expr="{KEYS:T.KEYS,FIELDS:T.FIELDS,GROUPS:T.GROUPS,ORDER:T.ORDER,PRESETS:T.PRESETS,LIM:T.LIM,DK:T.DK,WH:T.WH,HOVER:T.HOVER,PRESSED:T.PRESSED,KEY:T.KEY,GATE:T.GATE,version:ColorTool.version,entries:Object.keys(ColorTool).sort()}")
    case("nothing stored")
    case("background only", {"bg": "#1a1a1b"}); case("card only", {"card": "#222224"}); case("body text only", {"fg": "#ffffff"}); case("muted only", {"mut": "#b8b7b2"}); case("outlines only", {"ibd": "#a0a09b"}); case("lines only", {"line": "#3a3a3d"})
    case("link only", {"link": "#ffa057"}); case("solid, dark label", {"solid": "#d9722e"}); case("solid, white label", {"solid": "#bd561d"}); case("text on solid only", {"onsolid": "#ffffff"})
    case("label fill only", {"labbg": "#2e1d12"}); case("label all three", {"labbg": "#2e1d12", "labfg": "#ffa057", "labbd": "#ffa057"}); case("disabled fill only", {"disbg": "#303034"}); case("disabled text only", {"disfg": "#c0bfba"})
    for pid in ("live", "old", "two", "radix", "primer"): case(f"preset {pid}", expr=None, setup=STACK_SETUP + "T.save(T.norm(T.PRE[%s]));T.apply();" % js(pid))
    case("Live now, saved as a snapshot of every shipped value", dict(SH))
    case("an older look: bg, text, solid, tint", {"bg": "#1f1f21", "text": "#ffa057", "solid": "#bd561d", "tint": True})
    for nm_, v in (("white", {"bg": "#ffffff"}), ("edge, passes", {"bg": "#303030"}), ("edge, one step lighter", {"bg": "#313131"}), ("old 7:1 gate", {"bg": "#4c4c4c"}), ("muted text unreadable", {"mut": "#222224"}),
                   ("body text dim", {"fg": "#555555"}), ("outlines vanish", {"ibd": "#222224"}), ("white with an orange", {"bg": "#ffffff", "link": "#ffa057", "labbg": "#3a2619"}), ("junk", {"bg": "red", "link": "#abc", "solid": 5, "x": "#ffffff"})):
        case(nm_, v)
    case("white, light theme", {"bg": "#ffffff"}, theme="light"); case("a preset, light theme", {"link": "#ffa057", "solid": "#f76b15"}, theme="light")
    case("pure: nothing set", expr="T.resolve({})")
    case("pure: a background", expr="[T.resolve({bg:'#1a1a1b'}),T.resolve({bg:'#1a1a1b',card:'#222224',line:'#333336'}),T.resolve({fg:'#ffffff'}),T.resolve({solid:'#bd561d'}),T.resolve({link:'#ffa057'}),T.resolve({disbg:'#2a2a2c'}),T.resolve({solid:'#bd561d',bg:'#1a1a1b'})]")
    case("pure: norm", expr="[T.norm({}),T.norm(T.ship()),T.norm({bg:'#161617',card:'#1f1f21'}),T.norm({BG:'#1A1A1B',bg:'#1A1A1B',link:'#F0A06A',solid:'#BD561D'}),T.norm({bg:'#abc',card:'red',fg:7,mut:null,line:'#12345g'}),T.norm({bg:'#1a1a1b',card:'" + mixp("#ececea", "#1a1a1b", 4) + "'}),T.norm({solid:'#bd561d',onsolid:'#ffffff'}),T.norm({solid:'#bd561d',onsolid:'#eeeeee'})]")
    case("pure: presets", expr=PRE_NODE)
    case("pure: the background edge", expr="[T.refuse(T.resolve({bg:'#303030'})),T.refuse(T.resolve({bg:'#313131'})),T.refuse(T.resolve({bg:'#ffffff'})),T.refuse(T.resolve({fg:'#555555'})),T.refuse(T.resolve({mut:'#222224'})),T.refuse(T.resolve({ibd:'#222224'})),T.refuse(T.resolve({card:'#cccccc'}))]")
    case("pure: warnings", expr="[T.warn(T.resolve({link:'#444444'}),{link:1}),T.warn(T.resolve({line:'#212123'}),{line:1}),T.warn(T.resolve({labfg:'#3a2619',labbg:'#3a2619'}),{labfg:1}),T.warn(T.resolve({labbd:'#1f1f21'}),{labbd:1}),T.warn(T.resolve({solid:'#202022'}),{solid:1})]")
    # applyStored and init alone: nothing drawn, nothing asked of the network, the settings' stylesheet injected once
    case("applyStored, init and applyStored again", {"bg": "#1a1a1b"}, setup=ct.CFG_JS + "ColorTool.applyStored(window.stackshotColors);ColorTool.init(window.stackshotColors);ColorTool.applyStored(window.stackshotColors);ColorTool.init(window.stackshotColors);ColorTool.remount(null,window.stackshotColors);", expr="{remount:typeof ColorTool.remount}")
    # the second app
    SEED_F = {"bg": "#0b1218", "link": "#ffb000", "solid": "#d9722e"}
    FAKE_START = fake_cfg("fa", "fake-app-look") + "ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);"
    case("fake: a stored look is applied under the app's own names", data={"fake-app-look": json.dumps(SEED_F)}, setup=FAKE_START, expr="{log:window.faLog,key:F.KEY,gate:F.GATE,res:F.resolve(F.load())}")
    case("fake: Reset takes off everything, onApply's properties and class too", data={"fake-app-look": json.dumps(SEED_F)}, setup=FAKE_START + "snap('before');F.save({});F.apply();snap('after');F.save(F.norm(" + js(SEED_F) + "));F.apply();snap('again');F.apply();F.save(F.norm(F.PRE.live));F.apply();snap('live');", expr="window.faLog")
    case("fake: the shipped function is called on every apply, never cached, after the tracked properties were removed",
         data={"fake-app-look": json.dumps(SEED_F)}, setup=FAKE_START + "var n0=window.faLog.ship;F.apply();var n1=window.faLog.ship;window.faShip=" + js(FAKE_ALT) + ";F.apply();var n2=window.faLog.ship;",
         expr="{n:[n0,n1,n2],sees:window.faLog.sees,res:F.resolve({}),ship:F.ship().bg,cardAlt:F.resolve({bg:'#0b1218'}).card}")
    case("fake: isDark of the app decides, on every apply and at init (the page's data-theme is ignored)", data={"fake-app-look": json.dumps(SEED_F)}, theme="light",
         setup=FAKE_START + "var d0=window.faLog.dark;snap('darkByApp');window.faDark=false;F.apply();snap('lightByApp');var d1=window.faLog.dark;ColorTool.init(window.fa);var d2=window.faLog.dark;window.faDark=true;F.apply();snap('darkAgain');",
         expr="{d:[d0,d1,d2],isDark:F.isDark()}")
    case("fake: isDark false beats a dark page", data={"fake-app-look": json.dumps(SEED_F)}, theme="dark", setup=fake_cfg("fa", "fake-app-look") + "window.faDark=false;ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);", expr="window.faLog")
    case("fake: onApply runs on every apply, Reset and Live now included, stored = {} then", data={"fake-app-look": json.dumps(SEED_F)}, setup=FAKE_START + "F.apply();F.save({});F.apply();F.save(F.norm(F.PRE.live));F.apply();", expr="window.faLog.on")
    BAD_F = {"bg": "#ffffff"}
    case("fake: the refuse gate (the default) does not apply a stored white page and clears it", data={"fake-app-look": json.dumps(BAD_F)}, setup=FAKE_START, expr="{gate:F.GATE,refuse:F.refuse(F.resolve(%s)),warn:F.warn(F.resolve(%s),%s)}" % (js(BAD_F), js(BAD_F), js(BAD_F)))
    WARN_START = fake_cfg("fw", "fake-warn-look", gate="warn") + "ColorTool.applyStored(window.fw);var W=ColorTool.engine(window.fw);"
    case("fake: the warn gate applies a stored white page, keeps it and refuses nothing", data={"fake-warn-look": json.dumps(BAD_F)}, setup=WARN_START,
         expr="{gate:W.GATE,refuse:W.refuse(W.resolve(W.norm(%s))),refuseWorse:W.refuse(W.resolve(W.norm({fg:'#444444',mut:'#222224',ibd:'#202022'}))),warn:W.warn(W.resolve(W.norm(%s)),W.norm(%s)),stored:W.load(),res:W.resolve(W.load())}" % (js(BAD_F), js(BAD_F), js(BAD_F)))
    case("fake: the warn gate applies a typed combination that the refuse gate would turn down", data={}, setup=WARN_START + "W.save(W.norm({fg:'#444444',mut:'#222224',ibd:'#202022',bg:'#ffffff'}));W.apply();snap('typed');",
         expr="{refuse:W.refuse(W.resolve(W.norm({fg:'#444444',bg:'#ffffff'}))),stored:W.load()}")
    case("fake: the warn gate's warnings for a good dark look are the same pairs as the refuse gate's (no first six)", data={}, setup=WARN_START + FAKE_START.split("ColorTool.applyStored(window.fa);")[0].replace("window.faLog=", "window.faLog=") + "ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);",
         expr="{w:W.warn(W.resolve({}),{}),f:F.warn(F.resolve({}),{})}")
    case("fake: two apps on one page keep their own properties, keys and classes",
         data={"fake-app-look": json.dumps(SEED_F), ct.KEY: json.dumps({"bg": "#1a1a1b", "solid": "#bd561d"})}, setup=STACK_SETUP + FAKE_START + "snap('both');F.save({});F.apply();snap('afterFakeReset');T.save({});T.apply();snap('afterBothReset');",
         expr="{keys:[T.KEY,F.KEY]}")
    case("fake: the minimal settings (a key and the shipped values) work: nothing is set, nothing is drawn, nothing is asked", data={"min-look": json.dumps({"bg": "#0b1218", "link": "#ffb000"})},
         setup="window.mn={storageKey:'min-look',shipped:" + js(FAKE_SHIP) + "};ColorTool.applyStored(window.mn);ColorTool.init(window.mn);var M=ColorTool.engine(window.mn);", expr="{res:M.resolve(M.load()),gate:M.GATE,dark:M.isDark()}")
    # a light page (the app's isDark is false) with a stored dark look, and a shipped function that reads the light page: the stored look must be left alone
    LIGHT_SHIP = {**FAKE_SHIP, "bg": "#fafaf8", "card": "#ffffff", "line": "#dcdcd6", "fg": "#1b1b1a", "mut": "#5c5c57", "ibd": "#6f6f69"}
    case("fake: a light page keeps a stored dark look untouched whatever the shipped function answers there, and the dark page applies it again",
         data={"fake-app-look": json.dumps({"bg": "#0b1218", "solid": "#d9722e"})},
         setup=fake_cfg("fa", "fake-app-look") + "window.faShip=" + js(LIGHT_SHIP) + ";window.faDark=false;ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);snap('light');var kept=localStorage.getItem('fake-app-look');"
               "F.apply();snap('lightAgain');window.faShip=" + js(FAKE_SHIP) + ";window.faDark=true;F.apply();snap('dark');",
         expr="{kept:kept,log:window.faLog,after:localStorage.getItem('fake-app-look')}")
    case("fake: a shipped function that answers with something that is not an object falls back to nothing and does not stop the tool", data={"fake-app-look": json.dumps({"bg": "#0b1218"})},
         setup=fake_cfg("fa", "fake-app-look") + "window.faShip=null;ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);F.apply();var a=Object.keys(F.ship()).length;window.faShip=" + js(FAKE_SHIP) + ";F.apply();",
         expr="{empty:a,then:F.ship().bg}")
    # the five fields that follow others, when the app ships its own value for them (the shipped values above are not what the follow rule gives)
    BAD_FOL = {**FAKE_SHIP, "labbg": "red", "disbg": 5}; del BAD_FOL["labfg"]
    case("fake: shipped followers", setup=FAKE_START, expr="{follows:F.FOLLOWS,none:F.resolve({}),link:F.resolve({link:'#ffb000'}),solid:F.resolve({solid:'#d9722e'}),onsolid:F.resolve({onsolid:'#000000'}),bg:F.resolve({bg:'#0b1218'}),card:F.resolve({card:'#222224'}),"
                                                     "own:F.resolve({labbg:'#222224',disfg:'#ffffff'}),snap:F.norm(F.resolve({})),worked:F.norm({labbg:F.mix('#4aa3ff',F.ship().card,16),disbg:F.mix('#2f7fd6',F.ship().bg,50)}),again:F.norm(F.resolve(F.norm({link:'#ffb000',solid:'#d9722e'})))}")
    case("fake: shipped followers, one malformed and one missing", setup=fake_cfg("fa", "fake-app-look") + "window.faShip=" + js(BAD_FOL) + ";ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);",
         expr="{none:F.resolve({}),worked:{labbg:F.mix(F.ship().link,F.ship().card,16),labfg:F.ship().link,disbg:F.mix(F.ship().solid,F.ship().bg,50)}}")
    UP_SHIP = {**FAKE_SHIP, "labbg": "#173046".upper(), "disbg": "#2A3A4A", "disfg": "#9FB0C0"}
    case("fake: shipped followers in uppercase", data={"fake-app-look": json.dumps({"link": "#ffb000"})}, setup=fake_cfg("fa", "fake-app-look") + "window.faShip=" + js(UP_SHIP) + ";ColorTool.applyStored(window.fa);var F=ColorTool.engine(window.fa);",
         expr="{none:F.resolve({}),snap:F.norm(" + js(UP_SHIP) + "),lower:F.norm({disbg:'#2a3a4a',labbg:'#173046'}),link:F.resolve({link:'#ffb000'})}")
    case("stackshot: its five shipped followers against what the engine works out from the live fields", setup=ct.CFG_JS + "var c2=Object.assign({},window.stackshotColors);c2.shipped=Object.assign({},window.stackshotColors.shipped);"
         "['labbg','labfg','labbd','disbg','disfg'].forEach(function(k){delete c2.shipped[k]});ColorTool.applyStored(window.stackshotColors);var W=ColorTool.engine(c2);var T=ColorTool.engine(window.stackshotColors);",
         expr="{worked:W.resolve({}),shipped:T.resolve({})}")
    case("fake: shipped followers, answered by a function and changed between applies", data={"fake-app-look": json.dumps({"solid": "#d9722e"})},
         setup=FAKE_START + "window.faShip=" + js({**FAKE_SHIP, "labbg": "#222224", "disfg": "#eeeeee"}) + ";F.apply();var r1=F.resolve(F.load());",
         expr="{r1:r1,labbg:r1.labbg,disfg:r1.disfg}")
    if HAVE_NODE:
        (T / "colortool_lib.js").write_text(LIB, encoding="utf-8")
        (T / "colortool_cases.json").write_text(json.dumps(cases), encoding="utf-8")
        nr = subprocess.run(["node", str(harness), str(T / "colortool_lib.js"), str(T / "colortool_cases.json")], capture_output=True, text=True, timeout=60)
        res = {r["name"]: r for r in json.loads(nr.stdout)} if nr.returncode == 0 else {}
        check("node ran the library over a stub page, every case without an error", len(res) == len(cases) and not [r["name"] for r in res.values() if r["err"]], ((nr.stdout[:200] + nr.stderr)[:600], [(r["name"], r["err"]) for r in res.values() if r["err"]][:2]))
if res:
    P = lambda n: res[n]["props"]
    CONST = res["constants"]["val"]
    FIELDS = CONST["FIELDS"]; FIELD_KEYS = [f[0] for f in FIELDS]; PRESETS = CONST["PRESETS"]; PRE = {p[0]: p[2] for p in PRESETS}; LIM = CONST["LIM"]
    GROUPS = [("surfaces", ["bg", "card", "line"]), ("text", ["fg", "mut", "link"]), ("buttons", ["ibd", "solid", "onsolid", "disbg", "disfg"]), ("small-labels", ["labbg", "labfg", "labbd"])]
    check("the entries are version, applyStored, init, remount and engine; the version is 2; the gate of stackshot is the default, refuse", CONST["entries"] == ["applyStored", "engine", "init", "remount", "version"] and CONST["version"] == 2 and CONST["GATE"] == "refuse" and CONST["KEY"] == ct.KEY, CONST["entries"])
    check("the fields are the saved list's 14 keys, in the panel's order, four groups (Surfaces, Text, Buttons, Small labels), named as the panel names them", sorted(FIELD_KEYS) == sorted(__import__("colorcombos").KEYS) and len(FIELD_KEYS) == 14 and sum(len(k) for _, k in GROUPS) == 14
          and [k for _, ks in GROUPS for k in ks] == FIELD_KEYS and CONST["GROUPS"] == ["Surfaces", "Text", "Buttons", "Small labels"] and sorted(CONST["KEYS"]) == sorted(FIELD_KEYS)
          and [f[1] for f in FIELDS] == ["Page background", "Cards", "Lines", "Body text", "Muted text", "Text and links", "Button outlines", "Solid fills", "Text on solid fills", "Disabled fill", "Disabled text", "Fill", "Text", "Outline"], FIELD_KEYS)
    check("the presets are Live now (empty: what the page ships), Old orange, Two oranges, Radix and Primer, each a full 14-key combination of #rrggbb, the neutrals the same in every preset but Live now, the label outline equal to the label fill",
          [p[0] for p in PRESETS] == ["live", "old", "two", "radix", "primer"] and [p[1] for p in PRESETS] == ["Live now", "Old orange", "Two oranges", "Radix", "Primer"] and PRESETS[0][2] == {}
          and all(sorted(p) == sorted(FIELD_KEYS) and all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in p.values()) and p["labbd"] == p["labbg"]
                  and {k: p[k] for k in ("bg", "card", "line", "fg", "mut", "ibd", "disbg", "disfg")} == {"bg": "#161617", "card": "#1f1f21", "line": "#2c2c2e", "fg": "#ececea", "mut": "#a3a29d", "ibd": "#929190", "disbg": "#2a2a2c", "disfg": "#a3a29d"} for p in [q[2] for q in PRESETS[1:]]), None)
    check("the presets' oranges are the stated ones: text / solid / on solid / label fill / label text", [(PRE[i]["link"], PRE[i]["solid"], PRE[i]["onsolid"], PRE[i]["labbg"], PRE[i]["labfg"]) for i in ("old", "two", "radix", "primer")] == [
          ("#f0a06a", "#f0a06a", "#1f1f21", "#f0a06a", "#1f1f21"), ("#f0a06a", "#bd561d", "#ffffff", "#3a2619", "#f0a06a"), ("#ffa057", "#f76b15", "#ffffff", "#462100", "#ffa057"), ("#ffa657", "#bd561d", "#ffffff", "#2a1f19", "#db6d28")])
    check("the limits, the hover and pressed blends and the label colors are the stated ones", LIM == {"fg_bg": 11, "fg_card": 7, "mut": 4.5, "ibd": 3, "link": 4.5, "solid": 3, "onsolid": 4.5, "lab": 4.5, "labbd": 3, "dis": 3, "line": 1.15}
          and CONST["HOVER"] == 14 and CONST["PRESSED"] == 24 and CONST["DK"] == "#161617" and CONST["WH"] == "#ffffff" and SH["fg"] == tk["--fg"], CONST["LIM"])

    # which properties the settings can set: exactly these, every one reachable, none beyond
    EXPECT_PROPS = sorted(["--bg", "--card", "--line", "--ifill", "--fg", "--mut", "--ibd", "--acc", "--call", "--t-you", "--selbg", "--t-you-bg", "--orange-text", "--orange-solid", "--on-solid", "--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg"])
    declared = sorted({p for v in ct.CFG_VARS.values() for p in v} | set(re.findall(r"set\('(--[\w-]+)'", ct.ON_APPLY)) | {p for g in re.findall(r"\[((?:'--[\w-]+',?)+)\]\.forEach", ct.ON_APPLY) for p in re.findall(r"--[\w-]+", g)})
    seen_props = sorted({p for n, r in res.items() if not n.startswith(("fake", "pure", "constants")) for p in r["props"]})
    check("the settings set exactly these properties, and each one is reached by some stored look: " + " ".join(EXPECT_PROPS), declared == EXPECT_PROPS == seen_props, (declared, seen_props))
    check("--orange itself and every status color (--run --warn --yellow --ok --p1 --live --relay --amber --t-agent) are never set or re-pointed", not [t for t in ("--orange'", "--orange:", "--run", "--warn", "--yellow", "--ok", "--p1", "--live", "--relay", "--amber", "--t-agent", "--t-release", "--t-wait", "--t-done", "--t-red", "--on-acc'", "--iph") if t in (ct.ON_APPLY + json.dumps(ct.CFG_VARS)).replace("--orange-", "")], None)
    check("every property it sets is a token of the shipped dark stylesheet (or is new, and read only by the rules below)", all(p in tk or p in ("--orange-text", "--orange-solid", "--on-solid", "--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg") for p in EXPECT_PROPS), [p for p in EXPECT_PROPS if p not in tk])
    check("the dark theme only: apply() sets nothing unless isDark, and the library watches data-theme and the system scheme to apply again", "if (dk) KEYS.forEach(function (k) {" in LIB and LIB.index("if (dk) KEYS.forEach") < LIB.index("cfg.vars[k].forEach") and "MutationObserver" in LIB and "(prefers-color-scheme: dark)" in LIB and "ui.wrap.hidden = true" in LIB)
    check("the derived surfaces follow the background by the stated rule: Cards 4% and Lines and the input fill 10% of the body text over it, and only when the background is set",
          "r.card = s.card || (s.bg ? mix(r.fg, r.bg, 4) : S.card); r.line = s.line || (s.bg ? mix(r.fg, r.bg, 10) : S.line);" in LIB and "r.ifill = s.bg ? mix(r.fg, r.bg, 10) : S.ifill;" in LIB and tk["--ifill"] == "#2b2b2f", None)
    check("the tints follow the text orange as the shipped ones follow --orange: --selbg 8% and --t-you-bg 12% over the card", "set('--selbg','color-mix(in srgb,var(--orange-text) 8%,var(--card))')" in ct.ON_APPLY
          and "set('--t-you-bg','color-mix(in srgb,var(--orange-text) 12%,var(--card))')" in ct.ON_APPLY and "--selbg:color-mix(in srgb,var(--orange) 8%,var(--card))" in SRCT["ui/render.py"]
          and "--t-you-bg:color-mix(in srgb,var(--orange) 12%,var(--card))" in kit.CSS, None)
    body_css = css + render._BTN_CSS + open(os.path.join(STACK, "ui/render.py"), encoding="utf-8").read() + kit.CSS
    sol_css = {".b.main": r"\.b\.main\{background:var\(--acc\)", ".adot": r"\.adot::after\{[^}]*background:var\(--acc\)", "#panel-drop": r"#panel-drop\{[^}]*background:var\(--acc\)", "ul.hist li.ev-answer": r"ul\.hist li\.ev-answer::before\{background:var\(--call\)"}
    check("the solid fills the style re-points are fills in the shipped stylesheet: the main button, the live dot, the panel-order drop line and the answer dot of the history", set(sol_css) == set(ct.SOLID_RULES) and all(re.search(p, body_css) for p in sol_css.values()), [k for k, p in sol_css.items() if not re.search(p, body_css)])
    check("the style re-points them under html.ct-on only, each to --orange-solid (label --on-solid), and a lighter label hovers toward black (html.ct-wl .b.main)", "html.ct-on .b.main,html.ct-on .adot,html.ct-on #panel-drop{--acc:var(--orange-solid);--on-acc:var(--on-solid)}" in ct.CSS
          and "html.ct-on ul.hist li.ev-answer::before{--call:var(--orange-solid)}" in ct.CSS and "li.ev-answer{--call" not in ct.CSS and "html.ct-wl .b.main{--fg:#000}" in ct.CSS and "set('--orange-solid',s.solid?r.solid:'var(--orange)')" in ct.ON_APPLY)
    paint = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body_css):
        if "background:var(--t-you-bg)" in m.group(2) or "--bc:var(--call)" in m.group(2):
            paint |= {s.strip().split("\n")[-1].strip() for s in m.group(1).split(",") if re.fullmatch(r"\s*[.#]?[\w.#-]+\s*", s.strip().split("\n")[-1])}
    DKR = ":root[data-theme=dark]"; MQR = ":root:not([data-theme=light])"
    LAB_DECL = "{background:var(--lab-bg);color:var(--lab-fg);border-color:var(--lab-bd)}"; TAG_DECL = "{background:var(--lab-bg);color:var(--lab-fg);box-shadow:inset 0 0 0 1px var(--lab-bd)}"
    DIS_DECL = "{opacity:1;background:var(--dis-bg);border-color:var(--dis-bg);color:var(--dis-fg)}"; DIS_SEL = ".b:disabled:not(.busy,.on,[aria-busy=true],form[aria-busy] .b)"
    check("the orange labels of the shipped stylesheet are the Your move tag (.t-you) and the badges .badge.call and .badge.rec, and the dark rules of the stylesheet draw each from --lab-bg --lab-fg --lab-bd, in both dark forms (the chosen theme and the system scheme)", paint == {".t-you", ".badge.call", ".badge.rec"}
          and all(f"{r} .badge.call,{r} .badge.rec{LAB_DECL}" in css and f"{r} .tag.t-you{TAG_DECL}" in css for r in (DKR, MQR)), paint)
    check("every rendered .t-you is a .tag (so the dark rule .tag.t-you reaches it)", all("tag" in m.group(1).split() for pg in PAGES.values() for m in re.finditer(r'class="([^"]*\bt-you\b[^"]*)"', C.without_colortool(pg))), None)
    check("the label rules are dark only and change no size: no padding or border width in the tag's rule (its outline is an inset ring), the light theme's tokens carry no label token, and the badges keep their 16% tint there",
          "padding" not in TAG_DECL and "border:" not in TAG_DECL and "--lab-bg" not in re.search(r":root\{--bg:#fafaf8[^\n]*", css).group(0)
          and ".badge{--bc:var(--mut)" in body_css and "color-mix(in srgb,var(--bc) var(--ink),var(--fg));background:color-mix(in srgb,var(--bc) 16%,transparent)" in body_css, None)
    dis_shipped = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*opacity:[^{}]*)\}", body_css):
        sel = m.group(1).strip().split("\n")[-1].strip().split("}")[-1].strip()
        if ":disabled" in sel and ":not(:disabled)" not in sel: dis_shipped.add(sel)
    check("the shipped disabled looks that fade by opacity are .b:disabled, .b.main:disabled (the idle Send), the panel-order menu items and the option cards; the dark rule replaces the first two there and leaves the others alone",
          {s for s in dis_shipped if s.startswith(".b")} >= {".b:disabled", ".b.main:disabled"} and {".pmi:disabled", ".acards .acard:has(input:disabled)"} <= dis_shipped and all(f"{r} {DIS_SEL}{DIS_DECL}" in css for r in (DKR, MQR)) and ".pmi" not in DIS_SEL and ".acard" not in DIS_SEL, dis_shipped)
    check("the dark disabled rule: .b:disabled, not busy, not pressed (.on), not inside a busy form, opacity 1 and one flat look from --dis-bg and --dis-fg; the hover and pressed rules (:not(:disabled)) never meet it; the tool's own style has no label or disabled rule",
          ".b.main.busy,.b.main[aria-busy=true],form[aria-busy] .b.main{" in body_css and ".b.busy,.b[aria-busy=true],form[aria-busy] .b{" in body_css and ".b.on{" in body_css and 'aria-pressed="true" disabled' in SRCT["ui/render.py"]
          and "ct-dis" not in ct.CSS and "ct-lab" not in ct.CSS, None)

    # ---- the fields, in node
    check("nothing set applies nothing: no property, no class, nothing stored; the page is exactly the shipped stylesheet; applyStored makes no request and puts in only the settings' stylesheet",
          P("nothing stored") == {} and res["nothing stored"]["cls"] == [] and res["nothing stored"]["data"].get(ct.KEY) is None and res["nothing stored"]["fetches"] == 0 and res["nothing stored"]["created"] == 1)
    ai = res["applyStored, init and applyStored again"]
    check("applyStored alone applies the stored look and draws nothing; init and a second applyStored draw nothing in a page with no mount and add nothing (the stylesheet once), make no request, and remount before any button is a no-op",
          ai["props"].get("--bg") == "#1a1a1b" and ai["created"] == 1 and ai["fetches"] == 0 and ai["val"] == {"remount": "function"}, ai)
    check("resolve() of nothing is exactly the shipped dark theme in the 14 values (and the input fill)", {k: v for k, v in res["pure: nothing set"]["val"].items() if k != "ifill"} == {k: v for k, v in SH.items() if k != "ifill"} and res["pure: nothing set"]["val"]["ifill"] == tk["--ifill"], res["pure: nothing set"]["val"])
    rv = res["pure: a background"]["val"]
    check("a set background gives Cards 4% and Lines and the input fill 10% of the body text over it; a Cards or Lines field set wins; a set body text alone derives nothing (the card stays the shipped one)",
          rv[0]["card"] == mixp(SH["fg"], "#1a1a1b", 4) and rv[0]["line"] == mixp(SH["fg"], "#1a1a1b", 10) and rv[0]["ifill"] == mixp(SH["fg"], "#1a1a1b", 10) and rv[1]["card"] == "#222224" and rv[1]["line"] == "#333336"
          and rv[2]["card"] == SH["card"] and rv[2]["line"] == SH["line"] and rv[2]["fg"] == "#ffffff", rv[:3])
    check("a solid fill set picks the label that reads better on it (white on #bd561d), a text-orange set alone leaves the fill and its label shipped, a disabled fill set alone leaves the text the Send's label faded over the page, and the label and disabled pair follow a set solid and background",
          rv[3]["onsolid"] == "#ffffff" and rv[3]["disbg"] == mixp("#bd561d", SH["bg"], 50) and rv[3]["disfg"] == mixp("#ffffff", SH["bg"], 50) and rv[4]["solid"] == SH["solid"] and rv[4]["onsolid"] == SH["onsolid"] and rv[4]["labbg"] == mixp("#ffa057", SH["card"], 16)
          and rv[4]["labfg"] == "#ffa057" and rv[4]["labbd"] == "#ffa057" and rv[5]["disfg"] == SH["disfg"] and rv[6]["disbg"] == mixp("#bd561d", "#1a1a1b", 50) and rv[6]["labbg"] == mixp(SH["link"], mixp(SH["fg"], "#1a1a1b", 4), 16), rv[3:])
    rn = res["pure: norm"]["val"]
    check("norm() keeps only valid #rrggbb in lowercase and drops every value equal to what the field would be unset: nothing, the whole shipped set, a shipped background and card, capitals lowercased, #abc, color names, numbers and unknown keys; an auto label is dropped, a different one kept",
          rn[0] == {} and rn[1] == {} and rn[2] == {} and rn[3] == {"bg": "#1a1a1b", "solid": "#bd561d"} and rn[4] == {} and rn[5] == {"bg": "#1a1a1b"} and rn[6] == {"solid": "#bd561d"} and rn[7] == {"solid": "#bd561d", "onsolid": "#eeeeee"}, rn)
    bgc = mixp(SH["fg"], "#1a1a1b", 4)
    check("a background alone sets --bg --card --line --ifill (the derived blends as hex; the input fill is not a field) and, because the small labels and the disabled pair follow the page, those five tokens worked out from it",
          P("background only") == {"--bg": "#1a1a1b", "--card": bgc, "--line": mixp(SH["fg"], "#1a1a1b", 10), "--ifill": mixp(SH["fg"], "#1a1a1b", 10), "--lab-bg": mixp(SH["link"], bgc, 16), "--lab-fg": SH["labfg"], "--lab-bd": SH["labbd"],
                                  "--dis-bg": mixp(SH["solid"], "#1a1a1b", 50), "--dis-fg": mixp(SH["onsolid"], "#1a1a1b", 50)} and res["background only"]["cls"] == [], P("background only"))
    check("a card set alone sets --card and the small label fill that follows it (the tint of the text orange over it); body text, muted text, button outlines and lines set alone each set only their own property (nothing derived at the shipped background)",
          P("card only") == {"--card": "#222224", "--lab-bg": mixp(SH["link"], "#222224", 16), "--lab-fg": SH["labfg"], "--lab-bd": SH["labbd"]} and P("body text only") == {"--fg": "#ffffff"} and P("muted only") == {"--mut": "#b8b7b2"}
          and P("outlines only") == {"--ibd": "#a0a09b"} and P("lines only") == {"--line": "#3a3a3d"} and all(res[n]["cls"] == [] for n in ("card only", "body text only", "muted only", "outlines only", "lines only")))
    check("text and links set --orange-text and what reads it (--acc --call --t-you, and the tints --selbg and --t-you-bg), with ct-on, and the small labels that follow it (the tint of it over the card, it for the label text and outline); the solid fill and its label stay the shipped ones",
          P("link only") == {"--orange-text": "#ffa057", "--acc": "var(--orange-text)", "--call": "var(--orange-text)", "--t-you": "var(--orange-text)",
          "--selbg": "color-mix(in srgb,var(--orange-text) 8%,var(--card))", "--t-you-bg": "color-mix(in srgb,var(--orange-text) 12%,var(--card))", "--orange-solid": "var(--orange)", "--on-solid": "var(--on-acc)",
          "--lab-bg": mixp("#ffa057", SH["card"], 16), "--lab-fg": "#ffa057", "--lab-bd": "#ffa057"} and res["link only"]["cls"] == ["ct-on"], P("link only"))
    check("a solid fill sets --orange-solid and the label that reads better, ct-on, ct-wl (hover toward black) only under a lighter label, and the disabled pair that follows it (the fill and the label faded to 50% over the page); a label set alone (text on solid fills) does the same on the shipped fill",
          P("solid, dark label") == {"--orange-solid": "#d9722e", "--on-solid": "#161617", "--dis-bg": mixp("#d9722e", SH["bg"], 50), "--dis-fg": mixp("#161617", SH["bg"], 50)} and res["solid, dark label"]["cls"] == ["ct-on"]
          and P("solid, white label") == {"--orange-solid": "#bd561d", "--on-solid": "#ffffff", "--dis-bg": mixp("#bd561d", SH["bg"], 50), "--dis-fg": mixp("#ffffff", SH["bg"], 50)} and res["solid, white label"]["cls"] == ["ct-on", "ct-wl"]
          and P("text on solid only") == {"--orange-solid": "var(--orange)", "--on-solid": "#ffffff", "--dis-bg": SH["disbg"], "--dis-fg": mixp("#ffffff", SH["bg"], 50)} and res["text on solid only"]["cls"] == ["ct-on", "ct-wl"])
    check("small labels: any of the three sets all three properties (--lab-bg --lab-fg --lab-bd), the ones not set resolved to the shipped values, and no class (the stylesheet draws them)", P("label fill only") == {"--lab-bg": "#2e1d12", "--lab-fg": SH["labfg"], "--lab-bd": SH["labbd"]} and res["label fill only"]["cls"] == []
          and P("label all three") == {"--lab-bg": "#2e1d12", "--lab-fg": "#ffa057", "--lab-bd": "#ffa057"} and res["label all three"]["cls"] == [])
    check("disabled: either field sets BOTH properties, the one not set resolved to the shipped value, so a half-set pair never mixes two looks; no class (the stylesheet draws them)",
          P("disabled fill only") == {"--dis-bg": "#303034", "--dis-fg": SH["disfg"]} and P("disabled text only") == {"--dis-bg": SH["disbg"], "--dis-fg": "#c0bfba"} and res["disabled fill only"]["cls"] == [] and res["disabled text only"]["cls"] == [])
    pre = {r["id"]: r for r in res["pure: presets"]["val"]}
    EXPECT_CLS = {"live": [], "old": [], "two": ["ct-on", "ct-wl"], "radix": ["ct-on", "ct-wl"], "primer": ["ct-on", "ct-wl"]}
    check("applying each preset sets the classes expected (Live now and Old orange none; the others ct-on, and ct-wl under a white label); Live now applies nothing at all and Old orange only the three small-label tokens (it is the shipped look but for dark text on orange labels)",
          all(res[f"preset {i}"]["cls"] == EXPECT_CLS[i] for i in EXPECT_CLS) and P("preset live") == {} and P("preset old") == {"--lab-bg": "#f0a06a", "--lab-fg": "#1f1f21", "--lab-bd": "#f0a06a"}, {i: res[f"preset {i}"]["cls"] for i in EXPECT_CLS})
    check("a preset applies every field that differs from shipped and no other: Old orange the three label tokens only; the other three the oranges as stated (Two oranges shares the shipped text orange and the shipped small labels, so it sets neither of them: it sets the solid fill, its label and the disabled pair) and the label and disabled tokens together (a label text or outline equal to the text orange is not set: it follows it), not the outlines, which equal the shipped ones; no background, card, body text, muted text, line or outline property",
          all(set(P(f"preset {i}")) >= ({"--orange-solid", "--on-solid", "--dis-bg", "--dis-fg"} | (set() if i == "two" else {"--lab-bg", "--lab-fg", "--lab-bd"})) and not (i == "two" and set(P(f"preset {i}")) & {"--lab-bg", "--lab-fg", "--lab-bd"})
              and ("--orange-text" in P(f"preset {i}")) == (i != "two") and not set(P(f"preset {i}")) & {"--bg", "--card", "--line", "--fg", "--mut", "--ifill", "--ibd"} for i in ("two", "radix", "primer"))
          and P("preset radix")["--orange-text"] == "#ffa057" and P("preset radix")["--orange-solid"] == "#f76b15" and P("preset radix")["--on-solid"] == "#ffffff" and P("preset radix")["--lab-bg"] == "#462100" and P("preset radix")["--lab-bd"] == "#462100", P("preset radix"))
    check("every preset normalises to a smaller map that resolves to the same 14 values again, and the resolved snapshot a save sends normalises back to the same map (a saved combination applies as the preset did)", all(pre[i]["again"] == pre[i]["n"] for i in pre)
          and all({k: pre[i]["r"][k] for k in FIELD_KEYS} == ({k: {**SH, **PRE[i]}[k] for k in FIELD_KEYS} if i != "live" else {k: SH[k] for k in FIELD_KEYS}) for i in pre), {i: (pre[i]["n"], pre[i]["again"]) for i in pre})
    check("Live now saved as a snapshot of every shipped value (a combination saved with nothing set) applies nothing", P("Live now, saved as a snapshot of every shipped value") == {} and res["Live now, saved as a snapshot of every shipped value"]["cls"] == [])
    old = "an older look: bg, text, solid, tint"
    check("an older look {bg, text, solid, tint} is read: the text as Text and links, the tint ignored, and it is applied", P(old).get("--orange-text") == "#ffa057" and P(old).get("--bg") == "#1f1f21" and P(old).get("--orange-solid") == "#bd561d"
          and res[old]["cls"] == ["ct-on", "ct-wl"] and "ct-tint" not in res[old]["cls"] and json.loads(res[old]["data"][ct.KEY])["tint"] is True)
    # the gate, in the library
    check("a stored #ffffff, #313131 and #4c4c4c (the old 7:1 gate's) background are not applied and are cleared from storage; #303030 is applied and kept", all("--bg" not in P(n) and res[n]["data"].get(ct.KEY) is None for n in ("white", "edge, one step lighter", "old 7:1 gate"))
          and P("edge, passes").get("--bg") == "#303030" and json.loads(res["edge, passes"]["data"][ct.KEY]) == {"bg": "#303030"}, {n: res[n] for n in ("white", "edge, passes", "edge, one step lighter", "old 7:1 gate")})
    check("a stored muted text, body text or button outline that fails the gate (muted #222224 on the page, body text #555555, outlines #222224) is not applied and is cleared", all(P(n) == {} and res[n]["data"].get(ct.KEY) is None for n in ("muted text unreadable", "body text dim", "outlines vanish")), {n: res[n] for n in ("muted text unreadable", "body text dim", "outlines vanish")})
    check("a stored failing background beside a text orange and a label fill: the surface and text fields are dropped, the rest is kept and applied, and the cleaned look is stored", "--bg" not in P("white with an orange") and P("white with an orange").get("--orange-text") == "#ffa057" and P("white with an orange").get("--lab-bg") == "#3a2619"
          and json.loads(res["white with an orange"]["data"][ct.KEY]) == {"link": "#ffa057", "labbg": "#3a2619"}, res["white with an orange"])
    check("junk in storage (a color name, #abc, a number, an unknown key) applies nothing", P("junk") == {} and res["junk"]["cls"] == [])
    check("in the light theme nothing is applied, a saved dark look included", P("white, light theme") == {} and P("a preset, light theme") == {} and res["a preset, light theme"]["cls"] == [])
    ed = res["pure: the background edge"]["val"]
    check("the library's gate: #303030 passes, #313131 is refused naming body text on the page and the 11:1; white too; a body text, muted text or outline that fails, and a card too light for the body text (7:1), each name their pair",
          ed[0] == [] and len(ed[1]) == 1 and ed[1][0].startswith("body text would read 10.99:1 on the page (11:1 needed)") and ed[2] and ed[3] and "muted text" in ed[4][0] and "button outlines" in ed[5][0] and any("body text" in x and "cards" in x and "7:1 needed" in x for x in ed[6]), ed)
    wn = res["pure: warnings"]["val"]
    check("the library's warnings name the field that owns the pair: text and links, lines, small label text on its fill, a label outline against cards, and a solid fill against the page and cards",
          "link" in {x["k"] for x in wn[0]} and "line" in {x["k"] for x in wn[1]} and "labfg" in {x["k"] for x in wn[2]} and "labbd" in {x["k"] for x in wn[3]} and "solid" in {x["k"] for x in wn[4]}
          and all("below" in x["t"] for w_ in wn for x in w_), wn)

    # ---- a second app, the same file with other settings
    FK = "fake: "
    r = res[FK + "a stored look is applied under the app's own names"]
    check("a second app: its stored look is applied under its own property names, its own onApply sets its extras, and not one of stackshot's properties or classes is touched; its gate is the default, refuse; its key is its own",
          r["props"] == {"--page": "#0b1218", "--panel": mixp(FAKE_SHIP["fg"], "#0b1218", 4), "--panel-2": mixp(FAKE_SHIP["fg"], "#0b1218", 4), "--rule": mixp(FAKE_SHIP["fg"], "#0b1218", 10), "--accent": "#ffb000", "--cta": "#d9722e", "--on-cta": r["props"].get("--on-cta"), "--cta-hover": mixp("#000000", "#d9722e", 14)}
          and r["props"]["--on-cta"] in ("#161617", "#ffffff") and r["cls"] == ["fake-solid"] and not set(r["props"]) & set(EXPECT_PROPS) and r["val"]["key"] == "fake-app-look" and r["val"]["gate"] == "refuse"
          and r["created"] == 0 and r["fetches"] == 0 and r["val"]["res"]["bg"] == "#0b1218" and r["val"]["res"]["fg"] == FAKE_SHIP["fg"], r)
    r = res[FK + "Reset takes off everything, onApply's properties and class too"]; sn = r["snaps"]
    check("a second app: Reset and Live now take off every inline property and class the app's settings and onApply set (the extras included), and a new apply puts them back",
          "--cta-hover" in sn["before"]["props"] and sn["before"]["cls"] == ["fake-solid"] and sn["after"]["props"] == {} and sn["after"]["cls"] == [] and sn["again"]["props"] == sn["before"]["props"] and sn["again"]["cls"] == ["fake-solid"]
          and r["props"] == {} and r["cls"] == [] and r["data"].get("fake-app-look") is None, sn)
    r = res[FK + "onApply runs on every apply, Reset and Live now included, stored = {} then"]; on = r["val"]
    SIX = ["--accent", "--cta", "--page", "--panel", "--panel-2", "--rule"]
    check("a second app: onApply runs on every apply (at start, a plain apply, Reset, Live now) and for Reset and Live now with stored = {}; at its call everything the earlier apply set (onApply's own extras too) was already taken off: it sees only this apply's properties",
          len(on) == 4 and [o["stored"] for o in on] == [["bg", "link", "solid"], ["bg", "link", "solid"], [], []] and [o["before"] for o in on] == [SIX, SIX, [], []], on)
    r = res[FK + "the shipped function is called on every apply, never cached, after the tracked properties were removed"]; v = r["val"]
    check("a second app: the function for the shipped values is called on every apply (once for each), never cached, and at its call the tracked inline properties were already taken off; a changed answer is what the next apply resolves against",
          v["n"][1] == v["n"][0] + 1 and v["n"][2] == v["n"][1] + 1 and all(s == [] for s in v["sees"][1:]) and v["res"]["bg"] == FAKE_ALT["bg"] and v["ship"] == FAKE_ALT["bg"] and v["cardAlt"] == mixp(FAKE_ALT["fg"], "#0b1218", 4), v)
    r = res[FK + "isDark of the app decides, on every apply and at init (the page's data-theme is ignored)"]; sn = r["snaps"]; v = r["val"]
    check("a second app: isDark() decides (a page marked light is dark to it, and a dark one is light to it); it is asked on every apply and at init",
          sn["darkByApp"]["props"].get("--page") == "#0b1218" and sn["lightByApp"]["props"] == {} and sn["lightByApp"]["cls"] == [] and sn["darkAgain"]["props"].get("--page") == "#0b1218" and v["d"][0] >= 1 and v["d"][1] > v["d"][0] and v["d"][2] > v["d"][1] and v["isDark"] is True, r)
    r = res[FK + "isDark false beats a dark page"]
    check("a second app: isDark() false applies nothing on a page marked dark", r["props"] == {} and r["cls"] == [] and r["data"].get("fake-app-look") is not None, r)
    r = res[FK + "the refuse gate (the default) does not apply a stored white page and clears it"]
    check("a second app on the refuse gate: a stored white page is not applied and is cleared at load, as in stackshot; the gate names the pairs", r["props"].get("--page") is None and r["data"].get("fake-app-look") is None and r["val"]["gate"] == "refuse" and len(r["val"]["refuse"]) >= 1 and r["val"]["warn"][0]["k"] != "fg", r["val"])
    r = res[FK + "the warn gate applies a stored white page, keeps it and refuses nothing"]; v = r["val"]
    check("a second app on the warn gate: a stored white page is applied and kept in storage (never cleared at load), the gate refuses nothing (even body text, muted text and outlines that fail), and every failing first-six pair is a warning with its ratio",
          v["gate"] == "warn" and r["props"].get("--page") == "#ffffff" and json.loads(r["data"]["fake-warn-look"]) == {"bg": "#ffffff"} and v["refuse"] == [] and v["refuseWorse"] == [] and v["stored"] == {"bg": "#ffffff"}
          and any(w["k"] == "fg" and re.fullmatch(r"\d+\.\d\d:1 body text on the page \(below 11:1\)", w["t"]) for w in v["warn"]) and any(w["k"] == "fg" and w["t"].endswith("body text on cards (below 7:1)") for w in v["warn"])
          and any(w["k"] == "mut" for w in v["warn"]), v)
    r = res[FK + "the warn gate applies a typed combination that the refuse gate would turn down"]
    check("a second app on the warn gate: a typed combination the refuse gate would turn down is stored and applied", r["val"]["refuse"] == [] and r["val"]["stored"].get("bg") == "#ffffff" and r["snaps"]["typed"]["props"].get("--page") == "#ffffff" and r["snaps"]["typed"]["props"].get("--ink") == "#444444", r)
    r = res[FK + "the warn gate's warnings for a good dark look are the same pairs as the refuse gate's (no first six)"]; v = r["val"]
    check("a second app: for a good look the warn gate and the refuse gate warn about the same pairs (the first six pairs, which pass, add nothing)", v["w"] == v["f"], v)
    r = res[FK + "two apps on one page keep their own properties, keys and classes"]; sn = r["snaps"]
    check("two apps on one page keep their own properties, keys and classes: a reset of one leaves the other's inline properties and classes; a reset of the other takes the rest",
          {"--bg", "--orange-solid"} <= set(sn["both"]["props"]) and {"--page", "--cta"} <= set(sn["both"]["props"]) and sn["both"]["cls"] == ["ct-on", "ct-wl", "fake-solid"]
          and "--page" not in sn["afterFakeReset"]["props"] and "--cta-hover" not in sn["afterFakeReset"]["props"] and "--bg" in sn["afterFakeReset"]["props"] and sn["afterFakeReset"]["cls"] == ["ct-on", "ct-wl"]
          and sn["afterBothReset"]["props"] == {} and sn["afterBothReset"]["cls"] == [] and r["val"]["keys"] == [ct.KEY, "fake-app-look"], sn)
    r = res[FK + "the minimal settings (a key and the shipped values) work: nothing is set, nothing is drawn, nothing is asked"]
    check("a second app with only a key and the shipped values: the stored look resolves, nothing is set inline (no vars), nothing is drawn, nothing is asked of the network, and the gate is the default", r["props"] == {} and r["created"] == 0 and r["fetches"] == 0 and r["val"]["res"]["bg"] == "#0b1218" and r["val"]["res"]["link"] == "#ffb000"
          and r["val"]["gate"] == "refuse" and r["val"]["dark"] is True, r)
    r = res[FK + "a light page keeps a stored dark look untouched whatever the shipped function answers there, and the dark page applies it again"]; sn = r["snaps"]; v = r["val"]
    check("a second app on a light page: a stored dark look is neither read through the gate nor cleared (the shipped function answers with light values there), nothing is set inline, onApply is called with nothing stored, and the dark page applies the look again",
          json.loads(v["kept"]) == {"bg": "#0b1218", "solid": "#d9722e"} and json.loads(v["after"]) == {"bg": "#0b1218", "solid": "#d9722e"} and sn["light"]["props"] == {} and sn["lightAgain"]["props"] == {} and sn["light"]["cls"] == []
          and [o["stored"] for o in v["log"]["on"]][:2] == [[], []] and sn["dark"]["props"].get("--page") == "#0b1218" and sn["dark"]["props"].get("--cta") == "#d9722e", r)
    r = res[FK + "a shipped function that answers with something that is not an object falls back to nothing and does not stop the tool"]
    check("a second app whose shipped function answers with something that is not an object: the shipped values are empty until it answers with an object, and nothing throws", r["err"] is None and r["val"] == {"empty": 0, "then": FAKE_SHIP["bg"]}, r)
    r = res[FK + "shipped followers"]; v = r["val"]; FS = FAKE_SHIP
    wk = lambda lk, cd: mixp(lk, cd, 16)
    check("a second app's own labbg labfg labbd disbg disfg are the values in use while nothing they follow is set (they are not worked out from the link and the solid)",
          r["err"] is None and {k: v["none"][k] for k in ("labbg", "labfg", "labbd", "disbg", "disfg")} == {k: FS[k] for k in ("labbg", "labfg", "labbd", "disbg", "disfg")} and v["none"] == {**FS, "ifill": FS["ifill"]}
          and FS["labbg"] != wk(FS["link"], FS["card"]) and FS["disbg"] != mixp(FS["solid"], FS["bg"], 50), r)
    check("a second app: setting the text and links works the three small labels out from it (fill = 16% over the cards) and leaves the disabled pair as the app ships it",
          (v["link"]["labbg"], v["link"]["labfg"], v["link"]["labbd"]) == (wk("#ffb000", FS["card"]), "#ffb000", "#ffb000") and (v["link"]["disbg"], v["link"]["disfg"]) == (FS["disbg"], FS["disfg"]), v["link"])
    check("a second app: setting the solid fill works the disabled pair out from it (fill = solid at half over the page, text = its label at half) and leaves the small labels as the app ships them",
          (v["solid"]["disbg"], v["solid"]["disfg"]) == (mixp("#d9722e", FS["bg"], 50), mixp(v["solid"]["onsolid"], FS["bg"], 50)) and (v["solid"]["labbg"], v["solid"]["labfg"], v["solid"]["labbd"]) == (FS["labbg"], FS["labfg"], FS["labbd"]), v["solid"])
    check("a second app: setting only the text on solid fills works the disabled text out and keeps the disabled fill and the labels as shipped",
          v["onsolid"]["disfg"] == mixp("#000000", FS["bg"], 50) and v["onsolid"]["disbg"] == FS["disbg"] and v["onsolid"]["labbg"] == FS["labbg"], v["onsolid"])
    cardbg = mixp(FS["fg"], "#0b1218", 4)
    check("a second app: setting the page background works out the cards, the label fill and the disabled pair on it, and keeps the label text and outline as shipped; a set card moves the label fill only",
          (v["bg"]["card"], v["bg"]["labbg"], v["bg"]["disbg"], v["bg"]["disfg"]) == (cardbg, wk(FS["link"], cardbg), mixp(FS["solid"], "#0b1218", 50), mixp(FS["onsolid"], "#0b1218", 50)) and (v["bg"]["labfg"], v["bg"]["labbd"]) == (FS["labfg"], FS["labbd"])
          and v["card"]["labbg"] == wk(FS["link"], "#222224") and (v["card"]["labfg"], v["card"]["disbg"]) == (FS["labfg"], FS["disbg"]), (v["bg"], v["card"]))
    check("a second app: a field that is set wins over both the shipped value and the follow rule", v["own"]["labbg"] == "#222224" and v["own"]["disfg"] == "#ffffff" and v["own"]["labfg"] == FS["labfg"] and v["own"]["disbg"] == FS["disbg"], v["own"])
    check("a second app: the shipped values as a whole are no set field (norm drops all of them), and a value that is only what the follow rule gives is a set field, because it differs from what the app ships",
          v["snap"] == {} and v["worked"] == {"labbg": wk(FS["link"], FS["card"]), "disbg": mixp(FS["solid"], FS["bg"], 50)} and v["again"] == {"link": "#ffb000", "solid": "#d9722e"}, (v["snap"], v["worked"], v["again"]))
    check("the fields a field follows are one table the tool shows (FOLLOWS): the label fill follows text and links, background and cards; the other labels the text and links; the disabled pair the solid fill, the text on it and the background",
          v["follows"] == {"card": ["bg"], "line": ["bg"], "onsolid": ["solid"], "labbg": ["link", "bg", "card"], "labfg": ["link"], "labbd": ["link"], "disbg": ["solid", "bg"], "disfg": ["solid", "onsolid", "bg"]}
          and "FOLLOWS[k].some(function (d) { return s[d]; })" in LIB and "DEP" not in LIB, v["follows"])
    r = res[FK + "shipped followers, one malformed and one missing"]; v = r["val"]
    check("a second app whose labbg is not a #rrggbb, whose labfg is missing and whose disbg is not a string: those three are worked out as before, the others are shipped", r["err"] is None and (v["none"]["labbg"], v["none"]["labfg"], v["none"]["disbg"]) == (v["worked"]["labbg"], v["worked"]["labfg"], v["worked"]["disbg"])
          and v["none"]["labbd"] == FS["labbd"] and v["none"]["disfg"] == FS["disfg"], r)
    r = res[FK + "shipped followers, answered by a function and changed between applies"]
    check("a second app whose shipped function changes its followers between applies: the next apply reads the new ones (nothing is cached)", r["err"] is None and r["val"]["labbg"] == "#222224" and r["val"]["disfg"] != "#eeeeee" and r["val"]["r1"]["labfg"] == FS["labfg"], r)
    r = res[FK + "shipped followers in uppercase"]; v = r["val"]
    check("a second app that ships its followers in uppercase hex is read as if it shipped them in lowercase: the values in use are lowercase, the shipped set as a whole is still no set field, and a stored lowercase copy of one of them is dropped by norm",
          r["err"] is None and v["none"]["labbg"] == "#173046" and v["none"]["disbg"] == "#2a3a4a" and v["none"]["disfg"] == "#9fb0c0" and v["snap"] == {} and v["lower"] == {} and v["link"]["disbg"] == "#2a3a4a", r)
    r = res["stackshot: its five shipped followers against what the engine works out from the live fields"]; v = r["val"]
    check("stackshot's five shipped followers (labbg labfg labbd disbg disfg) are its own values (the small labels orange text on a dark brown fill, the disabled pair flat grey; the Old orange preset has dark text on the orange labels, the same disabled pair), which the follow rule would not give: the panel shows them while nothing they follow is set, and they differ from what the engine works out from the live fields with those five left out",
          r["err"] is None and {k: v["shipped"][k] for k in ("labbg", "labfg", "labbd", "disbg", "disfg")} == {"labbg": "#3a2619", "labfg": "#f0a06a", "labbd": "#3a2619", "disbg": PRE["old"]["disbg"], "disfg": PRE["old"]["disfg"]}
          and all(v["shipped"][k] != v["worked"][k] for k in ("labbg", "disbg", "disfg")) and v["worked"]["labbg"] == mixp(SH["link"], SH["card"], 16), r)
    check("the shared file names no screen, route or wording of the app that owns it: no 'board', no 'fleet', no example color of the app; the three lines the app may replace are in cfg.text with neutral defaults",
          not re.search(r"\bboard\b|fleet|#ec8a47", LIB, re.I) and "cfg.text" in LIB and "signIn: 'Sign in to use saved combinations.'" in LIB and "note: 'Dark theme only. The look you apply is kept in this browser.'" in LIB and "example: '#4a90d9'" in LIB
          and re.search(r"^ \*   text +optional \{signIn, note, example\}", LIB, re.M) is not None, None)
    check("stackshot passes its own three lines in cfg.text: the sign-in line names the board, the note says the saved combinations are shared with the fleet tool's web page, the example is the shipped text orange",
          ct.TEXT == {"signIn": "Sign in to the board to use saved combinations.", "note": "Dark theme only. The look you apply is kept in this browser; saved combinations are shared with the fleet tool's web page.", "example": SH["link"]} and ",text:" in ct.CFG_JS, ct.TEXT)

# ---- 5. the stylesheet of the button and the panel
check("the stylesheet of the library was read (it is a joined array of strings in the file)", len(CSS_LIB) > 3000 and ".ct-pop{" in CSS_LIB and ".ct-btn{" in CSS_LIB, len(CSS_LIB))
pop_rule = re.search(r"\.ct-pop\{([^}]*)\}", CSS_LIB).group(1)
check("the panel is fixed in the page (placed from the button's rectangle by the script), above the reload and Back to top buttons (their z-index is 10), at most the screen tall and scrolling inside itself (overscroll contained), and 366 px wide at most, 16 px less than the screen",
      "position:fixed" in pop_rule and int(re.search(r"z-index:(\d+)", pop_rule).group(1)) > 10 and "z-index:10;" in SRCT["ui/render.py"].split("#totop,.fab{")[1].split("}")[0] + ";" and "max-height:calc(100dvh - 16px)" in pop_rule and "overflow-y:auto" in pop_rule and "overscroll-behavior:contain" in pop_rule
      and "width:min(366px,calc(100vw - 16px))" in pop_rule and "document.body.appendChild(pop)" in LIB, pop_rule)
check("the panel is placed upward from the button (bottom set from the button's top, top auto), downward only when there is no room above, and placed again on resize and on any scroll",
      "pop.style.top = 'auto'; pop.style.bottom = (vh - rc.top + 8) + 'px'" in LIB and "if (above < 160 && below > above)" in LIB and "window.addEventListener('resize', place)" in LIB and "window.addEventListener('scroll', place, true)" in LIB)
BTN_CALL = re.search(r"var btn = el\('button', \{([^}]*)\}, \[([^\]]*)\]\);", LIB)
check("the button is a bare circle of the live page color (upper left half) and the live solid fill (lower right half), split by a diagonal line (135deg), with no text node and no frame: a gradient of --ct-a and --ct-b, set on the button from the resolved bg and solid on every apply; it is named by aria-label Colors",
      "background:linear-gradient(135deg,var(--ct-a,transparent) 50%,var(--ct-b,transparent) 50%)" in CSS_LIB and "90deg" not in re.search(r"\.ct-dot\{[^}]*\}", CSS_LIB).group(0) and "btn.style.setProperty('--ct-a', r.bg); btn.style.setProperty('--ct-b', r.solid);" in LIB
      and BTN_CALL is not None and "'aria-label': 'Colors'" in BTN_CALL.group(1) and BTN_CALL.group(2).strip() == "dot" and "text:" not in BTN_CALL.group(2) and "el('span', { text: 'Colors' })" not in LIB
      and re.search(r"\.ct-btn\{[^}]*border:0;[^}]*background:none", CSS_LIB) is not None, BTN_CALL.group(0) if BTN_CALL else None)
check("every field group is its own box with a heading in the side panel's section style (uppercase, 12 px, 600, letter-spacing .06em) but in the link color (--ct-link, set on the panel from the live text-and-links field; --fg when unset), with its fields indented under it (.ct-rows); the presets and the saved combinations share one box (#ct-dock, two sections)",
      ".ct-box{" in CSS_LIB and ".ct-gh{margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ct-link,var(--fg))}" in CSS_LIB and ".ct-rows{margin:0 0 0 14px}" in CSS_LIB
      and "pop.style.setProperty('--ct-link', r.link)" in LIB and "el('div', { className: 'ct-box', id: 'ct-dock' }, secs)" in LIB and "id: 'ct-g-presets', text: 'Presets'" in LIB
      and re.search(r"#panel section h2,#panel section h2\.hdr\{font-size:12px;font-weight:600;letter-spacing:\.06em;text-transform:uppercase;color:var\(--fg\)", SRCT["ui/render.py"]) is not None
      and "previewBox = box('ct-g-preview', 'Preview', [prev])" in LIB and "box('ct-g-' + g.toLowerCase().replace(/ /g, '-'), g, [el('div', { className: 'ct-rows' }, kids)])" in LIB and "id: 'ct-g-saved'" in LIB, None)
check("a saved-list answer (the read, a save, a delete, and each of their errors) is drawn inside keepEnd, which decides whether the panel is at its end when the answer arrives (not when the request left) and scrolls to the end again only then",
      "function atEnd() { return pop.scrollTop + pop.clientHeight >= pop.scrollHeight - 2; }" in LIB and "function keepEnd(fn) { var stick = atEnd(); fn(); if (stick) toEnd(); }" in LIB and LIB.count("keepEnd(function") == 6 and "stick" not in LIB.split("function list()")[1].split("function useNow")[0]
      and "call('/delete', { id: id }).then(function (d) { keepEnd(function () { draw(d); say('ct-n-saved', 'Deleted.'); }); }" in LIB and "(had ? 'Replaced ' : 'Saved ') + name + '.'); }); }" in LIB)
check("the Preview box is outside the fold: it is not one of the boxes of #ct-fields but is appended to the panel right after the Fields button, before the dock, so it stays drawn when the fields are folded",
      "boxes.push(previewBox)" not in LIB and "boxes.push(box('ct-g-preview'" not in LIB and "var fields = el('div', { className: 'ct-fields', id: 'ct-fields' }, boxes);" in LIB
      and re.search(r"pop\.appendChild\(foldBtn\);\s*if \(previewBox\) pop\.appendChild\(previewBox\);\s*pop\.appendChild\(el\('div', \{ className: 'ct-box', id: 'ct-dock' \}", LIB) is not None, None)
check("the Fields fold: a button (#ct-fold, aria-expanded, aria-controls=ct-fields) above the dock folds the 14 fields (#ct-fields, hidden at first); its state is kept in this browser and read when the panel opens; the panel keeps its end in view; Save is one word on one line",
      "id: 'ct-fold', 'aria-expanded': 'false', 'aria-controls': 'ct-fields', text: 'Fields'" in LIB and "fields.hidden = true;" in LIB and "if (t.id === 'ct-fold') fold(foldBtn.getAttribute('aria-expanded') !== 'true', true);" in LIB and "function toEnd() { pop.scrollTop = pop.scrollHeight; }" in LIB
      and "id: 'ct-save', text: 'Save' }" in LIB and "Save current" not in LIB and ".ct-save .ct-b{flex:none;white-space:nowrap}" in CSS_LIB and ".ct-fields[hidden]{display:none}" in CSS_LIB)
non_token = re.findall(r"(?<![\w-])#[0-9a-fA-F]{3,8}\b", CSS_LIB)
check("the button and panel read only existing tokens (--card --fg --mut --ibd --bg --line --ifill), with no color literal but black shadows", not non_token and set(re.findall(r"var\((--[\w-]+)", CSS_LIB)) <= {"--card", "--fg", "--mut", "--ibd", "--c", "--line", "--bg", "--ifill", "--ct-a", "--ct-b", "--ct-link"}
      and not re.search(r"var\(--(acc|call|orange|t-you|selbg)", CSS_LIB), (non_token, set(re.findall(r"var\((--[\w-]+)", CSS_LIB))))
check("keyboard: every control is a button or an input, a visible focus ring on them (2px, --fg, not the accent), Escape closes the panel and returns focus to the button", ".ct-pop .ct-b:focus-visible" in CSS_LIB and "outline:2px solid var(--fg)" in CSS_LIB
      and "e.key === 'Escape'" in LIB and "btn.focus()" in LIB and "setAttribute('aria-expanded'" in LIB and "tabindex" not in CSS_LIB and LIB.count("tabindex") == 0 and "}, true);" in LIB, None)
check("a click outside the button and the panel closes it, and the panel and button are not printed", "path.indexOf(pop) >= 0 || path.indexOf(wrap) >= 0" in LIB and "document.addEventListener('click', function (e) {" in LIB and "@media print{.ct,.ct-pop{display:none}}" in CSS_LIB)
check("a coarse pointer gets 44 px targets: the buttons, the picker and the hex box", "@media(pointer:coarse){.ct-b{min-height:44px}.ct-btn{min-width:44px}.ct-pick{width:44px;height:44px}.ct-hex{min-height:44px}}" in CSS_LIB)
check("the hex box is 16 px so a phone does not zoom on it, and the notes and the Now line are polite live regions (only the library's helper writes the role and aria-live; the settings' script has none)",
      re.search(r"\.ct-hex\{[^}]*font:16px ui-monospace", CSS_LIB) and LIB.count("'aria-live'") == 1 and LIB.count("role: 'status'") == 1 and "function live(id, cls, text)" in LIB and "live('ct-n-presets')" in LIB and "live('ct-cur', 'ct-cur', 'Now: Live now')" in LIB
      and "live('ct-n-store')" in LIB and "live('ct-n-' + k)" in LIB and "live('ct-n-saved')" in LIB and "aria-live" not in CFG_ONLY)
check("a row's name is a real label for its hex box (label for=ct-h-<key>), in a div of its own class ct-rl, which is not the html class ct-lab the settings use (html.ct-lab must not pick up the row's bold weight)",
      "el('label', { for: 'ct-h-' + k, id: 'ct-l-' + k, text: f[1] })" in LIB and "className: 'ct-rl'" in LIB and ".ct-rl{font-weight:600" in CSS_LIB and "ct-lab" not in LIB, None)
check("a refused saved combination says so next to the tap: the 'Not applied' sentence of the gate goes to the saved note (named with the combination) and stays; arming Delete on a row resets every other row's label to Delete; a note's text is set only when it changes",
      "say('ct-n-saved', c.name + ': ' + (sticky ? sticky.t : 'Not applied.'))" in LIB and "n.scrollIntoView({ block: 'nearest' })" in LIB and "$('ct-list').querySelectorAll('.ct-del').forEach(function (x) { if (x !== b) x.textContent = 'Delete'; })" in LIB
      and "function txt(e, t) { if (e.textContent !== t) e.textContent = t; }" in LIB and "var say = function (id, t) { var e = $(id); if (e && e.textContent !== t) e.textContent = t; }" in LIB, None)
check("a typed hex applies at once at six digits (with or without #), three digits are expanded on leaving the box, anything else keeps the last good value and says 'Use six digits like #f0a06a.'", "/^#?[0-9a-f]{6}$/i.test(i.value.trim())" in LIB
      and "v.replace(/./g, function (c) { return c + c; })" in LIB and "'Use six digits like ' + (X.example || T.example) + '.'" in LIB and "maxlength: '7'" in LIB)
check("low-contrast pairs are marked, not dropped: a warning is a note under the field with the ratio (floored, so 4.499 never shows as 4.50), a preset with any is dashed and named in its label", "'Below its limit: '" in LIB and ".ct-preset.low{border-style:dashed}" in CSS_LIB
      and "classList.toggle('low'" in LIB and "function fx(v) { return (Math.floor(v * 100) / 100).toFixed(2); }" in LIB)
check("a change goes through one gate: it is cleaned, checked on the resolved combination and, if it passes, stored and applied; a refusal says 'Not applied:' with the pair and the needed ratio and changes nothing (the same for a preset and a saved combination)",
      "function commit(n, k) {" in LIB and "n = norm(n); var bad = refuse(resolve(n));" in LIB and "'Not applied: ' + bad.join('; ') + '.'" in LIB and "save(n); kept(n); apply();" in LIB and LIB.count("commit(") >= 4)
check("the gate's text color is the stylesheet's own --fg, so the head script (which runs before the page's style) and the panel agree with the page", SH["fg"] == tk["--fg"] and '"fg_bg": 11' not in LIB and "fg_bg: 11" in LIB)
check("a stored value goes through the same gate: load() reads a valid map (an older text as link), cleans it, and one that fails the REFUSE pairs is cleared from storage; apply() reads only load(); the warn gate never clears",
      "if (refuse(resolve(s)).length) { ['bg', 'card', 'fg', 'mut', 'ibd'].forEach(function (k) { delete s[k]; }); s = norm(s); bad = true; }" in LIB and "if (bad) save(s);" in LIB and "if (ok(o.text) && !ok(o.link)) o.link = o.text;" in LIB
      and "var dk = isDark(), s = dk ? load() : {}, r = dk ? resolve(s) : {};" in LIB and "if (GATE === 'warn') return o;" in LIB)
check("storage that keeps nothing (off or full) is said in one line in the panel instead of a pick that seems to do nothing: a pick is read back and the note p#ct-n-store is filled when it did not stay",
      "live('ct-n-store')" in LIB and "function kept(s)" in LIB and "save(n); kept(n); apply();" in LIB and "storeOff: 'This browser does not allow saving here, so a pick has no effect.'" in LIB)
check("Reset clears the whole look and applies; the saved list is untouched (no call in it)", "$('ct-reset').addEventListener('click', function () { save({}); apply(); sticky = null;" in LIB and "call(" not in LIB.split("$('ct-reset')")[1].split("});")[0])
check("saved combinations: Save sends the 14 resolved values under the name (a name box of 40, trimmed, 'Replaced' when the name is on the list case-insensitively); a saved name is drawn with textContent, never as markup; Delete takes a second tap ('Delete?') within 4 s",
      "KEYS.forEach(function (k) { v[k] = r[k]; })" in LIB and "a.textContent = c.name" in LIB and LIB.count("innerHTML") == 2 and "prev.innerHTML = cfg.preview" in LIB and "(had ? 'Replaced ' : 'Saved ') + name" in LIB and "c.name.toLowerCase() === name.toLowerCase()" in LIB
      and "b.textContent = 'Delete?'" in LIB and "}, 4000)" in LIB and "needName: 'Give it a name first.'" in LIB and "maxlength: '40'" in LIB)
check("saved combinations: an error shows the server's own sentence (the answer's error), else a plain one for 403, offline and the rest; the applied look is never touched by a failed call; a failed read leaves the presets and fields working",
      "d && d.error ? d.error : (r.status === 403 ? (X.signIn || T.signIn) : T.savedOff)" in LIB and "signIn: 'Sign in to use saved combinations.'" in LIB and "savedOffline: 'Saved combinations are not available right now (offline?).'" in LIB
      and "function list() {\n        if (!API) return; say('ct-n-saved', '');" in LIB and "call('').then(function (d) { keepEnd(function () { draw(d); }); }, function (x) { keepEnd(function () { say('ct-n-saved', msg(x));" in LIB and "save(" not in LIB.split("function call(path, body)")[1].split("function useNow")[0].replace("save(this", ""), None)
check("the saved list and the preview are optional: without cfg.api there is no Saved box, without cfg.preview no Preview box; the preview is rendered inert and hidden from assistive technology; the only markup the library takes from the settings is cfg.preview",
      "if (cfg.preview) {" in LIB and "if (API) {" in LIB and "prev.setAttribute('inert', '')" in LIB and "'aria-hidden': 'true'" in LIB and LIB.count("cfg.preview") == 2, None)
check("the settings' preview strip is inert-ready and holds the real classes: an enabled and a disabled main button, a plain and a disabled plain button, the Your move tag, a recommended badge and a link, none of them focusable",
      ct.PREVIEW.count('class="b main"') == 2 and ct.PREVIEW.count(" disabled>") == 2 and ct.PREVIEW.count('class="b"') == 2 and '<span class="tag t-you">' in ct.PREVIEW and '<span class="rec badge">' in ct.PREVIEW and "<a>" in ct.PREVIEW and ct.PREVIEW.count('tabindex="-1"') == 4 and "<form" not in ct.PREVIEW)
check("a button is only drawn while the page is dark and its mount exists: init waits for the document when the mount is not there yet, a light page draws nothing and hides what it drew, remount moves the button and places the panel again",
      "if (!isDark()) return;" in LIB and "document.addEventListener('DOMContentLoaded'" in LIB and "if (!dk) { if (ui) { ui.wrap.hidden = true; ui.close(); } return; }" in LIB and "t.appendChild(ui.wrap); ui.place();" in LIB and "function remount(m) {" in LIB)

# ---- 6. the contrast (WCAG 2.x, tests/_colors.py): the library's numbers against an independent computation
def fxp(v): return f"{math.floor(v * 100) / 100:.2f}"
def py_refuse(p): return [(a, b) for a, b, mn in (("fg", "bg", LIM["fg_bg"]), ("fg", "card", LIM["fg_card"]), ("mut", "bg", LIM["mut"]), ("mut", "card", LIM["mut"]), ("ibd", "bg", LIM["ibd"]), ("ibd", "card", LIM["ibd"])) if C.ratio(p[a], p[b]) < mn]
def py_warn(p, first_six=False, set_solid=True):
    far = "#000000" if set_solid and C.lum(p["onsolid"]) > C.lum(p["solid"]) else p["fg"]      # the hover blends toward black only for a solid fill or label that was set and has a lighter label
    six = [("fg", p["fg"], p["bg"], LIM["fg_bg"], "body text on the page"), ("fg", p["fg"], p["card"], LIM["fg_card"], "body text on cards"), ("mut", p["mut"], p["bg"], LIM["mut"], "muted text on the page"),
           ("mut", p["mut"], p["card"], LIM["mut"], "muted text on cards"), ("ibd", p["ibd"], p["bg"], LIM["ibd"], "button outlines on the page"), ("ibd", p["ibd"], p["card"], LIM["ibd"], "button outlines on cards")] if first_six else []
    pairs = six + [("link", p["link"], p["bg"], LIM["link"], "on the page"), ("link", p["link"], p["card"], LIM["link"], "on cards"), ("solid", p["solid"], p["bg"], LIM["solid"], "against the page"), ("solid", p["solid"], p["card"], LIM["solid"], "against cards"),
             ("onsolid", p["onsolid"], p["solid"], LIM["onsolid"], "at rest"), ("onsolid", p["onsolid"], mixp(far, p["solid"], CONST["HOVER"] if res else 14), LIM["onsolid"], "hovered"), ("onsolid", p["onsolid"], mixp(far, p["solid"], CONST["PRESSED"] if res else 24), LIM["onsolid"], "pressed"),
             ("labfg", p["labfg"], p["labbg"], LIM["lab"], "on the label fill")] + ([("labbd", p["labbd"], p["card"], LIM["labbd"], "against cards")] if p["labbd"] != p["labbg"] else []) + [
             ("disfg", p["disfg"], p["disbg"], LIM["dis"], "on the disabled fill"), ("line", p["line"], p["card"], LIM["line"], "against cards: lines would disappear")]
    return [{"k": k, "t": f"{fxp(C.ratio(a, b))}:1 {t} (below {mn:g}:1)"} for k, a, b, mn, t in pairs if C.ratio(a, b) < mn]
if res:
    for pid, nm_, vals in PRESETS:
        full = {**SH, **vals}
        check(f"preset {nm_}: every REFUSE pair passes (body text 11:1 on the page and 7:1 on cards, muted text 4.5:1 and button outlines 3:1 on both), in the library and in Python", pre[pid]["refuse"] == [] and py_refuse(full) == [], (pre[pid]["refuse"], py_refuse(full)))
        check(f"preset {nm_}: the library's WARN list is the independent computation's: " + (", ".join(w["t"] for w in py_warn(full)) or "none"), pre[pid]["warn"] == py_warn(full), (pre[pid]["warn"], py_warn(full)))
    EXPECT_WARN = {"live": [], "old": [], "two": [], "radix": ["onsolid", "onsolid"], "primer": []}
    check("the WARN list per preset is exactly the expected one: Live now and Old orange none (the shipped look passes every pair), Radix its white label at rest and hovered (2.97:1, 3.93:1), the rest none; a changed preset or a changed shipped token fails here",
          {i: [w["k"] for w in pre[i]["warn"]] for i in pre} == EXPECT_WARN and pre["radix"]["warn"][0]["t"].startswith("2.97:1") and pre["radix"]["warn"][1]["t"].startswith("3.93:1"), {i: pre[i]["warn"] for i in pre})
    check("Radix text on solid fills is below 4.5:1 at rest and hovered (white on the fill, the hover toward black) but passes pressed, and a dark label on its fill would read 6.09:1 on the page and 5.54:1 on cards", C.ratio("#ffffff", "#f76b15") < 3 and C.ratio("#ffffff", mixp("#000000", "#f76b15", 24)) >= 4.5
          and f"{C.ratio('#161617', '#f76b15'):.2f}" == "6.09" and f"{C.ratio('#1f1f21', '#f76b15'):.2f}" == "5.54", C.ratio("#ffffff", "#f76b15"))
    # the "warn" gate's list is the independent computation's too: the first six pairs first, then the rest, for a look the refuse gate would turn down
    wlook = res["fake: the warn gate applies a stored white page, keeps it and refuses nothing"]["val"]["res"]
    wv = res["fake: the warn gate applies a stored white page, keeps it and refuses nothing"]["val"]["warn"]
    check("the warn gate's list for a stored white page is the independent computation's: the failing first-six pairs first, then the others", [w["t"] for w in wv] == [w["t"] for w in py_warn(wlook, first_six=True, set_solid=False)] and len(wv) >= 6, (wv, py_warn(wlook, True, False)))
fg, mut, ibd = tk["--fg"], tk["--mut"], tk["--ibd"]
passes = lambda bg: C.ratio(bg, fg) >= LIM["fg_bg"] if res else False
card_of = lambda bg: mixp(fg, bg, 4)
check(f"the gate's edge: #303030 reads {C.ratio('#303030', fg):.3f}:1 against the body text and passes, #313131 reads {C.ratio('#313131', fg):.3f}:1 and is refused, #4c4c4c (which a 7:1 gate let through) and #ffffff are refused",
      passes("#303030") and not passes("#313131") and not passes("#4c4c4c") and not passes("#ffffff") and all(passes(p[2]["bg"]) for p in PRESETS[1:]) if res else False, None)
worst = {"body text on the card": (99, None), "muted text on the card": (99, None), "muted text on the page": (99, None), "outlines on the page": (99, None), "outlines on the card": (99, None), "the shipped orange on the card": (99, None)}; n_pass = 0
for r_ in range(0, 0xa1, 4):
    for g_ in range(0, 0xa1, 4):
        for b_ in range(0, 0xa1, 4):
            bg = "#%02x%02x%02x" % (r_, g_, b_)
            if not passes(bg): continue
            n_pass += 1; cd = card_of(bg)
            for k, v in (("body text on the card", C.ratio(fg, cd)), ("muted text on the card", C.ratio(mut, cd)), ("muted text on the page", C.ratio(mut, bg)), ("outlines on the page", C.ratio(ibd, bg)), ("outlines on the card", C.ratio(ibd, cd)), ("the shipped orange on the card", C.ratio(tk["--orange"], cd))):
                if v < worst[k][0]: worst[k] = (v, bg)
need = {"body text on the card": LIM["fg_card"], "muted text on the card": LIM["mut"], "muted text on the page": LIM["mut"], "outlines on the page": LIM["ibd"], "outlines on the card": LIM["ibd"], "the shipped orange on the card": LIM["link"]} if res else {}
check(f"every background that passes the gate ({n_pass} colors sampled over the dark corner of the cube, the extreme hues included), with the Cards the 4% rule gives and the shipped text, passes all six REFUSE pairs and keeps the shipped orange on its card at 4.5:1: worst "
      + ", ".join(f"{k} {v[0]:.2f} at {v[1]}" for k, v in worst.items()), n_pass > 5000 and all(worst[k][0] >= need[k] for k in need), worst)
check("a free solid pick takes whichever of the dark and the white label reads better; the library's dark label is its own near-black", "function label(c) { return ratio(DK, c) >= ratio(WH, c) ? DK : WH; }" in LIB and (CONST["DK"] == "#161617" and CONST["WH"] == "#ffffff" if res else False))
if os.environ.get("COLOR_TRIAL_LIST") and res:
    for pid in pre: print(f"  {pid}: refuse {pre[pid]['refuse']}  warn {[w['t'] for w in pre[pid]['warn']]}")

# ---- 7. what the other tests rely on, and no trace of the retired temporary feature
PRESET_HEX = ({v for p in PRESETS for v in p[2].values()} | set(SH.values())) - {SH["link"], SH["bg"], SH["card"], SH["onsolid"]} if res else set()
band = lambda hx: 8.0 <= C.hsl(hx)[0] <= 38.0 and C.hsl(hx)[1] >= 0.20 and 0.06 <= C.hsl(hx)[2] <= 0.98
in_band = sorted(h for h in PRESET_HEX if band(h))
check("the preset oranges are in the orange scan's band (so the scan reads the pages without the tool's script blocks and skips the shared file): " + " ".join(in_band), len(in_band) >= 8 and all(h in LIB for h in in_band if h != SH["disbg"]), in_band)
check("with the tool in place the pages carry the preset oranges; with its script blocks cut out not one is left (pages and the shared file's own text aside)", all(any(h in p for p in PAGES.values()) for h in in_band) and
      not [h for h in in_band if h != SH["labbg"] for p in PAGES.values() if h in C.without_colortool(p)], [h for h in in_band if h != SH["labbg"] for p in PAGES.values() if h in C.without_colortool(p)][:3])      # the shipped small-label fill is in the stylesheet itself
OLD = ("SAMPLE-RETIRED-BUTTON", "sampleRetiredTool", "retiredsample", "strip_sample_button", "sr-btn", "sr-pop", "html.sr-", "'sr-", '"sr-', "retired sample panel", "Retired: a sample panel", "sample retirement")
skip_dirs = {"__pycache__", "node_modules", "screenshots"}      # and every folder whose name starts with a dot (.git, .claude, .venv, .suitemap: a checkout's tools and generated records, not sources)
def stale_in(top, skip_self=True):
    """The files of a tree that name the retired feature: sources, tests and documents; a dot-folder and a generated record are not walked."""
    out = []
    for root, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for f in files:
            if f.endswith((".py", ".md", ".js", ".sh", ".toml", ".html", ".yml", ".json")) and not (skip_self and f == "color_trial_scenario.py"):
                pth = os.path.join(root, f)
                if os.path.getsize(pth) > 3_000_000: continue
                try: txt = pathlib.Path(pth).read_text(encoding="utf-8")
                except UnicodeDecodeError: continue
                hit = [w for w in OLD if w in txt]
                if hit: out.append((os.path.relpath(pth, top), hit))
    return out
stale = stale_in(STACK)
probe = T / "stale_probe"; (probe / ".suitemap").mkdir(parents=True); (probe / "src").mkdir()
(probe / ".suitemap" / "map.json").write_text('{"m": ["retiredsample", "strip_sample_button"]}', encoding="utf-8"); (probe / "src" / "old.py").write_text("import retiredsample\n", encoding="utf-8"); (probe / "src" / "new.py").write_text("import colortool\n", encoding="utf-8")
check("the scan walks real sources only: a dot-folder such as a CI run's .suitemap that holds the old module names is skipped, a source file that names them is found, one that does not is not", [x[0] for x in stale_in(probe)] == [os.path.join("src", "old.py")], stale_in(probe))
check("no source, test or document names the retired temporary feature (its markers, its module, its global, its ids and classes, its removal notes)", not stale, stale[:6])

if fails: print(f"FAILED: color trial scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: color trial scenario, {len(ran)} checks")
