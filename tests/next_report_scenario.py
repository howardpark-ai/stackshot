"""Scenario test for the daily audit's check of the Next rules (tools/next_report.py, audit.py next-check) — fixture data, no live store, no network, no server socket.

One open item per rule N1 to N7 that breaks it, one that breaks none, and a closed item that would break one: the check names each rule on the item that breaks it and no other, leaves the
closed item and the clean one out, reads a label such as `Status:` as no actor, accepts a role in parentheses, reads a parked item with no step as N6 with the parked-item words, and exempts his own
steps from N7. The tool changes no file (a digest of the store before and after), `--line` and `--json` agree with the listing, and `audit.py next-check` runs the same report.

    tests/run-suite next_report        → exit 0 / 1"""
import hashlib, json, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nrtest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
(T / "store/a").mkdir(parents=True)

import next_report as NR
now = time.time(); OWNER = "00000000-0000-4000-8000-000000000001"
def item(i, status="open", needs=None, **meta):
    base = {"owner": OWNER, "project": "projects/alpha"}
    if needs is not None: base["needs"] = needs
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": {**base, **meta}}))
item(1, needs=["home-agent"], next="home-agent: build it")                                                                       # clean
item(2, needs=["home-agent"], next="Status: waiting for CI\nhome-agent (builder): build it")                                     # N1: a label is no actor (the role in parentheses is fine)
item(3, needs=["decision"], next="home-agent: look at the result", mover="Oliver")                                             # N2: waits on him, no step of his
item(4, needs=["home-agent"], next="home-agent: wait for CI (builder at work since 23:28)",
     steps=[{"text": "home-agent: wait for CI", "status": "open"}])                                                           # N3 (and N7: a stamp): the old step left next unmarked
item(5, needs=["home-agent"], next="home-agent: build it",
     steps=[{"text": "Oliver: pick A or B", "status": "done", "by": "home-agent", "at": NR.PART1_LIVE + 1000}, {"text": "home-agent: build it", "status": "open"}])        # N4
item(6, needs=["home-agent"], next="Oliver: look at the page\nhome-agent: build it")                                              # N5: his open step, the item is not his
item(7, needs=["home-agent"], next="")                                                                                         # N6: open, no step
item(8, needs=["home-agent"], next="", hold=True, wake=now + 86400)                                                            # N6 held: the parked-item words
item(9, needs=["home-agent"], next="home-agent: merged abc1234def and 12 tests passed")                                          # N7
item(10, needs=["decision"], next="Oliver: decide whether to ship it", mover="Oliver")                                       # clean: his step is exempt, he is the mover
item(12, needs=["home-agent"], next="home-agent: wait for CI and the deploy",
     steps=[{"text": "home-agent: wait for CI", "status": "dropped", "by": "home-agent", "at": now - 100}, {"text": "home-agent: wait for CI and the deploy", "status": "open"}])    # clean: a marked drop replaced by a longer step (note d)
item(13, needs=["home-agent"], next="home-agent: build it",
     steps=[{"text": "Oliver: pick A or B", "status": "done", "by": "home-agent", "at": NR.PART1_LIVE - 1000}, {"text": "home-agent: build it", "status": "open"}])        # clean: ticked by a session before part 1 went live (history)
item(14, needs=["decision"], after=["a11"], next="home-agent: look at the result", mover="Oliver")                            # N2: the item it waits after is closed, so it stands on him (the real after_open says so)
item(15, needs=["decision"], next="", mover="Oliver")                                                                       # N2 only: waits on him with no step at all; N6 is not counted twice
DONE_AT = NR.PART1_LIVE + 1000
def his_step(**meta): return dict(needs=["home-agent"], next="home-agent: build it", steps=[{"text": "Oliver: pick A or B", "status": "done", "by": "home-agent", "at": DONE_AT}, {"text": "home-agent: build it", "status": "open"}], **meta)
def said(tag, ts, checked=True): return [{"tag": tag, "quote": "go with A", "session": "s", "msg": "00000000-0000-4000-8000-0000000000aa", "ts": ts, "checked": checked}]
item(16, **his_step(said=said("Acked-by", DONE_AT - 60)))                                                                     # clean: his checked Acked-by words before the mark
item(17, **his_step(answers=[{"ts": DONE_AT - 60, "kind": "decision", "choice": "A", "via": "board"}]))                      # clean: his board answer before the mark
item(18, **his_step(said=said("Acked-by", DONE_AT + 60), answers=[{"ts": DONE_AT + 60, "kind": "decision", "choice": "A", "via": "board"}]))     # N4: both records come after the mark
item(19, **his_step(said=said("Acked-by", DONE_AT - 60, checked=False) + said("Reported-by", DONE_AT - 60)))                  # N4: an unchecked Acked-by and a Reported-by are no answer
item(20, **his_step(said=said("Suggested-by", DONE_AT - 60)))                                                                 # clean: his checked Suggested-by words before the mark
item(11, status="completed", needs=[], next="", steps=[{"text": "Oliver: pick A", "status": "done", "by": "home-agent", "at": now - 100}], outcome="done")   # closed: left alone

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def digest(): return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((T / "store").glob("*/*.json"))}
d0 = digest()

