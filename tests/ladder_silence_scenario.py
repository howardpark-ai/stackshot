"""Scenario test for the ladder switch: with `[ladder] enabled` and `[ladder] silence` the ten-minute silence pass (and the dates pass) bring an item to the one ladder, and a pane with no turn running
no longer does (ladder.py, silence.silence_pass `entered`, audit_run.dates_pass `entered`, server._ladder_enter_quiet, _ladder_quiet_look, _stall_tick). Fixture items, panes that are files in a temp
folder, messages recorded by a fake push, a fake clock (every pass is given its `now`), no live store, no network, no model call.

  1  the switch: `[ladder] silence` is off by default and does nothing without `[ladder] enabled`; only a TOML true with both turns it on; the silence tick and the dates tick hand the ladder to their pass only
     then; with it off the stall pass starts a ladder from a pane with no turn running, as before
  2  the ask: a fresh silence finding is sent to its mover (the message is the ask) and puts the item on the ladder at the look, its clock started then, a History line saying so; a second pass sends
     and enters nothing; a finding sent in an earlier episode (before the switch) is not entered
  3  the look: nothing before `look_minutes` (30); then, with the mover's pane idle, the mover is told once more (a front agent gets the History line alone); a pane with a turn running is left alone until it ends
  4  cold, builder: ten minutes after the look the cold call is asked; with no taker the item goes to the project's builder, and the silence entry ends with the mover change; with no builder and no cold call the last rung
     is ONE message to the fleet's builder, the item staying with its mover and off the owner's list
  5  activity ends it: a write that counts (the activity clock moves) before the look ends the entry; a bare confirm and the ladder's own notes do not, and the ladder goes on
  6  a pane with no turn running no longer starts a ladder (the silence audit does); an untaken hand-off is still the hand-off audit's, and its ladder is taken here as before
  7  the dates pass: an item past its expected time with no write since is sent its message and put on the same ladder
  8  the switch turned off in the middle of a ladder, and the whole one-ladder flag turned off: the entry is read in the old table (nothing is repeated, the builder rung stays reachable)
  9  pure: ladder.enter_quiet, quiet_over, via_of, unwind, action
 10  a background mover whose pane is busy (or shows a background shell) is still chased past the ask: the look is sent in the "nothing written for N minutes" wording; a work line in progress changed
     within 90 minutes holds the ladder; a live pane stops at the look, a pane that is not live goes on to the cold call and the builder (never the builder itself); one notice per agent per pass;
     a front agent keeps the pane rule; ladder.action for a background mover;
     only the mover's own work line holds the ladder; an empty or unreadable heartbeat is unknown (live); a gone entry reaches the cold call whatever the heartbeat shows

    tests/run-suite ladder_silence       -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="laddersil-"); T = pathlib.Path(tmp)
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
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/audit", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-peer3", "home-send", "home-beta-front", "home-stew", "home-beta-stew", "home-fleet")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
    "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"})):
    back = [k for k in agents if k in ("home-docs", "team-back")]
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the sample task is in progress.\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
B = now0 - 6 * H                  # the stall pass first ran then (before every clock below)
ZONE = __import__("datetime").timezone(__import__("datetime").timedelta(hours=4))   # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
local = lambda ts: __import__("datetime").datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
def put(i, project="projects/alpha", mover="home-peer", status="open", act=None, **meta):
    """An open doing item on `mover`, last written and last active `act` minutes before now0 (its other clocks recent: a bare confirm, a save of the server's)."""
    base = {"owner": U["home-front"], "project": project, "next": f"{mover}: do the thing", "state": "doing", "needs": [mover]}
    if mover: base["mover"] = mover
    base.update(meta)
    at = now0 - (60 if act is None else act) * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": at, "state_updated": at, "confirmed": at,
                                                       "activity": at, "written_at": at, "written_by": "home-front", "metadata": base}))
def close(*ids):
    for i in ids:
        d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def ho(i): return mt(i).get("handoff") or {}
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import handoff as H_; from stackshot.waits import stall as S; from stackshot.waits import ladder as LD; from stackshot.audit import silence as SL; from stackshot.audit import audit_run as AR; from stackshot.audit import audit
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
server._PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = server._tell_woken
def _tell(gid, owner, note, tag="wake"):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
server._tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
    while server._HO_COLD_THREADS: server._HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def look_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "nothing written for" in p[1]]
def stall_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "have had no turn running" in p[1]]
def set_cfg(**kw): server._cfg.CFG["model"] = dict(kw)
def ladder_cfg(enabled=True, silence=True, **kw):
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, "silence": silence, **kw}.items() if v is not None}
set_cfg(); server._cfg.CFG["stall"] = {}
server._cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"
COLD_MSGS = []
def cold(answer, status="ok"):
    def run(msg):
        COLD_MSGS.append(msg)
        return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    server._COLD_RUNNER = run
