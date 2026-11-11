"""Scenario test for the check on a wait a session sets on its own item (self_wait.py) — fixture data, the tools called in-process, the model call stubbed (`self_wait._run`;
router.run_call raises, so a test that reached the real model would fail), no live store, no network, no claude.

Covers, through stackshot_update and stackshot_create (a session's write):
  the replay    an agent sets a wake and writes "apply the step at Monday's scheduled run" with a reason that names no blocker, and the fake model says the step can be done now: refused,
                the model's reason quoted, nothing written
  a blocker     the reason names a real blocker and the model says no: accepted and written
  no reason     a wake, or a dated own step, with no wait_reason (or a short one) is refused, naming wait_reason, and no call is made
  failure       a model that raises, answers with an error status, or answers unreadably lets the write through (fail open)
  a deadline    "ship the fix by <date>" and "due <date>" are no wait: no refusal, no call
  the cap       past [wait_guard] max_calls the write goes through unjudged; max_calls = 0 makes no call and the missing-reason refusal stays
  the switch    [wait_guard] enabled = false: no refusal, no call
  out of scope  a wait on another item, on his decision, a stored wait_kind, a hold with its wait_basis, a hand-off, a wake the item already carries, a step it already carried,
                a sender that is not the mover, and a create with no mover= of its own make no call
  a create      mover=<the sender> with a dated step is judged like an update
  units         dated_wait, parse_answer and the call's message

    uv run tests/self_wait_scenario.py        → exit 0 / 1"""
import contextlib, datetime as dt, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="selfwaittest-"); T = pathlib.Path(tmp)
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
DESC = "- Goal: A thing, finished when it works"
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
def item(i, status="open", **meta):
    base = {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it"}
    base.update(meta)
    for k in [k for k, v in base.items() if v is None]: base.pop(k)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": base}))
for i in range(1, 40):
    item(i)                                                       # items in the agent's hands, one open step each
(T / "store/next-id").write_text("60"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def files(): return sorted(p.name for p in (T / "store/a").glob("*.json"))

from stackshot.web import server; from stackshot.waits import self_wait as SW; from stackshot.router import router as R
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
def _no_claude(*a, **k): raise AssertionError("the real model was called")
R.run_call = _no_claude
CALLS = []
ANSWER = None
def fake_run(message):
    CALLS.append(message)
    if isinstance(ANSWER, Exception): raise ANSWER
    return ANSWER
SW._run = fake_run
def answer(can, why="nothing blocks it"): return {"status": "ok", "text": json.dumps({"can_do_now": can, "reason": why})}
def reset(ans=None):
    global ANSWER
    CALLS.clear(); SW._CALLS.clear(); ANSWER = ans if ans is not None else answer(False, "the build is still running")
@contextlib.contextmanager
def cfg(**kw):
    g = server._cfg.CFG.setdefault("wait_guard", {}); was = dict(g); g.update(kw)
    try: yield
    finally: g.clear(); g.update(was)
ZONE_OFFSET = dt.timedelta(hours=4)      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
TODAY = dt.datetime.now(dt.timezone(ZONE_OFFSET)).date()
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()
REASON = "the vendor's build has to finish before the part can be applied"
def upd(i, **kw): return server.stackshot_update(f"a{i}", sender="home-agent", **kw)
def mk(**kw):
    kw = {"subject": "[home] a new thing", "description": DESC, "project": "projects/alpha", "next": "home-agent: build it", "sender": "home-agent", "mover": "home-agent", **kw}
    return server.stackshot_create(**kw)
def refused(name, f, *want, i=None, calls=None):
    was = rd(i) if i is not None else None
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want) and (was is None or rd(i) == was) and (calls is None or len(CALLS) == calls), (str(e), len(CALLS)))
def passes(name, f, calls):
    try:
        out = f(); check(name, len(CALLS) == calls, (out, len(CALLS)))
        return out
    except server.ToolError as e:
        check(name, False, str(e))
def quiet(name, f):
    try: f()
    except server.ToolError: pass
    check(name, len(CALLS) == 0, len(CALLS))

# ---- the replay
reset(answer(True, "the machines the step needs are online, so it can be applied now"))
refused("replay: a wake and a step at Monday's scheduled run, no blocker, the model says do it now: refused", lambda: upd(1, wake=D(7) + "T10:00", next="home-agent: apply the step at Monday's scheduled run", wait_reason="the scheduled run is when it is applied"),
        "can be done now", "the machines the step needs are online", "Do the step now", i=1, calls=1)
