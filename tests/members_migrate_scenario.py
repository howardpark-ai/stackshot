"""Scenario test for the members pass: the first person's name written on what the store holds without one (stackshot/waits/members_pass.py, the ops members and unmembers of the migration route in the server,
tools/members_migrate.py) — fixture data, no live store written, no network, no server socket.

A board that serves one person stores no name on his answers: a record with no `by` reads as the first person (`members.recorded_by`), and a decision that names nobody is his by default. The pass writes that
reading down, open and closed items alike: `by` on every stored answer that has none; on an open item, a decision with no stored mover gets the first person stored as its mover, and a `you:` line of `next`
gets the name where reading it makes no difference. One History line per changed item; no clock moves, nobody is told. The server refuses an item that would read differently, and an item whose `you:` line
would read differently with the name in its place keeps the line and is listed.

  1  plan_pure        members_pass.plan_for and its parts for each stored form: answers, a decision's mover, a `you:` line (with its writer pair and stored step), the placeholder first person
  2  dry_run          the route's dry run writes no file and answers the keys before and after, the form and the History line
  3  write            only answers, mover, next and its pairs, steps and the stall log move; clocks, writer, status, needs, project and the files' times stay; one History line each; nobody is told
  4  idempotent       a second pass answers `same` (or `kept`) and rewrites no file; the series-end check reads "items the pass would write: 0"
  5  one_person       the readings of an item (the pass's own reading, the model) are the same before and after on a board of one person; the one change is the stored mover's `mover_explicit`
  6  authorship       an unapplied or half-applied store reads each answer as the same person as an applied one, with one person and with two
  7  refusal          an item whose reading would change, or whose answer would read as another person's, is refused and left byte for byte
  8  script           tools/members_migrate.py: --apply asks for the plan first, backs up every touched file byte for byte and writes the undo file before the first write; --plan and a re-plan refuse when the store
                      moved; --undo puts the keys back and keeps what a later save changed; twice is a no-op; the dry run over a copy writes nothing live
  9  gate             refused while [model] migration is off, for a sender or machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write
  10 review lows      a closed item that holds a decision is stamped on its answers alone (its mover, stored or not, stays); a plan file edited after the dry run is refused on --apply with nothing written;
                      the unfinished pass of the earlier run folder (`people-run`) is named when the run folder is the default one, and not otherwise

    tests/run-suite members_migrate        -> exit 0 / 1"""
import argparse, contextlib, copy, dataclasses, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _midnight
tmp = _scratch.mkdtemp(prefix="membersmig-"); T = pathlib.Path(tmp)


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
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" the checks read: start on the far side of one that is close
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
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]
BACK = "team-back"
OWN = "Oliver"
SENDER = "falcon-engineer"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server, wiring; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.waits import watchers as WK_, stall as STALL, mover_pass as MP, members_pass as PP; from stackshot.model import model as _model, nextlines as _nl, steps as _steps
from stackshot.core import members as _members
from stackshot.tools import members_migrate as PM; from stackshot.tools import stamp_phase as SP
from stackshot.service import stamp as stamp_svc
from stackshot.service import retire_passes as retire_svc
HOST = stamp_svc.PassHost(server, stamp_svc, retire_svc, wiring.PASS_NAMES)   # the `S` of the pass: the server module, then the stamp and retire modules that own the names it reads
from stackshot.web.routes import client_api as _rt_client
import stackshot.core.config as _cfg_
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
sent = []
telling.tell_woken = lambda gid, owner, note, tag="wake": sent.append((gid, owner, note))
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = _cfg_.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
OLIVER = _members.first(); PAT = _members.Person("Pat", (), ("pat@example.org",))
check("0 the fixture: one person, Oliver", [p.name for p in _members.members()] == ["Oliver"] and OLIVER.name == "Oliver" and not OLIVER.placeholder, _members.members())

