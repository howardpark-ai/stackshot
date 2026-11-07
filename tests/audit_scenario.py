"""Scenario test for the server side of the daily board audit (audit.py) on a temp state
dir — a fixed clock, the push replaced by a recorder, no live store, no network.

Covers: runs / running / last on the run records (newest first, a date added from the file name, a broken file skipped; an
unfinished record younger than two hours is running, an older one is a crashed run); status's shape, with the record's times as
epoch seconds whether the record holds numbers or ISO-8601 strings (an offset, a trailing Z, none; unreadable ones null); next_run before, at and
after today's run time, and None when the audit is off; cue → 409 while a run is in progress, 404 when [audit] enabled is
false, 202 when push.py delivers, 503 when it does not (push.py's answer in the text), every cue logged to cues.jsonl; the
push goes through push.py as the message source; the CLI (`cue`, `status`); and over HTTP in-process, POST /audit/now and
GET /audit/status (405 for any other method on /audit/now, the board's sign-in in front of both when ui_open is false).

[audit] at as one "HH:MM" string or a list of them (config.audit_at: sorted, once each, bad entries left out, default 05:00) and next_run over two times a day.

    tests/run-suite audit        → exit 0 / 1"""
import datetime as dt, json, os, re, subprocess, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="audittest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1    # Oliver's instance: on
toml, n = re.subn(r'(?m)^mode = "script"', 'mode = "agent"', toml); assert n == 1    # this suite covers the agent-cue path (the rollback); tests/audit_run_scenario.py covers the script mode
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("1")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))

import config, audit
config.CFG["audit"]["at"] = "05:00"          # the example ships a list of two times; sections 1 to 3 are the once-a-day schedule, the list has its own section 3c
ZONE_HOURS = 4; ZONE = dt.timezone(dt.timedelta(hours=ZONE_HOURS))     # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
OFFSET = f"+{ZONE_HOURS:02d}:00"; ABBR = f"+{ZONE_HOURS:02d}"             # an ISO offset, and the zone's own abbreviation as the audit prints it after a clock time
def at(y, mo, d, h, mi=0): return dt.datetime(y, mo, d, h, mi, tzinfo=ZONE).timestamp()
T0 = at(2026, 10, 5, 6)                                  # Mon Oct 5th 2026, 06:00 local time
D = T / "state/audit"
def rec(date, **kw): (D / f"run-{date}.json").write_text(json.dumps(kw) if not isinstance(kw.get("raw"), str) else kw["raw"], encoding="utf-8")
pushed = []
def recorder(ok, said): return lambda agent, text: (pushed.append((agent, text)), (ok, said))[1]

# ---- 1. no records yet
check("state_dir: <paths.state>/audit, made on first use", not D.exists() and audit.state_dir() == D and D.is_dir())
check("no records: runs, last and running are empty", audit.runs() == [] and audit.last() is None and audit.running(T0) is None)
st = audit.status(T0)
check("status with no records: the shape, nothing running, no last run", st == {"enabled": True, "agent": "falcon-audit", "running": False, "running_since": None,
                                                                           "last": None, "next": at(2026, 10, 6, 5)}, st)

