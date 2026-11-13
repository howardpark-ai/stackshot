"""Scenario test for the temporary probe page GET /probe/sala-link: ui/render.py Board.probe_target, probe_intents and probe_html, the route in web/routes/ui_api.py. Fixture data, the route through Starlette's
test client, no live store, no network.

Covers:
  * signed out the page is refused as the other pages are (302 to /ui/login with next= the address), signed in it answers 200 with a heading, the instruction line and the six variants A to F;
  * the target: the session view of the first live session, or the template's origin root with no live session, or no link at all (and a line saying so) with no session_view set;
  * `?to=` is used only when it is on the origin of the session_view template; another origin, another scheme, user info, a look-alike host, a control character or a backslash are ignored;
  * A and B are the plain link with and without target=_blank; C, D and E are the intent:// link, exactly formed (host and path of the target, the #Intent part, scheme, the VIEW action and BROWSABLE category in E and no
    package anywhere), and the fallback decodes back to the target; F is two buttons that carry the target;
  * every value is escaped (a `to` with quotes and tags), and the page makes no write.

    tests/run-suite sala_link_probe        -> exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
from urllib.parse import quote, unquote, urlsplit
import html as _html

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="probe-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"; EMAIL = "user@example.org"; SALA = "https://sala.example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('session_view = ""', f'session_view = "{SALA}/#s={{name}}"', 1); assert "sala.example.org" in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
LIVE = "00000000-0000-4000-8000-000000000001"
(T / "fleet/a/sessions.json").write_text(json.dumps({LIVE: {"name": "zeta-main", "machine": "a", "seen": now, "url": "https://example.invalid/z"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
logging.disable(logging.INFO)

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.auth import signin as _signin
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
PATH = "/probe/sala-link"
URL = f"{SALA}/#s=zeta-main"          # the first live session's view, from the template

def hrefs(h):
    """(label letter -> list of (tag, attribute text)) of the page's variants: every <li> of the probe list, keyed by its letter."""
    out = {}
    for li in re.findall(r"<li>(.*?)</li>", h, re.S):
        m = re.match(r"<b>([A-F])\. ", li)
        if m: out[m.group(1)] = li
    return out
