"""Scenario test for the one ladder's quiet entry: with `[ladder] enabled` the dates pass brings an item to the one ladder, and a pane with no turn running no longer does (ladder.py, audit_run.dates_pass `entered`,
service/ladder.py ladder_enter_quiet and ladder_quiet_look, service/stall_tick.py stall_tick). The file once also tested the retired 45-minute news ask, the other way in ( `enter` below makes the entry the dates pass makes after its message). Fixture items,
panes that are files in a temp folder, messages recorded by a fake push, a fake clock (every pass is given its `now`), no live store, no network, no model call.

  1  the switch: `[ladder] enabled` alone is the whole switch (there is no `silence` key); the dates tick gives the ladder to the dates pass only then; with the one ladder off the stall pass starts a ladder from a pane with no
     turn running, as before
  2  the ask: the message the dates pass sent is the ask and puts the item on the ladder at the look, its clock started then, a History line saying so
  3  the look: nothing before `look_minutes` (30); then, with the mover's pane idle, the mover is told once more (a front agent gets the History line alone); a pane with a turn running is left alone until it ends
  4  cold, builder: ten minutes after the look the cold call is asked; with no taker the item goes to the project's builder, and the entry ends with the mover change; with no builder and no cold call the last rung
     is ONE message to the fleet's builder, the item staying with its mover and off the owner's list
  5  activity ends it: a write that counts (the activity clock moves) before the look ends the entry; a bare confirm and the ladder's own notes do not, and the ladder goes on
  6  a pane with no turn running starts no ladder (with the one ladder on); an untaken hand-off is still the hand-off audit's, and its ladder is taken here as before
  7  the dates pass: an item past its expected time with no write since is sent its message and put on the same ladder
  8  the whole one-ladder flag turned off in the middle of a ladder: the entry is read in the old table (nothing is repeated, the builder rung stays reachable)
  9  pure: ladder.enter_quiet, quiet_over, via_of, unwind, action
 10  a background mover whose pane is busy (or shows a background shell) is still chased past the ask: the look is sent in the "nothing written for N minutes" wording; a work line in progress changed
     within 90 minutes holds the ladder; a live pane gets no cold call and no builder (its silence goes to -main, section 11), a pane that is not live goes on to the cold call and the builder (never the builder itself); one notice per agent per pass;
     a front agent keeps the pane rule; ladder.action for a background mover;
     only the mover's own work line holds the ladder; an empty or unreadable heartbeat is unknown (live); a gone entry reaches the cold call whatever the heartbeat shows
 11  a live background mover that stays silent after the look is told to the project's -main agent: a notice to the project's -main agent `minutes` after the look (marked for the owner, naming the silence, asking for a nudge or a
     different mover and saying how to stop the repeats), the same notice again only every `ladder.MAIN_EVERY`, never one per pass; ONE notice per -main agent per pass, listing every item due for it; a front mover, a fresh work line and
     a mover whose pane is not live (the cold call, the builder) get none; a project with no -main agent gets the History line alone; a mover that is the project's -main agent itself is told nothing (nobody is above it) and its History line and the note of its save say so

    tests/run-suite ladder_silence       -> exit 0 / 1"""
import contextlib, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="laddersil-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import handoff as H_; from stackshot.waits import stall as S; from stackshot.waits import ladder as LD; from stackshot.audit import audit_run as AR; from stackshot.audit import audit
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import ladder as ladder_svc, stall as stall_svc, stall_tick as stalltick_svc
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake"):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
    while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def main_recovery_pushes(gid): return [p for p in pushes_to("home-beta-front", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, marked for the owner
def look_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "nothing written for" in p[1]]
def stall_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "have had no turn running" in p[1]]
def set_cfg(**kw): server._cfg.CFG["model"] = dict(kw)
def ladder_cfg(enabled=True, **kw):
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, **kw}.items() if v is not None}
set_cfg(); server._cfg.CFG["stall"] = {}
server._cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"
COLD_MSGS = []
def cold(answer, status="ok"):
    def run(msg):
        COLD_MSGS.append(msg)
        return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    hcold_svc.COLD_RUNNER = run
cold("no json at all here")
def cli_row(who, status, at):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
def no_row(who): (T / f"cli/{os.getpid()}-{who}.json").unlink(missing_ok=True)
handoff_svc.CLI_SESSIONS = T / "cli"
stall_svc.stall_since(B)
def stk(at):
    """One stall pass at `at` (the 20-second gate reset), the threads it started finished → the items it acted on."""
    stall_svc.STALL_LAST[0] = 0.0
    out = stalltick_svc.stall_tick(at); drain()
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
def enter(ids, at=None):
    """The dates pass's entry for these items at `at`: what `audit_run.dates_pass` does for each fresh finding that reached its mover (`entered=ladder_svc.ladder_enter_quiet`), without the pass's own message. → {"entered": n}."""
    now_ = now0 if at is None else at; n = 0
    for gid, it in load(*ids).items():
        n += bool(ladder_svc.ladder_enter_quiet(gid, str((it.get("metadata") or {}).get("mover") or ""), now_, "no activity"))
    return {"entered": n}
def entry(i): return stall_svc.stall_load().get(f"a{i}")
IDLE_SINCE = now0 - 50 * MIN        # the pane went idle then (the silent item's last activity was 60 minutes before now0)

# ================================================================ 1. the switch
ladder_cfg(False)
check("1 off: with `enabled` false the one ladder is off", not ladder_svc.ladder_on(), None)
ladder_cfg(True)
check("1 on: `enabled` alone turns the one ladder on, and the look is 30 minutes", ladder_svc.ladder_on() and ladder_svc.ladder_look() == 30.0, None)
spy = []
_real_dates = AR.dates_pass
AR.dates_pass = lambda **kw: spy.append(kw.get("entered")) or {}
try:
    server._dates_expected_tick()
    on_spy = list(spy); spy.clear()
    ladder_cfg(False); server._dates_expected_tick()
    off_spy = list(spy); spy.clear()
finally:
    AR.dates_pass = _real_dates
