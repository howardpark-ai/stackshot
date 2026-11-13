"""Scenario test for the board's one orange (ui/render.py's --orange token and what reads it; ui/kit.py's --t-you) — the source scanned, the pages rendered straight from render.Board, no server, no network.

The board has ONE orange: #ad4608 on the light theme, #f0a06a on the dark one. --acc (links, focus rings, the picked card, the main button), --call (the "Your move" card's border, the "your call" markers) and
--t-you (the "Your move" chip) are that token; --t-you-bg and --selbg are tints of it (a color-mix over the card), never hex of their own. This suite fails on any other orange.

Covers:
  * the scan: every colour literal (#rgb, #rrggbb, rgb(), rgba(), hsl(), hsla(), a CSS named colour of the orange family as a value; a data: SVG is decoded first) in the SOURCE of the repo (every .py, .css, .svg, .html, .js,
    .sh, .toml, .md outside tests/, so ui/*.py, render.py, home.py, itempage.py, runners.py, search.py, publish.py, server.py and the docs pages alike) and in the RENDERED stylesheet and pages (home, Closed, For you, the item pages,
    the search box), and every token of the stylesheet as it resolves in each theme (a var() or color-mix() included), is put to the ORANGE BAND below. A colour in the band that is not on the allowlist fails with
    its file and literal. A form this scan cannot compute (oklch(), lab(), hwb(), color(), percent rgb) fails too, so a colour cannot hide in one;
  * the values: --orange, --acc, --call and --t-you are exactly #ad4608 (light) and #f0a06a (dark) in the stylesheet as the cascade gives it (--acc, --call and --t-you reference --orange and repeat no hex), the OS-dark block
    carries the same dark value as the data-theme block, the two tints are the stated blends, and what stays stays: the status blue (--run, --t-agent), the amber (--warn, --amber, --yellow) and the icon orange #f0a06a
    (the favicon, in server.py);
  * the contrast, recomputed (WCAG 2.x) from the stylesheet's own tokens in both themes: a link (the accent) on the page, the card and the picked card at 4.5:1 or more; the main Send label on its fill at rest, hover and
    pressed at 4.5:1 or more, the label being whichever of white and the near-black page colour reads better; the secondary button's outline 3:1 or more on the page and the card; the "Your move" chip text on its tint 4.5:1 or more.

  * the one exclusion: the shared color tool (shared/colortool.js, and its script blocks inlined in the pages), which carries the presets to try, is left out of the source scan and cut out of the rendered pages before the scan (tests/_colors.py without_colortool); nothing else is.

    tests/run-suite orange        → exit 0 / 1       ORANGE_LIST=1 tests/run-suite orange  also prints every orange-band literal found and how it was handled"""
import base64, json, logging, os, pathlib, re, sys, time, urllib.parse
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch, _instance, _colors as C

# ---- the decision
ORANGE = {"light": "#ad4608", "dark": "#f0a06a"}         # the board's one orange
LABEL_FILL = "#3a2619"                                    # the dark brown fill and outline of the small labels in the dark theme (--lab-bg, --lab-bd; the label text on it is the orange): a colour of its own, not a tint of the orange, allowed as that one literal
ICON_ORANGE = "#f0a06a"                                 # the mark of the favicon and the app icons: allowed only inside an icon (a data: SVG, an .svg or a file under icons/)
TINT_PCT = {"--t-you-bg": 12, "--selbg": 8}               # the tints: this % of --orange over --card
STATUS_BLUE = {"light": {"--run": "#2f6fdd", "--t-agent": "#1f5bc4"}, "dark": {"--run": "#7fb0ff", "--t-agent": "#7fb0ff"}}
# The amber of the status colours (waiting and due warnings, the P2 yellow, the read-only page's banner). They stay as they are: they sit at hue 41 to 49, outside the band, which the checks
# below assert, so a drift of an amber toward the orange is caught as well. (readonly.py's #c98a00, #3a2d00 and #fff6df; ui/kit.py's --amber; ui/render.py's --warn and --yellow.)
AMBER_TOKENS = ("--warn", "--amber", "--yellow")
# THE ORANGE BAND, picked after listing what exists (run with ORANGE_LIST=1): the old oranges sat at hue 21.4 to 28.4 (#a34a14, #b3541e, #f0a06a and their tints #fbe9df #fbf0e8 #3a2619 #2b2118); the amber of the
# status colours at 41.2 to 49.2; the reds at 0; every gray of the page at saturation 0.18 or less. So the band is wider than "orange" on purpose, to catch a faint tint as well as a strong colour:
BAND = dict(hue=(8.0, 38.0), sat_min=0.20, light=(0.06, 0.98))
def in_band(hsl):
    h, s, l = hsl; return BAND["hue"][0] <= h <= BAND["hue"][1] and s >= BAND["sat_min"] and BAND["light"][0] <= l <= BAND["light"][1]

