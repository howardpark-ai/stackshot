"""Scenario test for the server-side state checks — fixture data, no live store, no network, no server socket.

No call sets a state word any more (the inputs state, clear_state, party, chase, end and proof are retired: tests/retired_inputs_scenario.py covers the refusal); an item that stores one is written here as fixture data and still read as before.

  3  Oliver's step hidden under the agent: a first line of next that opens with Oliver, AE or "you" while the state (stored or derived) is doing, queued, blocked or
     verifying. A create or an update that touches next, the state, needs or the step and would leave the item in that shape is refused (nothing is written);
     the fix is step=… (it stores the your-step state), or needs=decision with an ask. Any other write to an item already in that shape (a legacy item) is allowed, and get,
     the brief and the write's reply keep the note. Quiet under your-step, your-call, outside, parked, and for a closed item.
  4  Re-parking forever: a write that moves the wake of a parked item with nothing else changed counts (metadata.repark); any other change
     resets it; the third in a row is refused (and writes nothing), unless the owner's words stand behind it. A stored verifying item's end date is its wait like a wake (waiting.py): no separate wake,
     no idle nudge, no stale mark before it, and past it the item shows as past due (no call sets or moves an end any more, so its 30-day limit and its re-park count are not exercised).
  5  Stale next: (a) a write by a session that is neither the owner nor named by next, which changes needs, state, hold, wake or after and not next, sets metadata.next_stale, shown in
     get and the brief until a write passes next; (b) a next that names a date that has passed is flagged the same way.
  6  A decision asked again: a write that puts needs=decision back within 60 minutes of the owner's last answer on the item is refused unless the ask line changed.
  7  states.hint is gone with the call that stored a state; the client items read and the hook's board question carry no hint, and the items row has state and
     state_fields only for an item that stores a state.

    tests/run-suite state_checks        → exit 0 / 1"""
import contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="statechecks-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
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
DESC = "- A thing\n- It lives here\n- Done when done"
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
from stackshot.web import server; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.model import states
from stackshot.projects import pages as pg
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told_ = []
server._tell_woken = lambda gid, owner, note, tag="wake": told_.append((tag, gid, owner, note))
server._front_sender = lambda who: False      # kept stubbed: this suite sets a reminder wake on an alive item another session moves, as home-front, to touch a state field; the real front test would refuse it (suite watch covers the rule)
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # an expected_by n hours after the suite started (a time of day)
BACK = "team-back"
def upd(i, sender="home-front", **kw): return server._update(f"a{i}", sender=sender, **kw)
mt = lambda i: rd(i)["metadata"]
raw = lambda i: (T / f"store/a/{i}.json").read_text()
def refused_nw(name, i, f, *want):
    """refused with the words, and the item's file is byte for byte as it was"""
    was = raw(i)
    refused(name, f, *want)
    check(name + " (nothing written)", raw(i) == was, None)
get = lambda i: server.stackshot_get(f"a{i}")
ASK = "Decide: ship the thing now · Recommend: ship it · Stakes: a week of delay · By: no date"
ASK2 = "Decide: ship the thing next week · Recommend: ship it next week · Stakes: two weeks of delay · By: no date"
TODAY_D = server._pages.zone_now().date()
NOTE3 = "note: next names Oliver but the state is {s}: pass step=… (or needs=decision with an ask)"

# ================================================================ 3. Oliver's step hidden under the agent
item(1, needs=[BACK], next="Oliver: run `gh pr merge 241 --squash`")
check("3: a derived doing with a next that opens with Oliver draws the note in get", NOTE3.format(s="doing") in get(1), get(1))
refused_nw("3: a write that changes needs and leaves that shape is refused, naming the fix", 1, lambda: upd(1, needs=[BACK, "home-other"]),
           "Refused", "Oliver's step", "state is doing", "Pass step=<his step in one line>", "needs=decision with an ask", "Nothing was written")
