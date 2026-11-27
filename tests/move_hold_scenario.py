"""Scenario test for the hold every pass asks before it changes an item's mover (service/move_hold.py): an item whose mover may be at work on it is not moved, and a hold that goes on is told. Fixture items in a temporary
store, the agent-state push stored and read by the server's own code, the pane rows replaced by a dict, no live store, no network, no model call, no message really sent.

  1  every module that writes an item's mover is accounted for here: a pass asks the hold, and anything else says why it takes nothing from a working mover
  2  the question: a subagent tied to the item, one tied to none, and subagents that cannot be read hold; nothing running, a mover with no pane, the owner and no mover do not
  3  each pass: the hand-off pass's write (the ladders, the orphan hand-over), the hand-off ladder, the stall pass's builder step, the end of a wait, the cold call's answer, the step hand-over after a proof
  4  a hold that goes on is told: after an hour (unreadable) or two (a subagent tied to nothing), a History line per item and one summary per project to its -main agent, at most daily; the record ends when the hold does
  5  `[audit] no_handoff` in the passes beside the balancer: the cold call, the return to the sender, a wait's end with nobody written to pick it up, the send-time refusal, the config lines

    tests/run-suite move_hold      -> exit 0 / 1"""
import ast, contextlib, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="movehold-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml = _instance.set_person(toml)
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: never the host's pane registry
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-main", "team-back", "team-aux", "team-rev", "home-peer", "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": time.time()} for n, u in U.items()}))
ALPHA = {"home-main": "the front", "team-back": "builds, merges and releases the code", "team-aux": "maintains and merges the notes", "team-rev": "reviews the notes"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                              "agents": ALPHA, "back_agents": {n: m for n, m in ALPHA.items() if not n.endswith("-main")}}}}))
back = "".join(f"    {n}: {m}\n" for n, m in ALPHA.items() if not n.endswith("-main")); front = "".join(f"  {n}: {m}\n" for n, m in ALPHA.items() if n.endswith("-main"))
(T / "brain/projects/alpha.md").write_text(f"---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n{front}  background:\n{back}---\n\n# alpha\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("90"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.service import audit_ticks as audit_ticks_svc, move_hold as mhold
from stackshot.service import handoff as handoff_svc, handoff_cold as hcold_svc, stall as stall_svc, watching as watching_svc, proofs as proofs_svc
from stackshot.service import agent_state as agent_state_store, telling, messaging as _messaging, update as _update_svc
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.audit import hand_idle as HI
from stackshot.tools import next_report as NR
from stackshot.waits import stall as ST, handoff as HO
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from fastmcp.exceptions import ToolError
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.PUSH = [sys.executable, "-c", "pass"]
_cfg.CFG["audit"]["pattern_review"] = "off"
_cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every notice the server was asked to send: (items, recipient's id, text, tag)
def fake_tell(gid, owner, note, tag="wake", result=None): sent.append((gid, owner, note, tag)); return None
telling.tell_woken = fake_tell
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append(("message", to, text, "message")), "delivered to " + to)[1]
panes = {}; dead = {}
handoff_svc.handoff_status = lambda who, idx=None: (panes.get(who, ""), now0 - 3600) if panes.get(who) else ("", 0.0)
handoff_svc.handoff_pane = lambda who, idx=None: dead.get(who, "")
_fleet_sessions_registry._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = proofs_svc._sessions_index = lambda: {}

def put(i, mover="home-peer", **meta):
    """An open item on `mover`, written two hours ago."""
    base = {"owner": U["home-main"], "project": "projects/alpha", "next": "do the thing", "state": "doing", "needs": [mover] if mover else [], **({"mover": mover} if mover else {})}
    base.update(meta)
    base = {k: v for k, v in base.items() if v is not None}
    at = now0 - 2 * H
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": at, "state_updated": at, "confirmed": at, "activity": at,
                                                     "written_at": at, "written_by": "home-stew", "metadata": base}))
