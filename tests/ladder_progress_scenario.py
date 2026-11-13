"""Scenario test for the hand-up of an item that is not moving: with `[ladder] enabled`, an alive item (open, a session moves it, not waiting, not the owner's move) with NO PROGRESS for `[ladder] main_hours`
(4) goes up to its project's -main agent in the ladder's one notice (`server._ladder_stuck`, `_ladder_main_tell`), whatever its mover answers meanwhile. Progress is the item's own clock (model/progress.py, stamped by
`writes.save`): a step marked done or dropped, a state change, a pull request merged for the item. A status line, a note, a reply and a confirm are not. Fixture items, panes that are files in a temp folder,
messages recorded by a fake push, a fake clock (every pass is given its `now`, and the saves are stamped from a fake `time`), no live store, no network, no model call.

  1  pure: progress.moved (each kind, and what is none), at, stamp, due
  2  4 hours without progress: ONE notice to -main naming the item, the mover, how long it has not moved and what it is queued behind (the mover's other alive items by priority, then age); a History line; the mark
  3  no repeat within the next 4 hours, a repeat after another 4 hours of no progress, never one per pass
  4  one scenario per kind of progress (step done, step dropped, state change, pull request merged): each starts the 4 hours again from the save that made it, through a real `writes.save`
  5  what is no progress (a status line, a note, a reply, a confirm, a new step): the clock stays, the item goes up as it would have
  6  a busy mover that answers "no change" every 90 minutes (a work line in progress, a note, a reply) is still handed up at 4 hours, once
  7  out of scope: a waiting item and the owner's moves
  8  several items due in one pass: ONE notice that lists them
  9  the setting `[ladder] main_hours` (4; a bad value is 4) and the ladder switch
 10  a project with no -main agent: the History line alone
 11  the stall pass's silent-mover notice and this hand-up share one mark: an item handed up the one way is not handed up the other within the interval

    tests/run-suite ladder_progress       -> exit 0 / 1"""
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
for d in ("store/a", "fleet/a", "state/audit", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import handoff as H_; from stackshot.waits import stall as S; from stackshot.waits import ladder as LD; from stackshot.audit import silence as SL; from stackshot.audit import audit_run as AR; from stackshot.audit import audit
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
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
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def look_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "nothing written for" in p[1]]
def stall_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "have had no turn running" in p[1]]
def set_cfg(**kw): server._cfg.CFG["model"] = dict(kw)
def ladder_cfg(enabled=True, **kw):
    # main_hours defaults to a value no scenario reaches: these sections test the silence ladder's rungs, and an item that has not moved for hours is handed up by the other way in (tests/ladder_progress_scenario.py)
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, "main_hours": 10000, **kw}.items() if v is not None}
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
server._stall_since(B)
def stk(at, prime=True):
    """One stall pass at `at` (the 20-second gate reset), the threads it started finished → the items it acted on. `prime`: the pass keeps when it first saw each item due (the server's alive record), and a
    scenario that runs one pass at the due time would otherwise see every item as alive just now: an item the record does not know yet is entered as alive long ago, as an item that has been due for days is."""
    if prime:
        rec_ = server._alive_load()
        for f_ in (T / "store/a").glob("*.json"): rec_.setdefault("a" + f_.stem, now0 - 100 * H)
        server._alive_save(rec_)
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
def entry(i): return server._stall_load().get(f"a{i}")

from stackshot.model import progress as PG; from stackshot.model import activity as ACT
def ladder_cfg(enabled=True, **kw):
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, **kw}.items() if v is not None}
def up_notices(i, to="home-front"): return [p for p in pushes_to(to, f"a{i}") if "has not moved for" in p[1]]
def prog(i, ts):
    """Put the item's progress clock at `ts` (the fixture has none: an unstamped item reads as last written)."""
    d_ = rd(i); d_["progress"] = ts; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
