"""Scenario test for the balancer (audit/hand_idle.py `balance_*`, server._balance_tick, its own minute tick ahead of the hand-off tick, `[audit] balance`): an item that is NOT STARTED (an untaken hand-off to a
builder) or QUEUED BEHIND its mover's other item and has waited `balance_minutes` (10) goes to the builder with the fewest open items, and the mover it left is told to disregard it. Fixture items in a temporary
store, a fake clock (the pass is given its `now`), the pane registry replaced by a dict, no live store, no network, no model call, no message really sent.

Every rule is a probe that returns whether the rule held on a fixture, run twice: as the code is (it must hold) and with that one rule reverted by a patch (it must fail), so a check that cannot fail is caught.

  1  on by default: the example config documents `balance = true` and `balance_minutes = 10`, absent or a TOML true is on, false / the string "true" / 1 are off, the minutes read at use with a floor of 1, a read-only copy and agent mode do nothing
  2  an untaken hand-off older than balance_minutes moves to the least-loaded builder: one History line, the new builder told, the former mover told ONCE to disregard it (not by the message tool), a balance record
  3  the wait: counted from the delivery (else from the hand-off), balance_minutes read at use, an item written to meanwhile stays
  4  a queued item moves (the queue read over the balancer's window, `[model] queued_behind` off), the item in hand never does
  5  an item its mover started never moves: a taken hand-off, a step status in progress or done, a step marked done, a subagent, an anchor, a pull request event; read again under the lock
  6  the load: ties, a busy pane only a tie-break, names merged, strict improvement for an untaken hand-off, the +1 rule for a queued one, two items in one pass, the cap of 3, never a front agent, a dead pane, the item's own mover
  7  no target: the item stays, one History line, -main told once per item per 24 hours, a notice that asks nothing
  8  no flapping: one move per item per 24 hours, two in all (then -main is told once), `tried` is never the target, the idle hand-over's record is apart
  9  the notice to the mover it left: one message for several items, only for ids this pass moved, never to a front agent
  10 the tick: its place before the hand-off tick, a failure that stops nothing, a move at ten minutes ahead of the hand-off tick's reminder
  11 a torn record is not a signal

    tests/run-suite balance       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="balance-"); T = pathlib.Path(tmp)
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
NAMES = ("home-main", "team-back", "team-aux", "other-back", "beta-main", "home-peer", "home-peer2", "home-stew", "lone-back", "lone-main", "team-rev", "gamma-main", "gamma-maint")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-main": "the front", "team-back": "builds, merges and releases the code", "team-aux": "maintains and merges the notes", "team-rev": "reviews the notes"}
BETA = {"beta-main": "the front", "other-back": "builds the beta code"}
LONE = {"lone-main": "the front", "lone-back": "reviews the notes", "home-peer": "builds the side code"}
GAMMA = {"gamma-main": "the front", "gamma-maint": "maintains and merges the library"}
pages = {"projects/alpha": ("home-stew", ALPHA), "projects/beta": ("beta-main", BETA), "projects/lone": ("lone-main", LONE), "projects/gamma": ("gamma-main", GAMMA)}
(T / "store/projects.json").write_text(json.dumps({"pages": {k: {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": s, "status": "active", "board": [], "board_open": 0,
                                                                  "agents": ag, "back_agents": {n: m for n, m in ag.items() if not n.endswith("-main")}} for k, (s, ag) in pages.items()}}))
for k, (s, ag) in pages.items():
    back = "".join(f"    {n}: {m}\n" for n, m in ag.items() if not n.endswith("-main")); front = "".join(f"  {n}: {m}\n" for n, m in ag.items() if n.endswith("-main"))
    (T / f"brain/{k}.md").parent.mkdir(parents=True, exist_ok=True)
    (T / f"brain/{k}.md").write_text(f"---\ntitle: {k}\ndisplay-name: {s}\nagents:\n{front}  background:\n{back}---\n\n# {k}\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.service import messaging as _messaging
from stackshot.service import agents as _agents
from stackshot.service import update as _update_svc
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.core import readonly as _ro
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import migrations as migsvc
from stackshot.service import page_debt as pdebt_svc
from stackshot.service import fleet_events as fleetev
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import checks as checks_svc, proofs as proofs_svc, released as released_svc
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import owner_words as _owner_words
from stackshot.service import runner as runner_svc
from stackshot.web.tools import sessions as _wt_sessions
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
from stackshot.audit import hand_idle as HI, silence as SL
from stackshot.waits import stall as ST, handoff as HO
from stackshot.model import queued as Q, last_activity as LA
from stackshot.tools import next_report as NR
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the saves below: the pass is given its `now`, and the saves stamp from the server's own clock."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = fleetev.time = migsvc.time = pdebt_svc.time = handoff_svc.time = hcold_svc.time = checks_svc.time = proofs_svc.time = released_svc.time = _pane_recovery.time = _mover_steps.time = _owner_words.time = CLK
_cfg.CFG["audit"]["pattern_review"] = "off"
_cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every notice the server was asked to send: (items, recipient's id, text, tag)
def fake_tell(gid, owner, note, tag="wake", result=None): sent.append((gid, owner, note, tag)); return None
telling.tell_woken = fake_tell
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append(("message", to, text, "message")), "delivered to " + to)[1]
fleetev.inbox_flag_send = lambda *a, **k: sent.append(("flag", "", "", "flag"))
panes = {}; dead = {}                                              # a name -> its pane's registry status; a name -> why it has no pane
def fake_status(who, idx=None):
    st = panes.get(who, "")
    if st == "boom": raise OSError("registry unreadable")
    return (st, now0 - 3600) if st else ("", 0.0)
handoff_svc.handoff_status = fake_status
handoff_svc.handoff_pane = lambda who, idx=None: dead.get(who, "")
_fleet_sessions_registry._sessions_index = fleetev._sessions_index = pdebt_svc._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = proofs_svc._sessions_index = lambda: {}

def put(i, mover="home-peer", status="open", act=90, project="projects/alpha", last=None, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0. `last` = minutes ago (or (minutes, kind)) of its `last_activity` record, which the queue rule reads."""
    base = {"owner": U["home-main"], "project": project, "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    if last is not None:
        mins, kind = last if isinstance(last, tuple) else (last, "state_change")
        base["last_activity"] = {"at": now0 - mins * MIN, "kind": kind, "what": "something happened"}
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "written_at": at, "written_by": mover, "metadata": base}))
def ho(mover, mins, sender="home-stew", **extra):
    """The metadata of an untaken hand-off to `mover`, delivered `mins` minutes before now0 (`extra` sets or clears fields of the record)."""
    r = HO.new_record(mover, "", sender, now0 - mins * MIN); r["delivered_at"] = now0 - mins * MIN; r.update(extra)
    return {HO.KEY: {k: v for k, v in r.items() if v is not None or k in ("taken_at",)}}
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def mover_of(i): return mt(i).get("mover")      # the stored mover (a waiting item has no derived one)
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    sent.clear(); panes.clear(); dead.clear(); (T / "store/anchors.json").write_text("{}")
    server._BALANCE_LOGGED.clear(); _cfg.CFG["audit"].pop("balance_minutes", None); off()      # the baseline of every section is the switch off until it says `on()`
def on(): _cfg.CFG["audit"]["balance"] = True
def off(): _cfg.CFG["audit"]["balance"] = False
def tick(at=None, **kw):
    """One pass of the balancer at `at` (default now0), the server's clock set to it → the ids moved."""
    at = now0 if at is None else at
    CLK.t = at
    try: return server._balance_tick(now=at, **kw)
    finally: CLK.t = None
def to_main(): return [x for x in sent if x[1] == U["home-main"]]
def to_builder(name): return [x for x in sent if x[1] == U[name]]
def told(tag, name=None): return [x for x in sent if x[3] == tag and (name is None or x[1] == U[name])]
def history(i): return [e["text"] for e in ST.log_of(mt(i))]
def shown(i): return _gh.shown(f"a{i}")
def disregard(i, to): return f"Disregard: {shown(i)} is now with {to}. Drop it, stop any work or subagent on it, and write nothing to it. No reply is owed."
def busy_on(name, n, first=50):
    """`n` open items on builder `name`, each with activity a few minutes ago: the builder's load, none of them waited long enough to move."""
    for k in range(n): put(first + k, mover=name, act=3, last=3)