OLD = now0 - 10 * DAY
def put(i, status="open", letter="g", description=DESC, **meta):
    """An item file as a board of one person stores it: no `by` on an answer, no stored mover on a decision."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    p = T / f"store/{letter}/{i}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": description, "status": status, "updated": OLD, "state_updated": OLD, "confirmed": OLD, "metadata": base}, f, ensure_ascii=False, indent=1)
    os.utime(p, (OLD, OLD))
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def bytes_of(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_bytes()
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def times(): return {p.name: p.stat().st_mtime_ns for p in sorted((T / "store/g").glob("*.json"))}
BOARD = "board" + "#"      # a board id is built at run time, never written as a literal
ANS = lambda n, **kw: {"ts": now0 - n * 3600, "kind": "pick", "choice": "Wait", "text": "", "via": "web", **kw}
DECIDE = dict(needs=["decision"], ask=ASK, options=OPTS, next="Oliver: decide")
YOU = "you: send the form"
CASES = {
    1:  ("a decision, no mover, answers with no `by`, a `by` and a blank one",  dict(DECIDE, answers=[ANS(1), ANS(2, by="Pat"), ANS(3, by="  ")])),
    2:  ("a decision whose mover is stored as the first person",                dict(DECIDE, mover=OWN, answers=[ANS(1)])),
    3:  ("a decision whose mover is stored as an agent",                        dict(DECIDE, mover=BACK, answers=[ANS(1)])),
    4:  ("an item waiting on an agent for a date",                              dict(needs=[BACK], wait_kind="time", until=day(3), answers=[ANS(1)])),
    5:  ("a decision with the old picker key",                                  dict(DECIDE, post_wake_mover=BACK, answers=[ANS(1)])),
    6:  ("a next that opens with `you:`",                                       dict(next=YOU)),
    7:  ("a next that opens with the first person's name, an answer with `by`", dict(next="Oliver: review it", answers=[ANS(1, by="Oliver")])),
    8:  ("answers that all carry a `by`",                                       dict(answers=[ANS(1, by="Pat")])),
    9:  ("an empty list of answers",                                            dict(answers=[])),
    10: ("a decision with no answers",                                          dict(DECIDE)),
    11: ("a mail tick with no `by`",                                            dict(needs=[BACK], answers=[ANS(1, kind="tick", via="mail")])),
    13: ("a closed item with no answers",                                       None),
    15: ("`you:` on two lines of a longer next",                                dict(next="you: first\nteam-back: second\nyou: third")),
}
CLOSED = {12: dict(outcome="done", reason="it worked", answers=[ANS(1), ANS(2, kind="note", text="a word")]),
          13: dict(outcome="done", reason="it worked"),
          14: dict(outcome="done", reason="it worked", answers=[ANS(1, by="Pat")])}
def fixtures():
    for p in (T / "store/g").glob("*.json"): p.unlink()
    for i, (_w, m) in CASES.items():
        if m is not None: put(i, **m)
    for i, m in CLOSED.items(): put(i, status="completed", **m)
fixtures()
OPEN = [i for i, (_w, m) in CASES.items() if m is not None]
ALL = sorted(OPEN + list(CLOSED))
WRITES = (1, 2, 3, 4, 5, 10, 11, 12)        # answers with no `by`, or a decision with no stored mover: the pass writes these
SAMES = (7, 8, 9, 13, 14)                   # nothing stored without a name
YOUS = (6, 15)                              # the `you:` items: rewritten or kept and listed
KEYS = PP.KEYS
mod_of = lambda i: MP.prepared(HOST, f"g{i}", raw(i))[1]
def strip(o):
    """A dataclass as a dict, without the flag that says a mover is stored (the one thing a stored mover changes about the model's reading)."""
    if isinstance(o, dict): return {k: strip(v) for k, v in o.items() if k != "mover_explicit"}
    if isinstance(o, (list, tuple)): return [strip(v) for v in o]
    return o
model_of = lambda i: strip(dataclasses.asdict(mod_of(i)))
recs = lambda: {i: PP.recorded(mt(i)) for i in ALL}

# ---- 1. the plan, pure
snap_pre = snapshot()
P = {i: PP.plan_for(mt(i), mod_of(i) if i in OPEN else None, i in OPEN) for i in ALL}
check("1 answers with no `by` (absent or blank) get the first person; one with a `by` keeps it", P[1]["answers"] == 2 and P[1]["edits"]["answers"] == [{**ANS(1), "by": "Oliver"}, ANS(2, by="Pat"), {**ANS(3, by="  "), "by": "Oliver"}], P[1])
check("1 …the form says what it writes", P[1]["form"].startswith("by = Oliver on 2 answers") and "decision's mover stored as Oliver" in P[1]["form"], P[1]["form"])
check("1 a decision that stores no mover and reads the first person by default gets him stored as its mover", P[1]["edits"].get("mover") == "Oliver" and P[10]["edits"] == {"mover": "Oliver"}, (P[1]["edits"].get("mover"), P[10]["edits"]))
check("1 …a stored mover (the first person or an agent) is left as it is", "mover" not in P[2]["edits"] and "mover" not in P[3]["edits"], (P[2], P[3]))
check("1 …an item that waits, an item with the old picker key and a closed item store no mover", "mover" not in P[4]["edits"] and "mover" not in P[5]["edits"] and "mover" not in P[12]["edits"], (P[4], P[5], P[12]))
check("1 a closed item gets its answers named and nothing else", set(P[12]["edits"]) == {"answers"} and P[12]["answers"] == 2 and P[13]["edits"] == {} and P[14]["edits"] == {}, (P[12], P[13], P[14]))
check("1 a mail tick is an answer like the others", P[11]["answers"] == 1 and P[11]["edits"]["answers"][0]["by"] == "Oliver", P[11])
check("1 nothing stored without a name: no edits, no list, no form", all(P[i]["edits"] == {} and not P[i]["listed"] and not P[i]["form"] for i in (7, 8, 9, 13, 14)), {i: P[i] for i in (7, 8, 9, 13, 14)})
check("1 the plan is pure: planning every item changes no file", snapshot() == snap_pre, None)
check("1 answers_plan: an entry that is no object, answers that are no list and no answers at all are left alone", PP.answers_plan({"answers": ["junk", {"a": 1}, {"a": 2, "by": "Pat"}]}, "Oliver") == (["junk", {"a": 1, "by": "Oliver"}, {"a": 2, "by": "Pat"}], 1)
      and PP.answers_plan({"answers": "x"}, "Oliver") == (None, 0) and PP.answers_plan({}, "Oliver") == (None, 0) and PP.answers_plan({"answers": [{"by": "Pat"}]}, "Oliver") == (None, 0), None)
# a `you:` line, its writer pair and the stored step that matches it, pure
h = _nl.key_of("you: a")
meta_you = {"next": "you: a\nteam-back: b", "next_by": [["falcon", h], ["falcon", _nl.key_of("team-back: b")]], "steps": [{"text": "you: a", "status": "open", "writer": "falcon", "at": 1.0}, {"text": "team-back: b", "status": "open", "writer": "falcon", "at": 1.0}]}
ed, why = PP.you_edits(meta_you, "Oliver")
check("1 you_edits puts the name where the line opened with `you:`, in the text, in the line's writer pair (by the hash of the line) and in the stored open step", not why and ed["next"] == "Oliver: a\nteam-back: b"
      and ed["next_by"] == [["falcon", _nl.key_of("Oliver: a")], ["falcon", _nl.key_of("team-back: b")]] and [s["text"] for s in ed["steps"]] == ["Oliver: a", "team-back: b"], (ed, why))
check("1 …a next with no `you:` line has no edits, and neither has an empty one", PP.you_edits({"next": "team-back: b"}, "Oliver") == ({}, []) and PP.you_edits({}, "Oliver") == ({}, []) and PP.you_edits({"next": "  "}, "Oliver") == ({}, []), None)
ed2, why2 = PP.you_edits({"next": "you: do\n```\nyou: in a fence\n```"}, "Oliver")
check("1 …a `you:` that is not the start of a line of its own (inside a fence) leaves the item as it is and says so", ed2 == {} and why2 and "not a line of its own" in why2[0], (ed2, why2))
ed3, why3 = PP.you_edits({"next": "you: a", "steps": [{"text": "you: a", "status": "open"}, {"text": "you:a", "status": "done"}]}, "Oliver")
check("1 …a step that is done keeps its text (only an open step that matches the line is rewritten)", [s["text"] for s in ed3.get("steps", [])] in (["Oliver: a", "you:a"], []), (ed3, why3))
pr = lambda meta: PP.line_probe(meta, "Oliver")
check("1 line_probe and probe_diff: equal for the same lines, and say what differs", PP.probe_diff(pr({"next": "team-back: b"}), pr({"next": "team-back: b"})) == "" and PP.probe_diff(pr({"next": "team-back: b"}), pr({"next": "Oliver: b"})) != "", None)
for i in YOUS:
    notes = P[i]["notes"]
    rewritten = "next" in P[i]["edits"]
    check(f"1 item {i}: a `you:` line is rewritten with the lines reading the same, or kept and listed with what would differ (never both, never silently)",
          (rewritten and not notes and PP.probe_diff(pr(mt(i)), pr({**mt(i), **P[i]["edits"]})) == "") or (not rewritten and P[i]["listed"] and "a `you:` line is kept" in notes[0]), P[i])
    print(f"note: item {i} `you:` plan -> {'rewritten' if rewritten else 'kept and listed'}: {P[i]['notes'] or P[i]['edits'].get('next')!r}")
YOU_REWRITTEN = {i: "next" in P[i]["edits"] for i in YOUS}
real_first = _members.first; real_people = _members.members
_members.first = lambda: _members.Person("the owner", (), (), False)
try:
    Pph = {i: PP.plan_for(mt(i), mod_of(i) if i in OPEN else None, i in OPEN) for i in (1, 12, 6)}
finally:
    _members.first = real_first
check("1 the placeholder first person (the board names nobody) writes nothing and says why", all(Pph[i]["edits"] == {} and not Pph[i]["form"] and not Pph[i]["listed"] and "names no person" in Pph[i]["why"] for i in Pph), Pph)

# ---- 2. the dry run
CFGM["migration"] = True
call = lambda machine="box-a", **body: _rt_client._client_post(machine, "migrate", {"sender": SENDER, **body})
snap0 = snapshot(); t0 = times()
orig = {i: raw(i) for i in ALL}
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL], dry=True)
dry = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("2 a dry run writes no file and answers would_set for the items to stamp and same for the rest (a `you:` item: would_set, or kept when only the line is listed)", st_ == 200 and snapshot() == snap0 and times() == t0
      and [dry[i]["action"] for i in WRITES] == ["would_set"] * len(WRITES) and [dry[i]["action"] for i in SAMES] == ["same"] * len(SAMES)
      and all(dry[i]["action"] == ("would_set" if YOU_REWRITTEN[i] else "kept") for i in YOUS), (st_, {i: dry[i]["action"] for i in dry}))
