"""Scenario test for the take clock on a peer hand-off: in a front-only project (anchors.front_only: no builder) a session some page lists (a front agent, or a background agent of another project) hands an item to a front agent with `mover=`;
that hand-off is clocked like a builder's, and the item is the new mover's: only the new mover is reminded, the ladder ends at the project's -main agent, and the hander is told nothing at any point. A project with a
builder, a hand-off to another project's front agent and one to the -main agent itself keep the old exemption. Fixture data (English stand-in names) in a temporary store, the push replaced by a recorder, no network,
no model call.

  1  the clock, ladder off: the notice reaches the new mover once; before the take minutes nothing more (a turn that ended on the new mover's pane does not hurry it); after them ONE `handoff` reminder to the new mover
     alone; after another take minutes the last rung asks the project's -main agent (no owner mark); the hander and the fleet's builder get nothing at any step
  2  the clock, ladder on: the take minutes bring the item to the one ladder, its ask is the notice again to the new mover (a `handoff` push), the look after it likewise, then the -main agent is asked; the hander gets nothing
  3  a mover that starts work (a work line in progress) before the clock, or after the reminder, stops it
  4  exempt as before: a project with a builder (a front-to-front record), a hand-off to another project's front agent, a hand-off to the -main agent itself, a hand-off the server made (`from` is no front agent)
  5  the pieces on their own: handoff_exempt / handoff_peer for each shape, the reminder target of a peer (a front role) against a background agent's, `Env.peer` defaulting to the old rule
  6  the hander is the -main agent: the last rung still asks it (it is the project's escalation point), pinned; the request says so
  7  the rework: a peer's item is never put to the cold call (ladder off and on; a stub that would close the item proves it is not asked), a project with a background agent still is; a peer whose pane is busy gets the
     reminder but no request to the -main agent until the turn is over; the reminder says nothing of a subagent; the request says what was tried

  8  the hander is a session that is no front agent (another project's background agent): with the ladder off the item is never returned to it; the reminder, then the -main agent's request, and the hander is told nothing

    tests/run-suite peer_handoff_clock        -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="peerclock-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-alpha-desk", "home-beta-front", "home-delta-main", "home-delta-stew", "home-beta-stew", "home-stew", "home-fleet")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_OFFSET = 4 * 3600                                                                  # the instance zone is Asia/Dubai: UTC+4, no daylight saving
ZONE_ABBR = "+04"                                                                       # its strftime %Z abbreviation
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: a project with a builder (front home-front and home-alpha-desk; background home-docs and team-back); beta: one front agent, no background agent;
# delta: front-only with three front agents (home-delta-main is its -main agent; home-peer and home-peer2 are the peers)
ALPHA = {"home-front": "the front", "home-alpha-desk": "answers questions", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
DELTA = {"home-delta-main": "the front", "home-peer": "answers questions", "home-peer2": "answers other questions"}
BETA = {"home-beta-front": "the front"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
    "projects/beta": proj("home-beta-stew", BETA, {}),
    "projects/delta": proj("home-delta-stew", DELTA, {})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", BETA), ("delta", "home-delta-stew", DELTA)):
    back = [k for k in agents if k in ("home-docs", "team-back")]
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the vendor call is open.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("97"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
B = now0 - 900.0          # the base of the item clocks: items last written then, and the first step is due 10 minutes after the pane went idle at B + 60
def item(i, project="projects/alpha", mover="home-peer", status="open", updated=None, **meta):
    up = B if updated is None else updated
    base = {"owner": U["home-front"], "project": project, "next": f"{mover}: do the thing"}
    if mover: base["mover"] = mover
    base.update(meta)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": up, "state_updated": up, "confirmed": up, "metadata": base}))
def close(*ids):
    for i in ids:
        d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def ho(i): return mt(i).get("handoff") or {}
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1800]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import handoff as H; from stackshot.waits import stall as S
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.core import instance as _core_instance
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import stall as stall_svc, stall_tick as stalltick_svc
from stackshot.web.tools import get as _wt_get
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
# the record follows the mover (handoff.stale): checked after every save of the run, the stall pass's moves and raises included
_real_save = writes.save
INV_BAD = []; INV_SAVES = [0]
NOTES = []
def _save_inv(gid, item, *a, **kw):
    NOTES.append((gid, kw.get("note", "")))
    out = _real_save(gid, item, *a, **kw)
    INV_SAVES[0] += 1
    if H.stale(item, H.mover_of(item, lambda it: handoff_svc.ho_derive({**it, "gid": gid})), handoff_svc.ho_same): INV_BAD.append((gid, (item.get("metadata") or {}).get("handoff"), kw.get("note", "")))
    return out
writes.save = _save_inv
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
def set_cfg(**kw): _cfg.CFG["model"] = dict(kw)
def set_stall(**kw):
    """The [stall] section as given. A pause (enabled = false, a paused_until) names the item as its pause_item unless the call says otherwise: an item that carries Oliver's own answer,
    dated far ahead so it counts at any clock below; section 18 tests the refusals with answers of its own."""
    if (kw.get("enabled") is False or kw.get("paused_until")) and "pause_item" not in kw: kw["pause_item"] = "a97"
    _cfg.CFG["stall"] = dict(kw)
set_cfg(); set_stall()
_cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder: the ladders' last rung asks it, once per episode, to recover a quiet session
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def main_recovery_pushes(gid): return [p for p in pushes_to("home-delta-main", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, with no owner mark
item(97, status="completed", answers=[{"ts": 9e9, "kind": "comment", "text": "Pause it for now.", "via": "board"}])      # Oliver's answer, the pause_item of every pause below
stall_svc.stall_since(B)          # the pass first ran at B (before every clock below); test 12 starts from no file at all
COLD_MSGS = []
def cold(answer, status="ok"):
    def run(msg):
        COLD_MSGS.append(msg)
        return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    hcold_svc.COLD_RUNNER = run
hcold_svc.COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}
cold("no json at all here")            # a cold call that gives nothing
def cli_row(who, status, at):
    """The CLI's own registry row of a pane on this box: an interactive pane, status busy | idle and when it changed (ms)."""
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
DEAD_ISO = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 3 * 3600))      # gone three hours: past [client] dead_after_minutes
def set_gone(who, on=True):
    """the heartbeat's row of `who` says its pane has been gone for hours (the message tool's dead-recipient rule), or is live again"""
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if on and n == who else {})} for n, u in U.items()}))
def no_row(who): (T / f"cli/{os.getpid()}-{who}.json").unlink(missing_ok=True)
handoff_svc.CLI_SESSIONS = T / "cli"
OWN = _core_instance.OWNER
FUT = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400 + ZONE_OFFSET))
ASK = "Decide: ship the thing now · Recommend: ship it · Stakes: a week of delay · By: no date"
MIN = 60.0
def stk(at):
    """One stall pass at `at` (the 20-second gate reset), the threads it started finished → the items it acted on."""
    stall_svc.STALL_LAST[0] = 0.0
    out = stalltick_svc.stall_tick(at); drain()
    return out
