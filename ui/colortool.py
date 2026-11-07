"""ui/colortool.py — stackshot's side of the shared color tool (shared/colortool.js): the settings it is given and the two script blocks the pages carry.

The tool itself is the one shared file shared/colortool.js, which another app pins a verbatim copy of; nothing of it is written here. This module reads that file once, builds stackshot's cfg
(the header of the file describes each field) and emits:
  HEAD  the library inline, once per page, then the cfg and ColorTool.applyStored(cfg): in the head after the theme script, so the stored look is applied before the first paint
  BODY  ColorTool.init(cfg): at the end of the body, which builds the button in the side panel's mount (#panel-colors, ui/render.py _panel_frame) and the panel in the body

What it does for stackshot. The applied look is kept in THIS browser only (localStorage, the one key KEY); the saved combinations are on the server, one list for the owner shared with the fleet tool's web
page (GET /colors/combos, POST /colors/combos and POST /colors/combos/delete, colorcombos.py; read when the panel opens and written only by Save and Delete). Dark theme only.

The 14 fields are the keys of colorcombos.py, one flat map {key: "#rrggbb"}; a key that is not set is the shipped value (or, where a field follows another, what follows it):
  bg page background (--bg) · card cards (--card) · line lines (--line) · fg body text (--fg) · mut muted text (--mut) · link text and links (--orange-text, which --acc, --call and --t-you read) ·
  ibd button outlines (--ibd) · solid solid fills (--orange-solid) · onsolid text on solid fills (--on-solid) · disbg / disfg disabled fill and text (--dis-bg, --dis-fg) ·
  labbg / labfg / labbd small label fill, text and outline (--lab-bg, --lab-fg, --lab-bd).

How. The shipped dark look is the stylesheet's own (ui/render.py): the dark tokens --orange --on-acc --ibd and the five --lab-bg --lab-fg --lab-bd --dis-bg --dis-fg, with the dark rules that draw the small labels and the disabled buttons from them;
SHIPPED below repeats the values for the panel. The tool sets custom properties inline on <html> (an inline declaration outranks every theme block), only while the page is
dark and only for a field that is set: CFG_VARS says which property each field sets, ON_APPLY the ones that need more (the input fill, the properties that read the text orange, the solid fill and its
label, the small labels' three tokens, the disabled pair). Rules in CSS read some of them: html.ct-on re-points the solid fills (the main button, the live dot, the panel-order drop line and the answer dot of the history) to
--orange-solid with the label --on-solid, and html.ct-wl hovers a lighter label's button toward black. Reset removes what the tool set, which leaves the shipped look.

The contrast gate (the default, "refuse") runs in the page on the resolved combination (the server runs none). Body text on the page 11:1 or more and on cards 7:1, muted text on both 4.5:1 and button
outlines on both 3:1 are REFUSED (the change is not applied and the failing pair is named; a stored look that fails is cleared at load); the other pairs are WARNED (applied, with a note and the ratio):
see the header of shared/colortool.js and its LIMITS.
"""
import json as _json
from pathlib import Path as _Path

from ui import under as _under

LIB_FILE = _Path(__file__).resolve().parent.parent / "shared" / "colortool.js"
LIB = LIB_FILE.read_text(encoding="utf-8")
assert LIB.startswith("/* colortool v2 */") and "</" not in LIB and "<!--" not in LIB, "shared/colortool.js is inlined in a script element: no closing tag or comment opener in it"

KEY = "stackshot-color-trial"             # the one localStorage key: the flat map {key: "#rrggbb"} of the fields that are set; an older {"bg", "text", "solid", "tint"} is read ("text" as "link", "tint" ignored)
API = _under("/colors/combos")            # the saved list's address (the delete is API + "/delete")
MOUNT = "#panel-colors"                   # the side panel's mount for the button (ui/render.py _panel_frame)
# the dark theme as shipped (ui/render.py :root[data-theme=dark], ui/kit.py), the 14 values in use with nothing set: the Old orange look with the small labels flipped (orange text on a dark brown fill). The 'old' preset of shared/colortool.js is the same look but for those three label fields (tests/dark_default_scenario.py pins both).
# The last five follow others once one of those is set (the tool reads them as stackshot's own values until then): the three small-label fields follow the text orange, the page and cards; the disabled pair the solid fill, its label and the page.
# The stylesheet carries the shipped value of each as a dark token (--lab-bg --lab-fg --lab-bd --dis-bg --dis-fg), and ON_APPLY sets the whole group inline once a field of it, or one it follows, is set. ifill is the input fill (--ifill), which is not a field.
SHIPPED = {"bg": "#161617", "card": "#1f1f21", "line": "#2c2c2e", "fg": "#ececea", "mut": "#a3a29d", "link": "#f0a06a", "ibd": "#929190", "solid": "#f0a06a", "onsolid": "#1f1f21",
           "labbg": "#3a2619", "labfg": "#f0a06a", "labbd": "#3a2619", "disbg": "#2a2a2c", "disfg": "#a3a29d", "ifill": "#2b2b2f"}
# the three lines of the shared file that name the app (cfg.text): the saved list's sign-in line, the small note at the end of the panel, and the example hex of the "six digits" hint
TEXT = {"signIn": "Sign in to the board to use saved combinations.",
        "note": "Dark theme only. The look you apply is kept in this browser; saved combinations are shared with the fleet tool's web page.",
        "example": SHIPPED["link"]}
