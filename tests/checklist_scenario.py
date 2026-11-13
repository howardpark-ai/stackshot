"""Scenario test for next as a checklist (open items start the list now, a dropped step stays, struck through) — fixture data, the tools called in-process, no live store, no network.

Covers: an item with next lines and no stored steps has the checklist its lines give, all open (the list starts from now); `update(done=[…])` checks a step by position,
by its exact text and by a JSON string, `dropped=[…]` drops one, and a marked step keeps its place, with who marked it and when; `next` stays the text of the open
lines exactly (what every reader of next reads: get, the home row, the guards, the hand-off record); a next write that no longer lists an open step the call does not
mark is refused, naming done and dropped, and writes nothing; one that only adds or reorders open steps works, the open steps taking the new order in the places open steps
held; a mark with a next, a mark alone (next becomes the open steps left), a mark of a step that is not open, of a position that is not there, of text that matches none or
two, a step in both lists and a step still listed in next are refused; `[metadata.next] require_marks = false` reads an unmarked removal as dropped, nobody and no time;
a line that left next by a write that knows nothing of steps reads as dropped; a close marks the open steps (done when the outcome is done, dropped otherwise) and keeps the checklist as the record (get and the page show it), marks on
a closed item are refused and a reopening drops the steps an old close left open; get lists the done and dropped steps with their positions, who and when; History says `step done: …` and
`step dropped: …` (the page's and the GitHub mirror's comment); Oliver's Done checks his open step (the one that holds the Your step block's text, else the
first that is his), a note leaves it open, and a step that is not a line of next checks nothing; the page draws the checklist as CSS boxes (no form input), open / done (checked,
muted, who · when) / dropped (struck through), with a hidden word for a screen reader, and escapes hostile text in a step and in who marked it.

Since (nextlines) a step is a line as nextlines.split groups it and knows its writer: a mark reaches any open step and the marked line leaves next with its writer pair; an unmarked drop is refused for
the sender's own lines only (next replaced, or next="none"); clear_next=true is a deliberate wipe that marks every line dropped by the sender. Since the Your step block shows his own open Next lines (section 12),
his Done checks all of them, and the step field is a one-line summary (step_scenario, section 12, refuses a command in it).

    tests/run-suite checklist        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="checklisttest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                     (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "github.token").write_text("test-token\n")
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
DESC = "- A thing, finished when it works"
L4 = "home-agent: build the thing\nhome-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper"
STEP = "run the shipping command from your Next line"
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": L4, **meta}}))
for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 20):
    item(i)                                                       # a legacy item: four next lines, no stored steps
item(10, state="your-step", step=STEP, next="home-agent: prepare it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: verify it")        # Oliver's Done
item(11, state="your-step", step=STEP, next="home-agent: prepare it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: verify it")        # …and with a note
item(12, state="your-step", step=STEP, next="home-agent: look at it")                                                          # his step is not a line of next
item(13, state="your-step", step=STEP, next="Oliver: look at the page first\nOliver: In PowerShell run `ssh -t box-a 'ls'` on the box\nhome-agent: verify it")      # the line that holds the step's text
item(14, next="home-agent: first <script>alert(1)</script> & \"q\"\nhome-agent: second", steps=[
    {"text": "home-agent: old <b>bold</b>", "status": "done", "by": "<img src=x onerror=alert(2)>", "at": now - 600},
    {"text": "home-agent: first <script>alert(1)</script> & \"q\"", "status": "open"}, {"text": "home-agent: second", "status": "open"}])
item(15, next="home-agent: kept", steps=[{"text": "home-agent: kept", "status": "open"}, {"text": "home-agent: removed by a write that knows nothing of steps", "status": "open"}])
item(16, next="home-agent: same\nhome-agent: same")                                                                              # two lines of one text
HIS = ("home-agent: prepare the box\nOliver: In PowerShell run `ssh -t box-a 'sala ready'` and read the output\nOliver: then paste the <script>alert(3)</script> result back & say so"
       "\n  - a sub line with `Get-Date -Format o`\n**Oliver:** run this one\n```powershell\nGet-Date\n```\nhome-agent: check what he pasted")
STEPY = "One line in PowerShell on your Windows laptop"
item(21, state="your-step", step=STEPY, next=HIS)                                                          # his own Next lines in the Your step block
item(22, state="your-step", step=STEPY, next="home-agent: prepare the box")                                  # …none of his
item(23, state="your-step", step=STEPY, next="run `Get-Date -Format o` and say so")                        # …an unnamed line is his while the item is his move
for i in (30, 31, 32, 33, 34):
    item(i, next="home-here: keeper line one\nOliver: keeper line two")                                          # lines of the keeper of record (no writer stored: the keeper's)
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
def snap(msg="step"): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
STORE = T / "store"

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.github import ghsync as G; from stackshot.model import steps as S; from stackshot.web import home as H; from stackshot.web import itempage as IP; from stackshot.model import nextlines as NL
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.web.ui import render as ui_render
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def refused(name, f, *want, i=None):
    was = rd(i) if i is not None else None
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want) and (was is None or rd(i) == was), str(e))
def upd(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-here", **kw)
def upa(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-agent", **kw)
def upi(i, **kw): return server._update(f"a{i}", sender="home-agent", **kw)           # the server's own write: N6 (an open item keeps an open step) judges a session's write only
def st(i): return [(x["status"], S.first_line(x["text"])) for x in S.view(mt(i), closed=rd(i)["status"] == "completed")]
OPEN = lambda t: ("open", t)

# ---- 1. the list starts from now: a legacy item's lines are its open steps
check("an item with next lines and no stored steps has the checklist its lines give, all open, in order",
      st(1) == [OPEN("home-agent: build the thing"), OPEN("home-agent: test it"), OPEN("Oliver: In PowerShell run `ssh -t box-a 'ls'`"), OPEN("home-agent: tell the keeper")] and "steps" not in mt(1), st(1))
check("the steps of a text are nextlines' lines (the one rule): a top-level line is one, with the indented lines, a note in parentheses and a fenced block under it",
      S.split("home-a: one\n- home-b: two\n  more\n(a server note)\nhome-c: three\n```\nx\n\ny\n```\n\nfour") == ["home-a: one", "- home-b: two\n  more\n(a server note)", "home-c: three\n```\nx\n\ny\n```", "four"]
      and S.split("a\n- b\nc") == NL.split("a\n- b\nc"))

# ---- 2. done, by position
r = upd(1, done=[1])
m1 = mt(1)
check("done=[1]: the first step is checked, by home-here and now, and keeps its place; the others stay open",
      r.startswith("updated a1") and [x["status"] for x in m1["steps"]] == ["done", "open", "open", "open"] and m1["steps"][0]["by"] == "home-here" and abs(m1["steps"][0]["at"] - time.time()) < 60
      and m1["steps"][0]["text"] == "home-agent: build the thing", m1["steps"])
check("…and next is the open lines exactly, one per line, as every reader reads it", m1["next"] == "home-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper", m1["next"])
check("…the reply says which step was checked", "(step 1 done: home-agent: build the thing)" in r, r)
check("the readers of next read the open lines: the home row's first step, the hand-off names, get's next block",
      H.first_next(m1["next"], ("home-agent",)) == ("home-agent", "test it") and "next:\nhome-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper" in server._fmt({**rd(1), "gid": "a1"}))
g1 = server._fmt({**rd(1), "gid": "a1"})
check("get lists the checklist once a step is done: every step with its position, status, who and when",
      re.search(r"checklist:\n1\. \[done · home-here · [^\]]+\] home-agent: build the thing\n2\. \[open\] home-agent: test it\n3\. \[open\] Oliver: In PowerShell run `ssh -t box-a 'ls'`\n4\. \[open\] home-agent: tell the keeper", g1) is not None, g1[g1.find("next:"):])
check("get shows no checklist while every step is open", "checklist:" not in server._fmt({**rd(2), "gid": "a2"}))
snap()

# ---- 3. done by exact text, by a JSON string and by a digits string; dropped
r = upd(1, done=["home-agent: test it"])
check("done=[<the exact text of an open step's line>]: that step is checked", st(1)[1] == ("done", "home-agent: test it") and mt(1)["next"] == "Oliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper", st(1))
r = upd(2, done="[1]")
check("done as a JSON string", st(2)[0] == ("done", "home-agent: build the thing"), st(2))
r = upd(2, done="2, 3")
check("done as a string of positions", [s for s, _ in st(2)] == ["done", "done", "done", "open"] and mt(2)["next"] == "home-agent: tell the keeper", st(2))
r = upd(3, dropped=[2], done=[1])
check("done and dropped together: each step marked, the open ones left", [s for s, _ in st(3)] == ["done", "dropped", "open", "open"] and mt(3)["next"] == "Oliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper"
      and mt(3)["steps"][1]["by"] == "home-here" and "(step 2 dropped: home-agent: test it)" in r and "(step 1 done: home-agent: build the thing)" in r, (st(3), r))
check("get marks a dropped step", re.search(r"2\. \[dropped · home-here · [^\]]+\] home-agent: test it", server._fmt({**rd(3), "gid": "a3"})) is not None)
r = upd(3, done=[4])
check("a mark alone leaves the other open steps in next", mt(3)["next"] == "Oliver: In PowerShell run `ssh -t box-a 'ls'`" and st(3)[3][0] == "done", (mt(3), st(3)))
refused("the last open step checked by a session on an item that stays open is refused (N6)", lambda: upd(3, done=[3]), "no open step in next", i=3)
r = server._update("a3", sender="home-here", done=[3])        # the server's own write is not judged by N6
check("the last open step checked: next is gone, the checklist stays", "next" not in mt(3) and [s for s, _ in st(3)] == ["done", "dropped", "done", "done"], (mt(3), st(3)))
snap()

# ---- 4. the refusals
refused("a next that no longer lists an open step, with none marked: refused, naming done and dropped, the step and its position; nothing written",
        lambda: upd(4, next="home-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper"), "done=[1]", "dropped=[1]", "home-agent: build the thing", "1.", "a reworded line counts as a new step", "codemode.stackshot_update", i=4)
refused("…two steps lost: both named, with their positions in done and dropped", lambda: upd(4, next="home-agent: test it\nhome-agent: tell the keeper"), "done=[1,3]", "dropped=[1,3]", i=4)
refused("…a mark of another step does not cover it", lambda: upd(4, next="home-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`", done=[4]), "done=[1]", "home-agent: build the thing", i=4)
refused("a reworded line is a line lost and a new one: refused", lambda: upd(4, next="home-agent: build the big thing\nhome-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper"), "home-agent: build the thing", i=4)
refused("a step both done and dropped", lambda: upd(4, done=[1], dropped=[1]), "both done and dropped", i=4)
refused("a position that is not there", lambda: upd(4, done=[9]), "no step 9", "the checklist has 4", i=4)
refused("position 0", lambda: upd(4, done=[0]), "no step 0", i=4)
refused("text that matches no open step: the open ones are listed", lambda: upd(4, done=["home-agent: nothing like it"]), "no open step reads", "1. home-agent: build the thing", i=4)
refused("a step that is already done", lambda: upd(1, done=[1]), "step 1 is already done", i=1)
refused("a step still listed in next while the same call marks it", lambda: upd(4, next=L4, done=[1]), "still lists", "home-agent: build the thing", i=4)
refused("text that matches two open steps: the position is asked for", lambda: upd(16, done=["home-agent: same"]), "matches steps 1, 2", i=16)

# ---- 5. adding and reordering work as before; the open steps take the new order in the places open steps held
r = upd(5, done=[2], next="home-agent: tell the keeper\nhome-agent: build the thing\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: a new step")
check("a next that reorders the open steps and adds one, with a mark: stored as written; the checklist keeps the marked step in place, the open ones in the new order, the new one last",
      mt(5)["next"] == "home-agent: tell the keeper\nhome-agent: build the thing\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: a new step"
      and st(5) == [OPEN("home-agent: tell the keeper"), ("done", "home-agent: test it"), OPEN("home-agent: build the thing"), OPEN("Oliver: In PowerShell run `ssh -t box-a 'ls'`"), OPEN("home-agent: a new step")], st(5))
r = upd(6, next=L4 + "\nhome-agent: and one more")
check("a next that only adds a step works as today", mt(6)["next"] == L4 + "\nhome-agent: and one more" and len(st(6)) == 5 and st(6)[4] == OPEN("home-agent: and one more"), st(6))
r = upd(6, next="home-agent: and one more\n" + L4)
check("…and one that only reorders", mt(6)["next"] == "home-agent: and one more\n" + L4 and [t for _s, t in st(6)][0] == "home-agent: and one more", st(6))
r = upd(6, next="home-agent: and one more\nhome-agent: build the thing\nhome-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`", dropped=["home-agent: tell the keeper"])
check("a step taken out of next with dropped naming it: accepted, the step struck in its place, the open ones in their order",
      ("dropped", "home-agent: tell the keeper") in st(6) and [t for s, t in st(6) if s == "open"] == ["home-agent: and one more", "home-agent: build the thing", "home-agent: test it", "Oliver: In PowerShell run `ssh -t box-a 'ls'`"], st(6))
r = upd(6, dropped=["home-agent: and one more", "home-agent: build the thing", "home-agent: test it", "Oliver: In PowerShell run `ssh -t box-a 'ls'`"], next="home-agent: tell the keeper")
check("a step written again after an earlier call marked it is a new step, open at the end",
      st(6)[-1] == OPEN("home-agent: tell the keeper") and sum(1 for s, t in st(6) if t == "home-agent: tell the keeper") == 2, st(6))

# ---- 6. [metadata.next] require_marks = false: the way back
server._cfg.CFG["metadata"]["next"]["require_marks"] = False
r = upd(7, next="home-agent: test it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: tell the keeper")
check("require_marks = false: a step left out of next reads as dropped, with nobody and no time", st(7)[0] == ("dropped", "home-agent: build the thing") and mt(7)["steps"][0]["by"] == "" and not mt(7)["steps"][0]["at"] and mt(7)["next"].startswith("home-agent: test it"), (st(7), mt(7)["steps"]))
server._cfg.CFG["metadata"]["next"]["require_marks"] = True

# ---- 7. a write that knows nothing of steps
check("a stored open step whose line left next reads as dropped (nobody, no time); a line of next with no step is a new open step at the end",
      st(15) == [OPEN("home-agent: kept"), ("dropped", "home-agent: removed by a write that knows nothing of steps")], st(15))
vv = S.view(mt(15) | {"next": "home-agent: kept\nhome-agent: brand new"})
check("view(): a vanished open step reads as dropped, a new line as open at the end", [(x["status"], S.first_line(x["text"])) for x in vv] == [("open", "home-agent: kept"), ("dropped", "home-agent: removed by a write that knows nothing of steps"), ("open", "home-agent: brand new")]
      and vv[1]["by"] == "" and not vv[1]["at"], vv)

# ---- 8. closing marks the open steps and keeps the record; reopening keeps the marks and takes the new next as an open step
upd(8, done=[1])
r = _wt_complete.stackshot_complete("a8", outcome="done", reason="finished", description="- All done", sender="home-here")
m8 = mt(8)
check("closing marks the open steps: next is gone, the checklist is done all through, by the closer", "next" not in m8 and [x["status"] for x in m8["steps"]] == ["done", "done", "done", "done"] and all(x["by"] == "home-here" and x["at"] for x in m8["steps"]), m8)
g8 = server._fmt({**rd(8), "gid": "a8"})
check("get on the closed item lists the checklist", "checklist:\n1. [done · home-here" in g8 and "2. [done · home-here" in g8 and "home-agent: test it" in g8, g8[-500:])
bd = ui_render.Board(str(STORE))
p8 = bd.item_html("a8")
check("the closed item's page keeps the checklist as a record", 'class="cl-done"' in p8 and p8.count('class="cl-open"') == 0 and p8.count('class="cl-done"') >= 4 and "<h2>Next</h2>" in p8)
refused("a mark on a closed item is refused: reopen it first", lambda: upd(8, done=[2]), "closed", "reopen", i=8)
r = _wt_update.stackshot_update("a8", status="open", next="home-here: a fresh start", sender="home-here")
check("reopening: the steps the close marked stay as marked, the new next is the open step", [s for s, _ in st(8)] == ["done", "done", "done", "done", "open"] and mt(8)["next"] == "home-here: a fresh start", st(8))
r = _wt_update.stackshot_update("a9", status="completed", outcome="done", reason="finished", description="- All done", done=[1], sender="home-here")
check("a mark passed with the close counts; the other open steps are marked done by the close (outcome done)", [s for s, _ in st(9)] == ["done", "done", "done", "done"] and "next" not in mt(9), st(9))
snap()

# ---- 9. History: the page's and the mirror's
bd = ui_render.Board(str(STORE))
ev1 = [re.sub(r"<[^>]+>", "", h) for _t, k, h in bd.item_events(bd.item("a1"))[0] if k == "step"]
check("History says 'step done: …' for a step checked, one line each", any(x == "step done: home-agent: build the thing" for x in ev1) and any(x == "step done: home-agent: test it" for x in ev1), ev1)
ev3 = [re.sub(r"<[^>]+>", "", h) for _t, k, h in bd.item_events(bd.item("a3"))[0] if k == "step"]
check("…and 'step dropped: …' for one dropped", "step dropped: home-agent: test it" in ev3 and "step done: home-agent: build the thing" in ev3, ev3)
check("a step that left next with nobody marking it is no step event (the next line says it)", S.changes({"next": L4}, {"next": "home-agent: test it"}) == [])

# ---- 10. Oliver's Done and Send note (the two buttons of the step form)
r = server._answer("a10", "", "", "done")
m10 = mt(10)
check("Done with an empty box: the item goes on, and his open step (the line that is his) is checked, by Oliver and now; the rest of next stays",
      r == "done" and [x["status"] for x in m10["steps"]] == ["open", "done", "open"] and m10["steps"][1]["by"] == "Oliver" and abs(m10["steps"][1]["at"] - time.time()) < 60
      and m10["next"] == "home-agent: prepare it\nhome-agent: verify it" and "state" not in m10, (r, m10))
r = server._answer("a11", "", "which box?", "note")
m11 = mt(11)
check("Send note leaves his step open: the session that takes the item marks it", r == "stepreply" and "steps" not in m11 and m11["next"] == "home-agent: prepare it\nOliver: In PowerShell run `ssh -t box-a 'ls'`\nhome-agent: verify it", (r, m11))
r = server._answer("a12", "", "", "done")
check("a step that is not a line of next (no line of his) checks nothing; the item still goes on", r == "done" and "steps" not in mt(12) and mt(12)["next"] == "home-agent: look at it", (r, mt(12)))
r = server._answer("a13", "", "", "done")
check("with two lines of his, both are checked (the Your step block shows both; his Done finishes the step), the agent's line stays", st(13) == [("done", "Oliver: look at the page first"), ("done", "Oliver: In PowerShell run `ssh -t box-a 'ls'` on the box"), OPEN("home-agent: verify it")]
      and mt(13)["next"] == "home-agent: verify it" and mt(13)["next_by"] == [[OWNER, NL.key_of("home-agent: verify it")]], (st(13), mt(13)))
snap()
ev10 = [re.sub(r"<[^>]+>", "", h) for _t, k, h in ui_render.Board(str(STORE)).item_events(ui_render.Board(str(STORE)).item("a10"))[0] if k == "step"]
check("…and History says 'step done: …' for his step", ev10 == ["step done: Oliver: In PowerShell run ssh -t box-a 'ls'"], ev10)

# ---- 11. the page
bd = ui_render.Board(str(STORE))
p1 = bd.item_html("a1")
nx = lambda h: h[h.find("<h2>Next</h2></summary>"):h.find('<details class="fold" data-fold="item.description"')]
n1 = nx(p1)
lis = re.findall(r'<li class="cl-(open|done|dropped)">', n1)
check("the page's Next folds the older done steps behind one line, then shows the newest done step and the open steps in the order written: two open, two done",
      lis == ["done", "done", "open", "open"] and '<ul class="inext" aria-label="Next steps">' in n1 and '<summary>1 step done · <span class="sh-show">show</span>' in n1, lis)
check("a done step: a checked box (CSS, aria-hidden), a hidden 'Done' for a screen reader, the text, who · when under it",
      re.search(r'<li class="cl-done"><span class="cb" aria-hidden="true">✓</span><div class="cl-b"><span class="sr">Done: </span><span class="cl-t">home-agent: build the thing</span><span class="cl-by"><b>done</b> by home-here · [^<]+</span></div></li>', n1) is not None, n1[:900])
check("an open step: an empty box and a hidden 'To do'", '<li class="cl-open"><span class="cb" aria-hidden="true"></span><div class="cl-b"><span class="sr">To do: </span>' in n1)
p3 = bd.item_html("a3")
n3 = nx(p3)
check("a dropped step: a box with a cross, 'dropped · who · when' under the text, the text in the struck span",
      re.search(r'<li class="cl-dropped"><span class="cb" aria-hidden="true">×</span><div class="cl-b"><span class="sr">Dropped: </span><span class="cl-t">home-agent: test it</span><span class="cl-by"><b>dropped</b> by home-here · [^<]+</span></div></li>', n3) is not None, n3[:900])
css = bd._css()
check("the style: a done or dropped step is muted, a dropped one struck through, the boxes are CSS, the list is one column that wraps",
      "ul.inext li.cl-dropped .cl-t{text-decoration:line-through}" in css and "ul.inext li.cl-dropped{color:var(--mut);opacity:.75}" in css and "ul.inext .cl-b{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}" in css
      and ".sr{position:absolute;width:1px;height:1px" in css)
check(" style: a done step is a green-filled box with the tick in the page colour, its text at full strength and 'done' in green; a dropped one an empty grey box, muted at .75, struck through, 'dropped' bold",
      "ul.inext li.cl-done .cb{border-color:var(--ok);background:var(--ok);color:var(--bg)}" in css and "ul.inext li.cl-done .cl-by b{color:var(--ok);font-weight:600}" in css
      and "ul.inext li.cl-dropped .cb{border-color:var(--mut);color:var(--mut)}" in css and "ul.inext li.cl-dropped .cl-by b{font-weight:600}" in css
      and "ul.inext li.cl-done{color:var(--mut)" not in css and "ul.inext li.cl-done," not in css)
check("the byline says the verb and the session, 'done by' for a done step and 'dropped by' for a dropped one, in the same shape",
      "<b>done</b> by home-here · " in n1 and "<b>dropped</b> by home-here · " in n3 and "dropped · home-here" not in n3)
check("no form input is drawn in the checklist", "<input" not in n1 + n3 and "checkbox" not in n1 + n3)
check("a legacy item (all open) is a checklist too", re.findall(r'<li class="cl-(\w+)">', nx(bd.item_html("a20"))) == ["open"] * 4)
p14 = bd.item_html("a14")
n14 = nx(p14)
check("hostile text in a step and in who marked it is escaped", "<script>alert(1)" not in p14 and "&lt;script&gt;alert(1)&lt;/script&gt;" in n14 and "<img src=x" not in p14 and "&lt;img src=x onerror=alert(2)&gt;" in n14
      and "<b>bold</b>" not in n14 and re.findall(r'<li class="cl-(\w+)">', n14) == ["done", "open", "open"], n14[:1200])

# ---- 12. the Your step block shows his own open Next lines in full, with copy boxes; Next stays whole
from stackshot.model import step_commands as SC
BOX = {"action": "/items/a21/answer", "token": "TOKEN", "sent": ""}
bd = ui_render.Board(str(STORE))
p21 = bd.item_html("a21", answer=BOX)
ys = re.search(r'<div class="iask istep">.*?</form>', p21, re.S)
blk = ys.group(0) if ys else ""
sn = re.search(r'<div class="istepnext">(.*?)</div></div></div><form', blk, re.S)
sn_html = sn.group(1) if sn else ""
check("the step's summary line passes the step guards (no pointer, no command) and the page holds no pointer such as 'numbered below'",
      SC.problem(rd(21)) == "" and SC.points_elsewhere(STEPY) == "" and "numbered below" not in p21, SC.problem(rd(21)))
check("the Your step block holds his open Next lines in one numbered list, in full, without their 'Oliver:' openers, none of the agent's, and no summary line",
      "One line in PowerShell on your Windows laptop" not in blk and blk.index('<div class="istepnext">') < blk.index("<form") and sn_html.count("<li>") == 3
      and sn_html.startswith('<ol class="stepol"') and "In PowerShell run the command below and read the output" in sn_html and "then paste the" in sn_html and "run this one" in sn_html
      and "Oliver:" not in sn_html and "prepare the box" not in sn_html and "check what he pasted" not in sn_html, sn_html[:900])
check("each command is a code block with a Copy button under its line: a backticked span with a space in it, a sub line's, and a fenced block",
      sn_html.count('<div class="cmd">') == 3 and "ssh -t box-a &#x27;sala ready&#x27;</code></pre><button" in sn_html and "Get-Date</code></pre><button" in sn_html
      and "Get-Date -Format o</code></pre><button" in sn_html and sn_html.count('class="b copy"') == 3, sn_html[:1200])
check("hostile text is escaped", "<script>alert(3)" not in p21 and "&lt;script&gt;alert(3)&lt;/script&gt;" in sn_html, sn_html[:900])
nx21 = nx(p21)
check("Next stays whole: every step of the checklist, his and the agent's, open, the openers in place, so it reads on its own",
      re.findall(r'<li class="cl-(\w+)">', nx21) == ["open"] * 5 and nx21.count("Oliver:") >= 3 and "home-agent: prepare the box" in nx21 and "home-agent: check what he pasted" in nx21, nx21[:900])
p22, p23 = bd.item_html("a22", answer={**BOX, "action": "/items/a22/answer"}), bd.item_html("a23", answer={**BOX, "action": "/items/a23/answer"})
check("with no line of his in next the block has no list; an unnamed line is his",
      'class="istepnext"' not in p22 and 'class="iask istep"' in p22 and '<div class="istepnext"><ol' in p23 and "run the command below and say so" in p23, p23[p23.find("istepnext") - 40:][:400])
r = server._answer("a21", "", "", "done")
m21 = mt(21)
p21b = ui_render.Board(str(STORE)).item_html("a21", answer=BOX)
check("his Done checks his three open steps: checked, by Oliver and now; the agent's stay open; the item goes on",
      r == "done" and [x["status"] for x in m21["steps"]] == ["open", "done", "done", "done", "open"] and m21["steps"][1]["by"] == "Oliver" and "state" not in m21 and 'class="istepnext"' not in p21b,
      (r, [x["status"] for x in m21.get("steps", [])]))
nx21b = nx(ui_render.Board(str(STORE)).item_html("a21"))
check("…and Next folds two of his three checked steps (by Oliver), shows the newest of them, then the agent's steps still open", re.findall(r'<li class="cl-(\w+)">', nx21b) == ["done", "done", "done", "open", "open"] and "Oliver · " in nx21b and "<summary>2 steps done · " in nx21b, nx21b[:700])
back = rd(21); back["metadata"].update(state="your-step", step=STEPY, next=mt(21)["next"] + "\nOliver: and then read it back"); [back["metadata"].pop(k, None) for k in ("answers", "mover", "next_by")]; (T / "store/a/21.json").write_text(json.dumps(back)); snap()
p21c = ui_render.Board(str(STORE)).item_html("a21", answer=BOX)
sn2 = re.search(r'<div class="istepnext">(.*?)</div></div></div><form', p21c, re.S)
check("handed back to him with a new line of his: only his steps still open are in the block, the ones checked have left it", sn2 is not None and sn2.group(1).count("<li>") == 1 and "read it back" in sn2.group(1) and "In PowerShell run" not in sn2.group(1),
      (sn2 and sn2.group(1)[:500]) or ({k: v for k, v in rd(21).items() if k != "metadata"}, sorted(mt(21)), re.findall(r'class="istate[^"]*"[^>]*>.{0,200}', p21c)[:2]))

# ---- 13. two writers on one item: a mark reaches any open step, an unmarked drop is refused for the sender's own lines only, clear_next wipes and marks
upa(30, next="home-agent: agent line")
check("the agent's update adds its line after the keeper's, the keeper's lines stay and keep their writer",
      mt(30)["next"] == "home-here: keeper line one\nOliver: keeper line two\nhome-agent: agent line" and [p[0] for p in mt(30)["next_by"]] == [OWNER, OWNER, AGENT]
      and [x["writer"] for x in S.view(mt(30)) ] == [OWNER, OWNER, AGENT], (mt(30)["next"], mt(30).get("next_by")))
refused("the agent replaces its own line and leaves it out unmarked: refused, naming the step and its position, and what to pass",
        lambda: upa(30, next="home-agent: another line"), "your open step", "3. home-agent: agent line", "done=[3]", "dropped=[3]", "clear_next=true", i=30)
refused("next=none by the agent without a mark: the same refusal (its own line would go unmarked)", lambda: upa(30, next="none"), "3. home-agent: agent line", "dropped=[3]", i=30)
upa(30, next="home-agent: another line", dropped=[3])
check("…marked dropped in the same update it passes: the step is struck, by the agent, the new line is open at the end, the keeper's lines untouched",
      st(30) == [OPEN("home-here: keeper line one"), OPEN("Oliver: keeper line two"), ("dropped", "home-agent: agent line"), OPEN("home-agent: another line")]
      and mt(30)["steps"][2]["by"] == "home-agent" and mt(30)["next"] == "home-here: keeper line one\nOliver: keeper line two\nhome-agent: another line", (st(30), mt(30)["next"]))
upa(30, next="home-agent: another line\nhome-agent: and one more")
check("the agent adds a line to its own: nothing is lost, nothing is asked", mt(30)["next"].endswith("home-agent: another line\nhome-agent: and one more") and len(st(30)) == 5, st(30))
refused("the keeper leaves one of its own lines out unmarked: refused for that line only (the agent's lines are not its to answer for)",
        lambda: upd(30, next="home-here: keeper line one\nhome-here: and a new keeper line"), "your open step", "2. Oliver: keeper line two", "done=[2]", i=30)
r = upa(30, done=[1])
check("the agent marks the keeper's line done: it leaves next with its writer pair; the others keep theirs",
      st(30)[0] == ("done", "home-here: keeper line one") and mt(30)["steps"][0]["by"] == "home-agent"
      and mt(30)["next"] == "Oliver: keeper line two\nhome-agent: another line\nhome-agent: and one more" and [p[0] for p in mt(30)["next_by"]] == [OWNER, AGENT, AGENT], (st(30), mt(30)))
r = upa(30, dropped=["Oliver: keeper line two"])
check("…and drops another's line by its exact text: struck, by the agent", st(30)[1] == ("dropped", "Oliver: keeper line two") and mt(30)["steps"][1]["by"] == "home-agent" and "Oliver: keeper line two" not in mt(30)["next"]
      and [p[0] for p in mt(30)["next_by"]] == [AGENT, AGENT], (st(30), mt(30)))
refused("next=none with every own line marked, leaving no open step on an open item: refused (N6)", lambda: upa(30, next="none", dropped=["home-agent: another line", "home-agent: and one more"]), "no open step in next", i=30)
r = upi(30, next="none", dropped=["home-agent: another line", "home-agent: and one more"])
check("next=none with every own line marked: accepted, next is gone, the checklist stays", "next" not in mt(30) and "next_by" not in mt(30) and [s for s, _ in st(30)][-2:] == ["dropped", "dropped"], (st(30), mt(30)))
refused("a mark still listed in the same call's next is refused", lambda: upd(31, next="home-here: keeper line one", done=[1]), "still lists", i=31)
upa(31, next="home-agent: agent line"); snap()
refused("clear_next=true on an item that stays open and has no step of Oliver's: refused (N6)", lambda: upa(31, clear_next=True), "no open step in next", i=31)
r = upi(31, clear_next=True); snap()
check("clear_next=true is a deliberate wipe: every line, whoever wrote it, becomes a dropped step by the sender; next and its writers are gone",
      [s for s, _ in st(31)] == ["dropped"] * 3 and all(x["by"] == "home-agent" for x in mt(31)["steps"]) and "next" not in mt(31) and "next_by" not in mt(31), (st(31), mt(31)))
ev31 = [re.sub(r"<[^>]+>", "", h) for _t, k, h in ui_render.Board(str(STORE)).item_events(ui_render.Board(str(STORE)).item("a31"))[0] if k == "step"]
check("…and History says 'step dropped: …' for each", {"step dropped: home-here: keeper line one", "step dropped: Oliver: keeper line two", "step dropped: home-agent: agent line"} <= set(ev31), ev31)
upa(32, next="home-agent: agent line")
r = upa(32, clear_next=True, next="home-agent: a fresh start")
check("clear_next with a next: the wipe comes first (the lines become dropped steps), then the sender's lines are the open steps",
      [s for s, _ in st(32)] == ["dropped", "dropped", "dropped", "open"] and mt(32)["next"] == "home-agent: a fresh start" and mt(32)["next_by"][0][0] == AGENT, (st(32), mt(32)))
r = upa(33, done=[2], next="home-agent: agent line")
check("a mark of another session's line together with the sender's own new line: both land, the marked line leaves next",
      st(33) == [OPEN("home-here: keeper line one"), ("done", "Oliver: keeper line two"), OPEN("home-agent: agent line")] and mt(33)["next"] == "home-here: keeper line one\nhome-agent: agent line", (st(33), mt(33)))
check("get and the home row show the first open step", server._fmt({**rd(33), "gid": "a33"}).count("next:\nhome-here: keeper line one") == 1 and H.first_next(mt(33)["next"], ("home-here",))[1] == "keeper line one", None)
upd(34, done=[1])
check("get shows the first open step after the first is done: next starts with the second", server._fmt({**rd(34), "gid": "a34"}).find("next:\nOliver: keeper line two") > 0 and H.first_next(mt(34)["next"], ("home-here",))[0] == "Oliver", mt(34))
refused("a nonsense mark (an index past the list) names the checklist's length", lambda: upa(34, dropped=[9]), "there is no step 9", "the checklist has", i=34)

# ---- 13b. a line kept verbatim is never stored twice (example-site-builder kept "ask Sam" on its list; the line was example-site-main's, so the update added a copy,
# and dropping the copy was refused because its text still sat in next)
SH = "home-here: shared step"
def pairs(*rows): return [[w, NL.key_of(e)] for e, w in rows]
item(35, next=f"{SH}\nOliver: other step")                                                       # the keeper's two lines (no writer stored)
snap()
r = upa(35, next=f"home-agent: new step\n{SH}")                                                    # the agent keeps another session's step on its list, verbatim
check("a line of the sender's next that another session's open line already reads is not added a second time: that step stays, its writer's",
      mt(35)["next"] == f"{SH}\nOliver: other step\nhome-agent: new step" and [p[0] for p in mt(35)["next_by"]] == [OWNER, OWNER, AGENT]
      and [s for s, _ in st(35)] == ["open"] * 3 and sum(1 for _, t in st(35) if t == SH) == 1, (mt(35)["next"], st(35)))
check("…and the reply says which line was kept and whose it is", f'(next: "{SH}" is already an open step of home-here: it stays as it is, not added a second time)' in r, r)
r = upa(35, next=f"home-agent: new step\n{SH}")
check("the same update again changes nothing (one copy of each, the agent's line its own)", mt(35)["next"] == f"{SH}\nOliver: other step\nhome-agent: new step" and len(st(35)) == 3 and "already an open step" in r, (mt(35)["next"], st(35)))
upa(35, next=f"home-agent: new step\n- **{SH}**")
check("…a list marker and bold marks do not make a different line", len(st(35)) == 3 and mt(35)["next"].count("shared step") == 1, (mt(35)["next"], st(35)))
OWN = [("home-agent: own step", AGENT), ("home-agent: second own step", AGENT)]
item(36, next="\n".join(e for e, _ in OWN), next_by=pairs(*OWN))                          # the agent's own lines: written again, they are replaced in place, never doubled
snap()
upa(36, next="\n".join(e for e, _ in OWN))
check("the sender's own lines written again stay as they are", mt(36)["next"] == "\n".join(e for e, _ in OWN) and len(st(36)) == 2, (mt(36)["next"], st(36)))

DUP = [("home-agent: new step", AGENT), (SH, AGENT), ("Oliver: other step", OWNER), (SH, OWNER)]       # the store as 207 stood: the same text twice, two writers
def dup_item(i):
    item(i, next="\n".join(e for e, _ in DUP), next_by=pairs(*DUP), steps=[{"text": e, "status": "open"} for e, _ in DUP]); snap()
dup_item(37); dup_item(38); dup_item(39)
r = upa(37, next=f"home-agent: new step\n{SH}", dropped=[4])
check("with two open steps of the same text, dropping one by position while next keeps the other is not refused: one copy leaves next, the step is struck",
      st(37) == [OPEN("home-agent: new step"), OPEN("Oliver: other step"), OPEN(SH), ("dropped", SH)] and mt(37)["next"].count(SH) == 1 and mt(37)["steps"][3]["by"] == "home-agent" and "step 4 dropped" in r, (st(37), mt(37)["next"], r))
r = upa(38, dropped=[4])
check("…and a drop with no next does the same", st(38) == [OPEN("home-agent: new step"), OPEN("Oliver: other step"), OPEN(SH), ("dropped", SH)] and mt(38)["next"].count(SH) == 1, (st(38), mt(38)["next"]))
refused("a step marked while next still lists the only copy of its text is still refused", lambda: upa(39, next=f"home-agent: new step\n{SH}\nOliver: other step", dropped=[3, 2, 4]), "still lists", i=39)
r = upa(39, next=f"home-agent: new step\n{SH}\nOliver: other step\n{SH}")
check("an update that leaves duplicates as they are does not collapse them (the agent has its own copy)", mt(39)["next"].count(SH) == 2 and len(st(39)) == 4, (mt(39)["next"], st(39)))

# ---- 14. nextlines.prune: the unit under the marks
pm = {"owner": "k", "next": "a: one\nb: two\nc: three", "next_by": [["k", NL.key_of("a: one")], ["w", NL.key_of("b: two")], ["k", NL.key_of("c: three")]]}
check("nextlines.prune takes the lines out of next with their writers; the others keep theirs; a text that is not there is skipped",
      NL.prune(pm, ["b: two", "zz: nothing"], "k") == 1 and pm["next"] == "a: one\nc: three" and pm["next_by"] == [["k", NL.key_of("a: one")], ["k", NL.key_of("c: three")]]
      and NL.prune(pm, ["a: one", "c: three"], "k") == 2 and "next" not in pm and "next_by" not in pm and NL.prune(pm, ["a: one"], "k") == 0, pm)

# ---- 14b. the page draws the finished steps first (by when they were marked), then the open ones; stored order, next and get's positions are unchanged
item(41, next="home-agent: step A\nhome-agent: step C", steps=[
    {"text": "home-agent: step A", "status": "open"}, {"text": "home-agent: step B", "status": "done", "by": "home-here", "at": now - 200},
    {"text": "home-agent: step C", "status": "open"}, {"text": "home-agent: step D", "status": "dropped", "by": "home-here", "at": now - 300},
    {"text": "home-agent: step E", "status": "done", "by": "home-here", "at": now - 100}])
snap()
n41 = nx(ui_render.Board(str(STORE)).item_html("a41"))
check("the page's Next folds the earlier steps by the time they were marked (dropped and done together), then shows the newest done step and the open steps in their planned order",
      re.findall(r'<span class="cl-t">home-agent: step (.)</span>', n41) == ["D", "B", "E", "A", "C"] and re.findall(r'<li class="cl-(open|done|dropped)">', n41) == ["dropped", "done", "done", "open", "open"], n41[:900])
check("…while the stored steps, next and the checklist the tools list stay in the stored order",
      [x["text"][-1] for x in mt(41)["steps"]] == list("ABCDE") and mt(41)["next"] == "home-agent: step A\nhome-agent: step C" and [x["text"][-1] for x in S.view(mt(41))] == list("ABCDE"), mt(41))
g41 = server._fmt({**rd(41), "gid": "a41"})
check("…and get's checklist positions are the stored ones",
      re.search(r"checklist:\n1\. \[open\] home-agent: step A\n2\. \[done · home-here · [^\]]+\] home-agent: step B\n3\. \[open\] home-agent: step C\n4\. \[dropped · home-here · [^\]]+\] home-agent: step D\n5\. \[done · home-here · [^\]]+\] home-agent: step E", g41) is not None, g41[g41.find("next:"):])
item(42, next="home-agent: build option A", steps=[
    {"text": "home-agent: first look", "status": "done", "by": "home-agent", "at": now - 500}, {"text": "home-agent: build option A", "status": "open"},
    {"text": "home-agent: second look", "status": "dropped", "by": "home-agent", "at": now - 100}],
    answers=[{"ts": now - 300, "kind": "decision", "choice": "A", "choice_line": "do it the <b>short</b> way", "via": "board"},
             {"ts": now - 250, "kind": "comment", "text": "just a comment", "via": "board"}, {"ts": now - 240, "kind": "step-reply", "text": "a note on his step", "via": "board"},
             {"ts": now - 200, "kind": "decision", "choice": "Approve", "via": "board"}, {"ts": now - 150, "kind": "decision", "text": "go ahead,\nplease", "via": "board"}])
snap()
n42 = nx(ui_render.Board(str(STORE)).item_html("a42"))
check("his decision answers are drawn among the finished rows by time (a pick with its option line, a pick without one, his words); comments and notes on his step are not drawn; the fold holds the older rows, the newest finished row and the open step follow it",
      re.findall(r'<li class="cl-(\w+)">', n42) == ["done", "decided", "decided", "dropped", "decided", "open"]
      and re.findall(r'<span class="cl-t">(.*?)</span>', n42) == ["home-agent: first look", "Oliver: picked A (do it the &lt;b&gt;short&lt;/b&gt; way)", "Oliver: picked Approve", "home-agent: second look", "Oliver: go ahead, please", "home-agent: build option A"]
      and "just a comment" not in n42 and "a note on his step" not in n42, n42[:1400])
check("…a decided row: a checked box, a hidden 'Decided', 'decided on the board · when' under the text",
      re.search(r'<li class="cl-decided"><span class="cb" aria-hidden="true">✓</span><div class="cl-b"><span class="sr">Decided: </span><span class="cl-t">Oliver: picked Approve</span><span class="cl-by"><b>decided on the board</b> · [^<]+</span></div></li>', n42) is not None, n42[:1400])
g42 = server._fmt({**rd(42), "gid": "a42"})
check("…and get's checklist has the steps alone, at the stored positions, with no row for his decisions",
      re.search(r"checklist:\n1\. \[done · home-agent · [^\]]+\] home-agent: first look\n2\. \[open\] home-agent: build option A\n3\. \[dropped · home-agent · [^\]]+\] home-agent: second look", g42) is not None
      and "picked" not in g42[g42.find("checklist:"):] and [x["text"] for x in S.view(mt(42))] == ["home-agent: first look", "home-agent: build option A", "home-agent: second look"], g42[g42.find("next:"):])
check("drawn_order is stable for finished steps marked at the same time or with no time, and leaves the list it is given alone",
      [x["text"] for x in S.drawn_order([S._step("o1"), S._step("d1", S.DONE, "k", 5), S._step("o2"), S._step("x1", S.DROPPED, "k", 5), S._step("z", S.DONE, "k", 0)])] == ["z", "d1", "x1", "o1", "o2"])

# ---- 14c. reword: an open step gets new words and keeps its number, its place and its open state (no drop plus a new step)
import hashlib
kk = lambda t: hashlib.sha1(t.strip().encode("utf-8")).hexdigest()[:10]
for i in (50, 51, 54, 55, 56, 57, 58, 59):
    item(i)                                                           # the four lines of L4, the keeper's (home-here's)
item(52, step_proof={"home-agent: test it": "pr_merged o/r#7"})
item(53, next="home-agent: first\nhome-here: second", next_by=[[AGENT, kk("home-agent: first")], [OWNER, kk("home-here: second")]])      # a line of each writer
snap()
RW, OL = "home-agent: run the tests again", "Oliver: In PowerShell run `ssh -t box-a 'ls'`"
upd(50, done=[1])
r = upd(50, reword={2: RW})
check("reword alone: step 2 (a position counts the done step) has the new words, keeps its number and place and stays open; the others stay as they were",
      st(50) == [("done", "home-agent: build the thing"), OPEN(RW), OPEN(OL), OPEN("home-agent: tell the keeper")], st(50))
check("…next holds the new text in the same place, as every reader reads it, with the same writers", mt(50)["next"] == f"{RW}\n{OL}\nhome-agent: tell the keeper"
      and NL.writers_of(mt(50), mt(50)["owner"]) == [OWNER] * 3, (mt(50)["next"], mt(50).get("next_by")))
check("…the reply says which step was reworded, from what to what", "(step 2 reworded: home-agent: test it → home-agent: run the tests again)" in r, r)
check("…the stored steps keep the done step's mark and the number of the others", [(x["status"], x["text"]) for x in mt(50)["steps"]][:2] == [("done", "home-agent: build the thing"), ("open", RW)] and len(mt(50)["steps"]) == 4, mt(50)["steps"])
r = upd(50, reword={RW: "home-agent: run the suite once more"})
check("reword by the exact text of the open step's first line", st(50)[1] == OPEN("home-agent: run the suite once more"), st(50))
r = upd(50, reword='{"2": "home-agent: run the suite a last time"}')
check("reword as a JSON string, the key the position as a string", st(50)[1] == OPEN("home-agent: run the suite a last time") and "(step 2 reworded:" in r, st(50))
before, st_before = rd(50), st(50)
r = upd(50, reword={2: "home-agent: run the suite a last time"})
check("a new text the step already reads changes nothing and says nothing", st(50) == st_before and mt(50)["next"] == before["metadata"]["next"] and "reworded" not in r, r)
N4 = "home-agent: build the big thing\nhome-agent: test it\n" + OL + "\nhome-agent: tell the keeper"
r = upd(51, reword={1: "home-agent: build the big thing"}, next=N4)
check("reword with a next that lists the new text: accepted; the step keeps its number, the others stay", st(51)[0] == OPEN("home-agent: build the big thing") and len(st(51)) == 4 and mt(51)["next"] == N4, (st(51), mt(51)["next"]))
refused("reword with a next that still lists the old text: refused with the text the step was given; nothing written",
        lambda: upd(54, reword={1: "home-agent: build the big thing"}, next=L4), "reword gives step 1 the text", "build the big thing", "leave next out of the call", i=54)
r = upd(52, reword={2: "home-agent: retest it"})
check("a step that names its proof keeps it under the new words", mt(52).get("step_proof") == {"home-agent: retest it": "pr_merged o/r#7"} and st(52)[1] == OPEN("home-agent: retest it"), (mt(52).get("step_proof"), st(52)))
upd(55, done=[1]); upd(55, dropped=[2])
refused("reword of a done step is refused: only an open step", lambda: upd(55, reword={1: "home-agent: build it again"}), "step 1 is already done", "only an open step is reworded", i=55)
refused("reword of a dropped step is refused", lambda: upd(55, reword={2: "home-agent: test it again, later"}), "step 2 is already dropped", "only an open step is reworded", i=55)
refused("reword of a position that is not there", lambda: upd(55, reword={9: "home-agent: x"}), "reword: there is no step 9", "the checklist has 4", i=55)
refused("reword of position 0", lambda: upd(55, reword={0: "home-agent: x"}), "no step 0", i=55)
refused("reword by text that matches no open step: the open ones are listed", lambda: upd(55, reword={"home-agent: nothing like it": "home-agent: x"}), "reword: no open step reads", "3. ", i=55)
refused("a step in reword and in done", lambda: upd(55, reword={3: "home-agent: other words here"}, done=[3]), "step 3 is in reword and in done or dropped", i=55)
refused("a step in reword and in dropped", lambda: upd(55, reword={3: "home-agent: other words here"}, dropped=[3]), "in reword and in done or dropped", i=55)
refused("his step (a line opening with his name) is never reworded", lambda: upd(55, reword={3: "Oliver: some other thing"}), "Oliver's own step", i=55)
refused("another session's step is not reworded by this sender", lambda: upd(53, reword={1: "home-agent: opening move"}), "reword: step 1 is a line of", "only the session that wrote a step rewords it", i=53)
r = upa(53, reword={1: "home-agent: opening move"})
check("…the session that wrote it rewords it, and the other writer's line stays", st(53) == [OPEN("home-agent: opening move"), OPEN("home-here: second")] and NL.writers_of(mt(53), mt(53)["owner"]) == [AGENT, OWNER], (st(53), mt(53).get("next_by")))
refused("the old text with words added is the rewrite N3 refuses (progress goes on the page)", lambda: upd(56, reword={1: "home-agent: build the thing (PR 5)"}), "with words added", "dropped=[1]", "project page", i=56)
refused("a new text that names no one is refused as a line of next is", lambda: upd(56, reword={1: "build the other thing"}), "names no one", i=56)
refused("a new text over the limit is refused as a line of next is", lambda: upd(56, reword={1: "home-agent: " + "w" * 201}), "a line of next is 201 characters after its `<actor>: ` prefix", "limit is 200", i=56)
r = upd(56, reword={1: "home-agent: " + "w" * 200})
check("…200 characters after the prefix pass", S.first_line(st(56)[0][1]) == "home-agent: " + "w" * 200, st(56)[0])
refused("a new text of several steps is refused", lambda: upd(57, reword={1: "home-agent: one\nhome-agent: two"}), "more than one step", i=57)
refused("an empty new text is refused", lambda: upd(57, reword={1: "  "}), "non-empty string", i=57)
refused("a new text another open step already reads is refused", lambda: upd(57, reword={1: "home-agent: test it"}), "would read the same as open step 2", i=57)
refused("reword that is not a mapping is refused with the form", lambda: upd(57, reword=[1, 2]), "reword takes a mapping", i=57)
refused("reword with a string that is not a mapping is refused", lambda: upd(57, reword="not json"), "reword takes a mapping", i=57)
refused("reword with clear_next is refused", lambda: upd(57, reword={1: "home-agent: other words here"}, clear_next=True), "clear_next=true", i=57)
_wt_complete.stackshot_complete("a58", outcome="done", reason="finished", outcome_text="- All done", sender="home-here")
refused("reword on a closed item is refused (the checklist is the record)", lambda: upd(58, reword={1: "home-agent: other words here"}), "is closed", "reopen it", i=58)
refused("reword in a close is refused", lambda: upd(59, status="completed", outcome="done", reason="finished", outcome_text="- All done", reword={1: "home-agent: other words here"}), "reword changes the words of a step that stays open", i=59)
refused("the refusal of an unmarked step left out of next prints the retry calls with the number filled in, in one line", lambda: upd(4, next="home-agent: test it\n" + OL + "\nhome-agent: tell the keeper"),
        'Retry with done=[1], dropped=[1] or reword={1: "<new text>"}.', "a reworded line counts as a new step", "reword the step itself", i=4)
refused("…two steps: both numbers in each call", lambda: upd(4, next="home-agent: test it\nhome-agent: tell the keeper"), 'Retry with done=[1,3], dropped=[1,3] or reword={1: "<new text>", 3: "<new text>"}.', i=4)
item(60); upd(60, done=[1])
refused("…the number is the step's position in the checklist, marked steps counted", lambda: upd(60, next="home-agent: test it\nhome-agent: tell the keeper"), 'Retry with done=[3], dropped=[3] or reword={3: "<new text>"}.', "3. Oliver:", i=60)
for empty in ({}, "{}", " ", ""):
    was58, was57 = rd(58), rd(57)
    r = upd(58, reword=empty)
    check(f"reword={empty!r} counts as not given: a closed item is not refused for it", r.startswith("updated a58") and rd(58)["status"] == "completed", r)
    r = upd(57, reword=empty)
    check(f"…and on an open item it is no state change (the state clock, the confirm and the steps stay)", (rd(57)["state_updated"], rd(57)["confirmed"], rd(57)["metadata"].get("steps"), rd(57)["metadata"]["next"])
          == (was57["state_updated"], was57["confirmed"], was57["metadata"].get("steps"), was57["metadata"]["next"]) and "reworded" not in r, r)
check("steps.reword_given: None, {}, '{}' and blank text are not given; a mapping, a non-mapping and text that is no JSON are", [S.reword_given(x) for x in (None, {}, "{}", "", "  ", {1: "a: b"}, '{"1": "a: b"}', [1], "not json", 5)]
      == [False, False, False, False, False, True, True, True, True, True])
item(63)
refused("two steps reworded to the same new text are refused", lambda: upd(63, reword={1: "home-agent: one new text", 2: "home-agent: one new text"}), "steps 1 and 2 would both read", i=63)
refused("…also when the two texts differ only in spacing or a list marker", lambda: upd(63, reword={1: "home-agent: one new text", 2: "- home-agent:  one new   text"}), "would both read", i=63)
refused("a swap of two steps' texts is refused (it would desync next and the proofs)", lambda: upd(63, reword={1: "home-agent: test it", 2: "home-agent: build the thing"}), "step 1 would read the same as open step 2", "whose own words change in this call too", "separate calls", i=63)
refused("a shift of texts (a new text another reworded step has now) is refused", lambda: upd(63, reword={1: "home-agent: test it", 2: "home-agent: something else entirely"}), "whose own words change in this call too", i=63)
r = upd(63, reword={1: "home-agent: build it first", 2: "home-agent: run the tests later"})
check("two rewords to two different new texts, neither one a text a step holds now, are accepted", st(63)[:2] == [OPEN("home-agent: build it first"), OPEN("home-agent: run the tests later")], st(63))
item(61); item(62)
r = upd(61, reword={1: "home-agent: re-check 0109c0de0"})
check("the advisory notes run over the reworded text as over next: a commit hash in it draws the report note", "(step 1 reworded:" in r and "next reads like a report (a commit hash (0109c0de0))" in r, r)
r = server._update("a62", sender="home-here", reword={1: "home-agent: read https://example.com/x"})
check("…and a naked URL in it draws the naked-URL note (a script's write is not refused for it)", "a naked URL (https://example.com/x)" in r, r)
vm = S.view({"next": L4})
check("steps.resolve_reword: positions, texts and JSON keys; a no-op is left out; nothing is changed in the checklist given",
      S.resolve_reword(vm, {"2": "home-agent: x"}) == {1: "home-agent: x"} and S.resolve_reword(vm, {"home-agent: test it": "home-agent: y"}) == {1: "home-agent: y"} and S.resolve_reword(vm, None) == {}
      and S.resolve_reword(vm, {1: "home-agent: build the thing"}) == {} and [x["text"] for x in vm][:2] == ["home-agent: build the thing", "home-agent: test it"], S.resolve_reword(vm, {"2": "home-agent: x"}))
tx = {"next": "a: one\nb: two", "next_by": [["k", NL.key_of("a: one")], ["w", NL.key_of("b: two")]]}
check("nextlines.reword changes one line in place with its writer; a text that is not there changes nothing",
      NL.reword(tx, "b: two", "b: 2", "k") and tx["next"] == "a: one\nb: 2" and tx["next_by"] == [["k", NL.key_of("a: one")], ["w", NL.key_of("b: 2")]] and not NL.reword(tx, "zz: none", "z: x", "k"), tx)

# ---- 15. the tools' text
sig = __import__("inspect").signature(_wt_update.stackshot_update.fn if hasattr(_wt_update.stackshot_update, "fn") else _wt_update.stackshot_update)
check("update takes done and dropped; its description teaches the checklist", {"done", "dropped"} <= set(sig.parameters) and "next is a checklist" in _wt_text._lead(_wt_update._UPDATE_DESC + _wt_update._CHECKLIST_FORM)
      and "done=[…]" in _wt_update._CHECKLIST_FORM and "dropped=[…]" in _wt_update._CHECKLIST_FORM and "step done: …" in _wt_update._CHECKLIST_FORM, list(sig.parameters)[-4:])
check("update takes reword; the parameter's description, the checklist text and the refusals' text teach it and the retry call",
      "reword" in sig.parameters and "reword={n:" in _wt_update._CHECKLIST_FORM and "done=[n], dropped=[n] or reword={n:" in _wt_update._CHECKLIST_FORM and "reword={n:" in _wt_text._NEXT_REFUSALS
      and "keeps its number" in _wt_update._REWORD_PARAM.__metadata__[0].description and "same action in other words" in _wt_update._CHECKLIST_FORM and "after its `<actor>: ` prefix" in _wt_text._ITEM_FORM,
      _wt_update._REWORD_PARAM.__metadata__[0].description[:300])

print(("ok" if not fails else "FAILED") + f": checklist scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