out = upd(1, priority="p2")
check("3: …an unrelated write to the legacy item (a priority) is allowed, and its reply keeps the note", NOTE3.format(s="doing") in out and "state" not in mt(1), out)
out = upd(1, description="- A thing, reworded\n- It lives here\n- Done when done")
check("3: …a description rewrite too", NOTE3.format(s="doing") in out, out)
item(2, needs=[BACK], next="AE: try it on the phone")
check("3: AE opens a line too; a derived doing (a builder in needs) is an agent's state", NOTE3.format(s="doing") in get(2), get(2))
item(3, needs=[BACK], next="- you: check the link\nteam-back: then merge", after=["a2"])
check("3: a list marker is skipped, and you opens a line; a derived blocked is an agent's state", NOTE3.format(s="blocked") in get(3), get(3))
item(4, needs=[BACK], next="AE: check the link", state="verifying", proof="the link opens", end=day(5))
check("3: a stored verifying is an agent's state", NOTE3.format(s="verifying") in get(4), get(4))
item(5, needs=[], next="Oliver: run `x y`", state="your-step", step="run `x y`")
check("3: quiet under your-step", "next names" not in get(5), get(5))
item(6, needs=["decision"], next="Oliver: decide", ask=ASK)
check("3: …under a derived your-call", "next names" not in get(6), get(6))
item(7, needs=["external"], next="Oliver: nothing yet")
check("3: …under a derived outside", "next names" not in get(7), get(7))
item(8, needs=[BACK], next="Oliver: later", hold=True, wake=day(3))
check("3: …under a derived parked (a hold)", "next names" not in get(8), get(8))
item(9, needs=[BACK], next="team-back: build it for Oliver")
check("3: …when next opens with an agent (Oliver mid-line is no step of his)", "next names" not in get(9), get(9))
item(10, needs=[BACK], next="Oliversville is a place")
check("3: …and a word that only starts with Oliver is no name", "next names" not in get(10), get(10))
for n_, t_ in ((12, "Oliver's call is pending, build meanwhile"), (13, "AE-UX port: build it"), (14, "Oliver approved the plan; build it"), (15, "You can build it now")):
    item(n_, needs=[BACK], next=t_)
    check(f"3: …a narrative opener is no step of his ({t_[:24]!r})", "next names" not in get(n_), get(n_))
item(16, needs=[BACK], next="Oliver to run the merge")
check("3: …but `Oliver to …` is", NOTE3.format(s="doing") in get(16), get(16))
check("3: the opener rule, as a function", [states.next_names_owner(x) for x in ("Oliver: x", "home: x", "AE: x", "you: x", "You: x", "オリバー: x", "AE to x", "Oliver approved x", "Oliver's x", "AE-UX x", "you can x")] == ["Oliver", "", "Oliver", "Oliver", "Oliver", "Oliver", "Oliver", "", "", "", ""], None)
item(11, status="completed", needs=[], next="Oliver: closed")
check("3: …and a closed item", "next names" not in server._fmt({**rd(11), "gid": "a11"}), None)
b = server.stackshot_brief()
check("3: the brief carries it for items 1 to 4 and 16 (five open items name Oliver under an agent's state)", b.count("next names Oliver but the state is") == 5, b.count("next names Oliver but the state is"))
# the refusal on create and update, the fix accepted, and a legacy item fixed step by step
CR = lambda **kw: server._create(subject="[home] oliver step", description=DESC, project="projects/alpha", owner="home-front", **kw)
was_ids = sorted(p_.name for p_ in (T / "store/a").iterdir())
refused("3: a create whose next opens with Oliver under a derived doing is refused, naming the fix", lambda: CR(next="Oliver: merge the PR", needs=[BACK]),
        "Refused", "Oliver's step", "state is doing", "needs=decision with an ask", "open next with the agent who takes the step", "Nothing was written")
