"""Scenario test for the mover pass: the picker of a waiting item stored as `mover` instead of the old key `post_wake_mover` (stackshot/waits/mover_pass.py, the ops mover and unmover of the migration route
in the server, tools/mover_migrate.py) — fixture data, no live store written, no network, no server socket.

Items stored before the one-mover change carry the picker under the old key and may carry a `then` that nothing reads. The writers store `mover` and read both keys; the pass moves the stored picker of the open
items to `mover`, drops a `then` nothing reads, turns a `then` that stood in for a picker into the picker, adds one History line and changes nothing else. The server refuses an item that would read differently.

  1  plan_pure        mover_pass.plan_for for each stored form, and for the snapshot of a turned wait (watch.was)
  2  dry_run          the route's dry run writes no file and answers the keys before and after, the form and the History line
  3  write            only the picker keys, the snapshot and the stall log move; updated, clocks, written_by, status, needs and next stay; the reading is the same; one History line each; nobody is told
  4  idempotent       a second pass answers `same` (or `kept`) and rewrites no file
  5  reading          a wait on a date alone with an external need and a stored agent picker reads the same before and after
  6  refusal          an item whose reading would change is refused and left byte for byte
  7  script           tools/mover_migrate.py: --apply asks for the plan first, backs up every touched file byte for byte and writes the undo file before the first write; --undo puts the keys back; twice is a no-op;
                      a key a later save changed is `kept`; the dry run over a copy writes nothing live
  8  gate             refused while [model] migration is off, for a sender or machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write

    tests/run-suite mover_migrate        -> exit 0 / 1"""
import argparse, contextlib, copy, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _midnight
tmp = _scratch.mkdtemp(prefix="movermig-"); T = pathlib.Path(tmp)


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
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" and "tomorrow" the checks read: start on the far side of one that is close
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
from stackshot.web import server, wiring; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import watchers as WK_, waiting as W, until_pass as UP, until_write as UW, stall as STALL, mover_pass as MP; from stackshot.model import model as _model; from stackshot.tools import until_migrate as UM; from stackshot.tools import mover_migrate as MM; from stackshot.tools import stamp_phase as SP
from stackshot.service import stamp as stamp_svc
from stackshot.service import retire_passes as retire_svc
HOST = stamp_svc.PassHost(server, stamp_svc, retire_svc, wiring.PASS_NAMES)   # the `S` of until_pass: the server module, then the stamp and retire modules that own the names it reads
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import item_read as _item_read
import stackshot.core.config as _cfg_
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.service import answer_handover as _answer_handover
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = _cfg_.CFG.setdefault("model", {})
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

PK = ("mover", "then", "post_wake_mover", "watch")
LIVE = {"home-other", BACK, "home-stew"}
live_then = lambda then, meta: then in LIVE
W = dict(needs=[BACK], wait_kind="time", until=day(3))                # a wait an agent picks up
WAS = {"wait_kind": "relay", "wait_event": "the vendor's reply", "until": day(6), "post_wake_mover": "home-other", "then": BACK, "needs": ["external"]}
CASES = {
    1:  ("the old key alone",                          dict(W, post_wake_mover="home-other")),
    2:  ("the old key equal to mover",                 dict(W, mover="home-other", post_wake_mover="home-other")),
    3:  ("the old key differing from mover",           dict(W, mover=BACK, post_wake_mover="home-other")),
    4:  ("a blank old key",                            dict(W, post_wake_mover="")),
    5:  ("the word none under the old key",            dict(W, post_wake_mover="none")),
    6:  ("the old key on an item that waits on nothing", dict(needs=[BACK], post_wake_mover=BACK)),
    7:  ("an alive item, agent mover, a then that differs", dict(needs=[BACK], mover=BACK, then="home-other")),
    8:  ("an alive item, agent mover, an equal then",   dict(needs=[BACK], mover=BACK, then=BACK)),
    9:  ("a wait an agent picks up, a then that differs", dict(W, mover=BACK, then="home-other")),
    10: ("a wait the owner picks up, with a then",     dict(W, mover=OWN, then=BACK)),
    11: ("a then that stood in for a picker",          dict(wait_kind="time", until=day(3), then="home-other")),
    12: ("a then that is no live session",             dict(wait_kind="time", until=day(3), then="home-dead")),
    13: ("an external date-only wait, a stored mover", dict(needs=["external"], until=day(3), mover=BACK)),
    14: ("an external date-only wait, the old key",    dict(needs=["external"], until=day(3), post_wake_mover=BACK)),
    15: ("a turned wait with a snapshot",              dict(needs=["decision"], watch={"asked": "relay", "was": dict(WAS), "at": now0 - DAY})),
    16: ("an until with no kind and the old key",      dict(needs=[BACK], until=day(3), post_wake_mover=BACK)),
    17: ("a relay with the old key",                   dict(needs=["external"], wait_kind="relay", wait_event="the vendor's reply", until=day(6), post_wake_mover=BACK)),
    18: ("a hold that is due, a live then",            dict(hold=True, wake=day(-1), then="home-other", wait_kind="time")),
    20: ("a then beside a session in needs",           dict(W, then="home-other")),
    21: ("a then beside an external need",             dict(needs=["external"], wait_kind="time", until=day(3), then="home-other")),
    22: ("an external date-only wait, no picker",      dict(needs=["external"], until=day(3))),
}
for i, (_w, m) in CASES.items():
    put(i, **m)
