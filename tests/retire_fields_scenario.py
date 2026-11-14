"""Scenario test for the retire pass: the stored state words and their carry fields taken out of the open items (retire_fields.py, retire_svc._retire_one / _unretire_one, the retire and unretire ops of the
migration route, tools/retire_fields_report.py) — fixture data, no live store written, no network, no server socket.

An open item once stored one of seven state words and the fields a state carried (party, chase, end, proof, supplies, step). The readers already derive the word from the item's other fields, and the carry fields
already have homes (party → wait_event, chase → ask_by, end → wake). The pass moves the values to those homes and drops the old keys; the server refuses (and leaves as it is) an item whose phase, kind of wait or
mover would read differently. The pass is the stamp pass's shape: one item at a time under its lock, nothing else in the file changes, an undo file written before the first write.

  1  plan_pure               retire_fields.plan_for: the keys dropped and the homes written for each case; a your-step item, a step with no home and a proof outside a verifying item are held; queued and wait_kind stay
  2  reading_same            for every case the phase, the kind of the wait, the list and the mover are the same before and after, apart from the old state word
  3  only_the_keys_move      each file differs from the original in the keys the plan names (and the description for supplies), nothing else; the activity clock, updated and written_by are untouched
  4  home_not_overwritten    a party beside a wait_event keeps the wait_event; a supplies already said in the description adds no line
  5  verifying_keeps_waiting a verifying item reads waiting on its end day after, with the proof as the text of the wait
  6  dry_and_idempotent      a dry run writes nothing; a second pass answers `same` and rewrites no file
  7  refused_when_it_changes an item whose reading would change is refused and left byte for byte
  8  undo_roundtrip          apply then undo gives the same values in every file (a restored key goes last in the file); twice is a no-op; a key a later save changed is `kept`
  9  gate                    refused with [model] migration off, for a sender or a machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write
  10 script                  tools/retire_fields_report.py: --apply asks for the plan first and writes the undo file before the first write; --undo puts the files back; the dry run over a copy writes nothing and exits 0

    tests/run-suite retire_fields        → exit 0 / 1"""
import argparse, contextlib, copy, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="retire-"); T = pathlib.Path(tmp)


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
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W; from stackshot.model import model as _model; from stackshot.model import retire_fields as RF; from stackshot.tools import retire_fields_report as RR; from stackshot.tools import stamp_phase as SP
from stackshot.service import client_reads as client_reads_svc
from stackshot.service import agents as _agents
from stackshot.service import item_read as _item_read
from stackshot.service import update as _update_svc
from stackshot.core import config as _cfg
from stackshot.waits import watchers as _watch
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import migrations as migsvc
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = _cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))


