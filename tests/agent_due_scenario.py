"""tests/agent_due_scenario.py — agent work in progress carries no expected time (and no item has a computed one).

An item an agent moves (the stored state doing, a session in needs) shows how long it has run and nothing else.
Checked here, against a scratch store and config (no port, no real server, nothing outside the scratch folder):

  * an item that stores the old word doing (written as fixture data: no call sets a state any more) has no expected time, and a write's reply says nothing of one, whatever the item's age and however far or long past an old stored expected_by is;
  * expected_by and expected_reason, which older calls pass, are accepted whatever they hold (a far time, a past one, text that is no time) and are not stored; the reply carries one note that names
    the park calls; a call that passes neither carries no note;
  * the wake cap (7 days, refused without the owner's words) is a write gate and stays;
  * a doing item whose next reads as a wait gets a note (the write still goes through); a wake alone whose next waits for that date, or whose only steps are timed or start on an event, gets a note;
  * an item stored before (an expected_by on disk) keeps working: the stored value is not read, a write that does not touch it does not rewrite it, and the items API sends expected_by as null;
  * the tool text (update, create, client.py) says so; the retired inputs' own refusals are in tests/retired_inputs_scenario.py.

    tests/run-suite agent_due        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="agentduetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the clock; the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY, HOUR = 86400.0, 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
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
from stackshot.web import server; from stackshot.waits import waiting as W; from stackshot.model import states
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
server._tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
server._front_sender = lambda who: False
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
BACK = "team-back"
def upd(i, **kw): return server._update(f"a{i}", sender="home-front", **kw)
def raw(i): return (T / f"store/a/{i}.json").read_text()
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)
ZONE_OFFSET = 4 * HOUR      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
def stamp(ts): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts + ZONE_OFFSET))          # a time as an agent writes it, in the instance timezone
def stamp_t(ts): return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(ts + ZONE_OFFSET))

# ================================================================ 1. a doing item carries no expected time
item(1, needs=[BACK], state="doing", su=now0 - 3 * DAY)
out = upd(1, priority="p2")
check("doing: a stored doing item has no expected time and a write's reply does not mention one", mt(1)["state"] == "doing" and mt(1)["priority"] == "p2" and "expected_by" not in mt(1) and "expected_reason" not in mt(1) and "expected_by" not in out and "the default" not in out and "no longer kept" not in out, (mt(1), out))
txt = server.stackshot_get("a1")
check("doing: get shows no expected_by under the state", "state: doing" in txt and "expected_by" not in txt, txt[:600])

# ================================================================ 2. expected_by and expected_reason are accepted and not stored
item(2, needs=[BACK], state="doing")
out = upd(2, expected_by=stamp(now0 + 30 * HOUR), expected_reason="the builder subagent runs the full test suite and the review")
check("retired: a far expected_by (30 hours) with a reason, which was refused before, is accepted and not stored", mt(2)["state"] == "doing" and "expected_by" not in mt(2) and "expected_reason" not in mt(2), mt(2))
check("retired: …the reply carries one note: no longer kept, and the park calls", out.count("no longer kept") == 1 and "update(hold=true, wake=" in out and "after=[" in out and "wait_kind=\"relay\"" in out, out[-600:])
for n_, kw_ in ((20, dict(expected_by="next week")), (21, dict(expected_by="2026-10-30 25:00")), (22, dict(expected_by=stamp(now0 - 2 * HOUR))), (23, dict(expected_by=time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + DAY)))),
                (24, dict(expected_reason="slow")), (25, dict(expected_by=stamp(now0 + 5 * HOUR), expected_reason="waits on Sunday's timer runs, deploying the Monday change"))):
    item(n_, needs=[BACK], state="doing"); o_ = upd(n_, **kw_)
    check(f"retired: …{sorted(kw_)} {list(kw_.values())[0]!r} is accepted whatever it holds, nothing stored, one note", mt(n_)["state"] == "doing" and "expected_by" not in mt(n_) and "expected_reason" not in mt(n_) and o_.count("no longer kept") == 1, (mt(n_), o_[-300:]))
item(26, needs=[BACK], state="doing")
o_ = upd(26, expected_reason="the builder subagent runs the full test suite and the review")
check("retired: …a reason passed alone on a doing item is accepted, not stored, with the note", "expected_reason" not in mt(26) and o_.count("no longer kept") == 1, (mt(26), o_[-300:]))
o_ = upd(26, priority="p2")
check("retired: …a call that passes neither carries no note", "no longer kept" not in o_ and mt(26)["priority"] == "p2", o_[-300:])
check("retired: …the brief shows no expected_reason", "expected_reason" not in server.stackshot_brief(), None)
upd(2, needs=["decision"], ask="Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date")
check("retired: a later write that sets his decision keeps the item clean (nothing was stored, nothing to drop)", "expected_by" not in mt(2) and "expected_reason" not in mt(2), mt(2))

# ================================================================ 4. a stored doing item is never past due and nothing else happens: no step, no notice
for p in (T / "store/a").glob("*.json"): p.unlink()          # the items of the sections above are not in this pass
LD = 30
eb_ld = now0 - 2 * HOUR
item(LD, needs=[BACK], state="doing", expected_by=stamp(eb_ld), su=now0 - 6 * HOUR)          # stored before the time was dropped, and long past
check("past due: …get does not show it as past due, and shows no step of a ladder", not re.search(r"past due", server.stackshot_get(f"a{LD}")) and not re.search(r"step \d of \d|stuck", server.stackshot_get(f"a{LD}")), server.stackshot_get(f"a{LD}"))

# ================================================================ 5. every other wait keeps its day-based default and cap
for p in (T / "store/a").glob("*.json"): p.unlink()
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
item(40, needs=["decision", BACK], ask=ASK, state="your-call", su=now0 - DAY)
item(41, needs=["external"], state="outside", party="a vendor", chase=time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + 2 * DAY)), su=now0 - DAY)
item(42, needs=[BACK], state="doing", hold=True, wake=stamp_t(now0 + 2 * DAY), su=now0 - DAY)
item(43, needs=[BACK], state="doing", wake=stamp_t(now0 + 2 * DAY), su=now0 - DAY)
item(44, needs=[BACK], state="doing", check="pr_merged o/r#1", su=now0 - DAY)
item(45, needs=[BACK], su=now0 - DAY)                                       # a derived doing: no stored state
item(53, needs=[], su=now0 - DAY)                                           # a plain item of the owner's own: the idle clock's
item(54, needs=[U["home-front"]], su=now0 - DAY)                              # the stored creator named in its own needs is a session like any other: an agent wait
item(55, needs=[U["home-front"]], check="pr_merged o/r#7", su=now0 - DAY)     # …a done check too (a mover waiting on its own PR)
item(47, needs=[BACK], state="doing", su=now0 - DAY)
item(48, needs=[BACK], state="doing", after=["a41"], su=now0 - DAY)
item(49, needs=["decision", BACK], ask=ASK, state="doing", su=now0 - DAY)     # a stored state that is not the section's: Oliver's move wins
item(57, needs=[BACK], state="doing", expected_by=stamp(now0 + 2 * HOUR), su=now0 - DAY)     # an old stored time beside the state: not read
# a mover waiting on its own PR (a session in needs, the creator included, with a check): doing, no time to set
item(56, needs=[U["home-front"]], check="pr_merged o/r#8", state="doing", su=now0 - DAY)
o_ = upd(56, expected_by=stamp(now0 + 30 * HOUR), expected_reason="waiting for CI on the pull request")
check("own PR: …a mover waiting on its own PR is doing: the old time and reason are accepted and not stored, the check still stands beside it, the wait is `doing`",
      mt(56)["state"] == "doing" and "expected_by" not in mt(56) and "expected_reason" not in mt(56) and mt(56).get("check") == "pr_merged o/r#8" and "no longer kept" in o_, mt(56))
# the caps of the others are untouched: a wake past 7 days is still refused without his words
refused("others: a wake past the 7-day cap is still refused without his words", lambda: upd(43, wake=stamp_t(now0 + 20 * DAY)), "Refused")

# ================================================================ 6b. a doing item whose next reads as a wait gets a note (the write still goes through)
NOTE_HEAD = "reads as a wait"
NOTE_CALL = "update(hold=true, wake="
OVERNIGHT = "box-g's first nightly run ends overnight; kestrel-hosting records its counts and cost in the morning"
def bupd(i, **kw): return server._update(f"a{i}", sender=BACK, **kw)
def doing_next(k, why):
    """item k (new) written to doing with next = why by its mover: (the reply, "") or ("", the refusal): the next_wait guard, which is stricter than the note's matcher, may refuse a line first"""
    item(k, needs=[BACK], state="doing")
    try:
        return bupd(k, next="team-back: " + why), ""
    except Exception as e:
        return "", str(e)
