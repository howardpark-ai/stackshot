"""Scenario test for hold=true with a wake, and until with a time, on a relay wait (stackshot/service/update.py, stackshot/service/gates.py until_in) — a scratch store and config, no port, no network, no model call.

The report: on an item that waits on a relay with an anchor scoped to it, `update hold=true wake=<a date inside the cap>` was refused with "a hold that waits on a notice from the anchor scoped to
<id> still carries a backstop wake", although a wake was given; and `until=<date>T10:00` was refused with the ask_by wording. Cause: the date of a relay or event wait stands in its ask_by (until_in
sends a wake there), so the hold flag was set with no wake beside it. A relay wait is itself the park until its ask-by day, so the hold adds nothing:

  1  relay + hold   hold=true with a wake (or ask_by) on a relay or event wait is accepted: the date is stored as until, no hold flag, the reply says the wait is the park; hold=true alone on a
                    relay that already has its day is accepted too; a wake past the cap is still refused by the cap
  2  until + time   until with a time of day on a relay or event wait is refused with the reason (the ask-by day is YYYY-MM-DD)
  3  unchanged      an anchor wait with hold=true and a wake keeps its hold flag; a hold with no date on an anchor-scoped item is still refused with the backstop-wake message

    tests/run-suite hold_relay_wake        -> exit 0 / 1"""
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
def mof(g): return server._load(g)["metadata"]
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import waiting as W, until_write as UW, watchers as WK; from stackshot.model import model as MODEL; from stackshot.service import create as create_svc
from stackshot.web.tools import update as _wt_update
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._front_sender = lambda who: False
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
server._anc.save({"projects/alpha": [{"url": A1, "items": [f"a{n}" for n in range(1, 12)], "added": now0, "by": "x"}]})
REL = dict(needs=[BACK], until=w(5), wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK)

# ================================================================ 1. relay + hold
item(1, **REL)
out = bupd(1, hold=True, wake=w(3))
check("1 hold=true + wake inside the cap on a relay wait is accepted and stored as until, kind kept", W.stored_until(mt(1)) == w(3) and mt(1).get("wait_kind") == "relay", mt(1))
check("1 …no hold flag and no old field is stored", not mt(1).get("hold") and no_old(mt(1)), mt(1))
check("1 …the reply says the wait is the park until its ask-by day", "hold=true is not stored on a relay or event wait" in out and w(3) in out, out[-700:])

item(2, **REL)
bupd(2, hold=True, ask_by=w(4))
check("1 hold=true + ask_by on a relay wait is accepted too", W.stored_until(mt(2)) == w(4) and not mt(2).get("hold"), mt(2))

item(3, **REL)
out = bupd(3, hold=True)
check("1 hold=true alone on a relay wait that has its day is accepted, the day stands", W.stored_until(mt(3)) == w(5) and not mt(3).get("hold") and "not stored" in out, (mt(3), out[-500:]))

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
item(51, **REL)
refused("1 a wake past the cap on a relay wait that has a day is refused too", lambda: bupd(51, hold=True, wake=w(20)), "Refused")
item(52, **NOREL)
bupd(52, hold=True, wake=w(5))
check("1 a wake inside the cap on a relay wait with no stored day is accepted", W.stored_until(mt(52)) == w(5) and not mt(52).get("hold"), mt(52))
park = {"ts": now0 - 9 * DAY, "kind": "decision", "text": "park this until Jun 4th", "via": "board"}
item(53, answers=[park], **NOREL)
bupd(53, hold=True, wake=w(19))
check("1 a wake past the cap with the owner's recorded words on the item is accepted, and the words are recorded for the day",
      W.stored_until(mt(53)) == w(19) and not mt(53).get("hold") and (mt(53).get("cap_ok") or {}).get("quote") == park["text"], mt(53))

item(54, **REL)
out = bupd(54, clear_hold=True)
check("1 clear_hold on a relay wait that holds no flag says the wait goes on and clear_wait ends it", "holds no flag" in out and "clear_wait=true ends the wait" in out and mt(54).get("wait_kind") == "relay", (out[-400:], mt(54)))

# ================================================================ 2. until with a time
item(6, **REL)
refused("2 until with a time of day on a relay wait is refused with the reason", lambda: bupd(6, until=w(3) + "T10:00"), "on a relay or event wait until is its ask-by day, YYYY-MM-DD", "until=" + w(3))
check("2 …nothing was stored", W.stored_until(mt(6)) == w(5), mt(6))
bupd(6, until=w(3))
check("2 until with the day alone is accepted", W.stored_until(mt(6)) == w(3), mt(6))

refused("2 a create with until and a time on a relay wait is refused the same way",
        lambda: create_svc.create_item(subject="[home] new relay", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: wait for the reply", needs=[BACK],
                                       wait_kind="relay", wait_event="the vendor's reply", until=w(3) + "T10:00", post_wake_mover=BACK, request_id="hrw-create-1"),
        "on a relay or event wait until is its ask-by day")

# ================================================================ 3. unchanged
item(8, needs=[BACK], until=w(5), wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", post_wake_mover=BACK)
bupd(8, hold=True, wake=w(3))
check("3 hold=true + wake on an anchor wait keeps the hold flag and the date", mt(8).get("hold") is True and W.stored_until(mt(8)) == w(3), mt(8))
refused("3 a hold with no date on an item with a scoped anchor is still refused with the backstop-wake message", lambda: (item(10, needs=[BACK]), _wt_update.stackshot_update("a10", sender=BACK, hold=True))[1],
        "still carries a backstop wake", "at most 7 days out")

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
