"""Scenario test for the wait on a LIST of waits (waits/wait_list.py, the model's sixth kind, the ending in watchers.py and server.py) — fixture data, no live store, no network, no server socket.

An item can wait on 2 to 8 waits at once, of any kind (time, anchor, item, relay, event), with a mode: `all` (it comes back when every line has arrived) or `any` (when the first has), and on its backstop
day at the latest. This part of the feature is storage, the model and the ending: nothing a caller passes writes a list yet, so the fixtures store the metadata directly. Covered:

  * the pure half: what a stored list must be (a malformed or short one is not one), arrived marks that are idempotent, the group's end by mode, which lines an arrival is for (two lines on one item or anchor),
    the scheduler's next moment, the words of an end
  * the model: wait_kind=list reads as a wait of that kind with its lines and mode, the backstop and `due`; a list that does not hold is IGNORED (the item reads as a single wait, noted, counted); a single wait
    reads exactly as before; the phase stamp and the sweep write waits_on=list
  * the ending, per kind of line: time (the clock), item (a close, superseded followed, a missing file), anchor (a notice that answers the line's event), event (a reported event), relay (marked by the write
    path); mixed kinds; two lines on one item or anchor; `all` ends on the last arrival and `any` on the first; a repeated delivery changes nothing; an item already turned is not turned again
  * the backstop day, with and without an open relay line (the owner is asked then, and "not yet" puts the list back with what had arrived)
  * the end drops the wait's fields (waits and wait_mode with the rest), and the mover is told what arrived and what did not
  * with the watchers off, a legacy path marks no line of a list (the `after` release and the held-anchor release never take one) but the legacy wake pass still ends a list at its backstop day, by the
    watchers' own path and in their words; a single wait is not touched (the existing suites are the proof)

    tests/run-suite wait_list        → exit 0 / 1"""
import datetime, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="waitlist-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
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
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.service import writes, gates; from stackshot.waits import waiting as _WT, until_write as UW, wait_list as WL, watchers as wk, event_waits as EW; from stackshot.model import model, model_guards, migration
from stackshot.service import telling
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
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
CFG = server._cfg.CFG.setdefault("model", {})
def sent(tag=None): return [x for x in SENT if tag is None or x[3] == tag]
def reset(): SENT.clear(); NOTES.clear()
def notes_of(g): return [n for gid, n in NOTES if gid == g]
def cfg(**kw):
    for k, v in kw.items(): CFG[k] = v
cfg(guards=False, watchers=True, pause=False)       # the write guards have their own suite; here they are off
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
    return server._release_after(f"a{g}", outcome, more.get("superseded_by", ""), "home-front")
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
      all(f in gates._REPARK_FIELDS and f in gates._WAIT_STRUCTURE and f in model_guards.STATE_FIELDS and f in server._WAKE_FIELD_KEYS for f in ("waits", "wait_mode"))
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
def mod_of(i, **kw): return server._model_of({**rd(i), "gid": f"a{i}", **kw})
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
it = rd(100); server._phase_stamp("a100", it)
check("stamp: the save's stamp writes phase waiting and waits_on list", it["metadata"].get("phase") == "waiting" and it["metadata"].get("waits_on") == "list", it["metadata"])
v1 = model.view({**it, "gid": "a100"}, mod_of(100), after_open=lambda i_: [])
check("stamp: …and the board's reading of the stamped item is the list, with its lines", v1.wait.kind == "list" and len(v1.waits) == 3 and model.shown_pair(v1) == ("waiting", "list"), v1)
check("stamp: …a stored list the fields no longer hold is not drawn as a list with no lines", model.view({**it, "metadata": {**it["metadata"], "waits": [Tm(day(3))]}, "gid": "a100"}, model.derive({**it, "metadata": {**it["metadata"], "waits": [Tm(day(3))]}}), after_open=lambda i_: []).wait.kind == "time", None)
lst(105, [Tm(day(3)), It("a901")], mode="any"); put(105, {**rd(105)})
sw = server._phase_sweep()
check("stamp: the sweep stamps every open list item waiting on a list, and a second sweep changes nothing", "a105" in sw and mt(105).get("phase") == "waiting" and mt(105).get("waits_on") == "list" and mt(100).get("waits_on") == "list" and server._phase_sweep() == [], (sw, mt(105)))
check("stamp: …the stamped pair is what the board reads (stored first), and a sweep restamps a list edited down to one line", model.stored_waits_on(rd(105)) == "list", None)
d5 = rd(105); d5["metadata"]["waits"] = d5["metadata"]["waits"][:1]; put(105, d5)
check("stamp: …(the one line does not hold: the sweep finds the stored list outdated and restamps the date alone)", "a105" in server._phase_sweep() and mt(105).get("waits_on") == "time", mt(105))
lst(105, [Tm(day(3)), It("a901")], mode="any")

# ================================================================ time lines: the clock marks them, the group decides
reset()
lst(110, [Tm(day(-1)), Tm(day(4))], mode="all")
woke = server._wake_pass()
check("time (all): a line whose date has passed is marked arrived, the other is not; the item still waits and nobody is told", "a110" not in woke and arrived_of(110) == [True, False] and mt(110).get("wait_kind") == "list" and not mt(110).get("mover") and not sent("watch"), mt(110))
check("time (all): …with a History line `arrived: <what> (1 of 2)` and the item's own clock moved, not its state clock", notes_of("a110") == [f"arrived: its date {day(-1)} came (1 of 2)"] and rd(110)["state_updated"] < now0 - 9 * DAY and rd(110)["updated"] >= now0, notes_of("a110"))
check("time (all): …the model reads the item as still waiting on a list, one line arrived", mod_of(110).state == "waiting" and mod_of(110).waits[0].arrived and not mod_of(110).waits[1].arrived and mod_of(110).waits[0].arrived_what == f"its date {day(-1)} came", mod_of(110).waits)
b110 = raw(110); reset(); server._wake_pass()
check("time (all): the next pass changes nothing (the marked line keeps its first time)", raw(110) == b110 and not NOTES and not sent(), notes_of("a110"))
check("time (all): the next moment is the line still open (the arrived one is no moment)", wk.next_moment(mt(110)) == wk.day_epoch(day(4)), wk.next_moment(mt(110)))
d = rd(110); d["metadata"]["waits"][1]["until"] = day(-1); put(110, d)
reset(); woke = server._wake_pass(); m = mt(110)
check("time (all): the last line's date passing turns the item alive with the post-wake mover, on the cause of the completing line", "a110" in woke and m.get("mover") == BACK and m.get("needs") == [BACK] and "all 2 arrived" in m["woke"]["what"]
      and m["woke"]["what"].count(f"its date {day(-1)} came") == 2 and m["woke"]["to"] == BACK, m)
