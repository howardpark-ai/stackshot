"""Scenario test for the WRITE side of a wait on a list (waits/wait_list_write.py, gates.gate_waits and the create and update tools) — a scratch store and config, no port, no network, no model call.

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

    tests/run-suite wait_list_write        -> exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="waitlistwrite-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
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
def mof(g): return server._load(g)["metadata"]
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W, until_write as UW, watchers as WK; from stackshot.model import model as MODEL; from stackshot.service import create as create_svc
from stackshot.web.tools import brief as _wt_brief
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
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
server._anc.save({"projects/alpha": [entry(A1), entry(A2)]})        # project-wide anchors: a create and an update may wait on them
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
    m = re.search(r"created (\S+)", out); return server._norm_id(m.group(1)) if m else None
def mof_(g): return server._load(g)["metadata"]
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
check("1 …the model reads a waiting item with a list wait of two lines", MODEL.derive({**server._load(g1), "gid": g1}).wait.kind == "list" and len(MODEL.derive({**server._load(g1), "gid": g1}).waits) == 2, None)
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
refused("1 …an item twice, whichever way it is written", lambda: mk(waits=[It("a900"), It(server._gh.shown("a900"))], until=w(5)), "waits[2] repeats waits[1]")
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
n_items_ = len(list(server._item_files()))
try: mk(waits=[It("a900")], until=w(5), subject="[home] refused")
except Exception: pass
check("1 a refused create stored nothing", len(list(server._item_files())) == n_items_, None)

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
server._anc.save({"projects/alpha": [entry(A2)]})                  # the anchor the stored line waits on is no longer on the list
bupd(80, waits=[An(A1, "merged"), Re("a")], wait_mode="any")
check("4 a line the stored list holds is not judged again: sending the list again with a new mode works though its anchor has left the list", mt(80)["wait_mode"] == "any" and len(mt(80)["waits"]) == 2, mt(80))
refused("4 …while a new anchor line that is not on the list is refused", lambda: bupd(80, waits=[An(A1, "merged"), Re("a"), An(A3, "merged")]), "waits[3]")
server._anc.save({"projects/alpha": [entry(A1), entry(A2)]})
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
check("6h …and on an item that stores a list it clears it and says that instead", "the wait on a list is cleared" in out and "nothing was cleared" not in out, out[-300:])
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
check("7c …a single anchor wait on such an item keeps its note, as before", len(conflicts_("a320")) == 1 and "update hold=true (a hold ends" in conflicts_("a320")[0], conflicts_("a320"))
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
# waits=[] beside a later until
for i_, kw_ in ((344, dict(waits=[], until=w(7))), (345, dict(waits="none", until=w(7))), (346, dict(waits="[]", until=w(7)))):
    fresh(i_, [Tm(w(5)), Re("a")], until=w(6))
    refused(f"7d waits={kw_['waits']!r} beside an until later than the list's backstop is refused in its own words, not as a pushed-out clock", lambda i_=i_, kw_=kw_: bupd(i_, **kw_), "waits=[] ends the list", f"until={w(7)}", f"backstop day {w(6)}", "waits=[] alone")
    check(f"7d …nothing changed ({i_})", listed(mt(i_)) and mt(i_)["until"] == w(6), mt(i_))
fresh(347, [Tm(w(5)), Re("a")], until=w(6))
bupd(347, waits=[], until=w(6))
check("7d waits=[] beside the same day ends the list and leaves the date wait (as before)", not mt(347).get("waits") and mt(347)["until"] == w(6) and not mt(347).get("wait_kind"), mt(347))
fresh(348, [Tm(w(5)), Re("a")], until=w(6))
bupd(348, waits=[], until=w(3))
check("7d …and beside an earlier one", not mt(348).get("waits") and mt(348)["until"] == w(3), mt(348))

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

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": wait list write scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
