"""Scenario test for the pattern review of the twice-daily audit (audit_checks.group_patterns / pick_patterns / parse_drafts, audit_run.pattern_stage): the last stage of a model run reads the findings every
audit made since the review before it, groups the repeats by kind, agent and project, and makes ONE model call that drafts one guardrail per pattern. In shadow (the default) the drafts only go onto the
run record and the summary line. Fixture items, crafted findings, a recording sender, a fake model runner; no live store, no network, no server.

  1  grouping: findings group by kind, agent and project; the rule or kind inside `next rules` and `board checks` is part of the kind; a pattern needs PATTERN_MIN appearances on PATTERN_MIN_ITEMS items
  2  the answer: one JSON object with a `drafts` list; a pattern that was not asked about, a guardrail outside the five, a draft with no text and a second draft for a pattern are dropped; the route is the
     owner for a change in what he sees or a rule means, the rulebook's own path for a rulebook line, else the builder
  3  the findings log: an audit pass's record appends a finding the first time it shows it (not while it stays, again once it ended and came back); `off` keeps no log
  4  the run, shadow by default: one call, on the audit's lane and model with the review's brief, about the patterns only; the drafts, the counts and the time on the record; the summary line names them;
     nothing is sent to any agent but the findings' own messages, nothing is written to any item
  5  the window: the next review reads only what the audits found after the one before it
  6  dedupe: a pattern drafted within 7 days is not drafted again (no call when nothing else is left); after the 7 days it is
  7  the cap: no more than PATTERN_MAX patterns are asked about, the rest wait and are asked about on the next run
  8  the budget: the call keeps one of the `[audit] max_calls`, begins only inside `[audit] max_minutes`, and a cap of 0 leaves none
  9  failure is isolated: a call that fails, an answer that cannot be read and a stage that raises are recorded as failed, the run finishes, and the findings stay unread for the next review
  10 off: no call, no log, nothing on the record; the dry run groups and picks, makes no call, writes nothing
  11 the log keeps 14 days

    tests/run-suite pattern_review        → exit 0 / 1"""
import json, os, pathlib, re, sys, time
BID_A = 9168
BID_B = 9169
BID_C = 9170

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="patrev-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_run as AR; from stackshot.audit import audit_checks as AC

H = 3600; DAY = 86400; now = time.time()
ZONE_HOURS = 4                                                              # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
if min((now + ZONE_HOURS * 3600) % 86400, 86400 - (now + ZONE_HOURS * 3600) % 86400) < 600: now -= 900     # not within 10 minutes of a local midnight: the record times a few seconds after `now` stay on one date
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

# ---- fixtures: plain items nothing flags, and the findings the checks are made to return
AGENT = "home-agent"; OTHER = "other-agent"; ALPHA = "projects/alpha"; BETA = "projects/beta"
def item(i, **meta):
    at = now - 2 * H
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": at, "state_updated": at, "confirmed": at,
         "written_at": at, "written_by": AGENT, "metadata": {"owner": "00000000-0000-4000-8000-000000000001", "project": ALPHA, "state": "doing", "needs": [AGENT], "next": f"{AGENT}: build it",
                                                         "expected_by": "2099-01-01 00:00", "expected_reason": "the build runs overnight", **meta}}
    return f"a{i}", d
ITEMS = dict(item(i) for i in range(1, 80))
def fnd(i, kind="ask-missing", mover=AGENT, project=ALPHA, detail=None):
    return {"id": f"board#{i}", "project": project, "owner": mover, "mover": mover, "category": kind, "detail": detail or f"{kind} detail of item {i}", "fix": "fix it", "source": "code"}
