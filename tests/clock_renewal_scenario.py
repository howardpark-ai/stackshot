"""Scenario test for "no clock renewal without progress" — fixture data, no live store, no network, no server socket.

A session that pushes an item's wake or ask_by to a later time while the item's reason and its open steps are exactly as they were buys time without doing or saying anything: the
item keeps being re-dated and nobody sees it sit. The write is refused, and the refusal names the way out (change a step or the reason; or park the item, or use the event-wait form). Covered:

  * expected_by and expected_reason: a doing item (stored as fixture data: no call sets a state any more) carries no expected time, so there is no clock in them to renew: the retired fields are accepted and not stored, and are no reason either.
  * wake: a later wake with nothing else changed is refused (nothing written, the refusal names the park and the event-wait forms); with a changed step or reason, or a step marked done, accepted; a wait_reason
    is NOT a reason (it is not stored, any text would defeat the gate): refused, on _update and through the stackshot_update tool function (where the self-wait gate runs too); a first wake, an earlier one, the
    same one and a cleared one are accepted.
  * ask_by of an event wait: the same rule; its first setting (the event-wait form itself) is accepted.
  * the owner's words in the same write count as a reason only as a checked, recent Acked-by entry whose message is new on the write (unchecked, Reported-by and an already stored msg, whatever its quote, are refused).
  * a change to what the wait stands on (wait_kind, wait_event, wait_anchor, after) to a shape the item never held is progress; a flip back (A, B, A), the removal of after, and a changed
    post_wake_mover (the holder rules cover hand-offs) are not; a recycle wait aimed at another machine is the same shape (told by its verb); a new shape alone lets a clock push through
    twice in a row (metadata.clock_struct_n) and the third is refused, also for seven different real waits and for a return to a shape older than the five kept; a step change resets the count; an event wait's refusal does not advise the event-wait form it already uses; needs moved to decision is no hand-off.
  * a real hand-off (the effective holder, the stored mover else needs[0], resolved through the registry, becomes a session that is not the sender) is no renewal; setting the holder it already
    has, flipping it back, or writing the same session as a name and as an id (mover or needs) is refused.
  * the refusal fits the item: a parked item is told to give a new wait_basis, an item on a decision is not told to hold it, any other keeps the park and event-wait forms.
  * the wait_basis text of a park counts as the reason; a write of the server's own (not a session's) and [model] guards = false are not judged.

    tests/run-suite clock_renewal      → exit 0 / 1"""
import contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="clockrenewal-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the state checks, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)

from stackshot.service import gates
from stackshot.web import server
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
server._front_sender = lambda who: False
from stackshot.waits import waiting as W
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))
BACK = "team-back"
CFG = server._cfg.CFG.setdefault("model", {})
CFG.update(guards=True, pause=False)
mt = lambda i: rd(i)["metadata"]
raw = lambda i: (T / f"store/a/{i}.json").read_text()
def upd(i, sender=BACK, **kw):
    with server._session_write():
        return server._update(f"a{i}", sender=sender, **kw)
def refused_nw(name, i, f, *want):
    was = raw(i)
    refused(name, f, *want)
    check(name + " (nothing written)", raw(i) == was, None)
def doing(i, **kw):
    item(i, needs=[BACK], next="team-back: do the first thing\nteam-back: do the second thing", state="doing", wake=day(2), **kw)
FORMS = ("hold=true", "wait_basis", 'wait_kind="event"', "wait_event", "ask_by", "post_wake_mover")

# ================================================================ the retired expected_by and expected_reason: no clock to renew
doing(1)
upd(1, expected_by=hrs(5))
check("retired: a doing item's expected_by is accepted with nothing else changed (it is no clock) and not stored", "expected_by" not in mt(1) and wk_(mt(1)) == day(2), mt(1))
upd(1, expected_by=hrs(9), expected_reason="the second thing is running on the build box")
check("retired: …neither is a new expected_reason: not stored", "expected_by" not in mt(1) and "expected_reason" not in mt(1), mt(1))
refused_nw("wake: pushing a doing item's wake out with nothing else changed is refused, naming the park and the event-wait forms; the retired fields beside it are no reason", 1, lambda: upd(1, wake=day(5), expected_by=hrs(5), expected_reason="running the first thing now"),
           "Refused", "clock pushed out", "wake", *FORMS)
