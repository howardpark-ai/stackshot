"""Scenario tests for the small UI guards, in six parts that each run in a process of their own: the shipped dark look, the button set, the background of the item lists, the board's one orange, the Projects page's Archived fold and the Your step block on the home page.

Each part keeps the fixture of the suite it came from (a config and a store of its own in a scratch folder: the code under test reads its config and keeps module state at import), so each runs in a process of its own (this file
started again with `--part <name>`), and the parent adds their counts and exits 1 on any failure or any part that did not end cleanly.

Part `dark_default` - the shipped dark look:

Scenario test for the shipped dark look: the dark theme every page starts from is the original orange look (stackshot's shipped values for the color tool, ui/colortool.py SHIPPED: orange text and fills, orange text on a dark brown fill for the small labels), and the light theme is as it was.

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

Part `button_set` - the button set:

Scenario test for the button set (ui/render.py's _BTN_CSS and the classes the pages draw, ui/search.py's submit button) — fixture data, the pages rendered straight from render.Board, no server, no network, no browser.

Covers:
  * every button of every page is a `.b` with no look or size class (the old Primary .pri, Standard .std, Quiet .qt, recommended .rec and the sizes .sm and .xs are gone), in two levels: the secondary
    (a plain `.b`) and the main (`.b.main`, the composer's Send, one per form and nothing else); the round reload button being the one exception; no old .abtn or .a-btn class is left;
  * the mapping: Send in a comment box, a decision's answer box and a step's box; the answer options are cards (a radio input each, no button), the recommended one carrying the "recommended" badge;
    Clear, Clear all and Undo; seen and mark all seen; Watch, Mute and Default with the pressed one .on and aria-pressed; Copy (a command block, the draft, the home row's draft) keeping its .copy hook;
    the panel button, the theme switch and the search submit as .ico buttons; the newer-board banner's Reload as a solid accent button; Audit now as a text link (a button without the .b class);
  * the colours, computed (WCAG 2.x) from the real tokens of the stylesheet in both themes: the orange link and the main button's label on its fill at 4.5:1 or more (the orange part of this file holds the orange's own values and the scan for any other), the secondary's outline at 3:1 or more on the page
    and the card, its text at 4.5:1 or more and at full strength (--fg, not the muted --mut), the disabled main still visible, the status blue kept for running and live;
  * the stylesheet: the secondary look (outline, no fill, full-strength text, 13 px, 32 px tall, 8 px corners), the light hover and pressed fills, the .on, .warn and .ico modifiers, the focus-visible ring, the busy look,
    the coarse-pointer sizes, the round buttons' 1.5 px edge and hover fill, and no red;
  * the busy labels: the answer form's pressed Send reads "Sending…", Closed's Clear all reads "Clearing…" (a row's Clear keeps its label and shares a fixed width with Undo), all with aria-busy, and the script puts the label back;

Part `rows_background` - the background of the item lists:

Scenario test for the background of the item lists (ui/kit.py's ul.ir-rows and li.irow, ui/render.py's ul.fy-list and li.fy-row, ui/search.py's hits) — the stylesheet read straight from render.Board, no server, no network.

A row of Your move, On agent, Queued for release, Waiting, Closed, a project's items and the search hits is a card: the card color (--card) with the board's quiet border (--line) and a 3px left edge in the list's color (the owner's
pick on the row format), the cards of a list in a column with a gap. The lists of the hidden For you page keep the older shape: one group on the page color (--bg) outlined in --ibd (the input outline, 3:1 on the page), rows ruled apart.

Covers:
  * the item lists: ul.ir-rows draws no background and no outline of its own (the cards stand in a column), li.irow is the card (--card, --line, 10px corners), ul.fy-list and li.fy-row keep the group on the page color;
  * the cards: the side-panel cards (.pc: Machines, Runners, Anchor hub), the home count cards, the item page's boxes (.iask, .ianswer, .cmd pre, .md pre) and the other cards keep --card;
  * the edge: each list's color is a tag color (--t-you, --t-agent, --t-release, --t-wait, --t-done) and reads against the card at 3:1 or more in both themes (a non-text boundary, WCAG 1.4.11); the plain edge is the border's own --line;
  * the states of a row, recomputed (WCAG 2.x) against the card from the stylesheet's own tokens in both themes: the row picked by its link (li.irow:target) is a tint of --acc over the card with an accent edge, its text 4.5:1 or more on
    that tint and the edge 3:1 or more on the card; the title link on hover and the focus ring (--acc), the "Your move" markers (.attn, .own, the tag and the For you urgent edge), the amber and red ages, the muted lines, the project line and the For you
    time, all against the card (the page for the For you ones).

Part `orange` - the board's one orange:

Scenario test for the board's one orange (ui/render.py's --orange token and what reads it; ui/kit.py's --t-you) — the source scanned, the pages rendered straight from render.Board, no server, no network.

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

Part `archive_fold_view` - the Projects page's Archived fold:

Scenario test for the Projects page's Archived fold — fixture data, no live store, no network, no server process (the render module is imported and called
in-process, on a temporary config).

Covers: the archived projects (a page status in retired_statuses) sit in one foldable group named Archived, drawn as home's scope subsections are (a native
`<details class="fold sfold">` whose summary holds `h3.iscope` with the name and the count of its projects, a data-fold key), closed on load, after the active projects,
with the projects listed by scope inside; the count is the number of archived projects over every scope; a page with no archived project draws no group; a scope
whose projects are all archived keeps its side-panel anchor inside the group, and the page opens the fold on a hash (the fold script is on the page); the word
"finished" is gone from the Projects page's table, the side panel's hover text (`N active, M archived`) and the project page's group of agents, which says Archived;
and a project whose last agent is retired shows in the group once its page says archived.

Part `home_step` - the Your step block on the home page:

Scenario test for the Your step block on the home page's Your move rows (ui/render.py: Board.home_step) — fixture data, no live store, no network, no server.

Covers:
  * a your-step item whose Next holds two open lines of the owner's, each with a command: the home row draws both lines in one numbered list and no summary line, without their
    `Oliver:` openers, each command in a code block with its Copy box, as the item page's Your step block does; the agent's lines are not in it; the note box and Send follow;
  * a your-step item with no open line of the owner's draws its step as before: the step line and nothing more, no list.

    tests/run-suite ui_guards        -> exit 0 / 1"""