def anchor_on(i, added=60):
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://example.invalid/org/repo/pull/7", "items": [f"a{i}"], "added": now0 - added * MIN}]}))
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()

def mutated(patches, probe):
    """Run `probe` with each (object, name, value) of `patches` replaced, restoring them after. → the probe's answer."""
    old = [(o, n, getattr(o, n)) for o, n, _v in patches]
    for o, n, v in patches: setattr(o, n, v)
    try: return probe()
    finally:
        for o, n, v in old: setattr(o, n, v)
def rule(name, probe, patches):
    """The rule holds as the code is, and fails once `patches` revert it (a check that cannot fail proves nothing)."""
    for o_, n_, _v in patches: getattr(o_, n_)       # a patch of a name that is gone must fail here, not read as a reverted rule
    try: held = probe()
    except Exception as e_: held = f"raised {e_!r}"
    check(name, held is True, held)
    try: broke = mutated(patches, probe)
    except Exception as e_: broke = f"raised {e_!r}"
    check(name + " [reverted: the check fails]", broke is not True, broke)

# ================================================================ 1. on by default
EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
wipe(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
check("1 the example config documents `balance = true` and `balance_minutes = 10` in [audit]",
      re.search(r"(?m)^balance = true\b", EXAMPLE) is not None and re.search(r"(?m)^balance_minutes = 10\b", EXAMPLE) is not None)
_cfg.CFG["audit"].pop("balance", None)
check("1 …and with the key absent the code's default is on", HI.balance_enabled() is True)
for label, val in (("false", False), ("the string true", "true"), ("1", 1), ("yes", "yes")):
    _cfg.CFG["audit"]["balance"] = val
    check(f"1 {label} leaves it off (only a TOML true leaves it on)", HI.balance_enabled() is False and tick() == [] and mover_of(1) == "home-peer")
on()
check("1 a TOML true switches it on", HI.balance_enabled() is True)
ro = _ro.is_read_only
_ro.is_read_only = lambda: True
check("1 a read-only standby copy moves nothing", tick() == [] and mover_of(1) == "home-peer" and sent == [])
_ro.is_read_only = ro
def minutes_of(v):
    _cfg.CFG["audit"]["balance_minutes"] = v
    try: return HI.balance_minutes()
    finally: _cfg.CFG["audit"].pop("balance_minutes", None)
check("1 balance_minutes is 10 when unset, a number is taken, and it never goes under 1", HI.balance_minutes() == 10.0 and minutes_of(25) == 25.0 and minutes_of(2.5) == 2.5 and minutes_of(0) == 1.0 and minutes_of(-3) == 1.0 and minutes_of(0.2) == 1.0,
      [minutes_of(v) for v in (25, 0, -3)])
check("1 …and a value that is no number (text, a boolean, nan, infinity) reads as 10", all(minutes_of(v) == 10.0 for v in ("5", True, float("nan"), float("inf"), None, [3])))
def probe_off():
    wipe(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("1 off by default does nothing", probe_off, [(HI, "balance_enabled", lambda: True)])
def probe_audit_off():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    _cfg.CFG["audit"]["mode"] = "agent"
    try: return tick() == [] and mover_of(1) == "home-peer"
    finally: _cfg.CFG["audit"]["mode"] = "script"
check("1 it stands still while the audit runs in agent mode", probe_audit_off() is True)

# ================================================================ 2. an untaken hand-off moves to the least-loaded builder
wipe(); on(); put(1, act=15, **ho("home-peer", 12)); busy_on("team-back", 2); busy_on("other-back", 1, first=60); panes["team-aux"] = "idle"
before = rd(1)
with _Err() as err: got = tick()
m = mt(1)
check("2 an untaken hand-off that waited 12 minutes moves, and the pass says so", got == ["a1"], got)
check("2 it goes to the builder with the fewest open items (team-aux has none, team-back two, other-back one): the stored mover, `needs` and the hand-off record all name it", mover_of(1) == "team-aux" and m["needs"][0] == "team-aux"
      and HO.record_of(rd(1))["to"] == "team-aux" and HO.record_of(rd(1))["from"] == "stackshot" and HO.record_of(rd(1))["tried"] == ["home-peer"], (mover_of(1), m.get("needs"), HO.record_of(rd(1))))
h1 = history(1)
check("2 ONE History line says why and names the mover it left", h1 == ["handed to team-aux: not started in 10 min, so it goes to the builder with the fewest open items (it was with home-peer)"], h1)
check("2 the new builder is told (the hand-off notice) and told once", len(to_builder("team-aux")) == 1 and to_builder("team-aux")[0][3] == "handoff" and "not started in 10 min" in to_builder("team-aux")[0][2], to_builder("team-aux"))
check("2 the mover it left is told ONCE, to disregard the item, in the wording of the notice", [x[2] for x in told("balance")] == [disregard(1, "team-aux")] and told("balance")[0][1] == U["home-peer"], told("balance"))
check("2 …through the notice path (tell_woken), not the message tool: nothing was sent as a message and the former mover is not back in `needs`", not told("message") and "home-peer" not in [str(x) for x in m["needs"]] and "home-peer" not in str(m.get("mover")), (sent, m.get("needs")))
check("2 -main is told nothing of a move, and nobody else is: the new builder and the former mover only", to_main() == [] and sorted(x[1] for x in sent) == sorted([U["team-aux"], U["home-peer"]]), sent)
check("2 the record of the balancer is its own key, {at, from, to, count}, written in the save of the move, and `hand_idle` is not touched", m["balance"] == {"at": now0, "from": "home-peer", "to": "team-aux", "count": 1} and "hand_idle" not in m, m.get("balance"))
check("2 the owner is not put in the item: next and state as they were", m.get("next") == before["metadata"]["next"] and m.get("state") == "doing" and not any("Oliver" in str(v) for k, v in m.items() if k in ("needs", "next", "mover")), m)
check("2 the activity clock is as it was: the move is the server's own bookkeeping", all(rd(1)[k] == before[k] for k in ("activity", "written_by", "written_at")))
check("2 a second pass a minute later finds a fresh untaken hand-off and does nothing more", tick(now0 + MIN) == [] and len(told("balance")) == 1 and len(to_builder("team-aux")) == 1 and history(1) == h1)
check("2 the server logs it on stderr", "moved from home-peer to team-aux" in err.text, err.text)
check("2 the minute set carries a tag the front gate knows for that notice", telling.FRONT_TAG_KIND.get("balance") == "exempt", telling.FRONT_TAG_KIND.get("balance"))
def base2():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); busy_on("team-back", 2); busy_on("other-back", 1, first=60); panes["team-aux"] = "idle"
def probe_moved():
    base2()
    return tick() == ["a1"] and mover_of(1) == "team-aux"
rule("2 an untaken hand-off is moved", probe_moved, [(HI, "balance_all", lambda *a, **k: [])])
def probe_record():
    base2(); tick()
    return mt(1).get("balance", {}).get("count") == 1
rule("2 the balance record is written with the move", probe_record, [(HI, "mark_balanced", lambda meta, now, frm, to: None)])
def probe_history2():
    base2(); tick()
    return len(history(1)) == 1 and "fewest open items" in history(1)[0]
rule("2 the History line says why", probe_history2, [(HI, "balance_why", lambda kind, minutes: "x")])
def probe_disregard():
    base2(); tick()
    return len(told("balance", "home-peer")) == 1 and len(told("balance")) == 1
rule("2 the former mover is told, once", probe_disregard, [(server, "_session_id", lambda who: "")])

# ---- the wait
def waited(mins, **kw):
    wipe(); on(); put(1, act=15, **ho("home-peer", mins, **kw)); panes["team-aux"] = "idle"
    return tick() == ["a1"]
check("3 a hand-off delivered 9 minutes ago is not moved yet, one delivered 10 minutes ago is", waited(9) is False and waited(10) is True)
def probe_wait():
    return waited(5) is False and mover_of(1) == "home-peer"
rule("3 the clock counts from the delivery: 5 minutes is too soon", probe_wait, [(HI, "balance_minutes", lambda: 0.01)])
def probe_custom():
    wipe(); on(); _cfg.CFG["audit"]["balance_minutes"] = 3; put(1, act=15, **ho("home-peer", 5)); panes["team-aux"] = "idle"
    try: return tick() == ["a1"] and "not started in 3 min" in history(1)[0]
    finally: _cfg.CFG["audit"].pop("balance_minutes", None)
rule("3 `balance_minutes` is read at use: with 3, a hand-off 5 minutes old moves and the History line says 3 min", probe_custom, [(HI, "balance_minutes", lambda: 10.0)])
check("3 a hand-off never delivered counts from the time it was made", waited(12, delivered_at=None) is True and waited(8, delivered_at=None) is False)
check("3 …and a torn delivery time (text, a boolean) is no signal: the time it was made counts", waited(12, delivered_at="yesterday") is True and waited(12, delivered_at=True) is True)
def probe_written():
    wipe(); on(); put(1, act=2, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer"
rule("3 an item written to 2 minutes ago is not moved, whatever its hand-off says (silence.clock)", probe_written, [(SL, "clock", lambda item, mover="": 0.0)])


# ================================================================ 4. a queued item moves, the item in hand never does
def queue_setup(n_queued=1, queued_meta=None, hand_last=3, queued_last=30, builders_idle=("team-aux", "team-back", "other-back")):
    """Mover home-peer has the item in hand (a1: activity 3 minutes ago) and `n_queued` quiet ones (a2…: 30 minutes ago, no hand-off record)."""
    wipe(); on()
    put(1, act=hand_last, last=hand_last)
    for k in range(n_queued): put(2 + k, act=queued_last, last=queued_last, **(queued_meta or {}))
    for n in builders_idle: panes[n] = "idle"
check("4 `[model] queued_behind` is off in this suite: the balancer reads the queue itself", Q.enabled() is False)
queue_setup()
before_q = rd(2)
check("4 a queued item (its mover works on another, a1) is queued by the rule read over the balancer's window", HI.balance_queue(NR.load_all(None), now0, 600.0, None) == {"a2": "a1"})
got = tick()
check("4 …it moves to the least-loaded builder (all have none: the project's builder, first in order) and the item in hand stays with its mover", got == ["a2"] and mover_of(2) == "team-back" and mover_of(1) == "home-peer", (got, mover_of(1), mover_of(2)))
check("4 …with a History line naming the queue, the builder told, the mover it left told once to disregard it, and a balance record", history(2) == ["handed to team-back: queued behind another item for 10 min, so it goes to the builder with the fewest open items (it was with home-peer)"]
      and len(to_builder("team-back")) == 1 and [x[2] for x in told("balance")] == [disregard(2, "team-back")] and mt(2)["balance"]["count"] == 1 and history(1) == [], (history(2), sent))
check("4 …and a later pass moves nothing more: one item is left on the mover, in hand", tick(now0 + MIN) == [] and mover_of(1) == "home-peer")
def probe_queue_window():
    queue_setup(queued_last=8)
    return tick() == [] and mover_of(2) == "home-peer"
check("4 an item with activity 8 minutes ago is not yet queued (the balancer's window is balance_minutes, 10)", probe_queue_window() is True)
def probe_queue_read():
    queue_setup()
    return tick() == ["a2"]
rule("4 a queued item moves", probe_queue_read, [(Q, "queue", lambda cands, now, is_front=None, window=0: {})])
def probe_window_arg():
    queue_setup(queued_last=30)
    return HI.balance_queue(NR.load_all(None), now0, 600.0, None) == {"a2": "a1"} and Q.queue([("a1", "m", "p", now0 - 300), ("a2", "m", "p", now0 - 400)], now0, None, 600.0) == {} and Q.queue([("a1", "m", "p", now0 - 300), ("a2", "m", "p", now0 - 400)], now0) == {}
check("4 queue() takes a window: the default (an hour) is the board's reading and is unchanged", probe_window_arg() is True)
check("4 …a window of 10 minutes queues an item idle for 11 and leaves the board's hour alone", Q.queue([("a1", "m", "p", now0 - 60), ("a2", "m", "p", now0 - 700)], now0, None, 600.0) == {"a2": "a1"} and Q.queue([("a1", "m", "p", now0 - 60), ("a2", "m", "p", now0 - 700)], now0) == {})
def probe_all_idle():
    wipe(); on(); put(1, act=30, last=30); put(2, act=40, last=40); panes["team-aux"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer" and mover_of(2) == "home-peer"
check("4 a mover whose newest item is idle too is working on none: nothing is queued, nothing moves", probe_all_idle() is True)
def probe_hand_never():
    wipe(); on(); put(1, act=30, last=3); put(2, act=30, last=30); panes["team-aux"] = "idle"      # a1: its mover's activity record is fresh, though nothing has moved its clocks for 30 minutes
    got = tick()
    return got == ["a2"] and mover_of(1) == "home-peer"
rule("4 the item in hand never moves, whatever the clock says", probe_hand_never, [(Q, "queue", lambda cands, now, is_front=None, window=0: {c[0]: "z" for c in cands})])

# ================================================================ 5. an item its mover started is never taken
def started_case(name, queued_meta=None, last=30, extra=None, untaken=False):
    """One item that would move but for the start: as a queued one (a2 behind a1) or, with `untaken`, as a hand-off 12 minutes old. → whether it stayed with its mover, nobody told."""
    def probe():
        if untaken:
            wipe(); on(); put(1, act=15, **ho("home-peer", 12), **(queued_meta or {})); panes["team-aux"] = "idle"; item = 1
        else:
            queue_setup(queued_meta=queued_meta, queued_last=last); item = 2
        if extra: extra(item)
        return tick() == [] and mover_of(item) == "home-peer" and sent == []
    return probe
STEP = lambda state, ts, text="home-peer: do the thing": [{"text": text, "status": "open", "by": "", "at": 0, "tag": {"text": "coding", "state": state, "ts": ts}}]
cases5 = {
    "its hand-off was taken": dict(queued_meta=ho("home-peer", 30, taken_at=now0 - 25 * MIN)),
    "a step that opens with its name has a status in progress (long ago: no subagent running)": dict(queued_meta=dict(steps=STEP("in progress", now0 - 95 * MIN))),
    "a step that opens with its name has a status done": dict(queued_meta=dict(steps=STEP("done", now0 - 95 * MIN))),
    "a step that opens with its name is marked done": dict(queued_meta=dict(steps=[{"text": "home-peer: first part", "status": "done", "by": "home-peer", "at": now0 - 20 * MIN}])),
    "a subagent is running on it (a status in progress, set 5 minutes ago, on another session's step)": dict(queued_meta=dict(next="home-peer: do the thing\nteam-aux: review it", steps=[{"text": "home-peer: do the thing", "status": "open", "by": "", "at": 0}, *STEP("in progress", now0 - 5 * MIN, "team-aux: review it")])),
    "an anchor is scoped to it": dict(extra=lambda i: anchor_on(i)),
    "a pull request event is its last activity": dict(last=(30, "ci_result")),
}
for name, kw in cases5.items():
    last = kw.get("last", 30); pr = isinstance(last, tuple)
    def mk(kw=kw, last=last):
        def probe():
            queue_setup(queued_meta=kw.get("queued_meta"), queued_last=30)
            if isinstance(last, tuple): put(2, act=30, last=last)
            if kw.get("extra"): kw["extra"](2)
            return tick() == [] and mover_of(2) == "home-peer" and sent == []
        return probe
    rule(f"5 a queued item is left with its mover when {name}", mk(), [(HI, "started_reason", lambda *a, **k: "")])
rule("5 an untaken hand-off is left with its mover when a subagent is running on it", started_case("x", queued_meta=dict(next="home-peer: do the thing\nteam-aux: review it", steps=[{"text": "home-peer: do the thing", "status": "open", "by": "", "at": 0}, *STEP("in progress", now0 - 5 * MIN, "team-aux: review it")]), untaken=True), [(HI, "started_reason", lambda *a, **k: "")])
rule("5 …or an anchor is scoped to it", started_case("x", untaken=True, extra=lambda i: anchor_on(i)), [(HI, "started_reason", lambda *a, **k: "")])
rule("5 …or a pull request is its last activity", started_case("x", untaken=True, queued_meta=dict(last_activity={"at": now0 - 20 * MIN, "kind": "review", "what": "review on a pull request"})), [(HI, "started_reason", lambda *a, **k: "")])
def probe_unstarted_control():
    queue_setup(queued_meta=dict(steps=STEP("defined", now0 - 95 * MIN)))
    return tick() == ["a2"]
check("5 control: a step only defined (not in progress, not done) is no start: the queued item moves", probe_unstarted_control() is True)
def probe_other_step():
    queue_setup(queued_meta=dict(next="home-peer: do the thing\nteam-aux: review it", steps=[{"text": "home-peer: do the thing", "status": "open", "by": "", "at": 0}, *STEP("in progress", now0 - 100 * MIN, "team-aux: review it")]))
    return tick() == ["a2"]
check("5 control: another session's stale status (over 90 minutes) is no subagent and no start of the mover's", probe_other_step() is True)
def probe_stale_view():
    queue_setup(); view = NR.load_all(None)
    d = rd(2); d["metadata"]["steps"] = STEP("in progress", now0 - 95 * MIN); (T / "store/a/2.json").write_text(json.dumps(d))      # its mover started it after the pass read the store
    return tick(items=view) == [] and mover_of(2) == "home-peer" and sent == []
rule("5 an item its mover started after the pass read it is read again under the lock and stays", probe_stale_view,
     [(HI, "balance_due", lambda items, gid, now, minutes, front, behind, same, anchored=None, builder=None: {"mover": "home-peer", "project": "projects/alpha", "kind": "queued", "tried": [], "told_none": False, "capped": False})])
def probe_anchors_unreadable():
    queue_setup()
    real = _anc.load
    def boom(*a, **k): raise OSError("anchors gone")
    _anc.load = boom
    try: return tick() == [] and mover_of(2) == "home-peer"
    finally: _anc.load = real
check("5 an anchor store that cannot be read counts as an anchor: nothing moves on a guess", probe_anchors_unreadable() is True)


# ================================================================ 6. the load, the ties, the +1 rule, two items in one pass, the cap
def untaken_with_load(from_extra=0, loads=None, idle=(), busy=(), item_mover="home-peer"):
    """a1 is an untaken hand-off to `item_mover` (waited 12 minutes); the mover has `from_extra` other open items; `loads` = {builder: open items}."""
    wipe(); on(); put(1, mover=item_mover, act=15, **ho(item_mover, 12))
    busy_on(item_mover, from_extra, first=40)
    for k, (n, c) in enumerate((loads or {}).items()): busy_on(n, c, first=60 + 10 * k)
    for n in idle: panes[n] = "idle"
    for n in busy: panes[n] = "busy"
    return tick()
def probe_tie():
    got = untaken_with_load(idle=("team-back", "team-aux", "other-back"))
    return got == ["a1"] and mover_of(1) == "team-back"
rule("6 equal loads: the first candidate (the project's builder) takes it", probe_tie, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": c[-1])])
def probe_tie_idle():
    got = untaken_with_load(idle=("team-aux", "other-back"), busy=("team-back",))
    return got == ["a1"] and mover_of(1) == "team-aux"
rule("6 equal loads: a pane in a turn only loses the tie, an idle pane first", probe_tie_idle, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": c[0])])
def probe_busy_lower():
    got = untaken_with_load(loads={"team-aux": 1, "other-back": 1}, busy=("team-back",), idle=("team-aux", "other-back"), from_extra=1)
    return got == ["a1"] and mover_of(1) == "team-back"
rule("6 a busy pane is no exclusion: the builder with the fewest open items wins even in a turn", probe_busy_lower, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": next((x for x in c if status(x) != "busy"), ""))])
def probe_merge():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); busy_on("home-peer", 2, first=45); busy_on("team-aux", 1, first=40); put(60, mover=U["team-back"], act=3, last=3); put(61, mover="team-back", act=3, last=3)
    for n in ("team-back", "team-aux", "other-back"): panes[n] = "idle"
    busy_on("other-back", 3, first=70)
    got = tick()
    return got == ["a1"] and mover_of(1) == "team-aux"
rule("6 a builder named by its id on one item and by its name on another is ONE builder with two open items (team-aux has one, so it wins)", probe_merge, [(HI, "load_of", lambda load, who, same: load.get(who, 0))])
def probe_strict():
    return untaken_with_load(from_extra=0, loads={"team-back": 1, "team-aux": 1, "other-back": 1}, idle=("team-back", "team-aux", "other-back")) == [] and mover_of(1) == "home-peer"
rule("6 an untaken hand-off stays when no builder has strictly fewer open items than its mover (one each)", probe_strict, [(HI, "balance_ok", lambda kind, to, frm: True)])
check("6 …and goes when the builder has none (one item on its mover, none on the builder)", untaken_with_load(idle=("team-aux",)) == ["a1"])
check("6 …and when the mover has three and the builder one (1 + 1 < 3)", untaken_with_load(from_extra=2, loads={"team-back": 1, "team-aux": 1, "other-back": 1}, idle=("team-aux",)) == ["a1"])
def probe_swap():
    return untaken_with_load(from_extra=1, loads={"team-back": 1, "team-aux": 1, "other-back": 1}, idle=("team-aux",)) == [] and mover_of(1) == "home-peer" and sent == []
rule("6 …but not when it would only swap them: two on the mover and one on the builder stays (to == 0 or to + 1 < from), and nobody is told", probe_swap, [(HI, "balance_ok", lambda kind, to, frm: to < frm)])
def probe_plus1():
    queue_setup(n_queued=1)
    busy_on("team-back", 1, first=60); busy_on("team-aux", 1, first=70); busy_on("other-back", 1, first=80)
    return tick() == [] and mover_of(2) == "home-peer"
rule("6 a queued item needs to + 1 < from: with two on its mover and one on every builder it stays", probe_plus1, [(HI, "balance_ok", lambda kind, to, frm: to < frm)])
def probe_plus1_go():
    queue_setup(n_queued=1)
    busy_on("team-back", 1, first=60); busy_on("other-back", 1, first=80)
    return tick() == ["a2"] and mover_of(2) == "team-aux"
check("6 …and goes to a builder with none (0 + 1 < 2)", probe_plus1_go() is True)
def probe_plus1_three():
    queue_setup(n_queued=2)
    busy_on("team-back", 1, first=60); busy_on("team-aux", 1, first=70); busy_on("other-back", 1, first=80)
    return tick() == ["a2"] and mover_of(2) == "team-back" and mover_of(3) == "home-peer"
check("6 …three on its mover and one on each builder: the first queued item goes (1 + 1 < 3), the next stays (the counts moved: 2 on the mover, 2 on team-back)", probe_plus1_three() is True)
def probe_two_in_one():
    queue_setup(n_queued=2)
    got = tick()
    return got == ["a2", "a3"] and mover_of(2) == "team-back" and mover_of(3) == "team-aux" and mover_of(1) == "home-peer"
rule("6 two queued items of one mover in one pass go to two builders (the counts follow each move: the first builder now has an item)", probe_two_in_one, [(HI, "shift", lambda load, frm, to, same: None)])
def probe_cap():
    wipe(); on()
    for i in range(1, 6): put(i, act=15, **ho("home-peer", 12))
    for n in ("team-back", "team-aux", "other-back", "lone-back"): panes[n] = "idle"
    real = server._balance_builders; server._balance_builders = lambda project: ["team-back", "team-aux", "other-back", "lone-back"]
    try: got = tick()
    finally: server._balance_builders = real
    return len(got) == 3 and len({mover_of(i) for i in range(1, 6)} - {"home-peer"}) == 3
rule("6 at most three items are moved in one pass", probe_cap, [(HI, "BALANCE_MAX_PER_TICK", 99)])
def probe_no_front_target():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-back"] = "idle"
    real = server._balance_builders; server._balance_builders = lambda project: ["home-main", "team-back"]
    try: got = tick()
    finally: server._balance_builders = real
    return got == ["a1"] and mover_of(1) == "team-back"
rule("6 a front agent is never the target, whatever its load (home-main has none)", probe_no_front_target, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": c[0])])
def probe_front_mover():
    wipe(); on(); put(1, mover="home-main", act=15, **ho("home-main", 12)); panes["team-aux"] = "idle"
    real = server._balance_builder_names; server._balance_builder_names = lambda: [*real(), "home-main"]      # so only the front test stands between the item and a move
    try: return tick() == [] and mover_of(1) == "home-main" and sent == []
    finally: server._balance_builder_names = real
rule("6 an item a front agent moves is never moved", probe_front_mover, [(telling, "front_keeper", lambda w, p="", strict=False: (False, ""))])
def probe_dead_target():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"; panes["team-back"] = "idle"; dead["team-aux"] = "a retired session, its pane gone"
    return tick() == ["a1"] and mover_of(1) == "team-back"
rule("6 a builder known to have no pane is no target", probe_dead_target, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": c[1])])
def probe_own():
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 12)); panes["team-back"] = "idle"; panes["team-aux"] = "idle"
    return tick() == ["a1"] and mover_of(1) == "team-aux"
rule("6 an item is never moved to its own mover", probe_own, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": next((x for x in c if x), "")), (HI, "balance_ok", lambda kind, to, frm: True)])
def probe_unread_pane():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "boom"; panes["team-back"] = "idle"
    return tick() == ["a1"] and mover_of(1) == "team-back"
check("6 a builder whose pane cannot be read is left out, and the pass goes on", probe_unread_pane() is True)
# ================================================================ 7. no target: the item stays, one History line, -main told once per 24 hours
def none_setup():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12))
    for n in ("team-back", "team-aux", "other-back"): dead[n] = "a retired session, its pane gone"
def probe_none():
    none_setup(); got = tick()
    return got == [] and mover_of(1) == "home-peer" and len(to_main()) == 1 and len(sent) == 1 and not told("balance") and "no live builder could take it" in to_main()[0][2] and "stays with home-peer" in to_main()[0][2]
rule("7 with NO live builder to take it the item stays, nobody is told to disregard it, and -main is told, and only -main", probe_none, [(HI, "balance_ok", lambda kind, to, frm: True), (HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": "team-aux")])
none_setup(); tick(); m7 = to_main()[0][2]
check("7 the message to -main is the notice path's (the front agent's mark on line 1, tag stall), says what stayed where, and asks nothing", m7.startswith(_wt_text._FOR_OWNER + "\n") and to_main()[0][3] == "stall" and "Nothing is asked of you and no reply is owed" in m7 and "?" not in m7.split("\n", 1)[1], m7)
h7 = history(1)
check("7 one History line says so; the item keeps its mover, its hand-off and the balance record carries only the day's note", len(h7) == 1 and h7[0].startswith("not started or queued for 10 min, but no live builder could take it, so it stays with home-peer: home-main was told")
      and mt(1)["balance"] == {"none_at": now0} and HO.record_of(rd(1))["to"] == "home-peer", (h7, mt(1).get("balance")))
def probe_once_per_day():
    none_setup(); tick(); n1 = len(to_main())
    tick(now0 + 10 * MIN); tick(now0 + 8 * H); tick(now0 + 23 * H)
    return n1 == 1 and len(to_main()) == 1 and len(history(1)) == 1
rule("7 -main is told once per item per 24 hours, not every minute", probe_once_per_day, [(HI, "balance_none_told_recently", lambda meta, now: False)])
def probe_next_day():
    none_setup(); tick(); tick(now0 + 25 * H)
    return len(to_main()) == 2 and len(history(1)) == 2
check("7 …and again after 24 hours while it stays put", probe_next_day() is True)
def probe_not_better():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); [busy_on(n, 1, first=60 + 10 * k) for k, n in enumerate(("team-back", "team-aux", "other-back"))]
    for n in ("team-back", "team-aux", "other-back"): panes[n] = "idle"
    return tick() == [] and sent == [] and history(1) == [] and "balance" not in mt(1) and mover_of(1) == "home-peer"
rule("7 a builder that is no improvement (as many open items as its mover) is SILENT: the item stays, no History line, nobody told, nothing written", probe_not_better, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": "")])
def probe_dead_then_back():
    none_setup(); first = tick(); n1 = len(to_main())
    for n in ("team-back", "team-aux", "other-back"): dead.pop(n, None); panes[n] = "idle"
    sent.clear(); got = tick(now0 + 5 * MIN)
    return first == [] and n1 == 1 and got == ["a1"] and mover_of(1) == "team-back" and "none_at" not in mt(1)["balance"] and mt(1)["balance"]["count"] == 1 and to_main() == []
orig_due = HI.balance_due
def old_due(*a, **k):      # the old behaviour: an item with the day's no-builder note is left alone
    r = orig_due(*a, **k)
    return None if r is not None and r["told_none"] else r
rule("7 the note blocks nothing: builders dead on the first pass (-main told once), idle five minutes later, the item moves at once and the move ends the note", probe_dead_then_back, [(HI, "balance_due", old_due)])
def probe_single_builder():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12))
    real = server._balance_builders; server._balance_builders = lambda project: ["home-peer"]
    try:
        with _Err() as e: got = tick()
    finally: server._balance_builders = real
    return got == [] and sent == [] and history(1) == [] and "balance" not in mt(1) and "no other builder to move it to" in e.text
rule("7 a mover that is the only builder speaks to nobody: no History line, no message, a log line only", probe_single_builder, [(HI, "balance_others", lambda *a, **k: ["x"])])
def probe_only_tried():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12, tried=["team-back", "team-aux"]))
    real = server._balance_builders; server._balance_builders = lambda project: ["home-peer", "team-back", "team-aux"]
    try: got = tick()
    finally: server._balance_builders = real
    return got == [] and sent == [] and history(1) == []
rule("7 …nor when every other builder is one it already had (`tried`): nobody is dead, there is nobody to tell", probe_only_tried, [(HI, "balance_others", lambda *a, **k: ["x"])])
def probe_batched():
    none_setup(); put(2, act=15, **ho("home-peer", 12)); put(3, act=15, **ho("home-peer", 12)); tick()
    return len(to_main()) == 1 and to_main()[0][2].count("\n- ") == 3
check("7 several items that stay are one message to -main, one line each", probe_batched() is True)
def probe_no_main():
    none_setup(); real = _agents._main_agent; _agents._main_agent = lambda p: ""
    try: tick()
    finally: _agents._main_agent = real
    return sent == [] and len(history(1)) == 1 and "the project has no -main agent to tell" in history(1)[0]
check("7 a project with no -main agent gets the History line alone", probe_no_main() is True)
def probe_owner_main():
    none_setup(); real = _agents._main_agent; _agents._main_agent = lambda p: "Oliver"
    try: tick()
    finally: _agents._main_agent = real
    return not any(x[1] in ("Oliver", _web_page_debts._session_id("Oliver")) for x in sent)
rule("7 a page that names the owner as -main tells him nothing", probe_owner_main, [(_model, "is_owner", lambda who: False)])

# ================================================================ 8. no flapping: 24 hours, the lifetime cap, `tried`
def reopen_untaken(i, at, mins=30):
    """The item's hand-off, made by the last move, is untaken and `mins` minutes old at `at`: only the limits are left to hold it."""
    d = rd(i); r = d["metadata"][HO.KEY]; r["at"] = at - mins * MIN; r["delivered_at"] = at - mins * MIN; d["activity"] = d["state_updated"] = at - 40 * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def probe_day():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"; panes["other-back"] = "idle"; panes["team-back"] = "idle"; busy_on("team-back", 1, first=60)
    first = tick(); reopen_untaken(1, now0 + 10 * H); (T / "store/a/60.json").unlink()      # team-back is empty by then: only the 24-hour limit keeps the item with team-aux
    second = tick(now0 + 10 * H)
    return first == ["a1"] and second == [] and mover_of(1) == "team-aux" and mt(1)["balance"]["count"] == 1
rule("8 one balancer move per item per 24 hours", probe_day, [(HI, "balanced_recently", lambda meta, now: False)])
def probe_again():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); [panes.__setitem__(n, "idle") for n in ("team-back", "team-aux", "other-back")]
    tick(); reopen_untaken(1, now0 + 25 * H)
    second = tick(now0 + 25 * H)
    return second == ["a1"] and mover_of(1) == "team-aux" and mt(1)["balance"] == {"at": now0 + 25 * H, "from": "team-back", "to": "team-aux", "count": 2} and HO.record_of(rd(1))["tried"] == ["home-peer", "team-back"]
check("8 …and again after 24 hours, to a builder that had not had it (`tried` carries the way walked), the count 2", probe_again() is True)
def probe_lifetime():
    wipe(); on(); put(1, act=15, balance={"at": now0 - 30 * H, "from": "a", "to": "b", "count": 2}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    got = tick()
    return got == [] and mover_of(1) == "home-peer" and len(to_main()) == 1 and "2 times" in to_main()[0][2] and mt(1)["balance"]["capped_at"] == now0 and mt(1)["balance"]["count"] == 2 \
        and any("already moved 2 times" in h for h in history(1)) and not told("balance")
rule("8 two moves in all: an item at the cap is left to the ladders, one History line, -main told once", probe_lifetime, [(HI, "BALANCE_LIFETIME", 99)])
def probe_lifetime_once():
    wipe(); on(); put(1, act=15, balance={"at": now0 - 30 * H, "from": "a", "to": "b", "count": 2}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    tick(); n = len(to_main()); tick(now0 + 10 * MIN); tick(now0 + 30 * H); tick(now0 + 90 * H)
    return n == 1 and len(to_main()) == 1 and mover_of(1) == "home-peer" and len(history(1)) == 1
rule("8 …and told once, not at every pass or every day", probe_lifetime_once, [(HI, "balance_capped_told", lambda meta: False)])
def probe_tried():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12, tried=["team-aux", "other-back"])); busy_on("team-back", 1, first=60); [panes.__setitem__(n, "idle") for n in ("team-back", "team-aux", "other-back")]
    return tick() == [] and mover_of(1) == "home-peer"
rule("8 a builder in the hand-off record's `tried` is never the target, with no load at all", probe_tried, [(HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": c[1]), (HI, "balance_ok", lambda kind, to, frm: True)])
def probe_hand_idle_recent():
    wipe(); on(); put(1, act=15, hand_idle={"handed_at": now0 - H, "from": "x", "to": "home-peer"}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("8 an item the idle hand-over moved in the last 24 hours is not moved by the balancer (the two never both move one item inside a day)", probe_hand_idle_recent, [(HI, "handed_recently", lambda meta, now: False)])
def probe_hand_idle_apart():
    wipe(); on(); put(1, act=15, hand_idle={"handed_at": now0 - 30 * H, "from": "x", "to": "home-peer"}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    got = tick()
    return got == ["a1"] and mt(1)["hand_idle"] == {"handed_at": now0 - 30 * H, "from": "x", "to": "home-peer"} and mt(1)["balance"]["count"] == 1
check("8 …after 24 hours it moves it, and the idle hand-over's record is a separate key the balancer neither reads nor replaces", probe_hand_idle_apart() is True)


# ================================================================ 9. the notice to the mover it left
def probe_two_of_one():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); put(2, act=15, **ho("home-peer", 12)); [panes.__setitem__(n, "idle") for n in ("team-back", "team-aux", "other-back")]
    got = tick()
    msgs = told("balance")
    return got == ["a1", "a2"] and len(msgs) == 1 and msgs[0][1] == U["home-peer"] and msgs[0][2] == (
        f"Disregard: 2 items are now with other sessions:\n- {shown(1)} is now with team-back\n- {shown(2)} is now with team-aux\nDrop them, stop any work or subagent on them, and write nothing to them. No reply is owed.")
rule("9 two items one mover left in one pass are ONE notice, one line each", probe_two_of_one, [(HI, "shift", lambda load, frm, to, same: None), (HI, "BALANCE_MAX_PER_TICK", 99), (HI, "pick_least", lambda c, load, status, dead, same, frm="", tried=(), front=None, project="": "team-back")])
def probe_only_moved():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); put(2, act=15, **ho("home-peer", 3)); [panes.__setitem__(n, "idle") for n in ("team-back", "team-aux", "other-back")]      # a2 has not waited
    got = tick()
    return got == ["a1"] and [x[2] for x in told("balance")] == [disregard(1, "team-back")]
rule("9 an item that stays is named to nobody: the notice carries only the ids this pass moved", probe_only_moved, [(HI, "BALANCE_MAX_PER_TICK", 0)])
_real_fk = telling.front_keeper
telling.front_keeper = lambda w, p="", strict=False: (True, "") if (not strict and w == "home-peer") else _real_fk(w, p, strict)      # the gate's own test says the former mover is front; the pass's strict one does not
def probe_front_never():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    got = tick()
    return got == ["a1"] and told("balance") == []
rule("9 a front agent is never sent the notice unmarked (the pass checks before it sends)", probe_front_never, [(telling, "front_keeper", lambda w, p="", strict=False: (False, ""))])
telling.front_keeper = _real_fk

# ================================================================ 10. the tick: its place, and a failure that stops nothing
from stackshot.core import runner as R
import dataclasses
names10 = [t.name for t in runner_svc.ticks()]
check("10 the balancer is its own minute tick, right before the hand-off tick, in the hand-off group, standing still while the board is held", names10.index("balance_tick") == names10.index("handoff_tick") - 1
      and next(t for t in runner_svc.ticks() if t.name == "balance_tick").group == "handoff" and next(t for t in runner_svc.ticks() if t.name == "balance_tick").board is True, names10)
def probe_isolated():
    ran10 = []
    ticks10 = []
    for t in runner_svc.ticks():
        if t.name == "balance_tick": ticks10.append(dataclasses.replace(t, fn=lambda: (_ for _ in ()).throw(OSError("store gone"))))
        else: ticks10.append(dataclasses.replace(t, fn=lambda n=t.name: ran10.append(n)))
    clk = [1000.0]
    r = R.Runner(ticks10, holding=lambda: False, wake_wait=lambda: 60.0, clock=lambda: clk[0])
    r._wake_at = None; r.started = clk[0]      # no paced round yet: the first one is due and runs the whole table
    with _Err() as e10: r.run_round()
    st = {t["name"]: t for t in r.status()["ticks"]}
    return "handoff_tick" in ran10 and "answer_tick" in ran10 and "balance_tick" not in ran10 and "balance_tick failed: OSError: store gone" in e10.text and st["balance_tick"]["last_error"] == "OSError: store gone"
check("10 a balancer that raises is a logged error in the runner's status and stops the hand-off tick and the rest", probe_isolated() is True)
def probe_item_failure():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); put(2, act=15, **ho("home-peer", 12)); [panes.__setitem__(n, "idle") for n in ("team-back", "team-aux", "other-back")]
    real = handoff_svc.handoff_exec
    def exec_(steps, now, verify=True, env=None, recheck=None):
        if steps[0].gid == "a1": raise OSError("disk full")
        return real(steps, now, verify=verify, env=env, recheck=recheck)
    handoff_svc.handoff_exec = exec_
    try:
        with _Err() as e: got = tick()
    finally: handoff_svc.handoff_exec = real
    return got == ["a2"] and mover_of(1) == "home-peer" and "a1 sending after the move failed: OSError: disk full" in e.text and len(told("balance")) == 1
rule("10 one item's failure is a stderr line and stops the others", probe_item_failure, [(handoff_svc, "handoff_exec", lambda *a, **k: (_ for _ in ()).throw(OSError("every move fails")))])

# the order matters: a move at ten minutes comes before the hand-off tick's reminder to the mover
def reminders_to(name): return [x for x in sent if x[1] == U[name] and x[3] == "handoff"]
def probe_preempt():
    wipe(); put(1, mover="team-back", act=15, **ho("team-back", 10)); panes["team-aux"] = "idle"; panes["team-back"] = "idle"
    CLK.t = now0
    try: handoff_svc.handoff_tick(now=now0, only=["a1"])      # balancer off: the hand-off tick reminds team-back, a background agent that did not take it
    finally: CLK.t = None
    reminded = len(reminders_to("team-back"))
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 10)); panes["team-aux"] = "idle"; panes["team-back"] = "idle"
    tick()
    CLK.t = now0
    try: handoff_svc.handoff_tick(now=now0, only=["a1"])
    finally: CLK.t = None
    return reminded == 1 and mover_of(1) == "team-aux" and not reminders_to("team-back") and len(told("balance", "team-back")) == 1
rule("10 the balancer ahead of the hand-off tick: an untaken hand-off 10 minutes old moves, and its mover gets the disregard notice, not the hand-off tick's reminder", probe_preempt, [(HI, "balance_all", lambda *a, **k: [])])

# ================================================================ 11. a torn record is not a signal
def probe_torn_balance():
    wipe(); on(); put(1, act=15, balance={"at": "yesterday", "count": "x", "none_at": float("nan"), "capped_at": "no", "to": 5}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    try: got = tick()
    except Exception as e_: return f"raised {e_!r}"
    return got == ["a1"] and mt(1)["balance"]["count"] == 1 and mt(1)["balance"]["to"] == "team-back"
rule("11 a torn balance record (a time or count that is no number) does not raise and blocks nothing", probe_torn_balance, [(HI, "_num", lambda v: 1.0), (HI, "balance_count", lambda meta: 99)])
def probe_future_stamp():
    wipe(); on(); put(1, act=15, balance={"at": now0 + 400 * 86400.0, "count": 1}, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    return tick() == ["a1"]
rule("11 a balance stamp dated far ahead blocks nothing (a clock set wrong once must not hold an item for good)", probe_future_stamp, [(HI, "_within", lambda stamp, now: isinstance(stamp, (int, float)) and now - stamp < HI.DAY)])
def probe_torn_activity():
    wipe(); on(); put(1, act=15, last=None, last_activity={"at": True, "kind": 7, "what": None}, **ho("home-peer", 12)); put(2, act=15, last_activity="torn"); panes["team-aux"] = "idle"
    try: return isinstance(tick(), list)
    except Exception as e_: return f"raised {e_!r}"
check("11 a torn last_activity is no signal and raises nothing", probe_torn_activity() is True)
def probe_torn_item():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); items = {"a1": rd(1), "a2": {"status": "open", "metadata": "torn"}, "a3": {"status": "open"}, "a4": {"status": "open", "metadata": {"handoff": "torn", "steps": 7, "next": 7}}}; panes["team-aux"] = "idle"
    try: return isinstance(tick(items=items), list)
    except Exception as e_: return f"raised {e_!r}"
check("11 an item that cannot be read at all is left out and stops no other", probe_torn_item() is True, probe_torn_item())
def probe_torn_handoff():
    wipe(); on(); put(1, act=15, handoff={"to": "home-peer", "delivered_at": [1], "at": {"x": 1}, "tried": "oops"}); panes["team-aux"] = "idle"
    try: return tick() == []
    except Exception as e_: return f"raised {e_!r}"
check("11 a hand-off record with no readable time is no wait: nothing moves and nothing raises", probe_torn_handoff() is True)


# ================================================================ 12. builders only
def probe_builders_list():
    return server._balance_builders("projects/alpha") == ["team-back", "team-aux"] and "team-rev" not in server._balance_builders("projects/alpha")
rule("12 the candidates are builders only (a mandate that says build, maintain, merge or engineer), the item's own project's; a reviewer is none", probe_builders_list, [(handoff_svc, "handoff_ranked", lambda project: [(2, i, n) for i, n in enumerate(("team-back", "team-aux", "team-rev"))])])
def probe_reviewer_no_target():
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 12)); [busy_on(n, 1, first=60 + 10 * k) for k, n in enumerate(("team-aux", "other-back", "home-peer"))]
    for n in ("team-rev", "team-aux", "team-back", "other-back", "home-peer"): panes[n] = "idle"
    return tick() == [] and mover_of(1) == "team-back" and sent == []
rule("12 a builder's item does not go to a reviewer with no open items: with every builder as loaded as its mover it stays", probe_reviewer_no_target, [(server, "_balance_builders", lambda project: server._hand_idle_builders(project))])
def probe_reviewer_mover():
    wipe(); on(); put(1, mover="team-rev", act=15, **ho("team-rev", 12)); panes["team-aux"] = "idle"; panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "team-rev" and sent == []
rule("12 an item whose mover is a reviewer is never balanced", probe_reviewer_mover, [(server, "_balance_builder_names", lambda: ["team-rev", "team-back", "team-aux", "other-back", "home-peer"])])
def probe_stranger_mover():
    wipe(); on(); put(1, mover="home-peer2", act=15, **ho("home-peer2", 12)); panes["team-aux"] = "idle"; panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer2" and sent == []
rule("12 …nor one whose mover is no agent of any project page", probe_stranger_mover, [(server, "_balance_builder_names", lambda: ["home-peer2", "team-back", "team-aux"])])
def probe_roles_unreadable():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    real = server._balance_builder_names
    def boom(narrow=False): raise OSError("registry gone")
    server._balance_builder_names = boom
    try:
        with _Err() as e: got = tick()
    finally: server._balance_builder_names = real
    return got == [] and mover_of(1) == "home-peer" and "builders not read" in e.text
check("12 with no view of who builds nothing is judged a builder: nothing moves, a stderr line says so", probe_roles_unreadable() is True)

# ================================================================ 13. bookkeeping when a send after the save fails
def raising_handoff_tell(gid, owner, note, tag="wake", result=None):
    if tag == "handoff": raise OSError("push gone")
    return fake_tell(gid, owner, note, tag, result)
def probe_send_fails():
    queue_setup(n_queued=2); real = telling.tell_woken; telling.tell_woken = raising_handoff_tell
    try:
        with _Err() as e: got = tick()
    finally: telling.tell_woken = real
    return got == ["a2", "a3"] and mover_of(2) == "team-back" and mover_of(3) == "team-aux" and len(told("balance")) == 1 and "sending after the move failed" in e.text
rule("13 a failed send of the new builder's notice (after the save) does not lose the bookkeeping: the move counts, the next item sees the new load (+1 rule), and the former mover is still told", probe_send_fails,
     [(HI, "mark_balanced", lambda meta, now, frm, to: meta.__setitem__("balance", {"at": now + 1, "from": frm, "to": to, "count": 1}))])
def probe_send_fails_cap():
    wipe(); on()
    for i in range(1, 6): put(i, act=15, **ho("home-peer", 12))
    for n in ("team-back", "team-aux", "other-back", "lone-back"): panes[n] = "idle"
    real_b = server._balance_builders; server._balance_builders = lambda project: ["team-back", "team-aux", "other-back", "lone-back"]
    real = telling.tell_woken; telling.tell_woken = raising_handoff_tell
    try:
        with _Err(): got = tick()
    finally: telling.tell_woken = real; server._balance_builders = real_b
    return len(got) == 3
rule("13 …and the cap of three per pass still holds", probe_send_fails_cap, [(HI, "mark_balanced", lambda meta, now, frm, to: meta.__setitem__("balance", {"at": now + 1, "from": frm, "to": to, "count": 1}))])

# ================================================================ 14. the gates: [model] handoff, [audit] enabled, a pane that is gone
def probe_handoff_off():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    _cfg.CFG.setdefault("model", {})["handoff"] = False
    try: return tick() == [] and mover_of(1) == "home-peer" and sent == []
    finally: _cfg.CFG["model"].pop("handoff", None)
rule("14 with `[model] handoff` off the balancer stands still, as the hand-off tick does", probe_handoff_off, [(handoff_svc, "handoff_on", lambda: True)])
def probe_audit_disabled():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    old = _cfg.CFG["audit"].get("enabled"); _cfg.CFG["audit"]["enabled"] = False
    try: return tick() == [] and mover_of(1) == "home-peer" and sent == []
    finally: _cfg.CFG["audit"]["enabled"] = old
rule("14 with `[audit] enabled` false the balancer stands still (it needs the audit on, not hand_idle or hourly_line)", probe_audit_disabled, [(_cfg, "audit_enabled", lambda: True)])
def probe_needs_only_audit():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"
    for k in ("hand_idle", "hourly_line"): _cfg.CFG["audit"][k] = False
    return HI.enabled() is False and tick() == ["a1"]
check("14 …and it runs with hand_idle and hourly_line off", probe_needs_only_audit() is True)
def probe_dead_former():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); panes["team-aux"] = "idle"; dead["home-peer"] = "a retired session, its pane gone"
    got = tick()
    return got == ["a1"] and mover_of(1) == "team-back" and told("balance") == [] and "undelivered" not in mt(1)
