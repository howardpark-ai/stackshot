"""Scenario test for the side panel's per-person settings on the board's pages at the root, kept on the server: whether it is open or closed on a wide screen, and the order of its sections
(uiprefs.py panel_open and panel_order, ui/render.py apply_panel_open, apply_panel_order, _PANEL_JS and _PORDER_JS, the /prefs/panel-open and /prefs/panel-order routes, _panel_ordered in server.py):
fixture data, the routes through Starlette's test client, no live store, no network. People and addresses are made up. The suite is the two former suites, panel_open and panel_order,
one after the other on one fixture (the open part first, the order part second), every check kept.

Part 1, whether the panel is open (panel_open):
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

Part 2, the order of the sections (panel_order):
  * uiprefs: normalize (unknown and repeated names dropped, a section left out goes back after its default predecessor, a non-list is the default), set / reset, a default
    order is stored as no entry, one person's order is not another's, a file that does not parse is moved aside and the settings start empty, no temporary file is left;
  * the page: every root page that carries the panel draws the five sections (Projects last) with a grip each, no reset control, the move menu and the live region; a person who
    never moved a section gets the default order; with a saved order the home (a kept draw served to everyone), an item page, a project page, Landed and Search come in that
    order, and everything else in the page unchanged (same shell and block fingerprints, same set of sections); a visitor not signed in and
    another person get the default order; the saved order survives a section that is gone (dropped) and one that is new (placed by default);
  * the save route (POST /prefs/panel-order): refused without sign-in (403), from a foreign origin or none (403), without a JSON content type (415), with a body that is
    too long (413), not JSON (400), not an object (400), an `order` that is not a list of short strings (400), too many names (400), neither key (400); a good body answers the whole
    order; unknown names are ignored; a section left out keeps its default place; {"reset": true} puts the default back; GET is 405;
  * the scenario: Mina moves Runners to the top on her laptop and opens the board on her phone, where it is already in her order; Noor, signed in beside her, sees the default;
    Mina moves the sections back and both see the default;
  * no Reset order: the button, its row and its script are gone from every page, a saved order is still shown on load and still movable, and the default order needs no control;
  * the gap: under each of the five section titles the first block takes the same 8 px (the cascade over the page's own style, no rule that zeroes the top margin outranks the gap rule);
  * the script: each inline script parses (node, when present), and every address it writes is at the root.

    tests/run-suite panel_prefs        → exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="ppref-"); T = pathlib.Path(tmp)
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
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.routes import ui_api as _rt_ui
from stackshot.web.auth import signin as _signin
from stackshot.web import board_home as _web_board_home
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
from stackshot.core import config as _cfg; from stackshot.web import app as _wapp       # the order part's (_wapp drops the kept home draw when it changes the Anchor hub)
DEFAULT = ["machines", "runners", "anchorhub", "audit-panel", "projects-panel"]
UI = up.path()
COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
SAME = {"Origin": BOARD}
JSON_H = {**SAME, "Content-Type": "application/json"}
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))


def part_open():
    """Part 1: whether the panel is open (the former panel_open suite)."""
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
    PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("projects", "/projects"), ("closed", "/closed"), ("audits", "/audits"), ("search", "/search?q=item")]
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
            return asyncio.run(_rt_ui.panel_open_save(Request(scope, receive))), len(reads)
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


def part_order():
    """Part 2: the order of the sections (the former panel_order suite). Starts from the files and caches part 1 left, as a run of its own would find them."""
    UI.unlink(missing_ok=True)
    for f in UI.parent.glob("ui-prefs.json.bad-*"): f.unlink()
    (T / "state/anchor-hub").mkdir(parents=True)
    (T / "state/anchor-hub/status.json").write_text(json.dumps({"receivers": {"hook-a": {"ok": True, "checked": "2026-03-20 10:00:00"}}}))     # the Anchor hub section is drawn when a receiver has reported
    _wapp._board_home_drop()
    NORESET = re.compile(r'panel-reset|Reset order|class="prow"|showReset')       # the removed control: its id, its words, its row and its script function

    # ---- 1. uiprefs
    N = up.normalize
    check("normalize: a whole default order stays", N(DEFAULT) == DEFAULT and up.is_default(N(DEFAULT)))
    check("normalize: not a list (None, a string, a dict, a number) is the default order", all(N(x) == DEFAULT for x in (None, "runners", {"a": 1}, 7)))
    check("normalize: unknown, repeated and non-string names are dropped, the rest keep their order", N(["audit-panel", "nope", "audit-panel", "runners", 3, None]) == ["machines", "audit-panel", "projects-panel", "runners", "anchorhub"],
          N(["audit-panel", "nope", "audit-panel", "runners", 3, None]))
    check("normalize: a section left out goes back right after its default predecessor", N(["runners", "machines", "audit-panel"]) == ["runners", "anchorhub", "machines", "audit-panel", "projects-panel"]
          and N(["audit-panel", "anchorhub"]) == ["machines", "runners", "audit-panel", "projects-panel", "anchorhub"], (N(["runners", "machines", "audit-panel"]), N(["audit-panel", "anchorhub"])))
    check("normalize: one name only: the others are placed by default around it", N(["audit-panel"]) == DEFAULT and N(["anchorhub"]) == DEFAULT
          and N(["machines"]) == DEFAULT, N(["audit-panel"]))
    check("normalize: a section that comes first by default but is left out goes to the front", N(["runners", "anchorhub", "audit-panel"]) == DEFAULT
          and N(["anchorhub", "audit-panel", "runners"]) == ["machines", "anchorhub", "audit-panel", "projects-panel", "runners"], N(["anchorhub", "audit-panel", "runners"]))
    check("normalize: every result holds each section once", all(sorted(N(x)) == sorted(DEFAULT) for x in ([], ["x"], ["runners"] * 5, DEFAULT[::-1])))
    check("no file yet: everyone has the default order, nobody signed in too", up.panel_order(MINA) == DEFAULT and up.panel_order("") == DEFAULT and not UI.exists())
    check("set_panel_order returns the whole order and saves it", up.set_panel_order(MINA, ["runners"]) == DEFAULT and not up.is_default(up.set_panel_order(MINA, ["audit-panel", "machines"])))
    check("…one person's order is not another's", up.panel_order(NOOR) == DEFAULT and up.panel_order(MINA)[0] == "audit-panel")
    up.set_panel_order(NOOR, ["anchorhub", "runners", "machines", "audit-panel"])
    check("two people, two orders, one file", json.loads(UI.read_text())["users"] == {MINA: {"panel_order": up.panel_order(MINA)}, NOOR: {"panel_order": ["anchorhub", "runners", "machines", "audit-panel", "projects-panel"]}}, UI.read_text())
    up.set_panel_order(MINA, DEFAULT)
    check("saving the default order stores no entry (a person is 'on the default' only until a real choice)", MINA not in json.loads(UI.read_text())["users"] and up.panel_order(MINA) == DEFAULT)
    up.reset_panel_order(NOOR)
    check("reset removes the entry and leaves a file that parses", json.loads(UI.read_text()) == {"users": {}} and up.panel_order(NOOR) == DEFAULT)
    check("no temporary file is left beside it", not list(UI.parent.glob("*.tmp")), list(UI.parent.glob("*")))
    UI.write_text("{not json", encoding="utf-8")
    check("a file that does not parse: the default order, the file moved aside, a fresh start", up.panel_order(MINA) == DEFAULT and not UI.exists() and len(list(UI.parent.glob("ui-prefs.json.bad-*"))) == 1)
    UI.write_text("[1, 2]", encoding="utf-8")
    check("a file that is not an object: moved aside too", up.panel_order(MINA) == DEFAULT and len(list(UI.parent.glob("ui-prefs.json.bad-*"))) == 2)
    UI.write_text(json.dumps({"users": {MINA: {"panel_order": "runners"}, NOOR: "x"}}), encoding="utf-8")
    check("an entry of the wrong shape reads as the default", up.panel_order(MINA) == DEFAULT and up.panel_order(NOOR) == DEFAULT)
    UI.unlink()
    for f in UI.parent.glob("ui-prefs.json.bad-*"): f.unlink()
    # merge: the page sends the sections it shows; a section it does not draw (the Anchor hub, before a receiver has reported) keeps its stored place
    M = up.merge
    HID_STORED = ["anchorhub", "audit-panel", "machines", "runners", "projects-panel"]
    check("merge: the names sent take, in the order sent, the places they hold; the one not sent keeps its place",
          M(HID_STORED, ["runners", "audit-panel", "machines"]) == ["anchorhub", "runners", "audit-panel", "machines", "projects-panel"], M(HID_STORED, ["runners", "audit-panel", "machines"]))
    check("merge: a whole order sent replaces the stored one; nothing usable sent changes nothing; unknown and repeated names are dropped",
          M(HID_STORED, DEFAULT[::-1]) == DEFAULT[::-1] and M(HID_STORED, []) == HID_STORED and M(HID_STORED, "runners") == HID_STORED and M(HID_STORED, ["x", 3, None]) == HID_STORED
          and M(HID_STORED, ["runners", "runners", "nope", "audit-panel"]) == ["anchorhub", "runners", "machines", "audit-panel", "projects-panel"])
    check("merge: a stored order that is missing a section or is garbage is made whole first", M(["audit-panel"], ["runners", "machines"]) == ["runners", "machines", "anchorhub", "audit-panel", "projects-panel"] and M("garbage", ["audit-panel", "runners"]) == ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"],
          (M(["audit-panel"], ["runners", "machines"]), M("garbage", ["audit-panel", "runners"])))
    up.set_panel_order(MINA, HID_STORED)
    got = up.set_panel_order(MINA, ["runners", "audit-panel", "machines"])       # the page had no Anchor hub in it
    check("a save from a page without the Anchor hub keeps the Anchor hub's stored place (first), on disk too", got == ["anchorhub", "runners", "audit-panel", "machines", "projects-panel"]
          and json.loads(UI.read_text())["users"][MINA]["panel_order"] == got and up.panel_order(MINA) == got, (got, UI.read_text()))
    up.reset_panel_order(MINA)
    # the write: the temporary file is flushed to disk before it replaces the file, and is removed when the save fails
    events = []; real_fsync, real_replace = os.fsync, os.replace
    def spy_fsync(fd): events.append("fsync"); return real_fsync(fd)
    def spy_replace(a, b): events.append("replace"); return real_replace(a, b)
    os.fsync, os.replace = spy_fsync, spy_replace
    try: up.set_panel_order(MINA, ["runners", "machines"])
    finally: os.fsync, os.replace = real_fsync, real_replace
    check("a save fsyncs the temporary file before os.replace puts it in place", events == ["fsync", "replace"], events)
    before = UI.read_text()
    def failing_replace(a, b): raise OSError(28, "No space left on device")
    os.replace = failing_replace
    try:
        try: up.set_panel_order(MINA, ["audit-panel", "machines"]); failed = False
        except OSError: failed = True
    finally: os.replace = real_replace
    check("a failed save raises, leaves the file as it was and removes its temporary file", failed and UI.read_text() == before and not list(UI.parent.glob("*.tmp")), list(UI.parent.glob("*")))
    def failing_fsync(fd): raise OSError(5, "Input/output error")
    os.fsync = failing_fsync
    try:
        try: up.reset_panel_order(MINA); failed = False
        except OSError: failed = True
    finally: os.fsync = real_fsync
    check("…an fsync that fails does too (nothing replaced, no temporary file)", failed and UI.read_text() == before and not list(UI.parent.glob("*.tmp")))
    # a read error other than "no such file" is not an empty file: other people's orders must never be dropped
    up.reset_panel_order(MINA); up.set_panel_order(NOOR, ["audit-panel", "runners"]); kept = UI.read_text()
    real_read = pathlib.Path.read_text
    def denied_read(self, *a, **k):
        if self == UI: raise PermissionError(13, "Permission denied")
        return real_read(self, *a, **k)
    pathlib.Path.read_text = denied_read
    try:
        try: up.set_panel_order(MINA, ["runners"]); raised = False
        except OSError: raised = True
        try: up.reset_panel_order(NOOR); raised_reset = False
        except OSError: raised_reset = True
        unread = up.panel_order(NOOR)
    finally: pathlib.Path.read_text = real_read
    check("an unreadable settings file: a save and a reset raise, a read gives the default order", raised and raised_reset and unread == DEFAULT, (raised, raised_reset, unread))
    check("…and nothing was dropped: the file is as it was, not moved aside, no temporary file", UI.read_text() == kept and not list(UI.parent.glob("ui-prefs.json.bad-*")) and not list(UI.parent.glob("*.tmp")))
    UI.unlink()

    # ---- 2. the page
    PAGES = [("home", "/"), ("item", "/items/a1"), ("project", "/projects/alpha"), ("landed", "/closed"), ("search", "/search?q=item")]
    def sections(h):
        """The ids of the panel's sections in the order the page has them (the wrapped blocks), and the ids of the <section> elements inside the aside."""
        i = h.index('<aside id="panel"'); a = h[i:h.index("</aside>", i)]
        return re.findall(r"<!--ps:([a-z-]+)-->", a), re.findall(r'<section id="([a-z-]+)"', a)
    def shape(h):
        """The page with the sections taken out, in a fixed order: what must not change when only the order does."""
        secs = {m.group(1): m.group(0) for m in r2._PSEC_RX.finditer(h)}
        return r2._PSEC_RX.sub("", h), secs
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
        def get(path, who=MINA):
            c.cookies.clear()
            if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
            return c.get(path, follow_redirects=False)
        def post(body, who=MINA, headers=JSON_H, raw=None, path="/prefs/panel-order"):
            c.cookies.clear()
            if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
            return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers, follow_redirects=False)

        base = {n: get(p).text for n, p in PAGES}
        for n, h in base.items():
            s1, s2 = sections(h)
            check(f"default: root {n} page has the five sections in the default order (Projects last), wrapped and as elements", s1 == DEFAULT and s2 == DEFAULT and s1[-1] == "projects-panel", (s1, s2))
            check(f"default: root {n} page has a grip on each section, the move menu with its four moves, the live region, and no reset control",
                  len(re.findall(r'<button type="button" class="pgrip" id="pgrip-[a-z-]+" data-sec="', h)) == 5 and h.count('role="menuitem"') == 4 and 'id="panel-live"' in h and 'role="status" aria-live="polite"' in h
                  and not NORESET.search(h), (h.count("pgrip"), h.count("menuitem")))
        h = base["home"]
        check("each grip names its section and says it opens a menu", all(f'data-sec="{k}" data-label="{lab}" aria-label="Move {lab} section" aria-haspopup="menu"' in h for k, lab in
              (("machines", "Machines"), ("runners", "Runners"), ("anchorhub", "Anchor hub"), ("audit-panel", "Audit"), ("projects-panel", "Projects"))))
        check("the menu offers Move up, Move down, Move to top, Move to bottom (menuitems)", re.findall(r'data-act="(\w+)"[^>]*>([^<]+)<', h) == [("up", "Move up"), ("down", "Move down"), ("top", "Move to top"), ("bottom", "Move to bottom")])
        check("the grip is beside the fold, in its section and outside the <summary>, so the summary's name stays the title; it has a stable id", re.search(
            r'<section id="runners"><details class="fold" data-fold="runners" open><summary><h2 class="hdr">Runners</h2></summary>.*?</details><button type="button" class="pgrip" id="pgrip-runners" data-sec="runners"', h, re.S) is not None
              and not re.search(r"<summary>(?:(?!</summary>).)*pgrip", h, re.S) and all(f'id="pgrip-{k}"' in h for k in DEFAULT))
        check("the main column's folds carry no grip (only the panel's five)", h.count('class="pgrip"') == 5)

        # a saved order, as the page shows it
        r = post({"order": ["audit-panel", "runners"]})
        ORDER = ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"]      # the two names sent take the places they held (runners 2nd, audit 4th); the others stay
        check("save: a good body answers the whole order and that it is not the default", r.status_code == 200 and r.json() == {"order": ORDER, "default": False}, (r.status_code, r.text))
        check("…and it is on disk for that person", json.loads(UI.read_text())["users"] == {MINA: {"panel_order": ORDER}}, UI.read_text())
        ordered = {n: get(p).text for n, p in PAGES}
        for n, h in ordered.items():
            s1, s2 = sections(h)
            check(f"saved: root {n} page has the sections in the saved order, in the markup and as elements", s1 == ORDER and s2 == ORDER, (s1, s2))
            check(f"saved: root {n} page has no reset control either (a saved order is shown as it is, moved by the grips)", not NORESET.search(h))
            a, b = shape(base[n]), shape(h)
            norm = lambda t: re.sub(r'<meta name="stackshot-rendered" content="[^"]*">|data-ts="[0-9]+"|showing the board as of [^<]*?(?=\. Retrying)', "", t)       # the last: the page's own draw time, to the minute, so two draws a minute apart (a run across :00) differ in it alone
            check(f"saved: root {n} page is the default page with only the sections moved (nothing else differs)", norm(a[0]) == norm(b[0]) and {k: norm(v) for k, v in a[1].items()} == {k: norm(v) for k, v in b[1].items()}, n)
        check("saved: the home's shell and block fingerprints are the default page's (the in-place update keeps working)", all(
            re.search(rf'<meta name="stackshot-{k}" content="([^"]*)">', ordered["home"]).group(1) == re.search(rf'<meta name="stackshot-{k}" content="([^"]*)">', base["home"]).group(1) for k in ("shell", "blocks")))
        check("saved: the kept draw of the root home is still in the default order (the order is put in per person on the way out)", sections(_web_board_home._BOARD_HOME["html"])[0] == DEFAULT)
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[MINA]); rr = c.get("/")
        check("saved: Content-Length matches the body served", int(rr.headers["content-length"]) == len(rr.content), (rr.headers["content-length"], len(rr.content)))
        check("another signed-in person gets the default order", sections(get("/", NOOR).text)[0] == DEFAULT)
        check("nobody signed in (auth off) gets the default order", sections(get("/", None).text)[0] == DEFAULT)

        # a saved order from before a section was added or removed
        UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["retired-section", "audit-panel", "machines", "retired-section", "runners"]}}}), encoding="utf-8")   # anchorhub is "new"
        check("a section gone from the page is dropped, a new one placed after its default predecessor", sections(get("/").text)[0] == ["audit-panel", "projects-panel", "machines", "runners", "anchorhub"], sections(get("/").text)[0])
        UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["runners", "machines", "anchorhub", "audit-panel"]}}}), encoding="utf-8")      # an order saved before Projects existed: four sections, the person's own
        h_old = get("/").text
        check("an order saved before the Projects section: it renders whole, in the person's order, with Projects last (it follows Audit, which is last there), as one section and one grip",
              sections(h_old)[0] == sections(h_old)[1] == ["runners", "machines", "anchorhub", "audit-panel", "projects-panel"] and h_old.count('class="pgrip"') == 5 and not NORESET.search(h_old), sections(h_old))
        UI.write_text(json.dumps({"users": {MINA: {"panel_order": "garbage"}}}), encoding="utf-8")
        check("a saved order of the wrong shape is the default", sections(get("/").text)[0] == DEFAULT)
        UI.write_text("{broken", encoding="utf-8")
        rb = get("/")
        check("an unreadable file: the page still comes, in the default order", rb.status_code == 200 and sections(rb.text)[0] == DEFAULT)
        UI.unlink(missing_ok=True)
        for f in UI.parent.glob("ui-prefs.json.bad-*"): f.unlink()

        # a page that draws no Anchor hub (no receiver has reported): its place is empty, the others move
        os.rename(T / "state/anchor-hub/status.json", T / "state/anchor-hub/status.off"); _wapp._board_home_drop()
        UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["audit-panel", "anchorhub", "machines", "runners"]}}}), encoding="utf-8")
        h_ = get("/").text
        check("no Anchor hub drawn: four sections in the saved order, the empty place wrapped, the grips four", sections(h_)[1] == ["audit-panel", "projects-panel", "machines", "runners"] and sections(h_)[0] == ["audit-panel", "projects-panel", "anchorhub", "machines", "runners"]
              and h_.count('class="pgrip"') == 4 and not NORESET.search(h_), (sections(h_), h_.count('class="pgrip"')))
        UI.write_text(json.dumps({"users": {MINA: {"panel_order": ["anchorhub", "machines", "runners", "audit-panel"]}}}), encoding="utf-8")
        h_ = get("/").text
        check("…an order that differs only in where the empty place sits is drawn the same way", sections(h_)[1] == ["machines", "runners", "audit-panel", "projects-panel"] and not NORESET.search(h_))
        UI.unlink(); os.rename(T / "state/anchor-hub/status.off", T / "state/anchor-hub/status.json"); _wapp._board_home_drop()

        # ---- 3. the save route
        GOOD = {"order": ["runners", "machines"]}
        r = post(GOOD, who=None)
        check("save: not signed in is refused (403) and nothing is written", r.status_code == 403 and not UI.exists(), (r.status_code, r.text[:80]))
        r = post(GOOD, headers={"Origin": "https://evil.example.net", "Content-Type": "application/json"})
        check("save: from a foreign origin is refused (403)", r.status_code == 403 and not UI.exists(), r.status_code)
        r = post(GOOD, headers={"Content-Type": "application/json"})
        check("save: with no Origin or Referer is refused (403)", r.status_code == 403 and not UI.exists(), r.status_code)
        r = post(GOOD, headers={**SAME, "Content-Type": "text/plain"})
        check("save: not JSON by its content type is refused (415)", r.status_code == 415 and not UI.exists(), r.status_code)
        r = post(None, raw="x" * 5000)
        check("save: a body over 4 KB is refused (413)", r.status_code == 413 and not UI.exists(), r.status_code)
        bad = {"not json": dict(raw="{nope"), "an array": dict(body=["runners"]), "a string": dict(body="runners"), "null": dict(body=None),
               "neither key": dict(body={"colour": "blue"}), "order null": dict(body={"order": None}), "order a string": dict(body={"order": "runners"}),
               "order a dict": dict(body={"order": {"runners": 1}}), "a number in the list": dict(body={"order": ["runners", 3]}), "a null in the list": dict(body={"order": [None]}),
               "a nested list": dict(body={"order": [["runners"]]}), "a name too long": dict(body={"order": ["x" * 41]}), "too many names": dict(body={"order": ["runners"] * 33}),
               "reset not true": dict(body={"reset": "yes"}), "reset false and no order": dict(body={"reset": False})}
        for what, kw in bad.items():
            r = post(kw.get("body"), raw=kw.get("raw"))
            check(f"save: {what} is refused (400) and nothing is written", r.status_code == 400 and not UI.exists(), (r.status_code, r.text[:80]))
        r = post({"order": ["bogus", "runners", "machines", "audit-panel", "anchorhub", "bogus", "machines"]})
        check("save: unknown names are ignored, a repeated name counts once", r.status_code == 200 and r.json()["order"] == ["runners", "machines", "audit-panel", "anchorhub", "projects-panel"], r.text)
        r = post({"order": ["anchorhub"]})
        check("save: a section left out keeps its stored place: one name sent changes nothing", r.status_code == 200 and r.json()["order"] == ["runners", "machines", "audit-panel", "anchorhub", "projects-panel"], r.text)
        r = post({"order": ["anchorhub", "runners", "machines", "audit-panel", "projects-panel"]})
        check("save: a whole order sent replaces the stored one…", r.status_code == 200 and r.json()["order"] == ["anchorhub", "runners", "machines", "audit-panel", "projects-panel"] and r.json()["default"] is False, r.text)
        r = post({"order": DEFAULT})
        check("…and an order equal to the default stores no entry", r.status_code == 200 and r.json()["default"] is True and (not UI.exists() or MINA not in json.loads(UI.read_text())["users"]), UI.read_text() if UI.exists() else "")
        post({"order": ["audit-panel", "runners"]})
        r = post({"order": ["bogus", "worse"]})
        check("save: only unknown names: the stored order stays as it is", r.status_code == 200 and r.json()["order"] == ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"], r.text)
        r = post({"order": []})
        check("save: an empty list leaves the stored order as it is (a reset is {\"reset\": true})", r.status_code == 200 and r.json()["order"] == ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"], r.text)
        post({"reset": True})
        r = post({"order": ["anchorhub", "audit-panel", "runners", "machines"], "extra": "ignored"})
        check("save: an extra key is ignored", r.status_code == 200 and r.json()["order"] == ["anchorhub", "audit-panel", "runners", "machines", "projects-panel"], r.text)
        r = post({"reset": True})
        check("reset: back to the default, the entry removed", r.status_code == 200 and r.json() == {"order": DEFAULT, "default": True} and MINA not in json.loads(UI.read_text())["users"], r.text)
        r = post({"order": ["audit-panel"], "reset": True})
        check("reset wins over an order in the same body", r.status_code == 200 and r.json()["order"] == DEFAULT, r.text)
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[MINA])
        check("GET on the save route is not served a page (405)", c.get("/prefs/panel-order").status_code in (404, 405))
        r = post({"order": ["runners"]}, headers={"Referer": BOARD + "/", "Content-Type": "application/json"})
        check("save: a Referer from the board's own page is accepted when the browser sent no Origin", r.status_code == 200, r.status_code)
        post({"reset": True})
        # the page drew no Anchor hub (three sections): its stored place is kept
        up.set_panel_order(MINA, HID_STORED)
        r = post({"order": ["runners", "audit-panel", "machines"]})
        check("save: a page that shows four sections sends four names; the fifth section keeps its stored place", r.status_code == 200 and r.json()["order"] == ["anchorhub", "runners", "audit-panel", "machines", "projects-panel"]
              and up.panel_order(MINA) == ["anchorhub", "runners", "audit-panel", "machines", "projects-panel"], r.text)
        post({"reset": True})
        # a settings file that cannot be read: a clean refusal, the file untouched, the page still served
        up.set_panel_order(NOOR, ["audit-panel", "runners"]); kept = UI.read_text()
        pathlib.Path.read_text = denied_read
        try:
            r = post({"order": ["runners", "machines"]}); r2_ = post({"reset": True}); pg = get("/")
        finally: pathlib.Path.read_text = real_read
        check("save: an unreadable settings file answers 503 'could not be saved' (the script shows 'not saved'), also for a reset", r.status_code == 503 and r2_.status_code == 503 and "could not be saved" in r.text, (r.status_code, r2_.status_code, r.text))
        check("…nothing was dropped (no empty file written, other people's orders kept) and the page still comes in the default order", UI.read_text() == kept and pg.status_code == 200 and sections(pg.text)[0] == DEFAULT)
        post({"reset": True}, who=NOOR)
        # the size is judged from Content-Length before the body is read; a body with none is cut off as it arrives
        import asyncio
        from starlette.requests import Request
        def raw_post(length, chunks):
            hs = [(b"host", b"board.example.org"), (b"origin", BOARD.encode()), (b"content-type", b"application/json"), (b"cookie", f"{_signin._UI_COOKIE}={COOKIE[MINA]}".encode())]
            if length is not None: hs.append((b"content-length", str(length).encode()))
            scope = {"type": "http", "method": "POST", "path": "/prefs/panel-order", "raw_path": b"/prefs/panel-order", "query_string": b"", "headers": hs, "scheme": "https",
                     "server": ("board.example.org", 443), "client": ("203.0.113.9", 5000), "http_version": "1.1", "root_path": ""}
            reads = []
            async def receive():
                k = len(reads); reads.append(k)
                if k < len(chunks): return {"type": "http.request", "body": chunks[k], "more_body": k < len(chunks) - 1}
                return {"type": "http.disconnect"}
            return asyncio.run(_rt_ui.panel_order_save(Request(scope, receive))), len(reads)
        resp, nread = raw_post(10_000_000, [b"x" * 100])
        check("save: a Content-Length over 4 KB is refused (413) before any of the body is read", resp.status_code == 413 and nread == 0, (resp.status_code, nread))
        resp, nread = raw_post("12abc", [b"{}"])
        check("save: a Content-Length that is not a number is refused (400) before the body is read", resp.status_code == 400 and nread == 0, (resp.status_code, nread))
        resp, nread = raw_post(None, [b"x" * 3000, b"x" * 3000, b"x" * 3000])
        check("save: a body with no Content-Length is cut off as it passes 4 KB (413), the rest not read", resp.status_code == 413 and nread == 2, (resp.status_code, nread))
        resp, nread = raw_post(None, [b'{"order": ["runners", ', b'"machines"]}'])
        check("save: a small chunked body is read whole and saved", resp.status_code == 200 and json.loads(resp.body)["order"][:2] == ["runners", "machines"], resp.body)
        post({"reset": True})

        # ---- 4. the scenario: Mina on her laptop and her phone, Noor beside her
        laptop = post({"order": ["runners", "audit-panel", "machines", "anchorhub"]}, who=MINA)
        phone_home, phone_item = get("/", MINA).text, get("/items/a1", MINA).text
        check("Mina moves Runners to the top on her laptop; opened on her phone the board is already in her order",
              laptop.status_code == 200 and sections(phone_home)[0] == sections(phone_item)[0] == ["runners", "audit-panel", "machines", "anchorhub", "projects-panel"]
              and not NORESET.search(phone_home) and not NORESET.search(phone_item))
        check("Noor, signed in at the same time, sees the default order", sections(get("/", NOOR).text)[0] == DEFAULT)
        post({"order": ["machines", "anchorhub", "runners", "audit-panel"]}, who=NOOR)
        check("Noor's own move changes nothing for Mina", sections(get("/", MINA).text)[0] == ["runners", "audit-panel", "machines", "anchorhub", "projects-panel"] and sections(get("/", NOOR).text)[0] == ["machines", "anchorhub", "runners", "audit-panel", "projects-panel"])
        post({"order": DEFAULT}, who=MINA)
        check("Mina moves the sections back from her phone: the default everywhere for her, Noor's order stays", sections(get("/", MINA).text)[0] == DEFAULT
              and sections(get("/", NOOR).text)[0] == ["machines", "anchorhub", "runners", "audit-panel", "projects-panel"])
        post({"reset": True}, who=NOOR)

        # ---- 5. the script
        h = get("/").text
        scripts = re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", h, re.S)
        mine = [s for s in scripts if "panel-order" in s]
        check("the order script is on the root home, once, and writes its address at the root", len(mine) == 1 and "'/prefs/panel-order'" in mine[0] and "__DEF__" not in mine[0], len(mine))
        js = mine[0]
        check("the Tab key in the move menu puts the focus back on the grip, as Escape does (closeMenu(true))", re.search(r"k==='Tab'\)closeMenu\(true\)", js) is not None and re.search(r"k==='Escape'\).{0,80}closeMenu\(true\)", js, re.S) is not None)
        check("the order script no longer closes the menu or cancels a drag on the live update's swap (the update waits instead)", "stackshot:swapped" not in js and "data-pbusy" in js and "removeAttribute('data-pbusy')" in js, js.count("swapped"))
        live_js = r2._LIVE_JS; busy_fn = live_js[live_js.index("function busy()"):live_js.index("function draw()")]
        check("the live update is busy while the move menu is open or a drag is on (it keeps its 'newer board' state and retries), and fires 'swapped' only when a block was replaced",
              "#panel[data-pbusy]" in busy_fn and "#panel-menu:not([hidden])" in busy_fn and "if(did)document.dispatchEvent(new Event('stackshot:swapped'))" in live_js and "did=true" in live_js
              and live_js.count("stackshot:swapped") == 1, busy_fn)
        css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", h, re.S))
        check("the panel's first-section style no longer rests on :first-of-type (a hidden first section would keep the border); the first visible one is styled",
              "#panel>section:first-of-type" not in css and re.search(r"#panel>section:not\(\[hidden\][^{]*\)~section:not\(\[hidden\][^{]*\)\{--pt:14px;border-top:1px solid", css) is not None)
        check("…its default order is the server's", '["machines", "runners", "anchorhub", "audit-panel", "projects-panel"]' in mine[0])

        # ---- 6. no Reset order: the button is gone from the page, the script and the style; the grips still move every section
        GONE = r"panel-reset|showReset|reset:true|Order reset|Reset order"
        check("the order script has no reset: no button looked up, no show / hide, no {reset:true} sent, no announcement", not re.search(GONE, js), re.findall(GONE, js))
        check("…and it still has what moves a section: the drag, the menu's four moves, the live announcement and the save",
              all(t in js for t in ("function place(", "function act(", "function openMenu(", "function moved(", "say(SST('panel.moved',{label:label(id)", "save({order:o})", "/prefs/panel-order")), js[:80])
        check("the style has no rule for the removed row or button", not re.search(r"\.prow\b|panel-reset", css) and not re.search(GONE, r2._PORDER_CSS))
        check("the default order is drawn with every grip and no control to get back to it", sections(get("/").text)[0] == DEFAULT and get("/").text.count('class="pgrip"') == 5)
        post({"order": ["audit-panel", "runners"]})
        mv = get("/").text
        check("…with an order saved the sections come in it, each with its grip and the menu, and nothing about a reset",
              sections(mv)[0] == ["machines", "audit-panel", "anchorhub", "runners", "projects-panel"] and mv.count('class="pgrip"') == 5 and mv.count('role="menuitem"') == 4 and not NORESET.search(mv))
        post({"order": DEFAULT})

        # ---- 7. the gap under every section title: the cascade over the page's own style, read without a browser
        def flat_rules(text):
            """[(selector, declarations, position)] of the style: @media / @supports flattened (a rule inside one counts as if it applied, the stricter reading), other at-rules dropped."""
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S); out = []
            def walk(t):
                i = 0
                while True:
                    j = t.find("{", i)
                    if j < 0: return
                    d, k = 1, j + 1
                    while k < len(t) and d:
                        d += (t[k] == "{") - (t[k] == "}"); k += 1
                    sel, body = t[i:j].strip(), t[j + 1:k - 1]
                    if sel.startswith(("@media", "@supports")): walk(body)
                    elif not sel.startswith("@"):
                        for one in sel.split(","): out.append((one.strip(), body, len(out)))
                    i = k
            walk(text); return out
        def spec(sel):
            """(ids, classes / attributes / pseudo-classes, tags) of a selector, :not() / :has() / :is() counting their arguments."""
            ids = len(re.findall(r"#[\w-]+", sel))
            cls = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|(?<!:):(?!not\b|has\b|is\b|where\b)[a-z-]+", sel))
            tags = len(re.findall(r"(?:^|[\s>+~(])[a-z][\w-]*", sel))
            return (ids, cls, tags)
        def top_margin(body):
            """The top margin the declarations set (the last of `margin` / `margin-top` wins), or None."""
            v = None
            for prop, val in re.findall(r"(?:^|;)\s*(margin(?:-top)?)\s*:\s*([^;!]+)", body.strip()):
                v = val.split()[0] if val.split() else v
            return v
        def reaches(sel, sid, el):
            """Does `sel` match `el` = (tag, id, classes) as the first element after the summary of the fold in section `sid` of the panel? Only the ancestors the panel's rules use are read;
            a selector with any other ancestor, a state or a pseudo-element is taken as not matching, and a child of something else than the fold (the cards inside a block) is not the first block."""
            tag, eid, cls = el
            if "::" in sel or re.search(r":(hover|focus|active|checked|disabled|first-of-type|last-child)", sel): return False
            toks = [t for t in re.split(r"\s*([>+~])\s*|\s+", sel.strip()) if t]
            if not toks: return False
            if toks[-1] == "*":
                if toks[-3:-1] != ["summary", "+"]: return False
                anc = toks[:-3]
            else:
                m = re.fullmatch(r"([a-z][\w-]*)?((?:[#.][\w-]+)*)", toks[-1])
                if not m or (m.group(1) and m.group(1) != tag): return False
                if any((x[0] == "#" and x[1:] != eid) or (x[0] == "." and x[1:] not in cls) for x in re.findall(r"[#.][\w-]+", m.group(2))): return False
                anc = toks[:-1]
                if anc[-1:] in (["+"], ["~"]): return False
                if anc[-1:] == [">"]:
                    if anc[-2:-1] != ["details.fold"]: return False
                    anc = anc[:-1]
            return all(a in {"#panel", "section", f"#{sid}", "details", "details.fold", ".fold", ">", "+", "~"} for a in anc)
        # the first element after the summary, per section, as the page draws it, and the other forms the same section takes (the recycle line over the Machines cards, the note over the Runners cards)
        firsts = {}
        for sid in DEFAULT:
            m = re.search(rf'<section id="{sid}"><details class="fold"[^>]*><summary>.*?</summary>\s*<(\w+)([^>]*)>', get("/").text, re.S)
            if m:
                at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2))); firsts[sid] = [(m.group(1), at.get("id", ""), at.get("class", "").split())]
        for sid, more in (("machines", [("div", "", ["matrix"]), ("p", "recycle", ["mnote"])]), ("runners", [("p", "", ["mnote"]), ("div", "", ["rlist"])]),
                          ("anchorhub", [("div", "", ["matrix", "rcvs"])]), ("audit-panel", [("div", "audit", []), ("div", "ghcalls", ["pc", "ghc"])])):
            firsts.setdefault(sid, []).extend(more)
        rules = flat_rules(css)
        gap = next((r for r in rules if r[0] == "#panel details.fold>summary+*"), None)
        check("the gap rule is there: the first block after a section title in the panel takes 8px, unforced", gap is not None and top_margin(gap[1]) == "8px" and "!important" not in gap[1], gap)
        if gap:
            bad, lost = [], {}
            for sid, els in firsts.items():
                for el in els:
                    win = None
                    for sel, body, pos in rules:
                        v = top_margin(body)
                        if v is None or not reaches(sel, sid, el): continue
                        key = ("!important" in body, spec(sel), pos)
                        if win is None or key > win[0]: win = (key, v, sel)
                        if v in ("0", "0px") and key > (False, spec(gap[0]), gap[2]): bad.append((sid, el, sel))
                    if not win or win[1] != "8px": lost[f"{sid}:{el}"] = win
            check("no rule that zeroes the top margin of the first block under a section title outranks the gap rule", not bad, bad)
            check("the same 8px under all five titles, whichever block is first (the gap rule wins the top margin each time)", not lost and all(firsts.values()), lost)
            check("…and the five sections are the panel's five", set(firsts) == set(DEFAULT))
            check("the panel's matrix rules leave the top margin alone (the whole-margin `margin:0` is what hid the gap, and the grip sat on the first card)",
                  not any(top_margin(b) in ("0", "0px") for sel, b, _ in rules if "#panel" in sel and ".matrix" in sel))

        # ---- 8. the section titles are in the text colour (--fg), not the muted one; the grips stay muted; size and capitals are as they were
        def color_of(body):
            v = re.findall(r"(?:^|;)\s*color\s*:\s*([^;!]+)", body.strip())
            return v[-1].strip() if v else None
        def title_hit(sel):
            """Does `sel` match a panel section's title (h2 or h2.hdr, in the fold's summary, in any section of the panel, in either theme)? Ancestors other than the panel's own, the fold and the theme switch never match."""
            if "::" in sel or re.search(r":(hover|focus|active|first-of-type|last-child)", sel): return False
            toks = [t for t in re.split(r"\s*([>+~])\s*|\s+", sel.strip()) if t]
            m = re.fullmatch(r"(h2)?((?:\.[\w-]+)*)", toks[-1]) if toks else None
            if not m or not (m.group(1) or m.group(2)) or any(c != ".hdr" for c in re.findall(r"\.[\w-]+", m.group(2))): return False
            ok = {"#panel", "section", "details", "details.fold", ".fold", "summary", ">", "+", "~", "#machines", "#runners", "#anchorhub", "#audit-panel", "body", "html", ":root"}
            return all(a in ok or a.startswith(("[data-theme", ":root[", "html[", "body[")) or re.fullmatch(r"(?:\[data-theme[^\]]*\]|:root|html|body)(?::not\(.*\))?", a) for a in toks[:-1])
        hits = [(sel, body, pos) for sel, body, pos in rules if color_of(body) is not None and title_hit(sel)]
        wins = max(hits, key=lambda r: (spec(r[0]), r[2])) if hits else None
        check("a panel section title is in the text colour: the rule that wins its color is `#panel section h2` with var(--fg)", wins is not None and wins[0] in ("#panel section h2", "#panel section h2.hdr") and color_of(wins[1]) == "var(--fg)", wins)
        check("…every rule for the titles that sets a color sets var(--fg), none gives them var(--mut) (so the same in both themes)", bool(hits) and all(color_of(b) == "var(--fg)" for s_, b, _ in hits), [(s_, color_of(b)) for s_, b, _ in hits])
        title_rule = next((r for r in rules if r[0] == "#panel section h2"), None)
        check("…size, weight, capitals and spacing of the title are as they were", title_rule is not None and all(t in title_rule[1] for t in ("font-size:12px", "font-weight:600", "letter-spacing:.06em", "text-transform:uppercase")), title_rule)
        grip_rule = next((r for r in rules if r[0] == ".pgrip"), None)
        check("the grip stays muted (color var(--mut))", grip_rule is not None and color_of(grip_rule[1]) == "var(--mut)", grip_rule)

        # ---- 9. a machine card's new (available) version is in the text colour, not orange; the installed version beside it stays muted
        def st_hit(sel):
            """Does `sel` match the `.st` of a machine row that is behind (div.mr.update > span.st), in the panel or elsewhere, in either theme?"""
            if "::" in sel or re.search(r":(hover|focus|active|first-of-type|last-child)", sel): return False
            toks = [t for t in re.split(r"\s*([>+~])\s*|\s+", sel.strip()) if t]
            m = re.fullmatch(r"(span)?((?:\.[\w-]+)*)", toks[-1]) if toks else None
            if not m or not m.group(2) or any(c not in (".st",) for c in re.findall(r"\.[\w-]+", m.group(2))): return False
            have = {"mr", "update", "pc", "mach", "mcol", "matrix"}
            for a in toks[:-1]:
                if a in (">", "+", "~") or re.fullmatch(r"(?:\[data-theme[^\]]*\]|:root|html|body)(?::not\(.*\))?|#panel|#machines|section|details|details\.fold", a): continue
                if re.fullmatch(r"(?:div|span)?(?:\.[\w-]+)+", a) and all(c[1:] in have for c in re.findall(r"\.[\w-]+", a)): continue
                return False
            return True
        st_hits = [(sel, body, pos) for sel, body, pos in rules if color_of(body) is not None and st_hit(sel)]
        update_rule = next((r for r in rules if r[0] == ".mr.update .st"), None)
        check("a machine row that is behind: the rule for its new version's color is `.mr.update .st` with var(--fg), weight 600", update_rule is not None and color_of(update_rule[1]) == "var(--fg)" and "font-weight:600" in update_rule[1], update_rule)
        check("…no rule for that element gives it --call, --acc or --orange (the update orange is gone from it, in both themes)", not [(s_, color_of(b)) for s_, b, _ in st_hits if re.search(r"--call|--acc|--orange|#[0-9a-fA-F]{3,8}\b", color_of(b) or "")], [(s_, color_of(b)) for s_, b, _ in st_hits])
        check("…and the installed version beside it stays muted (`.mr .st` color var(--mut))", any(s_ == ".mr .st" and color_of(b) == "var(--mut)" for s_, b, _ in rules), None)
        for n, p in PAGES[1:]:
            check(f"the order script is on the root {n} page too", sum("panel-order" in s for s in re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>", get(p).text, re.S)) == 1)
        if shutil.which("node"):
            for i, js in enumerate(scripts):
                p_ = subprocess.run(["node", "-e", "new (require('vm').Script)(require('fs').readFileSync(0,'utf8'))"], input=js, capture_output=True, text=True, timeout=30)
                check(f"root home: inline script {i + 1} parses", p_.returncode == 0, p_.stderr[:300])


part_open()
part_order()

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
