"""Scenario test for the hourly audit line (audit/hourly.py, server._hourly_tick, called from the ten-minute audit tick, `[audit] hourly_line`, on by default): an item on an agent with no activity for 45 minutes gets ONE
History line saying what the audit verified, or that it is idle. Fixture items in a temporary store, a fake clock (the pass is given its `now`), the pane registry replaced by a dict, no live store, no
network, no model call, no message sent.

  1  due and verified: the mover's pane is busy, a subagent runs (a status line in progress, the mover's own), a tied pull request had a CI result in the last hour (metadata.last_activity), or several of
     them: `Audit hh:mm: verified …` in the instance's zone; the entry of the item's own log, metadata.hourly_audit.log (not the stall ladder's metadata.stall.log), has kind `audit`; a line that rests on a busy pane or a subagent alone says `live state only`; a line that verified something is stamped as the item's last-activity record (section 16), one that verified nothing or rests on a recorded event alone is not; the activity clock, `updated` and the
     writer are as they were; an idle, shell or unreadable pane, another agent's status line, a done or old one, and a pull request event older than an hour verify nothing
  2  due and nothing verified: `Audit hh:mm: idle, nothing verified`, kind `audit_idle`, `hourly.idle_marked`; the last-activity record is untouched
  3  not due: under 45 minutes of silence (a confirm just now moves nothing), a recent write, an item that just left a hold; the quiet-time clock (`silence.clock`) decides
  4  twice in 45 minutes: a second pass writes nothing, the next line comes 45 minutes after the first, and a mover's write in between starts the 45 minutes again
  5  not on an agent: a hold (dated wake or none), a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off to a back agent are skipped; one to a front
     agent is written
  6  the switch: absent or a TOML true writes the line (on by default); false, the string "true" and 1 write nothing; the example config documents it as true; read-only copies write nothing
  7  a front agent's item gets its line like any other and nothing is sent to anyone (no message, no ladder entry)
  8  the tick: `_silence_tick` (the audit tick) runs it (with the audit on in script mode) and stands still when the audit is off or in agent mode; an item read again under the lock that is no longer due is left alone; one that cannot
     be saved stops no other
  9  the pure parts: the line's words, `last_line`, the log's cap, a malformed item, a log entry dated far ahead, an item with no timestamp, each tied-pull-request kind, `new_entries`
  10 the cap on lines: one every 50 minutes on the ten-minute grid for the first 24 hours of silence (27), then one every 6 hours (51 in a week, the clock stepped), a clock that goes backwards delays the next line without a second write
  11 the lines are kept out of the stall ladder's log: its entries are untouched and not crowded out, `get` prints the newest as `audit:` and never as `stall:`, both History renderers show the line
  12 a last-activity record dated ahead of the clock is no event
  13 the audit tick stands still as a whole while the audit is off
  14 tick jitter: on a ten-minute grid with 0 to 8 seconds of jitter the lines come every 50 minutes in the first day and every 6 hours after
  15 a torn entry in the log never raises
  16 a verified line is the item's last activity: the row reads its time and words, an idle line leaves the record alone, an older line never replaces a newer real event, the backfill does not undo it
  18 the row never reads "idle over 1 h" between two lines (read through act_parts and band at the worst landing time); the record never goes backwards (a stepped-back clock, a record dated ahead)
  17 the tie to the ITEM: the reader of a session's transcript (running within 90 minutes, quiet to 6 hours, dropped past the cap, clock skew), what each unreadable thing reads as (unknown), the pure tie, the server's reader on the registry
  19 a running subagent tied to no item leaves the mover's items unknown, not idle (and not handed on); a front agent's busy pane still verifies
  21 an empty or partial fleet index reads the mover unknown, never idle; the lookups by a session id (a transcript id, a neutral heartbeat id) beside the lookups by name
  22 a role map that cannot be read reads the mover as front (never as a builder) for the hourly line
  23 a pull request number written alone is the item's own repository's: two items anchored to the same number in two repositories are told apart by the URL or `owner/repo#n`
  24 a mover's own status write with new text is the item's hourly update (kind `update`, the text its words, the row reads it), as the audit's line is: the same text again, a write by anyone but the mover and a cleared status
     are not; the audit's own line still stamps beside it and the newer of the two is the record
  26 the first line is owed after 45 minutes without activity (`hourly.EVERY`, the same as `FAST_GAP`), so it lands inside the hour: none at 44 minutes, one at 46, the cadence after it and the slow stretch unchanged, the constants pinned by value, the idle hand-over still waits a full hour, a tied pull request's event still verifies within the hour
  20 the tie by description first, the 90-minute and 6-hour boundaries through the audit, an absent registry row (idle, unless the fleet heartbeat holds the session running elsewhere: unknown) against a present but unreadable one (unknown), a read error kept for the pass, a front test that raises

  25 a subagent flagged finished still runs while it is parked on a task of its own (started by a result that opens with the start text; a Monitor ends with its lifetime; an end notice that only the session's transcript holds ends it) or resumed (`toolUseResult` of the session's transcript); one with no flag whose last row is an interruption is dead unless resumed; the values of the windows, slacks and bounds are pinned

    tests/run-suite audit_hourly       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="hourly-"); T = pathlib.Path(tmp)
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
NAMES = ("home-front", "team-back", "home-peer", "home-peer2", "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
# Not near a local midnight: a row's words carry a date once its time is on another day than the clock it is read at, and check 16 reads an event 80 minutes before
# `now0` (and the row 2 minutes after it). The distance is 100 minutes either side and a hit moves the clock back four hours, which lands 140 to 240 minutes before a
# midnight (a smaller step, or a distance of 4000 seconds, left a clock at 01:07 local with that event on the day before).
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 6000: now0 -= 4 * 3600
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                  "agents": ALPHA, "back_agents": {"team-back": ALPHA["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n# alpha\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.service import gates
from stackshot.web import server
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import ladder as ladder_svc, stall as stall_svc, stall_tick as stalltick_svc
from stackshot.web.tools import sessions as _wt_sessions
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.service import telling
from stackshot.audit import hourly as HR, silence as SL
from stackshot.waits import stall as ST, handoff as HO
from stackshot.audit import hourly_log as HL
from stackshot.model import last_activity as LA, activity as ACT
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the saves below: the pass is given its `now`, and the saves stamp from the server's own clock."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = handoff_svc.time = hcold_svc.time = stall_svc.time = stalltick_svc.time = CLK
server._cfg.CFG["audit"]["pattern_review"] = "off"
server._cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every message the server was asked to send: none is expected from this pass
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append((to, text)), "delivered to " + to)[1]
telling.tell_woken = lambda *a, **k: sent.append(("tell_woken", a))
server._inbox_flag_send = lambda *a, **k: sent.append(("flag", a))
panes = {}                                                         # mover -> the pane's registry status; "boom" = unreadable
def fake_status(who, idx=None):
    st = panes.get(who, "")
    if st == "boom": raise OSError("registry unreadable")
    return (st, now0 - 3600) if st else ("", 0.0)
handoff_svc.handoff_status = fake_status
server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = lambda: {}

def put(i, mover="home-peer", status="open", act=90, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0 (a bare confirm and the server's saves are recent)."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "written_at": at, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def lines(i): return HL.log_of(mt(i))
SUBS = {}; ANCH = {}                                                  # mover -> its running subagents ([{"text": description and brief}]); item id -> the pull requests anchored to it
def BID(n): return "board" + "#" + str(n)                              # an item id as a brief names it, built from pieces
def run_on(mover, *words): SUBS.setdefault(mover, []).append({"id": f"s{len(SUBS.get(mover, []))}", "text": "\n".join(words), "at": now0 - 60})
def tick(at=None, **kw):
    """One pass of the hourly line at `at` (default now0), the server's clock set to it → the ids written. The mover's running subagents and the anchored pull requests are the dicts above."""
    at = now0 if at is None else at
    CLK.t = at
    kw.setdefault("subagents", lambda who: SUBS.get(who, [])); kw.setdefault("anchored", ANCH)
    try: return server._hourly_tick(now=at, **kw)
    finally: CLK.t = None
def on(): server._cfg.CFG["audit"]["hourly_line"] = True
def off(): server._cfg.CFG["audit"]["hourly_line"] = False
def hm(at): return time.strftime("%H:%M", time.gmtime(at + 4 * 3600))      # the instance zone is Asia/Dubai, UTC+4
def clean_pane(): panes.clear(); SUBS.clear(); ANCH.clear()
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()
def pr_event(i, kind, what, ago_min): mt_ = rd(i); mt_["metadata"]["last_activity"] = {"at": now0 - ago_min * MIN, "kind": kind, "what": what}; (T / f"store/a/{i}.json").write_text(json.dumps(mt_))
def work(state, ago_min, agent="home-peer"): return [{"id": "build-it", "text": "build it", "agent": agent, "state": state, "ts": now0 - ago_min * MIN}]

# ================================================================ 6a. the switch is on by default
put(1, act=90); panes["home-peer"] = "busy"
check("6 the example config documents `hourly_line = true` in [audit]", re.search(r"(?m)^hourly_line = true\b", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)
check("6 …and the config as loaded (from that example) has it on", HR.enabled() is True)
server._cfg.CFG["audit"].pop("hourly_line", None)
check("6 …and with the key absent the code's default is on: a pass writes the line", HR.enabled() is True and tick() == ["a1"] and len(lines(1)) == 1, lines(1))
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90)
for label, val in (("false", False), ("the string true", "true"), ("1", 1), ("yes", "yes")):
    server._cfg.CFG["audit"]["hourly_line"] = val
    check(f"6 {label} leaves it off (only a TOML true leaves it on)", HR.enabled() is False and tick() == [] and lines(1) == [])
on()
check("6 a TOML true switches it on", HR.enabled() is True)
ro = server._ro.is_read_only
server._ro.is_read_only = lambda: True
check("6 a read-only standby copy writes nothing", tick() == [] and lines(1) == [])
server._ro.is_read_only = ro

# ================================================================ 1. due and verified
clean_pane(); put(1, mover="team-back", act=90); put(2, act=90); put(3, act=90); put(4, act=90); put(5, act=90); put(6, act=90, work=work("in progress", 30))
panes["home-peer"] = "busy"; panes["team-back"] = "busy"                                          # item 1 is team-back's only item (a busy pane); 4 and 6 are home-peer's; 2, 3 and 5 are home-peer2's (an idle pane)
put(2, mover="home-peer2", act=90); panes["home-peer2"] = "idle"
put(3, mover="home-peer2", act=90, work=work("in progress", 30, agent="home-peer2"))               # a status in progress on the mover's own step, which proves nothing; a subagent of the mover's whose brief names this item does
run_on("home-peer2", f"Build {BID(3)}: the thing")
put(4, act=90, last_activity={"at": now0 - 20 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"})
put(5, mover="home-peer2", act=90, last_activity={"at": now0 - 20 * MIN, "kind": "review", "what": "review on PR 9"})
put(6, act=90, work=work("in progress", 30), last_activity={"at": now0 - 20 * MIN, "kind": "ci_result", "what": "CI passing again on PR 7"})
run_on("home-peer", f"Fix {BID(6)}")
before = {i: rd(i) for i in range(1, 7)}
with _Err() as err: got = tick()
check("1 a pass over the six writes a line on the items with something verified and the idle ones too: items 1 to 6 are all due", got == ["a1", "a2", "a3", "a4", "a5", "a6"], got)
L = {i: lines(i) for i in range(1, 7)}
check("1 a busy pane of a mover with no other item on an agent: `Audit hh:mm: verified the mover's pane is in a turn (live state only, …)`, the time in the instance's zone, kind audit", len(L[1]) == 1 and L[1][0]["text"] == f"Audit {hm(now0)}: verified the mover's pane is in a turn" + HR.LIVE_ONLY and "live state only, nothing recorded on the item" in L[1][0]["text"] and L[1][0]["kind"] == "audit" and L[1][0]["at"] == now0, L[1])
check("1 an idle pane verifies nothing: the line says idle", len(L[2]) == 1 and L[2][0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and L[2][0]["kind"] == "audit_idle", L[2])
check("1 a running subagent of the mover's whose brief names this item is verified (the pane idle), a status line in progress is not read", len(L[3]) == 1 and L[3][0]["text"] == f"Audit {hm(now0)}: verified a subagent is running on it" + HR.LIVE_ONLY, L[3])
check("1 a CI result of a tied pull request in the last hour (metadata.last_activity) is verified, in the record's words, and a line that rests on a recorded event carries no live-state note (the mover's busy pane says nothing of this item: it has another)", L[4][0]["text"] == f"Audit {hm(now0)}: verified CI failed on PR 5", L[4])
check("1 …a review likewise", L[5][0]["text"] == f"Audit {hm(now0)}: verified review on PR 9", L[5])
check("1 …several signals are joined in one line", L[6][0]["text"] == f"Audit {hm(now0)}: verified a subagent is running on it, CI passing again on PR 7", L[6])
W1 = {1: "audit verified the mover's pane is in a turn", 3: "audit verified a subagent is running on it", 6: "audit verified a subagent is running on it, CI passing again on PR 7"}
check("1 a line that verified something is stamped as the item's last-activity record (kind audit, the line's phrases), one that verified nothing (item 2) is not, and one that rests on a recorded event alone (item 5) leaves that event as it was, at its own time and kind",
      all(mt(i).get("last_activity") == {"at": now0, "kind": "audit", "what": W1[i]} for i in (1, 3, 6))
      and "last_activity" not in mt(2) and mt(4)["last_activity"] == before[4]["metadata"]["last_activity"] and mt(5)["last_activity"] == before[5]["metadata"]["last_activity"] == {"at": now0 - 20 * MIN, "kind": "review", "what": "review on PR 9"}, [mt(i).get("last_activity") for i in range(1, 7)])
check("1 the save is the server's own bookkeeping: the activity clock, `updated`, the confirm and the writer are exactly as they were",
      all(all(rd(i)[k] == before[i][k] for k in ("activity", "updated", "state_updated", "confirmed", "written_by", "written_at")) for i in range(1, 7)))
ch = lambda i: {k for k in mt(i) if mt(i)[k] != before[i]["metadata"].get(k)}
check("1 …the History shows it: the revision's new entries of the item's own log are the line (hourly_log.new_entries), and nothing else changed in the metadata but the log and the phase stamp every save adds",
      [e["text"] for e in HL.new_entries(before[1]["metadata"], before[1]["metadata"])] == [] and [e["text"] for e in HL.new_entries(before[2]["metadata"], rd(2)["metadata"])] == [L[2][0]["text"]]
      and ch(2) == {"hourly_audit", "phase"} and ch(4) == {"hourly_audit", "phase"} and ch(6) == {"hourly_audit", "phase", "last_activity"}, (ch(2), ch(4), ch(6)))
check("1 nothing is sent to anyone: no message, no notice, no flag", sent == [], sent)
check("1 the server logs each line on stderr", err.text.count("hourly line: Audit") == 6, err.text)
# what verifies nothing
def nothing_fixtures():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    put(1, act=90); put(2, act=90, work=work("in progress", 30, agent="home-peer2")); put(3, act=90, work=work("done", 30)); put(4, act=90, work=work("in progress", 120))
    put(5, act=90, last_activity={"at": now0 - 90 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"}); put(6, act=90, last_activity={"at": now0 - 20 * MIN, "kind": "step_done", "what": "step 1 done"})
    put(7, act=90, last_activity={"at": now0 - 20 * MIN, "kind": "update", "what": "building"})
clean_pane()
for pane_st in ("idle", "shell", "boom", ""):
    panes["home-peer"] = pane_st
    nothing_fixtures()
    got_n = tick()
    check(f"1 a pane that is {pane_st or 'not shown on this box'} verifies nothing, and no other signal on items 1 to 7 does: all seven say idle",
          got_n == ["a1", "a2", "a3", "a4", "a5", "a6", "a7"] and all(lines(i)[-1]["kind"] == "audit_idle" for i in range(1, 8)), [lines(i) for i in range(1, 8)])
nothing_fixtures()
check("1 …(another agent's status line, a done one, one older than 90 minutes, a pull request event older than an hour, a step done and a bare update, each on its own item)",
      all(lines(i) == [] for i in range(1, 8)) and all(mt(i).get("stall") is None and mt(i).get("hourly_audit") is None for i in range(1, 8)))
panes["home-peer"] = "busy"
tick()
check("1 …they say idle, and with the pane busy they still do: the mover has seven items on an agent, so its busy pane says nothing of any one", [e["text"] for i in range(1, 8) for e in lines(i)] == [f"Audit {hm(now0)}: idle, nothing verified"] * 7, [lines(i) for i in range(1, 8)])

# ================================================================ 2. due and nothing verified
clean_pane()
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90)
check("2 nothing verified: the line says idle, kind audit_idle, `idle_marked` reads it, the last-activity record is untouched",
      tick() == ["a1"] and lines(1)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and lines(1)[0]["kind"] == "audit_idle" and HR.idle_marked(mt(1)) and "last_activity" not in mt(1))
panes["home-peer"] = "busy"
tick(now0 + 61 * MIN)
check("2 the next hour verifies the pane: idle_marked reads the newest line, not the first", len(lines(1)) == 2 and not HR.idle_marked(mt(1)) and HR.last_line(mt(1))["kind"] == "audit")

# ================================================================ 3. not due
clean_pane(); panes["home-peer"] = "busy"
put(1, act=44); put(2, act=46); put(3, act=10); put(4, act=90, hold=False)
put(5, act=240); d5 = rd(5); d5["state_updated"] = now0 - 20 * MIN; (T / "store/a/5.json").write_text(json.dumps(d5))           # silent four hours, but left a hold twenty minutes ago
put(6, act=90); d6 = rd(6); d6["confirmed"] = now0 - 1 * MIN; (T / "store/a/6.json").write_text(json.dumps(d6))                      # a bare confirm just now moves nothing: due
got = tick()
check("3 under 45 minutes without activity is not due (44 minutes, 10 minutes); 46 and a confirm just now are", got == ["a2", "a4", "a6"], got)
check("3 an item that left a hold twenty minutes ago counts from then (the quiet-time clock), not from its activity four hours back", lines(5) == [] and SL.clock(rd(5), "home-peer") == now0 - 20 * MIN)
put(7, act=44.9); check("3 the limit is exact: 44 minutes 54 seconds is not due", tick() == [])
put(7, act=45); check("3 …45 minutes is", tick() == ["a7"], tick())

# ================================================================ 4. twice in an hour
clean_pane(); panes["home-peer"] = "busy"
for i in range(1, 12): (T / f"store/a/{i}.json").unlink(missing_ok=True)
put(1, act=90)
first = tick()
second = tick(now0 + 10 * MIN); third = tick(now0 + 44 * MIN)
check("4 a second and a third pass inside 45 minutes (10 and 44 minutes after the line) write nothing: one line", first == ["a1"] and second == [] and third == [] and len(lines(1)) == 1, (first, second, third, lines(1)))
check("4 45 minutes after the first line (`FAST_GAP`), an item still silent gets the next", tick(now0 + 45 * MIN) == ["a1"] and len(lines(1)) == 2 and lines(1)[1]["at"] == now0 + 45 * MIN)
put(9, act=90); tick(); b1 = tick(now0 + 44 * MIN + 59); b2 = tick(now0 + 45 * MIN)
check("4 the gap is exact: 44 minutes 59 seconds after the line nothing, 45 minutes the next line", "a9" not in b1 and "a9" in b2 and [e["at"] for e in lines(9)] == [now0, now0 + 45 * MIN], (b1, b2, lines(9)))
put(2, act=90); tick(); d2 = rd(2); d2["activity"] = now0 + 5 * MIN; (T / "store/a/2.json").write_text(json.dumps(d2))
r48, r51 = tick(now0 + 48 * MIN), tick(now0 + 51 * MIN)
check("4 a write by the mover after the line starts the 45 minutes again: 43 minutes after it nothing (48 after the line), 46 minutes after it (and 51 after the line) the next line",
      "a2" not in r48 and "a2" in r51 and len(lines(2)) == 2, (r48, r51, lines(2)))
put(3, act=90); tick(now0 + 130 * MIN); tick(now0 + 131 * MIN)
check("4 two passes close together write one line", len([e for e in lines(3) if e["at"] == now0 + 130 * MIN]) == 1 and not any(e["at"] == now0 + 131 * MIN for e in lines(3)), lines(3))
# the stale view: a pass whose list was made before another pass wrote the line
put(4, act=90); put(8, act=90); stale_items = {"a4": rd(4), "a8": rd(8)}      # the view the slower pass made: both open, no line yet
tick()
with _Err():
    real_pass = HR.pass_
    put(8, act=90, status="completed", outcome="done")
    HR.pass_ = lambda items, now, env=None, pane=None, same=None, *a, **k: [("a4", {"text": "stale", "verified": [], "recorded": [], "kind": "audit_idle"}), ("a8", {"text": "stale", "verified": [], "recorded": [], "kind": "audit_idle"})]      # the list a slower pass made before the line was written, and an item that closed since
    try: stale = server._hourly_tick(now=now0 + 5 * MIN, items=stale_items)
    finally: HR.pass_ = real_pass
check("4 an item read again under the lock that is no longer due (a line written since, or closed since) is left alone", stale == [] and len(lines(4)) == 1 and lines(8) == [], (stale, lines(4), lines(8)))

# ================================================================ 5. not on an agent
clean_pane(); panes["home-peer"] = "busy"; panes["team-back"] = "busy"; panes["home-front"] = "busy"
for p in (T / "store/a").glob("*.json"): p.unlink()
put(1, act=90, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 5 * H + 4 * H)))           # a hold until a dated wake (instance zone)
put(2, act=90, hold=True)                                                                                  # a hold, no wake
put(3, act=90, state="parked", hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 3 * H + 4 * H)))
put(4, act=90, wait_kind="relay")
put(5, act=90, state="blocked", supplies="its output", after=["a6"])
put(6, act=30)                                                                                              # the open item a5 waits after: recent, not due itself
put(7, mover="Oliver", act=90, state="your-call", needs=["decision"], ask="pick one", next="Oliver: pick")
put(8, act=90, status="completed", outcome="done")
put(9, mover="team-back", act=90, **{HO.KEY: HO.new_record("team-back", "", "home-front", now0 - 90 * MIN)})      # handed to a back agent, not taken
put(10, mover="home-front", act=90, **{HO.KEY: HO.new_record("home-front", "", "team-back", now0 - 90 * MIN)})   # handed to a front agent, not taken: checked
put(11, mover="home-peer", act=90, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 5 * H + 4 * H)))     # a wake with no wait behind it leaves the item on agent
d1 = rd(1); got5 = tick()
check("5 a hold (dated wake or none), a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off to a back agent, and an item not yet due: none written",
      not any(g in got5 for g in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9")), got5)
check("5 …an untaken hand-off to a front agent is written and so is an item with a wake alone", sorted(got5) == ["a10", "a11"], got5)
check("5 the skipped items are byte for byte as they were", rd(1) == d1)

# ================================================================ 7. a front agent's item
clean_pane(); panes["home-front"] = "idle"
for p in (T / "store/a").glob("*.json"): p.unlink()
put(1, mover="home-front", act=90)
check("7 the test's front agent is one for the server's own answer", telling.front_keeper("home-front", "projects/alpha")[0] is True and telling.front_keeper("team-back", "projects/alpha")[0] is False)
got7 = tick()
check("7 a front agent's item due gets its line like any other (a pane that is not in a turn: idle)", got7 == ["a1"] and lines(1)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified", lines(1))
check("7 …and nothing is sent to it or to anyone: no message, no notice, no ladder entry", sent == [] and stall_svc.stall_load().get("a1") is None, (sent, stall_svc.stall_load()))
panes["home-front"] = "busy"; tick(now0 + 61 * MIN)
check("7 …a front agent in a turn is verified the same", lines(1)[1]["text"] == f"Audit {hm(now0 + 61 * MIN)}: verified the mover's pane is in a turn" + HR.LIVE_ONLY, lines(1))

# ================================================================ 8. the tick
clean_pane(); panes["home-peer"] = "busy"
for p in (T / "store/a").glob("*.json"): p.unlink()
put(1, act=90); put(2, act=90)
server._cfg.CFG["audit"]["enabled"] = False
check("8 `_silence_tick` stands still while the audit is off: no line", server._silence_tick() is None and lines(1) == [])
server._cfg.CFG["audit"]["enabled"] = True; server._cfg.CFG["audit"]["mode"] = "agent"
check("8 …and in agent mode (the rollback)", server._silence_tick() is None and lines(1) == [])
server._cfg.CFG["audit"]["mode"] = "script"
real_now = time.time
res = server._silence_tick()
check("8 with the audit on in script mode the audit tick writes the hourly line: one on each item", len(lines(1)) == 1 and len(lines(2)) == 1, (res, lines(1), lines(2)))
off()
for i in (1, 2): put(i, act=90)
server._silence_tick()
check("8 …and with `hourly_line` off the same tick writes none", lines(1) == [] and lines(2) == [])
on()
real_save = server._writes.save
def save_fail(gid, *a, **k):
    if gid == "a1": raise OSError("disk full")
    return real_save(gid, *a, **k)
server._writes.save = save_fail
for i in (1, 2): put(i, act=90)
with _Err() as e8: got8 = tick()
server._writes.save = real_save
check("8 one item that cannot be saved stops no other, and the failure is logged", got8 == ["a2"] and "a1 hourly line not written: OSError" in e8.text and lines(2) != [], (got8, e8.text))
real_hourly = server._hourly_tick
def boom(**kw): raise RuntimeError("pass failed")
server._hourly_tick = boom
with _Err() as e8b: r8 = server._silence_tick()
server._hourly_tick = real_hourly
check("8 a hourly pass that raises never stops the audit tick that called it", e8b.text.count("hourly line not run: RuntimeError") == 1, e8b.text)

# ================================================================ 13. the audit tick with the audit off stands still as a whole
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90); put(2, act=90)
server._cfg.CFG["audit"]["enabled"] = False
server._silence_tick()
server._cfg.CFG["audit"]["enabled"] = True
check("13 with the audit off the tick stands still as a whole: no line", lines(1) == [] and lines(2) == [])

# ================================================================ 10. the cap on lines, a clock that goes backwards
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90)                                                      # silent from 90 minutes before now0
t_ = now0; n_ = 0; stamps = []
while t_ <= now0 + 7 * 24 * H:
    got10 = tick(t_)
    if got10: stamps.append(t_)
    t_ += 10 * MIN                                                  # the ten-minute tick, for a week
silent_at = lambda t: t - (now0 - 90 * MIN)
gaps = [b_ - a_ for a_, b_ in zip(stamps, stamps[1:])]
check("10 a week of silence on a busy pane writes 51 lines (27 in the first day, one every 50 minutes on the ten-minute grid from 1.5 hours of silence; then one every 6 hours), not 168", len(stamps) == 51, len(stamps))
check("10 …one every 50 minutes (the first ten-minute tick past 45) for the first 24 hours of silence, then one every 6 hours", gaps[:26] == [50 * MIN] * 26 and gaps[26:] == [6 * H] * 24 and all(silent_at(a_) < 24 * H for a_ in stamps[:27]) and silent_at(stamps[27]) >= 24 * H, (len(gaps), gaps[24:29]))
check("10 …the log keeps its last eight and the item's last-activity record is the newest line (every line of a busy pane verified something and is stamped)", len(lines(1)) == 8 and mt(1)["last_activity"] == {"at": stamps[-1], "kind": "audit", "what": "audit verified the mover's pane is in a turn"}, (len(lines(1)), mt(1).get("last_activity")))
# a clock that goes backwards delays the next line and never doubles it
put(2, act=90); tick(now0 + 5 * H); k0 = len(lines(2))
back = tick(now0 + 5 * H - 30 * MIN); again = tick(now0 + 5 * H + 20 * MIN); later_ = tick(now0 + 5 * H + 61 * MIN)
check("10 a clock that goes backwards writes nothing, and the next line comes an hour after the last line, never earlier", k0 == 1 and "a2" not in back and "a2" not in again and "a2" in later_ and len(lines(2)) == 2, (k0, back, again, later_, len(lines(2))))

# ================================================================ 11. kept out of the stall ladder's log
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
ladder_log = [{"at": now0 - 100 * MIN + k, "text": f"ladder step {k}"} for k in range(8)]
put(1, act=90, stall={"log": ladder_log})
before11 = rd(1)
tick(); tick(now0 + 61 * MIN); tick(now0 + 122 * MIN)
check("11 the lines are not in the stall ladder's log: its eight entries are exactly as they were, none crowded out, and no Audit text is in it", mt(1)["stall"] == {"log": ladder_log} and len(lines(1)) == 3, (mt(1).get("stall"), len(lines(1))))
txt11 = server._fmt(server._load("a1"))
check("11 `get` prints the newest line with its own prefix (audit:) and the ladder's last three as stall: lines, never an Audit line as a stall step",
      sum(1 for l in txt11.splitlines() if l.startswith("audit: ")) == 1 and "Audit " + hm(now0 + 122 * MIN) in txt11 and not any(l.startswith("stall: ") and "Audit " in l for l in txt11.splitlines())
      and sum(1 for l in txt11.splitlines() if l.startswith("stall: ")) == 3, [l for l in txt11.splitlines() if l.startswith(("audit:", "stall:"))])
from stackshot.web import render as board_render
from stackshot.web.ui import render as ui_render
for label, mod in (("the board's renderer", board_render), ("the signed-in UI's renderer", ui_render)):
    bd = mod.Board(str(T / "store")); row = bd.item("a1") if hasattr(bd, "item") else next(r for r in bd.rows if r["gid"] == "a1")
    bd.item_versions = lambda r: [(now0 - 500, before11), (now0 - 400, rd(1))]
    evs, _more = bd.item_events(row)
    got11 = [x for x in evs if x[1] == "stall" and "Audit " in x[2]]
    check(f"11 {label} shows the audit lines in the History, one each, said by stackshot", len(got11) == 3 and all(x[2].startswith("stackshot: Audit ") for x in got11) and not any("ladder step" in x[2] for x in evs if "Audit" in x[2]), evs)
# an update that rewrites other metadata keeps the log (the key is the server's, like the ladder's)
check("11 the key is a re-park-quiet bookkeeping key like the ladder's and the front agent's", "hourly_audit" in gates._REPARK_QUIET)

# ================================================================ 12. a record dated ahead is no event; an absent key is off
clean_pane(); panes["home-peer"] = "idle"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90, last_activity={"at": now0 + 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"})
put(2, act=90, last_activity={"at": now0 - 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 6"})
tick()
check("12 a last-activity record dated ahead of the clock is no recorded event (the line says idle, the record is left alone); the same event ten minutes in the past is verified (and neither is stamped)",
      lines(1)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and mt(1)["last_activity"]["at"] == now0 + 10 * MIN
      and lines(2)[0]["text"] == f"Audit {hm(now0)}: verified CI failed on PR 6" and mt(2)["last_activity"] == {"at": now0 - 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 6"}, (lines(1), mt(1).get("last_activity"), lines(2)))
put(3, act=90); off()
check("12 with `hourly_line = false` in the loaded config the pass is off and writes nothing", server._cfg.CFG["audit"]["hourly_line"] is False and HR.enabled() is False and tick() == [] and lines(3) == [])
on()

# ================================================================ 14. tick jitter: an hour on the grid is an hour
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
import random
rng = random.Random(7)
put(1, act=90)                                                      # silent from 90 minutes before now0
t_ = now0; stamps14 = []
while t_ <= now0 + 3 * 24 * H:
    if tick(t_ + rng.uniform(0, 8)): stamps14.append(t_ + 0.0)      # the ten-minute tick reads its clock 0 to 8 seconds late, a different amount each time
    t_ += 10 * MIN
# (the stamp is the grid time; the line itself is dated by the jittered clock)
gaps14 = [b_ - a_ for a_, b_ in zip(stamps14, stamps14[1:])]
first_day = [a_ for a_ in stamps14 if a_ - (now0 - 90 * MIN) < 24 * H]
check("14 on a ten-minute grid with 0 to 8 seconds of jitter an item silent for 3 days gets 27 lines in the first 24 hours of silence, as on an exact grid, not 23", len(first_day) == 27, (len(first_day), len(stamps14)))
check("14 …one every 50 minutes on the grid: every gap in the first day is exactly 50 minutes (never 60), then one every 6 hours (never 6 hours 10 minutes)", gaps14[:26] == [50 * MIN] * 26 and gaps14[26:] and all(g == 6 * H for g in gaps14[26:]), (gaps14[:3], gaps14[24:29]))

# ================================================================ 15. a torn entry in the log never raises
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
good = {"at": now0 - 600, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}
torn = [{"at": "bad", "text": "x", "kind": "audit"}, {"at": float("inf"), "text": "x", "kind": "audit"}, {"at": 1e30, "text": "x", "kind": "audit"}, {"at": float("nan"), "text": "x", "kind": "audit"},
        {"at": now0 - 300, "kind": "audit"}, {"at": now0 - 200, "text": 7, "kind": "audit"}, {"at": None, "text": "x", "kind": "audit"}, "not a dict", {"at": True, "text": "x", "kind": "audit"}]
put(1, act=90, hourly_audit={"log": [good] + torn})
txt15 = server._fmt(server._load("a1"))
check("15 `get` on an item whose log holds torn entries (a time that is no number, inf, 1e30, nan, no text, a text that is no string, not a dict) does not raise and prints the one good line", sum(1 for l in txt15.splitlines() if l.startswith("audit: ")) == 1 and "Audit 10:00: idle, nothing verified" in txt15, [l for l in txt15.splitlines() if l.startswith("audit:")])
check("15 …the torn entries are left out of the log, not read", HL.log_of(mt(1)) == [good] and HR.last_line(mt(1))["at"] == good["at"])
put(2, act=90); base15 = rd(2)
for label, mod in (("the board's renderer", board_render), ("the signed-in UI's renderer", ui_render)):
    bd = mod.Board(str(T / "store")); row = bd.item("a1") if hasattr(bd, "item") else next(r for r in bd.rows if r["gid"] == "a1")
    bd.item_versions = lambda r: [(now0 - 500, base15), (now0 - 400, rd(1))]
    try: evs15, _m = bd.item_events(row); err15 = None
    except Exception as e_: evs15, err15 = [], e_
    got15 = [x for x in evs15 if "Audit " in x[2]]
    check(f"15 {label} shows the one good line and does not raise on the torn ones", err15 is None and len(got15) == 1, (err15, evs15))
# a good entry that repeats the text of an older one a day later is a new line, not a re-read
m_d = {}; HL.note(m_d, 100.0, "Audit 10:00: idle, nothing verified", "audit_idle")
m_e = json.loads(json.dumps(m_d)); HL.note(m_e, 100.0 + 86400, "Audit 10:00: idle, nothing verified", "audit_idle")
check("15 new_entries: the same words a day later are a new History line", [e["at"] for e in HL.new_entries(m_d, m_e)] == [100.0 + 86400], HL.new_entries(m_d, m_e))

# ================================================================ 9. the pure parts
clean_pane(); put(1, act=90); put(2, act=90)
meta = {"hourly_audit": {"log": [{"at": 20.0, "text": "plain", "kind": "other"}, {"at": 9.0, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}, {"at": 7.0, "text": "Audit 09:00: verified x", "kind": "audit"}, {"at": "bad", "text": "x", "kind": "audit"}, {"at": True, "text": "x", "kind": "audit"}]}}
check("9 last_line is the newest audit entry by time, skipping an entry of another kind and a torn one", HR.last_line(meta)["at"] == 9.0 and HR.idle_marked(meta) and HR.last_line({}) is None and HR.last_line(None) is None and not HR.idle_marked({"hourly_audit": {"log": [{"at": 1, "text": "x", "kind": "audit"}]}}))
check("9 the stall ladder's own log is not read: an entry there with an audit kind is no audit line", HR.last_line({"stall": {"log": [{"at": 9.0, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}]}}) is None)
m9b = {}
for k in range(10): HL.note(m9b, float(k), f"line {k}", "audit")
check("9 the log keeps eight entries", len(HL.log_of(m9b)) == 8 and HL.log_of(m9b)[0]["text"] == "line 2" and "stall" not in m9b)
check("9 the line's words: verified a, b / idle, nothing verified, hh:mm in the instance zone", HR.text(now0, ["a", "b"], ["b"]) == f"Audit {hm(now0)}: verified a, b" and HR.text(now0, ["a"], []) == f"Audit {hm(now0)}: verified a" + HR.LIVE_ONLY and HR.text(now0, []) == f"Audit {hm(now0)}: idle, nothing verified")
check("9 the pass reads only: pass_ over the items writes nothing and gives the same list twice", (lambda items: HR.pass_(items, now0, server._silence_env(), lambda w: "busy", handoff_svc.ho_same) == HR.pass_(items, now0, server._silence_env(), lambda w: "busy", handoff_svc.ho_same))({"a1": rd(1), "a2": rd(2)}))
check("9 an item the pass cannot read is left out, and a pane callable that raises verifies nothing", HR.pass_({"a1": {"status": "open", "metadata": "torn"}, "a2": rd(2)}, now0, server._silence_env(), lambda w: (_ for _ in ()).throw(OSError("x")), handoff_svc.ho_same)[0][1]["kind"] == "audit_idle")
check("9 a pane callable of None verifies nothing", HR.verified(rd(2), rd(2)["metadata"], "home-peer", now0, None, handoff_svc.ho_same) == ([], []))

# a log entry dated far ahead hides no later line
far = {"hourly_audit": {"log": [{"at": now0 + 400 * 86400.0, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}]}}
near = {"hourly_audit": {"log": [{"at": now0 + 30 * MIN, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}]}}
check("9 last_line given the clock ignores an entry dated more than an hour ahead of it, and keeps one dated 30 minutes ahead; without the clock it reads both", HR.last_line(far, now0) is None and HR.last_line(near, now0) is not None and HR.last_line(far) is not None)
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90, hourly_audit=far["hourly_audit"]); put(2, act=90, hourly_audit=near["hourly_audit"])
got9 = tick()
check("9 an item whose log holds an entry dated 400 days ahead gets its line now; one whose log holds an entry 30 minutes ahead waits (a clock stepped back a little only delays the line)", got9 == ["a1"] and len(lines(1)) == 2 and len(lines(2)) == 1, (got9, len(lines(1)), len(lines(2))))
# every tied pull request kind verifies, a merge and a comment included
clean_pane(); panes["home-peer"] = "idle"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
kinds9 = {1: ("pr_merged", "PR 4 merged"), 2: ("comment", "comment on PR 4"), 3: ("ci_result", "CI passed on PR 4"), 4: ("review", "review on PR 4"), 5: ("commit", "commit on PR 4")}
for i_, (k_, w_) in kinds9.items(): put(i_, act=90, last_activity={"at": now0 - 5 * MIN, "kind": k_, "what": w_})
put(6, act=90, last_activity={"at": now0 - 61 * MIN, "kind": "commit", "what": "commit on PR 4"})      # a new head commit an hour and a minute old: past the hour, nothing verified
put(7, act=90, last_activity={"at": now0 - 59 * MIN, "kind": "commit", "what": "commit on PR 4"})      # …and one 59 minutes old still verifies
tick()
check("9 a tied pull request's merge, comment, CI result, review and new head commit each verify, in the record's words", all(lines(i_)[0]["text"] == f"Audit {hm(now0)}: verified {w_}" for i_, (k_, w_) in kinds9.items()), [lines(i_) for i_ in kinds9])
check("9 a recorded commit under an hour old verifies (recorded, so the line is no live-only one) and one older than an hour verifies nothing (idle)", lines(7)[0]["text"] == f"Audit {hm(now0)}: verified commit on PR 4" and lines(7)[0]["kind"] == "audit"
      and lines(6)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and lines(6)[0]["kind"] == "audit_idle" and HR.PR_KINDS == frozenset({"ci_result", "review", "comment", "pr_merged", "commit"}), [lines(6), lines(7)])
# an item with no timestamp at all
nots = rd(1); [nots.pop(k_, None) for k_ in ("activity", "updated", "state_updated", "created", "confirmed", "written_at")]
try: wt = HR.due({"a1": nots}, "a1", now0, server._silence_env(), lambda w: "busy", handoff_svc.ho_same)
except Exception as e_: wt = e_
check("9 an item with no timestamp at all is read without an error, and a line for it is written or not at all (never a crash)", wt is None or isinstance(wt, dict), wt)
# new_entries: a later revision does not re-emit an older line
m_a = {}; HL.note(m_a, 100.0, "Audit 10:00: idle, nothing verified", "audit_idle")
m_b = json.loads(json.dumps(m_a)); HL.note(m_b, 4000.0, "Audit 11:00: verified x", "audit")
m_c = json.loads(json.dumps(m_b)); m_c["other"] = 1
check("9 new_entries: the revision that adds a second line shows only that one; a later revision that changes something else shows none, never the older lines again",
      [e["text"] for e in HL.new_entries(m_a, m_b)] == ["Audit 11:00: verified x"] and HL.new_entries(m_b, m_c) == [] and [e["text"] for e in HL.new_entries(None, m_a)] == ["Audit 10:00: idle, nothing verified"])

# ================================================================ 16. a verified line is the item's last activity (the On agent row reads it)
import datetime
from stackshot.model import last_activity_pass as LAP
from stackshot.web.ui import render as ui_render16
def board16(at):
    tz = datetime.timezone(datetime.timedelta(hours=4))      # the instance zone of this test (Asia/Dubai)
    return ui_render16.Board(str(T / "store"), now=datetime.datetime.fromtimestamp(at, tz))
def parts(gid, at): b = board16(at); return b.act_parts(b.item(gid))
def last_words(html): m = re.search(r'<span class="ir-lwhat">([^<]*)</span>', html or ""); return __import__("html").unescape(m.group(1)) if m else None
clean_pane(); panes["team-back"] = "busy"; panes["home-front"] = "busy"; panes["home-peer2"] = "idle"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
OLD = {"at": now0 - 80 * MIN, "kind": "step_done", "what": "step 1 done"}
put(1, mover="team-back", act=90, last_activity=OLD)                       # silent 90 minutes, its last event 80 minutes ago: the row reads "idle over 1 h"; the mover's one item, its pane busy
put(2, mover="home-peer2", act=90, last_activity=OLD)                       # the same, but the mover's pane is idle: nothing is verified
put(3, mover="home-peer2", act=90)                                         # idle pane, no record at all
put(4, mover="home-front", act=90, last_activity={"at": now0, "kind": "ci_result", "what": "CI failed on PR 5"})      # a real event at the very time of the line (a pane that is busy besides)
a1, a2 = parts("a1", now0), parts("a2", now0)
check("16 before the line: the row of an item whose last event was 80 minutes ago reads idle over 1 h and that event", a1 is not None and 'data-b="bad"' in a1[0] and "idle over 1 h" in a1[1] and last_words(a1[1]) == f"Last: step 1 done at {hm(now0 - 80 * MIN)}", a1)
snap16 = {i: rd(i) for i in (1, 2, 3, 4)}
got16 = tick()
check("16 the pass wrote a line on all four", got16 == ["a1", "a2", "a3", "a4"], got16)
check("16 verified (a busy pane): the item's last activity is the audit at the line's time, in the line's words; the row reads active, the age <1m and `Last: audit verified … at hh:mm`",
      mt(1)["last_activity"] == {"at": now0, "kind": "audit", "what": "audit verified the mover's pane is in a turn"}, mt(1).get("last_activity"))
b1 = parts("a1", now0 + 2 * MIN)
check("16 …on the home row: the pill is active (green), the words and the clock are the audit's", b1 is not None and 'data-b="ok"' in b1[1] and ">active<" in b1[1] and last_words(b1[1]) == f"Last: audit verified the mover's pane is in a turn at {hm(now0)}", b1)
check("16 …and the item's own clocks are as they were: the audit's write does not move `activity` (the silence clock reads the same as before the line), `updated` and the writer too",
      all(rd(1)[k] == snap16[1][k] for k in ("activity", "updated", "state_updated", "confirmed", "written_by", "written_at")) and SL.clock(rd(1), "team-back") == SL.clock(snap16[1], "team-back") == now0 - 90 * MIN)
check("16 idle (nothing verified): the record is untouched and the row still reads idle over 1 h and the older event; an item with no record gets none",
      mt(2)["last_activity"] == OLD and mt(2)["last_activity"] == snap16[2]["metadata"]["last_activity"] and lines(2)[0]["kind"] == "audit_idle" and "last_activity" not in mt(3) and lines(3)[0]["kind"] == "audit_idle"
      and "idle over 1 h" in parts("a2", now0 + 2 * MIN)[1] and last_words(parts("a2", now0 + 2 * MIN)[1]) == f"Last: step 1 done at {hm(now0 - 80 * MIN)}" and parts("a3", now0) is None, (mt(2).get("last_activity"), lines(2), parts("a2", now0)))
check("16 an older audit line never replaces a newer real event: a real event at the line's own time stays (newest wins, strictly later), and an audit signal older than the stored event changes nothing",
      mt(4)["last_activity"] == {"at": now0, "kind": "ci_result", "what": "CI failed on PR 5"} and lines(4)[0]["kind"] == "audit"
      and LA.apply(rd(4), [LA.audit_signal("audit verified x", now0 - 5 * MIN)], now0) is False and (lambda it: (LA.apply(it, [LA.audit_signal("audit verified x", now0 - 5 * MIN)], now0), it["metadata"]["last_activity"]["kind"])[1])(rd(4)) == "ci_result", mt(4))
later_real = rd(1); later_real["metadata"]["last_activity"] = {"at": now0 + 30 * MIN, "kind": "comment", "what": "comment on #5"}; (T / "store/a/1.json").write_text(json.dumps(later_real))
tick(now0 + 61 * MIN)
check("16 …a real event the hub recorded after the audit line (30 minutes later) is the record until a line later than it is written: the next line, an hour on, is later and takes it (newest wins both ways)",
      mt(1)["last_activity"] == {"at": now0 + 61 * MIN, "kind": "audit", "what": "audit verified the mover's pane is in a turn, comment on #5"} and len(lines(1)) == 2, (mt(1).get("last_activity"), lines(1)))
check("16 the backfill does not undo it: an item that carries an audit record has a record (the backfill leaves it alone), and the audit's save is no signal in the History the backfill replays",
      LAP.has_record(rd(1), now0 + 62 * MIN) and LAP.replay([(now0 - 100 * MIN, snap16[1]), (now0, rd(1))], now0 + 62 * MIN)[0] == LAP.replay([(now0 - 100 * MIN, snap16[1])], now0 + 62 * MIN)[0], LAP.replay([(now0 - 100 * MIN, snap16[1]), (now0, rd(1))], now0 + 62 * MIN))
# a line of a recorded event alone, and the pure signal
put(5, mover="home-peer2", act=90, last_activity={"at": now0 - 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 6"}); tick()
check("16 a line that rests on a recorded event alone leaves that event as it was (its own time and kind), never stamping the audit over it", mt(5)["last_activity"] == {"at": now0 - 10 * MIN, "kind": "ci_result", "what": "CI failed on PR 6"} and "verified CI failed on PR 6" in lines(5)[0]["text"], (mt(5), lines(5)))
sg = HR.stamp_signal
check("16 stamp_signal: a verified line gives the audit signal at its time, a line that verified nothing or only a recorded event gives none, a torn or empty line gives none, and the words stay one line of at most 80 characters (a recorded phrase that does not fit is left out whole)",
      sg({"kind": "audit", "verified": ["the mover's pane is in a turn", "a subagent is running on it", "CI passing again on PR 7"], "recorded": ["CI passing again on PR 7"]}, 50.0)["what"] == "audit verified the mover's pane is in a turn, a subagent is running on it" and
      sg({"kind": "audit", "verified": ["a subagent is running on it"], "recorded": []}, 50.0) == {"at": 50.0, "kind": "audit", "what": "audit verified a subagent is running on it"}
      and sg({"kind": "audit", "verified": ["the mover's pane is in a turn", "CI failed on PR 5"], "recorded": ["CI failed on PR 5"]}, 50.0)["what"] == "audit verified the mover's pane is in a turn, CI failed on PR 5"
      and sg({"kind": "audit_idle", "verified": [], "recorded": []}, 50.0) is None and sg({"kind": "audit", "verified": [], "recorded": []}, 50.0) is None
      and sg({"kind": "audit_idle", "verified": ["a subagent is running on it"], "recorded": []}, 50.0) is None and sg({"kind": "other", "verified": ["x"], "recorded": []}, 50.0) is None
      and sg({"kind": "audit", "verified": ["CI failed on PR 5"], "recorded": ["CI failed on PR 5"]}, 50.0) is None and sg(None, 50.0) is None and sg({}, 50.0) is None
      and len(sg({"kind": "audit", "verified": ["x" * 200], "recorded": []}, 50.0)["what"]) == LA.MAX_WHAT and sg({"kind": "audit", "verified": ["x"], "recorded": []}, "soon") is None)


# ================================================================ 17. a running subagent is tied to the item, not to the mover
from stackshot.audit import subagent_tie as TIE
WI = "https://github.com/acme/widgets"
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
same_status = work("in progress", 20)                                           # the very same status text on three items of one mover
for i in (1, 2, 3): put(i, act=90, work=same_status)
run_on("home-peer", f"Build the thing for {BID(1)}", "Work only in the worktree; open one pull request.")
got17 = tick()
check("17 one mover with three items, each with a status in progress, one subagent running whose brief names the first: all three are owed a line", got17 == ["a1", "a2", "a3"], got17)
check("17 only the item the subagent is tied to reads verified (a subagent is running on it), and it is stamped as the item's last activity",
      lines(1)[0]["text"] == f"Audit {hm(now0)}: verified a subagent is running on it" + HR.LIVE_ONLY and lines(1)[0]["kind"] == "audit" and mt(1)["last_activity"]["what"] == "audit verified a subagent is running on it", (lines(1), mt(1).get("last_activity")))
check("17 …the other two read idle, nothing verified, though they carry the same status in progress and the mover's pane is busy: marked idle (kind audit_idle, so part F hands them on) and not stamped",
      all(lines(i)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and lines(i)[0]["kind"] == "audit_idle" and HR.idle_marked(mt(i)) and "last_activity" not in mt(i) for i in (2, 3)), [lines(i) for i in (2, 3)])
# what ties, and what does not
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
clean_pane(); panes["home-peer"] = "busy"
for i in (1, 2, 3, 4, 5, 6, 7): put(i, act=90)
ANCH.update({"a2": {"acme/widgets#160"}, "a3": {"acme/widgets#161"}, "a4": {"acme/widgets#160", "acme/widgets#7"}})
run_on("home-peer", "Move the update writes", f"Goal: PR 160 in {WI} (branch moves-the-writes). Run the suites and push.")
run_on("home-peer", "Fix the row", f"see {BID(12)} and {BID(15)}, and {WI}/pull/161 for the row")
got17b = tick()
tied17 = {i: lines(i)[0]["text"].endswith("a subagent is running on it" + HR.LIVE_ONLY) for i in range(1, 8)}
check("17 a subagent names a pull request anchored to the item (`PR 160`, in the item's own repository): items 2 and 4 are tied; the pull request's URL (161) ties item 3; item 1, which no brief names, and the items no anchor reaches are idle",
      tied17 == {1: False, 2: True, 3: True, 4: True, 5: False, 6: False, 7: False} and all(lines(i)[0]["kind"] == "audit_idle" for i in (1, 5, 6, 7)), (tied17, [lines(i)[0]["text"] for i in range(1, 8)]))
clean_pane(); panes["home-peer"] = "busy"; panes["home-peer2"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 12, 13): put(i, act=90)
put(8, mover="home-peer2", act=90); put(9, mover="home-peer2", act=90)
ANCH.update({"a1": {"acme/widgets#40"}, "a12": {"other/repo#40"}})
run_on("home-peer", f"Fix {BID(12)}", f"{BID(123)} is the follow-up; PR 400 in {WI} is another one, #4 and PR 4 are not it")
run_on("home-peer2", f"Fix {BID(1)}")
tick()
tied17b = {i: lines(i)[0]["text"].endswith("a subagent is running on it" + HR.LIVE_ONLY) for i in (1, 12, 13, 8, 9)}
check("17 an id is named whole (board 12 is not 1, 13 or 123), another mover's subagent ties nothing of this mover's (home-peer2's brief names item 1, which is home-peer's), a pull request number alone is not a bare `#4` or another number, and a pull request of another repository with the same number ties nothing",
      tied17b == {1: False, 12: True, 13: False, 8: False, 9: False}, (tied17b, [lines(i)[0]["text"] for i in (1, 12, 13, 8, 9)]))
# the description alone, a subagent that cannot be read, and no view of subagents at all
clean_pane(); panes["home-peer2"] = "idle"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, mover="home-peer2", act=90); put(2, mover="home-peer2", act=90); put(3, mover="home-peer2", act=90); put(4, mover="home-peer2", act=90)
run_on("home-peer2", f"{BID(1)}")                                                    # its description is the item's id and nothing else
tick()
check("17 a subagent whose description is the item's id and nothing else is tied to it", lines(1)[0]["kind"] == "audit" and all(lines(i)[0]["kind"] == "audit_idle" for i in (2, 3, 4)), [lines(i) for i in (1, 2, 3, 4)])
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, mover="home-peer2", act=90); put(2, mover="home-peer2", act=90)
def boom_subs(who): raise OSError("transcript unreadable")
with _Err() as e17: got17c = tick(subagents=boom_subs)
check("17 a subagent view that cannot be read fails safe: a line is written, it reads UNKNOWN (kind audit_unknown, not audit_idle), says the subagents could not be read, stamps nothing, and the item is not idle-marked",
      got17c == ["a1", "a2"] and all(lines(i)[0]["kind"] == "audit_unknown" and "could not be read" in lines(i)[0]["text"] and not HR.idle_marked(mt(i)) and "last_activity" not in mt(i) for i in (1, 2)), (got17c, [lines(i) for i in (1, 2)]))
for i in (1, 2): put(i, mover="home-peer2", act=90)
tick(subagents=lambda who: [{"id": "x", "text": "", "at": 0.0, "unreadable": True}])
check("17 a subagent whose own files cannot be read (listed running with no words) ties to nothing: the mover's items read unknown, not idle", all(lines(i)[0]["kind"] == "audit_unknown" for i in (1, 2)), [lines(i) for i in (1, 2)])
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, mover="home-peer2", act=90, work=work("in progress", 20, agent="home-peer2"))
tick(subagents=lambda who: [])
check("17 no subagent running, only a status in progress on the item: idle (the status is the mover's claim, not read)", lines(1)[0]["kind"] == "audit_idle", lines(1))

# the busy pane counts only for a mover's one item on an agent
clean_pane(); panes["home-peer"] = "busy"; panes["home-peer2"] = "busy"; panes["team-back"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90); put(2, act=90)                                                       # home-peer: two items on an agent
put(3, mover="home-peer2", act=90); put(4, mover="home-peer2", act=90, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 9 * H + 4 * H)))     # home-peer2: one on an agent, one held
put(5, mover="team-back", act=90); put(6, mover="team-back", act=90, status="completed", outcome="done")      # team-back: one on an agent, one closed
tick()
check("17 a busy pane verifies an item only when it is the mover's one item on an agent: a mover with two says nothing of either, one whose other item is held or closed has its one item verified",
      [lines(i)[0]["kind"] if lines(i) else None for i in (1, 2, 3, 5)] == ["audit_idle", "audit_idle", "audit", "audit"] and lines(4) == [] and lines(6) == [], [lines(i) for i in range(1, 7)])

# the reader: the transcript Claude Code keeps beside a session's, read through a pane's registry row
import uuid as _uuid
SID = str(_uuid.UUID("00000000-0000-4000-8000-0000000000aa"))
proj = T / "transcripts/-home-x"; (proj / SID / "subagents").mkdir(parents=True); (proj / f"{SID}.jsonl").write_text("{}\n")
def agent(aid, desc, brief, finished=None, age=60, content="str", meta_ok=True):
    mp, tp = proj / SID / "subagents" / f"agent-{aid}.meta.json", proj / SID / "subagents" / f"agent-{aid}.jsonl"
    m = {"agentType": "general-purpose", "description": desc}
    if finished is not None: m["finished"] = finished
    mp.write_text(json.dumps(m) if meta_ok else "{not json")
    body = brief if content == "str" else [{"type": "text", "text": brief}]
    tp.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": body}}) + "\n" + json.dumps({"type": "assistant"}) + "\n")
    os.utime(tp, (now0 - age, now0 - age))
agent("run1", "Build the thing", f"Goal: {BID(1)} in the worktree")
agent("blocks", "Review", f"Please review {BID(2)}", content="blocks")
agent("done1", "Old work", f"{BID(3)}", finished=True)
agent("stale1", "Left behind", f"{BID(4)}", age=int(TIE.RUNNING_S) + 60)
agent("badmeta", "x", f"{BID(5)}", meta_ok=False)
agent("capped1", "Long gone", f"{BID(6)}", age=int(TIE.QUIET_CAP_S) + 60)
got_run = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}
check("17 the reader lists the running subagents of a session's transcript: no finished flag and a transcript written within the 6-hour cap, the description, the brief (a string or text blocks) and both as its text; a finished one and one past the cap are left out, a meta that cannot be read is listed running with no words (it may be running)",
      sorted(got_run) == ["badmeta", "blocks", "run1", "stale1"] and got_run["badmeta"] == {"id": "badmeta", "text": "", "at": 0.0, "unreadable": True} and got_run["run1"]["text"] == f"Build the thing\nGoal: {BID(1)} in the worktree"
      and got_run["run1"]["description"] == "Build the thing" and got_run["run1"]["brief"] == f"Goal: {BID(1)} in the worktree" and BID(2) in got_run["blocks"]["brief"] and got_run["run1"]["at"] == now0 - 60 and "quiet" not in got_run["run1"], got_run)
check("17 …one older than 90 minutes and younger than the cap is listed running but quiet (a builder waiting on a long run), a fresh one is not marked", got_run["stale1"].get("quiet") is True and got_run["stale1"]["description"] == "Left behind" and "capped1" not in got_run and "done1" not in got_run, got_run.get("stale1"))
# the boundaries, with two seconds of room for the file system's time resolution
agent("b1", "At 90", f"{BID(7)}", age=int(TIE.RUNNING_S) - 2); agent("b2", "Past 90", f"{BID(7)}", age=int(TIE.RUNNING_S) + 2)
agent("b3", "Inside cap", f"{BID(7)}", age=int(TIE.QUIET_CAP_S) - 2); agent("b4", "Past cap", f"{BID(7)}", age=int(TIE.QUIET_CAP_S) + 2)
agent("b5", "Ahead by a skew", f"{BID(7)}", age=-int(TIE.SKEW_S) + 2); agent("b6", "Ahead too far", f"{BID(7)}", age=-int(TIE.SKEW_S) - 2)
got_b = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}
check("17 the 90-minute boundary: a transcript written 90 minutes less two seconds ago is running (not quiet), 90 minutes and two seconds ago is quiet; the cap: 6 hours less two seconds is listed (quiet), 6 hours and two seconds is dropped",
      "quiet" not in got_b["b1"] and got_b["b2"].get("quiet") is True and got_b["b3"].get("quiet") is True and "b4" not in got_b, {k: v.get("quiet") for k, v in got_b.items() if k.startswith("b")})
check("17 clock skew: a transcript dated up to five minutes ahead of the clock is running (a skew of clocks), one dated further ahead is dropped, never listed as running for good", "b5" in got_b and "quiet" not in got_b["b5"] and "b6" not in got_b, sorted(got_b))
for n_ in ("b1", "b2", "b3", "b4", "b5", "b6", "capped1"):
    for ext_ in ("meta.json", "jsonl"): (proj / SID / "subagents" / f"agent-{n_}.{ext_}").unlink()
def raises(fn, exc):
    try: fn()
    except exc: return True
    except Exception: return False
    return False
check("17 …a session with no transcript on this box, a name that is no uuid and no roots cannot be read (Unreadable: unknown, not nothing running); a transcript with no subagents folder and a clock seven hours on (past the cap) give none",
      raises(lambda: TIE.running(str(_uuid.uuid4()), [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running("home-peer", [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running(SID, [], now0), TIE.Unreadable)
      and TIE.running(SID, [str(T / "transcripts")], now0 + 7 * H) == [])
SID2 = str(_uuid.UUID("00000000-0000-4000-8000-0000000000bb")); (proj / f"{SID2}.jsonl").write_text("{}\n")
check("17 …a transcript that has never had a subagent (no subagents folder) has none running: known, not unknown", TIE.running(SID2, [str(T / "transcripts")], now0) == [])
# a first line nested past the parser's depth (a RecursionError) and one that is not JSON, a truncated one, a list that is no text: the subagent is still listed, naming nothing
agent("deep", "Deep one", "x"); (proj / SID / "subagents" / "agent-deep.jsonl").write_text("[" * 200000 + "\n"); os.utime(proj / SID / "subagents" / "agent-deep.jsonl", (now0 - 60, now0 - 60))
agent("junk", "Junk one", "x"); (proj / SID / "subagents" / "agent-junk.jsonl").write_text("not json at all\n"); os.utime(proj / SID / "subagents" / "agent-junk.jsonl", (now0 - 60, now0 - 60))
try: got_deep = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}; err_deep = None
except BaseException as e_: got_deep, err_deep = {}, e_
check("17 a first line nested too deep (RecursionError) or not JSON never raises out of the reader: the subagent is listed running with its description and no brief, so it ties to nothing and the mover reads unknown",
      err_deep is None and got_deep.get("deep", {}).get("text") == "Deep one\n" and got_deep.get("junk", {}).get("text") == "Junk one\n" and not TIE.tied([got_deep["deep"]], BID(1)), (err_deep, got_deep.get("deep")))
for n_ in ("deep", "junk", "badmeta"):
    for ext_ in ("meta.json", "jsonl"): (proj / SID / "subagents" / f"agent-{n_}.{ext_}").unlink()
check("17 the pure tie: the id whole, a pull request by its URL or `PR n`/`#n` for the repository it is anchored in, never another number, another repository or a longer id; no text and no keys tie nothing",
      TIE.names_item(f"x {BID(1)}.", BID(1)) and TIE.names_item(f"X {BID(1).upper()}", BID(1)) and not TIE.names_item(BID(12), BID(1)) and not TIE.names_item("x" + BID(1), BID(1)) and not TIE.names_item("x" + BID(1), BID(1))
      and TIE.names_item("see PR 160", BID(9), ["acme/widgets#160"]) and TIE.names_item("see #160", BID(9), ["acme/widgets#160"]) and TIE.names_item(f"{WI}/pull/160", BID(9), ["Acme/Widgets#160"]) and not TIE.names_item("see PR 1600", BID(9), ["acme/widgets#160"])
      and not TIE.names_item("https://github.com/other/repo/pull/160", BID(9), ["acme/widgets#160"]) and not TIE.names_item("", BID(1), ["acme/widgets#160"]) and not TIE.names_item("PR 160", "", []) and TIE.tied([{"text": f"a {BID(1)}"}], BID(1)) and not TIE.tied([], BID(1)) and not TIE.tied(None, BID(1)))
# end to end: the server's own reader, through a pane's registry row (the isolated HOME), with no subagent view injected
sess_dir = T / "home/.claude/sessions"
row_path = sess_dir / f"{os.getpid()}.json"
OTHER_ROW = {"sess-z9": {"machine": "b", "name": "home-stew", "seen": "2026-01-01T00:00:00Z"}}      # a whole fleet index that holds no row of the mover (neutral fixture ids)
def registry(status="busy", sid=SID, kind="interactive", name="home-peer"): row_path.write_text(json.dumps({"pid": os.getpid(), "sessionId": sid, "kind": kind, "name": name, "status": status, "statusUpdatedAt": int(now0 * 1000), "updatedAt": int(now0 * 1000)}))
try:
    registry()
    check("17 the server's reader gives the running subagents of a mover whose pane is in a turn", [x["id"] for x in server._mover_subagents("home-peer", {}, now0)] == ["blocks", "run1", "stale1"], server._mover_subagents("home-peer", {}, now0))
    registry("idle"); a_ = server._mover_subagents("home-peer", {}, now0)
    registry("shell"); b_ = server._mover_subagents("home-peer", {}, now0)
    check("17 …and none when the pane is idle or showing a shell, or the mover has no registry row on this box at all (the session is gone, or runs elsewhere: nothing is claimed, so its items read idle as built)", a_ == [] and b_ == [] and server._mover_subagents("home-front", OTHER_ROW, now0) == [], (a_, b_))
    import subprocess as _sp
    dead_ = _sp.Popen(["true"]); dead_.wait()
    row_path.write_text(json.dumps({"pid": dead_.pid, "sessionId": SID, "kind": "interactive", "name": "home-peer", "status": "busy"}))
    check("17 …a row whose process is gone is no row: nothing is claimed, as for a mover with no row", server._mover_subagents("home-peer", OTHER_ROW, now0) == [], server._mover_subagents("home-peer", OTHER_ROW, now0))
    odd_ = {}
    registry("busy", kind="headless"); odd_["headless"] = raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable)
    registry("busy", kind="sdk-cli"); odd_["sdk"] = raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable)
    registry("working"); odd_["unknown status"] = raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable)
    registry(""); odd_["no status"] = raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable)
    check("17 …a PRESENT row that is no interactive pane (headless, another kind) or whose status the server does not know (a new word, none) is UNKNOWN (Unreadable), never nothing running: the session is there and cannot be looked into", all(odd_.values()), odd_)
    registry("busy", sid=str(_uuid.uuid4())); d_ = "a pane in a turn with no transcript here"
    check("17 …and Unreadable (unknown) for a pane in a turn whose transcript this box does not hold, or whose registry row names no session", raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable) and (registry("busy", sid=""), raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable))[1], d_)
    registry("busy")
    clean_pane(); panes["home-peer"] = "busy"
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    put(1, act=90); put(2, act=90); put(3, act=90)
    tick(subagents=None)
    check("17 a tick that is given no subagent view reads the transcripts itself: items 1 and 2, named in the briefs of two running subagents, are verified; item 3 is named by none and a quiet subagent (90 minutes to 6 hours old) names an item that is not the mover's, so it may be what item 3 is: unknown, not idle",
          [lines(i)[0]["kind"] for i in (1, 2, 3)] == ["audit", "audit", "audit_unknown"], [lines(i) for i in (1, 2, 3)])
finally:
    row_path.unlink(missing_ok=True)

# ================================================================ 18. the row never reads "idle over 1 h" between two lines; the record never goes backwards
clean_pane(); panes["team-back"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
rng18 = random.Random(11)
put(1, mover="team-back", act=90)
t_ = now0; landed = []
while t_ <= now0 + 24 * H:
    at_ = t_ + rng18.uniform(0, 68)                                  # the ten-minute set runs in the first paced round after the tenth minute (up to a minute late) and reads its clock a few seconds late
    if tick(at_): landed.append(at_)
    t_ += 10 * MIN
gaps18 = [b_ - a_ for a_, b_ in zip(landed, landed[1:])]
check("18 on the ten-minute grid with a late round and jitter, the next line lands 50 minutes on and never later than 51 minutes 10 seconds after the last (the true bound is 50 minutes plus the difference of two lateness values, at most 68 seconds; an hour would turn the row red)", len(landed) > 20 and max(gaps18) <= 50 * MIN + 70 and max(gaps18) < 55 * MIN and min(gaps18) >= 45 * MIN, (max(gaps18), min(gaps18), len(landed)))
worst = max(gaps18)
i_worst = gaps18.index(worst)
d18 = rd(1); d18["metadata"]["last_activity"] = {"at": landed[i_worst], "kind": "audit", "what": "audit verified the mover's pane is in a turn"}; (T / "store/a/1.json").write_text(json.dumps(d18))
row18 = parts("a1", landed[i_worst] + worst - 0.5)                    # the row an instant before the next line lands: the longest it ever shows one line's time
check("18 …the row read at that worst landing time (through act_parts and band) is not red: it is amber at most, and carries the audit's time", row18 is not None and 'data-b="bad"' not in row18[0] and 'data-b="bad"' not in row18[1] and LA.band(worst) != LA.BAD and 'data-b="warn"' in row18[1], (worst, row18))
check("18 …and the old gap would have shown it: a line landing an hour and a tick-jitter after the last is red", LA.band(H + 8) == LA.BAD and LA.band(H) == LA.WARN)

# a stamp never moves the record to an earlier time
TIME_ = 1.0e9
ahead = {"status": "open", "metadata": {"last_activity": {"at": now0 + 20 * MIN, "kind": "comment", "what": "comment on #5"}}}
line_ok = {"kind": "audit", "verified": ["the mover's pane is in a turn"], "recorded": []}
check("18 a stored record dated ahead of the clock by less than the skew (a clock stepped back, an event dated just ahead) stays: the audit line at an earlier time does not replace it", HR.stamp(ahead, line_ok, now0) is False and ahead["metadata"]["last_activity"]["kind"] == "comment" and ahead["metadata"]["last_activity"]["at"] == now0 + 20 * MIN, ahead)
far = {"status": "open", "metadata": {"last_activity": {"at": now0 + 5 * H, "kind": "comment", "what": "comment on #5"}}}
check("18 …a record dated further ahead than the skew is no record (a clock that jumped once): the line replaces it, as every signal does", HR.stamp(far, line_ok, now0) is True and far["metadata"]["last_activity"]["kind"] == "audit" and far["metadata"]["last_activity"]["at"] == now0, far)
older = {"status": "open", "metadata": {"last_activity": {"at": now0 - 5 * MIN, "kind": "comment", "what": "comment on #5"}}}
same_t = {"status": "open", "metadata": {"last_activity": {"at": now0, "kind": "comment", "what": "comment on #5"}}}
check("18 an older record is replaced by the line, a record at the very time of the line is kept (strictly later wins), and an idle line or no line changes nothing",
      HR.stamp(older, line_ok, now0) is True and older["metadata"]["last_activity"]["kind"] == "audit" and HR.stamp(same_t, line_ok, now0) is False and same_t["metadata"]["last_activity"]["kind"] == "comment"
      and HR.stamp({"status": "open", "metadata": {}}, {"kind": "audit_idle", "verified": ["x"], "recorded": []}, now0) is False and HR.stamp({"status": "open", "metadata": {}}, None, now0) is False)
clean_pane(); panes["team-back"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, mover="team-back", act=90, last_activity={"at": now0 + 20 * MIN, "kind": "comment", "what": "comment on #5"})
tick()
check("18 through the tick: a line written while the item's record stands 20 minutes ahead is written and the record stays as it was", len(lines(1)) == 1 and lines(1)[0]["kind"] == "audit" and mt(1)["last_activity"] == {"at": now0 + 20 * MIN, "kind": "comment", "what": "comment on #5"}, (lines(1), mt(1).get("last_activity")))
put(2, mover="team-back", act=90); put(1, mover="home-peer2", act=90); panes["home-peer2"] = "busy"
tick(now0 + 2 * H); stamped2 = mt(1)["last_activity"]
tick(now0 + 2 * H - 30 * MIN)                                        # the clock stepped back half an hour: the line is not owed (it is within 45 minutes of the last), and nothing moves the record back
tick(now0 + 2 * H + 3 * H)
check("18 a clock stepped back never moves the record to an earlier time: the stamp of the later line stays through passes at earlier clocks", stamped2["at"] == now0 + 2 * H and mt(1)["last_activity"]["at"] >= stamped2["at"], (stamped2, mt(1).get("last_activity")))

# ================================================================ 19. a subagent tied to no item leaves the mover's items unknown, not idle (and not handed on); a front agent's busy pane still verifies
from stackshot.audit import hand_idle as HI
def handed_on(now_):
    items_ = {f"a{i}": rd(i) for i in range(1, 12) if (T / f"store/a/{i}.json").exists()}
    return [g for g, _r in HI.due_all(items_, now_, lambda who, project: telling.front_keeper(who, project)[0])]
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 2, 3): put(i, act=90)
run_on("home-peer", "Build part D", "Goal: build it in the worktree and open a pull request. Nothing here names an item.")
tick()
check("19 one subagent that names nothing and three items on the mover: all three read unknown (a subagent of the mover is running, not tied to an item), none is idle-marked, none is stamped",
      all(lines(i)[0]["kind"] == "audit_unknown" and lines(i)[0]["text"] == f"Audit {hm(now0)}: a subagent of the mover is running, not tied to an item, nothing verified" and not HR.idle_marked(mt(i)) and "last_activity" not in mt(i) for i in (1, 2, 3)), [lines(i) for i in (1, 2, 3)])
check("19 …none is handed on: the hand-over reads audit_idle alone (the control below is handed on)", handed_on(now0 + 60) == [], handed_on(now0 + 60))
check("19 the unknown line is a line like the others: it is the newest line (the next one is owed 45 minutes on), and the log keeps it as audit_unknown", HR.last_line(mt(1))["kind"] == "audit_unknown" and tick(now0 + 30 * MIN) == [] and "a1" in tick(now0 + 45 * MIN))
# (b) the live case: one subagent tied to the first item, two other items of the mover
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 2, 3): put(i, act=90, work=work("in progress", 20))
run_on("home-peer", f"Build {BID(1)}: the thing")
tick()
check("19 one subagent tied to the first of three items: the first reads verified, the other two idle, are idle-marked and are handed on",
      lines(1)[0]["kind"] == "audit" and all(lines(i)[0]["kind"] == "audit_idle" and HR.idle_marked(mt(i)) for i in (2, 3)) and sorted(handed_on(now0 + 60)) == ["a2", "a3"], ([lines(i) for i in (1, 2, 3)], handed_on(now0 + 60)))
# two subagents, one tied and one naming nothing: an untied item is unknown (it may be what the second builds)
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 2): put(i, act=90)
run_on("home-peer", f"Build {BID(1)}"); run_on("home-peer", "Build part D")
tick()
check("19 two subagents, one tied to the first item and one naming nothing: the first is verified, the second unknown", lines(1)[0]["kind"] == "audit" and lines(2)[0]["kind"] == "audit_unknown", [lines(1), lines(2)])
# a subagent tied to an item of the mover's that is on hold: it is tied to an item, so the mover's other item is idle
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90); put(3, act=90); put(2, act=90, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 9 * H + 4 * H)))
run_on("home-peer", f"Build {BID(2)}")
tick()
check("19 a subagent tied to another item of the mover's (here one on hold) is tied to an item: the two due items read idle, as built", lines(1)[0]["kind"] == "audit_idle" and lines(3)[0]["kind"] == "audit_idle" and lines(2) == [], [lines(1), lines(2), lines(3)])
# front agent: its busy pane still verifies every item, so no stream of idle lines
clean_pane(); panes["home-front"] = "busy"; panes["team-back"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 2, 3): put(i, mover="home-front", act=90)
for i in (4, 5, 6): put(i, mover="team-back", act=90)
tick()
check("19 a front agent with three items on an agent and its pane in a turn: each is verified by the pane (the old phrase, live state only), none is idle; a back agent with three (the control) reads all three idle",
      all(lines(i)[0]["kind"] == "audit" and lines(i)[0]["text"] == f"Audit {hm(now0)}: verified the mover's pane is in a turn" + HR.LIVE_ONLY for i in (1, 2, 3)) and all(lines(i)[0]["kind"] == "audit_idle" for i in (4, 5, 6)), [lines(i) for i in range(1, 7)])
check("19 …the front agent's items are never handed on either way, and the back agent's three are", sorted(handed_on(now0 + 60)) == ["a4", "a5", "a6"], handed_on(now0 + 60))
panes["home-front"] = "idle"
for i in (1, 2, 3): put(i, mover="home-front", act=90)
tick(now0 + 3 * H)
check("19 a front agent whose pane is not in a turn reads idle as before (nothing to verify), and still is not handed on", all(lines(i)[-1]["kind"] == "audit_idle" for i in (1, 2, 3)) and not any(g in handed_on(now0 + 3 * H + 60) for g in ("a1", "a2", "a3")), [lines(i) for i in (1, 2, 3)])
# ================================================================ 20. the tie by description first; the quiet window; an absent row against a present one; a read error kept for the pass; a front test that raises
check("20 the tie reads the DESCRIPTION first: a description that names an item ties to it alone; a brief that only mentions another item ('a follow-up of item 1') does not tie when the description names one; a description that names none lets the brief decide",
      TIE.tied_to({"description": f"Build {BID(2)}", "brief": f"A follow-up of {BID(1)}"}, {"a1": (BID(1), ()), "a2": (BID(2), ())}) == {"a2"}
      and TIE.tied_to({"description": "Build part D", "brief": f"A follow-up of {BID(1)}"}, {"a1": (BID(1), ()), "a2": (BID(2), ())}) == {"a1"}
      and TIE.tied_to({"description": "Build part D", "brief": "nothing here"}, {"a1": (BID(1), ())}) == set()
      and TIE.tied_to({"text": f"Build {BID(2)}"}, {"a2": (BID(2), ())}) == {"a2"}, "pure")
check("20 …and one candidate alone: a description that names it ties, one that names none of the candidates lets the brief decide (the audit offers every item of the mover as a candidate, so a description naming one of them wins over a brief that mentions another)",
      TIE.tied([{"description": f"Build {BID(1)}", "brief": "x"}], BID(1)) is True and TIE.tied([{"description": "Build part D", "brief": f"a follow-up of {BID(1)}"}], BID(1)) is True and TIE.tied([{"description": "Build part D", "brief": "x"}], BID(1)) is False, "single")
check("20 a description that names an item of ANOTHER mover (not a candidate) while the brief names one of this mover's items still ties by the brief: a known limit, pinned (a false verified, never a false idle); a description naming two of the mover's items ties both",
      TIE.tied_to({"description": f"Build {BID(9)}", "brief": f"a follow-up of {BID(1)}"}, {"a1": (BID(1), ()), "a2": (BID(2), ())}) == {"a1"}
      and TIE.tied_to({"description": f"Build {BID(1)} and {BID(2)}", "brief": f"{BID(3)}"}, {"a1": (BID(1), ()), "a2": (BID(2), ()), "a3": (BID(3), ())}) == {"a1", "a2"}, "limit")
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90); put(2, act=90)
SUBS.setdefault("home-peer", []).append({"id": "f1", "description": f"Build {BID(2)}", "brief": f"a follow-up of {BID(1)}", "text": f"Build {BID(2)}\na follow-up of {BID(1)}", "at": now0 - 60})
tick()
check("20 through the audit: a subagent whose description names item 2 and whose brief mentions item 1 verifies item 2, and item 1 reads idle (tied to another item), not verified by a mention",
      lines(2)[0]["kind"] == "audit" and lines(1)[0]["kind"] == "audit_idle", [lines(1), lines(2)])

# the quiet window, end to end through the server's reader: a mover with two items on an agent, the pane busy, the registry row and the transcript folder planted
sess_dir = T / "home/.claude/sessions"
row_path = sess_dir / f"{os.getpid()}.json"
def one_agent(desc, brief, age_s):
    for f_ in (proj / SID / "subagents").glob("agent-q*"): f_.unlink()
    agent("q1", desc, brief, age=age_s)
def kinds20():
    clean_pane(); panes["home-peer"] = "busy"
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    put(1, act=90); put(2, act=90)
    tick(subagents=None)
    return [lines(i)[0]["kind"] for i in (1, 2)], [lines(i)[0]["text"] for i in (1, 2)]
try:
    registry("busy")
    for f_ in (proj / SID / "subagents").glob("agent-*"): f_.unlink()
    got20 = {}
    for label_, age_ in (("89 minutes", 89 * MIN), ("91 minutes", 91 * MIN), ("5 h 59 min", 5 * H + 59 * MIN), ("6 h 1 min", 6 * H + MIN)):
        one_agent("Build part D", "Goal: build it. Nothing here names an item.", age_); got20[label_] = kinds20()[0]
    check("20 an unfinished subagent that names no item, on a busy pane: running at 89 minutes and quiet at 91 minutes and at 5 h 59 min, so the mover's items read UNKNOWN; past the cap (6 h 1 min) it is dropped and the items read idle",
          got20 == {"89 minutes": ["audit_unknown"] * 2, "91 minutes": ["audit_unknown"] * 2, "5 h 59 min": ["audit_unknown"] * 2, "6 h 1 min": ["audit_idle"] * 2}, got20)
    one_agent("Build part D", f"Goal: {BID(1)}", 91 * MIN); k_, t_ = kinds20()
    check("20 a quiet subagent (91 minutes) that IS tied (its brief names item 1, its description none) verifies item 1 and leaves item 2 idle, tied to another item", k_ == ["audit", "audit_idle"], (k_, t_))
    one_agent("Build part D", f"Goal: {BID(1)}", 7 * H); k_, t_ = kinds20()
    check("20 …and past the cap, tied or not, it is dropped: both read idle", k_ == ["audit_idle", "audit_idle"], (k_, t_))
    # an ABSENT registry row is idle as before; a PRESENT one that is no interactive pane reads unknown
    one_agent("Build part D", "nothing", 60)
    row_path.unlink(missing_ok=True); real_idx0 = server._sessions_index; server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = lambda: OTHER_ROW      # a whole fleet index that holds no row of the mover
    try: k_, t_ = kinds20()
    finally: server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = real_idx0
    check("20 a mover with NO registry row on this box (gone, or elsewhere), in a fleet index that was read whole, reads idle as built: nothing is claimed for it, and the orphan and idle hand-overs may act", k_ == ["audit_idle", "audit_idle"], (k_, t_))
    registry("busy", kind="headless"); k_, t_ = kinds20()
    check("20 a PRESENT registry row that is no interactive pane (headless) reads UNKNOWN, never idle: not idle-marked, so not handed on", k_ == ["audit_unknown", "audit_unknown"] and all("could not be read" in x for x in t_) and not any(HR.idle_marked(mt(i)) for i in (1, 2)), (k_, t_))
    registry("working"); k_, t_ = kinds20()
    check("20 a PRESENT row with a status the server does not know reads UNKNOWN too", k_ == ["audit_unknown", "audit_unknown"], (k_, t_))
    # no row on this box: the fleet's heartbeat decides. A session it holds running is on another machine (unknown); one it marks gone, or holds not at all, is gone (idle)
    row_path.unlink(missing_ok=True)
    real_idx = server._sessions_index
    def hb(**rows): return {u_: {"machine": "b", "name": n_, "seen": "2026-01-01T00:00:00Z", **extra_} for u_, (n_, extra_) in rows.items()}
    def tick_with_index(idx_):
        server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = idx_ if callable(idx_) else (lambda: idx_)
        try:
            with _Err(): out_ = kinds20()
        finally: server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = real_idx
        return out_
    live_hb = hb(u1=("home-peer", {})); gone_hb = hb(u1=("home-peer", {"gone": "2026-01-01T00:00:00Z"})); other_hb = hb(u1=("home-stew", {}))
    r_live = raises(lambda: server._mover_subagents("home-peer", live_hb, now0), TIE.Unreadable)
    r_gone = server._mover_subagents("home-peer", gone_hb, now0) == []
    r_none = server._mover_subagents("home-peer", OTHER_ROW, now0) == [] and server._mover_subagents("home-peer", other_hb, now0) == []
    def no_index(): raise OSError("heartbeat unreadable")
    server_idx_none = raises(lambda: (setattr(server, "_sessions_index", no_index), server._mover_subagents("home-peer", None, now0))[1], TIE.Unreadable)
    server._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = real_idx
    check("20 no registry row on this box: the fleet heartbeat holds the session running (on another machine) → Unreadable (unknown); marked gone → none; no row anywhere (or only another session's) → none; the index cannot be read → Unreadable", r_live and r_gone and r_none and server_idx_none, (r_live, r_gone, r_none, server_idx_none))
    k_live = tick_with_index(live_hb); k_gone = tick_with_index(gone_hb); k_none = tick_with_index(OTHER_ROW); k_bad = tick_with_index(no_index)
    check("20 …through the audit: a mover on another machine (live heartbeat row, no local row) reads UNKNOWN on every item, not idle-marked (so never handed on to a second builder); a gone row, no row anywhere → idle as built; an unreadable index → unknown",
          k_live[0] == ["audit_unknown"] * 2 and k_gone[0] == ["audit_idle"] * 2 and k_none[0] == ["audit_idle"] * 2 and k_bad[0] == ["audit_unknown"] * 2 and not any(HR.idle_marked(mt(i)) for i in (1, 2)), (k_live, k_gone, k_none, k_bad))
    k_live = tick_with_index(live_hb)
    check("20 …an unknown line of that kind is not handed on", handed_on(now0 + 60) == [], handed_on(now0 + 60))
    # 21 an EMPTY or PARTIAL fleet index is no proof that the mover is gone: no row in it reads unknown, never idle (fleet.read gives {} for a machine whose sessions.json it cannot read)
    from stackshot.fleet import fleet as FL, sessions_registry as SR
    row_path.unlink(missing_ok=True)
    whole = SR._Index(); whole.update(OTHER_ROW)
    part = SR._Index(); part.update(OTHER_ROW); part.unreadable = ["b"]
    r_empty = raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable) and raises(lambda: server._mover_subagents("home-peer", SR._Index(), now0), TIE.Unreadable)
    r_part = raises(lambda: server._mover_subagents("home-peer", part, now0), TIE.Unreadable)
    r_whole = server._mover_subagents("home-peer", whole, now0) == [] and server._mover_subagents("home-peer", gone_hb, now0) == []
    check("21 an empty fleet index, and one with a machine whose sessions.json could not be read, give a mover with no row UNKNOWN (Unreadable); a whole index that holds no row of it, or marks it gone, still gives none (the session is gone)", r_empty and r_part and r_whole, (r_empty, r_part, r_whole))
    k_empty = tick_with_index({}); k_part = tick_with_index(part); k_whole = tick_with_index(whole)
    check("21 …through the audit: an empty index and a partial one read the mover's items UNKNOWN (kind audit_unknown, nothing stamped, not idle-marked); a whole index without a row of it reads idle as built",
          k_empty[0] == ["audit_unknown"] * 2 and k_part[0] == ["audit_unknown"] * 2 and k_whole[0] == ["audit_idle"] * 2 and not any("last_activity" in mt(i) for i in (1, 2)), (k_empty, k_part, k_whole))
    k_empty = tick_with_index({})
    check("21 …and an unknown line over an empty index is not handed on", not any(HR.idle_marked(mt(i)) for i in (1, 2)) and handed_on(now0 + 60) == [], (k_empty, handed_on(now0 + 60)))
    # the real index: a machine whose sessions.json is torn or absent is listed, and the index says so
    (T / "fleet/b").mkdir(exist_ok=True); (T / "fleet/b/machine.json").write_text(json.dumps({"letter": "b", "fleet": "otherbox", "claude": "1.0.0"}))
    (T / "fleet/b/sessions.json").write_text("{torn")
    got_torn = (FL.sessions_unreadable(), SR._sessions_index().unreadable)
    (T / "fleet/b/sessions.json").unlink(); got_absent = FL.sessions_unreadable()
    (T / "fleet/b/sessions.json").write_text("[]"); got_list = FL.sessions_unreadable()
    (T / "fleet/b/sessions.json").write_text(json.dumps({"sess-b1": {"name": "home-peer", "machine": "b"}})); got_ok = (FL.sessions_unreadable(), SR._sessions_index().unreadable)
    for f_ in (T / "fleet/b").glob("*.json"): f_.unlink()
    (T / "fleet/b").rmdir()
    check("21 the fleet index lists the machines whose sessions.json is torn, absent or not an object (`.unreadable`), and none when every machine's file reads", got_torn == (["b"], ["b"]) and got_absent == ["b"] and got_list == ["b"] and got_ok == ([], []), (got_torn, got_absent, got_list, got_ok))
    # 3 lookup by a session ID beside the name lookups: the mover is named by an id (a transcript id, a heartbeat id), not by its name
    registry("busy", name="home-other"); by_tid = handoff_svc.handoff_pane_row(SID, OTHER_ROW)
    by_name_miss = handoff_svc.handoff_pane_row("home-peer", OTHER_ROW)
    got_id = [x["id"] for x in server._mover_subagents(SID, OTHER_ROW, now0)]
    check("21 a pane's registry row is found by its session id when the mover is named by it (the row's own name is another), and not by a name that is none of its names", by_tid is not None and by_tid[1]["sessionId"] == SID and by_name_miss is None and len(got_id) > 0, (by_tid, by_name_miss, got_id))
    registry("busy", sid="sess-a1", name="home-other")
    by_fixture_id = handoff_svc.handoff_pane_row("sess-a1", OTHER_ROW); other_id = handoff_svc.handoff_pane_row("sess-a2", OTHER_ROW)
    check("21 …a neutral id (sess-a1) matches the row that carries it as its session id, another id (sess-a2) matches nothing", by_fixture_id is not None and by_fixture_id[1]["sessionId"] == "sess-a1" and other_id is None and handoff_svc.handoff_registered("sess-a1", OTHER_ROW) and not handoff_svc.handoff_registered("sess-a2", OTHER_ROW), (by_fixture_id, other_id))
    row_path.unlink(missing_ok=True)
    hb_by_id = lambda **extra: {"sess-a1": {"machine": "b", "name": "home-other", "seen": "2026-01-01T00:00:00Z", **extra}, **OTHER_ROW}
    r_id_live = raises(lambda: server._mover_subagents("sess-a1", hb_by_id(), now0), TIE.Unreadable)
    r_id_gone = server._mover_subagents("sess-a1", hb_by_id(gone="2026-01-01T00:00:00Z"), now0) == []
    r_id_none = server._mover_subagents("sess-a2", hb_by_id(), now0) == []
    check("21 no row on this box, the mover named by a heartbeat id: a live row under that id is on another machine (Unreadable), one marked gone reads none, another id with no row reads none", r_id_live and r_id_gone and r_id_none, (r_id_live, r_id_gone, r_id_none))
    registry("busy")
    registry("busy")
    # a read error is kept for the pass: one read of a mover's transcripts for all its items, again under the lock for none
    registry("busy")
    real_ms, calls20 = server._mover_subagents, []
    def failing(who, idx=None, now=None): calls20.append(who); raise OSError("transcript folder unreadable")
    server._mover_subagents = failing
    try:
        clean_pane(); panes["home-peer"] = "busy"
        for p_ in (T / "store/a").glob("*.json"): p_.unlink()
        for i in (1, 2, 3): put(i, act=90)
        with _Err(): got20e = tick(subagents=None)
    finally: server._mover_subagents = real_ms
    check("20 an unreadable transcript folder is read ONCE for the pass (the exception is cached like a result), however many items the mover has, and every item reads unknown", len(calls20) == 1 and got20e == ["a1", "a2", "a3"] and all(lines(i)[0]["kind"] == "audit_unknown" for i in (1, 2, 3)), (calls20, got20e))
    calls20.clear()
    def counting(who, idx=None, now=None): calls20.append(who); return []
    server._mover_subagents = counting
    try:
        for p_ in (T / "store/a").glob("*.json"): p_.unlink()
        for i in (1, 2, 3): put(i, act=90)
        tick(subagents=None)
    finally: server._mover_subagents = real_ms
    check("20 …and a result that read fine is read once for the pass as well", len(calls20) == 1, calls20)
finally:
    row_path.unlink(missing_ok=True)
    for f_ in (proj / SID / "subagents").glob("agent-*"): f_.unlink()

# a front-agent test that raises reads as front: the busy pane verifies each item and nothing is handed on, never an error out of the audit
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i in (1, 2, 3): put(i, act=90)
env20 = server._silence_env()
class RaisingFront:
    def __getattr__(self, n): return getattr(env20, n)
    def is_front(self, who, project): raise RuntimeError("keeper lookup failed")
    def is_front_or_unread(self, who, project): raise RuntimeError("keeper lookup failed")
with _Err() as e20: got20f = tick(env=RaisingFront())
check("20 a front test that raises reads as front, not as an error out of the pass: three items on a busy pane are each verified by it (the front rule), none idle, and the pass wrote its lines",
      got20f == ["a1", "a2", "a3"] and all(lines(i)[0]["kind"] == "audit" for i in (1, 2, 3)), (got20f, [lines(i) for i in (1, 2, 3)], e20.text[-300:]))

# ================================================================ 22. a role map that cannot be read reads as front, never as a builder
from stackshot.audit import audit_run as AR
reg_path = T / "store/projects.json"; reg_text = reg_path.read_text(encoding="utf-8")
def two_items_busy():
    clean_pane(); panes["team-back"] = "busy"
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    put(1, mover="team-back", act=90); put(2, mover="team-back", act=90)
try:
    sane = (telling.front_keeper("team-back", "projects/alpha"), telling.front_keeper("team-back", "projects/alpha", unread_front=True), telling.front_keeper("home-front", "projects/alpha", unread_front=True)[0])
    two_items_busy(); tick(); k_read = [lines(i)[0]["kind"] for i in (1, 2)]
    reg_path.write_text("{torn", encoding="utf-8")
    torn = (telling.front_keeper("team-back", "projects/alpha"), telling.front_keeper("team-back", "projects/alpha", unread_front=True))
    env_t = server._silence_env()
    torn_env = (env_t.is_front("team-back", "projects/alpha"), env_t.is_front_or_unread("team-back", "projects/alpha"), AR.Env(roles={}).is_front_or_unread("team-back", "projects/alpha"))
    two_items_busy(); tick(); k_torn = [lines(i)[0]["kind"] for i in (1, 2)]; ids_torn = [HR.idle_marked(mt(i)) for i in (1, 2)]
finally:
    reg_path.write_text(reg_text, encoding="utf-8")
check("22 a readable role map answers as before (a background agent is no front agent, the front agent is one), with or without the unread-is-front mode", sane == ((False, ""), (False, ""), True), sane)
check("22 a project registry that cannot be read (its file torn) reads the mover as no front agent by the plain test and as FRONT by the hourly's (`unread_front`, Env.is_front_or_unread); an Env given a role map of its own is read as given",
      torn == ((False, ""), (True, "")) and torn_env == (False, True, False), (torn, torn_env))
check("22 …through the audit: a background agent with two items and a busy pane reads each idle with the registry readable (the pane says nothing of either), and each verified by its pane, none idle-marked, with the registry unreadable",
      k_read == ["audit_idle", "audit_idle"] and k_torn == ["audit", "audit"] and ids_torn == [False, False], (k_read, k_torn, ids_torn))

# ================================================================ 23. a pull request number written alone is the item's own repository's
A_, B_ = ("acme/widgets#5", "other/repo#5")
cand = {"a1": (BID(1), (A_,)), "a2": (BID(2), (B_,))}
t_both = TIE.tied_to({"description": "Build PR 5", "brief": ""}, cand)
t_url_b = TIE.tied_to({"description": "Build https://github.com/other/repo/pull/5", "brief": ""}, cand)
t_full_a = TIE.tied_to({"description": "Build acme/widgets#5", "brief": ""}, cand)
t_url_then_bare = TIE.tied_to({"description": "Build PR 5 (https://github.com/other/repo/pull/5)", "brief": ""}, cand)
t_alone = (TIE.tied_to({"description": "Build PR 5", "brief": ""}, {"a1": (BID(1), (A_,))}), TIE.tied_to({"description": "Build #5", "brief": ""}, {"a1": (BID(1), (A_,)), "a2": (BID(2), ("other/repo#6",))}))
check("23 `PR 5` written alone ties neither of two items anchored to pull request 5 of two repositories; the URL or `owner/repo#n` tells them apart; a bare number with the URL of the other repository's pull request beside it is that one's",
      t_both == set() and t_url_b == {"a2"} and t_full_a == {"a1"} and t_url_then_bare == {"a2"}, (t_both, t_url_b, t_full_a, t_url_then_bare))
check("23 …a bare number still ties the one item anchored to it (and a number the other item does not share), as before",
      t_alone == ({"a1"}, {"a1"}), t_alone)
check("23 …names_item: a number whose pull request the text gives by URL in another repository is not the item's, and `owner/repo#n` written out is, in the item's own repository only",
      not TIE.names_item("PR 160 https://github.com/other/repo/pull/160", BID(9), ["acme/widgets#160"]) and TIE.names_item("PR 160 https://github.com/acme/widgets/pull/160", BID(9), ["acme/widgets#160"])
      and TIE.names_item("see acme/widgets#160", BID(9), ["acme/widgets#160"]) and not TIE.names_item("see other/repo#160", BID(9), ["acme/widgets#160"]) and not TIE.names_item("see acme/widgets#1600", BID(9), ["acme/widgets#160"])
      and not TIE.names_item("PR 160", BID(9), ["acme/widgets#160"], ["acme/widgets#160"]) and TIE.names_item("PR 160 acme/widgets#160", BID(9), ["acme/widgets#160"], ["acme/widgets#160"]))
clean_pane()
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
panes["home-peer2"] = "idle"
put(1, mover="home-peer2", act=90); put(2, mover="home-peer2", act=90)
ANCH["a1"] = [A_]; ANCH["a2"] = [B_]
run_on("home-peer2", "Build PR 5")
tick(); k_amb = [lines(i)[0]["kind"] for i in (1, 2)]
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, mover="home-peer2", act=90); put(2, mover="home-peer2", act=90); SUBS.clear(); run_on("home-peer2", "Build https://github.com/acme/widgets/pull/5")
tick(); k_url = [lines(i)[0]["kind"] for i in (1, 2)]
check("23 …through the audit: a subagent whose brief says `PR 5` while two of the mover's items are anchored to pull request 5 of two repositories leaves both UNKNOWN (not idle, not handed on); with the URL of one of them only that item is verified and the other reads idle",
      k_amb == ["audit_unknown", "audit_unknown"] and k_url == ["audit", "audit_idle"], (k_amb, k_url))

# ================================================================ 25. a subagent flagged finished that is only parked or resumed still runs
# Claude Code writes `finished: true` into a subagent's meta at the end of every turn, also one that ends waiting for a background task of its own; a resume or the task's notice drops it again.
SID3 = str(_uuid.UUID("00000000-0000-4000-8000-0000000000cc"))
sub3 = proj / SID3 / "subagents"; sub3.mkdir(parents=True)
par3 = proj / f"{SID3}.jsonl"
def _res(text, t=None): return {"type": "user", **({"timestamp": iso(t)} if t is not None else {}), "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}}
BGR = lambda tid, t=None: _res(f"Command running in background with ID: {tid}. Output is being written to: /x/{tid}.output. You will be notified when it completes.", t)
BGM = lambda tid: _res(f"Command was moved to the background (ID: {tid}) after running for 180s. You will be notified when it completes.")
BGT = lambda tid: _res(f"Command did not complete within its 120s timeout and was moved to the background (ID: {tid}). Output is being written to: /x/{tid}.output")
MON = lambda tid, life="expires in 30m unless the source ends first; you get one notice at expiry", t=None: _res(f"Monitor started (task {tid}{', ' + life if life else ''}). You will be notified on each event.", t)
NOTE = lambda tid, status="completed": {"type": "attachment", "attachment": {"type": "queued_command", "prompt": f"<task-notification>\n<task-id>{tid}</task-id>\n<output-file>/x/{tid}.output</output-file>\n<status>{status}</status>\n<summary>done</summary>\n</task-notification>"}}
EVT = lambda tid: {"type": "attachment", "attachment": {"type": "queued_command", "prompt": f"<task-notification>\n<task-id>{tid}</task-id>\n<summary>Monitor event: \"w\"</summary>\n<event>one more line</event>\n</task-notification>"}}
STOP = lambda tid: {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "TaskStop", "input": {"task_id": tid}}]}}
def fin(aid, extra=(), age=60, meta_age=600, finished=True, desc=None, brief=None):
    """a subagent of SID3: its transcript (the brief, then `extra` records) written `age` s ago, its meta (flag `finished`) written `meta_age` s ago"""
    mp, tp = sub3 / f"agent-{aid}.meta.json", sub3 / f"agent-{aid}.jsonl"
    m = {"agentType": "general-purpose", "description": desc or f"Review {aid}"}
    if finished is not None: m["finished"] = finished
    mp.write_text(json.dumps(m))
    tp.write_text("\n".join(json.dumps(r) for r in [{"type": "user", "message": {"role": "user", "content": brief or f"Review the change of {aid}"}}, *extra]) + "\n")
    os.utime(tp, (now0 - age, now0 - age)); os.utime(mp, (now0 - meta_age, now0 - meta_age))
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".250Z"
def resume_rec(aid, t, key="resumedAgentId", typ="user", both=False):
    res = {"success": True, "message": "Resuming agent", key: aid, **({"revivedAgentId" if key == "resumedAgentId" else "resumedAgentId": aid} if both else {})}
    return {"type": typ, "timestamp": iso(t), "message": {"role": "user", "content": [{"type": "tool_result", "content": [{"type": "text", "text": json.dumps(res)}]}]}, **({"toolUseResult": res} if typ == "user" else {})}
def parent(*recs, filler=0):
    par3.write_text("\n".join(json.dumps(r) for r in recs) + ("\n" + json.dumps({"type": "assistant", "x": "y" * filler}) if filler else "") + "\n")
def run3(): return {x["id"]: x for x in TIE.running(SID3, [str(T / "transcripts")], now0)}
parent({"type": "assistant", "message": {"role": "assistant", "content": "idle"}})
fin("pend1", [BGR("bg0001")]); fin("pend2", [BGM("bg0002")]); fin("pend3", [MON("mon001"), EVT("mon001"), EVT("mon001")])
fin("ended1", [BGR("bg0003"), NOTE("bg0003")]); fin("ended2", [MON("mon002"), NOTE("mon002")]); fin("ended3", [MON("mon003"), STOP("mon003")]); fin("ended4", [BGR("bg0004"), NOTE("bg0004", "failed")])
fin("half1", [BGR("bg0005"), BGR("bg0006"), NOTE("bg0005")])                                 # one of two tasks ended, the other still waits
fin("none1", [{"type": "assistant", "message": {"role": "assistant", "content": "done"}}])      # finished, nothing pending
fin("old1", [BGR("bg0007")], age=int(TIE.PARKED_S) + 60)                                       # pending, but its transcript is older than the window
fin("old2", [BGR("bg0008")], age=int(TIE.PARKED_S) - 2)
fin("capped2", [BGR("bg0009")], age=int(TIE.QUIET_CAP_S) + 60)
fin("live1", [BGR("bg0010")], finished=None)                                                   # no flag: running as ever
got25 = run3()
check("25 a subagent flagged finished whose own transcript holds a background Bash (started so, or moved there after its timeout) or a Monitor with no ending notice, written within 90 minutes, is running, in the shape of an unfinished one (no `quiet`)",
      all(k in got25 for k in ("pend1", "pend2", "pend3", "old2")) and got25["pend1"] == {"id": "pend1", "description": "Review pend1", "brief": "Review the change of pend1", "text": "Review pend1\nReview the change of pend1", "at": now0 - 60}
      and all("quiet" not in got25[k] for k in ("pend1", "pend2", "pend3", "old2")), sorted(got25))
check("25 …a Monitor's per-event notices end nothing (pend3 has two and still waits), and one of two tasks ended leaves the subagent parked on the other",
      "pend3" in got25 and "half1" in got25, sorted(got25))
check("25 …a task ended by a notice with a status (completed or failed), by a Monitor's end notice or by a TaskStop is no longer pending: the subagent is not running", not any(k in got25 for k in ("ended1", "ended2", "ended3", "ended4")), sorted(got25))
check("25 …finished with nothing pending (and no resume): not running, as before", "none1" not in got25, sorted(got25))
check("25 …a pending task whose subagent wrote nothing for more than 90 minutes is not running (90 minutes less two seconds is), and one past the 6-hour cap is dropped as ever; a subagent with no flag is as before", "old1" not in got25 and "old2" in got25 and "capped2" not in got25 and "live1" in got25, sorted(got25))
check("25 pending_tasks names the ids that wait", TIE.pending_tasks(sub3 / "agent-half1.jsonl") == {"bg0006"} and TIE.pending_tasks(sub3 / "agent-pend3.jsonl") == {"mon001"} and TIE.pending_tasks(sub3 / "agent-ended4.jsonl") == set()
      and TIE.pending_tasks(sub3 / "agent-none1.jsonl") == set() and TIE.pending_tasks(sub3 / "agent-missing.jsonl") == set(), None)
# the parent's resume
for f_ in sub3.glob("agent-*"): f_.unlink()
fin("res1", meta_age=600); fin("res2", meta_age=600); fin("res3", meta_age=600); fin("res4", meta_age=600); fin("res5", meta_age=600); fin("res6", meta_age=600); fin("res7", meta_age=600, age=100 * 60)
parent({"type": "assistant", "message": {"role": "assistant", "content": "x"}},
       resume_rec("res1", now0 - 300),                                                      # newer than the meta's write (600 s ago): resumed since
       resume_rec("res2", now0 - 300, key="revivedAgentId"),                                # the same on Claude Code 2.1.323
       resume_rec("res3", now0 - 900),                                                      # older than the meta's write: it ended after the resume
       resume_rec("res4", now0 - 300, typ="assistant"),                                     # an assistant message that quotes the words resumes nothing
       resume_rec("res7", now0 - 300, both=True),
       resume_rec("other", now0 - 300))                                                     # another subagent's
got25b = run3()
check("25 a subagent flagged finished that the session's transcript resumed (`resumedAgentId`, or `revivedAgentId`) after its meta's last write is running; one resumed before that write, one the session never resumed, one only an assistant record quotes, and a resume of another subagent are not",
      {"res1", "res2", "res7"} <= set(got25b) and not ({"res3", "res4", "res5", "res6"} & set(got25b)), sorted(got25b))
check("25 …the `quiet` rule is unchanged: a resumed one whose transcript is 100 minutes old is running but quiet, a fresh one is not", got25b["res7"].get("quiet") is True and "quiet" not in got25b["res1"], {k: v.get("quiet") for k, v in got25b.items()})
check("25 resumes: the newest resume time of each subagent, as epoch seconds", abs(TIE.resumes(par3)["res1"] - (now0 - 300 + 0.25)) < 0.01 and "res4" not in TIE.resumes(par3) and TIE.resumes(par3 / "missing") == {}, TIE.resumes(par3))
slack25 = {}
for rs_, sec_ in (("res1", 599), ("res2", 600), ("res3", 601), ("res4", 602), ("res5", 603)):          # the meta was written 600 s ago; a record's time carries a quarter of a second
    parent(resume_rec(rs_, now0 - sec_))
    slack25[sec_] = rs_ in run3()
check("25 …a resume dated as the meta's write or within a second before it counts (a clock's grain), one dated more than a second before it does not (the slack is one second, no more, no less)",
      slack25 == {599: True, 600: True, 601: True, 602: False, 603: False}, slack25)
parent(resume_rec("res1", now0 - 300), filler=64 * 1024); saved_tail = TIE.TAIL_BYTES; TIE.TAIL_BYTES = 4096
try: got25d = run3()
finally: TIE.TAIL_BYTES = saved_tail
check("25 …only the tail of the session's transcript is read: a resume further back than TAIL_BYTES from its end is not seen", "res1" not in got25d, sorted(got25d))
# the session's transcript is read only when it is needed, once, and never raises
reads = []; real_rp = TIE.read_parent
TIE.read_parent = lambda tr: (reads.append(tr), real_rp(tr))[1]
def n_reads(*subs):
    for f_ in sub3.glob("agent-*"): f_.unlink()
    for s_ in subs: s_()
    reads.clear(); run3(); return len(reads)
try:
    n25 = (n_reads(), n_reads(lambda: fin("u1", finished=None), lambda: fin("u2", [BGR("bg0021")], finished=None)),
           n_reads(lambda: fin("p1", [BGR("bg0020")]), lambda: fin("p2", [MON("mon020")])),
           n_reads(lambda: fin("f1"), lambda: fin("f2"), lambda: fin("f3")),
           n_reads(lambda: fin("p1", [BGR("bg0020")]), lambda: fin("f1"), lambda: fin("u1", finished=None)),
           n_reads(lambda: fin("f1", age=int(TIE.QUIET_CAP_S) + 60), lambda: fin("p1", [BGR("bg0020")], age=int(TIE.QUIET_CAP_S) + 60)),
           n_reads(lambda: fin("i1", [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None)),
           n_reads(lambda: fin("i1", [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None), lambda: fin("f1")))
    for f_ in sub3.glob("agent-*"): f_.unlink()
    fin("p1", [BGR("bg0020")]); fin("p2", [MON("mon020")]); fin("f1"); fin("f2"); fin("f3")
finally: TIE.read_parent = real_rp
check("25 the session's transcript is read once for a call (never once for each subagent), and only when a finished subagent (parked or not) or an interrupted one needs it: not for no subagent, for subagents with no flag, or for ones past the 6-hour cap",
      n25 == (0, 0, 1, 1, 1, 0, 1, 1), n25)
par3.unlink(); par3.mkdir()                                                                  # a transcript that cannot be read as a file
try:
    got25e = run3()
    check("25 a session transcript that cannot be read: a finished subagent with nothing pending is not running, one parked on a task still is, and nothing raises (unreadable is no reason to list a subagent unreadable)",
          sorted(got25e) == ["p1", "p2"] and not any(x.get("unreadable") for x in got25e.values()), sorted(got25e))
finally: par3.rmdir()
par3.write_text("{not json\n" + '{"type":"user","timestamp":"nope","x":"resumedAgentId\\":\\"f1"}\n' + "\x00\xff" + "\n")
check("25 …nor a transcript of torn lines, a resume with no readable time, or bytes that are no text", sorted(run3()) == ["p1", "p2"], sorted(run3()))
check("25 …a finished subagent whose meta cannot be read is still listed running with no words (unreadable, as before)", (lambda: (fin("bad1"), (sub3 / "agent-bad1.meta.json").write_text("{not json"), "bad1" in run3() and run3()["bad1"].get("unreadable") is True)[2])(), None)
parent({"type": "assistant", "message": {"role": "assistant", "content": "x"}})
# a parked subagent is tied like any other
fin("tie1", [BGR("bg0030")], desc=f"Review {BID(1)}", brief="nothing")
check("25 a parked subagent ties to an item by its description as any other", TIE.tied(list(run3().values()), BID(1)) and not TIE.tied([run3()["tie1"]], BID(2)), None)
# ---- the second round: what the session's transcript says, a start that is only quoted, a Monitor's lifetime, a subagent that was interrupted, a resume that is only quoted
ASSIST = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}
def wipe3():
    for f_ in sub3.glob("agent-*"): f_.unlink()
check("25 the values the rules rest on are pinned (a window, a cap, a slack or a bound changed in the code is seen here)",
      (TIE.RUNNING_S, TIE.QUIET_CAP_S, TIE.PARKED_S, TIE.SKEW_S, TIE.RESUME_SLACK_S, TIE.TAIL_BYTES, TIE.TASK_TAIL_BYTES, TIE.LAST_ROW_BYTES)
      == (5400.0, 21600.0, 5400.0, 300.0, 1.0, 8 * 1024 * 1024, 32 * 1024 * 1024, 16 * 1024), (TIE.RUNNING_S, TIE.QUIET_CAP_S, TIE.PARKED_S, TIE.SKEW_S, TIE.RESUME_SLACK_S, TIE.TAIL_BYTES, TIE.TASK_TAIL_BYTES, TIE.LAST_ROW_BYTES))
wipe3(); parent(ASSIST)
fin("w89", [BGR("bgw089")], age=89 * 60); fin("w91", [BGR("bgw091")], age=91 * 60)
got = run3()
check("25 …the parked window is 90 minutes: a task pending in a transcript written 89 minutes ago is running, one 91 minutes ago is not", "w89" in got and "w91" not in got, sorted(got))

# 1. the end notice that reached only the session's transcript
wipe3()
def PQ(tid, status="completed", event=None, op="enqueue"):
    """a notice as the session's own transcript keeps it: a queue record"""
    body = f"<task-notification>\n<task-id>{tid}</task-id>\n<tool-use-id>x</tool-use-id>\n<output-file>/x/{tid}.output</output-file>\n" + (f"<status>{status}</status>\n" if status else "") + f"<summary>done</summary>\n" + (f"<event>{event}</event>\n" if event else "") + "</task-notification>"
    return {"type": "queue-operation", "operation": op, "timestamp": iso(now0 - 100), "sessionId": "s", "content": body}
