"""Scenario test for handing an idle item on (audit/hand_idle.py, server._hand_idle_tick, run from the ten-minute silence tick right after the hourly line, `[audit] hand_idle`): an item on an agent that has had
no activity for an hour and whose hourly audit line says `idle, nothing verified` goes to a free builder, and the project's -main agent is told; the owner never is. Fixture items in a temporary store, a fake
clock (the pass is given its `now`), the pane registry replaced by a dict, no live store, no network, no model call, no message really sent.

Every rule is a probe that returns whether the rule held on a fixture, run twice: as the code is (it must hold) and with that one rule reverted by a patch (it must fail), so a check that cannot fail is caught.

  1  on by default: the example config documents `hand_idle = true`, absent or a TOML true is on; false / the string "true" / 1 do nothing; a read-only copy does nothing
  2  an idle item with a free builder is handed to it through the minute pass's own write: the builder is the mover, the hand-off record names it from the server, ONE History line says why and names the
     mover it left, the builder is told, -main gets ONE message that asks nothing, nobody else is told (the owner never), no step or decision is made for the owner
  3  what is read: the newest line must be idle (a verified one is not), not old (a line older than 6 hours 15 minutes is no news), and nothing may have moved the item since it
  4  what is left alone: a hold, a parked item, a stored wait, an item behind an open one, the owner's item, a closed item, an untaken hand-off, a front agent's item
  5  which builder is free: not one whose pane is in a turn, not one that moves an open item on an agent (an untaken hand-off to it counts), one that moves a held item is free; the project's own
     background agents only, never a builder of another project, however idle; a project with no background agent of its own, or none free, keeps the item and -main is told; the item's own mover is never picked;
     a name with no pane or an unreadable pane is not free
  6  no free builder: nothing moves, -main is told it once per item per 24 hours, one History line says so; a project with no -main agent gets the History line alone
  7  the limits: an item is handed on once in 24 hours and may be handed again after that; at most 3 items per pass; two builders never get one item each of the same pass twice over
  8  a torn audit entry or a torn record of this pass does not raise and is no signal
  9  the tick: `_silence_tick` runs it after the hourly line; a failure in it stops nothing

    tests/run-suite hand_idle       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="handidle-"); T = pathlib.Path(tmp)
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
NAMES = ("home-main", "team-back", "team-aux", "other-back", "beta-main", "home-peer", "home-peer2", "home-stew", "lone-back", "lone-main", "gamma-main", "delta-main", "delta-one", "delta-two")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-main": "the front", "team-back": "builds, merges and releases the code", "team-aux": "reviews the notes"}
BETA = {"beta-main": "the front", "other-back": "builds the beta code"}
LONE = {"lone-main": "the front", "lone-back": "reviews the notes"}
GAMMA = {"gamma-main": "the front"}                                      # a project with no background agent at all
DELTA = {"delta-main": "the front", "delta-one": "builds the code", "delta-two": "builds and releases the code"}      # a project with two builders
pages = {"projects/alpha": ("home-stew", ALPHA), "projects/beta": ("beta-main", BETA), "projects/gamma": ("gamma-main", GAMMA), "projects/delta": ("delta-main", DELTA)}
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
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.core import readonly as _ro
from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.anchors import anchors as _anc
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
from stackshot.web.tools import sessions as _wt_sessions
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
from stackshot.audit import hourly as HR, hand_idle as HI, silence as SL
from stackshot.waits import stall as ST, handoff as HO
from stackshot.audit import hourly_log as HL
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

def put(i, mover="home-peer", status="open", act=90, project="projects/alpha", idle_line=True, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0. With `idle_line` it carries the hourly audit's idle line, written 5 minutes before now0."""
    base = {"owner": U["home-main"], "project": project, "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    if idle_line and "hourly_audit" not in base: base["hourly_audit"] = {"log": [{"at": now0 - 5 * MIN, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}]}
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "written_at": at, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def mover_of(i): return mt(i).get("mover")      # the stored mover (a waiting item has no derived one)
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    sent.clear(); panes.clear(); dead.clear()
def on(): _cfg.CFG["audit"]["hand_idle"] = True
def off(): _cfg.CFG["audit"]["hand_idle"] = False
def tick(at=None, **kw):
    """One pass of the hand-over at `at` (default now0), the server's clock set to it → the ids handed on."""
    at = now0 if at is None else at
    CLK.t = at
    try: return server._hand_idle_tick(now=at, **kw)
    finally: CLK.t = None
def to_main(): return [x for x in sent if x[1] == U["home-main"]]
def to_builder(name): return [x for x in sent if x[1] == U[name]]
def history(i): return [e["text"] for e in ST.log_of(mt(i))]
def hm(at): return time.strftime("%H:%M", time.gmtime(at + 4 * 3600))
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
wipe(); put(1, act=90, idle_line=False); panes["home-peer"] = "idle"
check("1 the example config documents `hand_idle = true` in [audit]", re.search(r"(?m)^hand_idle = true\b", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)
check("1 …and the config as loaded (from that example) has it on; with no audit line on the item nothing is handed on and nobody is told", HI.enabled() is True and tick() == [] and mover_of(1) == "home-peer" and sent == [])
_cfg.CFG["audit"].pop("hand_idle", None)
check("1 …and with the key absent the code's default is on", HI.enabled() is True)
put(1, act=90)      # now with the hourly audit's idle line on it: only the switch decides whether it is handed on
for label, val in (("false", False), ("the string true", "true"), ("1", 1), ("yes", "yes")):
    _cfg.CFG["audit"]["hand_idle"] = val
    check(f"1 {label} leaves it off (only a TOML true leaves it on)", HI.enabled() is False and tick() == [] and mover_of(1) == "home-peer")
on()
check("1 a TOML true switches it on", HI.enabled() is True)
ro = _ro.is_read_only
_ro.is_read_only = lambda: True
check("1 a read-only standby copy hands nothing on", tick() == [] and mover_of(1) == "home-peer" and sent == [])
_ro.is_read_only = ro
off()
def probe_off():
    wipe(); put(1, act=90); panes["home-peer"] = "idle"; off()
    return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("1 off by default does nothing", probe_off, [(HI, "enabled", lambda: True)])

# ================================================================ 2. an idle item with a free builder
wipe(); on(); put(1, act=90); panes["home-peer"] = "idle"; panes["team-back"] = "idle"
before = rd(1)
with _Err() as err: got = tick()
m = mt(1)
check("2 the idle item is handed on: the pass says so", got == ["a1"], got)
check("2 the builder (the first background agent of the project whose mandate builds) is the mover", mover_of(1) == "team-back" and m["needs"][0] == "team-back" and m["mover"] == "team-back", (mover_of(1), m.get("needs"), m.get("mover")))
check("2 the hand-off record names the builder, from the server, with the reason", HO.record_of(rd(1))["to"] == "team-back" and "no activity for an hour, nothing verified" in str(HO.record_of(rd(1)).get("reason")), HO.record_of(rd(1)))
h1 = history(1)
check("2 ONE History line says why and names the mover it left", len(h1) == 1 and h1[0] == "handed to team-back: no activity for an hour, nothing verified (it was with home-peer)", h1)
check("2 the builder is told (the hand-off notice) and told once", len(to_builder("team-back")) == 1 and to_builder("team-back")[0][3] == "handoff" and "no activity for an hour, nothing verified" in to_builder("team-back")[0][2], to_builder("team-back"))
tm = to_main()
check("2 -main gets ONE message, through the notice path the ladder uses for it (tag stall, the front agent's mark on line 1)", len(tm) == 1 and tm[0][3] == "stall" and tm[0][2].startswith(_wt_text._FOR_OWNER + "\n") and tm[0][0] == "a1", tm)
check("2 …it says what happened and names both movers, and asks nothing", all(x in tm[0][2] for x in ("home-peer", "team-back", "no activity for an hour")) and "Nothing is asked of you" in tm[0][2] and "?" not in tm[0][2].split("\n", 1)[1], tm[0][2])
check("2 nobody else is told: every notice went to the builder or to -main, none to the owner, a message, a flag or anyone else", sorted(x[1] for x in sent) == sorted([U["team-back"], U["home-main"]]) and not any(x[3] in ("message", "flag") for x in sent), sent)
check("2 the owner is not put in the item: no decision or step of his, the next lines and the ask as they were, the item's state still doing",
      "decision" not in [str(x).lower() for x in m.get("needs", [])] and m.get("next") == before["metadata"]["next"] and not m.get("ask") and m.get("state") == "doing" and not any("Oliver" in str(v) for k, v in m.items() if k in ("needs", "next", "mover")), m)
check("2 the record of this pass says who it was handed from and to, and when", m["hand_idle"] == {"handed_at": now0, "from": "home-peer", "to": "team-back"}, m.get("hand_idle"))
check("2 the activity clock is as it was: the move is the server's own bookkeeping", all(rd(1)[k] == before[k] for k in ("activity", "written_by", "written_at")))
check("2 a second pass at once finds the item with an untaken hand-off and does nothing", tick(now0 + 10 * MIN) == [] and len(to_builder("team-back")) == 1 and len(to_main()) == 1 and history(1) == h1)
check("2 the server logs it on stderr", "idle, handed from home-peer to team-back" in err.text, err.text)

def probe_handed():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"
    return tick() == ["a1"] and mover_of(1) == "team-back"
rule("2 an idle item is handed on", probe_handed, [(HI, "due_all", lambda items, now, front=None: [])])
def probe_history():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"; tick()
    return history(1) == ["handed to team-back: no activity for an hour, nothing verified (it was with home-peer)"]
rule("2 the History line says why and names the mover it left", probe_history, [(HI, "WHY", "")])
def probe_main_told():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"; tick()
    return len(to_main()) == 1 and not [x for x in sent if x[1] not in (U["home-main"], U["team-back"])]
rule("2 -main is told, once, and nobody else is", probe_main_told, [(_agents, "_main_agent", lambda p: "")])
_real_main = _agents._main_agent
_agents._main_agent = lambda p: "Oliver"
def probe_owner_main():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"; tick()
    return not any(x[1] in ("Oliver", _web_page_debts._session_id("Oliver")) for x in sent)
rule("2 …a page that names the owner as -main tells him nothing", probe_owner_main, [(_model, "is_owner", lambda who: False)])
_agents._main_agent = _real_main

# ================================================================ 3. what is read
def probe_verified_not_handed():
    wipe(); on(); put(1, act=90, hourly_audit={"log": [{"at": now0 - 5 * MIN, "text": "Audit 10:00: verified the mover's pane is in a turn", "kind": "audit"}]}); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("3 an item whose newest line verified something is not handed on", probe_verified_not_handed, [(HR, "idle_marked", lambda meta, now=None: True)])
def probe_newest_line():
    wipe(); on(); old_idle = {"at": now0 - 65 * MIN, "text": "Audit 09:00: idle, nothing verified", "kind": "audit_idle"}; ok = {"at": now0 - 5 * MIN, "text": "Audit 10:00: verified x", "kind": "audit"}
    put(1, act=130, hourly_audit={"log": [old_idle, ok]}); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer"
rule("3 the NEWEST line decides: an idle line followed by a verified one is not idle", probe_newest_line, [(HR, "idle_marked", lambda meta, now=None: any(e.get("kind") == "audit_idle" for e in HL.log_of(meta)))])
def probe_no_line():
    wipe(); on(); put(1, act=90, idle_line=False); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer"
rule("3 an item with no audit line at all is not handed on", probe_no_line, [(HR, "idle_marked", lambda meta, now=None: True), (HR, "last_line", lambda meta, now=None: {"at": now0 - 5 * MIN, "text": "x", "kind": "audit_idle"})])
def probe_old_line():
    wipe(); on(); put(1, act=600, hourly_audit={"log": [{"at": now0 - 7 * H, "text": "Audit 03:00: idle, nothing verified", "kind": "audit_idle"}]}); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer"
rule("3 an idle line older than 6 hours 15 minutes is no news (the hourly pass is off, or the item left the agent)", probe_old_line, [(HI, "FRESH", 10 ** 9)])
def probe_fresh_line():
    wipe(); on(); put(1, act=600, hourly_audit={"log": [{"at": now0 - 6 * H, "text": "Audit 03:00: idle, nothing verified", "kind": "audit_idle"}]}); panes["team-back"] = "idle"
    return tick() == ["a1"]
check("3 …and one 6 hours old (the slow cadence after a day of silence) still is", probe_fresh_line() is True)
def probe_moved_since():
    wipe(); on(); put(1, act=90); d = rd(1); d["activity"] = now0 - 2 * MIN; (T / "store/a/1.json").write_text(json.dumps(d)); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("3 an item its mover wrote to after the line is not handed on", probe_moved_since, [(SL, "clock", lambda item, mover="": 0.0)])
def probe_state_since():
    wipe(); on(); put(1, act=90); d = rd(1); d["state_updated"] = now0 - 2 * MIN; (T / "store/a/1.json").write_text(json.dumps(d)); panes["team-back"] = "idle"
    return tick() == [] and mover_of(1) == "home-peer"
rule("3 …and so is one whose state changed after it", probe_state_since, [(SL, "clock", lambda item, mover="": 0.0)])
def probe_bare_confirm():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"           # `confirmed` two minutes ago is set by put(): a bare confirm moves nothing
    return tick() == ["a1"]
check("3 a bare confirm after the line is no activity: the item is still handed on", probe_bare_confirm() is True)
def probe_full_hour():
    # the first audit line is owed after 45 minutes, so an idle line can be younger than an hour of silence: the item is handed on only after a full hour (60:00 yes, 59:59 no)
    wipe(); on(); put(1, act=46); panes["team-back"] = "idle"           # silent 46 minutes at now0, its idle line 5 minutes old
    early, late = tick(), tick(now0 + 13 * MIN + 59)
    return early == [] and late == [] and mover_of(1) == "home-peer" and sent == [] and tick(now0 + 14 * MIN) == ["a1"]
rule("3 an item is handed on only after a full hour without activity, even with an idle line written inside the hour (59 minutes 59 seconds no, 60 minutes yes)", probe_full_hour, [(HR, "HOUR", 0.0)])

# ================================================================ 4. what is left alone
def left_alone(name, **kw):
    def probe():
        wipe(); on(); panes["team-back"] = "idle"
        put(1, act=90, **kw.get("meta", {}))
        if kw.get("extra"): kw["extra"]()
        return tick() == [] and mover_of(1) == kw.get("mover", "home-peer") and sent == []
    return probe
wake_far = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 9 * H + 4 * H))
cases4 = {
    "a hold with a dated wake": dict(meta=dict(hold=True, wake=wake_far)),
    "a hold with no wake": dict(meta=dict(hold=True)),
    "a parked item": dict(meta=dict(state="parked", hold=True, wake=wake_far)),
    "a stored wait (a relay)": dict(meta=dict(wait_kind="relay")),
    "an item behind an open one": dict(meta=dict(state="blocked", supplies="its output", after=["a2"]), extra=lambda: put(2, mover="home-peer2", act=30, idle_line=False)),
    "the owner's item": dict(meta=dict(needs=["decision"], ask="pick one", state="your-call", next="Oliver: pick"), mover="Oliver"),
    "an untaken hand-off to a back agent": dict(meta={HO.KEY: HO.new_record("home-peer", "", "team-aux", now0 - 90 * MIN)}),
    "an untaken hand-off to a front agent": dict(meta={HO.KEY: HO.new_record("home-peer", "", "home-main", now0 - 90 * MIN)}),
}
for name, kw in cases4.items():
    if "owner" in name:
        def probe(kw=kw):
            wipe(); on(); panes["team-back"] = "idle"; put(1, mover="Oliver", act=90, **kw["meta"]); return tick() == [] and sent == []
    else:
        probe = left_alone(name, **kw)
    check(f"4 {name} is left alone: nothing handed on, nobody told", probe() is True)
