"""Scenario test for the Your step block on the home page's Your move rows (ui/render.py: Board.home_step) — fixture data, no live store, no network, no server.

Covers:
  * a your-step item whose Next holds two open lines of the owner's, each with a command: the home row draws the step line, then both lines in one numbered list, without their
    `Oliver:` openers, each command in a code block with its Copy box, as the item page's Your step block does; the agent's lines are not in it; the note box and Send follow;
  * a your-step item with no open line of the owner's draws its step as before: the step line and nothing more, no list.

    tests/run-suite home_step        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="homesteptest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
STEP = "Two lines in a shell on your laptop"
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], **meta}}))
item(1, state="your-step", step=STEP, next="home-agent: prepare the box\nOliver: run `uv run tool.py --check` and read the output\nOliver: then run `git log --oneline -3` and paste it\nhome-agent: check what he pasted")
item(2, state="your-step", step=STEP, next="home-agent: prepare the box")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

import stackshot.web.ui.render as render2

def row(page, i):
    m = re.search(rf'<li class="(?:irow )?hrow" id="task-a-{i}"(?: data-st="[a-z]+")?>(.*?)</li>(?=<li class="(?:irow )?hrow"|</ul>)', page, re.S)
    return m.group(1) if m else ""

for label, mod in (("ui/render.py", render2),):
    page = mod.Board(str(T / "store")).html()
    r1, r2 = row(page, 1), row(page, 2)
    check(f"{label}: both your-step items are rows of Your move", bool(r1) and bool(r2), page[page.find('id="your-move"'):][:600])
    sn = re.search(r'<div class="istepnext">(.*?)</div>(?=<div class="hask">|</span></div><div class="ir-act">)', r1, re.S)
    sn_html = sn.group(1) if sn else ""
    check(f"{label}: the row with two open lines of his draws the step line, then his lines in one numbered list, before the note box",
          -1 < r1.find(STEP) < r1.find('<div class="istepnext">') < r1.find('<form class="hanswer hstep"') and sn_html.startswith('<ol class="stepol"')
          and sn_html.count("<li>") == 2 and "and read the output" in sn_html and "and paste it" in sn_html, r1[:1500])
    check(f"{label}: each of his two commands is a code block with its own Copy box",
          sn_html.count('<div class="cmd">') == 2 and "uv run tool.py --check</code></pre><button" in sn_html and "git log --oneline -3</code></pre><button" in sn_html
          and sn_html.count('class="b copy"') == 2, sn_html[:1200])
    check(f"{label}: the lines carry no 'Oliver:' opener and none of the agent's lines",
          "Oliver:" not in sn_html and "prepare the box" not in sn_html and "check what he pasted" not in sn_html, sn_html[:900])
    check(f"{label}: the row with no line of his draws the step as before: the step line, no list, no command block, then the note box",
          STEP in r2 and 'class="istepnext"' not in r2 and '<div class="cmd">' not in r2 and '<form class="hanswer hstep"' in r2, r2[:900])
    b = mod.Board(str(T / "store"))
    r2_item = next(x for x in b.rows if x["gid"] == "a2")
    check(f"{label}: home_step of an item with no line of his returns the step block exactly as before (the step with its draft, nothing added)",
          b.home_step(r2_item)[0] == b.step_block_html(r2_item, b.home_draft_html(r2_item)), b.home_step(r2_item)[0][:400])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
