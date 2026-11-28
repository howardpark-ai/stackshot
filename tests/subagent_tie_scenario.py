"""Scenario test for the module the session manager imports (audit/subagent_tie.py): `running(session, roots, now)`, the producer-side rule for which subagents of a session are running, read from the transcript Claude Code
keeps beside the session's (`<root>/<working-directory folder>/<session uuid>/subagents/agent-<id>.meta.json` and `.jsonl`), and the tie of a subagent to an item. The server's own audit pass does not call `running` (it reads
the agent-state snapshot, tests/agent_state_scenario.py); the sender of that snapshot does, so these checks are the rule's own. A temporary folder of fake transcripts, a fake clock, no live store, no network.

  1  the public interface the sender imports: `running(session, roots, now)`, a numeric `RUNNING_S`, and the helpers `running` uses (`pending_tasks`, `read_parent`, `resumes`, `interrupted`, `Unreadable`)
  2  the reader of a session's transcript: running within 90 minutes, quiet to 6 hours, dropped past the cap, clock skew, what each unreadable thing reads as (unknown), a first line nested too deep, the pure tie
  3  a subagent flagged finished that is only parked or resumed still runs: parked on a background Bash or a Monitor of its own, an end notice that only the session's transcript holds, a start that is only quoted, a start named by
     the record beside a command's result (its output first, the sentence after it), a Monitor's
     lifetime, one with no flag whose last row is an interruption (dead unless resumed), a resume that is only quoted, the tail limits, the values of the windows pinned

    tests/run-suite subagent_tie       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging, inspect
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="subagent-tie-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
from stackshot.audit import subagent_tie as TIE
import uuid as _uuid
H = 3600.0
now0 = float(int(time.time()))
def BID(n): return "board" + "#" + str(n)                              # an item id as a brief names it, built from pieces
WI = "https://github.com/acme/widgets"
(T / "transcripts/-home-x").mkdir(parents=True)

# ================================================================ 1. the public interface the sender imports
# PUBLIC INTERFACE of audit/subagent_tie.py: the session manager imports this module on the box that runs the panes and calls `running(session_id, roots, now)` and reads `RUNNING_S`. A rename or a changed signature here
# breaks every agent's state (it would read unknown) once released, so these names and this call shape are pinned, with the helpers `running` uses.
_p = list(inspect.signature(TIE.running).parameters)
check("1 the names the sender imports exist: `running(session, roots, now)` with those three parameters in that order, and `RUNNING_S` a number (90 minutes)",
      callable(TIE.running) and _p == ["session", "roots", "now"] and isinstance(TIE.RUNNING_S, float) and TIE.RUNNING_S == 5400.0, (_p, getattr(TIE, "RUNNING_S", None)))
check("1 …and the helpers it uses, `Unreadable` an exception the sender can catch",
      all(callable(getattr(TIE, n, None)) for n in ("pending_tasks", "read_parent", "resumes", "interrupted", "tied", "tied_to", "names_item")) and isinstance(TIE.Unreadable, type) and issubclass(TIE.Unreadable, Exception))
try: TIE.running(str(_uuid.uuid4()), [str(T / "transcripts")], now0); _raised = False
except TIE.Unreadable: _raised = True
check("1 …called as the sender calls it (`running(sid, roots, now)`, the roots a list of strings): a session with no transcript on the box raises `Unreadable`", _raised)

# ================================================================ 2. the reader of a session's transcript
# the reader: the transcript Claude Code keeps beside a session's
import uuid as _uuid
SID = str(_uuid.UUID("00000000-0000-4000-8000-0000000000aa"))
proj = T / "transcripts/-home-x"; (proj / SID / "subagents").mkdir(parents=True); (proj / f"{SID}.jsonl").write_text("{}\n")
def agent(aid, desc, brief, finished=None, age=60, content="str", meta_ok=True):
    mp, tp = proj / SID / "subagents" / f"agent-{aid}.meta.json", proj / SID / "subagents" / f"agent-{aid}.jsonl"
    m = {"agentType": "general-purpose", "description": desc}
    if finished is not None: m["finished"] = finished
    mp.write_text(json.dumps(m) if meta_ok else "{not json")
    body = brief if content == "str" else [{"type": "text", "text": brief}]
    tp.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": body}}) + "\n" + json.dumps({"type": "assistant"}) + "\n")
    os.utime(tp, (now0 - age, now0 - age))
agent("run1", "Build the thing", f"Goal: {BID(1)} in the worktree")
agent("blocks", "Review", f"Please review {BID(2)}", content="blocks")
agent("done1", "Old work", f"{BID(3)}", finished=True)
agent("stale1", "Left behind", f"{BID(4)}", age=int(TIE.RUNNING_S) + 60)
agent("badmeta", "x", f"{BID(5)}", meta_ok=False)
agent("capped1", "Long gone", f"{BID(6)}", age=int(TIE.QUIET_CAP_S) + 60)
got_run = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}
check("17 the reader lists the running subagents of a session's transcript: no finished flag and a transcript written within the 6-hour cap, the description, the brief (a string or text blocks) and both as its text; a finished one and one past the cap are left out, a meta that cannot be read is listed running with no words (it may be running)",
      sorted(got_run) == ["badmeta", "blocks", "run1", "stale1"] and {k_: v_ for k_, v_ in got_run["badmeta"].items() if k_ != "meta_at"} == {"id": "badmeta", "text": "", "at": 0.0, "unreadable": True} and isinstance(got_run["badmeta"].get("meta_at"), float) and got_run["run1"]["text"] == f"Build the thing\nGoal: {BID(1)} in the worktree"
      and got_run["run1"]["description"] == "Build the thing" and got_run["run1"]["brief"] == f"Goal: {BID(1)} in the worktree" and BID(2) in got_run["blocks"]["brief"] and got_run["run1"]["at"] == now0 - 60 and "quiet" not in got_run["run1"], got_run)
check("17 …one older than 90 minutes and younger than the cap is listed running but quiet (a builder waiting on a long run), a fresh one is not marked", got_run["stale1"].get("quiet") is True and got_run["stale1"]["description"] == "Left behind" and "capped1" not in got_run and "done1" not in got_run, got_run.get("stale1"))
# the boundaries, with two seconds of room for the file system's time resolution
agent("b1", "At 90", f"{BID(7)}", age=int(TIE.RUNNING_S) - 2); agent("b2", "Past 90", f"{BID(7)}", age=int(TIE.RUNNING_S) + 2)
agent("b3", "Inside cap", f"{BID(7)}", age=int(TIE.QUIET_CAP_S) - 2); agent("b4", "Past cap", f"{BID(7)}", age=int(TIE.QUIET_CAP_S) + 2)
agent("b5", "Ahead by a skew", f"{BID(7)}", age=-int(TIE.SKEW_S) + 2); agent("b6", "Ahead too far", f"{BID(7)}", age=-int(TIE.SKEW_S) - 2)
got_b = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}
check("17 the 90-minute boundary: a transcript written 90 minutes less two seconds ago is running (not quiet), 90 minutes and two seconds ago is quiet; the cap: 6 hours less two seconds is listed (quiet), 6 hours and two seconds is dropped",
      "quiet" not in got_b["b1"] and got_b["b2"].get("quiet") is True and got_b["b3"].get("quiet") is True and "b4" not in got_b, {k: v.get("quiet") for k, v in got_b.items() if k.startswith("b")})
check("17 clock skew: a transcript dated up to five minutes ahead of the clock is running (a skew of clocks), one dated further ahead is dropped, never listed as running for good", "b5" in got_b and "quiet" not in got_b["b5"] and "b6" not in got_b, sorted(got_b))
for n_ in ("b1", "b2", "b3", "b4", "b5", "b6", "capped1"):
    for ext_ in ("meta.json", "jsonl"): (proj / SID / "subagents" / f"agent-{n_}.{ext_}").unlink()
def raises(fn, exc):
    try: fn()
    except exc: return True
    except Exception: return False
    return False
check("17 …a session with no transcript on this box, a name that is no uuid and no roots cannot be read (Unreadable: unknown, not nothing running); a transcript with no subagents folder and a clock seven hours on (past the cap) give none",
      raises(lambda: TIE.running(str(_uuid.uuid4()), [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running("home-peer", [str(T / "transcripts")], now0), TIE.Unreadable) and raises(lambda: TIE.running(SID, [], now0), TIE.Unreadable)
      and TIE.running(SID, [str(T / "transcripts")], now0 + 7 * H) == [])
SID2 = str(_uuid.UUID("00000000-0000-4000-8000-0000000000bb")); (proj / f"{SID2}.jsonl").write_text("{}\n")
check("17 …a transcript that has never had a subagent (no subagents folder) has none running: known, not unknown", TIE.running(SID2, [str(T / "transcripts")], now0) == [])
# a first line nested past the parser's depth (a RecursionError) and one that is not JSON, a truncated one, a list that is no text: the subagent is still listed, naming nothing
agent("deep", "Deep one", "x"); (proj / SID / "subagents" / "agent-deep.jsonl").write_text("[" * 200000 + "\n"); os.utime(proj / SID / "subagents" / "agent-deep.jsonl", (now0 - 60, now0 - 60))
agent("junk", "Junk one", "x"); (proj / SID / "subagents" / "agent-junk.jsonl").write_text("not json at all\n"); os.utime(proj / SID / "subagents" / "agent-junk.jsonl", (now0 - 60, now0 - 60))
try: got_deep = {x["id"]: x for x in TIE.running(SID, [str(T / "transcripts")], now0)}; err_deep = None
except BaseException as e_: got_deep, err_deep = {}, e_
check("17 a first line nested too deep (RecursionError) or not JSON never raises out of the reader: the subagent is listed running with its description and no brief, so it ties to nothing and the mover reads unknown",
      err_deep is None and got_deep.get("deep", {}).get("text") == "Deep one\n" and got_deep.get("junk", {}).get("text") == "Junk one\n" and not TIE.tied([got_deep["deep"]], BID(1)), (err_deep, got_deep.get("deep")))
for n_ in ("deep", "junk", "badmeta"):
    for ext_ in ("meta.json", "jsonl"): (proj / SID / "subagents" / f"agent-{n_}.{ext_}").unlink()
check("17 the pure tie: the id whole, a pull request by its URL or `PR n`/`#n` for the repository it is anchored in, never another number, another repository or a longer id; no text and no keys tie nothing",
      TIE.names_item(f"x {BID(1)}.", BID(1)) and TIE.names_item(f"X {BID(1).upper()}", BID(1)) and not TIE.names_item(BID(12), BID(1)) and not TIE.names_item("x" + BID(1), BID(1)) and not TIE.names_item("x" + BID(1), BID(1))
      and TIE.names_item("see PR 160", BID(9), ["acme/widgets#160"]) and TIE.names_item("see #160", BID(9), ["acme/widgets#160"]) and TIE.names_item(f"{WI}/pull/160", BID(9), ["Acme/Widgets#160"]) and not TIE.names_item("see PR 1600", BID(9), ["acme/widgets#160"])
      and not TIE.names_item("https://github.com/other/repo/pull/160", BID(9), ["acme/widgets#160"]) and not TIE.names_item("", BID(1), ["acme/widgets#160"]) and not TIE.names_item("PR 160", "", []) and TIE.tied([{"text": f"a {BID(1)}"}], BID(1)) and not TIE.tied([], BID(1)) and not TIE.tied(None, BID(1)))

# ================================================================ 25. a subagent flagged finished that is only parked or resumed still runs
# Claude Code writes `finished: true` into a subagent's meta at the end of every turn, also one that ends waiting for a background task of its own; a resume or the task's notice drops it again.
SID3 = str(_uuid.UUID("00000000-0000-4000-8000-0000000000cc"))
sub3 = proj / SID3 / "subagents"; sub3.mkdir(parents=True)
par3 = proj / f"{SID3}.jsonl"
def _res(text, t=None): return {"type": "user", **({"timestamp": iso(t)} if t is not None else {}), "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}}
BGR = lambda tid, t=None: _res(f"Command running in background with ID: {tid}. Output is being written to: /x/{tid}.output. You will be notified when it completes.", t)
BGM = lambda tid: _res(f"Command was moved to the background (ID: {tid}) after running for 180s. You will be notified when it completes.")
BGT = lambda tid: _res(f"Command did not complete within its 120s timeout and was moved to the background (ID: {tid}). Output is being written to: /x/{tid}.output")
MON = lambda tid, life="expires in 30m unless the source ends first; you get one notice at expiry", t=None: _res(f"Monitor started (task {tid}{', ' + life if life else ''}). You will be notified on each event.", t)
NOTE = lambda tid, status="completed": {"type": "attachment", "attachment": {"type": "queued_command", "prompt": f"<task-notification>\n<task-id>{tid}</task-id>\n<output-file>/x/{tid}.output</output-file>\n<status>{status}</status>\n<summary>done</summary>\n</task-notification>"}}
EVT = lambda tid: {"type": "attachment", "attachment": {"type": "queued_command", "prompt": f"<task-notification>\n<task-id>{tid}</task-id>\n<summary>Monitor event: \"w\"</summary>\n<event>one more line</event>\n</task-notification>"}}
STOP = lambda tid: {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "TaskStop", "input": {"task_id": tid}}]}}
def fin(aid, extra=(), age=60, meta_age=600, finished=True, desc=None, brief=None):
    """a subagent of SID3: its transcript (the brief, then `extra` records) written `age` s ago, its meta (flag `finished`) written `meta_age` s ago"""
    mp, tp = sub3 / f"agent-{aid}.meta.json", sub3 / f"agent-{aid}.jsonl"
    m = {"agentType": "general-purpose", "description": desc or f"Review {aid}"}
    if finished is not None: m["finished"] = finished
    mp.write_text(json.dumps(m))
    tp.write_text("\n".join(json.dumps(r) for r in [{"type": "user", "message": {"role": "user", "content": brief or f"Review the change of {aid}"}}, *extra]) + "\n")
    os.utime(tp, (now0 - age, now0 - age)); os.utime(mp, (now0 - meta_age, now0 - meta_age))
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".250Z"
def resume_rec(aid, t, key="resumedAgentId", typ="user", both=False):
    res = {"success": True, "message": "Resuming agent", key: aid, **({"revivedAgentId" if key == "resumedAgentId" else "resumedAgentId": aid} if both else {})}
    return {"type": typ, "timestamp": iso(t), "message": {"role": "user", "content": [{"type": "tool_result", "content": [{"type": "text", "text": json.dumps(res)}]}]}, **({"toolUseResult": res} if typ == "user" else {})}
def parent(*recs, filler=0):
    par3.write_text("\n".join(json.dumps(r) for r in recs) + ("\n" + json.dumps({"type": "assistant", "x": "y" * filler}) if filler else "") + "\n")
def run3(): return {x["id"]: x for x in TIE.running(SID3, [str(T / "transcripts")], now0)}
parent({"type": "assistant", "message": {"role": "assistant", "content": "idle"}})
fin("pend1", [BGR("bg0001")]); fin("pend2", [BGM("bg0002")]); fin("pend3", [MON("mon001"), EVT("mon001"), EVT("mon001")])
fin("ended1", [BGR("bg0003"), NOTE("bg0003")]); fin("ended2", [MON("mon002"), NOTE("mon002")]); fin("ended3", [MON("mon003"), STOP("mon003")]); fin("ended4", [BGR("bg0004"), NOTE("bg0004", "failed")])
fin("half1", [BGR("bg0005"), BGR("bg0006"), NOTE("bg0005")])                                 # one of two tasks ended, the other still waits
fin("none1", [{"type": "assistant", "message": {"role": "assistant", "content": "done"}}])      # finished, nothing pending
fin("old1", [BGR("bg0007")], age=int(TIE.PARKED_S) + 60)                                       # pending, but its transcript is older than the window
fin("old2", [BGR("bg0008")], age=int(TIE.PARKED_S) - 2)
fin("capped2", [BGR("bg0009")], age=int(TIE.QUIET_CAP_S) + 60)
fin("live1", [BGR("bg0010")], finished=None)                                                   # no flag: running as ever
got25 = run3()
check("25 a subagent flagged finished whose own transcript holds a background Bash (started so, or moved there after its timeout) or a Monitor with no ending notice, written within 90 minutes, is running, in the shape of an unfinished one (no `quiet`)",
      all(k in got25 for k in ("pend1", "pend2", "pend3", "old2")) and got25["pend1"] == {"id": "pend1", "description": "Review pend1", "brief": "Review the change of pend1", "text": "Review pend1\nReview the change of pend1", "at": now0 - 60}
      and all("quiet" not in got25[k] for k in ("pend1", "pend2", "pend3", "old2")), sorted(got25))
check("25 …a Monitor's per-event notices end nothing (pend3 has two and still waits), and one of two tasks ended leaves the subagent parked on the other",
      "pend3" in got25 and "half1" in got25, sorted(got25))
check("25 …a task ended by a notice with a status (completed or failed), by a Monitor's end notice or by a TaskStop is no longer pending: the subagent is not running", not any(k in got25 for k in ("ended1", "ended2", "ended3", "ended4")), sorted(got25))
check("25 …finished with nothing pending (and no resume): not running, as before", "none1" not in got25, sorted(got25))
check("25 …a pending task whose subagent wrote nothing for more than 90 minutes is not running (90 minutes less two seconds is), and one past the 6-hour cap is dropped as ever; a subagent with no flag is as before", "old1" not in got25 and "old2" in got25 and "capped2" not in got25 and "live1" in got25, sorted(got25))
check("25 pending_tasks names the ids that wait", TIE.pending_tasks(sub3 / "agent-half1.jsonl") == {"bg0006"} and TIE.pending_tasks(sub3 / "agent-pend3.jsonl") == {"mon001"} and TIE.pending_tasks(sub3 / "agent-ended4.jsonl") == set()
      and TIE.pending_tasks(sub3 / "agent-none1.jsonl") == set() and TIE.pending_tasks(sub3 / "agent-missing.jsonl") == set(), None)
# the parent's resume
for f_ in sub3.glob("agent-*"): f_.unlink()
fin("res1", meta_age=600); fin("res2", meta_age=600); fin("res3", meta_age=600); fin("res4", meta_age=600); fin("res5", meta_age=600); fin("res6", meta_age=600); fin("res7", meta_age=600, age=100 * 60)
parent({"type": "assistant", "message": {"role": "assistant", "content": "x"}},
       resume_rec("res1", now0 - 300),                                                      # newer than the meta's write (600 s ago): resumed since
       resume_rec("res2", now0 - 300, key="revivedAgentId"),                                # the same on Claude Code 2.1.323
       resume_rec("res3", now0 - 900),                                                      # older than the meta's write: it ended after the resume
       resume_rec("res4", now0 - 300, typ="assistant"),                                     # an assistant message that quotes the words resumes nothing
       resume_rec("res7", now0 - 300, both=True),
       resume_rec("other", now0 - 300))                                                     # another subagent's
got25b = run3()
check("25 a subagent flagged finished that the session's transcript resumed (`resumedAgentId`, or `revivedAgentId`) after its meta's last write is running; one resumed before that write, one the session never resumed, one only an assistant record quotes, and a resume of another subagent are not",
      {"res1", "res2", "res7"} <= set(got25b) and not ({"res3", "res4", "res5", "res6"} & set(got25b)), sorted(got25b))
check("25 …the `quiet` rule is unchanged: a resumed one whose transcript is 100 minutes old is running but quiet, a fresh one is not", got25b["res7"].get("quiet") is True and "quiet" not in got25b["res1"], {k: v.get("quiet") for k, v in got25b.items()})
check("25 resumes: the newest resume time of each subagent, as epoch seconds", abs(TIE.resumes(par3)["res1"] - (now0 - 300 + 0.25)) < 0.01 and "res4" not in TIE.resumes(par3) and TIE.resumes(par3 / "missing") == {}, TIE.resumes(par3))
slack25 = {}
for rs_, sec_ in (("res1", 599), ("res2", 600), ("res3", 601), ("res4", 602), ("res5", 603)):          # the meta was written 600 s ago; a record's time carries a quarter of a second
    parent(resume_rec(rs_, now0 - sec_))
    slack25[sec_] = rs_ in run3()
check("25 …a resume dated as the meta's write or within a second before it counts (a clock's grain), one dated more than a second before it does not (the slack is one second, no more, no less)",
      slack25 == {599: True, 600: True, 601: True, 602: False, 603: False}, slack25)
parent(resume_rec("res1", now0 - 300), filler=64 * 1024); saved_tail = TIE.TAIL_BYTES; TIE.TAIL_BYTES = 4096
try: got25d = run3()
finally: TIE.TAIL_BYTES = saved_tail
check("25 …only the tail of the session's transcript is read: a resume further back than TAIL_BYTES from its end is not seen", "res1" not in got25d, sorted(got25d))
# the session's transcript is read only when it is needed, once, and never raises
reads = []; real_rp = TIE.read_parent
TIE.read_parent = lambda tr: (reads.append(tr), real_rp(tr))[1]
def n_reads(*subs):
    for f_ in sub3.glob("agent-*"): f_.unlink()
    for s_ in subs: s_()
    reads.clear(); run3(); return len(reads)
try:
    n25 = (n_reads(), n_reads(lambda: fin("u1", finished=None), lambda: fin("u2", [BGR("bg0021")], finished=None)),
           n_reads(lambda: fin("p1", [BGR("bg0020")]), lambda: fin("p2", [MON("mon020")])),
           n_reads(lambda: fin("f1"), lambda: fin("f2"), lambda: fin("f3")),
           n_reads(lambda: fin("p1", [BGR("bg0020")]), lambda: fin("f1"), lambda: fin("u1", finished=None)),
           n_reads(lambda: fin("f1", age=int(TIE.QUIET_CAP_S) + 60), lambda: fin("p1", [BGR("bg0020")], age=int(TIE.QUIET_CAP_S) + 60)),
           n_reads(lambda: fin("i1", [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None)),
           n_reads(lambda: fin("i1", [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None), lambda: fin("f1")))
    for f_ in sub3.glob("agent-*"): f_.unlink()
    fin("p1", [BGR("bg0020")]); fin("p2", [MON("mon020")]); fin("f1"); fin("f2"); fin("f3")
finally: TIE.read_parent = real_rp
check("25 the session's transcript is read once for a call (never once for each subagent), and only when a finished subagent (parked or not) or an interrupted one needs it: not for no subagent, for subagents with no flag, or for ones past the 6-hour cap",
      n25 == (0, 0, 1, 1, 1, 0, 1, 1), n25)
par3.unlink(); par3.mkdir()                                                                  # a transcript that cannot be read as a file
try:
    got25e = run3()
    check("25 a session transcript that cannot be read: a finished subagent with nothing pending is not running, one parked on a task still is, and nothing raises (unreadable is no reason to list a subagent unreadable)",
          sorted(got25e) == ["p1", "p2"] and not any(x.get("unreadable") for x in got25e.values()), sorted(got25e))
finally: par3.rmdir()
par3.write_text("{not json\n" + '{"type":"user","timestamp":"nope","x":"resumedAgentId\\":\\"f1"}\n' + "\x00\xff" + "\n")
check("25 …nor a transcript of torn lines, a resume with no readable time, or bytes that are no text", sorted(run3()) == ["p1", "p2"], sorted(run3()))
check("25 …a finished subagent whose meta cannot be read is still listed running with no words (unreadable, as before)", (lambda: (fin("bad1"), (sub3 / "agent-bad1.meta.json").write_text("{not json"), "bad1" in run3() and run3()["bad1"].get("unreadable") is True)[2])(), None)
parent({"type": "assistant", "message": {"role": "assistant", "content": "x"}})
# a parked subagent is tied like any other
fin("tie1", [BGR("bg0030")], desc=f"Review {BID(1)}", brief="nothing")
check("25 a parked subagent ties to an item by its description as any other", TIE.tied(list(run3().values()), BID(1)) and not TIE.tied([run3()["tie1"]], BID(2)), None)
# ---- the second round: what the session's transcript says, a start that is only quoted, a Monitor's lifetime, a subagent that was interrupted, a resume that is only quoted
ASSIST = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}
def wipe3():
    for f_ in sub3.glob("agent-*"): f_.unlink()
check("25 the values the rules rest on are pinned (a window, a cap, a slack or a bound changed in the code is seen here)",
      (TIE.RUNNING_S, TIE.QUIET_CAP_S, TIE.PARKED_S, TIE.SKEW_S, TIE.RESUME_SLACK_S, TIE.TAIL_BYTES, TIE.TASK_TAIL_BYTES, TIE.LAST_ROW_BYTES)
      == (5400.0, 21600.0, 5400.0, 300.0, 1.0, 8 * 1024 * 1024, 32 * 1024 * 1024, 16 * 1024), (TIE.RUNNING_S, TIE.QUIET_CAP_S, TIE.PARKED_S, TIE.SKEW_S, TIE.RESUME_SLACK_S, TIE.TAIL_BYTES, TIE.TASK_TAIL_BYTES, TIE.LAST_ROW_BYTES))
wipe3(); parent(ASSIST)
fin("w89", [BGR("bgw089")], age=89 * 60); fin("w91", [BGR("bgw091")], age=91 * 60)
got = run3()
check("25 …the parked window is 90 minutes: a task pending in a transcript written 89 minutes ago is running, one 91 minutes ago is not", "w89" in got and "w91" not in got, sorted(got))

# 1. the end notice that reached only the session's transcript
wipe3()
def PQ(tid, status="completed", event=None, op="enqueue"):
    """a notice as the session's own transcript keeps it: a queue record"""
    body = f"<task-notification>\n<task-id>{tid}</task-id>\n<tool-use-id>x</tool-use-id>\n<output-file>/x/{tid}.output</output-file>\n" + (f"<status>{status}</status>\n" if status else "") + f"<summary>done</summary>\n" + (f"<event>{event}</event>\n" if event else "") + "</task-notification>"
    return {"type": "queue-operation", "operation": op, "timestamp": iso(now0 - 100), "sessionId": "s", "content": body}
