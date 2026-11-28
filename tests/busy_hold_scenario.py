"""Scenario test for the refusal of a hold on an item its mover is moving: its two proofs, the mover's running subagent and the release of a pull request tied to the item (stackshot/service/gates.py
`gate_busy_hold`, stackshot/audit/busy_hold.py, web/wiring.py's `_busy_live`, the update tool's write path) — a scratch store, fixture items, fake subagents, units and release logs, no server socket, no network, no
model call, no GitHub. The two parts share one instance config and one process (the second part starts from a fresh store and sets its own release units and repository); the final line is the sum of the two.

Part 1, hold — the refusal on a running subagent of the item's mover:

A hold says nothing happens on the item until a date or a reply, which is false while a subagent of the item's mover builds it. The update tool refuses a hold (or a date alone, which the write turns into a
hold) from the item's mover while a running subagent of that mover is tied to THIS item (its description, else its brief, names the item or a pull request anchored to it, read against the mover's other open
items as the hourly audit reads it). Unknown is never a refusal.

  1  refuses     a tied live subagent (by the item's id, by an anchored pull request, by its brief when the description names none) refuses a hold and a date alone; the text names the subagent, tells the mover to
                 keep the item in hand with work=, and carries no id of another item
  2  passes      a subagent tied to ANOTHER item of the mover, none running, a read that is Unreadable or raises, a subagent entry the sender could not read, a running subagent that names no item, a sender that
                 is not the mover, the owner, the guard off, a closing write, done=, a clear_* of the park, a named blocker (wait_kind, after, needs, ask_by), a hand-off to another session, an item that is
                 not open, an item with no mover, no live callable at all
  3  tool        through the real update tool and the server's own wiring (web/wiring.py: `wiring._busy_live`, `audit_ticks._mover_subagents` replaced by a fake): the refused hold stores nothing; the same write passes once the
                 subagent has ended, and a status with work= passes while it runs; the anchors the server reads are the ones that tie
  4  shape       the gate is called from the update tool before the item lock and after gate_self_wait, takes its proof as a callable, gates.py imports no audit/ module, the config switch reads live
  5  text        the update tool's text no longer calls the mover's own release or run a wait to park

Part 2, release — the second proof, a release of a pull request tied to the item that is running (stackshot/audit/busy_hold.py `live_release`, stackshot/service/gates.py `gate_busy_hold` and
`BUSY_RELEASE_REFUSAL`, web/wiring.py's `_busy_live`):

release.sh runs each release as the user unit stackshot-release-<n>.service, which stays active through the checks, the merge queue, the merge, the deploy and main's run. A hold from the item's mover is refused while
the unit of a pull request TIED TO THIS ITEM is active and its log (<state>/releases/pr-<n>.log) was written within 15 minutes; an older log is a stuck release, and a mover is never trapped. Unknown is never a refusal.

  1  refuses     the unit of a pull request the item is tied to by an anchor, by an open step's URL, by `PR #n` in a step, by a step's stored proof, or by the status line of an open step refuses a hold and a date
                 alone; the text names the release, the unit, the log's age and its stage, and tells the mover to keep the item in hand or wait on the event by name; the stage is read from the log's own lines
  2  ties        what does NOT tie: another item's pull request, an anchored pull request with no unit, a unit of another repository's pull request with the same number, a pull request the item does not name
  3  passes      no unit, a unit read that raises, a log older than 15 minutes (the bound itself included), no log, a log that cannot be read, no own repository, anchors or an item that cannot be read; the same
                 early exits as the subagent proof: guard off, the owner, a sender that is not the mover, a closing write, done=, clear_*, a named blocker, a hand-off, an item that is not open, no `live`
  4  both arms   a subagent live OR a release live refuses (the subagent is named first), neither passes; a failing subagent read still lets the release arm speak
  5  tool        through the real update tool and `wiring._busy_live` (the unit list, the anchors and the logs read as the server reads them): the refused hold stores nothing, the same write passes once the unit
                 has ended or its log has gone quiet, work= passes; the reply note of a doing item is dropped while a tied release runs and stays when it does not
  6  shape       the log is never read while no unit runs, the check costs one unit read and the item, gates.py names no audit/ module, the text of the refusal

    tests/run-suite busy_hold        -> exit 0 / 1"""
import contextlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="busy-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other"), 1)}
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "the back"}, "back_agents": {"marsh-builder": "the back"}}}}))
(T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: the back\n---\n\n# Quill\n")
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
fails = []; ran = []; PARTS = []; PART = ["hold"]
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL [{PART[0]}] {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.audit import busy_hold, subagent_tie
from stackshot.core import config as _cfg
from stackshot.web import server
from stackshot.web import wiring    # `_busy_live` is web/wiring.py's
from stackshot.service import released_live as _rlive, store as _svcstore, handoff as _handoff_svc
from stackshot.web import publish as _web_publish
from stackshot.service import audit_ticks as audit_ticks_svc, gates, telling, update as update_svc
from stackshot.tools import next_report as _nr
from stackshot.web.tools import update as _wt_update
from stackshot.web.ui import releasing as _rel
from stackshot.waits import self_wait as _selfwait
from stackshot.model import steps as _steps      # part 2's
_selfwait._run = lambda message: {"status": "ok", "text": json.dumps({"can_do_now": False, "reason": "the soak window has to end first"})}      # the self-wait check judges a wait_reason: never a real model call here, and the answer is no, so the busy refusal is what the call meets
SOAK = "the soak window has to end before the part can be applied"      # a wait on the sender's own item names its reason, so a bare until reaches the busy gate (which runs after the self-wait check)
_rel._run = lambda argv: ""      # the second proof (a release of a pull request tied to the item, part 2 below) reads the release units: here none runs, never the host's

@contextlib.contextmanager
def patched(owner, **kv):
    """Names of a module replaced for a case, put back after."""
    old = {k: getattr(owner, k) for k in kv}
    for k, v in kv.items(): setattr(owner, k, v)
    try: yield
    finally:
        for k, v in old.items(): setattr(owner, k, v)
@contextlib.contextmanager
def cfg_model(**kv):
    """[model] keys set for a case (the config is read live), put back after."""
    m = _cfg.CFG.setdefault("model", {}); old = {k: m.get(k, "<absent>") for k in kv}
    m.update(kv)
    try: yield
    finally:
        for k, v in old.items():
            if v == "<absent>": m.pop(k, None)
            else: m[k] = v
def outcome(thunk):
    try: return ("ok", thunk())
    except ToolError as e: return ("refused", str(e))
    except Exception as e: return ("raised", f"{e.__class__.__name__}: {e}")

NOW = time.time()
OWNER = "Oliver"; BACK = "marsh-builder"; OTHER = "home-other"; PROJECT = "projects/quill"
import datetime as dt
FUT = (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
def put(i, status="open", **meta):
    it = {"id": str(i), "gid": f"a{i}", "subject": f"[home] item {i}", "description": "- A thing", "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
          "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
    return it
def read(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))
put(1, mover=BACK)                      # the item the cases hold
put(2, mover=BACK)                      # another open item of the same mover
put(3, mover=OTHER)                     # an item another session moves
put(4, status="completed", mover=BACK, outcome="done")
put(5, mover=BACK)
put(6, mover=BACK)

BOARD = "board" + chr(35)                                          # the board's id form, written out here so no literal id sits in the file: "@3" in a string below is item 3's shown id
def X(t): return re.sub(r"@(\d+)", lambda m: BOARD + m.group(1), t)
def sub(desc, brief="", **kw):
    desc, brief = X(desc), X(brief)
    return {"id": "x1", "description": desc, "brief": brief, "text": f"{desc}\n{brief}", "at": NOW, **kw}
def live_for(subs=None, raises=None, anch=None, items=None):
    """The gate's `live` callable as the server builds it (audit/busy_hold.py), over the scratch store and a fake `subagents`."""
    def live(gid, mover):
        return busy_hold.live_work(gid, mover, subagents=(lambda who: (_ for _ in ()).throw(raises)) if raises is not None else (lambda who: subs if who == BACK else []),
                                   items=items or (lambda: _nr.load_all(None)), anchored=lambda: anch or {}, same=_handoff_svc.ho_same, shown=_nr.shown)
    return live
def gate(live, sender=BACK, gid="a1", **kw):
    kw.setdefault("hold", True)
    return outcome(lambda: gates.gate_busy_hold(gid, sender, live=live, **kw))
def refused(got): return got[0] == "refused" and got[1].startswith("Refused: this item is being moved now: ")

BUILD = [sub("Build @1: the export fix")]
# ---------------------------------------------------------------- 1. refuses
got = gate(live_for(BUILD))
check("1 a running subagent whose description names the item refuses a hold from its mover, naming the subagent", refused(got) and X('your subagent "Build @1: the export fix"') in got[1], got)
check("1 …the refusal says to keep it in hand with work= and to park only once nothing of the mover's runs on it",
      "work=" in got[1] and "Keep it in hand" in got[1] and "Park it only once nothing of yours is running on it." in got[1], got)
check("1 …and it names no item of the board but what the subagent's own description says", not re.search(r"\b(?:" + BOARD + r"\d+|a\d+)\b", got[1].replace(BOARD + "1", "")), got)
check("1 the item's id is read whole: a subagent on item 10 or 12 is not on item 1", not refused(gate(live_for([sub("Build @10"), sub("Fix @12: a thing")]))), gate(live_for([sub("Build @10")])))
a_pr = {"a1": {"acme/stack#77"}}
got = gate(live_for([sub("Build the export fix, PR 77")], anch=a_pr))
check("1 a subagent that names a pull request anchored to the item (PR 77) refuses, naming the subagent", refused(got) and 'your subagent "Build the export fix, PR 77"' in got[1], got)
got = gate(live_for([sub("Fix it", brief="Work on https://github.com/acme/stack/pull/77 and report")], anch=a_pr))
check("1 …by the pull request's URL in its brief, when the description names none", refused(got) and 'your subagent "Fix it"' in got[1], got)
check("1 …but a pull request that is anchored to no item of the mover ties nothing", not refused(gate(live_for([sub("Build the export fix, PR 78")], anch=a_pr))), gate(live_for([sub("PR 78")], anch=a_pr)))
check("1 a brief that names the item ties the subagent when its description names none of the mover's items", refused(gate(live_for([sub("Build part D", brief="the work of @1")]))))
got = gate(live_for([sub("Build part D", brief="the work of @1")]))
check("1 …and the words of the refusal are the description (the brief is not quoted)", 'your subagent "Build part D"' in got[1] and "work of" not in got[1], got)
check("1 a subagent flagged quiet (the sender says it runs but has written nothing lately) still counts", refused(gate(live_for([sub("Build @1", quiet=True)]))))
check("1 a date alone is a wait the write turns into a hold: a wake or an until from the mover is refused too", refused(gate(live_for(BUILD), hold=False, wake=FUT)), gate(live_for(BUILD), hold=False, wake=FUT))
check("1 a hold with a wake and a reason is the case: refused", refused(gate(live_for(BUILD), wake=FUT)))
put(5, mover=BACK, hold=True)
check("1 a hold on an item already on hold is refused again (the write sets the hold)", refused(gate(live_for([sub("Build @5")]), gid="a5")), gate(live_for([sub("Build @5")]), gid="a5"))
put(5, mover=BACK)
check("1 a very long description is clipped, one line", len(gate(live_for([sub("Build @1 " + "x " * 300)]))[1]) < 600, len(gate(live_for([sub("Build @1 " + "x " * 300)]))[1]))
check("1 a subagent with no description is still named (by its brief)", 'your subagent is running' in gate(live_for([sub("", brief="the work of @1")]))[1], gate(live_for([sub("", brief="the work of @1")])))
check("1 the first of several subagents that is tied is the one named", X('your subagent "Build @1 (second)"') in gate(live_for([sub("Another item, @2"), sub("Build @1 (second)")]))[1])

# ---------------------------------------------------------------- 2. passes
ok = lambda got: got == ("ok", None)
check("2 a subagent tied to ANOTHER item of the mover (@2) leaves this item's hold alone", ok(gate(live_for([sub("Build @2: the other fix")]))), gate(live_for([sub("Build @2")])))
check("2 …even when its brief mentions this item (a description that names another item is what it works on)", ok(gate(live_for([sub("Build @2", brief="a follow-up of @1")]))), gate(live_for([sub("Build @2", brief="a follow-up of @1")])))
check("2 a closed item of the mover is no candidate: a subagent whose description names it and whose brief names this item is on this item", refused(gate(live_for([sub("Close-out notes for @4", brief="the work of @1")]))), gate(live_for([sub("Close-out notes for @4", brief="the work of @1")])))
check("2 a read that holds something that is no subagent (None, a string) beside a real one still finds the real one", refused(gate(live_for([None, "x", sub("Build @1")]))), gate(live_for([None, "x", sub("Build @1")])))
check("2 a subagent tied to an item of ANOTHER mover (@3: not the mover's) names no item of this mover: no refusal", ok(gate(live_for([sub("Build @3")]))), gate(live_for([sub("Build @3")])))
check("2 no subagent running passes", ok(gate(live_for([]))))
check("2 a subagent that names no item and no pull request is unknown, never a refusal", ok(gate(live_for([sub("Build part D")]))))
check("2 a subagent entry the sender could not read (listed with no words) passes", ok(gate(live_for([{"id": "x2", "text": "", "at": 0.0, "unreadable": True}]))))
check("2 an Unreadable read (no fresh agent-state snapshot, or none that names the mover) passes", ok(gate(live_for(raises=subagent_tie.Unreadable("no fresh agent-state snapshot names the agent")))))
check("2 any other error of the read passes, and so does a failure of the check itself", ok(gate(live_for(raises=RuntimeError("boom")))) and ok(gate(live_for(BUILD, items=lambda: 1 / 0))))
check("2 a `live` that raises passes the write", ok(gate(lambda g, w: 1 / 0)))
check("2 no `live` callable at all (an app built without one) passes", ok(gate(None)))
check("2 a sender that is not the item's mover is not refused (item 3's mover is another session)", ok(gate(live_for(BUILD), sender=BACK, gid="a3")), gate(live_for(BUILD), sender=BACK, gid="a3"))
check("2 …nor the owner", ok(gate(live_for(BUILD), sender=OWNER)), gate(live_for(BUILD), sender=OWNER))
check("2 …nor a write that names no sender", ok(gate(live_for(BUILD), sender="")))
with cfg_model(busy_hold_guard=False):
    off = gate(live_for(BUILD))
check("2 `[model] busy_hold_guard = false` switches the check off, read live (and back on after)", ok(off) and refused(gate(live_for(BUILD))), (off, gate(live_for(BUILD))))
with cfg_model(busy_hold_guard="off"):
    check("2 …the words off, no and 0 switch it off too", ok(gate(live_for(BUILD))))
check("2 …and the default, with the key absent, is on", _cfg.CFG.get("model", {}).get("busy_hold_guard", True) in (True,) and _cfg.model_busy_hold_guard() is True)
check("2 a write that closes the item is not refused (status completed)", ok(gate(live_for(BUILD), status="completed")))
check("2 a write that ticks a step (done=) is not refused", ok(gate(live_for(BUILD), done=[1])) and ok(gate(live_for(BUILD), done="1")))
check("2 a write that drops the park is not a park (clear_hold, clear_wake, clear_wait)", all(ok(gate(live_for(BUILD), **{k: True})) for k in ("clear_hold", "clear_wake", "clear_wait")))
check("2 a write that is no hold and no date is not refused (a status, a step)", ok(gate(live_for(BUILD), hold=False)))
check("2 a wait that names its blocker is not refused: a wait_kind, an after link, needs, a relay's ask_by",
      ok(gate(live_for(BUILD), wait_kind="relay")) and ok(gate(live_for(BUILD), wait_kind="anchor")) and ok(gate(live_for(BUILD), after=["a2"])) and ok(gate(live_for(BUILD), needs=["external"])) and ok(gate(live_for(BUILD), ask_by=FUT)))
check("2 …a wait_kind of time is the plain park and is refused", refused(gate(live_for(BUILD), wait_kind="time")))
check("2 a date that is none (until=none) is no park", ok(gate(live_for(BUILD), hold=False, wake="none")))
check("2 a write that hands the item to another session (mover=<other>) is not the mover's hold", ok(gate(live_for(BUILD), mover=OTHER)))
check("2 …nor a next line that hands it on", ok(gate(live_for(BUILD), next_text=f"{OTHER}: take it from here")))
check("2 a next line of the mover's own steps does not lift the refusal", refused(gate(live_for(BUILD), next_text=f"{BACK}: write the tests")))
check("2 a completed item and an item that does not exist are not refused", ok(gate(live_for([sub("Build @4")]), gid="a4")) and ok(gate(live_for(BUILD), gid="a99999")))
put(7, mover=OWNER)
check("2 an item the owner moves is his: the hold is not refused", ok(gate(live_for([sub("Build @7")]), gid="a7")))

# ---------------------------------------------------------------- 3. tool
SUBS = []
def fake_server_subs(who, now=None, snap=None):
    if who != BACK: return []
    return SUBS
def update(i, **kw):
    kw.setdefault("sender", BACK)
    with patched(_web_publish, _publish=lambda *a, **k: None), patched(telling, tell_woken=lambda *a, **k: None):
        return outcome(lambda: _wt_update.stackshot_update(f"a{i}", **kw))
HOLD = dict(next=f"{BACK}: do it", wake=FUT, hold=True, wait_basis=f"the soak window ends {FUT}")
check("3 the server hands the update tool its proof (wiring._busy_live): the tool holds it, and it answers a string", callable(_wt_update._busy_live) and isinstance(_wt_update._busy_live("a1", BACK), str))
with patched(audit_ticks_svc, _mover_subagents=fake_server_subs):
    SUBS[:] = [sub("Build @1: the export fix")]
    before = json.dumps(read(1), sort_keys=True)
    got = update(1, **HOLD)
    check("3 a hold from the mover while its subagent builds the item is refused through the real tool", refused(got) and X('your subagent "Build @1: the export fix"') in got[1], got)
    check("3 …and the refused write stores nothing (the item is as it was)", json.dumps(read(1), sort_keys=True) == before and not read(1)["metadata"].get("until") and not read(1)["metadata"].get("hold"))
    got = update(1, sender=BACK, work={"text": "PR 77 up, subagent building", "state": "in progress"})
    check("3 …a status line with work= (keeping it in hand) goes through", got[0] == "ok", got)
    SUBS[:] = [sub("Build @2: the other fix")]
    got = update(1, **HOLD)
    check("3 a subagent that builds another item of the mover does not stop the hold (it is stored)", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    put(1, mover=BACK)
    SUBS[:] = []
    got = update(1, **HOLD)
    check("3 with nothing running the same hold passes and is stored", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    put(1, mover=BACK)
    SUBS[:] = [sub("Build @1")]
    got = update(1, **{**HOLD, "sender": OWNER})
    check("3 the owner's own hold on the item is not refused", got[0] == "ok" or not refused(got), got)
    put(1, mover=BACK)
    got = update(1, sender=OTHER, **{k: v for k, v in HOLD.items() if k != "next"})
    check("3 a hold from a session that is not the mover is not refused by this check", not refused(got), got)
    put(1, mover=BACK)
    with cfg_model(busy_hold_guard=False):
        got = update(1, **HOLD)
    check("3 with the switch off the hold is stored through the tool", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    put(1, mover=BACK)
    got = update(1, until=FUT, next=f"{BACK}: do it", wait_basis=f"the soak window ends {FUT}", wait_reason=SOAK)
    check("3 an until alone (a wait the write parks) is refused through the tool as a hold is", refused(got), got)
    got = update(1, **{**HOLD, "done": [1]})
    check("3 a hold written together with done= is not refused", not refused(got), got)
    put(1, mover=BACK)
    SUBS[:] = [sub("Build the export fix, PR 77")]
    with patched(_rlive, released_anchors=lambda: {"a1": {"acme/stack#77"}}):
        got = update(1, **HOLD)
    check("3 the anchors the server reads (released_anchors) are the ones that tie a subagent that names a pull request", refused(got) and "PR 77" in got[1], got)
    put(1, mover=BACK)
    with patched(_rlive, released_anchors=lambda: 1 / 0):
        got = update(1, **HOLD)
    check("3 anchors that cannot be read are unknown: the write passes", got[0] == "ok", got)
    put(1, mover=BACK)
with patched(audit_ticks_svc, _mover_subagents=lambda who, now=None, snap=None: (_ for _ in ()).throw(subagent_tie.Unreadable("no fresh agent-state snapshot names the agent"))):
    got = update(1, **HOLD)
    check("3 a mover whose subagents cannot be read (Unreadable) passes through the tool", got[0] == "ok", got)
put(1, mover=BACK)
check("3 the real proof (nothing replaced): a mover that no session index row names reads as unknown or idle, never a refusal", wiring._busy_live("a1", "nobody-here") == "")

# ---------------------------------------------------------------- 3b. the reply note
# A doing item whose next reads as a wait gets a reply note that says to park it (service/update.py `_doing_wait_note`). While a running subagent of the mover is tied to the item the wait wording is about the mover's own
# run, work in hand, and the note's advice is the hold the update refuses: the note is left off then. Unknown (an unreadable read, a failing proof) leaves the note as it is.
NOTE = "this item is doing, but its next reads as a wait"
WAITING_NEXT = f"{BACK}: the first nightly run ends overnight; record its counts and cost in the morning"
def doing(i): put(i, mover=BACK, needs=[BACK], state="doing")
def note_of(i, subs=None, raises=None, **kw):
    doing(i)
    def fake(who, now=None, snap=None):
        if raises is not None: raise raises
        return subs if (subs is not None and who == BACK) else []
    with patched(audit_ticks_svc, _mover_subagents=fake):
        got = update(i, next=WAITING_NEXT, **kw)
    return got
doing(8); base = update(8, next=WAITING_NEXT)
check("3b with no subagent running the doing item's wait wording draws the note, as before", base[0] == "ok" and base[1].count(NOTE) == 1, base)
got = note_of(8, [sub("Build @8: the overnight run")])
check("3b …no note while a running subagent of the mover is tied to the item (by its id); the write itself goes through", got[0] == "ok" and NOTE not in got[1] and "overnight" in read(8)["metadata"]["next"], got)
got = note_of(8, [sub("Build the overnight run, PR 90")])
check("3b …a subagent that names a pull request nothing anchors is not tied: the note stays", got[0] == "ok" and got[1].count(NOTE) == 1, got)
doing(8)
with patched(_rlive, released_anchors=lambda: {"a8": {"acme/stack#90"}}):
    got = note_of(8, [sub("Build the overnight run, PR 90")])
check("3b …tied by an anchored pull request (PR 90 anchored to the item): no note", got[0] == "ok" and NOTE not in got[1], got)
got = note_of(8, [sub("Build @2: the other fix")])
check("3b …a subagent tied to ANOTHER item of the mover leaves the note as it is", got[0] == "ok" and got[1].count(NOTE) == 1, got)
got = note_of(8, [sub("Build part D")])
check("3b …a running subagent that names no item leaves the note as it is (unknown is no reason to drop it)", got[0] == "ok" and got[1].count(NOTE) == 1, got)
got = note_of(8, raises=subagent_tie.Unreadable("no fresh agent-state snapshot names the agent"))
check("3b …an Unreadable read leaves the note as it is", got[0] == "ok" and got[1].count(NOTE) == 1, got)
got = note_of(8, raises=RuntimeError("boom"))
check("3b …any other failure of the read leaves the note as it is", got[0] == "ok" and got[1].count(NOTE) == 1, got)
with cfg_model(busy_hold_guard=False):
    got = note_of(8, [sub("Build @8: the overnight run")])
check("3b …with [model] busy_hold_guard off the note stays as it was", got[0] == "ok" and got[1].count(NOTE) == 1, got)
got = note_of(8, [sub("Build @8: the overnight run")])
check("3b …and the switch is read live: on again, no note", got[0] == "ok" and NOTE not in got[1], got)
# the note's own function: a busy answer that names a live thing drops it; none, an empty one (nothing running, or nothing could be told) leaves it
DN = lambda busy=None: update_svc._doing_wait_note({"state": "doing"}, "alpha-main: wait until 2099-03-02 for the vendor's reply", busy)
check("3b `_doing_wait_note`: no answer, an empty one: the note is made", all(NOTE in DN(b) for b in (None, "")), [DN(b)[:40] for b in (None, "")])
check("3b …an answer that names a live thing drops it", DN('your subagent "x"') == "")
check("3b …a held item and work wording draw no note whatever the answer", update_svc._doing_wait_note({"state": "doing", "hold": True}, "alpha-main: wait until 2099-03-02 for the vendor's reply", "") == ""
      and update_svc._doing_wait_note({"state": "doing"}, "alpha-main: write the parser", "") == "")
# the proof is asked once, by the tool, BEFORE the item lock, and only when the note could be made; the service reads the answer it is given
from stackshot.service import writes as writes_mod
def _lock_held():
    """True when the item lock is held (by this thread: the lock is an RLock, so ownership is asked): the proof must run with it free."""
    return writes_mod.ITEM_LOCK._is_owned()
ASKED = []
def counting(who, now=None, snap=None):
    ASKED.append((who, _lock_held()))
    return [sub("Build @8: the overnight run")] if who == BACK else []
doing(8)
with patched(audit_ticks_svc, _mover_subagents=counting):
    got = update(8, next=WAITING_NEXT)
check("3b the proof for the note is asked once, with the item lock free (before the write takes it), for the item's holder", got[0] == "ok" and NOTE not in got[1] and ASKED == [(BACK, False)], (got, ASKED))
ASKED.clear(); doing(8)
with patched(audit_ticks_svc, _mover_subagents=counting):
    update(8, next=f"{BACK}: write the parser", work={"text": "x", "state": "in progress"})
    update(8, sender=BACK, hold=True, wake=FUT, wait_basis=f"the soak window ends {FUT}", next=WAITING_NEXT)
check("3b …never asked for a next that reads as work, and not for a write that holds (the gate asks for a hold, the note cannot be made)", [a for a in ASKED if a[1]] == [] and len(ASKED) <= 1, ASKED)
ASKED.clear(); put(10, mover=BACK, needs=[BACK])
with patched(audit_ticks_svc, _mover_subagents=counting):
    update(10, next=WAITING_NEXT)
check("3b …nor for an item whose stored state is not doing (no note can follow)", ASKED == [], ASKED)
ASKED.clear(); doing(8)
with patched(audit_ticks_svc, _mover_subagents=lambda who, now=None, snap=None: ASKED.append((who, _lock_held())) or [sub("Build @2: the other fix")]):
    got = update(8, hold=True, wake=FUT, wait_basis=f"the soak window ends {FUT}", next=WAITING_NEXT)
check("3b …a write that holds is asked once, by the hold's gate: the note cannot follow a hold, so the note's proof is not asked again", got[0] == "ok" and len(ASKED) == 1, (got, ASKED))
ASKED.clear(); put(18, status="completed", mover=BACK, needs=[BACK], state="doing", outcome="done")
with patched(audit_ticks_svc, _mover_subagents=counting):
    update(18, next=WAITING_NEXT)
check("3b …nor for a closed item", ASKED == [], ASKED)
ASKED.clear(); doing(8)
with patched(audit_ticks_svc, _mover_subagents=counting):
    update(8, mover=OTHER, next=f"{OTHER}: " + WAITING_NEXT.split(": ", 1)[1])
check("3b a write that hands the item to another session asks for the new holder (the one the note would speak to)", ASKED in ([(OTHER, False)], []), ASKED)
ASKED.clear(); doing(8)
with patched(audit_ticks_svc, _mover_subagents=counting):
    got = update(8, sender=OTHER, next=WAITING_NEXT)
check("3b the note asks the item's holder (its mover), not the sender: another session's write to the item is told nothing of its own runs", [a[0] for a in ASKED] == [BACK] and NOTE not in got[1], (got, ASKED))

# ---------------------------------------------------------------- 3c. stored blockers, spelling, the guard key, the tool's parameters reach the gate
for n, meta in ((11, dict(needs=["external"], wait_kind="relay", wait_event="the vendor", until=FUT)),
                (12, dict(needs=["external"], wait_kind="anchor", wait_anchor="https://github.com/acme/stack/pull/9", wait_event="merged", until=FUT)),
                (13, dict(after=["a2"])),
                (14, dict(needs=["external"])),
                (15, dict(wait_kind="event", wait_event="recycle", until=FUT))):
    put(n, mover=BACK, **meta)
    check(f"3c an item that already stores its blocker ({sorted(meta)}) is not refused a hold by its mover with a tied subagent", ok(gate(live_for([sub(f"Build @{n}")]), gid=f"a{n}")) and ok(gate(live_for([sub(f"Build @{n}")]), gid=f"a{n}", hold=False, wake=FUT)), gate(live_for([sub(f"Build @{n}")]), gid=f"a{n}"))
put(16, mover=BACK, wait_kind="time", until=FUT)
check("3c …an item that stores only a plain wait on a time is still refused (a hold, and a date alone)", refused(gate(live_for([sub("Build @16")]), gid="a16")) and refused(gate(live_for([sub("Build @16")]), gid="a16", hold=False, wake=FUT)), gate(live_for([sub("Build @16")]), gid="a16"))
check("3c …and so is an item that stores a closed `after` (no blocker is left)", (put(17, mover=BACK, after=["a4"]) and refused(gate(live_for([sub("Build @17")]), gid="a17"))), gate(live_for([sub("Build @17")]), gid="a17"))
check("3c a wait_kind of list in this write (a waits list) is never refused", ok(gate(live_for(BUILD), wait_kind="list")))
# the spelling of the mover, compared both ways
check("3c `mover=` naming the sender in upper case is still the sender's own item: refused", refused(gate(live_for(BUILD), mover=BACK.upper())), gate(live_for(BUILD), mover=BACK.upper()))
check("3c …the sender in upper case against the stored mover: refused", refused(gate(live_for(BUILD), sender=BACK.upper())), gate(live_for(BUILD), sender=BACK.upper()))
check("3c …`mover=` naming another session in upper case is a hand-off: not refused", ok(gate(live_for(BUILD), mover=OTHER.upper())), gate(live_for(BUILD), mover=OTHER.upper()))
# candidates: only the mover's own open items; an anchored pull request of another item ties nothing here
check("3c a subagent whose description names an item ANOTHER session moves is on none of this mover's items: its brief naming this item ties it",
      refused(gate(live_for([sub("Review @3", brief="the work of @1")]))), gate(live_for([sub("Review @3", brief="the work of @1")])))
check("3c a pull request anchored to ANOTHER item of the mover does not tie a subagent to this one", ok(gate(live_for([sub("Build PR 77")], anch={"a2": {"acme/stack#77"}}))), gate(live_for([sub("Build PR 77")], anch={"a2": {"acme/stack#77"}})))
# the guard key absent means on (the fixture carries it)
_m = _cfg.CFG.setdefault("model", {}); _had = _m.pop("busy_hold_guard", "<absent>")
try: absent = gate(live_for(BUILD))
finally:
    if _had != "<absent>": _m["busy_hold_guard"] = _had
check("3c `[model] busy_hold_guard` absent from the config means on: refused", refused(absent) and _had != "<absent>" or refused(absent), absent)
# through the tool: each parameter the gate reads reaches it
with patched(audit_ticks_svc, _mover_subagents=fake_server_subs):
    SUBS[:] = [sub("Build @1: the export fix")]
    put(1, mover=BACK)
    got = update(1, **HOLD, clear_hold=True)
    check("3c tool: clear_hold reaches the gate (a hold that clears itself is no park: not refused as being moved)", not refused(got), got)
    put(1, mover=BACK)
    got = update(1, next=f"{BACK}: do it", hold=True, ask_by=FUT, wait_kind="relay", wait_event="the vendor", needs=["external"], wait_basis=f"the vendor answers {FUT}")
    check("3c tool: a relay's ask_by and needs reach the gate", not refused(got), got)
    put(1, mover=BACK)
    got = update(1, next=f"{BACK}: do it", hold=True, ask_by=FUT)
    check("3c tool: ask_by alone reaches the gate (a wait that names its day to chase is not a plain park)", not refused(got), got)
    put(1, mover=BACK)
    got = update(1, next=f"{BACK}: do it", until=FUT, waits=[{"kind": "item", "after": "a2"}, {"kind": "time", "until": FUT}])
    check("3c tool: a waits list is never refused as being moved", not refused(got), got)
    put(1, mover=BACK)
    got = update(1, mover=BACK.upper(), **HOLD)
    check("3c tool: mover= in upper case naming the sender is refused", refused(got), got)
    put(1, mover=BACK)

# ---------------------------------------------------------------- 4. shape
import ast
gsrc = pathlib.Path(STACK, "stackshot/service/gates.py").read_text(encoding="utf-8")
usrc = pathlib.Path(STACK, "stackshot/web/tools/update.py").read_text(encoding="utf-8")
imports = [n.module or "" for n in ast.walk(ast.parse(gsrc)) if isinstance(n, ast.ImportFrom)] + [a.name for n in ast.walk(ast.parse(gsrc)) if isinstance(n, ast.Import) for a in n.names]
check("4 gates.py imports no audit/ or web/ module: the proof is handed in as a callable", not [m for m in imports if m.startswith(("stackshot.audit", "stackshot.web"))], imports)
check("4 the update tool calls the gate after gate_self_wait and before the item lock (`_writes.session_write`)", 0 < usrc.index("_gates.gate_self_wait(") < usrc.index("_gates.gate_busy_hold(") < usrc.index("with _writes.session_write()"))
check("4 the tool takes the proof from register(busy_live=…), and a registration without it passes every write", "busy_live=None" in usrc and "if _busy_live is not None else None" in usrc)
check("4 the refusal text carries no id of the board and is plain words", not re.search(re.escape(BOARD) + r"|\b[a-z]\d{1,6}\b", gates.BUSY_HOLD_REFUSAL.replace("{live}", "")), gates.BUSY_HOLD_REFUSAL)
check("4 the proof reads the audit's own helpers (subagent_tie.tied_to, the hourly audit's item view), not a second tie", "_tie.tied_to(" in pathlib.Path(STACK, "stackshot/audit/busy_hold.py").read_text(encoding="utf-8"))
bh_tree = ast.parse(pathlib.Path(STACK, "stackshot/audit/busy_hold.py").read_text(encoding="utf-8"))
bh_imports = sorted({n.module or "" for n in ast.walk(bh_tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(bh_tree) if isinstance(n, ast.Import) for a in n.names})
check("4 the proof reads nothing from GitHub and starts no process: it imports only the audit's own readers, the pure model helpers, the config and the standard library's re and pathlib (the release arm's log read)",
      bh_imports == ["__future__", "pathlib", "re", "stackshot.audit", "stackshot.core", "stackshot.model", "typing"], bh_imports)
ex = (pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
check("4 the example config carries the switch, on", re.search(r"(?m)^busy_hold_guard = true\b", ex) is not None)

# ---------------------------------------------------------------- 5. text
utext = " ".join(pathlib.Path(STACK, "stackshot/web/tools/text/update.md").read_text(encoding="utf-8").split())
ctext = " ".join(pathlib.Path(STACK, "stackshot/web/tools/text/create.md").read_text(encoding="utf-8").split())
check("5 the update text no longer lists another release among the waits to park", "another release" not in utext and "a timer, someone else's step or release" in utext)
check("5 …and the create text says the same of a wait", "another release" not in ctext and "someone else's step or release is not doing" in ctext)
check("5 …says a release or its queue, a run or a subagent of the mover's own is work moving in real time: do not park it", "a release or its queue, a run or subagent of yours): do not park it" in utext)
check("5 …and says the mover's park is refused while its subagent runs on the item", "its mover's park is refused while its subagent runs on it" in utext)

PARTS.append(("hold", len(ran)))

# ================================================================ part 2: release (the unit of a pull request tied to the item)
PART[0] = "release"; N0 = len(ran)
# a fresh store, as the part starts: only items 1 to 6 of the fixture, no item the first part left behind; no subagent left over
for _p in (T / "store/a").glob("*.json"): _p.unlink()
SUBS[:] = []
put(1, mover=BACK)                      # the item the cases hold
put(2, mover=BACK)                      # another open item of the same mover
put(3, mover=OTHER)                     # an item another session moves
put(4, status="completed", mover=BACK, outcome="done")
put(5, mover=BACK)
put(6, mover=BACK)
import shutil; shutil.rmtree(T / "state", ignore_errors=True); (T / "state").mkdir()      # no file of the first part in the state folder

# ---------------------------------------------------------------- fixtures: units, logs, the proof as the server builds it
OWN = "acme/stack"; OTHERREPO = "other/repo"
_rel._OWN[:] = [OWN]                                              # this checkout's repository, as releasing.own_repo reads it (read once per process)
UNITS_OUT = {"v": ""}
_rel._run = lambda argv: UNITS_OUT["v"]                           # never the host's systemd: `systemctl --user list-units` answers what a case says
def units_text(*ns): return "".join(f"stackshot-release-{n}.service loaded active running [systemd-run] /srv/stack/release.sh --run {n}\n" for n in ns)
RELDIR = T / "state/releases"; RELDIR.mkdir(parents=True)
STAMP = "2026-11-14T15:03:37Z "
QUEUED = STAMP + "in the merge queue (QUEUED position 1): 3 min since the enqueue, up to 40 min; reading it every 30s\n"
def tail(*lines): return "".join(STAMP + l + "\n" for l in lines)
def logfile(n, text=QUEUED, age=120.0):
    p = RELDIR / f"pr-{n}.log"; p.write_text(text, encoding="utf-8"); os.utime(p, (time.time() - age, time.time() - age)); return p
def rel_live(units=(77,), anch=None, own=OWN, logs=None, raises=None, now=None, calls=None, step_prs=None, item=None):
    """The gate's `live` callable as the server builds the release arm (audit/busy_hold.py `live_release`), over the scratch store, fake units and fake logs (a dict {n: (mtime, tail)}; absent = no log)."""
    logs = {n: (NOW - 120.0, QUEUED) for n in units} if logs is None else logs
    def count(k):
        if calls is not None: calls.append(k)
    def U():
        count("units")
        if raises is not None: raise raises
        return set(units)
    def L(n):
        count(f"log{n}")
        v = logs.get(n)
        if isinstance(v, Exception): raise v
        return v
    def live(gid, mover):
        return busy_hold.live_release(gid, units=U, anchored=lambda: anch or {}, item=item or (lambda g: count("item") or _svcstore._load(g)), own_repo=lambda: own, canon=_cfg.canon_repo,
                                      step_prs=step_prs or _rel.step_prs, log=L, now=lambda: NOW if now is None else now)
    return live
def both_for(subs=None, **kw):
    """web/wiring.py's `_busy_live` as a callable over fakes: the subagent proof first, the release proof second."""
    a, b = live_for(subs or [], anch=kw.get("anch")), rel_live(**kw)
    return lambda g, w: a(g, w) or b(g, w)
A77 = {"a1": {f"{OWN}#77"}}
def gtext(live, **kw):
    """The words of the refusal a gate answers with, \"\" when it did not refuse."""
    got = gate(live, **kw)
    return got[1] if got[0] == "refused" else ""
RELWORDS = lambda got: got[0] == "refused" and got[1].startswith("Refused: this item is being moved now: a release of PR #")
def reset(): put(1, mover=BACK)
def setdesc(i, text):
    """The item's own description (put() puts keyword arguments in the metadata)."""
    it = read(i); it["description"] = text; (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")

# ---------------------------------------------------------------- 1. refuses
want = ("Refused: this item is being moved now: a release of PR #77 tied to this item is running (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1)), so it is not paused. "
        "Keep it in hand and write where its step stands (work=<one line>, state in progress), or wait on it by name: update(wait_kind=\"event\", wait_event=\"pr_released <n>\" or \"pr_merged <n>\", until=<the day it comes back anyway; left out, the server takes tomorrow or the day the item's words give, and says so; it is not the 14-day backstop>, mover=<who takes it then>). Park it only once nothing is running on it.")
got = gate(rel_live(anch=A77))
check("1 a running release of a pull request anchored to the item refuses the mover's hold, in exactly the words of the refusal", got == ("refused", want), got)
check("1 …the same text is the constant, formatted", gates.BUSY_RELEASE_REFUSAL.format(live="a release of PR #77 tied to this item is running (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1))") == want)
check("1 …the subagent's refusal keeps its own text (no wait_event clause), so the two are told apart", gates.BUSY_HOLD_REFUSAL.format(live="x") != want and "pr_released" not in gates.BUSY_HOLD_REFUSAL)
check("1 …the refusal names no item of the board", not re.search(r"\b(?:" + BOARD + r"\d+|a\d+)\b", got[1]), got)
check("1 …and a date alone (a wake or an until the write turns into a hold) is refused as a hold is", RELWORDS(gate(rel_live(anch=A77), hold=False, wake=FUT)) and RELWORDS(gate(rel_live(anch=A77), wake=FUT)), gate(rel_live(anch=A77), hold=False, wake=FUT))
check("1 …and wait_kind time, the plain park, is refused", RELWORDS(gate(rel_live(anch=A77), wait_kind="time")))
put(5, mover=BACK, hold=True)
check("1 …an item already on hold is refused again when the write sets the hold", RELWORDS(gate(rel_live(anch={"a5": {f"{OWN}#77"}}), gid="a5")), gate(rel_live(anch={"a5": {f"{OWN}#77"}}), gid="a5"))
put(5, mover=BACK)
check("1 the anchor of another spelling of this repository (an old name through [github.moved]) ties as the repository's own", RELWORDS(gate(rel_live(anch={"a1": {"ACME/Stack#77"}}))), gate(rel_live(anch={"a1": {"ACME/Stack#77"}})))
# tied by an open step
put(1, mover=BACK, next=f"{BACK}: release https://github.com/{OWN}/pull/78 once the checks are green")
check("1 (fixture) the open step's URL is read by releasing.step_prs as this repository's pull request 78", _rel.step_prs(read(1)["metadata"]) == {78}, _rel.step_prs(read(1)["metadata"]))
got = gate(rel_live(units=(78,)))
check("1 a running release of the pull request an open step links by URL refuses (no anchor needed)", RELWORDS(got) and "PR #78 tied to this item is running (unit stackshot-release-78.service" in got[1], got)
put(1, mover=BACK, next=f"{BACK}: release PR #79 and watch main")
check("1 (fixture) `PR #79` in an open step reads as this repository's pull request 79", _rel.step_prs(read(1)["metadata"]) == {79}, _rel.step_prs(read(1)["metadata"]))
check("1 a running release of the pull request an open step names as `PR #79` refuses", RELWORDS(gate(rel_live(units=(79,)))), gate(rel_live(units=(79,))))
put(1, mover=BACK, next=f"{BACK}: land the fix", step_proof={_steps.key(f"{BACK}: land the fix"): f"pr_released {OWN}#80"})
check("1 (fixture) an open step's stored proof pr_released of this repository reads as pull request 80", _rel.step_prs(read(1)["metadata"]) == {80}, _rel.step_prs(read(1)["metadata"]))
check("1 a running release of the pull request an open step's proof names refuses", RELWORDS(gate(rel_live(units=(80,)))), gate(rel_live(units=(80,))))
put(1, mover=BACK, step_proof={_steps.key(f"{BACK}: do it"): f"pr_merged {OWN}#81"})
check("1 …a pr_merged proof ties as a pr_released one does", RELWORDS(gate(rel_live(units=(81,)))), gate(rel_live(units=(81,))))
# tied by the status line of an open step (the open work line)
def setsteps(*steps, nxt=f"{BACK}: do it"):
    """The item with these stored steps ({text, status, tag}) beside its next."""
    put(1, mover=BACK, next=nxt, steps=list(steps))
OPENSTEP = f"{BACK}: do it"
setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": "PR #83 in the merge queue", "state": "in progress"}})
check("1 a running release of the pull request the status line of an open step names (`PR #83`) refuses", RELWORDS(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": f"https://github.com/{OWN}/pull/82 released", "state": "in progress"}})
check("1 …by the pull request's URL in the status line", RELWORDS(gate(rel_live(units=(82,)))), gate(rel_live(units=(82,))))
setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": "PR #83 up", "state": "defined"}})
check("1 …a status line in any state but done counts", RELWORDS(gate(rel_live(units=(83,)))))
reset()

setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": "PR #83 in the merge queue", "state": "in progress"}})
check("1 a status line naming a pull request whose unit does not run is not counted although that pull request's log is fresh (only a unit proves it)", ok(gate(rel_live(units=(99,), logs={83: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)}))), gate(rel_live(units=(99,), logs={83: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)})))
setsteps({"text": OPENSTEP, "status": "open"}, {"text": f"{BACK}: land it", "status": "done", "tag": {"text": "PR #83 in the merge queue", "state": "in progress"}})
check("1 the status line a DONE step still carries (its state left at in progress) ties nothing: only an open step's line is read", ok(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
setsteps({"text": OPENSTEP, "status": "open"}, {"text": f"{BACK}: try it", "status": "dropped", "tag": {"text": "PR #83 in review", "state": "in progress"}})
check("1 …nor a dropped step's", ok(gate(rel_live(units=(83,)))))
reset()

# the description, a done step, a dropped step and any other free text never tie (a refusal is never a wrong one)
setdesc(1, "- Fixes the export in PR 83, see PR #83 and https://github.com/%s/pull/83" % OWN)
check("2 a description that names `PR 83`, `PR #83` and its URL while PR 83 is released under another item ties nothing: the hold passes", ok(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
reset(); setsteps({"text": OPENSTEP, "status": "open"}, {"text": f"{BACK}: land PR #83", "status": "done"}, {"text": f"{BACK}: try https://github.com/{OWN}/pull/83", "status": "dropped"})
check("2 a DONE step and a dropped step that name PR #83 (words and URL) tie nothing", ok(gate(rel_live(units=(83,)))) and _rel.step_prs(read(1)["metadata"]) == set(), (gate(rel_live(units=(83,))), _rel.step_prs(read(1)["metadata"])))
reset(); setsteps({"text": OPENSTEP, "status": "open"}, {"text": f"{BACK}: land it", "status": "done", "tag": {"text": "PR #83 released", "state": "done"}})
check("2 the status line of a done step ties nothing", ok(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
reset(); setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": "PR #83 released", "state": "done"}})
check("2 …nor a status line whose state is done", ok(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
put(1, mover=BACK, next=f"{BACK}: do it", wait_note="PR #83 is in review")
check("2 a mention in another field of the item (a note, a wait's text) ties nothing", ok(gate(rel_live(units=(83,)))))
put(1, mover=BACK, next=f"{BACK}: wait for #83 to be released")
check("2 a bare `#83` in an open step ties nothing (the number is read only as `PR #83` or by its URL)", ok(gate(rel_live(units=(83,)))) and _rel.step_prs(read(1)["metadata"]) == set(), _rel.step_prs(read(1)["metadata"]))
put(1, mover=BACK, next=f"{BACK}: take PR 83 from here")
check("2 …nor `PR 83` written without the #", ok(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
put(1, mover=BACK, next=f"{BACK}: open the follow-up to PR #83")
check("2 an OPEN step that says `follow-up to PR #83` is an open step naming it: it refuses while that unit runs (accepted: the unit is the mover's, a hold would be false)", RELWORDS(gate(rel_live(units=(83,)))), gate(rel_live(units=(83,))))
reset(); setdesc(1, "- Follow-up to PR 83 and PR #83")
check("2 …the same while another item (a2) is the one anchored to PR 83: the hold on this item passes", ok(gate(rel_live(units=(83,), anch={"a2": {f"{OWN}#83"}}))), gate(rel_live(units=(83,), anch={"a2": {f"{OWN}#83"}})))
check("2 named_prs reads only this repository's URL and `PR #n` / `pull request #n`", busy_hold.named_prs(f"PR #5, pull request #6, https://github.com/{OWN}/pull/7 https://github.com/{OTHERREPO}/pull/8 {OTHERREPO} PR #9 PR 10 #11", OWN, _cfg.canon_repo) == {5, 6, 7}, busy_hold.named_prs(f"PR #5, pull request #6, https://github.com/{OWN}/pull/7 https://github.com/{OTHERREPO}/pull/8 {OTHERREPO} PR #9 PR 10 #11", OWN, _cfg.canon_repo))
put(1, mover=BACK, next=f"{BACK}: open the follow-up to PR #83")
check("2 …and passes when no unit of PR 83 runs (the mover has none)", ok(gate(rel_live(units=(99,)))), gate(rel_live(units=(99,))))
put(1, mover=BACK, next=f"{BACK}: open the follow-up to PR #83")
check("2 …and when the unit's log is quiet", ok(gate(rel_live(units=(83,), logs={83: (NOW - 1200.0, QUEUED)}))))
for _txt in ("GH-PR #83 in the merge queue", "foo/PR #83 up", "x#PR #83 up", "XPR #83 up", "my.PR #83 up"):
    setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": _txt, "state": "in progress"}})
    check(f"2 a status line `{_txt}` (the PR word glued to another word, a path or a name) ties nothing: the lookbehind", ok(gate(rel_live(units=(83,)))) and busy_hold.named_prs(_txt, OWN, _cfg.canon_repo) == set(), (gate(rel_live(units=(83,))), busy_hold.named_prs(_txt, OWN, _cfg.canon_repo)))
setsteps({"text": OPENSTEP, "status": "open", "tag": {"text": "(PR #83) in the merge queue", "state": "in progress"}})
check("2 …while `(PR #83)` and `see PR #83` and a line that begins with it still tie", RELWORDS(gate(rel_live(units=(83,)))) and busy_hold.named_prs("see PR #83", OWN, _cfg.canon_repo) == {83} and busy_hold.named_prs("PR #83", OWN, _cfg.canon_repo) == {83} and busy_hold.named_prs("pull request #83", OWN, _cfg.canon_repo) == {83})
put(1, mover=BACK, next=f"{BACK}: read {OTHERREPO} PR #83")
check("2 …another repository's `other/repo PR #83` in an open step ties nothing", ok(gate(rel_live(units=(83,)))))
reset()

# the stage: the log's own words
def stage_in(text, **kw):
    got = gate(rel_live(anch=A77, logs={77: (NOW - 120.0, text)}, **kw))
    m = re.search(r"its log written 2 min ago(, .*?)?\), so it is not paused", got[1])
    return m.group(1)[2:] if m and m.group(1) else "" if m else got
for what, line, stage in (
        ("queued", "in the merge queue (QUEUED position 1): 3 min since the enqueue, up to 40 min; reading it every 30s", "in the merge queue (QUEUED position 1)"),
        ("awaiting checks", "in the merge queue (AWAITING_CHECKS position 2): 9 min since the enqueue, up to 40 min; reading it every 30s", "in the merge queue (AWAITING_CHECKS position 2)"),
        ("a state with no position", "in the merge queue (MERGEABLE): 1 min since the enqueue", "in the merge queue (MERGEABLE)"),
        ("enqueued", "enqueued: the merge queue accepted the head 1a2b3c4", "enqueued in the merge queue"),
        ("checks", "checks on 1a2b3c4d: 1 of 1 run(s) of 1a2b3c4d not completed (poller file 30s old); waiting on the ci-runs file, no GitHub call", "checks on 1a2b3c4d"),
        ("the PR's tests", "waiting for the PR's tests on 1a2b3c4 (pending); 3 min of up to 40", "waiting on the PR's checks"),
        ("merged", "merged by the merge queue as b187281, 16 min after the enqueue", "merged by the merge queue"),
        ("deploying", "deploying b187281 at once: the merge queue ran the suites its selection picked", "deploying"),
        ("main's run", "main's run 43607500681 on 52ef35e: 1 of 1 run(s) of 52ef35e not completed (poller file 30s old)", "main's run 43607500681"),
        ("main's run, running", "main's run 4360750 is running, on 52ef35e (4 min so far); waiting for it to finish", "main's run 4360750"),
        ("a line that names none", "release queue: nothing to start (1 of at most 4 running; 1 listed)", ""),
        ("an empty log", "", "")):
    got = stage_in(tail(line) if line else "")
    check(f"1 the stage is read from the log's last line: {what}", got == stage, (got, line))
check("1 a line with no time (a command's own output) names no stage even when it reads like one", stage_in("deploying b187281 now\n") == "", stage_in("deploying b187281 now\n"))
check("1 …but it is skipped, not the end of the search: a timed stage line before it is read", stage_in(tail("deploying b187281 at once") + "  web/server.py  (server-side)\n.service: unchanged\n") == "deploying")
check("1 the newest of the last four timed lines that names a stage is the stage", stage_in(tail("deploying b1", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start")) == "deploying")
check("1 …a stage five timed lines back is not quoted (it may be long past)", stage_in(tail("deploying b1", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start")) == "")
check("1 …the newer stage wins over an older one", stage_in(tail("merged by the merge queue as b187281", "deploying b187281 at once")) == "deploying")
check("1 a log that is only a torn line, or not text, names no stage and still refuses", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW - 120.0, "��\x00\x01")}))))
check("1 the stage function on its own: a line is read after its words are collapsed to one line", busy_hold.stage_of("in   the merge queue\t(QUEUED position 3)") == "in the merge queue (QUEUED position 3)" and busy_hold.stage_of(None) == "" and busy_hold.stage_of("") == "")
check("1 the age is told in minutes, and under a minute as such", "log written under a minute ago" in gtext(rel_live(anch=A77, logs={77: (NOW - 20.0, QUEUED)})) and "log written 1 min ago" in gtext(rel_live(anch=A77, logs={77: (NOW - 90.0, QUEUED)})) and "log written 14 min ago" in gtext(rel_live(anch=A77, logs={77: (NOW - 14 * 60.0 - 30.0, QUEUED)})))
two = gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: (NOW - 600.0, QUEUED), 91: (NOW - 60.0, tail("deploying b1"))}))
check("1 with two releases tied and running, the one written to most recently is named", RELWORDS(two) and "PR #91 tied to this item is running" in two[1] and "deploying" in two[1], two)
check("1 …a tied release with a stuck log beside a fresh one: the fresh one is named", "PR #77 tied to this item is running" in gtext(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: (NOW - 60.0, QUEUED), 91: (NOW - 5000.0, QUEUED)})))

# ---------------------------------------------------------------- 2. what does not tie
reset()
check("2 an anchored pull request with no unit running never refuses (anchors are never pruned)", ok(gate(rel_live(units=(), anch=A77))), gate(rel_live(units=(), anch=A77)))
check("2 …nor does a unit of a pull request the item names nothing of", ok(gate(rel_live(units=(99,), anch=A77))), gate(rel_live(units=(99,), anch=A77)))
check("2 a unit of a pull request that is anchored to ANOTHER item (a2) never refuses this item", ok(gate(rel_live(anch={"a2": {f"{OWN}#77"}}))), gate(rel_live(anch={"a2": {f"{OWN}#77"}})))
check("2 …an item with no anchor, no step and no word naming any pull request is untied (a false negative, never a false refusal)", ok(gate(rel_live())), gate(rel_live()))
check("2 a unit whose number is another repository's pull request anchored to the item (a number collision) never refuses", ok(gate(rel_live(anch={"a1": {f"{OTHERREPO}#77"}}))), gate(rel_live(anch={"a1": {f"{OTHERREPO}#77"}})))
put(1, mover=BACK, next=f"{BACK}: release https://github.com/{OTHERREPO}/pull/77 first")
check("2 …a step's URL of another repository's pull request with the same number", ok(gate(rel_live())) and _rel.step_prs(read(1)["metadata"]) == set(), (gate(rel_live()), _rel.step_prs(read(1)["metadata"])))
put(1, mover=BACK, next=f"{BACK}: wait for {OTHERREPO} PR #77")
check("2 …`other/repo PR #77` in a step", ok(gate(rel_live())) and _rel.step_prs(read(1)["metadata"]) == set(), (gate(rel_live()), _rel.step_prs(read(1)["metadata"])))
put(1, mover=BACK); setdesc(1, f"- See https://github.com/{OTHERREPO}/pull/77")
check("2 …a description that links another repository's pull request 77", ok(gate(rel_live())))
reset()
check("2 a pull request number in no word of the item ties nothing", ok(gate(rel_live())))
put(1, mover=BACK, next=f"{BACK}: do it, PR #770")
check("2 the number is read whole: `PR #770` in an open step does not tie unit 77", ok(gate(rel_live())) and _rel.step_prs(read(1)["metadata"]) == {770}, gate(rel_live()))
put(1, mover=BACK, next=f"{BACK}: do it, PR #77")
check("2 …and `PR #77` does tie it (the same fixture, the whole number)", RELWORDS(gate(rel_live())), gate(rel_live()))
reset()
put(3, mover=OTHER)
check("2 an item another session moves (a3) is not refused even with its pull request live", ok(gate(rel_live(anch={"a3": {f"{OWN}#77"}}), gid="a3")), gate(rel_live(anch={"a3": {f"{OWN}#77"}}), gid="a3"))

# ---------------------------------------------------------------- 3. passes (unknown is never a refusal)
reset()
check("3 no unit running passes", ok(gate(rel_live(units=(), anch=A77))))
check("3 a unit read that raises (systemctl gone, no user bus) passes", ok(gate(rel_live(anch=A77, raises=OSError("no bus")))), gate(rel_live(anch=A77, raises=OSError("no bus"))))
check("3 a log written 14 min 59 s ago is a release that is running", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW - 899.0, QUEUED)}))))
check("3 …a log written exactly 15 minutes ago is stuck: the mover is never trapped", ok(gate(rel_live(anch=A77, logs={77: (NOW - 900.0, QUEUED)}))), gate(rel_live(anch=A77, logs={77: (NOW - 900.0, QUEUED)})))
check("3 …and one written an hour ago", ok(gate(rel_live(anch=A77, logs={77: (NOW - 3600.0, QUEUED)}))))
check("3 …a log dated ahead of the clock (a skew, however far) is fresh, not a stuck one: it is `under 15 minutes` old", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW + 30.0, QUEUED)}))) and RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW + 3600.0, QUEUED)}))), gate(rel_live(anch=A77, logs={77: (NOW + 3600.0, QUEUED)})))
check("3 a unit with no log passes (unknown)", ok(gate(rel_live(anch=A77, logs={}))) and ok(gate(rel_live(anch=A77, logs={77: None}))))
check("3 a log that cannot be read passes", ok(gate(rel_live(anch=A77, logs={77: OSError("denied")}))), gate(rel_live(anch=A77, logs={77: OSError("denied")})))
check("3 a repository this checkout cannot name passes", ok(gate(rel_live(anch=A77, own=""))), gate(rel_live(anch=A77, own="")))
check("3 anchors that cannot be read pass", ok(outcome(lambda: gates.gate_busy_hold("a1", BACK, hold=True, live=lambda g, w: busy_hold.live_release(g, units=lambda: {77}, anchored=lambda: 1 / 0, item=_svcstore._load, own_repo=lambda: OWN,
      canon=_cfg.canon_repo, step_prs=_rel.step_prs, log=lambda n: (NOW - 60.0, QUEUED), now=lambda: NOW)))))