PU = lambda tid, status="failed": {"type": "user", "timestamp": iso(now0 - 100), "message": {"role": "user", "content": f"[SYSTEM NOTIFICATION] <task-notification>\n<task-id>{tid}</task-id>\n<status>{status}</status>\n</task-notification>"}}
for i_, mk_ in enumerate((BGR, BGR, MON, BGR, BGR, BGR, MON, MON, BGR, BGR, BGR, BGR, BGT), 1): fin(f"n{i_}", [mk_(f"pn{i_:04d}")])
fin("n6", [BGR("pn0006"), BGR("pn0106")])
parent(ASSIST,
       PQ("pn0001"),                                                                                   # n1: a queue record with a status: ended
       PU("pn0002"),                                                                                   # n2: a user message with a status: ended
       PQ("pn0003", None, "[Monitor expired after 10m with no events delivered. Re-arm it if you still need the watch.]"),    # n3: a Monitor's expiry event: ended
       NOTE("pn0004"),                                                                                 # n4: an attachment: ended
       PQ("pn9999"),                                                                                   # n5: a notice of another task ends nothing
       PQ("pn0006"),                                                                                   # n6: two tasks, one ended: still parked on the other
       PQ("pn0007", None, "one more line"),                                                            # n7: a Monitor's per-event notice ends nothing
       PQ("pn0008", None, "Monitor ended: the source closed"),                                         # n8: ended
       {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "<task-notification>\n<task-id>pn0009</task-id>\n<status>completed</status>\n</task-notification>"}]}},      # n9: quoted in a command's output: nothing
       {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "<task-id>pn0010</task-id><status>completed</status>"}]}},      # n10: an assistant record: nothing
       {"type": "api-request-blob", "message": {"content": [{"type": "text", "text": "<task-notification><task-id>pn0011</task-id><status>completed</status></task-notification>"}]}},      # n11: a request's copy: nothing
       PQ("pn0013", op="remove"))                                                                      # n13: a removed notice is one too
