"""Scenario test for the stored item state (metadata.state; states.py) — the data layer only, fixture data, no live store, no network, no server socket.

No call sets or clears a state word any more (update's state, clear_state, party, chase, end, proof and chase_note are retired: tests/retired_inputs_scenario.py covers their refusal, step and supplies, and the routes). An item an older write
stored a state on is still READ as before, so this suite writes such an item as fixture data (metadata state, and the carry fields) and checks what the readers and the remaining writers do with it:

  * Stored doing / your-call / blocked / parked / verifying: read as stored (`state: <s>` in get and the brief, with its carry fields); a filing edit (priority) or a retired expected_by passed keeps it and moves no clock; a queued one loads as doing.
  * update(step=…) stores your-step and update(supplies=…) with after the blocked state; the carry fields of the state it replaces are dropped on a change (the reply says so); a completed item has no step or supplies; a close drops the state and a reopen does not bring it back;
    the server's own acts that end a wait (an after link released, a wake that fired, his answer) drop the state that stood on it.
  * A write that leaves an item unable to stand in its stored state (a your-call item whose needs lose decision or whose ask is cleared, a blocked one whose after link is dropped, a parked one whose hold is released, a doing one that is put on hold) DROPS the word, with a note, and refuses nothing.
    A write that touches nothing the state stands on (a recycle mark, a priority, a cap-words basis) leaves it alone, whatever the item's fields now back.
  * expected_by and expected_reason, which older calls pass, are accepted and not stored; the reply carries one note naming the park calls.
  * Backward compatible: an item with no state reads a derived one (decision → your-call, external → outside, hold → parked, an open after → blocked, else doing), shown by no state word in get, the brief and the client items read; a stored one as `state: <s>` with its carry fields.
  * The retired state route still needs the machine token; the MCP update tool still takes step, supplies, expected_by and expected_reason.
  * Stored doing items with a far expected time (written before the time was dropped) are alive and listed under agents; dated waits and held waits read from the wake and the dated steps (dated_wait.py).
    (tools/state_from_fields.py and tools/move_waiting_doing.py, which wrote and moved states through the route, are removed with it.)

    tests/run-suite state        → exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _midnight
tmp = _scratch.mkdtemp(prefix="statetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about states, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" and "tomorrow" the checks read: start on the far side of one that is close
now0 = time.time()
DAY = 86400.0
ZONE_HOURS = 4; ZONE_OFFSET = ZONE_HOURS * 3600      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], **({} if {"mover", "then", "hold", "after"} & set(meta) or meta.get("needs") else {"mover": owner or U["home-front"]}), "project": "projects/alpha", "next": "do the thing", **meta}}))      # the creator moves nothing; a fixture item that names no one is moved by its former creator
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.github import ghsync; from stackshot.model import states
from stackshot.model import model as _model
from stackshot.service import store as _service_store
from stackshot.projects import pages as _pages
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import checks as checks_svc
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import brief as _wt_brief
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False      # kept stubbed: this suite sets a reminder wake on an alive item another session moves, as home-front, to touch a state field; the real front test would refuse it (suite watch covers the rule)
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # an expected_by n hours after the suite started (a time of day in the instance timezone)
BACK, OTHER, GONE = "team-back", "home-other", "home-gone"      # as the update path stores a name the registry does not know
UB, UO = U["team-back"], U["home-other"]
def upd(i, **kw):
    return server._update(f"a{i}", sender="home-front", **kw)

TODAY = day(0)
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
mt = lambda i, letter="a": rd(i, letter)["metadata"]
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
def refused_nw(name, i, f, *want, letter="a"):
    """refused with the words, and the item's file is byte for byte as it was"""
    was = raw(i, letter)
    refused(name, f, *want)
    check(name + " (nothing written)", raw(i, letter) == was, None)

# ================================================================ doing (stored as fixture data: no call sets a state word any more)
item(1, needs=[BACK], su=now0 - 3 * DAY, state="doing")
before = rd(1)
out = upd(1, priority="p2")
m = mt(1)
check("doing: a stored doing item carries no expected time, and a write that does not touch what it stands on keeps it", m.get("state") == "doing" and "expected_by" not in m and "expected_reason" not in m, m)
check("doing: a filing edit (priority): the state clock and the confirm stay; only `updated` moves",
      rd(1)["state_updated"] == before["state_updated"] and rd(1)["confirmed"] == before["confirmed"] and rd(1)["updated"] > before["updated"], (rd(1), before))
check("doing: …every other field stays (the stored phase and the priority apart: every save of an open item writes the phase)", {k: v for k, v in m.items() if k not in ("phase", "priority", "last_activity")} == before["metadata"], (m, before["metadata"]))
check("doing: …the reply shows `state: doing` (stored, not derived) and no expected time, and no note about a dropped state", "state: doing" in out and "state: doing (derived)" not in out and "expected_by" not in out and "dropped" not in out, out)
check("doing: …no page is owed for it", "page update" not in out.lower().replace("(pilot", ""), out[-300:])
item(2, needs=[BACK], state="doing")
out = upd(2, expected_by=hrs(30), expected_reason="the builder runs the whole suite and the review")
check("doing: expected_by and expected_reason, which older calls pass, are accepted and not stored: the item stays doing and the reply carries one note naming the park calls",
      mt(2)["state"] == "doing" and "expected_by" not in mt(2) and "expected_reason" not in mt(2) and out.count("no longer kept") == 1 and "hold=true" in out and "until=" in out and "after=[" in out and "wait_kind=\"relay\"" in out, (mt(2), out[-500:]))
for n_, kw_ in ((92, dict(expected_by=hrs(-1))), (93, dict(expected_by="next week")), (94, dict(expected_by="2026-02-30")), (95, dict(expected_by=hrs(24 * 8), expected_reason="a long job that waits on a vendor"))):
    item(n_, needs=[BACK], state="doing"); o_ = upd(n_, **kw_)
    check(f"doing: …a time that was refused before (item {n_}: past, no date, a 7-day one) is no longer judged: accepted, not stored, with the note", mt(n_)["state"] == "doing" and "expected_by" not in mt(n_) and "no longer kept" in o_, (mt(n_), o_[-300:]))
