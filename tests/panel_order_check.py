"""Panel-order browser check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Serves the real app (the board at the root, the save route, the sign-in
cookie) on a free local port from fixture data (no live store, no network) and drives the side panel's section order in Chromium:

  - at 1280 px (the panel pinned) and 390 px (the drawer), light and dark: the five sections each have a grip inside the header, to the right of the title, inside the panel,
    nothing runs past the screen's width, a click on a grip does not fold the section;
  - the order is in the first paint: with scripts off, a saved order is the order of the sections, and a second device (a 390 px context) signed in as the same person gets it;
  - the keyboard: the grip focused and Enter opens the move menu, Move up and Move to top are disabled on the first section, Down / Up / Home / End move through the enabled
    moves, Enter makes the move, Escape closes the menu and puts focus back on the grip; each move says "<Section> moved to position N of 5" in the live region; the move is saved (the server's file has the order) and survives a reload;
  - a drag with the pointer (mouse; the pointer-events path a touch takes too): while it goes an orange drop line (the accent colour) shows where the section lands, the dragged
    section is dimmed, the line is gone and the section placed on release; Escape during a drag cancels it;
  - there is no Reset order button anywhere (page, script): a saved order is shown on load and every section still moves by the grips, and moving the sections back is the way to the
    default order, saved the same way;
  - the gap: under each of the five titles the first block starts 8 px below the title and clear of the grip, the same on all five;
  - the five titles are in the text colour (--fg), the grips stay muted.

    tests/run-suite panel_order_check     → exit 0 / 1
    PANEL_ORDER_SHOTS=<dir> keeps a screenshot of each state (once per machine, the browser itself: uvx playwright@1.63.0 install chromium)"""
import json, logging, os, pathlib, re, socket, subprocess, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="porderchk-"); T = pathlib.Path(tmp)
with socket.socket() as s_:
    s_.bind(("127.0.0.1", 0)); PORT = s_.getsockname()[1]
BOARD = f"http://127.0.0.1:{PORT}"
EMAIL = "mina@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1    # the Audit section is drawn
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/audit", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A = "22222222-2222-4222-8222-222222222222"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "state/anchor-hub/status.json").write_text(json.dumps({"receivers": {"hook-a": {"ok": True, "checked": "2026-10-30 10:00:00"}, "hook-b": {"ok": True, "checked": "2026-10-30 10:00:00"}}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.web import server; from stackshot.web import uiprefs as up
import uvicorn
server._publish = lambda: None
DEFAULT = list(up.PANEL_SECTIONS); LAB = {"machines": "Machines", "runners": "Runners", "anchorhub": "Anchor hub", "audit-panel": "Audit", "projects-panel": "Projects"}
COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
srv = uvicorn.Server(uvicorn.Config(server.mcp.http_app(), host="127.0.0.1", port=PORT, log_level="critical", lifespan="on"))
th = threading.Thread(target=srv.run, daemon=True); th.start()
for _ in range(100):
    try: socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close(); break
    except OSError: time.sleep(0.1)
else: raise SystemExit("the app did not start")

SHOTS = os.environ.get("PANEL_ORDER_SHOTS", "")
if SHOTS: pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True)
def shot(pg, name):
    if SHOTS: pg.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"))
ORDER_JS = "[...document.querySelectorAll('#panel > section')].map(e=>e.id)"
def order(pg): return pg.evaluate(ORDER_JS)
def saved(): return up.panel_order(EMAIL)
def live(pg): return pg.inner_text("#panel-live").strip()
def settle(pg, ms=250): pg.wait_for_timeout(ms)