check("2 …its before and after name the keys it changes, the form and the History line", dry[1]["before"]["answers"] == orig[1]["metadata"]["answers"] and dry[1]["after"]["answers"][0]["by"] == "Oliver" and dry[1]["before"].get("mover") is None and dry[1]["after"]["mover"] == "Oliver"
      and "the first person was stamped" in dry[1]["history"] and dry[1]["form"].startswith("by = Oliver on 2 answers") and dry[1]["answers"] == 2 and dry[1]["sha256_before"], dry[1])
check("2 …a closed item says its answers get a name, and its before and after hold the answers alone", dry[12]["status"] == "completed" and set(dry[12]["after"]) == {"answers"} and dry[12]["answers"] == 2, dry[12])
check("2 …an item left as it is says so", dry[13]["why"] == "nothing stored without a name" and dry[13]["before"] == {} and dry[13]["after"] == {}, dry[13])
check("2 …the item with a stored mover and the one that waits are told apart: no mover in what they would get", "mover" not in dry[2]["after"] and "mover" not in dry[3]["after"] and "mover" not in dry[4]["after"] and "mover" not in dry[5]["after"], (dry[2]["after"].keys(), dry[4]["after"].keys()))
EXPECT_WRITE = [i for i in ALL if dry[i]["action"] == "would_set"]
EXPECT_LEFT = sorted(BOARD + str(i) for i in ALL if dry[i].get("notes"))

# ---- 3. the write
reading = lambda i: MP.reading(HOST, f"g{i}", raw(i))
before_r = {i: reading(i) for i in OPEN}; before_m = {i: model_of(i) for i in OPEN}; before_recs = recs(); t1 = times()
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL], pass_id="20260101-000000-abcdef")
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass stamps the items it planned and answers same for the rest", st_ == 200 and [i for i in ALL if res[i]["action"] == "set"] == EXPECT_WRITE and all(res[i]["action"] in ("same", "kept") for i in ALL if i not in EXPECT_WRITE), {i: res[i]["action"] for i in res})
check("3 …every item with an answer without a `by` is among them", set(WRITES) <= set(EXPECT_WRITE), EXPECT_WRITE)
CHANGED = EXPECT_WRITE
WRITTEN_KEYS = (*KEYS, "stall")
check("3 only answers, mover, next and its pairs, steps and the stall log changed in each written file (clocks, writer, status, subject, description, needs, ask, options, project stay)",
      all({k: v for k, v in raw(i).items() if k != "metadata"} == {k: v for k, v in orig[i].items() if k != "metadata"}
          and {k: v for k, v in mt(i).items() if k not in WRITTEN_KEYS} == {k: v for k, v in orig[i]["metadata"].items() if k not in WRITTEN_KEYS} for i in CHANGED), None)