# ---- 2. the run records
F1 = [{"id": "s1", "project": "projects/a", "owner": "home-a", "category": "stale"}, {"id": "s2", "project": "projects/b", "owner": "home-b", "category": "no-ask"}]
rec("2026-10-03", started=at(2026, 10, 3, 5), finished=at(2026, 10, 3, 5, 20), items_read=40, findings=F1[:1], by_session={"home-a": 1}, by_category={"stale": 1})
rec("2026-10-04", started=at(2026, 10, 4, 5), finished=at(2026, 10, 4, 5, 25), items_read=42, findings=F1, by_session={"home-a": 1, "home-b": 1}, by_category={"stale": 1, "no-ask": 1})
rec("2026-10-02", raw="{not json")
rec("2026-10-01", raw="[1, 2]")
(D / "run-latest.json").write_text("{}")
r = audit.runs()
check("runs: newest first, each with its date from the file name; broken files skipped", [x["date"] for x in r] == ["2026-10-04", "2026-10-03"] and r[0]["items_read"] == 42, r)
check("runs(limit=1): the newest only", [x["date"] for x in audit.runs(limit=1)] == ["2026-10-04"])
check("last: the newest record", (audit.last() or {}).get("date") == "2026-10-04")
check("finished records only: nothing running", audit.running(T0) is None)
rec("2026-10-05", started=at(2026, 10, 5, 5), finished=None, items_read=10, findings=F1[1:], by_session={"home-b": 1}, by_category={"no-ask": 1})
run = audit.running(T0)
check("an unfinished record an hour old is running", run is not None and run["date"] == "2026-10-05", run)
check("…still at 1:59 old", audit.running(at(2026, 10, 5, 6, 59)) is not None)
check("…but at two hours old it is a crashed run, not a running one", audit.running(at(2026, 10, 5, 7)) is None and audit.running(at(2026, 10, 5, 9)) is None)
check("last: the record in progress is the newest", (audit.last() or {}).get("date") == "2026-10-05")
st = audit.status(T0)
check("status: running since its start, the last run in brief with its findings as a count",
      st["running"] is True and st["running_since"] == at(2026, 10, 5, 5) and st["last"] == {"date": "2026-10-05", "started": at(2026, 10, 5, 5), "finished": None,
      "items_read": 10, "findings": 1, "by_category": {"no-ask": 1}, "by_session": {"home-b": 1}} and set(st) == {"enabled", "agent", "running", "running_since", "last", "next"}, st)
check("status is JSON", json.loads(json.dumps(st)) == st)

# ---- 3. next_run
check("next_run before today's run time: today at 05:00", audit.next_run(at(2026, 10, 5, 4, 59)) == at(2026, 10, 5, 5))
check("next_run at the run time: tomorrow's", audit.next_run(at(2026, 10, 5, 5)) == at(2026, 10, 6, 5))
check("next_run after it: tomorrow at 05:00", audit.next_run(at(2026, 10, 5, 23, 30)) == at(2026, 10, 6, 5))
config.CFG["audit"]["at"] = "22:30"
check("[audit] at = 22:30: tonight", audit.next_run(T0) == at(2026, 10, 5, 22, 30))
config.CFG["audit"]["at"] = "nonsense"
check("[audit] at that is no time of day: 05:00", audit.next_run(at(2026, 10, 5, 4)) == at(2026, 10, 5, 5))
config.CFG["audit"]["at"] = "05:00"
config.CFG["audit"]["enabled"] = False
check("next_run when the audit is off: None", audit.next_run(T0) is None and audit.status(T0)["next"] is None and audit.status(T0)["enabled"] is False)
config.CFG["audit"]["enabled"] = True

# ---- 3a. [audit] at: one "HH:MM" string or a list of them (config.audit_at)
def at_of(v):
    config.CFG["audit"]["at"] = v
    return config.audit_at()
check("audit_at, one string: that time, as a list of one", at_of("05:00") == ["05:00"] and at_of("22:30") == ["22:30"] and at_of("7:05") == ["07:05"])
check("audit_at, a list: the times, sorted, each HH:MM", at_of(["20:00", "05:00"]) == ["05:00", "20:00"] and at_of(["05:00", "20:00"]) == ["05:00", "20:00"])
check("audit_at, a list: a repeat counts once, a one-digit hour is padded", at_of(["20:00", "20:00", "5:00"]) == ["05:00", "20:00"])
check("audit_at, a list with an entry that is no time of day: that entry is left out", at_of(["05:00", "25:99", "later", 5, ""]) == ["05:00"])
check("audit_at, a list of one: the same as the string", at_of(["06:30"]) == at_of("06:30") == ["06:30"])
check("audit_at, nothing usable (garbage string, empty list, empty string, a number, a table): the default 05:00",
      all(at_of(v) == ["05:00"] for v in ("nonsense", "25:99", [], "", ["x", "99:99"], 5, {"a": "06:00"})))