class _Clock:
    """The server's `time` module for the saves below: the progress clock is stamped from the server's own clock, which a scenario with a fake `now` must be able to set."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = handoff_svc.time = hcold_svc.time = CLK; writes.time = CLK
def save_at(ts, i, mutate, writer="home-peer", **kw):
    """A real `writes.save` of item `i` at the fake time `ts`, `mutate` changing the loaded item first: the stamp the progress clock takes is the one a live write takes."""
    d_ = server._load(f"a{i}"); mutate(d_); CLK.t = ts
    try: writes.save(f"a{i}", d_, writer=writer, **kw)
    finally: CLK.t = None
ladder_cfg(True, main_hours=4)
cli_row("home-peer", "busy", now0 - 20 * MIN); cli_row("home-peer2", "busy", now0 - 20 * MIN)

# ================================================================ 1. pure: progress.py
def step(text, status, at=0): return {"text": text, "status": status, "by": "x", "at": at}
base = {"status": "open", "metadata": {"mover": "m", "state": "doing", "needs": ["m"], "phase": "alive", "steps": [step("a", "open"), step("b", "done", 5)]}}
def with_meta(**kw): return {**base, "metadata": {**base["metadata"], **kw}}
check("1 moved: a step newly marked done or dropped is progress; one already marked, or a step only reworded or added, is not",
      PG.moved(base, with_meta(steps=[step("a", "done", 9), step("b", "done", 5)])) == ["step"] and PG.moved(base, with_meta(steps=[step("a", "dropped", 9), step("b", "done", 5)])) == ["step"]
      and not PG.moved(base, with_meta(steps=[step("a2", "open"), step("b", "done", 5), step("c", "open")])) and not PG.moved(base, with_meta(steps=[step("a", "open"), step("b", "done", 7)])), None)
check("1 moved: a state change is progress: the status (closed), the phase, the kind of a wait, the mover, the state and the needs",
      PG.moved(base, {**base, "status": "completed"}) == ["state"] and PG.moved(base, with_meta(phase="waiting", waits_on="time")) == ["state"] and PG.moved(base, with_meta(mover="n")) == ["state"]
      and PG.moved(base, with_meta(state="verifying")) == ["state"] and PG.moved(base, with_meta(needs=["m", "decision"])) == ["state"] and not PG.moved(base, with_meta(needs=["m"])), None)
check("1 moved: a save that is no one's write (a migration, the server's bookkeeping: real=False) moves the item only by its status and phase, never by a step mark, a merge note, a mover, a state or needs",
      not PG.moved(base, with_meta(steps=[step("a", "done", 9), step("b", "done", 5)]), False) and not PG.moved(base, with_meta(mover="n"), False) and not PG.moved(base, with_meta(released_told=["merged o/r#5"]), False)
      and PG.moved(base, {**base, "status": "completed"}, False) == ["state"] and PG.moved(base, with_meta(phase="waiting", waits_on="time"), False) == ["state"], None)
check("1 moved: a status line (work), a note, a description or a reworded next step is not progress", not PG.moved(base, with_meta(work=[{"id": "build", "state": "in progress", "agent": "m", "ts": 1}], next="m: other words"))
      and not PG.moved(base, {**base, "description": "other"}), None)
check("1 moved: a pull request newly recorded as merged is progress; a release (a bare ref) and one already recorded are not",
      PG.moved(base, with_meta(released_told=["merged o/r#5"])) == ["merged"] and not PG.moved(base, with_meta(released_told=["o/r#5"])) and not PG.moved(with_meta(released_told=["merged o/r#5"]), with_meta(released_told=["merged o/r#5"])), None)
check("1 moved: an item with no phase stored yet is not changed by the save that stores it; a new item is progress", not PG.moved({**base, "metadata": {k: v for k, v in base["metadata"].items() if k != "phase"}}, base) and PG.moved(None, base) == ["created"], None)
check("1 at: the stamp, else the latest of the last write, state change, activity and step mark; 0 for nothing", PG.at({"progress": 50.0, "updated": 90.0}) == 50.0 and PG.at({"updated": 10.0, "state_updated": 30.0, "activity": 20.0}) == 30.0
      and PG.at(with_meta(steps=[step("a", "done", 70)])) == 70.0 and PG.at({}) == 0.0, None)
seed = {"status": "open", "updated": 800.0}; PG.stamp(seed, {"status": "open", "updated": 800.0}, 5000.0)
check("1 stamp: …progress moves it", (lambda it: PG.stamp(it, base, 5000.0) and it["progress"] == 5000.0)({"progress": 1000.0, **with_meta(mover="n")}), None)
check("1 stamp: …a closed item has no clock (a repair that marks its steps leaves its file alone), a reopened one gets it from the state change",
      (lambda c_, r_: not PG.stamp(c_, {"status": "open", "metadata": {}}, 5000.0) and "progress" not in c_ and PG.stamp(r_, {"status": "completed", "metadata": {}}, 5000.0) and r_["progress"] == 5000.0)({"status": "completed", "metadata": {}}, {"status": "open", "metadata": {}}), None)
check("1 stamp: …a save that is none keeps it, and an item with no clock gets the one it read as before", (lambda it: not PG.stamp(it, base, 5000.0) and it["progress"] == 1000.0)({"progress": 1000.0, **base}) and seed["progress"] == 800.0, seed)
check("1 due: 4 hours without progress and 4 hours since the last hand-up", not PG.due({"progress": 100.0}, 100.0 + 4 * H - 1, 4) and PG.due({"progress": 100.0}, 100.0 + 4 * H, 4) and not PG.due({"progress": 100.0}, 100.0 + 8 * H, 4, handed_at=100.0 + 5 * H)
      and PG.due({"progress": 100.0}, 100.0 + 9 * H, 4, handed_at=100.0 + 5 * H) and not PG.due({}, 9e9, 4), None)

# ================================================================ 2. an item that has not moved for 4 hours goes up to -main, with the mover, the span and what it is queued behind
put(100, act=30, mover="home-peer"); prog(100, now0)
put(101, act=30, mover="home-peer", priority="p1"); prog(101, now0 + 3.9 * H)
put(102, act=30, mover="home-peer", priority="p3"); prog(102, now0 + 3.9 * H)
put(103, act=30, mover="home-peer", priority="p2"); prog(103, now0 + 3.9 * H)
put(104, act=30, mover="home-peer2", priority="p1"); prog(104, now0 + 3.9 * H)      # another mover's item: not in the line
check("2 not yet: 3 hours 59 minutes without progress sends nothing", "a100" not in stk(now0 + 3 * H + 59 * MIN) and not up_notices(100), pushes_to("home-front", "a100"))
done = stk(now0 + 4 * H)
n100 = up_notices(100); t100 = n100[0][1] if n100 else ""
check("2 4 hours: ONE notice goes to the project's -main agent and the item is acted on", "a100" in done and len(n100) == 1, (done, pushes_to("home-front")))
check("2 the notice is marked for the owner, names the item, the mover and how long it has not moved (4 hours), says a status line, a note or a reply does not count, and asks for a nudge or a different mover",
      t100.splitlines()[0] == "[for Oliver]" and server._gh.shown("a100") in t100 and "has not moved for 4 hours" in t100 and "its mover home-peer " in t100 and "a status line, a note or a reply does not count" in t100
      and "Decide whether it needs a nudge or a different mover" in t100, t100)
check("2 …and what it is queued behind: the mover's other alive items by priority, then age; another mover's item is left out",
      f"queued behind: {server._gh.shown('a101')} (p1), {server._gh.shown('a103')} (p2), {server._gh.shown('a102')} (p3)." in t100 and server._gh.shown("a104") not in t100, t100)
check("2 …and how to stop the repeats: get it moving, and that it comes again in 4 hours", "To stop the repeats, get the item moving (mark a step done or dropped, change its state, set its wait); it comes again in 4 hours while it does not move." in t100, t100)
check("2 the item stays with its mover (no cold call, no hand-off); a History line says it; the item carries the hand-up mark; the entry of the silence ladder is not touched",
      mt(100).get("mover") == "home-peer" and mt(100).get("progress_up_at") == now0 + 4 * H and any("has not moved it for 4 hours" in x["text"] and "was told to decide on a nudge or a different mover" in x["text"] for x in log_of(100))
      and not (entry(100) or {}).get("step") and not (entry(100) or {}).get("via"), (mt(100), log_of(100), entry(100)))
check("2 the item is as it was (no write by a session: its version and its progress clock unmoved)", rd(100)["updated"] == now0 - 30 * MIN and rd(100)["progress"] == now0, rd(100))
alone = [p for p in pushes() if "has not moved for" in p[1] or "have not moved" in p[1]]
check("2 only the item that is due is in it (the others moved less than 4 hours ago)", len(alone) == 1, alone)

# ================================================================ 3. no repeat within the next 4 hours; again after another 4 hours of no progress
for off in (4 * H + 60, 6 * H, 7 * H + 59 * MIN):
    stk(now0 + off)
check("3 no repeat: passes a minute, 2 hours and 3 hours 59 minutes after the hand-up add none", len(up_notices(100)) == 1, pushes_to("home-front", "a100"))
done = stk(now0 + 8 * H)
n3 = up_notices(100)
check("3 another 4 hours without progress: the same notice goes again, and says it was told before", "a100" in done and len(n3) == 2 and "was told about this at" in n3[1][1] and "has not moved since" in n3[1][1], pushes_to("home-front", "a100"))
stk(now0 + 8 * H + 60); stk(now0 + 11 * H)
check("3 …and not again until another 4 hours have passed (one per stretch, never one per pass)", len(up_notices(100)) == 2, pushes_to("home-front", "a100"))
close(100, 101, 102, 103, 104)

# ================================================================ 4. each kind of progress resets the 4 hours: the item would have gone up at +30 minutes; progress at +20 minutes moves it to +4 hours 20 minutes
def mover_change(d_): d_["metadata"]["mover"] = "home-peer2"; d_["metadata"]["needs"] = ["home-peer2"]
KINDS = (
    ("step marked done", lambda d_: d_["metadata"].update(steps=[step("home-peer: do the thing", "done", now0 + 20 * MIN), step("home-peer: more", "open")]), {}),
    ("step marked dropped", lambda d_: d_["metadata"].update(steps=[step("home-peer: do the thing", "dropped", now0 + 20 * MIN), step("home-peer: more", "open")]), {}),
    ("state change (a new mover)", mover_change, {}),
    ("pull request merged", lambda d_: d_["metadata"].update(released_told=["merged owner/repo#5"]), {"writer": "", "activity": ACT.EVENT}),
)
for k, (name, mutate, kw) in enumerate(KINDS):
    i = 110 + k; clear_pushes = len(pushes())
    put(i, act=30, mover="home-peer"); prog(i, now0 - 3 * H - 30 * MIN)
    save_at(now0 + 20 * MIN, i, mutate, **({"writer": "home-peer", **kw}))
    who = mt(i).get("mover")
    stk(now0 + 31 * MIN); stk(now0 + 2 * H); stk(now0 + 20 * MIN + 4 * H - 60)
    early = len(up_notices(i))
    done = stk(now0 + 20 * MIN + 4 * H)
    check(f"4 {name}: the 4 hours start again from it: nothing at +30 minutes, 2 hours or 4 hours less a minute after the progress", early == 0 and rd(i)["progress"] == now0 + 20 * MIN, (rd(i)["progress"], pushes_to("home-front", f"a{i}")))
    check(f"4 {name}: …and 4 hours after it the item goes up (once), naming the mover it has now", f"a{i}" in done and len(up_notices(i)) == 1 and f"its mover {who} " in up_notices(i)[0][1], (done, pushes_to("home-front", f"a{i}")))
    close(i)

# ================================================================ 5. a status line, a note, a reply and a confirm are no progress
NOT = (
    ("status line", lambda d_: d_["metadata"].update(work=[{"id": "build", "text": "building the fix", "state": "in progress", "agent": "home-peer", "ts": now0 + 20 * MIN}]), {}),
    ("note", lambda d_: None, {"note": "still on it", "activity": ACT.MESSAGE}),
    ("reply", lambda d_: d_["metadata"].update(next="home-peer: do the thing (no change)"), {}),
    ("confirm", lambda d_: d_.update(confirmed=now0 + 20 * MIN), {"activity": ACT.CONFIRM}),
    ("new step", lambda d_: d_["metadata"].update(steps=[step("home-peer: do the thing", "open"), step("home-peer: one more", "open")]), {}),
)
for k, (name, mutate, kw) in enumerate(NOT):
    i = 120 + k
    put(i, act=30, mover="home-peer"); prog(i, now0 - 3 * H - 30 * MIN)
    save_at(now0 + 20 * MIN, i, mutate, **({"writer": "home-peer", **kw}))
    done = stk(now0 + 31 * MIN)
    check(f"5 {name}: it is no progress: the clock stays and the item goes up at +30 minutes as it would have", rd(i)["progress"] == now0 - 3 * H - 30 * MIN and f"a{i}" in done and len(up_notices(i)) == 1, (rd(i)["progress"], pushes_to("home-front", f"a{i}")))
    close(i)

# ================================================================ 6. a busy mover that answers "no change" every 90 minutes is still handed up at 4 hours
put(130, act=30, mover="home-peer"); prog(130, now0)
for k in range(1, 3):       # +90 minutes and +180 minutes: a work line in progress, a note and a reply each time, the pane busy
    t = now0 + k * 90 * MIN
    save_at(t, 130, lambda d_: d_["metadata"].update(work=[{"id": "build", "text": "building the fix", "state": "in progress", "agent": "home-peer", "ts": t}], next=f"home-peer: do the thing (no change {k})"),
            note="no change", activity=ACT.MESSAGE)
    check(f"6 answer {k} (+{k * 90} minutes): the reply moved the activity clock, not the progress clock, and nothing has gone up yet", rd(130)["activity"] == t and rd(130)["progress"] == now0 and not up_notices(130) and "a130" not in stk(t + 1), (rd(130), pushes_to("home-front", "a130")))
save_at(now0 + 3 * H + 59 * MIN, 130, lambda d_: d_["metadata"].update(next="home-peer: do the thing (no change 3)"), note="no change", activity=ACT.MESSAGE)
done = stk(now0 + 4 * H)
check("6 4 hours after the last progress, with replies every 90 minutes (the last one a minute before) and a work line in progress: the item goes up, once", "a130" in done and len(up_notices(130)) == 1 and "has not moved for 4 hours" in up_notices(130)[0][1], (done, pushes_to("home-front", "a130")))
for off in (4 * H + 90 * MIN, 5 * H + 90 * MIN, 7 * H + 59 * MIN):
    save_at(now0 + off - 60, 130, lambda d_: d_["metadata"].update(next=f"home-peer: do the thing (no change {off})"), note="no change", activity=ACT.MESSAGE)
    stk(now0 + off)
check("6 …and the replies that go on every 90 minutes do not send it again before the next 4 hours", len(up_notices(130)) == 1, pushes_to("home-front", "a130"))
close(130)

# ================================================================ 7. out of scope: a waiting item and the owner's move
def waits_after(i, dep):
    d_ = rd(i); d_["metadata"].pop("state", None); d_["metadata"].pop("needs", None); d_["metadata"]["after"] = [dep]; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
put(140, act=30, mover="home-peer"); prog(140, now0 - 9 * H); put(141, act=30, mover="home-peer"); waits_after(141, "a140"); prog(141, now0 - 9 * H)
put(142, act=30, mover="home-peer", needs=["decision"]); prog(142, now0 - 9 * H)
put(143, act=30, mover="Oliver"); prog(143, now0 - 9 * H)
stk(now0 + 1)
drain()
check("7 a waiting item (an open `after` link) and the owner's moves (a decision, the owner as mover) are not handed up; the alive item they wait behind is", len(up_notices(140)) == 1 and not any(mt(i).get("progress_up_at") for i in (141, 142, 143)) and mt(140).get("progress_up_at"),
      ([mt(i).get("progress_up_at") for i in (140, 141, 142, 143)], pushes_to("home-front")[-1:]))
close(140, 141, 142, 143)

# ================================================================ 8. several items due in one pass: ONE notice that lists them
put(150, act=30, mover="home-peer"); prog(150, now0 - 5 * H); put(151, act=30, mover="home-peer2"); prog(151, now0 - 6 * H)
c0 = len(pushes()); done = stk(now0 + 1)
batch = [p for p in pushes()[c0:] if p[0] == U["home-front"]]
check("8 two items due in one pass: ONE notice to -main lists both with the time since the last progress and what each is queued behind", sorted(done) == ["a150", "a151"] and len(batch) == 1
      and batch[0][1].count("\n- ") == 2 and batch[0][1].count("no progress since") == 2 and batch[0][1].count("queued behind") == 2 and batch[0][1].splitlines()[0] == "[for Oliver]" and "have not moved" in batch[0][1], batch)
close(150, 151)

# ================================================================ 9. the setting: main_hours (4), a bad value is 4, the ladder switch gates the path
put(160, act=30, mover="home-peer"); prog(160, now0)
ladder_cfg(True, main_hours=2)
check("9 main_hours = 2: the item goes up after 2 hours, not before, and the notice says it comes again in 2 hours", "a160" not in stk(now0 + 2 * H - 60) and "a160" in stk(now0 + 2 * H) and "again in 2 hours" in up_notices(160)[0][1], pushes_to("home-front", "a160"))
close(160)
check("9 main_hours: 4 when it is missing, zero, negative or not a number", all((ladder_cfg(True, **kw) or server._ladder_main_hours() == 4.0) for kw in ({}, {"main_hours": 0}, {"main_hours": -3}, {"main_hours": "x"})) and (ladder_cfg(True, main_hours=6) or server._ladder_main_hours() == 6.0), None)
put(161, act=30, mover="home-peer"); prog(161, now0 - 9 * H); ladder_cfg(False, main_hours=4)
check("9 the ladder switch off: nothing is handed up (the path is the ladder's)", "a161" not in stk(now0 + 1) and not up_notices(161), pushes_to("home-front", "a161"))
close(161); ladder_cfg(True, main_hours=4)

# ================================================================ 10. a project with no -main agent: the History line alone, once per stretch
put(170, act=30, mover="home-peer"); prog(170, now0 - 5 * H)
real_main = server._main_agent; server._main_agent = lambda project: ""
try:
    n_push = len(pushes()); done = stk(now0 + 1); done2 = stk(now0 + 61)
finally:
    server._main_agent = real_main
check("10 no -main agent: nothing is sent, a History line says so, the hand-up is marked once (the next pass does nothing)", "a170" in done and "a170" not in done2 and len(pushes()) == n_push and any("no -main agent to tell" in x["text"] for x in log_of(170)), (done, done2, log_of(170)))
close(170)

# ================================================================ 11. one message, one mark: a silent mover's notice (the stall ladder's own hand-up) counts as the hand-up
put(180, act=600, mover="home-peer"); prog(180, now0 - 9 * H)
server._ladder_main("a180", "home-peer", {}, now0)
drain(); c1 = len(up_notices(180)) + len([p for p in pushes_to("home-front", "a180") if "background mover" in p[1]])
stk(now0 + 1); stk(now0 + 2 * H)
check("11 an item the silent-mover notice just handed up is not handed up again for not moving: the mark is shared", c1 == 1 and not up_notices(180) and mt(180).get("progress_up_at") == now0, (pushes_to("home-front", "a180"), mt(180)))
close(180)

# ================================================================ 12. a parked item that becomes alive again is not handed up for the time it was parked: its 4 hours count from when it became alive
import datetime as _dt
def iso(ts): return _dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
def sweep_at(t):
    real_time = time.time; time.time = lambda: t      # the phase sweep reads the clock itself
    try: return server._phase_sweep()
    finally: time.time = real_time
# parked 9 hours ago with a wake 5 hours ahead: the board shows it waiting; the progress clock holds the park time
put(190, act=9 * 60, mover="home-peer"); prog(190, now0 - 9 * H)
d_ = rd(190); d_["metadata"].update(hold=True, wake=iso(now0 + 5 * H), phase="waiting", waits_on="time"); (T / "store/a/190.json").write_text(json.dumps(d_))
check("12 parked and waiting: not handed up however long ago it was parked", "a190" not in stk(now0 + 2 * H, prime=False) and not up_notices(190) and "a190" not in server._alive_load(), (pushes_to("home-front", "a190"), server._alive_load()))
swept = sweep_at(now0 + 4.5 * H)      # the sweep stores alive before the wake (the board's reading moves ahead of the wake): the two keys only, so the progress clock is the park time still
check("12 the phase sweep stores alive ahead of the wake and writes the two keys only: the progress clock is the park time still (no write of the item moved it), the item is still held", "a190" in swept and mt(190).get("phase") == "alive" and rd(190)["progress"] == now0 - 9 * H and mt(190).get("hold"), (swept, rd(190)))
T1 = now0 + 4.5 * H
stk(T1, prime=False)
check("12 the pass after it records when the item became alive (the board reads the stored phase), and does not hand it up on the park's age", not up_notices(190) and server._alive_load().get("a190") == T1 and rd(190)["progress"] == now0 - 9 * H, (server._alive_load(), pushes_to("home-front", "a190")))
save_at(now0 + 5 * H + 60, 190, lambda d: (d["metadata"].pop("hold", None), d["metadata"].pop("wake", None)), writer="")      # the wake passes and the server releases the hold: a save that finds the phase alive already, so it stamps no progress
check("12 the wake's release moves no progress either (the phase was alive already), and does not restart the alive record", rd(190)["progress"] == now0 - 9 * H and not mt(190).get("hold") and server._alive_load().get("a190") == T1, (rd(190), server._alive_load()))
stk(T1 + 60, prime=False); stk(now0 + 5 * H + 120, prime=False); stk(T1 + 4 * H - 60, prime=False)
check("12 …and it is not handed up until main_hours after it became alive", not up_notices(190) and not mt(190).get("progress_up_at"), pushes_to("home-front", "a190"))
done = stk(T1 + 4 * H + 60, prime=False)
check("12 …then it is, once, having been alive and not moving for 4 hours", "a190" in done and len(up_notices(190)) == 1 and "has not moved for 4 hours" in up_notices(190)[0][1], (done, pushes_to("home-front", "a190")))
close(190)
# the same for an item ordered after another: it is alive when the blocker closes, whatever its progress clock says
put(191, act=9 * 60, mover="home-peer"); prog(191, now0 - 9 * H)
d_ = rd(191); d_["metadata"].pop("state", None); d_["metadata"].pop("needs", None); d_["metadata"].update(after=["a192"], phase="waiting", waits_on="item"); (T / "store/a/191.json").write_text(json.dumps(d_))
put(192, act=30, mover="home-peer2"); prog(192, now0)
check("12 ordered after an open item: not handed up", "a191" not in stk(now0 + 1, prime=False) and "a191" not in server._alive_load(), pushes_to("home-front", "a191"))
close(192); sweep_at(now0 + 10)
check("12 the blocker closed: it is alive, and is not handed up at once", mt(191).get("phase") == "alive" and "a191" not in stk(now0 + 10, prime=False) and not up_notices(191), (mt(191), server._alive_load()))
check("12 …nor within the 4 hours after, and then it is", "a191" not in stk(now0 + 10 + 4 * H - 60, prime=False) and "a191" in stk(now0 + 10 + 4 * H + 60, prime=False) and len(up_notices(191)) == 1, pushes_to("home-front", "a191"))
close(191)
check("12 progress.due counts from the later of the last progress and when the item became alive", not PG.due({"progress": 0.0 + 100.0}, 100.0 + 5 * H, 4, 0.0, 100.0 + 2 * H) and PG.due({"progress": 100.0}, 100.0 + 6 * H, 4, 0.0, 100.0 + 2 * H), None)

# ================================================================ 13. the mover is the project's -main agent: its own wording, once per interval
put(195, act=30, mover="home-front"); prog(195, now0 - 5 * H)
d_ = rd(195); d_["metadata"]["owner"] = U["home-peer"]; (T / "store/a/195.json").write_text(json.dumps(d_))
n_push = len(pushes()); done = stk(now0 + 1); done2 = stk(now0 + 61); stk(now0 + 3 * H)
lines = [x["text"] for x in log_of(195)]
check("13 the mover is the -main agent: nobody is sent anything, and the History line says so (not 'no -main agent'), once in the interval", "a195" in done and len(pushes()) == n_push and len([x for x in lines if "is the project's -main agent" in x]) == 1 and not any("has no -main agent" in x for x in lines), (done, done2, lines))
close(195)

# ================================================================ 14. a pull request merged for the item is progress, whether or not it settles a step: the hub's merge log (anchors/merge_log.py), tied to items by merge_tie
from stackshot.anchors import merge_log as ML; from stackshot.model import merge_tie as MT
from stackshot.anchors.anchorhub import core as HUB
W_ = "https://github.com/acme/widgets"
def shown(i): return f"board#{i}"
def handed(i): return [p for p in pushes_to("home-front", f'a{i} "[home] item {i}"') if "queued behind" in p[1]]      # the notices that name the item as the one not moving (alone, or one of several that came due together), not as what another is queued behind
def merge_pass(now):
    """One merge pass at `now`, the saves stamped at it; the board id board#<n> is the fixture item a<n> for the pass (the fixtures are a<n>: [github] issues_letter), and the other sections' ids are left as they were."""
    gh_ = server._cfg.CFG.setdefault("github", {}); had = gh_.get("issues_letter"); gh_["issues_letter"] = "a"; CLK.t = now
    try: return server._merge_progress_tick(now)
    finally:
        CLK.t = None
        if had is None: gh_.pop("issues_letter", None)
        else: gh_["issues_letter"] = had