check("3 the files of the items left as they are are byte for byte the same", all(bytes_of(i) == json.dumps(orig[i], ensure_ascii=False, indent=1).encode() for i in ALL if i not in CHANGED), None)
check("3 every file keeps its modification time (a closed item is dated by its file)", times() == t1 and times() == t0, {k: (t0[k], times()[k]) for k in t0 if t0[k] != times()[k]})
check("3 every answer of an open or closed item that had no `by` now carries the first person's name, one with a `by` keeps it", all(a.get("by") for i in ALL for a in (mt(i).get("answers") or [])) and [a["by"] for a in mt(1)["answers"]] == ["Oliver", "Pat", "Oliver"]
      and [a["by"] for a in mt(12)["answers"]] == ["Oliver", "Oliver"] and [a["by"] for a in mt(14)["answers"]] == ["Pat"], [mt(1)["answers"], mt(12)["answers"]])
check("3 …nothing else of an answer changed: the same entries with `by` added", all([{k: v for k, v in a.items() if k != "by"} for a in mt(i).get("answers", [])] == [{k: v for k, v in a.items() if k != "by"} for a in orig[i]["metadata"].get("answers", [])] for i in WRITES), None)
check("3 the decision with no mover has the first person stored, the others keep the mover they had or none", mt(1)["mover"] == "Oliver" and mt(10)["mover"] == "Oliver" and mt(2)["mover"] == "Oliver" and mt(3)["mover"] == BACK and "mover" not in mt(4) and "mover" not in mt(5) and "mover" not in mt(12), {i: mt(i).get("mover") for i in ALL})
check("3 nobody's authorship changed: every answer reads as the person it read as before", recs() == before_recs, (before_recs, recs()))
check("3 the reading of every written open item is the same before and after (phase, kind of wait, mover, watched, held, picker, then, needs, end date)", all(MP.same(before_r[i], reading(i), "") == "" for i in OPEN), {i: MP.same(before_r[i], reading(i), "") for i in OPEN if MP.same(before_r[i], reading(i), "")})
logs = {i: [x["text"] for x in STALL.new_entries(orig[i]["metadata"], mt(i))] for i in CHANGED}
check("3 each written item gets exactly one History line, which says the first person was stamped and that nothing else changed", all(len(v) == 1 and "the first person was stamped" in v[0] and "nothing else on the item changed" in v[0] for v in logs.values()), logs)
check("3 …a closed item records it too (it does not show it)", len(STALL.log_of(mt(12))) == 1 and raw(12)["status"] == "completed", mt(12).get("stall"))
check("3 …an item left as it is gets none", all(not STALL.log_of(mt(i)) for i in ALL if i not in CHANGED), None)
check("3 nothing was closed, woken or told, and nothing was held", all(raw(i)["status"] == "open" for i in OPEN) and all(raw(i)["status"] == "completed" for i in CLOSED) and sent == [] and not WK_.holding(), sent)
for i in YOUS:
    if YOU_REWRITTEN[i]:
        check(f"3 item {i}: a `you:` line planned as a rewrite is written with the name and the lines read the same", "you:" not in mt(i)["next"].lower() or mt(i)["next"].lower().count("you:") == 0, mt(i)["next"])
    else:
        check(f"3 item {i}: a `you:` line the pass keeps stays exactly as it was, and the item is listed", mt(i)["next"] == orig[i]["metadata"]["next"] and res[i]["action"] == "kept" and res[i]["notes"], res[i])

# ---- 4. idempotent, and the series-end check
snap1 = snapshot()
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL])
check("4 a second pass rewrites nothing: same for the items stamped, kept for the ones listed, no file changes", st_ == 200 and snapshot() == snap1 and times() == t0 and {r["action"] for r in d_["results"]} <= {"same", "kept"}, (st_, [r["action"] for r in d_["results"]]))
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL], dry=True)
check("4 a dry run on the applied store would write nothing", st_ == 200 and [r["action"] for r in d_["results"] if r["action"] not in ("same", "kept")] == [], [r["action"] for r in d_["results"]])

# ---- 5. a board of one person reads as before
check("5 the model's reading of every open item is the same before and after, apart from the flag that says a mover is stored", all(model_of(i) == before_m[i] for i in OPEN), {i: (before_m[i], model_of(i)) for i in OPEN if model_of(i) != before_m[i]})
check("5 …the flag is the one thing that moved, and only on the decision whose mover the pass stored", mod_of(1).mover_explicit and mod_of(10).mover_explicit and not mod_of(2).__class__ is None and not mod_of(6).mover_explicit and not mod_of(7).mover_explicit, (mod_of(1).mover_explicit, mod_of(6).mover_explicit))
check("5 …each decision still has the first person as its mover and its ask, options and needs as they were", all(mod_of(i).mover == "Oliver" and mt(i)["ask"] == ASK and mt(i)["options"] == OPTS and mt(i)["needs"] == ["decision"] for i in (1, 2, 10)), None)
check("5 …an answer with no `by` and one stamped with the first person read as the same person, and `stamp` writes none (the writers store nothing for him)", _members.recorded_by(ANS(1)) == "Oliver" and _members.recorded_by(ANS(1, by="Oliver")) == "Oliver" and _members.stamp({}, "Oliver") == {}, None)

