"""Home step-buttons check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Starts the server in-process on 127.0.0.1 with a temporary
config and fixture data (no live store, no network), signs a browser in with the board's cookie, and loads the home page in Chromium:

  - a "your step" row's Done is enabled once the page script has shown the form, with the box empty (Done finishes the step with or without a note), and stays enabled after a note
    is typed and after it is cleared again; its Send note is disabled while the box is empty, enabled once a note is typed, and disabled again when it is cleared;
  - a decision row's Send (the form with option cards) is disabled until a card is picked or a note is typed, and goes back to disabled when the note is cleared.

    tests/run-suite home_step_send_check     → exit 0 / 1
    (the browser, once per machine: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, sys, tempfile, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stepsend-"); T = pathlib.Path(tmp)
EMAIL = "oliver@example.org"
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BASE}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BASE}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "A thing. It lives here. Done when it works.",
                                                     "status": "open", "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", **meta}}))
item(1, needs=["decision"], ask=ASK, options=OPTS)
item(2, state="your-step", step="Call the office and say done")
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
import subprocess
def git(*a): subprocess.run(["git", "-C", str(T / "store"), *a], check=True, capture_output=True)
git("init", "-q"); git("config", "user.email", "t@example.org"); git("config", "user.name", "t"); git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
import uvicorn; from stackshot.web import server
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda *a, **k: None
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

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

COOKIE = {"name": server._UI_COOKIE, "value": server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600})), "url": BASE}
from playwright.sync_api import sync_playwright
STATE = """() => { const q = (s) => document.querySelector(s), v = (f) => !!f && !f.hidden && f.getClientRects().length > 0;
  const st = q('li#task-a-2 form.hstep'), dc = q('li#task-a-1 form[data-cards]');
  return {step: st && {shown: v(st), dis: st.querySelector('button[value=done]').disabled, note: st.querySelector('button[value=note]').disabled}, dec: dc && {shown: v(dc), dis: dc.querySelector('button[name=act]').disabled}}; }"""
try:
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception as e:
            print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
        ctx = br.new_context(viewport={"width": 1000, "height": 900}); ctx.add_cookies([COOKIE]); pg = ctx.new_page()
        pg.goto(BASE + "/"); pg.wait_for_selector("li#task-a-2 form.hstep:not([hidden])", timeout=8000); pg.wait_for_selector("li#task-a-1 form[data-cards]:not([hidden])", timeout=8000); pg.wait_for_timeout(300)
        s0 = pg.evaluate(STATE)
        check("both rows are on the page with their forms shown", s0["step"] and s0["step"]["shown"] and s0["dec"] and s0["dec"]["shown"], s0)
        check("step row: Done is enabled and Send note is disabled with the box empty", s0["step"]["dis"] is False and s0["step"]["note"] is True, s0)
        check("decision row: Send is disabled with nothing picked and no note", s0["dec"]["dis"] is True, s0)
        pg.fill("#astep-a2", "a note on the step"); pg.wait_for_timeout(100)
        check("step row: after a note is typed Done stays enabled and Send note is enabled", pg.evaluate(STATE)["step"]["dis"] is False and pg.evaluate(STATE)["step"]["note"] is False, pg.evaluate(STATE))
        pg.fill("#astep-a2", ""); pg.wait_for_timeout(100)
        check("step row: after the note is cleared Done stays enabled and Send note is disabled again", pg.evaluate(STATE)["step"]["dis"] is False and pg.evaluate(STATE)["step"]["note"] is True, pg.evaluate(STATE))
        pg.fill("#astep-a2", "   \n  "); pg.wait_for_timeout(100)
        check("step row: a note of spaces only leaves Send note disabled", pg.evaluate(STATE)["step"]["note"] is True, pg.evaluate(STATE))
        pg.fill("#atext-a1", "a note"); pg.wait_for_timeout(100)
        check("decision row: typing a note enables Send", pg.evaluate(STATE)["dec"]["dis"] is False, pg.evaluate(STATE))
        pg.fill("#atext-a1", ""); pg.wait_for_timeout(100)
        check("decision row: clearing the note disables Send again", pg.evaluate(STATE)["dec"]["dis"] is True, pg.evaluate(STATE))
        pg.click("li#task-a-1 form[data-cards] .acard"); pg.wait_for_timeout(100)
        check("decision row: picking a card enables Send", pg.evaluate(STATE)["dec"]["dis"] is False, pg.evaluate(STATE))
        ctx.close(); br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)
print(f"ok: home step-buttons check, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
