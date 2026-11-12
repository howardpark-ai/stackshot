"""ui/kit.py — the pages' one item system: the state words and their colors, the row every list draws, and the type scale.

Why a module of its own: the redesign of the pages (one row for every list, one set of state words, one color per meaning, five text sizes) is a set of small, pure
pieces that the page code in ui/render.py, ui/search.py and the Closed page share. Nothing here reads the store or draws a whole page; render.py computes what a row says and
this module puts it in the one shape.

The row (every list): a card with a 3px edge on its left in the list's color (home's lists and the Closed page's New section; Last 14 days, Search and the project page's closed items keep the plain edge); above the title, a small quiet
project line where the page names one (home and Closed); a title line, `[state tag] #id title ... age`, the title wrapping and never cut; a who line (small, gray, drawn only when it says something); a detail
line behind a guide line (the one thing that matters in this state); and the actions (the answer form on Your move, Clear on Landed) under the detail.

The state words (one set, every page): Your move · On agent · Queued for release · Waiting · Done · Dropped · Superseded. A tag is drawn only where a list mixes states (Completed, Landed, Search,
the item page); on Your move, On agent, Queued for release and Waiting the list's heading says it. Red is held for overdue (a Your move age past five days) and priority P1; amber for a Your move age
past two days; the orange accent (--acc) for links; the tags are sentence case with a tinted fill and no outline, so they do not look like buttons.

The type scale: five sizes (12 tags, 13 who line and age and labels, 15 row title and body, 17 section heading, 22 page title), two weights (400, 600; tags 500), no letter spacing, no
capitals, monospace only for code. `type_scale` puts the stylesheet the pages carry on that scale rule by rule (the side panel and the Runners page keep their own)."""
from __future__ import annotations

import html as H
import re

from stackshot.web import i18n as _i18n     # the state words come from the string table (state.*), in the person's language

# ----------------------------------------------------------------------------- the state words
YOUR_MOVE, AGENT, WAITING, DONE, DROPPED, SUPERSEDED, CLOSED = "you", "agent", "wait", "done", "dropped", "superseded", "closed"
RELEASE = "release"     # an agent's item whose pull request is in the release script's queue (ui/releasing.py): it leaves On agent for Queued for release
NEW = "new"            # the edge of a close on the Closed page's New section: green, whatever its outcome
EDGES = (YOUR_MOVE, AGENT, RELEASE, WAITING, NEW)      # the kinds whose color a card's left edge takes: orange Your move, blue On agent, purple Queued for release, grey Waiting, green New on Closed
_KINDS = (YOUR_MOVE, AGENT, RELEASE, WAITING, DONE, DROPPED, SUPERSEDED, CLOSED)
WORDS = {k: _i18n.EN[f"state.{k}"] for k in _KINDS}      # the English state words; word() says them in the request's language (string table keys state.<kind>)
TITLES = {k: WORDS[k] for k in (YOUR_MOVE, AGENT, RELEASE, WAITING)}        # the home page's section headings and count cards (the board's own count words); title() says them in the request's language
_OF_LIST = {"your-move": YOUR_MOVE, "agents": AGENT, "waiting": WAITING}              # home.py's list names → a state kind
_OF_OUTCOME = {"done": DONE, "dropped": DROPPED, "superseded": SUPERSEDED}            # a close's outcome → a state kind (anything else is a plain "Closed")


def kind_of_list(which: str) -> str:
    """The state kind of one of home.py's three lists ("your-move", "agents", "waiting")."""
    return _OF_LIST[which]


def kind_of_outcome(oc: str) -> str:
    """The state kind of a close's outcome: done, dropped or superseded; an item closed with no outcome recorded is "closed"."""
    return _OF_OUTCOME.get(oc, CLOSED)


def word(kind: str) -> str:
    """The state word of a kind, as every page says it (in the request's language)."""
    return _i18n.t(f"state.{kind}")


def title(kind: str) -> str:
    """The heading and count-card word of one of the four lists (the state word of its kind, in the request's language)."""
    return _i18n.t(f"state.{kind}")


def tag(kind: str) -> str:
    """The state tag: a small tinted label with the word in it. Never a link or a button; the word carries the meaning, the color only helps."""
    return f'<span class="tag t-{kind}">{H.escape(word(kind))}</span>'


def esc(x) -> str:
    return H.escape(str(x), quote=True)