PU = lambda tid, status="failed": {"type": "user", "timestamp": iso(now0 - 100), "message": {"role": "user", "content": f"[SYSTEM NOTIFICATION] <task-notification>\n<task-id>{tid}</task-id>\n<status>{status}</status>\n</task-notification>"}}
for i_, mk_ in enumerate((BGR, BGR, MON, BGR, BGR, BGR, MON, MON, BGR, BGR, BGR, BGR, BGT), 1): fin(f"n{i_}", [mk_(f"pn{i_:04d}")])
fin("n6", [BGR("pn0006"), BGR("pn0106")])
parent(ASSIST,
       PQ("pn0001"),                                                                                   # n1: a queue record with a status: ended
       PU("pn0002"),                                                                                   # n2: a user message with a status: ended
       PQ("pn0003", None, "[Monitor expired after 10m with no events delivered. Re-arm it if you still need the watch.]"),    # n3: a Monitor's expiry event: ended
       NOTE("pn0004"),                                                                                 # n4: an attachment: ended
       PQ("pn9999"),                                                                                   # n5: a notice of another task ends nothing
       PQ("pn0006"),                                                                                   # n6: two tasks, one ended: still parked on the other
       PQ("pn0007", None, "one more line"),                                                            # n7: a Monitor's per-event notice ends nothing
       PQ("pn0008", None, "Monitor ended: the source closed"),                                         # n8: ended
       {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "<task-notification>\n<task-id>pn0009</task-id>\n<status>completed</status>\n</task-notification>"}]}},      # n9: quoted in a command's output: nothing
       {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "<task-id>pn0010</task-id><status>completed</status>"}]}},      # n10: an assistant record: nothing
       {"type": "api-request-blob", "message": {"content": [{"type": "text", "text": "<task-notification><task-id>pn0011</task-id><status>completed</status></task-notification>"}]}},      # n11: a request's copy: nothing
       PQ("pn0013", op="remove"))                                                                      # n13: a removed notice is one too
