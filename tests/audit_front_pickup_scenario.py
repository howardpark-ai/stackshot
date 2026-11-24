"""Scenario test for the turn started for an idle front agent with an open step of its own (audit/front_pickup.py, service/audit_ticks._front_pickup_tick, run from the ten-minute audit tick after the idle hand-over and before the
busy-stretch tell; it rides `[audit] hourly_line`). Fixture items in a temporary store, a fake clock (the tick is given its `now`), the fleet's agent-state snapshot passed in as the audit reads it, the owner's presence as the
prompt stamps say it, no network, no model call, no message really sent: every notice goes to a stand-in for `tell_woken` that records it and answers as a delivery would.

  1  the probe: an item an idle front agent moves, whose first open step is its own, quiet for 45 minutes, gets ONE line to that agent (the item, its open step, no reply owed, the tag that makes a turn), the item is not written, the record
     `<state>/front-pickup.json` holds the mark and no temporary file is left; 44 minutes of quiet starts nothing, 45 does
  2  once an hour: a tick 10 minutes later and one 59 minutes later start nothing, the one an hour on starts it again
  3  the owner in the conversation: a fresh last-prompt time for that pane (found by its session id in the fleet's index) starts nothing, an old one does, another pane's last-prompt time does not matter; a stamp folder or an index that cannot be read starts nothing
  4  a waiting item starts nothing: a hold (dated or not), an until, an open after, an anchor wait, a relay, a parked item, an item that waits on a decision, the owner's move, a closed item
  5  whose step: the owner's step first, a step naming nobody, another session's step, the owner's step before the agent's own; the agent's own steps first and another's behind them start it and the line names the leading run only (three, then a count),
     a bare sub-step is no step, an item with no steps starts nothing
  6  the agent state: busy, unknown, unread, missing from the snapshot, a snapshot 16 minutes old, one dated ahead, none at all start nothing; a fresh idle one starts it
  7  who: a background agent's own step stays with the idle hand-over (nothing sent here, the hand-over still finds the item); a front agent of another project, a keeper that is no front agent of its own project, a name no page lists
  8  a failed delivery sets no mark: the record is taken back, the next tick tries again; a send that raises, a stand-in that returns no thread, a record that cannot be written
  9  the cap: `MAX_TURNS_PER_TICK` turns in a tick, one turn per agent, the rest on the next tick
  10 reads that fail start nothing and say so once: a torn or foreign record (set aside, the next tick starts a clean one), a snapshot, the roles, the presence reader, one item that cannot be read among others
  11 one action per item per tick: the busy-stretch tell wins (and the item is not nudged again within the hour), the idle hand-over wins, a different item is not held back by either
  12 the record: pruned of closed items and old marks, a mark dated ahead beyond the hour is torn, one within it blocks, written whole
  13 the tick: it stands still with the hourly line off, in a read-only copy, with the board paused, in agent mode; `_silence_tick` runs it after the idle hand-over and before the busy tell, and one that fails stops nothing; the probe end to end
  15 the re-read before the send (an item closed, reassigned, held or written to between the pick and the send is not told and gets no mark) and the state half of the idle test (pane word `idle`, state `busy`: nothing is started), each shown to fail once its rule is reverted

    tests/run-suite audit_front_pickup       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontpickup-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: never the host's pane registry
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/prompts", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
FRONTS = ("a-main", "b-main", "c-main", "d-main")
NAMES = (*FRONTS, "a-keep", "b-keep", "c-keep", "d-keep", "a-back", "b-back", "c-back", "d-back", "ghost")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
pages = {f"projects/{p}": (f"{p}-keep", {f"{p}-main": "the front", f"{p}-back": "builds, merges and releases the code"}) for p in "abcd"}
pages = {k.replace("projects/a", "projects/alpha").replace("projects/b", "projects/beta").replace("projects/c", "projects/gamma").replace("projects/d", "projects/delta"): v for k, v in pages.items()}
PROJ = {"a": "projects/alpha", "b": "projects/beta", "c": "projects/gamma", "d": "projects/delta"}
(T / "store/projects.json").write_text(json.dumps({"pages": {k: {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": s, "status": "active", "board": [], "board_open": 0,
                                                                  "agents": ag, "back_agents": {n: m for n, m in ag.items() if not n.endswith("-main")}} for k, (s, ag) in pages.items()}}))
for k, (s, ag) in pages.items():
    back = "".join(f"    {n}: {m}\n" for n, m in ag.items() if not n.endswith("-main")); front = "".join(f"  {n}: {m}\n" for n, m in ag.items() if n.endswith("-main"))
    (T / f"brain/{k}.md").parent.mkdir(parents=True, exist_ok=True)
    (T / f"brain/{k}.md").write_text(f"---\ntitle: {k}\ndisplay-name: {s}\nagents:\n{front}  background:\n{back}---\n\n# {k}\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server, wiring
from stackshot.service import audit_ticks as audit_ticks_svc
from stackshot.service import agent_state as agent_state_svc
from stackshot.service import handoff as handoff_svc
from stackshot.service import telling
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.core import readonly as _ro
from stackshot.core import config as _cfg
from stackshot.web.tools import text as _web_tools_text
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.audit import front_pickup as FP, hourly as HR, hand_idle as HI, busy_tell as BT, agent_state as AS
from stackshot.tools import next_report as NR
_web_publish._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
_fleet_sessions_registry._sessions_index = lambda: {u: {"name": n} for n, u in U.items()}      # the fleet's index: a pane's session id -> its name (the prompt stamps are named by the id)
_cfg.CFG["audit"]["pattern_review"] = "off"
_cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every notice the server was asked to send: (items, recipient's id, text, tag)
outcome = {"ok": True, "none": False, "raise": False}              # what the stand-in for tell_woken does: delivers, fails to deliver, returns no thread, raises
def fake_tell(gid, owner, note, tag="wake", result=None):
    sent.append((gid, owner, note, tag))
    if outcome["raise"]: raise OSError("push is down")
    if outcome["none"]: return None
    if result is not None: result.update(ok=outcome["ok"], why="" if outcome["ok"] else "the pane is gone")
    th = threading.Thread(target=lambda: None); th.start()
    return th
telling.tell_woken = fake_tell
handoff_svc.handoff_pane = lambda who, idx=None: ""

def put(i, mover="a-main", status="open", act=60, project="projects/alpha", log=None, nxt=None, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0. `nxt` is its next text (the steps), by default one step of the mover's own. `log` = [(minutes after the activity, kind)] of audit lines, kind idle | pane."""
    base = {"owner": U["a-main"], "project": project, "next": f"{mover}: do the thing" if nxt is None else nxt, "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at_ = now0 - act * MIN
    if log is not None:
        base["hourly_audit"] = {"log": [{"at": at_ + m * MIN, "text": "Audit 10:00: " + ("idle, nothing verified" if k == "idle" else "verified the mover's pane is in a turn (live state only, nothing recorded on the item)"),
                                         "kind": "audit_idle" if k == "idle" else "audit", **({"pane_only": True} if k == "pane" else {})} for m, k in log]}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at_, "confirmed": now0 - 2 * MIN,
                                                       "activity": at_, "written_at": at_, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def marks_file(): return T / "state/front-pickup.json"
def stamps_dir(): return T / "state/prompts"
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    for p_ in stamps_dir().glob("*"): p_.unlink()
    for p_ in (T / "state").glob("*front-pickup*"): p_.unlink()
    sent.clear(); (T / "store/anchors.json").write_text("{}"); outcome.update(ok=True, none=False, raise_=False, raise_x=False); outcome["raise"] = False
    for k in ("hourly_line", "hand_idle", "busy_tell"): _cfg.CFG["audit"].pop(k, None)
    _cfg.CFG["audit"]["mode"] = "script"
def at(m): return now0 + m * MIN
def snap(t, states=None, age=0.0):
    """The fleet's agent-state snapshot as the route stores it: every front agent idle unless `states` says otherwise ({name: idle | busy | unread | unknown | None for absent})."""
    st = {n: "idle" for n in (*FRONTS, "a-back")}; st.update(states or {})
    ag = {n: {"state": "unknown" if s == "unread" else s, "since": t - H, "why": "", "pane": {"idle": "idle", "busy": "turn"}.get(s, ""), "read": s != "unread", "subagents": []} for n, s in st.items() if s is not None}
    return {"schema": 1, "written": t - age, "agents": ag}
NOT_THERE = lambda who: False
def tp(m=0, states=None, age=0.0, snap_=None, present=NOT_THERE, **kw):
    """One tick of the pick-up `m` minutes after now0, the snapshot as `snap` builds it; `present` None reads the owner's prompt stamps as the server does. → the ids a turn was started for."""
    t = at(m)
    return audit_ticks_svc._front_pickup_tick(now=t, snap=snap(t, states, age) if snap_ is None else snap_, present=present, **kw)
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()
    @property
    def pickup_lines(self): return [l for l in self.buf.getvalue().splitlines() if "front pick-up" in l and "told of its own step" not in l]
def marks(): return FP.read_marks() if marks_file().exists() else {}
def stamp(name, minutes_ago, m=0): (stamps_dir() / U[name]).write_text(f"{at(m) - minutes_ago * MIN}\n")
def to(name): return [x for x in sent if x[1] == U[name]]

# ================================================================ 1. the probe
check("1 the constants: an hour between turns for one item, the first hourly line's own 45 minutes of quiet, three turns a tick", FP.GAP == 3600.0 and FP.QUIET == HR.EVERY == 45 * MIN and FP.MAX_TURNS_PER_TICK == 3)
wipe(); put(1, act=60); before = rd(1)
got = tp(0, present=None)      # the real presence reader: an empty stamp folder, the fleet's index
check("1 an idle front agent with its own first open step, the item quiet for an hour: its turn is started, once", got == ["a1"] and len(sent) == 1 and sent[0][1] == U["a-main"] and sent[0][0] == "a1", (got, sent))
m = sent[0][2] if sent else ""
check("1 the line: the item and its project, the agent's own step by its first line, that it is idle and what is asked, no owner mark, no reply owed, the tag that makes a turn of a front agent",
      m.startswith("[stackshot] ") and "[home] item 1" in m and "projects/alpha" in m and '"do the thing"' in m and "you are idle" in m and "Take it, or write what blocks it" in m and "No reply is owed to the audit" in m
      and _web_tools_text._FOR_OWNER not in m and m.count("\n") == 1 and sent[0][3] == "stall", m)
check("1 the item is not written (the pick-up sends a line and records its own mark elsewhere)", rd(1) == before)
check("1 the mark is in <state>/front-pickup.json, whole, with no temporary file beside it", marks() == {"a1": at(0)} and json.loads(marks_file().read_text())["schema"] == 1 and not list((T / "state").glob(".front-pickup*")), (marks(), list((T / "state").iterdir())))
wipe(); put(1, act=44)
check("1 44 minutes of quiet start nothing, 45 do (the first hourly line's own threshold)", tp(0) == [] and sent == [] and tp(1) == ["a1"] and len(sent) == 1, sent)

# ================================================================ 2. once an hour
wipe(); put(1, act=60)
first = tp(0); between = [tp(k) for k in (10, 20, 30, 40, 50, 59)]
check("2 the turn is started, and not again 10, 20 … 59 minutes later", first == ["a1"] and between == [[]] * 6 and len(sent) == 1, (first, between, len(sent)))
again = tp(60)
check("2 an hour after it, still idle and still its own step: started again, the mark moves on", again == ["a1"] and len(sent) == 2 and marks() == {"a1": at(60)}, (again, sent, marks()))
check("2 …and not at 119 minutes", tp(119) == [] and len(sent) == 2 and tp(120) == ["a1"] and len(sent) == 3)

# ================================================================ 3. the owner in that conversation
wipe(); put(1, act=60); stamp("a-main", 5)
check("3 his last prompt in that pane 5 minutes ago (the stamp is named by the pane's session id, found in the fleet's index): nothing is started", tp(0, present=None) == [] and sent == [] and marks() == {})
stamp("a-main", telling.presence_minutes() + 1)
check("3 …older than the presence window: started", tp(1, present=None) == ["a1"] and len(sent) == 1, sent)
wipe(); put(1, act=60); stamp("b-main", 2)
check("3 a fresh stamp of another pane does not matter", tp(0, present=None) == ["a1"], sent)
wipe(); put(1, act=60); stamp("a-main", 5)
check("3 the present test it is given decides (a stand-in that says present starts nothing; one that says absent does, whatever the stamp says)", tp(0, present=lambda w: True) == [] and tp(1, present=lambda w: False) == ["a1"])
wipe(); put(1, act=60); stamp("a-main", 5)
real_index = _fleet_sessions_registry._sessions_index
_fleet_sessions_registry._sessions_index = lambda: {}      # the index does not name the pane: the stamp is still found by the agent's own session id
check("3 a pane the index does not list is found by the agent's session id all the same", tp(0, present=None) == [])
_fleet_sessions_registry._sessions_index = real_index
wipe(); put(1, act=60)
import shutil
shutil.rmtree(stamps_dir())
with _Err() as e3:
    got3 = tp(0, present=None)
stamps_dir().mkdir()
check("3 a stamp folder that cannot be read starts nothing, with one line saying so", got3 == [] and sent == [] and len(e3.pickup_lines) == 1, (got3, e3.text))
def boom_index(): raise OSError("the fleet index is unreadable")
_fleet_sessions_registry._sessions_index = boom_index
with _Err() as e3b:
    got3b = tp(1, present=None)
_fleet_sessions_registry._sessions_index = real_index
check("3 …and so does a fleet index that cannot be read", got3b == [] and sent == [] and len(e3b.pickup_lines) == 1, (got3b, e3b.text))

# ================================================================ 4. a waiting item
future_day = time.strftime("%Y-%m-%d", time.gmtime(now0 + 40 * 86400))
future_at = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 40 * 86400))
waits = [("a hold with no date", dict(hold=True)), ("a hold until a dated wake", dict(hold=True, wake=future_at)), ("an until", dict(until=future_day)), ("a wake on a doing item", dict(wake=future_at, until=future_at)),
         ("an anchor wait", dict(wait_kind="anchor", wait_anchor="https://example.invalid/pr/1", until=future_day)), ("a relay wait", dict(wait_kind="relay")),
         ("a parked item", dict(state="parked", hold=True, wake=future_at)), ("a wait on a decision", dict(state="your-call", needs=["decision"], ask="pick one")),
         ("the owner as the mover", dict(mover="Oliver", state="your-step"))]