rule("14 a former mover whose pane is gone is not sent the disregard notice (nothing is left undelivered on the item that moved)", probe_dead_former, [(handoff_svc, "handoff_pane", lambda who, idx=None: "")])

# ================================================================ 15. what the mover took before still counts
HIST = lambda to, taken=now0 - 50 * MIN: [{"to": to, "from": "home-stew", "at": now0 - 60 * MIN, "delivered_at": now0 - 59 * MIN, "taken_at": taken, "ended_at": now0 - 40 * MIN, "ended": "x"}]
def probe_history_taken(**meta):
    def probe():
        queue_setup(queued_meta=meta)
        return tick() == [] and mover_of(2) == "home-peer" and sent == []
    return probe
cases15 = {
    "the latest record names another mover and an earlier one to this mover was taken": dict(**ho("home-peer2", 30), handoff_history=HIST("home-peer")),
    "the latest record is missing": dict(handoff_history=HIST("home-peer")),
    "the latest record is torn": dict(handoff="torn", handoff_history=HIST("home-peer")),
}
for name, meta in cases15.items():
    rule(f"15 a queued item stays with its mover when {name} (handoff_history carries its taken_at)", probe_history_taken(**meta), [(HI._ho, "HISTORY", "no_such_key")])
def probe_history_other():
    queue_setup(queued_meta=dict(handoff_history=HIST("home-peer2")))
    return tick() == ["a2"]