ladder_cfg(True)
check("1 wiring: the dates tick gives the ladder to the dates pass only with the one ladder on", [e is ladder_svc.ladder_enter_quiet for e in on_spy] == [True] and off_spy == [None], (on_spy, off_spy))
# a pane with no turn running starts a ladder with the one ladder off, and none with it on
put(1, act=30); cli_row("home-peer", "idle", IDLE_SINCE)
ladder_cfg(False)
done = stk(now0 + 1)
check("1 off: with the one ladder off an item whose pane has had no turn for 10 minutes gets the stall notice and a via=stall entry, as before", "a1" in done and len(stall_notices("home-peer", 1)) == 1 and LD.via_of(entry(1)) == "stall", (done, pushes(), entry(1)))
close(1); stall_svc.stall_save({})
ladder_cfg(True)

# ================================================================ 2. the ask
clear_records()
put(10, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
r = enter([10])
e10 = entry(10)
check("2 ask: the item is on the ladder at the look: via silence (the stored value keeps its name), step 1, started now, for this stretch (the activity clock), the mover and the version noted",
      r["entered"] == 1 and e10 and e10.get("via") == "silence" and e10.get("step") == 1 and e10.get("last") == now0 and e10.get("act") == rd(10)["activity"] and e10.get("mover") == "home-peer" and e10.get("ladder") is True
      and LD.quiet(e10), (r, e10))
check("2 ask: …a History line says so, and the item is as it was (no write by a session: version and activity unmoved)",
      len(log_of(10)) == 1 and "asked for news" in log_of(10)[0]["text"] and rd(10)["activity"] == now0 - 60 * MIN and rd(10)["updated"] == now0 - 60 * MIN, (log_of(10), rd(10)))

# ================================================================ 3. the look
no_msgs = lambda: not look_notices("home-peer", 10)
check("3 look: 29 minutes after the ask nothing is sent", "a10" not in stk(now0 + 29 * MIN) and no_msgs(), pushes_to("home-peer", "a10"))
done = stk(now0 + 31 * MIN)
check("3 look: 31 minutes after the ask, the pane having no turn running, the mover is told once more, in the silence wording, with the step on the item and the ladder on the cold call",
      "a10" in done and len(look_notices("home-peer", 10)) == 1 and "nothing written for" in look_notices("home-peer", 10)[0][1] and entry(10)["step"] == 2 and entry(10)["last"] == now0 + 31 * MIN
      and len(log_of(10)) == 2 and "nothing was written to it" in log_of(10)[1]["text"] and not stall_notices("home-peer", 10), (done, pushes_to("home-peer", "a10"), entry(10), log_of(10)))
check("3 look: …the stall wording (a pane with no turn for N minutes) is not used for an item the dates pass brought", not stall_notices("home-peer", 10), pushes_to("home-peer", "a10"))
# a pane with a turn running at the look is left alone; the look comes when the turn ends
clear_records()
put(12, act=60, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE_SINCE)
enter([12]); cli_row("home-peer2", "busy", now0 + 20 * MIN)
check("3 look: a turn started after the ask: 35 minutes on, nothing is sent", "a12" not in stk(now0 + 35 * MIN) and not look_notices("home-peer2", 12), pushes_to("home-peer2", "a12"))
cli_row("home-peer2", "idle", now0 + 36 * MIN)
check("3 look: …the turn ends: the look comes at once", "a12" in stk(now0 + 37 * MIN) and len(look_notices("home-peer2", 12)) == 1, pushes_to("home-peer2", "a12"))
close(12)
# a front agent's item: the look is a History line alone
clear_records(); put(13, act=60, mover="home-front"); cli_row("home-front", "idle", IDLE_SINCE)
enter([13]); done = stk(now0 + 31 * MIN)
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
enter([14]); stk(now0 + 31 * MIN)
check("4 last: ask and look sent, no recovery request yet", len(look_notices("home-peer3", 14)) == 1 and not main_recovery_pushes("a14"), pushes_to("home-peer3", "a14"))
done = stk(now0 + 41 * MIN + 1)
check("4 last: cold call off and no builder: ONE message asks the project's -main agent (no background agent to build); the mover keeps the item; it is not on the owner's list",
      "a14" in done and len(main_recovery_pushes("a14")) == 1 and bool(ho(14).get("recovery_at")) and mt(14).get("mover") == "home-peer3" and "decision" not in (mt(14).get("needs") or []) and not mt(14).get("ask"), (done, ho(14), mt(14)))
check("4 last: …and nothing more later", stk(now0 + 5 * H) == [] and len(main_recovery_pushes("a14")) == 1, main_recovery_pushes("a14"))
close(14); set_cfg()

# ================================================================ 5. activity ends it; a bare confirm and the ladder's notes do not
clear_records(); put(15, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
enter([15]); a15 = entry(15)
d = rd(15); d["activity"] = now0 + 5 * MIN; d["updated"] = now0 + 5 * MIN; d["written_by"] = "home-peer"; (T / "store/a/15.json").write_text(json.dumps(d))     # the mover wrote to it: real activity
done = stk(now0 + 31 * MIN)
check("5 activity: a write that counts before the look ends the entry: no look is sent and the stall table keeps no silence entry", "a15" not in done and not look_notices("home-peer", 15) and not (entry(15) and LD.quiet(entry(15))), (done, entry(15)))
close(15)
clear_records(); put(16, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
enter([16]); d = rd(16); d["confirmed"] = now0 + 5 * MIN; d["written_by_id"] = U["home-peer"]; d["written_by"] = "home-peer"; (T / "store/a/16.json").write_text(json.dumps(d))     # a bare confirm by the mover
done = stk(now0 + 31 * MIN)
check("5 confirm: the mover's bare confirm is no activity: it does not restart the silence, and the look comes on time", "a16" in done and len(look_notices("home-peer", 16)) == 1 and entry(16)["step"] == 2 and LD.quiet(entry(16)), (done, entry(16)))
d = rd(16); d["updated"] = now0 + 32 * MIN; (T / "store/a/16.json").write_text(json.dumps(d))        # a write of the item's version that is not activity (an audit's, a repair's)
n_cold = len(COLD_MSGS)
check("5 confirm: …nor does a write that moves the item's version without activity: the cold call still comes ten minutes after the look", "a16" in stk(now0 + 41 * MIN + 1) and len(COLD_MSGS) == n_cold + 1, (entry(16), COLD_MSGS[-1:]))
close(16)
clear_records(); put(17, act=60, wait_kind="relay"); cli_row("home-peer", "idle", IDLE_SINCE)
check("5 not due: an item on a stored wait never enters", enter([17])["entered"] == 0 and entry(17) is None, entry(17))
close(17)
# the item put on a hold after it was asked: not due, its entry dropped
clear_records(); put(18, act=60); cli_row("home-peer", "idle", IDLE_SINCE)
enter([18]); d = rd(18); d["metadata"]["hold"] = True; d["metadata"].pop("phase", None); d["metadata"].pop("waits_on", None); d["metadata"]["wake"] = local(now0 + 5 * H); (T / "store/a/18.json").write_text(json.dumps(d))
stk(now0 + 31 * MIN)
check("5 not due: …put on a hold after the ask, the entry is dropped and nothing is sent", entry(18) is None and not look_notices("home-peer", 18), (entry(18), pushes_to("home-peer", "a18")))
close(18)

# ================================================================ 6. a pane with no turn running starts nothing; an untaken hand-off is still the hand-off audit's
put(20, act=30, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE_SINCE)
check("6 pane: with the one ladder on, an item whose pane has had no turn for 40 minutes and which is not silent is sent nothing and has no entry", "a20" not in stk(now0 + 1 * MIN) and not (entry(20) or {}).get("step") and not pushes_to("home-peer2", "a20"), (entry(20), pushes_to("home-peer2", "a20")))
check("6 pane: …nor 5 hours later (the dates pass, not the pane, brings an item)", "a20" not in stk(now0 + 5 * H) and not (entry(20) or {}).get("step") and not pushes_to("home-peer2", "a20"), entry(20))
close(20)
put(21, act=2, mover="home-peer", handoff=H_.new_record("home-peer", U["home-peer"], "home-send", IDLE_SINCE + 5 * MIN, delivered_at=IDLE_SINCE + 5 * MIN + 10)); cli_row("home-peer", "idle", IDLE_SINCE)
d = rd(21); d["activity"] = d["updated"] = d["state_updated"] = now0 - 3 * H; (T / "store/a/21.json").write_text(json.dumps(d))
check("6 hand-off: an untaken hand-off is left alone by the stall pass, however quiet", "a21" not in stk(now0 + 1 * MIN) and not pushes_to("home-peer", "a21"), pushes_to("home-peer", "a21"))
check("6 hand-off: …until the hand-off audit brings it (via handoff); the ladder then takes its later rungs here, once, as before",
      handoff_svc.handoff_tick(now=now0 + 61 * MIN, only=["a21"]) == ["a21"] and (entry(21) or {}).get("via") == "handoff" and (drain() or True) and len(pushes_to("home-peer", "a21")) == 1
      and "a21" not in stk(now0 + 62 * MIN) and "a21" in stk(now0 + 92 * MIN) and len(pushes_to("home-peer", "a21")) == 2, (pushes_to("home-peer", "a21"), entry(21)))
close(21)

# ================================================================ 7. the dates pass: a passed expected time is the same ladder
clear_records()
put(30, act=300, wake=local(now0 - 2 * H)); d = rd(30); d["written_at"] = now0 - 5 * H; (T / "store/a/30.json").write_text(json.dumps(d)); cli_row("home-peer", "idle", IDLE_SINCE)
rd_ = AR.dates_pass(now=now0, items=load(30), anchors={}, env=env(), entered=ladder_svc.ladder_enter_quiet)
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

# ================================================================ 8. the one ladder turned off in the middle of a ladder
clear_records(); ladder_cfg(True); put(41, act=60, mover="home-peer3"); cli_row("home-peer3", "idle", IDLE_SINCE)
enter([41]); stk(now0 + 31 * MIN)
check("8 mid-ladder: the entry is on the cold call (step 2, via silence)", entry(41)["step"] == 2 and LD.quiet(entry(41)), entry(41))
ladder_cfg(False); n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("8 ladder off: the old stall ladder reads the entry in its own table (the look maps to the cold call): the cold call comes, the look is not sent again", "a41" in done and len(COLD_MSGS) == n_cold + 1 and len(look_notices("home-peer3", 41)) == 1, (done, entry(41)))
close(41); ladder_cfg(True)

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
ladder_cfg(True)
# 10a. the builder's pane is busy (a turn, or subagents, running) and the item is past due: the look is sent all the same, in the new wording
clear_records(); put(50, act=300, mover="team-back", wake=local(now0 - 2 * H)); d = rd(50); d["written_at"] = now0 - 5 * H; (T / "store/a/50.json").write_text(json.dumps(d)); cli_row("team-back", "busy", now0 - 20 * MIN)
AR.dates_pass(now=now0, items=load(50), anchors={}, env=env(), entered=ladder_svc.ladder_enter_quiet)
check("10a busy builder: the past-due item is on the ladder at the look", (entry(50) or {}).get("step") == 1 and LD.quiet(entry(50)), entry(50))
check("10a busy builder: 29 minutes after the ask nothing is sent", "a50" not in stk(now0 + 29 * MIN) and not look_notices("team-back", 50), pushes_to("team-back", "a50"))
done = stk(now0 + 31 * MIN)
n50 = look_notices("team-back", 50)
check("10a busy builder: 31 minutes after the ask, with the pane busy, the look is sent and the entry goes on to the cold call", "a50" in done and len(n50) == 1 and entry(50)["step"] == 2, (done, pushes_to("team-back", "a50"), entry(50)))
check("10a look wording: it says nothing was written for N minutes (since the item's last write) and does not claim the pane has no turn running",
      bool(n50) and "nothing written for 5 hours 31 minutes" in n50[0][1] and "no turn running" not in n50[0][1], n50)
check("10a look wording: …and the History line says the same", any("nothing was written to it for 5 hours 31 minutes" in x["text"] and "no turn running" not in x["text"] for x in log_of(50)[1:]), log_of(50))
# a live background pane gets no cold call and no builder, however long it stays busy (its silence goes to -main instead: section 11)
n_cold = len(COLD_MSGS)
stk(now0 + 42 * MIN); stk(now0 + 5 * H)
check("10c live pane: 10 minutes after the look the cold call is not made, and not 5 hours later either (the pane is live: the silence goes to -main, section 11)", len(COLD_MSGS) == n_cold and mt(50).get("mover") == "team-back" and entry(50)["step"] == 2, (COLD_MSGS[n_cold:], mt(50), entry(50)))
close(50)
# 10b. a CI watch (a background shell) does not exempt the builder either
clear_records(); put(51, act=60, mover="team-back"); cli_row("team-back", "idle", IDLE_SINCE)
enter([51]); cli_row("team-back", "shell", now0 + 5 * MIN)
done = stk(now0 + 31 * MIN)
check("10b shell builder: a builder whose pane shows a background shell (a CI watch) gets the look", "a51" in done and len(look_notices("team-back", 51)) == 1, (done, pushes_to("team-back", "a51")))
close(51)
# 10d. the evidence: a work line in progress changed within 90 minutes holds the ladder; an older line, or one not in progress, does not
clear_records(); put(52, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([52]); work_line(52, "in progress", now0 + 20 * MIN, "home-docs")
check("10d work line: a work line in progress changed 11 minutes before the look: the look is not sent", "a52" not in stk(now0 + 31 * MIN) and not look_notices("home-docs", 52) and entry(52)["step"] == 1, (entry(52), pushes_to("home-docs", "a52")))
check("10d work line: …still held 89 minutes after the line was changed", "a52" not in stk(now0 + 20 * MIN + 89 * MIN) and not look_notices("home-docs", 52), pushes_to("home-docs", "a52"))
check("10d work line: …91 minutes after the line was changed the look is sent", "a52" in stk(now0 + 20 * MIN + 91 * MIN) and len(look_notices("home-docs", 52)) == 1, pushes_to("home-docs", "a52"))
close(52)
clear_records(); put(53, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([53]); work_line(53, "assigned", now0 + 20 * MIN, "home-docs")
check("10d work line: a line that is only assigned is no evidence of work: the look is sent", "a53" in stk(now0 + 31 * MIN) and len(look_notices("home-docs", 53)) == 1, pushes_to("home-docs", "a53"))
close(53)
# 10e. a background mover whose pane is not live is chased on: the cold call, then the builder
clear_records(); put(54, act=60, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
enter([54]); stk(now0 + 31 * MIN); no_row("home-docs"); set_gone("home-docs")
n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("10e dead pane: with the pane gone (no registry row, the heartbeat shows it gone for hours) the cold call is made 10 minutes after the look and the item falls to the builder", "a54" in done and len(COLD_MSGS) == n_cold + 1 and mt(54).get("mover") == "team-back", (done, COLD_MSGS[n_cold:], mt(54)))
close(54); set_live("home-docs")
# 10f. a builder is never handed its own item: the last rung is the one message to the fleet's builder
clear_records(); set_cfg(cold_call=False); put(55, act=60, mover="team-back"); cli_row("team-back", "idle", IDLE_SINCE)
enter([55]); stk(now0 + 31 * MIN); no_row("team-back"); set_gone("team-back")
done = stk(now0 + 41 * MIN + 1)
check("10f builder mover: with its pane gone, the builder rung does not hand the item to the builder itself: ONE message asks the fleet's builder and the item stays with its mover",
      "a55" in done and mt(55).get("mover") == "team-back" and len(recovery_pushes("a55")) == 1 and bool(ho(55).get("recovery_at")) and not [x for x in pushes_to("team-back", "a55") if "is handed to you by" in x[1]], (done, ho(55), recovery_pushes("a55"), mt(55).get("mover")))
close(55); set_live("team-back"); set_cfg()
# 10g. one notice per agent per pass: two items of one background agent due for the look at once get one notice a pass
clear_records(); put(56, act=60, mover="home-docs"); put(57, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([56, 57]); n0 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
done1 = stk(now0 + 31 * MIN); n1 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
done2 = stk(now0 + 31 * MIN + 60); n2 = len(look_notices("home-docs", 56)) + len(look_notices("home-docs", 57))
check("10g one notice a pass: the first pass sends one look to the agent, the next pass the other, and no item gets two", n0 == 0 and len(done1) == 1 and n1 == 1 and len(done2) == 1 and n2 == 2 and len(look_notices("home-docs", 56)) == 1 and len(look_notices("home-docs", 57)) == 1, (done1, done2, pushes_to("home-docs")))
close(56, 57)
# 10h. a front agent is as before: a pane with a turn running waits
clear_records(); put(58, act=60, mover="home-front"); cli_row("home-front", "idle", IDLE_SINCE)
enter([58]); cli_row("home-front", "busy", now0 + 20 * MIN)
check("10h front agent: a front agent with a turn running at the look is left alone", "a58" not in stk(now0 + 35 * MIN) and entry(58)["step"] == 1, entry(58))
close(58)
# 10k. the hold is the mover's own work line: a line in progress that another agent left on the item holds nothing
clear_records(); put(60, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([60]); work_line(60, "in progress", now0 + 20 * MIN, "team-back")
check("10k other agent's line: a recent line in progress written by another agent does not hold the ladder: the look is sent", "a60" in stk(now0 + 31 * MIN) and len(look_notices("home-docs", 60)) == 1, (entry(60), pushes_to("home-docs", "a60")))
close(60)
clear_records(); put(61, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([61]); work_line(61, "in progress", now0 + 20 * MIN, "home-docs")
check("10k mover's own line: the same line written by the mover holds it", "a61" not in stk(now0 + 31 * MIN) and not look_notices("home-docs", 61) and entry(61)["step"] == 1, (entry(61), pushes_to("home-docs", "a61")))
close(61)
from stackshot.audit import silence as SLN
it_ = {"metadata": {"work": [{"id": "w", "text": "t", "state": "in progress", "agent": "team-back", "ts": 1000.0}]}}
check("10k pure: subagent_running counts a line of any agent without a mover, and only the mover's own line with one",
      SLN.subagent_running(it_, 1100.0) and SLN.subagent_running(it_, 1100.0, "team-back", handoff_svc.ho_same) and not SLN.subagent_running(it_, 1100.0, "home-docs", handoff_svc.ho_same), None)
# 10l. a heartbeat that is empty or unreadable says nothing about the pane: a background mover with no registry row is taken as live (not cold-called, not handed on)
clear_records(); put(62, act=60, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
enter([62]); stk(now0 + 31 * MIN); no_row("home-docs")
hb_ = (T / "fleet/a/sessions.json").read_text(); (T / "fleet/a/sessions.json").write_text("{}")
n_cold = len(COLD_MSGS)
try:
    done = stk(now0 + 41 * MIN + 1); done2 = stk(now0 + 5 * H)
    check("10l empty heartbeat: with no registry row and an empty heartbeat the cold call is not made and the item stays with its mover (the silence goes to -main)", len(COLD_MSGS) == n_cold and mt(62).get("mover") == "home-docs" and entry(62)["step"] == 2, (done, done2, COLD_MSGS[n_cold:], mt(62)))
    (T / "fleet/a/sessions.json").write_text("not json")
    stk(now0 + 6 * H)
    check("10l unreadable heartbeat: the same", len(COLD_MSGS) == n_cold and mt(62).get("mover") == "home-docs" and entry(62)["step"] == 2, (COLD_MSGS[n_cold:], mt(62)))
finally:
    (T / "fleet/a/sessions.json").write_text(hb_)
close(62)
# 10j. pure: ladder.action for a background mover
ent2 = LD.enter_quiet(None, "m", [1.0, 2.0], 3.0, 100.0, 500.0)
bg = lambda rec, st, now, **kw: LD.action(rec, st, 1.0, 0.0, now, 10.0, 30.0, background=True, **kw)
check("10j action: a background mover's look is due 30 minutes after the ask whatever its pane shows (busy, shell, idle, none), not before",
      all(bg(ent2, st, 500.0 + 29 * 60, live=True) == "" for st in ("busy", "shell", "idle", "")) and all(bg(ent2, st, 500.0 + 30 * 60, live=True) == "look" for st in ("busy", "shell", "idle", "")), None)
cold_rec = {**ent2, "step": 2, "last": 3000.0}
check("10j action: …a live pane gets no cold call and no builder (its silence is handed to -main instead: 'main', section 11); a pane that is not live goes on, whatever the registry shows",
      bg(cold_rec, "busy", 3000.0 + 600, live=True) == "main" and bg({**ent2, "step": 3, "last": 3000.0}, "idle", 3000.0 + 600, live=True) == "main"
      and bg(cold_rec, "", 3000.0 + 599, live=False) == "" and bg(cold_rec, "", 3000.0 + 600, live=False) == "cold" and bg({**ent2, "step": 3, "last": 3000.0}, "busy", 3000.0 + 600, live=False) == "builder", None)
check("10m action: an entry the hand-off audit marked gone (two failed pushes, no delivery) reaches the cold call and the builder even when the heartbeat shows the pane live",
      bg({**cold_rec, "gone": True}, "idle", 3000.0 + 600, live=True) == "cold" and bg({**ent2, "step": 3, "last": 3000.0, "gone": True}, "idle", 3000.0 + 600, live=True) == "builder"
      and bg({**cold_rec, "gone": True}, "idle", 3000.0 + 599, live=True) == "" and bg(cold_rec, "idle", 3000.0 + 600, live=True) == "main", None)
check("10j action: a mover that is not background keeps the pane rule (busy waits)", LD.action(ent2, "busy", 1.0, 0.0, 500.0 + 3600, 10.0) == "" and LD.action(ent2, "busy", 1.0, 0.0, 500.0 + 3600, 10.0, 30.0, live=True) == "", None)
check("10j action: the first rung of a pane-triggered ladder (the ask) still waits for the pane to have no turn running, background or not",
      LD.action({"mover": "m", "step": 0, "last": 0.0}, "busy", 1.0, 0.0, 5000.0, 10.0, 30.0, background=True, live=True) == "" and LD.action({"mover": "m", "step": 0, "last": 0.0}, "idle", 1.0, 0.0, 5000.0, 10.0, 30.0, background=True, live=True) == "ask", None)

# ================================================================ 11. a live background mover that stays silent after the look reaches the project's -main agent
def main_notices(i, to="home-front"): return [p for p in pushes_to(to, f"a{i}") if "background mover" in p[1]]
def all_main_notices(to="home-front"): return [p for p in pushes_to(to) if "background mover" in p[1]]
ladder_cfg(True); set_live("home-docs"); set_live("team-back")
# 11a. the incident: a silent item on a live busy background agent: ask, look, then nothing for hours; now -main hears of it, once an interval
clear_records(); put(70, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([70]); stk(now0 + 31 * MIN)
check("11a after the look the entry is on the cold call's rung, nothing has gone to -main yet", entry(70)["step"] == 2 and not main_notices(70) and len(look_notices("home-docs", 70)) == 1, (entry(70), pushes_to("home-front", "a70")))
n_cold = len(COLD_MSGS)
check("11a nine minutes after the look: nothing yet", "a70" not in stk(now0 + 31 * MIN + 9 * MIN) and not main_notices(70), pushes_to("home-front", "a70"))
done = stk(now0 + 31 * MIN + 10 * MIN)
m70 = main_notices(70)
check("11a ten minutes after the look: ONE notice goes to the project's -main agent and the item is acted on", "a70" in done and len(m70) == 1, (done, pushes_to("home-front", "a70")))
t70 = m70[0][1] if m70 else ""
since70 = __import__("datetime").datetime.fromtimestamp(now0 - 60 * MIN, ZONE).strftime("%a %b")
check("11a the notice is marked for the owner on its first line, names the item, its mover and the time since the last write, and asks for a nudge or a different mover",
      t70.splitlines()[0] == "[for Oliver]" and "has had no write from its background mover home-docs since " + since70 in t70
      and "Decide whether it needs a nudge or a different mover" in t70 and "4 hours" in t70, t70)
check("11a the notice says how to stop the repeats: write to the item, hold it or set its wait, and that it comes again in 4 hours while the item stays silent",
      "To stop the repeats, write to the item, hold it or set its wait; it comes again in 4 hours while the item stays silent." in t70, t70)
check("11a no cold call, no hand-off: the item stays with its mover on the same rung; the entry carries the stamp; a History line says it", len(COLD_MSGS) == n_cold and mt(70).get("mover") == "home-docs" and entry(70)["step"] == 2 and entry(70).get("main_at") == now0 + 41 * MIN
      and any("was told to decide on a nudge or a different mover" in x["text"] for x in log_of(70)), (entry(70), log_of(70)))
for off in (41 * MIN + 60, 2 * H, 4 * H, 4 * H + 40 * MIN):
    stk(now0 + off)
check("11a no repeat before the interval: passes a minute, 80 minutes, 4 hours and 4 hours 40 minutes after the first notice add none", len(main_notices(70)) == 1, pushes_to("home-front", "a70"))
done = stk(now0 + 41 * MIN + 4 * H)
check("11a the interval after the first notice (4 hours) the same notice goes again, and says it was told before", "a70" in done and len(main_notices(70)) == 2 and "was told about this at" in main_notices(70)[1][1], pushes_to("home-front", "a70"))
stk(now0 + 41 * MIN + 4 * H + 60); stk(now0 + 41 * MIN + 7 * H)
check("11a …and then not again until another interval has passed (one per interval, not one per pass)", len(main_notices(70)) == 2 and len(COLD_MSGS) == n_cold, pushes_to("home-front", "a70"))
stk(now0 + 41 * MIN + 8 * H)
check("11a …it goes on every interval while the silence lasts", len(main_notices(70)) == 3, pushes_to("home-front", "a70"))
close(70)
# 11b. a front agent's own item is untouched by this rung
clear_records(); sent_before = len(all_main_notices()); put(71, act=60, mover="home-front"); cli_row("home-front", "idle", IDLE_SINCE)
enter([71]); stk(now0 + 31 * MIN); stk(now0 + 41 * MIN + 1); stk(now0 + 6 * H); stk(now0 + 12 * H)
check("11b front mover: its item never goes to -main as a silent background mover", len(all_main_notices()) == sent_before and not any("background mover" in p[1] for p in pushes_to("home-front", "a71")), pushes_to("home-front", "a71"))
close(71)
# 11c. an item that is not silent: activity after the entry ends it, a fresh work line holds it, and neither reaches -main
clear_records(); put(72, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([72]); d_ = rd(72); d_["activity"] = now0 + 35 * MIN; (T / "store/a/72.json").write_text(json.dumps(d_))
stk(now0 + 31 * MIN); stk(now0 + 45 * MIN); stk(now0 + 5 * H)
check("11c an item with activity after the entry was made: no notice to -main", not main_notices(72), pushes_to("home-front", "a72"))
close(72)
clear_records(); put(73, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([73]); work_line(73, "in progress", now0 + 20 * MIN, "home-docs")
stk(now0 + 31 * MIN); stk(now0 + 41 * MIN + 1); stk(now0 + 20 * MIN + 89 * MIN)
check("11c a work line of the mover in progress, changed within 90 minutes, holds the item: no notice to -main", not main_notices(73) and entry(73)["step"] == 1, (entry(73), pushes_to("home-front", "a73")))
done = stk(now0 + 20 * MIN + 91 * MIN)
check("11c an old work line left in progress hides the item no longer than 90 minutes after it was changed: the look is sent then, and -main has not been told yet", "a73" in done and len(look_notices("home-docs", 73)) == 1 and not main_notices(73), pushes_to("home-docs", "a73"))
stk(now0 + 20 * MIN + 101 * MIN + 1)
check("11c …ten minutes after that look -main is told", len(main_notices(73)) == 1, pushes_to("home-front", "a73"))
close(73)
# 11d. a mover whose pane is not live gets the cold call and the builder as before, and -main is not told
clear_records(); put(74, act=60, mover="home-docs"); cli_row("home-docs", "idle", IDLE_SINCE)
enter([74]); stk(now0 + 31 * MIN); no_row("home-docs"); set_gone("home-docs")
n_cold = len(COLD_MSGS)
done = stk(now0 + 41 * MIN + 1)
check("11d dead pane: the cold call is made and the item falls to the builder; nothing goes to -main", "a74" in done and len(COLD_MSGS) == n_cold + 1 and mt(74).get("mover") == "team-back" and not main_notices(74), (done, pushes_to("home-front", "a74")))
close(74); set_live("home-docs")
# 11e. ONE notice per -main agent per pass, listing every item due for it: three silent items of live background agents of one project, and one item of another project (another -main)
clear_records(); put(75, act=60, mover="home-docs"); put(76, act=60, mover="team-back"); put(78, act=60, mover="team-back"); put(79, project="projects/beta", act=60, mover="home-docs")
cli_row("home-docs", "busy", now0 - 20 * MIN); cli_row("team-back", "busy", now0 - 20 * MIN)
c_a, c_b = len(all_main_notices()), len(all_main_notices("home-beta-front")); enter([75, 76, 78, 79])
for k in range(4): stk(now0 + (31 + k) * MIN)      # one look a pass for each agent: the four items reach the cold call's rung a minute or two apart
check("11e before it, nothing has gone to either -main", len(all_main_notices()) == c_a and len(all_main_notices("home-beta-front")) == c_b and all(entry(i)["step"] == 2 for i in (75, 76, 78, 79)), [entry(i) for i in (75, 76, 78, 79)])
p0 = len(pushes()); d1 = stk(now0 + 50 * MIN)
n_alpha = [p for p in pushes()[p0:] if p[0] == U["home-front"] and "background movers" in p[1]]
n_beta = [p for p in pushes()[p0:] if p[0] == U["home-beta-front"] and "background mover" in p[1]]
check("11e three items due for one -main in one pass: ONE notice that lists all three (id, project, mover, time since the last write), the fourth item's notice goes to its own -main",
      sorted(d1) == ["a75", "a76", "a78", "a79"] and len(n_alpha) == 1 and len(n_beta) == 1 and all(server._gh.shown(f"a{i}") in n_alpha[0][1] for i in (75, 76, 78))
      and n_alpha[0][1].count("\n- ") == 3 and n_alpha[0][1].splitlines()[0] == "[for Oliver]" and n_alpha[0][1].count("(projects/alpha): mover ") == 3 and "mover home-docs" in n_alpha[0][1] and "mover team-back" in n_alpha[0][1]
      and "no write since" in n_alpha[0][1] and "To stop the repeats, write to the item, hold it or set its wait" in n_alpha[0][1] and server._gh.shown("a79") not in n_alpha[0][1] and "a79" in n_beta[0][1], (d1, n_alpha, n_beta))
check("11e …every listed item's entry is stamped and has its History line; the next pass sends nothing more", all(entry(i).get("main_at") == now0 + 50 * MIN for i in (75, 76, 78, 79)) and all(any("was told to decide" in x["text"] for x in log_of(i)) for i in (75, 76, 78, 79))
      and not stk(now0 + 50 * MIN + 60) and len(pushes()) == p0 + 2, [entry(i) for i in (75, 79)])
close(75, 76, 78, 79)
# 11f. a project with no -main agent: the History line alone, the rung is taken (no retry every pass)
clear_records(); put(77, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([77]); stk(now0 + 31 * MIN); real_main = server._main_agent; server._main_agent = lambda project: ""
err_f = io.StringIO()
try:
    n_push = len(pushes())
    with contextlib.redirect_stderr(err_f): done = stk(now0 + 41 * MIN + 1)
    done2 = stk(now0 + 41 * MIN + 61); flag_f = ladder_svc.ladder_no_main("a77", "home-docs")
finally:
    server._main_agent = real_main
check("11f …the stderr line says there is no -main agent to tell, and the reason is flagged as not the mover itself", "ladder: a77 home-docs is live and silent after the look: no -main agent to tell" in err_f.getvalue() and flag_f == (False, "the project has no -main agent to tell"), (err_f.getvalue(), flag_f))
check("11f no -main agent: nothing is sent, a History line says so, and the rung is taken once (the next pass does nothing)", "a77" in done and "a77" not in done2 and len(pushes()) == n_push and any("no -main agent to tell" in x["text"] for x in log_of(77)) and entry(77).get("main_at"), (done, done2, log_of(77)))
close(77)
# 11g. the live background mover is the project's -main agent itself: nobody is above it, so it is not told about its own silence (a mutant that lets -main tell itself fails the first check), the History line says
# why in the words for it, and the rung is taken once; the note the save is handed says "the -main agent itself", not "no -main agent to tell" (the third check; the old tick-level test of this went with the hand-up)
clear_records(); put(9091, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([9091]); stk(now0 + 31 * MIN); real_main = server._main_agent; server._main_agent = lambda project: "home-docs"
real_save = ladder_svc._writes.save; save_notes = []
def noting_save(gid, item, *a, **kw): save_notes.append(kw.get("note", "")); return real_save(gid, item, *a, **kw)      # the save's note reaches no page: read it as it is handed over
ladder_svc._writes.save = noting_save
err_g = io.StringIO()
try:
    n_push = len(pushes()); n_own = len(pushes_to("home-docs", "a9091"))
    with contextlib.redirect_stderr(err_g): done = stk(now0 + 41 * MIN + 1)
    done2 = stk(now0 + 41 * MIN + 61)
    to_ = ladder_svc.ladder_main_to("a9091", "home-docs"); itself_, why_ = ladder_svc.ladder_no_main("a9091", "home-docs")
finally:
    server._main_agent = real_main; ladder_svc._writes.save = real_save
check("11g the mover is the -main agent itself: ladder_main_to is empty (nobody above it), the reason is flagged as the mover itself and names it, not a missing -main agent", to_ == "" and itself_ is True and "no one above it to tell" in why_ and "has no -main agent" not in why_, (to_, itself_, why_))
check("11g …the stderr line does not say the project has no -main agent: it says the mover is the -main agent itself", "ladder: a9091 home-docs is live and silent after the look: it is the -main agent itself, so no one above it is told" in err_g.getvalue() and "no -main agent to tell" not in err_g.getvalue(), err_g.getvalue())
check("11g …nothing is sent to it about its own silence, and the rung is taken once (the next pass does nothing)", "a9091" in done and "a9091" not in done2 and len(pushes()) == n_push and len(pushes_to("home-docs", "a9091")) == n_own and entry(9091).get("main_at"), (done, done2, pushes()[n_push:], entry(9091)))
check("11g …the History line says the mover is the project's -main agent, with no one above it to tell (not the no -main agent wording)", any("its mover is the project's -main agent, so there is no one above it to tell" in x["text"] for x in log_of(9091)) and not any("no -main agent to tell" in x["text"] for x in log_of(9091)), log_of(9091))
check("11g …and the note the save is handed says it is the -main agent itself", "ladder: its mover is silent, it is the -main agent itself" in save_notes and not any("no -main agent to tell" in n for n in save_notes), save_notes)
close(9091)
# 11h. an untaken hand-off whose mover is a live background session: a write by someone else (the owner's comment, 20 minutes before the notice is due) does not delay the notice to -main:
# it is due ten minutes after the look, whatever the item's activity (a pin: no "recent activity" wait stands between the look and -main)
clear_records()
put(80, act=60, mover="home-docs", handoff=H_.new_record("home-docs", U["home-docs"], "home-send", now0 - 40 * MIN, delivered_at=now0 - 40 * MIN + 10)); cli_row("home-docs", "busy", now0 - 20 * MIN)
check("11h (setup) the hand-off audit brings the untaken hand-off to the ladder (via handoff), the ask is sent",
      handoff_svc.handoff_tick(now=now0, only=["a80"]) == ["a80"] and (drain() or True) and (entry(80) or {}).get("via") == "handoff" and entry(80).get("step") == 1, (entry(80), pushes_to("home-docs", "a80")))
d_ = rd(80); d_["activity"] = now0 + 21 * MIN; d_["updated"] = now0 + 21 * MIN; d_["written_by"] = "home-front"; (T / "store/a/80.json").write_text(json.dumps(d_))      # the owner's comment, 20 minutes before the notice is due
stk(now0 + 31 * MIN)
done = stk(now0 + 41 * MIN + 1)
check("11h the notice to -main goes at once, ten minutes after the look, although the owner wrote to the item 20 minutes before", "a80" in done and len(main_notices(80)) == 1 and entry(80).get("main_at") == now0 + 41 * MIN + 1, (done, entry(80), pushes_to("home-front", "a80")))
close(80)
# 11g. pure: ladder.action / advance for the rung
live_rec = {**ent2, "step": 2, "last": 3000.0}
check("11g action: a live background mover on the cold call's rung is due 'main' `minutes` after the look and not before, whatever its pane shows",
      all(bg(live_rec, st, 3000.0 + 599, live=True) == "" and bg(live_rec, st, 3000.0 + 600, live=True) == "main" for st in ("busy", "shell", "idle", "")), None)
LD.advance(live_rec, "main", 4000.0)
check("11g advance: the notice stamps `main_at` and `last` and leaves the step where it is (the cold call and the builder stay reachable)", live_rec["main_at"] == 4000.0 and live_rec["last"] == 4000.0 and live_rec["step"] == 2, live_rec)
check("11g action: …the next one is due `MAIN_EVERY` after the first, counted from `main_at`, not from every pass",
      bg(live_rec, "busy", 4000.0 + LD.MAIN_EVERY - 1, live=True) == "" and bg(live_rec, "busy", 4000.0 + LD.MAIN_EVERY, live=True) == "main" and LD.MAIN_EVERY == 4 * 3600.0, None)
def bgf(rec, now, floor): return LD.action(rec, "busy", 1.0, floor, now, 10.0, 30.0, background=True, live=True)
fresh_rec = {k: v for k, v in live_rec.items() if k != "main_at"}      # the same entry before its first notice to -main
check("11g action: the repeat clock honors the floor: an item that reached its mover again 2 hours after the last notice is told again 4 hours after that, not 4 hours after the last notice",
      live_rec["main_at"] == 4000.0 and bgf(live_rec, 4000.0 + LD.MAIN_EVERY, 4000.0 + 2 * H) == "" and bgf(live_rec, 4000.0 + 2 * H + LD.MAIN_EVERY - 1, 4000.0 + 2 * H) == ""
      and bgf(live_rec, 4000.0 + 2 * H + LD.MAIN_EVERY, 4000.0 + 2 * H) == "main" and bgf(live_rec, 4000.0 + LD.MAIN_EVERY, 0.0) == "main", None)
check("11g action: …and so does the first notice: it is due `minutes` after the later of the look and the floor",
      fresh_rec["last"] == 4000.0 and bgf(fresh_rec, 4000.0 + 600, 5000.0) == "" and bgf(fresh_rec, 5000.0 + 599, 5000.0) == "" and bgf(fresh_rec, 5000.0 + 600, 5000.0) == "main" and bgf(fresh_rec, 4000.0 + 600, 0.0) == "main", None)
check("11g action: …a pane that stops being live still reaches the cold call, counted from the last rung", bg(live_rec, "", 4000.0 + 600, live=False) == "cold" and bg({**live_rec, "step": 3}, "", 4000.0 + 600, live=False) == "builder", None)
check("11g action: a mover that is not a background agent never gets 'main' (the pane rule stands)", LD.action(live_rec, "busy", 1.0, 0.0, 9e9, 10.0, 30.0, live=True) == "", None)

# ================================================================ 12. a config that still carries the retired keys ([ladder] main_hours and silence) loads and does nothing
# The old hand-up of an alive item that had not moved for `main_hours` is gone: nothing reads the key (a value other than the old 4 shows it), and an item a busy mover has held for many hours, with no ladder entry, is told to no one.
set_live("home-peer"); set_live("home-docs"); ladder_cfg(True, main_hours=1, silence=True)
clear_records(); put(9080, act=30, mover="home-peer"); cli_row("home-peer", "busy", now0 - 20 * MIN)
n_before = len(pushes())
done = [stk(now0 + 31 * MIN), stk(now0 + 5 * H), stk(now0 + 9 * H), stk(now0 + 30 * H)]
check("12 a config that carries main_hours = 1 and silence = true: an alive item with a busy live mover that has not moved for 30 hours is told to no one, by any pass",
      done == [[], [], [], []] and len(pushes()) == n_before and not pushes_to("home-front", "a9080") and not any("has not moved for" in p_[1] for p_ in pushes()[n_before:]), (done, pushes()[n_before:]))
check("12 …and nothing is written to the item or the ladder's record: no History line, no mark, no rung taken (the entry the stall pass keeps stays at the ask, with no `main_at`)",
      mt(9080).get("progress_up_at") is None and "stall" not in mt(9080) and (entry(9080) or {}).get("step", 0) == 0 and not (entry(9080) or {}).get("main_at") and not hasattr(server, "_ladder_stuck"), (mt(9080), entry(9080)))
close(9080)
# the live mover's own rung is unchanged with the keys present: ONE notice to -main `minutes` after the look, the next only every ladder.MAIN_EVERY (4 hours), never every main_hours (1 hour here)
clear_records(); put(9081, act=60, mover="home-docs"); cli_row("home-docs", "busy", now0 - 20 * MIN)
enter([9081]); stk(now0 + 31 * MIN); stk(now0 + 41 * MIN)
n_first = len(main_notices(9081))
for off in (41 * MIN + 1 * H + 1, 41 * MIN + 2 * H, 41 * MIN + 3 * H, 41 * MIN + 4 * H - 60):
    stk(now0 + off)
check("12 …a silent live mover's item: ONE notice to -main at the first due time, and none an hour, 2 hours or 3 hours 59 minutes after it (main_hours = 1 is not its interval)", n_first == 1 and len(main_notices(9081)) == 1, pushes_to("home-front", "a9081"))
t9081 = main_notices(9081)[0][1] if main_notices(9081) else ""
check("12 …and the notice says it comes again in 4 hours (the fixed interval), not in the 1 hour the config's main_hours says",
      "it comes again in 4 hours while the item stays silent." in t9081 and "1 hour" not in t9081, t9081)
stk(now0 + 41 * MIN + 4 * H)
check("12 …and the next one goes 4 hours after the first, as ladder.MAIN_EVERY says (a fixed interval, no key)", len(main_notices(9081)) == 2 and LD.MAIN_EVERY == 4 * 3600.0 and not hasattr(server, "_ladder_main_hours")
      and "main_every" not in __import__("inspect").signature(LD.action).parameters, pushes_to("home-front", "a9081"))
close(9081)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
