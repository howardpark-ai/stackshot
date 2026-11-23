"""tests/refusal_report_scenario.py — the count of refused board writes, and the small corrections the server makes instead of refusing.

Checked here against a scratch state folder and config (no port, no real server, no message sent, no model call):

  1  call_log: one line per counted call (went through, went through with a correction, refused) in `<state>/calls/<YYYY-MM>.jsonl`; a refusal keeps tool, item, sender and the clipped, folded reason and
     no other argument; an uncounted tool writes nothing; a line that does not parse is skipped on read; the range read takes the month files it spans; kind_of names the refusal kinds and folds the rest
  2  the middleware (web/middleware.py _RefusalLog, run as _wmw._RefusalLog): a refused write is logged as refused and records no correction; a write that went through with a correction carries one reply line saying what the server
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.core import call_log as CL; from stackshot.tools import refusal_report as RR; from stackshot.core import config as CFG; from stackshot.model import ids as _model_ids; from stackshot.service import create as create_svc
from stackshot.service import update as _update_svc
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc
from stackshot.web import middleware as _wmw
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from fastmcp.exceptions import ToolError
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.front_sender = lambda who: False
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
    # the self-wait refusal names wait_basis as the other way to park, and its own kind comes first
    'Refused: a wait on your own item needs its reason: this write sets a wake 2099-03-02, and a wait that names no blocker is how ready work sits idle until its date. Pass wait_reason=<what the step waits on> with the same call. To wait, send the same call again: wake="2099-03-02", wait_reason="<what the step waits on that is not available now>". A wait that stands on a date outside the work is a park instead: hold=true, until="YYYY-MM-DD" and wait_basis="<what happens> YYYY-MM-DD".': "a wait set without its reason",
    'Refused: wait_basis must name the real-world date the wait stands on as a real YYYY-MM-DD': "a wait_basis the rule does not take",
    # the hand-off refusal (service/update.py) names the sessions handed to and quotes `<session>: <action>`: it is not a front agent's
    f"Refused: this update hands {BID(7)} to worker-a (a line of next in the form `<session>: <action>`) and nothing would close the item once that work is done. Add check=<what closes it>": "a hand-off with no check or date",
    f"Refused: this update hands {BID(7)} to worker-a, worker-b (a line of next in the form `<session>: <action>`) and nothing would close the item": "a hand-off with no check or date",
    # the refusals that do name a front agent keep their kind
    f"Refused: demo-main is a user-facing agent of projects/demo, and mover=demo-main from another session hands it an item it gets no notice of": "a front agent named as mover",
    "Refused: a name is not a background agent of any project, nor this project's keeper; needs names one of those": "a front agent named as mover",
    'Refused: the step "demo-main: ask" opens with demo-main, a user-facing agent of projects/demo: it gets no work notice': "a front agent named as mover",
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
        try: out = asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
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
g, fx = collect(lambda: _model_ids._norm_id("12", bare=True))
check("3 id: a bare number is read as board#N where the call is about the item, and the correction is noted", g == _model_ids._norm_id(BID(12)) and [k for k, _ in fx] == ["item-id"] and BID(12) in fx[0][1], (g, fx))
g, fx = collect(lambda: _model_ids._norm_id(BID(12), bare=True))
check("3 id: …the shown form passes with no note", fx == [] and g == _model_ids._norm_id(BID(12)), fx)
for given in ("12", "\u00b2", "\u0663", "1 2", ""):
    for bare in (False, True):
        try: _model_ids._norm_id(given, bare=bare); bad = ""
        except ToolError as e: bad = str(e)
        except Exception as e: bad = f"CRASH {type(e).__name__}"          # int('\u00b2') raises ValueError
        want_bad = not (bare and given == "12")
        check(f"3 id: {given!r} bare={bare} is {'a bad id' if want_bad else 'read'}", bad.startswith("bad item id") if want_bad else bad == "", bad)
rd5 = lambda: json.loads((T / "store/g/5.json").read_text())
try: _wt_complete.stackshot_complete("5", outcome="done", reason="because", sender="team-back"); cref = ""
except ToolError as e: cref = str(e)
check("3 id: complete refuses a bare number (a close is not undone by a resend), and the item stays open", cref.startswith("bad item id '5'") and rd5()["status"] == "open", (cref, rd5()["status"]))
tok = CL.begin()
try: _wt_complete.stackshot_confirm("5", sender="team-back")
finally: fx = CL.end(tok)
check("3 id: confirm reads a bare number, and says so", rd5()["confirmed"] > 1.0 and [k for k, _ in fx] == ["item-id"], (rd5()["confirmed"], fx))
tok = CL.begin()
try: got = _wt_get.stackshot_get("5")
finally: fx = CL.end(tok)
check("3 id: get reads a bare number, and says so", "item five" in got and [k for k, _ in fx] == ["item-id"], (got[:80], fx))
try: _wt_update.stackshot_update("5", status="completed", outcome="done", reason="because it is done", sender="team-back", outcome_text="- done"); uref = ""
except ToolError as e: uref = str(e)
check("3 id: update with status=completed refuses a bare number as complete does, and the item stays open", uref.startswith("bad item id '5'") and rd5()["status"] == "open", (uref, rd5()["status"]))
tok = CL.begin()
try: out_ = _wt_update.stackshot_update("5", sender="team-back", priority="p3")
finally: fx = CL.end(tok)
check("3 id: …while a note-only update of the same bare number lands, with the fix noted", rd5()["metadata"].get("priority") == "p3" and rd5()["status"] == "open" and "item-id" in [k for k, _ in fx], (rd5()["metadata"], fx))
tok = CL.begin()
try: _update_svc._update("5", sender="team-back", priority="p2")
finally: fx = CL.end(tok)
check("3 id: update reads a bare number, and says so", rd5()["metadata"].get("priority") == "p2" and "item-id" in [k for k, _ in fx], (rd5()["metadata"], fx))
# the wake
iso = lambda s: wakes_svc.parse_wake(s)
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
    return create_svc.create_item(subject=subject, description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: begin", mover="team-back", **kw)
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
try: create_svc.create_item(subject="No project to name a scope", description=DESC, project="projects/no-such", owner=U["home-front"], next="team-back: begin", mover="team-back"); nref = ""
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
rc, out = cli(os.path.join(STACK, "stackshot/tools/refusal_report.py"), "run", "--dry-run", "--week", mon.isoformat())
check("4 cli: refusal_report.py run --dry-run --week prints the report and exits 0", rc == 0 and "create and update: 20 of 106 calls refused" in out and "refusal report: dry run" in out, (rc, out[-400:]))
rc, out = cli(os.path.join(STACK, "stackshot/audit/audit.py"), "refusals", "--dry-run", "--week", mon.isoformat())
check("4 cli: audit.py refusals is the same report", rc == 0 and "create and update: 20 of 106 calls refused" in out, (rc, out[-400:]))
rc, out = cli(os.path.join(STACK, "stackshot/tools/refusal_report.py"), "run", "--week", "not-a-date")
check("4 cli: a bad --week exits 2 naming the form", rc == 2 and "YYYY-MM-DD" in out, (rc, out))
rc, out = cli(os.path.join(STACK, "stackshot/tools/refusal_report.py"), "run", "--bogus")
check("4 cli: an unknown option prints the usage and exits 2", rc == 2 and "usage: refusal_report.py" in out, (rc, out))
unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8").splitlines()
post = [l for l in unit if l.startswith("ExecStartPost=") and "stackshot audit refusals" in l]
check("4 unit: the audit unit runs the report after the audit run, with a timeout and a leading '-' so a failure never fails the audit", len(post) == 1 and post[0].startswith("ExecStartPost=-/usr/bin/timeout ")
      and [i for i, l in enumerate(unit) if l.startswith("ExecStart=")][0] < unit.index(post[0]), post)
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("4 example: the example config has a [refusal_report] section, off", re.search(r"(?m)^\[refusal_report\][^\n]*\nenabled = false", ex) is not None, ex[ex.find("[refusal_report]"):][:300])
import _docs
readme = _docs.page("configuration")
check("4 docs: the report and the corrections are documented, and so are the config keys", "refused board writes" in _docs.page("audit").lower() and all(f"`refusal_report.{k}`" in readme for k in ("enabled", "to", "top", "sender")), None)

# ================================================================ 5. bounce-backs: the writer undoes or redoes a fix the server made
wipe()
for f in CALLS.glob("open-fixes.json"): f.unlink()
H = CL._h
d_wake = {"fields": ["wake", "until"], "stored": H("2026-11-09T12:00"), "sent": H("2026-11-09T08:00:00Z")}
d_subj = {"fields": ["subject"], "stored": H("[home] Fix the thing")}
d_desc = {"fields": ["description"], "stored": H("- one\n- two")}
check("5 undone: a wake written again with another value is a bounce-back; the stored value, or the first form sent, is not",
      CL.undone("wake", d_wake, {"wake": "2026-11-12"}) and CL.undone("wake", d_wake, {"until": "2026-11-12"}) and not CL.undone("wake", d_wake, {"wake": "2026-11-09T12:00"}) and not CL.undone("wake", d_wake, {"wake": "2026-11-09T08:00:00Z"})
      and not CL.undone("wake", d_wake, {"next": "x"}) and not CL.undone("wake", d_wake, {"wake": "  "}), None)
check("5 undone: a subject or a description written again with other words is one; the stored text (spacing aside) is not",
      CL.undone("subject-prefix", d_subj, {"subject": "[home] Fix another thing"}) and not CL.undone("subject-prefix", d_subj, {"subject": "[home]  Fix the thing"})
      and CL.undone("description-bullet", d_desc, {"description": "- one\n- three"}) and not CL.undone("description-bullet", d_desc, {"description": "- one\n- two"}) and not CL.undone("description-bullet", d_desc, {"priority": "p2"}), None)
check("5 undone: a park the server made is undone by clear_hold, clear_wake or another wake; a wait reason by a wait_basis of its own or a clear",
      CL.undone("wake_park", {"stored": H("2026-11-09")}, {"clear_hold": True}) and CL.undone("wake_park", {"stored": H("2026-11-09")}, {"clear_wake": True}) and CL.undone("wake_park", {"stored": H("2026-11-09")}, {"wake": "2026-11-10"})
      and not CL.undone("wake_park", {"stored": H("2026-11-09")}, {"wake": "2026-11-09"}) and not CL.undone("wake_park", {"stored": H("2026-11-09")}, {"next": "x"})
      and CL.undone("wait_reason", {"stored": H("2026-11-09")}, {"wait_basis": "my own words"}) and CL.undone("wait_reason", {"stored": H("2026-11-09")}, {"clear_hold": True}) and not CL.undone("wait_reason", {"stored": H("2026-11-09")}, {"next": "x"}), None)
check("5 undone: a front agent named again in the field the server substituted is a bounce-back; another value or field is not",
      CL.undone("front_mover", {"fields": ["mover"], "stored": H("demo-main")}, {"mover": "Demo-Main"}) and not CL.undone("front_mover", {"fields": ["mover"], "stored": H("demo-main")}, {"mover": "demo-builder"})
      and not CL.undone("front_mover", {"fields": ["mover"], "stored": H("demo-main")}, {"then": "demo-main"}), None)
check("5 undone: item-id, step-none and settled_pick have no check (nothing a later write sends can tell), and are never kept open", all(k not in CL.CHECKED for k in ("item-id", "step-none", "settled_pick", "wait_end")) and not CL.undone("item-id", {}, {"item_id": "x"}), CL.CHECKED)

def wake_fix():
    CL.fixed("wake", "wake 2026-11-09T08:00:00Z read as 2026-11-09T12:00 +04", fields=["wake", "until"], stored="2026-11-09T12:00", sent="2026-11-09T08:00:00Z")
    CL.fixed("item-id", "item 12 read as " + BID(12))
    return reply("updated " + BID(12))
out, err = run_mw("update", {"item_id": BID(12), "sender": "team-back", "wake": "2026-11-09T08:00:00Z"}, wake_fix)
out, err = run_mw("update", {"item_id": BID(12), "sender": "other-back", "wake": "2026-11-20"}, lambda: reply("updated " + BID(12)))
out, err = run_mw("update", {"item_id": BID(13), "sender": "team-back", "wake": "2026-11-20"}, lambda: reply("updated " + BID(13)))
out, err = run_mw("update", {"item_id": BID(12), "sender": "team-back", "next": "team-back: go on"}, lambda: reply("updated " + BID(12)))
r = lines()
check("5 middleware: a later write by another writer, on another item, or that leaves the field alone is no bounce-back", len(r) == 4 and all("bounce" not in x for x in r[1:]), r)
out, err = run_mw("update", {"item_id": "12", "sender": "team-back", "wake": "2026-11-12"}, lambda: reply("updated " + BID(12)))
r = lines()
check("5 middleware: the same writer writing the corrected wake again with another value, on the same item, is logged as a bounce-back of the wake fix (the item written as 12 or in full)", r[-1].get("bounce") == ["wake"] and "fix" not in r[-1], r[-1])
check("5 middleware: …the reply is as the tool made it (a bounce-back adds no line), and the fix is closed: a second write is not counted again", out.content[0].text == "updated " + BID(12), out.content[0].text)
out, err = run_mw("update", {"item_id": BID(12), "sender": "team-back", "wake": "2026-11-14"}, lambda: reply("updated " + BID(12)))
check("5 middleware: …closed means once", "bounce" not in lines()[-1], lines()[-1])
t0 = 1_700_000_000
CL.remember("g1", "s", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=t0)
check("5 window: a write inside the window is asked, one after it is not", CL.bounces("g1", "s", {"wake": "b"}, now=t0 + CL.OPEN_WINDOW + 1) == [] and CL.bounces("g1", "s", {"wake": "b"}, now=t0 + 5) == ["wake"], None)
CL.remember("g2", "s", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=t0)
check("5 window: …inside it, a bounce-back is found", CL.bounces("g2", "s", {"wake": "b"}, now=t0 + 5) == ["wake"], None)
CL.remember("g3", "s", {"item-id": {"x": 1}}, now=t0)
check("5 window: a fix with no check is not kept", not any(k.startswith("g3|") for k in CL._read_open()), CL._read_open())
def two_fixes():
    CL.fixed("description-bullet", "a bullet split", fields=["description"], stored="- a\n- b")
    CL.fixed("subject-prefix", "prefix put", fields=["subject"], stored="[home] x")
    return reply("created " + BID(40) + " — it is being published")
out, err = run_mw("create", {"subject": "x", "sender": "team-back"}, two_fixes)
out, err = run_mw("update", {"item_id": BID(40), "sender": "team-back", "subject": "[home] y", "description": "- a\n- b"}, lambda: reply("updated " + BID(40)))
check("5 middleware: a create's fixes are kept open under the id its reply names, and one later write can bounce more than one", lines()[-1].get("bounce") == ["subject-prefix"], lines()[-1])

# the report counts both: fixes with the bounce-backs of each kind, and the share
wipe()
add("update", True, 30, mon + dt.timedelta(days=1)); add("create", True, 10, mon + dt.timedelta(days=1))
add("update", True, 6, mon + dt.timedelta(days=2), fixes=[("wake", "w")]); add("update", True, 4, mon + dt.timedelta(days=2), fixes=[("description-bullet", "d")])
CL.record("update", True, fixes=[(CL.BOUNCE + "wake", "")], now=epoch(2026, 11, 4, 11))
CL.record("update", True, fixes=[(CL.BOUNCE + "wake", ""), (CL.BOUNCE + "description-bullet", "")], now=epoch(2026, 11, 4, 12))
add("update", False, 5, mon + dt.timedelta(days=3), "Refused: next no longer lists 'a'")
rows5 = lines()
check("5 call_log: a bounce-back is a row field of its own, apart from the fixes", [x for x in rows5 if x.get("bounce")][0]["bounce"] == ["wake"] and "fix" not in [x for x in rows5 if x.get("bounce")][0], [x for x in rows5 if x.get("bounce")])
c5, p5 = RR.collect(mon)
t5 = RR.build(mon, c5, p5)
check("5 report: the fixes the writer sent back, of the fixes checked, with the share and the kinds", "- fixes the writer sent back: 3 of the 10 fixes checked (30.0%) (wake 2 of 6 · description-bullet 1 of 4)" in t5, t5)
check("5 report: …the refusal share is still the first line, apart from it", "create and update: 5 of 57 calls refused (8.8%)" in t5 and "corrected by the server instead of refused: 10 (wake 6 · description-bullet 4)" in t5, t5)
# only the fixes of a kind with a send-back check are in the share: a fix with none (item-id, step-kept, step-none) can never be sent back, so it stays out of the denominator, the corrected line still counts it
wipe()
add("update", True, 1, mon + dt.timedelta(days=1), fixes=[("wake", "w")]); add("update", True, 1, mon + dt.timedelta(days=1), fixes=[("item-id", "i")])
add("update", True, 1, mon + dt.timedelta(days=2), fixes=[("step-kept", "k")]); add("update", True, 1, mon + dt.timedelta(days=2), fixes=[("wake", "w")])
CL.record("update", True, item="g1", sender="a", fixes=[(CL.BOUNCE + "wake", "")], now=epoch(2026, 11, 4, 11))
c5b, p5b = RR.collect(mon)
t5b = RR.build(mon, c5b, p5b)
check("5 report: the share counts only the fixes of the checked kinds (1 of the 2 wake fixes, not of the 4 fixes made), and says so", "- fixes the writer sent back: 1 of the 2 fixes checked (50.0%) (wake 1 of 2)" in t5b and "corrected by the server instead of refused: 4 (wake 2 · item-id 1 · step-kept 1)" in t5b, t5b)
add("update", True, 1, mon - dt.timedelta(days=6), fixes=[("wake", "w")]); add("update", True, 1, mon - dt.timedelta(days=6), fixes=[("item-id", "i")]); add("update", True, 1, mon - dt.timedelta(days=6), fixes=[("item-id", "i")])
c5c, p5c = RR.collect(mon)
t5c = RR.build(mon, c5c, p5c)
check("5 report: …and so does the week before (1 checked fix of the 3 made)", "; the week before 0 of 1 (0.0%)" in t5c, t5c)
wipe(); add("update", True, 10, mon + dt.timedelta(days=1))
c6, p6 = RR.collect(mon)
check("5 report: with no fixes and no bounce-backs the line is left out", "sent back" not in RR.build(mon, c6, p6), None)

# ================================================================ 6. the report goes to the project's background agent too
week_data()
msgs, pages = [], []
def deliver_page(to, text_, sender): pages.append((to, text_, sender)); return True, "[200] ok"
def deliver_back(to, text_, sender): msgs.append((to, text_, sender)); return True, "[200] ok"
cfg_proj = {"enabled": True, "to": "projects/demo", "top": 6, "sender": "stackshot refusal report"}
res = RR.run(now=after, cfg=cfg_proj, deliver=deliver_page, deliver_agent=deliver_back, resolve=lambda to: "demo-builder" if to == "projects/demo" else "", state=fresh("route1"))
check("6 route: the page copy goes as before, and the background agent gets the report as a message that asks it to file the repeating kinds",
      res["sent"] and len(pages) == 1 and pages[0][0] == "projects/demo" and "What I ask of you" not in pages[0][1], (res, pages))
check("6 route: …the message names the agent, carries the whole report and the ask, and the result says both were sent",
      len(msgs) == 1 and msgs[0][0] == "demo-builder" and pages[0][1] in msgs[0][1] and "What I ask of you" in msgs[0][1] and "write-time hint or a server fix" in msgs[0][1] and "and to its background agent demo-builder" in res["why"], (msgs, res))
res = RR.run(now=after, cfg=cfg_proj, deliver=deliver_page, deliver_agent=deliver_back, resolve=lambda to: "", state=fresh("route2"))
check("6 route: a project with no background agent gets the page copy alone, and the week is recorded", res["sent"] and len(pages) == 2 and len(msgs) == 1 and "background agent" not in res["why"] and fresh("route2").exists(), (res, msgs))
res = RR.run(now=after, cfg=cfg_proj, deliver=deliver_page, deliver_agent=lambda *a: (False, "[500] down"), resolve=lambda to: "demo-builder", state=fresh("route3"))
check("6 route: a failing message to the agent does not unsend the page copy or the record, and says so", res["sent"] and "message to its background agent demo-builder failed" in res["why"] and fresh("route3").exists(), res)
res = RR.run(now=after, cfg=cfg_proj, deliver=lambda *a: (False, "[500] down"), deliver_agent=deliver_back, resolve=lambda to: "demo-builder", state=fresh("route4"))
check("6 route: a failing page copy sends nothing to the agent and records nothing", not res["sent"] and len(msgs) == 1 and not fresh("route4").exists(), (res, msgs))
n_msgs = len(msgs)
res = RR.run(now=after, cfg=cfg_proj, deliver=deliver_page, deliver_agent=deliver_back, resolve=lambda to: "demo-builder", state=fresh("route5"), dry=True)
check("6 route: a dry run sends neither", not res["sent"] and len(msgs) == n_msgs, res)
check("6 route: a `to` that is a session name has no project to read: the agent resolver gives none", RR.background_agent("my-x") == "" and RR.background_agent("") == "", None)
from stackshot.anchors import anchors as _anc_mod
_was_bg = _anc_mod.background_ranked
_anc_mod.background_ranked = lambda p, reg=None: [(1, 0, "demo-builder"), (2, 1, "demo-other")] if p == "projects/demo" else []
try:
    got_a, got_b = RR.background_agent("projects/demo"), RR.background_agent("projects/none")
    def boom(p, reg=None): raise OSError("registry unreadable")
    _anc_mod.background_ranked = boom
    got_c = RR.background_agent("projects/demo")
finally:
    _anc_mod.background_ranked = _was_bg
check("6 route: the resolver takes the first background agent of anchors.background_ranked (the builder first), none for a project with none, and none when the registry cannot be read", (got_a, got_b, got_c) == ("demo-builder", "", ""), (got_a, got_b, got_c))

# ================================================================ 7. streaks: one writer refused 3 times or more on one call within 15 minutes
def ref(t_min, sender="team-back", tool="update", item="a1", why="Refused: next no longer lists 'a'", ok=False):
    return {"t": 1_800_000_000 + int(t_min * 60), "tool": tool, "ok": ok, "item": item, "sender": sender, "why": why}
check("7 const: the window is 15 minutes and the threshold 3, as named constants", RR.STREAK_WINDOW == 15 * 60 and RR.STREAK_MIN == 3, (RR.STREAK_WINDOW, RR.STREAK_MIN))
got = RR.streaks([ref(0), ref(5), ref(9)])
check("7 streaks: three refusals of one writer on one item, each within 15 minutes of the one before, are one streak", len(got) == 1 and got[0]["n"] == 3 and got[0]["sender"] == "team-back" and got[0]["item"] == "a1" and got[0]["kind"].startswith("a step left out of next"), got)
check("7 streaks: two refusals are none", RR.streaks([ref(0), ref(5)]) == [], None)
check("7 streaks: a gap over 15 minutes cuts the run (2 + 2 is none, 3 after the gap is one of 3)", RR.streaks([ref(0), ref(5), ref(21), ref(26)]) == [] and [x["n"] for x in RR.streaks([ref(0), ref(5), ref(21), ref(26), ref(30)])] == [3], RR.streaks([ref(0), ref(5), ref(21), ref(26), ref(30)]))
check("7 streaks: each refusal counts from the one before it, not from the first: 4 refusals 14 minutes apart are one streak of 4", [x["n"] for x in RR.streaks([ref(0), ref(14), ref(28), ref(42)])] == [4], RR.streaks([ref(0), ref(14), ref(28), ref(42)]))
check("7 streaks: exactly 15 minutes apart still joins, 15 minutes and a second does not", [x["n"] for x in RR.streaks([ref(0), ref(15), ref(30)])] == [3] and RR.streaks([ref(0), ref(15.02), ref(30.04)]) == [], None)
check("7 streaks: another writer, another item or another tool is another call: they do not join", RR.streaks([ref(0), ref(1, sender="x-back"), ref(2, item="a2"), ref(3, tool="create"), ref(4, sender="y-back")]) == [], None)
check("7 streaks: a refusal that went through in between is not one, and does not break the run", [x["n"] for x in RR.streaks([ref(0), ref(1, ok=True), ref(2), ref(3)])] == [3], None)
SUB = "Refused: subject is 90 characters, the limit is 80"
mix = RR.streaks([ref(0, why=SUB), ref(1), ref(2), ref(3), ref(4, why=SUB)])
tie = RR.streaks([ref(0, why=SUB), ref(1), ref(2), ref(3, why=SUB)])
check("7 streaks: a streak of mixed kinds is counted under the kind most of its refusals are, the later one on a tie", len(mix) == 1 and mix[0]["n"] == 5 and mix[0]["kind"].startswith("a step left out of next") and len(tie) == 1 and tie[0]["kind"].startswith("subject is"), (mix, tie))
check("7 streaks: a call other than create and update names its tool before the kind", RR.streaks([ref(0, tool="complete", why="Refused: x"), ref(1, tool="complete", why="Refused: x"), ref(2, tool="complete", why="Refused: x")])[0]["kind"].startswith("complete: "), None)

week_data()
cur, prev = RR.collect(mon)
check("7 tally: the streaks of the week by kind, with the refusals they hold (the 12, the 5 and the 3 of the week; the 2 complete refusals are no streak)",
      sum(cur["streaks"].values()) == 3 and sum(cur["streak_refusals"].values()) == 20 and cur["streak_refusals"]["a step left out of next with no done or dropped"] == 12 and cur["streaks"]["a description bullet over its limit"] == 1, (cur["streaks"], cur["streak_refusals"]))
check("7 tally: …the week before is its own", sum(prev["streaks"].values()) == 1 and sum(prev["streak_refusals"].values()) == 10, (prev["streaks"], prev["streak_refusals"]))
text = RR.build(mon, cur, prev, top=6)
check("7 report: the streak line counts streaks and the refusals they hold of all refusals, with the share, the week before and the kinds",
      "- repeated refusals (one writer refused 3 times or more on one call within 15 minutes, a gap in the tool text): 3 streaks hold 20 of 22 refusals (90.9%); the week before 1 holding 10 of 10" in text
      and "a step left out of next with no done or dropped 1 holding 12" in text and "a description bullet over its limit 1 holding 5" in text, text)
check("7 report: …and it comes before the kinds of refusals, since the reviewer takes streaks first", 0 < text.index("repeated refusals") < text.index("the kinds of create and update refusals"), text)
RR.STREAK_MIN = 2
two = RR.tally(list(CL.read(*RR.week_bounds(mon))))
RR.STREAK_MIN = 3
check("7 const: the threshold is read from the constant (at 2 the two complete refusals are a streak too)", sum(two["streaks"].values()) == 4, two["streaks"])
wipe()
for hh in (9, 10, 11): CL.record("update", False, item="a1", sender="team-back", why="Refused: next no longer lists 'a'", now=epoch(2026, 11, 3, hh))
CL.record("update", True, now=epoch(2026, 11, 3, 12))
c7, p7 = RR.collect(mon)
check("7 report: refusals an hour apart are no streak, and the line is left out", "repeated refusals" not in RR.build(mon, c7, p7), RR.build(mon, c7, p7))
week_data()
msgs2 = []
res = RR.run(now=after, cfg=cfg_proj, deliver=lambda *a: (True, "[200] ok"), deliver_agent=lambda to, t, s: (msgs2.append(t) or (True, "[200] ok")), resolve=lambda to: "demo-builder", state=fresh("streak1"))
check("7 route: the message to the background agent lists the streak kinds before the kinds of refusals, and its ask names them first",
      res["sent"] and len(msgs2) == 1 and 0 < msgs2[0].index("repeated refusals") < msgs2[0].index("the kinds of create and update refusals") < msgs2[0].index("What I ask of you") and "take the repeated-refusal kinds first" in msgs2[0], msgs2)

# ================================================================ 8. the store of open fixes, the cap, the call row and the report's reading of them
from stackshot.waits import server_fixes as SF
OPENF = CALLS / "open-fixes.json"
def reset_open():
    for f in CALLS.glob("open-fixes.json*"): f.unlink()
wipe(); reset_open()
out, err = run_mw("update", {"item_id": "12", "sender": "team-back", "wake": "2026-11-09T08:00:00Z"}, wake_fix)
row = lines()[-1]
check("8 call row: a write that went through with a fix names its item and sender, so a later difference in the writer's text can be explained", row.get("fix") == ["wake", "item-id"] and row.get("item") == "g12" and row.get("sender") == "team-back", row)
out, err = run_mw("update", {"item_id": "12", "sender": "team-back", "next": "team-back: go"}, lambda: reply("updated " + BID(12)))
check("8 call row: …and one with no fix and no bounce-back stays as small as it was (no item, no sender)", "item" not in lines()[-1] and "sender" not in lines()[-1], lines()[-1])
raw = OPENF.read_text(encoding="utf-8")
check("8 open fixes: the file holds digests, not the session name nor the values (the key is item and a digest of the writer; the detail is digests and field names)",
      "team-back" not in raw and "2026-11-09" not in raw and f"12|{H('team-back')}" in raw and H("2026-11-09T12:00") in raw, raw[:300])
tok = CL.begin(); SF.record({}, "front_mover", "mover=Demo-Main|front-main-x|1700000000", "stackshot: front agent", 1_800_000_000); _, det7 = CL.end_detail(tok)
CL.remember("g7", "front-main-x", det7, now=1_800_000_000)
check("8 open fixes: a front-mover fix too keeps no agent name in the file (the key holds a digest of the writer)", "emo-main" not in OPENF.read_text(encoding="utf-8") and "front-main-x" not in OPENF.read_text(encoding="utf-8") and f"g7|{H('front-main-x')}" in OPENF.read_text(encoding="utf-8"), OPENF.read_text(encoding="utf-8")[-200:])
tok = CL.begin(); CL.fixed("wake", "w", fields=["wake"], stored="plain-value", sent="plain-sent", token="plain-token"); _, det = CL.end_detail(tok)
check("8 open fixes: …in the kept detail", det["wake"] == {"fields": ["wake"], "stored": H("plain-value"), "sent": H("plain-sent"), "token": H("plain-token")}, det)

# the cap: per writer, and in all (small caps for the test)
reset_open()
keep0, total0 = CL.OPEN_KEEP, CL.OPEN_TOTAL
CL.OPEN_KEEP, CL.OPEN_TOTAL = 5, 12
try:
    T0 = 1_800_100_000
    CL.remember("gb", "quiet-writer", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=T0)
    for i in range(8):
        CL.remember(f"gf{i}", "noisy-writer", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=T0 + 1 + i)
    d8 = CL._read_open()
    mine = sorted(k for k in d8 if k.endswith("|" + H("noisy-writer")))
    check("8 cap: one writer keeps its newest OPEN_KEEP fixes, the oldest of its own go first", mine == [f"gf{i}|{H('noisy-writer')}" for i in range(3, 8)], mine)
    check("8 cap: …and a flood by one writer never pushes another writer's record out", f"gb|{H('quiet-writer')}" in d8 and CL.bounces("gb", "quiet-writer", {"wake": "b"}, now=T0 + 20) == ["wake"], list(d8))
    reset_open()
    for w in range(4):
        for i in range(4):
            CL.remember(f"gt{w}{i}", f"writer-{w}", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=T0 + w * 10 + i)
    d9 = CL._read_open()
    check("8 cap: in all, no more than OPEN_TOTAL are kept, the oldest first", sum(len(v) for v in d9.values()) == 12 and f"gt00|{H('writer-0')}" not in d9 and f"gt33|{H('writer-3')}" in d9, (sum(len(v) for v in d9.values()), sorted(d9)))
finally:
    CL.OPEN_KEEP, CL.OPEN_TOTAL = keep0, total0
check("8 cap: the defaults are a writer's 100 and 2000 in all (a writer works a handful of items in an hour; the file stays small)", CL.OPEN_KEEP == 100 and CL.OPEN_TOTAL == 2000, (CL.OPEN_KEEP, CL.OPEN_TOTAL))

# a write that began before the fix was made could not have read its note
reset_open()
CL.remember("gp", "s", {"wake": {"fields": ["wake"], "stored": H("a")}}, now=100.9)
check("8 since: a write that began (100.7) before the fix was made (100.9) is no bounce-back, and the fix stays open for the next", CL.bounces("gp", "s", {"wake": "b"}, now=105, since=100.7) == [] and CL.bounces("gp", "s", {"wake": "b"}, now=106, since=101.5) == ["wake"], None)
check("8 since: no start time given asks every open fix (a caller that has none)", CL.bounces("gp", "s", {"wake": "b"}, now=107) == [], None)
reset_open()
def concurrent_fix():          # another call by the same writer on the same item finishes while this one runs
    CL.remember("g21", "team-back", {"wake": {"fields": ["wake"], "stored": H("a")}})
    return reply("updated " + BID(21))
out, err = run_mw("update", {"item_id": "21", "sender": "team-back", "wake": "2026-12-01"}, concurrent_fix)
check("8 since: through the middleware, the same writer's write that was running while the fix was made is no bounce-back", "bounce" not in lines()[-1], lines()[-1])
out, err = run_mw("update", {"item_id": "21", "sender": "team-back", "wake": "2026-12-02"}, lambda: reply("updated " + BID(21)))
check("8 since: …and the next write, begun after it, is", lines()[-1].get("bounce") == ["wake"], lines()[-1])

# one bounce of a kind per call: a store with two records of a kind, or a call that counted it itself, adds it once
reset_open()
OPENF.write_text(json.dumps({f"g22|{H('team-back')}": [{"k": "wake", "t": 1_800_000_000, "d": {"fields": ["wake"], "stored": H("a")}}, {"k": "wake", "t": 1_800_000_001, "d": {"fields": ["wake"], "stored": H("b")}}]}), encoding="utf-8")
real_now = time.time
time.time = lambda: 1_800_000_030.0
try:
    out, err = run_mw("update", {"item_id": "22", "sender": "team-back", "wake": "2026-12-05"}, lambda: reply("updated " + BID(22)))
finally:
    time.time = real_now
check("8 dedupe: two open records of one kind give one bounce-back in the row", lines()[-1].get("bounce") == ["wake"], lines()[-1])
wipe(); reset_open()          # the patched clock put the last row in a later month: start the log again
CL.remember("g23", "team-back", {"wake": {"fields": ["wake"], "stored": H("a")}})
def counts_it():
    CL.counted(CL.BOUNCE + "wake")
    return reply("updated " + BID(23))
out, err = run_mw("update", {"item_id": "23", "sender": "team-back", "wake": "2026-12-05"}, counts_it)
check("8 dedupe: a bounce-back the call counted itself is not added a second time", lines()[-1].get("bounce") == ["wake"], lines()[-1])

# the declined and the same-front-agent paths no longer count a bounce-back of their own: the same-writer, one-hour rule is the only count
check("8 no decline count: call_log has no `bounced` (the decline path was another writer's, or an hour late, as often as not)", not hasattr(CL, "bounced"), None)
tok = CL.begin(); SF.decline({}, "wake_park", "2026-11-09"); fx8, _ = CL.end_detail(tok)
check("8 no decline count: declining a park inside a write adds nothing to the call", fx8 == [], fx8)
tok = CL.begin(); SF.record({}, "wake_park", "2026-11-09", "stackshot: parked", 1_800_000_000); fx8, det8 = CL.end_detail(tok)
check("8 server_fixes: a park the server made is kept for the check by the wake it parked on", [k for k, _ in fx8] == ["wake_park"] and det8["wake_park"] == {"stored": H("2026-11-09")}, (fx8, det8))
tok = CL.begin(); SF.record({}, "front_mover", "mover=Demo-Main|team-back|1700000000", "stackshot: front agent", 1_800_000_000); fx8, det8 = CL.end_detail(tok)
check("8 server_fixes: a front-agent substitution is kept for the check by the field and the agent written (lower case)", det8["front_mover"] == {"fields": ["mover"], "stored": H("demo-main")}, det8)

# the report never reads more send-backs than fixes
wipe()
add("update", True, 1, mon + dt.timedelta(days=1), fixes=[("wake", "w")])
CL.record("update", True, item="g1", sender="a", fixes=[(CL.BOUNCE + "wake", "")], now=epoch(2026, 11, 3, 11))
CL.record("update", True, item="g1", sender="a", fixes=[(CL.BOUNCE + "wake", "")], now=epoch(2026, 11, 3, 12))
CL.record("update", True, item="g1", sender="a", fixes=[(CL.BOUNCE + "subject-prefix", "")], now=epoch(2026, 11, 3, 13))
c8, p8 = RR.collect(mon)
t8 = RR.build(mon, c8, p8)
check("8 report: send-backs are clamped to the fixes of their kind (2 wake send-backs of 1 wake fix read 1 of 1), never 'N of M' with N over M, and a kind with no fix shows none",
      "1 of the 1 fix checked (100.0%)" in t8 and "2 of 1" not in t8 and "200.0%" not in t8 and "subject-prefix" not in t8.split("sent back")[-1].split("\n")[0], t8)

# a refused create has no item: its call digest tells one create from another
def rc(t_min, call, sender="team-back"):
    r_ = ref(t_min, tool="create", item="", sender=sender); r_["call"] = call; return r_
check("8 streaks: three refused creates by one writer with the same call digest are one streak", [x["n"] for x in RR.streaks([rc(0, "aaaa"), rc(2, "aaaa"), rc(4, "aaaa")])] == [3], None)
check("8 streaks: three refused creates of three different subjects are no streak (one writer, three unrelated creates)", RR.streaks([rc(0, "aaaa"), rc(2, "bbbb"), rc(4, "cccc")]) == [], None)
check("8 streaks: a refused line with neither an item nor a call digest is no call to count (an old row, a create refused before it has a subject)", RR.streaks([rc(0, ""), rc(2, ""), rc(4, "")]) == [], None)
wipe(); reset_open()
for subj in ("[hp] one thing", "[hp] one thing", "[hp] another"):
    run_mw("create", {"subject": subj, "sender": "team-back"}, lambda: (_ for _ in ()).throw(ToolError("Refused: x")))
cr = [x for x in lines() if x["tool"] == "create"]
check("8 call row: a refused create carries a short digest of its subject as `call` (the same subject the same digest, another subject another), and no item",
      len(cr) == 3 and cr[0]["call"] == cr[1]["call"] != cr[2]["call"] and len(cr[0]["call"]) == 8 and not cr[0]["item"] and "[hp]" not in json.dumps(cr), cr)
run_mw("update", {"item_id": "9", "sender": "team-back"}, lambda: (_ for _ in ()).throw(ToolError("Refused: y")))
check("8 call row: a refused update names its item and carries no call digest", lines()[-1]["item"] == "9" and "call" not in lines()[-1], lines()[-1])

# the reply: a combined reply never asks for the whole write again
n_desc = ("description-bullet", "1 description bullet over 120 characters was split at the end of a sentence into shorter bullets, no word changed")
n_wake = ("wake", "wake 2026-11-09T08:00:00Z read as 2026-11-09T12:00 +04")
only_desc, only_wake, both = CL.reply_note([n_desc]), CL.reply_note([n_wake]), CL.reply_note([n_desc, n_wake])
check("8 reply: a description split alone invites no resend, a wake fix alone does", "send it again" not in only_desc and "send it again as you want it" in only_wake, (only_desc, only_wake))
check("8 reply: a split beside another fix never ends 'send it again as you want it' (that would put the whole write back): it names the field that can be kept and says the rest is complete",
      "send it again" not in both and "the wake" in both and "the rest is complete as stored" in both and both.startswith("\n(fixed for you: 1 description bullet"), both)
check("8 reply: two fixes that both invite a resend keep the one general line", CL.reply_note([n_wake, ("subject-prefix", "prefix put")]).endswith("send it again as you want it.)"), None)
check("8 reply: a step-none and a split, neither inviting a resend, close plainly", "send it again" not in CL.reply_note([n_desc, ("step-none", "step=\"none\" changed nothing")]) and "write that field" not in CL.reply_note([n_desc, ("step-none", "x")]), None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
