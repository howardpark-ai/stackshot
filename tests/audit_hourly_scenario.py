"""Scenario test for the hourly audit line (audit/hourly.py, server._hourly_tick, called from the ten-minute silence tick, `[audit] hourly_line`): an item on an agent with no activity for an hour gets ONE
History line saying what the audit verified, or that it is idle. Fixture items in a temporary store, a fake clock (the pass is given its `now`), the pane registry replaced by a dict, no live store, no
network, no model call, no message sent.

  1  due and verified: the mover's pane is busy, a subagent runs (a status line in progress, the mover's own), a tied pull request had a CI result in the last hour (metadata.last_activity), or several of
     them: `Audit hh:mm: verified …` in the instance's zone; the entry of metadata.stall.log has kind `audit`; the item's last-activity record becomes kind `audit`; the activity clock, the progress clock, `updated` and the
     writer are as they were; an idle, shell or unreadable pane, another agent's status line, a done or old one, and a pull request event older than an hour verify nothing
  2  due and nothing verified: `Audit hh:mm: idle, nothing verified`, kind `audit_idle`, `hourly.idle_marked`; the last-activity record is untouched
  3  not due: under an hour of silence (a confirm just now moves nothing), a recent write, an item that just left a hold; the clock the silence pass reads decides
  4  twice in an hour: a second pass writes nothing, the next line comes an hour after the first, and a mover's write in between starts the hour again
  5  not on an agent: a hold (dated wake or none), a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off to a back agent are skipped; one to a front
     agent is written
  6  the switch: absent, false, the string "true" and 1 write nothing; only a TOML true does; the example config documents it as false; read-only copies write nothing
  7  a front agent's item gets its line like any other and nothing is sent to anyone (no message, no ladder entry)
  8  the tick: `_silence_tick` runs it (with the audit on in script mode) and stands still when the audit is off or in agent mode; an item read again under the lock that is no longer due is left alone; one that cannot
     be saved stops no other
  9  the pure parts: the line's words, `last_line`, `stall.note` keeps a kind only when given, the entry cap, a malformed item

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
def lines(i): return [e for e in ST.log_of(mt(i)) if str(e.get("text", "")).startswith("Audit ")]
def tick(at=None, **kw):
    """One pass of the hourly line at `at` (default now0), the server's clock set to it → the ids written."""
    at = now0 if at is None else at
    CLK.t = at
    try: return server._hourly_tick(now=at, **kw)
    finally: CLK.t = None
def on(): server._cfg.CFG["audit"]["hourly_line"] = True
def off(): server._cfg.CFG["audit"].pop("hourly_line", None)
def hm(at): return time.strftime("%H:%M", time.gmtime(at + 4 * 3600))      # the instance zone is Asia/Dubai, UTC+4
def clean_pane(): panes.clear()
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
clean_pane(); put(1, act=90); put(2, act=90); put(3, act=90); put(4, act=90); put(5, act=90); put(6, act=90, work=work("in progress", 30))
panes["home-peer"] = "busy"                                                                       # items 1 and 4 and 5 are home-peer's; 2 is home-peer2's (an idle pane); 3, 6 below
put(2, mover="home-peer2", act=90); panes["home-peer2"] = "idle"
put(3, mover="home-peer2", act=90, work=work("in progress", 30, agent="home-peer2"))               # a subagent running on its own status line, the pane idle
put(4, act=90, last_activity={"at": now0 - 20 * MIN, "kind": "ci_result", "what": "CI failed on PR 5"})
put(5, mover="home-peer2", act=90, last_activity={"at": now0 - 20 * MIN, "kind": "review", "what": "review on PR 9"})
put(6, act=90, work=work("in progress", 30), last_activity={"at": now0 - 20 * MIN, "kind": "ci_result", "what": "CI passing again on PR 7"})
before = {i: rd(i) for i in range(1, 7)}
with _Err() as err: got = tick()
check("1 a pass over the six writes a line on the items with something verified and the idle ones too: items 1 to 6 are all due", got == ["a1", "a2", "a3", "a4", "a5", "a6"], got)
L = {i: lines(i) for i in range(1, 7)}
check("1 a busy pane: `Audit hh:mm: verified the mover's pane is in a turn`, the time in the instance's zone, kind audit", len(L[1]) == 1 and L[1][0]["text"] == f"Audit {hm(now0)}: verified the mover's pane is in a turn" and L[1][0]["kind"] == "audit" and L[1][0]["at"] == now0, L[1])
check("1 an idle pane verifies nothing: the line says idle", len(L[2]) == 1 and L[2][0]["text"] == f"Audit {hm(now0)}: idle, nothing verified" and L[2][0]["kind"] == "audit_idle", L[2])
check("1 a status line in progress on the mover's own step is a subagent running, the pane idle", len(L[3]) == 1 and L[3][0]["text"] == f"Audit {hm(now0)}: verified a subagent is running on it", L[3])
check("1 a CI result of a tied pull request in the last hour (metadata.last_activity) is verified, in the record's words", L[4][0]["text"] == f"Audit {hm(now0)}: verified the mover's pane is in a turn, CI failed on PR 5", L[4])
check("1 …a review likewise", L[5][0]["text"] == f"Audit {hm(now0)}: verified review on PR 9", L[5])
check("1 …several signals are joined in one line", L[6][0]["text"] == f"Audit {hm(now0)}: verified the mover's pane is in a turn, a subagent is running on it, CI passing again on PR 7", L[6])
check("1 a line that verified something is the item's last-activity record (kind audit, the words, the time); an idle one leaves the record as it was",
      mt(1)["last_activity"] == {"at": now0, "kind": "audit", "what": "the mover's pane is in a turn"} and mt(4)["last_activity"]["kind"] == "audit" and "last_activity" not in mt(2), (mt(1).get("last_activity"), mt(2).get("last_activity")))