try: CR(next="Oliver: merge the PR", needs=[BACK]); _cr_msg = ""
except Exception as e_: _cr_msg = str(e_)
check("3: …a create names no state or step (it has no such parameter)", _cr_msg and "state=your-step" not in _cr_msg and "step=" not in _cr_msg, _cr_msg)
check("3: …and the create wrote nothing", sorted(p_.name for p_ in (T / "store/a").iterdir()) == was_ids, None)
refused("3: …an `AE:` opener too", lambda: CR(next="AE: check the link", needs=[BACK], priority="p2"), "Refused", "Oliver's step")
out = CR(next="Oliver: decide", needs=["decision"], ask=ASK)
check("3: …the fix on a create (needs=decision and an ask) is accepted, with no note", out.startswith("created") and "next names" not in out, out)
out = CR(next="team-back: build it for Oliver", needs=[BACK])
check("3: …and a next that opens with an agent is accepted", out.startswith("created") and "next names" not in out, out)
item(30, needs=[BACK], next="Oliver: merge the PR")
refused_nw("3: an update that writes a next opening with Oliver under an agent's state is refused", 30, lambda: upd(30, next="AE: merge the PR now"), "Refused", "state is doing")
refused_nw("3: …a write that changes needs and leaves that shape is refused", 30, lambda: upd(30, needs=[BACK, "home-other"]), "Refused", "state is doing")
out = upd(30, step="merge the PR")
check("3: the fix is accepted: step=… (it stores the your-step state), and the note is gone", mt(30).get("state") == "your-step" and "next names" not in out and "Refused" not in out, out)
item(32, needs=[BACK], next="Oliver: merge the PR")
out = upd(32, next="team-back: build it")
check("3: …a mover fixes it step by step: a next that opens with an agent is accepted", mt(32)["next"].startswith("team-back") and "next names" not in out, out)
item(33, needs=[BACK], next="Oliver: merge the PR")
out = upd(33, needs=["decision"], ask=ASK)
check("3: …needs=decision with an ask turns the derived state into your-call, accepted", "Refused" not in out and "next names" not in out, out)
item(34, needs=[BACK], next="Oliver: merge the PR")
out = upd(34, due=day(6))
check("3: a write that touches none of next, state, needs or step (a due date) is allowed on a legacy item, with the note", NOTE3.format(s="doing") in out and mt(34)["due"] == day(6), out)
check("3: the note names the fix: pass step, or needs=decision with an ask", "pass step=… (or needs=decision with an ask)" in get(2), get(2))

# the board item review: another session's Oliver line stays first (nextlines keeps each writer's lines at their place), so a later write by a different session is refused naming the line's writer and the exits
item(200, needs=[BACK], state="doing", expected_by=hrs(2), next="Oliver: x")      # the line's writer is the keeper of record, U["home-front"] (no writer stored)
refused_nw("3: another session's Oliver line first under a stored doing: a write of needs by a different session is refused, naming the line's writer and the exits", 200,
           lambda: upd(200, sender="home-stew", needs=[BACK, "home-other"]),
           "Refused", "state is doing", "was written by", U["home-front"], "Drop the step (dropped=[its number])", "clear_next=true", "pass step=<his step in one line>", "Mark it done only when")
try: upd(200, sender="home-stew", needs=[BACK, "home-other"]); _x_msg = ""
except Exception as e_: _x_msg = str(e_)
check("3: …and it does not advise opening next with an agent", _x_msg and "open next with" not in _x_msg, _x_msg)
out = upd(200, sender="home-stew", needs=[BACK, "home-other"], clear_next=True, next="home-stew: build it")
check("3: …the writer-neutral exit works: clear_next=true", "Refused" not in out and mt(200).get("next", "").startswith("home-stew"), (out, mt(200)))
item(201, needs=[BACK], state="doing", expected_by=hrs(2), next="Oliver: x\nteam-back: build it")
out = upd(201, sender="home-stew", needs=[BACK, "home-other"], dropped=[1])
check("3: …and so does marking that line dropped", "Refused" not in out and "Oliver: x" not in str(mt(201).get("next", "")), (out, mt(201)))
item(202, needs=[BACK], state="your-step", step="x", next="Oliver: x")
out = upd(202, sender="home-stew", needs=[BACK, "home-other"])
check("3: a stored your-step item with a Oliver line and a needs write stays allowed", "Refused" not in out and mt(202).get("state") == "your-step", out)

# ================================================================ 4. re-parking
BAS = f"visit on {day(20)}"          # a time wait carries a reason: the same one for every move of the wake
item(20, needs=[BACK])
upd(20, hold=True, wake=day(2), wait_basis=BAS)
check("4: the first park is not a re-park (no counter)", "repark" not in mt(20), mt(20))
upd(20, wake=day(3), wait_basis=BAS)
check("4: moving the wake of a parked item with nothing else changed is the first re-park", mt(20).get("repark") == 1 and mt(20)["wake"] == day(3), mt(20))
upd(20, wake=day(4), wait_basis=BAS)
check("4: …the second", mt(20).get("repark") == 2 and mt(20)["wake"] == day(4), mt(20))
refused_nw("4: …the third in a row is refused, saying to bring it to Oliver", 20, lambda: upd(20, wake=day(5), wait_basis=BAS),
           "re-parked 2 times in a row with nothing else changed", "third move of its wake", "needs=decision and an ask", "said=[")
