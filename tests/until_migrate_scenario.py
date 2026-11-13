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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import watchers as WK_, waiting as W, until_pass as UP, until_write as UW, stall as STALL; from stackshot.model import model as _model; from stackshot.tools import until_migrate as UM; from stackshot.tools import stamp_phase as SP
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
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
telling.tell_woken = lambda gid, owner, note, tag="wake": sent.append((gid, owner, note))
server._tell = lambda *a, **k: sent.append(("tell", a))

BASIS = {"text": f"the vendor ships {day(4)}", "wake": day(4), "by": BACK, "at": now0}
put(31, needs=[BACK])
CASES = {
    1:  ("hold + wake with the kind time", dict(needs=[BACK], wait_kind="time", hold=True, wake=day(3), state="parked")),      # a hold stored the state word parked with it: without the word the item would read as doing once the hold is gone (a new model conflict: case 14 of section 16)
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
put(12, needs=[BACK], ask_by=day(5))                        # an ask_by alone: a backstop, not a wait (not in OPEN: the route calls below name the OPEN items)
OPEN = list(CASES)

# ---- 1. the plan, pure
P = {i: UP.plan_for(mt(i)) for i in OPEN}
check("1 hold + wake with the kind time: until = the wake, the wake and the hold go, the kind stays", P[1]["edits"] == {"until": day(3), "wake": None, "hold": None} and P[1]["form"] == "hold + wake", P[1])
check("1 hold + wake + a reason: until = the wake, the hold goes, its stamp (who set it, and when) and the reason stay", P[2]["edits"] == {"until": day(4), "wake": None, "hold": None} and P[2]["form"] == "hold + wake", P[2])
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
check("3 each rewritten item stores until and none of wake, ask_by, hold; the hold's stamp stays on the one that had it", all(W.stored_until(mt(i)) and not any(k in mt(i) for k in ("wake", "ask_by", "hold")) and ("hold_set" in mt(i)) == (i == 2) for i in (1, 2, 3, 4, 5, 10)), {i: wk(mt(i)) for i in (1, 2, 3, 4, 5, 10)})
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
_wt_update.stackshot_update("g41", sender=BACK, hold=True, wake=day(4), wait_basis=BASIS["text"])
_wt_update.stackshot_update("g42", sender=BACK, ask_by=day(5), wait_reason="the vendor replies only after that date")
strip = lambda m: {k: v for k, v in m.items() if k in ("until", "wait_kind", "wake", "ask_by", "hold")}      # the pass also keeps the hold's stamp (hold_set); update drops it with the hold
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
check("7 apply asks for the plan first (a dry call), writes the undo file, ends with the left-over exit code (3, not a failure) for the refused and listed items it names", rc1 == UM.EXIT_LEFT_OVER == 3 and out1["refused_in_the_plan"] == [BOARD + "11"] and app.log[0] == "until-dry" and "until" in app.log and undo_file.is_file() and out1["results"].get("set") == 6, (rc1, out1, app.log))
check("7 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == 6, seen_undo)
bk = pathlib.Path(out1["backup"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("7 …the backup holds every touched file byte for byte as it was, and only those", sorted(p.name for p in bk.glob("*.json")) == sorted(f"g{i}.json" for i in (1, 2, 3, 4, 5, 10))
      and all((bk / f"g{i}.json").read_bytes() == json.dumps({**json.loads(snapS0[f'{i}.json'])}, ensure_ascii=False, indent=1).encode() or json.loads((bk / f"g{i}.json").read_text()) == json.loads(snapS0[f"{i}.json"]) for i in (1, 2, 3, 4, 5, 10)), sorted(p.name for p in bk.glob("*")))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("7 …the undo file names each item with its keys before and after and the real result", {"pass_id", "by", "when", "store", "backup", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("7 the pass left each touched file as the route wrote it: until stored, no old field", all(W.stored_until(mt(i)) and "wake" not in mt(i) for i in (1, 2, 3, 4, 5, 10)), None)
rc2, out2 = cli(UM.apply)
check("7 a second apply rewrites nothing", rc2 == 3 and out2["rewritten"] == 0 and BOARD + "11" in out2["left_over"], (rc2, out2))
_wt_update.stackshot_update("g3", sender=BACK, until=day(3), wait_reason="the vendor replies only after that date")     # a session changes a key the pass wrote, on one item
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
      and "items the pass would write:" in p.stdout and "a second pass: " in p.stdout
      and "a bare ask_by is a backstop" in p.stdout and "a refused item keeps its old fields untouched" in p.stdout and "update(until=...)" in p.stdout and UM.human_date(UM.alias_date()) in p.stdout, (p.returncode, p.stdout[-900:], p.stderr[-600:]))

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
check("9 a new apply finds nothing to rewrite, and the crashed pass is not named any more: its results are taken from the server's record and written into its undo file", cli(UM.apply)[1]["rewritten"] == 0 and UM.unfinished(RUN2) == []
      and [e["result"] for e in json.loads(undo2[0].read_text())["items"]] == ["set"] * 6, (UM.unfinished(RUN2), [e["result"] for e in json.loads(undo2[0].read_text())["items"]]))
rc9, out9 = cli(UM.undo, undo=str(undo2[0]))
check("9 the undo of the crashed pass puts back all six (the entries are taken from the server's pass record)", rc9 == 0 and out9["results"] == {"set": 6} and snapshot().keys() == snapC0.keys() and all({k: v for k, v in mt(i).items()} == {k: v for k, v in json.loads(snapC0[f"{i}.json"])["metadata"].items()} for i in (1, 2, 3, 4, 5, 10)), (rc9, out9))
fresh(OPEN)
seen2 = set(RUN2.glob("*/undo.json"))
try:
    cli(UM.apply, app=DyingApp())
except RuntimeError:
    pass
undo3 = (set(RUN2.glob("*/undo.json")) - seen2).pop()          # the file this run made (pass ids sort by the second, so "the last" is not reliable)
pid3 = json.loads(undo3.read_text())["pass_id"]
(pathlib.Path(_cfg_.state("migration", f"{pid3}.json"))).unlink()          # the server's record is gone too: the planned entries stand
check("9 with no pass record the crashed pass stays unfinished, and a later apply says to undo the later pass files first", UM.unfinished(RUN2) == [undo3], UM.unfinished(RUN2))
_err = io.StringIO()
with contextlib.redirect_stderr(_err), contextlib.redirect_stdout(io.StringIO()):
    UM.apply(argparse.Namespace(**vars(args)), DirectApp())
check("9 …and says that undoing it alone reverts items a later apply wrote", "undo the later pass files first" in _err.getvalue() and str(undo3) in _err.getvalue(), _err.getvalue()[-400:])
rc9, out9 = cli(UM.undo, undo=str(undo3))
check("9 …and with no pass record either, the planned entries (which hold no clock value) put back all six", rc9 == 0 and out9["results"] == {"set": 6} and all(wk(mt(i)) == wk(json.loads(snapC0[f"{i}.json"])["metadata"]) and "stall" not in mt(i) for i in (1, 2, 3, 4, 5, 10)), (rc9, out9))

check("9 an undone pass is no longer named as unfinished", UM.unfinished(RUN2) == [] and json.loads(undo3.read_text()).get("undone"), UM.unfinished(RUN2))
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

# ---- 12. an undo sees a later save of a neighbouring wait key; an item edited between the plan and the write, then a crash
CFGM["migration"] = True
put(91, needs=[BACK], wait_kind="time", hold=True, wake=day(3), state="parked")
st_, d_ = call(op="until", items=["g91"])
ent91 = {k: d_["results"][0][k] for k in ("item", "before", "after", "history", "dropped")}
check("12 the entry names every wait key, changed or not", d_["results"][0]["action"] == "set" and set(ent91["before"]) == set(UP.KEYS) == set(ent91["after"]), ent91)
_wt_update.stackshot_update("g91", sender=BACK, after=["g31"], wait_kind="item")          # a session changes the kind, a key the pass did not change
neighbour = wk(mt(91))
st_, d_ = call(op="ununtil", items=[ent91])
check("12 a later save that changed a key the pass left alone makes the undo answer kept, and the item is untouched (no hold beside the after link)", d_["results"][0]["action"] == "kept" and wk(mt(91)) == neighbour and "hold" not in mt(91) and "wake" not in mt(91), (d_["results"][0]["action"], wk(mt(91))))
check("12 the entry's sides carry no key the dry-run row would print as changed beyond the pass's own", [k for k in ent91["after"] if ent91["after"][k] != ent91["before"][k]] == ["until", "wake", "hold"] or sorted(k for k in ent91["after"] if ent91["after"][k] != ent91["before"][k]) == ["hold", "until", "wake"], ent91)

class EditingDyingApp(DirectApp):
    """A session edits the item after the plan was made and before the write; then the call fails after the server wrote."""
    def __init__(self, gid, **meta): super().__init__(); self.gid, self.meta = gid, meta
    def call(self, body):
        if body["op"] == "until" and not body.get("dry"):
            put(int(self.gid[1:]), **self.meta)
        out = super().call(body)
        if body["op"] == "until" and not body.get("dry"):
            raise RuntimeError("the connection dropped after the batch was written")
        return out
def crashed(gid, drop_record):
    put(int(gid[1:]), needs=[BACK], hold=True, wake=day(3))
    args2 = argparse.Namespace(sender=SENDER, run_dir=str(RUN2), undo="")
    seen = set(RUN2.glob("*/undo.json"))
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            UM.apply(args2, EditingDyingApp(gid, needs=[BACK], hold=True, wake=day(9)))
    except RuntimeError:
        pass
    f = (set(RUN2.glob("*/undo.json")) - seen).pop()
    if drop_record:
        pathlib.Path(_cfg_.state("migration", f"{json.loads(f.read_text())['pass_id']}.json")).unlink()
    return f
f1 = crashed("g92", False)
rc, o1 = cli(UM.undo, undo=str(f1))
check("12 an item edited between the plan and the write, then a crash: the undo takes the real entry from the server's record and puts the edited item's own wake back", not o1["kept_because_a_later_save_changed_them"] and mt(92).get("wake") == day(9) and mt(92).get("hold") is True and "until" not in mt(92), (o1, wk(mt(92))))
f2 = crashed("g93", True)
rc, o2 = cli(UM.undo, undo=str(f2))
check("12 …and with the record gone the planned entry no longer matches the item: kept, and the item is left as the pass wrote it", o2["kept_because_a_later_save_changed_them"] == [BOARD + "93"] and mt(93).get("until") == day(9) and "wake" not in mt(93), (o2, wk(mt(93))))
CFGM["migration"] = False

import shutil

# ---- 13. a date nothing watched before: already due is not migrated; a future one is, and is listed as newly watched
CFGM["migration"] = True
put(95, needs=[BACK], after=["g31"], ask_by=day(-30)); b95 = bytes_of(95)
put(96, needs=[BACK], after=["g31"], ask_by=day(6))
put(98, needs=[BACK], after=["g31"], wake=day(-2))
sent.clear()
snap_before = {i: bytes_of(i) for i in (95, 98)}
st_, d_ = call(op="until", items=["g95", "g96", "g98"], dry=True)
r13 = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("13 a past ask_by beside an after link and no kind (never watched) is listed as already due and not rewritten", r13[95]["action"] == "kept" and r13[95]["due"] is True and "already due" in r13[95]["why"] and not r13[95]["after"], r13[95])
check("13 …so does a past wake in that form", r13[98]["action"] == "kept" and r13[98]["due"] is True, r13[98])
check("13 a future ask_by in that form is rewritten (the decided one-date model) and listed as newly watched, with its day", r13[96]["action"] == "would_set" and r13[96]["newly"] == day(6) and UM.watch_lines(list(r13.values())) == ([BOARD + "95", BOARD + "98"], [f"{BOARD}96 wakes on {UM.human_date(day(6))} (never watched)"]) and r13[98]["how"] == "previously only a notice", UM.watch_lines(list(r13.values())))
st_, d_ = call(op="until", items=["g95", "g96", "g98"])
check("13 the write leaves the due items byte for byte and rewrites the future one", bytes_of(95) == b95 and {i: bytes_of(i) for i in (95, 98)} == snap_before and mt(96).get("until") == day(6) and mt(96).get("wait_kind") == "item" and "ask_by" not in mt(96), (wk(mt(96))))
before_ticks = {i: bytes_of(i) for i in (95, 96, 98)}
woke13 = wakes_svc.wake_pass(); watched13 = watching_svc.watch_pass()
check("13 a wake pass and a watch pass after the migration change none of the three items and message no one about the two a person has to look at or the migrated one (the old-form wake pass already notes a past wake with its own wording, unchanged)", {i: bytes_of(i) for i in (95, 96)} == {i: before_ticks[i] for i in (95, 96)} and not [x for x in sent if x[0] in ("g95", "g96")], (woke13, watched13, sent[-3:]))
# the apply prints both lists, plans again before it writes, and refuses a plan that changed
put(97, needs=[BACK], hold=True, wake=day(3))                       # an ordinary item for the apply to write
put(101, needs=[BACK], after=["g31"], ask_by=day(7))                # a future date nothing watched before: the apply lists it as newly watched
class ChangingApp(DirectApp):
    """After the first plan, a new already-due item appears (a session saved it)."""
    def __init__(self): super().__init__(); self.plans = 0; self.first = None
    def call(self, body):
        if body["op"] == "until" and body.get("dry"):
            self.first = self.first or body["items"][0]
            if body["items"][0] == self.first:          # the first chunk of a plan
                self.plans += 1
                if self.plans == 1:             # while the first plan is read: the second plan lists the candidates again and finds it
                    put(99, needs=[BACK], after=["g31"], ask_by=day(-5))
        return super().call(body)
run4 = pathlib.Path(_scratch.mkdtemp(prefix="untilmig-run4-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(run4), undo="")
snap13 = snapshot()
_e = io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(io.StringIO()):
    rcA = UM.apply(argparse.Namespace(**vars(args)), ChangingApp())
check("13 the apply prints the newly watched and the already due lists before it writes", "newly watched:" in _e.getvalue() and "already due, not migrated:" in _e.getvalue() and f"{BOARD}101 wakes on {UM.human_date(day(7))}" in _e.getvalue(), _e.getvalue()[-500:])
check("13 an already due item that appeared after the first plan stops the write: exit 1, no file changed, no undo file", rcA == 1 and "changed while the plan was being read" in _e.getvalue() and {k: v for k, v in snapshot().items() if k != "99.json"} == snap13 and not list(run4.glob("*/undo.json")), (rcA, _e.getvalue()[-300:]))
_e = io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(io.StringIO()):
    rcB = UM.apply(argparse.Namespace(**{**vars(args), "allow_changed_plan": True}), DirectApp())
check("13 --allow-changed-plan applies it, and the exit code says items were left over", rcB == 3 and "applied with items left over" in _e.getvalue() and mt(97).get("until") == day(3), (rcB, _e.getvalue()[-300:]))
# --plan: the dry run's file; a changed list stops the apply
planfile = run4 / "plan.json"
st_, dd = call(op="until", items=[f"g{i}" for i in (95, 96, 98, 99)], dry=True)
planfile.write_text(json.dumps(dd["results"]))
put(100, needs=[BACK], after=["g31"], ask_by=day(-9))
_e = io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(io.StringIO()):
    rcC = UM.apply(argparse.Namespace(**{**vars(args), "plan": str(planfile)}), DirectApp())
check("13 --plan: a due item the dry run in the file did not show stops the apply", rcC == 1 and "differ from the dry run in --plan" in _e.getvalue(), (rcC, _e.getvalue()[-300:]))
# the catalog renames: a language without the key reads English, an unknown key shows itself
import stackshot.web.i18n as _i18n
check("13 the History wording keys (backstop set and cleared) read in a language that has no catalog for them, and the old keys are gone with no caller", _i18n.t("item.log.backstop_set", lang="zz", when="Fri Nov 13th") == "backstop set to Fri Nov 13th" and _i18n.t("item.log.backstop_cleared", lang="zz") == "backstop cleared"
      and not subprocess.run(["grep", "-rn", "reminder_set\\|reminder_cleared", os.path.join(STACK, "stackshot")], capture_output=True, text=True).stdout.strip(), None)
shutil.rmtree(run4, ignore_errors=True)
CFGM["migration"] = False

# ---- 14. what the old code did not act on is defined by what it read: a hold kept by a recycle with an ask_by and no kind, a wake beside an after link, the boundaries of "already due"
import datetime as _dtm
CFGM["migration"] = True
tzone = server._cfg.tz()
nowz = _dtm.datetime.now(tzone)
stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M")
put(102, needs=[BACK], hold=True, hold_set={"at": now0 - DAY, "by": BACK}, recycle={"at": now0}, ask_by=day(-30)); b102 = bytes_of(102)
put(103, needs=[BACK], hold=True, hold_set={"at": now0 - DAY, "by": BACK}, recycle={"at": now0}, ask_by=day(8))
put(104, needs=[BACK], hold=True, wake=day(-3), hold_set={"at": now0 - DAY, "by": BACK})            # a hold with a wake: the old pass released it at the date (consumed), whatever the date
put(105, needs=[BACK], after=["g31"], wake=day(5))
sent.clear()
st_, d_ = call(op="until", items=[f"g{i}" for i in (102, 103, 104, 105)], dry=True)
r14 = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("14 a hold kept by a recycle with a past ask_by and no kind (nothing read that date) is listed as already due and not rewritten", r14[102]["action"] == "kept" and r14[102]["due"] is True and r14[102]["how"] == "never watched" and "already due" in r14[102]["why"], r14[102])
check("14 …with a future ask_by it is rewritten and listed as newly watched, never watched before", r14[103]["action"] == "would_set" and r14[103]["newly"] == day(8) and r14[103]["how"] == "never watched" and UM.watch_lines([r14[103]])[1] == [f"{BOARD}103 wakes on {UM.human_date(day(8))} (never watched)"], r14[103])
check("14 a hold with a wake is consumed by the old wake pass: it is neither listed as due nor as newly watched, whatever the date", r14[104]["action"] in ("would_set", "refused") and not r14[104]["due"] and not r14[104]["newly"], r14[104])
check("14 a wake beside an after link is listed as previously only a notice", r14[105]["action"] == "would_set" and r14[105]["newly"] == day(5) and r14[105]["how"] == "previously only a notice", r14[105])
st_, d_ = call(op="until", items=["g102", "g103"])
before_t = bytes_of(102), bytes_of(103)
woke14 = wakes_svc.wake_pass(); watched14 = watching_svc.watch_pass()
check("14 the write leaves the due one byte for byte, and a wake and a watch pass change neither it nor the future one, and message nobody about them", bytes_of(102) == b102 and (bytes_of(102), bytes_of(103)) == before_t and mt(103).get("until") == day(8) and mt(103).get("hold") is True and not [x for x in sent if x[0] in ("g102", "g103")], (woke14, watched14, sent[-2:]))
# the boundaries: the day itself (a date alone is the start of that day), tomorrow, an hour ago, an hour ahead
cases = {106: (nowz.strftime("%Y-%m-%d"), True), 107: ((nowz + _dtm.timedelta(days=1)).strftime("%Y-%m-%d"), False), 108: (stamp(nowz - _dtm.timedelta(hours=1)), True), 109: (stamp(nowz + _dtm.timedelta(hours=1)), False)}
for i, (dte, _due) in cases.items():
    put(i, needs=[BACK], after=["g31"], ask_by=dte)
st_, d_ = call(op="until", items=[f"g{i}" for i in cases], dry=True)
r14b = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("14 already due at the boundaries: today's date alone and an hour ago are due and left; tomorrow and an hour ahead are migrated and listed as newly watched", all(r14b[i]["due"] is _due and r14b[i]["action"] == ("kept" if _due else "would_set") and bool(r14b[i]["newly"]) is (not _due) for i, (_d, _due) in cases.items()), {i: (r14b[i]["action"], r14b[i]["due"], r14b[i]["newly"]) for i in cases})
# the signature carries the date and how it was read
sg = lambda d, how="never watched": UM.signature([{"item": "x", "action": "would_set", "newly": d, "how": how}])
check("14 the plan signature changes with the newly watched date and with how it was read", sg("2026-01-01") != sg("2026-01-02") and sg("2026-01-01") != sg("2026-01-01", "previously only a notice") and UM.signature([{"item": "x", "action": "kept", "due": True}]) != UM.signature([]), None)
class DateChangingApp(DirectApp):
    """While the second plan is read, a newly watched date is moved by a session."""
    def __init__(self): super().__init__(); self.first = None; self.plans = 0
    def call(self, body):
        if body["op"] == "until" and body.get("dry"):
            self.first = self.first or body["items"][0]
            if body["items"][0] == self.first:
                self.plans += 1
                if self.plans == 2:             # item 107 is in both plans; its date moves as the second is read
                    put(107, needs=[BACK], after=["g31"], ask_by=(nowz + _dtm.timedelta(days=3)).strftime("%Y-%m-%d"))
        return super().call(body)
run5 = pathlib.Path(_scratch.mkdtemp(prefix="untilmig-run5-"))
_e = io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(io.StringIO()):
    rcD = UM.apply(argparse.Namespace(sender=SENDER, run_dir=str(run5), undo=""), DateChangingApp())
check("14 a newly watched date that moved between the plans stops the write (the signature carries the date)", rcD == 1 and "changed while the plan was being read" in _e.getvalue() and not list(run5.glob("*/undo.json")), (rcD, _e.getvalue()[-300:]))
shutil.rmtree(run5, ignore_errors=True)
# 15 a planned newly watched date that comes due between the second plan and the write: the write leaves it, and the apply says so
for f in (T / "store").glob("*/*.json"): f.unlink()
put(150, needs=[BACK], wait_kind="anchor", ask_by=day(6))
class PassingApp(DirectApp):
    """The date of the one planned item moves into the past after the second plan is read, before the first write."""
    def call(self, body):
        if body["op"] == "until" and not body.get("dry") and not getattr(self, "moved", False):
            self.moved = True; put(150, needs=[BACK], wait_kind="anchor", ask_by=day(-3))
        return super().call(body)
run6 = pathlib.Path(_scratch.mkdtemp(prefix="untilmig-run6-"))
_e, _o = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(_o):
    rcP = UM.apply(argparse.Namespace(sender=SENDER, run_dir=str(run6), undo="", plan="", allow_changed_plan=False), PassingApp())
check("15 an item the write leaves because its planned date came due is left over: exit 3, named, the file unchanged", rcP == 3 and f"{BOARD}150" in _e.getvalue() and mt(150).get("until") is None and mt(150).get("ask_by") == day(-3) and '"left_by_the_write"' in _o.getvalue(), (rcP, _e.getvalue()[-400:]))
shutil.rmtree(run6, ignore_errors=True)
CFGM["migration"] = False

# ---- 16. the review lows: left-over class, undo of a closed item, stall, hold_set, padded dates, differing releases, dates in words, the run's lock, prune, watch_reason, conflicts
CFGM["migration"] = True
for f in (T / "store").glob("*/*.json"): f.unlink()
import fcntl
def new_run(tag): return pathlib.Path(_scratch.mkdtemp(prefix=f"untilmig-{tag}-"))
def run_args(run, **kw): return argparse.Namespace(sender=SENDER, run_dir=str(run), undo="", plan="", allow_changed_plan=False, store="", **kw)
def quiet(fn, a, app=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(a, app or DirectApp())
    try: return rc, json.loads(out.getvalue()), err.getvalue()
    except ValueError: return rc, out.getvalue(), err.getvalue()
def close_file(i):
    d = raw(i); d["status"] = "completed"; d["metadata"] = {k: v for k, v in d["metadata"].items() if k not in ("wake", "until", "hold", "hold_set", "wait_kind")}
    (T / f"store/g/{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))

# 16.1 an item that closes between the plan and the write joins the left-over class
put(201, needs=[BACK], hold=True, wake=day(3)); put(202, needs=[BACK], hold=True, wake=day(3)); put(205, needs=[BACK], hold=True, wake=day(3))
class ClosingApp(DirectApp):
    """A session closes item 202 after the plan was made and before the write."""
    def call(self, body):
        if body["op"] == "until" and not body.get("dry") and not getattr(self, "closed", False):
            self.closed = True; close_file(202)
        return super().call(body)
run16 = new_run("r16")
rc, o, e = quiet(UM.apply, run_args(run16), ClosingApp())
check("16.1 an item closed between the plan and the write is left over, not a failure: exit 3, named, the others rewritten", rc == 3 and o["closed_since_the_plan"] == [BOARD + "202"] and o["results"] == {"set": 2, "closed since the plan": 1}
      and mt(201).get("until") == day(3) and mt(205).get("until") == day(3) and raw(202)["status"] == "completed" and "closed since the plan" in e, (rc, o, e[-300:]))
check("16.1 …its undo entry is final (refused), so the pass is not named unfinished and an undo skips it", [x["result"] for x in json.loads(pathlib.Path(o["undo"]).read_text())["items"] if x["shown"] == BOARD + "202"] == ["refused"] and UM.unfinished(run16) == [], None)

# 16.2 the undo of an item that closed since: kept (exit 0), and the file is marked undone only when no item is unfinished
put(206, needs=[BACK], hold=True, wake=day(3)); put(207, needs=[BACK], hold=True, wake=day(3))
rc, o, _ = quiet(UM.apply, run_args(run16))
undo16 = o["undo"]
close_file(207)
rc, u, _ = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run16)), "undo": undo16}))
check("16.2 an item closed since the pass is kept like one a later save changed: exit 0, listed apart, the others put back", rc == 0 and u["results"] == {"set": 1, "kept": 1} and u["kept_because_closed_since_the_pass"] == [BOARD + "207"] and not u["kept_because_a_later_save_changed_them"]
      and mt(206).get("wake") == day(3) and "until" not in mt(206) and raw(207)["status"] == "completed", (rc, u))
check("16.2 …and the undo file is marked undone, in Seoul time with the zone named", json.loads(pathlib.Path(undo16).read_text()).get("undone", "").endswith(" KST"), json.loads(pathlib.Path(undo16).read_text()).get("undone"))
put(208, needs=[BACK], hold=True, wake=day(3))
rc, o, _ = quiet(UM.apply, run_args(run16)); undo_b = o["undo"]
(T / "store/g/208.json").unlink()
rc, u, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run16)), "undo": undo_b}))
check("16.2 an entry the server refuses (no such item) is a failure: exit 1, and the undo file is NOT marked undone while it is unfinished", rc == 1 and u["results"].get("refused") == 1 and not json.loads(pathlib.Path(undo_b).read_text()).get("undone") and "not marked undone" in e, (rc, u, e[-200:]))