check("replay: the model got the step, the wait and the reason", all(w in CALLS[0] for w in ("<step>", "apply the step", "<reason>the scheduled run is when it is applied", D(7))), CALLS[0] if CALLS else None)
check("replay: nothing was written (no wake)", not wk_(mt(1)), mt(1))

# ---- a real blocker, the model says no
reset(answer(False, "the build is still running"))
passes("blocker: the reason names a real blocker and the model says no: accepted", lambda: upd(2, wake=D(3), next="home-agent: apply the step once the build is done", wait_reason=REASON), 1)
check("blocker: the wake is written and wait_reason is not stored", wk_(mt(2)) and "wait_reason" not in json.dumps(rd(2)), mt(2))

# ---- no reason
reset()
refused("no reason: a wake without wait_reason is refused, naming the parameter", lambda: upd(3, wake=D(2)), "wait_reason", "a wait on your own item needs its reason", i=3, calls=0)
refused("no reason: a dated own step without wait_reason is refused", lambda: upd(3, next=f"home-agent: apply the step on {D(4)}"), "wait_reason", i=3, calls=0)
refused("no reason: a reason that is too short is refused", lambda: upd(3, wake=D(2), wait_reason="later"), "wait_reason", i=3, calls=0)
refused("no reason: tomorrow reads as a wait", lambda: upd(3, next="home-agent: apply the step tomorrow"), "wait_reason", i=3, calls=0)

# ---- the call fails: fail open
for name, ans in (("raises", RuntimeError("boom")), ("answers an error status", {"status": "timeout", "text": "", "note": "killed"}), ("answers something unreadable", {"status": "ok", "text": "I think so"})):
    reset(ans)
    passes(f"failure: a model that {name} lets the write through", lambda: upd(4, wake=D(5), wait_reason=REASON), 1)
    check(f"failure: …and the wake is written ({name})", wk_(mt(4)) == D(5), wk_(mt(4)))
    upd(4, clear_wake=True)

# ---- a deadline is no wait
reset(answer(True, "should never be asked"))
for n, line in ((5, f"home-agent: ship the fix by {D(3)}"), (20, f"home-agent: ship the fix, due {D(3)}"), (21, f"home-agent: finish before {D(3)}")):
    passes(f"deadline: {line!r} is no wait: no refusal, no call", lambda: upd(n, next=line), 0)
    check(f"deadline: the line is written ({n})", line in mt(n)["next"], mt(n))

# ---- more deadline spellings are no wait (a false refusal is the costly error)
reset(answer(True, "should never be asked"))
for n, line in ((22, "home-agent: ship it, due: 2026-11-20"), (23, "home-agent: Deadline: Nov 20"), (24, "home-agent: ship it by the end of the day on Nov 20th"),
                (25, "home-agent: ship it Nov 20 at the latest"), (26, "home-agent: target Nov 20th"), (27, "home-agent: ETA Nov 20"), (28, "home-agent: run ./tomorrow.sh to rebuild the index")):
    passes(f"deadline: {line!r} is no wait: no refusal, no call", lambda: upd(n, next=line), 0)

# ---- a wake re-sent is no new wait; a bad wake gets its own refusal and no call
reset(answer(True, "should never be asked"))
item(30, wake=D(4) + "T10:00")
passes("wake: the stored wake re-sent with a space for the T sets nothing: no reason, no call", lambda: upd(30, wake=D(4) + " 10:00"), 0)
item(31, wake=D(4))
passes("wake: a stored date-only wake re-sent sets nothing", lambda: upd(31, wake=D(4)), 0)
refused("wake: a wake that is no date is refused by the wake check, with no model call", lambda: upd(32, wake="next tuesday", wait_reason=REASON), "metadata.wake must be", i=32, calls=0)
refused("wake: a wake in the past is refused by the wake check, with no model call", lambda: upd(33, wake="2020-01-01", wait_reason=REASON), "wake must be in the future", i=33, calls=0)
refused("wake: a bad wake with no reason is refused for the wake, not for the reason", lambda: upd(34, wake="2020-01-01"), "wake must be in the future", i=34, calls=0)
refused("wake: a new, different wake still needs its reason", lambda: upd(30, wake=D(5) + "T10:00"), "wait_reason", i=30, calls=0)