check("time (all): …the wait's fields are gone with the wait: the list, its mode, the kind, the backstop and the post-wake mover", all(k not in m for k in GONE) and "watch" not in m or all(k not in m.get("watch", {}) for k in ("asked", "was")), m)
check("time (all): …the mover is told in one line what arrived", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "is yours now: all 2 arrived:" in sent("watch")[0][2] and "\n" not in sent("watch")[0][2], sent())
check("time (all): …the History line says the item woke, with what arrived", any(n.startswith("woke: all 2 arrived:") and n.endswith(f"→ {BACK}") for n in notes_of("a110")), notes_of("a110"))
check("time (all): …the model reads it as alive, no conflicts, and nothing is left to watch", mod_of(110).state == "alive" and mod_of(110).mover == BACK and not mod_of(110).conflicts and not wk.watches(rd(110)), mod_of(110))
reset(); server._wake_pass(); check("time (all): …a later pass tells nobody again", not sent() and not notes_of("a110"), sent())
# any
reset()
lst(111, [Tm(day(-1)), Tm(day(6)), It("a901")], mode="any")
woke = server._wake_pass(); m = mt(111)
check("time (any): the first line to arrive ends the group: alive with the post-wake mover, what arrived and what was not needed", "a111" in woke and m.get("mover") == BACK and m["woke"]["what"] == f"any of 3 arrived: its date {day(-1)} came; not needed: the date {day(6)}; the close of {server._gh.shown('a901')}", m)
check("time (any): …the wait's fields are gone", all(k not in m for k in GONE), m)
check("time (any): …the message to the mover carries it", len(sent("watch")) == 1 and "any of 3 arrived:" in sent("watch")[0][2] and "; not needed: " in sent("watch")[0][2], sent())

# ================================================================ item lines
reset()
lst(120, [It("a121"), It("a122"), Tm(day(7))], mode="all")
item(121, subject="[home] first blocker"); item(122, subject="[home] second blocker")
close(121)
check("item (all): a closed item marks its line; the item waits on, nobody is told", arrived_of(120) == [True, False, False] and mt(120).get("wait_kind") == "list" and not sent("watch")
      and notes_of("a120") == [f"arrived: {server._gh.shown('a121')} closed (done) by home-front (1 of 3)"], (mt(120), notes_of("a120")))
b120 = raw(120); reset(); close(121)
check("item: the same close delivered again changes nothing (idempotent), writes nothing", raw(120) == b120 and not NOTES and not sent(), notes_of("a120"))
close(122)
check("item (all): the second close marks the second line; the time line is still open, so the item waits on", arrived_of(120) == [True, True, False] and mt(120).get("wait_kind") == "list" and not sent("watch"), mt(120))
d = rd(120); d["metadata"]["waits"][2]["until"] = day(-1); put(120, d); reset(); woke = server._wake_pass()
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
server._release_after("a129", "superseded", "a130", "home-front")
check("item: a superseded item is followed to its open replacement: the id in the line is replaced and the line has not arrived; the item waits on", mt(128)["waits"][0]["after"] == "a130" and arrived_of(128) == [False, False] and mt(128).get("wait_kind") == "list" and not sent("watch")
      and notes_of("a128") == [f"{server._gh.ref('a129')} was superseded, followed to {server._gh.ref('a130')}"], (mt(128), notes_of("a128")))
close(130)
check("item: …and the replacement's close then ends it", mt(128).get("mover") == BACK and "a130" not in str(mt(128).get("waits")) and f"{server._gh.shown('a130')} closed (done)" in mt(128)["woke"]["what"], mt(128))
# superseded with a closed replacement
reset()
lst(131, [It("a132"), Re("x")], mode="any"); item(132, subject="[home] old two"); item(133, status="completed", outcome="done", reason="r", needs=[], subject="[home] a replacement already closed")
it = rd(132); it["status"] = "completed"; it["metadata"].update(outcome="superseded", reason="r", superseded_by="a133"); put(132, it)
server._release_after("a132", "superseded", "a133", "home-front")
check("item: a superseded item whose replacement is closed too marks the line (nothing to follow)", mt(131).get("mover") == BACK and "was superseded by" in mt(131)["woke"]["what"] and "closed too" in mt(131)["woke"]["what"], mt(131).get("woke"))
# a close nobody saw, a missing file
reset()
lst(134, [It("a135"), It("a999"), Re("x")], mode="all"); item(135, status="completed", outcome="done", reason="r", needs=[], subject="[home] closed before")
woke = server._wake_pass()
check("item: a close nobody saw (the item is already closed) and an item with no file both count as closed: the clock's pass marks both lines", arrived_of(134) == [True, True, False] and mt(134).get("wait_kind") == "list" and "a134" not in woke, (arrived_of(134), mt(134)))
check("item: …(the relay line is still open)", len(notes_of("a134")) == 1 and notes_of("a134")[0].count("arrived:") == 2 and "(2 of 3)" in notes_of("a134")[0], notes_of("a134"))
lst(136, [It("a135"), Tm(day(5))], mode="any"); reset(); woke = server._wake_pass()
check("item (any): a catch-up finds the close and ends the group", "a136" in woke and mt(136).get("mover") == BACK, mt(136))
# a closed superseded item found by the clock is followed too
lst(137, [It("a138"), Re("x")], mode="any"); item(138, status="completed", outcome="superseded", superseded_by="a139", reason="r", needs=[], subject="[home] superseded, found later"); item(139, subject="[home] open replacement")
server._wake_pass()
check("item: the clock's catch-up follows a superseded item to its open replacement too", mt(137)["waits"][0]["after"] == "a139" and arrived_of(137) == [False, False] and mt(137).get("wait_kind") == "list", mt(137))