put(19, status="completed", outcome="done", **dict(W, post_wake_mover=BACK))
OPEN = list(CASES)
mod_of = lambda i: MP.prepared(HOST, f"g{i}", raw(i))[1]
plan = lambda i: MP.plan_for(mt(i), mod_of(i), live_then)

# ---- 1. the plan, pure
snap_pre = snapshot()
P = {i: plan(i) for i in OPEN}

SETS = (1, 2, 3, 4, 7, 8, 9, 11, 12, 15, 16, 17, 18, 20, 21)        # the items the pass writes
KEPT = (5, 6, 14)                                                         # listed, left as they are
SAMES = (10, 13, 22)                                                    # nothing to move
check("1 the old key alone: mover takes it, the key goes", P[1]["edits"] == {"post_wake_mover": None, "mover": "home-other"} and P[1]["new"] == "mover=home-other" and not P[1]["listed"], P[1])
check("1 the old key equal to mover: the key just goes, no row", P[2]["edits"] == {"post_wake_mover": None} and not P[2]["listed"], P[2])
check("1 the old key differing from mover: mover takes the old key (it won the reading) and the item is listed with both names", P[3]["edits"] == {"post_wake_mover": None, "mover": "home-other"} and P[3]["listed"] and "team-back" in P[3]["notes"][0] and "home-other" in P[3]["notes"][0], P[3])
check("1 a blank old key goes", P[4]["edits"] == {"post_wake_mover": None}, P[4])
check("1 the word none and an old key on an item that waits on nothing are left as they are and listed", P[5]["edits"] == {} and P[5]["listed"] and P[6]["edits"] == {} and P[6]["listed"], (P[5], P[6]))
check("1 a then beside an agent's own move is dropped: listed when it names another session, silent when it names the mover", P[7]["edits"] == {"then": None} and P[7]["listed"] and P[8]["edits"] == {"then": None} and not P[8]["listed"], (P[7], P[8]))
check("1 …on a wait an agent picks up too", P[9]["edits"] == {"then": None} and P[9]["listed"], P[9])
check("1 a then beside the owner's pick stays: it is read", P[10]["edits"] == {} and not P[10]["listed"], P[10])
check("1 a then that stood in for a picker (no stored picker, no session in needs, a live session): mover takes it, the then goes", P[11]["edits"] == {"mover": "home-other", "then": None} and P[11]["standin"] == "home-other" and not P[11]["listed"], P[11])
check("1 …a due hold with a live then is the same stand-in", P[18]["edits"] == {"mover": "home-other", "then": None} and P[18]["standin"] == "home-other", P[18])
check("1 a then that is no live session is dropped and listed, never a picker", P[12]["edits"] == {"then": None} and P[12]["standin"] == "" and P[12]["listed"], P[12])
check("1 a session in needs, or an external need, keeps a then from standing in: it is dropped and listed", P[20]["edits"] == {"then": None} and P[20]["standin"] == "" and P[21]["edits"] == {"then": None} and P[21]["standin"] == "", (P[20], P[21]))
check("1 an external date-only wait: a stored mover alone needs nothing, and the old key is left and listed (only the old key turns it at its date: as mover it would end on the date)", P[13]["edits"] == {} and P[14]["edits"] == {} and P[14]["listed"] and "external" in " ".join(P[14]["notes"]) and P[22]["edits"] == {}, (P[13], P[14], P[22]))
check("1 an until with no kind and a relay carry the old key to mover", P[16]["edits"] == {"post_wake_mover": None, "mover": BACK} and P[17]["edits"] == {"post_wake_mover": None, "mover": BACK}, (P[16], P[17]))
was15 = P[15]["edits"].get("watch", {})
check("1 the snapshot of a turned wait: the old key goes to mover, the unread then goes, the rest of the snapshot and of watch stays", set(P[15]["edits"]) == {"watch"} and was15.get("was") == {k: v for k, v in WAS.items() if k not in ("post_wake_mover", "then")} | {"mover": "home-other"}
      and was15.get("asked") == "relay" and was15.get("at") == mt(15)["watch"]["at"] and P[15]["listed"], P[15])