got = run3()
check("25 a finished subagent's task whose end notice only the SESSION's transcript holds (a queue record, a user message, an attachment, a Monitor's expiry or end event) is ended: the subagent is not running",
      not any(k in got for k in ("n1", "n2", "n3", "n4", "n8", "n13")), sorted(got))
check("25 …a notice of another task, a Monitor's per-event notice, a task of two of which one ended, and a notice quoted in a tool result, an assistant record or a request's copy of the conversation end nothing: still running",
      {"n5", "n6", "n7", "n9", "n10", "n11"} <= set(got), sorted(got))
check("25 read_parent: the ids whose end the session was told, and the resumes", TIE.read_parent(par3)[1] == {"pn0001", "pn0002", "pn0003", "pn0004", "pn9999", "pn0006", "pn0008", "pn0013"} and TIE.read_parent(par3 / "missing") == ({}, set()), TIE.read_parent(par3)[1])
parent(PQ("pn0012"), filler=64 * 1024); fin("n12", [BGR("pn0012")]); saved_tail = TIE.TAIL_BYTES
n12_all = "n12" in run3(); TIE.TAIL_BYTES = 4096
try: n12_cut = "n12" in run3()
finally: TIE.TAIL_BYTES = saved_tail
check("25 …only the last TAIL_BYTES of the session's transcript are read for a notice too: one further back is not seen", not n12_all and n12_cut, (n12_all, n12_cut))
par3.unlink(); par3.mkdir()
try: n_unread = {k for k in run3() if k.startswith("n")}
finally: par3.rmdir()
check("25 …a session transcript that cannot be read ends nothing (every task stays pending), and raises nothing", len(n_unread) == 13, sorted(n_unread))
wipe3(); parent(ASSIST)
fin("sub1", [BGR("bgs001")]); (sub3 / "agent-sub1.jsonl").write_text((sub3 / "agent-sub1.jsonl").read_text() + json.dumps(PQ("bgs001")) + "\n")
check("25 a notice in the subagent's own transcript (a queue record too) still ends its task", "sub1" not in run3(), None)