item(70, needs=[BACK], state="doing")
out = bupd(70, next="team-back: " + OVERNIGHT)
check("wait note: the overnight example as the next line of a doing item is stored (the write goes through)", mt(70)["state"] == "doing" and "nightly run ends overnight" in mt(70)["next"], mt(70))
check("wait note: …and the reply carries one note line that says to park it, with the hold, wake and wait_basis call",
      out.count(NOTE_HEAD) == 1 and "(note: this item is doing, but its next reads as a wait (overnight)" in out and NOTE_CALL in out and 'wait_basis="<what it waits on, with its date YYYY-MM-DD>"' in out and 'wake="<the time it waits for>"' in out, out)
out, err = doing_next(71, "building PR #13, tests running")
check("wait note: work wording (building, tests running) gets no note", mt(71)["state"] == "doing" and NOTE_HEAD not in out, (out, err))
for k, why in enumerate(("review of the diff, release running", "reviewing the builder's PR and running the suites", "the deploy step is running now"), 72):
    out, err = doing_next(k, why)
    check(f"wait note: work wording {why!r} gets no note", mt(k)["state"] == "doing" and NOTE_HEAD not in out, (out, err))
noted = 0
for k, why in enumerate(("waits for the nightly timer", "once the run finishes the counts are read", "ends tomorrow morning", "holds until 09:00 when the vendor answers", "after the run, record the cost", "the next run picks it up"), 80):
    out, err = doing_next(k, why)
    noted += out.count(NOTE_HEAD)
    check(f"wait note: wait wording {why!r} gets the note, or is refused first by the next_wait guard (which reads more strictly); it is never stored without one of them", (out.count(NOTE_HEAD) == 1 and why in mt(k)["next"]) or (err and why not in mt(k)["next"]), (out, err))
