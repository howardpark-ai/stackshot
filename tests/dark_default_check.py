"""Browser check of the shipped dark look: on a rendered page in a real browser, the dark theme with nothing stored computes to the shipped look (the original orange look: orange text on a dark brown fill for the small labels, checked against its own 14 fields), the light theme computes as it
did, a colored preset of the Colors panel changes the look, and Reset in the panel returns a changed look to the shipped one. The static proof (the stylesheet's tokens against the 14 fields, the
light theme's token block) is tests/dark_default_scenario.py, which CI runs; this one needs the browser (once per machine: uvx playwright@1.63.0 install chromium) and is run by hand, like the other checks.

The page is the item page of the Board, rendered with no server; a row of the elements that show each of the 14 fields is added to it (a card, a line, muted text, a link, a secondary button, the main
button, the disabled secondary and idle main buttons, an orange badge, a rec badge and a Your move tag), and their computed styles are read.

    tests/run-suite dark_default_check        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch, _instance

tmp = _scratch.mkdtemp(prefix="darkcheck-"); T = pathlib.Path(tmp)
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
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] ask with options", "description": "A thing. It lives here.", "status": "open", "updated": now - 3 * H, "state_updated": now - 3 * H,
                                              "confirmed": now - 3 * H, "metadata": {"owner": HERE, "project": "projects/alpha", "needs": ["decision"], "ask": "Decide: whether to ship · Recommend: ship · Stakes: none · By: no date",
                                              "options": [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}], "mover": "Oliver", "then": "home-other", "next": "Oliver: decide"}}))
(T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from ui import render, colortool as ct
import search as sm
Bd = lambda: render.Board(f"{tmp}/store", now=None)
sm.sync(Bd())
PAGE = T / "item.html"
PAGE.write_text(Bd().item_html("a1", answer={"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}), encoding="utf-8")

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

def rgb(h): return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
OLD = ct.SHIPPED                                    # the shipped look, whose 14 fields tests/dark_default_scenario.py pins

PROBE = """() => {
  const old = document.getElementById('dd-probe'); if (old) old.remove();
  const d = document.createElement('div'); d.id = 'dd-probe';
  d.innerHTML = '<div id="dd-card" style="background:var(--card);border:1px solid var(--line)"><p id="dd-mut" style="color:var(--mut)">m</p><a id="dd-link" href="#">l</a>' +
    '<button id="dd-sec" class="b" type="button">s</button><button id="dd-main" class="b main" type="button">m</button>' +
    '<button id="dd-dsec" class="b" type="button" disabled>d</button><button id="dd-dmain" class="b main" type="button" disabled>d</button>' +
    '<span id="dd-call" class="badge call">c</span><span id="dd-rec" class="badge rec">r</span><span id="dd-you" class="tag t-you">y</span><span id="dd-ok" class="badge open">o</span></div>';
  document.body.appendChild(d);
  const g = (id) => getComputedStyle(document.getElementById(id));
  const pick = (id, ...p) => { const s = g(id); return p.map(k => s[k]); };
  return {html: pick('dd-card', 'backgroundColor').concat(getComputedStyle(document.documentElement).backgroundColor), body: getComputedStyle(document.body).color, card: pick('dd-card', 'backgroundColor', 'borderTopColor'),
    mut: pick('dd-mut', 'color'), link: pick('dd-link', 'color'), sec: pick('dd-sec', 'borderTopColor', 'color', 'backgroundColor', 'opacity'), main: pick('dd-main', 'backgroundColor', 'color', 'borderTopColor', 'opacity'),
    dsec: pick('dd-dsec', 'backgroundColor', 'color', 'borderTopColor', 'opacity'), dmain: pick('dd-dmain', 'backgroundColor', 'color', 'borderTopColor', 'opacity'),
    call: pick('dd-call', 'backgroundColor', 'color', 'borderTopColor'), rec: pick('dd-rec', 'backgroundColor', 'color', 'borderTopColor'), you: pick('dd-you', 'backgroundColor', 'color', 'boxShadow'),
    ok: pick('dd-ok', 'backgroundColor', 'color'), inline: document.documentElement.getAttribute('style') || '', cls: document.documentElement.className};
}"""
def want_dark():
    o = {k: rgb(v) for k, v in OLD.items() if v.startswith("#")}
    return {"card": [o["card"], o["line"]], "mut": [o["mut"]], "link": [o["link"]], "sec": [o["ibd"], o["fg"], "rgba(0, 0, 0, 0)", "1"], "main": [o["solid"], o["onsolid"], o["solid"], "1"],
            "dsec": [o["disbg"], o["disfg"], o["disbg"], "1"], "dmain": [o["disbg"], o["disfg"], o["disbg"], "1"],
            "call": [o["labbg"], o["labfg"], o["labbd"]], "rec": [o["labbg"], o["labfg"], o["labbd"]], "you": [o["labbg"], o["labfg"], f"{o['labbd']} 0px 0px 0px 1px inset"], "body": o["fg"]}
def TOOL_PROPS(d): return [x for x in re.findall(r"(--[\w-]+)\s*:", d["inline"]) if x != "--hdr"]      # the page sets --hdr itself (the header height); the tool sets the others
def cmp(got, want): return {k: (got[k], w) for k, w in want.items() if got[k] != w}

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try: br = p.chromium.launch()
    except Exception as e:
        print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
    try:
        ctx = br.new_context(viewport={"width": 1000, "height": 900}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(PAGE.as_uri()); pg.wait_for_timeout(200)
        d0 = pg.evaluate(PROBE)
        check("dark, nothing stored: the page background is the shipped one, and so are the body text, a card and its line, muted text and a link", pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") and d0["html"][1] == rgb(OLD["bg"])
              and not cmp(d0, {k: v for k, v in want_dark().items() if k in ("body", "card", "mut", "link")}), (d0["html"], cmp(d0, want_dark())))
        check("dark, nothing stored: a secondary button's outline and text, the main button's fill and label, the disabled buttons' flat fill and text at full opacity, the orange badges and the Your move tag are the shipped ones", not cmp(d0, {k: v for k, v in want_dark().items() if k in ("sec", "main", "dsec", "dmain", "call", "rec", "you")}), cmp(d0, want_dark()))
        check("dark, nothing stored: nothing is set inline on the page and no tool class is on it (the look is the stylesheet's)", TOOL_PROPS(d0) == [] and "ct-" not in d0["cls"], (d0["inline"], d0["cls"]))
        check("dark, nothing stored: a status badge (open) keeps its own tint, not the label look", d0["ok"][0] != rgb(OLD["labbg"]) and d0["ok"][1] != rgb(OLD["labfg"]), d0["ok"])
        # the Colors panel: a colored preset changes the look; a changed look is undone by Reset
        pg.evaluate("document.getElementById('ct-btn').click()"); pg.wait_for_timeout(100)
        pg.evaluate("document.querySelector('.ct-preset[data-p=sky]').click()"); pg.wait_for_timeout(80)
        d2 = pg.evaluate(PROBE)
        check("a colored preset (Sky) does change the look: a different main fill, label fill and link, and the page background stays", d2["main"][0] != d0["main"][0] and d2["call"][0] != d0["call"][0] and d2["link"] != d0["link"] and d2["html"] == d0["html"] and d2["link"] == [rgb("#7cb7ff")], (d2["main"], d2["call"], d2["link"]))
        pg.evaluate("document.getElementById('ct-reset').click()"); pg.wait_for_timeout(80)
        d3 = pg.evaluate(PROBE)
        check("Reset returns the look to the shipped one: the same computed styles as the default, nothing stored, nothing set inline, no class", d3 == d0 and pg.evaluate("localStorage.getItem('stackshot-color-trial')") is None and TOOL_PROPS(d3) == [] and "ct-" not in d3["cls"], {k: (d3[k], d0[k]) for k in d3 if d3[k] != d0[k]})
        pg.evaluate("document.querySelector('.ct-preset[data-p=live]').click()"); pg.wait_for_timeout(80)
        check("the Original orange theme button is the same shipped look", pg.evaluate(PROBE) == d0)
        pg.evaluate("document.getElementById('ct-fold').click()"); pg.wait_for_timeout(60)
        pg.fill("#ct-h-link", "#ffa057"); pg.press("#ct-h-link", "Tab"); pg.wait_for_timeout(80)
        d4 = pg.evaluate(PROBE)
        check("a text-and-links change alone moves the link and, because the small label follows it, the label fill (a tint of the new orange) and its text; Reset undoes all of it", d4["link"] == [rgb("#ffa057")] and d4["call"][0] != d0["call"][0] and d4["call"][1] == rgb("#ffa057"), (d4["link"], d4["call"]))
        pg.evaluate("document.getElementById('ct-reset').click()"); pg.wait_for_timeout(80)
        check("Reset after a text-and-links change returns to the shipped look", pg.evaluate(PROBE) == d0)
        ctx.close()
        # a stored look, then a reload: the tool applies it before the first paint, and Reset on the reloaded page still returns to the shipped look
        ctx = br.new_context(viewport={"width": 1000, "height": 900}, color_scheme="dark")
        ctx.add_init_script("try{localStorage.setItem('stackshot-color-trial', JSON.stringify({link:'#ffa057', solid:'#bd561d'}))}catch(e){}")
        pg = ctx.new_page(); pg.goto(PAGE.as_uri()); pg.wait_for_timeout(200)
        s = pg.evaluate(PROBE)
        check("a stored look is applied on load (the link and the solid fill differ from the shipped ones)", s["link"] == [rgb("#ffa057")] and s["main"][0] == rgb("#bd561d"), (s["link"], s["main"]))
        pg.evaluate("document.getElementById('ct-btn').click()"); pg.evaluate("document.getElementById('ct-reset').click()"); pg.wait_for_timeout(80)
        check("Reset on a page loaded with a stored look returns it to the shipped one", pg.evaluate(PROBE) == d0)
        ctx.close()
        # the light theme: as it was (the main button the light orange with a white label, a disabled button faded by opacity, the badges tinted)
        ctx = br.new_context(viewport={"width": 1000, "height": 900}, color_scheme="light"); pg = ctx.new_page(); pg.goto(PAGE.as_uri()); pg.wait_for_timeout(200)
        lt = pg.evaluate(PROBE)
        check("light: the main button is #ad4608 with a white label, a link is #ad4608, a secondary button's outline is #85847f and its text #1a1918", lt["main"][:2] == [rgb("#ad4608"), rgb("#ffffff")] and lt["link"] == [rgb("#ad4608")] and lt["sec"][:2] == [rgb("#85847f"), rgb("#1a1918")], (lt["main"], lt["link"], lt["sec"]))
        check("light: a disabled secondary button is faded by opacity (0.45) with no flat fill, the idle main button at 0.5 on its orange fill", lt["dsec"][3] == "0.45" and lt["dsec"][0] == "rgba(0, 0, 0, 0)" and lt["dmain"][3] == "0.5" and lt["dmain"][0] == rgb("#ad4608"), (lt["dsec"], lt["dmain"]))
        check("light: the orange badge and the Your move tag keep their tints (no solid orange fill, text not the near-black label)", lt["call"][0] != rgb("#ad4608") and lt["call"][1] != rgb("#1f1f21") and lt["you"][0] != rgb("#ad4608") and lt["you"][1] != rgb("#1f1f21"), (lt["call"], lt["you"]))
        check("light: the Colors button is not drawn (the tool is dark only)", pg.evaluate("(() => { const b = document.getElementById('ct-btn'); return !b || b.closest('.ct').hidden; })()"))
        ctx.close()
    finally:
        br.close()

print(f"{'ok' if not fails else 'FAILED'}: dark default check, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
