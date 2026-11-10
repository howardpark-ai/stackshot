"""Scenario test for the one-off move of the old `work` lines onto the steps (stackshot/tools/migrate_work_to_steps.py) — a synthetic store in a scratch folder, no server, no network.

Items as they were stored before the one list: an open item whose builder had a line in progress and three done lines beside its step, one whose line names an agent with no step, one whose
line names no agent, one with an empty `work`, a closed item that still carries `work`, and one with no `work` at all. What the tool must do:

  1  the dry run (the default) reports each open item with what its lines become and writes nothing (a hash of the whole store before and after), and `--dry-run` says the same
  2  --apply writes the undo file first (the previous text of every item it will touch, fsynced) and then the items; each moved item has no `work` field, its in-progress line is the status of the
     agent's step, its done lines are done steps (the fold), a line with no step of its agent makes a new open step, and nothing else on the item changed (`updated`, `state_updated`, `confirmed`,
     the description and the activity clock stay); a closed item and one without `work` are not touched
  3  the readers see the same work before and after: the status lines in progress read the same (text, agent, state) through work.lines_of
  4  running it twice writes nothing the second time; the fold itself is idempotent
  5  --undo puts back every item byte for byte; an item a session saved after the pass is kept as it is and named; undoing twice is a no-op
  6  the command line: no flag is a dry run; --apply with --dry-run, and --undo with --apply, are refused (exit 2)
  7  superseded lines (a second store): of one agent's lines not done only the newest stays live (the status of the agent's open step, else one new open step) and every older one becomes a done
     step; two agents are told apart; a done line mixed in is a done step; equal times: the last in the list is the newest; the report and --json count them; a second run writes nothing; undo restores

    tests/run-suite work_migration        → exit 0 / 1"""
import hashlib, json, os, pathlib, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="workmigtest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.model import work as W; from stackshot.model import steps as S

STORE = T / "store"; (STORE / "a").mkdir(parents=True); RUN = T / "run"
now = time.time(); OWNER = "00000000-0000-4000-8000-000000000001"
def L(text, state="in progress", agent="quill-engineer", ago=600): return {"id": text.replace(" ", "-")[:24], "text": text, "agent": agent, "state": state, "ts": now - ago}
def put(i, status="open", **meta):
    base = {"owner": OWNER, "project": "projects/alpha", "mover": "quill-engineer", "needs": ["quill-engineer"]}
    (STORE / "a" / f"{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing\n- It lives here\n- Finished when it works", "status": status,
                                                       "updated": now - 3000, "state_updated": now - 4000, "confirmed": now - 4000, "activity": now - 3000, "metadata": {**base, **meta}}, indent=1, ensure_ascii=False))
put(1, next="quill-engineer: stage 11, auth and who", work=[L("stage 10: PR 82 up", "done", ago=7200), L("stage 9: PR 81 up", "done", ago=9000), L("stage 8: PR 80 up", "done", ago=11000),
                                                              L("PR 83 up; review, scan 99", "in progress", ago=300)])      # the long-running item's shape
put(2, next="quill-main: look at it", work=[L("migrating the ids", "in progress", agent="quill-docs")])                     # an agent with no step of its own
put(3, next="quill-engineer: build it", work=[L("tests", "defined", agent="")])                                             # no agent: the mover's step
put(4, next="quill-engineer: build it", work=[])                                                                            # an empty list
put(5, status="completed", next="", work=[L("old", "done", ago=99999)], outcome="done", reason="landed")                      # a closed item with the field still on it
put(6, next="quill-engineer: build it")                                                                                     # no work field at all