def record(to="home-peer", frm="home-stew", mins=90, **extra):
    r = HO.new_record(to, U.get(to, ""), frm, now0 - mins * MIN); r["delivered_at"] = now0 - mins * MIN; r.update(extra)
    return r
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_text()
def mt(i): return rd(i)["metadata"]
def mover_of(i): return mt(i).get("mover")
def history(i): return [e["text"] for e in ST.log_of(mt(i))]
def shown(i): return _gh.shown(f"a{i}")      # as the board writes the id
def named(i): return NR.shown(f"a{i}")      # as a subagent's description names it
def agent(description): return {"id": f"agent-{len(description)}", "description": description, "brief": "", "at": now0 - 6 * MIN}
def on(i): return agent(f"build {named(i)}")
def push(*subagents, state="busy", pane="turn", written=None, who="home-peer"):
    """The agent-state push, stored by the server's own code: every agent idle, `who` as given."""
    written = time.time() - 30 if written is None else written
    row = lambda st, p, subs: {"state": st, "since": written - 600, "why": "a pane", "pane": p, "read": True, "subagents": list(subs)}
    agents = {n: row("idle", "idle", ()) for n in NAMES}
    agents[who] = row(state, pane if state == "busy" else "idle", subagents)
    code, ans = agent_state_store.post("a", {"schema": 1, "written": written, "agents": agents})
    assert code == 200 and "ignored" not in ans, (code, ans)
def idle(written=None): push(state="idle", written=written)
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    sent.clear(); panes.clear(); dead.clear(); _cfg.CFG["audit"].pop("no_handoff", None)
    agent_state_store.path().unlink(missing_ok=True); mhold.path().unlink(missing_ok=True)
def listed(*names): _cfg.CFG["audit"]["no_handoff"] = list(names)
def to_(name): return [x for x in sent if x[1] in (U[name], name)]

# ================================================================ 1. every writer of a mover is accounted for
HELPERS = ("turn_alive", "end_date", "turn_to_owner", "_needs_store")      # each writes the mover or needs (which names the mover where none is stored)
KEYS = ("mover", "needs")
def mover_writes(source):
    """The places of a module that write who moves an item: an assignment to `x["mover"]` or `x["needs"]`, setdefault of either, an update(...) given mover= or needs= (or a dict that holds one), and a call of a helper that writes them."""
    key = lambda n: isinstance(n, ast.Constant) and n.value in KEYS
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and key(n.slice):
            yield n.lineno
        if not isinstance(n, ast.Call):
            continue
        name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        if name == "setdefault" and n.args and key(n.args[0]):
            yield n.lineno
        if name in ("update", "_update", "update_item"):
            spread = [*n.args, *[k.value for k in n.keywords if k.arg is None]]
            if any(k.arg in KEYS for k in n.keywords) or any(isinstance(d, ast.Dict) and any(k is not None and key(k) for k in d.keys) for a in spread for d in ast.walk(a)):
                yield n.lineno
        if name in HELPERS or (name == "successor" and isinstance(n.func, ast.Attribute) and getattr(n.func.value, "id", "") == "_ho"):
            yield n.lineno
ASKS = "asks move_hold"
SESSION = "a session's own write"
HIS = "the owner's or a member's answer"
ONCE = "a one-time migration"
ACCOUNTED = {      # module under stackshot/ -> (how many writes, ASKS or why none of them takes an item from a working mover)
    "service/handoff.py": (2, ASKS),
    "service/handoff_cold.py": (2, ASKS),
    "service/proofs.py": (2, ASKS),
    "service/watching.py": (6, ASKS),
    "fleet/session_ids.py": (1, "an old session id rewritten to its name"),
    "model/cold_call.py": (1, "a key of the call's parsed answer, no item"),
    "model/migration.py": (6, ONCE),
    "model/model.py": (2, "rewrites the arguments of a session's own write"),
    "model/model_guards.py": (1, "a count in a report"),
    "model/needs.py": (1, "the helper, counted where it is called"),
    "service/agent_names.py": (2, "a session's own write or message names an agent in needs"),
    "service/answer.py": (2, HIS),
    "service/answer_handover.py": (5, HIS),
    "service/asks.py": (1, "an ask its author withdraws by their own word"),
    "service/gates.py": (3, SESSION),
    "service/migrations.py": (1, ONCE),
    "service/store.py": (2, "an item stored in an old form, rewritten"),
    "service/update.py": (5, SESSION),
    "service/wait_fixes.py": (1, "states the stored mover again"),
    "service/wait_gates.py": (2, HIS),
    "waits/members_pass.py": (1, ONCE),
    "waits/mover_pass.py": (3, ONCE),
    "waits/watchers.py": (4, "the helpers, counted where they are called"),
    "web/tools/update.py": (1, SESSION),
}
found = {}
for p_ in sorted(pathlib.Path(STACK, "stackshot").rglob("*.py")):
    if (hits := list(mover_writes(p_.read_text(encoding="utf-8")))):
        found[p_.relative_to(pathlib.Path(STACK, "stackshot")).as_posix()] = sorted(hits)
