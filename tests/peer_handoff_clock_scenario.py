"""Scenario test for the take clock on a peer hand-off: in a front-only project (anchors.front_only: its `agents:` map lists no `background:` agent, so no builder) one front agent hands an item to another with `mover=`;
that hand-off is clocked like a builder's, and the item is the new mover's: only the new mover is reminded, the ladder ends at the project's -main agent, and the hander is told nothing at any point. A project with a
builder, a hand-off to another project's front agent and one to the -main agent itself keep the old exemption. Fixture data (English stand-in names) in a temporary store, the push replaced by a recorder, no network,
no model call.

  1  the clock, ladder off: the notice reaches the new mover once; before the take minutes nothing more (a turn that ended on the new mover's pane does not hurry it); after them ONE `handoff` reminder to the new mover
     alone; after another take minutes the last rung asks the project's -main agent (marked for the owner); the hander and the fleet's builder get nothing at any step
  2  the clock, ladder on: the take minutes bring the item to the one ladder, its ask is the notice again to the new mover (a `handoff` push), the look after it likewise, then the -main agent is asked; the hander gets nothing
  3  a mover that starts work (a work line in progress) before the clock, or after the reminder, stops it
  4  exempt as before: a project with a builder (a front-to-front record), a hand-off to another project's front agent, a hand-off to the -main agent itself, a hand-off the server made (`from` is no front agent)
  5  the pieces on their own: handoff_exempt / handoff_peer for each shape, the reminder target of a peer (a front role) against a background agent's, `Env.peer` defaulting to the old rule
  6  the hander is the -main agent: the last rung still asks it (it is the project's escalation point), pinned

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
def main_recovery_pushes(gid): return [p for p in pushes_to("home-delta-main", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, marked for the owner
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
check("1 …the hander, the project's -main agent and the fleet's builder are told nothing", not pushes_to("home-peer") and not pushes_to("home-delta-main") and not pushes_to("home-fleet"), pushes())
check("1 …and nothing goes down the ladder before the next take minutes", tick(d1b + 5 * MIN, 1) == [] and not ho(1).get("recovery_at"), ho(1))
done = tick(d1b + 11 * MIN, 1); drain()
mp = main_recovery_pushes("a1")
check("1 after another take minutes the last rung asks the project's -main agent, once, marked for the owner, naming the item and the quiet new mover", done == ["a1"] and len(mp) == 1 and mp[0][1].startswith(f"[for {OWN}]\n[stackshot] a1 ")
      and "home-peer2" in mp[0][1] and bool(ho(1).get("recovery_at")) and ho(1).get("recovery_by") == "the project's -main agent", (done, mp, ho(1)))
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
check("2 the look and the last rung follow: the new mover is asked once more, then the -main agent is asked once (marked for the owner)", len(main_recovery_pushes("a4")) == 1 and main_recovery_pushes("a4")[0][1].startswith(f"[for {OWN}]\n[stackshot] a4 ")
      and len(texts("home-peer2", "a4")) >= 3, (pushes(), ent, stall_svc.stall_load().get("a4")))
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
close(14)

# ================================================================ 6. the hander is the -main agent
put(15, mover="home-delta-main")
cli_row("home-peer2", "busy", now0)
r = hand(15, "home-peer2", sender="home-delta-main"); d15 = float(r["delivered_at"])
tick(d15 + 11 * MIN, 15); drain(); d15b = float(ho(15)["delivered_at"])
tick(d15b + 11 * MIN, 15); drain()
check("6 the hander is the -main agent: the reminder goes to the new mover, and the last rung still asks the -main agent (the project's escalation point: a request about a quiet session, no note to the hander)",
      len(texts("home-peer2", "a15")) == 2 and len(main_recovery_pushes("a15")) == 1 and "home-peer2" in main_recovery_pushes("a15")[0][1], pushes())
close(15)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
