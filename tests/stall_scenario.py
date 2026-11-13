"""Scenario test for the stall pass (stall.py, service/stall_tick.py stall_tick) — fixture data, no live store, no network, no server socket.

When the session that moves a live item has no turn running for 10 minutes, stackshot moves the item on itself. The signal is the CLI's registry (handoff_svc.handoff_status: a live pane's
status busy | idle and when it changed); the clocks are given to the pass as `now`, the panes' rows are files in a temp folder.

  1  the ladder: the notice again at 10 minutes of no turn, the cold call 10 minutes after that, then the project's builder (a cold call that gave nothing falls to it at once)
  2  the cold call off: the second step is the builder
  3  nobody can take it (a project with no builder, so front-only): the last rung, ONE message to the project's -main agent per episode (the fleet's builder when the quiet mover is the -main agent itself, test 14) with a History line, the item left with its mover and not on the owner's list;
     a second pass sends nothing; an item that moves (its mover writes) starts a new episode that may ask again
  4  a front agent's item is covered but never sent a notice (step 1 is a History line, the recovery request is not pushed to it); the cold call's answer is written to the item
  4b the stall ladder's cold call never asks Oliver: an ask_owner, a none or an unusable answer is not written and the item goes on to the builder at once (a History line and a journal
     line say so); a hand_to still hands; the ordinary hand-off cold call answering ask_owner still asks him
  5  exempt, untouched: a hold, the owner's decision, an external wait, a hand-off in flight, an item whose recovery was already asked, a pane the registry does not show, a busy pane, a closed item
  6  a turn starting restarts the clock: before the first step, and between two steps
  6b a pane with a background Bash task shows `shell`, which counts as idle; a busy pane (a background subagent) is left alone
  7  a write to the item restarts the ladder
  8  the delays are config keys ([stall] minutes, every_seconds, enabled), and the pass is off with [model] handoff off
  9  the cold call is made once per item in 24 hours: past it the builder takes the step
  10 History: each step is a line; get shows the last steps
  11 (retired with the news ask: the overlap between the stall ladder and that pass)
  12 a deploy: the first pass sends nothing for 10 minutes (no clock starts before the pass first ran, kept in stall.json), and at most [stall] max_per_tick first steps go out a tick
  13b a background agent whose pane shows `shell` (a background job running) is not quiet; a front agent's `shell` pane and a builder's `idle` pane are nudged
  13 a quiet builder is nudged at once: a `doing` item carries no expected time, so the pass waits for none (a time stored by an earlier version is not read)
  14 the 24-hour bound on a kept item (+23 h nothing, +25 h the ladder runs again), a restart (the state is the file's), a front agent's recovery request is not pushed to it
  15 the builder taking the item ends the stall flag on its record
  16 an item is looked at only when its work is due now: a wake with a wait_basis ahead (a bare wake is only a reminder), a hold with a dated wake, an `after` an open item, a wait on the owner or an outsider leave it alone and leave no record; once due it is stepped as before, its minutes counted from then
  17 a pause of the pass ends on its own: [stall] paused_until holds it until then; enabled = false holds it at most [stall] max_pause_hours (4) from when the server first saw it, a restart keeping that
     start (<state>/stall_pause.json); a paused_until beyond the cap is cut to it; one journal line at the start and one at the end (and a routing-log line); doctor, the start and a reload name the end
  18 an agent never switches the pass off: a pause is honored only when [stall] pause_item names a board item with Oliver's own answer dated within 4 hours of when
     the server first saw the setting; refused (no pause_item, no such item, no answer, an answer too old, an answer a session wrote) the pass keeps running and ONE journal line says why, once per config
     load (not per tick), doctor and the reload show it; his answer given later honors it; no pause is longer than 24 hours (max_pause_hours and a paused_until beyond it are cut to 24)

    tests/run-suite stall        → exit 0 / 1"""
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
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
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import ladder as ladder_svc, stall as stall_svc, stall_tick as stalltick_svc
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
# the record follows the mover (handoff.stale): checked after every save of the run, the stall pass's moves and raises included
_real_save = writes.save
INV_BAD = []; INV_SAVES = [0]
def _save_inv(gid, item, *a, **kw):
    out = _real_save(gid, item, *a, **kw)
    INV_SAVES[0] += 1
    if H.stale(item, H.mover_of(item, lambda it: handoff_svc.ho_derive({**it, "gid": gid})), handoff_svc.ho_same): INV_BAD.append((gid, (item.get("metadata") or {}).get("handoff"), kw.get("note", "")))
    return out
writes.save = _save_inv
server._refuse_if_owing = lambda debtor: None
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
def set_cfg(**kw): server._cfg.CFG["model"] = dict(kw)
def set_stall(**kw):
    """The [stall] section as given. A pause (enabled = false, a paused_until) names the item as its pause_item unless the call says otherwise: an item that carries Oliver's own answer,
    dated far ahead so it counts at any clock below; section 18 tests the refusals with answers of its own."""
    if (kw.get("enabled") is False or kw.get("paused_until")) and "pause_item" not in kw: kw["pause_item"] = "a97"
    server._cfg.CFG["stall"] = dict(kw)
set_cfg(); set_stall()
server._cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder: the ladders' last rung asks it, once per episode, to recover a quiet session
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
OWN = server.OWNER
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

# ================================================================ 1. the ladder
item(1)
cli_row("home-peer", "idle", IDLE0)
check("1 ladder: 599 seconds of no turn is not enough", stk(IDLE0 + 599) == [] and not log_of(1) and not pushes_to("home-peer", "a1"), (log_of(1), pushes()))
done = stk(T1)
check("1 ladder: step 1, at 10 minutes of no turn: the notice goes to the mover once more, with the step written on the item", "a1" in done and len(pushes_to("home-peer", "a1")) == 1
      and "no turn running for 10 minutes" in pushes_to("home-peer", "a1")[0][1] and len(log_of(1)) == 1 and "sent to it again" in log_of(1)[0]["text"], (done, pushes(), log_of(1)))
check("1 ladder: …the item itself is as it was (mover, version): the step is no write by a session", mt(1)["mover"] == "home-peer" and rd(1)["updated"] == B and not COLD_MSGS, (mt(1), rd(1)["updated"]))
check("1 ladder: …and 5 minutes on, nothing", stk(T1 + 5 * MIN) == [] and len(log_of(1)) == 1, log_of(1))
T2 = T1 + 10 * MIN + 1.0
done = stk(T2)
check("1 ladder: step 2, 10 minutes after the notice: the cold call is asked (once)", len(COLD_MSGS) == 1 and '"item": "a1"' in COLD_MSGS[0] and len(log_of(1)) >= 2 and "cold call" in log_of(1)[1]["text"], (done, COLD_MSGS[:1], log_of(1)))
check("1 ladder: …it gave nothing: the item falls on at once to the project's builder (not back to a sender), still a stall record", mt(1).get("mover") == "team-back" and ho(1).get("to") == "team-back" and ho(1).get("via") == "redirect"
      and ho(1).get("stall") is True and (ho(1).get("cold") or {}).get("state") == "failed" and len(pushes_to("team-back", "a1")) >= 1, (mt(1), ho(1), pushes()))
n_push1, n_cold1 = len(pushes()), len(COLD_MSGS)
later = stk(T2 + 3 * 3600)
check("1 ladder: …no cold call was made again, the item is the builder's now and its pane (no registry row) is left alone: nothing acts on it, nothing is sent", "a1" not in later and mt(1).get("mover") == "team-back"
      and len(COLD_MSGS) == n_cold1 and len(pushes()) == n_push1, (later, mt(1), pushes()[n_push1:]))
close(1)