check("1 every module that writes a mover or needs is accounted for, with as many writes as listed: a new one asks move_hold (service/move_hold.py) or is listed here with why it takes nothing from a working mover",
      {k: len(v) for k, v in found.items()} == {k: v[0] for k, v in ACCOUNTED.items()}, {k: (v, ACCOUNTED.get(k)) for k, v in found.items() if len(v) != ACCOUNTED.get(k, (0,))[0]} or sorted(set(ACCOUNTED) - set(found)))
asking = [k for k, v in ACCOUNTED.items() if v[1] == ASKS]
check("1 …and each module listed as asking does call it", all(re.search(r"\b_mhold\.(held|checker)\(", pathlib.Path(STACK, "stackshot", k).read_text(encoding="utf-8")) for k in asking), asking)
FORMS = ('meta["mover"] = who', 'meta["needs"] = [who]', 'meta.setdefault("mover", who)', '_needs_store(meta, [who])', 'hooks().update(gid, mover=who)', 'hooks().update(gid, needs=[who])', 'update(gid, **({"mover": who} if x else {}))',
         'set_.update({"mover": who})', '_watch.turn_alive(m, who, w, now)', '_ho.successor(i, s, t, now)')
check("1 …and the scan sees each form a write takes, and no read", all(list(mover_writes(s)) == [1] for s in FORMS) and not list(mover_writes('x = meta["mover"]\nrow = {"mover": who}\nupdate(gid, next=n)')), [s for s in FORMS if not list(mover_writes(s))])

# ================================================================ 2. the question
wipe(); put(1); put(2)
push(on(1)); check("2 a subagent tied to the item holds it", mhold.held("a1", "home-peer") == HI.HOLD_TIED, mhold.held("a1", "home-peer"))
push(on(2)); check("2 …one tied to another item of the mover's does not", mhold.held("a1", "home-peer") == "", mhold.held("a1", "home-peer"))
push(agent("fix the flaky test")); check("2 …one tied to none of them does", mhold.held("a1", "home-peer") == HI.HOLD_UNTIED, mhold.held("a1", "home-peer"))
push(); check("2 a busy pane in a turn with no subagent holds nothing", mhold.held("a1", "home-peer") == "", mhold.held("a1", "home-peer"))
push(pane="shell"); got = mhold.held("a1", "home-peer")
check("2 a busy mover whose pane is not in a turn and that lists no subagent holds: nothing says what it runs", got.startswith(HI.HOLD_UNREAD), got)
idle(); check("2 an idle mover holds nothing", mhold.held("a1", "home-peer") == "")
agent_state_store.path().unlink(missing_ok=True); got = mhold.held("a1", "home-peer")
check("2 no push at all: unreadable, held", got.startswith(HI.HOLD_UNREAD), got)
dead["home-peer"] = "home-peer has no pane"
check("2 …but a mover with no pane runs nothing", mhold.held("a1", "home-peer") == "")
dead.clear()
check("2 the owner and no mover are nobody to take an item from", mhold.held("a1", "") == "" and mhold.held("a1", _cfg.owner()) == "")

# ================================================================ 3. each pass
def both(label, setup, run, stayed, moved, subagent=lambda: on(1), who="home-peer"):
    """The pass with a subagent of the mover on item 1 (it must hold) and with the mover idle (it must act, so the check can fail)."""
    wipe(); setup(); push(subagent(), who=who); got = run()
    check(f"3 {label}: held while a subagent of the mover is on the item", stayed(got) is True, (got, rd(1), sent))
    wipe(); setup(); push(state="idle", who=who); got = run()
    check(f"3 {label}: …and done with the mover idle", moved(got) is True, (got, rd(1), sent))