check("4: …the item still holds the second wake and the count", mt(20)["wake"] == day(4) and mt(20)["repark"] == 2, mt(20))
upd(20, next="team-back: look at it once more")
check("4: a next edit changes nothing in the wait: the count stays (only the structured fields count)", mt(20).get("repark") == 2, mt(20))
refused_nw("4: …and the third move is still refused after it", 20, lambda: upd(20, wake=day(5), wait_basis=BAS), "third move of its wake")
upd(20, needs=["home-other"])
check("4: a change of a structured field (needs) resets the count", "repark" not in mt(20), mt(20))
upd(20, wake=day(5), wait_basis=BAS); upd(20, wake=day(6), wait_basis=BAS)
check("4: …and it counts from the start again", mt(20).get("repark") == 2, mt(20))
upd(20, wake=day(2), wait_basis=BAS)
check("4: a pull-in to an earlier day neither counts nor resets", mt(20).get("repark") == 2 and mt(20)["wake"] == day(2), mt(20))
upd(20, wake=f"{day(2)}T18:00", wait_basis=BAS)
check("4: …nor does a time of day on the same day", mt(20).get("repark") == 2 and mt(20)["wake"] == f"{day(2)}T18:00", mt(20))
upd(20, description="- A thing\n- It lives somewhere else\n- Done when done")
check("4: a description change changes nothing in the wait: the count stays", mt(20).get("repark") == 2, mt(20))
upd(20, needs=[BACK])
check("4: …a structured change resets it", "repark" not in mt(20), mt(20))
upd(20, wake=day(3), wait_basis=BAS); upd(20, wake=day(4), wait_basis=BAS)
# his words: an answer of his on the item since it last moved lifts the check and resets the count
it = rd(20); it["metadata"]["answers"] = [{"ts": time.time() + 5, "kind": "comment", "text": "park it again, nothing has changed", "via": "board"}]
(T / "store/a/20.json").write_text(json.dumps(it))
upd(20, wake=day(5), wait_basis=BAS)
check("4: his words on the item let a third re-park through, and reset the count", mt(20)["wake"] == day(5) and "repark" not in mt(20), mt(20))
item(21, needs=[BACK], hold=True, wake=day(3), wait_basis={"text": BAS, "wake": day(3), "by": "x", "at": now0})
upd(21, wake=day(4), wait_basis=BAS); upd(21, wake=day(5), wait_basis=BAS)
refused_nw("4: a stored hold counts the same", 21, lambda: upd(21, wake=day(6), wait_basis=BAS), "third move of its wake")
item(22, needs=[BACK], hold=True, wake=day(3), wait_basis={"text": BAS, "wake": day(3), "by": "x", "at": now0})
upd(22, wake=day(4), wait_basis=BAS); upd(22, hold=True)
check("4: a write that moves nothing leaves the count as it was", mt(22).get("repark") == 1, mt(22))
upd(22, wake=day(5), wait_basis=BAS)
check("4: …and the next push-out is the second", mt(22).get("repark") == 2, mt(22))
item(23, needs=[BACK])
upd(23, wake=day(3)); upd(23, wake=day(4)); upd(23, wake=day(5)); upd(23, wake=day(6))
check("4: a wake with no hold is a reminder, not a park: never counted", "repark" not in mt(23) and mt(23)["wake"] == day(6), mt(23))

# a changed wait_basis text is no structural change; cap_ok words are not
item(24, needs=[BACK])
upd(24, hold=True, wake=day(20), wait_basis=f"visit on {day(40)}")
upd(24, wake=day(21), wait_basis=f"visit on {day(40)}"); upd(24, wake=day(22), wait_basis=f"visit on {day(40)}")
check("4: the same basis text kept across moves: counted (the basis moves with the wake, its text does not change)", mt(24).get("repark") == 2, mt(24))
refused_nw("4: …a changed basis text on the third move is no structural change (only the structured fields count): still refused", 24,
           lambda: upd(24, wake=day(23), wait_basis=f"visit moved to {day(41)}"), "third move of its wake")
item(25, needs=[BACK], hold=True, wake=day(20), wait_basis={"text": f"visit on {day(40)}", "wake": day(20), "by": "x", "at": now0})
upd(25, wake=day(21), wait_basis=f"visit on {day(40)}"); upd(25, wake=day(22), wait_basis=f"visit on {day(40)}")
refused_nw("4: …three moves with the same basis text are refused as before", 25, lambda: upd(25, wake=day(23), wait_basis=f"visit on {day(40)}"), "third move of its wake")