cold("no json at all here")
def cli_row(who, status, at):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
def no_row(who): (T / f"cli/{os.getpid()}-{who}.json").unlink(missing_ok=True)
server.CLI_SESSIONS = T / "cli"
server._stall_since(B)
def stk(at):
    """One stall pass at `at` (the 20-second gate reset), the threads it started finished → the items it acted on."""
    server._STALL_LAST[0] = 0.0
    out = server._stall_tick(at); drain()
    return out
def log_of(i): return S.log_of(mt(i))
ROLES = {"home-peer": {"role": "background"}, "home-peer2": {"role": "background"}, "home-peer3": {"role": "background"}, "team-back": {"role": "background"}, "home-front": {"role": "front"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env():
    return AR.Env(roles=ROLES, fallback=lambda p: "home-front", builder=lambda p: "team-back", page_of=lambda p: ("", None), deliver=deliver, push=lambda to, text: (True, "delivered"), sessions=lambda: None,
                  pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
def clear_records():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
def load(*ids): return {f"a{i}": server._load(f"a{i}") for i in ids}
def silence_pass(ids, at=None, entered=True):
    """One silence pass over these items at `at`, as the server's tick runs it: the real pane view, and the ladder given to it when the switch is on."""
    return SL.silence_pass(now=now0 if at is None else at, items=load(*ids), env=env(), skip=server._silence_skip(), entered=server._ladder_enter_quiet if entered and server._ladder_silence_on() else None)
def entry(i): return server._stall_load().get(f"a{i}")
IDLE_SINCE = now0 - 50 * MIN        # the pane went idle then (the silent item's last activity was 60 minutes before now0)

# ================================================================ 1. the switch
check("1 off: with no [ladder] section the one ladder and the silence switch are off", not server._ladder_on() and not server._ladder_silence_on() and server._cfg.get("ladder", "silence", default=False) is False, None)
ladder_cfg(False, True)
check("1 off: `silence` alone does nothing (the one ladder is off)", not server._ladder_silence_on(), None)
ladder_cfg(True, None)
check("1 off: `enabled` alone leaves silence off (a pane with no turn running still starts a ladder, as before)", server._ladder_on() and not server._ladder_silence_on(), None)
ladder_cfg(True, "yes")
check("1 off: only a TOML true turns it on", not server._ladder_silence_on(), None)
ladder_cfg(True, True)
check("1 on: both `enabled` and `silence` true turn it on, and the look is 30 minutes", server._ladder_silence_on() and server._ladder_look() == 30.0, None)
spy = []
_real_pass, _real_dates = SL.silence_pass, AR.dates_pass
SL.silence_pass = lambda **kw: spy.append(("silence", kw.get("entered"))) or {}
AR.dates_pass = lambda **kw: spy.append(("dates", kw.get("entered"))) or {}
try:
    server._silence_tick(); server._dates_expected_tick()
    on_spy = list(spy); spy.clear()
    ladder_cfg(True, None); server._silence_tick(); server._dates_expected_tick()
    off_spy = list(spy); spy.clear()
    ladder_cfg(False, True); server._silence_tick(); server._dates_expected_tick()
    off2_spy = list(spy); spy.clear()
finally:
    SL.silence_pass, AR.dates_pass = _real_pass, _real_dates
ladder_cfg(True, True)
check("1 wiring: the silence tick and the dates tick give the ladder to their pass only with both on", [(k, e is server._ladder_enter_quiet) for k, e in on_spy] == [("silence", True), ("dates", True)]
      and [(k, e) for k, e in off_spy] == [("silence", None), ("dates", None)] and [(k, e) for k, e in off2_spy] == [("silence", None), ("dates", None)], (on_spy, off_spy, off2_spy))
# a pane with no turn running starts a ladder with the switch off, and none with it on
put(1, act=30); cli_row("home-peer", "idle", IDLE_SINCE)
ladder_cfg(True, None)
done = stk(now0 + 1)
check("1 off: with `silence` off an item whose pane has had no turn for 10 minutes gets the stall notice and a via=stall entry, as before", "a1" in done and len(stall_notices("home-peer", 1)) == 1 and LD.via_of(entry(1)) == "stall", (done, pushes(), entry(1)))
close(1); server._stall_save({})
ladder_cfg(True, True)

# ================================================================ 2. the ask
clear_records()
put(10, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
r = silence_pass([10])
e10 = entry(10)
check("2 ask: a silent item is found and the finding goes to its mover (the message is the ask)", r["findings"] == 1 and r["fresh"] == 1 and len(sent) == 1 and sent[0][0] == "home-peer" and "board#10" in sent[0][1], (r, sent))
check("2 ask: …and the item is on the ladder at the look: via silence, step 1, started now, for this silence (the activity clock), the mover and the version noted",
      e10 and e10.get("via") == "silence" and e10.get("step") == 1 and e10.get("last") == now0 and e10.get("act") == rd(10)["activity"] and e10.get("mover") == "home-peer" and e10.get("ladder") is True
      and LD.quiet(e10), e10)
check("2 ask: …a History line says so, and the item is as it was (no write by a session: version and activity unmoved)",
      len(log_of(10)) == 1 and "asked for news" in log_of(10)[0]["text"] and rd(10)["activity"] == now0 - 60 * MIN and rd(10)["updated"] == now0 - 60 * MIN, (log_of(10), rd(10)))
sent.clear(); r2 = silence_pass([10], at=now0 + 600)
check("2 ask: a second pass sends nothing and does not enter it again (the item is on the ladder: the pass leaves it to the ladder)", r2["fresh"] == 0 and not sent and entry(10) == e10 and len(log_of(10)) == 1, (r2, sent, entry(10)))
# a finding sent before the switch (an earlier episode) is not entered: the pass never floods the ladder
clear_records(); ladder_cfg(True, None)
put(11, act=60); cli_row("home-peer2", "idle", IDLE_SINCE); d11 = rd(11); d11["metadata"]["mover"] = "home-peer2"; d11["metadata"]["needs"] = ["home-peer2"]; (T / "store/a/11.json").write_text(json.dumps(d11))
silence_pass([11]); ladder_cfg(True, True); sent.clear()
r3 = silence_pass([11], at=now0 + 600)
check("2 ask: a finding sent before the switch was turned on is a repeat: not sent again, not put on the ladder", r3["repeats"] == 1 and r3["fresh"] == 0 and entry(11) is None and not sent, (r3, entry(11)))
close(11)

# ================================================================ 3. the look
no_msgs = lambda: not look_notices("home-peer", 10)
check("3 look: 29 minutes after the ask nothing is sent", "a10" not in stk(now0 + 29 * MIN) and no_msgs(), pushes_to("home-peer", "a10"))
done = stk(now0 + 31 * MIN)
check("3 look: 31 minutes after the ask, the pane having no turn running, the mover is told once more, in the silence wording, with the step on the item and the ladder on the cold call",
      "a10" in done and len(look_notices("home-peer", 10)) == 1 and "nothing written for" in look_notices("home-peer", 10)[0][1] and entry(10)["step"] == 2 and entry(10)["last"] == now0 + 31 * MIN
      and len(log_of(10)) == 2 and "nothing was written to it" in log_of(10)[1]["text"] and not stall_notices("home-peer", 10), (done, pushes_to("home-peer", "a10"), entry(10), log_of(10)))
check("3 look: …the stall wording (a pane with no turn for N minutes) is not used for an item the silence audit brought", not stall_notices("home-peer", 10), pushes_to("home-peer", "a10"))
# a pane with a turn running at the look is left alone; the look comes when the turn ends
clear_records()
put(12, act=60, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE_SINCE)
silence_pass([12]); cli_row("home-peer2", "busy", now0 + 20 * MIN)
check("3 look: a turn started after the ask: 35 minutes on, nothing is sent", "a12" not in stk(now0 + 35 * MIN) and not look_notices("home-peer2", 12), pushes_to("home-peer2", "a12"))
cli_row("home-peer2", "idle", now0 + 36 * MIN)
check("3 look: …the turn ends: the look comes at once", "a12" in stk(now0 + 37 * MIN) and len(look_notices("home-peer2", 12)) == 1, pushes_to("home-peer2", "a12"))
close(12)
# a front agent's item: the look is a History line alone
clear_records(); put(13, act=60, mover="home-front"); cli_row("home-front", "idle", IDLE_SINCE)
silence_pass([13]); done = stk(now0 + 31 * MIN)
check("3 look: a front agent is sent no notice at the look (the History line alone), and the entry goes on to the cold call", "a13" in done and not pushes_to("home-front", "a13") and entry(13)["step"] == 2
      and any("no notice is sent to a front agent" in x["text"] for x in log_of(13)), (done, pushes(), log_of(13)))
close(13)

# ================================================================ 4. cold, builder
n_cold = len(COLD_MSGS)
check("4 cold: 9 minutes after the look nothing", "a10" not in stk(now0 + 40 * MIN) and len(COLD_MSGS) == n_cold, COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("4 cold: 10 minutes after the look the cold call is asked; it names no taker and the item falls on to the project's builder",
      "a10" in done and len(COLD_MSGS) == n_cold + 1 and mt(10).get("mover") == "team-back" and ho(10).get("to") == "team-back" and ho(10).get("stall") is True, (done, mt(10), ho(10)))
n = len(pushes()); stk(now0 + 3 * H)
check("4 cold: …the next pass ends the silence entry (the mover changed) and nothing more is sent to the old mover", not (entry(10) and LD.quiet(entry(10))) and not [p for p in pushes()[n:] if p[0] == U["home-peer"]], (entry(10), pushes()[n:]))
close(10)
# the last rung: no builder and no cold call, ONE message to the fleet's builder; the item stays with its mover, off the owner's list
clear_records(); set_cfg(cold_call=False)
put(14, project="projects/beta", mover="home-peer3", act=60); cli_row("home-peer3", "idle", IDLE_SINCE)
silence_pass([14]); stk(now0 + 31 * MIN)
check("4 last: ask and look sent, no recovery request yet", len(look_notices("home-peer3", 14)) == 1 and not recovery_pushes("a14"), pushes_to("home-peer3", "a14"))
done = stk(now0 + 41 * MIN + 1)
check("4 last: cold call off and no builder: ONE message asks the fleet's builder; the mover keeps the item; it is not on the owner's list",
      "a14" in done and len(recovery_pushes("a14")) == 1 and bool(ho(14).get("recovery_at")) and mt(14).get("mover") == "home-peer3" and "decision" not in (mt(14).get("needs") or []) and not mt(14).get("ask"), (done, ho(14), mt(14)))
check("4 last: …and nothing more later", stk(now0 + 5 * H) == [] and len(recovery_pushes("a14")) == 1, recovery_pushes("a14"))
close(14); set_cfg()

# ================================================================ 5. activity ends it; a bare confirm and the ladder's notes do not
clear_records(); put(15, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
silence_pass([15]); a15 = entry(15)
d = rd(15); d["activity"] = now0 + 5 * MIN; d["updated"] = now0 + 5 * MIN; d["written_by"] = "home-peer"; (T / "store/a/15.json").write_text(json.dumps(d))     # the mover wrote to it: real activity
done = stk(now0 + 31 * MIN)
check("5 activity: a write that counts before the look ends the entry: no look is sent and the stall table keeps no silence entry", "a15" not in done and not look_notices("home-peer", 15) and not (entry(15) and LD.quiet(entry(15))), (done, entry(15)))
close(15)
clear_records(); put(16, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
silence_pass([16]); d = rd(16); d["confirmed"] = now0 + 5 * MIN; d["written_by_id"] = U["home-peer"]; d["written_by"] = "home-peer"; (T / "store/a/16.json").write_text(json.dumps(d))     # a bare confirm by the mover
done = stk(now0 + 31 * MIN)
check("5 confirm: the mover's bare confirm is no activity: it does not restart the silence, and the look comes on time", "a16" in done and len(look_notices("home-peer", 16)) == 1 and entry(16)["step"] == 2 and LD.quiet(entry(16)), (done, entry(16)))
d = rd(16); d["updated"] = now0 + 32 * MIN; (T / "store/a/16.json").write_text(json.dumps(d))        # a write of the item's version that is not activity (an audit's, a repair's)
n_cold = len(COLD_MSGS)
check("5 confirm: …nor does a write that moves the item's version without activity: the cold call still comes ten minutes after the look", "a16" in stk(now0 + 41 * MIN + 1) and len(COLD_MSGS) == n_cold + 1, (entry(16), COLD_MSGS[-1:]))
close(16)
clear_records(); put(17, act=60, wait_kind="relay"); cli_row("home-peer", "idle", IDLE_SINCE)
check("5 not due: an item on a stored wait is not silent and never enters", silence_pass([17])["findings"] == 0 and entry(17) is None, entry(17))
close(17)
# the item put on a hold after it was asked: not due, its entry dropped
clear_records(); put(18, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
silence_pass([18]); d = rd(18); d["metadata"]["hold"] = True; (T / "store/a/18.json").write_text(json.dumps(d))
stk(now0 + 31 * MIN)
check("5 not due: …put on a hold after the ask, the entry is dropped and nothing is sent", entry(18) is None and not look_notices("home-peer", 18), (entry(18), pushes_to("home-peer", "a18")))
close(18)

# ================================================================ 6. a pane with no turn running starts nothing; an untaken hand-off is still the hand-off audit's
put(20, act=30, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE_SINCE)
check("6 pane: with the switch on, an item whose pane has had no turn for 40 minutes and which is not silent is sent nothing and has no entry", "a20" not in stk(now0 + 1 * MIN) and not (entry(20) or {}).get("step") and not pushes_to("home-peer2", "a20"), (entry(20), pushes_to("home-peer2", "a20")))
check("6 pane: …nor 5 hours later (the silence pass, not the pane, brings an item)", "a20" not in stk(now0 + 5 * H) and not (entry(20) or {}).get("step") and not pushes_to("home-peer2", "a20"), entry(20))
close(20)
put(21, act=2, mover="home-peer", handoff=H_.new_record("home-peer", U["home-peer"], "home-send", IDLE_SINCE + 5 * MIN, delivered_at=IDLE_SINCE + 5 * MIN + 10)); cli_row("home-peer", "idle", IDLE_SINCE)
d = rd(21); d["activity"] = d["updated"] = d["state_updated"] = now0 - 3 * H; (T / "store/a/21.json").write_text(json.dumps(d))
check("6 hand-off: an untaken hand-off is left alone by the silence audit and the stall pass, however quiet", silence_pass([21])["findings"] == 0 and "a21" not in stk(now0 + 1 * MIN) and not pushes_to("home-peer", "a21"), pushes_to("home-peer", "a21"))
check("6 hand-off: …until the hand-off audit brings it (via handoff); the ladder then takes its later rungs here, once, as before",
      server._handoff_tick(now=now0 + 61 * MIN, only=["a21"]) == ["a21"] and (entry(21) or {}).get("via") == "handoff" and (drain() or True) and len(pushes_to("home-peer", "a21")) == 1
      and "a21" not in stk(now0 + 62 * MIN) and "a21" in stk(now0 + 92 * MIN) and len(pushes_to("home-peer", "a21")) == 2, (pushes_to("home-peer", "a21"), entry(21)))
close(21)

# ================================================================ 7. the dates pass: a passed expected time is the same ladder
clear_records()
put(30, act=300, wake=local(now0 - 2 * H)); d = rd(30); d["written_at"] = now0 - 5 * H; (T / "store/a/30.json").write_text(json.dumps(d)); cli_row("home-peer", "idle", IDLE_SINCE)
rd_ = AR.dates_pass(now=now0, items=load(30), anchors={}, env=env(), entered=server._ladder_enter_quiet)
e30 = entry(30)
check("7 dates: an item past its own wake with no write since is sent its message and put on the ladder at the look, the same record as silence",
      rd_["fresh"] == 1 and len(sent) == 1 and sent[0][0] == "home-peer" and e30 and e30.get("via") == "silence" and e30.get("step") == 1 and e30.get("last") == now0 and "past its wake" in log_of(30)[0]["text"], (rd_, sent, e30, log_of(30)))
done = stk(now0 + 31 * MIN)
check("7 dates: …and the look follows 30 minutes later", "a30" in done and len(look_notices("home-peer", 30)) == 1, (done, pushes_to("home-peer", "a30")))
clear_records(); sent.clear()
close(30)
put(31, act=300, wake=local(now0 - 2 * H)); d = rd(31); d["written_at"] = now0 - 5 * H; (T / "store/a/31.json").write_text(json.dumps(d))
AR.dates_pass(now=now0, items=load(31), anchors={}, env=env())
check("7 dates: with the ladder not handed to the pass (the switch off) the item is sent the message and nothing is entered, as before", len(sent) == 1 and entry(31) is None, (sent, entry(31)))
close(31)

# ================================================================ 8. the switch turned off in the middle of a ladder
clear_records(); put(40, act=60, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE_SINCE)
silence_pass([40]); stk(now0 + 31 * MIN)
check("8 mid-ladder: the entry is on the cold call (step 2, silence)", entry(40)["step"] == 2 and LD.quiet(entry(40)), entry(40))
ladder_cfg(True, None); n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("8 silence off, ladder on: the entry still takes its cold call (the ladder reads it as it was made), nothing is sent twice", "a40" in done and len(COLD_MSGS) == n_cold + 1 and len(look_notices("home-peer2", 40)) == 1, (done, COLD_MSGS[-1:]))
close(40)
clear_records(); ladder_cfg(True, True); put(41, act=60, mover="home-peer3"); cli_row("home-peer3", "idle", IDLE_SINCE)
silence_pass([41]); stk(now0 + 31 * MIN)
ladder_cfg(False, True); n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("8 ladder off: the old stall ladder reads the entry in its own table (the look maps to the cold call): the cold call comes, the look is not sent again", "a41" in done and len(COLD_MSGS) == n_cold + 1 and len(look_notices("home-peer3", 41)) == 1, (done, entry(41)))
close(41); ladder_cfg(True, True)

# ================================================================ 9. pure
ent = LD.enter_quiet(None, "m", [1.0, 2.0], 3.0, 100.0, 500.0)
check("9 enter_quiet: an entry on the look, started at the time given, for the activity clock given", ent["via"] == "silence" and ent["step"] == 1 and ent["last"] == 500.0 and ent["act"] == 100.0 and ent["ladder"] is True and ent["mover"] == "m" and ent["ver"] == [1.0, 2.0], ent)
carry = LD.enter_quiet({"cold_at": 9.0, "tried": ["x"], "kept": 1.0}, "m", [1.0, 2.0], 0.0, 1.0, 2.0)
check("9 enter_quiet: what outlives an episode (the cold call's bound) is kept; a `kept` mark is not", carry.get("cold_at") == 9.0 and carry.get("tried") == ["x"] and "kept" not in carry, carry)
same = lambda a, b: a == b
check("9 quiet_over: activity later than the entry's, or another mover, ends it; the same activity and mover do not", LD.quiet_over(ent, "m", same, 100.0) is False and LD.quiet_over(ent, "m", same, 100.5) is True and LD.quiet_over(ent, "n", same, 100.0) is True, None)
check("9 via_of: silence, handoff, and anything else is stall", LD.via_of({"via": "silence"}) == "silence" and LD.via_of({"via": "handoff"}) == "handoff" and LD.via_of({"via": "x"}) == "stall" and LD.via_of(None) == "stall" and "silence" in LD.VIAS, None)
check("9 unwind: the old table reads a silence entry without its marks (the look maps to the cold call)", LD.unwind(ent) == {"mover": "m", "ver": [1.0, 2.0], "conf": 3.0, "step": 1, "last": 500.0}, LD.unwind(ent))
check("9 action: the look is due 30 minutes after the ask when the pane is idle, not before; the cold call 10 minutes after the look", LD.action(ent, "idle", 1.0, 0.0, 500.0 + 29 * 60, 10.0) == "" and LD.action(ent, "idle", 1.0, 0.0, 500.0 + 30 * 60, 10.0) == "look"
      and LD.action(ent, "busy", 1.0, 0.0, 500.0 + 3600, 10.0) == "" and LD.action({**ent, "step": 2, "last": 3000.0}, "idle", 1.0, 0.0, 3000.0 + 599, 10.0) == "" and LD.action({**ent, "step": 2, "last": 3000.0}, "idle", 1.0, 0.0, 3000.0 + 600, 10.0) == "cold", None)

# ================================================================ 10. a background mover whose pane is busy is still chased: the evidence is the item's work line, not the pane
def set_gone(name, hours=2):
    """The heartbeat shows `name` gone for `hours` on an online machine: its pane is dead, not live (the other rows are as they were)."""
    d_ = json.loads((T / "fleet/a/sessions.json").read_text()); d_[U[name]]["gone"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * H))
    (T / "fleet/a/sessions.json").write_text(json.dumps(d_))
def set_live(name):
    d_ = json.loads((T / "fleet/a/sessions.json").read_text()); d_[U[name]].pop("gone", None); (T / "fleet/a/sessions.json").write_text(json.dumps(d_))
def work_line(i, state, ts, agent="x"):
    d_ = rd(i); d_["metadata"]["work"] = [{"id": "build", "text": "building the fix", "state": state, "agent": agent, "ts": ts}]; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
set_live("home-docs"); set_live("team-back")
ladder_cfg(True, True)
# 10a. the builder's pane is busy (a turn, or subagents, running) and the item is past due: the look is sent all the same, in the new wording
clear_records(); put(50, act=300, mover="team-back", wake=local(now0 - 2 * H)); d = rd(50); d["written_at"] = now0 - 5 * H; (T / "store/a/50.json").write_text(json.dumps(d)); cli_row("team-back", "busy", now0 - 20 * MIN)
AR.dates_pass(now=now0, items=load(50), anchors={}, env=env(), entered=server._ladder_enter_quiet)
check("10a busy builder: the past-due item is on the ladder at the look", (entry(50) or {}).get("step") == 1 and LD.quiet(entry(50)), entry(50))
check("10a busy builder: 29 minutes after the ask nothing is sent", "a50" not in stk(now0 + 29 * MIN) and not look_notices("team-back", 50), pushes_to("team-back", "a50"))
done = stk(now0 + 31 * MIN)
n50 = look_notices("team-back", 50)
check("10a busy builder: 31 minutes after the ask, with the pane busy, the look is sent and the entry goes on to the cold call", "a50" in done and len(n50) == 1 and entry(50)["step"] == 2, (done, pushes_to("team-back", "a50"), entry(50)))
check("10a look wording: it says nothing was written for N minutes (since the item's last write) and does not claim the pane has no turn running",
      bool(n50) and "nothing written for 5 hours 31 minutes" in n50[0][1] and "no turn running" not in n50[0][1], n50)
check("10a look wording: …and the History line says the same", any("nothing was written to it for 5 hours 31 minutes" in x["text"] and "no turn running" not in x["text"] for x in log_of(50)[1:]), log_of(50))
# a live background pane stops at the look: no cold call, no builder, however long it stays busy
n_cold = len(COLD_MSGS)
check("10c live pane: 10 minutes after the look the cold call is not made, and not 5 hours later either (the pane is live)", "a50" not in stk(now0 + 42 * MIN) and "a50" not in stk(now0 + 5 * H) and len(COLD_MSGS) == n_cold and mt(50).get("mover") == "team-back", (COLD_MSGS[n_cold:], mt(50)))
close(50)
# 10b. a CI watch (a background shell) does not exempt the builder either
clear_records(); put(51, act=60, mover="team-back"); cli_row("team-back", "idle", IDLE_SINCE)
silence_pass([51]); cli_row("team-back", "shell", now0 + 5 * MIN)
done = stk(now0 + 31 * MIN)
check("10b shell builder: a builder whose pane shows a background shell (a CI watch) gets the look", "a51" in done and len(look_notices("team-back", 51)) == 1, (done, pushes_to("team-back", "a51")))
close(51)
# 10d. the evidence: a work line in progress changed within 90 minutes holds the ladder; an older line, or one not in progress, does not
clear_records(); put(52, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
silence_pass([52]); work_line(52, "in progress", now0 + 20 * MIN, "home-docs")
check("10d work line: a work line in progress changed 11 minutes before the look: the look is not sent", "a52" not in stk(now0 + 31 * MIN) and not look_notices("home-docs", 52) and entry(52)["step"] == 1, (entry(52), pushes_to("home-docs", "a52")))
check("10d work line: …still held 89 minutes after the line was changed", "a52" not in stk(now0 + 20 * MIN + 89 * MIN) and not look_notices("home-docs", 52), pushes_to("home-docs", "a52"))
check("10d work line: …91 minutes after the line was changed the look is sent", "a52" in stk(now0 + 20 * MIN + 91 * MIN) and len(look_notices("home-docs", 52)) == 1, pushes_to("home-docs", "a52"))
close(52)
clear_records(); put(53, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
silence_pass([53]); work_line(53, "assigned", now0 + 20 * MIN, "home-docs")
check("10d work line: a line that is only assigned is no evidence of work: the look is sent", "a53" in stk(now0 + 31 * MIN) and len(look_notices("home-docs", 53)) == 1, pushes_to("home-docs", "a53"))
close(53)
# 10e. a background mover whose pane is not live is chased on: the cold call, then the builder
clear_records(); put(54, act=60, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
silence_pass([54]); stk(now0 + 31 * MIN); no_row("home-docs"); set_gone("home-docs")
n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("10e dead pane: with the pane gone (no registry row, the heartbeat shows it gone for hours) the cold call is made 10 minutes after the look and the item falls to the builder", "a54" in done and len(COLD_MSGS) == n_cold + 1 and mt(54).get("mover") == "team-back", (done, COLD_MSGS[n_cold:], mt(54)))
close(54); set_live("home-docs")
# 10f. a builder is never handed its own item: the last rung is the one message to the fleet's builder
clear_records(); set_cfg(cold_call=False); put(55, act=60, mover="team-back"); cli_row("team-back", "idle", IDLE_SINCE)
silence_pass([55]); stk(now0 + 31 * MIN); no_row("team-back"); set_gone("team-back")
done = stk(now0 + 41 * MIN + 1)
check("10f builder mover: with its pane gone, the builder rung does not hand the item to the builder itself: ONE message asks the fleet's builder and the item stays with its mover",
      "a55" in done and mt(55).get("mover") == "team-back" and len(recovery_pushes("a55")) == 1 and bool(ho(55).get("recovery_at")) and not [x for x in pushes_to("team-back", "a55") if "is handed to you by" in x[1]], (done, ho(55), recovery_pushes("a55"), mt(55).get("mover")))
close(55); set_live("team-back"); set_cfg()
# 10g. one notice per agent per pass: two items of one background agent due for the look at once get one notice a pass
clear_records(); put(56, act=60, mover="home-docs"); put(57, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
silence_pass([56, 57]); n0 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
done1 = stk(now0 + 31 * MIN); n1 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
done2 = stk(now0 + 31 * MIN + 60); n2 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
check("10g one notice a pass: the first pass sends one look to the agent, the next pass the other, and no item gets two", n0 == 0 and len(done1) == 1 and n1 == 1 and len(done2) == 1 and n2 == 2 and len(look_notices("home-docs", 56)) == 1 and len(look_notices("home-docs", 57)) == 1, (done1, done2, pushes_to("home-docs")))
close(56, 57)
# 10h. a front agent is as before: a pane with a turn running waits
clear_records(); put(58, act=60, mover="home-front"); cli_row("home-front", "idle", IDLE_SINCE)
silence_pass([58]); cli_row("home-front", "busy", now0 + 20 * MIN)
check("10h front agent: a front agent with a turn running at the look is left alone", "a58" not in stk(now0 + 35 * MIN) and entry(58)["step"] == 1, entry(58))
close(58)
# 10i. the ladder a pane with no turn running brought (`silence` off): the ask waits for the pane, the look after it does not, and a background agent's look is in the same wording
ladder_cfg(True, None); clear_records()
put(59, act=30, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
done = stk(now0 + 1)
check("10i pane-triggered: the ask is the stall notice, sent to an idle pane", "a59" in done and len(stall_notices("home-docs", 59)) == 1 and LD.via_of(entry(59)) == "stall" and entry(59)["step"] == 1, (done, entry(59)))
cli_row("home-docs", "busy", now0 + 5 * MIN)
check("10i pane-triggered: 29 minutes after the ask the busy pane is left alone", "a59" not in stk(now0 + 1 + 29 * MIN), entry(59))
done = stk(now0 + 1 + 31 * MIN)
check("10i pane-triggered: 31 minutes after the ask, the pane busy, the background agent's look is sent in the item's wording (nothing written), not the pane's",
      "a59" in done and len(look_notices("home-docs", 59)) == 1 and len(stall_notices("home-docs", 59)) == 1 and entry(59)["step"] == 2, (done, pushes_to("home-docs", "a59"), entry(59)))
close(59); ladder_cfg(True, True)
# 10k. the hold is the mover's own work line: a line in progress that another agent left on the item holds nothing
clear_records(); put(60, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
silence_pass([60]); work_line(60, "in progress", now0 + 20 * MIN, "team-back")
check("10k other agent's line: a recent line in progress written by another agent does not hold the ladder: the look is sent", "a60" in stk(now0 + 31 * MIN) and len(look_notices("home-docs", 60)) == 1, (entry(60), pushes_to("home-docs", "a60")))
close(60)
clear_records(); put(61, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
silence_pass([61]); work_line(61, "in progress", now0 + 20 * MIN, "home-docs")
check("10k mover's own line: the same line written by the mover holds it", "a61" not in stk(now0 + 31 * MIN) and not look_notices("home-docs", 61) and entry(61)["step"] == 1, (entry(61), pushes_to("home-docs", "a61")))
close(61)
from stackshot.audit import silence as SLN
it_ = {"metadata": {"work": [{"id": "w", "text": "t", "state": "in progress", "agent": "team-back", "ts": 1000.0}]}}
check("10k pure: subagent_running counts a line of any agent without a mover, and only the mover's own line with one",
      SLN.subagent_running(it_, 1100.0) and SLN.subagent_running(it_, 1100.0, "team-back", server._ho_same) and not SLN.subagent_running(it_, 1100.0, "home-docs", server._ho_same), None)
# 10l. a heartbeat that is empty or unreadable says nothing about the pane: a background mover with no registry row is taken as live (not cold-called, not handed on)
clear_records(); put(62, act=60, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
silence_pass([62]); stk(now0 + 31 * MIN); no_row("home-docs")
hb_ = (T / "fleet/a/sessions.json").read_text(); (T / "fleet/a/sessions.json").write_text("{}")
n_cold = len(COLD_MSGS)
try:
    done = stk(now0 + 41 * MIN + 1); done2 = stk(now0 + 5 * H)
    check("10l empty heartbeat: with no registry row and an empty heartbeat the cold call is not made and the item stays with its mover", "a62" not in done and "a62" not in done2 and len(COLD_MSGS) == n_cold and mt(62).get("mover") == "home-docs", (done, done2, COLD_MSGS[n_cold:], mt(62)))
    (T / "fleet/a/sessions.json").write_text("not json")
    check("10l unreadable heartbeat: the same", "a62" not in stk(now0 + 6 * H) and len(COLD_MSGS) == n_cold and mt(62).get("mover") == "home-docs", (COLD_MSGS[n_cold:], mt(62)))
finally:
    (T / "fleet/a/sessions.json").write_text(hb_)
close(62)
# 10j. pure: ladder.action for a background mover
ent2 = LD.enter_quiet(None, "m", [1.0, 2.0], 3.0, 100.0, 500.0)
bg = lambda rec, st, now, **kw: LD.action(rec, st, 1.0, 0.0, now, 10.0, 30.0, background=True, **kw)
check("10j action: a background mover's look is due 30 minutes after the ask whatever its pane shows (busy, shell, idle, none), not before",
      all(bg(ent2, st, 500.0 + 29 * 60, live=True) == "" for st in ("busy", "shell", "idle", "")) and all(bg(ent2, st, 500.0 + 30 * 60, live=True) == "look" for st in ("busy", "shell", "idle", "")), None)
cold_rec = {**ent2, "step": 2, "last": 3000.0}
check("10j action: …a live pane stops there (no cold call, no builder); a pane that is not live goes on, whatever the registry shows",
      bg(cold_rec, "busy", 3000.0 + 600, live=True) == "" and bg({**ent2, "step": 3, "last": 3000.0}, "idle", 3000.0 + 600, live=True) == ""
      and bg(cold_rec, "", 3000.0 + 599, live=False) == "" and bg(cold_rec, "", 3000.0 + 600, live=False) == "cold" and bg({**ent2, "step": 3, "last": 3000.0}, "busy", 3000.0 + 600, live=False) == "builder", None)
check("10m action: an entry the hand-off audit marked gone (two failed pushes, no delivery) reaches the cold call and the builder even when the heartbeat shows the pane live",
      bg({**cold_rec, "gone": True}, "idle", 3000.0 + 600, live=True) == "cold" and bg({**ent2, "step": 3, "last": 3000.0, "gone": True}, "idle", 3000.0 + 600, live=True) == "builder"
      and bg({**cold_rec, "gone": True}, "idle", 3000.0 + 599, live=True) == "" and bg(cold_rec, "idle", 3000.0 + 600, live=True) == "", None)
check("10j action: a mover that is not background keeps the pane rule (busy waits)", LD.action(ent2, "busy", 1.0, 0.0, 500.0 + 3600, 10.0) == "" and LD.action(ent2, "busy", 1.0, 0.0, 500.0 + 3600, 10.0, 30.0, live=True) == "", None)
check("10j action: the first rung of a pane-triggered ladder (the ask) still waits for the pane to have no turn running, background or not",
      LD.action({"mover": "m", "step": 0, "last": 0.0}, "busy", 1.0, 0.0, 5000.0, 10.0, 30.0, background=True, live=True) == "" and LD.action({"mover": "m", "step": 0, "last": 0.0}, "idle", 1.0, 0.0, 5000.0, 10.0, 30.0, background=True, live=True) == "ask", None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