def log_of(i): return S.log_of(mt(i))

from stackshot.service import update as _update_svc
def upd(i, sender, **kw): return _update_svc._update(f"a{i}", sender=sender, **kw)
def tick(at, *ids): return handoff_svc.handoff_tick(now=at, only=[f"a{i}" for i in ids] or None)
def texts(who, gid): return [p[1] for p in pushes_to(who, gid)]
set_cfg(cold_call=False)            # the cold call is off: the rung after the take minutes is the project's -main agent
def put(i, project="projects/delta", mover="home-peer", **meta):
    item(i, project=project, mover=mover, **meta)
def hand(i, to, sender="home-peer"):
    """the sender hands a<i> to `to` with mover=: the notice goes to `to` (a `handoff` push) and the record is made"""
    upd(i, sender, mover=to, next=f"{to}: do the thing"); drain()
    return ho(i)
for w in ("home-peer", "home-peer2", "home-delta-main", "home-alpha-desk", "home-beta-front", "home-front"): cli_row(w, "busy", now0)

# ================================================================ 1. the clock, ladder off
put(1)
r = hand(1, "home-peer2")
check("1 the hand-off is recorded for the new mover and its notice reached it once, a `handoff` text", r.get("to") == "home-peer2" and r.get("from") == "home-peer" and bool(r.get("delivered_at")) and len(texts("home-peer2", "a1")) == 1
      and "handed to you by home-peer" in texts("home-peer2", "a1")[0], (r, pushes()))
