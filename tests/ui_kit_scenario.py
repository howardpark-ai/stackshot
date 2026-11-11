"""Scenario test for the board pages' one item system (ui/kit.py and its use in ui/render.py): fixture store, the Board's own page methods, no network.

Covers:
  * the colors: every tag pair and every text color reaches 4.5:1 (WCAG 1.4.3) on the surfaces it sits on, in light and dark;
  * the type scale: every rule outside the side panel uses the five sizes (12, 13, 15, 17, 22) and two weights, no capitals, no letter spacing;
  * home: Your move, On agent, Queued for release (an agent's item whose pull request has a release in the release queue, ui/releasing.py) and Waiting draw the one row (title line with the age at the right, who line, detail behind its guide line, actions), keep the hooks the page script reads,
    say no "Open the item", and a Waiting row says "Until <day>: <what>" and "after the wait: <next step>";
  * the Projects page (the old Task board) lists each project with its items and only the agents that are running; its columns carry the lists' words and count what the lists count;
  * Completed is a section of the Landed page, paged 25 to a page with Newer and Older at the edges and an out-of-range page handled; it and the project page draw the same row, the outcome as a tag
    (Done, Dropped, Superseded), the age in the standard form, titles whole;
  * home has neither a Completed nor a Task board section, nor a Completed count card; the side panel's first link is Projects, not the title bar's;
  * the header: every page of the board (home, an item, a project, Projects, Closed, Search, Runners) starts with home's header, the site title, the five count cards (the counts home shows, drawn by the same code)
    and the search box; off home a list card links to home with that list open (`/#your-move`), Closed to /closed; home's own cards keep their `#anchor` click; the counts follow a change; the page's cost is one classification;
  * a machine's failed setup or update is a line inside its own Machines card (words, step or package and version, the reason on hover) under the version rows, the card bordered, no separate card;
    only a failure of a machine that has no card keeps the separate alert card.

    tests/run-suite ui_kit     → exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch
tmp = _scratch.mkdtemp(prefix="uitest-"); T = pathlib.Path(tmp)
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', 'board_url = "https://board.example.org"'),
                 (r'(?m)^base_url = "[^"]*"', 'base_url = "https://board.example.org"'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule\n" * 30, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A, X, B, Y = ("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
W = "66666666-6666-4666-8666-666666666666"
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in ((A, "alpha-main"), (X, "alpha-builder"), (B, "beta-main"), (Y, "beta-engineer-with-a-rather-long-name"), (W, "alpha-watcher"), ("77777777-7777-4777-8777-777777777777", "zeta-main"), ("88888888-8888-4888-8888-888888888888", "eta-main"), ("99999999-9999-4999-8999-999999999999", "omega-main"), ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "memo-main"))}))
# roles.json (the file the server keeps from sala's session list): alpha-watcher is running with no open item; alpha-idle is listed on the page but sala has no running session of it
(T / "state/roles.json").write_text(json.dumps({"sessions": {"alpha-main": {"live": True}, "alpha-builder": {"live": True}, "alpha-watcher": {"live": True}, "alpha-idle": {"live": False},
                                                            "beta-main": {"live": True}, "beta-engineer-with-a-rather-long-name": {"live": True},
                                                            "gamma-builder": {"live": True}, "gamma-main": {"live": True}, "gamma-reviewer": {"live": True}, "gamma-sweeper": {"live": True}, "gamma-asleep": {"live": False}, "epsilon-main": {"live": False}, "zeta-main": {"live": True}, "eta-main": {"live": False}, "omega-main": {"live": True}, "memo-main": {"live": True}}}))
def page_entry(name, agents): return {"title": name.title(), "name": name.title(), "org": "work", "tags": [], "type": "project", "session": agents[0], "status": "active", "board": [], "board_row": False,
                                      "updated": 1, "mirror": "https://example.invalid/" + name, "agents": {a: "builds" for a in agents}}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page_entry("alpha", ["alpha-main", "alpha-builder", "alpha-watcher", "alpha-idle"]), "projects/beta": page_entry("beta", ["beta-main", "beta-engineer-with-a-rather-long-name"]),
                                                              # gamma: front agents listed with -main in the middle, two background agents (one running, one not); delta: no agent, no keeper session; epsilon: an agent, none running
                                                              "projects/gamma": {**page_entry("gamma", ["gamma-builder", "gamma-main", "gamma-reviewer", "gamma-sweeper", "gamma-asleep"]), "back_agents": {"gamma-sweeper": "sweeps", "gamma-asleep": "sleeps"}},
                                                              "projects/delta": {**page_entry("delta", ["x"]), "session": "", "agents": {}},
                                                              "projects/epsilon": page_entry("epsilon", ["epsilon-main"]),
                                                              # zeta and eta list no agents: their keeper session is the one agent (running for zeta, not for eta); omega is retired; memo is a note page with a keeper session and an open item
                                                              "projects/zeta": {**page_entry("zeta", ["zeta-main"]), "agents": {}},
                                                              "projects/eta": {**page_entry("eta", ["eta-main"]), "agents": {}},
                                                              "projects/omega": {**page_entry("omega", ["omega-main"]), "status": "retired"},
                                                              "projects/memo": {**page_entry("memo", ["memo-main"]), "type": "note", "agents": {}}}}))
for k in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "omega", "memo"):
    (T / f"brain/projects/{k}.md").write_text(f"---\ntitle: {k.title()}\n---\n# {k.title()}\n\n## Current state\n\nSTATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
now0 = time.time()
DESC = "- A thing the item is about\n- It lives here\n- Finished when it works"
OPTS = [{"label": "Approve", "line": "Approve the label now; in the answer note give the wording and the builder applies it.", "recommended": True},
        {"label": "Decline", "line": "Keep the old label; the builder first tidies the sample docs, then re-exports.", "recommended": False}]
def item(i, owner=A, status="open", project="projects/alpha", subject=None, age=3600, desc=None, **meta):
    su = now0 - age
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[work] item {i}", "description": desc or DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner, "project": project, "next": "the next step", **meta}}))
ASK = "Decide: approve the new sample label now · Recommend: Approve · Stakes: tidying 40 sample files first takes days and rewrites the help texts · By: Wed"
item(1, subject="[work] Approve the new sample label and send the review copy", age=26 * 60, needs=["decision"], ask=ASK, options=OPTS,
     next="alpha-builder: carry out the answer on the label\nOliver: approve the new sample label now")
item(2, subject="[work] Order a spare handle for the sample widget before the stock runs out", age=3 * 86400, needs=["decision"], ask="Decide: which day to order the handle · Recommend: Fri · Stakes: the widget stays on back order · By: Fri", options=[])
item(3, subject="[work] Reply to the supplier about the sample order", age=7 * 86400, state="your-step", step="Reply to the supplier: `send the order terms` to them and say yes to the quote", mover="Oliver",
     draft="Hi Sam,\n\nWe would like to order on the same terms. Please send the price list.\n\nThanks,\nAlex", next="Oliver: reply to the supplier", needs=["alpha-main"])
item(4, owner=X, subject="[work] Pack the sample widget kit for a partner's own workshop, with two guides", age=5 * 60, next="alpha-builder: map the scope and hand the packing to its builder", state="doing", expected_by="2026-11-04", expected_reason="the build takes until Wednesday")
item(5, owner=Y, project="projects/beta", subject="[home] Redesign the sample dashboard with a per-panel toggle and a longer title to wrap", age=21 * 60, state="doing", expected_by="2026-11-04", expected_reason="the review is on Tuesday", next="beta-engineer-with-a-rather-long-name: review the change with a second reader, then ship it")
item(6, owner=B, project="projects/beta", subject="[home] Have the sample check compare every claim against the example", age=3600, wait_kind="time", wake="2026-11-05", post_wake_mover="beta-main",
     wait_basis={"text": "the first full sample report, Sunday morning", "wake": "2026-11-05", "by": "beta-main", "at": now0 - 3000}, next="beta-main: read the report")
item(7, owner=B, project="projects/beta", subject="[home] Report the sample queue cost three days after the change", age=14 * 3600, wait_kind="item", after=["a4"], post_wake_mover="beta-main", wake="2026-11-09", next="beta-main: write the report")
item(8, owner=B, project="projects/beta", subject="[home] Ask the supplier to raise the sample limit before the move", age=25 * 3600, state="outside", party="the supplier support desk", chase="2026-11-06", next="beta-main: ask the supplier")
item(14, owner=X, subject="[work] An item with steps behind it", age=2 * 3600, next="alpha-builder: review the PR", goal="Ship the review", priority="p1",
     steps=[{"text": "alpha-builder: write the code", "status": "done", "by": "alpha-builder", "at": now0 - 7000}, {"text": "alpha-builder: try the old way", "status": "dropped", "by": "alpha-builder", "at": now0 - 6000},
            {"text": "alpha-builder: review the PR", "status": "open"}])
for i, oc, why in ((10, "done", "Live at 0168c0d: the sample shows once in the list; rows follow the list order"), (11, "dropped", "Not needed any more: the supplier changed the plan and the question is moot"),
                   (12, "superseded", "Replaced by the paged Completed page; see the new item for the build"), (13, "done", "The sample check runs as a script; on-demand run worked")):
    item(i, owner=X, project="projects/alpha" if i % 2 else "projects/beta", subject=f"[work] A finished piece of work number {i} with a title long enough to wrap onto two lines on a phone", age=(i - 9) * 3600 * 5)
item(85, owner=A, project="projects/memo", subject="[work] An open item on a note page", next="alpha-main: read it")
NMORE = 30        # closed in the last 14 days, so that Completed has two pages (25, then 9 with the four closed below); none is closed through stackshot_complete, so none is on Landed
for i in range(40, 40 + NMORE):
    item(i, owner=X, project="projects/alpha" if i % 2 else "projects/beta", subject=f"[work] Closed batch piece {i}", status="completed", age=(i - 30) * 1800, desc="- A batch piece\n- Finished when shipped", outcome="done", reason=f"batch piece {i} shipped", needs=[])
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
logging.disable(logging.INFO)
from stackshot.web import server
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
from stackshot.core import config as _cfg
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
(T / "fakepush.py").write_text("import sys\nprint('delivered')\n"); server._PUSH = [sys.executable, str(T / "fakepush.py")]
for i, oc, why in ((10, "done", "Live at 0168c0d: the sample shows once in the list; rows follow the list order"), (11, "dropped", "Not needed any more: the supplier changed the plan and the question is moot"),
                   (12, "superseded", "Replaced by the paged Completed page; see the new item for the build"), (13, "done", "The sample check runs as a script; on-demand run worked")):
    kw = dict(outcome=oc, reason=why, sender="alpha-builder")
    if oc == "superseded": kw["superseded_by"] = "a4"
    kw["description"] = "- The thing works and is in use"
    r = server.stackshot_complete(f"a{i}", **kw)
from stackshot.web.ui import render as r2, search as s2
from stackshot.web import search as sm
Bd = lambda: r2.Board(str(T / "store"), now=None)
from stackshot.web import landed as ld
sm.sync(Bd())

# ---------------------------------------------------------------------------------------------------------------- the checks
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web.ui import kit as ui
from stackshot.web.ui import render as r2
def lum(h):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)

# ---- 1. the colors: each tag pair and each text color reaches 4.5:1 on the surfaces it sits on, in both themes
import _colors as C
_TK = C.resolved(r2.Board(str(T / "store"), now=None)._css())      # the Board's stylesheet, each token as the cascade gives it per theme (--t-you is var(--orange), --t-you-bg a blend of it over the card)
LIGHT = _TK["light"]; DARK = _TK["dark"]
SURF = {"light": {"bg": "#fafaf8", "card": "#ffffff"}, "dark": {"bg": "#161617", "card": "#1f1f21"}}
for theme, tk in (("light", LIGHT), ("dark", DARK)):
    for kind in ("you", "agent", "release", "wait", "done"):
        r = ratio(tk[f"--t-{kind}"], tk[f"--t-{kind}-bg"]); check(f"{theme}: the {kind} tag's word on its fill is {r:.2f}:1 (4.5 needed)", r >= 4.5)
    r = ratio(tk["--t-red"], tk["--t-red-bg"]); check(f"{theme}: the P1 tag is {r:.2f}:1", r >= 4.5)
    for surf, hexv in SURF[theme].items():
        for tok in ("--amber", "--red", "--t-you", "--t-agent", "--t-release", "--t-wait"):
            r = ratio(tk[tok], hexv); check(f"{theme}: {tok} on {surf} is {r:.2f}:1", r >= 4.5)
check("the state words are the one set", ui.WORDS == {"you": "Your move", "agent": "On agent", "release": "Queued for release", "wait": "Waiting", "done": "Done", "dropped": "Dropped", "superseded": "Superseded", "closed": "Closed"}, ui.WORDS)
check("the tag is a plain span with the word, never a link", ui.tag("superseded") == '<span class="tag t-superseded">Superseded</span>')

# ---- 2. the type scale: five sizes, two weights (tags 500), no capitals, no letter spacing
css = r2.Board(str(T / "store"), now=None)._css()
check("the stylesheet is the Board's own", len(css) > 20000, len(css))
odd = []; bad = []
for sel, dec in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
    if ui._KEEP.search(sel): continue
    field = bool(re.search(r"input|textarea|\.sbox", sel))
    for n in re.findall(r"font-size:([\d.]+)px", dec):
        if int(float(n)) not in ui.SIZES and not (field and float(n) == 16): odd.append((sel.strip()[:50], n))
    for w in re.findall(r"font-weight:(\d+)", dec):
        if int(w) not in (400, 600) and not (int(w) == 500 and re.search(r"badge|tag|chip|pill", sel)): bad.append((sel.strip()[:50], w))
    if re.search(r"letter-spacing:\s*[.\d]", dec) or "text-transform:uppercase" in dec: bad.append((sel.strip()[:50], "caps or spacing"))
check("every text size outside the side panel is one of 12, 13, 15, 17, 22", not odd, odd[:6])
check("weights are 400 and 600 (500 only on tags and badges); no capitals, no letter spacing", not bad, bad[:6])
once = ui.type_scale("a{font-size:14px;font-weight:700;letter-spacing:.1em}")
check("type_scale snaps a size, a weight and drops letter spacing", once == "a{font-size:15px;font-weight:600}", once)
check("type_scale is idempotent", ui.type_scale(once) == once)
check("the side panel's rules are left as written", ui.type_scale("#panel .x{font-size:11px;font-weight:700}") == "#panel .x{font-size:11px;font-weight:700}")
check("a form field keeps 16px (a phone zooms into a smaller one)", "font-size:16px" in ui.type_scale("textarea{font-size:16px}"))
# the font shorthand takes no `inherit` in a longer value (the browser drops the whole declaration): found by splitting the text on its own, not with the scale's patterns
bad_font = [d.strip() for d in css.replace("{", ";").replace("}", ";").split(";") if d.strip().startswith("font:") and "inherit" in d and d.strip() != "font:inherit"]
check("no `font:` shorthand holds `inherit` beside a size (invalid CSS)", not bad_font, bad_font[:4])
check("the monospace stack is gone from every rule but `code`", [s.strip() for s, d in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "ui-monospace" in d and s.strip() != "code"] == [])
mono = ui.type_scale("a{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:red}b{font:600 13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}")
check("a monospace shorthand becomes size, weight and family apart", mono == "a{font-size:12px;font-weight:400;font-family:inherit;color:red}b{font-size:13px;font-weight:600;font-family:inherit}", mono)
cm = ui.type_scale("/* the .pc cards stay */ a{font-size:14px}\n/* #panel */\nb{font-size:14px}")
check("a comment in front of a rule is not part of its selector", cm == "/* the .pc cards stay */ a{font-size:15px}\n/* #panel */\nb{font-size:15px}", cm)
check("the stylesheet carries no rule for markup the pages no longer draw (a.hopen, ul.hrows, td.ir, th.relay)", not any(w in css for w in ("a.hopen", "ul.hrows", "td.ir", "th.relay")))
check("the stylesheet has no rule for the Projects table's dropped id columns (td.ic, td.ia, th.call, th.agent, th.wait)", not any(w in css for w in ("td.ic", "td.ia", "th.call", "th.agent", "th.wait")))
check("_KEEP names the panel's own classes and ids only", all(ui._KEEP.search(s) for s in ("#panel .x", ".pc", ".pc h3", "a.pc.x", "#panel-open")) and not any(ui._KEEP.search(s) for s in (".pc-x", "#panelx", ".pcx", ".matrix2", ".mh-x", ".audit_line")))

# ---- 3. home: one row for every list
bd = r2.Board(str(T / "store"), now=None)
home = bd.html()
def lis(h): return re.findall(r'<li class="irow[^"]*"[^>]*>.*?</li>', h, flags=re.S)
def section(h, sid):
    m = re.search(rf'<section id="{sid}".*?</section>', h, flags=re.S); return m.group(0) if m else ""
ids = re.findall(r'<section id="([^"]+)"', home)
yours, agents, waits = (section(home, s) for s in ("your-move", "agents-at-work", "waiting-list"))
check("home draws the three lists", all((yours, agents, waits)), ids)
check("Your move, On agent and Waiting rows are the one row", len(lis(yours)) == 2 and len(lis(agents)) >= 1 and len(lis(waits)) == 3, (len(lis(yours)), len(lis(agents)), len(lis(waits))))
for name, sec in (("Your move", yours), ("On agent", agents), ("Waiting", waits)):
    for li in lis(sec):
        if name == "Waiting":      # its slot is the end date, plain text with the age on hover (section 3b)
            check("Waiting: title line, then the end date on the same line, no live age stamp", re.search(r'<div class="ir-top"><span class="ir-title">.*?</span><span class="tip ir-age ir-end[^"]*"[^>]*>(until [^<]+|no end date)</span></div>', li, flags=re.S) is not None and "data-ts" not in li.split('class="ir-who"')[0], li[:500])
        else:
            check(f"{name}: title line, then the age on the same line", re.search(r'<div class="ir-top"><span class="ir-title">.*?</span><span class="tip [^"]*ir-age[^"]*" data-ts="\d+"', li, flags=re.S) is not None, li[:300])
        check(f"{name}: the id has its own span beside the title's", re.search(r'<span class="ir-id">a\d+</span> <span class="hgoal">[^<]+</span>', li) is not None, li[:300])
        check(f"{name}: no state tag (the heading says it)", 'class="tag ' not in li)
        check(f"{name}: no 'Open the item' line", "Open the item" not in li and "hopen" not in li)
check("Your move: the answer form sits under the detail, in the actions", re.search(r'<div class="ir-det">.*?</div><div class="ir-act"><form class="hanswer', yours, flags=re.S) is not None)
check("Your move: the form keeps the hooks the page script reads (data-gid, hgoal)", 'data-gid="a1"' in yours and 'class="hgoal"' in yours)
check("an amber or red age only on Your move", ("ir-age amber" in yours or "ir-age red" in yours) and "ir-age amber" not in waits + agents and "ir-age red" not in waits + agents)
check("Waiting: the who line says who picks it up / watched by", all(re.search(r'class="ir-who">.*? (picks|to pick) it up', li) for li in lis(waits)))
check("Waiting: 'Until <day>: <what>' leads the detail", "Until Thu Nov 5th" in waits)
check("Waiting: the next step follows as 'after the wait: X' on its own line", waits.count("after the wait:") == 3, waits.count("after the wait:"))
check("Waiting: no old 'waits until' prose, no 'next:' label", "waits until" not in waits and "next:" not in waits)
check("On agent: the mover is the who line", 'class="ir-who">' in agents)
check("a row carries its anchor id for the page script (closest li[id])", all(re.search(r'<li class="irow[^"]*" id="[^"]+"', li) for li in lis(yours) + lis(waits)))
check("headings are sentence case with a count", all(f"<h2>{w} <span" in home for w in ("Your move", "On agent", "Queued for release", "Waiting")) and "<h2>Agents at work" not in home and "at work" not in home.lower() and "<h2>YOUR MOVE" not in home)

# ---- 4. home has no Task board and no Completed: neither section, nor the Completed count card; the Projects section is the side panel's last
check("home: no Task board and no Completed section, fold or card", not any(x in home for x in ('id="by-project"', 'id="completed"', 'data-fold="by-project"', 'data-fold="completed"', 'table class="pidx"', 'href="#completed"', ">Task board<")),
      [x for x in ('id="by-project"', 'id="completed"', 'href="#completed"', ">Task board<") if x in home])
LABEL = r'((?:[^<]|<span class="more">[^<]*</span>)*)'     # a card's label: plain text, or its short form with the rest in span.more
BADGE = r'(?: <i class="hnew">(\d+)<em> new</em></i>)?'    # the Closed card's count, on the label line right after the label: the closes not cleared yet
cards = [re.sub(r"<[^>]*>", "", x[0]) for x in re.findall(r'<a class="hcard[^"]*" href="[^"]*"[^>]*><b>\d+</b><span>' + LABEL + BADGE + r'</span></a>', home)]
check("home: the count cards run from Your move to Closed, and there is no Completed or Landed card", cards[:1] == ["Your move"] and cards[-1:] == ["Closed"] and "Waiting" in cards and "Completed" not in cards and "Landed" not in cards, cards)
check("home: the other sections stay (Your move, On agent, Waiting, and the panel's four)", all(f'<section id="{x}">' in home for x in ("your-move", "agents-at-work", "waiting-list", "machines", "runners", "audit-panel")), ids)
LDP = bd.landed_html(); PRJ = bd.projects_html(); ITEMP = bd.item_html("a1", answer=None, watch=None)
def panel_of(h):
    m = re.search(r'<aside id="panel".*?</aside>', h, re.S); return m.group(0) if m else ""
for nm, pg in (("home", home), ("Landed", LDP), ("Projects", PRJ), ("item", ITEMP)):
    pt = panel_of(pg); lk = pt.find('<a class="pc rc" href="/projects#grp-')
    check(f"{nm} page: the old Projects link at the top of the side panel is gone; the Projects section's cards link to the scopes' groups, inside the last section", lk > 0 and "plinks" not in pt and '<a href="/projects">Projects</a>' not in pt
          and 0 < pt.find("<!--ps:projects-panel-->") < lk < pt.find("<!--/ps:projects-panel-->"), pt[:400])
    tb_ = re.search(r'<div class="topline">.*?</div>', pg, re.S); hd_ = re.search(r"<header.*?</header>", pg, re.S)
    check(f"{nm} page: no Projects link in the title bar or the header", '/projects"' not in (tb_.group(0) if tb_ else "") + (hd_.group(0) if hd_ else ""), None)
check("the panel has no loose Projects link of its own any more (the Projects section is a movable section with its grip)", "plinks" not in panel_of(home) and 'id="pgrip-projects-panel"' in panel_of(home))

# ---- 5. the Projects page: a list of projects and their running agents, nothing else
heads = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", PRJ)
def agent_rows(key):   # the <li> lines of one project's Agents cell, and the cell's plain text when it has no list
    tr = re.search(r'<tr><td class="proj"><a href="/projects/%s".*?</tr>' % key, PRJ, re.S)
    return (re.findall(r"<li[^>]*>.*?</li>", tr.group(0), re.S) if tr else []), (re.sub(r"<[^>]+>", "", tr.group(0)) if tr else "")
check("Projects: the page is titled Projects and draws the project table", "<h1>Projects</h1>" in PRJ and "<title>Projects · " in PRJ and 'table class="pidx"' in PRJ)
check("Projects: two columns, Project and Agents, and no other header", [h for h in heads if "<span" not in h] == ["Project", "Agents"] * PRJ.count("<thead>") and not re.search(r"<th[^>]*>(Open|Your move|On agent|Waiting|Watch)</th>", PRJ), heads)
check("Projects: the table has two column widths and no id or watch columns", PRJ.count("<col ") == 2 * PRJ.count('<table class="pidx"') and not re.search(r'class="(ids|opn|anchors|ic|ia|iw)\b', PRJ), re.findall(r"<col [^>]*>", PRJ))
TBL = re.search(r'<section id="by-project">.*?</section>', PRJ, re.S).group(0)      # the table, without the side panel and the page frame
check("Projects: no item ids, no open counts, no watch light", not re.search(r">a\d+</a>", TBL) and "<summary" not in re.sub(r"<summary><h3 class=\"iscope\">Archived <span class=\"count\">\d+</span></h3></summary>", "", TBL) and "wl w-" not in TBL and "verifying" not in TBL, TBL[:600])
check("Projects: no '+' sign and no 'also' or 'pad' marker before an agent", "+" not in re.sub(r"<[^>]+>", "", TBL) and 'class="also"' not in TBL and 'class="pad"' not in TBL)
check("Projects: no 'no agent' group row for items nobody moves", ">no agent<" not in PRJ and "no agent</" not in PRJ and 'class=more' not in PRJ and "no project" not in PRJ)
check("Projects: every project is listed, each linking to its page at the root", all(f">{n}</a>" in PRJ and f'href="/projects/{n.lower()}"' in PRJ for n in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon")))
check("Projects: a session's name without the 'a/' prefix", "a/alpha" not in PRJ and "a/beta" not in PRJ)
check("Projects: an agent with a running session is listed (alpha-watcher has no item)", "alpha-watcher" in PRJ)
check("Projects: agents that own items are listed", "alpha-builder" in PRJ)
check("Projects: an agent the page lists but sala has no running session of is not listed", "idle" not in PRJ and "gamma-asleep" not in PRJ, re.findall(r"[\w-]*(?:idle|asleep)[\w-]*", PRJ))
gl, _gt = agent_rows("gamma"); gnames = [re.sub(r"<[^>]+>", "", x).replace("background", "").strip() for x in gl]
check("Projects: a plain list per project, the -main agent first, the other front agents next, then the running background agent", gnames == ["gamma-main", "gamma-builder", "gamma-reviewer", "gamma-sweeper"], gnames)
check("Projects: the background agent is muted (dimline) and tagged background; no front agent is either", 'class=dimline' in gl[-1] and 'class="rtag"' in gl[-1] and ">background</span>" in gl[-1]
      and not any("dimline" in x or "rtag" in x for x in gl[:-1]) and PRJ.count('class="rtag"') == 1, gl)
al, _at = agent_rows("alpha")
check("Projects: a project with no background agent shows no tag, and its -main agent leads", re.sub(r"<[^>]+>", "", al[0]).strip() == "alpha-main" and "background" not in "".join(al), al)
dl, dt = agent_rows("delta")
check("Projects: a project with no agent of its own says so, with no list", not dl and "no agent of its own" in dt and "<ul" not in re.search(r'<tr><td class="proj"><a href="/projects/delta".*?</tr>', PRJ, re.S).group(0), dt)
el, et = agent_rows("epsilon")
check("Projects: a project whose agents are all gone says no agent running, not 'of its own'", not el and "no agent running" in et and "of its own" not in et, et)
check("Projects: a top-level page of type project is a row with no open item (gamma, delta, epsilon have none)", all(f'href="/projects/{n}"' in PRJ for n in ("gamma", "delta", "epsilon")))
check("Projects: a type note page gets no row, with a keeper session and an open item (memo) alike; the item is open", 'href="/projects/memo"' not in PRJ and "memo" not in TBL.lower() and "a85" in {r["gid"] for r in bd.agent + bd.needs}, re.findall(r"[\w/-]*memo[\w-]*", TBL))
zl, zt = agent_rows("zeta"); el2, et2 = agent_rows("eta")
check("Projects: no agents map -> the keeper session is the one agent, plain, no tag, when it is running", [re.sub(r"<[^>]+>", "", x).strip() for x in zl] == ["zeta-main"] and "rtag" not in "".join(zl) and "dimline" not in "".join(zl), zl)
check("Projects: no agents map and the keeper not running -> 'no agent running', not the keeper's name and not 'of its own'", not el2 and "no agent running" in et2 and "eta-main" not in et2 and "of its own" not in et2, et2)
fin = re.search(r'<details class="fold sfold" data-fold="projects.archived">.*?</details>', TBL, re.S)
check("Projects: a retired project sits in the closed Archived group, and only there", fin is not None and 'href="/projects/omega"' in fin.group(0) and TBL.count('href="/projects/omega"') == 1 and "data-fold=\"projects.archived\" open" not in TBL, fin.group(0)[:300] if fin else None)
check("Projects: the Archived group repeats the two-column table, its agents listed", fin is not None and fin.group(0).count("<col ") == 2 and "omega-main" in fin.group(0) and "alpha" not in fin.group(0).lower().replace("<", " "))
scopes_ = re.findall(r'<tr class="scope">(.*?)</tr>', TBL)
check("Projects: every scope header row spans both columns", scopes_ and all('<th colspan="2">' in x for x in scopes_) and 'colspan="7"' not in TBL, scopes_)
check("Projects: the active projects come before the Archived group", TBL.index('href="/projects/alpha"') < TBL.index('<details class="fold sfold" data-fold="projects.archived">'))
check("Projects: the watch light and its script are gone from the page", "summary.wl" not in PRJ and "details.ag" not in PRJ and "details.wd" not in PRJ and "routing_cell" not in dir(bd))
check("Projects: no Completed section and no pager on this page", 'id="completed"' not in PRJ and '<nav class="lpager"' not in PRJ)
css_ = re.search(r"<style>(.*?)</style>", PRJ, re.S).group(1)
check("Projects: the style carries nothing only the dropped columns and rows used", not re.search(r"td\.(ids|opn|anchors|ic|ia)\b|\.also\b|\.pad\b|tr\.more|c-ids|c-anch|c-open|th\.(call|agent|wait)\b|\.vf\b", css_) and "ul.pagents" in css_)

# ---- 6. Completed, a section of the Landed page: 25 to a page, Newer and Older at the edges, only the page asked for is drawn
NDONE = len(bd.done)
check("the fixture has two pages of Completed", NDONE == 4 + NMORE and NDONE > 25, NDONE)
def comp_of(page=None, board=None):
    h = (board or bd).landed_html(page=page); m = re.search(r'<section id="completed".*?</section>', h, re.S); return h, (m.group(0) if m else "")
h1, c1 = comp_of(); h2, c2 = comp_of(2)
row_ids = lambda c: re.findall(r'<li class="irow"[^>]* id="(task-[^"]+)"', c)
check("Completed (Landed page 1): 25 rows, page 2 the other 9", len(lis(c1)) == 25 and len(lis(c2)) == NDONE - 25, (len(lis(c1)), len(lis(c2))))
check("Last 14 days: the heading is 'Last 14 days' with the whole count, and the section follows New", f'Last 14 days <span class="count">{NDONE}</span>' in c1 and h1.index('id="completed"') > h1.index('id="new"') > h1.index("<h1>Closed</h1>") and ">Completed <" not in h1 and "<h1>Landed</h1>" not in h1 and "<title>Closed" in h1)
check("Completed: only the page asked for is in the page (no hidden rows): the two pages share no row and together are every closed item",
      len(row_ids(c1)) == 25 and not set(row_ids(c1)) & set(row_ids(c2)) and len(set(row_ids(c1)) | set(row_ids(c2))) == NDONE and " hidden" not in c1, (len(row_ids(c1)), len(row_ids(c2))))
ts_ = lambda c: [int(x) for x in re.findall(r'class="tip [^"]*ir-age[^"]*" data-ts="(\d+)"', c)]
check("Completed: newest first, and page 1 is newer than page 2", len(ts_(c1)) == 25 and ts_(c1) == sorted(ts_(c1), reverse=True) and ts_(c2) == sorted(ts_(c2), reverse=True) and min(ts_(c1)) >= max(ts_(c2)), (ts_(c1)[:3], ts_(c2)[:3]))
check("Completed page 1: Older is a link to ?page=2 inside the section, Newer is plain text (the edge)",
      '<a class="pg" rel="next" href="/closed?page=2#completed">Older</a>' in c1 and '<span class="pg off" aria-disabled="true">Newer</span>' in c1 and 'rel="prev"' not in c1 and "Page 1 of 2" in c1, re.findall(r'<nav class="lpager".*?</nav>', c1, re.S))
check("Completed page 2 (the last): Newer is a link back to page 1 without a query, Older is plain text",
      '<a class="pg" rel="prev" href="/closed#completed">Newer</a>' in c2 and '<span class="pg off" aria-disabled="true">Older</span>' in c2 and 'rel="next"' not in c2 and "Page 2 of 2" in c2, re.findall(r'<nav class="lpager".*?</nav>', c2, re.S))
check("Completed: the note says which rows the page shows", f"Showing 1 to 25 of {NDONE}" in c1 and f"Showing 26 to {NDONE} of {NDONE}" in c2, re.findall(r'<p class="lpgnote">.*?</p>', c1 + c2))
for want in (99, "abc", 0, -4, "", None, "2.5", " 2 ", "2"):
    _h, c_ = comp_of(want); pg_ = re.search(r"Page (\d+) of 2", c_)
    exp = 2 if want in (99, " 2 ", "2") else 1
    check(f"Completed: page={want!r} is answered with page {exp} of 2 and its rows, not an error or an empty page", pg_ is not None and int(pg_.group(1)) == exp and len(lis(c_)) == (NDONE - 25 if exp == 2 else 25), (pg_.group(0) if pg_ else None, len(lis(c_))))
def board_with(done):
    o = Bd(); o.done = done; return o
_h, c3 = comp_of(board=board_with(bd.done[:3])); _h, c25 = comp_of(board=board_with(bd.done[:25])); _h, c26 = comp_of(board=board_with(bd.done[:26])); _h, c0 = comp_of(board=board_with([]))
check("Completed: up to 25 rows is one page with no pager; 26 is two", len(lis(c3)) == 3 and len(lis(c25)) == 25 and "lpager" not in c3 + c25 and "Page 1 of 2" in c26 and len(lis(c26)) == 25, [len(lis(x)) for x in (c3, c25, c26)])
check("Completed: no closed item says none and draws no pager", ">none<" in c0 and "lpager" not in c0 and 'class="count">0<' in c0, c0[:300])
check("Landed's own lines are above Completed, and Completed rows are not Landed lines (no Clear, no lrow)", len(lis(h1.split('id="completed"')[0])) == 3 and "lclear" not in c1 and "lrow" not in c1)
check("the Closed page's New section is the shared foldable subsections (a details with a data-fold starting closed.new.) and none of the old group classes remain, and the script's counters do not take Completed for a note",
      re.search(r'<details class="fold sfold hscope" data-fold="closed\.new\.[^"]+"', h1) and not any(x in h1 for x in ('class="lscope"', 'class="lgroup"', 'lscopehd')) and 'class="lnote"' not in c1, c1[:300])
comp = c1
cl = lis(comp)
check("Completed: the page shows Done, Dropped and Superseded as tags where they occur, never 'Replaced', never 'completed 3m ago'",
      all(f'class="tag t-{k}">{w}</span>' in "".join(lis(comp_of()[1]) + lis(comp_of(2)[1])) for k, w in (("done", "Done"), ("dropped", "Dropped"), ("superseded", "Superseded"))) and ">Replaced</span>" not in comp and "completed 1" not in comp, comp[:300])
check("Completed: the age is the standard 'Nh ago', the reason sits behind the guide line", re.search(r'ir-age[^>]*>(?:just now|\d+[mhd] ago)<', cl[0]) is not None and 'class="ir-det">' in cl[0], cl[0][:500])
check("Completed: the title is whole (wraps, never cut with an ellipsis)", all("…" not in x for x in cl) and "with a title long enough to wrap onto two lines on a phone" in comp + comp_of(2)[1])
proj = bd.routing_html("projects/alpha")
check("the project page draws its lists with the same row", len(lis(proj)) >= 3 and 'class="ir-top"' in proj and "Open the item" not in proj, len(lis(proj)))

# ---- 6. the page script's hooks still find what they need
check("the page script's selectors exist in the page", all(x in home for x in ("form.hanswer", ".hgoal", ".hwho")), [x for x in ("form.hanswer", ".hgoal", ".hwho") if x not in home])
_hjs = r2._HOME_JS
_hfs = re.findall(r'<form class="hanswer".*?</form>', home, re.S)
check("home: the answer forms' `back` is empty in the markup and the script fills it with the page's own path alone, no row fragment (it scrolled home to the item's new place)",
      _hfs and all(f.count('name="back" value=""') == 1 for f in _hfs) and "b.value=location.pathname;" in _hjs and "'#'+li.id" not in _hjs and "closest&&f.closest('li[id]')" not in _hjs and "<script>" + _hjs + "</script>" in home, len(_hfs))
check("home: the page stays where it was sent from: scrollY saved as the form is sent, restored once on the page the ?sent= answer lands on (fresh, same path, no hash), the notice's height added and kept in view",
      "sessionStorage.setItem(SK,JSON.stringify({y:Math.round(window.scrollY||0),t:Date.now(),p:location.pathname}))" in _hjs and "sessionStorage.removeItem(SK)" in _hjs and "window.scrollTo(0,Y)" in _hjs
      and "S.p===location.pathname" in _hjs and "!location.hash" in _hjs and "Date.now()-S.t<15000" in _hjs and "document.documentElement.scrollHeight-h0" in _hjs and "position:sticky" in _hjs and "addEventListener('load'" in _hjs
      and _hjs.index("sessionStorage.removeItem(SK)") < _hjs.index("window.scrollTo(0,Y)"), _hjs)
check("home: the page script syncs the cards' Send only on a decision form, never on a step form (form.hstep has no cards: a sync greyed its Send, the empty box that finishes the step included)",
      "if(window.ssCards&&!f.classList.contains('hstep'))ssCards.sync(f)" in _hjs and "if(window.ssCards)ssCards.sync(f)" not in _hjs, _hjs[_hjs.find("function show"):][:400])
check("the stylesheet carries the tokens in light and dark (--t-you reads the page's --orange, which each theme sets; the dark block opens with the tags' own pairs)", "--t-you:" in css and ":root[data-theme=dark]{--t-agent:" in css and DARK["--t-you"] != LIGHT["--t-you"])
check("rows cannot grow past the page (min-width:0 and wrapping)", "li.irow{" in css and "overflow-wrap:anywhere" in css)
# ---- the row as a card: the left edge by list, the project's name above the title (the owner's picks on the row format)
_cr = ui.row(href="/items/9181", rid="item-9181", title="A card", age_html='<span class="ir-age">1m</span>', project_html=ui.project_line("/projects/example", "Example A & B"), edge=ui.YOUR_MOVE)
check("the row: with a project, a small line above the title (a link to the project's page, the name escaped) comes first, then the title line; the card carries its edge's kind",
      _cr == '<li class="irow" data-st="you"><div class="ir-proj"><a class="pjl" href="/projects/example">Example A &amp; B</a></div><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/9181" target="_blank" rel="noopener"><span class="ir-id">item-9181</span> <span class="hgoal">A card</span></a></span><span class="ir-age">1m</span></div></li>', _cr)
_cp = ui.row(href="/items/9181", rid="item-9181", title="A card")
check("the row: no project line and no edge unless asked (Search and the closed items of a project page draw the plain card)", 'ir-proj' not in _cp and 'data-st' not in _cp and _cp.startswith('<li class="irow"><div class="ir-top">'), _cp)
check("the row: an unknown edge is left out, each of the five kinds is carried (orange Your move, blue On agent, purple Queued for release, grey Waiting, green New)",
      'data-st' not in ui.row(href="/x", rid="1", title="t", edge="bogus") and [re.search(r'data-st="([a-z]+)"', ui.row(href="/x", rid="1", title="t", edge=k)).group(1) for k in ui.EDGES] == ["you", "agent", "release", "wait", "new"], ui.EDGES)
check("the stylesheet: a card is a bordered, rounded card on the card color with a 3px left edge in --st, the cards of a list in a column with a gap, no rule between rows and no outline round the list",
      "li.irow{--st:var(--line);padding:10px 14px 12px;border:1px solid var(--line);border-left:3px solid var(--st);border-radius:10px;background:var(--card)" in css
      and "ul.ir-rows{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:12px}" in css and "li.irow:first-child{border-top:0}" not in css and "border:1px solid var(--ibd);border-radius:8px;background:var(--bg);overflow:hidden" not in css, None)
check("the stylesheet: the edge colors are the tag colors (--t-you, --t-agent, --t-release, --t-wait, --t-done for New), a plain card keeps the quiet --line",
      all(f"li.irow[data-st={k}]{{--st:var(--t-{c})}}" in css for k, c in (("you", "you"), ("agent", "agent"), ("release", "release"), ("wait", "wait"), ("new", "done"))), None)
check("the stylesheet: the project line is 12px and quiet (the muted color, the accent on hover), and a cleared Closed row dims it with the rest", ".ir-proj{font-size:12px;line-height:16px;" in css and ".ir-proj a.pjl{color:var(--mut)}" in css and "li.lrow.lcleared .ir-proj," in css, None)
_pcss = (lambda h: h)(Bd().html())
check("home: every list's rows carry their list's edge, and a row with a project names it above the title (Your move orange, On agent blue, Waiting grey)",
      all(re.search(rf'<li class="irow hrow" id="task-a-\d+" data-st="{k}"><div class="ir-proj"><a class="pjl" href="/projects/[a-z]+">[A-Za-z]+</a></div>', sec_) for k, sec_ in (("you", yours), ("agent", agents), ("wait", waits))), (yours[:400],))
_pg = Bd().routing_html("projects/alpha")
check("a project's own page: its open items keep the list's edge but name no project (the page says it), and its closed items keep the plain edge",
      re.search(r'<li class="irow hrow" id="task-a-\d+" data-st="(you|agent|wait)">', _pg) and 'class="ir-proj"' not in _pg, _pg[_pg.find('<section id="items">'):][:600])

# ---- 7. Landed: the same row, the outcome as its tag, Clear under the reason, the standard age
ld_html = bd.landed_html()
ll = lis(ld_html.split('<section id="completed"')[0])        # the Landed lines; Completed below them is checked in section 6
check("Landed: the three closes are the one row, each with its key for the page script", len(ll) == 3 and all(re.search(r'<li class="irow lrow" data-key="[^"]+" data-st="new">', x) for x in ll), len(ll))
check("Landed: Done and Dropped as tags, no Replaced", 'class="tag t-done">Done</span>' in ld_html and 'class="tag t-dropped">Dropped</span>' in ld_html and ">Replaced</span>" not in ld_html)
check("Landed: Clear sits under the reason, in the row's actions (not first)", all(re.search(r'<div class="ir-det">[^<]+</div><div class="ir-act"><form class="lclear"', x) for x in ll), ll[0][-400:])
check("Landed: the age is on the title line, in the standard words", all(re.search(r'class="tip ir-age lago" data-ts="\d+"[^>]*>(?:just now|\d+[mh] ago)<', x) for x in ll))
check("Landed: no old notification words", not re.search(r"\d+ min ago|\d+ h ago|yesterday", ld_html.split("<script>")[0]))
ages = [(0, "just now"), (59, "just now"), (60, "1m ago"), (12 * 60, "12m ago"), (59 * 60, "59m ago"), (60 * 60, "1h ago"), (3 * 3600, "3h ago"), (30 * 3600, "30h ago"), (47 * 3600, "47h ago"), (48 * 3600, "2d ago"), (20 * 86400, "20d ago"), (-5, "just now")]
check("Landed: landed_ago reads in the page's one format", [r2.landed_ago(a) for a, _w in ages] == [w for _a, w in ages], [r2.landed_ago(a) for a, _w in ages])
js = ld_html.split("<script>")[-1]
check("Landed: the page script says the same words, and finds Clear and the id in the new row", "function ago(s){return fa(s)}" in js and "m<60?'age.min':m<2880?'age.hour':'age.day'" in js and "Math.floor(m/1440)" in js and "'.ir-act'" in js and "'.ir-id'" in js and "min ago" not in js and "yesterday" not in js)
check("Landed: the hooks the script reads are still there", all(x in ld_html for x in ("li.lrow", "form.lclear", ".lago[data-ts]")) or all(x in js for x in ("li.lrow", "form.lclear", ".lago[data-ts]")))

# ---- 8. Search: the item's state as its tag, the project on the who line, the snippet behind the guide line, the link in the page's own tab
from stackshot.web import search as _sm
_sm.sync(bd)
sr = s2.results_html(bd, "item")
sl = lis(sr)
check("Search: item and History hits are the one row", len(sl) >= 5 and all("srow" in x for x in sl), len(sl))
check("Search: the state words are the lists' and the outcomes'", all(w in sr for w in ("Your move", "On agent", "Waiting")) and "at work" not in sr.lower() and 'class="tag t-superseded">Superseded</span>' in sr and not re.search(r">(open|completed)</span>", sr), None)
check("Search: no tag says 'open' or 'completed'", not re.search(r'class="tag [^"]*">(open|completed)<', sr))
check("Search: the project is on the who line", all('class="ir-who">' in x for x in sl))
check("Search: the typed word is marked in the snippet", "<mark>item</mark>" in sr)
check("Search: a result opens in the page's own tab", all("target=" not in re.search(r'<a class="ir-link"[^>]*>', x).group(0) for x in sl))
check("Search: the title is #id then the title (no ' · ' between)", "a1 · " not in sr and re.search(r'<span class="ir-id">a1</span> <span class="hgoal">', sr) is not None)

# ---- 9. the item page: the subject as the title, the goal under it, one header line, Next with the open steps first
def page(gid, **kw): return bd.item_html(gid, answer=None, watch=None)
p14, p1, p6, p10 = page("a14"), page("a1"), page("a6"), page("a10")
check("item page: the title is `#id subject` (no '[work]', no ' · ' between), never the goal", re.search(r'<h1><span class="hid">a14</span> An item with steps behind it</h1>', p14) is not None and "<title>a14 · An item with steps behind it</title>" in p14, re.findall(r"<h1>.*?</h1>", p14))
check("item page: the goal is the line under the title", '<p class="igoal">Ship the review</p>' in p14)
check("item page: the header line is the state tag and since, never the mover (the sidebar's Mover row opens the panel and names it, once)",
      re.search(r'<p class="istate"><span class="tag t-agent">On agent</span> · since <span class="tip[^>]*>[^<]+</span></p>', p14, flags=re.S) is not None
      and re.search(r'<aside class="iside"[^>]*><dl class="sgrp"><dt>Mover</dt><dd>[^<]*(?:<[^>]*>[^<]*)*?</dd><dt><span title="[^"]*">Creator</span>', p14) is not None and p14.count("<dt>Mover</dt>") == 1
      and "<dt>Mover</dt>" not in p14.split("More details")[-1], re.findall(r'<p class="istate">.*?</p>', p14))
check("item page: Your move and Waiting say so in the tag", 'class="tag t-you">Your move</span>' in p1 and 'class="tag t-wait">Waiting</span>' in p6)
check("item page: a closed item says Done with its reason in plain words", 'class="tag t-done">Done</span>' in p10 and '<p class="ireason">' in p10 and "Alive" not in p10)
check("item page: no 'Last change' line under the title (the state line stands alone); the state line and the History still render",
      all("ilast" not in p_ and "Last change" not in p_ and "· updated" not in p_ for p_ in (p14, p1, p6, p10)) and re.search(r'<p class="istate">', p14) is not None and re.search(r'<p class="istate">', p10) is not None
      and 'id="history"' in p14 and '<ul class="hist">' in p14)
check("item page: the old state words are gone (Alive, Mover and then, whose move)", not re.search(r"\bAlive\b|Mover and then|whose move", p14 + p1 + p6))
check("item page: Details of a waiting item have no Then row (an agent picks it up, in the wait block), and no Expected by, without the owner's name or the basis", ">Then</dt>" not in p6 and ">Picks it up</dt>" in p6 and "Expected by" not in p6 and "needs set" not in p6 + p1 + p14 and "no date of its own" not in p6 + p1 + p14)
check("item page: priority P1 is a red tag, P2 is plain text", 'class="tag t-p1">P1</span>' in p14 and "<dd>P2</dd>" in p1 and "badge prio" not in p14 + p1)
nx14 = p14[p14.find("<h2>Next</h2>"):p14.find('<details class="fold" data-fold="item.description"')]
check("item page: Next shows the newest finished step and the open step, and one fold of the other earlier ones with their count (a dropped step is not a done one)",
      re.search(r'<details class="iearlier"><summary>1 earlier step \(1 dropped\) · .*?try the old way.*?</details><ul class="inext" aria-label="Next steps">.*?write the code.*?review the PR', nx14, flags=re.S) is not None, nx14[:900])
check("item page: the open step and the newest done step are not inside the fold, the dropped one is", "review the PR" not in p14.split('<details class="iearlier">')[1].split("</details>")[0]
      and "write the code" not in p14.split('<details class="iearlier">')[1].split("</details>")[0] and "try the old way" in p14.split('<details class="iearlier">')[1].split("</details>")[0])
check("item page: a waiting item's next section is 'After the wait'", re.search(r"<h2>After the wait</h2>", p6) is not None and "<h2>Next</h2>" in p1 and "<h2>Next</h2>" not in p6)
check("item page: the project link in the Details has no arrow, only outside links do", "Project details ↗" not in home)

# ---- 10. the History says every move in the lists' words, from the stored state; the expected-by age says it in the rows' words
def version(i, age, **meta):
    item(i, age=age, **meta); git("add", "-A"); git("commit", "-q", "-m", f"a{i} at {age}")
version(31, 7200, state="your-call", needs=["decision"], ask=ASK, options=OPTS)
version(31, 3600, state="your-step", step="Reply to the supplier: send the order terms", mover="Oliver", needs=["alpha-main"])
version(32, 7200, needs=["decision"], ask=ASK, options=OPTS)               # no stored state: the lane's word
version(32, 3600)
version(33, 7200)
version(33, 5400, state=["a", "list"])                                      # a stored state that is no string (hand-edited): no crash
version(33, 3600)
bd2 = Bd()
h31, h32, h33 = (bd2.item_html(g, answer=None, watch=None) for g in ("a31", "a32", "a33"))
check("History: your-call → your-step reads 'moved to Your move' (the stored state's word, not the lane's)", "moved to <b>Your move</b>" in h31 and "moved to <b>On agent</b>" not in h31, re.findall(r"moved to <b>[^<]*</b>", h31))
check("History: an item with no stored state is read by its lane", "moved to <b>On agent</b>" in h32, re.findall(r"moved to <b>[^<]*</b>", h32))
check("History: the creation line says the list's word (item 32 was born asking for a decision), not 'your call' / 'on agent'", re.search(r"created as “[^”]*” · Your move · ", h31) is not None and re.search(r"created as “[^”]*” · Your move · ", h32) is not None and re.search(r"created as “[^”]*” · On agent · ", h33) is not None, re.findall(r"created as [^<]*", h31 + h32 + h33)[:3])
check("History: no page carries 'your call', 'on others' or 'on agent' as a whose-move word", not re.search(r"· (?:your call|on others|on agent)\b|whose move", h31 + h32 + h33 + p1 + p6 + p14), None)
check("History: a stored state that is no string does not raise", "<h1>" in h33 and "state cleared" in h33, re.findall(r"state cleared[^<]*", h33))
check("STATE_WORDS is looked up safely: a list, None and an unknown word give no word", [r2.list_word(x) for x in (["a"], None, "nonsense", {"a": 1})] == ["", "", "", ""] and r2.list_word("your-step", "") == "Your move" and r2.list_word(["a"], "relay") == "Waiting")
# the item page prints no computed date: a wait on a date shows no Expected by row, on time or late, and no 'past due by'
import datetime as _dt
ZONE = _dt.timezone(_dt.timedelta(hours=4))   # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
EB = time.time()      # no wait carries a computed date in the read model, and the page prints none, whatever the clock
def late_page(sec): return r2.Board(str(T / "store"), now=_dt.datetime.fromtimestamp(EB + sec, ZONE)).item_html("a6", answer=None, watch=None)
check("expected-by: late or not, the item page has no Expected by row and no 'past due by'", all("Expected by" not in late_page(x) and "past due by" not in late_page(x) for x in (-3600, 30, 300, 3 * 3600 + 60, 2 * 86400 + 60)))
# agent work in progress has no expected time: a4 and a5 are stored as doing and still carry a far expected_by from before it was retired
def li_of(sec, gid): return next((li for li in lis(sec) if f'<span class="ir-id">{gid}</span>' in li), "")
bd5 = Bd(); home5 = bd5.html(); ag5, wt5 = section(home5, "agents-at-work"), section(home5, "waiting-list")
check("doing, no expected time: a4 and a5 are in On agent, not Waiting, with the age stamp as the run time", li_of(ag5, "a4") and li_of(ag5, "a5") and not li_of(wt5, "a4") and not li_of(wt5, "a5")
      and all(re.search(r'<span class="tip [^"]*ir-age[^"]*" data-ts="\d+"', li_of(ag5, g)) for g in ("a4", "a5")), (re.findall(r'ir-id">(a\d+)', ag5), re.findall(r'ir-id">(a\d+)', wt5)))
check("doing, no expected time: the rows show no 'Expected by', no 'past due' and no overdue marker", not any(x in li_of(ag5, g) for g in ("a4", "a5") for x in ("Expected by", "past due", "overdue", "iwarn")), li_of(ag5, "a4")[:400])
check("doing, no expected time: the read model carries no computed wait at all (no `_wait`)", all("_wait" not in Bd().item(g) for g in ("a4", "a5", "a6")), sorted(Bd().item("a4")))
def far_late(gid, sec): return r2.Board(str(T / "store"), now=_dt.datetime.fromtimestamp(time.time() + sec, ZONE)).item_html(gid, answer=None, watch=None)
pg4, pg4_late = Bd().item_html("a4", answer=None, watch=None), far_late("a4", 30 * 86400)
check("doing, no expected time: the item page has no 'Expected by' and no 'past due', not even a month on", "Expected by" not in pg4 and "past due" not in pg4 and "Expected by" not in pg4_late and "past due" not in pg4_late, re.findall(r"Expected by.{0,80}", pg4_late)[:2])
check("a wait on a date shows no 'Expected by' on the item page", "Expected by" not in Bd().item_html("a6", answer=None, watch=None))
check("doing, no expected time: no On agent row carries the 7-hour marker either", "ir-age red" not in ag5 and "ir-age amber" not in ag5, re.findall(r'ir-age [a-z ]*', ag5))

# ---- 10. Queued for release: an agent's item whose pull request has a release in the release script's queue (its unit is running) leaves On agent for its own open list, count card and tag
from stackshot.web.ui import releasing as rel
units = {18}
rel._run = lambda argv: "".join(f"stackshot-release-{n}.service loaded active running [systemd-run] release.sh --run {n}\n" for n in sorted(units))     # the one systemctl call, stubbed: no unit of the host is read
rel._OWN[:] = ["acme/widget"]                                                                                                                   # this checkout's repository
def pr(n, repo="acme/widget"): return f"https://github.com/{repo}/pull/{n}"
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [
    {"url": pr(18), "items": ["a14", "a1", "a6"], "added": now0 - 500},        # the first item is an agent's (queued); the Your move one and the waiting one stay where they are
    {"url": pr(19), "items": ["a31"], "added": now0 - 400},                    # another agent's item: its PR's release has not started or has ended
    {"url": pr(18, "other/repo"), "items": ["a32"], "added": now0 - 300}]}))    # a third: another repository's pull request with the same number
def home_of(): return r2.Board(str(T / "store"), now=None).html()
def count_card(h, href):
    """(count, label text) of the card linking to href, or None; the label's short-form markup is stripped."""
    m = re.search(rf'<a class="hcard[^"]*" href="{href}"[^>]*><b>(\d+)</b><span>{LABEL}{BADGE}</span></a>', h)
    return (m.group(1), re.sub(r"<[^>]*>", "", m.group(2))) if m else None
