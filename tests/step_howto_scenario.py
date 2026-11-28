"""Scenario test for the how-to bullets drawn under the owner's open step — fixture data, no live store, no network, no server socket.

The home row's Your move entry and the item page's Your step draw his step, not the item's description, so a click path or an attachment written only in the description could not be acted on
from where he acts. Now step_howto.howto_bullets (a pure function over the description and the step) picks the description's how-to bullets and the Your step block draws them under his open step.
Nothing is stored and no write path reads it: the stored item is the same bytes after every page is drawn.

  1  the item page and the home row draw a click path and an attach-with-link under his open step, and no label, fact, date, warning, negation or past event
  2  nothing is drawn once the step has ended (a completed item, an item that is no longer his step), nor for a step that already says the bullet
  3  the detector, one case per rule: two or more arrows, attach or upload with a link; label, date, warning, negation, fact, past event, a single arrow, no link, a fenced line, a step that says it
  4  no write path changes: drawing the pages leaves the stored items byte for byte, and nothing under stackshot/service or stackshot/tools names the module
  5  a board of several members: the bullets draw under the owner's step block only, never under another member's; the stylesheet holds the list's rules
  6  the detector: an imperative opener wins over when/if, irregular past openers are out, 50000 distinct lines stop at the cap quickly

    tests/run-suite step_howto        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stephowto-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))

PATH = "Open Settings → Billing → Export CSV"
ATTACH = "Attach the file https://files.example.org/a.csv to the ticket"
DESC = "\n".join(["- Goal: send the billing export", f"- {PATH}", f"- {ATTACH}", "- Problem: the export is slow today", "- Done: 2026-11-20 the old export was removed",
                  "- Do not open Settings → Legacy → Export"])
STEP = "Export the billing CSV and attach it"
WRITTEN = {}


def item(i, description=DESC, status="open", **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": description, "status": status, "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
         "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "state": "your-step", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(d)); return d


item(1, step=STEP, owner_step=f"Oliver: {STEP}", next=f"Oliver: {STEP}\nhome-agent: check")
item(2, status="completed", step=STEP, next=f"Oliver: {STEP}\nhome-agent: check")                      # the item is over
item(3, step="", next="home-agent: check", state="working", mover="home-agent")                        # no step of his
item(4, description="- Goal: send the billing export\n- The export is slow today", step=STEP, owner_step=f"Oliver: {STEP}", next=f"Oliver: {STEP}\nhome-agent: check")   # only facts
item(5, description=f"- {PATH}\n- Problem: the export is slow today", step=f"{PATH}, then attach", owner_step=f"Oliver: {PATH}, then attach", next=f"Oliver: {PATH}, then attach\nhome-agent: check")                                      # the step already says the path
item(6, step=STEP, owner_step=f"Oliver: {STEP}", next=f"Oliver: {STEP}\nPat: Check the export looks right\nhome-agent: check")   # two members: his step is Oliver's, Pat holds an open step of his own
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

import stackshot.web.ui.render as ui_render
stored = lambda: {p.name: p.read_bytes() for p in sorted((T / "store/a").glob("*.json"))}
before = stored()
bd = ui_render.Board(str(T / "store"))
BOX = lambda i: {"action": f"/items/a{i}/answer", "token": "TOKEN", "sent": ""}
page = lambda i: bd.item_html(f"a{i}", answer=BOX(i))
def howto(h):
    m = re.search(r'<details class="istephowto">.*?<ul>(.*?)</ul></details>', h, re.S)
    return re.findall(r"<li>(.*?)</li>", m.group(1), re.S) if m else []
home = bd.html()
def row(i):
    m = re.search(rf'id="task-a-{i}"[^>]*>(.*?)(?=id="task-a-\d+"|$)', home, re.S)
    return m.group(1) if m else ""

# ---- 1. the item page and the home row
for where, h in (("page", page(1)), ("home", row(1))):
    li = howto(h)
    check(f"1 {where}: the click path and the attach line are drawn under his step, in order, and nothing else", len(li) == 2 and "Open Settings" in li[0] and "Export CSV" in li[0] and li[1].startswith("Attach the file") and "files.example.org" in li[1], (li, h[:600]))
    check(f"1 {where}: ...after his step, not before it", 0 <= h.find("Export the billing CSV and attach it") < h.find('class="istephowto"'), h[:600])
    check(f"1 {where}: the lines sit in a fold that starts closed, with the count in its summary, inside the Your step body", re.search(r'<details class="istephowto"><summary>How to \(2\)</summary>', h) is not None, h[-700:])
    check(f"1 {where}: no label, date, warning, negation or fact is drawn", not any(w in "".join(howto(h)) for w in ("Goal", "slow today", "2026-11-20", "Legacy")), h[-600:])

# ---- 2. nothing once the step ends, nor for facts, nor for what the step says
check("2 a completed item draws none", howto(page(2)) == [], page(2)[:300])
check("1 the item page holds the fold inside the Your step element", re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">.*<details class="istephowto">.*</details></div></div>', page(1), re.S) is not None, page(1)[-900:])
check("1 a home row draws no description text of its own: nothing but the step, the fold and the note form", "Problem" not in row(1) and "slow today" not in row(1), row(1)[:600])
check("2 an item that is not his step draws none", 'class="istephowto"' not in page(3) and 'class="istephowto"' not in row(3), None)
check("2 a description of facts draws none", 'class="istephowto"' not in page(4) and 'class="istephowto"' not in row(4), None)
check("2 a path the step already says is not drawn twice", 'class="istephowto"' not in page(5) and 'class="istephowto"' not in row(5), None)

# ---- 3. the detector, a case per rule
from stackshot.model import step_howto as H
S = "Do the export"
def got(*lines, step=S): return H.howto_bullets("\n".join(lines), step)
ok = lambda t: got(f"- {t}") == [t]
no = lambda t: got(f"- {t}") == []
check("3 rule: two arrows (the sign or ->) is a click path", ok("Open Settings → Billing → Export") and ok("Open Settings -> Billing -> Export"), None)
check("3 rule: one arrow is not", no("Open Settings → Billing"), got("- Open Settings → Billing"))
check("3 rule: attach or upload with a link", ok("Attach the file https://files.example.org/a.csv") and ok("Upload it to [the drive](https://files.example.org/d)"), None)
check("3 rule: attach with no link, or not at the start, is not", no("Attach the file to the ticket") and no("Then attach the file https://files.example.org/a.csv"), None)
check("3 rule: a label is not", no("Goal: Open Settings → Billing → Export") and no("Problem: Attach https://files.example.org/a.csv"), None)
check("3 rule: a date is not", no("Open Settings → Billing → Export on 2026-11-30") and no("Open Settings → Billing → Export by Friday"), None)
check("3 rule: a warning is not", no("Careful, open Settings → Billing → Export") and no("Note: Settings → Billing → Export"), None)
check("3 rule: a negation is not", no("Do not open Settings → Billing → Export") and no("Never attach https://files.example.org/a.csv") and no("Open Settings → Billing → Export without saving"), None)
check("3 rule: a fact is not", no("The menu shows Settings → Billing → Export") and no("Export is under Settings → Billing → Export"), None)
check("3 rule: a past event is not", no("Opened Settings → Billing → Export") and no("Attached https://files.example.org/a.csv"), None)
check("3 rule: a line of a fenced block, or not a bullet, is not", got("```", "- Open A → B → C", "```") == [] and got("Open A → B → C") == [], None)
check("3 rule: a nested bullet counts; order is kept and a repeat once", got("- Goal: x", "  - Open A → B → C", "- Open A → B → C", "- Upload https://x.example.org/f") == ["Open A → B → C", "Upload https://x.example.org/f"], None)
check("3 rule: a bullet the step already says is left out, and an empty step draws none", got("- Open A → B → C", step="open a → b → c, then wait") == [] and got("- Open A → B → C", step="") == [] and got("- Open A → B → C", step="  ") == [], None)
check("3 rule: at most five", len(got(*[f"- Open A{i} → B → C" for i in range(9)])) == 5, None)

# ---- 4. no write path changes
check("4 drawing the item page and the home row leave every stored item byte for byte", stored() == before, None)
srcs = "".join(p.read_text() for d in ("service", "tools") for p in (pathlib.Path(STACK) / "stackshot" / d).rglob("*.py"))
check("4 no service or tool module names the module: no write path can read it", "step_howto" not in srcs, None)

# ---- 5. several members: the bullets draw under the owner's own step block only
from stackshot.core import members as _members
OLIVER = _members.first(); PAT = _members.Person("Pat", (), ("pat@example.org",))
_members.members = lambda: [OLIVER, PAT]
mpage = lambda who: bd.item_html("a6", answer={**BOX(6), "member": who})
check("5 the owner's step block draws the bullets", len(howto(mpage("Oliver"))) == 2,mpage("Oliver")[:600])
check("5 the other member's step block (the stored step is asked of someone else) draws none", "Check the export looks right" in mpage("Pat") and 'class="istephowto"' not in mpage("Pat"), mpage("Pat")[:600])
css = bd._css()
check("5 the stylesheet has the fold's and the list's rules, muted and compact, in the shared variables", "details.istephowto>summary{" in css and "details.istephowto>ul{list-style:disc;" in css and "details.istephowto>ul>li{margin:2px 0}" in css and "color:var(--mut)" in css.split("details.istephowto>ul{", 1)[1].split("}", 1)[0], None)

# ---- 6. the detector: an imperative opener wins over when/if, irregular past openers are out, the cap
check("6 when or if after an imperative opener is kept", ok("Upload [the drive](https://files.example.org/d) when ready") and ok("Attach https://files.example.org/a.csv if asked") and ok("Open Settings → Billing → Export when ready"), None)
check("6 when or if with no imperative opener is still a fact", no("The menu shows Settings → Billing → Export when ready") and no("Settings → Billing → Export if it works") and no("Uploaded [the drive](https://files.example.org/d) when ready"), None)
check("6 an irregular past-tense opener is not a how-to bullet", all(no(f"{v} Settings → Billing → Export") for v in ("Went to", "Ran build → test →", "Sent", "Got", "Made", "Took", "Found", "Wrote", "Built", "Did")) and no("Ran build → test → deploy") and no("Went to Settings → Billing → Export"), None)
t0 = time.perf_counter(); big = got(*[f"- Open A{i} → B → C" for i in range(50000)]); dt = time.perf_counter() - t0
check("6 50000 distinct lines stop at the cap and finish in under a second", len(big) == 5 and dt < 1.0, dt)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
