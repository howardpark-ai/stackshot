"""Scenario test for what a canvas page is checked for and given (stackshot/service/canvas_page.py; docs/canvas.md): pure functions over page text, no store, no network.

Covers: the item link a page must carry in its first part (`href="<board>/items/N"`; the bare text `board#N` does not pass; a link past the first part, in a comment, a style or a script does
not count); whether a page sets a link color; the visible text and its first line; the notices of a decision page (longer than a screen, a first line with no question or no
recommendation); the default link color a page without one is served with (readable on white and on black); the shared click tooltip a page of `data-tip` spans is served with
(and that a page with a script of its own for `data-tip`, or none, is left alone); and that nothing else about the page changes.

    tests/run-suite canvas_page        -> exit 0 / 1"""
import os, re, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK)
from stackshot.service import canvas_page as P

FAILS = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"  :: {str(detail)[:600]}"), flush=True)
    if not ok:
        FAILS.append(name)


B = "https://board.example.org"
N = 42
BARE = "board" + "#" + str(N)                      # the bare text of an item id, built here so no id stands in this file
OTHER = "https://other.example.org/" + "items" + f"/{N}"
LINK = f'<a href="{B}/items/{N}">{BARE}</a>'

# ---- the item link
check("link: a page that opens with the item's link passes and names the item", P.item_link(f"<!doctype html><body>{LINK}<p>x</p>", B) == 42)
check("link: the bare text board#N does not pass", P.item_link(f"<body><p>{BARE} is the item</p></body>", B) is None)
check("link: a link to another board does not pass", P.item_link(f'<body><a href="{OTHER}">x</a>', B) is None)
check("link: a link to something other than an item does not pass", P.item_link(f'<body><a href="{B}/canvas/42">x</a>', B) is None)
check("link: single quotes pass", P.item_link(f"<body><a href='{B}/items/7'>x</a>", B) == 7)
check("link: a trailing slash on the board's address is the same board", P.item_link(f'<body><a href="{B}/items/7">x</a>', B + "/") == 7)
check("link: an anchor or a query after the number passes", P.item_link(f'<body><a href="{B}/items/7#steps">x</a>', B) == 7)
check("link: a longer number is read whole, not cut", P.item_link(f'<body><a href="{B}/items/7x">x</a>', B) is None)
filler = "<p>" + "word " * 1200 + "</p>"
check("link: a link after the first part does not count", P.item_link(f"<body>{filler}{LINK}", B) is None)
check("link: a long head style does not push a link at the top of the body out", P.item_link(f"<style>{'a{margin:0}' * 600}</style><body>{LINK}", B) == 42)
check("link: a link inside a comment does not count", P.item_link(f"<body><!-- {LINK} --><p>x</p>", B) is None)
check("link: a link inside a script does not count", P.item_link(f"<script>var s='{LINK}'</script><body>x", B) is None)
check("link: the first link is the one that counts", P.item_link(f'<body><a href="{B}/items/3">x</a><a href="{B}/items/4">y</a>', B) == 3)
check("link: an empty board address never matches", P.item_link(LINK, "") is None)
check("link: a page with no text at all has none", P.item_link("", B) is None)

# ---- a link color the page sets
check("color: a page with no style sets none", not P.sets_link_color("<body><a href='x'>x</a>"))
check("color: a rule on a sets one", P.sets_link_color("<style>a{color:#c00}</style><a>x</a>"))
check("color: a:link and a:visited rules set one", P.sets_link_color("<style>a:visited { color: red }</style>"))
check("color: a rule on a descendant a sets one", P.sets_link_color("<style>.card a, nav > a:hover{text-decoration:none;color:#fff}</style>"))
check("color: a rule on body does not", not P.sets_link_color("<style>body{color:#222;background:#fff}</style><a>x</a>"))
check("color: a rule on a class that merely starts with a does not", not P.sets_link_color("<style>.a-b, abbr, article{color:red}</style>"))
check("color: an a rule with no color does not", not P.sets_link_color("<style>a{text-decoration:none}</style>"))
check("color: background-color on a is not a link color", not P.sets_link_color("<style>a{background-color:#fff}</style>"))
check("color: a color in a script text is not a rule", not P.sets_link_color("<script>var s='a{color:red}'</script>"))
check("color: an a rule inside a media query sets one", P.sets_link_color("<style>@media (prefers-color-scheme:dark){a{color:#9cf}}</style>"))