def row_ids(sec): return re.findall(r'<span class="ir-id">(a\d+)</span>', sec)
h = home_of(); q = section(h, "queued-release"); ag = section(h, "agents-at-work")
check("queued: the home sections are Your move, On agent, Queued for release, Waiting, in that order", [x for x in re.findall(r'<section id="([^"]+)"', h) if x in ("your-move", "agents-at-work", "queued-release", "waiting-list")] == ["your-move", "agents-at-work", "queued-release", "waiting-list"])
check("queued: an item whose PR is in the queue shows under Queued for release, count 1", row_ids(q) == ["a14"] and 'Queued for release <span class="count">1</span>' in q, row_ids(q))
check("queued: the section is drawn open, On agent closed", '<details class="fold" data-fold="queued-release" open>' in q and '<details class="fold" data-fold="agents-at-work">' in ag)
check("queued: that item has left On agent; one whose release is not queued (its PR is not in the queue, or is another repository's) stays there", "a14" not in row_ids(ag) and {"a31", "a32"} <= set(row_ids(ag)), row_ids(ag))
check("queued: an item on Your move or Waiting is not moved by a queued PR", "a1" in row_ids(section(h, "your-move")) and "a6" in row_ids(section(h, "waiting-list")) and "a1" not in row_ids(q) and "a6" not in row_ids(q))
cq, ca = count_card(h, "#queued-release"), count_card(h, "#agents-at-work")
check("queued: a count card beside the others, after On agent, with the section's count", cq == ("1", "Queued for release") and ca == (str(len(row_ids(ag))), "On agent"), (cq, ca))
check("queued: the cards are in the sections' order", re.findall(r'<a class="hcard[^"]*" href="#([a-z-]+)"', h[h.find('id="counts"'):h.find("</nav>", h.find('id="counts"'))]) == ["your-move", "agents-at-work", "queued-release", "waiting-list"])
cn = h[h.find('<nav class="hcards"'):h.find("</nav>", h.find('<nav class="hcards"'))]
check("cards: Queued for release has a short form (Queued, the rest in span.more), the other four cards are plain labels", '<span>Queued<span class="more"> for release</span></span>' in cn and cn.count('class="more"') == 1
      and [x.strip() for x in re.findall(r"<b>\d+</b><span>([^<]*)(?:</span>|<i )", cn)] == ["Your move", "On agent", "Waiting", "Closed"], cn)
