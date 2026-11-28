"""Scenario test for hold=true and a wake or until with a time of day on a relay or event wait (stackshot/service/update.py, stackshot/service/gates.py until_in) — a scratch store and config, no port,
no network, no model call. Two parts, one after the other on one scratch store: part A, a hold on a relay or event wait that still stores a work-in-hand state; part B, a hold with a wake on a relay wait.

Part A. The report: an item stored wait_kind=relay beside state doing (the state was stored before the wait was rewritten) listed "model conflict: wait_kind=relay on an item whose state is doing, which
is alive: the wait wins. To drop the wait, update clear_wait=true; to keep it, park the item: update hold=true (a park ends a stored work-in-hand state)". hold=true with a wake was accepted, but on
a relay or event wait no hold flag is stored (the wait is the park), and the stored state was left alone, so the conflict stayed: the advice was circular. And wake=<day>T10:00 on a relay wait was
refused with the ask_by date wording, not the reason until's refusal gives.

  1  hold ends the state   hold=true + wake (or ask_by) on a relay or event wait stored beside state doing: the model has no conflict, the stored state is gone, the wait stays a relay or event wait with its
                           date, no hold flag; the reply says the state was dropped
  2  hold, no state        a relay wait with no stored state is unchanged: accepted, no flag, no state note
  3  wake with a time      wake=<day>T10:00 (and ask_by, and hold with either) on a relay or event wait is fixed, not refused: the day is stored, the time dropped, and the call log counts an ask-by-day fix
  4  unchanged             a hold on an item with no wait still ends its stored state and sets the flag
  5  derived state         a relay or event wait whose needs name only a session and that stores no state lists no alive-state conflict; with a stored doing state it does, and a hold clears it;
                           an anchor wait is not exempt
  6  alive states only     the hold on a relay or event wait ends doing, your-call and your-step (the states the conflict names); outside (party, chase) and verifying (end, proof) keep state and fields

Part B. The report: on an item that waits on a relay with an anchor scoped to it, `update hold=true wake=<a date inside the cap>` was refused with "a hold that waits on a notice from the anchor scoped to
<id> still carries a backstop wake", although a wake was given; and `until=<date>T10:00` was refused with the ask_by wording. Cause: the date of a relay or event wait stands in its ask_by (until_in
sends a wake there), so the hold flag was set with no wake beside it. A relay wait is itself the park until its ask-by day, so the hold adds nothing:

  1  relay + hold   hold=true with a wake (or ask_by) on a relay or event wait is accepted: the date is stored as until, no hold flag, the reply says the wait is the park; hold=true alone on a
                    relay that already has its day is accepted too; a wake past the cap is still refused by the cap
  2  until + time   until with a time of day on a relay or event wait is fixed (the day is stored, the time dropped, an ask-by-day fix is counted)
  3  unchanged      an anchor wait with hold=true and a wake keeps its hold flag; a hold with no date on an anchor-scoped item is still refused with the backstop-wake message

    tests/run-suite hold_relay        -> exit 0 / 1"""
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
from stackshot.web import server; from stackshot.waits import waiting as W, until_write as UW, watchers as WK; from stackshot.model import model as MODEL; from stackshot.service import create as create_svc
from stackshot.anchors import anchors as _anc
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import update as _wt_update
_web_publish._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
BACK = "team-back"
def bupd(i, **kw):
    if kw.get("wake") or kw.get("until") or kw.get("ask_by") or kw.get("wait_kind"): kw.setdefault("wait_reason", "the vendor replies only after that date")
    return _wt_update.stackshot_update(f"a{i}", sender=BACK, **kw)
local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
w = lambda n: local_day(now0 + n * DAY)
OLD = ("wake", "ask_by", "hold", "hold_set")
no_old = lambda m: not any(k in m for k in OLD)
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(x in str(e) for x in want), str(e)[:600])



A1 = "https://github.com/o/r/pull/101"
_anc.save({"projects/alpha": [{"url": A1, "items": [f"a{n}" for n in range(1, 12)], "added": now0, "by": "x"}]})
REL = dict(needs=["external"], until=w(5), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)      # needs external: with the stored state gone the item reads as an outside wait
EVT = dict(needs=["external"], until=w(5), wait_kind="event", wait_event="box_online testbox", post_wake_mover=BACK)
conflicts = lambda g: list(MODEL.derive(_service_store._load(g)).conflicts)
STATE_CONFLICT = "which is alive: the wait wins"