check("3 an item that cannot be read passes", ok(gate(rel_live(anch=A77, item=lambda g: 1 / 0))), gate(rel_live(anch=A77, item=lambda g: 1 / 0)))
check("3 an unreadable step reader passes", ok(gate(rel_live(anch=A77, step_prs=lambda m: 1 / 0))))
check("3 a pull request the unit list gives that is no number is no unit", ok(gate(rel_live(units=("x",), anch=A77))))
check("3 a `live` that raises passes the write, and no `live` at all passes", ok(gate(lambda g, w: 1 / 0)) and ok(gate(None)))
# the proof itself answers "" for anything it cannot tell (the gate would also catch a raise, so the callable is asked directly)
direct = lambda **kw: rel_live(**kw)("a1", BACK)
check("3 the proof answers \"\" itself, never raising, when the unit list raises, the anchors raise, the item raises, the log raises or the repository cannot be named",
      direct(anch=A77, raises=OSError("x")) == "" and direct(anch=A77, logs={77: OSError("denied")}) == "" and direct(anch=A77, item=lambda g: 1 / 0) == "" and direct(anch=A77, own="") == ""
      and busy_hold.live_release("a1", units=lambda: {77}, anchored=lambda: 1 / 0, item=_svcstore._load, own_repo=lambda: OWN, canon=_cfg.canon_repo, step_prs=_rel.step_prs, log=lambda n: (NOW, QUEUED), now=lambda: NOW) == "")