check("14 merge_log.refs: the board ids a body names, once each, in order; a bare #n, owner/repo#n and board-ish words are not", ML.refs("Closes " + shown(9301) + " and " + shown(9302) + ", " + shown(9301) + " again; see #5, acme/widgets#6, a board #9303") == [shown(9301), shown(9302)] and ML.refs(None) == []
      and len(ML.refs(" ".join(f"board#{n}" for n in range(1, 30)))) == ML.MAX_REFS, ML.refs("Closes " + shown(9301) + " and " + shown(9302) + ", " + shown(9301) + " again; see #5, acme/widgets#6, a board #9303"))
check("14 merge_log.pull_of: the anchor's own id, else the link of the event (a pull request page or a comment on it); a release or a bare repository has none",
      ML.pull_of("github:Acme/Widgets#21") == ("acme/widgets", 21) and ML.pull_of("github:acme/widgets@notifications", f"{W_}/pull/22#issuecomment-5") == ("acme/widgets", 22)
      and ML.pull_of("github:acme/widgets@releases", "https://github.com/acme/widgets/releases/tag/v1") == ("", 0) and ML.pull_of("slack:C1") == ("", 0), None)
check("14 merge_log.line_for: only a merge (the type among a burst's, joined with +) of a pull request makes a line", ML.line_for("github:acme/widgets#21", "", "pr_merged", [shown(9203)], 5.0) == {"ts": 5.0, "repo": "acme/widgets", "n": 21, "refs": [shown(9203)]}
      and ML.line_for("github:acme/widgets#21", "", "comment+pr_merged", [], 5.0)["n"] == 21 and ML.line_for("github:acme/widgets#21", "", "pr_closed", [], 5.0) is None and ML.line_for("github:acme/widgets#21", "", "", [], 5.0) is None
      and ML.line_for("github:acme/widgets@releases", "", "pr_merged", [], 5.0) is None, None)