def probe_closed():
    wipe(); on(); panes["team-back"] = "idle"; put(1, act=90, status="completed", outcome="done"); return tick() == [] and sent == []
check("4 a closed item is left alone", probe_closed() is True)
def probe_wait_skipped():
    wipe(); on(); panes["team-back"] = "idle"; put(1, act=90, wait_kind="relay"); return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("4 a waiting item (the board shows it waiting) is skipped", probe_wait_skipped, [(SL, "reading", lambda *a, **k: "agent")])
def probe_held_skipped():
    wipe(); on(); panes["team-back"] = "idle"; put(1, act=90, hold=True); return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("4 an item on hold is skipped", probe_held_skipped, [(HI._wt, "is_held", lambda it: False), (SL, "reading", lambda *a, **k: "agent")])
def probe_untaken():
    wipe(); on(); panes["team-back"] = "idle"; put(1, act=90, **{HO.KEY: HO.new_record("home-peer", "", "team-aux", now0 - 90 * MIN)}); return tick() == [] and mover_of(1) == "home-peer" and sent == []
rule("4 an untaken hand-off is left to the hand-off audit", probe_untaken, [(HO, "awaiting_session", lambda it: False)])
def probe_front_mover():
    wipe(); on(); panes["team-back"] = "idle"; put(1, mover="home-main", act=90); return tick() == [] and mover_of(1) == "home-main" and sent == []
