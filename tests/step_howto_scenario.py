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
  7  English coverage: 36 real-shaped how-to lines (action openers with or without a link, click paths) are drawn; 43 label, date, warning, negation, past, fact and bare lines are not
  8  Korean coverage: 38 how-to lines (request and plain-form endings on an action verb, click paths with arrows or chevrons) are drawn; 38 label, date, warning, negation, past, fact and bare lines are not

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
check("3 rule: one arrow with no action opener is not", no("Settings → Billing") and no("Billing → done"), got("- Settings → Billing"))
check("3 rule: attach or upload with a link", ok("Attach the file https://files.example.org/a.csv") and ok("Upload it to [the drive](https://files.example.org/d)"), None)
check("3 rule: an action opener counts with or without a link, and after then or please", ok("Attach the file to the ticket") and ok("Then attach the file https://files.example.org/a.csv") and ok("Please open Settings → Billing"), None)
check("3 rule: an action word that is not the opener is not", no("The file needs to be attached to the ticket") and no("Ops will attach the file https://files.example.org/a.csv"), None)
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

# ---- 7. English: a line that tells the person to DO something (an action opener, or a click path), with or without a link; never a label, date, warning, negation, past event or fact
POS_EN = [
    "Open the billing portal", "Click Export, then choose CSV", "Go to Settings and pick the Billing tab", "Visit https://portal.example.org/billing",
    "Sign in to the portal with your work account", "Log in at https://portal.example.org", "Download the invoice from https://files.example.org/inv.pdf",
    "Upload the signed form to the shared drive", "Attach the receipt to the ticket", "Copy the reference number from the confirmation screen",
    "Paste it into the notes box of the form", "Select \"Amended return\" as the filing type", "Choose the 2025 tax year", "Press Submit when the total looks right",
    "Tap the bell icon in the top bar", "Run the export from the Reports page", "Check the refund amount on the summary screen", "Enable two-factor sign-in for the account",
    "Install the desktop app from https://example.org/app", "Share the folder with the accountant", "Send the form to the office by email", "Fill in the bank account number",
    "Review the draft before sending it", "Then open the Reports page and click Export", "Please upload the scan to the portal", "Navigate to Billing, then press Export",
    "[Portal](https://portal.example.org) → Filing → Amended return → 2025", "Reports > Billing > Export", "Open Settings → Billing", "Open https://portal.example.org and sign in",
    "Log into the portal as the account owner", "Type the invoice number in the search box", "Submit the form and keep the confirmation page", "Disable the pop-up blocker for this site",
    "First, open the Reports page", "(Optional) Export the list as CSV",
]
NEG_EN = [
    "Goal: open the billing portal", "Problem: the export button is missing", "Open the portal on 2026-12-01", "Submit the form by Friday", "Dec 3: upload the scan",
    "Warning: do not click Delete", "Careful, click Export only once", "Note: upload the draft first", "Do not upload the draft", "Never share the link", "Don't click the banner",
    "Click nothing until the page loads", "Opened the portal and exported the file", "Uploaded the scan yesterday", "Clicked Export twice", "Sent the form last week", "Went to the office",
    "The portal shows the refund amount", "The export is slow today", "The refund is due in two months", "Settings has a Billing tab", "It was sent already", "The accountant needs the form",
    "Waiting on the accountant", "Refund expected soon", "A copy of the invoice", "Check", "Open", "Review pending", "Upload failed", "Download complete", "Sign in required",
    "Open questions about the form", "Download speed is low", "Login page looks different", "Check that the total is right", "Copying is slow", "Checking the totals now",
    "Open the portal because the form is there", "Billing owns the export", "In the portal the export button sits top right", "Settings → Billing", "Refund → 360 → paid",
]
bad = [t for t in POS_EN if not ok(t)]; check(f"7 every one of {len(POS_EN)} real-shaped how-to lines is drawn", len(POS_EN) >= 25 and not bad, bad)
bad = [t for t in NEG_EN if not no(t)]; check(f"7 none of {len(NEG_EN)} label, date, warning, negation, past, fact or bare lines is drawn", len(NEG_EN) >= 25 and not bad, bad)
check("7 a numbered or starred bullet counts like a dash", got("1. Open the portal", "2) Click Export", "* Choose CSV", "• Press Submit") == ["Open the portal", "Click Export", "Choose CSV", "Press Submit"], got("1. Open the portal", "2) Click Export", "* Choose CSV"))
check("7 a day word inside another word is no date", ok("Check the monitor settings") and ok("Open the monthly report"), None)

