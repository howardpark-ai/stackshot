"""Scenario test for the background of the item lists (ui/kit.py's ul.ir-rows and li.irow, ui/render.py's ul.fy-list and li.fy-row, ui/search.py's hits) — the stylesheet read straight from render.Board, no server, no network.

A row of Your move, On agent, Queued for release, Waiting, Closed, a project's items and the search hits is a card: the card color (--card) with the board's quiet border (--line) and a 3px left edge in the list's color (the owner's
pick on the row format), the cards of a list in a column with a gap. The lists of the hidden For you page keep the older shape: one group on the page color (--bg) outlined in --ibd (the input outline, 3:1 on the page), rows ruled apart.

Covers:
  * the item lists: ul.ir-rows draws no background and no outline of its own (the cards stand in a column), li.irow is the card (--card, --line, 10px corners), ul.fy-list and li.fy-row keep the group on the page color;
  * the cards: the side-panel cards (.pc: Machines, Runners, Anchor hub), the home count cards, the item page's boxes (.iask, .ianswer, .cmd pre, .md pre) and the other cards keep --card;
  * the edge: each list's color is a tag color (--t-you, --t-agent, --t-release, --t-wait, --t-done) and reads against the card at 3:1 or more in both themes (a non-text boundary, WCAG 1.4.11); the plain edge is the border's own --line;
  * the states of a row, recomputed (WCAG 2.x) against the card from the stylesheet's own tokens in both themes: the row picked by its link (li.irow:target) is a tint of --acc over the card with an accent edge, its text 4.5:1 or more on
    that tint and the edge 3:1 or more on the card; the title link on hover and the focus ring (--acc), the "Your move" markers (.attn, .own, the tag and the For you urgent edge), the amber and red ages, the muted lines, the project line and the For you
    time, all against the card (the page for the For you ones).

    tests/run-suite rows_background        → exit 0 / 1"""
import logging, os, pathlib, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _colors as C

tmp = _scratch.mkdtemp(prefix="rowsbg-"); (pathlib.Path(tmp) / "store").mkdir()
logging.disable(logging.INFO)
from stackshot.web.ui import render
css = render.Board(f"{tmp}/store")._css()

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

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

print(f"ok: rows background scenario, {len(ran)} checks" if not fails else f"FAILED: rows background scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1 if fails else 0)