check("cards: 60 px tall at every width, one-line labels, the short form chosen by the cards' column (a container query on the nav), not by the window",
      "nav.hcards{display:grid;" in css and "container:hcards/inline-size}" in css and re.search(r"a\.hcard\{[^}]*height:60px[^}]*\}", css) and re.search(r"a\.hcard span\{[^}]*white-space:nowrap[^}]*text-overflow:ellipsis", css)
      and re.search(r"@container hcards \(max-width:\d+px\)\{a\.hcard span \.more\{[^}]*clip-path:inset\(50%\)", css) and not re.search(r"@media[^{]*\{[^@]*\.hcard span \.more", css)
      and "overflow-wrap:anywhere}@container" not in css)
# the Closed card: the big number is the items closed in the last 14 days (the Last 14 days section's count), the badge beside it the closes not cleared yet (the New section's count)
def closed_card(b):
    hh = b.html(); m = re.search(r'<a class="(hcard[^"]*)" href="/closed"([^>]*)><b>(\d+)</b><span>Closed( <i class="hnew">(\d+)<em> new</em></i>)?</span></a>', hh)
    return m and {"cls": m.group(1), "n": int(m.group(3)), "new": int(m.group(5)) if m.group(5) else None, "attrs": m.group(2)}
_keys = [ld.key(x["gid"], x["ts"]) for x in ld.records()]
_c = closed_card(Bd())
# the number counted by hand from the fixture's files, not from Board.done: completed rows updated within 14 days whose outcome is done, dropped or superseded (the four closed through stackshot_complete and the NMORE batch pieces)
HAND = sum(1 for _f in (T / "store/a").glob("*.json") for _d in [json.loads(_f.read_text())]
           if _d["status"] == "completed" and now0 - _d["updated"] <= 14 * 86400 + 5 and _d["metadata"].get("outcome") in ("done", "dropped", "superseded"))