# ---- 8. Korean: the same rules in Korean: an instruction (a request or plain-form ending on an action verb) or a click path; never a label, date, warning, negation, past event or fact
POS_KO = [
    "\ud3ec\ud138\uc5d0 \uc811\uc18d\ud574 \uc8fc\uc138\uc694", "\ud3ec\ud138\uc744 \uc5f4\uace0 \uc138\uae08\uc2e0\uace0 \uba54\ub274\ub97c \ub204\ub974\uc138\uc694", "[\ud3ec\ud138](https://portal.example.org)\uc5d0 \ub85c\uadf8\uc778\ud574 \uc8fc\uc138\uc694", "\uc99d\uba85\uc11c\ub97c \ub2e4\uc6b4\ub85c\ub4dc\ud574 \uc8fc\uc2ed\uc2dc\uc624", "\uc11c\ub958\ub97c \ub0b4\ub824\ubc1b\uc544 \ucca8\ubd80\ud55c\ub2e4",
    "\uc601\uc218\uc99d \ud30c\uc77c\uc744 \uc5c5\ub85c\ub4dc\ud558\uc138\uc694", "\uc0ac\ubcf8\uc744 \uc62c\ub824 \uc8fc\uc138\uc694", "\uc2e0\uccad\uc11c\ub97c \ucd9c\ub825\ud574 \uc8fc\uc138\uc694", "\ud658\uae09 \uae08\uc561\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694", "\uc2e0\uace0\uc11c\ub97c \uc5f0\ub2e4", "\uba54\ub274\uc5d0\uc11c \uacbd\uc815\uccad\uad6c\ub97c \uc120\ud0dd\ud558\uc138\uc694",
    "\ubc88\ud638\ub97c \ubcf5\uc0ac\ud574\uc11c \uc785\ub825\ub780\uc5d0 \ubd99\uc5ec \ub123\uc73c\uc138\uc694", "\uc81c\ucd9c \ubc84\ud2bc\uc744 \ub204\ub978\ub2e4", "\ud655\uc778 \ud654\uba74\uc5d0\uc11c \uae08\uc561\uc744 \ud655\uc778\ud55c\ub2e4", "\uc99d\uba85\uc11c\ub97c \ubc1c\uae09\ud569\ub2c8\ub2e4", "\uacc4\uc88c \uc815\ubcf4\ub97c \uc785\ub825\ud558\uace0 \uc81c\ucd9c\ud569\ub2c8\ub2e4",
    "\uad00\ud560 \uc138\ubb34\uc11c \uc0ac\uc774\ud2b8\uc5d0\uc11c \uc2e0\uccad\uc11c\ub97c \uc791\uc131\ud55c\ub2e4", "\uba54\ub274\ub97c \ubabb \ucc3e\uc73c\uba74 \ud3ec\ud138\uc5d0\uc11c '\uacbd\uc815\uccad\uad6c'\ub97c \uac80\uc0c9\ud55c\ub2e4", "\uc571\uc744 \uc124\uce58\ud558\uace0 \uc2e4\ud589\ud558\uc138\uc694", "\ud30c\uc77c\uc744 \uacf5\uc720 \ud3f4\ub354\uc5d0 \uacf5\uc720\ud574 \uc8fc\uc138\uc694", "PDF\ub85c \uc800\uc7a5\ud558\uc138\uc694",
    "\ub85c\uadf8\uc778 \ud6c4 \ub9c8\uc774\ud398\uc774\uc9c0\ub85c \uc774\ub3d9\ud55c\ub2e4", "\ub2f4\ub2f9\uc790\uc5d0\uac8c \ud30c\uc77c\uc744 \ubcf4\ub0b4 \uc8fc\uc138\uc694", "\uc11c\uba85\ud55c \ub4a4 \uc2a4\uce94\ud574\uc11c \uc62c\ub824 \uc8fc\uc138\uc694", "\uc635\uc158\uc5d0\uc11c PDF\ub97c \uace0\ub974\uc138\uc694", "\uc2e0\uccad \ubc88\ud638\ub97c \uc785\ub825\ud574 \uc8fc\uc138\uc694",
    "\ub9c1\ud06c\ub97c \ub20c\ub7ec \uc124\uce58 \ud30c\uc77c\uc744 \ubc1b\ub294\ub2e4", "\uc591\uc2dd\uc744 \uc791\uc131\ud574 \uc8fc\uc2ed\uc2dc\uc624", "\uc601\uc218\uc99d\uc744 \ucca8\ubd80\ud558\uc5ec \uc81c\ucd9c\ud558\uc2ed\uc2dc\uc624", "[\uc2e0\uccad \ud398\uc774\uc9c0](https://portal.example.org/apply)\ub97c \ubc29\ubb38\ud558\uc138\uc694",
    "(\uc120\ud0dd) \uc758\ub8cc\ube44 \ub0b4\uc5ed\ub3c4 \ucd94\uac00\ud55c\ub2e4", "\ud3ec\ud138 → \uc138\uae08\uc2e0\uace0 → \uc885\ud569\uc18c\ub4dd\uc138 → \uacbd\uc815\uccad\uad6c → 2025\ub144 (\uc548 \ubcf4\uc774\uba74 '\uacbd\uc815\uccad\uad6c' \uac80\uc0c9)", "[\ud3ec\ud138](https://portal.example.org) → \uc99d\uba85 → \ubc1c\uae09",
    "\ud3ec\ud138 > \uc99d\uba85 > \ubc1c\uae09", "\ud3ec\ud138 › \uc99d\uba85 › \ubc1c\uae09", "\uc2e0\uace0\uc11c\uc758 \uacf5\uc81c\uba85\uc138\uc11c\uc5d0\uc11c \ubc30\uc6b0\uc790 \uce78\uc774 \ube44\uc5b4 \uc788\ub294\uc9c0 \ubcf8\ub2e4 (150\ub9cc\uc6d0\uc774 \uc788\uc73c\uba74 \uccad\uad6c\ud560 \uac83\uc774 \uc5c6\uc73c\ub2c8 \uc54c\ub824 \uc8fc\uace0 \ub05d)",
    "\ud658\uae09\ubc1b\uc744 \uc18c\ub4dd\uc138\uac00 36\ub9cc\uc6d0\uc778\uc9c0 \ud655\uc778\ud55c\ub2e4", "\uc2e0\uace0\uc11c \uc885\ub958\ub97c \uc120\ud0dd(\uc77c\ubc18 \uc2e0\uace0)\ud558\uace0 \uc2e0\uace0\ud558\uae30\ub85c \ub4e4\uc5b4\uac04\ub2e4",
]
NEG_KO = [
    "\ubaa9\ud45c: \ud3ec\ud138\uc5d0\uc11c \ud658\uae09 \ubc1b\uae30", "\ubb38\uc81c: \uc81c\ucd9c \ubc84\ud2bc\uc774 \uc548 \ubcf4\uc784", "11\uc6d4 28\uc77c 14:59 \uacbd\uc815\uccad\uad6c \uc81c\ucd9c, \uc644\ub8cc \ud654\uba74 \ud655\uc778", "2026-12-01\uae4c\uc9c0 \uc81c\ucd9c\ud558\uc138\uc694", "\uae08\uc694\uc77c\uae4c\uc9c0 \uc11c\ub958\ub97c \uc81c\ucd9c\ud574 \uc8fc\uc138\uc694",
    "\uc8fc\uc758: \uc81c\ucd9c \ubc84\ud2bc\uc744 \ub450 \ubc88 \ub204\ub974\uc9c0 \ub9c8\uc138\uc694", "\uc808\ub300 \uc11c\ub958\ub97c \uacf5\uc720\ud558\uc9c0 \ub9c8\uc138\uc694", "\uc11c\ub958\ub97c \uc81c\ucd9c\ud558\uc9c0 \ub9c8\uc138\uc694", "\uc81c\ucd9c\ud558\uba74 \uc548 \ub41c\ub2e4", "\uc544\uc9c1 \ub85c\uadf8\uc778\ud560 \uc218 \uc5c6\ub2e4", "\ud3ec\ud138\uc5d0\uc11c \uc11c\ub958\ub97c \uc81c\ucd9c\ud588\uc2b5\ub2c8\ub2e4",
    "\uc601\uc218\uc99d\uc744 \uc5c5\ub85c\ub4dc\ud588\ub2e4", "\uc5b4\uc81c \ud30c\uc77c\uc744 \uc62c\ub838\ub2e4", "\uc99d\uba85\uc11c \ubc1c\uae09 \uc644\ub8cc\ub428", "\uc81c\ucd9c \uc644\ub8cc\ud568", "\ud658\uae09 \uae08\uc561\uc740 36\ub9cc\uc6d0\uc785\ub2c8\ub2e4", "\uc138\ubb34\uc11c\uac00 \uc2e0\uccad\uc744 \ud655\uc778\ud55c\ub2e4", "\ud3ec\ud138\uc740 \uc2e0\uccad\uc11c\ub97c \uc811\uc218\ud569\ub2c8\ub2e4",
    "\uc11c\ub958 \uc81c\ucd9c \uc548\ub0b4", "\uac00\uc871\uad00\uacc4\uc99d\uba85\uc11c \ucca8\ubd80 \uc5ec\ubd80", "\ud648\ud0dd\uc2a4 \uc81c\ucd9c", "\ud655\uc778 \uc911\uc785\ub2c8\ub2e4", "\uc81c\ucd9c \uc608\uc815\uc774\ub2e4", "\uc2e0\uccad\uc740 2\uac1c\uc6d4 \ub4a4\uc5d0 \ucc98\ub9ac\ub428", "\uc774 \uc808\ucc28\ub294 \ubb34\ub8cc\uc785\ub2c8\ub2e4", "\ud655\uc778", "\uc81c\ucd9c",
    "\ub9c1\ud06c → \uc81c\ucd9c", "\ub85c\uadf8\uc778 \ud654\uba74\uc774 \uc5f4\ub9ac\uc9c0 \uc54a\ub294\ub2e4", "\uc65c \ub85c\uadf8\uc778\uc774 \uc548 \ub429\ub2c8\uae4c?", "\uc11c\ub958\uac00 \uc811\uc218\ub41c\ub2e4", "\uae08\uc561 \ud655\uc778\ub41c\ub2e4", "\uac00\uc871\uad00\uacc4\uc99d\uba85\uc11c \ucca8\ubd80 \uc5ec\ubd80\ub294 \ub2f4\ub2f9\uc790\uac00 \ud655\uc778 \uc911",
    "\uae08\uc561\uc774 \ub2e4\ub974\uac70\ub098 \uc2e0\uace0 \ub0b4\uc5ed\uc774 \uc548 \ub098\uc624\uba74, \uc81c\ucd9c\ud558\uc9c0 \ub9d0\uace0 \ud654\uba74\uc758 \ubb38\uad6c\ub97c \uc54c\ub824 \uc900\ub2e4", "\ucc38\uace0\ub85c \uc2e0\uccad\uc11c\ub97c \ucd9c\ub825\ud574 \ub450\uc5c8\ub2e4", "5\uc6d4 \uc2e0\uace0\uc11c\ub97c \ud655\uc778\ud588\uace0 \uc81c\ucd9c\ud588\ub2e4",
    "\ud3ec\ud138 → 100 → 200", "\uc2e0\uccad\uc11c\ub97c \uc81c\ucd9c\ud568",
]
bad = [t for t in POS_KO if not ok(t)]; check(f"8 every one of {len(POS_KO)} Korean how-to lines is drawn", len(POS_KO) >= 25 and not bad, bad)
bad = [t for t in NEG_KO if not no(t)]; check(f"8 none of {len(NEG_KO)} Korean label, date, warning, negation, past, fact or bare lines is drawn", len(NEG_KO) >= 25 and not bad, bad)
check("8 a Korean line the step already says is not drawn twice", got("- \ud3ec\ud138\uc5d0 \uc811\uc18d\ud574 \uc8fc\uc138\uc694", step="\ud3ec\ud138\uc5d0 \uc811\uc18d\ud574 \uc8fc\uc138\uc694, \uadf8\ub2e4\uc74c \ud655\uc778") == [], None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