def put(i, status="open", letter="g", description=DESC, **meta):
    """An item file as the older writer left it: a stored state word and its carry fields, in the format the server writes."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    with open(T / f"store/{letter}/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": description, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def bytes_of(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_bytes()
def same_values(a, b): return {k: json.loads(v) for k, v in a.items()} == {k: json.loads(v) for k, v in b.items()}
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def state_listing(): return sorted(str(p.relative_to(T / "state")) for p in (T / "state").rglob("*"))
def reading(i):
    """phase, kind, list and mover from the fields alone, at the clock now (the old state word apart)."""
    it = dict(raw(i), gid=f"g{i}")
    with SP.fields_only(server):
        mod = _item_read._model_of(it)
        shown = _model.view(it, mod, None, lambda i_: _item_read._after_open(i_.get("metadata") or {}), check=False)
        return [list(_model.shown_pair(shown)), client_reads_svc._item_list(it), shown.mover if shown.state == _model.ALIVE else ""]

BASIS_DAY = day(12)
END_WAKE = BASIS_DAY + "T23:59"
put(31, needs=[BACK], state="doing")
# (id, what it is, the metadata)
CASES = [
    (1, "doing",                    dict(needs=[BACK], state="doing")),
    (2, "your-call",                dict(needs=["decision", BACK], state="your-call", ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date")),
    (3, "outside with party/chase", dict(needs=["external"], state="outside", party="Acme legal", chase=day(5))),
    (4, "outside with a home",      dict(needs=["external"], state="outside", party="Acme legal", chase=day(5), wait_event="Acme legal replies", ask_by=day(6))),
    (5, "blocked with supplies",    dict(needs=[BACK], state="blocked", after=["g31"], supplies="its output feeds the build")),
    (6, "parked",                   dict(needs=[BACK], state="parked", hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"})),
    (7, "verifying",                dict(needs=[BACK], state="verifying", proof="the nightly run is green", end=BASIS_DAY)),
    (8, "doing with a retired time", dict(needs=[BACK], state="doing", expected_by=day(3), expected_reason="a short check")),
    (9, "no stored state",          dict(needs=[BACK])),
    (10, "outside, wait_kind kept", dict(needs=["external"], state="outside", party="Beta", chase=day(7), wait_kind="relay")),
]
for i, _w, m in CASES:
    put(i, **m)
put(11, needs=[BACK], state="your-step", step="Run the thing once", mover=OWN, next=f"{OWN}: run the thing once")
put(12, needs=[BACK], state="doing", step="a step on a doing item")
put(13, needs=[BACK], state="doing", proof="a proof on a doing item")
put(14, needs=[BACK], state="blocked", after=["g31"], supplies="its output feeds the build", description="- A thing\n- Needs: its output feeds the build the guides match\n- Done when done")
put(15, status="completed", needs=[BACK], state="doing", outcome="done")
put(16, needs=[BACK], state="queued")
OPEN = [i for i in [c[0] for c in CASES] + [11, 12, 13, 14, 16]]

# ---- 1. the plan, pure
P = {i: RF.plan_for(mt(i), raw(i)["description"], 1000.0) for i in OPEN}
check("1 doing: only the state word is dropped", P[1]["edits"] == {"state": None} and P[1]["description"] is None and P[1]["held"] == [], P[1])
check("1 your-call: only the state word is dropped", P[2]["edits"] == {"state": None}, P[2])
check("1 outside: party and chase go to wait_event and ask_by, then are dropped with the state", P[3]["edits"] == {"state": None, "wait_event": "Acme legal", "party": None, "ask_by": day(5), "chase": None} and P[3]["moved"] == {"wait_event": "Acme legal", "ask_by": day(5)}, P[3])
check("1 outside beside a wait_event that names the party and an ask_by that is another day: the party goes (the wait_event says it), the chase day is held (ask_by would lose it)", P[4]["edits"] == {"state": None, "party": None} and P[4]["moved"] == {} and [f for f, _w in P[4]["held"]] == ["chase"], P[4])
P23 = RF.plan_for({"state": "outside", "needs": ["external"], "party": "Beta", "wait_event": "a reply", "ask_by": day(6), "chase": day(6)}, DESC, 1000.0)
check("1 …a party the wait_event does not name is held (the relay's text 'a reply from Beta' would read 'a reply'); a chase the ask_by starts with goes", P23["edits"] == {"state": None, "chase": None} and [f for f, _w in P23["held"]] == ["party"], P23)
P24 = RF.plan_for({"state": "outside", "needs": ["external"], "party": "beta  Legal", "wait_event": "A reply from Beta Legal"}, DESC, 1000.0)
check("1 …a wait_event that names the party (apart from case and spacing) lets it go", P24["edits"] == {"state": None, "party": None} and P24["held"] == [], P24)
check("1 blocked: supplies becomes a Needs bullet at the end of the description and the field is dropped", P[5]["edits"] == {"state": None, "supplies": None} and P[5]["description"] == DESC + "\n- Needs: its output feeds the build", P[5])
check("1 …a supplies the description already says adds nothing", P[14]["edits"] == {"state": None, "supplies": None} and P[14]["description"] is None, P[14])
check("1 parked: only the state word is dropped", P[6]["edits"] == {"state": None}, P[6])
check("1 verifying: the end day goes to the wake as the END of that day (23:59), the proof becomes the text of a wait_basis on it", P[7]["edits"]["wake"] == END_WAKE and P[7]["edits"]["end"] is None and P[7]["edits"]["proof"] is None and P[7]["edits"]["wait_basis"] == {"text": "the nightly run is green", "wake": END_WAKE, "by": "migration", "at": 1000.0}, P[7])
P25 = RF.plan_for({"state": "blocked", "needs": [BACK], "supplies": "y" * 120}, DESC, 1000.0, lambda t: "a bullet of 129 characters, the limit is 120" if max(len(x) for x in t.splitlines()) > 120 else "")
check("1 supplies whose Needs bullet would break the line limit are held, the field and the description stay", P25["description"] is None and "supplies" not in P25["edits"] and [f for f, _w in P25["held"]] == ["supplies"] and P25["edits"] == {"state": None}, P25)
FULL = "\n".join(f"- line {n}" for n in range(8))
P26 = RF.plan_for({"state": "blocked", "needs": [BACK], "supplies": "its output"}, FULL, 1000.0, lambda t: "9 lines, the limit is 8" if len(t.splitlines()) > 8 else "")
check("1 …and so are supplies that would make a ninth line", P26["description"] is None and [f for f, _w in P26["held"]] == ["supplies"], P26)
check("1 expected_by and expected_reason (retired) are dropped", P[8]["edits"] == {"state": None, "expected_by": None, "expected_reason": None}, P[8])
check("1 an item with no stored state has nothing to retire", P[9]["edits"] == {} and P[9]["description"] is None, P[9])
check("1 wait_kind is never touched; on a watched item the party and a chase with no ask_by are held, nothing is copied", "wait_kind" not in P[10]["edits"] and mt(10)["wait_kind"] == "relay" and P[10]["edits"] == {"state": None} and [f for f, _w in P[10]["held"]] == ["party", "chase"] and P[10]["moved"] == {}, P[10])
P22 = RF.plan_for({"state": "outside", "needs": ["external"], "party": "Beta", "chase": day(7), "wait_kind": "relay", "ask_by": day(8), "wait_event": "a reply"}, DESC, 1000.0)
check("1 …a chase beside an ask_by of another day is held on a watched item as on any other, and the party the wait_event does not name too", P22["edits"] == {"state": None} and [f for f, _w in P22["held"]] == ["party", "chase"], P22)
check("1 your-step is held back whole: its state and step stay", P[11]["edits"] == {} and [f for f, _w in P[11]["held"]] == ["step"], P[11])
check("1 a step on another item and a proof outside a verifying item are held, the state word still goes", [f for f, _w in P[12]["held"]] == ["step"] and P[12]["edits"] == {"state": None} and [f for f, _w in P[13]["held"]] == ["proof"] and "proof" not in P[13]["edits"], (P[12], P[13]))
check("1 queued (the rank queue's word) stays", P[16]["edits"] == {}, P[16])

# ---- 2/3. the readings are the same, and only the planned keys moved
before_r = {i: reading(i) for i in OPEN}
def wc(i):
    """waiting.mover_for for an item as the server reads it (its `after` blockers loaded from the store): whose move it is."""
    ctx = _agents._WaitCtx(time.time())
    return W.mover_for({**raw(i), "gid": f"g{i}"}, ctx.load)
WAIT_IDS = (1, 5, 7, 8, 12, 14, 31)
wait_before = {i: wc(i) for i in WAIT_IDS}
orig = {i: raw(i) for i in OPEN}
listing0 = state_listing()
snap0 = snapshot()
CFGM["migration"] = True
call = lambda machine="box-a", **body: server._client_post(machine, "migrate", {"sender": SENDER, **body})
st_, d_ = call(op="retire", items=[f"g{i}" for i in OPEN], dry=True)
dry = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("6 a dry run answers what each item would get and writes no file", st_ == 200 and snapshot() == snap0 and dry[3]["action"] == "would_set" and dry[9]["action"] == "same" and dry[11]["action"] == "same" and dry[11]["held"] == ["step"], (st_, d_))
check("6 …its before and after name the keys the plan touches", dry[3]["before"] == {"state": "outside", "wait_event": None, "party": "Acme legal", "ask_by": None, "chase": day(5)} and dry[3]["after"] == {"state": None, "wait_event": "Acme legal", "party": None, "ask_by": day(5), "chase": None}, dry[3])
st_, d_ = call(op="retire", items=[f"g{i}" for i in OPEN], pass_id="20260101-000000-abcdef")
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass sets every item with something to retire and leaves the rest (an item in hand, a stored state doing with a session as mover, is held whole)", st_ == 200 and {i for i, r in res.items() if r["action"] == "set"} == {2, 3, 4, 5, 6, 7, 10, 14} and {i for i, r in res.items() if r["action"] == "same"} == {1, 8, 9, 11, 12, 13, 16} and [res[i]["held"] for i in (1, 8, 12, 13)] == [["state"], ["state"], ["state"], ["state"]], {i: r["action"] for i, r in res.items()})
check("2 the phase, kind, list and mover of every item are the same after the pass", all(reading(i) == before_r[i] for i in OPEN), [i for i in OPEN if reading(i) != before_r[i]])
def only(i, keys):
    a, b = copy.deepcopy(orig[i]), raw(i)
    for k in keys:
        a["metadata"].pop(k, None); b["metadata"].pop(k, None)
    return a == b
check("3 each file differs from the original in the planned keys only (no updated, no activity clock, no written_by)", only(1, []) and only(3, ["state", "party", "chase", "wait_event", "ask_by"]) and only(7, ["state", "end", "proof", "wake", "wait_basis"]) and only(8, []) and only(10, ["state"]), None)
check("3 …no state word and no carry field is left on an item the pass set, and wait_kind stays", all("state" not in mt(i) for i in (2, 3, 4, 5, 6, 7, 10, 14)) and all(mt(i)["state"] == "doing" for i in (1, 8, 12, 13)) and not any(k in mt(3) for k in ("party", "chase")) and mt(10)["wait_kind"] == "relay" and mt(10)["party"] == "Beta" and mt(10)["chase"] == day(7) and "wait_event" not in mt(10) and "ask_by" not in mt(10), mt(10))
check("3 …your-step, queued and the item with no state are byte for byte what they were", bytes_of(11) == json.dumps(orig[11], ensure_ascii=False, indent=1).encode() and mt(11)["state"] == "your-step" and mt(16)["state"] == "queued", None)
check("3 …the closed item is untouched and refused", call(op="retire", items=["g15"])[1]["results"][0]["action"] == "refused", None)
check("3 …no side effect: the state folder is the same and the phase and waits_on stored agree with the fields", state_listing() == listing0 or all(not n.startswith("state/") for n in set(state_listing()) - set(listing0)), set(state_listing()) ^ set(listing0))
check("4 a party beside a wait_event keeps the wait_event; a supplies the description said adds no line", mt(4)["wait_event"] == "Acme legal replies" and mt(4)["ask_by"] == day(6) and raw(14)["description"] == orig[14]["description"], (mt(4), raw(14)["description"]))
check("4 the supplies line is the last bullet of the description", raw(5)["description"] == DESC + "\n- Needs: its output feeds the build", raw(5)["description"])
it7 = dict(raw(7), gid="g7")
m7 = _model.view(it7, _item_read._model_of(it7), None, lambda i_: _item_read._after_open(i_.get("metadata") or {}), check=False)
check("5 the verifying item reads waiting on its end day, with the proof as the text of the wait", m7.state == _model.WAITING and W.basis_of(mt(7)) == "the nightly run is green" and mt(7)["wake"] == END_WAKE, (m7.state, mt(7)))
check("5 …and it waits to the end of that day, as the verifying state read it (its end is now its wake, and whose move it is stays the same)",
      W.wake_epoch(mt(7)["wake"]) is not None and wc(7) == wait_before[7], (wait_before[7], wc(7), mt(7)))
check("5 waiting.mover_for: the stored-doing items (a session as mover, nothing waited on) are a session's move, before and after the pass",
      all(wait_before[i]["kind"] == "session" and wc(i) == wait_before[i] for i in (1, 8, 12, 31)), [(i, wait_before[i], wc(i)) for i in (1, 8, 12, 31)])
st_, d_ = call(op="retire", items=["g31"])
check("5 …a doing item is held whole, so the items that wait after it (g5, g14) keep their mover (the blocker's, named by `via`)",
      st_ == 200 and d_["results"][0]["action"] == "same" and d_["results"][0]["held"] == ["state"] and mt(31)["state"] == "doing" and all(wc(i) == wait_before[i] for i in (5, 14, 31)) and wc(5).get("via") == "g31",
      [(i, wait_before[i], wc(i)) for i in (5, 14, 31)])
put(31, needs=[BACK], state="doing")      # the blocker as it was, for the undo below
snap1 = snapshot()
st_, d_ = call(op="retire", items=[f"g{i}" for i in OPEN])
check("6 a second pass answers same for every item and rewrites no file", st_ == 200 and {r["action"] for r in d_["results"]} == {"same"} and snapshot() == snap1, (st_, {r["action"] for r in d_["results"]}))

# ---- 7. an item whose reading would change is refused
put(21, needs=[BACK], state="parked")                                    # stored parked with no hold: it reads waiting; without the word it would read alive
b21 = bytes_of(21)
st_, d_ = call(op="retire", items=["g21"])
check("7 an item whose reading would change is refused, with the readings in the answer, and left byte for byte", d_["results"][0]["action"] == "refused" and "differently" in d_["results"][0]["why"] and bytes_of(21) == b21, d_)
put(22, needs=[BACK], state="doing", due=day(20))                       # stored doing ignores a due date; without the word the item would wait on that day: another wait
put(23, state="doing", mover=BACK)                                       # stored doing with no session in needs: without the word it is an idle item
put(24, needs=[BACK], state="doing", check="pr_merged o/r#1")            # the same with a check
b22, b23, b24 = bytes_of(22), bytes_of(23), bytes_of(24)
st_, d_ = call(op="retire", items=["g22", "g23", "g24"])
check("7 a stored doing item with a due date, with a check, with a mover from the fallback: held whole, byte for byte, not refused",
      st_ == 200 and [r["action"] for r in d_["results"]] == ["same"] * 3 and all(r["held"] == ["state"] for r in d_["results"]) and (bytes_of(22), bytes_of(23), bytes_of(24)) == (b22, b23, b24), d_)
FULL8 = "\n".join(f"- bullet {n}" for n in range(8))
put(25, needs=[BACK], state="blocked", after=["g31"], supplies="its output feeds the build", description=FULL8)
put(26, needs=[BACK], state="blocked", after=["g31"], supplies="z" * 130)
st_, d_ = call(op="retire", items=["g25", "g26"])
check("7 supplies whose Needs bullet would break the 8-line or the 120-character limit stay in supplies, the item's state still goes, the answer lists them as held",
      st_ == 200 and [r["action"] for r in d_["results"]] == ["set", "set"] and all(r["held"] == ["supplies"] for r in d_["results"]) and mt(25)["supplies"] and mt(26)["supplies"] and "state" not in mt(25) and raw(25)["description"] == FULL8 and "Needs:" not in raw(26)["description"], d_)
for _i in (22, 23, 24, 25, 26): (T / f"store/g/{_i}.json").unlink(missing_ok=True)

# ---- 8. undo
uf = migsvc.pass_load("20260101-000000-abcdef")
check("8 the pass kept its results on the server (every item, set or same)", len(uf.get("items") or []) == len(OPEN) and sum(1 for r in uf["items"] if r["action"] == "set") == 8, len(uf.get("items") or []))
undo_entries = [{"item": r["item"], "before": r["before"], "after": r["after"]} for r in uf.get("items") or [] if r["action"] == "set"]
st_, d_ = call(op="unretire", items=undo_entries)
check("8 undo puts every file back value for value (a restored key goes last in the file)", st_ == 200 and same_values(snapshot(), snap0 | {k: v for k, v in snapshot().items() if k in ("21.json",)}) and all(r["action"] == "set" for r in d_["results"]), (st_, [r["action"] for r in d_["results"]], [k for k in snap0 if snap0[k] != snapshot().get(k)]))
st_, d_ = call(op="unretire", items=undo_entries)
check("8 …undo twice is a no-op (every answer is same)", {r["action"] for r in d_["results"]} == {"same"}, d_)
call(op="retire", items=["g3", "g5"])
_update_svc._update("g3", sender="home-front", ask_by=day(9))                  # a session changes a key the pass wrote
st_, d_ = call(op="unretire", items=[e for e in undo_entries if e["item"] in ("board#3", "board#5")])
acts = {r["item"]: r["action"] for r in d_["results"]}
check("8 a key a later save changed makes the entry `kept` (left as the session saved it); the others are put back", acts.get("board#3") == "kept" and acts.get("board#5") == "set" and mt(3).get("until") == day(9) and mt(5).get("supplies") == "its output feeds the build" and raw(5)["description"] == DESC, (acts, mt(3), raw(5)["description"]))

# ---- 9. the gate
put(41, needs=["external"], state="outside")
b41 = bytes_of(41)
CFGM["migration"] = False
st_, d_ = call(op="retire", items=["g41"])
check("9 the route is refused while [model] migration is off", st_ == 403 and bytes_of(41) == b41, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="retire", items=["g41"], sender="somebody-else")
check("9 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(41) == b41, (st_, d_))
st_, d_ = call(machine="home-evil", op="retire", items=["g41"])
check("9 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(41) == b41, (st_, d_))
st_, d_ = call(op="retire", items=["g41"], writes=[{"item": "g41", "set": {"mover": BACK}}])
check("9 …a body naming a key of its own (a write, a set) is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(41) == b41, (st_, d_))
st_, d_ = call(op="unretire", items=[{"item": "g41", "before": {"mover": None}, "after": {"mover": BACK}}])
check("9 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused" and "not a key" in d_["results"][0]["why"], d_)
st_, d_ = call(op="unretire", items=[{"item": "g41", "before": {"state": "doing"}, "after": {"wake": None}}])
check("9 …and one whose sides name different keys", d_["results"][0]["action"] == "refused", d_)
st_, d_ = call(op="unretire", items=["g41"], dry=True)
check("9 …dry goes with retire only; an empty list is refused", st_ == 400 and call(op="retire", items=[])[0] == 400, (st_, d_))
st_, d_ = call(op="retire", items=["g9999", "nonsense"])
check("9 …an unknown item and a malformed id are refused one by one", st_ == 200 and [r["action"] for r in d_["results"]] == ["refused", "refused"], (st_, d_))
st_, d_ = call(op="retire", items=["g41"])
check("9 …a retire needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and "state" not in mt(41) and not _watch.holding(), (st_, d_))
CFGM["migration"] = False

# ---- 10. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return server._client_post("box-a", "migrate", {**body, "sender": SENDER})
CFGM["migration"] = True
RUN = pathlib.Path(_scratch.mkdtemp(prefix="retire-run-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="")
for i, _w, m in CASES:
    put(i, **m)
put(11, needs=[BACK], state="your-step", step="Run the thing once", mover=OWN, next=f"{OWN}: run the thing once")
put(12, needs=[BACK], state="doing", step="a step on a doing item")
put(13, needs=[BACK], state="doing", proof="a proof on a doing item")
put(14, needs=[BACK], state="blocked", after=["g31"], supplies="its output feeds the build", description="- A thing\n- Needs: its output feeds the build the guides match\n- Done when done")
put(41, needs=["external"], state="outside")
os.remove(T / "store/g/21.json")
snapS0 = snapshot()
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
rc1, out1 = cli(RR.apply, app=app)
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("10 apply asks for the plan first (a dry call), writes the undo file, ends well", rc1 == 0 and app.log[0] == "retire-dry" and "retire" in app.log and undo_file.is_file() and out1["results"].get("set") == 9, (rc1, out1, app.log))
check("10 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == 9, seen_undo)
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("10 …it names each item with its keys before and after and the real result", {"pass_id", "by", "when", "store", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
rc2, out2 = cli(RR.apply)
check("10 a second apply retires nothing", rc2 == 0 and out2 == {"retired": 0}, (rc2, out2))
rc3, out3 = cli(RR.undo, undo=str(undo_file))
check("10 --undo puts every file back value for value", rc3 == 0 and same_values(snapshot(), snapS0) and out3["results"] == {"set": 9}, (rc3, out3))
rc4, out4 = cli(RR.undo, undo=str(undo_file))
check("10 …twice is a no-op", rc4 == 0 and same_values(snapshot(), snapS0) and set(out4["results"]) == {"same"}, (rc4, out4))
check("10 --apply and --undo need --sender", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/retire_fields_report.py"), "--apply"], capture_output=True, text=True).returncode != 0 and subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/retire_fields_report.py"), "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
CFGM["migration"] = False
snapD = snapshot()
p = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/retire_fields_report.py"), "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("10 the dry run over a copy writes nothing live, prints the totals and exits 0", p.returncode == 0 and snapshot() == snapD and "items the pass would write" in p.stdout and "items whose phase, kind of wait, list or mover would change: 0" in p.stdout, (p.returncode, p.stdout[-600:], p.stderr[-600:]))

print(f"ok: retire fields scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