def step(via): return lambda: handoff_svc.handoff_exec([HO.Step("move", "a1", "home-peer did not take it", "home-peer", "team-back", via=via)], time.time(), verify=False)
for via in ("redirect", "return", "orphan"):
    before = []
    both(f"a move step of the hand-off pass's write (via {via})", lambda: (put(1, handoff=record()), before.clear(), before.append(raw(1))), step(via),
         lambda got: got == [] and raw(1) == before[0] and not sent, lambda got: got == ["a1"] and mover_of(1) == "team-back" and bool(to_("team-back")))
both("the hand-off ladder (the minute pass: an untaken hand-off goes to the project's builder)", lambda: put(1, handoff=record(reminded_at=now0 - 80 * MIN)), lambda: handoff_svc.handoff_tick(time.time(), only=["a1"]),
     lambda got: mover_of(1) == "home-peer" and not to_("team-back"), lambda got: mover_of(1) == "team-back" or got)
both("the stall pass's builder step (the one ladder takes it too)", lambda: put(1), lambda: stall_svc.stall_builder("a1", "home-peer", time.time(), 30),
     lambda got: got == "" and mover_of(1) == "home-peer" and not history(1) and "handoff" not in mt(1) and not sent, lambda got: got == "builder" and mover_of(1) == "team-back")
def fire():
    out = {}
    return watching_svc.watch_fire("a1", "time", time.time(), out), out
for label, wait in (("a wait with a kind", dict(wait_kind="time", wake="2026-01-02")), ("a wait on a date alone, back to others", dict(until="2026-01-02", needs=["external"]))):
    both(f"the end of {label} that would pass a front agent's item to the builder", lambda w=wait: put(1, mover="home-main", **{"state": "parked", "needs": ["home-main"], **w}), fire,
         lambda got: got[0] is True and mover_of(1) == "home-main" and any("the wait ended: the item stays with home-main and does not pass to team-back" in h and HI.HOLD_TIED in h for h in history(1))
         and list(got[1]) == [U["home-main"]], lambda got: got[0] is True and mover_of(1) == "team-back", who="home-main")

