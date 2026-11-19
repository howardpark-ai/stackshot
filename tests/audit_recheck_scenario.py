"""Scenario test for what the audit model is shown of a wait, and for the send-time recheck (audit_run.stored_wait_text, recheck_fresh, already_satisfied) — fixture items with fake names, a fake `claude`
binary, messages replaced by a recorder; no live store, no network, no server.

Covers: the message of a model call shows the item's stored wait (the date it ends on, its kind, a wake, a hold) in plain words, or "none"; an older-than-page finding about a wait the item already stores
(the date the finding asks for is the stored one, the steps say another in words, the project page is newer than the last write) is dropped just before it is told, with a line on the record (`rechecked`) and in
the summary, and nobody is told; the same item with a different stored date is still told; an item that stores no wait is still told; an item that changed between the decision and the send (read again through
`Env.item_of`) drops the finding; an item that cannot be read, or whose read fails, is told as before; a kind that is not in the recheck's list is never dropped; next-done and a closed item are dropped when
the live item shows it.

    tests/run-suite audit_recheck        → exit 0 / 1"""
import json, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="auditrecheck-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit_run as AR
_cfg.CFG["audit"]["pattern_review"] = "off"
H = 3600; now = time.time()
BID = 9301; SID = f"board#{BID}"; GID = f"a{BID}"; SID7 = f"board#{BID + 6}"      # a fake item number: the shown id and the store id are made from it
OWNER = "00000000-0000-4000-8000-000000000001"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

# ---- the fake `claude`: logs what it was started with, answers as the control file says (one answer per item id)
CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
(T / "fake_claude.py").write_text(f'''import sys, os, json, re
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
open({str(CALLS)!r}, "a").write(json.dumps({{"stdin": stdin}}) + "\\n")
m = re.search(r"^Item (board#\\d+):", stdin, re.M)
ans = ctl.get("answers", {{}}).get(m.group(1) if m else "", {{"finding": "no", "check": "", "reason": "", "fix": ""}})
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_ms": 10, "duration_api_ms": 5, "num_turns": 1, "result": json.dumps(ans),
                  "total_cost_usd": 0.001, "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
''')
def fake(answers=None): CTL.write_text(json.dumps({"answers": answers or {}}))
def calls(): return [json.loads(l) for l in CALLS.read_text().splitlines()] if CALLS.exists() else []
_cfg.CFG["router"] = {"shadow": True, "command": [sys.executable, str(T / "fake_claude.py")], "timeout_seconds": 20, "login_shell": False}
YES = lambda check, reason, fix: {"finding": "yes", "check": check, "reason": reason, "fix": fix}

# ---- fixtures: fake sessions, fake items
ROLES = {"home-agent": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=kw.pop("page_of", lambda p: ("", None)), deliver=deliver, push=lambda to, text: (True, "ok"),
                  sessions=lambda: None, pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}},
                  orphans=lambda apply: {"checked": True, "applied": apply, "read": 0, "found": 0, "moved": [], "left": []}, **kw)
def parked(i, **meta):
    """An item of a fake project, parked on a session, written 3 hours ago, with a step that says a date in words."""
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": now - 3 * H, "state_updated": now - 3 * H, "confirmed": now - 3 * H,
         "written_at": now - 3 * H, "written_by": "home-agent",
         "metadata": {"owner": OWNER, "project": "projects/alpha", "state": "parked", "needs": ["home-agent"], "next": f"home-agent: answer the vendor, park this until {OLD}", **meta}}
    return f"a{i}", d