got = run3()
check("25 a finished subagent's task whose end notice only the SESSION's transcript holds (a queue record, a user message, an attachment, a Monitor's expiry or end event) is ended: the subagent is not running",
      not any(k in got for k in ("n1", "n2", "n3", "n4", "n8", "n13")), sorted(got))
check("25 …a notice of another task, a Monitor's per-event notice, a task of two of which one ended, and a notice quoted in a tool result, an assistant record or a request's copy of the conversation end nothing: still running",
      {"n5", "n6", "n7", "n9", "n10", "n11"} <= set(got), sorted(got))
check("25 read_parent: the ids whose end the session was told, and the resumes", TIE.read_parent(par3)[1] == {"pn0001", "pn0002", "pn0003", "pn0004", "pn9999", "pn0006", "pn0008", "pn0013"} and TIE.read_parent(par3 / "missing") == ({}, set()), TIE.read_parent(par3)[1])
parent(PQ("pn0012"), filler=64 * 1024); fin("n12", [BGR("pn0012")]); saved_tail = TIE.TAIL_BYTES
n12_all = "n12" in run3(); TIE.TAIL_BYTES = 4096
try: n12_cut = "n12" in run3()
finally: TIE.TAIL_BYTES = saved_tail
check("25 …only the last TAIL_BYTES of the session's transcript are read for a notice too: one further back is not seen", not n12_all and n12_cut, (n12_all, n12_cut))
par3.unlink(); par3.mkdir()
try: n_unread = {k for k in run3() if k.startswith("n")}
finally: par3.rmdir()
check("25 …a session transcript that cannot be read ends nothing (every task stays pending), and raises nothing", len(n_unread) == 13, sorted(n_unread))
wipe3(); parent(ASSIST)
fin("sub1", [BGR("bgs001")]); (sub3 / "agent-sub1.jsonl").write_text((sub3 / "agent-sub1.jsonl").read_text() + json.dumps(PQ("bgs001")) + "\n")
check("25 a notice in the subagent's own transcript (a queue record too) still ends its task", "sub1" not in run3(), None)