# 16.3 stall: the keys of stall other than the log stay, a stall that is not an object is left alone, and the undo gives back the exact value
STALL3 = {"log": [{"at": now0 - 50, "text": "an earlier step"}], "paused_by": "a session", "marks": {"k": 1}}
put(209, needs=[BACK], hold=True, wake=day(3), stall=copy.deepcopy(STALL3)); put(211, needs=[BACK], hold=True, wake=day(3), stall="not an object")
run_s = new_run("stall")
rc, o, _ = quiet(UM.apply, run_args(run_s))
st209, st211 = mt(209)["stall"], mt(211).get("stall")
check("16.3 the pass keeps the other keys of stall and adds its one line to the log", st209["paused_by"] == "a session" and st209["marks"] == {"k": 1} and [x["text"] for x in st209["log"]][0] == "an earlier step" and len(st209["log"]) == 2 and "rewritten as until" in st209["log"][-1]["text"], st209)
check("16.3 a stall that is not an object is not touched, and the wait is still rewritten (no History line for it)", st211 == "not an object" and mt(211).get("until") == day(3), (st211, wk(mt(211))))
quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run_s)), "undo": o["undo"]}))
check("16.3 the undo gives back the exact stall value of each (the extra keys, the string)", mt(209).get("stall") == STALL3 and mt(211).get("stall") == "not an object" and mt(209).get("wake") == day(3), (mt(209).get("stall"), mt(211).get("stall")))