check("wait note: …the note itself is reached by at least three of the six (the rest met the stricter guard first)", noted >= 3, noted)
out, err = doing_next(86, "no need to wait for anything, the build is running now")
check("wait note: a negation passes (no need to wait for)", mt(86)["state"] == "doing" and NOTE_HEAD not in out, (out, err))
# a retired reason is no longer read: the same wording in expected_reason draws the retired note only
item(85, needs=[BACK], state="doing")
out = bupd(85, expected_by=stamp(now0 + 4 * HOUR), expected_reason=OVERNIGHT)
check("wait note: …wait wording in the retired expected_reason is not read: only the retired note, and nothing stored", NOTE_HEAD not in out and out.count("no longer kept") == 1 and "expected_reason" not in mt(85), out)
# a parked item with the same wording: the hold ends the doing state, so there is nothing to note
item(87, needs=[BACK], state="doing")
wake_day = time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + DAY))
out = upd(87, next="team-back: " + OVERNIGHT, hold=True, wake=wake_day, wait_basis=f"box-g's nightly run ends overnight; counts recorded in the morning ({wake_day})")
check("wait note: a parked item with the same wording gets no note, and the park is stored", NOTE_HEAD not in out and hd_(mt(87)) and mt(87).get("state") != "doing", (out, mt(87)))
# a line of next the sender just wrote, on an item that stays doing
item(88, needs=[BACK], state="doing")
out = bupd(88, next="team-back: record the counts and the cost in the morning")
check("wait note: a line of next the write sets that reads as a wait (in the morning) on a doing item gets the note, naming next", "its next reads as a wait" in out and mt(88)["state"] == "doing", out)
out = bupd(88, next="team-back: run the tests and push the branch")
check("wait note: …a next line of work gets none", NOTE_HEAD not in out, out)
# an old wait-worded next does not nag an unrelated write
item(89, needs=[BACK], state="doing", next="team-back: " + OVERNIGHT)
out = upd(89, priority="p2")
check("wait note: a write that sets neither the state nor next stays quiet about a stored next", NOTE_HEAD not in out and mt(89)["priority"] == "p2", out)
# create: a create takes no state (agent work starts with an update), so a create carries no such note, even with wait wording in next and the write still goes through
out = server._create(subject="[home] wait not doing", description=DESC, project="projects/alpha", owner="home-front", needs=[BACK], next="team-back: read the counts in the morning")
check("wait note: a create (never doing) carries no note and is created", NOTE_HEAD not in out and out.startswith("created"), out)
# the matcher, alone: one assertion per phrase (a builder waiting on its own CI or review, or running until green, is work in hand under)
from stackshot.model import model_guards as MG
for x in ("ends overnight", "in the morning", "nightly job", "the next run picks it up", "once the run finishes", "after the run", "until 09:00", "until tomorrow", "ends tomorrow", "tomorrow morning",
          "waiting on the 09:00 timer", "waits for Sunday's timer", "until the morning", "until Nov 3rd", "holds until 2026-11-02"):
    check(f"matcher: {x!r} reads as a wait", bool(MG.reads_as_wait(x)), MG.reads_as_wait(x))
