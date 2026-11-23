"""Scenario tests for the wait on a LIST of waits, in three parts that each run in a process of their own (they set up different instances, and the code under test reads its config and keeps module state at import): fixture data, no live store, no network, no server socket. The file prints the sum of the three parts' checks.

Part `list` - the list itself, its model and its ending:

Scenario test for the wait on a LIST of waits (waits/wait_list.py, the model's sixth kind, the ending in watchers.py and server.py) — fixture data, no live store, no network, no server socket.

An item can wait on 2 to 8 waits at once, of any kind (time, anchor, item, relay, event), with a mode: `all` (it comes back when every line has arrived) or `any` (when the first has), and on its backstop
day at the latest. This part of the feature is storage, the model and the ending: the fixtures store the metadata directly (what a caller passes to write a list is held by the `write` part). Covered:

  * the pure half: what a stored list must be (a malformed or short one is not one), arrived marks that are idempotent, the group's end by mode, which lines an arrival is for (two lines on one item or anchor),
    the scheduler's next moment, the words of an end
  * the model: wait_kind=list reads as a wait of that kind with its lines and mode, the backstop and `due`; a list that does not hold is IGNORED (the item reads as a single wait, noted, counted); a single wait
    reads exactly as before; the phase stamp and the sweep write waits_on=list
  * the ending, per kind of line: time (the clock), item (a close, superseded followed, a missing file), anchor (a notice that answers the line's event), event (a reported event), relay (marked by the write
    path); mixed kinds; two lines on one item or anchor; `all` ends on the last arrival and `any` on the first; a repeated delivery changes nothing; an item already turned is not turned again
  * the backstop day, with and without an open relay line (the owner is asked then, and "not yet" puts the list back with what had arrived)
  * the end drops the wait's fields (waits and wait_mode with the rest), and the mover is told what arrived and what did not
  * the old wake pass never marks or ends a list before its backstop day; the watchers end it there, in their words; a single wait is not touched (the existing suites are the proof)

Part `display` - how a list reads on the board:

Scenario test for how a wait on a LIST of waits reads on the board (the home page's Waiting row, the item page's wait block, the `model:` line of get) — fixture data, no live store, no network, no server socket.

The list itself (waits/wait_list.py) and its ending are the `list` part's. Nothing a caller passes writes a list yet, so the fixtures store the metadata directly. Covered:

  * the Waiting row of a list item: one line per wait with its kind and what it waits on, a box ticked (with the time) once the line has arrived, "all of N" / "any of N", how many have arrived, and the one backstop
    day ("back anyway <day>"), the end slot on the right (until <day>), the who line (who picks it up, and who watches: one watcher per kind of line, an arrived line needs none)
  * the item page's wait block: the same lines with a second line each (what watches it, or in what words and when it arrived, an item line open or closed), the mode in words, the Backstop row, no Watched by row
    and no Chases row (a list is never chased), the Picks it up row
  * every kind of line: time, anchor, item, relay, event; free text (an event, an anchor, the words of an arrival) is escaped in the row and on the page
  * a single wait reads exactly as it did (a row with no list class, the old words, its Watched by and Chases rows), and a stored list that does not hold reads as the date alone
  * every user-visible string comes from the string table: a locale that marks every key marks every word of a list row and of the page block
  * the `model:` line of get: the mode, how many arrived, each line ticked [x] or open [ ], with the time (and the zone's name) and the words of an arrival and the backstop
  * a stored arrival time no date can show (inf, "inf", 1e20, 1e300, year 10000) reads as no arrival on the home page, the item page and get, and no display of a time can raise (a model handed such a time anyway keeps the
    arrival words and drops the time); an item id in a line is clipped; a line that arrived with no recorded words reads "arrived <time>", never "arrived · arrived <time>"

Part `write` - the write side of a list:

Scenario test for the WRITE side of a wait on a list (waits/wait_list_write.py, gates.gate_waits and the create and update tools) — a scratch store and config, no port, no network, no model call.

An item can wait on 2 to 8 things at once. A caller writes the list with `waits` (lines of any of the five kinds), `wait_mode` (all or any) and `until` (the backstop day); the server reads each line with the rules of a
stored line (waits/wait_list.py), judges the new ones as their single waits are judged, and stores the shape the read side expects. Covered:

  1  create       a list through the create tool: the stored fields, the reply, `get` reading it back; every refusal (no backstop, one or nine lines, a line twice, an anchor or item id over 300 characters,
                  an `arrived`, an unknown key or kind, a mode that is neither, a list beside single-wait parameters, no list at all, a closed or missing item, an anchor not on the list, an event that
                  already happened or is no event, a date in the past or after the backstop)
  2  update       a list through the update tool, as a list or as JSON text; the mode (given, kept, defaulted); a list replacing a single wait leaves nothing of that wait behind; sending the list again keeps what
                  has arrived and judges only the new lines; the backstop moves with until; a refusal changes nothing
  3  removing     lines taken out: two left is a list; ONE left is stored as the single wait it is, for each of the five kinds (and works as one: it ends and clears as that wait does); one that had arrived, or none:
                  the wait ends as clear_wait ends it; waits=[] and the text none clear, clear_wait clears, a clear of nothing changes nothing; no list of one is ever stored
  4  unchanged    the single waits, set and cleared the way they were; an unrelated write leaves a list as it was; a list that does not hold is no reason to refuse a write that does not touch it
  5  text         the parameters and the description say the list; the docs say how it is written and what each refusal is
  6  fix round    the loop test follows a list's item lines (list and list, list and single, through a third item; a line outside a loop is accepted); a single wait written over a stored list replaces it; a repeat is judged
                  after an event is canonical, and a stored list sent again is no repeat of itself; a text nested too deep; the text of an empty list is a clear and a list of dates is judged as a date wait; until alone
                  earlier than a stored time line; values of a line (text, 300 characters, its kind's fields); waits=[] with no list says so; blank, CLEAR and None, clear_wait beside a clear, a time line with a space

    tests/run-suite wait_list        -> exit 0 / 1"""
import dataclasses, datetime, datetime as dt, html, json, logging, os, pathlib, re, subprocess, sys, time, zoneinfo
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _midnight
sys.path.insert(0, STACK)
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" and "tomorrow" the checks of the write part read: start on the far side of one that is close (the parts start after this and wait the same way)

# The three parts set up three different instances (the write part sets HOME in its scratch folder and reads the example config as it is, the other two with the keyword set of another language), and the code
# under test reads its config and keeps module state at import: so each part runs in a process of its own (this file started again with `--part <name>`), exactly as the three suites did, and the parent adds their counts.
PARTS = ("list", "display", "write")

def _setup(prefix, *, keywords):
    """The scratch folder and the instance config of a part: every path inside the scratch folder, the fixtures' timezone and prefixes, the transcripts of the part. Returns (tmp, T)."""
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp)
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=keywords)
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    return tmp, T