check("1 a plan with nothing to do carries no edits, no row and no form", all(not P[i]["form"] and not P[i]["new"] for i in (5, 6, 10, 13, 22)), None)
check("1 the plan is pure: planning every item changes no file", snapshot() == snap_pre, None)

# ---- 2. the dry run
CFGM["migration"] = True
call = lambda machine="box-a", **body: _rt_client._client_post(machine, "migrate", {"sender": SENDER, **body})
snap0 = snapshot()
orig = {i: raw(i) for i in (*OPEN, 19)}
st_, d_ = call(op="mover", items=[f"g{i}" for i in OPEN], dry=True)
dry = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("2 a dry run writes no file and answers would_set for the items to move, kept for the three it lists, same for the rest", st_ == 200 and snapshot() == snap0 and [dry[i]["action"] for i in SETS] == ["would_set"] * len(SETS)
      and [dry[i]["action"] for i in KEPT] == ["kept"] * 3 and [dry[i]["action"] for i in SAMES] == ["same"] * 3, (st_, {i: dry[i]["action"] for i in dry}))
check("2 …its before and after name the keys it changes, and the History line", dry[1]["before"]["post_wake_mover"] == "home-other" and dry[1]["before"]["mover"] is None and dry[1]["after"]["mover"] == "home-other" and dry[1]["after"]["post_wake_mover"] is None
      and "stored picker was moved to mover" in dry[1]["history"] and dry[1]["form"] == "old key home-other -> mover", dry[1])
check("2 …the route judges a then live as the server does: the stand-in is would_set with its session named; a name that is no session is not a stand-in", dry[11]["standin"] == "home-other" and dry[18]["standin"] == "home-other" and dry[12]["standin"] == "", (dry[11].get("standin"), dry[12].get("standin")))
check("2 …a kept item says why", "word none" in dry[5]["why"] and "waits on nothing" in dry[6]["why"], (dry[5]["why"], dry[6]["why"]))

# ---- 3. the write
reading = lambda i: MP.reading(HOST, f"g{i}", raw(i))
before_r = {i: reading(i) for i in OPEN}
st_, d_ = call(op="mover", items=[f"g{i}" for i in OPEN], pass_id="20260101-000000-abcdef")
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass moves the fifteen, lists the three, leaves the rest", [res[i]["action"] for i in SETS] == ["set"] * len(SETS) and [res[i]["action"] for i in KEPT] == ["kept"] * 3 and [res[i]["action"] for i in SAMES] == ["same"] * 3, {i: res[i]["action"] for i in res})
check("3 only the picker keys, the snapshot and the stall log changed in each written file (clocks, writer, status, subject, description, needs, next, project, wait keys stay)",
      all({k: v for k, v in raw(i).items() if k != "metadata"} == {k: v for k, v in orig[i].items() if k != "metadata"}
          and {k: v for k, v in mt(i).items() if k not in (*PK, "stall")} == {k: v for k, v in orig[i]["metadata"].items() if k not in (*PK, "stall")} for i in SETS), None)