# ---- ordinary lines that name a weekday or a run write with no reason and no call; a plain wait still needs its reason
reset(answer(True, "should never be asked"))
for n, line in ((35, "home-agent: read Monday's update from the vendor and apply it"), (36, "home-agent: Rae said on Monday that the plan holds; implement it"),
                (37, "home-agent: document how the next nightly run works")):
    passes(f"ordinary: {line!r} is no wait: no refusal, no call", lambda: upd(n, next=line), 0)
refused("ordinary: a plain wait (after the weekend) still needs its reason", lambda: upd(38, next="home-agent: check after the weekend"), "wait_reason", i=38, calls=0)

# ---- the cap and the switch
reset(answer(True, "nothing blocks it"))
with cfg(max_calls=1):
    refused("cap: the first call in the hour is judged", lambda: upd(6, wake=D(2), wait_reason=REASON), "can be done now", calls=1)
    passes("cap: the next one past max_calls goes through unjudged", lambda: upd(6, wake=D(2), wait_reason=REASON), 1)
reset(answer(True))
with cfg(max_calls=0):
    refused("cap: max_calls = 0 makes no call and the missing-reason refusal stays", lambda: upd(7, wake=D(2)), "wait_reason", calls=0)
    passes("cap: max_calls = 0 with a reason goes through, no call", lambda: upd(7, wake=D(2), wait_reason=REASON), 0)
reset(answer(True))
with cfg(enabled=False):
    passes("switch: enabled = false, no reason: accepted, no call", lambda: upd(8, wake=D(2), next=f"home-agent: apply on {D(3)}"), 0)

# ---- out of scope: no call
reset(answer(True))
quiet("scope: a wait on another open item (after) makes no call", lambda: upd(9, after=["a2"], wake=D(3), next=f"home-agent: apply on {D(3)}"))
quiet("scope: a wait on his decision (needs=decision) makes no call", lambda: upd(10, needs="decision", ask=ASK, options=OPTS, wake=D(3)))
quiet("scope: a stored wait kind makes no call", lambda: upd(11, wait_kind="relay", wake=D(3)))
quiet("scope: a park (hold with its wait_basis) makes no call", lambda: upd(12, hold=True, wake=D(3), wait_basis=f"the vendor ships the part {D(3)}"))
quiet("scope: a hand-off to another session makes no call", lambda: upd(13, next=f"home-here: take it on {D(3)}"))
j = rd(14); j["metadata"]["wake"] = D(3); (T / "store/a/14.json").write_text(json.dumps(j))
quiet("scope: a wake the item already carries is no new wait", lambda: upd(14, wake=D(3)))
j = rd(15); j["metadata"]["next"] = f"home-agent: apply on {D(3)}"; (T / "store/a/15.json").write_text(json.dumps(j))
quiet("scope: a dated step the item already carried is no new wait", lambda: upd(15, next=f"home-agent: apply on {D(3)}"))
quiet("scope: a sender that is not the mover makes no call", lambda: server.stackshot_update("a16", sender="home-here", wake=D(3)))
quiet("scope: a close makes no call", lambda: server.stackshot_complete("a17", sender="home-agent", outcome="done", reason="finished by " + D(1)))
quiet("scope: an undated write makes no call", lambda: upd(18, next="home-agent: build it, then test it"))
quiet("scope: a past date is no wait", lambda: upd(19, next=f"home-agent: the build of {D(-3)} failed, fix it"))

# ---- a create
reset(answer(True, "it can start now"))
before = files()
refused("create: mover=<the sender> with a dated step and no reason is refused", lambda: mk(next=f"home-agent: apply on {D(3)}"), "wait_reason", calls=0)
refused("create: with a reason the model judges it: yes refuses", lambda: mk(next=f"home-agent: apply on {D(3)}", wait_reason=REASON), "can be done now", calls=1)
check("create: nothing was created by the refusals", files() == before, files())
reset(answer(False, "the vendor has not replied"))
passes("create: the model says no: created", lambda: mk(next=f"home-agent: apply on {D(3)}", wait_reason=REASON), 1)
reset(answer(True))
passes("create: no mover= (the builder moves it) makes no call", lambda: mk(mover="", next=f"home-agent: apply on {D(3)}"), 0)