refused_nw("wake: …and a re-sent next (the same lines) is no change of a step", 1, lambda: upd(1, wake=day(5), next="team-back: do the first thing\nteam-back: do the second thing"), "clock pushed out")
upd(1, wake=day(5), done=[1])
check("wake: a push-out with a step marked done is accepted", wk_(mt(1)) == day(5), mt(1))
upd(1, wake=day(6), next="team-back: do a third thing")
check("wake: …with a new line of next accepted", wk_(mt(1)) == day(6), mt(1))
refused_nw("wake: a wait_reason on the write is no reason (any text would defeat the gate)", 1, lambda: upd(1, wake=day(7), wait_reason="x" * 60), "clock pushed out", "does not count")

doing(90, owner=U[BACK])
refused_nw("wake: a reword alone is no progress (it only restates the step), so a later wake with it is refused", 90, lambda: upd(90, wake=day(5), reword={2: "team-back: do the next thing"}), "clock pushed out", "wake")
upd(90, reword={2: "team-back: do the next thing"})
check("wake: …a reword without a later wake is accepted, and the wake stays", wk_(mt(90)) == day(2) and mt(90)["next"] == "team-back: do the first thing\nteam-back: do the next thing", mt(90))
upd(90, wake=day(5), reword={2: "team-back: do the last thing"}, done=[1])
check("wake: …a reword beside a step marked done is progress by the mark", wk_(mt(90)) == day(5) and mt(90)["next"] == "team-back: do the last thing", mt(90))