check("3 the files of the items left as they are are byte for byte the same", all(bytes_of(i) == json.dumps(orig[i], ensure_ascii=False, indent=1).encode() for i in (*KEPT, *SAMES)), None)
check("3 no stored item keeps the old key on a written item, and mover holds the picker the old key won", all("post_wake_mover" not in mt(i) for i in SETS) and [mt(i)["mover"] for i in (1, 2, 3)] == ["home-other"] * 3 and [mt(i)["mover"] for i in (16, 17)] == [BACK] * 2, {i: mt(i).get("mover") for i in SETS})
check("3 an unread then is gone (alive and waiting alike), the owner's pick keeps its then", all("then" not in mt(i) for i in (7, 8, 9, 12, 20, 21)) and mt(10)["then"] == BACK and mt(10)["mover"] == OWN, None)
check("3 a stand-in becomes the picker and its then goes", mt(11)["mover"] == "home-other" and "then" not in mt(11) and mt(18)["mover"] == "home-other" and "then" not in mt(18), (mt(11), mt(18)))
check("3 the snapshot of a turned wait holds mover, not the old key, and no unread then", mt(15)["watch"]["was"].get("mover") == "home-other" and "post_wake_mover" not in mt(15)["watch"]["was"] and "then" not in mt(15)["watch"]["was"], mt(15)["watch"])
check("3 the reading of every written item is the same before and after (phase, kind of wait, mover, watched, held, picker, then, needs, end date, who takes it back on `not yet`); a stand-in's picker is the one change",
      all(MP.same(before_r[i], reading(i), res[i]["standin"]) == "" for i in SETS), {i: MP.same(before_r[i], reading(i), res[i]["standin"]) for i in SETS if MP.same(before_r[i], reading(i), res[i]["standin"])})
check("3 …a picker never changes except for the two stand-ins", all(before_r[i]["picker"] == reading(i)["picker"] for i in SETS if i not in (11, 18)) and reading(11)["picker"] == ["home-other", "home-other"], (before_r[11]["picker"], reading(11)["picker"]))
logs = {i: [x["text"] for x in STALL.new_entries(orig[i]["metadata"], mt(i))] for i in SETS}
check("3 each written item gets exactly one History line, which says the picker was moved to mover", all(len(v) == 1 and "the stored picker was moved to mover" in v[0] and "nothing else on the item changed" in v[0] for v in logs.values()), logs)
check("3 nothing was closed, woken or told", all(raw(i)["status"] == "open" for i in OPEN) and sent == [] and not WK_.holding(), sent)

# ---- 4. idempotent
snap1 = snapshot()
st_, d_ = call(op="mover", items=[f"g{i}" for i in OPEN])
check("4 a second pass rewrites nothing: same for the items moved, kept for the three listed, no file changes", st_ == 200 and snapshot() == snap1 and {r["action"] for r in d_["results"]} == {"same", "kept"} and [r["action"] for r in d_["results"]].count("kept") == 3, (st_, [r["action"] for r in d_["results"]]))

# ---- 5. a wait on a date alone with an external need and a stored agent picker
put(31, **CASES[13][1]); put(32, **CASES[14][1]); put(33, **CASES[22][1])
modm = lambda i: MP.prepared(HOST, f"g{i}", raw(i))[1]
check("5 `ends_on_the_date` as it always read: an external wait on a date alone ends on the date unless the old key is stored (a stored mover alone does not turn it), a wait with a kind never ends on it",
      WK_.ends_on_the_date(mt(31), modm(31)) is True and WK_.ends_on_the_date(mt(32), modm(32)) is False and WK_.ends_on_the_date(mt(33), modm(33)) is True and WK_.ends_on_the_date(mt(1), modm(1)) is False, None)
check("5 the pass leaves the reading of both the same: an external date-only wait with a stored mover (ends on the date) and with the old key (turns), before and after, the old key left as it is", before_r[13]["ends"] is True and reading(13)["ends"] is True and before_r[14]["ends"] is False and reading(14)["ends"] is False and before_r[22]["ends"] is True and reading(22)["ends"] is True and mt(14).get("post_wake_mover") == BACK, (before_r[14]["ends"], reading(14)["ends"]))