ROLES = {AGENT: {"role": "background"}, OTHER: {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent, pushed = [], []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def push(to, text): pushed.append((to, text)); return True, "delivered"
def pages(run, deadline): return {"enabled": False, "mode": "", "counts": {}}
CALLS = []; ANSWER = {"fn": None}
def runner(message):
    CALLS.append(message)
    if ANSWER["fn"]: return ANSWER["fn"](message)
    drafts = [{"pattern": k, "guardrail": "hook", "draft": f"gate the write that makes {k.split(' | ')[0]}", "why": "the tool allows it", "changes_view": False} for k in keys_of(message)]
    return {"status": "ok", "text": json.dumps({"drafts": drafts})}
def keys_of(message): return re.findall(r"^\s*\d+\. key: (.+)$", message, re.M)
def env(**kw):
    e = AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, push=push, sessions=lambda: None, pages=pages, **kw)
    if "runner" not in kw: e.runner = runner
    return e
RUBRIC_TEXT = pathlib.Path(STACK, "audit_rubric.txt").read_text(encoding="utf-8").replace("{owner}", "Oliver")
FINDINGS = {"list": []}
AR.field_findings = lambda items, anchors, at, e, **k: (list(FINDINGS["list"]), [], len(items))
def go(findings, **kw):
    sent.clear(); pushed.clear(); CALLS.clear(); FINDINGS["list"] = findings
    return AR.run(now=kw.pop("now", now), items=kw.pop("items", ITEMS), anchors={}, env=kw.pop("env_", None) or env(), rubric=RUBRIC_TEXT, **kw)
def reset():
    for p in (T / "state/audit").glob("*"): p.unlink()
def summary(): return [s for s in sent if s[0] == "projects/example"][0][1]
def log_rows(): return AR.read_log(0.0)
def pr_of(rec): return rec["pattern_review"]
_cfg.CFG["audit"].pop("pattern_review", None)

# ---- 1. grouping
rows = [AC.log_row(f, now, "run") for f in [fnd(1), fnd(2), fnd(3), fnd(4, project=BETA), fnd(5, mover=OTHER), fnd(6, kind="stale"),
                                              fnd(7, kind="next rules", detail="N3: the line has no verb"), fnd(8, kind="next rules", detail="N3: the line has no owner"), fnd(9, kind="next rules", detail="N5: dated")]]
groups = {g["key"]: g for g in AC.group_patterns(rows)}
check("1 grouping: findings group by kind, agent and project", groups[f"ask-missing | {AGENT} | {ALPHA}"]["count"] == 3 and groups[f"ask-missing | {AGENT} | {BETA}"]["count"] == 1
      and groups[f"ask-missing | {OTHER} | {ALPHA}"]["count"] == 1 and groups[f"stale | {AGENT} | {ALPHA}"]["count"] == 1, sorted(groups))
check("1 grouping: the rule inside `next rules` is part of the kind", groups[f"next rules:N3 | {AGENT} | {ALPHA}"]["count"] == 2 and groups[f"next rules:N5 | {AGENT} | {ALPHA}"]["count"] == 1, sorted(groups))
check("1 grouping: the largest first, the items sorted and distinct, a few different evidence lines kept", AC.group_patterns(rows)[0]["key"] == f"ask-missing | {AGENT} | {ALPHA}"
      and groups[f"ask-missing | {AGENT} | {ALPHA}"]["items"] == ["board#1", "board#2", "board#3"] and len(groups[f"ask-missing | {AGENT} | {ALPHA}"]["details"]) == 3, groups[f"ask-missing | {AGENT} | {ALPHA}"])
twice = AC.group_patterns([AC.log_row(fnd(1), now, "run")] * 4 + [AC.log_row(fnd(2), now, "run")] * 2)
picked, n = AC.pick_patterns(twice, {})
check("1 pattern: the same item four times and another twice is not a pattern of one item, the rule is PATTERN_MIN appearances on PATTERN_MIN_ITEMS items", len(picked) == 1 and picked[0]["count"] == 6
      and AC.PATTERN_MIN == 3 and AC.PATTERN_MIN_ITEMS == 2, (picked, n))
one = AC.group_patterns([AC.log_row(fnd(1), now, "run")] * 5)
check("1 pattern: one item flagged again and again is not a pattern; two appearances on two items are not either", AC.pick_patterns(one, {})[0] == [] and AC.pick_patterns(AC.group_patterns([AC.log_row(fnd(1), now, "run"), AC.log_row(fnd(2), now, "run")]), {})[0] == [], None)

# ---- 2. the answer
K = f"ask-missing | {AGENT} | {ALPHA}"; K2 = f"stale | {AGENT} | {ALPHA}"; K3 = f"next rules:N3 | {AGENT} | {ALPHA}"
ans = json.dumps({"drafts": [{"pattern": K, "guardrail": "hook", "draft": "refuse a decision with no ask", "why": "w", "changes_view": False},
                             {"pattern": K, "guardrail": "mod", "draft": "a second draft for the same pattern"},
                             {"pattern": K2, "guardrail": "rulebook", "draft": "one line", "why": "w"},
                             {"pattern": K3, "guardrail": "audit", "draft": "edit N3", "changes_view": True},
                             {"pattern": "made-up | x | y", "guardrail": "hook", "draft": "unknown pattern"},
                             {"pattern": K3, "guardrail": "magic", "draft": "no such guardrail"},
                             {"pattern": K3, "guardrail": "hook", "draft": ""}]})
got = AC.parse_drafts("Here you go:\n```json\n" + ans + "\n```", {K, K2, K3})
check("2 answer: a fence or a line of prose around the object is read; a second draft for a pattern, an unknown pattern, a guardrail outside the five and an empty draft are dropped",
      [(d["key"], d["guardrail"]) for d in got] == [(K, "hook"), (K2, "rulebook"), (K3, "audit")], got)
check("2 answer: the route is the builder for a hook, the rulebook's own path for a rulebook line, the owner when it changes what he sees or a rule means", [d["route"] for d in got] == ["code", "rulebook", "owner"], got)
check("2 answer: no object with a drafts list, or two of them, is no answer; an empty list is an answer", AC.parse_drafts("no json", {K}) is None and AC.parse_drafts('{"drafts": []} {"drafts": []}', {K}) is None and AC.parse_drafts('{"drafts": []}', {K}) == [], None)

# ---- 3. the findings log
reset()
P = T / "state/audit/filing.json"
AR.write_pass_record(P, {"started": now, "finished": now + 1, "findings": [fnd(1), fnd(2)]})
AR.write_pass_record(P, {"started": now, "finished": now + 2, "findings": [fnd(1), fnd(2), fnd(3)]})
AR.write_pass_record(P, {"started": now, "finished": now + 3, "findings": [fnd(1)]})
AR.write_pass_record(P, {"started": now, "finished": now + 4, "findings": [fnd(1), fnd(2)]})
r3 = log_rows()
check("3 log: a pass's record appends a finding the first time it shows it, not while it stays, and again when it ended and came back", [r["id"] for r in r3] == ["board#1", "board#2", "board#3", "board#2"], [r["id"] for r in r3])
check("3 log: a row has the time, the pass, the item, kind, agent, project and the evidence", r3[0]["source"] == "filing" and r3[0]["kind"] == "ask-missing" and r3[0]["agent"] == AGENT and r3[0]["project"] == ALPHA and r3[0]["at"] == now + 1 and r3[0]["detail"], r3[0])
check("3 log: the record itself is written as before", json.loads(P.read_text())["findings"][1]["id"] == "board#2", None)
_cfg.CFG["audit"]["pattern_review"] = "off"; reset()
AR.write_pass_record(P, {"started": now, "finished": now + 1, "findings": [fnd(1)]})
check("3 log: with the review off no log is kept, the record is written", not (T / "state/audit/findings-log.jsonl").exists() and P.exists(), None)
_cfg.CFG["audit"].pop("pattern_review", None)
check("3 config: shadow is the default, off is off, anything else reads as the default", _cfg.audit_pattern_review() == "shadow" and (_cfg.CFG["audit"].__setitem__("pattern_review", " OFF ") or _cfg.audit_pattern_review() == "off")
      and (_cfg.CFG["audit"].__setitem__("pattern_review", "live") or _cfg.audit_pattern_review() == "shadow") and (_cfg.CFG["audit"].__setitem__("pattern_review", 3) or _cfg.audit_pattern_review() == "shadow"), None)
_cfg.CFG["audit"].pop("pattern_review", None)

# ---- 4. the run, in shadow by default
reset()
snap = json.dumps(ITEMS, sort_keys=True)
f4 = [fnd(1), fnd(2), fnd(3), fnd(4), fnd(5, kind="stale", project=BETA), fnd(6, kind="stale", project=BETA), fnd(7, kind="stale")]
rec = go(f4)
pr = pr_of(rec)
check("4 run: ONE call, about the one pattern only (3 or more appearances on 2 or more items), the message naming the pattern", len(CALLS) == 1 and keys_of(CALLS[0]) == [K] and "board#1" in CALLS[0] and "board#5" not in CALLS[0]
      and CALLS[0].startswith("Pattern review."), CALLS)
check("4 run: the record has the draft: pattern, guardrail, where it would go, text, the counts and when it was made", pr["mode"] == "shadow" and pr["called"] == 1 and pr["failed"] == 0 and len(pr["drafts"]) == 1
      and pr["drafts"][0]["key"] == K and pr["drafts"][0]["guardrail"] == "hook" and pr["drafts"][0]["route"] == "code" and pr["drafts"][0]["count"] == 4 and pr["drafts"][0]["items"] == ["board#1", "board#2", "board#3", "board#4"]
      and pr["drafts"][0]["at"] == pr["at"] and pr["patterns"] == 1 and pr["read"] == 7 and pr["deduped"] == 0 and pr["capped"] == 0, pr)
text4 = summary()
check("4 run: the summary line names it, and a line under it each draft's guardrail and where it would go; the text of a draft stays on the record", "pattern review (shadow): 1 pattern(s) in 7 finding(s), 1 drafted (hook)" in text4
      and f"pattern draft · hook · for code · {K}" in text4 and "gate the write" not in text4 and "of 40" in text4, text4)
check("4 run: shadow sends nothing for it: the messages are the findings' own and the summary, none to the builder or the -main agent, and nothing is written to any item",
      {s[0] for s in sent} <= {AGENT, "projects/example"} and not pushed and json.dumps(ITEMS, sort_keys=True) == snap, ([s[0] for s in sent], pushed, json.dumps(ITEMS, sort_keys=True) == snap))
check("4 run: the findings log holds this run's fresh findings, at the time of the review", len([r for r in log_rows() if r["source"] == "run"]) == 7 and {r["at"] for r in log_rows()} == {pr["at"]}, log_rows()[:2])
check("4 run: the call is made after the proof-waits and pages stages, the record carries the proof_waits and pages beside it", "proof_waits" in rec and "pages" in rec and list(rec).index("pattern_review") > list(rec).index("pages"), list(rec))

# the call itself: the audit's lane and model, the review's brief as the system prompt
from stackshot.router import router as _router
seen = []
def fake_run_call(message, rubric, model_name=None, lane=None, **kw):
    seen.append((message, rubric, model_name, lane)); return {"status": "ok", "text": json.dumps({"drafts": []})}
real_rc = _router.run_call; _router.run_call = fake_run_call
_cfg.CFG["audit"].update(lane="bedrock", model="sonnet")
try:
    reset(); e = AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, push=push, sessions=lambda: None, pages=pages)
    rec = go(f4, env_=e)