d1 = float(r["delivered_at"])
check("1 before the take minutes the pass does nothing", tick(d1 + 5 * MIN, 1) == [] and len(texts("home-peer2", "a1")) == 1, pushes())
cli_row("home-peer2", "idle", d1 + 60)
check("1 …and a turn that ended on the new mover's pane with no write does not hurry it (the take minutes alone count for a front agent)", tick(d1 + 5 * MIN, 1) == [] and not ho(1).get("reminded_at"), ho(1))
check("1 …nor does the stall pass start on an untaken peer hand-off (the hand-off audit's alone, as a builder's is), however long the pane has been idle", stk(d1 + 40 * MIN) == [] and not log_of(1) and not ho(1).get("reminded_at"), (log_of(1), ho(1)))
done = tick(d1 + 11 * MIN, 1); drain()
check("1 take minutes later ONE reminder goes to the new mover alone, worded as a reminder, and the record says so", done == ["a1"] and len(texts("home-peer2", "a1")) == 2 and texts("home-peer2", "a1")[1].startswith("[stackshot] reminder: a1 ")
      and bool(ho(1).get("reminded_at")), (ho(1), pushes()))
d1b = float(ho(1)["delivered_at"])
check("1 …the reminder fits a front agent: no subagent to start, take it by a step marked done or a work line set to in progress or done, or hand it back to the hander", "subagent" not in texts("home-peer2", "a1")[1] and "marking a step done, or by writing a work line set to in progress or done (a note does not count)" in texts("home-peer2", "a1")[1]
      and "hand it back (sender='home-peer')" in texts("home-peer2", "a1")[1], texts("home-peer2", "a1"))
check("1 …the hander, the project's -main agent and the fleet's builder are told nothing", not pushes_to("home-peer") and not pushes_to("home-delta-main") and not pushes_to("home-fleet"), pushes())
check("1 …and nothing goes down the ladder before the next take minutes", tick(d1b + 5 * MIN, 1) == [] and not ho(1).get("recovery_at"), ho(1))
done = tick(d1b + 11 * MIN, 1); drain()
mp = main_recovery_pushes("a1")
check("1 after another take minutes the last rung asks the project's -main agent, once, with no owner mark, naming the item and the quiet new mover", done == ["a1"] and len(mp) == 1 and mp[0][1].startswith("[stackshot] a1 ") and f"[for {OWN}]" not in mp[0][1]
      and "home-peer2" in mp[0][1] and bool(ho(1).get("recovery_at")) and ho(1).get("recovery_by") == "the project's -main agent", (done, mp, ho(1)))
check("1 …and says what was tried (the notice and one reminder), not a fresh session's call and the sender, and does not call the -main agent the hander", "What the ladder tried: the hand-off notice went to home-peer2 and, with no work started after 10 min, one reminder." in mp[0][1]
      and "fresh session" not in mp[0][1] and "yourself" not in mp[0][1], mp)
check("1 …the item stays with its mover, the hander has been told nothing at any step, and the fleet's builder neither", mt(1).get("mover") == "home-peer2" and not pushes_to("home-peer") and not pushes_to("home-fleet"), (mt(1), pushes()))
check("1 …later passes send nothing more", tick(d1b + 5 * 3600, 1) == [] and len(main_recovery_pushes("a1")) == 1, pushes())
close(1)

# ================================================================ 3. a mover that starts work stops the clock
cli_row("home-peer2", "busy", now0)
put(2)
r = hand(2, "home-peer2"); d2 = float(r["delivered_at"])
upd(2, "home-peer2", work={"text": "doing it", "state": "in progress"})
check("3 a work line in progress takes the hand-off", bool(ho(2).get("taken_at")), ho(2))
check("3 …and no reminder or request follows, however late", tick(d2 + 30 * MIN, 2) == [] and tick(d2 + 5 * 3600, 2) == [] and len(texts("home-peer2", "a2")) == 1 and not main_recovery_pushes("a2"), pushes())
close(2)
put(3)
r = hand(3, "home-peer2"); d3 = float(r["delivered_at"])
tick(d3 + 11 * MIN, 3); drain()
check("3 a mover that starts work after the reminder stops it too", bool(ho(3).get("reminded_at")), ho(3))
upd(3, "home-peer2", work={"text": "doing it", "state": "in progress"})
check("3 …taken: nothing is asked of -main", bool(ho(3).get("taken_at")) and tick(d3 + 5 * 3600, 3) == [] and not main_recovery_pushes("a3"), (ho(3), pushes()))
close(3)

