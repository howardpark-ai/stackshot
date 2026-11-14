"""Scenario test for Oliver's answer from an item's page (the item phase 3; design: the design doc,
"Proposal" and "Revised proposal", OK'd Mon Oct 12th 2026) — fixture data, the HTTP routes through Starlette's test client,
no live store, no network (the GitHub mirror is on, and its queue is read, never drained).

Covers: the item page of an open item that needs his decision carries one button per option, the recommended one first and
marked (Approve and Decline only when the owner stored them as options); an ask with none gets Yes (recommended, first) and No beside the box and its one Send, and an item with options never gets them; every open item carries the text box with one "Send": his answer while it needs his decision, a
comment otherwise; a closed item, and a viewer who is not signed in, get no form. POST /items/<n>/answer is refused (403) without the
board's sign-in, without the page's token or with another item's, and from another origin (or with no Origin and no Referer);
nothing is written then. An option's button records his answer: decision leaves needs, the sessions named stay, the ask is
cleared, metadata.answers holds {ts, kind, choice, via}, the state clock moves; Send, while the item needs his decision, does the same with his text;
Send on an item that needs none is a comment and changes neither needs nor the ask.
A pick among the item's options also clears its options (his answer keeps the option's label and line, shown by get and History); free text,
a stale choice and a comment leave them; the update tool clears options (options=[] or clear_options) and the ask (clear_ask) and still refuses a bad list. Each is pushed, one line, to the owner and to every session named in
needs (a front-agent owner's line marked [for Oliver]); with the mirror on nothing of it reaches the issue.
The POST answers 303 back to the item's page with a short notice; a stale choice, an empty box and a closed item send nothing.
The page sends the form by script (a fetch that follows the 303, then location.replace, so the answer replaces the page in
history), with the plain form as the no-script fallback; item and project pages reload when restored from the back-forward
cache, and item pages and the 303 are served no-store; a fetch-style POST (url-encoded, following the redirect) lands on the
item's page with its notice.
An old id's address answers the item it names now. A decision answer nobody it was sent to has followed with a write goes to
the project's keeper once after 30 min; the owner's write settles it. History shows "Oliver (board): …". The update,
complete and confirm tools refuse a sender that names itself Oliver.

    tests/run-suite answer        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, tempfile, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="answertest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                     (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
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
STEW = "00000000-0000-4000-8000-000000000003"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now},
                                                     STEW: {"name": "home-keeper", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-keeper", "agents": {"home-here": "builds it"}, "back_agents": {"home-here": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
DESC = "A thing. It lives here. Finished when it works."
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
YESNO = "Decide: whether to go ahead · Recommend: go · Stakes: a day either way · By: no date"
YN = [{"label": "Approve", "line": "Go ahead as proposed", "recommended": True}, {"label": "Decline", "line": "Do not go ahead", "recommended": False}]   # Approve and Decline are options like any other: only an owner who lists them gets them
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]
def item(L, i, status="open", **meta):
    (T / f"store/{L}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {L}{i}", "description": DESC, "status": status,
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", **meta}}))
item("a", 1, needs=["decision", "home-agent"], ask=ASK, options=OPTS)      # options, a session named in needs
item("a", 2, needs=["decision"], ask=YESNO, options=YN)                   # a yes/no ask with Approve and Decline stored as its options
item("a", 3)                                                              # on agent: comment box only
item("a", 4, status="completed", outcome="done", reason="it worked")
item("a", 5, needs=["decision"], ask=YESNO)                               # a comment leaves it as it is
item("a", 6, needs=["decision"], ask=YESNO, options=YN)                   # a front-agent owner
item("a", 7, needs=["decision"], ask=YESNO)                               # answered by text, then the escalation
item("a", 8, needs=["decision"], ask=ASK, options=OPTS)                  # options, answered in free text
item("a", 9, needs=["decision", "home-agent"], ask=ASK, options=OPTS)       # options, an option picked with a note
item("a", 10, needs=["decision"], ask=ASK, options=OPTS)                  # options, a choice that matches none; then a comment
item("a", 11, needs=["decision"], ask=ASK, options=OPTS)                  # the update tool clears options and ask
item("a", 12, needs=["decision"], ask=YESNO)                              # its subject carries what could be smuggled into an address
_d12 = json.loads((T / "store/a/12.json").read_text()); _d12["subject"] = "[home] spoof &x=1#frag 100% \r\nSet-Cookie: a=1 \U0001F600 &sent=decision"; (T / "store/a/12.json").write_text(json.dumps(_d12))
STEP = "run the one line `sala op reauth box-a --from me --words \"go\"`"
item("a", 13, state="your-step", step=STEP, needs=["home-agent"])                # a step item: Oliver moves, then home-agent (the first session in needs)
item("a", 14, state="your-step", step=STEP)                                   # a step item with no session in needs: then the owner
item("a", 15, state="your-step", step=STEP, needs=["home-agent"])               # a note sent on its own
item("a", 16, state="your-step", step=STEP, needs=["home-agent"])               # the page's token for the item page's own Done
item("a", 17, needs=["decision"], ask=YESNO, options=YN)                      # a decision item: Done is refused
item("a", 19, state="your-step", step=STEP, then="home-keeper", mover="Oliver")            # then = a session that is neither the owner nor in needs (review F1)
item("a", 20, state="your-step", step=STEP, owner="")                         # no owner, no session in needs: the keeper (F3)
item("a", 21, state="your-step", step=STEP, needs=["decision", "home-agent"], ask=ASK,
     options=[{"label": "Done", "line": "A stale option that parks", "recommended": True, "wake": "2099-01-01"}, {"label": "Wait", "line": "x", "recommended": False}])   # F4: a stale option named Done with a wake
item("a", 22, state="your-step", step=STEP, needs=["decision", "home-agent"], hold=True, wake="2099-01-01", hold_set={"by": "t", "at": now})     # F4: a hold, its wake and decision in needs
item("a", 23, state="your-step", step=STEP, needs=["home-agent"], due="2027-06-01", hold=True, wake="2027-05-01", hold_set={"by": "t", "at": now},
     cap_ok={"due": "2027-06-01", "due_by": "Oliver", "wake": "2027-05-01", "by": "Oliver", "quote": "park it", "source": "board"})      # G1: the owner's words behind a far due date
item("a", 24, state="your-step", step=STEP, needs=["home-agent"], wait_kind="time", post_wake_mover="home-agent", wake="2027-05-01")           # N1: a leftover wait
item("a", 25, state="your-step", step=STEP, owner="")                         # nobody to take it
item("a", 26, needs=["decision"], ask=YESNO)                                  # an open question: no options, so no Approve or Decline
item("a", 27, needs=["decision"], ask=YESNO)                                  # the same, answered through its one Send
item("a", 28, needs=["decision"], ask=YESNO, options=[{"label": "Approve", "line": "Go ahead", "recommended": False}, {"label": "Decline", "line": "No", "recommended": False}])   # misshaped stored options (no recommended one): no options at all
item("a", 18, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")     # stored model fields too
item("a", 29, needs=["home-agent"])                                          # no decision: a stale tab's Send as an answer is a comment
item("a", 30, needs=["decision", "home-agent"], ask=YESNO)                   # no options, Yes with a note
item("a", 31, needs=["decision"], ask=YESNO)                               # no options, No
item("a", 32, needs=["decision"], ask=YESNO)                               # Yes after the item has gained options (stale)
item("a", 33, needs=["decision"], ask=YESNO)                               # Yes after the decision has left the item (stale)
item("a", 40, state="your-step", step=STEP, needs=["home-agent"])                # an old page's single Send (act=send) with an empty box = Done
item("a", 41, state="your-step", step=STEP, needs=["home-agent"])                # an old page's single Send with a note = his note on the step, handed to the then-mover to judge
item("a", 45, state="your-step", step=STEP, needs=["home-agent"])                # Send with a note that names a later time: the item waits until then
item("a", 47, state="your-step", step=STEP, needs=["home-agent"])                # Send with a note the server reads as a later time: it holds the item itself
item("a", 46, state="your-step", step=STEP, needs=["home-agent"])                # a later-time note whose time is past the wait cap
item("a", 42)                                                              # Send on an item that has no step any more
item("a", 141, state="your-step", step=STEP, needs=["home-agent"])               # the Send note button: a note on the step, handed to the then-mover
item("a", 142, state="your-step", step=STEP, needs=["home-agent"])               # the Send note button with an empty box: refused, the step stands
item("a", 143)                                                             # the Send note button on an item that has no step any more: a comment
item("a", 43, state="your-step", step=STEP, owner="")                         # Send with a note, nobody to take it
item("a", 50, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent")              # the decision hand-over: a decision with a stored mover and then (no options: Yes / No)
item("a", 51, needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", then="home-keeper")   # the decision hand-over: then = a session that is neither the owner nor in needs; an option picked
item("a", 52, needs=["decision", "home-agent"], ask=YESNO, mover="Oliver")                  # the decision hand-over: a stored mover and no then: the first session in needs takes it
item("a", 53, needs=["decision"], ask=YESNO)                                              # the decision hand-over: nothing stored: today's behaviour, the owner takes it
item("a", 54, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent")             # the decision hand-over: a comment only: nothing moves
item("a", 55, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent")             # the decision hand-over: answered from the home page's row (back=/)
item("a", 56, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent")             # the decision hand-over: answered from the item page's own form
item("a", 57, needs=["decision"], ask=YESNO, mover="Oliver", then="Oliver")               # the decision hand-over: a then that names him is no then
item("a", 58, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent", hold=True, wake="2099-01-01", hold_set={"by": "t", "at": now})   # the hand-over, F1: still on hold with a wake after the answer
item("a", 59, needs=["decision", "external"], ask=YESNO, mover="Oliver", then="home-agent", party="the vendor", chase="2099-01-01")           # the hand-over, F1: external stays in needs
item("a", 90, needs=["home-agent"], next="home-agent: confirm the runs are gone")                  # a session sets the your-step and names the mover in one update, then his note
item("a", 91, needs=["home-agent"], next="home-agent: confirm the runs are gone")                  # the same, with its own Oliver line in next saying the step
item("a", 62)                                                                                                                            # the hand-over: a prerequisite that is open now and closed in the test
item("a", 60, needs=["decision"], ask=YESNO, mover="Oliver", then="home-agent", after=["a62"])                                               # the hand-over, F1: an open after link
item("a", 67)                                                                                                                              # the prerequisite of, closed in the test
item("a", 63, needs=["decision"], ask=ASK, mover="Oliver", then="home-agent", after=["a67"],
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # a park on an item that also waits after an open item
item("a", 64, needs=["decision", "external"], ask=ASK, mover="Oliver", then="home-agent", party="the vendor", chase="2099-01-01",
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # a park on an item that also waits on external
item("a", 65, needs=["decision"], ask=ASK, mover="Oliver", then="home-agent",
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # a park, then clear_hold
item("a", 66, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, then="home-agent")                                            # an old hold whose wake has come, with a then stored: the wake pass hands it
item("a", 68, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, mover="Oliver", then="home-agent")                             # the board item's shape: parked, mover Oliver stored, a then, no needs; its wake is due
item("a", 70)                                                                                                                              # the prerequisite of, closed in the test
item("a", 69, after=["a70"], mover="Oliver", then="home-agent")                                                                              # the same through an after release
item("a", 71, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, mover="home-keeper", then="home-agent")                           # an agent mover with an agent then: the then must not take it
item("a", 72, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, mover="Oliver", then="some free text, not a session")       # a then that is no session
item("a", 73, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, then="home-agent", needs=["home-keeper"])                         # an agent in needs: the then must not take it
item("a", 74, mover="home-agent")                                                                                                            # the whole chain: the agent asks, the write stores the Oliver mover (his state makes him the mover), his answer hands it back
item("a", 61, needs=["decision"], ask=ASK, mover="Oliver", then="home-agent",
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # the hand-over, F2: a pick that carries a wake, with a then
item("a", 80, needs=["decision"], ask=YESNO, mover="Oliver", then="home-ghost")                  # D1: a then that is no live session, answered Yes
item("a", 81, needs=["decision"], ask=ASK, mover="Oliver", then="home-ghost",
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # D1: the same, a park
item("a", 83)                                                                                  # D2: the prerequisite of, closed in the test
item("a", 82, needs=["decision", "home-agent"], ask=YESNO, mover="Oliver", then="home-agent", after=["a83"])      # D2: then is already named in needs; an open after link
item("a", 84, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": now}, mover="home-agent", then="home-agent")   # D2: a then that already is the mover, hold due
item("a", 85, needs=["decision"], ask=ASK, mover="Oliver", then="home-agent",
     options=[{"label": "Park", "line": "Park it until the date", "recommended": True, "wake": "2099-01-01"}, {"label": "Go", "line": "Go on now", "recommended": False}])   # D3: a park with a then, watchers off
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
def snap(msg): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(L, i): return json.loads((T / f"store/{L}/{i}.json").read_text())
STORE = T / "store"

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.github import ghsync as G
from stackshot.service import answer_handover as handover_svc
from stackshot.service import update as _update_svc
from stackshot.web import answers as _web_answers
from stackshot.waits import watchers as _watch
from stackshot.core import instance as _core_instance
from stackshot.model import model as _model
from stackshot.core import config as _cfg
from stackshot.service import store as _service_store
from stackshot.model import states as _states
from stackshot.model import owner_steps as _hs
import datetime as dt
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.web.routes import answers as _rt_answers
from stackshot.web.auth import signin as _signin
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def jobs(): return [json.loads(p.read_text()) for p in G.pending()]
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))

check("the fixture: the mirror is on (the queue is read, never drained), the owner is Oliver", G.enabled() and _core_instance.OWNER == "Oliver")

# ---- 1. the form, as the renderer draws it
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
B = ui_render.Board(str(STORE))
p1, p2, p3, p4 = (B.item_html(g, answer={**BOX, "action": f"/items/{g}/answer"}) for g in ("a1", "a2", "a3", "a4"))
form1 = re.search(r'<form class="ianswer".*?</form>', p1, re.S)
btns1 = re.findall(r'<input type="radio" name="choice" value="([^"]*)">', p1)
check("options: one card per option, three or more in the stored order and lettered, the recommended one marked recommended",
      btns1 == ["A · Wait", "B · Ship", "C · Drop"] and '<span class="alab"><span class="akey">B</span>Ship</span> <span class="badge rec">recommended</span>' in p1 and p1.count('class="badge rec"') == 1, btns1)
check("the form posts to the item's answer address with the token, under the Ask block",
      form1 is not None and 'method="post" action="/items/a1/answer"' in form1.group(0) and '<input type="hidden" name="token" value="TOKEN">' in form1.group(0)
      and p1.index('<div class="iask">') < p1.index('<form class="ianswer"') < p1.index("<h2>Next</h2>"), form1 and form1.group(0)[:300])
_m1 = p1[p1.find('<div class="imain">'):]
check("the item page's layout (GitHub's issue layout): the title, then the sidebar, then the main column with "
      "state line, Ask, the answer box, Next, Background and History in that order; the form is in the main column, not the sidebar",
      0 < p1.index("</h1>") < p1.index('<aside class="iside"') < p1.index("</aside>") < p1.index('<div class="imain">')
      and 0 <= _m1.find('<div class="istat">') < _m1.find('<div class="iask">') < _m1.find('<form class="ianswer"') < _m1.find("<h2>Next</h2>")
      < _m1.find("<h2>Background</h2>") < _m1.find("<h2>History") and "<dt>Then</dt>" in p1[p1.index('<aside class="iside"'):p1.index("</aside>")],
      p1[p1.find("</h1>"):][:600])
check("the note box and its one Send: an answer while the item needs his decision",
      '<textarea id="atext" name="text"' in p1 and '<button type="submit" class="b main" name="act" value="answer">Send</button>' in p1
      and 'value="comment"' not in p1 and "Send as" not in p1 and p1.count('name="act"') == 1)
check("a yes/no ask whose stored options are Approve and Decline gets exactly those, the recommended one first and marked",
      re.findall(r'name="choice" value="([^"]*)"', p2) == ["Approve", "Decline"] and '<span class="alab">Approve</span> <span class="badge rec">recommended</span>' in p2, re.findall(r'name="choice" value="([^"]*)"', p2))
p26, p28 = (B.item_html(g, answer={**BOX, "action": f"/items/{g}/answer"}) for g in ("a26", "a28"))
check("an ask with no options gets no Approve or Decline, only Yes and No; misshaped stored options draw no button at all",
      "Approve" not in p26 and "Decline" not in p26 and 'name="choice"' not in p28 and "Approve" not in p28 and "Yes" not in p28, re.findall(r'name="choice" value="([^"]*)"', p26))
check("an ask with no options gets Yes and No as choices, Yes first and marked recommended, No plain",
      re.findall(r'name="choice" value="([^"]*)"', p26) == ["Yes", "No"] and '<span class="alab">Yes</span> <span class="badge rec">recommended</span>' in p26
      and '<span class="alab">No</span><span class="adesc">' in p26 and p26.index('value="Yes"') < p26.index('value="No"'), re.findall(r'<label class="acard">.*?</label>', p26))
check("Yes and No are drawn only on an open decision with no options: not with options (the owner's own, or Approve and Decline), nor on a non-decision item, nor on a closed one",
      all('value="Yes"' not in x and 'value="No"' not in x for x in (p1, p2, p3, p4)) and re.findall(r'name="choice" value="([^"]*)"', p2) == ["Approve", "Decline"], [re.findall(r'name="choice" value="([^"]*)"', x) for x in (p1, p2, p3, p4)])
check("beside Yes and No the box keeps its one Send (act=answer), with the note worded as optional; no Done, no comment button",
      '<form class="ianswer"' in p26 and '<textarea id="atext" name="text"' in p26 and re.findall(r'<button type="submit"[^>]*name="act" value="([^"]*)">([^<]*)</button>', p26) == [("answer", "Send")]
      and "Note (optional)" in p26 and "Done" not in re.sub(r"(?s)<script.*?</script>", "", p26), re.findall(r'<button [^>]*>([^<]*)</button>', p26))      # the page's text, not its scripts: every page head carries the script-word table (js.sent_done reads "Done: ... takes it from here")
check("the wording: the agent on it is told (the comment box and the notices), never its owner",
      "Write a comment; the agent on it is told" in p3 and "its owner is told" not in p3 + p26 + p1 + p2
      and "and the agent on it has been told." in ui_render.Board._SENT["decision"][1] and "and the agent on it has been told." in ui_render.Board._SENT["comment"][1]
      and all("owner" not in v[1] for v in ui_render.Board._SENT.values()), ui_render.Board._SENT)
check("an item that needs no decision gets the comment box only", '<form class="ianswer"' in p3 and 'name="choice"' not in p3 and '<button type="submit" class="b main" name="act" value="comment">Send</button>' in p3 and 'value="answer"' not in p3 and "Send as" not in p3
      and "Write a comment; the agent on it is told" in p3 and "<b>Add a comment</b>" in p3 and "Your answer" not in p3 and "Your answer" in p1)
check("a completed item gets no form; a page drawn without the server's box (not signed in) neither",
      '<form class="ianswer"' not in p4 and '<form class="ianswer"' not in B.item_html("a1"))
check("the form needs no script and fits a phone: the box is full width, the buttons wrap",
      "<script" not in form1.group(0) and ".ianswer textarea{display:block;box-sizing:border-box;width:100%" in p1 and ".abtns{display:flex;flex-wrap:wrap" in p1)
check("the answer is sent by script: a same-origin fetch of the form's fields and the pressed button, url-encoded, then location.replace "
      "with the item page it landed on (the pre-answer page is replaced in history); the buttons are disabled meanwhile, a refusal shows inline",
      ui_render._ANSWER_JS in p1 and p1.index("</form>") < p1.index(ui_render._ANSWER_JS)
      and all(x in ui_render._ANSWER_JS for x in ("document.querySelector('form.ianswer')", "ev.preventDefault()", "if(s&&s.name)d.append(s.name,s.value)",
                                              "fetch(F.action,{method:'POST',body:new URLSearchParams(d),credentials:'same-origin',redirect:'follow'})",
                                              "location.replace(u.href)", "b.disabled=!on", "E.hidden=false"))
      and '<p class="isent warn aerr" role="alert" hidden></p></form>' in p1)
check("the no-script fallback: the form is still a plain POST to the answer address with named submit buttons, and a browser "
      "without SubmitEvent.submitter keeps it (the script returns before preventDefault)",
      'method="post" action="/items/a1/answer"' in form1.group(0) and form1.group(0).count('type="submit"') == 1 and form1.group(0).count('type="radio" name="choice"') == 3
      and ui_render._ANSWER_JS.index("if(s===undefined)return;") < ui_render._ANSWER_JS.index("ev.preventDefault()"))
check("pages restored from the back-forward cache reload: the item page (with or without the form) and the project page; "
      "the answer script only where there is a form",
      ui_render._BFCACHE_JS in p1 and ui_render._BFCACHE_JS in p4 and ui_render._BFCACHE_JS in B.item_html("a1") and ui_render._BFCACHE_JS in B.routing_html("projects/alpha")
      and "if(e.persisted)location.reload()" in ui_render._BFCACHE_JS and ui_render._ANSWER_JS not in p4 and ui_render._ANSWER_JS not in B.item_html("a1"))

# ---- 2. the routes: who may post, with what
from starlette.testclient import TestClient
COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
OTHER = _signin._ui_sign(json.dumps({"email": "someone@example.org", "exp": time.time() + 3600}))
tok = lambda g: _web_answers._answer_token(EMAIL, g)
SAME = {"Origin": BOARD}
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def post(path, data, headers=SAME, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    def page(path, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path)
    g0, g1 = page("/items/a1", cookie=None), page("/items/a1")
    check("GET: not signed in, the page has no form; signed in, it carries the form with this item's token for this person",
          g0.status_code == 200 and '<form class="ianswer"' not in g0.text and g1.status_code == 200
          and f'<input type="hidden" name="token" value="{tok("a1")}">' in g1.text and 'action="/items/a1/answer"' in g1.text, (g0.status_code, g1.status_code))
    before = rd("a", 1)
    r_anon = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship"}, cookie=None)
    r_other = post("/items/a1/answer", {"token": _web_answers._answer_token("someone@example.org", "a1"), "choice": "Ship"}, cookie=OTHER)
    r_notok = post("/items/a1/answer", {"choice": "Ship"})
    r_wrong = post("/items/a1/answer", {"token": tok("a2"), "choice": "Ship"})
    r_evil = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship"}, headers={"Origin": "https://evil.example.net"})
    r_null = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship"}, headers={"Origin": "null"})
    r_eref = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship"}, headers={"Referer": "https://evil.example.net/items/a1"})
    r_none = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship"}, headers={})
    r_a = post("/items/a99/answer", {"token": tok("a99"), "choice": "Ship"})
    check("refused 403: not signed in, an address not allowed on the board, no token, another item's token, another origin, Origin null, a foreign Referer, neither header",
          [r.status_code for r in (r_anon, r_other, r_notok, r_wrong, r_evil, r_null, r_eref, r_none)] == [403] * 8,
          [r.status_code for r in (r_anon, r_other, r_notok, r_wrong, r_evil, r_null, r_eref, r_none)])
    check("an unknown item is 404", r_a.status_code == 404, r_a.status_code)
    check("a refused POST wrote nothing, queued nothing, told nobody", rd("a", 1) == before and not jobs() and not told, (jobs(), told))
    check("item pages are served Cache-Control: no-store, signed in or not", g1.headers.get("cache-control") == "no-store" and g0.headers.get("cache-control") == "no-store",
          (g0.headers.get("cache-control"), g1.headers.get("cache-control")))
    # the home page's answer forms (part 1): the board is a static page without a token, so its script asks GET /answer-tokens for the signed-in viewer's
    t_ok = page("/answer-tokens?ids=a1,a2,a99,a1,%23x,,zz9")
    t_anon = page("/answer-tokens?ids=a1,a2", cookie=None)
    t_other = page("/answer-tokens?ids=a1", cookie=OTHER)
    check("GET /answer-tokens: signed in, one token per stored item asked for — the item page's own token for this person — and none for an unknown or malformed id, none twice",
          t_ok.status_code == 200 and t_ok.json() == {"a1": tok("a1"), "a2": tok("a2")}, (t_ok.status_code, t_ok.text[:300]))
    check("GET /answer-tokens: the token is the one the answer route takes (the item page's form carries the same value)", t_ok.json()["a1"] in g1.text)
    check("GET /answer-tokens: with the server's own sign-in off (this scenario's STACKSHOT_AUTH=off), not signed in gets 200 and no token", t_anon.status_code == 200 and t_anon.json() == {}, (t_anon.status_code, t_anon.text[:200]))
    t_forged = page("/answer-tokens?ids=a1", cookie="forged.cookie")
    check("GET /answer-tokens: a forged cookie is nobody: 200 and no token", t_forged.status_code == 200 and t_forged.json() == {} and tok("a1") not in t_forged.text, (t_forged.status_code, t_forged.text[:200]))
    _am, _uo = _signin._auth_mode, _cfg.CFG["auth"]["ui_open"]
    try:
        _signin._auth_mode = lambda: "oauth"          # the server's own sign-in on, [auth] ui_open = false as this scenario's config has it
        def raw(cookie):
            c.cookies.clear()
            if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
            return c.get("/answer-tokens?ids=a1", follow_redirects=False)
        r_no, r_bad, r_ok = raw(None), raw("forged.cookie"), raw(COOKIE)
        _cfg.CFG["auth"]["ui_open"] = True
        r_open = raw(None)
    finally:
        _signin._auth_mode = _am; _cfg.CFG["auth"]["ui_open"] = _uo
    check("GET /answer-tokens: ui_open = false and no cookie is a redirect to the sign-in, with no token in it", r_no.status_code == 302 and r_no.headers["location"].startswith("/ui/login?next=") and tok("a1") not in r_no.text + r_no.headers["location"], (r_no.status_code, r_no.headers.get("location")))
    check("GET /answer-tokens: ui_open = false and a forged cookie is the same redirect", r_bad.status_code == 302 and r_bad.headers["location"].startswith("/ui/login?next=") and tok("a1") not in r_bad.text, (r_bad.status_code, r_bad.headers.get("location")))
    check("GET /answer-tokens: ui_open = false and a good cookie still gets the token; ui_open = true and no cookie gets {} (the edge decides who reaches the board, nobody has a token)",
          r_ok.json() == {"a1": tok("a1")} and r_open.status_code == 200 and r_open.json() == {}, (r_ok.text[:120], r_open.status_code, r_open.text[:120]))
    check("GET /answer-tokens: nosniff on the answer", t_ok.headers.get("x-content-type-options") == "nosniff", dict(t_ok.headers))
    check("GET /answer-tokens: another person's token is another token, and is never the first person's", t_other.status_code != 200 or t_other.json().get("a1") != tok("a1"), (t_other.status_code, t_other.text[:200]))
    check("GET /answer-tokens: never cached", t_ok.headers.get("cache-control") == "no-store", t_ok.headers.get("cache-control"))
    check("GET /answer-tokens: at most 200 ids are read", len(page("/answer-tokens?ids=" + ",".join(["a1"] * 300 + ["a2"])).json()) == 1)
    # the board item: the home page's form
    # carries `back`, the page it is on; the server goes back there with the notice and the item named, and only to a same-origin path of a known page
    b_ = lambda back, **kw: post("/items/a5/answer", {"token": tok("a5"), "text": " ", "act": "comment", **({"back": back} if back is not None else {}), **kw})
    r_home = b_("/#task-a-5"); r_home2 = b_("/")
    check("home answer: back = / goes to / with the code and the item's id, the row's anchor after the query; nothing written for an empty box",
          r_home.status_code == 303 and r_home.headers["location"] == "/?sent=empty&item=a5#task-a-5"
          and r_home2.headers["location"] == "/?sent=empty&item=a5" and r_home.headers.get("cache-control") == "no-store"
          and rd("a", 5)["metadata"].get("ask") == YESNO, (r_home.headers.get("location"), r_home2.headers.get("location")))
    r_proj = b_("/projects/alpha"); r_item = b_("/items/a1")
    check("home answer: a project page and an item page are known pages too", r_proj.headers["location"] == "/projects/alpha?sent=empty&item=a5" and r_item.headers["location"] == "/items/a1?sent=empty&item=a5",
          (r_proj.headers["location"], r_item.headers["location"]))
    EVIL = ["//evil.com", "//evil.com/x", "https://evil.com", "http://evil.com/", "/\\evil.com", "\\\\evil.com", "%2F%2Fevil.com", "/%2Fevil.com", "/\r\nSet-Cookie: x=1", "/items/a1\r\nX-Evil: 1", "/\nevil",
            "javascript:alert(1)", "evil.com", "", "/foo", "/projects/../../etc/passwd", "/projects/alpha/../..", "/items/a1?x=1", "/#bad frag", "/#a#b", "/ /", "/projects/", "/items/", "/index.html/x", "/\u2215evil.com", "///evil.com"]
    bad = {e: b_(e).headers.get("location") for e in EVIL}
    check("home answer: an open-redirect attempt falls back to the item's page (//evil.com, a scheme, /\\evil.com, %2F%2Fevil.com, CR/LF, a path out of the pages, a query, a bad anchor)",
          all(v == "/items/a5?sent=empty" for v in bad.values()), {e: v for e, v in bad.items() if v != "/items/a5?sent=empty"})
    from urllib.parse import urlsplit, parse_qs
    r_sp = post("/items/a12/answer", {"token": tok("a12"), "text": " ", "act": "comment", "back": "/#task-a-12"})
    _u = urlsplit(r_sp.headers["location"])
    check("home answer: the Location's query parses back to exactly sent and item, nothing from the item's subject (&x=1#frag, %, CR/LF, an astral character, a forged &sent=) in it",
          r_sp.status_code == 303 and _u.path == "/" and parse_qs(_u.query, keep_blank_values=True) == {"sent": ["empty"], "item": ["a12"]} and _u.fragment == "task-a-12"
          and r_sp.headers["location"] == "/?sent=empty&item=a12#task-a-12" and not any(x in r_sp.headers["location"] for x in ("spoof", "%", "\r", "\n", "Cookie", "x=1")), r_sp.headers["location"])
    check("home answer: the item page's own form (no back) behaves as before: 303 to its own page, ?sent only", b_(None).headers["location"] == "/items/a5?sent=empty", b_(None).headers["location"])
    check("home answer: _answer_back keeps (path, anchor) for a known page and None for the rest", _rt_answers._answer_back("/#task-a-5") == ("/", "#task-a-5") and _rt_answers._answer_back("/projects/alpha/sub") == ("/projects/alpha/sub", "")
          and _rt_answers._answer_back("/index.html") == ("/index.html", "") and _rt_answers._answer_back(None) is None and _rt_answers._answer_back("//x") is None)
    c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE)
    rf = c.post("/items/a5/answer", content="token=" + tok("a5") + "&text=+&act=comment", headers={**SAME, "Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=True)
    check("a POST as the page's fetch sends it (url-encoded, following the redirect) lands on the item's page with its notice, 303 then no-store; nothing written for an empty box",
          rf.status_code == 200 and str(rf.url) == f"{BOARD}/items/a5?sent=empty" and [h.status_code for h in rf.history] == [303]
          and rf.history[0].headers.get("cache-control") == "no-store" and rf.headers.get("cache-control") == "no-store"
          and "Nothing sent: write something in the box" in rf.text and "answers" not in rd("a", 5)["metadata"] and not told,
          (rf.status_code, str(rf.url), [h.status_code for h in rf.history]))

    # ---- 3. an option's button: his answer
    t0 = time.time()
    r = post("/items/a1/answer", {"token": tok("a1"), "choice": "Ship", "text": ""})
    a1 = rd("a", 1); m1 = a1["metadata"]
    check("an option: 303 back to the item's page with the notice", r.status_code == 303 and r.headers["location"] == "/items/a1?sent=decision", (r.status_code, r.headers.get("location")))
    check("decision left needs and the session named stayed; the ask and the options are cleared (he picked one of them)",
          m1.get("needs") == ["home-agent"] and "ask" not in m1 and "options" not in m1, m1)
    ans = m1.get("answers") or []
    check("the answer is stored: {ts, kind: decision, choice, via: board}, no text when none was written",
          len(ans) == 1 and ans[0]["kind"] == "decision" and ans[0]["choice"] == "Ship" and ans[0]["via"] == "board" and "text" not in ans[0] and ans[0]["ts"] >= t0, ans)
    check("the answer keeps the chosen option's label and line, so the record survives the clear",
          ans[0].get("choice") == "Ship" and ans[0].get("choice_line") == "Ship it now as it is", ans)
    check("the answer also keeps every option he was shown (label, line, recommended), so the History can list them whole after the clear",
          ans[0].get("options") == OPTS, ans[0].get("options"))
    check("the state clock moved (and the confirm with it)", a1["state_updated"] >= t0 and a1["confirmed"] >= t0 and a1["updated"] >= t0, a1)
    line = f"[stackshot] Oliver answered a1 on the board: Ship → {BOARD}/items/a1"
    check("delivered, one line, to the item's mover (the session named in needs; the creator is not told), through the owner-notice path",
          sorted((t[1], t[2], t[3]) for t in told if t[0] == "a1") == [(AGENT, line, "answer")], told)
    j = jobs()
    check("the mirror: his answer is a change nothing of the issue carries (subject, open or closed, description): no job, no comment", j == [], j)
    pg = page("/items/a1?sent=decision")
    check("the page after: the sent notice, no option buttons any more (decision is in), the comment box still there",
          '<p class="isent ok" role="status">Sent: your answer is on the item, it has left your queue, and the agent on it has been told.</p>' in pg.text
          and 'name="choice"' not in pg.text and '<button type="submit" class="b main" name="act" value="comment">Send</button>' in pg.text, re.findall(r'<p class="isent.*?</p>', pg.text))
    check("…and no stale options, ask or recommended badge anywhere on the page; his answer shows in History",
          'class="iopts"' not in pg.text and 'class="iask"' not in pg.text and 'badge rec' not in pg.text and "Oliver (board): <b>Ship</b>" in pg.text,
          re.findall(r'<li class="ev ev-answer">.*?</li>', pg.text))
    told.clear()
    r = post("/items/a1/answer", {"token": tok("a1"), "choice": "Wait"})
    check("a choice once decision has left needs is stale: nothing written, nobody told",
          r.headers["location"] == "/items/a1?sent=stale" and len(rd("a", 1)["metadata"]["answers"]) == 1 and not told, (r.headers.get("location"), told))
    for p in G.pending(): p.unlink()

    # ---- 4. a comment changes neither needs nor the ask; the Referer stands in for a missing Origin
    told.clear(); before5 = rd("a", 5)
    r = post("/items/a5/answer", {"token": tok("a5"), "text": "What about the\nother box?", "act": "comment"}, headers={"Referer": f"{BOARD}/items/a5"})
    a5 = rd("a", 5)
    check("a comment (same-origin Referer, no Origin): 303 with its notice; needs and the ask unchanged, the state clock not moved",
          r.status_code == 303 and r.headers["location"] == "/items/a5?sent=comment" and a5["metadata"]["needs"] == ["decision"] and a5["metadata"]["ask"] == YESNO
          and a5["state_updated"] == before5["state_updated"], (r.status_code, r.headers.get("location"), a5["metadata"]))
    check("the comment is stored with kind comment and its text", [(a["kind"], a["text"], a["via"]) for a in a5["metadata"]["answers"]] == [("comment", "What about the\nother box?", "board")],
          a5["metadata"].get("answers"))
    check("the owner hears it, one line, the text's break flattened", [(t[1], t[2]) for t in told] == [(OWNER, f"[stackshot] Oliver commented on a5 on the board: What about the / other box? → {BOARD}/items/a5")], told)
    check("his comment queues no GitHub job either", jobs() == [], jobs())
    for p in G.pending(): p.unlink()
    told.clear()
    before29 = rd("a", 29)
    r = post("/items/a29/answer", {"token": tok("a29"), "text": "stale tab words", "act": "answer"})
    a29 = rd("a", 29)
    check("a stale tab's Send as an answer on an item that needs no decision is stored as a comment: nothing he wrote is lost, no decision recorded, needs and the clock untouched",
          r.status_code == 303 and r.headers["location"] == "/items/a29?sent=comment" and [(a["kind"], a["text"]) for a in a29["metadata"]["answers"]] == [("comment", "stale tab words")]
          and a29["metadata"]["needs"] == ["home-agent"] and a29["state_updated"] == before29["state_updated"], (r.headers.get("location"), a29["metadata"]))
    for p in G.pending(): p.unlink()
    told.clear()
    r_e = post("/items/a5/answer", {"token": tok("a5"), "text": "   ", "act": "answer"})
    r_l = post("/items/a5/answer", {"token": tok("a5"), "text": "x" * 4001, "act": "comment"})
    r_c0 = post("/items/a4/answer", {"token": tok("a4"), "text": "  ", "act": "comment"})
    check("nothing sent for an empty box, a text over 4000 characters, or a closed item with nothing written: each says why, nothing written",
          [x.headers.get("location") for x in (r_e, r_l, r_c0)] == ["/items/a5?sent=empty", "/items/a5?sent=toolong", "/items/a4?sent=closed"]
          and len(rd("a", 5)["metadata"]["answers"]) == 1 and "answers" not in rd("a", 4)["metadata"] and not told and not jobs(),
          [x.headers.get("location") for x in (r_e, r_l, r_c0)])
    r_c = post("/items/a4/answer", {"token": tok("a4"), "text": "late", "act": "comment"})
    a4 = rd("a", 4)
    check("a note on a closed item is kept: it goes onto the item as his comment, the item stays closed, and the page says it was kept",
          r_c.headers.get("location") == "/items/a4?sent=closednote" and a4["status"] == "completed"
          and [(a["kind"], a["text"], a["via"]) for a in a4["metadata"]["answers"]] == [("comment", "late", "board")]
          and "your note is on it" in ui_render.Board._SENT["closednote"][1], (r_c.headers.get("location"), a4["metadata"].get("answers")))
    told.clear()
    r_c2 = post("/items/a4/answer", {"token": tok("a4"), "text": "late", "act": "comment"})
    check("a second send of the same note on the closed item is a no-op: one comment, nobody told again", r_c2.headers.get("location") == "/items/a4?sent=closednote" and len(rd("a", 4)["metadata"]["answers"]) == 1 and not told, rd("a", 4)["metadata"]["answers"])
    server._answer("a4", "Yes", "a pick on it", "")
    check("a pick sent with a note on a closed item is kept with the pick named in front",
          [a["text"] for a in rd("a", 4)["metadata"]["answers"]][-1] == "(the item is closed: Yes) a pick on it" and len(rd("a", 4)["metadata"]["answers"]) == 2, rd("a", 4)["metadata"]["answers"])
    told.clear()
    d4 = rd("a", 4); d4["metadata"]["answers"] = [{"ts": "not a number", "kind": "comment", "text": "hand-edited"}, {"ts": None, "kind": "comment", "text": "no stamp"}]; (T / "store/a/4.json").write_text(json.dumps(d4))
    check("a record with a ts that is not a number is read as old: the note is kept, not an error", server._answer("a4", "", "after the hand edit", "comment") == "closednote" and [a["text"] for a in rd("a", 4)["metadata"]["answers"]][-1] == "after the hand edit"
          and len(rd("a", 4)["metadata"]["answers"]) == 3, rd("a", 4)["metadata"]["answers"])
    told.clear()
    a4_again = rd("a", 4)
    del a4_again["metadata"]["answers"]; (T / "store/a/4.json").write_text(json.dumps(a4_again))      # back to the fixture: later checks read item a4 as it was

    # ---- 5. Approve on a yes/no ask; "Send as my answer" with text; a front-agent owner
    r = post("/items/a2/answer", {"token": tok("a2"), "choice": "Approve", "text": "go, but tell Pat first"})
    m2 = rd("a", 2)["metadata"]
    check("Approve with a note: decision and the ask are gone (no needs key left), the choice and the text stored",
          "needs" not in m2 and "ask" not in m2 and [(a["choice"], a["text"]) for a in m2["answers"]] == [("Approve", "go, but tell Pat first")], m2)
    check("…delivered as 'Approve — go, but tell Pat first'", any(t[1] == OWNER and t[2] == f"[stackshot] Oliver answered a2 on the board: Approve — go, but tell Pat first → {BOARD}/items/a2" for t in told), told)
    check("…and no issue comment is queued for it", not any("comment" in x for x in jobs()), jobs()[-1:])

    # ---- 5b. no stored options, no Approve or Decline: a forged choice is refused; the open question's one Send is his answer
    told.clear(); b26, b28, njobs0 = rd("a", 26), rd("a", 28), len(jobs())
    r_f1 = post("/items/a26/answer", {"token": tok("a26"), "choice": "Approve"})
    r_f2 = post("/items/a26/answer", {"token": tok("a26"), "choice": "Decline", "text": "no"})
    r_f3 = post("/items/a28/answer", {"token": tok("a28"), "choice": "Approve"})
    r_f4 = post("/items/a26/answer", {"token": tok("a26"), "choice": "Done"})
    k26 = [(a["kind"], a["text"]) for a in rd("a", 26)["metadata"].get("answers", [])]; told_f = list(told); told.clear()
    d26 = rd("a", 26); d26["metadata"].pop("answers"); d26["updated"] = b26["updated"]
    check("a forged choice=Approve / Decline on an ask with no stored options (or misshaped ones) is refused: sent=stale, no decision written, nobody told; the one with a note keeps the note as his comment",
          [x.headers.get("location") for x in (r_f1, r_f2, r_f3, r_f4)] == ["/items/a26?sent=stale", "/items/a26?sent=stalenote", "/items/a28?sent=stale", "/items/a26?sent=stale"]
          and k26 == [("comment", "(late, the item no longer asks this: Decline) no")] and rd("a", 28) == b28 and len(told_f) == 1 and len(jobs()) == njobs0
          and all(d26["metadata"].get(k) == b26["metadata"].get(k) for k in ("needs", "ask", "options")), (k26, told_f, rd("a", 28) == b28, len(jobs()), njobs0))
    (T / "store/a/26.json").write_text(json.dumps(b26))      # back to the fixture
    check("…and the same through the server's own entry", server._answer("a26", "Approve", "", "") == "stale" and server._answer("a26", "Decline", "", "answer") == "stale" and rd("a", 26) == b26)
    r_q = post("/items/a27/answer", {"token": tok("a27"), "act": "answer", "text": "Go, with the smaller scope."})
    m27 = rd("a", 27)["metadata"]
    check("an open question's Send is his answer: kind decision with his text and no choice, the decision and the ask leave the item, the owner is told",
          r_q.headers["location"] == "/items/a27?sent=decision" and "needs" not in m27 and "ask" not in m27
          and [(a["kind"], a.get("choice"), a["text"]) for a in m27["answers"]] == [("decision", None, "Go, with the smaller scope.")]
          and any(t[1] == OWNER and "answered a27 on the board: Go, with the smaller scope." in t[2] for t in told), (r_q.headers.get("location"), m27, told))
    told.clear()
    # ---- 5c. Yes and No on a decision with no stored options, answered like an option's button
    told.clear(); njobs1 = len(jobs())
    r_y = post("/items/a30/answer", {"token": tok("a30"), "choice": "Yes", "text": "but keep it small"})
    m30 = rd("a", 30)["metadata"]
    check("Yes with a note on a no-option decision is his decision: sent=decision, the decision and the ask leave the item (the session in needs stays), choice and text stored via the board",
          r_y.headers["location"] == "/items/a30?sent=decision" and m30.get("needs") == ["home-agent"] and "ask" not in m30
          and [(a["kind"], a.get("choice"), a.get("text"), a.get("via")) for a in m30["answers"]] == [("decision", "Yes", "but keep it small", "board")], (r_y.headers.get("location"), m30))
    line30 = f"[stackshot] Oliver answered a30 on the board: Yes — but keep it small → {BOARD}/items/a30"
    check("...delivered as 'Yes - but keep it small' to the mover (the session in needs) alone, and no issue comment is queued",
          sorted((t[1], t[2]) for t in told if t[0] == "a30") == [(AGENT, line30)]
          and not any("comment" in x for x in jobs()), (told, jobs()[-1:]))
    told.clear()
    r_n = post("/items/a31/answer", {"token": tok("a31"), "choice": "No"})
    m31 = rd("a", 31)["metadata"]
    check("No alone is recorded the same way (choice No, no text), the decision leaves the item",
          r_n.headers["location"] == "/items/a31?sent=decision" and "needs" not in m31 and "ask" not in m31 and [(a["kind"], a.get("choice"), a.get("text")) for a in m31["answers"]] == [("decision", "No", None)]
          and any(t[1] == OWNER and "answered a31 on the board: No" in t[2] for t in told), (r_n.headers.get("location"), m31, told))
    told.clear()
    d32 = rd("a", 32); d32["metadata"]["options"] = YN; (T / "store/a/32.json").write_text(json.dumps(d32))
    d33 = rd("a", 33); d33["metadata"].pop("needs"); d33["metadata"].pop("ask"); (T / "store/a/33.json").write_text(json.dumps(d33))
    b32, b33, njobs2 = rd("a", 32), rd("a", 33), len(jobs())
    r_s1 = post("/items/a32/answer", {"token": tok("a32"), "choice": "Yes"})
    r_s2 = post("/items/a33/answer", {"token": tok("a33"), "choice": "No"})
    r_s3 = post("/items/a3/answer", {"token": tok("a3"), "choice": "Yes"})
    check("Yes read after the item gained options, or after it left the decision, is stale: nothing written, nobody told",
          [x.headers.get("location") for x in (r_s1, r_s2, r_s3)] == ["/items/a32?sent=stale", "/items/a33?sent=stale", "/items/a3?sent=stale"]
          and rd("a", 32) == b32 and rd("a", 33) == b33 and not told and len(jobs()) == njobs2, [x.headers.get("location") for x in (r_s1, r_s2, r_s3)])
    check("...and through the server's own entry: Yes is no choice of an item with options (even its own Approve and Decline), and a closed item is closed",
          server._answer("a32", "Yes", "", "") == "stale" and server._answer("a6", "No", "", "") == "stale" and server._answer("a4", "Yes", "", "") == "closed" and rd("a", 32) == b32)
    st_a = _web_answers._answers_load()
    check("a Yes / No answer is tracked for the escalation like any decision (then dropped here, so the later escalation checks count the earlier answers only)", "a30" in st_a and "a31" in st_a, st_a)
    _web_answers._answers_save({g: e for g, e in st_a.items() if g not in ("a30", "a31")}); told.clear()
    told.clear()
    r = post("/items/a7/answer", {"token": tok("a7"), "text": "Neither: do the smaller fix first.", "act": "answer"})
    m7 = rd("a", 7)["metadata"]
    check("Send as my answer: recorded as his decision with his text, decision and the ask cleared",
          r.headers["location"] == "/items/a7?sent=decision" and "needs" not in m7 and "ask" not in m7
          and [(a["kind"], a.get("choice"), a["text"]) for a in m7["answers"]] == [("decision", None, "Neither: do the smaller fix first.")], m7)
    _fs = telling.front_keeper
    telling.front_keeper = lambda who, project="": (True, "home-keeper")
    try:
        told.clear(); post("/items/a6/answer", {"token": tok("a6"), "choice": "Decline"})
    finally:
        telling.front_keeper = _fs
    check("a front-agent owner's line carries [for Oliver] on its first line", [(t[1], t[2]) for t in told] == [(OWNER, f"[for Oliver] [stackshot] Oliver answered a6 on the board: Decline → {BOARD}/items/a6")], told)

    # ---- 6. an old id's address answers the item it names now
    mp = G.load_map(STORE); mp["aliases"]["s9"] = "a3"; G.save_map(mp, STORE)
    told.clear()
    r = post("/items/s9/answer", {"token": tok("a3"), "text": "noted", "act": "comment"})
    check("POST /items/<old id>/answer resolves as the GET route does: recorded on the item, 303 to its page",
          r.status_code == 303 and r.headers["location"] == "/items/a3?sent=comment" and [a["text"] for a in rd("a", 3)["metadata"]["answers"]] == ["noted"], (r.status_code, r.headers.get("location")))

    # ---- 6b. the step item's buttons: Done moves the item to its then-mover with his words as his; any item without a step refuses it; the gates are the same
    told.clear(); before17 = rd("a", 17); before3 = rd("a", 3); njobs = len(jobs())
    r_nd = post("/items/a17/answer", {"token": tok("a17"), "act": "done", "text": "done!"})
    r_np = post("/items/a3/answer", {"token": tok("a3"), "act": "done", "text": "done!"})
    check("Done on an item that is not a step item is refused: 303 with sent=nostep, nothing written, nobody told (a decision item and a plain item alike)",
          r_nd.headers["location"] == "/items/a17?sent=nostep" and r_np.headers["location"] == "/items/a3?sent=nostep" and rd("a", 17) == before17 and rd("a", 3) == before3 and not told and len(jobs()) == njobs,
          (r_nd.headers.get("location"), r_np.headers.get("location")))
    r_ng = post("/items/a13/answer", {"token": tok("a13"), "act": "done", "text": "x" * 4001})
    check("a note over 4000 characters with Done is refused as for any answer: nothing written, the step still stands", r_ng.headers["location"] == "/items/a13?sent=toolong" and "answers" not in rd("a", 13)["metadata"] and rd("a", 13)["metadata"]["state"] == "your-step")
    told.clear()
    r_d = post("/items/a13/answer", {"token": tok("a13"), "act": "done", "text": "ran it, it said ok", "back": "/#task-a-13"})
    m13 = rd("a", 13)["metadata"]; d13 = _model.derive(rd("a", 13))
    check("Done with a note: 303 back to the page it came from with sent=donenote (the note went along), the item and who takes it (the then-mover's name), the row's anchor after",
          r_d.status_code == 303 and r_d.headers["location"] == "/?sent=donenote&item=a13&then=home-agent#task-a-13", r_d.headers.get("location"))
    check("Done: the step and its state are gone, the item moves to its then-mover (home-agent), Oliver is no longer in needs or the mover",
          "state" not in m13 and "step" not in m13 and m13.get("mover") == "home-agent" and not _model.is_owner(d13.mover) and d13.mover == "home-agent" and "decision" not in [x.lower() for x in m13.get("needs", [])]
          and rd("a", 13)["status"] == "open", m13)
    check("Done: his words are recorded as his (kind decision, choice Done, his note, via board, the step he did), once",
          [(a["kind"], a["choice"], a["text"], a["via"], a["step"]) for a in m13["answers"]] == [("decision", "Done", "ran it, it said ok", "board", STEP.replace('\"', '"'))], m13["answers"])
    _STEPN = STEP.replace('\\"', '"')
    check("Done: the then-mover (home-agent, in needs) alone is told, in a line headed as his answer, 'Oliver did his step on <id>: <step>. It's yours now, with his note: “<note>”' (review F5;: the creator is not told)",
      sorted((t[1], t[3]) for t in told) == [(AGENT, "answer")]
      and {t[1]: t[2] for t in told}[AGENT] == f"[stackshot] Oliver did his step on a13: {_STEPN}. It's yours now, with his note: “ran it, it said ok” → {BOARD}/items/a13", told)
    check("Done: the answer is tracked for the escalation like any decision, and no issue comment is queued for it", "a13" in _web_answers._answers_load() and not any("comment" in x for x in jobs()), jobs()[-1:])
    r_again = post("/items/a13/answer", {"token": tok("a13"), "act": "done", "text": "again"})
    check("Done twice: the second finds no step any more, nothing more written", r_again.headers["location"] == "/items/a13?sent=nostep" and len(rd("a", 13)["metadata"]["answers"]) == 1)
    told.clear(); r_d14 = post("/items/a14/answer", {"token": tok("a14"), "act": "done", "text": "", "back": "/"})
    m14 = rd("a", 14)["metadata"]
    check("Done with no note and no session in needs: the item goes to the project's keeper (never its creator), the answer is a bare Done, the redirect names the keeper",
          r_d14.headers["location"] == "/?sent=done&item=a14&then=home-keeper" and m14.get("mover") == "home-keeper" and "state" not in m14 and [(a["choice"], a.get("text")) for a in m14["answers"]] == [("Done", None)], (r_d14.headers.get("location"), m14))
    r_d18 = post("/items/a18/answer", {"token": tok("a18"), "act": "done", "text": "ok"}); m18 = rd("a", 18)["metadata"]
    check("Done on an item that stores mover and then too: they are replaced, the item reads as the then-mover's", m18.get("mover") == "home-agent" and "then" not in m18 and "state" not in m18 and _model.derive(rd("a", 18)).mover == "home-agent", m18)
    # F1: a then-mover that is neither the owner nor in needs is told, and its write settles the pending answer (the keeper is not told "its owner has not written")
    told.clear(); r_19 = post("/items/a19/answer", {"token": tok("a19"), "act": "done", "text": "go on"}); m19 = rd("a", 19)["metadata"]
    check("Done with then = home-keeper (not in needs): the item moves to home-keeper, who alone is told, once", m19.get("mover") == "home-keeper" and sorted(t[1] for t in told) == [STEW]
          and any(t[1] == STEW and "It's yours now, with his note: “go on”" in t[2] for t in told), (m19, told))
    check("…the answer is pending for the then-mover, and its write settles it", sorted(_web_answers._answers_load().get("a19", {}).get("told", [])) == [STEW], _web_answers._answers_load().get("a19"))
    check("Done on a step item (mover Oliver, then home-keeper, no needs): needs names the then-mover, and the notice goes to it, not the page's keeper",
          m19.get("needs") == [STEW] and telling.notice_to(m19) == [(STEW, "as a session named in its needs")]
          and _model.derive(rd("a", 19)).mover == "home-keeper", (m19, telling.notice_to(m19)))
    _update_svc._update("a19", next="home-keeper: on it", sender="home-keeper")
    check("…so no pending answer is left for a19, and the keeper is not told after 30 min that its owner has not written", "a19" not in _web_answers._answers_load(), _web_answers._answers_load())
    # F3: no owner and no session in needs: the project's keeper takes it at once, as mover, and is told
    told.clear(); _kp = telling.project_keeper; telling.project_keeper = lambda project, owner="": "home-keeper"
    try: r_20 = post("/items/a20/answer", {"token": tok("a20"), "act": "done", "text": ""}); m20 = rd("a", 20)["metadata"]
    finally: telling.project_keeper = _kp
    check("Done on an ownerless step item with no session in needs: the project's keeper is the mover at once and is told (and only it)", m20.get("mover") == "home-keeper" and "state" not in m20
          and [(t[1], t[3]) for t in told] == [(STEW, "answer")] and "It's yours now" in told[0][2] and r_20.status_code == 303, (m20, told))
    # F4: a stale option named Done is no pick; a hold, its wake and decision in needs go with his step
    told.clear(); post("/items/a21/answer", {"token": tok("a21"), "act": "done", "text": ""}); m21 = rd("a", 21)["metadata"]
    check("Done never reads a stale option named Done as his pick: nothing parked, no hold or wake, no 'on hold' in the line, decision gone from needs, the item with the then-mover",
          not any("parked" in a for a in m21["answers"]) and "hold" not in m21 and "wake" not in m21 and m21["needs"] == [AGENT] and m21.get("mover") == "home-agent"
          and not any("on hold" in t[2] for t in told) and "choice_line" not in m21["answers"][-1], (m21, told))
    post("/items/a22/answer", {"token": tok("a22"), "act": "done", "text": ""}); m22 = rd("a", 22)["metadata"]
    check("Done drops a hold and its wake, and decision and the old one-word kind from needs (the session stays)", "hold" not in m22 and "wake" not in m22 and "hold_set" not in m22 and m22["needs"] == [AGENT] and m22.get("mover") == "home-agent", m22)
    check("Done with a choice in the form is an ordinary answer, not a step (a stale option, act=done)", server._answer("a17", "Approve", "", "done") == "decision" and "Done" not in [a.get("choice") for a in rd("a", 17)["metadata"]["answers"]], rd("a", 17)["metadata"])
    # G1: Done keeps the owner's words behind a far due date (as the watcher's arrival does) and drops those behind the wake
    from stackshot.waits import waiting as _waiting
    check("fixture: the due date's cap is lifted by the owner's words", _waiting.cap_words(rd("a", 23)["metadata"], "due"))
    post("/items/a23/answer", {"token": tok("a23"), "act": "done", "text": ""}); m23 = rd("a", 23)["metadata"]
    check("Done keeps cap_ok's due words (the cap stays lifted for the due date, so the item does not resurface early) and drops the wake, the hold and the wake's words",
          _waiting.cap_words(m23, "due") and m23["cap_ok"] == {"due": "2027-06-01", "due_by": "Oliver"} and "wake" not in m23 and "hold" not in m23 and m23["due"] == "2027-06-01", m23)
    # N1: Done ends a wait the way the watcher does (watchers.LIVE_DROP): a leftover wait_kind does not hold the item
    check("fixture: a leftover wait reads as a wait", _model.derive(rd("a", 24)).state == "waiting", _model.derive(rd("a", 24)))
    post("/items/a24/answer", {"token": tok("a24"), "act": "done", "text": ""}); m24 = rd("a", 24)["metadata"]
    check("Done on a step item with a leftover wait_kind: the wait fields are gone and the item derives as alive, the then-mover's", _model.derive(rd("a", 24)).state == "alive" and _model.derive(rd("a", 24)).mover == "home-agent"
          and not any(k in m24 for k in ("wait_kind", "post_wake_mover", "wake")), m24)
    # no owner, no session in needs and no keeper: refused, nothing written
    told.clear(); before25 = rd("a", 25); _kp = telling.project_keeper; telling.project_keeper = lambda project, owner="": ""
    try: r_25 = post("/items/a25/answer", {"token": tok("a25"), "act": "done", "text": "x", "back": "/#task-a-25"}); r_25b = post("/items/a25/answer", {"token": tok("a25"), "act": "done", "text": "x"})
    finally: telling.project_keeper = _kp
    check("Done with nobody to take the item is refused with sent=nomover: nothing written, nobody told, the step still stands",
          r_25.headers["location"] == "/?sent=nomover&item=a25#task-a-25" and r_25b.headers["location"] == "/items/a25?sent=nomover" and rd("a", 25) == before25 and not told, (r_25.headers.get("location"), r_25b.headers.get("location")))
    check("the nomover notice says why and what to do instead", "Nobody is set to take this item next, so nothing was recorded. Write a comment instead." in ui_render.Board(str(STORE)).sent_html({"sent": "nomover"}))
    # the gates are the answer route's own: the token is the item's, the sign-in and the origin are checked before anything
    g_anon = post("/items/a16/answer", {"token": tok("a16"), "act": "done"}, cookie=None)
    g_tok = post("/items/a16/answer", {"token": tok("a15"), "act": "done"})
    g_evil = post("/items/a16/answer", {"token": tok("a16"), "act": "done"}, headers={"Origin": "https://evil.example.net"})
    g_none = post("/items/a16/answer", {"act": "done"})
    check("Done passes the same gates as an answer: signed out, another item's token, a foreign origin and no token all refused; the item is untouched",
          g_anon.status_code in (302, 303, 401, 403) and "sent=" not in g_anon.headers.get("location", "") and g_tok.status_code == 403 and g_evil.status_code == 403 and g_none.status_code == 403
          and rd("a", 16)["metadata"]["state"] == "your-step" and "answers" not in rd("a", 16)["metadata"], [x.status_code for x in (g_anon, g_tok, g_evil, g_none)])
    # a note on its own (Send) on a step item: a comment, the step stays
    told.clear(); r_c15 = post("/items/a15/answer", {"token": tok("a15"), "act": "comment", "text": "which box do I run it on?", "back": "/#task-a-15"})
    m15 = rd("a", 15)["metadata"]
    check("Send on a step item: a comment; the step, its state and the mover stay, nothing moves",
          r_c15.headers["location"] == "/?sent=comment&item=a15#task-a-15" and m15["state"] == "your-step" and m15["step"] == STEP.replace('\"', '"') and [(a["kind"], a["text"]) for a in m15["answers"]] == [("comment", "which box do I run it on?")]
          and _model.is_owner(_model.derive(rd("a", 15)).mover), m15)
    # ---- an old page's single Send (act=send, a page loaded before the two buttons): an empty box finishes the step, a note is his note on it
    told.clear(); r_s40 = post("/items/a40/answer", {"token": tok("a40"), "act": "send", "text": "  ", "back": "/#task-a-40"}); m40 = rd("a", 40)["metadata"]
    check("an old page's Send with an empty box is a Done: sent=done with who takes it, the step and state gone, the item with the then-mover, recorded as his answer Done (kind decision, no text)",
          r_s40.headers["location"] == "/?sent=done&item=a40&then=home-agent#task-a-40" and "state" not in m40 and "step" not in m40 and m40.get("mover") == "home-agent"
          and [(a["kind"], a["choice"], a.get("text"), a["via"]) for a in m40["answers"]] == [("decision", "Done", None, "board")], (r_s40.headers.get("location"), m40))
    check("an old page's Send with an empty box tells the then-mover with the Done line (no instruction to judge anything)",
          {t[1]: t[2] for t in told}[AGENT] == f"[stackshot] Oliver did his step on a40: {_STEPN}. It's yours now → {BOARD}/items/a40", told)
    told.clear(); r_s41 = post("/items/a41/answer", {"token": tok("a41"), "act": "send", "text": "which box do I run it on?", "back": "/#task-a-41"}); m41 = rd("a", 41)["metadata"]
    check("an old page's Send with a note: sent=stepreply with who takes it; the step and its state are gone and the item is with the then-mover (home-agent), as after a Done",
          r_s41.headers["location"] == "/?sent=stepreply&item=a41&then=home-agent#task-a-41" and "state" not in m41 and "step" not in m41 and m41.get("mover") == "home-agent"
          and not _model.is_owner(_model.derive(rd("a", 41)).mover) and rd("a", 41)["status"] == "open", (r_s41.headers.get("location"), m41))
    check("an old page's Send with a note: recorded as his note on the step (kind step-reply, his words, via board, the step he did), not as a Done",
          [(a["kind"], a.get("choice"), a["text"], a["via"], a["step"]) for a in m41["answers"]] == [("step-reply", None, "which box do I run it on?", "board", _STEPN)], m41["answers"])
    _tz, _minreason = _cfg.tz_abbr(), _cfg.WAIT_GUARD_REASON_MIN
    _judge_old = ". Judge the note: if it finishes the step, carry on as after a Done; if it is a question or a request, answer it or do it, then hand the item back to Oliver with a new step (step=…)"
    _judge_later = (f"; if it says he will do the step at a later time, put the item on hold until then (update hold=true, until=<that time, YYYY-MM-DDTHH:MM {_tz}>, "
                    f"wait_reason=<what it waits on, at least {_minreason} characters>), leave his step open and hand no new step back.")
    _judge = _judge_old + _judge_later
    check("an old page's Send with a note: the then-mover alone is told, with his note and the instruction to judge it (the creator is not told)",
          sorted((t[1], t[3]) for t in told) == [(AGENT, "answer")]
          and {t[1]: t[2] for t in told}[AGENT] == f"[stackshot] Oliver sent a note on his step on a41: {_STEPN}. It's yours now with his note: “which box do I run it on?”{_judge} → {BOARD}/items/a41", told)
    check("an old page's Send with a note: tracked for the escalation, and no issue comment is queued for it",
          "a41" in _web_answers._answers_load() and not any("comment" in x for x in jobs()), jobs()[-1:])
    check("History and `get` show the note as his note on the step, never as Done",
          "note on his step" in ui_render.Board(str(STORE)).item_html("a41") and "<b>Done</b>" not in ui_render.Board(str(STORE)).item_html("a41")
          and "note on his step: which box do I run it on?" in _wt_get.stackshot_get("a41"), None)
    # a note that names a later time the server does not read (no date or day part in it): the notice carries the third branch, and the tools it names put the item on hold with a wake
    told.clear(); r_s45 = post("/items/a45/answer", {"token": tok("a45"), "act": "send", "text": "I will do this after the trip, so wait until then", "back": "/#task-a-45"}); m45 = rd("a", 45)["metadata"]
    n45 = {t[1]: t[2] for t in told}[AGENT]
    check("a later-time note: the then-mover alone is told, and its notice keeps both earlier branches word for word and adds the wait branch after them",
          sorted(t[1] for t in told) == [AGENT] and _judge_old + "; if it says he will do the step at a later time" in n45 and n45.endswith(_judge_later + f" → {BOARD}/items/a45")
          and "if it finishes the step, carry on as after a Done" in n45 and "then hand the item back to Oliver with a new step (step=…)" in n45, n45)
    check("the wait branch names the exact tool form: hold=true, a wake as YYYY-MM-DDTHH:MM in the instance zone, a wait_reason with its minimum length, his step left open, no new step handed back",
          "update hold=true" in n45 and f"until=<that time, YYYY-MM-DDTHH:MM {_tz}>" in n45 and f"wait_reason=<what it waits on, at least {_minreason} characters>" in n45
          and "leave his step open and hand no new step back" in n45 and _minreason >= 15, n45)
    check("the server does not read a time out of a note that names none: the item is with the then-mover, not on hold, no wake (the instruction is the notice's text, carried out by the mover's update)",
          r_s45.headers["location"] == "/?sent=stepreply&item=a45&then=home-agent#task-a-45" and m45.get("mover") == "home-agent" and "hold" not in m45 and "wake" not in m45
          and [a["kind"] for a in m45["answers"]] == ["step-reply"], m45)
    _when = (dt.datetime.now(_wt_text.ZONE) + dt.timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    r_u45 = _wt_update.stackshot_update("a45", hold=True, wake=_when, wait_reason="Oliver said he will do the step tomorrow evening", sender="home-agent")
    i45 = rd("a", 45); m45 = i45["metadata"]
    check("following the notice (update hold=true, wake, wait_reason) is accepted: the item is on hold with that wake, the same mover, and no step handed back to him",
          r_u45.startswith("updated a45") and hd_(m45) is True and wk_(m45) == _when and m45.get("mover") == "home-agent" and "step" not in m45 and m45.get("state") != "your-step"
          and _model.derive(i45).state == "waiting" and not _model.is_owner(_model.derive(i45).mover), (r_u45, m45))
    check("the wake stands on his note: it is recorded as the words behind the hold (cap_ok quote)", "after the trip" in str((m45.get("cap_ok") or {}).get("quote")), m45.get("cap_ok"))
    # a note the server reads ("tomorrow evening"): it puts the item on hold itself, with his words behind the wake, and the notice says so instead of asking the mover to judge
    told.clear(); r_s47 = post("/items/a47/answer", {"token": tok("a47"), "act": "send", "text": "I will do this tomorrow evening", "back": "/#task-a-47"}); m47 = rd("a", 47)["metadata"]; n47 = {t[1]: t[2] for t in told}[AGENT]
    check("a note the server reads as a later time: the item is on hold until then (the wake as YYYY-MM-DDTHH:MM, his words behind it), with the then-mover, and the notice says what was done, not to judge the note",
          hd_(m47) is True and wk_(m47) == _when and (m47.get("cap_ok") or {}).get("quote") == "I will do this tomorrow evening" and m47.get("mover") == "home-agent"
          and "put the item on hold until" in n47 and "Judge the note" not in n47 and [a["kind"] for a in m47["answers"]] == ["step-reply"], (m47, n47))
    # a wake past the cap: his note, given since the item's last move, is the words that let it stand
    told.clear(); post("/items/a46/answer", {"token": tok("a46"), "act": "send", "text": "after the trip, next month", "back": "/#task-a-46"})
    _far = (dt.datetime.now(_wt_text.ZONE) + dt.timedelta(days=_WT.cap_days() + 12)).replace(hour=9, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    r_u46 = _wt_update.stackshot_update("a46", hold=True, wake=_far, wait_reason="Oliver said he will do the step after the trip", sender="home-agent")
    i46 = rd("a", 46); m46 = i46["metadata"]
    check("a note that names a time beyond the usual wait cap: the same update is accepted on his note's words, and the item waits until then",
          r_u46.startswith("updated a46") and hd_(m46) is True and wk_(m46) == _far and "after the trip" in str((m46.get("cap_ok") or {}).get("quote")) and _model.derive(i46).state == "waiting", (r_u46[:300], m46))
    r_s41b = post("/items/a41/answer", {"token": tok("a41"), "act": "send", "text": "again"})
    check("an old page's Send with a note twice: the second finds no step any more, so it is a comment (the board item's rule), the first note stays", r_s41b.headers["location"] == "/items/a41?sent=comment" and [a["kind"] for a in rd("a", 41)["metadata"]["answers"]] == ["step-reply", "comment"])
    r_s42 = post("/items/a42/answer", {"token": tok("a42"), "act": "send", "text": ""}); r_s42c = post("/items/a42/answer", {"token": tok("a42"), "act": "send", "text": "late note"})
    check("an old page's Send on an item with no step: an empty box is refused (nostep), a note is a comment", r_s42.headers["location"] == "/items/a42?sent=nostep" and r_s42c.headers["location"] == "/items/a42?sent=comment"
          and [a["kind"] for a in rd("a", 42)["metadata"]["answers"]] == ["comment"])
    told.clear(); _kp43 = telling.project_keeper; telling.project_keeper = lambda project, owner="": ""
    try: r_s43 = post("/items/a43/answer", {"token": tok("a43"), "act": "send", "text": "a note"}); r_s43b = post("/items/a43/answer", {"token": tok("a43"), "act": "send", "text": ""})
    finally: telling.project_keeper = _kp43
    check("an old page's Send with nobody to take the item (note or empty box): sent=nomover, nothing written, nobody told, the step stands",
          r_s43.headers["location"] == "/items/a43?sent=nomover" and r_s43b.headers["location"] == "/items/a43?sent=nomover" and "answers" not in rd("a", 43)["metadata"] and rd("a", 43)["metadata"]["state"] == "your-step" and not told, told)
    # the Send note button (act=note): a note on the step, never a Done; an empty box is refused; with no step left it is a comment
    told.clear(); r_n141 = post("/items/a141/answer", {"token": tok("a141"), "act": "note", "text": "which box do I run it on?", "back": "/#task-a-141"}); m141 = rd("a", 141)["metadata"]
    check("Send note: sent=stepreply with who takes it; recorded as his note on the step (kind step-reply, his words, via board, the step), not as a Done, and the item goes to the then-mover",
          r_n141.headers["location"] == "/?sent=stepreply&item=a141&then=home-agent#task-a-141" and m141.get("mover") == "home-agent" and "state" not in m141
          and [(a["kind"], a.get("choice"), a["text"], a["via"], a["step"]) for a in m141["answers"]] == [("step-reply", None, "which box do I run it on?", "board", _STEPN)], (r_n141.headers.get("location"), m141))
    check("Send note: the then-mover alone is told, with his note and the instruction to judge it, exactly as for an old page's Send with a note",
          sorted((t[1], t[3]) for t in told) == [(AGENT, "answer")]
          and {t[1]: t[2] for t in told}[AGENT] == f"[stackshot] Oliver sent a note on his step on a141: {_STEPN}. It's yours now with his note: “which box do I run it on?”{_judge} → {BOARD}/items/a141", told)
    told.clear(); r_n142 = post("/items/a142/answer", {"token": tok("a142"), "act": "note", "text": "   ", "back": "/#task-a-142"}); m142 = rd("a", 142)["metadata"]
    check("Send note with an empty box is no Done and no note: sent=emptynote (a note is needed, not an option), nothing written, nobody told, the step stands",
          r_n142.headers["location"] == "/?sent=emptynote&item=a142#task-a-142" and "answers" not in m142 and m142.get("state") == "your-step" and m142.get("step") and not told, (r_n142.headers.get("location"), m142, told))
    r_n143 = post("/items/a143/answer", {"token": tok("a143"), "act": "note", "text": "late note"})
    check("Send note on an item with no step: a comment, as the Send of an old page", r_n143.headers["location"] == "/items/a143?sent=comment" and [a["kind"] for a in rd("a", 143)["metadata"]["answers"]] == ["comment"], r_n143.headers.get("location"))
    told.clear(); r_d142 = post("/items/a142/answer", {"token": tok("a142"), "act": "done", "text": "ran it, ok", "back": "/#task-a-142"}); m142 = rd("a", 142)["metadata"]
    check("Done with a note after a note was refused: sent=donenote, the step is ticked (state and step gone, item with the then-mover), the answer is a Done carrying the note, and the then-mover is told the step is done and shown it",
          r_d142.headers["location"] == "/?sent=donenote&item=a142&then=home-agent#task-a-142" and "state" not in m142 and "step" not in m142 and m142.get("mover") == "home-agent"
          and [(a["kind"], a["choice"], a["text"]) for a in m142["answers"]] == [("decision", "Done", "ran it, ok")]
          and {t[1]: t[2] for t in told}[AGENT] == f"[stackshot] Oliver did his step on a142: {_STEPN}. It's yours now, with his note: “ran it, ok” → {BOARD}/items/a142", (r_d142.headers.get("location"), m142, told))
    r_s44 = post("/items/a41/answer", {"token": tok("a41"), "act": "send", "text": "x" * 4001})
    check("a step note over 4000 characters is refused as any answer", r_s44.headers["location"] == "/items/a41?sent=toolong")
    check("an old page's act=done still works (the Done checks above); its act=comment on a step form stays a comment and the step stands (the Send of a page loaded before the release)",
          server._answer("a15", "", "still a comment", "comment") == "comment" and rd("a", 15)["metadata"]["state"] == "your-step")
    # the page and the home row draw their forms, and the notices say who takes it
    pg = page("/items/a16").text; pg_done = page("/items/a13?sent=done").text
    check("the item page of a step item draws the step, the optional note box and TWO buttons: Done (the main one, act=done) and Send note (act=note, needs text), no comment button, with the token",
          'class="iask istep"' in pg and 'name="act" value="done">Done</button>' in pg and 'data-needs-text>Send note</button>' in pg and 'name="act" value="note" title="Write a note to send it" data-hint="Write a note to send it" data-needs-text' in pg and pg.count('name="act"') == 2
          and 'class="b main" name="act" value="done"' in pg and 'value="send"' not in pg and 'value="comment"' not in pg and 'placeholder="Note (optional)"' in pg
          and "Note for the next mover (optional)" in pg and "Send with an empty box finishes the step" not in pg and "A note, or nothing to finish the step" not in pg and 'name="token"' in pg and 'name="choice"' not in pg, pg[pg.find("Your step") - 200:][:600] if "Your step" in pg else pg[:300])
    check("after Done the item page's notice names who takes it: Done: home-agent takes it from here.", "Done: home-agent takes it from here." in pg_done, re.findall(r'class="isent[^>]*>.*?</p>', pg_done))
    pg_dn = page("/items/a13?sent=donenote").text; pg_en = page("/items/a13?sent=emptynote").text
    check("after Done with a note the item page's notice says the note went along and names who takes it; after Send note on a blank box it says a note is needed, not that an option is to be picked",
          "Done: home-agent takes it from here, and your note went along." in pg_dn and "Nothing sent: write a note to send it." in pg_en and "pick an option" not in pg_en, (re.findall(r'class="isent[^>]*>.*?</p>', pg_dn), re.findall(r'class="isent[^>]*>.*?</p>', pg_en)))
    b_ = ui_render.Board(str(STORE))
    check("after a note on the step the item page's notice names who has it", "Sent: home-agent has your note and decides whether the step is done." in page("/items/a41?sent=stepreply").text
          and "Sent: home-agent has your note" in ui_render.Board(str(STORE)).sent_html({"sent": "stepreply"}, "home-agent") and "hands the item back to you if it was a question" in ui_render.Board(str(STORE)).sent_html({"sent": "stepreply"}))
    check("sent_html: Done with a name says who takes it, without one it says the item goes on; nostep warns", "Done: home-agent takes it from here." in b_.sent_html({"sent": "done"}, "home-agent") and "goes on to its next mover" in b_.sent_html({"sent": "done"}) and "no step for you any more" in b_.sent_html({"sent": "nostep"})
          and "went along" not in b_.sent_html({"sent": "done"}, "home-agent") and "your note went along" in b_.sent_html({"sent": "donenote"}) and "Done: home-agent takes it from here, and your note went along." in b_.sent_html({"sent": "donenote"}, "home-agent"))
    # ---- 6c. the decision hand-over: a decision answered on an item that stores mover Oliver and a then hands the item to the then-mover (seen twice, the item stayed his with and needs read as the keeper). Home page row (back=/) and item page take the one path.
    r55 = post("/items/a55/answer", {"token": tok("a55"), "choice": "Yes", "back": "/#task-a-55"}); r56 = post("/items/a56/answer", {"token": tok("a56"), "choice": "Yes"})
    m55, m56 = rd("a", 55)["metadata"], rd("a", 56)["metadata"]
    check("a decision on the home page's row and on the item page's own form: the same result (mover and needs the then-mover, then gone), each back to its own page",
          r55.headers["location"] == "/?sent=decision&item=a55#task-a-55" and r56.headers["location"] == "/items/a56?sent=decision"
          and {k: m55.get(k) for k in ("mover", "needs", "then")} == {k: m56.get(k) for k in ("mover", "needs", "then")} == {"mover": "home-agent", "needs": [AGENT], "then": None}, (m55, m56))
    st_ = _web_answers._answers_load()
    for g in ("a55", "a56"): st_.pop(g, None)
    _web_answers._answers_save(st_)
    told.clear()

    st_ = _web_answers._answers_load()
    for g in ("a13", "a14", "a18", "a19", "a20", "a21", "a22", "a23", "a24", "a25", "a17", "a27", "a40", "a41", "a42", "a45", "a46", "a47", "a141", "a142", "a143"): st_.pop(g, None)
    _web_answers._answers_save(st_)
    for p in G.pending(): p.unlink()
    told.clear()

snap("answers")
# ---- 7. History: one line per answer
h1, h5, h2 = ui_render.Board(str(STORE)).item_html("a1"), ui_render.Board(str(STORE)).item_html("a5"), ui_render.Board(str(STORE)).item_html("a2")
check("History: the answer is one entry per revision — its author and time on the header, a bullet each for what the answer changed (whose move, the ask and the options leaving, each with its line), then Oliver (board): <choice>",
      re.search(r'<li class="ev ev-answer"><div class="eh"><b>Oliver</b> · <span class="t">[^<]+</span></div><div class="w"><div class="eb">moved to <b>On agent</b></div><div class="eb">the ask was: whether to ship<details class="ehold"><summary class="more">the whole ask</summary><div class="body md">.*?</div></details></div>'
                r'<div class="eb">the options were:</div><div class="eb osub"><b>Wait</b>: Wait for the next release</div><div class="eb osub"><b>Ship</b> \(recommended\): Ship it now as it is · <b>picked</b></div><div class="eb osub"><b>Drop</b>: Drop the feature</div><div class="eb">mover: [^<]+ → <b>[^<]+</b></div><div class="eb">ask cleared</div><div class="eb">options cleared</div><div class="eb">Oliver \(board\): <b>Ship</b></div></div></li>', h1, re.S) is not None,
      re.findall(r'<li class="ev ev-answer">.*?</li>', h1))
check("History: a comment's line is marked comment; a choice with a note shows both",
      "Oliver (board): What about the\nother box? <span class=\"dim\">· comment</span>" in h5 and "Oliver (board): <b>Approve</b> — go, but tell Pat first" in h2,
      (re.findall(r'<li class="ev ev-answer">.*?</li>', h5, re.S), re.findall(r'<li class="ev ev-answer">.*?</li>', h2)))
check("get shows his answers to the session reading the item, with the chosen option's line, and no options or ask any more",
      "Oliver's answers on the board:\n- " in _wt_get.stackshot_get("a1") and "answer: Ship [chosen option: Ship: Ship it now as it is]" in _wt_get.stackshot_get("a1")
      and "options:" not in _wt_get.stackshot_get("a1") and "ask:" not in _wt_get.stackshot_get("a1"), _wt_get.stackshot_get("a1"))

# ---- 8. the escalation: 30 min without a write by a session it was sent to → the keeper, once
st = _web_answers._answers_load()
check("pending: a1, a2, a6 and a7 (decisions), not the comments", sorted(st) == ["a1", "a2", "a6", "a7"] and st["a1"]["told"] == [AGENT], st)
told.clear()
check("before 30 min nothing goes", server._answer_tick(time.time() + 600) == [] and not told, told)
_update_svc._update("a1", next="home-agent: shipping it", dropped=[1], sender="home-agent")             # the session named in needs acts
_update_svc._update("a2", next="home-here: telling Pat", dropped=[1], sender="home-here")               # the owner acts
check("a write by a session the answer went to settles it (the owner's, or one named in needs)", sorted(_web_answers._answers_load()) == ["a6", "a7"], _web_answers._answers_load())
_update_svc._update("a7", next="home-keeper: someone else wrote", dropped=[1], sender="home-keeper")    # the keeper is not who was told: item 7 stays pending
told.clear()
out = server._answer_tick(time.time() + 1801)
stew = [t for t in told if t[1] == STEW]
check("after 30 min the keeper of the project is told, once per answer, and nobody else",
      sorted(out) == ["a6", "a7"] and len(stew) == 2 and len(told) == 2 and all(t[3] == "answer" for t in told), (out, told))
s7 = next(t[2] for t in stew if t[0] == "a7")
check("…in one line: what he answered, that its mover has not written, and the link",
      s7.startswith("[stackshot] Oliver answered a7 on the board at ") and "its mover home-here has not written to the item in 30 min: Neither: do the smaller fix first." in s7
      and "As the keeper of projects/alpha" in s7 and s7.endswith(f"→ {BOARD}/items/a7"), s7)
told.clear()
check("a second pass tells nobody again", server._answer_tick(time.time() + 7200) == [] and not told and _web_answers._answers_load() == {}, told)

# ---- 9. no session writes as Oliver
for nm in ("Oliver", "oliver", " OLIVER ", "Oliver · board"):
    refused(f"update refuses sender={nm!r}", lambda: _wt_update.stackshot_update("a3", next="x", sender=nm), "sender names Oliver")
refused("complete refuses sender='Oliver'", lambda: _wt_complete.stackshot_complete("a3", outcome="done", reason="r", description="Done.", sender="Oliver"), "sender names Oliver")
refused("confirm refuses sender='Oliver'", lambda: _wt_complete.stackshot_confirm("a3", sender="Oliver"), "sender names Oliver")
check("a session's own name still writes", _wt_update.stackshot_update("a3", next="home-here: y", dropped=[1], sender="home-here").startswith("updated a3"))

# ---- 10. a pick among the options clears ask and options; anything else leaves them as it did
for g in ("a8", "a9", "a10", "a11"): assert rd("a", int(g[1:]))["metadata"]["options"] == OPTS
check("free text (no choice): the decision is in and the ask is cleared as before, the options are untouched, no option line recorded",
      server._answer("a8", "", "Neither, do the smaller fix", "answer") == "decision" and "ask" not in rd("a", 8)["metadata"] and rd("a", 8)["metadata"].get("options") == OPTS
      and "choice_line" not in rd("a", 8)["metadata"]["answers"][0] and "choice" not in rd("a", 8)["metadata"]["answers"][0], rd("a", 8)["metadata"])
check("an option picked with a note: ask and options cleared, the answer keeps choice, line and text; the session named stays in needs",
      server._answer("a9", "Wait", "after the holiday", "") == "decision" and "ask" not in rd("a", 9)["metadata"] and "options" not in rd("a", 9)["metadata"]
      and rd("a", 9)["metadata"]["needs"] == ["home-agent"]
      and [(a["choice"], a["choice_line"], a["text"]) for a in rd("a", 9)["metadata"]["answers"]] == [("Wait", "Wait for the next release", "after the holiday")], rd("a", 9)["metadata"])
b9 = ui_render.Board(str(STORE)).item_html("a9", answer={**BOX, "action": "/items/a9/answer"})
check("…the cleared item draws no options, no ask and no option buttons, and History keeps his answer and says what was cleared",
      'class="iopts"' not in b9 and 'class="iask"' not in b9 and 'name="choice"' not in b9 and "Oliver (board): <b>Wait</b> — after the holiday" in b9 and "options cleared" in b9 and "ask cleared" in b9,
      re.findall(r'<li class="ev ev-[a-z]+">.*?</li>', b9))
check("a choice that matches no option is stale: nothing written, options and ask stay",
      server._answer("a10", "Nope", "", "") == "stale" and rd("a", 10)["metadata"].get("options") == OPTS and rd("a", 10)["metadata"].get("ask") == ASK
      and "answers" not in rd("a", 10)["metadata"], rd("a", 10)["metadata"])
check("a choice that matches no option, sent with a note, keeps the note as his comment (the choice named in it); the options and the ask stay, and it is no decision",
      server._answer("a10", "Nope", "wait, I meant the second one", "") == "stalenote" and rd("a", 10)["metadata"].get("options") == OPTS and rd("a", 10)["metadata"].get("ask") == ASK
      and "decision" in rd("a", 10)["metadata"]["needs"]
      and [(a["kind"], a["text"]) for a in rd("a", 10)["metadata"]["answers"]] == [("comment", "(late, the item no longer asks this: Nope) wait, I meant the second one")], rd("a", 10)["metadata"])
d10 = rd("a", 10); del d10["metadata"]["answers"]; (T / "store/a/10.json").write_text(json.dumps(d10))      # back to the fixture for the checks below
item("a", 120, needs=["decision"], ask=ASK, options=OPTS)
told.clear()
check("a pick with a note is a decision; the same send again (a double click) is stale and adds no comment and tells nobody more",
      server._answer("a120", "Wait", "after the holiday", "") == "decision" and (n_told := len(told)) >= 1
      and server._answer("a120", "Wait", "after the holiday", "") == "stalenote" and len(told) == n_told and [(a["kind"], a["text"]) for a in rd("a", 120)["metadata"]["answers"]] == [("decision", "after the holiday")], (told, rd("a", 120)["metadata"].get("answers")))
check("…but the same note sent again after another pick or other text is kept", server._answer("a120", "Ship", "after the holiday", "") == "stalenote" and len(rd("a", 120)["metadata"]["answers"]) == 2, rd("a", 120)["metadata"]["answers"])
check("a comment on an item with options changes neither the options nor the ask",
      server._answer("a10", "", "what does Drop mean?", "comment") == "comment" and rd("a", 10)["metadata"].get("options") == OPTS and rd("a", 10)["metadata"].get("ask") == ASK
      and rd("a", 10)["metadata"]["needs"] == ["decision"], rd("a", 10)["metadata"])

# ---- 11. the update tool clears options and ask without a recommended one
BAD1, BAD2 = OPTS[:1], [{**o, "recommended": True} for o in OPTS[:2]]
for why, o_ in (("one entry", BAD1), ("two recommended", BAD2), ("none recommended", [{**o, "recommended": False} for o in OPTS[:2]])):
    refused(f"update: a bad options list ({why}) is still refused", lambda o_=o_: _wt_update.stackshot_update("a11", options=o_, sender="home-here"), "Refused")
    check(f"…and nothing changed ({why})", rd("a", 11)["metadata"].get("options") == OPTS)
refused("update: clear_options does not go with a new list", lambda: _wt_update.stackshot_update("a11", options=OPTS[:2], clear_options=True, sender="home-here"), "clear_options")
refused("update: clear_ask does not go with a new ask", lambda: _wt_update.stackshot_update("a11", ask=YESNO, clear_ask=True, sender="home-here"), "clear_ask")
r_ = _wt_update.stackshot_update("a11", options=[], sender="home-here")
check("update: options=[] clears the options and leaves the ask", r_.startswith("updated a11") and "options" not in rd("a", 11)["metadata"] and rd("a", 11)["metadata"].get("ask") == ASK, r_)
_update_svc._update("a11", options=OPTS, sender="home-here")
check("fixture: the options are back", rd("a", 11)["metadata"].get("options") == OPTS)
r_ = _wt_update.stackshot_update("a11", clear_options=True, sender="home-here")
check("update: clear_options=true clears them too", r_.startswith("updated a11") and "options" not in rd("a", 11)["metadata"] and rd("a", 11)["metadata"].get("ask") == ASK, r_)
r_ = _wt_update.stackshot_update("a11", clear_ask=True, sender="home-here")
check("update: clear_ask=true clears the ask", r_.startswith("updated a11") and "ask" not in rd("a", 11)["metadata"], r_)
check("the update tool's description and parameters name the new flags",
      "clear_options=true" in _wt_update._UPDATE_DESC and "clear_ask=true" in _wt_update._UPDATE_DESC
      and {"clear_options", "clear_ask"} <= set(__import__("inspect").signature(_wt_update.stackshot_update.fn if hasattr(_wt_update.stackshot_update, "fn") else _wt_update.stackshot_update).parameters))

# ---- 12. the decision hand-over: a decision answer hands the item to its `then`, as a Done does on a step
told.clear()
b = lambda n: _model.derive(_service_store._load(f"a{n}"))
check("a decision with then = home-agent (Yes, no options): mover = then, needs = then, then cleared, your-call gone, no model conflict, and the then-mover is told with his answer",
      server._answer("a50", "Yes", "go on", "") == "decision" and rd("a", 50)["metadata"].get("mover") == "home-agent" and rd("a", 50)["metadata"].get("needs") == [AGENT]
      and "then" not in rd("a", 50)["metadata"] and "ask" not in rd("a", 50)["metadata"] and "state" not in rd("a", 50)["metadata"]
      and b(50).mover == "home-agent" and not b(50).conflicts and b(50).state == "alive" and _states.of(_service_store._load("a50"))[0] == "doing"
      and sorted(t[1] for t in told if t[0] == "a50") == [AGENT] and all("answered a50 on the board: Yes" in t[2] for t in told if t[0] == "a50"), (rd("a", 50)["metadata"], b(50), told))
told_a50 = [t for t in told if t[0] == "a50"]
check("F3: the then-mover's notice ends \"It's yours now\" (the owner's does not)",
      any(t[1] == AGENT and "answered a50 on the board: Yes — go on. It's yours now → " in t[2] for t in told_a50) and not any("yours now" in t[2] for t in told_a50 if t[1] == OWNER), told_a50)
check("...the pending answer names the then-mover alone",
      _web_answers._answers_load().get("a50", {}).get("told") == [AGENT], _web_answers._answers_load().get("a50"))
_update_svc._update("a50", next="home-agent: on it", sender="home-agent")
check("...and the then-mover's write settles it", "a50" not in _web_answers._answers_load(), _web_answers._answers_load())
told.clear()
check("a pick among the options with then = home-keeper (not in needs): the item goes to home-keeper, who alone is told, and the model reads clean",
      server._answer("a51", "Ship", "", "") == "decision" and rd("a", 51)["metadata"].get("mover") == "home-keeper" and rd("a", 51)["metadata"].get("needs") == [STEW] and "then" not in rd("a", 51)["metadata"]
      and "options" not in rd("a", 51)["metadata"] and b(51).mover == "home-keeper" and not b(51).conflicts and sorted(t[1] for t in told if t[0] == "a51") == [STEW], (rd("a", 51)["metadata"], told))
told.clear()
check("a stored mover Oliver and no then: the stored mover goes, the item reads as when nothing is stored (the first session in needs), no model conflict",
      server._answer("a52", "Yes", "", "") == "decision" and "mover" not in rd("a", 52)["metadata"] and rd("a", 52)["metadata"].get("needs") == ["home-agent"]
      and b(52).mover == "home-agent" and not b(52).conflicts, (rd("a", 52)["metadata"], b(52)))
told.clear()
check("nothing stored (today's behaviour, unchanged): decision out of needs, no mover or then written, the project's builder takes it as the model's default",
      server._answer("a53", "Yes", "", "") == "decision" and not any(k in rd("a", 53)["metadata"] for k in ("mover", "then", "needs")) and b(53).mover == "home-here" and not b(53).conflicts
      and [t[1] for t in told if t[0] == "a53"] == [OWNER], (rd("a", 53)["metadata"], b(53), told))
told.clear()
check("F1, a hold with a wake still standing: the stored mover Oliver goes, the item reads waiting with no model conflict, it is a time wait to home-agent (wait_kind time, mover home-agent as the picker and no old key, watch.set_at stamped), then cleared, nobody told it is theirs",
      server._answer("a58", "Yes", "", "") == "decision" and rd("a", 58)["metadata"].get("mover") == "home-agent" and "post_wake_mover" not in rd("a", 58)["metadata"] and "then" not in rd("a", 58)["metadata"] and "needs" not in rd("a", 58)["metadata"]
      and rd("a", 58)["metadata"].get("wait_kind") == "time" and rd("a", 58)["metadata"].get("watch", {}).get("set_at")
      and b(58).state == "waiting" and not b(58).conflicts and not any("yours now" in t[2] for t in told if t[0] == "a58"), (rd("a", 58)["metadata"], b(58), told))
_out = {}
watching_svc.watch_fire("a58", "time", time.time(), _out)
check("F1, a58 followed to the wake: alive, home-agent moves it, named in needs, no wait fields, no conflict, the arrival is owed to home-agent",
      b(58).state == "alive" and b(58).mover == "home-agent" and not b(58).conflicts and rd("a", 58)["metadata"].get("needs") == ["home-agent"] and AGENT in _out
      and not any(k in rd("a", 58)["metadata"] for k in ("hold", "wake", "then", "wait_kind", "post_wake_mover")), (rd("a", 58)["metadata"], _out))
told.clear()
check("F1, external still in needs: mover Oliver goes, the item reads waiting (outside), then is dropped (nothing reads it when external ends), needs holds external only, no model conflict",
      server._answer("a59", "Yes", "", "") == "decision" and "mover" not in rd("a", 59)["metadata"] and "then" not in rd("a", 59)["metadata"] and rd("a", 59)["metadata"].get("needs") == ["external"]
      and b(59).state == "waiting" and not b(59).conflicts and not any("yours now" in t[2] for t in told if t[0] == "a59"), (rd("a", 59)["metadata"], b(59), told))
_update_svc._update("a59", needs=[], sender="home-here")
check("F1, a59 followed to the end of external: it reads alive with no conflict (the owner's default mover; no stale then)", b(59).state == "alive" and not b(59).conflicts and "then" not in rd("a", 59)["metadata"], (rd("a", 59)["metadata"], b(59)))
told.clear()
check("F1, an open after link: mover Oliver goes, the item reads waiting (blocked), then stays for the release, no model conflict",
      server._answer("a60", "Yes", "", "") == "decision" and "mover" not in rd("a", 60)["metadata"] and rd("a", 60)["metadata"].get("then") == "home-agent" and "needs" not in rd("a", 60)["metadata"]
      and b(60).state == "waiting" and not b(60).conflicts, (rd("a", 60)["metadata"], b(60)))
# the prerequisite closes (its file says so), and the release hands to their then-movers
_p62 = json.loads((T / "store/a/62.json").read_text()); _p62["status"] = "completed"; _p62["outcome"] = "done"; (T / "store/a/62.json").write_text(json.dumps(_p62))
told.clear()
wakes_svc.release_after("a62", "done", "", "home-here")
check("F1, a60 followed to the end of its after: home-agent moves it (mover, first in needs), then cleared, no conflict, and home-agent is told by the release",
      b(60).state == "alive" and b(60).mover == "home-agent" and not b(60).conflicts and rd("a", 60)["metadata"].get("needs") == [AGENT] and "then" not in rd("a", 60)["metadata"]
      and any(t[0] == "a60" and t[1] == AGENT for t in told), (rd("a", 60)["metadata"], b(60), told))
told.clear()
check("F2, a pick that carries a wake with a then: it waits on its until, the mover Oliver and the then are gone, the time wait's picker is the then, stored as `mover` and never as the old key (stamped), no model conflict",
      server._answer("a61", "Park", "", "") == "decision" and hd_(rd("a", 61)["metadata"]) is True and wk_(rd("a", 61)["metadata"]) == "2099-01-01" and rd("a", 61)["metadata"].get("mover") == "home-agent" and "post_wake_mover" not in rd("a", 61)["metadata"]
      and "then" not in rd("a", 61)["metadata"] and "wait_kind" not in rd("a", 61)["metadata"]
      and rd("a", 61)["metadata"].get("watch", {}).get("set_at")
      and b(61).state == "waiting" and b(61).wait.post_wake_mover == "home-agent" and not b(61).conflicts, (rd("a", 61)["metadata"], b(61)))
_out = {}
watching_svc.watch_fire("a61", "time", time.time(), _out)
check("F2, through the wake: the item turns alive with home-agent as its mover, named in needs, the wake and the wait's fields gone, and the arrival is owed to home-agent",
      rd("a", 61)["metadata"].get("mover") == "home-agent" and rd("a", 61)["metadata"].get("needs") == ["home-agent"] and not any(k in rd("a", 61)["metadata"] for k in ("hold", "wake", "post_wake_mover", "wait_kind", "then"))
      and b(61).state == "alive" and b(61).mover == "home-agent" and not b(61).conflicts and AGENT in _out, (rd("a", 61)["metadata"], _out))
told.clear()
check("a park on an item that also waits after an open item: no time wait is stored (the wake would drop the after), then stays for the release of the after, no conflict",
      server._answer("a63", "Park", "", "") == "decision" and "wait_kind" not in rd("a", 63)["metadata"] and "post_wake_mover" not in rd("a", 63)["metadata"] and rd("a", 63)["metadata"].get("then") == "home-agent"
      and rd("a", 63)["metadata"].get("after") == ["a67"] and hd_(rd("a", 63)["metadata"]) is True and not b(63).conflicts, (rd("a", 63)["metadata"], b(63)))
_p67 = json.loads((T / "store/a/67.json").read_text()); _p67["status"] = "completed"; _p67["outcome"] = "done"; (T / "store/a/67.json").write_text(json.dumps(_p67))
told.clear(); wakes_svc.release_after("a67", "done", "", "home-here")
check("...a63 followed to the end of its after: the hold and wake go with it, home-agent moves it (mover, first in needs), then cleared, no conflict, and home-agent is told",
      b(63).state == "alive" and b(63).mover == "home-agent" and not b(63).conflicts and rd("a", 63)["metadata"].get("needs") == [AGENT] and "then" not in rd("a", 63)["metadata"]
      and any(t[0] == "a63" and t[1] == AGENT for t in told), (rd("a", 63)["metadata"], b(63), told))
told.clear()
check("a park on an item that also has external in needs: no time wait is stored, then is dropped, the item reads waiting with no conflict",
      server._answer("a64", "Park", "", "") == "decision" and "wait_kind" not in rd("a", 64)["metadata"] and "post_wake_mover" not in rd("a", 64)["metadata"] and "then" not in rd("a", 64)["metadata"]
      and "external" in rd("a", 64)["metadata"].get("needs", []) and not b(64).conflicts, (rd("a", 64)["metadata"], b(64)))
check("a park with a then stored its picker as `mover`; update clear_hold=true releases it and drops the wait's fields with it (wait_kind, watch), no refusal, no conflict; the agent stays the live mover (as clear_wait keeps an agent mover)",
      server._answer("a65", "Park", "", "") == "decision" and rd("a", 65)["metadata"].get("mover") == "home-agent" and "post_wake_mover" not in rd("a", 65)["metadata"] and "wait_kind" not in rd("a", 65)["metadata"]
      and (_update_svc._update("a65", clear_hold=True, sender="home-agent") or True) and not any(k in rd("a", 65)["metadata"] for k in ("hold", "wake", "wait_kind", "post_wake_mover", "watch", "then")) and rd("a", 65)["metadata"].get("mover") == "home-agent"
      and b(65).state == "alive" and b(65).mover == "home-agent" and not b(65).conflicts, (rd("a", 65)["metadata"], b(65)))
told.clear()
wakes_svc.wake_pass()
check("the wake pass hands a stored then (an old hold whose wake has come): home-agent moves it, no conflict, and is told",
      b(66).state == "alive" and b(66).mover == "home-agent" and not b(66).conflicts and "then" not in rd("a", 66)["metadata"] and rd("a", 66)["metadata"].get("needs") == [AGENT], (rd("a", 66)["metadata"], b(66), told))
check("the board item's shape (hold due, mover Oliver, then home-agent, no needs): the wake pass hands it to home-agent: the Oliver mover goes, mover and needs home-agent, then cleared, no conflict, home-agent told",
      b(68).state == "alive" and b(68).mover == "home-agent" and not b(68).conflicts and rd("a", 68)["metadata"].get("mover") == "home-agent" and rd("a", 68)["metadata"].get("needs") == [AGENT]
      and "then" not in rd("a", 68)["metadata"] and any("a68" in t[0] and t[1] == AGENT for t in told), (rd("a", 68)["metadata"], b(68), told))
check("an agent mover with an agent then (hold due): left alone, mover and then stay stored; the model reads no then beside an agent mover and notes no conflict",
      rd("a", 71)["metadata"].get("mover") == "home-keeper" and rd("a", 71)["metadata"].get("then") == "home-agent" and "needs" not in rd("a", 71)["metadata"] and not b(71).conflicts and b(71).then == "", (rd("a", 71)["metadata"], b(71)))
check("a then that is no session (free text), hold due: not handed, mover Oliver unchanged, the stale then is dropped (D2)",
      rd("a", 72)["metadata"].get("mover") == "Oliver" and "needs" not in rd("a", 72)["metadata"] and "then" not in rd("a", 72)["metadata"], rd("a", 72)["metadata"])
check("a session already in needs (hold due, then home-agent): left alone, needs unchanged, then stays",
      rd("a", 73)["metadata"].get("then") == "home-agent" and rd("a", 73)["metadata"].get("needs") == ["home-keeper"] and rd("a", 73)["metadata"].get("mover") is None, rd("a", 73)["metadata"])
_p70 = json.loads((T / "store/a/70.json").read_text()); _p70["status"] = "completed"; _p70["outcome"] = "done"; (T / "store/a/70.json").write_text(json.dumps(_p70))
told.clear(); wakes_svc.release_after("a70", "done", "", "home-here")
check("the board item's shape through an after release: handed to home-agent (stored Oliver mover dropped), no conflict, home-agent told",
      b(69).state == "alive" and b(69).mover == "home-agent" and not b(69).conflicts and rd("a", 69)["metadata"].get("needs") == [AGENT] and "then" not in rd("a", 69)["metadata"]
      and any(t[0] == "a69" and t[1] == AGENT for t in told), (rd("a", 69)["metadata"], b(69), told))
before54 = rd("a", 54)["metadata"]["needs"], rd("a", 54)["metadata"]["mover"], rd("a", 54)["metadata"]["then"]
check("a comment only on such an item: it stays his (decision, mover and then unchanged)",
      server._answer("a54", "", "a question first", "comment") == "comment" and (rd("a", 54)["metadata"]["needs"], rd("a", 54)["metadata"]["mover"], rd("a", 54)["metadata"]["then"]) == before54, rd("a", 54)["metadata"])
_u74 = _update_svc._update("a74", needs=["decision"], ask=YESNO, sender="home-agent")
m74 = rd("a", 74)["metadata"]
check("the whole chain, first half: the agent's own ask on an item it moves stores mover Oliver and then home-agent (his state makes him the mover), with no conflict",
      m74.get("mover") == "Oliver" and m74.get("then") == "home-agent" and "decision" in (m74.get("needs") or []) and not b(74).conflicts and b(74).mover == "Oliver", (_u74, m74, b(74)))
told.clear()
check("...second half: his answer hands the item back to the stored then-mover home-agent (mover, first in needs), then cleared, no conflict, and home-agent is told it is theirs",
      server._answer("a74", "Yes", "", "") == "decision" and rd("a", 74)["metadata"].get("mover") == "home-agent" and rd("a", 74)["metadata"].get("needs") == [AGENT] and "then" not in rd("a", 74)["metadata"]
      and b(74).mover == "home-agent" and b(74).state == "alive" and not b(74).conflicts
      and any(t[0] == "a74" and t[1] == AGENT and "It's yours now" in t[2] for t in told), (rd("a", 74)["metadata"], b(74), told))
check("a then that names him is no then: the stored mover goes, the project's builder takes it, no conflict",
      server._answer("a57", "Yes", "", "") == "decision" and "mover" not in rd("a", 57)["metadata"] and b(57).mover == "home-here" and not b(57).conflicts, (rd("a", 57)["metadata"], b(57)))

# ---- 13. review findings: D1 a then that is no live session, D2 a stale then after a declined hand-over, D3 watchers off
told.clear()
check("D1, Yes: a stored then that is no live session (home-ghost) takes nothing: then dropped, mover Oliver gone, the builder takes it as when no then is stored, no conflict, home-ghost not told or named",
      server._answer("a80", "Yes", "", "") == "decision" and "then" not in rd("a", 80)["metadata"] and "mover" not in rd("a", 80)["metadata"] and "home-ghost" not in json.dumps(rd("a", 80)["metadata"])
      and b(80).mover == "home-here" and b(80).state == "alive" and not b(80).conflicts and [t[1] for t in told if t[0] == "a80"] == [OWNER], (rd("a", 80)["metadata"], b(80), told))
told.clear()
check("D1, Park: a dead then is not stored as post_wake_mover: parked (hold and wake), then and mover Oliver gone, no wait_kind, no post_wake_mover, no conflict",
      server._answer("a81", "Park", "", "") == "decision" and hd_(rd("a", 81)["metadata"]) is True and wk_(rd("a", 81)["metadata"]) == "2099-01-01"
      and not any(k in rd("a", 81)["metadata"] for k in ("then", "mover", "wait_kind", "post_wake_mover")) and "home-ghost" not in json.dumps(rd("a", 81)["metadata"]) and not b(81).conflicts, (rd("a", 81)["metadata"], b(81)))
check("D1, a then that is live is still handed: a50's hand-over unchanged (mover home-agent), so the shared test lets a live session through",
      rd("a", 50)["metadata"].get("mover") == "home-agent" and handover_svc._then_live("home-agent", {"project": "projects/alpha"}) and not handover_svc._then_live("home-ghost", {"project": "projects/alpha"}))
told.clear()
check("D2, before the release: Yes on needs [decision, home-agent] + then home-agent + an open after leaves the item waiting, then stored, no conflict",
      server._answer("a82", "Yes", "", "") == "decision" and rd("a", 82)["metadata"].get("then") == "home-agent" and "mover" not in rd("a", 82)["metadata"] and rd("a", 82)["metadata"].get("needs") == ["home-agent"]
      and b(82).state == "waiting" and not b(82).conflicts, (rd("a", 82)["metadata"], b(82)))
_p83 = json.loads((T / "store/a/83.json").read_text()); _p83["status"] = "completed"; _p83["outcome"] = "done"; (T / "store/a/83.json").write_text(json.dumps(_p83))
wakes_svc.release_after("a83", "done", "", "home-here")
check("D2, the prerequisite closes: the hand-over declines (home-agent is already named in needs) and the stale then is dropped: no then, home-agent moves it, no conflict",
      "then" not in rd("a", 82)["metadata"] and rd("a", 82)["metadata"].get("needs") == ["home-agent"] and b(82).state == "alive" and b(82).mover == "home-agent" and not b(82).conflicts, (rd("a", 82)["metadata"], b(82)))
check("D2, the wake pass drops a then that already is the mover (mover home-agent, then home-agent, hold due)",
      "then" not in rd("a", 84)["metadata"] and rd("a", 84)["metadata"].get("mover") == "home-agent" and not b(84).conflicts, (rd("a", 84)["metadata"], b(84)))
_real_enabled = _watch.enabled
_watch.enabled = lambda: False       # D3: [model] watchers = false
try:
    told.clear()
    check("D3, watchers off: a park with a then stores no time wait: the old park stays (hold, wake), then stays, mover Oliver gone, no wait fields, no conflict",
          server._answer("a85", "Park", "", "") == "decision" and hd_(rd("a", 85)["metadata"]) is True and wk_(rd("a", 85)["metadata"]) == "2099-01-01"
          and rd("a", 85)["metadata"].get("then") == "home-agent" and not any(k in rd("a", 85)["metadata"] for k in ("mover", "wait_kind", "post_wake_mover", "watch")) and not b(85).conflicts, (rd("a", 85)["metadata"], b(85)))
    _p85 = rd("a", 85); _p85["metadata"]["until"] = "2020-01-01"; (T / "store/a/85.json").write_text(json.dumps(_p85))
    told.clear()
    wakes_svc.wake_pass()
    check("D3, the old wake pass ends the hold and hands the stored then: alive, home-agent moves it (mover, first in needs), no wait fields left, then cleared, no conflict, home-agent told",
          b(85).state == "alive" and b(85).mover == "home-agent" and rd("a", 85)["metadata"].get("needs") == [AGENT] and not any(k in rd("a", 85)["metadata"] for k in ("hold", "wake", "then", "wait_kind", "post_wake_mover"))
          and not b(85).conflicts and any(t[0] == "a85" and t[1] == AGENT for t in told), (rd("a", 85)["metadata"], b(85), told))
finally:
    _watch.enabled = _real_enabled

# ---- a your-step set by an update that also names the mover (mover=Oliver) still gets the server's step, so his note ticks it
STEP90 = "Run the 8 run deletions yourself: my gh DELETE call is refused by the permission layer"
_ol = lambda g: [(x["status"], x["text"]) for x in _hs._steps.view(rd("a", g)["metadata"], keeper=OWNER) if x["text"].startswith("Oliver:")]
_wt_update.stackshot_update("a90", sender="home-agent", step=STEP90, mover="Oliver", next="home-agent: confirm the runs are gone\nOliver: `for id in 1 2; do gh api -X DELETE runs/$id; done`")
_m90 = rd("a", 90)["metadata"]
check("named mover, setup: step= and mover=Oliver in one update: his step is on the list as the server's own (owner_step), beside the session's own Oliver line",
      _m90.get("state") == "your-step" and _m90.get("mover") == "Oliver" and _m90.get("owner_step") == f"Oliver: {STEP90}"
      and [(s_, t_.startswith("Oliver: `for id")) for s_, t_ in _ol(90)] == [("open", True), ("open", False)] and _ol(90)[1][1] == f"Oliver: {STEP90}", (_m90.get("owner_step"), _ol(90)))
told.clear(); r_s90 = server._answer("a90", "", "tried it, it says forbidden", "send"); _m90 = rd("a", 90)["metadata"]
check("named mover: his note on that step ticks the server's step (done, his words after the arrow), leaves the session's own Oliver line open, and the then-mover is still told to judge the note",
      r_s90 == "stepreply" and "owner_step" not in _m90
      and [s_ for s_, t_ in _ol(90) if t_.startswith(f"Oliver: {STEP90}")] == ["done"] and [s_ for s_, t_ in _ol(90) if t_.startswith("Oliver: `for id")] == ["open"]
      and any("Judge the note" in t[2] for t in told), (r_s90, _ol(90), _m90.get("owner_step"), [t[2][:80] for t in told]))
# a session that wrote its own Oliver line saying the same as the step: the equality rule adopts it (no second step), and his note ticks it
_wt_update.stackshot_update("a91", sender="home-agent", step=STEP90, mover="Oliver", next=f"home-agent: confirm the runs are gone\nOliver: {STEP90}")
check("named mover: the session's own `Oliver: <step>` line equal to the step is his one step (adopted, none added beside it)", len(_ol(91)) == 1 and rd("a", 91)["metadata"].get("owner_step") == f"Oliver: {STEP90}", (_ol(91), rd("a", 91)["metadata"].get("owner_step")))
server._answer("a91", "", "why does this fail?", "send")
check("named mover: his note ticks that one line by equality", [s_ for s_, _ in _ol(91)] == ["done"], _ol(91))

print(("ok" if not fails else "FAILED") + f": answer scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
