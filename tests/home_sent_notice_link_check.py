"""The notice after a move from a home row is one link to the item (a manual check like home_send_folds_check.py: it needs the browser, which CI's runner has not; the page script's
text is pinned in home_scenario.py, which CI does run). Starts the server in-process on 127.0.0.1 with a temporary config and fixture data (no live store, no network), signs a
browser in with the board's cookie and loads /?sent=<code>&item=<id> in Chromium: the notice (p.isent) holds one anchor that carries the whole notice text, points at the item page's
address, opens in a new tab (target _blank, rel noopener), is as wide as the notice, and keeps its colors; the notice of a ?sent= with no item, and with an id the script does not accept,
has no anchor and the same text as before.

    tests/run-suite home_sent_notice_link_check     -> exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, sys, tempfile, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="sentlink-"); T = pathlib.Path(tmp)
EMAIL = "oliver@example.org"
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml, _n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert _n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] ", "[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BASE}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BASE}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "secrets"): (T / d).mkdir(parents=True)

now = time.time()
A, B = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "home-alpha", "machine": "a", "seen": now}, B: {"name": "home-beta", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-alpha", "status": "active", "board": [], "board_open": 0},
    "projects/beta": {"title": "Beta", "name": "Beta", "org": "work", "tags": [], "type": "project", "session": "home-beta", "status": "active", "board": [], "board_open": 0}}}))
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def item(i, owner, project, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[{'work' if project == 'beta' else 'home'}] item a{i}", "description": "A thing. It lives here. Done when it works.",
                                                     "status": "open", "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": owner, "project": f"projects/{project}", "next": "the next step", **meta}}))
item(3, A, "alpha", needs=["decision"], ask=ASK, options=OPTS)                       # the item the notice names
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n"); (T / "brain/projects/beta.md").write_text("---\ntitle: Beta\n---\n\n# Beta\n")
import subprocess
def git(*a): subprocess.run(["git", "-C", str(T / "store"), *a], check=True, capture_output=True)
git("init", "-q"); git("config", "user.email", "t@example.org"); git("config", "user.name", "t"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.web import publish as _web_publish
from stackshot.web import board_home as _board_home
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.auth import signin as _signin
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {got}"))
    if not cond: fails.append(name)

srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
th = threading.Thread(target=srv.run, daemon=True); th.start()
for _ in range(200):
    if srv.started: break
    time.sleep(0.05)
if not srv.started: print("the test server did not start"); sys.exit(1)

COOKIE = {"name": _signin._UI_COOKIE, "value": _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "url": BASE}
from playwright.sync_api import sync_playwright
NOTICE = """() => { const p = document.querySelector('p.isent'); if (!p) return null; const a = [...p.querySelectorAll('a')], pr = p.getBoundingClientRect(), l = a[0] && a[0].getBoundingClientRect();
  return {text: p.textContent, role: p.getAttribute('role'), cls: p.className, n: a.length, href: a[0] && a[0].getAttribute('href'), target: a[0] && a[0].getAttribute('target'), rel: a[0] && a[0].getAttribute('rel'),
          atext: a[0] && a[0].textContent, cover: l ? [Math.round(l.left - pr.left), Math.round(pr.right - l.right), Math.round(l.top - pr.top), Math.round(pr.bottom - l.bottom)] : null,
          pcolor: getComputedStyle(p).color, acolor: a[0] && getComputedStyle(a[0]).color, cursor: a[0] && getComputedStyle(a[0]).cursor} }"""
def notice(pg, query):
    pg.goto(BASE + "/" + query); pg.wait_for_selector("p.isent", timeout=8000); return pg.evaluate(NOTICE)
try:
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        ctx = br.new_context(viewport={"width": 1500, "height": 1000}); ctx.add_cookies([COOKIE]); pg = ctx.new_page()
        n = notice(pg, "?sent=decision&item=a3")
        print("notice with an item:", n)
        check("an item: the notice holds exactly one anchor", n and n["n"] == 1, n)
        check("an item: the anchor points at the item page's address and opens in a new tab with noopener", n and n["href"] == "/items/a3" and n["target"] == "_blank" and n["rel"] == "noopener", n)
        check("an item: the anchor carries the whole notice text, and the paragraph keeps its role and classes", n and n["atext"] == n["text"] and "a3" in n["text"] and n["role"] == "status" and "isent" in n["cls"].split() and "ok" in n["cls"].split(), n)
        check("an item: the anchor covers the notice to its edges, shows a pointer, and keeps the notice's color", n and n["cover"] is not None and all(abs(v) <= 1 for v in n["cover"]) and n["cursor"] == "pointer" and n["acolor"] == n["pcolor"], n)
        with ctx.expect_page(timeout=8000) as newp: pg.click("p.isent a")
        np_ = newp.value; np_.wait_for_load_state(); check("an item: a click opens the item's page in a new tab", np_.url.endswith("/items/a3"), np_.url); np_.close()
        pg.bring_to_front()
        m = notice(pg, "?sent=decision")
        check("no item: the notice is plain text, with no anchor", m and m["n"] == 0 and m["text"] and m["role"] == "status", m)
        b = notice(pg, "?sent=decision&item=a3%22%3E%3Cb")
        check("an id the script does not accept: the notice is plain text, with no anchor", b and b["n"] == 0 and b["text"] == m["text"], b)
        ctx.close(); br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)
print(f"ok: the notice after a move is one link, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