# ================================================================ 2. the clock, ladder on
_cfg.CFG["ladder"] = {"enabled": True}
put(4)
r = hand(4, "home-peer2"); d4 = float(r["delivered_at"]); cli_row("home-peer2", "idle", d4 + 60)
check("2 ladder on: before the take minutes nothing happens, a turn that ended included", tick(d4 + 5 * MIN, 4) == [] and not stall_svc.stall_load().get("a4"), stall_svc.stall_load())
done = tick(d4 + 11 * MIN, 4); drain()
ent = stall_svc.stall_load().get("a4") or {}
check("2 the take minutes bring the item to the one ladder (via handoff)", done == ["a4"] and ent.get("via") == "handoff" and ent.get("mover") == "home-peer2", (done, ent))
check("2 …its ask is the hand-off's notice again to the new mover, a `handoff` push, and the History line says the notice was sent", len(texts("home-peer2", "a4")) == 2 and "handed to you by home-peer" in texts("home-peer2", "a4")[1]
      and any("has not taken it: the notice was sent to it again" in x["text"] for x in log_of(4)), (pushes(), log_of(4)))
check("2 …the hander and the -main agent are told nothing so far", not pushes_to("home-peer") and not pushes_to("home-delta-main", "a4"), pushes())
t = time.time() + 11 * MIN + 31 * MIN
stk(t); stk(t + 11 * MIN + 1); stk(t + 22 * MIN + 2)
check("2 the look and the last rung follow: the new mover is asked once more, then the -main agent is asked once (no owner mark)", len(main_recovery_pushes("a4")) == 1 and main_recovery_pushes("a4")[0][1].startswith("[stackshot] a4 ") and f"[for {OWN}]" not in main_recovery_pushes("a4")[0][1]
      and len(texts("home-peer2", "a4")) >= 3, (pushes(), ent, stall_svc.stall_load().get("a4")))
check("2 …the request says what was tried with the ladder on: the notice sent again and the pane looked at", "What the ladder tried: the hand-off notice went to home-peer2, was sent again after 10 min with no work started, and its pane was looked at later." in main_recovery_pushes("a4")[0][1]
      and "fresh session" not in main_recovery_pushes("a4")[0][1], main_recovery_pushes("a4"))
check("2 …the hander and the fleet's builder never heard of it", not pushes_to("home-peer") and not pushes_to("home-fleet"), pushes())
close(4)
_cfg.CFG["ladder"] = {}

# ================================================================ 4. exempt as before
# a front-to-front record the pair rule would refuse through update (a project with a builder), written as the machinery would have
def rec_item(i, project, to, frm, **meta):
    item(i, project=project, mover=to, handoff=H.new_record(to, U[to], frm, now0 - 3600, **{"delivered_at": now0 - 3500}), **meta)
def view(i): return {**rd(i), "gid": f"a{i}"}
rec_item(10, "projects/alpha", "home-alpha-desk", "home-front")
check("4 a project with a builder: a hand-off to a front agent is exempt, not a peer's, never clocked", handoff_svc.handoff_exempt(view(10), "home-alpha-desk") and not handoff_svc.handoff_peer(view(10), "home-alpha-desk")
      and tick(time.time() + 86400, 10) == [], (ho(10), pushes()))
rec_item(11, "projects/delta", "home-beta-front", "home-peer")
check("4 a hand-off to another project's front agent is exempt, never clocked", handoff_svc.handoff_exempt(view(11), "home-beta-front") and not handoff_svc.handoff_peer(view(11), "home-beta-front")
      and tick(time.time() + 86400, 11) == [], ho(11))
rec_item(12, "projects/delta", "home-delta-main", "home-peer")
check("4 a hand-off to the project's -main agent is exempt as before (nothing above it could be asked), never clocked", handoff_svc.handoff_exempt(view(12), "home-delta-main") and not handoff_svc.handoff_peer(view(12), "home-delta-main")
      and tick(time.time() + 86400, 12) == [] and not pushes_to("home-fleet"), (ho(12), pushes()))