check("1 the save is the server's own bookkeeping: the activity clock, the progress clock, `updated`, the confirm and the writer are exactly as they were",
      all(all(rd(i)[k] == before[i][k] for k in ("activity", "progress", "updated", "state_updated", "confirmed", "written_by", "written_at")) for i in range(1, 7)))
check("1 …the History shows it: the revision's new stall entries are the line (stall.new_entries), nothing else changed in the metadata but the line, the record and the phase stamp every save adds",
      [e["text"] for e in ST.new_entries(before[1]["metadata"], rd(1)["metadata"])] == [L[1][0]["text"]] and {k for k in mt(1) if mt(1)[k] != before[1]["metadata"].get(k)} == {"stall", "last_activity", "phase"}
      and {k for k in mt(2) if mt(2)[k] != before[2]["metadata"].get(k)} == {"stall", "phase"},
      ([e["text"] for e in ST.new_entries(before[1]["metadata"], rd(1)["metadata"])], {k for k in mt(1) if mt(1)[k] != before[1]["metadata"].get(k)}, {k for k in mt(2) if mt(2)[k] != before[2]["metadata"].get(k)}))
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
      all(lines(i) == [] for i in range(1, 8)) and all(mt(i).get("stall") is None for i in range(1, 8)))
panes["home-peer"] = "busy"
tick()
check("1 …they say idle, and with the pane busy only the pane is verified", [e["text"] for i in range(1, 8) for e in lines(i)] == [f"Audit {hm(now0)}: verified the mover's pane is in a turn"] * 7, [lines(i) for i in range(1, 8)])

# ================================================================ 2. due and nothing verified
clean_pane(); put(1, act=90)
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
second = tick(now0 + 10 * MIN); third = tick(now0 + 59 * MIN)
check("4 a second and a third pass inside the hour write nothing: one line", first == ["a1"] and second == [] and third == [] and len(lines(1)) == 1, (first, second, third, lines(1)))
check("4 an hour after the first line, an item still silent gets the next", tick(now0 + 60 * MIN) == ["a1"] and len(lines(1)) == 2 and lines(1)[1]["at"] == now0 + 60 * MIN)
put(2, act=90); tick(); d2 = rd(2); d2["activity"] = now0 + 5 * MIN; (T / "store/a/2.json").write_text(json.dumps(d2))
r62, r66 = tick(now0 + 62 * MIN), tick(now0 + 66 * MIN)
check("4 a write by the mover after the line starts the hour again: 57 minutes after it nothing, 61 minutes after it (and 66 after the line) the next line",
      "a2" not in r62 and "a2" in r66 and len(lines(2)) == 2, (r62, r66, lines(2)))