# 16.4 hold_set stays on a hold + wake item (who set the hold, and when), through the pass and the undo
HS = {"at": now0 - 3 * DAY, "by": BACK}
put(212, needs=[BACK], hold=True, wake=day(3), hold_set=HS)
rc, o, _ = quiet(UM.apply, run_args(run_s))
check("16.4 the pass keeps hold_set when it removes the hold", mt(212).get("hold_set") == HS and "hold" not in mt(212) and mt(212).get("until") == day(3), wk(mt(212)))
quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run_s)), "undo": o["undo"]}))
check("16.4 …and the undo leaves it as it was", mt(212).get("hold_set") == HS and mt(212).get("hold") is True and "until" not in mt(212), wk(mt(212)))

# 16.5 a reason bound to a date with spaces around it would be orphaned once the clean date is stored: listed, not rewritten; with no reason the padded date is rewritten
PAD = f" {day(4)} "
put(213, needs=[BACK], hold=True, wake=PAD, wait_basis={"text": "the vendor ships then", "wake": PAD, "by": BACK, "at": now0}); b213 = bytes_of(213)
put(214, needs=[BACK], hold=True, wake=PAD)
st_, d_ = call(op="until", items=["g213", "g214"])
r5 = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("16.5 a reason bound to a padded date is kept and listed (the file is untouched)", r5[213]["action"] == "kept" and "spaces around" in r5[213]["why"] and bytes_of(213) == b213, (r5[213]["action"], r5[213].get("why")))
check("16.5 …a padded date with no reason is rewritten to the clean date", r5[214]["action"] == "set" and mt(214).get("until") == day(4), (r5[214]["action"], r5[214].get("why"), wk(mt(214))))
OKB = UP.plan_for({"hold": True, "wake": day(4), "wait_basis": {"text": "x", "wake": day(4), "by": BACK, "at": now0}})
check("16.5 …and a reason bound to the very clean date still migrates (no regression)", OKB["edits"].get("until") == day(4) and not OKB["listed"], OKB)