finally:
    _router.run_call = real_rc; _cfg.CFG["audit"].pop("lane", None); _cfg.CFG["audit"].pop("model", None)
check("4 call: the router's call on the audit's lane and model, with the review's brief (not the judgment rubric) as the system prompt; an empty list of drafts is an answer", len(seen) == 1
      and seen[0][1] == AC.PATTERN_BRIEF and seen[0][1] != RUBRIC_TEXT and seen[0][2] == "sonnet" and seen[0][3] == "bedrock" and pr_of(rec)["failed"] == 0 and pr_of(rec)["drafts"] == [] and pr_of(rec)["at"], seen)
check("4 brief: the five guardrails are named, the drafts are not edits, the patterns' text is data", all(w in AC.PATTERN_BRIEF for w in ("hook", "mod", "tool-text", "rulebook", "audit", "edit nothing", "data to read")), None)

# ---- 5. the window: only what the audits found after the review before it
reset(); go(f4)
t_after = time.time() + 5
for i in (10, 11, 12):                                                           # a pass finds a new pattern after the review
    AR.write_pass_record(P, {"started": t_after, "finished": t_after + i, "findings": [fnd(10), fnd(11), fnd(12)][: i - 9]})
rec = go([], now=now + 12 * H, env_=env(clock=lambda: time.time() + 60))
pr = pr_of(rec)
check("5 window: the next review reads only what the passes found after the one before it (3 rows, not the first run's 7), on the pattern the first run drafted, so none is drafted again", pr["read"] == 3 and pr["patterns"] == 1 and pr["deduped"] == 1 and pr["called"] == 0 and CALLS == [], pr)

