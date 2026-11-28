"""canvas_page.py: what a canvas page is checked for when it is saved, and what it is given when it is served (docs/canvas.md). Pure functions over the page's text: no store, no config, no network.

Saved (service/canvas_write.py calls these):
    item_link(page, board)        the number N of the first `href="<board>/items/N"` in the page's first part, None when there is none. The bare text `board#N` is no link. The first part is the first
                                  FIRST_PART characters once comments, styles and scripts are taken out, so a link written into a script or a comment does not stand for one a reader can click.
    notices(page, board, decision)  what to tell the writer about a decision page (never a refusal): its visible text is longer than one screen, or its first line carries no question or no recommendation.
    visible_lines(page, board)    the page's visible text, one line per block, the item link's own text left out (it is a way to the item, not what the page says).

Served (web/routes/canvas.py calls this on the raw address; the stored bytes never change):
    served(page)                  the page with, when it needs them, a default link color (a page that sets none; readable on white and on black) and the shared click tooltip (a page that uses `data-tip`
                                  and has no script of its own for it), each added once at the end of the head.

A service module: stdlib only."""
from __future__ import annotations

import re
from html.parser import HTMLParser

FIRST_PART = 2000          # characters of the page, comments, styles and scripts out, in which the item link must be
SCREEN_CHARS = 1200        # about one phone screen of text
LINK_COLOR = "#2f72de"     # contrast 4.58 on white and 4.58 on black: readable on a light page and a dark one

