"""Scenario test for the shipped dark look: the dark theme every page starts from is the original orange look (stackshot's shipped values for the color tool, ui/colortool.py SHIPPED: orange text and fills, orange text on a dark brown fill for the small labels), and the light theme is as it was.

No server, no network, no browser: the pages are rendered straight from the Board and the stylesheet is read from them as the cascade resolves it (tests/_colors.py). The shipped look is checked against its own 14 fields, written out
below (no preset stands in for it). tests/dark_default_check.py is the same proof in a real browser (computed styles on the rendered page, the Colors panel's Reset and the Original orange theme button); it is run by hand like the other
checks. Covers:
  * the shipped look: the 14 fields of ui/colortool.py SHIPPED are exactly the ones written here (SHIPPED_FIELDS), the three small-label fields are the dark brown fill #3a2619 with the orange text #f0a06a (and the same brown outline),
    the neutrals are the ones the shared file gives every preset (its NEUTRAL map), the first preset of shared/colortool.js, the original orange theme, is the empty map (nothing set, so Reset and it return to the shipped look),
    and every page carries the shipped values for the tool;
  * the stylesheet of every page, in the dark theme, resolves the fields to the shipped look: the page, cards, lines, text, muted text, outlines, the one orange (links, the main button's fill), the label on it,
    the small labels' fill, text and outline, the disabled fill and text, in both dark forms (the chosen theme and the system scheme), and the dark rules that draw the labels and the disabled buttons from them;
  * the tool applies nothing of its own when nothing is set (every set and class in its onApply is behind a field being set), so Reset, which removes what it set, leaves the shipped look;
  * the light theme is unchanged: the light token block of the home page and of an item page (page, text, lines, cards, the orange and the label on it, the input tokens) has the values it had before the dark default moved (LIGHT_TOKENS), and carries no label or disabled token. The whole light stylesheet is not hashed: that would fail on every unrelated change to a light rule.

    tests/run-suite dark_default        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import _scratch, _instance, _colors as C

tmp = _scratch.mkdtemp(prefix="darkdefault-"); T = pathlib.Path(tmp)
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
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
PAGES = {"home": Bd().html(), "item": Bd().item_html("a1", answer=BOX), "project": Bd().routing_html("projects/alpha"), "Projects": Bd().projects_html(), "Closed": Bd().landed_html()}

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

LIB = pathlib.Path(STACK, "shared", "colortool.js").read_text(encoding="utf-8")
KEYS = ["bg", "card", "line", "fg", "mut", "link", "ibd", "solid", "onsolid", "labbg", "labfg", "labbd", "disbg", "disfg"]

# ---- 1. the shipped look, checked against its own 14 fields
SHIPPED_FIELDS = {"bg": "#161617", "card": "#1f1f21", "line": "#2c2c2e", "fg": "#ececea", "mut": "#a3a29d", "link": "#f0a06a", "ibd": "#929190", "solid": "#f0a06a", "onsolid": "#1f1f21",
                  "labbg": "#3a2619", "labfg": "#f0a06a", "labbd": "#3a2619", "disbg": "#2a2a2c", "disfg": "#a3a29d"}
NEW = SHIPPED_FIELDS
check("stackshot's shipped values for the tool (what Reset and the original orange theme return to) are exactly these 14 fields, each #rrggbb", sorted(SHIPPED_FIELDS) == sorted(KEYS) and all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in SHIPPED_FIELDS.values())
      and {k: ct.SHIPPED.get(k) for k in KEYS} == SHIPPED_FIELDS, {k: (ct.SHIPPED.get(k), SHIPPED_FIELDS.get(k)) for k in KEYS if ct.SHIPPED.get(k) != SHIPPED_FIELDS.get(k)})
check("the three small-label fields are orange text (the one orange, #f0a06a) on a dark brown fill with the same brown outline, and the text on the solid orange is the near-black #1f1f21",
      (ct.SHIPPED["labbg"], ct.SHIPPED["labbd"]) == ("#3a2619",) * 2 and ct.SHIPPED["labfg"] == ct.SHIPPED["link"] == ct.SHIPPED["solid"] == "#f0a06a" and ct.SHIPPED["onsolid"] == "#1f1f21")
neutral = re.search(r"var NEUTRAL = \{(.*?)\};", LIB, re.S)
NEUTRAL = dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", neutral.group(1))) if neutral else {}
check("the neutrals the shared file gives every preset are the shipped look's own (page, cards, lines, text, muted text, outlines and the disabled pair)", bool(NEUTRAL) and {k: ct.SHIPPED[k] for k in NEUTRAL} == NEUTRAL and sorted(NEUTRAL) == sorted(("bg", "card", "line", "fg", "mut", "ibd", "disbg", "disfg")), NEUTRAL)
check("the first preset of the shared file, the original orange theme, is the empty map: it sets nothing, so applying it is the shipped look", "['live', 'Original orange theme', {}]" in LIB)
check("the shipped input fill stays the stylesheet's own (it is not a field)", ct.SHIPPED.get("ifill") == "#2b2b2f")
for nm, pg in PAGES.items():
    m = re.search(r"window\.stackshotColors=\{storageKey:\"[^\"]*\",shipped:(\{[^}]*\}),", pg)
    check(f"{nm}: the page hands the tool the same shipped values", bool(m) and json.loads(m.group(1)) == ct.SHIPPED, m and m.group(1)[:200])

# ---- 3. the stylesheet of every page, in the dark theme
def page_css(pg): return "\n".join(re.findall(r"<style>(.*?)</style>", pg, re.S))
FIELD_TOKEN = {"bg": "--bg", "card": "--card", "line": "--line", "fg": "--fg", "mut": "--mut", "link": "--acc", "ibd": "--ibd", "solid": "--acc", "onsolid": "--on-acc",
               "labbg": "--lab-bg", "labfg": "--lab-fg", "labbd": "--lab-bd", "disbg": "--dis-bg", "disfg": "--dis-fg"}
for nm, pg in PAGES.items():
    css = page_css(pg); tk = C.resolved(css)["dark"]
    got = {k: tk.get(t) for k, t in FIELD_TOKEN.items()}
    check(f"{nm}: in the dark theme the stylesheet resolves all 14 fields to the shipped look (the text and links and the main button's fill read --acc, the one orange)", got == NEW, {k: (got[k], NEW[k]) for k in KEYS if got[k] != NEW[k]})
    check(f"{nm}: the one orange is --orange, and --acc, --call, --t-you and the small label text are it; the label on the solid fill is --on-acc; the small label fill and outline are the dark brown #3a2619", all(tk.get(t) == NEW["link"] for t in ("--orange", "--acc", "--call", "--t-you", "--lab-fg")) and tk.get("--on-acc") == NEW["onsolid"] and tk.get("--lab-bg") == tk.get("--lab-bd") == "#3a2619", None)
    mq = re.search(r"@media\(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{([^}]*)\}\}", css)
    check(f"{nm}: the system-dark form of the stylesheet carries the same orange, label on it and outlines as the chosen dark theme", bool(mq) and all(C.declarations(mq.group(1)).get(t) == C.declarations(re.search(r":root\[data-theme=dark\]\{([^}]*)\}", css).group(1)).get(t) for t in ("--orange", "--on-acc", "--ibd")), None)
    sysd = [re.search(r"@media\(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{([^}]*lab-bg[^}]*)\}\}", css), re.search(r":root\[data-theme=dark\]\{([^}]*lab-bg[^}]*)\}", css)]
    check(f"{nm}: both dark forms carry the five label and disabled tokens, equal", all(sysd) and C.declarations(sysd[0].group(1)) == C.declarations(sysd[1].group(1)) and all(k in C.declarations(sysd[1].group(1)) for k in ("--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg")), None)
home = page_css(PAGES["home"])
DK = ":root[data-theme=dark]"; MQ = ":root:not([data-theme=light])"
check("the dark rules draw the orange labels (the badges call and rec, the Your move tag) from the label tokens and every disabled button (but a busy, pressed or busy-form one) flat from the disabled tokens, in both dark forms",
      all(f"{r} .badge.call,{r} .badge.rec{{background:var(--lab-bg);color:var(--lab-fg);border-color:var(--lab-bd)}}" in home and f"{r} .tag.t-you{{background:var(--lab-bg);color:var(--lab-fg);box-shadow:inset 0 0 0 1px var(--lab-bd)}}" in home
          and f"{r} .b:disabled:not(.busy,.on,[aria-busy=true],form[aria-busy] .b){{opacity:1;background:var(--dis-bg);border-color:var(--dis-bg);color:var(--dis-fg)}}" in home for r in (DK, MQ)), None)
tk = C.resolved(home)["dark"]
check("the flat disabled pair reads at 3:1 or more (the tool's limit for it) and the small label text on its fill (the orange on the dark brown) and the label on the solid orange at 4.5:1 or more", C.ratio(tk.get("--dis-fg", "#000000"), tk.get("--dis-bg", "#000000")) >= 3 and C.ratio(tk.get("--lab-fg", "#000000"), tk.get("--lab-bg", "#000000")) >= 4.5 and C.ratio(tk["--on-acc"], tk["--acc"]) >= 4.5, (C.ratio(tk.get("--lab-fg", "#000000"), tk.get("--lab-bg", "#000000")), C.ratio(tk["--on-acc"], tk["--acc"])))

# ---- 4. the tool applies nothing by itself, so Reset leaves the shipped look; the preset is the shipped look
body = ct.ON_APPLY.split("{", 1)[1].rsplit("}", 1)[0]
stmts = [x.strip() for x in body.strip().split("\n") if x.strip()]
check("every statement of the tool's onApply is behind a field being set (if(s.…)), so with nothing set it sets no property and no class", stmts and all(re.match(r"if\(s\.\w+", x) for x in stmts), stmts)
check("no field is set by default: the tool's cfg has no stored look of its own and the key it keeps one under is the browser's", "stored" not in ct.CFG_JS and ct.KEY == "stackshot-color-trial")
vars_set = {p for v in ct.CFG_VARS.values() for p in v}
check("the properties the tool sets by field are the page's own tokens, none of the five label and disabled tokens (those are set together in onApply)", not vars_set & {"--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg"}, vars_set)
check("the tool's own style has no rule for the labels or the disabled buttons (the stylesheet draws them) and none of its classes is on the page by default", "ct-lab" not in ct.CSS and "ct-dis" not in ct.CSS and not re.search(r'class="[^"]*\bct-', "".join(PAGES.values())))

# ---- 5. the light theme is as it was
def strip_dark(css):
    """The stylesheet with every dark rule cut out: comments, @media(prefers-color-scheme:dark){…} blocks and rules whose selector names [data-theme=dark]."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, depth, start = [], 0, 0
    for i, ch in enumerate(css):
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = css[start:i + 1]; start = i + 1
                head = chunk.split("{", 1)[0]
                if "prefers-color-scheme:dark" in head.replace(" ", "") or "data-theme=dark" in head: continue
                out.append(chunk)
    out.append(css[start:])
    return "".join(out)