check("14 merge_tie.names: a URL names the pull request in any repository; #n, PR n and PR #n only for a repository the item speaks of without a URL; a prefix of a longer number or another repository's #n does not",
      MT.names(f"see {W_}/pull/21/files", "acme/widgets#21") and not MT.names(f"see {W_}/pull/210", "acme/widgets#21") and MT.names("PR #21 and more", "acme/widgets#21", ["acme/widgets"]) and MT.names("done in PR 21", "acme/widgets#21", ["acme/widgets"])
      and MT.names("#21 landed", "acme/widgets#21", ["acme/widgets"]) and not MT.names("#21 landed", "acme/widgets#21", ["other/repo"]) and not MT.names(shown(9221) + " and acme/widgets#21", "acme/widgets#21", ["acme/widgets"])
      and not MT.names("#210", "acme/widgets#21", ["acme/widgets"]), None)
check("14 progress.merges: a key of merged_seen counts as a merge recorded (one with the same pull request in released_told is one); progress.moved sees it newly added",
      PG.merges(with_meta(merged_seen=["a/b#1"], released_told=["merged a/b#1", "a/b#2"])) == frozenset({"merged a/b#1"}) and PG.moved(base, with_meta(merged_seen=["a/b#1"])) == ["merged"]
      and not PG.moved(with_meta(merged_seen=["a/b#1"]), with_meta(merged_seen=["a/b#1"])) and not PG.moved(base, with_meta(merged_seen=["a/b#1"]), False), None)

# the log, the anchors and the items. The items would all go up at +30 minutes; a merge tied to one at +20 minutes moves its clock to then.
def line(n, refs=(), at=20 * MIN): return {"ts": now0 + at, "repo": "acme/widgets", "n": n, "refs": list(refs)}
anchors_ = {"projects/alpha": [{"url": f"{W_}/pull/21", "items": ["a200"]}, {"url": f"{W_}/pull/22"}, {"url": f"{W_}/pull/30", "items": ["a205"]}, {"url": f"{W_}/pull/32", "items": ["a207"]}, {"url": f"{W_}/pull/28", "items": ["a212", "a213"]}]}
(T / "store/anchors.json").write_text(json.dumps(anchors_))
def fixture(i, **meta): put(i, act=30, mover="home-peer", **meta); prog(i, now0 - 3 * H - 30 * MIN)
for i in (200, 201, 202, 203, 204, 205, 207, 211): fixture(i)
fixture(206, project="projects/beta")      # an item of another project: its bare "#25" may be another repository's
d_ = rd(204); d_["description"] = f"- Waits on {W_}/pull/23\n- Done when it lands"; (T / "store/a/204.json").write_text(json.dumps(d_))
d_ = rd(205); d_["metadata"]["steps"] = [step("home-peer: land PR #24 and check it", "open")]; (T / "store/a/205.json").write_text(json.dumps(d_))
d_ = rd(206); d_["metadata"]["steps"] = [step("home-peer: land PR #25 and check it", "open")]; (T / "store/a/206.json").write_text(json.dumps(d_))      # the number alone, in a project that holds no anchor in that repository and with none of its own: not tied
d_ = rd(211); d_["metadata"]["steps"] = [step("home-peer: land PR #26 and check it", "open")]; (T / "store/a/211.json").write_text(json.dumps(d_))      # the number alone, in the project that holds anchors in that repository: tied
fixture(212, hold=True, wake=iso(now0 + 5 * H), phase="waiting", waits_on="time")      # held and waiting for a dated wake, with an anchor on the merged pull request: not on the stall ladder
fixture(213); waits_after(213, "a203"); prog(213, now0 - 3 * H - 30 * MIN)             # ordered after an open item, the same anchor: not on the stall ladder
fixture(208, project="projects/alpha"); close(208)                                   # a closed item named by the body: left alone
for ln in (line(21), line(22), line(23), line(24), line(25), line(26), line(28), line(99), line(31, [shown(201), shown(208), shown(9299)]), line(40, [shown(201)])):
    ML.append(ln)
saved = merge_pass(now0 + 21 * MIN)
check("14 the pass saves exactly the items a merge is tied to: anchored (a200), the body naming it (a201, also by a merge no anchor holds), its own words (a204 by URL, a205 by number with a pull request of its repository anchored, a211 by number in the project that holds the repository's anchors)",
      sorted(saved) == ["a200", "a201", "a204", "a205", "a211"], saved)
check("14 …each moved its clock to the save (progress = the pass's time), recorded the key in merged_seen, and said why in the History", all(rd(i)["progress"] == now0 + 21 * MIN and rd(i)["updated"] == now0 + 21 * MIN for i in (200, 201, 204, 205, 211))
      and mt(200).get("merged_seen") == ["acme/widgets#21"] and sorted(mt(201).get("merged_seen")) == ["acme/widgets#31", "acme/widgets#40"] and mt(204).get("merged_seen") == ["acme/widgets#23"] and mt(205).get("merged_seen") == ["acme/widgets#24"]
      and any("an anchor of the item names it" in x["text"] for x in log_of(200)) and any("description names the item" in x["text"] for x in log_of(201)) and any("own words name it" in x["text"] for x in log_of(204)),
      ([rd(i).get("progress") for i in (200, 201, 204, 205)], [mt(i).get("merged_seen") for i in (200, 201, 204, 205)], log_of(201)))