for label, extra in waits:
    wipe(); put(1, act=120, **extra)
    check(f"4 {label}: nothing is started", tp(0) == [] and sent == [] and marks() == {}, (extra, sent))
wipe(); put(2, act=1); put(1, act=120, state="blocked", supplies="its output", after=["a2"])
check("4 an item behind an open one (after): nothing is started", tp(0) == [] and sent == [])
wipe(); put(1, act=120, status="completed", outcome="done")
check("4 a closed item: nothing is started", tp(0) == [] and sent == [])
wipe(); put(1, act=120)
check("4 the same item with none of those is started (the control)", tp(0) == ["a1"], sent)

# ================================================================ 5. whose step
cases = [("the owner's step first", "Oliver: approve it", False), ("a step that names nobody (his, as the model reads it)", "approve it", False), ("another session's step", "a-back: build it", False),
         ("the owner's step before the agent's own", "Oliver: approve it\na-main: then ship it", False), ("another session's step before the agent's own", "a-back: build it\na-main: then ship it", False),
         ("no step at all", "", False), ("the agent's own step", "a-main: ship it", True)]
for label, nxt, want in cases:
    wipe(); put(1, act=120, nxt=nxt)
    got = tp(0)
    check(f"5 {label}: {'started' if want else 'nothing is started'}", (got == ["a1"]) is want and (len(sent) == 1) is want, (nxt, got, sent))
