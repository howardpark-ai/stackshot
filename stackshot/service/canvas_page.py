"""canvas_page.py: what a canvas page is checked for when it is saved, and what it is given when it is served (docs/canvas.md). Pure functions over the page's text: no store, no config, no network.

Saved (service/canvas_write.py calls these):
    item_link(page, board)        the number N of the first clickable `<a href="<board>/items/N">` in the page's first part, None when there is none. The bare text `board#N` is no link, nor is a
                                  `data-href`, a `<link>`, or an anchor in the head, a title, a textarea, a noscript or a template, or one that is hidden. The first part is the first FIRST_PART
                                  characters once the head, comments, styles and scripts are taken out, so a link written into a script or a comment does not stand for one a reader can click.
    notices(page, board, decision)  what to tell the writer about a decision page (never a refusal): its visible text is longer than one screen, or its first line carries no question or no recommendation.
    visible_lines(page, board)    the page's visible text, one line per block, the item link's own text left out (it is a way to the item, not what the page says).

Served (web/routes/canvas.py calls this on the raw address; the stored bytes never change):
    served(page)                  the page with, when it needs them, a default link color (a page that sets none; readable on white and on black, and on a dark background the page sets itself) and the shared click tooltip (a page that uses `data-tip`
                                  and has no script of its own for it), each added once at the end of the head.

A service module: stdlib only."""
from __future__ import annotations

import re
from html.parser import HTMLParser

FIRST_PART = 2000          # characters of the page, comments, styles and scripts out, in which the item link must be
SCREEN_CHARS = 1200        # about one phone screen of text
LINK_COLOR = "#2f72de"     # contrast 4.58 on white and 4.58 on black: readable on a light page and on black
LINK_LIGHT = "#8ab4f8"     # for a page that sets a dark background of its own (contrast 8.9 on #121212, 7.9 on #1e1e1e)

