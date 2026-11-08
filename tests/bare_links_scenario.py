"""Scenario test for bare web addresses in item text (ui/render.py) — fixture data, no live store, no network.

An address written without https:// (a host, with or without a path) is a link wherever item text is drawn: a one-line text (linkify,
the ask, the options), a Next line (md_inline) and a description or History entry (md_block), on the item page and the home page. Covers: a bare host, host and
path, host and path and query; trailing punctuation left out of the link; a `code span` left as text; file names, versions, dotted names,
e-mail addresses and git remotes left as text; the allow-list of top-level domains (and "sh" and "so" only with a path); an https:// address
and a [label](url) unchanged and never linked twice; the board's own host opening in the same tab (a bare address, an https:// address, a [label](url), an image) and no other host; quotes, < and & unable to break out of
the markup; and one made-up item through the item page and the home page.

    uv run tests/bare_links_scenario.py        → exit 0 / 1"""
import html as _html, json, os, re, sys, pathlib, subprocess, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="barelinks-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^board_url = "[^"]*"', 'board_url = "https://board.example.org/"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
OPTS = [{"label": "Ship", "line": "Ship it; notes at docs.example.org/ship.", "recommended": True}, {"label": "Wait", "line": "Wait for the release", "recommended": False}]
def item(i, subject, desc, nxt="", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": desc, "status": "open",
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "mover": OWNER, "project": "projects/alpha", "next": nxt, **meta}}))
item(1, "[home] ship the page", "just started", nxt="start")
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
now += 600                                  # the edit ten minutes later is the item's second version: the History shows what changed
item(1, "[home] ship the page", "Notes at docs.example.org/ship and the PR at github.com/owner/repo/pull/7.\n\n- the draft: example.net/draft?v=1&x=2.\n- not a link: render.py and 1.2.3",
     nxt="read github.com/owner/repo/pull/7 then reply\n  - see example.org/docs, and `example.org/code`",
     needs=["decision"], ask="Ship it now? See docs.example.org/ship.", options=OPTS)
git("add", "-A"); git("commit", "-q", "-m", "edit")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web.ui import render as ui_render

EXT = lambda addr, label, rel="noopener noreferrer": f'<a href="https://{addr}" target="_blank" rel="{rel}">{label} ↗</a>'
OLD = lambda url, label: f'<a href="{url}" target="_blank" rel="noopener">{label} ↗</a>'      # an https:// link as the board always wrote it
SAME_TAB = lambda addr, label: f'<a href="https://{addr}">{label}</a>'
TAGS = re.compile(r"</?(?:a|code|p|br|strong|em)\b[^<>]*>")

def browser_host(href):
    """The host a browser goes to: it reads a backslash as a slash, so everything after one is path."""
    from urllib.parse import urlsplit
    return (urlsplit(_html.unescape(href).replace("\\", "/")).hostname or "").lower()
def surfaces(m):
    """The three ways a module turns item text into HTML: a line (linkify), a Next line (md_inline) and a block (md_block, its <p> taken off)."""
    return {"linkify": m.linkify, "md_inline": m.md_inline, "md_block": lambda t: re.sub(r"^<p>(.*)</p>\n$", r"\1", m.md_block(t), flags=re.S)}