wipe(); put(1, act=120, nxt="a-main: first thing\nOliver: approve\na-main: last thing")
tp(0); m5 = sent[0][2] if sent else ""
check("5 the agent's own steps first and the owner's behind them: started, and the line names the leading run only", '"first thing"' in m5 and "last thing" not in m5 and "an open step is yours" in m5, m5)
wipe(); put(1, act=120, nxt="a-main: first thing\n- a sub step of it\na-main: second thing")
tp(0); m5 = sent[0][2] if sent else ""
check("5 a bare sub-step is part of the line above: it is no step, it does not end the run and it is not named", '"first thing"' in m5 and '"second thing"' in m5 and "sub step" not in m5 and "2 open steps are yours" in m5, m5)
wipe(); put(1, act=120, nxt="\n".join(f"a-main: step {k}" for k in range(1, 6)))
tp(0); m5 = sent[0][2] if sent else ""
check("5 five open steps of its own: one line naming three and counting the rest, never one line a step", '"step 1"' in m5 and '"step 3"' in m5 and '"step 4"' not in m5 and "(and 2 more)" in m5 and "5 open steps are yours" in m5 and len(sent) == 1, m5)
wipe(); put(1, act=120, nxt="a-main: " + "long " * 60)
tp(0); m5 = sent[0][2] if sent else ""
check("5 a long step is quoted by its first line, clipped", "…" in m5 and len(m5) < 400, len(m5))

# ================================================================ 6. the agent state
def started_with(**kw):
    wipe(); put(1, act=120); got = tp(0, **kw); return got