# ================================================================ anchor lines
reset()
lst(140, [An(AURL, "PR merged"), An(AURL2, "a reply")], mode="all", project="projects/alpha")
lst(141, [An(AURL, "PR merged"), Tm(day(7))], mode="any", project="projects/beta")
lst(142, [An(AURL, "a reply"), An("github:o/r#5", "a review"), Re("x")], mode="all")
server._anchor_release("projects/alpha", notice("old comment", ts=now0 - 20 * DAY))
check("anchor: a notice older than the wait does not count", arrived_of(140) == [False, False] and arrived_of(142) == [False, False, False], mt(140))
server._anchor_release("projects/alpha", notice("CI passed on the PR", log_only=True, ruled_by=server.AUTO_RULER, ruling="merged", to=""))
check("anchor: a routine line of the fleet's own PR does not end a line that waits for a merge (as for a single wait); a line waiting for a reply counts it", arrived_of(140) == [False, False] and arrived_of(142) == [True, True, False], (arrived_of(140), arrived_of(142)))
reset()
server._anchor_release("projects/alpha", notice("dropped by the keeper", ruling="dropped"))
check("anchor: a notice the keeper dropped does not count", arrived_of(140) == [False, False], None)
rel = server._anchor_release("projects/alpha", notice("PR #5 merged: the work landed"), by="home-stew")
check("anchor (all): a notice the keeper passed marks the line that answers it; another anchor's line and another project's item are not touched; nobody is told yet", arrived_of(140) == [True, False] and mt(140).get("wait_kind") == "list" and arrived_of(141) == [False, False] and "a140" not in rel and not sent("watch")
      and f"(1 of 2)" in notes_of("a140")[0] and "github:o/r#5" in notes_of("a140")[0] and "PR #5 merged" in notes_of("a140")[0], (arrived_of(140), notes_of("a140")))
check("anchor: two lines on one anchor (the same anchor written two ways) are both marked by one notice", arrived_of(142) == [True, True, False], None)
b140 = raw(140); reset()
server._anchor_release("projects/alpha", notice("PR #5 merged again", ts=now0 + 5, ruled_at=now0 + 5))
check("anchor: a second notice on an anchor whose line has arrived changes nothing", raw(140) == b140 and not NOTES, notes_of("a140"))
rel = server._anchor_release("projects/alpha", notice("PR #6 merged", anchor="github:o/r#6"), by="home-stew")
m = mt(140)
check("anchor (all): the last line's notice turns it alive with the post-wake mover, the cause the anchor", rel == ["a140"] and m.get("mover") == BACK and m["woke"]["what"].startswith("all 2 arrived:") and "PR #5 merged" in m["woke"]["what"] and "PR #6 merged" in m["woke"]["what"] and all(k not in m for k in GONE), (rel, m))
check("anchor: …and the mover is told", len(sent("watch")) == 1 and sent("watch")[0][1] == UB, sent())
reset()
rel = server._anchor_release("projects/beta", notice("PR #5 merged", ruling=None, to="", live=True), by="")
check("anchor (any): in a project nobody rules, a notice that arrived ends an `any` list on it at once", "a141" in rel and mt(141).get("mover") == BACK and "any of 2 arrived:" in mt(141)["woke"]["what"], (rel, mt(141)))
# the minute pass finds a notice in the routing log
lst(143, [An(AURL, "a reply"), Re("x")], mode="any")
server._routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="a reply on the PR", anchor="github:o/r#5", pilot=True)
nid = server._routing.read("projects/alpha", since=now0 - 60)[-1]["id"]
server._routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
time.sleep(0.01); out = server._anchor_pass()
check("anchor: the minute pass finds a keeper-passed notice in the routing log for an item whose list waits on the anchor", "a143" in out and mt(143).get("mover") == BACK, (out, mt(143)))
lst(144, [An(AURL2, "a reply"), Re("x")], mode="any", watch={})
server._anchor_pass()
check("anchor: …and gives a list that has no stamp one (a notice from the days it already waited through is not its arrival)", mt(144).get("watch", {}).get("set_at", 0) >= now0 and arrived_of(144) == [False, False], mt(144))

# ================================================================ event lines
reset()
lst(150, [Ev("job_run nightly"), Ev("recycle"), It("a901")], mode="all")
lst(151, [Ev("job_run nightly"), Re("x")], mode="any")
rep = lambda **kw: EW.event(**kw)
got = server._evwait_report(EW.event("job_run", name="other"))
check("event: an event no line answers marks nothing", got == [] and arrived_of(150) == [False, False, False] and arrived_of(151) == [False, False], None)
got = server._evwait_report(EW.event("job_run", name="nightly", what="the nightly job ran"))
check("event (any): an event that answers a line ends an `any` list; (all) it marks the line and waits for the rest", got == ["a151"] and mt(151).get("mover") == BACK and "any of 2 arrived: the nightly job ran" in mt(151)["woke"]["what"]
      and arrived_of(150) == [True, False, False] and mt(150).get("wait_kind") == "list" and len(notes_of("a150")) == 1 and "(1 of 3)" in notes_of("a150")[0], (got, mt(151), arrived_of(150)))
