"""Home send keeps the folds (a manual check like home_step_send_check.py: it needs the browser, which CI's runner has not; the same page scripts run in node, against a fake
document, in fold_memory_scenario.py, which CI does run). Starts the server in-process on 127.0.0.1 with a temporary config and fixture data (no live store, no network), signs a
browser in with the board's cookie and loads the home page in Chromium. It folds a main-column section, a project group and a side-panel section, and opens a section that renders
closed; then, from a home row, it sends a Done, a Send note and an answer (a card and Send), one after the other. After each send's 303 landing (/?sent=...) and again after the next
live swap, every fold on the page is as the viewer left it, and the stored choices are the same. A second tab of the same browser, loaded before any fold was touched and so still
showing the defaults, takes a live swap too (before the sends and after each one): it must leave the stored choices as the first tab set them. (That second tab is the case that failed:
a swapped-in fold that arrives open fires a toggle the listener recorded as a choice.)

    tests/run-suite home_send_folds_check     -> exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, sys, tempfile, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="sendfolds-"); T = pathlib.Path(tmp)
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
item(1, A, "alpha", state="your-step", step="Call the office and say done")          # sent with Done
item(2, A, "alpha", state="your-step", step="Write the note and send it")            # sent with Send note
item(3, A, "alpha", needs=["decision"], ask=ASK, options=OPTS)                       # answered with a card
item(4, A, "alpha", needs=["decision"], ask=ASK, options=OPTS)                       # stays: the Alpha group never empties
item(5, B, "beta", needs=["decision"], ask=ASK, options=OPTS)                        # the Beta group, which the viewer folds
item(6, B, "beta")                                                                    # an item an agent works on: the section that renders closed
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
_web_page_debts._owing_note = lambda debtor: ""
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
FOLDS = "() => { const o = {}; document.querySelectorAll('details.fold').forEach(d => { o[d.getAttribute('data-fold')] = d.open }); return o }"
STORED = "() => { const o = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.startsWith('stackshot.fold.')) o[k.slice(15)] = localStorage.getItem(k) } return o }"
bumps = [0]
def bump():
    """Something else changed on the board (an agent wrote to an item): two items get a new subject and the server's kept home draw is dropped, so the next stamp is newer and the page's next poll swaps blocks in."""
    bumps[0] += 1
    for i, scope in ((4, "home"), (6, "work")):
        f = T / f"store/a/{i}.json"; r = json.loads(f.read_text()); r["subject"] = f"[{scope}] item a{i} edit {bumps[0]}"; f.write_text(json.dumps(r))
    time.sleep(1.2); _board_home._board_home_drop()
def show(d): return {k: v for k, v in sorted(d.items())}
try:
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        ctx = br.new_context(viewport={"width": 1500, "height": 1000}); ctx.add_cookies([COOKIE]); pg = ctx.new_page()
        pg.add_init_script("document.addEventListener('stackshot:swapped', () => { window.__swaps = (window.__swaps || 0) + 1 })")
        pg.goto(BASE + "/"); pg.wait_for_selector("li#task-a-1 form.hstep:not([hidden])", timeout=8000); pg.wait_for_timeout(300)
        other = ctx.new_page(); other.add_init_script("document.addEventListener('stackshot:swapped', () => { window.__swaps = (window.__swaps || 0) + 1 })")      # a second tab of the same browser, loaded before any fold was touched: it keeps showing the defaults
        other.goto(BASE + "/"); other.wait_for_selector("li#task-a-1 form.hstep:not([hidden])", timeout=8000); pg.bring_to_front()
        d0 = pg.evaluate(FOLDS)
        print("folds on a fresh page:", show(d0))
        groups = [k for k in d0 if k.startswith("home.your-move.")]
        beta = "home.your-move.work"          # the group of the second project (scope work); the first project's rows are in home.your-move.home, the group the sends come from
        panel = next((k for k in ("machines", "runners", "anchorhub", "audit", "projects") if k in d0), None)
        check("the page has the folds the check drives", beta in d0 and "home.your-move.home" in d0 and panel is not None and all(k in d0 for k in ("your-move", "agents-at-work", "queued-release")), sorted(d0))
        check("defaults: Your move and Queued for release open, On agent and Waiting closed", d0["your-move"] and d0["queued-release"] and not d0["agents-at-work"] and not d0["waiting-list"], show(d0))
        FOUR = (beta, panel, "queued-release", "agents-at-work")
        for k in FOUR:          # a project group and a panel section closed, a main section closed, a main section that renders closed opened
            pg.click(f"details.fold[data-fold='{k}'] > summary"); pg.wait_for_timeout(150)
        now_ = pg.evaluate(FOLDS)
        check("the four folds took the click", (now_[beta], now_[panel], now_["queued-release"], now_["agents-at-work"]) == (False, False, False, True), show(now_))
        pg.reload(); pg.wait_for_selector("li#task-a-1 form.hstep:not([hidden])", timeout=8000); pg.wait_for_timeout(300)
        base = pg.evaluate(FOLDS); stored0 = pg.evaluate(STORED)
        check("a plain reload keeps the four folds", (base[beta], base[panel], base["queued-release"], base["agents-at-work"]) == (False, False, False, True), show(base))
        print("stored after the reload:", show(stored0))

        def swap_in(page):
            """Something else changed on the board, then `page` polls until it has swapped blocks in (a poll starts the server's new draw and a later one finds its stamp; the page polls at most every 2 s, here by a focus event)."""
            bump(); page.wait_for_timeout(2200)
            n0 = page.evaluate("window.__swaps || 0")
            for _ in range(4):
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                try: page.wait_for_function(f"(window.__swaps || 0) > {n0}", timeout=2500); page.wait_for_timeout(300); return True
                except Exception: pass
            return False
        def stale_tab(label):
            sw = swap_in(other); st = pg.evaluate(STORED)
            check(f"{label}: the stale tab's live swap leaves the stored choices of the four folds as the viewer set them", sw and all(st.get(k) == stored0.get(k) for k in FOUR), (sw, show(st), show(stored0)))
        stale_tab("before any send")

        def landing(kind, act):
            with pg.expect_navigation(url=re.compile(r"[?&]sent="), timeout=15000): act()
            pg.wait_for_selector("p.isent", timeout=8000); pg.wait_for_timeout(400)
            on = pg.evaluate(FOLDS); st = pg.evaluate(STORED)
            bad = {k: (base[k], on[k]) for k in base if k in on and base[k] != on[k]}
            check(f"{kind}: every fold is as it was after the 303 landing", not bad, bad)
            check(f"{kind}: the stored choices of the four folds are unchanged after the landing", all(st.get(k) == stored0.get(k) for k in FOUR), (show(st), show(stored0)))
            swapped = swap_in(pg)
            on2 = pg.evaluate(FOLDS); st2 = pg.evaluate(STORED)
            bad2 = {k: (base[k], on2[k]) for k in base if k in on2 and base[k] != on2[k]}
            check(f"{kind}: every fold is as it was after the next live swap", swapped and not bad2, (swapped, bad2))
            check(f"{kind}: the stored choices are unchanged after the swap", all(st2.get(k) == stored0.get(k) for k in FOUR), (show(st2), show(stored0)))
            stale_tab(kind)
        landing("Done", lambda: pg.click("li#task-a-1 form.hstep button[value=done]"))
        pg.fill("#astep-a2", "a note"); pg.wait_for_timeout(100)
        landing("Send note", lambda: pg.click("li#task-a-2 form.hstep button[value=note]"))
        pg.click("li#task-a-3 form[data-cards] .acard"); pg.wait_for_timeout(100)
        landing("answer", lambda: pg.click("li#task-a-3 form[data-cards] button[name=act]"))
        ctx.close(); br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)
print(f"ok: home send keeps the folds, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