check("6 a fresh idle snapshot starts it (the control)", started_with() == ["a1"])
for label, kw in (("busy", dict(states={"a-main": "busy"})), ("unknown", dict(states={"a-main": "unknown"})), ("not read", dict(states={"a-main": "unread"})), ("absent from the snapshot", dict(states={"a-main": None})),
                  ("a snapshot 16 minutes old", dict(age=16 * MIN)), ("a snapshot dated ahead of the clock", dict(age=-10 * MIN)), ("no snapshot", dict(snap_={}))):
    got = started_with(**kw)
    check(f"6 {label}: nothing is started", got == [] and sent == [] and marks() == {}, (got, sent))
check("6 a snapshot 14 minutes old still reads", started_with(age=14 * MIN) == ["a1"])
check("6 only the agent's own entry counts: another agent idle in a snapshot that has the mover busy starts nothing", started_with(states={"a-main": "busy", "b-main": "idle"}) == [])

# ================================================================ 7. who
wipe(); put(1, mover="a-back", act=120, nxt="a-back: build it", log=[(50, "idle")])
got7 = tp(0)
rows = HI.due_all(NR.load_all(None), now0, lambda w, p: telling.front_keeper(w, p)[0])
check("7 a background agent's own open step, idle: nothing is sent here, and the idle hand-over still finds the item as it did", got7 == [] and sent == [] and [g for g, _r in rows] == ["a1"], (got7, rows))
wipe(); put(1, mover="b-main", project="projects/alpha", act=120, nxt="b-main: ship it")
check("7 a front agent of another project than the item's: nothing is started", tp(0) == [] and sent == [])
wipe(); put(1, mover="a-keep", act=120, nxt="a-keep: ship it")
check("7 the project's own keeper is no front agent of it (the server's answer, as the other passes use): nothing is started", tp(0, states={"a-keep": "idle"}) == [] and sent == [])
wipe(); put(1, mover="ghost", act=120, nxt="ghost: ship it")
check("7 a name no page lists: nothing is started", tp(0, states={"ghost": "idle"}) == [] and sent == [])
wipe(); put(1, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
check("7 a front agent of its own project is started (the control)", tp(0) == ["a1"] and sent[0][1] == U["b-main"])

# ================================================================ 8. a delivery that fails: a half-hour backoff, not a retry every ten minutes
BACKOFF_MARK = lambda m: at(m) - FP.GAP + FP.FAIL_BACKOFF      # the mark a failed delivery leaves: it blocks for FAIL_BACKOFF from the send
check("8 the backoff is half an hour, under the hour", FP.FAIL_BACKOFF == 1800.0 and FP.FAIL_BACKOFF < FP.GAP)
wipe(); put(1, act=120); outcome["ok"] = False
with _Err() as e8:
    got8 = tp(0)
check("8 a delivery that fails starts nothing, is not counted or logged as told, and leaves the half-hour backoff mark; one line says it was not delivered", got8 == [] and len(sent) == 1 and marks() == {"a1": BACKOFF_MARK(0)}
      and "not delivered" in e8.text and "told of its own step" not in e8.text, (got8, marks(), e8.text))
outcome["ok"] = True
check("8 10 and 29 minutes later it is not tried (a push that keeps failing is not retried every ten minutes), 30 minutes later it is, and the delivery sets the full mark", tp(10) == [] and tp(29) == [] and len(sent) == 1
      and tp(30) == ["a1"] and marks() == {"a1": at(30)} and len(sent) == 2, (sent, marks()))
wipe(); put(1, act=120); outcome["ok"] = False
tp(0); tp(30); tp(60)
check("8 a push that fails every time is sent at 0, 30 and 60 minutes, three sends in an hour and a half, not nine", len(sent) == 3, len(sent))
wipe(); put(1, act=120); outcome["none"] = True
check("8 a stand-in that returns no sending thread (a notice that was held or had no owner) starts nothing and backs off the same way", tp(0) == [] and marks() == {"a1": BACKOFF_MARK(0)} and tp(10) == [])
outcome["none"] = False
wipe(); put(1, act=120); outcome["raise"] = True
with _Err() as e8b:
    got8b = tp(0)
outcome["raise"] = False
check("8 a send that raises starts nothing, one line says so, backs off, and the next try is at 30 minutes", got8b == [] and marks() == {"a1": BACKOFF_MARK(0)} and len(e8b.pickup_lines) == 1 and tp(10) == [] and tp(30) == ["a1"], (got8b, e8b.text))
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it"); outcome["ok"] = False
tp(0); outcome["ok"] = True
check("8 a failed delivery's backoff is the item's own: another item is not held back by it", tp(10) == [] and tp(30) == ["a1", "a2"] and set(marks()) == {"a1", "a2"})
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it"); outcome["ok"] = True
real_tell = telling.tell_woken
def tell_one_fails(gid, owner, note, tag="wake", result=None):
    th = real_tell(gid, owner, note, tag=tag, result=result)
    if result is not None and owner == U["a-main"]: result.update(ok=False, why="the pane is gone")
    return th
telling.tell_woken = tell_one_fails
with _Err() as e8d:
    try: got8d = tp(0)
    finally: telling.tell_woken = real_tell
check("8 the ids returned and the 'told' line are for the lines that were delivered only: one of two failed, one id and one line", got8d == ["a2"] and e8d.text.count("told of its own step") == 1 and "a2 idle front agent b-main told" in e8d.text and "a1 front pick-up not delivered" in e8d.text, (got8d, e8d.text))

wipe(); put(1, act=120)
real_write = FP.write_marks
def no_write(m): raise OSError("disk full")
FP.write_marks = no_write
with _Err() as e8c:
    got8c = tp(0)
FP.write_marks = real_write
check("8 a record that cannot be written starts nothing (no mark, no line), one line says so", got8c == [] and sent == [] and marks() == {} and len(e8c.pickup_lines) == 1, (got8c, e8c.text))

# ================================================================ 9. the cap
wipe()
for i, p in enumerate("abcd", 1): put(i, mover=f"{p}-main", project=PROJ[p], act=120, nxt=f"{p}-main: ship it")
put(5, act=120, nxt="a-main: and another")
t1 = tp(0)
check("9 four agents and a second item of the first, all due: three turns in the tick (a1, a2 and a3), one per agent (a5 waits for a1's agent to be free again)", t1 == ["a1", "a2", "a3"] and len(sent) == 3 and [x[1] for x in sent] == [U["a-main"], U["b-main"], U["c-main"]], (t1, sent))
t2 = tp(10)
check("9 the next tick takes the rest: the fourth agent's item and the first agent's second item", t2 == ["a4", "a5"] and len(sent) == 5, (t2, sent))
check("9 …and then nothing is left", tp(20) == [] and len(sent) == 5)
check("9 the cap is a constant of the module (3)", FP.MAX_TURNS_PER_TICK == 3 and FP.pick([(f"a{k}", {"mover": f"x{k}"}) for k in range(10)], lambda a, b: a == b) == [(f"a{k}", {"mover": f"x{k}"}) for k in range(3)])

# ================================================================ 10. reads that fail
wipe(); put(1, act=120); marks_file().write_text("{ torn")
with _Err() as e10:
    got10 = tp(0)
check("10 a torn record starts nothing, one line says so, and it is set aside so the next tick starts clean", got10 == [] and sent == [] and len(e10.pickup_lines) == 1 and not marks_file().exists() and (T / "state/front-pickup.json.torn").exists(), (got10, e10.text))
check("10 …the next tick starts it", tp(10) == ["a1"] and marks() == {"a1": at(10)})
wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 9, "marks": {}}))
with _Err() as e10:
    got10 = tp(0)
