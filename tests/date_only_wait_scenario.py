"""tests/date_only_wait_scenario.py — an item that only waits for a date shows as waiting from the write that sets it, and the ten-minute pass finds one that got through.

A mover that sets a wake while every open line of its next waits for that wake's own hour or day ("at 08:00 run the check") left the item reading as doing with nobody working it, until someone
asked. Checked here against a scratch store and config (no port, no real server, no model call):

  1  the write (server `_date_only_wait`, through dated_wait.timed_wait_lines): such a write is parked in the same call: on hold with the wake and a wait_basis (the call's wait_reason with the wake day,
     else the step's own words, falling back to the words when the reason would not pass the basis gate), stored phase waiting and waits_on time, the board's reading waiting on a time; the reply says so
     and says what to write if a step can run now; a next written alone on an item that keeps a stored wake is parked the same way
  2  a real reminder stays one: a line that is an action to take now, a timed line beside an action, a wake within the hour, a step started by an outside event (its note stays), another party's step in
     flight, a sender who is not the mover, a call that already holds or passes its own wait_basis: no hold, stored phase alive
  3  the ten-minute pass (audit_checks.date_only_wait through filing_findings, audit_run.filing_pass): the same shape set directly in the store is a why-not-now finding for its mover with the park as the fix,
     found with no model call and with no cap (more than the daily run's SELF_WAIT_MAX at once); a real reminder, an item already on hold, a wake within the hour, an item the board already lists as
     waiting and the item the write parked are no finding; the finding is sent once and again after a write; the daily run's why-not-now suspects are as they were

    tests/run-suite date_only_wait        → exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="dateonlywait-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY, HOUR = 86400.0, 3600.0
ZONE_OFFSET = 4 * HOUR                       # the instance timezone (Asia/Dubai, "timezone" above): UTC+4, no DST
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", su=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.waits import dated_wait as DW; from stackshot.model import model as MODEL
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._front_sender = lambda who: False
BACK = "team-back"
def bupd(i, **kw): return server._update(f"a{i}", sender=BACK, **kw)
def stamped(i): return (mt(i).get("phase"), mt(i).get("waits_on"))
local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
w2 = local_day(now0 + 2 * DAY)
PARK = "(parked: wake"
SN_HEAD = "alone is a wait until that date, and this item's only open next line"
TIMED = f"{BACK}: at 08:00 run the nightly check and report"

# ================================================================ 1. the write parks a wake that is the whole of a wait
item(1, needs=[BACK], next="")
out = bupd(1, next=TIMED, wake=f"{w2}T08:00", wait_reason="the nightly job writes the report at 08:00")
m1 = mt(1)
check("1 the write parks it: one parked line, no note", out.count(PARK) == 1 and SN_HEAD not in out, out)
check("1 the parked note says the item waits until the date (outside a hand-off), never that the date is a reminder", "alone is a wait until that date (outside a hand-off)" in out and "so the item waits until then" in out and "reminder" not in out.split(PARK, 1)[1].split("\n", 1)[0], out)
import json as _j
rec1 = _j.dumps(m1.get("server_fixes") or m1.get("fixes") or m1)
check("1 the History line the server keeps for the park says the same", "alone is a wait until that date (outside a hand-off)" in rec1 and "alone was a reminder" not in rec1, rec1[:400])
check("1 …on hold with the wake as given and a wait_basis made of the reason and the wake day", hd_(m1) is True and wk_(m1) == f"{w2}T08:00"
      and m1["wait_basis"]["text"] == f"the nightly job writes the report at 08:00 (wake {w2})" and m1["wait_basis"]["wake"] == f"{w2}T08:00", m1)
check("1 …stored as waiting on a time from this write, and the board reads it so", stamped(1) == ("waiting", "time") and MODEL.view({**rd(1), "gid": "a1"}, MODEL.derive({**rd(1), "gid": "a1"}), time.time()).state == "waiting", (stamped(1), m1))
check("1 …the reply says what the park is and what to write if a step can run now", "so the item waits until then, stored as waiting on a time" in out and "write it as the action and pass clear_hold=true" in out, out)
item(2, needs=[BACK], next="")
out = bupd(2, next=f"{BACK}: on {w2} rotate the key", wake=w2)
check("1 with no wait_reason (a gate that failed open, a script's write) the basis is the step's own words, and the item is parked all the same",
      out.count(PARK) == 1 and hd_(mt(2)) is True and mt(2)["wait_basis"]["text"] == f"the only open step is timed (on {w2}), wake {w2}" and stamped(2) == ("waiting", "time"), (out, mt(2)))
item(3, needs=[BACK], next="")
out = bupd(3, next=TIMED, wake=f"{w2}T08:00", wait_reason="the job reported nothing since 2026-02-30 and runs at 08:00")
check("1 a reason that would not pass the basis gate (a date not on the calendar) falls back to the step's words: still parked, no refusal",
      out.count(PARK) == 1 and hd_(mt(3)) is True and mt(3)["wait_basis"]["text"] == f"the only open step is timed (at 08:00), wake {w2}", (out, mt(3)))
item(4, needs=[BACK], next=TIMED, wake=f"{w2}T08:00")
out = bupd(4, next=TIMED + " and file the result")
check("1 a next written alone on an item that keeps a stored wake is parked the same way", out.count(PARK) == 1 and hd_(mt(4)) is True and stamped(4) == ("waiting", "time"), (out, mt(4)))
item(5, needs=[BACK], next="")
out = bupd(5, next=f"{BACK}: tomorrow at 9 run the check", wake=f"{local_day(now0 + DAY)}T09:00")
check("1 'tomorrow at 9' on a wake of tomorrow is parked", out.count(PARK) == 1 and hd_(mt(5)) is True, out)
out = bupd(1, clear_hold=True, next=f"{BACK}: write the report now")
check("1 clear_hold in a later call releases it, as for any hold (the way out the reply names)", not hd_(mt(1)) and "wake" not in mt(1) and stamped(1) == ("alive", None) and PARK not in out, (out[-300:], mt(1)))

d2_ = dt.datetime.fromtimestamp(now0 + 2 * DAY + ZONE_OFFSET, dt.timezone.utc)
WDN, MON_, DN_ = d2_.strftime("%a"), d2_.strftime("%b"), d2_.day
item(6, needs=[BACK], next="")
out = bupd(6, next=f"{BACK}: on {WDN} {MON_} {DN_} run the check", wake=w2)
check("1 the weekday form with the wake's date ('on Fri Nov 6th run …') is parked", out.count(PARK) == 1 and hd_(mt(6)) is True and stamped(6) == ("waiting", "time"), (out, mt(6)))
item(7, needs=[BACK], next="")
out = bupd(7, next=f"{BACK}: on {WDN} run the check", wake=w2)
check("1 the bare weekday of the wake ('on Fri run …', the wake within the week) is parked", out.count(PARK) == 1 and hd_(mt(7)) is True, (out, mt(7)))
item(8, needs=[BACK], next="")
out = bupd(8, next=f"{BACK}: {MON_} {DN_}: run the check", wake=w2)
check("1 the date with a colon ('Nov 6: run …') is parked", out.count(PARK) == 1 and hd_(mt(8)) is True, (out, mt(8)))
item(9, needs=[BACK], next="")
out = bupd(9, next=f"{BACK}: at 08:00 on {MON_} {DN_} run the check", wake=f"{w2}T08:00")
check("1 a clock time with the wake's day ('at 08:00 on Nov 7th …') stays parked", out.count(PARK) == 1 and hd_(mt(9)) is True, (out, mt(9)))

# ================================================================ 2. a reminder's date is a wait too, and nothing says it is parked
# (the wake is now written as `until`: an open item with an until is waiting, so there is no reminder left to park and no note about one)
def stays(name, i, **kw):
    out = bupd(i, **kw)
    m = mt(i)
    check(name, PARK not in out and _WT.stored_until(m) and "wake" not in m and "hold" not in m and stamped(i) == ("waiting", "time"), (out[-400:], m))
    return out
item(10, needs=[BACK], next="")
stays("2 an action to take now with a wake is a reminder: no hold, stored alive", 10, next=f"{BACK}: fix the retry loop and check the log", wake=f"{w2}T08:00")
item(11, needs=[BACK], next="")
stays("2 a timed line beside an action to take now: the action is work in hand", 11, next=f"{TIMED}\n{BACK}: file the report now", wake=f"{w2}T08:00")
soon = dt.datetime.fromtimestamp(now0 + ZONE_OFFSET + 30 * 60, dt.timezone.utc)
item(12, needs=[BACK], next="")
stays("2 a wake within the hour is a reminder even when the step is timed at it", 12, next=f"{BACK}: at {soon:%H:%M} run the check", wake=soon.strftime("%Y-%m-%dT%H:%M"))
item(13, needs=[BACK], next="")
out = stays("2 a step started by an outside event keeps its note and is not parked (the park is for a wait on a date)", 13, next=f"{BACK}: when the next vendor release lands, check the fleet reaches it", wake=f"{w2}T10:00")
check("2 …the note (a wake passed as the old parameter keeps it)", out.count(SN_HEAD) == 1, out)
item(14, needs=[BACK], next=f"home-other: review the draft")
stays("2 another party's step in flight: not parked", 14, next=f"{TIMED}", wake=f"{w2}T08:00")
item(15, needs=[BACK], next="")
out = server._update("a15", sender="home-front", next=TIMED, wake=f"{w2}T08:00")
check("2 a sender who is not the mover is not parked (the date is stored as until, no hold)", PARK not in out and _WT.stored_until(mt(15)) and "hold" not in mt(15), out)
item(16, needs=[BACK], next="")
out = bupd(16, next=TIMED, hold=True, wake=f"{w2}T08:00", wait_basis=f"the config window opens {w2}")
check("2 a call that parks itself is as it was: its own basis, no second park line", PARK not in out and mt(16)["wait_basis"]["text"] == f"the config window opens {w2}" and hd_(mt(16)) is True, (out[-300:], mt(16)))
item(17, needs=["decision"], ask="Pick A or B?", mover="home-owner", next=TIMED, state="your-call")
out = bupd(17, wake=f"{w2}T08:00")
check("2 an item on his call is not parked by this", PARK not in out and "hold" not in mt(17), out)
item(18, needs=[BACK], next="")
out = bupd(18, priority="p2")
check("2 a write that touches neither next nor the wake leaves an item alone", PARK not in out and not hd_(mt(18)), out)

item(19, needs=[BACK], next="")
out = stays("2 work to do now before a 'then at 08:00' ('build the fix now, then at 08:00 verify it') is not parked", 19, next=f"{BACK}: build the fix now, then at 08:00 verify it", wake=f"{w2}T08:00")
check("2 …the note (a wake passed as the old parameter keeps it)", out.count(SN_HEAD) == 1, out)
other_day = dt.datetime.fromtimestamp(now0 + 3 * DAY + ZONE_OFFSET, dt.timezone.utc)
item(21, needs=[BACK], next="")
stays("2 a weekday that is not the wake's ('on Mon' on a Fri wake) is no wait", 21, next=f"{BACK}: on {other_day.strftime('%a')} run the check", wake=w2)
item(22, needs=[BACK], next="")
stays("2 the wake's weekday with another date ('on Fri Nov 13th') is no wait", 22, next=f"{BACK}: on {WDN} {other_day.strftime('%b')} {other_day.day} run the check", wake=w2)
item(23, needs=[BACK], next="")
stays("2 another day with a colon ('Nov 8: run …') is no wait", 23, next=f"{BACK}: {other_day.strftime('%b')} {other_day.day}: run the check", wake=w2)
tn = dt.datetime.fromtimestamp(now0 + ZONE_OFFSET, dt.timezone.utc)
if (tn.hour * 3600 + tn.minute * 60) < 21 * 3600:                      # a wake later today that is over the hour away
    td_ = local_day(now0)
    item(24, needs=[BACK], next="")
    stays("2 a day-only step on today ('on <today> run the migration') with the wake later today can run now: not parked", 24, next=f"{BACK}: on {td_} run the migration", wake=f"{td_}T23:30")
    item(25, needs=[BACK], next="")
    out = bupd(25, next=f"{BACK}: at 23:30 on {td_} run the migration", wake=f"{td_}T23:30")
    check("2 …but a clock time on today at the wake still counts", out.count(PARK) == 1 and hd_(mt(25)) is True, (out, mt(25)))
# the same readings on fixed dates, whatever the clock says
from stackshot.model import model_guards as MG
FD = dt.date(2026, 11, 5)
tw = lambda txt, wake, only=True: MG.reads_as_timed_step(txt, wake, FD, dated_only=only)
check("2 (fixed dates) 'then at 08:00' is read by the note's reading and not by the park's", tw("build the fix now, then at 08:00 verify it", "2026-11-06T08:00", False) == "at 08:00" and tw("build the fix now, then at 08:00 verify it", "2026-11-06T08:00") == "", None)
check("2 (fixed dates) a day-only step on today is no wait; with a clock time it is", tw("on 2026-11-05 run the migration", "2026-11-05T18:00") == "" and tw("at 18:00 on 2026-11-05 run the migration", "2026-11-05T18:00") != "", None)
check("2 (fixed dates) weekday forms: the wake's weekday and date, bare weekday inside the week, colon form; not another weekday, another date, or a bare weekday a week on",
      all(tw(t, "2026-11-06") for t in ("on Fri Nov 6th run it", "on Fri run it", "Nov 6: run it", "Fri Nov 6: run it", "on Friday, Nov 6 run it"))
      and not any(tw(t, "2026-11-06") for t in ("on Sat run it", "on Fri Nov 13th run it", "Nov 7: run it", "on Sat Nov 6th run it")) and not tw("on Fri run it", "2026-11-13"), None)

# ================================================================ 3. the ten-minute pass finds the shape that got through
H = 3600; now = time.time()
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900
wake_f = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
def aitem(i, wake_in_h=6.0, nxt=None, **kw):
    w = wake_f(now + wake_in_h * H)
    nxt = f"home-agent: at {w[-5:]} run the nightly check and report" if nxt is None else nxt
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": now - H, "written_at": now - H, "written_by": "home-agent",
         "state_updated": now - H, "confirmed": now - H,
         "metadata": {"owner": U["home-front"], "project": "projects/alpha", "state": "doing", "needs": ["home-agent"], "next": nxt, "wake": w, **kw}}
    return f"a{i}", d
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(): return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, sessions=lambda: None,
                         pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
shape = dict([aitem(9031), aitem(9071)])           # the shape, set directly in the store: no phase was ever stamped, the write never saw it
fs, _flags = AC.filing_findings(shape, {}, now, env())
got = sorted((f["id"], f["category"]) for f in fs)
check("3 the shape set directly in the store is a why-not-now finding for each item", got == [("board#9031", "why-not-now"), ("board#9071", "why-not-now")], got)
f9031 = next(f for f in fs if f["id"] == "board#9031")
check("3 …to the mover, with the wake, the hours away, the line and the park as the fix", f9031["mover"] == "home-agent" and f9031["source"] == "code" and wk_(shape["a9031"]["metadata"]) in f9031["detail"] and "hours away" in f9031["detail"]
      and "every open next line waits for it" in f9031["detail"] and f9031["fix"] == AC.DATE_ONLY_FIX and "hold=true" in f9031["fix"] and "wait_basis" in f9031["fix"], f9031)
check("3 …and the server's stamp agrees that the board shows such an item alive (the gap this closes)", server._stamp_values("a9031", shape["a9031"])[0] == "alive", server._stamp_values("a9031", shape["a9031"]))
many = dict(aitem(i) for i in range(40, 40 + AR.SELF_WAIT_MAX + 4))
fs, _flags = AC.filing_findings(many, {}, now, env())
check(f"3 it is not capped: {len(many)} such items, more than the daily run's {AR.SELF_WAIT_MAX} why-not-now suspects a run, are all found", len([f for f in fs if f["category"] == "why-not-now"]) == len(many), len(fs))
clean = dict([aitem(50, nxt="home-agent: fix the retry loop and check the log"),                                                  # an action to take now: a reminder on work in hand
              aitem(51, nxt="home-agent: at 08:00 run the check\nhome-agent: file the report now"),                              # a timed line beside an action
              aitem(52, wake_in_h=0.5), aitem(53, hold=True, wait_basis={"text": "the window ends", "wake": "x", "by": "home-agent", "at": now}),
              aitem(54, nxt="ops-other: review the draft"),                                                                         # another party's step
              aitem(55, nxt="home-agent: when the next vendor release lands, check the fleet reaches it")])                         # an outside event: the note's, not a date
clean["a52"]["metadata"]["next"] = f"home-agent: at {clean['a52']['metadata']['wake'][-5:]} run the check"
fs, flags = AC.filing_findings(clean, {}, now, env())
check("3 a real reminder, a timed line beside an action, a wake within the hour, an item on hold, another party's step and an outside event are no finding", not [f for f in fs if f["category"] == "why-not-now"], fs)
dated = dict([aitem(60, wake_in_h=30.0, nxt=f"home-agent: after {local_day(now + 30 * H)} the run, check the report")])
dated["a60"]["metadata"]["wake"] = wake_f(now + 30 * H)
check("3 an item the board already lists as waiting (every step dated for a later day) is the daily run's, not this pass's", AC.date_only_wait(dated["a60"], dated["a60"]["metadata"], "home-agent", lambda i: [], now) == ""
      and not [f for f in AC.filing_findings(dated, {}, now, env())[0] if f["category"] == "why-not-now"], None)
check("3 the item the write parked is no finding (nothing for the pass to say once the write has corrected it)", not [f for f in AC.filing_findings({"a1": {**rd(4), "id": "4"}}, {}, time.time(), env())[0] if f["category"] == "why-not-now"], None)
wk_ = wake_f(now + 30 * H); wd_ = dt.datetime.strptime(wk_[:10], "%Y-%m-%d")
audit_forms = dict([aitem(70, wake_in_h=30.0, nxt=f"home-agent: build the fix now, then at {wk_[-5:]} verify it"),                              # work now before a 'then'
                    aitem(9073, wake_in_h=30.0, nxt=f"home-agent: on {wd_.strftime('%a %b')} {wd_.day} run the check"),                              # weekday + date: the wake's day
                    aitem(9030, wake_in_h=30.0, nxt=f"home-agent: on {wd_.strftime('%a')} run the check"),                                           # bare weekday of the wake
                    aitem(9072, wake_in_h=30.0, nxt=f"home-agent: {wd_.strftime('%b')} {wd_.day}: run the check")])                                 # date with a colon
got = {f["id"] for f in AC.filing_findings(audit_forms, {}, now, env())[0] if f["category"] == "why-not-now"}
check("3 the pass reads the weekday form, the bare weekday and the colon form as the wake's day, and not 'build now, then at …'", got == {"board#9073", "board#9030", "board#9072"}, got)
w2h = wake_f(now + 2 * H)
if w2h[:10] == local_day(now):
    today_only = dict([aitem(74, wake_in_h=2.0, nxt=f"home-agent: on {w2h[:10]} run the migration")])
    check("3 the pass does not flag a day-only step on today itself (it can run now)", not [f for f in AC.filing_findings(today_only, {}, now, env())[0] if f["category"] == "why-not-now"], None)
# the pass: delivered through deliver_findings, once; again after a write
r1 = AR.filing_pass(now=now, items=shape, anchors={}, env=env())
check("3 the pass sends each to its mover in one message headed as a filing check, with the category and the fix", r1["fresh"] == 2 and len(sent) == 1 and sent[0][0] == "home-agent"
      and sent[0][1].count("board#") == 2 and "· why-not-now ·" in sent[0][1] and "hold=true with the wake and wait_basis" in sent[0][1], (r1, sent))
sent.clear()
r2 = AR.filing_pass(now=now + 600, items=shape, anchors={}, env=env())
check("3 …and again ten minutes later sends nothing while the items are unwritten", r2["fresh"] == 0 and r2["repeats"] == 2 and not sent, (r2, sent))
fresher = dict(shape); k, d = aitem(9031); d["written_at"] = time.time() + 60; fresher[k] = d
r3 = AR.filing_pass(now=now + 1200, items=fresher, anchors={}, env=env())
check("3 a write to the item sends its finding again, and only that one", r3["fresh"] == 1 and sent and sent[0][1].count("board#") == 1, (r3, sent))
sus, _skipped = AR.suspects(shape, now, AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None)))
check("3 the daily run's why-not-now suspects are as they were: the dated-steps shape only, this shape is not a model call", not [s for s in sus if "why-not-now" in s["checks"]], sus)
check("3 the rubric still describes the daily check and the fix text is the pass's own", "why-not-now" in AC.CHECKS_FILING and AC.FIX["why-not-now"].startswith("do the step now"), None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": date only wait scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