check("14 a project-wide anchor's merge (a202's project holds #22 for nobody), an unrelated merge (#99), a bare number in an item of another project (a206: its PR number may be another repository's), a closed item named by the body (a208) and an anchored item the board shows held (a212) or ordered after an open item (a213) move nothing: the clock stays and nothing is written",
      all(rd(i)["progress"] == now0 - 3 * H - 30 * MIN and "merged_seen" not in mt(i) for i in (202, 203, 206, 207, 208, 212, 213)) and rd(208).get("status") == "completed" and rd(202)["updated"] == now0 - 30 * MIN, [rd(i).get("progress") for i in (202, 203, 206, 207, 208)])
check("14 the pass keeps where it stopped: a second pass reads no line again and saves nothing", merge_pass(now0 + 22 * MIN) == [] and ML.read(server._merge_progress_offset())[0] == [], server._merge_progress_offset())
check("14 …and a line a pass sees again (the offset lost) is not saved twice: the item holds the key already", (server._merge_progress_save(0), merge_pass(now0 + 23 * MIN))[1] == [] and mt(200).get("merged_seen") == ["acme/widgets#21"] and rd(200)["progress"] == now0 + 21 * MIN, mt(200))
done = stk(now0 + 31 * MIN); stk(now0 + 2 * H); stk(now0 + 21 * MIN + 4 * H - 60)
check("14 the hand-up: the items the merge tied are not handed up at +30 minutes, 2 hours or 4 hours less a minute after it; the items it did not tie (a207: anchored to another pull request) went up at +30 minutes, once",
      not any(handed(i) for i in (200, 201, 204, 205, 211)) and all(len(handed(i)) == 1 for i in (202, 203, 207)) and sorted(done) == ["a202", "a203", "a206", "a207"], (done, [len(handed(i)) for i in (200, 201, 202, 203, 204, 205, 206, 207)]))
done = stk(now0 + 21 * MIN + 4 * H)
check("14 …and 4 hours after the merge they are, once each, with no merge in between", sorted(done) == ["a200", "a201", "a204", "a205", "a211"] and all(len(handed(i)) == 1 for i in (200, 201, 204, 205, 211)), (done, pushes_to("home-front", "a200")))
close(200, 201, 202, 203, 204, 205, 206, 207, 211, 212, 213)