def anchors(li): return [(m.group(1), _html.unescape(m.group(2))) for m in re.finditer(r"<a\b([^>]*?)href=\"([^\"]*)\"", li)]
def attrs(li): return re.search(r"<a\b[^>]*>", li).group(0)

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path, follow_redirects=False)

    # ---- signed out: refused as the other pages are
    os.environ["STACKSHOT_AUTH"] = "oauth"
    try:
        r = get(PATH, cookie=None)
        check("signed out: 302 to /ui/login with next= the address, no page", r.status_code == 302 and r.headers.get("location") == "/ui/login?next=" + quote(PATH, safe="") and "intent://" not in r.text, (r.status_code, r.headers.get("location")))
        r = get(PATH + "?to=" + quote(URL, safe=""), cookie=None)
        check("signed out with a to=: still refused", r.status_code == 302 and "intent://" not in r.text, r.status_code)
    finally:
        os.environ["STACKSHOT_AUTH"] = "off"

    # ---- signed in: the page and its six variants
    r = get(PATH)
    h = r.text
    check("signed in: 200, HTML, never cached", r.status_code == 200 and "text/html" in r.headers.get("content-type", "") and r.headers.get("cache-control") == "no-store", (r.status_code, r.headers))
    check("a heading and the one-line instruction in English", "<h1>Opening a session link</h1>" in h
          and "Open this page in the stackshot app on Android and tap each link in turn; tell the agent which opened the sala app." in h)
    v = hrefs(h)
    check("the variants A to F are all there, once each, in order", list(v) == list("ABCDEF"), list(v))
    check("each variant has a label and a line saying what it is", all(re.search(r"<b>[A-F]\. [^<]+</b><br><span class=\"dim\">[^<]+</span>", v[k]) for k in v))
    check("the target is the first live session's view and is shown", f"<code>{_html.escape(URL)}</code>" in h, h[h.find("pjnote"):][:300])

    A, B = anchors(v["A"]), anchors(v["B"])
    check("A: a plain link to the target with target=_blank and rel=noopener (the control)", A == [(A[0][0], URL)] and 'target="_blank"' in A[0][0] + attrs(v["A"]) and 'rel="noopener"' in attrs(v["A"]), (A, attrs(v["A"])))
    check("B: a plain link to the target with no target attribute", B[0][1] == URL and "target" not in attrs(v["B"]), attrs(v["B"]))

    sp = urlsplit(URL)
    fb = quote(URL, safe="")
    INTENT = f"intent://{sp.netloc}/#Intent;scheme=https;S.browser_fallback_url={fb};end"
    INTENT_E = f"intent://{sp.netloc}/#Intent;scheme=https;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;S.browser_fallback_url={fb};end"
    C, D, E = anchors(v["C"])[0][1], anchors(v["D"])[0][1], anchors(v["E"])[0][1]
    check("C: the intent link is exactly formed, with target=_blank", C == INTENT and 'target=_blank' in attrs(v["C"]), (C, INTENT))
    check("D: the same intent link with no target", D == INTENT and "target" not in attrs(v["D"]), (D, attrs(v["D"])))
    check("E: the VIEW action and BROWSABLE category are added, the intent link otherwise the same, no target", E == INTENT_E and "target" not in attrs(v["E"]), (E, INTENT_E))
    check("no variant names a package", "package=" not in h)
    check("the fallback decodes back to the target, in C, D and E", all(unquote(re.search(r"S\.browser_fallback_url=([^;]*);end", x).group(1)) == URL for x in (C, D, E)))
    check("the fallback is fully percent-encoded (no scheme colon, slash, hash or equals left raw)", not re.search(r"[:/#=]", re.search(r"S\.browser_fallback_url=([^;]*);end", C).group(1)))
    check("the #Intent part's keys are not encoded", "#Intent;scheme=https;" in C and "%23Intent" not in C and "%3B" not in C.split("#Intent", 1)[1].split("S.browser", 1)[0])
    btns = re.findall(r'<button type="button" class="b" data-probe="(\w+)" data-url="([^"]*)">([^<]*)</button>', v["F"])
    check("F: two buttons, window.open and location.href, each carrying the target", [(b[0], _html.unescape(b[1]), b[2]) for b in btns] == [("open", URL, "window.open"), ("href", URL, "location.href")], btns)
    check("the script behind F runs window.open(u,'_blank') and sets location.href", "window.open(u,'_blank')" in h and "location.href=u" in h)
    check("the page links nothing to another origin than the target's", all(urlsplit(u).netloc in ("", sp.netloc) for _, u in A + B) and all(urlsplit(x).netloc == sp.netloc for x in (C[len("intent:"):], D[len("intent:"):], E[len("intent:"):])))

    # ---- ?to=
    def page(to): return get(PATH + "?to=" + quote(to, safe="")).text
    TO = f"{SALA}/abc/def?x=1&y=two#s=sess-1"
    ph = page(TO)
    check("a to= on the origin is the target (A and B point at it, in full)", [u for _, u in anchors(hrefs(ph)["A"])] == [TO] and [u for _, u in anchors(hrefs(ph)["B"])] == [TO])
    pc = _html.unescape(re.search(r'<a href="(intent://[^"]*)"', hrefs(ph)["C"]).group(1))
    check("…and the intent link carries its host, path and query, and the whole address, fragment included, as the fallback",
          pc == f"intent://sala.example.org/abc/def?x=1&y=two#Intent;scheme=https;S.browser_fallback_url={quote(TO, safe='')};end" and unquote(pc.split("S.browser_fallback_url=")[1].split(";end")[0]) == TO, pc)
    for what, bad in (("another origin", "https://evil.example.net/abc"), ("a look-alike host", SALA + ".evil.example.net/abc"), ("user info", "https://x@sala.example.org/abc"),
                      ("another scheme", "http://sala.example.org/abc"), ("a javascript: address", "javascript:alert(1)"), ("a protocol-relative address", "//evil.example.net/abc"),
                      ("a relative address", "/abc"), ("a control character", SALA + "/a\tb"), ("a backslash", SALA + "/a\\b"), ("a space", SALA + "/a b"), ("an intent address", "intent://sala.example.org/abc#Intent;end")):
        ph = page(bad)
        check(f"a to= with {what} is ignored (the live session's view is the target)", f"<code>{_html.escape(URL)}</code>" in ph and "evil.example.net" not in ph and "alert(1)" not in ph and "%5C" not in ph, ph[ph.find("pjnote"):][:200])
    check("a to= whose host differs from the origin's only in case is accepted (host names are not case-sensitive)", "<code>https://SALA.example.org/p</code>" in page("https://SALA.example.org/p"))
    check("an empty to= is the live session's view", f"<code>{_html.escape(URL)}</code>" in page(""))

    # ---- escaping
    NASTY = SALA + '/p"><script>alert(1)</script>?q="\'<b>'
    nh = page(NASTY)
    check("a to= with quotes and tags on the origin: no raw script tag or attribute break from it reaches the page", "<script>alert(1)" not in nh and 'p"><script>alert' not in nh and "q=\"'" not in nh)
    nv = hrefs(nh)
    check("…the plain links and buttons hold it escaped, and unescape to the very address", [u for _, u in anchors(nv["A"])] == [NASTY] and [_html.unescape(b) for b in re.findall(r'data-url="([^"]*)"', nv["F"])] == [NASTY, NASTY] and "<script>alert(1)" not in nh, nv["A"])
    ni = _html.unescape(re.search(r'<a href="(intent://[^"]*)"', nv["C"]).group(1))
    check("…and the intent link has the path and query percent-encoded (no quote, angle bracket or space), the fallback the whole address encoded",
          not re.search(r'["<>\s]', ni) and unquote(ni.split("S.browser_fallback_url=")[1].split(";end")[0]) == NASTY, ni)
    body = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", nh, flags=re.S)
    check("…and the visible target line shows it as text", "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "<script>alert(1)" not in body)

    # ---- no live session: the template's origin root
    (T / "fleet/a/sessions.json").write_text(json.dumps({LIVE: {"name": "zeta-main", "machine": "a", "seen": now, "gone": "2020-01-01T00:00:00Z", "url": ""}}))
    nl = get(PATH).text
    check("no live session: the origin root of the template is the target", f"<code>{SALA}/</code>" in nl and [u for _, u in anchors(hrefs(nl)["A"])] == [SALA + "/"], nl[nl.find("pjnote"):][:300])
    check("…and the intent link is host and root path", re.search(r'<a href="intent://sala\.example\.org/#Intent;scheme=https;S\.browser_fallback_url=https%3A%2F%2Fsala\.example\.org%2F;end"', nl))

    # ---- no session_view set: a line, no link
    saved = _cfg.CFG["client"]["session_view"]
    _cfg.CFG["client"]["session_view"] = ""
    try:
        e = get(PATH)
        check("no session_view: 200, a line saying so, no variant and no intent link", e.status_code == 200 and "No session view address is set" in e.text and not hrefs(e.text) and "intent://" not in e.text and "data-probe" not in e.text, e.status_code)
        e = get(PATH + "?to=" + quote(URL, safe=""))
        check("…and a to= opens nothing without a template", "intent://" not in e.text and "data-probe" not in e.text)
    finally:
        _cfg.CFG["client"]["session_view"] = saved

    # ---- the page is read-only
    before = {p: p.read_bytes() for p in T.rglob("*") if p.is_file() and "store" in p.parts}
    get(PATH); get(PATH + "?to=" + quote(TO, safe=""))
    after = {p: p.read_bytes() for p in T.rglob("*") if p.is_file() and "store" in p.parts}
    check("the page writes nothing to the store", before == after)
    check("the probe is marked temporary in the source", "TEMPORARY PROBE (the installed-app session link test)" in pathlib.Path(STACK, "stackshot/web/ui/render.py").read_text(encoding="utf-8")
          and "TEMPORARY PROBE (the installed-app session link test)" in pathlib.Path(STACK, "stackshot/web/routes/ui_api.py").read_text(encoding="utf-8"))

print(f"ok: sala link probe scenario, {len(ran)} checks" if not fails else f"FAILED: sala link probe scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1 if fails else 0)