def tree():
    return {str(p.relative_to(STORE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(STORE.rglob("*")) if p.is_file()}
def rd(i): return json.loads((STORE / "a" / f"{i}.json").read_text())
def run(*args):
    return subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/migrate_work_to_steps.py"), "--store", str(STORE), *args], capture_output=True, text=True, timeout=120)

before = tree(); old = {i: rd(i) for i in range(1, 7)}
lines_before = {i: [(l["text"], l["agent"], l["state"]) for l in W.lines_of(old[i]["metadata"]) if l["state"] == "in progress"] for i in range(1, 7)}

# ---- 1 the dry run
r = run()
check("the dry run (no flag) exits 0, names the four open items with work and the closed one left alone, and says nothing is written", r.returncode == 0 and "dry run: 4 open items would be moved, 1 closed one left as they are; 6 lines: 3 live, 0 superseded (a done step each), 3 done; nothing written" in r.stdout
      and all(f"a{i}  " in r.stdout for i in (1, 2, 3, 4)) and "a5" in r.stdout, (r.returncode, r.stdout[-700:], r.stderr[-300:]))
check("…and it wrote nothing: the store is byte for byte as it was", tree() == before and not RUN.exists())
r2 = run("--dry-run")
check("--dry-run says the same", r2.stdout == r.stdout and tree() == before, r2.stdout[-200:])
rj = run("--json"); js = json.loads(rj.stdout)
check("--json lists the same items", [x["gid"] for x in js["open_items_to_move"]] == ["a1", "a2", "a3", "a4"] and js["closed_left_alone"] == ["a5"], rj.stdout[:300])
check("a line shown in the report reads in plain words: the one in progress becomes the status of the step, a done one a done step", "-> the status of step" in r.stdout and "-> a done step" in r.stdout and "-> a new open step" in r.stdout, r.stdout)

# ---- 2 apply
ra = run("--apply", "--run-dir", str(RUN))
undo_files = sorted(RUN.glob("*/undo.json"))
check("--apply exits 0, reports 4 items moved and where the undo file is", ra.returncode == 0 and "wrote 4 of 4 items" in ra.stdout and len(undo_files) == 1 and str(undo_files[0]) in ra.stdout, (ra.returncode, ra.stdout[-500:], ra.stderr[-300:]))
ud = json.loads(undo_files[0].read_text())
check("the undo file holds the previous text of exactly the four items, with the hash of what the pass wrote", sorted(ud["items"]) == ["a1", "a2", "a3", "a4"]
      and all(e["before_sha"] and e["after_sha"] and e["before_sha"] != e["after_sha"] for e in ud["items"].values())
      and all(hashlib.sha256(e["before"].encode()).hexdigest() == e["before_sha"] for e in ud["items"].values()), list(ud["items"]))
after = {i: rd(i) for i in range(1, 7)}
check("no moved item has a `work` field; the closed one keeps it; the one with none is untouched", all("work" not in after[i]["metadata"] for i in (1, 2, 3, 4)) and "work" in after[5]["metadata"] and after[6] == old[6] and after[5] == old[5])
m1 = after[1]["metadata"]; st1 = S.view(m1)
check("item 1: three done lines became three done steps (the fold), the line in progress is the status of the open step, in place", [x["status"] for x in st1] == ["done", "done", "done", "open"]
      and (S.tag_of(st1[3]) or {}).get("text") == "PR 83 up; review, scan 99" and (S.tag_of(st1[3]) or {}).get("state") == "in progress" and m1["next"] == old[1]["metadata"]["next"], (st1, m1["next"]))
check("…the done steps read oldest first, each by its agent and at its time, with its status done", [x["text"] for x in st1[:3]] == ["quill-engineer: stage 8: PR 80 up", "quill-engineer: stage 9: PR 81 up", "quill-engineer: stage 10: PR 82 up"]
      and all((S.tag_of(x) or {}).get("state") == "done" and x.get("by") == "quill-engineer" and x.get("at") for x in st1[:3]), st1[:3])
st2 = S.view(after[2]["metadata"])
check("item 2: a line whose agent has no step makes a new open step for it, carrying the status", [(S.opener(x["text"]), x["status"], (S.tag_of(x) or {}).get("text")) for x in st2] == [("quill-main", "open", None), ("quill-docs", "open", "migrating the ids")]
      and after[2]["metadata"]["next"].endswith("\nquill-docs: migrating the ids"), (st2, after[2]["metadata"]["next"]))
st3 = S.view(after[3]["metadata"])
check("item 3: a line with no agent is the mover's: the status of the mover's step", [(S.opener(x["text"]), (S.tag_of(x) or {}).get("text"), (S.tag_of(x) or {}).get("state")) for x in st3] == [("quill-engineer", "tests", "defined")], st3)
check("item 4: an empty list is just removed", "work" not in after[4]["metadata"] and after[4]["metadata"]["next"] == old[4]["metadata"]["next"])
check("nothing else on a moved item changed: the clocks, the description, the owner, the needs", all({k: v for k, v in after[i].items() if k != "metadata"} == {k: v for k, v in old[i].items() if k != "metadata"}
      and all(after[i]["metadata"][k] == old[i]["metadata"][k] for k in ("owner", "project", "mover", "needs")) for i in (1, 2, 3, 4)))

# ---- 3 the readers
lines_after = {i: [(l["text"], l["agent"], l["state"]) for l in W.lines_of(after[i]["metadata"]) if l["state"] == "in progress"] for i in range(1, 7)}
check("the readers see the same work in progress before and after (text, agent, state) for every moved item", lines_after[1] == lines_before[1] == [("PR 83 up; review, scan 99", "quill-engineer", "in progress")]
      and lines_after[2] == lines_before[2] and lines_after[6] == lines_before[6] == [], (lines_before, lines_after))
check("a defined line stays defined (it is not in progress) and is still read", [(l["text"], l["state"]) for l in W.lines_of(after[3]["metadata"])] == [("tests", "defined")])

# ---- 4 idempotent
tr = tree(); rb = run("--apply", "--run-dir", str(RUN))
check("a second --apply finds nothing to move, writes nothing and keeps no second undo file", rb.returncode == 0 and "nothing to move" in rb.stdout and tree() == tr and len(list(RUN.glob("*/undo.json"))) == 1, (rb.stdout[-300:], tree() == tr))
f1, _n = W.fold_legacy(old[1]["metadata"]); f2, n2 = W.fold_legacy(f1)
check("the fold is idempotent: folding the result changes nothing and notes nothing", f1 == f2 and n2 == [] and "work" not in f1)
check("the dry run after the pass has nothing to move (the closed item is still counted as left alone)", "dry run: 0 open items would be moved, 1 closed one left as they are" in run().stdout)

# ---- 5 undo
(STORE / "a" / "2.json").write_text(json.dumps({**rd(2), "subject": "[home] a session saved this after the pass"}, indent=1, ensure_ascii=False))      # a later save
ru = run("--undo", str(undo_files[0]))
check("--undo puts back items 1, 3 and 4 byte for byte, and keeps item 2, saved since the pass, as it is, naming it", ru.returncode == 0 and "a1: put back" in ru.stdout and "a3: put back" in ru.stdout and "a4: put back" in ru.stdout and "a2: kept" in ru.stdout
      and all((STORE / "a" / f"{i}.json").read_text() == ud["items"][f"a{i}"]["before"] for i in (1, 3, 4)) and rd(2)["subject"].endswith("after the pass"), (ru.returncode, ru.stdout))
tr = tree(); ru2 = run("--undo", str(undo_files[0]))
check("undoing twice changes nothing more (the restored items say `same`)", ru2.returncode == 0 and "a1: same" in ru2.stdout and tree() == tr, ru2.stdout)

# ---- 6 arguments
check("--apply with --dry-run is refused (exit 2)", run("--apply", "--dry-run").returncode == 2)
check("--undo with --apply is refused (exit 2)", run("--undo", str(undo_files[0]), "--apply").returncode == 2)

# ---- 7 superseded lines
STORE2 = T / "store2"; (STORE2 / "b").mkdir(parents=True); RUN2 = T / "run2"
def put2(i, **meta):
    base = {"owner": OWNER, "project": "projects/alpha", "mover": "quill-engineer", "needs": ["quill-engineer"]}
    (STORE2 / "b" / f"{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item b{i}", "description": "- A thing\n- It lives here\n- Finished when it works", "status": "open",
                                                        "updated": now - 3000, "state_updated": now - 4000, "confirmed": now - 4000, "activity": now - 3000, "metadata": {**base, **meta}}, indent=1, ensure_ascii=False))