check("Closed card: the number counted by hand from the store is the four closed items plus the batch of NMORE", HAND == 4 + NMORE == 34, (HAND, NMORE))
check("Closed card (badge shown): the 14-day closed count, with the uncleared closes as an 'N new' badge beside it, linking to /closed",
      _c and _c["n"] == HAND and _c["new"] == len(_keys) == 3 and "zero" not in _c["cls"] and "3 new: closed by an agent, not cleared yet" in _c["attrs"] and HAND != 3, (_c, HAND))
check("Closed page: New counts the same uncleared closes the badge says, Last 14 days the same count as the big number", f'<h2 class="lsec">New <span class="count">{_c["new"]}</span></h2>' in Bd().landed_html()
      and f'Last 14 days <span class="count">{_c["n"]}</span>' in Bd().landed_html(), _c)
# the count sits beside the word Closed: on the label line, in green text, and the number line holds the number alone (a card cannot grow to hold a pill beside the number: each measures its own width for its narrow rules)
_nav = lambda hh: hh[hh.find('<nav class="hcards"'):hh.find("</nav>", hh.find('<nav class="hcards"'))]
_hh = Bd().html(); _cn = _nav(_hh); _cards = re.findall(r'<a class="hcard[^"]*"[^>]*>.*?</a>', _cn); _cl = [x for x in _cards if 'href="/closed"' in x]; _rest = [x for x in _cards if 'href="/closed"' not in x]
check("Closed card (count beside the label): the label line is the word Closed then the count '3 new' as one green <i class=hnew> in the same span; the number line holds the number alone, and no pill follows the label span",
      len(_cards) == 5 and len(_cl) == 1 and re.search(r'<b>\d+</b><span>Closed <i class="hnew">3<em> new</em></i></span></a>$', _cl[0]) and re.fullmatch(r"<b>\d+</b>", re.search(r"<b>.*?</b>", _cl[0]).group(0)) and _cn.count("<i ") == 1
      and "</span><i" not in _cn and "</b><i" not in _cn, _cl)
check("Closed card (count beside the label): the other four cards are unchanged: the number, then the label alone in its span (Queued for release with its short form), no count",
      len(_rest) == 4 and all(re.fullmatch(r'<a class="hcard[^"]*" href="[^"]+"[^>]*><b>\d+</b><span>[^<]*(?:<span class="more">[^<]*</span>)?</span></a>', x) for x in _rest) and _rest[2].count('class="more"') == 1, _rest)
_pill = re.search(r"a\.hcard i\.hnew\{([^}]*)\}", css)
_q = re.findall(r"@container hcard \(max-width:(\d+)px\)\{a\.hcard i\.hnew(\.w\d|)\{position:absolute;[^}]*\}@supports \(left:anchor\(--hcn right\)\)\{a\.hcard i\.hnew\2\{position-anchor:--hcn;left:calc\(anchor\(right\) \+ 4px\);[^}]*\}\}a\.hcard:has\(i\.hnew\2\) b\{font-size:min\(22px,calc\(\(100cqw \+ 2px\) \* 22 / var\(--need,1\)\)\)\}\}", css)
check("Closed card (count beside the label): the count's CSS is plain green text (no border, padding or grid cell of its own); where the card's content is too narrow for the label line to hold it (a container query on the card, one width for a count of one digit and one each for two, three and four digits or more) it moves up beside the number (anchored to the number), the word is never clipped away, and the card keeps measuring its own width",
      _pill and "color:var(--ok)" in _pill.group(1) and not re.search(r"border|padding|grid-area|background", _pill.group(1)) and [(int(x[0]), x[1]) for x in _q] == [(79, ""), (85, ".w2"), (92, ".w3"), (98, ".w4")]
      and not re.search(r"@container hcard \(max-width:\d+px\)\{a\.hcard i\.hnew[^@]*clip-path", css) and ".hnew.wide" not in css and ".hnew.wide) b" not in css and "container:hcard/inline-size" in css and re.search(r"a\.hcard b\{anchor-name:--hcn;grid-area:1/1;", css), (_pill and _pill.group(1), _q))
# a longer word for "new" (a catalog string) moves up sooner and still never clips: the limits grow with the word's estimated width, the English word's stay as they were
_long_css = re.findall(r"@container hcard \(max-width:(\d+)px\)\{a\.hcard i\.hnew", r2._hnew_css("an invented longer word"))
check("Closed card (a longer word): a word of 23 characters moves the count up beside the number at wider cards (limits 79, 85, 92 and 98 plus the room the word needs), the English word keeps its limits, and a short word takes no more room than the English one",
      [int(x) for x in re.findall(r"@container hcard \(max-width:(\d+)px\)\{a\.hcard i\.hnew", r2._hnew_css("new"))] == [79, 85, 92, 98] and [int(x) for x in _long_css] == [x + 140 for x in (79, 85, 92, 98)]
      and r2._hnew_css("no") == r2._hnew_css("new") and r2._hnew_need(40, 2, "new") == 62 and r2._hnew_need(40, 2, "an invented longer word") > 62 + 100, _long_css)
_wide = {}
for _k in (9, 10, 123, 4567, 12345):
    _bk = Bd(); _bk.landed_count = lambda _k=_k: _k; _wide[_k] = re.findall(r'<span>Closed( <i class="hnew[^"]*">\d+<em> new</em></i>)</span></a>', _nav(_bk.html()))
check("Closed card (count beside the label): the count's class says its digits so the card can keep the word 'new' for as long as it fits: none for one digit, w2, w3, w4 for two, three, four or more",
      _wide == {9: [' <i class="hnew">9<em> new</em></i>'], 10: [' <i class="hnew w2">10<em> new</em></i>'], 123: [' <i class="hnew w3">123<em> new</em></i>'], 4567: [' <i class="hnew w4">4567<em> new</em></i>'],
                12345: [' <i class="hnew w4">12345<em> new</em></i>']}, _wide)
ld.clear(_keys)
try:
    _c0 = closed_card(Bd()); _h0 = Bd().html()
    check("Closed card (no new close): the label line is the word Closed alone in its span, with no count and no trailing space", f'<b>{HAND}</b><span>Closed</span></a>' in _nav(_h0) and "hnew" not in _nav(_h0), _nav(_h0))
    check("Closed card (badge hidden): every close cleared leaves the 14-day count and no badge at all", _c0 and _c0["n"] == HAND and _c0["new"] is None and ('<i class="hnew">' not in _h0) and "not cleared yet" not in _c0["attrs"], _c0)
    _b = Bd(); _b.done = []; _z = closed_card(_b)
    check("Closed card (nothing closed in 14 days, nothing new): 0, muted, no badge", _z and _z["n"] == 0 and _z["new"] is None and "zero" in _z["cls"], _z)
finally:
    ld.unclear(_keys)
# an uncleared close older than 14 days stays New (and in the badge) for all the 60 days the record is kept, then leaves; the card's Closed number and the Last 14 days section stay on the 14-day window.
# the fixture items: completed 20 days, 59 days, 61 days and 14 days ago, each with its close recorded then, still uncleared
_OLD = {90: 20, 91: 59, 92: 61, 93: 14}
for _i, _d in _OLD.items():
    item(_i, owner=X, subject=f"[work] A close {_d} days old", status="completed", age=_d * 86400, outcome="done", reason=f"shipped {_d} days back", needs=[])
def _new_section(pg):
    m = re.search(r'<section id="new".*?<section id="completed"', pg, re.S)
    return m.group(0) if m else ""
def _in_new(pg, gid): return f'data-key="{gid}:' in _new_section(pg)
_all = []
try:
    for _i, _d in _OLD.items(): ld.record(f"a{_i}", now0 - _d * 86400, "done", by="alpha-builder")
    _old = Bd(); _co = closed_card(_old); _pg = _old.landed_html()
    _gids = {x["gid"] for x in ld.records()}
    check("landed.py keeps the closes up to 60 days old and drops the 61-day one", {"a90", "a91", "a93"} <= _gids and "a92" not in _gids and len(_gids) == 6, sorted(_gids))
    check("Closed page: an uncleared close 20 days old and one 59 days old are in the New section; the 14-day one is too; the 61-day one is not", _in_new(_pg, "a90") and _in_new(_pg, "a91") and _in_new(_pg, "a93") and not _in_new(_pg, "a92"), re.findall(r'data-key="([^"]+)"', _new_section(_pg)))
    check("Closed card: the badge counts them (the three of the fixture and those three), not the 61-day one", _co and _co["new"] == 6 and "6 new: closed by an agent, not cleared yet" in _co["attrs"], _co)
    check("Closed page: the New section says the same count as the badge", f'<h2 class="lsec">New <span class="count">{_co["new"]}</span></h2>' in _pg and _old.landed_count() == _co["new"] == len(_old.landed_keys()), _co)
    check("Closed card: the Closed number stays the 14-day count: it adds the 14-day close and none of the older ones", _co["n"] == HAND + 1 and len(_old.done) == _co["n"], (_co, HAND))
    _done_sec = "".join((lambda h: h[h.find('id="completed"'):])(_old.landed_html(page=_n)) for _n in (1, 2))      # the section is paged: the oldest close is on the second page
    check("Closed page: Last 14 days lists the 14-day close and not the older ones", f'Last 14 days <span class="count">{_co["n"]}</span>' in _pg and "A close 14 days old" in _done_sec and "A close 20 days old" not in _done_sec and "A close 59 days old" not in _done_sec, _co)
    _row = re.search(r'<li[^>]*data-key="a90:[^"]*".*?</li>', _new_section(_pg), re.S)
    _row = _row.group(0) if _row else ""
    check("Closed page: the 20-day close is drawn like any other row: its tag, `#id title` linking to the item, the close reason, Clear",
          'class="tag t-done">Done</span>' in _row and 'A close 20 days old' in _row and 'href="' in _row and "shipped 20 days back" in _row and 'class="b" aria-label="Clear' in _row and 'class="tip ir-age lago"' in _row, _row[:600])
    _row14 = re.search(r'<li[^>]*data-key="a93:[^"]*".*?</li>', _new_section(_pg), re.S)
    check("Closed page: the 14-day close draws the same row as before (reason and Clear)", _row14 and "shipped 14 days back" in _row14.group(0) and "Clear" in _row14.group(0), _row14 and _row14.group(0)[:300])
    # Clear on one line: only that close leaves the badge and the New section
    _k90 = ld.key("a90", now0 - 20 * 86400)
    check("Clear: the line's key is the one the row carries", f'data-key="{_k90}"' in _pg, _k90)
    check("Clear: one line cleared", ld.clear([_k90]) == 1, None)
    _c1 = Bd(); _p1 = _c1.landed_html(); _cc = closed_card(_c1)
    check("Clear: the 20-day close is gone from the badge and the New section, the 59-day and 14-day closes stay", _cc["new"] == 5 and not _in_new(_p1, "a90") and _in_new(_p1, "a91") and _in_new(_p1, "a93") and f'New <span class="count">{_cc["new"]}</span></h2>' in _p1, _cc)
    check("Undo: the 20-day close is back on both", ld.unclear([_k90]) == 1 and closed_card(Bd())["new"] == 6 and _in_new(Bd().landed_html(), "a90"), None)
    # Clear all: the keys the page carries clear every close on it, the old ones included
    _all = re.search(r'<form class="lmark"[^>]*><input type="hidden" name="keys" value="([^"]*)"', Bd().landed_html())
    _all = _all.group(1).split(",") if _all else []
    check("Clear all carries the key of every close on the page, the 20-day and the 59-day ones included", len(_all) == 6 and _k90 in _all and ld.key("a91", now0 - 59 * 86400) in _all and not any(k.startswith("a92:") for k in _all), _all)
    check("Clear all: clears them all", ld.clear(_all) == 6 and not ld.records(), len(ld.records()))
    _c2 = Bd(); _p2 = _c2.landed_html(); _z2 = closed_card(_c2)
    check("Clear all: no badge, an empty New section, the Closed number unchanged", _z2["new"] is None and _z2["n"] == HAND + 1 and "Nothing an agent closed is waiting here" in _p2 and 'data-key=' not in _new_section(_p2), _z2)
    check("Undo after Clear all: every one of them is back, the old ones too", ld.unclear(_all) == 6 and closed_card(Bd())["new"] == 6, None)
finally:
    for _i in _OLD:
        ld.forget(f"a{_i}"); (T / f"store/a/{_i}.json").unlink()
    if _all: ld.unclear(_keys)
check("Closed card: the closes are back after the Undo (the later checks read them)", len(ld.records()) == 3 and closed_card(Bd())["new"] == 3)
check("queued: the renamed header and card say On agent, never Agents at work, on the home page", "<h2>On agent <span" in ag and "at work" not in h.lower(), None)
check("queued: the row is the agent row (mover on its who line)", 'class="ir-who">' in q)
bq = r2.Board(str(T / "store"), now=None)
HEADS = ("Your move", "On agent", "Queued for release", "Waiting")
def group_heads(pg): return re.findall(r'<h3 class="iscope">([^<]*?) <span class="count">(\d+)</span>', pg)
_pa = bq.routing_html("projects/alpha"); _gh = group_heads(_pa); _hs = [x[0] for x in _gh if x[0] in HEADS]
check("project page: the item groups are the home page's, same labels in the same order, Queued for release among them", _hs == [x for x in HEADS if x in _hs] and "Queued for release" in _hs and "On agent" in _hs and "Agents at work" not in _hs, _gh)
check("project page: the Queued for release group holds the queued item, the On agent group does not", dict(_gh).get("Queued for release") == "1" and 'data-fold="project.items.release"' in _pa and 'data-fold="project.items.agents"' in _pa, _gh)
check("project page: no 'at work' anywhere on it", "at work" not in _pa.lower(), re.findall(r".{30}at work.{30}", _pa.lower())[:3])
check("no new-UI page says 'at work' (home, Projects, Closed, item, project, Search)", all("at work" not in pg.lower() for pg in (home, PRJ, LDP, ITEMP, _pa, bq.item_html("a31", answer=None, watch=None), sr)), None)
check("queued: the item page carries the label, the others keep theirs", 'class="tag t-release">Queued for release</span>' in bq.item_html("a14", answer=None, watch=None) and 'class="tag t-agent">On agent</span>' in bq.item_html("a31", answer=None, watch=None)
      and 'class="tag t-you">Your move</span>' in bq.item_html("a1", answer=None, watch=None))
_sm.sync(bq); srq = s2.results_html(bq, "An item with steps behind it")
check("queued: the search row carries the label", re.search(r'<span class="tag t-release">Queued for release</span>.{0,200}a14', srq, flags=re.S) is not None, srq[:400])
# the release ends (its unit is gone): the item goes back to its normal lane
units.clear(); h = home_of(); q = section(h, "queued-release"); ag = section(h, "agents-at-work")
check("queued: once the PR's release has ended the item is back On agent, the section empty, the card 0", "a14" in row_ids(ag) and not row_ids(q) and "no release is queued" in q and count_card(h, "#queued-release")[0] == "0")
check("queued: the label is gone from its item page", 'class="tag t-agent">On agent</span>' in r2.Board(str(T / "store"), now=None).item_html("a14", answer=None, watch=None))
# a PR listed in the queue file but not started has no unit: nothing is queued; an unreadable systemctl is the same
(T / "state/releases").mkdir(parents=True, exist_ok=True); (T / "state/releases/queue").write_text("18\n")
check("queued: a PR only listed in the queue file (no running release) is not queued", not row_ids(section(home_of(), "queued-release")))
def _boom(argv): raise OSError("no systemctl")
rel._run = _boom
check("queued: when systemctl cannot be read nothing is queued and the page still draws", "a14" in row_ids(section(home_of(), "agents-at-work")))
rel._run = lambda argv: "stackshot-release-18.service loaded active running x\nstackshot-release-40618.service loaded active running x\n"
check("queued: the unit name is matched whole (release 40618 is not release 18's)", rel.release_units() == {18, 40618} and rel.pr_of(pr(7)) == 7 and rel.pr_of(pr(7, "other/repo")) == 0 and rel.pr_of("https://example.org/x/pull/7") == 0)

# ---- 11. Queued for release, the other links: an agent's item counts when an open step names the PR (its proof, its URL, "PR #N"), not only when an anchor does
from stackshot.model import steps as _stp
KEY = _stp.key
item(41, owner=X, subject="[work] linked by a step's URL", next="alpha-builder: release [PR #23](https://github.com/acme/widget/pull/23) as it comes up")
item(42, owner=X, subject="[work] linked by a step that says PR #N", next="alpha-builder: release PR #27 (in its turn)")
item(43, owner=X, subject="[work] linked by a step's proof", next="alpha-builder: ship the thing", step_proof={KEY("alpha-builder: ship the thing"): "pr_released acme/widget#28"})
item(44, owner=X, subject="[work] linked by an anchor", next="alpha-builder: wait for the code to ship")
item(45, owner=X, subject="[work] only a done step and the description name the PR", next="alpha-builder: verify the pages", description="- Ships PR #29 and PR #35\n- Finished when it works",
     steps=[{"text": "alpha-builder: release PR #29", "status": "done", "by": "alpha-builder", "at": now0 - 900}, {"text": "alpha-builder: release PR #35", "status": "dropped", "by": "alpha-builder", "at": now0 - 800}],
     step_proof={KEY("alpha-builder: release PR #29"): "pr_released acme/widget#29"})
OTHER = "alpha-builder: release https://github.com/other/repo/pull/36 and other/repo PR #36, then other/repo#36"
item(46, owner=X, subject="[work] names another repository's pull requests", next=OTHER, step_proof={KEY(OTHER): "pr_released other/repo#36"})
item(47, owner=X, subject="[work] no link to any pull request", next="alpha-builder: think about the design")
item(48, owner=X, subject="[work] linked by a pull request's merge proof", next="alpha-builder: land it", step_proof={KEY("alpha-builder: land it"): "pr_merged acme/widget#35"})
item(49, subject="[work] on Your move, its step names a queued PR", needs=["decision"], ask=ASK, options=OPTS, next="Oliver: decide about PR #23")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": pr(37), "items": ["a44"], "added": now0 - 100}]}))
units.update({23, 27, 28, 37, 29, 36, 35})
rel._run = lambda argv: "".join(f"stackshot-release-{n}.service loaded active running [systemd-run] release.sh --run {n}\n" for n in sorted(units))
h = home_of(); q = section(h, "queued-release"); ag = section(h, "agents-at-work")
check("queued by step: a step's URL, its words, its proof (released or merged) and an anchor each put the item in the section", set(row_ids(q)) == {"a41", "a42", "a43", "a44", "a48"}, row_ids(q))
check("queued by step: a done or dropped step and the description naming the PR do not, nor another repository's PR (URL, words or proof)", {"a45", "a46"} <= set(row_ids(ag)) and not {"a45", "a46"} & set(row_ids(q)), (row_ids(ag), row_ids(q)))
check("queued by step: an item with no link stays On agent", "a47" in row_ids(ag) and "a47" not in row_ids(q))
check("queued by step: an item on Your move stays there whatever its step names", "a49" in row_ids(section(h, "your-move")) and "a49" not in row_ids(q))
check("queued by step: the section's count and the count card follow", 'Queued for release <span class="count">5</span>' in q and count_card(h, "#queued-release")[0] == "5")
check("queued by step: the item page of a step-linked item carries the label", all('class="tag t-release">Queued for release</span>' in r2.Board(str(T / "store"), now=None).item_html(g, answer=None, watch=None) for g in ("a41", "a43")))
units.difference_update({23, 27})
q = section(home_of(), "queued-release")
check("queued by step: once a PR's release has ended its item is back On agent", set(row_ids(q)) == {"a43", "a44", "a48"}, row_ids(q))
rel._OWN[:] = [""]
check("queued by step: a checkout with no known repository links nothing by words or proof", not {"a41", "a42", "a43", "a48"} & set(row_ids(section(home_of(), "queued-release"))))
rel._OWN[:] = ["acme/widget"]
steps_of = lambda nxt, **m: rel.step_prs({"owner": X, "next": nxt, **m})
check("step_prs: URL, 'PR #N' and 'pull request #N' match; a bare #N, a longer number and another repository's mentions do not",
      steps_of("a: release https://github.com/acme/widget/pull/7/files") == {7} and steps_of("a: review pull request #8 now") == {8} and steps_of("a: pr #9") == {9}
      and steps_of("a: see #38 and item a11") == set() and steps_of("a: release PR #123 and PR #1234") == {123, 1234} and steps_of("a: other/repo PR #39 and the one at https://github.com/other/repo/pull/51") == set()
      and steps_of("a: acme/widget#14") == set(), None)