# ---- the page fixture (the same shape as button_set_scenario's)
tmp = _scratch.mkdtemp(prefix="orange-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
HERE = "00000000-0000-4000-8000-000000000001"
now = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def item(i, subject, status="open", su=None, **meta):
    su = now - 3 * H if su is None else su
    d = {"id": str(i), "subject": subject, "description": "A thing. It lives here.", "status": status, "updated": su, "state_updated": su, "confirmed": su,
         "metadata": {"owner": HERE, "project": "projects/alpha", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
item(1, "[home] ask with options", needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", then="home-other", next="Oliver: decide")
item(3, "[home] agent item", mover="home-other", next="home-other: x", needs=["home-other"])
item(4, "[home] your step", state="your-step", step="run the one line `sala op reauth box-a --from me --words \"go\"` and say done", mover="Oliver", then="home-other",
     needs=["home-other"], next="home-other: check it", draft="Hello,\nthe draft text.")
item(5, "[home] closed one", status="completed", su=now - 2 * H, outcome="done", reason="shipped", mover=None)
(T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web.ui import render, search
bd = render.Board(f"{tmp}/store")
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
css = bd._css()
PAGES = {"stylesheet": css, "home": bd.html(), "closed": bd.landed_html(), "for-you": bd.for_you_html(), "search box": search.box("x"),
         **{f"item {g}": bd.item_html(g, answer=BOX) for g in ("a1", "a3", "a4")}}
PAGES = {k: C.without_colortool(v) for k, v in PAGES.items()}      # the shared color tool's script blocks hold the presets and are not scanned

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

# ---- the allowlist
TK = C.resolved(css)                                         # {"light": {token: hex}, "dark": {…}}
def tints():
    """Every hex a tint of an allowed orange can be: the orange at 1 to 40% over a surface of the same theme (page, card, input fill, white)."""
    out = {}
    for th, o in ORANGE.items():
        for surf in {TK[th].get("--bg"), TK[th].get("--card"), TK[th].get("--ifill"), "#ffffff"} - {None}:
            for p in range(1, 41): out.setdefault(C.mix(o, surf, p), f"{p}% of {o} over {surf}")
    return out
TINTS = tints()
RGB = {tuple(int(o[i:i + 2], 16) for i in (1, 3, 5)): o for o in ORANGE.values()}
def allowed(lit, kind, icon):
    """Why this orange-band literal is allowed, or None."""
    if kind == "hex":
        lit = lit.replace("%23", "#"); hx = C.full(lit)
        if hx in ORANGE.values(): return "the board's orange"
        if hx == LABEL_FILL: return "the dark brown small-label fill"
        if hx == ICON_ORANGE and icon: return "the icon orange, inside an icon"
        if len(lit) in (7, 4) and hx in TINTS: return "a tint: " + TINTS[hx]
    if kind == "rgb":
        ch = tuple(int(float(x)) for x in re.split(r"[,\s/]+", re.search(r"\(([^)]*)\)", lit).group(1).strip())[:3])
        if ch in RGB: return "a translucent " + RGB[ch]
    return None

# ---- 1. the scan
SKIP_DIRS = {".git", ".claude", "tests", "__pycache__", "node_modules", ".venv", "screenshots"}
SKIP_EXT = {".png", ".ico", ".woff", ".woff2", ".ttf", ".jpg", ".jpeg", ".gif", ".webp", ".lock", ".pyc"}
def sources():
    for root, dirs, files in os.walk(STACK):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p = pathlib.Path(root, f)
            if p.suffix in SKIP_EXT or p.stat().st_size > 3_000_000 or p.relative_to(STACK).as_posix() == "shared/colortool.js": continue      # the shared color tool holds the presets to try: not scanned
            try: yield str(p.relative_to(STACK)), p.read_text(encoding="utf-8")
            except UnicodeDecodeError: continue
DATA_URI = re.compile(r"data:image/svg\+xml(;base64)?,([A-Za-z0-9+/=%._~\-]+)")
def decoded_icons(text):
    out = []
    for m in DATA_URI.finditer(text):
        try: out.append(base64.b64decode(m.group(2)).decode("utf-8") if m.group(1) else urllib.parse.unquote(m.group(2)))
        except Exception: pass
    return out
unreadable = []
def scan(where, text, icon=False, into=None, bad=None):
    """Put every colour literal of `text` to the band; the in-band ones are appended to `into` (default: the repo's `found`), the unreadable forms to `bad` (default: `unreadable`)."""
    into = found if into is None else into; bad = unreadable if bad is None else bad
    for lit, hsl, kind in C.literals(text):
        if kind == "unreadable": bad.append((where, lit))
        elif kind == "named": into.append((where, lit, kind, None, None))      # a named orange-family colour: never allowed
        elif in_band(hsl): into.append((where, lit, kind, hsl, allowed(lit, kind, icon)))
found = []        # (where, literal, kind, hsl, why it is allowed or None)
nfiles = 0
for rel, text in sources():
    nfiles += 1
    icon_file = rel.endswith(".svg") or rel.startswith("icons/")
    for svg in decoded_icons(text): scan(f"{rel} (data: SVG)", svg, icon=True)
    scan(rel, DATA_URI.sub("data:", text), icon=icon_file)
for name, text in PAGES.items():
    for svg in decoded_icons(text): scan(f"rendered {name} (data: SVG)", svg, icon=True)
    scan(f"rendered {name}", DATA_URI.sub("data:", text))
check("the scan read the repo's source (more than 40 files) and the rendered stylesheet and pages", nfiles > 40 and len(css) > 20000 and len(PAGES) >= 7, nfiles)
check("no colour literal is in a form the scan cannot compute (oklch, lab, hwb, color(), percent rgb)", not unreadable, unreadable[:6])
rogue = [(w, l, None if h is None else tuple(round(x, 2) for x in h)) for w, l, k, h, why in found if why is None]
check("every colour literal in the orange band (hue %g to %g, saturation %g or more, lightness %g to %g) is the board's orange, a tint of it, the icon orange inside an icon, or a translucent form of the orange; any other fails with its file and literal"
      % (*BAND["hue"], BAND["sat_min"], *BAND["light"]), not rogue, rogue[:10])
if os.environ.get("ORANGE_LIST"):
    seen = {}
    for w, l, k, h, why in found: seen.setdefault((w if not w.startswith("rendered") else "rendered pages", l), why)
    for (w, l), why in sorted(seen.items()): print(f"  band: {w:34} {l:44} {why or 'NOT ALLOWED'}")
check("the old oranges are gone from the source: #a34a14, #b3541e, and the old tints #fbe9df, #fbf0e8, #2b2118 appear in no file outside tests/",
      not [(rel, o) for rel, text in sources() for o in ("#a34a14", "#b3541e", "#fbe9df", "#fbf0e8", "#2b2118") if o in text.lower()], None)
# #3a2619 was one of the old tints and is now the small labels' fill (the shipped dark look): it stays out of everything but the places that name that fill
check("the small-label fill #3a2619 appears only in the stylesheet's dark label tokens (stackshot/web/ui/render.py), the color tool's shipped values (stackshot/web/ui/colortool.py) and docs/color-tool.md, nowhere else outside tests/",
      sorted({rel for rel, text in sources() if LABEL_FILL in text.lower()}) == ["docs/color-tool.md", "stackshot/web/ui/colortool.py", "stackshot/web/ui/render.py"], sorted({rel for rel, text in sources() if LABEL_FILL in text.lower()}))

# the scan itself, on planted text: each way a rogue orange could hide is caught, and what is not a colour is left alone (the text is in memory; no file is written)
def rogues(text, icon=False):
    got, bad = [], []; scan("planted", text, icon=icon, into=got, bad=bad)
    return [lit for _, lit, _, _, why in got if why is None] + [lit for _, lit in bad]
PLANTED = {
    "a short hex after a space in a declaration (border:1px solid #d62)": ".x{border:1px solid #d62}",
    "a short hex deeper in a shorthand (box-shadow:0 0 0 1px #d62)": ".x{box-shadow:0 0 0 1px #d62}",
    "a hex glued to a word (1px solid#c2601a)": ".x{border:1px solid#c2601a}",
    "a URL-encoded hex outside a data: SVG (%23c2601a)": ".x{background:url(\"x.svg?c=%23c2601a\")}",
    "a named orange after a space (border:1px solid orange)": ".x{border:1px solid orange}",
    "a named orange in a shadow (box-shadow:0 0 2px orangered)": ".x{box-shadow:0 0 2px orangered}",
    "a named orange in a gradient (linear-gradient(orange,#fff))": ".x{background:linear-gradient(orange,#fff)}",
    "a named orange as a bare value (color:coral)": ".x{color:coral}",
    "a named orange in an SVG attribute": '<path fill="tomato"/>',
    "a custom property holding a named orange": ":root{--rogue:darkorange}",
    "an rgba of another orange": ".x{color:rgba(200,100,30,.4)}",
    "an hsl orange": ".x{color:hsl(24,70%,50%)}",
    "a modern colour form": ".x{color:oklch(70% .15 50)}",
}
for what, text in PLANTED.items(): check(f"planted: {what} fails the scan", rogues(text), text)
check("planted: the board's own oranges, a tint of one, and the icon orange inside an icon pass", not rogues(".x{border:1px solid #ad4608;box-shadow:0 0 0 1px rgba(240,160,106,.3);color:%23f0a06a}") and not rogues("<path stroke='%23f0a06a'/>", icon=True), None)
check("planted: the retired dark orange #ec8a47 fails", rogues(".x{color:#ec8a47}") == ["#ec8a47"], rogues(".x{color:#ec8a47}"))
NOT_COLOURS = ["a#d62{color:#fff}", '<a href="#d62">x</a>', '<a href="page.html#fab">x</a>', "url(#d62)", "&#d62; &#123;", "(PRs #11 and #13)", "see https://x.example/y#d62",
               "# --acc is the one accent of the board: orange (the update orange, on the row's own line)", "the update orange, on the row's own line", ".orange{color:var(--orange)}", "--acc:var(--orange);--orange:#ad4608",
               "id=\"#d62\"", "section.tan{margin:0}", "label: coral reef", "color-mix(in srgb,var(--orange) 12%,var(--card))"]
for text in NOT_COLOURS: check(f"planted: not a colour, not flagged: {text[:60]}", not rogues(text), rogues(text))

# every token of the stylesheet, as it resolves in each theme (catches an orange that is a var() or a color-mix(), not a literal)
ORANGE_TOKENS = {"--orange", "--acc", "--call", "--t-you", "--t-you-bg", "--selbg", "--lab-bg", "--lab-fg", "--lab-bd"}
stray = [(th, k, v) for th, toks in TK.items() for k, v in toks.items() if in_band(C.hsl(v)) and k not in ORANGE_TOKENS]
check("no token of the stylesheet resolves into the orange band in either theme but --orange, --acc, --call, --t-you, the tints --t-you-bg and --selbg, and the small labels' dark fill, text and outline --lab-bg, --lab-fg and --lab-bd (the text references --orange, the fill and outline are #3a2619)", not stray, stray[:8])
check("the amber of the status colours stays amber (hue 40 to 52) and outside the orange band in both themes: --warn, --amber, --yellow",
      all(40 <= C.hsl(TK[th][t])[0] <= 52 and not in_band(C.hsl(TK[th][t])) for th in TK for t in AMBER_TOKENS), {th: {t: TK[th].get(t) for t in AMBER_TOKENS} for th in TK})
ro = pathlib.Path(STACK, "stackshot/core/readonly.py").read_text(encoding="utf-8")
check("the read-only page's amber (#c98a00, #3a2d00, #fff6df) is amber, outside the band", all(o in ro and not in_band(C.hsl(o)) and C.hsl(o)[0] >= 40 for o in ("#c98a00", "#3a2d00", "#fff6df")))

# ---- the favicon: the icon orange stays
srv = pathlib.Path(STACK, "stackshot/web/app.py").read_text(encoding="utf-8")
ico = re.search(r'^_ICON = "(data:image/svg\+xml;base64,[A-Za-z0-9+/=]+)"', srv, re.M)
svg = decoded_icons(ico.group(1))[0] if ico else ""
check("the favicon (web/app.py _ICON) draws its mark in the icon orange #f0a06a, which is also the board's dark orange", ICON_ORANGE in svg and ICON_ORANGE == ORANGE["dark"], svg[:200])

# ---- 2. the values
raw = C.themes(css)
for th in ("light", "dark"):
    t = TK[th]
    for tok in ("--orange", "--acc", "--call", "--t-you"):
        check(f"{th}: {tok} is {ORANGE[th]}", t.get(tok) == ORANGE[th], t.get(tok))
    for tok, pct in TINT_PCT.items():
        want = C.mix(ORANGE[th], t["--card"], pct)
        check(f"{th}: {tok} is {pct}% of the orange over the card ({want})", t.get(tok) == want, t.get(tok))
    for tok, want in STATUS_BLUE[th].items(): check(f"{th}: {tok} stays the status blue {want}", t.get(tok) == want, t.get(tok))
check("--acc, --call and --t-you reference --orange and repeat no hex; the tints are color-mix() over the card",
      raw["light"].get("--acc") == "var(--orange)" and raw["light"].get("--call") == "var(--orange)" and raw["light"].get("--t-you") == "var(--orange)"
      and raw["light"].get("--t-you-bg") == "color-mix(in srgb,var(--orange) 12%,var(--card))" and raw["light"].get("--selbg") == "color-mix(in srgb,var(--orange) 8%,var(--card))"
      and not any(k in raw["dark"] and raw["dark"][k] != raw["light"][k] for k in ("--acc", "--call", "--t-you", "--t-you-bg", "--selbg")), (raw["light"].get("--acc"), raw["light"].get("--call"), raw["light"].get("--t-you")))
check("the hex of each orange is written once per block that defines it: the light one once, the dark one in the OS-dark block and the data-theme block",
      css.lower().count(ORANGE["light"]) == 1 and css.lower().count(ORANGE["dark"]) == 2, (css.lower().count(ORANGE["light"]), css.lower().count(ORANGE["dark"])))
mq = re.search(r"@media\(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{([^}]*)\}\}", css)
check("the OS-dark block carries the same dark orange as the data-theme=dark block", mq and C.declarations(mq.group(1)).get("--orange") == ORANGE["dark"], mq and C.declarations(mq.group(1)).get("--orange"))
check("the rules read the tokens: the link, the Your move card's border, the update marker, the picked card, the chip",
      re.search(r"(?:^|\})a\{color:var\(--acc\)", css, re.M) and "a.hcard.call{border-color:var(--call)}" in css and ".aflag{color:var(--call)" in css
      and "border:2px solid var(--acc);background:var(--selbg)" in css and ".t-you{background:var(--t-you-bg);color:var(--t-you)}" in css, None)

# ---- 3. the contrast, recomputed from the tokens
rule = lambda sel: (re.search(r"(?:^|\})" + re.escape(sel) + r"\{([^}]*)\}", css, re.M) or [0, None])[1]
hov = int((re.search(r"background:color-mix\(in srgb,var\(--fg\) (\d+)%,var\(--acc\)\)", css[css.find(".b.main:hover"):]) or [0, "0"])[1])
prs = int((re.search(r"background:color-mix\(in srgb,var\(--fg\) (\d+)%,var\(--acc\)\)", css[css.find(".b.main:active"):]) or [0, "0"])[1])
check("the main button's hover and pressed fills are blends of --fg over --acc (percentages read from the stylesheet)", hov > 0 and prs > hov, (hov, prs))
report = []
for th in ("light", "dark"):
    t = TK[th]; acc = t["--acc"]
    surfaces = {"page": t["--bg"], "card": t["--card"], "picked card": t["--selbg"]}
    for sname, sv in surfaces.items():
        r = C.ratio(acc, sv); report.append((th, f"link on {sname}", r)); check(f"{th}: a link (the accent) on the {sname} is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    r = C.ratio(t["--call"], t["--card"]); check(f"{th}: the 'your call' marker (--call) on the card is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    on = t["--on-acc"]; other = "#161617" if C.lum(on) > 0.5 else "#ffffff"
    check(f"{th}: the Send label ({on}) is the better of white and the near-black page colour on the fill", C.ratio(on, acc) >= C.ratio(other, acc), (on, other))
    for nm, fill in (("rest", acc), ("hover", C.mix(t["--fg"], acc, hov)), ("pressed", C.mix(t["--fg"], acc, prs))):
        r = C.ratio(on, fill); report.append((th, f"Send label at {nm}", r)); check(f"{th}: the Send label on its {nm} fill ({fill}) is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    for sname in ("page", "card"):
        r = C.ratio(t["--ibd"], surfaces[sname]); report.append((th, f"secondary outline on {sname}", r)); check(f"{th}: the secondary button's outline on the {sname} is {r:.2f}:1 (3 needed)", r >= 3, r)
    r = C.ratio(t["--t-you"], t["--t-you-bg"]); report.append((th, "Your move chip", r)); check(f"{th}: the 'Your move' chip text on its tint ({t['--t-you-bg']}) is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
if os.environ.get("ORANGE_LIST"):
    for th, what, r in report: print(f"  contrast {th:5} {what:34} {r:.2f}:1")

if fails: print(f"FAILED: orange scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: orange scenario, {len(ran)} checks")