# 2. a start that is only quoted
wipe3(); parent(ASSIST)
UT = lambda c: {"type": "user", "message": {"role": "user", "content": c}}
fin("q1", [_res("12\nCommand running in background with ID: qq0001. Output is being written to: /x")])      # a command printed it after another line: quoted
fin("q2", [UT("a message: Monitor started (task qq0002, expires in 30m unless the source ends first).")])
fin("q3", [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Command running in background with ID: qq0003."}]}}])
fin("q4", [{"type": "api-request-blob", "message": {"content": [{"type": "tool_result", "content": "Command running in background with ID: qq0004."}]}}])
fin("q5", [BGT("qq0005")])                                                                                  # the real form after a timeout
fin("q6", [_res([{"type": "text", "text": "Command running in background with ID: qq0006. Output is being written to: /x"}])])      # a list of text blocks
fin("q7", [_res("see Command was moved to the background (ID: qq0007) in the log")])
fin("q8", [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "echo Command running in background with ID: qq0008"}}]}}])
got = run3()
check("25 a task starts only with a tool result that OPENS with the start text (running in the background, moved there, moved there after its timeout, a Monitor started): text that is only quoted in a result, a message, a request or a command starts none",
      {"q5", "q6"} <= set(got) and not any(k in got for k in ("q1", "q2", "q3", "q4", "q7", "q8")), sorted(got))
