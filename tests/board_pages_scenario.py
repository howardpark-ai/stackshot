#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastmcp>=4.0,<5", "httpx", "markdown-it-py>=4,<5"]
#
# [tool.uv]
# exclude-newer = "2026-10-03T04:00:00Z"
# ///
"""Scenario test for the board's pages: the board at the root (ui/render.py, ui/search.py, ui/runners.py), the server routes that serve them and the write routes they post to.
Fixture data, the routes through Starlette's test client, no live store, no network.

Covers:
  * the pages are served at the root: the home, an item page, a project page, Projects, Closed, Search and Runners, behind the sign-in (a visitor not signed in is sent to /ui/login with next= the
    address, and the login keeps that address for the way back);
  * every address a page writes is an absolute path of the board: each href and form action, every script's fetch and every address a script builds, the search box, paging, the item links and
    the logo;
  * the writes: an answer, a watch change, Clear on Closed and Mark seen change the store and 303 back to the form's `back` when it names a page of the board, else the item's page; a `back` that
    is not a page of the board is not followed;
  * the header: every page starts with home's header (the title, the five count cards with home's counts, the search box); off home a list card links to `/#<list>` and Closed to /closed;
  * the home is drawn on request: a change made from a page is on it at the next read, a failed draw is not tried again on every request, /render-stamp never waits for a draw;
  * the answer box: a card per option with its whole text (lettered from three options), one Send greyed until a card or a note, no Options list in the Ask block, the lettered choice kept beside the label.

    tests/run-suite board_pages        -> exit 0 / 1"""
import html as _html, json, logging, os, pathlib, re, shutil, subprocess, sys, time
from urllib.parse import quote, urlsplit

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="boardtest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "user@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A, X, B, Y = ("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444",
              "55555555-5555-4555-8555-555555555555")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((A, "alpha-main"), (X, "alpha-x"), (B, "beta-main"), (Y, "beta-x"))}))
def page_entry(name, agents): return {"title": name.title(), "name": name.title(), "org": "work", "tags": [], "type": "project", "session": agents[0], "status": "active", "board": [], "board_row": False,
                                      "updated": 1, "mirror": "https://example.invalid/" + name, "agents": {a: "builds" for a in agents}}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page_entry("alpha", ["alpha-main", "alpha-x"]),
                                                              "projects/beta": page_entry("beta", ["beta-main", "beta-x"])}}))
