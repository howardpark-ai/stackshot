"""Scenario test for the refusal of a hold on an item its mover is moving (stackshot/service/gates.py `gate_busy_hold`, stackshot/audit/busy_hold.py, the update tool's write path) — a scratch store, fixture items,
a fake `subagents` callable, no server socket, no network, no model call.

A hold says nothing happens on the item until a date or a reply, which is false while a subagent of the item's mover builds it. The update tool refuses a hold (or a date alone, which the write turns into a
hold) from the item's mover while a running subagent of that mover is tied to THIS item (its description, else its brief, names the item or a pull request anchored to it, read against the mover's other open
items as the hourly audit reads it). Unknown is never a refusal.

  1  refuses     a tied live subagent (by the item's id, by an anchored pull request, by its brief when the description names none) refuses a hold and a date alone; the text names the subagent, tells the mover to
                 keep the item in hand with work=, and carries no id of another item
  2  passes      a subagent tied to ANOTHER item of the mover, none running, a read that is Unreadable or raises, a subagent whose files cannot be read, a running subagent that names no item, a sender that
                 is not the mover, the owner, the guard off, a closing write, done=, a clear_* of the park, a named blocker (wait_kind, after, needs, ask_by), a hand-off to another session, an item that is
                 not open, an item with no mover, no live callable at all
  3  tool        through the real update tool and the server's own wiring (web/wiring.py: `wiring._busy_live`, `audit_ticks._mover_subagents` replaced by a fake): the refused hold stores nothing; the same write passes once the
                 subagent has ended, and a status with work= passes while it runs; the anchors the server reads are the ones that tie
  4  shape       the gate is called from the update tool before the item lock and after gate_self_wait, takes its proof as a callable, gates.py imports no audit/ module, the config switch reads live
  5  text        the update tool's text no longer calls the mover's own release or run a wait to park

    tests/run-suite busy_hold        -> exit 0 / 1"""
import contextlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="busyhold-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
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
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

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
_rel._run = lambda argv: ""      # the second proof (a release of a pull request tied to the item, tests/busy_release_scenario.py) reads the release units: here none runs, never the host's

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
      "work=" in got[1] and "Keep it in hand" in got[1] and "Park it with a hold only once nothing of yours is running on it." in got[1], got)
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
check("1 a subagent flagged quiet (running, its transcript not written lately) still counts", refused(gate(live_for([sub("Build @1", quiet=True)]))))
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
check("2 a subagent whose files cannot be read (listed with no words) passes", ok(gate(live_for([{"id": "x2", "text": "", "at": 0.0, "unreadable": True}]))))
check("2 an Unreadable read (no transcript on this box, an index that cannot be read) passes", ok(gate(live_for(raises=subagent_tie.Unreadable("no transcript of the session on this box")))))
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
def fake_server_subs(who, idx=None, now=None):
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
    got = update(1, until=FUT, next=f"{BACK}: do it", wait_basis=f"the soak window ends {FUT}")
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
with patched(audit_ticks_svc, _mover_subagents=lambda who, idx=None, now=None: (_ for _ in ()).throw(subagent_tie.Unreadable("no transcript of the session on this box"))):
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
    def fake(who, idx=None, now=None):
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
got = note_of(8, raises=subagent_tie.Unreadable("no transcript of the session on this box"))
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
def counting(who, idx=None, now=None):
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
with patched(audit_ticks_svc, _mover_subagents=lambda who, idx=None, now=None: ASKED.append((who, _lock_held())) or [sub("Build @2: the other fix")]):
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
check("5 …and says the mover's hold is refused while its subagent runs on the item", "its mover's hold is refused while its subagent runs on it" in utext)

print(f"busy_hold scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup()
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: busy_hold scenario, {len(ran)} checks")