check("25 pending_tasks reads the real start forms", TIE.pending_tasks(sub3 / "agent-q5.jsonl") == {"qq0005"} and TIE.pending_tasks(sub3 / "agent-q6.jsonl") == {"qq0006"} and TIE.pending_tasks(sub3 / "agent-q1.jsonl") == set(), None)
saved_tt = TIE.TASK_TAIL_BYTES; fin("tb1", [BGR("tb0001"), {"type": "assistant", "x": "y" * 70000}]); tb_all = "tb1" in run3(); TIE.TASK_TAIL_BYTES = 4096
try: tb_cut = "tb1" in run3()
finally: TIE.TASK_TAIL_BYTES = saved_tt
check("25 …only the last TASK_TAIL_BYTES of the subagent's transcript are read: a start further back is not seen", tb_all and not tb_cut, (tb_all, tb_cut))

# 3. a Monitor's lifetime
wipe3(); parent(ASSIST)
def mon_case(aid, life, start_ago, at_ago=None, **kw):
    fin(aid, [MON(f"mt{aid}", life, t=now0 - start_ago)], age=at_ago if at_ago is not None else start_ago, **kw)
mon_case("m1", "expires in 10m unless the source ends first", 80 * 60, 79 * 60)           # a 10-minute Monitor, read 80 minutes later, the transcript not written since
mon_case("m2", "expires in 30m unless the source ends first", 20 * 60, 19 * 60)
mon_case("m3", "expires in 30m unless the source ends first", 40 * 60)
mon_case("m4", "expires in 10m unless the source ends first", 601, 600)                    # its end is a second less than the slack ahead: still counts
mon_case("m5", "expires in 10m unless the source ends first", 602)                         # past it
mon_case("m6", "expires in 10m unless the source ends first", 3000, 2300)                  # written after its end: the window alone bounds it
mon_case("m7", "expires in 10m unless the source ends first", 3000, 3000 - 600 - 0.25 - 0.5)      # written half a second after its end: not since (the slack)
mon_case("m8", "expires in 10m unless the source ends first", 3000, 3000 - 600 - 0.25 - 1.5)      # written a second and a half after its end: since
fin("m9", [MON("mtm9", None, t=now0 - 80 * 60)], age=79 * 60)                              # a Monitor that gives no lifetime: the window only
fin("m10", [MON("mtm10", "expires in 10m unless the source ends first")], age=79 * 60)      # a record with no time: no lifetime applies
fin("m11", [BGR("mtm11", t=now0 - 80 * 60)], age=79 * 60)                                  # a background Bash has no lifetime
mon_case("m12", "expires in 15m 30s unless the source ends first", 20 * 60, 19 * 60)      # 930 s: ended
mon_case("m13", "expires in 15m 30s unless the source ends first", 10 * 60, 9 * 60)       # alive
mon_case("m14", "expires in 45s unless the source ends first", 5 * 60)                     # ended
mon_case("m15", "expires in 1h unless the source ends first", 30 * 60, 29 * 60)           # alive
mon_case("m16", "expires in 1h 5m unless the source ends first", 70 * 60, 69 * 60)       # 65 minutes: ended
mon_case("m17", "timeout 900000ms", 20 * 60, 19 * 60)                                      # the other wording: ended
mon_case("m18", "timeout 900000ms", 10 * 60, 9 * 60)
mon_case("m20", "expires in 15m 30s unless the source ends first", 915, 900)                  # 930 s, 915 s gone: alive (the seconds count)
mon_case("m21", "expires in 45s unless the source ends first", 30)                         # alive
mon_case("m19", "expires in 10m unless the source ends first", 80 * 60, 79 * 60, finished=None)      # no flag: this reads the finished ones only
got = run3()
check("25 a Monitor whose start plus its lifetime is past, with no write since, has ended: a 10-minute Monitor read 80 minutes later is not running, a 30-minute one 40 minutes later neither, one still within its lifetime is",
      "m1" not in got and "m3" not in got and "m2" in got, sorted(got))