check("10 a record of another schema is no record: nothing is started, one line", got10 == [] and len(e10.pickup_lines) == 1, e10.text)
wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a1": "yesterday", "a2": True, "a3": float("nan")}}))
check("10 a mark that is no number (text, a boolean, nan) is no mark: the item is started", tp(0) == ["a1"])
wipe(); put(1, act=120)
real_snap = AS.snapshot
def boom_snap(): raise OSError("agent-state.json is unreadable")
AS.snapshot = boom_snap
with _Err() as e10:
    try: got10 = audit_ticks_svc._front_pickup_tick(now=at(0), present=NOT_THERE)
    finally: AS.snapshot = real_snap
check("10 a snapshot that cannot be read starts nothing, one line", got10 == [] and sent == [] and len(e10.pickup_lines) == 1, e10.text)
wipe(); put(1, act=120)
def boom_front(who, project): raise RuntimeError("roles unreadable")
got10 = tp(0, front=boom_front)
check("10 a role map that cannot be read starts nothing", got10 == [] and sent == [])
wipe(); put(1, act=120)
real_reader = audit_ticks_svc._owner_present_reader
def boom_reader(now): raise OSError("stamps unreadable")
audit_ticks_svc._owner_present_reader = boom_reader
with _Err() as e10:
    try: got10 = audit_ticks_svc._front_pickup_tick(now=at(0), snap=snap(at(0)))
    finally: audit_ticks_svc._owner_present_reader = real_reader
check("10 a presence reader that cannot read starts nothing, one line", got10 == [] and sent == [] and len(e10.pickup_lines) == 1, e10.text)
def boom_present(who): raise OSError("stamp unreadable")
wipe(); put(1, act=120)
check("10 a presence test that raises for the agent reads as no start", tp(0, present=boom_present) == [] and sent == [])
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
real_run = FP.own_run
def own_run_bad(meta, mover, same):
    if mover == "a-main": raise ValueError("a step list that cannot be read")
    return real_run(meta, mover, same)
FP.own_run = own_run_bad
with _Err() as e10:
    try: got10 = tp(0)
    finally: FP.own_run = real_run
check("10 one item that cannot be read starts nothing for it and stops no other: one line names it", got10 == ["a2"] and len(e10.pickup_lines) == 1 and "a1 not read" in e10.pickup_lines[0], (got10, e10.text))

# ================================================================ 11. one action per item per tick
# the busy-stretch tell: a front agent's item with only hourly lines for 4 hours
def busy_item(i=1, mover="b-main", project="projects/beta"):
    put(i, mover=mover, project=project, act=300, nxt=f"{mover}: ship it", log=[(60, "pane"), (110, "pane"), (160, "pane"), (210, "pane"), (260, "pane"), (298, "pane")])
wipe(); busy_item()
bt_rows = BT.due_all(NR.load_all(None), now0, lambda w, p: telling.front_keeper(w, p)[0], {}, 4.0)
check("11 the fixture: the busy-stretch tell is due for the front agent's item", [g for g, _r in bt_rows] == ["a1"] and bt_rows[0][1]["kind"] == "front", bt_rows)
got11 = tp(0)
check("11 the busy-stretch tell wins: the pick-up starts nothing for an item it acts on in this tick", got11 == [] and sent == [] and marks() == {})
told = audit_ticks_svc._busy_tell_tick(now=now0)
check("11 …and the tell sends its one line to that agent", told == ["a1"] and len(sent) == 1 and sent[0][1] == U["b-main"] and sent[0][3] == "stall", (told, sent))
check("11 the pick-up does not nudge the item again within the hour of the tell (10 and 59 minutes later)", tp(10) == [] and tp(59) == [] and len(sent) == 1, sent)
check("11 …and does an hour after it, if the agent is still idle on its own step", tp(61) == ["a1"] and len(sent) == 2, sent)
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
real_due_all = HI.due_all
HI.due_all = lambda items, now, front=None: [("a1", {"mover": "a-main", "project": "projects/alpha", "line_at": now, "told_none": False})]
try: got11 = tp(0)
finally: HI.due_all = real_due_all
check("11 the idle hand-over wins: an item it acts on in this tick is not picked up, another item is", got11 == ["a2"] and [x[1] for x in sent] == [U["b-main"]], (got11, sent))
wipe(); put(1, act=120, nxt="a-main: ship it", log=[(50, "idle")])
row = HI.due(NR.load_all(None), "a1", now0, lambda w, p: telling.front_keeper(w, p)[0])
check("11 by construction the two do not meet: the idle hand-over leaves a front agent's item with an open step of its own where it is", row is None and tp(0) == ["a1"], (row, sent))
wipe(); put(1, act=120); _cfg.CFG["audit"]["busy_tell"] = False; _cfg.CFG["audit"]["hand_idle"] = False
check("11 with the other two passes off the pick-up still runs", tp(0) == ["a1"])