rep = NR.scan(NR.load_all(T / "store"))
by = {}
for f in rep["findings"]: by.setdefault(f["id"], []).append(f["rule"])
rule = lambda i: sorted(set(by.get(f"board#{i}", [])))
check("a clean item and the one with his own open step name no finding", rule(1) == [] and rule(10) == [], by)
check("N1: `Status:` is no actor, a role in parentheses is fine", rule(2) == ["N1"], by)
check("N2: the item waits on Oliver and no open step of his says what he is to do", rule(3) == ["N2"], by)
check("N3: an open step that is an unmarked left-out step with words added; a marked drop replaced by a longer step stays quiet", "N3" in rule(4) and rule(12) == [], by)
check("N4: his step marked done by a session since part 1 went live; one ticked before it is history", rule(5) == ["N4"] and rule(13) == [], by)
check("N4 is quiet when the item carries his checked Acked-by words, or a board answer of his, at or before the mark (also a Suggested-by)", rule(16) == [] and rule(17) == [] and rule(20) == [], by)
check("N4 still fires when no record exists (item 5), when the only records come after the mark, or when the record is an unchecked Acked-by or a Reported-by", rule(5) == ["N4"] and rule(18) == ["N4"] and rule(19) == ["N4"], by)
check("N2 reads the real after links: an item whose `after` item is closed stands on him", rule(14) == ["N2"], by)
check("N5: an open step of his on an item that does not wait on him", rule(6) == ["N5"], by)
check("N6: an open item with no open step, and a held one with the parked-item words",
      rule(7) == ["N6"] and rule(8) == ["N6"] and rule(15) == ["N2"] and any(f["id"] == "board#8" and "wake" in f["detail"] for f in rep["findings"]) and any(f["id"] == "board#7" and "no open step" in f["detail"] for f in rep["findings"]), rep["findings"])
check("N7: a step that reads as a report", "N7" in rule(9) and "N7" in rule(4), by)
check("a closed item is left as it is", "board#11" not in by, by)
check("the counts: 19 open, 1 closed, 12 items break a rule", rep["open"] == 19 and rep["closed"] == 1 and rep["items"] == 12, (rep["open"], rep["closed"], rep["items"]))
check("a finding carries id, project, mover, category and rule", all(set(f) >= {"id", "project", "mover", "category", "rule", "detail"} and f["category"] == "next rules" and f["project"] == "projects/alpha" for f in rep["findings"]), rep["findings"][:2])
check("the check changes no file", digest() == d0, None)

def run(*a):
    r = subprocess.run([sys.executable, *a], capture_output=True, text=True, env=dict(os.environ)); return r.returncode, r.stdout, r.stderr
rc, out, err = run(os.path.join(STACK, "tools", "next_report.py"), "--store", str(T / "store"))
check("the listing: one line per finding, then the counts line; exit 0", rc == 0 and out.count(" | N") == len(rep["findings"]) and "Next rules: 12 item(s) break a rule" in out, (rc, out[-400:], err[-300:]))
rc, out, _ = run(os.path.join(STACK, "tools", "next_report.py"), "--store", str(T / "store"), "--line")
check("--line gives the one line with the counts per rule", rc == 0 and out.strip().startswith("Next rules: 12 item(s) break a rule · N1 1 · N2 3 · N3 1 · N4 3 · N5 1 · N6 2 · N7 2"), out)
rc, out, _ = run(os.path.join(STACK, "audit.py"), "next-check", "--json", "--store", str(T / "store"))
js = json.loads(out) if rc == 0 else {}
check("audit.py next-check --json runs the same report", js.get("findings") == rep["findings"] and js.get("rules") == rep["rules"], (rc, out[:300]))
rc, _, err = run(os.path.join(STACK, "tools", "next_report.py"), "--store", str(T / "no-such"))
check("a --store that is no folder: exit 2", rc == 2, (rc, err))
check("…and nothing was written by any of it", digest() == d0, None)

print(("ok" if not fails else "FAILED") + f": next_report scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