item(96, needs=[BACK], state="doing"); o_ = upd(96, priority="p2")
check("doing: …a call with neither retired field carries no note", "no longer kept" not in o_, o_[-300:])
item(3, needs=[BACK], state="doing")
upd(3, expected_by=TODAY)
check("doing: …a bare date is the same: nothing stored", mt(3)["state"] == "doing" and "expected_by" not in mt(3), mt(3))

# ================================================================ queued (retired): a stored one still loads
item(9, needs=[BACK], state="queued")
check("queued: a stored one loads as doing", states.stored(rd(9)) == "doing" and states.of(rd(9)) == ("doing", False), states.of(rd(9)))
check("queued: …and is no state the item can be written in", "queued" not in states.STATES, None)

# ================================================================ your-call: a stored one stands on needs decision and the ask; a write that takes either away drops the word
item(11, needs=["decision"], ask=ASK, state="your-call")
item(12, needs=["decision"], ask=ASK, state="your-call")
check("your-call: a stored one is read as stored", states.stored(rd(12)) == "your-call" and "state: your-call" in server._fmt({**rd(12), "gid": "a12"}), None)
out = upd(12, clear_needs=True)
check("your-call: a later write that takes the decision away drops the state, says so and names what it stood on (it is no refusal: no call can clear a state)",
      "state" not in mt(12) and "decision" not in mt(12).get("needs", []) and "stored state your-call dropped" in out and "needs decision and the ask" in out, (mt(12), out[-300:]))

# ================================================================ your-step: step= stores it
item(14, needs=[])
refused_nw("your-step: a step over 300 characters is refused", 14, lambda: upd(14, step="x" * 301), "at most 300 characters")
upd(14, step="gh pr merge 6  --squash\nthen check the deploy")
check("your-step: stored on one line, no agent session needed", mt(14)["state"] == "your-step" and mt(14)["step"] == "gh pr merge 6 --squash then check the deploy", mt(14))

# ================================================================ blocked: after and supplies; a write that drops the link drops the word
item(17, needs=[BACK]); item(18, needs=[OTHER], subject="[home] what 17 waits on")
upd(17, after=["a18"], supplies="the schema it writes", ask_by=day(9))   # an item wait has an end: ask_by
check("blocked: after and supplies in the same write", mt(17)["state"] == "blocked" and mt(17)["after"] == ["a18"] and mt(17)["supplies"] == "the schema it writes", mt(17))
out = upd(17, clear_after=True)
check("blocked: a later write that drops the after link drops the state and its supplies and says so (no refusal)", "state" not in mt(17) and "supplies" not in mt(17) and "after" not in mt(17) and "stored state blocked dropped" in out and "after, and supplies" in out, (mt(17), out[-300:]))

# ================================================================ parked: a stored one stands on the hold, the wake and its basis
item(20, needs=[BACK], hold=True, wake=day(30), wait_basis={"text": f"Printer order confirmed {day(35)}", "wake": day(30), "by": "x", "at": now0}, state="parked")
out = upd(20, clear_hold=True)
check("parked: a later write that releases the hold drops the state and says so (no refusal)", "state" not in mt(20) and "hold" not in mt(20) and "stored state parked dropped" in out and "the wake and the owner's words or the wait_basis" in out, (mt(20), out[-300:]))
item(22, needs=[BACK], hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}, state="parked")
upd(22, priority="p1")
check("parked: …a stored park on his recorded words (cap_ok) keeps its state through a write that touches nothing it stands on", mt(22)["state"] == "parked" and mt(22)["priority"] == "p1", mt(22))

# ================================================================ the other gates
item(26, status="completed", needs=[BACK], outcome="done")
refused_nw("gate: a completed item has no step or supplies", 26, lambda: upd(26, step="x"), "completed item has no step or supplies")
refused_nw("gate: …a close that passes a step", 2, lambda: upd(2, status="completed", outcome="done", reason="x", description="- Done", step="x"), "completed item has no step or supplies")
refused_nw("gate: step and supplies together are refused: pass one", 2, lambda: upd(2, step="x", after=["a18"], supplies="y"), "pass one of them")

# ================================================================ a change of state drops the old state's fields
out = upd(1, step="open https://x.example/approve")
check("change: doing → your-step says so (doing carries no field to drop)", mt(1)["state"] == "your-step" and "expected_by" not in mt(1) and mt(1)["step"] == "open https://x.example/approve"
      and "state doing → your-step" in out and "dropped" not in out, (mt(1), out[-300:]))
out = upd(1, after=["a18"], supplies="the numbers", ask_by=day(5))
check("change: your-step → blocked drops step", mt(1)["state"] == "blocked" and "step" not in mt(1) and mt(1)["supplies"] == "the numbers" and "state your-step → blocked" in out and "dropped step" in out, (mt(1), out[-300:]))
out = upd(1, expected_by=hrs(4))
check("change: a write that leaves the state alone, with a retired expected_by, changes nothing, stores no date and says so once", "expected_by" not in mt(1) and mt(1)["state"] == "blocked" and "state blocked →" not in out and out.count("no longer kept") == 1, (out[-700:],))
item(23, needs=[BACK], state="verifying", proof="uptime 200 for 3 days", end=day(5))
check("change: …a write that leaves the state alone (a new next) keeps it and its fields", (upd(23, next="home-front: still checking"), mt(23))[1].get("proof") == "uptime 200 for 3 days" and mt(23)["state"] == "verifying" and mt(23)["end"] == day(5), mt(23))

# ================================================================ a close, a reopen
upd(11, status="completed", outcome="done", reason="decided", description="- Settled and live")
check("close: a close drops the state; the outcome is the record", rd(11)["status"] == "completed" and "state" not in mt(11) and mt(11)["outcome"] == "done", mt(11))
upd(11, status="open", next="home-front: back again")
check("close: …a reopen does not bring it back", "state" not in mt(11), mt(11))
item(27, needs=[BACK], state="doing", expected_by=hrs(2), check="item_closed a99")
with contextlib.redirect_stderr(io.StringIO()):
    checks_svc.check_close("a27", _service_store._load("a27"), "item_closed a99", time.time())