b150 = raw(150); reset(); got = server._evwait_report(EW.event("job_run", name="nightly"))
check("event: the same event reported again changes nothing", got == [] and raw(150) == b150 and not NOTES, notes_of("a150"))
server._evwait_report(EW.event("recycle", machine="testbox")); close(901)
check("event + item (all): every line arrived (an event, an event, a close): the group ends on the last, of mixed kinds", mt(150).get("mover") == BACK and mt(150)["woke"]["what"].startswith("all 3 arrived:") and "the close of" not in mt(150)["woke"]["what"], mt(150))
# an old reported event is not a wait's arrival
lst(152, [Ev("fleet_op many"), Re("x")], mode="any", state_updated=None)
d = rd(152); d["state_updated"] = now0 + 3600; put(152, d)
check("event: a reported event older than the wait (the item's last move) is not an arrival", server._evwait_report(EW.event("fleet_op", verb="lane", sessions=3)) == [] and arrived_of(152) == [False, False], mt(152))
# the pollers look for event lines as they do for an event wait
lst(153, [Ev("box_online testbox"), Ev("pr_merged o/r#77"), Re("x")], mode="any")
specs = server._event_specs(rd(153) | {"gid": "a153"})
check("event: the catch-up pollers find the event lines of a list (the machine and the pull request), and an arrived line is no longer looked for", [(s.kind, s.key or s.machine) for s in specs] == [("box_online", "testbox"), ("pr_merged", "o/r#77")]
      and [s.kind for s in server._event_specs({**rd(153), "metadata": {**mt(153), "waits": [{**mt(153)["waits"][0], "arrived": {"at": 1, "what": "x"}}, *mt(153)["waits"][1:]]}})] == ["pr_merged"]
      and [s.kind for s in server._event_specs({**rd(100), "gid": "a100"})] == [] and server._event_specs({**rd(10), "gid": "a10"} if (T / "store/a/10.json").exists() else {"metadata": {}}) == [], specs)

# ================================================================ relay lines and the write path's mark
reset()
lst(160, [Re("the lease"), It("a901x")], mode="all"); item("901x", subject="[home] a blocker for the relay list")
d = rd(160); d["metadata"]["waits"][1]["after"] = "a901x"; put(160, d)
check("relay: a relay line has no detector: nothing the server sees marks it", server._evwait_report(EW.event("recycle")) == [] and server._wake_pass() == [] and arrived_of(160) == [False, False], None)
out_ = {}
turned = server._watch_mark("a160", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "the owner relayed the lease")
check("relay: the write path marks it (watchers' seam: a line, the words, the cause); under `all` the item waits on", turned is False and arrived_of(160) == [True, False] and mt(160).get("wait_kind") == "list" and not out_, (turned, mt(160)))
close("901x")
check("relay: …and the last line arriving ends the group on the cause of that line", mt(160).get("mover") == BACK and mt(160)["woke"]["what"].startswith("all 2 arrived: the owner relayed the lease;"), mt(160))
lst(161, [Re("the lease"), Tm(day(6))], mode="any"); out_ = {}
check("relay (any): the relay line arriving is an arrival, not a question: the item goes to its post-wake mover", server._watch_mark("a161", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "the owner relayed the lease") is True
      and mt(161).get("mover") == BACK and mt(161).get("needs") == [BACK] and "ask" not in mt(161) and [x for rows in out_.values() for x in rows], mt(161))
check("relay: a second delivery of the same mark changes nothing, and an item already turned is not turned again", server._watch_mark("a161", "relay", time.time(), {}, lambda m_: [0], "again") is False, None)

# ================================================================ mixed kinds, the group ends on the last
reset()
lst(170, [Tm(day(-1)), It("a171"), An(AURL2, "a reply"), Ev("job_run weekly"), Re("x")], mode="all")
item(171, subject="[home] a blocker in a mixed list")
woke = server._wake_pass()
check("mixed: five lines, five kinds: the clock marks the time line", arrived_of(170) == [True, False, False, False, False], None)
close(171)
server._anchor_release("projects/alpha", notice("a reply came", anchor="github:o/r#6"), by="home-stew")
server._evwait_report(EW.event("job_run", name="weekly"))
check("mixed: …an item, an anchor and an event each mark their line; the item still waits, nobody is told", arrived_of(170) == [True, True, True, True, False] and mt(170).get("wait_kind") == "list" and not sent("watch"), arrived_of(170))
server._watch_mark("a170", "relay", time.time(), {}, lambda m_: WL.lines_by_kind(m_, "relay"), "he relayed x")
check("mixed: …the relay line, the last, ends it", mt(170).get("mover") == BACK and mt(170)["woke"]["what"].startswith("all 5 arrived:") and all(k not in mt(170) for k in GONE) and "hold" not in mt(170), mt(170))

# the marks are made, and the group ended, on the item as it stands under the lock: an item that no longer stores a list, an event older than the wait, and a group that is not due are left as they are
reset()
lst(172, [Ev("job_run weekly"), Re("x")], mode="any"); item(173, subject="[home] a single time wait that replaced a list", wait_kind="time", hold=True, wake=day(5), needs=[], post_wake_mover=BACK, watch={"set_at": now0 - 3600})
lst(174, [Tm(day(5)), Re("y")], mode="all")
b172, b173, b174 = raw(172), raw(173), raw(174)
old_ev = EW.event("job_run", name="weekly")
check("under the lock: an event dated before the wait was set (its floor) marks no line", server._watch_mark("a172", "event", now0 - 7200, {}, lambda m_: WL.lines_by_kind(m_, "event"), "weekly ran", ev=old_ev) is False and raw(172) == b172, mt(172))
check("under the lock: …an item that no longer stores a list (a single wait now) marks nothing and is not touched", server._watch_mark("a173", "relay", now0, {}, lambda m_: [0], "x") is False and raw(173) == b173, mt(173))
check("under the lock: …a group that is not due is not ended (the wait is read again: its cause is not the one the caller saw)", server._watch_fire("a174", "time", now0, {}, recheck=True) is False and raw(174) == b174, mt(174))
check("under the lock: …the same event dated after the wait was set marks its line and, in an `any` list, ends it", server._watch_mark("a172", "event", now0, {}, lambda m_: WL.lines_by_kind(m_, "event"), "weekly ran", ev=old_ev) is True and mt(172).get("mover") == BACK, mt(172))

