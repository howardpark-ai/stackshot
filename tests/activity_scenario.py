"""Scenario test for the item's `activity` clock (activity.py and the stamp in writes.save): the time of the last real activity on an item, which a later silence pass reads.
Fixture data in a temp store, no live store, no network, no server socket, no tmux.

  1  activity.counts: every kind against an ordinary writer, an audit writer (by session name, by id, by author label, case and spacing ignored) and no writer
  2  activity.kind_of: an explicit kind wins, the owner's board answer is an answer, another author a migration, a writer a write, nothing the server's bookkeeping; an unknown kind is refused
  3  activity.at: the stamp, else the last state change or update of an item from before the field, bad values read as 0
  4  activity.stamp: a counting save moves the clock; one that does not leaves it; an item with no clock is seeded from what it read as before the save, never from the save itself
  5  the server's saves: a session's update, the owner's board answer and comment, an anchor event and a message move the clock; a bare confirm, an audit agent's write, the server's own nudge
     and a migration do not, and none of them moves it back
  6  backward compatibility: an item with no field reads as its last state change or update, a file nobody saves is not rewritten, the item as a session reads it (`get`) is the same with and
     without the field, and the GitHub mirror's body is the same

    tests/run-suite activity        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="activitytest-"); T = pathlib.Path(tmp)
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
AUDIT_AGENT = "falcon-audit"       # the example instance's [audit] agent, as _instance names it (the test asserts the server reads the same)
NAMES = ("home-front", "team-back", "home-peer", AUDIT_AGENT, "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew",
                                                                                 "status": "active", "board": [], "board_open": 0, "agents": ALPHA, "back_agents": {"team-back": ALPHA["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n"
                                           "# alpha\n\n## Current state\n\nSTATE-OF-ALPHA: the vendor call is open.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
OLD = now0 - 7200                      # an item last touched two hours ago
def item(i, **fields):
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "home-peer: do the thing", "mover": "home-peer"}
    d = {"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": OLD, "state_updated": OLD - 60, "confirmed": OLD, "metadata": base, **fields}
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def act(i): return rd(i).get("activity")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.model import activity as A
from stackshot.web import server; from stackshot.service import create as create_svc
from stackshot.service import telling
from stackshot.service import writes
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
assert server._cfg.audit_agent() == AUDIT_AGENT, server._cfg.audit_agent()
AUDIT = [AUDIT_AGENT, "stackshot audit"]

# ---- 1. counts
for kind in (A.WRITE, A.ANSWER, A.MESSAGE, A.EVENT):
    check(f"1 counts: {kind} by an ordinary writer moves the clock", A.counts(kind, "home-peer", AUDIT))
for kind in (A.CONFIRM, A.AUDIT, A.MIGRATION, A.BOOKKEEPING):
    check(f"1 counts: {kind} never moves it", not A.counts(kind, "home-peer", AUDIT))
check("1 counts: a write with no writer named is still a write (the kind decides)", A.counts(A.WRITE, "", AUDIT))
for name in (AUDIT_AGENT, AUDIT_AGENT.upper(), f"  {AUDIT_AGENT} ", "stackshot audit", "Stackshot   Audit"):
    check(f"1 counts: a write by the audit ({name!r}) does not move it", not A.counts(A.WRITE, name, AUDIT))
check("1 counts: an audit's anchor event or message does not move it either", not A.counts(A.EVENT, AUDIT_AGENT, AUDIT) and not A.counts(A.MESSAGE, AUDIT_AGENT, AUDIT))
check("1 counts: any one of several names being the audit's is enough (name, id, author label)", not A.counts(A.WRITE, [U[AUDIT_AGENT], AUDIT_AGENT, ""], AUDIT) and A.counts(A.WRITE, [U["home-peer"], "home-peer"], AUDIT))
check("1 counts: no audit names known: nothing is an audit's write", A.counts(A.WRITE, AUDIT_AGENT, ()))
check("1 counts: an unknown kind does not count", not A.counts("nonsense", "home-peer", AUDIT))
check("1 counts: the counting kinds are exactly write, answer, message, event", A.COUNTS == {"write", "answer", "message", "event"} and A.COUNTS < A.KINDS)

# ---- 2. kind_of
check("2 kind_of: an explicit kind wins over the writer", A.kind_of("home-peer", None, A.CONFIRM) == A.CONFIRM and A.kind_of("", None, A.EVENT) == A.EVENT)
check("2 kind_of: the owner's board answer is an answer", A.kind_of("", ("Oliver", "board")) == A.ANSWER)
check("2 kind_of: another author (the migration's) is a migration", A.kind_of("", ("migration", "migration")) == A.MIGRATION)
check("2 kind_of: a writer is a write", A.kind_of("home-peer") == A.WRITE)
check("2 kind_of: no writer, no author, no kind is the server's bookkeeping", A.kind_of("") == A.BOOKKEEPING and A.kind_of("  ") == A.BOOKKEEPING)
try:
    A.kind_of("x", None, "nonsense"); check("2 kind_of: an unknown kind is refused", False)
except ValueError:
    check("2 kind_of: an unknown kind is refused", True)

# ---- 3. at
check("3 at: the stamp wins", A.at({"activity": 500.0, "updated": 900.0, "state_updated": 800.0}) == 500.0)
check("3 at: no stamp reads the later of the state change and the update", A.at({"updated": 900.0, "state_updated": 800.0}) == 900.0 and A.at({"updated": 700.0, "state_updated": 800.0}) == 800.0)
check("3 at: only an update, only a state change", A.at({"updated": 5}) == 5.0 and A.at({"state_updated": 6}) == 6.0)
check("3 at: nothing, None, bad values and a zero stamp read as the item's other clocks or 0", A.at({}) == 0.0 and A.at(None) == 0.0 and A.at({"activity": "soon", "updated": "x"}) == 0.0
      and A.at({"activity": 0, "updated": 40.0}) == 40.0)

# ---- 4. stamp
it = {"updated": 100.0, "state_updated": 90.0}
check("4 stamp: a counting save sets the clock to now and says it changed", A.stamp(it, dict(it), 1000.0, A.WRITE, "home-peer", AUDIT) and it["activity"] == 1000.0)
check("4 stamp: a later counting save moves it again", A.stamp(it, dict(it), 2000.0, A.EVENT, "", AUDIT) and it["activity"] == 2000.0)
check("4 stamp: a save that does not count leaves it where it was and says nothing changed", not A.stamp(it, dict(it), 3000.0, A.CONFIRM, "home-peer", AUDIT) and it["activity"] == 2000.0)
check("4 stamp: nor does an audit's write", not A.stamp(it, dict(it), 3500.0, A.WRITE, AUDIT_AGENT, AUDIT) and it["activity"] == 2000.0)
legacy = {"updated": 4000.0, "state_updated": 100.0}                          # this save already moved `updated` to 4000
check("4 stamp: an item with no clock, saved by something that does not count, is seeded from the stored item before the save (not from the save)",
      A.stamp(legacy, {"updated": 100.0, "state_updated": 100.0}, 4000.0, A.BOOKKEEPING, "", AUDIT) and legacy["activity"] == 100.0, legacy)
fresh = {"updated": 7.0}
check("4 stamp: no stored item (a new one): seeded from the item itself", A.stamp(fresh, None, 8.0, A.AUDIT, "", AUDIT) and fresh["activity"] == 7.0)
empty = {}
check("4 stamp: nothing to seed from writes no field", not A.stamp(empty, None, 9.0, A.BOOKKEEPING, "", AUDIT) and "activity" not in empty)
w = {"activity": 500.0, "updated": 500.0}
A.stamp(w, dict(w), 1000.0, A.ANSWER, "", AUDIT, when=700.0)
check("4 stamp: `when` is the time the activity happened, if it is after the clock and not after now", w["activity"] == 700.0)
A.stamp(w, dict(w), 1000.0, A.ANSWER, "", AUDIT, when=600.0)
check("4 stamp: …never before the clock already read", w["activity"] == 700.0)
A.stamp(w, dict(w), 1000.0, A.ANSWER, "", AUDIT, when=5000.0)
check("4 stamp: …never after now", w["activity"] == 1000.0)
A.stamp(w, dict(w), 1200.0, A.ANSWER, "", AUDIT, when="soon")
check("4 stamp: …a `when` that is no number reads as now", w["activity"] == 1200.0)
A.stamp(w, dict(w), 1300.0, A.CONFIRM, "", AUDIT, when=1250.0)
check("4 stamp: …and a save that does not count ignores it", w["activity"] == 1200.0)
check("4 stamp: a seeded clock is then kept by a later non-counting save", not A.stamp(legacy, {"updated": 4000.0}, 5000.0, A.BOOKKEEPING, "", AUDIT) and legacy["activity"] == 100.0)

# ---- 5. the server's saves
for i in range(1, 12): item(i)
def save(i, **kw):
    it = server._load(f"a{i}"); it["updated"] = time.time(); writes.save(f"a{i}", it, **kw)
t0 = time.time()
# a legacy item, saved first by the server itself (a nudge): the field appears, at the old value
save(1, note="stall: the notice was sent again")
check("5 a server nudge on an old item seeds the clock from the old state, not from the nudge", abs(act(1) - OLD) < 1 and rd(1)["updated"] >= t0, (act(1), OLD))
save(1, note="woke: the wait ended")
check("5 …and a second server save leaves it", abs(act(1) - OLD) < 1)
# a session's write
server._update("a1", sender="home-peer", next="home-peer: do the next thing")
check("5 a session's update moves it to now", act(1) >= t0, act(1))
a1 = act(1)
time.sleep(0.02)
# a bare confirm
server.stackshot_confirm("a1", sender="home-peer")
check("5 a bare confirm moves `confirmed` and leaves `activity`", rd(1)["confirmed"] > a1 and act(1) == a1, (rd(1)["confirmed"], a1, act(1)))
# the server's own passes
save(1, note="stall: handed to the builder")
save(1, note="hand-off: asked")
check("5 the server's nudges (stall, hand-off, silence) leave it", act(1) == a1)
# the audit agent
save(1, writer=AUDIT_AGENT)
save(1, writer=U[AUDIT_AGENT])
check("5 a write by the audit agent (its name or its id) leaves it", act(1) == a1, act(1))
save(1, note="nudge sent by the audit", author=("stackshot audit", "stackshot audit"))
check("5 …and so does a write stamped with the audit's label", act(1) == a1)
# a migration
save(1, note="migrated", author=("migration", "migration"), mirror=False)
check("5 a migration's write leaves it", act(1) == a1)
time.sleep(0.02)
# an anchor event, a message, an answer
save(1, note="step done: the release (PR #1 is released; ticked by stackshot)", activity=A.EVENT)
e1 = act(1)
check("5 an anchor event (a step its proof ticked) moves it", e1 > a1, (e1, a1))
time.sleep(0.02)
save(1, note="team-back reported to home-front: it is live", activity=A.MESSAGE)
m1 = act(1)
check("5 a message written onto the item moves it", m1 > e1)
time.sleep(0.02)
save(1, note="an answer", author=("Oliver", "board"))
n1 = act(1)
check("5 the owner's answer on the board moves it", n1 > m1)
time.sleep(0.02)
save(1, note="a comment", activity=A.ANSWER)
check("5 the owner's comment on GitHub moves it", act(1) > n1)
b1 = act(1)
time.sleep(0.02)
save(1, writer="home-peer", activity=A.EVENT)
check("5 an audit's name is the only writer that overrides a counting kind", act(1) > b1)
c1 = act(1)
save(1, writer=AUDIT_AGENT, activity=A.EVENT)
check("5 …an audit's event or message write does not", act(1) == c1)
# unknown kind never fails a write
writes.save("a2", server._load("a2"), writer="home-peer", activity="nonsense")
check("5 a save with an unknown kind is not refused and the clock is left", rd(2).get("activity") in (None, OLD) or abs(rd(2)["activity"] - OLD) < 1, rd(2).get("activity"))
# create: a session's create is a write
gid, _r = create_svc.create_item(subject="[home] a new item", description=DESC, project="projects/alpha", owner=U["home-peer"], next="home-peer: start", mover="home-peer")
new = json.loads((T / f"store/{gid[0]}/{gid[1:]}.json").read_text())
check("5 a new item made by a session starts with its clock at the creation", abs(new["activity"] - new["updated"]) < 2, (gid, new.get("activity")))
# a session's filing-only update is a write about the item too
server._update("a3", sender="home-peer", priority="p1")
check("5 a session's filing edit (priority) moves it too (a write about the work by a mover)", act(3) is not None and act(3) >= t0, act(3))
# the audit agent's update through the tool
before_audit = act(3)
time.sleep(0.02)
server._update("a3", sender=AUDIT_AGENT, priority="p2")
check("5 the audit agent's update through the tool leaves it", act(3) == before_audit, (act(3), before_audit))

# ---- 6. backward compatibility
OLD_ONLY = {"id": "40", "subject": "[home] old", "description": DESC, "status": "open", "updated": OLD, "state_updated": OLD - 60, "confirmed": OLD,
            "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-peer: do the thing", "mover": "home-peer"}}
(T / "store/a/40.json").write_text(json.dumps(OLD_ONLY))
raw0 = (T / "store/a/40.json").read_bytes()
loaded = server._load("a40")
check("6 an item with no field loads unchanged (no key added by the load)", "activity" not in loaded and loaded == OLD_ONLY)
check("6 …and reads as its last update", A.at(loaded) == OLD)
check("6 …and the file is the same bytes after the reads (no migration pass)", (T / "store/a/40.json").read_bytes() == raw0)
out_without = server.stackshot_get("a40")
(T / "store/a/40.json").write_text(json.dumps({**OLD_ONLY, "activity": OLD + 5}))        # the same item, the field added
out_with = server.stackshot_get("a40")
check("6 `get` shows the same item the same with and without the field", out_without == out_with and "activity" not in out_with, (out_without, out_with))
(T / "store/a/40.json").write_bytes(raw0)
a_with = {**OLD_ONLY, "activity": OLD + 5}
check("6 the GitHub mirror's body and text are the same with and without the field",
      server._gh.body_of("a40", OLD_ONLY) == server._gh.body_of("a40", a_with) and server._gh.body_text(OLD_ONLY) == server._gh.body_text(a_with))

# ---- 7. the real call sites: each save the server makes on its own account is filed under the kind that moves (or leaves) the clock
# (the step-proof saves are driven in tests/step_proof_scenario.py, which has the checkout and pull-request fixtures they need)
telling.tell_woken = lambda *a, **k: None
telling.tell_comment = lambda *a, **k: []
server._release_after = lambda *a, **k: None
for i in range(20, 36): item(i)
t7 = time.time()
# the done check's close and its "met, waits for the decision" save
server._check_close("a20", server._load("a20"), "item_closed a2", t7)
check("7 the done check's close moves the clock (an event the check waited for)", (act(20) or 0) >= t7 and rd(20)["status"] == "completed", act(20))
server._check_wait("a21", server._load("a21"), "item_closed a2")
check("7 the done check met while the item waits on a decision moves it", (act(21) or 0) >= t7, act(21))
# the owner's comment on GitHub, stamped at the comment's own time
def comment(i, ts, cid): return server._github_comment(f"a{i}", {"id": cid, "ts": ts, "text": "go ahead", "url": "https://example.test/c"})
t_c = t7 - 300
check("7 the owner's comment on GitHub is recorded", comment(22, t_c, 1) is True)
check("7 …and moves the clock to the comment's own time, not to the time it was read", t_c - 1 <= (act(22) or 0) <= t_c + 1 and act(22) < t7 - 100, (act(22), t_c, t7))
comment(22, t7 - 100, 2)
check("7 …a later comment moves it on", abs(act(22) - (t7 - 100)) < 1, act(22))
comment(22, t7 - 5000, 3)
check("7 …a comment older than the clock never moves it back", abs(act(22) - (t7 - 100)) < 1, act(22))
comment(22, t7 + 7200, 4)
check("7 …a time in the future is cut to now", t7 <= act(22) <= time.time() + 1, (act(22), t7))
comment(23, OLD - 9000, 5)
check("7 …a backlog comment older than the item's last update leaves the clock at that update (never before what it already read)", abs(act(23) - OLD) < 1, (act(23), OLD))
# a background agent's report onto the item it names, and the same report sent by the audit
ROLES = {"team-back": {"role": "back"}, AUDIT_AGENT: {"role": "back"}, "home-front": {"role": "front"}}
IDX = {"team-back": {"name": "team-back"}, AUDIT_AGENT: {"name": AUDIT_AGENT}}
rep = server._builder_report("home-front", "a30: PR 9 is live and the suites pass. The step is merged.", "team-back", IDX, ROLES)
check("7 a builder's plain report is written onto the item (not delivered)", rep.startswith("Not delivered: written onto"), rep)
check("7 …and a message about the work moves the clock", (act(30) or 0) >= t7, act(30))
rep = server._builder_report("home-front", "a31: PR 9 is live and the suites pass. The step is merged.", AUDIT_AGENT, IDX, ROLES)
check("7 the audit's report is written onto the item too", rep.startswith("Not delivered: written onto"), rep)
check("7 …but is not activity: the clock stays at the item's last update", abs((act(31) or 0) - OLD) < 1, (act(31), OLD))
# the owner's recorded words for a wake: settle bookkeeping, not activity
writes.save("a32", server._load("a32"), note="his words recorded for the wake 2026-12-01: go (his answer), by a script")
check("7 a script copying the owner's stored words onto the wake (a save with no writer) leaves the clock", abs((act(32) or 0) - OLD) < 1, (act(32), OLD))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