# ================================================================ 12. the record
wipe(); put(1, act=120); put(2, status="completed", outcome="done", act=10)
marks_file().write_text(json.dumps({"schema": 1, "marks": {"a2": at(-5), "a9": at(-5), "a7": at(-90)}}))      # a closed item's mark, a missing item's, an old one
tp(0)
check("12 the record is pruned when it is written: a closed item's and an expired mark go, the new one is in, and the mark of an item this tick's list does not hold stays until it expires (an item that could not be read this tick is not started for twice in an hour)", marks() == {"a1": at(0), "a9": at(-5)}, marks())
wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a1": at(0) + 5 * H}}))
check("12 a mark dated more than an hour ahead of the clock is torn: the item is started", tp(0) == ["a1"])
wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a1": at(0) + 20 * MIN}}))
check("12 a mark dated 20 minutes ahead (a clock a little off) still blocks", tp(0) == [] and sent == [])
wipe(); put(1, act=120)
check("12 marked_recently, pure: an hour is the edge, ahead beyond an hour is torn, a non-number is none", FP.marked_recently({"a": 100.0}, "a", 100.0 + 3599) and not FP.marked_recently({"a": 100.0}, "a", 100.0 + 3600)
      and not FP.marked_recently({"a": 100.0 + 3601}, "a", 100.0) and FP.marked_recently({"a": 100.0 + 3600}, "a", 100.0) and not FP.marked_recently({"a": "x"}, "a", 5.0) and not FP.marked_recently({}, "a", 5.0))
check("12 unmark changes only the mark it wrote (a later one stays), and into a half-hour backoff, not none", (FP.mark("a1", 500.0), FP.unmark("a1", 499.0), FP.read_marks().get("a1"))[2] == 500.0 and FP.unmark("a1", 500.0) is True and FP.read_marks().get("a1") == 500.0 - FP.GAP + FP.FAIL_BACKOFF and FP.marked_recently(FP.read_marks(), "a1", 500.0 + FP.FAIL_BACKOFF - 1) and not FP.marked_recently(FP.read_marks(), "a1", 500.0 + FP.FAIL_BACKOFF))

# ================================================================ 13. the tick
wipe(); put(1, act=120); _cfg.CFG["audit"]["hourly_line"] = False
check("13 with the hourly line off the pick-up stands still", tp(0) == [] and sent == [])
wipe(); put(1, act=120)
real_ro = _ro.is_read_only; _ro.is_read_only = lambda: True
try: got13 = tp(0)
finally: _ro.is_read_only = real_ro
check("13 a read-only standby copy starts nothing", got13 == [] and sent == [])
real_paused = handoff_svc.handoff_paused; handoff_svc.handoff_paused = lambda: True
try: got13 = tp(0)
finally: handoff_svc.handoff_paused = real_paused
check("13 a paused board starts nothing", got13 == [] and sent == [])
_cfg.CFG["audit"]["mode"] = "agent"
audit_ticks_svc._silence_tick()
check("13 the audit tick in agent mode does nothing at all", sent == [])
_cfg.CFG["audit"]["mode"] = "script"
order = []
real_hi, real_fo, real_fp, real_bt = audit_ticks_svc._hand_idle_tick, audit_ticks_svc._front_handon_tick, audit_ticks_svc._front_pickup_tick, audit_ticks_svc._busy_tell_tick
audit_ticks_svc._front_handon_tick = lambda *a, **k: order.append("handon") or []
audit_ticks_svc._hand_idle_tick = lambda *a, **k: order.append("hand_idle") or []
audit_ticks_svc._front_pickup_tick = lambda *a, **k: (order.append("pickup"), (_ for _ in ()).throw(RuntimeError("the pick-up failed")))[0]
audit_ticks_svc._busy_tell_tick = lambda *a, **k: order.append("busy_tell") or []
with _Err() as e13:
    try: audit_ticks_svc._silence_tick()
    finally: audit_ticks_svc._hand_idle_tick, audit_ticks_svc._front_handon_tick, audit_ticks_svc._front_pickup_tick, audit_ticks_svc._busy_tell_tick = real_hi, real_fo, real_fp, real_bt
check("13 the audit tick runs it after the idle hand-over and the front hand-on and before the busy tell, and a pick-up that raises stops nothing (one line)", order == ["hand_idle", "handon", "pickup", "busy_tell"] and "idle front agents not picked up" in e13.text, (order, e13.text))
# the probe end to end: the real tick, the snapshot as the route stores it, an idle front agent, an item of its own
wipe(); put(1, act=50)
body = snap(time.time(), {"a-back": "busy"});      # the project's background agent is in a turn: no one is free, so the item is the pick-up's (a free one would take it, audit_front_handon)
code, resp = agent_state_svc.post("machine-a", body)
check("13 the fixture: the route stores the snapshot", code == 200, (code, resp))
audit_ticks_svc._silence_tick()
check("13 the probe: an item on an idle front agent gets its turn started by the audit tick, once, naming the item and its step", len(to("a-main")) == 1 and "[home] item 1" in to("a-main")[0][2] and '"do the thing"' in to("a-main")[0][2], sent)
audit_ticks_svc._silence_tick()
check("13 …and the tick after it starts nothing more (the mark)", len(to("a-main")) == 1 and set(marks()) == {"a1"}, (sent, marks()))
check("13 the owner is never told: every recipient is a session", all(x[1] in U.values() for x in sent) and not any(x[1] in ("Oliver", "") for x in sent))

# ================================================================ 14. the review's findings: a partial index, a read that failed for now, the pane word, a stamp from the future, one turn per agent, the re-read, the roles
class PartialIdx(dict):
    unreadable = ["b"]      # a machine whose sessions.json could not be read when the index was built (sessions_registry._sessions_index sets it)