for k, v in (("alpha", "ALPHA"), ("beta", "BETA")):
    (T / f"brain/projects/{k}.md").write_text(f"---\ntitle: {k.title()}\n---\n# {k.title()}\n\n## Current state\n\n{v}-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
now0 = time.time()
DESC = "- A thing\n- It lives here\n- Finished when it works"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
def item(i, owner=A, status="open", project="projects/alpha", subject=None, **meta):
    su = now0 - 3600
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[work] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner, "project": project, "next": "the next step", **meta}}))
item(1, needs=["decision"], ask="Ship it now?", options=OPTS)        # an answer box with two buttons
item(2, owner=B, project="projects/beta", subject="[home] needle item")   # a plain open item, found by search
item(3); item(4); item(5, owner=B, project="projects/beta")             # closed by an agent below: they land
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
(T / "fakepush.py").write_text("import sys\nprint('delivered → ' + sys.argv[-2])\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

import config as _cfg, landed as ld
import server, render, search, runners
import ui as ui_pkg
from ui import render as r2, search as s2, runners as n2
from starlette.testclient import TestClient
pub = [0]; server._publish = lambda: pub.__setitem__(0, pub[0] + 1)
server._PUSH = [sys.executable, str(T / "fakepush.py")]
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
NEWD = "- The thing works and is in use"
for i, who in ((3, "alpha-x"), (4, "alpha-x"), (5, "beta-x")):
    r = server.stackshot_complete(f"a{i}", outcome="done", reason="the change is live", description=NEWD, sender=who)
    assert "a" in str(r), r
check("the fixture has closes on the Landed list", len(ld.records()) == 3, ld.records())

# ---- 0. what the pages share with the data modules
check("the search and runners pages use the index and the data of search.py and runners.py, and render.py's address helpers", s2.query is search.query and s2.rebuild is search.rebuild
      and n2.switch_boxes is runners.switch_boxes and n2.conf is runners.conf and r2.icon_href is render.icon_href and r2.font_href is render.font_href)
check("paths: the board's under() adds nothing to an address", ui_pkg.under("/landed") == "/landed" and ui_pkg.under("/") == "/" and ui_pkg.PREFIX == "")

from ui import releasing as _rel2
_rel2._run = lambda argv: ""             # the release queue is the host's systemd units: none are read here (ui_kit_scenario drives the queue)

# ---- 1. the pages
COOKIE =server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
SAME = {"Origin": BOARD}
tok = lambda g: server._answer_token(EMAIL, g)
wtok = lambda g: server._watch_token(EMAIL, g)
PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("landed", "/closed"), ("search", "/search?q=needle"), ("runners", "/runners")]
search.sync(render.Board(str(T / "store")))                        # the search index is built from the fixture before the first query
STATIC = re.compile(r"/(favicon\.svg|fonts/[^?\s]*|manifest\.webmanifest|apple-touch-icon[^?\s]*\.png|icon-[^?\s]*\.png)(\?v=[0-9a-f]+)?")
SHARED = re.compile(r"/(answer-tokens|audit/status|audit/now|receivers\.json)")           # the JSON endpoints the pages call at their root address
def _kind(u):
    """None for an address that is not a path of the board (a fragment, another site, mailto); "bad" for a relative or protocol-relative address; else "static" / "shared" for those root files and endpoints, else "root"."""
    u = _html.unescape(u).strip()
    if not u or u.startswith(("#", "mailto:", "tel:", "javascript:", "data:")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", u): return None
    if u.startswith("//") or not u.startswith("/"): return "bad"   # a relative address would resolve against the page: none is allowed
    p = urlsplit(u).path
    if STATIC.fullmatch(u.split("#")[0]): return "static"
    if SHARED.fullmatch(p): return "shared"
    return "root"
def inside(u):
    """True when an address of a page is fit to follow: a shared static file or endpoint, a fragment, outside the board, or an absolute path of the board (not a relative address)."""
    return _kind(u) in (None, "static", "shared", "root")
def addresses(h):
    """Every address a page writes: href, action, src, form `formaction`, a meta refresh, and in its scripts each quoted string that starts with a slash or is fetched/assigned."""
    out = [m.group(2) for m in re.finditer(r"""\b(?:href|action|formaction|src)=(["'])(.*?)\1""", h, re.S)]
    out += [m.group(1) for m in re.finditer(r"""content=["']\d+;\s*url=([^"']+)""", h)]
    for s in re.findall(r"<script[^>]*>(.*?)</script>", h, re.S):
        out += [m.group(2) for m in re.finditer(r"""(["'`])(/[A-Za-z0-9_.][^"'`\s]*|/)\1""", s)]
        out += [m.group(2) for m in re.finditer(r"""(?:fetch|open|assign|replace)\(\s*(["'`])([^"'`]+)\1""", s)]
        out += [m.group(2) for m in re.finditer(r"""location(?:\.href)?\s*=\s*(["'`])([^"'`]+)\1""", s)]
    return out
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=COOKIE, headers=None):
        c.cookies.clear()
        if cookie: c.cookies.set(server._UI_COOKIE, cookie)
        return c.get(path, headers=headers or {}, follow_redirects=False)
    def post(path, data, headers=SAME, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(server._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    got = {}
    for name, path in PAGES:
        r = get(path); got[name] = r
        check(f"{name} page: 200 HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""), (path, r.status_code, r.text[:200]))
    if shutil.which("node"):                                       # an inline script must parse
        for name, r in got.items():
            for i, js in enumerate(re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", r.text, re.S)):
                p_ = subprocess.run(["node", "-e", "new (require('vm').Script)(require('fs').readFileSync(0,'utf8'))"], input=js, capture_output=True, text=True, timeout=30)
                check(f"{name} page: inline script {i + 1} parses", p_.returncode == 0, p_.stderr[:300])
    for name, want in (("item", "Ship it now?"), ("project", "item 1"), ("landed", "item 3"), ("search", "href=\"/items/a2\""), ("runners", "unners"), ("home", "needle item")):
        check(f"{name} page shows its own content ({want!r})", want in got[name].text, got[name].text[:300])
    hs = re.findall(r'<section id="([^"]+)"', got["home"].text)
    check("home: the sections are Your move, On agent, Queued for release (open, empty here), Waiting; the cards say so",
          [x for x in hs if x in ("your-move", "agents-at-work", "queued-release", "waiting-list")] == ["your-move", "agents-at-work", "queued-release", "waiting-list"]
          and "<h2>On agent <span" in got["home"].text and "Agents at work" not in got["home"].text.split('<section id="by-project">')[0]
          and re.search(r'href="#queued-release"[^>]*><b>0</b><span>Queued<span class="more"> for release</span></span>', got["home"].text) is not None
          and '<details class="fold" data-fold="queued-release" open>' in got["home"].text, hs)
    check("no page says 'at work' (home, item, project, landed, search, runners)", all("at work" not in got[n].text.lower() for n in ("home", "item", "project", "landed", "search", "runners")),
          [n for n in ("home", "item", "project", "landed", "search", "runners") if "at work" in got[n].text.lower()])
    # every address stays at the root
    for name, r in got.items():
        bad = sorted({a for a in addresses(r.text) if not inside(a)})
        n_all = len(addresses(r.text))
        check(f"{name} page: every link, form action and script address is an absolute path of the board ({n_all} found)", n_all > 3 and not bad, bad[:12])
    check("home: the logo, the item links and the side panel point at the root", 'href="/"' in got["home"].text and 'href="/items/a1"' in got["home"].text and 'href="/projects#grp-work"' in got["home"].text,
          re.findall(r'href="[^"]*items/a1"', got["home"].text)[:3])
    check("search page: the box submits to /search and a project hit links at the root", 'action="/search"' in got["search"].text, re.findall(r'<form[^>]*>', got["search"].text)[:3])
    pg = get("/search?q=item").text
    check("search: the project and item hits stay in (a longer result list too)", all(inside(a) for a in addresses(pg)) and "/items/" in pg, [a for a in addresses(pg) if not inside(a)])
    check("item page: the answer form posts to /items/a1/answer, the watch form to /items/a1/watch", 'action="/items/a1/answer"' in got["item"].text and 'action="/items/a1/watch"' in got["item"].text,
          re.findall(r'action="[^"]*"', got["item"].text))
    check("landed page: the Clear forms and the script post to /landed/clear and /landed/unclear", 'action="/landed/clear"' in got["landed"].text and "'/landed/clear'" in got["landed"].text
          and "'/landed/unclear'" in got["landed"].text, re.findall(r"""[ '"]/[a-z0-9/]*landed/[a-z]+""", got["landed"].text)[:8])
    # the Projects page and the paged Completed section of Landed
    rp = get("/projects")
    check("/projects: 200 HTML, the project table with both projects, every address an absolute path of the board", rp.status_code == 200 and "text/html" in rp.headers.get("content-type", "") and "<h1>Projects</h1>" in rp.text and 'table class="pidx"' in rp.text
          and ">Alpha</a>" in rp.text and ">Beta</a>" in rp.text and not [a for a in addresses(rp.text) if not inside(a)], (rp.status_code, [a for a in addresses(rp.text) if not inside(a)][:6]))
    def pcards(t):    # the Projects section's cards: (href, scope, count text), in the order drawn
        sec = re.search(r'<section id="projects-panel">.*?</section>', t, re.S)
        return re.findall(r'<a class="pc rc" href="([^"]+)"[^>]*><b class="rn">([^<]*)</b><span class="rv">([^<]*)</span>', sec.group(0) if sec else "")
    WANT = [("/projects#grp-work", "work", "2 projects"), ("/projects#grp-home", "home", "0 projects"), ("/projects#grp-infra", "infra", "0 projects")]   # [scopes] order in the example config; alpha and beta are both work
    check("the side panel has no Pages nav and no loose Projects link, on every page", all('plinks' not in r.text and 'aria-label="Pages"' not in r.text and '<a href="/projects">Projects</a>' not in r.text
          for r in (rp, *got.values()) if 'id="panel"' in r.text) and 'id="panel"' in rp.text, [n for n, r in got.items() if 'plinks' in r.text])
    check("/projects: the side panel's Projects section has one card per scope, with its project count and a link to the scope's group, and every page's panel does",
          all([(h, s, v) for h, s, v in pcards(r.text)] == WANT for r in (rp, *got.values()) if 'id="panel"' in r.text), [(n, pcards(r.text)) for n, r in got.items() if pcards(r.text) != WANT])
    check("the Projects section is a fold with the title Projects, open, and a grip, keyed like Runners (section id = fold key = swap block id)", all(
        '<section id="projects-panel"><details class="fold" data-fold="projects-panel" open><summary><h2 class="hdr">Projects</h2></summary>' in r.text and 'id="pgrip-projects-panel"' in r.text for r in (rp, *got.values()) if 'id="panel"' in r.text))
    check("/projects: each scope that has projects has its group on the page under the id its card links to (work has one; home and infra have none and no id)",
          re.findall(r'<tr class="scope" id="(grp-[a-z0-9-]+)"><th colspan="2"><span class="sc">([^<]*)</span>', rp.text) == [("grp-work", "work")] and rp.text.count('id="grp-') == 1, re.findall(r'<tr class="scope"[^>]*>', rp.text))
    # the header: every page of the board at the root starts with home's header, the title, the five count cards (home's counts) and the search box
    hdr_cards = lambda t: re.findall(r'<a class="hcard[^"]*" href="([^"]*)"[^>]*><b>(\d+)</b>', (re.search(r'<header class="top">.*?</header>', t, re.S) or [""])[0])
    root_pages = {**got, "Projects": rp}
    home_n = [n for _h, n in hdr_cards(got["home"].text)]
    check("header: home's cards are the four lists' #anchors and /closed, five of them", [h for h, _n in hdr_cards(got["home"].text)] == ["#your-move", "#agents-at-work", "#queued-release", "#waiting-list", "/closed"] and len(home_n) == 5, hdr_cards(got["home"].text))
    for name, r in root_pages.items():
        t = r.text; hd = (re.search(r'<header class="top">.*?</header>', t, re.S) or [""])[0]
        check(f"header: {name} page (the route) starts with the header: title, five count cards, one search box; the counts are home's",
              hd.count('class="site"') == 1 and hd.count('<form class="sbox"') == 1 and t.count('<form class="sbox"') == 1 and [n for _h, n in hdr_cards(t)] == home_n and t.find("<header") < t.find("<h1"), (name, hdr_cards(t)))
        if name != "home":
            check(f"header: {name} page (the route): the cards go to home's lists ('/#your-move' and so on) and /closed, all at the root",
                  [h for h, _n in hdr_cards(t)] == ["/#your-move", "/#agents-at-work", "/#queued-release", "/#waiting-list", "/closed"] and all(inside(h) for h, _n in hdr_cards(t)), hdr_cards(t))
    check("header: a card's target on home is a section of that id (the hash opens it)", all(f'<section id="{x}">' in got["home"].text for x in ("your-move", "agents-at-work", "queued-release", "waiting-list")))
    check("home: no Completed or Task board section", all(x not in got["home"].text for x in ('id="completed"', 'id="by-project"', 'table class="pidx"')))
    check("/projects: not a project's details page (the route comes before /<page key>)", get("/projects/alpha").status_code == 200 and "<h1>Projects</h1>" not in get("/projects/alpha").text)
    for q_ in ("", "?page=1", "?page=2", "?page=99", "?page=abc", "?page=-1"):
        rl_ = get("/closed" + q_)
        check(f"/closed{q_}: 200 with the Last 14 days section of one page, every address an absolute path of the board", rl_.status_code == 200 and 'id="completed"' in rl_.text and "<h1>Closed</h1>" in rl_.text and not [a for a in addresses(rl_.text) if not inside(a)], (rl_.status_code, [a for a in addresses(rl_.text) if not inside(a)][:6]))
        mv_ = get("/landed" + q_)
        check(f"/landed{q_}: the old address is a permanent redirect to /closed{q_}, kept out of every cache", mv_.status_code == 301 and mv_.headers.get("location") == "/closed" + q_ and mv_.headers.get("cache-control") == "no-store", (mv_.status_code, mv_.headers.get("location"), mv_.headers.get("cache-control")))
    check("the pages carry the scripts' addresses and no unfilled placeholder", "@RUNNERS_JSON@" not in got["runners"].text and "{under(" not in "".join(r.text for r in got.values()))
    check("runners page: its refresh reads /runners.json", "'/runners.json'" in got["runners"].text, re.findall(r"runners\.json", got["runners"].text))

    # sign-in: not signed in is sent to the login with the address; the login keeps it
    os.environ["STACKSHOT_AUTH"] = "oauth"
    try:
        for name, path in PAGES:
            r = get(path, cookie=None)
            check(f"{name} page, not signed in: 302 to /ui/login with next= the address", r.status_code == 302 and r.headers.get("location") == "/ui/login?next=" + quote(path, safe=""), (r.status_code, r.headers.get("location")))
        server._ui_client_id = lambda: "test-client"                 # the board's own sign-in service is not reached from a test
        for nxt in ("/items/a1", "/", "/items/a1"):
            rl = get("/ui/login?next=" + quote(nxt, safe=""), cookie=None)
            flow = json.loads(server._ui_unsign(rl.cookies.get(server._UI_FLOW) or "") or "{}")
            check(f"the login started from {nxt} comes back to {nxt} (its flow cookie keeps the address)", rl.status_code == 302 and flow.get("next") == nxt, (rl.status_code, flow))
        for p in ("/projects", "/receivers.json", "/render-stamp", "/answer-tokens?ids=a1", "/runners.json", "/no-such-page"):
            r = get(p, cookie=None)
            check(f"{p}, not signed in: 302 to the login (or 401), never the data", r.status_code in (302, 401, 403), (r.status_code, r.text[:80]))
    finally:
        os.environ["STACKSHOT_AUTH"] = "off"

    # the small routes at the root
    r = get("/render-stamp"); check("/render-stamp: the render time of the home", r.status_code == 200 and isinstance(r.json().get("ts"), int) and r.json()["ts"] > 1.7e9, r.text)
    r = get("/receivers.json"); check("/receivers.json answers (503 unavailable without a status file, else the receivers)", r.status_code in (200, 503), r.status_code)
    r = get("/answer-tokens?ids=a1"); check("/answer-tokens answers", r.status_code == 200 and r.json().get("a1") == tok("a1"), r.text[:120])
    r = get("/no-such-page"); check("/<unknown>: 404, not the static site (a path never serves a file of the root)", r.status_code == 404, (r.status_code, r.text[:80]))
    r = get("/items/a1.html"); check("/items/<id>.html redirects 301 to /items/<id>", r.status_code == 301 and r.headers["location"] == "/items/a1", (r.status_code, r.headers.get("location")))
    check("/index.html is the home", get("/index.html").status_code == 200 and get("/index.html").text == get("/").text and "<h2>On agent <span" in get("/").text)
    r = get("/items/zz9"); check("/items/<unknown>: 404", r.status_code == 404, r.status_code)
    r = get("/projects/alpha/"); check("/<key>/ redirects 301 to /<key>", r.status_code == 301 and r.headers["location"] == "/projects/alpha", (r.status_code, r.headers.get("location")))

    # ---- 2. the writes: back to the page the form was on
    r = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship", "back": "/#a1"})
    check("answer from with a back: 303 to that address", r.status_code == 303 and re.fullmatch(r"/\?sent=decision&item=a1#a1", r.headers["location"]), (r.status_code, r.headers.get("location"), r.text[:120]))
    a1 = rd(1)
    check("…and it changed the same store: the decision left needs and the answer is recorded", "decision" not in (a1["metadata"].get("needs") or []) and a1["metadata"].get("answers"), a1["metadata"])
    item(6, needs=["decision"], ask="Go?", options=OPTS); item(7, needs=["decision"], ask="Go?", options=OPTS); item(8, needs=["decision"], ask="Go?", options=OPTS)
    r = post("/items/a6/answer", {"token": tok("a6"), "choice": "Ship"})
    check("answer from with no back: 303 to the item's page with sent=", r.status_code == 303 and r.headers["location"].startswith("/items/a6?sent="), (r.status_code, r.headers.get("location")))
    r = post("/items/a7/answer", {"token": tok("a7"), "choice": "Ship", "back": "//evil.example.net/items/a7"})
    check("answer with a back that is not a page of the board: not followed; to the item's page", r.status_code == 303 and r.headers["location"].startswith("/items/a7?sent="), (r.status_code, r.headers.get("location")))
    r = post("/items/a2/answer", {"token": tok("a2"), "text": "noted", "back": "/items/a2"}, headers={"Origin": "https://evil.example.net"})
    check("an answer from a foreign origin is refused", r.status_code == 403, r.status_code)
    r = post("/items/a2/answer", {"token": tok("a2"), "text": "noted", "back": "/items/a2"}, cookie=None)
    check("an answer without sign-in is refused", r.status_code == 403, r.status_code)
    check("an answer with a back of //evil or a lookalike of a page is not followed", all(
        server._answer_back(b) is None for b in ("//evil.example.net/x", "/items/a1?x=1", "https://evil.example.net/", "/items/%2e%2e/x", "/../items/a1", "/items//x"))
        and server._answer_back("/") == ("/", "") and server._answer_back("/#a1") == ("/", "#a1") and server._answer_back("/projects/alpha#x") == ("/projects/alpha", "#x")
        and server._answer_back("/items/a1") == ("/items/a1", ""))

    r = post("/items/a2/watch", {"token": wtok("a2"), "mode": "watch"})
    check("watch from the root: 303 to the item's page", r.status_code == 303 and r.headers["location"] == "/items/a2", (r.status_code, r.headers.get("location"), r.text[:100]))
    r = post("/for-you/seen", {"id": "all"})
    check("Mark seen from the root: 303 to the home", r.status_code == 303 and r.headers["location"] == "/#for-you", (r.status_code, r.headers.get("location")))
    keys = [ld.key(x["gid"], x["ts"]) for x in ld.records()]
    check("Landed holds the three closes before the Clear", len(keys) == 3, keys)
    r = post("/landed/clear", {"keys": keys[0]})
    check("Clear on Closed: 303 to /closed, and the same list lost the line", r.status_code == 303 and r.headers["location"] == "/closed" and len(ld.records()) == 2, (r.status_code, r.headers.get("location"), len(ld.records())))
    r = post("/landed/clear", {"keys": ",".join(keys[1:])}, headers={**SAME, "Accept": "application/json"})
    check("Clear all from the page's script (Accept: application/json): {ok, changed}, the list is empty", r.status_code == 200 and r.json() == {"ok": True, "changed": 2} and ld.records() == [], (r.status_code, r.text))
    r = post("/landed/unclear", {"keys": keys[0]})
    check("Undo on Closed: 303 to /closed and the line is back", r.status_code == 303 and r.headers["location"] == "/closed" and len(ld.records()) == 1, (r.status_code, r.headers.get("location"), len(ld.records())))
    r = post("/landed/clear", {"keys": keys[0]}, headers={"Origin": "https://evil.example.net"})
    check("Clear from a foreign origin is refused under too", r.status_code == 403, r.status_code)
    r = post("/runners/switch", {"machine": "box-a", "action": "off"}, cookie=None)
    check("the runners switch refuses a visitor who is not signed in", r.status_code in (400, 403, 404, 503), (r.status_code, r.text[:80]))
    check("a POST to a page that takes none is refused (405), not served the page", post("/landed", {}).status_code in (404, 405))

    # ---- 2b. the answer box: one card per option with its whole text, letters from three options, one Send 
    LONG = {"Alpha": "Alpha's whole text, long enough that a one-line cut would lose its tail: the rows keep 'then X' and the item page keeps 'Then' until the next release ships.",
            "Beta": "Beta's whole text, the recommended one, which is stored second and so lettered B.", "Gamma": "Gamma's whole text."}
    O3 = [{"label": "Alpha", "line": LONG["Alpha"], "recommended": False}, {"label": "Beta", "line": LONG["Beta"], "recommended": True}, {"label": "Gamma", "line": LONG["Gamma"], "recommended": False}]
    item(30, needs=["decision"], ask="Decide: which word · Recommend: B, Beta · Stakes: a label · By: no date", options=O3)
    item(31, needs=["decision"], ask="Decide: ship or wait · Recommend: Ship", options=OPTS)
    item(32, needs=["decision"], ask="Decide: go?")                                   # no stored options: Yes and No
    for i in (33, 34, 35, 36): item(i, needs=["decision"], ask="Decide: which word · Recommend: B, Beta", options=O3)
    pg3, pg2, pgyn = (get(f"/items/a{i}").text for i in (30, 31, 32))
    def box(h):
        m = re.search(r'<form class="ianswer"[^>]*>.*?</form>', h, re.S)
        return m.group(0) if m else ""
    b3, b2, byn = box(pg3), box(pg2), box(pgyn)
    vals = lambda b: re.findall(r'name="choice" value="([^"]*)"', b)
    check("item, three options: a card per option, each with its label and its whole text", b3.count('class="acard"') == 3 and all(_html.escape(LONG[k]) in b3 and f"{k}</span>" in b3 for k in LONG), b3[:600])
    check("item, three options: lettered A, B, C in the stored order (the recommended one, stored second, is B) and the letter rides in the value",
          re.findall(r'<span class="akey">(.)</span>([A-Za-z]+)</span>', b3) == [("A", "Alpha"), ("B", "Beta"), ("C", "Gamma")] and vals(b3) == ["A · Alpha", "B · Beta", "C · Gamma"], vals(b3))
    check("item: the recommended badge is on the recommended card only, and no card has a style of its own for it", b3.count('badge rec') == 1
          and '<span class="akey">B</span>Beta</span> <span class="badge rec">recommended</span>' in b3 and ".acard.rec" not in pg3 and 'class="acard rec"' not in pg3)
    check("item, two options: cards without letters, the value is the bare label", b2.count('class="acard"') == 2 and 'class="akey"' not in b2 and vals(b2) == ["Ship", "Wait"]
          and OPTS[1]["line"] in b2 and OPTS[0]["line"] in b2, b2[:500])
    check("item, no stored options: the Yes and No cards (two, no letters)", byn.count('class="acard"') == 2 and vals(byn) == ["Yes", "No"] and 'class="akey"' not in byn, byn[:400])
    check("item: the Ask block no longer lists the options (no Options list, no heading) while the box is drawn", all('<ol class="iopts">' not in h and '<b class="osub">Options</b>' not in h and "<b>Options</b>" not in h for h in (pg3, pg2, pgyn))
          and "<b>Ask</b>" in pg3)
    check("item: one Send, the only submit button; no per-option button and no \"Choose this\"", all(len(re.findall(r"<button[^>]*type=\"submit\"", b)) == 1 and 'class="b main" name="act" value="answer">Send</button>' in b and "Choose this" not in b
          and not re.search(r'<button[^>]*name="choice"', b) for b in (b3, b2, byn)), re.findall(r"<button[^>]*>", b3))
    check("item: the optional note and the hint for the greyed Send", 'Note (optional)' in b3 and '<span class="ahint" hidden>Pick an option or write a note</span>' in b3 and '<form class="ianswer" data-cards ' in pg3 and 'name="text"' in b3)
    check("item: the page carries the cards' script and style; the selected card gets a filled circle, a 2 px accent border and a tint", "window.ssCards" in pg3 and ".acards .acard:has(input:checked){border:2px solid var(--acc);background:var(--selbg)" in pg3
          and ".adot::after" in pg3)
    check("item, the comment-only box of an item he does not move is unchanged: no cards", '<form class="ianswer" data-cards' not in get("/items/a2").text)
    server._board_home_drop(); hm3 = get("/").text
    hrow = re.search(r'<form class="hanswer" data-cards method="post" action="/items/a30/answer".*?</form>', hm3, re.S)
    check("home: the row's answer form has the same cards, note and one Send (drawn hidden until its token arrives)", bool(hrow) and hrow.group(0).count('class="acard"') == 3 and _html.escape(LONG["Alpha"]) in hrow.group(0) and 'value="B · Beta"' in hrow.group(0)
          and 'disabled>Send</button><span class="ahint" hidden>' in hrow.group(0) and not re.search(r'<button[^>]*name="choice"', hrow.group(0)), (hrow.group(0) if hrow else hm3[:200])[:500])
    hrow2 = re.search(r'<form class="hanswer" data-cards method="post" action="/items/a31/answer".*?</form>', hm3, re.S)
    check("home: a two-option row has no letters", bool(hrow2) and 'class="akey"' not in hrow2.group(0) and hrow2.group(0).count('class="acard"') == 2)
    check("home: the page script re-reads the Send state once the tokens arrive, and the busy check counts a picked card", "ssCards.sync(f)" in hm3 and "form.hanswer input[name=choice]:checked" in hm3)
    # without a box (signed out, no token) the options are still the page's: the Ask block lists them
    nobox = r2.Board(str(T / "store")).item_html("a30")
    check("item without an answer box: the Ask block lists the options (nothing is lost for a viewer with no box)", '<b class="osub">Options</b>' in nobox and _html.escape(LONG["Alpha"]) in nobox and "<form class=\"ianswer\"" not in nobox)
    # the answer: the label is the choice, the letter is kept beside it
    r = post("/items/a33/answer", {"token": tok("a33"), "choice": "B · Beta", "text": "go with it", "back": "/items/a33"})
    a33 = rd(33)["metadata"]; ans33 = (a33.get("answers") or [{}])[-1]
    check("answer with a lettered choice: recorded as the label with its letter, the note and the option's line kept", r.status_code == 303 and r.headers["location"].startswith("/items/a33?sent=decision")
          and ans33.get("choice") == "Beta" and ans33.get("letter") == "B" and ans33.get("text") == "go with it" and ans33.get("choice_line") == LONG["Beta"] and "options" not in a33, ans33)
    check("…and the History line, the saved note and the notice words show \"B · Beta\"", "B · Beta" in get("/items/a33").text and "**B · Beta**" in server._answer_note(ans33) and server._answer_words(ans33).startswith("B · Beta — go with it"), server._answer_words(ans33))
    r = post("/items/a34/answer", {"token": tok("a34"), "choice": "C · Beta"})
    check("a letter that is not the option's place is refused as stale, nothing recorded", r.status_code == 303 and "sent=stale" in r.headers["location"] and not rd(34)["metadata"].get("answers"), (r.headers.get("location"), rd(34)["metadata"].get("answers")))
    r = post("/items/a35/answer", {"token": tok("a35"), "choice": "B · Nowhere"})
    check("a lettered choice that names no option is refused as stale", "sent=stale" in r.headers["location"] and not rd(35)["metadata"].get("answers"), r.headers.get("location"))
    r = post("/items/a36/answer", {"token": tok("a36"), "choice": "Beta"})
    check("a bare label is still taken (a form without the letter), with no letter recorded", "sent=decision" in r.headers["location"] and rd(36)["metadata"]["answers"][-1].get("choice") == "Beta" and "letter" not in rd(36)["metadata"]["answers"][-1], rd(36)["metadata"].get("answers"))
    item(37, needs=["decision"], ask="Decide: ship or wait", options=OPTS)
    r = post("/items/a37/answer", {"token": tok("a37"), "choice": "A · Ship"})
    check("two options carry no letters: \"A · Ship\" is no option", "sent=stale" in r.headers["location"] and not rd(37)["metadata"].get("answers"), r.headers.get("location"))
    item(38, needs=["decision"], ask="Decide: which word", options=O3)
    r = post("/items/a38/answer", {"token": tok("a38"), "text": "none of them, call it Delta", "act": "answer"})
    a38 = rd(38)["metadata"]
    check("a note with no card picked is his answer as a note (no choice, no letter)", "sent=decision" in r.headers["location"] and a38["answers"][-1].get("text") == "none of them, call it Delta"
          and "choice" not in a38["answers"][-1] and "letter" not in a38["answers"][-1], a38.get("answers"))
    # the letters agree with the ask text: a session writes "Recommend: B, Beta" in the STORED order, and the recommended option is stored second
    ask_letter = re.search(r"Recommend: ([A-Z]), (\w+)", rd(30)["metadata"]["ask"])
    card = re.search(r'<span class="akey">([A-Z])</span>(\w+)</span> <span class="badge rec">recommended</span>', b3)
    check("the recommended option is stored second: its card is B, and the ask's \"Recommend: B, Beta\" and the card agree", bool(ask_letter) and bool(card) and ask_letter.groups() == card.groups() == ("B", "Beta"), (ask_letter and ask_letter.groups(), card and card.groups()))
    check("…and the stored order is the drawn order (a recommended option in the middle does not move to A)", re.findall(r'<span class="akey">(.)</span>(\w+)</span>', b3)[0] == ("A", "Alpha"))
    check("two options keep the recommended one first (Ship is stored second)", vals(b2) == ["Ship", "Wait"])
    # a label that itself looks like a lettered choice cannot capture the card for another option
    OT = [{"label": "Q", "line": "Q's text", "recommended": False}, {"label": "X", "line": "X's text", "recommended": True}, {"label": "B · X", "line": "the odd one", "recommended": False}]
    item(39, needs=["decision"], ask="Decide: which · Recommend: B, X", options=OT); item(40, needs=["decision"], ask="Decide: which · Recommend: B, X", options=OT)
    r = post("/items/a39/answer", {"token": tok("a39"), "choice": "B · X"})
    a39 = (rd(39)["metadata"].get("answers") or [{}])[-1]
    check("a posted \"B · X\" is the card for X at place B, not the option whose label is \"B · X\" (place C)", "sent=decision" in r.headers["location"] and a39.get("choice") == "X" and a39.get("letter") == "B", a39)
    r = post("/items/a40/answer", {"token": tok("a40"), "choice": "C · B · X"})
    a40 = (rd(40)["metadata"].get("answers") or [{}])[-1]
    check("…and \"C · B · X\" is the option labelled \"B · X\" at place C", "sent=decision" in r.headers["location"] and a40.get("choice") == "B · X" and a40.get("letter") == "C", a40)
    check("_split_letter in the stored order: a letter past the options, or at another option's place, is left for the stale check", server._split_letter(rd(30), "D · Gamma") == ("D · Gamma", "")
          and server._split_letter(rd(30), "A · Beta") == ("A · Beta", "") and server._split_letter(rd(30), "B · Beta") == ("Beta", "B") and server._split_letter(rd(30), "Beta") == ("Beta", ""))

    # ---- 3. the home is drawn on request; a write from shows at the next read
    h0 = get("/").text
    item(10, subject="[work] fresh item ten")
    h1 = get("/").text
    check("the home keeps its draw for a moment (a file written under it is not on it yet)", "fresh item ten" not in h0 and "fresh item ten" not in h1)
    post("/for-you/seen", {"id": "all"})
    check("…and a write from a page drops it: the next read draws again", "fresh item ten" in get("/").text)
    item(11, subject="[work] fresh item eleven")
    server._board_home_drop()
    check("a drop (what a publish does) makes the next read draw again", "fresh item eleven" in get("/").text)

    # a watch change drops the home too (the publish is stubbed here, so only the handler's own drop can show it)
    get("/"); item(12, subject="[work] fresh item twelve")
    check("watch drop: the kept home does not have the new item yet", "fresh item twelve" not in get("/").text)
    r = post("/items/a2/watch", {"token": wtok("a2"), "mode": "watch"})
    check("a watch change drops the home: the next read draws again", r.status_code == 303 and "fresh item twelve" in get("/").text, r.status_code)
    post("/items/a2/watch", {"token": wtok("a2"), "mode": "default"})

    # a failed draw is not tried again on every request: the last good copy is served, then the back-off ends
    class _Boom:
        calls = 0
        def __init__(self, *a, **k): type(self).calls += 1; raise RuntimeError("draw failed (test)")
    real_board, real_backoff = r2.Board, server._BOARD_FAIL_BACKOFF_S
    try:
        good = get("/").text; server._board_home_drop(); r2.Board = _Boom
        rs = [get("/") for _ in range(5)]
        check("a failed draw: one attempt for five requests, each served the last good copy (200)", _Boom.calls == 1 and all(x.status_code == 200 and x.text == good for x in rs), (_Boom.calls, [x.status_code for x in rs]))
        server._board_home_drop(); get("/")
        check("a drop (a write) during the back-off does not draw again", _Boom.calls == 1, _Boom.calls)
        server._BOARD_HOME["failed"] -= server._BOARD_FAIL_BACKOFF_S + 1; get("/")
        check("...after the back-off one more attempt is made (and a failure starts it again)", _Boom.calls == 2 and get("/").status_code == 200 and _Boom.calls == 2, _Boom.calls)
        server._BOARD_HOME.update(html=None, at=0.0, failed=0.0); _Boom.calls = 0
        rs = [get("/") for _ in range(4)]
        check("a failed draw with no good copy: one attempt, then the plain 503 for each request", _Boom.calls == 1 and all(x.status_code == 503 for x in rs), (_Boom.calls, [x.status_code for x in rs]))
        r2.Board = real_board; server._BOARD_HOME["failed"] = 0.0
        check("...and once the draw works again the page is served", get("/").status_code == 200)
    finally:
        r2.Board = real_board; server._BOARD_FAIL_BACKOFF_S = real_backoff; server._BOARD_HOME["failed"] = 0.0

    # a slow draw that then fails backs off from the moment it failed, not from the moment it started
    class _SlowBoom:
        raised = 0.0
        def __init__(self, *a, **k): time.sleep(0.2); _SlowBoom.raised = time.time(); raise RuntimeError("slow draw failed (test)")
    try:
        r2.Board = _SlowBoom; server._BOARD_HOME.update(html=None, at=0.0, failed=0.0); get("/"); t_after = time.time()
        check("a slow failing draw records the time it failed (between the raise and the return), not the time it started", _SlowBoom.raised > 0 and _SlowBoom.raised <= server._BOARD_HOME["failed"] <= t_after, (_SlowBoom.raised, server._BOARD_HOME["failed"], t_after))
    finally:
        r2.Board = real_board; server._BOARD_HOME.update(html=None, at=0.0, failed=0.0)

    # /render-stamp never waits for a draw and never answers 0; an expired or absent copy is drawn once in the background, so an open page sees the new stamp at its next poll
    import threading
    def settle(limit=10.0):
        dl = time.time() + limit
        while server._BOARD_HOME_LOCK.locked() and time.time() < dl: time.sleep(0.02)
        return not server._BOARD_HOME_LOCK.locked()
    class _Count:
        calls = 0
        def __init__(self, *a, **k): _Count.calls += 1; self.b = real_board(*a, **k)
        def html(self): return self.b.html()
    gate = threading.Event()
    class _Slow(_Count):
        def html(self): gate.wait(10); return self.b.html()
    try:
        # after a restart (nothing held): 503 at once, one background draw, then the stamp
        server._BOARD_HOME.update(html=None, at=0.0, drawn=0, failed=0.0); r2.Board = _Count; _Count.calls = 0
        t0 = time.time(); r = get("/render-stamp")
        check("render-stamp with nothing held: 503 JSON without a ts, uncached, answered at once", r.status_code == 503 and "ts" not in r.json() and r.headers.get("cache-control") == "no-store" and time.time() - t0 < 5, (r.status_code, r.text))
        check("...and it started one background draw, so the next poll has a stamp (no 'unreachable' until someone loads the home)", settle() and _Count.calls == 1, _Count.calls)
        r = get("/render-stamp"); ts0 = r.json().get("ts")
        check("render-stamp after that draw: the page's own stamp, a positive number, and no new draw", r.status_code == 200 and isinstance(ts0, int) and ts0 > 1.7e9 and _Count.calls == 1
              and f'<meta name="stackshot-rendered" content="{ts0}">' in server._BOARD_HOME["html"], (r.text, _Count.calls))
        # a write: the poll answers with the held stamp at once, the next sees the new one
        old = ts0 - 100
        server._BOARD_HOME["html"] = server._BOARD_HOME["html"].replace(f'content="{ts0}"', f'content="{old}"', 1)
        server._board_home_drop(); n1 = _Count.calls
        r = get("/render-stamp")
        check("render-stamp after a write (a drop): the held stamp at once, never 0", r.status_code == 200 and r.json() == {"ts": old}, r.text)
        check("...one background draw ran, and the next poll sees the newer stamp (an open page then fetches the new copy)", settle() and _Count.calls == n1 + 1 and get("/render-stamp").json().get("ts", 0) > old, (_Count.calls, n1))
        # a burst of polls with a slow draw: at most one draw, no waiting
        server._board_home_drop(); n2 = _Count.calls; r2.Board = _Slow; gate.clear()
        t0 = time.time(); rs = [get("/render-stamp") for _ in range(6)]
        check("a burst of polls while a draw runs: all answered at once with the held stamp, and only one draw started", all(x.status_code == 200 and x.json().get("ts", 0) > 0 for x in rs) and time.time() - t0 < 5 and _Count.calls == n2 + 1, (_Count.calls, n2, [x.status_code for x in rs]))
        gate.set()
        check("...the draw ends and the lock is free again", settle())
        # a drop while a draw runs: the copy it finishes is held but not marked fresh, so the next read draws again
        server._board_home_drop(); n4 = _Count.calls; r2.Board = _Slow; gate.clear()
        get("/render-stamp")
        dl = time.time() + 10
        while _Count.calls == n4 and time.time() < dl: time.sleep(0.02)
        server._board_home_drop(); gate.set()
        check("a drop while a draw runs: the draw ends, its copy is held, and it is not marked fresh (at stays 0)", settle() and _Count.calls == n4 + 1 and server._BOARD_HOME["html"] is not None and server._BOARD_HOME["at"] == 0.0, (_Count.calls, n4, server._BOARD_HOME["at"]))
        r2.Board = _Count
        # the lock held elsewhere (a draw by a page request): the poll does not wait for it and starts nothing
        server._board_home_drop(); n3 = _Count.calls; r2.Board = _Count
        server._BOARD_HOME_LOCK.acquire()
        try:
            t0 = time.time(); r = get("/render-stamp")
            check("render-stamp while a draw holds the lock: answered at once, no second draw", r.status_code == 200 and time.time() - t0 < 5 and _Count.calls == n3, (r.status_code, _Count.calls, n3))
        finally:
            server._BOARD_HOME_LOCK.release()
        server._BOARD_HOME["at"] = time.time()
        # a failing draw: polls within the back-off start no more than the one attempt
        server._board_home_drop(); server._BOARD_HOME["failed"] = 0.0; r2.Board = _Boom; _Boom.calls = 0
        for _ in range(5): get("/render-stamp"); settle()
        check("polls after a failed draw: one attempt in all (the back-off holds), the held stamp still answered", _Boom.calls == 1 and get("/render-stamp").status_code == 200, _Boom.calls)
        r2.Board = _Count; server._BOARD_HOME["failed"] = 0.0; server._BOARD_HOME["at"] = time.time()
        # a page with no stamp of its own, and one with no usable time (held and not expired, so nothing redraws it)
        server._BOARD_HOME.update(html="<!doctype html><title>no stamp</title>", drawn=1790000000, at=time.time())
        r = get("/render-stamp")
        check("render-stamp for a page with no stamp of its own: the time it was drawn", r.status_code == 200 and r.json() == {"ts": 1790000000}, r.text)
        server._BOARD_HOME.update(html="<!doctype html><title>no stamp</title>", drawn=0, at=time.time())
        r = get("/render-stamp")
        check("render-stamp with no usable time at all: 503, never ts 0", r.status_code == 503 and "ts" not in r.json(), r.text)
    finally:
        gate.set(); settle(); r2.Board = real_board; server._board_home_drop(); server._BOARD_HOME.update(html=None, drawn=0, failed=0.0)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
