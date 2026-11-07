"""tests/refusal_report_scenario.py — the count of refused board writes, and the small corrections the server makes instead of refusing.

Checked here against a scratch state folder and config (no port, no real server, no message sent, no model call):

  1  call_log: one line per counted call (went through, went through with a correction, refused) in `<state>/calls/<YYYY-MM>.jsonl`; a refusal keeps tool, item, sender and the clipped, folded reason and
     no other argument; an uncounted tool writes nothing; a line that does not parse is skipped on read; the range read takes the month files it spans; kind_of names the refusal kinds and folds the rest
  2  the middleware (server._RefusalLog): a refused write is logged as refused and records no correction; a write that went through with a correction carries one reply line saying what the server
     did and how to keep the field as written, and is logged with the fix kinds; a write with none is logged plain and its reply is as it was
  3  the corrections: a bare item number is read as board#N; a full ISO wake (seconds, a fraction, Z or an offset) is converted to that minute in the instance zone; a subject with no scope prefix
     takes the project's scope prefix (else the fallback); a script's item (`by`) and a subject that already has a prefix are left alone; a field sent again as written is not touched (it is refused as before)
  4  the weekly report (tools/refusal_report.py): the text and its share arithmetic, the week before, the kinds, the senders, the corrections, a late-starting log; sent once per week, not before the
     week is over, not when `enabled` is false, not with no records; --dry-run, --force and --week; the audit.py verb and the audit unit's ExecStartPost

    tests/run-suite refusal_report        → exit 0 / 1"""
import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, subprocess, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="refusalrep-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^fallback_prefix = .*$', 'fallback_prefix = "[home] "', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-front", "team-back")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "scope": "work", "tags": [], "type": "project", "session": "home-front", "status": "active", "board": [], "board_open": 0,
                       "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-front\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
import server, call_log as CL, refusal_report as RR, config as CFG
from fastmcp.exceptions import ToolError
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._front_sender = lambda who: False
CALLS = T / "state/calls"
def lines(month=None):
    out = []
    for p in sorted(CALLS.glob("*.jsonl")) if CALLS.exists() else []:
        if month and p.stem != month: continue
        out += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out
def wipe():
    for p in list(CALLS.glob("*.jsonl")) if CALLS.exists() else []: p.unlink()
zone = CFG.tz()
def epoch(y, m, d, hh=12, mm=0): return dt.datetime(y, m, d, hh, mm, tzinfo=zone).timestamp()

BID = lambda n: "board" + "#" + str(n)                       # an id built in code

# ================================================================ 1. call_log
now = epoch(2026, 11, 3)
CL.record("update", True, now=now)
CL.record("update", True, fixes=[("wake", "x"), ("item-id", "y")], now=now + 1)
CL.record("create", False, item=BID(12), sender="my  x", why="Refused: line one\n  line two " + "w" * 400, now=now + 2)
CL.record("get", True, now=now + 3)                          # not a counted tool
CL.record("update", False, item="a1", sender="s", why="Refused: next no longer lists 3", now=epoch(2026, 12, 1))   # next month
rows = lines()
check("1 call_log: counted calls only, one line each, in the month's file", [r["tool"] for r in rows] == ["update", "update", "create", "update"] and (CALLS / "2026-11.jsonl").exists() and (CALLS / "2026-12.jsonl").exists(), rows)
check("1 call_log: a plain success has t, tool, ok and nothing else", rows[0] == {"t": int(now), "tool": "update", "ok": True}, rows[0])
check("1 call_log: …a corrected one lists the fix kinds, not the notes", rows[1].get("fix") == ["wake", "item-id"] and "x" not in json.dumps(rows[1].get("why", "")), rows[1])
check("1 call_log: …a refusal keeps item, sender and the reason folded to one line and clipped, and nothing of the call's other arguments",
      rows[2]["ok"] is False and rows[2]["item"] == BID(12) and rows[2]["sender"] == "my x" and "\n" not in rows[2]["why"] and len(rows[2]["why"]) <= CL.WHY_MAX and rows[2]["why"].endswith("…")
      and set(rows[2]) == {"t", "tool", "ok", "item", "sender", "why"}, rows[2])