# ---- units
today = dt.date(2026, 11, 4)         # a Wednesday
for line, want in (("home-agent: apply it at Monday's scheduled run", "Monday"), ("home-agent: ship it tomorrow", "tomorrow"), ("home-agent: apply on 2026-11-20", "2026-11-20"),
                   ("home-agent: apply Nov 20th", "Nov 20th"), ("home-agent: revisit next week", "next week"), ("home-agent: ship by Nov 20th", ""), ("home-agent: due 2026-11-20", ""),
                   ("home-agent: build it on Wednesday", ""), ("home-agent: the build of 2026-11-01 failed", ""), ("home-agent: build it, then test it", ""),
                   ("home-agent: ship it no later than Nov 20th", ""), ("home-agent: use `Nov 20th` in the config", "")):
    got = SW.dated_wait(line, today)
    check(f"unit: dated_wait({line!r}) -> {want!r}", (got != "") == (want != "") and (not want or want.lower() in got.lower()), got)
# deadlines in the spellings the first version missed: none is a wait
for line in ("home-agent: ship it, due: 2026-11-20", "home-agent: Deadline: Nov 20", "home-agent: ship it by the end of the day on Nov 20th", "home-agent: ship it Nov 20 at the latest",
             "home-agent: target Nov 20th", "home-agent: ETA Nov 20", "home-agent: ship it by tomorrow", "home-agent: finish by next Monday", "home-agent: ship it Nov 20 or earlier",
             "home-agent: run ./tomorrow.sh now", "home-agent: fix tomorrow.sh", "home-agent: done within 2 days"):
    check(f"unit: deadline {line!r} is no wait", SW.dated_wait(line, today) == "", SW.dated_wait(line, today))
# waits the first version missed, and "tomorrow" as a word
for line, want in (("home-agent: apply it at the next nightly run", "next nightly run"), ("home-agent: apply it at the next scheduled run", "next scheduled run"), ("home-agent: apply it on the next daily run", "next daily run"),
                   ("home-agent: check after the weekend", "after the weekend"), ("home-agent: re-check in 3 days", "in 3 days"), ("home-agent: re-check in two weeks", "in two weeks"),
                   ("home-agent: apply at Monday's run", "Monday"), ("home-agent: apply at Monday's scheduled run", "Monday"), ("home-agent: wait until Friday", "Friday"),
                   ("home-agent: re-run on Fri", "Fri"), ("home-agent: re-run next Wednesday", "next Wednesday"), ("home-agent: retry tomorrow.", "tomorrow"), ("home-agent: ship by Friday, then apply after Nov 20", "Nov 20"),
                   ("home-agent: to be applied on Monday", "Monday")):
    got = SW.dated_wait(line, today)
    check(f"unit: wait {line!r} -> {want!r}", want.lower() in got.lower() and got != "", got)
# ordinary text with a weekday or a date word that is no plan stays uncaught
for line in ("home-agent: read Monday's incident log", "home-agent: the Monday standup notes say it works", "home-agent: it failed on Monday", "home-agent: the fix merged on Monday",
             "home-agent: the job has been red since Monday", "home-agent: compare with last Friday's numbers", "home-agent: the build of 2026-11-01 failed", "home-agent: read the in-3-days report"):
    check(f"unit: {line!r} is no wait", SW.dated_wait(line, today) == "", SW.dated_wait(line, today))
# ordinary work that names a weekday, a day word or a run is no wait (a false refusal is the costly error)
for line in ("home-agent: re-run Monday's build and compare", "home-agent: read Monday's update from the vendor and apply it", "home-agent: review Tuesday's release notes",
             "home-agent: check Monday's deploy log for errors", "home-agent: look at Monday's sync result",
             "home-agent: Rae said on Monday that the plan holds; implement it", "home-agent: Rae told me on Monday to ship it", "home-agent: write down what Sam found on Tuesday",
             "home-agent: look into the issue seen on Monday", "home-agent: use the answer Sam gave on Thursday", "home-agent: the call on Friday went well; write it up",
             "home-agent: the check on Monday failed", "home-agent: write up the next Monday standup", "home-agent: compare with the numbers from Tuesday",
             "home-agent: the build finished in 2 days; compare timings", "home-agent: add a test for the retry in 3 days case", "home-agent: fix the retry-in-3-days config",
             "home-agent: document how the next nightly run works", "home-agent: add the next scheduled run to the docs", "home-agent: test the tomorrow parser", "home-agent: review tomorrow's agenda"):
    check(f"unit: ordinary line {line!r} is no wait", SW.dated_wait(line, today) == "", SW.dated_wait(line, today))