lt = C.resolved(home)["light"]
check("the light theme's tokens are what they were: the orange #ad4608, the label on it #ffffff, the outline #85847f, the page #fafaf8, and no label or disabled token", (lt.get("--orange"), lt.get("--on-acc"), lt.get("--ibd"), lt.get("--bg")) == ("#ad4608", "#ffffff", "#85847f", "#fafaf8")
      and not [k for k in lt if k in ("--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg")], lt.get("--orange"))
# The light theme is pinned on its token block (the tokens the dark default could have touched), not on a hash of the whole stylesheet: a hash fails on every unrelated change to a light rule.
LIGHT_TOKENS = {"--bg": "#fafaf8", "--fg": "#1a1918", "--mut": "#6b6a66", "--line": "#e4e2dc", "--card": "#ffffff", "--orange": "#ad4608", "--acc": "#ad4608", "--on-acc": "#ffffff",
                "--ibd": "#85847f", "--ifill": "#ffffff", "--iph": "#68675f"}
for nm in ("home", "item"):
    ltk = C.resolved(page_css(PAGES[nm]))["light"]
    check(f"{nm}: the light token block is what it was before the dark default moved (page, text, lines, cards, the orange and the label on it, the input tokens)", all(ltk.get(k) == v for k, v in LIGHT_TOKENS.items()) and not [k for k in ltk if k in ("--lab-bg", "--lab-fg", "--lab-bd", "--dis-bg", "--dis-fg")], {k: ltk.get(k) for k in LIGHT_TOKENS if ltk.get(k) != LIGHT_TOKENS[k]})
check("strip_dark does cut the dark rules (the planted stylesheet loses its dark orange and keeps its light one)", strip_dark(":root{--orange:#ad4608}@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--orange:#f0a06a}}:root[data-theme=dark]{--orange:#f0a06a}:root[data-theme=dark] .b{color:red}.b{color:blue}")
      == ":root{--orange:#ad4608}.b{color:blue}", None)

print(f"{'ok' if not fails else 'FAILED'}: dark default scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