for mod_name, m in (("ui/render.py", ui_render),):
    for surf, fn in surfaces(m).items():
        def ck(name, cond, got=None): check(f"{mod_name} {surf}: {name}", cond, got)
        # -- what becomes a link
        out = fn("see example.org now")
        ck("a bare host is a link: https:// added, short label, a new tab with noopener noreferrer", out == "see " + EXT("example.org", "example.org") + " now", out)
        out = fn("open example.org/docs please")
        ck("a host and a path: the href keeps the path, the label is the host", out == "open " + EXT("example.org/docs", "example.org") + " please", out)
        out = fn("PR at github.com/owner/repo/pull/7")
        ck("a GitHub pull request address gets the board's short label", out == "PR at " + EXT("github.com/owner/repo/pull/7", "repo PR #7"), out)
        out = fn("q example.org/search?q=a&b=2#top end")
        ck("host, path and query: the whole address in the href, & escaped", out == "q " + EXT("example.org/search?q=a&amp;b=2#top", "example.org") + " end", out)
        out = fn("at EXAMPLE.org/Path and sub.example.co.kr/x and example.com:8080/y")
        ck("a capital letter, a country subdomain and a port", out == "at " + EXT("EXAMPLE.org/Path", "example.org") + " and " + EXT("sub.example.co.kr/x", "sub.example.co.kr") + " and " + EXT("example.com:8080/y", "example.com:8080"), out)
        # -- trailing punctuation and brackets
        out = fn("(see example.org/docs).")
        ck("a closing bracket and a full stop are not part of the link", out == "(see " + EXT("example.org/docs", "example.org") + ").", out)
        out = fn("a example.org, b example.net; c example.io: d example.dev! e example.ai? f example.org/x.")
        ck("a comma, semicolon, colon, !, ? and a full stop after the host or the path stay prose",
           out == ("a " + EXT("example.org", "example.org") + ", b " + EXT("example.net", "example.net") + "; c " + EXT("example.io", "example.io") + ": d "
                   + EXT("example.dev", "example.dev") + "! e " + EXT("example.ai", "example.ai") + "? f " + EXT("example.org/x", "example.org") + "."), out)
        out = fn('"example.org" and \'example.net\' and [example.io] and example.ai...')
        ck("quotes, square brackets and an ellipsis around an address stay outside it",
           out.count("<a ") == 4 and out.startswith(("&quot;" + EXT("example.org", "example.org") + "&quot; and "))
           and ("&#x27;" + EXT("example.net", "example.net") + "&#x27;" in out or "'" + EXT("example.net", "example.net") + "'" in out) and "[" + EXT("example.io", "example.io") + "]" in out and EXT("example.ai", "example.ai") + "..." in out, out)
        # -- what stays text
        out = fn("`example.org/docs` and `render.py`")
        ck("inside a code span: no link, the span is code", out == "<code>example.org/docs</code> and <code>render.py</code>", out)
        text = "render.py config.toml a.b.c 1.2.3 ui.render 0.9.12-rc.1 0108c0d.b2 install.sh libfoo.so notion.so README.md setup.py 127.0.0.1 file.tar.gz deploy.sh."
        out = fn(text)
        ck("file names, a dotted name, version numbers, a sha-like string, an IP address: plain text", "<a " not in out and "<code>" not in out and out.replace("&#x27;", "'") == text, out)
        out = fn("mail me@example.org or first.co@example.org or git@github.com:owner/repo.git")
        ck("an e-mail address and a git remote are not links", "<a " not in out, out)
        out = fn("ssh://example.org/x and ./example.org/x and my_host.example.org and example.org.bak and config.toml.example")
        ck("after a slash, a dot or a word character, with another label after it: not an address", "<a " not in out, out)
        out = fn("run bun.sh/install, not install.sh, and notion.so/page, not notion.so")
        ck("sh and so are addresses only with a path", out == "run " + EXT("bun.sh/install", "bun.sh") + ", not install.sh, and " + EXT("notion.so/page", "Notion") + ", not notion.so", out)
        out = fn("a.zip b.mov c.rs d.pl e.ts f.cc g.md h.py")
        ck("endings that are file types are not top-level domains here", "<a " not in out, out)
        # -- https:// and markdown links stay as they were
        out = fn("see https://example.org/docs.")
        ck("an https:// address: today's link, not linked twice", out.count("<a ") == 1 and out.endswith(".") and (out == "see " + OLD("https://example.org/docs", "example.org") + "."), out)
        out = fn("see https://github.com/owner/repo/pull/7 and http://example.net/a")
        ck("an https:// address with a host inside its path is one link, an http:// one stays http://",
           out == "see " + OLD("https://github.com/owner/repo/pull/7", "repo PR #7") + " and " + OLD("http://example.net/a", "example.net"), out)
        out = fn("[docs](https://example.org/docs) and example.net")
        ck("a markdown link keeps its label and href, the bare host beside it links", out == OLD("https://example.org/docs", "docs") + " and " + EXT("example.net", "example.net"), out)
        out = fn("[docs](example.org/docs) and [example.org](example.org/docs)")
        ck("a markdown link whose target has no https:// is not turned into a link", "https://example.org" not in out and "<a " not in out, out)
        # -- the board's own host
        out = fn("see board.example.org/items/5 and sub.board.example.org/x and example.org")
        ck("the board's own host (from [instance] board_url) opens in the same tab, no arrow; another host stays a new tab",
           out == "see " + SAME_TAB("board.example.org/items/5", "board.example.org") + " and " + EXT("sub.board.example.org/x", "sub.board.example.org") + " and " + EXT("example.org", "example.org"), out)
        out = fn("Board.Example.org")
        ck("the own host is matched without regard to case", out == SAME_TAB("Board.Example.org", "board.example.org"), out)
        # -- the board's own host in an https:// address and a [label](url): the same tab and no arrow too; every other host as before
        out = fn("see https://board.example.org/items/5. And http://board.example.org/x?a=1&b=2, then https://board.example.org")
        ck("an https:// or http:// address on the board's own host: the same tab, no arrow, trailing punctuation still prose",
           out == "see " + SAME_TAB("board.example.org/items/5", "board.example.org") + ". And " + '<a href="http://board.example.org/x?a=1&amp;b=2">board.example.org</a>' + ", then " + SAME_TAB("board.example.org", "board.example.org"), out)
        out = fn("[the item](https://board.example.org/items/5) and [docs](https://example.org/docs) and [sub](https://sub.board.example.org/x)")
        ck("a [label](url) on the board's own host: the same tab, no arrow; on another host (a subdomain too) a new tab with today's rel",
           out == '<a href="https://board.example.org/items/5">the item</a> and ' + OLD("https://example.org/docs", "docs") + " and " + OLD("https://sub.board.example.org/x", "sub"), out)
        out = fn("[`the item`](https://board.example.org/items/5)")
        ck("a [label](url) whose label holds code keeps the code, the same tab", out == '<a href="https://board.example.org/items/5"><code>the item</code></a>' if surf == "linkify" else "<a href=\"https://board.example.org/items/5\">" in out and "↗" not in out, out)
        out = fn("https://example.org/items/5 and https://board.example.org.evil.example.net/x")
        ck("another host, or the board's host as only the start of a longer one: a new tab with the arrow", out == OLD("https://example.org/items/5", "example.org") + " and " + OLD("https://board.example.org.evil.example.net/x", "board.example.org.evil.example.net"), out)
        if surf != "linkify":
            out = fn("![pic](https://board.example.org/a.png) ![far](https://example.org/a.png)")
            ck("an image on the board's own host is the same plain link, no arrow; another host's keeps it", out == '<a href="https://board.example.org/a.png">pic</a> ' + OLD("https://example.org/a.png", "far"), out)
        # -- a backslash in an address: a browser reads it as a slash, so the board's host after one is not the board's (markdown reads \@ as an escaped @, the address then has a user name and is the board's)
        out = fn("a https://evil.example.net\\@board.example.org/x b [x](https://evil.example.net\\@board.example.org/x) c https://board.example.org/ok")
        tags = re.findall(r"<a [^>]*>", out)
        ck("an address with a backslash before the board's host never opens in the same tab: the host a browser reads decides",
           len(tags) >= 2 and all(('target="_blank"' in t) == (browser_host(re.search(r'href="([^"]*)"', t).group(1)) != "board.example.org") for t in tags), out)
        if surf == "linkify":
            ck("…and through linkify both the bare https:// address and the [x](…) one are new-tab links with the arrow", out.count("↗") == 2 and out.count('target="_blank"') == 2 and out.count("<a ") == 3, out)
            ck("…while the board's own address beside them still opens in the same tab", out.endswith(SAME_TAB("board.example.org/ok", "board.example.org")), out)
        # -- Japanese text: a particle or a word glued to an address neither hides nor joins it
        out = fn("example.orgで確認, アドレスはexample.org です, example.org/docsで, example.org/docs/日本語, (example.org)です.")
        ck("an address followed by a Japanese particle, preceded by a Japanese word, or ended by Japanese text in its path: linked, the Japanese stays outside",
           out == (EXT("example.org", "example.org") + "で確認, アドレスは" + EXT("example.org", "example.org") + " です, " + EXT("example.org/docs", "example.org") + "で, "
                   + EXT("example.org/docs/", "example.org") + "日本語, (" + EXT("example.org", "example.org") + ")です."), out)
        out = fn("render.pyで config.tomlを 1.2.3版 `example.org`で")
        ck("file names and versions with a Japanese particle are still text", "<a " not in out, out)
        # -- code that looks dotted
        out = fn('logger.info("x") self.app self.io self.me Claude.app os.me sys.dev logging.org cls.com this.net foo.io("y") self.io.example.org')
        ck("a call, a name of code (a receiver, a lone app or info) and a host after a receiver are not addresses", "<a " not in out, out)
        out = fn("a example.info/x b example.app/dl c example.info d example.app")
        ck("info and app are addresses only with a path", out == "a " + EXT("example.info/x", "example.info") + " b " + EXT("example.app/dl", "example.app") + " c example.info d example.app", out)
        # -- time: a long line of brackets or half links takes no longer than any other
        slow = 0.0
        for nasty in ("[" * 50000, "[a](" * 12500, "[a](https://x" * 4000, "[a](https://" * 4000, "`" * 50000, "a." * 25000, "a-" * 25000, "example.org/" * 4000, "[\n" * 25000, "](" * 25000):
            t0 = time.time(); fn(nasty); slow = max(slow, time.time() - t0)
        ck(f"fifty kilobytes of brackets, half links, dots and backticks are read in a few seconds at most (slowest {slow:.1f} s)", slow < (1.5 if surf == "linkify" else 4), slow)
        # -- escaping
        for evil in ('example.org/a"onmouseover="x', "example.org/<script>alert(1)</script>", "example.org/?a=1&b=\"2\"'<>", "example.org/a'b&c", "x<example.org>y", "`x` example.org/&lt;b&gt;&amp;"):
            out = fn(evil); rest = TAGS.sub("", out)
            hrefs = re.findall(r'href="([^"]*)"', out)
            ck(f"no markup is injected by {evil!r}", "<" not in rest and ">" not in rest and "onmouseover=" not in re.sub(r"&quot;onmouseover=&quot;", "", rest) and all("<" not in h and ">" not in h and '"' not in h for h in hrefs)
               and all(re.fullmatch(r'<a href="[^"<>]*"(?: target="_blank" rel="noopener noreferrer")?>[^<>]*</a>', a) for a in re.findall(r"<a .*?</a>", out)), out)
        out = fn('example.org/a"onmouseover="x')
        ck("a double quote ends the address; the rest is escaped text", out.startswith(EXT("example.org/a", "example.org")) and out.endswith("&quot;onmouseover=&quot;x"), out)

    # -- one made-up item through the item page and the home page
    B = mod_name; bd = m.Board(f"{tmp}/store")
    page = bd.item_html("a1"); home = bd.html()
    PR = EXT("github.com/owner/repo/pull/7", "repo PR #7")
    check(f"{B} item page: the ask links its bare address", f'Ship it now? See {EXT("docs.example.org/ship", "docs.example.org")}' in page, page[page.find("Ship it now"):][:400])
    check(f"{B} item page: the option's line links it, the full stop after it stays prose", f'Ship it; notes at {EXT("docs.example.org/ship", "docs.example.org")}.' in page, page[page.find("notes at"):][:400])
    check(f"{B} item page: the description links its addresses, not render.py or 1.2.3",
          f'Notes at {EXT("docs.example.org/ship", "docs.example.org")} and the PR at {PR}.' in page and EXT("example.net/draft?v=1&amp;x=2", "example.net") + "." in page
          and "not a link: render.py and 1.2.3" in page, page[page.find("Notes at"):][:600])
    check(f"{B} item page: the Next line links its address and leaves the code span as code", f"read {PR} then reply" in page and f"see {EXT('example.org/docs', 'example.org')}, and <code>example.org/code</code>" in page,
          page[page.find("read "):][:500])
    hist = page[page.find('class="ev '):]
    check(f"{B} item page: the History's next entry links the address, its fold and the description's fold too",
          f"next: read {PR} then reply" in hist and hist.count(PR) >= 3 and "description edited" in hist, hist[:600])
    check(f"{B} home page: the item's row links its Next line's address", PR in home, home[home.find("read "):][:400] if "read " in home else home[:300])
    check(f"{B} pages: file names and versions in the text stay plain, no link is empty", "render.py</a>" not in page and "1.2.3</a>" not in page and 'href=""' not in page and 'href=""' not in home)

if fails: print(f"FAILED: bare links scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: bare links scenario, {len(ran)} checks")