rec_item(13, "projects/delta", "home-peer2", H.SERVER)
check("4 a record the server made (`from` is no front agent) is not a peer's: exempt as before", handoff_svc.handoff_exempt(view(13), "home-peer2") and tick(time.time() + 86400, 13) == [], ho(13))
for i in (10, 11, 12, 13): close(i)

# ================================================================ 5. the pieces
rec_item(14, "projects/delta", "home-peer2", "home-peer")
check("5 handoff_peer: the peer case, by id as well as by name, and it is not exempt", handoff_svc.handoff_peer(view(14), "home-peer2") and handoff_svc.handoff_peer(view(14), U["home-peer2"]) and not handoff_svc.handoff_exempt(view(14), "home-peer2"), None)
check("5 …not for a session the record does not name, nor an item with no record", not handoff_svc.handoff_peer(view(14), "home-peer") and not handoff_svc.handoff_peer({**view(14), "metadata": {k: v for k, v in view(14)["metadata"].items() if k != "handoff"}}, "home-peer2"), None)
roles = _anc.session_roles()
check("5 the reminder target of a peer is its session id (a front role), a background agent's is the back role", handoff_svc.handoff_reminder_target("home-peer2", roles, front=True) == U["home-peer2"] and handoff_svc.handoff_reminder_target("home-peer2", roles) == ""
      and handoff_svc.handoff_reminder_target("team-back", roles) == U["team-back"] and handoff_svc.handoff_reminder_target("team-back", roles, front=True) == "", (roles.get("home-peer2"), roles.get("team-back")))
env0 = H.Env(now=0.0, derive=lambda it: None)
check("5 Env.peer and Env.exempt default to the old rule", env0.peer({}, "x") is False and env0.exempt({}, "x") is False, None)
rec_item(27, "projects/delta", "home-peer2", "team-back")
rec_item(28, "projects/delta", "home-peer2", "home-nobody")
check("5 a session some page lists (here another project's background agent) may hand over to a front-only project's front agent: that hand-off is a peer's too; a sender no page lists is not (exempt as before)",
      handoff_svc.handoff_peer(view(27), "home-peer2") and not handoff_svc.handoff_exempt(view(27), "home-peer2") and not handoff_svc.handoff_peer(view(28), "home-peer2") and handoff_svc.handoff_exempt(view(28), "home-peer2"), (ho(27), ho(28)))
close(27, 28)
close(14)

# ================================================================ 6. the hander is the -main agent
put(15, mover="home-delta-main")
cli_row("home-peer2", "busy", now0)
r = hand(15, "home-peer2", sender="home-delta-main"); d15 = float(r["delivered_at"])
tick(d15 + 11 * MIN, 15); drain(); d15b = float(ho(15)["delivered_at"])
cli_row("home-peer2", "idle", d15b + 60)      # the turn is over: a busy pane is not asked about (section 7)
tick(d15b + 11 * MIN, 15); drain()
check("6 the hander is the -main agent: the reminder goes to the new mover, and the last rung still asks the -main agent (the project's escalation point: a request about a quiet session, no note to the hander)",
      len(texts("home-peer2", "a15")) == 2 and len(main_recovery_pushes("a15")) == 1 and "home-peer2" in main_recovery_pushes("a15")[0][1], pushes())
check("6 …and the request says the -main agent handed the item over itself", "you, the project's -main agent, handed this item to home-peer2 yourself" in main_recovery_pushes("a15")[0][1], main_recovery_pushes("a15"))
close(15)

# ================================================================ 7. the rework
COLD_CALLS = []
def cold_close(msg):
    COLD_CALLS.append(msg)
    return {"status": "ok", "text": json.dumps({"action": "close", "outcome": "done", "reason": "it looks finished", "outcome_text": "- The thing is done\n- It lives here"}), "duration_s": 0.1, "usage": {}, "note": "stub"}
hcold_svc.COLD_RUNNER = cold_close
set_cfg(cold_call=True)             # the cold call is ON from here, answering `close`: a peer's item must never reach it
def still_theirs(i, to): return rd(i)["status"] == "open" and mt(i).get("mover") == to and "decision" not in (mt(i).get("needs") or []) and not mt(i).get("ask")