# ---- 5b. a then beside a relay whose picker is the owner stays, and a then with a picker the plan leaves stands in for nothing
RELAY = dict(wait_kind="relay", wait_event="the vendor's reply", ask_by=day(6))
put(61, needs=["decision"], then=BACK, **RELAY)                                   # a relay: nobody stored as its picker, the owner picks it up
put(62, needs=["decision"], mover=OWN, then=BACK, **RELAY)                        # …and the owner stored as it
P61, P62 = plan(61), plan(62)
check("5b a relay the owner picks up (no picker stored): a then beside it is read after his answer, so it stays and nothing stands in", mod_of(61).wait is not None and _model.is_owner(mod_of(61).wait.mover) and P61["edits"] == {} and P61["standin"] == "" and not P61["listed"], (P61, mod_of(61).wait))
check("5b …with the owner stored as the picker: the same, it stays", P62["edits"] == {} and P62["standin"] == "" and not P62["listed"], P62)
b61 = bytes_of(61)
st_, d_ = call(op="mover", items=["g61", "g62"])
check("5b …the route leaves both relays byte for byte and moves no picker", st_ == 200 and [r["action"] for r in d_["results"]] == ["same", "same"] and bytes_of(61) == b61 and mt(61)["then"] == BACK and "mover" not in mt(61) and mt(62)["then"] == BACK and mt(62)["mover"] == OWN, (st_, d_))

# ---- 5c. the reading check holds through each key alone: the end date, and who picks the item up when a turned wait is put back
put(71, **CASES[14][1]); put(72, needs=["decision"], watch={"asked": "relay", "was": dict(WAS), "at": now0 - DAY}); b71, b72 = bytes_of(71), bytes_of(72)
r71, r72 = reading(71), reading(72)
check("5c the fixtures: an external date-only wait with the old key turns at its date, and a turned wait puts its picker back", r71["ends"] is False and r72["restored"][0] == "home-other", (r71["ends"], r72["restored"]))
real_plan = MP.plan_for
MP.plan_for = lambda meta, mod, tl: {**real_plan(meta, mod, tl), "edits": {"post_wake_mover": None, "mover": BACK}, "form": "a wrong plan", "new": f"mover={BACK}", "standin": ""}   # the picker reads the same; only the end date would
try:
    r_ends = call(op="mover", items=["g71"])[1]["results"][0]
finally:
    MP.plan_for = real_plan
check("5c a plan that changes only the end date (the old key turns an external date-only wait, `mover` would not) is refused for that key alone and the file stays", r_ends["action"] == "refused" and "ends False -> True" in r_ends["why"]
      and "picker [" not in r_ends["why"] and "restored" not in r_ends["why"] and bytes_of(71) == b71, r_ends)
wrong_was = {k: v for k, v in WAS.items() if k not in ("post_wake_mover", "then")} | {"mover": BACK}
MP.plan_for = lambda meta, mod, tl: {**real_plan(meta, mod, tl), "edits": {"watch": {**meta["watch"], "was": wrong_was}}, "form": "a wrong plan", "new": "no picker change", "standin": ""}   # the item itself reads the same; only the picker its "not yet" puts back would
try:
    r_rest = call(op="mover", items=["g72"])[1]["results"][0]
finally:
    MP.plan_for = real_plan
check("5c a plan that changes only who picks the item up when a turned wait is put back is refused for that key alone and the file stays", r_rest["action"] == "refused" and "restored" in r_rest["why"]
      and "picker [" not in r_rest["why"] and "ends" not in r_rest["why"] and bytes_of(72) == b72, r_rest)
r_ok = call(op="mover", items=["g71", "g72"])[1]["results"]
check("5c …and the real plan for the same two items is not refused", [r["action"] for r in r_ok] == ["kept", "set"] and bytes_of(71) == b71, [r["action"] for r in r_ok])

# ---- 6. the reading check refuses
put(41, **W); put(42, **CASES[10][1]); b41, b42 = bytes_of(41), bytes_of(42)
MP.plan_for = lambda meta, mod, tl: {**real_plan(meta, mod, tl), "edits": {"mover": "home-other"}, "form": "a wrong plan", "new": "mover=home-other"}      # a plan that changes who picks the item up
try:
    st_, d_ = call(op="mover", items=["g41"])
    r41 = d_["results"][0]