del config.CFG["audit"]["at"]
check("audit_at, the key absent: the default 05:00", config.audit_at() == ["05:00"])
config.CFG["audit"]["at"] = "05:00"
ex = config.tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
check("the shipped example: at = [\"05:00\", \"20:00\"]", ex["audit"]["at"] == ["05:00", "20:00"], ex["audit"].get("at"))

# ---- 3c. next_run with two times a day (05:00 and 20:00)
config.CFG["audit"]["at"] = ["05:00", "20:00"]
check("two times, before the first: today 05:00", audit.next_run(at(2026, 10, 5, 4, 59)) == at(2026, 10, 5, 5))
check("two times, at the first: today 20:00", audit.next_run(at(2026, 10, 5, 5)) == at(2026, 10, 5, 20))
check("two times, between them: today 20:00", audit.next_run(at(2026, 10, 5, 12)) == at(2026, 10, 5, 20))
check("two times, at the second: tomorrow 05:00", audit.next_run(at(2026, 10, 5, 20)) == at(2026, 10, 6, 5))
check("two times, after the second: tomorrow 05:00", audit.next_run(at(2026, 10, 5, 23, 30)) == at(2026, 10, 6, 5))
check("two times, listed the other way round: the same", (config.CFG["audit"].__setitem__("at", ["20:00", "05:00"]), audit.next_run(at(2026, 10, 5, 12)))[1] == at(2026, 10, 5, 20))
check("two times: status reports the soonest as `next`", audit.status(at(2026, 10, 5, 12))["next"] == at(2026, 10, 5, 20))
config.CFG["audit"]["at"] = "05:00"

# ---- 3b. the agent writes its times as ISO-8601 strings: status gives epoch seconds either way
E1, E2 = at(2026, 10, 20, 5), at(2026, 10, 20, 5, 10)
rec("2026-10-20", started=f"2026-10-20T05:00{OFFSET}", finished=f"2026-10-20T05:10{OFFSET}", items_read=5, findings=F1[:1], by_category={"stale": 1})
st = audit.status(at(2026, 10, 20, 12))
check("status: ISO started and finished (with an offset) come back as the same epoch seconds a number gives, floats", st["last"]["started"] == E1 and st["last"]["finished"] == E2
      and isinstance(st["last"]["started"], float) and not st["running"] and st["running_since"] is None, st)