from playwright.sync_api import sync_playwright
try:
  with sync_playwright() as p:
    try: br = p.chromium.launch()
    except Exception as e:
        print("no browser (once per machine: uvx playwright@1.63.0 install chromium):", str(e)[:160]); srv.should_exit = True; sys.exit(2)
    def ctx_for(w, scheme, js=True):
        ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme, java_script_enabled=js)
        ctx.add_cookies([{"name": server._UI_COOKIE, "value": COOKIE, "url": BOARD}])
        return ctx
    def open_panel(pg, w):
        if w < 800 and not pg.evaluate("document.body.classList.contains('panel-open')"):
            pg.click("#panel-open"); settle(pg, 300)
    for w in (1280, 390):
        for scheme in ("light", "dark"):
            tag = f"{w}-{scheme}"
            up.reset_panel_order(EMAIL)
            ctx = ctx_for(w, scheme); pg = ctx.new_page(); pg.goto(BOARD + "/"); settle(pg); open_panel(pg, w)
            check(f"{tag}: the default order", order(pg) == DEFAULT, order(pg))
            check(f"{tag}: there is no Reset order button, nothing runs past the screen's width", pg.locator("#panel-reset").count() == 0 and "Reset order" not in pg.inner_text("#panel") and pg.evaluate("document.documentElement.scrollWidth") <= w, pg.evaluate("document.documentElement.scrollWidth"))
            gaps = pg.evaluate("""[...document.querySelectorAll('#panel > section')].map(s=>{const t=s.querySelector('summary').getBoundingClientRect(),f=s.querySelector('summary').nextElementSibling,r=f.getBoundingClientRect(),g=s.querySelector('.pgrip').getBoundingClientRect();
              return {id:s.id,mt:getComputedStyle(f).marginTop,gap:Math.round(r.top-t.bottom),clear:g.bottom<=r.top+0.5}})""")
            check(f"{tag}: the first block under each of the five titles has the same 8px gap and the grip is clear of it", len(gaps) == 5 and all(x["mt"] == "8px" and x["gap"] == 8 and x["clear"] for x in gaps), gaps)
            geo = pg.evaluate("""[...document.querySelectorAll('#panel > section')].map(s=>{const g=s.querySelector('.pgrip').getBoundingClientRect(),h=s.querySelector('summary h2').getBoundingClientRect(),P=document.getElementById('panel').getBoundingClientRect();
              return {id:s.id,gw:g.width,gh:g.height,right_of_title:g.left>=h.right-1,inside:g.right<=P.right&&g.left>=P.left,vis:g.width>0,dy:Math.abs((g.top+g.bottom)/2-(h.top+h.bottom)/2),nested:!!s.querySelector('summary .pgrip')}})""")
            check(f"{tag}: each grip is visible, right of its title, inside the panel", len(geo) == 5 and all(x["vis"] and x["right_of_title"] and x["inside"] for x in geo), geo)
            check(f"{tag}: each grip is centred on its title's line, and is not inside the fold's summary", all(x["dy"] <= 3 and not x["nested"] for x in geo), geo)
            check(f"{tag}: the summary's name is the title alone (the grip is a button of its own, named 'Move Runners section')", pg.inner_text("#runners summary").strip().lower() == "runners"
                  and pg.get_by_role("button", name="Move Runners section", exact=True).count() == 1 and pg.get_by_role("button", name="Move Runners section", exact=True).evaluate("e=>e.id") == "pgrip-runners")
            check(f"{tag}: the grip is a comfortable target ({'>= 28 px' })", all(x["gw"] >= 28 and x["gh"] >= 28 for x in geo), geo)
            cols = pg.evaluate("""(()=>{const rd=v=>{const e=document.createElement('i');e.style.color=v;document.body.appendChild(e);const c=getComputedStyle(e).color;e.remove();return c};
              return {fg:rd('var(--fg)'),mut:rd('var(--mut)'),titles:[...document.querySelectorAll('#panel > section summary h2')].map(h=>getComputedStyle(h).color),grips:[...document.querySelectorAll('#panel .pgrip')].map(g=>getComputedStyle(g).color)}})()""")
            check(f"{tag}: the five section titles are in the text colour and the grips stay muted", len(cols["titles"]) == 5 and all(c == cols["fg"] for c in cols["titles"]) and all(c == cols["mut"] for c in cols["grips"]) and cols["fg"] != cols["mut"], cols)
            before = pg.evaluate("document.querySelector('#runners details').open")
            pg.click("#runners .pgrip"); settle(pg, 150)
            check(f"{tag}: a click on the grip opens the menu and does not fold the section", pg.is_visible("#panel-menu") and pg.evaluate("document.querySelector('#runners details').open") == before)
            shot(pg, f"{tag}-menu-open")
            pg.keyboard.press("Escape"); settle(pg, 100)
            check(f"{tag}: Escape closes the menu and the focus is back on the grip", not pg.is_visible("#panel-menu") and pg.evaluate("document.activeElement.dataset.sec") == "runners")
            # keyboard: Projects (the last section) up to the top
            pg.focus("#projects-panel .pgrip"); pg.keyboard.press("Enter"); settle(pg, 100)
            dis = pg.evaluate("[...document.querySelectorAll('#panel-menu .pmi')].map(b=>b.dataset.act+':'+b.disabled)")
            check(f"{tag}: on the last section Move down and Move to bottom are disabled, the first item enabled is focused", dis == ["up:false", "down:true", "top:false", "bottom:true"] and pg.evaluate("document.activeElement.dataset.act") == "up", dis)
            pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowUp"); pg.keyboard.press("End"); settle(pg, 50)
            check(f"{tag}: End goes to the last enabled move, Home to the first", pg.evaluate("document.activeElement.dataset.act") == "top")
            pg.keyboard.press("Home"); pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter"); settle(pg, 300)
            check(f"{tag}: Move to top by keyboard puts Projects first", order(pg)[0] == "projects-panel", order(pg))
            check(f"{tag}: it is announced", live(pg) == "Projects moved to position 1 of 5", live(pg))
            check(f"{tag}: the focus is on the moved section's grip", pg.evaluate("document.activeElement.dataset.sec") == "projects-panel")
            check(f"{tag}: the move is saved on the server", saved() == ["projects-panel", "machines", "runners", "anchorhub", "audit-panel"], saved())
            shot(pg, f"{tag}-after-keyboard-move")
            # reload: the order survives, in the first paint (scripts off)
            pg.reload(); settle(pg); open_panel(pg, w)
            check(f"{tag}: after a reload the order is the saved one, with no Reset order button", order(pg) == saved() and pg.locator("#panel-reset").count() == 0, order(pg))
            nojs = ctx_for(w, scheme, js=False); npg = nojs.new_page(); npg.goto(BOARD + "/")
            html = npg.content(); a = html[html.index('<aside id="panel"'):html.index("</aside>", html.index('<aside id="panel"'))]
            check(f"{tag}: with scripts off the sections already come in the saved order (no move on load) and no reset button", re.findall(r'<section id="([a-z-]+)"', a) == saved() and 'panel-reset' not in a and 'Reset order' not in a, re.findall(r'<section id="([a-z-]+)"', a))
            nojs.close()
            # move down / up through the menu with the mouse
            pg.click("#projects-panel .pgrip"); pg.click("#panel-menu .pmi[data-act=down]"); settle(pg, 200)
            check(f"{tag}: Move down by mouse swaps Projects and Machines, announced as position 2 of 5", order(pg)[:2] == ["machines", "projects-panel"] and live(pg) == "Projects moved to position 2 of 5", (order(pg), live(pg)))
            # drag: Anchor hub to the top
            g = pg.locator("#anchorhub .pgrip").bounding_box(); first = pg.locator("#panel > section").first.bounding_box()
            pg.mouse.move(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2); pg.mouse.down()
            pg.mouse.move(g["x"] + g["width"] / 2, g["y"] - 10, steps=4); pg.mouse.move(g["x"] + g["width"] / 2, first["y"] + 4, steps=8); settle(pg, 100)
            drop = pg.evaluate("""(()=>{const d=document.getElementById('panel-drop');if(!d)return null;const c=getComputedStyle(d),r=d.getBoundingClientRect(),acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim(),
              probe=document.createElement('i');probe.style.color=acc;document.body.appendChild(probe);const a=getComputedStyle(probe).color;probe.remove();
              return {bg:c.backgroundColor,acc:a,h:r.height,w:r.width,top:r.top,dim:getComputedStyle(document.getElementById('anchorhub')).opacity}})()""")
            check(f"{tag}: while dragging a drop line shows in the accent colour (orange) and the dragged section is dimmed", drop is not None and drop["bg"] == drop["acc"] and drop["h"] >= 2 and drop["w"] > 100 and float(drop["dim"]) < 1, drop)
            shot(pg, f"{tag}-dragging")
            pg.keyboard.press("Escape"); pg.mouse.up(); settle(pg, 150)
            check(f"{tag}: Escape during a drag cancels it: nothing moved, line gone", order(pg)[:2] == ["machines", "projects-panel"] and pg.evaluate("!document.getElementById('panel-drop')") and pg.evaluate("!document.querySelector('.pdragging')"), order(pg))
            g = pg.locator("#anchorhub .pgrip").bounding_box(); first = pg.locator("#panel > section").first.bounding_box()
            pg.mouse.move(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2); pg.mouse.down()
            pg.mouse.move(g["x"] + g["width"] / 2, g["y"] - 10, steps=4); pg.mouse.move(g["x"] + g["width"] / 2, first["y"] + 4, steps=8); pg.mouse.up(); settle(pg, 300)
            check(f"{tag}: dropping Anchor hub above the first section puts it first; line gone; section no longer dimmed; announced", order(pg)[0] == "anchorhub" and pg.evaluate("!document.getElementById('panel-drop') && !document.querySelector('.pdragging')")
                  and live(pg) == "Anchor hub moved to position 1 of 5", (order(pg), live(pg)))
            check(f"{tag}: the drag's move is saved", saved() == order(pg), (saved(), order(pg)))
            check(f"{tag}: the drag's release did not open the menu or fold anything", not pg.is_visible("#panel-menu"))
            shot(pg, f"{tag}-after-drag")
            # a second device: a phone-sized context signed in as the same person gets the same order
            dev = ctx_for(390, scheme); dpg = dev.new_page(); dpg.goto(BOARD + "/"); settle(dpg)
            check(f"{tag}: another device (390 px) has the same order", order(dpg) == saved(), (order(dpg), saved())); dev.close()
            # back to the default by the grips: no reset control, and the saved order is the default again
            open_panel(pg, w)
            for sid in reversed(DEFAULT):
                if order(pg)[0] != sid: pg.click(f"#{sid} .pgrip"); pg.click("#panel-menu .pmi[data-act=top]"); settle(pg, 200)
            check(f"{tag}: moving the sections back by the grips gives the default order, saved", order(pg) == DEFAULT and saved() == DEFAULT, (order(pg), saved()))
            check(f"{tag}: nothing runs past the screen's width after the moves", pg.evaluate("document.documentElement.scrollWidth") <= w)
            ctx.close()
    # the live update (the board's in-place swap of changed blocks) leaves an open move menu, a drag and the focus alone
    up.reset_panel_order(EMAIL)
    hub_json = T / "state/anchor-hub/status.json"; bumps = [0]
    def bump_hub():       # a new receiver has reported: the Anchor hub block of the next draw differs
        bumps[0] += 1; d = json.loads(hub_json.read_text()); d["receivers"][f"hook-new{bumps[0]}"] = {"ok": True, "checked": "2026-10-30 10:00:00"}
        hub_json.write_text(json.dumps(d)); time.sleep(1.1); server._board_home_drop()
    def tick(pg):
        pg.evaluate("window.dispatchEvent(new Event('focus'))"); pg.wait_for_timeout(2300)      # the first poll starts the new draw, the second sees its stamp
        pg.evaluate("window.dispatchEvent(new Event('focus'))"); pg.wait_for_timeout(1500)
    ctx = ctx_for(1280, "light"); pg = ctx.new_page(); pg.goto(BOARD + "/"); settle(pg, 800)
    pg.evaluate("window.__sw=0;document.addEventListener('stackshot:swapped',()=>{window.__sw++})")
    conn_new = "(()=>{const c=document.getElementById('conn');return !c.hidden&&c.classList.contains('new')})()"
    # 1. the menu open: a newer board waits (the 'newer board' state), the menu stays and keeps its focus
    pg.click("#runners .pgrip"); settle(pg, 150)
    bump_hub(); tick(pg)
    check("live update: with the move menu open the page does not swap, close the menu or take the focus; it shows the 'newer board' state",
          pg.is_visible("#panel-menu") and pg.evaluate("document.activeElement.classList.contains('pmi')") and pg.evaluate("window.__sw") == 0 and pg.evaluate(conn_new) and "hook-new1" not in pg.inner_text("#anchorhub"),
          (pg.is_visible("#panel-menu"), pg.evaluate("document.activeElement.outerHTML.slice(0,80)"), pg.evaluate("window.__sw"), pg.evaluate(conn_new)))
    # 2. Tab leaves the menu and the focus continues from the grip (not from the end of the panel, where the menu sits)
    pg.keyboard.press("Tab"); settle(pg, 100)
    after = pg.evaluate("""(()=>{const g=document.getElementById('pgrip-runners'),a=document.activeElement;return {menu:!document.getElementById('panel-menu').hidden,expanded:g.getAttribute('aria-expanded'),
      inMenu:!!a.closest('#panel-menu'),follows:!!(g.compareDocumentPosition(a)&Node.DOCUMENT_POSITION_FOLLOWING),near:a.closest('#panel')!==null&&(a.closest('section')===g.closest('section')||a.closest('section')===g.closest('section').nextElementSibling)}})()""")
    check("Tab in the menu closes it and the focus goes on from the grip (closeMenu(true)), not from the menu", not after["menu"] and after["expanded"] == "false" and not after["inMenu"] and after["follows"] and after["near"], after)
    # 3. a drag in progress is not cancelled by the tick
    g = pg.locator("#anchorhub .pgrip").bounding_box()
    pg.mouse.move(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2); pg.mouse.down(); pg.mouse.move(g["x"] + g["width"] / 2, g["y"] - 40, steps=4); settle(pg, 100)
    bump_hub(); tick(pg)
    check("live update: a drag in progress goes on (drop line and dimmed section stay, nothing swapped)", pg.evaluate("!!document.getElementById('panel-drop')") and pg.evaluate("!!document.querySelector('.pdragging')") and pg.evaluate("window.__sw") == 0
          and "hook-new2" not in pg.inner_text("#anchorhub"))
    pg.keyboard.press("Escape"); pg.mouse.up(); settle(pg, 150)
    check("…Escape then cancels it, and the page is no longer busy", order(pg) == DEFAULT and pg.evaluate("!document.getElementById('panel-drop')") and pg.evaluate("!document.getElementById('panel').hasAttribute('data-pbusy')"))
    # 4. nothing in the way: the changed block is swapped, 'swapped' fires once, and the focus on a grip in the swapped section comes back by its id
    pg.focus("#pgrip-anchorhub"); tick(pg)
    check("live update: with no menu or drag the changed block is swapped in place (once), and the grip that had the focus has it again", pg.evaluate("window.__sw") == 1 and "hook-new2" in pg.inner_text("#anchorhub")
          and pg.evaluate("document.activeElement.id") == "pgrip-anchorhub" and not pg.evaluate(conn_new), (pg.evaluate("window.__sw"), pg.evaluate("document.activeElement.outerHTML.slice(0,80)"), pg.inner_text("#anchorhub")[:80], pg.evaluate("[!!document.querySelector('details.ag[open]'), String(getSelection()), !!document.querySelector('#panel[data-pbusy],#panel-menu:not([hidden])'), document.getElementById('conn').className]")))
    # 5. a tick that finds a newer draw with no block changed swaps nothing and says nothing
    time.sleep(1.1); server._board_home_drop(); tick(pg)
    check("live update: a newer draw with no changed block fires no 'swapped' (a menu opened now would not be closed)", pg.evaluate("window.__sw") == 1)
    pg.click("#audit-panel .pgrip"); settle(pg, 100); tick(pg)
    check("…a tick with the menu open and nothing new leaves it open", pg.is_visible("#panel-menu")); pg.keyboard.press("Escape")
    # 6. a hidden first section: the first visible one gets the first-section style (no border above it, the short top padding)
    st = pg.evaluate("""(()=>{const l=[...document.querySelectorAll('#panel>section')],f=(s)=>{const c=getComputedStyle(s);return [c.borderTopWidth,c.paddingTop]},o=l.map(f);
      l[0].hidden=true;const h=l.slice(1).map(f);l[0].hidden=false;return {shown:o,hidden:h}})()""")
    check("a hidden first section: the next visible one takes the first-section style (no top border, 2 px padding); with all shown only the first has it", st["shown"][0] == ["0px", "2px"] and all(x == ["1px", "14px"] for x in st["shown"][1:])
          and st["hidden"][0] == ["0px", "2px"] and all(x == ["1px", "14px"] for x in st["hidden"][1:]), st)
    shot(pg, "live-update-done"); ctx.close()
    # the item page carries the same panel and order
    up.set_panel_order(EMAIL, ["runners", "machines"])
    ctx = ctx_for(1280, "light"); pg = ctx.new_page(); pg.goto(BOARD + "/projects/alpha"); settle(pg)
    check("a project page has the saved order too", order(pg) == saved() and order(pg)[0] == "runners", order(pg)); ctx.close()
    br.close()
finally:
    srv.should_exit = True; th.join(timeout=10)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