import datetime as dt
UTC = dt.timezone.utc
D0 = dt.datetime.fromtimestamp(now, UTC) + dt.timedelta(days=30)         # the day the fake wait ends: near, so a finding that names it without a year means this one
day = lambda n: D0 + dt.timedelta(days=n)
stamp = lambda d, t="": d.strftime("%Y-%m-%d") + t
say = lambda d: f"{d:%b} {d.day}th"                                          # how a finding words a day: "Mar 5th"
DAY, OTHER, LATER, OLD = say(D0), say(day(1)), say(day(7)), f"{day(-14).month}/{day(-14).day}"
FAR = D0.replace(year=D0.year + 5, day=min(D0.day, 28))
DAY_FAR = say(FAR)
STORED = {"until": stamp(D0, "T09:00"), "wait_kind": "time"}        # the wait the board holds
PAGE = lambda p: (f"- {SID} answered the vendor; parked until {DAY}\n- other line", now - H) if p == "projects/alpha" else ("", None)
ASK = YES("older-than-page", f"the page says it is parked until {DAY}; the item's steps say {OLD}", f"record the park until {DAY}")
def rec_clear():
    for p in (T / "state/audit").glob("run-*.json"): p.unlink()
    if CALLS.exists(): CALLS.unlink()
    sent.clear()
def go(items, **kw):
    rec_clear()
    for f in (T / "store/a").glob("*.json"): f.unlink()
    for gid, d in items.items(): (T / "store/a" / f"{gid[1:]}.json").write_text(json.dumps(d))       # the store the recheck reads when the environment names no `item_of`
    return AR.run(now=now, items=items, anchors={}, env=kw.pop("env_", None) or env(page_of=PAGE), rubric="rubric", store=T / "store", **kw)
told = lambda cat: [t for to, t, fy in sent if to == "home-agent" and cat in t]
oc = lambda rec: [f for f in rec["findings"] if f["category"] == "older-than-page"]
LOG = T / "state/audit/findings-log.jsonl"
log_rows = lambda: len(LOG.read_text().splitlines()) if LOG.exists() else 0

# ---- 1. what the model is shown of a wait
_, with_wait = parked(BID, **STORED, wake="2099-11-20")
_, held = parked(2, hold="waiting for the vendor", until="2099-11-24")
_, bare = parked(3)
_, same = parked(4, until="2099-11-24", wait_kind="time", wake="2099-11-24")
_, long_ = parked(5, until="2099-11-24" + "9" * 500, wake="x" * 500, wait_kind="time")
check("the stored wait reads in plain words: its date, its kind and its wake", AR.stored_wait_text(with_wait) == f"ends on {stamp(D0, 'T09:00')} · kind time · wake 2099-11-20", AR.stored_wait_text(with_wait))
check("a hold reads as a hold, with its words", AR.stored_wait_text(held) == "ends on 2099-11-24 · kind time · on hold (waiting for the vendor)", AR.stored_wait_text(held))
check("an item with no stored wait reads as none", AR.stored_wait_text(bare) == "none", AR.stored_wait_text(bare))
check("a wake that is the date the wait ends on is not said twice", AR.stored_wait_text(same) == "ends on 2099-11-24 · kind time", AR.stored_wait_text(same))
check("a long date or wake is clipped, not shown whole", len(AR.stored_wait_text(long_)) < 160, len(AR.stored_wait_text(long_)))
check("the dates a text names are read as written (ISO, month name, slash) and nothing else", AR.dates_in("on 2099-11-23 or Nov 23rd or 11/16, not 13/45 or 4/5/6") == {(2099, 11, 23), (None, 11, 23), (None, 11, 16)}, AR.dates_in("on 2099-11-23 or Nov 23rd or 11/16, not 13/45 or 4/5/6"))

# ---- 2. the item that already stores the wait: the finding is asked of the model, answered yes, and not told
fake({SID: ASK})
rec = go(dict([parked(BID, **STORED)]))
check("a model call was made and its message shows the stored wait", len(calls()) == 1 and f"Stored wait (in the item's own fields, whatever the steps say): ends on {stamp(D0, 'T09:00')} · kind time" in calls()[0]["stdin"] and "the project page" in calls()[0]["stdin"], calls())
check("the finding about a wait the item already stores is dropped at send time: nothing told, a line on the record", oc(rec) == [] and told("older-than-page") == []
      and [(d["id"], d["category"]) for d in rec.get("rechecked", [])] == [(SID, "older-than-page")] and stamp(D0, "T09:00") in rec["rechecked"][0]["why"], (rec["findings"], rec.get("rechecked"), sent))
check("the summary says how many were dropped at send time", any("1 dropped at send time" in t for to, t, fy in sent if fy), sent)