utc = lambda ep: dt.datetime.fromtimestamp(ep, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")      # the same two instants as UTC strings
rec("2026-10-20", started=utc(E1), finished=utc(E2), items_read=5, findings=[])
st = audit.status(at(2026, 10, 20, 12))
check("status: a trailing Z is UTC", st["last"]["started"] == E1 and st["last"]["finished"] == E2, st)
rec("2026-10-20", started="2026-10-20T05:00:00", finished="2026-10-20T05:10:00", items_read=5, findings=[])
st = audit.status(at(2026, 10, 20, 12))
check("status: a string with no offset is read in the instance timezone", st["last"]["started"] == E1 and st["last"]["finished"] == E2, st)
rec("2026-10-20", started=E1, finished=f"2026-10-20T05:10{OFFSET}", items_read=5, findings=[])
st = audit.status(at(2026, 10, 20, 12))
check("status: a number and an ISO string in one record", st["last"]["started"] == E1 and st["last"]["finished"] == E2, st)
for bad in ("yesterday", "", "  ", f"2026-13-45T00:00{OFFSET}", True, [], {}, "nan", float("inf")):
    rec("2026-10-20", started=bad, finished=bad, items_read=5, findings=[])
    st = audit.status(at(2026, 10, 20, 12))
    check(f"status: a time that cannot be read ({bad!r}) is null, never an error", st["last"]["started"] is None and st["last"]["finished"] is None and st["running"] is False, st)
rec("2026-10-20", started=f"2026-10-20T05:00{OFFSET}", finished=None, items_read=5, findings=[])
st = audit.status(at(2026, 10, 20, 6))
check("status: a run in progress with an ISO start is running, since its epoch; finished stays null",
      st["running"] is True and st["running_since"] == E1 and st["last"]["started"] == E1 and st["last"]["finished"] is None, st)
check("cue while that run is in progress: 409 with its start time, not an error", audit.cue("button", at(2026, 10, 20, 6)) == (409, f"an audit is running since 2026-10-20 05:00 {ABBR}") and pushed == [], pushed)
(D / "cues.jsonl").unlink()                              # the section 4 checks below count the cues from none
st = audit.status(at(2026, 10, 20, 8))
check("status: an ISO start two hours old is a crashed run: not running, started kept, finished null", st["running"] is False and st["running_since"] is None
      and st["last"]["started"] == E1 and st["last"]["finished"] is None, st)
check("status with ISO times is JSON", json.loads(json.dumps(st)) == st)
(D / "run-2026-10-20.json").unlink()

# ---- 4. cue
audit._push = recorder(True, "delivered → falcon-audit")
check("cue while a run is in progress: 409 with its start time, nothing pushed",
      audit.cue("button", T0) == (409, f"an audit is running since 2026-10-05 05:00 {ABBR}") and pushed == [], pushed)
T1 = at(2026, 10, 5, 8)                                  # the 05:00 record is three hours old now: a crashed run
config.CFG["audit"]["enabled"] = False
check("cue when [audit] enabled is false: 404, nothing pushed", audit.cue("button", T1) == (404, "the audit is not enabled on this instance ([audit] enabled)") and pushed == [], pushed)
config.CFG["audit"]["enabled"] = True
check("cue past a crashed run, delivered: 202", audit.cue("button", T1) == (202, "audit cued to falcon-audit"), pushed)
check("…one line to the agent, saying why and when",
      pushed == [("falcon-audit", f"[stackshot] Audit now (button, 2026-10-05 08:00 {ABBR}): run the audit as your brief says, write the run record, report as usual.")], pushed)
config.CFG["audit"]["agent"] = "ops-other-audit"; pushed.clear()
audit._push = recorder(False, "queued → ops-other-audit")
check("cue when push.py does not deliver: 503 with push.py's answer",
      audit.cue("scheduled", T1) == (503, "the audit agent ops-other-audit is not running: queued → ops-other-audit") and pushed[0][0] == "ops-other-audit"
      and pushed[0][1].startswith(f"[stackshot] Audit now (scheduled, 2026-10-05 08:00 {ABBR})"), pushed)
config.CFG["audit"]["agent"] = "falcon-audit"
log = [json.loads(l) for l in (D / "cues.jsonl").read_text(encoding="utf-8").splitlines()]
check("every cue logged to cues.jsonl: ts, reason, code, text, whatever the outcome",
      [(x["reason"], x["code"]) for x in log] == [("button", 409), ("button", 404), ("button", 202), ("scheduled", 503)]
      and all(set(x) == {"ts", "reason", "code", "text"} for x in log) and log[0]["ts"] == T0 and log[2]["text"] == "audit cued to falcon-audit", log)
check("the server never writes a run record", sorted(p.name for p in D.glob("run-*.json")) == ["run-2026-10-01.json", "run-2026-10-02.json", "run-2026-10-03.json", "run-2026-10-04.json", "run-2026-10-05.json", "run-latest.json"])

# ---- 5. the push goes through push.py, as the message source
import importlib; audit = importlib.reload(audit)          # the module's own _push again
fake = T / "fakepush.py"
fake.write_text(f"import json, os, sys\nopen({str(T / 'push.args')!r}, 'w').write(json.dumps([sys.argv[1:], os.environ.get('ANCHOR_PUSH_SOURCE')]))\n"
                "print(os.environ.get('FAKE_OUT', ''))\nerr = os.environ.get('FAKE_ERR')\nerr and print(err, file=sys.stderr)\n")
audit.PUSH = [sys.executable, str(fake)]
os.environ["FAKE_OUT"] = "delivered → falcon-audit"
ok, said = audit._push("falcon-audit", "hello")
args, src = json.loads((T / "push.args").read_text())
check("_push: push.py --from <its name> <session> <text>, as the message source; delivered → True", ok is True and args == ["--from", "stackshot audit", "falcon-audit", "hello"] and src == "msg", (ok, said, args, src))
os.environ.update(FAKE_OUT="inbox → falcon-audit", FAKE_ERR="machine asleep")
check("_push: a line left waiting in the inbox is not delivered; the answer carries stderr too",
      audit._push("falcon-audit", "x") == (False, "inbox → falcon-audit — machine asleep"))
os.environ.pop("FAKE_ERR")
check("the real push.py is the default", pathlib.Path(audit.PUSH[1]).name == "fakepush.py" and importlib.reload(audit).PUSH[1] == os.path.join(STACK, "push.py"))
audit.PUSH = [sys.executable, str(fake)]
# the interpreter this timer's process runs on was deleted under it (its uv environment): the push still goes out, through uv
audit.PUSH = [str(T / "gone-env/bin/python"), str(fake)]; os.environ["FAKE_OUT"] = "delivered → falcon-audit"
ok, said = audit._push("falcon-audit", "env gone")
args, src = json.loads((T / "push.args").read_text())
check("_push with a deleted interpreter: delivered through the fallback command", ok is True and args == ["--from", "stackshot audit", "falcon-audit", "env gone"] and src == "msg", (ok, said, args, src))
audit.PUSH = [sys.executable, str(fake)]

# ---- 6. the CLI (what the timer's service runs)
def cli(*a, **env):
    r = subprocess.run([sys.executable, os.path.join(STACK, "audit.py"), *a], capture_output=True, text=True, env={**os.environ, **env})
    return r.returncode, r.stdout, r.stderr
rc, out, _ = cli("status")
st = json.loads(out) if rc == 0 else {}
check("audit.py status: the status JSON", rc == 0 and st.get("enabled") is True and st.get("last", {}).get("date") == "2026-10-05", out[:300])
off = T / "off.toml"; off.write_text(re.sub(r'(?m)^(\[audit\][^\n]*\n)enabled = true', r'\g<1>enabled = false', toml), encoding="utf-8")
rc, out, _ = cli("cue", "scheduled", STACKSHOT_CONFIG=str(off))
check("audit.py cue scheduled with the audit off: prints the refusal, exit 1", rc == 1 and out.strip() == "the audit is not enabled on this instance ([audit] enabled)", (rc, out))
rc, out, err = cli("bogus")
check("audit.py with no verb it knows: usage, exit 2", rc == 2 and "usage" in err, (rc, err))
check("audit.py orphans names itself in the usage, and with no server to reach it says so and exits 1 (the server makes the check)", "orphans [--apply]" in err and cli("orphans")[0] == 1 and "not run" in cli("orphans")[2], err)
rc, _o, err2 = cli("orphans", "--bogus")
check("audit.py orphans takes only --apply: anything else is the usage, exit 2", rc == 2 and "usage" in err2, (rc, err2))
import client as _cl, contextlib as _ctx, io
_real_oh = _cl.orphan_handover
def _orph_out(ans, apply):
    _cl.orphan_handover = lambda a, timeout=120.0: (200, ans)
    buf = io.StringIO()
    try:
        with _ctx.redirect_stdout(buf):
            rc_ = audit.orphans(apply)
    finally:
        _cl.orphan_handover = _real_oh
    return rc_, buf.getvalue()
_mv = [{"id": "c7", "from": "gone-main", "to": "live-main", "why": "gone-main is gone"}]
rc_, txt = _orph_out({"checked": True, "applied": False, "read": 9, "found": 1, "moved": _mv, "left": [], "note": "[audit] orphan_handover is report: nothing was moved; set it to apply under [audit] to hand these over"}, True)
check("audit.py orphans --apply in report mode: the dry-run lines AND the server's note (nothing was moved, set apply) are printed", rc_ == 0 and "1 would move" in txt and "(a dry run: nothing written, nobody told)" in txt and "nothing was moved; set it to apply" in txt, txt)
rc_, txt = _orph_out({"checked": True, "applied": False, "ceiling": True, "read": 20, "found": 12, "moved": _mv, "left": [], "note": "12 of 20 open items read as left with a gone session: that is a partial view, so nothing was moved"}, True)
check("audit.py orphans when the ceiling trips: the note that nothing was moved is printed with the list", rc_ == 0 and "partial view, so nothing was moved" in txt, txt)
rc_, txt = _orph_out({"checked": True, "applied": True, "read": 9, "found": 1, "moved": _mv, "left": [], "note": ""}, True)
check("audit.py orphans --apply that applied: no dry-run wording and no note line", "handed over" in txt and "dry run" not in txt and txt.count("audit:") == 1, txt)
n0 = len((D / "cues.jsonl").read_text().splitlines())
check("…the CLI's cue was logged like any other", n0 == 5 and json.loads((D / "cues.jsonl").read_text().splitlines()[-1])["reason"] == "scheduled")

# ---- 7. over HTTP, in-process
import server
server._publish = lambda: None
from starlette.testclient import TestClient
calls = []
server._audit.cue = lambda reason: (calls.append(reason), (202, "audit cued to falcon-audit"))[1]
with TestClient(server.mcp.http_app()) as c:
    r = c.post("/audit/now")
    check("POST /audit/now: audit.cue('button'), its code and text as text/plain", r.status_code == 202 and r.text == "audit cued to falcon-audit"
          and r.headers["content-type"].startswith("text/plain") and calls == ["button"], (r.status_code, r.text, calls))
    for code, text in ((409, f"an audit is running since 2026-10-05 05:00 {ABBR}"), (404, "the audit is not enabled on this instance ([audit] enabled)"), (503, "the audit agent x is not running: queued → x")):
        server._audit.cue = lambda reason, c_=code, t_=text: (c_, t_)
        r = c.post("/audit/now"); check(f"POST /audit/now: {code} passed through", r.status_code == code and r.text == text, (r.status_code, r.text))
    calls.clear(); server._audit.cue = lambda reason: (calls.append(reason), (202, "x"))[1]
    bad = {m: c.request(m, "/audit/now").status_code for m in ("GET", "PUT", "DELETE", "PATCH")}
    check("any other method on /audit/now: 405, nothing cued", all(v == 405 for v in bad.values()) and calls == [], (bad, calls))
    check("…and it says POST is allowed", c.get("/audit/now").headers.get("allow") == "POST")
    r = c.get("/audit/status")
    check("GET /audit/status: audit.status() as JSON, not cached", r.status_code == 200 and r.headers["content-type"].startswith("application/json")
          and set(r.json()) == {"enabled", "agent", "running", "running_since", "last", "next", "runner", "phase_sweep"} and r.headers.get("cache-control") == "no-store", (r.status_code, r.text[:200]))
    check("…and no waiting counts: the ladder's counts (open, overdue, stuck, undelivered, nodate, unaddressed) went with the ladder", "waiting" not in r.json(), list(r.json()))
    check("…and the runner's record instead (the minute set's mode and a record per tick)", r.json().get("runner", {}).get("mode") == "runner" and r.json()["runner"].get("enabled") is True, r.json().get("runner"))
    check("POST /audit/status is not a route: 405", c.post("/audit/status").status_code == 405)
    real_mode, server._auth_mode = server._auth_mode, (lambda: "google"); server._cfg.CFG["auth"]["ui_open"] = False
    r1, r2 = c.post("/audit/now", follow_redirects=False), c.get("/audit/status", follow_redirects=False)
    check("[auth] ui_open = false: both ask for the board's sign-in first, as the board and the item pages do",
          r1.status_code == 302 and r1.headers["location"].startswith("/ui/login") and r2.status_code == 302 and r2.headers["location"] == "/ui/login?next=%2Faudit%2Fstatus" and calls == [],
          (r1.status_code, r1.headers.get("location"), r2.status_code, r2.headers.get("location")))
    server._auth_mode = real_mode; server._cfg.CFG["auth"]["ui_open"] = True

# ---- 8. the audit's own writes and a bare confirm do not move an item's activity clock (activity.py; its full table is tests/activity_scenario.py)
import activity
audit_agent = config.audit_agent()
check("8 the server counts the configured audit agent among the audit's own writers", audit_agent in server._audit_writer_names() and "stackshot audit" in server._audit_writer_names(), server._audit_writer_names())
ACT_OLD = T0 - 7200
(T / "store/a/60.json").write_text(json.dumps({"id": "60", "subject": "[home] an item", "description": "- A\n- B\n- C", "status": "open", "updated": ACT_OLD, "state_updated": ACT_OLD, "confirmed": ACT_OLD,
                                               "metadata": {"owner": "home-a", "project": "projects/a", "next": "home-a: do it", "mover": "home-a"}}))
def act60(): return json.loads((T / "store/a/60.json").read_text()).get("activity")
def save60(**kw): it = server._load("a60"); it["updated"] = time.time(); server._save("a60", it, **kw)
save60(writer=audit_agent)
seed = act60()
check("8 an audit agent's write to an old item leaves its activity at the item's last update (the field is seeded, not set to now)", seed is not None and abs(seed - ACT_OLD) < 1, (seed, ACT_OLD))
save60(note="stall: the notice was sent again")
save60(note="nudge", author=("stackshot audit", "stackshot audit"))
check("8 …nor does the server's own nudge, nor a write stamped with the audit's label", act60() == seed, act60())
time.sleep(0.02)
item60 = server._load("a60"); item60["confirmed"] = time.time(); server._save("a60", item60, writer="home-a", activity=activity.CONFIRM)
check("8 a bare confirm moves `confirmed` and not `activity`", json.loads((T / "store/a/60.json").read_text())["confirmed"] > ACT_OLD + 1 and act60() == seed, act60())
save60(writer="home-a")
check("8 a write by the item's mover does move it", act60() > seed + 3600, act60())

# ---- 9. the code checks live in audit_checks.py; the filing pass's record sits beside the run records and is none of them
import audit_checks, audit_run
before = (audit.runs(), audit.last(), audit.status(T0)); running_before = audit.running(T0)
(D / "filing.json").write_text(json.dumps({"started": T0, "finished": T0 + 30, "items_read": 3, "repeats": 0, "findings": [{"id": "board#1", "category": "stuck-elsewhere", "project": "projects/a", "owner": "home-a"}], "flags": []}))
check("9 filing.json beside the run records is no run: runs, last and status are what they were", (audit.runs(), audit.last(), audit.status(T0)) == before)
check("9 …nor a run in progress: that is told from the run records alone (the filing record is never running)", audit.running(T0) == running_before and not any(r.get("date") == "filing" for r in audit.runs()))
check("9 the daily run's check names are importable from audit_run and are audit_checks' own", all(getattr(audit_run, n) is getattr(audit_checks, n) for n in ("field_findings", "check_stale", "check_ask_missing", "check_stuck_elsewhere", "idle_pass", "FIX", "CHECKS_CODE")))
check("9 the filing categories all have a fix line, as every finding needs one", all(audit_checks.FIX.get(c) for c in ("stuck-elsewhere", "board checks", "reads-as-wait", "step-handover", "ask-options", "why-not-now")) and audit_checks.CHECKS_FILING == ("stuck-elsewhere", "board checks", "reads-as-wait", "step-handover", "ask-options", "why-not-now"))
check("9 the board report has no silence kind any more (idle-on-agent is gone; silence is the silence pass's) and the filing kinds are its kinds", "idle-on-agent" not in audit_checks.FILING_KINDS and "idle-on-agent" not in __import__("board_report").KINDS and set(audit_checks.FILING_KINDS) <= set(__import__("board_report").KINDS))
(D / "filing.json").unlink()

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": audit scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
