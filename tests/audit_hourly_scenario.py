"""Scenario test for the hourly audit line (audit/hourly.py, server._hourly_tick, called from the ten-minute silence tick, `[audit] hourly_line`): an item on an agent with no activity for an hour gets ONE
History line saying what the audit verified, or that it is idle. Fixture items in a temporary store, a fake clock (the pass is given its `now`), the pane registry replaced by a dict, no live store, no
network, no model call, no message sent.

  1  due and verified: the mover's pane is busy, a subagent runs (a status line in progress, the mover's own), a tied pull request had a CI result in the last hour (metadata.last_activity), or several of
     them: `Audit hh:mm: verified …` in the instance's zone; the entry of the item's own log, metadata.hourly_audit.log (not the stall ladder's metadata.stall.log), has kind `audit`; a line that rests on a busy pane or a subagent alone says `live state only`; a line that verified something is stamped as the item's last-activity record (section 16), one that verified nothing or rests on a recorded event alone is not; the activity clock, the progress clock, `updated` and the
     writer are as they were; an idle, shell or unreadable pane, another agent's status line, a done or old one, and a pull request event older than an hour verify nothing
  2  due and nothing verified: `Audit hh:mm: idle, nothing verified`, kind `audit_idle`, `hourly.idle_marked`; the last-activity record is untouched
  3  not due: under an hour of silence (a confirm just now moves nothing), a recent write, an item that just left a hold; the clock the silence pass reads decides
  4  twice in 45 minutes: a second pass writes nothing, the next line comes 45 minutes after the first, and a mover's write in between starts the hour again
  5  not on an agent: a hold (dated wake or none), a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off to a back agent are skipped; one to a front
     agent is written
  6  the switch: absent, false, the string "true" and 1 write nothing; only a TOML true does; the example config documents it as false; read-only copies write nothing
  7  a front agent's item gets its line like any other and nothing is sent to anyone (no message, no ladder entry)
  8  the tick: `_silence_tick` runs it (with the audit on in script mode) and stands still when the audit is off or in agent mode; an item read again under the lock that is no longer due is left alone; one that cannot
     be saved stops no other
  9  the pure parts: the line's words, `last_line`, the log's cap, a malformed item, a log entry dated far ahead, an item with no timestamp, each tied-pull-request kind, `new_entries`
  10 the cap on lines: one every 50 minutes on the ten-minute grid for the first 24 hours of silence (27), then one every 6 hours (51 in a week, the clock stepped), a clock that goes backwards delays the next line without a second write
  11 the lines are kept out of the stall ladder's log: its entries are untouched and not crowded out, `get` prints the newest as `audit:` and never as `stall:`, both History renderers show the line
  12 a last-activity record dated ahead of the clock is no event
  13 the hourly line runs whatever the silence pass did: a ladder view that cannot be built (the pass returns early) or a pass that raises still gets the hourly line
  14 tick jitter: on a ten-minute grid with 0 to 8 seconds of jitter the lines come every 50 minutes in the first day and every 6 hours after
  15 a torn entry in the log never raises
  16 a verified line is the item's last activity: the row reads its time and words, an idle line leaves the record alone, an older line never replaces a newer real event, the backfill does not undo it
  18 the row never reads "idle over 1 h" between two lines (read through act_parts and band at the worst landing time); the record never goes backwards (a stepped-back clock, a record dated ahead)

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
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
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
from stackshot.web import server
from stackshot.audit import hourly as HR, silence as SL
from stackshot.waits import stall as ST, handoff as HO
from stackshot.audit import hourly_log as HL
from stackshot.model import last_activity as LA, activity as ACT
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the saves below: the pass is given its `now`, and the saves stamp from the server's own clock."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = CLK
server._cfg.CFG["audit"]["pattern_review"] = "off"
server._cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every message the server was asked to send: none is expected from this pass
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append((to, text)), "delivered to " + to)[1]
server._tell_woken = lambda *a, **k: sent.append(("tell_woken", a))
server._inbox_flag_send = lambda *a, **k: sent.append(("flag", a))
panes = {}                                                         # mover -> the pane's registry status; "boom" = unreadable
def fake_status(who, idx=None):
    st = panes.get(who, "")
    if st == "boom": raise OSError("registry unreadable")
    return (st, now0 - 3600) if st else ("", 0.0)
server._handoff_status = fake_status
server._sessions_index = lambda: {}
server._stall_active = lambda: set()

def put(i, mover="home-peer", status="open", act=90, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0 (a bare confirm and the server's saves are recent)."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "progress": at, "written_at": at, "written_by": mover, "metadata": base}))
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
def off(): server._cfg.CFG["audit"].pop("hourly_line", None)
def hm(at): return time.strftime("%H:%M", time.gmtime(at + 4 * 3600))      # the instance zone is Asia/Dubai, UTC+4
def clean_pane(): panes.clear(); SUBS.clear(); ANCH.clear()
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()
def pr_event(i, kind, what, ago_min): mt_ = rd(i); mt_["metadata"]["last_activity"] = {"at": now0 - ago_min * MIN, "kind": kind, "what": what}; (T / f"store/a/{i}.json").write_text(json.dumps(mt_))
def work(state, ago_min, agent="home-peer"): return [{"id": "build-it", "text": "build it", "agent": agent, "state": state, "ts": now0 - ago_min * MIN}]

# ================================================================ 6a. the switch is off by default
put(1, act=90); panes["home-peer"] = "busy"
check("6 the example config documents `hourly_line = false` in [audit]", re.search(r"(?m)^hourly_line = false\b", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)
check("6 …and the config as loaded (from that example) has it off: nothing is written", HR.enabled() is False and tick() == [] and lines(1) == [] and sent == [])
for label, val in (("false", False), ("the string true", "true"), ("1", 1), ("yes", "yes")):
    server._cfg.CFG["audit"]["hourly_line"] = val
    check(f"6 {label} does not switch it on (only a TOML true does)", HR.enabled() is False and tick() == [] and lines(1) == [])
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
check("1 the save is the server's own bookkeeping: the activity clock, the progress clock, `updated`, the confirm and the writer are exactly as they were",
      all(all(rd(i)[k] == before[i][k] for k in ("activity", "progress", "updated", "state_updated", "confirmed", "written_by", "written_at")) for i in range(1, 7)))
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
put(1, act=59); put(2, act=61); put(3, act=10); put(4, act=90, hold=False)
put(5, act=240); d5 = rd(5); d5["state_updated"] = now0 - 20 * MIN; (T / "store/a/5.json").write_text(json.dumps(d5))           # silent four hours, but left a hold twenty minutes ago
put(6, act=90); d6 = rd(6); d6["confirmed"] = now0 - 1 * MIN; (T / "store/a/6.json").write_text(json.dumps(d6))                      # a bare confirm just now moves nothing: due
got = tick()
check("3 under an hour without activity is not due (59 minutes, 10 minutes); 61 and a confirm just now are", got == ["a2", "a4", "a6"], got)
check("3 an item that left a hold twenty minutes ago counts from then (the silence pass's clock), not from its activity four hours back", lines(5) == [] and SL.clock(rd(5), "home-peer") == now0 - 20 * MIN)
put(7, act=59.9); check("3 the limit is exact: 59 minutes 54 seconds is not due", tick() == [])
put(7, act=60); check("3 …an hour is", tick() == ["a7"], tick())

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
r62, r66 = tick(now0 + 62 * MIN), tick(now0 + 66 * MIN)
check("4 a write by the mover after the line starts the hour again: 57 minutes after it nothing, 61 minutes after it (and 66 after the line) the next line",
      "a2" not in r62 and "a2" in r66 and len(lines(2)) == 2, (r62, r66, lines(2)))
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
put(10, mover="home-front", act=90, **{HO.KEY: HO.new_record("home-front", "", "team-back", now0 - 90 * MIN)})   # handed to a front agent, not taken: checked, as the silence pass does
put(11, mover="home-peer", act=90, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 5 * H + 4 * H)))     # a wake with no wait behind it leaves the item on agent
d1 = rd(1); got5 = tick()
check("5 a hold (dated wake or none), a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off to a back agent, and an item not yet due: none written",
      not any(g in got5 for g in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9")), got5)
check("5 …an untaken hand-off to a front agent is written (the silence pass checks it too), and so is an item with a wake alone", sorted(got5) == ["a10", "a11"], got5)
check("5 the skipped items are byte for byte as they were", rd(1) == d1)

# ================================================================ 7. a front agent's item
clean_pane(); panes["home-front"] = "idle"
for p in (T / "store/a").glob("*.json"): p.unlink()
put(1, mover="home-front", act=90)
check("7 the test's front agent is one for the server's own answer", server._front_keeper("home-front", "projects/alpha")[0] is True and server._front_keeper("team-back", "projects/alpha")[0] is False)
got7 = tick()
check("7 a front agent's item due gets its line like any other (a pane that is not in a turn: idle)", got7 == ["a1"] and lines(1)[0]["text"] == f"Audit {hm(now0)}: idle, nothing verified", lines(1))
check("7 …and nothing is sent to it or to anyone: no message, no notice, no ladder entry", sent == [] and server._stall_load().get("a1") is None, (sent, server._stall_load()))
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
check("8 with the audit on in script mode the silence tick writes the hourly line too: one on each item", res is not None and len(lines(1)) == 1 and len(lines(2)) == 1, (res, lines(1), lines(2)))
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
check("8 a hourly pass that raises never stops the silence tick that called it", e8b.text.count("hourly line not run: RuntimeError") == 1, e8b.text)

# ================================================================ 13. the hourly line runs whatever the silence pass did
clean_pane(); panes["home-peer"] = "busy"
for p_ in (T / "store/a").glob("*.json"): p_.unlink()
put(1, act=90); put(2, act=90)
real_skip = server._silence_skip
def skip_boom(*a, **k): raise RuntimeError("ladder view failed")
server._silence_skip = skip_boom
with _Err() as e13: r13 = server._silence_tick()
server._silence_skip = real_skip
check("13 a ladder view that cannot be built sends the silence pass home early, and the hourly line is written all the same: one on each item", r13 is None and "ladder view not read" in e13.text and len(lines(1)) == 1 and len(lines(2)) == 1, (r13, e13.text, lines(1), lines(2)))
for i in (1, 2): put(i, act=90)
real_pass = server._silence_pass_tick
def pass_boom(*a, **k): raise RuntimeError("silence pass failed")
server._silence_pass_tick = pass_boom
raised = None
try: server._silence_tick()
except RuntimeError as e: raised = e
server._silence_pass_tick = real_pass
check("13 a silence pass that raises still lets the hourly line run, and its error is not hidden", raised is not None and "silence pass failed" in str(raised) and len(lines(1)) == 1 and len(lines(2)) == 1, (raised, lines(1), lines(2)))
server._cfg.CFG["audit"]["enabled"] = False
for i in (1, 2): put(i, act=90)
server._silence_tick()
server._cfg.CFG["audit"]["enabled"] = True
check("13 …but not with the audit off: the tick stands still as a whole", lines(1) == [] and lines(2) == [])

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
check("11 the key is a re-park-quiet bookkeeping key like the ladder's and the front agent's", "hourly_audit" in server._REPARK_QUIET)

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
check("12 with the key absent from the loaded config the pass is off and writes nothing", "hourly_line" not in server._cfg.CFG["audit"] and HR.enabled() is False and tick() == [] and lines(3) == [])
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
check("9 the pass reads only: pass_ over the items writes nothing and gives the same list twice", (lambda items: HR.pass_(items, now0, server._silence_env(), lambda w: "busy", server._ho_same) == HR.pass_(items, now0, server._silence_env(), lambda w: "busy", server._ho_same))({"a1": rd(1), "a2": rd(2)}))
check("9 an item the pass cannot read is left out, and a pane callable that raises verifies nothing", HR.pass_({"a1": {"status": "open", "metadata": "torn"}, "a2": rd(2)}, now0, server._silence_env(), lambda w: (_ for _ in ()).throw(OSError("x")), server._ho_same)[0][1]["kind"] == "audit_idle")
check("9 a pane callable of None verifies nothing", HR.verified(rd(2), rd(2)["metadata"], "home-peer", now0, None, server._ho_same) == ([], []))

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
kinds9 = {1: ("pr_merged", "PR 4 merged"), 2: ("comment", "comment on PR 4"), 3: ("ci_result", "CI passed on PR 4"), 4: ("review", "review on PR 4")}
for i_, (k_, w_) in kinds9.items(): put(i_, act=90, last_activity={"at": now0 - 5 * MIN, "kind": k_, "what": w_})
tick()
check("9 a tied pull request's merge, comment, CI result and review each verify, in the record's words", all(lines(i_)[0]["text"] == f"Audit {hm(now0)}: verified {w_}" for i_, (k_, w_) in kinds9.items()), [lines(i_) for i_ in kinds9])
# an item with no timestamp at all
nots = rd(1); [nots.pop(k_, None) for k_ in ("activity", "progress", "updated", "state_updated", "created", "confirmed", "written_at")]
try: wt = HR.due({"a1": nots}, "a1", now0, server._silence_env(), lambda w: "busy", server._ho_same)
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
check("16 …and the item's own clocks are as they were: the audit's write moves neither `activity` nor `progress` (the silence clock reads the same as before the line), `updated` and the writer too",
      all(rd(1)[k] == snap16[1][k] for k in ("activity", "progress", "updated", "state_updated", "confirmed", "written_by", "written_at")) and SL.clock(rd(1), "team-back") == SL.clock(snap16[1], "team-back") == now0 - 90 * MIN)
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
got_run = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}
check("17 the reader lists the running subagents of a session's transcript: no finished flag and a transcript written within 90 minutes, the description and the brief (a string or text blocks) as its text; a finished one and a stale one are left out, a meta that cannot be read is listed running with no words (it may be running)",
      sorted(got_run) == ["badmeta", "blocks", "run1"] and got_run["badmeta"] == {"id": "badmeta", "text": "", "at": 0.0, "unreadable": True} and got_run["run1"]["text"] == f"Build the thing\nGoal: {BID(1)} in the worktree" and BID(2) in got_run["blocks"]["text"] and got_run["run1"]["at"] == now0 - 60, got_run)
def raises(fn, exc):
    try: fn()
    except exc: return True
    except Exception: return False
    return False
check("17 …a session with no transcript on this box, a name that is no uuid and no roots cannot be read (Unreadable: unknown, not nothing running); a transcript with no subagents folder and a clock three hours on give none",
      raises(lambda: TIE.running(str(_uuid.uuid4()), [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running("home-peer", [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running(SID, [], now0), TIE.Unreadable)
      and TIE.running(SID, [str(T / "transcripts")], now0 + 3 * H) == [])
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
def registry(status="busy", sid=SID, kind="interactive"): row_path.write_text(json.dumps({"pid": os.getpid(), "sessionId": sid, "kind": kind, "name": "home-peer", "status": status, "statusUpdatedAt": int(now0 * 1000), "updatedAt": int(now0 * 1000)}))
try:
    registry()
    check("17 the server's reader gives the running subagents of a mover whose pane is in a turn", [x["id"] for x in server._mover_subagents("home-peer", {}, now0)] == ["blocks", "run1"], server._mover_subagents("home-peer", {}, now0))
    registry("idle"); a_ = server._mover_subagents("home-peer", {}, now0)
    registry("shell"); b_ = server._mover_subagents("home-peer", {}, now0)
    registry("busy", kind="headless"); c_ = server._mover_subagents("home-peer", {}, now0)
    registry("busy", sid=str(_uuid.uuid4())); d_ = "a pane in a turn with no transcript here"
    check("17 …and none when the pane is idle or showing a shell, is no interactive pane, or the mover has no pane on this box (known: nothing runs, or nothing can be claimed)", a_ == [] and b_ == [] and c_ == [] and server._mover_subagents("home-front", {}, now0) == [], (a_, b_, c_))
    check("17 …and Unreadable (unknown) for a pane in a turn whose transcript this box does not hold, or whose registry row names no session", raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable) and (registry("busy", sid=""), raises(lambda: server._mover_subagents("home-peer", {}, now0), TIE.Unreadable))[1], d_)
    registry("busy")
    clean_pane(); panes["home-peer"] = "busy"
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    put(1, act=90); put(2, act=90); put(3, act=90)
    tick(subagents=None)
    check("17 a tick that is given no subagent view reads the transcripts itself: item 1, named in the brief of the one running subagent, is verified; items 2 (named in a brief that is also running) and 3 follow their own briefs (a finished subagent names none)",
          [lines(i)[0]["kind"] for i in (1, 2, 3)] == ["audit", "audit", "audit_idle"], [lines(i) for i in (1, 2, 3)])
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
    return [g for g, _r in HI.due_all(items_, now_, lambda who, project: server._front_keeper(who, project)[0])]
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
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