# ---- 2b. a dropped finding is no finding of the pattern review: three runs, the findings log holds no row of it
_cfg.CFG["audit"]["pattern_review"] = "shadow"
for _ in range(3):
    rec = go(dict([parked(BID, **STORED)]))
check("a dropped finding never reaches the findings log (three daily runs) and the record shows it dropped each time", log_rows() == 0 and len(rec.get("rechecked", [])) == 1 and rec["pattern_review"]["read"] == 0, (log_rows(), rec.get("rechecked"), rec.get("pattern_review")))
rec = go(dict([parked(BID, until=stamp(day(1), "T09:00"), wait_kind="time")]))
check("a finding that is told still reaches the findings log", log_rows() == 1 and [f["id"] for f in oc(rec)] == [SID], (log_rows(), rec["findings"]))
_cfg.CFG["audit"]["pattern_review"] = "off"

# ---- 3. the same item with another stored date is still told
rec = go(dict([parked(BID, until=stamp(day(1), "T09:00"), wait_kind="time")]))
check("a different stored date: the finding is told to the mover and is on the record", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1 and "rechecked" not in rec, (rec["findings"], sent))

# ---- 4. an item with no stored wait is still told
rec = go(dict([parked(BID)]))
check("no stored wait: the model's message says none", re.search(r"^Stored wait[^\n]*: none$", calls()[0]["stdin"], re.M) is not None, calls())
check("no stored wait: the finding is told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1 and "rechecked" not in rec, (rec["findings"], sent))
rec = go(dict([parked(BID, wake=stamp(D0, "T09:00"))]))
check("a wake with no wait kind and no until is no stored wait: told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1 and "rechecked" not in rec, (rec["findings"], sent))

# ---- 5. an item changed between the decision and the send
snap = dict([parked(BID)])
live = dict([parked(BID, **STORED)])
rec = go(snap, env_=env(page_of=PAGE, item_of=lambda gid: live[gid]))
check("the run read an item with no wait and the live item holds it by the send: dropped", oc(rec) == [] and told("older-than-page") == [] and len(rec.get("rechecked", [])) == 1, (rec["findings"], rec.get("rechecked"), sent))
rec = go(dict([parked(BID, **STORED)]), env_=env(page_of=PAGE, item_of=lambda gid: dict([parked(BID)])[gid]))
check("the run read the wait and the live item lost it: told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1, (rec["findings"], sent))
rec = go(snap, env_=env(page_of=PAGE, item_of=lambda gid: None))
check("a live item that cannot be read leaves the finding told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1 and "rechecked" not in rec, (rec["findings"], sent))
def boom(gid): raise OSError("store gone")
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()):
    rec = go(snap, env_=env(page_of=PAGE, item_of=boom))
check("a read that fails leaves the finding told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1, (rec["findings"], sent))
rec = go(snap, env_=env(page_of=PAGE, item_of=lambda gid: {}))
check("a live item with no status is no closed item: the finding is told", [f["id"] for f in oc(rec)] == [SID] and len(told("older-than-page")) == 1 and "rechecked" not in rec, (rec["findings"], sent))

# ---- 6. the recheck by itself: the findings it leaves alone and the other kinds it drops
by = {SID: GID}
fnd = lambda cat, detail=f"parked until {DAY}", fix=f"record the park until {DAY}": {"id": SID, "category": cat, "detail": detail, "fix": fix, "project": "projects/alpha", "mover": "home-agent", "source": "model"}
satisfied = dict([parked(BID, **STORED)])
seen = parked(BID)[1]
kept, dropped = AR.recheck_fresh(env(item_of=lambda g: satisfied[g]), {GID: seen}, by, [fnd("ask-missing"), fnd("why-not-now"), fnd("older-than-page")])
check("a kind that is not in the list is never dropped, even when the live item holds what it says", [f["category"] for f in kept] == ["ask-missing", "why-not-now"] and [d["category"] for d in dropped] == ["older-than-page"], (kept, dropped))
closed = parked(BID, **STORED)[1]; closed["status"] = "completed"
OTHERS = ("ask-missing", "wrong-needs", "unneeded-escalation", "obsolete-wait", "why-not-now", "goal-unclear", "mislabeled-state", "reads-as-wait", "wait-end", "stale", "stuck-elsewhere")
kept, dropped = AR.recheck_fresh(env(item_of=lambda g: closed), {GID: seen}, by, [fnd(c) for c in OTHERS] + [fnd("next-done"), fnd("older-than-page")])
check("with the live item closed, only the listed kinds are dropped: every other kind is told", [f["category"] for f in kept] == list(OTHERS) and sorted(d["category"] for d in dropped) == ["next-done", "older-than-page"], (kept, dropped))
other = lambda detail, fix: AR.already_satisfied(fnd("older-than-page", detail, fix), satisfied[GID], seen, D0.year)
check("the board-shaped finding (the page's date is the stored one, the steps say another) is dropped", other(f"the page says it is parked until {DAY}; the item's steps say {OLD}", f"record the park until {DAY}") != "")
check("a finding that names a change of another kind with the date is not read as a wait finding", other(f"the page says it is done, parked until {DAY}", "tick the step") == "" and other(f"the page says the mover is now someone else, parked until {DAY}", "move it") == "")
check("a finding that says the stored wait is wrong is told, however it words it", other(f"page says park until the PR merges, not until {DAY}", "change the wait") == ""
      and other(f"page says work starts now, the wait until {DAY} is off", "remove the wait") == "" and other(f"page says it was unparked; held until {DAY} per item", "unpark") == ""
      and other(f"the wait until {DAY} was lifted", "lift the hold") == "" and other(f"the wait until {DAY} is stale, wrong", "fix it") == "" and other(f"park until the review instead of {DAY}", "record it") == "")
check("a finding that names a date the item does not store, or that names no date, is not dropped", other(f"parked until {OTHER}", "record it") == "" and other("the page says it is parked", "record the park") == "")
check("a finding that names the stored date and another that the item never said is not dropped", other(f"parked until {DAY}, then until {LATER}", "record both") == "")
check("a finding that names only the date the steps already say is not dropped", other(f"the item says parked until {OLD}", "record the park") == "")
far = parked(BID, until=stamp(FAR, "T09:00"), wait_kind="time")[1]
check("a finding that names a day without a year is not the same day in a far year", AR.already_satisfied(fnd("older-than-page", f"parked until {DAY_FAR}"), far, seen, D0.year) == "" and AR.already_satisfied(fnd("older-than-page"), satisfied[GID], seen, D0.year) != "")
check("a finding that names the year too is matched on the year", AR.already_satisfied(fnd("older-than-page", f"parked until {stamp(FAR)}", "record the park"), far, seen, D0.year) != ""
      and AR.already_satisfied(fnd("older-than-page", f"parked until {stamp(FAR.replace(year=FAR.year + 1))}", "record the park"), far, seen, D0.year) == "")
with_until = parked(BID, until=stamp(D0, "T09:00"))[1]; bare_wake = parked(BID, wake=stamp(D0, "T09:00"))[1]
check("a date with no wait kind reads as a time wait and is dropped; a wake with no until and no kind stores no wait for the check", AR.already_satisfied(fnd("older-than-page"), with_until, seen, D0.year) != "" and AR.already_satisfied(fnd("older-than-page"), bare_wake, seen, D0.year) == "")
check("a finding for an item that is closed now is dropped", AR.already_satisfied(fnd("next-done"), closed, None, D0.year) == "the item is closed now" and "closed" in AR.already_satisfied(fnd("older-than-page"), closed, None, D0.year))
nostat = {"metadata": {}}
check("an item with no status key keeps its finding", AR.already_satisfied(fnd("next-done"), nostat, None, D0.year) == "" and AR.already_satisfied(fnd("older-than-page"), nostat, None, D0.year) == "")
cites = parked(BID, next=f"home-agent: wait for {SID7} to close")[1]; none = parked(BID, next="home-agent: build it")[1]
check("next-done: dropped when no open step cites an item any more, told while one does", AR.already_satisfied(fnd("next-done"), none, cites, D0.year) != "" and AR.already_satisfied(fnd("next-done"), cites, cites, D0.year) == "")

fails and print(f"{len(fails)} of {len(ran)} checks failed")
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