check("15 control: a taken hand-off in the history that was to another session, or one never taken, is no start of this mover's", probe_history_other() is True and (queue_setup(queued_meta=dict(handoff_history=HIST("home-peer", taken=None))) or tick() == ["a2"]))

# ================================================================ 16. who counts as a builder: the mover's test, apart from the targets
def probe_cross():
    return "gamma-maint" in server._balance_builder_names() and "team-rev" not in server._balance_builder_names() and "gamma-maint" not in server._balance_builders("projects/alpha")
rule("16 a maintainer of another project is a builder (its item may be balanced) but never a target for another project's item", probe_cross, [(server, "_balance_builder_names", lambda: [])])

# ================================================================ 17. only the builders of the item's own project
def old_builders(project):      # the reverted rule: the project's own builders, then the `build` builders of every other project
    out = [n for c, _o, n in handoff_svc.handoff_ranked(project) if c < 2]
    reg = _anc.registry()
    return out + [n for n, r in _anc.session_roles(reg).items() if r.get("role") == "back" and not r.get("retired") and n not in out
                  and re.search(r"\bbuild", str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or ""), re.I)]
def probe_own_only_list():
    return (server._balance_builders("projects/alpha") == ["team-back", "team-aux"] and server._balance_builders("projects/beta") == ["other-back"]
            and server._balance_builders("projects/lone") == ["home-peer"] and server._balance_builders("projects/gamma") == ["gamma-maint"])