# 7a. ladder off: reminder, then the -main agent, never the cold call
cli_row("home-peer2", "idle", now0)
put(20)
r = hand(20, "home-peer2"); d = float(r["delivered_at"])
tick(d + 11 * MIN, 20); drain(); d = float(ho(20)["delivered_at"])
tick(d + 11 * MIN, 20); drain()
check("7 ladder off: the peer's item skips the cold call: the stub was never asked, nothing closed or put to the owner, the -main agent is asked", COLD_CALLS == [] and still_theirs(20, "home-peer2") and len(main_recovery_pushes("a20")) == 1, (COLD_CALLS, mt(20), pushes()))
close(20)

# 7b. ladder on: ask, look, then the -main agent, never the cold call
_cfg.CFG["ladder"] = {"enabled": True}
put(21)
r = hand(21, "home-peer2"); d = float(r["delivered_at"]); cli_row("home-peer2", "idle", d + 60)
tick(d + 11 * MIN, 21); drain()
t = time.time() + 11 * MIN + 31 * MIN
stk(t); stk(t + 11 * MIN + 1); stk(t + 22 * MIN + 2); stk(t + 33 * MIN + 3)
check("7 ladder on: the peer's item skips the cold call too: never asked, nothing closed or put to the owner, the -main agent asked once", COLD_CALLS == [] and still_theirs(21, "home-peer2") and len(main_recovery_pushes("a21")) == 1, (COLD_CALLS, mt(21), pushes_to("home-delta-main", "a21")))
close(21)
_cfg.CFG["ladder"] = {}

# 7c. ladder off, a busy pane: the reminder goes once, no request while the turn runs, the request when it is over
cli_row("home-peer2", "busy", now0)
put(22)
r = hand(22, "home-peer2"); d = float(r["delivered_at"])
tick(d + 11 * MIN, 22); drain(); d = float(ho(22)["delivered_at"])
check("7 a busy peer: the reminder went once", len(texts("home-peer2", "a22")) == 2 and bool(ho(22).get("reminded_at")), pushes())
check("7 …and a pane still busy hours later gets no request to the -main agent", tick(d + 11 * MIN, 22) == [] and tick(d + 3 * 3600, 22) == [] and not main_recovery_pushes("a22") and not ho(22).get("recovery_at") and len(texts("home-peer2", "a22")) == 2, (ho(22), pushes()))
cli_row("home-peer2", "idle", d + 12 * MIN)
done = tick(d + 12 * MIN + 60, 22); drain()
check("7 …the pane's turn over with nothing written: the request goes to the -main agent, once", len(main_recovery_pushes("a22")) == 1 and bool(ho(22).get("recovery_at")), (done, ho(22), pushes()))
close(22)

# 7d. a project with a background agent keeps the cold rung exactly as before
cli_row("team-back", "idle", now0)
hcold_svc.COLD_RUNNER = lambda msg: (COLD_CALLS.append(msg), {"status": "ok", "text": "no json at all here", "duration_s": 0.1, "usage": {}, "note": "stub"})[1]
before = len(COLD_CALLS)
item(23, project="projects/alpha", mover="team-back", handoff=H.new_record("team-back", U["team-back"], "home-front", now0 - 3600, **{"delivered_at": now0 - 3500}))
tick(time.time() + 86400, 23); drain()
d = float(ho(23).get("delivered_at") or 0) or time.time()
tick(max(d, time.time()) + 86400 * 2, 23); drain()
check("7 a project with a background agent: the cold rung is taken as before (the stub was asked)", len(COLD_CALLS) > before, (len(COLD_CALLS), ho(23)))
close(23)

# what the reminder claims is what takes the item (H.started): a step marked done, a work line in progress or done; a note, or a work line only defined, does not
bef = {"status": "open", "metadata": {"owner": "o", "next": "x: a", "steps": [{"text": "x: a", "status": "open"}]}}
check("7 the reminder's claim is true: a work line set to in progress or to done takes the hand-off, a work line only defined and a note do not",
      bool(H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "in progress"}]}})) and bool(H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "done"}]}}))
      and not H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "defined"}]}}) and not H.started(bef, {**bef, "metadata": {**bef["metadata"], "next": "x: queued"}}), None)

