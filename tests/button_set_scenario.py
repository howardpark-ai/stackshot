"""Scenario test for the button set (ui/render.py's _BTN_CSS and the classes the pages draw, ui/search.py's submit button) — fixture data, the pages rendered straight from render.Board, no server, no network, no browser.

Covers:
  * every button of every page is a `.b` with no look or size class (the old Primary .pri, Standard .std, Quiet .qt, recommended .rec and the sizes .sm and .xs are gone), in two levels: the secondary
    (a plain `.b`) and the main (`.b.main`, the composer's Send, one per form and nothing else); the round reload button being the one exception; no old .abtn or .a-btn class is left;
  * the mapping: Send in a comment box, a decision's answer box and a step's box; the answer options are cards (a radio input each, no button), the recommended one carrying the "recommended" badge;
    Clear, Clear all and Undo; seen and mark all seen; Watch, Mute and Default with the pressed one .on and aria-pressed; Copy (a command block, the draft, the home row's draft) keeping its .copy hook;
    the panel button, the theme switch and the search submit as .ico buttons; the newer-board banner's Reload with the warn edge; Audit now as a text link (a button without the .b class);
  * the colours, computed (WCAG 2.x) from the real tokens of the stylesheet in both themes: the orange link and the main button's label on its fill at 4.5:1 or more (tests/orange_scenario.py holds the orange's own values and the scan for any other), the secondary's outline at 3:1 or more on the page
    and the card, its text at 4.5:1 or more and at full strength (--fg, not the muted --mut), the disabled main still visible, the status blue kept for running and live;
  * the stylesheet: the secondary look (outline, no fill, full-strength text, 13 px, 32 px tall, 8 px corners), the light hover and pressed fills, the .on, .warn and .ico modifiers, the focus-visible ring, the busy look,
    the coarse-pointer sizes, the round buttons' 1.5 px edge and hover fill, and no red;
  * the busy labels: the answer form's pressed Send reads "Sending…", Closed's Clear all reads "Clearing…" (a row's Clear keeps its label and shares a fixed width with Undo), all with aria-busy, and the script puts the label back;

    tests/run-suite button_set        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="buttonset-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1      # the Audit card (and its button) is drawn
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
item(2, "[home] ask with no options", needs=["decision"], ask=ASK, mover="Oliver", then="home-other", next="home-other: wait")           # Yes and No
item(3, "[home] agent item", mover="home-other", next="home-other: x", needs=["home-other"])                                                  # the comment box in the answer box's slot
item(4, "[home] your step", state="your-step", step="run the one line `sala op reauth box-a --from me --words \"go\"` and say done", mover="Oliver", then="home-other",
     needs=["home-other"], next="home-other: check it", draft="Hello,\nthe draft text.")
item(5, "[home] closed one", status="completed", su=now - 2 * H, outcome="done", reason="shipped", mover=None)
(T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web.ui import render, search
from stackshot.web import landed as ld; from stackshot.web import foryou as fy
bd = render.Board(f"{tmp}/store")
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
for k, (g, w) in enumerate((("a50", "older row"), ("a51", "newer row"))):
    fy.add(key=f"page:{k}", kind="closed", gid=g, item=g, project="projects/alpha", what=w, url=f"/items/{g[1:]}", ts=now - 60 * (k + 1))
item(6, "[home] another closed one", status="completed", su=now - H, outcome="done", reason="shipped too", mover=None)
for k, g in enumerate(("a5", "a6")): ld.record(g, now - 100 * (k + 1), "done", by="home-x", project="projects/alpha")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
BTN = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.S)
def buttons(h):
    """[(class tokens, name=value, label text)] for every <button> of the page."""
    out = []
    for m in BTN.finditer(h):
        a = m.group(1); c = re.search(r'class="([^"]*)"', a)
        out.append((set((c.group(1) if c else "").split()), (re.search(r'name="([^"]*)"', a) or [0, ""])[1] + "=" + (re.search(r'value="([^"]*)"', a) or [0, ""])[1], re.sub(r"<[^>]+>", "", m.group(2)).strip(), a))
    return out
def one(h, label, pred=lambda cl, nv, a: True):
    xs = [b for b in buttons(h) if b[2] == label and pred(b[0], b[1], b[3])]
    return xs[0][0] if len(xs) == 1 else (xs and xs[0][0] if xs else None)
# ---- 1. the pages
import _colors as _C
P = _C.without_colortool      # the shared color tool (shared/colortool.js) draws its own button and a preview strip with two inert Sends from script, which are not the board's buttons: the pages are read without its script blocks
home = P(bd.html()); landed = P(bd.landed_html()); foryou = P(bd.for_you_html())
WQ = {"action": "/items/a1/watch", "token": "W", "flag": "watch", "watched": True, "why": "you asked"}
pg = {g: P(bd.item_html(g, answer=BOX)) for g in ("a1", "a2", "a3", "a4")}
pw = P(bd.item_html("a1", answer=BOX, watch=WQ)); pw0 = P(bd.item_html("a1", answer=BOX, watch={**WQ, "flag": "", "watched": False}))
srch = search.box("x")
ALL = {"home": home, "landed": landed, "foryou": foryou, "a1": pg["a1"], "a2": pg["a2"], "a3": pg["a3"], "a4": pg["a4"], "a1+watch": pw}

# every button is the one look
bad = [(name, c, lab) for name, h in ALL.items() for c, nv, lab, a in buttons(h) if not (c & {"fab", "pgrip", "pmi"}) and "b" not in c and 'id="audit-now"' not in a]
check("every button of the board, the Closed page and the item pages is a .b; the round reload button, the summary panel's order controls (the grip and the move menu's items, styled in _PORDER_CSS) and the Audit card's Audit now text link (#audit-now, styled in _RUN_CSS) are the others", not bad, bad[:6])
old = [(name, sorted(c), lab) for name, h in ALL.items() for c, nv, lab, a in buttons(h) if c & {"pri", "std", "qt", "rec", "sm", "xs"}]
check("no button carries a look or size class (pri, std, qt, rec, sm, xs)", not old, old[:6])
check("no page draws the old .abtn or .a-btn class (the .abtns row of buttons is not a button)", all(not re.search(r'class="[^"]*\babtn\b', h) and "a-btn" not in h for h in ALL.values()))
def groups(h): return [m.group(1) for m in re.finditer(r'<div class="abtns[^"]*">(.*?)</div>', h, re.S)]
check("a form with options draws them as cards, not buttons, and holds one Send; so does the lone Send of a form with no options",
      all('<input type="radio" name="choice"' in pg[g] and not [b for b in buttons(pg[g]) if b[1].startswith("choice=")] and len(re.findall(r'<button type="submit" class="b main" name="act"', "".join(groups(pg[g])))) == 1 for g in ("a1", "a2"))
      and '<button type="submit" class="b main" name="act" value="comment"' in pg["a3"])
def forms(h): return re.findall(r"<form\b.*?</form>", h, re.S)
mains = [(name, b[1], b[2]) for name, h in ALL.items() for b in buttons(h) if "main" in b[0]]
check("the main button is the composer's Send and nothing else: every .main button on every page is a Send (act=answer, comment or send)", mains and all(nv in ("act=answer", "act=comment", "act=send") and lab == "Send" for _, nv, lab in mains), mains[:8])
check("one main button per form: no form on any page holds two, and every Send is a main",
      all(len([b for b in buttons(f) if "main" in b[0]]) <= 1 for h in ALL.values() for f in forms(h))
      and all("main" in b[0] for h in ALL.values() for b in buttons(h) if b[2] == "Send"), None)
check("every other button (Clear, Clear all, Undo, seen, Copy, Watch, Mute, Default, Reload, the icon buttons) is secondary: no .main", all("main" not in b[0] for h in ALL.values() for b in buttons(h) if b[2] != "Send"), None)

# ---- 2. the mapping
c = lambda h, nv: [b[0] for b in buttons(h) if b[1] == nv]
def cards(h):
    """{label: (radio value, whether the card carries the recommended badge)} for the option cards of a page."""
    return {re.search(r'class="alab">(?:<span class="akey">[A-Z]</span>)?([^<]*)<', m.group(2)).group(1): (m.group(1), 'class="badge rec"' in m.group(2))
            for m in re.finditer(r'<label class="acard"><input type="radio" name="choice" value="([^"]*)">(.*?)</label>', h, re.S)}
check("answer options: one card each, in the order drawn, the recommended one first with its badge and the others without (item page, stored options)",
      cards(pg["a1"]) == {"Ship": ("Ship", True), "Wait": ("Wait", False)} and list(cards(pg["a1"])) == ["Ship", "Wait"], cards(pg["a1"]))
check("answer options: Yes (recommended) and No cards when none are stored", cards(pg["a2"]) == {"Yes": ("Yes", True), "No": ("No", False)}, cards(pg["a2"]))
check("Send is the main .b in every answer box: beside the option cards (item page), the comment box, a step's Send",
      c(pg["a1"], "act=answer") == [{"b", "main"}] and c(pg["a2"], "act=answer") == [{"b", "main"}] and c(pg["a3"], "act=comment") == [{"b", "main"}] and c(pg["a4"], "act=send") == [{"b", "main"}],
      (c(pg["a1"], "act=answer"), c(pg["a3"], "act=comment"), c(pg["a4"], "act=send")))
comm = bd.answer_html(json.loads((T / "store/a/3.json").read_text()) | {"gid": "a3"}, BOX, comment_only=True)
check("the comment-only box's Send is the main .b", c(comm, "act=comment") == [{"b", "main"}], comm[-300:])
hc = cards(home)
check("the home row's ask form: the option cards with the recommended one badged, Send the main .b (drawn disabled until a token comes); a step's row Send the same",
      hc.get("Ship") == ("Ship", True) and hc.get("Wait") == ("Wait", False) and not [b for b in buttons(home) if b[1].startswith("choice=")]
      and c(home, "act=answer") and all(x == {"b", "main"} for x in c(home, "act=answer")) and c(home, "act=send") == [{"b", "main"}],
      (hc, c(home, "act=answer"), c(home, "act=send")))
check("Watch, Mute and Default are plain .b; the pressed one is .on with aria-pressed=true, the others aria-pressed=false",
      c(pw, "mode=watch") == [{"b", "on"}] and c(pw, "mode=mute") == [{"b"}] and c(pw, "mode=default") == [{"b"}]
      and 'class="b on" name="mode" value="watch" aria-pressed="true" disabled' in pw and 'class="b" name="mode" value="mute" aria-pressed="false"' in pw, [b[3] for b in buttons(pw) if b[1].startswith("mode=")])
check("…with no flag stored the Default button is the pressed one", c(pw0, "mode=default") == [{"b", "on"}] and c(pw0, "mode=watch") == [{"b"}])
check("Closed: Clear, Clear all and Undo (the script's, which draws it) are plain .b",
      c(landed, "=") and one(landed, "Clear all") == {"b"} and one(landed, "Clear") == {"b"}
      and "mk('lundo','b'," in render._LANDED_JS and "mk('lclear','b'," in render._LANDED_JS and "b.className=look" in render._LANDED_JS, (one(landed, "Clear all"), one(landed, "Clear")))
check("For you: seen and mark all seen are plain .b", one(foryou, "seen") == {"b"} and one(foryou, "mark all seen") == {"b"}, (one(foryou, "seen"), one(foryou, "mark all seen")))
copies = [b for b in buttons(home) + buttons(pg["a4"]) if b[2] == "Copy"]
check("Copy (a step's command block, the draft block, the home row's draft) is a plain .b, and keeps the .copy hook the page script finds it by",
      len(copies) >= 4 and all(b[0] == {"b", "copy"} for b in copies), [sorted(b[0]) for b in copies])
check("the summary panel button and its close button, the theme switch and the search submit are .ico buttons",
      all(c(home, nv) for nv in ("=",)) and all(x >= {"b", "ico"} for x in [b[0] for b in buttons(home) if 'id="panel-open"' in b[3] or 'id="panel-close"' in b[3] or 'id="theme"' in b[3]])
      and len([1 for b in buttons(home) if 'id="panel-open"' in b[3] or 'id="panel-close"' in b[3] or 'id="theme"' in b[3]]) == 3
      and 'class="b ico" aria-label="Search"' in srch and 'class="b ico" aria-label="Search"' in home, srch)
check("the newer-board banner's button reads Reload and has the warn edge; Audit now is a text link, a button with no .b class (a link look in _RUN_CSS, not a secondary button)",
      one(home, "Reload", lambda cl, nv, a: "conn-reload" in a) == {"b", "warn"} and one(home, "Audit now") == set(), (one(home, "Reload", lambda cl, nv, a: "conn-reload" in a), one(home, "Audit now")))
fab = re.search(r'<button[^>]*id="reload"[^>]*>', home)
check("the round reload button keeps its own .fab class (a fixed overlay beside Back to top)", fab and 'class="fab"' in fab.group(0), fab and fab.group(0))

# ---- 3. the stylesheet
css = bd._css()
rule = lambda sel: (re.search(r"(?:^|\})" + re.escape(sel) + r"\{([^}]*)\}", css, re.M) or [0, None])[1]  # the selector starts a rule: "li.lrow .b{" is not ".b{"
check("the secondary look: 13 px, a 32 px minimum height, 8 px corners, a 1 px --ibd outline, no fill, full-strength --fg text (not the muted --mut), weight 400, an inline flex row",
      all(x in (rule(".b") or "") for x in ("font-size:13px", "min-height:32px", "border-radius:8px", "border:1px solid var(--ibd,var(--mut))", "background:transparent", "color:var(--fg)", "font-weight:400", "display:inline-flex"))
      and "color:var(--mut)" not in (rule(".b") or "") and "var(--line)" not in (rule(".b") or ""), rule(".b"))
check("the icon button is 32 px square, and 44 px on a coarse pointer (which also lifts every button to 44 px)",
      all(x in (rule(".b.ico") or "") for x in ("width:32px", "height:32px")) and "@media(pointer:coarse){.b{min-height:44px}.b.ico{width:44px;height:44px;min-height:44px}}" in css, rule(".b.ico"))
check("hover (a pointer that can hover only): the outline firms up to --fg and a light fill appears, the warn edge kept; pressed: a 12% fill; disabled: 45% opacity",
      "@media(hover:hover){.b:hover:not(:disabled){color:var(--fg);border-color:var(--fg);background:color-mix(in srgb,var(--fg) 6%,transparent)}.b.warn:hover:not(:disabled){border-color:var(--warn)}}" in css
      and "color-mix(in srgb,var(--fg) 12%,transparent)" in (rule(".b:active:not(:disabled)") or "") and "opacity:.45" in (rule(".b:disabled") or ""))
check("the modifiers: .on a --acc outline and a 12% --acc tint, .warn a --warn edge",
      all(x in (rule(".b.on") or "") for x in ("border-color:var(--acc)", "color-mix(in srgb,var(--acc) 12%,transparent)")) and "border-color:var(--warn)" in (rule(".b.warn") or ""), (rule(".b.on"), rule(".b.warn")))
check("no rule for the old looks or sizes: no .b.pri, .b.std, .b.qt, .b.rec, .b.sm or .b.xs", not re.search(r"\.b\.(?:pri|std|qt|rec|sm|xs)\b", css))
check("a focus-visible ring of 2 px in the accent, offset 2 px, on every .b", ".b:focus-visible{outline:2px solid var(--acc);outline-offset:2px}" in css)
check("busy: the border and text stay, a 6% text-colour fill over the page colour, the progress cursor, no fading; for the pressed button (aria-busy) and the whole busy form",
      "background:color-mix(in srgb,var(--fg) 6%,var(--bg))" in (re.search(r"\.b\.busy,[^{]*\{([^}]*)\}", css) or [0, ""])[1] and "cursor:progress" in (re.search(r"\.b\.busy,[^{]*\{([^}]*)\}", css) or [0, ""])[1]
      and re.search(r"\.b\.busy,\.b\[aria-busy=true\],form\[aria-busy\] \.b\{", css) and "opacity:1" in (re.search(r"\.b\.busy,[^{]*\{([^}]*)\}", css) or [0, ""])[1], None)
check("the round buttons: a 1.5 px --mut edge, the accent edge and a 10% accent fill on hover", "border:1.5px solid var(--mut)" in (rule("#totop,.fab") or "") and "border-color:var(--acc);background:color-mix(in srgb,var(--acc) 10%,var(--card))" in (rule("#totop:hover,.fab:hover") or ""), (rule("#totop,.fab"), rule("#totop:hover,.fab:hover")))
check("the old per-control looks are gone: no .abtn, .a-btn, .theme, .pbtn or .copy colour or edge rule, and the search box's own button style", ".abtn{" not in css and ".abtn:" not in css and ".a-btn" not in css
      and ".sbox button{flex:none}" in css and "var(--ibd,var(--mut));border-radius:8px;background:var(--ifill,var(--card));color:var(--mut)" not in css and ".draft button.copy{font:inherit" not in css and ".cmd button.copy{position:absolute;top:5px;right:5px;font" not in css)
check("the panel close × keeps its 22 px size (the type scale's): the rule is .b.pbtn, which outranks .b (a bare .pbtn before it would lose)", ".b.pbtn{font-size:22px;line-height:1;flex:none}" in css and ".pbtn{font-size:22px" not in css.replace(".b.pbtn{", ""))
check("red (--p1) is in no button rule", not re.search(r"\.b[.:\[][^{]*\{[^}]*--p1", css) and "--p1" not in render._BTN_CSS)

# ---- 4. the busy labels
AJ = render._ANSWER_JS; LJ = render._LANDED_JS
check("the answer form: the pressed Send reads Sending… and is aria-busy, the form is busy, and a failure puts the label and the state back",
      "s.textContent='Sending\\u2026'" in AJ and "s.name==='act'" in AJ and "s.setAttribute('aria-busy','true')" in AJ and "F.setAttribute('aria-busy','true')" in AJ and "S.innerHTML=L" in AJ and "S.removeAttribute('aria-busy')" in AJ, None)
check("Landed: only Clear all reads Clearing… (a row's Clear and Undo keep their label); all are aria-busy while the request runs; the label comes back when it ends",
      "if(all)b.textContent='Clearing\\u2026'" in LJ and LJ.count("Clearing") == 1 and "if(!undo)b.textContent" not in LJ and "b.setAttribute('aria-busy','true')" in LJ and "b.removeAttribute('aria-busy');b.textContent=lab" in LJ and LJ.count("rest()") >= 2, None)
check("Landed rows: Clear and Undo share one fixed width so the swap never moves the text, and the swapped-in button has no colour fade",
      "li.lrow form.lclear .b,li.lrow form.lundo .b{width:64px;min-width:64px;" in css and "li.lrow .b{transition:none}" in css, None)

# ---- 5. the colours, computed from the stylesheet's own tokens (WCAG 2.x contrast), light and dark
import _colors as C
lum, ratio, mix = C.lum, C.ratio, C.mix
THEMES = C.resolved(css)      # {"light": {token: hex}, "dark": {…}}: each token as the cascade gives it in that theme, a var() or a color-mix() resolved (--acc is var(--orange); the tints blend it over the card)
check("both themes define the accent, the label on it, the status blue and the outline token", all(k in t for t in THEMES.values() for k in ("--bg", "--card", "--fg", "--acc", "--on-acc", "--run", "--ibd", "--selbg")), {n: sorted(t) for n, t in THEMES.items()})
check("the accent is the one orange in both themes (#ad4608 light, #f0a06a dark: tests/orange_scenario.py scans for any other), the status blue stays blue (#2f6fdd light, #7fb0ff dark)",
      THEMES["light"].get("--acc") == "#ad4608" and THEMES["dark"].get("--acc") == "#f0a06a" and THEMES["light"].get("--run") == "#2f6fdd" and THEMES["dark"].get("--run") == "#7fb0ff", {n: (t.get("--acc"), t.get("--run")) for n, t in THEMES.items()})
dis_op = float((re.search(r"opacity:([\d.]+)", rule(".b.main:disabled") or "") or [0, "1"])[1])
hov_pct = int((re.search(r"background:color-mix\(in srgb,var\(--fg\) (\d+)%,var\(--acc\)\)", css[css.find(".b.main:hover"):]) or [0, "0"])[1])
act_pct = int((re.search(r"background:color-mix\(in srgb,var\(--fg\) (\d+)%,var\(--acc\)\)", css[css.find(".b.main:active"):]) or [0, "0"])[1])
check("the main button reads --acc for its fill and --on-acc for its label; the link reads --acc; the secondary reads --fg and --ibd", "background:var(--acc)" in (rule(".b.main") or "") and "color:var(--on-acc)" in (rule(".b.main") or "")
      and re.search(r"(?:^|\})a\{color:var\(--acc\)", css, re.M) is not None, (rule(".b.main"),))
for theme, t in THEMES.items():
    surfaces = {"page": t["--bg"], "card": t["--card"], "selected card": t["--selbg"]}
    for sname, sv in surfaces.items():
        r = ratio(t["--acc"], sv); check(f"{theme}: a link (--acc) on the {sname} is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    r = ratio(t["--on-acc"], t["--acc"]); check(f"{theme}: the main button's label on its fill is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    for nm, pct in (("hover", hov_pct), ("pressed", act_pct)):
        fill = mix(t["--fg"], t["--acc"], pct); r = ratio(t["--on-acc"], fill)
        check(f"{theme}: the main button's label on its {nm} fill ({pct}% --fg over --acc) is {r:.2f}:1 (4.5 needed)", pct > 0 and r >= 4.5, (pct, r))
    for sname in ("page", "card"):
        r = ratio(t["--ibd"], surfaces[sname]); check(f"{theme}: the secondary's outline (--ibd) on the {sname} is {r:.2f}:1 (3 needed)", r >= 3, r)
        r = ratio(t["--fg"], surfaces[sname]); check(f"{theme}: the secondary's text (--fg, full strength) on the {sname} is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    r = ratio(t["--fg"], mix(t["--fg"], t["--bg"], 12)); check(f"{theme}: the secondary's text on its pressed fill (12% --fg) is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
    fill_d = mix(t["--acc"], t["--bg"], dis_op * 100)
    r = ratio(fill_d, t["--bg"]); check(f"{theme}: the disabled main button (fill at {dis_op:.0%}) stays visible on the page: {r:.2f}:1 (1.5 needed) and reads fainter than the live one", 0 < dis_op < 1 and r >= 1.5 and r < ratio(t["--acc"], t["--bg"]), r)
    r = ratio(mix(t["--on-acc"], t["--bg"], dis_op * 100), fill_d); check(f"{theme}: the disabled main button's label is still readable as a label: {r:.2f}:1 (2 needed)", r >= 2, r)
    check(f"{theme}: the accent is not the status blue, and the status blue is what the running and live badges read", t["--acc"] != t["--run"] and ".badge.agent,.badge.due,.badge.done,.badge.w-assigned{--bc:var(--run)}" in css, None)
check("a busy main button keeps its fill and label (the busy fill of the secondary would hide the white label), and the focus ring is the accent",
      all(x in css for x in (".b.main.busy,.b.main[aria-busy=true],form[aria-busy] .b.main{background:var(--acc)", "color:var(--on-acc);opacity:.75}")) and ".b:focus-visible{outline:2px solid var(--acc);outline-offset:2px}" in css, None)
check("the old blue is left only as the status token --run (and the tags' own --t-agent): no page rule reads it as --acc", "--acc:#2f6fdd" not in css and "--acc:#7fb0ff" not in css and css.count("--run:#2f6fdd") == 1 and css.count("--run:#7fb0ff") == 2 and "#eef3fc" not in css and "#1c2534" not in css, None)

if fails: print(f"FAILED: button set scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: button set scenario, {len(ran)} checks")