for x in ("running tests until green", "rerun until stable", "watch CI until PR #13 merges", "waiting for CI on PR #13", "waiting on review", "building PR #13, tests running", "reviewing the diff",
          "release running", "preparing tomorrow's demo", "会議資料を作成中", "after the test run, push", "no need to wait for the 09:00 timer", "run `waiting on 09:00` in the shell", "", None):
    check(f"matcher: {x!r} is work in hand, no wait", not MG.reads_as_wait(x), MG.reads_as_wait(x))
for k, why in enumerate(("running tests until green", "rerun until stable", "watch CI until PR #13 merges", "waiting for CI on PR #13", "waiting on review", "preparing tomorrow's demo", "会議資料を作成中"), 90):
    out, err = doing_next(k, why)
    check(f"wait note: builder work wording {why!r} on a doing item gets no note (or meets the stricter next_wait guard first), and is never stored with a note", NOTE_HEAD not in out and (mt(k).get("state") == "doing" or "reads as a wait" in err), (out, err))
out, err = doing_next(97, "waiting on the 09:00 timer")
check("wait note: 'waiting on the 09:00 timer' on a doing item gets the note or is refused first by the guard", out.count(NOTE_HEAD) == 1 or "reads as a wait" in err, (out, err))

# ================================================================ 6c. a wake alone whose next waits for that date gets a note; a window the work needs is parked
WN_HEAD = "alone is a wait until that date, and this item's next waits for that date"
w2 = time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + 2 * DAY))
def bupd(i, **kw): return server._update(f"a{i}", sender=BACK, **kw)
item(120, needs=[BACK], next=f"team-back: collect logs until {w2}, then review")
out = bupd(120, wake=w2)
check("window note: a wake alone on an item whose next says 'collect logs until <the wake day>, then review' is stored, and the reply carries one note", wk_(mt(120)) == w2 and "hold" not in mt(120) and out.count(WN_HEAD) == 1, out)
check("window note: …it names the wake, says the item waits until then, and gives the reason form", f"wake {w2} alone" in out and "the item waits until then, listed as waiting" in out and 'until="<when the window ends>", wait_basis="<what the window collects> ends <YYYY-MM-DD>"' in out and 'until="none"' in out and "clear_wake" not in out, out)
item(121, needs=[BACK])
out = bupd(121, next="team-back: merge the PR once the reviewer approves", wake=w2)
check("window note: a wake alone with an unrelated next gets no note, and the wake is stored", WN_HEAD not in out and wk_(mt(121)) == w2, out)
item(122, needs=[BACK])
refused("window note: writing 'collect logs until <the wake day>' as next on an alive item is still refused by the next_wait guard, which names the park (hold, wake, wait_basis)",
        lambda: bupd(122, next=f"team-back: collect logs until {w2}, then review", wake=w2), "reads as a wait", "hold=true with wake=YYYY-MM-DD")