# 2. a start that is only quoted
wipe3(); parent(ASSIST)
UT = lambda c: {"type": "user", "message": {"role": "user", "content": c}}
fin("q1", [_res("12\nCommand running in background with ID: qq0001. Output is being written to: /x")])      # a command printed it after another line: quoted
fin("q2", [UT("a message: Monitor started (task qq0002, expires in 30m unless the source ends first).")])
fin("q3", [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Command running in background with ID: qq0003."}]}}])
fin("q4", [{"type": "api-request-blob", "message": {"content": [{"type": "tool_result", "content": "Command running in background with ID: qq0004."}]}}])
fin("q5", [BGT("qq0005")])                                                                                  # the real form after a timeout
fin("q6", [_res([{"type": "text", "text": "Command running in background with ID: qq0006. Output is being written to: /x"}])])      # a list of text blocks
fin("q7", [_res("see Command was moved to the background (ID: qq0007) in the log")])
fin("q8", [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "echo Command running in background with ID: qq0008"}}]}}])
got = run3()
check("25 a task starts only with a tool result that OPENS with the start text (running in the background, moved there, moved there after its timeout, a Monitor started): text that is only quoted in a result, a message, a request or a command starts none",
      {"q5", "q6"} <= set(got) and not any(k in got for k in ("q1", "q2", "q3", "q4", "q7", "q8")), sorted(got))
