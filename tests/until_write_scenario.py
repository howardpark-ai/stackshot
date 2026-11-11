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
check("1 …the reply says when the old parameter stops being accepted", UW.ALIAS_UNTIL in out and "refused after" in out, out[-400:])
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
check("1 the window is a config value read at use: [model] wait_alias_until, the code's default when unset", server._wait_alias_until() == dt.date.fromisoformat(UW.ALIAS_UNTIL), None)

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
check("4 the window note prints the date the wait stands for (the legacy wake)", w(2) in note and "alone is a reminder" in note, note)
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

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": until write scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
