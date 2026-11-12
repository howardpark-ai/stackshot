"""Scenario test for the front-step rule (front_step.py, audit_run.front_step_pass, server._front_step_mark and _front_step_move): a step held by a front agent (or a retired session) that stays the first open
step of an item another session moves is moved to that mover by the ten-minute filing pass, with nobody asking. Fixture items in a temporary store, the server's own item writes, messages replaced by recorders,
no network, no model call.

  1  the clock: the first pass that sees the finding for a step stores `metadata.stuck_since` ({step: hash, at: now}) on the item, for a front agent's step, a keeper's and a retired session's; none for a
     background agent's step, the owner's step, an item the owner moves, or a stuck step whose mover is no session; the finding of a waiting step says what will happen and when
  2  (a) nothing moves before the threshold, and a write to the item by a session does not restart the clock; (b) at the threshold the step is reworded to open with the mover (its place, its other lines and
     its writer pair handled as a reword does: the line is the mover's now), one History line names the original opener, the hours and how to put it back, the mover gets one fyi message and nobody else does
     (not the front agent, not the project), the finding ends; a front agent as mover and a retired opener are moved too (a front mover is not messaged); (c) the cases that are not covered stay untouched, byte for byte
  3  (e) a step moves once: later passes change nothing, and a step worded back to the front agent starts no clock and is not moved again
  4  (d) the clock is dropped when the finding ends (the step done, dropped or reworded: a reworded step starts its own clock; the mover changed), an item with a clock left over when the rule is switched off loses it
  5  (f) the threshold is `[audit] front_step_move_hours` (a decimal reads), 0 = off (nothing kept, nothing moved), a bad value reads as the default (3); a pass with no writers, an empty role map or a dry run does nothing
  6  the server's tick wires the two writers into the pass
  7  a moved step is chased again: a step that moves to a mover who then does not act, on an item with a wake far ahead that is only a reminder, is found silent by the silence pass 45 minutes after the move,
     reaches the mover and is entered on the ladder with no person asking; the controls (a wake that stands on a dated event silences an unmoved item, a step that names a date, a mover who acts) stay quiet;
     a step already found stuck is not covered by a wake set after it
  8  an unanswered finding is not sent once and forgotten (the filing pass): it is sent again after `[audit] remind_hours`, worded as a later try so the router does not drop it as a repeat, up to three
     sends, then once to the project's builder as unmoved (by the page key when the builder is the mover), then, a finding that went to a builder, once to the project's -main agent, and no more; 0 = once only

    tests/run-suite front_step_move        → exit 0 / 1"""
import copy, datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="fsmove-"); T = pathlib.Path(tmp)
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
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.audit import front_step as FS; from stackshot.model import steps as ST; from stackshot.model import nextlines as NL
from stackshot.web import server
server._cfg.CFG["audit"]["mode"] = "script"
H = 3600; now = time.time()
ZONE_OFFSET = 4 * H                       # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900
OWNER = "00000000-0000-4000-8000-000000000001"
fails = []; ran = []
bid = lambda n: f"board#{n}"                           # an item's id as the board writes it
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