# ---- the visible text and its first line
page = f"<!doctype html><head><title>T</title><style>p{{color:red}}</style></head><body>{LINK}<h1>Ship it? Recommend: yes</h1><p>Because it is\n  small.</p><script>var x='no'</script><!-- no --></body>"
check("text: the lines are the page's visible text, one per block, the item link and scripts and styles left out",
      P.visible_lines(page, B) == ["Ship it? Recommend: yes", "Because it is small."], P.visible_lines(page, B))
check("text: inline tags do not break a line", P.visible_lines("<p>one <b>two</b> three</p>", B) == ["one two three"])
check("text: br breaks one", P.visible_lines("one<br>two", B) == ["one", "two"])
check("text: entities are read", P.visible_lines("<p>a &amp; b</p>", B) == ["a & b"])

# ---- the notices of a decision page
good = f"<body>{LINK}<h1>Ship the new layout? I recommend yes.</h1><p>Short.</p>"
check("notice: a page that is not a decision page gets none", P.notices("<body><p>" + "x" * 5000 + "</p>", B, decision=False) == [])
check("notice: a short decision page with a question and a recommendation gets none", P.notices(good, B, decision=True) == [])
long_page = good + "<p>" + "word " * 400 + "</p>"
n = P.notices(long_page, B, decision=True)
check("notice: a decision page longer than one screen is told so", len(n) == 1 and "longer than one screen" in n[0], n)
n = P.notices(f"<body>{LINK}<h1>I recommend we ship the new layout</h1><p>Short.</p>", B, decision=True)
check("notice: a first line with no question is told so", len(n) == 1 and "question" in n[0] and "recommendation" not in n[0], n)
n = P.notices(f"<body>{LINK}<h1>Ship the new layout?</h1><p>Recommend: yes</p>", B, decision=True)
check("notice: a first line with a question and no recommendation is told so", len(n) == 1 and "recommendation" in n[0], n)
n = P.notices(f"<body>{LINK}<h1>Ship the new layout</h1>", B, decision=True)
check("notice: a first line with neither says both in one notice", len(n) == 1 and "question" in n[0] and "recommendation" in n[0], n)
n = P.notices(long_page.replace("Ship the new layout?", "Ship the new layout"), B, decision=True)
check("notice: both findings are two notices", len(n) == 2, n)
check("notice: a decision page with no visible text is told its first line has none", len(P.notices("<body></body>", B, decision=True)) == 1)
check("notice: a recommendation in the second line does not stand for the first", len(P.notices(f"<body>{LINK}<p>Ship it?</p><p>I recommend yes</p>", B, decision=True)) == 1)
check("notice: the length counts visible text, not markup", P.notices(good.replace("<p>Short.</p>", "<p style='" + "x" * 5000 + "'>Short.</p>"), B, decision=True) == [])

# ---- the default link color
SKY = re.compile(r"#[0-9a-f]{6}")


def lum(h):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


check("color: the default is readable on white and on black (contrast of 4.5 or more on both)",
      (1.05 / (lum(P.LINK_COLOR) + 0.05) >= 4.5) and ((lum(P.LINK_COLOR) + 0.05) / 0.05 >= 4.5), P.LINK_COLOR)
plain = "<!doctype html><html><head><meta charset=utf-8><title>t</title></head><body><a href='#x'>x</a></body></html>"
out = P.served(plain)
check("served: a page with no link color gets the default style, once, at the end of its head", P.LINK_COLOR in out and out.count("<style") == 1 and out.index("<style") < out.index("</head>") and out.index("<style") > out.index("<title>"), out[:300])
check("served: the rest of the page is untouched", out.replace(re.search(r"<style[^>]*>.*?</style>", out, re.S).group(0), "", 1) == plain)
check("served: a default is under any rule the page has (zero specificity)", ":where(" in out)
colored = "<head><style>a{color:#c00}</style></head><body><a>x</a></body>"
check("served: a page with its own link color is returned as it is", P.served(colored) == colored)
check("served: a page with no head gets the style at the top, after a doctype", P.served("<!doctype html><p><a href='#'>x</a></p>").startswith("<!doctype html><style"))
check("served: a fragment gets it first", P.served("<p><a href='#'>x</a></p>").startswith("<style"))
check("served: a page with no link at all is returned as it is", P.served("<body><p>hi</p></body>") == "<body><p>hi</p></body>")
check("served: serving twice adds nothing more", P.served(P.served(plain)) == P.served(plain))