check("3 …and its words, when it can tell, are the refusal's start", direct(anch=A77).startswith("a release of PR #77 tied to this item is running (unit stackshot-release-77.service"), direct(anch=A77))
check("3 an anchored pull request that is not running is not counted although its log is fresh (only a unit proves it)", ok(gate(rel_live(units=(99,), anch=A77, logs={77: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)}))), gate(rel_live(units=(99,), anch=A77, logs={77: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)})))
check("3 a step's pull request that is not running is not counted although its log is fresh", ok(gate(rel_live(units=(99,), step_prs=lambda m: {78}, logs={78: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)}))))
check("3 two tied releases, one with no log and one fresh: the fresh one refuses (a missing log is skipped, not fatal)", "PR #91 tied to this item is running" in gtext(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={91: (NOW - 60.0, QUEUED)})), gtext(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={91: (NOW - 60.0, QUEUED)})))
check("3 …and with the log of one unreadable the other still speaks", "PR #91 tied to this item is running" in gtext(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: OSError("x"), 91: (NOW - 60.0, QUEUED)})))
# the early exits are the subagent proof's own
L77 = rel_live(anch=A77)
check("3 (the live proof refuses before the exits below)", RELWORDS(gate(L77)))
check("3 a sender that is not the item's mover is not refused (a3's mover is another session)", ok(gate(rel_live(anch={"a3": {f"{OWN}#77"}}), sender=BACK, gid="a3")))
check("3 …nor the owner, nor a write that names no sender", ok(gate(L77, sender=OWNER)) and ok(gate(L77, sender="")))
with cfg_model(busy_hold_guard=False):
    off = gate(L77)