# ----------------------------------------------------------------------------- the row
def row(*, tag_html: str = "", href: str, rid: str, title: str, age_html: str = "", who_html: str = "", detail_html: str = "", actions_html: str = "",
        li_id: str = "", li_class: str = "", data: str = "", title_attr: str = "", new_tab: bool = True, title_html: str = "", project_html: str = "", edge: str = "", act_html: str = "") -> str:
    """One item as the row every list draws, as an `<li>` for a `<ul class="ir-rows">`.

    `project_html` (home and Closed: the project's name as a link to its page, then the item's owner; a project page: the owner alone; already escaped) is drawn as a small quiet line above the title (`.ir-proj`); `edge` is the state kind (EDGES) whose color the card's left edge takes, empty for the plain edge.
    Line one: the state tag (only where the list mixes states), `#id` and the title in one link (the id in the title's color and size, weight 400), the age at the right. The title
    wraps; the page never cuts it. The id sits outside `.hgoal` (the title's own span), which the page script reads when it names a row.
    Then, each only when it has something to say: the who line (`.ir-who`), the activity line (`.ir-actl`: On agent rows, the pill and what happened last; `act_html`, already escaped), the detail behind its guide line (`.ir-det`), the actions at the text's left edge (`.ir-act`).
    `title_html` (Search: the typed words marked, already escaped) stands for the escaped `title`; `new_tab=False` (Search) keeps the title's link in the page's own tab. `tag_html`, `age_html`, `who_html`, `detail_html` and `actions_html` are HTML the caller has already escaped; `rid` and `title` are plain text."""
    link = (f'<a class="ir-link" href="{esc(href)}"{' target="_blank" rel="noopener"' if new_tab else ""}{f" title={chr(34)}{esc(title_attr)}{chr(34)}" if title_attr else ""}>'
            f'<span class="ir-id">{esc(rid)}</span> <span class="hgoal">{title_html or esc(title)}</span></a>')
    return (f'<li class="irow{" " + li_class if li_class else ""}"{f" id={chr(34)}{esc(li_id)}{chr(34)}" if li_id else ""}{" " + data if data else ""}{f" data-st={chr(34)}{esc(edge)}{chr(34)}" if edge in EDGES else ""}>'
            + (f'<div class="ir-proj">{project_html}</div>' if project_html else "")
            + f'<div class="ir-top"><span class="ir-title">{tag_html + " " if tag_html else ""}{link}</span>{age_html}</div>'
            + (f'<div class="ir-who">{who_html}</div>' if who_html else "")
            + (f'<div class="ir-actl">{act_html}</div>' if act_html else "")
            + (f'<div class="ir-det">{detail_html}</div>' if detail_html else "")
            + (f'<div class="ir-act">{actions_html}</div>' if actions_html else "") + '</li>')


def project_line(href: str, name: str) -> str:
    """The project's name as a link to the project's page: the inner html of a row's `.ir-proj` line."""
    return f'<a class="pjl" href="{esc(href)}">{esc(name)}</a>'


def rows(lis: list[str], cls: str = "") -> str:
    """The rows of one list as a column of cards."""
    return f'<ul class="ir-rows{" " + cls if cls else ""}">{"".join(lis)}</ul>'


# ----------------------------------------------------------------------------- the stylesheet
# Colors: one meaning each. --t-you is the board's one orange (--orange, defined with the page tokens in ui/render.py, #ad4608 light and #f0a06a dark) and --t-you-bg a 12% tint of it over the card; neither repeats a hex. The pairs below are checked for WCAG 1.4.3 (4.5:1 for small text) by tests/ui_kit_scenario.py, which reads this very string.
_LIGHT = ("--t-you:var(--orange);--t-you-bg:color-mix(in srgb,var(--orange) 12%,var(--card));--t-agent:#1f5bc4;--t-agent-bg:#e6eefc;--t-wait:#5f5e5a;--t-wait-bg:#eeede9;--t-release:#6b3fa0;--t-release-bg:#f0e9f9;--t-done:#256e43;--t-done-bg:#e3f2e8;"
          "--t-red:#b42323;--t-red-bg:#f9e1e1;--amber:#8a6100;--red:#b42323")
_DARK = ("--t-agent:#7fb0ff;--t-agent-bg:#1b2a44;--t-wait:#a3a29d;--t-wait-bg:#2a2a2c;--t-release:#c9aef5;--t-release-bg:#2b2140;--t-done:#6fcf97;--t-done-bg:#183326;"
         "--t-red:#ff7b7b;--t-red-bg:#3d1c1c;--amber:#e3b341;--red:#ff7b7b")