# ---- 6. dedupe
reset(); rec1 = go(f4)
check("6 dedupe setup: the first run drafted the pattern", [d["key"] for d in pr_of(rec1)["drafts"]] == [K], pr_of(rec1))
f6 = [fnd(20), fnd(21), fnd(22)]
rec2 = go(f6, now=now + 12 * H, env_=env(clock=lambda: time.time() + 60))
check("6 dedupe: the same pattern 12 hours later is not drafted again, and with nothing else left there is no call", CALLS == [] and pr_of(rec2)["deduped"] == 1 and pr_of(rec2)["drafts"] == [] and pr_of(rec2)["called"] == 0 and pr_of(rec2)["patterns"] == 1, pr_of(rec2))
check("6 dedupe: the summary line says so", "1 already drafted in the last 7 days" in summary(), summary())
f6b = [fnd(30), fnd(31), fnd(32), fnd(33, kind="stale"), fnd(34, kind="stale"), fnd(35, kind="stale")]
rec3 = go(f6b, now=now + 24 * H, env_=env(clock=lambda: time.time() + 120))
check("6 dedupe: another pattern next to the drafted one is asked about alone", len(CALLS) == 1 and keys_of(CALLS[0]) == [K2] and [d["key"] for d in pr_of(rec3)["drafts"]] == [K2] and pr_of(rec3)["deduped"] == 1, (CALLS, pr_of(rec3)))
f6c = [fnd(40), fnd(41), fnd(42)]
later = now + 8 * DAY
rec4 = go(f6c, now=later, env_=env(clock=lambda: later + 60))
check("6 dedupe: after 7 days the pattern is drafted again", len(CALLS) == 1 and keys_of(CALLS[0]) == [K] and [d["key"] for d in pr_of(rec4)["drafts"]] == [K], (CALLS, pr_of(rec4)))