rule("17 the candidates for an item are the builders of its own project, never another project's", probe_own_only_list, [(server, "_balance_builders", old_builders)])
def probe_other_project_never():
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 12)); busy_on("team-back", 1, first=60)
    for n in ("team-aux", "other-back", "home-peer", "gamma-maint"): panes[n] = "idle"
    dead["team-aux"] = "a retired session, its pane gone"      # the project's only other builder cannot take it; the empty builders of beta, lone and gamma must not
    with _Err() as e: got = tick()
    return got == [] and mover_of(1) == "team-back" and HO.record_of(rd(1))["to"] == "team-back" and not told("balance")
rule("17 an item of one project is not handed to another project's builder, however idle (its own project's other builder has no pane: the item stays)", probe_other_project_never, [(server, "_balance_builders", old_builders)])
def probe_no_other_builder():
    wipe(); on(); put(1, mover="home-peer", project="projects/lone", act=15, **ho("home-peer", 12))
    for n in ("team-back", "team-aux", "other-back", "gamma-maint"): panes[n] = "idle"
    with _Err() as e: got = tick()
    return got == [] and mover_of(1) == "home-peer" and sent == [] and history(1) == [] and "balance" not in mt(1) and "no other builder to move it to" in e.text
rule("17 a project whose only builder is the item's mover leaves the item where it is, silently, whoever else is idle", probe_no_other_builder, [(server, "_balance_builders", old_builders)])
def probe_own_project_still_moves():
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 12)); busy_on("team-back", 1, first=60)
    for n in ("team-aux", "other-back"): panes[n] = "idle"
    return tick() == ["a1"] and mover_of(1) == "team-aux"