# ================================================================ part list: the list, its model and its ending
def part_list():
    tmp, T = _setup("waitlist-", keywords=True)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time()
    DAY = 86400.0
    ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                    "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                    "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}},
                                                              "projects/beta": {"title": "Beta", "name": "Beta", "org": "home", "tags": [], "type": "project",
                                                                                "session": "", "status": "active", "board": [], "board_open": 0}}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
    (T / "brain/projects/beta.md").write_text("---\ntitle: Beta\n---\n\n# Beta\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    DESC = "- A thing\n- It lives here\n- Done when done"
    def item(i, owner=None, status="open", su=None, letter="a", subject=None, project="projects/alpha", **meta):
        su = now0 - 10 * DAY if su is None else su
        (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                                  "updated": su, "state_updated": su, "confirmed": su,
                                                                  "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
    def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
    def mt(i, letter="a"): return rd(i, letter)["metadata"]
    def raw(i, letter="a"): return (T / f"store/{letter}/{i}.json").read_text()
    def put(i, it, letter="a"): (T / f"store/{letter}/{i}.json").write_text(json.dumps(it))
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
    logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.service import writes, gates; from stackshot.waits import waiting as _WT, until_write as UW, wait_list as WL, watchers as wk, event_waits as EW; from stackshot.model import model, model_guards, migration
    from stackshot.service import stamp as stamp_svc
    from stackshot.service import answer as answer_svc
    from stackshot.service import wait_gates as wait_gates_svc, released as released_svc
    from stackshot.service import item_read as _item_read
    from stackshot.service import update as _update_svc
    from stackshot.router import routing as _routing
    from stackshot.core import config as _cfg
    from stackshot.projects import pages as _pages
    from stackshot.github import ghsync as _gh
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.service import migrations as migsvc
    from stackshot.service import wakes as wakes_svc, watching as watching_svc, event_waits as evwaits_svc
    from stackshot.service import telling
    _web_publish._publish = lambda: None
    _web_page_debts._refuse_if_owing = lambda debtor: None
    SENT: list[tuple[str, str, str, str]] = []
    telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
    NOTES: list[tuple[str, str]] = []                      # the History line of every save the server makes on its own (writes.save's note)
    _save = writes.save
    def _spy(gid, item_, *a, **kw):
        NOTES.append((gid, kw.get("note", "")))
        return _save(gid, item_, *a, **kw)
    writes.save = _spy
    ST = T / "state/waiting.json"
    ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
    day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
    BACK, OTHER, FRONT = "team-back", "home-other", "home-front"
    UB, UO, UF = U["team-back"], U["home-other"], U["home-front"]
    OWN = model.owner_display()
    CFG = _cfg.CFG.setdefault("model", {})
    def sent(tag=None): return [x for x in SENT if tag is None or x[3] == tag]
    def reset(): SENT.clear(); NOTES.clear()
    def notes_of(g): return [n for gid, n in NOTES if gid == g]
    def cfg(**kw):
        for k, v in kw.items(): CFG[k] = v
    cfg(guards=False, pause=False)       # the write guards have their own suite; here they are off
    AURL = "https://github.com/o/r/pull/5"
    AURL2 = "https://github.com/o/r/pull/6"
    def notice(text, ts=None, anchor="github:o/r#5", ruling="passed", to=None, **kw):
        n = {"id": "n" + str(len(SENT)) + str(int(time.time() * 1000) % 100000), "ts": now0 if ts is None else ts, "kind": "anchor", "anchor": anchor, "to": to or U["home-stew"], "text": text,
             "ruling": ruling, "ruled_at": now0 if ts is None else ts}
        n.update(kw); return n
    # the lines
    Tm = lambda d: {"kind": "time", "until": d}
    An = lambda url, ev="PR merged": {"kind": "anchor", "anchor": url, "event": ev}
    It = lambda g: {"kind": "item", "after": g}
    Re = lambda ev="the lease": {"kind": "relay", "event": ev}
    Ev = lambda ev: {"kind": "event", "event": ev}
    def lst(i, waits, mode="all", until=None, **extra):
        """A waiting item that stores a list: wait_kind=list, the lines, the mode, the backstop day in `until`, the post-wake mover; its wait stamped as the writer stamps it (`watch.set_at`)."""
        base = dict(wait_kind="list", hold=True, wait_mode=mode, until=until or day(9), waits=waits, post_wake_mover=BACK, needs=[], subject=f"[home] list {i}", watch={"set_at": now0 - 3600})
        base.update(extra)
        item(i, **base)
    def close(g, outcome="done", **more):
        it = rd(g); it["status"] = "completed"; it["metadata"].update(outcome=outcome, reason="r", **more); put(g, it)
        return wakes_svc.release_after(f"a{g}", outcome, more.get("superseded_by", ""), "home-front")
    def arrived_of(i): return [bool(ln.get("arrived")) for ln in mt(i)["waits"]]
    GONE = ("waits", "wait_mode", "wait_kind", "until", "post_wake_mover")

    # ================================================================ the pure half: what a stored list is
    GOOD = {"wait_kind": "list", "wait_mode": "all", "until": "2026-12-01", "waits": [Tm("2026-11-20"), It("a1")]}
    check("shape: a list of two lines with a mode and a backstop day holds; the lines are read in order with their fields", WL.valid(GOOD) and WL.mode(GOOD) == "all" and WL.backstop(GOOD) == "2026-12-01"
          and [ln["kind"] for ln in WL.lines(GOOD)] == ["time", "item"] and WL.lines(GOOD)[0]["until"] == "2026-11-20" and WL.lines(GOOD)[1]["after"] == "a1", WL.lines(GOOD))
    check("shape: …all five kinds hold, with the fields of their kinds; eight lines is the most", WL.valid({**GOOD, "waits": [Tm("2026-11-20"), An(AURL), It("a1"), Re(), Ev("recycle")]})
          and WL.valid({**GOOD, "waits": [Tm("2026-11-20")] * 8}) and not WL.valid({**GOOD, "waits": [Tm("2026-11-20")] * 9}), None)
    BAD = {
        "one line": {**GOOD, "waits": [Tm("2026-11-20")]}, "no lines": {**GOOD, "waits": []}, "not a list": {**GOOD, "waits": "x"}, "no waits": {k: v for k, v in GOOD.items() if k != "waits"},
        "unknown kind": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "soon"}]}, "a line that is no object": {**GOOD, "waits": [Tm("2026-11-20"), "a1"]},
        "time line, no date": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "time"}]}, "time line, not a date": {**GOOD, "waits": [Tm("2026-11-20"), Tm("soon")]},
        "anchor line, no event": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "anchor", "anchor": AURL}]}, "anchor line, no anchor": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "anchor", "event": "x"}]},
        "item line, no after": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "item"}]}, "item line, a list of items": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "item", "after": ["a1", "a2"]}]},
        "relay line, no event": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "relay"}]}, "event line, no event": {**GOOD, "waits": [Tm("2026-11-20"), {"kind": "event"}]},
        "no mode": {k: v for k, v in GOOD.items() if k != "wait_mode"}, "a mode that is neither": {**GOOD, "wait_mode": "some"}, "no backstop day": {k: v for k, v in GOOD.items() if k != "until"},
        "a backstop that is no date": {**GOOD, "until": "soon"}, "not stored as a list": {**GOOD, "wait_kind": "time"},
    }
    for what, meta in BAD.items():
        check(f"shape: not a list when it has {what}: no lines, not valid", not WL.valid(meta) and WL.lines(meta) == (), WL.problem(meta))
    check("shape: …and the problem says why (a stored list only)", "2 to 8" in WL.problem(BAD["one line"]) and "kind is one of" in WL.problem(BAD["unknown kind"]) and "needs" in WL.problem(BAD["time line, no date"]) and WL.problem(BAD["not stored as a list"]) == ""
          and "all or any" in WL.problem(BAD["a mode that is neither"]) and "backstop" in WL.problem(BAD["no backstop day"]), [WL.problem(v) for v in BAD.values()])
    check("shape: a line that carries an arrival is read with it; a torn record is no arrival", WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": 5.0, "what": "x"}}, It("a1")]})[0])
          and not WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": "no", "what": "x"}}, It("a1")]})[0]), None)
    HOSTILE_AT = (float("inf"), "inf", "Infinity", 1e20, 1e300, "1e400", 10 ** 400, 253402300800, WL.ARRIVED_AT_MAX + 1, float("nan"), -5.0, 0, True, None, [1.7e9])      # a time no date can show, or no time at all
    arr_of = lambda at: WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": at, "what": "x"}}, It("a1")]})[0]
    check("shape: an arrival whose time no date can show (inf, \"inf\", 1e20, 1e300, year 10000, nan, a huge integer, a bool, a negative) is no arrival: the line reads as open, with no time and no words",
          all(not WL.arrived(arr_of(at)) and arr_of(at)["arrived_at"] == 0.0 and arr_of(at)["arrived_what"] == "" for at in HOSTILE_AT) and WL.open_lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": float("inf"), "what": "x"}}, It("a1")]}) == [0, 1],
          [at for at in HOSTILE_AT if WL.arrived(arr_of(at))])
    check("shape: …a real time (a string number too, and the latest the shape allows) is an arrival; the first moment past the latest is not",
          all(WL.arrived(arr_of(at)) and arr_of(at)["arrived_at"] == float(at) for at in (1.7e9, "1.7e9", 1, WL.ARRIVED_AT_MAX)) and not WL.arrived(arr_of(WL.ARRIVED_AT_MAX + 1)) and WL.ARRIVED_AT_MAX < 253402300800, WL.ARRIVED_AT_MAX)
    check("shape: …every time the shape accepts can be drawn as a date in the board's zone (the latest one too), so a reader never has to guard it",
          all(isinstance(datetime.datetime.fromtimestamp(arr_of(at)["arrived_at"], datetime.timezone(datetime.timedelta(hours=14))).strftime("%Y-%m-%d %H:%M"), str) for at in (1, 1.7e9, WL.ARRIVED_AT_MAX)), None)
    LONG_ID = "a" + "9" * 1_000_000
    long_line = WL.lines({**GOOD, "waits": [Tm("2026-11-20"), It(LONG_ID)]})[1]
    check("shape: an item line's id is clipped like an anchor's or an event's (a stored line can be long, what a reader sees never is): LINE_MAX characters, and a normal id is untouched",
          len(long_line["after"]) == WL.LINE_MAX == 300 and long_line["after"] == LONG_ID[:300] and WL.lines(GOOD)[1]["after"] == "a1" and len(WL.line_text(long_line)) < 400
          and len(WL.lines({**GOOD, "waits": [Tm("2026-11-20"), An(AURL, "e" * 5000)]})[1]["event"]) == 300, len(long_line["after"]))

    # marks
    m0 = json.loads(json.dumps(GOOD)); alias = dict(m0)
    check("mark: a line arrives once, with its words and time; the list is copied (a shallow copy of the metadata keeps the source's lines)", WL.mark_arrived(m0, 1, "a1 closed", 100.0)
          and m0["waits"][1]["arrived"] == {"at": 100.0, "what": "a1 closed"} and "arrived" not in alias["waits"][1] and WL.arrived_lines(m0) == [1] and WL.open_lines(m0) == [0], m0)
    check("mark: …idempotent (an arrived line keeps its first time and words; nothing changes, False)", not WL.mark_arrived(m0, 1, "again", 200.0) and m0["waits"][1]["arrived"] == {"at": 100.0, "what": "a1 closed"}
          and not WL.mark_arrived(m0, 7, "x", 1.0) and not WL.mark_arrived(m0, -1, "x", 1.0), m0)
    check("mark: …the order of arrival is by time", (WL.mark_arrived(m0, 0, "date", 50.0), WL.arrived_lines(m0)) == (True, [0, 1]), WL.arrived_lines(m0))
    # the group's end
    allm = {**GOOD, "waits": [Tm("2026-11-20"), It("a1"), Re()]}; anym = {**allm, "wait_mode": "any"}
    check("done: all needs every line, any needs one; nothing arrived is not over; no list is never over",
          not WL.done(allm) and not WL.done(anym) and not WL.done({}) and not WL.done(BAD["one line"]), None)
    for mm in (allm, anym): WL.mark_arrived(mm, 1, "x", 10.0)
    check("done: …one arrived: any is over, all is not", WL.done(anym) and not WL.done(allm), None)
    for mm in (allm, anym): WL.mark_arrived(mm, 0, "y", 20.0); WL.mark_arrived(mm, 2, "z", 30.0)
    check("done: …every line arrived: both are over; the line that completed the group is the last to arrive", WL.done(allm) and WL.done(anym) and WL.completing_kind(allm) == "relay" and WL.completing_kind({**GOOD}) == "", WL.completing_kind(allm))
    # which lines an arrival is for
    two = {**GOOD, "waits": [It("a1"), It("a1"), It("a2"), An(AURL), An("github:o/r#5", "a review"), Ev("job_run nightly"), Ev("recycle")]}
    same = lambda a, b: a == b or a.replace("https://github.com/o/r/pull/", "github:o/r#") == b.replace("https://github.com/o/r/pull/", "github:o/r#")
    check("for: two lines on one item are both found, another item's line is not", WL.lines_for_item(two, "a1") == [0, 1] and WL.lines_for_item(two, "a2") == [2] and WL.lines_for_item(two, "a3") == [], None)
    check("for: two lines on one anchor (written two ways) are both found", WL.lines_for_anchor(two, AURL, same) == [3, 4] and WL.lines_for_anchor(two, "https://x/y", same) == [], None)
    check("for: an event line is found by the matcher it is given; a phrase the matcher raises on matches nothing", WL.lines_for_event(two, lambda ph: ph == "job_run nightly") == [5]
          and WL.lines_for_event(two, lambda ph: (_ for _ in ()).throw(ValueError("x"))) == [], None)
    WL.mark_arrived(two, 0, "x", 1.0)
    check("for: an arrived line is no longer open (open_only), and found with open_only False", WL.lines_for_item(two, "a1") == [1] and WL.lines_for_item(two, "a1", open_only=False) == [0, 1], None)
    check("for: the time lines whose date has come, and the first open relay line's event", WL.lines_for_time({**GOOD, "waits": [Tm("2026-11-20"), Tm("2026-12-20"), Re("the lease")]}, WL.backstop({"until": "2026-11-25"}) and _WT.wake_epoch("2026-11-25")) == [0]
          and WL.relay_event({**GOOD, "waits": [Tm("2026-11-20"), Re("the lease")]}) == "the lease" and WL.relay_event(GOOD) == "", None)
    # the scheduler
    NM = {**GOOD, "until": "2026-12-01", "waits": [Tm("2026-11-20"), Tm("2026-11-25"), It("a1")]}
    ep = _WT.wake_epoch
    check("next_moment: the earliest of the backstop and the open time lines (an item line is an event, not a moment)", WL.next_moment(NM) == ep("2026-11-20") and WL.next_moment({**NM, "until": "2026-11-10"}) == ep("2026-11-10")
          and WL.next_moment({**GOOD, "waits": [It("a1"), It("a2")]}) == ep("2026-12-01") and WL.next_moment({}) is None and WL.next_moment(BAD["one line"]) is None, WL.next_moment(NM))
    WL.mark_arrived(NM, 0, "d", 5.0)
    check("next_moment: …an arrived time line is no longer a moment", WL.next_moment(NM) == ep("2026-11-25"), WL.next_moment(NM))
    WL.mark_arrived(NM, 1, "d", 6.0); WL.mark_arrived(NM, 2, "i", 7.0)
    check("next_moment: …a group already over by what has arrived is due now (a pause, a crash or an edit left it)", WL.next_moment(NM, now=1234.0) == 1234.0 and abs(WL.next_moment(NM) - time.time()) < 5, WL.next_moment(NM, 1234.0))
    # words
    W3 = {**GOOD, "until": "2026-12-01", "waits": [Tm("2026-11-20"), It("a1"), Re("the lease")]}
    check("words: a line as a phrase (an item id as the caller shows it)", [WL.line_text(ln, lambda g: "#" + g) for ln in WL.lines(W3)] == ["the date 2026-11-20", "the close of #a1", "news of the lease"]
          and WL.line_text(WL.lines({**GOOD, "waits": [An(AURL), Ev("recycle")]})[0]) == f"a notice at {AURL} (PR merged)", None)
    w_all = json.loads(json.dumps(W3))
    for i, (what, at) in enumerate((("its date came", 1.0), ("a1 closed", 2.0), ("the lease was relayed", 3.0))): WL.mark_arrived(w_all, i, what, at)
    w_any = {**json.loads(json.dumps(W3)), "wait_mode": "any"}; WL.mark_arrived(w_any, 1, "a1 closed", 2.0)
    w_bs = json.loads(json.dumps(W3)); WL.mark_arrived(w_bs, 0, "its date came", 1.0)
    check("words: all → \"all 3 arrived: a; b; c\"", WL.outcome_text(w_all, "relay") == "all 3 arrived: its date came; a1 closed; the lease was relayed", WL.outcome_text(w_all, "relay"))
    check("words: any → \"any of 3 arrived: a; not needed: b; c\" (nothing left: no `not needed`)", WL.outcome_text(w_any, "item") == "any of 3 arrived: a1 closed; not needed: the date 2026-11-20; news of the lease"
          and WL.outcome_text({**w_any, "waits": w_any["waits"][:2]}, "item").endswith("; not needed: the date 2026-11-20")
          and WL.outcome_text({**w_any, "waits": [w_any["waits"][1], {**w_any["waits"][0], "arrived": {"at": 9.0, "what": "d"}}]}, "item") == "any of 2 arrived: a1 closed; d", WL.outcome_text(w_any, "item"))
    w_bs2 = json.loads(json.dumps(W3)); WL.mark_arrived(w_bs2, 0, "its date came", 1.0); WL.mark_arrived(w_bs2, 1, "a1 closed", 2.0)
    check("words: the backstop day with the group not over → \"backstop day D: arrived a; b; still open: c; d\" (both lists joined with \"; \"), and with nothing arrived", WL.outcome_text(w_bs, "backstop") == "backstop day 2026-12-01: arrived its date came; still open: the close of a1; news of the lease"
          and WL.outcome_text(w_bs2, "backstop") == "backstop day 2026-12-01: arrived its date came; a1 closed; still open: news of the lease"
          and WL.outcome_text(W3, "backstop") == "backstop day 2026-12-01: nothing had arrived; still open: the date 2026-11-20; the close of a1; news of the lease", WL.outcome_text(W3, "backstop"))
    check("words: the summary", WL.summary(w_bs) == "3 waits, all: the date 2026-11-20 (arrived); the close of a1; news of the lease; backstop day 2026-12-01" and WL.summary({}) == "", WL.summary(w_bs))
    check("words: watchers.what_list is the same text (the message to the mover carries it)", wk.what_list(w_bs, "backstop") == WL.outcome_text(w_bs, "backstop"), None)

    # ================================================================ watchers: the pure readings
    LI = lambda **m: {"status": "open", "metadata": {"wait_kind": "list", "wait_mode": "all", "until": day(5), "waits": [Tm(day(3)), It("a1")], **m}}
    check("watchers: a stored list is a kind (a malformed one is ignored: the date alone, or none) and is watched always (the backstop day is its end)",
          wk.stored_kind(LI()["metadata"]) == "list" and "list" in model.WAIT_KINDS and wk.can_end(LI()["metadata"]) and wk.watches(LI())
          and wk.stored_kind({**LI()["metadata"], "waits": [Tm(day(3))]}) == "time" and wk.stored_kind({k: v for k, v in LI()["metadata"].items() if k != "until"} | {"waits": []}) == ""
          and not wk.watches({"status": "open", "metadata": {"wait_kind": "list"}}) and wk.stored_kind({"wait_kind": "relay"}) == "relay", None)
    check("watchers: due → the backstop day when it has come; nothing before; a group over by what has arrived is due with the kind of the line that completed it",
          wk.due(LI(until=day(-1)), now0) == "backstop" and wk.due(LI(), now0) == "" and wk.due({**LI(), "metadata": {**LI()["metadata"], "wait_mode": "any", "waits": [{**Tm(day(3)), "arrived": {"at": 5, "what": "x"}}, It("a1")]}}, now0) == "time", None)
    check("watchers: next_moment → the earliest of the backstop and the open time lines; a turn that failed is looked at again after the back-off",
          wk.next_moment(LI()["metadata"]) == wk.day_epoch(day(3)) and wk.next_moment({**LI()["metadata"], "until": day(2)}) == wk.day_epoch(day(2))
          and wk.next_moment({**LI()["metadata"], "until": day(-2), "watch": {"failed_at": now0}}) == now0 + wk.BACKOFF, wk.next_moment(LI()["metadata"]))
    check("watchers: a list has no chases (a list is not a chased wait)", not wk.chased_out({**LI()["metadata"], "chases": [{"at": 1}, {"at": 2}, {"at": 3}]}) and "list" not in wk.CHASE_KINDS, None)
    check("watchers: what a clear of the wait drops names waits and wait_mode (the one list: WAIT_GROUP; the end of a wait, a close, a date alone, what a put-back keeps)",
          all(f in model.WAIT_GROUP and f in model.MODEL_FIELDS and f in model.DROP_ON_CLOSE and f in wk.LIVE_DROP and f in wk.DATE_DROP and f in wk.WAS_FIELDS for f in ("waits", "wait_mode")), None)
    check("seams: the lists of wait fields name waits and wait_mode (the re-park fields, the wait's structure, the write guards' state fields, the wake hint's fields), and the migration's set fields do NOT (nothing migrates a list)",
          all(f in gates._REPARK_FIELDS and f in gates._WAIT_STRUCTURE and f in model_guards.STATE_FIELDS and f in migsvc.WAKE_FIELD_KEYS for f in ("waits", "wait_mode"))
          and not any(f in migration.OPEN_SET_FIELDS or f in migration.SET_FIELDS for f in ("waits", "wait_mode")), None)
    sig = lambda **m: gates._struct_sig({"wait_kind": "list", **m})
    base_ = {"wait_mode": "all", "waits": [Tm(day(3)), It("a1")]}
    check("seams: a changed list is a new wait shape; a line arriving, a reorder and a single wait's signature are not",
          sig(**base_) != sig(**{**base_, "waits": [Tm(day(3)), It("a2")]}) and sig(**base_) != sig(**{**base_, "waits": [Tm(day(3)), It("a1"), It("a2")]}) and sig(**base_) != sig(**{**base_, "wait_mode": "any"})
          and sig(**base_) == sig(**{**base_, "waits": [{**Tm(day(3)), "arrived": {"at": 1, "what": "x"}}, It("a1")]}) and sig(**base_) == sig(**{**base_, "waits": [It("a1"), Tm(day(3))]})
          and gates._struct_sig({"wait_kind": "item", "after": ["a1"]}) == json.dumps(["item", "", "", ["a1"]]), (sig(**base_), gates._struct_sig({"wait_kind": "item", "after": ["a1"]})))
    sub = lambda **m: gates._substance({"status": "open", "metadata": {"wait_kind": "list", **m}})
    cfg(guards=True)
    check("seams: the re-park test ignores the server's record of what arrived and sees a changed line", sub(**base_) == sub(**{**base_, "waits": [{**Tm(day(3)), "arrived": {"at": 1, "what": "x"}}, It("a1")]}) and sub(**base_) != sub(**{**base_, "waits": [Tm(day(4)), It("a1")]}), None)
    cfg(guards=False)
    check("seams: a caller still cannot pass wait_kind=list (the five kinds are what a write names)", "wait_kind is one of time | anchor | item | relay | event (got 'list')" in model.check_fields({"wait_kind": "list"})[0]
          and model.check_fields({"wait_kind": "event"}) == [] and model.SINGLE_KINDS == ("time", "anchor", "item", "relay", "event"), model.check_fields({"wait_kind": "list"}))

    # ================================================================ the model
    lst(100, [Tm(day(3)), It("a901"), Re("the lease")], mode="all", until=day(9))
    item(901, subject="[home] a blocker")
    def mod_of(i, **kw): return _item_read._model_of({**rd(i), "gid": f"a{i}", **kw})
    u0 = model.UNSTAMPED["count"]
    md = mod_of(100)
    check("model: wait_kind=list reads as a waiting item with a wait of that kind: the backstop is the item's `until`, the mover is the post-wake mover", md.state == "waiting" and md.wait.kind == "list" and md.wait.backstop == day(9) and md.wait.by_until
          and md.wait.mover == BACK and not md.wait.due and md.wait.after == () and md.wait.event == "" and md.wait.anchor == "", md)
    check("model: …with its lines (kind, fields, none arrived) and its mode", [(w.kind, w.until, w.after, w.event, w.arrived) for w in md.waits] == [("time", day(3), "", "", False), ("item", "", "a901", "", False), ("relay", "", "", "the lease", False)]
          and md.wait_mode == "all" and isinstance(md.waits[0], model.WaitLine) and not md.conflicts, (md.conflicts, md.wait_mode))
    check("model: …and words for get: the list, its mode, its lines and the backstop", model.words(md).startswith("model: waiting on several things (all of 3, 0 arrived: [ ] the date " + day(3) + "; [ ] the close of a901; [ ] news of the lease; until " + day(9) + ") · mover " + BACK), model.words(md))
    check("model: a wait is `due` when the backstop day has passed or the group is over by what has arrived", not md.wait.due and model.derive({**rd(100), "metadata": {**mt(100), "until": day(-1)}}).wait.due
          and model.derive({**rd(100), "metadata": {**mt(100), "wait_mode": "any", "waits": [{**Tm(day(3)), "arrived": {"at": 5, "what": "x"}}, It("a901"), Re()]}}).wait.due, None)
    check("model: KIND_WORDS says what the kind is", model.KIND_WORDS["list"] == "several things", None)
    lst(101, [Tm(day(3))], mode="all"); mt101 = mt(101)
    c0 = WL.MALFORMED["count"]
    mm = mod_of(101)
    check("model: a list that does not hold is IGNORED: the item reads as it would without it (the date alone), with a model note, counted", mm.state == "waiting" and mm.wait.kind == "time" and mm.wait.until == day(9) and mm.waits == () and mm.wait_mode == ""
          and any("does not hold" in c and "2 to 8" in c for c in mm.conflicts) and WL.MALFORMED["count"] == c0 + 1, (mm, WL.MALFORMED))
    mod_of(101); check("model: …each read of it is counted", WL.MALFORMED["count"] == c0 + 2, WL.MALFORMED)
    lst(102, [Tm(day(3)), "junk"], mode="soon"); nm = mod_of(102)
    check("model: …a line that is no line, a mode that is neither: the same, never a crash", nm.wait.kind == "time" and nm.waits == () and len(nm.conflicts) == 1, nm)
    item(103, wait_kind="time", hold=True, wake=day(5), needs=[], post_wake_mover=BACK, subject="[home] a single wait")
    sm = mod_of(103); c1 = WL.MALFORMED["count"]
    check("model: a single wait reads as it did (no lines, no mode, no note, nothing counted)", sm.wait.kind == "time" and sm.waits == () and sm.wait_mode == "" and sm.conflicts == () and WL.MALFORMED["count"] == c1
          and "several" not in model.words(sm), sm)
    item(104, wait_kind="item", hold=True, after=["a901"], wake=day(5), needs=[], post_wake_mover=BACK, subject="[home] a single item wait")
    check("model: …nor an item wait that stores a `waits` it does not use", mod_of(104).wait.kind == "item" and model.derive({**rd(104), "metadata": {**mt(104), "waits": [Tm(day(3)), It("a1")]}}).wait.kind == "item", None)
    check("model: the stored kind of a stamped item accepts list (a waits_on outside the six is half a pair, as before)", model.stored_waits_on({"status": "open", "metadata": {"waits_on": "list"}}) == "list"
          and model.stored_waits_on({"status": "open", "metadata": {"waits_on": "soon"}}) == "", None)
    # the stamp
    it = rd(100); stamp_svc._phase_stamp("a100", it)
    check("stamp: the save's stamp writes phase waiting and waits_on list", it["metadata"].get("phase") == "waiting" and it["metadata"].get("waits_on") == "list", it["metadata"])
    v1 = model.view({**it, "gid": "a100"}, mod_of(100), after_open=lambda i_: [])
    check("stamp: …and the board's reading of the stamped item is the list, with its lines", v1.wait.kind == "list" and len(v1.waits) == 3 and model.shown_pair(v1) == ("waiting", "list"), v1)
    check("stamp: …a stored list the fields no longer hold is not drawn as a list with no lines", model.view({**it, "metadata": {**it["metadata"], "waits": [Tm(day(3))]}, "gid": "a100"}, model.derive({**it, "metadata": {**it["metadata"], "waits": [Tm(day(3))]}}), after_open=lambda i_: []).wait.kind == "time", None)
    lst(105, [Tm(day(3)), It("a901")], mode="any"); put(105, {**rd(105)})
    sw = stamp_svc._phase_sweep()
    check("stamp: the sweep stamps every open list item waiting on a list, and a second sweep changes nothing", "a105" in sw and mt(105).get("phase") == "waiting" and mt(105).get("waits_on") == "list" and mt(100).get("waits_on") == "list" and stamp_svc._phase_sweep() == [], (sw, mt(105)))
    check("stamp: …the stamped pair is what the board reads (stored first), and a sweep restamps a list edited down to one line", model.stored_waits_on(rd(105)) == "list", None)
    d5 = rd(105); d5["metadata"]["waits"] = d5["metadata"]["waits"][:1]; put(105, d5)
    check("stamp: …(the one line does not hold: the sweep finds the stored list outdated and restamps the date alone)", "a105" in stamp_svc._phase_sweep() and mt(105).get("waits_on") == "time", mt(105))
    lst(105, [Tm(day(3)), It("a901")], mode="any")

    # ================================================================ time lines: the clock marks them, the group decides
    reset()
    lst(110, [Tm(day(-1)), Tm(day(4))], mode="all")
    woke = wakes_svc.wake_pass()
    check("time (all): a line whose date has passed is marked arrived, the other is not; the item still waits and nobody is told", "a110" not in woke and arrived_of(110) == [True, False] and mt(110).get("wait_kind") == "list" and not mt(110).get("mover") and not sent("watch"), mt(110))
    check("time (all): …with a History line `arrived: <what> (1 of 2)` and the item's own clock moved, not its state clock", notes_of("a110") == [f"arrived: its date {day(-1)} came (1 of 2)"] and rd(110)["state_updated"] < now0 - 9 * DAY and rd(110)["updated"] >= now0, notes_of("a110"))
    check("time (all): …the model reads the item as still waiting on a list, one line arrived", mod_of(110).state == "waiting" and mod_of(110).waits[0].arrived and not mod_of(110).waits[1].arrived and mod_of(110).waits[0].arrived_what == f"its date {day(-1)} came", mod_of(110).waits)
    b110 = raw(110); reset(); wakes_svc.wake_pass()
    check("time (all): the next pass changes nothing (the marked line keeps its first time)", raw(110) == b110 and not NOTES and not sent(), notes_of("a110"))
    check("time (all): the next moment is the line still open (the arrived one is no moment)", wk.next_moment(mt(110)) == wk.day_epoch(day(4)), wk.next_moment(mt(110)))
    d = rd(110); d["metadata"]["waits"][1]["until"] = day(-1); put(110, d)
    reset(); woke = wakes_svc.wake_pass(); m = mt(110)
    check("time (all): the last line's date passing turns the item alive with the post-wake mover, on the cause of the completing line", "a110" in woke and m.get("mover") == BACK and m.get("needs") == [BACK] and "all 2 arrived" in m["woke"]["what"]
          and m["woke"]["what"].count(f"its date {day(-1)} came") == 2 and m["woke"]["to"] == BACK, m)
    check("time (all): …the wait's fields are gone with the wait: the list, its mode, the kind, the backstop and the post-wake mover", all(k not in m for k in GONE) and "watch" not in m or all(k not in m.get("watch", {}) for k in ("asked", "was")), m)
    check("time (all): …the mover is told in one line what arrived", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "is yours now: all 2 arrived:" in sent("watch")[0][2] and "\n" not in sent("watch")[0][2], sent())
    check("time (all): …the History line says the item woke, with what arrived", any(n.startswith("woke: all 2 arrived:") and n.endswith(f"→ {BACK}") for n in notes_of("a110")), notes_of("a110"))
    check("time (all): …the model reads it as alive, no conflicts, and nothing is left to watch", mod_of(110).state == "alive" and mod_of(110).mover == BACK and not mod_of(110).conflicts and not wk.watches(rd(110)), mod_of(110))
    reset(); wakes_svc.wake_pass(); check("time (all): …a later pass tells nobody again", not sent() and not notes_of("a110"), sent())
    # any
    reset()
    lst(111, [Tm(day(-1)), Tm(day(6)), It("a901")], mode="any")
    woke = wakes_svc.wake_pass(); m = mt(111)
    check("time (any): the first line to arrive ends the group: alive with the post-wake mover, what arrived and what was not needed", "a111" in woke and m.get("mover") == BACK and m["woke"]["what"] == f"any of 3 arrived: its date {day(-1)} came; not needed: the date {day(6)}; the close of {_gh.shown('a901')}", m)
    check("time (any): …the wait's fields are gone", all(k not in m for k in GONE), m)
    check("time (any): …the message to the mover carries it", len(sent("watch")) == 1 and "any of 3 arrived:" in sent("watch")[0][2] and "; not needed: " in sent("watch")[0][2], sent())

    # ================================================================ item lines
    reset()
    lst(120, [It("a121"), It("a122"), Tm(day(7))], mode="all")
    item(121, subject="[home] first blocker"); item(122, subject="[home] second blocker")
    close(121)
    check("item (all): a closed item marks its line; the item waits on, nobody is told", arrived_of(120) == [True, False, False] and mt(120).get("wait_kind") == "list" and not sent("watch")
          and notes_of("a120") == [f"arrived: {_gh.shown('a121')} closed (done) by home-front (1 of 3)"], (mt(120), notes_of("a120")))
    b120 = raw(120); reset(); close(121)
    check("item: the same close delivered again changes nothing (idempotent), writes nothing", raw(120) == b120 and not NOTES and not sent(), notes_of("a120"))
    close(122)
    check("item (all): the second close marks the second line; the time line is still open, so the item waits on", arrived_of(120) == [True, True, False] and mt(120).get("wait_kind") == "list" and not sent("watch"), mt(120))
    d = rd(120); d["metadata"]["waits"][2]["until"] = day(-1); put(120, d); reset(); woke = wakes_svc.wake_pass()
    check("item (all): the last arrival (the clock, here) turns it with all three in the words", "a120" in woke and mt(120).get("mover") == BACK and mt(120)["woke"]["what"].startswith("all 3 arrived:") and "closed (done)" in mt(120)["woke"]["what"], mt(120))
    # any, one close
    reset()
    lst(123, [It("a124"), Re("the quote")], mode="any"); item(124, subject="[home] the one blocker")
    close(124, "dropped")
    m = mt(123)
    check("item (any): a close ends the group at once: alive with the post-wake mover, dropped said so", m.get("mover") == BACK and "was dropped" in m["woke"]["what"] and "not needed: news of the quote" in m["woke"]["what"]
          and all(k not in m for k in GONE) and len(sent("watch")) == 1 and "was dropped" in sent("watch")[0][2], m)
    # two lines on one item
    reset()
    lst(125, [It("a126"), It("a126"), It("a127")], mode="all"); item(126); item(127)
    close(126)
    check("item: two lines on one item are both marked by one close", arrived_of(125) == [True, True, False] and len(notes_of("a125")) == 1 and "(2 of 3)" in notes_of("a125")[0] and notes_of("a125")[0].count("arrived:") == 2, (arrived_of(125), notes_of("a125")))
    # superseded followed
    reset()
    lst(128, [It("a129"), Re("x")], mode="any"); item(129, subject="[home] old"); item(130, subject="[home] the replacement")
    it = rd(129); it["status"] = "completed"; it["metadata"].update(outcome="superseded", reason="r", superseded_by="a130"); put(129, it)
    wakes_svc.release_after("a129", "superseded", "a130", "home-front")
    check("item: a superseded item is followed to its open replacement: the id in the line is replaced and the line has not arrived; the item waits on", mt(128)["waits"][0]["after"] == "a130" and arrived_of(128) == [False, False] and mt(128).get("wait_kind") == "list" and not sent("watch")
          and notes_of("a128") == [f"{_gh.ref('a129')} was superseded, followed to {_gh.ref('a130')}"], (mt(128), notes_of("a128")))
    close(130)
    check("item: …and the replacement's close then ends it", mt(128).get("mover") == BACK and "a130" not in str(mt(128).get("waits")) and f"{_gh.shown('a130')} closed (done)" in mt(128)["woke"]["what"], mt(128))
    # superseded with a closed replacement
    reset()
    lst(131, [It("a132"), Re("x")], mode="any"); item(132, subject="[home] old two"); item(133, status="completed", outcome="done", reason="r", needs=[], subject="[home] a replacement already closed")
    it = rd(132); it["status"] = "completed"; it["metadata"].update(outcome="superseded", reason="r", superseded_by="a133"); put(132, it)
    wakes_svc.release_after("a132", "superseded", "a133", "home-front")
    check("item: a superseded item whose replacement is closed too marks the line (nothing to follow)", mt(131).get("mover") == BACK and "was superseded by" in mt(131)["woke"]["what"] and "closed too" in mt(131)["woke"]["what"], mt(131).get("woke"))
    # a close nobody saw, a missing file
    reset()
    lst(134, [It("a135"), It("a999"), Re("x")], mode="all"); item(135, status="completed", outcome="done", reason="r", needs=[], subject="[home] closed before")
    woke = wakes_svc.wake_pass()
    check("item: a close nobody saw (the item is already closed) and an item with no file both count as closed: the clock's pass marks both lines", arrived_of(134) == [True, True, False] and mt(134).get("wait_kind") == "list" and "a134" not in woke, (arrived_of(134), mt(134)))
    check("item: …(the relay line is still open)", len(notes_of("a134")) == 1 and notes_of("a134")[0].count("arrived:") == 2 and "(2 of 3)" in notes_of("a134")[0], notes_of("a134"))
    lst(136, [It("a135"), Tm(day(5))], mode="any"); reset(); woke = wakes_svc.wake_pass()
    check("item (any): a catch-up finds the close and ends the group", "a136" in woke and mt(136).get("mover") == BACK, mt(136))
    # a closed superseded item found by the clock is followed too
    lst(137, [It("a138"), Re("x")], mode="any"); item(138, status="completed", outcome="superseded", superseded_by="a139", reason="r", needs=[], subject="[home] superseded, found later"); item(139, subject="[home] open replacement")
    wakes_svc.wake_pass()
    check("item: the clock's catch-up follows a superseded item to its open replacement too", mt(137)["waits"][0]["after"] == "a139" and arrived_of(137) == [False, False] and mt(137).get("wait_kind") == "list", mt(137))

    # ================================================================ anchor lines
    reset()
    lst(140, [An(AURL, "PR merged"), An(AURL2, "a reply")], mode="all", project="projects/alpha")
    lst(141, [An(AURL, "PR merged"), Tm(day(7))], mode="any", project="projects/beta")
    lst(142, [An(AURL, "a reply"), An("github:o/r#5", "a review"), Re("x")], mode="all")
    wakes_svc.anchor_release("projects/alpha", notice("old comment", ts=now0 - 20 * DAY))
    check("anchor: a notice older than the wait does not count", arrived_of(140) == [False, False] and arrived_of(142) == [False, False, False], mt(140))
    wakes_svc.anchor_release("projects/alpha", notice("CI passed on the PR", log_only=True, ruled_by=released_svc.AUTO_RULER, ruling="merged", to=""))
    check("anchor: a routine line of the fleet's own PR does not end a line that waits for a merge (as for a single wait); a line waiting for a reply counts it", arrived_of(140) == [False, False] and arrived_of(142) == [True, True, False], (arrived_of(140), arrived_of(142)))
    reset()
    wakes_svc.anchor_release("projects/alpha", notice("dropped by the keeper", ruling="dropped"))
    check("anchor: a notice the keeper dropped does not count", arrived_of(140) == [False, False], None)
    rel = wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged: the work landed"), by="home-stew")
    check("anchor (all): a notice the keeper passed marks the line that answers it; another anchor's line and another project's item are not touched; nobody is told yet", arrived_of(140) == [True, False] and mt(140).get("wait_kind") == "list" and arrived_of(141) == [False, False] and "a140" not in rel and not sent("watch")
          and f"(1 of 2)" in notes_of("a140")[0] and "github:o/r#5" in notes_of("a140")[0] and "PR #5 merged" in notes_of("a140")[0], (arrived_of(140), notes_of("a140")))
    check("anchor: two lines on one anchor (the same anchor written two ways) are both marked by one notice", arrived_of(142) == [True, True, False], None)
    b140 = raw(140); reset()
    wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged again", ts=now0 + 5, ruled_at=now0 + 5))
    check("anchor: a second notice on an anchor whose line has arrived changes nothing", raw(140) == b140 and not NOTES, notes_of("a140"))
    rel = wakes_svc.anchor_release("projects/alpha", notice("PR #6 merged", anchor="github:o/r#6"), by="home-stew")
    m = mt(140)
    check("anchor (all): the last line's notice turns it alive with the post-wake mover, the cause the anchor", rel == ["a140"] and m.get("mover") == BACK and m["woke"]["what"].startswith("all 2 arrived:") and "PR #5 merged" in m["woke"]["what"] and "PR #6 merged" in m["woke"]["what"] and all(k not in m for k in GONE), (rel, m))
    check("anchor: …and the mover is told", len(sent("watch")) == 1 and sent("watch")[0][1] == UB, sent())
    reset()
    rel = wakes_svc.anchor_release("projects/beta", notice("PR #5 merged", ruling=None, to="", live=True), by="")
    check("anchor (any): in a project nobody rules, a notice that arrived ends an `any` list on it at once", "a141" in rel and mt(141).get("mover") == BACK and "any of 2 arrived:" in mt(141)["woke"]["what"], (rel, mt(141)))
    # the minute pass finds a notice in the routing log
    lst(143, [An(AURL, "a reply"), Re("x")], mode="any")
    _routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="a reply on the PR", anchor="github:o/r#5", pilot=True)
    nid = _routing.read("projects/alpha", since=now0 - 60)[-1]["id"]
    _routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
    time.sleep(0.01); out = wakes_svc.anchor_pass()
    check("anchor: the minute pass finds a keeper-passed notice in the routing log for an item whose list waits on the anchor", "a143" in out and mt(143).get("mover") == BACK, (out, mt(143)))
    lst(144, [An(AURL2, "a reply"), Re("x")], mode="any", watch={})
    wakes_svc.anchor_pass()
    check("anchor: …and gives a list that has no stamp one (a notice from the days it already waited through is not its arrival)", mt(144).get("watch", {}).get("set_at", 0) >= now0 and arrived_of(144) == [False, False], mt(144))

    # ================================================================ event lines
    reset()
    lst(150, [Ev("job_run nightly"), Ev("recycle"), It("a901")], mode="all")
    lst(151, [Ev("job_run nightly"), Re("x")], mode="any")
    rep = lambda **kw: EW.event(**kw)
    got = evwaits_svc.evwait_report(EW.event("job_run", name="other"))
    check("event: an event no line answers marks nothing", got == [] and arrived_of(150) == [False, False, False] and arrived_of(151) == [False, False], None)
    got = evwaits_svc.evwait_report(EW.event("job_run", name="nightly", what="the nightly job ran"))
    check("event (any): an event that answers a line ends an `any` list; (all) it marks the line and waits for the rest", got == ["a151"] and mt(151).get("mover") == BACK and "any of 2 arrived: the nightly job ran" in mt(151)["woke"]["what"]
          and arrived_of(150) == [True, False, False] and mt(150).get("wait_kind") == "list" and len(notes_of("a150")) == 1 and "(1 of 3)" in notes_of("a150")[0], (got, mt(151), arrived_of(150)))
    b150 = raw(150); reset(); got = evwaits_svc.evwait_report(EW.event("job_run", name="nightly"))
    check("event: the same event reported again changes nothing", got == [] and raw(150) == b150 and not NOTES, notes_of("a150"))
    evwaits_svc.evwait_report(EW.event("recycle", machine="testbox")); close(901)
    check("event + item (all): every line arrived (an event, an event, a close): the group ends on the last, of mixed kinds", mt(150).get("mover") == BACK and mt(150)["woke"]["what"].startswith("all 3 arrived:") and "the close of" not in mt(150)["woke"]["what"], mt(150))
    # an old reported event is not a wait's arrival
    lst(152, [Ev("fleet_op many"), Re("x")], mode="any", state_updated=None)
    d = rd(152); d["state_updated"] = now0 + 3600; put(152, d)
    check("event: a reported event older than the wait (the item's last move) is not an arrival", evwaits_svc.evwait_report(EW.event("fleet_op", verb="lane", sessions=3)) == [] and arrived_of(152) == [False, False], mt(152))
    # the pollers look for event lines as they do for an event wait
    lst(153, [Ev("box_online testbox"), Ev("pr_merged o/r#77"), Re("x")], mode="any")
    specs = evwaits_svc.event_specs(rd(153) | {"gid": "a153"})
    check("event: the catch-up pollers find the event lines of a list (the machine and the pull request), and an arrived line is no longer looked for", [(s.kind, s.key or s.machine) for s in specs] == [("box_online", "testbox"), ("pr_merged", "o/r#77")]
          and [s.kind for s in evwaits_svc.event_specs({**rd(153), "metadata": {**mt(153), "waits": [{**mt(153)["waits"][0], "arrived": {"at": 1, "what": "x"}}, *mt(153)["waits"][1:]]}})] == ["pr_merged"]
          and [s.kind for s in evwaits_svc.event_specs({**rd(100), "gid": "a100"})] == [] and evwaits_svc.event_specs({**rd(10), "gid": "a10"} if (T / "store/a/10.json").exists() else {"metadata": {}}) == [], specs)

    # ================================================================ relay lines and the write path's mark
    reset()
    lst(160, [Re("the lease"), It("a901x")], mode="all"); item("901x", subject="[home] a blocker for the relay list")
    d = rd(160); d["metadata"]["waits"][1]["after"] = "a901x"; put(160, d)
    check("relay: a relay line has no detector: nothing the server sees marks it", evwaits_svc.evwait_report(EW.event("recycle")) == [] and wakes_svc.wake_pass() == [] and arrived_of(160) == [False, False], None)
    out_ = {}
    turned = watching_svc.watch_mark("a160", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "the owner relayed the lease")
    check("relay: the write path marks it (watchers' seam: a line, the words, the cause); under `all` the item waits on", turned is False and arrived_of(160) == [True, False] and mt(160).get("wait_kind") == "list" and not out_, (turned, mt(160)))
    close("901x")
    check("relay: …and the last line arriving ends the group on the cause of that line", mt(160).get("mover") == BACK and mt(160)["woke"]["what"].startswith("all 2 arrived: the owner relayed the lease;"), mt(160))
    lst(161, [Re("the lease"), Tm(day(6))], mode="any"); out_ = {}
    check("relay (any): the relay line arriving is an arrival, not a question: the item goes to its post-wake mover", watching_svc.watch_mark("a161", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "the owner relayed the lease") is True
          and mt(161).get("mover") == BACK and mt(161).get("needs") == [BACK] and "ask" not in mt(161) and [x for rows in out_.values() for x in rows], mt(161))
    check("relay: a second delivery of the same mark changes nothing, and an item already turned is not turned again", watching_svc.watch_mark("a161", "relay", time.time(), {}, lambda m_: [0], "again") is False, None)

    # ================================================================ mixed kinds, the group ends on the last
    reset()
    lst(170, [Tm(day(-1)), It("a171"), An(AURL2, "a reply"), Ev("job_run weekly"), Re("x")], mode="all")
    item(171, subject="[home] a blocker in a mixed list")
    woke = wakes_svc.wake_pass()
    check("mixed: five lines, five kinds: the clock marks the time line", arrived_of(170) == [True, False, False, False, False], None)
    close(171)
    wakes_svc.anchor_release("projects/alpha", notice("a reply came", anchor="github:o/r#6"), by="home-stew")
    evwaits_svc.evwait_report(EW.event("job_run", name="weekly"))
    check("mixed: …an item, an anchor and an event each mark their line; the item still waits, nobody is told", arrived_of(170) == [True, True, True, True, False] and mt(170).get("wait_kind") == "list" and not sent("watch"), arrived_of(170))
    watching_svc.watch_mark("a170", "relay", time.time(), {}, lambda m_: WL.lines_by_kind(m_, "relay"), "he relayed x")
    check("mixed: …the relay line, the last, ends it", mt(170).get("mover") == BACK and mt(170)["woke"]["what"].startswith("all 5 arrived:") and all(k not in mt(170) for k in GONE) and "hold" not in mt(170), mt(170))

    # the marks are made, and the group ended, on the item as it stands under the lock: an item that no longer stores a list, an event older than the wait, and a group that is not due are left as they are
    reset()
    lst(172, [Ev("job_run weekly"), Re("x")], mode="any"); item(173, subject="[home] a single time wait that replaced a list", wait_kind="time", hold=True, wake=day(5), needs=[], post_wake_mover=BACK, watch={"set_at": now0 - 3600})
    lst(174, [Tm(day(5)), Re("y")], mode="all")
    b172, b173, b174 = raw(172), raw(173), raw(174)
    old_ev = EW.event("job_run", name="weekly")
    check("under the lock: an event dated before the wait was set (its floor) marks no line", watching_svc.watch_mark("a172", "event", now0 - 7200, {}, lambda m_: WL.lines_by_kind(m_, "event"), "weekly ran", ev=old_ev) is False and raw(172) == b172, mt(172))
    check("under the lock: …an item that no longer stores a list (a single wait now) marks nothing and is not touched", watching_svc.watch_mark("a173", "relay", now0, {}, lambda m_: [0], "x") is False and raw(173) == b173, mt(173))
    check("under the lock: …a group that is not due is not ended (the wait is read again: its cause is not the one the caller saw)", watching_svc.watch_fire("a174", "time", now0, {}, recheck=True) is False and raw(174) == b174, mt(174))
    check("under the lock: …the same event dated after the wait was set marks its line and, in an `any` list, ends it", watching_svc.watch_mark("a172", "event", now0, {}, lambda m_: WL.lines_by_kind(m_, "event"), "weekly ran", ev=old_ev) is True and mt(172).get("mover") == BACK, mt(172))

    # ================================================================ the backstop day
    reset()
    lst(180, [Tm(day(5)), It("a181"), An(AURL, "x")], mode="all", until=day(-1)); item(181, subject="[home] never closes")
    woke = wakes_svc.wake_pass(); m = mt(180)
    check("backstop (no relay line): the backstop day turns the item alive to the post-wake mover whatever has arrived, saying what had and what is still open", "a180" in woke and m.get("mover") == BACK and m["woke"]["what"].startswith(f"backstop day {day(-1)}: nothing had arrived; still open: ") and "the close of" in m["woke"]["what"]
          and all(k not in m for k in GONE) and "ask" not in m, m)
    check("backstop: …the mover is told", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "backstop day" in sent("watch")[0][2], sent())
    reset()
    lst(182, [It("a183"), Tm(day(-3)), An(AURL, "x")], mode="all", until=day(-1)); item(183, status="completed", outcome="done", reason="r", needs=[], subject="[home] closed")
    wakes_svc.wake_pass(); m = mt(182)
    check("backstop: lines that arrived are said as arrived (the item and time lines here), the anchor line is still open", m.get("mover") == BACK and "arrived" in m["woke"]["what"] and "still open: a notice at " + AURL in m["woke"]["what"] and m["woke"]["what"].startswith(f"backstop day {day(-1)}:"), m.get("woke"))
    # with an open relay line
    reset()
    lst(184, [Tm(day(-2)), Re("the lease"), It("a185")], mode="all", until=day(-1), then="home-other"); item(185, subject="[home] open")
    woke = wakes_svc.wake_pass(); m = mt(184)
    check("backstop (open relay line): the owner is asked, as a relay's ask-by day asks: the fixed question about the relay line's event, three options, the post-wake mover as `then`", "a184" in woke and m.get("needs") == ["decision"]
          and m.get("ask") == "Decide: has the lease arrived? · Options: arrived / ask again in a week, two weeks or a month / not yet, ask again on <date> / drop" and [o["label"] for o in m["options"]][0::5] == ["arrived", "drop"] and len(m["options"]) == 6 and m.get("then") == BACK and "mover" not in m, m)
    check("backstop (open relay line): …the words of what arrived and what did not are on the item, nobody is messaged, and the wait is put by", m["woke"]["to"] == OWN and m["woke"]["what"].startswith(f"backstop day {day(-1)}: arrived ") and "still open" in m["woke"]["what"] and not sent("watch")
          and all(k not in m for k in GONE) and m["watch"]["was"]["wait_kind"] == "list" and len(m["watch"]["was"]["waits"]) == 3 and m["watch"]["was"]["waits"][0].get("arrived"), m)
    check("backstop (open relay line): …the model reads it as the owner's move", mod_of(184).owner_moves, mod_of(184))
    out = answer_svc._answer("a184", "not yet, ask again on <date>", f"ask again on {day(10)}", "answer"); m = mt(184)
    check("backstop (open relay line): `not yet` with a date puts the list back: its lines (what had arrived stays), mode and post-wake mover, the backstop moved to that day, nothing of the question left",
          out == "decision" and m.get("wait_kind") == "list" and m.get("wait_mode") == "all" and m.get("until") == day(10) and arrived_of(184) == [True, False, False] and m.get("mover") == BACK and "post_wake_mover" not in m
          and "ask" not in m and "options" not in m and "decision" not in (m.get("needs") or []) and WL.valid(m) and mod_of(184).wait.kind == "list", (out, m))
    check("backstop (open relay line): …and it is watched again (the next moment is that day)", wk.watches(rd(184)) and wk.next_moment(m) == wk.day_epoch(day(10)), None)
    # the owner says arrived / drop
    lst(186, [Re("the quote"), Tm(day(6))], mode="all", until=day(-1)); wakes_svc.wake_pass(); reset()
    answer_svc._answer("a186", "arrived", "", "answer"); m = mt(186)
    check("backstop (open relay line): `arrived` puts the item with the post-wake mover, alive; the wait's fields are gone", m.get("mover") == BACK and "ask" not in m and all(k not in m for k in GONE), m)
    lst(187, [Re("the quote"), Tm(day(6))], mode="all", until=day(-1)); wakes_svc.wake_pass()
    answer_svc._answer("a187", "drop", "", "answer"); m = mt(187)
    check("backstop (open relay line): `drop` closes it as not planned and the list goes with the rest of the wait", rd(187)["status"] == "completed" and m.get("outcome") == "dropped" and all(k not in m for k in GONE) and "ask" not in m, m)
    # an open relay line that has arrived does not ask
    reset()
    lst(188, [Re("the lease"), Tm(day(6))], mode="all", until=day(-1)); d = rd(188); d["metadata"]["waits"][0]["arrived"] = {"at": now0 - 100, "what": "he relayed it"}; put(188, d)
    wakes_svc.wake_pass(); m = mt(188)
    check("backstop: a relay line that has arrived is not an open one: the item goes to its post-wake mover, no question", m.get("mover") == BACK and "ask" not in m and "decision" not in (m.get("needs") or []), m)

    # ================================================================ races, edits and the other mechanisms
    # a list edited so that the group is over is found by the next pass
    reset()
    lst(190, [Tm(day(-1)), It("a191"), Re("x")], mode="all"); item(191)
    wakes_svc.wake_pass(); d = rd(190); d["metadata"]["waits"][1]["arrived"] = {"at": now0, "what": "a191 closed"}; put(190, d)        # two of three arrived
    check("edit: two of three lines have arrived: the item waits on", mt(190).get("wait_kind") == "list" and not WL.done(mt(190)), mt(190))
    d = rd(190); d["metadata"]["waits"] = d["metadata"]["waits"][:2]; put(190, d)                                                      # …and the open line is removed from the list
    check("edit: …the line that was open is removed: every line left has arrived, so the group is over and the scheduler sees it is due now", WL.done(mt(190)) and wakes_svc.next_wake() is not None and wakes_svc.next_wake() <= _pages.zone_now(), wakes_svc.next_wake())
    reset(); woke = wakes_svc.minute_wake_pass() or wakes_svc.wake_pass()
    check("edit: …and the next pass turns it", mt(190).get("mover") == BACK and mt(190)["woke"]["what"].startswith("all 2 arrived:"), mt(190))
    # a list that does not hold is a single wait: it ends as one
    reset()
    lst(192, [Tm(day(5))], mode="all", until=day(-1))
    woke = wakes_svc.wake_pass(); m = mt(192)
    check("malformed: an item that stores wait_kind=list with a list that does not hold ends as the date alone: its backstop day comes, the mover has it, the stray fields go with the wait", "a192" in woke and m.get("mover") == BACK
          and "its until" in m["woke"]["what"] and all(k not in m for k in GONE), m)
    # the backstop day ends a list (the watchers' pass; the old wake pass never touches a list)
    reset()
    lst(193, [Tm(day(9)), It("a194")], mode="all", until=day(9)); item(194)
    reset(); woke = wakes_svc.wake_pass()
    check("watchers: the wake pass leaves a list before its backstop day alone", "a193" not in woke and mt(193).get("wait_kind") == "list", (woke, mt(193)))
    item(206, subject="[home] the blocker of a list that is still open")
    lst(215, [Tm(day(9)), It("a206"), Ev("job_run weekly")], mode="all", until=day(-1)); reset(); woke = wakes_svc.wake_pass()
    check("watchers: a list whose backstop day has passed ends with the watchers' words (nothing arrived, every line still open)", "a215" in woke and mt(215).get("mover") == BACK
          and mt(215)["woke"]["what"] == f"backstop day {day(-1)}: nothing had arrived; still open: the date {day(9)}; the close of {_gh.shown('a206')}; a fleet event (job_run weekly)", (mt(215).get("woke"),))
    # pause
    reset()
    lst(195, [Tm(day(-1)), Re("x")], mode="any", until=day(-1)); lst(196, [It("a197"), Re("x")], mode="any"); item(197)
    cfg(pause=True); b195 = raw(195); woke = wakes_svc.wake_pass(); close(197)
    check("pause: nothing is marked or ended while paused (the clock's pass, a close)", raw(195) == b195 and woke == [] and arrived_of(196) == [False, False] and not sent(), (woke, mt(196)))
    cfg(pause=False); woke = wakes_svc.wake_pass()
    check("pause: …when it lifts the clock's pass finds the arrivals and ends them", "a195" in woke and "a196" in woke and mt(196).get("mover") == BACK and mt(195).get("mover") == BACK, (woke, mt(196)))
    check("pause: …each recipient hears one message for the two items", len(sent("watch")) == 1 and "2 items are yours now" in sent("watch")[0][2], sent())
    # a failed turn is backed off, not retried hot
    lst(198, [Tm(day(-1)), Re("x")], mode="any")
    orig_fire = watching_svc.watch_fire
    def boom(*a, **k): raise RuntimeError("disk")
    watching_svc.watch_fire = boom
    try:
        wakes_svc.wake_pass()
    finally:
        watching_svc.watch_fire = orig_fire
    check("backstop: a turn that cannot be made is backed off (noted on the item), the arrival stays recorded", mt(198).get("watch", {}).get("failed_at", 0) > 0 and arrived_of(198)[0] is True and mt(198).get("wait_kind") == "list", mt(198))
    check("backstop: …and the scheduler looks at it again after the back-off, not at once", wk.next_moment(mt(198)) >= mt(198)["watch"]["failed_at"] + wk.BACKOFF - 1, wk.next_moment(mt(198)))
    # a closed item drops the list with the rest
    lst(199, [Tm(day(5)), It("a901")], mode="all")
    _update_svc._update("a199", sender=FRONT, status="completed", outcome="done", reason="finished", description="- The thing works now\n- It lives here\n- Finished when it ships")
    check("close: a closed item loses the list (waits and wait_mode go with the rest of the wait)", rd(199)["status"] == "completed" and all(k not in mt(199) for k in GONE), mt(199))
    lst(200, [Tm(day(5)), It("a901")], mode="all")
    _update_svc._update("a200", sender=FRONT, clear_wait=True)
    check("clear_wait: it drops the list with the rest of the wait", all(k not in mt(200) for k in GONE), mt(200))

    # ================================================================ the review lows of the first part
    # (a) two relay lines: the owner is asked for the OPEN one
    reset()
    lst(220, [Re("the first quote"), Re("the second quote"), Tm(day(9))], mode="all", until=day(-1)); d = rd(220); d["metadata"]["waits"][0]["arrived"] = {"at": now0 - 100, "what": "the first quote was relayed"}; put(220, d)
    check("relay_event: the first OPEN relay line's event (an arrived one is not asked about)", WL.relay_event(mt(220)) == "the second quote" and WL.relay_event({**GOOD, "waits": [Re("a"), Re("b")]}) == "a", WL.relay_event(mt(220)))
    wakes_svc.wake_pass(); m = mt(220)
    check("backstop (two relay lines, the first arrived): the owner is asked about the OPEN one", m.get("ask") == "Decide: has the second quote arrived? · Options: arrived / ask again in a week, two weeks or a month / not yet, ask again on <date> / drop" and m.get("needs") == ["decision"]
          and "the first quote was relayed" in m["woke"]["what"] and "still open: news of the second quote" in m["woke"]["what"], m)
    # (b) an arrived line is still found by the close (open_only=False): the item is one the close is for, not a mention
    WO: list[set[str]] = []
    _tcm = telling.tell_close_mentions
    def _tcm_spy(gid_, outcome_, reason_, writer_, waiting_on): WO.append(set(waiting_on)); return _tcm(gid_, outcome_, reason_, writer_, waiting_on)
    telling.tell_close_mentions = _tcm_spy
    reset()
    lst(221, [It("a222"), Re("the lease")], mode="all"); item(222, subject="[home] closes twice")
    close(222); WO.clear(); close(222)
    check("release: an item whose line on the closed item has already arrived is still one that waited on it (found with open_only False: it is told no mention), and the second close marks and writes nothing more",
          arrived_of(221) == [True, False] and len(notes_of("a221")) == 1 and WO and "a221" in WO[-1], (WO, notes_of("a221")))
    check("lines_for_item: …an arrived line is found with open_only False and not by the open-only lookup", WL.lines_for_item(mt(221), "a222") == [] and WL.lines_for_item(mt(221), "a222", open_only=False) == [0], mt(221))
    telling.tell_close_mentions = _tcm
    # (c) a changed list is a new wait: its stamp is reset
    old_meta = json.loads(json.dumps(mt(100)))
    def on_write(new): return wait_gates_svc._watch_on_write("a100", {"metadata": old_meta}, new, {}, set(), FRONT, False)
    for what_, edit in (("a line changed", lambda n_: n_["waits"].__setitem__(0, Tm(day(5)))), ("a line added", lambda n_: n_["waits"].append(Tm(day(6)))), ("the mode changed", lambda n_: n_.__setitem__("wait_mode", "any"))):
        nm_ = json.loads(json.dumps(old_meta)); nm_["watch"] = {"set_at": 5.0, "chases_seen": 1}; edit(nm_); on_write(nm_)
        check(f"stamp: {what_}: watch.set_at is reset to now (a notice older than the new list is not its arrival), the rest of watch stays", nm_["watch"]["set_at"] >= now0 and nm_["watch"].get("chases_seen") == 1, nm_["watch"])
    nm_ = json.loads(json.dumps(old_meta)); nm_["watch"] = {"set_at": 5.0}; on_write(nm_)
    check("stamp: …a write that leaves the list as it is keeps the stamp", nm_["watch"]["set_at"] == 5.0, nm_["watch"])
    # (5) an unstamped list: the first mark stamps the floor it had, so a second notice dated before that save still counts
    reset()
    lst(223, [An(AURL, "a reply"), An(AURL2, "a reply"), Re("x")], mode="all", watch={}); item_ = rd(223)
    check("stamp: an unstamped list reads its last write as the floor", "set_at" not in mt(223).get("watch", {}) and watching_svc.watch_floor(item_) == max(item_["state_updated"], item_["updated"]), mt(223))
    wakes_svc.anchor_release("projects/alpha", notice("first reply", anchor="github:o/r#5", ts=now0 - 3600, ruled_at=now0 - 3600, ruling="passed"), by="home-stew")
    m = mt(223)
    check("stamp: the first mark stamps the floor the list had (the old last write), not now", arrived_of(223) == [True, False, False] and abs(m["watch"]["set_at"] - item_["updated"]) < 1 and rd(223)["updated"] >= now0, (m.get("watch"), item_["updated"]))
    wakes_svc.anchor_release("projects/alpha", notice("second reply", anchor="github:o/r#6", ts=now0 - 1800, ruled_at=now0 - 1800, ruling="passed"), by="home-stew")
    check("stamp: …so a second notice dated before the first mark's save still counts", arrived_of(223) == [True, True, False], (arrived_of(223), mt(223).get("watch")))
    # (e) a bool is no time; free text is clipped; the History note is clipped
    check("shape: a bool is no arrival time (float(True) is 1.0): the line is a line that has not arrived", not WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": True, "what": "x"}}, It("a1")]})[0])
          and WL.valid({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": True, "what": "x"}}, It("a1")]}) and WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": 1, "what": "x"}}, It("a1")]})[0]), None)
    LONG = "word " * 200
    cl = WL.lines({**GOOD, "waits": [An("https://x/" + "a" * 400, LONG), Ev(LONG), Re(LONG), {**Tm("2026-11-20"), "arrived": {"at": 5.0, "what": LONG}}]})
    check("shape: an anchor, an event and the words of an arrival are clipped to LINE_MAX (300); nothing else is", WL.LINE_MAX == 300 and len(cl[0]["anchor"]) == 300 and len(cl[0]["event"]) == 300 and len(cl[1]["event"]) == 300 and len(cl[2]["event"]) == 300
          and len(cl[3]["arrived_what"]) == 300 and cl[3]["until"] == "2026-11-20", [len(cl[0]["anchor"]), len(cl[0]["event"]), len(cl[3]["arrived_what"])])
    lst(224, [Re("the lease"), Tm(day(7))], mode="all"); out_ = {}
    watching_svc.watch_mark("a224", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "he relayed: " + LONG)
    check("shape: the History note of an arrival clips its words too (one line's worth), and the stored words keep to LINE_MAX", len(notes_of("a224")) == 1 and len(notes_of("a224")[0]) < 340 and notes_of("a224")[0].endswith("(1 of 2)") and len(mt(224)["waits"][0]["arrived"]["what"]) <= 300, [len(n) for n in notes_of("a224")])
    # (4) a list that does not hold is read as the date alone by every reader of the kind
    BADL = {"wait_kind": "list", "wait_mode": "all", "until": "2026-12-01", "waits": [Tm("2026-11-20")]}
    check("kind_of: a stored list that does not hold is the date alone to waiting.kind_of (time with an until, none without) and to until_write.kind_of (none); a list that holds is a list to both",
          _WT.kind_of(BADL) == "time" and _WT.kind_of({k: v for k, v in BADL.items() if k != "until"}) == "" and UW.kind_of(BADL) == "" and _WT.kind_of(GOOD) == "list" and UW.kind_of(GOOD) == "list"
          and _WT.kind_of({"wait_kind": "relay"}) == "relay" and UW.kind_of({"wait_kind": "relay"}) == "relay", (_WT.kind_of(BADL), UW.kind_of(BADL)))
    check("kind_of: …whatever is wrong with the list (not a list of lines, a mode that is neither, no backstop day)", all(not UW.kind_of({**BADL, **bad}) and _WT.kind_of({**BADL, **bad}) in ("time", "") for bad in ({"waits": "x"}, {"wait_mode": "some", "waits": GOOD["waits"]}, {"until": "", "waits": GOOD["waits"]})), None)

    # ================================================================ the lows of the display follow-up
    # one list whose end failed is moved off by its back-off, as the watchers' branch gives it
    reset()
    lst(231, [Tm(day(9)), It("a206")], mode="all", until=day(-1))
    d_ = rd(231); d_["metadata"]["watch"] = {"failed_at": time.time() - 100}; put(231, d_)
    fa100_ = d_["metadata"]["watch"]["failed_at"]
    pin_w_ = [at for g, *_, at in wakes_svc.wake_rows() if g == "a231"]
    check("watchers: a failure 100 s ago puts the moment at failed_at + BACKOFF, to the microsecond, and the watchers' own next_moment gives the same", len(pin_w_) == 1 and abs(pin_w_[0].timestamp() - (fa100_ + wk.BACKOFF)) < 0.001 and abs(wk.next_moment(mt(231)) - (fa100_ + wk.BACKOFF)) < 0.001, (pin_w_, wk.next_moment(mt(231))))
    lst(235, [Tm(day(9)), It("a206")], mode="all", until=day(5)); lst(236, [Tm(day(9)), It("a206")], mode="all", until=day(6))      # two lists the torn note on a231 must not stop
    # a torn failure note (no number, a bool, a negative, a non-finite, a moment no date can show) is no failure: it never stops the rows of the other items, and the moment is the one with no note
    d_ = rd(231); d_["metadata"]["watch"].pop("failed_at", None); put(231, d_)
    base_ = {k_: [at for g, *_, at in wakes_svc.wake_rows() if g == "a231"] for k_ in (False, True)}
    for mode_ in (True,):
        for v_ in (1e18, 1e300, float("inf"), float("-inf"), float("nan"), "x", "Infinity", "1e999", -5, 0, True, None, [1], {"at": 1}, 10 ** 400):
            d_ = rd(231); d_["metadata"]["watch"]["failed_at"] = v_; put(231, d_)
            try: rows_ = wakes_svc.wake_rows(); nxt_ = wakes_svc.next_wake(); why_ = ""
            except Exception as e_: rows_, nxt_, why_ = [], None, f"{e_.__class__.__name__}: {e_}"
            ids_ = [g for g, *_ in rows_]
            mine_ = [at for g, *_, at in rows_ if g == "a231"]
            check(f"hostile failed_at {v_!r} (watchers): wake_rows and next_wake never raise, every other list keeps its row, and the item's moment is the one with no note",
                  not why_ and all(g in ids_ for g in ("a235", "a236")) and nxt_ is not None and mine_ == base_[mode_], (why_, ids_, mine_, base_[mode_]))
            check(f"hostile failed_at {v_!r} (watchers): …and failed_at itself reads it as no failure (0.0)", wk.failed_at({"watch": {"failed_at": v_}}) == 0.0, wk.failed_at({"watch": {"failed_at": v_}}))
            try: nm_ = wk.next_moment(mt(231)); ok_ = nm_ is None or isinstance(nm_, float)
            except Exception as e_: ok_, nm_ = False, f"{e_.__class__.__name__}: {e_}"
            check(f"hostile failed_at {v_!r} (watchers): …and next_moment reads it as no failure too", ok_, nm_)
    d_ = rd(231); d_["metadata"]["watch"].pop("failed_at", None); put(231, d_)
    check("failed_at reads a real failure as it is stored (a float, an int, a number as text) and a missing or torn note as none", wk.failed_at({"watch": {"failed_at": 1.5e9}}) == 1.5e9 and wk.failed_at({"watch": {"failed_at": 1500000000}}) == 1.5e9 and wk.failed_at({"watch": {"failed_at": "1500000000"}}) == 1.5e9 and wk.failed_at({}) == 0.0 and wk.failed_at({"watch": "x"}) == 0.0, None)
    # `watch_fire` ends a list that is open and nothing else: a closed item that still stores a list is left alone
    lst(234, [Tm(day(9)), It("a206")], mode="all", until=day(-1)); d_ = rd(234); d_["status"] = "completed"; put(234, d_)
    b234 = raw(234); out_ = {}
    try: got_ = watching_svc.watch_fire("a234", "backstop", time.time(), out_); why_ = ""
    except Exception as e_: got_, why_ = None, f"{e_.__class__.__name__}: {e_}"
    check("watch_fire on a closed item that stores a list does nothing (False, no message, no save, the item as it was)", got_ is False and not out_ and raw(234) == b234, (got_, why_, out_))
    # hostile data: a megabyte in every field of every line is clipped before it is normalised, and what is kept is what normalising the whole would keep
    HUGE = ("ab cd " * 170000)[:1_000_000]
    big_ = {"wait_kind": "list", "wait_mode": "all", "until": "2026-12-01", "waits": [{**An(HUGE, HUGE), "arrived": {"at": 5.0, "what": HUGE}}, {**Ev(HUGE), "arrived": {"at": 6.0, "what": HUGE}}, Re(HUGE), It(HUGE)] * 2}
    t0_ = time.perf_counter()
    for _ in range(5): ok_ = WL.valid(big_) and bool(WL.lines(big_)) and bool(WL.summary(big_)) and _WT.kind_of(big_) == "list"
    spent_ = time.perf_counter() - t0_
    cl_ = WL.lines(big_)
    check("hostile: eight lines of a megabyte each are read in no time (5 rounds of valid, lines, summary and kind_of in under half a second; it took seconds when the whole text was normalised first)", ok_ and spent_ < 0.5, spent_)
    def spent(f, n=20):
        t_ = time.perf_counter()
        for _ in range(n): r_ = f()
        return r_, time.perf_counter() - t_
    SLOW = {"a megabyte wait_kind": lambda: WL.stored({"wait_kind": HUGE}), "a megabyte wait_mode": lambda: WL.mode({"wait_mode": HUGE}), "a megabyte backstop day": lambda: WL.backstop({"until": HUGE}),
            "a megabyte line kind": lambda: WL.problem({**GOOD, "waits": [{"kind": HUGE, "event": "x"}, It("a1")]}), "a megabyte date of a time line": lambda: WL.problem({**GOOD, "waits": [Tm(HUGE), It("a1")]}),
            "a megabyte mode in the refusal": lambda: WL.problem({**GOOD, "wait_mode": HUGE})}
    for what_, f_ in SLOW.items():
        r_, took_ = spent(f_)
        check(f"hostile: {what_} is read in no time (20 reads in under a tenth of a second: it is clipped before it is normalised) and is no kind, mode or day", took_ < 0.1 and (r_ is False or r_ == "" or (isinstance(r_, str) and len(r_) <= WL.WORD_MAX + 100)), (took_, str(r_)[:60]))
    check("hostile: …what is kept is the first LINE_MAX characters of the normalised text, as before", cl_[0]["anchor"] == " ".join(HUGE.split())[:300] and cl_[0]["event"] == " ".join(HUGE.split())[:300] and cl_[0]["arrived_what"] == " ".join(HUGE.split())[:300]
          and cl_[3]["after"] == " ".join(HUGE.split())[:300], [len(cl_[0]["anchor"]), len(cl_[3]["after"])])
    for text_ in ("a" + " " * 5000 + "b" * 400, " " * 4000, "x" * 700, " ".join(["\t\n word"] * 400), "é" * 301 + "\u00a0" * 900 + "tail"):
        lines_ = WL.lines({**GOOD, "waits": [An("https://x/" + text_, text_), Ev(text_)]}) if text_.strip() else ()
        if lines_: check(f"hostile: clipping before normalising keeps what clipping after kept (a text of {len(text_)} characters, mostly whitespace or not)", lines_[1]["event"] == " ".join(text_.split())[:300] and lines_[0]["anchor"] == (" ".join(("https://x/" + text_).split()))[:300], lines_[1]["event"][:40])
    check("hostile: a megabyte of whitespace-only text in a field is no text (the line needs it), and a megabyte kind, mode or backstop day is no kind, mode or day", not WL.valid({**GOOD, "waits": [Re(" " * 1_000_000), It("a1")]}) and not WL.valid({**GOOD, "waits": [{"kind": HUGE, "event": "x"}, It("a1")]})
          and not WL.valid({**GOOD, "wait_mode": HUGE}) and not WL.valid({**GOOD, "until": HUGE}) and not WL.stored({"wait_kind": HUGE}) and WL.stored({"wait_kind": "  List "}), None)

    # ================================================================ nothing changed for a single wait
    check("single: the model's fields, kinds and words for the five single kinds are what they were (an item with one wait stores no list, reads no lines, and the five-kind write check is the same)",
          model.WAIT_KINDS[:5] == ("time", "anchor", "item", "relay", "event") and model.KIND_WORDS["event"] == "a fleet event" and model.derive({**rd(103), "metadata": {**mt(103)}}).waits == (), None)
    check("single: the stored `until` of a single wait that the list reader sees is no list (wait_kind not list)", not WL.valid({"wait_kind": "time", "until": day(3), "waits": [Tm(day(3)), It("a1")], "wait_mode": "all"}) and WL.lines({"waits": [Tm(day(3)), It("a1")]}) == (), None)

    return ran, fails