check("3 `[model] busy_hold_guard = false` switches the release arm off too, read live (and back on after)", ok(off) and RELWORDS(gate(L77)), (off, gate(L77)))
check("3 a write that closes the item (status completed) is not refused", ok(gate(L77, status="completed")))
check("3 a write that ticks a step (done=) is not refused", ok(gate(L77, done=[1])) and ok(gate(L77, done="1")))
check("3 a write that drops the park (clear_hold, clear_wake, clear_wait) is not refused", all(ok(gate(L77, **{k: True})) for k in ("clear_hold", "clear_wake", "clear_wait")))
check("3 a write that is no hold and no date is not refused", ok(gate(L77, hold=False)) and ok(gate(L77, hold=False, wake="none")))
check("3 a wait that names its blocker is not refused (wait_kind, after, needs, ask_by)", ok(gate(L77, wait_kind="relay")) and ok(gate(L77, wait_kind="event")) and ok(gate(L77, after=["a2"])) and ok(gate(L77, needs=["external"])) and ok(gate(L77, ask_by=FUT)))
check("3 a hand-off to another session (mover=, a next line that hands it on) is not the mover's hold", ok(gate(L77, mover=OTHER)) and ok(gate(L77, next_text=f"{OTHER}: take it from here")))
check("3 a next line of the mover's own steps does not lift the refusal", RELWORDS(gate(L77, next_text=f"{BACK}: write the tests")))
put(4, status="completed", mover=BACK, outcome="done"); put(7, mover=OWNER)
check("3 a completed item, an item that does not exist, and an item the owner moves are not refused", ok(gate(rel_live(anch={"a4": {f"{OWN}#77"}}), gid="a4")) and ok(gate(L77, gid="a99999")) and ok(gate(rel_live(anch={"a7": {f"{OWN}#77"}}), gid="a7")))
put(1, mover=BACK, hold=True, wait_kind="event", wait_event=f"pr_released {OWN}#77")
check("3 an item whose stored wait names its blocker (an event wait) is not parked again by this check", ok(gate(L77)), gate(L77))
reset()

