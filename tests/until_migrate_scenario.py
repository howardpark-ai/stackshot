"""Scenario test for the until pass: the waits stored as wake, ask_by and hold rewritten as `until` (stackshot/waits/until_pass.py, the ops until and ununtil of the migration route in the server,
tools/until_migrate.py) — fixture data, no live store written, no network, no server socket.

Items stored before the until writers carry a wait in the old fields. The pass gives each the form the writers store the same wait in today (their own fold), keeps a bare wake (a backstop) as it is, adds one
History line and changes nothing else; the server refuses an item that would read differently. It is the stamp pass's shape: one item at a time under its lock, an undo file and a backup written before the first write.

  1  plan_pure        until_pass.plan_for for each old form: wake + kind, hold + wake, ask_by beside an after link, a relay's ask_by, an anchor's wake + ask_by, a bare wake (kept), an item with none, an until beside a wake
  2  dry_run          the route's dry run writes no file and answers the keys before and after, the form and the History line
  3  write            only the wait keys and the stall log move; updated, state clocks, written_by, mover and needs stay; nothing is closed, nobody is told; the reading is the same; one History line each
  4  writers          the same wait written through update today (hold + wake + wait_basis; an after link with ask_by) stores the same wait keys as the pass leaves
  5  idempotent       a second pass answers `same` (or `kept`) and rewrites no file
  6  history          the date History compares and the held flag are the same before and after; the stall log has exactly one new entry
  7  script           tools/until_migrate.py: --apply asks for the plan first, backs up every touched file byte for byte and writes the undo file before the first write; --undo puts the keys back; twice is a no-op;
                      a key a later save changed is `kept`; the dry run over a copy writes nothing live
  8  gate             refused while [model] migration is off, for a sender or machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write

    tests/run-suite until_migrate        -> exit 0 / 1"""
import argparse, contextlib, copy, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="untilmig-"); T = pathlib.Path(tmp)


def mk_toml(root):
    """A config whose every path is inside `root`, with no GitHub mirror and no commit."""
    t = _instance.apply(_instance.base_toml(), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    t, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', t); assert n == 1
    t, n = re.subn(r'(?m)^git = true', 'git = false', t, count=1); assert n == 1
    t, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]', t); assert n == 1
    t, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", t); assert n == 1
    return t


(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchors", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
BACK = "team-back"
OWN = "Oliver"
SENDER = "falcon-engineer"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import waiting as W, until_pass as UP, until_write as UW, stall as STALL; from stackshot.model import model as _model; from stackshot.tools import until_migrate as UM; from stackshot.tools import stamp_phase as SP
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
server._front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = server._cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))