# verifying (a stored one, fixture data: no call sets an end or a state any more): the end date is the wait
item(30, needs=[BACK], state="verifying", proof="one real stuck-pane notice arrives", end=day(25))
check("4: a stored verifying end 25 days out reads with no wake (the cap on a wake does not apply to an end)", mt(30)["end"] == day(25) and "wake" not in mt(30), mt(30))
w = W.compute({**rd(30), "gid": "a30"}, time.time())
check("4: …the end is the item's expected-by (the end of that day), its wait is `end`, and it is not overdue", w["wait"] == "end" and not w["overdue"]
      and abs(w["expected_by"] - W.due_epoch(day(25))) < 1 and w["mover"]["kind"] == "session", w)
upd(30, priority="p2")
check("4: …a write that moves nothing it stands on keeps the stored state, proof and end, and counts no re-park", mt(30)["state"] == "verifying" and mt(30)["end"] == day(25) and mt(30)["proof"] == "one real stuck-pane notice arrives" and "repark" not in mt(30), mt(30))
# an end that has passed: overdue
item(33, needs=[BACK], state="verifying", proof="p", end=day(-1))
w = W.compute({**rd(33), "gid": "a33"}, time.time())
check("4: a verifying item past its end is overdue, kind `end`", w["wait"] == "end" and w["overdue"], w)
# a verifying item with a wake of its own: the wake is read as before
item(34, needs=[BACK], state="verifying", proof="p", end=day(20), wake=day(2), hold=False)
w = W.compute({**rd(34), "gid": "a34"}, time.time())
check("4: …a wake of its own (an explicit reminder) is still read as a wake", w["wait"] == "wake", w)
# the item stays fresh until its end: render.freshness reads the end as a wait
r30 = {**rd(30), "gid": "a30", "L": "a", "id": "30"}; r30["metadata"] = dict(r30["metadata"]); r30["confirmed"] = now0 - 10 * DAY
r30["_wait"] = W.compute(r30, time.time())
r30n = json.loads(json.dumps(r30)); r30n["metadata"].pop("state"); r30n["_wait"] = W.compute(r30n, time.time())
check("4: no stale mark before the end date: freshness reads `held`; without the state the same item reads stale", render.freshness(r30, time.time())[0] == "held" and render.freshness(r30n, time.time())[0] == "stale",
      (render.freshness(r30, time.time()), render.freshness(r30n, time.time())))
# the tool text says so
import asyncio
async def _desc():
    from fastmcp import Client
    async with Client(server.mcp) as c:
        return next(t.description for t in await c.list_tools() if t.name == "update")
desc = asyncio.run(_desc())
tail = desc[desc.index("Checks:"):]
check("tool text: the update description documents the four checks in one short clause each (the new text stays under 600 bytes); the end is no input any more",
      tail.count(";") == 3 and "re-park" in tail and "stale" in tail and "60 min" in tail and len(tail.encode()) < 600 and "end=YYYY-MM-DD" not in desc, (len(tail.encode()), tail))