# ################################################################ part A: hold=true on a relay or event wait that still stores a state (the former hold_relay_state suite)

# ================================================================ 1. hold ends the stored state
item(1, state="doing", **REL)
check("1 setup: the stored doing state beside a relay wait lists the conflict", any(STATE_CONFLICT in c for c in conflicts("a1")), conflicts("a1"))
out = bupd(1, hold=True, wake=w(3))
check("1 hold=true + wake on a relay wait with state doing: the stored state is gone", not mt(1).get("state"), mt(1))
check("1 …the model lists no conflict", not conflicts("a1"), conflicts("a1"))
check("1 …the wait stays a relay wait with its new date, no hold flag", mt(1).get("wait_kind") == "relay" and W.stored_until(mt(1)) == w(3) and not mt(1).get("hold") and no_old(mt(1)), mt(1))
check("1 …the reply says the stored state was dropped", "stored state doing dropped" in out, out[-700:])

item(2, state="doing", **REL)
bupd(2, hold=True, ask_by=w(4))
check("1 the same with ask_by", not mt(2).get("state") and not conflicts("a2") and W.stored_until(mt(2)) == w(4) and mt(2).get("wait_kind") == "relay", (mt(2), conflicts("a2")))

item(3, state="doing", **REL)
bupd(3, hold=True)
check("1 hold=true alone on a relay wait that has its day: the state is gone and the day stands", not mt(3).get("state") and not conflicts("a3") and W.stored_until(mt(3)) == w(5) and not mt(3).get("hold"), (mt(3), conflicts("a3")))

item(4, state="doing", **EVT)
bupd(4, hold=True, wake=w(3))
check("1 an event wait takes the same write", not mt(4).get("state") and not conflicts("a4") and mt(4).get("wait_kind") == "event" and W.stored_until(mt(4)) == w(3) and not mt(4).get("hold"), (mt(4), conflicts("a4")))

# ================================================================ 2. no stored state
item(5, **REL)
out = bupd(5, hold=True, wake=w(3))
check("2 a relay wait with no stored state: accepted as before, no state note", not mt(5).get("hold") and W.stored_until(mt(5)) == w(3) and "stored state" not in out and not conflicts("a5"), (mt(5), out[-500:]))

# ================================================================ 3. a wake with a time of day on a relay or event wait
from stackshot.core import call_log as CL
def fixed_by(fn):
    tok = CL.begin()
    try: fn()
    finally: fx = CL.end(tok)
    return fx
item(6, **REL); item(7, **EVT)
for i, nm in ((6, "relay"), (7, "event")):
    kinds = fixed_by(lambda i=i: bupd(i, wake=w(4) + "T10:00"))
    check(f"3 wake with a time of day on a {nm} wait is fixed: the day is stored, the time dropped, the fix is counted", W.stored_until(mt(i)) == w(4) and [k for k, _ in kinds] == ["ask-by-day"] and "wake" in kinds[0][1], (mt(i), kinds))
    kinds = fixed_by(lambda i=i: bupd(i, hold=True, wake=w(3) + "T10:00"))
    check(f"3 hold=true + wake with a time of day on a {nm} wait is fixed the same way", W.stored_until(mt(i)) == w(3) and not mt(i).get("hold") and [k for k, _ in kinds] == ["ask-by-day"] and "wake" in kinds[0][1], (mt(i), kinds))
    kinds = fixed_by(lambda i=i: bupd(i, ask_by=w(2) + "T10:00"))
    check(f"3 ask_by with a time of day on a {nm} wait is fixed the same way", W.stored_until(mt(i)) == w(2) and "T" not in str(W.stored_until(mt(i))) and [k for k, _ in kinds] == ["ask-by-day"] and "ask_by" in kinds[0][1], (mt(i), kinds))
    kinds = fixed_by(lambda i=i: bupd(i, wake=w(1)))
    check(f"3 …the day alone on the {nm} wait is no fix", W.stored_until(mt(i)) == w(1) and kinds == [], (mt(i), kinds))
