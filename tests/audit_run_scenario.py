"""Scenario test for the daily board audit as a script (audit_run.py) — fixture items, a fake `claude` binary, messages and pushes replaced by recorders; no live store, no network, no server.

Covers: a field check fires in code with no model call (ask-missing, next rules; stuck-elsewhere, arbitrary-hold, mislabeled-state, the wake half of stale and the silence of an item on an agent are
the ten-minute passes' and the run makes none of them: pinned with field_findings(ten_minute=True) against the old rows, the delivery sections run every check through go_all, the stuck-elsewhere rules through the filing pass); a suspect gets exactly ONE model call (its message names
the candidate checks, the rubric is the system prompt) and a "yes" under a check that was not a candidate is not accepted; the cap holds (extra suspects counted, never called); a dry run lists the suspects and
makes no call, no message and no record; the threshold message goes once, to the builder, naming the check and the item ids, and not when no check reaches the threshold; an item judged "no" is not judged again
until it is written, a "yes" is carried; three failed calls in a row end the calls; a finding goes to its mover (a front agent's message starts with [for Oliver], Oliver's goes to the project's -main agent), an
unmoved flag to the builder as a job and onto `stuck`; the record is the one audit.py reads (runs, last, status keep their shape); `[audit] mode` switches between the script and the agent cue; and the shared
engine (mover_state.py) answers the stall pass and the board check alike.
Review round: a run that dies leaves a finished record with `error` and a line in cues.jsonl, so the next cue is not 409, and the detached child's output goes to run.log; `audit.py run` by hand is refused while
a run is in progress, when the audit is not enabled and in agent mode (a dry run never); two runs on one day keep two records and readers take the newest; `[audit] max_minutes` stops new calls; a finding whose
message fails goes to the project's -main agent; the cue's check and the running record are written under an exclusive flock.
Follow-up: stuck-elsewhere on a waiting item compares the first open step with the post-wake mover (a session's step, or Oliver's while the wait is on him, is no finding; Oliver's step on a wait that is not
on him and a session's step beside a named post-wake mover still are); a message refused because the recipient is a front agent goes unmarked to the project's page key (`kind: project`).
obsolete-wait: a waiting item (held, parked, outside, after another item) is a suspect when an item its wait cites is closed, or when its project page, written after both the wait and the item's last write, names it
or an item it cites; a replay of a hold whose premise was dropped is caught (one call, the finding on its mover); a wait on an open item, a closed item cited as background (judged no) and an alive item are not
flagged; a verdict stands until the evidence's signature changes; the cap holds.

Two runs a day ([audit] at with two times): a second run on one date keeps the first one's record and is not refused, names itself in its messages (`<date> 20:00`), sends nothing the first sent, chases an unmoved item against the
run 9 hours before it once, and the tightening history counts days, not runs; the rulebook scan is none of the run's business.

    tests/run-suite audit_run        → exit 0 / 1"""
import contextlib, datetime as dt, fcntl, io, json, os, pathlib, re, signal, subprocess, sys, threading, time, tomllib
BID_00 = 9200
BID_01 = 9201
BID_02 = 9202
BID_03 = 9203
BID_04 = 9204
BID_05 = 9205
BID_06 = 9206
BID_07 = 9207
BID_08 = 9208
BID_11 = 9211
BID_12 = 9212
BID_13 = 9213
BID_14 = 9214
BID_15 = 9215
BID_20 = 9220
BID_21 = 9221
BID_22 = 9222
BID_23 = 9223
BID_24 = 9224
BID_25 = 9225
BID_26 = 9226
BID_28 = 9228
BID_38 = 9238
BID_39 = 9239
BID_40 = 9240
BID_41 = 9241
BID_42 = 9242
BID_43 = 9243
BID_44 = 9244
BID_45 = 9245
BID_46 = 9246
BID_47 = 9247
BID_50 = 9250
BID_60 = 9260
BID_61 = 9261
BID_63 = 9263
BID_64 = 9264
BID_65 = 9265
BID_74 = 9274
BID_75 = 9275
BID_76 = 9276
BID_77 = 9277
BID_78 = 9278
BID_80 = 9280

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="auditrun-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_run as AR; from stackshot.waits import mover_state as MS; from stackshot.waits import stall; from stackshot.tools import board_report as BR; from stackshot.tools import next_report as NR
_cfg.CFG["audit"]["pattern_review"] = "off"      # this suite holds the run to its other stages: the pattern review has its own suite (pattern_review_scenario)
H = 3600; now = time.time()
ZONE_OFFSET = 4 * H                         # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900     # a run within 10 minutes of local midnight starts 15 minutes earlier: the sections that read record times a few seconds after `now` must stay on one calendar day
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET)); OWNER = "00000000-0000-4000-8000-000000000001"
local = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d %H:%M")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

# ---- the fake `claude`: logs what it was started with, answers as the control file says (one answer per item id, by the id in the message)
CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
(T / "fake_claude.py").write_text(f'''import sys, os, json, re
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
open({str(CALLS)!r}, "a").write(json.dumps({{"argv": sys.argv[1:], "stdin": stdin, "pid": os.getpid()}}) + "\\n")
if ctl["mode"] == "exit":
    sys.stderr.write("boom"); sys.exit(3)
m = re.search(r"^Item (board#\\d+):", stdin, re.M)
ans = ctl.get("answers", {{}}).get(m.group(1) if m else "", ctl.get("default", {{"finding": "no", "check": "", "reason": "", "fix": ""}}))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_ms": 10, "duration_api_ms": 5, "num_turns": 1, "result": json.dumps(ans) if isinstance(ans, dict) else ans,
                  "total_cost_usd": 0.001, "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
''')
def fake(mode="answer", answers=None, default=None): CTL.write_text(json.dumps({"mode": mode, "answers": answers or {}, **({"default": default} if default else {})}))
def calls(): return [json.loads(l) for l in CALLS.read_text().splitlines()] if CALLS.exists() else []
def reset_calls(): CALLS.exists() and CALLS.unlink()
_cfg.CFG["router"] = {"shadow": True, "command": [sys.executable, str(T / "fake_claude.py")], "timeout_seconds": 20, "login_shell": False}
YES = lambda check, reason="r", fix="f": {"finding": "yes", "check": check, "reason": reason, "fix": fix}
fake()

# ---- fixtures
# a fixture number below 10 is its own id; one from 10 on is the next counter from 9200, in the order of the numbers the file uses
FIXTURE_NS = [*range(10, 76), *range(80, 88), *range(90, 96), 99, *range(100, 115), 121]
fid = lambda n: n if n < 10 else 9200 + FIXTURE_NS.index(n)
def item(i, status="open", wrote=None, **meta):
    i = fid(i)
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if wrote is None else wrote,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"a{i}", d
def doing(i, ago, nxt="home-agent: build it", **kw): return item(i, wrote=now - ago * H, state="doing", needs=["home-agent"], next=nxt, **kw)
def clean(i): return doing(i, 1, expected_by=local(now + 30 * H), expected_reason="the build runs overnight")
def build(*pairs): return dict(pairs)
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}, "home-front": {"role": "front"}}
sent, pushed = [], []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def push(to, text): pushed.append((to, text)); return True, "delivered"
def env(**kw):
    kw.setdefault("sessions", lambda: None)                  # sala is never read here: the page agent lines are "not checked" unless a section hands in sessions and a registry
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})      # the server is never asked here: the page-debt call is off unless a section hands in the pages stage's answer
    kw.setdefault("orphans", lambda apply: {"checked": True, "applied": apply, "read": 0, "found": 0, "moved": [], "left": []})      # the server is never asked here: the orphan hand-over finds nothing unless a section hands in its answer (successor_scenario holds the stage)
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=kw.pop("page_of", lambda p: ("", None)),
                  deliver=kw.pop("deliver", deliver), push=kw.pop("push", push), **kw)
RUBRIC_TEXT = pathlib.Path(STACK, "audit_rubric.txt").read_text(encoding="utf-8").replace("{owner}", "Oliver")   # the rubric names the owner as {owner}; the tool fills it from [instance] owner
def go(items, **kw):
    sent.clear(); pushed.clear(); reset_calls()
    return AR.run(now=kw.pop("now", now), items=items, anchors={}, env=kw.pop("env_", None) or env(), rubric=RUBRIC_TEXT, **kw)
_go_base = go
def go_all(items, **kw):
    """A run that makes every code check, the ten-minute passes' too (field_findings(ten_minute=True)). The sections on delivery (the recipient, the fallbacks, the send stamps) take their sample
    finding from whichever check is handy, and the stuck-elsewhere and wake-passed ones are; what the run itself makes is pinned in section 1 and 1b."""
    real = AR.field_findings
    AR.field_findings = lambda *a, **k: real(*a, **{**k, "ten_minute": True})
    try:
        return _go_base(items, **kw)
    finally:
        AR.field_findings = real
def fil(items):
    """What the filing and dates passes find on `items`, as a record the `ids` helper reads (the stuck-elsewhere rules are theirs now)."""
    fs = AC.filing_findings(items, {}, now, env())[0] + AC.dates_findings(items, {}, now, env())[0]
    return {"findings": fs}
def rec_clear():
    for p in (T / "state/audit").glob("run-*.json"): p.unlink()
today = AR._date_of(now)
ids = lambda rec, cat: sorted(f["id"] for f in rec["findings"] if f["category"] == cat)

# ---- 1. the field checks: code only, no model call
f1 = build(item(1, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one"),                       # ask-missing: a decision with no ask
           doing(2, 5, wake=local(now - 2 * H)),                                                      # stale: its wake passed 2 hours ago, nothing written since (5 hours)
           doing(3, 1, nxt="ops-other: do the first part\nhome-agent: then the second", expected_by=local(now + 30 * H), expected_reason="the build"),   # stuck-elsewhere: the first open step is ops-other's
           doing(4, 1, nxt="build it", expected_by=local(now + 30 * H), expected_reason="the build"),                                     # next rules: no one named in next
           doing(5, 8, expected_by=local(now + 30 * H), expected_reason="the build runs overnight"),                                       # quiet 8 hours: the silence pass's, no daily finding
           clean(6), clean(7), clean(8), clean(9), clean(72), item(33, status="completed", wrote=now - 40 * H, state="doing", needs=["home-agent"], next="", outcome="done"))
rec_clear(); fake()
rec = go(f1)
check("ask-missing: a decision item with no ask is a finding in code", ids(rec, "ask-missing") == ["board#1"], rec["findings"])
check("stale: past its wake with no write since is the dates pass's, so the run makes no finding for it", ids(rec, "stale") == [], rec["findings"])
check("stuck-elsewhere is the filing pass's, so the run makes no finding for it", ids(rec, "stuck-elsewhere") == [], rec["findings"])
check("next rules: the report's finding is carried as a finding of its category", "board#4" in ids(rec, "next rules"), rec["findings"])
check("board checks: the daily run makes none (the filing kinds are the filing pass's, an item quiet for 8 hours is the silence pass's)", ids(rec, "board checks") == [] and "board#5" not in ids(rec, "stale"), rec["findings"])
check("a clean item and a closed one are no finding", not any(f["id"] in ("board#6", "board#7", "board#8", f"board#{BID_23}") for f in rec["findings"]), rec["findings"])
check("the field checks made no model call (nothing to suspect)", calls() == [] and rec["calls"]["made"] == 0, calls())
check("every finding names its mover and its source", all(f.get("source") == "code" and f.get("mover") for f in rec["findings"]), rec["findings"])
check("the record: items_read counts the open items", rec["items_read"] == 10 and rec["mode"] == "script", rec["items_read"])

# ---- pin: the code checks give what they gave before they moved to audit_checks.py (the expected rows were produced by the old audit_run.py on these same fixtures)
def _pin_t(s): return re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}( (?:[A-Z]{2,5}|[+-]\d{2}(?::?\d{2})?))?", "<t>", str(s))
def _pin_rows(fs): return sorted([f["id"], f["category"], f["source"], f["mover"], f.get("to", ""), _pin_t(f["detail"]), f["fix"]] for f in fs)
PIN_F = build(*f1.items(),
              item(52, wrote=now - H, state="parked", needs=["home-agent"], hold=True, next="home-agent: later"),                                       # arbitrary-hold: a hold whose words name no event
              item(34, wrote=now - H, state="blocked", needs=["home-agent"], next="home-agent: build it"),                                             # mislabeled-state: blocked with no after
              doing(60, 14, nxt="home-agent: build it"),                                                                                               # no date of its own: the silence pass's, no daily finding
              item(92, wrote=now - H, state="parked", needs=["home-agent"], hold=True, wake=local(now + 30 * H), next="ops-other: the first part\nhome-agent: then the second"),   # a parked item, its wake ahead: no stuck-elsewhere
              doing(41, 1, nxt="home-agent: waiting for the build", expected_by=local(now + 30 * H), expected_reason="the build"))
PIN_F["a9250"]["metadata"]["idle"] = {"poked": now - H}; PIN_F["a9250"]["confirmed"] = now - 2 * H          # the server's idle pass poked it since the last confirm
def _pin_run(mod, **kw):
    fs, ps, n = mod.field_findings(PIN_F, {}, now, env(), **kw)
    return [_pin_rows(fs), sorted([p["id"], p["category"], p["mover"], _pin_t(p["detail"])] for p in ps), n]
def _pin_each(mod):
    known = {k.lower() for k in ROLES} | {mod._norm(k) for k in ROLES}; rows = []
    for gid in sorted(PIN_F, key=mod._num):
        it, meta, after_open, mover = mod._item_view(PIN_F, gid)
        last = BR._last_write(it)
        rows.append([gid, mod.check_ask_missing(meta), _pin_t(mod.check_stale(it, meta, mover, after_open, now, last)), _pin_t(repr(mod.check_stuck_elsewhere(it, meta, mover, known, last, after_open, now))), mod.idle_pass(it)])
    return rows
PIN_GOLD = json.loads(rf'''{{
"run": [
[
[
"board#1",
"ask-missing",
"code",
"Oliver",
"",
"needs a decision from Oliver and carries no ask",
"write the ask Oliver is to decide, or take needs: decision off the item"
],
[
"board#1",
"board checks",
"code",
"Oliver",
"",
"mislabeled-state: stored state your-call lacks ask=<the ask line>",
"move the item, or write what holds it and the state that fits"
],
[
"board#2",
"stale",
"code",
"home-agent",
"",
"past its wake (<t>) with no write since (last write <t>)",
"write the item: done, moved, or a new date"
],
[
"board#3",
"stuck-elsewhere",
"code",
"home-agent",
"ops-other",
"the first open step is ops-other's, the item's mover is home-agent: ops-other: do the first part, item last written <t>",
"the step's named session takes it, or the step is renamed to the item's mover"
],
[
"board#4",
"next rules",
"code",
"home-agent",
"",
"N1: the open step names no one: build it",
"rewrite next as the rule says"
],
[
"board#{BID_42}",
"board checks",
"code",
"home-agent",
"",
"arbitrary-hold: on hold with no wake date; nothing holds it (no open after, check, outside party or anchor) and its words name no event: home-agent: later",
"move the item, or write what holds it and the state that fits"
],
[
"board#{BID_24}",
"board checks",
"code",
"home-agent",
"",
"mislabeled-state: stored state blocked lacks after=[\"board#N\"] (the item it waits on)",
"move the item, or write what holds it and the state that fits"
],
[
"board#{BID_24}",
"board checks",
"code",
"home-agent",
"",
"mislabeled-state: stored state blocked, but its fields read as doing",
"move the item, or write what holds it and the state that fits"
],
[
"board#{BID_76}",
"board checks",
"code",
"home-agent",
"",
"arbitrary-hold: on hold with wake <t>; nothing holds it (no open after, check, outside party or anchor) and its words name no event: ops-other: the first part",
"move the item, or write what holds it and the state that fits"
]
],
[],
15
],
"each": [
[
"a1",
"needs a decision from Oliver and carries no ask",
"",
"None",
false
],
[
"a2",
"",
"past its wake (<t>) with no write since (last write <t>)",
"None",
false
],
[
"a3",
"",
"",
"('ops-other', 'ops-other: do the first part')",
false
],
[
"a4",
"",
"",
"None",
false
],
[
"a5",
"",
"",
"None",
false
],
[
"a6",
"",
"",
"None",
false
],
[
"a7",
"",
"",
"None",
false
],
[
"a8",
"",
"",
"None",
false
],
[
"a9",
"",
"",
"None",
false
],
[
"a9262",
"",
"",
"None",
false
],
[
"a9223",
"",
"",
"None",
false
],
[
"a9242",
"",
"",
"None",
false
],
[
"a9224",
"",
"",
"None",
false
],
[
"a9250",
"",
"",
"None",
true
],
[
"a9276",
"",
"",
"None",
false
],
[
"a9231",
"",
"",
"None",
false
]
]
}}''')
PIN_GOLD["run"][0] = sorted(PIN_GOLD["run"][0]); PIN_GOLD["run"][1] = sorted(PIN_GOLD["run"][1]); PIN_GOLD["each"] = sorted(PIN_GOLD["each"], key=lambda r: AR._num(r[0]))      # the gold lists are in the pins' own order (sorted rows; the per-item rows by number)
from stackshot.audit import audit_checks as AC
PIN_NAMES = ("check_stale", "check_ask_missing", "check_stuck_elsewhere", "idle_pass", "field_findings", "_item_view", "FIX", "CHECKS_CODE", "_norm", "_no_session", "_clip", "_hours", "_f", "_num", "_stamp")
check("pin: audit_run offers every check it offered before they moved, and each is the one in audit_checks.py", all(getattr(AR, n) is getattr(AC, n) for n in PIN_NAMES), [n for n in PIN_NAMES if getattr(AR, n) is not getattr(AC, n)])
# what the ten-minute passes took over: stuck-elsewhere, the board report's arbitrary-hold and mislabeled-state, and the wake half of stale
_pin_moved = lambda r: r[1] == "stuck-elsewhere" or (r[1] == "board checks" and r[5].startswith(("arbitrary-hold", "mislabeled-state"))) or (r[1] == "stale" and "past its wake" in r[5])
_pin_without = lambda rows: [[r for r in rows[0] if not _pin_moved(r)], rows[1], rows[2]]
check("pin: with ten_minute=True field_findings gives, on the pinned fixtures, the rows the old audit_run gave less the two silence rules (the 12-hour stale half and idle-on-agent), which the silence pass has", _pin_run(AR, ten_minute=True) == PIN_GOLD["run"], _pin_run(AR, ten_minute=True))
check("pin: …and without it (the daily run) the same rows less the moved checks, and every moved kind was in the old rows", _pin_run(AR) == _pin_without(PIN_GOLD["run"])
      and {r[1] for r in PIN_GOLD["run"][0] if _pin_moved(r)} == {"stuck-elsewhere", "board checks", "stale"} and len(_pin_run(AR)[0]) < len(PIN_GOLD["run"][0]), _pin_run(AR))
check("pin: …and each per-item check (ask-missing, stale, stuck-elsewhere, idle-pass) gives what it gave", _pin_each(AR) == PIN_GOLD["each"], _pin_each(AR))
check("pin: …audit_checks called directly gives the same", _pin_run(AC, ten_minute=True) == PIN_GOLD["run"] and _pin_each(AC) == PIN_GOLD["each"] and _pin_run(AC) == _pin_run(AR))

# ---- 2. the record is the one audit.py reads
st = audit.status()
check("the run record is written and finished", audit.last() is not None and audit.last()["date"] == today and audit.last()["finished"] is not None and audit.running() is None)
check("status keeps its shape and counts the findings", set(st) == {"enabled", "agent", "running", "running_since", "last", "next"} and st["last"]["findings"] == len(rec["findings"])
      and st["last"]["items_read"] == 10 and st["last"]["by_category"] == rec["by_category"] and st["last"]["by_session"] == rec["by_session"], st)
check("runs() reads it, the findings with the keys the agent's record has", audit.runs(1)[0]["findings"][0].keys() >= {"id", "project", "owner", "category"}, audit.runs(1))

# ---- 3. messages: one per recipient, a front agent's starts with [for Oliver], Oliver's findings go to the project's -main agent
by_to = {to: text for to, text, fyi in sent if not fyi}
check("one message per recipient; lines are '<id> · <category> · <evidence> · <fix>'", len({to for to, _, _ in sent if _ != ""}) == len(sent) and by_to.get("home-agent", "").count("board#") >= 1
      and all(len(l.split(" · ")) == 4 for l in by_to["home-agent"].splitlines() if l.startswith("board#")), sent)
check("a finding on Oliver goes to the project's -main agent with [for Oliver] first", by_to.get("alpha-main", "").startswith("[for Oliver]") and "board#1 · ask-missing" in by_to["alpha-main"], by_to.get("alpha-main"))
check("a stuck-elsewhere finding is the filing pass's: the run sends none to the session whose step it is", "ops-other" not in by_to and all("stuck-elsewhere" not in t for t in by_to.values()), by_to)
summary = [(to, text, fyi) for to, text, fyi in sent if to == "projects/example"]
check("a summary goes to projects/example, fyi", len(summary) == 1 and summary[0][2] is True and "Board audit" in summary[0][1], summary)
check("the month's first run counts the front-held steps: one line in the summary, `front_step_count` on the record", "front-held steps, last 30 days:" in summary[0][1] and (audit.last().get("front_step_count") or {}).get("month"), (summary, audit.last()))