# ================================================================ 5. stale next
item(50, needs=[BACK], next="team-back: build it")
upd(50, sender="home-stew", hold=True, wake=day(3), wait_basis=BAS)
ns = mt(50).get("next_stale") or {}
check("5a: a write by a session that is neither the owner nor named by next, changing hold and wake and not next, marks next", ns.get("fields") == ["hold", "wake"] and ns.get("by") == "home-stew" and ns.get("at"), mt(50))
check("5a: …get shows it: who, what, when", re.search(r"\(next may be stale: home-stew changed hold, wake \w{3} \w{3} \d+\w\w \d\d:\d\d\)", get(50)) is not None, get(50))
check("5a: …and the brief", "(next may be stale: home-stew changed hold, wake" in server.stackshot_brief(), None)
upd(50, priority="p2")
check("5a: the owner's later write that leaves next alone keeps the mark", "next_stale" in mt(50), mt(50))
upd(50, next="team-back: build it after the wake")
check("5a: …until a write passes next", "next_stale" not in mt(50) and "may be stale" not in get(50), mt(50))
item(51, needs=[BACK], next="team-back: build it")
upd(51, sender="team-back", hold=True, wake=day(3), wait_basis=BAS)
check("5a: the mover's own write marks nothing", "next_stale" not in mt(51), mt(51))
item(52, needs=[BACK], next="home-stew: look at the build\nteam-back: build it")
upd(52, sender="home-stew", hold=True, wake=day(3), wait_basis=BAS)
check("5a: a session next names (a `<session>:` line) marks nothing", "next_stale" not in mt(52), mt(52))
item(53, needs=[BACK], next="team-back: build it")
upd(53, sender="home-stew", priority="p2", description="- A thing\n- It lives elsewhere\n- Done when done")
check("5a: a non-owner's write that changes none of needs, state, hold, wake, after marks nothing", "next_stale" not in mt(53), mt(53))
reads = []
_roster = server._session_roster
server._session_roster = lambda: (reads.append(1), _roster())[1]
upd(53, sender="home-stew", priority="p3")
check("5a: a write that changes nothing it watches reads neither the fleet's names nor the roster", reads == [], reads)
server._session_roster = _roster
upd(53, sender="home-stew", needs=["decision"], ask=ASK)
check("5a: …needs is one of them", (mt(53).get("next_stale") or {}).get("fields") == ["needs"], mt(53))
upd(53, sender="home-stew", next="team-back: build it, then ask Oliver", needs=[BACK])
check("5a: a non-owner that passes next in the same write leaves nothing stale", "next_stale" not in mt(53), mt(53))
item(54, needs=[BACK], next="team-back: build it")
upd(54, sender="home-stew", expected_by=hrs(2))
check("5a: a non-owner's write that changes none of the fields it watches (an old expected_by, accepted and not stored) marks nothing", "next_stale" not in mt(54), mt(54))
upd(54, sender="home-stew", step="check the link")
check("5a: …a real change of the state read (derived doing → the stored your-step that step= sets) does", (mt(54).get("next_stale") or {}).get("fields") == ["state"], mt(54))
item(55, needs=[BACK], next="team-back: build it")
item(56, needs=[BACK], next="team-back: wait for 55")
upd(56, sender="home-stew", after=["a55"], ask_by=day(9))
check("5a: after counts (and the derived blocked it brings is not listed as a state change of its own)", (mt(56).get("next_stale") or {}).get("fields") == ["after"], mt(56))
upd(56, sender="home-stew", status="completed", outcome="done", reason="finished", description="- A thing\n- It is finished\n- Nothing is left to do")
check("5a: a close drops the mark", "next_stale" not in mt(56), mt(56))
# 5b: a next that names a date that has passed
ordn = lambda d: f"{d.day}{'th' if 11 <= d.day % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d.day % 10, 'th')}"
past = TODAY_D - datetime.timedelta(days=3); fut = TODAY_D + datetime.timedelta(days=3)
item(57, needs=[BACK], next=f"team-back: reply by {past.isoformat()}")
check("5b: an ISO date that has passed is flagged in get", f"(next may be stale: it names {past.isoformat()}, which has passed)" in get(57), get(57))
item(58, needs=[BACK], next=f"team-back: reply by {past.strftime('%a %b')} {ordn(past)}")
check("5b: …a `Mon Oct 26th` form", f"it names {past.strftime('%a %b')} {ordn(past)}, which has passed" in get(58), get(58))
item(59, needs=[BACK], next=f"team-back: reply by {past.strftime('%b')} {ordn(past)}")
check("5b: …an `Oct 26th` form", f"it names {past.strftime('%b')} {ordn(past)}, which has passed" in get(59), get(59))
item(60, needs=[BACK], next=f"team-back: reply by {fut.isoformat()} or {fut.strftime('%b')} {ordn(fut)} or today {TODAY_D.isoformat()}")
check("5b: a date to come, and today, are not flagged", "may be stale" not in get(60), get(60))
item(61, needs=[BACK], next=f"team-back: read [the log](https://example.com/logs/{past.isoformat()}/x) and carry on")
check("5b: a date inside a link target is not read", "may be stale" not in get(61), get(61))
item(62, needs=[BACK], next="team-back: the Market 5 plan, and the 2026-02-30 typo")
check("5b: a word that only starts like a month, and a date that is no date, are not read", "may be stale" not in get(62), get(62))
item(63, needs=[BACK], next=f"team-back: see docs/{past.isoformat()}-plan.md and notes-{past.isoformat()}.md, and read docs/notes/{past.strftime('%b')} {ordn(past)}/x")
check("5b: a path or a file name is cut out before the dates are read", "may be stale" not in get(63), get(63))
item(64, needs=[BACK], next=f"team-back: {past.strftime('%b')} {past.day} items are open, {past.strftime('%b')} {past.day} tests pass")
check("5b: a month and day followed by a counting noun is a count, not a date", "may be stale" not in get(64), get(64))
item(65, needs=[BACK], next=f"team-back: reply by {past.strftime('%b')} {past.day}, or at the latest {past.strftime('%b')} {past.day}.")
check("5b: …a bare day that ends the phrase or is followed by a comma or a full stop is a date", f"it names {past.strftime('%b')} {past.day}, which has passed" in get(65), get(65))
check("5b: …a bare day before at/by/until or a time is a date; before a noun it is not",
      [w_ for w_, d_ in states.named_dates("Oct 5 at 18:00 and Oct 6 by noon and Oct 7 18:00", datetime.date(2026, 10, 24))] == ["Oct 5", "Oct 6", "Oct 7"]
      and states.named_dates("May 5 items, Mar 12 tests and May 5 reviewers", datetime.date(2026, 10, 24)) == [], None)