(CALLS / "2026-11.jsonl").write_text((CALLS / "2026-11.jsonl").read_text(encoding="utf-8") + "not json\n{\"t\": \"x\"}\n[1]\n", encoding="utf-8")
got = list(CL.read(epoch(2026, 11, 1, 0), epoch(2026, 12, 31)))
check("1 call_log: read spans the month files, skips a line that does not parse and one with no time", len(got) == 4, got)
got = list(CL.read(now + 1, now + 3))
check("1 call_log: read is since <= t < until", [r["t"] for r in got] == [int(now + 1), int(now + 2)], got)
kinds = {
    "Refused: next no longer lists 'step one' — mark it done or dropped": "a step left out of next with no done or dropped",
    "Refused: description bullet is 190 characters, the limit is 120": "a description bullet over its limit",
    "Refused: the subject is 91 characters and the limit is 80": "a subject over its limit",
    "Refused: subject must start with one of ['[work] '] — got 'x'": "a subject without a scope prefix",
    "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) — got 'x'": "a wake in the wrong form",
    "bad item id '12' — ids read board#<n>": "an item id in the wrong form",
    "Refused: ask must read as a question": "an ask in the wrong form",
}
for why, want in kinds.items():
    check(f"1 kind_of: {want}", CL.kind_of(why) == want, CL.kind_of(why))
check("1 kind_of: an unknown refusal is folded: ids and numbers become N/ID, cut to 70 characters", CL.kind_of(f"Refused: {BID(123)} has 45 odd things " + "z" * 90) == (f"{BID(123)} has 45 odd things ".replace(BID(123), "ID").replace("45", "N") + "z" * 90)[:70].rstrip()
      or CL.kind_of(f"Refused: {BID(123)} has 45 odd things " + "z" * 90).startswith("ID has N odd things"), CL.kind_of(f"Refused: {BID(123)} has 45 odd things " + "z" * 90))
wipe()

# ================================================================ 2. the middleware
def run_mw(name, args, call):
    async def nxt(ctx): return call()
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name=name, arguments=args))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: out = asyncio.run(server._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: out = e
    return out, buf.getvalue()
def reply(text): return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], structured_content={"result": text})
def fixing():
    CL.fixed("wake", "wake 2026-11-09T08:00:00Z read as 2026-11-09T12:00 +04")
    CL.fixed("wake", "again")                                      # a kind is reported once
    CL.fixed("item-id", f"item 12 read as {BID(12)}")
    return reply(f"updated {BID(12)}")
out, err = run_mw("update", {"item_id": "12", "sender": "team-back"}, fixing)
note = out.content[0].text.split(f"updated {BID(12)}", 1)[1]
check("2 middleware: a write that went through with corrections carries one reply line naming each once and how to keep a field as written",
      note.startswith(f"\n(fixed for you: wake 2026-11-09T08:00:00Z read as 2026-11-09T12:00 +04; item 12 read as {BID(12)}.") and "send it again as you want it" in note and note.count("fixed for you") == 1 and "; again" not in note, note)
check("2 middleware: …the structured result carries the same line, and nothing goes to stderr", out.structured_content["result"] == out.content[0].text and err == "", (out.structured_content, err))
r = lines()
check("2 middleware: …and the call is logged ok with the fix kinds, once each", len(r) == 1 and r[0]["ok"] is True and r[0]["fix"] == ["wake", "item-id"], r)
out, err = run_mw("update", {"item_id": "12", "sender": "team-back"}, lambda: reply(f"updated {BID(12)}"))
r = lines()
check("2 middleware: a write with no correction is logged plain and its reply is as the tool made it", out.content[0].text == f"updated {BID(12)}" and len(r) == 2 and r[1] == {"t": r[1]["t"], "tool": "update", "ok": True}, (out.content[0].text, r))
def refusing():
    CL.fixed("wake", "a correction made before the refusal")
    raise ToolError("Refused: next no longer lists 'a step'")
out, err = run_mw("update", {"item_id": BID(7), "sender": "team-back", "description": "SECRET-DESCRIPTION"}, refusing)
r = lines()
check("2 middleware: a refused write is logged refused with item, sender and reason, no fix, no other argument; the refusal reaches the caller unchanged",
      isinstance(out, ToolError) and str(out).startswith("Refused: next no longer lists") and r[2]["ok"] is False and r[2]["item"] == BID(7) and r[2]["sender"] == "team-back" and "fix" not in r[2]
      and "SECRET" not in json.dumps(r[2]) and err.startswith(f"refused: update item={BID(7)} sender=team-back: "), (out, r[2:], err))