STORE = T / "store/a"
def path(k): return STORE / f"{k[1:]}.json"
def put(k, d): path(k).write_text(json.dumps(d), encoding="utf-8")
def get(k): return json.loads(path(k).read_text(encoding="utf-8"))
def raw(k): return path(k).read_bytes()
def item(i, status="open", wrote=None, **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if wrote is None else wrote,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"a{i}", d
def doing(i, nxt, needs=("home-agent",), **kw): return item(i, wrote=now - H, state="doing", needs=list(needs), next=nxt, **kw)
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-keeper": {"role": "keeper"},
         "old-front": {"role": "keeper", "retired": True}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    kw.setdefault("step_mark", server._front_step_mark); kw.setdefault("step_move", server._front_step_move)
    kw.setdefault("clock", lambda: 0.0)         # the pass time is the test's own `now` (a pass reads max(env.clock(), now)): never the real clock, which near a local midnight sits 15 minutes past the shifted `now`
    return AR.Env(roles=kw.pop("roles", ROLES), fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None),
                  deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
def run_pass(at, **kw):
    sent.clear()
    return AR.filing_pass(now=at, env=env(**kw))
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
def wipe_store():
    for p in STORE.glob("*.json"): p.unlink()
def clock_of(k): return (get(k)["metadata"] or {}).get(FS.CLOCK)
def first_open(k): return AC.first_open_step(get(k)["metadata"])
def opener_of(k): return ST.opener(first_open(k))
def to_set(): return {to for to, _t, _f in sent}
def stuck_ids(res): return sorted(f["id"] for f in res["detail"] if f["category"] == "stuck-elsewhere") if res.get("detail") else None

# ---- fixtures
T0 = now
fixtures = [
    doing(1, "alpha-main: decide the wording\nhome-agent: then build it"),                         # a front agent's step; the mover is a background agent
    doing(2, "ops-other: do the first part\nhome-agent: then the second"),                         # a background agent's step: the agent gets the finding itself and can answer
    doing(3, "Oliver: pick one\nhome-agent: then build it"),                                       # the owner's step on an item a session moves
    item(4, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", ask="which one?", then="home-agent", next="alpha-main: apply his pick, then close"),   # the owner moves it
    doing(5, "old-front: check the report\nhome-agent: then ship it"),                              # a retired session's step
    doing(6, "alpha-keeper: write the page entry\nhome-agent: then close"),                          # a keeper's step
    doing(7, "old-front: check the report again\nalpha-builder: then ship it", needs=("alpha-main",), mover="alpha-main"),   # a retired opener, a front agent as the mover
    doing(8, "alpha-main: answer the question\nhome-agent: then build it"),
]
def load_fixtures():
    wipe_store(); clear_state()
    for k, d in fixtures: put(k, copy.deepcopy(d))

load_fixtures()
res = AR.filing_pass(now=T0, env=env(), dry=True)
check("0 the fixture: stuck-elsewhere findings exist for the front agent's, keeper's, retired and background agent's and owner's steps (the owner-moved item with a `then` of home-agent too)",
      {"board#1", "board#2", "board#3", "board#4", "board#5", "board#6", "board#7", "board#8"} <= {f["id"] for f in res["detail"] if f["category"] == "stuck-elsewhere"},
      sorted((f["id"], f["category"]) for f in res["detail"]))

# ---- 1. the clock
load_fixtures()
r = run_pass(T0)
check("1 a front agent's, a keeper's and a retired session's step start a clock on the item (step hash and the pass time)",
      all(clock_of(k) == {"step": FS.step_hash(first_open(k)), "mover": "alpha-main" if k == "a7" else "home-agent", "at": T0} for k in ("a1", "a5", "a6", "a7", "a8")), [clock_of(k) for k in ("a1", "a5", "a6", "a7", "a8")])
check("1 …and none for a background agent's step, the owner's step, or an item the owner moves", all(clock_of(k) is None for k in ("a2", "a3", "a4")), [clock_of(k) for k in ("a2", "a3", "a4")])
check("1 …and the report says which started", sorted(r["front_steps"]["started"]) == ["board#1", "board#5", "board#6", "board#7", "board#8"], r.get("front_steps"))
check("1 the clock is the server's bookkeeping: the item's own write stamps are as they were", all(get(k).get("written_by") == "home-agent" and get(k)["updated"] == now - H for k in ("a1", "a5")), [(get(k).get("written_by"), get(k)["updated"]) for k in ("a1", "a5")])
text_to = lambda to: "\n".join(t for t_, t, _f in sent if t_ == to)
check("1 the finding about a front agent's step goes to the project's page key, as before, and never to the front agent", "board#1 · stuck-elsewhere" in text_to("projects/alpha") and not text_to("alpha-main") and not text_to("alpha-keeper") and not text_to("old-front"), sent)
due = AC._stamp(T0 + 3 * H)
line1 = next(l for l in text_to("projects/alpha").splitlines() if l.startswith("board#1 "))
check("1 …and says what will happen and when: it moves to the mover at the time the clock runs out", f"moves to home-agent at {due}" in line1 and "reword it to home-agent" in line1, line1)
line2 = next(l for l in text_to("ops-other").splitlines() if l.startswith("board#2 "))
check("1 …while a background agent's finding keeps its old fix line", "moves to" not in line2 and line2.endswith(AC.FIX["stuck-elsewhere"]), line2)

# ---- 2a. before the threshold, and a write does not restart the clock
d = get("a1"); d["written_at"] = T0 + H; d["written_by"] = "alpha-main"; d["updated"] = T0 + H; d["metadata"]["note"] = "a write by a session"; put("a1", d)
r = run_pass(T0 + 3 * H - 60)
check("2a nothing moves before the threshold (a minute short)", all(opener_of(k) == o for k, o in (("a1", "alpha-main"), ("a5", "old-front"), ("a6", "alpha-keeper"), ("a7", "old-front"), ("a8", "alpha-main"))) and r["front_steps"]["moved"] == [], (r["front_steps"], [opener_of(k) for k in ("a1", "a5")]))
check("2a …a write to the item by a session does not restart the clock", clock_of("a1")["at"] == T0 and clock_of("a5")["at"] == T0, (clock_of("a1"), clock_of("a5")))
before_bytes = {k: raw(k) for k in ("a2", "a3", "a4")}

# ---- 2b. at the threshold
r = run_pass(T0 + 3 * H)
fs = r["front_steps"]
check("2b at the threshold the steps move: the report names each (from, to, hours)", sorted((m["id"], m["from"], m["to"], m["hours"]) for m in fs["moved"]) == [("board#1", "alpha-main", "home-agent", 3.0), ("board#5", "old-front", "home-agent", 3.0), ("board#6", "alpha-keeper", "home-agent", 3.0),
      ("board#7", "old-front", "alpha-main", 3.0), ("board#8", "alpha-main", "home-agent", 3.0)], fs)
check("2b …the first open step opens with the mover, its other words and the later lines as they were",
      first_open("a1") == "home-agent: decide the wording" and get("a1")["metadata"]["next"] == "home-agent: decide the wording\nhome-agent: then build it" and first_open("a7") == "alpha-main: check the report again", (first_open("a1"), get("a1")["metadata"]["next"]))
m1 = get("a1")["metadata"]
check("2b …the checklist follows (the same two open steps, none dropped) and the line is the mover's now: nobody but home-agent's own write replaces it",
      [(s["text"], s["status"]) for s in ST.view(m1, keeper=OWNER)] == [("home-agent: decide the wording", "open"), ("home-agent: then build it", "open")]
      and [w for _e, w in NL.resolve(m1, OWNER)][0] == "home-agent" and not any(s["status"] == "dropped" for s in m1["steps"]), (m1.get("steps"), m1.get("next_by")))
log1 = (m1.get("stall") or {}).get("log") or []
check("2b …one History line (the stall log) names the original opener, the hours, how to undo it and the step", len(log1) == 1 and "moved from alpha-main to home-agent after 3 hours" in log1[0]["text"]
      and "unanswered" in log1[0]["text"] and "reword it back to undo" in log1[0]["text"] and "decide the wording" in log1[0]["text"] and log1[0]["at"] == T0 + 3 * H, log1)
check("2b …the clock is gone and the step's hash is kept as moved", FS.CLOCK not in m1 and m1[FS.MOVED] == [FS.step_hash("alpha-main: decide the wording")], (m1.get(FS.CLOCK), m1.get(FS.MOVED)))
check("2b …the item's own write stamps are the server's bookkeeping: the last writer stays", get("a1")["written_by"] == "alpha-main" and get("a5")["written_by"] == "home-agent", (get("a1")["written_by"], get("a5")["written_by"]))
movers = [(to, t, f) for to, t, f in sent if "is now yours" in t]
check("2b the mover is told once per step, plainly and as an fyi", sorted(to for to, _t, _f in movers) == ["home-agent"] * 4 and all(f is True for _to, _t, f in movers), sent)
check("2b …the message names the step, the original opener and what happened", all("[stackshot] Filing check " in t and "stayed open 3 hours" in t and "reworded it to open with you" in t for _to, t, _f in movers)
      and any("board#1: the first open step is now yours (home-agent: decide the wording). It opened with alpha-main, a front agent," in t for _to, t, _f in movers)
      and any("board#5: the first open step is now yours" in t and "It opened with old-front, a retired session," in t for _to, t, _f in movers), [t for _to, t, _f in movers])
check("2b …nobody else hears of it: not the front agent, not the keeper, not the retired session, not the project", to_set() <= {"home-agent", "projects/alpha"} and not any("is now yours" in t for to, t, _f in sent if to != "home-agent"), sent)
check("2b …a front agent that is the mover (and a retired opener) is moved too and is not messaged", opener_of("a7") == "alpha-main" and not any(to == "alpha-main" for to, _t, _f in sent) and len((get("a7")["metadata"].get("stall") or {}).get("log") or []) == 1, sent)
check("2b …the finding ends: no stuck-elsewhere finding about a moved step is on the record or sent", not any(f["category"] == "stuck-elsewhere" and f["id"] in ("board#1", "board#5", "board#6", "board#7", "board#8") for f in json.loads((T / "state/audit/filing.json").read_text())["findings"])
      and not any("board#1 · stuck-elsewhere" in t for _to, t, _f in sent), sent)
check("2c what the rule does not cover stays untouched, byte for byte: a background agent's step, the owner's, an item the owner moves", all(raw(k) == v for k, v in before_bytes.items()), [k for k, v in before_bytes.items() if raw(k) != v])
check("2b the moved step no longer reads as stuck: the filing rules find nothing on it", not any(f["id"] == "board#1" and f["category"] == "stuck-elsewhere" for f in AC.filing_findings({"a1": get("a1")}, {}, T0 + 3 * H, env())[0]))

# ---- 3. once only
after = {k: raw(k) for k in ("a1", "a5", "a6", "a7", "a8")}
r = run_pass(T0 + 6 * H)
check("3 a later pass moves nothing and writes nothing, and tells no one", r["front_steps"]["moved"] == [] and all(raw(k) == v for k, v in after.items()) and not any("is now yours" in t for _to, t, _f in sent), (r["front_steps"], sent))
d = get("a1"); d["metadata"]["next"] = "alpha-main: decide the wording\nhome-agent: then build it"; d["metadata"].pop("steps", None); d["metadata"].pop("next_by", None); put("a1", d)      # worded back to the front agent
run_pass(T0 + 7 * H)
back_line = next((l for l in text_to("projects/alpha").splitlines() if l.startswith("board#1 ")), "")
r = run_pass(T0 + 12 * H)
check("3 a step worded back to the front agent starts no clock and is not moved a second time", clock_of("a1") is None and opener_of("a1") == "alpha-main" and r["front_steps"]["moved"] == [] and not any("is now yours" in t for _to, t, _f in sent), (clock_of("a1"), r["front_steps"]))
check("3 …its finding is the old one again, with the old fix line (nothing is promised)", "stuck-elsewhere" in back_line and "moves to" not in back_line and back_line.endswith(AC.FIX["stuck-elsewhere"]), back_line)

# ---- 4. the clock is dropped when the finding ends
load_fixtures()
run_pass(T0)
d = get("a1"); d["metadata"]["next"] = "home-agent: then build it"; put("a1", d)                                                  # the front agent's step is done: gone from next
d = get("a5"); d["metadata"]["next"] = "alpha-main: check the report, other words\nhome-agent: then ship it"; put("a5", d)       # reworded to another front agent's step
d = get("a6"); d["metadata"]["next"] = "home-agent: write the page entry\nhome-agent: then close"; put("a6", d)                  # reworded to the mover
d = get("a7"); d["metadata"]["needs"] = ["alpha-builder"]; d["metadata"]["mover"] = "alpha-builder"; d["metadata"]["next"] = "old-front: check the report again\nalpha-builder: then ship it"; put("a7", d)      # the mover changed to a background agent: still a front opener
d = get("a8"); d["status"] = "completed"; d["metadata"]["outcome"] = "done"; put("a8", d)                                         # closed
r = run_pass(T0 + 2 * H)
check("4 a step done or reworded to its mover, an item closed: the clock is dropped", all(clock_of(k) is None for k in ("a1", "a6", "a8")), [clock_of(k) for k in ("a1", "a6", "a8")])
check("4 a reworded step starts a clock of its own (the old clock does not carry over)", clock_of("a5") == {"step": FS.step_hash("alpha-main: check the report, other words"), "mover": "home-agent", "at": T0 + 2 * H}, clock_of("a5"))
check("4 a new mover gets a clock of its own: the step whose mover changed (the opener did not) starts afresh, under the new mover", clock_of("a7") == {"step": FS.step_hash("old-front: check the report again"), "mover": "alpha-builder", "at": T0 + 2 * H}, clock_of("a7"))
r3 = run_pass(T0 + 3 * H)
check("4 …neither a reworded step nor the step whose mover changed is moved at the old clock's time", r3["front_steps"]["moved"] == [] and opener_of("a5") == "alpha-main" and opener_of("a7") == "old-front", (r3["front_steps"], opener_of("a5"), opener_of("a7")))
r5 = run_pass(T0 + 5 * H)
check("4 …but each at its own, the new mover receiving the step then", sorted(m["id"] for m in r5["front_steps"]["moved"]) == ["board#5", "board#7"] and opener_of("a5") == "home-agent" and opener_of("a7") == "alpha-builder", (r5["front_steps"], clock_of("a5"), opener_of("a5"), opener_of("a7")))
check("4 …the report names the clocks dropped", sorted(r["front_steps"]["cleared"]) == ["board#1", "board#6", "board#8"], r["front_steps"])

# ---- 5. the threshold
load_fixtures()
cfg_audit = server._cfg.CFG["audit"]
cfg_audit.pop("front_step_move_hours", None)
check("5 the default is 3 hours", _cfg.audit_front_step_move_hours() == 3.0 and FS.hours() == 3.0)
for bad in (-1, "soon", True, None, "", float("inf")):
    cfg_audit["front_step_move_hours"] = bad
    if _cfg.audit_front_step_move_hours() != 3.0: check(f"5 a bad value {bad!r} reads as the default", False, _cfg.audit_front_step_move_hours())
cfg_audit["front_step_move_hours"] = 1.5
check("5 a decimal reads", _cfg.audit_front_step_move_hours() == 1.5)
run_pass(T0); r = run_pass(T0 + 1.5 * H - 60)
check("5 [audit] front_step_move_hours sets the threshold (1.5: not at 89 minutes)", r["front_steps"]["moved"] == [] and opener_of("a1") == "alpha-main")
r = run_pass(T0 + 1.5 * H)
check("5 …and at 90 minutes the steps move, the History line saying 1.5 hours", {m["id"] for m in r["front_steps"]["moved"]} == {"board#1", "board#5", "board#6", "board#7", "board#8"} and "after 1.5 hours" in get("a1")["metadata"]["stall"]["log"][0]["text"], r["front_steps"])
load_fixtures()
cfg_audit["front_step_move_hours"] = 0
r = run_pass(T0); r2 = run_pass(T0 + 30 * H)
check("5 0 is off: no clock is kept and nothing moves, however long a step stays", all(clock_of(k) is None for k in ("a1", "a5", "a6", "a7", "a8")) and r2["front_steps"]["moved"] == [] and opener_of("a1") == "alpha-main" and r2["front_steps"]["hours"] == 0, r2["front_steps"])
check("5 …and the findings go out as they always did", "board#1 · stuck-elsewhere" in text_to("projects/alpha") or r["fresh"] >= 1)
cfg_audit["front_step_move_hours"] = 3
run_pass(T0 + 40 * H)
check("5 the rule on again starts clocks afresh", clock_of("a1") == {"step": FS.step_hash(first_open("a1")), "mover": "home-agent", "at": T0 + 40 * H}, clock_of("a1"))
cfg_audit["front_step_move_hours"] = 0
r = run_pass(T0 + 41 * H)
check("5 switched off with clocks standing, the pass drops them (so a later switch-on does not move at once)", all(clock_of(k) is None for k in ("a1", "a5", "a6", "a7", "a8")) and len(r["front_steps"]["cleared"]) == 5, r["front_steps"])
cfg_audit["front_step_move_hours"] = 3
load_fixtures()
r = AR.filing_pass(now=T0, env=env(step_mark=None, step_move=None))
check("5 an environment without the item writers (the command line) does nothing", r["front_steps"]["started"] == [] and all(clock_of(k) is None for k in ("a1", "a5")) and r["fresh"] >= 1, r.get("front_steps"))
r = AR.filing_pass(now=T0, env=env(roles={}), dry=False)
check("5 an empty role map does nothing and drops no clock", r["front_steps"]["started"] == [] and r["front_steps"]["cleared"] == [], r.get("front_steps"))
run_pass(T0); marked = {k: raw(k) for k in ("a1", "a5")}
r = AR.filing_pass(now=T0 + 4 * H, env=env(), dry=True)
check("5 a dry run starts, moves and drops nothing", r["dry"] is True and all(raw(k) == v for k, v in marked.items()) and "front_steps" not in r, r.keys())
r = AR.filing_pass(now=T0 + 4 * H, env=env(roles={}), dry=False)
check("5 …and an empty role map in the middle of a clock keeps it", clock_of("a1")["at"] == T0 and all(raw(k) == v for k, v in marked.items()), clock_of("a1"))

# ---- 5b. the server's writes under their own checks
load_fixtures()
check("5b the clock write refuses a step that is not the first open one, no mover or one that is not the item's, a clock already there", server._front_step_mark("a1", "0" * 12, T0, "home-agent") is False and server._front_step_mark("a1", FS.step_hash(first_open("a1")), T0) is False
      and server._front_step_mark("a1", FS.step_hash(first_open("a1")), T0, "alpha-builder") is False and clock_of("a1") is None
      and server._front_step_mark("a1", FS.step_hash(first_open("a1")), T0, "home-agent") is True
      and server._front_step_mark("a1", FS.step_hash(first_open("a1")), T0 + 5, "home-agent") is False and clock_of("a1")["at"] == T0)
check("5b …the move refuses before its clock is due, for another opener, for a changed step; and moves nothing", server._front_step_move("a1", FS.step_hash(first_open("a1")), "alpha-main", "home-agent", 3, T0 + 3 * H - 1)["moved"] is False
      and server._front_step_move("a1", FS.step_hash(first_open("a1")), "ops-other", "home-agent", 3, T0 + 3 * H)["moved"] is False and server._front_step_move("a1", "0" * 12, "alpha-main", "home-agent", 3, T0 + 3 * H)["moved"] is False
      and opener_of("a1") == "alpha-main")
dup = get("a8"); dup["metadata"]["next"] = "alpha-main: answer the question\nhome-agent: answer the question"; put("a8", dup)
server._front_step_mark("a8", FS.step_hash(first_open("a8")), T0, "home-agent")
check("5b …and refuses a move that would make two open steps read the same", server._front_step_move("a8", FS.step_hash(first_open("a8")), "alpha-main", "home-agent", 3, T0 + 3 * H) == {"moved": False, "why": "another open step already reads the same"} and opener_of("a8") == "alpha-main")
withproof = get("a6"); withproof["metadata"]["step_proof"] = {ST.key(first_open("a6")): {"kind": "event", "event": "recycle"}}; put("a6", withproof)
server._front_step_mark("a6", FS.step_hash(first_open("a6")), T0, "home-agent")
server._front_step_move("a6", FS.step_hash(first_open("a6")), "alpha-keeper", "home-agent", 3, T0 + 3 * H)
check("5b a step with a proof keeps it: the proof follows the reworded step", list(get("a6")["metadata"]["step_proof"]) == [ST.key("home-agent: write the page entry")], get("a6")["metadata"].get("step_proof"))
check("5b the reword keeps the first line's marker and bold marks and the lines under it", FS.reopen("- **alpha-main (front):** decide it\n  note under it", "home-agent") == "- **home-agent:** decide it\n  note under it" and FS.reopen("Status: x", "home-agent") != ""
      and FS.reopen("no opener here", "home-agent") == "" and FS.reopen("alpha-main:", "home-agent") == "home-agent:", FS.reopen("- **alpha-main (front):** decide it\n  note under it", "home-agent"))

# ---- 5b2. the item changes between the pass's read and the move (the server reads it again under its lock)
def race(change, k="a1", at=T0 + 3 * H):
    """Clock the item, then let `change(item)` happen after the pass has decided (its snapshot) and before the server's move; the step text is the same."""
    load_fixtures(); run_pass(T0)
    log = []
    def racing_move(gid, *a):
        d = get(gid); change(d); put(gid, d)
        res = server._front_step_move(gid, *a); log.append(res); return res
    r = run_pass(at, step_move=racing_move)
    return r, log
def handed(d): d["metadata"]["needs"] = ["alpha-main"]
def parked(d): d["metadata"]["hold"] = True; d["metadata"]["state"] = "parked"
def waiting(d): d["metadata"]["wake"] = (dt.datetime.fromtimestamp(T0 + 3 * H + 86400, dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"); d["metadata"]["state"] = "parked"; d["metadata"]["hold"] = True
for label, change in (("handed to the opener", handed), ("parked", parked), ("put on a wait with a wake ahead", waiting)):
    r, log = race(change)
    check(f"5b2 an item {label} between the pass's read and the move is not moved, the step text unchanged", opener_of("a1") == "alpha-main" and first_open("a1") == "alpha-main: decide the wording"
          and not any(m["id"] == "board#1" for m in r["front_steps"]["moved"]) and not get("a1")["metadata"].get("stall") and not any("is now yours" in t and "board#1" in t for _to, t, _f in sent), (r["front_steps"], log, opener_of("a1")))
    check(f"5b2 …the server says why, and no message goes to the mover", bool(log) and log[0]["moved"] is False and bool(log[0]["why"]) and not any(to == "home-agent" and "is now yours" in t for to, t, _f in sent), (log, sent))
r, log = race(lambda d: d["metadata"].update({"mover": "alpha-builder", "needs": ["alpha-builder"]}))
check("5b2 an item whose mover changed in the same gap is not moved to the old mover either", opener_of("a1") == "alpha-main" and log and log[0]["moved"] is False and "mover is now" in log[0]["why"], log)
load_fixtures()
d = get("a1"); d["metadata"]["needs"] = ["alpha-main"]; put("a1", d)                                          # handed to the opener, the step text unchanged
d = get("a8"); d["metadata"]["hold"] = True; d["metadata"]["state"] = "parked"; put("a8", d)                   # parked
check("5b2 the server's clock write refuses an item handed to the opener, or parked, since the pass read it", server._front_step_mark("a1", FS.step_hash(first_open("a1")), T0, "home-agent") is False
      and server._front_step_mark("a8", FS.step_hash(first_open("a8")), T0, "home-agent") is False and clock_of("a1") is None and clock_of("a8") is None
      and server._front_step_mark("a6", FS.step_hash(first_open("a6")), T0, "home-agent") is True, (clock_of("a1"), clock_of("a8"), clock_of("a6")))

# ---- 5b3. a new mover is not handed the step minutes after it took the item
load_fixtures(); run_pass(T0)
d = get("a1"); d["metadata"]["needs"] = ["alpha-builder"]; d["metadata"]["mover"] = "alpha-builder"; put("a1", d)           # at 2h 50m the item goes to another session; the front agent's step stays first
r = run_pass(T0 + 3 * H - 600)
check("5b3 the clock restarts under the new mover (the old mover's clock is not carried over)", clock_of("a1") == {"step": FS.step_hash(first_open("a1")), "mover": "alpha-builder", "at": T0 + 3 * H - 600} and "board#1" in r["front_steps"]["started"], clock_of("a1"))
r = run_pass(T0 + 3 * H + 60)
check("5b3 …so nothing moves to it minutes after it took the item", opener_of("a1") == "alpha-main" and not any(m["id"] == "board#1" for m in r["front_steps"]["moved"]), r["front_steps"])
r = run_pass(T0 + 6 * H - 600)
check("5b3 …and it gets the step a full threshold after it took the item", opener_of("a1") == "alpha-builder" and any(m["id"] == "board#1" and m["to"] == "alpha-builder" for m in r["front_steps"]["moved"]), r["front_steps"])
check("5b3 the clock record without a mover (or another one) reads as none", FS.clock({FS.CLOCK: {"step": "x", "at": 5.0}}, "x", "home-agent") is None and FS.clock({FS.CLOCK: {"step": "x", "mover": "Home-Agent", "at": 5.0}}, "x", "home-agent") == 5.0, None)

# ---- 5b4. a clock write that fails promises no time in the finding
load_fixtures()
run_pass(T0, step_mark=lambda gid, h, now, mover="": False)
check("5b4 a clock that could not be written promises no move time: the finding keeps its plain fix line", "moves to" not in text_to("projects/alpha") and AC.FIX["stuck-elsewhere"] in text_to("projects/alpha") and clock_of("a1") is None, text_to("projects/alpha")[:300])
def boom(gid, h, now, mover=""): raise RuntimeError("write failed")
load_fixtures()
r = run_pass(T0, step_mark=boom)
check("5b4 …nor one whose write raised (the error is on the report)", "moves to" not in text_to("projects/alpha") and any("write failed" in e for e in r["front_steps"]["errors"]), (r["front_steps"], text_to("projects/alpha")[:200]))
load_fixtures(); run_pass(T0)
r = run_pass(T0 + 3 * H, step_move=lambda *a: {"moved": False, "why": "refused"})
check("5b4 …nor a step whose move was refused (its time has passed): the finding says what it said before the rule", "moves to" not in text_to("projects/alpha") and any("refused" in e for e in r["front_steps"]["errors"]), r["front_steps"])

# ---- 5c. the conditions, one by one (the pieces, not the whole pass)
load_fixtures()
res = AR.filing_pass(now=T0, env=env(), dry=True)
fnd = [f for f in res["detail"] if f["category"] == "stuck-elsewhere"]
items_ = {k: get(k) for k, _d in fixtures}
shown_ = {f"board#{k[1:]}": k for k in items_}
cand = lambda roles: FS.candidates(copy.deepcopy(fnd), items_, shown_, roles, AR.FRONT_ROLES)
base = cand(ROLES)
check("5c the covered steps are the front agent's, the keeper's and the retired session's, and no other", sorted(base) == ["a1", "a5", "a6", "a7", "a8"], sorted(base))
check("5c a background opener is not covered, even when its role is the only thing that differs", "a2" not in base and "a2" in cand({**ROLES, "ops-other": {"role": "front"}}), sorted(base))
check("5c the owner is never a front agent, whatever the role map says of his name", not FS.front_opener("Oliver", {**ROLES, "Oliver": {"role": "front"}}, AR.FRONT_ROLES) and "a3" not in cand({**ROLES, "Oliver": {"role": "front"}}), sorted(cand({**ROLES, "Oliver": {"role": "front"}})))
check("5c an item the owner moves is not covered (nobody to move the step to)", "a4" not in cand({**ROLES, "Oliver": {"role": "front"}}) and "a4" not in base, sorted(base))
check("5c a retired mover is not a place to move a step to", "a1" not in cand({**ROLES, "home-agent": {"role": "background", "retired": True}}) and "a1" in base, sorted(cand({**ROLES, "home-agent": {"role": "background", "retired": True}})))
calls = []
def counting_move(*a): calls.append(a); return {"moved": False, "why": "counted"}
load_fixtures(); run_pass(T0)
calls.clear(); run_pass(T0 + 3 * H - 60, step_move=counting_move)
check("5c the pass asks the server to move nothing before the threshold", calls == [], calls)
run_pass(T0 + 3 * H, step_move=counting_move)
check("5c …and asks it once per covered step at the threshold", sorted(c[0] for c in calls) == ["a1", "a5", "a6", "a7", "a8"], calls)
cfg_audit["front_step_move_hours"] = 0
calls.clear(); r0 = run_pass(T0 + 9 * H, step_move=counting_move)
check("5c with the threshold 0 the pass asks for no move and drops the clocks it finds", calls == [] and all(clock_of(k) is None for k in ("a1", "a5", "a6", "a7", "a8")), (calls, [clock_of(k) for k in ("a1", "a5")]))
cfg_audit["front_step_move_hours"] = 3

# ---- 6. the server's tick
load_fixtures()
msgs = []
real_msg = server._message
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (msgs.append((to, text, sender, auth, origin, fyi)), "delivered to " + to)[1]
from stackshot.anchors import anchors as _anc
real_roles = _anc.file_roles
_anc.file_roles = lambda reg=None, live=None: ROLES
cfg_audit["front_step_move_hours"] = 3
server._cfg.CFG["audit"]["enabled"] = True
res = server._filing_tick()
check("6 the server's tick starts the clocks through the writers it passes", res is not None and sorted(res["front_steps"]["started"]) == ["board#1", "board#5", "board#6", "board#7", "board#8"] and clock_of("a1") is not None, res)
d = get("a1"); d["metadata"]["stuck_since"]["at"] = time.time() - 3 * H - 5; put("a1", d)
msgs.clear()
res = server._filing_tick()
check("6 …and moves a step whose clock is due, telling the mover through the server's own message function as an fyi", [m["id"] for m in res["front_steps"]["moved"]] == ["board#1"] and opener_of("a1") == "home-agent"
      and [(m[0], m[5]) for m in msgs if "is now yours" in m[1]] == [("home-agent", True)] and all(m[2] == "stackshot audit" for m in msgs), (res["front_steps"], msgs))
server._message = real_msg; _anc.file_roles = real_roles

# ---- 7. a moved step is chased again (a far wake that is only a backstop does not silence it)
from stackshot.audit import silence as SL; from stackshot.tools import next_report as NR
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET))
def wake_in(hours): return dt.datetime.fromtimestamp(now + hours * H, ZONE).strftime("%Y-%m-%dT%H:%M")
def items_now(): return NR.load_all(T / "store")
def silent_ids(at): return [f["id"] for f in SL.findings(items_now(), at)[0]]
M = 60
def seven_fixtures(first_step="alpha-main: clear the old copy"):
    wipe_store(); clear_state()
    w = wake_in(30)
    k, d = doing(9030, f"{first_step}\nhome-agent: then rerun the drill", wake=w); put(k, d)
    k, d = doing(21, "home-agent: keep going\nhome-agent: then rerun the drill", wake=w, wait_basis={"text": "the vendor answers on that day", "wake": w, "by": "home-agent", "at": T0}); put(k, d)      # control: the same far wake, standing on a dated event: the board shows it waiting
seven_fixtures()
check("7 control: an item whose far wake stands on a dated event (a wait_basis) is not silent, however long it stands; the same wake without one is only a reminder, so its item is silent after 45 minutes",
      bid(21) not in silent_ids(T0 + 5 * H) and bid(21) not in silent_ids(T0 + 20 * H) and silent_ids(T0 + 5 * H) == [bid(9030)], (silent_ids(T0 + 5 * H), silent_ids(T0 + 20 * H)))
AR.filing_pass(now=T0, env=env()); sent.clear()
check("7 the stuck-elsewhere finding still holds on an item with a far wake (a wake on a doing item is a backstop, not a wait): the clock starts", clock_of("a9030") is not None, list(get("a9030")["metadata"]))
f7 = SL.findings(items_now(), T0 + 50 * M)[0]
check("7 a step found stuck is no longer covered by a wake: its mover is found silent after 45 minutes without activity, the evidence says why (the clock only, nothing moved yet)",
      [f["id"] for f in f7] == ["board#9030"] and "does not cover the step in hand" in f7[0]["detail"], f7)
seven_fixtures()
AR.filing_pass(now=T0, env=env()); sent.clear()
r7 = AR.filing_pass(now=T0 + 3 * H, env=env())
m20 = get("a9030")["metadata"]; moved_step = first_open("a9030")
check("7 the front-step rule moves the step to the mover", opener_of("a9030") == "home-agent" and [x["id"] for x in r7["front_steps"]["moved"]] == ["board#9030"], (r7["front_steps"], moved_step))
check("7 …and records where it landed: the reworded step's hash, the mover and the time", m20.get(FS.LANDED) == {"step": FS.step_hash(moved_step), "mover": "home-agent", "at": T0 + 3 * H}, m20.get(FS.LANDED))
check("7 …the landing is the server's bookkeeping (no writer, no activity), so the mover's silence is counted from the move, not from the item's old activity",
      get("a9030")["written_by"] == "home-agent" and SL.clock(get("a9030"), "home-agent") == T0 + 3 * H, (get("a9030")["written_by"], SL.clock(get("a9030"), "home-agent"), T0 + 3 * H))
check("7 the mover has the usual 45 minutes: nothing 44 minutes after the move, although the item's own activity is hours old", silent_ids(T0 + 3 * H + 44 * M) == [], silent_ids(T0 + 3 * H + 44 * M))
at7 = T0 + 3 * H + 50 * M
check("7 …and 50 minutes after it the item is found silent although its wake is a day away; the control standing on a dated event still is not", silent_ids(at7) == [bid(9030)], silent_ids(at7))
entered = []
sent.clear()
res = SL.silence_pass(now=at7, items=items_now(), env=env(), entered=lambda gid, who, n, detail: entered.append((gid, who, detail)))
check("7 the silence pass tells the mover (a message, no person asking) and puts the item on the ladder", res["fresh"] == 1 and [to for to, _t, _f in sent] == ["home-agent"] and bid(9030) + " · stale · no write for 50 minutes and a wake that" in sent[0][1]
      and len(entered) == 1 and entered[0][:2] == ("a9030", "home-agent") and entered[0][2].startswith("no write for 50 minutes and a wake that"), (res, sent, entered))
sent.clear()
res2 = SL.silence_pass(now=at7 + 10 * M, items=items_now(), env=env())
check("7 …once per silence: the next pass sends nothing", res2["fresh"] == 0 and res2["repeats"] == 1 and sent == [], (res2, sent))
d = get("a9030"); d["activity"] = at7 + 12 * M; put("a9030", d)
check("7 a mover who acts (activity on the item) ends it: nothing 40 minutes later", silent_ids(at7 + 52 * M) == [], silent_ids(at7 + 52 * M))
check("7 …and the next silence is counted from that write, not from the move: still quiet 44 minutes after it, found 46 minutes after it (a wake that is only a backstop covers nothing)",
      get("a9030")["metadata"].get(FS.LANDED, {}).get("step") == FS.step_hash(first_open("a9030")) and silent_ids(at7 + 12 * M + 44 * M) == [] and silent_ids(at7 + 12 * M + 46 * M) == [bid(9030)],
      (silent_ids(at7 + 12 * M + 44 * M), silent_ids(at7 + 12 * M + 46 * M)))
d = get("a9030"); d["activity"] = 0; d["metadata"]["next"] = "home-agent: done differently\nhome-agent: then rerun the drill"; put("a9030", d)
check("7 …and a reworded step has no landing record any more: the move is no longer the clock", SL.clock(get("a9030"), "home-agent") < T0 + 3 * H, SL.clock(get("a9030"), "home-agent"))
seven_fixtures()
AR.filing_pass(now=T0, env=env()); AR.filing_pass(now=T0 + 3 * H, env=env())
d = get("a9030"); d["metadata"].pop("phase", None); d["metadata"].pop("waits_on", None); d["metadata"]["next"] = f"home-agent: after {(dt.datetime.fromtimestamp(now + 30 * H, ZONE) + dt.timedelta(days=1)).strftime('%Y-%m-%d')} rerun the drill"; d["metadata"][FS.LANDED]["step"] = FS.step_hash(d["metadata"]["next"]); put("a9030", d)
check("7 a step that names a date after its wake is the wake's business: the board shows the item waiting, so it is not chased, whatever its record says", silent_ids(T0 + 9 * H) == [], silent_ids(T0 + 9 * H))
seven_fixtures()
AR.filing_pass(now=T0, env=env()); cfg_audit["front_step_move_hours"] = 0; AR.filing_pass(now=T0 + 3 * H, env=env()); cfg_audit["front_step_move_hours"] = 3
check("7 with the rule off nothing is recorded and nothing is moved, and the move is no clock", FS.LANDED not in get("a9030")["metadata"] and opener_of("a9030") == "alpha-main" and SL.clock(get("a9030"), "home-agent") < T0 + 3 * H, (list(get("a9030")["metadata"]), SL.clock(get("a9030"), "home-agent")))
seven_fixtures()
AR.filing_pass(now=T0, env=env()); AR.filing_pass(now=T0 + 3 * H, env=env())
at7b = T0 + 3 * H + 50 * M
before_off = silent_ids(at7b)
cfg_audit["front_step_move_hours"] = 0
cl_off = SL.clock(get("a9030"), "home-agent")
cfg_audit["front_step_move_hours"] = 3
check("7 the rule turned off after a move: the landing record is ignored (the move is no longer a clock), and on again it counts as before",
      before_off == [bid(9030)] and cl_off < T0 + 3 * H and SL.clock(get("a9030"), "home-agent") == T0 + 3 * H, (before_off, cl_off, SL.clock(get("a9030"), "home-agent")))

# ---- 8. an unanswered finding is sent again, then escalated, then quiet
REM = 6 * H
def eight_fixtures():
    wipe_store(); clear_state(); sent.clear()
    k, d = doing(9020, "ops-other: do the first part\nhome-agent: then the second"); put(k, d)       # a background agent's step: the finding goes to the agent itself
cfg_audit["remind_hours"] = 6
eight_fixtures()
AR.filing_pass(now=T0, env=env()); first = [t for to, t, _f in sent if to == "ops-other"]
check("8 the first send is as it always was", len(first) == 1 and "board#9020 · stuck-elsewhere · the first open step" in first[0], first)
sent.clear(); AR.filing_pass(now=T0 + REM - 60, env=env())
check("8 …and nothing follows before remind_hours", sent == [], sent)
AR.filing_pass(now=T0 + REM + 60, env=env()); second = [t for to, t, _f in sent if to == "ops-other"]
check("8 the unanswered finding is sent again after remind_hours, worded as the second try (words, not digits, so the router does not drop it as a repeat)", len(second) == 1 and "board#9020 · stuck-elsewhere · second try, no answer · " in second[0], second)
from stackshot.router import router as RT
check("8 …and the router would not take it for a repeat of the first", not RT.same_text(RT.normal_text(first[0]), RT.normal_text(second[0])), (first[0][:200], second[0][:200]))
sent.clear(); AR.filing_pass(now=T0 + REM + 10 * M, env=env())
check("8 …once per due time: the next pass is quiet", sent == [], sent)
d = get("a9020"); d["written_at"] = T0 + REM + 20 * M; d["written_by"] = "home-agent"; d["updated"] = T0 + REM + 20 * M; d["metadata"]["note"] = "a write that does not move the step"; put("a9020", d)
sent.clear(); AR.filing_pass(now=T0 + REM + 30 * M, env=env()); third = [t for to, t, _f in sent if to == "ops-other"]
check("8 a write to the item sends the finding again, counted as the third try (the tries add up while the finding stands)", len(third) == 1 and "third try, no answer" in third[0], sent)
sent.clear(); AR.filing_pass(now=T0 + 2 * REM + 31 * M, env=env())
esc = [(to, t) for to, t, _f in sent]
check("8 after the third send the finding goes once to the project's builder as unmoved, and to no one else", [to for to, _t in esc] == ["alpha-builder"] and "unmoved after 3 messages" in esc[0][1] and "chase the mover (job)" in esc[0][1], esc)
sent.clear(); AR.filing_pass(now=T0 + 2 * REM + 31 * M + 10 * M, env=env())
check("8 …nothing more is sent before the next remind_hours", sent == [], sent)
sent.clear(); AR.filing_pass(now=T0 + 3 * REM + 32 * M, env=env()); up = [(to, t) for to, t, _f in sent]
check("8 a remind_hours after the builder was told and the item still unwritten, the finding reaches the project's -main agent once, marked for the owner, the builder named as having had it",
      [to for to, _t in up] == ["alpha-main"] and up[0][1].startswith("[for Oliver]\n") and "nobody answered after 4 messages" in up[0][1] and "board#9020" in up[0][1] and "its builder after the reminders" in up[0][1], up)
sent.clear()
for k in range(1, 6): AR.filing_pass(now=T0 + 3 * REM + 32 * M + k * REM, env=env())
check("8 …and then it is quiet for good until the item is written", sent == [], sent)
check("8 the pass's record keeps the tries", [f["tries"] for f in AR.read_filing()["findings"] if f["id"] == "board#9020"] == [5], AR.read_filing()["findings"])
# the mover is the project's builder: the escalation must not land on the session that did not answer; it goes by the page key, where the router rules it
wipe_store(); clear_state(); sent.clear()
k, d = doing(9032, "ops-other: do the first part\nalpha-builder: then the second", needs=("alpha-builder",), mover="alpha-builder"); put(k, d)
tk = T0
for n in range(1, 4):
    AR.filing_pass(now=tk, env=env()); tk += REM + 60
sent.clear(); AR.filing_pass(now=tk, env=env())
esc2 = [(to, t) for to, t, _f in sent]
check("8 a mover who is the project's builder is not sent its own escalation: it goes once to the project's page key instead (unmoved, chase the mover), and to no session",
      [to for to, _t in esc2] == ["projects/alpha"] and "unmoved after 3 messages" in esc2[0][1] and "board#9032" in esc2[0][1] and not any(to == "alpha-builder" for to, _t in esc2), esc2)
sent.clear(); AR.filing_pass(now=tk + REM + 60, env=env()); up2 = [(to, t) for to, t, _f in sent]
check("8 …and a remind_hours later, still unwritten, the project's -main agent is told (marked for the owner); the builder is not told again",
      [to for to, _t in up2] == ["alpha-main"] and up2[0][1].startswith("[for Oliver]") and "board#9032" in up2[0][1], up2)
sent.clear()
for k_ in range(2, 5): AR.filing_pass(now=tk + k_ * REM, env=env())
check("8 …and then it is quiet, as for any other finding", sent == [], sent)
# a release that adds the second level sends no burst: a finding already escalated to the builder before (its record carries no level) stays quiet, one escalated by this code goes on to -main
eight_fixtures()
tk = T0
for n in range(1, 5):
    AR.filing_pass(now=tk, env=env()); tk += REM + 60
lv1 = [f.get("lvl") for f in AR.read_filing()["findings"] if f["id"] == "board#9020"]
check("8 the builder-level send is kept on the record as level 1 (and the tries as 4)", lv1 == [1] and [f["tries"] for f in AR.read_filing()["findings"] if f["id"] == "board#9020"] == [4], AR.read_filing()["findings"])
rec_old = AR.read_filing()
for f in rec_old["findings"]: f.pop("lvl", None)         # the record as the code before the second level left it: tries 4, sent long ago, no level
AR.write_pass_record(AR._filing_path(), rec_old)
sent.clear(); AR.filing_pass(now=tk, env=env())
check("8 an old finding at its fourth send (no level on its record) gets no message to the -main agent on the first pass after the release, and none later", sent == [], sent)
for k_ in range(1, 4): AR.filing_pass(now=tk + k_ * REM, env=env())
check("8 …it stays quiet until the item is written", sent == [] and [f["tries"] for f in AR.read_filing()["findings"] if f["id"] == "board#9020"] == [4], (sent, AR.read_filing()["findings"]))
eight_fixtures()
tk = T0
for n in range(1, 5):
    AR.filing_pass(now=tk, env=env()); tk += REM + 60
sent.clear(); AR.filing_pass(now=tk, env=env())
check("8 …while a finding the builder was told of by this code goes on to the -main agent, once", [to for to, _t, _f in sent] == ["alpha-main"], sent)
# a reminder or the escalation that is not reached keeps its old stamp and tries: the next pass retries that same send, not the first one
down =lambda to, text, fyi=False: (False, "[500] down")
eight_fixtures()
AR.filing_pass(now=T0, env=env()); sent.clear()
AR.filing_pass(now=T0 + REM + 60, env=env(deliver=down))
rec8 = [f for f in AR.read_filing()["findings"] if f["id"] == "board#9020"]
check("8 a reminder that is not reached keeps the finding on its first send (stamp and tries are carried into the record, not dropped)", len(rec8) == 1 and rec8[0].get("tries") == 1 and abs(rec8[0].get("sent", 0) - T0) < 120, rec8)
sent.clear(); AR.filing_pass(now=T0 + REM + 70 * M, env=env()); retry = [t for to, t, _f in sent if to == "ops-other"]
check("8 …so the next pass retries the reminder, worded as the second try (not the first send), once", len(retry) == 1 and "second try, no answer" in retry[0], sent)
tk = T0 + REM + 70 * M
tk += REM + 60; AR.filing_pass(now=tk, env=env())          # the third send
tk += REM + 60; sent.clear()
AR.filing_pass(now=tk, env=env(deliver=down))
rec8 = [f for f in AR.read_filing()["findings"] if f["id"] == "board#9020"]
check("8 an escalation that is not reached keeps the finding at its third send (tries 3), not back at the first", len(rec8) == 1 and rec8[0].get("tries") == 3, rec8)
sent.clear(); AR.filing_pass(now=tk + 10 * M, env=env()); retry2 = [(to, t) for to, t, _f in sent]
check("8 …and the escalation is retried on its own, to the builder, once", [to for to, _t in retry2] == ["alpha-builder"] and "unmoved after 3 messages" in retry2[0][1], retry2)
sent.clear(); AR.filing_pass(now=tk + 20 * M, env=env())
check("8 …then it is quiet", sent == [], sent)
tk += REM + 60; sent.clear()
AR.filing_pass(now=tk, env=env(deliver=down))
rec8 = [f for f in AR.read_filing()["findings"] if f["id"] == "board#9020"]
check("8 a message to the -main agent that is not reached keeps the finding at its fourth send (tries 4), and the next pass tries it again, once", len(rec8) == 1 and rec8[0].get("tries") == 4, rec8)
sent.clear(); AR.filing_pass(now=tk + 10 * M, env=env()); retry3 = [(to, t) for to, t, _f in sent]
check("8 …to the -main agent, marked for the owner", [to for to, _t in retry3] == ["alpha-main"] and retry3[0][1].startswith("[for Oliver]") and "nobody answered after 4 messages" in retry3[0][1], retry3)
# a finding that did not go to a builder (a front agent's step goes to the page key) has nobody above the builder's escalation: it ends there, with no message to the -main agent
cfg_audit["front_step_move_hours"] = 0
wipe_store(); clear_state(); sent.clear()
k, d = doing(9031, "alpha-main: decide the wording\nhome-agent: then build it"); put(k, d)
tk = T0
for n in range(1, 4):
    AR.filing_pass(now=tk, env=env()); tk += REM + 60
sent.clear(); AR.filing_pass(now=tk, env=env()); l1 = [(to, t) for to, t, _f in sent]; tk += REM + 60
check("8 a front agent's step: after its three sends the finding goes to the builder as unmoved, as before", [to for to, _t in l1] == ["alpha-builder"] and "board#9031" in l1[0][1], l1)
sent.clear()
for k_ in range(0, 4): AR.filing_pass(now=tk + k_ * REM, env=env())
check("8 …and nothing follows it to the -main agent (the finding never went to a builder), the record counts the step as sent", sent == [] and [f["tries"] for f in AR.read_filing()["findings"] if f["id"] == "board#9031"] == [5], (sent, AR.read_filing()["findings"]))
cfg_audit["front_step_move_hours"] = 3
cfg_audit["remind_hours"] = 0
eight_fixtures()
AR.filing_pass(now=T0, env=env()); sent.clear(); AR.filing_pass(now=T0 + 30 * H, env=env())
check("8 remind_hours 0 is the old behaviour: sent once, quiet while the item is not written", sent == [], sent)
cfg_audit["remind_hours"] = 6

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: front step move scenario, {len(ran)} checks")