out = bupd(122, next=f"team-back: collect logs for 2 days, then review on {w2}", wake=w2)
check("window note: a window the guard's list misses ('for 2 days, then review on <the wake day>') in this call's next draws the note", out.count(WN_HEAD) == 1, out)
item(123, needs=[BACK])
out = bupd(123, next=f"team-back: soak the timer for 3 days, read the counts {time.strftime('%b', time.gmtime(now0 + ZONE_OFFSET + 2 * DAY))} {int(w2[-2:])}", wake=w2)
check("window note: a month-day form of the wake day reads too", out.count(WN_HEAD) == 1, out)
item(124, needs=[BACK])
out = bupd(124, next=f"team-back: no need to wait; fix the docs, due {w2}", wake=w2)
check("window note: a negation passes", WN_HEAD not in out, out)
item(125, needs=[BACK], next=f"team-back: collect logs until {w2}, then review")
out = bupd(125, priority="p2")
check("window note: a write that sets no wake stays quiet about the stored next", WN_HEAD not in out, out)
item(126, needs=[BACK])
out = bupd(126, next=f"team-back: collect logs until {w2}, then review", hold=True, wake=w2, wait_basis=f"log collection ends {w2}; logs reviewed then")
check("window note: hold=true + wake + wait_basis on the mover's own item is accepted and parked (no note)", hd_(mt(126)) is True and wk_(mt(126)) == w2 and isinstance(mt(126).get("wait_basis"), dict) and WN_HEAD not in out, (out, mt(126)))
check("window note: …and it reads as waiting on a time", server._model.derive({**json.loads(raw(126)), "gid": "a126"}).state == "waiting", None)
NX = f"team-back: collect logs until {w2}, then review"
item(127, needs=[BACK], next=NX)
out = bupd(127, wake=f"{w2}T09:00")
check("window note: a YYYY-MM-DDTHH:MM wake reads by its day and draws the note", out.count(WN_HEAD) == 1, out)
item(128, needs=["decision"], ask="Pick A or B?", mover="Oliver", next=NX, state="your-call")
out = bupd(128, wake=w2)
check("window note: skipped for an item on Oliver's decision (not on agent)", WN_HEAD not in out, out)
item(14, needs=[BACK], state="doing", next="team-back: build it")
item(130, needs=[BACK], after=["a14"], next=NX)
out = bupd(130, wake=w2)
check("window note: skipped for an item waiting after an open item", WN_HEAD not in out, out)
item(131, needs=["external"], party="Acme", chase=w2, next=NX, state="outside")
out = bupd(131, wake=w2)
check("window note: skipped for needs=external and a stored state of outside", WN_HEAD not in out, out)
for n_, st_ in ((132, "verifying"), (133, "blocked")):
    item(n_, needs=[BACK], next=NX, state=st_)
    try:
        out = bupd(n_, wake=w2)
    except Exception as e:       # a stored state the item no longer stands on may be refused by the state check; the note is the question here
        out = str(e)
    check(f"window note: skipped for a stored state of {st_}", WN_HEAD not in out, out)
for x in ("collect logs until 2026-11-02, then review", "after Mon Nov 2nd the counts are in", "soak for 3 days, then check 11/2", "wait until 2 Nov", "wait until Mon"):
    check(f"window matcher: {x!r} reads on a wake of 2026-11-02", bool(MG.reads_as_window(x, "2026-11-02")), MG.reads_as_window(x, "2026-11-02"))
for x in ("collect logs until 2026-11-03", "fix the docs on 2026-11-02", "merge the PR once the reviewer approves", "run `wait until 2026-11-02`", "(note: wait until 2026-11-02)", "merge the PR once CI is green; demo on Monday", "ship after review, due 2026-11-02",
          "demo on Monday", "after 12026-11-02", "no need to wait until 2026-11-02", "", None):
    check(f"window matcher: {x!r} does not read on a wake of 2026-11-02", not MG.reads_as_window(x, "2026-11-02"), MG.reads_as_window(x, "2026-11-02"))
check("window matcher: a wake that is no date reads nothing", not MG.reads_as_window("wait until 2026-11-02", "soon"), None)
import asyncio as _aio
_ud = {t.name: t for t in _aio.run(server.mcp.list_tools())}["update"].description
check("window text: update's description names the park for a window the work needs, and that real-time work stays on agent",
      "Work moving in real time stays on agent however long it takes" in _ud and "wait-and-see window" in _ud and "a soak, a log or data collection window, a trial week, a timer it started" in _ud
      and 'wait_basis=\"<what the window collects> ends <YYYY-MM-DD>\"' in _ud and "does not park to defer work it could do now" in _ud and "gets a note on the reply, never a refusal" in _ud
      and "or an item not on agent (on hold" in _ud and "needs=external" in _ud, None)

# ================================================================ 6d. a wake alone whose mover's only open steps are timed or start on an event gets a note
SN_HEAD = "alone is a wait until that date, and this item's only open next line"
import datetime as _dtm
_today_local = _dtm.datetime.fromtimestamp(now0 + ZONE_OFFSET, _dtm.timezone.utc).date()
w_tomorrow = (_today_local + _dtm.timedelta(days=1)).isoformat()
TIMED = "team-back: at 03:00 install the new config, validate, restart the service, check the status page"
EVENT = "team-back: when the next vendor release lands, check the fleet reaches it within 30 min; complete if so"
item(140, needs=[BACK], next="")
out = bupd(140, next=TIMED, wake=f"{w2}T03:00")
check("step park: a step timed at the wake's own hour is parked by the write (one parked line, no note): on hold with the wake, a wait_basis, stored waiting on a time",
      out.count("(parked: wake") == 1 and SN_HEAD not in out and wk_(mt(140)) == f"{w2}T03:00" and hd_(mt(140)) is True and f"wake {w2}" in mt(140)["wait_basis"]["text"]
      and mt(140).get("phase") == "waiting" and mt(140).get("waits_on") == "time", (out, mt(140)))