# ---------------------------------------------------------------- 4. both arms
SUB1 = [sub("Build @1: the export fix")]
got = gate(both_for(SUB1, anch=A77))
check("4 a subagent live and a release live: the subagent is named (its proof comes first), with its own refusal", refused(got) and 'your subagent "' in got[1] and "a release of PR" not in got[1] and "pr_released" not in got[1], got)
check("4 a release live and no subagent: the release is named, with its own refusal", RELWORDS(gate(both_for([], anch=A77))))
check("4 a subagent live and no release: the subagent is named", 'your subagent "' in gtext(both_for(SUB1, anch=A77, units=())))
check("4 neither passes", ok(gate(both_for([], anch=A77, units=()))))
check("4 a subagent tied to another item of the mover and a release tied to this one: the release refuses", RELWORDS(gate(both_for([sub("Build @2: the other fix")], anch=A77))), gate(both_for([sub("Build @2: the other fix")], anch=A77)))
def broken_subs(gid, mover):
    return busy_hold.live_work(gid, mover, subagents=lambda who: (_ for _ in ()).throw(subagent_tie.Unreadable("no fresh agent-state snapshot")), items=lambda: _nr.load_all(None), anchored=lambda: {}, same=_handoff_svc.ho_same, shown=_nr.shown)
check("4 a mover whose subagents cannot be read (unknown) still lets a live release speak", RELWORDS(gate(lambda g, w: broken_subs(g, w) or rel_live(anch=A77)(g, w))))
check("4 …and when neither can be told it passes", ok(gate(lambda g, w: broken_subs(g, w) or rel_live(anch=A77, raises=OSError("x"))(g, w))))