rule("4 an item a front agent moves is left where it is (it is the owner's work)", probe_front_mover, [(telling, "front_keeper", lambda w, p: (False, ""))])
def probe_unreadable():
    wipe(); on(); panes["team-back"] = "idle"; put(1, act=90); d = rd(1); d["metadata"]["next"] = 7; d["metadata"]["needs"] = {"x": 1}; (T / "store/a/1.json").write_text(json.dumps(d))
    return isinstance(tick(), list)
check("4 an item whose record the board's model cannot read does not raise the pass", probe_unreadable() is True)

def probe_stale_view():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"
    from stackshot.tools import next_report as nr
    view = nr.load_all(None)                                                     # the view the pass made: the item idle
    d = rd(1); d["activity"] = now0 - 1 * MIN; (T / "store/a/1.json").write_text(json.dumps(d))      # its mover wrote to it since
    return tick(items=view) == [] and mover_of(1) == "home-peer" and sent == []
rule("4 an item its mover wrote to after the pass read it is read again under the lock and left where it is", probe_stale_view,
     [(HI, "due", lambda items, gid, now, front=None: {"mover": "home-peer", "project": "projects/alpha", "line_at": 0, "told_none": False})])

# ================================================================ 5. which builder is free
def first_pick(**setup):
    wipe(); on(); put(1, act=90)
    for k, v in setup.get("panes", {}).items(): panes[k] = v
    for k, v in setup.get("dead", {}).items(): dead[k] = v
    if setup.get("extra"): setup["extra"]()
    got = tick()
    return got, mover_of(1)