out, err = run_mw("get", {"item_id": BID(7)}, lambda: reply("an item"))
check("2 middleware: an uncounted tool (get) is not logged", len(lines()) == 3 and out.content[0].text == "an item", lines())
wipe()

# ================================================================ 3. the corrections
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": time.time(), "state_updated": time.time(),
                                                       "confirmed": time.time(), "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
def collect(fn):
    tok = CL.begin()
    try: res = fn()
    finally: fixes = CL.end(tok)
    return res, fixes
# a bare number: read for get, update and confirm (the item a call is about); a bad id anywhere else (complete, after, items)
(T / "store/g").mkdir(exist_ok=True)
(T / "store/g/5.json").write_text(json.dumps({"id": "5", "subject": "[home] item five", "description": DESC, "status": "open", "updated": time.time(), "state_updated": time.time(), "confirmed": 1.0,
                                              "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}}))
g, fx = collect(lambda: server._norm_id("12", bare=True))
check("3 id: a bare number is read as board#N where the call is about the item, and the correction is noted", g == server._norm_id(BID(12)) and [k for k, _ in fx] == ["item-id"] and BID(12) in fx[0][1], (g, fx))
g, fx = collect(lambda: server._norm_id(BID(12), bare=True))
check("3 id: …the shown form passes with no note", fx == [] and g == server._norm_id(BID(12)), fx)
for given in ("12", "\u00b2", "\u0663", "1 2", ""):
    for bare in (False, True):
        try: server._norm_id(given, bare=bare); bad = ""
        except ToolError as e: bad = str(e)
        except Exception as e: bad = f"CRASH {type(e).__name__}"          # int('\u00b2') raises ValueError
        want_bad = not (bare and given == "12")
        check(f"3 id: {given!r} bare={bare} is {'a bad id' if want_bad else 'read'}", bad.startswith("bad item id") if want_bad else bad == "", bad)
rd5 = lambda: json.loads((T / "store/g/5.json").read_text())
try: server.stackshot_complete("5", outcome="done", reason="because", sender="team-back"); cref = ""
except ToolError as e: cref = str(e)
check("3 id: complete refuses a bare number (a close is not undone by a resend), and the item stays open", cref.startswith("bad item id '5'") and rd5()["status"] == "open", (cref, rd5()["status"]))
tok = CL.begin()
try: server.stackshot_confirm("5", sender="team-back")
finally: fx = CL.end(tok)
check("3 id: confirm reads a bare number, and says so", rd5()["confirmed"] > 1.0 and [k for k, _ in fx] == ["item-id"], (rd5()["confirmed"], fx))
tok = CL.begin()
try: got = server.stackshot_get("5")
finally: fx = CL.end(tok)
check("3 id: get reads a bare number, and says so", "item five" in got and [k for k, _ in fx] == ["item-id"], (got[:80], fx))
try: server.stackshot_update("5", status="completed", outcome="done", reason="because it is done", sender="team-back", outcome_text="- done"); uref = ""
except ToolError as e: uref = str(e)
check("3 id: update with status=completed refuses a bare number as complete does, and the item stays open", uref.startswith("bad item id '5'") and rd5()["status"] == "open", (uref, rd5()["status"]))
tok = CL.begin()
try: out_ = server.stackshot_update("5", sender="team-back", priority="p3")
finally: fx = CL.end(tok)
check("3 id: …while a note-only update of the same bare number lands, with the fix noted", rd5()["metadata"].get("priority") == "p3" and rd5()["status"] == "open" and "item-id" in [k for k, _ in fx], (rd5()["metadata"], fx))
tok = CL.begin()
try: server._update("5", sender="team-back", priority="p2")
finally: fx = CL.end(tok)
check("3 id: update reads a bare number, and says so", rd5()["metadata"].get("priority") == "p2" and "item-id" in [k for k, _ in fx], (rd5()["metadata"], fx))
# the wake
iso = lambda s: server._parse_wake(s)
day = (dt.datetime.now(zone) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
cases = (
    (f"{day}T08:00:30", f"{day}T08:00"),                         # seconds, no offset: the instance's own time
    (f"{day}T08:00:00.250", f"{day}T08:00"),
    (f"{day}T08:00:00+04:00", f"{day}T08:00"),
    (f"{day}T08:00:00+0400", f"{day}T08:00"),
    (f"{day}T08:00+04", f"{day}T08:00"),
    (f"{day}T04:00:00Z", f"{day}T08:00"),
    (f"{day}T23:30:00-05:00", (dt.datetime.strptime(day, "%Y-%m-%d") + dt.timedelta(days=1)).strftime("%Y-%m-%d") + "T08:30"),
)
for given, want in cases:
    got, fx = collect(lambda g_=given: iso(g_))
    check(f"3 wake: {given} → {want} and the correction is noted", got == want and [k for k, _ in fx] == ["wake"] and want in fx[0][1], (got, fx))
for plain in (day, f"{day}T08:00", f"{day} 08:00"):
    got, fx = collect(lambda p=plain: iso(p))
    check(f"3 wake: {plain!r} is the plain form: no correction", fx == [] and got in (day, f"{day}T08:00"), (got, fx))
for badw in (f"{day}T24:00", f"{day}T12", f"{day}T12:00+25:00", f"{day}T12:00:61Q", "2026/12/01", "next tuesday"):
    try: iso(badw); msg = ""
    except ToolError as e: msg = str(e)
    check(f"3 wake: {badw!r} is refused naming the two forms", msg.startswith("Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM"), msg)
# the subject prefix
def create(subject, **kw):
    return server._create_item(subject=subject, description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: begin", mover="team-back", **kw)
(g1, out1), fx = collect(lambda: create("Check the nightly job"))
it = json.loads((T / "store" / g1[0] / f"{g1[1:]}.json").read_text())
check("3 subject: a subject with no scope prefix takes the project's scope prefix and the correction is noted", it["subject"] == "[work] Check the nightly job" and [k for k, _ in fx] == ["subject-prefix"] and "[work]" in fx[0][1], (it["subject"], fx))
(g2, _o), fx = collect(lambda: create("[home] Already scoped"))
it = json.loads((T / "store" / g2[0] / f"{g2[1:]}.json").read_text())
check("3 subject: …a subject that has a prefix is left as written, even another scope's", it["subject"] == "[home] Already scoped" and fx == [], (it["subject"], fx))
try: create("Filed by a script", by="a watcher (a script on box-a)"); sref = ""
except ToolError as e: sref = str(e)
check("3 subject: …a script's own item with no prefix is refused as before", sref.startswith("Refused: subject must start with"), sref)
for tagged in ("[Work] Fix X", "[work]Fix X", " [work] Fix X", "work: Fix X", "[Home] x", "[other] x", "\u200b[work] x", "\ufeff[work] x"):
    try: create(tagged); tref = ""
    except ToolError as e: tref = str(e)
    check(f"3 subject: {tagged!r} already opens with a tag: refused with the prefix list named, never stacked", tref.startswith("Refused: subject must start with one of ['[work] ', '[home] ']"), tref)
try: server._create_item(subject="No project to name a scope", description=DESC, project="projects/no-such", owner=U["home-front"], next="team-back: begin", mover="team-back"); nref = ""
except ToolError as e: nref = str(e)
check("3 subject: …a project that names no record gets no guess: refused as before", "subject must start with" in nref or "project" in nref, nref)
wipe()

# ================================================================ 4. the weekly report
mon = dt.date(2026, 11, 2)                                    # a Monday
prev_mon = mon - dt.timedelta(days=7)
def add(tool, ok, n, day_, why="", sender="team-back", fixes=None, hour=10):
    for i in range(n):
        CL.record(tool, ok, item=BID(1), sender=sender, why=why, fixes=fixes, now=epoch(day_.year, day_.month, day_.day, hour, i % 60))
def week_data():
    wipe()
    add("update", True, 70, mon); add("create", True, 10, mon + dt.timedelta(days=2))
    add("update", False, 12, mon + dt.timedelta(days=1), "Refused: next no longer lists 'a step'", sender="team-back")
    add("update", False, 5, mon + dt.timedelta(days=1), "Refused: description bullet is 190 characters, the limit is 120", sender="home-front")
    add("create", False, 3, mon + dt.timedelta(days=3), "Refused: some rare new thing 77", sender="team-back")
    add("update", True, 4, mon + dt.timedelta(days=4), fixes=[("wake", "w")]); add("update", True, 2, mon + dt.timedelta(days=4), fixes=[("item-id", "i"), ("wake", "w")])
    add("complete", False, 2, mon + dt.timedelta(days=4), "Refused: x", sender="home-front")
    add("update", True, 40, prev_mon + dt.timedelta(days=1)); add("update", False, 10, prev_mon + dt.timedelta(days=1), "Refused: next no longer lists 'a'")
    add("update", True, 3, mon - dt.timedelta(days=1), hour=23)                      # Sunday before: the previous week
    add("update", True, 1, mon + dt.timedelta(days=7), hour=0)                       # the next Monday: not in the week
week_data()
cur, prev = RR.collect(mon)
check("4 tally: create and update calls, refused, and corrections of the week", RR._headline(cur) == (20, 70 + 10 + 20 + 6) and cur["refused"].get("complete") == 2 and sum(cur["fixes"].values()) == 8, (RR._headline(cur), cur["refused"], cur["fixes"]))
check("4 tally: …the week before is its own Monday-to-Sunday window", RR._headline(prev) == (10, 50 + 3), RR._headline(prev))
text = RR.build(mon, cur, prev, top=2)
check("4 report: headline with the share and the week before", "Refused board writes, Mon Nov 2nd to Sun Nov 8th (+04):" in text and "create and update: 20 of 106 calls refused (18.9%); the week before 10 of 53 (18.9%)" in text, text)
check("4 report: the kinds with counts and shares, the top N then the rest", "a step left out of next with no done or dropped 12 (60%)" in text and "a description bullet over its limit 5 (25%)" in text and "3 in other kinds" in text, text)
check("4 report: the senders refused most, the other writes refused, the corrections by kind",
      "refused most: team-back 15 · home-front 5" in text and "other writes refused: complete 2 of 2" in text and "corrected by the server instead of refused: 8 (wake 6 · item-id 2)" in text, text)
check("4 report: a log that starts on time has no late-start line", "call log starts" not in text, text)
wipe(); add("update", True, 10, mon + dt.timedelta(days=3)); add("update", False, 1, mon + dt.timedelta(days=3), "Refused: next no longer lists 'a'")
c2, p2 = RR.collect(mon)
t2 = RR.build(mon, c2, p2)
check("4 report: a log that starts late says so, and no week before says so", "the call log starts Thu Nov 5th" in t2 and "no records for the week before" in t2, t2)
wipe(); add("update", True, 10, mon + dt.timedelta(days=1))
c3, p3 = RR.collect(mon)
t3 = RR.build(mon, c3, p3)
check("4 report: a week with nothing refused reads 0 and lists no kinds", "0 of 10 calls refused (0.0%)" in t3 and "kinds of" not in t3, t3)

# the run: once per week, gated
week_data()
sent = []
def deliver(to, text_, sender): sent.append((to, text_, sender)); return True, "[200] ok"
state = T / "state/refusal-report/sent.json"
after = epoch(2026, 11, 9, 5)                                  # Monday after: the week is over
cfg_on = {"enabled": True, "to": "my-x", "top": 6, "sender": "stackshot refusal report"}
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=state)
check("4 run: the finished week is sent once to the configured session, as the configured sender", res["sent"] and len(sent) == 1 and sent[0][0] == "my-x" and sent[0][2] == "stackshot refusal report"
      and "20 of 106 calls refused" in sent[0][1] and res["week"] == mon, (res, sent))
res = RR.run(now=after + 3600, cfg=cfg_on, deliver=deliver, state=state)
check("4 run: …and not again (the audit timer runs twice a day)", not res["sent"] and res["why"] == "already sent" and len(sent) == 1, res)
res = RR.run(now=after + 3600, cfg=cfg_on, deliver=deliver, state=state, force=True)
check("4 run: --force sends the week again", res["sent"] and len(sent) == 2, res)
fresh = lambda n: T / f"state/refusal-report/{n}.json"
res = RR.run(now=epoch(2026, 11, 5), cfg=cfg_on, deliver=deliver, state=fresh("early"))
check("4 run: asked on a Thursday it reports the last finished week (the one that began Mon Oct 26th), not the running one", res["week"] == prev_mon and res["sent"], res)
res = RR.run(now=after, cfg=dict(cfg_on, enabled=False), deliver=deliver, state=fresh("off"))
check("4 run: enabled = false sends nothing and marks nothing, and says so", not res["sent"] and res["why"].startswith("not enabled") and len(sent) == 3 and not fresh("off").exists() and res["text"], res)
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=fresh("dry"), dry=True)
check("4 run: --dry-run returns the text and sends nothing, marks nothing (also while enabled)", not res["sent"] and res["why"] == "dry run" and res["text"] and len(sent) == 3 and not fresh("dry").exists(), res)
res = RR.run(now=after, cfg=cfg_on, deliver=lambda *a: (False, "[500] down"), state=fresh("down"))
check("4 run: a send that fails is not marked sent (the next run tries again)", not res["sent"] and not fresh("down").exists(), res)
blocked = T / "state/refusal-report/blocked"; blocked.write_text("a file where a folder should be")
n_before = len(sent)
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=blocked / "sent.json")
check("4 run: a record that cannot be written is reported as 'sent but not recorded', not raised", res["sent"] and len(sent) == n_before + 1 and "but not recorded" in res["why"], res)
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=fresh("weeks"), week=mon - dt.timedelta(days=28))
check("4 run: --week for a week with no records sends nothing", not res["sent"] and res["why"] == "no call records for the week", res)
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=fresh("weeks"), week=mon + dt.timedelta(days=1))
check("4 run: --week must be a Monday", not res["sent"] and "not a Monday" in res["why"], res)
res = RR.run(now=after, cfg=cfg_on, deliver=deliver, state=fresh("weeks"), week=prev_mon)
check("4 run: --week reports that week (and the week before it has no records, which the report says)", res["sent"] and res["week"] == prev_mon and "Mon Oct 26th to Sun Nov 1st" in sent[-1][1], (res, sent[-1][1][:120]))
check("4 settings: defaults read from the config ([refusal_report] absent: not enabled, six kinds)", RR.settings()["enabled"] is False and RR.settings()["top"] == 6 and RR.settings()["sender"] == "stackshot refusal report", RR.settings())