wipe(); put(1, act=120); stamp("a-main", 5)
_fleet_sessions_registry._sessions_index = lambda: PartialIdx({u: {"name": n} for n, u in U.items()})
with _Err() as e14:
    try: got14 = tp(0, present=None)
    finally: _fleet_sessions_registry._sessions_index = real_index
check("14 a partial fleet index (a machine's sessions.json not read) starts nothing, one line says so: a pane on that machine has no row, so no stamp would be found", got14 == [] and sent == [] and len(e14.pickup_lines) == 1 and "partial" in e14.text and "b" in e14.text, (got14, e14.text))
wipe(); put(1, act=120)
class WholeIdx(dict):
    unreadable = []
_fleet_sessions_registry._sessions_index = lambda: WholeIdx({u: {"name": n} for n, u in U.items()})
try: got14 = tp(0, present=None)
finally: _fleet_sessions_registry._sessions_index = real_index
check("14 an index with no unreadable machine is whole (the control)", got14 == ["a1"], got14)
# a transient OSError on the record is not a torn record
wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a9": at(-5)}})); keep_text = marks_file().read_text()
real_read_text = pathlib.Path.read_text
def read_text_fails(self, *a, **k):
    if self.name == "front-pickup.json": raise PermissionError("busy for now")
    return real_read_text(self, *a, **k)
pathlib.Path.read_text = read_text_fails
with _Err() as e14b:
    try: got14b = tp(0)
    finally: pathlib.Path.read_text = real_read_text
check("14 a record that cannot be read for now (an OSError) starts nothing, one line says so, and is NOT set aside: the file is where it was, unchanged", got14b == [] and sent == [] and len(e14b.pickup_lines) == 1 and marks_file().read_text() == keep_text and not (T / "state/front-pickup.json.torn").exists(), (got14b, e14b.text))
check("14 …and the next tick, the read working again, starts the item and keeps the other mark", tp(10) == ["a1"] and marks() == {"a1": at(10), "a9": at(-5)}, marks())
wipe(); put(1, act=120); marks_file().write_bytes(b"\xff\xfe not text")
with _Err() as e14c:
    got14c = tp(0)
check("14 a record that is no text at all is torn: set aside, nothing is started", got14c == [] and (T / "state/front-pickup.json.torn").exists() and not marks_file().exists() and len(e14c.pickup_lines) == 1, (got14c, e14c.text))
# the pane word
def snap_pane(word):
    s = snap(at(0)); s["agents"]["a-main"]["pane"] = word; return s
for word in ("shell", "sleeping", "turn", ""):
    wipe(); put(1, act=120)
    check(f"14 a front agent the snapshot calls idle but whose pane word is '{word}' starts nothing (a line to such a pane is queued, not a turn)", tp(0, snap_=snap_pane(word)) == [] and sent == [], (word, sent))
wipe(); put(1, act=120)
check("14 the pane word `idle` starts it (the control)", tp(0, snap_=snap_pane("idle")) == ["a1"])
# a stamp from the future
wipe(); put(1, act=120); stamp("a-main", -1)      # dated one minute ahead of the clock: clocks a little apart
check("14 a last-prompt time dated ahead of the clock (clock skew) is the owner just now: present, nothing is started", tp(0, present=None) == [] and sent == [])
wipe(); put(1, act=120); stamp("a-main", -5 * 3600)
check("14 …a stamp hours ahead too (fail closed)", tp(0, present=None) == [] and sent == [])
wipe(); put(1, act=120); stamp("a-main", telling.presence_minutes() + 1)
check("14 …and a stamp older than the window is absent (the control)", tp(0, present=None) == ["a1"])
# the notices' own presence test is asked too
wipe(); put(1, act=120)
real_present = audit_ticks_svc._front_turn.present
audit_ticks_svc._front_turn.present = lambda who: True
try: got14 = tp(0, present=None)
finally: audit_ticks_svc._front_turn.present = real_present
check("14 `front_turn.present` (the notices' own test, which needs the pane on this box) saying present starts nothing even with no stamp", got14 == [] and sent == [], got14)
# one turn per agent per tick, with room under the cap
wipe(); put(1, act=120, nxt="a-main: first"); put(2, act=120, nxt="a-main: second"); put(3, mover="b-main", project="projects/beta", act=120, nxt="b-main: other")
check("14 two due items of one agent and one of another, under the cap of three: the first item of each agent only (the second waits for the next tick)", tp(0) == ["a1", "a3"] and [x[1] for x in sent] == [U["a-main"], U["b-main"]], sent)
# the item is read again before the send
wipe(); put(1, act=120); stale = NR.load_all(None)
put(1, act=120, status="completed", outcome="done")
check("14 an item closed since the pass read it is not told (the item is read again before the send)", tp(0, items=stale) == [] and sent == [] and marks() == {})
wipe(); put(1, act=120); stale = NR.load_all(None)
put(1, act=120, nxt="Oliver: approve it")
check("14 …nor one whose first step has become the owner's", tp(0, items=stale) == [] and sent == [])
wipe(); put(1, act=120, status="completed", outcome="done"); closed_items = NR.load_all(None)
check("14 `due` on a closed item is None", FP.due(closed_items, "a1", now0, lambda w, p: True, lambda w: True, lambda w: False, lambda a, b: a == b, {}) is None)
# a retired role, a role of another project, a name with no row
real_roles = audit_ticks_svc._anc.session_roles
real_fk = audit_ticks_svc._telling.front_keeper
audit_ticks_svc._telling.front_keeper = lambda who, project="", **k: (True, "")      # the server's own answer says front: only the role row decides here
try:
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "front", "project": "projects/alpha"}}
    check("14 a front agent listed on the item's project is front (the control)", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is True)
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "front", "project": "projects/alpha", "retired": True}}
    check("14 a retired front agent is no front agent", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is False)
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "back", "project": "projects/alpha"}}
    check("14 a background agent is no front agent", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is False)
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "front", "project": "projects/beta"}}
    check("14 a front agent of another project is not the item's", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is False)
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "front", "project": "projects/alpha"}}
    check("14 an item with no project has no front agent", audit_ticks_svc._front_of_project("a-main", "") is False)
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {}
    check("14 a name the role map does not hold is no front agent", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is False)
    audit_ticks_svc._telling.front_keeper = lambda who, project="", **k: (False, "")
    audit_ticks_svc._anc.session_roles = lambda *a, **k: {"a-main": {"role": "front", "project": "projects/alpha"}}
    check("14 the server's own answer (front_keeper) saying no wins over a role row", audit_ticks_svc._front_of_project("a-main", "projects/alpha") is False)