# 16.6 a hold + wake whose release differs from the old wake pass's is listed in the plan (migrated, not held back), past or future
put(215, needs=[OWN], hold=True, wake=day(3)); put(216, needs=[BACK], hold=True, wake=day(3), post_wake_mover="home-other"); put(217, needs=[BACK], hold=True, wake=day(3))
st_, d_ = call(op="until", items=["g215", "g216", "g217"], dry=True)
r6 = {int(r["item"].split("#")[1]): r for r in d_["results"]}
check("16.6 needs naming the owner, and a post_wake_mover that is not the one session in needs, are listed with how the release differs; a plain hold + wake is not", r6[215]["action"] == "would_set" and "owner" in r6[215]["differs"] and r6[216]["action"] == "would_set" and "post_wake_mover home-other" in r6[216]["differs"]
      and r6[217]["differs"] == "", {i: (r6[i]["action"], r6[i]["differs"]) for i in r6})
check("16.6 …the plan lists them (one line each), and the signature carries them so a change stops the apply", len(UM.differ_lines(list(r6.values()))) == 2 and UM.signature(list(r6.values())) != UM.signature([{**r, "differs": ""} for r in r6.values()]), UM.differ_lines(list(r6.values())))
check("16.6 …past or future alike: the pure test does not read the date's side", UP.release_differs({"hold": True, "wake": day(-4), "needs": [OWN]}, server._model.is_owner) != "" and UP.release_differs({"wake": day(3), "needs": [OWN]}, server._model.is_owner) == "", None)
_e = io.StringIO()
with contextlib.redirect_stderr(_e), contextlib.redirect_stdout(io.StringIO()):
    UM.say_watch(list(r6.values()))