import base64, json, logging, os, pathlib, re, subprocess, sys, time, urllib.parse
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR)
PARTS = ("dark_default", "button_set", "rows_background", "orange", "archive_fold_view", "home_step")

def _setup(prefix, *, owner=False, audit=False, rules=False, board=None, extra_dirs=()):
    """The scratch folder and the instance config of a part: every path inside the scratch folder, the fixtures' timezone and prefixes, the environment the config is read from, the folders every part's store needs. Returns (tmp, T)."""
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    if owner: toml = _instance.set_person(toml)
    if audit: toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1      # the Audit card (and its button) is drawn
    if board:
        for pat, rep in ((r'(?m)^board_url = "[^"]*"', f'board_url = "{board}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{board}"'), (r'(?m)^ui_open = true', 'ui_open = false')):
            toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    if rules: (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", *(("secrets",) if rules else ()), *extra_dirs): (T / d).mkdir(parents=True)
    return tmp, T

def _checker(limit):
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:limit]}" if got is not None else ""))
    return check, fails, ran

def _fleet_alpha(T, HERE, now):
    """The fleet and project fixture of the three page parts that draw the home page for one owner session: one machine, one session, one active project."""
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now}}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))

ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def _item_writer(T, HERE, now):
    H = 3600.0
    def item(i, subject, status="open", su=None, **meta):
        su = now - 3 * H if su is None else su
        d = {"id": str(i), "subject": subject, "description": "A thing. It lives here.", "status": status, "updated": su, "state_updated": su, "confirmed": su,
             "metadata": {"owner": HERE, "project": "projects/alpha", **meta}}
        (T / f"store/a/{i}.json").write_text(json.dumps(d))
    return item


