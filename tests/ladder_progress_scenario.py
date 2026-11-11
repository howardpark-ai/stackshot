"""Scenario test for the hand-up of an item that is not moving: with `[ladder] enabled`, an alive item (open, a session moves it, not waiting, not the owner's move) with NO PROGRESS for `[ladder] main_hours`
(4) goes up to its project's -main agent in the ladder's one notice (`server._ladder_stuck`, `_ladder_main_tell`), whatever its mover answers meanwhile. Progress is the item's own clock (model/progress.py, stamped by
`server._save`): a step marked done or dropped, a state change, a pull request merged for the item. A status line, a note, a reply and a confirm are not. Fixture items, panes that are files in a temp folder,
messages recorded by a fake push, a fake clock (every pass is given its `now`, and the saves are stamped from a fake `time`), no live store, no network, no model call.

  1  pure: progress.moved (each kind, and what is none), at, stamp, due
  2  4 hours without progress: ONE notice to -main naming the item, the mover, how long it has not moved and what it is queued behind (the mover's other alive items by priority, then age); a History line; the mark
  3  no repeat within the next 4 hours, a repeat after another 4 hours of no progress, never one per pass
  4  one scenario per kind of progress (step done, step dropped, state change, pull request merged): each starts the 4 hours again from the save that made it, through a real `_save`
  5  what is no progress (a status line, a note, a reply, a confirm, a new step): the clock stays, the item goes up as it would have
  6  a busy mover that answers "no change" every 90 minutes (a work line in progress, a note, a reply) is still handed up at 4 hours, once
  7  out of scope: a waiting item and the owner's moves
  8  several items due in one pass: ONE notice that lists them
  9  the setting `[ladder] main_hours` (4; a bad value is 4) and the ladder switch
 10  a project with no -main agent: the History line alone
 11  the silent mover's notice and this hand-up share one mark: an item handed up the one way is not handed up the other within the interval

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
    # main_hours defaults to a value no scenario reaches: these sections test the silence ladder's rungs, and an item that has not moved for hours is handed up by the other way in (tests/ladder_progress_scenario.py)
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, "silence": silence, "main_hours": 10000, **kw}.items() if v is not None}
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

from stackshot.model import progress as PG; from stackshot.model import activity as ACT
def ladder_cfg(enabled=True, silence=True, **kw):
    server._cfg.CFG["ladder"] = {k: v for k, v in {"enabled": enabled, "silence": silence, **kw}.items() if v is not None}
def up_notices(i, to="home-front"): return [p for p in pushes_to(to, f"a{i}") if "has not moved for" in p[1]]
def prog(i, ts):
    """Put the item's progress clock at `ts` (the fixture has none: an unstamped item reads as last written)."""
    d_ = rd(i); d_["progress"] = ts; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
class _Clock:
    """The server's `time` module for the saves below: the progress clock is stamped from the server's own clock, which a scenario with a fake `now` must be able to set."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = CLK
def save_at(ts, i, mutate, writer="home-peer", **kw):
    """A real `server._save` of item `i` at the fake time `ts`, `mutate` changing the loaded item first: the stamp the progress clock takes is the one a live write takes."""
    d_ = server._load(f"a{i}"); mutate(d_); CLK.t = ts
    try: server._save(f"a{i}", d_, writer=writer, **kw)
    finally: CLK.t = None
ladder_cfg(True, True, main_hours=4)
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
ladder_cfg(True, True, main_hours=2)
check("9 main_hours = 2: the item goes up after 2 hours, not before, and the notice says it comes again in 2 hours", "a160" not in stk(now0 + 2 * H - 60) and "a160" in stk(now0 + 2 * H) and "again in 2 hours" in up_notices(160)[0][1], pushes_to("home-front", "a160"))
close(160)
check("9 main_hours: 4 when it is missing, zero, negative or not a number", all((ladder_cfg(True, True, **kw) or server._ladder_main_hours() == 4.0) for kw in ({}, {"main_hours": 0}, {"main_hours": -3}, {"main_hours": "x"})) and (ladder_cfg(True, True, main_hours=6) or server._ladder_main_hours() == 6.0), None)
put(161, act=30, mover="home-peer"); prog(161, now0 - 9 * H); ladder_cfg(False, True, main_hours=4)
check("9 the ladder switch off: nothing is handed up (the path is the ladder's)", "a161" not in stk(now0 + 1) and not up_notices(161), pushes_to("home-front", "a161"))
close(161); ladder_cfg(True, True, main_hours=4)

# ================================================================ 10. a project with no -main agent: the History line alone, once per stretch
put(170, act=30, mover="home-peer"); prog(170, now0 - 5 * H)
real_main = server._main_agent; server._main_agent = lambda project: ""
try:
    n_push = len(pushes()); done = stk(now0 + 1); done2 = stk(now0 + 61)
finally:
    server._main_agent = real_main
check("10 no -main agent: nothing is sent, a History line says so, the hand-up is marked once (the next pass does nothing)", "a170" in done and "a170" not in done2 and len(pushes()) == n_push and any("no -main agent to tell" in x["text"] for x in log_of(170)), (done, done2, log_of(170)))
close(170)

# ================================================================ 11. one message, one mark: a silent mover's notice (the ladder's own way in) counts as the hand-up
put(180, act=600, mover="home-peer"); prog(180, now0 - 9 * H)
server._ladder_main("a180", "home-peer", {}, now0)
drain(); c1 = len(up_notices(180)) + len([p for p in pushes_to("home-front", "a180") if "background mover" in p[1]])
stk(now0 + 1); stk(now0 + 2 * H)
check("11 an item the silent-mover notice just handed up is not handed up again for not moving: the mark is shared", c1 == 1 and not up_notices(180) and mt(180).get("progress_up_at") == now0, (pushes_to("home-front", "a180"), mt(180)))
close(180)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