check("16.6 the apply says so before it writes", "release differs: 2 items" in _e.getvalue(), _e.getvalue())

# 16.7 dates a person reads are in the rulebook's form; machine fields stay ISO
check("16.7 human_date: weekday, three-letter month, ordinal day (st, nd, rd, th and the teens), the time of day when the date has one", [UM.human_date(x) for x in ("2026-11-24", "2026-11-01", "2026-11-12", "2026-11-23", "2026-11-13", "2026-11-11", "2026-11-24T14:30")]
      == ["Tue Nov 24th", "Sun Nov 1st", "Thu Nov 12th", "Mon Nov 23rd", "Fri Nov 13th", "Wed Nov 11th", "Tue Nov 24th 14:30"] and UM.human_date("not a date") == "not a date", None)
check("16.7 the lists a person reads use it; the signature and the JSON rows keep the ISO date", UM.watch_lines([{"item": BOARD + "1", "action": "would_set", "newly": "2026-11-24", "how": "never watched"}])[1] == [BOARD + "1 wakes on Tue Nov 24th (never watched)"]
      and UM.signature([{"item": BOARD + "1", "action": "would_set", "newly": "2026-11-24", "how": "never watched"}])[0][2] == "2026-11-24", None)
check("16.7 the stamps of a run are Seoul time with the zone named", UM.kst_stamp().endswith(" KST") and re.fullmatch(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}(st|nd|rd|th) \d\d:\d\d KST", UM.kst_stamp()) is not None
      and json.loads(pathlib.Path(o["undo"]).read_text())["when"].endswith(" KST"), (UM.kst_stamp(), json.loads(pathlib.Path(o["undo"]).read_text())["when"]))