def probe_busy_pane():
    got, mv = first_pick(panes={"team-back": "busy", "team-aux": "idle"})
    return got == ["a1"] and mv == "team-aux"
rule("5 a builder whose pane is in a turn is not free: the next background agent of the project takes it", probe_busy_pane, [(HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x), ""))])
def probe_busy_item():
    got, mv = first_pick(panes={"team-back": "idle", "team-aux": "idle"}, extra=lambda: put(2, mover="team-back", act=10, idle_line=False))
    return got == ["a1"] and mv == "team-aux"
rule("5 a builder that moves an open item on an agent is not free", probe_busy_item, [(HI, "busy_movers", lambda items, now: [])])
def probe_busy_untaken():
    got, mv = first_pick(panes={"team-back": "idle", "team-aux": "idle"}, extra=lambda: put(2, mover="team-back", act=10, idle_line=False, **{HO.KEY: HO.new_record("team-back", "", "home-peer2", now0 - 3 * MIN)}))
    return got == ["a1"] and mv == "team-aux"
check("5 …an untaken hand-off to it counts: it is about to take that item", probe_busy_untaken() is True)
def probe_held_builder_free():
    got, mv = first_pick(panes={"team-back": "idle"}, extra=lambda: put(2, mover="team-back", act=10, idle_line=False, hold=True))
    return got == ["a1"] and mv == "team-back"
