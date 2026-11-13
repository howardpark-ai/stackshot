"""Scenario test for the step of a your-step item as a numbered list with commands to copy, and its write guards (step_commands.py) — fixture data, no live store, no network, no server socket.

A your-step item is written by update(step=…), which stores the state with the step (the state input of update is retired: tests/retired_inputs_scenario.py); fixtures store `state` and `step` directly.

  1  the field: a step with a numbered line or a fenced block keeps its lines (caps relaxed: 3000 characters, 20 lines, 500 on a line); any other step stays one line of at most 300
  2  the parts: numbered lines make one ordered list, commands (a span with a space in it, a fenced block) go under their item, a fenced block outside a list stands alone
  3  the page: the item page's Your step block and the home row's step draw an <ol> with a copy block for each command, escaped, the draft inside the step that uses it; a one-line step is drawn as ever
  4  guard 1: a shell command in the description of a your-step item with the owner as the mover is refused, pointing at step (Japanese and English text around it)
  5  guard 2: a step with a command names where it runs (PowerShell, Windows, パワーシェル, ウィンドウズ; a `! ` pane line is refused since); a terminal on box-a is no place
  6  guard 3: bash for box-a is refused with the ssh form named; ssh, a cmdlet and the cross-platform tools pass
  7  guard 4: a step that points elsewhere is refused (see the description, see below, 説明を参照, 下の説明を参照); "the command below" is no pointer
  8  scope: only a your-step item with the owner as the mover, only writes that set the state, step, mover, description or draft; [model] guards = false skips them
  10 the tool text: create and update say it (the snapshot)
  12 a next line that starts with the owner's name passes the step's Windows-command check: the same judgement and text ("next line:"), on create and update; other lines are not judged
  14 no pane form on the board: a `! ` line in a step or in a Oliver: line of next is refused and the refusal gives the ssh form; another agent's line and "done!" pass
  15 the tool text and the client's usage: where a command runs, per [steps] owner_shell (the client's usage has no place line any more: post state is retired)
  11 the description is the Background: on an item that is his to move (him as mover, your-step, your-call) a numbered line or a `! ` line is refused, judged on what the write adds

    tests/run-suite step        → exit 0 / 1"""
import html, json, os, re, subprocess, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="draft-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the your-step form, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-stew")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); H = 3600.0; DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", desc=None, subject=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H, "state_updated": now0 - 3 * H,
                                                      "confirmed": now0 - 3 * H, "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / (f"store/{i[0]}/{i[1:]}.json" if isinstance(i, str) else f"store/a/{i}.json")).read_text())
mt = lambda i: rd(i)["metadata"]


def nx(i):
    """The next lines a session wrote: the stored next without the line the server made for the item's step of his."""
    m = mt(i)
    return "\n".join(ln for ln in str(m.get("next") or "").split("\n") if ln != str(m.get("owner_step") or "\0"))