finally:
    MP.plan_for = real_plan
check("6 an item whose picker would read differently is refused and left byte for byte", r41["action"] == "refused" and "would read differently" in r41["why"] and "picker" in r41["why"] and bytes_of(41) == b41, r41)
MP.plan_for = lambda meta, mod, tl: {**real_plan(meta, mod, tl), "edits": {"then": None}, "form": "a wrong plan", "new": "no picker change"}                       # a plan that drops a then that stands
try:
    st_, d_ = call(op="mover", items=["g42"])
    r42 = d_["results"][0]
finally:
    MP.plan_for = real_plan
check("6 …a then that stands (the owner's pick) is never dropped: refused, byte for byte", r42["action"] == "refused" and "then" in r42["why"] and bytes_of(42) == b42, r42)
r43 = call(op="mover", items=["g41"])[1]["results"][0]
check("6 …and the real plan for the same items moves nothing", r43["action"] == "same" and bytes_of(41) == b41, r43)

# ---- 7. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return _rt_client._client_post("box-a", "migrate", {**body, "sender": SENDER})
def fresh():
    for p in (T / "store/g").glob("*.json"): p.unlink()
    for i, (_w, m) in CASES.items(): put(i, **m)
fresh()
snapS0 = snapshot()
RUN = pathlib.Path(_scratch.mkdtemp(prefix="movermig-run-"))
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
rc1, out1 = cli(MM.apply, app=app)
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("7 apply asks for the plan first (a dry call), writes the undo file, and ends with the left-over exit code (3, not a failure) for the three items it lists", rc1 == MM.EXIT_LEFT_OVER == 3 and sorted(out1["listed_in_the_plan"]) == sorted([BOARD + "5", BOARD + "6", BOARD + "14"]) and app.log[0] == "mover-dry" and "mover" in app.log and undo_file.is_file() and out1["results"].get("set") == len(SETS), (rc1, out1, app.log))
check("7 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == len(SETS), seen_undo)
bk = pathlib.Path(out1["backup"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("7 …the backup holds every touched file byte for byte as it was, and only those", sorted(p.name for p in bk.glob("*.json")) == sorted(f"g{i}.json" for i in SETS) and all((bk / f"g{i}.json").read_bytes() == snapS0[f"{i}.json"] for i in SETS), sorted(p.name for p in bk.glob("*")))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("7 …the undo file names each item with its keys before and after and the real result", {"pass_id", "by", "when", "store", "backup", "items"} <= set(uj) and len(uj["items"]) == len(SETS) and all({"item", "before", "after", "history", "dropped", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("7 the pass left each touched file as the route wrote it: no old key, one History line", all("post_wake_mover" not in mt(i) and len(STALL.log_of(mt(i))) == 1 for i in SETS), None)
pass_rec = T / "state/migration" / f"{uj.get('pass_id')}.json"
check("7 …the pass kept its results on the server (<state>/migration/<pass id>.json, under `items`: the same count as the undo file)", pass_rec.is_file() and len(json.loads(pass_rec.read_text())["items"]) == len(SETS), uj.get("pass_id"))
rc2, out2 = cli(MM.apply)
check("7 a second apply moves nothing", rc2 == 3 and out2["changed"] == 0 and sorted(out2["left_over"]) == sorted([BOARD + "5", BOARD + "6", BOARD + "14"]), (rc2, out2))
d3 = raw(3); d3["metadata"]["mover"] = "home-stew"; (T / "store/g/3.json").write_text(json.dumps(d3, ensure_ascii=False, indent=1))      # a session saves a key the pass wrote, on one item
rc3, out3 = cli(MM.undo, undo=str(undo_file))
vals_back = all({k: v for k, v in mt(i).items() if k != "stall"} == {k: v for k, v in json.loads(snapS0[f"{i}.json"])["metadata"].items() if k != "stall"} for i in SETS if i != 3)
check("7 --undo puts the keys back value for value on the items still as the pass left them, and keeps the one a later save changed", rc3 == 0 and vals_back and out3["results"] == {"set": len(SETS) - 1, "kept": 1} and out3["kept_because_a_later_save_changed_them"] == [BOARD + "3"] and mt(3)["mover"] == "home-stew", (rc3, out3))
check("7 …the History line goes with the undo (the stall log is back to what it was)", all("stall" not in mt(i) for i in SETS if i != 3), None)
rc4, out4 = cli(MM.undo, undo=str(undo_file))
check("7 …undo twice is a no-op", rc4 == 0 and set(out4["results"]) <= {"same", "kept"} and "set" not in out4["results"], (rc4, out4))
script = os.path.join(STACK, "stackshot/tools/mover_migrate.py")
check("7 --apply and --undo need --sender", subprocess.run([sys.executable, script, "--apply"], capture_output=True, text=True).returncode != 0 and subprocess.run([sys.executable, script, "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
fresh(); CFGM["migration"] = False
snapD = snapshot()
p = subprocess.run([sys.executable, script, "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("7 the dry run over a copy writes nothing live, prints old and new per item and the totals, lists the kept items and the stand-ins, and exits 0", p.returncode == 0 and snapshot() == snapD and "old: " in p.stdout and "new: " in p.stdout and "History line: stackshot:" in p.stdout
      and "items the pass would write:" in p.stdout and "a second pass: " in p.stdout and "stand-ins: 2 items" in p.stdout + p.stderr and "items kept and listed for a person: 3" in p.stdout, (p.returncode, p.stdout[-900:], p.stderr[-600:]))

# ---- 8. the gate
put(51, **CASES[1][1])
b51 = bytes_of(51)
CFGM["migration"] = False
st_, d_ = call(op="mover", items=["g51"])
check("8 the route is refused while [model] migration is off", st_ == 403 and bytes_of(51) == b51, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="mover", items=["g51"], sender="somebody-else")
check("8 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(machine="home-evil", op="mover", items=["g51"])
check("8 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(op="mover", items=["g51"], writes=[{"item": "g51", "set": {"mover": BACK}}])
check("8 …a body naming a key of its own is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(51) == b51, (st_, d_))
st_, d_ = call(op="unmover", items=[{"item": "g51", "before": {"subject": None}, "after": {"subject": "x"}}])
check("8 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused" and "not a key" in d_["results"][0]["why"], d_)
st_, d_ = call(op="unmover", items=["g51"], dry=True)
check("8 …dry goes with mover only; an empty list is refused", st_ == 400 and call(op="mover", items=[])[0] == 400, (st_, d_))
st_, d_ = call(op="mover", items=["g9999", "nonsense"])
check("8 …an unknown item and a malformed id are refused one by one", st_ == 200 and [r["action"] for r in d_["results"]] == ["refused", "refused"], (st_, d_))
put(52, status="completed", outcome="done", **dict(W, post_wake_mover=BACK))
st_, d_ = call(op="mover", items=["g52"])
check("8 …a closed item is refused and left as it is", d_["results"][0]["action"] == "refused" and "post_wake_mover" in mt(52), d_)
st_, d_ = call(op="mover", items=["g51"])
check("8 …a move needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not WK_.holding(), (st_, d_))
done51 = raw(51); entry51 = {k: d_["results"][0][k] for k in ("item", "before", "after", "history", "dropped")}
done51["status"] = "completed"; done51["outcome"] = "done"; (T / "store/g/51.json").write_text(json.dumps(done51, ensure_ascii=False, indent=1)); b51c = bytes_of(51)      # the item closed after the pass moved it
st_, d_ = call(op="unmover", items=[entry51])
check("8 …an undo of an item closed since the pass is `kept`, says it is closed, and leaves the file byte for byte (the keys the pass wrote stay)", st_ == 200 and d_["results"][0]["action"] == "kept" and "closed" in d_["results"][0]["why"] and bytes_of(51) == b51c and mt(51)["mover"] == "home-other" and "post_wake_mover" not in mt(51), (st_, d_))
CFGM["migration"] = False

print(f"mover_migrate: {len(ran) - len(fails)} of {len(ran)} checks passed")
if fails:
    print("FAILED:", *fails, sep="\n  ")
    sys.exit(1)
