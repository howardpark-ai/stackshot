"""Scenario test for the ten-minute filing pass (audit_checks.filing_findings, audit_run.filing_pass, service/audit_ticks._filing_tick): is each open item filed in the right state? Fixture items, messages replaced by
recorders, no live store, no network, no model call.

  1  one item per filing rule: stuck-elsewhere (the first open step is someone else's), arbitrary-hold (a hold nothing explains), mislabeled-state (a stored state its fields contradict), reads-as-wait (an alive
     item whose next says it waits) are each a finding of the category and the evidence the daily run gave before the pass took them (field_findings(ten_minute=True)), which the daily run no longer makes; the broad words (when, once, after, until) are a flag and no finding; and none of these is raised
     for a clean item, a closed one, an item that already waits (its next is the record of the wait), an item idle for hours (an hourly audit line's rule) or one stale by its dates (stale is, too)
  2  the words of an alive item's next are read from next itself (audit_checks.wait_words): a precise line, the broad words only when no line reads as a wait, a negation, a waiting item, a closed one;
     the note that get carries comes from the same words (nothing is stored), and a flag stored by an older write is ignored
  3  the pass: findings go to their movers, one message per recipient, headed as a filing check; a second pass sends nothing (the same finding is not sent again while its item is unwritten) and keeps the stamps;
     a write to the item sends it again; a finding that ended and came back is sent afresh; a front agent's and an unknown mover's findings go where the daily run sends them; the record is
     <state>/audit/filing.json and is no run record (audit.runs and status do not see it); a dry run sends and writes nothing; a pass skips while a daily run is in progress
  4  the server's tick: it stands still when the audit is off or in agent mode, sends through the server's own message function as the audit's sender, and a refusal is a failed delivery

    tests/run-suite filing        → exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="filing-"); T = pathlib.Path(tmp)
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
H = 3600; now = time.time()
ZONE_HOURS = 4                                                                              # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
if min((now + ZONE_HOURS * 3600) % 86400, 86400 - (now + ZONE_HOURS * 3600) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight
ZONE = dt.timezone(dt.timedelta(hours=ZONE_HOURS)); OWNER = "00000000-0000-4000-8000-000000000001"
local = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d %H:%M")
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
def clean(i, **kw): return doing(i, 1, **kw)
def build(*pairs): return dict(pairs)
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})      # the server is never asked here
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None),
                  deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
cats = lambda fs: sorted((f["id"], f["category"]) for f in fs)

# ---- 1. one item per filing rule
FUT = local(now + 30 * H)
rules = build(
    doing(1, 1, nxt="ops-other: do the first part\nhome-agent: then the second"),                              # stuck-elsewhere
    item(2, wrote=now - H, state="parked", needs=["home-agent"], hold=True, next="home-agent: later"),                                                           # arbitrary-hold
    item(3, wrote=now - H, state="blocked", needs=["home-agent"], next="home-agent: build it"),                                                                  # mislabeled-state (blocked, nothing it waits after)
    doing(4, 1, nxt="home-agent: waiting for the build"),                                                          # reads-as-wait
    doing(5, 1, nxt="home-agent: ship it when the build is green"),                                                # the broad words: a flag
    clean(6),                                                                                                                                                    # clean
    item(7, status="completed", wrote=now - 40 * H, state="doing", needs=["home-agent"], next="home-agent: waiting for the build", outcome="done"),            # closed
    item(8, wrote=now - H, state="blocked", needs=["home-agent"], after=["a6"], next="home-agent: waiting for the build"),                                      # already waits: its next is the record of the wait
    doing(9, 8),                                                                                    # idle for 8 hours: an hourly-line matter, not a filing rule
    doing(9041, 5, wake=local(now - 2 * H)),                                                                                     # past its wake with no write since: stale is the dates pass's rule
)
fs, flags = AC.filing_findings(rules, {}, now, env())
got = cats(fs)
check("1 stuck-elsewhere: the first open step is someone else's, said as the daily run says it, to the session whose step it is",
      ("board#1", "stuck-elsewhere") in got and next(f for f in fs if f["category"] == "stuck-elsewhere")["to"] == "ops-other"
      and "the first open step is ops-other's, the item's mover is home-agent" in next(f["detail"] for f in fs if f["category"] == "stuck-elsewhere"), fs)
check("1 arbitrary-hold: a hold nothing explains is a board checks finding of that kind", any(f["id"] == "board#2" and f["category"] == "board checks" and f["detail"].startswith("arbitrary-hold: ") for f in fs), fs)
check("1 mislabeled-state: a stored state its fields contradict is a board checks finding of that kind",
      any(f["id"] == "board#3" and f["category"] == "board checks" and f["detail"].startswith("mislabeled-state: ") for f in fs), fs)
check("1 reads-as-wait: an alive item whose next says it waits, naming the line and the pattern", any(f["id"] == "board#4" and f["category"] == "reads-as-wait" and "waiting for the build" in f["detail"] for f in fs), fs)
check("1 the broad words are a flag (id, mover, the words) and no finding", flags == [{"id": "board#5", "project": "projects/alpha", "mover": "home-agent", "words": ["when"]}] and not any(f["id"] == "board#5" for f in fs), (flags, fs))
check("1 none is raised for a clean item, a closed one, one that already waits, one idle for hours or one stale by its dates",
      not any(f["id"] in ("board#6", "board#7", "board#8", "board#9", "board#9041") for f in fs), [f for f in fs if f["id"] in ("board#6", "board#7", "board#8", "board#9", "board#9041")])
check("1 every finding has the daily run's shape: id, project, owner, mover, category, detail, fix, source code", all(set(f) >= {"id", "project", "owner", "mover", "category", "detail", "fix", "source"} and f["source"] == "code" and f["fix"] for f in fs), fs)
check("1 the pass raises exactly these and no other", set(got) == {("board#1", "stuck-elsewhere"), ("board#2", "board checks"), ("board#3", "board checks"), ("board#4", "reads-as-wait")}, got)
daily, _p, _n = AC.field_findings(rules, {}, now, env(), ten_minute=True)
check("1 the daily run made the filing kinds the same way before the pass took them over (ten_minute=True: same category, same evidence, same recipient field)",
      all(any((d["id"], d["category"], d["detail"], d.get("to", "")) == (f["id"], f["category"], f["detail"], f.get("to", "")) for d in daily) for f in fs if f["category"] != "reads-as-wait"), [(f["id"], f["detail"]) for f in fs])
now_daily, _p, _n = AC.field_findings(rules, {}, now, env())
check("1 …and the daily run itself no longer makes them: no stuck-elsewhere, no arbitrary-hold, no mislabeled-state",
      not [d for d in now_daily if d["category"] == "stuck-elsewhere" or (d["category"] == "board checks" and d["detail"].startswith(("arbitrary-hold", "mislabeled-state")))]
      and [d for d in daily if d["category"] == "stuck-elsewhere"], now_daily)

# ---- 1b. stuck-elsewhere on an item the owner moves: the filing pass reads `then` as the daily run does
def owner_item(i, nxt, **kw): return item(i, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", ask="which one?", next=nxt, **kw)
owned = build(owner_item(30, "alpha-main: apply Oliver's pick, then close", then="alpha-main"),     # then named, the opener is that session
              owner_item(31, "ops-other: apply Oliver's pick, then close"),                          # no then named
              owner_item(9042, "ops-other: apply Oliver's pick, then close", then="alpha-main"))       # then named as another session
fs, _fl = AC.filing_findings(owned, {}, now, env())
check("1b an item the owner moves: the opener that is `then` (or no `then` named) is no finding, another session beside a named `then` is",
      [f["id"] for f in fs if f["category"] == "stuck-elsewhere"] == ["board#9042"], fs)
daily, _p, _n = AC.field_findings(owned, {}, now, env(), ten_minute=True)
check("1b the daily run agreed with the filing pass (ten_minute=True)", [f["id"] for f in daily if f["category"] == "stuck-elsewhere"] == ["board#9042"], daily)

# ---- 2. the words of next
alive = lambda nxt: item(20, wrote=now - H, state="doing", needs=["home-agent"], next=nxt)[1]
ww = lambda it: AC.wait_words(it, None, now)
check("2 a precise line is a hit, and the broad words are left out of the answer", ww(alive("home-agent: wait for the PR to merge, then ship it when green"))[0] and ww(alive("home-agent: wait for the PR to merge, then ship it when green"))[1] == [])
check("2 the broad words alone: when, once, after and until, each once, in the list's order", ww(alive("home-agent: ship it when green\nhome-agent: do it after the review, once built, until done"))[1] == ["when", "once", "after", "until"], ww(alive("home-agent: ship it when green\nhome-agent: do it after the review, once built, until done")))
check("2 a negation passes", ww(alive("home-agent: no waiting for a slot, run it now")) == ([], []), ww(alive("home-agent: no waiting for a slot, run it now")))
check("2 a waiting item has none (its next is the record of its wait)", ww(item(21, wrote=now - H, state="blocked", needs=["home-agent"], after=["a6"], next="home-agent: waiting for the build when it closes")[1]) == ([], []))
check("2 a closed item has none", ww(item(22, status="completed", wrote=now - H, state="doing", next="home-agent: wait for it", outcome="done")[1]) == ([], []))
from stackshot.web import server
from stackshot.service import audit_ticks as audit_ticks_svc
from stackshot.service import wait_fixes as _wait_fixes_svc
from stackshot.service import wait_gates as wait_gates_svc
from stackshot.service import messaging as _messaging
from fastmcp.exceptions import ToolError
from stackshot.web.tools import get as _wt_get
_cfg.CFG["audit"]["mode"] = "script"
(T / "store/a/30.json").write_text(json.dumps(item(30, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: ship it when the build is green")[1]))
g = _wt_get.stackshot_get("a30")
check("2 get carries the note for the broad words, read from next (the flag is stored nowhere)", "flag: next uses when, words that can hide a wait" in g and "model_flags" not in json.loads((T / "store/a/30.json").read_text())["metadata"], g[-400:])
(T / "store/a/31.json").write_text(json.dumps(item(31, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: build it now", model_flags={"next_wait_words": ["when"]})[1]))
check("2 …a flag an older write stored is ignored: no words, no note", "flag: next uses" not in _wt_get.stackshot_get("a31"))
for p in (T / "store/a").glob("*.json"): p.unlink()

# ---- 3. the pass
clear_state()
pass_items = build(*[(k, v) for k, v in rules.items() if k in ("a1", "a2", "a3", "a4", "a5", "a6")])
r1 = AR.filing_pass(now=now, items=pass_items, anchors={}, env=env())
by_to = {to: text for to, text, fyi in sent}
check("3 findings go to their movers, one message per recipient; a stuck-elsewhere one to the session whose step it is", set(by_to) == {"home-agent", "ops-other"} and len(sent) == 2 and "board#1 · stuck-elsewhere" in by_to["ops-other"]
      and sum(1 for l in by_to["home-agent"].splitlines() if l.startswith("board#")) == 4, sent)
check("3 …headed as a filing check, lines as '<id> · <check> · <evidence> · <fix>'", all(re.match(r"\[stackshot\] Filing check \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+: \d+ item\(s\) for you", t) for t in by_to.values())
      and all(len(l.split(" · ")) == 4 for t in by_to.values() for l in t.splitlines() if l.startswith("board#")), by_to)
check("3 …no message for the flag, the clean item, and none to the project's summary", not any("board#5" in t or "board#6" in t for t in by_to.values()) and not any(to == "projects/example" for to, _t, _f in sent), sent)
check("3 the result counts them", r1["findings"] == 5 and r1["fresh"] == 5 and r1["repeats"] == 0 and r1["flags"] == 1 and r1["open"] == 6 and len(r1["sent"]) == 2, r1)
fp = T / "state/audit/filing.json"
frec = json.loads(fp.read_text())
check("3 the record is <state>/audit/filing.json: findings with their sent stamps, the flags, the messages, shaped like a run record's findings",
      fp.exists() and len(frec["findings"]) == 5 and all(f.get("sent") for f in frec["findings"]) and frec["flags"][0]["id"] == "board#5" and frec["items_read"] == 6 and frec["repeats"] == 0 and len(frec["messages"]) == 2, frec)
check("3 it is no run record: runs, last and status see none of it", audit.runs() == [] and audit.last() is None and audit.status()["last"] is None)
sent.clear()
r2 = AR.filing_pass(now=now + 600, items=pass_items, anchors={}, env=env())
check("3 a second pass ten minutes on sends nothing: the same findings are not sent again while their items are unwritten", sent == [] and r2["fresh"] == 0 and r2["repeats"] == 5, (sent, r2))
frec2 = json.loads(fp.read_text())
check("3 …and the record keeps the first send's stamps", {f["id"]: f["sent"] for f in frec2["findings"]} == {f["id"]: f["sent"] for f in frec["findings"]} and frec2["repeats"] == 5, frec2["findings"])
fresher = dict(pass_items); k, d = doing(4, 1, nxt="home-agent: waiting for the build, still"); d["written_at"] = time.time() + 60; fresher[k] = d
r3 = AR.filing_pass(now=now + 1200, items=fresher, anchors={}, env=env())
check("3 a write to the item sends its finding again, and only that one", r3["fresh"] == 1 and [to for to, _t, _f in sent] == ["home-agent"] and sent[0][1].count("board#") == 1 and "board#4 · reads-as-wait" in sent[0][1], (r3, sent))
sent.clear()
gone = {k: v for k, v in pass_items.items() if k != "a2"}
AR.filing_pass(now=now + 1800, items=gone, anchors={}, env=env())
check("3 a finding that ended is dropped from the record", "board#2" not in {f["id"] for f in json.loads(fp.read_text())["findings"]} and sent == [], json.loads(fp.read_text())["findings"])
AR.filing_pass(now=now + 2400, items=pass_items, anchors={}, env=env())
check("3 …and sent afresh when it comes back", len(sent) == 1 and sent[0][0] == "home-agent" and "board#2 · board checks" in sent[0][1], sent)

# recipients: as the daily run sends them
clear_state()
front = build(item(9010, wrote=now - H, state="parked", needs=["alpha-main"], hold=True, mover="alpha-main", next="alpha-main: later"),
              item(9040, wrote=now - H, state="parked", needs=["home-nobody"], hold=True, mover="home-nobody", next="home-nobody: later"),
              item(9032, wrote=now - H, state="parked", needs=["decision"], hold=False, mover="Oliver", next="Oliver: pick"))
AR.filing_pass(now=now, items=front, anchors={}, env=env())
text_to = lambda to: "\n".join(t for t_, t, _f in sent if t_ == to)
check("3 a front agent's finding goes to the project's page key, unmarked, and not to the front agent", "board#9010" in text_to("projects/alpha") and "board#9010" not in text_to("alpha-main")
      and not text_to("projects/alpha").startswith("[for Oliver]"), sent)
check("3 …the owner's own item goes to the project's -main agent with [for Oliver] first; an unknown mover's finding goes to that name, as the daily run sends it",
      text_to("alpha-main").startswith("[for Oliver]") and "board#9032" in text_to("alpha-main") and "board#9040" in text_to("home-nobody"), sent)

# a daily run in progress, a dry run
clear_state()
(T / "state/audit/run-2026-11-03-050000.json").write_text(json.dumps({"started": now - 60, "finished": None, "findings": []}))
rs = AR.filing_pass(now=now, items=pass_items, anchors={}, env=env())
check("3 a daily run in progress: the pass skips, sends nothing and writes nothing", rs == {"skipped": "a daily run is in progress"} and sent == [] and not fp.exists(), rs)
clear_state()
rd = AR.filing_pass(now=now, items=pass_items, anchors={}, env=env(), dry=True)
check("3 a dry run lists the findings and the flags and sends and writes nothing", rd["dry"] is True and len(rd["detail"]) == 5 and len(rd["flag_detail"]) == 1 and sent == [] and not fp.exists(), rd.keys())
(T / "state/audit/run-2026-11-03-050000.json").write_text(json.dumps({"started": now - 60, "finished": None, "findings": []}))
check("3 …and a dry run is never refused for a running one", AR.filing_pass(now=now, items=pass_items, anchors={}, env=env(), dry=True)["dry"] is True)
clear_state()

# a delivery that fails is not recorded as sent: the next pass sends it again
failing = lambda to, text, fyi=False: (False, "[500] down")
AR.filing_pass(now=now, items=pass_items, anchors={}, env=env(deliver=failing))
check("3 a message no one received leaves its findings without a send stamp, so the next pass tries again", not any(f.get("sent") for f in json.loads(fp.read_text())["findings"] if f["id"] in ("board#2", "board#3", "board#4")), json.loads(fp.read_text())["findings"][:2])
sent.clear()
AR.filing_pass(now=now + 600, items=pass_items, anchors={}, env=env())
check("3 …and it is sent then", len(sent) >= 1 and sum(t.count("board#") for _to, t, _f in sent) >= 4, sent)

# ---- 4. the server's tick
clear_state()
for k, v in pass_items.items(): (T / f"store/a/{k[1:]}.json").write_text(json.dumps(v))
msgs = []
real_msg = _messaging._message
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (msgs.append((to, text, sender, auth, origin, fyi)), "delivered to " + to)[1]
_cfg.CFG["audit"]["enabled"] = False
check("4 the tick stands still while the audit is off", audit_ticks_svc._filing_tick() is None and msgs == [])
_cfg.CFG["audit"]["enabled"] = True; _cfg.CFG["audit"]["mode"] = "agent"
check("4 …and in agent mode (the rollback)", audit_ticks_svc._filing_tick() is None and msgs == [])
_cfg.CFG["audit"]["mode"] = "script"
res = audit_ticks_svc._filing_tick()
check("4 with the audit on it runs the pass over the store and sends through the server's own message function, as the audit's sender, from a script (not as a session)",
      res is not None and res["findings"] >= 3 and msgs and all(m[2] == "stackshot audit" and m[3] == "server" and m[4] == os.uname().nodename and m[5] is False for m in msgs), (res, msgs[:1]))
check("4 …the findings it sent are on the record", fp.exists() and len(json.loads(fp.read_text())["findings"]) == res["findings"] and res["sent"], res)
msgs.clear()
audit_ticks_svc._filing_tick()
check("4 the next tick sends nothing new", msgs == [])
seen_env = []
from stackshot.audit import audit_run as _AR4
real_filing_pass = _AR4.filing_pass
_AR4.filing_pass = lambda **kw: (seen_env.append(kw.get("env")), {"findings": 0})[1]
try:
    audit_ticks_svc._filing_tick()
finally:
    _AR4.filing_pass = real_filing_pass
check("4 the tick hands the pass the server's wait-end fix and facts (wait_end.py), as it hands the front-step and park functions",
      len(seen_env) == 1 and seen_env[0].wait_end is _wait_fixes_svc._wait_end_fix and seen_env[0].wait_facts is _wait_fixes_svc._wait_end_facts and seen_env[0].wake_park is _wait_fixes_svc._wake_park)
def refuse(*a, **k): raise ToolError("Refused: nobody by that name")
_messaging._message = refuse
check("4 a refusal is a failed delivery (False and the refusal's words), as the message route's 400 is", wait_gates_svc._filing_deliver("x", "t") == (False, "Refused: nobody by that name"))
_messaging._message = real_msg

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: filing scenario, {len(ran)} checks")