check("25 pending_tasks reads the real start forms", TIE.pending_tasks(sub3 / "agent-q5.jsonl") == {"qq0005"} and TIE.pending_tasks(sub3 / "agent-q6.jsonl") == {"qq0006"} and TIE.pending_tasks(sub3 / "agent-q1.jsonl") == set(), None)
# a backgrounded MCP tool call (Claude Code 2.1.332: three wordings) is a task that waits too; a Bash moved so a message can reach the session already was
fin("m1", [_res('MCP tool "svc__run" was moved to the background as task mcp001 so that a message that arrived while it was running can reach you; it was not interrupted and keeps running. You can keep working in the meantime.')])
fin("m2", [_res('MCP tool "svc__run" is still running after 120s. It was moved to the background as task mcp002 and keeps running. You can keep working in the meantime.')])
fin("m3", [_res('MCP tool "svc__run" started server-side task srv9. It was moved to the background as task mcp003 and keeps running on the server; you can keep working in the meantime.')])
fin("m4", [_res("Command was moved to the background (ID: mcp004) so that a message that arrived while it was running can reach you; it was not interrupted. Output is being written to: /x/mcp004.output.")])
fin("m5", [_res('see MCP tool "svc__run" was moved to the background as task mcp005 in the log')])
check("25 pending_tasks reads a backgrounded MCP tool call in its three wordings, and a Bash moved so a message can reach the session; a quote of one is none",
      [TIE.pending_tasks(sub3 / f"agent-m{i}.jsonl") for i in range(1, 6)] == [{"mcp001"}, {"mcp002"}, {"mcp003"}, {"mcp004"}, set()], [TIE.pending_tasks(sub3 / f"agent-m{i}.jsonl") for i in range(1, 6)])