# ---- 7. the cap
reset()
kinds = [f"kind{c}" for c in "abcdefg"]
f7 = [fnd(10 * n + k, kind=kd) for n, kd in enumerate(kinds, 1) for k in range(3)]
rec = go(f7)
asked = keys_of(CALLS[0]); pr = pr_of(rec)
check("7 cap: seven patterns, PATTERN_MAX asked about in one call, the largest first then by key, the rest counted", len(CALLS) == 1 and len(asked) == AC.PATTERN_MAX == 5 and pr["patterns"] == 7 and pr["capped"] == 2 and len(pr["drafts"]) == 5
      and asked == [f"{kd} | {AGENT} | {ALPHA}" for kd in kinds[:5]], (asked, pr["capped"]))
check("7 cap: the summary line says what waits for the next run", "2 over the cap of 5, left for the next run" in summary(), summary())
rec = go([fnd(75 + k, kind="kindz") for k in range(3)], now=now + 12 * H, env_=env(clock=lambda: time.time() + 60))
asked2 = keys_of(CALLS[0]) if CALLS else []
check("7 cap: the cap left the review unfinished (no `at`), so the next one starts at the record's start: the five drafted are deduped, the two held back are asked about with the new one", pr["at"] is None, None)
check("7 cap: the next run asks about the two held back and the new pattern; the five drafted are read again and not drafted twice", pr_of(rec)["deduped"] == 5 and sorted(asked2) == sorted(f"{kd} | {AGENT} | {ALPHA}" for kd in kinds[5:] + ["kindz"]) and pr_of(rec)["capped"] == 0, (asked2, pr_of(rec)))
too_many = lambda m: {"status": "ok", "text": json.dumps({"drafts": [{"pattern": k, "guardrail": "hook", "draft": "d"} for k in keys_of(m)] + [{"pattern": f"kindq{n} | {AGENT} | {ALPHA}", "guardrail": "hook", "draft": "unasked"} for n in range(4)]})}
ANSWER["fn"] = too_many; reset(); rec = go(f7); ANSWER["fn"] = None
check("7 cap: drafts for patterns that were not asked about are dropped, so a run never has more than PATTERN_MAX", len(pr_of(rec)["drafts"]) == 5, pr_of(rec)["drafts"])