check("17 control: the project's own idle builder still takes it", probe_own_project_still_moves() is True)

# ================================================================ 18. a hand-back leaves no stale `needs` entry for the previous holder
def moved_item():
    wipe(); on(); put(1, mover="team-back", act=15, **ho("team-back", 12)); busy_on("team-back", 1, first=60); panes["team-aux"] = "idle"; panes["team-back"] = "idle"
    return tick()
check("18 the balancer's own write names only the new holder in `needs` (the one it left is dropped from it)", moved_item() == ["a1"] and mt(1)["needs"] == ["team-aux"] and mover_of(1) == "team-aux", mt(1).get("needs"))
def probe_handback(**kw):
    moved_item()
    _update_svc._update("a1", sender="home-stew", mover="team-back", **kw)
    return mover_of(1) == "team-back" and mt(1)["needs"] == ["team-back"]
check("18 an item handed back by `mover=` names the new holder in `needs` and not the one it came from", probe_handback() is True, mt(1).get("needs"))
check("18 …with a `next` line beside it", probe_handback(next="team-back: take it back") is True, mt(1).get("needs"))
def probe_handback_keeps_kinds():
    moved_item()
    _update_svc._update("a1", sender="home-stew", needs=["external", "team-aux"])
    _update_svc._update("a1", sender="home-stew", mover="team-back")
    return mt(1)["needs"] == ["external", "team-back"]