# the command line and the audit verb, in a child process with the scratch config (a dry run: no message is sent)
env = dict(os.environ, STACKSHOT_CONFIG=f"{tmp}/stackshot.toml")
def cli(*argv):
    p = subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env, cwd=STACK, timeout=120)
    return p.returncode, p.stdout + p.stderr
rc, out = cli(os.path.join(STACK, "tools/refusal_report.py"), "run", "--dry-run", "--week", mon.isoformat())
check("4 cli: refusal_report.py run --dry-run --week prints the report and exits 0", rc == 0 and "create and update: 20 of 106 calls refused" in out and "refusal report: dry run" in out, (rc, out[-400:]))
rc, out = cli(os.path.join(STACK, "audit.py"), "refusals", "--dry-run", "--week", mon.isoformat())
check("4 cli: audit.py refusals is the same report", rc == 0 and "create and update: 20 of 106 calls refused" in out, (rc, out[-400:]))
rc, out = cli(os.path.join(STACK, "tools/refusal_report.py"), "run", "--week", "not-a-date")
check("4 cli: a bad --week exits 2 naming the form", rc == 2 and "YYYY-MM-DD" in out, (rc, out))
rc, out = cli(os.path.join(STACK, "tools/refusal_report.py"), "run", "--bogus")
check("4 cli: an unknown option prints the usage and exits 2", rc == 2 and "usage: refusal_report.py" in out, (rc, out))
unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8").splitlines()
post = [l for l in unit if l.startswith("ExecStartPost=") and "audit.py refusals" in l]
check("4 unit: the audit unit runs the report after the audit run, with a timeout and a leading '-' so a failure never fails the audit", len(post) == 1 and post[0].startswith("ExecStartPost=-/usr/bin/timeout ")
      and [i for i, l in enumerate(unit) if l.startswith("ExecStart=")][0] < unit.index(post[0]), post)
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("4 example: the example config has a [refusal_report] section, off", re.search(r"(?m)^\[refusal_report\][^\n]*\nenabled = false", ex) is not None, ex[ex.find("[refusal_report]"):][:300])
readme = pathlib.Path(STACK, "README.md").read_text(encoding="utf-8")
check("4 readme: the report and the corrections are documented, and so are the config keys", "refused board writes" in readme.lower() and all(f"`refusal_report.{k}`" in readme for k in ("enabled", "to", "top", "sender")), None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
