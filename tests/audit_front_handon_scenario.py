"""Scenario: the hand-on of an idle front agent's own step to a free background agent of its project (audit/front_handon.py, run by audit_ticks._front_handon_tick), and the pick-up (audit/front_pickup.py) as its fallback.

  1.  the probe: an idle front agent, an open step of its own, the owner not in that conversation, a free builder: the item is handed to it (mover, stored mover, needs with the front agent behind it, contact, the hand-off
      record, one History line, the guard stamp, one hand-off notice to the builder and nobody else)
  2.  which agent: the builder-mandate one first, then the others; one in a turn or moving another open item is not free; two items go to two agents; the third is the pick-up's
  3.  no one free (in a turn, unknown, unread, absent, shell, sleeping, no pane, a stale or missing snapshot) or no background agent at all: nothing is handed, the pick-up starts the front agent's turn
  4.  what is never handed on: the owner's step, another session's step, no step, every wait, a closed item, a front agent that is not idle, a mover that is no front agent of the item's project, under 45 minutes of quiet
  5.  the owner in that conversation (a fresh stamp, a future stamp, a partial or unreadable index, an unreadable stamp folder, a presence test that raises): nothing
  6.  one action per item per tick: a failed hand-on does not start the turn either; the audit tick's order; the real tick end to end
  7.  no loop, once a day: a handed item is not handed again; a hand-back inside 24 hours is not handed on again
  8.  a write that fails leaves the item as it was, no mark, nobody told
  9.  the cap of three a tick
  10. reads that fail: the snapshot, the role map, the presence reader, the fleet index, one item, the background-agent lookup
  11. the switches: hourly line, idle hand-over, read-only, paused, agent mode
  12. the idle hand-over's and the busy tell's items are theirs
  13. the writer: the old mover stays named only with `keep_frm`
  14. the rules above fail once the code that holds them is reverted (free test, idle-and-fresh, own step, owner present, partial index)

tests/run-suite audit_front_handon -> exit 0 on success, 1 on a failed check."""
import io, json, os, re, sys, pathlib, time, logging, threading
SCR =os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="fronthandon-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1
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
for d in ("store/a", "fleet/a", "state/prompts", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
FRONTS = ("a-main", "b-main", "c-main", "d-main", "e-main")
NAMES = (*FRONTS, "a-keep", "b-keep", "c-keep", "d-keep", "e-keep", "a-back", "b-back", "c-back", "d-back", "a-aide", "b-aide", "c-aide", "d-aide", "ghost")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times in the lines stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
pages = {f"projects/{p}": (f"{p}-keep", {f"{p}-main": "the front", f"{p}-back": "builds, merges and releases the code", f"{p}-aide": "reviews designs"}) for p in "abcd"}
pages = {k.replace("projects/a", "projects/alpha").replace("projects/b", "projects/beta").replace("projects/c", "projects/gamma").replace("projects/d", "projects/delta"): v for k, v in pages.items()}
PROJ = {"a": "projects/alpha", "b": "projects/beta", "c": "projects/gamma", "d": "projects/delta", "e": "projects/epsilon"}
pages["projects/epsilon"] = ("e-keep", {"e-main": "the front"})      # a project with no background agent of its own
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
from stackshot.web import server, wiring
from stackshot.service import audit_ticks as audit_ticks_svc
from stackshot.service import agent_state as agent_state_svc
from stackshot.service import handoff as handoff_svc
from stackshot.service import telling
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.core import readonly as _ro
from stackshot.core import config as _cfg
from stackshot.web.tools import text as _web_tools_text
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.audit import front_pickup as FP, front_handon as FH, hourly as HR, hand_idle as HI, busy_tell as BT, agent_state as AS
from stackshot.waits import handoff as HO, stall as ST
from stackshot.service import writes as _writes_svc, front_turn as _front_turn_svc
from stackshot.tools import next_report as NR
_web_publish._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
_fleet_sessions_registry._sessions_index = lambda: {u: {"name": n} for n, u in U.items()}      # the fleet's index: a pane's session id -> its name (the prompt stamps are named by the id)
_cfg.CFG["audit"]["pattern_review"] = "off"
_cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every notice the server was asked to send: (items, recipient's id, text, tag)
outcome = {"ok": True, "none": False, "raise": False}              # what the stand-in for tell_woken does: delivers, fails to deliver, returns no thread, raises
def fake_tell(gid, owner, note, tag="wake", result=None):
    sent.append((gid, owner, note, tag))
    if outcome["raise"]: raise OSError("push is down")
    if outcome["none"]: return None
    if result is not None: result.update(ok=outcome["ok"], why="" if outcome["ok"] else "the pane is gone")
    th = threading.Thread(target=lambda: None); th.start()
    return th
telling.tell_woken = fake_tell
handoff_svc.handoff_pane = lambda who, idx=None: ""

def put(i, mover="a-main", status="open", act=60, project="projects/alpha", log=None, nxt=None, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0. `nxt` is its next text (the steps), by default one step of the mover's own. `log` = [(minutes after the activity, kind)] of audit lines, kind idle | pane."""
    base = {"owner": U["a-main"], "project": project, "next": f"{mover}: do the thing" if nxt is None else nxt, "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at_ = now0 - act * MIN
    if log is not None:
        base["hourly_audit"] = {"log": [{"at": at_ + m * MIN, "text": "Audit 10:00: " + ("idle, nothing verified" if k == "idle" else "verified the mover's pane is in a turn (live state only, nothing recorded on the item)"),
                                         "kind": "audit_idle" if k == "idle" else "audit", **({"pane_only": True} if k == "pane" else {})} for m, k in log]}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * MIN, "state_updated": at_, "confirmed": now0 - 2 * MIN,
                                                       "activity": at_, "written_at": at_, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def marks_file(): return T / "state/front-pickup.json"
def stamps_dir(): return T / "state/prompts"
def wipe():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
    for p_ in stamps_dir().glob("*"): p_.unlink()
    for p_ in (T / "state").glob("*front-pickup*"): p_.unlink()
    sent.clear(); (T / "store/anchors.json").write_text("{}"); outcome.update(ok=True, none=False, raise_=False, raise_x=False); outcome["raise"] = False
    for k in ("hourly_line", "hand_idle", "busy_tell"): _cfg.CFG["audit"].pop(k, None)
    _cfg.CFG["audit"]["mode"] = "script"
def at(m): return now0 + m * MIN
PANES = {"idle": ("idle", "idle"), "busy": ("busy", "turn"), "unknown": ("unknown", ""), "unread": ("unknown", ""), "shell": ("idle", "shell"), "sleeping": ("idle", "sleeping")}
def snap(t, states=None, age=0.0):
    """The fleet's agent-state snapshot as the route stores it: every agent idle unless `states` says otherwise ({name: idle | busy | unread | unknown | shell | sleeping | None for absent})."""
    st = {n: "idle" for n in NAMES if n != "ghost"}; st.update(states or {})
    ag = {n: {"state": PANES[s][0], "since": t - H, "why": "", "pane": PANES[s][1], "read": s != "unread", "subagents": []} for n, s in st.items() if s is not None}
    return {"schema": 1, "written": t - age, "agents": ag}
NOT_THERE = lambda who: False
def both_busy(**kw): return {"a-back": "busy", "a-aide": "busy", **kw}
def th(m=0, states=None, age=0.0, snap_=None, present=NOT_THERE, **kw):
    """One tick of the front hand-on `m` minutes after now0, the snapshot as `snap` builds it; `present` None reads the owner's prompt stamps as the server does. → the ids handed on."""
    t = at(m)
    return audit_ticks_svc._front_handon_tick(now=t, snap=snap(t, states, age) if snap_ is None else snap_, present=present, **kw)
def tick2(m=0, states=None, age=0.0, snap_=None, present=NOT_THERE, dead=None, **kw):
    """The two passes as the audit tick runs them, one after the other with the hand-on's `acted` given to the pick-up as its `skip`. → (the ids handed on, the ids a turn was started for)."""
    t = at(m); s = snap(t, states, age) if snap_ is None else snap_; acted = set()
    h = audit_ticks_svc._front_handon_tick(now=t, snap=s, present=present, acted=acted, **({"dead": dead} if dead else {}), **kw)
    p = audit_ticks_svc._front_pickup_tick(now=t, snap=s, present=present, skip=acted, **kw)
    return h, p
class _Err:
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()
    @property
    def pickup_lines(self): return [l for l in self.buf.getvalue().splitlines() if "front pick-up" in l and "told of its own step" not in l]
    @property
    def handon_lines(self): return [l for l in self.buf.getvalue().splitlines() if "front hand-on" in l]
def marks(): return FP.read_marks() if marks_file().exists() else {}
def stamp(name, minutes_ago, m=0): (stamps_dir() / U[name]).write_text(f"{at(m) - minutes_ago * MIN}\n")
def to(name): return [x for x in sent if x[1] == U[name]]
def hist(i): return [e["text"] for e in ST.log_of(mt(i))]
def mover_of(i): return (mt(i).get("needs") or [""])[0]
def untouched(i, before): return rd(i) == before
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
    check(name + " [mutated: the check fails]", broke is not True, broke)
real_index = _fleet_sessions_registry._sessions_index
real_exec = handoff_svc.handoff_exec
real_pickup, real_handon = audit_ticks_svc._front_pickup_tick, audit_ticks_svc._front_handon_tick

# ================================================================ 1. the probe
check("1 the constants: the hand-on rides the pick-up's own test, the hand-over's own 24-hour guard and its cap of three a tick", FH._fp.eligible is FP.eligible and HI.DAY == 24 * 3600.0 and HI.MAX_PER_TICK == 3 and FP.QUIET == 45 * MIN)
wipe(); put(1, act=60, contact="a-main"); before = rd(1)
h1, p1 = tick2(0)
m = mt(1); r = HO.record_of(rd(1))
check("1 the probe: an idle front agent's item with a step of its own, a free builder: it is handed on, and the pick-up starts nothing for it", h1 == ["a1"] and p1 == [], (h1, p1))
check("1 the builder is the mover: it heads needs, the stored mover follows, and the front agent stays named in needs behind it (it hears of the item)", m.get("needs") == ["a-back", "a-main"] and m.get("mover") == "a-back", (m.get("needs"), m.get("mover")))
check("1 the item's contact is the front agent, as it was", m.get("contact") == "a-main" and before["metadata"].get("contact") == "a-main")
check("1 the hand-off record names the builder, made by the server, with the reason and the mover it left", bool(r) and r.get("to") == "a-back" and FH.WHY in str(r.get("reason")) and "a-main" in str(r.get("redirected_from") or r.get("tried") or ""), r)
check("1 ONE History line says why and names the mover it left", hist(1) == [f"handed to a-back: {FH.WHY} (it was with a-main)"], hist(1))
check("1 the hand-over's own guard is stamped (metadata.hand_idle: when, from, to)", m.get("hand_idle") == {"handed_at": at(0), "from": "a-main", "to": "a-back"}, m.get("hand_idle"))
check("1 the steps are not rewritten (the front-step rule rewords them to the new mover later) and nothing else of the item changed", m.get("next") == before["metadata"]["next"] and rd(1)["status"] == "open" and rd(1)["description"] == before["description"] and m.get("state") == "doing", m.get("next"))
check("1 the builder is told once, by the hand-off notice, with the reason; the front agent, the owner and everyone else are told nothing", len(sent) == 1 and len(to("a-back")) == 1 and to("a-back")[0][3] == "handoff" and FH.WHY in to("a-back")[0][2], sent)
check("1 no pick-up mark is made for it", marks() == {})
check("1 the idle hand-over leaves it alone from then on (its 24-hour guard is the hand-on's)", HI.handed_recently(mt(1), at(1)) and HI.due(NR.load_all(None), "a1", at(1), lambda w, p: telling.front_keeper(w, p)[0]) is None)

# ================================================================ 2. which background agent
wipe(); put(1, act=60)
check("2 two free (the builder a-back, and a-aide, a reviewer whose name sorts first): the one whose mandate builds", th(0) == ["a1"] and mover_of(1) == "a-back" and mt(1)["hand_idle"]["to"] == "a-back")
wipe(); put(1, act=60)
check("2 the builder in a turn: the next free one", th(0, {"a-back": "busy"}) == ["a1"] and mover_of(1) == "a-aide" and len(to("a-aide")) == 1)
wipe(); put(1, act=60); put(2, mover="a-back", act=5, nxt="a-back: build it")
check("2 the builder moves another open item (idle pane or not): it is not free, the next one is", th(0) == ["a1"] and mover_of(1) == "a-aide")
wipe(); put(1, act=60)
check("2 a name known to have no pane is not free", th(0, dead=lambda who: "a retired session, its pane gone" if who == "a-back" else "") == ["a1"] and mover_of(1) == "a-aide")
wipe(); put(1, act=60); put(2, act=60, nxt="a-main: another thing")
check("2 two items of the front agent: each goes to its own free agent (a builder that took one is no longer free), the first to the builder", th(0) == ["a1", "a2"] and mover_of(1) == "a-back" and mover_of(2) == "a-aide", (mover_of(1), mover_of(2)))
wipe(); put(1, act=60); put(2, act=60, nxt="a-main: another thing"); put(3, act=60, nxt="a-main: and a third")
got = tick2(0)
check("2 a third item with none left free is the pick-up's, and the two handed are not picked up", got == (["a1", "a2"], ["a3"]) and [x[3] for x in to("a-main")] == ["stall"] and mover_of(3) == "a-main", (got, sent))
wipe(); put(1, act=60)
check("2 another project's idle builder is never a candidate: with the project's own both in a turn nothing is handed and the pick-up has it", tick2(0, both_busy()) == ([], ["a1"]) and mover_of(1) == "a-main")

# ================================================================ 3. no one free: the pick-up
none_free = [("both in a turn", both_busy()), ("both state unknown and unread", {"a-back": "unknown", "a-aide": "unread"}), ("both absent from the snapshot", {"a-back": None, "a-aide": None}),
             ("the builder's pane reads shell, the other's sleeping", {"a-back": "shell", "a-aide": "sleeping"})]
for label, st_ in none_free:
    wipe(); put(1, act=60); before = rd(1)
    got = tick2(0, st_)
    check(f"3 {label}: nothing is handed, the item is not written, and the pick-up starts the front agent's turn", got == ([], ["a1"]) and untouched(1, before) and len(sent) == 1 and sent[0][1] == U["a-main"] and sent[0][3] == "stall" and marks() == {"a1": at(0)}, (got, sent))
wipe(); put(1, act=60); before = rd(1)
got = tick2(0, dead=lambda who: "no pane of it is in the heartbeat")
check("3 both names known to have no pane: nothing is handed, the pick-up has it", got == ([], ["a1"]) and untouched(1, before))
wipe(); put(1, mover="e-main", project="projects/epsilon", act=60, nxt="e-main: ship it"); before = rd(1)
got = tick2(0)
check("3 a project with no background agent of its own: nothing is handed, the pick-up has it", got == ([], ["a1"]) and untouched(1, before) and sent[0][1] == U["e-main"], (got, sent))
wipe(); put(1, act=60)
check("3 a snapshot more than 15 minutes old reads every agent unknown: nothing is handed and nothing is started", tick2(0, age=16 * MIN) == ([], []) and sent == [])
wipe(); put(1, act=60)
check("3 no snapshot at all: nothing", tick2(0, snap_={}) == ([], []) and sent == [])
wipe(); put(1, act=60); marks_file().write_text(json.dumps({"schema": 1, "marks": {"a1": at(-5)}}))
check("3 a pick-up mark of the last hour does not hold the hand-on back (an hour of nudging that did nothing, the item goes on)", th(0) == ["a1"] and mover_of(1) == "a-back")

# ================================================================ 4. what is never handed on
def stays(label, extra=None, states=None, **put_kw):
    wipe(); put(1, **{"act": 120, **put_kw}); before = rd(1)
    got = th(0, states)
    ok = got == [] and untouched(1, before) and not to("a-back") and not to("a-aide")
    check(f"4 {label}: nothing is handed", ok, (got, sent))
stays("the owner's step first", nxt="Oliver: approve it")
stays("a step that names nobody (his, as the model reads it)", nxt="approve it")
stays("another session's step first", nxt="a-aide: look at it")
stays("the owner's step before the agent's own", nxt="Oliver: approve it\na-main: then ship it")
stays("another session's step before the agent's own", nxt="a-aide: look\na-main: then ship it")
stays("no step at all", nxt="")
future_day = time.strftime("%Y-%m-%d", time.gmtime(now0 + 40 * 86400))
future_at = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 40 * 86400))
for label, extra in [("a hold with no date", dict(hold=True)), ("a hold until a dated wake", dict(hold=True, wake=future_at)), ("an until", dict(until=future_day)), ("an anchor wait", dict(wait_kind="anchor", wait_anchor="https://example.invalid/pr/1", until=future_day)),
                     ("a relay wait", dict(wait_kind="relay")), ("a parked item", dict(state="parked", hold=True, wake=future_at)), ("a wait on a decision", dict(state="your-call", needs=["decision"], ask="pick one")),
                     ("the owner as the mover", dict(mover="Oliver", state="your-step"))]:
    stays(label, **extra)
wipe(); put(2, act=1); put(1, act=120, state="blocked", supplies="its output", after=["a2"]); before = rd(1)
check("4 an item behind an open one (after): nothing is handed", th(0) == [] and untouched(1, before))
stays("a closed item", status="completed", outcome="done")
stays("the front agent in a turn", states={"a-main": "busy"})
stays("the front agent's state unknown", states={"a-main": "unknown"})
stays("the front agent's state not read", states={"a-main": "unread"})
stays("the front agent missing from the snapshot", states={"a-main": None})
stays("the front agent's pane reading shell (a line to it is queued, not a turn)", states={"a-main": "shell"})
stays("the front agent's pane reading sleeping", states={"a-main": "sleeping"})
stays("a background agent's own step (not this rule's: a front agent's only)", mover="a-back", nxt="a-back: build it")
stays("the project's keeper, which is no front agent of it", mover="a-keep", nxt="a-keep: ship it", states={"a-keep": "idle"})
stays("a name no page lists", mover="ghost", nxt="ghost: ship it", states={"ghost": "idle"})
stays("a front agent of another project than the item's", mover="b-main", nxt="b-main: ship it")
stays("44 minutes of quiet (the first hourly line's own threshold is 45)", act=44)
wipe(); put(1, act=45)
check("4 …45 minutes are enough (the control)", th(0) == ["a1"] and mover_of(1) == "a-back")
wipe(); put(1, act=120)
check("4 the same item with none of those is handed on (the control)", th(0) == ["a1"] and mover_of(1) == "a-back")
wipe(); put(1, act=120, nxt="a-main: first thing\nOliver: approve\na-main: last thing")
check("4 the agent's own steps first and the owner's behind them: handed on (the steps stay as they were)", th(0) == ["a1"] and mt(1)["next"] == "a-main: first thing\nOliver: approve\na-main: last thing")

# ================================================================ 5. the owner in that conversation
wipe(); put(1, act=120); stamp("a-main", 5); before = rd(1)
check("5 his last prompt in that pane 5 minutes ago (found by the pane's session id in the fleet's index): nothing is handed, nothing is started", tick2(0, present=None) == ([], []) and untouched(1, before) and sent == [])
stamp("a-main", telling.presence_minutes() + 1)
check("5 …older than the presence window: handed", th(1, present=None) == ["a1"])
wipe(); put(1, act=120); stamp("b-main", 2)
check("5 a fresh stamp of another pane does not matter", th(0, present=None) == ["a1"])
wipe(); put(1, act=120); stamp("a-main", -1)
check("5 a stamp dated a minute ahead of the clock is the owner just now: present", th(0, present=None) == [] and sent == [])
wipe(); put(1, act=120); stamp("a-main", 5)
check("5 the present test it is given decides (present: nothing; absent: handed, whatever the stamp says)", th(0, present=lambda w: True) == [] and th(1, present=lambda w: False) == ["a1"])
class PartialIdx(dict):
    unreadable = ["b"]
wipe(); put(1, act=120); before = rd(1)
_fleet_sessions_registry._sessions_index = lambda: PartialIdx({u: {"name": n} for n, u in U.items()})
with _Err() as e5:
    try: got5 = th(0, present=None)
    finally: _fleet_sessions_registry._sessions_index = real_index
check("5 a partial fleet index (a machine's sessions.json not read) hands nothing on, one line says so: the owner may be typing on that machine", got5 == [] and untouched(1, before) and len(e5.handon_lines) == 1 and "partial" in e5.text, (got5, e5.text))
import shutil
wipe(); put(1, act=120); shutil.rmtree(stamps_dir())
with _Err() as e5b:
    got5b = th(0, present=None)
stamps_dir().mkdir()
check("5 a stamp folder that cannot be read hands nothing on, one line says so", got5b == [] and len(e5b.handon_lines) == 1, (got5b, e5b.text))
def boom_index(): raise OSError("the fleet index is unreadable")
wipe(); put(1, act=120); _fleet_sessions_registry._sessions_index = boom_index
with _Err() as e5c:
    try: got5c = th(0, present=None)
    finally: _fleet_sessions_registry._sessions_index = real_index
check("5 …and so does a fleet index that cannot be read", got5c == [] and len(e5c.handon_lines) == 1, (got5c, e5c.text))
def boom_present(who): raise OSError("stamp unreadable")
wipe(); put(1, act=120)
check("5 a presence test that raises for the agent reads as no hand-on", th(0, present=boom_present) == [] and sent == [])
wipe(); put(1, act=120)
real_present = audit_ticks_svc._front_turn.present
audit_ticks_svc._front_turn.present = lambda who: True
try: got5d = th(0, present=None)
finally: audit_ticks_svc._front_turn.present = real_present
check("5 the notices' own presence test (front_turn.present) saying present hands nothing on either", got5d == [])

# ================================================================ 6. one action per item per tick, and the order
wipe(); put(1, act=60); put(2, mover="b-main", project="projects/beta", act=60, nxt="b-main: ship it")
got = tick2(0, {"b-back": "busy", "b-aide": "busy"})
check("6 an item with a free builder is handed on and an item with none is the pick-up's, in one tick: each gets one action", got == (["a1"], ["a2"]) and len(to("a-back")) == 1 and to("a-back")[0][3] == "handoff" and len(to("b-main")) == 1 and to("b-main")[0][3] == "stall" and to("a-main") == [], (got, sent))
check("6 …the handed item has no pick-up mark, the other has", marks() == {"a2": at(0)} and mover_of(1) == "a-back" and mover_of(2) == "b-main")
def failed_write_probe():
    wipe(); put(1, act=60); before = rd(1)
    handoff_svc.handoff_exec = lambda *a, **k: []
    try: got_ = tick2(0)
    finally: handoff_svc.handoff_exec = real_exec
    return got_ == ([], []) and untouched(1, before) and sent == [] and marks() == {}
rule("6 a hand-on whose write did not go through leaves the item as it was and the pick-up does NOT start the front agent's turn for it in the same tick (never both on one item)", failed_write_probe,
     [(audit_ticks_svc, "_front_pickup_tick", lambda *a, skip=(), **k: real_pickup(*a, **k))])
wipe(); put(1, act=60); before = rd(1)
def raising_exec(*a, **k): raise RuntimeError("the hand-off pass failed")
handoff_svc.handoff_exec = raising_exec
with _Err() as e6:
    try: got6 = tick2(0)
    finally: handoff_svc.handoff_exec = real_exec
check("6 a hand-on that raises: one line, the item untouched, and the pick-up still leaves it alone at that tick", got6 == ([], []) and untouched(1, before) and len(e6.handon_lines) == 1 and sent == [], (got6, e6.text))
check("6 …the next tick hands it on", th(10) == ["a1"])
wipe(); put(1, act=60); before = rd(1)
real_due = FH.due; calls6 = []
def due_once(*a, **k):
    calls6.append(1)
    return real_due(*a, **k) if len(calls6) == 1 else None      # the pass found it due; under the lock the item is no longer due
FH.due = due_once
try: got6b = tick2(0)
finally: FH.due = real_due
check("6 an item that is no longer due when the lock is held (the recheck says no) is not handed on, and the pick-up leaves it for the next tick", got6b == ([], []) and untouched(1, before) and sent == [], got6b)
# the audit tick: the order and what it passes on
order = []; seen = {}
real_hi, real_bt, real_hl = audit_ticks_svc._hand_idle_tick, audit_ticks_svc._busy_tell_tick, audit_ticks_svc._hourly_tick
audit_ticks_svc._hourly_tick = lambda *a, **k: order.append("hourly") or []
audit_ticks_svc._hand_idle_tick = lambda *a, **k: order.append("hand_idle") or []
def fake_handon(*a, acted=None, **k): order.append("handon"); acted.add("a77"); return []
def fake_pickup(*a, skip=(), **k): order.append("pickup"); seen["skip"] = set(skip); return []
audit_ticks_svc._front_handon_tick, audit_ticks_svc._front_pickup_tick = fake_handon, fake_pickup
audit_ticks_svc._busy_tell_tick = lambda *a, **k: order.append("busy_tell") or []
try: audit_ticks_svc._silence_tick()
finally:
    audit_ticks_svc._hourly_tick, audit_ticks_svc._hand_idle_tick, audit_ticks_svc._busy_tell_tick = real_hl, real_hi, real_bt
    audit_ticks_svc._front_handon_tick, audit_ticks_svc._front_pickup_tick = real_handon, real_pickup
check("6 the audit tick runs the hand-on after the idle hand-over and before the pick-up, then the busy tell; the items the hand-on acted on are the pick-up's `skip`", order == ["hourly", "hand_idle", "handon", "pickup", "busy_tell"] and seen.get("skip") == {"a77"}, (order, seen))
def raising_handon(*a, **k): raise RuntimeError("the hand-on failed")
order.clear()
audit_ticks_svc._hourly_tick = lambda *a, **k: order.append("hourly") or []
audit_ticks_svc._hand_idle_tick = lambda *a, **k: order.append("hand_idle") or []
audit_ticks_svc._front_handon_tick = raising_handon
audit_ticks_svc._front_pickup_tick = fake_pickup
audit_ticks_svc._busy_tell_tick = lambda *a, **k: order.append("busy_tell") or []
with _Err() as e6c:
    try: audit_ticks_svc._silence_tick()
    finally:
        audit_ticks_svc._hourly_tick, audit_ticks_svc._hand_idle_tick, audit_ticks_svc._busy_tell_tick = real_hl, real_hi, real_bt
        audit_ticks_svc._front_handon_tick, audit_ticks_svc._front_pickup_tick = real_handon, real_pickup
check("6 a hand-on that raises stops nothing after it (one line), and the pick-up runs with an empty skip", order == ["hourly", "hand_idle", "pickup", "busy_tell"] and seen.get("skip") == set() and "not handed on" in e6c.text, (order, seen, e6c.text))
# end to end through the real audit tick: the snapshot as the route stores it
def e2e(free, write_fails=False):
    wipe(); put(1, act=60)
    body = snap(time.time(), {} if free else both_busy()); code, _resp = agent_state_svc.post("machine-a", body)
    assert code == 200
    stubs = [(audit_ticks_svc, "_hourly_tick", lambda *a, **k: []), (audit_ticks_svc, "_hand_idle_tick", lambda *a, **k: []), (audit_ticks_svc, "_busy_tell_tick", lambda *a, **k: [])]
    if write_fails: stubs.append((handoff_svc, "handoff_exec", lambda *a, **k: []))
    return mutated(stubs, audit_ticks_svc._silence_tick)
e2e(True)
check("6 the real audit tick, a free builder in the snapshot: the item is handed on, the front agent is not nudged", mover_of(1) == "a-back" and to("a-main") == [] and len(to("a-back")) == 1, sent)
e2e(False)
check("6 …no builder free: the front agent's turn is started instead", mover_of(1) == "a-main" and len(to("a-main")) == 1 and to("a-main")[0][3] == "stall" and to("a-back") == [], sent)
def e2e_probe_no_both():
    e2e(True, write_fails=True)
    return mover_of(1) == "a-main" and sent == []
rule("6 the real audit tick, a free builder whose hand-on write fails: the front agent's turn is NOT started either (never both)", e2e_probe_no_both, [(audit_ticks_svc, "_front_handon_tick", lambda now=None, items=None, env=None, snap=None, front=None, present=None, dead=None, acted=None: real_handon(now=now, items=items, env=env, snap=snap, front=front, present=present, dead=dead))])
def e2e_probe_order():
    e2e(True)
    return to("a-main") == [] and mover_of(1) == "a-back"
def pickup_first(**k):
    real_pickup(); return real_handon(**k)
rule("6 the real audit tick hands on before it picks up: the front agent is not nudged for an item that went to a builder", e2e_probe_order, [(audit_ticks_svc, "_front_handon_tick", pickup_first)])

# ================================================================ 7. no loop, once a day
wipe(); put(1, act=60); th(0)
check("7 a handed item is not handed again: its mover is a background agent, outside this rule (10 minutes, an hour, a day later)", th(10) == [] and th(70) == [] and th(24 * 60 + 10) == [] and mover_of(1) == "a-back" and len(to("a-back")) == 1, sent)
wipe(); put(1, act=60); th(0)
put(1, mover="a-back", act=60, nxt="a-back: do the thing", needs=["a-back", "a-main"], hand_idle={"handed_at": at(0), "from": "a-main", "to": "a-back"})
check("7 …even when its step is reworded to the new mover and the item goes quiet again: no front agent moves it, nothing is handed or started", tick2(100) == ([], []))
wipe(); put(1, act=120, hand_idle={"handed_at": at(-30), "from": "a-main", "to": "a-back"}); before = rd(1)
check("7 an item that came back to a front agent within a day of being handed on (a hand-back) is not handed on again at once, and the pick-up has it", tick2(0) == ([], ["a1"]) and untouched(1, before))
check("7 …23 hours 59 minutes after the hand-on it is still not handed, and 24 hours after it is", th(1409) == [] and th(1410) == ["a1"] and mt(1)["hand_idle"]["handed_at"] == at(1410))
for label, rec in (("a handed_at that is no number", {"handed_at": "yesterday"}), ("a boolean", {"handed_at": True}), ("one dated ahead of the clock", {"handed_at": now0 + 5 * H}), ("a record that is no record", "x")):
    wipe(); put(1, act=120, hand_idle=rec)
    check(f"7 a hand_idle stamp that is {label} is no signal: handed on", th(0) == ["a1"], rec)
def loop_probe():
    wipe(); put(1, act=120, hand_idle={"handed_at": at(-30), "from": "a-main", "to": "a-back"}); before = rd(1)
    return th(0) == [] and untouched(1, before)
rule("7 the loop guard: the hand-over's own 24-hour guard holds an item that came back", loop_probe, [(HI, "handed_recently", lambda meta, now: False)])
def back_agent_probe():
    wipe(); put(1, mover="a-back", act=120, nxt="a-back: build it"); before = rd(1)
    return th(0) == [] and untouched(1, before) and sent == []
rule("7 the loop guard: a background agent's own step is never handed on by this rule (so a back agent hands nothing to a front agent and back)", back_agent_probe, [(audit_ticks_svc, "_front_of_project", lambda who, project: True)])

# ================================================================ 8. a write that fails
wipe(); put(1, act=60); raw = (T / "store/a/1.json").read_bytes()
real_save = _writes_svc.save
def save_fails(*a, **k): raise OSError("disk full")
_writes_svc.save = save_fails
with _Err() as e8:
    try: got8 = th(0)
    finally: _writes_svc.save = real_save
check("8 a write that fails hands nothing on: the file is byte for byte what it was, no hand-over mark, nobody told", got8 == [] and (T / "store/a/1.json").read_bytes() == raw and "hand_idle" not in mt(1) and sent == [], (got8, sent))
check("8 …the failure is one line, and the next tick (the write working) hands it on and sets the mark", "failed" in e8.text and th(10) == ["a1"] and mt(1)["hand_idle"]["handed_at"] == at(10))

# ================================================================ 9. the cap
wipe()
for i, p in enumerate("abcd", 1): put(i, mover=f"{p}-main", project=PROJ[p], act=120, nxt=f"{p}-main: ship it")
put(5, act=120, nxt="a-main: and another"); put(6, mover="b-main", project="projects/beta", act=120, nxt="b-main: and another")
t1 = th(0)
check("9 six items due, each with a free background agent: three are handed in a tick, in id order", t1 == ["a1", "a2", "a3"] and HI.MAX_PER_TICK == 3, t1)
t2 = th(10)
check("9 the next tick takes the rest (a builder that took an item is no longer free: the item of the same project goes to its other agent)", t2 == ["a4", "a5", "a6"] and mover_of(5) == "a-aide" and mover_of(6) == "b-aide", (t2, mover_of(5), mover_of(6)))

# ================================================================ 10. reads that fail
wipe(); put(1, act=120); before = rd(1)
real_snap = AS.snapshot
def boom_snap(): raise OSError("agent-state.json is unreadable")
AS.snapshot = boom_snap
with _Err() as e10:
    try: got10 = audit_ticks_svc._front_handon_tick(now=at(0), present=NOT_THERE)
    finally: AS.snapshot = real_snap
check("10 a snapshot that cannot be read hands nothing on, one line", got10 == [] and untouched(1, before) and len(e10.handon_lines) == 1, e10.text)
def boom_front(who, project): raise RuntimeError("roles unreadable")
check("10 a role map that cannot be read hands nothing on", th(0, front=boom_front) == [] and untouched(1, before))
real_reader = audit_ticks_svc._owner_present_reader
def boom_reader(now): raise OSError("stamps unreadable")
audit_ticks_svc._owner_present_reader = boom_reader
with _Err() as e10b:
    try: got10b = audit_ticks_svc._front_handon_tick(now=at(0), snap=snap(at(0)))
    finally: audit_ticks_svc._owner_present_reader = real_reader
check("10 a presence reader that cannot read hands nothing on, one line", got10b == [] and untouched(1, before) and len(e10b.handon_lines) == 1, e10b.text)
_fleet_sessions_registry._sessions_index = boom_index
with _Err() as e10c:
    try: got10c = th(0, front=lambda who, project: who == "a-main")
    finally: _fleet_sessions_registry._sessions_index = real_index
check("10 a fleet index that cannot be read (whether a name may have a pane is not known): nothing is handed on, one line", got10c == [] and untouched(1, before) and len(e10c.handon_lines) == 1, e10c.text)
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
real_run = FP.own_run
def own_run_bad(meta, mover, same):
    if mover == "a-main": raise ValueError("a step list that cannot be read")
    return real_run(meta, mover, same)
FP.own_run = own_run_bad
with _Err() as e10d:
    try: got10d = th(0)
    finally: FP.own_run = real_run
check("10 one item that cannot be read is left alone and stops no other: one line names it", got10d == ["a2"] and len(e10d.handon_lines) == 1 and "a1 not read" in e10d.handon_lines[0], (got10d, e10d.text))
wipe(); put(1, act=120)
real_builders = audit_ticks_svc._hand_idle_builders
def boom_builders(project): raise RuntimeError("the role map is unreadable")
audit_ticks_svc._hand_idle_builders = boom_builders
with _Err() as e10e:
    try: got10e = tick2(0)
    finally: audit_ticks_svc._hand_idle_builders = real_builders
check("10 a background-agent lookup that fails hands nothing on and leaves the item alone for that tick (one line)", got10e == ([], []) and len(e10e.handon_lines) == 1 and mover_of(1) == "a-main", (got10e, e10e.text))

# ================================================================ 11. the switches
wipe(); put(1, act=120); _cfg.CFG["audit"]["hourly_line"] = False
check("11 with the hourly line off the hand-on stands still", th(0) == [] and mover_of(1) == "a-main")
wipe(); put(1, act=120); _cfg.CFG["audit"]["hand_idle"] = False
got11 = tick2(0)
check("11 with the idle hand-over off the hand-on stands still (it is that pass's own move) and the pick-up has the item", got11 == ([], ["a1"]) and mover_of(1) == "a-main", got11)
wipe(); put(1, act=120)
real_ro = _ro.is_read_only; _ro.is_read_only = lambda: True
try: got11 = th(0)
finally: _ro.is_read_only = real_ro
check("11 a read-only standby copy hands nothing on", got11 == [] and mover_of(1) == "a-main")
real_paused = handoff_svc.handoff_paused; handoff_svc.handoff_paused = lambda: True
try: got11 = th(0)
finally: handoff_svc.handoff_paused = real_paused
check("11 a paused board hands nothing on", got11 == [] and mover_of(1) == "a-main")
wipe(); put(1, act=120); _cfg.CFG["audit"]["mode"] = "agent"
audit_ticks_svc._silence_tick()
_cfg.CFG["audit"]["mode"] = "script"
check("11 the audit tick in agent mode does nothing at all", sent == [] and mover_of(1) == "a-main")

# ================================================================ 12. the other passes win
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
real_hi_due, real_bt_due = HI.due_all, BT.due_all
HI.due_all = lambda items, now, front=None: [("a1", {"mover": "a-main", "project": "projects/alpha", "line_at": now, "told_none": False})]
try: got12 = th(0)
finally: HI.due_all = real_hi_due
check("12 an item the idle hand-over acts on at this tick is not handed on by this pass (another item is)", got12 == ["a2"] and mover_of(1) == "a-main", got12)
wipe(); put(1, act=120); put(2, mover="b-main", project="projects/beta", act=120, nxt="b-main: ship it")
BT.due_all = lambda items, now, front, queued, hours: [("a1", {"kind": "front"})]
try: got12 = th(0)
finally: BT.due_all = real_bt_due
check("12 …and so for the busy-stretch tell", got12 == ["a2"] and mover_of(1) == "a-main", got12)

# ================================================================ 13. the writer: the old mover stays named only when asked
def move(needs, frm, to_, keep, why="x"):
    it = {"gid": "a900", "status": "open", "subject": "s", "metadata": {"needs": list(needs), "mover": frm, "project": "projects/alpha"}}
    handoff_svc.handoff_write_move(it, HO.Step("move", "a900", why, frm, to_, via="orphan", keep_frm=keep), now0)
    return it["metadata"]
check("13 without keep_frm the old mover leaves needs (the idle hand-over as it was)", move(["a-main"], "a-main", "a-back", False)["needs"] == ["a-back"] and HO.Step("move", "a1", "w").keep_frm is False)
check("13 with keep_frm it stays named behind the new mover", move(["a-main"], "a-main", "a-back", True)["needs"] == ["a-back", "a-main"])
check("13 a kind in needs (decision) is kept, the old mover still named", set(move(["a-main", "decision"], "a-main", "a-back", True)["needs"]) == {"a-back", "a-main", "decision"})
check("13 the old mover is not named twice, nor the new one", move(["a-main", "a-back"], "a-main", "a-back", True)["needs"] == ["a-back", "a-main"])
check("13 the stored mover follows to the new mover", move(["a-main"], "a-main", "a-back", True).get("mover") == "a-back")

# ================================================================ 14. the checks above fail once the rule is reverted
def free_probe():
    wipe(); put(1, act=60); before = rd(1)
    got_ = tick2(0, both_busy())
    return got_ == ([], ["a1"]) and untouched(1, before)
rule("14 free test: a background agent in a turn is not handed an item", free_probe, [(HI, "pick_free", lambda cands, busy, status, dead, same, frm="": next((c for c in cands if c and not same(c, frm)), ""))])
def fresh_probe():
    wipe(); put(1, act=60); before = rd(1)
    got_ = tick2(0, {"a-main": "unknown", "a-back": "unknown", "a-aide": "unknown"})
    return got_ == ([], []) and untouched(1, before)
rule("14 idle-and-fresh test: an agent whose state the snapshot cannot give is neither idle nor free", fresh_probe, [(audit_ticks_svc, "_pane_idle", lambda who, now, snap: True)])
def own_step_probe():
    wipe(); put(1, act=120, nxt="Oliver: approve it"); before = rd(1)
    return th(0) == [] and untouched(1, before)
rule("14 own-step test: an item whose first open step is the owner's is not handed on", own_step_probe, [(FP, "own_run", lambda meta, mover, same: ["x"])])
def present_probe():
    wipe(); put(1, act=120); stamp("a-main", 5); before = rd(1)
    return th(0, present=None) == [] and untouched(1, before)
rule("14 owner-present test: an item whose front agent the owner is typing to is not handed on", present_probe, [(audit_ticks_svc, "_owner_present_reader", lambda now: (lambda who: False))])
def partial_probe():
    wipe(); put(1, act=120); before = rd(1)
    _fleet_sessions_registry._sessions_index = lambda: PartialIdx({u: {"name": n} for n, u in U.items()})
    try: return th(0, present=None) == [] and untouched(1, before)
    finally: _fleet_sessions_registry._sessions_index = real_index
class _Never:
    def __get__(self, obj, typ=None): return []
rule("14 partial-index test: an index with an unreadable machine hands nothing on", partial_probe, [(PartialIdx, "unreadable", [])])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