saved_tt = TIE.TASK_TAIL_BYTES; fin("tb1", [BGR("tb0001"), {"type": "assistant", "x": "y" * 70000}]); tb_all = "tb1" in run3(); TIE.TASK_TAIL_BYTES = 4096
try: tb_cut = "tb1" in run3()
finally: TIE.TASK_TAIL_BYTES = saved_tt
check("25 …only the last TASK_TAIL_BYTES of the subagent's transcript are read: a start further back is not seen", tb_all and not tb_cut, (tb_all, tb_cut))

# 2b. the record beside a command's result: what a command printed comes before the sentence, and the row carries the task's id (`toolUseResult.backgroundTaskId`)
def CMD(text, tid=None, **extra): return {**_res(text), "toolUseResult": {"stdout": "step 1", "stderr": "", "interrupted": False, **({} if tid is None else {"backgroundTaskId": tid}), **extra}}
CAP = lambda tid: f"Command was moved to the background (ID: {tid}) after running for 180s. Output is being written to: /x/{tid}.output."
LATE = lambda tid: f"Command did not complete within its 120s timeout and was moved to the background (ID: {tid}). Output is being written to: /x/{tid}.output."
MSG = lambda tid: f"Command was moved to the background (ID: {tid}) so that a message that arrived while it was running can reach you; it was not interrupted. Output is being written to: /x/{tid}.output."
HAND = lambda tid: f"Command was manually backgrounded by user with ID: {tid}. Output is being written to: /x/{tid}.output."
wipe3(); parent(ASSIST)
fin("r1", [CMD("step 1\n" + CAP("rc0001"), "rc0001", subagentCapApplied=True)])
fin("r2", [CMD("step 1\nstep 2\n" + LATE("rc0002"), "rc0002", timedOutAfterMs=120000)])
fin("r3", [CMD("step 1\n" + MSG("rc0003"), "rc0003", backgroundedToDeliverMessage=True)])
fin("r4", [CMD("step 1\n" + HAND("rc0004"), "rc0004", backgroundedByUser=True)])
fin("r5", [CMD("a notice in words this module does not know", "rc0005")])
fin("h1", [_res(HAND("rc0006"))])                                                                           # no record beside it: the sentence says it
fin("h2", [{**MON("rc0007"), "toolUseResult": {"taskId": "rc0007", "timeoutMs": 1800000, "persistent": False}}])      # a Monitor's record is no command's: its text is read
got = run3()
check("25 a command's record that names a background task starts it, wherever the sentence stands in the result (after what the command printed, in any wording)",
      {"r1", "r2", "r3", "r4", "r5"} <= set(got) and [TIE.pending_tasks(sub3 / f"agent-r{i}.jsonl") for i in range(1, 6)] == [{f"rc000{i}"} for i in range(1, 6)], sorted(got))
check("25 …a command moved to the background by hand is read from its sentence too, and a Monitor whose row carries its own record still starts", {"h1", "h2"} <= set(got), sorted(got))
wipe3(); parent(ASSIST)
fin("w1", [CMD(CAP("wq0001"))])                                                                             # a `cat` of a log: the result opens with the sentence, the command's record names no task
fin("w2", [CMD(HAND("wq0002") + "\n3 lines")])
fin("w3", [CMD("step 1\n" + CAP("wq0003"))])
fin("w4", [CMD(CAP("wq0004"), None, backgroundTaskId="")]); fin("w5", [CMD(CAP("wq0005"), None, backgroundTaskId=None)]); fin("w6", [CMD(CAP("wq0006"), None, backgroundTaskId=["wq0006"])])
fin("w7", [{"type": "assistant", "message": {"role": "assistant", "content": "x"}, "toolUseResult": {"stdout": "", "backgroundTaskId": "wq0007"}}])
fin("w8", [{"type": "api-request-blob", **{k: v for k, v in CMD("x", "wq0008").items() if k != "type"}}])
got = run3()
check("25 …a command that only quotes such a sentence (its record names no task, wherever the sentence stands), a task id that is no text, and a record on a row that is no tool result start nothing", not got, sorted(got))
wipe3()
fin("e1", [CMD("step 1\n" + CAP("rc0101"), "rc0101"), NOTE("rc0101")]); fin("e2", [CMD("step 1\n" + CAP("rc0102"), "rc0102"), STOP("rc0102")]); fin("e3", [CMD("step 1\n" + CAP("rc0103"), "rc0103")])
fin("e4", [CMD("step 1\n" + CAP("rc0104"), "rc0104"), CMD("step 1\n" + CAP("rc0104"))])                     # a later command that prints the sentence again does not start it twice or end it
parent(ASSIST, PQ("rc0103"))                                                   # e3: the notice only the session was handed
got = run3()
check("25 …a task found by the record ends as any other: its notice in the subagent's or the session's transcript, or a TaskStop", set(got) == {"e4"}, sorted(got))

# 3. a Monitor's lifetime
wipe3(); parent(ASSIST)
def mon_case(aid, life, start_ago, at_ago=None, **kw):
    fin(aid, [MON(f"mt{aid}", life, t=now0 - start_ago)], age=at_ago if at_ago is not None else start_ago, **kw)