# ================================================================ wake
item(10, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("wake: a later wake with nothing else changed is refused", 10, lambda: upd(10, wake=day(5)), "clock pushed out", "wake", *FORMS)
upd(10, wake=day(5), done=[1])
check("wake: …with a step marked done accepted", wk_(mt(10)) == day(5), mt(10))
upd(10, wake=day(6), description="- Goal: A thing, its reason changed\n- It lives here\n- Done when done")
check("wake: …with a new description accepted", wk_(mt(10)) == day(6), mt(10))
upd(10, wake=day(4))
check("wake: an earlier wake is accepted", wk_(mt(10)) == day(4), mt(10))
upd(10, wake=day(4))
check("wake: the same wake again is accepted", wk_(mt(10)) == day(4), mt(10))
refused_nw("wake: a later time on the same day is a push-out too", 10, lambda: upd(10, wake=f"{day(4)}T18:00"), "clock pushed out")
upd(10, clear_wake=True)
check("wake: clearing it is accepted", "wake" not in mt(10), mt(10))
upd(10, wake=day(7))
check("wake: a wake set again after it was cleared is a first wake: accepted", wk_(mt(10)) == day(7), mt(10))
item(11, needs=[BACK], next="team-back: do the thing")
upd(11, wake=day(2))
check("wake: the first wake an item gets is accepted", wk_(mt(11)) == day(2), mt(11))

# a park: the basis text is the reason (a basis is bound to its wake and names a date from it, so a later wake carries a new one)
item(12, needs=[BACK], next="team-back: wait for it", hold=True, wake=day(3), wait_basis={"text": f"the vendor ships on {day(3)}", "wake": day(3), "by": "team-back", "at": now0})
upd(12, wake=day(5), wait_basis=f"the vendor moved the ship day to {day(5)}, a message from them says so")
check("park: a later wake with new basis text is accepted", wk_(mt(12)) == day(5), mt(12))

# ================================================================ the tool function: the self-wait gate and this gate both run
from stackshot.waits import self_wait as SW
CALLS = []
def fake_run(message):
    CALLS.append(message)
    return {"status": "ok", "text": json.dumps({"can_do_now": False, "reason": "the vendor ships on that day"})}
SW._run = fake_run
item(15, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
was15 = raw(15)
try:
    server.stackshot_update("a15", sender=BACK, wake=day(5), wait_reason="x" * 60); check("tool: a later wake with a long wait_reason is refused", False, mt(15))
except server.ToolError as e:
    check("tool: a later wake with a long wait_reason is refused by the clock gate, after the self-wait gate passed it", "clock pushed out" in str(e) and len(CALLS) == 1, (str(e), len(CALLS)))
check("tool: …and nothing is written", raw(15) == was15, None)
server.stackshot_update("a15", sender=BACK, wake=day(5), done=[1], wait_reason="the vendor ships on that day, not before")
check("tool: …with a step marked done accepted", wk_(mt(15)) == day(5), mt(15))

# ================================================================ the owner's words in the same write are a reason
_real_verify = gates._said_verify
VERIFY = {"on": True}      # True: the transcript check passes (a checked entry); False: the real check, which finds no transcript here (an unchecked entry)
gates._said_verify = lambda sess, spec, *a, **k: (sess, {"code": "ok", "ts": time.time(), "checked": True, "detail": "", "prompt_source": ""}) if VERIFY["on"] else _real_verify(sess, spec, *a, **k)
def said(tag="Acked-by", quote="push it out a few days", msg="11111111-1111-4111-8111-000000000001"): return [{"tag": tag, "quote": quote, "msg": msg, "session": U["home-owner"]}]
doing(40)
refused_nw("said: a push-out with no words is refused", 40, lambda: upd(40, wake=day(4)), "clock pushed out")
refused_nw("said: …an Acked-by entry that is unchecked (no readable transcript) is refused", 40, lambda: (VERIFY.update(on=False), upd(40, wake=day(4), said=said()))[1], "clock pushed out")
VERIFY["on"] = True
refused_nw("said: …a checked Reported-by entry is refused", 40, lambda: upd(40, wake=day(4), said=said("Reported-by")), "clock pushed out")
upd(40, wake=day(4), said=said())
check("said: …a checked Acked-by entry, new on this write, is accepted", wk_(mt(40)) == day(4) and mt(40).get("said"), mt(40))
refused_nw("said: …the same quote sent again does not count a second time", 40, lambda: upd(40, wake=day(5), said=said()), "clock pushed out")
refused_nw("said: …the same message with a new quote does not count either (the message is spent)", 40, lambda: upd(40, wake=day(5), said=said(quote="and a few more days after that")), "clock pushed out")
upd(40, wake=day(5), said=said(quote="and a few more days after that", msg="11111111-1111-4111-8111-000000000002"))
check("said: …a second message counts", wk_(mt(40)) == day(5), mt(40))

# ================================================================ a new holder: a changed mover or first session in needs is no renewal
TWO = "team-back: do the first thing\nteam-back: do the second thing"
doing(41)
upd(41, wake=day(4), needs=["home-other"], next="home-other: do the first thing\nhome-other: do the second thing")
check("holder: a real hand-off in needs (back to other, by back) is accepted: the new holder's own clock", wk_(mt(41)) == day(4) and mt(41)["needs"][0] == "home-other", mt(41))
refused_nw("holder: …the sender taking it back with a later time (the flip loop) is refused", 41, lambda: upd(41, wake=day(5), needs=[BACK]), "clock pushed out")
upd(41, sender="home-other", wake=day(5), needs=[BACK])
check("holder: …while the other session handing it back is a real hand-off: accepted", wk_(mt(41)) == day(5) and mt(41)["needs"][0] == BACK, mt(41))
item(42, mover=BACK, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("holder: mover set to the holder it already has, with a later wake, is refused", 42, lambda: upd(42, wake=day(5), mover=BACK), "clock pushed out")
refused_nw("holder: …the same holder written as its id is refused", 42, lambda: upd(42, wake=day(5), mover=U[BACK]), "clock pushed out")
upd(42, wake=day(5), mover="home-other")
check("holder: a changed mover is accepted", wk_(mt(42)) == day(5) and mt(42)["mover"] == "home-other", mt(42))
item(43, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("holder: no mover stored, the first session in needs is the holder: mover=<it> is refused", 43, lambda: upd(43, wake=day(5), mover=BACK), "clock pushed out")
item(44, mover=U[BACK], needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("holder: a stored id and the same session's name is refused", 44, lambda: upd(44, wake=day(5), mover=BACK), "clock pushed out")
item(45, needs=[BACK, "home-other"], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("holder: reordering needs so the id of the same holder leads is refused", 45, lambda: upd(45, wake=day(5), needs=[U[BACK], "home-other"]), "clock pushed out")

# ================================================================ the refusal fits the item
item(50, needs=["decision"], state="your-call", ask="Park it or drop it?", next="team-back: wait for his call\nteam-back: then act", wake=day(3))
refused_nw("text: an item on a decision is not told to hold it", 50, lambda: upd(50, wake=day(5)), "clock pushed out", "cannot be held")
try:
    upd(50, wake=day(5))
except Exception as e:
    check("text: …no hold=true, no event-wait form in it", "hold=true" not in str(e) and "wait_kind" not in str(e), str(e))
item(51, needs=[BACK], next="team-back: wait for it\nteam-back: then check", hold=True, wake=day(3), wait_basis={"text": f"the vendor ships on {day(9)}", "wake": day(3), "by": "team-back", "at": now0})
try:
    upd(51, wake=day(5), wait_basis=f"the vendor ships on {day(9)}"); check("text: a parked item's push-out is refused", False, mt(51))
except Exception as e:
    m = str(e)
    check("text: a parked item is told to lead with a new wait_basis, and not to park it again", "clock pushed out" in m and "Change something real in the same write: a new wait_basis" in m and "park it (" not in m, m)

# ================================================================ ask_by of an event wait
item(20, wait_kind="event", wait_event="recycle", ask_by=day(3), post_wake_mover=BACK, needs=[], mover="none", next="team-back: wait for the recycle\nteam-back: then check it")
refused_nw("ask_by: pushing the backstop out with nothing else changed is refused", 20, lambda: upd(20, ask_by=day(6)), "clock pushed out", "ask_by")
upd(20, ask_by=day(6), done=[1])
check("ask_by: …with a step marked done accepted", ab_(mt(20)) == day(6), mt(20))
try:
    upd(20, ask_by=day(6))
except Exception as e:
    check("text: an event wait is told to change what it stands on, not to use the event-wait form again", "a different wait_event or wait_anchor" in str(e) and "park it (" not in str(e), str(e))
item(22, wait_kind="event", wait_event="recycle", ask_by=day(3), post_wake_mover=BACK, needs=[], mover="none", next="team-back: wait for the recycle\nteam-back: then check it")
upd(22, wait_event="fleet_op any", ask_by=day(6))
check("wait structure: a changed wait_event with a later ask_by is accepted", ab_(mt(22)) == day(6) and mt(22)["wait_event"] == "fleet_op any", mt(22))
item(23, wait_kind="event", wait_event="recycle", ask_by=day(3), post_wake_mover=BACK, needs=[], mover="none", next="team-back: wait for the recycle\nteam-back: then check it")
refused_nw("wait structure: a changed post_wake_mover with a later ask_by is refused (who takes it after is not what the wait stands on)", 23, lambda: upd(23, post_wake_mover="home-other", ask_by=day(6)), "clock pushed out")
refused_nw("wait structure: …the wait_event flipped back to the first one (A, B, A) with a later ask_by is refused", 22, lambda: upd(22, wait_event="recycle", ask_by=day(8)), "clock pushed out")
check("wait structure: …the item still holds B, and the record keeps both shapes", mt(22)["wait_event"] == "fleet_op any" and len(mt(22).get("clock_struct") or []) == 2, mt(22))
item(26, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
item(27, needs=[BACK], next="team-back: the other blocker")
item(24, needs=[BACK], next="team-back: the blocker")
upd(26, wake=day(4), after=["a24"])
check("wait structure: after A (first) with a later wake is accepted", wk_(mt(26)) == day(4), mt(26))
upd(26, wake=day(5), after=["a27"])
check("wait structure: …after B, a shape never held, with a later wake is accepted", wk_(mt(26)) == day(5), mt(26))
refused_nw("wait structure: …after A again (A, B, A) with a later wake is refused", 26, lambda: upd(26, wake=day(6), after=["a24"]), "clock pushed out")
refused_nw("wait structure: …clearing after with a later wake is refused (a removal is no progress)", 26, lambda: upd(26, wake=day(6), clear_after=True), "clock pushed out")
W = lambda k: f"{day(3)}T{k:02d}:00"      # a later wake each time within the same day (a wake may be at most 7 days out)
# the count of pushes a new wait shape alone lets through: at most two in a row
for n_ in range(70, 77): item(n_, needs=[BACK], next=f"team-back: blocker {n_}")
item(60, wait_kind="event", wait_event="recycle", ask_by=day(3), post_wake_mover=BACK, needs=[], mover="none", next="team-back: wait for the recycle\nteam-back: then check it")
for k_, m_ in enumerate(("far-host", "far-host-2", "far-host-3")):
    refused_nw(f"count: a recycle wait aimed at another machine ({m_}) is the same shape (told by its verb): refused", 60, lambda m_=m_, k_=k_: upd(60, wait_event=f"recycle {m_}", ask_by=day(4 + k_)), "clock pushed out")
item(61, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
for k_ in range(7):
    if k_ < 2:
        upd(61, wake=W(1 + k_), after=[f"a{70 + k_}"])
        check(f"count: different real wait #{k_ + 1} in a row is let through", wk_(mt(61)) == W(1 + k_) and mt(61).get("clock_struct_n") == k_ + 1, mt(61))
    else:
        refused_nw(f"count: different real wait #{k_ + 1} in a row is refused (the third and after)", 61, lambda k_=k_: upd(61, wake=W(1 + k_), after=[f"a{70 + k_}"]), "clock pushed out", "in a row", "Change something real")
item(62, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
upd(62, wake=W(1), after=["a70"]); upd(62, wake=W(2), after=["a71"])
check("count: two passes are counted", mt(62).get("clock_struct_n") == 2, mt(62))
upd(62, wake=W(3), next="team-back: a third thing")
check("count: a step change resets it", not mt(62).get("clock_struct_n"), mt(62))
upd(62, wake=W(4), after=["a72"])
check("count: …and the next new shape alone is let through again (count 1)", wk_(mt(62)) == W(4) and mt(62).get("clock_struct_n") == 1, mt(62))
item(63, needs=[BACK], next="team-back: step 0", wake=day(3))
for k_ in range(7):
    upd(63, wake=W(1 + k_), after=[f"a{70 + k_}"], next=f"team-back: step {k_ + 1}")      # a step changes with each: the count stays 0 and the record fills past 5
check("count: seven shapes behind steps leave the record at five and the count at 0", len(mt(63)["clock_struct"]) == 5 and not mt(63).get("clock_struct_n"), mt(63))
upd(63, wake=W(11), after=["a70"])
upd(63, wake=W(12), after=["a71"])
refused_nw("count: …a return to a shape older than the last five is a new shape, and the count caps it at the third", 63, lambda: upd(63, wake=W(13), after=["a72"]), "clock pushed out", "in a row")
item(25, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("wait structure: …the same wake push with no after is refused", 25, lambda: upd(25, wake=day(5)), "clock pushed out")
upd(25, wake=day(5), after=["a24"])
check("wait structure: an added after with a later wake is accepted", wk_(mt(25)) == day(5) and mt(25).get("after"), mt(25))
item(46, needs=[BACK], next="team-back: do the thing\nteam-back: and the other thing", wake=day(3))
refused_nw("holder: needs moved to decision is no hand-off (it holds no session)", 46, lambda: upd(46, wake=day(5), needs=["decision"], ask="Decide: keep it parked or drop it · Recommend: yes · Stakes: low · By: tomorrow"), "clock pushed out")
item(21, mover=BACK, next="team-back: do the thing")
upd(21, wait_kind="event", wait_event="recycle", ask_by=day(4), post_wake_mover=BACK, mover="none")
check("ask_by: the event-wait form itself (a first ask_by) is accepted", ab_(mt(21)) == day(4) and mt(21)["wait_kind"] == "event", mt(21))

# ================================================================ what is not judged
doing(30)
server._update("a30", sender=BACK, wake=day(4))
check("not judged: a write of the server's own (not a session's) pushing the wake out", wk_(mt(30)) == day(4), mt(30))
doing(31)
CFG["guards"] = False
upd(31, wake=day(4))
check("not judged: [model] guards = false", wk_(mt(31)) == day(4), mt(31))
CFG["guards"] = True
doing(32)
upd(32, priority="p2")
check("not judged: a write that moves no clock", wk_(mt(32)) == day(2), mt(32))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
