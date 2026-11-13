"""Scenario test for the ten-minute silence pass (silence.findings, silence.silence_pass, server._silence_tick): has an item on an agent had no real activity for 45 minutes? Fixture items, messages
replaced by recorders, a fake clock (every pass is given its `now`), no live store, no network, no model call.

  1  the rule: an open item in the state doing, on a session, with no activity for more than 45 minutes is a `stale` finding in the daily run's wording (the time in minutes); not found: 45 minutes or less, an item the board shows
     waiting (a wake with a wait_basis, a hold with a dated wake, an item behind an open one, a stored wait), an untaken hand-off to a back agent (a front agent's is checked), the owner's or an outside party's item, a closed item, a state that is itself a
     wait; a wake alone (ahead or passed) is only a reminder and the item is found; the clock is the item's `activity` stamp, so a bare confirm and a recent `updated` do not move it; an item the idle pass poked is an idle-pass entry, no finding
  2  the pass: a finding goes to its mover, once per silence episode, headed as a silence check; a second pass sends nothing; activity on the item ends the episode and a new silence is sent afresh; a bare confirm
     and the pass's own delivery (a save while delivering) are no activity; a finding that went away with no activity (a wait filed and lifted) is not sent again; the record is <state>/audit/silence.json;
     the daily run neither sends a silence finding nor sends again what the pass sent; a dry run sends and writes nothing; the pass skips while a daily run is in progress; a message no one received is tried again
  1b the clock starts at the later of the item's activity and the moment it left a hold, a wait or an after link (an item parked 30 hours and woken is not silent for 45 minutes); spans read in hours and minutes
  2b the stall pass's view: only an item the stall ladder is already on is left alone; the pane's state (busy, shell, idle, unreadable) is never read, so a busy pane hides no silent item
  3  the server's tick (also: a background agent's shell pane is busy and a front agent's is idle; a pane view that cannot be built sends nothing): stands still when the audit is off or in agent mode, and sends through the server's own message function as the audit's sender
  4  a builder directing subagents is busy all day: its items are judged one by one by their own activity (an event on an anchored pull request counts, a bare confirm does not)
  5  a build subagent running on an item (a `work` line in progress, changed within 90 minutes, on the project builder's item) is the evidence that it is taken, whatever the pane shows; a builder's item with
     neither such a line nor an event is silent while its pane is busy; lines only defined, assigned or done, one past the bound, a non-builder's item and a project with no builder are not taken

    tests/run-suite silence       -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="silence-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.audit import silence as SL; from stackshot.waits import handoff as HO
_cfg.CFG["audit"]["pattern_review"] = "off"      # this suite holds the run to its other stages: the pattern review has its own suite (pattern_review_scenario)
H = 3600; now = time.time()
ZONE_OFFSET = 4 * H                                    # the instance timezone (the config's `timezone` above): UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight: a fixture's date words stay on one day
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET)); OWNER = "00000000-0000-4000-8000-000000000001"
local_str = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
fails = []; ran = []
bid = lambda n: f"board#{n}"                           # an item's id as the board writes it
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

def item(i, status="open", wrote=None, **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if wrote is None else wrote,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"a{i}", d
def doing(i, ago, nxt="home-agent: build it", **kw): return item(i, wrote=now - ago * H, state="doing", needs=["home-agent"], next=nxt, **kw)
def pastwake(i, wake_ago, wrote_ago, **kw):
    """A doing item whose wake was `wake_ago` hours ago and whose last write was `wrote_ago` hours ago."""
    return item(i, wrote=now - wrote_ago * H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local_str(now - wake_ago * H), **kw)
def build(*pairs): return dict(pairs)
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent, pushed = [], []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def push(to, text): pushed.append((to, text)); return True, "delivered"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})      # the server is never asked here
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None),
                  deliver=kw.pop("deliver", deliver), push=push, sessions=lambda: None, **kw)
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear(); pushed.clear()
def daily(items, at):
    """One daily run over fixture items: no suspects, so no model call."""
    sent.clear()
    return AR.run(now=at, items=items, anchors={}, env=env(), rubric="unused")
dsent = lambda: "\n".join(t for _to, t, _f in sent)


M = 60
def quiet(i, mins, **meta):
    """A doing item on a session whose last activity was `mins` minutes ago (its other clocks are recent: a bare confirm, a server save)."""
    k, d = item(i, wrote=now - M, **{"state": "doing", "needs": ["home-agent"], "next": "home-agent: build it", **meta})
    d["activity"] = now - mins * M
    return k, d

# ---- 1. the rule
OPEN_A1 = item(8, wrote=now - M, state="doing", needs=["home-agent"], next="home-agent: build it")
rules = build(
    quiet(1, 50),                                                                                       # 50 minutes silent: found
    quiet(2, 40),                                                                                       # 40 minutes: not yet
    quiet(3, 50, wake=local_str(now + 5 * H)),                                                          # a wake ahead that stands on a dated event (its wait_basis, set below): the board shows it waiting
    quiet(4, 50, wake=local_str(now - 2 * H)),                                                          # a wake passed, with no write: only a reminder, the board shows it on agent
    quiet(5, 50, hold=True, wake=local_str(now + 5 * H)),                                               # held until a dated wake: the board shows it waiting
    quiet(6, 50, state="blocked", supplies="its output", after=["a8"]),                                 # behind an open item
    quiet(7, 50, wait_kind="relay"),                                                                    # a stored wait
    OPEN_A1,                                                                                            # the open item a6 waits after
    quiet(9, 50, **{HO.KEY: HO.new_record("home-agent", "", "alpha-main", now - 50 * M)}),              # a hand-off nobody took: the hand-off audit's alone
    item(10, wrote=now - M, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick"),   # the owner's item
    item(11, status="completed", wrote=now - 40 * H, state="doing", needs=["home-agent"], next="home-agent: done", outcome="done"),   # closed
    item(12, wrote=now - M, state="parked", needs=["home-agent"], hold=True, wake=local_str(now + 3 * H), next="home-agent: later", cap_ok=True),   # a state that is itself a wait
    quiet(13, 50, mover="home-nobody-else"),                                                            # a session mover: found like a1
    quiet(14, 50, wake=local_str(now + 5 * H)),                                                         # a wake ahead and nothing else is a backstop: the board shows it on agent, so it is found
)
rules["a3"]["metadata"]["wait_basis"] = {"text": "the vendor answers on that day", "wake": rules["a3"]["metadata"]["wake"], "by": "home-agent", "at": now}
rules["a12"]["activity"] = now - 3 * H
rules["a10"]["activity"] = now - 3 * H
rules["a9"]["metadata"][HO.KEY]["taken_at"] = None
rules["a2"]["confirmed"] = now - 2 * M                                                                  # a confirm just now moves nothing
rules["a1"]["confirmed"] = now - 2 * M
fs, ps = SL.findings(rules, now, env())
got = sorted(f["id"] for f in fs)
check("1 an item silent for 50 minutes is found: stale, in the daily run's wording with the time in minutes", ("board#1" in got) and next(f["detail"] for f in fs if f["id"] == "board#1") == "no write for 50 minutes and no date of its own", fs)
check("1 …with the daily run's shape: id, project, owner, mover, category, detail, fix, source code", all(set(f) >= {"id", "project", "owner", "mover", "category", "detail", "fix", "source"} and f["source"] == "code" and f["category"] == "stale" and f["fix"] == AC.FIX["stale"] for f in fs), fs)
check("1 the limit is 45 minutes: 40 is not found, and a bare confirm two minutes ago does not keep an item fresh", SL.LIMIT == 45 * 60 and "board#2" not in got and "board#1" in got, got)
check("1 a wake with a wait_basis, a hold with a dated wake, an item behind an open one, a stored wait, an untaken hand-off: none found (the board shows each waiting, or the hand-off audit has it)",
      not any(f["id"] in (bid(3), bid(5), bid(6), bid(7), bid(9)) for f in fs), fs)
detail14 = next((f["detail"] for f in fs if f["id"] == bid(14)), "")
check("1 a wake alone, ahead (item 14) or passed (item 4), is a backstop and leaves the item on agent: found, and the evidence says the wake is only a backstop",
      {bid(4), bid(14)} <= set(got) and detail14.startswith("no write for 50 minutes and a wake kept as a hand-off's backstop, which is no wait"), fs)
check("1 the owner's item, a closed item and a state that is itself a wait: none found", not any(f["id"] in ("board#10", "board#11", "board#12") for f in fs), fs)
check("1 the pass raises exactly these and no other", got == [bid(1), bid(13), bid(14), bid(4)], got)
check("1 a finding is the daily run's `stale` finding by key (one finding to both)", all(AR.finding_key(f) == (f["id"], "stale", "") for f in fs))
nf = build(item(20, wrote=now - 3 * H, state="doing", needs=["home-agent"], next="home-agent: build it"))
nf["a20"].pop("written_at"); nf["a20"].pop("written_by"); nf["a20"]["updated"] = now - 3 * H; nf["a20"]["state_updated"] = now - 3 * H
check("1 an item saved before the activity field existed is read from its last state change or update", [f["detail"] for f in SL.findings(nf, now, env())[0]] == ["no write for 180 minutes and no date of its own"])
poked = build(quiet(21, 60)); poked["a21"]["metadata"]["idle"] = {"poked": now - 600}; poked["a21"]["confirmed"] = now - 3 * H
fs2, ps2 = SL.findings(poked, now, env())
check("1 an item the idle pass poked is an idle-pass entry and no finding, as in the daily run", fs2 == [] and [p["id"] for p in ps2] == ["board#21"] and ps2[0]["category"] == "stale", (fs2, ps2))
check("1 the daily run does not make this finding any more: no stale finding for these items (the wake of board#4 was written past)", [f["id"] for f in AC.field_findings(rules, {}, now, env())[0] if f["category"] == "stale"] == [], [f["id"] for f in AC.field_findings(rules, {}, now, env())[0] if f["category"] == "stale"])

# ---- 2. the pass
pass_items = build(*[(k, v) for k, v in rules.items() if k in ("a1", "a13")])
clear_state()
fp = T / "state/audit/silence.json"
r1 = SL.silence_pass(now=now, items=pass_items, env=env())
by_to = {to: text for to, text, fyi in sent}
ids_in = lambda t: [l.split(" · ")[0] for l in t.splitlines() if l.startswith("board#")]
check("2 the findings go to their mover, one message each, headed as a silence check, lines as '<id> · stale · <evidence> · <fix>'",
      len(sent) == 2 and {to: ids_in(t) for to, t in by_to.items()} == {"home-agent": ["board#1"], "home-nobody-else": ["board#13"]}, sent)
check("2 the message is the daily run's: a silence check head and the stale line", all(re.match(r"\[stackshot\] Silence check \d{4}-\d{2}-\d{2} \d{2}:\d{2} [+\w]+: \d+ item\(s\) for you", t) for t in by_to.values())
      and all(len(l.split(" · ")) == 4 and l.split(" · ")[1] == "stale" for t in by_to.values() for l in t.splitlines() if l.startswith("board#")), sent)
check("2 the result counts them", r1["findings"] == 2 and r1["fresh"] == 2 and r1["repeats"] == 0 and r1["open"] == 2, r1)
frec = json.loads(fp.read_text())
check("2 the record is <state>/audit/silence.json: findings with their sent stamps, and no temporary file is left",
      len(frec["findings"]) == 2 and all(f.get("sent") for f in frec["findings"]) and frec["items_read"] == 2 and frec["repeats"] == 0 and not list((T / "state/audit").glob("*.tmp")), frec)
check("2 it is no run record: runs, last and status see none of it", audit.runs() == [] and audit.last() is None and audit.status()["last"] is None)
sent.clear()
r2 = SL.silence_pass(now=now + 600, items=pass_items, env=env())
check("2 a finding is sent once per episode: a second pass ten minutes on sends nothing, and the record keeps the first send's stamps",
      sent == [] and r2["fresh"] == 0 and r2["repeats"] == 2 and {f["id"]: f["sent"] for f in json.loads(fp.read_text())["findings"]} == {f["id"]: f["sent"] for f in frec["findings"]}, (sent, r2))
sent.clear()
for n in range(2, 8): SL.silence_pass(now=now + n * 600, items=pass_items, env=env())
check("2 …and never on the passes after that, however long the item stays silent", sent == [], sent)

# activity ends the episode; the next silence is a new one
moved = {k: dict(v, metadata=dict(v["metadata"])) for k, v in pass_items.items()}
w = now + 2 * H
moved["a1"]["activity"] = w
SL.silence_pass(now=w + 600, items=moved, env=env())
check("2 activity on the item ends the finding: it is off the record and nothing is sent", "board#1" not in {f["id"] for f in json.loads(fp.read_text())["findings"]} and sent == [], (sent, json.loads(fp.read_text())["findings"]))
r3 = SL.silence_pass(now=w + 50 * M, items=moved, env=env())
check("2 …and when the item is silent again for 45 minutes it is sent afresh (a new episode)", r3["fresh"] == 1 and "board#1 · stale · no write for 50 minutes" in dsent(), (r3, sent))
sent.clear()
SL.silence_pass(now=w + 60 * M, items=moved, env=env())
check("2 …and again not twice", sent == [], sent)

# a bare confirm and a server save are no activity; the pass's own delivery is none either
clear_state()
conf = {k: dict(v, metadata=dict(v["metadata"])) for k, v in pass_items.items()}
SL.silence_pass(now=now, items=conf, env=env())
sent.clear()
conf["a1"]["confirmed"] = now + 300; conf["a1"]["updated"] = now + 300; conf["a1"]["written_at"] = now + 300
SL.silence_pass(now=now + 600, items=conf, env=env())
check("2 a bare confirm (confirmed, updated and the writer stamp move; the activity clock does not) starts no new episode", sent == [], sent)
clear_state()
win = {k: dict(v, metadata=dict(v["metadata"])) for k, v in pass_items.items()}
ticks = iter(now + n for n in range(1, 100))
def deliver_win(to, text, fyi=False):
    sent.append((to, text, fyi))
    for it in win.values(): it["activity"] = now + 1.5               # the server saved the item while delivering (between the pass's first and last clock read)
    return True, "[200] ok"
e = env(deliver=deliver_win, clock=lambda: next(ticks))
SL.silence_pass(now=now, items=win, env=e); sent.clear()
r7 = SL.silence_pass(now=now + 60 * M, items=win, env=env(deliver=deliver_win))
check("2 a save the pass's own delivery caused is no activity: the next pass finds the same episode and sends nothing", sent == [] and r7["repeats"] == 2, (sent, r7))
clear_state()
win2 = {k: dict(v, metadata=dict(v["metadata"])) for k, v in pass_items.items()}
SL.silence_pass(now=now, items=win2, env=env()); sent.clear()
for it in win2.values(): it["activity"] = time.time() + 5            # a write after the run's end is real activity
SL.silence_pass(now=now + 10 * M, items=win2, env=env())
r8 = SL.silence_pass(now=time.time() + 5 + 50 * M, items=win2, env=env())
check("2 …but activity after the pass's end is: the episode ends, and the next silence is sent afresh", r8["fresh"] == 2, (r8, sent))

# a finding that went away with no activity (a wait filed and lifted) is not sent again
clear_state()
SL.silence_pass(now=now, items=pass_items, env=env()); sent.clear()
held = {k: dict(v, metadata=dict(v["metadata"])) for k, v in pass_items.items()}
held["a1"]["metadata"]["hold"] = True; held["a1"]["metadata"]["wake"] = local_str(now + 5 * H)      # a hold the board shows waiting: held until a dated wake
SL.silence_pass(now=now + 600, items=held, env=env())
rec_held = json.loads(fp.read_text())
check("2 an item that went on hold with no activity leaves the findings, and its send stamp is carried on the record", "board#1" not in {f["id"] for f in rec_held["findings"]} and "board#1" in {f["id"] for f in rec_held.get("carried", [])} and sent == [], rec_held)
SL.silence_pass(now=now + 1200, items=pass_items, env=env())
check("2 …and when the hold is lifted the same episode goes on: nothing is sent again", sent == [] and "board#1" in {f["id"] for f in json.loads(fp.read_text())["findings"]}, sent)
gone = {k: v for k, v in pass_items.items() if k != "a1"}
SL.silence_pass(now=now + 1800, items=gone, env=env())
check("2 …and the carried stamp is dropped once the item is closed or gone", "board#1" not in {f["id"] for f in json.loads(fp.read_text()).get("carried", [])}, json.loads(fp.read_text()))

# the daily run and the pass share what they sent
clear_state()
SL.silence_pass(now=now, items=pass_items, env=env()); sent.clear()
rec = daily(pass_items, now + 5)
check("2 the daily run sends no silence finding: no stale line for a silent item with no date of its own", "board#1 · stale" not in dsent() and "board#13 · stale" not in dsent(), dsent())
clear_state()
dec = daily(pass_items, now)
check("2 …before the pass either", "board#1 · stale" not in dsent(), dsent())
sent.clear()
r5 = SL.silence_pass(now=now + 600, items=pass_items, env=env())
check("2 the pass sends the silence on its own (the daily run left it to the pass)", r5["fresh"] == 2 and "board#1 · stale" in dsent(), (r5, sent))
# a stale stamp the daily run or the dates pass left on the same key counts for the pass: one finding, once
clear_state()
(T / "state/audit/run-2026-11-03-050000.json").write_text(json.dumps({"started": now - 25 * M, "finished": now - 22 * M, "repeats": 0, "findings": [
    {"id": "board#1", "category": "stale", "sent": now - 23 * M, "sending_from": now - 24 * M, "run_started": now - 25 * M}]}))
sent.clear()
r6 = SL.silence_pass(now=now, items=pass_items, env=env())
check("2 a stale finding the daily run sent on the same item, with no activity since, is not sent again by the pass", "board#1 ·" not in dsent() and r6["repeats"] == 1 and r6["fresh"] == 1, (r6, sent))

clear_state()
(T / "state/audit/run-2026-11-03-050000.json").write_text(json.dumps({"started": now - 60, "finished": None, "findings": []}))
rs = SL.silence_pass(now=now, items=pass_items, env=env())
check("2 a daily run in progress: the pass skips, sends nothing and writes nothing", rs == {"skipped": "a daily run is in progress"} and sent == [] and not fp.exists(), rs)
rd = SL.silence_pass(now=now, items=pass_items, env=env(), dry=True)
check("2 a dry run is never refused for a running one; it lists the findings and sends and writes nothing", rd["dry"] is True and len(rd["detail"]) == 2 and sent == [] and not fp.exists() and pushed == [], rd.keys())
clear_state()
rd = SL.silence_pass(now=now, items=pass_items, env=env(), dry=True)
check("2 a dry run with no daily run in progress sends and writes nothing either, and a real pass after it still sends", rd["fresh"] == 2 and sent == [] and not fp.exists() and SL.silence_pass(now=now, items=pass_items, env=env())["fresh"] == 2 and len(sent) >= 1)
before_rec = fp.read_text(); sent.clear()
SL.silence_pass(now=now + 600, items={}, env=env(), dry=True)
check("2 a dry run leaves an existing record as it was", fp.read_text() == before_rec and sent == [])

# recipients: the daily run's for a stale finding
clear_state()
rcp = build(quiet(40, 60, mover="alpha-main", needs=["alpha-main"], next="alpha-main: go"), quiet(41, 60, mover="home-nobody", needs=["home-nobody"], next="home-nobody: go"))
SL.silence_pass(now=now, items=rcp, env=env())
text_to = lambda to: "\n".join(t for t_, t, _f in sent if t_ == to)
want = {AR.recipient(f.get("to") or f.get("mover") or "", f["project"], env(), f.get("mover") or "")[0] for f in SL.findings(rcp, now, env())[0]}
check("2 a finding goes where the daily run sends a stale finding", {to for to, _t, _f in sent} == want and "board#40" in text_to("projects/alpha") and "board#41" in text_to("home-nobody"), (sent, want))

# a delivery that fails is not recorded as sent: the next pass sends it again
clear_state()
failing = lambda to, text, fyi=False: (False, "[500] down")
SL.silence_pass(now=now, items=pass_items, env=env(deliver=failing))
check("2 a message no one received leaves its findings without a send stamp", not any(f.get("sent") for f in json.loads(fp.read_text())["findings"]), json.loads(fp.read_text())["findings"])
sent.clear()
SL.silence_pass(now=now + 600, items=pass_items, env=env())
check("2 …and it is sent then", len(sent) >= 1 and dsent().count("board#") >= 2, sent)

# ---- 1b. the clock starts when the item left its hold, wait or after link
def woke(i, parked_h, left_ago_m):
    """An item parked for `parked_h` hours (no activity since), released `left_ago_m` minutes ago by a save with no writer: only its state_updated moves."""
    k, d = quiet(i, parked_h * 60 + left_ago_m)
    d["state_updated"] = now - left_ago_m * M; d["updated"] = now - left_ago_m * M
    return k, d
w = build(woke(50, 30, 5))
check("1b an item parked 30 hours and woken five minutes ago is not silent: its 45 minutes start when it left the hold", SL.findings(w, now, env())[0] == [], SL.findings(w, now, env())[0])
check("1b …still not at 44 minutes after the wake", SL.findings(w, now + 39 * M, env())[0] == [])
late = SL.findings(w, now + 41 * M, env())[0]
check("1b …and found once 45 minutes have passed since the wake, with the span counted from the wake", [f["detail"] for f in late] == ["no write for 46 minutes and no date of its own"], late)
old = build(quiet(51, 30 * 60 + 5))
old["a51"]["state_updated"] = old["a51"]["activity"]
check("1b without a release in between the same silence is found, in hours and minutes", [f["detail"] for f in SL.findings(old, now, env())[0]] == ["no write for 30 hours 5 minutes and no date of its own"], SL.findings(old, now, env())[0])
check("1b spans: minutes up to four hours, hours and minutes past", [SL.minutes(x * M) for x in (50, 239, 240, 241, 600, 1801)] == ["50 minutes", "239 minutes", "4 hours", "4 hours 1 minute", "10 hours", "30 hours 1 minute"])
SL_w = build(woke(52, 30, 5)); clear_state()
SL.silence_pass(now=now, items=SL_w, env=env())
check("1b the pass sends nothing for the woken item that round, and a message once its 45 minutes are up", sent == [], sent)
SL.silence_pass(now=now + 41 * M, items=SL_w, env=env())
check("1b …", len(sent) == 1 and "board#52 · stale · no write for 46 minutes" in dsent(), sent)

# ---- 2b. the stall pass's view: only an item its ladder is on is left alone; no pane is read
def skip(gid, it, mover): return gid == "a13"
sk = build(quiet(10, 50), quiet(11, 50), quiet(12, 50), quiet(13, 50), quiet(21, 50))
check("2b an item the stall ladder is on is left alone, every other silent item is found (no pane state in the view)",
      [f["id"] for f in SL.findings(sk, now, env(), skip)[0]] == ["board#10", "board#11", "board#12", "board#21"], SL.findings(sk, now, env(), skip)[0])
check("2b without the view every silent item is found", len(SL.findings(sk, now, env())[0]) == 5)
def boom(gid, it, mover): raise OSError("ladder view unreadable")
check("2b a view that cannot answer leaves the item alone (fail open: nothing is sent)", SL.findings(sk, now, env(), boom)[0] == [])
clear_state()
r = SL.silence_pass(now=now, items=sk, env=env(), skip=skip)
check("2b the pass sends the four silent items, and keeps no send stamp for the ladder's", r["findings"] == 4 and len(sent) == 1 and ids_in(sent[0][1]) == ["board#10", "board#11", "board#12", "board#21"]
      and [f["id"] for f in json.loads(fp.read_text())["findings"]] == ["board#10", "board#11", "board#12", "board#21"], (r, sent))
sent.clear()
SL.silence_pass(now=now + 600, items=sk, env=env(), skip=lambda g, i, m: False)
check("2b the item the ladder let go of is found on the next round, and the four sent before are not sent again", len(sent) == 1 and ids_in(sent[0][1]) == ["board#13"], sent)

# ---- 3. the server's tick
clear_state()
from stackshot.web import server
from stackshot.service import telling
for k, v in pass_items.items(): (T / f"store/a/{k[1:]}.json").write_text(json.dumps(v))
msgs = []
real_msg = server._message
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (msgs.append((to, text, sender, auth, origin, fyi)), "delivered to " + to)[1]
panes = {}                                                           # mover -> the pane's status; the registry is read through server._handoff_status
def fake_status(who, idx=None):
    st = panes.get(who, "")
    if st == "boom": raise OSError("registry unreadable")
    return (st, now - 3600) if st else ("", 0.0)
real_status, real_active = server._handoff_status, server._stall_active
server._handoff_status = fake_status
ladder = set()
server._stall_active = lambda: set(ladder)
server._cfg.CFG["audit"]["enabled"] = False
check("3 the tick stands still while the audit is off", server._silence_tick() is None and msgs == [])
server._cfg.CFG["audit"]["enabled"] = True; server._cfg.CFG["audit"]["mode"] = "agent"
check("3 …and in agent mode (the rollback)", server._silence_tick() is None and msgs == [])
server._cfg.CFG["audit"]["mode"] = "script"
for who, st in (("home-agent", "busy"), ("home-nobody-else", "")):          # a busy pane, and a pane this box does not show
    panes[who] = st
res = server._silence_tick()
check("3 the tick finds both silent items whatever the panes show: a busy pane and a pane this box does not show hide nothing",
      res and res["findings"] == 2 and sorted(m[0] for m in msgs) == ["home-agent", "home-nobody-else"], (res, msgs))
msgs.clear(); clear_state()
panes.update({"home-agent": "boom", "home-nobody-else": "idle"})
res = server._silence_tick()
check("3 …a pane whose state cannot be read is not read at all: both items are found", res and res["findings"] == 2 and sorted(m[0] for m in msgs) == ["home-agent", "home-nobody-else"], (res, msgs))
msgs.clear(); clear_state()
panes.update({"home-agent": "idle", "home-nobody-else": "idle"}); ladder.add("a1")
res = server._silence_tick()
check("3 …but not the item the stall ladder is on", res and res["findings"] == 1 and [m[0] for m in msgs] == ["home-nobody-else"], (res, msgs))
msgs.clear(); clear_state(); ladder.clear()
panes.update({"home-agent": "shell", "home-nobody-else": "busy"})
res = server._silence_tick()
check("3 a `shell` pane (a task running) and a busy pane make no difference: both items are found", res and res["findings"] == 2 and sorted(m[0] for m in msgs) == ["home-agent", "home-nobody-else"], (res, msgs))
msgs.clear(); clear_state()
real_active_fn = server._stall_active
def no_ladder_view(): raise OSError("stall file unreadable")
server._stall_active = no_ladder_view
res = server._silence_tick()
check("3 a ladder view that cannot be built sends nothing: the tick returns without a message or a record", res is None and msgs == [] and not fp.exists(), (res, msgs))
server._stall_active = real_active_fn

# the environment the tick hands to the pass and to the backstop: spy on both, so a change in how it is built is seen
spy = {"pass": [], "backstop": []}
real_pass, real_backstop = SL.silence_pass, server._silence_backstop
SL.silence_pass = lambda **kw: (spy["pass"].append(kw.get("env")), {"findings": 0, "fresh": 0})[1]
server._silence_backstop = lambda **kw: spy["backstop"].append(kw.get("env"))
try:
    server._silence_tick()
finally:
    SL.silence_pass, server._silence_backstop = real_pass, real_backstop
pe, be = (spy["pass"] or [None])[0], (spy["backstop"] or [None])[0]
check("3 the tick builds the environment once and hands the very same one to the pass and to its backstop", len(spy["pass"]) == 1 and len(spy["backstop"]) == 1 and pe is not None and pe is be, spy)
check("3 …it sends through the filing deliver, not the default one", pe is not None and pe.deliver is server._filing_deliver, pe)
check("3 …and its `front` answers with the server's own judgement: a keeper that is not front for its own project is not front there",
      pe is not None and pe.front is not None and all(bool(pe.front(w, p)) == bool(telling.front_keeper(w, p)[0]) for w, p in (("home-agent", "home"), ("home-main", "home"), ("nobody", "")))
      , pe)
msgs.clear(); clear_state()

# ---- 4. a builder directing subagents is busy all day; its items are judged one by one
from stackshot.model import activity as ACT
def ev(i, ago_min, kind):
    """A doing item of the builder whose last write was 3 hours ago, then one more activity `ago_min` minutes ago (an event on its own anchor: a PR review, a CI run, a step proof)."""
    k, d = item(i, wrote=now - 3 * H, state="doing", needs=["home-agent"], next="home-agent: build it", project="projects/alpha")
    d["activity"] = d["state_updated"] = now - 3 * H
    if ago_min is not None: ACT.stamp(d, d, now - ago_min * M, kind)
    return k, d
busy = build(ev(1, None, ACT.EVENT),          # a PR sat unreviewed for three hours: no event, no write
             ev(2, 10, ACT.EVENT),            # an event on its anchor ten minutes ago
             ev(3, 20, ACT.WRITE),            # a write twenty minutes ago
             ev(4, 130, ACT.WRITE),           # silent for 2 hours 10 minutes
             ev(5, 5, ACT.CONFIRM))           # a bare confirm five minutes ago is no activity: still silent
busy["a5"]["confirmed"] = now - 5 * M
panes.update({"home-agent": "busy", "home-nobody-else": "busy"})
check("4 setup: the builder's pane reads busy (the registry the stall pass reads)", server._handoff_status("home-agent", {})[0] == "busy")
clear_state(); msgs.clear()
found4 = SL.findings(busy, now, env(), server._silence_skip())[0]
check("4 a busy builder's silent items are flagged: the item with no event for three hours, the one silent 2 hours 10 minutes and the one with only a bare confirm",
      [f["id"] for f in found4] == ["board#1", "board#4", "board#5"], found4)
check("4 …the item with an event ten minutes ago and the one written twenty minutes ago are not, though the pane is just as busy", not any(f["id"] in ("board#2", "board#3") for f in found4), found4)
check("4 …the evidence says how long", [f["detail"] for f in found4][:2] == ["no write for 180 minutes and no date of its own", "no write for 130 minutes and no date of its own"], found4)
r4 = SL.silence_pass(now=now, items=busy, env=env(), skip=server._silence_skip())
check("4 the pass sends them to the busy builder in one message, once; the next round sends nothing", r4["fresh"] == 3 and len(sent) == 1 and sent[0][0] == "home-agent" and ids_in(sent[0][1]) == ["board#1", "board#4", "board#5"], (r4, sent))
sent.clear()
r4b = SL.silence_pass(now=now + 600, items=busy, env=env(), skip=server._silence_skip())
check("4 …", r4b["fresh"] == 0 and r4b["repeats"] == 3 and sent == [], (r4b, sent))
ladder.add("a4"); clear_state()
check("4 an item the stall ladder is already chasing is left to it, busy builder or not", [f["id"] for f in SL.findings(busy, now, env(), server._silence_skip())[0]] == ["board#1", "board#5"])
ladder.clear()

# ---- 5. a build subagent running on the item (its `work` line) is the evidence that it is taken; a busy pane alone is not
def wl(state, ago_h, agent="home-agent"): return [{"id": "build-it", "text": "build it", "agent": agent, "state": state, "ts": now - ago_h * H}]
def sub(i, lines, mover="home-agent"):
    """A doing item of `mover` silent for 3 hours (no event, no write), carrying the given work lines."""
    k, d = ev(i, None, ACT.EVENT)
    d["metadata"]["needs"] = [mover]; d["metadata"]["next"] = f"{mover}: build it"
    if lines is not None: d["metadata"]["work"] = lines
    return k, d
real_builder = server._handoff_builder
server._handoff_builder = lambda project: ["home-agent"] if project == "projects/alpha" else []
panes.update({"home-agent": "busy", "home-nobody-else": "busy"})
subs = build(sub(1, wl("in progress", 0.5)),                    # a subagent running on it, started 30 minutes ago, nothing written since: taken
             sub(2, None),                                     # no subagent, no event, the pane is busy: silent
             sub(3, wl("assigned", 1)),                        # handed to an agent, not started: silent
             sub(4, wl("defined", 1)),                         # only defined: silent
             sub(5, wl("done", 1)),                            # finished: silent
             sub(6, wl("in progress", 2)),                     # a line left behind 2 hours ago (a recycle stops subagents): silent
             sub(7, wl("in progress", 0.5), mover="home-nobody-else"),    # not the builder's item: the line is not read, silent
             ev(9, 10, ACT.EVENT))                             # an event on its anchored pull request ten minutes ago: taken, as in section 4
found5 = SL.findings(subs, now, env(), server._silence_skip())[0]
check("5 a builder's item with a build subagent running on it (a work line in progress) is not flagged, though it has had no write for three hours",
      "board#1" not in [f["id"] for f in found5], found5)
check("5 …nor the one with an event on its anchor ten minutes ago", "board#9" not in [f["id"] for f in found5], found5)
check("5 a builder's item with neither a subagent nor an event is flagged though its pane is busy, as are lines only defined or assigned, a done one, one older than 90 minutes, and a non-builder's",
      [f["id"] for f in found5] == ["board#2", "board#3", "board#4", "board#5", "board#6", "board#7"], found5)
check("5 the rule alone: a line in progress inside the bound is a subagent running, the same line past it is not",
      SL.subagent_running(subs["a1"], now) and not SL.subagent_running(subs["a6"], now) and not SL.subagent_running(subs["a2"], now) and SL.SUBAGENT_S == 90 * M)
panes.update({"home-agent": "idle"})
check("5 …the pane's state makes no difference to a taken item: an idle pane reads the same", "board#1" not in [f["id"] for f in SL.findings(subs, now, env(), server._silence_skip())[0]])
clear_state()
r5 = SL.silence_pass(now=now, items=subs, env=env(), skip=server._silence_skip())
check("5 the pass sends the six silent items to the builder in one message and leaves the taken ones out",
      r5["fresh"] == 6 and len(sent) == 2 and sorted(ids_in(t) for _to, t, _f in sent) == [["board#2", "board#3", "board#4", "board#5", "board#6"], ["board#7"]], (r5, sent))
server._handoff_builder = lambda project: []
check("5 a project with no builder: no item is taken by a work line", "board#1" in [f["id"] for f in SL.findings(subs, now, env(), server._silence_skip())[0]])
server._handoff_builder = real_builder
panes.update({"home-agent": "busy", "home-nobody-else": "busy"})
clear_state(); msgs.clear()

msgs.clear(); clear_state()
res = server._silence_tick()
check("3 …and sends through the server's own message function, as the audit's sender, from a script (not as a session)",
      res and res["fresh"] == 2 and msgs and all(m[2] == "stackshot audit" and m[3] == "server" and m[4] == os.uname().nodename and m[5] is False for m in msgs) and any("board#1 · stale" in m[1] for m in msgs), (res, msgs[:1]))
check("3 …the findings it sent are on the record", fp.exists() and {f["id"] for f in json.loads(fp.read_text())["findings"]} == {"board#1", "board#13"})
msgs.clear()
server._silence_tick()
check("3 the next tick sends nothing new", msgs == [])
server._message = real_msg
server._handoff_status, server._stall_active = real_status, real_active

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: silence scenario, {len(ran)} checks")