mon_case("m1", "expires in 10m unless the source ends first", 80 * 60, 79 * 60)           # a 10-minute Monitor, read 80 minutes later, the transcript not written since
mon_case("m2", "expires in 30m unless the source ends first", 20 * 60, 19 * 60)
mon_case("m3", "expires in 30m unless the source ends first", 40 * 60)
mon_case("m4", "expires in 10m unless the source ends first", 601, 600)                    # its end is a second less than the slack ahead: still counts
mon_case("m5", "expires in 10m unless the source ends first", 602)                         # past it
mon_case("m6", "expires in 10m unless the source ends first", 3000, 2300)                  # written after its end: the window alone bounds it
mon_case("m7", "expires in 10m unless the source ends first", 3000, 3000 - 600 - 0.25 - 0.5)      # written half a second after its end: not since (the slack)
mon_case("m8", "expires in 10m unless the source ends first", 3000, 3000 - 600 - 0.25 - 1.5)      # written a second and a half after its end: since
fin("m9", [MON("mtm9", None, t=now0 - 80 * 60)], age=79 * 60)                              # a Monitor that gives no lifetime: the window only
fin("m10", [MON("mtm10", "expires in 10m unless the source ends first")], age=79 * 60)      # a record with no time: no lifetime applies
fin("m11", [BGR("mtm11", t=now0 - 80 * 60)], age=79 * 60)                                  # a background Bash has no lifetime
mon_case("m12", "expires in 15m 30s unless the source ends first", 20 * 60, 19 * 60)      # 930 s: ended
mon_case("m13", "expires in 15m 30s unless the source ends first", 10 * 60, 9 * 60)       # alive
mon_case("m14", "expires in 45s unless the source ends first", 5 * 60)                     # ended
mon_case("m15", "expires in 1h unless the source ends first", 30 * 60, 29 * 60)           # alive
mon_case("m16", "expires in 1h 5m unless the source ends first", 70 * 60, 69 * 60)       # 65 minutes: ended
mon_case("m17", "timeout 900000ms", 20 * 60, 19 * 60)                                      # the other wording: ended
mon_case("m18", "timeout 900000ms", 10 * 60, 9 * 60)
mon_case("m20", "expires in 15m 30s unless the source ends first", 915, 900)                  # 930 s, 915 s gone: alive (the seconds count)
mon_case("m21", "expires in 45s unless the source ends first", 30)                         # alive
mon_case("m19", "expires in 10m unless the source ends first", 80 * 60, 79 * 60, finished=None)      # no flag: this reads the finished ones only
got = run3()
check("25 a Monitor whose start plus its lifetime is past, with no write since, has ended: a 10-minute Monitor read 80 minutes later is not running, a 30-minute one 40 minutes later neither, one still within its lifetime is",
      "m1" not in got and "m3" not in got and "m2" in got, sorted(got))
check("25 …the slack is a second: a Monitor whose end is less than a second ahead of the clock counts, one past it does not; a write after its end (more than the slack) leaves the window alone to bound it, one within the slack does not",
      "m4" in got and "m5" not in got and "m6" in got and "m7" not in got and "m8" in got, sorted(got))
check("25 …a Monitor with no lifetime, a start record with no time and a background Bash have none to end: the 90-minute window alone bounds them", {"m9", "m10", "m11"} <= set(got), sorted(got))
check("25 …the lifetime is read in every wording the start text takes (`15m 30s`, `45s`, `1h`, `1h 5m`, `timeout 900000ms`)",
      "m12" not in got and "m13" in got and "m14" not in got and "m15" in got and "m20" in got and "m21" in got and "m16" not in got and "m17" not in got and "m18" in got, sorted(got))
check("25 …a subagent with no flag is untouched by a Monitor's lifetime", "m19" in got, sorted(got))
check("25 pending_tasks: the lifetime applies only when it is given the clock", TIE.pending_tasks(sub3 / "agent-m1.jsonl") == {"mtm1"} and TIE.pending_tasks(sub3 / "agent-m1.jsonl", now0) == set() and TIE.pending_tasks(sub3 / "agent-m2.jsonl", now0) == {"mtm2"}, None)

# 4. a subagent with no flag whose last row is an interruption
wipe3()
INT = lambda txt="[Request interrupted by user]": {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": txt}]}}
fin("i1", [ASSIST, INT()], finished=None); fin("i2", [ASSIST, INT("[Request interrupted by user for tool use]")], finished=None)
fin("i3", [INT(), ASSIST], finished=None)                                                   # not the last row
fin("i4", [ASSIST, INT("do not [Request interrupted by user] again")], finished=None)      # a row that says more
fin("i5", [ASSIST, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}], finished=None)
fin("i6", [INT()], finished=None); fin("i7", [INT()], finished=None); fin("i12", [INT()], finished=None); fin("i13", [INT()], finished=None)
fin("i8", [INT()], finished=None, age=100 * 60); fin("i9", [ASSIST], finished=None, age=100 * 60)
fin("i11", [ASSIST, UT("[Request interrupted by user]")], finished=None)                   # the text as a string
fin("i14", [ASSIST, INT()], finished=True, meta_age=600)                                    # flagged finished: the rule of a finished one
parent(ASSIST, resume_rec("i6", now0 - 30), resume_rec("i7", now0 - 120), resume_rec("i12", now0 - 61), resume_rec("i13", now0 - 63))
got = run3()
check("25 a subagent with no flag whose last row is `[Request interrupted by user]` (or `... for tool use]`) is dead, not quiet: it is not running, even written a minute ago; one whose interruption is not its last row, or that says more, or is an assistant's, is running as ever",
      not any(k in got for k in ("i1", "i2", "i8", "i11")) and {"i3", "i4", "i5", "i9"} <= set(got), sorted(got))
check("25 …unless the session's transcript holds a resume of it newer than its last row (a second of slack): then it is running; an older resume is none", "i6" in got and "i7" not in got and "i12" in got and "i13" not in got, sorted(got))
check("25 …a plain unflagged one 100 minutes old stays running but quiet; a finished one that was interrupted follows the rule of the finished", got["i9"].get("quiet") is True and "i14" not in got, sorted(got))
check("25 interrupted: the last row only, and nothing raises", TIE.interrupted(sub3 / "agent-i1.jsonl") and TIE.interrupted(sub3 / "agent-i2.jsonl") and TIE.interrupted(sub3 / "agent-i11.jsonl") and not any(TIE.interrupted(sub3 / f"agent-{k}.jsonl") for k in ("i3", "i4", "i5", "i9")) and not TIE.interrupted(sub3 / "agent-none.jsonl"), None)
saved_lr = TIE.LAST_ROW_BYTES; TIE.LAST_ROW_BYTES = 40
try: cut_i = TIE.interrupted(sub3 / "agent-i1.jsonl")
finally: TIE.LAST_ROW_BYTES = saved_lr
check("25 …a last row longer than LAST_ROW_BYTES is none", cut_i is False, cut_i)