# ================================================================ the backstop day
reset()
lst(180, [Tm(day(5)), It("a181"), An(AURL, "x")], mode="all", until=day(-1)); item(181, subject="[home] never closes")
woke = server._wake_pass(); m = mt(180)
check("backstop (no relay line): the backstop day turns the item alive to the post-wake mover whatever has arrived, saying what had and what is still open", "a180" in woke and m.get("mover") == BACK and m["woke"]["what"].startswith(f"backstop day {day(-1)}: nothing had arrived; still open: ") and "the close of" in m["woke"]["what"]
      and all(k not in m for k in GONE) and "ask" not in m, m)
check("backstop: …the mover is told", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "backstop day" in sent("watch")[0][2], sent())
reset()
lst(182, [It("a183"), Tm(day(-3)), An(AURL, "x")], mode="all", until=day(-1)); item(183, status="completed", outcome="done", reason="r", needs=[], subject="[home] closed")
server._wake_pass(); m = mt(182)
check("backstop: lines that arrived are said as arrived (the item and time lines here), the anchor line is still open", m.get("mover") == BACK and "arrived" in m["woke"]["what"] and "still open: a notice at " + AURL in m["woke"]["what"] and m["woke"]["what"].startswith(f"backstop day {day(-1)}:"), m.get("woke"))
# with an open relay line
reset()
lst(184, [Tm(day(-2)), Re("the lease"), It("a185")], mode="all", until=day(-1), then="home-other"); item(185, subject="[home] open")
woke = server._wake_pass(); m = mt(184)
check("backstop (open relay line): the owner is asked, as a relay's ask-by day asks: the fixed question about the relay line's event, three options, the post-wake mover as `then`", "a184" in woke and m.get("needs") == ["decision"]
      and m.get("ask") == "Decide: has the lease arrived? · Options: arrived / not yet, ask again on <date> / drop" and [o["label"] for o in m["options"]] == ["arrived", "not yet, ask again on <date>", "drop"] and m.get("then") == BACK and "mover" not in m, m)
check("backstop (open relay line): …the words of what arrived and what did not are on the item, nobody is messaged, and the wait is put by", m["woke"]["to"] == OWN and m["woke"]["what"].startswith(f"backstop day {day(-1)}: arrived ") and "still open" in m["woke"]["what"] and not sent("watch")
      and all(k not in m for k in GONE) and m["watch"]["was"]["wait_kind"] == "list" and len(m["watch"]["was"]["waits"]) == 3 and m["watch"]["was"]["waits"][0].get("arrived"), m)
check("backstop (open relay line): …the model reads it as the owner's move", mod_of(184).owner_moves, mod_of(184))
out = server._answer("a184", "not yet, ask again on <date>", f"ask again on {day(10)}", "answer"); m = mt(184)
check("backstop (open relay line): `not yet` with a date puts the list back: its lines (what had arrived stays), mode and post-wake mover, the backstop moved to that day, nothing of the question left",
      out == "decision" and m.get("wait_kind") == "list" and m.get("wait_mode") == "all" and m.get("until") == day(10) and arrived_of(184) == [True, False, False] and m.get("post_wake_mover") == BACK
      and "ask" not in m and "options" not in m and "decision" not in (m.get("needs") or []) and WL.valid(m) and mod_of(184).wait.kind == "list", (out, m))
check("backstop (open relay line): …and it is watched again (the next moment is that day)", wk.watches(rd(184)) and wk.next_moment(m) == wk.day_epoch(day(10)), None)
# the owner says arrived / drop
lst(186, [Re("the quote"), Tm(day(6))], mode="all", until=day(-1)); server._wake_pass(); reset()
server._answer("a186", "arrived", "", "answer"); m = mt(186)
check("backstop (open relay line): `arrived` puts the item with the post-wake mover, alive; the wait's fields are gone", m.get("mover") == BACK and "ask" not in m and all(k not in m for k in GONE), m)
lst(187, [Re("the quote"), Tm(day(6))], mode="all", until=day(-1)); server._wake_pass()
server._answer("a187", "drop", "", "answer"); m = mt(187)
check("backstop (open relay line): `drop` closes it as not planned and the list goes with the rest of the wait", rd(187)["status"] == "completed" and m.get("outcome") == "dropped" and all(k not in m for k in GONE) and "ask" not in m, m)
# an open relay line that has arrived does not ask
reset()
lst(188, [Re("the lease"), Tm(day(6))], mode="all", until=day(-1)); d = rd(188); d["metadata"]["waits"][0]["arrived"] = {"at": now0 - 100, "what": "he relayed it"}; put(188, d)
server._wake_pass(); m = mt(188)
check("backstop: a relay line that has arrived is not an open one: the item goes to its post-wake mover, no question", m.get("mover") == BACK and "ask" not in m and "decision" not in (m.get("needs") or []), m)