# ================================================================ part dark_default: the shipped dark look
def part_dark_default():
    import _colors as C
    tmp, T = _setup("darkdefault-", owner=True)
    HERE = "00000000-0000-4000-8000-000000000001"
    now = time.time(); H = 3600.0
    _fleet_alpha(T, HERE, now)
    (T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] ask with options", "description": "A thing. It lives here.", "status": "open", "updated": now - 3 * H, "state_updated": now - 3 * H,
                                                  "confirmed": now - 3 * H, "metadata": {"owner": HERE, "project": "projects/alpha", "needs": ["decision"], "ask": "Decide: whether to ship · Recommend: ship · Stakes: none · By: no date",
                                                  "options": [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}], "mover": "Oliver", "then": "home-other", "next": "Oliver: decide"}}))
    (T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web.ui import render, colortool as ct
    from stackshot.web import search as sm
    Bd = lambda: render.Board(f"{tmp}/store", now=None)
    sm.sync(Bd())
    BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
    PAGES = {"home": Bd().html(), "item": Bd().item_html("a1", answer=BOX), "project": Bd().routing_html("projects/alpha"), "Projects": Bd().projects_html(), "Closed": Bd().landed_html()}

    check, fails, ran = _checker(700)

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

    return ran, fails


# ================================================================ part button_set: the button set
def part_button_set():
    tmp, T = _setup("buttonset-", owner=True, audit=True)
    HERE = "00000000-0000-4000-8000-000000000001"
    now = time.time(); H = 3600.0
    _fleet_alpha(T, HERE, now)
    item = _item_writer(T, HERE, now)
    item(1, "[home] ask with options", needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", then="home-other", next="Oliver: decide")
    item(2, "[home] ask with no options", needs=["decision"], ask=ASK, mover="Oliver", then="home-other", next="home-other: wait")           # Yes and No
    item(3, "[home] agent item", mover="home-other", next="home-other: x", needs=["home-other"])                                                  # the comment box in the answer box's slot
    item(4, "[home] your step", state="your-step", step="run the one line `sala op reauth box-a --from me --words \"go\"` and say done", mover="Oliver", then="home-other",
         needs=["home-other"], next="home-other: check it", draft="Hello,\nthe draft text.")
    item(5, "[home] closed one", status="completed", su=now - 2 * H, outcome="done", reason="shipped", mover=None)
    (T / "store/next-id").write_text("40"); (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web.ui import render, search
    from stackshot.service import landed as ld; from stackshot.service import foryou as fy; from stackshot.web import i18n_catalog
    bd = render.Board(f"{tmp}/store")
    BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
    for k, (g, w) in enumerate((("a50", "older row"), ("a51", "newer row"))):
        fy.add(key=f"page:{k}", kind="closed", gid=g, item=g, project="projects/alpha", what=w, url=f"/items/{g[1:]}", ts=now - 60 * (k + 1))
    item(6, "[home] another closed one", status="completed", su=now - H, outcome="done", reason="shipped too", mover=None)
    for k, g in enumerate(("a5", "a6")): ld.record(g, now - 100 * (k + 1), "done", by="home-x", project="projects/alpha")
    check, fails, ran = _checker(900)
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
    bad = [(name, c, lab) for name, h in ALL.items() for c, nv, lab, a in buttons(h) if not (c & {"fab", "pgrip", "pmi", "xp-b"}) and "b" not in c and 'id="audit-now"' not in a]
    check("every button of the board, the Closed page and the item pages is a .b; the round reload button, the summary panel's order controls (the grip and the move menu's items, styled in _PORDER_CSS), the explainer's \"?\" (.xp-b, styled in ui/explain.py) and the Audit card's Audit now text link (#audit-now, styled in _RUN_CSS) are the others", not bad, bad[:6])
    old = [(name, sorted(c), lab) for name, h in ALL.items() for c, nv, lab, a in buttons(h) if c & {"pri", "std", "qt", "rec", "sm", "xs"}]
    check("no button carries a look or size class (pri, std, qt, rec, sm, xs)", not old, old[:6])
    check("no page draws the old .abtn or .a-btn class (the .abtns row of buttons is not a button)", all(not re.search(r'class="[^"]*\babtn\b', h) and "a-btn" not in h for h in ALL.values()))
    def groups(h): return [m.group(1) for m in re.finditer(r'<div class="abtns[^"]*">(.*?)</div>', h, re.S)]
    check("a form with options draws them as cards, not buttons, and holds one Send; so does the lone Send of a form with no options",
          all('<input type="radio" name="choice"' in pg[g] and not [b for b in buttons(pg[g]) if b[1].startswith("choice=")] and len(re.findall(r'<button type="submit" class="b main" name="act"', "".join(groups(pg[g])))) == 1 for g in ("a1", "a2"))
          and '<button type="submit" class="b main" name="act" value="comment"' in pg["a3"])
    def forms(h): return re.findall(r"<form\b.*?</form>", h, re.S)
    mains = [(name, b[1], b[2]) for name, h in ALL.items() for b in buttons(h) if "main" in b[0]]
    check("the main button is the composer's Send or a step form's Done and nothing else: every .main button on every page is a Send (act=answer or comment) or a Done (act=done)", mains and all((nv in ("act=answer", "act=comment") and lab == "Send") or (nv == "act=done" and lab == "Done") for _, nv, lab in mains), mains[:8])
    check("one main button per form: no form on any page holds two, and every Send is a main (a step form's Send note is secondary)",
          all(len([b for b in buttons(f) if "main" in b[0]]) <= 1 for h in ALL.values() for f in forms(h))
          and all("main" in b[0] for h in ALL.values() for b in buttons(h) if b[2] == "Send"), None)
    check("every other button (Clear, Clear all, Undo, seen, Copy, Watch, Mute, Default, Reload, the icon buttons) is secondary: no .main", all("main" not in b[0] for h in ALL.values() for b in buttons(h) if b[2] not in ("Send", "Done")), None)

    # ---- 2. the mapping
    c = lambda h, nv: [b[0] for b in buttons(h) if b[1] == nv]
    def cards(h):
        """{label: (radio value, whether the card carries the recommended badge)} for the option cards of a page."""
        return {re.search(r'class="alab">(?:<span class="akey">[A-Z]</span>)?([^<]*)<', m.group(2)).group(1): (m.group(1), 'class="badge rec"' in m.group(2))
                for m in re.finditer(r'<label class="acard"><input type="radio" name="choice" value="([^"]*)">(.*?)</label>', h, re.S)}
    check("answer options: one card each, in the order drawn, the recommended one first with its badge and the others without (item page, stored options)",
          cards(pg["a1"]) == {"Ship": ("Ship", True), "Wait": ("Wait", False)} and list(cards(pg["a1"])) == ["Ship", "Wait"], cards(pg["a1"]))
    check("answer options: Yes (recommended) and No cards when none are stored", cards(pg["a2"]) == {"Yes": ("Yes", True), "No": ("No", False)}, cards(pg["a2"]))
    check("Send is the main .b in every answer box: beside the option cards (item page), the comment box; a step's Done is the main .b and its Send note a plain .b",
          c(pg["a1"], "act=answer") == [{"b", "main"}] and c(pg["a2"], "act=answer") == [{"b", "main"}] and c(pg["a3"], "act=comment") == [{"b", "main"}] and c(pg["a4"], "act=done") == [{"b", "main"}] and c(pg["a4"], "act=note") == [{"b"}] and not c(pg["a4"], "act=send"),
          (c(pg["a1"], "act=answer"), c(pg["a3"], "act=comment"), c(pg["a4"], "act=done"), c(pg["a4"], "act=note")))
    comm = bd.answer_html(json.loads((T / "store/a/3.json").read_text()) | {"gid": "a3"}, BOX, comment_only=True)
    check("the comment-only box's Send is the main .b", c(comm, "act=comment") == [{"b", "main"}], comm[-300:])
    hc = cards(home)
    check("the home row's ask form: the option cards with the recommended one badged, Send the main .b (drawn disabled until a token comes); a step's row Done the main .b and its Send note a plain .b, both drawn disabled the same way",
          hc.get("Ship") == ("Ship", True) and hc.get("Wait") == ("Wait", False) and not [b for b in buttons(home) if b[1].startswith("choice=")]
          and c(home, "act=answer") and all(x == {"b", "main"} for x in c(home, "act=answer")) and c(home, "act=done") == [{"b", "main"}] and c(home, "act=note") == [{"b"}] and not c(home, "act=send"),
          (hc, c(home, "act=answer"), c(home, "act=done"), c(home, "act=note")))
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
          "s.textContent=SST('js.answer.sending')" in AJ and i18n_catalog.CATALOG["js.answer.sending"] == "Sending\u2026" and "s.name==='act'" in AJ and "s.setAttribute('aria-busy','true')" in AJ and "F.setAttribute('aria-busy','true')" in AJ and "S.innerHTML=L" in AJ and "S.removeAttribute('aria-busy')" in AJ, None)
    check("Landed: only Clear all reads Clearing… (a row's Clear and Undo keep their label); all are aria-busy while the request runs; the label comes back when it ends",
          "if(all)b.textContent=SST('js.closed.clearing')" in LJ and LJ.count("js.closed.clearing") == 1 and "if(!undo)b.textContent" not in LJ and "b.setAttribute('aria-busy','true')" in LJ and "b.removeAttribute('aria-busy');b.textContent=lab" in LJ and LJ.count("rest()") >= 2, None)
    check("Landed rows: Clear and Undo share one fixed width so the swap never moves the text, and the swapped-in button has no colour fade",
          "li.lrow form.lclear .b,li.lrow form.lundo .b{width:64px;min-width:64px;" in css and "li.lrow .b{transition:none}" in css, None)

    # ---- 5. the colours, computed from the stylesheet's own tokens (WCAG 2.x contrast), light and dark
    import _colors as C
    lum, ratio, mix = C.lum, C.ratio, C.mix
    THEMES = C.resolved(css)      # {"light": {token: hex}, "dark": {…}}: each token as the cascade gives it in that theme, a var() or a color-mix() resolved (--acc is var(--orange); the tints blend it over the card)
    check("both themes define the accent, the label on it, the status blue and the outline token", all(k in t for t in THEMES.values() for k in ("--bg", "--card", "--fg", "--acc", "--on-acc", "--run", "--ibd", "--selbg")), {n: sorted(t) for n, t in THEMES.items()})
    check("the accent is the one orange in both themes (#ad4608 light, #f0a06a dark: the orange part of this file scans for any other), the status blue stays blue (#2f6fdd light, #7fb0ff dark)",
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
    # ---- 6. the connection strip (the newer-board notice with its Reload button): a calm panel strip, the button the solid accent
    strip = rule(".conn") or ""
    check("the strip is a --card panel with a 1 px --line bottom border only, no accent or warn color mixed into its background or edge",
          "background:var(--card)" in strip and "border-bottom:1px solid var(--line)" in strip and "border:0" in strip and "color-mix" not in strip and "--warn" not in strip and "--acc" not in strip, strip)
    reload_rule = rule(".conn .b.warn") or ""
    check("the strip's Reload is a solid --acc fill with the --on-acc label, no border, 8 px corners, weight 600, padding 4px 12px",
          all(x in reload_rule for x in ("background:var(--acc)", "color:var(--on-acc)", "border:0", "border-radius:8px", "font-weight:600", "padding:4px 12px")), reload_rule)
    check("the strip's Reload keeps the shared keyboard focus ring (no outline rule of its own) and shifts its fill toward --fg under the pointer and when pressed (darker in light, lighter in dark), keeping its label color",
          "outline" not in reload_rule and ".b:focus-visible{outline:2px solid var(--acc);outline-offset:2px}" in css
          and "@media(hover:hover){.conn .b.warn:hover:not(:disabled){background:color-mix(in srgb,var(--fg) 14%,var(--acc));color:var(--on-acc)}}" in css
          and ".conn .b.warn:active:not(:disabled){background:color-mix(in srgb,var(--fg) 24%,var(--acc));color:var(--on-acc)}" in css, reload_rule)
    new_rule = rule(".conn.new") or ""
    check("the unreachable and signed-out states carry the warn color on their text (one rule, .conn.down and .conn.out); the Reload state (.conn.new) carries none", re.search(r"\.conn\.down,\.conn\.out\{color:var\(--warn\)\}", css) is not None
          and "--warn" not in new_rule and not re.search(r"\.conn\.new[^{]*\{[^}]*--warn", css) and "--warn" not in strip, (new_rule, strip))
    for theme, t in THEMES.items():
        r = ratio(t["--warn"], t["--card"]); check(f"{theme}: the warn text of the unreachable and signed-out strips (--warn on --card) is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        r = ratio(t["--fg"], t["--card"]); check(f"{theme}: the strip's text (--fg) on its --card fill is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        r = ratio(t["--on-acc"], t["--acc"]); check(f"{theme}: the strip's Reload label (--on-acc) on its --acc fill is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        for nm, pct in (("hover", 14), ("pressed", 24)):
            r = ratio(t["--on-acc"], mix(t["--fg"], t["--acc"], pct)); check(f"{theme}: the strip's Reload label on its {nm} fill is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)

    return ran, fails


# ================================================================ part rows_background: the background of the item lists
def part_rows_background():
    import _scratch, _colors as C
    tmp = _scratch.mkdtemp(prefix="rowsbg-"); (pathlib.Path(tmp) / "store").mkdir()
    sys.path.insert(0, STACK)
    logging.disable(logging.INFO)
    from stackshot.web.ui import render
    css = render.Board(f"{tmp}/store")._css()

    check, fails, ran = _checker(900)

    RULES = [(tuple(s.strip() for s in sel.split(",")), body) for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))]
    def bodies(sel):
        """The bodies of every rule whose selector list holds `sel` exactly."""
        return [b for sels, b in RULES if sel in sels]
    def decl(sel, prop):
        """The values `prop` takes in the rules of `sel`, in the order of the stylesheet."""
        return [m for b in bodies(sel) for m in re.findall(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]*)", b)]

    LISTS = ["ul.ir-rows", "li.irow", "ul.fy-list", "li.fy-row", "ul.ir-rows.se-hits", "li.irow.lrow", "li.irow.srow", "details.hscope ul.ir-rows", "section.lcompleted ul.ir-rows"]
    CARD_LISTS = ["ul.ir-rows", "ul.ir-rows.se-hits", "li.irow.lrow", "li.irow.srow", "details.hscope ul.ir-rows", "section.lcompleted ul.ir-rows"]      # the item lists other than li.irow itself, which carries the card

    # ---- the item lists are columns of cards; the For you list keeps the group on the page color
    check("ul.ir-rows (home, Closed, a project's items, the search hits) draws no background and no outline of its own: the cards stand in a column with a gap",
          decl("ul.ir-rows", "background") == [] and decl("ul.ir-rows", "border") == [] and decl("ul.ir-rows", "overflow") == [] and decl("ul.ir-rows", "display") == ["flex"] and decl("ul.ir-rows", "gap") == ["12px"],
          {k: decl("ul.ir-rows", k) for k in ("background", "border", "overflow", "display", "gap")})
    check("ul.fy-list (For you) takes the page color", decl("ul.fy-list", "background") == ["var(--bg)"], decl("ul.fy-list", "background"))
    check("li.irow is the card: the card color, the board's quiet border, 10px corners, a 3px left edge in --st",
          decl("li.irow", "background") == ["var(--card)"] and decl("li.irow", "border") == ["1px solid var(--line)"] and decl("li.irow", "border-left") == ["3px solid var(--st)"] and decl("li.irow", "border-radius") == ["10px"],
          {k: decl("li.irow", k) for k in ("background", "border", "border-left", "border-radius")})
    check("no other rule of an item-list selector sets a background from --card (the card is li.irow's alone)",
          not [(s_, b) for sels, b in RULES for s_ in sels if s_ in CARD_LISTS and "--card" in b], [(s_, b[:80]) for sels, b in RULES for s_ in sels if s_ in CARD_LISTS and "--card" in b])
    check("no rule of an item-list selector sets a background other than the card, the page color or the :target tint",
          all(v in ("var(--bg)", "var(--card)") or v.startswith("color-mix(in srgb,var(--acc)") or v in ("none", "transparent") for s_ in LISTS for v in decl(s_, "background")), {s_: decl(s_, "background") for s_ in LISTS})
    check("li.fy-row sets no background (the list shows through)", decl("li.fy-row", "background") == [], decl("li.fy-row", "background"))

    # ---- the cards keep the card color
    for sel in (".pc", "a.hcard", ".iask", ".ianswer", ".cmd pre", ".md pre", ".draft pre", "nav.lpager .pg", ".pmenu", ".acards .acard"):
        check(f"{sel} keeps the card color", decl(sel, "background") == ["var(--card)"], decl(sel, "background"))

    # ---- the outline
    check("the For you list's outline and the rule between its rows are --ibd", decl("ul.fy-list", "border") == ["1px solid var(--ibd)"] and decl("li.fy-row", "border-top") == ["1px solid var(--ibd)"], (decl("ul.fy-list", "border"), decl("li.fy-row", "border-top")))
    check("li.irow has no rule between rows (a card has its whole border) and the plain card edge is --line", decl("li.irow", "border-top") == [] and "li.irow:first-child{" not in css and decl("li.irow", "--st") == ["var(--line)"], (decl("li.irow", "border-top"), decl("li.irow", "--st")))
    check("li.hrow sets no border and no :target tint of its own (li.irow carries both; a rule of li.hrow would only lose to it by order)",
          decl("li.hrow", "border-top") == [] and decl("li.hrow", "border") == [] and bodies("li.hrow:target") == [] and bodies("li.hrow:first-child") == [], (bodies("li.hrow"), bodies("li.hrow:target")))
    check("the controls directly under a list (Show more, the Closed pager) outline in --ibd",
          decl("a.se-more", "border") == ["1px solid var(--ibd)"] and decl("nav.lpager .pg", "border") == ["1px solid var(--ibd)"], (decl("a.se-more", "border"), decl("nav.lpager .pg", "border")))
    check("the search summary above the hits closes with the same outline, and the hits stand a card's gap below it", ".se-summary{padding:9px 2px;font-size:13px;color:var(--mut);border-bottom:1px solid var(--ibd)}" in css and decl("ul.ir-rows.se-hits", "margin-top") == ["12px"])

    TK = C.resolved(css)
    THEMES = {"light": TK["light"], "dark": TK["dark"]}
    for th, t in THEMES.items():
        bg = t["--bg"]
        r = C.ratio(t["--ibd"], bg); check(f"{th}: the outline (--ibd) on the page is {r:.2f}:1 (3 needed)", r >= 3.0, r)
        r = C.ratio(t["--line"], bg); check(f"{th}: --line on the page is {r:.2f}:1, under the 3:1 an outline needs, so it is not the row outline", r < 3.0, r)

    # ---- the states against the card
    tint = re.search(r"li\.irow:target\{background:color-mix\(in srgb,var\(--acc\) (\d+)%,var\(--card\)\);box-shadow:inset 3px 0 0 var\(--acc\)\}", css)
    check("a row picked by its link: an accent tint over the card and a 3px accent edge", bool(tint), [b for b in bodies("li.irow:target")])
    pct = int(tint.group(1)) if tint else 0
    for th, t in THEMES.items():
        bg = t["--card"]; acc = t["--acc"]; pk = C.mix(acc, bg, pct)
        for name, tok in (("title and text (--fg)", "--fg"), ("age and who lines (--mut)", "--mut")):
            r = C.ratio(t[tok], pk); check(f"{th}: {name} on the picked row is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        r = C.ratio(acc, bg); check(f"{th}: the picked row's accent edge on the card is {r:.2f}:1 (3 needed)", r >= 3.0, r)
        r = C.ratio(acc, pk); check(f"{th}: the accent link on the picked row is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        for name, fgc in (("the title link on hover (--acc)", t["--acc"]), ("the focus ring (--acc)", t["--acc"])):
            r = C.ratio(fgc, bg); check(f"{th}: {name} on the card is {r:.2f}:1 ({3 if 'ring' in name else 4.5} needed)", r >= (3.0 if "ring" in name else 4.5), r)
        for name, tok, need in (("the 'Your move' words (.attn, .own: --t-you)", "--t-you", 4.5), ("the For you urgent edge (--call)", "--call", 3.0), ("the amber age", "--amber", 4.5), ("the red age", "--red", 4.5),
                                ("the muted who line, project line and For you time (--mut)", "--mut", 4.5), ("the title (--fg)", "--fg", 4.5)):
            r = C.ratio(t[tok], bg); check(f"{th}: {name} on the card is {r:.2f}:1 ({need} needed)", r >= need, r)
        for kind in ("you", "agent", "release", "wait", "done"):
            r = C.ratio(t[f"--t-{kind}"], bg); check(f"{th}: the {kind} edge (--t-{kind}) on the card is {r:.2f}:1 (3 needed)", r >= 3.0, r)
        r = C.ratio(t["--t-you"], t["--t-you-bg"]); check(f"{th}: the 'Your move' tag text on its tint is {r:.2f}:1 (4.5 needed)", r >= 4.5, r)
        # a cleared Landed row dims to 45% on purpose: its contrast is a number to read, not a floor
        dim = C.mix(t["--fg"], bg, 45); print(f"info {th}: a cleared Closed row (45% text over the card) {C.ratio(dim, bg):.2f}:1")
        print(f"info {th}: outline --ibd {C.ratio(t['--ibd'], bg):.2f}:1, --line {C.ratio(t['--line'], bg):.2f}:1 on the page; picked-row tint {pct}% of --acc is {C.ratio(pk, bg):.2f}:1 against the card")

    return ran, fails


# ================================================================ part orange: the board's one orange
def part_orange():
    import _colors as C
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

    # ---- the page fixture (the same shape as the button set part's)
    tmp, T = _setup("orange-", owner=True, audit=True)
    HERE = "00000000-0000-4000-8000-000000000001"
    now = time.time(); H = 3600.0
    _fleet_alpha(T, HERE, now)
    item = _item_writer(T, HERE, now)
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

    check, fails, ran = _checker(900)

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

    return ran, fails


# ================================================================ part archive_fold_view: the Projects page's Archived fold
def part_archive_fold_view():
    tmp, T = _setup("archgrp-", rules=True, extra_dirs=("brain/infra",))
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({}))
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
    def page(rel, front):
        q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    check, fails, ran = _checker(600)

    page("projects/w-live.md", "type: project\ntitle: Work live\norg: work\ndisplay-name: work-wlive\nagents:\n  work-wlive-main: talks\nstatus: active")
    page("projects/w-old.md", "type: project\ntitle: Work old\norg: work\ndisplay-name: work-wold\nstatus: archived")
    page("projects/h-live.md", "type: project\ntitle: Home live\norg: home\ndisplay-name: home-hlive\nagents:\n  home-hlive-main: talks\nstatus: active")
    page("projects/h-old.md", "type: project\ntitle: Home old\norg: home\ndisplay-name: home-hold\nstatus: done")
    page("projects/o-old.md", "type: project\ntitle: Infra old\ntags:\n  - infra\ndisplay-name: zeta-zold\nstatus: Archived")
    from stackshot.projects import pages as p
    from stackshot.web.ui import render as ui_render
    p.cmd_registry(quiet=True)
    def board(): return ui_render.Board(f"{tmp}/store")
    def text(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", h))
    OPEN = re.compile(r'<details class="fold sfold" data-fold="projects.archived"( open)?>')
    HEAD = '<summary><h3 class="iscope">Archived <span class="count">3</span></h3></summary>'

    # ---- the group
    bd = board(); tab = bd.projects_table()
    m = OPEN.search(tab)
    check("Archived: one foldable group, drawn with home's fold markup (details.fold.sfold, a data-fold key) and closed on load", len(OPEN.findall(tab)) == 1 and m and not m.group(1), tab[:300])
    check("Archived: the heading is home's: h3.iscope with the name and the count of the archived projects over every scope (3: work, home and infra)", HEAD in tab, text(tab)[:400])
    check("Archived: it follows the active table and holds the archived projects, by scope", tab.index("w-live") < tab.index(HEAD) < tab.index("w-old") and tab.index("w-old") < tab.index("h-old") < tab.index("o-old")
          and tab.index("h-live") < tab.index(HEAD), text(tab))
    check("Archived: the old closed 'finished' details and its lowercase summary are gone from the table", "finished" not in tab and '<details class="finished"' not in tab)
    check("Archived: the markup stays balanced (details, tables)", tab.count("<details") == tab.count("</details>") == 1 and tab.count("<table") == tab.count("</table>") == 2, (tab.count("<details"), tab.count("<table")))
    from stackshot.web.ui import groups as _grp
    check("Archived: the same helper draws home's scope subsections (groups.fold) and this group (groups.fold_block); a subsection is still open with its hscope class",
          _grp.fold("k", "work", ["<li>x</li>"]).startswith('<details class="fold sfold hscope" data-fold="k" open><summary><h3 class="iscope">work <span class="count">1</span></h3></summary>')
          and _grp.fold_block("k", "Archived", 2, "", opened=False, cls="fold sfold") == '<details class="fold sfold" data-fold="k"><summary><h3 class="iscope">Archived <span class="count">2</span></h3></summary></details>')
    check("Archived: the infra scope has only an archived project, so its anchor (the side panel's link) sits inside the group", tab.index('id="' + bd.scope_anchor("infra") + '"') > tab.index(HEAD)
          and tab.index('id="' + bd.scope_anchor("work") + '"') < tab.index(HEAD), text(tab))

    # ---- the page and the side panel
    html = board().projects_html()
    check("Projects page: it carries the Archived heading and the fold script (a hash into the closed group opens it)", HEAD in html and "go(location.hash,false)" in html and html.count('data-fold="projects.archived"') == 1)
    panel = board().panel_blocks()["projects-panel"]
    check("side panel: a scope's hover text says 'N active, M archived' (the word 'finished' is gone)", 'title="1 active, 1 archived"' in panel and "finished" not in panel, text(panel))
    check("side panel: a scope with only archived projects says '0 active, 1 archived'", 'title="0 active, 1 archived"' in panel, text(panel))

    # ---- the project page
    page("projects/w-old.md", "type: project\ntitle: Work old\norg: work\ndisplay-name: work-wold\nagents:\n  work-wold-main: was the contact\nstatus: archived")
    p.cmd_registry(quiet=True)
    n, h = board().sessions_html("projects/w-old")
    check("project page: an archived project's agents sit in a closed group titled Archived (not 'finished')", n == 1 and h.startswith('<details class="archived"><summary>Archived</summary>') and "finished" not in h and not re.match(r"<details[^>]*\bopen", h), h[:200])

    # ---- no archived project → no group; a project archived after its last agent retired joins the group
    for rel in ("projects/w-old.md", "projects/h-old.md", "projects/o-old.md"): (T / "brain" / rel).unlink()
    p.cmd_registry(quiet=True)
    tab2 = board().projects_table()
    check("Archived: with no archived project there is no group", "Archived" not in tab2 and "<details" not in tab2 and "w-live" in tab2, text(tab2))
    page("projects/w-live.md", "type: project\ntitle: Work live\norg: work\ndisplay-name: work-wlive\nagents:\nstatus: archived")      # its last agent retired and the page archived (project_archive.py)
    p.cmd_registry(quiet=True)
    tab3 = board().projects_table()
    check("Archived: a project whose last agent was retired and whose page says archived is in the group, count 1", '<h3 class="iscope">Archived <span class="count">1</span></h3>' in tab3 and tab3.index("w-live") > tab3.index("Archived"), text(tab3))

    return ran, fails


# ================================================================ part home_step: the Your step block on the home page
def part_home_step():
    BOARD = "https://board.example.org"
    tmp, T = _setup("homesteptest-", owner=True, rules=True, board=BOARD)
    OWNER = "00000000-0000-4000-8000-000000000001"
    AGENT = "00000000-0000-4000-8000-000000000002"
    now = time.time()
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
    STEP = "Two lines in a shell on your laptop"
    def item(i, **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open",
                                                         "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                         "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], **meta}}))
    item(1, state="your-step", step=STEP, next="home-agent: prepare the box\nOliver: run `uv run tool.py --check` and read the output\nOliver: then run `git log --oneline -3` and paste it\nhome-agent: check what he pasted")
    item(2, state="your-step", step=STEP, next="home-agent: prepare the box")
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
    git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    check, fails, ran = _checker(900)

    import stackshot.web.ui.render as render2

    def row(page, i):
        m = re.search(rf'<li class="(?:irow )?hrow" id="task-a-{i}"(?: data-st="[a-z]+")?>(.*?)</li>(?=<li class="(?:irow )?hrow"|</ul>)', page, re.S)
        return m.group(1) if m else ""

    for label, mod in (("ui/render.py", render2),):
        page = mod.Board(str(T / "store")).html()
        r1, r2 = row(page, 1), row(page, 2)
        check(f"{label}: both your-step items are rows of Your move", bool(r1) and bool(r2), page[page.find('id="your-move"'):][:600])
        sn = re.search(r'<div class="istepnext">(.*?)</div>(?=<div class="hask">|</span></div><div class="ir-act">)', r1, re.S)
        sn_html = sn.group(1) if sn else ""
        check(f"{label}: the row with two open lines of his draws his lines in one numbered list and no summary line, before the note box",
              STEP not in r1 and -1 < r1.find('<div class="istepnext">') < r1.find('<form class="hanswer hstep"') and sn_html.startswith('<ol class="stepol"')
              and sn_html.count("<li>") == 2 and "and read the output" in sn_html and "and paste it" in sn_html, r1[:1500])
        check(f"{label}: each of his two commands is a code block with its own Copy box",
              sn_html.count('<div class="cmd">') == 2 and "uv run tool.py --check</code></pre><button" in sn_html and "git log --oneline -3</code></pre><button" in sn_html
              and sn_html.count('class="b copy"') == 2, sn_html[:1200])
        check(f"{label}: the lines carry no 'Oliver:' opener and none of the agent's lines",
              "Oliver:" not in sn_html and "prepare the box" not in sn_html and "check what he pasted" not in sn_html, sn_html[:900])
        check(f"{label}: the row with no line of his draws the step as before: the step line, no list, no command block, then the note box",
              STEP in r2 and 'class="istepnext"' not in r2 and '<div class="cmd">' not in r2 and '<form class="hanswer hstep"' in r2, r2[:900])
        b = mod.Board(str(T / "store"))
        r2_item = next(x for x in b.rows if x["gid"] == "a2")
        check(f"{label}: home_step of an item with no line of his returns the step block exactly as before (the step with its draft, nothing added)",
              b.home_step(r2_item)[0] == b.step_block_html(r2_item, home=True), b.home_step(r2_item)[0][:400])

    return ran, fails


MARK = "@@ui_guards part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = globals()["part_" + name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as the archive and home-step suites always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: ui_guards scenario, {total} checks")