# 16.8 the run directory's lock, a refused whole batch, the prune of old pass folders, --store with --apply
for f in (T / "store").glob("*/*.json"): f.unlink()      # only this item is a candidate below
run_l = new_run("lock"); put(218, needs=[BACK], hold=True, wake=day(3)); b218 = bytes_of(218)
os.makedirs(run_l, exist_ok=True); lock_fd = os.open(run_l / ".lock", os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(lock_fd, fcntl.LOCK_EX)
rc, o, e = quiet(UM.apply, run_args(run_l))
check("16.8 a second --apply on a locked run directory does nothing: exit 1, says why, no file changed", rc == 1 and "another --apply or --undo is running" in e and bytes_of(218) == b218 and not list(run_l.glob("*/undo.json")), (rc, e[-200:]))
fcntl.flock(lock_fd, fcntl.LOCK_UN); os.close(lock_fd)
class RefusingApp(DirectApp):
    def call(self, body):
        if body["op"] == "until" and not body.get("dry"): return 400, {"error": "Refused: the whole batch"}
        return super().call(body)
rc, o, e = quiet(UM.apply, run_args(run_l), RefusingApp())
uf = json.loads(pathlib.Path(o["undo"]).read_text())
check("16.8 a refused whole batch is recorded in the undo file (the server wrote none of it): exit 1, no entry left without a result, the pass not named unfinished", rc == 1 and [x["result"] for x in uf["items"]] == ["batch refused"] and UM.unfinished(run_l) == [] and bytes_of(218) == b218, (rc, uf["items"]))
rc, u, _ = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run_l)), "undo": o["undo"]}))
check("16.8 …and its undo has nothing to put back", rc == 0 and u["results"] == {}, (rc, u))
rc, o, e = quiet(UM.apply, run_args(run_l))
check("16.8 the lock is let go at the end: the next --apply works", rc == 0 and o["results"] == {"set": 1} and mt(218).get("until") == day(3), (rc, o))
run_p = new_run("prune"); fake_store = new_run("fakestore")
old_names = [f"2020010{n}-000000-aaaaa{n}" for n in range(1, 9)]
for n in old_names: (run_p / n / "items").mkdir(parents=True)
(run_p / "notes").mkdir(); (run_p / "20200101-000000-zzzzzz").mkdir(); os.symlink(str(fake_store), str(run_p / "20190101-000000-bbbbbb"))      # a folder not named like a pass, one with a wrong name, and a link
recent = SP.new_pass_id(); (run_p / recent).mkdir()
gone = UM.prune_runs(run_p, T / "store")
check("16.8 the prune removes the pass folders older than 60 days beyond the newest five, and only those", gone == old_names[:4] and sorted(p.name for p in run_p.iterdir() if UM.PASS_DIR_RX.fullmatch(p.name) and not p.is_symlink() and p.name != "20200101-000000-zzzzzz") == sorted(old_names[4:] + [recent]), gone)
check("16.8 …nothing else in the run directory is touched (a folder with another name, the link and what it points at)", (run_p / "notes").is_dir() and (run_p / "20190101-000000-bbbbbb").is_symlink() and (run_p / "20200101-000000-zzzzzz").is_dir() and fake_store.is_dir(), None)
inside = new_run("prune2"); (inside / "20200101-000000-cccccc").mkdir()
check("16.8 …and a folder that is, holds or lies inside the live store is never removed", UM.prune_runs(inside, inside / "20200101-000000-cccccc") == [] and UM.prune_runs(inside, inside) == [] and (inside / "20200101-000000-cccccc").is_dir()
      and UM.prune_runs(new_run("prune3"), T / "store") == [], None)
# The subprocess runs get a run directory and a HOME of their own and a server address nothing listens on: with the --store refusal gone they would otherwise run an apply against the default run directory
# (<HOME>/.local/share/stackshot-runs/until-run) and the live server. Here the worst a missing refusal does is leave a lock file in a temp folder, which the check below looks for.
sub_home = new_run("subhome"); sub_run = new_run("subrun")
sub_env = {**os.environ, "HOME": str(sub_home), "STACKSHOT_URL": "http://127.0.0.1:9"}
for opt in ("--apply", "--undo=x.json"):
    pr = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/until_migrate.py"), opt, "--sender", "x", "--store", str(T / "store"), "--run-dir", str(sub_run)], capture_output=True, text=True, env=sub_env)
    check(f"16.8 --store with {opt.split('=')[0]} is refused with a message (it would be ignored)", pr.returncode == 2 and "--store is for the dry run only" in pr.stderr, (pr.returncode, pr.stderr[-200:]))
check("16.8 …and the refusal touches nothing: the run directory is empty and the temp HOME has no run directory", not list(sub_run.iterdir()) and not (sub_home / ".local").exists(), (list(sub_run.iterdir()), list(sub_home.iterdir())))

# 16.11 the prune keeps the pass folder of an undo file that is unfinished (an entry with no result): it is the only record of what that pass wrote
run_u = new_run("keepopen")
def undo_file(folder, results, **extra):
    d = run_u / folder; (d / "items").mkdir(parents=True)
    (d / "undo.json").write_text(json.dumps({"pass_id": folder, "items": [{"item": f"g{i}", "shown": f"g{i}", "before": {}, "after": {}, "result": r} for i, r in enumerate(results, 1)], **extra}))
undo_file("20200101-000000-aaaaa1", [None, "set"])                  # an entry with no result: unfinished
undo_file("20200102-000000-aaaaa2", ["set", "same"])                 # every entry has its result
undo_file("20200103-000000-aaaaa3", [None], undone="20200104-000000 KST")      # no result, but it was undone
for n in range(4, 9): (run_u / f"2020010{n}-000000-aaaaa{n}").mkdir()
rc, o, e = quiet(UM.apply, run_args(run_u))
check("16.11 the prune keeps an old pass folder whose undo file is unfinished (and still names it), and removes the finished and the undone ones beyond the newest five",
      rc == 0 and (run_u / "20200101-000000-aaaaa1/undo.json").is_file() and not (run_u / "20200102-000000-aaaaa2").exists() and not (run_u / "20200103-000000-aaaaa3").exists()
      and "removed 2 pass folders" in e and "did not finish recording its results" in e and "20200101-000000-aaaaa1" in e, (rc, e[-400:], sorted(p_.name for p_ in run_u.iterdir())))