# ---------------------------------------------------------------- 5. tool: the real update tool, the real `wiring._busy_live`
check("5 the real unit list is parsed from systemctl's own line shape: release_units reads the numbers of active release units", (UNITS_OUT.update(v=units_text(77, 225)), _rel.release_units())[1] == {77, 225} and (UNITS_OUT.update(v=""), _rel.release_units())[1] == set())
with patched(audit_ticks_svc, _mover_subagents=fake_server_subs), patched(_rlive, released_anchors=lambda: dict(A77)):
    SUBS[:] = []
    UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=120.0)
    before = json.dumps(read(1), sort_keys=True)
    got = update(1, **HOLD)
    check("5 a hold while the release of the item's anchored pull request runs is refused through the real tool, naming the release, its unit, its log and its stage", RELWORDS(got) and "PR #77 tied to this item is running (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1))" in got[1], got)
    check("5 …and the refused write stores nothing", json.dumps(read(1), sort_keys=True) == before and not read(1)["metadata"].get("until") and not read(1)["metadata"].get("hold"))
    got = update(1, until=FUT, next=f"{BACK}: do it", wait_basis=f"the soak window ends {FUT}", wait_reason=SOAK)
    check("5 …an until alone (a date the write turns into a hold) is refused as a hold is", RELWORDS(got), got)
    got = update(1, sender=BACK, work={"text": "PR 77 in the merge queue", "state": "in progress"})
    check("5 …a status line with work= (keeping it in hand) goes through", got[0] == "ok", got)
    reset()
    UNITS_OUT["v"] = ""
    got = update(1, **HOLD)
    check("5 the same hold passes and is stored once the unit has ended (a failed or finished release has none)", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset(); UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=16 * 60.0)
    got = update(1, **HOLD)
    check("5 …and while the unit runs but its log has been quiet for 16 minutes (a stuck release) the hold is stored", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset(); logfile(77, QUEUED, age=60.0)
    (RELDIR / "pr-77.log").unlink()
    got = update(1, **HOLD)
    check("5 …and a unit with no log at all passes", got[0] == "ok", got)
    reset(); logfile(77, QUEUED, age=60.0); UNITS_OUT["v"] = units_text(78)
    got = update(1, **HOLD)
    check("5 …and a unit of a pull request the item is not tied to passes (the unit of PR 78 is another item's)", got[0] == "ok", got)
    reset(); UNITS_OUT["v"] = units_text(77)
    got = update(1, **{**HOLD, "sender": OWNER})
    check("5 the owner's own hold is not refused", not RELWORDS(got), got)
    reset()
    with cfg_model(busy_hold_guard=False):
        got = update(1, **HOLD)
    check("5 with the switch off the hold is stored through the tool", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset()
    got = update(1, **{**HOLD, "done": [1]})
    check("5 a hold written together with done= is not refused", not RELWORDS(got), got)
    reset()
    SUBS[:] = [sub("Build @1: the export fix")]
    got = update(1, **HOLD)
    check("5 both live through the tool: the subagent is named, with its own text", refused(got) and X('your subagent "Build @1: the export fix"') in got[1] and "a release of PR" not in got[1], got)
    reset(); SUBS[:] = []
    # the units cannot be listed at all: a box with no systemd, the failover box
    def no_systemd(argv): raise FileNotFoundError("systemctl")
    with patched(_rel, _run=no_systemd):
        got = update(1, **HOLD)
    check("5 a box where the unit list cannot be had (no systemctl) passes the hold", got[0] == "ok", got)
    reset()
with patched(audit_ticks_svc, _mover_subagents=lambda who, now=None, snap=None: (_ for _ in ()).throw(subagent_tie.Unreadable("no fresh agent-state snapshot names the agent"))), patched(_rlive, released_anchors=lambda: dict(A77)):
    UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=60.0)
    got = update(1, **HOLD)
    check("5 a mover whose subagents cannot be read (unknown) does not hide a live release through the tool", RELWORDS(got), got)
    reset()
with patched(_rlive, released_anchors=lambda: 1 / 0), patched(audit_ticks_svc, _mover_subagents=fake_server_subs):
    got = update(1, **HOLD)
    check("5 anchors the server cannot read are unknown: the write passes", got[0] == "ok", got)
    reset()
UNITS_OUT["v"] = ""
# the failover box: a stale copy of a log and no unit
logfile(77, QUEUED, age=30.0)
check("5 a stale log with no unit (the failover box's stale copies) is never read as a release", wiring._busy_live("a1", BACK) == "")
# the real proof, nothing but the unit list replaced
UNITS_OUT["v"] = units_text(77)
with patched(audit_ticks_svc, _mover_subagents=fake_server_subs), patched(_rlive, released_anchors=lambda: dict(A77)):
    check("5 wiring._busy_live answers the words of the release for an item whose anchored pull request is released now", wiring._busy_live("a1", BACK).startswith("a release of PR #77 tied to this item is running (unit stackshot-release-77.service"), wiring._busy_live("a1", BACK))
    check("5 …and \"\" for another item of the mover", wiring._busy_live("a2", BACK) == "")
UNITS_OUT["v"] = ""

# the reply note
def rel_note_of(i, **kw):
    doing(i)
    with patched(audit_ticks_svc, _mover_subagents=fake_server_subs):
        return update(i, next=WAITING_NEXT, **kw)
A90 = {"a8": {f"{OWN}#90"}}
logfile(90, tail("deploying b1"), age=60.0)
doing(8); base = update(8, next=WAITING_NEXT)
check("5 with no release running the doing item's wait wording draws the note, as before", base[0] == "ok" and base[1].count(NOTE) == 1, base)
UNITS_OUT["v"] = units_text(90)
with patched(_rlive, released_anchors=lambda: dict(A90)):
    got = rel_note_of(8)
    check("5 …no note while a release of a pull request tied to the item runs (its wait wording is about the mover's own release); the write itself goes through", got[0] == "ok" and NOTE not in got[1] and "overnight" in read(8)["metadata"]["next"], got)
    logfile(90, tail("deploying b1"), age=20 * 60.0)
    got = rel_note_of(8)
    check("5 …the note stays when that release's log has been quiet for 20 minutes", got[0] == "ok" and got[1].count(NOTE) == 1, got)
    logfile(90, tail("deploying b1"), age=60.0)
    with cfg_model(busy_hold_guard=False):
        got = rel_note_of(8)
    check("5 …and with the switch off", got[0] == "ok" and got[1].count(NOTE) == 1, got)
with patched(_rlive, released_anchors=lambda: {"a2": {f"{OWN}#90"}}):
    got = rel_note_of(8)
    check("5 …and the note stays when the running release is tied to another item", got[0] == "ok" and got[1].count(NOTE) == 1, got)
with patched(_rlive, released_anchors=lambda: dict(A90)), patched(_rel, _run=lambda argv: (_ for _ in ()).throw(OSError("no bus"))):
    got = rel_note_of(8)
    check("5 …and when the unit list cannot be read", got[0] == "ok" and got[1].count(NOTE) == 1, got)
UNITS_OUT["v"] = ""

# ---------------------------------------------------------------- 6. shape and cost
calls = []
check("6 with no unit running nothing else is read: no item, no log", ok(gate(rel_live(units=(), anch=A77, calls=calls))) and calls == ["units"], calls)
calls.clear()
check("6 an item tied by an anchor to the one unit that runs: one unit read, the item once, that pull request's log once", RELWORDS(gate(rel_live(units=(77,), anch=A77, calls=calls))) and sorted(calls) == ["item", "log77", "units"], calls)
calls.clear()
check("6 …with another unit beside it: still the item once, and only the tied pull request's log", RELWORDS(gate(rel_live(units=(77, 91), anch=A77, calls=calls, logs={77: (NOW - 60.0, QUEUED), 91: (NOW - 60.0, QUEUED)}))) and sorted(calls) == ["item", "log77", "units"], calls)
calls.clear()
check("6 a unit tied to nothing reads no log", ok(gate(rel_live(units=(99,), calls=calls))) and not [c for c in calls if c.startswith("log")], calls)
calls.clear()
check("6 an own-repository that cannot be named reads no item and no log", ok(gate(rel_live(anch=A77, own="", calls=calls))) and calls == ["units"], calls)
gsrc = pathlib.Path(STACK, "stackshot/service/gates.py").read_text(encoding="utf-8")
check("6 gates.py names no audit/ module (the proof is handed in as a callable)", "stackshot.audit" not in gsrc and "from stackshot import audit" not in gsrc)
check("6 the gate chooses the release refusal by the words' own prefix, and that prefix is what live_release writes", gates.BUSY_RELEASE_PREFIX == busy_hold.RELEASE_WORDS == "a release of PR #" and gtext(rel_live(anch=A77)).count(gates.BUSY_RELEASE_PREFIX + "77 tied to this item is running") == 1)
check("6 the units are the release script's own (stackshot-release-<n>.service), listed by the board's own reader", "stackshot-release-" in pathlib.Path(STACK, "stackshot/web/ui/releasing.py").read_text(encoding="utf-8") and busy_hold.RELEASE_FRESH_S == 15 * 60.0)
check("6 the refusal names wait_event kinds that exist: pr_released and pr_merged are in the tools' shared text", all(k in " ".join(pathlib.Path(STACK, "stackshot/web/tools/text/shared.md").read_text(encoding="utf-8").split()) for k in ("pr_released", "pr_merged")))
_shared = " ".join(pathlib.Path(STACK, "stackshot/web/tools/text/shared.md").read_text(encoding="utf-8").split())
check("6 the refusal's wait form is the one the tools' shared text gives: wait_kind=\"event\", wait_event=\"pr_released <n>\", until, mover", 'update(wait_kind="event", wait_event="pr_released <n>"' in _shared and "until=<the day it comes back anyway; left out, the server takes tomorrow or the day the item's words give, and says so; it is not the 14-day backstop>" in _shared and "mover=<who takes it then>" in _shared
      and all(k in gates.BUSY_RELEASE_REFUSAL for k in ('wait_kind="event"', 'wait_event="pr_released <n>"', "until=<the day it comes back anyway; left out, the server takes tomorrow or the day the item's words give, and says so; it is not the 14-day backstop>", "mover=<who takes it then>")))
check("6 …and the update tool takes those parameters", all(f"{k}:" in pathlib.Path(STACK, "stackshot/web/tools/update.py").read_text(encoding="utf-8") for k in ("wait_kind", "wait_event", "ask_by", "mover")))
check("6 the words say a release tied to this item runs, never that it is the mover's own", "your" not in gate(rel_live(anch=A77))[1].split("so it is not paused")[0] and "tied to this item is running" in gate(rel_live(anch=A77))[1])
check("6 the log's end is read through a bounded tail, a unit's number through int", busy_hold.LOG_TAIL_BYTES <= 64 * 1024 and busy_hold.STAGE_LINES == 4)
big = RELDIR / "pr-95.log"; big.write_text("x" * 200000 + "\n" + tail("deploying b1"), encoding="utf-8")
got = busy_hold.release_log(95)
check("6 release_log reads only the end of a long log (never the whole file), with its time", got is not None and len(got[1]) <= busy_hold.LOG_TAIL_BYTES and "deploying" in got[1] and abs(got[0] - time.time()) < 60, (got and (len(got[1]), got[0])))
check("6 …and None for a log that is not there", busy_hold.release_log(96) is None)

PARTS.append(("release", len(ran) - N0))

print("busy_hold scenario parts: " + ", ".join(f"{n} {c}" for n, c in PARTS))
print(f"busy_hold scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup()
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: busy_hold scenario, {len(ran)} checks")