# 7e. the request's "what the ladder tried" follows the record: a pane that is gone before the clock runs out was never reminded (ladder off) or asked (ladder on)
set_cfg(cold_call=False)
cli_row("home-peer2", "idle", now0)
put(24)
r = hand(24, "home-peer2"); d = float(r["delivered_at"])
no_row("home-peer2"); set_gone("home-peer2")
done = tick(d + 2 * MIN, 24); drain()
mp = main_recovery_pushes("a24")
check("7 ladder off, the pane gone 2 minutes after the delivery: the request says the pane is gone and claims no reminder", done == ["a24"] and len(mp) == 1 and "What the ladder tried: the hand-off notice went to home-peer2; home-peer2's pane is gone." in mp[0][1]
      and not ho(24).get("reminded_at"), (done, mp, ho(24)))
close(24); set_gone("home-peer2", False)
_cfg.CFG["ladder"] = {"enabled": True}
cli_row("home-peer2", "idle", now0)
put(25)
r = hand(25, "home-peer2"); d = float(r["delivered_at"])
no_row("home-peer2"); set_gone("home-peer2")
done = tick(d + 2 * MIN, 25); drain()
mp = main_recovery_pushes("a25")
check("7 ladder on, the pane gone: the request says the pane is gone and claims neither the notice sent again nor a look", len(mp) == 1 and "What the ladder tried: the hand-off notice went to home-peer2; home-peer2's pane is gone." in mp[0][1]
      and "sent again" not in mp[0][1] and "looked at" not in mp[0][1], (done, mp))
close(25); set_gone("home-peer2", False)
_cfg.CFG["ladder"] = {}
# a pane that was reminded and is gone afterwards: the reminder is claimed, and the pane too
cli_row("home-peer2", "idle", now0)
put(26)
r = hand(26, "home-peer2"); d = float(r["delivered_at"])
tick(d + 11 * MIN, 26); drain(); d = float(ho(26)["delivered_at"])
no_row("home-peer2"); set_gone("home-peer2")
tick(d + 2 * MIN, 26); drain()
mp = main_recovery_pushes("a26")
check("7 reminded first and gone after: both are said", len(mp) == 1 and "went to home-peer2 and, with no work started after 10 min, one reminder; home-peer2's pane is gone." in mp[0][1], mp)
close(26); set_gone("home-peer2", False)
cli_row("home-peer2", "idle", now0)

# 7f. a notice that was only queued is not said to have gone
cli_row("home-peer2", "idle", now0)
item(29, project="projects/delta", mover="home-peer2", handoff=H.new_record("home-peer2", U["home-peer2"], "home-peer", now0 - 3600, queued="inbox", queued_at=now0 - 3500))
set_gone("home-peer2")
done = tick(time.time() + 3600, 29); drain()
mp = main_recovery_pushes("a29")
check("7 a notice that waited in the inbox and a pane that is gone: the request says the notice was queued, not that it went", len(mp) == 1 and "What the ladder tried: the hand-off notice was queued for home-peer2; home-peer2's pane is gone." in mp[0][1], (done, mp))
close(29); set_gone("home-peer2", False)

# ================================================================ 8. a hander that is no front agent (the front-only hand-over rule lets any listed session hand over): the item is never returned to it
cli_row("home-peer2", "idle", now0); cli_row("team-back", "idle", now0)
set_cfg(cold_call=False)
item(30, project="projects/delta", mover="home-peer2", handoff=H.new_record("home-peer2", U["home-peer2"], "team-back", now0 - 3600, **{"delivered_at": now0 - 3500}))
check("8 a background agent of another project handing over to the front-only project's front agent is a peer hand-off", handoff_svc.handoff_peer({**rd(30), "gid": "a30"}, "home-peer2"), ho(30))
tick(now0 + 11 * MIN, 30); drain(); d = float(ho(30)["delivered_at"])
check("8 ladder off, after the first clock: the new mover is reminded (once), the hander told nothing", bool(ho(30).get("reminded_at")) and len(texts("home-peer2", "a30")) == 1 and not pushes_to("team-back", "a30"), (ho(30), pushes()))
done = tick(d + 11 * MIN, 30); drain()
mp = main_recovery_pushes("a30")
check("8 …after the second clock the request goes to the -main agent and the mover is unchanged: the item does not go back to the hander", len(mp) == 1 and mt(30).get("mover") == "home-peer2" and ho(30).get("to") == "home-peer2" and bool(ho(30).get("recovery_at")), (done, mt(30), ho(30), mp))
check("8 …and the hander got nothing at any step: no 'it came to you', no 'comes back to you', no request", not pushes_to("team-back", "a30"), pushes_to("team-back", "a30"))
close(30)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