_HIDDEN = re.compile(r"<!--.*?(?:-->|\Z)|<(script|style)\b.*?(?:</\1\s*>|\Z)", re.S | re.I)
_BLOCKS = frozenset(("address", "article", "aside", "blockquote", "body", "br", "caption", "dd", "details", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
                     "h5", "h6", "header", "hr", "html", "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "td", "th", "tr", "ul"))
_SKIP = frozenset(("head", "script", "style", "title", "noscript", "template"))


def _link(board: str) -> re.Pattern[str]:
    return re.compile(r"""href\s*=\s*(["'])""" + re.escape(board.rstrip("/")) + r"""/items/(\d+)(?:[?#][^"']*)?\1""", re.I)


def item_link(page: str, board: str) -> int | None:
    """The item number of the first link to an item of `board` in the page's first part, None when there is none."""
    if not board.strip():
        return None
    m = _link(board).search(_HIDDEN.sub("", page)[:FIRST_PART])
    return int(m.group(2)) if m else None


# ---- a link color the page sets
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_A = re.compile(r"(?:^|[\s>+~(,])a(?![\w-])|:link\b|:visited\b", re.I)
_COLOR = re.compile(r"(?:^|[;\s])color\s*:", re.I)


def _css(page: str) -> str:
    """The text of the page's style elements."""
    page = re.sub(r"<!--.*?(?:-->|\Z)", "", page, flags=re.S)
    return "\n".join(m.group(1) for m in re.finditer(r"<style\b[^>]*>(.*?)(?:</style\s*>|\Z)", page, re.S | re.I))


def sets_link_color(page: str) -> bool:
    """True when a style rule of the page names a link (a, a:link, a:visited, :link, :visited, as a whole selector or as part of one) and gives it a color."""
    for sel, body in _RULE.findall(re.sub(r"/\*.*?\*/", "", _css(page), flags=re.S)):
        if _A.search(sel) and _COLOR.search(body):
            return True
    return False


# ---- the visible text
class _Text(HTMLParser):
    def __init__(self, board: str) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.mute = 0                       # inside the item link
        self.link = _link(board) if board.strip() else None

    def flush(self) -> None:
        line = " ".join("".join(self.buf).split())
        if line:
            self.lines.append(line)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        if tag in _BLOCKS:
            self.flush()
        if tag == "a" and self.link is not None and self.link.search(" ".join(f'{k}="{v}"' for k, v in attrs if v is not None)):
            self.mute += 1

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _BLOCKS:
            self.flush()
        if tag == "a" and self.mute:
            self.mute -= 1

    def handle_data(self, data):
        if not self.skip and not self.mute:
            self.buf.append(data)


def visible_lines(page: str, board: str) -> list[str]:
    """The page's visible text, one entry per block."""
    p = _Text(board)
    p.feed(page)
    p.close()
    p.flush()
    return p.lines


def notices(page: str, board: str, decision: bool) -> list[str]:
    """What to tell the writer of a decision page, one sentence each; none for another page and none for a page that fits."""
    if not decision:
        return []
    lines = visible_lines(page, board)
    out = []
    size = sum(len(x) for x in lines)
    if size > SCREEN_CHARS:
        out.append(f"the page is longer than one screen ({size} characters of visible text; a phone shows about {SCREEN_CHARS}): a decision page holds what the choice needs and leaves the rest to a link")
    first = lines[0] if lines else ""
    asks = "?" in first or "？" in first
    recommends = re.search(r"recommend", first, re.I) is not None
    if not asks and not recommends:
        out.append("the first line has no question and no recommendation: open the page with the question the reader decides and what you recommend")
    elif not asks:
        out.append("the first line has no question: open the page with the question the reader decides")
    elif not recommends:
        out.append("the first line has no recommendation: say in it what you recommend")
    return out


# ---- what a page is served with
_STYLE_LINK = f"<style data-canvas-link>:where(a:link,a:visited){{color:{LINK_COLOR}}}</style>"
_STYLE_TIP = ("<style data-canvas-tip>:where([data-tip]){cursor:pointer;text-decoration:underline dotted;text-underline-offset:2px}"
              "[data-canvas-tip-bubble]{position:absolute;z-index:2147483647;box-sizing:border-box;max-width:min(22em,calc(100vw - 16px));padding:8px 10px;border-radius:6px;"
              "background:#222;color:#fff;font:14px/1.4 system-ui,sans-serif;text-align:left;white-space:pre-wrap;box-shadow:0 2px 10px rgba(0,0,0,.4)}</style>")
_SCRIPT_TIP = """<script data-canvas-tip>
(function(){
var tip=null,src=null;
function close(){if(tip){tip.remove();tip=null}if(src){src.removeAttribute('aria-expanded');src=null}}
function open(el){
close();src=el;el.setAttribute('aria-expanded','true');
tip=document.createElement('div');tip.setAttribute('role','tooltip');tip.setAttribute('data-canvas-tip-bubble','');
tip.textContent=el.getAttribute('data-tip');
(document.body||document.documentElement).appendChild(tip);
var r=el.getBoundingClientRect(),w=tip.offsetWidth,sx=window.pageXOffset,sy=window.pageYOffset,vw=document.documentElement.clientWidth;
tip.style.left=Math.max(sx+8,Math.min(r.left+sx,sx+vw-w-8))+'px';
tip.style.top=(r.bottom+sy+6)+'px';
}
function toggle(el){if(el===src){close()}else{open(el)}}
document.addEventListener('click',function(e){
var t=e.target,el=t&&t.closest?t.closest('[data-tip]'):null;
if(el){toggle(el)}else if(!(tip&&t&&tip.contains(t))){close()}
});
document.addEventListener('keydown',function(e){
if(e.key==='Escape'){close();return}
var t=e.target;
if((e.key==='Enter'||e.key===' ')&&t&&t.matches&&t.matches('[data-tip]')){e.preventDefault();toggle(t)}
});
document.addEventListener('DOMContentLoaded',function(){
var all=document.querySelectorAll('[data-tip]');
for(var i=0;i<all.length;i++){if(!all[i].hasAttribute('tabindex')){all[i].setAttribute('tabindex','0')}}
});
})();
</script>"""


class _Facts(HTMLParser):
    """What the page has that decides what it is served with."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.anchor = False
        self.tip = False
        self.own_tip_script = False
        self._script = False

    def handle_starttag(self, tag, attrs):
        names = {k for k, _ in attrs}
        if tag == "a" and "href" in names:
            self.anchor = True
        if "data-tip" in names:
            self.tip = True
        if tag == "script":
            self._script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False

    def handle_data(self, data):
        if self._script and "data-tip" in data:
            self.own_tip_script = True


def _put(page: str, extra: str) -> str:
    """`extra` at the end of the page's head, else after the head's opening tag, the html tag, the doctype, else first."""
    m = re.search(r"</head\s*>", page, re.I)
    if m:
        return page[:m.start()] + extra + page[m.start():]
    for pat in (r"<head\b[^>]*>", r"<html\b[^>]*>", r"<!doctype[^>]*>"):
        m = re.search(pat, page, re.I)
        if m:
            return page[:m.end()] + extra + page[m.end():]
    return extra + page


def served(page: str) -> str:
    """The page as the raw address serves it: itself, with a default link color and the shared tooltip added where the page needs them."""
    facts = _Facts()
    facts.feed(page)
    facts.close()
    extra = ""
    if facts.anchor and not sets_link_color(page):
        extra += _STYLE_LINK
    if facts.tip and not facts.own_tip_script:
        extra += _STYLE_TIP + _SCRIPT_TIP
    return _put(page, extra) if extra else page