rule("5 a builder that moves only a held item is free", probe_held_builder_free, [(HI, "busy_movers", lambda items, now: [it.get("metadata", {}).get("mover") for it in items.values() if it.get("status") == "open"])])
def old_builders(project):      # the reverted rule: the project's own background agents, then every other project's agent whose mandate says build
    out = list(handoff_svc.handoff_background(project))
    reg = _anc.registry()
    return out + [n for n, r in _anc.session_roles(reg).items() if r.get("role") == "back" and not r.get("retired") and n not in out
                  and re.search(r"\bbuild", str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or ""), re.I)]
def probe_other_project():
    got, mv = first_pick(panes={"team-back": "busy", "team-aux": "busy", "other-back": "idle", "delta-one": "idle"})
    return got == [] and mv == "home-peer" and to_builder("other-back") == [] and to_builder("delta-one") == [] and len(to_main()) == 1
rule("5 with none of the project's own free, a builder of another project is not offered, however idle: the item stays and -main is told", probe_other_project, [(server, "_hand_idle_builders", old_builders)])
def probe_own_project_pick():
    wipe(); on(); put(1, act=90); put(2, act=90, project="projects/beta")
    for n in ("team-back", "team-aux", "other-back", "delta-one", "delta-two"): panes[n] = "idle"
    got = tick()
    return got == ["a1", "a2"] and mover_of(1) == "team-back" and mover_of(2) == "other-back"
rule("5 an item goes to a builder of its own project: an item of alpha to alpha's, an item of beta to beta's", probe_own_project_pick, [(server, "_hand_idle_builders", lambda project: ["other-back", "team-back"] if project == "projects/alpha" else ["team-back", "other-back"])])
def probe_beta_never_alpha():
    wipe(); on(); put(1, act=90, project="projects/beta"); panes["other-back"] = "busy"
    for n in ("team-back", "team-aux", "delta-one"): panes[n] = "idle"
    got = tick()
    return got == [] and mover_of(1) == "home-peer" and to_builder("team-back") == [] and to_builder("team-aux") == [] and to_builder("delta-one") == []