item(141, needs=[BACK], next="")
out = bupd(141, next=EVENT, wake=f"{w2}T10:00")
check("step note: a step that starts on an outside event ('when the next vendor release lands, check …') draws one note, and the item waits until the date (the reason is the wait_basis)", out.count(SN_HEAD) == 1 and "the item waits until then, listed as waiting" in out
      and 'until="<when the wait ends>", wait_basis="<what it waits on, with its date YYYY-MM-DD>"' in out and "wait_reason" in out and 'until="none"' in out and "clear_wake" not in out and "hold" not in mt(141), out)
item(142, needs=[BACK], next=EVENT, wake=f"{w2}T10:00")
out = bupd(142, priority="p2")
check("step note: a write that touches neither next nor the wake stays quiet", SN_HEAD not in out, out)
out = bupd(142, next=EVENT + " Then close the ticket.")
check("step note: a next write on an item that keeps a stored wake draws the note", out.count(SN_HEAD) == 1, out)
item(143, needs=[BACK], next="")
out = bupd(143, next=f"team-back: on {w2} rotate the key", wake=w2)
check("step park: a step on the wake's own day ('on <the wake day>') is parked", out.count("(parked: wake") == 1 and SN_HEAD not in out and hd_(mt(143)) is True, out)
item(144, needs=[BACK], next="")
out = bupd(144, next="team-back: tomorrow at 9 run the check", wake=f"{w_tomorrow}T09:00")
check("step park: 'tomorrow at …' on a wake of tomorrow is parked", out.count("(parked: wake") == 1 and SN_HEAD not in out and hd_(mt(144)) is True, out)
item(145, needs=[BACK], next="")
out = bupd(145, next="team-back: tomorrow at 9 run the check", wake=w2)
check("step note: 'tomorrow at …' on a wake two days off does not", SN_HEAD not in out, out)
item(146, needs=[BACK], next="")
out = bupd(146, next=f"team-back: {TIMED.split(': ', 1)[1]}\nteam-back: file the report now", wake=f"{w2}T03:00")
check("step note: one line of the mover's is an action to take now, so no note", SN_HEAD not in out, out)
item(147, needs=[BACK], next="")
out = bupd(147, next="team-back: rotate the key", wake=f"{w2}T03:00")
check("step note: an action with no trigger, no note", SN_HEAD not in out, out)
item(148, needs=[BACK], next="")
out = bupd(148, next="team-back: at 04:00 install the config", wake=f"{w2}T03:00")
check("step note: a time that is not the wake's hour, no note", SN_HEAD not in out, out)
item(149, needs=[BACK], next="")
out = bupd(149, next="team-back: at 03:00 install the config", wake=w2)
check("step note: a wake with no time of day does not match a clock time", SN_HEAD not in out, out)
item(150, needs=[BACK], next="")
out = bupd(150, next=TIMED, hold=True, wake=f"{w2}T03:00", wait_basis=f"the config window opens {w2}")
check("step note: a hold being set, no note", SN_HEAD not in out and hd_(mt(150)) is True, out)
item(151, needs=[BACK], next="")
out = upd(151, next=TIMED, wake=f"{w2}T03:00")
check("step note: a sender who is not the mover gets none", SN_HEAD not in out, out)
item(152, needs=[BACK], next="home-other: review the draft")
out = bupd(152, next=TIMED, wake=f"{w2}T03:00")
check("step note: another session's open step is in flight, no note", SN_HEAD not in out, out)
item(153, needs=[BACK], next="home-owner: pick the date")
out = bupd(153, next=TIMED, wake=f"{w2}T03:00")
check("step note: the owner's open step is in flight, no note", SN_HEAD not in out, out)
item(154, needs=[BACK], next="")
out = bupd(154, next="team-back: install the config now, not at 03:00", wake=f"{w2}T03:00")
check("step note: a negation before the time passes", SN_HEAD not in out, out)
item(155, needs=[BACK], next="")
out = bupd(155, next="team-back: run `at 03:00` by hand", wake=f"{w2}T03:00")
check("step note: a code span is not read", SN_HEAD not in out, out)
item(156, needs=[BACK], next="")
out = bupd(156, next="team-back: at 03:00 UTC install the config", wake=f"{w2}T03:00")
check("step note: a time in UTC is not the wake's hour", SN_HEAD not in out, out)
item(157, needs=[BACK], next=f"team-back: collect logs until {w2}, then review")
out = bupd(157, wake=f"{w2}T03:00")
check("step note: the window note comes first, and the reply carries one note, not two", out.count(WN_HEAD) == 1 and SN_HEAD not in out, out)
item(158, needs=["decision"], ask="Pick A or B?", mover="home-owner", next=TIMED, state="your-call")
out = bupd(158, wake=f"{w2}T03:00")
check("step note: skipped for an item on a decision (not on agent)", SN_HEAD not in out, out)
item(159, needs=[BACK], next="")
out = bupd(159, next="team-back: when the tests pass, merge it; check the log", wake=f"{w2}T10:00")
check("step note: a builder waiting on its own tests is work in hand, no note", SN_HEAD not in out, out)
item(160, needs=[BACK], next="")
out = bupd(160, next="team-back: when the vendor replies, send them the signed copy", wake=f"{w2}T10:00")
check("step note: a trigger that is a named outside party's reply also names needs=external with the relay wait (wait_kind, wait_event, ask_by)", out.count(SN_HEAD) == 1 and 'needs=["external"] with wait_kind="relay", wait_event=<who> and ask_by=YYYY-MM-DD' in out, out)
item(161, needs=[BACK], next="")
out = bupd(161, next=EVENT, wake=f"{w2}T10:00")
check("step note: …and a release trigger does not", out.count(SN_HEAD) == 1 and "needs=[" not in out, out)
STEP_CASES = (  # (step, wake, fires)
    (TIMED.split(": ", 1)[1], f"{w2}T03:00", True), (EVENT.split(": ", 1)[1], f"{w2}T10:00", True), ("once the vendor replies, send the doc", w2, True), ("once Mara replies send the doc", w2, True),
    ("after the next release, ship it", w2, True), ("when the next release lands check the fleet", w2, True), ("when the next release lands, check the fleet", w2, True),
    ("install it, then at 03:00 restart it", f"{w2}T03:00", True), ("at 03:00 +04", f"{w2}T03:00", True), ("on Nov 3rd at 3am run it", "2026-11-03T03:00", True),
    ("tomorrow at 9 ping the vendor", f"{w_tomorrow}T09:00", True), ("on 2026-11-03 run it", "2026-11-03", True),
    # the coordinator's review of the first version: a self action after a trigger word is no outside event
    ("when you merge, update the page", w2, False), ("upon merge, restart the service", w2, False), ("after you open the PR, request review", w2, False),
    ("after the next commit, run the tests", w2, False), ("after the next step finishes, post the result", w2, False), ("when we merge, update the page", w2, False),
    ("when I am back, check it", w2, False), ("when the tests pass, merge it; check the log", w2, False),
    # a written time must be the wake's time
    ("tomorrow at 9 ping the vendor", f"{w_tomorrow}T14:00", False), ("tomorrow at 9 ping the vendor", w_tomorrow, False), ("on Nov 3rd at 9pm run it", "2026-11-03T03:00", False),
    ("at 04:00 install it", f"{w2}T03:00", False), ("at 03:00 install it", w2, False), ("at 03:00 on Nov 5th install it", "2026-11-03T03:00", False),
    # a time or day inside the step is its content, not its trigger
    ("the cron runs at 03:00 daily; fix the script now", "2026-11-03T03:00", False), ("edit the unit so it fires at 03:00", "2026-11-03T03:00", False),
    ("schedule the job at 03:00 +04", "2026-11-03T03:00", False), ("fix the 'at 3 am' cron entry", "2026-11-03T03:00", False),
    ("check job exit codes on 11/3 numbers", "2026-11-03", False),
    ("ship by " + w2, w2, False), ("rotate the key now", w2, False), ("run `at 03:00` now", f"{w2}T03:00", False), ("at 03:00 UTC run it", f"{w2}T03:00", False), ("", w2, False), ("at 03:00 install", "soon", False),
)
for x, w_, want in STEP_CASES:
    check(f"step matcher: {x!r} on {w_!r} {'reads' if want else 'does not read'}", bool(MG.reads_as_timed_step(x, w_, _today_local)) is want, MG.reads_as_timed_step(x, w_, _today_local))