finally:
    audit_ticks_svc._anc.session_roles = real_roles; audit_ticks_svc._telling.front_keeper = real_fk
# a torn busy-stretch record
for label, rec, started in (("not a record", "x", True), ("an `at` that is no number", {"at": "yesterday"}, True), ("an `at` dated hours ahead", {"at": now0 + 5 * H}, True), ("an `at` that is a boolean", {"at": True}, True),
                            ("an `at` ten minutes ago", {"at": now0 - 10 * MIN}, False), ("an `at` two hours ago", {"at": now0 - 2 * H}, True)):
    wipe(); put(1, act=120, busy_tell=rec)
    check(f"14 a busy-stretch record that is {label}: {'started' if started else 'nothing is started'}", (tp(0) == ["a1"]) is started, (rec, sent))

# ================================================================ 15. the re-read before the send, and the state half of the idle test
def mutated(patches, probe):
    """Run `probe` with each (object, name, value) of `patches` replaced, restoring them after. -> the probe's answer."""
    old = [(o, n, getattr(o, n)) for o, n, _v in patches]
    for o, n, v in patches: setattr(o, n, v)
    try: return probe()
    finally:
        for o, n, v in old: setattr(o, n, v)
def rule(name, probe, patches):
    """The rule holds as the code is, and fails once `patches` revert it (a check that cannot fail proves nothing)."""
    for o_, n_, _v in patches: getattr(o_, n_)       # a patch of a name that is gone must fail here, not read as a reverted rule
    try: held = probe()
    except Exception as e_: held = f"raised {e_!r}"
    check(name, held is True, held)
    try: broke = mutated(patches, probe)
    except Exception as e_: broke = f"raised {e_!r}"
    check(name + " [mutated: the check fails]", broke is not True, broke)
seen_items = {}                                    # the list the tick was given: the reverted re-read judges the item by it, as the pass found it
real_due, real_pick = FP.due, FP.pick
def between(change, **kw):
    """One tick whose item changes after the pass picked it and before it sends (a write that lands in between): `change` runs once `FP.pick` has returned. -> the ids a turn was started for."""
    seen_items["items"] = stale_ = NR.load_all(None)
    def pick_then_change(*a, **k):
        out = real_pick(*a, **k); change(); return out
    FP.pick = pick_then_change
    try: return tp(0, items=stale_, **kw)
    finally: FP.pick = real_pick
no_reread = [(FP, "due", lambda items, gid, *a, **k: real_due(seen_items["items"], gid, *a, **k))]      # the re-read removed: the send is decided on the list the pass began with
CHANGED = (("it was closed", dict(status="completed", outcome="done")), ("its first step went to another session", dict(nxt="a-back: build it")),
           ("its mover became a session that is no front agent", dict(mover="a-back")), ("the owner's step came first", dict(nxt="Oliver: approve it")),
           ("a hold was set", dict(hold=True)), ("an until was set", dict(until=future_day)), ("it was written to just now", dict(act=1)))
for label, extra in CHANGED:
    def reread_probe(extra=extra):
        wipe(); put(1, act=120); got = between(lambda: put(1, **{"act": 120, **extra}))
        return got == [] and sent == [] and marks() == {}
    rule(f"15 an item that changed between the pick and the send ({label}) is not told and gets no mark", reread_probe, no_reread)
def reread_keeps_mark():
    wipe(); put(1, act=120); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a1": at(-70)}}))
    got = between(lambda: put(1, act=120, hold=True))
    return got == [] and sent == [] and marks() == {"a1": at(-70)}
rule("15 …and an older mark of it is kept as it was (the re-read neither marks nor takes one back)", reread_keeps_mark, no_reread)
def reread_other_item():
    wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
    got = between(lambda: put(1, act=120, status="completed", outcome="done"))
    return got == ["a2"] and [x[1] for x in sent] == [U["b-main"]] and marks() == {"a2": at(0)}
rule("15 …and it does not hold back another item of the same tick, which is told and marked", reread_other_item, no_reread)
wipe(); put(1, act=120)
check("15 a change that leaves the item due (its text rewritten, still the agent's own step) is told (the control)", between(lambda: put(1, act=120, nxt="a-main: do the thing, differently")) == ["a1"] and len(sent) == 1 and marks() == {"a1": at(0)}, (sent, marks()))
def busy_idle_pane(name="a-main"):
    s = snap(at(0)); s["agents"][name].update(state="busy", pane="idle", subagents=[{"description": "a long build", "at": at(-20)}]); return s      # a subagent runs: the state is busy although the pane word reads idle
pane_only = [(audit_ticks_svc, "_pane_idle", lambda who, now, snap_: audit_ticks_svc._agent_state(who, now, snap_).pane == "idle")]      # the state half removed: the pane word alone
def state_half_probe():
    wipe(); put(1, act=120); before = rd(1)
    got = tp(0, snap_=busy_idle_pane())
    return got == [] and sent == [] and marks() == {} and rd(1) == before
rule("15 a front agent whose pane word is `idle` but whose state is `busy` (a subagent runs) starts nothing and is told nothing", state_half_probe, pane_only)
wipe(); put(1, act=120)
check("15 …and the same agent, state and pane both idle, is started (the control)", tp(0, snap_=snap(at(0))) == ["a1"] and len(sent) == 1)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