# ================================================================ 2. the cold call off
set_cfg(cold_call=False)
item(2, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
check("2 cold off: step 1 as always", "a2" in stk(T1) and len(log_of(2)) == 1, log_of(2))
n_cold = len(COLD_MSGS)
done = stk(T2)
check("2 cold off: step 2 is the builder, with no cold call", "a2" in done and len(COLD_MSGS) == n_cold and mt(2).get("mover") == "team-back" and ho(2).get("to") == "team-back" and ho(2).get("stall") is True
      and "project's builder" in log_of(2)[-1]["text"], (done, mt(2), log_of(2)))
close(2); set_cfg()

# ================================================================ 3. nobody can take it: the last rung, one message to the fleet's builder per episode
set_cfg(cold_call=False)
item(3, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
check("3 recovery: step 1", "a3" in stk(T1) and not main_recovery_pushes("a3"), log_of(3))
done = stk(T2)
m3 = mt(3)
check("3 recovery: no builder in the project and the cold call off: nobody can take it: the mover is unchanged and the item is not returned to a sender, and the record carries the request",
      "a3" in done and bool(ho(3).get("recovery_at")) and ho(3).get("stall") is True and ho(3).get("to") == "home-peer3" and m3.get("mover") == "home-peer3" and "stuck" not in ho(3) and "stuck_reason" not in ho(3), (done, ho(3), log_of(3)))
check("3 recovery: …a History line says which session is quiet, who was asked and what was tried", "home-peer3 is quiet" in log_of(3)[-1]["text"] and "home-beta-front was asked to recover it" in log_of(3)[-1]["text"] and "tried:" in log_of(3)[-1]["text"], log_of(3))
rp = main_recovery_pushes("a3")
check("3 recovery: …exactly one message went to the project's -main agent (beta lists no background agent, so there is no builder to ask), marked for the owner on its first line, then `[stackshot] <item> …`, naming the quiet session and asking it to decide; it owes no reply; the fleet's builder was not asked",
      len(rp) == 1 and rp[0][1].startswith(f"[for {OWN}]\n[stackshot] a3 ") and "home-peer3" in rp[0][1] and "decide" in rp[0][1] and "no reply is owed" in rp[0][1] and not recovery_pushes("a3"), rp)
check("3 recovery: …nothing went to the quiet session or the project's front, and the item is not on the owner's list: no decision in needs, no ask, no options, no idle raise, and the model keeps its session as the mover",
      len(pushes_to("home-peer3", "a3")) == 1 and "decision" not in (m3.get("needs") or []) and not m3.get("ask") and not m3.get("options") and not (m3.get("idle") or {}).get("raised")
      and not server._model_of({**rd(3), "gid": "a3"}).owner_moves, (pushes_to("home-peer3", "a3"), m3))
T3 = T2 + 21.0
check("3 recovery: a second pass sends nothing, and neither do later ones: still one message, no raise, the entry carries no stuck mark", stk(T3) == [] and stk(T3 + 5 * 3600) == [] and len(main_recovery_pushes("a3")) == 1 and "decision" not in (mt(3).get("needs") or []), (main_recovery_pushes("a3"), mt(3)))
# the guard is the record's, not the pass's memory: with the pass's entry for the item lost (a file wiped, a restart that lost it) the ladder walks its steps again from the top and must not ask a second time
_st = stall_svc.stall_load(); _st.pop("a3", None); stall_svc.stall_save(_st)
X3 = T3 + 3 * 3600
walked = stk(X3) + stk(X3 + 11 * MIN) + stk(X3 + 22 * MIN) + stk(X3 + 33 * MIN)
check("3 recovery: …and the request is once per record, not per pass: with the pass's own entry wiped the ladder walks again and still sends no second message", len(main_recovery_pushes("a3")) == 1 and bool(ho(3).get("recovery_at"))
      and sum("was asked to recover it" in x["text"] for x in log_of(3)) == 1, (walked, main_recovery_pushes("a3"), log_of(3)))
check("3 recovery: …the journal-side brief and the board list no stuck line for it", "stuck" not in handoff_svc.handoff_brief().lower() and all("stuck" not in ln for ln in H.brief_lines({"a3": rd(3)}, time.time())), handoff_svc.handoff_brief()[-300:])
# the mover writing to the item ends the episode: the ladder starts over, and a later episode may ask again (one message for each)
server._update("a3", sender="home-peer3", next="home-peer3: back at it")
floor3 = rd(3)["updated"]
check("3 episode: the mover's own write ends the episode: the request is cleared from the record", not ho(3).get("recovery_at") and not ho(3).get("recovery_reason") and len(main_recovery_pushes("a3")) == 1, ho(3))
at3 = max(floor3, ho(3).get("at") or 0)      # the stall record's own stamp (a pass at a time ahead of the clock made it) counts as the item reaching its mover
check("3 episode: …the ladder starts over from the write: nothing for 10 minutes, then step 1 again with no new message", stk(at3 + 5 * MIN) == [] and "a3" in stk(at3 + 10 * MIN + 5) and len(main_recovery_pushes("a3")) == 1, (ho(3), log_of(3)))
done = stk(at3 + 20 * MIN + 10)
check("3 episode: …and at the last rung the new episode asks once more: two messages in all, one for each episode, and a second History line", "a3" in done and len(main_recovery_pushes("a3")) == 2 and bool(ho(3).get("recovery_at"))
      and sum("was asked to recover it" in x["text"] for x in log_of(3)) == 2, (done, main_recovery_pushes("a3"), log_of(3)))
check("3 episode: …and that one is not repeated either", stk(at3 + 20 * MIN + 40) == [] and stk(at3 + 6 * 3600) == [] and len(main_recovery_pushes("a3")) == 2, main_recovery_pushes("a3"))
# an item that moves to another session (not by its mover's write) ends the record too: the new mover's ladder is its own
writes.save("a3", {**rd(3), "metadata": {**mt(3), "mover": "home-peer2", "next": "home-peer2: take over"}})
check("3 episode: …a server save that moves the item on ends the record as handed on: no request is carried to the new mover", not ho(3).get("recovery_at") and ho(3).get("to") == "home-peer2" and len(main_recovery_pushes("a3")) == 2, (ho(3), mt(3).get("handoff_history")))
close(3); set_cfg()

# ================================================================ 4. a front agent's item is covered
cold({"action": "hand_to", "to": "home-docs", "reason": "it is the project's own work"})
item(4, mover="home-front"); cli_row("home-front", "idle", IDLE0)
done = stk(T1)
check("4 front: an item a front agent moves is covered, but no notice wakes a front agent: step 1 is the History line alone, no push", "a4" in done and not pushes_to("home-front", "a4") and len(log_of(4)) == 1
      and "front agent" in log_of(4)[0]["text"] and stall_svc.stall_load()["a4"]["step"] == 1, (done, pushes(), log_of(4)))
n_cold = len(COLD_MSGS)
done = stk(T2)
check("4 front: …the cold call hands it on to the session it names, written as the cold call", len(COLD_MSGS) == n_cold + 1 and mt(4).get("mover") == "home-docs" and rd(4).get("written_by") == "cold-call"
      and (ho(4).get("cold") or {}).get("state") == "done", (done, mt(4), rd(4).get("written_by"), ho(4)))
close(4); cold("no json at all here")

# ================================================================ 4b. the stall ladder's cold call never asks Oliver
import io, contextlib; from stackshot.model import cold_call as CC; from stackshot.router import router as RT
ASK_ANS = {"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "wait", "line": "Hold it a week.", "recommended": False}]}
def two_steps(i, mover="home-peer2"):
    """An item stepped to its cold call (the notice at T1, the cold call at T2) → the journal text of the second pass."""
    item(i, mover=mover); cli_row(mover, "idle", IDLE0)
    stk(T1)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        stk(T2)
    return err.getvalue()
cold(ASK_ANS); n_cold = len(COLD_MSGS)
journal = two_steps(90)
check("4b no ask: a stall cold call that answers ask_owner asks nobody: no decision, no ask, no options, no state your-call on the item", len(COLD_MSGS) == n_cold + 1 and "decision" not in (mt(90).get("needs") or [])
      and not mt(90).get("ask") and not mt(90).get("options") and mt(90).get("state") != "your-call" and rd(90).get("written_by") != "cold-call", (mt(90), rd(90).get("written_by")))
check("4b no ask: …the ladder went on to step 3 at once: the project's builder has the item, still a stall record, the cold step ended and no recovery is asked or raised",
      mt(90).get("mover") == "team-back" and ho(90).get("to") == "team-back" and ho(90).get("stall") is True and (ho(90).get("cold") or {}).get("state") == "done"
      and not ho(90).get("recovery_at") and not recovery_pushes("a90") and len(pushes_to("team-back", "a90")) >= 1, (mt(90), ho(90)))
check("4b no ask: …a History line (metadata.stall.log) and a journal line say the cold call named no taker", any("named no taker" in x["text"] and "builder" in x["text"] for x in log_of(90))
      and "stall: a90 cold call named no taker: to the builder" in journal, (log_of(90), journal))
close(90)
cold({"action": "none", "reason": "nothing in the record says who owns it"})            # none: the same, and the 24-hour bound still stamps the cold call
journal = two_steps(91)
check("4b no ask: …a none answer is the same: nothing written, the builder next", "decision" not in (mt(91).get("needs") or []) and not mt(91).get("ask") and mt(91).get("mover") == "team-back"
      and ho(91).get("stall") is True and "stall: a91 cold call named no taker: to the builder" in journal, (mt(91), ho(91)))
check("4b no ask: …and the cold call is stamped for its 24 hours", stall_svc.stall_load().get("a91", {}).get("cold_at"), stall_svc.stall_load().get("a91"))
close(91)
cold("no json at all here")                                                             # an answer the call could not give: the same
journal = two_steps(92)
check("4b no ask: …an unusable answer is the same", "decision" not in (mt(92).get("needs") or []) and mt(92).get("mover") == "team-back" and (ho(92).get("cold") or {}).get("state") == "failed"
      and "named no taker" in journal, (mt(92), ho(92), journal))
close(92)
cold({"action": "hand_to", "to": "home-docs", "reason": "it is the project's own work"})      # a taker named: handed, as before
two_steps(93)
check("4b no ask: a stall cold call that names a live session still hands the item to it, written as the cold call", mt(93).get("mover") == "home-docs" and rd(93).get("written_by") == "cold-call"
      and (ho(93).get("cold") or {}).get("state") == "done" and not any("named no taker" in x["text"] for x in log_of(93)), (mt(93), ho(93), log_of(93)))
close(93)
# the ladder's last rung: no builder in the project, so its -main agent is asked (the stall cold call asked the owner nothing before it, and the last rung asks him nothing either)
cold(ASK_ANS)
item(94, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
stk(T1); stk(T2)
check("4b no ask: …with no builder in the project the cold call's ask_owner is still not written: the ladder's last rung asks the -main agent once and the owner nothing",
      ho(94).get("recovery_at") and len(main_recovery_pushes("a94")) == 1 and "decision" not in (mt(94).get("needs") or []) and not mt(94).get("ask"), (mt(94), ho(94), main_recovery_pushes("a94")))
stk(T2 + 21)
check("4b no ask: …and a later pass raises nothing and asks nobody again", "decision" not in (mt(94).get("needs") or []) and not mt(94).get("options") and len(main_recovery_pushes("a94")) == 1 and rd(94).get("written_by") != "cold-call", (mt(94), ho(94)))
close(94)
# the ordinary hand-off cold call is unchanged: ask_owner still asks him
item(95, mover="home-peer2", handoff={**H.new_record("home-peer2", U["home-peer2"], "home-send", B + 30, delivered_at=B + 40), "cold": {"at": T1, "state": "running"}})
cold(ASK_ANS); hcold_svc.handoff_cold("a95", T1)
check("4b no ask: …the ordinary (non-stall) hand-off cold call answering ask_owner still asks Oliver: a decision with its ask and options, written as the cold call",
      "decision" in (mt(95).get("needs") or []) and mt(95).get("ask") == ASK and len(mt(95).get("options") or []) == 2 and rd(95).get("written_by") == "cold-call", (mt(95), ho(95)))
close(95); cold("no json at all here")
# the pure half: the stall rubric offers hand_to and close, never ask_owner; the ordinary one is as it was; validate and parse
seen = {}
_real_run_call = RT.run_call
RT.run_call = lambda message, rubric: seen.update(rubric=rubric) or {"status": "ok", "text": '{"action": "none", "reason": "x"}'}
try:
    st_stall = CC.run("m", None, stall=True); st_plain = CC.run("m", None)
finally:
    RT.run_call = _real_run_call
check("4b pure: the stall call runs with STALL_RUBRIC (hand_to, close, none; no ask_owner offered) and reads none; the ordinary call has no none", '"action": "ask_owner"' not in CC.STALL_RUBRIC and '"action": "none"' in CC.STALL_RUBRIC
      and '"action": "ask_owner"' in CC.RUBRIC and "When unsure, ask Oliver." in CC.RUBRIC and "When unsure, answer none." in CC.STALL_RUBRIC and st_stall[1] == {"action": "none", "reason": "x"} and st_plain[1] is None, (st_stall, st_plain))
check("4b pure: validate(stall=True): ask_owner and none are `none`; hand_to and close as before; without stall ask_owner validates as before and none is unknown",
      CC.validate(ASK_ANS, set(), stall=True)[0]["action"] == "none" and CC.validate({"action": "none"}, set(), stall=True)[0]["action"] == "none"
      and CC.validate({"action": "hand_to", "to": "x"}, {"home-docs"}, stall=True)[0] is None and CC.validate({"action": "hand_to", "to": "home-docs"}, {"home-docs"}, stall=True)[0]["to"] == "home-docs"
      and CC.validate(ASK_ANS, set())[0]["action"] == "ask_owner" and CC.validate({"action": "none"}, set())[0] is None, None)

# ================================================================ 5. exempt, untouched
cli_row("home-peer", "idle", IDLE0); cli_row("home-peer2", "idle", IDLE0); cli_row("team-back", "idle", IDLE0); cli_row("home-peer3", "busy", IDLE0)
item(10, hold=True, wake=FUT)
item(11, mover="", needs=["decision"], ask=ASK, next=f"{OWN}: decide")
item(12, needs=["external"], next="a vendor: reply")
item(13, mover="home-peer2", handoff=H.new_record("home-peer2", U["home-peer2"], "home-send", B + 30, delivered_at=B + 40))
item(15, handoff={**H.new_record("home-peer", U["home-peer"], "home-send", B + 30, delivered_at=B + 40), "recovery_at": B + 50, "recovery_reason": "nobody could take it"})
item(16, mover="home-send")                                    # no registry row on this box: nothing can be told
item(17, mover="home-peer3")                                   # a turn is running
item(18, mover="home-peer", status="completed")
before = {i: rd(i) for i in (10, 11, 12, 13, 15, 16, 17, 18)}
done = stk(IDLE0 + 5 * 3600) + stk(IDLE0 + 6 * 3600)
check("5 exempt: a hold, the owner's decision, an external wait, a hand-off in flight, an item whose recovery was already asked, an unknown pane, a busy pane and a closed item: untouched",
      not (set(done) & {f"a{i}" for i in before}) and all(rd(i) == before[i] for i in before), done)
check("5 exempt: …none got a step, a push or an entry", not (set(done) & {f"a{i}" for i in before}) and all(rd(i) == before[i] for i in before) and not [p for p in pushes() if any(f"a{i}:" in p[1] or f"a{i}," in p[1] for i in before)]
      and not [g for g, r in stall_svc.stall_load().items() if g in {f"a{i}" for i in before} and int(r.get("step") or 0) > 0], (done, stall_svc.stall_load()))
close(10, 11, 12, 13, 15, 16, 17)
# ranks are retired: an item that still stores one (a store from before the cleanup) is stalled like any other
item(19, mover="home-peer", rank=1)
done = stk(IDLE0 + 7 * 3600)
check("5 rank: an item that still stores a rank is no longer skipped: its mover's idle pane gets the first step like any other item", "a19" in done and len(log_of(19)) >= 1, (done, log_of(19)))
close(19)
no_row("team-back"); cli_row("home-peer3", "idle", IDLE0)

# ================================================================ 6. a turn starting restarts the clock
item(20); cli_row("home-peer", "busy", IDLE0 + 440)            # a turn started at IDLE0 + 440 and is running
check("6 turn: a pane whose turn is running is not stalled, however long since the item reached it", stk(T1 + 30 * MIN) == [], log_of(20))
cli_row("home-peer", "idle", T1 + 30 * MIN - 96)              # the turn ended; the count starts there
check("6 turn: …the turn ended with no write: the count starts from its end (9 minutes later nothing, 10 on the notice)", stk(T1 + 30 * MIN - 96 + 9 * MIN) == [] and "a20" in stk(T1 + 30 * MIN - 96 + 10 * MIN + 1), log_of(20))
close(20)
item(21, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
stk(T1); n21 = len(log_of(21)); n_cold6 = len(COLD_MSGS)
cli_row("home-peer2", "busy", T1 + 96); cli_row("home-peer2", "idle", T1 + 400)      # a turn between the notice and the cold call
check("6 turn: …and a turn between two steps restarts the wait for the next (the cold call at 10 minutes after the turn ended, not after the notice)", n21 == 1 and stk(T1 + 10 * MIN + 1) == []
      and len(COLD_MSGS) == n_cold6 and "a21" in stk(T1 + 400 + 10 * MIN + 1) and len(log_of(21)) == 3 and "named no taker" in log_of(21)[2]["text"],     # the cold call (2nd line) gave nothing: a 3rd line says it went to the builder
      (log_of(21), COLD_MSGS[n_cold6:]))
close(21)

# ================================================================ 6b. a pane with a background Bash task shows `shell`, not `idle`
check("6b shell: pure: action() counts `shell` like `idle` (10 minutes on: resend; 9 minutes: nothing) and `busy` and an unknown pane never",
      S.action({"step": 0, "last": 0}, "shell", 100.0, 0, 100.0 + 601, 10.0) == "resend" and S.action({"step": 0, "last": 0}, "shell", 100.0, 0, 100.0 + 599, 10.0) == ""
      and S.action({"step": 0, "last": 0}, "busy", 100.0, 0, 100.0 + 601, 10.0) == "" and S.action({"step": 0, "last": 0}, "", 100.0, 0, 100.0 + 601, 10.0) == "", None)
item(90); cli_row("home-peer", "shell", IDLE0)                  # the turn is over, a run_in_background task runs
check("6b shell: a pane whose turn is over with a background Bash task running: 599 seconds nothing, then the step is taken as for an idle pane", stk(IDLE0 + 599) == [] and not log_of(90)
      and "a90" in stk(T1) and len(pushes_to("home-peer", "a90")) == 1 and len(log_of(90)) == 1, (log_of(90), pushes()))
close(90)
item(91); cli_row("home-peer", "busy", IDLE0)                   # a background subagent keeps the pane busy
check("6b shell: …a pane that is busy (a background subagent running) is left alone however long", stk(T1 + 5 * 3600) == [] and not log_of(91), log_of(91))
close(91); cli_row("home-peer", "idle", IDLE0)

# ================================================================ 7. a write restarts the ladder
item(22); cli_row("home-peer", "idle", IDLE0)
stk(T1)
server._update("a22", sender="home-peer", next="home-peer: still on it")
w22 = rd(22)["updated"]
check("7 write: a write to the item restarts the ladder (the version moved): no step at the old time", w22 > B and stk(T1 + 11 * MIN) == [], w22)
done = stk(w22 + 10 * MIN + 5)
check("7 write: …from the write, the notice again (step 1 of a new episode)", "a22" in done and S.log_of(mt(22))[-1]["text"].endswith("sent to it again") and len(pushes_to("home-peer", "a22")) == 2 and stall_svc.stall_load()["a22"]["step"] == 1, (done, stall_svc.stall_load().get("a22")))
close(22)

# ================================================================ 8. config
set_stall(minutes=3)
item(23, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
check("8 config: [stall] minutes = 3: the notice at 3 minutes, not before", stk(IDLE0 + 3 * MIN - 1) == [] and "a23" in stk(IDLE0 + 3 * MIN + 1) and "no turn running for 3 minutes" in pushes_to("home-peer2", "a23")[-1][1], pushes_to("home-peer2", "a23"))
close(23)
set_stall(enabled=False)
item(24, mover="home-peer2")
check("8 config: [stall] enabled = false: nothing", stk(IDLE0 + 5 * 3600) == [] and not log_of(24), log_of(24))
set_stall(every_seconds=600)
stall_svc.STALL_LAST[0] = 0.0; first = stalltick_svc.stall_tick(T1 + 5 * 3600); drain()
check("8 config: [stall] every_seconds = 600: a second pass 20 seconds after the first does nothing", "a24" in first and stalltick_svc.stall_tick(T1 + 5 * 3600 + 20) == [] and len(log_of(24)) == 1, (first, log_of(24)))
close(24); set_stall()
# the runner ticks the pass once a minute (the old fleet watch every 20 s): with the default gate of 20 s every tick of a minute pace runs the pass, a tick 20 s after one does not
stall_svc.STALL_LAST[0] = 0.0
stalltick_svc.stall_tick(T1 + 6 * 3600); l1 = stall_svc.STALL_LAST[0]
stalltick_svc.stall_tick(T1 + 6 * 3600 + 60); l2 = stall_svc.STALL_LAST[0]
stalltick_svc.stall_tick(T1 + 6 * 3600 + 80); l3 = stall_svc.STALL_LAST[0]
check("8 config: with the default every_seconds (20) a tick every 60 s (the minute pace) runs the pass each time, and a tick 20 s after a pass runs again too",
      l1 == T1 + 6 * 3600 and l2 == T1 + 6 * 3600 + 60 and l3 == T1 + 6 * 3600 + 80 and stall_svc.stall_num("every_seconds", server._stall.EVERY) == 20, (l1, l2, l3))
set_cfg(handoff=False)
item(25, mover="home-peer2")
check("8 config: [model] handoff = false: the pass does nothing (it moves items through the hand-off machinery)", stk(IDLE0 + 5 * 3600) == [] and not log_of(25), log_of(25))
close(25); set_cfg()
check("8 config: the example config documents the keys with their defaults", all(re.search(rf'(?m)^{k} = {v}\b', re.search(r'(?ms)^\[stall\][^\n]*\n(.*?)^\[', toml).group(1)) for k, v in (("enabled", "true"), ("max_pause_hours", "4"), ("minutes", "10"), ("every_seconds", "20"), ("max_per_tick", "5"))), toml[toml.find("[stall]"):][:400])

# ================================================================ 9. the cold call once per item in 24 hours
item(26, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
stall_svc.stall_save({"a26": {"mover": "home-peer2", "ver": [B, B], "step": 1, "last": T1, "cold_at": T1 - 3600}})
n_cold = len(COLD_MSGS)
done = stk(T2)
check("9 once a day: a cold call made for the item less than 24 hours ago is not made again: the step is the builder's", "a26" in done and len(COLD_MSGS) == n_cold and mt(26).get("mover") == "team-back" and ho(26).get("stall") is True, (done, mt(26), COLD_MSGS[n_cold:]))
check("9 once a day: pure: action() says cold for a stale stamp, builder for a fresh one", S.action({"step": 1, "last": 0, "cold_at": 1000.0}, "idle", 0.5, 0, 1000.0 + 90000, 10.0) == "cold"
      and S.action({"step": 1, "last": 0, "cold_at": 1000.0}, "idle", 0.5, 0, 1000.0 + 3600, 10.0) == "builder", None)
close(26)

# ================================================================ 10. History and get
item(27); cli_row("home-peer", "idle", IDLE0)
stk(T1)
from stackshot.web import render as R
shown = server._fmt({**rd(27), "gid": "a27"})
check("10 get: the last steps are shown on the item", re.search(r"stall: .*sent to it again", shown) is not None, shown[-600:])
new = S.new_entries({"stall": {"log": []}}, mt(27))
check("10 history: a new log entry is one History line (new_entries), an old one is not repeated", len(new) == 1 and not S.new_entries(mt(27), mt(27)), new)
close(27)

# ================================================================ 12. a deploy: no flood
for i in (40, 41, 42, 43, 44, 45):
    item(i, mover="home-peer")                                  # six items on one long-idle pane (idle for hours)
cli_row("home-peer", "idle", B - 5 * 3600)
stall_svc.stall_path().unlink(missing_ok=True)                  # no stall.json: the pass has never run on this store
X = now0 + 7 * 86400                                          # the first pass of the new deploy
check("12 deploy: the first pass sends nothing, though every pane has been idle for hours", stk(X) == [] and not any(log_of(i) for i in range(40, 46)), [log_of(i) for i in range(40, 46)])
check("12 deploy: …it recorded when it first ran in stall.json, and that survives the next passes", stall_svc.stall_raw().get("_pass", {}).get("since") == X and stk(X + 96) == [] and stall_svc.stall_raw()["_pass"]["since"] == X, stall_svc.stall_raw())
check("12 deploy: …nothing 599 seconds after it, either", stk(X + 599) == [], None)
set_stall(max_per_tick=2)
got = stk(X + 601)
check("12 deploy: …then at most [stall] max_per_tick (2) first steps a tick, not six", len(got) == 2, got)
got += stk(X + 622) + stk(X + 643)
check("12 deploy: …the rest follow on the next ticks, each once", sorted(got) == [f"a{i}" for i in range(40, 46)] and all(len(log_of(i)) == 1 for i in range(40, 46)) and stk(X + 664) == [], (got, [len(log_of(i)) for i in range(40, 46)]))
set_stall(); close(*range(40, 46))
check("12 deploy: the default cap is 5", S.MAX_PER_TICK == 5, S.MAX_PER_TICK)

# ================================================================ 13. a quiet builder is nudged at once: a doing item carries no expected time to wait for
def hhmm(ep): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ep + ZONE_OFFSET))      # the instance zone is Asia/Dubai
cli_row("team-back", "idle", IDLE0); cli_row("home-front", "idle", IDLE0)
stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
LATE = IDLE0 + 3 * 3600
item(50, mover="team-back", needs=["team-back"], state="doing", expected_by=hhmm(LATE))      # written before the time was dropped: the stored time is not read
item(51, mover="home-front", needs=["home-front"], state="doing", expected_by=hhmm(LATE))
item(52, mover="team-back", needs=["team-back"], state="doing")                           # a doing item with no time at all
d13 = stk(T1 + 2 * 3600)
check("13 doing: a quiet builder's doing item (stored with a time still ahead, or with none) is stepped at once, the front agent's too: the pass waits for no expected time",
      all(f"a{i}" in d13 for i in (50, 51, 52)) and all(len(log_of(i)) == 1 for i in (50, 51, 52)), (d13, log_of(50), log_of(51), log_of(52)))
check("13 doing: …a record is kept for each, as for any item the pass steps", all(f"a{i}" in stall_svc.stall_load() for i in (50, 51, 52)), stall_svc.stall_load())
check("13 doing: pure: not_due says nothing for a doing item, whatever expected_by it was stored with", S.not_due(rd(50), IDLE0) == "" and S.not_due(rd(52), IDLE0) == "" and S.due_at(rd(50)) == 0.0, (S.not_due(rd(50), IDLE0), S.due_at(rd(50))))
close(50, 51, 52); no_row("team-back")

# ---- 13b. a background agent whose pane shows `shell` (its turn is over, a run_in_background job such as a CI watch runs) is working on that job: not quiet
stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
item(53, mover="team-back", needs=["team-back"], state="doing"); cli_row("team-back", "shell", IDLE0)
item(54, mover="home-front", needs=["home-front"], state="doing"); cli_row("home-front", "shell", IDLE0)
d13b = stk(T1 + 2 * 3600)
check("13b background job: a background agent's `shell` pane is not nudged, however long (the job is its work); no record is kept", "a53" not in d13b and not log_of(53) and "a53" not in stall_svc.stall_load(), (d13b, log_of(53)))
check("13b background job: …a front agent does no background work of its own, so its `shell` pane counts as idle and is nudged", "a54" in d13b and len(log_of(54)) == 1, (d13b, log_of(54)))
check("13b background job: …the same builder's turn over with nothing running (`idle`) is nudged at once", (cli_row("team-back", "idle", IDLE0 + 2 * 3600), "a53" in stk(T1 + 4 * 3600))[1] and len(log_of(53)) == 1, log_of(53))
check("13b background job: pure: _stall_background is true for a background agent of a project page only", stall_svc.stall_background("team-back") and stall_svc.stall_background("home-docs") and not stall_svc.stall_background("home-front") and not stall_svc.stall_background("home-peer"), None)
close(53, 54); no_row("team-back"); no_row("home-front")

# ================================================================ 14. the 24-hour bound on a kept item, a restart, a front agent's recovery request
cli_row("home-peer2", "idle", IDLE0)
item(60, mover="home-peer2")
R = T1 + 100.0
stall_svc.stall_save({"a60": {"mover": "home-peer2", "ver": stall_svc.stall_ver(server._load("a60")), "step": 0, "last": R, "kept": R}})       # the cold call kept the item with its mover at R (the entry is carried into a new episode)
check("14 24 h: an item kept less than 24 hours ago is left alone, 23 hours on", stk(R + 23 * 3600) == [] and not log_of(60), log_of(60))
done = stk(R + 25 * 3600)
check("14 24 h: …and past 24 hours the ladder runs again (the notice, step 1)", "a60" in done and len(log_of(60)) == 1 and S.spent({"kept": R}, R + 25 * 3600) is False and S.spent({"kept": R}, R + 23 * 3600) is True, (done, log_of(60)))
close(60)
# a restart: the pass holds nothing in memory, its state is stall.json (steps, stamps)
item(61, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
set_cfg(cold_call=False)
stk(T1)
snap = stall_svc.stall_path().read_text(encoding="utf-8")
stall_svc.STALL_LAST[0] = 0.0
check("14 restart: step 1 is in the file (the episode, its stamps, when the pass first ran)", json.loads(snap)["a61"]["step"] == 1 and json.loads(snap)["a61"]["last"] == T1 and json.loads(snap)["_pass"]["since"] == B, snap[:400])
check("14 restart: …a pass that knows only the file does not send step 1 again (5 minutes on), and takes step 2 at its time", stk(T1 + 5 * MIN) == [] and len(log_of(61)) == 1 and "a61" in stk(T1 + 10 * MIN + 1) and mt(61).get("mover") == "team-back", (log_of(61), mt(61)))
close(61); set_cfg()
# a front agent's item (the project's -main agent itself is quiet, nobody is above it): the recovery request goes to the fleet's builder, never to the front agent
set_cfg(cold_call=False)
item(62, project="projects/beta", mover="home-beta-front"); cli_row("home-beta-front", "idle", IDLE0)
stk(T1); n_push62 = len(pushes()); done = stk(T2)
check("14 front recovery: nobody can take a front agent's item (no builder, and it is the -main agent itself): the fleet's builder is asked once, the owner nothing, and no front agent or page keeper is pushed",
      "a62" in done and ho(62).get("recovery_at") and "decision" not in (mt(62).get("needs") or []) and len(recovery_pushes("a62")) == 1 and len(pushes()) == n_push62 + 1
      and not pushes_to("home-beta-front", "a62") and not pushes_to("home-beta-stew"), (done, ho(62), pushes()[n_push62:]))
check("14 front recovery: …and the next pass sends nothing", stk(T2 + 21) == [] and len(pushes()) == n_push62 + 1, pushes()[n_push62:])
close(62); set_cfg()

# ================================================================ 15. the stall flag ends with the episode: the mover taking the item
item(63, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
set_cfg(cold_call=False)
stk(T1); stk(T2)
check("15 flag: (setup) the item went to the builder as a stall record", ho(63).get("to") == "team-back" and ho(63).get("stall") is True and not ho(63).get("taken_at"), ho(63))
server._update("a63", sender="team-back", next="team-back: on it now")
check("15 flag: …a note by the builder is no start: still not taken, the flag stays", not ho(63).get("taken_at") and ho(63).get("stall") is True, ho(63))
server._update("a63", sender="team-back", work={"text": "doing it", "state": "in progress"})
check("15 flag: …the builder starting work on it: taken, and the stall flag is gone from its record", ho(63).get("taken_at") and "stall" not in ho(63), ho(63))
close(63); set_cfg()

# ================================================================ 16. an item is looked at only when its work is due now
N = T1 + 3600
def wk(ep): return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(ep + ZONE_OFFSET))      # a wake with a time of day, in the instance zone
for w_ in ("home-front", "team-back", "home-peer", "home-peer2", "home-peer3"): cli_row(w_, "idle", IDLE0)
stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
WAKE16 = wk(N + 3600)
BASIS16 = {"text": "the vendor answers on that day", "wake": WAKE16, "by": "team-back", "at": N}      # a wake that stands on a real-world date: the board shows the item waiting
item(70, mover="home-front", wake=WAKE16, wait_basis=BASIS16)                          # a front agent's item parked until a dated event
item(71, mover="team-back", needs=["team-back"], wake=WAKE16, wait_basis=BASIS16)        # a background agent's
item(73, mover="home-peer", hold=True, wake=WAKE16)                                    # parked
item(74, mover="home-send")                                                            # the open item 75 is ordered after (no pane on this box: not looked at itself)
item(75, mover="home-peer2", after=["a74"])
item(76, mover="home-peer3", needs=["decision"], ask=ASK, next=f"{OWN}: decide")       # waiting on the owner, though a session is stored as mover
item(77, mover="home-peer", needs=["external"], next="a vendor: reply")                # waiting on someone outside
item(78, mover="home-peer2", wake=WAKE16, wait_basis=BASIS16)                          # a dated wait, with a leftover record from an earlier episode
stall_svc.stall_save({"a78": {"mover": "home-peer2", "ver": [B, B], "step": 2, "last": N - 100.0, "cold_at": N - 200.0}})
ids16 = (70, 71, 73, 75, 76, 77, 78)
before16 = {i: rd(i) for i in ids16}
done = stk(N) + stk(N + 1800)
gids16 = {f"a{i}" for i in ids16}
check("16 not due: a wake with a wait_basis (front mover and background mover), a parked item, an item after an open one, a needs-decision item and a needs-external item: none is stepped, written or sent anything",
      not (set(done) & gids16) and all(rd(i) == before16[i] for i in ids16) and not [p for p in pushes() if any(f"a{i}" in p[1] for i in ids16)], (done, pushes()[-3:]))
check("16 not due: ...and the pass keeps no record of them, a leftover one included", not (set(stall_svc.stall_load()) & gids16), stall_svc.stall_load())
check("16 not due: pure: not_due says why, and nothing for an item whose work is due",
      S.not_due(rd(70), N) == "the board shows it waiting (time)" and S.not_due(rd(73), N) == "the board shows it waiting (time)" and S.not_due(rd(76), N) == "waiting on the owner"
      and S.not_due(rd(77), N) == "the board shows it waiting (relay)" and S.not_due(rd(75), N, lambda it: ["a74"]) == "the board shows it waiting (item)" and S.not_due(rd(75), N, lambda it: []) == ""
      and S.not_due(rd(70), N + 7200) == "", [S.not_due(rd(i), N) for i in (70, 73, 75, 76, 77)])
# a wake alone is a backstop: the board shows the item on agent, so the pass looks at it (it used to hold the pass off, and an item sat on agent for a day)
item(79, mover="home-front", wake=WAKE16)
check("16 not due: a bare wake ahead is a backstop, not a wait: not_due says nothing, and due_at counts nothing from a wake that has not passed",
      S.not_due(rd(79), N) == "" and S.due_at(rd(79), N) == 0.0 and S.due_at(rd(79), N + 7200) > 0.0 and S.due_at(rd(79)) > 0.0, (S.not_due(rd(79), N), S.due_at(rd(79), N)))
done = stk(N + 1900)
check("16 not due: ...and the pass steps that item with the wake still ahead (a front mover: its History line)", "a79" in done and len(log_of(79)) == 1, (done, log_of(79)))
close(79)
D = N + 3600                                                                         # the wakes (to the minute) have passed
done = stk(D + 9 * MIN)
check("16 due: just past the wake the item has its minutes first: nothing at 9 minutes (the clock starts when the work is due)", not (set(done) & gids16), done)
close(74)                                                                            # the item 75 is after is closed: it is ordered after nothing
for i in (73, 76, 77):                                                               # the hold is released, the owner and the outsider have answered
    d_ = rd(i)
    for k_ in ("hold", "needs", "ask"): d_["metadata"].pop(k_, None)
    (T / f"store/a/{i}.json").write_text(json.dumps(d_))
n_push = len(pushes())
done = stk(D + 11 * MIN) + stk(D + 11 * MIN + 30)        # at most [stall] max_per_tick (5) first steps a tick: the rest on the next
check("16 due: ...and past 10 minutes the same items are stepped as before: a passed wake (front mover: History line only, background mover: the notice), an `after` closed, a hold released, the answers given",
      gids16 <= set(done) and all(len(log_of(i)) == 1 for i in ids16), (sorted(gids16 - set(done)), [len(log_of(i)) for i in ids16]))
check("16 due: ...the background mover's notice went out, the front agent's did not", len(pushes_to("team-back", "a71")) == 1 and not pushes_to("home-front"), pushes()[n_push:])
check("16 due: ...the item with the leftover record starts at the notice (step 1), not at the cold call it had reached", stall_svc.stall_load()["a78"]["step"] == 1 and "cold_at" not in stall_svc.stall_load()["a78"] and S.log_of(mt(78))[-1]["text"].endswith("sent to it again"), (stall_svc.stall_load().get("a78"), log_of(78)))
close(*ids16)
for w_ in ("home-front", "team-back", "home-peer", "home-peer2", "home-peer3"): no_row(w_)

# ================================================================ 17. a pause of the pass ends on its own (enabled = false stayed off for hours)
import datetime as _dt
ZONE_TZ = _dt.timezone(_dt.timedelta(seconds=ZONE_OFFSET))
def iso(ep): return _dt.datetime.fromtimestamp(ep, ZONE_TZ).isoformat(timespec="minutes")
def err(fn, *a):
    """fn(*a) with stderr (the journal) captured → (result, what it wrote)."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf): r = fn(*a)
    return r, buf.getvalue()
def fresh_pause():
    """A server restart for the pause: nothing in memory, the state file is what is left."""
    stall_svc.STALL_PAUSE.update(rec=None, loaded=False, said="")
PAUSE_FILE = T / "state/stall_pause.json"
H4 = 4 * 3600.0
Q = float(int(T1 // 60) * 60 + 6 * 3600)                    # a whole minute (an ISO time here has no seconds)
START = r"stall: paused until \w{3} \w{3} \d+(?:st|nd|rd|th) \d\d:\d\d " + re.escape(ZONE_ABBR) + r" \((.*)\)"
cli_row("home-peer", "idle", IDLE0)
stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
stall_svc.stall_pause_log_project = lambda: "projects/alpha"           # the fleet operator's page (the test fleet has no operator_session)

# 17a. paused_until ahead: no step until then, one start line, one end line, the pass runs again with no edit
item(80)
set_stall(paused_until=iso(Q + 7200))
r, e = err(stk, Q)
m = re.findall(START, e)
check("17 paused_until ahead: the pass takes no step, and the journal says until when and why (one line, with the zone's abbreviation)", r == [] and not log_of(80) and not pushes_to("home-peer", "a80") and m == ["paused_until"], (r, e))
check("17 paused_until ahead: the pause's start is kept in <state>/stall_pause.json", json.loads(PAUSE_FILE.read_text())["since"] == Q, PAUSE_FILE.read_text() if PAUSE_FILE.exists() else None)
r, e = err(stk, Q + 3600)
check("17 paused_until ahead: still paused an hour in, and no second start line", r == [] and not log_of(80) and e == "", (r, e))
n_rt = len(server._routing.read("projects/alpha"))
r, e = err(stk, Q + 7200 + 1)
check("17 paused_until passed: the pass runs again with no config edit (the item is stepped), one `pause ended` line", "a80" in r and len(log_of(80)) == 1 and e.count("stall: pause ended, the pass runs again") == 1, (r, e))
rt = [n for n in server._routing.read("projects/alpha") if n.get("label") == "stall pause ended"]
check("17 paused_until passed: ...and one routing-log line, ruled dropped by stackshot (auto), not delivered to anyone", len(rt) == 1 and rt[0].get("ruling") == "dropped" and rt[0].get("text") == "stall: pause ended, the pass runs again" and len(server._routing.read("projects/alpha")) == n_rt + 1, rt)
check("17 paused_until passed: ...and the state file is gone", not PAUSE_FILE.exists())
r, e = err(stk, Q + 7200 + 2 * MIN)
check("17 paused_until passed: no further pause line while the setting stays in the file", e == "", e)
close(80)

# 17b. paused_until already past: the pass runs and nothing is logged
fresh_pause(); stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
item(81)
set_stall(paused_until=iso(Q - 3600))
r, e = err(stk, Q)
check("17 paused_until in the past: the pass runs, no pause line, no state file", "a81" in r and "paused" not in e and not PAUSE_FILE.exists(), (r, e))
close(81)

# 17c. enabled = false is held at most [stall] max_pause_hours (4) from when the server first saw it
Q2 = Q + 86400
fresh_pause(); stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
item(82)
set_stall(enabled=False)
r, e = err(stk, Q2)
check("17 enabled = false: no step, and the journal says it is capped at 4 h", r == [] and re.findall(START, e) == ["enabled=false, capped at 4 h"], (r, e))
r, e = err(stk, Q2 + H4 - 60)
check("17 enabled = false: still no step a minute before the cap, no new line", r == [] and not log_of(82) and e == "", (r, e))
r, e = err(stk, Q2 + H4 + 1)
check("17 enabled = false: past the cap the pass runs again (stepped) with enabled still false, one `pause ended` line", "a82" in r and e.count("stall: pause ended, the pass runs again") == 1, (r, e))
r, e = err(stall_svc.stall_pause_check, Q2 + 5 * 3600)
check("17 enabled = false: ...and the same setting does not start another pause or repeat the line", r is None and e == "" and stall_svc.stall_on(Q2 + 5 * 3600), (r, e))
set_stall()
r, e = err(stall_svc.stall_pause_check, Q2 + 6 * 3600)
check("17 enabled = false: ...turning it back on after the cap logs nothing and clears the record", r is None and e == "" and not PAUSE_FILE.exists(), (r, e, stall_svc.STALL_PAUSE))
set_stall(enabled=False)
r, e = err(stall_svc.stall_pause_check, Q2 + 7 * 3600)
check("17 enabled = false: ...setting it false again is a new pause: a start line, a new cap", r == Q2 + 7 * 3600 + H4 and re.findall(START, e) == ["enabled=false, capped at 4 h"], (r, e))
# a restart does not reset the clock: the start time is the state file's
fresh_pause()
r, e = err(stall_svc.stall_pause_check, Q2 + 10 * 3600)
check("17 a restart keeps the pause's start: the same end time, no new start line", r == Q2 + 7 * 3600 + H4 and e == "", (r, e))
check("17 a restart keeps the pause's start: the file holds the first sighting", json.loads(PAUSE_FILE.read_text())["since"] == Q2 + 7 * 3600, PAUSE_FILE.read_text())
fresh_pause()
r, e = err(stall_svc.stall_pause_check, Q2 + 7 * 3600 + H4 + 1)
check("17 a restart after the cap: the pass runs, the end is logged once", r is None and e.count("stall: pause ended, the pass runs again") == 1, (r, e))
close(82)

# 17d. a paused_until further out than the cap is cut to the cap; [stall] max_pause_hours changes the cap
Q3 = Q2 + 86400
set_stall(paused_until=iso(Q3 + 10 * 3600)); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q3)
check("17 paused_until beyond the cap: the pause ends at the cap, and the line says so", r == Q3 + H4 and re.findall(START, e) == ["paused_until, capped at 4 h"], (r, e))
r, e = err(stall_svc.stall_pause_check, Q3 + H4 + 1)
check("17 paused_until beyond the cap: ...and past it the pass runs again though the file still names a later time", r is None and e.count("pause ended") == 1, (r, e))
Q4 = Q3 + 86400
set_stall(paused_until=iso(Q4 + 10 * 3600), max_pause_hours=1); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q4)
check("17 [stall] max_pause_hours = 1: the cap is one hour", r == Q4 + 3600 and re.findall(START, e) == ["paused_until, capped at 1 h"], (r, e))
Q5 = Q4 + 86400
set_stall(enabled=False, paused_until=iso(Q5 + 3600)); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q5)
check("17 enabled = false with a nearer paused_until: the earlier end holds", r == Q5 + 3600 and re.findall(START, e) == ["paused_until"], (r, e))
Q6 = Q5 + 86400
set_stall(enabled=False, paused_until=iso(Q6 + 10 * 3600)); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q6)
check("17 enabled = false with a paused_until beyond the cap: cut to the cap", r == Q6 + 4 * 3600 and re.findall(START, e) == ["paused_until, capped at 4 h"], (r, e))
set_stall(max_pause_hours="x", enabled=False); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q6)
check("17 [stall] max_pause_hours that is not a number: the default (4 h)", r == Q6 + H4, (r, e))
set_stall(paused_until="tomorrow"); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
r, e = err(stall_svc.stall_pause_check, Q6)
check("17 a paused_until that is not a time is ignored (the pass runs), and the notes name it", r is None and e == "" and any("paused_until" in n and "ignored" in n for n in server._cfg.stall_notes()), (r, e, server._cfg.stall_notes()))

# 17e. doctor and the start (config.notes) and the reload name a pause and when it ends
set_stall(); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
check("17 notes: nothing paused: no stall note", server._cfg.notes() == [] and server._cfg.stall_notes() == [], server._cfg.notes())
set_stall(paused_until=iso(now0 + 3600))
n1 = server._cfg.stall_notes()
check("17 notes: a pause the server has not read yet: named with its end, counted from now", len(n1) == 1 and "takes no step until" in n1[0] and "counted from now" in n1[0] and "runs again on its own" in n1[0] and ZONE_ABBR in n1[0], n1)
err(stall_svc.stall_pause_check)
n2 = server._cfg.stall_notes()
check("17 notes: ...once the server has read it: its end, no 'counted from now'", len(n2) == 1 and "takes no step until" in n2[0] and "counted from now" not in n2[0] and "(paused_until)" in n2[0], n2)
check("17 notes: ...config.notes (doctor, the start) carries it too", any("takes no step until" in n for n in server._cfg.notes()), server._cfg.notes())
set_stall(enabled=False); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)
n3 = server._cfg.stall_notes()
check("17 notes: enabled = false: named with 'enabled=false, capped at 4 h'", len(n3) == 1 and "enabled=false, capped at 4 h" in n3[0], n3)
set_stall(); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)

# the reload: a config file with a pause is read live, the start line is logged and a warning names the end
i_ = toml.index("\nenabled = true", toml.index("\n[stall]")); toml_pause = toml[:i_] + f'\npause_item = "a97"\npaused_until = "{iso(now0 + 7200)}"' + toml[i_:]
(T / "stackshot.toml").write_text(toml_pause, encoding="utf-8")
_, e = err(server._on_hup)
check("17 reload: a pause in the file is logged (start line) and warned about, with its end", len(re.findall(START, e)) == 1 and "config reload: [stall] the stall pass is paused (paused_until) and takes no step until" in e, e)
check("17 reload: ...the warning is printed once, not twice (config.reload's own; the server adds none)", e.count("takes no step until") == 1 and "warning:" not in e, e)
_, e = err(server._on_hup)
check("17 reload: a second reload with the pause unchanged warns once again, with no new start line", e.count("takes no step until") == 1 and len(re.findall(START, e)) == 0 and "warning:" not in e
      and "counted from now" not in e, e)             # ... and says "counted from now" no more: config.reload's line reads the server's record of the pause too
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
_, e = err(server._on_hup)
check("17 reload: no pause in the file: no stall warning", "takes no step until" not in e and "warning:" not in e, e)
set_stall(); set_cfg(); fresh_pause(); PAUSE_FILE.unlink(missing_ok=True)

# the pure half
check("17 pure: parse_until reads an ISO time with an offset, an offset-less one in the zone given, and nothing for an unset or unreadable one",
      S.parse_until("2026-10-30T21:00+04:00") == S.parse_until("2026-10-30T17:00:00+00:00") == S.parse_until("2026-10-30T21:00", ZONE_TZ) and S.parse_until("") is None and S.parse_until(None) is None
      and S.parse_until("tomorrow") is None and S.parse_until("2026-10-30T21:00") is None, S.parse_until("2026-10-30T21:00+04:00"))
check("17 pure: pause_hours is a positive number, else the default 4", S.pause_hours(2) == 2.0 and S.pause_hours("0.5") == 0.5 and S.pause_hours(0) == 4.0 and S.pause_hours(-1) == 4.0 and S.pause_hours("x") == 4.0 and S.pause_hours(None) == 4.0)
check("17 pure: pause with nothing to pause for gives no record and no event", S.pause(True, "", ZONE_TZ, 4, None, 1000.0) == (None, None, "", []) and S.pause(True, "2000-01-01T00:00+04:00", ZONE_TZ, 4, None, 2e9)[1] is None)
rec_, end_, why_, ev_ = S.pause(False, "", ZONE_TZ, 4, None, 1000.0)
check("17 pure: a first sighting of enabled = false starts at now and ends 4 h later", end_ == 1000.0 + H4 and why_ == "enabled=false, capped at 4 h" and ev_ == ["start"] and rec_["since"] == 1000.0, (rec_, end_, why_, ev_))
rec2, end2, why2, ev2 = S.pause(False, "", ZONE_TZ, 4, rec_, 1000.0 + H4)
check("17 pure: at the cap it ends (record kept, ended), and a later look logs nothing more", end2 is None and ev2 == ["end"] and rec2.get("ended") and S.pause(False, "", ZONE_TZ, 4, rec2, 1000.0 + 2 * H4)[3] == [], (rec2, ev2))
check("17 pure: the setting no longer asking for a pause clears the record, with an end event only if the pause had not ended", S.pause(True, "", ZONE_TZ, 4, rec_, 2000.0)[::3] == (None, ["end"]) and S.pause(True, "", ZONE_TZ, 4, rec2, 2000.0)[::3] == (None, []), S.pause(True, "", ZONE_TZ, 4, rec_, 2000.0))

# ================================================================ 18. an agent never switches the pass off
# A pause is honored only when [stall] pause_item names a board item with Oliver's own answer (metadata.answers) dated no earlier than 4 hours before the server first saw the setting.
REFUSED = r"stall: pause refused, the pass keeps running: (.*)"
H24 = 24 * 3600.0
def reset18():
    fresh_pause(); PAUSE_FILE.unlink(missing_ok=True); stall_svc.stall_save({}); stall_svc.stall_write({"_pass": {"since": B}})
def oliver(i, *stamps, **extra):
    """An item that carries Oliver's answers dated `stamps` (a closed item: the pass leaves it alone)."""
    item(i, status="completed", answers=[{"ts": t, "kind": "comment", "text": "Pause it.", "via": "board"} for t in stamps], **extra)
def raw_stall(**kw): server._cfg.CFG["stall"] = dict(kw)       # the section as a file would give it: no pause_item added
cli_row("home-peer", "idle", IDLE0)

# 18a. no pause_item: refused; the pass runs; ONE line, once per load (not per tick); doctor shows it; a reload or start logs it once more; no "pause ended" when the setting goes
Q7 = Q6 + 86400
reset18(); item(96)
raw_stall(enabled=False)
r, e = err(stk, Q7)
m = re.findall(REFUSED, e)
check("18 no pause_item: the pass keeps running (the item is stepped) and the journal has ONE line saying why", "a96" in r and len(log_of(96)) == 1 and len(m) == 1 and "pause_item names no board item" in m[0] and e.count("pause refused") == 1, (r, e))
check("18 no pause_item: ...no pause starts (no `paused until` line)", not re.findall(START, e), e)
r, e = err(stk, Q7 + 30)
check("18 no pause_item: ...the next tick logs nothing more (once per config load, not per tick)", e == "", e)
r, e = err(stall_svc.stall_pause_check, Q7 + 60)
check("18 no pause_item: ...many checks, still nothing more, and the pass is on", e == "" and r is None and stall_svc.stall_on(Q7 + 60), (r, e))
stall_svc.stall_pause_reload()
r, e = err(stall_svc.stall_pause_check, Q7 + 90)
check("18 no pause_item: a reload or a start (a new config load) logs the refusal once more", len(re.findall(REFUSED, e)) == 1 and e.count("\n") == 1, e)
nn = server._cfg.stall_notes()
check("18 no pause_item: doctor and the start show it: refused, the pass keeps running, why", len(nn) == 1 and "pause_item names no board item" in nn[0] and "refused" in nn[0] and "keeps running" in nn[0] and "takes no step until" not in nn[0], nn)
check("18 no pause_item: ...config.notes (doctor, the start) carries it", any("refused" in n for n in server._cfg.notes()), server._cfg.notes())
check("18 no pause_item: the record keeps when the server first saw the setting, marked refused", json.loads(PAUSE_FILE.read_text()).get("refused") is True and json.loads(PAUSE_FILE.read_text())["since"] == Q7, PAUSE_FILE.read_text() if PAUSE_FILE.exists() else None)
set_stall()
r, e = err(stall_svc.stall_pause_check, Q7 + 120)
check("18 no pause_item: the setting going away logs nothing (no `pause ended`: nothing had paused) and clears the record", r is None and e == "" and not PAUSE_FILE.exists() and server._cfg.stall_notes() == [], (r, e))
close(96)

# 18b. pause_item names no item; an item without an answer of his (a note a session wrote is not one); an answer that is too old; the edge of the window
Q8 = Q7 + 86400
reset18(); item(19)
raw_stall(enabled=False, pause_item="a98")
r, e = err(stk, Q8)
m = re.findall(REFUSED, e)
check("18 a pause_item that is no item: refused, the pass runs, one line says so", "a19" in r and len(m) == 1 and "pause_item a98 is not a board item" in m[0], (r, e))
close(19)
reset18(); item(31)
item(92, status="completed", said=[{"ts": Q8, "text": "Oliver said to pause it."}], history=[{"at": Q8, "text": "paused by the engineer"}])
raw_stall(enabled=False, pause_item="a92")
r, e = err(stk, Q8)
m = re.findall(REFUSED, e)
check("18 an item with no answer of Oliver's (only what a session wrote on it): refused, the pass runs", "a31" in r and len(m) == 1 and "carries no answer of Oliver's" in m[0], (r, e))
close(31)
reset18(); item(32)
oliver(93, Q8 - H4 - 60)
raw_stall(enabled=False, pause_item="a93")
r, e = err(stk, Q8)
check("18 his answer is older than 4 hours before the setting was first seen: refused, the pass runs", "a32" in r and len(re.findall(REFUSED, e)) == 1 and not re.findall(START, e), (r, e))
close(32)
reset18(); item(104)
oliver(94, Q8 - H4 + 60)
raw_stall(enabled=False, pause_item="a94")
r, e = err(stk, Q8)
check("18 his answer 4 hours less a minute before it was first seen: honored (the pass takes no step), the start line as before", r == [] and not log_of(104) and re.findall(START, e) == ["enabled=false, capped at 4 h"] and not re.findall(REFUSED, e), (r, e))
close(104)

# 18c. his answer given after the setting was first seen honors it, counted from when the setting was first seen
Q9 = Q8 + 86400
reset18(); item(33)
oliver(95)
raw_stall(enabled=False, pause_item="a95")
r, e = err(stk, Q9)
check("18 an item with no answer yet: refused, the pass runs", "a33" in r and len(re.findall(REFUSED, e)) == 1, (r, e))
oliver(95, Q9 + 600)
r, e = err(stk, Q9 + 700)
check("18 ...he answers: the next tick honors the pause (no step, the start line)", r == [] and re.findall(START, e) == ["enabled=false, capped at 4 h"] and not re.findall(REFUSED, e), (r, e))
r, e = err(stall_svc.stall_pause_check, Q9 + 800)
check("18 ...its end is 4 hours from when the setting was first seen, not from his answer", r == Q9 + H4 and e == "", (r, e))
r, e = err(stall_svc.stall_pause_check, Q9 + H4 + 1)
check("18 ...and it ends on its own at that time (one `pause ended` line)", r is None and e.count("stall: pause ended, the pass runs again") == 1, (r, e))
close(33)

# 18c2. his answer must approve a pause: an unrelated answer of his on the item does not count (round 2 of the review); an option or a comment that says "pause" does, in any case
def answered(i, *recs): item(i, status="completed", answers=[{"ts": t, "via": "board", **r} for t, r in recs])
Q9b = Q9 + 3 * 86400
reset18(); item(35)
answered(37, (Q9b - 60, {"kind": "comment", "text": "Looks good, ship it."}), (Q9b - 30, {"kind": "decision", "choice": "Go ahead", "choice_line": "release it"}))
raw_stall(enabled=False, pause_item="a37")
r, e = err(stk, Q9b)
m = re.findall(REFUSED, e)
check("18 an unrelated answer of his in the window (a comment and a pick that do not say pause): refused, the pass runs, the line says a pause must be approved", "a35" in r and len(m) == 1 and "approving a pause" in m[0] and not re.findall(START, e), (r, e))
close(35)
reset18(); item(911)
answered(38, (Q9b - 60, {"kind": "comment", "text": "Please PAUSE the nudge until the fix is in."}))
raw_stall(enabled=False, pause_item="a38")
r, e = err(stk, Q9b)
check("18 a comment that mentions pause (any case): honored, the pass takes no step", r == [] and not log_of(911) and re.findall(START, e) == ["enabled=false, capped at 4 h"] and not re.findall(REFUSED, e), (r, e))
close(911)
reset18(); item(912)
answered(39, (Q9b - 60, {"kind": "decision", "choice": "Pause for 2 hours"}))
raw_stall(enabled=False, pause_item="a39")
r, e = err(stk, Q9b)
check("18 a picked option whose label says pause: honored", r == [] and not log_of(912) and re.findall(START, e) == ["enabled=false, capped at 4 h"], (r, e))
close(912)
reset18(); item(913)
answered(47, (Q9b - 60, {"kind": "decision", "choice": "Go ahead", "choice_line": "pause the stall pass"}))
raw_stall(enabled=False, pause_item="a47")
r, e = err(stk, Q9b)
check("18 a pick whose line (not its label) says pause: honored", r == [] and not log_of(913) and re.findall(START, e) == ["enabled=false, capped at 4 h"], (r, e))
close(913)
check("18 pure: authorize needs the word pause in the choice, its line or the text, and nothing else counts",
      S.authorize("a1", [{"ts": 1e6, "text": "ok"}], 1e6) != "" and "approving a pause" in S.authorize("a1", [{"ts": 1e6, "text": "ok"}], 1e6)
      and S.authorize("a1", [{"ts": 1e6, "text": "Pause it"}], 1e6) == "" and S.authorize("a1", [{"ts": 1e6, "choice": "PAUSE"}], 1e6) == ""
      and S.authorize("a1", [{"ts": 1e6, "choice_line": "pause"}], 1e6) == "" and S.authorize("a1", [{"ts": 1e6, "kind": "pause", "via": "pause"}], 1e6) != "",
      S.authorize("a1", [{"ts": 1e6, "text": "ok"}], 1e6))

# 18c3. refused, then answered after the pause's whole cap: the clock restarts when the answer is honored (still at most 24 h) and one line says it started late
Q9c = Q9 + 4 * 86400
reset18(); item(36)
answered(49)
raw_stall(enabled=False, pause_item="a49")
r, e = err(stk, Q9c)
check("18 late: no answer yet, refused (the first sighting is kept)", "a36" in r and len(re.findall(REFUSED, e)) == 1 and json.loads(PAUSE_FILE.read_text())["since"] == Q9c, (r, e))
answered(49, (Q9c + H4 + 3600, {"kind": "comment", "text": "Pause it, please."}))
r, e = err(stk, Q9c + H4 + 3700)
late = [l for l in e.splitlines() if "started late" in l]
check("18 late: his answer comes after the cap has passed: the pause starts then (no step), with ONE line saying it started late", r == [] and len(late) == 1 and e.count("stall: paused until") == 1 and not re.findall(REFUSED, e), (r, e))
rec_ = json.loads(PAUSE_FILE.read_text())
check("18 late: the record's clock restarted at the moment it was honored, no longer marked refused", rec_.get("since") == Q9c + H4 + 3700 and "refused" not in rec_ and not rec_.get("ended"), rec_)
r, e = err(stall_svc.stall_pause_check, Q9c + H4 + 3800)
check("18 late: it ends 4 hours after it was honored, and logs nothing more meanwhile", r == Q9c + H4 + 3700 + H4 and e == "", (r, e))
r, e = err(stall_svc.stall_pause_check, Q9c + 2 * H4 + 3701)
check("18 late: and it ends on its own then (one `pause ended` line)", r is None and e.count("stall: pause ended, the pass runs again") == 1, (r, e))
close(36)
reset18(); item(915)
answered(53)
raw_stall(enabled=False, pause_item="a53", max_pause_hours=96)
r, e = err(stk, Q9c)
answered(53, (Q9c + 3 * 86400, {"kind": "comment", "text": "pause"}))
r, e = err(stall_svc.stall_pause_check, Q9c + 3 * 86400 + 60)
check("18 late: still capped at 24 hours from when it was honored (max_pause_hours = 96)", r == Q9c + 3 * 86400 + 60 + H24 and e.count("started late") == 1, (r, e))
close(915)
rLa, eLa, wLa, vLa = S.pause(False, "", ZONE_TZ, 4, {"sig": "0|", "since": 1000.0, "refused": True}, 1000.0 + 5 * 3600, lambda since: "")
check("18 pure: late (refused, now past since + cap, then authorized): clock restarts at now, event `late` and not `start`, end = now + cap",
      vLa == ["late"] and rLa["since"] == 1000.0 + 5 * 3600 and "refused" not in rLa and eLa == 1000.0 + 5 * 3600 + 4 * 3600, (rLa, eLa, vLa))
rLb, eLb, wLb, vLb = S.pause(False, "", ZONE_TZ, 4, {"sig": "0|", "since": 1000.0, "refused": True}, 1000.0 + 3600, lambda since: "")
check("18 pure: ...inside the cap it keeps its first sighting and starts normally",
      vLb == ["start"] and rLb["since"] == 1000.0 and eLb == 1000.0 + 4 * 3600, (rLb, eLb, vLb))

# 18d. the pause_item can be written as board#N or as a stored id
g7 = server._gh.norm("board#7"); (T / f"store/{g7[0]}").mkdir(exist_ok=True)
(T / f"store/{g7[0]}/{g7[1:]}.json").write_text(json.dumps({"id": g7[1:], "subject": "[home] item", "description": DESC, "status": "completed", "updated": B, "state_updated": B, "confirmed": B,
                                                           "metadata": {"project": "projects/alpha", "answers": [{"ts": 9e9, "kind": "decision", "choice": "Pause", "via": "board"}]}}))
Q10 = Q9 + 86400
reset18(); raw_stall(enabled=False, pause_item="board#7")
r, e = err(stall_svc.stall_pause_check, Q10)
check("18 pause_item = board#7: found in the issue-numbered store and honored", r == Q10 + H4 and len(re.findall(START, e)) == 1, (r, e))
reset18(); raw_stall(enabled=False, pause_item="#7")
r, e = err(stall_svc.stall_pause_check, Q10)
check("18 pause_item = #7: the same", r == Q10 + H4, (r, e))

# 18e. no pause is longer than 24 hours
Q11 = Q10 + 86400
reset18(); raw_stall(enabled=False, pause_item="a97", max_pause_hours=48)
r, e = err(stall_svc.stall_pause_check, Q11)
check("18 max_pause_hours = 48: the pause is cut to 24 hours", r == Q11 + H24 and re.findall(START, e) == ["enabled=false, capped at 24 h"], (r, e))
reset18(); raw_stall(paused_until=iso(Q11 + 3 * 86400), pause_item="a97", max_pause_hours=96)
r, e = err(stall_svc.stall_pause_check, Q11)
check("18 a paused_until three days out (max_pause_hours = 96): cut to 24 hours from when it was first seen", r == Q11 + H24 and re.findall(START, e) == ["paused_until, capped at 24 h"], (r, e))
r, e = err(stall_svc.stall_pause_check, Q11 + H24 + 1)
check("18 ...and it ends there, the pass runs again", r is None and e.count("pause ended") == 1, (r, e))
reset18(); raw_stall(paused_until=iso(Q11 + 20 * 3600), pause_item="a97", max_pause_hours=96)
r, e = err(stall_svc.stall_pause_check, Q11)
check("18 a paused_until inside the 24 hours keeps its own time", r == Q11 + 20 * 3600 and re.findall(START, e) == ["paused_until"], (r, e))

# 18f. a reload of a config file with the switch-off and no pause_item
toml_off = toml[:i_] + "\nenabled = false" + toml[i_ + len("\nenabled = true"):]
(T / "stackshot.toml").write_text(toml_off, encoding="utf-8")
reset18(); item(34)
_, e = err(server._on_hup)
check("18 reload: a file with enabled = false and no pause_item logs the refusal once, and the reload note says the pass keeps running", len(re.findall(REFUSED, e)) == 1 and e.count("keeps running") == 2 and "refused" in e, e)
r, e = err(stk, Q11 + 5 * 86400)
check("18 reload: ...the pass runs (the item is stepped) and logs nothing more", "a34" in r and "refused" not in e, (r, e))
_, e = err(server._on_hup)
check("18 reload: ...a second reload (a new config load) logs the refusal once more", len(re.findall(REFUSED, e)) == 1, e)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
_, e = err(server._on_hup)
check("18 reload: the switch-off removed: no refusal line, no note", "refused" not in e and "keeps running" not in e, e)
close(34)
set_stall(); set_cfg(); reset18()

# 18g. the example config documents the key
check("18 config: the example config documents pause_item and the 24 h ceiling in the [stall] block", re.search(r'(?m)^# pause_item = ', re.search(r'(?ms)^\[stall\][^\n]*\n(.*?)^\[', toml).group(1)) and "above 24 is read as 24" in toml)

# the pure half
check("18 pure: authorize: no item, no such item, no answer, an old answer, the edge, a later answer, entries that are not answers",
      "names no board item" in S.authorize("", [], 1e6) and "names no board item" in S.authorize("  ", [], 1e6) and "not a board item" in S.authorize("a1", None, 1e6)
      and "no answer of Oliver's" in S.authorize("a1", [], 1e6) and "no answer of Oliver's" in S.authorize("a1", [{"ts": 1e6 - H4 - 1, "text": "pause"}], 1e6)
      and S.authorize("a1", [{"ts": 1e6 - H4, "text": "pause"}], 1e6) == "" and S.authorize("a1", [{"ts": 1e6 - 96 * H4, "text": "pause"}, {"ts": 1e6 + 60, "text": "pause"}], 1e6) == ""
      and "no answer" in S.authorize("a1", [None, "x", {"text": "no ts, but pause"}], 1e6), S.authorize("a1", [None, "x", {"text": "no ts, but pause"}], 1e6))
check("18 pure: pause_hours never exceeds 24", S.pause_hours(48) == 24.0 and S.pause_hours(24) == 24.0 and S.pause_hours(23.5) == 23.5 and S.PAUSE_MAX_HOURS == 24.0 and S.ANSWER_HOURS == 4.0)
rA, eA, wA, vA = S.pause(False, "", ZONE_TZ, 4, None, 1000.0, lambda since: "no")
check("18 pure: a refused pause pauses nothing: no end, the reason, a `refuse` event, a record that keeps the first sighting and says refused", eA is None and wA == "no" and vA == ["refuse"] and rA["since"] == 1000.0 and rA["refused"] is True, (rA, eA, wA, vA))
rB, eB, wB, vB = S.pause(False, "", ZONE_TZ, 4, rA, 5000.0, lambda since: "no")
check("18 pure: ...refused again later: the same record, `refuse` again (the caller logs once per load)", rB == rA and eB is None and vB == ["refuse"], (rB, vB))
rC, eC, wC, vC = S.pause(False, "", ZONE_TZ, 4, rA, 5000.0, lambda since: "" if since == 1000.0 else "wrong since")
check("18 pure: ...then his answer: it starts, counted from the first sighting, the refused mark gone", eC == 1000.0 + H4 and vC == ["start"] and "refused" not in rC and rC["since"] == 1000.0, (rC, eC, vC))
check("18 pure: a refused pause whose setting goes away ends without an `end` event; a pause with no rule (auth None) is honored as before",
      S.pause(True, "", ZONE_TZ, 4, rA, 6000.0)[::3] == (None, []) and S.pause(False, "", ZONE_TZ, 4, None, 1000.0)[1] == 1000.0 + H4)

# ================================================================ 19. the cold call names the session that already moves the item
# An idle mover that waits on something is the right one: the call says so, and the ladder neither goes on to the builder nor asks the fleet's builder to recover it.
cold({"action": "hand_to", "to": "home-peer2", "reason": "it waits on a release that is theirs to watch"}); n_cold = len(COLD_MSGS)
journal = two_steps(64)
check("19 kept: the cold call that names the mover leaves the item with it: same mover, no decision, no ask, no recovery asked, not written as the cold call",
      len(COLD_MSGS) == n_cold + 1 and mt(64).get("mover") == "home-peer2" and "decision" not in (mt(64).get("needs") or []) and not mt(64).get("ask") and rd(64).get("written_by") != "cold-call"
      and not ho(64).get("recovery_at") and not recovery_pushes("a64") and (ho(64).get("cold") or {}).get("state") == "done", (mt(64), ho(64)))
check("19 kept: …the History line says the call named its mover and the item was left with it", any("named its mover" in e["text"] and "left with it" in e["text"] for e in log_of(64)), log_of(64))
check("19 kept: …the episode is marked kept, and it is spent (the pass leaves the item alone)", (stall_svc.stall_load().get("a64") or {}).get("kept") and S.spent(stall_svc.stall_load()["a64"], T2 + 1), stall_svc.stall_load().get("a64"))
told = [p for p in pushes_to("home-peer2", "a64") if "fresh session read it" in p[1]]
check("19 kept: …the mover is told once, with how to store a wait the server watches", len(told) == 1 and "wait_kind=" in told[0][1], pushes_to("home-peer2", "a64"))
n_push = len(pushes_to("home-peer2", "a64"))
later = stk(T2 + 11 * MIN + 2) + stk(T2 + 3 * 3600)
check("19 kept: …later passes do nothing: no builder, no recovery request, no second call, no second notice", "a64" not in later and mt(64).get("mover") == "home-peer2" and not ho(64).get("recovery_at") and not recovery_pushes("a64") and len(COLD_MSGS) == n_cold + 1
      and len(pushes_to("home-peer2", "a64")) == n_push and "decision" not in (mt(64).get("needs") or []), (later, mt(64), ho(64)))
check("19 kept: pure: names_mover is a hand_to to the mover (any case), not another session, not a close", CC.names_mover({"action": "hand_to", "to": "Home-Peer2"}, "home-peer2") and not CC.names_mover({"action": "hand_to", "to": "team-back"}, "home-peer2")
      and not CC.names_mover({"action": "close", "to": "home-peer2"}, "home-peer2") and not CC.names_mover({"action": "hand_to", "to": ""}, "") and "handed_to" in CC.STALL_RUBRIC, None)
close(64)
cold("no json at all here")

# ================================================================ 20. a confirm ends the episode
item(65); cli_row("home-peer", "idle", IDLE0)
stk(T1)
check("20 confirm: (setup) the notice went at T1, the episode is on step 1", stall_svc.stall_load()["a65"]["step"] == 1, stall_svc.stall_load().get("a65"))
d = rd(65); d["confirmed"] = T2 - 30.0; d["written_by"] = "home-peer"; (T / "store/a/65.json").write_text(json.dumps(d))     # its mover confirms it just before the cold call is due; nobody else writes it
n_cold = len(COLD_MSGS)
done = stk(T2)
check("20 confirm: the mover's confirm ends the episode: no cold call at T2, the count starts over from the confirm (step 0 again)", "a65" not in done and len(COLD_MSGS) == n_cold and stall_svc.stall_load()["a65"]["step"] == 0
      and stall_svc.stall_load()["a65"].get("conf") == T2 - 30.0, (done, stall_svc.stall_load().get("a65")))
done = stk(T2 - 30.0 + 10 * MIN + 1)
check("20 confirm: …and the first step comes ten minutes after the confirm", "a65" in done and stall_svc.stall_load()["a65"]["step"] == 1, (done, stall_svc.stall_load().get("a65")))
old = S.episode({"mover": "home-peer", "ver": [1.0, 1.0], "step": 1, "last": 5.0}, "home-peer", [1.0, 1.0], lambda a, b: a == b, 77.0)
check("20 confirm: pure: an entry written before the confirm was recorded adopts the item's confirm and keeps its step; a later confirm starts over",
      old["step"] == 1 and old["conf"] == 77.0 and S.episode(old, "home-peer", [1.0, 1.0], lambda a, b: a == b, 77.0) is old and S.episode(old, "home-peer", [1.0, 1.0], lambda a, b: a == b, 99.0)["step"] == 0, old)
close(65)

# ================================================================ 21. only the mover's own confirm restarts the episode, and only a few times
item(66); cli_row("home-peer", "idle", IDLE0)
stk(T1)
d = rd(66); d["confirmed"] = T2 - 30.0; d["written_by"] = "home-other"; (T / "store/a/66.json").write_text(json.dumps(d))     # another session confirms it: that says nothing about the mover
n_cold = len(COLD_MSGS)
done = stk(T2)
check("21 confirm: another session's confirm does not restart the episode: the cold call comes at T2 as it would have", len(COLD_MSGS) == n_cold + 1 and not stall_svc.stall_load().get("a66", {}).get("restarts"), (done, stall_svc.stall_load().get("a66")))
same = lambda a, b: a == b
rec = {"mover": "home-peer", "ver": [1.0, 1.0], "conf": 10.0, "step": 1, "last": 5.0}
r1 = S.episode(rec, "home-peer", [1.0, 1.0], same, 20.0)
r2 = S.episode(r1, "home-peer", [1.0, 1.0], same, 30.0)
r3 = S.episode(r2, "home-peer", [1.0, 1.0], same, 40.0)
r4 = S.episode(r3, "home-peer", [1.0, 1.0], same, 50.0)
check("21 confirm: pure: the mover's first three confirms start the episode over (step 0, restarts counted); the fourth is adopted without a restart and the ladder carries on",
      (r1["step"], r2["step"], r3["step"]) == (0, 0, 0) and (r1["restarts"], r2["restarts"], r3["restarts"]) == (1, 2, 3) and r4 is r3 and r4["conf"] == 50.0 and r4.get("capped") and S.RESTARTS == 3, (r1, r2, r3, r4))
r5 = S.episode(r4, "home-peer", [2.0, 2.0], same, 50.0)
check("21 confirm: pure: a write to the item (a new version) starts the count over; an older confirm moves nothing", not r5.get("restarts") and not r5.get("capped") and S.episode(rec, "home-peer", [1.0, 1.0], same, 5.0) is rec, r5)
close(66)

# the mover's confirm, then another session's: the mover's credit stays (the entry keeps it)
item(68); cli_row("home-peer", "idle", IDLE0)
stk(T1)
d = rd(68); d["confirmed"] = T2 - 300.0; d["written_by"] = "home-peer"; (T / "store/a/68.json").write_text(json.dumps(d))
stk(T2 - 290.0)
d = rd(68); d["confirmed"] = T2 - 30.0; d["written_by"] = "home-other"; (T / "store/a/68.json").write_text(json.dumps(d))
done = stk(T2)
check("21 confirm: the mover confirmed, then another session did: the entry keeps the mover's confirm and the minutes still count from it (nothing due at T2)",
      "a68" not in done and stall_svc.stall_load()["a68"].get("conf") == T2 - 300.0 and stall_svc.stall_load()["a68"]["step"] == 0, (done, stall_svc.stall_load().get("a68")))
done = stk(T2 - 300.0 + 10 * MIN + 1)
check("21 confirm: …and the first step comes ten minutes after the mover's confirm", "a68" in done, (done, stall_svc.stall_load().get("a68")))
check("21 confirm: pure: a confirm of 0 (not the mover's) or an older one leaves the mover's `conf` as it was", S.episode(rec, "home-peer", [1.0, 1.0], same, 0.0) is rec and rec["conf"] == 10.0, rec)
close(68)

# the tick does not overwrite a `kept` mark that the cold call wrote while the pass ran
item(67); cli_row("home-peer", "idle", IDLE0)
stk(T1)
orig_cold = stall_svc.stall_cold
def cold_keeps_meanwhile(gid, who, now, minutes):
    with stall_svc.STALL_LOCK:
        st = stall_svc.stall_load(); rec = dict(st[gid]); rec["kept"] = now; rec["marker"] = "written during the tick"; st[gid] = rec; stall_svc.stall_save(st)
    return "cold"
stall_svc.stall_cold = cold_keeps_meanwhile
try:
    stk(T2)
finally:
    stall_svc.stall_cold = orig_cold
check("21 kept: a `kept` mark written while the pass ran survives the pass's own save", (stall_svc.stall_load().get("a67") or {}).get("marker") == "written during the tick" and (stall_svc.stall_load().get("a67") or {}).get("kept"), stall_svc.stall_load().get("a67"))
close(67)

# ================================================================ 22. the one ladder ([ladder] enabled): the stall pass takes the later rungs of an entry the hand-off audit or the dates pass made
# A pane with no turn running starts no ladder here. With the flag off (the default) sections 1 to 21 above are the ladder.
from stackshot.waits import ladder as LD
def ladder_cfg(on=True, **kw): server._cfg.CFG["ladder"] = {"enabled": on, "main_hours": 10000, **kw}      # main_hours: a value no scenario reaches; the hand-up of an item that has not moved is tests/ladder_progress_scenario.py's
def stall_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "no turn running" in p[1]]
cold("no json at all here"); COLD_MSGS.clear(); set_cfg(); set_stall()
server._cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder, as at the top (an earlier section's config swap may have dropped it)
check("22 off: the flag is off by default: no [ladder] section reads as off", not ladder_svc.ladder_on() and ladder_svc.ladder_look() == 30.0, None)
ladder_cfg(True)
check("22 on: [ladder] enabled = true turns it on (only a TOML true), look_minutes is the look time (30 by default; a bad value is the default)", ladder_svc.ladder_on() and ladder_svc.ladder_look() == 30.0
      and (ladder_cfg(True, look_minutes=20) or ladder_svc.ladder_look() == 20.0) and (ladder_cfg(True, look_minutes="x") or ladder_svc.ladder_look() == 30.0) and (ladder_cfg("yes") or not ladder_svc.ladder_on()), None)
ladder_cfg(True)

# A. a pane with no turn running starts no ladder: the items come to it from the dates pass's entry and the hand-off audit, not from the stall pass (the rungs themselves are tests/ladder_silence_scenario.py's)
item(83); cli_row("home-peer", "idle", IDLE0)
check("22 A: with the ladder on, a pane idle for 10 minutes, for 41 minutes and for hours starts nothing: no notice, no cold call, no step taken",
      all("a83" not in stk(t) for t in (T1, T1 + 31 * MIN, T1 + 41 * MIN + 1, T1 + 5 * 3600)) and not stall_notices("home-peer", 83) and not COLD_MSGS and not (stall_svc.stall_load().get("a83") or {}).get("step"), (pushes_to("home-peer", "a83"), COLD_MSGS, stall_svc.stall_load().get("a83")))
close(83)

# D. an untaken hand-off to a session is the hand-off audit's: the stall pass does not start it, so one item never has two ladders
item(86, mover="home-peer", handoff=H.new_record("home-peer", U["home-peer"], "home-send", IDLE0 + 5 * MIN, delivered_at=IDLE0 + 5 * MIN + 10)); cli_row("home-peer", "idle", IDLE0)
check("22 D: a hand-off that nobody took yet is left alone by the stall pass, however quiet its pane (no notice, no entry)", "a86" not in stk(T1 + 60 * MIN) and not pushes_to("home-peer", "a86") and "a86" not in stall_svc.stall_load(), (pushes_to("home-peer", "a86"), stall_svc.stall_load().get("a86")))
check("22 D: …until the hand-off audit brings it (its entry says so), and then the ladder takes the later rungs here, once, in its order",
      handoff_svc.handoff_tick(now=T1 + 61 * MIN, only=["a86"]) == ["a86"] and (stall_svc.stall_load().get("a86") or {}).get("via") == "handoff" and (drain() or True) and len(pushes_to("home-peer", "a86")) == 1
      and "a86" not in stk(T1 + 62 * MIN) and len(pushes_to("home-peer", "a86")) == 1 and "a86" in stk(T1 + 92 * MIN) and len(pushes_to("home-peer", "a86")) == 2, (pushes_to("home-peer", "a86"), stall_svc.stall_load().get("a86")))
close(86)

# E0. the flag off from the start: the old ladder's own first step and the cold call after it
ladder_cfg(False)
item(88, mover="home-peer2"); cli_row("home-peer2", "idle", IDLE0)
stk(T1)
n_cold = len(COLD_MSGS)
check("22 E0 off: with the flag off from the start the first step is the old ladder's (the notice, step 1) and the next is the cold call 10 minutes later", stall_svc.stall_load()["a88"]["step"] == 1 and "a88" in stk(T2) and len(COLD_MSGS) == n_cold + 1, (stall_svc.stall_load().get("a88"), COLD_MSGS[-1:]))
close(88)

# F. the ladder steps read in the old table when the flag is turned off
check("22 F off: pure: the ladder's steps read in the old table: ask 0, look 1, cold 1, builder 2, done 3; an entry the ladder did not write is as it was",
      [LD.unwind({"step": n, "ladder": True, "via": "handoff"})["step"] for n in range(5)] == [0, 1, 1, 2, 3] and "via" not in LD.unwind({"step": 1, "via": "handoff"}) and LD.unwind({"step": 3}) == {"step": 3} and LD.unwind(None) is None, None)
ladder_cfg(True)

check("16 follow: after every save of the run (the pass's moves, raises and returns) no OPEN record named someone but the item's mover", INV_SAVES[0] > 50 and not INV_BAD, (INV_SAVES[0], INV_BAD[:4]))
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