check("close: a close on a done check drops it too", rd(27)["status"] == "completed" and "state" not in mt(27) and "expected_by" not in mt(27), mt(27))
item(28, needs=[BACK], after=["a29"], state="blocked", supplies="the numbers"); item(29, needs=[OTHER], subject="[home] what 28 waits on")
upd(29, status="completed", outcome="done", reason="finished", description="- The thing is done and live")
check("release: an after link released by the item's close ends the blocked state", "after" not in mt(28) and "state" not in mt(28) and "supplies" not in mt(28), mt(28))

item(31, needs=[BACK], hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}, state="parked")
item(32, needs=[BACK], wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}, state="parked")
item(33, needs=[BACK], state="doing", expected_by=hrs(2), hold=True, wake=day(20))
with contextlib.redirect_stderr(io.StringIO()):
    wakes_svc.wake_pass(_pages.zone_now() + datetime.timedelta(days=21))
check("release: a wake that fires ends the park that stood on it (held, and a reminder alike)", "wake" not in mt(31) and "hold" not in mt(31) and "state" not in mt(31) and "state" not in mt(32) and "wake" not in mt(32), (mt(31), mt(32)))
check("release: …a state that did not stand on the wake is kept", mt(33).get("state") == "doing" and mt(33).get("expected_by") == hrs(2) and "wake" not in mt(33), mt(33))

# ================================================================ a write that leaves the state alone
item(30, needs=[BACK], state="doing", expected_by=hrs(-3), su=now0 - 5 * DAY)
upd(30, next="home-front: still going")
check("alone: a stored time that has lapsed (written before the time was dropped) refuses nothing and is not read", mt(30)["state"] == "doing", mt(30))
out = upd(30, expected_by=hrs(-3))
check("alone: …a past date passed now is accepted and not stored, with the note: it is no longer judged", mt(30)["state"] == "doing" and "no longer kept" in out, (mt(30), out[-300:]))

# ---- a stored state is re-checked only by a write that touches a field it stands on
item(37, needs=[], state="doing", expected_by=hrs(2))            # a stored state its fields no longer back (hand-edited, or from before a rule)
server._update("a37", recycle=True, sender="home-front")
check("touched: a recycle mark is not wedged by a stored state its item no longer backs", mt(37).get("recycle") is True and mt(37)["state"] == "doing", mt(37))
upd(37, priority="p1")
check("touched: …nor is a filing edit (priority)", mt(37)["priority"] == "p1" and mt(37)["state"] == "doing", mt(37))
item(57, needs=[], hold=True, wake=day(30), state="doing", expected_by=hrs(2))
st, d = server._client_post("testbox", "cap-words", {"item": "a57", "basis": f"Printer order confirmed {day(35)}", "sender": "home-test"})
check("touched: …nor a cap-words wait_basis (doing stands on needs and next, not on that)", st == 200 and mt(57).get("wait_basis"), (st, d, mt(57)))
item(114, needs=["decision"], ask=ASK, state="your-call")
out = upd(114, clear_ask=True)
check("touched: a write that clears the ask a your-call stands on drops the state and says so (no refusal)", "state" not in mt(114) and "ask" not in mt(114) and "stored state your-call dropped" in out, (mt(114), out[-300:]))

# ---- his answer ends a stored your-call (and a park he picks)
item(58, needs=["decision"], ask=ASK, state="your-call")
server._answer("a58", "", "go ahead with it", "answer")
check("answer: his decision ends a stored your-call (the call is made)", "state" not in mt(58) and "decision" not in mt(58).get("needs", []) and "ask" not in mt(58), mt(58))
upd(58, next="home-front: carrying on")
check("answer: …and a plain write afterwards is not refused", mt(58)["next"] == "home-front: carrying on", mt(58))
park_lab = f"Park until {day(5)}"      # a raise stored before the park option was dropped still carries one; his press is his own hold
opts_ = [{"label": park_lab, "line": f"On hold with a wake on {day(5)}.", "recommended": True, "wake": day(5)}, {"label": "Not needed", "line": "No longer wanted.", "recommended": False}]
item(59, needs=["decision", BACK], ask=ASK, options=opts_, state="your-call")
server._answer("a59", park_lab, "", "")
check("answer: …a park he picks from the options leaves no stored state, only the hold and the wake", "state" not in mt(59) and hd_(mt(59)) is True and wk_(mt(59)), mt(59))
upd(59, next="home-front: waiting it out")
check("answer: …and a plain write on it works", mt(59)["next"] == "home-front: waiting it out", mt(59))

# ---- a hold and a state of another kind cannot stand together
item(130, needs=[BACK], hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}, state="parked")
refused_nw("hold: a decision put on a parked item is refused (an ask for later is a time wait whose post-wake mover is the owner), naming clear_hold", 130, lambda: upd(130, needs=["decision"], ask=ASK), "decision together with a hold", "clear_hold=true")
out = upd(130, needs=["decision"], ask=ASK, clear_hold=True)
check("hold: …with clear_hold the hold goes, and the state that stood on it (the write drops it)", "hold" not in mt(130) and "state" not in mt(130) and "decision" in mt(130)["needs"] and "stored state parked dropped" in out, (mt(130), out[-300:]))
upd(130, next="home-front: carry on")
check("hold: …and a plain write afterwards is not refused", mt(130)["next"].split("\n")[0] == "home-front: carry on", mt(130))
item(38, needs=[BACK], state="doing", expected_by=hrs(2))
out = upd(38, hold=True, wake=day(3), wait_basis=f"paper delivery confirmed {day(4)}")      # a time wait carries a reason: a real date
check("hold: hold=true on a doing item drops the stored state and says why", "state" not in mt(38) and "expected_by" not in mt(38) and hd_(mt(38)) is True
      and "stored state doing dropped: a hold ends it; the item reads parked" in out, (mt(38), out[-300:]))
check("hold: …it reads as waiting on a time from its until (the hold and the wake are stored as that one date) and shows no state word",
      _model.derive({**rd(38), "gid": "a38"}).state == "waiting" and _WT.stored_until(mt(38)) and "state: " not in server._fmt({**rd(38), "gid": "a38"}), None)