# the first pass on a state directory with no offset reads only lines the clock could use (main_hours and 2 hours back); the offset file is then written
(T / "state/merge-progress.json").unlink(missing_ok=True)
fixture(209, project="projects/alpha"); fixture(210, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/50", "items": ["a209"]}, {"url": f"{W_}/pull/51", "items": ["a210"]}]}))
ML.append({"ts": now0 - 7 * H, "repo": "acme/widgets", "n": 50, "refs": []}); ML.append({"ts": now0 - 1 * H, "repo": "acme/widgets", "n": 51, "refs": []})
saved = merge_pass(now0)
check("14 the first pass: a merge older than main_hours + 2 hours is skipped (a209), a recent one counts (a210); the offset is kept", saved == ["a210"] and "merged_seen" not in mt(209) and server._merge_progress_offset() == ML.read(0)[1], (saved, server._merge_progress_offset()))
close(209, 210)

# a shorter or replaced merges.jsonl (the offset is past its end): read from the start with the first run's time filter, never a full replay
fixture(214, project="projects/alpha"); fixture(215, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/52", "items": ["a214"]}, {"url": f"{W_}/pull/53", "items": ["a215"]}]}))
off_before = server._merge_progress_offset()
ML.path().write_text(json.dumps({"ts": now0 - 7 * H, "repo": "acme/widgets", "n": 52, "refs": []}) + "\n" + json.dumps({"ts": now0 - 1 * H, "repo": "acme/widgets", "n": 53, "refs": []}) + "\n", encoding="utf-8")
saved = merge_pass(now0)
check("14 the file replaced by a shorter one (offset past its end): read from the start, only the lines the clock could use (a merge 7 hours old is skipped, one an hour old counts), the offset is the new end",
      off_before > ML.size() and saved == ["a215"] and "merged_seen" not in mt(214) and server._merge_progress_offset() == ML.size(), (off_before, ML.size(), saved, server._merge_progress_offset()))
close(214, 215)

# one item that cannot be read or saved does not abort the pass: the others are saved, the failure is logged, the offset is stored
for i in (216, 217, 218): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/54", "items": ["a216", "a217", "a218"]}]}))
ML.append(line(54, at=-60))
_real_save, _real_load = writes.save, server._load
def _bad_save(gid, *a, **kw):
    if gid == "a216": raise OSError("disk full")
    return _real_save(gid, *a, **kw)
def _bad_load(gid, *a, **kw):
    if gid == "a218" and _bad_load.on: raise OSError("unreadable")
    return _real_load(gid, *a, **kw)
_bad_load.on = False
writes.save, server._load = _bad_save, _bad_load
import io as _io, contextlib as _cl
errs = _io.StringIO()
try:
    _bad_load.on = True
    with _cl.redirect_stderr(errs): saved = merge_pass(now0)
finally:
    writes.save, server._load = _real_save, _real_load
check("14 an item whose save fails (a216) or whose read fails (a218) is logged and skipped; the other (a217) is saved, and the offset is stored so the pass does not repeat",
      saved == ["a217"] and "merged_seen" not in mt(216) and "merged_seen" not in mt(218) and mt(217).get("merged_seen") == ["acme/widgets#54"] and "a216 not saved" in errs.getvalue() and server._merge_progress_offset() == ML.size(),
      (saved, errs.getvalue()[-300:], server._merge_progress_offset(), ML.size()))
close(216, 217, 218)

# a malformed line between two good ones is logged and skipped, and the offset moves past it (it never stops the pass)
for i in (219, 220): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/70", "items": ["a219"]}, {"url": f"{W_}/pull/71", "items": ["a220"]}]}))
ML.append(line(70, at=-120))
with open(ML.path(), "a", encoding="utf-8") as f_:
    f_.write(json.dumps({"ts": "yesterday", "repo": "acme/widgets", "n": 5, "refs": []}) + "\n")      # a ts that is no number
    f_.write(json.dumps({"ts": now0, "repo": "acme/widgets", "n": "x", "refs": []}) + "\n")            # a pull request number that is none
    f_.write(json.dumps({"ts": now0, "repo": "not a repo", "n": 5, "refs": []}) + "\n")                # a repository that is none
    f_.write('{"ts": 1, "repo": "acme/wid\n')                                                           # a torn line that is no JSON at all
ML.append(line(71, at=-60))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): saved = merge_pass(now0)
check("14 a bad line (a ts or a pull request number that is none, a repository that is none, a torn line) between two good ones is logged and skipped: both good ones are saved and the offset moves to the end",
      sorted(saved) == ["a219", "a220"] and errs.getvalue().count("line skipped") == 3 and server._merge_progress_offset() == ML.size(), (saved, errs.getvalue()[-400:], server._merge_progress_offset(), ML.size()))
check("14 …and the pass after it reads nothing again (the offset is past the bad lines)", merge_pass(now0 + 60) == [] and server._merge_progress_offset() == ML.size(), None)
close(219, 220)

# the backlog of a downtime: on every pass (not only the first), a merge older than main_hours + 2 hours is no progress now, and is not stamped
for i in (221, 222): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/72", "items": ["a221"]}, {"url": f"{W_}/pull/73", "items": ["a222"]}]}))
ML.append(line(72, at=-30 * H)); ML.append(line(73, at=-60))
saved = merge_pass(now0)
check("14 a backlog line from 30 hours ago (the server was down) is not stamped on a pass that is not the first, a recent one is; the offset moves past both",
      saved == ["a222"] and "merged_seen" not in mt(221) and rd(221)["progress"] == now0 - 3 * H - 30 * MIN and server._merge_progress_offset() == ML.size(), (saved, server._merge_progress_offset(), ML.size()))
close(221, 222)

# which ids a body names: board#N, a temporary id, a legacy letter-and-number id and an item link, as a message's ids are read (code, quotes, glued ids and the queue's groups are not)
TMP_ = "board" + "-tmp-box" + chr(35)      # a temporary id and an item link, built from pieces so no id-shaped or link-shaped text sits in the source
HOST_ = "https" + ":" + "//host" + "/items/"
body_ = "Closes " + shown(9301) + ", " + TMP_ + "4 and g12. In code `" + shown(9302) + "`, fenced:\n```\n" + shown(9303) + "\n```\nquoted \"" + shown(9304) + "\", x_" + shown(9305) + ", group g7, [" + shown(9306) + "]" + "(" + HOST_ + "9306) and " + HOST_ + "9307"
check("14 merge_log.refs reads a body as a message's ids are read (model/ids.py): board#N, a temporary id, a legacy gNN id and an item link count; fenced code, inline code, quoted text, an id with something glued on and a merge queue's group number do not",
      ML.refs(body_) == [shown(9301), TMP_ + "4", "g12", shown(9306), shown(9307)], ML.refs(body_))
fixture(230, project="projects/alpha"); fixture(231, project="projects/alpha")
(T / "store/anchors.json").write_text("{}")
ML.append(line(74, ["board" + "-tmp-nobox" + chr(35) + "9", "zz", "a230"], at=-60))
saved = merge_pass(now0)
check("14 the server resolves a stored ref as it resolves any id (a legacy letter-and-number id, a000-style, names a230); a ref that names no item (another machine's temporary id, a word) is skipped and does not stop the pass",
      saved == ["a230"] and mt(230).get("merged_seen") == ["acme/widgets#74"] and "merged_seen" not in mt(231), saved)

# a failure in the anchor pass does not stop the merge pass (the minute tick runs both)
fixture(232, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/75", "items": ["a232"]}]}))
ML.append({"ts": time.time(), "repo": "acme/widgets", "n": 75, "refs": []})
_real_anchor_pass = wakes_svc.anchor_pass
def _broken_anchor_pass(): raise RuntimeError("anchor pass broke")
wakes_svc.anchor_pass = _broken_anchor_pass
errs = _io.StringIO()
try:
    with _cl.redirect_stderr(errs): wakes_svc.minute_anchor_pass()
finally:
    wakes_svc.anchor_pass = _real_anchor_pass
check("14 _minute_anchor_pass: an anchor pass that raises is logged and the merge pass still runs (the item the merge is tied to is saved)",
      "anchor pass: RuntimeError: anchor pass broke" in errs.getvalue() and mt(232).get("merged_seen") == ["acme/widgets#75"], (errs.getvalue()[-300:], mt(232)))
close(230, 231, 232)

# the item's own words include each step's status tag and the lines of its next: a session writes "PR 261 released; PR 262 in review" on the tag, or names the pull request on its next line, before any step text says it
def tagged(text): return step("home-peer: do the thing", "open") | {"tag": {"text": text, "state": "in progress", "ts": now0 - 3 * H}}
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/9999"}]}))      # the project holds an anchor in the repository (for no item): a bare number in its items speaks of that repository
fixture(250, project="projects/alpha", steps=[tagged("PR 260 released; PR 261 in review")])
fixture(251, project="projects/alpha", next="home-peer: land PR #262 and check it")
fixture(252, project="projects/beta", steps=[tagged("PR 263 in review")])      # the number alone in a tag, in a project that holds no anchor in the repository: another repository's number, not tied
fixture(253, project="projects/alpha", steps=[tagged("PR 264 in review")])
fixture(254, project="projects/alpha", steps=[step("home-peer: do the thing", "open"), step("home-peer: an earlier step", "done") | {"tag": {"text": "PR 266 released", "state": "done", "ts": now0 - 3 * H}}])      # a finished step keeps its tag: a stale "PR 266 released" ties nothing
fixture(255, project="projects/alpha", steps=[tagged("PR 266 released")])      # the same tag on an open step ties
for n_ in (261, 262, 263, 265, 266): ML.append(line(n_, at=-60))
saved = merge_pass(now0 + 21 * MIN)
check("14 the item's own words include a step's status tag (a250 names PR 261 only there, a255 PR 266) and a line of its next (a251 names PR 262 there): both tie, with the History line of the words", sorted(saved) == ["a250", "a251", "a255"]
      and mt(250).get("merged_seen") == ["acme/widgets#261"] and mt(251).get("merged_seen") == ["acme/widgets#262"] and mt(255).get("merged_seen") == ["acme/widgets#266"] and all(rd(i)["progress"] == now0 + 21 * MIN for i in (250, 251, 255))
      and any("own words name it" in x["text"] for x in log_of(250)) and any("own words name it" in x["text"] for x in log_of(251)), (saved, [mt(i).get("merged_seen") for i in (250, 251)], log_of(250)))
check("14 …a bare number in a tag of an item that does not speak of that repository (a252, project beta, PR 263) ties nothing, nor does a merge no word of an item names (#265), nor a number the tag did not name (a253 names 264, which did not merge), nor a tag on a done step (a254: the tag of a finished step is stale; the same words on an open step, a255, tie)",
      all("merged_seen" not in mt(i) and rd(i)["progress"] == now0 - 3 * H - 30 * MIN for i in (252, 253, 254)), [mt(i).get("merged_seen") for i in (252, 253, 254)])
close(250, 251, 252, 253, 254, 255)

# merge_tie: a bare number ties only an item of a project that holds an anchor in the repository, or with a pull request of it anchored; a URL ties anywhere
pg_ = MT.repo_pages({"projects/alpha": [{"url": f"{W_}/pull/1"}, {"url": "https://example.org/x"}], "projects/beta": [{"url": "https://github.com/other/repo/pull/2"}, "junk"]}, lambda u: "acme/widgets" if "acme/widgets" in u else "other/repo" if "other/repo" in u else "")
check("14 merge_tie.repo_pages: the pages that hold an anchor in each repository (any scope), others and malformed entries left out", pg_ == {"acme/widgets": {"projects/alpha"}, "other/repo": {"projects/beta"}}, pg_)
tx_ = {"i1": "see #7", "i2": "see #7", "i3": "see #7", "i4": f"see {W_}/pull/7"}
tied_ = MT.tied("acme/widgets#7", [], {"i3": {"acme/widgets#99"}}, tx_, {"i1": "projects/alpha", "i2": "projects/beta", "i3": "projects/beta", "i4": "projects/beta"}, pg_)
check("14 merge_tie.tied: the item of the repository's project (i1) and the one with a pull request of it anchored (i3) tie by a bare number, the item of another project (i2) does not, a URL ties it anywhere (i4)",
      tied_ == {"i1": "words", "i3": "words", "i4": "words"}, tied_)

# the hub: Hub.emit writes the line for a merge, before any lane, and for nothing else
hub_ = HUB.Hub(); hub_.deliver = lambda anchor, session, text: None; hub_.write_status = lambda: None; hub_.persist = lambda: "saved"
hub_.bindings = {"github:acme/widgets#60": {"home-peer"}, "github:acme/widgets@notifications": {"home-peer"}}
off_ = ML.read(0)[1]
def hub_event(anchor, etype, url, refs=None, text="merged it"):
    summary = {"title": "widgets#60", "who": "someone", "text": text, "url": url, "ts": "2026-11-12T00:00:00Z", "etype": etype}
    if refs is not None: summary["meta"] = {"refs": refs}
    hub_.event(anchor, summary, kind="github-state")
hub_event("github:acme/widgets#60", "pr_closed", f"{W_}/pull/60")
hub_event("github:acme/widgets#60", "ci_passed", f"{W_}/pull/60")
check("14 the hub: a closed pull request and a CI result write no line", ML.read(off_)[0] == [], ML.read(off_)[0])
hub_event("github:acme/widgets#60", "pr_merged", f"{W_}/pull/60", [shown(201)])
hub_event("github:acme/widgets@notifications", "comment+pr_merged", f"{W_}/pull/61#issuecomment-9", [], "merged on #61")
rows_, _o = ML.read(off_)
check("14 the hub: a merge writes one line (the anchored pull request, with the board ids its body names; a thread of a repository's notifications, by its link), whatever lane its notice takes",
      [(r["repo"], r["n"], r["refs"]) for r in rows_] == [("acme/widgets", 60, [shown(201)]), ("acme/widgets", 61, [])], rows_)
with open(ML.path(), "ab") as f_: f_.write(b'{"ts": 1, "repo": "acme/widgets", "n": 62, "refs": []}')      # a line the hub is still writing: no newline yet
part_rows, part_off = ML.read(_o)
with open(ML.path(), "ab") as f_: f_.write(b"\n")
whole_rows, whole_off = ML.read(_o)
check("14 merge_log.read: a line the hub is still writing (no newline yet) is not read, and is read whole next time; the offset moves past whole lines only",
      part_rows == [] and part_off == _o and [r["n"] for r in whole_rows] == [62] and whole_off == ML.path().stat().st_size, (part_rows, part_off, whole_rows, whole_off))
check("14 merge_log.read: an offset past the end (a replaced, shorter file) reads from the start; no file reads as nothing", ML.read(10 ** 9)[0][0]["n"] == 52 and (ML.path().rename(ML.path().with_suffix(".gone")), ML.read(5))[1] == ([], 5), None)

# a line that cannot be parsed costs only itself: deep nesting (RecursionError), an oversized number and a bad byte (ValueError) are skipped, the lines around them are read
ML.path().unlink(missing_ok=True)
deep_line = b"[" * 200000
big_num = b'{"repo": "acme/widgets", "n": ' + b"9" * 6000 + b"}"
ML.append({"ts": 1, "repo": "acme/widgets", "n": 71, "refs": []})
with open(ML.path(), "ab") as f_: f_.write(deep_line + b"\n" + big_num + b"\n" + b'\xff\xfe{"repo": "acme/widgets", "n": 99}\n')
ML.append({"ts": 2, "repo": "acme/widgets", "n": 72, "refs": []})
bad_rows, bad_off = ML.read(0)
check("14 merge_log.read: a line nested too deep to parse, an oversized number and a bad byte are each skipped, and the lines around them are still read",
      [r["n"] for r in bad_rows] == [71, 72] and bad_off == ML.path().stat().st_size, (bad_rows, bad_off))

# append starts on a line of its own when the file does not end with a newline, so two rows never glue together
ML.path().unlink(missing_ok=True)
ML.path().write_bytes(b'{"ts": 1, "repo": "acme/widgets", "n": 81, "refs": []}')      # no newline at the end (a torn write, a hand edit)
ML.append({"ts": 2, "repo": "acme/widgets", "n": 82, "refs": []})
glued_rows, _ = ML.read(0)
check("14 merge_log.append: a file that does not end with a newline gets one before the new row, so both rows read apart", [r["n"] for r in glued_rows] == [81, 82], glued_rows)
ML.append({"ts": 3, "repo": "acme/widgets", "n": 83, "refs": []})
raw_ = ML.path().read_bytes()
check("14 merge_log.append: a file that already ends with a newline gets no blank line; a first row in a new file starts with none",
      b"\n\n" not in raw_ and raw_.count(b"\n") == 3 and raw_.endswith(b"\n") and (ML.path().unlink(), ML.append({"ts": 4, "repo": "acme/widgets", "n": 84, "refs": []}), ML.path().read_bytes().startswith(b"{"))[2], raw_)

# ---- a line nested deeper than str() can follow: json still parses it, and `normal` used to turn its refs into text (RecursionError), then the handler turned the whole line into text (RecursionError again), so the pass
# died before it saved its offset and every pass after it read the same line. Nothing below assumes a depth: the depth is found at run time, the first one where str() on this interpreter fails (str() follows the C
# recursion limit of the interpreter, which is not always sys.getrecursionlimit()), starting from three times the Python limit.
def nest(d):
    x = []
    for _ in range(d): x = [x]
    return x
def str_fails(x):
    try: str(x)
    except RecursionError: return True
    return False
depth = sys.getrecursionlimit() * 3
while not str_fails(nest(depth)):
    depth = int(depth * 1.1) + 1
    assert depth < 3_000_000, depth
deep = nest(depth)
def attempt(fn):
    try: return fn()
    except Exception as e_: return f"raised {e_.__class__.__name__}"

# (1) normal: a ref is a string, anything else is no ref and is never turned into text
got = attempt(lambda: ML.normal({"ts": 1, "repo": "acme/widgets", "n": 5, "refs": [deep, "g12", [["g99"]], {"g98": deep}, "g13"]})["refs"])
check("14 merge_log.normal: a ref that is a list or an object, however deep, is skipped as no ref (never turned into text); the line keeps its string refs", got == ["g12", "g13"], got)
got = attempt(lambda: ML.normal({"ts": 1, "repo": "acme/widgets", "n": 5, "refs": [12, True, 1.5, None, "g12"]})["refs"])
check("14 merge_log.normal: a number, a boolean and none are no refs (12 and True would match a ref's shape as text)", got == ["g12"], got)

# (2) the handler: the exception's class, the first of its message and a bounded look at the line, never str(row)
import reprlib as _rl
from stackshot.anchors import event_log as EL
class _Hostile:
    def __repr__(self): raise RuntimeError("no repr")
class _NoClass:      # reprlib's own fallback reads x.__class__, so this one makes reprlib itself raise; only a class name read with type() survives it
    __class__ = property(lambda self: (_ for _ in ()).throw(RuntimeError("no class")))
    def __repr__(self): raise RuntimeError("no repr")
dict_deep = {}
for _ in range(depth): dict_deep = {"k": dict_deep}
wide = {k_: "v" * 200 for k_ in ("aaaa", "bbbb", "cccc", "dddd")}      # reprlib renders it at more than 80 characters, so the cap decides what is kept
t0_ = time.perf_counter()
got = attempt(lambda: (ML.shown(deep), ML.shown({"repo": deep}), ML.shown("x" * 5000), ML.shown({"a": "y" * 5000}), ML.shown(_Hostile()), ML.shown(wide), ML.shown(dict_deep), ML.shown({"a": "y" * 10**7}), ML.shown(_NoClass())))
took = time.perf_counter() - t0_
check("14 merge_log.shown: at most 80 characters for a deep structure, a long string and a long value; an object whose repr raises shows as its class (reprlib's own fallback)",
      isinstance(got, tuple) and all(len(x_) <= 80 for x_ in got) and got[4].startswith("<_Hostile"), got)
check("14 merge_log.shown: the cap is what cuts a row reprlib renders at more than 80 characters (the first 80 of it, no more, no less), and a second cap is honored",
      isinstance(got, tuple) and len(_rl.repr(wide)) > 80 and got[5] == _rl.repr(wide)[:80] and got[5].startswith("{'aaaa': 'vvv") and ML.shown(wide, 30) == _rl.repr(wide)[:30] and ML.shown(wide, 160) == _rl.repr(wide)[:160], got[5:6])
check("14 merge_log.shown: a dict nested past reprlib's depth shows its structure (the nesting, then '...'), not just its class; a 10-million-character value is cut at once",
      isinstance(got, tuple) and got[6].startswith("{'k': {'k': {'k':") and "..." in got[6] and got[6] != "<dict>" and got[7] == _rl.repr({"a": "y" * 10**7})[:80] and took < 1.0, (got[6:8], took))
check("14 merge_log.shown: when reprlib itself raises (an object whose repr and __class__ both raise: reprlib's own fallback reads __class__) the class name stands in, read with type(): it never raises",
      isinstance(got, tuple) and got[8] == "<_NoClass>" and got[0].startswith("[[[[") and "..." in got[0] and got[0] != "<list>", got[:1] + got[8:])
check("14 event_log.shown is merge_log.shown with a cap of 160: the same content, longer, and the same fallback",
      EL.shown(wide) == _rl.repr(wide)[:160] and len(EL.shown(wide)) > 80 and EL.shown(_NoClass()) == "<_NoClass>" and EL.shown(dict_deep) == ML.shown(dict_deep, 160) and EL.shown(deep) == ML.shown(deep, 160), None)

# (2b) normal: the wrong shapes it raises on, each by its class, and the bounds on repo and n
def raised(row):
    try: ML.normal(row)
    except Exception as e_: return e_.__class__.__name__
    return "none"
ok_row = {"ts": 1, "repo": "acme/widgets", "n": 5, "refs": []}
shapes = {"repo list": {**ok_row, "repo": deep}, "repo dict": {**ok_row, "repo": dict_deep}, "repo number": {**ok_row, "repo": 12}, "n 1e999": {**ok_row, "n": 1e999}, "ts 400 digits": {**ok_row, "ts": 10**400},
          "n text": {**ok_row, "n": "abc"}, "n list": {**ok_row, "n": [1]}, "repo long": {**ok_row, "repo": "a" * 70 + "/" + "b" * 71}, "n big": {**ok_row, "n": 10**12}, "n 0": {**ok_row, "n": 0}, "repo bad": {**ok_row, "repo": "nope"}}
got = {k_: raised(r_) for k_, r_ in shapes.items()}
check("14 merge_log.normal: each wrong shape raises by the class the docstring names (a repo that is not text is a TypeError before it is turned into text, however deep; n=1e999 and a time of 400 digits are OverflowError)",
      got == {"repo list": "TypeError", "repo dict": "TypeError", "repo number": "TypeError", "n 1e999": "OverflowError", "ts 400 digits": "OverflowError", "n text": "ValueError", "n list": "TypeError", "repo long": "ValueError", "n big": "ValueError", "n 0": "ValueError", "repo bad": "ValueError"}, got)
check("14 merge_log.normal: owner/repo at GitHub's longest (39 + 1 + 100) and a number at the bound are kept; one character more is not",
      raised({**ok_row, "repo": "a" * 39 + "/" + "b" * 100, "n": ML.MAX_NUMBER}) == "none" and raised({**ok_row, "repo": "a" * 40 + "/" + "b" * 100}) == "ValueError" and raised({**ok_row, "n": ML.MAX_NUMBER + 1}) == "ValueError", None)
try: ML.normal({**ok_row, "repo": "z" * 5000})
except ValueError as e_: msg_ = str(e_)
else: msg_ = ""
LONG_OK, LONG_BAD = "a" * 39 + "/" + "b" * 100, "a" * 40 + "/" + "b" * 100      # GitHub's longest owner/repo (140 characters), and one character more
caps_ok = [ML.line_for(f"github:{LONG_OK}#{ML.MAX_NUMBER}", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/{LONG_OK}/pull/{ML.MAX_NUMBER}", "pr_merged", [], 5.0), EL.lines_for(f"github:{LONG_OK}#{ML.MAX_NUMBER}", "", "pr_merged", "", [], 5.0)]
caps_bad = [ML.line_for(f"github:{LONG_BAD}#5", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/{LONG_BAD}/pull/5", "pr_merged", [], 5.0), ML.line_for(f"github:acme/widgets#{ML.MAX_NUMBER + 1}", "", "pr_merged", [], 5.0),
            ML.line_for(f"github:acme/widgets#{'9' * 400}", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/acme/widgets/pull/{ML.MAX_NUMBER + 1}", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/acme/widgets/pull/{'7' * 30}", "pr_merged", [], 5.0),
            EL.lines_for(f"github:{LONG_BAD}#5", "", "pr_merged", "", [], 5.0), EL.lines_for(f"github:acme/widgets#{ML.MAX_NUMBER + 1}", "", "pr_merged", "", [], 5.0)]
check("14 merge_log writers: a repository at the cap (140 characters) and a number at the cap (a billion) are written, and `normal` accepts each line", caps_ok[0] and caps_ok[1] and caps_ok[0]["n"] == ML.MAX_NUMBER and len(caps_ok[0]["repo"]) == ML.MAX_REPO and len(caps_ok[2]) == 1
      and ML.normal(caps_ok[0])["n"] == ML.MAX_NUMBER and ML.normal(caps_ok[1])["repo"] == LONG_OK, caps_ok)
check("14 merge_log writers: an over-cap repository or number (an anchor or a link, a run of digits however long) is no line at all, never one the reader would refuse; the same for event_log.lines_for",
      caps_bad[:6] == [None] * 6 and caps_bad[6:] == [[], []] and ML.pull_of(f"github:{LONG_BAD}#5") == ("", 0) and ML.pull_of("", f"https://github.com/acme/widgets/pull/{ML.MAX_NUMBER + 1}") == ("", 0), caps_bad)
check("14 merge_log: the regexes bound their digit runs and name parts, so no pattern can match a run longer than the caps (a 30-digit number is not read as its first ten)", "{1,10}" in ML._ANCHOR.pattern and "{1,10}" in ML._GITHUB_PATH.pattern and "{1,140}" in ML._ANCHOR.pattern
      and ML.pull_of("", f"https://github.com/acme/widgets/pull/{'1' * 30}") == ("", 0), (ML._ANCHOR.pattern, ML._GITHUB_PATH.pattern))
_eleven = "https://github.com/a/b/pull/10000000001"      # eleven digits whose first ten are at the cap: only the lookahead keeps it from reading as number 1000000000
_no_look = re.compile(ML._GITHUB_PATH.pattern.replace(r"(?!\d)", ""), re.I).search(_eleven)
check("14 merge_log: the link pattern's lookahead is what refuses an eleven-digit number whose first ten digits are within the cap (without it the link reads as a/b#1000000000)",
      r"(?!\d)" in ML._GITHUB_PATH.pattern and _no_look is not None and (_no_look.group(1), int(_no_look.group(2))) == ("a/b", 1000000000)
      and ML._GITHUB_PATH.search(_eleven) is None and ML.pull_of("", _eleven) == ("", 0), (_no_look and _no_look.groups(), ML.pull_of("", _eleven)))
check("14 merge_log.normal: the message of a refused line holds no more than the start of a long repo (it rides into a log line)", msg_.startswith("not a merge line: repo='zzz") and "z" * 41 not in msg_ and len(msg_) < 120, msg_)
errs = _io.StringIO()
with _cl.redirect_stderr(errs): kept = attempt(lambda: server._merge_rows([{"ts": now0, "repo": deep, "n": 5, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": 6, "refs": []}], now0))
logged = [l_ for l_ in errs.getvalue().splitlines() if "line skipped" in l_]
check("14 _merge_rows: a line whose repo nests too deep for str() is logged as its exception class and a bounded look (one short line), and the line after it is kept",
      isinstance(kept, list) and [r_["n"] for r_ in kept] == [6] and len(logged) == 1 and "TypeError" in logged[0] and len(logged[0]) < 300, (kept, logged and logged[0][:300]))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): kept = attempt(lambda: server._merge_rows([{"ts": now0, "repo": "not-a-repo", "n": 7, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": "x" * 50, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": 8, "refs": []}], now0))
logged = [l_ for l_ in errs.getvalue().splitlines() if "line skipped" in l_]
check("14 _merge_rows: the log line carries the start of the exception's message beside its class (the repo that was refused; the text int() choked on), cut at 80, and the line after is kept",
      isinstance(kept, list) and [r_["n"] for r_ in kept] == [8] and len(logged) == 2 and "ValueError: not a merge line: repo='not-a-repo'" in logged[0] and "ValueError: invalid literal for int()" in logged[1]
      and all(len(l_) < 330 for l_ in logged), logged)

# (4) the whole pass: first with the lines handed in from memory (no parse, so no interpreter's parse depth matters), then through the file (the lines are parsed, or dropped by read, whichever this interpreter does)
for i in (240, 241, 242, 243): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{90 + k}", "items": [f"a{240 + k}"]} for k in range(4)]}))
ML.path().unlink(missing_ok=True); server._merge_progress_save(0)
SENT = 4321
_real_read = ML.read
ML.read = lambda offset=0, file=None: ([{"ts": now0, "repo": "acme/widgets", "n": 95, "refs": [deep, 12, "g12"]}, {"ts": now0, "repo": deep, "n": 96, "refs": []}, line(93, at=-30)], SENT)
errs = _io.StringIO()
try:
    with _cl.redirect_stderr(errs): saved = attempt(lambda: merge_pass(now0))
finally:
    ML.read = _real_read
check("14 the pass, lines nested too deep for str() handed in: it does not stop, the line after them moves its item's clock, and the offset is saved",
      saved == ["a243"] and server._merge_progress_offset() == SENT and mt(243).get("merged_seen") == ["acme/widgets#93"] and rd(243)["progress"] > now0 - 3 * H and errs.getvalue().count("line skipped") == 1,
      (saved, server._merge_progress_offset(), errs.getvalue()[-300:]))
server._merge_progress_save(0)

# Where the lines of the next two checks go wrong is the interpreter's: json parses to a depth of its own and str() fails at another. On Python 3.14 json parses what str() cannot follow (json fails at 57,947
# levels, str at 47,413), so a deep line reaches `normal` and the handler through the file; on 3.12 and 3.13 both fail near 9,998, so `read` drops the line as unparseable and the handler never sees it. The checks
# through the file prove less there, and say so in their label; the checks above with the lines handed in from memory hold on every version.
try: json.loads("[" * depth + "]" * depth); through_file = "json parses these lines here: they reach normal and the handler"
except RecursionError: through_file = "json refuses these lines on this Python, so read drops them and this proves less than on 3.14"
ML.path().unlink(missing_ok=True)
ML.append(line(90, at=-120))
with open(ML.path(), "ab") as f_:
    f_.write(f'{{"ts": {int(now0)}, "repo": "acme/widgets", "n": 95, "refs": '.encode() + b"[" * depth + b"]" * depth + b"}\n")                  # nested refs
    f_.write(f'{{"ts": {int(now0)}, "repo": '.encode() + b"[" * depth + b"]" * depth + f', "n": 96, "refs": []}}\n'.encode())                     # a nested repo
ML.append(line(91, at=-60)); ML.append(line(92, at=-30))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): saved = attempt(lambda: merge_pass(now0))
check(f"14 the pass, the lines nested too deep for str() in the file: the offset is saved at its end, and the lines before and after them move their items' clocks [{through_file}]",
      isinstance(saved, list) and sorted(saved) == ["a240", "a241", "a242"] and server._merge_progress_offset() == ML.size() and all(rd(i)["progress"] > now0 - 3 * H for i in (240, 241, 242)), (saved, server._merge_progress_offset(), ML.size(), errs.getvalue()[-300:]))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): again = attempt(lambda: merge_pass(now0 + 60))
check(f"14 …and the pass after it does not read the deep lines again: nothing is saved, nothing is logged, the offset stays at the end [{through_file}]",
      again == [] and "line skipped" not in errs.getvalue() and server._merge_progress_offset() == ML.size(), (again, errs.getvalue()[-300:]))

# (3) the documented behaviour of read: a line that is not JSON, or too deep to parse, is dropped with no log line (the doc says so)
ML.path().unlink(missing_ok=True)
with open(ML.path(), "ab") as f_: f_.write(b"[" * 200000 + b"\n" + b'{"ts": 1, "repo": "acme/wid\n')
ML.append({"ts": 2, "repo": "acme/widgets", "n": 97, "refs": []})
with open(ML.path(), "ab") as f_: f_.write(b'{}\n[1]\n{"repo": "acme/widgets", "n": 0}\n{"repo": "", "n": 5}\n{"repo": "acme/widgets"}\n')      # parsed, but not an object with a repository and a number
ML.append({"ts": 3, "repo": "acme/widgets", "n": 98, "refs": []})
quiet = _io.StringIO()
with _cl.redirect_stderr(quiet): quiet_rows, _ = ML.read(0)
doc_ = pathlib.Path(STACK, "docs/stall-and-ladder.md").read_text(encoding="utf-8")
check("14 docs: the merge pass's section says that merge_log.read drops a line that is not JSON or is too deep to parse without a log line, and the code does exactly that (it prints nothing)",
      "`merge_log.read` without a log line" in doc_ and "(logged, the offset moves past it)" not in doc_ and [r_["n"] for r_ in quiet_rows] == [97, 98] and quiet.getvalue() == "", (quiet_rows, quiet.getvalue()[:200]))
check("14 docs: …and a line that parses but is no object with a repository and a number ({}, [1], a number of 0, an empty repository) is dropped by read the same way (not logged, as the section said), while a line with both and a wrong shape is logged by the pass",
      "so is a line that parses but is not an object with a repository and a number" in doc_ and "is logged by the pass as its exception class, the first 80 characters of its message" in doc_ and "a line that parses but is of the wrong shape is logged by the pass" not in doc_
      and all(r_.get("repo") and r_.get("n") for r_ in quiet_rows), doc_[doc_.find("so is a line that parses") - 100:doc_.find("so is a line that parses") + 200])
close(240, 241, 242, 243)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
