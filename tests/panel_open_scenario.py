"""Scenario test for whether the side panel is open or closed on a wide screen, as the signed-in person last left it (uiprefs.py panel_open, ui/render.py apply_panel_open and
_PANEL_JS, the /prefs/panel-open route and _panel_ordered in server.py): fixture data, the routes through Starlette's test client, no live store, no network. People and addresses are made up.

Covers:
  * uiprefs: open is the default for nobody signed in, for a person with no entry and for a file with no such key (one written before the key existed: no migration); closing stores
    `"panel_open": false`, opening again removes the key, and a person left with no setting has no entry; the panel order and the panel state leave each other and the person's other keys
    alone; a value that is not `false` reads as open; two people differ; a file that cannot be read gives open and a save raises without changing it; a failed save leaves no temporary file;
  * the page: every root page that carries the panel (home, which the For you section is part of, an item page, a project page, Projects, Closed, Audits, Search) is drawn open by default (body.panel-pin,
    the button expanded, "Hide summary panel"), the item page included (it no longer starts closed on its own); with the panel stored closed the same pages come with a bare body and the
    button offering to show it, and nothing else in the page differs (same shell and block fingerprints, the sections in the person's order); another person and a visitor not signed in
    still get it open; the home's kept draw stays open for everyone; the order and the state apply together;
  * the save route (POST /prefs/panel-open): refused without sign-in (403), from a foreign origin or none (403), without a JSON content type (415), with a body that is too long (413),
    not JSON (400), not an object (400), with no `open` or one that is not a real boolean (400), and nothing is written then; a good body answers {"open": bool}; GET is 405; an
    unreadable settings file answers 503 and is left as it was; the order save still works beside it and keeps the state;
  * the scenario: Mina closes the panel on her laptop and opens the board on her phone's wide window and on another page, where it is closed; Noor beside her sees it open; Mina opens it again;
  * the script: it saves only a click on a wide screen (the drawer's open, close, scrim, Escape and the width change save nothing), sends one boolean, keeps no state in the browser, and
    writes its address at the root; the in-place swap does not touch the body; every inline script parses (node, when present).

    tests/run-suite panel_open        → exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="popen-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MINA, NOOR = "mina@example.org", "noor@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}", "{NOOR}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A, X = "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in ((A, "alpha-main"), (X, "alpha-x"))}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
now0 = time.time()
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[work] item one", "description": "- A thing\n- It lives here\n- Finished when it works", "status": "open",
    "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step"}}))
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web import search; from stackshot.web import uiprefs as up
from stackshot.web import server
from stackshot.web.auth import signin as _signin
from stackshot.web import board_home as _web_board_home
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
server._publish = lambda: None
DEFAULT = ["machines", "runners", "anchorhub", "audit-panel", "projects-panel"]
UI = up.path()
def users(): return json.loads(UI.read_text())["users"] if UI.exists() else {}

# ---- 1. uiprefs
check("no file yet: the panel is open for everyone, nobody signed in too, and reading writes nothing", up.panel_open(MINA) is True and up.panel_open("") is True and up.panel_prefs(MINA) == (DEFAULT, True)
      and up.panel_prefs("") == (DEFAULT, True) and not UI.exists())
check("set_panel_open(closed) returns False and stores `panel_open: false` for that person only", up.set_panel_open(MINA, False) is False and users() == {MINA: {"panel_open": False}}
      and up.panel_open(MINA) is False and up.panel_open(NOOR) is True, UI.read_text())
check("…two people, two states, one file", up.set_panel_open(NOOR, False) is False and up.set_panel_open(MINA, True) is True and up.panel_open(MINA) is True and up.panel_open(NOOR) is False
      and users() == {NOOR: {"panel_open": False}}, UI.read_text())
up.set_panel_open(NOOR, True)
check("opening again removes the key and a person left with nothing has no entry (open is the default, never stored)", users() == {} and up.panel_open(NOOR) is True, UI.read_text())
up.set_panel_open(MINA, True)
check("opening a panel that was never closed stores nothing", users() == {}, UI.read_text())
up.set_panel_open(MINA, False); up.set_panel_order(MINA, ["runners", "machines"])
order_now = up.panel_order(MINA)
check("saving the panel order leaves the closed state, and both are on file for the person", users() == {MINA: {"panel_open": False, "panel_order": order_now}} and up.panel_open(MINA) is False
      and up.panel_prefs(MINA) == (order_now, False), UI.read_text())
up.reset_panel_order(MINA)
check("resetting the order leaves the closed state (the entry stays: it holds the state)", users() == {MINA: {"panel_open": False}} and up.panel_order(MINA) == DEFAULT, UI.read_text())
up.set_panel_order(MINA, ["runners", "machines"]); up.set_panel_open(MINA, True)
check("opening leaves the saved order (the entry stays: it holds the order)", users() == {MINA: {"panel_order": order_now}} and up.panel_order(MINA) == order_now, UI.read_text())
up.reset_panel_order(MINA)
check("no setting left, no entry", users() == {}, UI.read_text())
# a file written before the key existed, a person with other keys, and values that are not `false`
UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["runners", "machines", "anchorhub", "audit-panel", "projects-panel"]}, NOOR: {"theme": "dark"}}}), encoding="utf-8")
check("an old file without the key reads as open, with its order intact, and needs no migration", up.panel_open(MINA) is True and up.panel_open(NOOR) is True
      and up.panel_order(MINA)[0] == "runners")
up.set_panel_open(NOOR, False)
check("a person's other keys are kept when the state is saved", users()[NOOR] == {"theme": "dark", "panel_open": False}, UI.read_text())
up.set_panel_open(NOOR, True)
check("…and when it is opened again (the entry stays: it holds the other key)", users()[NOOR] == {"theme": "dark"}, UI.read_text())
for odd in (True, None, 0, "false", "closed", [], {}, 1):
    UI.write_text(json.dumps({"users": {MINA: {"panel_open": odd}}}), encoding="utf-8")
    check(f"a stored value of {json.dumps(odd)} is not `false`: the panel reads as open", up.panel_open(MINA) is True)
UI.write_text(json.dumps({"users": {MINA: "x", NOOR: ["panel_open"]}}), encoding="utf-8")
check("an entry of the wrong shape reads as open", up.panel_open(MINA) is True and up.panel_open(NOOR) is True)
UI.write_text(json.dumps({"users": {MINA: {"panel_open": False}}}), encoding="utf-8")
check("a stored `false` reads as closed", up.panel_open(MINA) is False and up.panel_prefs(MINA) == (DEFAULT, False))
UI.write_text("{broken", encoding="utf-8")
check("a file that does not parse: open, moved aside, a fresh start", up.panel_open(MINA) is True and not UI.exists() and len(list(UI.parent.glob("ui-prefs.json.bad-*"))) == 1)
for f in UI.parent.glob("ui-prefs.json.bad-*"): f.unlink()
# a save that fails is not a half write: the file is as it was and no temporary file is left
up.set_panel_open(MINA, False); before = UI.read_text(); real_replace = os.replace
def failing_replace(a, b): raise OSError(28, "No space left on device")
os.replace = failing_replace
try:
    try: up.set_panel_open(NOOR, False); failed = False
    except OSError: failed = True
finally: os.replace = real_replace
check("a failed save raises, leaves the file as it was and removes its temporary file", failed and UI.read_text() == before and not list(UI.parent.glob("*.tmp")), list(UI.parent.glob("*")))
# opening a panel that is not stored closed is a no-op: nothing is written (no fsync, no replace), and an unwritable file is no error for it
UI.write_text(json.dumps({"users": {NOOR: {"panel_open": False}}}), encoding="utf-8"); noop_before = UI.read_text(); noop_events = []; real_fsync = os.fsync
def spy_fsync(fd): noop_events.append("fsync"); return real_fsync(fd)
def spy_replace(a, b): noop_events.append("replace"); return real_replace(a, b)
os.fsync, os.replace = spy_fsync, spy_replace
try: r_open = up.set_panel_open(MINA, True)
finally: os.fsync, os.replace = real_fsync, real_replace
check("opening the panel for a person with nothing stored writes nothing: no fsync, no replace, the file as it was", r_open is True and noop_events == [] and UI.read_text() == noop_before, noop_events)
os.replace = failing_replace
try:
    try: r_open = up.set_panel_open(MINA, True); noop_ok = r_open is True
    except OSError: noop_ok = False
    try: up.set_panel_open(NOOR, True); noop_real_write_raised = False
    except OSError: noop_real_write_raised = True
finally: os.replace = real_replace
check("...so a no-op open on an unwritable file raises nothing, while really opening a stored closed panel there still raises", noop_ok and noop_real_write_raised and UI.read_text() == noop_before)
UI.unlink()
check("...and with no file at all it creates none", up.set_panel_open(MINA, True) is True and not UI.exists())
up.set_panel_open(MINA, False); before = UI.read_text()
# a file that cannot be read is not an empty file: a save raises, a read gives open and writes nothing
real_read = pathlib.Path.read_text
def denied_read(self, *a, **k):
    if self == UI: raise PermissionError(13, "Permission denied")
    return real_read(self, *a, **k)
pathlib.Path.read_text = denied_read
try:
    try: up.set_panel_open(NOOR, False); raised = False
    except OSError: raised = True
    unread = (up.panel_open(MINA), up.panel_prefs(MINA))
finally: pathlib.Path.read_text = real_read
check("an unreadable settings file: a save raises, a read gives open (the defaults), and the file is as it was", raised and unread == (True, (DEFAULT, True)) and UI.read_text() == before
      and not list(UI.parent.glob("ui-prefs.json.bad-*")), (raised, unread))
UI.unlink()

# ---- 2. the page
COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
SAME = {"Origin": BOARD}
JSON_H = {**SAME, "Content-Type": "application/json"}
PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("projects", "/projects"), ("closed", "/closed"), ("audits", "/audits"), ("search", "/search?q=item")]
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))
OPEN_BODY, SHUT_BODY = r2._PANEL_BODY + '<div id="layout">', r2._PANEL_BODY_CLOSED + '<div id="layout">'
OPEN_BTN = 'id="panel-open" aria-label="Summary panel" aria-controls="panel" aria-expanded="true" title="Hide summary panel"'
SHUT_BTN = 'id="panel-open" aria-label="Summary panel" aria-controls="panel" aria-expanded="false" title="Show summary panel"'
def state(h):
    """open, closed or odd: what the page draws for the panel (the body tag and the button, which must agree)."""
    body_open, body_shut = OPEN_BODY in h, SHUT_BODY in h
    btn_open, btn_shut = OPEN_BTN in h, SHUT_BTN in h
    if body_open and btn_open and not body_shut and not btn_shut: return "open"
    if body_shut and btn_shut and not body_open and not btn_open: return "closed"
    return f"odd: body open={body_open} shut={body_shut}, button open={btn_open} shut={btn_shut}"
def sections(h):
    i = h.index('<aside id="panel"'); a = h[i:h.index("</aside>", i)]
    return re.findall(r"<!--ps:([a-z-]+)-->", a)
norm = lambda t: re.sub(r'<meta name="stackshot-rendered" content="[^"]*">|data-ts="[0-9]+"|showing the board as of [^<]*?(?=\. Retrying)|<p class="rline">.*?</p>', "", t, flags=re.S)       # the page's own draw time (the rendered line, to the minute) is not what differs
def same_but_panel(a, b):
    """a (drawn open) and b (drawn closed) are the same page apart from the body tag and the button."""
    return norm(r2.apply_panel_open(a, False)) == norm(b)
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, who=MINA):
        c.cookies.clear()
        if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.get(path, follow_redirects=False)
    def post(body, who=MINA, headers=JSON_H, raw=None, path="/prefs/panel-open"):
        c.cookies.clear()
        if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers, follow_redirects=False)

    base = {}
    for n, p in PAGES:
        r = get(p); base[n] = r.text
        check(f"default: the {n} page ({p}) is served and draws the panel open (pinned body, the button offering to hide it)", r.status_code == 200 and state(r.text) == "open", (r.status_code, state(r.text)))
    check("default: the item page does not start closed on its own any more", state(base["item"]) == "open" and 'class="panel-pin"' in base["item"])
    check("default: a visitor not signed in (auth off) and the other person get it open on every page", all(state(get(p, None).text) == "open" and state(get(p, NOOR).text) == "open" for _, p in PAGES))

    # saved closed
    r = post({"open": False})
    check("save: {\"open\": false} answers {\"open\": false} and is on disk for that person only", r.status_code == 200 and r.json() == {"open": False} and users() == {MINA: {"panel_open": False}}
          and r.headers.get("cache-control") == "no-store", (r.status_code, r.text, UI.read_text() if UI.exists() else ""))
    shut = {n: get(p).text for n, p in PAGES}
    for n, h in shut.items():
        check(f"closed: the {n} page draws the panel closed (a bare body, the button offering to show it), and nothing else differs from the open page", state(h) == "closed" and same_but_panel(base[n], h), state(h))
    check("closed: the panel itself is still in the page (a hover still peeks it open, the button shows it)", all('<aside id="panel"' in h and 'id="panel-edge"' in h and 'id="panel-scrim"' in h and 'id="panel-open"' in h for h in shut.values()))
    check("closed: the home's shell and block fingerprints are the open page's (the in-place update keeps working)", all(
        re.search(rf'<meta name="stackshot-{k}" content="([^"]*)">', shut["home"]).group(1) == re.search(rf'<meta name="stackshot-{k}" content="([^"]*)">', base["home"]).group(1) for k in ("shell", "blocks")))
    check("closed: the kept draw of the home is still open (the state is put in per person on the way out)", state(_web_board_home._BOARD_HOME["html"]) == "open")
    c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[MINA]); rr = c.get("/")
    check("closed: Content-Length matches the body served", int(rr.headers["content-length"]) == len(rr.content), (rr.headers["content-length"], len(rr.content)))
    check("another signed-in person still gets it open, on every page", all(state(get(p, NOOR).text) == "open" for _, p in PAGES))
    check("nobody signed in still gets it open, on every page", all(state(get(p, None).text) == "open" for _, p in PAGES))
    post({"open": False}, who=NOOR)
    check("two people closed it: each has their own key", users() == {MINA: {"panel_open": False}, NOOR: {"panel_open": False}})
    post({"open": True}, who=NOOR)
    check("Noor opening it again does not open it for Mina", state(get("/", MINA).text) == "closed" and state(get("/", NOOR).text) == "open" and users() == {MINA: {"panel_open": False}})

    # the order and the state together; the order save keeps the state
    r = post({"order": ["audit-panel", "runners"]}, path="/prefs/panel-order")
    both = get("/").text
    check("the order save keeps the closed state; the page has the new order and is closed", r.status_code == 200 and users()[MINA].get("panel_open") is False
          and state(both) == "closed" and sections(both) == ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"], (r.status_code, users(), sections(both)))
    post({"reset": True}, path="/prefs/panel-order")
    r = post({"open": True})
    check("opening it again: the page is open on every page and the file has no entry", r.status_code == 200 and r.json() == {"open": True} and users() == {}
          and all(state(get(p).text) == "open" for _, p in PAGES), (r.text, UI.read_text() if UI.exists() else ""))
    # an old file without the key, and a stored value that is not `false`
    UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["runners", "machines", "anchorhub", "audit-panel", "projects-panel"]}}}), encoding="utf-8")
    old = get("/").text
    check("an old store with an order and no panel_open key draws open, in the person's order", state(old) == "open" and sections(old)[0] == "runners", (state(old), sections(old)))
    UI.write_text(json.dumps({"users": {MINA: {"panel_open": "no"}}}), encoding="utf-8")
    check("a stored value that is not `false` draws open", state(get("/").text) == "open")
    UI.write_text(json.dumps({"users": {MINA: {"panel_open": False}}}), encoding="utf-8")
    check("a store with `panel_open: false` written by hand draws closed on every page", all(state(get(p).text) == "closed" for _, p in PAGES))
    UI.write_text("{broken", encoding="utf-8")
    rb = get("/")
    check("an unreadable file: the page still comes, open", rb.status_code == 200 and state(rb.text) == "open")
    UI.unlink(missing_ok=True)
    for f in UI.parent.glob("ui-prefs.json.bad-*"): f.unlink()

    # the in-place update: it fetches the page as the same person and swaps blocks, never the body
    live = r2._LIVE_JS
    check("the in-place swap leaves the body and the panel alone: it swaps blocks by id, reads no panel class and no panel state, and never writes the body's class",
          "panel-pin" not in live and "panel-open" not in live and "panel-peek" not in live and "classList" not in live.replace("B.className", "")
          and "#panel" not in live.replace("#panel[data-pbusy],#panel-menu:not([hidden])", ""), None)
    post({"open": False}); fresh = get("/").text
    check("the page the swap fetches (the same URL, as the same person) is closed too, so a swapped-in page agrees with the body already there", state(fresh) == "closed", state(fresh))
    post({"open": True})

    # the kept home draw: a toggle leaves it (the draw does not depend on the state); the order save still drops it as before
    get("/"); kept_gen, kept_at, kept_html = _web_board_home._BOARD_HOME["gen"], _web_board_home._BOARD_HOME["at"], _web_board_home._BOARD_HOME["html"]
    check("the kept home draw exists after a read", kept_html is not None and kept_at > 0)
    post({"open": False}); post({"open": True}); post({"open": False}); post({"open": True})
    check("toggling the panel (four saves) leaves the kept home draw: same generation, same time, same page", _web_board_home._BOARD_HOME["gen"] == kept_gen and _web_board_home._BOARD_HOME["at"] == kept_at and _web_board_home._BOARD_HOME["html"] is kept_html,
          (_web_board_home._BOARD_HOME["gen"], kept_gen))
    post({"open": False})
    check("...and the next read serves the stored state from that same draw", state(get("/").text) == "closed" and _web_board_home._BOARD_HOME["html"] is kept_html and state(kept_html) == "open")
    post({"open": True})
    post({"order": ["runners", "machines"]}, path="/prefs/panel-order")
    check("(control) the order save still drops it", _web_board_home._BOARD_HOME["gen"] == kept_gen + 1 and _web_board_home._BOARD_HOME["at"] == 0.0, _web_board_home._BOARD_HOME["gen"])
    post({"reset": True}, path="/prefs/panel-order")
    # an open save that is a no-op answers 200 even where the file cannot be written
    os.replace = failing_replace
    try: r = post({"open": True})
    finally: os.replace = real_replace
    check('save: {"open": true} for a person with nothing stored answers 200 even when the settings file cannot be written (nothing to write)', r.status_code == 200 and r.json() == {"open": True}, (r.status_code, r.text))

    # ---- 3. the save route
    GOOD = {"open": False}
    r = post(GOOD, who=None)
    check("save: not signed in is refused (403) and nothing is written", r.status_code == 403 and users() == {}, (r.status_code, r.text[:80]))
    r = post(GOOD, headers={"Origin": "https://evil.example.net", "Content-Type": "application/json"})
    check("save: from a foreign origin is refused (403)", r.status_code == 403 and users() == {}, r.status_code)
    r = post(GOOD, headers={"Content-Type": "application/json"})
    check("save: with no Origin or Referer is refused (403)", r.status_code == 403 and users() == {}, r.status_code)
    r = post(GOOD, headers={**SAME, "Content-Type": "text/plain"})
    check("save: not JSON by its content type is refused (415)", r.status_code == 415 and users() == {}, r.status_code)
    r = post(None, raw="x" * 5000)
    check("save: a body over 4 KB is refused (413)", r.status_code == 413 and users() == {}, r.status_code)
    bad = {"not json": dict(raw="{nope"), "an array": dict(body=[False]), "a string": dict(body="closed"), "null": dict(body=None), "a bare boolean": dict(body=False),
           "no open key": dict(body={"colour": "blue"}), "open null": dict(body={"open": None}), "open a string": dict(body={"open": "false"}), "open the string true": dict(body={"open": "true"}),
           "open 0": dict(body={"open": 0}), "open 1": dict(body={"open": 1}), "open a list": dict(body={"open": [False]}), "open a dict": dict(body={"open": {}}),
           "an order only": dict(body={"order": ["runners"]}), "a reset": dict(body={"reset": True})}
    for what, kw in bad.items():
        r = post(kw.get("body"), raw=kw.get("raw"))
        check(f"save: {what} is refused (400) and nothing is written", r.status_code == 400 and users() == {}, (r.status_code, r.text[:80]))
    r = post({"open": False, "extra": "ignored"})
    check("save: an extra key is ignored", r.status_code == 200 and users() == {MINA: {"panel_open": False}}, r.text)
    r = post({"open": True})
    check("save: open removes the key", r.status_code == 200 and r.json() == {"open": True} and users() == {}, r.text)
    c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[MINA])
    check("GET on the save route is not served a page (405)", c.get("/prefs/panel-open").status_code in (404, 405))
    r = post({"open": False}, headers={"Referer": BOARD + "/", "Content-Type": "application/json"})
    check("save: a Referer from the board's own page is accepted when the browser sent no Origin", r.status_code == 200 and users() == {MINA: {"panel_open": False}}, r.status_code)
    post({"open": True})
    # a settings file that cannot be read: a clean refusal, the file untouched, the page still served
    up.set_panel_open(NOOR, False); kept = UI.read_text()
    pathlib.Path.read_text = denied_read
    try:
        r = post({"open": False}); pg = get("/")
    finally: pathlib.Path.read_text = real_read
    check("save: an unreadable settings file answers 503 'could not be saved' and the page still comes, open", r.status_code == 503 and "could not be saved" in r.text and pg.status_code == 200 and state(pg.text) == "open", (r.status_code, r.text))
    check("…nothing was dropped (no empty file written, the other person's state kept)", UI.read_text() == kept and not list(UI.parent.glob("ui-prefs.json.bad-*")), UI.read_text())
    post({"open": True}, who=NOOR)
    # the size is judged from Content-Length before the body is read; a body with none is cut off as it arrives
    import asyncio
    from starlette.requests import Request
    def raw_post(length, chunks):
        hs = [(b"host", b"board.example.org"), (b"origin", BOARD.encode()), (b"content-type", b"application/json"), (b"cookie", f"{_signin._UI_COOKIE}={COOKIE[MINA]}".encode())]
        if length is not None: hs.append((b"content-length", str(length).encode()))
        scope = {"type": "http", "method": "POST", "path": "/prefs/panel-open", "raw_path": b"/prefs/panel-open", "query_string": b"", "headers": hs, "scheme": "https",
                 "server": ("board.example.org", 443), "client": ("203.0.113.9", 5000), "http_version": "1.1", "root_path": ""}
        reads = []
        async def receive():
            k = len(reads); reads.append(k)
            if k < len(chunks): return {"type": "http.request", "body": chunks[k], "more_body": k < len(chunks) - 1}
            return {"type": "http.disconnect"}
        return asyncio.run(server.panel_open_save(Request(scope, receive))), len(reads)
    resp, nread = raw_post(10_000_000, [b"x" * 100])
    check("save: a Content-Length over 4 KB is refused (413) before any of the body is read", resp.status_code == 413 and nread == 0, (resp.status_code, nread))
    resp, nread = raw_post("12abc", [b"{}"])
    check("save: a Content-Length that is not a number is refused (400) before the body is read", resp.status_code == 400 and nread == 0, (resp.status_code, nread))
    resp, nread = raw_post(None, [b"x" * 3000, b"x" * 3000, b"x" * 3000])
    check("save: a body with no Content-Length is cut off as it passes 4 KB (413), the rest not read", resp.status_code == 413 and nread == 2, (resp.status_code, nread))
    resp, nread = raw_post(None, [b'{"open": ', b'false}'])
    check("save: a small chunked body is read whole and saved", resp.status_code == 200 and json.loads(resp.body) == {"open": False} and users() == {MINA: {"panel_open": False}}, resp.body)
    post({"open": True})

    # ---- 4. the scenario: Mina closes it on her laptop, opens the board on another page, Noor beside her
    laptop = post({"open": False}, who=MINA)
    check("Mina closes the panel on her laptop; her phone's wide window and every other page open it closed", laptop.status_code == 200 and all(state(get(p, MINA).text) == "closed" for _, p in PAGES))
    check("Noor, signed in at the same time, sees it open everywhere", all(state(get(p, NOOR).text) == "open" for _, p in PAGES))
    post({"open": False}, who=NOOR); post({"open": True}, who=MINA)
    check("Mina opens it again: open for her, closed for Noor, whose own choice she did not change", all(state(get(p, MINA).text) == "open" for _, p in PAGES) and all(state(get(p, NOOR).text) == "closed" for _, p in PAGES))
    post({"open": True}, who=NOOR)
    check("the file is back to nothing stored once both are open", users() == {})

    # ---- 5. the script
    h = get("/").text
    js = r2._PANEL_JS
    scripts = re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", h, re.S)
    mine = [s for s in scripts if "/prefs/panel-open" in s]
    check("the panel script is on the home once, with its save address at the root and no placeholder left", len(mine) == 1 and mine[0] == js and "'/prefs/panel-open'" in js and "@ROOT@" not in js, len(mine))
    for n, p in PAGES[1:]:
        check(f"the panel script (with its save) is on the {n} page too", sum("/prefs/panel-open" in s for s in re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", get(p).text, re.S)) == 1)
    click = js[js.index("B.addEventListener('click'"):js.index("if(X)X.addEventListener")]
    narrow_part, wide_part = click.split("return}\n", 1)
    check("a click on a wide screen pins or unpins, remembers it as the width-crossing default, and saves it; the narrow drawer branch saves nothing",
          "keep(" not in narrow_part and "s.pin=!s.pin;s.peek=false;D=s.pin;apply();keep(s.pin)" in wide_part and js.count("keep(") == 2, click)
    check("nothing else saves: the drawer's close, the scrim, Escape, the hash reveal, the hover peek and the width change never call it",
          js.count("keep(") == 2 and "keep(" not in js[js.index("function peek()"):js.index("B.addEventListener('click'")] and "keep(" not in js[js.index("if(X)X.addEventListener"):]
          and "s.pin=!M.matches&&D;apply()" in js, js.count("keep("))
    check("the save is one POST of {open: boolean} to /prefs/panel-open, same origin with the cookie, one in flight at a time (the last click wins), a failed one is ignored",
          "JSON.stringify({open:v})" in js and "method:'POST'" in js and "keepalive:true" in js and "credentials:'same-origin'" in js and "if(!KB)kflush()" in js and "KB=true" in js and ".then(null,function(){})" in js and "KB=false;kflush()" in js)
    check("the script keeps no state in the browser (no localStorage, sessionStorage, cookie, indexedDB or history call)", re.search(r"localStorage|sessionStorage|document\.cookie|indexedDB|history\.", js) is None)
    check("a narrow screen starts a closed drawer whatever is stored: the pin starts from the page's class only when wide, the drawer starts shut", "pin:D&&!M.matches,open:false" in js)
    if shutil.which("node"):
        for i, s in enumerate(scripts):
            p_ = subprocess.run(["node", "-e", "new (require('vm').Script)(require('fs').readFileSync(0,'utf8'))"], input=s, capture_output=True, text=True, timeout=30)
            check(f"root home: inline script {i + 1} parses", p_.returncode == 0, p_.stderr[:300])
        sim = r"""