check("18 a kind in `needs` (external) stays when the holder is replaced", probe_handback_keeps_kinds() is True, mt(1).get("needs"))
def probe_handback_needs_given():
    moved_item()
    _update_svc._update("a1", sender="home-stew", mover="team-back", needs=["team-back", "team-aux"])
    return mt(1)["needs"] == ["team-back", "team-aux"]
check("18 a write that sets `needs` itself is taken as given", probe_handback_needs_given() is True, mt(1).get("needs"))

def probe_handback_notices():
    moved_item(); sent.clear()
    _update_svc._update("a1", sender="home-stew", mover="team-back")
    mine = to_builder("team-back")
    return mover_of(1) == "team-back" and mt(1)["needs"] == ["team-back"] and len(mine) == 1 and mine[0][3] != "needs" and not told("needs", "team-back")
check("18 the new mover of a `mover=` hand-back hears one notice (the hand-off's), not also a `now needs you` for the needs entry the write itself made", probe_handback_notices() is True, [(x[3], x[2][:60]) for x in to_builder("team-back")])
def probe_handback_notices_old():      # the control: a session named in `needs` by the writer's own `needs=` is still told that it is needed
    moved_item(); sent.clear()
    _update_svc._update("a1", sender="home-stew", needs=["team-aux", "team-back"])
    return len(told("needs", "team-back")) == 1
