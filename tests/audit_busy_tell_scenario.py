"""Scenario test for a long busy stretch telling the right agent once (audit/busy_tell.py, server._busy_tell_tick, run from the ten-minute audit tick after the idle hand-over, `[audit] busy_tell` and `busy_tell_hours`):
an item on an agent whose hourly audit lines have said only "the mover's pane is in a turn" for about 4 hours, with no other write between them, tells the project's -main agent ONCE; an item a front agent holds with only
hourly lines for that long tells that front agent itself, once; the owner is never told. Fixture items in a temporary store, a fake clock (the passes are given their `now`), the pane registry replaced by a dict, no live
store, no network, no model call, no message really sent. The timelines run the real hourly tick and the real busy tick every ten minutes, so the lines the rule reads are the ones the audit writes.

  1  the switch and the threshold: the example config documents `busy_tell = true` and `busy_tell_hours = 4`, absent or a TOML true is on, false / the string "true" / 1 are off, the hours read at use (floor 1, garbage reads 4);
     a read-only copy, the board paused, the hourly line off and agent mode do nothing
  2  the timeline: busy-only lines for 3 h 59 min tell nobody, at 4 h the -main agent is told once (the message, its form, the History line, the record), at 5 h and 6 h still only that one; the owner is never told
  3  the stretch ends: real activity in the middle (the tell comes 4 h after it), a line that verified something else, an idle line mid-way, and a mover with several items (its pane verifies none of them)
  4  an item whose newest line is idle is not told of (it is the idle hand-over's), and the idle hand-over still finds it
  5  a front agent's item: the front agent itself is told once, whatever the lines said, never -main and never the owner; a busy pane or idle lines alike; real activity resets it
  6  -main: missing is a log line and never raises (the item is told of later when one appears); the mover is itself -main; one message for several items
  7  once: the record is in the item's own metadata and survives a restart, the audit's own lines are no activity and never reset it, a new stretch is told again, a torn record is no record
  8  what is read: lines ahead of now, a stale newest line, torn entries; a hold, a wait, a closed item, the owner's item and an item with no lines are left alone
  9  the tick: `_silence_tick` runs it after the hourly line and the idle hand-over, a failure in it stops nothing; the hourly log marks a pane-only line and no other
  10 a recorded commit, how long it says, a future record, the lines no other check pinned
  11 a stretch is only built from lines about an hour apart (`BT.EXTEND_GAP`): the slow cadence tells nobody, a longer gap restarts the stretch at that line, two pane-only lines at least; the wording of both History lines, the freshness margin
     (a background mover's: the same gap, up to the tell itself; a front agent's: the wide one), one unreadable item among others, a queued item
  12 the follow-up: a tell only on a fresh line, a recorded event no line has seen holds it back (the audit's own stamp does not), a log that rolled past the activity is told with the length its lines show

    tests/run-suite audit_busy_tell       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="busytell-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
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
for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-main", "team-back", "team-aux", "other-back", "beta-main", "home-peer", "home-peer2", "home-stew", "lone-back", "lone-main", "gamma-main", "delta-main", "delta-one", "delta-two")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-main": "the front", "team-back": "builds, merges and releases the code", "team-aux": "reviews the notes"}
BETA = {"beta-main": "the front", "other-back": "builds the beta code"}
LONE = {"lone-main": "the front", "lone-back": "reviews the notes"}
GAMMA = {"gamma-main": "the front"}                                      # a project with no background agent at all
DELTA = {"delta-main": "the front", "delta-one": "builds the code", "delta-two": "builds and releases the code"}      # a project with two builders
pages = {"projects/alpha": ("home-stew", ALPHA), "projects/beta": ("beta-main", BETA), "projects/gamma": ("gamma-main", GAMMA), "projects/delta": ("delta-main", DELTA)}
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
from stackshot.web import server
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import telling
from stackshot.audit import hourly as HR, hand_idle as HI, silence as SL, busy_tell as BT
from stackshot.waits import stall as ST, handoff as HO
from stackshot.audit import hourly_log as HL
from stackshot.tools import next_report as NR
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the saves below: the pass is given its `now`, and the saves stamp from the server's own clock."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = handoff_svc.time = hcold_svc.time = CLK
server._cfg.CFG["audit"]["pattern_review"] = "off"
server._cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every notice the server was asked to send: (items, recipient's id, text, tag)
def fake_tell(gid, owner, note, tag="wake", result=None): sent.append((gid, owner, note, tag)); return None
telling.tell_woken = fake_tell
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append(("message", to, text, "message")), "delivered to " + to)[1]
server._inbox_flag_send = lambda *a, **k: sent.append(("flag", "", "", "flag"))
panes = {}; dead = {}                                              # a name -> its pane's registry status; a name -> why it has no pane
def fake_status(who, idx=None):
    st = panes.get(who, "")
    if st == "boom": raise OSError("registry unreadable")
    return (st, now0 - 3600) if st else ("", 0.0)
handoff_svc.handoff_status = fake_status
handoff_svc.handoff_pane = lambda who, idx=None: dead.get(who, "")
server._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = lambda: {}

sent_at = []                                                       # when (the fake clock) each notice was sent, in step with `sent`
def fake_tell2(gid, owner, note, tag="wake", result=None): sent.append((gid, owner, note, tag)); sent_at.append(CLK.t); return None
telling.tell_woken = fake_tell2
HRS = 4
def put(i, mover="team-back", status="open", act=0, project="projects/alpha", log=None, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0. `log` = [(minutes after the activity, kind)] of audit lines already on it, kind pane | idle | unknown | other | pr."""
    base = {"owner": U["home-main"], "project": project, "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at = now0 - act * MIN
    if log is not None:
        ent = []
        for m, k in log:
            t = at + m * MIN
            tx = {"pane": "verified the mover's pane is in a turn (live state only, nothing recorded on the item)", "idle": "idle, nothing verified", "unknown": "a subagent of the mover is running, not tied to an item, nothing verified",
                  "other": "verified a subagent is running on it (live state only, nothing recorded on the item)", "pr": "verified CI failed on PR 5"}[k]
            e = {"at": t, "text": f"Audit 10:00: {tx}", "kind": {"pane": "audit", "other": "audit", "pr": "audit", "idle": "audit_idle", "unknown": "audit_unknown"}[k]}
            if k == "pane": e["pane_only"] = True
            ent.append(e)
        base["hourly_audit"] = {"log": ent}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "progress": at, "written_at": at, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def wr(i, d): (T / f"store/a/{i}.json").write_text(json.dumps(d))
def mt(i): return rd(i)["metadata"]
def lines(i): return HL.log_of(mt(i))
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    sent.clear(); sent_at.clear(); panes.clear(); dead.clear(); server._BALANCE_LOGGED.clear(); (T / "store/anchors.json").write_text("{}")
    for k in ("busy_tell", "busy_tell_hours", "hourly_line", "hand_idle"): server._cfg.CFG["audit"].pop(k, None)
def at(m): return now0 + m * MIN                                    # `m` minutes after the item's last activity in the timelines (act=0)
def hourly(t):
    CLK.t = t
    try: return server._hourly_tick(now=t, subagents=lambda who: [], anchored={})
    finally: CLK.t = None
def tick(t, **kw):
    CLK.t = t
    try: return server._busy_tell_tick(now=t, **kw)
    finally: CLK.t = None
def run(frm, to, step=10, line=True, each=None):
    """The audit ticks of minutes frm..to after the activity: the hourly line, then the busy tell; `each(m)` runs first (an event of the fixture). → the ids told."""
    out = []
    for m in range(frm, to + 1, step):
        if each: each(m)
        if line: hourly(at(m))
        out += tick(at(m))
    return out
def activity_at(i, t):
    d = rd(i); d["activity"] = d["progress"] = d["written_at"] = t; wr(i, d)
def to_main(): return [x for x in sent if x[1] == U["home-main"]]
def to(name): return [x for x in sent if x[1] == U[name]]
def history(i): return [e["text"] for e in ST.log_of(mt(i))]
def owner_free(): return all(x[1] in U.values() for x in sent) and not any(x[1] in ("Oliver", "") for x in sent)      # every recipient is a session and nobody is the owner
def S0(): return sent[0] if sent else ("", "", "", "")      # the first notice, or an empty one (a check then fails, it does not raise)
def first_told(): return (sent_at[0] - now0) / MIN if sent_at else None
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()
def pane_busy(*names):
    for n in names: panes[n] = "busy"
def seed(kinds_minutes): return [(m, k) for k, m in kinds_minutes]      # [(kind, minutes after the activity)] -> the `log` of `put`
SEVEN = [(50 * k, "pane") for k in range(1, 8)]                        # seven busy-only lines, 50 minutes apart: the newest 50 minutes before an activity 400 minutes ago

# ================================================================ 1. the switch and the threshold
EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("1 the example config documents `busy_tell = true` and `busy_tell_hours = 4` in [audit]", re.search(r"(?m)^busy_tell = true\b", EXAMPLE) is not None and re.search(r"(?m)^busy_tell_hours = 4\b", EXAMPLE) is not None)
wipe()
check("1 with the keys absent the code's defaults are on and 4 hours", BT.enabled() is True and BT.hours() == 4.0)
def hours_of(v):
    server._cfg.CFG["audit"]["busy_tell_hours"] = v
    try: return BT.hours()
    finally: server._cfg.CFG["audit"].pop("busy_tell_hours", None)
check("1 busy_tell_hours: a number is taken, never under 1; text, a boolean, nan and infinity read as 4", hours_of(6) == 6.0 and hours_of(2.5) == 2.5 and hours_of(0) == 1.0 and hours_of(-3) == 1.0 and all(hours_of(v) == 4.0 for v in ("5", True, float("nan"), float("inf"), None, [3])),
      [hours_of(v) for v in (6, 0, -3)])
for label, val in (("false", False), ("the string true", "true"), ("1", 1), ("yes", "yes")):
    wipe(); put(1, act=400, log=seed([("pane", 50), ("pane", 100), ("pane", 395)])); server._cfg.CFG["audit"]["busy_tell"] = val
    check(f"1 {label} leaves it off (only a TOML true leaves it on): nobody is told, nothing is written", BT.enabled() is False and tick(now0) == [] and sent == [] and "busy_tell" not in mt(1))
wipe(); put(1, act=400, log=SEVEN)
server._cfg.CFG["audit"]["busy_tell"] = True
check("1 a TOML true switches it on", tick(now0) == ["a1"] and len(to_main()) == 1, sent)
for label, tgt, name, val in (("a read-only standby copy", server._ro, "is_read_only", lambda: True), ("a paused board", handoff_svc, "handoff_paused", lambda: True)):
    wipe(); put(1, act=400, log=SEVEN)
    real = getattr(tgt, name); setattr(tgt, name, val)
    try: got = tick(now0)
    finally: setattr(tgt, name, real)
    check(f"1 {label} tells nobody", got == [] and sent == [] and "busy_tell" not in mt(1))
wipe(); put(1, act=400, log=SEVEN); server._cfg.CFG["audit"]["hourly_line"] = False
check("1 with the hourly line off the busy tell stands still (the lines it reads are not being written)", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, log=SEVEN); server._cfg.CFG["audit"]["mode"] = "agent"
server._silence_tick()
check("1 …and so does the tick in agent mode", sent == [])
server._cfg.CFG["audit"]["mode"] = "script"

# ================================================================ 2. the timeline
wipe(); put(1, act=0); pane_busy("team-back")
told = run(10, 230)
check("2 busy-only lines are written (the audit's own: kind audit, only the pane, marked pane_only) and nobody is told in the first 3 h 50 min", told == [] and sent == [] and len(lines(1)) >= 4 and all(l["kind"] == "audit" and l.get("pane_only") is True for l in lines(1)), (told, lines(1)))
check("2 the activity clock is untouched by the audit's lines (they are no activity)", SL.clock(rd(1), "team-back") == now0 and rd(1)["activity"] == now0)
check("2 3 h 59 min: still nobody", tick(at(239)) == [] and sent == [])
got = tick(at(240))
check("2 4 h: the -main agent is told, once", got == ["a1"] and len(sent) == 1 and S0()[1] == U["home-main"] and S0()[0] == "a1", (got, sent))
m = S0()[2]
check("2 the message is the front agent's form: `[for <owner>]` on line 1, the item and its project, the mover, about 4 hours, a request to look, no reply owed, the tag the ladder's notices use",
      m.startswith(server._FOR_OWNER + "\n[stackshot] ") and '[home] item 1' in m and "projects/alpha" in m and "team-back" in m and "about 4 hours" in m and "Please look" in m and "pane is in a turn" in m and "No reply is owed" in m and S0()[3] == "stall", m)
check("2 one History line says who was told, and the record is on the item (told at 4 h, the stretch counting from the last activity)", len(history(1)) == 1 and "home-main was told" in history(1)[0] and "about 4 hours" in history(1)[0]
      and mt(1).get("busy_tell") == {"at": at(240), "to": "home-main", "kind": "main", "since": now0}, (history(1), mt(1).get("busy_tell")))
told2 = run(250, 360)
check("2 5 h and 6 h: still only that one message and one record (told once per stretch)", told2 == [] and len(sent) == 1 and len(history(1)) == 1 and mt(1).get("busy_tell", {}).get("at") == at(240) and owner_free(), (told2, len(sent)))
check("2 the audit kept writing its hourly lines meanwhile, and none of them moved the clock", len(lines(1)) >= 6 and SL.clock(rd(1), "team-back") == now0)

# ================================================================ 3. the stretch ends
wipe(); put(1, act=0); pane_busy("team-back")
run(10, 120); activity_at(1, at(120)); told = run(130, 350)
check("3 real activity in the middle resets the stretch: nobody is told at 4 h after the first activity (and 3 h 50 min after the second)", told == [] and sent == [], (told, sent_at))
told = run(360, 370)
check("3 …the tell comes 4 h after the activity that reset it", told == ["a1"] and first_told() == 360 and mt(1).get("busy_tell", {}).get("since") == at(120), (told, first_told(), mt(1).get("busy_tell")))
def pr_event(m):
    if m == 140:
        d = rd(1); d["metadata"]["last_activity"] = {"at": at(138), "kind": "ci_result", "what": "CI failed on PR 5"}; wr(1, d)      # a recorded event: it verifies the next line besides the pane and moves no clock
wipe(); put(1, act=0); pane_busy("team-back")
told = run(10, 400, each=pr_event)
other = [l for l in lines(1) if not l.get("pane_only")]
check("3 a line that verified something else besides the pane ends the stretch: the tell comes 4 h after it, not 4 h after the activity", len(other) >= 1 and told == ["a1"] and sent_at[0] >= other[-1]["at"] + 4 * H - 1 and first_told() > 240, (told, first_told(), [(l["at"] - now0) / 60 for l in other]))
def idle_window(m):
    panes["team-back"] = "idle" if 95 <= m <= 130 else "busy"
wipe(); put(1, act=0); pane_busy("team-back")
told = run(10, 420, each=idle_window)
idl = [l for l in lines(1) if l["kind"] == "audit_idle"]
check("3 an idle line mid-way ends the stretch: nobody is told at 4 h, the tell comes 4 h after the last idle line", told == ["a1"] and first_told() > 240 and (not idl or sent_at[0] >= idl[-1]["at"] + 4 * H - 1), (told, first_told(), [(l["at"] - now0) / 60 for l in idl]))
wipe(); put(1, act=0); put(2, mover="team-back", act=0); pane_busy("team-back")
told = run(10, 400)
check("3 a mover with several items on an agent has none verified by its pane (the lines are idle), so nothing is told of busy", told == [] and sent == [] and all(l["kind"] == "audit_idle" for l in lines(1)), (told, lines(1)))

# ================================================================ 4. an idle line is the idle hand-over's
wipe(); put(1, act=0); panes["team-back"] = "idle"
told = run(10, 400)
check("4 an item whose lines are all idle is not told of, whatever the hours", told == [] and sent == [] and lines(1) and all(l["kind"] == "audit_idle" for l in lines(1)), (told, sent))
wipe(); put(1, act=300, log=seed([("pane", 50), ("pane", 100), ("pane", 150), ("pane", 200), ("pane", 250), ("idle", 295)]))
check("4 an item with an idle line as its newest is not told of even when its pane lines are old enough…", tick(now0) == [] and sent == [])
check("4 …and the idle hand-over finds it (it is that pass's case)", [g for g, _r in HI.due_all(NR.load_all(None), now0, server._silence_env().is_front)] == ["a1"])
wipe(); put(1, act=370, log=seed([("pane", 50), ("pane", 100), ("idle", 150), ("pane", 200), ("pane", 250), ("pane", 300)]))
check("4 an idle line in the middle of the lines moves the start to it: 250 minutes after it is not yet 4 h, so nobody is told", tick(now0) == [] and sent == [])
wipe(); put(1, act=450, log=seed([("pane", 50), ("pane", 100), ("idle", 150), ("pane", 200), ("pane", 250), ("pane", 300), ("pane", 350), ("pane", 400)]))
check("4 …and past 4 h after it the pane-only lines since tell -main", tick(now0) == ["a1"] and mt(1).get("busy_tell", {}).get("since") == now0 - 450 * MIN + 150 * MIN and len(to_main()) == 1, (mt(1).get("busy_tell"), sent))

# ================================================================ 5. a front agent's item
wipe(); put(1, mover="beta-main", act=0); pane_busy("beta-main")
told = run(10, 230)
check("5 a front agent's item: nobody is told before 4 h", told == [] and sent == [] and lines(1) and all(l["kind"] == "audit" for l in lines(1)), (told, lines(1)))
told = run(240, 360)
check("5 at 4 h the front agent ITSELF is told, once (beta-main holds it; -main of the project, home-main, is not), never the owner", told == ["a1"] and len(sent) == 1 and S0()[1] == U["beta-main"] and to_main() == [] and owner_free(), (told, sent))
m = S0()[2]
check("5 its message is for the holder: the front mark on line 1, no write but the hourly lines for about 4 hours, write a line or say what blocks it, no reply owed", m.startswith(server._FOR_OWNER + "\n[stackshot] ") and "no write on it but the hourly audit lines" in m and "about 4 hours" in m and "No reply is owed" in m and S0()[3] == "stall", m)
check("5 the History line names the front agent and the record says kind front", len(history(1)) == 1 and "beta-main was told" in history(1)[0] and mt(1).get("busy_tell", {}).get("kind") == "front" and mt(1).get("busy_tell", {}).get("to") == "beta-main", (history(1), mt(1).get("busy_tell")))
wipe(); put(1, mover="beta-main", act=0); panes["beta-main"] = "idle"
told = run(10, 250)
check("5 a front agent's item with idle lines (its pane is not in a turn) is told too: only hourly lines for 4 h, whatever they said", told == ["a1"] and S0()[1] == U["beta-main"] and len(sent) == 1 and all(l["kind"] == "audit_idle" for l in lines(1)), (told, sent))
wipe(); put(1, mover="beta-main", act=0); pane_busy("beta-main")
run(10, 120); activity_at(1, at(120)); told = run(130, 350)
check("5 real activity on a front agent's item resets it (nobody is told 4 h after the first activity, the tell comes 4 h after the second)", told == [] and sent == [], (told, sent_at))
told = run(360, 370)
check("5 …", told == ["a1"] and first_told() == 360 and S0()[1] == U["beta-main"], (told, first_told()))
wipe(); put(1, mover="beta-main", act=0, project="projects/beta"); pane_busy("beta-main")
told = run(10, 250)
check("5 a front agent that is its own project's -main agent is told itself, in the front wording", told == ["a1"] and len(sent) == 1 and S0()[1] == U["beta-main"] and "no write on it but the hourly audit lines" in S0()[2], (told, sent))

wipe(); put(1, mover="beta-main", act=400, log=[])
check("5 a front agent's item with no audit line since its last activity is not told of (nothing says it was watched)", tick(now0) == [] and sent == [])
wipe(); put(1, mover="beta-main", act=400, log=SEVEN)
check("5 …and with its lines it is (the same item, the front agent itself)", tick(now0) == ["a1"] and S0()[1] == U["beta-main"] and len(sent) == 1)

# ================================================================ 6. -main
wipe(); put(1, act=400, log=SEVEN)
real_main = server._main_agent; server._main_agent = lambda p: ""
try:
    with _Err() as err: got = tick(now0)
    check("6 a project with no -main agent is a log line, tells nobody and never raises", got == [] and sent == [] and "no -main agent to tell" in err.text and "busy_tell" not in mt(1) and history(1) == [], (got, err.text))
    with _Err() as err2: tick(now0 + 10 * MIN)
    check("6 …the line is logged once an hour per item, not at every tick", err2.text == "", err2.text)
finally: server._main_agent = real_main
check("6 …and when a -main agent appears the item is told of then, while its newest line is still fresh (nothing was marked)", tick(now0 + 12 * MIN) == ["a1"] and len(to_main()) == 1)
wipe(); put(1, act=400, log=SEVEN)
server._main_agent = lambda p: "Oliver"
try: got = tick(now0)
finally: server._main_agent = real_main
check("6 a -main agent that is the owner is no one to tell", got == [] and sent == [], (got, sent))
wipe(); put(1, mover="team-back", act=400, log=SEVEN)
server._main_agent = lambda p: "team-back"
try: got = tick(now0)
finally: server._main_agent = real_main
check("6 a mover that is itself the project's -main agent is told in the front wording, once", got == ["a1"] and len(sent) == 1 and S0()[1] == U["team-back"] and "no write on it but the hourly audit lines" in S0()[2], (got, sent))
wipe(); put(1, mover="team-back", act=400, log=SEVEN); put(2, mover="team-aux", act=400, log=SEVEN); put(3, mover="team-aux", act=0, log=[])
got = tick(now0)
check("6 several items for one -main agent are one message, one line each, naming both ids", got == ["a1", "a2"] and len(sent) == 1 and S0()[0] == "a1,a2" and S0()[2].count("\n- ") == 2 and S0()[1] == U["home-main"], (got, sent))

# ================================================================ 7. once
wipe(); put(1, act=0); pane_busy("team-back"); run(10, 245)
check("7 told once, the record on the item itself (its own metadata key, apart from hand_idle and balance)", len(sent) == 1 and set(mt(1).get("busy_tell", {})) == {"at", "to", "kind", "since"} and "hand_idle" not in mt(1) and "balance" not in mt(1))
import importlib
importlib.reload(BT); server._BALANCE_LOGGED.clear()
told = run(250, 400)
check("7 a restart (the module reloaded, nothing held in memory) does not tell again: the record is in the store", told == [] and len(sent) == 1, (told, len(sent)))
d = rd(1); d["metadata"]["busy_tell"] = {"at": "yesterday", "to": 1}; wr(1, d)
check("7 a torn record is no record: the stretch is told of again, and the new record is whole", tick(at(410)) == ["a1"] and len(sent) == 2 and isinstance(mt(1).get("busy_tell", {}).get("at"), float))
d = rd(1); d["metadata"]["busy_tell"] = {"at": float("nan")}; wr(1, d)
check("7 …a nan time is none either", tick(at(420)) == ["a1"])
activity_at(1, at(430)); d = rd(1); d["metadata"]["busy_tell"] = {"at": at(420), "to": "home-main", "kind": "main", "since": now0}; wr(1, d)
for m in range(440, 700, 10): hourly(at(m))
n0 = len(sent); tick(at(430 + 239)); n1 = len(sent); tick(at(430 + 240))
check("7 a new stretch (activity after the record) is told again 4 h after it, not before", n1 == n0 and len(sent) == n0 + 1 and mt(1).get("busy_tell", {}).get("since") == at(430), (n0, n1, len(sent)))

wipe(); put(1, act=400, log=SEVEN); snap = NR.load_all(None); activity_at(1, now0 - 5 * MIN)
check("7 the item is read again under the lock: a write that came after the pass read it ends the tell", tick(now0, items=snap) == [] and sent == [] and "busy_tell" not in mt(1), (sent, mt(1).get("busy_tell")))
wipe(); put(1, act=400, log=SEVEN); snap = NR.load_all(None); d = rd(1); d["metadata"]["busy_tell"] = {"at": now0 - MIN, "to": "home-main", "kind": "main", "since": now0 - 400 * MIN}; wr(1, d)
check("7 …and so does a tell that came after it (told once, though the pass's own read had no record)", tick(now0, items=snap) == [] and sent == [])

# ================================================================ 8. what is read
wipe(); put(1, act=400, log=[(50, "pane"), (100, "pane"), (150, "pane"), (200, "pane"), (250, "pane"), (300, "pane"), (350, "pane"), (700, "idle")])
check("8 a line dated ahead of now is not read (an idle line in the future would end the stretch)", tick(now0) == ["a1"] and mt(1).get("busy_tell", {}).get("since") == now0 - 400 * MIN)
wipe(); put(1, act=700, log=[(50, "pane"), (100, "pane"), (150, "pane")])
check("8 a stretch whose newest line is old (the hourly pass is off, or the item left the agent since) is no news", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, log=[])
check("8 an item with no audit line at all is not told of (nothing says it was watched)", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, hourly_audit={"log": [{"at": "bad", "text": "x", "kind": "audit", "pane_only": True}, {"at": float("inf"), "text": "x", "kind": "audit", "pane_only": True}, "not a dict", {"at": now0 - 100 * MIN, "kind": "audit", "pane_only": True},
                                              {"at": now0 - 10 * MIN, "text": "Audit 10:00: verified the mover's pane is in a turn", "kind": "audit", "pane_only": True}, {"at": now0 - 20 * MIN, "text": "Audit 10:00: verified x", "kind": "audit", "pane_only": "yes"}]})
with _Err() as err3: got = tick(now0)
check("8 torn log entries are left out and never raise (a pane_only that is not a true is no mark, and it ends the stretch)", err3.text == "" and got == [] and sent == [], (got, err3.text))
wipe(); put(1, act=400, log=SEVEN, hold=True)
check("8 an item on hold is left alone", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, log=SEVEN, wait_kind="relay")
check("8 an item the board shows waiting is left alone", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, status="completed", log=SEVEN, outcome="done")
check("8 a closed item is left alone", tick(now0) == [] and sent == [])
wipe(); put(1, mover="Oliver", act=400, log=SEVEN, needs=["decision"], ask="pick one", state="your-call", next="Oliver: pick")
check("8 the owner's item is left alone and the owner is never told", tick(now0) == [] and sent == [])
wipe(); put(1, act=400, log=SEVEN); d = rd(1); d["metadata"]["next"] = 7; d["metadata"]["needs"] = {"x": 1}; wr(1, d); put(2, act=400, log=SEVEN); wr(3, {"status": "open", "metadata": "torn"})
with _Err() as err4: got = tick(now0)
check("8 an item that cannot be read is left out and stops no other", "a2" in got and len(to_main()) == 1, (got, err4.text))
wipe(); put(1, act=400, log=SEVEN)
fr = telling.front_keeper; telling.front_keeper = lambda w, p, strict=False, unread_front=False: (_ for _ in ()).throw(OSError("roles unreadable"))
try: got = tick(now0)
finally: telling.front_keeper = fr
check("8 a front test that cannot answer reads as front: the holder is told, never a guess at -main", got == ["a1"] and S0()[1] == U["team-back"] and "no write on it but the hourly audit lines" in S0()[2], (got, sent))

# ================================================================ 9. the threshold in the config, never the owner, the tick
for hrs, expect in ((2, 120), (6, 360)):
    wipe(); put(1, act=0); pane_busy("team-back"); server._cfg.CFG["audit"]["busy_tell_hours"] = hrs
    told = run(10, expect - 10); before = list(sent); told += run(expect, expect + 10)
    check(f"9 busy_tell_hours = {hrs}: nobody told before {hrs} h, the -main agent told at {hrs} h, the message says about {hrs} hours", before == [] and told == ["a1"] and first_told() == expect and f"about {hrs} hours" in S0()[2], (before, told, first_told()))
wipe(); put(1, act=0); pane_busy("team-back"); server._cfg.CFG["audit"]["busy_tell"] = False
check("9 the switch off: nothing is told and nothing written over 6 h", run(10, 360) == [] and sent == [] and "busy_tell" not in mt(1))
server._cfg.CFG["audit"]["busy_tell"] = True
check("9 …and switched on again, the stretch that ran meanwhile is told of at the next tick", tick(at(370)) == ["a1"] and len(sent) == 1)
order = []
real = (server._hourly_tick, server._hand_idle_tick, server._busy_tell_tick)
server._hourly_tick = lambda *a, **k: order.append("hourly"); server._hand_idle_tick = lambda *a, **k: order.append("hand"); server._busy_tell_tick = lambda *a, **k: order.append("busy")
try: server._silence_tick()
finally: server._hourly_tick, server._hand_idle_tick, server._busy_tell_tick = real
check("9 `_silence_tick` runs the busy tell last, after the hourly line and the idle hand-over", order == ["hourly", "hand", "busy"], order)
def boom(*a, **k): raise OSError("store gone")
order.clear()
server._hourly_tick = lambda *a, **k: order.append("hourly"); server._hand_idle_tick = lambda *a, **k: order.append("hand"); server._busy_tell_tick = boom
try:
    with _Err() as err5: server._silence_tick()
finally: server._hourly_tick, server._hand_idle_tick, server._busy_tell_tick = real
check("9 a failure in the busy tell is a stderr line and stops nothing (the lines before it have run)", order == ["hourly", "hand"] and "long busy stretches not told: OSError" in err5.text, (order, err5.text))
order.clear()
server._hourly_tick = boom; server._hand_idle_tick = lambda *a, **k: order.append("hand"); server._busy_tell_tick = lambda *a, **k: order.append("busy")
try:
    with _Err(): server._silence_tick()
finally: server._hourly_tick, server._hand_idle_tick, server._busy_tell_tick = real
check("9 …and a failure in the hourly line stops neither of the others", order == ["hand", "busy"], order)
check("9 the hourly log marks a pane-only line and no other (an idle, a subagent and a recorded-event line carry no mark)",
      HR.pane_only({"kind": "audit", "verified": [HR.PANE], "recorded": []}) and not HR.pane_only({"kind": "audit", "verified": [HR.PANE, "a subagent is running on it"], "recorded": []})
      and not HR.pane_only({"kind": "audit", "verified": [HR.PANE, "CI failed on PR 5"], "recorded": ["CI failed on PR 5"]}) and not HR.pane_only({"kind": "audit_idle", "verified": [], "recorded": []})
      and not HR.pane_only({"kind": "audit_unknown", "verified": [], "recorded": []}) and not HR.pane_only(None) and not HR.pane_only({"kind": "audit", "verified": ["a subagent is running on it"], "recorded": []}))
m9 = {}; HL.note(m9, 5.0, "a", "audit", pane_only=True); HL.note(m9, 6.0, "b", "audit"); HL.note(m9, 7.0, "c", "audit_idle")
check("9 the entry carries pane_only only when it is true, and a later note keeps the earlier marks", HL.log_of(m9)[0].get("pane_only") is True and "pane_only" not in HL.log_of(m9)[1] and "pane_only" not in HL.log_of(m9)[2])

# ================================================================ 10. a recorded commit, how long it says, a future record, and the lines no other check pinned
def commit_event(m):
    if m == 140:
        d = rd(1); d["metadata"]["last_activity"] = {"at": at(138), "kind": "commit", "what": "commit on PR 5"}; wr(1, d)      # a new head commit on the tied pull request: recorded, and it moves no clock
wipe(); put(1, act=0); pane_busy("team-back")
told = run(10, 400, each=commit_event)
other = [l for l in lines(1) if not l.get("pane_only")]
check("10 a recorded commit with a busy pane verifies the line besides the pane (the line names both), so it carries no pane_only mark", len(other) == 1 and other[0]["kind"] == "audit" and "commit on PR 5" in other[0]["text"] and "pane is in a turn" in other[0]["text"], other)
check("10 …and it ends the stretch like a CI result does: nobody is told at 4 h after the first activity, the tell comes 4 h after that line", told == ["a1"] and first_told() > 240 and sent_at[0] >= other[-1]["at"] + 4 * H - 1, (told, first_told(), [(l["at"] - now0) / 60 for l in other]))
item_c = {"metadata": {"last_activity": {"at": now0 - 600, "kind": "commit", "what": "commit on PR 5"}}}
vc, rc = HR.verified(item_c, item_c["metadata"], "team-back", now0, lambda who: "busy", None, None, None)
check("10 hourly.verified: a commit newer than an hour verifies (recorded) and makes the line no pane-only one; one older than an hour verifies nothing", rc == ["commit on PR 5"] and not HR.pane_only({"kind": "audit", "verified": vc, "recorded": rc})
      and HR.verified({"metadata": {"last_activity": {"at": now0 - 2 * H, "kind": "commit", "what": "commit on PR 5"}}}, {"last_activity": {"at": now0 - 2 * H, "kind": "commit", "what": "commit on PR 5"}}, "team-back", now0, lambda who: "idle", None, None, None) == ([], []), (vc, rc))

# the length it says is the real one (whole hours, never under the threshold)
wipe(); put(1, mover="beta-main", act=3000, log=[(2900, "pane")])      # beta-main is a front agent of projects/alpha (it is the keeper of projects/beta, which is the own-main case: a background mover under the two-line rule)
check("10 a front agent's item quiet for 50 hours is told so (about 50 hours), in the message and the History line, not as the threshold's 4", tick(now0) == ["a1"] and "about 50 hours" in S0()[2] and "about 4 hours" not in S0()[2] and "about 50 hours" in history(1)[0] and "about 4 hours" not in history(1)[0], (sent, history(1)))
wipe(); put(1, act=400, log=SEVEN)
check("10 a background mover's stretch that is 6 h 40 min old when first seen says about 6 hours (the real time in whole hours, rounded down)", tick(now0) == ["a1"] and "about 6 hours" in S0()[2] and "about 6 hours" in history(1)[0], (sent, history(1)))
wipe(); put(1, act=0); pane_busy("team-back"); run(10, 235); told = run(240, 250)
check("10 …and a stretch told on the tick it turns 4 h still says about 4 hours", told == ["a1"] and "about 4 hours" in S0()[2] and "about 4 hours" in history(1)[0], (sent, history(1)))
wipe(); put(1, act=70, log=[(50, "pane"), (60, "pane")]); server._cfg.CFG["audit"]["busy_tell_hours"] = 1
check("10 a one-hour threshold reads `about 1 hour`, never `1 hours`", tick(now0) == ["a1"] and "about 1 hour (" in S0()[2] and "1 hours" not in S0()[2] and "about 1 hour:" in history(1)[0], (sent, history(1)))
wipe(); put(1, act=0); pane_busy("team-back"); server._cfg.CFG["audit"]["busy_tell_hours"] = 2.5; run(10, 140)
check("10 a threshold of 2.5 hours keeps its own wording when the stretch is just that long (never below it: 2 h 30 min is not `2 hours`)", tick(at(150)) == ["a1"] and "about 2.5 hours" in S0()[2], sent)
check("10 BT.span: the real hours rounded down, never under the threshold", BT.span(0.0, 4 * H, 4) == "4 hours" and BT.span(0.0, 4 * H + 60, 4) == "4 hours" and BT.span(0.0, 50.3 * H, 4) == "50 hours" and BT.span(0.0, 3 * H, 4) == "4 hours"
      and BT.span(0.0, 3.2 * H, 2.5) == "3 hours" and BT.span(0.0, 2.6 * H, 2.5) == "2.5 hours" and BT.span(0.0, 2.5 * H, 2.5) == "2.5 hours" and BT.span(0.0, 6.9 * H, 4) == "6 hours" and BT.span(0.0, H, 1) == "1 hour", [BT.span(0.0, x * H, 4) for x in (4, 50.3, 3)])

# a record dated in the future is no record
wipe(); put(1, act=400, log=SEVEN); d = rd(1); d["metadata"]["busy_tell"] = {"at": now0 + 3 * H, "to": "home-main", "kind": "main", "since": now0 - 400 * MIN}; wr(1, d)
check("10 a told-record dated 3 hours ahead of now is no record: the stretch is told, and the new record is dated now", tick(now0) == ["a1"] and len(to_main()) == 1 and mt(1)["busy_tell"]["at"] == now0, (sent, mt(1).get("busy_tell")))
wipe(); put(1, act=400, log=SEVEN); d = rd(1); d["metadata"]["busy_tell"] = {"at": now0 + 30 * MIN, "to": "home-main", "kind": "main", "since": now0 - 400 * MIN}; wr(1, d)
check("10 …a record dated half an hour ahead (a clock skew inside the audit's hour) still counts: told once, not again", tick(now0) == [] and sent == [], sent)
check("10 BT.told_since: a record at or after the start counts, one before it, a torn one and one more than an hour ahead do not",
      BT.told_since({"busy_tell": {"at": 100.0}}, 100.0, 200.0) and not BT.told_since({"busy_tell": {"at": 99.0}}, 100.0, 200.0) and not BT.told_since({"busy_tell": {"at": "x"}}, 100.0, 200.0)
      and BT.told_since({"busy_tell": {"at": 200.0 + H}}, 100.0, 200.0) and not BT.told_since({"busy_tell": {"at": 201.0 + H}}, 100.0, 200.0) and not BT.told_since(None, 100.0, 200.0))

# lines older than the item's last activity make nothing due
wipe(); put(1, act=100, log=[(-250, "idle"), (-20, "pane")])
check("10 a background item whose only lines are older than its last activity is not due (an old idle line would otherwise start a stretch 6 h back)", tick(now0) == [] and sent == [], sent)
wipe(); put(1, mover="beta-main", act=250, log=[(-10, "pane")])
check("10 a front agent's item whose only line is older than its last activity is not told (the lines must come after the activity)", tick(now0) == [] and sent == [], sent)

# the newest line must be a pane-only one, over 4 h old included (the slow cadence reaches it)
for label, lg in (("a line that verified something else", [(50, "pane"), (100, "pane"), (150, "pane"), (200, "other")]), ("an idle line", [(50, "pane"), (100, "pane"), (150, "idle")]),
                  ("an unknown line", [(50, "pane"), (100, "pane"), (200, "unknown")])):
    wipe(); put(1, act=520, log=lg)
    check(f"10 a stretch whose newest line is {label} is not told as busy, though it started over 4 h ago", tick(now0) == [] and sent == [] and "busy_tell" not in mt(1), (sent, lg))

# a line that verified something else, or an idle one, in the middle resets the run
def due_row(i, front_test=None):
    return BT.due(NR.load_all(None), f"a{i}", now0, front_test if front_test is not None else (lambda who, project: False), None, 4.0)
wipe(); put(1, act=450, log=seed([("pane", 50), ("pane", 100), ("idle", 150), ("pane", 200), ("pane", 250), ("pane", 300), ("pane", 350), ("pane", 400)]))
r13 = due_row(1)
check("10 an idle line in the middle resets the run: the lines of the stretch are the five after it", r13 is not None and r13["lines"] == 5 and r13["kind"] == "main" and r13["since"] == now0 - 300 * MIN, r13)
wipe(); put(1, act=450, log=seed([("pane", 50), ("pane", 100), ("other", 150), ("pane", 200), ("pane", 250), ("pane", 300), ("pane", 350), ("pane", 400)]))
r13 = due_row(1)
check("10 a line that verified something else in the middle resets the run too (five lines, counted from it)", r13 is not None and r13["lines"] == 5 and r13["since"] == now0 - 300 * MIN, r13)
wipe(); put(1, act=450, log=seed([("pane", 50), ("pane", 100), ("unknown", 150), ("pane", 200), ("pane", 250), ("pane", 300), ("pane", 350), ("pane", 400)]))
r13 = due_row(1)
check("10 …and an unknown line the same", r13 is not None and r13["lines"] == 5 and r13["since"] == now0 - 300 * MIN, r13)

# a front test that raises reads as front (the holder is told, never a guess at -main)
def front_raises(who, project): raise OSError("roles unreadable")
wipe(); put(1, act=400, log=SEVEN)
r16 = due_row(1, front_raises); r16b = due_row(1)
check("10 BT.due with a front test that raises reads the mover as front (kind front, counted from the last activity); the same item with a front test that says no is a -main case", r16 is not None and r16["kind"] == BT.KIND_FRONT and r16["since"] == now0 - 400 * MIN and r16["mover"] == "team-back"
      and r16b is not None and r16b["kind"] == BT.KIND_MAIN, (r16, r16b))
check("10 BT.due with no front test at all reads none as front", BT.due(NR.load_all(None), "a1", now0, None, None, 4.0)["kind"] == BT.KIND_MAIN)

# the open check: an item that closes between the pass's read and the locked re-read is not told
wipe(); put(1, act=400, log=SEVEN); snap = NR.load_all(None); d = rd(1); d["status"] = "completed"; d["metadata"]["outcome"] = "done"; wr(1, d)
check("10 an item closed after the pass read it is not told (the re-read under the lock sees it closed)", tick(now0, items=snap) == [] and sent == [] and "busy_tell" not in mt(1), (sent, mt(1).get("busy_tell")))
closed = NR.load_all(None)
check("10 BT.due itself refuses a closed item and a missing one (the check is its own, not only due_all's)", BT.due(closed, "a1", now0, lambda w, p: False, None, 4.0) is None and BT.due(closed, "a99", now0, lambda w, p: False, None, 4.0) is None)

# ================================================================ 11. a stretch is only built from lines about an hour apart
def due_rows(**kw): return BT.due(NR.load_all(None), "a1", now0, lambda who, project: False, kw.get("queue"), kw.get("hrs", 4.0))
LIMIT = 65                                                         # minutes: BT.EXTEND_GAP = hourly.HOUR + hourly.SLACK
check("11 BT.EXTEND_GAP is the fast cadence's hour plus the tick's slack, taken from the hourly module's own constants, and a stretch needs two pane-only lines",
      BT.EXTEND_GAP == HR.HOUR + HR.SLACK and BT.EXTEND_GAP == LIMIT * MIN and BT.MIN_LINES == 2, (BT.EXTEND_GAP, BT.MIN_LINES))

# the slow cadence: a CI result a few hours before a line that is pane-only because the hourly check sees events only up to an hour old
wipe(); put(1, act=29 * 60 + 20, log=[(23 * 60 + 20, "pr"), (29 * 60 + 20, "pane")])
check("11 the reviewer's scenario: a line that verified a CI result at 23 h 20, then ONE pane-only line after a 6 h gap (29 h 20): nobody is told, nothing is written", tick(now0) == [] and sent == [] and "busy_tell" not in mt(1) and history(1) == [], (sent, mt(1).get("busy_tell")))
wipe(); put(1, act=29 * 60 + 20, log=[(23 * 60 + 20, "pr"), (29 * 60 + 20 - 6, "pane"), (29 * 60 + 20, "pane")])
check("11 …and two pane-only lines 6 minutes apart after that gap are a stretch of 6 minutes, not 6 hours: nobody is told", tick(now0) == [] and sent == [], (sent, mt(1).get("busy_tell")))
wipe(); put(1, act=0); pane_busy("team-back")
def slow_ci(m):
    if m == 22 * 60 + 50: d = rd(1); d["metadata"]["last_activity"] = {"at": at(m), "kind": "ci_result", "what": "CI failed on PR 5"}; wr(1, d)
    if m == 27 * 60: d = rd(1); d["metadata"]["last_activity"] = {"at": at(m), "kind": "ci_result", "what": "CI passed on PR 5"}; wr(1, d)
told = run(10, 31 * 60, each=slow_ci)
lg = [(l["at"] - now0) / MIN for l in lines(1)]
check("11 the whole timeline through the real hourly and busy ticks (a CI result at 22 h 50 and another at 27 h): the line after 24 h of silence comes about 6 h after the one before it, and the mover is told ONCE, at 4 h, never again at the slow cadence",
      told == ["a1"] and len(sent) == 1 and first_told() == 240 and any(l - p > 300 for p, l in zip(lg, lg[1:])) and lg[-1] > 24 * 60 and len(to_main()) == 1, (told, first_told(), lg[-8:]))

# the fast zone: the same item is told 4 hours after the line that ended the earlier stretch
wipe(); put(1, act=400, log=[(50, "pr")] + [(m, "pane") for m in range(100, 401, 50)])
r = due_rows()
check("11 the same item in the fast zone (lines 50 minutes apart) is told once it has been 4 h since the line that verified the CI result", r is not None and r["kind"] == "main" and r["since"] == at(50 - 400) and r["lines"] == 7 and tick(now0) == ["a1"] and len(to_main()) == 1, r)

# a gap: restarts the stretch at the line after it, unless it is no longer than the limit
def gap_log(gap, before=((50, 'pane'), (100, 'pane'), (150, 'pane'))):
    lg = list(before); t = lg[-1][0] + gap; lg += [(t, "pane"), (t + 50, "pane"), (t + 100, "pane"), (t + 150, "pane")]
    return lg, t + 150
for gap, label, told_ in ((LIMIT, "exactly the limit (65 minutes: the hour plus the tick's slack)", True), (61, "61 minutes (a skipped tick)", True), (LIMIT + 1, "66 minutes", False)):
    lg, newest = gap_log(gap); wipe(); put(1, act=newest + 5, log=lg)
    r = due_rows()
    check(f"11 a gap of {label} inside a stretch {'does not restart it: told, the stretch counts from the last activity' if told_ else 'restarts it at the line after the gap: 3 h 50 min of lines since, nobody told'}",
          (r is not None and r["since"] == now0 - (newest + 5) * MIN and r["lines"] == 7) if told_ else (r is None and tick(now0) == [] and sent == []), (gap, r, newest))
lg, newest = gap_log(LIMIT + 1); wipe(); put(1, act=newest + 5, log=lg)
check("11 …and the restart is counted from that line: at a two-hour threshold the stretch (2 h 35 min since the line after the gap) is told, from that line", (lambda r: r is not None and r["since"] == now0 - (newest + 5) * MIN + (150 + LIMIT + 1) * MIN and r["lines"] == 4)(BT.due(NR.load_all(None), "a1", now0, lambda w, p: False, None, 2.0)))
wipe(); put(1, act=500, log=[(400, "pane"), (450, "pane")])
check("11 the first line after the last real activity is held to the same limit: one 400 minutes after it starts the stretch at its own time (100 min of stretch, not told), the next line extends it", due_rows() is None and tick(now0) == [] and sent == [], sent)
wipe(); put(1, act=170, log=[(100, "pane"), (150, "pane")])
r = due_rows(hrs=1.0)
check("11 a line after a long gap counts as the first line of the new stretch (the restart line and one more are two: told at a one-hour threshold, 2 lines)", r is not None and r["lines"] == 2 and r["since"] == now0 - 70 * MIN, r)

# two pane-only lines at least
wipe(); put(1, act=300, log=[(60, "pane")])
check("11 ONE pane-only line is not a stretch of 4 hours: 5 h after the last activity with a single line (an hour after it) nobody is told", due_rows() is None and tick(now0) == [] and sent == [], sent)
wipe(); put(1, act=300, log=[(50, "pane"), (100, "pane"), (150, "pane"), (200, "pane"), (250, "pane"), (295, "pane")])
check("11 …and a run of them is (the same 5 h, a line every 50 minutes, the newest 5 minutes ago)", (lambda r: r is not None and r["lines"] == 6 and r["since"] == now0 - 300 * MIN)(due_rows()) and tick(now0) == ["a1"], sent)
wipe(); put(1, act=125, log=[(60, "pane")])
check("11 …and at the shortest threshold (one hour) a single line that is itself fresh is still not a stretch (2 h of quiet, one pane-only line 65 minutes old: MIN_LINES holds)", due_rows(hrs=1.0) is None and BT.due(NR.load_all(None), "a1", now0, lambda w, p: False, None, 1.0) is None, sent)
wipe(); put(1, act=125, log=[(60, "pane"), (100, "pane")])
check("11 …and two lines at that threshold are", (lambda r: r is not None and r["lines"] == 2)(due_rows(hrs=1.0)))
wipe(); put(1, mover="beta-main", act=300, log=[(60, "pane")])
check("11 the front agent's rule is unchanged: one line since its last activity, and 5 h of quiet, tell that front agent itself", tick(now0) == ["a1"] and S0()[1] == U["beta-main"] and "no write on it but the hourly audit lines" in S0()[2] and "pull request" not in S0()[2], sent)
for who, proj in (("team-back", "projects/alpha"), ("beta-main", "projects/alpha")):
    pass
r_bt = BT.stretch_start({"hourly_audit": {"log": [{"at": 100.0, "text": "x", "kind": "audit", "pane_only": True}, {"at": 100.0 + LIMIT * MIN, "text": "x", "kind": "audit", "pane_only": True}]}}, 0.0, 10 ** 6)
r_bt2 = BT.stretch_start({"hourly_audit": {"log": [{"at": 100.0, "text": "x", "kind": "audit", "pane_only": True}, {"at": 100.0 + LIMIT * MIN + 1, "text": "x", "kind": "audit", "pane_only": True}]}}, 0.0, 10 ** 6)
check("11 BT.stretch_start: two lines exactly the limit apart are one stretch from the activity; one second more and the stretch restarts at the second line, with one line, so there is none", r_bt == (0.0, 2) and r_bt2 is None, (r_bt, r_bt2))

# the History line of both wordings, the freshness margin, one unreadable item among others, a queued item
wipe(); put(1, act=400, log=SEVEN); tick(now0)
check("11 the History line of a background mover's item, word for word", history(1) == ["team-back's item has had only a busy pane for its hourly audit lines for about 6 hours: home-main was told"], history(1))
check("11 …and the message to -main, word for word up to the shared tail", S0()[2].split("\n")[2] == "[stackshot] [home] item 1 \"[home] item 1\" (projects/alpha): team-back has looked busy for about 6 hours (every audit line since said only that its pane is in a turn) with no step change, pull request event or other sign of progress on this item. Please look at what it is doing."
      or "has looked busy for about 6 hours (every audit line since said only that its pane is in a turn) with no step change, pull request event or other sign of progress on this item. Please look at what it is doing." in S0()[2], S0()[2])
wipe(); put(1, mover="beta-main", act=400, log=SEVEN); tick(now0)
check("11 the History line of a front agent's item, word for word", history(1) == ["beta-main's item has had no write but the hourly audit lines for about 6 hours: beta-main was told"], history(1))
check("11 …and its message says no write but the hourly audit lines, and asks for a line or what blocks it, and claims no pull request event", "no write on it but the hourly audit lines for about 6 hours. If you are at work on it, write a line on it; if you are not, say what blocks it or hand it on." in S0()[2] and "pull request" not in S0()[2], S0()[2])

FRESH_MIN = 375                                                    # FRESH = the slow cadence's 6 h plus 15 minutes: a FRONT agent's margin
check("11 BT.FRESH is the slow cadence's 6 h plus a quarter of an hour, and a background mover's margin is the stretch's own gap (BT.EXTEND_GAP, 65 minutes)", BT.FRESH == HR.SLOW_EVERY + 900.0 and BT.FRESH == FRESH_MIN * MIN and BT.EXTEND_GAP == LIMIT * MIN, (BT.FRESH, BT.EXTEND_GAP))
for ago, told_, label in ((LIMIT, True, "65 minutes old (exactly the gap that joins two lines) still counts as a fresh line"), (LIMIT + 1, False, "66 minutes old is no news"), (FRESH_MIN, False, "6 h 15 min old (the old margin) is no news")):
    wipe(); put(1, act=350 + ago, log=[(50 * k, "pane") for k in range(1, 8)])
    check(f"11 the freshness margin of a background mover's item: a stretch of 4 h and more whose newest line is {label}: {'told' if told_ else 'nobody told, nothing written'}",
          (tick(now0) == ["a1"] and len(to_main()) == 1) if told_ else (tick(now0) == [] and sent == [] and "busy_tell" not in mt(1) and BT.due(NR.load_all(None), "a1", now0, lambda w, p: False, None, 4.0) is None), (ago, sent))
wipe(); put(1, mover="beta-main", act=110 + FRESH_MIN + 15, log=[(60, "pane"), (110, "pane")])
check("11 the front agent's item keeps the wide margin (6 h 30 min since its newest line: nobody told)", tick(now0) == [] and sent == [])
wipe(); put(1, mover="beta-main", act=110 + FRESH_MIN, log=[(60, "pane"), (110, "pane")])
check("11 …and 6 h 15 min is fresh for it", tick(now0) == ["a1"])
wipe(); put(1, mover="beta-main", act=110 + FRESH_MIN, log=[(60, "pane"), (110, "pane")]); put(2, act=110 + FRESH_MIN, log=[(60, "pane"), (110, "pane")])
check("11 …the same 6 h 15 min old lines of a background mover are not told, the front agent's are", tick(now0) == ["a1"] and S0()[1] == U["beta-main"] and "busy_tell" not in mt(2), sent)

class _BadQueue(dict):
    def get(self, k, d=None):
        if k == "a2": raise RuntimeError("torn queue entry")
        return dict.get(self, k, d)
wipe(); put(1, act=400, log=SEVEN); put(2, act=400, log=SEVEN); put(3, mover="team-aux", act=400, log=SEVEN)
rows = BT.due_all(NR.load_all(None), now0, lambda w, p: False, _BadQueue({"a9": "a8"}), 4.0)
check("11 BT.due_all: an item whose reading raises is left out and the others are still returned, in id order", [g for g, _r in rows] == ["a1", "a3"], rows)

server._cfg.CFG.setdefault("model", {})["queued_behind"] = True
try:
    wipe(); put(1, act=400, log=SEVEN); put(2, act=400, log=SEVEN, last_activity={"at": now0 - 10 * MIN, "kind": "audit", "what": "audit verified the mover's pane is in a turn"})      # a2 is the item in hand (activity within the hour: an audit stamp, which holds no tell back), a1 waits behind it
    qm = SL.queued(NR.load_all(None), now0, server._silence_env())
    told_ = tick(now0)
    check("11 a queued item is not told: of two items of one mover, the one the board queues behind the item in hand is left out, and the item in hand is told", qm == {"a1": "a2"} and told_ == ["a2"] and len(to_main()) == 1 and "busy_tell" not in mt(1) and "busy_tell" in mt(2), (qm, told_, sent))
finally: server._cfg.CFG["model"].pop("queued_behind", None)
wipe(); put(1, act=400, log=SEVEN)
check("11 BT.due: an item the queue shows behind another is not due (the queue passed in is read)", BT.due(NR.load_all(None), "a1", now0, lambda w, p: False, {"a1": "a2"}, 4.0) is None and BT.due(NR.load_all(None), "a1", now0, lambda w, p: False, {"a2": "a1"}, 4.0) is not None)

# the log keeps eight lines: once it has rolled past the activity, the gap between the activity and the oldest line left says nothing (or a told stretch would read as a new one every time the window moves on)
wipe(); put(1, act=350, log=[(200 + 20 * k, "pane") for k in range(7)])
check("11 a log that holds every line since the activity (seven of eight kept) and whose first line comes 200 minutes after it: that line starts the stretch (140 minutes of stretch, nobody told)", due_rows() is None and tick(now0) == [] and sent == [], sent)
wipe(); put(1, act=350, log=[(200 + 20 * k, "pane") for k in range(8)])
r = due_rows()
check("11 …and a full log (eight lines, the oldest 200 minutes after the activity: earlier ones may have rolled off) counts from the activity: told once, as before the window moved", r is not None and r["since"] == now0 - 350 * MIN and r["lines"] == 8, r)

# ================================================================ 12. the follow-up to the third review: a tell on a fresh line, an event no line has seen, a span the lines can show
# L1: a stretch is told only while its newest line is within BT.EXTEND_GAP of now (the tell is built from lines about an hour apart up to the tell itself)
wipe(); put(1, act=400, log=seed([("pane", 50), ("pane", 100), ("pane", 150), ("pane", 200), ("pane", 250), ("pane", 300)]))
check("12 a stretch of 6 h whose lines are an hour apart but whose newest is 100 minutes old (the hourly pass stopped, or the item was off the agent) is not told: nothing is written, nobody is sent anything",
      due_rows() is None and tick(now0) == [] and sent == [] and "busy_tell" not in mt(1) and history(1) == [], (sent, mt(1).get("busy_tell")))
wipe(); put(1, act=400, log=seed([("pane", 50), ("pane", 100), ("pane", 150), ("pane", 200), ("pane", 250), ("pane", 300)]))
check("12 …the same lines are told while the newest is within its 65-minute margin, and not a minute after (100 minutes old now: 35 minutes earlier it was 65)",
      BT.due(NR.load_all(None), "a1", now0 - 35 * MIN, lambda w, p: False, None, 4.0) is not None and BT.due(NR.load_all(None), "a1", now0 - 34 * MIN, lambda w, p: False, None, 4.0) is None)
wipe(); put(1, mover="beta-main", act=400, log=seed([("pane", 50), ("pane", 100), ("pane", 150), ("pane", 200), ("pane", 250), ("pane", 300)]))
check("12 …and the front agent's item with the same lines is told (its rule is unchanged: the wide margin, the last real activity as the start)", tick(now0) == ["a1"] and S0()[1] == U["beta-main"], sent)

# L2: a recorded event after the stretch began that no line has seen holds the tell back
EVENTS = (("ci_result", "CI failed on PR 5"), ("review", "review on PR 5"), ("comment", "comment on #5"), ("commit", "commit on PR 5"), ("pr_merged", "PR 5 merged"), ("update", "a status update"), ("step_done", "a step done"), ("state_change", "state change"))
for kind_, what_ in EVENTS:
    wipe(); put(1, act=400, log=SEVEN, last_activity={"at": now0 - 10 * MIN, "kind": kind_, "what": what_})
    check(f"12 a recorded {kind_} event 10 minutes ago (after the stretch began, after the newest line) holds the tell back: nobody is told, nothing is written", due_rows() is None and tick(now0) == [] and sent == [] and "busy_tell" not in mt(1) and history(1) == [], (kind_, sent))
wipe(); put(1, act=400, log=SEVEN, last_activity={"at": now0 - 10 * MIN, "kind": "audit", "what": "audit verified the mover's pane is in a turn"})
check("12 …an audit's own stamp (every pane-only line stamps one) is no event: told", tick(now0) == ["a1"] and len(to_main()) == 1, sent)
wipe(); put(1, act=400, log=SEVEN, last_activity={"at": now0 - 400 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"})
check("12 …an event at the very start of the stretch (the last real activity) is not after it: told", tick(now0) == ["a1"], sent)
wipe(); put(1, act=400, log=SEVEN, last_activity={"at": now0 - 400 * MIN + 1, "kind": "ci_result", "what": "CI failed on PR 5"})
check("12 …one second after the start is after it: not told", tick(now0) == [] and sent == [], sent)
for label, rec_ in (("a record dated more than an hour ahead (no record)", {"at": now0 + 2 * H, "kind": "ci_result", "what": "CI failed on PR 5"}), ("a torn record (a time that is text)", {"at": "soon", "kind": "ci_result", "what": "CI failed on PR 5"}),
                    ("a kind nobody knows", {"at": now0 - 10 * MIN, "kind": "nothing", "what": "x"})):
    wipe(); put(1, act=400, log=SEVEN, last_activity=rec_)
    check(f"12 …{label} holds nothing back: told", tick(now0) == ["a1"], (label, sent))
wipe(); put(1, mover="beta-main", act=400, log=SEVEN, last_activity={"at": now0 - 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"})
check("12 …and the front agent's item is told whatever the event (its message claims no pull request event, only that nothing was written)", tick(now0) == ["a1"] and "pull request" not in S0()[2], sent)
wipe(); put(1, act=0); pane_busy("team-back")
def ev_before_tell(m):
    if m == 230: d = rd(1); d["metadata"]["last_activity"] = {"at": at(m), "kind": "ci_result", "what": "CI failed on PR 5"}; wr(1, d)      # between the line at 200 and the tell that was due at 240
told = run(10, 480, each=ev_before_tell)
check("12 the timeline: a CI result at 3 h 50 min, after the line at 3 h 20 min and before the tell that was due at 4 h, holds it back; the next line (4 h 10 min) verifies the event and ends the stretch, nobody is told in the next 4 hours", told == [] and sent == [] and any(not l.get("pane_only") for l in lines(1)), (told, [(l["at"] - now0) / 60 for l in lines(1)]))
told = run(490, 500)
check("12 …and the stretch that starts at that line is told 4 h later, once", told == ["a1"] and len(sent) == 1 and (first_told() or 0) >= 250 + 240 and mt(1).get("busy_tell", {}).get("since") == at(250), (told, first_told(), mt(1).get("busy_tell")))

# L3: a log that has rolled past the activity: the length told is the one the lines show
wipe(); put(1, act=2000, log=[(1600 + 50 * k, "pane") for k in range(8)])
r = due_rows()
check("12 a log that has rolled past the activity (eight lines, the oldest 6 h 40 min old, the activity 33 h back): the stretch still counts from the activity for the once, but its length is the one the lines show", r is not None and r["since"] == now0 - 2000 * MIN and r["shown"] == now0 - 400 * MIN and r["lines"] == 8, r)
tick(now0)
check("12 …the message and the History line say about 6 hours, never about 33", S0()[0] == "a1" and "about 6 hours" in S0()[2] and "33 hours" not in S0()[2] and history(1) == ["team-back's item has had only a busy pane for its hourly audit lines for about 6 hours: home-main was told"]
      and mt(1).get("busy_tell", {}).get("since") == now0 - 2000 * MIN, (S0()[2], history(1), mt(1).get("busy_tell")))
check("12 …and it is told once: the window moving on reads no new stretch", tick(now0 + 5 * MIN) == [] and len(sent) == 1)
wipe(); put(1, act=400, log=SEVEN)
r = due_rows()
check("12 a log that still holds every line since the activity: what the lines show is the stretch itself (shown is since)", r is not None and r["shown"] == r["since"] == now0 - 400 * MIN, r)
wipe(); put(1, act=900, log=[(500, "idle")] + [(550 + 50 * k, "pane") for k in range(7)])
r = due_rows()
check("12 a rolled log whose stretch was restarted by a line that verified something else: it counts from that line, which is itself shown", r is not None and r["since"] == r["shown"] == now0 - 900 * MIN + 500 * MIN and r["lines"] == 7, r)
wipe(); put(1, mover="beta-main", act=2000, log=[(1600 + 50 * k, "pane") for k in range(8)])
r = BT.due(NR.load_all(None), "a1", now0, lambda w, p: True, None, 4.0)
check("12 a front agent's item keeps counting from its last real activity (its length is the activity's, the lines are not the measure)", r is not None and r["kind"] == "front" and r["shown"] == r["since"] == now0 - 2000 * MIN, r)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