check("16.11 …prune_runs itself: the unfinished folder is outside the newest five and older than 60 days and stays, a second call removes nothing more",
      UM.prune_runs(run_u, T / "store") == [] and (run_u / "20200101-000000-aaaaa1").is_dir(), None)

# 16.12 --undo reads its file first: a path that is none, or no undo file, is a clean error that creates no directory and no lock; the lock is taken only at <run dir>/<pass id>/undo.json
base_u = new_run("undopath")
typo = base_u / "nope" / "20200101-000000-aaaaaa" / "undo.json"
rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_u)), "undo": str(typo)}))
check("16.12 --undo of a path that is none: exit 1, a message, and no directory and no lock created", rc == 1 and "cannot use" in e and "Traceback" not in e and not (base_u / "nope").exists() and not list(base_u.iterdir()), (rc, e[-200:], list(base_u.iterdir())))
(base_u / "run" / "20200101-000000-aaaaaa").mkdir(parents=True); (base_u / "run" / "20200101-000000-aaaaaa" / "undo.json").write_text("not json")
(base_u / "run" / "20200102-000000-aaaaaa").mkdir(); (base_u / "run" / "20200102-000000-aaaaaa" / "undo.json").write_text("[1]")
bad_ok = []
for f_ in ("20200101-000000-aaaaaa", "20200102-000000-aaaaaa"):
    rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_u)), "undo": str(base_u / "run" / f_ / "undo.json")}))
    bad_ok.append(rc == 1 and "cannot use" in e and not (base_u / "run" / ".lock").exists())
check("16.12 --undo of a file that is not JSON, or has no list of items: exit 1, a message, no lock file made", bad_ok == [True, True], bad_ok)
odd = base_u / "odd"; odd.mkdir(); (odd / "undo.json").write_text(json.dumps({"pass_id": "x", "items": []}))
rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_u)), "undo": str(odd / "undo.json")}))
check("16.12 …an undo file outside the <run dir>/<pass id>/ layout is still read and undone, with a note that no lock is taken, and no lock file appears beside it or above it", rc == 0 and "no run directory's lock is taken" in e and not (odd / ".lock").exists() and not (base_u / ".lock").exists(), (rc, e[-300:]))
good = base_u / "run" / "20200103-000000-aaaaaa"; good.mkdir(); (good / "undo.json").write_text(json.dumps({"pass_id": "20200103-000000-aaaaaa", "items": []}))
lock_fd = os.open(base_u / "run" / ".lock", os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(lock_fd, fcntl.LOCK_EX)
rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_u)), "undo": str(good / "undo.json")}))
fcntl.flock(lock_fd, fcntl.LOCK_UN); os.close(lock_fd)
check("16.12 …and a file at <run dir>/<pass id>/undo.json still takes the run directory's lock: held by another run, exit 1 and nothing done", rc == 1 and "another --apply or --undo is running" in e and "undone" not in json.loads((good / "undo.json").read_text()), (rc, e[-200:]))
rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_u)), "undo": str(good / "undo.json")}))
check("16.12 …and once the lock is let go the same undo runs", rc == 0 and "undone" in json.loads((good / "undo.json").read_text()), (rc, e[-200:]))

# 16.12b --undo checks every entry before it does anything: an entry that is no object, or lacks the item and its before and after keys, and a file nested too deep to parse, are each the same clean one-line error and exit 1, creating nothing
base_v = new_run("undoshape")
shapes_u = {"empty entry": '{"items": [{}]}', "number entry": '{"items": [1]}', "no before and after": '{"items": [{"item": "g1"}]}', "item not text": '{"items": [{"item": 5, "before": {}, "after": {}}]}',
            "deep": "[" * 100000}
bad_shape = {}
for n_, (k_, body_) in enumerate(shapes_u.items(), 1):
    d_ = base_v / "run" / f"2020020{n_}-000000-cccccc"; d_.mkdir(parents=True); (d_ / "undo.json").write_text(body_)
    rc, o, e = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(base_v)), "undo": str(d_ / "undo.json")}))
    bad_shape[k_] = rc == 1 and "cannot use" in e and "Traceback" not in e and e.count("\n") == 1 and not (base_v / "run" / ".lock").exists() and not (d_ / "items").exists() and "undone" not in (d_ / "undo.json").read_text()
check("16.12b --undo of a file with an entry that is no object or lacks item, before and after, or that is nested too deep to parse: exit 1, one clean line, no lock, nothing created or marked", all(bad_shape.values()) and len(bad_shape) == 5, bad_shape)
check("16.12b …and the same files in the run directory do not stop --apply from naming the unfinished ones (a file that cannot be read is skipped)", UM.unfinished(base_v / "run") == [], UM.unfinished(base_v / "run"))

# 16.13 a batch that gets no 4xx answer may have been written in part: its entries keep no result (the file is named unfinished and an undo can put them back); a 4xx is a refusal before any write
class WrittenThenLostApp(DirectApp):
    """The server writes the batch and the answer never arrives (a timeout: status 0)."""
    def call(self, body):
        st, d = super().call(body)
        return (0, "TimeoutError: timed out") if body["op"] == "until" and not body.get("dry") else (st, d)
class ServerErrorApp(DirectApp):
    """The server fails (5xx) before it writes anything."""
    def call(self, body):
        if body["op"] == "until" and not body.get("dry"): return 503, {"error": "unavailable"}
        return super().call(body)
put(231, needs=[BACK], hold=True, wake=day(3)); b231 = bytes_of(231); run_t = new_run("lost")
rc, o, e = quiet(UM.apply, run_args(run_t), WrittenThenLostApp())
uf = json.loads(pathlib.Path(o["undo"]).read_text())
check("16.13 a batch the server wrote whose answer never came is not recorded as refused: the entry keeps no result, the pass fails (exit 1) and says it does not know what was written",
      rc == 1 and [x["result"] for x in uf["items"]] == [None] and o["results"] == {"batch unanswered": 1} and "no answer that says what it wrote" in e and mt(231).get("until") == day(3) and bytes_of(231) != b231, (rc, uf["items"], o, e[-300:]))