const vm=require('vm'),fs=require('fs');const src=fs.readFileSync(0,'utf8');const calls=[];
function P(v){return{then(a,b){const f=a||(x=>x);try{return P(f(v))}catch(e){return P(undefined)}}}}
function mkEl(id){const l={};return{id,_l:l,addEventListener(t,f){(l[t]=l[t]||[]).push(f)},matches(){return false},setAttribute(){},focus(){},contains(){return false},closest(){return null}}}
function run(wide,bodyPin){calls.length=0;const els={};['panel','panel-open','panel-edge','panel-scrim','panel-close'].forEach(i=>els[i]=mkEl(i));
const cls=new Set(bodyPin?['panel-pin']:[]);
const body={classList:{contains:c=>cls.has(c),toggle:(c,on)=>{on?cls.add(c):cls.delete(c)}}};const mm={matches:!wide,addEventListener(t,f){this.f=f}};
const ctx={document:{getElementById:i=>els[i],body,addEventListener(){},querySelector(){return null}},window:{matchMedia:()=>mm,addEventListener(){},fetch:true},location:{hash:''},
fetch:(u,o)=>{calls.push([u,o.method,o.body,o.keepalive]);return P(undefined)},clearTimeout(){},setTimeout(){return 1},decodeURIComponent,SST:k=>k};      // SST: the page head's word lookup (a stub: this run does not read the words)
ctx.window.fetch=ctx.fetch;vm.runInNewContext(src,ctx);const click=()=>els['panel-open']._l.click[0]();return{click,cls,calls,mm,els}}
const out={};
let r=run(true,true);r.click();out.wideClose=[r.calls.slice(),[...r.cls]];r.click();out.wideOpen=r.calls.slice();
r=run(false,true);r.click();out.narrowOpen=[r.calls.slice(),[...r.cls]];r.click();out.narrowClose=r.calls.slice();
r=run(true,false);out.wideStoredClosed=[...r.cls];r.mm.matches=true;r.mm.f();out.crossToNarrow=[...r.cls];r.mm.matches=false;r.mm.f();out.crossBack=[...r.cls];r.click();out.reopened=[...r.cls];
r=run(true,true);r.click();r.mm.matches=true;r.mm.f();r.mm.matches=false;r.mm.f();out.closedByHandThenCrossed=[...r.cls];
process.stdout.write(JSON.stringify(out));"""
        sp = subprocess.run(["node", "-e", sim], input=js, capture_output=True, text=True, timeout=30)
        if sp.returncode != 0: check("the panel script runs in a simulated page (node)", False, sp.stderr[-500:])
        else:
            o = json.loads(sp.stdout)
            check("run: a wide click closes the panel and posts {open:false}, the next opens it and posts {open:true}",
                  o["wideClose"][0] == [["/prefs/panel-open", "POST", '{"open":false}', True]] and "panel-pin" not in o["wideClose"][1]
                  and o["wideOpen"] == [["/prefs/panel-open", "POST", '{"open":false}', True], ["/prefs/panel-open", "POST", '{"open":true}', True]], o["wideClose"])
            check("run: a narrow screen: the button opens the drawer and shuts it, and nothing is posted", o["narrowOpen"][0] == [] and o["narrowOpen"][1] == ["panel-open"] and o["narrowClose"] == [], o["narrowOpen"])
            check("run: a page drawn closed stays unpinned on a wide screen, narrow and back; opened by a click it pins", o["wideStoredClosed"] == [] and o["crossToNarrow"] == [] and o["crossBack"] == [] and o["reopened"] == ["panel-pin"], o)
            check("run: closed by a click, then the width crosses 800 px and back: it stays closed (the choice is the default again)", o["closedByHandThenCrossed"] == [], o["closedByHandThenCrossed"])

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
