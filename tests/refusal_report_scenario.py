"""Scenario tests for the two counts the audit unit sends, in two parts that each run in a process of their own: the count of refused board writes (tools/refusal_report.py) and the count of a hook's catches (tools/catch_report.py) (formerly the suites refusal_report and catch_report).

Part `refusal_report` - the count of refused board writes, and the small corrections the server makes instead of refusing.

Checked here against a scratch state folder and config (no port, no real server, no message sent, no model call):

  1  call_log: one line per counted call (went through, went through with a correction, refused) in `<state>/calls/<YYYY-MM>.jsonl`; a refusal keeps tool, item, sender and the clipped, folded reason and
     no other argument; an uncounted tool writes nothing; a line that does not parse is skipped on read; the range read takes the month files it spans; kind_of names the refusal kinds and folds the rest
  2  the middleware (web/middleware.py _RefusalLog, run as _wmw._RefusalLog): a refused write is logged as refused and records no correction; a write that went through with a correction carries one reply line saying what the server
     did and how to keep the field as written, and is logged with the fix kinds; a write with none is logged plain and its reply is as it was
  3  the corrections: a bare item number is read as board#N; a full ISO wake (seconds, a fraction, Z or an offset) is converted to that minute in the instance zone; a subject with no scope prefix
     takes the project's scope prefix (else the fallback); a script's item (`by`) and a subject that already has a prefix are left alone; a field sent again as written is not touched (it is refused as before)
  4  the weekly report (tools/refusal_report.py): the text and its share arithmetic, the week before, the kinds, the senders, the corrections, a late-starting log; sent once per week, not before the
     week is over, not when `enabled` is false, not with no records; --dry-run, --force and --week; the audit.py verb and the audit unit's ExecStartPost

Part `catch_report` - Scenario test for the record of a hook's catches (`client.py post catch`, POST /client/catch, service/catches.py) and its daily count (tools/catch_report.py, `audit.py catches`) — fixture data, no live
store, no network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: the route (a machine token is enough; no token and an unknown token are a 401; a body that is not an object, a field that is not text, a missing required field, a bad or offset-less time, a control
character, a field over its limit are a 400 that names the field, with nothing written); the id (a replay answers 200 with duplicate true and writes nothing, eight threads posting one id write one line); the line
(one per catch in `<state>/catches/<YYYY-MM>.jsonl`, the body's fields plus source, project and day; `first` folded to one line and clipped to 200 characters); the source classes worked out from the raw sender,
the kind and the roles registry (router notice, stackshot message, background-agent hand-back, front peer, script, other, and the order the rules apply in); the project (the pane's, else the sender's, else
none); the day in the instance timezone (just before and just after midnight, an offset other than the instance's, a month boundary that opens the next month's file); the held fyi (the first catch of an
hour for one pane and sender sends the project's builder one line, composed in the instance timezone with the first words, an @name broken; a second in the hour, another hour, another sender or pane, a project with no builder,
a send that fails; it goes through the message path as an fyi, and held for the builder's next turn); the report (the per-source table with the day before and its total, the panes and senders caught most, a day with no
catches not sent, sent once per day to the configured session, not while `enabled` is false, --dry-run and --force, a record that cannot be written, the command line, the audit verb, the unit's ExecStartPost, the
example config and the docs); and `client.py post catch` (the fields on stdin or as flags, ok or duplicate on stdout, usage on misuse, the server's refusal on stderr, a server that is not reached).

The two parts set up two different instances (their own config, fixture pages and state folder) and the code under test reads its config and keeps module state at import: so each part runs in a process of its own (this file starts them).

    tests/run-suite refusal_report        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("refusal_report", "catch_report")


# ================================================================ part refusal_report: the count of refused board writes, and the small corrections the server makes instead of refusing
def part_refusal_report():
    import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, subprocess, sys, time, types
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

    return ran, fails


# ================================================================ part catch_report: a hook's catches and their daily count
def part_catch_report():
    import contextlib, datetime as dt, io, json, os, re, socket, subprocess, sys, pathlib, logging, threading, time
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="catchrep-"); T = pathlib.Path(tmp)          # removed and locked by _scratch while the suite runs, whatever ends it
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = ""', f'session_links = "{tmp}/links"', 1); assert f'session_links = "{tmp}/links"' in toml   # the fixture registry, never the host's store
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1       # the person the tools speak of
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    (T / "home").mkdir()
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T / "home")); os.environ.pop("STACKSHOT_URL", None)
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    for d in ("store/a", "fleet/a", "links/a", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({uid_: {"name": n_, "machine": "a"} for uid_, n_ in (("00000000-0000-4000-8000-000000000101", "home-sparrow-builder"), ("00000000-0000-4000-8000-000000000102", "home-sparrow-main"))}))   # live in the heartbeat: a message goes only to a session the fleet lists
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

    def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
    S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104)}
    def row(key, name, project_key):
        return {"id": S[key], "name": name, "aliases": [], "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
                "cwd": "/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
                "transcripts": [{"id": uid(200 + int(S[key][-3:]) - 100), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
    ROWS = [row("build", "home-sparrow-builder", "projects/alpha"), row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild")]
    (T / "links/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
    def page(rel, front):
        q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
    page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\n    stackshot-builder: keeps a log\n    stackshot: keeps a log\nstatus: active")
    page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: home-nobuild\nagents:\n  home-nobuild-main: talks to Oliver\nstatus: active")
    for pg in (T / "brain").rglob("*.md"): os.utime(pg, (time.time() - 8 * 3600, time.time() - 8 * 3600))
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

    from stackshot.projects import pages as p
    p.cmd_registry(quiet=True)
    from stackshot.fleet import sessions_registry as sr
    sr.TTL = 0
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.fleet import client
    from stackshot.web.routes import client_api as _rt_client
    from stackshot.service import catches as CA
    from stackshot.tools import catch_report as CR
    from stackshot.core import config as _cfg
    from stackshot.web import publish as _web_publish
    from stackshot.waits import held as _held
    from stackshot.service import messaging as _messaging
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    CA._now = lambda: dt.datetime(2026, 12, 15, 12, 0, tzinfo=dt.timezone.utc).timestamp()          # the server's clock for this part: the times below are from Jan to Dec 2026, and a catch's `t` may be at most two days ahead of it
    from starlette.testclient import TestClient
    me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); HD = {"Authorization": "Bearer " + tok}
    CATCHES = T / "state/catches"
    zone = _cfg.tz()
    def lines(name=None):
        out = []
        for q in sorted(CATCHES.glob("*.jsonl")) if CATCHES.exists() else []:
            if name and q.stem != name: continue
            out += [json.loads(l) for l in q.read_text(encoding="utf-8").split("\n") if l.strip()]       # newline only, as the server reads
        return out
    def wipe():
        for q in list(CATCHES.glob("*.jsonl")) if CATCHES.exists() else []: q.unlink()
        CA._BUDGET.clear()
    told = []                                  # every fyi the server would hold: (to, text, kind, sender, project)
    fail_next = {"on": False, "refuse": False}
    def fake_hold(target, text, kind, *, gid="", project="", sender="", asks=False, owner_words=False):
        if fail_next["on"]: raise RuntimeError("the hold is down")
        if fail_next["refuse"]: return False
        told.append((target, text, kind, sender, project)); return True
    real_hold = CA._telling.hold_notice
    CA._telling.hold_notice = fake_hold
    pushes = []                                # a fyi pushed as a turn would come through the message path: the catch never uses it
    _messaging._message = lambda *a, **k: pushes.append((a, k)) or "pushed"
    N = [0]
    def body(**kw):
        N[0] += 1
        b = {"hook": "no-ask-signoff", "id": f"catch-{N[0]}", "t": "2026-11-02T10:05:00+04:00", "pane": "home-sparrow-main", "kind": "message", "sender": "home-sparrow-builder", "outcome": "nudged", "first": "Nothing needed from you."}
        b.update(kw)
        return {k: v for k, v in b.items() if v is not None}
    def post(**kw): return _rt_client._client_post(me, "catch", body(**kw))

    # ---- 1. one catch: the line, the answer, the fields the server adds
    b1 = body()
    st, o = _rt_client._client_post(me, "catch", b1)
    check("a catch: 200 ok, not a duplicate, with its source, project and day", st == 200 and o == {"ok": True, "duplicate": False, "id": b1["id"], "source": "background-agent hand-back", "project": "projects/alpha", "day": "2026-11-02", "told": "home-sparrow-builder"}, (st, o))
    got = lines("2026-11")
    check("…one line in the month's file with the body's eight fields and source, project and day, nothing else", len(got) == 1 and got[0] == {**b1, "source": "background-agent hand-back", "project": "projects/alpha", "day": "2026-11-02"}, got)
    st, o2 = _rt_client._client_post(me, "catch", b1)
    check("a replay of the id: 200 ok with duplicate true, nothing written, nothing told again", st == 200 and o2["ok"] is True and o2["duplicate"] is True and o2["told"] == "" and len(lines()) == 1 and len(told) == 1, (st, o2, len(lines()), len(told)))
    st, o3 = _rt_client._client_post(me, "catch", {**b1, "first": "another text", "sender": "someone"})
    check("…even when the replay's other fields differ: the first line stands", st == 200 and o3["duplicate"] is True and len(lines()) == 1 and lines()[0]["first"] == "Nothing needed from you.", (st, o3))
    check("a body with extra keys is taken, the extras ignored", post(extra="x")[0] == 200 and "extra" not in lines()[-1], lines()[-1])
    st, o = post(sender=None, outcome=None, first=None)
    check("sender, outcome and first may be left out: they read as empty text", st == 200 and lines()[-1]["sender"] == "" and lines()[-1]["outcome"] == "" and lines()[-1]["first"] == "" and lines()[-1]["source"] == "other", (st, o, lines()[-1]))

    # ---- 2. first: folded and clipped, never refused for its length
    st, o = post(first="line one\n  line two\t" + "w" * 500)
    f = lines()[-1]["first"]
    check("first: whitespace folded to one line, clipped to 200 characters (the last is an ellipsis), the catch taken", st == 200 and len(f) == 200 and f.startswith("line one line two ") and f.endswith("…") and "\n" not in f, (st, len(f), f[:40]))
    st, o = post(first="x" * 200)
    check("first: exactly 200 characters is kept whole", st == 200 and lines()[-1]["first"] == "x" * 200, lines()[-1]["first"][-5:])
    st, o = post(first="")
    check("first: empty is taken", st == 200 and lines()[-1]["first"] == "", st)

    # ---- 3. a bad body is a 400 that names the field, and writes nothing
    n0 = len(lines()); told0 = len(told)
    bads = [("an id of 201 characters", dict(id="i" * 201), "id"), ("a hook of 81 characters", dict(hook="h" * 81), "hook"), ("a pane of 121 characters", dict(pane="p" * 121), "pane"), ("a kind of 41 characters", dict(kind="k" * 41), "kind"),
            ("a sender of 301 characters", dict(sender="s" * 301), "sender"), ("an outcome of 121 characters", dict(outcome="o" * 121), "outcome"),
            ("an id that is a number", dict(id=7), "id"), ("a hook that is a list", dict(hook=["a"]), "hook"),
            ("a pane with a newline", dict(pane="a\nb"), "pane"), ("a sender with a control character", dict(sender="a\x07b"), "sender"),
            ("no hook", dict(hook=""), "hook"), ("no id", dict(id=" "), "id"), ("no time", dict(t=""), "t"), ("no pane", dict(pane=""), "pane"), ("no kind", dict(kind=""), "kind"),
            ("a time that is not a time", dict(t="yesterday at noon"), "t"), ("a time with no offset", dict(t="2026-11-02T10:05:00"), "t"), ("a date alone", dict(t="2026-11-02"), "t")]
    for name, kw, field in bads:
        st, e = post(**kw)
        check(f"{name}: 400 naming `{field}`, nothing written, nothing told", st == 400 and e["error"].startswith(field + " = "), (st, e))
    for ch_name, ch in (("U+2028", "\u2028"), ("U+2029", "\u2029"), ("U+0085", "\u0085"), ("a tab", "\t"), ("a no-break space", "\xa0"), ("a zero-width space", "\u200b")):
        outs = [(field, post(**{field: f"a{ch}b"})) for field in ("sender", "pane", "id", "hook", "outcome", "kind")]
        check(f"{ch_name} in a sender, a pane, an id, a hook, an outcome or a kind: 400 naming the field, nothing written", all(st == 400 and e["error"].startswith(field + " = ") for field, (st, e) in outs), outs)
    for key in ("hook", "id", "t", "pane", "kind"):
        b = body(); del b[key]; st, e = _rt_client._client_post(me, "catch", b)
        check(f"a body with no {key}: 400 naming it", st == 400 and e["error"].startswith(key + " = ") and "required" in e["error"], (st, e))
    check("…and none of those wrote a line or told a builder", len(lines()) == n0 and len(told) == told0, (len(lines()), n0, len(told), told0))
    st, e = post(t="2026-11-02T10:05:00")
    check("the time's refusal says what is taken (an offset or Z) with an example", "offset" in e["error"] and "+09:00" in e["error"], e)
    for ok_t in ("2026-11-02T06:05:00Z", "2026-11-02T10:05:00+04:00", "2026-11-02T10:05:00.250+04:00"):
        check(f"a time {ok_t!r} is taken", post(t=ok_t)[0] == 200, ok_t)

    # ---- 4. the source classes: from the raw sender, the kind and the roles registry; the first rule that fits
    wipe(); told.clear()
    CASES = [("a notice kind", dict(kind="notice", sender="stackshot"), "router notice"), ("a router kind, a spelling with a capital and an underscore", dict(kind="Router_Notice", sender="whoever"), "router notice"),
             ("a notice kind beats a background sender", dict(kind="notice", sender="home-sparrow-builder"), "router notice"),
             ("a message from the server's own name", dict(kind="message", sender="stackshot"), "stackshot message"), ("…a label that starts with it", dict(kind="message", sender="stackshot audit"), "stackshot message"),
             ("a name that only begins with the letters is no server label", dict(kind="message", sender="stackshots-friend"), "other"),
             ("a message from a background agent", dict(kind="message", sender="home-sparrow-builder"), "background-agent hand-back"), ("…another background agent of the page", dict(kind="message", sender="home-sparrow-notes"), "background-agent hand-back"),
             ("…the name in another case", dict(kind="message", sender="Home-Sparrow-Builder"), "background-agent hand-back"),
             ("a message from a front agent", dict(kind="message", sender="home-sparrow-docs"), "front peer"), ("…the pane's own project-mate, with the sender's whitespace trimmed", dict(kind="message", sender="  home-sparrow-docs  "), "front peer"),
             ("a script kind", dict(kind="script", sender="nightly-job"), "script"), ("a message whose sender says it is a script", dict(kind="message", sender="nightly (a script on testbox)"), "script"),
             ("a sender that starts with script", dict(kind="message", sender="script: nightly"), "script"), ("a script kind beats a front sender", dict(kind="script", sender="home-sparrow-docs"), "script"),
             ("a message from nobody the registry lists", dict(kind="message", sender="a-stranger"), "other"), ("an unlisted kind and an empty sender", dict(kind="wake", sender=""), "other")]
    for name, kw, want in CASES:
        st, o = post(**kw)
        check(f"source: {name} -> {want}", st == 200 and o["source"] == want and lines()[-1]["source"] == want, (st, o))
    check("…the source is worked out here: one the hook sends is ignored", post(source="front peer", kind="message", sender="a-stranger")[1]["source"] == "other" and lines()[-1]["source"] == "other", lines()[-1])
    st, o = post(pane="home-sparrow-main", sender="a-stranger"); pr1 = o["project"]
    st, o = post(pane="not-listed-pane", sender="home-sparrow-builder"); pr2 = o["project"]
    st, o = post(pane="not-listed-pane", sender="a-stranger"); pr3 = o["project"]
    st, o = post(pane="home-nobuild-main", sender="home-sparrow-builder"); pr4 = o["project"]
    check("project: the pane's agent's page; else the sender's; else none; the pane wins over the sender", (pr1, pr2, pr3, pr4) == ("projects/alpha", "projects/alpha", "", "projects/nobuild"), (pr1, pr2, pr3, pr4))

    # ---- 5. the day in the instance timezone (Asia/Dubai, +04:00) and the month's file
    wipe(); told.clear()
    for name, t, day, month in (("just before local midnight, written in UTC", "2026-11-02T19:59:59Z", "2026-11-02", "2026-11"), ("local midnight, written in UTC", "2026-11-02T20:00:00Z", "2026-11-03", "2026-11"),
                                ("late in the evening at an offset behind the instance", "2026-11-02T23:30:00-05:00", "2026-11-03", "2026-11"), ("early at an offset ahead of it", "2026-11-03T03:30:00+09:00", "2026-11-02", "2026-11"),
                                ("the last evening of a month, in UTC", "2026-11-30T19:00:00Z", "2026-11-30", "2026-11"), ("…and an hour later, which is the next month here", "2026-11-30T20:00:00Z", "2026-12-01", "2026-12"),
                                ("the instance's own offset", "2026-11-02T00:00:00+04:00", "2026-11-02", "2026-11")):
        st, o = post(t=t)
        mine = next((r for r in lines() if r["id"] == o.get("id")), {})
        check(f"day: {name}: {t} is {day}", st == 200 and o["day"] == day and mine.get("day") == day and mine.get("t") == t, (st, o))
        check(f"…and is written to the {month} file", any(json.loads(l)["id"] == o["id"] for l in (CATCHES / f"{month}.jsonl").read_text(encoding="utf-8").splitlines()), sorted(q.name for q in CATCHES.glob("*")))
    check("the day read back: read_day finds the lines of one day only, in the order written", [r["t"] for r in CA.read_day("2026-11-02")] == ["2026-11-02T19:59:59Z", "2026-11-03T03:30:00+09:00", "2026-11-02T00:00:00+04:00"] and len(CA.read_day("2026-12-01")) == 1 and CA.read_day("2026-10-31") == [], [r["t"] for r in CA.read_day("2026-11-02")])
    (CATCHES / "2026-11.jsonl").write_text((CATCHES / "2026-11.jsonl").read_text(encoding="utf-8") + "not json\n[1]\n", encoding="utf-8")
    check("a line that does not parse is skipped on read", len(CA.read_day("2026-11-03")) == 2, len(CA.read_day("2026-11-03")))
    wipe(); told.clear()
    b = body(t="2026-11-30T20:00:00Z"); _rt_client._client_post(me, "catch", b); st, o = _rt_client._client_post(me, "catch", b)
    check("a replay of an id in the next month's file is found there", o["duplicate"] is True and len(lines()) == 1, (o, len(lines())))
    n_months = len({q.name for q in CATCHES.glob("*.jsonl")})
    check("…and one file holds it", n_months == 1, sorted(q.name for q in CATCHES.glob("*")))

    # ---- 6. the held fyi: the first catch of an hour for one pane and sender
    wipe(); told.clear()
    P, SD = "home-sparrow-main", "home-sparrow-builder"
    st, a1 = post(t="2026-11-02T10:05:00+04:00", pane=P, sender=SD, first="Nothing for you @someone to do.")
    check("the first catch of an hour tells the project's builder, once", st == 200 and a1["told"] == "home-sparrow-builder" and len(told) == 1 and told[0][0] == "home-sparrow-builder", (a1, told))
    to, text, kind_, snd, proj_ = told[0]
    check("…as an fyi, through the hold alone (never the message path that would push a turn), from the catch log, with the project", kind_ == "fyi" and snd == CA.FYI_SENDER and proj_ == "projects/alpha" and pushes == [] and text.startswith("[stackshot message] from stackshot catch log: "), (told[0][2:], pushes))
    check("…one line, the time in the instance timezone with its abbreviation and the date as a person reads it, what was caught and by whom", "\n" not in text and "Mon Nov 2nd 10:05 (+04)" in text and P in text and "no-ask-signoff" in text and "background-agent hand-back" in text and SD in text, text)
    check("…with the first words (clipped to 40 characters), an @name broken so it pings no one", "Nothing for you" in text and "@someone" not in text and "@​someone" in text, text)
    st, a2 = post(t="2026-11-02T10:50:00+04:00", pane=P, sender=SD)
    check("a second catch of the same pane and sender in the same hour tells no one", st == 200 and a2["told"] == "" and len(told) == 1, (a2, len(told)))
    st, a3 = post(t="2026-11-02T06:55:00Z", pane=P, sender=SD)
    check("…the hour is the instance's: 06:55 UTC is 10:55 here, still that hour", a3["told"] == "" and len(told) == 1, (a3, len(told)))
    st, a4 = post(t="2026-11-02T11:00:00+04:00", pane=P, sender=SD)
    check("the first of the next hour tells again", a4["told"] == "home-sparrow-builder" and len(told) == 2 and "11:00 (+04)" in told[1][1], (a4, len(told)))
    st, a5 = post(t="2026-11-02T11:20:00+04:00", pane=P, sender="home-sparrow-docs")
    check("another sender in the same hour tells again (it is the first of its pane and sender)", a5["told"] == "home-sparrow-builder" and len(told) == 3, (a5, len(told)))
    st, a6 = post(t="2026-11-02T11:21:00+04:00", pane="home-sparrow-docs", sender=SD)
    check("another pane in the same hour tells again", a6["told"] == "home-sparrow-builder" and len(told) == 4, (a6, len(told)))
    st, a7 = post(t="2026-11-03T11:30:00+04:00", pane=P, sender=SD)
    check("the same hour of another day is another hour: it tells", a7["told"] == "home-sparrow-builder" and len(told) == 5, (a7, len(told)))
    st, a8 = post(t="2026-11-02T19:45:00-05:00", pane=P, sender=SD)       # 2026-11-03 04:45 here: the same hour of day as nothing before it
    check("a catch posted late (an hour already past) is judged by its own hour, not by the clock", st == 200 and a8["told"] == "home-sparrow-builder" and len(told) == 6, (a8, len(told)))
    n_told = len(told)
    st, a9 = post(t="2026-11-02T14:00:00+04:00", pane="home-nobuild-main", sender="whoever")
    check("a project with no builder: the catch is written, no one is told, no error", st == 200 and a9["project"] == "projects/nobuild" and a9["told"] == "" and lines()[-1]["id"] == a9["id"] and len(told) == n_told, (a9, len(told)))
    st, a10 = post(t="2026-11-02T14:00:00+04:00", pane="not-listed-pane", sender="whoever")
    check("a pane no page lists (no project): written, no one told", st == 200 and a10["project"] == "" and a10["told"] == "" and len(told) == n_told, (a10, len(told)))
    fail_next["on"] = True
    n_lines = len(lines())
    st, a11 = post(t="2026-11-02T16:00:00+04:00", pane=P, sender=SD)
    check("a hold that fails: the catch is written, the answer is 200 with nothing told, no error raised", st == 200 and a11["told"] == "" and len(lines()) == n_lines + 1, (st, a11))
    fail_next["on"] = False; fail_next["refuse"] = True
    st, a11b = post(t="2026-11-02T16:05:00+04:00", pane="home-sparrow-docs", sender="someone-else")
    check("a hold that is refused (the builder's hook does not fetch held lines): written, nothing told, nothing pushed in its place", st == 200 and a11b["told"] == "" and pushes == [], (st, a11b, pushes))
    fail_next["refuse"] = False
    st, a12 = post(t="2026-11-02T16:30:00+04:00", pane=P, sender=SD)
    check("…that hour counts as seen (the line was written first): the next catch in it tells no one", a12["told"] == "", a12)

    st, a12b = post(t="2026-11-02T18:00:00+04:00", pane=P, sender=SD, first="y" * 200)
    check("the first words in the line are clipped to 40 characters, so the held line stays a short note", a12b["told"] != "" and "\"" + "y" * 39 + "\u2026\"" in told[-1][1] and "y" * 41 not in told[-1][1] and len(told[-1][1]) <= 260, told[-1][1])

    # the real hold: the same fyi is held for the builder's next turn and starts none
    CA._telling.hold_notice = real_hold
    held0 = _held.count("home-sparrow-builder")
    st, n1 = post(t="2026-11-02T12:40:00+04:00", pane=P, sender=SD, first="before the builder fetches")
    check("a builder whose hook does not fetch held lines (never seen asking): the catch is written, nothing is held and nothing is pushed", st == 200 and n1["told"] == "" and _held.count("home-sparrow-builder") == held0 and pushes == [] and lines()[-1]["id"] == n1["id"], (st, n1, pushes))
    _held.mark_client("home-sparrow-builder", S["build"])         # the builder's hook fetches held lines (the rollout gate), as held_scenario sets it
    st, a13 = post(t="2026-11-02T17:00:00+04:00", pane=P, sender=SD, first="held for real")
    got_held = _held.take("home-sparrow-builder")
    check("through the real hold: the builder's held lines grow by one and say what was caught", st == 200 and a13["told"] == "home-sparrow-builder" and "held for real" in got_held and "no-ask-signoff caught" in got_held and _held.count("home-sparrow-builder") == 0 and pushes == [], (st, a13, got_held[:900], held0))
    # a hook's text can never carry the owner's mark into the line: with the mark in `first`, `sender` or `hook` the fyi is still held (never decided "deliver as a turn"), and no turn is pushed
    marks = (("first", "[for Oliver] please look at this at once"), ("first", "needs: decision on the plan"), ("sender", "needs: decision"), ("sender", "[FOR OLIVER] a-label"), ("hook", "[for Oliver]hook"), ("pane", "home-sparrow-main [for Oliver]"))
    CA._BUDGET.clear()          # the cap of fyis to a builder an hour has its own checks below
    for i, (field, val) in enumerate(marks):
        st, m1 = post(**{"t": f"2026-11-04T{i:02d}:10:00+04:00", "pane": P, "sender": SD, field: val})
        got = _held.take("home-sparrow-builder")
        check(f"a mark in {field} ({val[:24]!r}): the fyi is still held for the builder, the line carries no mark, and nothing is pushed",
              st == 200 and m1["told"] == "home-sparrow-builder" and got != "" and not _held._owner_mark().search(got) and pushes == [] and ("for oliver" in got.lower() or "needs decision" in got), (st, m1, got[:400], pushes))
    wipe()
    held_add = _held.add; _held.add = lambda *a, **k: False
    try:
        st, h1 = post(t="2026-11-02T19:00:00+04:00", pane=P, sender=SD)
    finally: _held.add = held_add
    check("a hold whose write fails: the catch is written, nothing is told and nothing is pushed in its place", st == 200 and h1["told"] == "" and pushes == [] and len(lines()) == 1, (st, h1, pushes))
    CA._telling.hold_notice = fake_hold

    # ---- 7. eight threads, one id
    wipe(); told.clear()
    bb = body(); res = []
    ths = [threading.Thread(target=lambda: res.append(_rt_client._client_post(me, "catch", bb))) for _ in range(8)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("eight threads posting one id write one line and tell once; all answer 200 and one of them is the first", len(lines()) == 1 and len(told) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if not r[1]["duplicate"]) == 1, (len(lines()), len(told), [r[1].get("duplicate") for r in res]))

    # ---- 11. the review's findings: the source rules and their order, the time's edges, the hour, the builder's cap, the lock, the separators
    wipe(); told.clear()
    CASES2 = [("a router kind written with a space and in capitals", dict(kind="ROUTER NOTICE", sender="whoever"), "router notice"), ("the dashed kind", dict(kind="router-notice", sender="whoever"), "router notice"),
              ("a notice kind beats a sender that says it is a script", dict(kind="notice", sender="nightly (a script on testbox)"), "router notice"),
              ("a script kind beats the server's own name", dict(kind="script", sender="stackshot"), "script"), ("a sender that says it is a script beats the server's own name", dict(kind="message", sender="stackshot via a script on testbox"), "script"),
              ("the server's own name beats the registry (a background agent named `stackshot`)", dict(kind="message", sender="stackshot"), "stackshot message"),
              ("…in another case, with a label after it", dict(kind="message", sender="Stackshot Audit"), "stackshot message"),
              ("`stackshot-builder` is a session's name: a background agent of the registry is a hand-back", dict(kind="message", sender="stackshot-builder"), "background-agent hand-back"),
              ("`stackshotx` is no server label", dict(kind="message", sender="stackshotx"), "other"), ("`stackshot-other` which the registry does not list is other", dict(kind="message", sender="stackshot-other"), "other"),
              ("a script kind beats a background sender", dict(kind="script", sender="home-sparrow-builder"), "script"), ("a notice kind beats the server's own name", dict(kind="notice", sender="stackshot audit"), "router notice")]
    for name, kw, want in CASES2:
        st, o = post(**kw)
        check(f"source: {name} -> {want}", st == 200 and o["source"] == want and lines()[-1]["source"] == want, (st, o))
    inst_name = CA._inst.NAME
    CA._inst.NAME = "relay"
    try:
        r1, r2, r3 = (post(kind="message", sender=x)[1]["source"] for x in ("relay", "relay audit", "stackshot audit"))
    finally: CA._inst.NAME = inst_name
    check("the server's own name is the instance's [instance] name, not a word in the code: `relay` and `relay audit` with that name, `stackshot audit` no longer", (r1, r2, r3) == ("stackshot message", "stackshot message", "other"), (r1, r2, r3))

    wipe(); told.clear()
    now_utc = dt.datetime.fromtimestamp(CA._now(), dt.timezone.utc)
    for name, t in (("the first instant of the calendar at the farthest offset ahead", "0001-01-01T00:00:00+14:00"), ("the last instant of the calendar at the farthest offset behind", "9999-12-31T23:59:59-14:00"),
                    ("the first instant of the calendar in UTC", "0001-01-01T00:00:00Z"), ("a year before 2020", "1999-06-01T12:00:00Z"), ("the last second before 2020", "2019-12-31T23:59:59Z"),
                    ("a time far ahead", "2099-01-01T00:00:00Z"), ("three days ahead of now", (now_utc + dt.timedelta(days=3)).isoformat(timespec="seconds"))):
        try: st, e = post(t=t)
        except Exception as ex: st, e = 0, {"error": repr(ex)}
        check(f"t {name} ({t}): 400 naming `t`, no exception, nothing written", st == 400 and e["error"].startswith("t = ") and not list(CATCHES.glob("*")), (st, e, sorted(q.name for q in CATCHES.glob("*"))))
    st1, e1 = post(t="2020-01-01T00:00:00Z"); st2, e2 = post(t=(now_utc + dt.timedelta(days=1)).isoformat(timespec="seconds"))
    check("…the edges themselves are taken: 2020-01-01T00:00:00Z and a time a day ahead", st1 == 200 and st2 == 200 and (CATCHES / "2020-01.jsonl").exists(), (st1, e1, st2, e2))

    wipe(); told.clear()
    nyc = __import__("zoneinfo").ZoneInfo("America/New_York")
    h_a, h_b = dt.datetime.fromisoformat("2026-11-01T01:30:00-04:00"), dt.datetime.fromisoformat("2026-11-01T01:30:00-05:00")
    check("the hour is the UTC instant's: the two 01:30s of the night a clock goes back are two hours, and 05:59Z is the first one's hour", CA._hour(h_a) != CA._hour(h_b) and CA._hour(h_a) == CA._hour(dt.datetime.fromisoformat("2026-11-01T05:59:00+00:00")), (CA._hour(h_a), CA._hour(h_b)))
    cfg_tz = CA._cfg.tz; CA._cfg.tz = lambda: nyc
    try:
        st, f1 = post(t="2026-11-01T01:30:00-04:00", pane=P, sender=SD); st, f2 = post(t="2026-11-01T01:30:00-05:00", pane=P, sender=SD); st, f3 = post(t="2026-11-01T01:50:00-05:00", pane=P, sender=SD)
    finally: CA._cfg.tz = cfg_tz
    check("in a zone that repeats an hour: both 01:30s tell the builder, a second catch in the second one does not", f1["told"] == f2["told"] == "home-sparrow-builder" and f3["told"] == "" and len(told) == 2, (f1, f2, f3, len(told)))

    wipe(); told.clear()
    outs = [post(t="2026-11-02T10:05:00+04:00", pane=f"cap-pane-{i}", sender=SD)[1]["told"] for i in range(12)]
    check("a builder is sent at most FYI_PER_BUILDER (10) fyis in an hour, whatever the panes: 12 first catches of 12 panes tell 10", CA.FYI_PER_BUILDER == 10 and outs == ["home-sparrow-builder"] * 10 + ["", ""] and len(told) == 10, (CA.FYI_PER_BUILDER, outs, len(told)))
    check("…and the catches over the cap are written all the same", len(lines()) == 12, len(lines()))
    real_now = CA._now; CA._now = lambda: real_now() + 3700
    try: st, g1 = post(t="2026-11-02T10:05:00+04:00", pane="cap-pane-next", sender=SD)
    finally: CA._now = real_now
    check("…the next hour of the clock counts again", g1["told"] == "home-sparrow-builder" and len(told) == 11, (g1, len(told)))
    fail_next["refuse"] = True
    outs = [post(t="2026-11-02T10:05:00+04:00", pane=f"cap-refused-{i}", sender=SD)[1]["told"] for i in range(12)]
    fail_next["refuse"] = False
    st, g2 = post(t="2026-11-02T10:05:00+04:00", pane="cap-after-refused", sender=SD)
    check("holds that were refused or failed take nothing from the hour's cap (it is the held ones that count): 12 refused, and the next one is still told", set(outs) == {""} and g2["told"] == "home-sparrow-builder" and max(CA._BUDGET.values(), default=0) == 1, (outs, g2, dict(CA._BUDGET)))

    wipe(); told.clear()
    st, o = post(first="a\u2028b\u0085c\u2029d\x00e\tf\x0bg")
    check("first with line and paragraph separators and control characters: they become spaces, one folded line", st == 200 and lines()[-1]["first"] == "a b c d e f g", lines()[-1])
    wipe(); CATCHES.mkdir(parents=True, exist_ok=True)
    rawrow = {"hook": "h", "id": "raw-1", "t": "2026-11-02T10:05:00+04:00", "pane": "p", "kind": "k", "sender": "a\u2028b\u0085c", "outcome": "", "first": "", "source": "other", "project": "", "day": "2026-11-02"}
    (CATCHES / "2026-11.jsonl").write_text(json.dumps(rawrow, ensure_ascii=False) + "\n", encoding="utf-8")
    check("a line separator inside a stored field (U+2028, U+0085) never cuts a line: read_day returns the row whole", [r["id"] for r in CA.read_day("2026-11-02")] == ["raw-1"] and CA.read_day("2026-11-02")[0]["sender"] == "a\u2028b\u0085c", CA.read_day("2026-11-02"))
    st, o = post(id="raw-1", t="2026-11-02T10:05:00+04:00")
    check("…and a replay of that id is a duplicate, written once", st == 200 and o["duplicate"] is True and len(lines()) == 1, (st, o, len(lines())))

    wipe(); told.clear()
    real_rows = CA._rows; bar = threading.Barrier(8)
    def slow_rows(path):          # every thread has read the file before any of them writes (the barrier gives up after 2 s: with the lock the others wait outside it and never arrive)
        got = list(real_rows(path))
        try: bar.wait(2.0)
        except threading.BrokenBarrierError: pass
        return iter(got)
    CA._rows = slow_rows
    bb = body(); res = []
    try:
        ths = [threading.Thread(target=lambda: res.append(_rt_client._client_post(me, "catch", bb))) for _ in range(8)]
        [t.start() for t in ths]; [t.join() for t in ths]
    finally: CA._rows = real_rows
    check("eight threads that all read the file before any writes: the lock still lets one write, one tell and seven duplicates (without the lock this writes eight)", len(lines()) == 1 and len(told) == 1 and sum(1 for r in res if not r[1]["duplicate"]) == 1 and len(res) == 8, (len(lines()), len(told), len(res), [r[1].get("duplicate") for r in res]))

    # ---- 8. over HTTP: the token
    app = server.mcp.http_app()
    wipe(); told.clear()
    with TestClient(app) as c:
        jb = body()
        r = c.post("/client/catch", json=jb); check("http: without a token -> 401, nothing written", r.status_code == 401 and lines() == [], (r.status_code, r.text))
        r = c.post("/client/catch", json=jb, headers={"Authorization": "Bearer " + "x" * 43}); check("http: an unknown token -> 401, nothing written", r.status_code == 401 and lines() == [], (r.status_code, r.text))
        r = c.post("/client/catch", json=jb, headers={"Authorization": "Bearer short"}); check("http: a token of the wrong shape -> 401", r.status_code == 401 and lines() == [], r.status_code)
        r = c.post("/client/catch", json=jb, headers=HD)
        check("http: with the machine token -> 200 and the line, answered with no-store", r.status_code == 200 and r.json()["ok"] is True and r.json()["duplicate"] is False and r.headers["cache-control"] == "no-store" and len(lines()) == 1, (r.status_code, r.text))
        r = c.post("/client/catch", json=jb, headers=HD); check("http: the same id again -> 200 duplicate", r.status_code == 200 and r.json()["duplicate"] is True and len(lines()) == 1, r.text)
        r = c.post("/client/catch", json=body(t="2026-11-02T10:05:00"), headers=HD); check("http: a bad time -> 400 with the error", r.status_code == 400 and r.json()["error"].startswith("t = "), r.text)
        r = c.post("/client/catch", content="[1, 2]", headers={**HD, "Content-Type": "application/json"}); check("http: a body that is no object -> 400", r.status_code == 400 and "JSON object" in r.json()["error"], r.text)
        r = c.post("/client/catch", content="nope", headers={**HD, "Content-Type": "application/json"}); check("http: a body that is no JSON -> 400", r.status_code == 400, r.text)
        import hashlib
        from stackshot.service import caller_pass as _cp
        ptok = _cp.PASS_PREFIX + "p" * 40; _cp._PASSES[hashlib.sha256(ptok.encode()).hexdigest()] = {"fp": "f" * 64, "sender": "a-form", "exp": time.time() + 600}
        lookup = _cp._keys.lookup_approved; _cp._keys.lookup_approved = lambda fp: {"sender": "a-form"}
        try:
            n_before = len(lines())
            r = c.post("/client/catch", json=body(), headers={"Authorization": "Bearer " + ptok})
            r2 = c.post("/client/job-gap", json={}, headers={"Authorization": "Bearer " + ptok})
        finally: _cp._keys.lookup_approved = lookup; _cp._PASSES.clear()
        check("http: a pass (a caller's own key) is no machine token: catch is a 403 that names what a pass opens, nothing written", r.status_code == 403 and "a pass opens only" in r.text and len(lines()) == n_before and r2.status_code == 403, (r.status_code, r.text, r2.status_code))
        r = c.post("/client/no-such-catch", json={}, headers=HD); check("http: the 404 for an unknown write lists catch among the writes there are", r.status_code == 404 and "catch" in r.text and "job-gap" in r.text, r.text)

        # ---- 9. client.py post catch
        import urllib.request, urllib.error
        class _Resp:
            def __init__(s, r): s.status = r.status_code; s._b = r.content
            def read(s): return s._b
            def __enter__(s): return s
            def __exit__(s, *a): return False
        down = {"on": False}
        def fake_urlopen(req, timeout=0):
            if down["on"]: raise urllib.error.URLError("connection refused")
            path = req.full_url.replace(client.server_url(), "")
            r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
            if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen
        def run(*argv, stdin=None):
            so, se = io.StringIO(), io.StringIO()
            old = sys.stdin
            sys.stdin = io.StringIO(stdin or "")
            try:
                with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
            finally: sys.stdin = old
            return rc, so.getvalue(), se.getvalue()
        wipe(); told.clear()
        jb = body(); flags = [x for k, v in jb.items() for x in (f"--{k}", v)]
        rc, o, e = run("post", "catch", *flags)
        check("client.py with flags: ok on stdout, nothing on stderr, exit 0, one line written", rc == 0 and o == "ok\n" and e == "" and len(lines()) == 1 and lines()[0]["id"] == jb["id"], (rc, o, e))
        rc, o, e = run("post", "catch", *flags)
        check("client.py again with the same id: duplicate on stdout, exit 0, nothing more written", rc == 0 and o == "duplicate\n" and e == "" and len(lines()) == 1, (rc, o, e))
        jb2 = body()
        rc, o, e = run("post", "catch", "-", stdin=json.dumps(jb2))
        check("client.py with the object on stdin: ok, the line written", rc == 0 and o == "ok\n" and lines()[-1]["id"] == jb2["id"], (rc, o, e))
        jb3 = body()
        rc, o, e = run("post", "catch", "-", "--kind", "script", stdin=json.dumps(jb3))
        check("client.py: a flag wins over the stdin object", rc == 0 and lines()[-1]["id"] == jb3["id"] and lines()[-1]["kind"] == "script" and lines()[-1]["source"] == "script", (rc, o, e, lines()[-1]))
        n_l = len(lines())
        U = "usage: client.py post catch"
        for name, argv, stdin, needle in (("no fields at all", [], None, "required"), ("a missing pane", ["--hook", "h", "--id", "i", "--t", "2026-11-02T10:05:00Z", "--kind", "k"], None, "required"),
                                          ("a flag with no value", ["--hook"], None, "needs a value"), ("a stray word", ["stray", "--hook", "h"], None, U), ("an unknown flag", ["--nope", "x"], None, U),
                                          ("stdin that is not JSON", ["-"], "not json", "does not parse"), ("stdin that is a list", ["-"], "[1]", "not an object"),
                                          ("stdin with a number as the id", ["-"], json.dumps({**body(), "id": 5}), "required")):
            rc, o, e = run("post", "catch", *argv, stdin=stdin)
            check(f"client.py misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
        rc, o, e = run("post", "catch", "--hook", "h", "--id", "i1", "--t", "2026-11-02T10:05:00", "--pane", "p", "--kind", "k")
        check("client.py with a time the server refuses: the server's 400 on stderr, exit 1, nothing on stdout, nothing written", rc == 1 and o == "" and "[400]" in e and "t = " in e and len(lines()) == n_l, (rc, o, e))
        tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
        try:
            rc, o, e = run("post", "catch", *flags)
            check("client.py with no token on the machine: exit 1, the reason on stderr", rc == 1 and o == "" and "no token on this machine" in e, (rc, o, e))
        finally: hold.rename(tokfile)
        down["on"] = True
        rc, o, e = run("post", "catch", *[x for k, v in body().items() for x in (f"--{k}", v)])
        check("client.py with the server not reached: exit 1 and the reason on stderr", rc == 1 and o == "" and e.strip() != "" and len(lines()) == n_l, (rc, o, e))
        down["on"] = False

    # ---- 10. the report
    wipe(); told.clear()
    day = dt.date(2026, 11, 2); prev_day = dt.date(2026, 11, 1)
    def add(n, d, pane, sender, kind="message", hour=10):
        for i in range(n): post(t=f"{d.isoformat()}T{hour:02d}:{i % 60:02d}:00+04:00", pane=pane, sender=sender, kind=kind)
    add(3, day, "home-sparrow-main", "stackshot", kind="notice"); add(2, day, "home-sparrow-main", "home-sparrow-builder"); add(1, day, "home-sparrow-docs", "home-sparrow-docs", kind="message")
    add(1, day, "home-sparrow-docs", "nightly (a script on testbox)"); add(2, day, "home-nobuild-main", "a-stranger", hour=15)
    add(1, prev_day, "home-sparrow-main", "stackshot", kind="notice"); add(2, prev_day, "home-sparrow-main", "stackshot"); add(1, prev_day, "home-sparrow-docs", "home-sparrow-builder", hour=23)
    add(1, dt.date(2026, 11, 3), "home-sparrow-main", "stackshot", kind="notice", hour=0)             # the next day: in neither column
    cur, prev = CR.collect(day)
    check("tally: the day's counts by source, pane and sender, and the day before's", cur["total"] == 9 and dict(cur["sources"]) == {"router notice": 3, "background-agent hand-back": 2, "front peer": 1, "script": 1, "other": 2}
          and prev["total"] == 4 and dict(prev["sources"]) == {"router notice": 1, "stackshot message": 2, "background-agent hand-back": 1}, (cur["total"], dict(cur["sources"]), prev["total"], dict(prev["sources"])))
    check("tally: a line of a source the code does not know counts as other", CR.tally([{"source": "from the future", "pane": "p", "sender": "s"}])["sources"] == {"other": 1}, None)
    text = CR.build(day, cur, prev, top=3)
    check("report: the headline with the day's total in the instance timezone and the day before's", text.startswith("Hook catches, Mon Nov 2nd (+04): 9; the day before 4\n"), text)
    rowre = lambda name, a, b: re.search(rf"(?m)^{re.escape(name)}\s+{a}\s+{b}$", text) is not None
    check("report: a table with a row for each source and the total, the day beside the day before", re.search(r"(?m)^source\s+Mon Nov 2nd\s+Sun Nov 1st$", text) and rowre("router notice", 3, 1) and rowre("stackshot message", 0, 2) and rowre("background-agent hand-back", 2, 1)
          and rowre("front peer", 1, 0) and rowre("script", 1, 0) and rowre("other", 2, 0) and rowre("total", 9, 4) and text.count("```") == 2, text)
    check("report: the panes caught most and the senders of the turns, the top N, most first", re.search(r"- caught most: home-sparrow-main 5 · (home-nobuild-main 2 · home-sparrow-docs 2|home-sparrow-docs 2 · home-nobuild-main 2)\n", text) and "- turns started by: stackshot 3 · home-sparrow-builder 2" in text, text)
    t_next = CR.build(dt.date(2026, 11, 5), *CR.collect(dt.date(2026, 11, 5)))
    check("report: a day after a day with none reads no catches the day before", "no catches recorded for the day before" in t_next, t_next)
    check("the report reads the log and never writes it", len(lines()) == 14, len(lines()))

    sent = []
    def deliver(to, text_, sender): sent.append((to, text_, sender)); return True, "[200] ok"
    sp = lambda n: T / f"state/catch-report/{n}.json"
    after = dt.datetime(2026, 11, 3, 5, 0, tzinfo=zone).timestamp()                  # the day after: Mon Nov 2nd is over
    cfg_on = {"enabled": True, "to": "my-x", "top": 5, "sender": "stackshot catch report"}
    res = CR.run(now=after, cfg=cfg_on, deliver=deliver, state=sp("a"))
    check("run: yesterday is sent once to the configured session, as the configured sender", res["sent"] and res["day"] == day and len(sent) == 1 and sent[0][0] == "my-x" and sent[0][2] == "stackshot catch report" and "Hook catches, Mon Nov 2nd" in sent[0][1], (res, sent))
    res = CR.run(now=after + 3600, cfg=cfg_on, deliver=deliver, state=sp("a"))
    check("run: …and not again (the audit timer runs twice a day)", not res["sent"] and res["why"] == "already sent" and len(sent) == 1, res)
    res = CR.run(now=after + 3600, cfg=cfg_on, deliver=deliver, state=sp("a"), force=True)
    check("run: --force sends the day again", res["sent"] and len(sent) == 2, res)
    res = CR.run(now=after, cfg=dict(cfg_on, enabled=False), deliver=deliver, state=sp("off"))
    check("run: enabled = false sends nothing and marks nothing, and says so", not res["sent"] and res["why"].startswith("not enabled") and len(sent) == 2 and not sp("off").exists() and res["text"], res)
    res = CR.run(now=after, cfg=cfg_on, deliver=deliver, state=sp("dry"), dry=True)
    check("run: --dry-run returns the text, sends nothing, marks nothing (also while enabled)", not res["sent"] and res["why"] == "dry run" and res["text"] and len(sent) == 2 and not sp("dry").exists(), res)
    res = CR.run(now=after, cfg=cfg_on, deliver=lambda *a: (False, "[500] down"), state=sp("down"))
    check("run: a send that fails is not marked sent (the next run tries again)", not res["sent"] and not sp("down").exists() and "[500]" in res["why"], res)
    blocked = T / "state/catch-report/blocked"; blocked.write_text("a file where a folder should be")
    res = CR.run(now=after, cfg=cfg_on, deliver=deliver, state=blocked / "sent.json")
    check("run: a record that cannot be written is reported as 'sent but not recorded', not raised", res["sent"] and "but not recorded" in res["why"], res)
    res = CR.run(now=after, cfg=cfg_on, deliver=deliver, state=sp("none"), day=dt.date(2026, 10, 1))
    check("run: --day for a day with no catches sends nothing", not res["sent"] and res["why"] == "no catches recorded for the day", res)
    res = CR.run(now=after, cfg=cfg_on, deliver=deliver, state=sp("early"), day=prev_day)
    check("run: --day reports that day, the day before it counted from the log", res["sent"] and "Hook catches, Sun Nov 1st" in sent[-1][1] and "no catches recorded for the day before" in sent[-1][1], sent[-1][1][:120])
    res = CR.run(now=dt.datetime(2026, 11, 3, 0, 5, tzinfo=zone).timestamp(), cfg=cfg_on, deliver=deliver, state=sp("mid"), dry=True)
    check("run: just after local midnight, yesterday is the day that ended (the instance's day, not UTC's)", res["day"] == day, res["day"])
    check("settings: defaults from the config ([catch_report] present, enabled false: not enabled, five panes)", CR.settings()["enabled"] is False and CR.settings()["top"] == 5 and CR.settings()["sender"] == "stackshot catch report" and CR.settings()["to"], CR.settings())
    _cfg.CFG["catch_report"] = {"enabled": True, "to": "projects/alpha", "top": 3, "sender": "me"}
    check("settings: [catch_report] read live: enabled, to, top, sender", CR.settings() == {"enabled": True, "to": "projects/alpha", "top": 3, "sender": "me"}, CR.settings())
    _cfg.CFG["catch_report"] = {"top": 99, "enabled": "yes"}
    check("settings: a top out of range reads as the default, enabled as text yes is true", CR.settings()["top"] == 5 and CR.settings()["enabled"] is True, CR.settings())
    _cfg.CFG.pop("catch_report", None)

    # the command line and the audit verb, in a child process with the scratch config (a dry run: no message is sent)
    env = dict(os.environ, STACKSHOT_CONFIG=f"{tmp}/stackshot.toml")
    def cli(*argv):
        p_ = subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env, cwd=STACK, timeout=120)
        return p_.returncode, p_.stdout + p_.stderr
    rc, out = cli(os.path.join(STACK, "stackshot/tools/catch_report.py"), "run", "--dry-run", "--day", "2026-11-02")
    check("cli: catch_report.py run --dry-run --day prints the report and exits 0", rc == 0 and "Hook catches, Mon Nov 2nd (+04): 9; the day before 4" in out and "catch report: dry run" in out, (rc, out[-400:]))
    rc, out = cli(os.path.join(STACK, "stackshot/audit/audit.py"), "catches", "--dry-run", "--day", "2026-11-02")
    check("cli: audit.py catches is the same report", rc == 0 and "Hook catches, Mon Nov 2nd (+04): 9" in out, (rc, out[-400:]))
    rc, out = cli(os.path.join(STACK, "stackshot/audit/audit.py"), "catches", "--dry-run", "--day", "2026-10-01")
    check("cli: a day with no catches says so and exits 0", rc == 0 and "no catches recorded for the day" in out, (rc, out[-300:]))
    rc, out = cli(os.path.join(STACK, "stackshot/tools/catch_report.py"), "run", "--day", "not-a-date")
    check("cli: a bad --day exits 2 naming the form", rc == 2 and "YYYY-MM-DD" in out, (rc, out))
    rc, out = cli(os.path.join(STACK, "stackshot/tools/catch_report.py"), "run", "--bogus")
    check("cli: an unknown option prints the usage and exits 2", rc == 2 and "usage: catch_report.py" in out, (rc, out))
    rc, out = cli(os.path.join(STACK, "stackshot/audit/audit.py"), "bogus")
    check("cli: the audit's usage line lists the catches verb", rc == 2 and "catches [--dry-run] [--force] [--day DATE]" in out, (rc, out[-300:]))
    unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8").splitlines()
    post_ = [l for l in unit if l.startswith("ExecStartPost=") and "stackshot audit catches" in l]
    check("unit: the audit unit runs the count after the audit run, with a timeout and a leading '-' so a failure never fails the audit", len(post_) == 1 and post_[0].startswith("ExecStartPost=-/usr/bin/timeout ")
          and [i for i, l in enumerate(unit) if l.startswith("ExecStart=")][0] < unit.index(post_[0]), post_)
    ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
    check("example: the example config has a [catch_report] section, off", re.search(r"(?m)^\[catch_report\][^\n]*\nenabled = false", ex) is not None, ex[ex.find("[catch_report]"):][:300])
    import _docs
    check("docs: the route is in the client contract and the daily count in the audit page, the config keys in the configuration page",
          "POST /client/catch" in _docs.page("client-contract") and "post catch" in _docs.page("client-contract") and "hook catches" in _docs.page("audit").lower() and "catch_report.py" in _docs.page("audit")
          and all(f"`catch_report.{k}`" in _docs.page("configuration") for k in ("enabled", "to", "top", "sender")), None)
    cc = _docs.page("client-contract")
    check("docs: the contract says what the review found: kind aliases, the label from [instance] name, printable fields, the time's range, the same t for a replay, the UTC hour, the cap of 10 an hour, the hold only",
          all(x in cc for x in ("`router-notice`", "[instance] name", "`stackshot-builder`", "U+2028", "Jan 1st 2020", "same `t`", "the UTC hour of `t`", "At most 10 such fyis", "never pushed")), [x for x in ("`router-notice`", "[instance] name", "`stackshot-builder`", "U+2028", "Jan 1st 2020", "same `t`", "the UTC hour of `t`", "At most 10 such fyis", "never pushed") if x not in cc])
    check("docs: every source the server names is in the contract's text", all(s in _docs.page("client-contract") for s in CA.SOURCES), [s for s in CA.SOURCES if s not in _docs.page("client-contract")])

    return ran, fails

MARK = "@@refusal_report part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"refusal_report": part_refusal_report, "catch_report": part_catch_report}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as both suites always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: refusal_report scenario, {total} checks")
