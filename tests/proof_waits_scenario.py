"""Scenario test for the proof-waits stage of the daily audit (audit_checks.proof_wait_findings, audit_run.proof_stage): an open item held for a real event closes once the fix's tests passed and it is live,
otherwise its mover is told to stage the event now; a wait that cannot be staged keeps its basis named and is left alone. Fixture items, a recording sender, a fake clock, a fake model runner that must never
be called; no live store, no network, no server.

  1  the candidates: an event wait for a recycle, a fleet op or a job run, and a hold or park whose own words say it is kept open to see the fix happen for real; not a wait on a pull request's merge or release,
     not alive work, not a plain park, not a closed item
  2  the verdict: an item with a release notice (`released_told`) gets "close it" with the live pull request named, any other the "stage the event now" finding; a merge-only or dead stamp is no release
  3  left alone with the basis named: a real-world date (wait basis), news only the owner relays, an anchor event, another item's close, needs external, a release still to come (a step with its proof), a post-wake
     mover who is the owner; none of them is a finding, each is on the record with its basis
  4  the run: the stage runs after the model checks and before the pages stage, makes no model call, writes nothing to any item (the audit closes nothing), sends the finding to the mover once (a second run
     with the item unwritten sends nothing, a write to the item brings it back) and never to the owner
  5  the cap: more fresh findings than PROOF_MAX are not sent, are counted in `capped` and go out on the next run, the ones sent before taking no place
  6  a stage that fails is a stage not made: the run finishes, the record says so
  7  the dry run lists the findings and the items left alone, sends nothing and writes no record

  8  review follow-ups: a held item stored as doing is left alone for a real-world date as a parked one is; the words that must and must not count; the fix text never says to queue a recycle or fleet op
     and names the owner's go as the basis; a prose wait for a pull request to merge or be released is the release path's; one unreadable item is skipped and counted

    tests/run-suite proof_waits        → exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time
BID_00 = 9300
BID_01 = 9301
BID_02 = 9302
BID_03 = 9303
BID_04 = 9304
BID_05 = 9305
BID_06 = 9306
BID_07 = 9307
BID_08 = 9308
BID_09 = 9309
BID_10 = 9310
BID_11 = 9311
BID_14 = 9314
BID_15 = 9315
BID_16 = 9316
BID_21 = 9321
BID_22 = 9322
BID_23 = 9323

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="proofwait-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_run as AR; from stackshot.audit import audit_checks as AC; from stackshot.waits import event_waits as EW
_cfg.CFG["audit"]["pattern_review"] = "off"      # this suite holds the run to its other stages: the pattern review has its own suite (pattern_review_scenario)

H = 3600; DAY = 86400; now = time.time()
ZONE_OFFSET = 4 * H                                    # the instance timezone (the config's `timezone` above): UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900     # not within 10 minutes of a local midnight: the record times a few seconds after `now` stay on one date
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET)); OWNER = "00000000-0000-4000-8000-000000000001"
local_str = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d %H:%M")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

# ---- fixtures
AGENT = "home-agent"; WAKE = local_str(now + 3 * DAY)
FIXTURE_NS = [*range(6, 16), 18, 20, 30, 40, 50, 51, 52, *range(55, 61), 62, *range(100, 113)]
def item(i, status="open", **meta):
    if i > 5: i = 9300 + FIXTURE_NS.index(i)                       # ids 1..5 stay, every other fixture number is the next counter from 9300
    at = now - 2 * H
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": at, "state_updated": at, "confirmed": at,
         "written_at": at, "written_by": AGENT, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    return f"a{i}", d
def evwait(i, event="recycle", **meta): return item(i, **{"wait_kind": "event", "wait_event": event, "wake": WAKE, "post_wake_mover": AGENT, "needs": [], "next": f"{AGENT}: confirm it after the event", **meta})
def park(i, nxt=f"{AGENT}: keep it open to see it in real life", **meta): return item(i, **{"state": "parked", "wake": WAKE, "post_wake_mover": AGENT, "needs": [], "next": nxt, **meta})
def build(*pairs): return dict(pairs)
ROLES = {AGENT: {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent, pushed = [], []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def push(to, text): pushed.append((to, text)); return True, "delivered"
ORDER = []
def pages(run, deadline): ORDER.append("pages"); return {"enabled": False, "mode": "", "counts": {}}
def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=kw.pop("deliver", deliver), push=push,
                             sessions=lambda: None, pages=kw.pop("pages", pages), **kw)
RUBRIC_TEXT = pathlib.Path(STACK, "audit_rubric.txt").read_text(encoding="utf-8").replace("{owner}", "Oliver")
RUNNER_CALLS = []
def runner(message): RUNNER_CALLS.append(message); raise AssertionError("the proof-waits stage must make no model call")
def go(items, **kw):
    sent.clear(); pushed.clear(); RUNNER_CALLS.clear(); ORDER.clear()
    e = env(); e.runner = runner
    return AR.run(now=kw.pop("now", now), items=items, anchors={}, env=e, rubric=RUBRIC_TEXT, **kw)
def rec_clear():
    for p in (T / "state/audit").glob("run-*.json"): p.unlink()
def pw_ids(rec): return sorted(f["id"] for f in rec["findings"] if f["category"] == "proof-wait")
def find(findings, sid): return [f for f in findings if f["id"] == sid]
def left_ids(rec): return {x["id"]: x["basis"] for x in rec["proof_waits"]["left"]}

# ---- 1 + 2 + 3. the rule on fixtures
BASIS = {"text": "the vendor's visit on 2031-04-17", "wake": WAKE, "at": now - H}
items = build(
    evwait(1, "recycle", released_told=["o/r#5"]),                                        # event wait, fix live → close it
    evwait(2, "fleet_op many"),                                                           # event wait, nothing live → stage it
    evwait(3, "job_run nightly"),                                                         # a job run can be staged too
    park(4),                                                                              # a park kept open to see it in real life → stage it
    park(5, released_told=["merged o/r#6", "dead o/r#7"]),                                # a merge-only and a dead stamp are no release
    park(10, released_told=["o/r#8"], expected_reason="to see whether the first real run is clean"),   # words in the expected reason → close it
    evwait(9, "pr_released o/r#9"),                                                       # the release path's wait: no candidate
    evwait(20, "pr_merged o/r#9"),
    item(8, state="doing", needs=[AGENT], next=f"{AGENT}: watch it in real life"),         # alive work: no candidate
    park(60, nxt=f"{AGENT}: look again on the date"),                                       # a plain park: no words, no candidate
    item(50, status="completed", state="parked", wake=WAKE, next=f"{AGENT}: see it in real life", outcome="done"),
    park(11, wait_basis=BASIS),                                                           # a real-world date: left alone, basis named
    item(59, state="outside", needs=["external"], party="the vendor", next=f"{AGENT}: see it in real life"),     # an outside party
    item(7, state="outside", wait_kind="relay", ask_by=local_str(now + 3 * DAY)[:10], post_wake_mover=AGENT, needs=[], next=f"{AGENT}: see it in real life"),    # news only the owner relays
    item(52, state="blocked", after=["board#2"], post_wake_mover=AGENT, needs=[], next=f"{AGENT}: see it in real life"),   # another item's close
    park(62, post_wake_mover="Oliver"),                                                   # the post-wake mover is the owner
    item(51, state="outside", wait_kind="anchor", wait_anchor="https://github.com/o/r/issues/16", wait_event="a reply", wake=WAKE, post_wake_mover=AGENT, needs=[], next=f"{AGENT}: see it in real life"),   # an anchor event
)
fs, left, read, skipped0 = AC.proof_wait_findings(items, {}, now, env())
got = {f["id"]: f for f in fs}
check("1 candidates: the event waits for a recycle, a fleet op and a job run and the parks whose words say 'see it in real life' are findings", {"board#1", "board#2", "board#3", "board#4", "board#5", f"board#{BID_04}"} <= set(got), sorted(got))
check("1 candidates: a wait on a pull request's merge or release, alive work, a plain park and a closed item are none", not ({f"board#{BID_03}", f"board#{BID_11}", f"board#{BID_02}", f"board#{BID_22}", f"board#{BID_14}"} & (set(got) | {x["id"] for x in left})), (sorted(got), left))
check("2 verdict: an item with a release notice is told to close it, the live pull request named, and the event waited for", "o/r#5" in got["board#1"]["detail"] and "recycle" in got["board#1"]["detail"] and got["board#1"]["fix"] == AC.FIX["proof-wait"] and "live" in got["board#1"]["detail"], got["board#1"])
check("2 verdict: the words in the expected reason count, the release notice again", "o/r#8" in got[f"board#{BID_04}"]["detail"] and got[f"board#{BID_04}"]["fix"] == AC.FIX["proof-wait"], got[f"board#{BID_04}"])
check("2 verdict: no release notice → stage it now (a downgrade, a probe, a dry run), and write the basis if it cannot be staged", all(got[f"board#{n}"]["fix"] == AC.PROOF_STAGE_FIX for n in (2, 3, 4)) and "stage the event now" in AC.PROOF_STAGE_FIX and "basis" in AC.PROOF_STAGE_FIX and "downgrade" in AC.PROOF_STAGE_FIX, [got[f"board#{n}"]["fix"] for n in (2, 3, 4)])
check("2 verdict: a merge-only or dead stamp is no release → stage it", got["board#5"]["fix"] == AC.PROOF_STAGE_FIX and "o/r#6" not in got["board#5"]["detail"], got["board#5"])
check("2 verdict: every finding is the mover's, in code, in the category's shape", all(f["mover"] == AGENT and f["owner"] == AGENT and f["source"] == "code" and f["project"] == "projects/alpha" and f["detail"] and f["fix"] for f in fs), fs)
lf = {x["id"]: x["basis"] for x in left}
check("3 left alone: a real-world date, an outside party, news only the owner relays, another item's close, an anchor event: each names its basis",
      "real-world date" in lf.get(f"board#{BID_05}", "") and "vendor" in lf[f"board#{BID_05}"] and "outside party" in lf.get(f"board#{BID_21}", "") and "Oliver relays" in lf.get(f"board#{BID_01}", "") and "item's close" in lf.get(f"board#{BID_16}", "") and "anchor" in lf.get(f"board#{BID_15}", ""), lf)
check("3 left alone: the owner as the post-wake mover is left alone", "not a session's" in lf.get(f"board#{BID_23}", ""), lf)
check("3 left alone: none of them is a finding", not ({f"board#{BID_05}", f"board#{BID_21}", f"board#{BID_01}", f"board#{BID_16}", f"board#{BID_23}", f"board#{BID_15}"} & set(got)), sorted(got))
check("3 candidates read counts the findings and the items left alone", read == len(fs) + len(left), (read, len(fs), len(left)))
# a release step still to come
pend = item(30, state="parked", wake=WAKE, post_wake_mover=AGENT, needs=[], next=f"{AGENT}: release PR #19", released_told=[])
from stackshot.model import steps as _steps
d30 = pend[1]; d30["metadata"]["next"] = f"{AGENT}: finish the rollout and see it in real life"
key = _steps.key(_steps.first_line(d30["metadata"]["next"]))
d30["metadata"]["step_proof"] = {key: "pr_released o/r#12"}
fs30, left30, _, _ = AC.proof_wait_findings({pend[0]: d30}, {}, now, env())
check("3 left alone: an open step whose release has not happened keeps the item out of the findings, 'release' named", not fs30 and left30 and "release has not happened" in left30[0]["basis"], (fs30, left30))

# ---- 4. the run
base = build(evwait(1, "recycle", released_told=["o/r#5"]), evwait(2, "fleet_op many"), park(11, wait_basis=BASIS), park(62, post_wake_mover="Oliver"), item(8, state="doing", needs=[AGENT], next=f"{AGENT}: watch it in real life"))
snapshot = json.dumps(base, sort_keys=True)
real_pages = pages
def pages_after_proof(run, deadline):
    ORDER.append("pages"); return {"enabled": False, "mode": "", "counts": {}}
_real_proof = AR.proof_stage
def spy_proof(*a, **k):
    ORDER.append("proof"); return _real_proof(*a, **k)
AR.proof_stage = spy_proof
rec_clear()
rec = go(base)
AR.proof_stage = _real_proof
check("4 run: the stage runs after the model checks and before the pages stage", ORDER == ["proof", "pages"], ORDER)
check("4 run: it makes no model call", RUNNER_CALLS == [] and rec["calls"]["made"] == 0, RUNNER_CALLS)
check("4 run: two findings, one to close and one to stage, on the record with the category", pw_ids(rec) == ["board#1", "board#2"] and rec["by_category"].get("proof-wait") == 2, (rec["findings"], rec["by_category"]))
msgs = [s for s in sent if s[0] == AGENT]
check("4 run: the mover is sent one message with both lines, the category and what fixes it", len(msgs) == 1 and "board#1 · proof-wait" in msgs[0][1] and "board#2 · proof-wait" in msgs[0][1] and "stage the event now" in msgs[0][1], sent)
check("4 run: nothing goes to the owner or his -main agent for these, and no item of the owner's is flagged", not any("[for Oliver]" in s[1] and "proof-wait" in s[1] for s in sent) and not [s for s in sent if s[0] == "alpha-main" and "proof-wait" in s[1]], sent)
check("4 run: the record names what it left alone with the basis, and the counts", left_ids(rec).get(f"board#{BID_05}", "").startswith("a real-world date") and f"board#{BID_23}" in left_ids(rec) and rec["proof_waits"]["read"] == 4 and rec["proof_waits"]["found"] == 2 and rec["proof_waits"]["left_n"] == 2 and not rec["proof_waits"]["failed"], rec["proof_waits"])
summary = [s for s in sent if s[0] == "projects/example"][0][1]
check("4 run: the summary line says it", "proof waits: 2 found, 2 left alone with their basis" in summary, summary)
check("4 run: the audit writes nothing to any item and closes none", json.dumps(base, sort_keys=True) == snapshot and all(v["status"] == "open" for k, v in base.items()), None)
# a second run, items unwritten: sent once, quiet after
rec2 = go(base, now=now + 12 * H)
check("4 run: a second run with the items unwritten sends nothing for them again (they stay on the record, counted as unchanged)", pw_ids(rec2) == ["board#1", "board#2"] and rec2["repeats"] >= 2 and not [s for s in sent if s[0] == AGENT and "proof-wait" in s[1]], (rec2["repeats"], sent))
# a write to the item brings the finding back
base["a2"]["written_at"] = now + 13 * H; base["a2"]["updated"] = now + 13 * H
rec3 = go(base, now=now + 24 * H)
again = [s for s in sent if s[0] == AGENT and "proof-wait" in s[1]]
check("4 run: a write to an item brings its finding back, the other stays quiet", len(again) == 1 and "board#2 · proof-wait" in again[0][1] and "board#1 · proof-wait" not in again[0][1], sent)

# ---- 5. the cap
many = build(*[evwait(100 + n, "fleet_op many") for n in range(AC.PROOF_MAX + 3)])
rec_clear()
rec = go(many)
sent_lines = "\n".join(s[1] for s in sent if s[0] == AGENT)
check("5 cap: no more than PROOF_MAX fresh findings are sent, the others counted as capped and left off the record", len(pw_ids(rec)) == AC.PROOF_MAX and rec["proof_waits"]["capped"] == 3 and rec["proof_waits"]["found"] == AC.PROOF_MAX + 3 and sent_lines.count("proof-wait") == AC.PROOF_MAX, (len(pw_ids(rec)), rec["proof_waits"], sent_lines.count("proof-wait")))
check("5 cap: the summary line says what is left for the next run", "3 over the cap" in [s for s in sent if s[0] == "projects/example"][0][1], sent)
rec_b = go(many, now=now + 12 * H)
check("5 cap: the next run sends the 3 the cap held back, and the ones sent before take no place", len(pw_ids(rec_b)) == AC.PROOF_MAX + 3, pw_ids(rec_b))
sent_b = "\n".join(s[1] for s in sent if s[0] == AGENT)
check("5 cap: …exactly those 3 go out", sent_b.count("proof-wait") == 3 and rec_b["proof_waits"]["capped"] == 0, (sent_b.count("proof-wait"), rec_b["proof_waits"]))

# ---- 6. a stage that fails is a stage not made
rec_clear()
real_find = AR.proof_wait_findings
def boom(*a, **k): raise RuntimeError("boom in the stage")
AR.proof_wait_findings = boom
try:
    rec = go(base)
finally:
    AR.proof_wait_findings = real_find
check("6 failure: the run finishes, the record and the summary say the stage failed, no proof-wait finding", rec.get("finished") and not rec.get("error") and rec["proof_waits"]["failed"] == 1 and "boom" in rec["proof_waits"]["note"] and not pw_ids(rec)
      and "proof waits: the proof-waits stage failed" in [s for s in sent if s[0] == "projects/example"][0][1], rec["proof_waits"])

# ---- 7. the dry run
rec_clear(); sent.clear(); lines = []
out = AR.run(dry=True, now=now, items=base, anchors={}, env=env(), rubric=RUBRIC_TEXT, out=lines.append)
text = "\n".join(lines)
check("7 dry: the findings and the items left alone are listed, nothing is sent, no record is written", "[proof-wait] board#1 · proof-wait" in text and f"[proof-wait · left alone] board#{BID_05} · a real-world date" in text
      and not sent and not list((T / "state/audit").glob("run-*.json")) and out["proof_waits"]["found"] == 2, (text, sent))

# ---- 8. review follow-ups
# 8a a held item stored as doing has no model wait: its real-world date still keeps it, as the same parked item
VENDOR = {"text": "the vendor's visit on 2031-04-17", "wake": WAKE, "at": now - H}
def held_doing(i, **meta): return item(i, **{"state": "doing", "hold": True, "wake": WAKE, "needs": [AGENT], "next": f"{AGENT}: keep it open to see it in real life", **meta})
dated = build(park(6, wait_basis=VENDOR), held_doing(14, wait_basis=VENDOR), held_doing(12))
fs8, left8, read8, skip8 = AC.proof_wait_findings(dated, {}, now, env())
lf8 = {x["id"]: x["basis"] for x in left8}
check("8a held as doing: the same real-world date keeps a held item stored as doing and a parked one alike, the basis named", "real-world date" in lf8.get(f"board#{BID_00}", "") and "real-world date" in lf8.get(f"board#{BID_08}", "") and "vendor" in lf8.get(f"board#{BID_08}", ""), (lf8, [f["id"] for f in fs8]))
check("8a held as doing: the same item without a basis is a finding (it is a candidate)", [f["id"] for f in fs8] == [f"board#{BID_06}"] and skip8 == 0, fs8)

# 8b the words: what must not match, and what must
NOT = ("the buyer to see if the contract is signed", "run it to see that it passes", "the next real step is the vendor call", "first real customer onboarded", "a real case from the buyer", "observe the first batch",
       "next real-world date", "to see whether the vendor replies")
YES_ = ("keep it open to see it in real life", "wait for a real run", "the first real incident", "watch the next real event", "see it work for real.", "it is live in real use", "when it next happens", "check it organically",
        "the next scheduled occurrence", "next real traffic")
bad = [t for t in NOT if AC._REAL_EVENT_RX.search(t)]
check("8b words: the loose phrases do not match", not bad, bad)
miss = [t for t in YES_ if not AC._REAL_EVENT_RX.search(t)]
check("8b words: the phrases it is for do match", not miss, miss)
check("8b words: through an item, a next line with 'see if' is no candidate and one with 'see it in real life' is", AC.real_event_words(park(55, nxt=f"{AGENT}: the buyer to see if the contract is signed")[1]) == ""
      and "real life" in AC.real_event_words(park(56)[1]), None)

# 8c the fix text: never tells anyone to queue a recycle or fleet op alone; the owner's go is the basis
check("8c wording: no 'queue', the owner's go named as the basis, still a downgrade, a probe and a dry run", "queue" not in AC.PROOF_STAGE_FIX and "Oliver's go" in AC.PROOF_STAGE_FIX and "that is the wait's basis" in AC.PROOF_STAGE_FIX
      and all(w in AC.PROOF_STAGE_FIX for w in ("downgrade", "probe", "dry run")), AC.PROOF_STAGE_FIX)

# 8d a prose wait that names a pull request to merge or release is the release path's
prose = build(park(57, nxt=f"{AGENT}: wait for PR #19 to merge, then see it in real life"), park(58, nxt=f"{AGENT}: release o/r#13, then watch it in real life"),
              park(15, nxt=f"{AGENT}: PR #19 was released; keep it open to see it in real life"))
fs9, left9, _, _ = AC.proof_wait_findings(prose, {}, now, env())
check("8d prose: a wait for a PR to merge or be released is no candidate, one whose PR is already released still is", [f["id"] for f in fs9] == [f"board#{BID_09}"] and not left9, (fs9, left9))

# 8e one unreadable item is skipped and counted, the others are read
real_item = AC._proof_item
def flaky(gid, items_, now_):
    if gid == "a9316": raise ValueError("malformed metadata")
    return real_item(gid, items_, now_)
AC._proof_item = flaky
try:
    two = build(evwait(13, "fleet_op many"), evwait(52, "fleet_op many"), evwait(18, "job_run nightly"))
    fs10, left10, read10, skip10 = AC.proof_wait_findings(two, {}, now, env())
    rec_clear()
    rec = go(two)
finally:
    AC._proof_item = real_item
check("8e unreadable: the item is skipped and counted, the others are findings", [f["id"] for f in fs10] == [f"board#{BID_07}", f"board#{BID_10}"] and skip10 == 1 and read10 == 2, (fs10, skip10, read10))
check("8e unreadable: the run's record and summary carry the count, the stage did not fail", rec["proof_waits"]["skipped"] == 1 and not rec["proof_waits"]["failed"] and rec["proof_waits"]["found"] == 2
      and "1 unreadable item(s) skipped" in [s for s in sent if s[0] == "projects/example"][0][1], rec["proof_waits"])
check("8f the unused category tuple is gone", not hasattr(AC, "CHECKS_PROOF"), None)

# ---- the stage costs the old runs nothing: an item set with no such wait gives no proof-wait line and a summary without the stage
rec_clear()
rec = go(build(item(40, state="doing", needs=[AGENT], next=f"{AGENT}: build it", expected_by=local_str(now + 30 * H), expected_reason="the build runs overnight")))
check("0 quiet: with no held item the stage finds nothing and the summary does not mention it", rec["proof_waits"]["found"] == 0 and "proof waits" not in [s for s in sent if s[0] == "projects/example"][0][1], rec["proof_waits"])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