# ---- 8. the budget
import types
reset(); _cfg.CFG["audit"]["max_calls"] = 5
n_picked = []
real_suspects, real_judge = AR.suspects, AR.judge
AR.suspects = lambda items, at, e, judged=None, live=None, goal_seen=None: ([{"id": f"board#{k}", "gid": f"a{k}", "project": ALPHA, "checks": ["next-done"], "evidence": {"next-done": "x"}, "write": 0.0, "priority": 0, "sig": "", "context": []} for k in range(1, 11)], 0)
def fake_judge(items, picked, at, e, rubric, t0=None): n_picked.append(len(picked)); return [], {}, {"made": len(picked), "failed": 0, "timed_out": False, "notes": []}
AR.judge = fake_judge
try:
    rec = go(f4)
    check("8 budget: the review keeps one of the calls of the cap: 5 calls, 4 for the suspects, the review's the fifth", n_picked == [4] and len(CALLS) == 1 and "5 model call(s) of 5" in summary() and rec["calls"]["made"] == 4, (n_picked, summary()))
    _cfg.CFG["audit"]["max_calls"] = 1; n_picked.clear(); reset()
    rec = go(f4)
    check("8 budget: with a cap of 1 the suspects keep it and the review says it has no call", n_picked == [1] and CALLS == [] and pr_of(rec)["called"] == 0 and "leaves no model call" in pr_of(rec)["note"] and pr_of(rec)["at"] is None, pr_of(rec))
    _cfg.CFG["audit"]["pattern_review"] = "off"; _cfg.CFG["audit"]["max_calls"] = 5; n_picked.clear(); reset()
    rec = go(f4)
    check("8 budget: with the review off the suspects have all 5", n_picked == [5], n_picked)
finally:
    AR.suspects, AR.judge = real_suspects, real_judge
_cfg.CFG["audit"]["max_calls"] = 0; _cfg.CFG["audit"].pop("pattern_review", None); reset()
rec = go(f4)
check("8 budget: a cap of 0 leaves no call for the review", CALLS == [] and pr_of(rec)["called"] == 0 and "leaves no model call" in pr_of(rec)["note"], pr_of(rec))
_cfg.CFG["audit"]["max_calls"] = 40; reset()
rec = go(f4, env_=env(clock=lambda: now + 101 * 60))
check("8 budget: 101 minutes after the run began (the limit is 100) no call is begun, and the record says so", CALLS == [] and pr_of(rec)["timed_out"] is True and "minutes passed" in pr_of(rec)["note"] and pr_of(rec)["at"] is None, pr_of(rec))
check("8 budget: …and the findings are still sent", any(s[0] == AGENT and "ask-missing" in s[1] for s in sent), [s[0] for s in sent])

# ---- 9. failure is isolated
def failing(m): return {"status": "timeout", "note": "the call took too long"}
ANSWER["fn"] = failing; reset(); rec = go(f4); pr = pr_of(rec)
check("9 failure: a call that fails is recorded as failed, the run finishes with its other stages and its findings sent", rec.get("finished") and not rec.get("error") and pr["failed"] == 1 and pr["called"] == 1 and "failed" in pr["note"]
      and pr["at"] is None and pr["drafts"] == [] and "proof_waits" in rec and any(s[0] == AGENT for s in sent) and "pattern review (shadow): the pattern review call failed" in summary(), pr)
ANSWER["fn"] = lambda m: {"status": "ok", "text": "I think you should add a hook."}
reset(); rec = go(f4); pr = pr_of(rec)
check("9 failure: an answer that cannot be read is a failure too", pr["failed"] == 1 and "no usable JSON" in pr["note"] and pr["at"] is None and not rec.get("error"), pr)
ANSWER["fn"] = None
rec2 = go([], now=now + 12 * H, env_=env(clock=lambda: time.time() + 60))
check("9 failure: the findings the failed review left unread are read by the next one (it has no `at` to start from, so it starts at the record's start)", len(CALLS) == 1 and keys_of(CALLS[0]) == [K] and pr_of(rec2)["read"] == 7
      and [d["key"] for d in pr_of(rec2)["drafts"]] == [K], (CALLS, pr_of(rec2)))
real_group = AR.group_patterns
def boom(*a, **k): raise RuntimeError("boom in the stage")
AR.group_patterns = boom
try:
    reset(); rec = go(f4)
finally:
    AR.group_patterns = real_group
check("9 failure: a stage that raises is a stage not made: the run finishes, the record and the summary say so", rec.get("finished") and not rec.get("error") and pr_of(rec)["failed"] == 1 and "boom" in pr_of(rec)["note"] and pr_of(rec)["at"] is None
      and CALLS == [] and "pattern review (shadow): the pattern review failed" in summary() and "proof_waits" in rec, pr_of(rec))