# the cold call: its answer is written as the stored record's call
ASKED = []
def answer_with(answer):
    def run(msg):
        ASKED.append(msg)
        return {"status": "ok", "text": json.dumps(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    hcold_svc.COLD_RUNNER = run
COLD_AT = now0 - MIN
def cold_item(): put(1, handoff=record(cold={"at": COLD_AT, "state": "running"}))
def cold():
    hcold_svc.handoff_cold("a1", COLD_AT)
    while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
HAND = {"action": "hand_to", "to": "team-aux", "reason": "it keeps the notes"}
answer_with(HAND)
both("the cold call's answer (hand over)", cold_item, cold,
     lambda got: mover_of(1) == "home-peer" and mt(1)["handoff"]["cold"]["state"] == "done" and any("the cold call's answer (hand_to) was not written" in h for h in history(1)) and not to_("team-aux"),
     lambda got: mover_of(1) == "team-aux")
answer_with({"action": "close", "outcome": "dropped", "outcome_text": "- It is no longer wanted\n- Nothing was built", "reason": "it is no longer wanted"})
both("the cold call's answer (close)", cold_item, cold,
     lambda got: rd(1)["status"] == "open" and any("the cold call's answer (close) was not written" in h for h in history(1)), lambda got: rd(1)["status"] != "open")

# the step hand-over: the server's tick hands on, a session's own mark is not asked
NEXT = "team-back: verify the pages"
def step_item(): put(1, next=NEXT)
def hand(by_pass): return lambda: proofs_svc.handover("a1", time.time(), ["home-peer: merge the part"], by_pass=by_pass)
both("the step hand-over after a proof's tick", step_item, hand(True),
     lambda got: got["action"] == "held" and got["why"] == HI.HOLD_TIED and mover_of(1) == "home-peer" and "handover" not in mt(1) and any("step hand-over" in h and "stays with home-peer" in h for h in history(1))
     and len(to_("home-peer")) == 1 and "stays with you" in to_("home-peer")[0][2] and not to_("team-back"), lambda got: got["action"] == "moved" and mover_of(1) == "team-back")
wipe(); step_item(); push(on(1)); got = hand(False)()
check("3 …a step a session marked itself is its own write: handed on whatever runs", got["action"] == "moved" and mover_of(1) == "team-back", got)

# ================================================================ 4. a hold that goes on is told
T0 = now0 - 40 * H
def stretch(start, until, gids=("a1",), subagent=None, every=25 * MIN):
    """The passes asking about `gids` and the report running, every `every` from `start` to `until` (both included) → [(time, the ids that report told)] where it told any."""
    out = []; at = start
    while True:
        if subagent is not None: push(subagent, written=at - 30)
        hold = mhold.checker(at)
        for g in gids: hold(g, "home-peer")
        if (told := mhold.report(at)): out.append((at, told))
        if at >= until: return out
        at = min(at + every, until)
def summaries(): return [x for x in sent if x[3] == "stall_summary"]
wipe(); put(1); put(2)
early = stretch(T0, T0 + H - 1, ("a1", "a2"))
check("4 unreadable subagents: nothing is said in the first hour", early == [] and not sent and not history(1), (early, sent))
first = stretch(T0 + H, T0 + H, ("a1", "a2"))
line = history(1)[0] if history(1) else ""
check("4 …after an hour each held item gets one History line that says who holds it, since when, why and that no pass moves it",
      first == [(T0 + H, ["a1", "a2"])] and len(history(1)) == 1 and len(history(2)) == 1 and line.startswith("held with home-peer since ") and HI.HOLD_UNREAD in line and "no pass moves it until that clears" in line, (first, history(1)))
check("4 …and the project's -main agent one summary naming both, a progress notice that asks nothing and is not the owner's", len(summaries()) == 1 and summaries()[0][0] == "a1,a2" and summaries()[0][1] == U["home-main"]
      and shown(1) in summaries()[0][2] and shown(2) in summaries()[0][2] and "moves are held on 2 items of projects/alpha" in summaries()[0][2] and "No reply is owed" in summaries()[0][2], summaries())
quiet = stretch(T0 + H + 25 * MIN, T0 + H + 86400 - 1, ("a1", "a2"))
check("4 …then nothing more within a day", quiet == [] and len(summaries()) == 1 and len(history(1)) == 1, (quiet, len(summaries())))
again = stretch(T0 + H + 86400, T0 + H + 86400, ("a1", "a2"))
check("4 …and once again a day later", again == [(T0 + H + 86400, ["a1", "a2"])] and len(summaries()) == 2 and len(history(1)) == 2, (again, len(summaries()), history(1)))
at = T0 + H + 86400 + MIN
idle(written=at); got = mhold.report(at)
check("4 …the record ends when the subagents read again, with no pass asking", got == [] and mhold.load()["items"] == {}, mhold.load())
idle(written=at + MIN); mhold.checker(at + MIN)("a1", "home-peer")
agent_state_store.path().unlink(missing_ok=True)
fresh = stretch(at + 2 * MIN, at + 2 * MIN + H - 1)
check("4 …and the next hold starts its own hour", fresh == [] and mhold.load()["items"]["a1"]["since"] == at + 2 * MIN, (fresh, mhold.load()))
wipe(); put(1)
mhold.checker(T0)("a1", "home-peer")
mhold.checker(T0 + 10 * MIN)("a1", "home-peer")
idle(written=T0 + 11 * MIN); free = mhold.checker(T0 + 11 * MIN)("a1", "home-peer")
check("4 …a pass that reads the item as free ends the record at once", free == "" and mhold.load()["items"] == {}, (free, mhold.load()))
wipe(); put(1); mhold.checker(T0)("a1", "home-peer")
got = mhold.report(T0 + H)
check("4 a hold no pass has asked about for half an hour is over: nothing is said and the record goes", got == [] and mhold.load()["items"] == {} and not history(1), (got, mhold.load()))
wipe(); put(1); mhold.checker(T0)("a1", "home-peer"); mhold.checker(T0 + H)("a1", "home-peer")
check("4 …and a pass that asks again after such a gap starts a new clock", mhold.load()["items"]["a1"]["since"] == T0 + H, mhold.load())
for label, change in (("closed", lambda: (T / "store/a/1.json").write_text(json.dumps({**rd(1), "status": "completed"}))), ("handed on", lambda: put(1, mover="team-aux"))):
    wipe(); put(1); mhold.checker(T0, once=True)("a1", "home-peer"); change()
    got = mhold.report(T0 + H)
    check(f"4 an item that was {label} is not reported and its record goes", got == [] and mhold.load()["items"] == {} and not sent, (got, mhold.load()))
wipe(); put(1); mhold.checker(T0, once=True)("a1", "home-peer")
got = mhold.report(T0 + H)
check("4 a step no pass retries (a wait's end, a cold answer, a step hand-over) is read again by the report itself: told after the hour", got == ["a1"] and len(summaries()) == 1 and history(1), (got, sent))
wipe(); put(1)
got = stretch(T0, T0 + 2 * H - 1, subagent=agent("fix the flaky test"))
check("4 a subagent tied to none of the mover's items: nothing is said for two hours", got == [] and not sent, got)
got = stretch(T0 + 2 * H, T0 + 2 * H, subagent=agent("fix the flaky test"))
check("4 …then it is, the same way", got == [(T0 + 2 * H, ["a1"])] and HI.HOLD_UNTIED in history(1)[0] and len(summaries()) == 1, (got, history(1)))
wipe(); put(1)
got = stretch(T0, T0 + 3 * H, subagent=on(1))
check("4 a subagent tied to the item is work in progress: held and never reported", got == [] and not sent and not history(1) and mhold.load()["items"] == {}, (got, mhold.load()))
wipe(); put(1, project="projects/unlisted"); got = stretch(T0, T0 + H)
check("4 a project with no -main agent gets the History line alone", got == [(T0 + H, ["a1"])] and history(1) and not sent, (got, sent))
wipe(); put(1); put(2)
stretch(T0, T0 + H, ("a1",)); stretch(T0 + H + MIN, T0 + 2 * H + MIN, ("a1", "a2"))
check("4 one summary per project in a day: an item that comes due later gets its History line, and no second message", len(history(2)) == 1 and len(summaries()) == 1, (history(2), len(summaries())))
called = []; real_report = mhold.report
mhold.report = lambda now=None: called.append(now) or []
try:
    wipe(); handoff_svc.handoff_tick(now0, only=["a1"]); a = list(called); handoff_svc.handoff_tick(now0)
    check("4 the report is run by the minute hand-off pass (not by a run limited to some items)", a == [] and called == [now0], (a, called))
finally:
    mhold.report = real_report

# ================================================================ 5. [audit] no_handoff beside the balancer
wipe(); cold_item(); idle(); listed("team-aux"); ASKED.clear(); answer_with(HAND); cold()
offered = ASKED[0].split("Sessions it may be handed to")[1] if ASKED else ""
check("5 the cold call does not offer a listed agent", "team-back" in offered and "team-aux" not in offered, offered)
check("5 …and an answer that names one is refused: the item does not go to it", mover_of(1) != "team-aux" and not to_("team-aux"), (mover_of(1), history(1), mt(1).get("handoff")))
def next_of(*names, tried=("team-back",)):
    wipe(); listed(*names)
    r = record(origin="team-rev", tried=list(tried))
    put(1, handoff=r)
    env = handoff_svc.handoff_env(time.time()); env.ladder = False
    st = HO.next_step({**rd(1), "gid": "a1"}, r, "home-peer", "home-peer did not take it", env, gid="a1", cold_ok=False)
    return st.kind, st.to, st.reason if hasattr(st, "reason") else st.why
got = next_of()
check("5 the hand-off ladder returns an item to its sender", got[:2] == ("move", "team-rev"), got)
got = next_of("team-rev")
check("5 …not to a listed one, and the last step says why", got[0] == "recover" and "its sender team-rev takes no hand-offs ([audit] no_handoff)" in str(got), got)
got = next_of("team-back", "team-aux", "team-rev", tried=())
check("5 …and with every builder listed it says that, not that the project lists none", got[0] == "recover" and "the project's builder takes no hand-offs ([audit] no_handoff)" in str(got) and "lists no builder" not in str(got), got)
def unwritten(*names, **meta):
    wipe(); listed(*names); idle()
    put(1, mover="", state="parked", wait_kind="time", wake="2026-01-02", next="do the thing", **meta)
    out = {}
    watching_svc.watch_fire("a1", "time", time.time(), out)
    return mover_of(1), out
base = unwritten()
got = unwritten("team-back")
check("5 a wait that ends with nobody written to pick it up gives a listed builder nothing: the next builder takes it, and History and the message say why", base[0] == "team-back" and got[0] == "team-aux"
      and list(got[1]) == [U["team-aux"]] and "takes no hand-offs, so it comes to you" in got[1][U["team-aux"]][0][2], (base, got, history(1)))
got = unwritten("team-back", "team-aux")
check("5 …the -main agent when no builder takes hand-offs", got[0] == "home-main", got)
got = unwritten("team-back", "team-aux", "home-main")
check("5 …and the pick stands when neither can", got[0] == "team-back", got)
wipe(); listed("team-back"); idle(); put(1, state="parked", mover="team-back", needs=["team-back"], wait_kind="time", wake="2026-01-02"); watching_svc.watch_fire("a1", "time", time.time(), {})
check("5 …and a listed agent somebody wrote as the one to pick it up keeps it", mover_of(1) == "team-back", mt(1))
wipe(); listed("team-back"); idle(); push(agent("fix the flaky test"), who="team-back")
put(1, mover="", state="parked", wait_kind="time", wake="2026-01-02", next="do the thing"); watching_svc.watch_fire("a1", "time", time.time(), {})
check("5 …nor is the item passed from a pick whose subagent may be on it", mover_of(1) == "team-back" and any("does not pass to team-aux" in h for h in history(1)), (mover_of(1), history(1)))
def refusal(*names):
    wipe(); listed(*names); put(1); dead["team-back"] = "team-back has no pane"
    try: _update_svc._update("a1", needs=["team-back"], sender="home-peer")
    except ToolError as e: return str(e)
    return ""
got = refusal()
check("5 the refusal of a send to a session with no pane names a background agent that has one", "The project's background agent team-aux has a pane" in got, got)
got = refusal("team-aux", "team-rev")
check("5 …with every one of those listed it says they take no hand-offs, not that none has a pane", "No background agent is named here: the project's with a pane (team-aux, team-rev) take no hand-offs ([audit] no_handoff). Hand it to a session that has one" in got
      and "no background agent with a pane either" not in got, got)
notes = lambda v: _cfg.audit_no_handoff_notes({"audit": {"no_handoff": v}})
check("5 the config lines: a value that is not a list, an entry that is not text or is blank; none for a good or an absent one", len(notes("team-back")) == 1 and "is not a list" in notes("team-back")[0] and len(notes([1, " ", "team-back"])) == 2
      and notes(["team-back"]) == [] and _cfg.audit_no_handoff_notes({"audit": {}}) == [], (notes("team-back"), notes([1, " "])))
_cfg.CFG["audit"]["no_handoff"] = "team-back"
check("5 …and they are among the config's own notes", any("no_handoff" in n for n in _cfg.notes()), _cfg.notes())
listed("team-back", "nobody-here", U["team-aux"])
got = _anc.no_handoff_notes()
check("5 …a name that matches no agent gets a line; a listed agent by name or id gets none", len(got) == 1 and "'nobody-here'" in got[0] and "keeps nobody out of a pass" in got[0], got)
(T / "stackshot.toml").write_text(re.sub(r"(?m)^(\[audit\][^\n]*\n)", r'\g<1>no_handoff = ["nobody-here"]\n', re.sub(r"(?m)^no_handoff = .*\n", "", toml)), encoding="utf-8")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    server._on_hup()
check("5 …said on a reload", "config: [audit] no_handoff names 'nobody-here'" in err.getvalue(), err.getvalue()[-800:])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