put(3, act=90); tick(now0 + 130 * MIN); tick(now0 + 131 * MIN)
check("4 two passes close together write one line", len([e for e in lines(3) if e["at"] == now0 + 130 * MIN]) == 1 and not any(e["at"] == now0 + 131 * MIN for e in lines(3)), lines(3))
# the stale view: a pass whose list was made before another pass wrote the line
put(4, act=90); stale_items = {"a4": rd(4)}
tick()
with _Err():
    real_pass = HR.pass_
    put(8, act=90, status="completed", outcome="done")
    HR.pass_ = lambda items, now, env=None, pane=None, same=None: [("a4", {"text": "stale", "verified": [], "kind": "audit_idle"}), ("a8", {"text": "stale", "verified": [], "kind": "audit_idle"})]      # the list a slower pass made before the line was written, and an item that closed since
    try: stale = server._hourly_tick(now=now0 + 5 * MIN)
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
check("7 …a front agent in a turn is verified the same", lines(1)[1]["text"] == f"Audit {hm(now0 + 61 * MIN)}: verified the mover's pane is in a turn", lines(1))

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
real_save = server._save
def save_fail(gid, *a, **k):
    if gid == "a1": raise OSError("disk full")
    return real_save(gid, *a, **k)
server._save = save_fail
for i in (1, 2): put(i, act=90)
with _Err() as e8: got8 = tick()
server._save = real_save
check("8 one item that cannot be saved stops no other, and the failure is logged", got8 == ["a2"] and "a1 hourly line not written: OSError" in e8.text and lines(2) != [], (got8, e8.text))
real_hourly = server._hourly_tick
def boom(**kw): raise RuntimeError("pass failed")
server._hourly_tick = boom
with _Err() as e8b: r8 = server._silence_tick()
server._hourly_tick = real_hourly
check("8 a hourly pass that raises never stops the silence tick that called it", e8b.text.count("hourly line not run: RuntimeError") == 1, e8b.text)

# ================================================================ 9. the pure parts
clean_pane(); put(1, act=90); put(2, act=90)
meta = {"stall": {"log": [{"at": 5.0, "text": "ladder line"}, {"at": 9.0, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}, {"at": 7.0, "text": "Audit 09:00: verified x", "kind": "audit"}, {"at": "bad", "text": "x", "kind": "audit"}]}}
check("9 last_line is the newest audit entry by time, skipping the ladder's lines and a torn one", HR.last_line(meta)["at"] == 9.0 and HR.idle_marked(meta) and HR.last_line({}) is None and HR.last_line(None) is None and not HR.idle_marked({"stall": {"log": [{"at": 1, "text": "x"}]}}))
m9 = {}; ST.note(m9, 1.0, "plain"); ST.note(m9, 2.0, "Audit 00:00: idle, nothing verified", kind="audit_idle")
check("9 stall.note keeps a kind only when given (the ladder's entries are as they were)", m9["stall"]["log"] == [{"at": 1.0, "text": "plain"}, {"at": 2.0, "text": "Audit 00:00: idle, nothing verified", "kind": "audit_idle"}], m9)
m9b = {}
for k in range(10): ST.note(m9b, float(k), f"line {k}", kind="audit")
check("9 the log keeps eight entries", len(ST.log_of(m9b)) == 8 and ST.log_of(m9b)[0]["text"] == "line 2")
check("9 the line's words: verified a, b / idle, nothing verified, hh:mm in the instance zone", HR.text(now0, ["a", "b"]) == f"Audit {hm(now0)}: verified a, b" and HR.text(now0, []) == f"Audit {hm(now0)}: idle, nothing verified")
check("9 the pass reads only: pass_ over the items writes nothing and gives the same list twice", (lambda items: HR.pass_(items, now0, server._silence_env(), lambda w: "busy", server._ho_same) == HR.pass_(items, now0, server._silence_env(), lambda w: "busy", server._ho_same))({"a1": rd(1), "a2": rd(2)}))
check("9 an item the pass cannot read is left out, and a pane callable that raises verifies nothing", HR.pass_({"a1": {"status": "open", "metadata": "torn"}, "a2": rd(2)}, now0, server._silence_env(), lambda w: (_ for _ in ()).throw(OSError("x")), server._ho_same)[0][1]["kind"] == "audit_idle")
check("9 a pane callable of None verifies nothing", HR.verified(rd(2), rd(2)["metadata"], "home-peer", now0, None, server._ho_same) == [])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