# ---- 10. off, and the dry run
_cfg.CFG["audit"]["pattern_review"] = "off"; reset()
rec = go(f4)
check("10 off: no call, nothing on the record, no log", CALLS == [] and "pattern_review" not in rec and not (T / "state/audit/findings-log.jsonl").exists() and "pattern review" not in summary(), list(rec))
_cfg.CFG["audit"].pop("pattern_review", None); reset()
AR.write_pass_record(P, {"started": now, "finished": now + 1, "findings": [fnd(1), fnd(2), fnd(3)]})
log_before = (T / "state/audit/findings-log.jsonl").read_text()
sent.clear(); CALLS.clear(); lines = []
out = AR.run(dry=True, now=now, items=ITEMS, anchors={}, env=env(), rubric=RUBRIC_TEXT, out=lines.append)
text = "\n".join(lines)
check("10 dry: the review groups and picks, says how many, makes no call, sends nothing, writes no record and leaves the log as it was",
      "[pattern-review · shadow] 3 finding(s) in the log" in text and "1 pattern(s)" in text and out["pattern_review"]["patterns"] == 1 and out["pattern_review"]["called"] == 0 and CALLS == [] and not sent
      and not list((T / "state/audit").glob("run-*.json")) and (T / "state/audit/findings-log.jsonl").read_text() == log_before, (text, sent))

# ---- 11. the log keeps 14 days
reset()
old_row = AC.log_row(fnd(9168), now - 20 * DAY, "filing"); new_row = AC.log_row(fnd(9169), now - 2 * DAY, "filing")
AR.log_findings([old_row, new_row])
rec = go([])
check("11 log: a run drops the rows older than 14 days and keeps the others", [r["id"] for r in log_rows()] == [f"board#{BID_B}"], log_rows())

# ---- 12. the window walks back to the last review that finished reading, however many failed or were capped since
T0 = 1_000_000_000.0
rv = lambda at=None: {"started": T0, "finished": T0 + 1, "pattern_review": {"at": at}}
hist_a = [rv(), {"started": T0 - 1}, rv(T0 - 10 * H), rv(T0 - 30 * H)]
check("12 window: after a failed review and a record with no review, the window opens at the newest review that finished reading", AR.review_since(hist_a, T0) == T0 - 10 * H, AR.review_since(hist_a, T0))
check("12 window: …never more than 48 hours back, and 48 when no record holds a finished review; 24 with no record at all", AR.review_since([rv(T0 - 100 * H)], T0) == T0 - 48 * H and AR.review_since([rv(), rv()], T0) == T0 - 48 * H
      and AR.review_since([], T0) == T0 - 24 * H, None)
reset(); go(f4)
t_after = time.time() + 5
for i in (1, 2, 3):                                                              # a pass finds a new pattern after the first review
    AR.write_pass_record(P, {"started": t_after, "finished": t_after + i, "findings": [fnd(60, "stale"), fnd(61, "stale"), fnd(62, "stale")][:i]})
ANSWER["fn"] = failing
rb = go([], now=now + 6 * H, env_=env(clock=lambda: time.time() + 30)); rb2 = go([], now=now + 12 * H, env_=env(clock=lambda: time.time() + 40))
ANSWER["fn"] = None
check("12 window: two reviews in a row that failed (no `at`)", pr_of(rb)["failed"] == 1 and pr_of(rb)["at"] is None and pr_of(rb2)["failed"] == 1 and pr_of(rb2)["at"] is None, (pr_of(rb), pr_of(rb2)))
rc = go([], now=now + 18 * H, env_=env(clock=lambda: time.time() + 60))
check("12 window: the review after them still reads the rows the first of them left unread (the window opens at the last finished review, not at the newest record)", pr_of(rc)["read"] == 3 and pr_of(rc)["failed"] == 0
      and pr_of(rc)["since"] < t_after and pr_of(rc)["patterns"] == 1, pr_of(rc))

# ---- 13. a malformed row is skipped, never an error
good = [AC.log_row(fnd(k), now, "run") for k in (1, 2, 3)]
bad = [None, 7, "x", {}, {"kind": "k"}, {"kind": "ask-missing", "id": 5}, {"kind": "ask-missing", "id": ["board#1"]}, {"kind": None, "id": "board#2"}, {"kind": "ask-missing", "id": "board#4", "agent": 3},
       {"kind": "ask-missing", "id": "board#5", "project": ["p"]}, {"kind": ["ask-missing"], "id": f"board#{BID_C}"}]
try:
    gm = AC.group_patterns(bad + good + bad)
    ok13 = len(gm) == 1 and gm[0]["count"] == 3 and gm[0]["items"] == ["board#1", "board#2", "board#3"]