def run2(*args):
    return subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/migrate_work_to_steps.py"), "--store", str(STORE2), *args], capture_output=True, text=True, timeout=120)
def rd2(i): return json.loads((STORE2 / "b" / f"{i}.json").read_text())
def tree2(): return {str(p.relative_to(STORE2)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(STORE2.rglob("*")) if p.is_file()}
put2(1, next="quill-engineer: build it", work=[L("third try", ago=300), L("first try", "defined", ago=900), L("second try", "assigned", ago=600)])      # stored out of order: the newest is by time
put2(2, next="quill-main: look at it", work=[L("one", ago=900), L("two", ago=600), L("three", ago=300)])                                              # no open step of the agent
put2(3, next="quill-engineer: build it\nquill-docs: write it", work=[L("e1", ago=900), L("d1", agent="quill-docs", ago=800), L("e2", ago=700), L("d2", agent="quill-docs", ago=100)])
put2(4, next="quill-engineer: build it", work=[L("shipped", "done", ago=5000), L("early", ago=900), L("late", ago=300), L("also shipped", "done", ago=100)])          # a done line mixed in, one newer than the live line
put2(5, next="quill-engineer: build it", work=[L("alpha", ago=500), L("omega", ago=500)])                                                            # equal times: the last in the list
put2(6, next="quill-engineer: build it", work=[L("lone", ago=500)])                                                                                  # nothing to supersede
before2 = tree2(); old2 = {i: rd2(i) for i in range(1, 7)}
r = run2()
check("the dry run counts the lines: 17 in all, 7 live, 8 superseded (a done step each), 2 done; each item says its own", r.returncode == 0
      and "17 lines: 7 live, 8 superseded (a done step each), 2 done; nothing written" in r.stdout and "b1  [home] item b1  (3 lines: 1 live, 2 superseded, 0 done)" in r.stdout
      and "b4  [home] item b4  (4 lines: 1 live, 1 superseded, 2 done)" in r.stdout and "b6  [home] item b6  (1 line: 1 live, 0 superseded, 0 done)" in r.stdout, (r.returncode, r.stdout[-1500:], r.stderr[-300:]))
check("…a superseded line reads `superseded line \"<text>\" -> a done step`, and the dry run wrote nothing", 'superseded line "first try" -> a done step' in r.stdout and 'superseded line "second try" -> a done step' in r.stdout
      and 'line "third try" -> the status of step 3' in r.stdout and tree2() == before2 and not RUN2.exists(), r.stdout[:800])
js = json.loads(run2("--json").stdout)
check("--json carries the same counts, per item and in all", js["lines"] == {"lines": 17, "live": 7, "superseded": 8, "done": 2}
      and {x["gid"]: (x["live"], x["superseded"], x["done"]) for x in js["open_items_to_move"]} == {"b1": (1, 2, 0), "b2": (1, 2, 0), "b3": (2, 2, 0), "b4": (1, 1, 2), "b5": (1, 1, 0), "b6": (1, 0, 0)}, js)
ra = run2("--apply", "--run-dir", str(RUN2)); ud2 = sorted(RUN2.glob("*/undo.json"))
check("--apply moves the six items and writes one undo file", ra.returncode == 0 and "wrote 6 of 6 items" in ra.stdout and len(ud2) == 1, (ra.returncode, ra.stdout[-400:], ra.stderr[-300:]))
af2 = {i: rd2(i) for i in range(1, 7)}
def shape(i): return [(S.opener(x["text"]), x["text"].split(": ", 1)[-1], x["status"], (S.tag_of(x) or {}).get("text"), (S.tag_of(x) or {}).get("state")) for x in S.view(af2[i]["metadata"])]
check("b1: the newest line (by time, not by place in the list) is the status of the open step; the two older are done steps, oldest first",
      shape(1) == [("quill-engineer", "first try", "done", "first try", "done"), ("quill-engineer", "second try", "done", "second try", "done"), ("quill-engineer", "build it", "open", "third try", "in progress")]
      and af2[1]["metadata"]["next"] == old2[1]["metadata"]["next"], shape(1))
check("b1: each done step is by its agent and at its line's time", [(x.get("by"), x.get("at")) for x in S.view(af2[1]["metadata"])[:2]] == [("quill-engineer", now - 900), ("quill-engineer", now - 600)], S.view(af2[1]["metadata"])[:2])
check("b2: with no open step of the agent the newest becomes one new open step carrying the status; the older two are done steps",
      shape(2) == [("quill-engineer", "one", "done", "one", "done"), ("quill-engineer", "two", "done", "two", "done"), ("quill-main", "look at it", "open", None, None), ("quill-engineer", "three", "open", "three", "in progress")]
      and af2[2]["metadata"]["next"].endswith("\nquill-engineer: three"), shape(2))
check("b3: two agents are told apart: each keeps its own newest line on its own step and has its older line done",
      shape(3) == [("quill-engineer", "e1", "done", "e1", "done"), ("quill-docs", "d1", "done", "d1", "done"), ("quill-engineer", "build it", "open", "e2", "in progress"), ("quill-docs", "write it", "open", "d2", "in progress")], shape(3))
check("b4: done lines stay done steps; the older line in progress is superseded; the newest in progress is live (a done line newer than it changes nothing)",
      shape(4) == [("quill-engineer", "shipped", "done", "shipped", "done"), ("quill-engineer", "early", "done", "early", "done"), ("quill-engineer", "also shipped", "done", "also shipped", "done"), ("quill-engineer", "build it", "open", "late", "in progress")], shape(4))
check("b5: equal times: the last line in the list is the newest", shape(5) == [("quill-engineer", "alpha", "done", "alpha", "done"), ("quill-engineer", "build it", "open", "omega", "in progress")], shape(5))
check("b6: a lone line is just the status of the step, as before", shape(6) == [("quill-engineer", "build it", "open", "lone", "in progress")], shape(6))
check("no moved item has a `work` field, and the readers see one live line per agent (never a superseded one)", all("work" not in af2[i]["metadata"] for i in range(1, 7))
      and sorted((l["agent"], l["text"]) for l in W.lines_of(af2[3]["metadata"]) if l["state"] != "done") == [("quill-docs", "d2"), ("quill-engineer", "e2")]
      and all(len([l for l in W.open_lines(af2[i]["metadata"])]) == (2 if i == 3 else 1) for i in range(1, 7)), [W.open_lines(af2[i]["metadata"]) for i in range(1, 7)])
check("only the checklist's open steps stay open: the superseded lines add no open step", [sum(x["status"] == "open" for x in S.view(af2[i]["metadata"])) for i in range(1, 7)] == [1, 2, 2, 1, 1, 1], [S.view(af2[i]["metadata"]) for i in range(1, 7)])
tr = tree2(); rb = run2("--apply", "--run-dir", str(RUN2))
check("a second --apply writes nothing and keeps no second undo file", rb.returncode == 0 and "nothing to move" in rb.stdout and tree2() == tr and len(list(RUN2.glob("*/undo.json"))) == 1, rb.stdout[-300:])
f1, _n = W.fold_legacy(old2[3]["metadata"]); f2, n2 = W.fold_legacy(f1)
check("the fold is idempotent with superseded lines too", f1 == f2 and n2 == [] and "work" not in f1)
ru = run2("--undo", str(ud2[0]))
check("--undo puts back all six items byte for byte; again says `same`", ru.returncode == 0 and ru.stdout.count("put back") == 6 and tree2() == before2 and run2("--undo", str(ud2[0])).stdout.count("same") == 6, (ru.stdout, ))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + (f"; FAILED: {len(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
