"""Scenario test for where the stall ladder ends (server._recovery_target, _recovery_tell, the `recover` step of handoff.next_step): a front-only project (anchors.front_only: its `agents:` map lists no
`background:` agent, so there is no builder to try) ends at its -main agent, marked for the owner as every message to a front agent is, instead of the fleet's builder; a project with a builder is
unchanged. Fixture data (English stand-in names) in a temporary store, the push replaced by a recorder, no network, no model call.

  1  the stall ladder in a front-only project: the cold call off, no builder, so the last rung asks the project's -main agent, once: one message marked `[for <owner>]` on its first line, naming the item and the
     quiet session and asking it to decide; the fleet's builder is told nothing; the History line says who was asked; the item stays with its mover and is not on the owner's list; later passes send nothing
  2  a project with a builder is unchanged: its builder is the first choice, and when the quiet session is that builder itself the last rung still asks the fleet's builder (unmarked, `fleet recovery:`), not the -main agent
  3  a front-only project whose quiet mover is its -main agent itself, and one with no -main agent to name: the fleet's builder is asked, as before
  4  the choice on its own (server._recovery_target: the recipient, its kind, whether the project is builderless) for each shape, a front-only test that raises keeps the fleet's builder (one line on stderr)
  5  what the request says: the target is computed once per request; the hand-off record (`recovery_by`), its event, `get`'s line, the journal note and the History line name who was actually asked; "what
     the ladder tried" never claims a builder for a front-only project, whether its -main agent or the fleet's builder is asked, in the stall ladder and the hand-off ladder alike; a project with a builder keeps its old words

    tests/run-suite front_only_ladder        -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stalltest-"); T = pathlib.Path(tmp)
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
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-peer3", "home-send", "home-beta-front", "home-stew", "home-beta-stew", "home-fleet")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_OFFSET = 4 * 3600                                                                  # the instance zone is Asia/Dubai: UTC+4, no daylight saving
ZONE_ABBR = "+04"                                                                       # its strftime %Z abbreviation
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: front home-front; background home-docs (listed first) and team-back (builds); beta: a front agent and no background agent (nobody to build)
ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
    "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"})):
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
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:97]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import handoff as H; from stackshot.waits import stall as S
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
def main_recovery_pushes(gid): return [p for p in pushes_to("home-beta-front", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, marked for the owner
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
IDLE0 = B + 60.0                       # the pane went idle then: the first step is due at T1
T1 = IDLE0 + 10 * MIN + 1.0
T2 = T1 + 10 * MIN + 1.0

set_cfg(cold_call=False)
FLEET_ONLY = lambda gid: [p for p in pushes_to("home-fleet", gid)]
MAIN_ONLY = lambda gid: [p for p in pushes_to("home-beta-front", gid)]

# ================================================================ 1. a front-only project ends at its -main agent
item(1, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
check("1 step 1 (the notice again) sends nothing to -main or the fleet's builder", "a1" in stk(T1) and not MAIN_ONLY("a1") and not FLEET_ONLY("a1"), pushes())
done = stk(T2)
mp = MAIN_ONLY("a1")
check("1 nobody can take it (no builder in the project, cold call off): the record carries the request and the mover is unchanged", "a1" in done and bool(ho(1).get("recovery_at")) and mt(1).get("mover") == "home-peer3", (done, ho(1)))
check("1 …ONE message went to the project's -main agent, marked for the owner on its first line, naming the item and the quiet session, asking it to decide, owing no reply",
      len(mp) == 1 and mp[0][1].startswith(f"[for {OWN}]\n[stackshot] a1 ") and "home-peer3" in mp[0][1] and "decide" in mp[0][1] and "no builder" in mp[0][1] and "no reply is owed" in mp[0][1], mp)
check("1 …the fleet's builder was told nothing, and the quiet session got only the notice of step 1", not FLEET_ONLY("a1") and len(pushes_to("home-peer3", "a1")) == 1, pushes())
check("1 …the History line says the -main agent was asked, and what was tried without a builder", "home-peer3 is quiet" in log_of(1)[-1]["text"] and "home-beta-front was asked to recover it" in log_of(1)[-1]["text"]
      and "project's builder" not in log_of(1)[-1]["text"], log_of(1))
check("1 …the item is not on the owner's list, and later passes send nothing more", "decision" not in (mt(1).get("needs") or []) and not mt(1).get("ask") and stk(T2 + 21) == [] and stk(T2 + 5 * 3600) == [] and len(MAIN_ONLY("a1")) == 1, (mt(1), pushes()))
close(1)

# ================================================================ 2. a project with a builder is unchanged
item(2, mover="home-peer"); cli_row("home-peer", "idle", IDLE0)
stk(T1); stk(T2)
check("2 a project with a builder: the builder takes the item (the first choice, as before), and neither the -main agent nor the fleet's builder is asked", mt(2).get("mover") == "team-back" and ho(2).get("to") == "team-back"
      and not ho(2).get("recovery_at") and not pushes_to("home-front", "a2") and not FLEET_ONLY("a2"), (mt(2), ho(2), pushes()))
close(2)
item(3, mover="team-back"); cli_row("team-back", "idle", IDLE0)
stk(T1); stk(T2)
rp = FLEET_ONLY("a3")
check("2 …and when the quiet session is the builder itself, the last rung asks the fleet's builder, unmarked, in the old wording; the project's -main agent is told nothing",
      len(rp) == 1 and rp[0][1].startswith("[stackshot] fleet recovery: a3 ") and not rp[0][1].startswith("[for") and "usual path" in rp[0][1] and not pushes_to("home-front", "a3") and bool(ho(3).get("recovery_at")), (rp, ho(3), pushes_to("home-front", "a3")))
check("2 …the History line names the fleet's builder", "home-fleet was asked to recover it" in log_of(3)[-1]["text"], log_of(3))
close(3)

# ================================================================ 3. the -main agent is itself the quiet one; no -main agent to name
item(4, project="projects/beta", mover="home-beta-front"); cli_row("home-beta-front", "idle", IDLE0)
stk(T1); stk(T2)
check("3 a front-only project whose quiet mover is its -main agent: nobody is above it in the project, so the fleet's builder is asked (unmarked), and the -main agent is told nothing",
      len(FLEET_ONLY("a4")) == 1 and FLEET_ONLY("a4")[0][1].startswith("[stackshot] fleet recovery: a4 ") and not MAIN_ONLY("a4") and bool(ho(4).get("recovery_at")), (pushes_to("home-fleet", "a4"), MAIN_ONLY("a4"), ho(4)))
close(4)

CALLS = []
_real_tgt = server._recovery_target
def _counting(project, quiet):
    out = _real_tgt(project, quiet); CALLS.append((project, quiet, out)); return out
def rec(to, frm="home-send", **kw):
    """A hand-off record made by the machinery an hour ago (delivered, not taken), for an item that is written to disk with it."""
    return H.new_record(to, U[to], frm, now0 - 3600, **{"delivered_at": now0 - 3500, **kw})
# ================================================================ 5. what the request says: who was actually asked, what was tried, computed once
def ev_texts(i): return [e["text"] for e in ho(i).get("events", [])]
def msgs(gid, who): return [p[1] for p in pushes_to(who, gid)]
# (a) the -main agent was asked: every line that names the recipient says so, not the fleet's builder
item(10, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
CALLS.clear(); server._recovery_target = _counting
stk(T1); stk(T2)
server._recovery_target = _real_tgt
check("5 the target is computed once per request (the record, the wording of `tried` and the send follow the one answer)", len([c for c in CALLS if c[0] == "projects/beta" and c[1] == "home-peer3"]) == 1 and len(CALLS) == 1, CALLS)
check("5 …the hand-off record says who was asked, and its event line names the -main agent, not the fleet's builder", ho(10).get("recovery_by") == "the project's -main agent"
      and any("the project's -main agent was asked" in t for t in ev_texts(10)) and not any("fleet's builder" in t for t in ev_texts(10)), (ho(10), ev_texts(10)))
check("5 …`get` reads it the same way (the hand-off line)", any("the project's -main agent was asked to recover it" in l for l in H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x)) and not any("fleet" in l for l in H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x)), H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x))
check("5 …the journal note of the History write names the -main agent", any(g == "a10" and "the project's -main agent was asked" in n for g, n in NOTES) and not any(g == "a10" and "fleet" in n and "recovery" not in n for g, n in NOTES), [n for g, n in NOTES if g == "a10"])
check("5 …and what was tried says there was no builder (a stall record: the notice again and a fresh session's call)", any("What the ladder tried: the stall pass sent the notice again and asked a fresh session who takes it." in t for t in msgs("a10", "home-beta-front"))
      and not any("project's builder" in t for t in msgs("a10", "home-beta-front")), msgs("a10", "home-beta-front"))
_it10 = rd(10); H.touch(_it10, "home-peer3", U["home-peer3"], T2 + 60, handoff_svc.ho_same)
check("5 …the mover writing ends the request and the record forgets who was asked", not (_it10["metadata"]["handoff"].get("recovery_at") or _it10["metadata"]["handoff"].get("recovery_by")), _it10["metadata"]["handoff"])
close(10)

# (b) a front-only project whose quiet mover is its -main agent: the fleet's builder is asked, and no builder was tried (there is none)
item(11, project="projects/beta", mover="home-beta-front"); cli_row("home-beta-front", "idle", IDLE0)
stk(T1); stk(T2)
check("5 a quiet -main agent: the fleet's builder is asked, the record and the History line say so", ho(11).get("recovery_by") == "the fleet's builder" and any("the fleet's builder was asked" in t for t in ev_texts(11)) and bool(ho(11).get("recovery_at")), (ho(11), ev_texts(11)))
check("5 …and the request does not say the project's builder was tried: the project has none", len(FLEET_ONLY("a11")) == 1 and "What the ladder tried: the stall pass sent the notice again and asked a fresh session who takes it." in FLEET_ONLY("a11")[0][1]
      and "project's builder" not in FLEET_ONLY("a11")[0][1] and not any("project's builder" in x["text"] for x in log_of(11)), (FLEET_ONLY("a11"), log_of(11)))
close(11)

# (c) the hand-off ladder (a record that is no stall record): the same, in the hand-off ladder's words
item(12, project="projects/beta", mover="home-beta-front", handoff=rec("home-beta-front"))
hcold_svc.handoff_recover("a12", "home-beta-front did not take it"); drain()
check("5 the hand-off ladder, a quiet -main agent: the fleet's builder is asked and what was tried leaves out the project's builder", len(FLEET_ONLY("a12")) == 1 and "What the ladder tried: the hand-off ladder tried a fresh session's call and the sender." in FLEET_ONLY("a12")[0][1]
      and "project's builder" not in FLEET_ONLY("a12")[0][1], FLEET_ONLY("a12"))
close(12)
item(13, project="projects/beta", mover="home-peer3", handoff=rec("home-peer3"))
hcold_svc.handoff_recover("a13", "home-peer3 did not take it"); drain()
check("5 the hand-off ladder, a quiet session of a front-only project: its -main agent is asked, in its words, and what was tried leaves out the project's builder", len(MAIN_ONLY("a13")) == 1 and "the hand-off ladder tried a fresh session's call and the sender." in MAIN_ONLY("a13")[0][1]
      and "project's builder" not in MAIN_ONLY("a13")[0][1] and ho(13).get("recovery_by") == "the project's -main agent", (MAIN_ONLY("a13"), ho(13)))
close(13)

# (d) a project with a builder keeps the old words everywhere
item(14, mover="team-back"); cli_row("team-back", "idle", IDLE0)
stk(T1); stk(T2)
check("5 a project with a builder: the fleet's builder, `recovery_by` the same, and what was tried still names the project's builder", ho(14).get("recovery_by") == "the fleet's builder" and len(FLEET_ONLY("a14")) == 1
      and "asked a fresh session who takes it and tried the project's builder." in FLEET_ONLY("a14")[0][1], (ho(14), FLEET_ONLY("a14")))
close(14)

# (e) the text a session reads in `get`'s description (the stall form) names the -main agent as well as the fleet's builder
check("5 the served stall form says where a recovery message goes: a front-only project's -main agent, else the fleet's builder (it said the fleet's builder only)",
      "the project's -main agent when the project lists no background agent, to the fleet's builder otherwise" in _wt_get._STALL_FORM and "the fleet's builder is sent one message" not in _wt_get._STALL_FORM, _wt_get._STALL_FORM[:200])

# ================================================================ 4. the choice on its own
tgt = server._recovery_target
check("4 a front-only project with a -main agent -> (that agent, main)", tgt("projects/beta", "home-peer3") == ("home-beta-front", "main", True), tgt("projects/beta", "home-peer3"))
check("4 …the quiet session is that agent (by name or by id) -> the fleet's builder", tgt("projects/beta", "home-beta-front") == ("home-fleet", "fleet", True) and tgt("projects/beta", U["home-beta-front"]) == ("home-fleet", "fleet", True), (tgt("projects/beta", "home-beta-front"), tgt("projects/beta", U["home-beta-front"])))
check("4 a project with a builder -> the fleet's builder, whoever is quiet", tgt("projects/alpha", "home-peer") == ("home-fleet", "fleet", False) and tgt("projects/alpha", "team-back") == ("home-fleet", "fleet", False), tgt("projects/alpha", "home-peer"))
check("4 a project nobody lists (front-only, no -main agent to name: builderless) and an empty project (no read made: not builderless) -> the fleet's builder", tgt("projects/nowhere", "home-peer") == ("home-fleet", "fleet", True) and tgt("", "home-peer") == ("home-fleet", "fleet", False), (tgt("projects/nowhere", "home-peer"), tgt("", "home-peer")))
_real_fo = _anc.front_only
_anc.front_only = lambda *a, **k: 1 / 0
import io, contextlib
with contextlib.redirect_stderr(io.StringIO()) as eb: boom = tgt("projects/beta", "home-peer3")
_anc.front_only = _real_fo
check("4 a front-only test that raises keeps the fleet's builder and says so on stderr", boom == ("home-fleet", "fleet", False) and "front-only test of projects/beta failed" in eb.getvalue(), (boom, eb.getvalue()))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