rule("5 an item of beta whose own builder is in a turn is not handed to alpha's or delta's idle builder", probe_beta_never_alpha, [(server, "_hand_idle_builders", old_builders)])
def probe_no_background_agent():
    wipe(); on(); put(1, act=90, project="projects/gamma")
    for n in ("team-back", "team-aux", "other-back", "delta-one", "delta-two", "lone-back"): panes[n] = "idle"
    with _Err() as e: got = tick()
    tm = [x for x in sent if x[1] == U["gamma-main"]]
    return (got == [] and mover_of(1) == "home-peer" and len(sent) == 1 and len(tm) == 1 and tm[0][3] == "stall" and "no builder was free" in tm[0][2] and "stays with home-peer" in tm[0][2]
            and len(history(1)) == 1 and "no builder was free to take it: gamma-main was told" in history(1)[0] and mt(1)["hand_idle"] == {"none_at": now0}
            and "idle, no builder free" in e.text)
rule("5 a project with no background agent of its own keeps the item, however many builders other projects have idle: the History line and -main say so", probe_no_background_agent, [(server, "_hand_idle_builders", old_builders)])
def probe_no_background_agent_once():
    wipe(); on(); put(1, act=90, project="projects/gamma"); panes["team-back"] = "idle"
    tick(); tick(now0 + 10 * MIN); tick(now0 + 23 * H)
    return len([x for x in sent if x[1] == U["gamma-main"]]) == 1 and len(history(1)) == 1 and to_builder("team-back") == []
check("5 …and that is told once per item per 24 hours, as for any item with no builder free", probe_no_background_agent_once() is True)
def probe_two_builders():
    wipe(); on(); put(1, act=90, project="projects/delta"); put(2, act=90, project="projects/delta"); put(3, mover="delta-one", act=10, idle_line=False, project="projects/delta")
    for n in ("delta-one", "delta-two", "team-back", "other-back"): panes[n] = "idle"
    got = tick()
    return got == ["a1"] and mover_of(1) == "delta-two" and mover_of(2) == "home-peer" and to_builder("team-back") == [] and to_builder("other-back") == []
rule("5 a project with two builders: the one that moves an open item is not free, the other takes the first item, the second item stays (no builder of another project takes it)", probe_two_builders, [(server, "_hand_idle_builders", old_builders), (HI, "busy_movers", lambda items, now: [])])
def probe_two_builders_first():
    wipe(); on(); put(1, act=90, project="projects/delta")
    for n in ("delta-one", "delta-two", "team-back"): panes[n] = "idle"
    return tick() == ["a1"] and mover_of(1) == "delta-one"
check("5 …with both free, the first of the page's order takes it", probe_two_builders_first() is True)
def probe_dead():
    got, mv = first_pick(panes={"team-back": "idle", "team-aux": "idle"}, dead={"team-back": "a retired session, its pane gone"})
    return got == ["a1"] and mv == "team-aux"
rule("5 a name known to have no pane is not free", probe_dead, [(HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x and status(x) != "busy"), ""))])
def probe_boom():
    got, mv = first_pick(panes={"team-back": "boom", "team-aux": "idle"})
    return got == ["a1"] and mv == "team-aux"
rule("5 a builder whose pane cannot be read is not free", probe_boom, [(HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x), ""))])
def probe_unknown_pane_free():
    got, mv = first_pick(panes={})
    return got == ["a1"] and mv == "team-back"
check("5 a pane this box does not show (no registry row) reads as not in a turn: the first builder takes it", probe_unknown_pane_free() is True)
def probe_own_mover():
    wipe(); on(); put(1, mover="team-back", act=90); panes["team-back"] = "idle"; panes["team-aux"] = "idle"
    got = tick()
    return got == ["a1"] and mover_of(1) == "team-aux"
rule("5 an idle item a builder moves goes to ANOTHER builder, never back to the same one", probe_own_mover, [(HI, "busy_movers", lambda items, now: []), (HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x), ""))])

# ================================================================ 6. no builder free
def all_busy():
    for n in ("team-back", "team-aux", "other-back"): panes[n] = "busy"
def probe_none_free():
    wipe(); on(); put(1, act=90); all_busy()
    got = tick()
    return got == [] and mover_of(1) == "home-peer" and len(to_main()) == 1 and len(sent) == 1 and "no builder was free" in to_main()[0][2] and "stays with home-peer" in to_main()[0][2] and "Oliver" not in to_main()[0][2].split("\n", 1)[1].replace("nothing here is for Oliver", "")