# ---- a machine's failed setup or update is a line inside its own card, under its version rows
def machines_of(): return r2.Board(str(T / "store"), now=None).panel_blocks()["machines"]
def mcards(sec): return [c[:c.index("</div></div>") + 6] for c in sec.split('<div class="mcol">')[1:]]       # each column of the matrix up to the close of its card (a card holds no nested div)
def mach_card(sec, name): return next((c for c in mcards(sec) if f'<b class="lbl mh">{name}</b>' in c), "")
(T / "state/site/versions.json").write_text(json.dumps({"packages": [{"name": "claude code", "installed": "1.0.0", "latest": "1.0.0", "state": "latest"}]}))     # one version row in the publisher's card
sec0 = machines_of()
check("machine failure: a healthy machine's card has no failure line and no alert border", '<div class="pc mach">' in sec0 and 'class="mf"' not in sec0 and "pc alert" not in sec0 and "pc mach bad" not in sec0, sec0[:500])
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0",
    "setup": {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "winget exited with <1>"},
    "updates": [{"what": "gbrain", "from": "0.60.1", "to": "0.60.2", "at": "2026-10-16T00:00:00Z", "ok": False, "reason": "bun install failed: EACCES"},
                {"what": "claude code", "from": "1.0.0", "to": "1.0.1", "at": "2026-10-16T00:00:00Z", "ok": True}]}))
sec1 = machines_of(); ca = mach_card(sec1, "box-a")
lines = re.findall(r'<div class="mf" title="([^"]*)"><span class="lbl bad">([^<]*)</span> <span class="val">([^<]*)</span></div>', ca)
check("machine failure: the card is marked with the alert border", ca.startswith('<div class="pc mach bad">') and sec1.count('<div class="pc mach bad">') == 1, ca[:200])
check("machine failure: one line per failure inside that machine's own card, with its words and the step or the package and version",
      [(w, d) for _t, w, d in lines] == [("setup failed ✗", "step Install Claude Code"), ("update failed ✗", "gbrain 0.60.2")], lines)
check("machine failure: the reason is the line's hover text (the successful update gives no line)",
      len(lines) == 2 and "winget exited with &lt;1&gt;" in lines[0][0] and "Install Claude Code" in lines[0][0] and "bun install failed: EACCES" in lines[1][0] and "0.60.1 → 0.60.2" in lines[1][0], lines)