# ================================================================ races, edits and the other mechanisms
# a list edited so that the group is over is found by the next pass
reset()
lst(190, [Tm(day(-1)), It("a191"), Re("x")], mode="all"); item(191)
server._wake_pass(); d = rd(190); d["metadata"]["waits"][1]["arrived"] = {"at": now0, "what": "a191 closed"}; put(190, d)        # two of three arrived
check("edit: two of three lines have arrived: the item waits on", mt(190).get("wait_kind") == "list" and not WL.done(mt(190)), mt(190))
d = rd(190); d["metadata"]["waits"] = d["metadata"]["waits"][:2]; put(190, d)                                                      # …and the open line is removed from the list
check("edit: …the line that was open is removed: every line left has arrived, so the group is over and the scheduler sees it is due now", WL.done(mt(190)) and server._next_wake() is not None and server._next_wake() <= server._pages.zone_now(), server._next_wake())
reset(); woke = server._minute_wake_pass() or server._wake_pass()
check("edit: …and the next pass turns it", mt(190).get("mover") == BACK and mt(190)["woke"]["what"].startswith("all 2 arrived:"), mt(190))
# a list that does not hold is a single wait: it ends as one
reset()
lst(192, [Tm(day(5))], mode="all", until=day(-1))
woke = server._wake_pass(); m = mt(192)
check("malformed: an item that stores wait_kind=list with a list that does not hold ends as the date alone: its backstop day comes, the mover has it, the stray fields go with the wait", "a192" in woke and m.get("mover") == BACK
      and "its until" in m["woke"]["what"] and all(k not in m for k in GONE), m)
# the legacy paths: with the watchers off nothing marks a line, and only the backstop day ends a list
reset()
lst(193, [Tm(day(9)), It("a194")], mode="all", until=day(9)); item(194)
cfg(watchers=False)
b193 = raw(193); woke = server._wake_pass(); server._release_after("a194", "done", "", "home-front"); server._anchor_release("projects/alpha", notice("a notice"), by="home-stew")
check("legacy: with the watchers off nothing marks a line or ends a list before its backstop day (the wake pass, the `after` release and the held-anchor release leave it as it is)", raw(193) == b193 and "a193" not in woke, (woke, mt(193)))
check("legacy: …the scheduler looks at its backstop day alone (one moment, the day's start)", [at for g, *_, at in server._wakes() if g == "a193"] == [server._wake_at(day(9))], [(g, at) for g, *_, at in server._wakes()])
# (d) the backstop day ends a list with the watchers off
reset()
lst(205, [Tm(day(9)), It("a206"), Ev("job_run weekly")], mode="all", until=day(-1)); item(206, subject="[home] the blocker of a list with the watchers off")
woke = server._wake_pass(); m = mt(205)
check("legacy (watchers off): a list whose backstop day has passed ends: the post-wake mover has it, alive, with the watchers' words (nothing arrived, every line still open)", "a205" in woke and m.get("mover") == BACK and m.get("needs") == [BACK]
      and m["woke"]["what"] == f"backstop day {day(-1)}: nothing had arrived; still open: the date {day(9)}; the close of {server._gh.shown('a206')}; a fleet event (job_run weekly)", m)
check("legacy (watchers off): …through end_wait: the whole wait group goes (the list, its mode, the kind, the backstop, the post-wake mover) and the hold", all(k not in m for k in GONE) and all(k not in m for k in model.WAIT_GROUP) and "hold" not in m and "ask" not in m, m)
check("legacy (watchers off): …the mover is told in one line and the History says the item woke", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "backstop day" in sent("watch")[0][2] and any(n.startswith("woke: backstop day ") for n in notes_of("a205")), (sent(), notes_of("a205")))
reset(); server._wake_pass()
check("legacy (watchers off): …a later pass tells nobody again", not sent() and not notes_of("a205"), sent())
reset()
lst(207, [Re("the lease"), Tm(day(9))], mode="all", until=day(-1), then="home-other"); server._wake_pass(); m = mt(207)
check("legacy (watchers off): with a relay line still open the owner is asked, as the watchers ask (the same question, three options, the post-wake mover as `then`), nobody is messaged", m.get("needs") == ["decision"] and m.get("ask") == "Decide: has the lease arrived? · Options: arrived / not yet, ask again on <date> / drop"
      and m.get("then") == BACK and "mover" not in m and m["woke"]["what"].startswith(f"backstop day {day(-1)}: nothing had arrived; still open: news of the lease; ") and all(k not in m for k in GONE) and not sent("watch"), m)
lst(209, [Re("x"), Tm(day(9))], mode="any", until=day(-1)); d = rd(209); d["metadata"]["waits"][1]["arrived"] = {"at": now0 - 100, "what": "the date came"}; put(209, d)
reset(); server._wake_pass()
check("legacy (watchers off): a list that is already over by what has arrived (edited by hand) ends with the words of the arrival, not the backstop's", mt(209).get("mover") == BACK and mt(209)["woke"]["what"] == "any of 2 arrived: the date came; not needed: news of x", mt(209))
item(213, wait_kind="time", hold=True, wake=day(-1), needs=[], post_wake_mover=BACK, subject="[home] a single wait with the watchers off")
reset(); woke = server._wake_pass()
check("legacy (watchers off): a single wait is released by the old pass as it always was (wake, no list words)", "a213" in woke and "hold" not in mt(213) and "woke" not in mt(213) and any(n.startswith("woke (wake ") for n in notes_of("a213")), (mt(213), notes_of("a213")))
lst(214, [Tm(day(9)), It("a206")], mode="all", until=day(-1)); d = rd(214); d["metadata"]["waits"] = d["metadata"]["waits"][:1]; put(214, d)
reset(); woke = server._wake_pass()
check("legacy (watchers off): a stored list that does not hold ends as the date alone, as it did (the old pass's own words, no list words)", "a214" in woke and "woke" not in mt(214) and any(n.startswith("woke (wake ") for n in notes_of("a214"))
      and not any("backstop day" in n for n in notes_of("a214")) and "until" not in mt(214), (mt(214), notes_of("a214")))