item(132, needs=[BACK], hold=True, wake=day(30), wait_basis={"text": f"Printer order confirmed {day(35)}", "wake": day(30), "by": "x", "at": now0}, state="parked")
upd(132, hold=True)
check("hold: hold=true again on a parked item keeps its state", mt(132)["state"] == "parked", mt(132))
item(133, needs=[BACK], state="doing", expected_by=hrs(2))
upd(133, wake=day(3))
check("hold: a wake alone is a backstop: it does not drop a stored state", mt(133)["state"] == "doing", mt(133))
item(39, needs=["decision", BACK], ask=ASK, options=[{"label": f"Park until {day(5)}", "line": "On hold.", "recommended": True, "wake": day(5)}, {"label": "Not needed", "line": "No.", "recommended": False}], state="doing", expected_by=hrs(2))
server._answer("a39", f"Park until {day(5)}", "", "")
check("answer: a park he picks ends a stored state of any kind (doing here), not only your-call", "state" not in mt(39) and "expected_by" not in mt(39) and hd_(mt(39)) is True, mt(39))
# ================================================================ the derived state
item(63, needs=["decision", BACK], ask=ASK, state="doing", expected_by=hrs(2))        # a stored state that is not the section's: the brief says it
D = lambda i, letter="a": states.of(rd(i, letter), lambda it: server._after_open(it.get("metadata") or {}))
item(40, needs=["decision"], ask=ASK, then="home-front"); item(41, needs=["external"]); item(42, needs=[BACK], hold=True, wake=day(30), wait_basis={"text": f"visit {day(35)}", "wake": day(30), "by": "x", "at": now0})
item(43, needs=[BACK], hold=True, wake=day(3)); item(44, needs=[BACK], after=["a18"]); item(45, needs=[BACK], after=["a29"]); item(46, needs=[BACK], rank=2); item(47, needs=[], rank=2)   # a leftover rank on a stored item
item(48, needs=[BACK]); item(49, status="completed", needs=[BACK], outcome="done"); item(50, needs=[BACK], state="doing", expected_by=hrs(2))
item(51, needs=["decision", BACK], hold=True, wake=day(3), ask=ASK); item(52, needs=["decision", "external"], ask=ASK)
item(53, needs=[BACK], hold=True, after=["a18"]); item(54, needs=[BACK], hold=True, wake=day(30), after=["a18"], cap_ok={"wake": day(30), "by": "the owner", "quote": "wait"})
item(55, needs=[BACK], state="bogus"); item(56, needs=[BACK], hold=True, after=["a29"])
check("derived: needs decision → your-call", D(40) == ("your-call", True), D(40))
check("derived: needs external → outside", D(41) == ("outside", True), D(41))
check("derived: a hold with a wake and a wait_basis → parked", D(42) == ("parked", True), D(42))
check("derived: …a hold with a wake and his words (cap_ok) → parked", D(54) == ("parked", True), D(54))
check("derived: …a hold on a wake alone is a park too", D(43) == ("parked", True), D(43))
check("derived: an after link to an open item → blocked", D(44) == ("blocked", True), D(44))
check("derived: …a closed one blocks nothing: doing", D(45) == ("doing", True), D(45))
check("derived: a leftover rank is read by nothing: doing", D(46) == ("doing", True), D(46))
check("derived: …with or without a session in needs", D(47) == ("doing", True), D(47))
check("derived: nothing else → doing", D(48) == ("doing", True), D(48))
check("derived: a closed item has none", D(49) == ("", False) and states.derive(rd(49)) == "" and states.words(rd(49)) == "", D(49))
check("derived: a stored state is read as stored", D(50) == ("doing", False) and states.words(rd(50)) == "state: doing", D(50))
check("derived: decision beats a hold (a decision is never on hold) and external", D(51) == ("your-call", True) and D(52) == ("your-call", True), (D(51), D(52)))
check("derived: a hold with an open after link and no wake → blocked; with a wake and his words → parked (the park wins)", D(53) == ("blocked", True) and D(54) == ("parked", True), (D(53), D(54)))
check("derived: …a hold whose after target is closed is a plain park", D(56) == ("parked", True), D(56))
check("derived: a value that is no state is ignored: derived", D(55) == ("doing", True), D(55))
check("derived: the words: a stored state reads `state: doing`, a derived one shows no word", states.words(rd(48), lambda it: []) == "" and states.words(rd(50)) == "state: doing", None)
# get
txt = server._fmt({**rd(40), "gid": "a40"})
check("get: a derived state shows no state word (the model line says who moves it)", "state: " not in txt and "model:" in txt, txt)
txt = server._fmt({**rd(50), "gid": "a50"})
check("get: a stored one reads `state: doing` with no expected time under it, whatever the file still holds", "state: doing\n" in txt + "\n" and "(derived)" not in txt.split("state: doing")[1].split("\n")[0] and "expected_by" not in txt, txt)
txt = server._fmt({**rd(44), "gid": "a44"})
check("get: an after link to an open item reads blocked from the fields (the server's own look at the other item) and shows no state word", D(44) == ("blocked", True) and "state: " not in txt, txt)
txt = server._fmt({**rd(49), "gid": "a49"})
check("get: a closed item shows no state line", "state:" not in txt, txt)
# the brief
b = _wt_brief.stackshot_brief()
check("brief: an item that stores a state carries its state line; one that stores none carries none", "state: your-call (derived)" not in b and "(derived)" not in b and "expected_by" not in b and "state: doing" in b, b.count("state: "))
B_ = render.Board(str(T / "store"))
br = B_.brief()
sline = next((ln for ln in br.splitlines() if ln.startswith("  alive ")), "")
mm_ = re.fullmatch(r"  alive (\d+) \(your move (\d+), agents (\d+)\) · waiting (\d+)", sline)
nopen = sum(1 for p in (T / "store/a").glob("*.json") if json.loads(p.read_text()).get("status") == "open")
check("brief: the session-start brief has one alive / waiting line counting every open item, and no `states:` line",
      mm_ and int(mm_[1]) + int(mm_[4]) == nopen and int(mm_[2]) + int(mm_[3]) == int(mm_[1]) and int(mm_[2]) >= 3 and not any(ln.startswith("  states: ") for ln in br.splitlines()), (sline, nopen))