check("step matcher: is_reply_trigger reads a reply, not a release", MG.is_reply_trigger(MG.reads_as_timed_step("once the vendor replies, send it", w2)) and not MG.is_reply_trigger(MG.reads_as_timed_step(EVENT.split(": ", 1)[1], w2)), None)
_ud2 = _ud
check("step text: update's description names the note for a mover's timed or event-started steps", "every open step opens with a time at the wake's hour or day" in _ud2 and "the reply says `(parked: …)`" in _ud2 and "clear_hold=true" in _ud2 and "needs=external for a named outside party's reply" in _ud2 and "started by an outside event" in _ud2 and "another party's step in flight" in _ud2, None)

# ================================================================ 7. what was stored before keeps working
for p in (T / "store/a").glob("*.json"): p.unlink()
d2 = time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + 2 * DAY))
item(50, needs=[BACK], state="doing", expected_by=d2, su=now0 - DAY)
upd(50, priority="p1")
check("legacy: a write that does not touch it does not rewrite it", mt(50)["expected_by"] == d2 and mt(50)["priority"] == "p1", mt(50))
item(51, needs=[BACK], state="doing", expected_by=time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET - 2 * DAY)), su=now0 - 3 * DAY)
check("legacy: a lapsed date-only value: a write that leaves it alone is not refused for it", (upd(51, priority="p2") is not None) and mt(51)["priority"] == "p2", mt(51))
item(52, needs=[BACK], state="doing", expected_by="garbage", su=now0 - DAY)
check("legacy: a stored value that is no time breaks nothing: get still reads the item", "state: doing" in server.stackshot_get("a52"), server.stackshot_get("a52")[:300])