# ---- 6. an unapplied or half-applied store reads the same as an applied one
fixtures()
unapplied = recs()
check("6 an unapplied store (no `by`) reads each answer as the first person", unapplied[1] == ["Oliver", "Pat", "Oliver"] and unapplied[12] == ["Oliver", "Oliver"] and unapplied[14] == ["Pat"] and unapplied[9] == [], unapplied)
half = [f"g{i}" for i in (1, 12, 4)]
st_, d_ = call(op="members", items=half)
check("6 a store half applied (three of its items) reads every answer as the same person as the unapplied one", st_ == 200 and [r["action"] for r in d_["results"]] == ["set"] * 3 and recs() == unapplied and all(a.get("by") for a in mt(1)["answers"]) and not any(a.get("by") for a in mt(11)["answers"]), (st_, recs()))
_members.members = lambda: [OLIVER, PAT]
try:
    check("6 …with a second person on the board too: the first person is still who a record without a name reads as, the one stamped and the one not", recs() == unapplied and _members.recorded_by({}) == "Oliver", recs())
    st_, d_ = call(op="members", items=[f"g{i}" for i in ALL])
    check("6 …and after the rest is applied under two members, nobody's authorship moved", st_ == 200 and recs() == unapplied and all(a.get("by") for i in ALL for a in (mt(i).get("answers") or [])), (st_, recs()))
finally:
    _members.members = real_people
check("6 the one reader is back (the list is the config's one person)", [p.name for p in _members.members()] == ["Oliver"], _members.members())
fixtures()

# ---- 7. the checks refuse
real_plan = PP.plan_for
b1, b12 = bytes_of(1), bytes_of(12)
PP.plan_for = lambda meta, mod, is_open: {**real_plan(meta, mod, is_open), "edits": {"mover": BACK}, "form": "a wrong plan"}      # a plan that changes who moves the decision
try:
    r1 = call(op="members", items=["g1"])[1]["results"][0]
finally:
    PP.plan_for = real_plan
check("7 an item whose reading would change is refused and left byte for byte", r1["action"] == "refused" and "would read differently" in r1["why"] and "mover" in r1["why"] and bytes_of(1) == b1, r1)
PP.plan_for = lambda meta, mod, is_open: {**real_plan(meta, mod, is_open), "edits": {"answers": [{**a, "by": "Pat"} for a in meta["answers"]]}, "form": "a wrong plan"}      # a plan that names the second person
try:
    r12 = call(op="members", items=["g12"])[1]["results"][0]
finally:
    PP.plan_for = real_plan
check("7 …a plan that would make an answer read as another person's is refused for a closed item too, byte for byte", r12["action"] == "refused" and "another person's" in r12["why"] and bytes_of(12) == b12, r12)
r_ok = call(op="members", items=["g1", "g12"])[1]["results"]
check("7 …and the real plan for the same two items is not refused", [r["action"] for r in r_ok] == ["set", "set"], r_ok)
fixtures()
_members.first = lambda: _members.Person("the owner", (), (), False)
try:
    snapPH = snapshot()
    st_, d_ = call(op="members", items=[f"g{i}" for i in ALL])
finally:
    _members.first = real_first
check("7 a board that names no person writes nothing: every item answers same and no file changes", st_ == 200 and snapshot() == snapPH and {r["action"] for r in d_["results"]} == {"same"} and all("names no person" in r["why"] for r in d_["results"]), (st_, [r["why"] for r in d_["results"]][:2]))