rc, u, _ = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run_t)), "undo": o["undo"]}))
check("16.13 …and its undo puts the written item back (it would have skipped it as a refused batch)", rc == 0 and mt(231).get("until") is None and mt(231).get("wake") == day(3) and mt(231).get("hold") is True, (rc, u, wk(mt(231))))
b231 = bytes_of(231)
rc, o, e = quiet(UM.apply, run_args(run_t), ServerErrorApp())
uf = json.loads(pathlib.Path(o["undo"]).read_text())
check("16.13 a 5xx before any write: the same record (no result), exit 1, the item untouched", rc == 1 and [x["result"] for x in uf["items"]] == [None] and bytes_of(231) == b231, (rc, uf["items"]))
rc, u, _ = quiet(UM.undo, argparse.Namespace(**{**vars(run_args(run_t)), "undo": o["undo"]}))
check("16.13 …and its undo changes nothing and ends clean", rc == 0 and bytes_of(231) == b231, (rc, u))
(T / "store/g/231.json").unlink()

# 16.14 an unfinished undo file where the server wrote nothing: an entry whose item is open and still holds the planned `before` (not `after`) is `same`, so the file stops being unfinished; an item that holds `after`, or anything else, stays unresolved
OLD14 = dict(needs=[BACK], hold=True, wake=day(3))
def keys14(i): return {k: mt(i).get(k) for k in UP.KEYS}
put(241, **OLD14); before14 = keys14(241)
after14 = {**before14, "until": day(3), "wake": None, "hold": None}
def unrecorded(tag, items, store=None):
    """An undo file left by a run that died, one folder in a run directory of its own; every entry has no result."""
    run = new_run(tag); d = run / "20200301-000000-dddddd"; d.mkdir()
    (d / "undo.json").write_text(json.dumps({"pass_id": d.name, "store": str(store or T / "store"), "items": [{"item": g, "shown": BOARD + g[1:], "before": b, "after": a, "history": "", "dropped": [], "result": None} for g, b, a in items]}))
    return run, d / "undo.json"
run14, f14 = unrecorded("holds-before", [("g241", before14, after14)])
bytes14 = bytes_of(241)
check("16.14 an entry whose item still holds the planned before is not named unfinished, and `same` is written into the file", UM.unfinished(run14) == [] and [x["result"] for x in json.loads(f14.read_text())["items"]] == ["same"] and bytes_of(241) == bytes14, UM.unfinished(run14))
old_mig = CFGM["migration"]; CFGM["migration"] = False
rc, o, e = quiet(UM.apply, run_args(run14))
CFGM["migration"] = old_mig
check("16.14 …so a later --apply prints no 'did not finish recording' note for it", "did not finish recording" not in e and "the plan could not be made" in e, e[-300:])
check("16.14 …and the pass folder reads finished, so the prune may remove it once it is old", not UM.unfinished(run14) and {x["result"] for x in json.loads(f14.read_text())["items"]} == {"same"}, None)

put(242, needs=[BACK], until=day(3), wait_kind="time")      # the pass's own result: the item holds `after`
b242, a242 = dict(before14), keys14(242)
put(243, needs=[BACK], until=day(9), wait_kind="time")      # a later save: neither before nor after
put(244, status="done", **OLD14)                            # closed: not decided here
put(245, needs=[BACK], hold=True, wake=day(3))              # holds before, but its after is the same as its before: nothing to tell them apart
run14b, f14b = unrecorded("others", [("g242", b242, a242), ("g243", before14, after14), ("g244", before14, after14), ("g245", before14, dict(before14)), ("g249", before14, after14)])
left14 = [x["result"] for x in json.loads(f14b.read_text())["items"]]
check("16.14 an item that holds after, one that holds anything else, a closed one, one whose after equals its before and one with no file stay unresolved, and the file stays unfinished", UM.unfinished(run14b) == [f14b] and left14 == [None] * 5, left14)
check("16.14 …an unfinished file still counts for a prune: its folder is old and outside the newest five and stays", UM.prune_runs(run14b, T / "store") == [] and f14b.is_file(), None)
run14d, f14d = unrecorded("path", [("g241", before14, after14)])
rec14d = json.loads(f14d.read_text()); rec14d["items"][0]["item"] = "../../../x"
f14d.write_text(json.dumps(rec14d))
check("16.14 an item id that is no file id (a hand-edited path) is never read: the entry stays unresolved", UM.unfinished(run14d) == [f14d], UM.unfinished(run14d))
for i_ in (241, 242, 243, 244, 245): (T / f"store/g/{i_}.json").unlink()
for d_ in (run14, run14b, run14d, base_v): shutil.rmtree(d_, ignore_errors=True)

# 16.9 a front agent's watch_reason goes with the wake when the watchers end the wait (the old wake pass dropped it)
REASON = "no push reaches this session for the vendor"
put(219, needs=[BACK], wait_kind="time", until=day(-1), watch_reason=REASON)
put(221, needs=["external"], wait_kind="relay", until=day(-1), watch_reason=REASON, post_wake_mover=BACK)
woke16 = wakes_svc.wake_pass()
check("16.9 the watchers end a time wait and a relay's ask-by day and take watch_reason with them", {"g219", "g221"} <= set(woke16) and "watch_reason" not in mt(219) and "watch_reason" not in mt(221) and "until" not in mt(219), (woke16, wk(mt(219)), wk(mt(221))))
check("16.9 …the list of what the end of a wait clears names it (one list for the watcher's arrival and the owner's Done)", "watch_reason" in WK_.LIVE_DROP and "watch_reason" in WK_.DATE_DROP, None)

# 16.10 the reading check compares the model's conflicts: a hold + wake + kind time with no stored state would show a new conflict once the hold is gone, so it is refused and left
put(222, needs=[BACK], wait_kind="time", hold=True, wake=day(3)); b222 = bytes_of(222)
st_, d_ = call(op="until", items=["g222"])
check("16.10 hold + wake + wait_kind time on an item that reads as doing without the hold is refused for the conflict it would show, and left untouched", d_["results"][0]["action"] == "refused" and "conflicts:" in d_["results"][0]["why"] and "which is alive" in d_["results"][0]["why"] and bytes_of(222) == b222, d_["results"][0])
r0_, r1_ = {"pair": 1, "mover": "", "held": False, "stamp": [], "date": "", "watched": False, "conflicts": ["a"]}, {"pair": 1, "mover": "", "held": False, "stamp": [], "date": "", "watched": False, "conflicts": ["a", "b"]}
check("16.10 same(): a new conflict is a difference; the same ones, or fewer, are not", "conflicts" in UP.same(r0_, r1_) and UP.same(r1_, r0_) == "" and UP.same(r0_, r0_) == "", UP.same(r0_, r1_))
CFGM["migration"] = False
CFGM["migration"] = False
shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(RUN, ignore_errors=True); shutil.rmtree(RUN2, ignore_errors=True)
for d in (run16, run_s, run_l, run_p, fake_store, inside, sub_home, sub_run, run_u, base_u, run_t): shutil.rmtree(d, ignore_errors=True)
print(f"ok: until migrate scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