# ---- 4. a dry run: suspects listed, no call, no message, no record
rec_clear()
f2 = build(*[doing(16 + k, 1, nxt=f"home-agent: build it\nhome-agent: tick board#{BID_21}", expected_by=local(now + 30 * H), expected_reason="the build") for k in range(6)],
           item(31, status="completed", wrote=now - 3 * H, state="doing", needs=["home-agent"], next="", outcome="done"), clean(40))
out = []
sent.clear(); pushed.clear(); reset_calls()
res = AR.run(dry=True, now=now, items=f2, anchors={}, env=env(), rubric=RUBRIC_TEXT, out=out.append)
check("dry run: the suspects are listed, no model call, no message, no push, no record", res["dry"] is True and len(res["suspects"]) == 6 and calls() == [] and sent == [] and pushed == []
      and list((T / "state/audit").glob("run-*.json")) == [] and any("suspect" in l for l in out), (res.get("suspects"), calls(), sent, out[:3]))
check("dry run: says how many calls it would make under the cap", res["would_call"] == 6 and res["cap"] == 40 and "would make 6 call" in out[0], out[0])

# ---- 5. a suspect gets exactly one model call, with the rubric as the system prompt and the candidate checks in the message
rec_clear(); fake(answers={f"board#{BID_06}": YES("next-done", f"step cites board#{BID_21}, closed", "tick the step")})
rec = go(f2)
cs = calls()
check("each suspect got exactly one call: 6 suspects, 6 calls, one per item", len(cs) == 6 and rec["calls"]["made"] == 6 and sorted(re.search(r"^Item (board#\d+):", c["stdin"], re.M).group(1) for c in cs)
      == sorted(f"board#{9206 + k}" for k in range(6)), [c["stdin"][:30] for c in cs])
check("the rubric is the system prompt; the message names the candidate checks and the evidence", all("--system-prompt" in c["argv"] and RUBRIC_TEXT in c["argv"] for c in cs)
      and f"next-done: open step cites board#{BID_21}, which is closed" in cs[0]["stdin"] and "Candidate checks" in cs[0]["stdin"], cs[0]["stdin"])
check("a 'yes' becomes a finding of the check the call named, with its reason, source model", [(f["id"], f["category"], f["detail"], f["source"]) for f in rec["findings"] if f["source"] == "model"]
      == [(f"board#{BID_06}", "next-done", f"step cites board#{BID_21}, closed", "model")], rec["findings"])
check("the other five were judged 'no': recorded in judged, no finding", sum(1 for e in rec["judged"].values() if e["verdict"] == "no") == 5 and rec["judged"][f"board#{BID_06}"]["verdict"] == "yes", rec["judged"])
SUSP6 = sorted(rec["judged"])                    # the six suspects, in the order the cap takes them

# ---- 6. a 'yes' under a check that was not a candidate is not accepted
rec_clear(); fake(answers={f"board#{BID_06}": YES("stale", "x", "y")})
rec = go(f2)
check("a yes under a check that was not a candidate is no finding (judged 'no')", not [f for f in rec["findings"] if f["source"] == "model"] and rec["judged"][f"board#{BID_06}"]["verdict"] == "no", rec["findings"])

# ---- 7. the cap holds; the rest is counted as not called
rec_clear(); fake(); _cfg.CFG["audit"]["max_calls"] = 4
rec = go(f2)
check("the cap holds: 6 suspects, a cap of 4, exactly 4 calls", len(calls()) == 4 and rec["calls"]["made"] == 4 and rec["calls"]["cap"] == 4 and rec["calls"]["suspects"] == 6, (len(calls()), rec["calls"]))
check("the suspects past the cap are not judged (no entry), the nearest board#N come first", sorted(rec["judged"]) == SUSP6[:4], sorted(rec["judged"]))
_cfg.CFG["audit"]["max_calls"] = 0
rec = go(f2)
check("a cap of 0 makes no call at all", calls() == [] and rec["calls"]["made"] == 0, calls())
_cfg.CFG["audit"]["max_calls"] = 40

# ---- 8. an item judged 'no' is not judged again until written; a 'yes' is carried
rec_clear(); fake(answers={f"board#{BID_06}": YES("next-done")})
go(f2)                                                                                              # run 1 writes today's record (judged map)
first = json.loads(AR._record_path(now).read_text())
older = dict(first, started=now - 2 * 86400, finished=now - 2 * 86400 + 60, findings=first["findings"])
(T / "state/audit" / f"run-{dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date().isoformat()}.json").write_text(json.dumps(older))
AR._record_path(now).unlink()
rec = go(f2)
check("unchanged items are not judged again: no call, the 'yes' carried as a finding, the 'no's skipped", calls() == [] and [f["id"] for f in rec["findings"] if f["source"] == "model"] == [f"board#{BID_06}"]
      and rec["calls"]["unchanged"] == 6, (len(calls()), rec["calls"], rec["findings"]))
f2b = dict(f2); k, d = doing(57, 1, nxt=f"home-agent: build it\nhome-agent: tick board#{BID_21}", expected_by=local(now + 30 * H), expected_reason="the build"); d["written_at"] = now - 60; f2b[k] = d
AR._record_path(now).unlink()
rec = go(f2b)
check("an item written since is judged again (one call, for that item only)", len(calls()) == 1 and f"Item board#{BID_47}:" in calls()[0]["stdin"], [c["stdin"][:30] for c in calls()])

# ---- 9. three failed calls in a row end the calls
rec_clear(); fake("exit")
rec = go(f2)
check("three failed calls in a row stop the calls; failures are counted, not judged 'no'", len(calls()) == 3 and rec["calls"]["failed"] == 3 and rec["judged"] == {} and rec["calls"]["notes"], (len(calls()), rec["calls"]))
fake()