yc = [ln for ln in br.splitlines() if ln.startswith("  your move: ")]
check("brief: …a your-move line names the item and its mover and says no state word", yc and not any("state:" in ln for ln in yc), yc)
check("brief: …no line of the session-start brief carries one of the seven state words (it names alive and waiting)", not any("state:" in ln for ln in br.splitlines()), [ln for ln in br.splitlines() if "state:" in ln])
check("brief: …render and states agree: a stored state has its word, a derived one none", render.state_words(next(r for r in B_.rows if r["gid"] == "a46")) == ""
      and render.state_words(next(r for r in B_.rows if r["gid"] == "a50")) == "state: doing", None)
# the client API's items read
def items_for(key): return json.loads(server._client_items(key)[2])["items"]
mine = {x["shown"]: x for k in ("home-front", BACK) for x in items_for(U[k])}      # an item is listed under its mover (or its then), not its creator
check("client items: an item that stores no state carries no state, state_fields, state_derived or state_hint", all(k not in mine["a40"] for k in ("state", "state_fields", "state_derived", "state_hint")), mine.get("a40"))
check("client items: …a stored doing one carries its state and no carry field", mine["a50"]["state"] == "doing" and "state_derived" not in mine["a50"] and mine["a50"]["state_fields"] == {}, mine.get("a50"))
check("client items: …an item with a stored state of another kind has only its own fields", mine["a14"]["state"] == "your-step" and mine["a14"]["state_fields"] == {"step": "gh pr merge 6 --squash then check the deploy"}, mine.get("a14"))
check("client items: …a derived blocked item is listed as waiting, with no state word", "state" not in mine["a44"] and "state" not in mine["a45"] and mine["a44"]["list"] == "waiting", (mine["a44"], mine["a45"]))
check("client items: …a closed item is not listed", "a49" not in mine, None)


# ================================================================ POST /client/state, the MCP layer (the route and the inputs are retired: the refusals are in retired_inputs_scenario)
from stackshot.fleet import client as _client
from starlette.testclient import TestClient
(T / "secrets").mkdir(exist_ok=True)
tok = open(_client.mint("home-test")).read().strip()
item(62, needs=[BACK])
was62 = raw(62)
with TestClient(server.mcp.http_app()) as c:
    r = c.post("/client/state", json={"sender": "home-test", "item": "a62", "state": "doing"})
    check("http: the retired state route still needs the machine token: without it 401, and nothing is written", r.status_code == 401 and raw(62) == was62, (r.status_code, r.text[:100]))
async def mcp_checks():
    from fastmcp import Client
    async with Client(server.mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
        props = tools["update"].input_schema["properties"]
        check("mcp: update takes step, supplies, expected_by and expected_reason as strings (the last two are accepted and not kept)",
              all(props.get(k, {}).get("type") == "string" for k in ("step", "supplies", "expected_by", "expected_reason")), {k: props.get(k) for k in ("step", "supplies", "expected_by", "expected_reason")})
        desc = tools["update"].description
        check("mcp: …its description says expected_by and expected_reason are accepted and not kept, and that step sets his step (step=\"none\" withdraws it) and supplies the blocked state",
              "expected_by and expected_reason, which older calls pass, are accepted and not kept" in desc and 'step="none" withdraws it' in desc and "sets the item blocked on that item" in desc and "(derived)" not in desc, None)
        item(80, needs=[BACK], state="doing")
        await c.call_tool("update", {"item_id": "a80", "expected_by": hrs(2), "sender": "home-front"})
        check("mcp: …and a call through the layer with an old expected_by is accepted, nothing is stored, the stored state stays", mt(80).get("state") == "doing" and "expected_by" not in mt(80), mt(80))
        try:
            await c.call_tool("update", {"item_id": "a80", "supplies": "the numbers", "sender": "home-front"})
            check("mcp: …and a refusal comes back through it, naming what to add (supplies needs after)", False)
        except Exception as e:
            check("mcp: …and a refusal comes back through it, naming what to add (supplies needs after)", "after" in str(e) and "Refused" in str(e), str(e)[:300])
        check("mcp: …the refused call wrote nothing", mt(80).get("state") == "doing" and "supplies" not in mt(80), mt(80))
asyncio.run(mcp_checks())

# ================================================================ fixtures from here on: items that STORE an old state word (tools/state_from_fields.py and the inputs that wrote one are removed)
def g(n, subject=None, **kw): item(n, letter="g", subject=subject, **kw)

# ================================================================ a doing item stored with a far expected time (before the time was dropped): work in hand, read as it always was (tools/move_waiting_doing.py, which parked them once, is removed)
from stackshot.model import model as _model
# states.reads_as_wait stays gone: the reason text is never refused. The wait wording is read since the board item's follow-up by model_guards.reads_as_wait, which only adds a note to the update
# reply (service/update.py _doing_wait_note; tests/agent_due_scenario.py, section 6b), never a refusal and never a state change.
check("far-by states.reads_as_wait is gone: the reason text is never refused (model_guards.reads_as_wait only notes)", not hasattr(states, "reads_as_wait"), None)
for p in (T / "store/a").glob("*.json"): p.unlink()
for p in (T / "store/g").glob("*.json"): p.unlink()
g(20, needs=[BACK], state="doing", expected_by=hrs(60), expected_reason="waits on Sunday's timer run")        # a wait, and long
g(21, needs=[BACK], state="doing", expected_by=hrs(30))                                                       # long, no reason
g(22, needs=[BACK], state="doing", expected_by=hrs(5), expected_reason="waits for tonight's timer to fire")     # near: ignored from now on, left as it is
g(23, needs=[BACK], state="doing", expected_by=hrs(5), expected_reason="the builder subagent runs the test suite")   # work in hand: stays
g(24, needs=[BACK], state="doing", expected_by=hrs(24 * 400), expected_reason="waits for the yearly timer")           # wake beyond a year: for review
g(25, needs=[BACK], state="doing", expected_by=hrs(-2), expected_reason="waits for tomorrow's timer")               # in the past: ignored, left as it is
g(26, needs=[BACK], state="doing", expected_by=hrs(5))                                                               # work in hand, short, no reason: stays
g(27, needs=[BACK], state="doing", expected_by=hrs(11), expected_reason="the builder subagent runs the review")      # inside 12 h: left as it is
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + n * 86400))                                    # the local calendar day n days from the suite's start
g(29, needs=[BACK], state="doing", expected_by=day(3))                                                              # a bare date 3 days out reads as the end of that day: long, wake = the start of the next day
g(28, needs=[BACK], state="doing")                                                                                   # stored without any time (how a doing item is stored now)
now_ = time.time()
lst = lambda n: server._item_list(dict(rd(n, "g"), gid=f"g{n}"))
check("far-by list: every stored doing item is listed under Agents at work, a far stored expected_by or none alike: the time is not read, so none reads as Waiting",
      all(lst(n) == "agents" for n in (20, 21, 22, 23, 24, 25, 26, 27, 28, 29)), {n: lst(n) for n in (20, 21, 22, 23, 24, 25, 26, 27, 28, 29)})