CSS = ":root{" + _LIGHT + "}\n@media(prefers-color-scheme:dark){:root:not([data-theme=light]){" + _DARK + "}}:root[data-theme=dark]{" + _DARK + """}
/* the tag: sentence case, tinted fill, no outline, never clickable */
.tag{display:inline-block;flex:none;font-size:12px;line-height:20px;font-weight:500;padding:0 6px;border-radius:4px;white-space:nowrap;vertical-align:1px;margin-right:2px}
.t-you{background:var(--t-you-bg);color:var(--t-you)}.t-agent{background:var(--t-agent-bg);color:var(--t-agent)}.t-release{background:var(--t-release-bg);color:var(--t-release)}
.t-wait,.t-dropped,.t-superseded,.t-closed{background:var(--t-wait-bg);color:var(--t-wait)}.t-done{background:var(--t-done-bg);color:var(--t-done)}.t-p1{background:var(--t-red-bg);color:var(--t-red)}
/* the row: a card (the board's quiet border --line, 10px corners, the card color) with a 3px edge on its left in the list's color (data-st; no data-st is the plain edge); the cards of a list stand in a column with a 12px gap; the row picked by its link (:target) a light orange tint with an orange edge; the title wraps, the age stays on the title line */
ul.ir-rows{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:12px}
li.irow{--st:var(--line);padding:10px 14px 12px;border:1px solid var(--line);border-left:3px solid var(--st);border-radius:10px;background:var(--card);min-width:0;font-size:15px;line-height:22px;scroll-margin-top:calc(var(--hdr,0px) + 12px)}
li.irow[data-st=you]{--st:var(--t-you)}li.irow[data-st=agent]{--st:var(--t-agent)}li.irow[data-st=release]{--st:var(--t-release)}li.irow[data-st=wait]{--st:var(--t-wait)}li.irow[data-st=new]{--st:var(--t-done)}
li.irow:target{background:color-mix(in srgb,var(--acc) 8%,var(--card));box-shadow:inset 3px 0 0 var(--acc)}
@media(max-width:480px){li.irow{padding:10px 12px 12px}}
/* the project line: small and quiet above the title, a link to the project's page */
.ir-proj{font-size:12px;line-height:16px;margin:0 0 2px;overflow-wrap:anywhere;color:var(--mut)}
.ir-proj a.pjl{color:var(--mut)}.ir-proj a.pjl:hover{color:var(--acc)}
.ir-proj a.pjo{color:var(--mut)}.ir-proj a.pjo:hover{color:var(--acc)}
.ir-top{display:flex;align-items:baseline;gap:8px;min-width:0}
.ir-title{flex:1 1 auto;min-width:0;font-weight:600;overflow-wrap:anywhere}
.ir-title a.ir-link{color:var(--fg)}.ir-title a.ir-link:hover{color:var(--acc)}
.ir-id{font-weight:400;font-variant-numeric:tabular-nums}
.ir-age{flex:none;font-size:13px;line-height:18px;color:var(--mut);white-space:nowrap}
.ir-age.amber{color:var(--amber);font-weight:600}.ir-age.red{color:var(--red);font-weight:600}
/* the last activity of an On agent row: the age on the title line and the pill and words under the mover take one of three bands (data-b: ok green under 45 minutes, warn amber to an hour, bad red past it; the page script moves them as time passes) */
.ir-age[data-b=ok],.ir-pill[data-b=ok]{color:var(--t-done)}.ir-age[data-b=warn],.ir-pill[data-b=warn]{color:var(--amber)}.ir-age[data-b=bad],.ir-pill[data-b=bad]{color:var(--red)}
.ir-age[data-b]{font-weight:600;font-variant-numeric:tabular-nums}
.ir-actl{display:flex;flex-wrap:wrap;align-items:center;gap:2px 8px;font-size:13px;line-height:18px;margin-top:2px;min-width:0}
.ir-pill{flex:none;font-size:12px;line-height:16px;font-weight:600;padding:0 7px;border:1px solid currentColor;border-radius:999px;white-space:nowrap}
.ir-lbl,.ir-lwhat{color:var(--mut);min-width:0;overflow-wrap:anywhere}
.istat .ir-actl{flex:1 1 100%;margin-top:0}
.ir-who{font-size:13px;line-height:18px;color:var(--mut);margin-top:2px;overflow-wrap:anywhere}
.ir-who .attn{color:var(--t-you);font-weight:600}.ir-who a{color:var(--mut)}.ir-who a:hover{color:var(--acc)}.ir-who .own{color:var(--t-you);font-weight:600}
.ir-det{margin-top:6px;padding-left:10px;border-left:2px solid var(--line);min-width:0;overflow-wrap:anywhere}
.ir-det>:first-child{margin-top:0}.ir-det .hnote{margin-top:4px}
.ir-act{margin-top:8px;padding-left:12px;min-width:0}
.ir-act form.hanswer{margin:0;padding:0;border:0;background:none}
.ir-act form.hanswer textarea{font-size:15px}
.ir-act form.lclear,.ir-act form.lundo{margin:0}
.ir-act .abtns{margin-top:8px}.ir-act .abtns-opt{margin-top:0}.ir-act .abox{margin-top:8px}
/* the actions of a row whose only action (the answer form) is still hidden take no room */
.ir-act:has(>form[hidden]:only-child){display:none}
.ir-det>.hnext+.hnext{margin-top:2px}.ir-det .hafter .dim{color:var(--mut)}
/* Landed: the same row; Clear sits under the reason, a cleared row dims whole (title, age, who line, reason; the Undo stays bright) until the page is reloaded */
li.irow.lrow{display:block}
li.lrow.lcleared .ir-proj,li.lrow.lcleared .ir-top,li.lrow.lcleared .ir-who,li.lrow.lcleared .ir-det{opacity:.45}
/* the item page: title as home shows it, the goal under it, one header line, the last change in plain words, Next with the earlier steps folded */
main.itempage h1 .hid{font-family:inherit;font-weight:400;color:inherit}
main.itempage .igoal{margin:-2px 0 10px;color:var(--mut)}
main.itempage .istate{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 6px}
main.itempage .ireason{margin:0 0 12px;font-size:13px;line-height:18px;color:var(--mut)}main.itempage .ireason{font-size:15px;line-height:22px;color:var(--fg)}
main.itempage .istat{margin-bottom:6px}.imain>.ireason{order:0}
details.iearlier{margin:8px 0 0}details.iearlier>summary{cursor:pointer;color:var(--mut);font-size:13px;line-height:18px;padding:4px 0}
details.iearlier>ul.inext{margin-top:8px}
@media(pointer:coarse){.b{min-height:44px}.b.ico{width:44px;height:44px;min-height:44px}}
"""