check("25 …the slack is a second: a Monitor whose end is less than a second ahead of the clock counts, one past it does not; a write after its end (more than the slack) leaves the window alone to bound it, one within the slack does not",
      "m4" in got and "m5" not in got and "m6" in got and "m7" not in got and "m8" in got, sorted(got))
check("25 …a Monitor with no lifetime, a start record with no time and a background Bash have none to end: the 90-minute window alone bounds them", {"m9", "m10", "m11"} <= set(got), sorted(got))
check("25 …the lifetime is read in every wording the start text takes (`15m 30s`, `45s`, `1h`, `1h 5m`, `timeout 900000ms`)",
      "m12" not in got and "m13" in got and "m14" not in got and "m15" in got and "m20" in got and "m21" in got and "m16" not in got and "m17" not in got and "m18" in got, sorted(got))
check("25 …a subagent with no flag is untouched by a Monitor's lifetime", "m19" in got, sorted(got))
check("25 pending_tasks: the lifetime applies only when it is given the clock", TIE.pending_tasks(sub3 / "agent-m1.jsonl") == {"mtm1"} and TIE.pending_tasks(sub3 / "agent-m1.jsonl", now0) == set() and TIE.pending_tasks(sub3 / "agent-m2.jsonl", now0) == {"mtm2"}, None)