_HIDDEN = re.compile(r"<!--.*?(?:-->|\Z)|<(script|style)\b.*?(?:</\1\s*>|\Z)|<head\b[^>]*>.*?</head\s*>", re.S | re.I)
_BLOCKS = frozenset(("address", "article", "aside", "blockquote", "body", "br", "caption", "dd", "details", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
                     "h5", "h6", "header", "hr", "html", "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "td", "th", "tr", "ul"))
_SKIP = frozenset(("head", "script", "style", "title", "noscript", "template"))


def _item_of(href: str, board: str) -> int | None:
    """The item number when `href` is a link to an item of `board` (the board's address, /items/N, a trailing slash, query or fragment allowed), else None."""
    m = re.fullmatch(re.escape(board.rstrip("/")) + r"/items/(\d+)/?(?:[?#].*)?", href.strip(), re.I | re.S)
    return int(m.group(1)) if m else None


_NOT_SHOWN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_INERT = frozenset(("title", "textarea", "noscript", "template", "select", "option"))


class _Anchors(HTMLParser):
    """The item numbers of the board's links a reader can click: an `a` element with an href, in the body, not hidden, not inside a title, textarea, noscript or template."""

    def __init__(self, board: str) -> None:
        super().__init__(convert_charrefs=True)
        self.board = board
        self.found: list[int] = []
        self.inert = 0
        self.head = False
        self.hidden = 0
        self._open: list[bool] = []          # per open `a`: whether it is hidden

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if tag == "head":
            self.head = True
        elif tag == "body":
            self.head = False
        if tag in _INERT:
            self.inert += 1
        if tag == "a":
            hid = "hidden" in d or bool(_NOT_SHOWN.search(d.get("style", "")))
            self._open.append(hid)
            if hid:
                self.hidden += 1
            n = _item_of(d["href"], self.board) if "href" in d else None
            if n is not None and not self.head and not self.inert and not self.hidden:
                self.found.append(n)

    def handle_endtag(self, tag):
        if tag == "head":
            self.head = False
        if tag in _INERT and self.inert:
            self.inert -= 1
        if tag == "a" and self._open and self._open.pop():
            self.hidden -= 1


def item_link(page: str, board: str) -> int | None:
    """The item number of the first clickable link to an item of `board` in the page's first part, None when there is none."""
    if not board.strip():
        return None
    p = _Anchors(board)
    p.feed(_HIDDEN.sub("", page)[:FIRST_PART])
    p.close()
    return p.found[0] if p.found else None


# ---- a link color the page sets
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_A = re.compile(r"(?:^|[\s>+~(,])a(?![\w-])|:link\b|:visited\b", re.I)
_COLOR = re.compile(r"(?:^|[;\s])color\s*:", re.I)


def _css(page: str) -> str:
    """The text of the page's style elements."""
    page = re.sub(r"<!--.*?(?:-->|\Z)", "", page, flags=re.S)
    return "\n".join(m.group(1) for m in re.finditer(r"<style\b[^>]*>(.*?)(?:</style\s*>|\Z)", page, re.S | re.I))


_STATE = re.compile(r":(?:hover|focus|focus-visible|focus-within|active|target)\b", re.I)


def _plain_css(page: str) -> str:
    return re.sub(r"/\*.*?\*/", "", _css(page), flags=re.S)


def sets_link_color(page: str) -> bool:
    """True when a style rule of the page names a link (a, a:link, a:visited, :link, :visited, as a whole selector or as part of one) and gives it a color. A rule for a link in one state only
    (a:hover, a:focus, a:active) is not the page choosing its link color."""
    for sel, body in _RULE.findall(_plain_css(page)):
        if _COLOR.search(body) and any(_A.search(one) and not _STATE.search(one) for one in sel.split(",")):
            return True
    return False


# ---- the background the page sets, and the link color that reads on it
_AT_BLOCK = re.compile(r"@[\w-]+[^{};]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}")
_DARK_MEDIA = re.compile(r"@media[^{};]*prefers-color-scheme\s*:\s*dark[^{};]*\{((?:[^{}]*\{[^{}]*\})*)[^{}]*\}", re.I)
_PAGE_SEL = re.compile(r"^\s*(?:html|body|:root|html\s+body|html\s*>\s*body)\s*$", re.I)
_BG = re.compile(r"(?:^|[;\s])background(?:-color)?\s*:\s*([^;]*)", re.I)
_NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "navy": (0, 0, 128), "darkblue": (0, 0, 139), "midnightblue": (25, 25, 112), "darkslategray": (47, 79, 79), "darkslategrey": (47, 79, 79),
          "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192), "whitesmoke": (245, 245, 245)}
_COLOR_TOKEN = re.compile(r"#[0-9a-f]{8}\b|#[0-9a-f]{6}\b|#[0-9a-f]{3,4}\b|(?:rgba?|hsla?)\([^)]*\)|\b[a-z]+\b", re.I)


def _rgb(token: str) -> tuple[int, int, int] | None:
    t = token.strip().lower()
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) if len(h) >= 6 else None
    m = re.fullmatch(r"(rgba?|hsla?)\(([^)]*)\)", t)
    if m:
        nums = re.findall(r"-?\d+(?:\.\d+)?%?", m.group(2))[:3]
        if len(nums) < 3:
            return None
        v = [float(n.rstrip("%")) for n in nums]
        if m.group(1).startswith("rgb"):
            return tuple(int(max(0, min(255, x * 2.55 if n.endswith("%") else x))) for x, n in zip(v, nums))      # type: ignore[return-value]
        import colorsys
        r, g, b = colorsys.hls_to_rgb((v[0] % 360) / 360, max(0, min(100, v[2])) / 100, max(0, min(100, v[1])) / 100)
        return int(r * 255), int(g * 255), int(b * 255)
    return _NAMED.get(t)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _background(css: str) -> tuple[int, int, int] | None:
    """The last background color the css gives the page (html, body, :root); None when it gives none or one that is not a plain color."""
    got = None
    for sel, body in _RULE.findall(css):
        if not any(_PAGE_SEL.match(one) for one in sel.split(",")):
            continue
        for m in _BG.finditer(body):
            val = m.group(1)
            if re.search(r"url\(|gradient\(|\bvar\(|\binherit\b|\binitial\b|\bunset\b|\btransparent\b", val, re.I):
                got = None
                continue
            for tok in _COLOR_TOKEN.findall(val):
                rgb = _rgb(tok)
                if rgb is not None:
                    got = rgb
                    break
    return got


def _best(bg: tuple[int, int, int] | None) -> str:
    """The default link color that reads best on `bg` (white when the page sets none)."""
    on = bg or (255, 255, 255)
    return max((LINK_COLOR, LINK_LIGHT), key=lambda c: contrast(_rgb(c), on))      # type: ignore[arg-type]


def link_style(page: str, body_style: str = "") -> str:
    """The style element that gives a page its default link color: one color for the page's own background, and for a dark scheme the page sets in a media query, the one for that."""
    css = _plain_css(page) + (f"\nbody{{{body_style}}}" if body_style else "")
    dark = _DARK_MEDIA.findall(css)
    base = _background(_AT_BLOCK.sub("", css))
    out = f":where(a:link,a:visited){{color:{_best(base)}}}"
    if dark:
        bg = _background(dark[-1]) or base
        out += f"@media (prefers-color-scheme:dark){{:where(a:link,a:visited){{color:{_best(bg)}}}}}"
    return f"<style data-canvas-link>{out}</style>"


# ---- the visible text
class _Text(HTMLParser):
    def __init__(self, board: str) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.mute = 0                       # inside the item link
        self.board = board if board.strip() else ""

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
        if tag == "a" and self.board and _item_of(dict(attrs).get("href") or "", self.board) is not None:
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
    """What the page has that decides what it is served with, and where in it the additions go."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.anchor = False
        self.tip = False
        self.own_tip_script = False
        self.body_style = ""
        self.head_end: tuple[int, int] | None = None        # where the head's closing tag begins
        self.after: dict[str, tuple[int, int]] = {}         # where the first head, html and doctype end
        self._script = False

    def _at(self) -> tuple[int, int]:
        return self.getpos()

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype") and "doctype" not in self.after:
            line, col = self._at()
            self.after["doctype"] = (line, col + len(decl) + 3)

    def handle_starttag(self, tag, attrs):
        names = {k for k, _ in attrs}
        if tag == "a" and "href" in names:
            self.anchor = True
        if "data-tip" in names:
            self.tip = True
        if tag in ("html", "body"):
            self.body_style += ";" + dict(attrs).get("style", "")
        if tag in ("head", "html") and tag not in self.after:
            line, col = self._at()
            self.after[tag] = (line, col + len(self.get_starttag_text() or ""))
        if tag == "script":
            self._script = True

    def handle_endtag(self, tag):
        if tag == "head" and self.head_end is None:
            self.head_end = self._at()
        if tag == "script":
            self._script = False

    def handle_data(self, data):
        if self._script and "data-tip" in data:
            self.own_tip_script = True


def _offset(page: str, pos: tuple[int, int]) -> int:
    """The index in `page` of a (line, column) the parser reported."""
    line, col = pos
    at = 0
    for _ in range(line - 1):
        at = page.index("\n", at) + 1
    return at + col


def _put(page: str, extra: str, facts: _Facts) -> str:
    """`extra` at the end of the page's head (the closing tag the parser saw: not one in a comment or a script), else after the head's opening tag, the html tag, the doctype, else first."""
    if facts.head_end is not None:
        at = _offset(page, facts.head_end)
        return page[:at] + extra + page[at:]
    for key in ("head", "html", "doctype"):
        if key in facts.after:
            at = _offset(page, facts.after[key])
            return page[:at] + extra + page[at:]
    return extra + page


def served(page: str) -> str:
    """The page as the raw address serves it: itself, with a default link color and the shared tooltip added where the page needs them."""
    facts = _Facts()
    facts.feed(page)
    facts.close()
    extra = ""
    if facts.anchor and not sets_link_color(page):
        extra += link_style(page, facts.body_style)
    if facts.tip and not facts.own_tip_script:
        extra += _STYLE_TIP + _SCRIPT_TIP
    return _put(page, extra, facts) if extra else page