# ================================================================ 8. the routes and the text
item(60, needs=[BACK])
b60 = raw(60)
st, d = server._client_post("testbox", "state", {"sender": "home-test", "item": "a60", "state": "doing", "expected_by": stamp(now0 + 10 * HOUR), "expected_reason": "the builder runs the review and the suites"})
check("route: POST /client/state is retired (its own refusal is in tests/retired_inputs_scenario.py): a call that passes expected_by with it is refused too and nothing is stored", st == 400 and raw(60) == b60, (st, d))
item(62, needs=[BACK], state="doing")
rows62 = {x["shown"]: x for x in json.loads(server._client_items(U["team-back"])[2])["items"]}
check("route: the items API sends expected_by null for a doing item (its wait has no date)", rows62["a62"]["state"] == "doing" and rows62["a62"].get("expected_by", "missing") is None, rows62.get("a62"))
import asyncio                                                  # the tool-text checks below read the registered descriptions
async def tools():
    return {t.name: t for t in await server.mcp.list_tools()}
tl = asyncio.run(tools())
ud, cd = tl["update"].description, tl["create"].description
check("text: update's description says a doing item carries no expected time, that the old fields are accepted and not kept, and the park calls, and no ladder",
      "carries no expected time (the item shows how long it has run)" in ud and "expected_by and expected_reason, which older calls pass, are accepted and not kept" in ud and "update(hold=true, wake=" in ud and 'wait_kind="relay" with wait_event=<who>, ask_by=<the day to chase>, post_wake_mover and needs=["external"]' in ud
      and "ladder" not in ud and "stuck list" not in ud and "3 hours from this write" not in ud and "at most 12 hours ahead" not in ud, None)
check("text: update's parameters still include expected_reason, a string (so an older call is not rejected)", tl["update"].parameters["properties"].get("expected_reason", {}).get("type") == "string", tl["update"].parameters["properties"].get("expected_reason"))
check("text: create's description says agent work carries no expected time, and no tool text derives one or says past due for a wait",
      "Agent work carries no expected time: a create sets none" in cd and "never past due" not in cd and "A doing item is never past due" not in cd and "timed in hours" not in cd + ud, None)
check("text: update's wait form says an open item waits on its real dates only, that no expected time is derived for any item, and that a parked item carries no stale mark",
      "waits on its real dates only (wake, due, ask by): no expected time is derived for any item" in ud and "held until its wake or its blocker closes, with no stale mark" in ud and "is shown as past due" not in ud, None)
check("text: the audit rubric's why-not-now reads the wake only",
      "but its wake is hours or a day away" in pathlib.Path(STACK, "audit_rubric.txt").read_text(encoding="utf-8") and "wake, or expected-by" not in pathlib.Path(STACK, "audit_rubric.txt").read_text(encoding="utf-8"), None)
cli = pathlib.Path(STACK, "stackshot/fleet/client.py").read_text(encoding="utf-8")
check("text: client.py's usage lists neither --expected-by nor --expected-reason (post state, which took them, is retired: tests/retired_inputs_scenario.py)",
      "[--expected-reason" not in cli and "[--expected-by T]" not in cli and "--expected-by" not in cli, None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": agent due scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