# 4. a subagent with no flag whose last row is an interruption
wipe3()
INT = lambda txt="[Request interrupted by user]": {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": txt}]}}
fin("i1", [ASSIST, INT()], finished=None); fin("i2", [ASSIST, INT("[Request interrupted by user for tool use]")], finished=None)
fin("i3", [INT(), ASSIST], finished=None)                                                   # not the last row
fin("i4", [ASSIST, INT("do not [Request interrupted by user] again")], finished=None)      # a row that says more
fin("i5", [ASSIST, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None)
fin("i6", [INT()], finished=None); fin("i7", [INT()], finished=None); fin("i12", [INT()], finished=None); fin("i13", [INT()], finished=None)
fin("i8", [INT()], finished=None, age=100 * 60); fin("i9", [ASSIST], finished=None, age=100 * 60)
fin("i11", [ASSIST, UT("[Request interrupted by user]")], finished=None)                   # the text as a string
fin("i14", [ASSIST, INT()], finished=True, meta_age=600)                                    # flagged finished: the rule of a finished one
parent(ASSIST, resume_rec("i6", now0 - 30), resume_rec("i7", now0 - 120), resume_rec("i12", now0 - 61), resume_rec("i13", now0 - 63))
got = run3()
check("25 a subagent with no flag whose last row is `[Request interrupted by user]` (or `... for tool use]`) is dead, not quiet: it is not running, even written a minute ago; one whose interruption is not its last row, or that says more, or is an assistant's, is running as ever",
      not any(k in got for k in ("i1", "i2", "i8", "i11")) and {"i3", "i4", "i5", "i9"} <= set(got), sorted(got))
check("25 …unless the session's transcript holds a resume of it newer than its last row (a second of slack): then it is running; an older resume is none", "i6" in got and "i7" not in got and "i12" in got and "i13" not in got, sorted(got))
check("25 …a plain unflagged one 100 minutes old stays running but quiet; a finished one that was interrupted follows the rule of the finished", got["i9"].get("quiet") is True and "i14" not in got, sorted(got))
check("25 interrupted: the last row only, and nothing raises", TIE.interrupted(sub3 / "agent-i1.jsonl") and TIE.interrupted(sub3 / "agent-i2.jsonl") and TIE.interrupted(sub3 / "agent-i11.jsonl") and not any(TIE.interrupted(sub3 / f"agent-{k}.jsonl") for k in ("i3", "i4", "i5", "i9")) and not TIE.interrupted(sub3 / "agent-none.jsonl"), None)
saved_lr = TIE.LAST_ROW_BYTES; TIE.LAST_ROW_BYTES = 40
try: cut_i = TIE.interrupted(sub3 / "agent-i1.jsonl")
finally: TIE.LAST_ROW_BYTES = saved_lr
check("25 …a last row longer than LAST_ROW_BYTES is none", cut_i is False, cut_i)

# 5. a resume that is only quoted
wipe3()
for k_ in ("rq1", "rq2", "rq3", "rq4", "rq5", "rq6", "rq7", "rq8"): fin(k_, meta_age=600)
RQ = lambda r: {**r, "timestamp": iso(now0 - 300)}
parent(ASSIST,
       RQ({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": json.dumps({"resumedAgentId": "rq1"})}]}}),                       # quoted in a tool result: no top-level key
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"result": {"resumedAgentId": "rq2"}}}),                                          # not a top-level key
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": "resumedAgentId\": \"rq3\""}),                                                    # a string
       RQ({"type": "api-request-blob", "message": {"content": [{"type": "text", "text": json.dumps({"resumedAgentId": "rq4"})}]}, "toolUseResult": {"resumedAgentId": "rq4"}}),   # not a user record
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": "rq5", "revivedAgentId": "rq5", "success": True}}),         # both keys, one id: the real record
       RQ({"type": "user", "message": {"role": "user", "content": "typed: \"resumedAgentId\": \"rq6\""}}),                                                                   # a message that quotes it
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": 7, "revivedAgentId": ""}}),
       {"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": "rq8"}})                                                                  # a resume with no time says nothing and spoils no other
got = run3()
check("25 a resume is the key `resumedAgentId` (or `revivedAgentId`) at the top level of a user record's `toolUseResult`: one quoted inside a tool result, nested deeper, in a string, in a request's copy or in a typed message is none; both keys of one record count once",
      "rq5" in got and not any(k in got for k in ("rq1", "rq2", "rq3", "rq4", "rq6", "rq7", "rq8")), sorted(got))
check("25 …resumes: both keys on the one record, the time of the record", set(TIE.resumes(par3)) == {"rq5"} and abs(TIE.resumes(par3)["rq5"] - (now0 - 300 + 0.25)) < 0.01, TIE.resumes(par3))
wipe3(); parent(ASSIST)
for f_ in sub3.glob("agent-*"): f_.unlink()

clean_pane()

# 6. the review's follow-ups: a record is cut at a newline only, a Monitor that lives hours, the parked window to the second
wipe3()
SEP = "\u2028"      # JSON leaves it raw inside a string (json.dumps with ensure_ascii off, as Claude Code writes it); `str.splitlines` would cut a record there
def fin_raw(aid, extra=(), age=60, meta_age=600):
    mp, tp = sub3 / f"agent-{aid}.meta.json", sub3 / f"agent-{aid}.jsonl"
    mp.write_text(json.dumps({"agentType": "general-purpose", "description": f"Review {aid}", "finished": True}))
    tp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [{"type": "user", "message": {"role": "user", "content": f"Review the change of {aid}"}}, *extra]) + "\n", encoding="utf-8")
    os.utime(tp, (now0 - age, now0 - age)); os.utime(mp, (now0 - meta_age, now0 - meta_age))
fin_raw("u1", [_res(f"Command running in background with ID: bgu001. Output is being written to: /x/bgu001.output.{SEP}You will be notified when it completes.")])
fin_raw("u2", [BGR("bgu002")])
fin_raw("u3", [BGR("bgu003")])
par3.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [ASSIST,
      {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(now0 - 100), "content": f"<task-notification>\n<task-id>bgu002</task-id>\n<status>completed</status>\n<summary>done{SEP}at last</summary>\n</task-notification>"},
      {"type": "user", "timestamp": iso(now0 - 100), "message": {"role": "user", "content": f"a message{SEP}that mentions <task-id>bgu003</task-id> and no status"}}]) + "\n", encoding="utf-8")
got = run3()
check("25 a transcript record is cut at a newline and nowhere else: a task start whose result holds a raw U+2028 is still seen (pending_tasks, and the subagent parked on it runs), and an end notice that holds one still ends its task (read_parent), where a cut record is torn and says nothing",
      TIE.pending_tasks(sub3 / "agent-u1.jsonl") == {"bgu001"} and TIE.read_parent(par3)[1] == {"bgu002"} and "u1" in got and "u2" not in got and "u3" in got, (TIE.pending_tasks(sub3 / "agent-u1.jsonl"), TIE.read_parent(par3)[1], sorted(got)))
wipe3(); parent(ASSIST)
mon_case("h1", "expires in 1h unless the source ends first", 61 * 60)                         # an hour-only lifetime: 61 minutes on it has ended
mon_case("h2", "expires in 1h unless the source ends first", 59 * 60)                         # 59 minutes on it is alive
mon_case("h3", "expires in 1h 30s unless the source ends first", 3600 + 30 + 2)                # hours and seconds: ended
mon_case("h4", "expires in 1h 30s unless the source ends first", 3600 + 25)                    # …alive
mon_case("h5", "expires in 2h unless the source ends first", 80 * 60)                          # a 2-hour Monitor 80 minutes on is alive
mon_case("h6", "expires in 1h unless the source ends first", 3600 + 1, finished=None)          # no flag: not this rule's
got = run3()
check("25 a Monitor whose lifetime is in hours: `expires in 1h` has ended 61 minutes on and lives at 59, `1h 30s` counts its seconds, `2h` lives at 80 minutes, a subagent with no flag is not read by it",
      "h1" not in got and "h2" in got and "h3" not in got and "h4" in got and "h5" in got and "h6" in got and TIE._life("Monitor started (task x, expires in 2h unless the source ends first)") == 7200.0, sorted(got))
wipe3(); parent(ASSIST)
fin("b0", [BGR("bgb000")], age=int(TIE.PARKED_S)); fin("b1", [BGR("bgb001")], age=int(TIE.PARKED_S) + 1); fin("b2", [BGR("bgb002")], age=int(TIE.PARKED_S) - 1)
got = run3()
check("25 the parked window to the second: a pending task in a transcript written exactly 90 minutes ago (5400 seconds) still counts, one second more does not, one second less does (a task that never reported is believed for that long and no longer)", "b0" in got and "b1" not in got and "b2" in got, sorted(got))

# ================================================================ 24. a mover's status write with new text is the hourly update
from stackshot.service import writes as WR24
WR24.time = CLK      # the save stamps from the server's own (fake) clock
def tagged(text, state="in progress", ts=0.0, who="home-peer"):
    """The mover's one open step, with a status line (its tag) when `text` is given."""
    st = {"text": f"{who}: do the thing", "status": "open", "by": who, "at": 0}
    if text: st["tag"] = {"text": text, "state": state, "ts": ts}
    return st
def save24(i, at, mutate, writer="home-peer", **kw):
    """A real save of item `i` by `writer` at the fake time `at`, `mutate` changing the loaded item's metadata first."""
    d_ = server._load(f"a{i}"); mutate(d_["metadata"]); CLK.t = at
    try: WR24.save(f"a{i}", d_, writer=writer, **kw)
    finally: CLK.t = None
def status_of(i, text, state="in progress", ts=0.0, who="home-peer"): return lambda m: m.update(steps=[tagged(text, state, ts, who)])
def rec24(i): return mt(i).get("last_activity")
clean_pane()
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
for i_ in (1, 2, 3, 4, 5): put(i_, mover="home-peer", act=90, steps=[tagged(None)])
T0 = now0 - 30 * MIN
save24(1, T0, status_of(1, "building the fix", ts=T0))
check("24 the mover's first status line is an update: the record is kind update at the save's time, the words the text itself; the activity clock moved too",
      rec24(1) == {"at": T0, "kind": "update", "what": "building the fix"} and rd(1)["activity"] == T0, (rec24(1), rd(1).get("activity")))
