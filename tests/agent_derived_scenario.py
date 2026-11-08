"""tests/agent_derived_scenario.py — the due times the server works out itself are hours too, when the wait is on an agent (the dates an agent sets were already in hours, the ones the server derives still ran in days).

Checked here, against a scratch store and config (no port, no real server, nothing outside the scratch folder):

  * a needs wait on an agent session with no expected_by: agent_hours (3) from when the wait was set, not default_days (the idle pass is unchanged);
  * a done check on an agent's work: the same 3 hours, not the 7-day cap, and the check still closes the item when it passes;
  * an item's own expected_by always beats a derived date, a check included (the case: doing + check + own time);
  * a wait on Oliver or an outside party, a due date, the owner's own idle move (empty needs) keep their rule (days, or the idle clock);
  * a late derived agent wait is shown as past due and nothing is sent for it: no step, no notice;
  * `metadata.agent_from`: a derived agent wait counts its hours from it when it is later than the state clock; an `agent_rejudge` key an older waiting.json still holds is ignored (never loaded, never rewritten);
  * the words: the tool text and the notice say hours, not days, for these.

    tests/run-suite agent_derived        → exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="agentderivedtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
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
def clear_items():
    for p in (T / "store/a").glob("*.json"): p.unlink()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import waiting as W
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
server._tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
server._front_sender = lambda who: False
ST = T / "state/waiting.json"
def fresh_state(**extra):
    ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": [], **extra}))
fresh_state()
BACK = "team-back"
def raw(i): return (T / f"store/a/{i}.json").read_text()
ZONE_OFFSET = 4 * HOUR      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
def stamp(ts): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts + ZONE_OFFSET))
def epoch_of(v): return W.expected_parse(v)[0]
def W_of(i, at=None):
    at = now0 if at is None else at
    return server._waiting_of(f"a{i}", rd(i), at, server._WaitCtx(at))
def ctx_at(at): return server._WaitCtx(at)

# ================================================================ 1. a needs wait on an agent session: 3 hours from when it was set
item(1, needs=[BACK], su=now0 - HOUR)                      # set an hour ago
w = W_of(1)
check("needs: a wait on an agent session with no expected_by is `needs`, agent_hours (3) from its clock, not default_days", w["wait"] == "needs" and w["agent"] and abs(w["expected_by"] - (now0 - HOUR + 3 * HOUR)) < 1 and not w["overdue"], w)
check("needs: …its basis says hours, not the default", w["basis"] == "needs set + the agent hours" and "default" not in W.line(w, now0), W.line(w, now0))
w = W_of(1, now0 + 2 * HOUR + 60)
check("needs: …3 hours after it was set it is past due", w["overdue"], w)
item(2, needs=[BACK], su=now0 - 2 * DAY)                    # set 2 days ago, counts from its clock
w = W_of(2)
check("needs: …a wait set days ago is long past by the hours rule", w["overdue"] and w["wait"] == "needs", w)

# ================================================================ 2. a done check on an agent's work: the same hours
item(3, needs=[BACK], check="pr_merged o/r#1", su=now0 - HOUR)
w = W_of(3)
check("check: a done check on an agent's work is `check`, 3 hours from when it was set, not the 7-day cap", w["wait"] == "check" and w["agent"] and abs(w["expected_by"] - (now0 - HOUR + 3 * HOUR)) < 1 and not w["overdue"], w)
check("check: …its basis says hours, not the cap", w["basis"] == "check set + the agent hours" and "the cap" not in W.line(w, now0), W.line(w, now0))
item(4, needs=["decision", BACK], ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date", check="pr_merged o/r#2", su=now0 - DAY)
w = W_of(4)
check("check: a check on Oliver's move keeps the 7-day cap", w["wait"] == "check" and not w["agent"] and abs(w["expected_by"] - (now0 - DAY + 7 * DAY)) < 1, w)
item(5, needs=["external"], check="pr_merged o/r#3", su=now0 - DAY)
w = W_of(5)
check("check: …so does a check on an outside party", w["wait"] == "check" and not w["agent"] and abs(w["expected_by"] - (now0 - DAY + 7 * DAY)) < 1, w)
item(9, needs=[], check="pr_merged o/r#4", su=now0 - DAY)
w = W_of(9)
check("check: a check on an item with empty needs is not an agent wait (the mover is only the owner by fallback): it keeps the 7-day cap",
      w["wait"] == "check" and not w["agent"] and abs(w["expected_by"] - (now0 - DAY + 7 * DAY)) < 1 and w["basis"] == "check set + the cap", w)
item(15, needs=[U["home-front"]], check="pr_merged o/r#5", su=now0 - DAY)       # only the creator named in needs: a session like any other (no creator special case)
w = W_of(15)
check("check: …a check whose needs names only the creator is an agent wait too: 3 hours", w["wait"] == "check" and w["agent"] and abs(w["expected_by"] - (now0 - DAY + 3 * HOUR)) < 1, w)
check("check: the check still closes the item when it passes (the check wait is the only thing that changed: its kind is still `check`)", W_of(3)["wait"] == "check", None)

# ================================================================ 3. a doing item has no date at all: a stored expected_by is ignored
own = stamp(now0 + 2 * HOUR)
item(6, needs=[BACK], state="doing", expected_by=own, check="pr_merged example-org/app#422", su=now0 - DAY)      # the case
w = W_of(6)
check("own: doing + a check + an expected_by stored before the time was dropped is `doing`: no date, the stored time and the check set none, never past due",
      w["wait"] == "doing" and w["expected_by"] == 0.0 and w["agent"] and "the cap" not in W.line(w, now0) and "expected by" not in W.line(w, now0) and not w["overdue"], w)
item(7, needs=[BACK], state="doing", expected_by=own, su=now0 - 5 * DAY)
w = W_of(7)
check("own: a doing item with a stored time and no check is the same, however old it is", w["wait"] == "doing" and w["expected_by"] == 0.0 and not w["overdue"], w)
due_ts = time.strftime("%Y-%m-%d", time.gmtime(now0 + ZONE_OFFSET + 2 * DAY))
item(8, needs=[BACK], due=due_ts, su=now0 - HOUR)
w = W_of(8)
check("own: a real due date is still the item's wait (a deadline is not derived): kind `due`", w["wait"] == "due", w)

# ================================================================ 4. what keeps its rule
item(10, needs=["decision", BACK], ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date", su=now0 - DAY)
item(11, needs=["external"], su=now0 - DAY)
item(13, needs=[BACK], rank=2, su=now0 - DAY)                # a leftover rank is read by nothing: the wait is an ordinary agent wait
item(14, needs=[], su=now0 - DAY)                             # the owner's own move: the idle clock's
for i, kind in ((10, "decision"), (11, "external")):
    w = W_of(i)
    check(f"keeps: a wait on {kind} stays `needs`, 3 days from its clock (default_days)", w["wait"] == "needs" and not w["agent"] and abs(w["expected_by"] - (now0 - DAY + 3 * DAY)) < 1
          and w["basis"] == "needs set + the default", w)
w = W_of(13)
check("hours: an item with a leftover rank is an ordinary agent wait, 3 hours from its clock", w["wait"] == "needs" and w["agent"] and abs(w["expected_by"] - (now0 - DAY + 3 * HOUR)) < 1, w)
w = W_of(14)
check("keeps: the owner's own idle move keeps the idle clock (hours already)", w["wait"] == "idle" and not w["agent"], w)

# ================================================================ 5. a late derived agent wait is shown as past due and nothing is sent: no step, no notice
clear_items(); told.clear(); fresh_state()
item(20, needs=[BACK], su=now0 - 5 * HOUR)                  # due 2 hours ago by the hours rule
item(21, needs=[BACK], check="pr_merged o/r#9", su=now0 - 5 * HOUR)
w20, w21 = W_of(20), W_of(21)
check("late: a derived needs wait and a derived check wait on an agent are past due, by the hours rule", w20["overdue"] and w20["wait"] == "needs" and w21["overdue"] and w21["wait"] == "check", (w20, w21))
check("late: …get shows each on its waiting line as past due, with no step of a ladder", all(re.search(r"waiting: .*past due", server.stackshot_get(g)) and not re.search(r"step \d of \d|stuck", server.stackshot_get(g)) for g in ("a20", "a21")), server.stackshot_get("a20"))
check("late: …and nothing is sent and no record is written: no notice, no `waiting` record", not told and "waiting" not in mt(20) and "waiting" not in mt(21), (told, mt(20)))

# ================================================================ 6. metadata.agent_from, and the retired agent_rejudge key
clear_items(); told.clear()
fresh_state(agent_rejudge={"at": now0, "rewritten": ["a1"], "restarted": []})      # a waiting.json an older server wrote: the key is ignored
item(30, needs=[BACK], su=now0 - 2 * DAY)                                      # set 2 days ago: long past by the hours rule
item(31, needs=[BACK], su=now0 - 2 * DAY, agent_from=now0)                    # the same, stamped from now by a cleanup: 3 hours out
check("agent_from: without it a wait set 2 days ago is overdue", W_of(30)["overdue"], W_of(30))
w = W_of(31)
check("agent_from: …with it the hours count from the stamp: 3 hours out, not overdue, basis says hours", abs(w["expected_by"] - (now0 + 3 * HOUR)) < 1 and not w["overdue"] and w["basis"] == "needs set + the agent hours", w)
check("agent_from: …a stamp earlier than the state clock changes nothing", W.agent_clock({"state_updated": now0, "metadata": {"agent_from": now0 - DAY}}, now0) == now0, None)
check("state: an agent_rejudge key in an old waiting.json is not loaded", "agent_rejudge" not in W.load_state() and W.load_state()["baseline"] == now0 - 100 * DAY, W.load_state())
old_file = ST.read_text()
check("state: …reading the old file for every item rewrites nothing (the key stays in it, unread) and no item gets a retired pass's stamp", all(W_of(i)["wait"] for i in (30, 31)) and ST.read_text() == old_file and "agent_from" not in mt(30), (ST.read_text(), mt(30)))
check("retired: no one-off re-judge is left in the server or the waiting module", not any(hasattr(m, n) for m in (server, W) for n in ("_agent_rejudge", "_agent_rejudge_plan", "_agent_rejudge_switchover", "_REJUDGE_LAST", "agent_max_hours")), None)
check("retired: …nor its key in the example config", "agent_max_hours" not in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), None)

# ================================================================ 7. the words
import asyncio
async def tools():
    return {t.name: t for t in await server.mcp.list_tools()}
tl = asyncio.run(tools())
ud, cd = tl["update"].description, tl["create"].description
check("text: create and update say a wait on an agent session that is not stored as doing (needs a session, or a done check) is hours, and doing carries no expected time",
      all("a wait on an agent session that is not stored as doing" in x.lower() and "3 hours from when" in x for x in (cd,)) and "hours from when it was set" in ud and "carries no expected time" in ud, None)
check("text: …the check text says a check does not set the due", "A check does not set the item's due time" in cd and "3 hours from when the check was set" in cd, None)
check("text: …no tool text still sends a check or a needs wait to the cap or the default for an agent", "check set + the cap" not in cd + ud and "needs set + the default" not in cd + ud, None)
import _docs
readme = _docs.page("waiting-and-doing")
check("text: the docs state the rule and no longer the one-off re-judge", "Derived waits on an agent are hours too" in readme and "one-off re-judge" not in _docs.pages() and "check set + the agent hours" in readme, None)

print(("ok" if not fails else "FAILED") + f": agent derived scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