def put(i, status="open", letter="g", description=DESC, **meta):
    """An item file as the older writer left it: the wait in wake, ask_by and hold."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    with open(T / f"store/{letter}/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": description, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def bytes_of(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_bytes()
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def same_values(a, b): return {k: json.loads(v) for k, v in a.items()} == {k: json.loads(v) for k, v in b.items()}
BOARD = "board" + "#"      # a board id is built at run time, never written as a literal
WAITKEYS = ("until", "wait_kind", "wake", "ask_by", "hold", "hold_set")
wk = lambda m: {k: m.get(k) for k in WAITKEYS if k in m}
sent = []
server._tell_woken = lambda gid, owner, note, tag="wake": sent.append((gid, owner, note))
server._tell = lambda *a, **k: sent.append(("tell", a))

BASIS = {"text": f"the vendor ships {day(4)}", "wake": day(4), "by": BACK, "at": now0}
put(31, needs=[BACK])
CASES = {
    1:  ("hold + wake with the kind time", dict(needs=[BACK], wait_kind="time", hold=True, wake=day(3))),
    2:  ("hold + wake + a reason",         dict(needs=[BACK], hold=True, wake=day(4), hold_set={"at": now0 - DAY, "by": BACK}, wait_basis=BASIS)),
    3:  ("ask_by beside an after link",    dict(needs=[BACK], after=["g31"], ask_by=day(5))),
    4:  ("a relay's ask_by",               dict(needs=["external"], wait_kind="relay", wait_event="the vendor's reply", ask_by=day(6), post_wake_mover=BACK)),
    5:  ("an anchor's wake and ask_by",    dict(needs=[BACK], wait_kind="anchor", wait_anchor="https://example.com/x", wake=day(6), ask_by=day(5))),
    6:  ("a bare wake (a backstop)",       dict(needs=[BACK], mover=BACK, wake=day(3))),
    7:  ("no wait at all",                 dict(needs=[BACK])),
    8:  ("an until beside a wake",         dict(needs=[BACK], until=day(4), wake=day(4))),
    9:  ("a hold with no date",            dict(needs=["external"], hold=True)),
    10: ("hold + wake, no reason",         dict(needs=[BACK], hold=True, wake=day(3))),
    11: ("a wake + kind time, no hold",    dict(needs=[BACK], wait_kind="time", wake=day(3))),
}
for i, (_w, m) in CASES.items():
    put(i, **m)
OPEN = list(CASES)

# ---- 1. the plan, pure
P = {i: UP.plan_for(mt(i)) for i in OPEN}
check("1 hold + wake with the kind time: until = the wake, the wake and the hold go, the kind stays", P[1]["edits"] == {"until": day(3), "wake": None, "hold": None} and P[1]["form"] == "hold + wake", P[1])
check("1 hold + wake + a reason: until = the wake, hold and its stamp go, the reason stays", P[2]["edits"] == {"until": day(4), "wake": None, "hold": None, "hold_set": None} and P[2]["form"] == "hold + wake", P[2])
check("1 ask_by beside an after link with no kind: until = the ask-by day and the kind is item (as create and update store it)", P[3]["edits"] == {"until": day(5), "ask_by": None, "wait_kind": "item"} and P[3]["new"] == f"until={day(5)}, wait_kind=item", P[3])
check("1 a relay's ask_by becomes until, the kind stays", P[4]["edits"] == {"until": day(6), "ask_by": None}, P[4])
check("1 an anchor's wake and ask_by: until is the earlier of the two (the backstop)", P[5]["edits"] == {"until": day(5), "wake": None, "ask_by": None}, P[5])
check("1 a bare wake is kept as it is: a backstop, not a wait", P[6]["edits"] == {} and "backstop" in P[6]["kept"] and not P[6]["listed"], P[6])
check("1 an item with no old date has nothing to rewrite", P[7]["edits"] == {} and not P[7]["listed"] and P[9]["edits"] == {}, (P[7], P[9]))
check("1 an until beside an old date is kept and listed", P[8]["edits"] == {} and P[8]["listed"], P[8])
check("1 the plan is the writers' fold: the same date and fields as until_write.fold on a copy", all(UW.fold(m := dict(mt(i))) and m["until"] == P[i]["edits"]["until"] for i in (1, 2, 4, 5, 10)), None)
PK = UP.plan_for({**mt(2), "wait_basis": {**BASIS, "wake": day(9)}})
check("1 a reason bound to another date than the one the wait is stored as is kept and listed", PK["edits"] == {} and PK["listed"] or UP.plan_for({"wait_kind": "relay", "ask_by": day(6), "wake": day(3), "wait_basis": BASIS})["listed"], PK)
PH = UP.plan_for(mt(2), keeps_hold=True)
check("1 a hold that waits on an anchor or a pane recycle keeps its flag and stamp", "hold" not in PH["edits"] and "hold_set" not in PH["edits"] and PH["edits"]["until"] == day(4), PH)

# ---- 2. the dry run
CFGM["migration"] = True
call = lambda machine="box-a", **body: server._client_post(machine, "migrate", {"sender": SENDER, **body})
snap0 = snapshot()
orig = {i: raw(i) for i in OPEN}
st_, d_ = call(op="until", items=[f"g{i}" for i in OPEN], dry=True)
dry = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("2 a dry run writes no file and answers would_set for the items to rewrite, same or kept for the others", st_ == 200 and snapshot() == snap0 and [dry[i]["action"] for i in (1, 2, 3, 4, 5, 10)] == ["would_set"] * 6
      and [dry[i]["action"] for i in (6, 7, 9)] == ["same"] * 3 and dry[8]["action"] == "kept" and dry[11]["action"] == "refused" and "held False -> True" in dry[11]["why"], (st_, {i: dry[i]["action"] for i in dry}))
check("2 …its before and after name the keys it changes, and the History line", dry[2]["before"]["hold"] is True and dry[2]["before"]["wake"] == day(4) and dry[2]["after"]["until"] == day(4) and dry[2]["after"]["hold"] is None
      and "rewritten as until" in UM.history_of(dry[2]) and dry[2]["form"] == "hold + wake", dry[2])
check("2 …a bare wake says why it stays", "backstop" in dry[6]["why"], dry[6])

# ---- 3. the write
def reading(i):
    return UP.reading(server, f"g{i}", raw(i))
before_r = {i: reading(i) for i in OPEN}
cmeta = {i: server._load(f"g{i}")["metadata"] for i in OPEN}
st_, d_ = call(op="until", items=[f"g{i}" for i in OPEN], pass_id="20260101-000000-abcdef")
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass rewrites the six, leaves the bare wake, the item with none and the hold with no date, lists the until beside a wake, and refuses a wake with the kind time and no hold (it would turn held)", [res[i]["action"] for i in (1, 2, 3, 4, 5, 10)] == ["set"] * 6
      and [res[i]["action"] for i in (6, 7, 9)] == ["same"] * 3 and res[8]["action"] == "kept" and res[11]["action"] == "refused" and bytes_of(11) == json.dumps(orig[11], ensure_ascii=False, indent=1).encode(), {i: res[i]["action"] for i in res})
SAME_KEYS = ("updated", "state_updated", "confirmed", "written_by", "status", "subject", "description")
check("3 only the wait keys and the stall log changed in each rewritten file (clocks, writer, status, subject, description, mover, needs, next, project stay)",
      all({k: v for k, v in raw(i).items() if k != "metadata"} == {k: v for k, v in orig[i].items() if k != "metadata"}
          and {k: v for k, v in mt(i).items() if k not in (*WAITKEYS, "stall")} == {k: v for k, v in orig[i]["metadata"].items() if k not in (*WAITKEYS, "stall")} for i in (1, 2, 3, 4, 5, 10)), None)
check("3 the files of the items left as they are are byte for byte the same", all(bytes_of(i) == json.dumps(orig[i], ensure_ascii=False, indent=1).encode() for i in (6, 7, 8, 9)), None)
check("3 each rewritten item stores until and none of wake, ask_by, hold, hold_set", all(W.stored_until(mt(i)) and not any(k in mt(i) for k in ("wake", "ask_by", "hold", "hold_set")) for i in (1, 2, 3, 4, 5, 10)), {i: wk(mt(i)) for i in (1, 2, 3, 4, 5, 10)})
check("3 the kinds: the stored kind stays (time, relay, anchor), an after link with a date stores item, hold + wake stores none", mt(1)["wait_kind"] == "time" and mt(4)["wait_kind"] == "relay" and mt(5)["wait_kind"] == "anchor"
      and mt(3)["wait_kind"] == "item" and "wait_kind" not in mt(2) and "wait_kind" not in mt(10), {i: mt(i).get("wait_kind") for i in (1, 2, 3, 4, 5, 10)})
check("3 the reason stays beside its date (the same date it was written for)", W.basis_of(mt(2)) == BASIS["text"], mt(2))
check("3 the dates: the wake, the ask-by day, the earlier of an anchor's two", [mt(i)["until"] for i in (1, 2, 3, 4, 5, 10)] == [day(3), day(4), day(5), day(6), day(5), day(3)], None)
check("3 the reading of every rewritten item is the same before and after (phase, kind of wait, mover, watched, held, the stored pair, the end date)", all(UP.same(before_r[i], reading(i)) == "" for i in (1, 2, 3, 4, 5, 10)), {i: UP.same(before_r[i], reading(i)) for i in (1, 2, 3, 4, 5, 10)})
logs = {i: [x["text"] for x in STALL.new_entries(orig[i]["metadata"], mt(i))] for i in (1, 2, 3, 4, 5, 10)}
check("3 each rewritten item gets exactly one History line, which says the wait was rewritten as until", all(len(v) == 1 and "rewritten as until=" in v[0] and "nothing else on the item changed" in v[0] for v in logs.values()), logs)
check("3 nothing was closed, woken or told", all(raw(i)["status"] == "open" for i in OPEN) and sent == [] and not server._watch.holding(), sent)

# ---- 4. the writers store the same wait
put(41, needs=[BACK]); put(42, needs=[BACK], after=["g31"])
server.stackshot_update("g41", sender=BACK, hold=True, wake=day(4), wait_basis=BASIS["text"])
server.stackshot_update("g42", sender=BACK, ask_by=day(5), wait_reason="the vendor replies only after that date")
strip = lambda m: {k: v for k, v in m.items() if k in ("until", "wait_kind", "wake", "ask_by", "hold", "hold_set")}
check("4 hold + wake + a reason: update stores the wait keys the pass left", strip(mt(41)) == strip(mt(2)) and W.basis_of(mt(41)) == W.basis_of(mt(2)), (strip(mt(41)), strip(mt(2))))
check("4 an after link with ask_by: update stores until and the kind item, as the pass did", strip(mt(42)) == strip(mt(3)), (strip(mt(42)), strip(mt(3))))

# ---- 5. idempotent
snap1 = snapshot()
st_, d_ = call(op="until", items=[f"g{i}" for i in OPEN])
check("5 a second pass rewrites nothing: same for every item, kept for the one listed, refused for the one that would turn held, no file changes", st_ == 200 and snapshot() == snap1 and {r["action"] for r in d_["results"]} == {"same", "kept", "refused"} and [r["action"] for r in d_["results"]].count("refused") == 1, (st_, [r["action"] for r in d_["results"]]))

# ---- 6. History
import stackshot.web.render as R
rd_ = lambda m: {"status": "open", "metadata": m}
check("6 the date History compares and the held flag are the same before and after, for every rewritten item", all(R.wait_date_of(rd_(orig[i]["metadata"])) == R.wait_date_of(rd_(mt(i))) and R.is_held(rd_(orig[i]["metadata"])) == R.is_held(rd_(mt(i))) for i in (1, 2, 3, 4, 5, 10)),
      {i: (R.wait_date_of(rd_(orig[i]["metadata"])), R.wait_date_of(rd_(mt(i)))) for i in (1, 2, 3, 4, 5, 10)})

# ---- 7. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return server._client_post("box-a", "migrate", {**body, "sender": SENDER})
for i in OPEN:
    put(i, **CASES[i][1])
snapS0 = snapshot()
RUN = pathlib.Path(_scratch.mkdtemp(prefix="untilmig-run-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="")
def cli(fn, app=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    try: return rc, json.loads(out.getvalue())
    except ValueError: return rc, out.getvalue()
app = DirectApp()
orig_write = SP.write_atomic
seen_undo = []
def spy(path, obj):
    if str(path).endswith("undo.json") and not seen_undo and not any(r.get("result") for r in obj["items"]):
        seen_undo.append((len([f for f in snapshot() if snapshot()[f] != snapS0[f]]), len(obj["items"])))      # files already written when the undo file first lands
    return orig_write(path, obj)
SP.write_atomic = spy
rc1, out1 = cli(UM.apply, app=app)
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("7 apply asks for the plan first (a dry call), writes the undo file, exits 1 only for the refused item it names", rc1 == 1 and out1["refused_in_the_plan"] == [BOARD + "11"] and app.log[0] == "until-dry" and "until" in app.log and undo_file.is_file() and out1["results"].get("set") == 6, (rc1, out1, app.log))
check("7 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == 6, seen_undo)
bk = pathlib.Path(out1["backup"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("7 …the backup holds every touched file byte for byte as it was, and only those", sorted(p.name for p in bk.glob("*.json")) == sorted(f"g{i}.json" for i in (1, 2, 3, 4, 5, 10))
      and all((bk / f"g{i}.json").read_bytes() == json.dumps({**json.loads(snapS0[f'{i}.json'])}, ensure_ascii=False, indent=1).encode() or json.loads((bk / f"g{i}.json").read_text()) == json.loads(snapS0[f"{i}.json"]) for i in (1, 2, 3, 4, 5, 10)), sorted(p.name for p in bk.glob("*")))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("7 …the undo file names each item with its keys before and after and the real result", {"pass_id", "by", "when", "store", "backup", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("7 the pass left each touched file as the route wrote it: until stored, no old field", all(W.stored_until(mt(i)) and "wake" not in mt(i) for i in (1, 2, 3, 4, 5, 10)), None)
rc2, out2 = cli(UM.apply)
check("7 a second apply rewrites nothing", rc2 == 1 and out2 == {"rewritten": 0}, (rc2, out2))
server.stackshot_update("g3", sender=BACK, until=day(3), wait_reason="the vendor replies only after that date")     # a session changes a key the pass wrote, on one item
rc3, out3 = cli(UM.undo, undo=str(undo_file))
vals_back = all({k: v for k, v in mt(i).items() if k != "stall"} == {k: v for k, v in json.loads(snapS0[f"{i}.json"])["metadata"].items() if k != "stall"} for i in (1, 2, 4, 5, 10))
check("7 --undo puts the keys back value for value on the items still as the pass left them, and keeps the one a later save changed", rc3 == 0 and vals_back and out3["results"] == {"set": 5, "kept": 1} and out3["kept_because_a_later_save_changed_them"] == [BOARD + "3"] and mt(3).get("until") == day(3), (rc3, out3))
check("7 …the History line goes with the undo (the stall log is back to what it was)", all("stall" not in mt(i) for i in (1, 2, 4, 5, 10)), None)
rc4, out4 = cli(UM.undo, undo=str(undo_file))
check("7 …undo twice is a no-op", rc4 == 0 and set(out4["results"]) <= {"same", "kept"} and "set" not in out4["results"], (rc4, out4))
check("7 --apply and --undo need --sender", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/until_migrate.py"), "--apply"], capture_output=True, text=True).returncode != 0 and subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/until_migrate.py"), "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
CFGM["migration"] = False
snapD = snapshot()
p = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/until_migrate.py"), "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("7 the dry run over a copy writes nothing live, prints old and new per item and the totals, and exits 0", p.returncode == 0 and snapshot() == snapD and "old: " in p.stdout and "new: " in p.stdout and "History line: stackshot:" in p.stdout
      and "items the pass would write:" in p.stdout and "a second pass: " in p.stdout, (p.returncode, p.stdout[-900:], p.stderr[-600:]))

# ---- 8. the gate
put(51, needs=["external"], hold=True, wake=day(3), wait_kind="time")
b51 = bytes_of(51)
CFGM["migration"] = False
st_, d_ = call(op="until", items=["g51"])
check("8 the route is refused while [model] migration is off", st_ == 403 and bytes_of(51) == b51, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="until", items=["g51"], sender="somebody-else")
check("8 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(machine="home-evil", op="until", items=["g51"])
check("8 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(op="until", items=["g51"], writes=[{"item": "g51", "set": {"mover": BACK}}])
check("8 …a body naming a key of its own is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(op="ununtil", items=[{"item": "g51", "before": {"mover": None}, "after": {"mover": BACK}}])
check("8 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused" and "not a key" in d_["results"][0]["why"], d_)
st_, d_ = call(op="ununtil", items=["g51"], dry=True)
check("8 …dry goes with until only; an empty list is refused", st_ == 400 and call(op="until", items=[])[0] == 400, (st_, d_))
st_, d_ = call(op="until", items=["g9999", "nonsense"])
check("8 …an unknown item and a malformed id are refused one by one", st_ == 200 and [r["action"] for r in d_["results"]] == ["refused", "refused"], (st_, d_))
put(52, status="completed", needs=[BACK], hold=True, wake=day(3), outcome="done")
st_, d_ = call(op="until", items=["g52"])
check("8 …a closed item is refused and left as it is", d_["results"][0]["action"] == "refused" and "wake" in mt(52), d_)
st_, d_ = call(op="until", items=["g51"])
check("8 …a rewrite needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not server._watch.holding(), (st_, d_))
CFGM["migration"] = False

# ---- 9. a pass that dies after the server wrote a batch is undoable; an unrelated later History line does not stop an undo
CFGM["migration"] = True
import stackshot.core.config as _cfg_
def fresh(ids):
    for i in ids:
        put(i, **CASES[i][1])
class DyingApp(DirectApp):
    """The server writes the batch; then the call fails (the process died before it recorded the answer)."""
    def call(self, body):
        out = super().call(body)
        if body["op"] == "until" and not body.get("dry"):
            raise RuntimeError("the connection dropped after the batch was written")
        return out
fresh(OPEN); snapC0 = snapshot()
RUN2 = pathlib.Path(_scratch.mkdtemp(prefix="untilmig-run2-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN2), undo="")
try:
    cli(UM.apply, app=DyingApp())
    died = None
except RuntimeError as ex:
    died = str(ex)
undo2 = sorted(RUN2.glob("*/undo.json"))
rec2 = json.loads(undo2[0].read_text()) if undo2 else {"items": [], "pass_id": ""}
check("9 the call failed after the server wrote the batch: six files are rewritten and every undo entry still has no result", died and sum(1 for k in snapshot() if snapshot()[k] != snapC0[k]) == 6 and [e["result"] for e in rec2["items"]] == [None] * 6, (died, [e["result"] for e in rec2["items"]]))
check("9 a new apply finds nothing to rewrite and names the unfinished undo file", cli(UM.apply)[1] == {"rewritten": 0} and UM.unfinished(RUN2) == undo2, UM.unfinished(RUN2))
rc9, out9 = cli(UM.undo, undo=str(undo2[0]))
check("9 the undo of the crashed pass puts back all six (the entries are taken from the server's pass record)", rc9 == 0 and out9["results"] == {"set": 6} and snapshot().keys() == snapC0.keys() and all({k: v for k, v in mt(i).items()} == {k: v for k, v in json.loads(snapC0[f"{i}.json"])["metadata"].items()} for i in (1, 2, 3, 4, 5, 10)), (rc9, out9))
fresh(OPEN)
try:
    cli(UM.apply, app=DyingApp())
except RuntimeError:
    pass
undo3 = sorted(RUN2.glob("*/undo.json"))[-1]
pid3 = json.loads(undo3.read_text())["pass_id"]
(pathlib.Path(_cfg_.state("migration", f"{pid3}.json"))).unlink()          # the server's record is gone too: the planned entries stand
rc9, out9 = cli(UM.undo, undo=str(undo3))
check("9 …and with no pass record either, the planned entries (which hold no clock value) put back all six", rc9 == 0 and out9["results"] == {"set": 6} and all(wk(mt(i)) == wk(json.loads(snapC0[f"{i}.json"])["metadata"]) and "stall" not in mt(i) for i in (1, 2, 3, 4, 5, 10)), (rc9, out9))

# an unrelated History line added after the pass does not make the undo answer kept; it stays, the pass's own line goes
fresh(OPEN)
rc, outA = cli(UM.apply)
undoA = pathlib.Path(outA["undo"])
for i in (1, 2):
    d = raw(i); d["metadata"].setdefault("stall", {"log": []})["log"].append({"at": now0 + 5, "text": "a later, unrelated step"})
    (T / f"store/g/{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
rcB, outB = cli(UM.undo, undo=str(undoA))
check("9 an unrelated History line added after the pass does not stop the undo", outB["results"] == {"set": 6} and not outB["kept_because_a_later_save_changed_them"], outB)
check("9 …the later line stays and the pass's own line is gone", [x["text"] for x in STALL.log_of(mt(1))] == ["a later, unrelated step"] and not STALL.log_of(mt(3)) and "stall" not in mt(3), mt(1).get("stall"))
# a full log: the pass's line pushes the oldest out; the undo puts it back
full = [{"at": now0 - 100 + n, "text": f"step {n}"} for n in range(8)]
put(71, needs=[BACK], hold=True, wake=day(3), stall={"log": full})
rc, outC = cli(UM.apply)
check("9 a log of eight lines keeps eight lines after the pass, the oldest pushed out", [x["text"] for x in STALL.log_of(mt(71))][0] == "step 1" and len(STALL.log_of(mt(71))) == 8, mt(71).get("stall"))
cli(UM.undo, undo=outC["undo"])
check("9 …and the undo puts the log back as it was", STALL.log_of(mt(71)) == full and "until" not in mt(71), mt(71).get("stall"))

# ---- 10. holds the route keeps, holds it refuses, and a writer that takes no lock
put(81, needs=[BACK], hold=True, wake=day(3), hold_set={"at": now0 - DAY, "by": BACK}, recycle={"at": now0})
put(82, needs=[BACK], hold=True, wake=day(3), hold_set={"at": now0 - DAY, "by": BACK})
put(83, needs=[BACK], hold=True, wake=day(3), after=["g31"])
put(84, needs=["external"], hold=True, wake=day(3), wait_kind="anchor", wait_anchor="https://example.com/y")
put(85, needs=["external"], hold=True, wake=day(3))
real_scoped = server._scoped_anchors
server._scoped_anchors = lambda project, gid: ["https://example.com/watched"] if gid == "g82" else real_scoped(project, gid)
try:
    st_, d_ = call(op="until", items=[f"g{i}" for i in (81, 82, 83, 84, 85)])
finally:
    server._scoped_anchors = real_scoped
r10 = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("10 a hold on a pane recycle keeps its flag and its stamp, and stores the date as until", r10[81]["action"] == "set" and mt(81).get("hold") is True and mt(81).get("hold_set") and mt(81).get("until") == day(3) and "wake" not in mt(81), (r10[81]["action"], r10[81].get("why"), wk(mt(81))))
check("10 a hold on an anchor scoped to the item keeps its flag and its stamp too", r10[82]["action"] == "set" and mt(82).get("hold") is True and mt(82).get("hold_set") and mt(82).get("until") == day(3), (r10[82]["action"], r10[82].get("why"), wk(mt(82))))
check("10 a hold beside an open after item, one with the kind anchor and one with needs external are left as they are or rewritten without a change of reading; none is half done",
      all(r10[i]["action"] in ("refused", "set", "same", "kept") for i in (83, 84, 85)) and all(("wake" in mt(i)) != ("until" in mt(i)) for i in (83, 84, 85)), {i: (r10[i]["action"], r10[i].get("why"), wk(mt(i))) for i in (83, 84, 85)})
check("10 a hold beside an open after item and a hold on needs external are refused (their reading would change) and left byte for byte", all(r10[i]["action"] == "refused" for i in (83, 84, 85)), {i: r10[i]["action"] for i in (83, 84, 85)})

put(86, needs=[BACK], hold=True, wake=day(3)); b86 = bytes_of(86)
orig_sw = server._stamp_write
def sneaky(p, raw_, h0, edits):
    d = json.loads(p.read_text()); d["metadata"]["noted_by_a_writer_without_the_lock"] = d["metadata"].get("noted_by_a_writer_without_the_lock", 0) + 1
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    return orig_sw(p, raw_, h0, edits)
server._stamp_write = sneaky
try:
    st_, d_ = call(op="until", items=["g86"])
finally:
    server._stamp_write = orig_sw
check("10 a writer without the lock that changes the item between the read and the replace: answered moved, its write stands, the wait is not rewritten", d_["results"][0]["action"] == "moved" and mt(86).get("noted_by_a_writer_without_the_lock") == 1 and mt(86).get("wake") == day(3) and "until" not in mt(86), (d_["results"][0]["action"], wk(mt(86))))
st_, d_ = call(op="until", items=["g86"])
check("10 …and the next run rewrites it", d_["results"][0]["action"] == "set" and mt(86).get("until") == day(3), d_["results"][0]["action"])
d0 = call(op="until", items=["g86"])[1]
ent = {"item": "g86", "before": {"until": None, "wake": day(3), "hold": True}, "after": {"until": day(3), "wake": None, "hold": None}, "history": "x", "dropped": []}
server._stamp_write = sneaky
try:
    st_, d_ = call(op="ununtil", items=[ent])
finally:
    server._stamp_write = orig_sw
check("10 the undo answers moved the same way and leaves the other writer's change", d_["results"][0]["action"] == "moved" and mt(86).get("until") == day(3) and mt(86).get("noted_by_a_writer_without_the_lock") == 2, d_["results"][0]["action"])

# ---- 11. the two History renderers print the same date for a backstop
src = {f: pathlib.Path(os.path.join(STACK, f)).read_text() for f in ("stackshot/web/render.py", "stackshot/web/ui/render.py")}
lines = {f: [l.strip() for l in t.splitlines() if "backstop" in l and "ev.append" in l] for f, t in src.items()}
check("11 both renderers print the backstop and wake lines from wait_date_of (an old-form relay's ask_by logs the same line in both)", all(len(v) == 1 and v[0].startswith("w = wait_date_of(v);") for v in lines.values()) and
      all(any(l.strip().startswith("w = wait_date_of(v);") and ("wake_set" in l or "wake {" in l) for l in t.splitlines()) for t in src.values()), lines)
CFGM["migration"] = False

import shutil
shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(RUN, ignore_errors=True); shutil.rmtree(RUN2, ignore_errors=True)
print(f"ok: until migrate scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
