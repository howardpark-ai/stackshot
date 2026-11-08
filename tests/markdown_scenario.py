"""Scenario test for the item page's text as markdown (GitHub's mirrored issues already show the same text as markdown) — fixture data, no live store, no network.

The item page's description, its Next lines and the text of a History entry render as a safe markdown subset through
markdown-it-py with raw HTML off (ui_render.md_block, md_inline). Covers: paragraphs kept whole (not one bullet per sentence), nested
lists, bold and italic, inline code and fenced code, blockquotes; a single newline is a line break; headings, images and tables
stay plain text; raw HTML shown as text (<script> never runs); a link opens only for http and https (javascript:, data: and a
relative path stay as typed); a bare url becomes a labelled link; an item id (board#N, a1) in text links to its item page, and
not inside a code span, a fenced block, a link or its href; a Next line keeps its steps and its copy-button command; a History
comment's text renders the same way; an old description (sentences and "- " lines) reads as a paragraph and a list; the board's
one-line rows and board.md are untouched.

    tests/run-suite markdown        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="mdtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
def item(letter, i, desc, nxt="", subject=None):
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {letter}{i}", "description": desc, "status": "open",
                                                              "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                              "metadata": {"owner": OWNER, "mover": OWNER, "project": "projects/alpha", "next": nxt}}))
SUBJ5 = "[home] the issue-numbered one"
item("g", 5, "Another item.", subject=SUBJ5)
item("a", 1, "x", subject="[home] other")
OLD = ("Move the board to GitHub issues. It keeps the old ids as aliases. Check the mirror first (see a1).\n"
       "- the worker posts the comments\n- the reader polls every 30 s\nDone when the History reads from the issue.")
item("a", 10, OLD, nxt="pick vendor A or B; then tell the keeper\n  - ask about a1")
RICH = ("First paragraph. It has two sentences, and **bold**, *italic* and `code`.\n\n"
        "- top one\n  - nested a\n    - nested deeper\n  - nested b\n- top two\n\n"
        "1. step one\n2. step two\n\n"
        "> quoted line with board#5\n\n"
        "```\nrun board#5 <b>not bold</b>\nsecond line\n```\n\n"
        "Last paragraph.\nSame paragraph, next line.")
item("a", 11, RICH)
SAFE = ("Raw: <script>alert(1)</script> and <img src=x onerror=alert(1)> and <b>b</b>.\n\n"
        "[bad](javascript:alert(1)) [data](data:text/html;base64,PHNjcmlwdD4=) [rel](/items/5) [ok](https://example.invalid/a?b=1&c=2) [also](http://example.invalid/x)\n\n"
        "# not a heading\n\n![an image](https://example.invalid/i.png)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
item("a", 12, SAFE)
LINKS = ("Text board#5 and a1 link; `board#5 and a1` in a code span do not; [board#5](https://example.invalid/board#5) keeps its label; "
         "and a bare https://example.invalid/board#5 gets a short label.\n\n- list item with board#5\n\n> quote with a1\n\n```\nboard#5 a1\n```")
item("a", 13, LINKS)
item("a", 14, "d", nxt="the owner: run `ssh -t host 'x y'` then **confirm** it; see board#5\n  - sub **step** with `code`\n  <script>alert(1)</script> now")
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web.ui import render as ui_render
bd = ui_render.Board(f"{tmp}/store")
def desc_of(gid):
    h = bd.item_html(gid); i = h.find('<div class="desc md">')
    return h[i:h.find("</div>", i) + 6] if i >= 0 else ""
def next_of(gid):
    h = bd.item_html(gid); i = h.find('<ul class="inext"')
    return h[i:h.find("</details>", i)] if i >= 0 else ""      # the checklist list, to the end of its fold
OPEN1 = '<ul class="inext" aria-label="Next steps"><li class="cl-open"><span class="cb" aria-hidden="true"></span><div class="cl-b"><span class="sr">To do: </span><span class="cl-t">'      # the first step of a checklist
IA = lambda gid, subj: f'<a href="/items/{gid[1:] if gid.startswith("g") else gid}" target="_blank" rel="noopener" title="{subj}">'
BN5 = IA("g5", SUBJ5); LBL5 = "#5"        # an issue-numbered item is written, its link reads #5 (ui_render.shown)

# ---- 1. the subset
d11 = desc_of("a11")
check("a paragraph stays whole: two sentences in one <p>, not one bullet each", "<p>First paragraph. It has two sentences, and <strong>bold</strong>, <em>italic</em> and <code>code</code>.</p>" in d11, d11)
check("nested lists, three deep", "<li>top one\n<ul>\n<li>nested a\n<ul>\n<li>nested deeper</li>\n</ul>\n</li>\n<li>nested b</li>\n</ul>\n</li>\n<li>top two</li>" in d11, d11)
check("an ordered list", "<ol>\n<li>step one</li>\n<li>step two</li>\n</ol>" in d11, d11)
check("a blockquote, its id linked", f"<blockquote>\n<p>quoted line with {BN5}#5</a></p>\n</blockquote>" in d11, d11)
check("a fenced code block: verbatim and escaped, the id and the tag not touched", "<pre><code>run board#5 &lt;b&gt;not bold&lt;/b&gt;\nsecond line\n</code></pre>" in d11, d11)
check("a single newline is a line break, the paragraph is one", "<p>Last paragraph.<br>\nSame paragraph, next line.</p>" in d11, d11)
check("no sentence is split into bullets any more", d11.count("<p>") == 3 and "<ul>" in d11 and "It has two sentences" in d11)

# ---- 2. safety
d12 = desc_of("a12")
check("raw HTML is shown as text: <script>, an <img> with a handler and <b> are escaped", "&lt;script&gt;alert(1)&lt;/script&gt;" in d12 and "&lt;img src=x onerror=alert(1)&gt;" in d12 and "&lt;b&gt;b&lt;/b&gt;" in d12
      and "<script" not in d12 and "<img" not in d12 and "<b>" not in d12, d12)
check("a javascript: link is not a link: typed as is", "[bad](javascript:alert(1))" in d12 and "javascript:alert(1)\"" not in d12 and 'href="javascript' not in d12, d12)
check("a data: link and a relative one are not links either", "[data](data:text/html;base64,PHNjcmlwdD4=)" in d12 and "[rel](/items/5)" in d12 and 'href="data:' not in d12 and 'href="/items/5"' not in d12, d12)
check("http and https links open, in a new tab, with the arrow", '<a href="https://example.invalid/a?b=1&amp;c=2" target="_blank" rel="noopener">ok ↗</a>' in d12
      and '<a href="http://example.invalid/x" target="_blank" rel="noopener">also ↗</a>' in d12, d12)
check("a heading and a table stay plain text", "<p># not a heading</p>" in d12 and "<h1" not in d12 and "<table" not in d12 and "| a | b |" in d12, d12)
check("an image is its plain link alone: the alt text and the arrow, no <img>, no leading '!'",
      '<a href="https://example.invalid/i.png" target="_blank" rel="noopener">an image ↗</a>' in d12 and "<img" not in d12 and "!<a" not in d12 and "![" not in d12, d12)
check("an image with a javascript: address stays typed text", ui_render.md_block("![j](javascript:alert(1))") == "<p>![j](javascript:alert(1))</p>\n", ui_render.md_block("![j](javascript:alert(1))"))
check("no tag the subset does not name appears in any of the pages", not re.search(r"<(h[1-6]|table|img|hr|iframe|script|style|form)\b", "".join(desc_of(g) for g in ("a10", "a11", "a12", "a13"))))

# an empty or non-http address leaves the label as plain text: never <a href="">
check("an empty link address: [x]() is the plain text x, no href=\"\"", ui_render.md_block("[x]()") == "<p>x</p>\n", ui_render.md_block("[x]()"))
check("an empty image address: ![a]() is the plain alt text, no link", ui_render.md_block("![a]()") == "<p>a</p>\n", ui_render.md_block("![a]()"))
check("an empty label and address: []() leaves nothing, no link", ui_render.md_block("[]()") == "<p></p>\n", ui_render.md_block("[]()"))
_mix = ui_render.md_block("a [x]() b ![a]() c []() d [ok](https://example.invalid/y) [j](javascript:alert(1)) ![]()")
check("…among others: only the http(s) link is a link, and no empty href anywhere", _mix.count("<a ") == 1 and 'href=""' not in _mix and "<a href=\"https://example.invalid/y\"" in _mix, _mix)

# a bad URL in a comment cannot take the page down: urlparse raises ValueError on "http://[x"
check("link_label: an invalid IPv6 host falls back to the raw url", ui_render.link_label("http://[x") == "http://[x", ui_render.link_label("http://[x"))
try: _bad = (ui_render.md_block("see http://[x here and [a](http://[x) and http://[::1 z"), ui_render.md_inline("see http://[x here"), ui_render.linkify("see http://[x here"))
except Exception as e: _bad = repr(e)
check("an invalid IPv6 address in item text renders and does not raise (block, inline, and the board's own linkify)", isinstance(_bad, tuple) and "http://[x" in _bad[0] and "here" in _bad[1] and "here" in _bad[2], _bad)

# ---- 3. the link passes on the markdown
d13 = desc_of("a13")
check("an item id in text, a list item and a quote links to its item page, its subject as the tooltip",
      f"Text {BN5}#5</a> and {IA('a1', '[home] other')}a1</a> link" in d13 and f"list item with {BN5}#5</a>" in d13 and f"quote with {IA('a1', '[home] other')}a1</a>" in d13, d13)
check("not inside a code span", "<code>board#5 and a1</code>" in d13, d13)
check("not inside a fenced block", "<pre><code>board#5 a1\n</code></pre>" in d13, d13)
check("not inside a link's label or its href", '<a href="https://example.invalid/board#5" target="_blank" rel="noopener">board#5 ↗</a>' in d13, d13)
check("a bare url becomes a labelled link, the id inside its address untouched", '<a href="https://example.invalid/board#5" target="_blank" rel="noopener">example.invalid ↗</a> gets a short label' in d13, d13)
check("the item's own id stays plain on its page", "/items/g5" not in bd.item_html("g5"), None)
check("a bare url ends before its trailing full stop", ui_render.md_block("see https://example.invalid/x.") == '<p>see <a href="https://example.invalid/x" target="_blank" rel="noopener">example.invalid ↗</a>.</p>\n', ui_render.md_block("see https://example.invalid/x."))

# ---- 4. an old description, written as sentences and "- " lines
d10 = desc_of("a10")
check("an old description: a paragraph, a list of its dash lines, then the plain line after them as a paragraph of its own",
      d10 == ('<div class="desc md"><p>Move the board to GitHub issues. It keeps the old ids as aliases. Check the mirror first (see ' + IA("a1", "[home] other") + 'a1</a>).</p>\n'
              '<ul>\n<li>the worker posts the comments</li>\n<li>the reader polls every 30 s</li>\n</ul>\n<p>Done when the History reads from the issue.</p>\n</div>'), d10)
check("a plain line after a list starts a new paragraph, but not inside a fenced block, and an indented line or a quote stays where it is",
      ui_render.md_block("- a\n  cont\nPlain\nPlain2\n- b\n> q\n```\n- k\nraw\n```\nafter") == "<ul>\n<li>a<br>\ncont</li>\n</ul>\n<p>Plain<br>\nPlain2</p>\n<ul>\n<li>b</li>\n</ul>\n<blockquote>\n<p>q</p>\n</blockquote>\n<pre><code>- k\nraw\n</code></pre>\n<p>after</p>\n", ui_render.md_block("- a\n  cont\nPlain\nPlain2\n- b\n> q\n```\n- k\nraw\n```\nafter"))
check("an old description in a bullet-dot form reads as a list", ui_render.md_block("one\n• a\n• b") == "<p>one</p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n", ui_render.md_block("one\n• a\n• b"))
item("a", 15, "[home] item a15"); bd = ui_render.Board(f"{tmp}/store")
check("a description equal to the subject still says none", '<h2>Background</h2></summary><p class="empty">none</p>' in bd.item_html("a15"), bd.item_html("a15")[-900:-500])

# ---- 5. Next: the steps stay one per line, each line inline markdown, the owner's command keeps its copy block
n10 = next_of("a10")
check("Next keeps a line whole (item model, step 3: one line, one mover) with its mover's name added, and its sub-step, the id linked", n10.startswith(OPEN1 + "home-here: pick vendor A or B; then tell the keeper</span><ul><li>ask about " + IA("a1", "[home] other") + "a1</a></li></ul></div></li>"), n10)
n14 = next_of("a14")
check("Next: bold in a step, an id in it linked", "then <strong>confirm</strong> it; see " + BN5 + "#5</a><div class=\"cmd\">" in n14, n14)
check("Next: a step addressed to the owner keeps its command block", '<div class="cmd"><pre><code>ssh -t host &#x27;x y&#x27;</code></pre><button type="button" class="b copy"' in n14 and "the command below" in n14, n14)
check("Next: a sub-step renders inline markdown, a raw tag stays text", "<li>sub <strong>step</strong> with <code>code</code></li>" in n14 and "&lt;script&gt;alert(1)&lt;/script&gt; now" in n14 and "<script>" not in n14, n14)

# ---- 6. History: a comment's text
check("…and the History line is a block that can hold it: div.w, not a span", re.search(r'<li class="ev ev-created"><div class="eh">(?:<b>[^<]+</b> · )?<span class="t">[^<]+</span></div><div class="w"><div class="eb">created as', bd.item_html("a10")) is not None, bd.item_html("a10")[-700:])

# ---- 6b. the brief, flush and bump never need markdown-it (publish.py runs on the system python): import render (the brief) and the board pages' ui/render.py (item text) with it blocked
_probe = ("import sys; sys.modules['markdown_it'] = None; sys.modules['markdown_it.token'] = None; sys.path.insert(0, " + repr(STACK) + "); import render, config; from ui import render as ui_render; "
          "d = str(config.path('paths', 'store')); print(render.render(d, 'brief')); "
          "print(repr(ui_render.md_block('- a\\n- b **c**'))); print(repr(ui_render.md_inline('x **y** https://example.invalid/z')))")
_r = subprocess.run([sys.executable, "-c", _probe], capture_output=True, text=True, env=dict(os.environ))
check("render and ui/render.py import and the brief is made with markdown_it blocked", _r.returncode == 0 and _r.stdout.startswith("Board: "), (_r.returncode, _r.stdout[:200], _r.stderr[-300:]))
check("…and item text then falls back to plain escaped text instead of failing (a list of its lines, a labelled link, no markdown)",
      _r.returncode == 0 and "<ul><li>a</li><li>b **c**</li></ul>" in _r.stdout and "x **y** <a href=" in _r.stdout and "markdown-it-py is not importable" in _r.stderr, (_r.stdout[-400:], _r.stderr[-300:]))

# ---- 7. the other surfaces are untouched
md = bd.markdown(); br = bd.brief(); home = bd.html()
check("board.md and the brief keep the plain text: no HTML tags from the markdown pass, the description split into its bullets as before",
      "<blockquote" not in md and "<pre" not in md and "- the worker posts the comments" in md and "Move the board to GitHub issues." in md, md[md.find("a10"):][:400])
check("the board's page rows are not markdown-rendered", '<div class="desc md">' not in home and "<blockquote" not in home, None)

if fails: print(f"FAILED: markdown scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: markdown scenario, {len(ran)} checks")