# ---- 10. the threshold: ONE message to the builder, naming the check and the item ids; none when no check reaches it
many = build(*[item(24 + k, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one") for k in range(6)], *[clean(32 + k) for k in range(30)])
rec_clear(); rec = go(many)
check("six findings of one check, threshold 5: ONE message to falcon-engineer through the push path, naming the check and the item ids", len(pushed) == 1 and pushed[0][0] == "falcon-engineer"
      and "ask-missing: 6 findings" in pushed[0][1] and all(f"board#{9214 + k}" in pushed[0][1] for k in range(6)), pushed)
check("…recorded in the run's messages as the threshold kind", sum(1 for m in rec["messages"] if m.get("kind") == "threshold") == 1, rec["messages"])
_cfg.CFG["audit"]["threshold"] = 7
rec_clear(); rec = go(many)
check("threshold 7: six findings trip no check (the tightening share is 17%, under 20%), no message to the builder", pushed == [], pushed)
_cfg.CFG["audit"]["threshold"] = 5
few = build(item(44, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one"), *[clean(14 + k) for k in range(20)])
rec_clear(); rec = go(few)
check("one finding in 21 open items: no threshold message", pushed == [], pushed)
rec_clear(); rec = go(build(*[item(100 + k, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one") for k in range(3)], *[clean(110 + k) for k in range(5)]))
check("more than 20% of the open items flagged is a tightening trip: one message naming it", len(pushed) == 1 and "open items flagged" in pushed[0][1], pushed)
_cfg.CFG["audit"]["threshold"] = 1
rec_clear(); rec = go(f1)
check("two runs' worth of trips in one run still send ONE message", len(pushed) == 1, pushed)
_cfg.CFG["audit"]["threshold"] = 5

# ---- 11. the unmoved flag: a finding on the previous run whose item has had no write since goes to the builder, as a job, and onto `stuck`
rec_clear()
prev_day = dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date().isoformat()
(T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10,
      "findings": [{"id": "board#1", "project": "projects/alpha", "owner": "Oliver", "mover": "Oliver", "category": "ask-missing", "detail": "x"},
                   {"id": "board#2", "project": "projects/alpha", "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "y"}], "by_session": {}, "by_category": {}}))
f3 = build(*[(k, d) for k, d in f1.items()])
k2, d2 = f3["a2"] and ("a2", dict(f3["a2"])); d2["written_at"] = now - 60; d2["updated"] = now - 60; f3["a2"] = d2          # the board item was written since: not unmoved
f3["a1"]["updated"] = now - 3 * 86400; f3["a1"]["written_at"] = now - 3 * 86400; f3["a1"]["written_by"] = "home-agent"                     # the board item was not
rec = go(f3)
check("an item flagged on the previous run and not written since is on `stuck` with its first_flagged day", [(s["id"], s["first_flagged"]) for s in rec["stuck"]] == [("board#1", prev_day)], rec["stuck"])
jobs = [t for to, t, fy in sent if to == "alpha-builder"]
check("…and goes to the project's builder as ONE job message", len(jobs) == 1 and "board#1" in jobs[0] and "board#2" not in jobs[0] and "unmoved since " + prev_day in jobs[0], jobs)

# ---- 12. idle-pass: the daily run no longer checks stale (the dates pass and the silence pass do), so it counts no idle-pass entry and makes no finding for an item the idle pass poked
ip = build(*[(k, d) for k, d in f1.items() if k in ("a6", "a7")], doing(2, 5, wake=local(now - 2 * H)))
ip["a2"]["metadata"]["idle"] = {"poked": now - 600}; ip["a2"]["confirmed"] = now - 3 * H
rec_clear(); rec = go(ip)
check("an item the idle pass poked, past its wake, is no finding and no message of the daily run (the dates pass counts it as idle-pass)", rec["findings"] == [] and not rec["by_category"].get("idle-pass")
      and all("board#2" not in t for to, t, fy in sent if not fy), (rec["findings"], rec["by_category"], sent))

# ---- 13. an older-than-page suspect
rec_clear()
pg = lambda p: (f"- board#{BID_11} landed on the page today: the vendor said yes\n- other line", now - H) if p == "projects/alpha" else ("", None)
op = build(doing(21, 3, expected_by=local(now + 30 * H), expected_reason="the build"), clean(121))
fake(answers={f"board#{BID_11}": YES("older-than-page", "the page says the vendor said yes", "write it on the item")})
rec = go(op, env_=env(page_of=pg))
check("older-than-page: the page is newer than the item's write and mentions it: one call, a finding", len(calls()) == 1 and "the project page" in calls()[0]["stdin"] and ids(rec, "older-than-page") == [f"board#{BID_11}"], (calls(), rec["findings"]))
fake()

# ---- 14. the shared engine: the stall pass reads the pane through mover_state (the board check no longer does: silence is the silence pass's)
rows = T / "home/.claude/sessions"
def pane_row(status, ago):
    (rows / "1.json").write_text(json.dumps({"kind": "interactive", "pid": os.getpid(), "name": "home-agent", "sessionId": "s-1", "status": status, "statusUpdatedAt": (now - ago) * 1000.0}))
for status, ago, idle in (("idle", 3 * H, True), ("shell", 3 * H, True), ("busy", 3 * H, False)):
    pane_row(status, ago)
    st, at = MS.status(MS.pane_row({"home-agent"}, {"s-1"}, rows))
    act = stall.action({"step": 0, "last": 0.0}, st, at, 0.0, now, 10.0)
    check(f"shared engine, pane {status}: the stall pass acts ({act!r}) exactly when the pane has had no turn", (act == "resend") == idle, (act, st, at))
check("shared engine: idle_seconds counts from the later of the status change and the floor (an item that just arrived is not stalled on the pane's age)", MS.idle_seconds("idle", now - 3 * H, now, now - 600) == 600.0
      and MS.idle_seconds("busy", now - 3 * H, now) == 0.0 and MS.idle_seconds("", 0.0, now) == 0.0)
(rows / "1.json").unlink()

# ---- 15. [audit] mode: script (the default) runs the script, agent cues the agent; the button path starts a detached run
check("[audit] mode defaults to script, an unknown value to script", _cfg.audit_mode() == "script" and (_cfg.CFG["audit"].__setitem__("mode", "bogus") or _cfg.audit_mode() == "script"))
_cfg.CFG["audit"]["mode"] = "script"
(T / "state/audit").exists() and rec_clear()
for gid, d in f1.items(): (T / "store/a" / f"{gid[1:]}.json").write_text(json.dumps(d))
AR._deliver = deliver; audit._push = lambda agent, text: (pushed.append((agent, text)), (True, "delivered"))[1]
sent.clear(); pushed.clear(); fake()
with contextlib.redirect_stderr(io.StringIO()): code, text = audit.cue("scheduled", now=now, inline=True)      # the default pages stage has no token here: its stderr line is expected
check("script mode, the timer's way (inline): 202, the run happened in this process, no push to an agent", code == 202 and text.startswith("audit run:") and audit.last()["finished"] is not None
      and not [p for p in pushed if p[0] == _cfg.audit_agent()] and sent, (code, text, pushed))
spawned = []
REAL_SPAWN = audit._spawn_run
audit._spawn_run = lambda started: spawned.append(started)
rec_clear(); sent.clear(); pushed.clear()
code, text = audit.cue("button", now=now)
check("script mode, the button's way: 202 at once, the running record written, the run started detached", code == 202 and text == "audit run started" and len(spawned) == 1 and spawned[0] == now
      and audit.running(now + 5) is not None and audit.running(now + 5)["started"] == now, (code, text, spawned))
check("…a second cue while it runs: 409", audit.cue("button", now=now + 5)[0] == 409)
check("the detached run refuses a --started that names no running record (nothing done), and continues the one that is there",
      AR.main(["--started", "12345.0"]) == 1 and audit.running(now + 5) is not None)
res = AR.run(now=now + 5, started=now, items=f1, anchors={}, env=env(), rubric=RUBRIC_TEXT)
check("…the run given its --started finishes that very record", res["started"] == now and audit.running(now + 10) is None and audit.last()["finished"] is not None)
_cfg.CFG["audit"]["mode"] = "agent"; rec_clear(); pushed.clear(); sent.clear()
code, text = audit.cue("button", now=now)
check("agent mode: the old cue to the audit agent (rollback), no script run", code == 202 and pushed and pushed[0][0] == _cfg.audit_agent() and sent == [] and audit.last() is None, (code, pushed))
_cfg.CFG["audit"]["mode"] = "script"

# ---- 17. review round: a crashed run is finished with its error, never silent, never holds the lock (item 1)
import contextlib, io, signal, subprocess, threading, fcntl
AUD = T / "state/audit"
def cues_clear(): (AUD / "cues.jsonl").unlink(missing_ok=True)
def cues(): return [json.loads(l) for l in (AUD / "cues.jsonl").read_text().splitlines()] if (AUD / "cues.jsonl").exists() else []
def quiet(fn, *a):
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        try: rc = fn(*a)
        except BaseException as e: rc = e
    return rc, err.getvalue(), out.getvalue()
_real_judge = AR.judge
def boom(*a, **k): raise RuntimeError("boom in the middle of the run")
rec_clear(); cues_clear()
_cfg.CFG["audit"]["mode"] = "script"; _cfg.CFG["audit"]["enabled"] = True
AR.judge = boom
try:
    code, text = audit.cue("scheduled", now=now + 100, inline=True)
finally:
    AR.judge = _real_judge
crash = audit.last()
check("an exception mid-run: the cue answers 503 with the reason", code == 503 and "RuntimeError" in text and "boom" in text, (code, text))
check("…the record is finished with `error` set (not left running)", crash is not None and crash["finished"] is not None and crash.get("error", "").startswith("RuntimeError: boom") and crash["started"] == now + 100
      and audit.running(now + 200) is None, crash)
check("…cues.jsonl has the run's own line (code 500, the error) and the cue's 503", [c["code"] for c in cues()] == [500, 503] and "boom" in cues()[0]["text"] and cues()[0]["reason"] == "script run", cues())
spawned.clear()
code, text = audit.cue("button", now=now + 200)
check("…a later cue is not 409: it starts a run", code == 202 and spawned == [now + 200], (code, text))
# the detached child: claim, then main --started; the run raises -> the record is finished with the error, the exception reaches the child's stderr (run.log)
rec_clear(); cues_clear()
t_a = time.time() - 30
sig_before = signal.getsignal(signal.SIGTERM)
check("claim writes the running record under the lock (202)", audit.claim(t_a) == (202, "") and audit.running(t_a + 1) is not None and (AUD / "cue.lock").exists())
AR.judge = boom
try:
    rc, err, _ = quiet(AR.main, ["--started", repr(t_a)])
finally:
    AR.judge = _real_judge
check("the detached run that raises: the exception propagates (to run.log in the real child), the record is finished with `error`, the lock is gone", isinstance(rc, RuntimeError)
      and audit.running(t_a + 1) is None and audit.last()["error"].startswith("RuntimeError") and [c["code"] for c in cues()] == [500], (rc, audit.last(), cues()))
check("…and the SIGTERM handler is put back after the run", signal.getsignal(signal.SIGTERM) is sig_before)
def term_in_run(*a, **k):
    h = signal.getsignal(signal.SIGTERM)
    assert callable(h) and h is not sig_before, h
    h(signal.SIGTERM, None)                                                     # what a systemctl stop, a reboot or the unit's TimeoutStartSec would deliver (called directly, no real signal)
rec_clear(); cues_clear()
AR.judge = term_in_run
try:
    rc, err, _ = quiet(AR.main, [])
finally:
    AR.judge = _real_judge
check("a SIGTERM during `audit.py run` ends it through the crash path: SystemExit, the record finished with the reason, the handler restored", isinstance(rc, SystemExit) and rc.code == 143
      and audit.running() is None and audit.last()["error"].startswith("SystemExit") and signal.getsignal(signal.SIGTERM) is sig_before, (rc, audit.last()))
# the timer unit runs `audit.py cue scheduled`: cue -> claim -> _cue_script(inline) -> run(), not audit_run.main
rec_clear(); cues_clear()
AR.judge = term_in_run
try:
    code, text = audit.cue("scheduled", now=time.time() - 5, inline=True)           # the handler raises SystemExit, which is no Exception: the cue lets it through, as the process ends
except SystemExit as e:
    code, text = "exit", e.code
finally:
    AR.judge = _real_judge
check("a SIGTERM during the timer's cue (inline run) ends it too: SystemExit(143), the record finished with the reason, a line in cues.jsonl, the handler restored", (code, text) == ("exit", 143)
      and audit.running() is None and audit.last()["error"].startswith("SystemExit") and [c["code"] for c in cues()] == [500] and "SystemExit" in cues()[0]["text"]
      and signal.getsignal(signal.SIGTERM) is sig_before, (code, text, audit.last(), cues()))
spawned.clear()
check("…and the next cue is not held back by it (not 409)", audit.cue("button", now=time.time())[0] == 202 and len(spawned) == 1)
rec_clear(); cues_clear(); fake()
t_b = time.time() - 20
audit.claim(t_b)
rc, err, out = quiet(AR.main, ["--started", repr(t_b)])
check("a detached run that finishes puts its end in cues.jsonl too (code 200, reason script run)", rc == 0 and [(c["code"], c["reason"]) for c in cues()] == [(200, "script run")] and audit.running() is None
      and audit.last()["finished"] is not None and "error" not in audit.last(), (rc, cues(), out))
rec_clear(); cues_clear()
# the detached child logs to <audit state>/run.log
pops = []
class FakePopen:
    def __init__(self, argv, **kw): pops.append((argv, kw))
_real_popen = subprocess.Popen; subprocess.Popen = FakePopen
try:
    REAL_SPAWN(now + 400)
finally:
    subprocess.Popen = _real_popen
kw = pops[0][1] if pops else {}
check("the detached child's stdout and stderr go to a log file under the audit state dir (not DEVNULL)", pops and getattr(kw.get("stdout"), "name", "") == str(AUD / "run.log") and kw.get("stderr") == subprocess.STDOUT
      and kw.get("start_new_session") is True and "--started" in pops[0][0], pops)
check("…the log gets a header line for the run", "audit.py run --started" in (AUD / "run.log").read_text(encoding="utf-8"))

# ---- 18. `audit.py run` without --started passes the cue's guards (item 2)
rec_clear(); fake(); sent.clear(); pushed.clear()
audit.start_t = None
AR.start_record(time.time() - 60)                                               # a run is in progress
rc, err, _ = quiet(AR.main, [])
check("a run in progress: audit.py run is refused with exit 1 and says so", rc == 1 and "is running since" in err and "nothing done" in err and len(list(AUD.glob("run-*.json"))) == 1, (rc, err))
rc, err, out = quiet(AR.main, ["--dry-run"])
check("…a dry run is not refused", rc == 0 and "audit dry run" in out, (rc, err, out[:200]))
rec_clear(); _cfg.CFG["audit"]["enabled"] = False
rc, err, _ = quiet(AR.main, [])
check("[audit] enabled false: refused with exit 1, no record written", rc == 1 and "not enabled" in err and list(AUD.glob("run-*.json")) == [], (rc, err))
rc, err, out = quiet(AR.main, ["--dry-run"])
check("…a dry run is not refused", rc == 0 and "audit dry run" in out, (rc, err))
_cfg.CFG["audit"]["enabled"] = True; _cfg.CFG["audit"]["mode"] = "agent"; reset_calls()
rc, err, _ = quiet(AR.main, [])
check("mode agent: refused with exit 1, a line that names the mode, no record, no call", rc == 1 and 'mode is "agent"' in err and list(AUD.glob("run-*.json")) == [] and calls() == [], (rc, err))
rc, err, out = quiet(AR.main, ["--dry-run"])
check("…a dry run is not refused", rc == 0 and "audit dry run" in out, (rc, err))
_cfg.CFG["audit"]["mode"] = "script"
rc, err, out = quiet(AR.main, [])
check("every guard passed: audit.py run goes, writes its record finished, prints the record's name", rc == 0 and audit.last()["finished"] is not None and audit.running() is None
      and re.search(r"record run-\d{4}-\d\d-\d\d-\d{6}\.json", out), (rc, err, out))

# ---- 19. a second run the same day keeps the first one's record; readers take the newest (item 3)
rec_clear(); fake()
go(f2, now=now)
go(f2, now=now + 2)
files = sorted(p.name for p in AUD.glob("run-*.json"))
check("two runs on one day: two record files, named by the start time", len(files) == 2 and all(re.fullmatch(r"run-\d{4}-\d\d-\d\d-\d{6}\.json", n) for n in files), files)
check("runs() lists both, the later start first; last() and status() read the later one", [r["started"] for r in audit.runs()] == [now + 2, now] and audit.last()["started"] == now + 2
      and audit.status(now + 10)["last"]["started"] == now + 2 and {r["date"] for r in audit.runs()} == {today}, [r["started"] for r in audit.runs()])
reset_calls(); go(f2, now=now + 4)
check("the next run carries `judged` from the newest record (the verdicts hold until an item is written): no call", calls() == [], len(calls()))
plain = AUD / f"run-{today}.json"
plain.write_text(json.dumps({"started": now + 10, "finished": now + 20, "items_read": 1, "findings": []}))
check("the agent's plain run-<date>.json is still read, and the newest by `started` wins within the day", audit.last()["started"] == now + 10 and audit.runs()[0]["date"] == today, audit.runs(1))
plain.write_text(json.dumps({"started": now - 5, "finished": now - 1, "items_read": 1, "findings": []}))
check("…an older plain record does not outrank a later script record", audit.last()["started"] == now + 4, audit.last())
plain.unlink()
prev, hist = AR.previous(now + 8 * H)
check("previous(): the newest finished record at least 6 hours old, history newest first", prev["started"] == now + 4 and [h["started"] for h in hist] == [now + 4, now + 2, now], (prev and prev["started"], [h["started"] for h in hist]))
check("a record file with a stamp that is not a time of day is not a record", (AUD / "run-2026-10-05-abc.json").write_text("{}") is not None and all(r["started"] in (now, now + 2, now + 4) for r in audit.runs()))
(AUD / "run-2026-10-05-abc.json").unlink()

# ---- 20. the wall-clock bound (item 4)
check("[audit] max_minutes: default 100, kept under the unit's 2 h (a larger value reads as 110), nonsense as the default",
      _cfg.audit_max_minutes() == 100 and (_cfg.CFG["audit"].__setitem__("max_minutes", 500) or _cfg.audit_max_minutes() == 110)
      and (_cfg.CFG["audit"].__setitem__("max_minutes", 0) or _cfg.audit_max_minutes() == 100) and (_cfg.CFG["audit"].__setitem__("max_minutes", "x") or _cfg.audit_max_minutes() == 100))
_cfg.CFG["audit"].pop("max_minutes", None)
rec_clear(); fake()
clk = lambda: now + len(calls()) * 40 * 60                                      # every model call costs 40 minutes on this clock
rec = go(f2, env_=env(clock=clk))
check("100 minutes pass after 3 calls (40 min each): no 4th call is begun, the rest of the suspects wait", len(calls()) == 3 and rec["calls"]["made"] == 3 and rec["calls"]["timed_out"] is True
      and rec["calls"]["max_minutes"] == 100 and any("100 minutes" in n and "3 suspect" in n for n in rec["calls"]["notes"]), (len(calls()), rec["calls"]))
check("…the three judged are on the record (judged again next run is only the other three), the summary says where it stopped", sorted(rec["judged"]) == SUSP6[:3]
      and any("stopped at the 100-minute limit" in t for to, t, fy in sent if to == "projects/example"), (sorted(rec["judged"]), [t for to, t, fy in sent if fy]))
_cfg.CFG["audit"]["max_minutes"] = 50
rec_clear(); rec = go(f2, env_=env(clock=clk))
check("[audit] max_minutes = 50: 2 calls (80 minutes after the second)", len(calls()) == 2 and rec["calls"]["timed_out"] is True and rec["calls"]["max_minutes"] == 50, (len(calls()), rec["calls"]))
_cfg.CFG["audit"].pop("max_minutes", None)
rec_clear(); rec = go(f2)
check("within the time (the real clock): all six suspects are called, timed_out false", len(calls()) == 6 and rec["calls"]["timed_out"] is False, rec["calls"])

# ---- 21. a finding whose message fails goes to the project's -main (item 5)
def deliver_down(*down):
    def d(to, text, fyi=False):
        sent.append((to, text, fyi))
        return (False, "[503] session not live") if to in down else (True, "[200] ok")
    return d
rec_clear(); fake()
rec = go(f1, env_=env(deliver=deliver_down("home-agent")))
fb = [m for m in rec["messages"] if m.get("kind") == "fallback"]
msg_main = [t for to, t, fy in sent if to == "alpha-main" and "could not be reached" in t]
failed = [m for m in rec["messages"] if m["to"] == "home-agent"]
check("the mover's message fails: its findings go to the project's -main agent, [for Oliver] first, naming who could not be reached", len(msg_main) == 1 and msg_main[0].startswith("[for Oliver]")
      and "for home-agent" in msg_main[0] and "board#4 · next rules" in msg_main[0] and "board#5" not in msg_main[0] and "· stale ·" not in msg_main[0], msg_main)
check("…the message log records the failed one and the fallback beside it", len(failed) == 1 and failed[0]["delivered"] is False and len(fb) == 1 and fb[0]["to"] == "alpha-main" and fb[0]["for"] == "home-agent"
      and fb[0]["delivered"] is True and fb[0]["lines"] == failed[0]["lines"], rec["messages"])
check("…and the findings of the other movers are not duplicated to the -main agent", "board#3 · stuck-elsewhere" not in msg_main[0])
rec_clear(); rec = go(f1, env_=env(deliver=deliver_down("home-agent", "alpha-main")))
fb = [m for m in rec["messages"] if m.get("kind") == "fallback"]
check("the -main agent is down too: the fallback is recorded as not delivered, the run still finishes", len(fb) == 1 and fb[0]["delivered"] is False and rec["finished"] is not None and "error" not in rec, rec["messages"])
rec_clear(); rec = go(f1, env_=env(deliver=deliver_down("alpha-main")))
check("a finding already addressed to the -main agent that fails has no one to fall back to: no fallback message", not [m for m in rec["messages"] if m.get("kind") == "fallback"], rec["messages"])
def deliver_raises(to, text, fyi=False):
    sent.append((to, text, fyi))
    if to == "home-agent": raise OSError("connection refused")
    return True, "ok"
rec_clear(); rec = go(f1, env_=env(deliver=deliver_raises))
check("a delivery that raises is a failed delivery (the run does not die), and falls back too", rec["finished"] is not None and "error" not in rec and any(m.get("kind") == "fallback" and m["for"] == "home-agent" and m["delivered"] for m in rec["messages"])
      and any(m["to"] == "home-agent" and "connection refused" in m["said"] and m["delivered"] is False for m in rec["messages"]), rec["messages"])

# ---- 22. the cue's check and the running record are one step under an exclusive lock (item 6)
orig_running = audit.running
def slow_running(n=None):
    r = orig_running(n); time.sleep(0.3); return r                             # both cues would pass the check before either writes its record, without the lock
def two_cues(nows):
    rec_clear(); cues_clear(); spawned.clear(); results = []
    def one(tag, n): results.append((tag, audit.cue("button", now=n)[0]))
    ths = [threading.Thread(target=one, args=(t, n)) for t, n in zip("ab", nows)]
    audit.running = slow_running
    try:
        for th in ths: th.start()
        for th in ths: th.join(20)
    finally:
        audit.running = orig_running
    return sorted(c for _, c in results), len(spawned)
real_lock = audit._cue_lock
audit._cue_lock = contextlib.nullcontext                                        # the control: with no lock the same two cues both pass the check
try:
    unlocked = two_cues((now + 1000, now + 1001))
finally:
    audit._cue_lock = real_lock
check("without the lock, two cues at once both start a run (the test has teeth)", unlocked == ([202, 202], 2), unlocked)
locked = two_cues((now + 1000, now + 1000))                                   # the same `now`: whichever gets the lock first, the other must find its record
check("two cues at once under the lock: exactly one 202 and one 409, one run started, one running record", locked == ([202, 409], 1) and len(list(AUD.glob("run-*.json"))) == 1, locked)
check("…the lock file is in the audit state dir", (AUD / "cue.lock").is_file())
rec_clear(); spawned.clear()
holder = open(AUD / "cue.lock", "a+"); fcntl.flock(holder, fcntl.LOCK_EX)
res = []
th = threading.Thread(target=lambda: res.append(audit.cue("button", now=now + 2000)[0])); th.start(); th.join(0.6)
waited = th.is_alive() and not res and not list(AUD.glob("run-*.json"))
fcntl.flock(holder, fcntl.LOCK_UN); holder.close(); th.join(20)
check("a cue waits while another process holds the lock (no check, no record), and goes on when it is released", waited and res == [202] and len(spawned) == 1, (waited, res, spawned))
rec_clear(); cues_clear(); spawned.clear()
holder = open(AUD / "cue.lock", "a+"); fcntl.flock(holder, fcntl.LOCK_EX)           # the lock is held only around check + record: an inline run takes it for nothing of its own
res = []
th = threading.Thread(target=lambda: res.append(quiet(lambda: audit.cue("scheduled", now=now + 3000, inline=True))[0][0])); th.start(); th.join(0.4)
blocked = th.is_alive()
fcntl.flock(holder, fcntl.LOCK_UN); holder.close(); th.join(60)
lk = open(AUD / "cue.lock", "a+")
try:
    fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); free_after = True            # nothing keeps the lock after the cue (and its run) are done
except OSError:
    free_after = False
finally:
    lk.close()
check("an inline run waits for the lock like any cue, and releases it once the running record is written (not held across the run)", blocked and res == [202] and free_after, (blocked, res, free_after))
rec_clear(); cues_clear()

# ---- 23. the unit and the CLI text
unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8")
check("the unit still starts `stackshot audit cue scheduled` (the mode switch lives in config) and carries the bedrock lane for the model calls", "stackshot audit cue scheduled" in unit and "X-Model-Lane=bedrock" in unit and "X-Model-Lane=max" not in unit, unit)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/audit/audit.py"), "bogus"], capture_output=True, text=True, env=dict(os.environ))
check("audit.py usage lists the run verb", r.returncode == 2 and "run [--dry-run]" in r.stderr, r.stderr)

# ---- 24. stuck-elsewhere reads a waiting item's post-wake mover
WAKE = (dt.datetime.now(ZONE) + dt.timedelta(days=5)).strftime("%Y-%m-%d")
def parked_at(i, nxt, wake, **kw): return item(i, wrote=now - H, state="parked", needs=["home-agent"], hold=True, wake=wake, wait_basis={"text": "a booked visit", "wake": wake, "by": "x", "at": now}, next=nxt, **kw)
def parked(i, nxt, **kw): return parked_at(i, nxt, WAKE, **kw)
PAST = (dt.datetime.now(ZONE) - dt.timedelta(days=2)).strftime("%Y-%m-%d")                 # a wake that has come: the wait is over, the post-wake mover is to take the item
def outside(i, nxt, **kw): return item(i, wrote=now - H, state="outside", needs=["external"], party="Acme legal", chase=WAKE, next=nxt, **kw)
f24 = build(parked(24, "alpha-builder: after the wake, check the build"),                                  # post-wake mover not named (defaults to home-agent): the step names the session that takes it
            parked(22, "home-agent: after the wake, check the build", post_wake_mover="home-agent"),             # the step is the named post-wake session's
            outside(71, "ops-other: chase Acme and tell Oliver"),                                         # a relay wait: a session's chase step, post-wake not named
            outside(91, "Oliver: pass on Acme's reply to the builder"),                                      # a relay wait is a wait on Oliver
            parked_at(53, "Oliver: review the tab", PAST, post_wake_mover="home-agent"),                      # a Oliver step on a wait that is not on him, its wake come
            parked_at(30, "ops-other: do the second part", PAST, post_wake_mover="home-agent"),             # a session's step beside a post-wake mover the writer named, its wake come
            parked_at(73, "Oliver: review the tab", PAST),                                                  # …the same, with the post-wake mover defaulted (home-agent)
            doing(13, 1, nxt="ops-other: do the first part", expected_by=local(now + 30 * H), expected_reason="the build"))   # alive: unchanged
rec = fil(f24)
check("a waiting item whose first step is a session that takes it after the wake (post-wake not named, or named and equal) is no finding", not {f"board#{BID_14}", f"board#{BID_12}"} & set(ids(rec, "stuck-elsewhere")), rec["findings"])
check("a relay wait with a session's chase step, or with Oliver's own step, is no finding", not {f"board#{BID_61}", f"board#{BID_75}"} & set(ids(rec, "stuck-elsewhere")), rec["findings"])
check("a true mismatch still is once the wake has come: Oliver's step on a wait that is not on him, a session's step beside a named post-wake mover", sorted(ids(rec, "stuck-elsewhere")) == sorted([f"board#{BID_43}", f"board#{BID_20}", f"board#{BID_63}", f"board#{BID_03}"]), rec["findings"])
check("…and an alive item keeps its rule (the opener must be its mover)", "ops-other" in next(f["detail"] for f in rec["findings"] if f["id"] == f"board#{BID_03}" and f["category"] == "stuck-elsewhere"), rec["findings"])

# Oliver is the post-wake mover, named: a session chases and then he acts, so neither his step nor a session's step is a finding
f24h = build(parked(58, "ops-other: chase the answer and tell Oliver", post_wake_mover="Oliver"), parked(59, "Oliver: decide after the wake", post_wake_mover="Oliver"))
rec = fil(f24h)
check("Oliver the named post-wake mover: a session's step and his own step are no finding", ids(rec, "stuck-elsewhere") == [], rec["findings"])
# a model that cannot read the item must not end the run: the old path (the opener against the mover) runs
_it50 = f24["a9203"]; _known = {k.lower() for k in ROLES} | {AR._norm(k) for k in ROLES}
_real_derive = AR._model.derive
def _bad_derive(*a, **k): raise ValueError("malformed item")
AR._model.derive = _bad_derive
try:
    _res = AR.check_stuck_elsewhere(_it50, _it50["metadata"], "home-agent", _known, 0.0, None, now)
finally:
    AR._model.derive = _real_derive
check("a derive that raises is not a crash: the old path runs (a session's step beside another mover is a finding)", _res is not None and _res[0] == "ops-other", _res)

# ---- 24b. stuck-elsewhere on an alive item the owner moves: a session's step is the one for after his answer, which `then` names
def owner_item(i, nxt, **kw): return item(i, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", ask="which one?", next=nxt, **kw)
f24o = build(owner_item(14, "alpha-main: apply Oliver's pick, then close", then="alpha-main"),                          # then named, the opener is that session
             owner_item(55, "ops-other: apply Oliver's pick, then close"),                                              # no then named: the step is the only word on who takes it
             owner_item(50, "ops-other: apply Oliver's pick, then close", then="alpha-main"),                           # then named as another session than the opener
             doing(56, 1, nxt="ops-other: do the first part", expected_by=local(now + 30 * H), expected_reason="the build"),   # an agent moves it, another session opens
             owner_item(93, "alpha-main: apply Oliver's pick (the do-not-file list, or his second step), then close", then="alpha-main"))   # the shape of a real item
rec = fil(f24o)
check("an item the owner moves is no stuck-elsewhere finding when the opener is the explicit `then`, or when no `then` is named", not {f"board#{BID_04}", f"board#{BID_45}", f"board#{BID_77}"} & set(ids(rec, "stuck-elsewhere")), rec["findings"])
check("…still a finding beside an explicit `then` that is another session, and for an alive item a session moves", ids(rec, "stuck-elsewhere") == [f"board#{BID_40}", f"board#{BID_46}"], rec["findings"])
check("…the model reads the owner as mover with `then` explicit on the item with the live shape", (lambda m: m.owner_moves and m.then == "alpha-main" and m.then_explicit)(AR._model.derive(f24o["a9277"], now, None)))
rec_clear()

# ---- 25. a recipient that is a front agent: the lines go to the project's key, unmarked
go = go_all                                  # sections 25 to 25d are about delivery, whichever check made the finding: they run every code check (see go_all)
FRONT_ID = "00000000-0000-4000-8000-000000000051"                      # a session id the role map does not know as a front agent
def deliver_front(to, text, fyi=False):
    sent.append((to, text, fyi))
    return (False, "[400] Refused: home-front is a front agent of projects/alpha, a session Oliver talks to, and it takes a message only when the first line carries [for Oliver]") if to == FRONT_ID else (True, "[200] ok")
f25 = build(item(35, wrote=now - 5 * H, state="doing", needs=[FRONT_ID], next=f"{FRONT_ID}: build it", wake=local(now - 2 * H)))
rec_clear(); fake(); rec = go(f25, env_=env(deliver=deliver_front))
proj = [m for m in rec["messages"] if m.get("kind") == "project"]
to_key = [t for to, t, fy in sent if to == "projects/alpha"]
check("a front agent refuses the message: the lines go to projects/alpha, with no [for Oliver] mark", len(to_key) == 1 and not to_key[0].startswith("[for Oliver]") and f"board#{BID_25} · stale" in to_key[0] and f"for {FRONT_ID}" in to_key[0], sent)
check("…recorded as kind project beside the failed one, and nothing goes to the -main agent as a fallback", len(proj) == 1 and proj[0]["to"] == "projects/alpha" and proj[0]["delivered"] is True and proj[0]["for"] == FRONT_ID
      and not [m for m in rec["messages"] if m.get("kind") == "fallback"] and not [t for to, t, fy in sent if to == "alpha-main" and "could not be reached" in t], rec["messages"])
rec_clear(); rec = go(f25, env_=env(deliver=deliver_down(FRONT_ID)))
check("any other failure keeps the -main fallback, marked [for Oliver]", [m for m in rec["messages"] if m.get("kind") == "fallback"] and not [m for m in rec["messages"] if m.get("kind") == "project"]
      and any(to == "alpha-main" and t.startswith("[for Oliver]") and "could not be reached" in t for to, t, fy in sent), (rec["messages"], sent))
f25b = build(item(61, wrote=now - 5 * H, state="doing", needs=[FRONT_ID], next=f"{FRONT_ID}: build it", wake=local(now - 2 * H), project="alpha"))
rec_clear(); rec = go(f25b, env_=env(deliver=deliver_front))
check("a bare-slug project (no '/') goes to projects/<slug> as well", [t for to, t, fy in sent if to == "projects/alpha"] and any(m.get("kind") == "project" and m["to"] == "projects/alpha" for m in rec["messages"]), (rec["messages"], sent))
f25c = build(item(62, wrote=now - 5 * H, state="doing", needs=[FRONT_ID], next=f"{FRONT_ID}: build it", wake=local(now - 2 * H), project=""))
rec_clear(); rec = go(f25c, env_=env(deliver=deliver_front))
check("a finding with no project has no page key to go to: the -main fallback, [for Oliver] first", not [m for m in rec["messages"] if m.get("kind") == "project"] and any(m.get("kind") == "fallback" for m in rec["messages"])
      and any(to == "alpha-main" and t.startswith("[for Oliver]") and "could not be reached" in t for to, t, fy in sent), (rec["messages"], sent))
rec_clear()

# ---- 25b. stuck-elsewhere is no finding on a deliberate wait that is still on, and on the owner's step dated after the wake
ROLES["beta-main"] = {"role": "front", "project": "projects/beta"}
LATER = (dt.datetime.now(ZONE) + dt.timedelta(days=25)).strftime("%Y-%m-%d")                                # a day well after WAKE
f25p = build(parked(32, "Oliver: review the tab", post_wake_mover="beta-main"),                                         # parked, wake ahead, the owner's step, the post-wake mover a front agent of another project
             parked(70, "ops-other: do the second part", post_wake_mover="home-agent"),                                  # parked, wake ahead, a session's step beside a named post-wake mover
             item(17, wrote=now - H, state="parked", needs=["home-agent"], hold=True, next="Oliver: review the tab"),      # on hold with no wake at all
             parked_at(49, "Oliver: review the tab", PAST, post_wake_mover="home-agent"),                                # control: the wake has come, the same step is a finding
             doing(18, 1, nxt=f"Oliver: sign off after {LATER}", wake=WAKE),                                              # alive, a check-back wake ahead, his step dated for after it
             doing(10, 1, nxt="Oliver: sign off", wake=WAKE))                                                           # control: the same step with no date is a finding
rec = fil(f25p)
check("a parked or held item with a wake ahead (or none) is no stuck-elsewhere finding, whoever the post-wake mover is and whichever step is first", not {f"board#{BID_22}", f"board#{BID_60}", f"board#{BID_07}"} & set(ids(rec, "stuck-elsewhere")), rec["findings"])
check("…the owner's step dated for after the item's wake is none either", f"board#{BID_08}" not in ids(rec, "stuck-elsewhere"), rec["findings"])
check("…while the same shapes with the wake come, or the step undated, still are", {f"board#{BID_39}", f"board#{BID_00}"} <= set(ids(rec, "stuck-elsewhere")), rec["findings"])
step_day = AR._dw.step_wait_day
check("dated_wait.step_wait_day reads the day a step waits for, and None for a deadline or an undated step",
      step_day("Oliver: sign off after 2026-12-01", dt.date(2026, 11, 1)) == dt.date(2026, 12, 1) and step_day("Oliver: sign off, due 2026-12-01", dt.date(2026, 11, 1)) is None and step_day("Oliver: sign off", dt.date(2026, 11, 1)) is None)

# ---- 25c. a finding goes to a background mover; any other recipient goes to the project's page key, never straight to a front agent
f25r = build(item(44, wrote=now - 5 * H, state="doing", needs=["beta-main"], next="beta-main: build it", wake=local(now - 2 * H)),           # stale, mover a front agent of another project
             item(81, wrote=now - 5 * H, state="doing", needs=["home-front"], next="home-front: build it", wake=local(now - 2 * H)),         # stale, mover a front agent of this project
             item(82, wrote=now - 5 * H, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(now - 2 * H)),        # stale, mover a background agent
             doing(83, 1, nxt="Oliver: decide", expected_by=local(now + 30 * H), expected_reason="the build"))                                                                 # stuck-elsewhere: the owner's step, the mover a background agent
rec_clear(); fake(); rec = go(f25r)
to_of = lambda n: sorted({to for to, t, fy in sent if f"board#{fid(n)} ·" in t})
check("a stale finding on an item a front agent moves goes to the project's page key, unmarked, and to no front agent", to_of(44) == ["projects/alpha"] and to_of(81) == ["projects/alpha"]
      and not any(t.startswith("[for Oliver]") for to, t, fy in sent if to == "projects/alpha") and not any(to in ("beta-main", "home-front") for to, t, fy in sent), sent)
check("…and one on a background agent's item goes to that agent", to_of(82) == ["home-agent"], sent)
check("a stuck-elsewhere finding whose first step is the owner's is no decision for him: it goes to the item's mover, never to the -main agent", to_of(83) == ["home-agent"] and "alpha-main" not in {to for to, t, fy in sent}, sent)
rec_clear(); fake(); rec = go(build(item(84, wrote=now - H, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one")))
check("the owner's own marked path stays: a finding on an item that is his move goes to the project's -main agent with [for Oliver] first", to_of(84) == ["alpha-main"] and [t for to, t, fy in sent if to == "alpha-main"][0].startswith("[for Oliver]"), sent)
check("recipient(): background -> itself; front, keeper, retired, outside, nobody -> the page key; no project -> the -main agent, marked", AR.recipient("home-agent", "projects/alpha", env()) == ("home-agent", False)
      and AR.recipient("alpha-main", "projects/alpha", env()) == ("projects/alpha", False) and AR.recipient("-", "alpha", env()) == ("projects/alpha", False)
      and AR.recipient("an outside party", "projects/alpha", env()) == ("projects/alpha", False) and AR.recipient("home-agent", "", env()) == ("home-agent", False)
      and AR.recipient("alpha-main", "", env()) == ("alpha-main", True) and AR.recipient("Oliver", "projects/alpha", env(), "home-agent") == ("home-agent", False))
ROLES["gone-agent"] = {"role": "background", "retired": True}; ROLES["page-keeper"] = {"role": "keeper"}
check("…a retired session and a page's name-line session are not reached directly either", AR.recipient("gone-agent", "projects/alpha", env()) == ("projects/alpha", False) and AR.recipient("page-keeper", "projects/alpha", env()) == ("projects/alpha", False))
ROLES.pop("gone-agent"); ROLES.pop("page-keeper"); ROLES.pop("beta-main")
rec_clear()

# ---- 25d. a finding already sent, with its item not written since, is not sent again
f25s = build(doing(2, 5, wake=local(now - 2 * H)),                                    # stale, mover home-agent
             doing(3, 1, nxt="ops-other: do the first part\nhome-agent: then the second", expected_by=local(now + 30 * H), expected_reason="the build"))   # stuck-elsewhere, to ops-other
rec_clear(); fake(); rec1 = go(f25s, now=now)
item_msgs = lambda: [(to, t) for to, t, fy in sent if not fy and "Board audit" in t and "item(s) for you" in t]
check("the first run sends both findings and stamps each as sent", len(item_msgs()) == 2 and rec1["repeats"] == 0 and all(isinstance(f.get("sent"), float) for f in rec1["findings"]), (sent, rec1["findings"]))
rec2 = go(f25s, now=now + 2)
check("the same findings on the next run are not sent again: no item message, the record still lists them with the first run's stamp, `repeats` counts them", item_msgs() == [] and rec2["repeats"] == 2
      and sorted((f["id"], f["category"], f["sent"]) for f in rec2["findings"]) == sorted((f["id"], f["category"], f["sent"]) for f in rec1["findings"]), (sent, rec2["findings"]))
check("…the counts and the summary still see them, and the summary says how many were not sent again", rec2["by_category"] == rec1["by_category"] and any("2 unchanged since sent, not sent again" in t for to, t, fy in sent if to == "projects/example"), (rec2["by_category"], sent))
rec3 = go(f25s, now=now + 4)
check("…and a third run keeps them quiet (the stamp is carried, not renewed)", item_msgs() == [] and rec3["repeats"] == 2 and {f["sent"] for f in rec3["findings"]} == {f["sent"] for f in rec1["findings"]}, (sent, rec3["findings"]))
f25w = {k: dict(v, metadata=dict(v["metadata"])) for k, v in f25s.items()}
f25w["a3"]["written_at"] = time.time() + 600; f25w["a3"]["written_by"] = "home-agent"; f25w["a3"]["updated"] = time.time() + 600       # the stuck-elsewhere item was written after the send
rec4 = go(f25w, now=now + 6)
check("an item written since the send is sent again (to ops-other, the step's session); the one not written stays quiet", [to for to, t in item_msgs()] == ["ops-other"] and "board#3 · stuck-elsewhere" in item_msgs()[0][1]
      and not any("board#2" in t for to, t in item_msgs()) and rec4["repeats"] == 1, (item_msgs(), rec4["repeats"]))
rec_clear(); rec5 = go(f25s, now=now, env_=env(deliver=deliver_down("home-agent", "alpha-main", "ops-other", "projects/alpha")))
check("a finding whose message reached no one carries no stamp", rec5["findings"] and not any("sent" in f for f in rec5["findings"]) and rec5["repeats"] == 0, (rec5["findings"], rec5["messages"]))
rec6 = go(f25s, now=now + 2)
check("…so the next run sends it", len(item_msgs()) == 2 and rec6["repeats"] == 0, (item_msgs(), rec6["repeats"]))
rec_clear(); fake(); rec1 = go(f25s, now=now)
go(build(clean(1)), now=now + 2)
go(f25s, now=now + 4)
check("a finding that goes away and comes back is new: it is sent again", len(item_msgs()) == 2, item_msgs())
# a record from before the stamp existed (no `repeats` key): its findings count as sent when its run started
rec_clear(); fake()
(T / "state/audit" / f"run-{today}.json").write_text(json.dumps({"started": now - H, "finished": now - H + 60, "items_read": 2, "findings": [{"id": "board#2", "project": "projects/alpha", "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "y"}],
                                                                  "by_session": {}, "by_category": {}}))
rec7 = go(f25s, now=now)
check("an old record's finding counts as sent at its run's start (the first run after the change does not resend the board)", item_msgs() and all("board#2" not in t for to, t in item_msgs()) and rec7["repeats"] == 1, (item_msgs(), rec7["repeats"]))
# the unmoved digest: once per item for as long as it stays unmoved; `stuck` and the summary keep naming it
rec_clear(); sent.clear()
(T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10,
      "findings": [{"id": "board#2", "project": "projects/alpha", "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "y"}], "by_session": {}, "by_category": {}}))
f25u = {k: dict(v, metadata=dict(v["metadata"])) for k, v in f25s.items()}
f25u["a2"]["updated"] = now - 3 * 86400; f25u["a2"]["written_at"] = now - 3 * 86400; f25u["a2"]["written_by"] = "home-agent"
ru1 = go(f25u, now=now)
digest = lambda: [t for to, t, fy in sent if to == "alpha-builder" and "chase the mover" in t]
check("the digest lists an unmoved item the first time", len(digest()) == 1 and "board#2" in digest()[0] and [s["chased"] for s in ru1["stuck"]] == [True], (digest(), ru1["stuck"]))
ru2 = go(f25u, now=now + 7 * H)
check("…and not again on the next run, while `stuck` and the summary still name it", not any("board#2" in t for t in digest()) and ("board#2", True) in [(s["id"], s["chased"]) for s in ru2["stuck"]]
      and any("unmoved: board#2" in t for to, t, fy in sent if to == "projects/example"), (sent, ru2["stuck"]))
def legacy_prev():
    (T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10,
          "findings": [{"id": "board#2", "project": "projects/alpha", "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "y"}], "by_session": {}, "by_category": {}}))
# a digest that was not delivered is no chase: the next run sends it
rec_clear(); legacy_prev()
rx1 = go(f25u, now=now, env_=env(deliver=deliver_down("alpha-builder")))
check("a digest whose send fails leaves the item unchased (recorded as not delivered)", [(s["id"], s["chased"]) for s in rx1["stuck"]] == [("board#2", False)] and any(m.get("kind") == "unmoved" and m["delivered"] is False for m in rx1["messages"]), (rx1["stuck"], rx1["messages"]))
rx2 = go(f25u, now=now + 7 * H)
check("…so the next run chases it, and only then is it chased", any("board#2" in t for t in digest()) and ("board#2", True) in [(s["id"], s["chased"]) for s in rx2["stuck"]], (digest(), rx2["stuck"]))
# two runs on one day: the second is too soon to take the first as its previous run, but it knows the first chased the item
rec_clear(); legacy_prev()
ry1 = go(f25u, now=now)
ry2 = go(f25u, now=now + 2)
check("a second run the same day does not chase an item again that the first run chased", not any("board#2" in t for t in digest()) and ("board#2", True) in [(s["id"], s["chased"]) for s in ry2["stuck"]], (digest(), ry2["stuck"]))
# a message that cites an item may write it (a server save): the stamp and the next run's comparison are taken after the last send, so that is no write of the item's
rec_clear(); legacy_prev()
f25v = {k: dict(v, metadata=dict(v["metadata"])) for k, v in f25s.items()}
for _it in f25v.values(): _it.pop("written_at", None); _it.pop("written_by", None)          # no session wrote them: the item's own clock `updated` stands in for the last write
f25v["a2"]["updated"] = now - 3 * 86400; f25v["a3"]["updated"] = now - H
def deliver_bump(to, text, fyi=False):
    sent.append((to, text, fyi))
    if to in ("alpha-builder", "projects/example"):                                       # the digest and the summary name items: the server saves them while delivering
        for it in f25v.values(): it["updated"] = time.time()
    return True, "[200] ok"
rz1 = go(f25v, now=now, env_=env(deliver=deliver_bump))
check("the run's first messages went out before the saves (a finding was sent, the digest chased the unmoved item)", len(item_msgs()) >= 1 and len(digest()) == 1, (item_msgs(), digest()))
rz2 = go(f25v, now=now + 7 * H, env_=env(deliver=deliver_bump))
check("a save the server made while delivering is no write: the finding is not sent again (what is new, 7 simulated hours of idleness, is), and the item stays on `stuck`", not any("stuck-elsewhere" in t or "· stale" in t for to, t in item_msgs()) and ("board#2", True) in [(s["id"], s["chased"]) for s in rz2["stuck"]] and rz2["repeats"] >= 1, (item_msgs(), rz2["stuck"], rz2["repeats"]))
check("…the stamp and the run's end are the same time, after every send (board#2's stale finding is the previous run's, a repeat on its old stamp)", any(f["id"] == "board#3" and "sent" in f for f in rz1["findings"])
      and all(f["sent"] == rz1["finished"] for f in rz1["findings"] if "sent" in f and f["id"] != "board#2"), (rz1["finished"], rz1["findings"]))
# a mover of "-" and one of "" read alike
check("recipient(): the owner's finding on an item whose mover is nobody (\"\" or \"-\") goes the same way, to the -main agent, marked", AR.recipient("Oliver", "projects/alpha", env(), "-") == AR.recipient("Oliver", "projects/alpha", env(), "") == ("alpha-main", True))
# a write the run's own judging time let by is a write; one inside its send window is the run's own delivery
S = now - 8 * H                                                                            # the earlier run read the board at S, sent from S+100 and ended at S+200
def prior(window=True):
    f = {"id": "board#1", "project": "projects/alpha", "owner": "Oliver", "mover": "Oliver", "category": "ask-missing", "detail": "needs a decision from Oliver and carries no ask", "source": "code", "sent": S + 200}
    if window: f.update(sending_from=S + 100, run_started=S)
    AR._record_path(S).write_text(json.dumps({"started": S, "finished": S + 200, "items_read": 1, "findings": [f], "repeats": 0, **({"sending_from": S + 100} if window else {}),
                                              "by_session": {}, "by_category": {}, "stuck": [], "idle_pass": [], "judged": {}}))
def wrote_at(t):
    k, d = item(1, wrote=t, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one"); return {k: d}
def ask_sent(): return any("board#1 · ask-missing" in t for to, t in item_msgs())
for label, window, t, in_stuck, resent in (("a write mid-run, before the sends began", True, S + 50, False, True), ("a write in the send window", True, S + 150, True, False),
                                           ("a write after the run ended", True, S + 250, False, True), ("a write mid-run, on a record with no send window (as before)", False, S + 50, True, False)):
    rec_clear(); prior(window); fake()
    rw = go(wrote_at(t), now=now)
    check(f"{label}: {'it is a write' if resent else 'it is not'}: the item {'leaves' if not in_stuck else 'stays on'} `stuck` and its finding is {'sent again' if resent else 'not sent again'}",
          (("board#1" in [x["id"] for x in rw["stuck"]]) == in_stuck) and ask_sent() == resent, (rw["stuck"], item_msgs(), rw["repeats"]))
rec_clear(); fake(); rw = go(f25s, now=now)
check("a run records `sending_from` (no earlier than its start, no later than its end) and stamps each sent finding with it and its start", rw["started"] <= rw["sending_from"] <= rw["finished"]
      and all(f["sending_from"] == rw["sending_from"] and f["run_started"] == rw["started"] and f["sent"] == rw["finished"] for f in rw["findings"] if "sent" in f) and rw["findings"], rw)
rw2 = go(f25s, now=now + 2)
check("…and a repeat keeps its first run's stamps", all(f["sending_from"] == rw["sending_from"] and f["run_started"] == rw["started"] for f in rw2["findings"] if "sent" in f) and rw2["repeats"] == len(rw["findings"]), rw2["findings"])

# a run that starts just before a local midnight and a second one just after it: the same stretch, whatever the calendar says
rec_clear()
T0 = now - (now + ZONE_OFFSET) % 86400 - 2                      # the last local midnight minus 2 seconds: at or before `now`, at most a day and 2 seconds back, whatever day the suite runs
assert T0 <= now and now - T0 <= 86400 + 2, (now, T0)
f25m = {k: dict(v, metadata=dict(v["metadata"])) for k, v in f25s.items()}                      # the items as they stood at T0: every write is older than the first run
for _it in f25m.values(): _it["written_by"] = "home-agent"
f25m["a2"]["updated"] = f25m["a2"]["written_at"] = T0 - 3 * 86400                                   # older than the prior record's start, T0 - 2 days
f25m["a3"]["updated"] = f25m["a3"]["written_at"] = T0 - H
(T / "state/audit" / f"run-{AR._date_of(T0 - 2 * 86400)}.json").write_text(json.dumps({"started": T0 - 2 * 86400, "finished": T0 - 2 * 86400 + 60, "items_read": 10, "by_session": {}, "by_category": {},
      "findings": [{"id": "board#2", "project": "projects/alpha", "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "y"}]}))
rm1 = go(f25m, now=T0)
rm2 = go(f25m, now=T0 + 4)
days = [r["date"] for r in audit.runs()[:2]]
check("a second run 4 seconds later, across local midnight, is the newer record of the next day", days == [AR._date_of(T0 + 4), AR._date_of(T0)] and days[0] != days[1] and rm2["started"] == T0 + 4 and audit.last()["started"] == T0 + 4, (days, audit.last()))
check("…it does not chase again what the first chased, and does not send again what the first sent", not any("board#2" in t for t in digest()) and item_msgs() == [] and rm2["repeats"] == len(rm1["findings"]) and ("board#2", True) in [(x["id"], x["chased"]) for x in rm2["stuck"]],
      (digest(), item_msgs(), rm2["stuck"]))
rec_clear()

go = _go_base                                # …and the run is the daily run again
# ---- 27. [audit] lane: the audit's calls run on a sala lane, the router's other calls do not
# a fake `salamander` on PATH: logs its argv, then runs what follows `--` (the real one sets the lane's environment first)
LANELOG = T / "fake-salamander.log"; (T / "bin").mkdir(exist_ok=True)
(T / "bin/salamander").write_text(f'''#!/bin/sh
echo "$*" >> {LANELOG}
while [ "$1" != "--" ]; do shift; done; shift
exec "$@"
'''); os.chmod(T / "bin/salamander", 0o755)
_old_path = os.environ["PATH"]; os.environ["PATH"] = f"{T / 'bin'}:{_old_path}"
def lane_log(): return [l for l in LANELOG.read_text().splitlines() if l.startswith("lane exec ")] if LANELOG.exists() else []   # the system prompt in $* has newlines: count the lines that start a call
from stackshot.router import router as RT
_cfg.CFG.setdefault("audit", {})
try:
    check("[audit] lane unset reads as empty", _cfg.audit_lane() == "", _cfg.audit_lane())
    _cfg.CFG["audit"]["lane"] = "bedrock"; ok1 = _cfg.audit_lane()
    _cfg.CFG["audit"]["lane"] = " Bad Lane;rm "; ok2 = _cfg.audit_lane()
    _cfg.CFG["audit"]["lane"] = "testlane"
    check("…a lane name is kept, a value that is no lane name reads as the default", ok1 == "bedrock" and ok2 == "", (ok1, ok2))
    a = RT.build_argv("sys", None, "testlane"); i = a.index("salamander")
    check("build_argv with a lane puts `salamander lane exec <lane> --` right before the router command, after the variables are unset", a[i:i + 5] == ["salamander", "lane", "exec", "testlane", "--"]
          and a[i + 5] == sys.executable and "-u" in a[:i] and a.index("--model") > i, a[:12])
    check("build_argv with no lane (every other caller) has no salamander in it", "salamander" not in RT.build_argv("sys") and "salamander" not in RT.build_argv("sys", "haiku"), RT.build_argv("sys")[:8])
    _cfg.CFG["router"]["login_shell"] = True; al = RT.build_argv("sys", None, "testlane"); _cfg.CFG["router"]["login_shell"] = False
    check("…the login-shell form wraps the same way, after its unset loop", al[:3] == ["bash", "-l", "-c"] and al[al.index("stackshot-router") + 1:al.index("stackshot-router") + 6] == ["salamander", "lane", "exec", "testlane", "--"], al[:8])
    rec_clear(); fake(); LANELOG.exists() and LANELOG.unlink()
    rec = go(f2)
    check("the audit's calls (all 6) ran through the lane: one `lane exec testlane --` line each, and the fake claude still answered", len(lane_log()) == 6 and all(l.startswith("lane exec testlane -- ") for l in lane_log())
          and len(calls()) == 6 and rec["calls"]["made"] == 6 and rec["calls"]["failed"] == 0, (len(lane_log()), len(calls()), rec["calls"]))
    LANELOG.unlink(); reset_calls()
    r = RT.run_call("Item board#1: x", "sys rubric")
    check("a router call made while [audit] lane is set (the default run_call) does not touch the lane", r["status"] == "ok" and lane_log() == [] and len(calls()) == 1, (r, lane_log()))
    r = RT.run_call("Item board#1: x", "sys rubric", lane="testlane")
    check("run_call(lane=...) is the one way onto the lane", r["status"] == "ok" and len(lane_log()) == 1, (r, lane_log()))
    _cfg.CFG["audit"]["lane"] = ""; LANELOG.exists() and LANELOG.unlink()
    rec_clear(); fake(); rec = go(f2)
    check("with [audit] lane empty the audit's calls are today's: no salamander, the router command alone", lane_log() == [] and len(calls()) == 6 and rec["calls"]["made"] == 6, (lane_log(), len(calls())))
    _cfg.CFG["audit"]["lane"] = "testlane"; LANELOG.exists() and LANELOG.unlink()
    seen = []; env_run = env(runner=lambda m: seen.append(m) or {"status": "ok", "text": json.dumps({"finding": "no", "check": "", "reason": "", "fix": ""})})
    rec_clear(); rec = go(f2, env_=env_run)
    check("an injected runner (the test seam) is left alone by the lane setting", len(seen) == 6 and lane_log() == [], (len(seen), lane_log()))
finally:
    os.environ["PATH"] = _old_path; _cfg.CFG["audit"].pop("lane", None)
rec_clear()

# ---- 26. page agent lines: one message per agent that sala knows, listing its pages' leftovers; nothing when sala cannot be read
ROLES["bravo-main"] = {"role": "background"}
PREG = {"projects/alpha": {"session": "alpha", "role": "name", "status": "active", "agents": {"alpha-main": "x", "alpha-gone": "was renamed"}, "back_agents": {}},
        "projects/bravo": {"session": "bravo", "role": "name", "status": "active", "agents": {"bravo-main": "x", "bravo-old": "retired", "bravo-older": "retired too"}, "back_agents": {}},
        "projects/charlie": {"session": "charlie", "role": "name", "status": "done", "agents": {"charlie-gone": "x"}, "back_agents": {}}}
SESS_OK = ({"alpha-main", "bravo-main", "alpha-builder"}, {"alpha-lead"})
f26 = build(clean(1))
rec_clear(); fake(); rec = go(f26, env_=env(sessions=lambda: SESS_OK, registry=lambda: PREG))
pa_msgs = {to: (text, fyi) for to, text, fyi in sent if "Page agent lines" in text and to != "projects/example"}
check("page agent lines: one message to each page's -main agent, not fyi, kind page-agents on the record", sorted(pa_msgs) == ["alpha-main", "bravo-main"] and all(fyi is False for _, fyi in pa_msgs.values())
      and sorted((m["to"], m["lines"]) for m in rec["messages"] if m.get("kind") == "page-agents") == [("alpha-main", 1), ("bravo-main", 2)], (sorted(pa_msgs), rec["messages"]))
check("...a front agent's starts with [for Oliver], the other's does not; the lines are '<page> · <line> · <name> · <fix>'", pa_msgs["alpha-main"][0].startswith("[for Oliver]") and not pa_msgs["bravo-main"][0].startswith("[for Oliver]")
      and "projects/alpha · agents line · alpha-gone · " in pa_msgs["alpha-main"][0] and all(len(l.split(" · ")) == 4 for t, _ in pa_msgs.values() for l in t.splitlines() if l.startswith("projects/")), pa_msgs)
check("...a retired page is skipped, an alias counts as live", "charlie" not in pa_msgs["alpha-main"][0] + pa_msgs["bravo-main"][0] and "alpha-lead" not in pa_msgs["alpha-main"][0], pa_msgs)
check("the record carries them apart from the item findings: page_agents, no finding and no category count", rec["page_agents"]["checked"] is True and len(rec["page_agents"]["findings"]) == 3
      and rec["findings"] == [] and "page agent lines" not in rec["by_category"] and rec["page_agents"]["findings"][0].keys() >= {"page", "line", "name", "to"}, rec["page_agents"])
check("the summary says how many", any("page agent lines 3" in t for to, t, fy in sent if to == "projects/example"), [t for to, t, fy in sent if to == "projects/example"])
rec_clear(); rec = go(f26, env_=env(sessions=lambda: None, registry=lambda: PREG))
check("sala unreadable: nothing is sent about page agent lines, the record and the summary say not checked", not [1 for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"]
      and rec["page_agents"]["checked"] is False and any("page agent lines not checked" in t for to, t, fy in sent if to == "projects/example"), (sent, rec["page_agents"]))
rec_clear(); rec = go(f26, env_=env(sessions=lambda: (set(), {"lone-alias"}), registry=lambda: PREG))
check("sala lists no session: the same, nothing flagged", rec["page_agents"]["checked"] is False and rec["page_agents"]["findings"] == [] and not [m for m in rec["messages"] if m.get("kind") == "page-agents"], rec["page_agents"])
def boom(): raise RuntimeError("sala exploded")
rec_clear(); rec = go(f26, env_=env(sessions=boom, registry=lambda: PREG))
check("a check that raises is a check not made: the run goes on and finishes its record", rec["finished"] is not None and rec["page_agents"]["checked"] is False and "failed" in rec["page_agents"]["note"], rec["page_agents"])
rec_clear(); sent.clear(); out = []
res = AR.run(dry=True, now=now, items=f26, anchors={}, env=env(sessions=lambda: SESS_OK, registry=lambda: PREG), rubric=RUBRIC_TEXT, out=out.append)
check("a dry run lists the page agent lines and sends nothing, writes no record", any("[page-agents] projects/bravo" in l for l in out) and len(res["page_agents"]["findings"]) == 3 and sent == [] and list((T / "state/audit").glob("run-*.json")) == [], (out, sent))
rec_clear()
# a project page with items and no agents map (the moved page that had no -main agent): its line goes the same way as the others, to the audit's -main agent when no page agent is live, marked [for Oliver]
AXREG = {"projects/alpha": {"session": "", "role": "", "status": "active", "type": "project", "agents": None, "back_agents": None, "title": ""}}      # f26's item names projects/alpha
ROLES["falcon-main"] = {"role": "front"}
rec_clear(); rec = go(f26, env_=env(sessions=lambda: SESS_OK, registry=lambda: AXREG))
axm = [(to, t) for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"]
check("a project page with items and no agents map: one message to the audit's -main agent, marked [for Oliver], with the line and a header that says what is wrong",
      [to for to, t in axm] == ["falcon-main"] and axm[0][1].startswith("[for Oliver]") and "projects/alpha · no agents map · 1 open item · its items have no contact" in axm[0][1] and "need a fix" in axm[0][1]
      and [(m["to"], m["lines"], m["kind"]) for m in rec["messages"] if m.get("kind") == "page-agents"] == [("falcon-main", 1, "page-agents")], (axm, rec["messages"]))
check("…it is on the record's page_agents and in no item category", [(f["page"], f["line"]) for f in rec["page_agents"]["findings"]] == [("projects/alpha", "no agents map")] and "page agent lines" not in rec["by_category"], rec["page_agents"])
rec_clear(); rec = go(f26, env_=env(sessions=lambda: SESS_OK, registry=lambda: {"projects/alpha": {**AXREG["projects/alpha"], "agents": {"alpha-main": "keeps it"}}}))
check("…and with the agents map added there is no such message", not [1 for to, t, fy in sent if "no agents map" in t], sent)
FREG = {"projects/other": {"session": "other", "role": "name", "status": "active", "type": "project", "agents": {"other-main": "x"}, "back_agents": {}, "title": ""},
        "projects/alpha": {**AXREG["projects/alpha"], "session": "other-ax", "role": "name"}}      # the page's only session is named for another project
rec_clear(); rec = go(f26, env_=env(sessions=lambda: ({"other-main", "other-ax"}, set()), registry=lambda: FREG))
fxm = [t for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"]
check("a page whose only session is named for another project: its line and the header that names the kind", len(fxm) == 1 and "projects/alpha · other project's session · other-ax · 1 open item; named for other, not for this page" in fxm[0] and "need a fix" in fxm[0], fxm)
rec_clear(); rec = go(f26, env_=env(sessions=lambda: ({"other-main", "alpha-solo"}, set()), registry=lambda: {**FREG, "projects/alpha": {**FREG["projects/alpha"], "session": "alpha-solo"}}))
check("…and a one-session page with a live session of its own is not flagged", not [1 for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"], sent)
rec_clear(); out = []
res = AR.run(dry=True, now=now, items=f26, anchors={}, env=env(sessions=lambda: SESS_OK, registry=lambda: AXREG), rubric=RUBRIC_TEXT, out=out.append)
check("the dry run lists it as a page-agents line", any("[page-agents] projects/alpha · no agents map · 1 open item" in l and "(to falcon-main)" in l for l in out), out)
ROLES.pop("falcon-main", None)
rec_clear()
# a live session that created an item of a project whose agents map has no line for it: one more kind of page agent line, to the page's -main agent, marked [for Oliver]
OFFREG = {"projects/alpha": {"session": "alpha", "role": "name", "status": "active", "type": "project", "agents": {"alpha-main": "keeps it"}, "back_agents": {}, "title": ""}}
f_off = build(item(1, owner="alpha-ghost"), item(2, owner="alpha-ghost"), item(3))
rec_clear(); rec = go(f_off, env_=env(sessions=lambda: ({"alpha-main", "alpha-ghost"}, set()), registry=lambda: OFFREG))
offm = [(to, t) for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"]
check("a session its project's agents map has no line for: one message to the page's -main agent, marked [for Oliver], with the line and the header that names the kind",
      [to for to, t in offm] == ["alpha-main"] and offm[0][1].splitlines()[0] == "[for Oliver]" and "projects/alpha · session off the map · alpha-ghost (2 items) · " in offm[0][1] and "need a fix" in offm[0][1]
      and [(m["to"], m["lines"], m["kind"]) for m in rec["messages"] if m.get("kind") == "page-agents"] == [("alpha-main", 1, "page-agents")], (offm, rec["messages"]))
check("…it is on the record's page_agents and in no item category", [(f["page"], f["line"]) for f in rec["page_agents"]["findings"]] == [("projects/alpha", "session off the map")] and "page agent lines" not in rec["by_category"], rec["page_agents"])
rec_clear(); rec = go(f_off, env_=env(sessions=lambda: ({"alpha-main", "alpha-ghost"}, set()), registry=lambda: {"projects/alpha": {**OFFREG["projects/alpha"], "agents": {"alpha-main": "keeps it", "alpha-ghost": "builds it"}}}))
check("…and once the map lists the session there is no such message", not [1 for to, t, fy in sent if "session off the map" in t], sent)
rec_clear()
# a page whose -main agent is gone and no fallback is live: the real fallback (anchors.fallback_main on the registry, not a stand-in) names the gone agent, the line goes to the audit's -main agent instead
from stackshot.anchors import anchors as _anc
GREG = {"projects/delta": {"session": "delta", "role": "name", "status": "active", "agents": {"delta-main": "x", "delta-gone": "was renamed"}, "back_agents": {}}}
_real_registry = _anc.registry
_anc.registry = lambda: GREG                                    # the real Env.main_of reads the registry through anchors: give it the fixture, nothing else is stood in
try:
    genv = env(sessions=lambda: ({"alpha-main", "bravo-main", "delta-builder"}, set()), registry=lambda: GREG)
    genv.fallback = None                                        # no fallback lambda: Env.main_of takes the real anchors.fallback_main
    ROLES["falcon-main"] = {"role": "front"}
    check("the real fallback names the gone -main agent (the premise: a message there would queue silently)", genv.main_of("projects/delta") == "delta-main", genv.main_of("projects/delta"))
    rec_clear(); rec = go(f26, env_=genv)
    gmsgs = [(to, t) for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"]
    check("a gone -main agent: its page's line goes to the audit's -main agent, marked [for Oliver], never to the gone name",
          [to for to, t in gmsgs] == ["falcon-main"] and gmsgs[0][1].startswith("[for Oliver]") and "projects/delta · agents line · delta-gone · " in gmsgs[0][1] and not any(to == "delta-main" for to, t, fy in sent)
          and [(m["to"], m["lines"]) for m in rec["messages"] if m.get("kind") == "page-agents"] == [("falcon-main", 2)], (gmsgs, rec["messages"]))
    rec_clear(); out = []
    res = AR.run(dry=True, now=now, items=f26, anchors={}, env=genv, rubric=RUBRIC_TEXT, out=out.append)
    check("the dry run names the same recipient", any("[page-agents] projects/delta" in l and "(to falcon-main)" in l for l in out), out)
finally:
    _anc.registry = _real_registry
    ROLES.pop("falcon-main", None)
rec_clear()

# ---- 27. obsolete-wait: a waiting item whose premise a later change overtook
# The replay: an item parked on a wake (a script parked it from doing) whose wait rests on the first run of another item's nightly sync; that other item is closed as dropped, "overtaken" by a new
# feature. The item is shown as it stood while it waited: hold, wake, wait basis, next citing the dropped item.
def hold_at(i, ago, nxt, text, cites_state="parked", **kw):
    k, d = item(i, wrote=now - ago * H, state=cites_state, needs=["home-agent"], hold=True, wake=WAKE, hold_set={"at": now - ago * H, "by": "a script"},
                wait_basis={"text": text, "wake": WAKE, "by": "a script", "at": now - ago * H}, next=nxt, **kw)
    return k, d
def closed(i, outcome, reason, ago, subject):
    k, d = item(i, status="completed", wrote=now - ago * H, state="doing", needs=["home-agent"], next="", outcome=outcome, reason=reason)
    d["subject"] = subject; d["state_updated"] = now - ago * H
    return k, d
OBS = "obsolete-wait"
replay = build(hold_at(99, 20, f"home-agent: then fold board#{BID_65}'s nightly sync into this item's record", f"the done line needs a daily run and board#{BID_65}'s first sync runs on the wake (parked from doing)"),
               closed(75, "dropped", "Oliver: close as overtaken; the new live-update feature made the nightly sync unneeded", 21, "[home] Add a nightly sync"))
rec_clear(); fake(answers={f"board#{BID_80}": YES(OBS, f"board#{BID_65} was dropped as overtaken by the new live-update feature; the nightly sync this waits for will never run", f"drop the item, citing board#{BID_65}")})
sus, _skip = AR.suspects(replay, now, env())
check("the replay: the held item is a suspect, for next-done and obsolete-wait in one call, with the dropped item as evidence",
      [(s["id"], s["checks"]) for s in sus] == [(f"board#{BID_80}", ["next-done", OBS])] and f"board#{BID_65} is closed as dropped" in sus[0]["evidence"][OBS] and "overtaken" in sus[0]["evidence"][OBS], sus)
rec = go(replay)
fnd = [f for f in rec["findings"] if f["category"] == OBS]
check("the replay is caught: one finding under obsolete-wait, source model, on the item's mover, with the reason the call gave", len(fnd) == 1 and fnd[0]["id"] == f"board#{BID_80}" and fnd[0]["source"] == "model"
      and fnd[0]["mover"] == "home-agent" and "dropped as overtaken" in fnd[0]["detail"], rec["findings"])
check("…with exactly one model call, whose message names the check, when the wait began, the wait's basis and how the cited item closed", len(calls()) == 1 and rec["calls"]["made"] == 1
      and f"- {OBS}: an item the wait cites is closed" in calls()[0]["stdin"] and "The wait began" in calls()[0]["stdin"] and "first sync runs on the wake" in calls()[0]["stdin"]
      and f"board#{BID_65} is closed as dropped (Oliver: close as overtaken" in calls()[0]["stdin"], calls())
check("the rubric (the system prompt) carries the check, so the call can answer under it", "obsolete-wait" in RUBRIC_TEXT and "--system-prompt" in calls()[0]["argv"] and RUBRIC_TEXT in calls()[0]["argv"], RUBRIC_TEXT[-300:])
check("the finding goes to the mover as one line '<id> · obsolete-wait · <evidence> · <fix>', through the usual delivery", any(to == "home-agent" and f"board#{BID_80} · obsolete-wait · board#{BID_65} was dropped" in t and f"drop the item, citing board#{BID_65}" in t for to, t, fy in sent), sent)
check("the verdict is kept with a signature of its evidence", rec["judged"][f"board#{BID_80}"]["verdict"] == "yes" and rec["judged"][f"board#{BID_80}"]["check"] == OBS and rec["judged"][f"board#{BID_80}"]["sig"], rec["judged"])

# still-valid waits are not flagged: the item it waits for is open (no suspect, no call); a closed item that is only background (the model says no: a suspect, a call, no finding)
valid = build(hold_at(74, 20, f"home-agent: then check board#{BID_41}'s rollout", f"board#{BID_41}'s rollout ends on the wake"), item(51, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: roll it out", expected_by=local(now + 30 * H), expected_reason="the rollout"),
              hold_at(54, 20, "home-agent: after the visit, check the result", f"a booked visit; board#{BID_15} only set the date"), closed(25, "done", "the date is set", 21, "[home] Book the visit"))
rec_clear(); fake()
sus, _skip = AR.suspects(valid, now, env())
check("a wait on an open item is no suspect; one that cites a closed item only as background is (the call decides)", [s["id"] for s in sus] == [f"board#{BID_44}"], [(s["id"], s["checks"]) for s in sus])
rec = go(valid)
check("a still-valid wait: no finding, one call (for the background citation only), judged 'no'", not [f for f in rec["findings"] if f["category"] == OBS] and len(calls()) == 1 and rec["judged"][f"board#{BID_44}"]["verdict"] == "no"
      and f"board#{BID_64}" not in rec["judged"], (rec["findings"], len(calls())))
check("an alive item that cites a closed item is not an obsolete-wait suspect", [s["id"] for s in AR.suspects(build(*replay.items(), doing(19, 1, nxt="home-agent: build it", expected_by=local(now + 30 * H), expected_reason="x", description=f"- see board#{BID_65}")),
      now, env())[0]] == [f"board#{BID_80}"], "")
check("a closed item is never a suspect", AR.suspects(build(closed(20, "dropped", "x", 5, "[home] done")), now, env())[0] == [], "")

# a verdict stands until the evidence changes; a 'yes' is carried; a changed evidence is judged again
rec_clear(); fake(answers={f"board#{BID_80}": YES(OBS)})
go(replay)
prev = json.loads(AR._record_path(now).read_text())
(T / "state/audit" / f"run-{dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date().isoformat()}.json").write_text(json.dumps(dict(prev, started=now - 2 * 86400, finished=now - 2 * 86400 + 60)))
AR._record_path(now).unlink()
rec = go(replay)
check("unchanged evidence: no new call, the 'yes' is carried as a finding", calls() == [] and [f["id"] for f in rec["findings"] if f["category"] == OBS] == [f"board#{BID_80}"] and rec["calls"]["unchanged"] == 1, (len(calls()), rec["calls"]))
replay3 = build(*replay.items()); replay3["a9265"] = dict(replay["a9265"], subject="[home] Add a nightly sync (edited)", state_updated=now - H, updated=now - H)
AR._record_path(now).unlink()
rec = go(replay3)
check("a later edit to the closed item (subject, timestamps) leaves the signature alone: no new call, the 'yes' carried", calls() == [] and rec["calls"]["unchanged"] == 1 and [f["id"] for f in rec["findings"] if f["category"] == OBS] == [f"board#{BID_80}"], (len(calls()), rec["calls"]))
replay4 = build(*replay.items()); replay4["a9265"] = dict(replay["a9265"], status="open")
AR._record_path(now).unlink()
rec = go(replay4)
check("a cited item that was reopened: no suspect, no call, the old 'yes' is not sent again and not kept", calls() == [] and not [f for f in rec["findings"] if f["category"] == OBS] and f"board#{BID_80}" not in rec["judged"] and not [1 for to, t, fy in sent if "obsolete-wait" in t], (rec["findings"], rec["judged"], sent))
replay2 = build(*replay.items()); replay2["a9265"] = dict(replay["a9265"], metadata={**replay["a9265"]["metadata"], "reason": "Oliver: close as overtaken and replaced by a different plan"})
AR._record_path(now).unlink()
rec = go(replay2)
check("evidence that changed (the cited item's reason) is judged again, though the held item was not written", len(calls()) == 1 and f"Item board#{BID_80}:" in calls()[0]["stdin"], [c["stdin"][:30] for c in calls()])
rec_clear()

# the page signal: a page written after the wait began and after the item's last write, naming an item the wait cites, makes it a suspect; a page older than the wait, an item written since the page, a line that names only the item itself, or another project's page does not
PAGE_TS = now - 2 * H
PAGE = f"Current state\n- board#{BID_25} is replaced by the new plan\n- board#{BID_38} holds the build\n- board#{BID_50} waits on the visit\n- board#{BID_42} was parked with a visit booked\n"
pg = build(hold_at(52, 30, f"home-agent: after the wake, check board#{BID_25}", "a booked visit"), hold_at(48, 1, f"home-agent: after the wake, check board#{BID_25}", "a booked visit"), hold_at(60, 30, f"home-agent: after the wake, check board#{BID_25}", "a booked visit"),
           hold_at(92, 30, "home-agent: after the wake, check", "a booked visit"), item(35, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x"))
pg["a9250"]["metadata"]["project"] = "projects/other"                                                         # a page of another project, written before the wait
def page_of(p): return (PAGE, PAGE_TS) if p == "projects/alpha" else (f"- board#{BID_25} waits\n", now - 40 * H)
sus, _skip = AR.suspects(pg, now, env(page_of=page_of))
check("the page signal: written after the wait and after the item's last write and naming an item it cites: a suspect; the page older than the wait, the item written after the page, or a line naming only the item itself: not",
      [s["id"] for s in sus] == [f"board#{BID_42}"] and "is newer than the wait" in sus[0]["evidence"][OBS] and "replaced by the new plan" in sus[0]["evidence"][OBS] and "was parked with a visit" not in sus[0]["evidence"][OBS], [(s["id"], s["checks"]) for s in sus])
check("the page lines are in the call's message, as the wait's context", f"page: - board#{BID_25} is replaced by the new plan" in AR.prompt(pg["a9242"], sus[0], "home-agent", now), AR.prompt(pg["a9242"], sus[0], "home-agent", now))
check("a page-only suspect ranks after the other checks (priority 3)", sus[0]["priority"] == 3, sus[0]["priority"])
pn = build(("a2", item(2, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x")[1]), hold_at(16, 30, "home-agent: after the wake, check board#2", "a booked visit"))
check("a page line that names a longer id does not name the shorter id it starts with (whole numbers only)", AR.obsolete_wait_evidence("a9206", pn, {"2": ["a2"], "9206": ["a9206"]}, env(page_of=lambda p: (f"- board#{BID_42} something else\n", PAGE_TS)), {}, 0.0)[0] == "", "")

# page-only suspects are capped per run: eight holds cite one open item the page names, five are suspects
cap_pg = build(*[hold_at(80 + k, 30, f"home-agent: after the wake, check board#{BID_22}", "a booked visit") for k in range(8)],
               item(32, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x"))
sus, _skip = AR.suspects(cap_pg, now, env(page_of=lambda p: (f"- board#{BID_22} is replaced by the new plan\n", PAGE_TS)))
check("at most five suspects a run rest on a page line alone", [s["id"] for s in sus] == [f"board#{9266 + k}" for k in range(5)], [s["id"] for s in sus])

# a relay wait (an outside item that waits on news only the owner relays) is no wait for this check, though it cites a closed item; the same item parked is
relay_o = outside(57, f"home-agent: then check board#{BID_01}'s result")
relay_o[1]["metadata"]["wait_basis"] = {"text": f"board#{BID_01}'s result", "wake": WAKE, "by": "a script", "at": now - 20 * H}
rl = build(relay_o, closed(11, "dropped", "overtaken", 21, "[home] dropped"), hold_at(36, 20, f"home-agent: then check board#{BID_01}'s result", f"board#{BID_01}'s result"))
check("a relay wait is not an obsolete-wait suspect; a parked one that cites the same closed item is", [s["id"] for s in AR.suspects(rl, now, env())[0] if OBS in s["checks"]] == [f"board#{BID_26}"], [(s["id"], s["checks"]) for s in AR.suspects(rl, now, env())[0]])

# a closed item named only in the description counts when it was dropped or superseded, not when it was done
dsc = build(hold_at(38, 20, "home-agent: after the wake, check", "a booked visit"), closed(23, "done", "the date is set", 21, "[home] done"), closed(94, "superseded", "replaced", 21, "[home] replaced"))
dsc["a9228"]["description"] = f"- see board#{BID_13} and board#{BID_78}"
check("a closed item named only in the description counts only when it was dropped or superseded", [s["id"] for s in AR.suspects(dsc, now, env())[0]] == [f"board#{BID_28}"] and f"board#{BID_78}" in AR.suspects(dsc, now, env())[0][0]["evidence"][OBS]
      and f"board#{BID_13}" not in AR.suspects(dsc, now, env())[0][0]["evidence"][OBS], [(s["id"], s["evidence"]) for s in AR.suspects(dsc, now, env())[0]])

# no 1970: a wait whose start is unknown has no "The wait began" clause
nos = build(hold_at(34, 20, f"home-agent: then check board#{BID_74}", f"board#{BID_74} runs on the wake"), closed(90, "dropped", "overtaken", 21, "[home] dropped"))
nos["a9224"]["metadata"].pop("hold_set"); nos["a9224"]["metadata"].pop("wait_basis"); nos["a9224"]["state_updated"] = 0; nos["a9224"]["updated"] = 0
sus, _skip = AR.suspects(nos, now, env())
msg = AR.prompt(nos["a9224"], sus[0], "home-agent", now) if sus else ""
check("an unknown wait start leaves out the 'The wait began' clause and any 1970 date", sus and "The wait" in msg and f"board#{BID_74} is closed as dropped" in msg and "The wait began" not in msg and "1970" not in msg, msg)

# the counts the run adds: one call per suspect, at most the cap, none for an item with no signal
many_w = build(*[hold_at(92 + k, 20, "home-agent: then check", f"board#{9225 + k} first runs on the wake") for k in range(3)], *[closed(35 + k, "dropped", "overtaken", 21, "[home] dropped") for k in range(3)],
               *[hold_at(27 + k, 20, "home-agent: then check", f"board#{9238 + k} first runs on the wake") for k in range(3)],
               *[item(48 + k, wrote=now - H, state="doing", needs=["home-agent"], next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x") for k in range(3)])
rec_clear(); fake(); rec = go(many_w)
check("six waiting items, three with a dropped citation: three calls, none for the three waiting on an open item", rec["calls"]["made"] == 3 and rec["calls"]["suspects"] == 3 and len(calls()) == 3, rec["calls"])
rec_clear(); _cfg.CFG["audit"]["max_calls"] = 2; rec = go(many_w)
check("the cap holds for this check as for the others", rec["calls"]["made"] == 2 and rec["calls"]["suspects"] == 3, rec["calls"])
_cfg.CFG["audit"]["max_calls"] = 40
rec_clear()

# the priority: fifty obsolete-wait suspects and one wrong-needs suspect under a cap of forty: the wrong-needs one is judged
flood = build(closed(12, "dropped", "overtaken", 21, "[home] dropped"), *[hold_at(24 + k, 20, "home-agent: then check", f"board#{BID_02} first runs on the wake") for k in range(50)],
              item(15, wrote=now - 3 * H, state="doing", needs=["home-agent"], ask="Pick a colour", next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x"))
sus, _skip = AR.suspects(flood, now, env())
check("fifty obsolete-wait suspects rank after the wrong-needs one", len(sus) == 51 and sus[0]["id"] == f"board#{BID_05}" and "wrong-needs" in sus[0]["checks"] and all(s["priority"] == 3 for s in sus[1:]), [(s["id"], s["priority"]) for s in sus[:3]])
rec_clear(); fake(); rec = go(flood)
check("under the cap of 40 the wrong-needs suspect is judged, and the calls stop at the cap", rec["calls"]["made"] == 40 and any(f"Item board#{BID_05}:" in c["stdin"] for c in calls()), (rec["calls"], len(calls())))
rec_clear()

# ---- 28. why-not-now: a stored doing item that only waits for a later day (dated_wait.py) is asked "why not now?"
WNN = "why-not-now"
def ordinal(n): return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
def prose(n):                                                  # "Wed Nov 4th": the local day n days from now, as the board writes a date
    t = dt.datetime.fromtimestamp(now + n * 86400, ZONE)
    return t.strftime("%a %b ") + ordinal(t.day)
wake_in = lambda h: local(now + h * H).replace(" ", "T")
STEP = f"home-agent: {prose(2)} after the nightly run, check the result"
def selfwait(i, nxt=STEP, wake=None, ago=2, **kw): return doing(i, ago, nxt=nxt, wake=wake or wake_in(24), **kw)
sw = build(selfwait(32))
rec_clear(); fake(answers={f"board#{BID_22}": YES(WNN, "the step is dated two days out and nothing says why it waits for then", "do it now, or write what holds it")})
sus, _skip = AR.suspects(sw, now, env())
check("why-not-now: a doing item with a wake tomorrow and only a dated step is a suspect, priority 3 with obsolete-wait, with a signature and the wait as context",
      [(s["id"], s["checks"], s["priority"]) for s in sus] == [(f"board#{BID_22}", [WNN], 3)] and sus[0]["sig"] and "dated for later" in sus[0]["evidence"][WNN] and sus[0]["context"], sus)
rec = go(sw)
fnd = [f for f in rec["findings"] if f["category"] == WNN]
check("why-not-now: the audit asks, and a yes is a finding from the model on the item's mover", len(fnd) == 1 and fnd[0]["id"] == f"board#{BID_22}" and fnd[0]["source"] == "model" and fnd[0]["mover"] == "home-agent"
      and "nothing says why" in fnd[0]["detail"], rec["findings"])
check("why-not-now: one call, whose message names the check, the dated step and the wake, and the rubric carries the check",
      len(calls()) == 1 and rec["calls"]["made"] == 1 and f"- {WNN}: read as doing" in calls()[0]["stdin"] and "after the nightly run" in calls()[0]["stdin"] and "The wait (for why-not-now):" in calls()[0]["stdin"]
      and "why-not-now" in RUBRIC_TEXT and RUBRIC_TEXT in calls()[0]["argv"], calls())
check("why-not-now: the finding goes to the mover as one line '<id> · why-not-now · <evidence> · <fix>'", any(to == "home-agent" and f"board#{BID_22} · why-not-now · the step is dated" in t and "do it now, or write what holds it" in t for to, t, fy in sent), sent)
check("why-not-now: the verdict is kept with the signature", rec["judged"][f"board#{BID_22}"]["verdict"] == "yes" and rec["judged"][f"board#{BID_22}"]["check"] == WNN and rec["judged"][f"board#{BID_22}"]["sig"] == sus[0]["sig"], rec["judged"])

# not a suspect: one undated step, a wake 30 minutes out, a step dated today, no wake
nots = build(selfwait(70, nxt=STEP + "\nhome-agent: tidy the notes"), selfwait(17, wake=wake_in(0.5)), selfwait(49, nxt=f"home-agent: {prose(0)} check the result"), doing(18, 2, nxt=STEP))
check("why-not-now: an undated step, a wake 30 minutes out, a step dated today, or no wake is no suspect", AR.suspects(nots, now, env())[0] == [], [(s["id"], s["checks"]) for s in AR.suspects(nots, now, env())[0]])
rec_clear(); fake(); rec = go(nots)
check("why-not-now: …no call and no finding", calls() == [] and not [f for f in rec["findings"] if f["category"] == WNN], (len(calls()), rec["findings"]))

# a verdict stands while the dated lines and the wake stand; a 'yes' is carried; a changed line or wake is judged again
def yesterday_record():
    prev = json.loads(AR._record_path(now).read_text())
    (T / "state/audit" / f"run-{dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date().isoformat()}.json").write_text(json.dumps(dict(prev, started=now - 2 * 86400, finished=now - 2 * 86400 + 60)))
    AR._record_path(now).unlink()
rec_clear(); fake(answers={f"board#{BID_22}": YES(WNN)}); go(sw); yesterday_record()
rec = go(sw)
check("why-not-now: unchanged lines and wake: no new call, the 'yes' is carried as a finding", calls() == [] and rec["calls"]["unchanged"] == 1 and [f["id"] for f in rec["findings"] if f["category"] == WNN] == [f"board#{BID_22}"], (len(calls()), rec["calls"]))
AR._record_path(now).unlink()
rec = go(build(selfwait(32, wake=wake_in(30))))
check("why-not-now: a moved wake is judged again", len(calls()) == 1 and rec["calls"]["made"] == 1, rec["calls"])
AR._record_path(now).unlink()
rec = go(build(selfwait(32, nxt=f"home-agent: {prose(3)} after the weekly run, check the result")))
check("why-not-now: a changed dated line is judged again", len(calls()) == 1 and rec["calls"]["made"] == 1, rec["calls"])
AR._record_path(now).unlink()
rec = go(build(selfwait(32, nxt=STEP + "\nhome-agent: tidy the notes")))
check("why-not-now: a step that became undated: no suspect, no call, the old 'yes' is not sent again and not kept", calls() == [] and not [f for f in rec["findings"] if f["category"] == WNN] and f"board#{BID_22}" not in rec["judged"]
      and not [1 for to, t, fy in sent if WNN in t], (rec["findings"], rec["judged"]))
rec_clear()

# a 'no' is kept and not asked again
rec_clear(); fake(); go(sw); yesterday_record(); rec = go(sw)
check("why-not-now: a 'no' stands: no new call, no finding", calls() == [] and rec["calls"]["unchanged"] == 1 and not [f for f in rec["findings"] if f["category"] == WNN], (len(calls()), rec["calls"]))
rec_clear()

# the cap per run, the priority, and the call cap
many_sw = build(*[selfwait(44 + k) for k in range(8)])
sus, _skip = AR.suspects(many_sw, now, env())
check("why-not-now: at most five suspects a run", [s["id"] for s in sus] == [f"board#{9234 + k}" for k in range(5)], [s["id"] for s in sus])
rec_clear(); fake(); rec = go(many_sw)
check("why-not-now: the calls added are one per suspect, five here", rec["calls"]["made"] == 5 and rec["calls"]["suspects"] == 5 and len(calls()) == 5, rec["calls"])
rec_clear(); _cfg.CFG["audit"]["max_calls"] = 2; rec = go(many_sw)
check("why-not-now: the [audit] cap holds for this check as for the others", rec["calls"]["made"] == 2, rec["calls"])
_cfg.CFG["audit"]["max_calls"] = 40
mixed = build(*many_sw.items(), item(15, wrote=now - 3 * H, state="doing", needs=["home-agent"], ask="Pick a colour", next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x"))
sus, _skip = AR.suspects(mixed, now, env())
check("why-not-now: ranks after the other checks (a wrong-needs suspect comes first)", sus[0]["id"] == f"board#{BID_05}" and all(s["priority"] == 3 for s in sus[1:]), [(s["id"], s["priority"]) for s in sus[:3]])
rec_clear()

# ---- 28b. goal-unclear: an open item whose subject and `Goal:` bullet are new or reworded is asked "do both name an outcome wanted?"
GU = "goal-unclear"
def gitem(i, subject="[home] Make the nightly run finish by 06:00", goal="The nightly run finishes by 06:00", status="open", **kw):
    k, d = clean(i) if status == "open" else item(i, status=status, wrote=now - 2 * H)
    d["subject"] = subject
    d["description"] = f"- Goal: {goal}\n- Problem: it fails when the disk is full\n- Lives in the nightly unit" if goal is not None else "- A thing, finished when it works"
    d["metadata"].update(kw)
    return k, d
gs = build(gitem(14))
sus, _skip = AR.suspects(gs, now, env())
check("goal-unclear: an open item with a Goal bullet and no verdict yet is a suspect, priority 3, with the subject and the Goal sentence as evidence and a stamp",
      [(s["id"], s["checks"], s["priority"]) for s in sus] == [(f"board#{BID_04}", [GU], 3)] and sus[0]["gsig"] and len(sus[0]["gsig"]) == 12 and "subject: [home] Make the nightly run finish by 06:00" in sus[0]["evidence"][GU]
      and "Goal: The nightly run finishes by 06:00" in sus[0]["evidence"][GU], sus)
rec_clear(); fake(answers={f"board#{BID_04}": YES(GU, "the subject names the failure, not the result wanted", "model's own fix text")})
rec = go(gs)
fnd = [f for f in rec["findings"] if f["category"] == GU]
check("goal-unclear: a yes is a finding from the model on the item's mover, with the check's own fix text", len(fnd) == 1 and fnd[0]["id"] == f"board#{BID_04}" and fnd[0]["source"] == "model" and fnd[0]["mover"] == "home-agent"
      and fnd[0]["detail"] == "the subject names the failure, not the result wanted" and rec["judged"][f"board#{BID_04}"]["fix"] == AR.FIX[GU], rec["findings"])
check("goal-unclear: one call, whose message names the check with the subject and the Goal sentence, and the rubric carries the check",
      len(calls()) == 1 and rec["calls"]["made"] == 1 and f"- {GU}: the subject and the Goal bullet are new or reworded" in calls()[0]["stdin"] and "Goal: The nightly run finishes by 06:00" in calls()[0]["stdin"]
      and "\ngoal-unclear\n  An item states its goal twice" in RUBRIC_TEXT and RUBRIC_TEXT in calls()[0]["argv"], calls())
check("goal-unclear: delivered as '<id> · goal-unclear · <reason> · <fix>' to the mover", any(to == "home-agent" and f"board#{BID_04} · goal-unclear · the subject names the failure" in t and "reword the subject to the outcome wanted and the first bullet to `Goal:" in t for to, t, fy in sent), sent)
check("goal-unclear: the verdict and the (subject, Goal) stamp are on the record", rec["judged"][f"board#{BID_04}"]["verdict"] == "yes" and rec["judged"][f"board#{BID_04}"]["gsig"] == sus[0]["gsig"] and rec["goal_judged"] == {f"board#{BID_04}": sus[0]["gsig"]},
      (rec["judged"], rec.get("goal_judged")))

# not a suspect: no Goal bullet (filed before the form: the one-time pass's), a closed item, a Goal bullet with no sentence
nog = build(gitem(55, goal=None), gitem(50, status="completed"), (lambda k, d: (k, dict(d, description="- Goal:\n- Problem: x")))(*gitem(56)))
check("goal-unclear: an item with no Goal bullet, a closed item and a bare `Goal:` are no suspects", AR.suspects(nog, now, env())[0] == [], [(s["id"], s["checks"]) for s in AR.suspects(nog, now, env())[0]])
rec_clear(); fake(); rec = go(nog)
check("goal-unclear: …no call, no finding, no stamp", calls() == [] and not [f for f in rec["findings"] if f["category"] == GU] and rec["goal_judged"] == {}, (len(calls()), rec["goal_judged"]))

# the stamp stands: a 'yes' is carried while the item is unwritten; a 'no' is not asked again even when the item is written for something else
rec_clear(); fake(answers={f"board#{BID_04}": YES(GU)}); go(gs); yesterday_record()
rec = go(gs)
check("goal-unclear: unchanged pair: no new call, the 'yes' is carried as a finding", calls() == [] and [f["id"] for f in rec["findings"] if f["category"] == GU] == [f"board#{BID_04}"] and rec["goal_judged"] == {f"board#{BID_04}": sus[0]["gsig"]}, (len(calls()), rec["findings"]))
rec_clear(); fake(); go(gs); yesterday_record()
k, d = gitem(14, next="home-agent: build it, then check")
d["written_at"] = now - 0.5 * H
rec = go(build((k, d)))
check("goal-unclear: …a 'no' stands when the item is written for another reason (same pair): no call, no finding, the stamp kept", calls() == [] and not [f for f in rec["findings"] if f["category"] == GU] and rec["goal_judged"] == {f"board#{BID_04}": sus[0]["gsig"]},
      (len(calls()), rec["goal_judged"]))
# a reworded subject or Goal sentence is judged again, a reworded later bullet is not
for what, kw in (("subject", {"subject": "[home] Make the nightly run finish by 05:00"}), ("Goal sentence", {"goal": "The nightly run finishes by 05:00"})):
    rec_clear(); fake(); go(gs); yesterday_record()
    rec = go(build(gitem(14, **kw)))
    check(f"goal-unclear: a reworded {what} is judged again", len(calls()) == 1 and rec["calls"]["made"] == 1 and rec["goal_judged"][f"board#{BID_04}"] != sus[0]["gsig"], (rec["calls"], rec["goal_judged"]))
rec_clear(); fake(); go(gs); yesterday_record()
k, d = gitem(14); d["description"] = d["description"].replace("it fails when the disk is full", "it fails when the disk is full or the unit is stopped")
rec = go(build((k, d)))
check("goal-unclear: a reworded Problem bullet is no new pair: not judged again", calls() == [], len(calls()))
rec_clear(); fake(); go(gs); yesterday_record()
k, d = gitem(14, goal="  The   nightly run\tfinishes by 06:00 "); rec = go(build((k, d)))
check("goal-unclear: whitespace in the Goal sentence is no new pair", calls() == [], len(calls()))
# the stamp of a closed item goes; an item dropped from the board does too
rec_clear(); fake(); go(gs); yesterday_record()
rec = go(build(gitem(14, status="completed")))
check("goal-unclear: the stamp of an item that is no longer open is dropped", rec["goal_judged"] == {} and calls() == [], rec["goal_judged"])
rec_clear()

# the per-run cap, the call cap, and the rank
many_g = build(*[gitem(100 + k) for k in range(13)])
sus, _skip = AR.suspects(many_g, now, env())
check("goal-unclear: at most GOAL_MAX (ten) suspects a run", AR.GOAL_MAX == 10 and [s["id"] for s in sus] == [f"board#{9281 + k}" for k in range(10)], [s["id"] for s in sus])
rec_clear(); fake(); rec = go(many_g)
check("goal-unclear: one call per suspect, ten here, and ten stamps", rec["calls"]["made"] == 10 and len(rec["goal_judged"]) == 10, (rec["calls"], len(rec["goal_judged"])))
yesterday_record()
rec = go(many_g)
check("goal-unclear: the three left over are judged the next run (the first ten, judged, are not asked again)", rec["calls"]["made"] == 3 and len(rec["goal_judged"]) == 13, (rec["calls"], len(rec["goal_judged"])))
rec_clear(); _cfg.CFG["audit"]["max_calls"] = 2; rec = go(many_g)
check("goal-unclear: the [audit] cap holds for this check as for the others", rec["calls"]["made"] == 2, rec["calls"])
_cfg.CFG["audit"]["max_calls"] = 40
mixed_g = build(*many_g.items(), item(12, wrote=now - 3 * H, state="doing", needs=["home-agent"], ask="Pick a colour", next="home-agent: go", expected_by=local(now + 30 * H), expected_reason="x"))
sus, _skip = AR.suspects(mixed_g, now, env())
check("goal-unclear: ranks after the other checks (a wrong-needs suspect comes first)", sus[0]["id"] == f"board#{BID_02}" and all(s["priority"] == 3 for s in sus[1:]) and len(sus) == 11, [(s["id"], s["priority"]) for s in sus[:3]])
# an item that is a suspect for two checks lists both
k, d = gitem(95, ask="Pick a colour", state="doing", needs=["home-agent"]); d["written_at"] = now - 3 * H
sus, _skip = AR.suspects(build((k, d)), now, env())
check("goal-unclear: an item picked for other checks as well carries all of them, and the other checks rank it", len(sus) == 1 and GU in sus[0]["checks"] and "wrong-needs" in sus[0]["checks"] and sus[0]["priority"] < 3 and sus[0]["gsig"], [(s["id"], s["checks"], s["priority"]) for s in sus])
rec_clear(); fake(); reset_calls(); dry = AR.run(dry=True, now=now, items=gs, anchors={}, env=env(), rubric=RUBRIC_TEXT)
check("goal-unclear: a dry run lists the suspect, makes no call and writes no stamp", [s["id"] for s in dry["suspects"]] == [f"board#{BID_04}"] and calls() == [] and not list((T / "state/audit").glob("run-*.json")), dry["suspects"])
rec_clear()

# ---- the ten-minute passes make the filing and date checks; the daily run does not (tests/filing_scenario.py and tests/dates_scenario.py cover the passes themselves)
rec_clear(); (T / "state/audit/filing.json").exists() and (T / "state/audit/filing.json").unlink(); (T / "state/audit/dates.json").exists() and (T / "state/audit/dates.json").unlink()
sent.clear()
fp_res = AR.filing_pass(now=now, items=f1, anchors={}, env=env())
fp_sent = [(to, text) for to, text, _f in sent]
check("filing: the pass sent f1's filing findings (the stuck-elsewhere one to its session, the mislabeled-state one on the decision item to the project's -main agent)", any(to == "ops-other" and "board#3 · stuck-elsewhere" in t for to, t in fp_sent)
      and any("board#1 · board checks · mislabeled-state" in t for _to, t in fp_sent), fp_sent)
sent.clear()
dp_res = AR.dates_pass(now=now, items=f1, anchors={}, env=env())
check("dates: the dates pass sent the item past its wake, the stale finding the daily run no longer makes", [t for to, t, _f in sent if "board#2 · stale · past its wake" in t] != [] and dp_res["fresh"] == 1, (dp_res, sent))
rec = go(f1)
daily_text = "\n".join(t for _to, t, _f in sent)
check("filing: the daily run makes none of those: no stuck-elsewhere, no filing kind of board checks, no wake-passed stale, and still sends the rest", "stuck-elsewhere" not in daily_text and "mislabeled-state" not in daily_text and "arbitrary-hold" not in daily_text
      and "board#2 · stale" not in daily_text and "board#1 · ask-missing" in daily_text and "board#4 · next rules" in daily_text and "board#5" not in daily_text, daily_text)
check("filing: …none of them is on the daily record, which counts only what the run checks", rec["repeats"] == 0 and not {f["category"] for f in rec["findings"]} & {"stuck-elsewhere", "stale"}
      and not [f for f in rec["findings"] if f["category"] == "board checks" and f["detail"].startswith(("mislabeled-state", "arbitrary-hold"))] and rec["by_category"].get("stuck-elsewhere") is None, (rec["repeats"], rec["by_category"], rec["findings"]))
f1w = dict(f1); k3, d3 = doing(3, 1, nxt="ops-other: do the first part\nhome-agent: then the second", expected_by=local(now + 30 * H), expected_reason="the build"); d3["written_at"] = time.time() + 60; f1w[k3] = d3
rec_clear(); sent.clear(); AR.filing_pass(now=now + 1, items=f1w, anchors={}, env=env())
check("filing: an item written since the pass sent its finding is sent again, by the pass", "board#3 · stuck-elsewhere" in "\n".join(t for _to, t, _f in sent), sent)
rec_clear(); (T / "state/audit/filing.json").unlink(); (T / "state/audit/dates.json").unlink()
rec = go(f1)
check("filing: with no pass record the daily run still sends none of the moved checks (they are the passes', not a fallback of the run)", not any(w in "\n".join(t for _to, t, _f in sent) for w in ("stuck-elsewhere", "mislabeled-state", "board#2 · stale")))
rec_clear()

# ---- 29. two runs a day ([audit] at = ["05:00", "20:00"]): a second run on one date keeps the first one's record, is not refused, names itself in its messages, and every check that looks back reads days, not runs
# a fixed clock two days back: D at 05:00 and 20:00 local time, then D+1 at 05:00; the items were last written before D, so nothing moves between the runs
Dd = dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date()
at_local = lambda d, h: dt.datetime(d.year, d.month, d.day, h, 0, tzinfo=ZONE).timestamp()
t1, t2, t3 = at_local(Dd, 5), at_local(Dd, 20), at_local(Dd + dt.timedelta(days=1), 5)
Dstr, D2str = Dd.isoformat(), (Dd + dt.timedelta(days=1)).isoformat()
W = t1 - 2 * 86400
def itemW(i, **meta):
    k, d = item(i, wrote=W, **meta); d["state_updated"] = d["confirmed"] = W; return k, d
def cleanW(i): return itemW(i, state="doing", needs=["home-agent"], next="home-agent: build it", wake=local(t3 + 30 * H), expected_by=local(t3 + 30 * H), expected_reason="the build runs overnight")
two = build(itemW(1, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick one"),            # ask-missing, the owner's own: to the project's -main agent
            itemW(2, state="your-call", needs=["decision"], mover="home-agent", next="home-agent: pick one"),     # ask-missing, a background agent's: straight to it
            *[cleanW(10 + k) for k in range(12)])
def go_at(items, t): return go(items, now=t, env_=env(clock=lambda: t + 300))
heads = lambda: [t.splitlines()[0] for to, t, fy in sent if "Board audit" in t.splitlines()[0]]
dig = lambda: [t for to, t, fy in sent if to == "alpha-builder" and "chase the mover" in t]
summ = lambda: [t for to, t, fy in sent if to == "projects/example"]

# the tightening history counts days: yesterday's two runs are one day (a record whose top category is ask-missing)
def seed(t, cat="ask-missing"):
    AR._record_path(t).write_text(json.dumps({"started": t, "finished": t + 600, "items_read": 14, "findings": [], "by_session": {}, "by_category": {cat: 2}, "stuck": [], "idle_pass": [], "judged": {}}))
rec_clear()
seed(at_local(Dd - dt.timedelta(days=1), 5)); seed(at_local(Dd - dt.timedelta(days=1), 20))
r1 = go_at(two, t1)
check("two runs a day: yesterday's two records are one day of history, so 'the top category 3 days running' is not tripped by them", pushed == [] and r1["by_category"].get("ask-missing") == 2, (pushed, r1["by_category"]))
seed(at_local(Dd - dt.timedelta(days=2), 5))
rec_clear_run = AR._record_path(t1); rec_clear_run.unlink()
r1 = go_at(two, t1)
check("…and with a second earlier day on top, it is (3 days running)", len(pushed) == 1 and "ask-missing is the top category 3 days running" in pushed[0][1], pushed)
hist_ = [{"date": "d4", "started": 4}, {"date": "d3", "started": 31}, {"date": "d3", "started": 30}, {"date": "d2", "started": 21}, {"date": "d2", "started": 20}, {"date": "d1", "started": 10}]
check("by_day: the newest record of each earlier day, the run's own date left out", [(h["date"], h["started"]) for h in AR.by_day(hist_, "d4")] == [("d3", 31), ("d2", 21), ("d1", 10)]
      and AR.by_day([], "d4") == [] and [h["date"] for h in AR.by_day(hist_[1:], "d3")] == ["d2", "d1"], AR.by_day(hist_, "d4"))

# the chain: 05:00, 20:00 the same date, 05:00 the next date
rec_clear(); fake()
r1 = go_at(two, t1)
check("run 1 (05:00): its record is run-<date>-050000.json, its messages and summary carry the plain date", AR._record_path(t1).name == f"run-{Dstr}-050000.json" and AR._record_path(t1).is_file()
      and r1["started"] == t1 and heads() and all(h.startswith(f"[stackshot] Board audit {Dstr}:") or h.startswith(f"[stackshot] Board audit {Dstr} (script)") for h in heads()) and len(item_msgs()) == 2
      and r1["repeats"] == 0 and r1["stuck"] == [], (heads(), r1["stuck"]))
before1 = AR._record_path(t1).read_bytes()
code, why = audit.claim(t2)
check("a second run the same date is not refused as 'already run today': the cue is claimed (202) with the first run finished", code == 202 and AR._record_path(t2).is_file(), (code, why))
AR._record_path(t2).unlink()
r2 = go_at(two, t2)
check("run 2 (20:00, the same date): a record of its own beside the first, which is as it was", AR._record_path(t2).name == f"run-{Dstr}-200000.json" and AR._record_path(t2).is_file() and AR._record_path(t1).read_bytes() == before1
      and r2["started"] == t2, (sorted(p.name for p in (T / "state/audit").glob("run-*.json"))))
check("…readers see both, the later first; last() and status() read the 20:00 run", [r["started"] for r in audit.runs()] == [t2, t1] and {r["date"] for r in audit.runs()} == {Dstr}
      and audit.last()["started"] == t2 and audit.status(t2 + 3600)["last"]["started"] == t2, [r["started"] for r in audit.runs()])
check("…its messages and summary say which run of the date it is (20:00); the first run's text was the plain date", heads() and all(f"Board audit {Dstr} 20:00" in h for h in heads()) and summ() and "Board audit " + Dstr + " 20:00 (script)" in summ()[0], (heads(), summ()))
check("…it sends nothing the first run sent (the same findings, their items unwritten): `repeats` counts them", item_msgs() == [] and r2["repeats"] == len(r1["findings"]) > 0, (item_msgs(), r2["repeats"], len(r1["findings"])))
check("…the unmoved digest: the run before is the 05:00 one (9 hours earlier, over the 6-hour floor), so the two unwritten items are unmoved and chased to the builder once",
      sorted(s["id"] for s in r2["stuck"]) == ["board#1", "board#2"] and all(s["chased"] for s in r2["stuck"]) and len(dig()) == 1 and "board#1" in dig()[0] and "board#2" in dig()[0]
      and f"unmoved since {Dstr}" in dig()[0] and f"Board audit {Dstr} 20:00" in dig()[0], (r2["stuck"], dig()))
r3 = go_at(two, t3)
check("run 3 (05:00 the next date): the plain date again, the digest not repeated, `stuck` still names the items", all(f"Board audit {D2str}" in h and "20:00" not in h for h in heads()) and dig() == [] and sorted(s["id"] for s in r3["stuck"]) == ["board#1", "board#2"]
      and all(s["chased"] for s in r3["stuck"]) and AR._record_path(t3).name == f"run-{D2str}-050000.json" and [r["started"] for r in audit.runs()] == [t3, t2, t1], (heads(), dig(), r3["stuck"]))
check("…the previous run for the unmoved comparison is the 20:00 one, 9 hours back, not the 05:00 one from a day ago", AR.previous(t3)[0]["started"] == t2 and AR.previous(t2)[0]["started"] == t1 and AR.previous(t1)[0] is None, (AR.previous(t3)[0] or {}).get("started"))

# the threshold message goes out per run, labelled like the run's other messages
rec_clear(); _cfg.CFG["audit"]["threshold"] = 1
go_at(two, t1); p1 = [t for to, t in pushed]
go_at(two, t2); p2 = [t for to, t in pushed]
_cfg.CFG["audit"]["threshold"] = 5
check("the threshold message: one per run, the first headed with the date, the second with the date and 20:00", len(p1) == 1 and len(p2) == 1 and p1[0].startswith(f"[stackshot] Board audit {Dstr} tripped a threshold")
      and p2[0].startswith(f"[stackshot] Board audit {Dstr} 20:00 tripped a threshold"), (p1, p2))
check("run_label: the first run of a date (so a once-a-day schedule with no other run that day) is the plain date", AR.run_label(t1, []) == Dstr and AR.run_label(t2, []) == Dstr
      and AR.run_label(t3, [{"date": Dstr, "started": t2}]) == D2str and AR.run_label(t2, [{"date": Dstr, "started": t1}]) == f"{Dstr} 20:00", (AR.run_label(t2, [{"date": Dstr, "started": t1}])))
rec_clear()

# ---- 30. the pages stage: the page-debt call is made once per run, after the judgment calls, under the run's time limit; a failed page or a failed stage never stops the run
pages_asked = []
def pages_ans(ans):
    def f(run, deadline): pages_asked.append((run, deadline)); return ans
    return f
def pages_raises(run, deadline): pages_asked.append((run, deadline)); raise RuntimeError("[0] ConnectionRefusedError")
def summary_of(): return [t for to, t, fy in sent if to == "projects/example"][0]
tP = now + 7                                                                      # the run's start; its stamp names the run to the server
rec_clear(); pages_asked.clear()
rec = go({}, now=tP, env_=env(pages=pages_ans({"enabled": True, "mode": "live", "counts": {"pages": 3, "applied": 1, "fallback": 1, "error": 1}})))
check("the stage asks the pass once per run, naming the run by its start stamp, with the end of the run's time budget as the deadline", pages_asked == [(AR._stamp_of(tP), tP + 100 * 60)], pages_asked)
check("…the record carries it: called, results, pages without an edit (a page whose call raised counts), nothing left", rec["pages"] == {"enabled": True, "mode": "live", "called": 3, "left": 0,
      "results": {"applied": 1, "fallback": 1, "error": 1}, "failed": 2, "timed_out": False, "note": ""}, rec.get("pages"))
check("…the run went on: the summary has the pages part and was sent, the record is finished with no error", "pages (live): 3 called (1 applied, 1 error, 1 fallback), 2 without an edit" in summary_of() and rec.get("error") is None
      and audit.last()["pages"]["called"] == 3, summary_of())
rec_clear(); pages_asked.clear()
rec = go({}, now=tP, env_=env(pages=pages_ans({"enabled": False, "mode": "", "counts": {}})))
check("[router] page_debt off (the server says so): the stage is recorded as off and the summary says nothing of pages", rec["pages"]["enabled"] is False and rec["pages"]["failed"] == 0 and " · pages" not in summary_of(), summary_of())
rec_clear()
with contextlib.redirect_stderr(io.StringIO()) as se:
    rec = go({}, now=tP, env_=env(pages=pages_raises))
check("a stage that fails altogether (the server not reached) is counted and noted, logged to stderr, and the run still ends with its record and summary", rec["pages"]["failed"] == 1 and rec["pages"]["enabled"] is None
      and rec["pages"]["note"].startswith("the pages stage failed: RuntimeError: [0] ConnectionRefusedError") and "pages: the pages stage failed" in summary_of() and rec.get("error") is None
      and "audit run: the pages stage failed" in se.getvalue(), (rec["pages"], se.getvalue()))
rec_clear(); pages_asked.clear()
rec = go({}, now=tP, env_=env(pages=pages_ans({"enabled": True, "mode": "shadow", "counts": {"pages": 1, "proposed": 1, "left": 2}})))
check("pages left at the server's deadline are on the record as timed out and the summary names them", rec["pages"]["left"] == 2 and rec["pages"]["timed_out"] is True and rec["pages"]["failed"] == 0
      and "pages (shadow): 1 called (1 proposed), 2 left for the next run" in summary_of() and "2 page(s) wait for the next run" in rec["pages"]["note"], (rec["pages"], summary_of()))
rec_clear(); pages_asked.clear()
rec = go({}, now=tP, env_=env(pages=pages_ans({"enabled": True, "mode": "live", "counts": {"pages": 0}}), clock=lambda: tP + 101 * 60))
check("the run's time budget already spent when the stage would begin: the server is not asked, the stage is recorded timed out", pages_asked == [] and rec["pages"]["timed_out"] is True and rec["pages"]["called"] == 0
      and "100 minutes passed" in rec["pages"]["note"], (pages_asked, rec["pages"]))
rec_clear(); pages_asked.clear()
fake(); clk2 = lambda: tP + len(calls()) * 40 * 60
rec = go(f2, now=tP, env_=env(clock=clk2, pages=pages_ans({"enabled": True, "mode": "live", "counts": {"pages": 1, "applied": 1}})))
check("the judgment calls come first and the stage shares their budget: three calls of 40 minutes use it up, so the stage is not asked", rec["calls"]["timed_out"] is True and pages_asked == [] and rec["pages"]["timed_out"] is True, (rec["calls"], pages_asked))
from stackshot.fleet import client as _client
real_pd = _client.page_debt
got = []
def fake_pd(run, deadline=None, timeout=600.0): got.append((run, deadline, timeout)); return fake_pd.ans
try:
    _client.page_debt = fake_pd
    fake_pd.ans = (200, {"enabled": True, "mode": "live", "counts": {"pages": 1, "applied": 1}})
    ans = AR._pages_ask("r-1", time.time() + 6000)
    check("the default stage asks the server through client.page_debt, with a timeout that outlasts the deadline by the grace", ans["counts"] == {"pages": 1, "applied": 1} and got[0][0] == "r-1"
          and 6000 + AR.PAGES_GRACE_S - 5 <= got[0][2] <= 6000 + AR.PAGES_GRACE_S + 5, got)
    fake_pd.ans = (503, {"error": "the standby copy is read only"})
    try: AR._pages_ask("r-2", time.time() + 60); raised = ""
    except RuntimeError as e: raised = str(e)
    check("…a refusal or an unreachable server is an error the stage counts, with the status in it", raised.startswith("[503] "), raised)
finally:
    _client.page_debt = real_pd
import _docs
pg_doc = _docs.pages()
check("the docs name the pages stage, its route and the run's mark, and no daily 09:00 call or start hour", "`POST /client/page-debt`" in _docs.page("router") and "pages_stage" in _docs.page("audit") and "page_debt_hour" not in pg_doc
      and "daily page" not in pg_doc and "thread of its own, once a day per page" not in pg_doc)

# ---- 31. the orphan hand-over stage: the first stage of a run; the server finds and moves (tests/successor_scenario.py holds that half), the run asks, records and reports
orph_asked = []
def orph_ans(ans):
    def f(apply): orph_asked.append(apply); return ans
    return f
def orph_raises(apply): orph_asked.append(apply); raise RuntimeError("[0] ConnectionRefusedError")
MOVED_ROW = {"id": "c12", "project": "projects/alpha", "from": "kid-main", "to": "par-main", "tier": "parent", "why": "kid-main is gone (a retired session, its pane gone); closest live agent: par-main"}
LEFT_ROW = {"id": "c13", "project": "projects/solo", "from": "solo-main", "why": "solo-main is gone; no live successor was found"}
ORPH_ANS = {"checked": True, "applied": True, "read": 9, "found": 2, "moved": [MOVED_ROW], "left": [LEFT_ROW], "skipped": 0, "over_cap": 0, "note": ""}
tO = now + 11
check("orphans: the shipped default is report (the example config names it, and a missing or unknown value reads as it); apply is switched on by the setting", _cfg.audit_orphan_handover() == "report"
      and 'orphan_handover = "report"' in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), _cfg.audit_orphan_handover())
_cfg.CFG["audit"]["orphan_handover"] = "apply"
rec_clear(); sent.clear(); orph_asked.clear()
rec = go({}, now=tO, env_=env(orphans=orph_ans(ORPH_ANS)))
check("orphans: a run asks the server once, to apply (the default mode is apply), before it reads the board", orph_asked == [True], orph_asked)
check("…the record carries the stage: mode, counts, the item moved with its reason and the one left with no live successor", rec["orphans"]["mode"] == "apply" and rec["orphans"]["applied"] is True and rec["orphans"]["found"] == 2
      and rec["orphans"]["moved_n"] == 1 and rec["orphans"]["left_n"] == 1 and rec["orphans"]["moved"][0]["to"] == "par-main" and rec["orphans"]["left"][0]["id"] == "c13", rec.get("orphans"))
check("…the summary line says how many were handed over and how many have no live successor, and names each item under it (from → to, why; the one left)", "orphan hand-over (apply): 1 handed over, 1 with no live successor" in summary_of()
      and "orphan handed over · c12 · kid-main → par-main · kid-main is gone" in summary_of() and "orphan left · c13 · solo-main · no live agent to take it (projects/solo)" in summary_of(), summary_of())
rec_clear(); sent.clear(); orph_asked.clear()
rec = go({}, now=tO, env_=env(orphans=orph_ans({"checked": True, "applied": True, "read": 9, "found": 0, "moved": [], "left": []})))
check("orphans: an audit that finds nothing leaves the summary without a word of it, the record shows the stage ran", " · orphan hand-over" not in summary_of() and "orphan " not in summary_of() and rec["orphans"]["found"] == 0 and rec["orphans"]["checked"], summary_of())
rec_clear(); sent.clear(); orph_asked.clear()
with contextlib.redirect_stderr(io.StringIO()) as se:
    rec = go({}, now=tO, env_=env(orphans=orph_raises))
check("orphans: a stage that fails (the server not reached) is a stage not made: said in the summary and the record, the run goes on and is finished with no error", rec.get("error") is None and rec["orphans"]["failed"] is True
      and "the orphan hand-over failed: RuntimeError: [0] ConnectionRefusedError" in summary_of() and "orphan hand-over failed" in se.getvalue(), (rec.get("orphans"), summary_of()))
rec_clear(); sent.clear(); orph_asked.clear()
rec = go({}, now=tO, env_=env(orphans=orph_ans({"checked": False, "mode": "apply", "note": "the fleet's heartbeat is empty: every session would look gone, nothing was checked"})))
check("orphans: an answer 'not checked' (an empty heartbeat) is said in the summary with the server's reason and moves nothing", "orphan hand-over: the fleet's heartbeat is empty" in summary_of() and rec["orphans"]["moved_n"] == 0, summary_of())
for mode in ("report", "off"):
    _cfg.CFG["audit"]["orphan_handover"] = mode
    rec_clear(); sent.clear(); orph_asked.clear()
    rec = go({}, now=tO, env_=env(orphans=orph_ans({**ORPH_ANS, "applied": False})))
    if mode == "report":
        check("orphans: [audit] orphan_handover = report asks for a read only (apply false), lists what it found, names it 'would move'", orph_asked == [False] and "would be handed over" in summary_of() and "orphan would move · c12" in summary_of(), (orph_asked, summary_of()))
    else:
        check("orphans: [audit] orphan_handover = off makes no call and the record has no orphans part", orph_asked == [] and "orphans" not in rec and "orphan" not in summary_of(), (orph_asked, rec.keys()))
_cfg.CFG["audit"]["orphan_handover"] = "apply"
out = []; orph_asked.clear(); rec_clear()
res = AR.run(dry=True, now=now, items={}, anchors={}, env=env(orphans=orph_ans({**ORPH_ANS, "applied": False})), rubric=RUBRIC_TEXT, out=out.append)
check("orphans: a dry run asks for a read only (apply false), prints the [orphans] line and each [orphan] row, writes no record and sends nothing", orph_asked == [False] and res["orphans"]["moved_n"] == 1 and not list((T / "state/audit").glob("run-*.json"))
      and any(ln.startswith("  [orphans · apply] 9 open items read · 2 with a mover that is gone · 1 would move to the closest live agent · 1 with no live successor") for ln in out)
      and any("[orphan] would move · c12 · kid-main → par-main" in ln for ln in out) and any("[orphan] left · c13" in ln for ln in out), out)
real_oh = _client.orphan_handover
got_o = []
def fake_oh(apply, timeout=120.0): got_o.append(apply); return fake_oh.ans
try:
    _client.orphan_handover = fake_oh
    fake_oh.ans = (200, ORPH_ANS)
    check("orphans: the default stage asks the server through client.orphan_handover with the run's apply flag", AR._orphans_ask(True) == ORPH_ANS and got_o == [True], got_o)
    fake_oh.ans = (503, {"error": "the standby copy is read only"})
    try: AR._orphans_ask(False); raised = ""
    except RuntimeError as e: raised = str(e)
    check("…a refusal or an unreachable server is an error the stage counts, with the status in it", raised.startswith("[503] "), raised)
finally:
    _client.orphan_handover = real_oh
rec_clear(); sent.clear()
check("the docs name the orphan hand-over, its route, its setting and the by-hand verb", "orphan hand-over" in _docs.page("audit") and "`POST /client/orphan-handover`" in _docs.page("audit") and "orphan_handover" in _docs.page("audit") and "audit.py orphans" in _docs.page("audit"))

# ---- 32. the summary's destination is a setting: [audit] summary_to, the stand-in page by default
STAND_IN = "projects/example"; REPORTS = "projects/example-reports"
_au = _cfg.CFG["audit"]; _was = _au.pop("summary_to", None)
try:
    check("summary_to: the default is the stand-in page, and so is the example config's value", _cfg.audit_summary_to() == STAND_IN
          and 'summary_to = "projects/example"' in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), _cfg.audit_summary_to())
    rec_clear()
    rec = go({}, now=now + 21)
    check("…a run with the key unset sends its summary to the stand-in page (fyi), and the record says so", [(to, fy) for to, t, fy in sent if "Board audit" in t] == [(STAND_IN, True)]
          and [m["to"] for m in rec["messages"] if m.get("kind") == "summary"] == [STAND_IN], (sent, rec["messages"]))
    for bad in ("", "  ", "has space", "projects//x", "/projects/x", 7, ["projects/x"]):
        _au["summary_to"] = bad
        check(f"…a value that is no page key ({bad!r}) reads as the default, and notes() names it unless it is empty", _cfg.audit_summary_to() == STAND_IN
              and bool(_cfg.report_notes(_cfg.CFG)) == (bad not in ("", "  ")), (_cfg.audit_summary_to(), _cfg.report_notes(_cfg.CFG)))
    _au["summary_to"] = " " + REPORTS + " "
    check("…a set value is read with its spaces cut", _cfg.audit_summary_to() == REPORTS and _cfg.report_notes(_cfg.CFG) == [], _cfg.audit_summary_to())
    rec_clear()
    rec = go({}, now=now + 22)
    check("a configured summary_to receives the summary (fyi) and the stand-in page receives nothing", [(to, fy) for to, t, fy in sent if "Board audit" in t] == [(REPORTS, True)]
          and not [1 for to, t, fy in sent if to == STAND_IN], sent)
    check("…and the run record's summary message is addressed to it", [m["to"] for m in rec["messages"] if m.get("kind") == "summary"] == [REPORTS], rec["messages"])
    # the release report's destination is read the same way (release.sh asks config.release_report_to(); tests/release_scenario.py holds the shell half)
    _rl = _cfg.CFG.pop("release", None)
    check("report_to: the default is the stand-in page, and so is the example config's value", _cfg.release_report_to() == STAND_IN
          and tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))["release"]["report_to"] == STAND_IN, _cfg.release_report_to())
    _cfg.CFG["release"] = {"report_to": REPORTS}
    check("…a configured value is read, and notes() has nothing to say", _cfg.release_report_to() == REPORTS and _cfg.report_notes(_cfg.CFG) == [], _cfg.release_report_to())
    _cfg.CFG["release"]["report_to"] = "two words"
    check("…a malformed one reads as the default, and notes() (so doctor and a reload) names it", _cfg.release_report_to() == STAND_IN
          and any("[release] report_to" in n for n in _cfg.report_notes(_cfg.CFG)) and any("[release] report_to" in n for n in _cfg.notes(_cfg.CFG)), _cfg.report_notes(_cfg.CFG))
    _cfg.CFG.pop("release", None)
    if _rl is not None: _cfg.CFG["release"] = _rl
finally:
    _au.pop("summary_to", None)
    if _was is not None: _au["summary_to"] = _was

# ---- 33. the project registry stage (tools/registry_report.py): one message per agent listing the record's problems with the fix of each; silent when the record has no projects; a check that fails is a check not made
ROLES["falcon-main"] = {"role": "front"}
def rgf(page, line, name, to, project="prj_0000b001"): return {"page": page, "line": line, "name": name, "fix": f"run `tools/project.py mirror {project}`", "project": project, "to": to}
RG = {"checked": True, "note": "", "projects": 3, "pages": 5, "findings": [rgf("projects/alpha", "page lines differ", "display-name", "alpha-main"), rgf("projects/beta", "page with no project", "Beta", "alpha-main", ""),
                                                                              rgf("projects/gamma", "project's page is gone", "home-gamma", "alpha-builder"), rgf("projects/delta", "two projects on one page", "prj_a, prj_b", "")]}
f33 = build(clean(1))
def rg_env(answer, **kw): return env(registry_check=lambda items, at: answer(items, at) if callable(answer) else answer, **kw)
try:
    _cfg.CFG.pop("registry_audit", None)
    rec_clear(); fake(); rec = go(f33, env_=rg_env(RG))
    rg_off = [t for to, t, fy in sent if "Project registry" in t and to != "projects/example"]
    check("registry, [registry_audit] send unset (the default): the findings are on the record and the summary, and nobody is messaged", rg_off == [] and not [m for m in rec["messages"] if m.get("kind") == "registry"]
          and len(rec["registry"]["findings"]) == 4 and rec["registry"]["send"] is False and any("registry problems 4" in t for to, t, fy in sent if to == "projects/example"), (rg_off, rec["registry"]))
    out = []; AR.run(dry=True, now=now, items=f33, anchors={}, env=rg_env(RG), rubric=RUBRIC_TEXT, out=out.append)
    check("registry, …a dry run says sending is off, and still lists the problems", any("[registry · sending off: [registry_audit] send = false] 4 problem(s)" in l for l in out) and any("[registry] projects/alpha" in l for l in out), out)
    for bad in (False, "true", 1, "yes", None):
        _cfg.CFG["registry_audit"] = {"send": bad}
        rec_clear(); rec = go(f33, env_=rg_env(RG))
        check(f"registry, …send = {bad!r} (anything but the boolean true) sends nothing either", not [1 for to, t, fy in sent if "Project registry" in t and to != "projects/example"], sent)
    _cfg.CFG["registry_audit"] = {"send": True}
    check("registry, config.registry_audit_send() reads the boolean true only", _cfg.registry_audit_send() is True and tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))["registry_audit"]["send"] is False)
    rec_clear(); fake(); rec = go(f33, env_=rg_env(RG))
    rg_msgs = {to: (text, fyi) for to, text, fyi in sent if "Project registry" in text and to != "projects/example"}
    check("registry: one message to each agent the problems go to (a finding with nobody live goes to the audit's -main agent), not fyi, kind registry on the record",
          sorted(rg_msgs) == ["alpha-builder", "alpha-main", "falcon-main"] and all(fyi is False for _, fyi in rg_msgs.values())
          and sorted((m["to"], m["lines"]) for m in rec["messages"] if m.get("kind") == "registry") == [("alpha-builder", 1), ("alpha-main", 2), ("falcon-main", 1)], (sorted(rg_msgs), rec["messages"]))
    check("...a front agent's message starts with [for Oliver], a background agent's does not; each line is '<page> · <problem> · <name> · <fix>' and the head says each line names its fix",
          rg_msgs["alpha-main"][0].startswith("[for Oliver]") and rg_msgs["falcon-main"][0].startswith("[for Oliver]") and not rg_msgs["alpha-builder"][0].startswith("[for Oliver]")
          and "projects/alpha · page lines differ · display-name · run `tools/project.py mirror prj_0000b001`" in rg_msgs["alpha-main"][0] and "each line says the fix" in rg_msgs["alpha-main"][0]
          and all(len(l.split(" · ")) == 4 for t, _ in rg_msgs.values() for l in t.splitlines() if l.startswith("projects/")), rg_msgs)
    check("...the record carries them apart from the item findings: registry, no finding and no category count; the summary says how many",
          rec["registry"]["checked"] is True and len(rec["registry"]["findings"]) == 4 and rec["registry"]["findings"][0].keys() >= {"page", "line", "name", "project", "to"} and rec["findings"] == []
          and "registry" not in " ".join(rec["by_category"]) and any("registry problems 4" in t for to, t, fy in sent if to == "projects/example"), (rec["registry"], rec["by_category"]))
    check("...it is no page agent line: those two checks send their own messages", not [1 for to, t, fy in sent if "Page agent lines" in t and to != "projects/example"])

    rec_clear(); rec = go(f33, env_=rg_env({"checked": False, "note": "the project record has no projects", "silent": True, "projects": 0, "pages": 0, "findings": []}))
    check("registry, empty record: nothing is sent, the summary says nothing about it, the record says not checked", not [1 for to, t, fy in sent if "Project registry" in t]
          and not any("registry" in t for to, t, fy in sent if to == "projects/example") and rec["registry"]["checked"] is False and not [m for m in rec["messages"] if m.get("kind") == "registry"], (sent, rec["registry"]))
    rec_clear(); rec = go(f33, env_=rg_env({"checked": False, "note": "something", "projects": 0, "pages": 0, "findings": []}))
    check("registry, a check not made without being silent: the summary says not checked and why, and nothing is sent", any("registry not checked (something)" in t for to, t, fy in sent if to == "projects/example")
          and not [1 for to, t, fy in sent if "Project registry" in t], [t for to, t, fy in sent if to == "projects/example"])
    rec_clear(); rec = go(f33, env_=rg_env({**RG, "findings": [], "note": ""}))
    check("registry, no problem: nothing is sent and the summary says 0", not [1 for to, t, fy in sent if "Project registry" in t] and any("registry problems 0" in t for to, t, fy in sent if to == "projects/example"))
    def rg_boom(items, at): raise RuntimeError("registry exploded")
    rec_clear(); rec = go(f33, env_=rg_env(rg_boom))
    check("registry, a check that raises is a check not made: the run goes on and finishes its record", rec["finished"] is not None and rec["registry"]["checked"] is False and "failed" in rec["registry"]["note"], rec["registry"])
    seen33 = []
    rec_clear(); rec = go(f33, env_=rg_env(lambda items, at: seen33.append((sorted(items), at)) or RG))
    check("registry: the check is given the run's items and its time", seen33 and seen33[0][0] == sorted(f33) and seen33[0][1] == now, seen33)
    rec_clear(); sent.clear(); out = []
    res = AR.run(dry=True, now=now, items=f33, anchors={}, env=rg_env(RG), rubric=RUBRIC_TEXT, out=out.append)
    check("registry, a dry run lists the problems with their recipients, sends nothing and writes no record", any("[registry · sending on] 4 problem(s) on 4 page(s)" in l for l in out) and any("[registry] projects/alpha" in l and "(to alpha-main)" in l for l in out)
          and any("[registry] projects/delta" in l and "(to falcon-main)" in l for l in out) and res["registry"]["checked"] is True and sent == [] and list((T / "state/audit").glob("run-*.json")) == [], (out, sent))
    out = []
    AR.run(dry=True, now=now, items=f33, anchors={}, env=rg_env({"checked": False, "note": "x", "silent": True, "projects": 0, "pages": 0, "findings": []}), rubric=RUBRIC_TEXT, out=out.append)
    check("registry, a dry run on an empty record says nothing about it", not any("[registry]" in l for l in out), out)
    # once a day: a second run of the date sends an agent nothing a delivered message of the date already told it; a message that was not delivered is tried again; the next date sends again
    rec_clear(); rec1 = go(f33, env_=rg_env(RG)); first = sorted(to for to, t, fy in sent if "Project registry" in t and to != "projects/example")
    rec2 = go(f33, env_=rg_env(RG), now=now + 600); second = [to for to, t, fy in sent if "Project registry" in t and to != "projects/example"]
    check("registry, once a day: the first run of a date tells three agents, a second run of the same date tells none and the record names who was told earlier", first == ["alpha-builder", "alpha-main", "falcon-main"] and second == []
          and sorted(rec2["registry"]["told_earlier_today"]) == first and not [m for m in rec2["messages"] if m.get("kind") == "registry"] and len(rec2["registry"]["findings"]) == 4, (first, second, rec2["registry"]))
    rec3 = go(f33, env_=rg_env(RG), now=now + 86400 + 600); third = sorted(to for to, t, fy in sent if "Project registry" in t and to != "projects/example")
    check("registry, …the next date tells them again (until the problem is fixed)", third == first and rec3["registry"]["told_earlier_today"] == [], third)
    rec_clear()
    def flaky(to, text, fyi=False):
        sent.append((to, text, fyi)); return (to != "alpha-main"), "[500] no"
    rec_a = go(f33, env_=rg_env(RG, deliver=flaky)); rec_b = go(f33, env_=rg_env(RG), now=now + 600); retried = [to for to, t, fy in sent if "Project registry" in t and to != "projects/example"]
    check("registry, …a message that was not delivered does not count as told: the second run of the date sends it again, and only it", retried == ["alpha-main"] and sorted(rec_b["registry"]["told_earlier_today"]) == ["alpha-builder", "falcon-main"], (retried, rec_b["registry"]))
    rec_clear(); rec = go(f33, env_=rg_env({**RG, "unrouted": True}))
    check("registry, sala's list unreadable (the result is unrouted): nothing is sent even with send on, the findings stay on the record", not [1 for to, t, fy in sent if "Project registry" in t and to != "projects/example"]
          and len(rec["registry"]["findings"]) == 4, rec["registry"])
    from stackshot.tools import registry_report as _rr
    longkey = "projects/" + "very-long-page-key-" * 5 + "end"
    npf = _rr.no_project({}, {longkey: {"type": "project", "title": "Long"}})
    check("registry, the real 'page with no project' finding for a long key (" + str(len(longkey)) + " characters) keeps its --name hint and its closing parenthesis in the message line",
          len(npf) == 1 and f"adopt {longkey}" in AR.par_line(npf[0]) and "--name <name>" in AR.par_line(npf[0]) and AR.par_line(npf[0]).endswith("(409))"), AR.par_line(npf[0]) if npf else npf)
    rec_clear(); rec = go(f33)
    check("registry, no hook handed in: the default reads the store's record (empty here) and is silent, the run is as before", rec["registry"]["checked"] is False and not [1 for to, t, fy in sent if "Project registry" in t], rec["registry"])
finally:
    ROLES.pop("falcon-main", None)
    _cfg.CFG.pop("registry_audit", None)
rec_clear()

# ---- the wait-end pass (wait_end_scenario holds the cases against the server's fix): the pass only acts through env.wait_end
from stackshot.waits import wait_end as _WE
def _gap(op="after"):
    return _WE.Gap("item", 1, "wait for board#" "2", "board#" "2", "ev", {"op": op, "ids": ["g2"], "shown": ["board#" "2"]}, "item:board#" "2|abcdef01")
def _wf(i, mover="home-agent", cat="wait-end", gap=True):
    return {"id": f"board#{i}", "project": "projects/alpha", "owner": mover, "mover": mover, "category": cat, "detail": "d", "fix": "f", "source": "code", **({"gap": _gap()} if gap else {})}
wcalls, wsent = [], []
def _we_ok(gid, plan, now_): wcalls.append((gid, plan)); return {"fixed": True, "what": "after=board#" "2", "why": ""}
def _wdeliver(to, text, fyi=False): wsent.append((to, text, fyi)); return True, "[200] ok"
wenv = lambda **kw: AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=_wdeliver, **kw)
fl = [_wf(1), _wf(2), _wf(3, gap=False), _wf(4, cat="event-missing", gap=False)]
shown_ = {f"board#{i}": f"g{i}" for i in range(1, 5)}
left_, rep_ = AR.wait_end_pass(fl, {}, shown_, now, wenv(wait_end=_we_ok))
check("wait-end pass: a finding with a fix is made through env.wait_end and no longer sent; one with no fix and the builder's message stand", [f["id"] for f in left_] == ["board#" "3", "board#" "4"] and [c[0] for c in wcalls] == ["g1", "g2"] and rep_["fixed"] == ["board#" "1", "board#" "2"], (left_, rep_))
check("wait-end pass: the plan reaches the fix with its token and line", wcalls[0][1]["op"] == "after" and wcalls[0][1]["token"] == "item:board#" "2|abcdef01" and wcalls[0][1]["pos"] == 1, wcalls)
check("wait-end pass: one fyi message names the items fixed, to the mover", len(wsent) == 1 and wsent[0][2] is True and "board#" "1" in wsent[0][1] and "board#" "2" in wsent[0][1], wsent)
check("wait-end pass: the record counts what stands", rep_["asked"] == 1 and rep_["routed"] == 1, rep_)
wcalls.clear(); wsent.clear()
left_, rep_ = AR.wait_end_pass([_wf(1)], {}, shown_, now, wenv())
check("wait-end pass: with no env.wait_end nothing is made and the finding stands", len(left_) == 1 and not wcalls and not wsent and rep_["fixed"] == [], (left_, rep_))
left_, rep_ = AR.wait_end_pass([_wf(i) for i in range(1, 15)], {}, {f"board#{i}": f"g{i}" for i in range(1, 15)}, now, wenv(wait_end=_we_ok))
check("wait-end pass: at most ten fixes a pass", len(rep_["fixed"]) == _WE.FIX_CAP and len(left_) == 4, (len(rep_["fixed"]), len(left_)))
wcalls.clear()
left_, rep_ = AR.wait_end_pass([_wf(1, mover="alpha-main")], {}, shown_, now, wenv(wait_end=_we_ok))
check("wait-end pass: a front agent's item is not fixed (it would get no notice)", len(left_) == 1 and not wcalls, (left_, wcalls))
left_, rep_ = AR.wait_end_pass([_wf(1)], {}, shown_, now, wenv(wait_end=lambda g, p, n: {"fixed": False, "why": "the line changed"}))
check("wait-end pass: a fix the server declines leaves the finding standing", len(left_) == 1 and rep_["fixed"] == [], (left_, rep_))
left_, rep_ = AR.wait_end_pass([_wf(1)], {}, shown_, now, wenv(wait_end=lambda g, p, n: 1 / 0))
check("wait-end pass: a fix that raises is recorded and never stops the pass", len(left_) == 1 and rep_["errors"] and "ZeroDivisionError" in rep_["errors"][0], rep_)
from stackshot.audit import audit_checks as _AC9
check("wait-end: event-missing is sent once (never repeated or escalated)", AR.ONCE == ("event-missing",) and "wait-end" in _AC9.CHECKS_FILING and "event-missing" in _AC9.CHECKS_FILING)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: audit_run scenario, {len(ran)} checks")