rule("6 with no builder free nothing moves and -main is told that none was, and only -main", probe_none_free, [(HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x), ""))])
wipe(); on(); put(1, act=90); all_busy(); tick()
h6 = history(1)
check("6 one History line says so, and the item keeps its mover and its record", len(h6) == 1 and h6[0].startswith("no activity for an hour and nothing verified, but no builder was free to take it: home-main was told") and mt(1)["hand_idle"] == {"none_at": now0}, (h6, mt(1).get("hand_idle")))
check("6 the pass leaves the item's hand-off alone: no record, the next lines as they were", HO.record_of(rd(1)) is None or not HO.record_of(rd(1)), HO.record_of(rd(1)))
def probe_once_per_day():
    wipe(); on(); put(1, act=90); all_busy()
    tick(); n1 = len(to_main())
    tick(now0 + 10 * MIN); tick(now0 + 8 * H); tick(now0 + 23 * H)
    return n1 == 1 and len(to_main()) == 1 and len(history(1)) == 1
rule("6 -main is told that none was free once per item per 24 hours, not every tick", probe_once_per_day, [(HI, "none_told_recently", lambda meta, now: False)])
def probe_told_again_next_day():
    wipe(); on(); put(1, act=90); all_busy(); tick()
    d = rd(1); d["metadata"]["hourly_audit"] = {"log": [{"at": now0 + 24 * H - 5 * MIN, "text": "Audit: idle, nothing verified", "kind": "audit_idle"}]}; (T / "store/a/1.json").write_text(json.dumps(d))
    tick(now0 + 24 * H + MIN)
    return len(to_main()) == 2 and len(history(1)) == 2
check("6 …and again after 24 hours while it stays idle", probe_told_again_next_day() is True)
def probe_batched():
    wipe(); on(); put(1, act=90); put(2, act=90); put(3, act=90); all_busy(); tick()
    return len(to_main()) == 1 and to_main()[0][2].count("\n- ") == 3 and sorted(to_main()[0][0].split(",")) == ["a1", "a2", "a3"]
check("6 several items with no builder free are one message to -main, one line each", probe_batched() is True)
# a project whose page names no -main agent
def probe_no_main():
    wipe(); on(); put(1, act=90); all_busy()
    real = _agents._main_agent; _agents._main_agent = lambda p: ""
    try: tick()
    finally: _agents._main_agent = real
    return sent == [] and len(history(1)) == 1 and "the project has no -main agent to tell" in history(1)[0]
check("6 a project with no -main agent gets the History line alone, and no message", probe_no_main() is True)

# ================================================================ 7. the limits
def probe_day_limit():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"; panes["team-aux"] = "idle"
    first = tick()
    d = rd(1); d["metadata"].pop(HO.KEY, None)      # the hand-off was taken: only the 24-hour limit is left to hold the item
    d["metadata"]["hourly_audit"] = {"log": [{"at": now0 + 10 * H - 5 * MIN, "text": "Audit: idle, nothing verified", "kind": "audit_idle"}]}; (T / "store/a/1.json").write_text(json.dumps(d))
    second = tick(now0 + 10 * H)
    return first == ["a1"] and second == [] and mover_of(1) == "team-back"
rule("7 an item is handed on once in 24 hours", probe_day_limit, [(HI, "handed_recently", lambda meta, now: False)])
def probe_day_again():
    wipe(); on(); put(1, act=90); panes["team-back"] = "idle"; panes["team-aux"] = "idle"
    first = tick()
    d = rd(1); d["metadata"].pop(HO.KEY, None)
    d["metadata"]["hourly_audit"] = {"log": [{"at": now0 + 25 * H - 5 * MIN, "text": "Audit: idle, nothing verified", "kind": "audit_idle"}]}; (T / "store/a/1.json").write_text(json.dumps(d))
    second = tick(now0 + 25 * H)
    return first == ["a1"] and second == ["a1"] and mover_of(1) == "team-aux" and mt(1)["hand_idle"]["from"] == "team-back"
check("7 …and may be handed on again once it has been idle for 24 hours more (to another builder: the one that had it is not free)", probe_day_again() is True)
def probe_cap():
    wipe(); on()
    for i in range(1, 6): put(i, act=90)
    for n in ("team-back", "team-aux", "other-back", "lone-back"): panes[n] = "idle"
    real = server._hand_idle_builders; server._hand_idle_builders = lambda project: ["team-back", "team-aux", "other-back", "lone-back"]      # four free builders, five idle items
    try: got = tick(); more = tick(now0 + 10 * MIN)
    finally: server._hand_idle_builders = real
    return len(got) == 3 and len(more) <= 3 and len(set(mover_of(i) for i in range(1, 6)) - {"home-peer"}) == len(got) + len(more)
rule("7 at most three items are handed on in one pass (the next pass goes on with the rest)", probe_cap, [(HI, "MAX_PER_TICK", 99)])
def probe_distinct():
    wipe(); on()
    for i in range(1, 4): put(i, act=90)
    panes["team-back"] = "idle"; panes["team-aux"] = "busy"; panes["other-back"] = "busy"
    got = tick()
    return got == ["a1"] and mover_of(1) == "team-back" and mover_of(2) == "home-peer" and mover_of(3) == "home-peer"