# ----------------------------------------------------------------------------- the type scale
SIZES = (12, 13, 15, 17, 22)                         # tags · who line, age and labels · row title and body · section heading · page title
_SIZE_OF = {10: 12, 11: 12, 12: 12, 13: 13, 14: 15, 15: 15, 16: 15, 18: 17, 20: 22, 22: 22, 24: 22}
_KEEP = re.compile(r"(?:#panel(?:-edge|-open|-scrim)?|\.pc|\.matrix|\.mnote|\.audit|\.phead|\.ptitle|\.mh)(?![\w-])")      # the side panel and its cards: changed on their own
_RULE = re.compile(r"((?:\s*/\*.*?\*/)*)([^{}]+)\{([^{}]*)\}", re.S)       # group 1: the comments in front of the rule, which are not part of its selector
_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"      # i18n: skip  (a font stack)


def _snap(n: float) -> int:
    return _SIZE_OF.get(int(round(n)), min(SIZES, key=lambda s: abs(s - n)))


def _declarations(sel: str, dec: str) -> str:
    """One rule's declarations on the scale: sizes snapped to SIZES (a form field keeps 16px, below which a phone zooms into it), weights to 400/600 (a badge or tag keeps 500), no letter
    spacing, no capitals, no monospace (the `code` rule names its own face, so it keeps it)."""
    field = bool(re.search(r"input|textarea|\.sbox", sel))
    dec = re.sub(r"font:(?:(\d{3}) )?(\d+)px " + re.escape(_MONO), lambda m: f"font-size:{m.group(2)}px;font-weight:{m.group(1) or 400};font-family:inherit", dec)   # the shorthand cannot take `inherit` for its family
    dec = re.sub(r"font-size:([\d.]+)px", lambda m: m.group(0) if field and float(m.group(1)) == 16 else f"font-size:{_snap(float(m.group(1)))}px", dec)
    dec = re.sub(r"font:((?:\d{3} )?)(\d+)px ", lambda m: f"font:{m.group(1)}{_snap(int(m.group(2)))}px ", dec)
    keep500 = bool(re.search(r"badge|tag", sel))
    weight = lambda n: 600 if n >= 600 else 500 if (n == 500 and keep500) else 400
    dec = re.sub(r"font-weight:(\d+)", lambda m: f"font-weight:{weight(int(m.group(1)))}", dec)
    dec = re.sub(r"font:(\d{3}) ", lambda m: f"font:{weight(int(m.group(1)))} ", dec)
    dec = re.sub(r"(?:^|;)\s*letter-spacing:[^;]*", "", dec)
    dec = re.sub(r"(?:^|;)\s*text-transform:uppercase", "", dec)
    dec = re.sub(r"(?:^|;)\s*font-family:" + re.escape(_MONO), "", dec)
    return dec.lstrip(";")


def type_scale(css: str) -> str:
    """The stylesheet `css` on the type scale, rule by rule. A rule whose selector names the side panel or its cards (_KEEP) is left as written; every other rule: font sizes snapped to
    SIZES, weights to two, letter spacing and capitals dropped, monospace dropped. The Runners page and the machine cards draw their own style (not passed through here)."""
    def one(m: re.Match) -> str:
        pre, sel, dec = m.group(1), m.group(2), m.group(3)
        return m.group(0) if _KEEP.search(sel) else f"{pre}{sel}{{{_declarations(sel.strip(), dec)}}}"
    return _RULE.sub(one, css)