cfg(watchers=True)
reset(); woke = server._wake_pass()
check("legacy: …and with the watchers on they end a list the same way (the backstop day)", "a193" not in woke and mt(193).get("wait_kind") == "list", (woke, mt(193)))
lst(215, [Tm(day(9)), It("a206"), Ev("job_run weekly")], mode="all", until=day(-1)); reset(); woke = server._wake_pass()
check("legacy: …(watchers on: the same words as with them off)", "a215" in woke and mt(215)["woke"]["what"] == mt(205)["woke"]["what"], (mt(215).get("woke"), mt(205).get("woke")))
# pause
reset()
lst(195, [Tm(day(-1)), Re("x")], mode="any", until=day(-1)); lst(196, [It("a197"), Re("x")], mode="any"); item(197)
cfg(pause=True); b195 = raw(195); woke = server._wake_pass(); close(197)
check("pause: nothing is marked or ended while paused (the clock's pass, a close)", raw(195) == b195 and woke == [] and arrived_of(196) == [False, False] and not sent(), (woke, mt(196)))
cfg(pause=False); woke = server._wake_pass()
check("pause: …when it lifts the clock's pass finds the arrivals and ends them", "a195" in woke and "a196" in woke and mt(196).get("mover") == BACK and mt(195).get("mover") == BACK, (woke, mt(196)))
check("pause: …each recipient hears one message for the two items", len(sent("watch")) == 1 and "2 items are yours now" in sent("watch")[0][2], sent())
# a failed turn is backed off, not retried hot
lst(198, [Tm(day(-1)), Re("x")], mode="any")
orig_fire = server._watch_fire
def boom(*a, **k): raise RuntimeError("disk")
server._watch_fire = boom
try:
    server._wake_pass()
finally:
    server._watch_fire = orig_fire
check("backstop: a turn that cannot be made is backed off (noted on the item), the arrival stays recorded", mt(198).get("watch", {}).get("failed_at", 0) > 0 and arrived_of(198)[0] is True and mt(198).get("wait_kind") == "list", mt(198))
check("backstop: …and the scheduler looks at it again after the back-off, not at once", wk.next_moment(mt(198)) >= mt(198)["watch"]["failed_at"] + wk.BACKOFF - 1, wk.next_moment(mt(198)))
# a closed item drops the list with the rest
lst(199, [Tm(day(5)), It("a901")], mode="all")
server._update("a199", sender=FRONT, status="completed", outcome="done", reason="finished", description="- The thing works now\n- It lives here\n- Finished when it ships")
check("close: a closed item loses the list (waits and wait_mode go with the rest of the wait)", rd(199)["status"] == "completed" and all(k not in mt(199) for k in GONE), mt(199))
lst(200, [Tm(day(5)), It("a901")], mode="all")
server._update("a200", sender=FRONT, clear_wait=True)
check("clear_wait: it drops the list with the rest of the wait", all(k not in mt(200) for k in GONE), mt(200))