# 5. a resume that is only quoted
wipe3()
for k_ in ("rq1", "rq2", "rq3", "rq4", "rq5", "rq6", "rq7", "rq8"): fin(k_, meta_age=600)
RQ = lambda r: {**r, "timestamp": iso(now0 - 300)}
parent(ASSIST,
       RQ({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": json.dumps({"resumedAgentId": "rq1"})}]}}),                       # quoted in a tool result: no top-level key
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"result": {"resumedAgentId": "rq2"}}}),                                          # not a top-level key
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": "resumedAgentId\": \"rq3\""}),                                                    # a string
       RQ({"type": "api-request-blob", "message": {"content": [{"type": "text", "text": json.dumps({"resumedAgentId": "rq4"})}]}, "toolUseResult": {"resumedAgentId": "rq4"}}),   # not a user record
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": "rq5", "revivedAgentId": "rq5", "success": True}}),         # both keys, one id: the real record
       RQ({"type": "user", "message": {"role": "user", "content": "typed: \"resumedAgentId\": \"rq6\""}}),                                                                   # a message that quotes it
       RQ({"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": 7, "revivedAgentId": ""}}),
       {"type": "user", "message": {"role": "user", "content": "x"}, "toolUseResult": {"resumedAgentId": "rq8"}})                                                                  # a resume with no time says nothing and spoils no other
got = run3()
check("25 a resume is the key `resumedAgentId` (or `revivedAgentId`) at the top level of a user record's `toolUseResult`: one quoted inside a tool result, nested deeper, in a string, in a request's copy or in a typed message is none; both keys of one record count once",
      "rq5" in got and not any(k in got for k in ("rq1", "rq2", "rq3", "rq4", "rq6", "rq7", "rq8")), sorted(got))
check("25 …resumes: both keys on the one record, the time of the record", set(TIE.resumes(par3)) == {"rq5"} and abs(TIE.resumes(par3)["rq5"] - (now0 - 300 + 0.25)) < 0.01, TIE.resumes(par3))
wipe3(); parent(ASSIST)
for f_ in sub3.glob("agent-*"): f_.unlink()


# 6. the review's follow-ups: a record is cut at a newline only, a Monitor that lives hours, the parked window to the second
wipe3()
SEP = "\u2028"      # JSON leaves it raw inside a string (json.dumps with ensure_ascii off, as Claude Code writes it); `str.splitlines` would cut a record there
def fin_raw(aid, extra=(), age=60, meta_age=600):
    mp, tp = sub3 / f"agent-{aid}.meta.json", sub3 / f"agent-{aid}.jsonl"
    mp.write_text(json.dumps({"agentType": "general-purpose", "description": f"Review {aid}", "finished": True}))
    tp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [{"type": "user", "message": {"role": "user", "content": f"Review the change of {aid}"}}, *extra]) + "\n", encoding="utf-8")
    os.utime(tp, (now0 - age, now0 - age)); os.utime(mp, (now0 - meta_age, now0 - meta_age))
fin_raw("u1", [_res(f"Command running in background with ID: bgu001. Output is being written to: /x/bgu001.output.{SEP}You will be notified when it completes.")])
fin_raw("u2", [BGR("bgu002")])
fin_raw("u3", [BGR("bgu003")])
par3.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [ASSIST,
      {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(now0 - 100), "content": f"<task-notification>\n<task-id>bgu002</task-id>\n<status>completed</status>\n<summary>done{SEP}at last</summary>\n</task-notification>"},
      {"type": "user", "timestamp": iso(now0 - 100), "message": {"role": "user", "content": f"a message{SEP}that mentions <task-id>bgu003</task-id> and no status"}}]) + "\n", encoding="utf-8")
got = run3()
check("25 a transcript record is cut at a newline and nowhere else: a task start whose result holds a raw U+2028 is still seen (pending_tasks, and the subagent parked on it runs), and an end notice that holds one still ends its task (read_parent), where a cut record is torn and says nothing",
      TIE.pending_tasks(sub3 / "agent-u1.jsonl") == {"bgu001"} and TIE.read_parent(par3)[1] == {"bgu002"} and "u1" in got and "u2" not in got and "u3" in got, (TIE.pending_tasks(sub3 / "agent-u1.jsonl"), TIE.read_parent(par3)[1], sorted(got)))
wipe3(); parent(ASSIST)
mon_case("h1", "expires in 1h unless the source ends first", 61 * 60)                         # an hour-only lifetime: 61 minutes on it has ended
mon_case("h2", "expires in 1h unless the source ends first", 59 * 60)                         # 59 minutes on it is alive
mon_case("h3", "expires in 1h 30s unless the source ends first", 3600 + 30 + 2)                # hours and seconds: ended
mon_case("h4", "expires in 1h 30s unless the source ends first", 3600 + 25)                    # …alive
mon_case("h5", "expires in 2h unless the source ends first", 80 * 60)                          # a 2-hour Monitor 80 minutes on is alive
mon_case("h6", "expires in 1h unless the source ends first", 3600 + 1, finished=None)          # no flag: not this rule's
got = run3()
check("25 a Monitor whose lifetime is in hours: `expires in 1h` has ended 61 minutes on and lives at 59, `1h 30s` counts its seconds, `2h` lives at 80 minutes, a subagent with no flag is not read by it",
      "h1" not in got and "h2" in got and "h3" not in got and "h4" in got and "h5" in got and "h6" in got and TIE._life("Monitor started (task x, expires in 2h unless the source ends first)") == 7200.0, sorted(got))
wipe3(); parent(ASSIST)
fin("b0", [BGR("bgb000")], age=int(TIE.PARKED_S)); fin("b1", [BGR("bgb001")], age=int(TIE.PARKED_S) + 1); fin("b2", [BGR("bgb002")], age=int(TIE.PARKED_S) - 1)
got = run3()
check("25 the parked window to the second: a pending task in a transcript written exactly 90 minutes ago (5400 seconds) still counts, one second more does not, one second less does (a task that never reported is believed for that long and no longer)", "b0" in got and "b1" not in got and "b2" in got, sorted(got))


print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