mod = _model.derive(dict(rd(21, "g"), gid="g21"), now_, after_open=lambda it: [], anchored=lambda it: False)
vw = _model.view(dict(rd(21, "g"), gid="g21"), mod, now_)
check("far-by model: view leaves the doing item with a far stored expected_by alive: no wait on a time, derive unchanged", mod.state == _model.ALIVE and vw.state == _model.ALIVE and mod.today == "doing", (mod, vw))
check("far-by items API: …the items API sends no expected time for them, however far or long past the stored time is",
      all(x["expected_by"] is None and x["overdue"] is None and x["wait"] == "" for x in items_for(BACK) if x["gid"] in ("g20", "g21", "g25", "g28")) and any(x["gid"] == "g20" for x in items_for(BACK)),
      [x for x in items_for(BACK) if x["gid"] == "g20"])
bf0 = render.Board(str(T / "store")).brief()
check("far-by brief: the brief carries no line about doing items with a far expected_by (the line is gone)", "have an expected_by more than 12 h out" not in bf0 and "expected_by" not in bf0, [l for l in bf0.splitlines() if "doing items" in l][:5])
g(34, needs=[BACK], next="home-peer: wait for board#21 and board#23", state="doing")
nn = "\n".join(server._next_names_lines(dict(rd(34, "g"), gid="g34")))
check("far-by named in next: a doing item with a far stored time is open, mover, like any doing item", "board#21: open, mover" in nn and "board#23: open, mover" in nn, nn)
g(35, needs=[BACK], state="doing", expected_by=hrs(60), expected_reason="waits on Sunday's timer run", hold=True, wake=day(3))      # stored doing, held, with a far legacy time: parked already, left alone
check("far-by held: the held doing item is on hold as the server reads it, and its legacy time would otherwise select it", W.is_held(rd(35, "g")) and W.doing_agent(rd(35, "g")), rd(35, "g").get("metadata"))

# ================================================================ a doing item that only waits for a later day reads as waiting (dated_wait.py)
from stackshot.waits import dated_wait as _dw
for p in (T / "store/g").glob("*.json"): p.unlink()
def ordinal(n): return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
def prose(n):                                                         # "Wed Nov 4th": the board's prose form for the local day n days from the suite's start
    t = time.gmtime(now0 + n * DAY + ZONE_OFFSET)
    return time.strftime("%a %b ", t) + ordinal(t.tm_mday)
def iso(n): return time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))     # "2026-11-04": the same day in ISO form
def view_of(n):
    it = dict(rd(n, "g"), gid=f"g{n}")
    return _model.view(it, _model.derive(it, now_, after_open=lambda i: [], anchored=lambda i: False), now_)