# a noun phrase around the day, a possessive "next week's", and verbs that only look like plans
for line in ("home-agent: write the plan for next week's planning doc", "home-agent: fix the cron so it runs next week's batch correctly",
             "home-agent: release notes for next month's version are drafted; check them", "home-agent: check why the release on Monday failed",
             "home-agent: run the test suite for the Tuesday fixture", "home-agent: schedule the review on Friday with the vendor", "home-agent: plan the demo on Thursday",
             "home-agent: queue the report for Monday's digest"):
    check(f"unit: ordinary line {line!r} is no wait", SW.dated_wait(line, today) == "", SW.dated_wait(line, today))
# a day or "next week" as a modifier of a noun, and "look" as a word of its own: no wait
for line in ("home-agent: look at the Monday failures", "home-agent: look for the Monday entry", "home-agent: look at logs on Monday night", "home-agent: look at it again after the weekend deploy failed",
             "home-agent: run tests on Monday data", "home-agent: apply patch for Tuesday build", "home-agent: retry job on Monday cluster", "home-agent: check results on Tuesday host",
             "home-agent: merge PR on Monday branch", "home-agent: deploy build on Wednesday server", "home-agent: check logs for Tuesday outage", "home-agent: ask what next week looks like",
             "home-agent: ship the release next week plan doc", "home-agent: ping the vendor regarding Monday", "home-agent: apply the policy effective Monday", "home-agent: retry the weekend job fix",
             "home-agent: wait for Monday morning's report", "home-agent: apply on Friday by noon", "home-agent: ship on Monday by 5pm"):
    check(f"unit: ordinary line {line!r} is no wait", SW.dated_wait(line, today) == "", SW.dated_wait(line, today))
# the waits that are still caught
for line, want in (("home-agent: apply at Monday's scheduled run", "Monday"), ("home-agent: after the weekend", "after the weekend"), ("home-agent: in 3 days check the build", "in 3 days"),
                   ("home-agent: re-run next Monday", "next Monday"), ("home-agent: tomorrow", "tomorrow"), ("home-agent: apply it on Monday", "on Monday"), ("home-agent: Monday: apply the step", "Monday"),
                   ("home-agent: the fix will land on Friday", "on Friday"), ("home-agent: retry in 2 weeks", "in 2 weeks"), ("home-agent: ship it tomorrow morning", "tomorrow"),
                   ("home-agent: apply on Monday", "on Monday"), ("home-agent: will ship on Friday", "on Friday"), ("home-agent: then apply on Friday", "on Friday"),
                   ("home-agent: retry on Friday", "on Friday"), ("home-agent: ship it next week", "next week"), ("home-agent: wait until next week", "next week"), ("home-agent: next week: check the build", "next week"),
                   ("home-agent: wait until Friday for the vendor build", "Friday"), ("home-agent: apply on Monday once the build is done", "on Monday"), ("home-agent: retry next week while the vendor is away", "next week"),
                   ("home-agent: wait until Monday per the vendor", "Monday"), ("home-agent: apply it on Monday during the window", "on Monday"), ("home-agent: ship tomorrow as planned", "tomorrow"),
                   ("home-agent: apply it on Monday via the cron", "on Monday")):
    got = SW.dated_wait(line, today)
    check(f"unit: still a wait {line!r} -> {want!r}", got != "" and want.lower() in got.lower(), got)
check("unit: parse_answer reads a bare object", SW.parse_answer('{"can_do_now": true, "reason": "x"}') == (True, "x"))
check("unit: parse_answer reads a fenced object with prose around it", SW.parse_answer('Sure:\n```json\n{"can_do_now": false, "reason": "y"}\n```') == (False, "y"))
check("unit: parse_answer refuses a missing boolean", SW.parse_answer('{"can_do_now": "yes"}') is None and SW.parse_answer("") is None)
q = SW.question("S", "do it", ["a wake 2026-11-20"], "because", dt.datetime(2026, 11, 4, 9, 0))
check("unit: the call's message carries the clock, the step, the wait and the reason", all(t in q for t in ("Wednesday 2026-11-04", "<step>do it</step>", "<wait>a wake 2026-11-20</wait>", "<reason>because</reason>")), q)

print(("ok" if not fails else "FAILED") + f": self_wait scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