except Exception as e:
    gm, ok13 = repr(e), False
check("13 malformed: a row that is no dict, has no kind or id, or a kind, id, agent or project of the wrong type is skipped; the good ones group", ok13, gm)
reset()
with open(T / "state/audit/findings-log.jsonl", "w") as fh:
    fh.write('[1, 2]\nnot json\n{"at": %s, "kind": "ask-missing", "id": 5}\n{"at": %s, "kind": "ask-missing", "id": ["x"], "agent": null}\n{"at": "soon"}\n' % (time.time() + 1, time.time() + 1))
rec = go(f4)
check("13 malformed: a log with such lines in it is read, the review is not failed and drafts as before", pr_of(rec)["failed"] == 0 and [d["key"] for d in pr_of(rec)["drafts"]] == [K], pr_of(rec))

# ---- 14. the log's upkeep does not depend on the review
reset()
AR.log_findings([AC.log_row(fnd(9168), now - 20 * DAY, "filing")])
AR.group_patterns = boom
try:
    rec = go(f4)
finally:
    AR.group_patterns = real_group
ids14 = sorted({r["id"] for r in log_rows()})
check("14 upkeep: a review that raises still lets the run's findings into the log and the rows past 14 days out", pr_of(rec)["failed"] == 1 and f"board#{BID_A}" not in ids14 and ids14 == [f"board#{k}" for k in range(1, 8)], (pr_of(rec)["failed"], ids14))
real_prune = AR.prune_log
def boom_prune(*a, **k): raise OSError("disk full")
reset(); AR.prune_log = boom_prune
try:
    rec = go(f4)
finally:
    AR.prune_log = real_prune
check("14 upkeep: a prune that fails neither ends the run nor undoes the review", rec.get("finished") and not rec.get("error") and pr_of(rec)["failed"] == 0 and len(pr_of(rec)["drafts"]) == 1, pr_of(rec))
reset(); AR.log_findings([AC.log_row(fnd(9168), now - 20 * DAY, "filing")])
AR.prune_log = boom_prune
try:
    go(f4)
finally:
    AR.prune_log = real_prune
check("14 upkeep: …and the fresh findings were logged all the same", len([r for r in log_rows() if r["source"] == "run"]) == 7, len(log_rows()))

# ---- 15. an append is one write on an append descriptor
real_open, real_write = os.open, os.write
fds, wrote, flagsq = set(), [], []
short = {"first": True}
def spy_open(path, fl, *a, **k):
    fd = real_open(path, fl, *a, **k)
    if str(path).endswith("findings-log.jsonl"): fds.add(fd); flagsq.append(fl)
    return fd
def spy_write(fd, data):
    if fd in fds:
        wrote.append(len(data))
        if short["first"] and short.get("on"): short["first"] = False; return real_write(fd, data[: len(data) // 2])
    return real_write(fd, data)
big = [AC.log_row(fnd(k % 70 + 1, detail="x" * 190), now, "filing") for k in range(150)]
reset()
os.open, os.write = spy_open, spy_write
try:
    AR.log_findings(big)
finally:
    os.open, os.write = real_open, real_write
size = (T / "state/audit/findings-log.jsonl").stat().st_size
check("15 append: a batch over 8 KB goes in with ONE write of the whole batch on an O_APPEND descriptor, and every line is whole", size > 8192 and wrote == [size] and flagsq and flagsq[0] & os.O_APPEND and len(log_rows()) == 150, (size, wrote))
reset(); wrote.clear(); fds.clear(); flagsq.clear(); short.update(first=True, on=True)
os.open, os.write = spy_open, spy_write
try:
    AR.log_findings(big)
finally:
    os.open, os.write = real_open, real_write; short["on"] = False
check("15 append: a short write goes on from where it stopped, nothing lost or doubled", len(wrote) == 2 and len(log_rows()) == 150 and (T / "state/audit/findings-log.jsonl").stat().st_size == wrote[0] and wrote[1] < wrote[0], (wrote, len(log_rows())))
def no_open(*a, **k): raise OSError("read-only file system")
os.open = no_open
try:
    AR.log_findings(big); raised = False
except Exception:
    raised = True
finally:
    os.open = real_open
check("15 append: a log that cannot be opened is a line on stderr, never an error", not raised, None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