a24 = parts("a1", T0 + 2 * MIN)
check("24 …the On agent row reads it as an audit line's: active, the age <1m, `Last: building the fix at hh:mm`", a24 is not None and 'data-b="ok"' in a24[1] and ">active<" in a24[1] and last_words(a24[1]) == f"Last: building the fix at {hm(T0)}", a24)
save24(1, T0 + 10 * MIN, status_of(1, "tests pass, opening the PR", ts=T0 + 10 * MIN))
check("24 a second, different text is the newer update", rec24(1) == {"at": T0 + 10 * MIN, "kind": "update", "what": "tests pass, opening the PR"}, rec24(1))
save24(1, T0 + 20 * MIN, status_of(1, "  TESTS pass,   opening the PR ", ts=T0 + 10 * MIN))
check("24 the same text again (case and spacing aside) is no update: the record keeps its time, and the save still moved the activity clock", rec24(1) == {"at": T0 + 10 * MIN, "kind": "update", "what": "tests pass, opening the PR"} and rd(1)["activity"] == T0 + 20 * MIN, (rec24(1), rd(1).get("activity")))
save24(1, T0 + 22 * MIN, lambda m: m.update(steps=[tagged("tests pass, opening the PR", "done", T0 + 22 * MIN)]))
check("24 …nor is the same text moved to another state: only the words count", rec24(1)["at"] == T0 + 10 * MIN, rec24(1))
save24(1, T0 + 24 * MIN, lambda m: m.update(steps=[tagged(None)]))
check("24 …nor a cleared status line", rec24(1)["at"] == T0 + 10 * MIN, rec24(1))
# a write by anyone but the mover
save24(2, T0, status_of(2, "building the fix", ts=T0), writer="home-front")
save24(2, T0 + MIN, status_of(2, "somebody else's words", ts=T0 + MIN), writer="home-peer2")
save24(2, T0 + 2 * MIN, status_of(2, "the owner's words", ts=T0 + 2 * MIN), writer="", author=("Oliver", "board"))
save24(2, T0 + 3 * MIN, status_of(2, "a bookkeeping save", ts=T0 + 3 * MIN), writer="")
save24(2, T0 + 4 * MIN, status_of(2, "the audit's own write", ts=T0 + 4 * MIN), writer=server.NAME)
check("24 a status written by someone who is not the item's mover (a front agent, another session, the owner's answer, the server's own save, the audit's writer) is no update: the item has no record", rec24(2) is None, rec24(2))
save24(3, T0, status_of(3, "by the session id", ts=T0), writer=U["home-peer"])
check("24 the mover writing under its session id (not its name) is the mover", rec24(3) == {"at": T0, "kind": "update", "what": "by the session id"}, rec24(3))
save24(4, T0, lambda m: m.update(steps=[tagged("building the fix", ts=T0), {"text": "home-peer: second", "status": "open", "by": "home-peer", "at": 0}]), writer="home-peer")
save24(4, T0 + 5 * MIN, lambda m: m.update(steps=[{**tagged("building the fix", ts=T0), "text": "home-peer: do the thing, reworded"}, {"text": "home-peer: second", "status": "open", "by": "home-peer", "at": 0}]), writer="home-peer")
check("24 a step reworded with its status line kept is no update (the text is one the session already had)", rec24(4) == {"at": T0, "kind": "update", "what": "building the fix"}, rec24(4))
# the audit's own line still stamps, and the newest wins
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()      # the mover's one item on an agent, so its busy pane verifies it
put(5, mover="home-peer", act=90, steps=[tagged(None)])
save24(5, now0 - 70 * MIN, status_of(5, "an hour ago", ts=now0 - 70 * MIN))
d5 = rd(5); d5["activity"] = now0 - 90 * MIN; wr5 = (T / "store/a/5.json"); wr5.write_text(json.dumps(d5))      # the hour's silence is the item's, whatever the save above moved
got24 = tick()
check("24 the audit's own line still stamps (kind audit, its words) over an older update, and the update's own text is no longer the record", got24 == ["a5"] and rec24(5) == {"at": now0, "kind": "audit", "what": "audit verified the mover's pane is in a turn"} and lines(5)[0]["kind"] == "audit", (got24, rec24(5), lines(5)))
save24(5, now0 + 5 * MIN, status_of(5, "back at it", ts=now0 + 5 * MIN))
check("24 …and a later mover's update is newer than the audit line: newest wins both ways", rec24(5) == {"at": now0 + 5 * MIN, "kind": "update", "what": "back at it"}, rec24(5))
# the hourly clock: an update resets it as the audit line does
clean_pane(); panes["home-peer"] = "idle"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(6, mover="home-peer", act=90, steps=[tagged(None)])
save24(6, now0 - 5 * MIN, status_of(6, "still going", ts=now0 - 5 * MIN))
check("24 an item whose mover wrote new text 5 minutes ago is not owed a line (the update is the hourly update), the row reads its words and an age under an hour",
      tick() == [] and lines(6) == [] and last_words(parts("a6", now0)[1]) == f"Last: still going at {hm(now0 - 5 * MIN)}" and 'data-b="ok"' in parts("a6", now0)[1], parts("a6", now0))
check("24 …an hour after the write (56 minutes on), when the mover has written nothing more, the audit's line is owed again (an idle one: nothing verified, the update stays the record)",
      tick(now0 + 56 * MIN) == ["a6"] and lines(6)[0]["kind"] == "audit_idle" and rec24(6)["kind"] == "update", (lines(6), rec24(6)))
clean_pane()
# --- what the first review found: a status text reused on a later stage, and each way a write is no update
clean_pane()
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
S1 = {"text": "home-peer: stage 1", "status": "done", "by": "home-peer", "at": 1, "tag": {"text": "waiting for CI", "state": "done", "ts": 1.0}}
S2 = {"text": "home-peer: stage 2", "status": "open", "by": "home-peer", "at": 0}
put(7, mover="home-peer", act=90, steps=[S1, S2], next="home-peer: stage 2")
save24(7, T0, lambda m: m.update(steps=[S1, {**S2, "tag": {"text": "waiting for CI", "state": "in progress", "ts": T0}}]))
check("24 a status text the mover used on an earlier stage is a first status on a later step that already existed with none: it is an update", rec24(7) == {"at": T0, "kind": "update", "what": "waiting for CI"}, rec24(7))
# a mover that is the audit's own name: the audit's writes are never an update
put(8, mover=server.NAME, act=90, steps=[tagged(None, who=server.NAME)], next=f"{server.NAME}: do the thing", needs=[server.NAME])
save24(8, T0, status_of(8, "the audit's own words", ts=T0, who=server.NAME), writer=server.NAME)
check("24 the audit's own writer is no mover for this: the audit's name as the item's mover and as the writer stamps no update (the audit's writes never count as work)", rec24(8) is None, rec24(8))
# a mover's write filed under another kind of activity, or under none the clock counts
put(9, mover="home-peer", act=90, steps=[tagged(None)])
for n_, kind_ in enumerate((ACT.MESSAGE, ACT.EVENT), 1): save24(9, T0 + n_ * MIN, status_of(9, f"filed as {kind_}", ts=T0), activity=kind_)
check("24 a mover's save filed as a message or an event of an anchor (kinds the activity clock counts) is no status write by the mover: no update", rec24(9) is None, rec24(9))
for n_, kind_ in enumerate((ACT.BOOKKEEPING, ACT.MIGRATION, ACT.CONFIRM), 3): save24(9, T0 + n_ * MIN, status_of(9, f"filed as {kind_}", ts=T0), activity=kind_)
check("24 …nor is a save of the server's own kind (bookkeeping, a migration, a confirm) written under the mover's name: it is no real write about the work", rec24(9) is None, rec24(9))
save24(9, T0 + 9 * MIN, status_of(9, "a plain write", ts=T0 + 9 * MIN))
check("24 …while the same mover's plain write (no kind given) does", rec24(9) == {"at": T0 + 9 * MIN, "kind": "update", "what": "a plain write"}, rec24(9))
# the owner is the mover (the item waits on his decision): a session's status write is no update
put(10, mover="home-peer", act=90, steps=[tagged(None)], needs=["decision"], state="your-call")
save24(10, T0, status_of(10, "building while he decides", ts=T0))
check("24 a session writing a status while the owner is the item's mover (it waits on his decision) is no update, whatever mover the item stores", (rec24(10) or {}).get("kind") != "update" and server._model.is_owner(server._model.derive(rd(10)).mover), (rec24(10), server._model.derive(rd(10)).mover))
put(16, mover="home-peer", act=90, steps=[tagged(None)]); d16 = rd(16); d16["metadata"].pop("mover"); (T / "store/a/16.json").write_text(json.dumps(d16))      # no stored mover: the model reads it from the needs
save24(16, T0, status_of(16, "mover read from the needs", ts=T0), ctx=WR24.QUIET)
put(17, mover="Oliver", act=90, steps=[tagged(None, who="Oliver")], next="Oliver: do the thing", needs=["decision"], state="your-call")
save24(17, T0, status_of(17, "a session named as the owner", ts=T0, who="Oliver"), writer="Oliver")
check("24 the mover is the model's, not the stored field alone (an item with no stored mover whose needs name the session: its write is an update), and a session that carries the owner's name while he is the mover is not him: no update",
      rec24(16) == {"at": T0, "kind": "update", "what": "mover read from the needs"} and rec24(17) is None and server._model.is_owner(server._model.derive(rd(17)).mover), (rec24(16), rec24(17), mt(16).get("mover")))
# a mover known by another name of the same session: the registry's alias, and its id
from stackshot.fleet import sessions_registry as SR24
sala24 = T / "sala/a"; sala24.mkdir(parents=True)
PID = "00000000-0000-4000-8000-0000000000aa"
(sala24 / "session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {PID: {"id": PID, "name": "home-peer-new", "aliases": ["home-peer-old"], "project": None, "project_key": None,
        "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": "home-peer-new", "cwd": "/srv/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None, "transcripts": []}}}))
cl24 = server._cfg.CFG.setdefault("client", {}); had24 = cl24.get("session_links"); cl24["session_links"] = str(T / "sala"); SR24.reset()
try:
    put(11, mover="home-peer-old", act=90, steps=[tagged(None, who="home-peer-old")], next="home-peer-old: do the thing", needs=["home-peer-old"])
    save24(11, T0, status_of(11, "under its new name", ts=T0, who="home-peer-old"), writer="home-peer-new")
    a24_ = rec24(11)
    put(12, mover=PID, act=90, steps=[tagged(None, who=PID)], next=f"{PID}: do the thing", needs=[PID])
    save24(12, T0, status_of(12, "by its name, stored as its id", ts=T0, who=PID), writer="home-peer-new")
    b24_ = rec24(12)
    put(13, mover="home-peer-old", act=90, steps=[tagged(None, who="home-peer-old")], next="home-peer-old: do the thing", needs=["home-peer-old"])
    save24(13, T0, status_of(13, "somebody else", ts=T0, who="home-peer-old"), writer="home-peer2")
    c24_ = rec24(13)
finally:
    if had24 is None: cl24.pop("session_links", None)
    else: cl24["session_links"] = had24
    SR24.reset()
check("24 a mover stored under an old name (the registry's alias) is the mover when its current name writes, and one stored as its permanent id likewise; another session is still not",
      a24_ == {"at": T0, "kind": "update", "what": "under its new name"} and b24_ == {"at": T0, "kind": "update", "what": "by its name, stored as its id"} and c24_ is None, (a24_, b24_, c24_))
# an odd earlier version or item never takes the step, state or merge stamp of the same save with it
d24 = server._load("a7"); d24["metadata"]["steps"] = "not a list"; CLK.t = T0 + MIN
try: WR24.save("a7", d24, writer="home-peer")
finally: CLK.t = None
bad_before = server._load("a7"); bad_before["metadata"] = ["torn"]
err24 = _Err()
with err24: ups24 = WR24._update_signals(rd(7), bad_before, "home-peer", T0), WR24._update_signals({"id": "x", "metadata": None}, None, "home-peer", T0), WR24._update_signals({"id": "x"}, {"metadata": 3}, "home-peer", T0)
check("24 an earlier version or item that is not what it should be gives no update and never raises out of the save's stamp", ups24 == ([], [], []), (ups24, err24.text))
def tripped(*a, **k): raise RuntimeError("fleet unreadable")
mv24 = WR24._is_mover; WR24._is_mover = tripped
try:
    put(14, mover="home-peer", act=90, steps=[tagged(None)]); d14 = server._load("a14"); d14["metadata"]["state"] = "verifying"; d14["metadata"]["steps"] = [tagged("x", ts=T0)]; CLK.t = T0
    with _Err() as e14: WR24.save("a14", d14, writer="home-peer")
finally: WR24._is_mover = mv24; CLK.t = None
check("24 a mover test that fails costs only the update: the save is written, the state change of the same save is still stamped, and the failure is on stderr", rec24(14) is not None and rec24(14)["kind"] == "state_change" and "update not recorded" in e14.text, (rec24(14), e14.text))
calls24 = []; mv24 = WR24._is_mover; WR24._is_mover = lambda *a, **k: (calls24.append(1), mv24(*a, **k))[1]
try:
    put(15, mover="home-peer", act=90, steps=[tagged("same words", ts=T0)])
    save24(15, T0 + MIN, lambda m: m.update(note="no status change here")); save24(15, T0 + 2 * MIN, status_of(15, "same words", ts=T0)); n_plain = len(calls24)
    save24(15, T0 + 3 * MIN, status_of(15, "new words", ts=T0 + 3 * MIN)); n_new = len(calls24)
finally: WR24._is_mover = mv24
check("24 the mover test (it reads the fleet's sessions) is asked only when a save carries new status text: none for a save with no status change or the same text, one for a new text", (n_plain, n_new) == (0, 1), (n_plain, n_new))

# ================================================================ 26. the first line is owed after 45 minutes without activity, so it lands inside the hour
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
check("26 the constants, by value: the first line waits 2700 seconds (`EVERY`), the gap between two lines is 2700 seconds (`FAST_GAP`), the hour (`HOUR`) is 3600, and the slow stretch is as it was (24 hours, then one every 6 hours less 5 minutes of slack)",
      HR.EVERY == 2700.0 and HR.FAST_GAP == 2700.0 and HR.HOUR == 3600.0 and HR.LONG_AFTER == 86400.0 and HR.SLOW_EVERY == 21600.0 and HR.SLACK == 300.0, (HR.EVERY, HR.FAST_GAP, HR.HOUR, HR.LONG_AFTER, HR.SLOW_EVERY, HR.SLACK))
put(1, act=30); put(2, act=44); put(3, act=44.9); put(4, act=46); put(5, act=45)
put(12, mover="home-peer2", act=46); panes["home-peer2"] = "busy"      # a mover with this one item and a pane in a turn: its first line verifies
got26 = tick()
check("26 no line is owed while activity is recent: 30 minutes, 44 minutes and 44 minutes 54 seconds owe nothing; 45 minutes (the limit) and 46 minutes owe their first line", got26 == ["a4", "a5", "a12"] and lines(1) == [] and lines(2) == [] and lines(3) == [], (got26, lines(1), lines(2), lines(3)))
check("26 …the first line is the audit's own write and a verified one stamps the item's last activity (kind `audit`, at the line's time), as the later lines do",
      lines(12)[0]["kind"] == "audit" and LA.read(rd(12)) is not None and LA.read(rd(12))["kind"] == "audit" and LA.read(rd(12))["at"] == now0 and SL.clock(rd(12), "home-peer2") == now0 - 46 * MIN, (lines(12), LA.read(rd(12)), SL.clock(rd(12), "home-peer2")))
check("26 …and the row of that item, read an hour after its last real activity (14 minutes after the line), carries the audit's time and words and is not red: with no first line until then it would read \"idle over 1 h\"",
      (lambda r: r is not None and 'data-b="bad"' not in r[0] and 'data-b="bad"' not in r[1] and 'data-b="ok"' in r[0] and "audit verified" in r[1])(parts("a12", now0 + 14 * MIN)), parts("a12", now0 + 14 * MIN))
# the cadence after the first line is the one it was
put(6, act=46); tick()
c1, c2, c3 = tick(now0 + 10 * MIN), tick(now0 + 44 * MIN + 59), tick(now0 + 45 * MIN)
check("26 after the first line the gap is the same 45 minutes: nothing 10 minutes and 44 minutes 59 seconds after it, the next line at 45", "a6" not in c1 and "a6" not in c2 and "a6" in c3 and [e["at"] for e in lines(6)] == [now0, now0 + 45 * MIN], (c1, c2, c3, lines(6)))
# the slow stretch is as it was: the fast gap until 24 hours of silence, then 5 hours 55 minutes
put(7, act=23 * 60); tick()
d1, d2 = tick(now0 + 44 * MIN + 59), tick(now0 + 45 * MIN)          # 23 hours 45 minutes of silence at the second line: still the fast gap
d3, d4 = tick(now0 + 45 * MIN + 45 * MIN), tick(now0 + 45 * MIN + 5 * H + 54 * MIN + 59)      # past 24 hours: a line only every 6 hours less the slack
d5 = tick(now0 + 45 * MIN + 5 * H + 55 * MIN)
check("26 the fast stretch lasts to 24 hours of silence (a first line at 23 hours, the next 45 minutes on) and then the lines thin out: nothing 45 minutes later and 5 hours 54 minutes 59 seconds after the line, the next at 5 hours 55 minutes",
      "a7" not in d1 and "a7" in d2 and "a7" not in d3 and "a7" not in d4 and "a7" in d5 and [e["at"] for e in lines(7)] == [now0, now0 + 45 * MIN, now0 + 45 * MIN + 5 * H + 55 * MIN], (d1, d2, d3, d4, d5, [e["at"] for e in lines(7)]))
put(8, act=25 * 60); tick(); e1, e2 = tick(now0 + 5 * H + 54 * MIN + 59), tick(now0 + 5 * H + 55 * MIN)
check("26 an item silent for 25 hours gets its first line at once and the next after 5 hours 55 minutes, not 45 minutes", "a8" not in e1 and "a8" in e2 and len(lines(8)) == 2, (e1, e2, lines(8)))
# a tied pull request's event still verifies an item within the hour, so a first line at 46 minutes is not idle
panes["home-peer"] = ""
put(9, act=46); pr_event(9, LA.CI_RESULT, "CI passed on PR 4", 46)
put(10, act=59); pr_event(10, LA.CI_RESULT, "CI passed on PR 5", 59)
put(11, act=61); pr_event(11, LA.CI_RESULT, "CI passed on PR 6", 61)
tick()
check("26 a CI result 46 or 59 minutes old still verifies the item (the event window is the hour, not the 45 minutes); one 61 minutes old does not",
      lines(9)[0]["kind"] == "audit" and "CI passed on PR 4" in lines(9)[0]["text"] and lines(10)[0]["kind"] == "audit" and lines(11)[0]["kind"] == "audit_idle", (lines(9), lines(10), lines(11)))
# a log entry dated ahead of the clock is torn only past the hour (`HOUR`), as it was: a clock stepped back 50 minutes only delays the next line
def meta26(at_): return {"hourly_audit": {"log": [{"at": at_, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}]}}
check("26 an entry dated 50 minutes ahead of the clock still counts as the newest line (a clock stepped back a little only delays the next line), one dated 61 minutes ahead is torn",
      HR.last_line(meta26(now0 + 50 * MIN), now0) is not None and HR.last_line(meta26(now0 + 61 * MIN), now0) is None, (HR.last_line(meta26(now0 + 50 * MIN), now0), HR.last_line(meta26(now0 + 61 * MIN), now0)))
# the idle hand-over still waits for a full hour without activity: an idle first line written at 46 minutes hands nothing on yet
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=46); tick()
items26 = lambda: {"a1": rd(1)}
front26 = lambda who, project: telling.front_keeper(who, project)[0]
h46, h59, h60, h61 = (HI.due_all(items26(), now0 + m * MIN, front26) for m in (0, 13, 14, 15))
check("26 the idle line written at 46 minutes of silence hands nothing on until the item has been silent a full hour (not at 46 or 59 minutes, handed at 60 and 61)", idle_marked26 := HR.idle_marked(mt(1)) and h46 == [] and h59 == [] and [g for g, _r in h60] == ["a1"] and [g for g, _r in h61] == ["a1"], (h46, h59, h60, h61, lines(1)))
# the hour's two boundaries to the second: a recorded event exactly an hour old still verifies, one second older does not; a log entry dated exactly an hour ahead still counts, one second more is torn
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
panes["home-peer"] = ""
put(1, act=70); pr_event(1, LA.CI_RESULT, "CI passed on PR 8", 60)
put(2, act=70); pr_event(2, LA.CI_RESULT, "CI passed on PR 9", 60 + 1 / 60)
tick()
check("26 a CI result exactly an hour (60:00) old verifies the item, one at 60:01 does not", lines(1)[0]["kind"] == "audit" and "CI passed on PR 8" in lines(1)[0]["text"] and lines(2)[0]["kind"] == "audit_idle", (lines(1), lines(2)))
check("26 a log entry dated exactly an hour (+60:00) ahead of the clock still counts as the newest line, one second more (+60:01) is torn",
      HR.last_line(meta26(now0 + HR.HOUR), now0) is not None and HR.last_line(meta26(now0 + HR.HOUR + 1), now0) is None, (HR.last_line(meta26(now0 + HR.HOUR), now0), HR.last_line(meta26(now0 + HR.HOUR + 1), now0)))
clean_pane()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