item(8, needs=[BACK], until=w(5), wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", post_wake_mover=BACK)
bupd(8, wake=w(3) + "T10:00")
check("3 a wake with a time of day on an anchor wait is still accepted", W.stored_until(mt(8)) == w(3) + "T10:00", mt(8))

# ================================================================ 4. unchanged
item(9, state="doing", needs=[BACK], answers=[{"ts": now0 - 9 * DAY, "kind": "decision", "text": "park this until Jun 4th", "via": "board"}])
out = bupd(9, hold=True, wake=w(3))
check("4 a hold on an item with no wait still ends its stored state and sets the flag", mt(9).get("hold") is True and not mt(9).get("state") and "stored state doing dropped" in out, (mt(9), out[-500:]))

# ================================================================ 5. a wait whose needs name only a session: the item reads alive from its fields
SES = dict(needs=[BACK], until=w(5), wait_event="the vendor's reply", post_wake_mover=BACK)
for kind, extra in (("relay", {}), ("event", {"wait_event": "box_online testbox"})):
    item(30, wait_kind=kind, **{**SES, **extra})
    check(f"5 a {kind} wait with session-only needs and no stored state lists no conflict", not conflicts("a30"), conflicts("a30"))
    item(31, wait_kind=kind, state="doing", **{**SES, **extra})
    check(f"5 …with a stored doing state it still lists the conflict", any(STATE_CONFLICT in c for c in conflicts("a31")), conflicts("a31"))
    bupd(31, hold=True, wake=w(3))
    check(f"5 …and a hold on it ends the state and the conflict goes, the {kind} wait and its day stay", not mt(31).get("state") and not conflicts("a31") and mt(31).get("wait_kind") == kind and W.stored_until(mt(31)) == w(3) and not mt(31).get("hold"), (mt(31), conflicts("a31")))
item(32, wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", **{k: v for k, v in SES.items() if k != "wait_event"})
check("5 an anchor wait on an alive-reading item still lists the conflict (only relay and event waits are exempt)", any(STATE_CONFLICT in c for c in conflicts("a32")), conflicts("a32"))

# ================================================================ 6. the hold ends only the alive states the conflict line names
for st in ("doing", "your-call", "your-step"):
    item(40, state=st, **REL)
    bupd(40, hold=True, wake=w(3))
    check(f"6 a relay wait stored as {st} loses the state on a hold and the day stands", not mt(40).get("state") and W.stored_until(mt(40)) == w(3), mt(40))
item(41, state="outside", party="the vendor", chase=w(4), **REL)
bupd(41, hold=True, wake=w(3))
check("6 a relay wait stored as outside keeps its state, party and chase on a hold", mt(41).get("state") == "outside" and mt(41).get("party") == "the vendor" and mt(41).get("chase") == w(4) and W.stored_until(mt(41)) == w(3), mt(41))
item(42, state="verifying", end=w(4), proof="the log shows it", **REL)
bupd(42, hold=True, wake=w(3))
check("6 a relay wait stored as verifying keeps its state, end and proof on a hold", mt(42).get("state") == "verifying" and mt(42).get("end") == w(4) and mt(42).get("proof") == "the log shows it" and W.stored_until(mt(42)) == w(3), mt(42))
item(43, state="outside", party="the vendor", chase=w(4), **EVT)
bupd(43, hold=True, wake=w(3))
check("6 the same on an event wait stored as outside", mt(43).get("state") == "outside" and mt(43).get("party") == "the vendor" and mt(43).get("chase") == w(4), mt(43))

# ################################################################ part B: hold=true with a wake, and until with a time, on a relay wait (the former hold_relay_wake suite)
# the shared scratch store, helpers and anchor above stand; this part's relay wait names the session in needs (REL2), part A's names external (REL)
REL2 = dict(needs=[BACK], until=w(5), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)

# ================================================================ 1. relay + hold
item(1, **REL2)
out = bupd(1, hold=True, wake=w(3))
check("1 hold=true + wake inside the cap on a relay wait is accepted and stored as until, kind kept", W.stored_until(mt(1)) == w(3) and mt(1).get("wait_kind") == "relay", mt(1))
check("1 …no hold flag and no old field is stored", not mt(1).get("hold") and no_old(mt(1)), mt(1))
check("1 …the reply says the wait is the park until its ask-by day", "stores no park flag" in out and w(3) in out, out[-700:])

item(2, **REL2)
bupd(2, hold=True, ask_by=w(4))
check("1 hold=true + ask_by on a relay wait is accepted too", W.stored_until(mt(2)) == w(4) and not mt(2).get("hold"), mt(2))

item(3, **REL2)
out = bupd(3, hold=True)
check("1 hold=true alone on a relay wait that has its day is accepted, the day stands", W.stored_until(mt(3)) == w(5) and not mt(3).get("hold") and "stores no park flag" in out, (mt(3), out[-500:]))

item(4, needs=[BACK], until=w(5), wait_kind="event", wait_event="box_online testbox", post_wake_mover=BACK)
bupd(4, hold=True, wake=w(3))
check("1 an event wait takes the same write", W.stored_until(mt(4)) == w(3) and mt(4).get("wait_kind") == "event" and not mt(4).get("hold"), mt(4))

CAP_MSG = "a wait runs at most 7 days from the item's last move"
NOREL = dict(needs=[BACK], wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)
item(5, **NOREL)
refused("1 hold=true + a wake past the cap on a relay wait with no stored day is refused by the cap's own message", lambda: bupd(5, hold=True, wake=w(19)), CAP_MSG, "this wake (" + w(19) + ")")
check("1 …and nothing was stored", not W.stored_until(mt(5)), mt(5))
item(50, needs=[BACK], wait_kind="event", wait_event="box_online testbox", post_wake_mover=BACK)
refused("1 the same on an event wait with no stored day", lambda: bupd(50, hold=True, wake=w(19)), CAP_MSG)
item(51, **REL2)
refused("1 a wake past the cap on a relay wait that has a day is refused too", lambda: bupd(51, hold=True, wake=w(20)), "Refused")
item(52, **NOREL)
bupd(52, hold=True, wake=w(5))
check("1 a wake inside the cap on a relay wait with no stored day is accepted", W.stored_until(mt(52)) == w(5) and not mt(52).get("hold"), mt(52))
park = {"ts": now0 - 9 * DAY, "kind": "decision", "text": "park this until Jun 4th", "via": "board"}
item(53, answers=[park], **NOREL)
bupd(53, hold=True, wake=w(19))
check("1 a wake past the cap with the owner's recorded words on the item is accepted, and the words are recorded for the day",
      W.stored_until(mt(53)) == w(19) and not mt(53).get("hold") and (mt(53).get("cap_ok") or {}).get("quote") == park["text"], mt(53))

item(54, **REL2)
out = bupd(54, clear_hold=True)
check("1 clear_hold on a relay wait that holds no flag says the wait goes on and clear_wait ends it", "(clear_hold releases a park, and this relay or event wait holds no flag" in out and "clear_wait=true ends the wait" in out and "on hold" not in out and mt(54).get("wait_kind") == "relay", (out[-400:], mt(54)))

# ================================================================ 2. until with a time
item(6, **REL2)
from stackshot.core import call_log as CL
tok = CL.begin()
try: bupd(6, until=w(4) + "T10:00")
finally: fx2 = CL.end(tok)
check("2 until with a time of day on a relay wait is fixed: the day is stored, the time dropped, and the fix is counted", W.stored_until(mt(6)) == w(4) and [k for k, _ in fx2] == ["ask-by-day"] and "until" in fx2[0][1], (mt(6), fx2))
bupd(6, until=w(3))
check("2 until with the day alone is accepted", W.stored_until(mt(6)) == w(3), mt(6))

tok = CL.begin()
try: gid_c, _ = create_svc.create_item(subject="[home] new relay", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: wait for the reply", needs=[BACK],
                                       wait_kind="relay", wait_event="the vendor's reply", until=w(3) + "T10:00", post_wake_mover=BACK, request_id="hrw-create-1")
finally: fxc = CL.end(tok)
check("2 a create with until and a time on a relay wait is fixed the same way: the day is stored", W.stored_until(_service_store._load(gid_c)["metadata"]) == w(3) and [k for k, _ in fxc] == ["ask-by-day"], (gid_c, fxc))

# ================================================================ 3. unchanged
item(8, needs=[BACK], until=w(5), wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", post_wake_mover=BACK)
bupd(8, hold=True, wake=w(3))
check("3 hold=true + wake on an anchor wait keeps the hold flag and the date", mt(8).get("hold") is True and W.stored_until(mt(8)) == w(3), mt(8))
item(10, needs=[BACK])
res10 = _wt_update.stackshot_update("a10", sender=BACK, hold=True)
check("3 a hold with no date on an item with a scoped anchor is accepted with the server's backstop day; the hold flag stays (the anchor's notice releases a hold) and no time kind is stamped",
      mt(10).get("hold") is True and W.stored_until(mt(10)) == w(14) and mt(10).get("until_server") == w(14) and "wait_kind" not in mt(10), (res10, mt(10)))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