check("5b: a yearless date rolls into next year only when more than 90 days past",
      states.passed_dates("Aug 1st", datetime.date(2026, 10, 24)) != [] and states.passed_dates("Jul 1st", datetime.date(2026, 10, 24)) == []
      and states.passed_dates("Jan 5th", datetime.date(2026, 10, 24)) == [] and states.passed_dates("Dec 24th", datetime.date(2026, 3, 1)) == []
      and states.passed_dates("Dec 24th", datetime.date(2026, 10, 24)) == [] and states.passed_dates("Jan 5th", datetime.date(2026, 12, 20)) == [], None)
check("5b: the end of an inner line ends a bare day (re.M)",
      [d for _, d in states.named_dates("reply by Oct 5\nsecond line", datetime.date(2026, 10, 24))] == [datetime.date(2026, 10, 5)], None)
b = server.stackshot_brief()
check("5b: the brief flags it too", f"it names {past.isoformat()}, which has passed" in b, None)
upd(57, next=f"team-back: reply by {fut.isoformat()}")
check("5b: …and a write that rewrites next ends it", "may be stale" not in get(57), get(57))
check("5b: the year rule: a `Jan 5th` written in December is next January's, an `Oct 5th` in October is past",
      states.passed_dates("Jan 5th", datetime.date(2026, 12, 20)) == [] and [w_ for w_, d_ in states.passed_dates("Oct 5th", datetime.date(2026, 10, 24))] == ["Oct 5th"]
      and [d_ for w_, d_ in states.passed_dates("Dec 24th 2025", datetime.date(2026, 10, 24))] == [datetime.date(2025, 12, 24)], None)

# ================================================================ 6. a decision asked again
item(70, needs=["decision"], ask=ASK)
check("6: (setup) Oliver answers on the board: decision out of needs, ask dropped, the ask he answered kept with his answer", server._answer("a70", "", "ship it", "answer") == "decision"
      and "decision" not in mt(70).get("needs", []) and "ask" not in mt(70) and mt(70)["answers"][-1].get("ask") == ASK, mt(70))
refused_nw("6: needs=decision back with the same ask within the hour is refused, with why and how to go on", 70, lambda: upd(70, needs=["decision"], ask=ASK),
           "answered board#70" if server._gh.shown("a70") == "board#70" else "answered ", "min ago", "one ask per decision", "pass the new ask line in this same write")
refused_nw("6: …with no ask in the write at all", 70, lambda: upd(70, needs=["decision"]), "one ask per decision")
upd(70, needs=["decision"], ask=ASK2)
check("6: a changed ask line passes", mt(70)["needs"] == ["decision"] and mt(70)["ask"] == ASK2, mt(70))
upd(70, priority="p2")
check("6: …and a decision already in needs is not put back: other writes pass", mt(70)["priority"] == "p2", mt(70))
# already on his call: nothing is put back
item(77, needs=["decision"], ask=ASK, state="your-call")
it_ = rd(77); it_["metadata"]["answers"] = [{"ts": time.time() - 300, "kind": "comment", "text": "a question of mine, not a call", "via": "board"}]
(T / "store/a/77.json").write_text(json.dumps(it_))
upd(77, needs=["decision"], ask=ASK, priority="p2")
check("6: …nor is needs=decision restated on it", mt(77)["priority"] == "p2", mt(77))
# the clock: 59 minutes ago is within, 61 is not
def answered(i, minutes_ago, ask=ASK, **meta):
    item(i, needs=[], **meta)
    it_ = rd(i); it_["metadata"]["answers"] = [{"ts": time.time() - minutes_ago * 60, "kind": "decision", "text": "go ahead", "via": "board", "ask": ask}]
    (T / f"store/a/{i}.json").write_text(json.dumps(it_))