# ---- the shared tooltip
tip = "<body><p>An <span data-tip='what it means'>idea</span> here</p></body>"
out = P.served(tip)
check("tip: a page of data-tip spans gets the tooltip script and style, once each", out.count("<script") == 1 and out.count("data-tip") >= 2 and out.count("data-canvas-tip") >= 1, out[:200])
check("tip: the page's own markup is kept whole", "<span data-tip='what it means'>idea</span>" in out)
check("tip: a page without data-tip gets no script", "<script" not in P.served("<body><a>x</a></body>"))
own = "<body><span data-tip='x'>a</span><script>document.querySelectorAll('[data-tip]').forEach(function(e){})</script></body>"
check("tip: a page whose own script handles data-tip is left alone", "data-canvas-tip" not in P.served(own))
check("tip: data-tip in text only (no attribute) gets none", "data-canvas-tip" not in P.served("<body><p>use data-tip=\"x\" on a span</p></body>"))
check("tip: serving twice adds nothing more", P.served(P.served(tip)) == P.served(tip))
js = re.search(r"<script[^>]*>(.*?)</script>", out, re.S).group(1)
check("tip: the script opens on click and never on hover", "click" in js and "mouseover" not in js and "mouseenter" not in js and "pointerenter" not in js and "hover" not in js, js[:300])
check("tip: it closes on Escape and on a click outside", "Escape" in js and re.search(r"closest\(", js) is not None, js[:300])
check("tip: the text is put in as text, never as markup", "innerHTML" not in js and "textContent" in js, js[:300])
check("tip: no hover rule in the style", ":hover" not in re.search(r"<style[^>]*>(.*?)</style>", out, re.S).group(1))
check("tip: the script holds no end-of-script sequence of its own", "</script" not in js.lower())

# ---- weak spots of the item link check, the hover rule, dark backgrounds and the head's end
for what, html in (("a data-href", f'<body><span data-href="{B}/items/5">x</span>'), ("a link element in the head", f'<head><link rel="x" href="{B}/items/5"></head><body>x'),
                   ("a title", f'<head><title><a href="{B}/items/5">x</a></title></head><body>x'), ("a textarea", f'<body><textarea><a href="{B}/items/5">x</a></textarea>'),
                   ("a noscript", f'<body><noscript><a href="{B}/items/5">x</a></noscript>'), ("a template", f'<body><template><a href="{B}/items/5">x</a></template>'),
                   ("a hidden anchor", f'<body><a hidden href="{B}/items/5">x</a>'), ("a display:none anchor", f'<body><a style="display: none" href="{B}/items/5">x</a>'),
                   ("a link in plain text", f'<body><p>href="{B}/items/5"</p>'), ("a link to another host that holds the board's address", f'<body><a href="https://evil.example/{B}/items/5">x</a>'),
                   ("a link to a host that starts like the board", f'<body><a href="{B}.evil.example/items/5">x</a>')):
    check(f"link: {what} does not count", P.item_link(html, B) is None, html)