check("18 …while a session the writer names in `needs=` is still told", probe_handback_notices_old() is True)

# ================================================================ 19. a stay that lasts is logged once an hour, not every minute
def probe_log_throttle():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12))
    real = server._balance_builders; server._balance_builders = lambda project: ["home-peer"]
    try:
        with _Err() as e1: tick(); tick(now0 + 60); tick(now0 + 30 * MIN)
        with _Err() as e2: tick(now0 + 61 * MIN)
    finally: server._balance_builders = real
    return e1.text.count("no other builder to move it to") == 1 and e2.text.count("no other builder to move it to") == 1
rule("19 'no other builder to move it to' is logged once per item per hour", probe_log_throttle, [(server, "BALANCE_LOG_EVERY", 0.0)])
def probe_log_throttle_load():
    wipe(); on(); put(1, act=15, **ho("home-peer", 12)); [busy_on(n, 1, first=60 + 10 * k) for k, n in enumerate(("team-back", "team-aux"))]
    for n in ("team-back", "team-aux"): panes[n] = "idle"
    with _Err() as e: tick(); tick(now0 + 60); tick(now0 + 5 * MIN)
    return e.text.count("no builder has few enough open items") == 1
rule("19 'no builder has few enough open items' is logged once per item per hour too", probe_log_throttle_load, [(server, "BALANCE_LOG_EVERY", 0.0)])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