# ================================================================ part display: how a list reads on the board
def part_display():
    tmp, T = _setup("waitlistdisplay-", keywords=True)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "brain/projects", "locales", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    NAMES = ("home-owner", "home-stew", "team-back", "home-front")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    ZONE = datetime.timezone(datetime.timedelta(hours=4))      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
    NOW = datetime.datetime(2026, 11, 13, 10, 0, tzinfo=ZONE)
    now0 = NOW.timestamp(); H, DAY = 3600.0, 86400.0
    day = lambda n: (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                    "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
    DESC = "- A thing\n- It lives here\n- Done when done"
    BACK = "team-back"
    def item(i, status="open", subject=None, **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * H, "state_updated": now0 - 2 * H, "confirmed": now0 - 2 * H,
                                                         "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
    Tm = lambda d: {"kind": "time", "until": d}
    An = lambda url, ev="PR merged": {"kind": "anchor", "anchor": url, "event": ev}
    It = lambda g: {"kind": "item", "after": g}
    Re = lambda ev="the lease": {"kind": "relay", "event": ev}
    Ev = lambda ev: {"kind": "event", "event": ev}
    def arr(line, at, what): return {**line, "arrived": {"at": at, "what": what}}
    def lst(i, waits, mode="all", until=None, **extra):
        item(i, wait_kind="list", hold=True, wait_mode=mode, until=until or day(4), waits=waits, post_wake_mover=BACK, needs=[], subject=extra.pop("subject", f"[home] list {i}"), watch={"set_at": now0 - 3600}, **extra)
    AURL, AURL2 = "https://github.com/o/r/pull/5", "https://github.com/o/r/pull/6"
    EVIL = "<script>alert(1)</script> & <b>bold</b>"
    GOT = now0 - 90 * 60          # the time of an arrival: 08:30, the same day
    # the items
    item(300, status="completed", subject="[home] a blocker that has closed", outcome="done", reason="finished", needs=[])
    item(301, subject="[home] a blocker that is open", mover="team-back", needs=["team-back"])
    lst(310, [Re("SK's final ticket and its feedback"), Re("the signing order the team agrees")], mode="all", until=day(4), subject="[home] two pieces of news, both needed")
    lst(311, [An(AURL, "GitHub's confirmation posted"), An(AURL2, "the head ref no longer resolves")], mode="any", until=day(2) + "T10:00", subject="[home] two signs, one needed")
    lst(312, [arr(Tm(day(3)), GOT, "its date came"), arr(It("a300"), GOT + 600, "the other item closed (done)"), It("a301"), An(AURL, "PR merged"), Ev("recycle testbox"), Re("the lease")], mode="all", until=day(6), subject="[home] six lines of every kind")
    lst(313, [Re(EVIL), arr(An('https://x.example/a"><img src=x onerror=alert(1)>', EVIL), GOT, EVIL), Ev(EVIL)], mode="all", subject="[home] free text")
    lst(314, [Re("one"), An("github:o/r#7", "a review")], mode="all", until=day(4), subject="[home] a list with an anchor that is no address")
    lst(315, [It("a300"), It("a301")], mode="all", subject="[home] two items, one already closed (its arrival not recorded yet)")
    item(320, subject="[home] a single time wait", wait_kind="time", hold=True, wake=day(5), needs=[], post_wake_mover=BACK, wait_basis={"text": "the vendor ships on that day", "by": "home-front"})
    item(321, subject="[home] a single relay wait", wait_kind="relay", hold=True, ask_by=day(5), wait_event="the lease", party="the landlord", needs=[], post_wake_mover=BACK)
    item(322, subject="[home] a single item wait", wait_kind="item", hold=True, after=["a301"], wake=day(7), needs=[], post_wake_mover=BACK)
    item(323, subject="[home] a single anchor wait", wait_kind="anchor", hold=True, wait_anchor=AURL, wait_event="PR merged", wake=day(7), needs=[], post_wake_mover=BACK)
    lst(330, [Tm(day(3))], mode="all", until=day(4), subject="[home] a list that does not hold")
    HOSTILE = {340: float("inf"), 341: "inf", 342: 1e20, 343: 1e300, 344: 253402300800, 345: 10 ** 400}      # a stored arrival time no date can show (the shape reads each as no arrival)
    for i_, at_ in HOSTILE.items(): lst(i_, [arr(Re("the lease"), at_, "the lease arrived"), It("a301")], mode="all", subject=f"[home] hostile arrival time {i_}")
    lst(346, [arr(Re("the lease"), GOT, "the lease arrived"), It("a301")], mode="all", subject="[home] a real arrival time")
    LONG_ID = "a" + "9" * 1_000_000
    lst(347, [Re("one"), It(LONG_ID)], mode="all", subject="[home] a line that names an item with a very long id")
    lst(348, [arr(Re("the lease"), GOT, ""), arr(An(AURL, "PR merged"), GOT + 60, ""), It("a301")], mode="all", subject="[home] arrivals with no words recorded")
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
    logging.disable(logging.INFO)
    from stackshot.core import config as _cfg
    from stackshot.web.ui import render; from stackshot.web import server, i18n; from stackshot.model import model
    from stackshot.web.tools import notes as _notes_tool
    from stackshot.service import item_read as _item_read
    from stackshot.web import publish as _web_publish
    _web_publish._publish = lambda: None
    b = render.Board(str(T / "store"), now=NOW)
    plain = lambda h: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
    def row(g): r = next(x for x in b.rows if x["gid"] == g); return r, b.mod_of(r)
    def wait_cell(g): r, m = row(g); return b.home_wait(r, m)
    def who_line(g): r, m = row(g); return plain(b.wait_who(r, m))
    def end_slot(g): r, m = row(g); return plain(b.wait_end_slot(m, 0))
    def page_wait(g): h = b.item_html(g); i = h.find('<section class="iwait">'); return h[i:h.find("</section>", i)] if i >= 0 else ""
    def lines_of(h): return re.findall(r'<span class="wll(?: wdone)?">(.*?)</span></span></span>', h, re.S)
    def box_on(h): return [c == "wbox on" for c in re.findall(r'<span class="(wbox(?: on)?)"', h)]
    W = lambda d: b.day_words(d)
    W_ = lambda ts: b.when(ts)

    # ================================================================ the Waiting row: all of 2, nothing arrived
    c310 = wait_cell("a310"); p310 = plain(c310)
    check("row (all, nothing arrived): the head says the mode, that nothing has arrived and the backstop day; each wait is one line with its kind and its words, none ticked",
          '<span class="wl">' in c310 and plain(re.search(r'class="wmode">(.*?)</span>', c310).group(1)) == "all of 2" and f"0 arrived · back anyway {W(day(4))}" in p310 and box_on(c310) == [False, False]
          and p310.count("news") == 2 and "SK's final ticket and its feedback" in p310 and "the signing order the team agrees" in p310 and "arrived " not in p310.replace("0 arrived", ""), p310)
    check("row: …the lines come in the stored order", p310.index("SK's final ticket") < p310.index("the signing order"), p310)
    check("row: …the end slot on the right is the backstop day, as an item or anchor wait's is", end_slot("a310") == f"until {W(day(4))}", end_slot("a310"))
    check("row: …the who line: who picks it up and who watches (relay lines: the scheduler)", who_line("a310") == "team-back picks it up · watched by the scheduler", who_line("a310"))
    check("row: …no `ask by`, no chases (a list has only its backstop day and is never chased)", "ask by" not in p310 and "chased" not in p310, p310)
    # any of 2, a date with a time, anchors
    c311 = wait_cell("a311"); p311 = plain(c311)
    check("row (any): \"any of 2\", the backstop day with its time, two anchor lines each with the anchor as a link", plain(re.search(r'class="wmode">(.*?)</span>', c311).group(1)) == "any of 2" and f"0 arrived · back anyway {W(day(2) + 'T10:00')}" in p311
          and "10:00" in p311 and c311.count('<a href="https://github.com/o/r/pull/') == 2 and p311.count("anchor") == 2 and "GitHub's confirmation posted" in p311, p311)
    check("row: …anchor lines are watched by the anchor module; the end slot carries the time", who_line("a311") == "team-back picks it up · watched by the anchor module" and "10:00" in end_slot("a311"), (who_line("a311"), end_slot("a311")))
    # six lines of every kind, two arrived
    c312 = wait_cell("a312"); p312 = plain(c312)
    check("row (all of 6, two arrived): the head counts them; the arrived lines are ticked and carry the time of their arrival, the other four are open", f"2 arrived · back anyway {W(day(6))}" in p312 and "all of 6" in p312
          and box_on(c312) == [True, True, False, False, False, False] and p312.count("arrived " + W_(GOT)) == 1 and p312.count("arrived ") == 3, (p312, box_on(c312)))
    check("row: …each kind says its own words: the date, the close of an item (a link to it), an anchor (its event and a link), a fleet event, news",
          f"the date {W(day(3))}" in p312 and "the close of a300" in p312 and 'href="/items/a300"' in c312 and "PR merged ( r PR #5 )" in p312 and 'href="https://github.com/o/r/pull/5"' in c312 and "recycle" in p312 and "the lease" in p312
          and [x for x in re.findall(r'class="wkind">(.*?)</span>', c312)] == ["date", "item", "item", "anchor", "event", "news"], (p312, re.findall(r'class="wkind">(.*?)</span>', c312)))
    check("row: …who watches: the arrived lines need no watcher, the open ones each have theirs, once (the server for an item and an event, the anchor module, the scheduler)", who_line("a312") == "team-back picks it up · watched by the server, the anchor module, the scheduler", who_line("a312"))
    check("row: a list with an anchor that is no address still has its watcher (the anchor module)", who_line("a314") == "team-back picks it up · watched by the scheduler, the anchor module", who_line("a314"))

    # ================================================================ the item page
    pg310, pg311, pg312 = page_wait("a310"), page_wait("a311"), page_wait("a312")
    p_310 = plain(pg310)
    check("page (all, nothing arrived): Waits on holds the list: the mode, how many arrived and how it ends, one line per wait with its kind", "all of 2" in p_310 and "0 arrived · it comes back when the last one does" in p_310 and box_on(pg310) == [False, False] and p_310.count("news only") == 2, p_310)
    check("page: …Backstop is its own row (the day, and that it is back at the latest whatever has arrived); Picks it up follows; there is no Watched by row and no Chases row", re.findall(r"<dt>(.*?)</dt>", pg310) == ["Waits on", "Backstop", "Picks it up"]
          and f"{b.wait_day(day(4))} · back at the latest, whatever has arrived" in p_310, re.findall(r"<dt>(.*?)</dt>", pg310))
    check("page: …each open line says what watches it: news only <owner> relays, watched by the scheduler", p_310.count("news only") == 2 and p_310.count("watched by the scheduler") == 2 and "Chases" not in p_310 and "Watched by" not in p_310, p_310)
    p_311 = plain(pg311)
    check("page (any): \"any of 2\" and \"the first to arrive brings it back\"; each anchor line shows its anchor in full as a link, watched by the anchor module", "any of 2" in p_311 and "the first to arrive brings it back" in p_311 and "arrived ·" not in p_311
          and pg311.count('<a href="https://github.com/o/r/pull/') == 2 and p_311.count("watched by the anchor module") == 2 and "https://github.com/o/r/pull/5" in p_311 and "https://github.com/o/r/pull/6" in p_311, (pg311.count('<a href="https://github.com/o/r/pull/'), p_311.count("watched by the anchor module"), p_311))
    p_312 = plain(pg312)
    check("page (all of 6, two arrived): the arrived lines are ticked with the words of their arrival and the time; the open ones say what watches them", "2 arrived · it comes back when the last one does" in p_312 and box_on(pg312) == [True, True, False, False, False, False]
          and f"its date came · arrived {W_(GOT)}" in p_312 and f"the other item closed (done) · arrived {W_(GOT + 600)}" in p_312, p_312)
    check("page: …an item line says whether the item is open or closed, a fleet event is watched by the server, an anchor line by the anchor module", "the close of a301 (open) · watched by the server" in p_312 and "watched by the server" in p_312 and "watched by the anchor module" in p_312 and "news only" in p_312, p_312)
    check("page: …the sidebar's wait group reads Backstop with the day (the one date of the item)", re.search(r"<dt>Backstop</dt><dd>" + re.escape(b.wait_day(day(6))) + "</dd>", b.item_html("a312")) is not None, None)

    p_315 = plain(page_wait("a315"))
    check("page: an item line says whether its item is open or closed (an item that closed before the clock's pass marked the line is closed, the other open)", "the close of a300 (closed) · watched by the server" in p_315 and "the close of a301 (open) · watched by the server" in p_315, p_315)

    # ================================================================ free text is escaped
    c313 = wait_cell("a313"); pg313 = page_wait("a313"); full = c313 + pg313 + b.item_html("a313")
    check("escape: the event of a line, the anchor of a line and the words of an arrival are free text: none of them reaches the row or the page as markup", "<script>alert(1)" not in full and "<b>bold</b>" not in full and "<img src=x" not in full and "onerror=alert(1)>" not in full, re.findall(r"<script>alert|<b>bold|<img src=x[^>]*>", full))
    check("escape: …they are there as text, once escaped (the row and the page), and the anchor's quote and angle bracket stay inside its href", "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in c313 and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in pg313
          and 'href="https://x.example/a&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in c313 and 'href="https://x.example/a&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in pg313, c313[:900])
    c314, pg314 = wait_cell("a314"), page_wait("a314")
    check("escape: …an anchor that is not a web address is text, not a link (row and page)", "github:o/r#7" in plain(c314) and 'href="github:' not in c314 + pg314 and "github:o/r#7" in plain(pg314), plain(c314))

    # ================================================================ a single wait reads as it did; a list that does not hold is the date alone
    S320, S321, S322, S323 = (plain(wait_cell(g)) for g in ("a320", "a321", "a322", "a323"))
    check("single: a time wait reads as it did (until the day), no list class", S320 == f"Until {W(day(5))}" and 'class="wl"' not in wait_cell("a320"), S320)
    check("single: …a relay wait (the party's news, ask by the day)", S321.startswith("On ") and f"ask by {W(day(5))}" in S321 and "the lease" in S321 and 'class="wl"' not in wait_cell("a321"), S321)
    check("single: …an item wait (after the item, and only the item: the backstop it carries stays stored and is not printed, as the model line says it)", S322 == "After a301", S322)
    P322 = page_wait("a322")
    check("single: …its page names the item and shows no end row and no backstop day (the model line's words)", "a301" in plain(P322) and W(day(7)) not in plain(P322) and "Backstop" not in P322 and "<dt>End</dt>" not in P322
          and W(day(7)) not in plain(b.item_html("a322")), plain(P322))
    check("single: …an anchor wait (on the anchor, its event, the backstop)", S323.startswith("On ") and "PR merged" in S323 and f"backstop {W(day(7))}" in S323, S323)
    check("single: …their who lines keep the watcher of their kind (scheduler, scheduler, server, anchor module)", [who_line(g) for g in ("a320", "a321", "a322", "a323")]
          == ["team-back picks it up · watched by the scheduler", "team-back picks it up · watched by the scheduler", "team-back picks it up · watched by the server", "team-back picks it up · watched by the anchor module"], [who_line(g) for g in ("a320", "a321", "a322", "a323")])
    check("single: …the item page keeps its Watched by row, its Until or Ask by row and (relay, anchor) its Chases row, and no list block", all('class="wl"' not in page_wait(g) for g in ("a320", "a321", "a322", "a323"))
          and re.findall(r"<dt>(.*?)</dt>", page_wait("a321")) == ["Waits on", "Watched by", "Ask by", "Picks it up", "Chases"] and "Watched by" in page_wait("a322") and "Chases" in page_wait("a323"), re.findall(r"<dt>(.*?)</dt>", page_wait("a321")))
    c330 = wait_cell("a330")
    check("malformed: a stored list that does not hold (one line) is read as the date alone, everywhere: no list class on the row or the page", 'class="wl"' not in c330 and 'class="wl"' not in page_wait("a330") and "list" not in plain(c330).lower(), plain(c330))

    # ================================================================ the string table
    LOC = T / "locales"
    MARK = lambda v: f"[x:{v}]"
    DATE_AGE = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.day": "{n}{ord}", "date.ord.1": "o1", "date.ord.2": "o2", "date.ord.3": "o3", "date.ord.n": "on",
                "age.now": "A<now>", "age.min": "A<{n}min>", "age.hour": "A<{n}hr>", "age.day": "A<{n}day>"}
    DATE_AGE.update({f"date.wd.{i}": f"w{i}" for i in range(7)}); DATE_AGE.update({f"date.mon.{i}": f"m{i}" for i in range(1, 13)})
    KEYS = sorted(k for k in i18n.EN if k.startswith("wait.list.") or k in ("wait.what.list", "wait.label.backstop", "home.watched_by", "wait.waits_on", "wait.picks_up", "wait.end.backstop") or k.startswith("home.watcher."))
    check("strings: every key of a list's display is in the string table (English), as a plain template", len([k for k in KEYS if k.startswith("wait.list.")]) >= 18 and all(i18n.fields_of(i18n.EN[k]) is not None for k in KEYS), KEYS)
    (LOC / "ko.json").write_text(json.dumps({**{k: MARK(v) for k, v in i18n.EN.items()}, **DATE_AGE}), encoding="utf-8")
    _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(LOC); i18n._WARNED.clear(); i18n._LOADED.clear()
    with i18n.use("ko"):
        bx = render.Board(str(T / "store"), now=NOW); rx, mx = next(x for x in bx.rows if x["gid"] == "a312"), None
        mx = bx.mod_of(rx); cx = bx.home_wait(rx, mx); wx = bx.wait_who(rx, mx); gx = bx.item_html("a312"); gi = gx.find('<section class="iwait">'); px = gx[gi:gx.find("</section>", gi)]
    def english_left(h):
        """The English words of a list's display that a marked locale must have replaced: text outside the marks, bar the fixtures' own words."""
        t = plain(h)
        while True:                                      # a mark may hold another (a template that carries a marked word): the innermost goes first
            t2 = re.sub(r"\[x:[^\[\]]*\]", " ", t)
            if t2 == t: break
            t = t2
        for fx in ("PR merged", "the next recycle of testbox", "recycle testbox", "the lease", "its date came", "the other item closed (done)", "github.com/o/r/pull/5", "https://github.com/o/r/pull/5", "r PR #5", "list 312", "#300", "#301", "a300", "a301", "team-back", "testbox"):
            t = t.replace(fx, " ")      # the fixtures' own words (an anchor's short label and a fleet event's words are the board's own helpers, not this display's)
        return re.sub(r"[\s·()\d:/.\-–,;✓\[\]]+", " ", re.sub(r"D<[^>]*>|A<[^>]*>|o\d|on\b|w\d|m\d+", " ", t)).strip()
    check("strings: every word of a list row comes from the string table (a locale that marks each key marks the head, each kind, the arrival, the watchers)", cx.count("[x:") >= 10 and not english_left(cx), english_left(cx))
    check("strings: …and of the item page's block (the mode, the notes, the sub lines, the Backstop row, its words)", px.count("[x:") >= 12 and not english_left(px), english_left(px))
    check("strings: …the who line carries the watchers through the table too", "[x:" in wx and not english_left(wx), plain(wx))
    _cfg.CFG["ui"].pop("locale_dir", None); i18n._WARNED.clear(); i18n._LOADED.clear()

    # ================================================================ the `model:` line of get
    def get_line(g): return [l for l in _notes_tool._model_lines({**json.loads((T / f"store/a/{g[1:]}.json").read_text()), "gid": g}) if l.startswith("model:")][0]
    ZLAB = zoneinfo.ZoneInfo("Asia/Dubai").tzname(NOW)      # the zone's own label, as the refusals that give a time name it (the instance zone pinned above)
    g312 = get_line("a312")
    check("get: the model line says the mode, how many have arrived, each line ticked [x] or open [ ] (an arrival with its words and its time), the backstop and the mover",
          g312.startswith("model: waiting on several things (all of 6, 2 arrived: [x] the date " + day(3) + " (its date came, " + day(0) + " 08:30 " + ZLAB + "); [x] the close of ") and "[ ] the close of" in g312 and "[ ] a notice at " + AURL + " (PR merged)" in g312
          and "[ ] a fleet event (recycle testbox)" in g312 and "[ ] news of the lease; until " + day(6) + ") · mover team-back" in g312, g312)
    check("get: …nothing arrived: every line open, 0 arrived", get_line("a310") == f"model: waiting on several things (all of 2, 0 arrived: [ ] news of SK's final ticket and its feedback; [ ] news of the signing order the team agrees; until {day(4)}) · mover team-back", get_line("a310"))
    check("get: …a single wait's line is what it was", get_line("a320") == f"model: waiting on a time (wake {day(5)}) · mover team-back", get_line("a320"))
    check("get: …the model's words without a time formatter name no time (the brief and other callers)", "(its date came)" in model.words(next(m_ for m_ in [_item_read._model_of({**json.loads((T / "store/a/312.json").read_text()), "gid": "a312"})]), derived=False), None)

    # ================================================================ a stored arrival time no date can show; an arrival with no words
    check("zone: the arrival time of get's model line names the zone, the way the refusals that give a time do (the label is the instance zone's, and not empty)", bool(ZLAB) and ZLAB == _cfg.tz_abbr(NOW) and f"08:30 {ZLAB})" in g312, (ZLAB, g312))
    home_html, why_home = None, ""
    try: home_html = b.html()
    except Exception as ex_: why_home = f"{ex_.__class__.__name__}: {ex_}"
    check("hostile: a list whose stored arrival time no date can show (inf, \"inf\", 1e20, 1e300, year 10000, a huge integer) does not take the home page down: every one of them is drawn", home_html is not None
          and all(f"hostile arrival time {i_}" in home_html for i_ in HOSTILE) and "a real arrival time" in home_html, why_home)
    for i_, at_ in HOSTILE.items():
        g_ = f"a{i_}"; tag = f"hostile arrival time ({at_!r:.12})"
        try: c_, p_ = wait_cell(g_), page_wait(g_); why_ = ""
        except Exception as ex_: c_ = p_ = ""; why_ = f"{ex_.__class__.__name__}: {ex_}"
        check(f"{tag}: the home row and the item page draw it, and it reads as not arrived (open, no time, no words), 0 arrived", bool(c_) and bool(p_) and box_on(c_) == [False, False] and box_on(p_) == [False, False]
              and "0 arrived" in plain(c_) and "the lease arrived" not in plain(c_ + p_) and "arrived · arrived" not in plain(p_), why_ or plain(c_))
        gl = get_line(g_)
        check(f"{tag}: get keeps its model line, with the line open and no time", gl == f"model: waiting on several things (all of 2, 0 arrived: [ ] news of the lease; [ ] the close of a301; until {day(4)}) · mover team-back", gl)
    c346, p346, g346 = wait_cell("a346"), plain(page_wait("a346")), get_line("a346")
    check("hostile: …a real arrival time on the same shape is drawn: ticked, with its time on the row, its words and time on the page, its words, time and zone in get", box_on(c346) == [True, False] and f"arrived {W_(GOT)}" in plain(c346)
          and f"the lease arrived · arrived {W_(GOT)}" in p346 and f"[x] news of the lease (the lease arrived, {day(0)} 08:30 {ZLAB})" in g346, (plain(c346), p346, g346))
    # a model handed a time no date can show anyway (the shape keeps it out; the three places that say a time never raise on one)
    r312, m312 = row("a312")      # its first two lines have arrived (the date line and the item line)
    NOT_A_DATE = (float("inf"), 1e20, 1e300, 253402300800.0)
    for at_ in NOT_A_DATE:
        bad = dataclasses.replace(m312, waits=tuple(dataclasses.replace(ln, arrived_at=at_) if ln.arrived else ln for ln in m312.waits))
        try: hr_, hp_ = b.wait_list_html(r312, bad, page=False), b.wait_list_html(r312, bad, page=True); why_ = ""
        except Exception as ex_: hr_ = hp_ = ""; why_ = f"{ex_.__class__.__name__}: {ex_}"
        try: wd_ = model.words(bad, when=_notes_tool._arrival_when); why_w = ""
        except Exception as ex_: wd_ = ""; why_w = f"{ex_.__class__.__name__}: {ex_}"
        check(f"hostile model ({at_!r}): the row and the page of a model handed it draw, ticked and keeping the arrival words with no time; get's words keep the words with no empty bracket",
              bool(hr_) and bool(hp_) and box_on(hr_)[:2] == [True, True] and "its date came" in plain(hp_) and "arrived · arrived" not in plain(hp_) and "arrived arrived" not in plain(hp_) and "arrived" in plain(hr_)
              and "(its date came)" in wd_ and "()" not in wd_, why_ or why_w or (plain(hp_), wd_))
        bare = dataclasses.replace(m312, waits=tuple(dataclasses.replace(ln, arrived_at=at_, arrived_what="") if ln.arrived else ln for ln in m312.waits))
        try: wb_ = model.words(bare, when=_notes_tool._arrival_when); hb_ = b.wait_list_html(r312, bare, page=True)
        except Exception as ex_: wb_ = hb_ = f"{ex_.__class__.__name__}: {ex_}"
        check(f"hostile model ({at_!r}): an arrival with no words and no time to say reads as ticked alone: get's words carry no empty bracket, the page says \"arrived\" once", "[x] the date " in wb_ and "[x] the close of a300;" in wb_ and "()" not in wb_ and "( )" not in wb_
              and plain(hb_).count("arrived arrived") == 0 and "arrived · arrived" not in plain(hb_), (wb_, plain(hb_)[:300]))
    check("hostile: the time of an arrival is empty (never an error) for a time no date can show, in the server's `model:` line, and the zone follows a real one", all(_notes_tool._arrival_when(x) == "" for x in (float("inf"), 1e20, 1e300, 253402300800.0, float("nan")))
          and _notes_tool._arrival_when(GOT) == f"{day(0)} 08:30 {ZLAB}" and b.arrival_when(float("inf")) == "" and b.arrival_when(GOT) == W_(GOT), (_notes_tool._arrival_when(float("inf")), _notes_tool._arrival_when(GOT)))
    # the brief's model line (short) carries the arrival time of a line as get's does: the same time formatter
    sh312 = _notes_tool._model_lines({**json.loads((T / "store/a/312.json").read_text()), "gid": "a312"}, short=True)
    check("brief: the short model line of a list with arrived lines carries the time of each arrival and the zone's name, as get's line does (one line, no conflicts)",
          len(sh312) == 1 and f"(its date came, {day(0)} 08:30 {ZLAB})" in sh312[0] and sh312[0].startswith("model: waiting on several things (all of 6, 2 arrived: "), sh312)
    # the time and its zone's name come from one source, read at the call (the instance zone can change under a running server, ZONE is fixed at import)
    _tz0 = _cfg.CFG["instance"]["timezone"]
    try:
        _cfg.CFG["instance"]["timezone"] = "Asia/Tokyo"
        at_tokyo = _notes_tool._arrival_when(GOT)
    finally:
        _cfg.CFG["instance"]["timezone"] = _tz0
    tk = datetime.datetime.fromtimestamp(GOT, zoneinfo.ZoneInfo("Asia/Tokyo"))
    check("zone: the arrival time is drawn in the zone the instance has at the call, with that zone's own name (never the clock of one zone with the name of another)", at_tokyo == f"{tk:%Y-%m-%d %H:%M} JST" and _notes_tool._arrival_when(GOT) == f"{day(0)} 08:30 {ZLAB}", (at_tokyo, _notes_tool._arrival_when(GOT)))
    # an item id of a megabyte in a line is clipped everywhere it is drawn
    c347, p347, h347, g347 = wait_cell("a347"), page_wait("a347"), b.item_html("a347"), get_line("a347")
    check("clip: a line that names an item with a one-megabyte id is drawn with the id clipped (the home cell, the item page, get's model line), never the megabyte", len(c347) < 4000 and len(p347) < 8000 and len(h347) < len(b.item_html("a310")) + 5000 and len(g347) < 2000
          and LONG_ID[:300] in c347 and LONG_ID[:301] not in c347 and LONG_ID[:301] not in h347 and LONG_ID[:301] not in g347, (len(c347), len(p347), len(h347), len(g347)))
    # an arrival with no words recorded
    p348, c348, g348 = plain(page_wait("a348")), plain(wait_cell("a348")), get_line("a348")
    check("words: a line that arrived with no recorded words reads as the time alone on the item page (\"arrived <time>\", the word once), the anchor line keeps its address before it", f"arrived {W_(GOT)}" in p348 and "arrived · arrived" not in p348 and "arrived arrived" not in p348
          and p348.count("arrived " + W_(GOT)) == 1 and f"{AURL} · arrived {W_(GOT + 60)}" in p348 and "arrived · arrived" not in c348, p348)
    check("words: …and a line that arrived with words keeps them: \"<words> · arrived <time>\"", f"the lease arrived · arrived {W_(GOT)}" in p346, p346)
    check("words: …in get's model line the time alone stands in the bracket, with the zone", f"[x] news of the lease ({day(0)} 08:30 {ZLAB})" in g348 and "()" not in g348, g348)

    return ran, fails

# ================================================================ part write: the write side of a list
def part_write():
    sys.path.insert(0, os.path.join(STACK, "tools"))
    tmp, T = _setup("waitlistwrite-", keywords=False)
    (T / "home/.claude/sessions").mkdir(parents=True)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time()
    DAY, HOUR = 86400.0, 3600.0
    ZONE_OFFSET = 4 * HOUR                       # the instance timezone (Asia/Dubai, "timezone" above): UTC+4, no DST
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                    "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                    "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    DESC = "- A thing\n- It lives here\n- Done when done"
    def item(i, status="open", su=None, desc=DESC, **meta):
        su = now0 - 10 * DAY if su is None else su
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": status,
                                                           "updated": su, "state_updated": su, "confirmed": su,
                                                           "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
    def mof(g): return _service_store._load(g)["metadata"]
    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    mt = lambda i: rd(i)["metadata"]
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
    logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W, until_write as UW, watchers as WK; from stackshot.model import model as MODEL; from stackshot.service import create as create_svc
    from stackshot.anchors import anchors as _anc
    from stackshot.service import store as _service_store
    from stackshot.model import ids as _model_ids
    from stackshot.core import store as _store
    from stackshot.github import ghsync as _gh
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.web.tools import brief as _wt_brief
    from stackshot.web.tools import update as _wt_update
    from stackshot.service import telling
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._refuse_if_owing = lambda debtor: None
    telling.front_sender = lambda who: False
    from stackshot.waits import wait_list as WL, wait_list_write as WLW, event_waits as EW
    from stackshot.web.tools import create as _wt_create, get as _wt_get
    from stackshot.service import gates as _gates
    BACK = "team-back"
    local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
    def day(n): return local_day(now0 + n * DAY)
    w = day
    FRONT = "home-front"
    A1, A2, A3 = "https://github.com/o/r/pull/5", "https://github.com/o/r/pull/6", "https://github.com/o/r/pull/7"
    def entry(url, items=None): return {"url": url, "items": items, "added": now0, "by": "x"}
    _anc.save({"projects/alpha": [entry(A1), entry(A2)]})        # project-wide anchors: a create and an update may wait on them
    Tm = lambda d: {"kind": "time", "until": d}
    An = lambda url, ev="PR merged": {"kind": "anchor", "anchor": url, "event": ev}
    It = lambda g: {"kind": "item", "after": g}
    Re = lambda ev="the lease": {"kind": "relay", "event": ev}
    Ev = lambda ev="recycle": {"kind": "event", "event": ev}
    def mk(**kw):
        base = dict(subject="[home] a list", description="- Goal: the list ends\n- It lives here\n- Done when done", project="projects/alpha", sender=BACK, mover=BACK, next=f"{BACK}: wait for the list", needs=[BACK])
        base.update(kw)
        return _wt_create.stackshot_create(**base)
    def gid_of(out): return re.search(r"created board#(\d+)", out).group(1) if re.search(r"created board#(\d+)", out) else re.search(r"created (\S+)", out).group(1)
    def shown_id(out):
        m = re.search(r"created (\S+)", out); return _model_ids._norm_id(m.group(1)) if m else None
    def mof_(g): return _service_store._load(g)["metadata"]
    def Mt(g): return mof_(g)
    GONE = ("waits", "wait_mode", "wait_kind", "until")
    def listed(m): return m.get("wait_kind") == "list" and WL.valid(m)
    def one_of(m): return not m.get("waits") and not m.get("wait_mode")
    item(900, needs=[BACK])
    item(901, needs=[BACK])
    item(902, status="completed", outcome="done", reason="r", outcome_text="- done")

    # ================================================================ 1. create
    out = mk(waits=[It("a900"), Re("the lease")], until=w(6))
    g1 = shown_id(out)
    m = Mt(g1)
    check("1 a list through create stores wait_kind=list, the lines, the mode all and the backstop in until, nothing of a single wait", listed(m) and m["wait_mode"] == "all" and m["until"] == w(6)
          and [ln["kind"] for ln in m["waits"]] == ["item", "relay"] and m["waits"][0]["after"] == "a900" and m["waits"][1]["event"] == "the lease" and not any(k in m for k in ("wait_anchor", "wait_event", "ask_by", "wake", "hold")), m)
    check("1 …no line carries an arrival, and the reply says what the item waits on", all("arrived" not in ln for ln in m["waits"]) and "wait list: 2 waits, all:" in out and f"backstop day {w(6)}" in out, out[-500:])
    check("1 …`get` reads it back as a wait on several things", "waiting on several things (all of 2, 0 arrived" in _wt_get.stackshot_get(g1), _wt_get.stackshot_get(g1)[:1500])
    check("1 …the model reads a waiting item with a list wait of two lines", MODEL.derive({**_service_store._load(g1), "gid": g1}).wait.kind == "list" and len(MODEL.derive({**_service_store._load(g1), "gid": g1}).waits) == 2, None)
    out = mk(waits=[Tm(w(3)), An(A1, "merged"), Ev("recycle"), It("a901"), Re()], wait_mode="any", until=w(6), subject="[home] a list of five")
    m = Mt(shown_id(out))
    check("1 all five kinds go through, in order, with wait_mode any", listed(m) and m["wait_mode"] == "any" and [ln["kind"] for ln in m["waits"]] == ["time", "anchor", "event", "item", "relay"]
          and m["waits"][1] == {"kind": "anchor", "anchor": A1, "event": "merged"} and m["waits"][2]["event"] == "recycle", m)
    out = mk(waits=json.dumps([It("a900"), Re("the lease")]), until=w(6), subject="[home] a list as text")
    check("1 a list may be passed as JSON text", listed(Mt(shown_id(out))), out[-300:])
    out = mk(waits=[], until=w(6), subject="[home] an empty list is nothing")
    check("1 waits=[] on a create is nothing to clear (the item is created as a wait on the date)", Mt(shown_id(out)).get("until") == w(6) and not Mt(shown_id(out)).get("waits"), Mt(shown_id(out)))
    out = mk(waits=[Tm(w(3)), Re()], until=w(6) + "T09:30", subject="[home] a backstop with a time of day")
    check("1 the backstop may carry a time of day", Mt(shown_id(out))["until"] == f"{w(6)}T09:30", Mt(shown_id(out)))

    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out[-300:])
        except Exception as e:
            check(name, all(x in str(e) for x in want), str(e)[:700])
    refused("1 no backstop day is refused, and the refusal says what to pass", lambda: mk(waits=[It("a900"), Re()]), "needs its backstop day", "until=YYYY-MM-DD")
    refused("1 one line is refused (a single wait is written with wait_kind)", lambda: mk(waits=[Re()], until=w(5)), "2 to 8 lines (got 1)", "wait_kind")
    refused("1 nine lines are refused", lambda: mk(waits=[Re(f"news {i}") for i in range(9)], until=w(5)), "2 to 8 lines (got 9)")
    check("1 …eight are not", listed(Mt(shown_id(mk(waits=[Re(f"news {i}") for i in range(8)], until=w(5), subject="[home] eight lines")))), None)
    refused("1 a line twice is refused, naming both", lambda: mk(waits=[Re("x"), It("a900"), Re("x")], until=w(5)), "waits[3] repeats waits[1]")
    refused("1 …an item twice, whichever way it is written", lambda: mk(waits=[It("a900"), It(_gh.shown("a900"))], until=w(5)), "waits[2] repeats waits[1]")
    check("1 …two anchor lines on one anchor with different events are two waits", listed(Mt(shown_id(mk(waits=[An(A1, "merged"), An(A1, "closed")], until=w(5), subject="[home] one anchor twice")))), None)
    refused("1 an anchor over 300 characters is refused, naming the line and the limit", lambda: mk(waits=[Re(), An(A1 + "x" * 300)], until=w(5)), "waits[2]", "anchor is at most 300 characters (got")
    refused("1 an item id over 300 characters is refused, naming the line and the limit", lambda: mk(waits=[Re(), It("a" + "9" * 300)], until=w(5)), "waits[2]", "item id is at most 300 characters")
    check("1 …300 characters exactly is the limit, not over it (an anchor of 300)", WLW.parse([An("x" * 300), Re()])[0]["anchor"] == "x" * 300, None)
    refused("1 an `arrived` is never accepted from a caller", lambda: mk(waits=[{**Re(), "arrived": {"at": 5.0, "what": "x"}}, It("a900")], until=w(5)), "waits[1]", "arrived is set by the server")
    refused("1 an unknown key in a line is refused", lambda: mk(waits=[{**Re(), "mover": "x"}, It("a900")], until=w(5)), "waits[1]", "unknown key mover")
    refused("1 an unknown kind is refused, naming the kinds", lambda: mk(waits=[{"kind": "soon"}, It("a900")], until=w(5)), "waits[1]", "kind is one of time | anchor | item | relay | event")
    refused("1 a line missing the field of its kind is refused", lambda: mk(waits=[{"kind": "item"}, Re()], until=w(5)), "waits[1]", "item line names ONE item id")
    refused("1 a line that is no object is refused", lambda: mk(waits=["a900", Re()], until=w(5)), "waits[1]", "a line is an object")
    refused("1 waits that is no list is refused", lambda: mk(waits="soon", until=w(5)), "not valid JSON")
    refused("1 …nor is an object", lambda: mk(waits=json.dumps({"kind": "relay"}), until=w(5)), "waits is a list of lines")
    refused("1 a wait_mode that is neither all nor any is refused", lambda: mk(waits=[Re(), It("a900")], until=w(5), wait_mode="some"), "wait_mode is all or any")
    refused("1 wait_mode without waits is refused", lambda: mk(wait_mode="any", until=w(5)), "wait_mode is the mode of a list and goes with waits")
    for name, kw in (("wait_kind", {"wait_kind": "relay"}), ("wait_event", {"wait_event": "x"}), ("after", {"after": ["a900"]}), ("ask_by", {"ask_by": w(4)}), ("wait_anchor", {"wait_anchor": A1})):
        refused(f"1 a list beside {name} is refused, naming it and the way out", lambda kw=kw: mk(waits=[Re(), It("a900")], until=w(5), **kw), f"does not go with {name}", "put each thing waited on in a line of waits")
    refused("1 an item that does not exist is refused, naming the line", lambda: mk(waits=[Re(), It("a9999")], until=w(5)), "waits[2]", "does not exist")
    refused("1 an item that is closed is refused, naming the line", lambda: mk(waits=[Re(), It("a902")], until=w(5)), "waits[2]", "already completed")
    refused("1 an anchor that is not on the project's list is refused as its single wait is, naming the line", lambda: mk(waits=[Re(), An(A3)], until=w(5)), "waits[2]", "is not on projects/alpha's anchors list")
    refused("1 an event that is no event is refused as its single wait is, naming the line", lambda: mk(waits=[Re(), Ev("whenever")], until=w(5)), "waits[2]")
    refused("1 a date in the past is refused, naming the line", lambda: mk(waits=[Re(), Tm(w(-1))], until=w(5)), "waits[2]", "must be in the future")
    refused("1 a date that is no date is refused, naming the line", lambda: mk(waits=[Re(), Tm("2030-02-31")], until=w(5)), "waits[2]", "until is YYYY-MM-DD")
    refused("1 a date later than the backstop day could never arrive and is refused", lambda: mk(waits=[Re(), Tm(w(8))], until=w(5)), "waits[2]", "later than the backstop day")
    refused("1 a backstop in the past is refused as any until is", lambda: mk(waits=[Re(), It("a900")], until=w(-1)), "until must be in the future")
    refused("1 an until that is no date is refused", lambda: mk(waits=[Re(), It("a900")], until="soon"), "until is YYYY-MM-DD")
    n_items_ = len(list(_store._item_files()))
    try: mk(waits=[It("a900")], until=w(5), subject="[home] refused")
    except Exception: pass
    check("1 a refused create stored nothing", len(list(_store._item_files())) == n_items_, None)

    # ================================================================ 2. update
    def bupd(i, **kw):
        if kw.get("wake") or kw.get("until") or kw.get("ask_by") or kw.get("wait_kind"): kw.setdefault("wait_reason", "the vendor replies only after that date")
        return _wt_update.stackshot_update(f"a{i}", sender=BACK, **kw)
    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    mt = lambda i: rd(i)["metadata"]
    raw = lambda i: (T / f"store/a/{i}.json").read_text()
    item(10, needs=[BACK])
    out = bupd(10, waits=[It("a900"), Re("the lease")], until=w(6))
    m = mt(10)
    check("2 an update sets a list on an item that waits on nothing: kind, lines, mode all, the backstop in until, no old wake field", listed(m) and m["wait_mode"] == "all" and m["until"] == w(6) and len(m["waits"]) == 2
          and not any(k in m for k in ("wake", "ask_by", "hold", "wait_anchor", "wait_event")), m)
    check("2 …the reply says what it waits on, and the item reads as waiting on a list", "wait list: 2 waits, all:" in out and MODEL.derive({**rd(10), "gid": "a10"}).wait.kind == "list", out[-400:])
    check("2 …get reads it back", "waiting on several things (all of 2" in _wt_get.stackshot_get("a10"), _wt_get.stackshot_get("a10")[:900])
    item(11, needs=[BACK])
    out = bupd(11, waits=json.dumps([It("a900"), Re("the lease")]), until=w(6), wait_mode="any")
    check("2 a list as JSON text with wait_mode any is the same list", listed(mt(11)) and mt(11)["wait_mode"] == "any" and mt(11)["waits"][0]["after"] == "a900", mt(11))
    check("2 …the arrival is the server's: nothing a call passed set one", all("arrived" not in ln for ln in mt(10)["waits"]), mt(10))
    # the single wait a list replaces
    item(12, needs=[BACK], wait_kind="anchor", wait_anchor=A1, wait_event="merged", until=w(5), post_wake_mover=BACK)
    out = bupd(12, waits=[An(A1, "merged"), Re("the lease")], until=w(4))
    m = mt(12)
    check("2 a list replacing an anchor wait: the list is stored, the anchor wait's own fields are gone, and the backstop is the one given (earlier than before: no renewal)", listed(m) and "wait_anchor" not in m and "wait_event" not in m and m["until"] == w(4) and m.get("post_wake_mover") == BACK, m)
    item(13, needs=[BACK], wait_kind="relay", wait_event="the vendor", until=w(5), post_wake_mover=BACK)
    out = bupd(13, waits=[Re("the lease"), It("a900")])
    m = mt(13)
    check("2 a list with no until of its own takes the backstop the item holds (a relay's ask-by day becomes the list's backstop day)", listed(m) and m["until"] == w(5) and "wait_event" not in m and "ask_by" not in m, m)
    item(14, needs=[BACK], wait_kind="item", after=["a900"], until=w(5), post_wake_mover=BACK)
    out = bupd(14, waits=[It("a900"), It("a901")])
    m = mt(14)
    check("2 a list replacing a wait on an item drops that wait's `after` (the lines hold it) and keeps the backstop", listed(m) and "after" not in m and m["until"] == w(5) and [ln["after"] for ln in m["waits"]] == ["a900", "a901"], m)
    item(15, needs=[BACK])
    refused("2 an update with no backstop anywhere is refused, and nothing is stored", lambda: bupd(15, waits=[It("a900"), Re()]), "needs its backstop day")
    check("2 …nothing was stored", not mt(15).get("waits") and not mt(15).get("wait_kind"), mt(15))
    for name, kw in (("wait_kind", {"wait_kind": "relay"}), ("wait_event", {"wait_event": "x"}), ("after", {"after": ["a900"]}), ("ask_by", {"ask_by": w(4)}), ("wake", {"wake": w(4)}), ("hold", {"hold": True}),
                     ("wait_basis", {"wait_basis": f"vendor ships {w(4)}"}), ("clear_hold", {"clear_hold": True}), ("clear_after", {"clear_after": True}), ("clear_wait", {"clear_wait": True})):
        refused(f"2 a list beside {name} is refused, naming it", lambda kw=kw: bupd(15, waits=[It("a900"), Re()], until=w(5), **kw), f"does not go with {name}")
    refused("2 until=none beside waits is refused: a list needs its backstop", lambda: bupd(15, waits=[It("a900"), Re()], until="none"), "needs its backstop day")
    refused("2 wait_mode alone is refused (send the lines again to change it)", lambda: bupd(10, wait_mode="any"), "goes with waits")
    refused("2 a closed item takes no list", lambda: _wt_update.stackshot_update("a902", sender=BACK, waits=[It("a900"), Re()], until=w(5)), "waits")
    refused("2 one line on an item with no list is refused", lambda: bupd(15, waits=[Re()], until=w(5)), "2 to 8 lines (got 1)")
    refused("2 a line twice is refused", lambda: bupd(15, waits=[Re(), Re()], until=w(5)), "waits[2] repeats waits[1]")
    refused("2 an anchor over 300 characters is refused", lambda: bupd(15, waits=[Re(), An(A1 + "y" * 300)], until=w(5)), "waits[2]", "at most 300 characters")
    refused("2 an unlisted anchor is refused, naming the line and the anchors call", lambda: bupd(15, waits=[Re(), An(A3)], until=w(5)), "waits[2]", "anchors(project=")
    refused("2 an `arrived` is refused", lambda: bupd(15, waits=[{**Re(), "arrived": {"at": 1.0, "what": "x"}}, It("a900")], until=w(5)), "arrived is set by the server")
    check("2 …a refusal changes nothing: the item is as it was", not mt(15).get("waits") and not mt(15).get("wait_kind") and not mt(15).get("until"), mt(15))

    # the mode: given, kept, defaulted; arrivals kept when the list is sent again
    item(20, needs=[BACK])
    bupd(20, waits=[Re("a"), Re("b"), Re("c")], until=w(6), wait_mode="any")
    check("2 wait_mode any is stored", mt(20)["wait_mode"] == "any", mt(20))
    bupd(20, waits=[Re("a"), Re("b"), Re("c"), Re("d")])
    check("2 sending the lines again with no wait_mode keeps the mode the item's list has", mt(20)["wait_mode"] == "any" and len(mt(20)["waits"]) == 4, mt(20))
    bupd(20, waits=[Re("a"), Re("b"), Re("c"), Re("d")], wait_mode="all")
    check("2 …and wait_mode changes it", mt(20)["wait_mode"] == "all", mt(20))
    d_ = rd(20); d_["metadata"]["waits"][0]["arrived"] = {"at": now0 - 100, "what": "a came"}; (T / "store/a/20.json").write_text(json.dumps(d_))
    bupd(20, waits=[Re("a"), Re("b"), Re("c"), Re("e")])
    check("2 sending the list again keeps what has arrived (the same line, the same time and words) and a new line has none", mt(20)["waits"][0].get("arrived") == {"at": now0 - 100, "what": "a came"} and "arrived" not in mt(20)["waits"][3], mt(20)["waits"])
    bupd(20, until=w(5))
    check("2 until alone moves the backstop day of the list, and the list is as it was", mt(20)["until"] == w(5) and listed(mt(20)) and len(mt(20)["waits"]) == 4, mt(20))
    d_ = rd(20); d_["metadata"]["next"] = "x"; 
    bupd(20, description="- Goal: the list ends\n- It lives here\n- And more\n- Done when done")
    check("2 a write of something else leaves the list as it was", listed(mt(20)) and mt(20)["until"] == w(5) and mt(20)["waits"][0].get("arrived"), mt(20))
    # an item line whose item has since closed is kept when the list is sent again; a new closed one is refused
    item(21, needs=[BACK]); bupd(21, waits=[It("a900"), It("a901")], until=w(6))
    d_ = rd(900); d_["status"] = "completed"; d_["metadata"].update(outcome="done", reason="r", outcome_text="- done"); (T / "store/a/900.json").write_text(json.dumps(d_))
    bupd(21, waits=[It("a900"), It("a901"), Re("news")])
    check("2 an item line the stored list holds is kept when the list is sent again, though its item has closed since (the watchers end the line)", [ln["kind"] for ln in mt(21)["waits"]] == ["item", "item", "relay"], mt(21))
    refused("2 …a new line on a closed item is refused", lambda: bupd(21, waits=[It("a900"), It("a901"), It("a902")], until=w(6)), "waits[3]", "already completed")
    d_ = rd(900); d_["status"] = "open"; [d_["metadata"].pop(k) for k in ("outcome", "reason", "outcome_text")]; (T / "store/a/900.json").write_text(json.dumps(d_))

    # ================================================================ 3. removing lines
    def fresh(i, waits, mode="all", until=None, **kw):
        item(i, needs=[BACK]); bupd(i, waits=waits, until=until or w(6), wait_mode=mode, **kw)
        return i
    fresh(30, [Re("a"), Re("b"), Re("c")])
    out = bupd(30, waits=[Re("a"), Re("c")])
    check("3 a list with a line taken out and two left is still a list", listed(mt(30)) and [ln["event"] for ln in mt(30)["waits"]] == ["a", "c"], mt(30))
    out = bupd(30, waits=[Re("c")])
    m = mt(30)
    check("3 a list left with one line is stored as the single wait that line is (a relay wait): no list, no mode, no wait_kind=list", m.get("wait_kind") == "relay" and m.get("wait_event") == "c" and one_of(m) and m.get("until") == w(6), m)
    check("3 …the reply says so, and the item reads as a single relay wait", "down to one wait" in out and MODEL.derive({**rd(30), "gid": "a30"}).wait.kind == "relay", out[-400:])
    check("3 …and `get` reads a single wait, not a list", "several things" not in _wt_get.stackshot_get("a30"), _wt_get.stackshot_get("a30")[:900])
    # each kind
    fresh(31, [An(A1, "merged"), Re("a")])
    bupd(31, waits=[An(A1, "merged")])
    m = mt(31)
    check("3 one anchor line left: an anchor wait with its anchor and event, the backstop kept", m.get("wait_kind") == "anchor" and m.get("wait_anchor") == A1 and m.get("wait_event") == "merged" and one_of(m) and m.get("until") == w(6), m)
    fresh(32, [It("a901"), Re("a")])
    bupd(32, waits=[It("a901")])
    m = mt(32)
    check("3 one item line left: a wait on that item (kind item, after), the backstop kept", m.get("wait_kind") == "item" and m.get("after") == ["a901"] and one_of(m) and m.get("until") == w(6), m)
    fresh(33, [Ev("recycle"), Re("a")])
    bupd(33, waits=[Ev("recycle")])
    m = mt(33)
    check("3 one event line left: an event wait with its phrase, the backstop kept", m.get("wait_kind") == "event" and m.get("wait_event") == "recycle" and one_of(m) and m.get("until") == w(6), m)
    fresh(34, [Tm(w(3)), Re("a")])
    bupd(34, waits=[Tm(w(3))])
    m = mt(34)
    check("3 one time line left: the wait is that date alone (until the line's date, no kind, no list)", not m.get("wait_kind") and m.get("until") == w(3) and one_of(m), m)
    fresh(35, [Tm(w(3)), Re("a")], until=w(3))
    d_ = rd(35); d_["metadata"]["waits"][0]["until"] = w(9); (T / "store/a/35.json").write_text(json.dumps(d_))     # a stored list the backstop was moved in front of
    bupd(35, waits=[Tm(w(9))])
    check("3 a date later than the list's backstop (a stored list the backstop was moved in front of) is never kept past it when it is the line left: the single wait ends on the backstop day", mt(35).get("until") == w(3) and not mt(35).get("wait_kind"), mt(35))
    fresh(36, [Re("a"), Re("b")], until=w(6)); d_ = rd(36); d_["metadata"]["until"] = w(6) + "T09:30"; (T / "store/a/36.json").write_text(json.dumps(d_))
    bupd(36, waits=[Ev("recycle")])
    check("3 …a list whose backstop carries a time of day, left with one relay or event line: that wait takes its ask-by day alone", mt(36).get("until") == w(6) and mt(36).get("wait_kind") == "event", mt(36))
    # the single wait works as one
    fresh(37, [It("a901"), Re("a")])
    bupd(37, waits=[It("a901")])
    out = bupd(37, clear_wait=True, clear_after=True)
    check("3 the single wait a list was reduced to ends with clear_wait and clear_after as any wait on an item does", not any(k in mt(37) for k in ("wait_kind", "after", "until", "waits", "wait_mode")), mt(37))
    fresh(38, [Re("a"), Re("b")])
    bupd(38, waits=[Re("b")])
    bupd(38, wait_kind="relay", wait_event="the vendor", until=w(5))
    check("3 …and is replaced by another single wait the way any single wait is", mt(38).get("wait_event") == "the vendor" and mt(38).get("until") == w(5) and one_of(mt(38)), mt(38))
    # a line that had arrived, and none
    fresh(39, [Re("a"), Re("b")])
    d_ = rd(39); d_["metadata"]["waits"][0]["arrived"] = {"at": now0 - 50, "what": "a came"}; (T / "store/a/39.json").write_text(json.dumps(d_))
    out = bupd(39, waits=[Re("a")])
    check("3 one line left that had already arrived: the group is over, the wait is cleared as clear_wait clears it", not any(k in mt(39) for k in ("wait_kind", "waits", "wait_mode", "until", "wait_event")) and "cleared" in out, (mt(39), out[-300:]))
    for i_, how in ((40, {"waits": []}), (41, {"waits": "none"}), (42, {"clear_wait": True}), (43, {"waits": json.dumps([])}), (44, {"waits": "-"})):
        fresh(i_, [Re("a"), Re("b")])
        out = bupd(i_, **how)
        check(f"3 {how} ends the wait: nothing of the list or its backstop is left, and the item reads as waiting on nothing", not any(k in mt(i_) for k in ("wait_kind", "waits", "wait_mode", "until")) and MODEL.derive({**rd(i_), "gid": f"a{i_}"}).wait is None, mt(i_))
    item(45, needs=[BACK])
    before_ = raw(45)
    out = bupd(45, waits=[])
    check("3 waits=[] on an item with no list changes nothing", mt(45).get("wait_kind") is None and not mt(45).get("waits"), mt(45))
    item(46, needs=[BACK], wait_kind="relay", wait_event="the vendor", until=w(5), post_wake_mover=BACK)
    bupd(46, waits=[])
    check("3 …and leaves a single wait alone", mt(46).get("wait_kind") == "relay" and mt(46).get("until") == w(5), mt(46))
    refused("3 waits=[] beside a new single wait is refused", lambda: bupd(46, waits=[], wait_kind="relay", wait_event="x", until=w(4)), "does not go with wait_kind")
    refused("3 waits=[] with wait_mode is refused", lambda: bupd(40, waits=[], wait_mode="any"), "does not go with a clear")
    # no list of one is ever stored, whichever way
    import itertools
    all_lists = []
    for p_ in sorted(T.glob("store/*/*.json")):
        mm = json.loads(p_.read_text()).get("metadata") or {}
        if mm.get("waits") is not None: all_lists.append((p_.name, len(mm["waits"])))
    check("3 no item stores a list of fewer than two lines", all(n >= 2 for _, n in all_lists) and len(all_lists) >= 8, all_lists)
    check("3 …and no item stores waits beside a kind that is not list", all(json.loads(p_.read_text())["metadata"].get("wait_kind") == "list" for p_ in T.glob("store/*/*.json") if json.loads(p_.read_text())["metadata"].get("waits") is not None), None)

    # ================================================================ 4. what did not change
    item(50, needs=[BACK])
    bupd(50, wait_kind="relay", wait_event="the vendor", until=w(5), post_wake_mover=BACK)
    check("4 a relay wait is written as before: its kind, its event and the day as until, no list field", mt(50).get("wait_kind") == "relay" and mt(50).get("wait_event") == "the vendor" and mt(50).get("until") == w(5) and one_of(mt(50)), mt(50))
    item(51, needs=[BACK])
    bupd(51, wait_kind="anchor", wait_anchor=A1, wait_event="merged", until=w(5), post_wake_mover=BACK)
    check("4 an anchor wait is written as before", mt(51).get("wait_kind") == "anchor" and mt(51).get("wait_anchor") == A1 and mt(51).get("until") == w(5) and one_of(mt(51)), mt(51))
    item(52, needs=[BACK])
    bupd(52, after=["a901"], until=w(5))
    check("4 a wait on an item is written as before (after, and the backstop as until)", mt(52).get("after") == ["a901"] and mt(52).get("until") == w(5) and one_of(mt(52)), mt(52))
    item(53, needs=[BACK])
    bupd(53, wait_kind="event", wait_event="recycle", until=w(5), post_wake_mover=BACK)
    check("4 an event wait is written as before", mt(53).get("wait_kind") == "event" and mt(53).get("wait_event") == "recycle" and mt(53).get("until") == w(5) and one_of(mt(53)), mt(53))
    item(54, needs=[BACK])
    bupd(54, until=w(4))
    check("4 a date alone is a wait as before: until, no kind", mt(54).get("until") == w(4) and not mt(54).get("wait_kind") and one_of(mt(54)), mt(54))
    for i_ in (50, 51, 53, 54):
        bupd(i_, clear_wait=True)
    check("4 clear_wait ends each of them as before", all(not any(k in mt(i_) for k in ("wait_kind", "wait_anchor", "wait_event", "until")) for i_ in (50, 51, 53, 54)), [mt(i_) for i_ in (50, 51, 53, 54)])
    check("4 the single-wait parameters of both tools are unchanged and the list has two of its own (waits, wait_mode), after the old ones",
          all(p in _wt_update.stackshot_update.__code__.co_varnames for p in ("wait_kind", "wait_anchor", "wait_event", "ask_by", "until", "waits", "wait_mode")), None)
    # a list is not undone by a write that does not mean it
    refused("4 until=none on an item that stores a list is refused (a list needs its backstop), the list is as it was", lambda: bupd(10, until="none"), "wait on a list that does not hold", "clear_wait=true")
    check("4 …nothing changed", listed(mt(10)) and mt(10)["until"] == w(6), mt(10))
    refused("4 clear_wake on an item that stores a list is refused the same way", lambda: bupd(10, clear_wake=True), "wait on a list that does not hold")
    bupd(10, clear_hold=True)
    check("4 clear_hold on an item that stores a list changes nothing of the list", listed(mt(10)) and mt(10)["until"] == w(6), mt(10))
    item(60, needs=[BACK], wait_kind="list", wait_mode="all", waits=[Re("only one")], until=w(5), post_wake_mover=BACK)      # hand-edited: a list that does not hold
    out = bupd(60, description="- Goal: the list ends\n- It lives here\n- And more\n- Done when done")
    check("4 a stored list that does not hold is no reason to refuse a write that does not touch it", "more" in rd(60)["description"], out[-300:])
    out = bupd(60, waits=[Re("a"), Re("b")], until=w(4))
    check("4 …and a new list replaces it", listed(mt(60)) and len(mt(60)["waits"]) == 2, mt(60))
    # a close drops the list with the rest of the wait
    out = _wt_update.stackshot_update("a20", sender=BACK, status="completed", outcome="done", reason="the work is done", outcome_text="- done")
    check("4 a close drops the list, its mode and its backstop with the wait", not any(k in mt(20) for k in ("waits", "wait_mode", "wait_kind", "until")), mt(20))
    fresh(955, [Re("a"), Re("b")])
    out955 = _wt_update.stackshot_update("a955", sender=BACK, status="completed", outcome="done", reason="the work is done", outcome_text="- done", waits=[])
    check("4 …a close that also sends waits=[] on a stored list closes it and adds no line about a wait to the reply (a closed item waits on nothing: _list_note says nothing for it)",
          rd(955)["status"] == "completed" and not any(k in mt(955) for k in ("waits", "wait_mode", "wait_kind", "until")) and "the wait on a list is cleared" not in out955 and "wait list:" not in out955, out955[-400:])
    # the watchers end a list the tool wrote
    from stackshot.service import telling
    SENT = []; telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
    item(70, needs=[BACK]); item(71, needs=[BACK])
    bupd(70, waits=[It("a71"), Re("news")], until=w(6), wait_mode="any")
    d_ = rd(71); d_["status"] = "completed"; d_["metadata"].update(outcome="done", reason="r", outcome_text="- done"); (T / "store/a/71.json").write_text(json.dumps(d_))
    from stackshot.service import wakes as wakes_svc
    wakes_svc.release_after("a71", "done", "", "home-front")
    check("4 a list the tool wrote ends the way the read side says: the item it waits on closes, the mode is any, so the item comes back with what arrived and nothing of the wait is left",
          not any(k in mt(70) for k in ("waits", "wait_mode", "wait_kind", "until")) and "any of 2 arrived" in str(mt(70).get("woke") or mt(70)), mt(70))

    # ---- what the mutation checks showed the sections above did not pin
    got_, why_ = WL.write_line({"kind": "time", "until": w(3), "arrived": {"at": 1.0, "what": "x"}})
    check("4 the stored-line reader the write path uses never takes an `arrived` from the caller (it is dropped, not kept)", got_ == {"kind": "time", "until": w(3)} and why_ == "", (got_, why_))
    fresh(80, [An(A1, "merged"), Re("a")])
    _anc.save({"projects/alpha": [entry(A2)]})                  # the anchor the stored line waits on is no longer on the list
    bupd(80, waits=[An(A1, "merged"), Re("a")], wait_mode="any")
    check("4 a line the stored list holds is not judged again: sending the list again with a new mode works though its anchor has left the list", mt(80)["wait_mode"] == "any" and len(mt(80)["waits"]) == 2, mt(80))
    refused("4 …while a new anchor line that is not on the list is refused", lambda: bupd(80, waits=[An(A1, "merged"), Re("a"), An(A3, "merged")]), "waits[3]")
    _anc.save({"projects/alpha": [entry(A1), entry(A2)]})
    fresh(81, [Re("a"), Re("b")], until=w(6))
    bupd(81, waits=[Re("a")], until=w(5) + "T10:00")
    check("4 a relay line left alone takes the ask-by day alone, not a time of day", mt(81).get("wait_kind") == "relay" and mt(81).get("until") == w(5) and "T" not in str(mt(81).get("until")), mt(81))
    refused("4 until=none beside a list is refused with its own reason (the backstop cannot go)", lambda: bupd(10, waits=[Re("a"), Re("b")], clear_wake=True), "cannot be none")
    item(82, needs=[BACK], wait_kind="relay", wait_event="old news", until=w(6), hold=True, hold_set=now0, wait_basis="a basis the old wait had")
    bupd(82, waits=[Re("a"), Re("b")], until=w(6))
    check("4 a list that replaces a single wait leaves no hold or wait_basis of that wait behind", listed(mt(82)) and not any(k in mt(82) for k in ("hold", "hold_set", "wait_basis", "wait_event")), mt(82))
    fresh(83, [Tm(w(3)), Re("a")])
    d_ = rd(83); d_["metadata"]["waits"][0]["until"] = w(-1); (T / "store/a/83.json").write_text(json.dumps(d_))      # the date line has come since it was written
    out = bupd(83, waits=[Tm(w(-1))])
    check("4 the one line left is a date that has come: the wait is over and cleared, never stored as a wait on a past day", not any(k in mt(83) for k in ("waits", "wait_mode", "wait_kind", "until")) and "has come" in out, (mt(83), out[-300:]))
    # a list names its blockers: the check on a wait with no blocker (which asks a model) is not made for one
    from stackshot.waits import self_wait as SW; from stackshot.router import router as R
    CALLS_ = []
    def _no_claude(*a, **k): raise AssertionError("the real model was called")
    R.run_call = _no_claude
    SW._run = lambda message: (CALLS_.append(message), {"status": "ok", "text": json.dumps({"can_do_now": True, "reason": "nothing blocks it"})})[1]
    item(84, needs=[BACK], mover=BACK)
    try:
        bupd(84, until=w(6), next=f"{BACK}: apply the step on {w(6)}")
        CALLS_.append("control did not refuse")
    except Exception:
        pass
    check("4 control: a single dated wait with no blocker is judged by the model (the stub is reached)", len(CALLS_) == 1 and "control" not in str(CALLS_[0]), CALLS_)
    CALLS_.clear()
    out = bupd(84, waits=[Re("a"), Re("b")], until=w(6), next=f"{BACK}: apply the step on {w(6)}")
    check("4 …and a list through update makes no such call: its lines are its blockers", not CALLS_ and listed(mt(84)), (CALLS_, mt(84)))
    out = mk(waits=[Re("a"), Re("b")], until=w(6), next=f"{BACK}: apply the step on {w(6)}", subject="[home] a list names its blockers")
    check("4 …nor does a list through create", not CALLS_ and listed(Mt(shown_id(out))), (CALLS_, out[-200:]))

    # ================================================================ 6. the fix round (the loop test reads a list's item lines; what a list may be written over, resent or given)
    # ---- 6a the loop test: an item line of a list is a link like `after`, whichever way the two items wait on each other
    def loopers(base, n):
        for i_ in range(base, base + n): item(i_, needs=[BACK])
        return [f"a{i_}" for i_ in range(base, base + n)]
    def bu(g, **kw): return _wt_update.stackshot_update(g, sender=BACK, **kw)
    A_, B_ = loopers(100, 2)
    bu(A_, waits=[It(B_), Re("lp")], until=w(6))
    refused("6a list then list: B cannot list A while A lists B", lambda: bu(B_, waits=[It(A_), Re("lq")], until=w(6)), "a loop", "waits[1]")
    check("6a …and B stored nothing", not mt(101).get("waits"), mt(101))
    A_, B_ = loopers(102, 2)
    bu(B_, waits=[It(A_), Re("lq")], until=w(6))
    refused("6a …the other way round, too", lambda: bu(A_, waits=[It(B_), Re("lp")], until=w(6)), "a loop", "waits[1]")
    A_, B_ = loopers(104, 2)
    bu(A_, waits=[It(B_), Re("lp")], until=w(6))
    refused("6a list then single: B cannot wait on A (after) while A lists B", lambda: bu(B_, after=[A_], until=w(6)), "a loop")
    check("6a …and B stored no after", not mt(105).get("after"), mt(105))
    A_, B_ = loopers(106, 2)
    bu(B_, after=[A_], until=w(6))
    refused("6a single then list: A cannot list B while B waits on A", lambda: bu(A_, waits=[It(B_), Re("lp")], until=w(6)), "a loop", "waits[1]")
    A_, B_ = loopers(108, 2)
    bu(A_, after=[B_], until=w(6))
    refused("6a …single then list, the other order", lambda: bu(B_, waits=[It(A_), Re("lq")], until=w(6)), "a loop", "waits[1]")
    A_, B_ = loopers(110, 2)
    bu(B_, waits=[It(A_), Re("lq")], until=w(6))
    refused("6a …list then single, the other order", lambda: bu(A_, after=[B_], until=w(6)), "a loop")
    A_, B_, C_ = loopers(112, 3)
    bu(A_, waits=[Re("x"), It(B_)], until=w(6)); bu(B_, after=[C_], until=w(6))
    refused("6a a loop through a third item (A lists B, B waits on C): C cannot list A", lambda: bu(C_, waits=[It(A_), Re("lr")], until=w(6)), "a loop", "waits[1]")
    refused("6a …nor wait on A with after", lambda: bu(C_, after=[A_], until=w(6)), "a loop")
    A_, B_, C_ = loopers(115, 3)
    bu(A_, after=[B_], until=w(6)); bu(B_, waits=[Re("x"), It(C_)], until=w(6))
    refused("6a …the same with the list in the middle (A waits on B, B lists C): C cannot list A", lambda: bu(C_, waits=[It(A_), Re("lr")], until=w(6)), "a loop", "waits[1]")
    A_, B_, C_ = loopers(118, 3)
    bu(A_, waits=[It(B_), Re("x")], until=w(6)); bu(B_, waits=[It(C_), Re("y")], until=w(6))
    refused("6a …lists all the way round (A lists B, B lists C): C cannot list A", lambda: bu(C_, waits=[It(A_), Re("lr")], until=w(6)), "a loop")
    refused("6a …a second item line of the same list closes the loop as well (C lists X and A)", lambda: bu(C_, waits=[Re("z"), It(A_), It("a901")], until=w(6)), "a loop", "waits[2]")
    # a list whose item line is not part of a loop is accepted
    A_, B_, C_ = loopers(121, 3)
    bu(A_, waits=[It(B_), Re("x")], until=w(6))
    bu(C_, waits=[It(A_), Re("lr")], until=w(6))
    check("6a a list whose item line leads into a chain that does not come back is accepted (C lists A, A lists B)", listed(mt(123)) and mt(123)["waits"][0]["after"] == A_, mt(123))
    bu(B_, waits=[It("a901"), Re("y")], until=w(6))
    check("6a …and so is the tail of the chain pointing elsewhere", listed(mt(122)), mt(122))
    A_, B_ = loopers(124, 2)
    bu(A_, waits=[It(B_), Re("x")], until=w(6))
    d_ = rd(124); d_["metadata"]["waits"][0]["arrived"] = {"at": now0 - 5, "what": "b closed"}; (T / "store/a/124.json").write_text(json.dumps(d_))
    bu(B_, waits=[It(A_), Re("lq")], until=w(6))
    check("6a an item line that has arrived is no link any more: B may list A (the line of A for B is over)", listed(mt(125)), mt(125))
    check("6a wait_list.item_ids: the open item lines of a list that holds, in stored order, and none for one that does not hold or is no list",
          WL.item_ids({"wait_kind": "list", "wait_mode": "all", "until": w(6), "waits": [{"kind": "item", "after": "a1"}, {"kind": "relay", "event": "x"}, {"kind": "item", "after": "a2", "arrived": {"at": 5.0, "what": "x"}}, {"kind": "item", "after": "a3"}]}) == ["a1", "a3"]
          and WL.item_ids({"wait_kind": "list", "wait_mode": "all", "until": w(6), "waits": [{"kind": "item", "after": "a1"}]}) == [] and WL.item_ids({"until": w(6)}) == [] and WL.item_ids({}) == [], None)

    # ---- 6b a single wait written over a stored list replaces it (the list and its mode go; the same call as a list over a single wait)
    for i_, kw, kind_ in ((130, dict(wait_kind="relay", wait_event="the vendor"), "relay"), (131, dict(wait_kind="anchor", wait_anchor=A1, wait_event="merged"), "anchor"),
                          (132, dict(wait_kind="event", wait_event="recycle"), "event"), (133, dict(wait_kind="item", after=["a901"]), "item"), (134, dict(after=["a901"]), "item")):
        fresh(i_, [Re("a"), Re("b")], mode="any")
        bupd(i_, **kw)
        check(f"6b a {kind_} wait written over a stored list ({sorted(kw)}) replaces it: no waits, no wait_mode, the kind is {kind_}, the backstop is kept", mt(i_).get("wait_kind") == kind_ and one_of(mt(i_)) and mt(i_).get("until") == w(6), mt(i_))
        check(f"6b …and the item reads as that single wait", MODEL.derive({**rd(i_), "gid": f"a{i_}"}).wait.kind == kind_, mt(i_))
    fresh(135, [Re("a"), Re("b")])
    bupd(135, wait_kind="none")
    check("6b wait_kind=none over a stored list drops the list with it (the kind and the lines go, the backstop with the kind as for a single wait), nothing of a list is left", not any(k in mt(135) for k in ("waits", "wait_mode", "wait_kind")), mt(135))
    fresh(136, [Re("a"), Re("b")])
    bupd(136, wait_event="the vendor")
    check("6b a wait_event alone over a stored list leaves no list of one kind with the lines of another", not mt(136).get("waits") and not mt(136).get("wait_mode") and mt(136).get("wait_kind") != "list", mt(136))
    fresh(1360, [Re("a"), Re("b")])
    bupd(1360, wait_anchor=A1)
    check("6b a wait_anchor alone over a stored list drops the list and its kind, as it would leave an item that stored no list (nothing of a list is left)", one_of(mt(1360)) and mt(1360).get("wait_kind") != "list" and mt(1360).get("wait_anchor") == A1, mt(1360))
    fresh(137, [Re("a"), Re("b")], mode="any")
    bupd(137, until=w(5))
    check("6b the backstop day alone (until) is no single wait: the list stays as it was", listed(mt(137)) and mt(137)["until"] == w(5) and mt(137)["wait_mode"] == "any" and len(mt(137)["waits"]) == 2, mt(137))
    fresh(138, [Re("a"), Re("b")])
    bupd(138, clear_after=True)
    check("6b clear_after on an item that stores a list leaves the list as it was", listed(mt(138)) and len(mt(138)["waits"]) == 2, mt(138))
    fresh(139, [Re("a"), Re("b")])
    bupd(139, after="none")
    check("6b …and so does after=none (a clear of after is no single wait)", listed(mt(139)) and len(mt(139)["waits"]) == 2, mt(139))

    # ---- 6c a repeat is judged after an event line is in its canonical form; a stored list sent again is never a repeat of itself
    fresh(140, [Ev("recycle"), Re("a")])
    refused("6c `recycle` and `Recycle` are the one event: a list with both is refused as a repeat", lambda: bu("a141" if (item(141, needs=[BACK]) or True) else "", waits=[Ev("recycle"), Ev("Recycle")], until=w(6)), "waits[2] repeats waits[1]", "event line twice")
    check("6c …and nothing was stored", not mt(141).get("waits"), mt(141))
    bupd(140, waits=[Ev("Recycle"), Re("a")])
    check("6c a stored event line sent again in other letters is the same line (no repeat, stored once in its canonical form)", [ln["event"] for ln in mt(140)["waits"]] == ["recycle", "a"], mt(140))
    d_ = rd(140); d_["metadata"]["waits"] = [{"kind": "event", "event": "recycle"}, {"kind": "event", "event": "recycle"}, {"kind": "relay", "event": "a"}]; (T / "store/a/140.json").write_text(json.dumps(d_))      # a list stored with a line twice (before the check was made after canonicalizing)
    bupd(140, waits=[Ev("recycle"), Ev("recycle"), Re("a")], wait_mode="any")
    check("6c a stored list that holds a line twice is sent again as it stands: no refusal as a repeat of itself", mt(140)["wait_mode"] == "any" and len(mt(140)["waits"]) == 3, mt(140))
    refused("6c …but a third copy is a repeat", lambda: bupd(140, waits=[Ev("recycle"), Ev("recycle"), Ev("recycle"), Re("a")]), "waits[3] repeats waits[1]")
    check("6c WLW.duplicate: the first repeat and its first copy, none for distinct lines, none for a line held as often as it is sent",
          WLW.duplicate([Re("a"), Re("b"), Re("a")]) == (1, 3) and WLW.duplicate([Re("a"), Re("b")]) is None and WLW.duplicate([Re("a"), Re("a")], __import__("collections").Counter({WL.line_key(Re("a")): 2})) is None
          and WLW.duplicate([Re("a"), Re("a"), Re("a")], __import__("collections").Counter({WL.line_key(Re("a")): 2})) == (1, 3), None)

    # ---- 6d a text nested too deep is no list (a plain refusal, never a raw RecursionError)
    bomb_ = "[" * 100000
    refused("6d a JSON text nested 100000 deep is refused as text that is no list, on a create", lambda: mk(waits=bomb_, until=w(5)), "waits is not valid JSON")
    item(150, needs=[BACK])
    refused("6d …and on an update", lambda: bupd(150, waits=bomb_, until=w(5)), "waits is not valid JSON")
    check("6d …the lines of such a text are none and the write has stored nothing", WLW.event_phrases(bomb_) == [] and not mt(150).get("waits"), mt(150))
    try: WLW.parse(bomb_); check("6d parse refuses it with a ValueError", False, None)
    except ValueError as e: check("6d parse refuses it with a ValueError", "not valid JSON" in str(e), str(e)[:200])
    except RecursionError: check("6d parse refuses it with a ValueError", False, "RecursionError")
    refused("6d a list of lists nested 500 deep is refused as lines that are no object", lambda: bupd(150, waits=json.dumps([[[[[]]]]]), until=w(5)), "a line is an object")

    # ---- 6e an empty list is a clear everywhere: the text "[]" too, and a list of dates is judged as a date wait
    check("6e clearing(): [], the text [] (with spaces), none, clear and - are clears (any case); a list of lines, the empty text and nothing are not",
          all(WLW.clearing(x) for x in ([], "[]", " [ ] ", "[\n]", "none", "None", "CLEAR", "Clear", "-", " - ")) and not any(WLW.clearing(x) for x in ([Re()], json.dumps([Re()]), "", "   ", None, "[1]", "[[]]", "soon")), None)
    check("6e judged_as(): a list with a line that is not a date, a text that does not parse: list; dates only, a clear, nothing: none",
          WLW.judged_as([Tm(w(3)), Re()]) == "list" and WLW.judged_as(json.dumps([Tm(w(3)), It("a900")])) == "list" and WLW.judged_as("soon") == "list" and WLW.judged_as([Tm(w(3)), Tm(w(4))]) == ""
          and WLW.judged_as([]) == "" and WLW.judged_as("[]") == "" and WLW.judged_as(None) == "" and WLW.judged_as("none") == "", None)
    fresh(160, [Re("a"), Re("b")])
    out = bupd(160, waits="[]")
    check("6e waits=\"[]\" (the text of an empty list) clears a stored list as waits=[] does", not any(k in mt(160) for k in ("wait_kind", "waits", "wait_mode", "until")) and "cleared" in out, (mt(160), out[-300:]))
    out = mk(waits="[]", until=w(6), subject="[home] an empty list as text is nothing")
    check("6e …and on a create it is nothing to clear", Mt(shown_id(out)).get("until") == w(6) and not Mt(shown_id(out)).get("waits") and not Mt(shown_id(out)).get("wait_kind"), Mt(shown_id(out)))
    CALLS_.clear()
    item(161, needs=[BACK], mover=BACK)
    try: bupd(161, waits="[]", until=w(6), next=f"{BACK}: apply the step on {w(6)}"); CALLS_.append("not refused")
    except Exception as e: CALLS_.append(("refused", str(e)[:200]))
    check("6e waits=\"[]\" beside a date is no list: the date is a plain date wait and is judged as one (the model is asked)", len(CALLS_) == 2 and CALLS_[0].startswith("Now:") and CALLS_[1][0] == "refused" and "can be done now" in CALLS_[1][1], CALLS_)
    CALLS_.clear()
    item(162, needs=[BACK], mover=BACK)
    try: bupd(162, waits=[Tm(w(3)), Tm(w(4))], until=w(6), next=f"{BACK}: apply the step on {w(6)}"); CALLS_.append("not refused")
    except Exception as e: CALLS_.append(("refused", str(e)[:200]))
    check("6e a list of dates only is judged as a date wait is: the model is asked, and a step that can be done now is refused", len(CALLS_) == 2 and CALLS_[0].startswith("Now:") and CALLS_[1][0] == "refused" and "can be done now" in CALLS_[1][1] and not mt(162).get("waits"), (CALLS_, mt(162)))
    CALLS_.clear()
    item(163, needs=[BACK], mover=BACK)
    out = bupd(163, waits=[Tm(w(3)), Re("a")], until=w(6), next=f"{BACK}: apply the step on {w(6)}")
    check("6e …while a list with one line that is not a date still makes no such call", not CALLS_ and listed(mt(163)), (CALLS_, mt(163)))
    CALLS_.clear()
    try: mk(waits=[Tm(w(3)), Tm(w(4))], until=w(6), next=f"{BACK}: apply the step on {w(6)}", subject="[home] a list of dates only"); CALLS_.append("not refused")
    except Exception as e: CALLS_.append(("refused", str(e)[:200]))
    check("6e a list of dates only on a create is judged the same way: a dated step with no wait_reason is refused as it is beside a date alone", len(CALLS_) == 1 and CALLS_[0][0] == "refused" and "needs its reason" in CALLS_[0][1], CALLS_)
    CALLS_.clear()
    try: mk(waits=[Tm(w(3)), Re("a")], until=w(6), next=f"{BACK}: apply the step on {w(6)}", subject="[home] a list of a date and a relay")
    except Exception as e: CALLS_.append(("refused", str(e)[:200]))
    check("6e …and a list with a line that is not a date is not", not CALLS_, CALLS_)
    CALLS_.clear()

    # ---- 6f the backstop moved earlier by until alone, past a time line
    fresh(170, [Tm(w(5)), Re("a")], until=w(6))
    refused("6f until alone, earlier than a time line the stored list holds, is refused as the same list sent with it is", lambda: bupd(170, until=w(4)), "waits[1] is a date", "later than the backstop day", "an earlier date or a later until")
    check("6f …and nothing changed", mt(170)["until"] == w(6) and listed(mt(170)), mt(170))
    refused("6f …through waits as before", lambda: bupd(170, waits=[Tm(w(5)), Re("a")], until=w(4)), "waits[1] is a date", "later than the backstop day")
    bupd(170, until=w(5))
    check("6f until alone on the day of the time line, or later, is accepted", mt(170)["until"] == w(5), mt(170))
    fresh(171, [Re("a"), Tm(w(5)), Tm(w(3))], until=w(6))
    refused("6f …the refusal names the line (the second of three)", lambda: bupd(171, until=w(4)), "waits[2] is a date")
    d_ = rd(171); d_["metadata"]["waits"][1]["arrived"] = {"at": now0 - 5, "what": "the date came"}; (T / "store/a/171.json").write_text(json.dumps(d_))
    bupd(171, until=w(4))
    check("6f a time line that has arrived no longer holds the backstop back", mt(171)["until"] == w(4), mt(171))
    fresh(172, [Tm(w(5)), Re("a")], until=w(6))
    bupd(172, wait_kind="relay", wait_event="the vendor", until=w(4))
    check("6f a single wait with its own date over the list is no write of the list's backstop: it replaces the list", mt(172).get("wait_kind") == "relay" and mt(172).get("until") == w(4) and one_of(mt(172)), mt(172))
    fresh(173, [Tm(w(5)), Re("a")], until=w(6))
    bupd(173, after=["a901"], until=w(4))
    check("6f …a wait on an item with an earlier day too (its day is the wake a time line is judged against only when the list stays)", mt(173).get("after") == ["a901"] and mt(173).get("until") == w(4) and one_of(mt(173)), mt(173))
    fresh(174, [Tm(w(5)), Re("a")], until=w(6))
    bupd(174, wait_kind="anchor", wait_anchor=A1, wait_event="merged", until=w(4))
    check("6f …and an anchor wait", mt(174).get("wait_kind") == "anchor" and mt(174).get("until") == w(4) and one_of(mt(174)), mt(174))
    fresh(175, [Tm(w(5)), Re("a")], until=w(6))
    bupd(175, clear_wait=True)
    check("6f …and clear_wait clears the list (nothing is judged against a backstop that is going)", not mt(175).get("waits"), mt(175))

    # ---- 6g the values of a line: text only, within the limit, of the fields of its kind
    for name_, line_, want_ in (("an event that is an object", {"kind": "relay", "event": {"a": 1}}, "event is text (got dict)"), ("an event that is a list", {"kind": "relay", "event": ["x"]}, "event is text (got list)"),
                                ("an event that is a number", {"kind": "event", "event": 5}, "event is text (got int)"), ("an anchor that is a number", {"kind": "anchor", "anchor": 5, "event": "x"}, "anchor is text (got int)"),
                                ("an anchor event that is a list", {"kind": "anchor", "anchor": A1, "event": [1]}, "event is text (got list)"), ("an until that is a number", {"kind": "time", "until": 20301120}, "until is text (got int)"),
                                ("an item id that is a number", {"kind": "item", "after": 900}, "item id is text (got int)"), ("an item id that is a list", {"kind": "item", "after": ["a900"]}, "item id is text (got list)"),
                                ("an event that is true", {"kind": "relay", "event": True}, "event is text (got bool)")):
        refused(f"6g {name_} is refused, naming the line", lambda l=line_: bupd(150, waits=[Re("ok"), l], until=w(5)), "waits[2]", want_)
        refused(f"6g …on a create too", lambda l=line_: mk(waits=[Re("ok"), l], until=w(5)), "waits[2]", want_)
    refused("6g an event over 300 characters is refused, naming the line and the limit (a relay line)", lambda: bupd(150, waits=[Re("ok"), Re("e" * 301)], until=w(5)), "waits[2]", "event is at most 300 characters (got 301)")
    refused("6g …an event line", lambda: bupd(150, waits=[Re("ok"), Ev("e " * 151)], until=w(5)), "waits[2]", "event is at most 300 characters")
    refused("6g …the event of an anchor line", lambda: bupd(150, waits=[Re("ok"), An(A1, "e" * 301)], until=w(5)), "waits[2]", "event is at most 300 characters")
    check("6g …300 characters exactly is the limit, not over it", WLW.parse([Re("e" * 300), Re("f")])[0]["event"] == "e" * 300 and WLW.parse([An(A1, "e" * 300), Re("f")])[0]["event"] == "e" * 300, None)
    check("6g …and the text counts as it is read (runs of white space are one space)", WLW.parse([Re("e" + " " * 400 + "f"), Re("g")])[0]["event"] == "e f", None)
    refused("6g an until on a relay line is a field of another kind and is refused, naming it and the field the line takes", lambda: bupd(150, waits=[{**Re("ok"), "until": w(3)}, Re("b")], until=w(5)), "waits[1]", "a relay line takes event, not until")
    refused("6g …an anchor on an item line", lambda: bupd(150, waits=[{**It("a900"), "anchor": A1}, Re("b")], until=w(5)), "waits[1]", "an item line takes after, not anchor")
    refused("6g …an event and an after on a time line, both named", lambda: bupd(150, waits=[{**Tm(w(3)), "event": "x", "after": "a900"}, Re("b")], until=w(5)), "waits[1]", "a time line takes until, not event, after")
    refused("6g …an after on an anchor line", lambda: bupd(150, waits=[{**An(A1), "after": "a900"}, Re("b")], until=w(5)), "waits[1]", "an anchor line takes anchor and event, not after")
    refused("6g …on a create", lambda: mk(waits=[{**Re("ok"), "until": w(3)}, Re("b")], until=w(5)), "waits[1]", "relay line takes event, not until")
    check("6g a field of another kind that says nothing (null or empty) is left out, as it is for a client that fills every field", WLW.parse([{**Re("ok"), "until": None, "after": "", "anchor": None}, Re("b")])[0] == {"kind": "relay", "event": "ok"}, None)
    try: WLW.parse([{"kind": "RELAY", "event": "ok", "until": w(3)}, Re("b")]); check("6g …a foreign field on a line whose kind is in capitals is refused", False, None)
    except ValueError as e: check("6g …a foreign field on a line whose kind is in capitals is refused", "a relay line takes event" in str(e).lower() or "a RELAY line takes event" in str(e), str(e))
    check("6g the stored-shape reader is not the write's: a stored line with a number for an event reads as text and a stored event of 500 characters reads clipped to 300, as before",
          WL.lines({"wait_kind": "list", "wait_mode": "all", "until": w(6), "waits": [{"kind": "relay", "event": 5}, {"kind": "relay", "event": "e" * 500, "until": "ignored", "extra": 1}]})[0]["event"] == "5"
          and WL.lines({"wait_kind": "list", "wait_mode": "all", "until": w(6), "waits": [{"kind": "relay", "event": 5}, {"kind": "relay", "event": "e" * 500, "until": "ignored", "extra": 1}]})[1]["event"] == "e" * 300, None)
    check("6g …and WL.write_line refuses them as the write does", WL.write_line({"kind": "relay", "event": 5})[1] == "a line's event is text (got int)" and WL.write_line({"kind": "relay", "event": "e" * 301})[1] == "a line's event is at most 300 characters (got 301)"
          and WL.write_line({"kind": "relay", "event": "e" * 300})[0] == {"kind": "relay", "event": "e" * 300}, WL.write_line({"kind": "relay", "event": 5}))

    # ---- 6h waits=[] on an item with no list says so
    item(180, needs=[BACK], wait_kind="relay", wait_event="the vendor", until=w(5), post_wake_mover=BACK)
    out = bupd(180, waits=[])
    check("6h waits=[] on an item that waits on one thing says there was no list to clear, and changes nothing", "stores none, so nothing was cleared" in out and mt(180).get("wait_kind") == "relay" and mt(180).get("until") == w(5), (out[-300:], mt(180)))
    item(181, needs=[BACK])
    out = bupd(181, waits="none")
    check("6h …on an item that waits on nothing too, however the clear is written", "stores none, so nothing was cleared" in out, out[-300:])
    fresh(182, [Re("a"), Re("b")])
    out = bupd(182, waits=[])
    check("6h …and on an item that stores a list it clears it and says that instead (the item is left waiting on nothing)", "the wait on a list is cleared: the item waits on nothing now" in out and "nothing was cleared" not in out, out[-300:])
    out = bupd(181, waits=[], description="- Goal: the list ends\n- It lives here\n- And more\n- Done when done")
    check("6h …a write that passes no waits says nothing of the kind", "nothing was cleared" not in bupd(181, description="- Goal: the list ends\n- It lives here\n- And more\n- More still\n- Done when done"), None)

    # ---- 6i the gaps the mutation checks found
    fresh(190, [Re("a"), Re("b")], mode="any")
    out = bupd(190, waits="")
    check("6i waits=\"\" (a blank text) is no list and no clear: the call is as if it did not pass waits, and the list is as it was", listed(mt(190)) and mt(190)["wait_mode"] == "any" and len(mt(190)["waits"]) == 2 and "cleared" not in out, (mt(190), out[-200:]))
    out = bupd(190, waits="   ")
    check("6i …white space alone is the same", listed(mt(190)) and "cleared" not in out, (mt(190), out[-200:]))
    refused("6i …and a blank text beside wait_mode is refused as wait_mode without waits is", lambda: bupd(190, waits="", wait_mode="all"), "goes with waits")
    for i_, how in ((191, "CLEAR"), (192, "None"), (193, "Clear"), (194, " NONE ")):
        fresh(i_, [Re("a"), Re("b")])
        bupd(i_, waits=how)
        check(f"6i waits={how!r} clears the list, whatever its case", not any(k in mt(i_) for k in ("wait_kind", "waits", "wait_mode", "until")), mt(i_))
    fresh(195, [Re("a"), Re("b")])
    out = bupd(195, waits=[], clear_wait=True)
    check("6i clear_wait beside waits=[] is allowed (both say clear)", not any(k in mt(195) for k in ("wait_kind", "waits", "wait_mode", "until")), (mt(195), out[-200:]))
    fresh(196, [Re("a"), Re("b")])
    bupd(196, waits="none", clear_wait=True)
    check("6i …and beside waits=none", not mt(196).get("waits") and not mt(196).get("wait_kind"), mt(196))
    item(197, needs=[BACK])
    bupd(197, waits=[Tm(f"{w(3)} 10:30"), Re("a")], until=w(6))
    check("6i a time line written with a space is stored in the stored form (YYYY-MM-DDTHH:MM)", mt(197)["waits"][0] == {"kind": "time", "until": f"{w(3)}T10:30"}, mt(197))
    item(198, needs=[BACK])
    bupd(198, waits=[Tm(f"  {w(3)}  "), Re("a")], until=w(6))
    check("6i …with spaces around the date, the date alone", mt(198)["waits"][0] == {"kind": "time", "until": w(3)}, mt(198))
    bupd(198, waits=[Tm(f"{w(3)}T10:30"), Re("a")], until=w(6))
    bupd(198, waits=[Tm(f"{w(3)} 10:30"), Re("a")], until=w(6))
    check("6i …the two forms of one time are one line (sent again, the list is the same)", mt(198)["waits"][0]["until"] == f"{w(3)}T10:30" and len(mt(198)["waits"]) == 2, mt(198))
    refused("6i …and the two forms of one time in one list are a repeat", lambda: bupd(198, waits=[Tm(f"{w(3)} 10:30"), Tm(f"{w(3)}T10:30")], until=w(6)), "waits[2] repeats waits[1]")

    # ================================================================ 5. the text
    tools_ = {t.name: t for t in __import__("asyncio").run(server.mcp.list_tools())}
    for name_ in ("create", "update"):
        t_ = tools_[name_]; props_ = t_.parameters["properties"]
        check(f"5 {name_} takes waits and wait_mode, and says what they are", "waits" in props_ and "wait_mode" in props_ and "2 to 8 lines" in props_["waits"]["description"] and "backstop" in props_["waits"]["description"] and "all" in props_["wait_mode"]["description"], props_.get("waits"))
        check(f"5 …the description has the list in one worked example, and the parameter names the refusals that matter", 'waits=[{"kind": "item", "after": "board#N"}' in t_.description and "waits (2 to 8 lines)" in t_.description and "the backstop day" in props_["waits"]["description"] and "no wait_kind" in props_["waits"]["description"], t_.description[-600:])
    check("5 …until says it is the list's backstop beside waits, on both", all("list's backstop day" in tools_[n].parameters["properties"]["until"]["description"] for n in ("create", "update")), None)
    check("5 the tool text names no person, machine or session", not re.search(r"(?i)box-[a-d]|salamander|\bsala\b|board#\d{3,}", tools_["update"].parameters["properties"]["waits"]["description"] + tools_["update"].parameters["properties"]["wait_mode"]["description"]), None)
    root_ = pathlib.Path(STACK)
    wd_ = (root_ / "docs" / "waiting-and-doing.md").read_text(encoding="utf-8"); im_ = (root_ / "docs" / "item-model.md").read_text(encoding="utf-8")
    check("5 docs/waiting-and-doing.md says how a list is written: the parameters, the judging of a line, each refusal and what an edit leaves",
          all(x in wd_ for x in ("## A list is written with `waits`", "`wait_mode`", "`until`** is the backstop day", "a list needs its backstop day", "repeats `waits[1]`", "300 characters", "`arrived`", "no list of one is ever stored", "`waits=[]`")), None)
    check("5 …and the fix round: the loop test reads a list's item lines, a single wait replaces a list, a repeat is judged in the canonical form, a value is text of the kind's own fields within 300 characters, waits=[] says there was no list to clear",
          all(x in wd_ for x in ("the item lines of a stored list counting as links", "a single wait replaces a list", "`Recycle` and `recycle` are one wait", "a value that is not text", "an `event` or an item id over 300 characters", "there was no list to clear", "nested too deep", "judged as a date wait is")), None)
    bullet_ = next(l for l in im_.splitlines() if l.startswith("- **A wait on a list of waits"))
    check("5 …and no page says any more that the write path comes later", "a later change" not in wd_ and "a later change" not in bullet_ and "not yet written by any tool" not in bullet_ and "until a later change adds the write path" not in bullet_ and "later" not in bullet_, None)
    check("5 docs/item-model.md points to the write path and says an edit never stores a list of one", "how a list is written, and each refusal" in im_ and "never stores a list of one line" in im_, None)

    # ================================================================ 7. the lows round
    def arrive(i, k, what="it came"):
        d_ = rd(i); d_["metadata"]["waits"][k]["arrived"] = {"at": now0 - 5, "what": what}; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
    # ---- 7a an arrival is kept when the event line is sent again in another form
    fresh(300, [Ev("recycle"), Re("a")], until=w(6))
    arrive(300, 0)
    bupd(300, waits=[Ev("Recycle"), Re("a")], until=w(6))
    check("7a an event line that had arrived, sent again as `Recycle`, keeps its arrival and is the one line, not a new open line", mt(300)["waits"][0].get("arrived") and mt(300)["waits"][0]["event"] == "recycle" and len(mt(300)["waits"]) == 2, mt(300))
    bupd(300, waits=[Ev("recycle"), Re("a")], until=w(6))
    check("7a …and sent in its canonical form it keeps it as before (the control)", mt(300)["waits"][0].get("arrived") and not mt(300)["waits"][1].get("arrived"), mt(300))
    fresh(301, [Ev("fleet_op any"), Re("a")], until=w(6))
    arrive(301, 0)
    bupd(301, waits=[Ev("FLEET_OP   any"), Re("a")], until=w(6))
    check("7a …the same for `FLEET_OP   any` (case and spaces)", mt(301)["waits"][0].get("arrived") and mt(301)["waits"][0]["event"] == "fleet_op any", mt(301))
    fresh(302, [Ev("recycle"), Re("a")], until=w(6))
    arrive(302, 0)
    bupd(302, waits=[Re("a"), Ev(" RECYCLE ")], until=w(6))
    check("7a …in another position too, and the arrival goes with the line", mt(302)["waits"][1].get("arrived") and "arrived" not in mt(302)["waits"][0], mt(302))
    fresh(303, [Ev("recycle"), Re("the Lease")], until=w(6))
    arrive(303, 1)
    bupd(303, waits=[Ev("recycle"), Re("the lease")], until=w(6))
    check("7a a relay line that differs only in case stays a different line (its text is the owner's words, not a canonical phrase): the arrival is not carried", not mt(303)["waits"][1].get("arrived"), mt(303))
    fresh(304, [Re("Recycle"), Re("a")], until=w(6))
    check("7a a relay line whose text happens to parse as an event phrase (`Recycle`) is stored as written, not canonicalized as an event line would be", mt(304)["waits"][0] == {"kind": "relay", "event": "Recycle"}, mt(304))
    bupd(304, waits=[Re("Recycle"), Re("a"), Re("b")], until=w(6))
    check("7a …and sent again it stays `Recycle`", [ln["event"] for ln in mt(304)["waits"]] == ["Recycle", "a", "b"], mt(304))

    # ---- 7b a backstop earlier than an open time line, whichever parameter says it
    for name_, kw_ in (("ask_by", {"ask_by": w(4)}), ("after=none and until", {"after": "none", "until": w(4)}), ("hold and until", {"hold": True, "until": w(4)}), ("clear_hold and until", {"clear_hold": True, "until": w(4)}),
                       ("clear_after and until", {"clear_after": True, "until": w(4)}), ("after=[] and until", {"after": [], "until": w(4)})):
        fresh(310, [Tm(w(5)), Re("a")], until=w(6))
        refused(f"7b {name_}, earlier than an open time line, is refused as until alone is", lambda kw_=kw_: bupd(310, **kw_), "waits[1] is a date", "later than the backstop day", "an earlier date or a later until")
        check(f"7b …and nothing changed ({name_})", mt(310)["until"] == w(6) and listed(mt(310)) and not mt(310).get("ask_by"), mt(310))
    fresh(310, [Tm(w(5)), Re("a")], until=w(6))
    bupd(310, ask_by=w(5))
    check("7b ask_by on the day of the time line is accepted, and is the backstop", mt(310)["until"] == w(5) and listed(mt(310)), mt(310))
    fresh(310, [Tm(w(5)), Re("a")], until=w(6))
    bupd(310, after="none", until=w(5))
    check("7b after=none with a backstop on the day of the time line is accepted", mt(310)["until"] == w(5) and listed(mt(310)), mt(310))
    fresh(311, [Tm(w(5)), Re("a")], until=w(6))
    d_ = rd(311); d_["metadata"]["waits"][0]["arrived"] = {"at": now0 - 5, "what": "the date came"}; (T / "store/a/311.json").write_text(json.dumps(d_))
    bupd(311, ask_by=w(4))
    check("7b a time line that has arrived holds no backstop back from ask_by either", mt(311)["until"] == w(4), mt(311))
    item(312, needs=[BACK], wait_kind="list", wait_mode="all", waits=[Tm(w(5)), Re("a")], until=w(4), post_wake_mover=BACK)      # hand-edited: a backstop in front of its time line
    out = bupd(312, description="- Goal: the list ends\n- It lives here\n- And more\n- Done when done")
    check("7b a write that does not move the backstop day is no refusal for a hand-edited list whose backstop is already in front of a time line", "more" in rd(312)["description"] and mt(312)["until"] == w(4), out[-300:])

    # ---- 7c the model conflict note on a list written on an item in the doing state
    conflicts_ = lambda g: [l for l in _wt_get.stackshot_get(g).splitlines() if "the wait wins" in l]
    for k_, kw_ in (("list", dict(waits=[Re("a"), Re("b")], until=w(6))), ("relay", dict(wait_kind="relay", wait_event="x", until=w(6))), ("event", dict(wait_kind="event", wait_event="recycle", until=w(6))),
                    ("item", dict(wait_kind="item", after=["a900"], until=w(6)))):
        item(320, needs=[BACK])
        bupd(320, **kw_)
        check(f"7c a {k_} wait written on an item with no stored state is no model conflict (the state it would read as is the wait's own)", conflicts_("a320") == [] and not MODEL.derive({**rd(320), "gid": "a320"}).conflicts, conflicts_("a320"))
    item(320, needs=[BACK])
    bupd(320, wait_kind="anchor", wait_anchor=A1, wait_event="merged", until=w(6))
    check("7c …a single anchor wait on such an item keeps its note, as before", len(conflicts_("a320")) == 1 and "update hold=true (a park ends" in conflicts_("a320")[0], conflicts_("a320"))
    item(321, needs=[BACK], state="doing")
    bupd(321, waits=[Re("a"), Re("b")], until=w(6))
    check("7c a list written on an item whose state is stored as doing keeps the note, and its advice says where hold=true goes (an update of its own: beside waits it is refused)", len(conflicts_("a321")) == 1 and "update hold=true in an update of its own, not beside waits" in conflicts_("a321")[0], conflicts_("a321"))
    refused("7c …and beside waits hold=true is refused", lambda: bupd(321, waits=[Re("a"), Re("b")], until=w(6), hold=True), "does not go with hold")
    bupd(321, hold=True)
    check("7c …on its own it ends the stored state and the note with it, the list is as it was", conflicts_("a321") == [] and listed(mt(321)) and mt(321).get("state") != "doing", (conflicts_("a321"), mt(321)))

    # ---- 7d wording
    # a loop through a list line names the line, and is no `(after)` (the written wait is no after link)
    item(340, needs=[BACK]); item(341, needs=[BACK])
    bupd(341, waits=[It("a340"), Re("lp")], until=w(6))
    try: bupd(340, waits=[It("a341"), Re("lq")], until=w(6)); loop_ = "stored"
    except Exception as e: loop_ = str(e)
    check("7d a loop refusal for a list line names the line and says no (after): the written wait is no after link", "waits[1]: a loop" in loop_ and "(after)" not in loop_ and "out of waits[1]" in loop_, loop_)
    try: bupd(340, after=["a341"], until=w(6)); loop_ = "stored"
    except Exception as e: loop_ = str(e)
    check("7d …the loop through the single `after` keeps its words", "a loop" in loop_ and "(after)" in loop_ and "waits[" not in loop_, loop_)
    # the collapse reply says the day the item waits until
    fresh(342, [Tm(w(5)), Re("a")], until=w(6))
    o_ = bupd(342, waits=[Tm(w(5))], until=w(4))
    check("7d a list collapsed to a date later than the backstop: the reply says the stored day (the backstop), not the line's later one", mt(342)["until"] == w(4) and f"the date {w(4)}" in o_ and f"the date {w(5)}" not in o_, (mt(342), o_[-300:]))
    fresh(343, [Tm(w(5)), Re("a")], until=w(6))
    o_ = bupd(343, waits=[Tm(w(5))], until=w(5))
    check("7d …a date the backstop does not pass is as the line has it", mt(343)["until"] == w(5) and f"the date {w(5)}" in o_, (mt(343), o_[-300:]))
    # waits=[] beside a later until: the clock-renewal gate's own test decides (a write with progress goes through, as it does on main)
    def tryu(i, **kw):
        """The write's reply and the refusal it met ("" for none), so a write that is refused fails its own check instead of ending the run."""
        try: return bupd(i, **kw), ""
        except Exception as e: return "", str(e)
    NEWDESC = "- Goal: the list ends\n- It lives here\n- Done when done\n- And it waits on a later date now"
    for i_, kw_ in ((344, dict(waits=[], until=w(7))), (345, dict(waits="none", until=w(7))), (346, dict(waits="[]", until=w(7)))):
        fresh(i_, [Tm(w(5)), Re("a")], until=w(6))
        refused(f"7d waits={kw_['waits']!r} beside an until later than the list's backstop, with no progress, is refused in its own words, not as a pushed-out clock", lambda i_=i_, kw_=kw_: bupd(i_, **kw_), "waits=[] ends the list", f"until={w(7)}", f"backstop day {w(6)}", "waits=[] alone", "or change something real in the same write")
        check(f"7d …nothing changed ({i_})", listed(mt(i_)) and mt(i_)["until"] == w(6), mt(i_))
    fresh(347, [Tm(w(5)), Re("a")], until=w(6))
    bupd(347, waits=[], until=w(6))
    check("7d waits=[] beside the same day ends the list and leaves the date wait (as before)", not mt(347).get("waits") and mt(347)["until"] == w(6) and not mt(347).get("wait_kind"), mt(347))
    fresh(348, [Tm(w(5)), Re("a")], until=w(6))
    bupd(348, waits=[], until=w(3))
    check("7d …and beside an earlier one", not mt(348).get("waits") and mt(348)["until"] == w(3), mt(348))
    # …with progress, as on main: stored as the date wait on the later day
    fresh(349, [Tm(w(5)), Re("a")], until=w(6))
    out349, why_ = tryu(349, waits=[], until=w(7), description=NEWDESC)
    check("7d waits=[] beside a later until with a new description is accepted: the list ends, the item waits on the later date", not why_ and not mt(349).get("waits") and not mt(349).get("wait_kind") and mt(349)["until"] == w(7), mt(349))
    check("7d …and the reply says it waits on that date, never on nothing (the same reply says it waits on a time)", f"the item waits on the date {w(7)} now" in out349 and "waits on nothing" not in out349 and "waiting on a time" in out349, out349[-500:])
    fresh(350, [Tm(w(5)), Re("a")], until=w(6))
    _, why_ = tryu(350, waits=[], until=w(7), next=f"{BACK}: look again on {w(7)}")
    check("7d …with a new next step", not why_ and not mt(350).get("waits") and mt(350)["until"] == w(7) and "look again" in str(mt(350).get("next")), mt(350))
    fresh(352, [Tm(w(5)), Re("a")], until=w(6))
    refused("7d clear_wait beside waits=[] and a later until is refused as it is on a list-free item (it is no progress)", lambda: bupd(352, waits=[], clear_wait=True, until=w(7)), "Refused:")
    check("7d …nothing changed (clear_wait)", listed(mt(352)) and mt(352)["until"] == w(6), mt(352))
    # the owner's checked words lift it too: his words, from a transcript, in this very write
    SAY_SESSION, SAY_MSG = "22222222-3333-4444-8555-666666666666", "bbbbbbbb-bbbb-4bbb-8bbb-000000000001"
    (T / f"transcripts/-home-x/{SAY_SESSION}.jsonl").write_text(json.dumps({"type": "user", "uuid": SAY_MSG, "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "origin": {"kind": "human"},
                                                                           "message": {"role": "user", "content": "yes, the list can end and the date can move out"}}) + "\n", encoding="utf-8")
    fresh(353, [Tm(w(5)), Re("a")], until=w(6))
    _, why_ = tryu(353, waits=[], until=w(7), said=[{"tag": "Acked-by", "quote": "the list can end and the date can move out", "msg": SAY_MSG, "session": SAY_SESSION}])
    check("7d …and so do his words, checked against a transcript: the list ends, the item waits on the later date", not why_ and not mt(353).get("waits") and mt(353)["until"] == w(7) and mt(353).get("said"), mt(353))
    # an item that stores no list: waits=[] clears nothing, and the gate speaks its own words, never the list's
    item(354, needs=[BACK], wait_kind="anchor", wait_anchor=A1, wait_event="merged", until=w(5), post_wake_mover=BACK)
    try: bupd(354, waits=[], until=w(6)); why_ = "stored"
    except Exception as e: why_ = str(e)
    check("7d waits=[] with a later until on an item that stores no list is refused as a pushed-out clock, never as the end of a list", "pushed out" in why_ and "ends the list" not in why_ and "waits=[] alone" not in why_, why_[:400])
    out, why_ = tryu(354, waits=[], until=w(6), description=NEWDESC)
    check("7d …with progress it goes through as on main: the date moves, and the reply says there was no list to clear", not why_ and mt(354)["until"] == w(6) and "stores none" in out, (mt(354), out[-300:], why_[:300]))

    # ---- 7e the count is judged before the lines are read
    class Walked_(list):
        walked = 0
        def __iter__(self):
            Walked_.walked += 1
            return super().__iter__()
    big_ = Walked_([Re(f"news {i}") for i in range(200)] + [{"kind": "soon"}])
    try: WLW.parse(big_); why_ = "parsed"
    except ValueError as e: why_ = str(e)
    check("7e a list over 8 lines is refused on its count, before any line is read, with the same words (a bad line past the eighth is never reached)", why_ == "a list holds 2 to 8 lines (got 201)" and Walked_.walked == 0, (why_, Walked_.walked))
    try: WLW.parse([{"kind": "soon"}] + [Re(f"news {i}") for i in range(9)]); why_ = "parsed"
    except ValueError as e: why_ = str(e)
    check("7e …a bad first line in a list of ten says the count, as the count is judged first", why_ == "a list holds 2 to 8 lines (got 10)", why_)
    refused("7e …through create the refusal is the one it was", lambda: mk(waits=[Re(f"news {i}") for i in range(200)], until=w(5)), "Refused: a list holds 2 to 8 lines (got 200)")
    refused("7e …through update too, as JSON text", lambda: bupd(10, waits=json.dumps([Re(f"news {i}") for i in range(9)]), until=w(6)), "Refused: a list holds 2 to 8 lines (got 9)")
    check("7e …8 lines are read as before, and the count never refuses fewer", len(WLW.parse([Re(f"news {i}") for i in range(8)])) == 8 and len(WLW.parse([Re("a"), Re("b")])) == 2 and len(WLW.parse([Re("a")])) == 1, None)
    check("7e event_phrases and judged_as read a list over the limit as one that does not parse, as before (no phrase, and judged as a list)", WLW.event_phrases([Ev("recycle")] * 9) == [] and WLW.judged_as([Tm(w(5))] * 9) == "list", None)

    # ---- 7f the waits parameter text names what the refusal names
    for n_ in ("create", "update"):
        d_ = tools_[n_].parameters["properties"]["waits"]["description"]
        check(f"7f {n_}: the waits text names every parameter a list does not go with (clear_* for the clears), the stored backstop, and says until is not the only way to give it",
              all(x in d_ or (x.startswith("clear_") and "clear_*" in d_) for x in WLW.SINGLE if x != "until") and "wait_basis" in d_ and "Needs until, the backstop day (an update may omit it)" in d_ and "or the stored one" not in d_, d_)


    return ran, fails

MARK = "@@wait_list part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"list": part_list, "display": part_display, "write": part_write}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as each suite always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
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
    print(f"ok: wait list scenario, {total} checks")
