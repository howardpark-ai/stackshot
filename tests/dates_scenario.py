"""Scenario test for the ten-minute dates pass (audit_checks.dates_findings, audit_run.dates_pass, server._dates_tick): has an item's own expected time passed with nobody acting? Fixture items, messages
replaced by recorders, no live store, no network, no model call.

  1  the rule: an item whose wake passed with no write since is a `stale` finding with the evidence the daily run gives; a doing item with no date of its own is never found (its quiet is the hourly audit line's), nor is a wake still ahead, a write since the wake, a closed item, an item on the owner, behind an open item or in a state that is itself a wait; a held item follows the stale rule (its wake
     ahead or no wake is no finding, its wake passed is one); an item the idle pass poked is an idle-pass entry, no finding
  2  the pass: a finding goes to the recipient the daily run sends a stale one to, once, headed as a dates check; a second pass sends nothing; a write to the item sends it again; a finding that ended and came
     back is sent afresh; the record is <state>/audit/dates.json (written atomically, no run record); the daily run no longer makes the wake half of stale, so it sends nothing for an item past its wake, and the pass does not send again what an earlier daily run sent;
     a dry run sends and writes nothing; a pass skips while a daily run is in progress; a message no one received is tried again
  3  the server's tick: the For-you look still runs (and its gate is opened); the expected-time look stands still when the audit is off or in agent mode, sends through the server's own message function as the
     audit's sender, and an error in one look never stops the other (the first is raised after both)

    tests/run-suite dates         -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="dates-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR
_cfg.CFG["audit"]["pattern_review"] = "off"      # this suite holds the run to its other stages: the pattern review has its own suite (pattern_review_scenario)
H = 3600; now = time.time()
ZONE_HOURS = 4                                                                              # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
if min((now + ZONE_HOURS * 3600) % 86400, 86400 - (now + ZONE_HOURS * 3600) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight: a fixture's date words stay on one day
ZONE = dt.timezone(dt.timedelta(hours=ZONE_HOURS)); OWNER = "00000000-0000-4000-8000-000000000001"
local = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
fails = []; ran = []
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
    return item(i, wrote=now - wrote_ago * H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(now - wake_ago * H), **kw)
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

# ---- 1. the rule
rules = build(
    pastwake(1, 2, 3),                                                                                                                                      # past its wake, no write since: found
    doing(2, 1),                                                                                                                                            # doing, no date of its own, written an hour ago
    doing(3, 30),                                                                                                                                           # doing, no date of its own, silent for 30 hours: the daily run's quiet rule
    item(4, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(now + 5 * H)),                                        # wake still ahead
    item(5, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(now - 2 * H)),                                        # wake passed, written since: somebody acted
    item(6, status="completed", wrote=now - 40 * H, state="doing", needs=["home-agent"], next="home-agent: done", outcome="done", wake=local(now - 30 * H)), # closed
    item(7, wrote=now - 3 * H, state="your-call", needs=["decision"], ask="pick one", wake=local(now - 2 * H), mover="Oliver", next="Oliver: pick"),          # on the owner
    item(8, wrote=now - 3 * H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(now - 2 * H), after=["a1"]),                      # behind an open item
    item(9, wrote=now - 3 * H, state="parked", needs=["home-agent"], hold=True, wake=local(now - 2 * H), next="home-agent: later", cap_ok=True),             # a state that is itself a wait
    item(9011, wrote=now - 3 * H, state="doing", needs=["home-agent"], hold=True, wake=local(now + 4 * H), next="home-agent: build it"),                        # held, wake ahead
    item(9014, wrote=now - 3 * H, state="doing", needs=["home-agent"], hold=True, next="home-agent: build it"),                                               # held with no wake
    item(9013, wrote=now - 3 * H, state="doing", needs=["home-agent"], hold=True, wake=local(now - 2 * H), next="home-agent: build it"),                        # held, wake passed
    item(9041, wrote=now - 3 * H, state="verifying", needs=["home-agent"], proof="it runs", end=(dt.datetime.fromtimestamp(now, ZONE) - dt.timedelta(days=2)).strftime("%Y-%m-%d"), next="home-agent: watch"),   # verifying: a state that is itself a wait
    pastwake(9020, 1, 9),                                                                                                                                     # wake passed, silent 9 hours: the idle rule's
)
fs, ps = AC.dates_findings(rules, {}, now, env())
got = sorted((f["id"], f["category"]) for f in fs)
stale_daily = lambda items, e=None: sorted((f["id"], f["detail"]) for f in AC.field_findings(items, {}, now, e or env())[0] if f["category"] == "stale")                      # what the daily run finds now
stale_before = lambda items, e=None: sorted((f["id"], f["detail"]) for f in AC.field_findings(items, {}, now, e or env(), ten_minute=True)[0] if f["category"] == "stale")      # …and what it found before the pass took the wake half
check("1 an overdue wake is found: stale, saying past its wake and the last write, as the daily run says it",
      ("board#1", "stale") in got and next(f["detail"] for f in fs if f["id"] == "board#1") == f"past its wake ({AC._stamp(now - 2 * H)}) with no write since (last write {AC._stamp(now - 3 * H)})", fs)
check("1 …with the daily run's shape: id, project, owner, mover, category, detail, fix, source code", all(set(f) >= {"id", "project", "owner", "mover", "category", "detail", "fix", "source"} and f["source"] == "code" and f["fix"] == AC.FIX["stale"] for f in fs), fs)
check("1 a doing item with no date of its own is not found, written an hour ago or silent for 30 hours", not any(f["id"] in ("board#2", "board#3") for f in fs), fs)
check("1 …nor is it the daily run's stale finding any more: the silence of an item with no date of its own is the hourly audit line's (tests/audit_hourly_scenario.py)",
      "board#3" not in {i for i, _d in stale_daily(rules)} and "board#2" not in {i for i, _d in stale_daily(rules)}, stale_daily(rules))
check("1 a wake still ahead, a write since the wake, a closed item, the owner's item, an item behind an open one, a parked or verifying state: none found",
      not any(f["id"] in ("board#4", "board#5", "board#6", "board#7", "board#8", "board#9", "board#9041") for f in fs), fs)
check("1 a held item follows the stale rule: its wake ahead and no wake are no finding, its wake passed is one", [f["id"] for f in fs if f["id"] in ("board#9011", "board#9014", "board#9013")] == ["board#9013"], fs)
check("1 an item silent 9 hours past its wake is found like any other overdue wake (no idle rule takes it first), by the pass; the daily run finds none", any(f["id"] == "board#9020" for f in fs) and "board#9020" in {i for i, _d in stale_before(rules)} and stale_daily(rules) == [], (fs, stale_before(rules), stale_daily(rules)))
check("1 the pass raises exactly these and no other", got == [("board#1", "stale"), ("board#9013", "stale"), ("board#9020", "stale")], got)
check("1 every finding of the pass is one the daily run found before the pass took it, word for word, and the daily run no longer finds any of them",
      all((f["id"], f["detail"]) in stale_before(rules) for f in fs) and not any((f["id"], f["detail"]) in stale_daily(rules) for f in fs), (fs, stale_before(rules), stale_daily(rules)))
poked = build(pastwake(9040, 2, 3)); poked["a9040"]["metadata"]["idle"] = {"poked": now - 600}
fs2, ps2 = AC.dates_findings(poked, {}, now, env())
check("1 an item the idle pass poked is an idle-pass entry and no finding, as in the daily run", fs2 == [] and [p["id"] for p in ps2] == ["board#9040"] and ps2[0]["category"] == "stale", (fs2, ps2))
it3, meta3, ao3, mv3 = AC._item_view(rules, "a3")
check("1 check_stale is the date half alone: an item with no date of its own is not stale however long it was silent",
      AC.check_stale(it3, meta3, mv3, ao3, now, now - 30 * H) == "" and not hasattr(AC, "STALE_HOURS"))
it1, meta1, ao1, mv1 = AC._item_view(rules, "a1")
check("1 …and an item with a wake of its own is stale once the wake has passed with no write since", AC.check_stale(it1, meta1, mv1, ao1, now, now - 3 * H).startswith("past its wake"))

# ---- 2. the pass
pass_items = build(*[(k, v) for k, v in rules.items() if k in ("a1", "a2", "a4", "a5", "a9013")])
clear_state()
fp = T / "state/audit/dates.json"
r1 = AR.dates_pass(now=now, items=pass_items, anchors={}, env=env())
by_to = {to: text for to, text, fyi in sent}
check("2 the findings go to their mover, one message, headed as a dates check, lines as '<id> · stale · <evidence> · <fix>'",
      set(by_to) == {"home-agent"} and len(sent) == 1 and re.match(r"\[stackshot\] Dates check \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+: 2 item\(s\) for you", by_to["home-agent"])
      and all(len(l.split(" · ")) == 4 and l.split(" · ")[1] == "stale" for l in by_to["home-agent"].splitlines() if l.startswith("board#")), sent)
check("2 the result counts them", r1["findings"] == 2 and r1["fresh"] == 2 and r1["repeats"] == 0 and r1["open"] == 5 and len(r1["sent"]) == 1, r1)
frec = json.loads(fp.read_text())
check("2 the record is <state>/audit/dates.json: findings with their sent stamps, shaped like a run record's findings, and no temporary file is left",
      len(frec["findings"]) == 2 and all(f.get("sent") for f in frec["findings"]) and frec["items_read"] == 5 and frec["repeats"] == 0 and len(frec["messages"]) == 1
      and not list((T / "state/audit").glob("*.tmp")), frec)
check("2 it is no run record: runs, last and status see none of it", audit.runs() == [] and audit.last() is None and audit.status()["last"] is None)
sent.clear()
r2 = AR.dates_pass(now=now + 600, items=pass_items, anchors={}, env=env())
check("2 a finding is sent once: a second pass ten minutes on sends nothing while the item is unwritten, and the record keeps the first send's stamps",
      sent == [] and r2["fresh"] == 0 and r2["repeats"] == 2 and {f["id"]: f["sent"] for f in json.loads(fp.read_text())["findings"]} == {f["id"]: f["sent"] for f in frec["findings"]}, (sent, r2))
# the item is written (its wake moved ahead): the finding ends; the new wake passes with no write since, and it is sent again
w = time.time()
moved = dict(pass_items); k, d = pastwake(1, 0, 0); d["written_at"] = w + 60; d["updated"] = w + 60; d["metadata"]["wake"] = local(w + 30 * 60); moved[k] = d
AR.dates_pass(now=w + 600, items=moved, anchors={}, env=env())
check("2 a write that moves the wake ahead ends the finding: it is off the record and nothing is sent", "board#1" not in {f["id"] for f in json.loads(fp.read_text())["findings"]} and sent == [], (sent, json.loads(fp.read_text())["findings"]))
r3 = AR.dates_pass(now=w + 3 * H, items=moved, anchors={}, env=env())
check("2 …and when the new wake passes with no write since, it is sent again, because the item was written since the first send", r3["fresh"] >= 1 and "board#1 · stale" in dsent(), (r3, sent))
sent.clear()
AR.dates_pass(now=w + 3 * H + 600, items=moved, anchors={}, env=env())
check("2 …and again not twice", sent == [], sent)

# a finding that ended and came back with its item unwritten: fresh, as the filing pass does when the daily record keeps no stamp
clear_state()
AR.dates_pass(now=now, items=pass_items, anchors={}, env=env())
gone = {k: v for k, v in pass_items.items() if k != "a9013"}
sent.clear()
AR.dates_pass(now=now + 600, items=gone, anchors={}, env=env())
check("2 a finding that ended is dropped from the record", "board#9013" not in {f["id"] for f in json.loads(fp.read_text())["findings"]} and sent == [], json.loads(fp.read_text())["findings"])
AR.dates_pass(now=now + 1200, items=pass_items, anchors={}, env=env())
check("2 …and sent afresh when it comes back", len(sent) == 1 and "board#9013 · stale" in sent[0][1] and "board#1 · stale" not in sent[0][1], sent)

# recipients: the daily run's for a stale finding (the mover's session; an unknown mover's name; a front agent's page key)
clear_state()
rcp = build(item(9012, wrote=now - 3 * H, state="doing", needs=["alpha-main"], mover="alpha-main", next="alpha-main: go", wake=local(now - 2 * H)),
            item(9010, wrote=now - 3 * H, state="doing", needs=["home-nobody"], mover="home-nobody", next="home-nobody: go", wake=local(now - 2 * H)))
AR.dates_pass(now=now, items=rcp, anchors={}, env=env())
text_to = lambda to: "\n".join(t for t_, t, _f in sent if t_ == to)
d_fs = AC.field_findings(rcp, {}, now, env(), ten_minute=True)[0]
want = {AR.recipient(f.get("to") or f.get("mover") or "", f["project"], env(), f.get("mover") or "")[0] for f in d_fs if f["category"] == "stale"}
check("2 a finding goes where the daily run sent the same stale finding (before the pass took it)", {to for to, _t, _f in sent} == want and "board#9012" in text_to("projects/alpha") and "board#9010" in text_to("home-nobody"), (sent, want))

# the daily run no longer makes the wake half: the pass alone sends it, and the pass keeps the stamps of a send an earlier daily run made
clear_state()
share = build(pastwake(1, 2, 3), doing(2, 1))
AR.dates_pass(now=now, items=share, anchors={}, env=env())
sent.clear()
rec = daily(share, now + 5)
check("2 the daily run sends no stale line for an item past its wake, whether or not the pass sent it, and its record has none", "board#1 · stale" not in dsent() and rec["repeats"] == 0 and not [f for f in rec["findings"] if f["category"] == "stale"], (dsent(), rec["findings"]))
clear_state()
silent = build(doing(3, 30))
sent.clear(); AR.run(now=now, items=silent, anchors={}, env=env(), rubric="unused")
check("2 the daily run no longer sends the silence of an item with no date of its own (the hourly audit line's)", "board#3" not in dsent(), dsent())
clear_state()
rec = daily(share, now)
sent.clear()
r5 = AR.dates_pass(now=now + 600, items=share, anchors={}, env=env())
check("2 the pass sends the overdue wake once, with the text the daily run gave it", r5["fresh"] == 1 and r5["repeats"] == 0 and "board#1 · stale · past its wake" in dsent()
      and dict(stale_before(share)).get("board#1", "?") in dsent(), (sent, r5))
sent.clear()
r5b = AR.dates_pass(now=now + 1200, items=share, anchors={}, env=env())
check("2 …and not again while the item is unwritten", sent == [] and r5b["repeats"] == 1 and r5b["fresh"] == 0, (sent, r5b))
# a send an earlier daily run made (a record from before the pass took the wake half over) still counts: the pass does not send it a second time
clear_state()
real_ff = AR.field_findings
AR.field_findings = lambda *a, **k: real_ff(*a, **{**k, "ten_minute": True})
try: daily(share, now)
finally: AR.field_findings = real_ff
sent.clear()
r5c = AR.dates_pass(now=now + 600, items=share, anchors={}, env=env())
check("2 …an earlier daily run's send counts: the pass sends nothing for the item it already reached", sent == [] and r5c["repeats"] == 1 and r5c["fresh"] == 0, (sent, r5c))
fresher = dict(share); fresher["a1"] = {**fresher["a1"], "written_at": time.time() + 60, "written_by": "home-agent"}
fresher["a1"]["metadata"] = {**fresher["a1"]["metadata"], "wake": local(time.time() + 120)}
sent.clear()
r6 = AR.dates_pass(now=time.time() + 4 * H, items=fresher, anchors={}, env=env())
check("2 …but an item written since that send is sent again by the pass", r6["fresh"] == 1 and "board#1 · stale" in dsent(), (r6, sent))

# a daily run in progress, a dry run
clear_state()
(T / "state/audit/run-2026-11-03-050000.json").write_text(json.dumps({"started": now - 60, "finished": None, "findings": []}))
rs = AR.dates_pass(now=now, items=pass_items, anchors={}, env=env())
check("2 a daily run in progress: the pass skips, sends nothing and writes nothing", rs == {"skipped": "a daily run is in progress"} and sent == [] and not fp.exists(), rs)
rd = AR.dates_pass(now=now, items=pass_items, anchors={}, env=env(), dry=True)
check("2 a dry run is never refused for a running one; it lists the findings and sends and writes nothing", rd["dry"] is True and len(rd["detail"]) == 2 and sent == [] and not fp.exists() and pushed == [], rd.keys())
clear_state()
rd = AR.dates_pass(now=now, items=pass_items, anchors={}, env=env(), dry=True)
check("2 a dry run with no daily run in progress sends and writes nothing either, and a real pass after it still sends", rd["fresh"] == 2 and sent == [] and not fp.exists() and AR.dates_pass(now=now, items=pass_items, anchors={}, env=env())["fresh"] == 2 and len(sent) == 1)
AR.dates_pass(now=now, items=pass_items, anchors={}, env=env()); before_rec = fp.read_text(); sent.clear()
AR.dates_pass(now=now + 600, items={}, anchors={}, env=env(), dry=True)
check("2 a dry run leaves an existing record as it was", fp.read_text() == before_rec and sent == [])

# a delivery that fails is not recorded as sent: the next pass sends it again
clear_state()
failing = lambda to, text, fyi=False: (False, "[500] down")
AR.dates_pass(now=now, items=pass_items, anchors={}, env=env(deliver=failing))
check("2 a message no one received leaves its findings without a send stamp", not any(f.get("sent") for f in json.loads(fp.read_text())["findings"]), json.loads(fp.read_text())["findings"])
sent.clear()
AR.dates_pass(now=now + 600, items=pass_items, anchors={}, env=env())
check("2 …and it is sent then", len(sent) == 1 and dsent().count("board#") >= 2, sent)

# ---- 3. the server's tick
clear_state()
from stackshot.web import server
for k, v in pass_items.items(): (T / f"store/a/{k[1:]}.json").write_text(json.dumps(v))
msgs = []
real_msg = server._message
server._message = lambda to, text, sender, auth="", origin="", fyi=False: (msgs.append((to, text, sender, auth, origin, fyi)), "delivered to " + to)[1]
server._cfg.CFG["audit"]["enabled"] = False
check("3 the expected-time look stands still while the audit is off", server._dates_expected_tick() is None and msgs == [])
server._cfg.CFG["audit"]["enabled"] = True; server._cfg.CFG["audit"]["mode"] = "agent"
check("3 …and in agent mode (the rollback)", server._dates_expected_tick() is None and msgs == [])
server._cfg.CFG["audit"]["mode"] = "script"
server._FORYOU_LAST[0] = time.time() + 1e6              # the For-you look's own gate is shut …
res = server._dates_tick()
check("3 the dates pass still opens the For-you look's gate, so the look runs every ten minutes", server._FORYOU_LAST[0] < time.time() + 1000 and res == [], server._FORYOU_LAST[0])
check("3 …and its expected-time look sends through the server's own message function, as the audit's sender, from a script (not as a session)",
      msgs and all(m[2] == "stackshot audit" and m[3] == "server" and m[4] == os.uname().nodename and m[5] is False for m in msgs) and any("board#1 · stale" in m[1] for m in msgs), msgs[:1])
check("3 …the findings it sent are on the record", fp.exists() and {f["id"] for f in json.loads(fp.read_text())["findings"]} >= {"board#1", "board#9013"})
msgs.clear()
server._dates_tick()
check("3 the next tick sends nothing new", msgs == [])
real_fy, real_ex = server._foryou_tick, server._dates_expected_tick
ran_log = []
server._foryou_tick = lambda *a, **k: (ran_log.append("foryou"), ["a1"])[1]
server._dates_expected_tick = lambda: ran_log.append("expected")
check("3 the tick returns the For-you look's gids and runs both looks", server._dates_tick() == ["a1"] and ran_log == ["foryou", "expected"], ran_log)
def boom(*a, **k): ran_log.append("foryou"); raise RuntimeError("for-you broke")
server._foryou_tick = boom; ran_log.clear()
try: server._dates_tick(); err = None
except RuntimeError as e: err = str(e)
check("3 an error in the For-you look does not stop the expected-time look, and is raised after it (the runner records it)", ran_log == ["foryou", "expected"] and err == "for-you broke", (ran_log, err))
def boom2(): ran_log.append("expected"); raise RuntimeError("dates broke")
server._foryou_tick = lambda *a, **k: (ran_log.append("foryou"), [])[1]; server._dates_expected_tick = boom2; ran_log.clear()
try: server._dates_tick(); err = None
except RuntimeError as e: err = str(e)
check("3 …and an error in the expected-time look is raised too, after the For-you look has run", ran_log == ["foryou", "expected"] and err == "dates broke", (ran_log, err))
server._foryou_tick, server._dates_expected_tick = real_fy, real_ex
server._message = real_msg

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: dates scenario, {len(ran)} checks")