# the properties each field sets inline when it is set (Cards and Lines also with a set page background, which they follow)
CFG_VARS = {"bg": ["--bg"], "card": ["--card"], "line": ["--line"], "fg": ["--fg"], "mut": ["--mut"], "link": ["--orange-text"], "ibd": ["--ibd"]}
# what is set besides: the input fill under a set background; what reads the text orange; the solid fill and its label (and the classes that re-point the fills); the small labels' three tokens together, once a label field or one it follows (the text orange, the page, cards) is set;
# the disabled pair together, once either field or one it follows (the solid fill, its label, the page) is set
ON_APPLY = """function(r,s,set,add,t){
if(s.bg)set('--ifill',r.ifill);
if(s.link){['--acc','--call','--t-you'].forEach(function(k){set(k,'var(--orange-text)')});set('--selbg','color-mix(in srgb,var(--orange-text) 8%,var(--card))');set('--t-you-bg','color-mix(in srgb,var(--orange-text) 12%,var(--card))')}
if(s.link||s.solid||s.onsolid){add('ct-on');set('--orange-solid',s.solid?r.solid:'var(--orange)');set('--on-solid',(s.solid||s.onsolid)?r.onsolid:'var(--on-acc)');if(t.lighter(s,r))add('ct-wl')}
if(s.labbg||s.labfg||s.labbd||s.link||s.bg||s.card){set('--lab-bg',r.labbg);set('--lab-fg',r.labfg);set('--lab-bd',r.labbd)}
if(s.disbg||s.disfg||s.solid||s.onsolid||s.bg){set('--dis-bg',r.disbg);set('--dis-fg',r.disfg)}}"""
SOLID_RULES = (".b.main", ".adot", "#panel-drop", "ul.hist li.ev-answer")      # the solid orange fills of the shipped stylesheet, which the CSS below re-points (tests/color_trial_scenario.py checks each is still a fill there)

CSS = """/* the solid fills read --orange-solid while an override is on (the label --on-solid); a lighter label hovers and presses toward black */
html.ct-on .b.main,html.ct-on .adot,html.ct-on #panel-drop{--acc:var(--orange-solid);--on-acc:var(--on-solid)}
html.ct-on ul.hist li.ev-answer::before{--call:var(--orange-solid)}
html.ct-wl .b.main{--fg:#000}
/* the small labels (the orange badges and the "Your move" tag) and the disabled buttons are drawn by the dark rules of the stylesheet (ui/render.py) from --lab-bg --lab-fg --lab-bd and --dis-bg --dis-fg: the tool only sets those five inline */
/* the mount: the last thing in the side panel, outside the sections that move. While the tool has drawn its button (the dark theme) the panel is a flex column that gives up its own bottom padding, so that the mount, a band
   with the button at its left, sits at the very bottom of a short panel and sticks there while a tall one scrolls; the gap before it keeps what the padding kept, the last section clear of the reload and Back to top buttons
   (126px in all, while the panel is pinned) */
#panel-colors-gap,#panel-colors{display:none}
#panel:has(#panel-colors>.ct:not([hidden])){display:flex;flex-direction:column;padding-bottom:0}
#panel:has(#panel-colors>.ct:not([hidden]))>*{flex:none}
#panel:has(#panel-colors>.ct:not([hidden])) #panel-colors{display:block;position:sticky;bottom:0;z-index:2;margin:auto -16px 0;padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:var(--bg);border-top:1px solid var(--line)}
#panel:has(#panel-colors>.ct:not([hidden])) #panel-colors-gap{display:block;height:0}
@media(min-width:800px){body.panel-pin #panel:has(#panel-colors>.ct:not([hidden])) #panel-colors-gap{height:76px}}"""

# the preview strip: the shipped classes, so the buttons and labels are the real ones
# (the preview badge writes its classes as "rec badge", the same .badge.rec rule, so that tests counting the page's own class="badge rec" count only the real ones)
PREVIEW = ('<button type="button" class="b main" tabindex="-1">Send</button><button type="button" class="b main" tabindex="-1" disabled>Send</button>'
           '<button type="button" class="b" tabindex="-1">Cancel</button><button type="button" class="b" tabindex="-1" disabled>Undo</button>'
           '<span class="tag t-you">Your move</span><span class="rec badge">recommended</span><a>A link</a>')


def _js(value) -> str:
    return _json.dumps(value).replace("</", "<\\/")


CFG_JS = ("window.stackshotColors={storageKey:" + _js(KEY) + ",shipped:" + _js(SHIPPED) + ",vars:" + _js(CFG_VARS) + ",css:" + _js(CSS) + ",mount:" + _js(MOUNT)
          + ",api:" + _js(API) + ",preview:" + _js(PREVIEW) + ",text:" + _js(TEXT) + ",onApply:" + ON_APPLY + "};")

HEAD = "<script>" + LIB + "</script><script>" + CFG_JS + "ColorTool.applyStored(window.stackshotColors);</script>"      # appended to render._APP_HEAD: in the head of every page after the theme script, before the first paint
BODY = "<script>ColorTool.init(window.stackshotColors);</script>"                                                      # appended to render._FAB_PAIR: at the end of every page's body