wk = lambda h: hrs(h).replace(" ", "T")
NX = f"team-back: {prose(2)} after the nightly run, check the result"
g(50, needs=[BACK], state="doing", wake=wk(24), next=NX)                                                      # a wake tomorrow, the only step dated for the day after
g(51, needs=[BACK], state="doing", wake=wk(24), next=NX + "\nteam-back: tidy the notes")                       # …with one undated step: can act now
g(52, needs=[BACK], state="doing", wake=wk(0.5), next=NX)                                                     # a wake 30 minutes out
g(53, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: after {day(2)} check the result\nteam-back: {prose(3)} after the weekly run, close it")   # two dated steps: ISO and prose
g(54, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: {prose(-1)} check the result")             # a step dated in the past
g(55, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: {prose(0)} check the result")              # a step dated today
g(56, needs=[BACK], state="doing", wake=wk(24), next="")                                                      # no open step
g(57, needs=[BACK], state="doing", wake=wk(72), next=f"team-back: {prose(2)} check the result")              # the step is dated before the wake's day
g(58, needs=[BACK], state="doing", expected_by=hrs(30), expected_reason="the nightly run", next=NX)           # a stored expected_by alone (past 12 h too) and a dated step: no wake, so no wait
g(59, needs=[BACK], state="doing", wake=wk(24), expected_by=hrs(0.5), expected_reason="the build", next=NX)   # a wake tomorrow beside a stored expected_by within the hour: the stored time is not read
g(60, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: {prose(2)} after the run, check the result\n- {prose(5)} the tail of the same step")  # a bare sub-bullet joins the step above
g(61, needs=[BACK], state="doing", wake=wk(24), hold=True, next=NX)                                            # on hold: not a doing item to relabel
v = {n: view_of(n) for n in (50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60)}
check("dated wait: a doing item with a wake tomorrow and only dated steps reads as waiting, on a time until the wake, the mover kept for after it",
      v[50].state == _model.WAITING and v[50].wait.kind == "time" and v[50].wait.until == wk(24) and v[50].wait.post_wake_mover == "team-back", v[50])
check("dated wait: …the same item with one undated open step stays doing", v[51].state == _model.ALIVE, v[51])
check("dated wait: …a wake 30 minutes out stays doing", v[52].state == _model.ALIVE, v[52])
check("dated wait: …an ISO date and a prose date both count, and the item is listed as waiting", v[53].state == _model.WAITING and lst(53) == "waiting" and lst(51) == "agents" and lst(52) == "agents", (v[53], lst(53), lst(51)))
check("dated wait: …a step dated in the past or today, no open step, or a step dated before the wake's day stays doing",
      all(v[n].state == _model.ALIVE for n in (54, 55, 56, 57)), [v[n].state for n in (54, 55, 56, 57)])
check("dated wait: …with no wake, a stored expected_by and dated steps is work in hand (the stored time is not read); beside a wake it changes nothing, the wake decides",
      v[58].state == _model.ALIVE and v[59].state == _model.WAITING and v[59].wait.until == wk(24), (v[58], v[59]))
check("dated wait: …a bare sub-bullet is part of the step above it (one step, its earliest date)", v[60].state == _model.WAITING, v[60])
check("dated wait: …an item on hold is not relabeled (the hold already says it)", _dw.of(dict(rd(61, "g"), gid="g61"), now_) is None, None)
check("dated wait: derive and the stored state are unchanged (the guards read the item as stored)", _model.derive(dict(rd(50, "g"), gid="g50"), now_, after_open=lambda i: [], anchored=lambda i: False).state == _model.ALIVE and mt(50, "g").get("state") == "doing", None)
dw50 = _dw.of(dict(rd(50, "g"), gid="g50"), now_)
check("dated wait: the signature is stable across calls and moves with a dated line or the wake",
      _dw.signature(dw50) == _dw.signature(_dw.of(dict(rd(50, "g"), gid="g50"), now_ + 60)) and _dw.signature(dw50) != _dw.signature(_dw.of(dict(rd(53, "g"), gid="g53"), now_))
      and _dw.of(dict(rd(58, "g"), gid="g58"), now_) is None, None)
mls = "\n".join(server._model_lines(dict(rd(50, "g"), gid="g50")))
check("dated wait: get and brief say the board lists it as waiting until the wake, and why", "the board lists it as waiting until" in mls and "dated for later" in mls, mls)
check("dated wait: …an item that stays doing carries no such note", "the board lists it as waiting" not in "\n".join(server._model_lines(dict(rd(51, "g"), gid="g51"))), None)

# a date counts as a wait only when the step says it waits for it: a deadline or a reference date does not
g(62, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: land the PR by {prose(2)}")
g(63, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: due {prose(2)}, check the result")
g(64, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: after the review closed {prose(2)}, check the result")
g(65, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: wait until {prose(2)}, then check the result")
g(66, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: merge before {prose(2)}\nteam-back: {prose(2)} after the nightly run, check")   # one deadline step: the item stays doing
check("dated wait: a deadline or a reference date is no wait: 'by', 'due', 'closed' and 'before' leave the item doing",
      all(view_of(n).state == _model.ALIVE for n in (62, 63, 64, 66)), [view_of(n).state for n in (62, 63, 64, 66)])
check("dated wait: …'wait until <date>' is one", view_of(65).state == _model.WAITING, view_of(65))
# more references that are no wait: a deadline after a colon, a bracketed date, a date after a comma, a date then a dash, "from <date>"; a bracketed date after a waiting word is one
PROBES = {69: "finish by end of day, deadline: {d}", 70: "land the PR ({d})", 71: "land the PR, {d} at the latest", 72: "{d} - draft the release notes", 73: "review the logs from {d}"}
for n, t in PROBES.items():
    g(n, needs=[BACK], state="doing", wake=wk(24), next="team-back: " + t.format(d=prose(2)))
g(74, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: once the run finishes ({prose(2)}), verify")
LOOK = {75: "merge once CI is green ({d})", 76: "finish the notes after lunch (release {d})", 77: "finish the notes after lunch for the {i} release", 78: "wait for CI (the {i} build is old)"}
for n, t in LOOK.items():
    g(n, needs=[BACK], state="doing", wake=wk(24), next="team-back: " + t.format(d=prose(2), i=iso(2)))
g(79, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: after {prose(2)}, verify")
g(80, needs=[BACK], state="doing", wake=wk(24), next=f"team-back: wait until the {iso(2)}, then verify")
check("dated wait: a deadline after a colon, a bracketed date, a date after a comma, a date then a dash, and 'from <date>' are no wait",
      all(view_of(n).state == _model.ALIVE for n in PROBES), {n: view_of(n).state for n in PROBES})
check("dated wait: …a bracket ends the clause: 'once the run finishes (<date>)' is a missed wait, never a false one", view_of(74).state == _model.ALIVE, view_of(74))
check("dated wait: a waiting word further back is no wait ('merge once CI is green (<date>)', 'after lunch (release <date>)', 'after lunch for the <iso> release', 'wait for CI (the <iso> build is old)')",
      all(view_of(n).state == _model.ALIVE for n in LOOK), {n: view_of(n).state for n in LOOK})
check("dated wait: …'after <date>' and 'until the <iso>' (a waiting word right before the date, one filler word allowed) still wait", view_of(79).state == _model.WAITING and view_of(80).state == _model.WAITING, (view_of(79), view_of(80)))
# the year roll: on Jan 5th a step that names Dec 28th (past, finished) is read by states.named_dates as next December; a date that far past the wake's day is no wait
jan = datetime.datetime(2027, 1, 5, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=ZONE_HOURS))).timestamp()
g(67, needs=[BACK], state="doing", wake="2027-01-06T09:00", next="team-back: Dec 28th the run finished; verify it")
g(68, needs=[BACK], state="doing", wake="2027-01-06T09:00", next="team-back: after Jan 8th, verify it")
check("dated wait: on Jan 5th a yearless step about Dec 28th (read as next December) is no wait, while 'after Jan 8th' is one",
      _dw.of(dict(rd(67, "g"), gid="g67"), jan) is None and _dw.of(dict(rd(68, "g"), gid="g68"), jan) is not None, (_dw.of(dict(rd(67, "g"), gid="g67"), jan), _dw.of(dict(rd(68, "g"), gid="g68"), jan)))
# the brief counts the items the board lists as waiting for this reason
bf = render.Board(str(T / "store")).brief()
nd = sum(1 for n in range(50, 81) if (T / f"store/g/{n}.json").exists() and _dw.of(dict(rd(n, "g"), gid=f"g{n}"), time.time()) is not None)
check("dated wait: the brief says how many doing items are listed as waiting because every open step is dated for later, and what to do", f"{nd} of the doing items have a wake more than 1 h out and every open step dated for a later day" in bf and nd >= 4, (nd, [l for l in bf.splitlines() if "doing items" in l]))

# a step that names its date in words ("after the Nov 30th launch") on an item with no stored state (a wake and a mover read as doing), and an on-hold doing item with a wake
def md(n, full=False):                                                  # "Nov 4th" / "November 4th": the local day n days from the suite's start, month and day only
    t = time.gmtime(now0 + n * DAY + ZONE_OFFSET)
    return time.strftime("%B " if full else "%b ", t) + ordinal(t.tm_mday)
g(90, needs=[BACK], wake=wk(24 * 12), next=f"team-back: after the {md(12)} launch, check each job uses the key")                  # no stored state, the step names its day in words
g(91, needs=[BACK], wake=wk(24 * 12), next=f"team-back: after the {md(-10)} launch, check each job uses the key")                 # the named day is past
g(92, needs=[BACK], wake=wk(24 * 12), next="team-back: check each job uses the key")                                              # no date in the step
g(93, needs=[BACK], wake=wk(24 * 12), next=f"team-back: after the {md(12)} launch, check each job\nteam-back: tidy the notes")      # one dated step, one undated
g(94, needs=[BACK], wake=wk(24 * 12), next=f"team-back: after {md(12, True)}, check each job uses the key")                       # the month spelled out
g(95, needs=[BACK], wake=wk(24 * 12), next="team-back: wait for next week, then check each job")                                  # no month and day: never guessed
g(96, needs=[BACK], wake=wk(24 * 12), next=f"team-back: land the PR by {md(12)}")                                                  # a deadline, not a wait
g(97, needs=[BACK], wake=wk(24 * 12), after=["g3"], next=f"team-back: after the {md(12)} launch, check each job")                  # an open after link reads as blocked, never as a dated doing wait
w90 = view_of(90)
check("dated wait: an item with no stored state (a mover and a wake read as doing) whose only step says 'after the <Mon day> launch' reads as waiting on a time until the wake",
      w90.state == _model.WAITING and w90.wait.kind == "time" and w90.wait.until == wk(24 * 12) and w90.wait.post_wake_mover == "team-back" and w90.today == "doing" and "state" not in mt(90, "g"), w90)
check("dated wait: …the named day already past, no date in the step, one undated open step, or a step with no month and day stays alive",
      all(view_of(n).state == _model.ALIVE for n in (91, 92, 93, 95)), [view_of(n).state for n in (91, 92, 93, 95)])
check("dated wait: …the month spelled out ('after <Month> <day>') counts, a deadline ('by <Mon day>') does not, an open after link is no dated wait",
      view_of(94).state == _model.WAITING and view_of(96).state == _model.ALIVE and _dw.of(dict(rd(97, "g"), gid="g97"), now_) is None, (view_of(94), view_of(96)))
check("dated wait: …the item is listed as waiting and get names why", lst(90) == "waiting" and lst(92) == "agents" and "the board lists it as waiting until" in "\n".join(server._model_lines(dict(rd(90, "g"), gid="g90"))), (lst(90), lst(92)))
# a doing item on hold with a wake more than the hour ahead is a wait on that wake; no wake, a past wake or a wake within the hour leaves it alone
g(100, needs=[BACK], state="doing", hold=True, wake=wk(24), next="team-back: read the run on main, then the checks on later runs")
g(101, needs=[BACK], state="doing", hold=True, next="team-back: read the run on main")
g(102, needs=[BACK], state="doing", hold=True, wake=wk(-5), next="team-back: read the run on main")
g(103, needs=[BACK], state="doing", hold=True, wake=wk(0.5), next="team-back: read the run on main")
g(104, needs=["decision", BACK], state="doing", hold=True, wake=wk(24), next="team-back: read the run on main")      # his decision is asked: never on hold
g(105, needs=[BACK], state="doing", hold=True, wake=wk(24), expected_by=hrs(0.5), expected_reason="the build", next="team-back: read the run on main")   # far wake, a stored expected_by within the hour beside it (not read)
g(106, needs=["external"], state="doing", hold=True, wake=wk(24), next="team-back: read the run on main")             # a mover that is not a session
g(107, needs=[BACK], state="parked", hold=True, wake=wk(24), wait_basis={"text": f"visit {day(1)}", "wake": wk(24), "by": "x", "at": now0})    # a stored state of another kind beside the hold
w_a = view_of(100)
check("held wait: a stored doing item on hold with a wake tomorrow reads as waiting on a time until the wake, whatever its undated step says",
      w_a.state == _model.WAITING and w_a.wait.kind == "time" and w_a.wait.until == wk(24) and w_a.wait.post_wake_mover == "team-back" and lst(100) == "waiting" and w_a.wait.basis == "on hold until its wake", (w_a, lst(100)))
check("held wait: …a hold with no wake, a wake already past, or a wake within the hour is unchanged (alive)", all(view_of(n).state == _model.ALIVE for n in (101, 102, 103)), [view_of(n).state for n in (101, 102, 103)])
check("held wait: …a stored expected_by within the hour beside the wake is not read: the far wake on hold is a held wait all the same", view_of(105).state == _model.WAITING and _dw.held_wait(dict(rd(105, "g"), gid="g105"), now_) is not None, view_of(105))
check("held wait: …a mover that is not a session (external) gets no held wait", W.mover_of(rd(106, "g")["metadata"])["kind"] != "session" and _dw.held_wait(dict(rd(106, "g"), gid="g106"), now_) is None, W.mover_of(rd(106, "g")["metadata"]))
check("held wait: …a stored state other than doing beside a hold gets no held wait from this rule", _dw.held_wait(dict(rd(107, "g"), gid="g107"), now_) is None, None)
check("held wait: …an item whose needs hold decision is no held item", view_of(104).state == _model.ALIVE and not W.is_held(dict(rd(104, "g"), gid="g104")), view_of(104))
check("held wait: …the dated-step reading (dated_wait.of) still leaves a held item alone, and the stored model is unchanged",
      _dw.of(dict(rd(100, "g"), gid="g100"), now_) is None and _dw.held_wait(dict(rd(100, "g"), gid="g100"), now_) is not None and _dw.held_wait(dict(rd(101, "g"), gid="g101"), now_) is None
      and _model.derive(dict(rd(100, "g"), gid="g100"), now_, after_open=lambda i: [], anchored=lambda i: False).state == _model.ALIVE, None)
check("held wait: get says the board lists it as waiting until the wake and that it is on hold", "on hold until its wake" in "\n".join(server._model_lines(dict(rd(100, "g"), gid="g100"))), "\n".join(server._model_lines(dict(rd(100, "g"), gid="g100"))))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": state scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