rows_end = [m.end() for m in re.finditer(r'<div class="mr \w+">.*?</div>', ca)]
check("machine failure: the lines sit under the version rows, at the end of the card", len(rows_end) == 1 and ca.index('class="mf"') > max(rows_end) and ca.endswith("</div>") and ca.count('class="mf"') == 2, ca[-400:])
check("machine failure: no separate card for it", "pc alert" not in sec1 and 'class="mcol"><div class="pc alert' not in sec1)
css1 = r2.Board(str(T / "store"), now=None)._css()
check("machine failure: the line wraps (normal white space, long words broken) and spans the card", re.search(r"\.pc\.mach>\.mf\{[^}]*grid-column:1/-1[^}]*white-space:normal[^}]*overflow-wrap:anywhere", css1) is not None)
# a failure for a machine that has no card (its view carries no fleet name) is not lost: the separate card stays for that case only
(T / "fleet/q").mkdir(); (T / "fleet/q/sessions.json").write_text("{}")
(T / "fleet/q/machine.json").write_text(json.dumps({"letter": "q", "setup": {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Join the tailnet", "reason": "no auth key"}}))
sec2 = machines_of(); orph = re.findall(r'<div class="pc alert bad" title="([^"]*)">(.*?)</div>', sec2)
check("machine failure: a failed machine with no card keeps a separate alert card, naming it, with its step and reason on hover",
      len(orph) == 1 and "machine q" in orph[0][0] and "no auth key" in orph[0][0] and "Join the tailnet" in orph[0][1] and "setup" in orph[0][1] and "failed" in orph[0][1], orph)
check("machine failure: the machines that have cards are unchanged by it (the same lines in box-a's card, no card for the failed machine)",
      mach_card(sec2, "box-a") == ca and sec2.count('class="mf"') == 2 and sec2.count('<div class="pc mach') == sec1.count('<div class="pc mach'), sec2[:300])
shutil.rmtree(T / "fleet/q")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0", "setup": {"ok": True}}))
sec3 = machines_of()
check("machine failure: once the machine has no failure, it has no line and no border", 'class="mf"' not in sec3 and "pc mach bad" not in sec3 and "pc alert" not in sec3, sec3[:300])

# ---- the header: every page of the board starts with home's header (the site title, the five count cards, the search box); off home each list card links to home with that list open
import time as _time
from stackshot.web.ui import runners as n2
LISTS = (("your-move", "Your move"), ("agents-at-work", "On agent"), ("queued-release", "Queued for release"), ("waiting-list", "Waiting"))
def header_of(pg):
    m = re.search(r"<header class=\"top\">.*?</header>", pg, re.S); return m.group(0) if m else ""
def cards_of(hd):
    """[(href, number, label text, badge)] of the header's count cards, in order."""
    return [(m.group(1), m.group(2), re.sub(r"<[^>]*>", "", m.group(3)), m.group(4) or "")
            for m in re.finditer(r'<a class="hcard[^"]*" href="([^"]*)"[^>]*><b>(\d+)</b><span>' + LABEL + r'( <i class="hnew[^"]*">\d+<em> new</em></i>)?</span></a>', hd)]
def pages_now():
    """Every page of the board, drawn from the fixture as it is now: name -> HTML."""
    snap = {"ts": _time.time(), "errors": {}, "failed": [], "runners": [{"box": "box-a", "repo": "acme/widget", "state": "idle", "name": "box-a-1", "kind": "", "reason": "", "job": None}]}
    return {"home": Bd().html(), "item": Bd().item_html("a1", answer=None, watch=None), "project": Bd().routing_html("projects/alpha"), "Projects": Bd().projects_html(),
            "Closed": Bd().landed_html(), "Closed (page 2)": Bd().landed_html(page=2), "Search": s2.results_html(Bd(), "item"), "Search (no query)": s2.results_html(Bd(), ""), "runners": n2.page_html(Bd(), snap)}
ALLPG = pages_now(); HOME_CARDS = cards_of(header_of(ALLPG["home"]))
check("header: home's five cards are Your move, On agent, Queued for release, Waiting, Closed", [c[2] for c in HOME_CARDS] == ["Your move", "On agent", "Queued for release", "Waiting", "Closed"], HOME_CARDS)
for nm, pg in ALLPG.items():
    hd = header_of(pg); cs = cards_of(hd)
    check(f"header: {nm} page draws one header with the site title, the five count cards and the search box, in that order",
          pg.count('<header class="top">') == 1 and 0 < hd.find('class="site"') < hd.find('<nav class="hcards" id="counts"') < hd.find("</nav>") < hd.find('<form class="sbox"') and hd.count('<form class="sbox"') == 1 and len(cs) == 5, (len(cs), hd[:300]))
    check(f"header: {nm} page: the counts are home's, number for number (and the Closed badge)", [(c[1], c[2], c[3]) for c in cs] == [(c[1], c[2], c[3]) for c in HOME_CARDS], (cs, HOME_CARDS))
    check(f"header: {nm} page: the page has one h1 (the site title is the h1 on home only), one counts block and one search box", pg.count("<h1") == 1 and pg.count('id="counts"') == 1 and pg.count('<form class="sbox"') == 1 and ('<h1 class="site">' in hd) == (nm == "home"), (pg.count("<h1"), pg.count('id="counts"')))
    check(f"header: {nm} page: the theme and panel buttons are in the header, and the old title bar (.topline) is gone", 'id="theme"' in hd and 'id="panel-open"' in hd and "topline" not in pg and pg.count('id="theme"') == 1 and pg.count('id="panel-open"') == 1)
    check(f"header: {nm} page: the header's height script is on the page (rows and sections keep clear of the sticky header)", "--hdr" in pg and "header.top" in pg)
    margin_sel = {x.strip() for m in re.finditer(r"(?:^|[{}])([^{}]+)\{scroll-margin-top:calc\(var\(--hdr,0px\) \+ 12px\)\}", re.sub(r"/\*.*?\*/", "", "".join(re.findall(r"<style>(.*?)</style>", pg, re.S)), flags=re.S)) for x in m.group(1).split(",")}
    check(f"header: {nm} page: the scroll margin under the sticky header covers every id a link scrolls to (a section, a task, a history line, a quote tag, a fold)",
          {"section", "article.task", "li.iline", "details.said", "details.fold"} <= margin_sel, sorted(margin_sel))
    sheet = re.sub(r"/\*.*?\*/", "", "".join(re.findall(r"<style>(.*?)</style>", pg, re.S)), flags=re.S)
    check(f"header: {nm} page: the title bar's buttons take a size from one variable, 32 px and 44 px on a touch screen, the same two sizes as .b.ico",
          "header.top{--ico:32px}@media(pointer:coarse){header.top{--ico:44px}}" in sheet and ".b.ico{width:32px;height:32px;min-width:0;padding:0}" in sheet
          and "@media(pointer:coarse){.b{min-height:44px}.b.ico{width:44px;height:44px;min-height:44px}}" in sheet)
    check(f"header: {nm} page: the title row is as tall as the buttons and keeps clear of both (padding for two buttons and the gap), so the cards start below them",
          "header.top h1,header.top p.site{display:flex;align-items:center;min-height:var(--ico);padding-right:calc(24px + 2 * var(--ico))}" in sheet
          and "header.top .theme{position:absolute;top:12px;right:16px}header.top .pbtn{position:absolute;top:12px;right:calc(24px + var(--ico))}" in sheet)
    check(f"header: {nm} page: on a phone the buttons sit at the header's top padding, so they line up with the title row, and the connection notice keeps clear of them",
          "header.top{position:relative;margin:0;padding:16px 0 0;border:0;box-shadow:none}header.top .theme{top:16px;right:0}header.top .pbtn{top:16px;right:calc(8px + var(--ico))}" in sheet
          and ".conn{display:flex;align-items:center;gap:8px;margin:0 calc(24px + 2 * var(--ico, 32px)) 8px 0;" in sheet)
    check(f"header: {nm} page: the search box's input is as tall as its button (the row stretches; the input has a minimum, never a fixed height)",
          ".sbox{display:flex;align-items:stretch;" in sheet and re.search(r"\.sbox input\{[^}]*min-height:32px", sheet) is not None and re.search(r"\.sbox input\{[^}]*[^-]height:", sheet) is None, sheet[sheet.find(".sbox{"):sheet.find(".sbox{") + 300])
    if nm != "home":
        check(f"header: {nm} page: the list cards link to home with that list open, Closed to /closed", [c[0] for c in cs] == ["/#" + x[0] for x in LISTS] + ["/closed"], [c[0] for c in cs])
        check(f"header: {nm} page: no card is a bare #anchor (a page that is not home has no such section)", not any(c[0].startswith("#") for c in cs))
# ---- the header and panel layout: the cards do not change with the panel, the panel's left border runs to the top, a page's title has home's room under the header
_sheet = re.sub(r"/\*.*?\*/", "", "".join(re.findall(r"<style>(.*?)</style>", ALLPG["home"], re.S)), flags=re.S)
_dock = _sheet[_sheet.find("@media(min-width:800px){\nbody::before"):]; _dock = _dock[:_dock.find(".phead{display:none}}")]       # the wide-screen block that holds the panel's own rules
check("cards: a card's size does not follow the panel: the cards' column is capped, in every panel state, to the width it has with the panel pinned (the page's width less the panel's 288 px reserve and the body's 32 px of padding; the root element is the size container, so a classic scrollbar is left out of the width as the pinned layout leaves it out), "
      "so the cards and the container query that shortens 'Queued for release' see the same column in every panel state (the browser check measures it with and without a scrollbar)",
      "html{container:page/inline-size}nav.hcards{max-width:calc(100cqw - 320px)}" in _dock and "100vw" not in _dock.split("nav.hcards")[1][:60] and "nav.hcards{display:grid;grid-template-columns:repeat(5,minmax(0,148px))" in _sheet and "container:hcards/inline-size" in _sheet
      and "@container hcards (max-width:680px){a.hcard span .more{position:absolute" in _sheet and "body.panel-pin nav.hcards" not in _sheet and "panel-open nav.hcards" not in _sheet and "panel-peek nav.hcards" not in _sheet, _dock[-300:])
check("cards: the third card's wording ('Queued' with ' for release' clipped away in a narrow column) is the same markup on every page, whatever the panel's state: the panel's state is script and class, never part of the card markup",
      all(re.search(r'<a class="hcard" href="[^"]*#queued-release"[^>]*><b>\d+</b><span>Queued<span class="more"> for release</span></span></a>', header_of(pg)) for pg in ALLPG.values())
      and all("panel-" not in header_of(pg).replace("panel-open", "").replace("panel-pin", "") for pg in ALLPG.values()), header_of(ALLPG["item"])[-900:-500])
check("panel: its left border runs to the top of the page: the panel starts under the buttons' 56 px band, and while it is pinned or peeking a 1 px line of the panel's own colour continues its left edge up through the band, "
      "over the header and above the peeking panel, never over the buttons (it sits at the panel's left edge, 279 px from the right, the buttons are within 104 px of it)",
      'body::after{content:"";display:none;position:fixed;top:0;right:calc(280px - 1px);width:1px;height:56px;background:var(--line);z-index:31;pointer-events:none}body.panel-pin::after,body.panel-peek::after{display:block}' in _dock
      and "#panel{top:56px;height:calc(100dvh - 56px);width:280px;" in _dock and "border-left:1px solid var(--line)" in _sheet[_sheet.find("#panel{position:fixed"):][:700], _dock[-500:])
check("panel: under 800 px (the drawer) it starts at the top of the page and needs no line: no body::after outside the wide-screen block", "body::after" not in _sheet[:_sheet.find("@media(min-width:800px){\nbody::before")], "")
for nm, pg in ALLPG.items():
    if nm == "home": continue       # home's room is its first section's own 32 px (the h2 margin below); the browser check (the page script of this change's report) measures it
    sp = re.search(r"</header>\s*(<[^>]+>)", pg)
    check(f"title spacing: {nm} page: the page's title block (its h1; on a project page the small back link just above it, then the h1) follows the header directly and takes the 32 px margin above it that home has above its first section",
          bool(sp) and (sp.group(1) == "<h1>" or sp.group(1).startswith("<h1 ") or (sp.group(1) == '<p class="pjback">' and re.match(r'</header>\s*<p class="pjback"><a [^>]*>[^<]*</a></p>\s*<h1[ >]', pg[sp.start():]) is not None)), sp.group(1) if sp else None)
check("title spacing: the margin is one rule for every non-home page (item, project, Projects, Closed, Search, runners), stronger than the item page's own h1 margin (6px 0 8px), and home's section margin it copies is 32 px",
      "main header.top+h1,main header.top+p.pjback{margin-top:32px}" in _sheet and "main.itempage h1{font-size:22px;line-height:1.3;margin:6px 0 8px}" in "".join(re.findall(r"<style>(.*?)</style>", ALLPG["item"], re.S)) and re.search(r"(?:^|[};])h2\{[^}]*;margin:32px 0 12px;", _sheet) is not None, "")
hc = header_of(ALLPG["home"])
check("header: home's cards keep their own #anchors and the click that filters in place", [c[0] for c in HOME_CARDS] == ["#" + x[0] for x in LISTS] + ["/closed"]
      and "a.hcard[href^=\"#\"]" in ALLPG["home"] and "go(location.hash,false)" in ALLPG["home"] and "go(h,true)" in ALLPG["home"], [c[0] for c in HOME_CARDS])
check("header: home's header runs buttons, connection notice, title (the h1) with the rendered line beside it, cards, search box", hc.find("<header") < hc.find('id="theme"') < hc.find('id="conn"') < hc.find('<h1 class="site">') < hc.find('<p class="rline">') < hc.find('<nav class="hcards"')
      < hc.find('class="sbox"') < hc.find("</header>") and '<p class="sub">rendered' not in hc, hc[:200])
# the rendered line is one helper's markup on every page with the header: in the header's title row (beside the title, before the cards), the stale threshold and the title text on it, and the age kept by the page: home's tick, every other page's _STAMP_JS
_RL = re.compile(r'<div class="hbar">(<(?:h1|p) class="site">.*?</(?:h1|p)>)(<p class="rline"><span class="rw">rendered </span><span id="rendered" data-stale="(\d+)" title="([^"]*)">(.*?)</span></p>)</div>', re.S)
for nm, pg in ALLPG.items():
    hd = header_of(pg); m = _RL.search(hd)
    check(f"header: {nm} page: the rendered line sits in the title row, right after the site title, before the cards, once", bool(m) and hd.find('class="hbar"') < hd.find('<nav class="hcards"') and pg.count('id="rendered"') == 1, hd[:700])
    check(f"header: {nm} page: the line carries the stale threshold ({r2._stale_s()} s) and its title text", bool(m) and m.group(3) == str(r2._stale_s()) and (f"older than {r2._stale_s() // 60} minutes means the server has not published since" in m.group(4) if nm == "home"
          else re.fullmatch(r"this page was drawn at \w{3} \w{3} \d+(?:st|nd|rd|th) \d\d:\d\d; reload for the current board", m.group(4)) is not None), m and m.group(0)[:300])
    check(f"header: {nm} page: its age is kept by the page ({'the home tick' if nm == 'home' else '_STAMP_JS'}), once", (r2._STAMP_JS in pg) == (nm != "home"), nm)
check("header: a page drawn per request shows its own draw time on the line (a stamp with data-ts); home's shell has the line with no stamp", all(re.search(r'id="rendered"[^>]*><span class="tip" data-ts="\d+"', ALLPG[n]) for n in ALLPG if n != "home"))
check("header: the stamp script finds the line wherever it is and does nothing on a page without it", "if(!s)return" in r2._STAMP_JS and "getElementById('rendered')" in r2._STAMP_JS and "classList.toggle('old'" in r2._STAMP_JS)
check("header: the line is muted, warn-coloured when old, and under 600 px loses the word 'rendered'", ".rline{margin:0;flex:none;white-space:nowrap;color:var(--mut)" in _sheet and "#rendered.old{color:var(--warn)" in _sheet and "@media(max-width:600px){header.top .rline .rw{display:none}" in _sheet)
check("header: off home each card's target exists on home (a section of that id; the Closed page)", all(f'<section id="{x[0]}">' in ALLPG["home"] for x in LISTS))
check("header: the Search page's box carries the typed words, and it is the header's one box", 'value="item"' in header_of(ALLPG["Search"]) and 'value=""' in header_of(ALLPG["Search (no query)"]), header_of(ALLPG["Search"])[-300:])
check("header: every page's panel button, the item page's too, is drawn for an open panel (the closed form is the server's, for a person who closed it)",
      all('aria-expanded="true"' in header_of(pg) and 'aria-expanded="false"' not in header_of(pg) for pg in ALLPG.values()))
# the counts are live: an item that arrives shows on every page's cards at the next draw, the same number as home's
item(91, owner=A, subject="[work] a new item that waits on the owner", age=60, needs=["decision"], ask=ASK, options=OPTS)
git("add", "-A"); git("commit", "-q", "-m", "a new item")
ALLPG2 = pages_now(); H2 = cards_of(header_of(ALLPG2["home"]))
check("header: a new Your move item raises the count on home and on every other page alike", int(H2[0][1]) == int(HOME_CARDS[0][1]) + 1
      and all([c[1:] for c in cards_of(header_of(pg))] == [c[1:] for c in H2] for pg in ALLPG2.values()), [(nm, cards_of(header_of(pg))[0]) for nm, pg in ALLPG2.items()])
# cost: a page that is not home asks the release queue once and classifies the open items once for its cards
calls = {"run": 0, "classify": 0}
_run0, _classify0 = rel._run, r2._home.classify
rel._run = lambda argv: (calls.__setitem__("run", calls["run"] + 1), _run0(argv))[1]
r2._home.classify = lambda *a, **k: (calls.__setitem__("classify", calls["classify"] + 1), _classify0(*a, **k))[1]
try:
    bq = Bd(); bq.item_html("a1", answer=None, watch=None); calls_item = dict(calls)
    calls.update(run=0, classify=0); bq = Bd(); bq.landed_html(); calls_closed = dict(calls)
    calls.update(run=0, classify=0); bq = Bd(); bq.projects_html(); calls_prj = dict(calls)
finally:
    rel._run, r2._home.classify = _run0, _classify0
check("header cost: the item page, Closed and Projects ask the release queue at most once and classify the open items once for the cards (the lists are drawn once per Board)",
      calls_item["run"] <= 1 and calls_closed["run"] <= 1 and calls_prj["run"] <= 1 and calls_closed["classify"] == 1 and calls_prj["classify"] == 1 and calls_item["classify"] <= 2, (calls_item, calls_closed, calls_prj))

# ---- 12. Waiting: an item that waits on an outside event reads "On <event> · backstop <day>", never as a relay ("ask by"); an anchor wait still reads as before
import datetime as _dt
def _day(n): return (_dt.datetime.fromtimestamp(now0, _dt.timezone.utc) + _dt.timedelta(days=n)).strftime("%Y-%m-%d")
item("ev1", owner=B, project="projects/beta", subject="[home] waits for a build", wait_kind="event", wait_event="a build ends", wake=_day(3), post_wake_mover="beta-main", needs=[], next="beta-main: read the result")
item("an1", owner=B, project="projects/beta", subject="[home] waits for a review", wait_kind="anchor", wait_anchor="https://example.org/o/r/pull/9", wait_event="the review lands", wake=_day(3), post_wake_mover="beta-main", needs=[], next="beta-main: read the result")
wrows = {re.search(r'<span class="ir-id">(a\w+)</span>', li).group(1): li for li in lis(section(home_of(), "waiting-list"))}
check("Waiting: the event wait and the anchor wait are both on the list", {"aev1", "aan1"} <= set(wrows), sorted(wrows))
ev = wrows.get("aev1", "")
check("Waiting: an event wait reads 'On <event>' with its backstop day, not as a relay", "On a build ends" in ev and "· backstop" in ev and "ask by" not in ev, ev[:400])
an = wrows.get("aan1", "")
check("Waiting: an anchor wait still reads 'On <anchor>' with its backstop day", "On <a " in an and "example.org/o/r/pull/9" in an and "· backstop" in an and "ask by" not in an, an[:400])

# ---- 12b. Waiting: line one's right-hand slot is the end date the list is sorted by (home.end_of), "no end date" (dimmed) and last when there is none; the age is the hover; the other lists keep the age
item("wk1", owner=B, project="projects/beta", subject="[home] end date with a clock", age=2 * 86400, hold=True, wake="2031-03-05T09:00", post_wake_mover="beta-main", needs=[], next="beta-main: take it")
item("wk2", owner=B, project="projects/beta", subject="[home] end date a relay's ask-by day", age=86400, wait_kind="relay", wait_event="the supplier's reply", ask_by="2031-03-09", post_wake_mover="beta-main", needs=["external"], next="beta-main: take it")
item("wk3", owner=B, project="projects/beta", subject="[home] end date an anchor's backstop day", age=3600, wait_kind="anchor", wait_anchor="https://example.org/o/r/pull/38", wait_event="the review lands", wake="2031-03-12", post_wake_mover="beta-main", needs=["external"], next="beta-main: take it")
item("wk4", owner=B, project="projects/beta", subject="[home] end date none, a hold", age=4 * 86400, hold=True, next="beta-main: someone must look")
item("wk5", owner=B, project="projects/beta", subject="[home] end date none, an item wait", age=86400, after=["a4"], next="beta-main: continue once a4 is done")
h12 = home_of(); w12 = lis(section(h12, "waiting-list"))
slot12 = lambda li: re.search(r'<span class="tip ir-age ir-end[^"]*"([^>]*)>([^<]*)</span></div>', li)
by12 = {re.search(r'<span class="ir-id">(a\w+)</span>', li).group(1): li for li in w12}
check("Waiting end date: the slot shows 'until <day>' in the Mon Sep 28th form, with the time when the stored wake has one",
      all(k in by12 for k in ("awk1", "awk2", "awk3")) and [slot12(by12[k]).group(2) for k in ("awk1", "awk2", "awk3")] == ["until Wed Mar 5th 09:00", "until Sun Mar 9th", "until Wed Mar 12th"], [(k, slot12(v).group(2)) for k, v in by12.items() if slot12(v)])
check("Waiting end date: a wait with no date says 'no end date', dimmed", all(k in by12 for k in ("awk4", "awk5")) and all(slot12(by12[k]).group(2) == "no end date" and "ir-end dim" in by12[k] for k in ("awk4", "awk5")), [by12.get(k, "")[:300] for k in ("awk4", "awk5")])
check("Waiting end date: the slot is plain text (no data-ts, no live age) and the hover keeps the age ('waiting since <time>')",
      all("data-ts" not in slot12(v).group(0) and re.search(r'data-tip="waiting since \d{4}-\d\d-\d\d \d\d:\d\d (?:[A-Z]+|[+-]\d{2}(?::?\d{2})?)"', slot12(v).group(1)) for v in w12), [slot12(v).group(0) for v in w12][:3])
b12 = r2.Board(str(T / "store"), now=None); l12 = b12.home_pairs()[r2._home.WAITING]
eps12 = [r2._home.end_epoch(m) for _r, m in l12]
check("Waiting end date: the rows run by the date they show (the same reader as the sort), the dateless last", len(l12) >= 10 and eps12 == sorted(eps12) and [slot12(v).group(2) for v in w12][-2:] == ["no end date"] * 2 and
      all((slot12(v).group(2) == "no end date") == (e12 == float("inf")) for v, e12 in zip(w12, eps12)), (eps12, [slot12(v).group(2) for v in w12]))
check("Waiting end date: the slot is the stored day of home.end_of (a wake with a time keeps it, no date is None)",
      {r["gid"]: r2._home.end_of(m) for r, m in l12 if r["gid"] in ("awk1", "awk2", "awk3", "awk4", "awk5")} == {"awk1": "2031-03-05T09:00", "awk2": "2031-03-09", "awk3": "2031-03-12", "awk4": None, "awk5": None}, [(r["gid"], r2._home.end_of(m)) for r, m in l12][-6:])
y12 = lis(section(h12, "your-move")) + lis(section(h12, "agents-at-work"))
check("Your move and On agent rows keep the age: a live stamp with data-ts, no end date", len(y12) >= 3 and all(re.search(r'<span class="tip [^"]*ir-age[^"]*" data-ts="\d+"', li) and "ir-end" not in li and "until " not in li.split('class="ir-who"')[0] for li in y12))
check("Waiting end date: the detail line of a time wait is as before ('Until <day>: <why>' still leads it)", "Until Wed Mar 5th 09:00" in by12.get("awk1", "") and 'class="ir-det"><span class="hwait">Until' in by12.get("awk1", ""), by12.get("awk1", "")[-400:])

# ---- 13. page chrome: an unnamed sub-page's label, the in-place update's stamps and fingerprints, the pane-recycle line and badge,
#          the answer and back-forward cache scripts, the first-paint fold script
import datetime as _dt2
bd13 = Bd()
bd13.proj.update({"ops/gen": {"name": "gen"}, "ops/gen/sub": {}, "ops/gen/sub/deep": {}, "ops/gen/named": {"name": "Named"}})
labels = [bd13.proj_label(k) for k in ("ops/gen/sub", "ops/gen/sub/deep", "ops/gen/named", "ops/gen")]
check("a sub-page without a name is labelled by its path below its row, never the row twice", labels == ["gen/sub", "gen/sub/deep", "gen/Named", "gen"], labels)

# the page's stamp, shell and block fingerprints (the in-place update swaps only a block whose fingerprint changed)
t13 = bd13.now.replace(second=0, microsecond=0)
he = r2.Board(str(T / "store"), now=t13).html()
he2 = r2.Board(str(T / "store"), now=t13 + _dt2.timedelta(minutes=7)).html()
bm = lambda h: re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', h).group(1)
sh = lambda h: re.search(r'<meta name="stackshot-shell" content="([0-9a-f]{16})">', h).group(1)
check("the home page carries its render stamp in the head, before the shell fingerprint", f'<meta name="stackshot-rendered" content="{int(t13.timestamp())}">' in he[:900]
      and he.find('<meta name="stackshot-rendered"') < he.find('<meta name="stackshot-shell"') < 900, he[:900])
check("the 'rendered' line carries the stale threshold (1.5 times the publish period) and the page script marks it old", f'<span id="rendered" data-stale="{r2._stale_s()}"' in he and r2._stale_s() == 900
      and "g.classList.toggle('old',n-(+gs.getAttribute('data-ts'))>+g.getAttribute('data-stale'))" in he and "#rendered.old{color:var(--warn)" in he, r2._stale_s())
check("the unreachable banner is hidden and names the render time in the board's zone; the newer-board banner has its reload button",
      '<div id="conn" class="conn" role="status" aria-live="polite" hidden>' in he and f"Can't reach stackshot — showing the board as of {bd13.when(t13)}. Retrying…" in he
      and 'A newer board is available — <button type="button" id="conn-reload" class="b warn">Reload</button>' in he)
ids13 = [p.split("=")[0] for p in bm(he).split()]
check("the block fingerprints list the page's blocks by id in page order: counts and status first, then the lists, then the panel's blocks", ids13[:2] == ["counts", "status"]
      and [x for x in ids13 if x in ("your-move", "agents-at-work", "queued-release", "waiting-list")] == ["your-move", "agents-at-work", "queued-release", "waiting-list"] and {"machines", "runners", "audit-panel"} <= set(ids13), ids13)
check("a later render of the same board (ages and the 'as of' moved on) keeps every fingerprint and the shell", bm(he) == bm(he2) and sh(he) == sh(he2) and he != he2)
it13 = json.loads((T / "store/a/1.json").read_text())
try:
    (T / "store/a/1.json").write_text(json.dumps({**it13, "subject": "[work] item one renamed"}))
    he3 = r2.Board(str(T / "store"), now=t13).html()
finally:
    (T / "store/a/1.json").write_text(json.dumps(it13))
diff13 = [a.split("=")[0] for a, b_ in zip(bm(he).split(), bm(he3).split()) if a != b_]
check("a changed item changes only the blocks it is drawn in, never the shell, the counts or the machines", diff13 and "your-move" in diff13 and not {"machines", "counts", "runners"} & set(diff13) and sh(he) == sh(he3), diff13)
css0 = r2.Board._css
try:
    r2.Board._css = lambda self: css0(self) + "/*changed*/"
    sh_css = sh(r2.Board(str(T / "store"), now=t13).html())
finally:
    r2.Board._css = css0
check("a changed stylesheet changes the shell, so the open page reloads instead of swapping into an old frame", sh_css != sh(he))
L13 = r2._LIVE_JS
check("the live script is on the page; it polls the stamp uncached, every 60 s, and again on focus, online, visibility and a restored page",
      L13 in he and "/render-stamp',{cache:'no-store'" in L13 and "setTimeout(poll,down?15000:60000)" in L13 and all(f"addEventListener('{e}'" in L13 for e in ("focus", "online", "offline", "visibilitychange", "pageshow")), L13[:300])
check("the live script reloads only through reload(), only from the fallback or the banner's button; a redirect or a non-OK answer reads as unreachable",
      L13.count("location.reload") == 1 and "function reload(){ss(KY,String(window.scrollY||0));location.reload()}" in L13 and L13.count("addEventListener('click',reload)") == 1
      and "if(k==='fail')fallback(ts)" in L13 and "if(!r.ok||r.redirected)throw 0" in L13 and "try{k=apply(t)}catch(e){k='fail'}" in L13)
check("the in-place swap: a different shell or block set falls back to the reload; only a changed block is swapped; folds, the live audit card and the scroll position are kept; the stamp moves after the last block",
      "if(!SH||!sh||sh.content!==SH.content)throw 0" in L13 and "K.join(' ')!==Object.keys(V).join(' ')" in L13 and "if(V[k]===W[k])return;" in L13 and "if(k in f)d.open=f[k]" in L13
      and "if(oa&&na)na.parentNode.replaceChild(oa,na)" in L13 and "if(window.scrollY!==y)window.scrollTo(0,y)" in L13 and "R=S;M.content=String(S)}" in L13 and "document.dispatchEvent(new Event('stackshot:swapped'))" in L13)
check("a newer render is not swapped in while a field has focus or text is selected: the banner shows instead", "if(busy()||tried===ts){newer=true;return}return update(ts)" in L13 and "if(busy())return 'busy'" in L13 and "INPUT|TEXTAREA|SELECT" in L13)

# the pane-recycle line and badge
h_norec = Bd().html()
def ritem(i, ago, rec, **kw): item(i, owner=B, project="projects/beta", subject=f"[home] recycle item {i}", age=ago, recycle=rec, needs=[], **kw)
H_ = 3600
ritem(81, 5 * H_, True); ritem(82, 9 * H_, "yes"); ritem(83, 2 * H_, 1)          # open: listed, oldest update first
ritem(88, 6 * H_, True, hold=True)                                                # held for the recycle alone: listed
ritem(84, 7 * H_, "true", hold=True, wake=_day(900))                           # held for a wake as well: not listed
ritem(85, 3 * H_, True, status="completed"); ritem(86, 4 * H_, "no"); ritem(87, 1 * H_, 0)     # completed, or a falsy value: not listed
br = Bd(); hr = br.html()
rline = (lambda i: hr[i:hr.find("</p>", i)])(hr.find('<p id="recycle"'))
check("recycle: no item waits for one, no status line and no badge", '<p id="recycle"' not in h_norec and "waits for recycle" not in h_norec and "Pane recycle" not in h_norec)
check("recycle: the field reads as set for true, yes and 1, and not for false, no, 0 or absent", all(r2.waits_recycle({"metadata": {"recycle": v}}) for v in (True, "true", "TRUE", 1, "yes", "1"))
      and not any(r2.waits_recycle({"metadata": {"recycle": v}}) for v in (False, 0, "", "no", "false", None, 2)) and not r2.waits_recycle({"metadata": {}}))
check("recycle: the status line lists the open items that wait for a recycle, oldest update first, a hold for the recycle alone included", [r["gid"] for r in br.recycle] == ["a82", "a88", "a81", "a83"], [r["gid"] for r in br.recycle])
check("recycle: one plain status line under the Machines heading with each id linked (new tab, subject as tooltip), in that order",
      hr.count('<p id="recycle"') == 1 and "Pane recycle pending for" in rline and re.findall(r'/items/(a\d+)"', rline) == ["a82", "a88", "a81", "a83"]
      and 'target="_blank" rel="noopener" title="[home] recycle item 82"' in rline and hr.find('id="machines"') < hr.find('<p id="recycle"'), rline)
check("recycle: an item held for a wake as well, a completed item and a falsy value are not on the line", all(f'/items/a{g}"' not in rline for g in (84, 85, 86, 87)), rline)
RB = '<span class="badge recycle">waits for recycle</span>'
check("recycle: the badge is on the item page of an item that waits (a held one too), not on a completed one or one without the field",
      RB in br.item_html("a82") and RB in br.item_html("a84") and RB not in br.item_html("a85") and RB not in br.item_html("a86"))
check("recycle: the project page's lines carry the badge too", RB in br.routing_html("projects/beta"))

# the answer script and the back-forward cache reload
AJ13 = r2._ANSWER_JS; BJ13 = r2._BFCACHE_JS
BOX13 = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
ip13, ip13_done = Bd().item_html("a1", answer=BOX13, watch=None), Bd().item_html("a40", answer=BOX13, watch=None)
check("the answer is sent by script: a same-origin fetch of the form's fields and the pressed button, then location.replace with the item page it landed on, the buttons disabled meanwhile, a refusal inline",
      AJ13 in ip13 and all(x in AJ13 for x in ("document.querySelector('form.ianswer')", "ev.preventDefault()", "if(s&&s.name)d.append(s.name,s.value)",
                                                 "fetch(F.action,{method:'POST',body:new URLSearchParams(d),credentials:'same-origin',redirect:'follow'})", "location.replace(u.href)", "b.disabled=!on", "E.hidden=false"))
      and '<p class="isent warn aerr" role="alert" hidden></p></form>' in ip13, AJ13[:200])
check("the script returns before preventDefault when the browser has no SubmitEvent.submitter, so the plain POST still works", AJ13.index("if(s===undefined)return;") < AJ13.index("ev.preventDefault()"))
check("the answer script is only on a page with the form", AJ13 not in ip13_done and AJ13 not in ITEMP and 'class="ianswer"' not in ip13_done)
PRJP = Bd().routing_html("projects/alpha")
check("pages restored from the back-forward cache reload: the item page (with or without a form), the project page, Closed and Projects",
      "if(e.persisted)location.reload()" in BJ13 and all(BJ13 in pg for pg in (ip13, ip13_done, ITEMP, PRJP, LDP, PRJ)))

# the first-paint fold script
FH = r2._FOLD_HEAD
check("the first-paint fold script sits in the head of the item page and of the project page, before the stylesheet", all(FH in pg and pg.find(FH) < pg.find("<style>") for pg in (ITEMP, PRJP)), FH[:120])
check("the first-paint fold script applies a stored state at once and leaves a fold inside the side panel alone", "MutationObserver" in FH and "closest('#panel')" in FH and "DOMContentLoaded" in FH, FH)

# ---- 14. History after a decision, the reminder line, the comment heading, and the text helpers
ASK14 = "Decide: whether to ship the change · Recommend: ship · Stakes: none · By: Fri"
OPT14 = [{"label": "Ship", "line": "Ship it now.", "recommended": True}, {"label": "Wait", "line": "Hold it until the review.", "recommended": False}]
def rev14(i, age, **kw): item(i, owner=B, project="projects/beta", age=age, **kw); git("add", "-A"); git("commit", "-q", "-m", f"revision of {i}")
rev14(71, 3 * H_, subject="[home] decided item", needs=["decision"], ask=ASK14, options=OPT14, next="beta-main: wait for the answer")
rev14(71, 1 * H_, subject="[home] decided item", needs=[], ask=ASK14, options=OPT14, state="doing", next="beta-main: carry out the answer")          # the decision left; the stored ask and options stay
item(72, owner=B, project="projects/beta", subject="[home] still open decision", age=H_, needs=["decision"], ask=ASK14, options=OPT14, next="beta-main: wait for the answer")
b14 = Bd(); ev71 = [(k, x) for _t, k, x in b14.item_events(b14.item("a71"))[0]]
hist71 = (lambda h: h[h.find('data-fold="item.history"'):])(b14.item_html("a71", answer=None, watch=None))
check("open_ask and open_options: the ask and the options count only while the item still needs his decision", r2.open_ask(b14.item("a72")) == ASK14 and r2.open_options(b14.item("a72")) == OPT14
      and r2.open_ask(b14.item("a71")) == "" and r2.open_options(b14.item("a71")) == [] and r2.open_ask(b14.item("a40")) == "", (r2.open_ask(b14.item("a71")), r2.open_options(b14.item("a71"))))
pg71, pg72 = b14.item_html("a71", answer=BOX13, watch=None), b14.item_html("a72", answer=BOX13, watch=None)
top71 = pg71[:pg71.find('data-fold="item.history"')]
check("a decision that has left the needs draws no Ask block, no option cards and no 'Your answer' box on the item page, though the line is still stored",
      'class="iask"' not in top71 and "Recommend: ship" not in top71 and "Hold it until the review" not in top71 and "Your answer" not in pg71 and '<form class="ianswer" data-cards' not in pg71, top71[-700:])
check("an item that still needs his decision draws the Ask block and the answer box", 'class="iask"' in pg72 and "whether to ship the change" in pg72 and "Your answer" in pg72 and "Hold it until the review" in pg72)
check("the home page lists the open decision as a question and not the one that left", "a72" in section(Bd().html(), "your-move") and "a71" not in section(Bd().html(), "your-move"))
check("History keeps the ask on the line where the decision left: 'the ask was' with the Decide part, and a closed fold holding the whole ask",
      "the ask was: whether to ship the change" in hist71 and '<details class="ehold"><summary class="more">the whole ask</summary>' in hist71 and "Recommend: ship" in hist71.split("the whole ask")[1]
      and "Recommend: ship" not in re.sub(r"<details.*?</details>", "", hist71, flags=re.S) and '<details class="ehold" open' not in hist71, hist71[:900])
OPTS_HTML = '<div class="eb">the options were:</div><div class="eb osub"><b>Ship</b> (recommended): Ship it now.</div><div class="eb osub"><b>Wait</b>: Hold it until the review.'
check("History keeps the options on that line as well: 'the options were', then a bullet each with its whole sentence and the recommended one marked; a session moved it, so none is marked picked",
      OPTS_HTML + "</div>" in hist71 and "the options were: Ship" not in hist71 and "<b>picked</b>" not in hist71 and "no option was picked" not in hist71, hist71[:1200])
check("the search and migration text takes the 'the ask was' bullet alone, with no fold and no ask text beyond the Decide part", any("the ask was: whether to ship the change" in x for _k, x in ev71)
      and all("<details" not in x and "Recommend" not in x for _k, x in ev71), ev71)
# a decision he answered: History lists every option whole and marks the one he picked; a note with no pick says so; a record from before the options were kept on the answer reads them from the version before
def ans14(**k): return {"ts": now0 - 2 * H_, "kind": "decision", "via": "board", **k}
def decided14(i, ans, **left):
    rev14(i, 3 * H_, subject="[home] answered item", needs=["decision"], ask=ASK14, options=OPT14, next="beta-main: wait for the answer")
    rev14(i, 1 * H_, subject="[home] answered item", needs=[], state="doing", next="beta-main: carry out the answer", answers=[ans], **left)
    bd = Bd(); return (lambda h: h[h.find('data-fold="item.history"'):])(bd.item_html(f"a{i}", answer=None, watch=None)), [x for _t, _k, x in bd.item_events(bd.item(f"a{i}"))[0]]
h_d, e_a = decided14(190, ans14(choice="Wait", choice_line="Hold it until the review.", text="after the review", options=OPT14))      # as the server stores it: the pick took the options off the item
h_e, e_b = decided14(191, ans14(text="isn't a daily audit enough here?", options=OPT14), options=OPT14)                          # a note with no pick: the options stay on the item
h_f, e_c = decided14(192, ans14(choice="Ship", choice_line="Ship it now."))                                                      # an answer from before the options were kept on it
check("History after a pick: every option on its own bullet with its whole sentence, the recommended one marked, and the picked one marked picked",
      '<div class="eb">the options were:</div><div class="eb osub"><b>Ship</b> (recommended): Ship it now.</div><div class="eb osub"><b>Wait</b>: Hold it until the review. · <b>picked</b></div>' in h_d, h_d[:1400])
check("…only the picked option carries the mark, and his answer line stays after the options", h_d.count("<b>picked</b>") == 1 and h_d.index("the options were:") < h_d.index("(board): <b>Wait</b>"), h_d[:1400])
check("History after a note with no pick: the options are listed, none is marked, and it says no option was picked", "<b>picked</b>" not in h_e and '<div class="eb">no option was picked</div>' in h_e
      and '<div class="eb osub"><b>Wait</b>: Hold it until the review.</div>' in h_e, h_e[:1400])
check("History after an answer stored without the options: they come from the version before it, the pick is still marked", '<div class="eb osub"><b>Ship</b> (recommended): Ship it now. · <b>picked</b></div>' in h_f
      and '<div class="eb osub"><b>Wait</b>: Hold it until the review.</div>' in h_f and "no option was picked" not in h_f, h_f[:1400])
# options whose labels repeat their badge letters ("A Report"): the History lists and marks them as the card showed them, for an answer as the server stores it now (the shown label), one stored before
# (the label as stored), and one with no options of its own (read from the version before); a letter-only option is listed by its letter
OPTL = [{"label": "A Report", "line": "Write the report.", "recommended": False}, {"label": "B Plan", "line": "Plan it first.", "recommended": True}, {"label": "C Fix", "line": "Fix it now.", "recommended": False}]
OPTLO = [{"label": "A", "line": "The first way.", "recommended": False}, {"label": "B Plan", "line": "Plan it first.", "recommended": True}, {"label": "C Fix", "line": "Fix it now.", "recommended": False}]
def decidedL(i, ans, before, **left):
    rev14(i, 3 * H_, subject="[home] answered item", needs=["decision"], ask=ASK14, options=before, next="beta-main: wait for the answer")
    rev14(i, 1 * H_, subject="[home] answered item", needs=[], state="doing", next="beta-main: carry out the answer", answers=[ans], **left)
    bd = Bd(); return (lambda h: h[h.find('data-fold="item.history"'):])(bd.item_html(f"a{i}", answer=None, watch=None)), [x for _t, _k, x in bd.item_events(bd.item(f"a{i}"))[0]]
h_l1, e_l1 = decidedL(194, ans14(choice="Report", choice_line="Write the report.", letter="A", options=OPTL), OPTL)
h_l2, e_l2 = decidedL(195, ans14(choice="B Plan", choice_line="Plan it first.", options=OPTL), OPTL)
h_l3, e_l3 = decidedL(196, ans14(choice="Fix", choice_line="Fix it now.", letter="C"), OPTL)
h_l4, e_l4 = decidedL(197, ans14(choice="A", choice_line="The first way.", letter="A", options=OPTLO), OPTLO)
h_l5, e_l5 = decidedL(198, ans14(text="none of them", options=OPTL), OPTL, options=OPTL)
LBL = '<div class="eb">the options were:</div><div class="eb osub"><b>Report</b>: Write the report.{m0}</div><div class="eb osub"><b>Plan</b> (recommended): Plan it first.{m1}</div><div class="eb osub"><b>Fix</b>: Fix it now.{m2}</div>'
PK = " · <b>picked</b>"
check("History, options that repeat their letters: the labels are listed without them and the pick (stored under the shown label) is marked; his line reads \"A · Report\"",
      LBL.format(m0=PK, m1="", m2="") in h_l1 and h_l1.count("<b>picked</b>") == 1 and "(board): <b>A · Report</b>" in h_l1 and "A Report" not in h_l1, h_l1[:1600])
check("…an answer stored with the label as it was stored (\"B Plan\", before the letter was dropped on read) is marked picked too", LBL.format(m0="", m1=PK, m2="") in h_l2 and h_l2.count("<b>picked</b>") == 1, h_l2[:1600])
check("…an answer with no options of its own reads them from the version before it, stripped, the pick marked", LBL.format(m0="", m1="", m2=PK) in h_l3 and "(board): <b>C · Fix</b>" in h_l3, h_l3[:1600])
check("…a letter-only option is listed by its letter and its pick reads as the letter alone", '<div class="eb osub"><b>A</b>: The first way. · <b>picked</b></div><div class="eb osub"><b>Plan</b> (recommended): Plan it first.</div>' in h_l4
      and "(board): <b>A</b>" in h_l4 and "A · A" not in h_l4, h_l4[:1600])
check("…a note with no pick lists them stripped, none marked", LBL.format(m0="", m1="", m2="") in h_l5 and "<b>picked</b>" not in h_l5 and '<div class="eb">no option was picked</div>' in h_l5, h_l5[:1600])
check("the search text of that History reads the same", "Report: Write the report. · picked" in [re.sub(r"<[^>]+>", "", x) for x in e_l1] and "Plan (recommended): Plan it first." in [re.sub(r"<[^>]+>", "", x) for x in e_l1])
# one option's shown label equals another option's stored label ("A B Plan" is drawn "B Plan"; the second is stored "B Plan"): one option is marked, the first that matches as the pick resolves, or the one at the answer's letter
OPTD = [{"label": "A B Plan", "line": "Plan, the first way.", "recommended": False}, {"label": "B Plan", "line": "Plan, the second way.", "recommended": True}, {"label": "C Fix", "line": "Fix it now.", "recommended": False}]
h_d1, _e = decidedL(199, ans14(choice="B Plan", choice_line="Plan, the first way.", options=OPTD), OPTD)
h_d2, _e = decidedL(200, ans14(choice="B Plan", choice_line="Plan, the second way.", letter="B", options=OPTD), OPTD)
check("History, a shown label equal to another option's stored label: one option is marked, the first match", h_d1.count("<b>picked</b>") == 1 and "Plan, the first way. · <b>picked</b>" in h_d1, h_d1[:1600])
check("…and the option at the answer's letter when it carries one", h_d2.count("<b>picked</b>") == 1 and "Plan, the second way. · <b>picked</b>" in h_d2, h_d2[:1600])
LJ = r2._LIVE_JS.split("function apply(t)")[1].split("function update")[0]
check("the live refresh asks whether an answer form holds a pick or a note before it compares frames, so a refresh under way when he picks never reloads the page under the pick",
      LJ.index("if(busy())return 'busy'") < LJ.index("sh.content!==SH.content") and "input[name=choice]:checked" in r2._LIVE_JS, LJ[:500])
plain_g = [re.sub(r"<[^>]+>", "", x) for x in e_a]
check("the search text of that answer has the option lines plain, one each", "the options were:" in plain_g and "Ship (recommended): Ship it now." in plain_g and "Wait: Hold it until the review. · picked" in plain_g, plain_g)

# the reminder line: a wake alone on an open item is a reminder, never a hold
item(73, owner=B, project="projects/beta", subject="[home] reminder item", age=5 * H_, next="beta-main: look again")
git("add", "-A"); git("commit", "-q", "-m", "reminder 1")
rev14(73, 3 * H_, subject="[home] reminder item", wake=_day(4), next="beta-main: look again")
rev14(73, 1 * H_, subject="[home] reminder item", next="beta-main: look again")
ev73 = [x for _t, k, x in Bd().item_events(Bd().item("a73"))[0]]
check("History: a wake set on an open item reads 'reminder set to <day>' and clearing it reads 'reminder cleared', and neither is a hold", any(x.startswith("reminder set to ") for x in ev73)
      and "reminder cleared" in ev73 and not any("on hold" in x or "wake set" in x for x in ev73), ev73)

# the heading over the box: an item he does not decide gets a comment box, not 'Your answer'
pg_c = Bd().item_html("a4", answer=BOX13, watch=None)
check("the box is headed 'Add a comment' when no decision is open, and 'Your answer' when one is", "<b>Add a comment</b>" in pg_c and "Your answer" not in pg_c and 'name="act" value="comment"' in pg_c
      and "Your answer" in ip13 and "Add a comment" not in ip13, pg_c[pg_c.find("ianswer") - 80:][:400])

item(84, owner=B, project="projects/beta", subject="[home] his move, no decision", age=H_, mover="the owner", next="the owner: pick a colour", needs=[])
pg_m = Bd().item_html("a84", answer=BOX13, watch=None)
check("an item that is his to move but asks no decision has the same 'Add a comment' box, headed so", "<b>Add a comment</b>" in pg_m and "Your answer" not in pg_m and 'name="act" value="comment"' in pg_m, pg_m[pg_m.find("ianswer") - 80:][:300])

# a hand-over: 'handed to X, not yet taken' only for a session, never for him
item(74, owner=B, project="projects/gamma", subject="[home] handed to a session", age=H_, mover="gamma-sweeper", next="gamma-sweeper: take it", handoff={"to": "gamma-sweeper", "from": "alpha-main", "at": now0 - 600, "delivered_at": now0 - 590, "taken_at": None})
item(75, owner=B, project="projects/beta", subject="[home] handed to him", age=H_, mover="the owner", next="the owner: do it", needs=["decision"], ask=ASK14, options=OPT14, handoff={"to": "the owner", "from": "alpha-main", "at": now0 - 600, "delivered_at": now0 - 590, "taken_at": None})
item(76, owner=B, project="projects/gamma", subject="[home] handed and taken", age=H_, mover="gamma-sweeper", next="gamma-sweeper: take it", handoff={"to": "gamma-sweeper", "from": "alpha-main", "at": now0 - 600, "delivered_at": now0 - 590, "taken_at": now0 - 500})
b15 = Bd()
check("the item page says 'handed over, not yet taken' for a session that has not taken the hand-off, not for him and not for one already taken",
      "handed over, not yet taken" in b15.item_html("a74") and "not yet taken" not in b15.item_html("a75") and "not yet taken" not in b15.item_html("a76"))
def row_of14(h, gid): return next((li for li in lis(h) if f'<span class="ir-id">a{gid}</span>' in li), "")
h15 = b15.html()
check("the home row says 'handed to <session>, not yet taken' for a session, in the wrapping who line; never for his own hand-over", "handed to" in row_of14(h15, 74) and "not yet taken" in row_of14(h15, 74)
      and "not yet taken" not in row_of14(h15, 75) and "not yet taken" not in row_of14(h15, 76), (row_of14(h15, 74)[-400:], row_of14(h15, 75)[-300:]))

# the Done button and the notice after Done
HJ = r2._HOME_JS
check("home script: a button marked spent stays disabled when the page re-enables the forms, and Done names who takes it from here",
      "button[disabled]:not([data-spent])" in HJ and "b.setAttribute('data-spent','1')" in HJ and "'js.sent_done'" in HJ and "form.hstep button[value=send]" in HJ and HJ in Bd().html())
check("the item page's notice after Done names who takes the item on, and without a name says it goes on to its next mover", "Done: alpha-main takes it from here." in Bd().sent_html({"sent": "done"}, "alpha-main")
      and "goes on to its next mover" in Bd().sent_html({"sent": "done"}), Bd().sent_html({"sent": "done"}))

# markdown and links in item text
md = r2.md_block
check("markdown: an image is its plain link alone (alt text and arrow), a javascript: image stays typed, and an empty address leaves the label as plain text",
      '<a href="https://example.invalid/i.png" target="_blank" rel="noopener">an image ↗</a>' in md("![an image](https://example.invalid/i.png)") and "<img" not in md("![an image](https://example.invalid/i.png)")
      and md("![j](javascript:alert(1))") == "<p>![j](javascript:alert(1))</p>\n" and md("[x]()") == "<p>x</p>\n" and md("![a]()") == "<p>a</p>\n" and md("[]()") == "<p></p>\n", md("![an image](https://example.invalid/i.png)"))
mix = md("a [x]() b ![a]() c []() d [ok](https://example.invalid/y) [j](javascript:alert(1)) ![]()")
check("markdown: among other links only the http(s) one is a link, and no empty href is drawn", mix.count("<a ") == 1 and 'href=""' not in mix and '<a href="https://example.invalid/y"' in mix, mix)
lst = "- a\n  cont\nPlain\nPlain2\n- b\n> q\n```\n- k\nraw\n```\nafter"
check("markdown: a plain line after a list starts a paragraph of its own, but not inside a fenced block; an indented line or a quote stays where it is",
      md(lst) == "<ul>\n<li>a<br>\ncont</li>\n</ul>\n<p>Plain<br>\nPlain2</p>\n<ul>\n<li>b</li>\n</ul>\n<blockquote>\n<p>q</p>\n</blockquote>\n<pre><code>- k\nraw\n</code></pre>\n<p>after</p>\n", md(lst))
check("markdown: a bullet-dot list reads as a list", md("one\n• a\n• b") == "<p>one</p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n", md("one\n• a\n• b"))
try: bad14 = (md("see http://[x here and [a](http://[x) and http://[::1 z"), r2.md_inline("see http://[x here"), r2.linkify("see http://[x here"), r2.link_label("http://[x"))
except Exception as ex: bad14 = repr(ex)
check("markdown: an invalid IPv6 address in item text renders and does not raise, in a block, inline and as a one-line text", isinstance(bad14, tuple) and "http://[x" in bad14[0] and "here" in bad14[1] and "here" in bad14[2] and bad14[3] == "http://[x", bad14)
check("code span: <code>, verbatim, never linked and never split", r2.linkify("run `curl https://x.invalid/a?b=1`") == "run <code>curl https://x.invalid/a?b=1</code>"
      and r2.next_steps("alpha-main: run `a; b -> c` then x; y") == [(0, "alpha-main: run `a; b -> c` then x"), (0, "y")], r2.linkify("run `curl https://x.invalid/a?b=1`"))
lk = r2.linkify("see [`server.py`](https://x.invalid/s?a=1&b=2) now")
check("code span: a link whose label holds code stays one link, and a stray backtick never stops a split", lk == 'see <a href="https://x.invalid/s?a=1&amp;b=2" target="_blank" rel="noopener"><code>server.py</code> ↗</a> now'
      and r2.next_steps("it`s a; b") == [(0, "it`s a"), (0, "b")] and len(r2.sentences("one ` here\ntwo")) == 2, (lk, r2.next_steps("it`s a; b"), r2.sentences("one ` here\ntwo")))

own14 = r2._OWNER
c1 = b14.cmd_step(f"{own14}: in a terminal run `ssh -t host 'x trust'` and type `default` when asked")
c2 = b14.cmd_step(f"{own14}: run `a b` then `c d`"); c3 = b14.cmd_step("Then run `a b`"); c4 = b14.cmd_step(f"{own14}: read [`a b`](https://x.invalid/r) first")
check("command: a backticked command with a space leaves the line for its own block with a copy button, a lone word stays inline", c1.count('class="cmd"') == 1 and c1.count('class="b copy"') == 1
      and "run the command below and type <code>default</code> when asked" in c1 and "ssh -t host &#x27;x trust&#x27;" in c1, c1)
check("command: several are numbered; a line not addressed to the owner keeps them inline", "run command 1 below then command 2 below" in c2 and c2.count('class="cmd"') == 2 and c3 == "Then run <code>a b</code>", (c2, c3))
check("command: code inside a link's label is the label's and never a command", 'class="cmd"' not in c4 and "<code>a b</code> ↗</a>" in c4, c4)

# ---- 15. a doing item whose open steps are all dated for a later day reads as waiting; the Next list's bylines; three defects fixed (a stray letter, an overflowing hand-over, amber contrast)
item(78, owner=X, project="projects/alpha", subject="[work] dated wait, every step dated", age=3 * H_, state="doing", wake=_day(3), next=f"alpha-builder: after {_day(3)} read the report")
item(79, owner=X, project="projects/alpha", subject="[work] dated wait, one step undated", age=3 * H_, state="doing", wake=_day(3), next=f"alpha-builder: after {_day(3)} read the report\nalpha-builder: check the build now")
item(80, owner=X, project="projects/alpha", subject="[work] dated wait, deadline only", age=3 * H_, state="doing", wake=_day(3), next=f"alpha-builder: finish it by {_day(3)}")
b17 = Bd(); h17 = b17.html()
w17, a17 = row_ids(section(h17, "waiting-list")), row_ids(section(h17, "agents-at-work"))
check("a doing item whose open steps are all dated for a later day is listed under Waiting, not On agent", "a78" in w17 and "a78" not in a17, (w17, a17))
check("a doing item with a step that can run now, or whose date is only a deadline, stays On agent", {"a79", "a80"} <= set(a17) and not {"a79", "a80"} & set(w17), (w17, a17))
check("the dated wait row says what it waits for: 'Until <day>' and the step after the wait", "Until " in row_of14(h17, 78) and "after the wait:" in row_of14(h17, 78), row_of14(h17, 78))
check("the brief counts the doing items that read as waiting for their dates", "have a wake more than" in b17.brief(), b17.brief()[:600])

pg14 = Bd().item_html("a14")
check("Next: a done step and a dropped step each open their byline with the verb, then who and when", re.search(r'<span class="cl-by"><b>done</b> by alpha-builder · [^<]+</span>', pg14) is not None
      and re.search(r'<span class="cl-by"><b>dropped</b> by alpha-builder · [^<]+</span>', pg14) is not None, pg14[pg14.find("iearlier"):][:900])

item(77, owner="deadbeef-dead-4dea-8dea-deadbeefdead", project="projects/alpha", subject="[work] closed with no session", status="completed", age=2 * 86400, outcome="done", reason="it shipped on schedule", needs=[])
b18 = Bd(); d77 = next(r for r in b18.done if r["gid"] == "a77")
md77 = next((ln for ln in b18.markdown().splitlines() if "closed with no session" in ln), "")
check("a closed item with no session has no label: not the store letter, in the Closed row nor in the board.md line", b18.lab(d77) == "" and b18.lab(d77) != d77["L"] and md77 and " · `" not in md77 and "iown" not in row_of14(b18.landed_html(), 77), md77)
hnot = re.search(r"\.hage\.hnot\{([^}]*)\}", css)
check("the 'handed to X, not yet taken' text can shrink and break inside its row: its who line wraps anywhere, and the old age rule keeps flex:0 1 auto and min-width:0",
      re.search(r"\.ir-who\{[^}]*overflow-wrap:anywhere", css) is not None and bool(hnot) and all(x in hnot.group(1) for x in ("flex:0 1 auto", "min-width:0", "overflow-wrap:anywhere", "white-space:normal")), hnot and hnot.group(1))
lt = re.search(r":root\{--bg:(#[0-9a-f]{3,6});[^}]*--card:(#[0-9a-f]{3,6});[^}]*--warn:(#[0-9a-f]{3,6});", css)
dk = re.search(r":root\[data-theme=dark\]\{--bg:(#[0-9a-f]{3,6});[^}]*--card:(#[0-9a-f]{3,6});[^}]*--warn:(#[0-9a-f]{3,6});", css)
full6 = lambda hx: "#" + "".join(ch * 2 for ch in hx[1:]) if len(hx) == 4 else hx
check("the amber (--warn) is 4.5:1 or more as small text on the page and on a card, in light and in dark",
      bool(lt and dk) and all(ratio(full6(lt.group(3)), full6(lt.group(g))) >= 4.5 for g in (1, 2)) and all(ratio(full6(dk.group(3)), full6(dk.group(g))) >= 4.5 for g in (1, 2)),
      (lt and lt.groups(), dk and dk.groups()))

# ---- 16. a hand-edited anchors file does not fail a page; anchor waits name their anchors; no steward wording; the Closed page's script; small script and style pins
item(81, owner=B, project="projects/beta", subject="[home] anchor wait, anchors scoped to it", age=H_, wait_kind="anchor", wait_event="the review lands", wake=_day(4), post_wake_mover="beta-main", needs=[], next="beta-main: read the thread")
item(82, owner=B, project="projects/beta", subject="[home] anchor wait, none recorded", age=H_, wait_kind="anchor", wait_event="the supplier answers", wake=_day(4), post_wake_mover="beta-main", needs=[], next="beta-main: look again")
item(83, owner=B, project="projects/beta", subject="[home] item wait with only a backstop", age=H_, wait_kind="item", wake=_day(5), post_wake_mover="beta-main", needs=[], next="beta-main: look at it then")
good = [{"url": f"https://example.invalid/t/{n}", "items": ["a81"], "added": n, "by": "t"} for n in (1, 2, 3, 4)]
junk = ["junk", 7, None, {"url": "https://example.invalid/items-int", "items": 5, "added": "yesterday"}, {"url": ["x"], "items": ["a81"]}, {"url": 123, "items": ["a81"], "added": 6},
        {"url": "https://example.invalid/added-junk", "items": ["a83"], "added": "not a time"}, {"url": "https://example.invalid/added-huge", "items": ["a83"], "added": 1e300}]
anchors0 = (T / "store/anchors.json").read_text()
(T / "store/anchors.json").write_text(json.dumps({"projects/beta": good}))
bA = Bd(); hA = section(bA.html(), "waiting-list"); wr = {gid: row_of14(hA, gid) for gid in (81, 82, 83)}
check("an anchor wait whose anchors are scoped to the item names them: three on the row, the rest as '+1 more', labels that repeat numbered in the order shown",
      re.findall(r'<a href="([^"]+)"[^>]*>([^<]*)</a>', wr[81].split('class="ir-det"')[1].split('class="hnext"')[0])[:3] == [(f"https://example.invalid/t/{n}", f"example.invalid ({n})") for n in (1, 2, 3)]
      and '<span class="dim">+1 more</span>' in wr[81] and "none recorded" not in wr[81], wr[81])
check("the item page names all the scoped anchors in full", all(f'href="https://example.invalid/t/{n}"' in bA.item_html("a81") for n in (1, 2, 3, 4)))
check("an anchor wait with no anchor anywhere says so, and an item wait with only a backstop day says no item is recorded, both keeping their day",
      "an anchor (none recorded)" in wr[82] and "backstop" in wr[82] and "an item (none recorded)" in wr[83] and "back anyway" in wr[83], (wr[82], wr[83]))
check("the item page says 'an item (none recorded)' for an item wait with no item, as the row does", "an item (none recorded)" in bA.item_html("a83") and "no item stored" not in bA.item_html("a83"))
bJ = Bd()
bJ.anchors = {"projects/beta": good + junk, "projects/alpha": "junk", "projects/gamma": {"url": "x"}, "projects/delta": None}
bJ._scoped = None
try:
    hJ, pJ, iJ = bJ.html(), bJ.routing_html("projects/beta"), [bJ.item_html(g) for g in ("a81", "a82", "a83")]; errJ = ""
except Exception as ex: hJ = pJ = iJ = ""; errJ = f"{type(ex).__name__}: {ex}"
check("a hand-edited anchors file: the home page, the project page and the item pages all render", errJ == "" and 'id="waiting-list"' in hJ and "a81" in pJ and all("<h1" in x for x in iJ), errJ)
check("a hand-edited anchors file: the real anchors are named and the junk is scoped to nothing", 'href="https://example.invalid/t/1"' in hJ and "items-int" not in "".join(u for g in ("a81", "a83") for u in bJ.scoped_urls(g))
      and bJ.scoped_urls("a83") == ["https://example.invalid/added-junk", "https://example.invalid/added-huge"] and bJ.scoped_urls("a81") == [f"https://example.invalid/t/{n}" for n in (1, 2, 3, 4)], (bJ.scoped_urls("a83"), bJ.scoped_urls("a81")))
check("a hand-edited anchors file: a page whose value is no list holds no anchors, and only the readable entries count",
      all(bJ.anchor_entries(k) == [] for k in ("projects/alpha", "projects/gamma", "projects/delta")) and len(bJ.anchor_entries("projects/beta")) == len(good) + 3, [len(bJ.anchor_entries(k)) for k in ("projects/beta", "projects/alpha")])
(T / "store/anchors.json").write_text(anchors0)

# no steward wording on any page: the role is gone, the router rules every notice
pages16 = {"home": home, "Projects": PRJ, "project": PRJP, "item": ITEMP, "Closed": LDP}
check("no page says steward (home, Projects, a project page, an item page, Closed), nor does the role tip", not any("steward" in pg.lower() for pg in pages16.values()) and "steward" not in " ".join(r2._ROLE_TIP.values()).lower()
      and "steward" not in " ".join(w for v in r2.Board.WATCH.values() for w in v).lower(), [k for k, pg in pages16.items() if "steward" in pg.lower()])
check("the project page says the router rules every notice; the watch words name no steward", "the router rules every notice" in PRJP and r2.Board.WATCH["wait"][1] == "a notice is waiting for its ruling", PRJP[PRJP.find("last 24 hours"):][:200])

# the Closed page's script keeps a cleared line in place, and re-enables Clear all after a successful request
LJ = r2._LANDED_JS
check("Closed: the page script restores the Clear all button before it draws the new state, and a Clear all shows 'Clearing…' on the button alone",
      "function rest(){if(b){b.disabled=false;b.removeAttribute('aria-busy');b.textContent=lab}}" in LJ and "if(!d||!d.ok)throw 0;rest();lis.forEach(function(x){setState(x,!undo," in LJ and "if(all)b.textContent=SST('js.closed.clearing')" in LJ, LJ[1500:1900])
check("Closed: a cleared line keeps its place (no fade) and Clear and Undo share one fixed width, so the row does not jump", "li.lrow .b{transition:none}" in css
      and "li.lrow form.lclear .b,li.lrow form.lundo .b{width:64px;min-width:64px;padding-left:0;padding-right:0}" in css and re.search(r"span\.lgone\{[^}]*min-width:64px", css) is not None)
check("the stylesheet carries no board number in a note of its own", "board#" not in css and "task-a-" not in css)

# small pins: the home page drops its hash once a section has opened; the panel's close button keeps its size; the form fields keep their border, fill and placeholder tokens
check("home: a click on a link to a section opens it and the address drops the hash", "history.replaceState(null,'',location.pathname+location.search)" in home and "var go0=go;go=function(h,scroll){go0(h,scroll);if(scroll&&location.hash)" in home)
check("the panel's close button keeps its own size: a rule on .b.pbtn, which outranks the plain button's", re.search(r"\.b\.pbtn\{font-size:(?:20|22)px;line-height:1;flex:none\}", css) is not None)
check("form fields carry the border, fill and placeholder tokens in both themes", len(re.findall(r"--ibd:#[0-9a-f]{6}", css)) >= 2 and len(re.findall(r"--ifill:#[0-9a-f]{6}", css)) >= 2 and len(re.findall(r"--iph:#[0-9a-f]{6}", css)) >= 2
      and "form.hanswer textarea" in css and ".ianswer textarea" in css, re.findall(r"--i(?:bd|fill|ph):#[0-9a-f]{6}", css))
check("a section the sent notice follows: the home notice is inserted after the page header", "document.querySelector('header.top')||" in home)

# the answer boxes' resize handle: a corner grip on a fine pointer, the bottom edge still the whole handle, the height kept per box; on a coarse pointer no handle and a box that grows with its text
AJ = r2._ABOX_JS; AC = r2._ABOX_CSS
check("answer box: the markup is the textarea, then the full-width separator that is the handle (home rows and the item page alike), and the page carries the style and the script",
      all(re.search(r'<div class="abox"><textarea id="[^"]+" name="text".*?</textarea><div class="rsz" role="separator" aria-orientation="horizontal" tabindex="0" aria-controls="[^"]+" aria-label="Resize the answer box"></div></div>', pg_, re.S) for pg_ in (home, ip13))
      and AJ in ip13 and AJ in home and ".rsz::after{" in css and "(pointer:coarse){.rsz{display:none}" in css, ip13[ip13.find('class="abox"'):][:400])
check("answer box, fine pointer: the browser's own grip stays off, the whole bottom edge is the handle (row-resize, 12 px, full width) and the corner grip is drawn at its right end, nothing at the middle",
      ".abox textarea{resize:none}" in AC and ".rsz{position:absolute;left:0;right:0;bottom:0;height:12px;cursor:row-resize;" in AC and ".rsz::after{content:'';position:absolute;right:3px;bottom:2px;width:9px;height:9px;" in AC
      and "linear-gradient(135deg" in AC and "left:50%" not in AC and "padding-bottom" not in AC and ".rsz:hover,.rsz.drag,.rsz:focus-visible{--grip:var(--acc)}" in AC, AC)
check("answer box, coarse pointer: chosen by the pointer, not the width; no handle, a cap of 40% of the viewport (dvh, vh before it for an older browser) and no minimum height beyond the two lines the script sets",
      "@media(pointer:coarse){.rsz{display:none}.abox textarea{max-height:40vh;max-height:40dvh}.abox.js textarea{min-height:0}}" in AC and "max-width" not in AC and "min-width" not in AC
      and r2._ABOX_COARSE_VH == 40 and "matchMedia('(pointer: coarse)')" in AJ and "t.rows=2" in AJ and "innerWidth" not in AJ, AC)
check("answer box, coarse pointer: the script grows the box to its text (height auto, then scrollHeight plus the borders), never starts a drag or answers a handle key, and puts the rows and the kept height back on a fine pointer",
      "t.style.height='auto';t.style.height=(t.scrollHeight+b)+'px'" in AJ and "if(coarse()&&t&&t.matches&&t.matches('.abox textarea'))grow(t)" in AJ and "||coarse()||(e.pointerType==='mouse'" in AJ
      and "if(!h||coarse()||e.altKey" in AJ and "t.rows=+t.getAttribute('data-rows0')" in AJ and "MQ.addEventListener('change',init)" in AJ and "if(!t.getClientRects().length){t.style.height='';return}" in AJ, AJ)
check("answer box, fine pointer: the height is kept per box (H, keyed by the form's gid or class) and put back after the in-place swap",
      "H[key(h)]=v" in AJ and "if(h&&k in H&&!t.style.height)t.style.height=H[k]+'px'" in AJ and "document.addEventListener('stackshot:swapped',init)" in AJ and "function key(h){var f=h.closest('form');return f&&(f.getAttribute('data-gid')||f.className)||''}" in AJ)
import shutil as _sh
if _sh.which("node"):
    _jsf = T / "abox.js"; _jsf.write_text(AJ, encoding="utf-8")
    _p = subprocess.run(["node", "--check", str(_jsf)], capture_output=True, text=True)
    check("answer box: _ABOX_JS is valid JavaScript (node --check)", _p.returncode == 0, _p.stderr[:400])
    # the script itself, run in node over a stub of the few DOM calls it makes: a coarse pointer grows the box with its text and ignores a drag; a fine pointer drags the box, and the height it was given comes back after the swap
    _harness = r"""
const vm = require('vm'), fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const out = [];
function cls() { const s = new Set(); return { add: x => s.add(x), remove: x => s.delete(x), contains: x => s.has(x) }; }
function mk() {
  const at = {}, box = { classList: cls() }, form = { className: 'hanswer', getAttribute: n => n === 'data-gid' ? 'a1' : null };
  const t = { rows: 3, style: {}, scrollHeight: 40, parentNode: box, getClientRects: () => [1], getBoundingClientRect: () => ({ height: parseFloat(t.style.height) || 48 }),
    matches: q => q === '.abox textarea', hasAttribute: n => n in at, getAttribute: n => at[n], setAttribute: (n, v) => { at[n] = String(v) }, removeAttribute: n => { delete at[n] } };
  const h = { parentNode: box, classList: cls(), setAttribute() {}, closest: q => q === 'form' ? form : (q === '.rsz' ? h : null), setPointerCapture() {}, focus() {} };
  box.querySelector = q => q === '.rsz' ? h : t; return { t, h, box };
}
let cur = mk(), coarse = false; const ev = {};
const sb = { console, requestAnimationFrame: f => f(), getComputedStyle: () => ({ minHeight: '48px', borderTopWidth: '1px', borderBottomWidth: '1px' }), matchMedia: () => ({ get matches() { return coarse }, addEventListener() {} }) };
sb.window = sb; sb.innerHeight = 800; sb.scrollY = 0; sb.scrollX = 0; sb.scrollTo = () => {}; sb.addEventListener = (n, f) => { (ev[n] = ev[n] || []).push(f) };
sb.document = { addEventListener: (n, f) => { (ev[n] = ev[n] || []).push(f) }, contains: () => true, querySelectorAll: q => q === '.abox .rsz' ? [cur.h] : q === '.abox textarea' ? [cur.t] : [] };
const fire = (n, e) => (ev[n] || []).forEach(f => f(e));
const ptr = (type, y) => ({ target: cur.h, pointerId: 1, pointerType: 'mouse', button: 0, clientY: y, preventDefault() {}, type });
function check(name, ok, got) { out.push((ok ? 'ok ' : 'FAIL ') + name + (ok ? '' : ' ' + JSON.stringify(got))); }
// fine pointer
vm.runInNewContext(src, sb);
check('fine: rows untouched and the box marked for the handle', cur.t.rows === 3 && cur.box.classList.contains('js'), cur.t.rows);
fire('pointerdown', ptr('pointerdown', 100)); fire('pointermove', ptr('pointermove', 160)); fire('pointerup', ptr('pointerup', 160));
check('fine: a drag of 60 px makes the box 60 px taller', cur.t.style.height === '108px', cur.t.style.height);
fire('pointerdown', ptr('pointerdown', 100)); fire('pointermove', ptr('pointermove', 100 + 9999)); fire('pointerup', ptr('pointerup', 0));
check('fine: a drag is held to 70% of the window (560 px)', cur.t.style.height === '560px', cur.t.style.height);
fire('pointerdown', ptr('pointerdown', 100)); fire('pointermove', ptr('pointermove', 100 - 9999)); fire('pointerup', ptr('pointerup', 0));
check('fine: and held to the minimum, 48 px', cur.t.style.height === '48px', cur.t.style.height);
fire('pointerdown', ptr('pointerdown', 100)); fire('pointermove', ptr('pointermove', 160)); fire('pointerup', ptr('pointerup', 160));
const kept = cur.t.style.height; cur = mk(); fire('stackshot:swapped', {});
check('fine: the swap brings a new box, which gets the height back (' + kept + ')', cur.t.style.height === kept && cur.t.rows === 3, cur.t.style.height);
// coarse pointer
coarse = true; cur = mk(); fire('stackshot:swapped', {});
check('coarse: rows are two and the box is as high as its text (40 px + 2 borders)', cur.t.rows === 2 && cur.t.style.height === '42px', [cur.t.rows, cur.t.style.height]);
cur.t.scrollHeight = 150; fire('input', { target: cur.t });
check('coarse: typing grows the box with the text', cur.t.style.height === '152px', cur.t.style.height);
cur.t.scrollHeight = 30; fire('input', { target: cur.t });
check('coarse: deleting shrinks it again', cur.t.style.height === '32px', cur.t.style.height);
const before = cur.t.style.height; fire('pointerdown', ptr('pointerdown', 100)); fire('pointermove', ptr('pointermove', 400)); fire('pointerup', ptr('pointerup', 400));
check('coarse: no drag changes the box', cur.t.style.height === before, cur.t.style.height);
coarse = false; fire('stackshot:swapped', {});
check('coarse back to fine: rows 3 again and the height the viewer had given comes back', cur.t.rows === 3 && cur.t.style.height === kept, [cur.t.rows, cur.t.style.height]);
console.log(out.join('\n'));
"""
    _hf = T / "abox-harness.js"; _hf.write_text(_harness, encoding="utf-8")
    _r = subprocess.run(["node", str(_hf), str(_jsf)], capture_output=True, text=True, timeout=60)
    _lines = [x for x in _r.stdout.splitlines() if x.strip()]
    check("answer box: the script run in node over a stub DOM (fine: drag, cap, floor, kept after a swap; coarse: two rows, grows and shrinks with the text, no drag, back to fine)",
          _r.returncode == 0 and len(_lines) == 10 and all(x.startswith("ok ") for x in _lines), (_r.stdout + _r.stderr)[:900])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