rule("7 a builder that took an item this pass is no longer free: with one builder only the first item goes", probe_distinct, [(HI, "pick_free", lambda c, busy, status, dead, same, frm="": next((x for x in c if x and status(x) != "busy"), ""))])

# ================================================================ 8. a torn entry
def probe_torn_log():
    wipe(); on(); good = {"at": now0 - 5 * MIN, "text": "Audit 10:00: idle, nothing verified", "kind": "audit_idle"}
    torn = [{"at": "bad", "text": "x", "kind": "audit"}, {"at": float("inf"), "text": "x", "kind": "audit"}, {"at": 1e30, "text": "x", "kind": "audit"}, {"at": float("nan"), "text": "x", "kind": "audit"},
            {"at": now0 - 1, "kind": "audit"}, {"at": now0 - 2, "text": 7, "kind": "audit"}, {"at": None, "text": "x", "kind": "audit"}, "not a dict", {"at": True, "text": "x", "kind": "audit"}]
    put(1, act=90, hourly_audit={"log": [good] + torn}); panes["team-back"] = "idle"
    try: got = tick()
    except Exception as e_: return f"raised {e_!r}"
    return got == ["a1"] and mover_of(1) == "team-back"
rule("8 an hourly log holding torn entries does not raise, and the one good idle line is read", probe_torn_log, [(HL, "_well_formed", lambda x: True)])
def probe_torn_record():
    wipe(); on(); put(1, act=90, hand_idle={"handed_at": "yesterday", "none_at": float("nan"), "to": 5}); panes["team-back"] = "idle"
    try: got = tick()
    except Exception as e_: return f"raised {e_!r}"
    return got == ["a1"] and mover_of(1) == "team-back" and mt(1)["hand_idle"]["to"] == "team-back"
rule("8 a torn record of this pass (a stamp that is no number) does not raise and blocks nothing", probe_torn_record, [(HI, "_within", lambda stamp, now: now - stamp < HI.DAY)])
def probe_future_stamp():
    wipe(); on(); put(1, act=90, hand_idle={"handed_at": now0 + 400 * 86400.0}); panes["team-back"] = "idle"
    return tick() == ["a1"]
rule("8 a hand-over stamp dated far ahead blocks nothing (a clock set wrong once must not hold an item for good)", probe_future_stamp, [(HI, "_within", lambda stamp, now: isinstance(stamp, (int, float)) and now - stamp < HI.DAY)])
def probe_torn_item():
    wipe(); on(); put(1, act=90); items = {"a1": rd(1), "a2": {"status": "open", "metadata": "torn"}, "a3": {"status": "open"}}; panes["team-back"] = "idle"
    try: return isinstance(tick(items=items), list)
    except Exception as e_: return f"raised {e_!r}"
check("8 an item that cannot be read at all is left out and stops no other", probe_torn_item() is True, probe_torn_item())

# ================================================================ 9. the tick
wipe(); on(); put(1, act=90); panes["team-back"] = "idle"
_cfg.CFG["audit"]["hourly_line"] = True
order = []
real_hourly, real_hand = server._hourly_tick, server._hand_idle_tick
server._hourly_tick = lambda *a, **k: (order.append("hourly"), real_hourly(*a, **k))[1]
server._hand_idle_tick = lambda *a, **k: (order.append("hand"), real_hand(now=now0, *a, **k))[1]
try:
    CLK.t = now0
    server._hourly_tick = lambda *a, **k: (order.append("hourly"), [])[1]
    server._silence_tick()
finally:
    CLK.t = None
check("9 `_silence_tick` runs the hand-over after the hourly line, and it hands the idle item on", order == ["hourly", "hand"] and mover_of(1) == "team-back", (order, mover_of(1)))
def boom(*a, **k): raise OSError("store gone")
server._hand_idle_tick = boom
order.clear()
with _Err() as err9: server._silence_tick()
check("9 a failure in the hand-over is a stderr line and stops nothing", "idle items not handed on: OSError" in err9.text, err9.text)
server._hourly_tick, server._hand_idle_tick = real_hourly, real_hand
_cfg.CFG["audit"]["mode"] = "agent"
wipe(); on(); put(1, act=90); panes["team-back"] = "idle"
server._silence_tick()
check("9 the tick stands still when the audit runs in agent mode", mover_of(1) == "home-peer")
_cfg.CFG["audit"]["mode"] = "script"

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