# ---- 8. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return _rt_client._client_post("box-a", "migrate", {**body, "sender": SENDER})
class MovingApp(DirectApp):
    """A route whose store moves between the plan and the re-plan before the write: an item is saved by someone else."""
    def call(self, body):
        if body.get("dry") and self.log.count("members-dry") == 1:
            d = raw(1); d["metadata"]["note_to_self"] = "saved meanwhile"; (T / "store/g/1.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
        return super().call(body)
fixtures()
snapS0 = snapshot(); orig_s = {i: raw(i) for i in ALL}
RUN = pathlib.Path(_scratch.mkdtemp(prefix="membersmig-run-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="", plan="", allow_changed_plan=False)
def cli(fn, app=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    try: return rc, json.loads(out.getvalue())
    except ValueError: return rc, out.getvalue()
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL], dry=True)
plan_rows = d_["results"]
PLAN = RUN / "plan.json"; PLAN.write_text(json.dumps(plan_rows))
WILL = sorted(int(r["item"].split("#")[1]) for r in plan_rows if r["action"] == "would_set")
LEFT = sorted(r["item"] for r in plan_rows if r.get("notes") or r["action"] == "refused")
rc0, out0 = cli(PM.apply, app=MovingApp())
check("8 a re-plan right before the write that differs from the plan refuses: nothing else is written, no undo file, exit 1", rc0 == 1 and {k: v for k, v in snapshot().items() if k != "1.json"} == {k: v for k, v in snapS0.items() if k != "1.json"} and not list(RUN.rglob("undo.json")), (rc0, out0, [k for k in snapS0 if snapshot()[k] != snapS0[k]], list(RUN.rglob("undo.json"))))
fixtures()
d1 = raw(1); d1["metadata"]["note_to_self"] = "saved after the dry run"; (T / "store/g/1.json").write_text(json.dumps(d1, ensure_ascii=False, indent=1))
snapMoved = snapshot()
rc0b, out0b = cli(PM.apply, plan=str(PLAN))
check("8 --plan: the store moved since the dry run (a file it would change differs from the one it read): nothing is written, exit 1", rc0b == 1 and snapshot() == snapMoved and not list(RUN.glob("2*/undo.json")), (rc0b, out0b))
fixtures(); snapS0 = snapshot()
app = DirectApp()
orig_write = SP.write_atomic
seen_undo = []
def spy(path, obj):
    if str(path).endswith("undo.json") and not seen_undo and not any(r.get("result") for r in obj["items"]):
        seen_undo.append((len([f for f in snapshot() if snapshot()[f] != snapS0[f]]), len(obj["items"])))      # files already written when the undo file first lands
    return orig_write(path, obj)
SP.write_atomic = spy
rc1, out1 = cli(PM.apply, app=app, plan=str(PLAN))
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("8 apply asks for the plan first (a dry call), then writes: the exit code is 3 (not a failure) when items are listed, 0 when none is", rc1 == (3 if LEFT else 0) and app.log[0] == "members-dry" and "members" in app.log and undo_file.is_file()
      and isinstance(out1, dict) and out1["results"].get("set") == len(WILL) and sorted(out1["listed_in_the_plan"]) == sorted(r["item"] for r in plan_rows if r.get("notes")), (rc1, out1, app.log))
check("8 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == len(WILL), seen_undo)
bk = pathlib.Path(out1["backup"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("8 …the backup holds every touched file byte for byte as it was, and only those (open and closed)", sorted(p.name for p in bk.glob("*.json")) == sorted(f"g{i}.json" for i in WILL) and all((bk / f"g{i}.json").read_bytes() == snapS0[f"{i}.json"] for i in WILL) and 12 in WILL, sorted(p.name for p in bk.glob("*")))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("8 …the undo file names each item with its keys before and after and the real result", {"pass_id", "by", "when", "store", "backup", "items"} <= set(uj) and len(uj["items"]) == len(WILL) and all({"item", "before", "after", "history", "dropped", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("8 …the pass left each touched file as the route wrote it: every answer named, one History line", all(all(a.get("by") for a in (mt(i).get("answers") or [])) and len(STALL.log_of(mt(i))) == 1 for i in WILL), None)
pass_rec = T / "state/migration" / f"{uj.get('pass_id')}.json"
check("8 …the pass kept its results on the server (<state>/migration/<pass id>.json, under `items`: the same count as the undo file)", pass_rec.is_file() and len(json.loads(pass_rec.read_text())["items"]) == len(WILL), uj.get("pass_id"))
rc2, out2 = cli(PM.apply)
check("8 a second apply moves nothing", rc2 == (3 if LEFT else 0) and out2["changed"] == 0 and sorted(out2["left_over"]) == LEFT, (rc2, out2))
d4 = raw(4); d4["metadata"]["answers"].append(ANS(9)); (T / "store/g/4.json").write_text(json.dumps(d4, ensure_ascii=False, indent=1))      # a session saves an answer, on one item the pass wrote
rc3, out3 = cli(PM.undo, undo=str(undo_file))
back = lambda i: {k: v for k, v in mt(i).items() if k != "stall"} == {k: v for k, v in orig_s[i]["metadata"].items() if k != "stall"}
check("8 --undo puts the keys back value for value on the items still as the pass left them, and keeps the one a later save changed", rc3 == 0 and all(back(i) for i in WILL if i != 4) and out3["results"] == {"set": len(WILL) - 1, "kept": 1} and out3["kept_because_a_later_save_changed_them"] == [BOARD + "4"]
      and [a.get("by") for a in mt(4)["answers"]] == ["Oliver", None], (rc3, out3, mt(4).get("answers")))
check("8 …the History line goes with the undo (the stall log is back to what it was), a closed item's answers are unnamed again", all("stall" not in mt(i) for i in WILL if i != 4) and not any(a.get("by") for a in mt(12)["answers"]), None)
rc4, out4 = cli(PM.undo, undo=str(undo_file))
check("8 …undo twice is a no-op", rc4 == 0 and set(out4["results"]) <= {"same", "kept"} and "set" not in out4["results"], (rc4, out4))
script = os.path.join(STACK, "stackshot/tools/members_migrate.py")
check("8 --apply and --undo need --sender", subprocess.run([sys.executable, script, "--apply"], capture_output=True, text=True).returncode != 0 and subprocess.run([sys.executable, script, "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
check("8 --store cannot be combined with --apply", subprocess.run([sys.executable, script, "--apply", "--sender", SENDER, "--store", str(T / "store")], capture_output=True, text=True).returncode != 0, None)
fixtures(); CFGM["migration"] = False
snapD = snapshot(); tD = times()
JSON = RUN / "rows.json"
env = {**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"}
p = subprocess.run([sys.executable, script, "--store", str(T / "store"), "--json", str(JSON)], capture_output=True, text=True, env=env)
m = re.search(r"items the pass would write: (\d+) of (\d+)", p.stdout)
check("8 the dry run over a copy writes nothing live, prints a block per item and the totals, and exits 0", p.returncode == 0 and snapshot() == snapD and times() == tD and "History line: stackshot:" in p.stdout and "answers: 2 with no `by`" in p.stdout
      and "items the pass would write:" in p.stdout and "a second pass: " in p.stdout and "answers that get a name:" in p.stdout, (p.returncode, p.stdout[-1200:], p.stderr[-600:]))
check("8 …the totals count the items it would write, of all of them", m and int(m.group(1)) == len(WILL) and int(m.group(2)) == len(ALL), (m and m.groups(), len(WILL), len(ALL)))
check("8 …its --json holds a row per item, and the second pass on the copy writes nothing", JSON.is_file() and len(json.loads(JSON.read_text())) == len(ALL) and all(r["again"] != "set" for r in json.loads(JSON.read_text())) and "a second pass: " in p.stdout and "set" not in p.stdout.split("a second pass: ")[1].split("\n")[0], p.stdout[-400:])
rcA, outA = cli(PM.apply) if False else (None, None)
CFGM["migration"] = True
rcA, outA = cli(PM.apply)
CFGM["migration"] = False
p2 = subprocess.run([sys.executable, script, "--store", str(T / "store")], capture_output=True, text=True, env=env)
check("8 the series-end check: on the applied store the dry run reads \"items the pass would write: 0\" and exits 0", rcA in (0, 3) and p2.returncode == 0 and re.search(r"items the pass would write: 0 of %d" % len(ALL), p2.stdout), (rcA, p2.returncode, p2.stdout[-500:], p2.stderr[-400:]))

# ---- 9. the gate
fixtures()
b1 = bytes_of(1)
CFGM["migration"] = False
st_, d_ = call(op="members", items=["g1"])
check("9 the route is refused while [model] migration is off", st_ == 403 and bytes_of(1) == b1, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="members", items=["g1"], sender="somebody-else")
check("9 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(1) == b1, (st_, d_))
st_, d_ = call(machine="home-evil", op="members", items=["g1"])
check("9 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(1) == b1, (st_, d_))
st_, d_ = call(op="members", items=["g1"], writes=[{"item": "g1", "set": {"mover": BACK}}])
check("9 …a body naming a key of its own is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(1) == b1, (st_, d_))
st_, d_ = call(op="unmembers", items=[{"item": "g1", "before": {"subject": None}, "after": {"subject": "x"}}])
check("9 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused" and "not a key" in d_["results"][0]["why"], d_)
st_, d_ = call(op="unmembers", items=["g1"], dry=True)
check("9 …dry goes with members only; an empty list is refused", st_ == 400 and call(op="members", items=[])[0] == 400, (st_, d_))
st_, d_ = call(op="members", items=["g9999", "nonsense"])
check("9 …an unknown item and a malformed id are refused one by one", st_ == 200 and [r["action"] for r in d_["results"]] == ["refused", "refused"], (st_, d_))
st_, d_ = call(op="members", items=["g1"])
check("9 …a stamp needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not WK_.holding(), (st_, d_))
entry1 = {k: d_["results"][0][k] for k in ("item", "before", "after", "history", "dropped")}
e_bad = {**entry1, "after": {**entry1["after"], "subject": "x"}}
st_, d_ = call(op="unmembers", items=[e_bad])
check("9 …an undo entry whose before and after name different keys is refused", d_["results"][0]["action"] == "refused", d_)
d1 = raw(1); d1["metadata"]["answers"].append(ANS(9)); (T / "store/g/1.json").write_text(json.dumps(d1, ensure_ascii=False, indent=1)); b1c = bytes_of(1)      # a later save adds an answer
st_, d_ = call(op="unmembers", items=[entry1])
check("9 …an undo of an item saved since the pass is `kept` and leaves the file byte for byte", st_ == 200 and d_["results"][0]["action"] == "kept" and bytes_of(1) == b1c, (st_, d_))
# the ops' first names are read as the new ones for one release: a pass the earlier script began stays reversible
st_n, d_n = call(op="members", items=["g1"], dry=True)
st_o, d_o = call(op="people", items=["g1"], dry=True)
check("9 …the first name of the stamp op (`people`) is read as `members`", st_o == 200 and st_n == 200 and d_o == d_n, (st_o, d_o, st_n, d_n))
st_, d_ = call(op="unpeople", items=[entry1])
check("9 …and the first name of the undo op (`unpeople`) is read as `unmembers`: the same answer", st_ == 200 and d_["results"][0]["action"] == "kept" and bytes_of(1) == b1c, (st_, d_))
CFGM["migration"] = False

# ---- 10. the review lows: a closed decision, a plan edited after the dry run, the earlier run folder
CFGM["migration"] = True
def cli2(fn, app=None, **kw):
    """cli, with the script's own lines (stderr) as well: → exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    return rc, out.getvalue(), err.getvalue()
fixtures()
CLOSED_DECISIONS = {20: dict(DECIDE, outcome="done", reason="it worked", answers=[ANS(1), ANS(2, by="Pat")]),
                    21: dict(DECIDE, mover=OWN, outcome="done", reason="it worked", answers=[ANS(1, by="Oliver")]),
                    22: dict(DECIDE, mover=BACK, outcome="done", reason="it worked", answers=[ANS(1)])}
for i, m in CLOSED_DECISIONS.items(): put(i, status="completed", **m)
o10 = {i: raw(i) for i in CLOSED_DECISIONS}
P10 = {i: PP.plan_for(mt(i), None, False) for i in CLOSED_DECISIONS}
check("10 a closed item that holds a decision with no stored mover gets its answers named and no mover (the pass reads a closed item for its answers alone); the same decision open gets the mover too",
      set(P10[20]["edits"]) == {"answers"} and "mover" not in P10[20]["edits"] and PP.plan_for(mt(20), mod_of(1), True)["edits"].get("mover") == "Oliver", (P10[20], PP.plan_for(mt(20), mod_of(1), True)["edits"].keys()))
check("10 …a closed decision whose mover is stored (the first person, or an agent) keeps it, and one whose answers all carry a `by` has nothing to write", set(P10[22]["edits"]) == {"answers"} and P10[21]["edits"] == {} and not P10[21]["form"], (P10[22], P10[21]))
st_, d_ = call(op="members", items=[f"g{i}" for i in CLOSED_DECISIONS])
r10 = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("10 …the route writes the closed decisions that have an unnamed answer and leaves the other as it is", st_ == 200 and [r10[i]["action"] for i in (20, 21, 22)] == ["set", "same", "set"], (st_, {i: r10[i]["action"] for i in r10}))
check("10 …in the written files only the answers changed: the mover is as it was (none, the first person's, the agent's), and status, needs, ask, options, outcome and next stay",
      all({k: v for k, v in mt(i).items() if k not in ("answers", "stall")} == {k: v for k, v in o10[i]["metadata"].items() if k not in ("answers", "stall")} and {k: v for k, v in raw(i).items() if k != "metadata"} == {k: v for k, v in o10[i].items() if k != "metadata"}
          for i in CLOSED_DECISIONS) and "mover" not in mt(20) and mt(21)["mover"] == OWN and mt(22)["mover"] == BACK, {i: mt(i).get("mover") for i in CLOSED_DECISIONS})
check("10 …every answer of them is named: the unnamed ones the first person, a `by` as it was; a closed item does not show the History line but records it", [a["by"] for a in mt(20)["answers"]] == ["Oliver", "Pat"] and [a["by"] for a in mt(22)["answers"]] == ["Oliver"]
      and len(STALL.log_of(mt(20))) == 1 and len(STALL.log_of(mt(22))) == 1 and not STALL.log_of(mt(21)) and bytes_of(21) == json.dumps(o10[21], ensure_ascii=False, indent=1).encode(), None)

# a plan file edited after the dry run is refused on --apply, nothing written
fixtures()
st_, d_ = call(op="members", items=[f"g{i}" for i in ALL], dry=True)
rows10 = d_["results"] if st_ == 200 else []
def edited(label, fn):
    rs = copy.deepcopy(rows10); fn(rs); f = RUN / f"edited-{label}.json"; f.write_text(json.dumps(rs)); return f
def first_of(action): return next(r for r in rows10 if r["action"] == action)["item"]
def mark(rs, item, **kw):
    for r in rs:
        if r["item"] == item: r.update(kw)
snapE = snapshot(); undosE = sorted(RUN.rglob("undo.json"))
EDITS = {"a row marked refused": (edited("refused", lambda rs: mark(rs, first_of("same"), action="refused")), "differ from the dry run"),
         "a note added to a row": (edited("note", lambda rs: mark(rs, first_of("would_set"), notes=["a note the plan never had"])), "differ from the dry run"),
         "a note taken off a listed row": (edited("unlisted", lambda rs: [r.pop("notes", None) for r in rs if r.get("notes")] and None), "differ from the dry run"),
         "the file's hash of an item changed": (edited("hash", lambda rs: mark(rs, first_of("would_set"), sha256_before="0" * 64)), "the store moved since the dry run")}
if not any(r.get("notes") for r in rows10): EDITS.pop("a note taken off a listed row")        # no row is listed in this fixture: nothing to take off
check("10 the dry run gives rows to edit", st_ == 200 and len(rows10) == len(ALL) and any(r["action"] == "would_set" for r in rows10) and any(r["action"] == "same" for r in rows10), (st_, [r["action"] for r in rows10]))
for label, (f, said) in EDITS.items():
    rcE, outE, errE = cli2(PM.apply, plan=str(f))
    check(f"10 --plan edited after the dry run ({label}): refused with exit 1, saying so, and nothing is written, no undo file", rcE == 1 and said in errE and snapshot() == snapE and sorted(RUN.rglob("undo.json")) == undosE and outE == "", (rcE, errE[-300:], outE[-200:]))
fE = edited("same", lambda rs: None)
rcE, outE, errE = cli2(PM.apply, plan=str(fE))
check("10 …the same file left as the dry run wrote it is applied (the refusals above are the edits, not the file)", rcE in (0, 3) and snapshot() != snapE and "differ from the dry run" not in errE and "moved since" not in errE, (rcE, errE[-300:]))

# the earlier run folder: named only when the run folder is the default one, and only read
NEW = pathlib.Path(_scratch.mkdtemp(prefix="membersmig-dflt-"))
real_default, real_earlier = PM.DEFAULT_RUN, PM.EARLIER_RUN
PM.DEFAULT_RUN, PM.EARLIER_RUN = NEW / "members-run", NEW / "people-run"
def unfinished_undo(folder, pass_id, result=None):
    f = folder / pass_id / "undo.json"; f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"pass_id": pass_id, "by": SENDER, "when": "x", "store": str(T / "store"), "backup": str(f.parent / "items"),
                             "items": [{"item": "g9999", "shown": BOARD + "9999", "before": {"mover": None}, "after": {"mover": "Oliver"}, "history": "", "dropped": [], "sha256_before": "0" * 64, "result": result}]}))
    return f
try:
    earlier = unfinished_undo(PM.EARLIER_RUN, "20250101-000000-abcdef"); kept = earlier.read_bytes()
    named = lambda err, f: "an earlier pass did not finish recording its results" in err and f"--undo {f}" in err
    rcN, outN, errN = cli2(PM.apply, run_dir=str(PM.DEFAULT_RUN))
    check("10 an unfinished pass left in the earlier run folder (people-run) is named by an --apply on the default run folder, with the --undo line", named(errN, earlier) and rcN in (0, 3), (rcN, errN[-500:]))
    check("10 …the earlier folder is only read: nothing is added to it (no lock file, no pass folder) and its undo file is the same bytes", sorted(p.name for p in PM.EARLIER_RUN.iterdir()) == ["20250101-000000-abcdef"] and earlier.read_bytes() == kept and sorted(p.name for p in earlier.parent.iterdir()) == ["undo.json"], sorted(p.name for p in PM.EARLIER_RUN.rglob("*")))
    rcN, outN, errN = cli2(PM.apply, run_dir=str(NEW / "own-run"))
    check("10 …a run folder of one's own never looks there: the same --apply names nothing", "an earlier pass did not finish" not in errN and rcN in (0, 3), (rcN, errN[-500:]))
    newer = unfinished_undo(PM.DEFAULT_RUN, "20250102-000000-abcdef")
    rcN, outN, errN = cli2(PM.apply, run_dir=str(PM.DEFAULT_RUN))
    check("10 …an unfinished pass in the default folder is named as well, and both are told apart by their paths", named(errN, newer) and named(errN, earlier) and errN.count("an earlier pass did not finish") == 2, errN[-700:])
    earlier.write_text(json.dumps({**json.loads(kept), "items": [{**e, "result": "set"} for e in json.loads(kept)["items"]]}))
    newer.write_text(json.dumps({**json.loads(newer.read_text()), "items": [{**e, "result": "set"} for e in json.loads(newer.read_text())["items"]]}))
    rcN, outN, errN = cli2(PM.apply, run_dir=str(PM.DEFAULT_RUN))
    check("10 …a pass whose entries all have their result is not named", "an earlier pass did not finish" not in errN and rcN in (0, 3), errN[-500:])
finally:
    PM.DEFAULT_RUN, PM.EARLIER_RUN = real_default, real_earlier
CFGM["migration"] = False

print(f"members_migrate: {len(ran) - len(fails)} of {len(ran)} checks passed")
if fails:
    print("FAILED:", *fails, sep="\n  ")
    sys.exit(1)