check("link: an unquoted href counts", P.item_link(f"<body><a href={B}/items/8>x</a>", B) == 8)
check("link: a trailing slash after the number counts", P.item_link(f'<body><a href="{B}/items/8/">x</a>', B) == 8)
check("link: an entity in the href is read", P.item_link(f'<body><a href="{B}/items/8?a=1&amp;b=2">x</a>', B) == 8)
check("link: a hidden anchor does not hide the one after it", P.item_link(f'<body><a hidden href="{B}/items/5">x</a><a href="{B}/items/6">y</a>', B) == 6)
check("link: a long head does not push the body's link out of the first part", P.item_link(f"<head><title>t</title>{'<meta name=a content=b>' * 200}</head><body>{LINK}", B) == 42)
check("link: the item the page names is the first link's, whatever number follows", P.item_link(f'<body><a href="{B}/items/9">x</a><a href="{B}/items/{N}">y</a>', B) == 9)
check("color: a:hover alone is not a link color", not P.sets_link_color("<style>a:hover{color:#c00}</style><a>x</a>"))
check("color: a:focus and a:active are not either", not P.sets_link_color("<style>a:focus, a:active { color: red }</style>"))
check("color: a:hover beside a plain a rule still counts", P.sets_link_color("<style>a, a:hover{color:#c00}</style>"))
hov = "<head><style>a:hover{color:#c00}</style></head><body><a href='#'>x</a></body>"
check("served: a page with only a hover color gets the default", "data-canvas-link" in P.served(hov))
for bg in ("#000", "#121212", "#1e1e1e", "#333", "rgb(30,30,30)", "hsl(0,0%,10%)", "black", "navy"):
    css = P.link_style(f"<style>body{{background:{bg}}}</style><a href=x>x</a>")
    color = re.search(r"color:(#[0-9a-f]{6})", css).group(1)
    check(f"dark: background {bg} gets a link color with contrast 4.5 or more", P.contrast(P._rgb(color), P._background(f"body{{background:{bg}}}")) >= 4.5, (css, color))
check("dark: a page with no background keeps the default", "#2f72de" in P.link_style("<a href=x>x</a>") and P.LINK_LIGHT not in P.link_style("<a href=x>x</a>"))
check("dark: a light background keeps the default", P.LINK_LIGHT not in P.link_style("<style>body{background:#fff}</style>"))
check("dark: the html rule and a shorthand with an image are read", P.LINK_LIGHT in P.link_style("<style>html{background: #111 no-repeat}</style>"))
check("dark: a gradient or a var is no plain color: the default stays", P.LINK_LIGHT not in P.link_style("<style>body{background:linear-gradient(#000,#111)}</style>") and P.LINK_LIGHT not in P.link_style("<style>body{background:var(--bg)}</style>"))
check("dark: the body's style attribute is read", P.LINK_LIGHT in P.served('<body style="background:#111"><a href=x>x</a>'))
check("dark: a dark scheme in a media query gets its own rule, the light one keeps the default",
      P.link_style("<style>body{background:#fff}@media (prefers-color-scheme: dark){body{background:#111}}</style>").count("color:") == 2
      and "#2f72de}@media" in P.link_style("<style>body{background:#fff}@media (prefers-color-scheme: dark){body{background:#111}}</style>"))
check("dark: a media query's background is not the page's own", P.LINK_LIGHT not in P.link_style("<style>@media print{body{background:#000}}</style>"))
check("dark: served puts the light color in a dark page", P.LINK_LIGHT in P.served("<head><style>body{background:#1e1e1e}</style></head><body><a href=x>x</a></body>"))
check("dark: the light color reads on #1e1e1e and #121212", all(P.contrast(P._rgb(P.LINK_LIGHT), P._rgb(c)) >= 4.5 for c in ("#1e1e1e", "#121212", "#000000")))
for tag in ("</head>", "</HEAD>", "</HEAD >", "</Head\n>", "</head foo=bar>"):
    out = P.served(f"<html><head><title>t</title>{tag}<body><a href=x>x</a></body></html>")
    check(f"head: {tag!r} is the end of the head", out.index("data-canvas-link") < out.index(tag) and out.index("data-canvas-link") > out.index("</title>"), out)
out = P.served("<html><head><!-- </head> --><script>var s='</head>'</script><title>t</title></head><body><a href=x>x</a></body></html>")
check("head: a closing tag in a comment or a script is not the end", out.index("data-canvas-link") > out.index("<title>"), out)
out = P.served("<!doctype html>\n<html>\n<head>\n<title>t</title>\n<body><a href=x>x</a>")
check("head: with no closing tag the style goes right after the opening tag, on a page of many lines", "<head><style data-canvas-link>" in out.replace("<head>\n", "<head>", 1) and out.index("data-canvas-link") < out.index("<title>"), out)

print(f"\n{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