raw = lambda i: (T / f"store/a/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import draft as D; from stackshot.github import ghsync; from stackshot.web import home; from stackshot.model import model
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.service import telling
from stackshot.web.ui import render as ui_render

def live_tools():
    """The tool text of this scenario's own instance: owner Oliver with his shell rule (box-a, PowerShell) and his aliases, as the tools render it for him. The expected
    sentences below name the owner as "the owner", so his name is put back to that form here; everything else is the live text, which is why a change to the shell sentences still fails these checks."""
    import asyncio
    return {t.name: {"description": (t.description or "").replace("Oliver", "the owner")} for t in asyncio.run(server.mcp.list_tools())}
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: server._update(f"a{i}", sender=sender, **kw)
get = lambda i: _wt_get.stackshot_get(f"a{i}")

from stackshot.model import step_commands as SC; from stackshot.model import states
GUARDS = server._cfg.CFG.setdefault("model", {})
HOW = dict(mover="Oliver", then="team-back", needs=["team-back"], state="your-step", next="team-back: check it")
BOX = {"action": "/items/a4/answer", "token": "TOKEN", "sent": ""}
page = lambda i, **kw: ui_render.Board(f"{tmp}/store").item_html(f"a{i}", **kw)
SSH1 = "ssh -t box-a 'sala op reauth box-a --from me --words go'"
SSH2 = "ssh -t box-a 'tmux ls'"
NC = ("In PowerShell, do these in order:\n1. Run the first command and wait for the line that says queued\n2. Run the second command and read the list\n3. Tell me done on the item")      # a numbered step with no command: what a write may set now
NUMBERED = (f"In PowerShell, do these in order:\n1. Run `{SSH1}` and wait for the line that says queued\n2. Run `{SSH2}` and read the list\n"
            "3. Tell me done on the item")


def P(step="", desc=DESC, mover="Oliver", state="your-step", status="open"):
    """The guard's reading of an item as a write would leave it."""
    return SC.problem({"status": status, "description": desc, "metadata": {"state": state, "mover": mover, "step": step}})


# ================================================================ 1. the field
item(1, needs=["team-back"], next="team-back: build it")
out = upd(1, step=NC)
check("1 field: a numbered step is stored with its lines", mt(1)["step"] == NC and mt(1)["state"] == "your-step", mt(1).get("step"))
check("1 field: get shows it as a `step:` block with its lines", "step: In PowerShell, do these in order:\n1. Run the first command" in get(1), get(1))
item(2, needs=["team-back"], next="team-back: build it")
upd(2, step="In PowerShell run\n  the first command\n  and say   done")
check("1 field: a step with no numbered line or fence is one line as ever", mt(2)["step"] == "In PowerShell run the first command and say done", mt(2))
item(3, needs=["team-back"], next="team-back: build it")
upd(3, step="In PowerShell:\r\n\r\n1.   First   thing\r\n\r\n2. Second\r\n")
check("1 field: blank lines outside a fence are dropped, spaces in a line collapsed", mt(3)["step"] == "In PowerShell:\n1. First thing\n2. Second", repr(mt(3)["step"]))
check("1 field: …a fence's text is kept as written (a stored step, since a write that sets a step with a fence is refused: a fence is a command)",
      states.step_text("In PowerShell:\r\n1. First thing\r\n```\r\nssh -t box-a 'ls   -la'\r\n\r\n   indented\r\n```\r\n") == "In PowerShell:\n1. First thing\n```\nssh -t box-a 'ls   -la'\n\n   indented\n```", None)
many = "In PowerShell:\n" + "\n".join(f"{n}. step {n}" for n in range(1, 20))        # 20 lines
upd(3, step=many)
check("1 field: 20 lines of a numbered step are stored (a one-line step stops at 300 characters)", mt(3)["step"].count("\n") == 19, None)
refused_nw("1 field: 21 lines are refused, naming the cap", 3, lambda: upd(3, step=many + "\n20. one more"), "at most 20 lines")
refused_nw("1 field: a numbered step over 3000 characters is refused", 3, lambda: upd(3, step="In PowerShell:\n" + "\n".join(f"{n}. " + "x" * 450 for n in range(1, 8))), "at most 3000 characters")
refused_nw("1 field: a line over 500 characters outside a fence is refused, pointing at a fenced block", 3, lambda: upd(3, step="In PowerShell:\n1. " + "x" * 520), "500 characters on a line", "``` block")
check("1 field: …a long command inside a fenced block is fine for the length rule (the fence itself is refused by a write: see 12)", states.step_problem("In PowerShell:\n1. run it\n```\nssh -t box-a '" + "x" * 700 + "'\n```") == "", None)
refused_nw("1 field: a plain step over 300 characters is still refused", 3, lambda: upd(3, step="x" * 301), "at most 300 characters on one line", "lines of next")
check("1 field: states.step_text / step_problem on their own", states.step_text("a\n b") == "a b" and states.step_text("1. a\n b") == "1. a\n b" and states.step_problem("1. " + "y" * 10) == "" and states.step_problem("z" * 301) != "", None)
item(4, needs=["team-back"], next="team-back: build it")
upd(4, step=" \n ")
check("1 field: a step of only whitespace is no step: it stores neither a step nor the your-step state (the old refusal went with the state input)", "step" not in mt(4) and "state" not in mt(4), mt(4))

# ================================================================ 2. the parts
pp = SC.parse("Do:\n1. one `ssh -t box-a 'a b'` two\n   continued\n```bash\nssh -t box-a 'x'\n```\n2) two\n\n3. three\nAfter that\n```\nGet-Date -Format o\n```\n5. a new list")
check("2 parts: a plain line, one list of three items (a continuation joins its item), a text, a fence of its own, a second list that keeps its number",
      [p.kind for p in pp] == ["text", "ol", "text", "cmd", "ol"] and [len(p.items) for p in pp if p.kind == "ol"] == [3, 1] and pp[1].items[0].text == "one `ssh -t box-a 'a b'` two continued"
      and pp[1].items[0].fences == ["ssh -t box-a 'x'"] and pp[3].text == "Get-Date -Format o" and pp[4].start == 5, pp)
t, c = SC.split_spans("Run `ssh -t box-a 'a b'` then `Get-Date -Format o` and `lone` word")
check("2 parts: commands leave the line for 'command 1 below' placeholders, a lone word stays inline", c == ["ssh -t box-a 'a b'", "Get-Date -Format o"] and t == "Run command 1 below then command 2 below and `lone` word", (t, c))
check("2 parts: one command is 'the command below'; a span after a colon at the line's end is dropped; a line of commands only has no text",
      SC.split_spans("Run `a b c` now")[0] == "Run the command below now" and SC.split_spans("In PowerShell: `a b c`") == ("In PowerShell:", ["a b c"]) and SC.split_spans("`a b` and `c d`") == ("", ["a b", "c d"]), None)
check("2 parts: structured() is true for a numbered line or a fence, not for prose with a number in it", SC.structured("1. a") and SC.structured("x\n2) b") and SC.structured("```\nx y\n```") and not SC.structured("Step 1. do it") and not SC.structured("run 3. times"), None)
check("2 parts: an unclosed fence runs to the end; an empty one is dropped", SC.parse("```\nssh -t box-a 'a'")[0].text == "ssh -t box-a 'a'" and SC.parse("```\n```\n1. x")[0].kind == "ol", None)

# ================================================================ 3. the page
item(10, subject="[home] reauth", **HOW, step=NUMBERED, draft="Hi Kim,\nthe text\n")
p10 = page(10, answer=BOX)
blk = re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">(.*?)</div></div><form class="ianswer"', p10, re.S)
b10 = blk.group(1) if blk else ""
check("3 page: the Your step block holds the intro line, then one ordered list of three items", bool(blk) and b10.startswith('<p class="sp">In PowerShell, do these in order:</p><ol class="stepol">') and b10.count("<li>") == 3 and b10.count("</ol>") == 1, b10[:400])
check("3 page: …item 1 and item 2 each carry one copy block, item 3 none, under their text", [li.count('class="cmd"') for li in re.findall(r"<li>(.*?)</li>", b10, re.S)] == [1, 1, 0], b10)
cmds = re.findall(r'<div class="cmd"><pre><code>(.*?)</code></pre><button type="button" class="b copy" aria-label="Copy to the clipboard">Copy</button></div>', b10, re.S)
check("3 page: …the blocks hold the commands exactly (escaped), and the text says 'the command below'", [html.unescape(x) for x in cmds] == [SSH1, SSH2] and b10.count("the command below") == 2, cmds)
check("3 page: …the draft comes after the whole list, before the note box and the buttons", b10.index("</ol>") < b10.index('<div class="draft">') and p10.index('<div class="draft">') < p10.index('<form class="ianswer"'), None)
CSS = ui_render.Board(f"{tmp}/store")._css()
check("3 page: the list and its blocks are styled, the copy script is on the page", "ol.stepol{" in CSS and ".stepol .cmd{" in CSS and "closest('button.copy')" in p10, None)
item(11, **HOW, step="In PowerShell:\n1. Open the settings\n```\nssh -t box-a 'uptime'\n```\n2. Say done\n```\nGet-Date\n```", draft=None)
p11 = page(11, answer=BOX)
check("3 page: a fenced block after an item sits in that item; one before any list is a block of its own", re.findall(r"<li>(.*?)</li>", p11, re.S)[0].count('class="cmd"') == 1 and re.findall(r"<li>(.*?)</li>", p11, re.S)[1].count('class="cmd"') == 1, None)
item(12, **HOW, step="Fenced first, in PowerShell:\n```\nssh -t box-a 'ls'\n```\n1. then say done")
p12 = page(12, answer=BOX)
check("3 page: …(a fence before the first number is a block of its own, outside the list)", p12.index('class="cmd"') < p12.index('<ol class="stepol">'), None)
HOST = "In PowerShell:\n1. <img src=x onerror=alert(1)> & \"q\" run `ssh -t box-a 'echo <script>alert(2)</script> && echo \"x\"'` [x](javascript:alert(3))\n```\n<b>raw</b> & more y\n```"
item(13, **HOW, step=HOST)
p13 = page(13, answer=BOX)
check("3 page: hostile text is only text: no tag, no handler, no javascript link, commands escaped", "<script>alert" not in p13 and "<img src=x" not in p13 and "<b>raw</b>" not in p13 and 'href="javascript:' not in p13
      and "&lt;script&gt;alert(2)&lt;/script&gt; &amp;&amp; echo &quot;x&quot;" in p13 and "&lt;b&gt;raw&lt;/b&gt; &amp; more y" in p13 and "&lt;img src=x onerror=alert(1)&gt;" in p13, p13[p13.find("Your step"):][:900])
p10b = page(10)
check("3 page: signed out, the Your step block draws the same list", '<ol class="stepol">' in p10b and p10b.count('class="cmd"') == 2, None)
item(14, **HOW, step="In PowerShell run `ssh -t box-a 'ls'` and say done")
p14 = page(14, answer=BOX)
check("3 page: a one-line step is drawn as ever (the text, then its block) with no list", '<ol class="stepol">' not in p14 and "the command below" in p14 and p14.count('class="cmd"') == 1, None)
item(15, **HOW, step="1. Only one numbered line")
check("3 page: one numbered line is a list of one", '<ol class="stepol"><li>Only one numbered line</li></ol>' in page(15, answer=BOX), None)

b = ui_render.Board(f"{tmp}/store")
pairs = b.home_pairs()
ym = {r["gid"]: (r, m) for r, m in pairs[home.YOUR_MOVE]}
r10 = b.home_row(*ym["a10"], home.YOUR_MOVE)
check("3 home: the Your move row draws the same list with a copy block per command, under the guide line", '<ol class="stepol">' in r10 and r10.count('class="cmd"') == 2 and r10.index("In PowerShell, do these") < r10.index('<ol class="stepol">') < r10.index('class="draft hdraft"') < r10.index('<form class="hanswer hstep"'), r10[:1500])
r13 = b.home_row(*ym["a13"], home.YOUR_MOVE)
check("3 home: hostile text is only text on the row too", "<script>alert" not in r13 and "<img src=x" not in r13 and "<b>raw</b>" not in r13 and "&lt;script&gt;alert(2)&lt;/script&gt;" in r13, None)
r14 = b.home_row(*ym["a14"], home.YOUR_MOVE)
check("3 home: a one-line step row is as ever", "stepol" not in r14 and r14.count('class="cmd"') == 1, None)

# ================================================================ 4. guard 1: no shell command in the description
FENCED = "- Run it\n```bash\nsudo systemctl restart stackshot\n```\n- Done when green"
for name, d in (("a fenced block with a command", FENCED), ("a console fence with a $ prompt", "- x\n```console\n$ git pull --rebase\n```"), ("a powershell fence", "- x\n```powershell\nGet-Process -Name claude\n```"), ("a sh fence, upper case tag", "- x\n```SH\nuv run tests/x.py\n```"), ("cd", "- Oliver: run `cd ~/stackshot && ./deploy.sh`"), ("./", "- Start `./deploy.sh --dry-run`"),
                ("~/", "- Run `~/bin/tool go`"), ("sudo", "- `sudo reboot now`"), ("ssh", "- `ssh -t box-a 'ls'` first"), ("git", "- `git pull --rebase`"), ("python3", "- `python3 tools/x.py --json`"),
                ("uv", "- `uv run tests/x.py`"), ("sala", "- `sala op ready x --from me`"), ("curl", "- `curl -s https://example.com/x`"), ("a pane line", "- type `! sala reauth x`"),
                ("an env prefix", "- `FOO=1 uv run tests/x.py`"), ("Japanese text around it", "- オリバー: `sala op recycle x --from y` を実行します"), ("a cmdlet", "- `Get-Process -Name claude`"), ("a Windows path", "- `C:\\tools\\x.exe --go`")):
    w = P(step="In PowerShell run `ssh -t box-a 'ls'` and say done", desc=d)
    check(f"4 guard 1: a description with {name} is refused, naming description and the line of next", w.startswith("description:") and "line of next" in w and "(`" in w, w)
for name, d in (("plain bullets", DESC), ("a file path", "- It lives in `~/stackshot/render.py` and `tests/x.py`"), ("a lone word", "- uses `git` and `uv` and `sala`"), ("a field name", "- set `state=your-step` and `step`"),
                ("a fence of text", "- Quote\n```\nhello there everyone\n```"), ("an untagged fence of pasted output", "- Got\n```\nsudo systemctl restart stackshot\nsala op ready x\n```"), ("a text-tagged fence", "- Got\n```text\nsala op ready x --from me\n```"), ("Japanese prose", "- 確認すること: `state=your-step` です"), ("a sentence with a path", "- the file ./notes.md holds it"), ("a url", "- see `https://example.com/a b`")):
    check(f"4 guard 1: …{name} in the description passes", P(step="In PowerShell run `ssh -t box-a 'ls'` and say done", desc=d) == "", P(step="In PowerShell run `ssh -t box-a 'ls'` and say done", desc=d))
# wired into the writes
item(40, **HOW, step="In PowerShell run `ssh -t box-a 'ls'` and say done")
refused_nw("4 write: a description write with a command on a your-step item for him is refused", 40, lambda: upd(40, description="- A thing\n- Run `sala op ready x --from me`\n- Done when done"), "a40: description:", "line of next")
upd(40, description="- A thing\n- It lives here\n- Done when done")
check("4 write: …and a clean description goes through", rd(40)["description"].startswith("- A thing"), None)
item(41, desc="- A thing\n- Run `sala op ready x --from me`\n- Done when done", needs=["team-back"], next="team-back: build it")
refused_nw("4 write: moving an item to your-step with a command left in its description is refused", 41, lambda: upd(41, step="In PowerShell run `ssh -t box-a 'ls'` and say done"), "description:")
upd(41, step="In PowerShell run the Oliver: line of Next and say done", description="- A thing\n- It lives here\n- Done when done")
check("4 write: …but the one write that cleans the description and sets a summary step is accepted", mt(41)["state"] == "your-step" and "sala" not in rd(41)["description"], None)

# a description write is judged only on the commands it adds or changes
OLDD = "- A thng\n- Run `sala op ready x --from me`\n- Done when done"
item(70, desc=OLDD, **HOW, step="In PowerShell run `ssh -t box-a 'ls'` and say done")
upd(70, description="- A thing\n- Run `sala op ready x --from me`\n- Done when done")
check("4 diff: a typo fixed beside an old command passes", rd(70)["description"].startswith("- A thing\n"), rd(70)["description"])
refused_nw("4 diff: …a new command in the write is refused, with the hint", 70, lambda: upd(70, description="- A thing\n- Run `sala op ready x --from me`\n- Also `uv run tests/x.py`"), "a70: description:", "drop the backticks or the fence")
refused_nw("4 diff: …a changed command is refused", 70, lambda: upd(70, description="- A thing\n- Run `sala op ready y --from me`\n- Done when done"), "description:")
refused_nw("4 diff: …a write that leaves the description alone is still judged against the stored one", 70, lambda: upd(70, mover="Oliver", priority="p2", step="In PowerShell run `ssh -t box-a 'pwd'`"), "description:")
check("4 diff: problem() with a prior judges the added commands only; a removed one passes; whitespace is not a change", SC.problem({"status": "open", "description": "- a\n- `sala op x  y`", "metadata": {"state": "your-step", "step": "Call"}}, "- b\n- `sala op x y`") == ""
      and SC.problem({"status": "open", "description": "- a", "metadata": {"state": "your-step", "step": "Call"}}, "- b\n- `sala op x y`") == ""
      and SC.problem({"status": "open", "description": "- `sala op x y`\n- `sala op x y`", "metadata": {"state": "your-step", "step": "Call"}}, "- `sala op x y`") != "", None)
# the finding-fixes: false positives pass, the true cases still refuse
for lbl in ("Make a copy", "Sort by date", "Go to settings", "Find and replace", "top 5", "Free trial", "Cut and paste", "More options", "Less is more", "Head to the office", "Watch the video", "Mount the drive", "Screen time", "Reg ister", "Sc ore"):
    check(f"5b labels: `{lbl}` in a step is not a command: the step passes with no place named", P(step=f"Click `{lbl}` and say done") == "", P(step=f"Click `{lbl}` and say done"))
    check(f"5b labels: …nor in a description", P(step="In PowerShell run `ssh -t box-a 'ls'` and say done", desc=f"- Click `{lbl}`\n- A\n- B") == "", None)
for c in ("make -j4 all", "go build ./...", "find . -name x", "sort -u f.txt", "top -b", "make CC=gcc test", "head -n 5 notes.txt", "watch -n 5 ls", "free -m", "mount /dev/sda1 /mnt"):
    check(f"5b labels: …`{c}` is a command: refused with no place named", "does not say where it runs" in P(step=f"Run `{c}` and say done") or "bash for box-a" in P(step=f"Run `{c}` and say done"), P(step=f"Run `{c}` and say done"))
check("5b labels: …`make -j4` with a place named passes (not Linux-only)", P(step="In PowerShell run `make -j4 all`") == "", P(step="In PowerShell run `make -j4 all`"))
check("5b labels: …`free -m` and `mount /dev/sda1 /mnt` are bash for box-a", "bash for box-a" in P(step="In PowerShell run `free -m`") and "bash for box-a" in P(step="In PowerShell run `mount /dev/sda1 /mnt`") and P(step="In PowerShell run `free trial`") == "", None)
w = P(step="Run `sala op x y`")
check("5b labels: both refusals add the label hint, and the bash one says to name a Windows path", "a button or menu label is not a command: use bold or quotes, not backticks" in w and "if this is a Windows path, say so" in w
      and "a button or menu label is not a command: use bold or quotes, not backticks" in P(step="Run `ssh -t box-a 'ls'`"), w)
check("5b wsl: WSL names a place", P(step="In WSL run `ssh -t box-a 'ls'` and say done") == "" and P(step="In wsl: `ssh -t box-a 'ls'`") == "", None)
check("5b claude: a fenced line after a bare claude line is REPL input and is skipped (bash included)", P(step="In PowerShell:\n```\nclaude\nsala op ready x\n```") == ""
      and "bash for box-a" in P(step="In PowerShell:\n```\nsala op ready x\nclaude\n```") and "bash for box-a" in P(step="In PowerShell:\n```\nsudo reboot\nclaude\n```"), P(step="In PowerShell:\n```\nclaude\nsala op ready x\n```"))
check("5b points: details and a bare check are no pointer; see/refer to/as described in followed by description, below or above still are", all(P(step=t) == "" for t in ("Check the details of the invoice and approve", "Read the details above the table and say done", "Check below the fold"))
      and all("points elsewhere" in P(step=t) for t in ("See the description", "see below", "Refer to the description", "Refer to above", "As described in the description", "As described in below", "説明を参照", "下の説明を参照")), None)

for lbl in ("Export data", "Source code", "Kill switch", "Ping me", "Docker Desktop", "Claude Code", "Git Settings", "Python 3.12", "Su Kim", "Free up 5.5 GB", "Sort by Date/Time", "Make 4.0", "Top 10 5.5"):
    check(f"5c titles: `{lbl}` is a label or a name: the step and the description pass", P(step=f"Click `{lbl}` and say done") == "" and P(step="In PowerShell run `ssh -t box-a 'ls'` and say done", desc=f"- Open `{lbl}`\n- A\n- B") == "", P(step=f"Click `{lbl}` and say done"))
for lbl in ("free up 5.5 GB", "sort by Date/Time", "make 4.0", "top 3.12", "free trial 5.5"):
    check(f"5c titles: …lower case `{lbl}`: version, size and Date/Time are no argument", P(step=f"Click `{lbl}` and say done") == "", P(step=f"Click `{lbl}` and say done"))
for c in ("Docker run -it x", "Git pull --rebase", "Export -x data", "Ping /n 3 host", "Kill $pid now", "Source ./env.sh", "Cat ~/notes.txt", "sort -u Date/Time", "sort by notes.txt", "free 5.5 -m"):
    check(f"5c titles: …`{c}` still reads as a command (a flag follows)", P(step=f"Run `{c}` and say done") != "", P(step=f"Run `{c}` and say done"))
check("5c titles: a cmdlet, a path and a drive letter are commands whatever the case; a /x flag must be a whole token", "does not say where" in P(step="Run `Get-Process claude`") and "does not say where" in P(step="Run `C:\\tools\\x.exe go`")
      and "does not say where" in P(step="Run `Ping /n 3 host`") and P(step="Run `Ping /n/x host`") == "", None)
# a write that newly moves an item into your-step is judged on its whole description
item(71, desc=OLDD, needs=["team-back"], next="team-back: build it")
refused_nw("4 diff: a write that newly moves the item to your-step for him judges the whole description even when it also changes it", 71, lambda: upd(71, step="In PowerShell run `ssh -t box-a 'ls'` and say done", description="- A thing\n- Run `sala op ready x --from me`\n- Done when done"), "a71: description:")
item(72, desc=OLDD, needs=["team-back"], next="team-back: build it", mover="team-back")
refused_nw("4 diff: …also when the mover changes to him in that write", 72, lambda: upd(72, mover="Oliver", step="In PowerShell run `ssh -t box-a 'ls'` and say done", description="- A thing\n- Run `sala op ready x --from me`\n- Done when done"), "description:")
upd(71, step="In PowerShell run the Oliver: line of Next and say done", description="- A thing\n- It lives here\n- Done when done")
check("4 diff: …and a clean description in that write goes through", mt(71)["state"] == "your-step", None)
# ================================================================ 5. guard 2: where it runs
for name, s in (("English, no place", "Run `ssh -t box-a 'ls'` and say done"), ("a terminal on box-a", "In a terminal on box-a run `ssh -t box-a 'ls'`"),
                ("Japanese, no place", "次のコマンドを実行してください `ssh -t box-a 'ls -la'`"), ("a fenced block, no place", "1. Run this\n```\nssh -t box-a 'ls'\n```"),
                ("a numbered list, no place", "1. Run `ssh -t box-a 'ls'`\n2. Say done"), ("the word in the command only", "Run `ssh -t box-a 'echo windows powershell'`"),
                ("a cmdlet, no place", "Run `Get-Process -Name claude` and say done"), ("a pane line, no pane", "Type `! sala reauth x` and say done"), ("a pane, no session", "In the pane type `! sala reauth x`"),
                ("a bare ! step", "! sala reauth box-a"), ("a pane line, pane named", "In ops-x's pane type `! sala reauth x` and say done"),
                ("a pane line, Japanese", "ops-x のペインで `! sala reauth x` を入力してください"), ("both kinds, both named", "In PowerShell: `ssh -t box-a 'ls'`, then in ops-x's pane: `! sala reauth x`")):
    w = P(step=s)
    check(f"5 guard 2: {name} is refused: 'step:' and where it runs", w.startswith("step:") and ("does not say where it runs" in w or "typed into a session's pane" in w) and "\n" not in w, w)
for name, s in (("PowerShell", "In PowerShell run `ssh -t box-a 'ls'` and say done"), ("Windows", "On your Windows machine, run `ssh -t box-a 'ls'`"), ("pwsh", "In pwsh: `Get-Process -Name claude`"),
                ("パワーシェル", "パワーシェルで `ssh -t box-a 'ls -la'` を実行してください"), ("パワーシェール spelled the other way", "パワーシェールで `Get-Process -Name claude` を実行"), ("ウィンドウズ", "ウィンドウズで `ssh -t box-a 'ls'` 実行"),
                ("a numbered list", "In PowerShell:\n1. Run `ssh -t box-a 'ls'`\n2. Say done"), ("a fenced block", "In PowerShell:\n```\nssh -t box-a 'ls'\n```"),
                ("no command at all", "Call the office and say done"),
                ("a lone word is no command", "Open the `Settings` app and say done"), ("a link", "Sign in at https://example.com/login and say done")):
    check(f"5 guard 2: …{name} passes", P(step=s) == "", P(step=s))
check("5 guard 2: …both kinds with only the shell place named is refused for the pane", "pane" in P(step="In PowerShell: `ssh -t box-a 'ls'`, then `! sala reauth x`"), P(step="In PowerShell: `ssh -t box-a 'ls'`, then `! sala reauth x`"))

# ================================================================ 6. guard 3: bash for box-a
for name, c in (("sala", "sala op ready x --from me"), ("systemctl", "systemctl --user status stackshot"), ("./", "./deploy.sh now"), ("ls with a flag", "ls -la ~/x"),
                ("grep", "grep -r foo /home/user"), ("python3", "python3 tools/x.py"), ("a $( )", "echo $(date)"), ("sudo", "sudo reboot now"), ("journalctl", "journalctl --user -u x"), ("tmux", "tmux attach -t x"),
                ("an env prefix", "TZ=Asia/Dubai journalctl -n 5"), ("an absolute path", "/usr/bin/env python3"), ("chmod", "chmod +x run.sh")):
    w = P(step=f"In PowerShell run `{c}` and say done")
    check(f"6 guard 3: `{c}` is bash for box-a: refused with the ssh form named", w.startswith("step:") and "ssh -t box-a '<command>'" in w and "bash for box-a" in w, w)
for name, c in (("ssh", "ssh -t box-a 'sala op ready x'"), ("a cmdlet", "Get-Process -Name claude"), ("winget", "winget upgrade --id Example.Tool"), ("git", "git pull --rebase"), ("gh", "gh pr view 5"),
                ("vpn", "vpn status --json"), ("uv", "uv tool install x"), ("curl", "curl -s https://example.com/x"), ("ls of a Windows path", "ls C:\\Users"), ("a drive path", "C:\\tools\\x.exe --go"),
                ("a variable", "$env:USERPROFILE --x"), ("cat a file", "cat notes.txt"), ("cd to a ~/ path", "cd ~/Documents"), ("cat a ~/ file", "cat ~/notes.txt"), ("git -C a ~/ path", "git -C ~/repo pull"), ("a ~/ program", "~/bin/tool go")):
    check(f"6 guard 3: …`{c}` runs in PowerShell: passes", P(step=f"In PowerShell run `{c}` and say done") == "", P(step=f"In PowerShell run `{c}` and say done"))
check("6 guard 3: a `! ` line is refused as the pane form, not as bash for box-a", "bash for box-a" not in P(step="In ops-x's pane: `! sala reauth x`") and P(step="In ops-x's pane: `! sala reauth x`").startswith("step: a `! ` line"), P(step="In ops-x's pane: `! sala reauth x`"))
check("6 guard 3: a fenced block is judged line by line (comments, blank and continuation lines skipped)", P(step="In PowerShell:\n```\n# check it\nssh -t box-a 'ls' `\n  -x\n\nssh -t box-a 'pwd'\n```") == ""
      and "sala op" in P(step="In PowerShell:\n```\nssh -t box-a 'ls'\nsala op ready x\n```"), P(step="In PowerShell:\n```\nssh -t box-a 'ls'\nsala op ready x\n```"))
check("6 guard 3: …and bash is named before a missing place", "bash for box-a" in P(step="Run `sala op ready x`"), P(step="Run `sala op ready x`"))

# ================================================================ 7. guard 4: points elsewhere
for s in ("See the description for the commands", "Run the commands in the description", "see description", "See below", "The steps are below", "The commands are below, please read", "As described in the description",
          "Refer to the description first", "説明を参照", "下の説明を参照", "下の内容を参照してください", "説明を参照して実行してください", "本文を参照", "詳細は説明欄を参照", "上の説明を参照"):
    w = P(step=s)
    check(f"7 guard 4: {s!r} points elsewhere: refused, in one line naming step", w.startswith("step: it points elsewhere") and "\n" not in w, w)
for s in ("Run the command below in PowerShell: `ssh -t box-a 'ls'`", "下のコマンドをパワーシェルで実行してください `ssh -t box-a 'ls'`", "In PowerShell:\n1. Run the command below\n```\nssh -t box-a 'ls'\n```",
          "Update the description field in Notion and say done", "Check the details of the invoice and approve", "Read the details of the offer and say done", "Check below the table and say done", "Per Kim, send it", "Open the page at the bottom and say done", "Run `ssh -t box-a 'echo see the description'` in PowerShell"):
    check(f"7 guard 4: …{s[:50]!r} is no pointer", P(step=s) == "", P(step=s))
check("7 guard 4: the pointer is judged before the commands", "points elsewhere" in P(step="See the description: `sala op ready x`"), None)

# ================================================================ 8. scope
check("8 scope: an agent as the mover is not his step", P(step="See below", mover="team-back") == "" and P(step="Run `sala op x y`", mover="team-back") == "", None)
check("8 scope: another state, or a closed item, is not judged", P(step="See below", state="doing") == "" and P(step="See below", status="completed") == "", None)
check("8 scope: the owner's own name as the mover is his step; no stored mover too", P(step="See below", mover="Oliver") != "" and P(step="See below", mover="") != "" and P(step="See below", mover=None) != "", None)
item(50, desc="- A thing\n- Run `sala op ready x --from me`\n- Done when done", **HOW, step="In PowerShell run `ssh -t box-a 'ls'` and say done")
upd(50, priority="p1")
check("8 scope: a write that sets none of the state, step, mover, description or draft is never held up by an old item's text", mt(50).get("priority") == "p1", None)
upd(50, next="team-back: check it again")
check("8 scope: …nor a next", nx(50) == "team-back: check it again", mt(50)["next"])
item(55, **HOW, step="Call the office and say done")
refused_nw("8 scope: a step write is judged", 55, lambda: upd(55, step="See below"), "points elsewhere")
refused_nw("8 scope: …so is a draft write (the whole item is judged)", 50, lambda: upd(50, draft="x y z"), "description:")
refused_nw("8 scope: …and a mover write", 50, lambda: upd(50, mover="Oliver"), "description:")
GUARDS["guards"] = False
upd(50, step="See below `sala op x y`")
check("8 scope: [model] guards = false skips them", mt(50)["step"] == "See below `sala op x y`", None)
GUARDS["guards"] = True
item(52, needs=["team-back"], next="team-back: build it")
upd(52, description="- A thing\n- Run `sala op ready x --from me`\n- Done when done")
check("8 scope: a doing item may hold a command in its description", "sala op" in rd(52)["description"], None)
item(53, needs=["team-back"], next="team-back: build it")
upd(53, step="Call the office and say done")
check("8 scope: a plain step with no command is accepted as ever", mt(53)["step"] == "Call the office and say done", None)
item(54, needs=["team-back"], next="team-back: build it")
upd(54, step="Post the message in #general (the text is on the item)", draft="the text")
check("8 scope: a step with a draft and no command is accepted (the draft guard's own business)", mt(54)["draft"] == "the text", None)
refused_nw("8 write: the refusal is one line that starts with the item and names the field", 54, lambda: upd(54, step="Run `sala op ready x`"), "Refused: a54: step:")
try:
    upd(54, step="Run `sala op ready x`")
except Exception as e:
    check("8 write: …on one line", "\n" not in str(e), str(e))

# ================================================================ 11. the description is the Background: no numbered steps, no `! ` line
def PD(desc, prior=None, mover="Oliver", state="your-step", status="open", step="Call the office and say done"):
    """The guard's reading of an item as a write would leave it, with the description it replaces."""
    return SC.problem({"status": status, "description": desc, "metadata": {"state": state, "mover": mover, "step": step}}, prior)
w = PD("- A thing\n- 1. Open the page\n- 2. Say done")
check("11 unit: a numbered line in the description of his item is refused, naming description, Background and step", w.startswith("description: it holds numbered steps") and "Background" in w and "step=" in w and '("Open the page")' in w, w)
check("11 unit: …the bare form `1.` and `2)` too, after any bullet marker", all("numbered steps" in PD(d) for d in ("1. Open the page\n2) Say done", "2) Say done", "* 3. Say done", "  - 4. Say done", "- 12. Say done")), None)
check("11 unit: …a fenced block holds output or commands judged elsewhere: its numbered lines are not steps", PD("- A thing\n```\n1. one\n2. two\n```\n- Done when done") == "" and PD("- A thing\n~~~text\n1. one\n~~~") == "", None)
check("11 unit: …a number inside a line, a version, a year, a decimal and a bang with no space are no step",
      all(PD(d) == "" for d in ("- Ship 4. Later", "- 1.2 released", "- 2026. A year", "- Wow! Really", "- !important", "- Step 1 of the plan", "- Done in 3. Then more", "- 1.x branch", "- 7th. day")), [d for d in ("- Ship 4. Later", "- 1.2 released", "- 2026. A year", "- Wow! Really", "- !important", "- Step 1 of the plan", "- 1.x branch") if PD(d)])
w = PD("- A thing\n- ! sala reauth box-a")
check("11 unit: a `! ` line is refused, pointing at the line of next and the pane", w.startswith("description: it holds a `! ` line") and "line of next" in w and "pane" in w, w)
check("11 unit: …a `!` inside a sentence or a quoted span is not that line", PD("- Run it, then say! done\n- The `! ` prefix types into a pane") == "", PD("- Run it, then say! done\n- The `! ` prefix types into a pane"))
OLD11 = "- A thng\n- 1. Open the page\n- 2. Say done"
check("11 diff: judged on what the write adds: a typo fixed beside old numbered lines passes, a new numbered line or a changed one is refused",
      PD("- A thing\n- 1. Open the page\n- 2. Say done", OLD11) == "" and "numbered steps" in PD("- A thing\n- 1. Open the page\n- 2. Say done\n- 3. Also this", OLD11)
      and "numbered steps" in PD("- A thng\n- 1. Open the page\n- 2. Say it is done", OLD11) and PD("- A thng\n- 2. Say done", OLD11) == "", None)
check("11 diff: …the number itself is not what counts (renumbering a kept step passes); the same line twice is two", PD("- 2. Open the page\n- 3. Say done", OLD11) == "" and "numbered steps" in PD("- 1. Open the page\n- 1. Open the page", "- 1. Open the page"), None)
check("11 diff: …the `! ` lines the same", PD("- Fine\n- ! sala reauth x", "- Fine\n- ! sala reauth x") == "" and "`! ` line" in PD("- Fine\n- ! sala reauth x\n- ! sala reauth y", "- Fine\n- ! sala reauth x"), None)
# who it reaches: his items only (the narrowest form of "never steps")
NUM = "- A thing\n- 1. Open the page\n- 2. Say done"
check("11 scope: reached: him as the stored mover in any state, your-step or your-call whoever the mover, and a your-step with no mover",
      all("numbered steps" in PD(NUM, mover=m, state=st) for m, st in (("Oliver", "doing"), ("Oliver", ""), ("Oliver", "your-call"), ("team-back", "your-call"), ("team-back", "your-step"), ("", "your-step"), (None, "your-call"))), [(m, st) for m, st in (("Oliver", "doing"), ("team-back", "your-call"), ("team-back", "your-step")) if not PD(NUM, mover=m, state=st)])
def PN(needs, desc=NUM, status="open", **meta):
    return SC.problem({"status": status, "description": desc, "metadata": {"needs": needs, **meta}})
check("11 scope: his decision counts with no state and no mover stored (derived your-call): needs=decision or the old one-word kind is refused; needs=an agent passes",
      all("numbered steps" in PN(n) for n in (["decision"], ["Decision"], ["team-back", "decision"])) and all(PN(n) == "" for n in (["team-back"], [], ["external"])) and PN(["decision"], status="completed") == "", [PN(n) for n in (["decision"], ["oliver"], ["team-back"])])
check("11 scope: …a stored state that is not his, with his decision in needs, is still his; the stored mover of an agent with an agent in needs is not",
      "numbered steps" in PN(["decision"], state="doing", mover="team-back") and PN(["team-back"], state="doing", mover="team-back") == "", None)
item(84, desc=DESC, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: low · By: Fri", next="Oliver: decide")
refused_nw("11 write: an item with needs=decision and no state or mover stored is his: a numbered description line is refused", 84, lambda: upd(84, description="- A thing\n- 1. Open the page\n- Done when done"), "a84: description:", "numbered steps")
item(85, desc=DESC, needs=["team-back"], mover="team-back", next="team-back: build it")
upd(85, description="- A thing\n- 1. Build it\n- Done when done")
check("11 write: …an item with an agent in needs keeps it", "- 1. Build it" in rd(85)["description"], None)
check("11 scope: not reached: an agent's own item (doing, queued, blocked, parked, no state), a waiting item, or a closed one keeps its multi-step description",
      all(PD(NUM, mover="team-back", state=st) == "" for st in ("doing", "queued", "blocked", "parked", "verifying", "outside", "")) and PD(NUM, mover="team-back", state="") == "" and PD(NUM, status="completed") == "", None)
check("11 scope: a backticked command stays judged on your-step with him as the mover only (an agent-moved your-call item may name one)",
      "shell command" in PD("- Run `sala op ready x --from me`") and PD("- Run `sala op ready x --from me`", mover="team-back", state="your-call") == "" and PD("- Run `sala op ready x --from me`", mover="Oliver", state="doing") == "", None)
check("11 scope: a description with both a command and a numbered line names the command first", "shell command" in PD("- 1. Run `sala op ready x --from me`"), PD("- 1. Run `sala op ready x --from me`"))
check("11 unit: description_steps returns the lines it found outside fences (the numbered lines' text, the `! ` lines whole)", SC.description_steps("- 1. a\n```\n2. b\n```\n- ! c\n3) d") == (["a", "d"], ["- ! c"]), SC.description_steps("- 1. a\n```\n2. b\n```\n- ! c\n3) d"))
# through the tools
item(80, desc=DESC, **HOW, step="Call the office and say done")
refused_nw("11 write: a numbered description line on his your-step item is refused, pointing at step", 80, lambda: upd(80, description="- A thing\n- 1. Open the page\n- Done when done"), "a80: description:", "numbered steps", "step=")
refused_nw("11 write: …and a `! ` line", 80, lambda: upd(80, description="- A thing\n- ! sala reauth x\n- Done when done"), "a80: description:", "`! ` line", "line of next")
upd(80, description="- A thing\n- It lives here, step 1 is in Your step\n- Done when done")
check("11 write: …a clean description goes through", "step 1 is in Your step" in rd(80)["description"], None)
item(81, needs=["team-back"], mover="team-back", next="team-back: build it")
upd(81, description="- A thing\n- 1. Build it\n- 2. Test it\n- Done when done")
check("11 write: an agent's own item keeps its multi-step description", "- 2. Test it" in rd(81)["description"], None)
item(82, desc=DESC, mover="Oliver", then="team-back", needs=["team-back"], next="team-back: check it")
refused_nw("11 write: an item with him as the mover in no state is his: refused", 82, lambda: upd(82, description="- A thing\n- 1. Open the page\n- Done when done"), "a82: description:", "numbered steps")
item(83, desc="- A thng\n- 1. Open the page\n- 2. Say done", **HOW, step="Call the office and say done")
upd(83, description="- A thing\n- 1. Open the page\n- 2. Say done")
check("11 write: a stored numbered description is not a block: a typo fixed beside the old lines goes through", rd(83)["description"].startswith("- A thing\n"), rd(83)["description"])
refused_nw("11 write: …a numbered line the write adds is refused", 83, lambda: upd(83, description="- A thing\n- 1. Open the page\n- 2. Say done\n- 3. And this"), "a83: description:", "numbered steps")
refused_nw("11 write: …and moving the item to him is judged on the whole stored description", 81, lambda: upd(81, step="Call the office and say done", mover="Oliver"), "a81: description:", "numbered steps")
GUARDS["guards"] = False
upd(80, description="- A thing\n- 1. Open the page\n- Done when done")
check("11 write: [model] guards = false skips it", "1. Open the page" in rd(80)["description"], None)
GUARDS["guards"] = True
SNAP11 = live_tools()
check("11 text: update's and create's description call the description the item's background and send steps and commands to step",
      all("the item's background" in SNAP11[k]["description"] and "never steps or commands for the owner" in SNAP11[k]["description"] for k in ("create", "update")), None)
check("11 text: …update says which writes are refused and that the description is the background, never steps",
      all(t_ in SNAP11["update"]["description"] for t_ in ("adds a numbered line (`1.`, `2)`) or a `! ` line outside a fenced block", "the description is the background, never steps", "him as mover, in his step, or with his decision in needs")), None)

# ================================================================ 12. the owner's next lines pass the step's Windows-command check
from stackshot.model import model_guards as mg
BARE = "Oliver: run `bash /home/user/notes/x.sh` in a terminal on box-a"
WRAP = "Oliver: In PowerShell run `ssh -t box-a 'bash /home/user/notes/x.sh'`"
BARE_BODY = "run `bash /home/user/notes/x.sh` in a terminal on box-a"
nl = lambda why: why.replace("step: ", "next line: ", 1)
check("12 unit: the step's refusal for the bare line's command, with the field word changed, is the next line's",
      SC.command_problem(BARE_BODY, "next line") == nl(SC.command_problem(BARE_BODY)) != ""
      and SC.command_problem(BARE_BODY, "next line").startswith("next line: `bash /home/user/notes/x.sh` is bash for box-a"), None)
own = lambda t: [x for x, _ in mg.owner_next_lines(t)]
SAMPLE = "Oliver: a\n- AE: b\n* **オリバー:** c\n1. Oliver to d\nyou: e\nteam-back: Oliver: f\n(server note)\nask Oliver: g\nOliver's turn: h"
check("12 unit: his lines are Oliver:, AE:, オリバー:, `Oliver to`, `you:`, with a marker or bold; a session's line, a note and his name in a body are not",
      own(SAMPLE) == ["Oliver: a", "- AE: b", "* **オリバー:** c", "1. Oliver to d", "you: e"], own(SAMPLE))
ol = mg.owner_next_lines("team-back: x\n```\nOliver: in a session's fence\n```\nOliver: In PowerShell:\n  1. run `ssh -t box-a 'ls'`\n```\nssh -t box-a 'tmux ls'\n```\nteam-back: y `bash /home/user/x.sh`\nOliver: later")
check("12 unit: a line takes its indented continuation and a fenced block under it; a fence's text (under any line) is no line of his; the next top-level line ends it",
      [x for x, _ in ol] == ["Oliver: In PowerShell:", "Oliver: later"] and "ssh -t box-a 'ls'" in ol[0][1] and "ssh -t box-a 'tmux ls'" in ol[0][1] and "session's fence" not in ol[0][1] + ol[1][1] and "bash /home" not in ol[0][1] + ol[1][1], ol)
# ---- update
item(120, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
refused_nw("12 update: a Oliver next line with a bare box-a command is refused with the step's text, naming the next line", 120, lambda: upd(120, next=BARE),
           "next line: `bash /home/user/notes/x.sh` is bash for box-a", "write it \"In PowerShell:\" `ssh -t box-a '<command>'`")
try:
    upd(120, next=BARE); got12 = ""
except Exception as e:
    got12 = str(e)
check("12 update: …the whole refusal is `Refused: ` + the step's text with `next line` for `step`", got12 == "Refused: " + nl(SC.command_problem(BARE_BODY)), got12)
upd(120, next=WRAP)
check("12 update: the same line wrapped the way the step check accepts (ssh form, PowerShell said) passes", nx(120) == WRAP, mt(120)["next"])
check("12 update: …and the step check accepts that text too", SC.command_problem("In PowerShell run `ssh -t box-a 'bash /home/user/notes/x.sh'`") == "", None)
item(121, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
upd(121, next="team-back: run `bash /home/user/notes/x.sh` on box-a")
check("12 update: a line for another session with the same command passes", "team-back: run `bash" in mt(121)["next"], mt(121)["next"])
item(122, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
PULL = "run `git -C ~/repo pull`"
refused_nw("12 update: a Oliver line whose command is no bash for box-a and says no place is refused, as the step is (a terminal on box-a is no place)", 122,
           lambda: upd(122, next=f"Oliver: {PULL} in a terminal on box-a"), "next line: it has a command but does not say where it runs", "a terminal on box-a is not a place")
upd(122, next=f"Oliver: In PowerShell {PULL}")
check("12 update: …and passes once it says PowerShell, as the step does", mt(122)["next"].startswith("Oliver: In PowerShell"), mt(122)["next"])
check("12 update: …the step check gives the same verdicts (no for 'in a terminal on box-a' and 'on box-a', yes for PowerShell)",
      SC.command_problem(f"{PULL} in a terminal on box-a") != "" and SC.command_problem(f"{PULL} on box-a") != "" and SC.command_problem(f"In PowerShell {PULL}") == "", None)
item(123, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
for variant in ("AE: run `sala op x y` in a terminal", "- Oliver: run `systemctl --user status x` on box-a", "オリバー: `./deploy.sh now` 実行"):
    refused_nw(f"12 update: {variant[:28]!r} is his line too", 123, lambda v=variant: upd(123, next=v), "next line:")
refused_nw("12 update: a continuation line of his line is read with it", 123, lambda: upd(123, next="Oliver: run this\n  `sala op reauth box-a --from me --words go`"), "next line: `sala op reauth")
upd(123, next="Oliver: open the page and say done, see `ssh` notes\nteam-back: then `bash /home/user/x.sh` runs")
check("12 update: prose and a lone word in backticks, and another session's command, pass", "say done" in mt(123)["next"], mt(123)["next"])
# a stored bad line is not rejudged by a write that does not set next
item(124, needs=["team-back"], next=BARE, state="your-step", step="Read the lines in Next and say done")
upd(124, priority="p1")
check("12 update: a stored bad Oliver line never holds up a write that leaves next alone", mt(124).get("priority") == "p1", mt(124))
GUARDS["guards"] = False
upd(123, next=BARE)
check("12 update: [model] guards = false skips it", nx(123) == BARE, mt(123)["next"])
GUARDS["guards"] = True
# ---- create
ASK12 = "Decide: run the script now · Recommend: yes · Stakes: a day of delay · By: no date"      # a create has no state to store, so a Oliver next line goes with needs=decision and an ask (an agent state under it would be refused)
refused("12 create: a Oliver next line with a bare box-a command is refused with the step's text",
        lambda: _wt_create._create(subject="[home] case-a bare", description=DESC, project="projects/alpha", owner="home-front", next=BARE, needs=["decision"], ask=ASK12), "next line: `bash /home/user/notes/x.sh` is bash for box-a")
out12 = _wt_create._create(subject="[home] case-a wrapped", description=DESC, project="projects/alpha", owner="home-front", next=WRAP, needs=["decision"], ask=ASK12)
check("12 create: the wrapped line passes", "Refused" not in str(out12) and "case-a wrapped" in str(out12) or "created" in str(out12).lower(), out12)
out12 = _wt_create._create(subject="[home] case-a other session", description=DESC, project="projects/alpha", owner="home-front", next="team-back: run `bash /home/user/notes/x.sh` on box-a", needs=["team-back"])
check("12 create: another session's line with the same command passes", "Refused" not in str(out12), out12)
# ---- the model guards name it
rep12 = mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": BARE}}, mg.Ctx(), touched={"next"})[0]
check("12 guard: it is a key of GUARDS with a label, and check names it", "next_windows" in mg.GUARDS and "next_windows" in mg.LABELS and [p.key for p in rep12] == ["next_windows"], rep12)

# ---- the scope: only a line that asks him to run something (a review)
B3 = "`" * 3
MENTIONS = [
    "Oliver: decide whether `git push --force origin main` is safe",
    "Oliver: approve `sala op recycle box-a --from me --words go` when you see it",
    "Oliver: the fix is `systemctl --user restart stackshot` once the unit is read",
    "Oliver: set `timeout = 30` in the config",
    "Oliver: `/home/user is full`, free some space",
    f"Oliver: paste this reply:\n{B3}\nsala op recycle box-a is queued\n{B3}",
    "Oliver: say whether `bash /home/user/x.sh` should stay",
]
for k_, line_ in enumerate(MENTIONS):
    check(f"12 scope: a line that only mentions a command is not judged ({k_})", mg.ask_to_run(mg.owner_next_lines(line_)[0][1]) == "", line_)
item(130, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
for k_, line_ in enumerate(MENTIONS):
    if B3 in line_:
        continue                                          # (a fence in next is refused by the placeholder guard, whatever this one says)
    upd(130, next=line_)
    check(f"12 scope: …and an update writing it goes through ({k_})", nx(130) == line_, mt(130)["next"])
refused_nw("12 scope: `Oliver: run `bash /home/user/x.sh` in a terminal on box-a` is still refused", 130, lambda: upd(130, next="Oliver: run `bash /home/user/x.sh` in a terminal on box-a"), "next line: `bash /home/user/x.sh` is bash for box-a")
upd(130, next="Oliver: In PowerShell run `ssh -t box-a 'bash /home/user/x.sh'`")
check("12 scope: `Oliver: In PowerShell run `ssh -t box-a '…'`` passes", "In PowerShell run" in mt(130)["next"], mt(130)["next"])
upd(130, next="Oliver: In PowerShell:\n  `ssh -t box-a 'tmux ls'`")
check("12 scope: a line that opens with a place phrase asks him to run what is under it, and passes with the ssh form", "tmux ls" in mt(130)["next"], mt(130)["next"])
refused_nw("12 scope: …and is refused with a bare command under it", 130, lambda: upd(130, next="Oliver: In PowerShell:\n  `sala op reauth box-a --from me --words go`"), "next line: `sala op reauth")
refused_nw("12 scope: paste beside a terminal is a run cue", 130, lambda: upd(130, next="Oliver: paste into the terminal `sala op ready x --from me`"), "next line:")
refused_nw("12 scope: a command after the cue is judged though one before it was only mentioned", 130,
           lambda: upd(130, next="Oliver: decide whether `git push origin main` is safe, then run `bash /home/user/x.sh`"), "next line: `bash /home/user/x.sh` is bash for box-a")
upd(130, next="Oliver: PowerShellで `ssh -t box-a 'ls'` 実行")
check("12 scope: a Japanese line with a backticked command passes", "実行" in mt(130)["next"], mt(130)["next"])
# the refusal says what to write for a next line
refused_nw("12 text: the no-place refusal tells a next line to write `Oliver: In PowerShell: …`", 130, lambda: upd(130, next="Oliver: run `git -C ~/repo pull` in a terminal on box-a"), "write `Oliver: In PowerShell: …`")
# ---- a continuation that starts another session's line ends his line; an unclosed fence is no fence
rost = {"team-back", "home-front", "home-stew"}
ol2 = mg.owner_next_lines("Oliver: run it\n  team-back: then `bash /home/user/x.sh` runs\n    deeper `sala op x y`\nOliver: later", rost)
check("12 continuation: an indented line that starts another session's `name:` ends his line, and what is indented under it", [t_ for _, t_ in ol2] == ["run it", "later"], ol2)
ol3 = mg.owner_next_lines("Oliver: In PowerShell:\n  In WSL: `ssh x y`", rost)
check("12 continuation: …but an indented `In WSL:` is no session's name", "In WSL: `ssh x y`" in ol3[0][1], ol3)
item(131, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
refused_nw("12 continuation: his line with a bad command under it is refused", 131, lambda: upd(131, next="Oliver: run this\n  `bash /home/user/x.sh`"), "next line:")
upd(131, next="Oliver: run this\n  team-back: then `bash /home/user/x.sh` runs")
check("12 continuation: …and passes when the bad command sits under another session's line", "team-back: then" in mt(131)["next"], mt(131)["next"])
ol4 = mg.owner_next_lines("Oliver: look at this\n" + B3 + "\nteam-back: after that `bash /home/user/x.sh`\nOliver: later", rost)
check("12 fence: an unclosed fence is no fence; a later top-level line is not swallowed", [x for x, _ in ol4] == ["Oliver: look at this", "Oliver: later"] and "team-back" not in ol4[0][1] + ol4[1][1] and B3 not in ol4[1][1], ol4)
ol5 = mg.owner_next_lines("team-back: x\n" + B3 + "\nOliver: in a fence\n" + B3 + "\nOliver: real", rost)
check("12 fence: a closed fence under another session's line holds no line of his", [x for x, _ in ol5] == ["Oliver: real"], ol5)
# ---- a stored bad line is never rejudged: the switchover judges the whole item, the line stays
GUARDS["switchover"] = True
item(132, needs=["team-back"], next=BARE + "\nteam-back: build it", desc=DESC, state="your-step", step="Read the lines in Next and say done")
upd(132, description="- A thing\n- It lives here\n- Done when done, with more words")
check("12 switchover: a description write on an item holding a stored bad Oliver line passes", "more words" in rd(132)["description"], rd(132)["description"])
upd(132, needs=["team-back", "external"])      # home-front is a user-facing agent (named by mover=), so the added need is external
check("12 switchover: …a needs write", "external" in str(mt(132).get("needs")), mt(132).get("needs"))
upd(132, step="Read the lines in Next and say done, again")      # an agent's state under his line is refused now, so the state write is his own
check("12 switchover: …a state write", mt(132).get("state") == "your-step" and "again" in mt(132).get("step", ""), mt(132))
upd(132, sender="team-back", next="team-back: build it again")
check("12 switchover: …a sender's own valid line beside another session's stored bad Oliver line", "build it again" in mt(132)["next"], mt(132)["next"])
refused_nw("12 switchover: …but a bad Oliver line the write sets is refused", 132, lambda: upd(132, next=BARE), "next line:")
GUARDS["switchover"] = False
# ---- a command outside backticks (the step)
BARE_PS = "In PowerShell, run this, typing gbrain's token when asked: ssh -t box-a 'bash /home/user/notes/scripts/x.sh'"
item(133, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
refused_nw("12 bare: the step text, its command outside backticks, is refused: the step holds no command (it goes in a Oliver: line of next)", 133, lambda: upd(133, step=BARE_PS),
           "step: it carries a command (`ssh -t box-a 'bash /home/user/notes/scripts/x.sh'`)", "line of next")
refused_nw("12 bare: …the same with the command in backticks is refused too", 133, lambda: upd(133, step="In PowerShell, run this, typing gbrain's token when asked: `ssh -t box-a 'bash /home/user/notes/scripts/x.sh'`"), "step: it carries a command")
upd(133, next="team-back: build it\nOliver: In PowerShell, run this, typing gbrain's token when asked: `ssh -t box-a 'bash /home/user/notes/scripts/x.sh'`")
check("12 bare: …the command in a backticked Oliver: next line passes", mt(133)["next"].count("`") == 2, mt(133))
refused_nw("12 bare: …and the next line still faces the Windows rule (bare bash, no ssh)", 133, lambda: upd(133, next="Oliver: In PowerShell, run `bash /home/user/x.sh`"), "next line: `bash /home/user/x.sh` is bash for box-a")
upd(133, step="Run the cleanup when you're back, then say done")
check("12 bare: a prose run line with no command passes", mt(133)["step"].startswith("Run the cleanup"), mt(133))
check("12 bare: …prose after a cue stays prose, a command with a flag after a cue is found", SC.bare_command("In PowerShell run the update when ready") == "" and SC.bare_command("run ssh -t box-a 'ls'") != "", None)
check("12 bare: …a fenced block and a Japanese line with a backticked command", SC.bare_command("In PowerShell:\n" + B3 + "\nssh -t box-a 'ls'\n" + B3) == "" and SC.bare_command("PowerShellで `ssh -t box-a 'ls'` 実行") == "", None)
check("12 bare: a command after a colon that follows a place phrase, a cmdlet and a path are found", SC.bare_command("In PowerShell: Get-Date -Format o") != "" and SC.bare_command("type ~/x.sh --now") != "", None)
refused_nw("12 bare: a Oliver next line with a bare command after a run cue is refused with the same fix", 133, lambda: upd(133, next="Oliver: In PowerShell: ssh -t box-a 'ls'"),
           "next line: the command `ssh -t box-a 'ls'` is not in backticks")
upd(133, next="Oliver: decide whether ssh -t box-a 'ls' still works")
check("12 bare: …but a line that only mentions one passes", "decide whether" in mt(133)["next"], mt(133)["next"])

# ---- second review: place phrases with markers and bold, a command on the next line, imperative cues only, quotes and colons, the quoted command, `! `
BT = "`"
RO = {"team-back", "home-front", "home-stew", "ops-x"}
BARE_FIX = "is not in backticks; put the command in backticks (or a fenced block) so the board shows a copy box"
F1 = ["1. In PowerShell: ssh -t box-a 'sala status'", "- In PowerShell: ssh -t box-a 'sala status'", "**In PowerShell:** ssh -t box-a 'sala status'",
      "In PowerShell:\nssh -t box-a 'sala status'", "when back, run:\n  ssh -t box-a 'x'", "In PowerShell:\n  ssh -t box-a 'x'"]
for k_, t_ in enumerate(F1):
    check(f"12 F1: no backticks is found after a list marker, bold, or on the next line ({k_})", SC.bare_command(t_, RO) != "" and BARE_FIX in SC.command_problem(t_, "step", RO), SC.bare_command(t_, RO))
item(140, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
refused_nw("12 F1: a Oliver line 'when back, run:' with the command on the next line is refused for no backticks", 140, lambda: upd(140, next="Oliver: when back, run:\n  ssh -t box-a 'x'"), "next line: the command `ssh -t box-a 'x'`", BARE_FIX)
refused_nw("12 F1: …and 'In PowerShell:' with it on the next line", 140, lambda: upd(140, next="Oliver: In PowerShell:\n  ssh -t box-a 'x'"), "next line: the command `ssh -t box-a 'x'`")
refused_nw("12 F1: …and a bold place phrase", 140, lambda: upd(140, next="Oliver: **In PowerShell:** ssh -t box-a 'x'"), "next line: the command `ssh -t box-a 'x'`")
# F2: someone else runs it
F2 = ["say go and I will run `sala op recycle x`", "say go; then ops-x runs `bash /home/user/x.sh`", "the nightly run will do `systemctl --user start x`", "the session runs `bash /home/user/x.sh`",
      "approve the run of `bash /home/user/x.sh`", "pick the type, then approve `gh pr merge 5`", "tell the session to run `bash /home/user/x.sh`", "Ask the reviewer to run `bash /home/user/x.sh`",
      "承認したらセッションが `bash /home/user/x.sh` 実行", "入力した `bash /home/user/x.sh` の結果を確認", "ops-x run `bash /home/user/x.sh`", "we will run `bash /home/user/x.sh`", "next run `bash /home/user/x.sh`"]
for k_, t_ in enumerate(F2):
    sc_ = mg.ask_to_run(t_, RO)
    check(f"12 F2: where someone else runs it, the line is not judged ({k_})", not (sc_ and SC.command_problem(sc_, "next line", RO)), (t_, sc_))
upd(140, next="Oliver: say go and I will run `sala op recycle x`")
check("12 F2: …and an update writing one goes through", "I will run" in mt(140)["next"], mt(140)["next"])
upd(140, next="Oliver: 承認したらセッションが `bash /home/user/x.sh` 実行")
check("12 F2: …a Japanese one too", "セッションが" in mt(140)["next"], mt(140)["next"])
for k_, t_ in enumerate(["run `bash /home/user/x.sh`", "then run `bash /home/user/x.sh` now", "type `bash /home/user/x.sh`", "execute `bash /home/user/x.sh`", "これを実行して `bash /home/user/x.sh`", "`bash /home/user/x.sh` 実行してね",
                         "`bash /home/user/x.sh` 実行", "paste into PowerShell `bash /home/user/x.sh`"]):
    check(f"12 F2: an imperative cue still makes the line his ({k_})", bool(mg.ask_to_run(t_, RO)) and SC.command_problem(mg.ask_to_run(t_, RO), "next line", RO) != "", t_)
# F3: a place phrase on a continuation line
refused_nw("12 F3: a place phrase on a continuation line is judged", 140, lambda: upd(140, next="Oliver: do this\n  In PowerShell: `bash /home/user/y.sh`"), "next line: `bash /home/user/y.sh` is bash for box-a")
check("12 F3: …ask_to_run starts the judgement at that line, the command before it is only mentioned", mg.ask_to_run("see `bash /a/b.sh` first\nIn PowerShell: `ls -la`", RO).startswith("see bash /a/b.sh first\n"), None)
# F4: colons and quotes
for k_, t_ in enumerate(["Run the update. Note: git is 'old' here", "Run the installer. Result: python 3.12 'ok'", "Run this: git can't push"]):
    check(f"12 F4: a colon after a sentence stop, a quote inside a word, a word that is no flag are no command ({k_})", SC.bare_command(t_, RO) == "", (t_, SC.bare_command(t_, RO)))
check("12 F4: …a colon that ends the cue clause within eight words counts; farther or past a stop it does not",
      SC.bare_command("Run this: ssh -t box-a 'x'") != "" and SC.bare_command("Run one two three four five six seven eight nine ten: ssh -t box-a 'x'") == "" and SC.bare_command("Run it. Then: ssh -t box-a 'x'") == "", None)
# F5: only the command is quoted
check("12 F5: the refusal quotes the command, not the sentence", SC.bare_command("Run cd ~/foo in PowerShell") == "cd ~/foo" and SC.bare_command("Run ssh -t box-a 'ls -la' and say done") == "ssh -t box-a 'ls -la'"
      and SC.bare_command("In PowerShell: sala op reauth box-a --from me --words go, then wait") == "sala op reauth box-a --from me --words go", SC.bare_command("In PowerShell: sala op reauth box-a --from me --words go, then wait"))
refused_nw("12 F5: …in the step's refusal (it names the command alone)", 133, lambda: upd(133, step="Run cd ~/foo in PowerShell"), "step: it carries a command (`cd ~/foo`)")
# F6: a pane line after a cue (a bare command for the unbackticked check; as a next line the pane refusal comes first)
check("12 F6: `type: ! ~/…sh --only x` without backticks is refused for no backticks", SC.bare_command("type: ! ~/wiki/x.sh --only x") == "~/wiki/x.sh --only x", SC.bare_command("type: ! ~/wiki/x.sh --only x"))
refused_nw("12 F6: …as a Oliver next line", 140, lambda: upd(140, next="Oliver: type: ! ~/wiki/x.sh --only x"), "next line: a `! ` line (`! ~/wiki/x.sh --only x`)")
# F7: a bare command with no flag, path or quoted argument passes
check("12 F7: a bare command with no flag, path or quoted argument is left alone", SC.bare_command("In PowerShell: ssh box-a") == "" and SC.bare_command("run uv sync") == "", None)

# ================================================================ 13. the step is a one-line summary: a command in it is refused
Hs = f"{model.owner_display()}"
w = SC.step_carries_command("Run `sala op ready x`")
check("13 unit: a step with a command is refused, naming the field, the command and the `Oliver:` line of next", w.startswith("step: it carries a command (`sala op ready x`)") and f'"{Hs}:" line of next' in w and "\n" not in w, w)
check("13 unit: …a fenced block and a `! ` line are commands too; a bold label, a lone word, a path alone and plain words are not",
      all(SC.step_carries_command(s) for s in ("Run:\n```\nGet-Date\n```", "! sala reauth x", "In ops-x's pane: `! sala reauth x`", "In PowerShell run `ssh -t box-a 'ls'`", "Run `Get-Date -Format o`"))
      and not any(SC.step_carries_command(s) for s in ("Click **Make a copy** and say done", "Open `git` and read the README", "Run the Oliver: lines of Next in PowerShell", "Call the office and say done", "Open `~/stackshot/render.py`")), None)
item(90, needs=["team-back"], next="team-back: build it")
refused_nw("13 write: a step that carries a command is refused, in one line, naming the item and the field", 90, lambda: upd(90, step="Run `sala op ready x`"), "Refused: a90: step: it carries a command", "line of next")
refused_nw("13 write: …a fenced block in the step", 90, lambda: upd(90, step="In PowerShell:\n```\nGet-Date\n```"), "step: it carries a command")
refused_nw("13 write: …the way it was written before (a numbered list with commands, a place named)", 90, lambda: upd(90, step=NUMBERED), "step: it carries a command")
refused_nw("13 write: …a step that points at the description is still refused, and the refusal says the step may name his Next line", 90, lambda: upd(90, step="See the description"), "points elsewhere", "Next line")
upd(90, step="In PowerShell: run the commands in your Next lines and say done", next="Oliver: In PowerShell run `ssh -t box-a 'ls'` and read the list\nteam-back: check it")
check("13 write: the summary step that names his Next line is accepted with the command in a `Oliver:` line of next, both in the one write",
      mt(90)["step"] == "In PowerShell: run the commands in your Next lines and say done" and "ssh -t box-a 'ls'" in mt(90)["next"] and mt(90)["state"] == "your-step", mt(90))
p90 = page(90, answer=BOX)
b90 = re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">(.*?)</div></div><form class="ianswer"', p90, re.S)
b90 = b90.group(1) if b90 else ""
check("13 page: and the Your step block shows his line in full with a Copy button, and not the summary beside it",
      b90.startswith('<div class="istepnext"><ol class="stepol">') and b90.count("<li>") == 1 and b90.count('class="cmd"') == 1 and "ssh -t box-a" in b90 and "run the commands in your Next lines" not in b90, b90[:600])
item(91, desc=DESC, **HOW, step="Run `ssh -t box-a 'ls'` and say done")
upd(91, priority="p2")
refused_nw("13 legacy: a step stored with a command and no place keeps the older judgement on a write that leaves the step alone (a command needs a place)", 91,
           lambda: upd(91, description="- A thing\n- It lives here\n- Done when done"), "does not say where it runs")
item(92, desc=DESC, **HOW, step="In PowerShell run `ssh -t box-a 'ls'` and say done")
upd(92, description="- A thing\n- It lives here\n- Done when done")
check("13 legacy: …and one that names its place goes through on a write that leaves the step alone", rd(92)["description"].startswith("- A thing"), None)
refused_nw("13 legacy: rewriting its step still holding the command is refused (it moves to a line of next)", 92, lambda: upd(91, step="In PowerShell run `ssh -t box-a 'ls'` and say done"), "step: it carries a command")
check("13 legacy: command_problem is still the check for a stored step with no place named", "does not say where it runs" in SC.command_problem("Run `ssh -t box-a 'ls'`") and SC.command_problem("In PowerShell run `ssh -t box-a 'ls'`") == "", None)
check("13 text: nowhere in the step's own words, the guards or the page does a pointer 'numbered below' appear",
      "numbered below" not in pathlib.Path(STACK, "stackshot/model/step_commands.py").read_text(encoding="utf-8") + pathlib.Path(STACK, "stackshot/model/states.py").read_text(encoding="utf-8") + pathlib.Path(STACK, "stackshot", "web", "ui", "render.py").read_text(encoding="utf-8") + pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8"), None)

# ================================================================ 14. no pane form on the board: a `! ` line in a step or in a Oliver: line of next is refused; the fix is the ssh form
PANE_FIX = "\"In PowerShell:\" `ssh -t box-a '<command>'`"
check("14 unit: pane_commands finds a line that starts `! ` (after a marker or bold) and a backticked `! cmd`; `done!`, a quoted `! ` and a `!` with no command are none",
      SC.pane_commands("! sala reauth x") == ["! sala reauth x"] and SC.pane_commands("- ! sala reauth x") == ["! sala reauth x"] and SC.pane_commands("In ops-x's pane: `! sala reauth x`") == ["! sala reauth x"]
      and SC.pane_commands("say done!") == [] and SC.pane_commands("The `! ` prefix types into a pane") == [] and SC.pane_commands("!important") == [] and SC.pane_commands("Wow! then `ssh -t box-a 'ls'`") == [], SC.pane_commands("Wow! then `ssh -t box-a 'ls'`"))
w14 = SC.pane_problem("! sala reauth x", "next line")
check("14 unit: the refusal names the field, the pane form and the fix: In PowerShell: ssh -t box-a '<command>'",
      w14.startswith("next line: a `! ` line (`! sala reauth x`) is a command typed into a session's pane, and the board takes none; a command for Oliver is written " + PANE_FIX) and "\n" not in w14, w14)
check("14 unit: command_problem gives it first, for a pane line that names its pane or says PowerShell, as for a step", all(SC.command_problem(t_).startswith("step: a `! ` line") for t_ in ("In ops-x's pane: `! sala reauth x`", "In PowerShell: `! sala reauth x`", "! sala reauth x")), SC.command_problem("In ops-x's pane: `! sala reauth x`"))
check("14 unit: …and the bash-for-box-a hint teaches the ssh form only, no pane form", "pane" not in SC.command_problem("In PowerShell run `sala op ready x`") and PANE_FIX in SC.command_problem("In PowerShell run `sala op ready x`"), SC.command_problem("In PowerShell run `sala op ready x`"))
item(93, needs=["team-back"], next="team-back: build it")
# a step
for k_, st_ in enumerate(("Type `! sala reauth x` and say done", "! sala reauth box-a", "In ops-x's pane: `! sala reauth x`")):
    refused_nw(f"14 step: a step with a pane-form command is refused ({k_})", 93, lambda st_=st_: upd(93, step=st_), "Refused: a93: step: a `! ` line", PANE_FIX)
upd(93, step="Say done! once the page is open")
check("14 step: a `!` that no command follows (\"done!\") is allowed in a step", mt(93)["step"] == "Say done! once the page is open", mt(93))
# a Oliver: next line (his line first in next needs his state, so is a your-step item)
item(151, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
for k_, ln_ in enumerate(("Oliver: ! sala reauth box-a --from me --words go", "Oliver: `! sala reauth x`", "AE: In ops-x's pane: `! sala reauth x`", "- Oliver: type `! ls -la`", "オリバー: `! sala reauth x` 実行",
                          "Oliver: In PowerShell:\n  ! sala reauth x")):
    refused_nw(f"14 next: a Oliver: line with a pane-form command is refused, a run cue or not ({k_})", 151, lambda ln_=ln_: upd(151, next=ln_), "Refused: next line: a `! ` line", PANE_FIX)
try:
    upd(151, next="Oliver: ! sala reauth x"); got14 = ""
except Exception as e:
    got14 = str(e)
check("14 next: …the whole refusal is `Refused: ` + the pane text for `next line`", got14 == "Refused: " + SC.pane_problem("! sala reauth x", "next line") and got14.startswith("Refused: next line: a `! ` line (`! sala reauth x`)"), got14)
refused("14 create: a Oliver: next line with a pane-form command is refused", lambda: _wt_create._create(subject="[home] case-b bang", description=DESC, project="projects/alpha", owner="home-front", next="Oliver: ! sala reauth x", needs=["team-back"]), "Refused: next line: a `! ` line", PANE_FIX)
upd(151, next="team-back: ! sala reauth x\nteam-back: run `! ls`")
check("14 next: another agent's line with the pane form is allowed", "team-back: ! sala reauth x" in mt(151)["next"], mt(151)["next"])
for k_, ln_ in enumerate(("Oliver: open the page and say done!", "Oliver: wow! the page is up", "Oliver: the prefix `! ` types into a pane", "Oliver: In PowerShell run `ssh -t box-a 'sala op ready x'`", "Oliver: !important is a CSS word")):
    upd(151, next=ln_)
    check(f"14 next: a Oliver: line with a `!` that no command follows, or the ssh form, is allowed ({k_})", nx(151) == ln_, mt(151)["next"])
out14 = _wt_create._create(subject="[home] case-b ok", description=DESC, project="projects/alpha", owner="home-front", next="team-back: build it\nOliver: In PowerShell run `ssh -t box-a 'ls'`", needs=["team-back"])      # his line is not first, so the item stays an agent's
check("14 create: the ssh form passes", "Refused" not in str(out14), out14)
rep14 = mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": "Oliver: ! sala reauth x"}}, mg.Ctx(), touched={"next"})[0]
check("14 guard: the model guard names it next_windows", [p.key for p in rep14] == ["next_windows"] and "`! ` line" in mg.LABELS["next_windows"], rep14)
item(152, needs=["team-back"], next="Oliver: ! sala reauth x\nteam-back: build it")
upd(152, priority="p1")
check("14 next: a stored pane line never holds up a write that leaves next alone", mt(152).get("priority") == "p1", mt(152))
GUARDS["guards"] = False
upd(151, next="Oliver: ! sala reauth x")
check("14 next: [model] guards = false skips it", nx(151) == "Oliver: ! sala reauth x", mt(151)["next"])
GUARDS["guards"] = True
# the inline form: a `!` and a command word after a colon or a run cue
INL14 = ("In PowerShell: ! sala reauth x", "type ! sala reauth x", "In the pane type: ! sala x", "Type ! sala reauth x and say done", "実行: ! sala reauth x")
check("14 unit: pane_commands finds an inline `! cmd` after a colon or a run cue", all(SC.pane_commands(t_) and SC.pane_commands(t_)[0].startswith("! sala") for t_ in INL14), [SC.pane_commands(t_) for t_ in INL14])
check("14 unit: …and none in prose: done!, wow!, !important, Japanese 感嘆符! です, `Wow! then ...`", all(SC.pane_commands(t_) == [] for t_ in ("done!", "wow! the page is up", "!important", "感嘆符! です", "Please run! now thanks", "Wow! then `ssh -t box-a 'ls'`")))
for k_, t_ in enumerate(("In PowerShell: ! sala reauth x", "Type ! sala reauth x and say done")):
    refused_nw(f"14 step: an inline `! cmd` in a step is refused ({k_})", 93, lambda t_=t_: upd(93, step=t_), "Refused: a93: step: a `! ` line", PANE_FIX)
for k_, ln_ in enumerate(("Oliver: In PowerShell: ! sala reauth x", "Oliver: type ! sala reauth x", "Oliver: In the pane type: ! sala x")):
    refused_nw(f"14 next: an inline `! cmd` in a Oliver: line is refused ({k_})", 151, lambda ln_=ln_: upd(151, next=ln_), "Refused: next line: a `! ` line", PANE_FIX)
for k_, ln_ in enumerate(("Oliver: 感嘆符! です", "Oliver: wow! the page is up", "Oliver: say done! when it is open")):
    upd(151, next=ln_)
    check(f"14 next: prose with a `!` stuck to a word is allowed ({k_})", nx(151) == ln_, mt(151)["next"])
upd(93, step="感嘆符! です")
check("14 step: Japanese prose with a `!` stuck to a word is allowed in a step", mt(93)["step"] == "感嘆符! です", mt(93))
item(16, desc=DESC, **HOW, step="In ops-x's pane: `! sala reauth x`")
refused_nw("14 legacy: a step stored in the pane form blocks a write that leaves the step alone, until it is rewritten", 16,
           lambda: upd(16, description="- A thing\n- It lives here\n- Done when done"), "Refused: a16: step: a `! ` line", PANE_FIX)
upd(16, step="In PowerShell: run the commands in your Next lines and say done", next="Oliver: In PowerShell run `ssh -t box-a 'ls'`\nteam-back: check it")
upd(16, description="- A thing\n- It lives here\n- Done when done")
check("14 legacy: …and rewriting the step lets the write through", rd(16)["description"].startswith("- A thing"), None)
snap14 = live_tools()
check("14 text: create's and update's description say a `! ` line in a Oliver: line of next is refused and give the ssh form; update's step text no longer teaches the pane form",
      all("A `! ` line (a command typed into a pane) in a line that starts `the owner:`" in snap14[k]["description"] and "write it `In PowerShell: ssh -t box-a '<command>'`" in snap14[k]["description"] for k in ("create", "update"))
      and "names the pane" not in snap14["update"]["description"] and "in ops-x's pane" not in snap14["update"]["description"] and "pane form" in snap14["update"]["description"], None)

# ================================================================ 10. the tool text
import inspect
snap = live_tools()
d = snap["update"]["description"]
check("10 text: update's description says the step is a one-line summary with no command, where the commands go (a `Oliver:` line of next) and the refusals",
      "step (update only; create sets no step): a ONE-LINE summary of what the person whose step it is does" in d and "never holds a command" in d and "next line that starts `the owner:`" in d and "Copy button" in d and "on a Windows machine, the default" in d and "ssh -t box-a '<command>'" in d
      and "in ops-x's pane" not in d and "never a `! ` line, the pane form, which is refused in a step and in a next line that starts `the owner:`" in d and "the description holds a shell command" in d and "A step that carries a command" in d
      and "points elsewhere" in d and "pointer_patterns" in d and "a step that names his Next line passes" in d and "[model] guards = false" in d, d[-2400:])
check("10 text: …a backticked span with a space reads as a command, so a label goes in bold or quotes",
      "a backticked span with a space in it that reads as a shell command" in d and "A button or menu label is not a command: put it in bold or quotes, not backticks" in d, None)
check("10 text: …a description write is judged only on the commands it adds, and a fence there counts only when tagged and is judged line by line",
      "judged only on the commands it adds or changes" in d and "tagged sh, bash, shell, powershell, pwsh or console, and each command line of a tagged fence is judged" in d and "untagged fence holds pasted output" in d, None)
check("10 text: create's description carries no step text (it sets no step)", "step (update only" not in snap["create"]["description"] and "Say where each command runs" not in snap["create"]["description"], None)
check("10 text: …the description's own line sends a command to a `Oliver:` next line, and the step stays a summary", "never in the description or in the step" in snap["create"]["description"] and "see step below" in snap["create"]["description"] and "see step below" in snap["update"]["description"], None)
check("12 text: create's and update's description say the Oliver next line gets the command check, naming `next line`",
      "(or `AE:`, `オリバー:`) and asks him to run something" in snap["create"]["description"] and "gets the command check (where it runs, the ssh form) on create and update" in snap["create"]["description"]
      and "only for the lines the call sets" in snap["create"]["description"] and "A line that only mentions a command" in snap["create"]["description"]
      and "A next line that starts with his name" in snap["update"]["description"] and "gets the command check (where it runs, the ssh form), on create and update" in snap["update"]["description"]
      and "refused as `next line: …`; a line that only mentions a command" in snap["update"]["description"]
      and "outside backticks or a fence after a run cue" in snap["update"]["description"], None)
check("12 text: F2 and F7 are in the tool text: someone else running it is no cue, a bare command has a flag, path or quoted argument",
      all("is not a cue" in snap[k]["description"] and "say go and I will run" in snap[k]["description"] for k in ("create", "update"))
      and "A bare command with a flag, path or quoted argument" in snap["update"]["description"], None)
check("10 text: …the description's own line sends a command to a `Oliver:` line of next, not to the step", "goes in a next line that starts `the owner:`, whole in backticks, never in the description or in the step" in snap["create"]["description"] and "see step below" in snap["update"]["description"], None)
check("10 text: …and the your-step line of the states", "step=<one line, no command, of the single thing only" in snap["update"]["description"], None)

# ================================================================ 15. [steps] owner_shell = "sala-shell": a command is bash as typed in sala's Shell, or ssh for another machine
# The guards read the setting where they run, so the section flips it in the running config and puts it back; the tool text is built at import, so it is read from fresh processes on a config of each kind.
STEPS = server._cfg.CFG["steps"]; WAS15 = dict(STEPS)
STEPS["owner_shell"] = "sala-shell"; STEPS["shell_name"] = "my-shell"
try:
    check("15 mode: sala-shell is its own mode: not the PowerShell rule", SC.shell_mode() == "sala-shell" and SC.sala_shell() and not SC.shell_rule() and SC.shell_name() == "my-shell", SC.shell_mode())
    for k_, t_ in enumerate(("Run `sala op ready x --from me` and say done", "Run `systemctl --user status x` and say done", "Run `./deploy.sh now` and say done", "Run `ls -la ~/x` and say done", "Run `git pull --rebase` and say done",
                             "Run `ssh other-host 'systemctl status x'` and say done", "Run `ssh -t other-host 'sala ready'` and say done", "In sala's Shell: run `python3 tools/x.py`", "1. Run `grep -r foo /etc/x`\n2. Say done")):
        check(f"15 pass: a bash command, or ssh to another machine, is fine and no line saying where it runs is asked for ({k_})", SC.command_problem(t_) == "", SC.command_problem(t_))
    check("15 pass: a cmdlet or a Windows program inside ssh is the other machine's", SC.command_problem("Run `ssh other-host 'Get-Process -Name claude'` and say done") == "" and SC.command_problem("Run `ssh other-host 'winget upgrade --id X.Y'`") == "")
    for k_, t_ in enumerate(("Run `Get-Process -Name claude` and say done", "Run `winget upgrade --id Example.Tool`", "Run `C:\\tools\\x.exe --go`", "In PowerShell: `Get-Date -Format o`", "Run `ipconfig /all` and say done")):
        w15 = SC.command_problem(t_)
        check(f"15 refused: a PowerShell or Windows-only command outside ssh, naming sala's Shell and the ssh form ({k_})",
              w15.startswith("step: ") and "PowerShell or Windows" in w15 and "sala's Shell (the session `my-shell`)" in w15 and "`ssh <host> '<command>'`" in w15 and "\n" not in w15, w15)
    w15 = SC.command_problem("In sala's Shell: sala op ready x --from me")
    check("15 bare: a command written outside backticks after the place phrase still needs its backticks", "is not in backticks" in w15 and SC.run_cue("In sala's Shell: ls") is not None and SC.run_cue("In sala's Shell: ls") == 0, w15)
    w15 = SC.pane_problem("! sala reauth x", "next line")
    check("15 pane: a `! ` line is refused and the fix is the Shell form", w15.startswith("next line: a `! ` line (`! sala reauth x`)") and "sala's Shell (the session `my-shell`)" in w15 and "ssh <host> '<command>'" in w15 and "PowerShell" not in w15, w15)
    for k_, body_ in enumerate(("ssh other-host '\nGet-Process\n'", "ssh other-host 'cd /x\nGet-Content f.txt'", "ssh other-host 'cat <<EOF\nGet-Process -x\nEOF'", "ssh other-host <<EOF\nGet-Process -x\nEOF\nls -la",
                               "ssh other-host \"\nGet-Process\n\"")):
        t_ = f"In sala's Shell:\n```\n{body_}\n```"
        check(f"15 fence: lines inside a quote or heredoc an ssh line opened are the other machine's, not judged as bash ({k_})", SC.command_problem(t_) == "", SC.command_problem(t_))
    w15 = SC.command_problem("In sala's Shell:\n```\nssh other-host 'ls'\nGet-Process -Name claude\n```")
    check("15 fence: …but a PowerShell line after the quote is closed is refused", "PowerShell or Windows" in w15 and "Get-Process" in w15, w15)
    check("15 fence: a Windows line before any ssh line is refused", "PowerShell or Windows" in SC.command_problem("In sala's Shell:\n```\nGet-Process -Name claude\nssh other-host 'ls'\n```"))
    check("15 fence: the default reading of a fence is unchanged (every line of it counts)", SC.fence_commands("ssh h '\nGet-Process\n'") == ["ssh h '", "Get-Process", "'"] and SC.fence_commands("ssh h '\nGet-Process\n'", bodies=False) == ["ssh h '"], SC.fence_commands("ssh h '\nGet-Process\n'", bodies=False))
    for k_, c_ in enumerate((".\\run.ps1 -x", "C:\\tools\\x.exe --go", "& 'C:\\x y\\z.exe' -a")):
        check(f"15 windows: a .\\ path, a drive path and the call operator are Windows ({k_})", SC.windows_only(c_), c_)
    # end to end: create and update
    item(96, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
    for k_, ln_ in enumerate(("Oliver: run `sala op ready x --from me` and say done", "Oliver: In sala's Shell run `ssh other-host 'ls -la'`", "Oliver: type `systemctl --user status x`")):
        upd(96, next=ln_)
        check(f"15 next: a Oliver: line with a bash command or the ssh form passes ({k_})", nx(96) == ln_, mt(96)["next"])
    refused_nw("15 next: a Oliver: line with a cmdlet is refused, as `next line: …`", 96, lambda: upd(96, next="Oliver: run `Get-Date -Format o` and say done"), "Refused: next line: ", "PowerShell or Windows", "sala's Shell")
    refused_nw("15 next: a Oliver: line in the pane form is refused with the Shell form", 96, lambda: upd(96, next="Oliver: ! sala reauth x"), "Refused: next line: a `! ` line", "sala's Shell", "ssh <host> '<command>'")
    upd(96, step="Say done in the board when the command in Next has run")
    check("15 step: a one-line summary passes", mt(96)["step"].startswith("Say done"), mt(96))
    refused_nw("15 step: a command in the step is refused: it goes in a Oliver: line of next", 96, lambda: upd(96, step="Run `sala op ready x` and say done"), "Refused: a96: step: it carries a command")
    rep15 = mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": "Oliver: run `Get-Date -Format o`"}}, mg.Ctx(), touched={"next"})[0]
    check("15 guard: the model guard names it next_windows", [p.key for p in rep15] == ["next_windows"], rep15)
    item(97, needs=["team-back"], next="team-back: build it")
    upd(97, step="Say done after the command in Next has run", next="Oliver: run `sala op ready x --from me`\nteam-back: check it")
    check("15 stored: a your-step item whose step is a summary and whose next line holds a bash command writes through", "sala op ready x" in mt(97)["next"], mt(97))
finally:
    STEPS.clear(); STEPS.update(WAS15)
# powershell mode is as it was
check("15 powershell: the mode is back and its rules are unchanged", SC.shell_mode() == "powershell" and SC.shell_rule() and not SC.sala_shell(), SC.shell_mode())
w15 = SC.command_problem("Run `sala op ready x --from me` and say done")
check("15 powershell: bash for the host is still refused with the ssh form, and a command with no place still needs one",
      w15.startswith("step: ") and "bash for box-a" in w15 and "ssh -t box-a '<command>'" in w15 and "does not say where it runs" in SC.command_problem("Run `git pull --rebase` and say done")
      and SC.command_problem("In PowerShell run `Get-Process -Name claude`") == "" and SC.command_problem("In PowerShell run `ssh -t box-a 'sala ready'`") == "", w15)
for mode_ in ("powershell", ""):
    STEPS["owner_shell"] = mode_
    try:
        check(f"15 unchanged ({mode_ or 'default'}): \"In sala's Shell:\" is no place phrase there, as before: no run cue, no bare command, nothing judged",
              SC.run_cue("In sala's Shell: ls -la") is None and SC.run_cue("Using sala shell is fine") is None and SC.bare_command("In sala's Shell: sala op ready x --from me") == ""
              and SC.command_problem("In sala's Shell: sala op ready x --from me") == "" and SC.run_cue("In a terminal: ls -la") == 0 and SC.run_cue("In the shell: ls") == 0, (SC.run_cue("In sala's Shell: ls -la"), SC.command_problem("In sala's Shell: sala op ready x --from me")))
        item(98, needs=["team-back"], next="team-back: build it", state="your-step", step="Read the lines in Next and say done")
        upd(98, next="Oliver: Using sala shell is fine, say done")
        check(f"15 unchanged ({mode_ or 'default'}): …so a Oliver: line that says it passes", nx(98) == "Oliver: Using sala shell is fine, say done", mt(98)["next"])
    finally:
        STEPS["owner_shell"] = WAS15["owner_shell"]
# the text: a fresh process on a config of each kind
TEXT15 = ("import asyncio, json, logging, sys\nlogging.disable(logging.WARNING)\nimport server, client\n"
          "print(json.dumps({'tools': {t.name: (t.description or '') for t in asyncio.run(server.mcp.list_tools())}, 'usage': client._usage()}))\n")
def text15(owner_shell, shell_name=None):
    cfg = _instance._set(toml, "steps", "owner_shell", f'"{owner_shell}"')
    cfg = _instance._set(cfg, "steps", "shell_name", f'"{shell_name}"') if shell_name is not None else cfg
    p_ = T / f"text15-{owner_shell or 'none'}-{shell_name or 'x'}.toml"; p_.write_text(cfg, encoding="utf-8")
    r_ = subprocess.run([sys.executable, "-c", TEXT15], cwd=STACK, env={**os.environ, "STACKSHOT_CONFIG": str(p_), "PYTHONPATH": STACK}, capture_output=True, text=True, timeout=180)
    assert r_.returncode == 0, r_.stderr[-600:]
    return json.loads(r_.stdout.strip().splitlines()[-1])
named15, bare15, ps15, off15 = text15("sala-shell", "my-shell"), text15("sala-shell", ""), text15("powershell"), text15("")
for k_ in ("create", "update"):
    dn_, db_ = named15["tools"][k_], bare15["tools"][k_]
    check(f"15 text: {k_} says the command is as typed in sala's Shell, with its session's name from the config, the ssh form and no place line",
          "as typed in sala's Shell (the session `my-shell`)" in dn_ and "`ssh <host> '<command>'`" in dn_ and "In PowerShell" not in dn_ and "Windows machine" not in dn_ and "where it runs, the ssh form" not in dn_ and ("never a `! ` line, the pane form" in dn_ or k_ == "create"), dn_[-1800:])
    check(f"15 text: {k_} names no session when the config names none", "sala's Shell" in db_ and "(the session `" not in db_ and "my-shell" not in db_, db_[-1800:])
    check(f"15 text: {k_} in the PowerShell and the default instance reads as before", "In PowerShell" in ps15["tools"][k_] and "sala's Shell" not in ps15["tools"][k_] and "sala's Shell" not in off15["tools"][k_], None)
check("15 text: update carries the paste hint: Shift+Insert, not Ctrl+V", "Shift+Insert, not Ctrl+V" in named15["tools"]["update"] and "Shift+Insert" not in ps15["tools"]["update"] and "Shift+Insert" not in off15["tools"]["update"], None)
check("15 text: the client's usage no longer teaches a step's command place in any mode (post state is retired: its line says so and has no @WHERE@), and leaves no placeholder behind",
      all("@WHERE@" not in u_ and "{OWNER}" not in u_ and "post state ...      retired:" in u_ and "--step" not in u_.split("post state ...")[1].split("\n  client.py ")[0] for u_ in (named15["usage"], bare15["usage"], ps15["usage"], off15["usage"]))
      and "sala's Shell" not in named15["usage"] and "Shift+Insert" not in named15["usage"], named15["usage"][named15["usage"].find("post state"):][:400])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": step scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