# ================================================================ the review lows of the first part
# (a) two relay lines: the owner is asked for the OPEN one
reset()
lst(220, [Re("the first quote"), Re("the second quote"), Tm(day(9))], mode="all", until=day(-1)); d = rd(220); d["metadata"]["waits"][0]["arrived"] = {"at": now0 - 100, "what": "the first quote was relayed"}; put(220, d)
check("relay_event: the first OPEN relay line's event (an arrived one is not asked about)", WL.relay_event(mt(220)) == "the second quote" and WL.relay_event({**GOOD, "waits": [Re("a"), Re("b")]}) == "a", WL.relay_event(mt(220)))
server._wake_pass(); m = mt(220)
check("backstop (two relay lines, the first arrived): the owner is asked about the OPEN one", m.get("ask") == "Decide: has the second quote arrived? · Options: arrived / not yet, ask again on <date> / drop" and m.get("needs") == ["decision"]
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
def on_write(new): return server._watch_on_write("a100", {"metadata": old_meta}, new, {}, set(), FRONT, False)
for what_, edit in (("a line changed", lambda n_: n_["waits"].__setitem__(0, Tm(day(5)))), ("a line added", lambda n_: n_["waits"].append(Tm(day(6)))), ("the mode changed", lambda n_: n_.__setitem__("wait_mode", "any"))):
    nm_ = json.loads(json.dumps(old_meta)); nm_["watch"] = {"set_at": 5.0, "chases_seen": 1}; edit(nm_); on_write(nm_)
    check(f"stamp: {what_}: watch.set_at is reset to now (a notice older than the new list is not its arrival), the rest of watch stays", nm_["watch"]["set_at"] >= now0 and nm_["watch"].get("chases_seen") == 1, nm_["watch"])
nm_ = json.loads(json.dumps(old_meta)); nm_["watch"] = {"set_at": 5.0}; on_write(nm_)
check("stamp: …a write that leaves the list as it is keeps the stamp", nm_["watch"]["set_at"] == 5.0, nm_["watch"])
# (5) an unstamped list: the first mark stamps the floor it had, so a second notice dated before that save still counts
reset()
lst(223, [An(AURL, "a reply"), An(AURL2, "a reply"), Re("x")], mode="all", watch={}); item_ = rd(223)
check("stamp: an unstamped list reads its last write as the floor", "set_at" not in mt(223).get("watch", {}) and server._watch_floor(item_) == max(item_["state_updated"], item_["updated"]), mt(223))
server._anchor_release("projects/alpha", notice("first reply", anchor="github:o/r#5", ts=now0 - 3600, ruled_at=now0 - 3600, ruling="passed"), by="home-stew")
m = mt(223)
check("stamp: the first mark stamps the floor the list had (the old last write), not now", arrived_of(223) == [True, False, False] and abs(m["watch"]["set_at"] - item_["updated"]) < 1 and rd(223)["updated"] >= now0, (m.get("watch"), item_["updated"]))
server._anchor_release("projects/alpha", notice("second reply", anchor="github:o/r#6", ts=now0 - 1800, ruled_at=now0 - 1800, ruling="passed"), by="home-stew")
check("stamp: …so a second notice dated before the first mark's save still counts", arrived_of(223) == [True, True, False], (arrived_of(223), mt(223).get("watch")))
# (e) a bool is no time; free text is clipped; the History note is clipped
check("shape: a bool is no arrival time (float(True) is 1.0): the line is a line that has not arrived", not WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": True, "what": "x"}}, It("a1")]})[0])
      and WL.valid({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": True, "what": "x"}}, It("a1")]}) and WL.arrived(WL.lines({**GOOD, "waits": [{**Tm("2026-11-20"), "arrived": {"at": 1, "what": "x"}}, It("a1")]})[0]), None)
LONG = "word " * 200
cl = WL.lines({**GOOD, "waits": [An("https://x/" + "a" * 400, LONG), Ev(LONG), Re(LONG), {**Tm("2026-11-20"), "arrived": {"at": 5.0, "what": LONG}}]})
check("shape: an anchor, an event and the words of an arrival are clipped to LINE_MAX (300); nothing else is", WL.LINE_MAX == 300 and len(cl[0]["anchor"]) == 300 and len(cl[0]["event"]) == 300 and len(cl[1]["event"]) == 300 and len(cl[2]["event"]) == 300
      and len(cl[3]["arrived_what"]) == 300 and cl[3]["until"] == "2026-11-20", [len(cl[0]["anchor"]), len(cl[0]["event"]), len(cl[3]["arrived_what"])])
lst(224, [Re("the lease"), Tm(day(7))], mode="all"); out_ = {}
server._watch_mark("a224", "relay", time.time(), out_, lambda m_: WL.lines_by_kind(m_, "relay"), "he relayed: " + LONG)
check("shape: the History note of an arrival clips its words too (one line's worth), and the stored words keep to LINE_MAX", len(notes_of("a224")) == 1 and len(notes_of("a224")[0]) < 340 and notes_of("a224")[0].endswith("(1 of 2)") and len(mt(224)["waits"][0]["arrived"]["what"]) <= 300, [len(n) for n in notes_of("a224")])
# (4) a list that does not hold is read as the date alone by every reader of the kind
BADL = {"wait_kind": "list", "wait_mode": "all", "until": "2026-12-01", "waits": [Tm("2026-11-20")]}
check("kind_of: a stored list that does not hold is the date alone to waiting.kind_of (time with an until, none without) and to until_write.kind_of (none); a list that holds is a list to both",
      _WT.kind_of(BADL) == "time" and _WT.kind_of({k: v for k, v in BADL.items() if k != "until"}) == "" and UW.kind_of(BADL) == "" and _WT.kind_of(GOOD) == "list" and UW.kind_of(GOOD) == "list"
      and _WT.kind_of({"wait_kind": "relay"}) == "relay" and UW.kind_of({"wait_kind": "relay"}) == "relay", (_WT.kind_of(BADL), UW.kind_of(BADL)))
check("kind_of: …whatever is wrong with the list (not a list of lines, a mode that is neither, no backstop day)", all(not UW.kind_of({**BADL, **bad}) and _WT.kind_of({**BADL, **bad}) in ("time", "") for bad in ({"waits": "x"}, {"wait_mode": "some", "waits": GOOD["waits"]}, {"until": "", "waits": GOOD["waits"]})), None)

# ================================================================ the lows of the display follow-up
# one list whose end fails never stops the lists after it, with the watchers off (the legacy wake pass, as the watchers' pass does it)
reset()
for i_ in (230, 231, 232, 233): lst(i_, [Tm(day(9)), It("a206")], mode="all", until=day(-1))
cfg(watchers=False)
calls_ = []
def flaky(gid, *a, **k):
    calls_.append(gid)
    if gid == "a231": raise RuntimeError("disk")
    return orig_fire(gid, *a, **k)
server._watch_fire = flaky
try:
    woke = server._wake_pass()
    first_calls = list(calls_); calls_.clear()
    woke2 = server._wake_pass()
    next_231 = [at for g, *_, at in server._wakes() if g == "a231"]
finally:
    server._watch_fire = orig_fire; server._WATCH_BACKOFF.pop("a231", None)
check("legacy (watchers off): a list whose end raises is skipped and noted, and the lists after it (and before it) are still ended", "a231" not in woke and all(g in woke for g in ("a230", "a232", "a233"))
      and all(mt(i_).get("mover") == BACK and "wait_kind" not in mt(i_) for i_ in (230, 232, 233)) and mt(231).get("wait_kind") == "list", (woke, first_calls))
check("legacy (watchers off): …the failed one is backed off (noted on the item, as the watchers' pass notes it) and is not tried again by the next pass", mt(231).get("watch", {}).get("failed_at", 0) > 0 and "a231" in first_calls and "a231" not in calls_ and woke2 == [], (first_calls, calls_, mt(231).get("watch")))
check("legacy (watchers off): …and the scheduler looks at it again after the back-off, not at once (so the runner does not spin on it)", len(next_231) == 1 and next_231[0].timestamp() >= time.time() + wk.BACKOFF - 60, next_231)
cfg(watchers=True)
# `_watch_fire(legacy=True)` ends a list that is open and nothing else: a closed item that still stores a list is left alone
lst(234, [Tm(day(9)), It("a206")], mode="all", until=day(-1)); d_ = rd(234); d_["status"] = "completed"; put(234, d_)
cfg(watchers=False); b234 = raw(234); out_ = {}
try: got_ = server._watch_fire("a234", "backstop", time.time(), out_, legacy=True); why_ = ""
except Exception as e_: got_, why_ = None, f"{e_.__class__.__name__}: {e_}"
cfg(watchers=True)
check("legacy: _watch_fire(legacy=True) on a closed item that stores a list does nothing (False, no message, no save, the item as it was)", got_ is False and not out_ and raw(234) == b234, (got_, why_, out_))
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

print(("ok" if not fails else "FAILED") + f": wait list scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