answered(71, 59)
refused_nw("6: 59 minutes after his answer is within the hour", 71, lambda: upd(71, needs=["decision"], ask=ASK), "one ask per decision")
answered(72, 61)
upd(72, needs=["decision"], ask=ASK)
check("6: 61 minutes after it, the same ask goes through", mt(72)["needs"] == ["decision"], mt(72))
answered(73, 10, ask="")
it_ = rd(73); it_["metadata"]["answers"][0].pop("ask"); it_["metadata"]["ask"] = ASK; (T / "store/a/73.json").write_text(json.dumps(it_))
refused_nw("6: a comment of his that left the ask on the item counts (the ask on the item is the one asked)", 73, lambda: upd(73, needs=["decision"], ask=ASK), "one ask per decision")
upd(73, needs=["decision"], ask=ASK2)
check("6: …and a changed ask passes there too", mt(73)["ask"] == ASK2, mt(73))
item(74, needs=["decision"], ask=ASK)
upd(74, priority="p3")
check("6: an item that was never answered is not held to it", mt(74)["priority"] == "p3", mt(74))
item(75, needs=[])
upd(75, needs=["decision"], ask=ASK)
check("6: …nor one whose last answer is older than any (none at all)", mt(75)["needs"] == ["decision"], mt(75))

# ================================================================ 7. the client items read, the brief and the hook's board question carry no state hint (states.hint is removed with the call that stored a state)
item(80, mover="home-front")                                          # no stored state, no session in needs
item(81, needs=["decision"], ask=ASK, then="home-front")              # needs a decision; home-front takes it after his answer
item(82, mover="home-front", state="doing", expected_by=hrs(2))       # stored
item(83, owner=U["home-other"], needs=["home-front"])                   # owned by someone else, home-front only named in needs
rows = {x["shown"]: x for x in json.loads(server._client_items(U["home-front"])[2])["items"]}      # the mover's items, not the creator's
check("7: the client items read carries no state_hint and no state_derived, and no state for an item that stores none; the stored one keeps its state", all("state_hint" not in r and "state_derived" not in r for r in rows.values()) and "state" not in rows["a80"] and rows["a82"]["state"] == "doing", {k: (rows[k].get("state"), rows[k].get("state_hint")) for k in ("a80", "a81", "a82")})
rows_f = {x["shown"]: x for x in json.loads(server._client_items(U["home-front"])[2])["items"]}
check("7: …a session named in needs is the item's mover and its row still has the role, with no hint", rows_f["a83"].get("role") == "agent" and "state_hint" not in rows_f["a83"], rows_f["a83"])
b = server.stackshot_brief()
check("7: the brief and get carry no hint to store a state, and no derived state word", "state hint:" not in b and "no stored state:" not in b and "state hint:" not in get(80) and "(derived)" not in get(80), None)
due = [rows["a80"], rows["a81"], rows["a82"], rows_f["a83"]]
check("7: the hook's board question has no state-hint lines (pages.state_hints is gone)", not hasattr(pg, "state_hints") and "Items with no stored state" not in pg.board_ask(["a write"], due), None)
pg.owned_items = lambda sid: list(due)
pg.turn_activity = lambda path: {"start": int(time.time()) + 10, "writes": True}
pg.board_mode = lambda: "block"
pg.load_state = lambda sid: {}; pg.save_state = lambda sid, st: None
q = pg.early_question({"session_id": "s", "tool_name": "mcp__x__update", "tool_response": "updated a1", "transcript_path": "/none"})
check("7: the early question (the hook text `Your other open items…`) ends with no hint lines", q.startswith("[stackshot] The end-of-turn board question") and "Your other open items" in q and "Items with no stored state" not in q, q[-400:])


import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": state checks scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
