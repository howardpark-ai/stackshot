"""Scenario test for the write side of the `until` date of a wait (stackshot/waits/until_write.py and the update / create paths in the server) — a scratch store and config, no port, no network, no model call.

A wait is one stored date, `until`, with an optional `wait_kind` beside it. The old parameters wake, ask_by and hold still work, as aliases that write `until` (and no old field); a write that gives a
kind and no date is never refused (it takes a date); the server clears `until` and `wait_kind` when the wait ends. The read side of `until` is held by the `until` suite; this one holds the writers:

  1  aliases       wake, ask_by and hold(+wake) on update and ask_by on create store `until` and none of the old fields, and the reply names `until`; the `until` parameter stores it with no such note;
                   until=none drops it; after [model] wait_alias_until the old parameters are refused with the way out
  2  no date       a kind with no date (relay, anchor, item, event, time; update and create) is not refused: a date the item's own words give, else its due date or the date of the item it waits after,
                   else tomorrow, and the reply says which; a date held for another kind moves with the wait to the new kind
  3  wait ends     the wake pass, the release of an `after` link, a clear_wait write and the watchers' end_wait clear `until` and `wait_kind` together; an item that stores the old fields keeps its kind
  4  readers       the four readers that read the old fields only: the window note prints the date it stands for; clear_hold on an item that stores only until drops the wait it stood on (ask_by, the
                   post-wake mover, the watcher stamps) and clear_wake keeps a relay's until; the basis is read against the until; the backstop gap reads until (the wait_end suite holds the write)

    tests/run-suite until_write        -> exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="untilwrite-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
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
from stackshot.web import server; from stackshot.waits import waiting as W, until_write as UW, watchers as WK; from stackshot.model import model as MODEL
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._front_sender = lambda who: False
BACK = "team-back"
def bupd(i, **kw):
    if kw.get("wake") or kw.get("until") or kw.get("ask_by") or kw.get("wait_kind"): kw.setdefault("wait_reason", "the vendor replies only after that date")
    return server.stackshot_update(f"a{i}", sender=BACK, **kw)
local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
w = lambda n: local_day(now0 + n * DAY)
OLD = ("wake", "ask_by", "hold", "hold_set")
no_old = lambda m: not any(k in m for k in OLD)
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(x in str(e) for x in want), str(e)[:600])

# ================================================================ 1. the old parameters are aliases of until
item(1, needs=[BACK])
out = bupd(1, wake=w(2))
check("1 wake alone is stored as until, with no old field, and the reply names until", W.stored_until(mt(1)) == w(2) and no_old(mt(1)) and "wake is now written as until" in out and f"until={w(2)}" in out, (out[-400:], mt(1)))
check("1 …the reply says when the old parameter stops being accepted", server._wait_alias_until().isoformat() in out and "refused after" in out, out[-400:])
item(2, needs=[BACK])
out = bupd(2, wait_kind="relay", wait_event="the vendor's reply", ask_by=w(3))
check("1 ask_by on a relay wait is stored as until (the relay's ask-by day), the kind beside it", W.stored_until(mt(2)) == w(3) and mt(2).get("wait_kind") == "relay" and no_old(mt(2)) and "ask_by is now written as until" in out, (out[-400:], mt(2)))
item(3, needs=[BACK])
out = bupd(3, hold=True, wake=w(3), wait_basis=f"the vendor ships {w(3)}")
check("1 hold with a wake and a reason is stored as until with the reason, no hold and no hold stamp, and both old names are in the note",
      W.stored_until(mt(3)) == w(3) and no_old(mt(3)) and W.basis_of(mt(3)) == f"the vendor ships {w(3)}" and "wake and hold are now written as until" in out, (out[-400:], mt(3)))
check("1 …the board reads it as a wait on a time", MODEL.derive({**rd(3), "gid": "a3"}).state == MODEL.WAITING, mt(3))
item(4, needs=[BACK])
out = bupd(4, until=w(2))
check("1 the until parameter stores until with no note about an old name", W.stored_until(mt(4)) == w(2) and no_old(mt(4)) and "now written as until" not in out, (out[-300:], mt(4)))
item(7, needs=[BACK])
out = bupd(7, until=w(3) + "T09:30")
check("1 …a date with a time of day is kept as written", W.stored_until(mt(7)) == f"{w(3)}T09:30", mt(7))
out = bupd(4, until="none")
check("1 …until=none drops it", not W.stored_until(mt(4)) and no_old(mt(4)), mt(4))
refused("1 an until in the past is refused", lambda: bupd(4, until=w(-1)), "until must be in the future")
refused("1 …and one that is no date", lambda: bupd(4, until="2030-02-31"), "until is YYYY-MM-DD")
item(5, needs=[BACK])
out = bupd(5, wake=w(3))
check("1 a second write of the old name moves the one date (it replaces, it does not add a second field)", (bupd(5, wake=w(2)) and True) and W.stored_until(mt(5)) == w(2) and no_old(mt(5)), mt(5))

# a create
g, out = server._create_item(subject="[home] created with an old name", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the reply", needs=[BACK],
                             wait_kind="relay", wait_event="the vendor's reply", ask_by=w(4), request_id="uw-create-1")
m_ = mof(g)
check("1 create: ask_by is stored as until, with the kind beside it and no old field, and the reply names until", W.stored_until(m_) == w(4) and m_.get("wait_kind") == "relay" and no_old(m_) and "ask_by is now written as until" in out, (out[-300:], m_))
g2, out2 = server._create_item(subject="[home] created with until", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the reply", needs=[BACK],
                               wait_kind="relay", wait_event="the vendor's reply", until=w(5), request_id="uw-create-2")
m2_ = mof(g2)
check("1 create: the until parameter is stored as it is, with no note about an old name", W.stored_until(m2_) == w(5) and no_old(m2_) and "now written as until" not in out2, (out2[-300:], m2_))

# the window
real_gate = server._wait_alias_until
server._wait_alias_until = lambda: dt.date(2020, 1, 1)
try:
    item(6, needs=[BACK])
    refused("1 after [model] wait_alias_until a wake is refused with the way out", lambda: bupd(6, wake=w(2)), "wake is not a parameter any more", "until=")
    refused("1 …ask_by and hold too", lambda: bupd(6, wait_kind="relay", wait_event="x", ask_by=w(2)), "ask_by is not a parameter any more")
    refused("1 …hold with its wake names both", lambda: bupd(6, hold=True, wake=w(2), wait_basis=f"vendor reply {w(2)}"), "wake, hold are not a parameter any more")
    check("1 …and until still works", bupd(6, until=w(2)) and W.stored_until(mt(6)) == w(2), mt(6))
finally:
    server._wait_alias_until = real_gate
_held_open = server._cfg.CFG.setdefault("model", {}).pop("wait_alias_until", None)      # the suites hold the window open (tests/_instance.py); the code's own default is read with the key unset
try:
    check("1 the window is a config value read at use: [model] wait_alias_until, the code's default when unset", server._wait_alias_until() == dt.date.fromisoformat(UW.ALIAS_UNTIL), None)
finally:
    if _held_open is not None:
        server._cfg.CFG["model"]["wait_alias_until"] = _held_open
import pathlib as _pl
_example = (_pl.Path(__file__).resolve().parent.parent / "stackshot.example.toml").read_text(encoding="utf-8")
check("1 stackshot.example.toml lists wait_alias_until with the code's date, next to owner_param_until (so a start from it warns of nothing)",
      f'wait_alias_until = "{UW.ALIAS_UNTIL}"' in _example and _example.index("owner_param_until =") < _example.index("wait_alias_until ="), UW.ALIAS_UNTIL)
check("1 …and the suites' own start holds the window open (a fixed date in the example fails no suite after it)", _held_open is None or str(_held_open) >= "2099", _held_open)

# ================================================================ 2. a kind with no date takes a date
item(10, needs=[BACK], next=f"{BACK}: the vendor replies until {w(2)}")
out = bupd(10, wait_kind="relay", wait_event="the vendor's reply")
check("2 a date in the item's own words is taken, and the reply quotes the words", W.stored_until(mt(10)) == w(2) and "wait_kind=relay came with no date" in out and "read from the item's own words" in out, (out[-400:], mt(10)))
item(11, needs=[BACK], due=w(4))
out = bupd(11, wait_kind="relay", wait_event="the vendor's reply")
check("2 no date in the words: the deadline is suggested", W.stored_until(mt(11)) == w(4) and "suggested by its due date" in out, (out[-400:], mt(11)))
item(12, needs=[BACK], until=w(5), wait_kind="time")
item(13, needs=[BACK])
out = bupd(13, wait_kind="item", after=["a12"])
check("2 …or the date of the item it waits after", W.stored_until(mt(13)) == w(5) and "suggested by the item it waits after" in out and mt(13).get("after") == ["a12"], (out[-400:], mt(13)))
item(14, needs=[BACK])
out = bupd(14, wait_kind="relay", wait_event="the vendor's reply")
check("2 nothing gives a date: tomorrow, and the reply says so and how to change it", W.stored_until(mt(14)) == w(1) and "set to tomorrow" in out and "clear_wait=true" in out and no_old(mt(14)), (out[-400:], mt(14)))
for kind, extra, idx in (("event", dict(wait_event="recycle", post_wake_mover=BACK, mover="none"), 16), ("time", {}, 17)):
    item(idx, needs=[BACK])
    try:
        out = bupd(idx, wait_kind=kind, **extra); ok = True
    except Exception as e:
        out, ok = str(e), False
    check(f"2 a {kind} wait with no date is not refused: until is taken and no old field is stored", ok and W.stored_until(mt(idx)) and no_old(mt(idx)) and f"wait_kind={kind} came with no date" in out, (out[-300:], mt(idx)))
item(18, needs=[BACK])
bupd(18, wait_kind="item", after=["a12"])
out = bupd(18, wait_kind="relay", wait_event="the vendor's reply")
check("2 a date held for one kind moves with the wait to another kind (no second fallback, no note)", mt(18).get("wait_kind") == "relay" and W.stored_until(mt(18)) == w(5) and "came with no date" not in out, (out[-300:], mt(18)))
g3, out3 = server._create_item(subject="[home] created with a kind and no date", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the reply", needs=[BACK],
                               wait_kind="relay", wait_event="the vendor's reply", request_id="uw-create-3")
m3_ = mof(g3)
check("2 create: a kind with no date is not refused: until is taken and the reply says so", W.stored_until(m3_) == w(1) and "set to tomorrow" in out3 and no_old(m3_), (out3[-300:], m3_))
# the pure part
D = dt.date(2026, 11, 11)
pd = lambda t, today: (WK.parse_date(t, today) or "")
check("2 fallback_date: the earliest date after today and within the cap in the words, else a suggestion, else tomorrow",
      UW.fallback_date(["file it on 2026-11-14", "or 2026-11-13"], D, pd, 7)[:2] == ("2026-11-13", UW.TEXT)
      and UW.fallback_date(["no date"], D, pd, 7, due="2026-11-15")[:2] == ("2026-11-15", UW.SUGGESTED)
      and UW.fallback_date(["no date"], D, pd, 7, other=["2026-11-17", "2026-11-12"])[:2] == ("2026-11-12", UW.SUGGESTED)
      and UW.fallback_date(["on 2026-12-30"], D, pd, 7, due="2026-12-30")[:2] == ("2026-11-12", UW.TOMORROW), None)

# ================================================================ 3. the end of a wait clears until and wait_kind together
item(20, needs=[BACK], until=w(-1))
item(21, needs=[BACK], until=w(-1), wait_kind="time", post_wake_mover=BACK)
item(22, needs=[BACK], hold=True, wake=w(-1), wait_kind="time", post_wake_mover=BACK)             # stored by the old fields: the pass leaves its kind as it did
woke = server._wake_pass()
check("3 the wake pass: a past until ends the wait, and until goes (with the kind when it stood beside it)", "a20" in woke and "a21" in woke and not W.stored_until(mt(20)) and not W.stored_until(mt(21)) and "wait_kind" not in mt(21), (woke, mt(20), mt(21)))
check("3 …an item that stores the old fields is released as it was: wake and hold go", "a22" in woke and "wake" not in mt(22) and "hold" not in mt(22), mt(22))
item(23, needs=[BACK], until=w(4), wait_kind="item", after=["a24"], post_wake_mover=BACK)
item(24, needs=[BACK])
p24 = rd(24); p24["status"] = "completed"; p24["outcome"] = "done"; (T / "store/a/24.json").write_text(json.dumps(p24))
rel = server._release_after("a24", "done", "", "home-other")
check("3 the release of an after link: the wait is over, until, after and the kind go", "a23" in rel and not W.stored_until(mt(23)) and "after" not in mt(23) and "wait_kind" not in mt(23), (rel, mt(23)))
item(25, needs=[BACK], until=w(4), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)
bupd(25, clear_wait=True)
check("3 clear_wait drops until with the kind and the rest of the wait", not W.stored_until(mt(25)) and "wait_kind" not in mt(25) and "wait_event" not in mt(25) and no_old(mt(25)), mt(25))
m26 = {"until": w(4), "wait_kind": "anchor", "wait_anchor": "https://github.com/o/r/pull/9", "wait_event": "merged", "watch": {"set_at": 1.0}, "needs": [BACK]}
WK.end_wait(m26)
check("3 the watchers' end_wait clears until with the kind group", "until" not in m26 and "wait_kind" not in m26, m26)

# ================================================================ 4. the readers that read the old fields only
from stackshot.model import model_guards as MG
timed_next = f"{BACK}: collect the logs until {w(2)}, then review them"
note = server._wake_window_note({"wake": w(2), "next": timed_next, "needs": [BACK], "project": "projects/alpha"})
check("4 the window note prints the date the wait stands for (the legacy wake)", w(2) in note and "alone is a wait until that date" in note, note)
check("4 …and the same date stored as until with a kind is the wait, not a reminder: no note", server._wake_window_note({"until": w(2), "wait_kind": "time", "next": timed_next, "needs": [BACK], "project": "projects/alpha"}) == "", None)
check("4 …and a kind-less until is a wait too: no reminder note for any stored until", server._wake_window_note({"until": w(2), "next": timed_next, "needs": [BACK], "project": "projects/alpha"}) == ""
      and not server._wake_alone_on_agent({"until": w(2), "needs": [BACK]}), None)
item(40, needs=[BACK], until=w(5), post_wake_mover=BACK, watch={"set_at": now0}, wait_basis={"text": f"the vendor ships {w(5)}", "wake": w(5), "by": BACK, "at": now0})
bupd(40, clear_hold=True)
check("4 clear_hold on an item that stores only until releases it: until, the post-wake mover, the watcher stamps and the basis go", not W.stored_until(mt(40)) and not any(k in mt(40) for k in ("post_wake_mover", "watch", "wait_basis", "wait_kind", "ask_by")), mt(40))
item(41, needs=[BACK], until=w(5), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)
bupd(41, clear_wake=True)
check("4 clear_wake on a relay keeps its until (the ask-by day was never a wake)", W.stored_until(mt(41)) == w(5) and mt(41).get("wait_kind") == "relay", mt(41))
bupd(41, clear_hold=True)
check("4 clear_hold on a relay keeps it too, and its post-wake mover", W.stored_until(mt(41)) == w(5) and mt(41).get("post_wake_mover") == BACK, mt(41))
item(42, needs=[BACK], until=w(30), wait_basis={"text": f"the license expires {w(31)}", "wake": w(30), "by": BACK, "at": now0}, cap_ok={"wake": w(30), "by": "a checked said entry"})
bupd(42, priority="p2")
check("4 the basis is read against the until it was given for: an unrelated write keeps it", W.basis_of(mt(42)) == f"the license expires {w(31)}" and W.stored_until(mt(42)) == w(30), mt(42))
bupd(42, until=w(3))
check("4 …and a write that moves the date to another day drops the record bound to the old one", not W.basis_of(mt(42)) and W.stored_until(mt(42)) == w(3), mt(42))

# ================================================================ 5. defects a review found: each one failed before its fix
# 5.1 clearing the date of a wait that unfolds as a hold (a basis, or the kind time) is not refused as an indefinite park
item(50, needs=[BACK], until=w(5), wait_basis={"text": f"the vendor ships {w(5)}", "wake": w(5), "by": BACK, "at": now0})
try:
    bupd(50, until="none"); e50 = ""
except Exception as e:
    e50 = str(e)
check("5.1 until=none on a wait that carries a basis ends it, no refusal", not e50 and not W.stored_until(mt(50)), (e50, mt(50)))
item(51, needs=[BACK], until=w(5), wait_kind="time")
try:
    bupd(51, clear_wake=True); e51 = ""
except Exception as e:
    e51 = str(e)
check("5.1 clear_wake on a stored time wait ends it, no refusal", not e51 and not W.stored_until(mt(51)), (e51, mt(51)))

# 5.2 a date given in the write that changes the kind of the wait is the date that stands
item(52, needs=[BACK], until=w(3), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)
item(53, needs=[BACK])
bupd(52, wait_kind="item", after=["a53"], until=w(6))
check("5.2 relay → item with a new until: the new date stands, not the earlier one", W.stored_until(mt(52)) == w(6) and mt(52).get("wait_kind") == "item", mt(52))
item(54, needs=[BACK], until=w(6), wait_kind="item", after=["a53"])
bupd(54, wait_kind="relay", wait_event="the vendor's reply", ask_by=w(3), post_wake_mover=BACK)
check("5.2 item → relay with a new ask_by: the new date stands", W.stored_until(mt(54)) == w(3) and mt(54).get("wait_kind") == "relay", mt(54))

# 5.3 a date written as until is a wait, never a reminder: the reply carries no reminder note
item(55, needs=[BACK], next=timed_next)
out55 = bupd(55, until=w(2))
check("5.3 update(until=D) with a timed next line: no reminder note, and the item reads waiting", "alone is a reminder" not in out55 and W.stored_until(mt(55)) == w(2) and mt(55).get("phase") == "waiting", (out55[-500:], mt(55)))

# 5.4 a wait on a date alone ends by dropping the date: needs, after and the mover stay as stored
item(56, needs=["external"], until=w(1))
item(57, needs=[BACK], until=w(1), after=["a53"], wait_kind="item")
for g in (56,):
    d = rd(g); d["metadata"]["until"] = w(-1); (T / f"store/a/{g}.json").write_text(json.dumps(d))
server._watch_pass()
check("5.4 a date-only wait that ends keeps needs=external (the item goes back to others, not to a session)", W.stored_until(mt(56)) is None or not W.stored_until(mt(56)), mt(56))
check("5.4 …and needs stays external, with the arrival recorded", mt(56).get("needs") == ["external"] and mt(56).get("woke"), mt(56))
item(58, needs=[BACK], until=w(1), after=["a53"])
d = rd(58); d["metadata"]["until"] = w(-1); (T / "store/a/58.json").write_text(json.dumps(d))
server._watch_pass()
check("5.4 a date that passes never drops an open after link", mt(58).get("after") == ["a53"], mt(58))

# 5.5 update matches create: a date beside an after link with no kind is the item wait's backstop
item(59, needs=[BACK], hold=True, after=["a53"], wake=w(5), wait_basis={"text": f"the vendor ships {w(5)}", "wake": w(5), "by": BACK, "at": now0})
bupd(59, wake=w(4))
check("5.5 a legacy hold + after given wake= stores the item wait with the date as its backstop", mt(59).get("wait_kind") == "item" and W.stored_until(mt(59)) == w(4) and mt(59).get("after") == ["a53"], mt(59))

# 5.6 a session reads a wait on a date alone as parked, as the board draws it (get's tag, the session items listing); a decision item is never parked
item(60, needs=[BACK], until=w(3))
item(61, needs=["decision"], until=w(3))
fm60, fm61 = server._fmt(dict(rd(60), gid="a60")).splitlines()[0], server._fmt(dict(rd(61), gid="a61")).splitlines()[0]
check("5.6 get tags a wait on a date alone as on hold, and never a decision item", "on hold" in fm60 and "on hold" not in fm61, (fm60, fm61))
st_, ct_, body_ = server._client_get("items", {"key": U["team-back"]})
held_ = {x["gid"]: x["held"] for x in json.loads(body_)["items"]}
check("5.6 the session items listing says held for it, as the board draws it", held_.get("a60") is True, held_)
check("5.6 _is_parked is the renderers' rule: a date-only wait, a hold flag and never a decision item", server._is_parked(rd(60)) and not server._is_parked(rd(61)) and server._is_parked(dict(rd(60), metadata={"hold": True, "needs": [BACK]})), None)

# 5.7 until given to an item that already stores an open after link (no kind, no hold, no after in this write) is that link's backstop, as create stores it
item(62, needs=[BACK], after=["a53"])
bupd(62, until=w(5))
check("5.7 update(until) beside a stored open after link stores the kind item", mt(62).get("wait_kind") == "item" and W.stored_until(mt(62)) == w(5) and mt(62).get("after") == ["a53"], mt(62))
item(63, needs=[BACK], after=["a98"])
bupd(63, until=w(5))
check("5.7 ...a stored link that is already closed stays a date alone", mt(63).get("wait_kind", "") in ("", "time") and W.stored_until(mt(63)) == w(5), mt(63))

# 5.8 a time wait stated as one (wait_kind=time) and written as until carries the basis or his words, as a hold's wake does; a bare date carries wait_reason as a reminder's wake did
item(64, needs=[BACK])
refused("5.8 until with wait_kind=time and no basis is refused for its reason, as a hold's wake is", lambda: bupd(64, until=w(3), wait_kind="time"), "no reason")
item(65, needs=[BACK])
refused("5.8 hold=true with until and no basis is refused for its reason too", lambda: bupd(65, until=w(3), hold=True), "no reason")
out65 = bupd(65, until=w(3), hold=True, wait_basis=f"the vendor ships {w(3)}")
check("5.8 ...with the basis it stands, stored as until with its basis", W.stored_until(mt(65)) == w(3) and W.basis_of(mt(65)), mt(65))
item(66, needs=[BACK])
bupd(66, until=w(3))
check("5.8 a bare date still needs only wait_reason (the wait on a date alone), no basis", W.stored_until(mt(66)) == w(3) and not W.basis_of(mt(66)), mt(66))

# 5.9 a create is capped as an update's wake is
cap9 = W.cap_days()
far9 = local_day(now0 + (cap9 + 20) * DAY)
try:
    server._create_item(subject="[home] created far out", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the date", needs=[BACK], until=far9, request_id="uw-create-cap-1"); e9 = ""
except Exception as e_:
    e9 = str(e_)
check("5.9 create with an until past the cap is refused as an update's wake is", "a wait runs at most" in e9 and "until" in e9, e9[:400])
g9, out9 = server._create_item(subject="[home] created inside the cap", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the date", needs=[BACK], until=w(3), request_id="uw-create-cap-2")
check("5.9 ...an until inside the cap is stored", W.stored_until(mof(g9)) == w(3), mof(g9))
g9b, out9b = server._create_item(subject="[home] relay far out", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the reply", needs=[BACK], wait_kind="relay", wait_event="the vendor's reply", until=far9, request_id="uw-create-cap-3")
check("5.9 ...a relay's ask-by day is no wake: the cap does not judge it, as on an update", W.stored_until(mof(g9b)) == far9, mof(g9b))

# 5.10 a decision beside an until is never parked: the tag, the brief and the session items listing read it the one way the board does (_is_parked)
item(67, needs=["decision", BACK], until=w(3), ask="Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date")
item(68, needs=[BACK], until=w(3))
f67, f68 = server._fmt(dict(rd(67), gid="a67")).splitlines()[0], server._fmt(dict(rd(68), gid="a68")).splitlines()[0]
check("5.10 tag: a decision with an until is not on hold, a date-only wait is", "on hold" not in f67 and "on hold" in f68, (f67, f68))
st_, ct_, body_ = server._client_get("items", {"key": U["team-back"]})
held10 = {x["gid"]: x["held"] for x in json.loads(body_)["items"]}
check("5.10 listing: a decision with an until is held False, a date-only wait True", held10.get("a67") is False and held10.get("a68") is True, held10)
(T / "board.md").write_text("", encoding="utf-8")
brief10 = server.stackshot_brief(); act10, _, hold10 = brief10.partition("\n\nOn hold (")
check("5.10 brief: a decision with an until is among the active items, a date-only wait among the parked", "a67 [open" in act10 and "a67 [open" not in hold10 and "a68 [open" in hold10 and "a68 [open" not in act10, (act10[-300:], hold10[:300]))
check("5.10 all three read the one rule: _is_parked is render.is_held", server._is_parked(rd(68)) and not server._is_parked(rd(67)) and server._is_parked(rd(68)) == server._rmod.is_held(rd(68)) and server._is_parked(rd(67)) == server._rmod.is_held(rd(67)), None)

# 5.11 the alias window's own end is read from the config: a missing [model] wait_alias_until is said once at the start
import contextlib, io as _io
was_model = dict(server._cfg.CFG.get("model") or {})
try:
    server._cfg.CFG.setdefault("model", {}).pop("wait_alias_until", None)
    buf11 = _io.StringIO()
    with contextlib.redirect_stderr(buf11):
        server._wait_alias_check()
    miss11 = buf11.getvalue()
    server._cfg.CFG["model"]["wait_alias_until"] = "2030-01-01"
    buf11b = _io.StringIO()
    with contextlib.redirect_stderr(buf11b):
        server._wait_alias_check()
    server._cfg.CFG["model"]["wait_alias_until"] = "soon"
    buf11c = _io.StringIO()
    with contextlib.redirect_stderr(buf11c):
        server._wait_alias_check()
finally:
    server._cfg.CFG["model"] = was_model
check("5.11 a missing [model] wait_alias_until is warned once, naming the default it stands on", "wait_alias_until is missing" in miss11 and UW.ALIAS_UNTIL in miss11 and miss11.count("config:") == 1, miss11)
import inspect
src11 = inspect.getsource(server._start_background)
check("5.11 the server's start calls the check, after the config notes and before the first migration, so the warning is in the log of every start (the check fails when the call is removed)",
      "_wait_alias_check()" in src11 and src11.index("_cfg.notes()") < src11.index("_wait_alias_check()") < src11.index("_migrate_holds()"), None)
check("5.11 ...a date there is silent, and a value that is not a date is warned too", buf11b.getvalue() == "" and "not a date (soon)" in buf11c.getvalue(), (buf11b.getvalue(), buf11c.getvalue()))

# 5.12 the keeper's relay names a date-only wait as the park it replaces, and the minute loop is woken by it
rel12 = []
real_charge, real_relay, real_owes = server._pilot_charge, server._pilot_relay, server._writer_owes
server._pilot_charge = lambda project, who: ("home-stew", "name")
server._writer_owes = lambda: False
server._pilot_relay = lambda project, gid, item, what, debtor, stew, role, tail="": (rel12.append(what), "told")[1]
try:
    item(69, needs=[BACK]); server._WAKE_EVENT.clear()
    bupd(69, until=w(3))
    woke12 = server._WAKE_EVENT.is_set()
    bupd(69, clear_hold=True)
finally:
    server._pilot_charge, server._pilot_relay, server._writer_owes = real_charge, real_relay, real_owes
check("5.12 a write that sets a date-only wait tells the keeper 'put on hold', and one that clears it 'released from hold'", len(rel12) == 2 and rel12[0] == "put on hold" and rel12[1] == "released from hold", rel12)
check("5.12 ...and the minute loop is woken by the write that parks it", woke12, None)

# 5.13 the words that teach the date carry the hand-off exception, and none calls a date a reminder or recommends the aliases the window ends
until_desc = server._UNTIL_PARAM.__metadata__[0].description
check("5.13 the until parameter's own text says that in a hand-off the date is only the backstop and parks nothing", "outside a hand-off" in until_desc and "backstop" in until_desc and "stays active" in until_desc, until_desc[:400])
upd_desc = server._UPDATE_DESC
check("5.13 the update description calls a date a reminder nowhere (a decision's dropped hold, the drop of a date) and drops a date with until=none",
      "its wake stays, a reminder" not in upd_desc and "a reminder simply goes" not in upd_desc and "(its date stays" in upd_desc and 'until="none"' in upd_desc, None)
import pathlib as pathlib_
docs13 = {n_: (pathlib_.Path(__file__).resolve().parent.parent / "docs" / n_).read_text(encoding="utf-8") for n_ in ("handoffs.md", "waiting-and-doing.md")}
check("5.13 docs/handoffs.md no longer calls the wake a reminder that parks only with hold=true, and says a hand-off write ends a park", "a wake parks an item only with an explicit" not in docs13["handoffs.md"] and "ends that wait" in docs13["handoffs.md"] and "backstop" in docs13["handoffs.md"], None)
check("5.13 docs/waiting-and-doing.md's paragraph carries the hand-off exception", "outside a hand-off" in docs13["waiting-and-doing.md"] and "backstop" in docs13["waiting-and-doing.md"], None)

# 5.14 no refusal text, state hint or comment teaches the date as a reminder that leaves the item active
import pathlib as _pl14
root14 = _pl14.Path(__file__).resolve().parent.parent
from stackshot.model import model_guards as _mg14, states as _st14
defer14 = _pl14.Path(_mg14.__file__).read_text(encoding="utf-8")
check("5.14 the next_defers refusal says a bare date makes the item wait until then (outside a hand-off it parks), not that it is a reminder that leaves the item active",
      "is a reminder that leaves the item active" not in defer14 and "until=YYYY-MM-DD makes the item wait until then (outside a hand-off the date parks the item" in defer14, None)
states14 = _pl14.Path(_st14.__file__).read_text(encoding="utf-8")
check("5.14 the parked state's missing-field hint no longer says a wake alone is never a park", "a wake alone is a reminder, never a park" not in states14 and "a date alone makes the item wait until then, outside a hand-off" in states14, None)
stale14 = [str(f.relative_to(root14)) for f in (root14 / "stackshot").rglob("*.py")
           if any(x in f.read_text(encoding="utf-8") for x in ("a wake alone is a reminder", "A wake alone is a reminder", "is a reminder that leaves the item active", "check-back reminder, and the item stays alive"))]
check("5.14 no stackshot source still says a wake alone is a reminder (the comments and docstrings too)", not stale14, stale14)
phrases14 = {str(f.relative_to(root14)): [x for x in ("shows no wait", "show no wait") if x in f.read_text(encoding="utf-8")] for f in (root14 / "stackshot").rglob("*.py")}
check("5.14 no stackshot source says a wake alone shows no wait (the get and brief text, the update description, comments)", not any(phrases14.values()), {k: v for k, v in phrases14.items() if v})
served14 = [r for r in ("stackshot/web/server.py", "stackshot/waits/self_wait.py", "stackshot/model/model_guards.py", "stackshot/model/states.py") if "check-back" in (root14 / r).read_text(encoding="utf-8")]
check("5.14 no served text or prompt (server.py, self_wait.py, model_guards.py, states.py) still calls a date a check-back", not served14, served14)
# what the update description now says about a basis is what the guard does: a bare date within the cap refuses one, a hold's wake and a date past the cap take one
item(94, needs=[BACK]); item(95, needs=[BACK]); item(96, needs=[BACK])
refused("5.14 a bare date within the cap refuses a wait_basis as not needed", lambda: bupd(94, until=w(3), wait_basis=f"the vendor ships {w(3)}"), "wait_basis is not needed", "a wait on its own")
check("5.14 …a hold's wake takes it", bool(bupd(95, hold=True, wake=w(3), wait_basis=f"the vendor ships {w(3)}")) and bool(W.basis_of(mt(95))), mt(95))
check("5.14 …and a date past the cap takes it", bool(bupd(96, until=w(40), wait_basis=f"the vendor ships {w(40)}")) and bool(W.basis_of(mt(96))), mt(96))
upd14 = server._UPDATE_DESC + server._WAIT_FORM
check("5.14 the update description says so: a bare date within the cap refuses a basis unless the item is on hold or verifying, and a date no longer leaves an item active as a reminder",
      "A bare date within the cap (until, or its old name wake) is a wait on its own" in upd14 and "refused as not needed unless the item is on hold (hold=true) or verifying" in upd14 and "a date no longer leaves the item active as a reminder" in upd14, None)
check("5.14 docs/item-model.md names until as the one date of a wait", "stored as `until`" in (root14 / "docs" / "item-model.md").read_text(encoding="utf-8"), None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": until write scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
