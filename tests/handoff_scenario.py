"""Scenario test for the hand-off machinery of the item model (handoff.py, cold_call.py, server.py step 2, part 1) — fixture data, no live store, no network, no server socket.

An alive item has one mover. A write that changes it to a session other than the writer records a hand-off on the item; the clock and the fallbacks act on it:

  1  the record (to, from, at, delivered_at, taken_at) on a mover change by a session; not on a self-naming; the owner as new mover has a record with no clock
  2  delivered: set when the push to the new mover came back delivered, not when it failed; a push that waits is neither; a failed push is sent once more, a second failure
     sends the item down section 5 with the sender told on the item
  3  taken: the new mover's first write that shows work started (a step marked done, a work line in progress or done, the item closed), by name and by id; another session's write does not take it,
     and neither does the mover's own note, confirm, queue or wait line, a reword of next or description, a hold or a wake: the 10-minute clock keeps running on those
  4  the clock: a delivered hand-off not taken in [model] handoff_minutes, or whose recipient's turn ended with no write, goes to the project's background agent (the builder
     first), not back to the sender; a front agent is never clocked; the sender is told once
  5  section 5 in order: the background agent, the cold call (hand to / close / ask Oliver, written as `cold-call`; a bad answer or a failed call falls on), the sender (never
     the owner), then stuck (listed in the brief); a gone mover goes the same way without the sender
  6  [model] pause holds the clock and the gone-mover pass, and what is due fires in one batch; one pass that fires several items for one recipient sends one message
  7  the send-time guard: a hand-off to a session with no pane is refused, the background agent named
  8  display: get shows handed to X, not yet taken (since HH:MM) | taken HH:MM | returned to Y: X did not take it in 10 min, in the instance's timezone; the brief carries one line
  9  [model] handoff = false: nothing is recorded, nothing is clocked
 10  the hand-off path from the router's side: the background agent a hand-off falls to is the router's builder
 12  a hand-off to Oliver: his board answer, a session relaying it, his GitHub comment, or the item leaving his hands (a save of the server's own) ends the record; nothing else does
 16  a background agent that did not take a hand-off is reminded once (11 min yes, 9 no), the ladder goes on only after another handoff_minutes; an anchor scoped to the item counts as taken; a front
     agent, a no_clock record and a name that is no live background session (unknown, retired, a keeper entry, an unreadable role map) get no reminder
 14  a turn that ends in a relaunch is no answer: a delivered hand-off whose mover's pane was relaunched before it wrote is sent again once, not cold-called, and the clock restarts
     from the re-send; a second loss goes down section 5. A ladder write the server refuses (the cold call's answer) is tried once more, then the item is stuck with the refusal text (see 5 ladder write)

    tests/run-suite handoff        → exit 0 / 1"""
import contextlib, datetime, io, json, os, re, subprocess, sys, pathlib, tempfile, threading, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="handofftest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the hand-offs, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-send", "home-dead", "home-beta-front", "home-gamma-front", "home-gamma-bg", "home-idle", "home-send-dead", "home-stew", "home-beta-stew", "home-gamma-stew", "home-gamma-docs", "home-fleet")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DEAD_ISO = datetime.datetime.fromtimestamp(now0 - 3 * 3600, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")      # gone three hours: past [client] dead_after_minutes
GONE = {"home-dead", "home-gamma-bg", "home-send-dead"}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": DEAD_ISO}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if n in GONE else {})} for n, u in U.items() if n != "home-idle"}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: front home-front; background home-docs (listed first) and team-back (builds), home-idle (listed, no pane at all); beta: a front agent and no background agent;
# gamma: a front agent and a background agent whose pane has been gone for hours
ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code", "home-idle": "listed, no pane"}
GAMMA = {"home-gamma-front": "the front", "home-gamma-bg": "builds the code", "home-gamma-docs": "keeps the pages"}      # the cold call is offered background agents only, so gamma has a second one with a pane
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back", "home-idle")}),
    "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {}),
    "projects/gamma": proj("home-gamma-stew", GAMMA, {k: GAMMA[k] for k in ("home-gamma-bg", "home-gamma-docs")})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"}), ("gamma", "home-gamma-stew", GAMMA)):
    back = [k for k in agents if k in ("home-docs", "team-back", "home-idle", "home-gamma-bg", "home-gamma-docs")]
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the sample task is in progress.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", project="projects/alpha", letter="a", updated=None, **meta):
    up = now0 - 3600 if updated is None else updated
    base = {"owner": owner or U["home-front"], "project": project, "next": "home-front: do the thing"}
    if not ({"needs", "hold", "after", "mover", "then"} & set(meta)): base["mover"] = "home-front" if owner is None else owner      # the creator moves nothing; the fixture's items are moved by the session that used to be their creator
    base.update(meta)
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": up, "state_updated": up, "confirmed": up, "metadata": base}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def ho(i): return mt(i).get("handoff") or {}
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want, none=()):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want) and not any(w in str(e) for w in none), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.service import gates; from stackshot.web import server; from stackshot.service import writes; from stackshot.waits import handoff as H; from stackshot.model import cold_call as CC; from stackshot.model import model; from stackshot.router import router_live
from stackshot.service import telling
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
# section 15's invariant, checked after every save of the run: an OPEN record never names someone but the item's mover (handoff.stale)
_real_save = writes.save
INV_BAD = []; INV_SAVES = [0]
def _save_inv(gid, item, *a, **kw):
    out = _real_save(gid, item, *a, **kw)
    try:
        INV_SAVES[0] += 1
        mv = H.mover_of(item, lambda it: server._ho_derive({**it, "gid": gid}))
        if H.stale(item, mv, server._ho_same) and gid not in (f'a{34}', f'a{171}'): INV_BAD.append((gid, (item.get("metadata") or {}).get("handoff"), mv, kw.get("note") or (a[1] if len(a) > 1 else "")))
    except Exception as e:
        INV_BAD.append((gid, "checker failed", repr(e)))
    return out
writes.save = _save_inv
# the push: a fake script. A uuid listed in push-fail.txt fails, one in push-inbox.txt waits (inbox), the rest are delivered; every call is logged
PUSHLOG, FAIL, INBOX = T / "push.log", T / "push-fail.txt", T / "push-inbox.txt"
QUEUED, PAUSED = T / "push-queued.txt", T / "push-paused.txt"
(T / "fakepush.py").write_text(f"import sys, json, os\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"open({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\n"
                               f"if os.path.exists({str(FAIL)!r}) and a[0] in open({str(FAIL)!r}).read().split():\n    print('failed: not live'); sys.exit(2)\n"
                               f"if os.path.exists({str(INBOX)!r}) and a[0] in open({str(INBOX)!r}).read().split():\n    print('inbox → ' + a[0]); sys.exit(1)\n"
                               f"if os.path.exists({str(QUEUED)!r}) and a[0] in open({str(QUEUED)!r}).read().split():\n    print('queued → ' + a[0]); sys.exit(1)\n"
                               f"if os.path.exists({str(PAUSED)!r}) and a[0] in open({str(PAUSED)!r}).read().split():\n    print('queued (paused for a reboot) → ' + a[0]); sys.exit(1)\n"
                               f"print('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake"):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
    while server._HO_COLD_THREADS: server._HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
def clear_pushes(): PUSHLOG.unlink(missing_ok=True)
def failing(*names): FAIL.write_text("\n".join(U[n] for n in names)) if names else FAIL.unlink(missing_ok=True)
def inbox(*names): INBOX.write_text("\n".join(U[n] for n in names)) if names else INBOX.unlink(missing_ok=True)
def queued(*names): QUEUED.write_text("\n".join(U[n] for n in names)) if names else QUEUED.unlink(missing_ok=True)
def paused(*names): PAUSED.write_text("\n".join(U[n] for n in names)) if names else PAUSED.unlink(missing_ok=True)
def rec(to, frm="home-send", **kw):
    """A hand-off record made by the machinery an hour ago (delivered, not taken), for an item that is written to disk with it (the store holds records only this machinery made)."""
    return H.new_record(to, U[to], frm, now0 - 3600, **{"delivered_at": now0 - 3500, **kw})
def set_cfg(**kw): server._cfg.CFG["model"] = dict(kw)
set_cfg()
server._cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder: the last rung of the ladder asks it, once, to recover a session nobody could hand the item to
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def main_recovery_pushes(gid): return [p for p in pushes_to("home-beta-front", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, marked for the owner
server._COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}
COLD_MSGS = []
def cold(answer, status="ok"):
    def run(msg):
        COLD_MSGS.append(msg)
        return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    server._COLD_RUNNER = run
def cli_row(who, status, at, name=None, started=None, kind="interactive", pid=None, file=None, sid=None):
    """The CLI's own registry row of a pane on this box: status busy | idle and when it changed (ms); `started` (epoch s) is when its process started (startedAt, ms): a new process is a relaunch.
    `kind` is the row's kind (interactive: a pane; anything else is no pane), `pid` its process (default: this one, which is alive), `file` a second row's file name, `sid` a session id other than the pane's."""
    (T / f"cli/{file or f'{os.getpid()}-{who}.json'}").write_text(json.dumps({"pid": pid or os.getpid(), "sessionId": sid or U[who], "name": name or who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000),
                                                                              "kind": kind, **({"startedAt": int(started * 1000)} if started is not None else {})}))
server.CLI_SESSIONS = T / "cli"
OWN = model.owner_display()
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
FUT = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400 + ZONE_OFFSET))
CHK = "unit_active watchtest.service"      # a hand-off by a session that is not a front agent needs a check or a date (wake or until): the hand() helper uses the check; the date forms are in the 15.1b block
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
def upd(i, sender, **kw): return server._update(f"a{i}", sender=sender, **kw)
def tick(at, *ids):
    """One pass of the hand-off clock at `at` (None: now) over the named items only (none named: the whole board)."""
    return server._handoff_tick(now=at, only=[f"a{i}" for i in ids] or None)
def hand(i, to, sender="home-send", **kw):
    """sender hands item a<i> to `to`: mover=<to> (needs names only a background agent or the owner), and the next line names it."""
    return upd(i, sender, mover=to, next=f"{to}: do the thing", **({} if telling.front_sender(sender) else {"check": CHK}), **kw)       # a next line naming another session needs a check or a wake (the done-check rule); a front agent's hand-off asks for neither and may not set them
def start(i, sender, **kw):
    """sender starts work on a<i>: the one write that shows it without closing the item (a work line in progress)."""
    return upd(i, sender, work={"text": "doing it", "state": "in progress"}, **kw)
ZONE = server.ZONE
assert datetime.datetime.now(ZONE).utcoffset() == datetime.timedelta(seconds=ZONE_OFFSET)
hhmm = lambda ts: datetime.datetime.fromtimestamp(ts, ZONE).strftime("%H:%M")
def got(i): return server._fmt({**rd(i), "gid": f"a{i}"})
MIN = 60.0

# ================================================================ 1. the record
item(1)
hand(1, "home-peer")
r = ho(1)
check("1 record: a mover change by another session records the hand-off (to, from, at), delivered and taken not yet known",
      r.get("to") == "home-peer" and r.get("from") == "home-send" and abs(r.get("at", 0) - time.time()) < 30 and r.get("delivered_at") is None and r.get("taken_at") is None and r.get("to_id") == U["home-peer"], r)
drain()
check("1 record: …and the push that told the new mover (the one \"now needs you\" line of the write) set delivered_at", isinstance(ho(1).get("delivered_at"), float) and ho(1).get("taken_at") is None, ho(1))
check("1 record: …with one push to the new mover, not two (the hand-off notice is not added to what the write already told)", len(pushes_to("home-peer", "a1")) == 1, pushes())
item(2, owner=U["home-front"], needs=[])
upd(2, "home-peer", mover="home-peer", next="home-peer: do the thing")
check("1 record: a writer naming itself is no hand-off", "handoff" not in mt(2), mt(2))
item(3, owner=U["home-front"], mover="home-peer", next="home-peer: do the thing")
upd(3, "home-peer", mover="home-peer", goal="the thing works")
check("1 record: a write that changes no mover records nothing", "handoff" not in mt(3), mt(3))
item(4, mover="home-peer", next="home-peer: do the thing")
upd(4, "home-peer", needs=["decision"], ask=ASK, next=f"{OWN}: decide", clear_mover=True)
r = ho(4)
check("1 record: the owner as new mover is a record with no clock", r.get("to") == OWN and r.get("from") == "home-peer" and r.get("no_clock") is True and r.get("delivered_at") is None, r)
check("1 record: …and nothing ever fires on it (a day later, nothing)", tick(time.time() + 86400, 4) == [] or ho(4).get("to") == OWN, ho(4))
check("1 record: …the item is still his", ho(4).get("to") == OWN and "needs" in mt(4) and "decision" in mt(4)["needs"], mt(4))
# a new hand-off moves the old record into the history
item(5)
hand(5, "home-peer"); drain(); hand(5, "home-peer2", sender="home-peer"); drain()
check("1 record: a later hand-off replaces the record and the old one goes to the history (handed on by its mover with no work started: not taken)", ho(5).get("to") == "home-peer2" and ho(5).get("from") == "home-peer"
      and len(mt(5).get("handoff_history") or []) == 1 and mt(5)["handoff_history"][0].get("to") == "home-peer" and not mt(5)["handoff_history"][0].get("taken_at"), mt(5))
# a create with another session in needs is a hand-off too

# ================================================================ 2. delivered, waiting, failed
item(10); clear_pushes(); inbox("home-peer")
hand(10, "home-peer"); drain()
check("2 delivered: a push that waits in the inbox is neither delivered nor failed", ho(10).get("delivered_at") is None and ho(10).get("queued", "").startswith("inbox") and not ho(10).get("attempts"), ho(10))
check("2 delivered: …it is queued (queued_at), with no delivered_at", isinstance(ho(10).get("queued_at"), float) and len(pushes_to("home-peer", "a10")) == 1, (ho(10), pushes()))
# the puller's ack, seen by the server in the /inbox/ack route, is the delivery
from stackshot.fleet import inbox as IB
iid = IB.put(U["home-peer"], server._handoff_text("a10", rd(10), ho(10)), "msg", sender="home-send")
st_, body_ = server._client_post("a", "ack", {"delivered": [iid]})
check("2 ack: the puller's ack of the hand-off notice (read from the inbox file before it goes) makes the hand-off delivered, at the ack's time", st_ == 200 and abs((ho(10).get("delivered_at") or 0) - time.time()) < 30
      and "queued_at" not in ho(10) and "queued" not in ho(10) and not IB.exists(iid), (st_, body_, ho(10)))
iid = IB.put(U["home-peer"], "[stackshot] a99 is handed to you by home-send: something else", "msg", sender="home-send"); item(98); hand(98, "home-peer"); inbox("home-peer"); drain()
server._client_post("a", "ack", {"delivered": [iid]})
check("2 ack: …an acked line about another item delivers nothing", ho(98).get("delivered_at") is None and ho(98).get("queued", "").startswith("inbox"), ho(98))
inbox()
# no ack seen: the clock starts [model] handoff_inbox_grace_minutes (10) after the line was queued
item(12); inbox("home-peer"); hand(12, "home-peer"); drain(); inbox(); q12 = ho(12)["queued_at"]
check("2 grace: a line that waits and whose ack is not seen: nothing is due while the grace and the minutes run (19 min after it was queued)", tick(q12 + 19 * MIN, 12) == [] and ho(12).get("to") == "home-peer", ho(12))
done = tick(q12 + 21 * MIN, 12); drain()
check("2 grace: …and 10 min of grace plus the 10 minutes on, it goes to the project's builder", done == ["a12"] and ho(12).get("to") == "team-back", (done, ho(12)))
set_cfg(handoff_inbox_grace_minutes=3)
item(13); inbox("home-peer"); hand(13, "home-peer"); drain(); inbox(); q13 = ho(13)["queued_at"]
check("2 grace: [model] handoff_inbox_grace_minutes sets the grace (3: nothing at 12 min, due at 14)", tick(q13 + 12 * MIN, 13) == [] and tick(q13 + 14 * MIN, 13) == ["a13"], ho(13))
drain(); set_cfg()
# queued is not failed: the pane is not reachable now (push.py's `queued →`), or a reboot's pause holds the line
item(14); queued("home-peer"); clear_pushes(); hand(14, "home-peer"); drain()
check("2 queued: `queued →` (the pane is not reachable now) is waiting, not failed: no retry, no failure on the record, a queue time", len(pushes_to("home-peer", "a14")) == 1 and not ho(14).get("attempts")
      and ho(14).get("queued", "").startswith("queued") and isinstance(ho(14).get("queued_at"), float) and ho(14).get("to") == "home-peer", (ho(14), pushes()))
item(15); queued(); paused("home-peer"); clear_pushes(); hand(15, "home-peer"); drain(); paused()
check("2 queued: …and so is `queued (paused for a reboot)`", len(pushes_to("home-peer", "a15")) == 1 and not ho(15).get("attempts") and ho(15).get("queued", "").startswith("queued (paused"), (ho(15), pushes()))
check("2 queued: …neither moved the item", ho(14).get("to") == "home-peer" and ho(15).get("to") == "home-peer", None)
item(11); clear_pushes(); failing("home-peer2")
hand(11, "home-peer2"); drain()
r = ho(11)
check("2 failed: a push that fails is sent once more (two pushes to it), and a second failure sends the item to the project's background agent (the builder, not home-docs)",
      len(pushes_to("home-peer2", "a11")) == 2 and r.get("to") == "team-back" and r.get("via") == "redirect" and r.get("redirected_from") == "home-peer2" and "home-peer2" in (r.get("tried") or []), (r, pushes()))
check("2 failed: …the sender is told on the item (the failures and the move are its events) and by one push", any("failed" in e.get("text", "") for e in r.get("events", [])) and len(pushes_to("home-send", "a11")) == 1
      and "needs" in mt(11) and mt(11)["needs"][0] == "team-back" and "home-peer2" not in mt(11)["needs"], (r.get("events"), mt(11), pushes()))
check("2 failed: …and the background agent is told, its delivery set on the new record", len(pushes_to("team-back", "a11")) == 1 and isinstance(ho(11).get("delivered_at"), float), (ho(11), pushes()))
failing()

# ================================================================ 3. taken
item(20); item(21); item(22); item(23)
hand(20, "home-peer"); hand(21, "home-peer"); hand(22, "home-peer"); hand(23, "home-peer"); drain()
upd(20, "home-send", next="home-peer: do the thing again")
check("3 taken: another session's write does not take it (the sender's own write neither)", not ho(20).get("taken_at"), ho(20))
upd(20, "home-peer", next="home-peer: done the first part")
check("3 taken: the new mover's reword of next is no start: not taken", not ho(20).get("taken_at"), ho(20))
upd(20, "home-peer", description="- queued behind two other items")
check("3 taken: …a description write neither", not ho(20).get("taken_at"), ho(20))
upd(20, "home-peer", next="home-peer: queued behind a9, waiting")
check("3 taken: …a queue note in next neither (the sentence is not read, only the marks are)", not ho(20).get("taken_at"), ho(20))
server.stackshot_confirm("a21", sender="home-peer")
check("3 taken: …a confirm by the new mover is no start either", not ho(21).get("taken_at"), ho(21))
# the clock keeps running on a note-only mover (a queue note alone used to take the item and stop the nudges)
item(24); hand(24, "home-peer"); drain(); dlv24 = ho(24)["delivered_at"]
upd(24, "home-peer", next="home-peer: queued behind a9, starting at my next turn")
upd(24, "home-peer", description="- queued behind board#6")
server.stackshot_confirm("a24", sender="home-peer")
check("3 taken: notes, a description write and a confirm leave the hand-off untaken", not ho(24).get("taken_at"), ho(24))
done = tick(dlv24 + 11 * MIN, 24); drain()
check("3 taken: …so the clock still fires after ten minutes: the item goes down section 5 to the builder, as if nothing was written",
      done == ["a24"] and ho(24).get("to") == "team-back" and "did not take it in 10 min" in ho(24).get("reason", ""), (done, ho(24)))
start(20, "home-peer")
check("3 taken: the new mover's work line in progress takes it, by name", isinstance(ho(20).get("taken_at"), float) and ho(20).get("to") == "home-peer", ho(20))
upd(21, "home-peer", work={"text": "queued", "state": "defined"})
check("3 taken: a work line only defined (queued) is no start", not ho(21).get("taken_at"), ho(21))
upd(21, "home-peer", done=[2])
check("3 taken: …a step marked done does (the sender's own step 1 is another's: the mover's is step 2)", isinstance(ho(21).get("taken_at"), float), (ho(21), mt(21).get("steps")))
upd(22, U["home-peer"], next="home-peer: done by id")
check("3 taken: …a note by its transcript id is no start", not ho(22).get("taken_at"), ho(22))
start(22, U["home-peer"])
check("3 taken: …and a start by its transcript id counts as the same session", isinstance(ho(22).get("taken_at"), float), ho(22))
upd(23, U["home-peer"], dropped=[2])
check("3 taken: …a step dropped is no start (dropping is not work)", not ho(23).get("taken_at"), ho(23))
bef = {"status": "open", "metadata": {"owner": "o", "next": "x: a", "steps": [{"text": "x: a", "status": "open"}]}}
check("3 taken: pure: a close is a start; a note, a dropped step, a new step and a work line only defined are not; a step done, a work line in progress or done are",
      H.started(bef, {**bef, "status": "completed"}) and not H.started(bef, {**bef, "metadata": {**bef["metadata"], "next": "x: queued"}})
      and not H.started(bef, {**bef, "metadata": {"owner": "o", "steps": [{"text": "x: a", "status": "dropped", "by": "x", "at": 5.0}]}})
      and not H.started(bef, {**bef, "metadata": {**bef["metadata"], "next": "x: a\nx: b", "steps": [*bef["metadata"]["steps"], {"text": "x: b", "status": "open"}]}})
      and not H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "defined"}]}})
      and not H.started(None, bef) and not H.started(bef, bef)
      and H.started(bef, {**bef, "metadata": {"owner": "o", "steps": [{"text": "x: a", "status": "done", "by": "x", "at": 5.0}]}})
      and H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "in progress"}]}})
      and H.started(bef, {**bef, "metadata": {**bef["metadata"], "work": [{"id": "1", "text": "t", "state": "done"}]}}), None)
tg = {"text": "PR up", "state": "in progress", "ts": 1000.0}
bs = {"status": "open", "metadata": {"owner": "o", "next": "x: a", "steps": [{"text": "x: a", "status": "open", "tag": tg}]}}
check("3 taken: pure: a reword of a step that carries a status is no start (the status is unchanged: same words, state and time); a new or changed status is",
      not H.started(bs, {**bs, "metadata": {"owner": "o", "next": "x: a, reworded", "steps": [{"text": "x: a, reworded", "status": "open", "tag": dict(tg)}]}})
      and H.started(bs, {**bs, "metadata": {**bs["metadata"], "steps": [{"text": "x: a", "status": "open", "tag": {**tg, "text": "review", "ts": 2000.0}}]}})
      and H.started(bef, {**bef, "metadata": bs["metadata"]}), None)
t0 = ho(20)["taken_at"]; upd(20, "home-peer", next="home-peer: a second write")
check("3 taken: the first start stays the time it was taken", ho(20)["taken_at"] == t0, ho(20))

# ================================================================ 4. the clock, the turn end, the exemptions
item(30); clear_pushes()
hand(30, "home-peer"); drain()
d30 = ho(30)["delivered_at"]
check("4 clock: nine minutes after the delivery nothing is due", tick(d30 + 9 * MIN, 30) == [] and ho(30).get("to") == "home-peer", ho(30))
done = tick(d30 + 11 * MIN, 30); drain()
r = ho(30)
check("4 clock: ten minutes on, a delivered hand-off not taken goes to the project's background agent (the builder), not back to the sender",
      done == ["a30"] and r.get("to") == "team-back" and r.get("via") == "redirect" and "did not take it in 10 min" in r.get("reason", "") and mt(30)["needs"][0] == "team-back", (done, r))
check("4 clock: …the old record is in the history, with what ended it", (mt(30).get("handoff_history") or [{}])[-1].get("to") == "home-peer" and "10 min" in (mt(30).get("handoff_history") or [{}])[-1].get("ended", ""), mt(30))
check("4 clock: …the background agent is told, once, and the sender is told once that home-peer did not take it",
      len(pushes_to("team-back", "a30")) == 1 and len(pushes_to("home-send", "a30")) == 1 and "did not take it" in pushes_to("home-send", "a30")[0][1] and "team-back" in pushes_to("home-send", "a30")[0][1], pushes())
check("4 clock: …and a pass again, with nothing new due, tells no one again", tick(ho(30)["delivered_at"] + 5 * MIN, 30) == [] and len(pushes_to("home-send", "a30")) == 1, pushes())
item(31); hand(31, "home-peer"); drain(); d31 = ho(31)["delivered_at"]
cli_row("home-peer", "busy", d31 + 5)
check("4 turn end: a recipient still in its turn (busy) is not marked not taken", tick(d31 + 3 * MIN, 31) == [], ho(31))
cli_row("home-peer", "idle", d31 - 30)
check("4 turn end: …nor one whose idle stamp is from before the delivery", tick(d31 + 3 * MIN, 31) == [], ho(31))
cli_row("home-peer", "idle", d31 + 5)
check("4 turn end: …nor one that turned idle a moment ago (its queued message starts the next turn at once)", tick(d31 + 10, 31) == [], ho(31))
done = tick(d31 + 3 * MIN, 31); drain()
check("4 turn end: a recipient whose turn ended after the delivery with no write to the item is marked not taken at once and the background agent is asked (3 minutes in)",
      done == ["a31"] and ho(31).get("to") == "team-back" and "turn ended" in ho(31).get("reason", ""), (done, ho(31)))
item(37); hand(37, "home-peer"); drain(); d_h = ho(37)["delivered_at"]
cli_row("home-peer", "shell", d_h + 5)
done = tick(d_h + 3 * MIN, 37); drain()
check("4 turn end: a recipient whose turn ended with a background Bash task still running (the registry's `shell`) counts as ended: marked not taken, the background agent asked",
      done == ["a37"] and ho(37).get("to") == "team-back" and "turn ended" in ho(37).get("reason", ""), (done, ho(37)))
(T / f"cli/{os.getpid()}-home-peer.json").unlink()
# a front agent is never clocked; a builder's item is, whatever rank it still stores (ranks are retired: a builder takes what it is handed)
item(32); upd(32, "home-send", needs=["team-back"], next="team-back: do the thing"); drain()
m32 = rd(32); m32["metadata"]["rank"] = 1; (T / "store/a/32.json").write_text(json.dumps(m32))
tick(time.time() + 86400, 32)
check("4 clock: an item that still stores a rank for its builder is clocked like any other hand-off (a day on, the builder did not take it: it is reminded, the first step for a background agent)", bool(ho(32).get("reminded_at") or ho(32).get("cold")), ho(32))
item(33); hand(33, "home-front"); drain()
check("4 exempt: a hand-off to a front agent is neither pushed nor clocked (no item notice wakes one)", ho(33).get("delivered_at") is None and not pushes_to("home-front", "a33")
      and tick(time.time() + 86400, 33) == [], (ho(33), pushes()))

# ================================================================ 5. section 5, in order
# 5a: the project has no background agent with a pane (gamma: its builder's pane is gone), cold call hands to a live session
item(40, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(40, "home-peer"); drain(); d40 = ho(40)["delivered_at"]
cold({"action": "hand_to", "to": "home-gamma-docs", "reason": "it is the project's own work"})
done = tick(d40 + 11 * MIN, 40); drain()
check("5 cold: no background agent with a pane (gamma's is gone): the cold call is asked, with the item and its page's Current state", done == ["a40"] and len(COLD_MSGS) == 1
      and '"item": "a40"' in COLD_MSGS[0] and "STATE-OF-GAMMA" in COLD_MSGS[0] and "home-gamma-docs [background] live" in COLD_MSGS[0] and "home-gamma-bg [background] no pane" in COLD_MSGS[0]
      and "home-gamma-front" not in COLD_MSGS[0].split("Sessions it may be handed to")[1], COLD_MSGS[:1])      # a front agent is not offered
check("5 cold: …hand to <session>: the item is handed to it, written as the author cold-call, the record carries the way walked and the call's answer",
      mt(40).get("mover") == "home-gamma-docs" and mt(40).get("needs") == ["home-gamma-docs"] and rd(40).get("written_by") == "cold-call" and ho(40).get("from") == "cold-call" and "home-peer" in (ho(40).get("tried") or []) and (ho(40).get("cold") or {}).get("state") == "done", (mt(40), rd(40).get("written_by"), ho(40)))
item(41, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(41, "home-peer"); drain(); d41 = ho(41)["delivered_at"]
before41 = rd(41)["description"]
cold({"action": "close", "outcome": "done", "reason": "the page says the sample task is in progress and the work is finished", "outcome_text": "- The thing is done and in use\n- It lives here"})
tick(d41 + 11 * MIN, 41); drain()
check("5 cold: …close with <outcome>: the item is closed with its outcome, reason and outcome text, as cold-call, and its description stays", rd(41)["status"] == "completed" and mt(41).get("outcome") == "done" and rd(41).get("written_by") == "cold-call"
      and "in use" in mt(41).get("outcome_text", "") and rd(41)["description"] == before41, (rd(41)["status"], mt(41)))
# a cold call's close with a reason over the 120-character limit still closes the item, the reason cut to the limit by the server
item(88, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(88, "home-peer"); drain(); d_j = ho(88)["delivered_at"]
cold({"action": "close", "outcome": "done", "reason": "the page says the work is finished and in use, " + "and the vendor confirmed it " * 8, "description": "- The thing is done and in use\n- It lives here"})
tick(d_j + 11 * MIN, 88); drain()
check("5 cold: a close whose reason is over 120 characters still closes the item, the reason cut to 120 with an ellipsis", rd(88)["status"] == "completed" and rd(88).get("written_by") == "cold-call"
      and mt(88).get("outcome") == "done" and mt(88).get("reason", "").startswith("the page says the work is finished and in use") and 100 < len(mt(88).get("reason", "")) <= 120 and mt(88)["reason"].endswith(" …"), (rd(88)["status"], mt(88).get("reason")))
# …and a reason of ids: 96 characters as the model wrote it, 156 once _update shows the store id in its board form, so the cut comes after the expansion
(T / "store/g").mkdir(exist_ok=True); item(66, letter="g")
item(75, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(75, "home-peer"); drain(); d_k = ho(75)["delivered_at"]
ID_REASON = "see g66 " * 12
cold({"action": "close", "outcome": "done", "reason": ID_REASON, "description": "- The thing is done and in use\n- It lives here"})
tick(d_k + 11 * MIN, 75); drain()
check("5 cold: a reason full of ids (96 characters raw, over 120 once shown) still closes the item, the reason within 120 and carrying the id", rd(75)["status"] == "completed" and len(ID_REASON) < 120
      and "board#66" in mt(75).get("reason", "") and "g66" not in mt(75).get("reason", "").replace("board#66", "") and len(mt(75).get("reason", "")) <= 120, (rd(75)["status"], mt(75).get("reason")))
(T / "store/g/66.json").unlink()
item(42, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(42, "home-peer"); drain(); d42 = ho(42)["delivered_at"]
cold({"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "wait", "line": "Hold it a week.", "recommended": False}]})
tick(d42 + 11 * MIN, 42); drain()
check("5 cold: …ask Oliver: a decision with its ask and its options, as cold-call, the item his", "decision" in mt(42).get("needs", []) and mt(42).get("ask") == ASK and len(mt(42).get("options") or []) == 2 and rd(42).get("written_by") == "cold-call"
      and ho(42).get("to") == OWN and ho(42).get("no_clock") is True, (mt(42), ho(42)))
# an item stored in state doing (a session at work: needs names a session) whose cold call asks Oliver reaches him with needs decision and the ask (no stored state: the cold call no longer writes your-call), not back to its sender
item(84, project="projects/gamma", owner=U["home-gamma-front"], needs=["home-send"], mover="home-send", state="doing", expected_by=time.strftime("%Y-%m-%d 23:59", time.gmtime(now0 + ZONE_OFFSET + 3600)))
hand(84, "home-peer"); drain(); d_l = ho(84)["delivered_at"]
cold({"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "wait", "line": "Hold it a week.", "recommended": False}]})
tick(d_l + 11 * MIN, 84); drain()
check("5 cold: …ask Oliver on an item in state doing: needs decision and the ask with no stored state, as cold-call, the item his and not returned to its sender",
      mt(84).get("needs") == ["decision"] and "state" not in mt(84) and mt(84).get("ask") == ASK and rd(84).get("written_by") == "cold-call"
      and ho(84).get("to") == OWN and ho(84).get("via") != "return" and (ho(84).get("cold") or {}).get("state") == "done" and "expected_by" not in mt(84), (mt(84), ho(84)))
# …and a hand to a front agent from doing: no session is in needs for it (a front agent is the mover only), so doing cannot stand: the item reads as derived, the front agent is its mover
item(69, project="projects/gamma", owner=U["home-gamma-front"], needs=["home-send"], mover="home-send", state="doing", expected_by=time.strftime("%Y-%m-%d 23:59", time.gmtime(now0 + ZONE_OFFSET + 3600)))
hand(69, "home-peer"); drain(); d_m = ho(69)["delivered_at"]
cold({"action": "hand_to", "to": "home-gamma-docs", "reason": "it is the project's own work"})
tick(d_m + 11 * MIN, 69); drain()
check("5 cold: …hand to a background agent on an item in state doing: handed to it, not returned to the sender",
      mt(69).get("mover") == "home-gamma-docs" and ho(69).get("from") == "cold-call" and ho(69).get("via") != "return" and (ho(69).get("cold") or {}).get("state") == "done"
      and rd(69).get("written_by") == "cold-call", (mt(69), ho(69)))
# 5a: a correct close whose description is prose, with a sentence over 120 characters, still closes the item: the server puts it into bullets first
item(72, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(72, "home-peer"); drain(); d_i = ho(72)["delivered_at"]
LONGS = "It lives on the vendor's side and " + "keeps going " * 14 + "until the end. See [the vendor's page](https://example.com/vendor/status?x=1) for the rest."
cold({"action": "close", "outcome": "done", "reason": "the page says the work is finished",
      "description": "1. The thing is done and in use, e.g. the nightly run.\n2) Dr. Kim signed it off.\n" + LONGS + "\n\n- \n...\n* Nothing is left to do."})
tick(d_i + 11 * MIN, 72); drain()
dd = mt(72).get("outcome_text", ""); dl = dd.splitlines()
check("5 cold: a prose close (numbered lines, \"e.g.\", \"Dr.\", a line over 120 characters; the older `description` key) still closes the item, its outcome text written as bullets within the limits, split on lines only",
      rd(72)["status"] == "completed" and rd(72).get("written_by") == "cold-call" and len(dl) == 4 and dl[0] == "- The thing is done and in use, e.g. the nightly run."
      and dl[1] == "- Dr. Kim signed it off." and dl[3] == "- Nothing is left to do" + "." and all(l.startswith("- ") and server._visible_len(l) <= 120 for l in dl)
      and dl[2].endswith(" …") and "[the vendor" not in dl[2] , dd)
check("5 cold: …the validator alone: a marker (-, *, a dot, 1. or 1)) is taken off once, a line of digits and punctuation is dropped, and sentences are not split",
      CC.bullets("* A star\n\u2022 A dot\n- A dash\n3) A paren\n 4. A number\n...\n---\n", 8, 120) == "- A star\n- A dot\n- A dash\n- A paren\n- A number"
      and CC.bullets("Dr. Who said e.g. this. And that.", 8, 120) == "- Dr. Who said e.g. this. And that.", CC.bullets("* A star\n\u2022 A dot", 8, 120))
check("5 cold: …more lines than max_lines: the last kept line says how many more (and counts within max_lines)",
      CC.bullets("\n".join(f"line {i}" for i in range(1, 12)), 8, 120).splitlines() == [f"- line {i}" for i in range(1, 8)] + ["- …and 4 more"]
      and len(CC.bullets("\n".join(f"line {i}" for i in range(1, 9)), 8, 120).splitlines()) == 8 and "more" not in CC.bullets("\n".join(f"line {i}" for i in range(1, 9)), 8, 120))
# …and a close the gate still refuses is no answer: the item is left as it was (not half written), and the ladder goes on
item(88, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(88, "home-peer"); drain(); d_j = ho(88)["delivered_at"]
before_a = rd(88)["description"]
_gate_was = server._gate_description
def _gate_refusing(desc, field="description"):
    if field == "outcome_text" and "Resolved:" in desc:
        raise server.ToolError("Refused: outcome_text is refused (test)")
    return _gate_was(desc, field)
server._gate_description = _gate_refusing
cold({"action": "close", "outcome": "done", "reason": "finished", "outcome_text": "Resolved: the thing is done."})
tick(d_j + 11 * MIN, 88); drain()
server._gate_description = _gate_was
check("5 cold: a close whose outcome text the gate refuses leaves the item open and unchanged, the record says why, the ladder goes on",
      rd(88)["status"] == "open" and rd(88)["description"] == before_a and "outcome" not in mt(88) and (ho(88).get("cold") or {}).get("state") == "failed"
      and "refused" in json.dumps(ho(88)) and ho(88).get("to") == "home-send", (rd(88)["status"], rd(88)["description"], ho(88)))
# a write of the ladder's own that the server refuses (the answer was valid, `_update` still said no: the board item's ask on an item in state doing) is tried once more; refused again the item is
# stuck with the refusal text (the brief lists it), not returned to its sender; the refusals are in the journal
_real_update = server._update
LADDER_WRITES = []; LADDER_KW = []; REFUSE = {"left": 0, "between": None, "boom": False}
def _ladder_update(gid, *a, **kw):
    if kw.get("sender") == H.COLD:
        LADDER_WRITES.append(gid); LADDER_KW.append(dict(kw))
        if REFUSE["boom"]:
            raise RuntimeError("the store broke (test)")                  # an error that is no refusal
        if REFUSE["left"] > 0:
            REFUSE["left"] -= 1
            if REFUSE["between"]: REFUSE["between"]()                     # something else writes the item after this attempt read it and before the next one does
            raise server.ToolError("Refused: the item is in state doing and needs a session in needs (test)")
    return _real_update(gid, *a, **kw)
def stored_edit(i, fn):
    """Edit the stored metadata of item a<i> on disk, as another writer would between two attempts."""
    p = T / f"store/a/{i}.json"; d = json.loads(p.read_text()); fn(d["metadata"]); p.write_text(json.dumps(d))
server._update = _ladder_update
item(38, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(38, "home-peer"); drain(); d_n = ho(38)["delivered_at"]; before_b = rd(38)["description"]
cold({"action": "close", "outcome": "done", "reason": "the work is finished", "description": "- The thing is done and in use\n- It lives here"})
REFUSE["left"] = 99; LADDER_WRITES.clear(); journal = io.StringIO()
with contextlib.redirect_stderr(journal):
    tick(d_n + 11 * MIN, 38); drain()
check("5 ladder write: a valid answer whose write the server refuses twice leaves the item open and unchanged with its mover and the fleet's builder asked, with the refusal text; it is not returned to its sender",
      rd(38)["status"] == "open" and rd(38)["description"] == before_b and bool(ho(38).get("recovery_at")) and "refused twice" in ho(38).get("recovery_reason", "") and "state doing" in ho(38).get("recovery_reason", "")
      and (ho(38).get("cold") or {}).get("state") == "failed" and ho(38).get("to") == "home-peer" and ho(38).get("via") != "return" and not pushes_to("home-send", "a38"), (rd(38)["status"], ho(38)))
check("5 ladder write: …the write was tried exactly twice, and both refusals are in the journal with their text",
      LADDER_WRITES == ["a38", "a38"] and "a38 the cold call's close refused (attempt 1 of 2): Refused: the item is in state doing" in journal.getvalue()
      and "attempt 2 of 2" in journal.getvalue(), (LADDER_WRITES, journal.getvalue()[-600:]))
check("5 ladder write: …the fleet's builder got exactly one recovery message with the refusal, the brief lists no stuck line, get says the builder was asked, and the History has the line",
      len(recovery_pushes("a38")) == 1 and "refused twice" in recovery_pushes("a38")[0][1] and "nobody can take" not in server._handoff_brief()
      and "the fleet's builder was asked" in server.stackshot_get("a38") and any("was asked to recover it" in (e.get("text") or "") for e in ((mt(38).get("stall") or {}).get("log") or [])), (recovery_pushes("a38"), server.stackshot_get("a38")[-600:], (mt(38).get("stall") or {}).get("log")))
# a refusal that does not come again (a write that lost a race) is tried once more and lands: no recovery asked, nothing returned
item(39, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(39, "home-peer"); drain(); d_o = ho(39)["delivered_at"]
cold({"action": "close", "outcome": "done", "reason": "the work is finished", "description": "- The thing is done and in use\n- It lives here"})
REFUSE["left"] = 1; LADDER_WRITES.clear(); journal = io.StringIO()
with contextlib.redirect_stderr(journal):
    tick(d_o + 11 * MIN, 39); drain()
check("5 ladder write: a refusal that does not come again is retried once and the write lands: closed as cold-call, no recovery asked, the first refusal alone in the journal",
      rd(39)["status"] == "completed" and rd(39).get("written_by") == "cold-call" and not ho(39).get("recovery_at") and ((mt(39).get("handoff_history") or [{}])[-1].get("cold") or {}).get("state") == "done"
      and LADDER_WRITES == ["a39", "a39"] and "attempt 1 of 2" in journal.getvalue() and "attempt 2 of 2" not in journal.getvalue(), (rd(39)["status"], ho(39), LADDER_WRITES, journal.getvalue()[-300:]))
# the retry reads the item again: ask Oliver on the shape (state doing, a stored mover); the first attempt is refused, and before the second the stored mover is gone: the second
# write carries no clear_mover (the first did), so it was built from the item as it stood then, and it lands
item(83, project="projects/gamma", owner=U["home-gamma-front"], needs=["home-send"], mover="home-send", state="doing", expected_by=time.strftime("%Y-%m-%d 23:59", time.gmtime(now0 + ZONE_OFFSET + 3600)))
hand(83, "home-peer"); drain(); d_p = ho(83)["delivered_at"]
cold({"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "wait", "line": "Hold it a week.", "recommended": False}]})
REFUSE["left"] = 1; REFUSE["between"] = lambda: stored_edit(83, lambda m: m.pop("mover", None)); LADDER_WRITES.clear(); LADDER_KW.clear(); journal = io.StringIO()
with contextlib.redirect_stderr(journal):
    tick(d_p + 11 * MIN, 83); drain()
REFUSE["between"] = None
check("5 ladder write: ask Oliver (the shape), first attempt refused: the second is built from the item as it stands then (the first carried clear_mover, the second, the mover being gone, does not) and lands",
      len(LADDER_KW) == 2 and LADDER_KW[0].get("clear_mover") is True and "clear_mover" not in LADDER_KW[1] and LADDER_KW[0].get("ask") == ASK and LADDER_KW[1].get("ask") == ASK
      and mt(83).get("needs") == ["decision"] and "state" not in mt(83) and rd(83).get("written_by") == "cold-call" and not ho(83).get("recovery_at") and ho(83).get("to") == OWN
      and "attempt 1 of 2" in journal.getvalue(), (LADDER_KW, mt(83), ho(83), journal.getvalue()[-300:]))
# hand to a front agent from state doing: the first attempt is refused, and before the second the stored state is gone: the second write does not clear it (the first did)
item(74, project="projects/gamma", owner=U["home-gamma-front"], needs=["home-send"], mover="home-send", state="doing", expected_by=time.strftime("%Y-%m-%d 23:59", time.gmtime(now0 + ZONE_OFFSET + 3600)))
hand(74, "home-peer"); drain(); d_q = ho(74)["delivered_at"]
cold({"action": "hand_to", "to": "home-gamma-docs", "reason": "it is the project's own work"})
REFUSE["left"] = 1; REFUSE["between"] = lambda: stored_edit(74, lambda m: (m.pop("state", None), m.pop("expected_by", None))); LADDER_WRITES.clear(); LADDER_KW.clear(); journal = io.StringIO()
with contextlib.redirect_stderr(journal):
    tick(d_q + 11 * MIN, 74); drain()
REFUSE["between"] = None
check("5 ladder write: hand to <session> from state doing, first attempt refused: the second is built from the item as it stands then (the stored state being gone) and lands: the item is the background agent's (never a front agent's)",
      len(LADDER_KW) == 2 and LADDER_KW[0].get("mover") == "home-gamma-docs" and LADDER_KW[1].get("mover") == "home-gamma-docs"
      and mt(74).get("mover") == "home-gamma-docs" and rd(74).get("written_by") == "cold-call" and not ho(74).get("recovery_at") and (ho(74).get("cold") or {}).get("state") == "done"
      and "attempt 1 of 2" in journal.getvalue(), (LADDER_KW, mt(74), ho(74), journal.getvalue()[-300:]))
# an error inside the write that is no refusal (a bug, a store failure) does not send the item back to its sender: the fleet's builder is asked with the exception text, once tried, the journal has it
item(49, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(49, "home-peer"); drain(); d_v = ho(49)["delivered_at"]; before_c = rd(49)["description"]
cold({"action": "close", "outcome": "done", "reason": "the work is finished", "description": "- The thing is done and in use\n- It lives here"})
REFUSE["boom"] = True; LADDER_WRITES.clear(); journal = io.StringIO(); clear_pushes()
with contextlib.redirect_stderr(journal):
    tick(d_v + 11 * MIN, 49); drain()
REFUSE["boom"] = False
check("5 ladder write: an error inside the write that is no refusal leaves the item open and unchanged with its mover, the fleet's builder asked with the exception text (not returned to its sender), tried once, the journal has it",
      rd(49)["status"] == "open" and rd(49)["description"] == before_c and bool(ho(49).get("recovery_at")) and "failed with an error" in ho(49).get("recovery_reason", "") and "RuntimeError: the store broke (test)" in ho(49).get("recovery_reason", "") and len(recovery_pushes("a49")) == 1
      and ho(49).get("to") == "home-peer" and ho(49).get("via") != "return" and not pushes_to("home-send", "a49") and LADDER_WRITES == ["a49"]
      and "a49 the cold call's close failed on attempt 1 of 2: RuntimeError: the store broke (test)" in journal.getvalue(), (rd(49)["status"], ho(49), LADDER_WRITES, journal.getvalue()[-300:]))
server._update = _real_update
# 5b: a bad answer falls on to the sender, then (sender gone) the fleet's builder is asked
item(43, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(43, "home-peer"); drain(); d43 = ho(43)["delivered_at"]
cold({"action": "hand_to", "to": "home-nobody", "reason": "x"})
tick(d43 + 11 * MIN, 43); drain()
check("5 cold: an answer that names no live session is not written; the item goes on to its sender (the last fallback), the record says why", ho(43).get("to") == "home-send" and ho(43).get("via") == "return"
      and (ho(43).get("cold") or {}).get("state") == "failed" and "not a live session" in json.dumps(ho(43)), ho(43))
item(44, project="projects/gamma", owner=U["home-gamma-front"], needs=[])
hand(44, "home-peer", sender="home-send-dead"); drain(); d44 = ho(44)["delivered_at"]
cold("no json at all here", status="ok")
tick(d44 + 11 * MIN, 44); drain()
check("5 recovery: the cold call gave nothing and the sender's pane is gone: nobody can take it: the fleet's builder is asked once, with the reason; the item stays with its mover",
      bool(ho(44).get("recovery_at")) and "home-peer did not take it in 10 min" in ho(44).get("recovery_reason", "") and "no usable answer" in ho(44).get("recovery_reason", "") and "home-send-dead" in ho(44).get("recovery_reason", "")
      and ho(44).get("to") == "home-peer" and len(recovery_pushes("a44")) == 1 and recovery_pushes("a44")[0][1].startswith("[stackshot] fleet recovery: "), (ho(44), recovery_pushes("a44")))
check("5 recovery: …the item is not on the owner's list: no decision in needs, no ask, no options, no idle raise", "decision" not in (mt(44).get("needs") or []) and not mt(44).get("ask") and not mt(44).get("options") and not (mt(44).get("idle") or {}).get("raised"), mt(44))
check("5 recovery: …a record that asked once is left alone by the next passes: nothing moves and no second message", tick(d44 + 40 * MIN, 44) == [] and len(recovery_pushes("a44")) == 1, (ho(44), recovery_pushes("a44")))
check("5 recovery: …and the brief has no stuck line for it", all("stuck" not in ln for ln in H.brief_lines({"a44": rd(44)}, time.time())), H.brief_lines({"a44": rd(44)}, time.time()))
upd(44, "home-peer", next="home-peer: back at it")
check("5 recovery: …its mover's note ends the request (the session is alive) but does not take the item: no work started", not ho(44).get("recovery_at") and not ho(44).get("taken_at"), ho(44))
start(44, "home-peer")
check("5 recovery: …its mover starting work takes it: taken_at is set and the request is cleared, so a later episode may ask again", ho(44).get("taken_at") and not ho(44).get("recovery_at") and not ho(44).get("recovery_reason")
      and "a44" not in server._handoff_brief(), ho(44))
# 5c: never the owner, a script or the server as the sender; cold off and no agent: the fleet's builder is asked
set_cfg(cold_call=False)
item(45, project="projects/beta", owner=U["home-beta-front"], needs=[])
hand(45, "home-peer", sender="home-send"); drain(); d45 = ho(45)["delivered_at"]
tick(d45 + 11 * MIN, 45); drain()
check("5 return: the project has no background agent and the cold call is off: the item goes back to its sender (the last fallback)", ho(45).get("to") == "home-send" and ho(45).get("via") == "return" and mt(45)["needs"][0] == "home-send", (ho(45), mt(45)))
d45b = ho(45).get("delivered_at"); check("5 return: …told to the sender as an item that came back", isinstance(d45b, float) and len(pushes_to("home-send", "a45")) == 1 and "came to you" in pushes_to("home-send", "a45")[0][1], pushes())
tick(d45b + 11 * MIN, 45); drain()
check("5 recovery: …and when the sender does not take it either, the project's -main agent (beta lists no background agent) is asked once (no ping-pong)", bool(ho(45).get("recovery_at")) and ho(45).get("to") == "home-send" and len(main_recovery_pushes("a45")) == 1, (ho(45), main_recovery_pushes("a45")))
item(47, project="projects/beta", owner=U["home-beta-front"], needs=["decision"], ask=ASK, next=f"{OWN}: decide")
hand(47, "home-peer", sender="home-beta-front", clear_needs=True); drain()
check("5 return: (setup) a hand-off whose sender is a front agent is recorded", ho(47).get("from") == "home-beta-front", ho(47))
set_cfg()
# 5d: a gone mover of a hand-off record: the background agent, without the sender; with none, the cold call; with none of them, stuck. An item with no record (from before the
# machinery) is only counted in the brief, never moved.
item(50, needs=["home-dead"], next="home-dead: do the thing", handoff=rec("home-dead"))
item(51, project="projects/beta", owner=U["home-beta-front"], needs=["home-dead"], next="home-dead: do the thing", handoff=rec("home-dead"))
item(52, needs=["home-dead"], next="home-dead: do the thing", updated=now0 - 40 * 86400, handoff=rec("home-dead"))
item(55, needs=["home-dead"], next="home-dead: do the thing")
item(56, needs=["home-dead"], next="home-dead: do the thing", rank=1, handoff=rec("home-dead"))     # a leftover stored rank
clear_pushes(); cold({"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "drop", "line": "Drop it.", "recommended": False}]})
done = tick(None, 50, 51, 52, 55, 56); drain()
check("5 gone: an alive item with a hand-off record whose mover's pane is gone goes to the project's builder", "a50" in done and ho(50).get("to") == "team-back" and mt(50)["needs"][0] == "team-back" and "is gone" in ho(50).get("reason", ""), (done, ho(50)))
check("5 gone: …a project with no builder: the cold call (it asks Oliver)", "decision" in mt(51).get("needs", []) and rd(51).get("written_by") == "cold-call", (mt(51), ho(51)))
check("5 gone: …an item last written 40 days ago is left for the migration", ho(52).get("to") == "home-dead" and mt(52)["needs"] == ["home-dead"] and "a52" not in done, mt(52))
check("5 gone: …an item with NO hand-off record (from before the machinery) is not moved, whatever its mover's pane", "handoff" not in mt(55) and mt(55)["needs"] == ["home-dead"] and "a55" not in done, mt(55))
check("5 gone: …an item that still stores a rank is moved like any other when its builder's pane is gone", ho(56).get("to") == "team-back" and "a56" in done, (done, ho(56)))
check("5 gone: …the brief counts the items with no record, as `mover gone: n`, and moves none", re.search(r"mover gone: \d+ item", server._handoff_brief()) and "a55" not in server._handoff_brief(), server._handoff_brief())
set_cfg(cold_call=False)
item(53, project="projects/beta", owner=U["home-beta-front"], needs=["home-dead"], next="home-dead: do the thing", handoff=rec("home-dead"))
tick(None, 53); drain()
check("5 gone: …with no builder and no cold call, the project's -main agent is asked, and the reason says the project lists none", bool(ho(53).get("recovery_at")) and "no builder" in ho(53).get("recovery_reason", "") and "is gone" in ho(53).get("recovery_reason", "") and len(main_recovery_pushes("a53")) == 1, (ho(53), main_recovery_pushes("a53")))
set_cfg()
# the cold call's message and the answer parser, pure
check("5 cold: the answer parser takes the JSON out of prose and a fence, and only the three actions", CC.parse("sure:\n```json\n{\"action\": \"close\", \"outcome\": \"done\"}\n```")["action"] == "close" and CC.parse("{\"action\": \"delete\"}") is None and CC.parse("") is None, None)
check("5 cold: the parser wants exactly one JSON object with a known action: two (an answer and a second thought) are no answer, one with options inside is one",
      CC.parse('{"action": "close", "outcome": "done"} and then {"action": "hand_to", "to": "team-back"}') is None
      and CC.parse('{"action": "ask_owner", "ask": "a", "options": [{"label": "x"}, {"label": "y"}]}')["action"] == "ask_owner" and CC.parse('{"note": 1} {"action": "close"}')["action"] == "close", None)
check("5 cold: validation: a hand-off may not go to the session that just failed or to the original sender (the exclude list), the others pass",
      CC.validate({"action": "hand_to", "to": "home-peer"}, {"home-peer", "team-back"}, exclude=["home-peer"])[0] is None and CC.validate({"action": "hand_to", "to": "HOME-SEND"}, {"home-send", "team-back"}, exclude=["home-send"])[0] is None
      and CC.validate({"action": "hand_to", "to": "team-back"}, {"home-peer", "team-back"}, exclude=["home-peer", "home-send"])[0]["to"] == "team-back", None)
check("5 cold: validation: a session must be on the live list, a close needs outcome, reason and description, an ask two options",
      CC.validate({"action": "hand_to", "to": "TEAM-BACK"}, {"team-back"})[0]["to"] == "team-back" and CC.validate({"action": "hand_to", "to": "x"}, {"team-back"})[0] is None
      and CC.validate({"action": "close", "outcome": "done", "reason": "r"}, set())[0] is None and CC.validate({"action": "close", "outcome": "dropped", "reason": "r", "description": "d"}, set())[0] is not None
      and CC.validate({"action": "close", "outcome": "superseded", "reason": "r", "description": "d"}, set())[0] is None and CC.validate({"action": "ask_owner", "ask": "a", "options": [{}]}, set())[0] is None, None)
argv = server._router.build_argv(CC.RUBRIC)
check("5 cold: the call runs the router's way: a login shell with ANTHROPIC_API_KEY and the other provider variables unset", "ANTHROPIC_API_KEY" in " ".join(argv) and "-u" in argv[3] + " ".join(argv) and "--tools" in argv, argv[:6])

# ================================================================ 6. the pause switch and the batch
item(60); item(61); item(62)
hand(60, "home-peer"); hand(61, "home-peer"); hand(62, "home-peer2"); drain(); clear_pushes()
d6 = max(ho(i)["delivered_at"] for i in (60, 61, 62))
item(54, needs=["home-dead"], next="home-dead: do the thing", handoff=rec("home-dead"))
set_cfg(pause=True)
check("6 pause: while the switch is on, the clock and the gone-mover pass do nothing, though three hand-offs and a gone mover are due", tick(d6 + 20 * MIN, 54, 60, 61, 62) == [] and ho(60).get("to") == "home-peer" and ho(62).get("to") == "home-peer2" and ho(54).get("to") == "home-dead", pushes())
check("6 pause: …and the brief says how many it holds", "paused" in server._handoff_brief() and "would fire" in server._handoff_brief(), server._handoff_brief())
set_cfg(pause=False)
done = tick(d6 + 20 * MIN, 54, 60, 61, 62); drain()
check("6 pause: turned off, the items that would have fired fire in one pass", set(done) == {"a54", "a60", "a61", "a62"} and ho(54).get("to") == "team-back" and ho(60).get("to") == "team-back" and ho(61).get("to") == "team-back" and ho(62).get("to") == "team-back", (done, ho(60), ho(62)))
to_back = [p for p in pushes() if p[0] == U["team-back"]]
check("6 batch: …one message to the background agent listing its items, not one per item", len(to_back) == 1 and all(x in to_back[0][1] for x in ("a54", "a60", "a61", "a62")), to_back)
to_send = [p for p in pushes() if p[0] == U["home-send"]]
check("6 batch: …and one to the sender listing its three", len(to_send) == 1 and all(x in to_send[0][1] for x in ("a60", "a61", "a62")), to_send)

# ================================================================ 7. the send-time guard
item(70)
refused("7 guard: a hand-off to a background agent whose pane is not running is refused, the project's agent with a pane named", lambda: hand(70, "home-idle"), "Refused:", "home-idle", "no pane of it is in the heartbeat", "team-back", "needs=")
refused("7 guard: …a session whose pane has been gone for hours is refused too (with the guards off, the way the message tool refuses it)", lambda: (set_cfg(guards=False), hand(70, "home-dead"))[1], "home-dead", "pane has been gone", "team-back")
set_cfg()
check("7 guard: …nothing was written", "handoff" not in mt(70) and mt(70).get("needs") is None, mt(70))
item(71, project="projects/gamma", owner=U["home-gamma-front"], needs=[], mover="home-gamma-front")
_sess = (T / "fleet/a/sessions.json").read_text()
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if n in GONE | {"home-gamma-docs"} else {})} for n, u in U.items() if n != "home-idle"}))      # (gamma's second background agent is gone for this check)
refused("7 guard: …a project with no live background agent says so", lambda: hand(71, "home-gamma-bg"), "home-gamma-bg", "no background agent with a pane either", "needs=decision")
(T / "fleet/a/sessions.json").write_text(_sess)
refused("7 guard: …a create that hands to such a session is refused too", lambda: server._create(subject="[home] made for an idle one", description=DESC, project="projects/alpha", owner="home-front", next="home-idle: do the thing", needs=["home-idle"]), "home-idle", "team-back")
out = server._create(subject="[home] made for the builder", description=DESC, project="projects/alpha", owner="home-front", next="team-back: do the thing", needs=["team-back"]); drain()
cm = re.search(r"created ([a-z])(\d+)", str(out)); cl, cn = cm.group(1), int(cm.group(2))
cr = (json.loads((T / f"store/{cl}/{cn}.json").read_text())["metadata"].get("handoff") or {})
check("7 guard: …and one that hands to a live background agent is a hand-off from its creator, told once", cr.get("to") == "team-back" and cr.get("from") == "home-front" and isinstance(cr.get("delivered_at"), float)
      and len(pushes_to("team-back", f"{cl}{cn}")) == 1, (out, cr, pushes()))
check("7 guard: the owner and a live session pass", hand(70, "home-peer") and ho(70).get("to") == "home-peer", ho(70))

# ================================================================ 8. display
item(80); hand(80, "home-peer"); drain()
txt = got(80)
check("8 display: get shows handed to X, not yet taken (since HH:MM) in the instance's timezone", f"handoff: handed to home-peer, not yet taken (since {hhmm(ho(80)['at'])})" in txt and "UTC" not in txt, txt)
upd(80, "home-peer", next="home-peer: queued")
check("8 display: …a note leaves it not yet taken", "not yet taken" in got(80), got(80))
start(80, "home-peer")
check("8 display: …taken HH:MM once the new mover started work", f"handoff: handed to home-peer, taken {hhmm(ho(80)['taken_at'])}" in got(80), got(80))
item(81); hand(81, "home-peer"); drain(); set_cfg(cold_call=False)
done = tick(ho(81)["delivered_at"] + 11 * MIN, 81); drain()
check("8 display: a hand-off that went to the background agent says why", "handed to team-back (home-peer did not take it in 10 min), not yet taken" in got(81), got(81))
tick(ho(81)["delivered_at"] + 11 * MIN, 81); drain()      # team-back does not take it: a background agent is reminded once before the ladder goes on
check("8 display: …a background agent that did not take it is reminded first, and the item says so", "team-back did not take it in 10 min: its mover was reminded" in got(81) and "reminded_at" in ho(81), got(81))
tick(ho(81)["delivered_at"] + 11 * MIN, 81); drain()      # still not taken after the reminder: only the builder is tried (not home-docs, the page's other background agent); no cold call: back to the sender
check("8 display: …and returned to the sender when the agent did not take it either, with the reason", "handoff: returned to home-send: team-back did not take it in 10 min after a reminder, not yet taken" in got(81), got(81))
set_cfg()
b = server.stackshot_brief()
check("8 display: the brief shows the not-yet-taken ones in one short line, not the owner's and not stuck ones", re.search(r"handed over, not yet taken: .*a80", b) is None and "handed over, not yet taken:" in b and "a1 → home-peer" in b, b[:1500])
check("8 display: …in the instance's timezone, never UTC", "UTC" not in server._handoff_brief(), server._handoff_brief())

# ================================================================ 9. the switch
set_cfg(handoff=False)
item(90); hand(90, "home-peer"); drain()
check("9 switch: [model] handoff = false: no record is written", "handoff" not in mt(90), mt(90))
check("9 switch: …no clock runs, no gone mover is looked for", server._handoff_tick(now=time.time() + 86400) == [], None)
check("9 switch: …and get and the brief say nothing of hand-offs", "handoff:" not in got(80) and server._handoff_brief() == "", got(80))
set_cfg(handoff=False, guards=False); item(91); hand(91, "home-idle"); check("9 switch: …and no hand-off is refused for its pane", mt(91).get("mover") == "home-idle" and "handoff" not in mt(91), mt(91))
set_cfg()

# ================================================================ 10. the router's side of the path
server._cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
check("10 router: the background agent a hand-off falls to is the router's builder for the project (alpha: team-back, whose mandate says builds), and the order has it first",
      router_live.builder("projects/alpha") == "team-back" and server._handoff_background("projects/alpha")[0] == "team-back" and server._handoff_background("projects/alpha")[1:] == ["home-docs", "home-idle"], server._handoff_background("projects/alpha"))
check("10 router: …a project with no background agent has none (beta)", server._handoff_background("projects/beta") == [], None)
check("10 router: …the fallback is the builder alone, not every background agent on the page (alpha: team-back only; gamma: its builder, whose pane is gone; beta: none)",
      server._handoff_builder("projects/alpha") == ["team-back"] and server._handoff_builder("projects/gamma") == ["home-gamma-bg"] and server._handoff_builder("projects/beta") == [], None)
# pure: a plan is a function of the items and the env
env = H.Env(now=700.0, derive=lambda it: model.derive(it, 700.0), minutes=10.0, background=lambda p: ["b"], pane=lambda w: "", exempt=lambda it, w: False)
pitem = {"status": "open", "metadata": {"owner": "o", "needs": ["x"], "project": "p", "handoff": {"to": "x", "from": "s", "at": 100.0, "delivered_at": 200.0, "taken_at": None}}}
check("10 pure: plan() says move to the agent once the minutes are up, and nothing before; it changes nothing", H.plan({"g1": pitem}, env) == [] and H.plan({"g1": pitem}, H.Env(**{**env.__dict__, "now": 200.0 + 601}))[0].to == "b"
      and pitem["metadata"]["handoff"].get("taken_at") is None, None)

# ================================================================ 11. the review round
# 11.1 the cold call takes minutes: its answer is checked again under the lock, and dropped quietly when the item has moved on
ANS = {"action": "hand_to", "to": "home-gamma-front", "reason": "its own work"}
def cold_during(answer, during):
    def run(msg):
        COLD_MSGS.append(msg); during()
        return {"status": "ok", "text": json.dumps(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    server._COLD_RUNNER = run
def gamma(i): item(i, project="projects/gamma", owner=U["home-gamma-front"], needs=[]); hand(i, "home-peer"); drain(); return ho(i)["delivered_at"]
d_e = gamma(100)
cold_during(ANS, lambda: start(100, "home-peer"))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    tick(d_e + 11 * MIN, 100); drain()
check("11 cold race: its mover took the item while the call ran: the answer is dropped, nothing is written by cold-call, a log line says so",
      rd(100).get("written_by") == "home-peer" and mt(100).get("mover") == "home-peer" and mt(100).get("needs") in (None, []) and ho(100).get("taken_at") and "answer was dropped" in err.getvalue()
      and "took it meanwhile" in err.getvalue(), (mt(100), err.getvalue()[-300:]))
d_f = gamma(101)
cold_during(ANS, lambda: upd(101, "home-send", mover="home-peer2", next="home-peer2: do it", wake=FUT))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    tick(d_f + 11 * MIN, 101); drain()
check("11 cold race: …handed to someone else meanwhile (a new record): dropped too", rd(101).get("written_by") == "home-send" and ho(101).get("to") == "home-peer2" and mt(101).get("mover") == "home-peer2"
      and "no longer the one" in err.getvalue(), (ho(101), err.getvalue()[-300:]))
d_g = gamma(16)
cold_during(ANS, lambda: server._update("a16", status="completed", outcome="done", reason="finished meanwhile", description="- The thing is done\n- It lives here", sender="home-peer"))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    tick(d_g + 11 * MIN, 16); drain()
check("11 cold race: …closed meanwhile: dropped, the close stands", rd(16)["status"] == "completed" and rd(16).get("written_by") == "home-peer" and "no longer open" in err.getvalue(), (rd(16)["status"], err.getvalue()[-300:]))

# 11.2 one cold call at a time board-wide, one started per pass; the thread list is pruned
gate = threading.Event()
def blocking(msg):
    COLD_MSGS.append(msg); gate.wait(30)
    return {"status": "ok", "text": json.dumps({"action": "ask_owner", "ask": ASK, "options": [{"label": "ship", "line": "Ship it now.", "recommended": True}, {"label": "wait", "line": "Hold it.", "recommended": False}]}),
            "duration_s": 0.1, "usage": {}, "note": "stub"}
server._COLD_RUNNER = blocking
dd = max(gamma(i) for i in (110, 111, 112)); n0 = len(COLD_MSGS)
done = tick(dd + 11 * MIN, 110, 111, 112)
for _ in range(100):
    if len(COLD_MSGS) > n0: break
    time.sleep(0.05)
check("11 cold: a pass with three due starts one cold call, the other two wait for the next tick, untouched", len(done) == 1 and len(COLD_MSGS) == n0 + 1 and sum(1 for i in (110, 111, 112) if ho(i).get("cold")) == 1, (done, [ho(i).get("cold") for i in (110, 111, 112)]))
done2 = tick(dd + 11 * MIN, 110, 111, 112); time.sleep(0.3)
check("11 cold: …none is started while one runs", done2 == [] and len(COLD_MSGS) == n0 + 1, (done2, len(COLD_MSGS) - n0))
gate.set()
first_calls = list(server._HO_COLD_THREADS)
for t in first_calls: t.join(30)
done3 = tick(dd + 11 * MIN, 110, 111, 112)
for _ in range(100):
    if len(COLD_MSGS) > n0 + 1: break
    time.sleep(0.05)
for t in list(server._HO_COLD_THREADS): t.join(30)      # the second call (a stub that returns at once) is over too, so the list is read at rest, not while it runs
check("11 cold: …the next tick starts the next one, and the finished thread is pruned from the list (the first call's thread is gone, one in it, not two)",
      len(done3) == 1 and len(COLD_MSGS) == n0 + 2 and len(server._HO_COLD_THREADS) == 1 and not any(t in server._HO_COLD_THREADS for t in first_calls), (done3, len(server._HO_COLD_THREADS)))
drain(); tick(dd + 11 * MIN, 110, 111, 112); drain()
check("11 cold: …and the third after it: all three were asked, one per tick", len(COLD_MSGS) == n0 + 3 and all("decision" in mt(i).get("needs", []) for i in (110, 111, 112)), [mt(i).get("needs") for i in (110, 111, 112)])
server._COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}

# 11.3 nobody is told twice in one write
item(64, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); clear_pushes()   # the record follows the mover: an item with a record to home-peer has home-peer as its mover
telling.HO_STATE.told = set()
telling.pilot_relay("projects/nowhere", "a64", rd(64), "changed", "home-send", "home-peer")
for _ in range(100):
    if [x for x in pushes() if x[0] == "home-peer"]: break
    time.sleep(0.05)
time.sleep(0.3)
check("11 told: a pilot relay's push to a session is in the write's told-set (its hand-off notice would not double it), and its outcome delivers the hand-off to that session",
      ("a64", server._session_id("home-peer")) in telling.HO_STATE.told and len([x for x in pushes() if x[0] == "home-peer" and "a64" in x[1]]) == 1 and isinstance(ho(64).get("delivered_at"), float), (telling.HO_STATE.told, pushes(), ho(64)))
telling.HO_STATE.told = set(); telling.writer_charge("projects/alpha", "a64", "home-send", "home-stew", "created", False)
check("11 told: …and so is a writer charge's (the writer hears the write in its reply)", ("a64", server._session_id("home-send")) in telling.HO_STATE.told, telling.HO_STATE.told)

# 11.4 writes that are no session's: Oliver's board answer, a script, the server's own save
item(17, needs=["decision"], ask=ASK, next=f"{OWN}: decide")
it_ag = rd(17); it_ag["gid"] = "a17"; it_ag["metadata"].pop("needs"); it_ag["metadata"]["mover"] = "home-peer"; it_ag["metadata"]["next"] = "home-peer: carry it out"; it_ag.pop("gid")
writes.save("a17", it_ag, note="answered on the board", author=(server.OWNER, "board"))
check("11 no record: Oliver's board answer (author) creates no hand-off record, whoever the answer makes the mover", "handoff" not in mt(17) and not pushes_to("home-peer", "a17"), (mt(17), pushes()))
item(18); it_ah = rd(18); it_ah["metadata"]["mover"] = "home-peer"; it_ah["metadata"]["next"] = "home-peer: do the thing"
writes.save("a18", it_ah, writer="home-send via a script on testbox")
check("11 no record: a script's write (\"<sender> via a script on <machine>\": cap-words, state_from_fields --apply) records no hand-off and pushes nothing", "handoff" not in mt(18) and not pushes_to("home-peer", "a18"), (mt(18), pushes()))
item(24); it_ai = rd(24); it_ai["metadata"]["mover"] = "home-peer"; it_ai["metadata"]["next"] = "home-peer: do the thing"
writes.save("a24", it_ai)
check("11 follow: the server's own save (no writer: a wake, an idle pass) that changes the mover records the hand-off, from the server, not delivered (no notice went out: the notice that does marks it); it pushes nothing itself",
      (mt(24).get("handoff") or {}).get("to") == "home-peer" and (mt(24).get("handoff") or {}).get("from") == "stackshot" and not (mt(24).get("handoff") or {}).get("delivered_at") and not pushes_to("home-peer", "a24"), (mt(24), pushes()))
refusal_ok = True
try:
    gates.gate_handoff("a18", rd(18), {**rd(18), "metadata": {**mt(18), "mover": "home-dead"}}, "x via a script on testbox")
except Exception:
    refusal_ok = False
check("11 no record: …and a script's write is not refused by the send-time guard", refusal_ok, None)

# 11.5 a needs-based hand-off to a remote background agent: its only notice is tell_needed's "now needs you" line; the puller's ack of that line delivers the hand-off
item(25); inbox("team-back"); upd(25, "home-send", needs=["team-back"], next="team-back: do the thing"); drain(); inbox()
check("11 ack: (setup) a needs-based hand-off whose line waits in the inbox is queued", ho(25).get("to") == "team-back" and ho(25).get("queued", "").startswith("inbox") and ho(25).get("delivered_at") is None, ho(25))
line_ao = [x for x in pushes_to("team-back", "a25")][-1][1]
check("11 ack: …and the line it sent is not the hand-off notice's wording", "now needs you" in line_ao and "is handed to you by" not in line_ao, line_ao)
iid = IB.put(U["team-back"], line_ao, "msg", sender="home-send")
st_, body_ = server._client_post("a", "ack", {"delivered": [iid]})
check("11 ack: …the ack of that line, whatever its phrasing, delivers the hand-off", st_ == 200 and isinstance(ho(25).get("delivered_at"), float) and "queued" not in ho(25), (st_, ho(25)))
check("11 script labels: every label a script writes under is one (via a script on, (a script on …), a script on …), a session's name is not",
      all(H.is_script(x) for x in ("home-send via a script on testbox", "a script on testbox", "home-send (a script on testbox)")) and not H.is_script("home-send") and not H.is_script("cold-call"), None)

# ================================================================ 12. his hand-off ends
# A hand-off to Oliver is taken by no write of his: he answers on the board (a save with an author) or a session relays his answer, and the record read "handed to Oliver, not yet taken" for good.
def to_him(i, **kw):
    """An item of team-back's that a write of team-back hands to him by a decision: the record to Oliver is made by the write itself."""
    item(i, needs=["team-back"], mover="team-back", **kw)
    upd(i, "team-back", needs=["decision"], ask=ASK)
    return ho(i)
r_to_him = to_him(26)
check("12 his hand-off: a write that hands an item to him records it, mover Oliver, the agent in then", r_to_him.get("to") == OWN and not r_to_him.get("taken_at") and mt(26)["mover"] == OWN and mt(26)["then"] == "team-back", (mt(26), r_to_him))
check("12 his hand-off: …and get reads it as not yet taken", f"handoff: handed to {OWN}, not yet taken" in server.stackshot_get("a26"), server.stackshot_get("a26"))
upd(26, "team-back", next="Oliver: decide")
check("12 his hand-off: a later write of the agent's, with the item still his to move, leaves it not taken", not ho(26).get("taken_at"), ho(26))
check("12 his hand-off: …and his board answer ends it, with the mover back on the agent", server._answer("a26", "Yes", "", "answer") == "decision" and isinstance(ho(26).get("taken_at"), float)
      and mt(26)["mover"] == "team-back" and "then" not in mt(26), (mt(26), ho(26)))
g_aa = server.stackshot_get("a26")
check("12 his hand-off: …get no longer says not yet taken and the brief does not list it", "not yet taken" not in g_aa and f"handoff: handed to {OWN}, taken" in g_aa and "a26" not in "\n".join(server._handoff_brief()), g_aa)
to_him(161)
upd(161, "team-back", needs=["team-back"], clear_hold=True)
check("12 his hand-off: a session relaying his answer (needs without decision) ends it, and the mover is the agent again, with a note in the reply", isinstance(ho(161).get("taken_at"), float)
      and mt(161)["mover"] == "team-back" and "then" not in mt(161), (mt(161), ho(161)))
to_him(162)
out_ap = upd(162, "team-back", clear_needs=True, next="team-back: carry on")
check("12 his hand-off: clear_needs ends it too, and the reply says the mover came back", isinstance(ho(162).get("taken_at"), float) and f"(mover: {OWN} →" in out_ap, (out_ap, ho(162)))
to_him(27)
c_d = {"id": 67, "ts": time.time() + 5, "text": "go ahead", "url": "https://github.com/x/y/issues/1#issuecomment-67"}
server._github_comment("a27", c_d)
check("12 his hand-off: his comment on GitHub ends it", isinstance(ho(27).get("taken_at"), float) and ho(27)["taken_at"] == c_d["ts"], ho(27))
to_him(28)
server._github_comment("a28", {"id": 68, "ts": now0 - 7200, "text": "an old comment", "url": "https://github.com/x/y/issues/1#issuecomment-68"})
check("12 his hand-off: …a comment made before the hand-off does not", not ho(28).get("taken_at"), ho(28))
to_him(29)
it_am = server._load("a29"); it_am["metadata"]["state"] = "your-step"; it_am["metadata"]["step"] = "gh pr merge 1"; it_am["metadata"].pop("needs"); it_am["metadata"].pop("ask", None)
writes.save("a29", it_am)
check("12 his hand-off: it stays while the item stays his to move, whoever saves it (the server's own save, no writer)", not ho(29).get("taken_at") and mt(29)["mover"] == OWN, (mt(29), ho(29)))
it_am = server._load("a29"); it_am["metadata"].update(needs=["team-back"]); it_am["metadata"].pop("state", None); it_am["metadata"].pop("step", None)
writes.save("a29", it_am)
check("12 his hand-off: …and ends when the server's own save leaves it not his (no writer: a wake, an idle pass), the mover back on the agent", isinstance(ho(29).get("taken_at"), float) and mt(29)["mover"] == "team-back", (mt(29), ho(29)))
set_cfg(handoff=False)
to_him(166)
check("12 his hand-off: [model] handoff = false records nothing", not ho(166), ho(166))
set_cfg()
to_him(34)
raw_at = json.loads((T / "store/a/34.json").read_text()); raw_at["metadata"].update(needs=["team-back"], mover="team-back"); raw_at["metadata"].pop("ask", None); raw_at["metadata"].pop("then", None)
(T / "store/a/34.json").write_text(json.dumps(raw_at))          # a stored item no longer his, its record to him still not taken (written outside writes.save)
server.stackshot_confirm("a34", sender="team-back")
check("12 his hand-off: a confirm changes nothing but its clock: the record is not ended by it", not ho(34).get("taken_at") and mt(34)["mover"] == "team-back", ho(34))
upd(34, "team-back", next="team-back: carry on")
check("12 his hand-off: …the next real write ends it", isinstance(ho(34).get("taken_at"), float), ho(34))
to_him(171)
raw_au = json.loads((T / "store/a/171.json").read_text()); raw_au["metadata"].update(needs=["team-back"], mover="team-back"); raw_au["metadata"].pop("ask", None); raw_au["metadata"].pop("then", None)
(T / "store/a/171.json").write_text(json.dumps(raw_au))
upd(171, "team-back", priority="p2")
upd(171, "team-back", subject="[home] item 171 renamed")
check("12 his hand-off: a filing write (priority, rename) leaves the hand-off line as it is", not ho(171).get("taken_at") and mt(171)["mover"] == "team-back" and mt(171).get("priority") == "p2", (ho(171), mt(171)))
to_him(65)
upd(65, "team-back", status="completed", outcome="done", reason="finished", description="- A thing\n- It shipped\n- Done")
check("12 his hand-off: a close drops the mover and then, settles nothing and leaves the closed item's record alone", "mover" not in mt(65) and "then" not in mt(65) and not ho(65).get("taken_at") and "handoff:" not in server.stackshot_get("a65"), (mt(65), ho(65)))
# what a close and a confirm do to an item that stands in his state with then=<agent> and a hand-off to him not yet taken. The close path: writes.save reaches
# _settle_mover_on_save and _handoff_his_over with a closed item; model.settle returns None for status != open and handoff.pending_his is None for a closed record, so neither hook acts.
# The mover and then go because of model.DROP_ON_CLOSE, which update_unlocked (service/update.py) applies, not because of settle.
to_him(35)
pre_as = (mt(35)["mover"], mt(35)["then"], dict(ho(35)))
check("12 close: before the close the item is his (mover Oliver, then the agent) with the record to him not yet taken", pre_as[0] == OWN and pre_as[1] == "team-back" and not pre_as[2].get("taken_at"), pre_as)
out_aq = server.stackshot_complete("a35", outcome="done", reason="finished", description="- A thing\n- It shipped\n- Done", sender="team-back")
last_an = (mt(35).get("handoff_history") or [{}])[-1]
check("12 close: complete (not only update status=completed) on such an item: mover and then dropped, the record to him ends into the history unchanged but for how it ended (not taken, no event added), get shows no hand-off line",
      rd(35)["status"] == "completed" and "mover" not in mt(35) and "then" not in mt(35) and "handoff" not in mt(35) and last_an.get("ended") == "the item closed" and not last_an.get("taken_at") and "events" not in last_an
      and {k: v for k, v in last_an.items() if k not in ("ended", "ended_at")} == pre_as[2] and "handoff:" not in server.stackshot_get("a35"), (mt(35), ho(35), pre_as[2]))
shut = json.loads(json.dumps(rd(35))); shut["metadata"].update(mover="team-back", needs=["decision"], ask=ASK, handoff=dict(pre_as[2]))
check("12 close: the hooks themselves leave a closed item alone: _settle_mover_on_save on a closed item with a stored agent mover beside his state changes nothing",
      server._settle_mover_on_save(shut, rd(35)) is False and shut["metadata"]["mover"] == "team-back", shut["metadata"])
check("12 close: …and _handoff_his_over on a closed item with a not-taken record to him ends nothing (pending_his is None for a closed item)",
      server._handoff_his_over("a35", shut) is False and not shut["metadata"]["handoff"].get("taken_at"), shut["metadata"]["handoff"])
to_him(36)
pre_item = (json.dumps(rd(36), sort_keys=True), mt(36)["mover"], mt(36)["then"], dict(ho(36)))
server.stackshot_confirm("a36", sender="team-back")
row_after = rd(36)
check("12 confirm: on an item that is his to move (mover Oliver, then the agent, record not taken) it sets its clock only: mover, then, record and every other field as they were",
      mt(36)["mover"] == pre_item[1] and mt(36)["then"] == pre_item[2] and ho(36) == pre_item[3] and not ho(36).get("taken_at")
      and {k: v for k, v in row_after.items() if k not in ("confirmed", "written_by", "written_by_id", "written_at")} == {k: v for k, v in json.loads(pre_item[0]).items() if k not in ("confirmed", "written_by", "written_by_id", "written_at")}, (mt(36), ho(36)))
item(168, needs=["team-back"], mover="home-send")
check("12 his hand-off: an item never handed to him has no record to end", H.pending_his(rd(168)) is None, mt(168))
_rec = lambda to, **kw: {"status": "open", "metadata": {"handoff": {"to": to, "from": "home-send", "at": 1.0, "taken_at": None, **kw}}}
check("13 awaiting_session: a hand-off to a session not yet taken is one; to the owner (with or without no_clock), taken, or already asked of the fleet's builder is not; a mover must match",
      H.awaiting_session(_rec("team-back")) and H.awaiting_session(_rec("team-back"), "TEAM-Back") and not H.awaiting_session(_rec("team-back"), "home-other")
      and not H.awaiting_session(_rec("Oliver", no_clock=True)) and not H.awaiting_session(_rec("Oliver")) and not H.awaiting_session(_rec("team-back", no_clock=True))
      and not H.awaiting_session(_rec("team-back", taken_at=5.0)) and not H.awaiting_session(_rec("team-back", recovery_at=5.0)) and not H.awaiting_session({"status": "open", "metadata": {}}))

# ================================================================ 14. a turn that ends in a relaunch is no answer
# The case: the notice reached the pane, and its recycle ended the turn before it wrote; the new process came up idle, and the turn-end rule read that as "no write".
item(46); clear_pushes(); hand(46, "home-peer"); drain(); d_r = ho(46)["delivered_at"]
cli_row("home-peer", "busy", d_r - 60, started=d_r - 600)
check("14 relaunch: a pane that has run since before the delivery is no relaunch: nothing is due a minute in, and the notice was sent once", tick(d_r + MIN, 46) == [] and len(pushes_to("home-peer", "a46")) == 1 and "resent_at" not in ho(46), (ho(46), pushes()))
cli_row("home-peer", "idle", d_r + 31, started=d_r + 30)                 # the recycle: a new process, idle, 30 s after the delivery
COLD_N = len(COLD_MSGS); cold({"action": "hand_to", "to": "home-gamma-front", "reason": "should not be asked"})
done = tick(d_r + MIN, 46); drain()
r = ho(46)
check("14 relaunch: a mover whose pane was relaunched after the delivery and before it wrote is sent the notice again, once: the item stays with it, no cold call, no move down section 5",
      done == ["a46"] and r.get("to") == "home-peer" and not r.get("via") and len(COLD_MSGS) == COLD_N and not r.get("cold") and not mt(46).get("handoff_history") and r.get("resent_at") == d_r + MIN, (done, r))
check("14 relaunch: …the re-send went out to the pane that is back (the second push to it, saying the pane restarted), the sender and the builder were told nothing",
      len(pushes_to("home-peer", "a46")) == 2 and "sent again" in pushes_to("home-peer", "a46")[-1][1] and not pushes_to("home-send", "a46") and not pushes_to("team-back", "a46"), pushes())
check("14 relaunch: …the record says so (an event naming the relaunch and the start time, resent_after = the first delivery) and the clock restarted from the re-send's own delivery",
      r.get("resent_after") == d_r and r.get("delivered_at") and r["delivered_at"] != d_r and any("relaunched" in e.get("text", "") and "sent again" in e.get("text", "") for e in r.get("events", [])), r)
check("14 relaunch: …get shows it among the hand-off lines", any("relaunched" in ln and "sent again" in ln for ln in H.words(rd(46), time.time(), server._cfg.tz(), server._session_label)), H.words(rd(46), time.time(), server._cfg.tz(), server._session_label))
d_sb = r["delivered_at"]
cli_row("home-peer", "busy", d_sb + 1, started=d_r + 30)                  # the pane that is back takes the re-sent notice: a turn begins
check("14 relaunch: …a pass on, with the same relaunch still the newest, sends nothing again (once only), and neither does the clock before it is due", tick(d_sb + 5 * MIN, 46) == [] and len(pushes_to("home-peer", "a46")) == 2 and ho(46).get("to") == "home-peer", ho(46))
# the re-sent turn is lost too (a second relaunch): that is an answer of sorts, and the item goes down section 5 as it always did
cli_row("home-peer", "idle", d_sb + 61, started=d_sb + 60)
done = tick(d_sb + 2 * MIN, 46); drain()
check("14 relaunch: a second loss (the re-send's pane relaunched and idle with no write) goes down section 5 as today: to the project's builder, not re-sent again",
      done == ["a46"] and ho(46).get("to") == "team-back" and ho(46).get("via") == "redirect" and "turn ended" in ho(46).get("reason", "") and len(pushes_to("home-peer", "a46")) == 2, (done, ho(46)))
# a relaunch AFTER the pane wrote is nothing to re-send (the hand-off is taken), and one before the delivery is none either
item(48); hand(48, "home-peer"); drain(); d_t = ho(48)["delivered_at"]
start(48, "home-peer", next="home-send: it is done on my side"); drain()
cli_row("home-peer", "idle", d_t + 31, started=d_t + 30); n_resent = len(pushes_to("home-peer", "a48"))
check("14 relaunch: a hand-off its mover took before the relaunch is not re-sent", ho(48).get("taken_at") and tick(d_t + MIN, 48) == [] and len(pushes_to("home-peer", "a48")) == n_resent and "resent_at" not in ho(48), ho(48))
# a hand-off whose notice only waits (inbox) has no delivery to lose: a relaunch before the ack re-sends nothing
item(86); inbox("home-peer"); hand(86, "home-peer"); drain(); inbox()
cli_row("home-peer", "idle", time.time() + 5, started=time.time() + 4)
check("14 relaunch: …nor one whose notice is still waiting in the inbox (it was never delivered, so nothing was lost)", ho(86).get("delivered_at") is None and tick(time.time() + 2 * MIN, 86) == [] and "resent_at" not in ho(86), ho(86))
(T / f"cli/{os.getpid()}-home-peer.json").unlink(missing_ok=True)
# a pane this box does not run has no registry row: no relaunch is seen, the hand-off goes on as it did
item(78); hand(78, "home-peer"); drain(); d_u = ho(78)["delivered_at"]
check("14 relaunch: a mover with no registry row on this box (a remote pane) is never re-sent (no signal: the hand-off goes on as before)", H.relaunched(ho(78), server._handoff_env(d_u + MIN), "home-peer") == "" and tick(d_u + MIN, 78) == [], ho(78))
# the re-send's push result is lost (the server restarts between the save and the push's report): the record is marked queued now, so its clock starts at the inbox grace and the hand-off still times out
item(57); hand(57, "home-peer"); drain(); d_w = ho(57)["delivered_at"]
cli_row("home-peer", "busy", d_w + 31, started=d_w + 30)
_tell_kept = telling.tell_woken; telling.tell_woken = lambda *a, **k: None          # the notice goes nowhere and no result is ever reported
try:
    done = tick(d_w + MIN, 57)
finally:
    telling.tell_woken = _tell_kept
r = ho(57); env_z = server._handoff_env(d_w)
check("14 relaunch: a re-send saved with no push result is marked queued now (queued = resent, queued_at = the re-send), so the record has a clock", done == ["a57"] and r.get("resent_at") == d_w + MIN and r.get("delivered_at") is None
      and r.get("queued") == "resent" and r.get("queued_at") == d_w + MIN and H.clock_start(r, env_z) == d_w + MIN + env_z.inbox_grace * 60, r)
t_ay = d_w + MIN + (env_z.inbox_grace + env_z.minutes) * 60
check("14 relaunch: …nothing is due before the inbox grace and the hand-off minutes are over", tick(d_w + MIN + 5 * MIN, 57) == [] and ho(57).get("to") == "home-peer", ho(57))
done = tick(t_ay + MIN, 57); drain()
check("14 relaunch: …and then it times out down section 5 as any hand-off does (to the project's builder), never left with no clock and never asked of the fleet's builder for it",
      done == ["a57"] and ho(57).get("to") == "team-back" and ho(57).get("via") == "redirect" and "did not take it" in ho(57).get("reason", "") and not ho(57).get("recovery_at"), (done, ho(57)))
# a re-send whose push fails is sent once more worded as a re-send (not as the first notice)
item(58); hand(58, "home-peer"); drain(); d_x = ho(58)["delivered_at"]
cli_row("home-peer", "busy", d_x + 31, started=d_x + 30)
failing("home-peer")
try:
    tick(d_x + MIN, 58); drain()
finally:
    failing()
p_ar = pushes_to("home-peer", "a58")
check("14 relaunch: a re-send whose push fails is tried once more with the same words: all three pushes to the pane after the first say the notice is sent again, the first does not",
      len(p_ar) == 3 and "sent again" not in p_ar[0][1] and "sent again" in p_ar[1][1] and "sent again" in p_ar[2][1], p_ar)
# the row a pane is read from, shared by _handoff_status and _handoff_started: alive, interactive, the most recently updated one
def cli_clear():
    for f in (T / "cli").glob("*.json"): f.unlink()
def same_row(who, want_at, want_started, want_status):
    s, at = server._handoff_status(who); st = server._handoff_started(who)
    return s == want_status and abs(at - want_at) < 0.01 and abs(st - want_started) < 0.01
cli_clear(); t14 = time.time(); _p = subprocess.Popen([sys.executable, "-c", "pass"]); _p.wait(); DEAD = _p.pid
cli_row("home-peer", "idle", t14 + 10, started=t14 + 9, pid=DEAD)
check("14 started: a row of a process that is gone says nothing (no start, no status)", server._handoff_started("home-peer") == 0.0 and server._handoff_status("home-peer") == ("", 0.0), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_clear()
cli_row("home-peer", "idle", t14 + 100, started=t14 + 90, file="old.json")
cli_row("home-peer", "busy", t14 + 200, started=t14 + 5, file="new.json")
check("14 started: two live rows of one session: the most recently updated one is the pane, for the start as for the status (the later start of the older row is not taken)", same_row("home-peer", t14 + 200, t14 + 5, "busy"), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_row("home-peer", "idle", t14 + 300, started=t14 + 4, pid=DEAD, file="dead.json")
check("14 started: …a newer row of a dead process does not count either", same_row("home-peer", t14 + 200, t14 + 5, "busy"), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_clear()
cli_row("home-peer", "idle", t14 + 50, started=t14 + 40, sid="a-session-id-this-box-does-not-know")
check("14 started: a row that matches by name alone (its session id is another) is the pane", same_row("home-peer", t14 + 50, t14 + 40, "idle"), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_clear()
cli_row("home-peer", "busy", t14 + 500, started=t14 + 400, kind="headless", file="bg.json")
check("14 started: a row that is no interactive pane (a headless process of the session) says nothing: no start, no status", server._handoff_started("home-peer") == 0.0 and server._handoff_status("home-peer") == ("", 0.0), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_row("home-peer", "idle", t14 + 100, started=t14 + 90, file="pane.json")
check("14 started: …and beside the pane's own row it does not win by being newer", same_row("home-peer", t14 + 100, t14 + 90, "idle"), (server._handoff_started("home-peer"), server._handoff_status("home-peer")))
cli_clear()
item(63); hand(63, "home-peer"); drain(); d_y = ho(63)["delivered_at"]
cli_row("home-peer", "busy", d_y + 5, started=d_y - 600, file="pane.json")
cli_row("home-peer", "busy", d_y + 40, started=d_y + 30, kind="headless", file="bg.json")        # a headless process of the session starts after the delivery
check("14 relaunch: a headless process of the session starting after the delivery is no relaunch of its pane: nothing is re-sent", tick(d_y + MIN, 63) == [] and "resent_at" not in ho(63) and len(pushes_to("home-peer", "a63")) == 1, (ho(63), pushes_to("home-peer", "a63")))
cli_clear()
# pure: the plan alone
env14 =H.Env(now=100.0, derive=server._ho_derive, started=lambda who: 90.0)
check("14 relaunch: pure, relaunched() needs a delivery, a start after it, and no earlier re-send",
      H.relaunched({"delivered_at": 80.0}, env14, "x") != "" and H.relaunched({"delivered_at": 95.0}, env14, "x") == "" and H.relaunched({"delivered_at": None}, env14, "x") == ""
      and H.relaunched({"delivered_at": 80.0, "resent_at": 85.0}, env14, "x") == "" and H.relaunched({"delivered_at": 80.0}, H.Env(now=100.0, derive=server._ho_derive), "x") == "")

# ================================================================ 15. the record follows the mover
def stale_now(i):
    it = rd(i); return H.stale(it, H.mover_of(it, lambda x: server._ho_derive({**x, "gid": f"a{i}"})), server._ho_same)
def hist(i): return [h.get("to") for h in (mt(i).get("handoff_history") or [])]
# 15.1 a session's hand-off, then a hand-on by another session
item(90); hand(90, "home-peer"); drain()
check("15 session: a hand-off records the mover", ho(90).get("to") == "home-peer" and not stale_now(90), ho(90))
upd(90, "home-send", mover="home-peer2", next="home-peer2: do the thing", wake=FUT); drain()
check("15 session: handed on to another session: the record names it and the first goes to the history", ho(90).get("to") == "home-peer2" and hist(90)[-1] == "home-peer" and not stale_now(90), (ho(90), hist(90)))

# 15.1b a hand-off that carries a bare date never parks the item: the date stays as the hand-off's backstop, the item is alive in the new mover's lane and the record is made
import io as _io
for n_, kw_ in ((140, {"wake": FUT}), (141, {"until": FUT}), (142, {"wake": FUT, "check": CHK})):
    item(n_); server.stackshot_update(f"a{n_}", sender="home-send", mover="home-peer", next="home-peer: do the thing", **kw_); drain()
    m_ = mt(n_)
    check(f"15.1b a{n_} a hand-off with {'/'.join(sorted(kw_))}: the record names the new mover and the item is not parked", ho(n_).get("to") == "home-peer" and m_.get("mover") == "home-peer" and not stale_now(n_) and not m_.get("until") and not m_.get("hold"), m_)
    check(f"15.1b a{n_} …the date stays as the hand-off's backstop (a wake), and the board draws the item alive", m_.get("wake") == FUT and not server._is_parked(rd(n_)) and not server._date_parked(rd(n_)), m_)
item(143); out143 = upd(143, "home-send", mover="home-peer", next="home-peer: do the thing", wake=FUT)
check("15.1b the reply names no wait note for the backstop", "alone is a wait" not in out143 and "put on hold" not in out143 and "until" not in out143.split("\n", 1)[0], out143[-400:])
item(146); out146 = server.stackshot_update("a146", sender="home-send", mover="home-peer", next="home-peer: do the thing", wake=FUT)      # through the tool: the whole reply, the alias note included
check("15.1b the whole reply of the tool says the date is stored as the wake, the hand-off's backstop, and no wait (not as until)",
      f"stored as wake={FUT}" in out146 and "no wait" in out146 and "stored as until" not in out146 and "now written as until" not in out146 and "alone is a" not in out146 and "put on hold" not in out146, out146[-700:])
check("15.1b …and the stored date is the wake it says", mt(146).get("wake") == FUT and not mt(146).get("until"), mt(146))
item(147); out147 = server.stackshot_update("a147", sender="home-send", mover="home-peer", next="home-peer: do the thing", check=CHK, ask_by=FUT)
check("15.1b an ask_by backstop says so in the whole reply too", f"stored as ask_by={FUT}" in out147 and "stored as until" not in out147, out147[-700:])
item(148); out148 = server.stackshot_update("a148", sender="home-send", next="home-send: do the thing now", wake=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")      # control: no hand-off, the alias note is the plain one
check("15.1b control: with no hand-off the alias note says the date is stored as until", f"stored as until={FUT}" in out148 and "backstop" not in out148, out148[-500:])
item(144); upd(144, "home-send", next="home-send: do the thing now", wake=FUT)       # no hand-off: the same bare date is a wait, and the item is parked on its date
check("15.1b control: the same date with no hand-off is a wait stored as until", mt(144).get("until") == FUT and "wake" not in mt(144) and server._is_parked(rd(144)), mt(144))
try:
    item(145); upd(145, "home-send", mover="home-peer", next="home-peer: do the thing"); e145 = ""
except Exception as e_:
    e145 = str(e_)
check("15.1b a hand-off with neither a check nor a date is still refused, and the refusal says the date is a backstop that is no wait", "backstop of this hand-off" in e145 and "the date is no wait" in e145 and "the item stays active in the new mover's lane" in e145, e145[:600])
# 15.1c the hand-off the DERIVED mover shows (needs naming a session, no mover argument) with a bare date, or a hand-off with ask_by as the date: it records and never parks (the date stays as the backstop)
item(150, needs=["home-send"]); out150 = upd(150, "home-send", needs=["team-back"], next="team-back: do the thing", wake=FUT); drain()
item(151, needs=["home-send"]); out151 = server.stackshot_update("a151", sender="home-send", needs=["team-back"], until=FUT); drain()
item(152); out152 = upd(152, "home-send", mover="home-peer", next="home-peer: do the thing", check=CHK, ask_by=FUT); drain()
for n_, who_ in ((150, "team-back"), (151, "team-back"), (152, "home-peer")):
    m_ = mt(n_)
    check(f"15.1c a{n_} the hand-off to {who_} with a bare date is recorded and the item is not parked", ho(n_).get("to") == who_ and not stale_now(n_) and not m_.get("until") and not m_.get("hold") and not server._is_parked(rd(n_)) and not server._date_parked(rd(n_)), m_)
check("15.1c a150 …the date is kept as the wake, the backstop", mt(150).get("wake") == FUT and mt(151).get("wake") == FUT, (mt(150), mt(151)))
check("15.1c a152 …the date given as ask_by stays as it was given (the backstop)", mt(152).get("ask_by") == FUT and not mt(152).get("wake"), mt(152))
item(153, needs=["home-send"]); upd(153, "home-send", needs=["team-back"], next="team-back: do the thing", wake=FUT, check=CHK); drain()
check("15.1c control: needs, a next line and a check with the date is a hand-off too (as it was)", ho(153).get("to") == "team-back" and not server._is_parked(rd(153)), mt(153))
item(154, mover="home-send"); upd(154, "home-send", next="home-send: do the thing now", wake=FUT)
check("15.1c control: a bare date on an item whose mover does not change is still a wait, stored as until", mt(154).get("until") == FUT and server._is_parked(rd(154)), mt(154))
# 15.1d a hand-off write on an item a bare until had parked ends that wait, keeps the date as the backstop, and the reply says so; a write that hands nothing on leaves the park alone
item(155, mover="home-front"); server.stackshot_update("a155", sender="home-front", until=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
check("15.1d the item is parked on its until before the hand-off", mt(155).get("until") == FUT and server._is_parked(rd(155)), mt(155))
out155 = server.stackshot_update("a155", sender="home-send", mover="home-peer", next="home-peer: do the thing", check=CHK); drain()
check("15.1d the hand-off ends the wait: the record is made, the date stays as the wake, the item is active", ho(155).get("to") == "home-peer" and mt(155).get("wake") == FUT and not mt(155).get("until") and not server._is_parked(rd(155)) and not stale_now(155), mt(155))
check("15.1d …and the reply says so, with the date", f"the item was waiting until {FUT}" in out155 and "this hand-off ends that wait" in out155 and "backstop" in out155, out155[-600:])
item(156, mover="home-front"); server.stackshot_update("a156", sender="home-front", until=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
upd(156, "home-send", next="home-front: do the thing again"); drain()
check("15.1d control: a write by another session that hands nothing on leaves the park as it was (no record, still parked on its until)", mt(156).get("until") == FUT and server._is_parked(rd(156)) and not ho(156), mt(156))
# 15.1e one rule for a park: the keeper relay's put-on-hold (_date_parked) agrees with the board's (_is_parked), a decision on his call included
item(157, needs=["decision"], until=FUT, ask=ASK)
check("15.1e an item waiting on his decision with an until is parked by neither reading", not server._is_parked(rd(157)) and not server._date_parked(rd(157)), mt(157))
for n_, kw_ in ((158, {"until": FUT}), (159, {"until": FUT, "wait_kind": "time"}), (160, {"until": FUT, "wait_kind": "relay"}), (161, {"hold": True, "wake": FUT}), (162, {})):
    item(n_, mover="home-front", **kw_)
    check(f"15.1e a{n_} {sorted(kw_)}: _date_parked is _is_parked for an item with no hold flag, and neither parks a decision", (server._date_parked(rd(n_)) == server._is_parked(rd(n_))) or bool(mt(n_).get("hold")), mt(n_))
# 15.1f the backstop reading fails closed: when handoff.detect raises inside _hands_on (service/update.py), the date stays the hand-off's backstop (the item stays active) and the failure is logged
import contextlib as _cl
from stackshot.service import update as _upd_svc
_real_detect = server._ho.detect
def _raising_detect(*a, **k):
    if sys._getframe(1).f_code.co_name == "_hands_on":
        raise RuntimeError("forced")
    return _real_detect(*a, **k)
_err = _io.StringIO()
server._ho.detect = _raising_detect
try:
    with _cl.redirect_stderr(_err):
        direct_ = _upd_svc._hands_on("a149", rd(150), rd(150), None, "home-send")
        item(149); upd(149, "home-send", next="home-send: do the thing now", wake=FUT)      # a write that hands nothing on: the reading fails, so the date is kept as the backstop and the item is not parked
finally:
    server._ho.detect = _real_detect
check("15.1f a reading that fails counts as a hand-off (fail closed)", direct_ is True, direct_)
check("15.1f …the failure is logged, naming that the date stays a backstop", "backstop not judged: RuntimeError: forced" in _err.getvalue() and "the item stays active" in _err.getvalue(), _err.getvalue()[-300:])
check("15.1f …and a write whose reading fails keeps its date as the wake and leaves the item active", mt(149).get("wake") == FUT and not mt(149).get("until") and not server._is_parked(rd(149)), mt(149))
# 15.1g a failed reading leaves a stored bare until untouched (no "ends that wait") and the reply says the reading failed
item(163, mover="home-front"); server.stackshot_update("a163", sender="home-front", until=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
server._ho.detect = _raising_detect
try:
    with _cl.redirect_stderr(_io.StringIO()):
        out163 = server.stackshot_update("a163", sender="home-send", needs=["team-back"])      # a hand-off the derived mover shows: no hand-off line in next, so the reading itself runs
finally:
    server._ho.detect = _real_detect
check("15.1g the stored until stays as it was, and the item stays parked on it", mt(163).get("until") == FUT and not mt(163).get("wake") and server._is_parked(rd(163)), mt(163))
check("15.1g …the reply says the hand-off reading failed and the wait was kept, never that the hand-off ends it",
      "the hand-off reading failed" in out163 and f"the wait until {FUT} is kept as it was" in out163 and "this hand-off ends that wait" not in out163, out163[-500:])
item(164); server._ho.detect = _raising_detect
try:
    with _cl.redirect_stderr(_io.StringIO()):
        out164 = server.stackshot_update("a164", sender="home-send", next="home-send: do the thing now", wake=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
finally:
    server._ho.detect = _real_detect
check("15.1g a new date whose reading failed is kept as the wake, and the reply says the reading failed", mt(164).get("wake") == FUT and "the hand-off reading failed, so the date is kept as it was given" in out164, (mt(164), out164[-400:]))
FUT2 = time.strftime("%Y-%m-%d", time.gmtime(now0 + 7 * 86400 + ZONE_OFFSET))
item(165, mover="home-front"); server.stackshot_update("a165", sender="home-front", until=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
server._ho.detect = _raising_detect
try:
    with _cl.redirect_stderr(_io.StringIO()):
        out165 = server.stackshot_update("a165", sender="home-send", until=FUT2, needs=["team-back"], wait_reason="the nightly run finishes at 03:00 on the day after")
finally:
    server._ho.detect = _real_detect
check("15.1g a new date on an item a bare until parks, with the reading failed: the reply names the date that is stored, not the one kept", mt(165).get("until") == FUT2 and f"stored as the wait until {FUT2}" in out165 and f"it was until {FUT}" in out165 and "is kept as it was" not in out165, (mt(165), out165[-500:]))
item(166, mover="home-front"); server.stackshot_update("a166", sender="home-front", until=FUT, wait_reason="the nightly run finishes at 03:00 tomorrow")
server._ho.detect = _raising_detect
try:
    with _cl.redirect_stderr(_io.StringIO()):
        out166 = server.stackshot_update("a166", sender="home-front", description="- Goal: the nightly run finishes")
finally:
    server._ho.detect = _real_detect
check("15.1g a write that touches no date and cannot hand the item on (its description alone), with the reading failed, gets no hand-off note", "the hand-off reading failed" not in out166 and mt(166).get("until") == FUT, (mt(166), out166[-400:]))
upd(90, "home-peer2", mover="home-peer2", next="home-peer2: carry on")
check("15 session: the mover writing itself in as the mover takes it, the record stays its own", ho(90).get("to") == "home-peer2" and not stale_now(90), ho(90))
# 15.2 a session makes ITSELF the mover over a record to someone else: the old record ends (no record for a self-naming)
item(91); hand(91, "home-peer"); drain()
upd(91, "home-send", mover="home-send", next="home-send: do the thing")
check("15 session: a session making itself the mover ends the record to the one it took the item from (no record of a self-naming)", "handoff" not in mt(91) and hist(91)[-1] == "home-peer" and not stale_now(91), mt(91))
# 15.3 a needs hand-off, then needs changed to another background agent
item(92); upd(92, "home-send", needs=["team-back"], next="team-back: do the thing"); drain()
check("15 needs: a hand-off through needs records the session in needs", ho(92).get("to") == "team-back", ho(92))
upd(92, "home-send", needs=["home-docs"], next="home-docs: do the thing"); drain()
check("15 needs: …and a later needs naming another one moves the record there", ho(92).get("to") == "home-docs" and not stale_now(92), ho(92))
# 15.4 a time wait's post_wake_mover takes effect on a wake: the server's own save records it, the wake notice delivers it
dayp = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * 86400.0 + ZONE_OFFSET))
item(93, wait_kind="time", hold=True, wake=dayp(-1), post_wake_mover="team-back", needs=[], handoff=rec("home-peer"))
clear_pushes(); woke = server._wake_pass(); drain()
check("15 wake: a time wait's post_wake_mover becomes the mover on the wake, and the record names it, from the server (the record to the one before goes to the history)",
      "a93" in woke and mt(93).get("mover") == "team-back" and ho(93).get("to") == "team-back" and ho(93).get("from") == "stackshot" and "home-peer" in hist(93) and not stale_now(93), (woke, mt(93)))
check("15 wake: …and the wake notice delivered it (the clock can start)", isinstance(ho(93).get("delivered_at"), float) and len(pushes_to("team-back", "a93")) >= 1, (ho(93), pushes()))
# 15.5 a cold call's hand-on
item(94, project="projects/gamma", owner=U["home-gamma-front"], needs=[]); hand(94, "home-peer"); drain(); d94 = ho(94)["delivered_at"]
cold({"action": "hand_to", "to": "home-gamma-docs", "reason": "it knows the pages"})
tick(d94 + 11 * MIN, 94); drain()
check("15 cold call: a hand-on by the cold call leaves the record on the new mover", mt(94).get("mover") == "home-gamma-docs" and ho(94).get("to") == "home-gamma-docs" and not stale_now(94), (mt(94), ho(94)))
# 15.6 close and reopen
item(95); hand(95, "home-peer"); drain()
server.stackshot_complete("a95", outcome="done", reason="finished", description="- A thing\n- It shipped\n- Done", sender="home-peer"); drain()
check("15 close: the mover's own close takes the record (a close is a start): taken, nothing stale", rd(95)["status"] == "completed" and ho(95).get("taken_at") and not stale_now(95), (rd(95)["status"], mt(95)))
item(115); hand(115, "home-peer"); drain()
server.stackshot_complete(f"a{115}", outcome="done", reason="finished", description="- A thing\n- It shipped\n- Done", sender="home-send"); drain()
check("15 close: another session's close ends the open record into the history (\"the item closed\"): a closed item has no mover and no open record",
      rd(115)["status"] == "completed" and "handoff" not in mt(115) and mt(115)["handoff_history"][-1].get("ended") == "the item closed" and not stale_now(115), (rd(115)["status"], mt(115)))
upd(95, "home-send", status="open", mover="team-back", next="team-back: look again", wake=FUT); drain()
check("15 reopen: reopened with a new mover, the record names it", rd(95)["status"] == "open" and ho(95).get("to") == "team-back" and not stale_now(95), (rd(95)["status"], mt(95)))
# 15.7 the owner's board answer, a script's save and the server's own save (no session wrote)
item(96); hand(96, "home-peer"); drain()
it96 = rd(96); it96["metadata"]["mover"] = "team-back"; it96["metadata"]["next"] = "team-back: carry out"
writes.save("a96", it96, note="answered on the board", author=(server.OWNER, "board"))
check("15 owner answer: the owner's answer that makes another the mover ends the record to the one left and makes none", "handoff" not in mt(96) and hist(96)[-1] == "home-peer" and not stale_now(96), mt(96))
item(97); hand(97, "home-peer"); drain()
it97 = rd(97); it97["metadata"]["mover"] = "team-back"; it97["metadata"]["next"] = "team-back: carry out"
writes.save("a97", it97, writer="home-send via a script on testbox")
check("15 script: a script's save ends the record to the mover it took the item from, and records none", "handoff" not in mt(97) and not stale_now(97), mt(97))
item(98); hand(98, "home-peer"); drain()
it98 = rd(98); it98["metadata"]["mover"] = "team-back"; it98["metadata"]["next"] = "team-back: carry out"
writes.save("a98", it98)
check("15 server save: the server's own save moves the record to the new mover, from the server", ho(98).get("to") == "team-back" and ho(98).get("from") == "stackshot" and hist(98)[-1] == "home-peer" and not stale_now(98), mt(98))
item(99); hand(99, "home-peer"); drain(); rec99 = dict(ho(99))
it99 = rd(99); writes.save("a99", it99)
check("15 server save: a save that leaves the mover alone changes nothing about the record", ho(99) == rec99, (ho(99), rec99))
# 15.8 a record that carries the recovery request of an open item stays (a closed item's is ended with the close) (the item goes to the owner's state)
item(100, handoff=rec("home-peer", recovery_at=now0 - 100, recovery_reason="nobody could take it", stall=True), mover="home-peer")
it_ad = rd(100); it_ad["metadata"].pop("mover"); it_ad["metadata"]["needs"] = ["decision"]; it_ad["metadata"]["ask"] = ASK; writes.save(f"a{100}", it_ad)
check("15 recovery: a record with the recovery request stays while the item is open (the item goes to the owner's state)", bool(ho(100).get("recovery_at")) and not stale_now(100), ho(100))
# 15.9 delivery on the other notice paths
item(102, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); server._handoff_told_text("home-peer", f"[board] a{102} needs a look", "delivered → x")
check("15 told: a push to the mover whose text names the item marks its open record delivered", isinstance(ho(102).get("delivered_at"), float), ho(102))
item(103, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); server._handoff_told_text("home-peer", f"a{103} again", "inbox → x")
check("15 told: …a push that waits in the inbox marks it queued, not delivered", not ho(103).get("delivered_at") and str(ho(103).get("queued", "")).startswith("inbox"), ho(103))
item(104, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); server._handoff_told_text("home-peer", f"a{104} again", "failed: not live")
check("15 told: …a failed one marks nothing (the notice senders retry)", not ho(104).get("delivered_at") and not ho(104).get("queued"), ho(104))
item(105, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); server._handoff_told_text("home-peer2", f"a{105}", "delivered → x")
check("15 told: …to someone else marks nothing", not ho(105).get("delivered_at"), ho(105))
item(106, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); got_ab = server._router_delivered("home-peer", f"a{106} was ruled → {telling.notice_link(f'a{106}')}", "delivered → x")
check("15 told: the router's delivery hook marks the record and returns the outcome unchanged", got_ab == "delivered → x" and isinstance(ho(106).get("delivered_at"), float), (got_ab, ho(106)))
item(107, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); telling.push_noted("home-peer", f"[stackshot] a{107} owes its page → {telling.notice_link(f'a{107}')}")
check("15 told: the keeper batch and anchors prompt send (push_noted) marks the record of an item the note names", isinstance(ho(107).get("delivered_at"), float), ho(107))

# 15.10 the one-off repair: records the older code left, found and ended; dry by default
item(110, mover="team-back", handoff=rec("home-peer"))                        # open record to someone but the mover
item(111, mover="home-peer", handoff=rec("home-peer"))                        # fine
item(112, mover="team-back", handoff=rec("home-peer", taken_at=now0 - 100))   # taken: history
item(113, status="completed", handoff=rec("home-peer"))                       # closed (the older code left its record open)
item(114, handoff=rec("home-peer"), wait_kind="time", hold=True, wake=dayp(3), post_wake_mover="team-back", needs=[])   # waiting: no mover
before = {i: json.dumps(rd(i), sort_keys=True) for i in (110, 111, 112, 113, 114)}
mine = lambda rows: sorted(r["gid"] for r in rows if r["gid"] in (f"a{110}", f"a{111}", f"a{112}", f"a{113}", f"a{114}"))      # (section 12 leaves two stored states of the older code on the board: the repair sees them too)
rows = server._handoff_repair()
check("15 repair: the dry run lists the open records that name someone but the mover (110, a waiting item's 114, a closed item's 113) and no other (not 111: its mover; not 112: taken)", mine(rows) == [f"a{110}", f"a{113}", f"a{114}"], rows)
check("15 repair: …and writes nothing", all(json.dumps(rd(i), sort_keys=True) == before[i] for i in before), None)
clear_pushes(); rows2 = server._handoff_repair(apply=True)
check("15 repair: --apply ends exactly those: the record to the history (a closed item's as \"the item closed\"), the item kept as it was otherwise",
      "handoff" not in mt(110) and hist(110)[-1] == "home-peer" and "handoff" not in mt(114) and "handoff" not in mt(113) and (mt(113)["handoff_history"][-1].get("ended")) == "the item closed" and mt(110).get("mover") == "team-back"
      and ho(111).get("to") == "home-peer" and json.dumps(rd(112), sort_keys=True) == before[112] and mine(rows2) == [f"a{110}", f"a{113}", f"a{114}"], (mt(110), mt(113), mt(114)))
check("15 repair: …and a second run finds none", server._handoff_repair() == [], server._handoff_repair())
check("15 repair: nobody is told and no record is made new", not pushes() and "handoff" not in mt(110), pushes())

# 15.11 review fixes: a server-made record runs no take clock, and a taken record to the same name does not stand in for the wake's new hand-off
def parked(i, post, **kw):
    item(i, wait_kind="time", hold=True, wake=dayp(-1), post_wake_mover=post, needs=kw.pop("needs", []), **kw)
parked(116, "team-back", handoff=rec("team-back", taken_at=now0 - 900))          # team-back took it, then parked it for itself
clear_pushes(); woke = server._wake_pass(); drain()
r_wake = ho(116); h_wake = (mt(116).get("handoff_history") or [{}])[-1]
check("15 wake after a take: a wake to a mover who already holds a TAKEN record to the same name makes a new record (from the server, not taken); the taken one goes to the history as handed on",
      f"a{116}" in woke and r_wake.get("to") == "team-back" and r_wake.get("from") == "stackshot" and not r_wake.get("taken_at") and h_wake.get("taken_at") and h_wake.get("ended") == "handed on" and not stale_now(116), (woke, mt(116)))
check("15 wake after a take: …marked no_clock, and the wake notice delivered it", r_wake.get("no_clock") is True and isinstance(r_wake.get("delivered_at"), float), r_wake)
check("15 no clock: the take clock never runs on a server-made record (a day on, nothing fires; the stall pass keeps the timing)", tick(time.time() + 86400, 116, 93) == [] and ho(116).get("to") == "team-back" and ho(93).get("no_clock") is True, (ho(116), ho(93)))
check("15 no clock: …and a session's hand-off keeps its clock (no_clock is not on it)", not ho(90).get("no_clock") and not ho(1).get("no_clock"), (ho(90), ho(1)))
item(117, mover="home-peer", handoff=rec("home-peer", taken_at=now0 - 900)); it_ae = rd(117); writes.save(f"a{117}", it_ae)
check("15 no clock: a server save that leaves the mover alone makes no record over a taken one (the same mover, no hand-off)", ho(117).get("taken_at") and "handoff_history" not in mt(117), mt(117))

# 15.12 a server-made record is not marked delivered until a notice actually reaches the mover: a front agent, a held notice, or a notice that goes to another session in needs
_real_gate = telling.front_gate
parked(119, "home-peer", handoff=rec("home-docs", taken_at=now0 - 900))
telling.front_gate = lambda gid, owner, note, tag, kind: True          # the front gate holds every notice (a front agent away, a quiet hour)
clear_pushes(); woke = server._wake_pass(); drain()
telling.front_gate = _real_gate
check("15 undelivered: a wake whose notice the front gate holds still records the hand-off (no_clock), and nothing marks it delivered while no notice reached the mover",
      f"a{119}" in woke and ho(119).get("to") == "home-peer" and ho(119).get("no_clock") is True and not ho(119).get("delivered_at") and not pushes_to("home-peer", f"a{119}"), (woke, ho(119), pushes()))
parked(120, "home-front", handoff=rec("home-docs", taken_at=now0 - 900))
clear_pushes(); woke = server._wake_pass(); drain()
check("15 undelivered: a record to a front agent is made, no_clock, and is delivered only if a notice reached it", f"a{120}" in woke and ho(120).get("to") == "home-front" and ho(120).get("no_clock") is True
      and bool(ho(120).get("delivered_at")) == bool(pushes_to("home-front", f"a{120}")), (woke, ho(120), pushes()))
item(121, mover="home-peer", needs=["home-docs"], handoff=rec("home-peer", taken_at=now0 - 900))
it_af = rd(121); it_af["metadata"]["mover"] = "team-back"; writes.save(f"a{121}", it_af)          # the server's own save moves it on; the notice goes to the session in needs, not to the mover
clear_pushes(); telling.tell_woken(f"a{121}", "home-docs", f"[stackshot] a{121} changed → {telling.notice_link(f'a{121}')}"); drain()
check("15 undelivered: a server save that moves the item on records the hand-off to the new mover, no_clock, and a notice that goes to a session in needs other than that mover marks nothing",
      ho(121).get("to") == "team-back" and ho(121).get("from") == "stackshot" and ho(121).get("no_clock") is True and not ho(121).get("delivered_at") and [x for x in pushes() if x[0] == "home-docs"] and not pushes_to("team-back", f"a{121}"), (mt(121), pushes()))
server._handoff_told_text("team-back", f"[stackshot] a{121} woke → {telling.notice_link(f'a{121}')}", "delivered → x", link_only=True)
check("15 undelivered: …and a notice that does reach the mover marks it delivered", isinstance(ho(121).get("delivered_at"), float), ho(121))

# 15.13 the router push and the keeper batch mark an item delivered only on its own notice link; the message path takes a citation
item(122, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); item(123, mover="home-peer", handoff=rec("home-peer", delivered_at=None))
batch_text = f"- a{122} needs a look → {telling.notice_link(f'a{122}')}\n- a{122} follows a{123} in the subject, which this line has no link for"
server._router_delivered("home-peer", batch_text, "delivered → x")
check("15 told: a batch notice citing another item in a subject does not mark that item delivered on the router push (only the item whose own link it carries)",
      isinstance(ho(122).get("delivered_at"), float) and not ho(123).get("delivered_at"), (ho(122), ho(123)))
item(124, mover="home-peer", handoff=rec("home-peer", delivered_at=None))
telling.push_noted("home-peer", f"- a{122} page owed → {telling.notice_link(f'a{122}')} (follows a{124})")
check("15 told: …and on the keeper batch (push_noted) too", not ho(124).get("delivered_at"), ho(124))
server._handoff_told_text("home-peer", batch_text, "delivered → x")
check("15 told: the message path stays as it was: a citation of the item is enough there", isinstance(ho(123).get("delivered_at"), float), ho(123))
item(140, mover="home-peer", handoff=rec("home-peer", delivered_at=None)); item(1400, mover="home-peer", handoff=rec("home-peer", delivered_at=None))
server._handoff_told_text("home-peer", f"a{140} is cited; the notice is for a{1400} → {telling.notice_link(f'a{1400}')}", "delivered → x", link_only=True)
check("15 told: the link of one item is no link of an item whose id it begins (the id ends at a non-word character)", isinstance(ho(1400).get("delivered_at"), float) and not ho(140).get("delivered_at"), (ho(1400), ho(140)))

# 15.14 the stored copy of an item from before an earlier change is read the way the loaded one is
raw = {"id": "125", "subject": "[home] item 125", "description": DESC, "status": "open", "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
       "metadata": {"owner": U["home-front"], "project": "projects/alpha", "agent": "home-peer", "next": "home-peer: do the thing"}}      # the linked agent (metadata.agent), no needs
(T / "store/a/125.json").write_text(json.dumps(raw))
loaded = server._load(f"a{125}"); writes.save(f"a{125}", loaded)
check("15 legacy: a server save of an item stored in an older form makes no hand-off out of the conversion (before is read through the same readers as the item)", "handoff" not in mt(125), mt(125))

# 15.15 the cold call's outcome is written only on the record that call was asked about
item(126, mover="home-peer", handoff=rec("home-peer", cold={"at": 4242.0, "state": "running"}))
server._handoff_cold_end(f"a{126}", "failed", "from a call that was asked about an earlier record", 1.0)
check("15 cold end: an outcome with another call's stamp is not written on the record", (ho(126).get("cold") or {}).get("state") == "running" and not ho(126).get("events"), ho(126))
server._handoff_cold_end(f"a{126}", "failed", "the call failed", 4242.0)
check("15 cold end: …the stamp of the call asked about is", (ho(126).get("cold") or {}).get("state") == "failed", ho(126))
item(127, mover="home-peer", handoff=rec("home-peer", cold={"at": 77.0, "state": "running"}))
server._handoff_cold_end(f"a{127}", "done", "no stamp: as before")
check("15 cold end: a call with no stamp writes as before", (ho(127).get("cold") or {}).get("state") == "done", ho(127))

# 15.16 the repair: one item that fails does not stop it; the start-time pass applies it, once, with one count line
item(128, mover="team-back", handoff=rec("home-peer")); item(129, mover="team-back", handoff=rec("home-peer"))
_real_one = server._handoff_repair_one
def _one(gid, p, apply, now):
    if gid == f"a{128}": raise RuntimeError("unreadable on purpose")
    return _real_one(gid, p, apply, now)
server._handoff_repair_one = _one
jr = io.StringIO()
with contextlib.redirect_stderr(jr):
    rows_av = server._handoff_repair()
server._handoff_repair_one = _real_one
check("15 repair: an item whose repair fails is logged and the others go on", f"a{129}" in [r["gid"] for r in rows_av] and f"a{128}" not in [r["gid"] for r in rows_av] and f"a{128} record not repaired: RuntimeError" in jr.getvalue(), (rows_av, jr.getvalue()))
jr = io.StringIO()
with contextlib.redirect_stderr(jr):
    n_pass = server._handoff_repair_pass()
check("15 repair: the start-time pass ends the stale records (here two or more), logs one count line, and a second run finds none (idempotent)",
      n_pass >= 2 and jr.getvalue().count("migrate: hand-off records:") == 1 and "handoff" not in mt(128) and "handoff" not in mt(129) and server._handoff_repair_pass() == 0, (n_pass, jr.getvalue(), mt(128)))
import inspect
src_start = inspect.getsource(server._start_background)
check("15 repair: the pass runs at start, after the mover migrations and before the wake pass and the threads",
      src_start.index("_migrate_owner_mover()") < src_start.index("_mover_backfill_pass()") < src_start.index("_handoff_repair_pass()") < src_start.index("_wake_pass()") < src_start.index("threading.Thread"), None)
set_cfg(handoff=False); item(130, mover="team-back", handoff=rec("home-peer")); n_off = server._handoff_repair_pass(); set_cfg()
check("15 repair: …and not while [model] handoff is false", n_off == 0 and ho(130).get("to") == "home-peer", ho(130))
server._handoff_repair_pass()

# 15.17 the tool: --live --apply is refused while the server runs; --live alone (the dry run) is not
import importlib.util
spec = importlib.util.spec_from_file_location("handoff_repair_tool", os.path.join(STACK, "stackshot", "tools", "handoff_repair.py")); tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
item(131, mover="team-back", handoff=rec("home-peer"))
for label, state in (("active", True), ("unknown", None)):
    tool.service_running = lambda state=state: state
    e_, o_ = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(e_), contextlib.redirect_stdout(o_):
        rc = tool.main(["--live", "--apply"])
    check(f"15 tool: --live --apply is refused while the service is {label}, and writes nothing", rc == 1 and "refused" in e_.getvalue() and "stackshot server" in e_.getvalue() and ho(131).get("to") == "home-peer", (rc, e_.getvalue(), ho(131)))
e_, o_ = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(e_), contextlib.redirect_stdout(o_):
    rc = tool.main(["--live"])
check("15 tool: --live without --apply is a dry run and is allowed while the service runs", rc == 0 and "would end" in o_.getvalue() and ho(131).get("to") == "home-peer", (rc, o_.getvalue()[-300:], e_.getvalue()))
tool.service_running = lambda: False
e_, o_ = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(e_), contextlib.redirect_stdout(o_):
    rc = tool.main(["--live", "--apply"])
check("15 tool: …and --live --apply runs when the service is stopped", rc == 0 and "handoff" not in mt(131), (rc, o_.getvalue()[-300:], e_.getvalue()))

# 15.18 a failed mover reading is not "no mover": the open record is kept, and a line says so
item(150, mover="team-back", handoff=rec("home-peer"))                                  # stale: an open record to someone but the mover
_real_derive = server._ho_derive
def _raising_derive(it): raise RuntimeError("the model could not read this one")
server._ho_derive = _raising_derive
jr = io.StringIO()
with contextlib.redirect_stderr(jr):
    rows_aw = server._handoff_repair(apply=True)
    it_aj = rd(150); it_aj["metadata"]["next"] = "team-back: carry on"; _real_save(f"a{150}", it_aj)          # the server's own save, the reading failing
server._ho_derive = _real_derive
check("15 strict: a repair whose mover reading raises ends nothing, keeps the open record and logs one line per item", f"a{150}" not in [r["gid"] for r in rows_aw] and ho(150).get("to") == "home-peer"
      and "handoff" in mt(150) and not mt(150).get("handoff_history") and f"a{150} record kept: its mover could not be read" in jr.getvalue(), (rows_aw, mt(150), jr.getvalue()[-300:]))
check("15 strict: …and so does the follow step of a save (the record is kept, one line)", f"a{150} record left as it is" in jr.getvalue() and ho(150).get("to") == "home-peer", jr.getvalue()[-300:])
check("15 strict: …handoff.mover_of(strict=True) is None for a failing reading, \"\" for a closed item, and the plain call still says \"\"",
      H.mover_of(rd(150), _raising_derive, strict=True) is None and H.mover_of(rd(150), _raising_derive) == "" and H.mover_of({"status": "completed"}, _raising_derive, strict=True) == "", None)
rows_axb = server._handoff_repair(apply=True)
check("15 strict: …once it reads again the repair ends it as before", f"a{150}" in [r["gid"] for r in rows_axb] and "handoff" not in mt(150), (rows_axb, mt(150)))

# 15.19 a record with the recovery request stays while the item stays with its mover or goes to the owner; a server save that moves it on to another session ends it and records the new mover
item(151, mover="home-peer", handoff=rec("home-peer", recovery_at=now0 - 100, stall=True, recovery_reason="nobody could take it"))
it_ak = rd(151); it_ak["metadata"]["next"] = "home-peer: a line"; writes.save(f"a{151}", it_ak)
check("15 recovery: a server save that leaves the mover alone keeps the record", bool(ho(151).get("recovery_at")) and ho(151).get("to") == "home-peer", mt(151))
it_ak = rd(151); it_ak["metadata"]["mover"] = "team-back"; it_ak["metadata"]["next"] = "team-back: take over"; writes.save(f"a{151}", it_ak)
h_ac = (mt(151).get("handoff_history") or [{}])[-1]
check("15 recovery: …a server save that moves the item to another session ends the record as handed on and records the new mover (no_clock, from the server)",
      ho(151).get("to") == "team-back" and ho(151).get("from") == "stackshot" and ho(151).get("no_clock") is True and not ho(151).get("recovery_at") and h_ac.get("to") == "home-peer" and bool(h_ac.get("recovery_at"))
      and h_ac.get("ended") == "handed on" and not stale_now(151), mt(151))
item(152, mover="home-peer", handoff=rec("home-peer", recovery_at=now0 - 100, stall=True))
it_al = rd(152); it_al["metadata"]["mover"] = "team-back"; it_al["metadata"]["next"] = "team-back: take over"; writes.save(f"a{152}", it_al, writer="home-send")
check("15 recovery: …a session's own write is the session path's, as before (a hand-off record to the new mover through apply)", ho(152).get("to") == "team-back" and not ho(152).get("recovery_at"), mt(152))

# ================================================================ 16. a background agent that did not take a hand-off is reminded first
# A delivered hand-off to a background agent that is not taken in [model] handoff_minutes gets ONE reminder to that session (start its subagent alongside the current work); only when it is
# still not taken after another handoff_minutes does the ladder go on. An anchor scoped to the item counts as taken. Front agents stay exempt; a name that is no background session gets nothing.
set_cfg(cold_call=False); failing(); inbox(); queued(); paused(); clear_pushes()
D16 = now0 - 1000
item(1500, mover="team-back", handoff=rec("team-back", delivered_at=D16))
b9 = tick(D16 + 9 * MIN, 1500); drain()
check("16 remind: nothing at 9 minutes: no step, no push, the record as it was", b9 == [] and not pushes_to("team-back", "a1500") and "reminded_at" not in ho(1500) and ho(1500).get("delivered_at") == D16, (b9, ho(1500)))
cold0 = len(COLD_MSGS)
b11 = tick(D16 + 11 * MIN, 1500); drain()
p1500 = pushes_to("team-back", "a1500")
check("16 remind: at 11 minutes the background agent gets ONE reminder, to its own session, saying to start its subagent alongside the current work",
      b11 == ["a1500"] and len(p1500) == 1 and p1500[0][0] == U["team-back"] and "reminder" in p1500[0][1] and "start its subagent alongside the current work" in p1500[0][1].lower(), (b11, p1500))
check("16 remind: …the item stays with it (no move, no history entry, no sender told, no cold call) and says it was reminded",
      ho(1500).get("to") == "team-back" and mt(1500).get("mover") == "team-back" and not mt(1500).get("handoff_history") and not pushes_to("home-send", "a1500") and len(COLD_MSGS) == cold0
      and isinstance(ho(1500).get("reminded_at"), float) and "its mover was reminded" in got(1500), (ho(1500), pushes()))
check("16 remind: …and the reminder's delivery restarts the clock", isinstance(ho(1500).get("delivered_at"), float) and ho(1500)["delivered_at"] > D16 and not ho(1500).get("queued"), ho(1500))
D2 = ho(1500)["delivered_at"]
cli_row("team-back", "idle", D2 + 5)
a9 = tick(D2 + 9 * MIN, 1500); drain()
check("16 escalate: after the reminder nothing happens before another handoff_minutes, not even for a pane whose turn ended with no write", a9 == [] and len(pushes_to("team-back", "a1500")) == 1 and ho(1500).get("to") == "team-back", (a9, ho(1500)))
(T / f"cli/{os.getpid()}-team-back.json").unlink(missing_ok=True)
a11 = tick(D2 + 11 * MIN, 1500); drain()
check("16 escalate: …after the second handoff_minutes the ladder goes on as before (here no cold call: back to the sender), with no second reminder",
      a11 == ["a1500"] and ho(1500).get("to") == "home-send" and ho(1500).get("via") == "return" and len(pushes_to("team-back", "a1500")) == 1, (a11, ho(1500)))
check("16 escalate: …and the reason says it was a reminder it did not answer", "team-back did not take it in 10 min after a reminder" in got(1500), got(1500))
# a new hand-off of the same item counts again
item(1501, mover="team-back", handoff=rec("team-back", delivered_at=D16, reminded_at=D16 + 700))
hand(1501, "home-peer"); hand(1501, "team-back"); drain()
check("16 remind: a new hand-off of the same item is a new record: it is reminded again after its own clock", "reminded_at" not in ho(1501) and ho(1501).get("to") == "team-back", ho(1501))
n_rem = len(pushes_to("team-back", "a1501")); d_rem = ho(1501)["delivered_at"]
tick(d_rem + 11 * MIN, 1501); drain()
check("16 remind: …and again after its own clock", len(pushes_to("team-back", "a1501")) == n_rem + 1 and "reminded_at" in ho(1501), (n_rem, ho(1501)))
# an anchor scoped to the item counts as taken, for a builder and for anyone else; read once for the whole pass; one scoped to another item changes nothing
item(1502, mover="team-back", handoff=rec("team-back", delivered_at=D16))
item(1503, mover="home-peer", handoff=rec("home-peer", delivered_at=D16))
item(1504, mover="team-back", handoff=rec("team-back", delivered_at=D16))
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://example.test/pr/1", "items": ["a1502", "a1503"], "added": now0, "by": "x"},
                                                                    {"url": "https://example.test/pr/2", "items": None, "added": now0, "by": "x"}]}))
loads = []; _real_load = server._anc.load
def _count_load(*a, **k): loads.append(1); return _real_load(*a, **k)
server._anc.load = _count_load
try:
    n_before = len(pushes())
    ad = tick(D16 + 11 * MIN, 1502, 1503, 1504); drain()
finally:
    server._anc.load = _real_load
check("16 anchor: an item with an anchor scoped to it is neither reminded nor moved on, whether its mover is a background agent or not; an unscoped project anchor changes nothing for the third",
      ad == ["a1504"] and not pushes_to("team-back", "a1502") and "reminded_at" not in ho(1502) and ho(1502).get("to") == "team-back" and ho(1503).get("to") == "home-peer" and not pushes_to("team-back", "a1503")
      and len(pushes_to("team-back", "a1504")) == 1 and "reminded_at" in ho(1504), (ad, ho(1502), ho(1503), ho(1504), pushes()[n_before:]))
check("16 anchor: …the anchors were read once for the pass", len(loads) == 1, loads)
(T / "store/anchors.json").write_text("{}")
# front agents keep their exemption; a record the server made (no_clock) has no clock at all
item(1505, mover="home-front", handoff=rec("home-front", delivered_at=D16))
item(1506, mover="team-back", handoff=rec("team-back", delivered_at=D16, no_clock=True))
fr = tick(D16 + 11 * MIN, 1505, 1506); drain()
check("16 exempt: a front agent is never reminded or moved on, and a no_clock record has no clock", fr == [] and not pushes_to("home-front", "a1505") and not pushes_to("team-back", "a1506") and "reminded_at" not in ho(1505) and "reminded_at" not in ho(1506), (fr, pushes()))
# fail closed: only a live session the role map lists as background (and not retired) is reminded; anything else gets no push, and the ladder is what it was
roles16 = server._anc.session_roles()
tgt = lambda w, roles=roles16: server._handoff_reminder_target(w, roles)
check("16 closed: the target is the background session's id; a front agent, the page's name-line session, an unknown name, the user's own entry, a keeper entry, a retired entry, no role map and an empty name get nothing",
      tgt("team-back") == U["team-back"] and not tgt("home-front") and not tgt("home-stew") and not tgt("nobody-here") and not tgt(model.owner_display()) and not tgt("") and not tgt("team-back", None) and not tgt("team-back", {})
      and not tgt("team-back", {"team-back": {"role": "keeper"}}) and not tgt("team-back", {"team-back": {"role": "back", "retired": True}}) and tgt("team-back", {"team-back": {"role": "back"}}) == U["team-back"],
      [tgt(w) for w in ("team-back", "home-front", "home-stew", "nobody-here")])
item(1507, mover="home-peer", handoff=rec("home-peer", delivered_at=D16))
unk = tick(D16 + 11 * MIN, 1507); drain()
check("16 closed: a mover that is no background session (here a session of no page) is not reminded: the ladder goes on as before", unk == ["a1507"] and not pushes_to("home-peer", "a1507") and "reminded_at" not in ho(1507) and ho(1507).get("to") == "team-back", (unk, ho(1507)))
item(1508, mover="team-back", handoff=rec("team-back", delivered_at=D16))
_real_roles = server._anc.session_roles
def _roles_raise(*a, **k): raise RuntimeError("roles unreadable")
server._anc.session_roles = _roles_raise
try:
    rr = tick(D16 + 11 * MIN, 1508); drain()
finally:
    server._anc.session_roles = _real_roles
check("16 closed: a role map that cannot be read means no push to the mover and no reminder; the ladder goes on", not pushes_to("team-back", "a1508") and "reminded_at" not in ho(1508), (rr, ho(1508), pushes_to("team-back", "a1508")))
# an anchor older than the hand-off says nothing about it; one added since counts
item(1511, mover="team-back", handoff=rec("team-back", delivered_at=D16))
item(1512, mover="team-back", handoff=rec("team-back", delivered_at=D16))
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://example.test/pr/old", "items": ["a1511"], "added": now0 - 7200, "by": "x"},
                                                                    {"url": "https://example.test/pr/new", "items": ["a1512"], "added": now0 - 600, "by": "x"}]}))
od = tick(D16 + 11 * MIN, 1511, 1512); drain()
check("16 anchor: an anchor older than the hand-off (an earlier pull request, one added before the hand-over) does not hide it: reminded; one added since it does", od == ["a1511"] and len(pushes_to("team-back", "a1511")) == 1 and "reminded_at" in ho(1511)
      and not pushes_to("team-back", "a1512") and "reminded_at" not in ho(1512), (od, ho(1511), ho(1512)))
(T / "store/anchors.json").write_text("{}")
# the early idle path: a background agent whose turn ended with no write waits for the clock, so the reminder's minutes are true; anyone else is moved on at once, as before (section 4)
item(1513, mover="team-back", handoff=rec("team-back", delivered_at=D16))
cli_row("team-back", "idle", D16 + 5)
e3 = tick(D16 + 3 * MIN, 1513); drain()
check("16 idle: a background agent whose turn ended with no write is not reminded 3 minutes in: it gets the whole clock", e3 == [] and not pushes_to("team-back", "a1513") and "reminded_at" not in ho(1513), (e3, ho(1513)))
e11 = tick(D16 + 11 * MIN, 1513); drain()
check("16 idle: …and is reminded at the clock, the text saying the minutes that passed", e11 == ["a1513"] and "no work on it has started in 10 min" in pushes_to("team-back", "a1513")[0][1], (e11, pushes_to("team-back", "a1513")))
(T / f"cli/{os.getpid()}-team-back.json").unlink(missing_ok=True)
# several reminders due in one pass for one agent go in one message
item(1514, mover="team-back", handoff=rec("team-back", delivered_at=D16))
item(1515, mover="team-back", handoff=rec("team-back", delivered_at=D16))
bt = tick(D16 + 11 * MIN, 1514, 1515); drain()
pb = [p for p in pushes_to("team-back") if "a1514" in p[1] or "a1515" in p[1]]
check("16 batch: two reminders due in one pass for one agent are one message naming both, and both records are delivered afterwards", sorted(bt) == ["a1514", "a1515"] and len(pb) == 1 and "a1514" in pb[0][1] and "a1515" in pb[0][1] and "2 items" in pb[0][1]
      and isinstance(ho(1514).get("delivered_at"), float) and isinstance(ho(1515).get("delivered_at"), float) and ho(1514)["delivered_at"] > D16 and ho(1515)["delivered_at"] > D16, (bt, pb, ho(1514), ho(1515)))
# a reminder's retry is worded as a reminder, even on a record that was sent again earlier; a resend after a reminder stays a resend
item(1516, mover="team-back", handoff=rec("team-back", delivered_at=D16, resent_at=D16 - 60))
failing("team-back")
tick(D16 + 11 * MIN, 1516); drain()
p16 = pushes_to("team-back", "a1516")
check("16 retry: a reminder whose push is tried once more is worded as a reminder both times, not as a notice sent again after a restart", len(p16) == 2 and all("reminder" in p[1] and "sent again" not in p[1] for p in p16), p16)
failing()
it_ = {"subject": "x", "metadata": {"project": "projects/alpha"}}
check("16 retry: …the later of the two decides: a resend after a reminder is worded as a resend", "reminder" in server._handoff_text("a1", it_, {"reminded_at": 9, "resent_at": 5}, again=True)
      and "sent again" in server._handoff_text("a1", it_, {"reminded_at": 5, "resent_at": 9}, again=True) and "reminder" not in server._handoff_text("a1", it_, {"reminded_at": 5, "resent_at": 9}, again=True), None)
# a reminder's push failing is sent once more and then the ladder goes on (the clock restarts only from a delivery); one that waits in the inbox starts it after the inbox grace
item(1509, mover="team-back", handoff=rec("team-back", delivered_at=D16))
failing("team-back")
tick(D16 + 11 * MIN, 1509); drain()
check("16 push: a reminder whose push fails twice sends the item down the ladder, with no second reminder", len(pushes_to("team-back", "a1509")) == 2 and ho(1509).get("to") != "team-back", (pushes_to("team-back", "a1509"), ho(1509)))
failing()
item(1510, mover="team-back", handoff=rec("team-back", delivered_at=D16))
inbox("team-back")
tick(D16 + 11 * MIN, 1510); drain()
q = ho(1510)
check("16 push: a reminder that waits in the inbox is neither delivered nor failed: the clock restarts from the inbox grace", q.get("delivered_at") is None and q.get("queued_at") and len(pushes_to("team-back", "a1510")) == 1 and q.get("to") == "team-back", q)
w9 = tick(q["queued_at"] + 19 * MIN, 1510); drain()
w11 = tick(q["queued_at"] + 21 * MIN, 1510); drain()
check("16 push: …and nothing is due 19 minutes after it, the ladder 21 minutes after it", w9 == [] and w11 == ["a1510"] and ho(1510).get("to") == "home-send", (w9, w11, ho(1510)))
inbox()
set_cfg()

# ---- 17. the minute pace: the hand-off tick runs once a minute (the runner's pace), so a hand-off that comes due between two ticks is acted on by the next one, at most a
# minute after its deadline, once, and not before
set_cfg(cold_call=False); failing(); inbox(); queued(); paused(); clear_pushes()
D17 = now0 - 3000
item(1700, mover="team-back", handoff=rec("team-back", delivered_at=D17))
m0 = tick(D17 + 10 * MIN - 1, 1700); drain()
m1 = tick(D17 + 10 * MIN + 59, 1700); drain()       # the first tick of a one-minute pace after the 10-minute deadline
m2 = tick(D17 + 10 * MIN + 119, 1700); drain()      # the next minute's tick: the reminder restarted the clock, so nothing again
check("17 minute pace: nothing a second before the deadline, the reminder at the first tick a minute-paced runner makes after it (59 s late), and nothing at the tick after that",
      m0 == [] and m1 == ["a1700"] and m2 == [] and len(pushes_to("team-back", "a1700")) == 1 and "reminded_at" in ho(1700), (m0, m1, m2, ho(1700)))
set_cfg()

# ================================================================ 18. the one ladder ([ladder] enabled): an untaken hand-off and a silent pane share one record and one order
# ask the mover, 30 minutes later look at its pane (no turn running: the notice again), the cold call, the project's builder, then the fleet's builder asked once. The sender rung is gone.
from stackshot.waits import ladder as LD
for p_ in (T / "store/a").glob("*.json"):
    d_ = json.loads(p_.read_text()); d_["status"] = "completed"; p_.write_text(json.dumps(d_))      # earlier sections' items are closed: only this section's are on the board now
for p_ in (T / "cli").glob("*.json"): p_.unlink()
set_cfg(); clear_pushes(); inbox(); failing(); queued(); paused(); cold("no json at all here"); COLD_MSGS.clear()
server._cfg.CFG["stall"] = {}
server._stall_since(now0 - 7200)                   # the stall pass first ran before every clock below
def ladder_cfg(on=True, **kw): server._cfg.CFG["ladder"] = {"enabled": on, "main_hours": 10000, **kw}      # main_hours: a value no scenario reaches; the hand-up of an item that has not moved is tests/ladder_progress_scenario.py's
def stk(at):
    """One stall pass at `at` (its 20-second gate reset), the threads it started finished → the items it acted on."""
    server._STALL_LAST[0] = 0.0
    out = server._stall_tick(at); drain()
    return out
def hot(at, *ids):
    out = tick(at, *ids); drain()
    return out
def entry(i): return (json.loads((T / "state/stall.json").read_text()) if (T / "state/stall.json").exists() else {}).get(f"a{i}")
def slog(i): return [x["text"] for x in ((mt(i).get("stall") or {}).get("log") or [])]
def notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "is handed to you by" in p[1]]
N0 = now0 + 60.0
IDLE17 = now0 - 3000.0                             # the panes went idle then
ladder_cfg(True)

# pure: the ladder's clock
E_ = 1.0e9
rec_ = {"mover": "x", "step": 0, "last": 0.0, "via": "handoff"}
check("18 ladder: an item the hand-off audit brought is asked at once, whatever its pane shows", LD.action(rec_, "busy", E_, 0.0, E_, 10.0) == "ask" and LD.action(rec_, "", 0.0, 0.0, E_, 10.0) == "ask", None)
rec_ = {"mover": "x", "step": 0, "last": 0.0}
check("18 ladder: a silent pane is asked after `minutes` of no turn, not before", LD.action(rec_, "idle", E_, 0.0, E_ + 599.0, 10.0) == "" and LD.action(rec_, "idle", E_, 0.0, E_ + 601.0, 10.0) == "ask", None)
LD.advance(rec_, "ask", E_ + 1000.0)
check("18 ladder: the look comes 30 minutes after the ask, only for an idle pane; a pane with a turn running is left alone", LD.action(rec_, "idle", E_, 0.0, E_ + 1000.0 + 1799.0, 10.0) == ""
      and LD.action(rec_, "busy", E_, 0.0, E_ + 1000.0 + 1801.0, 10.0) == "" and LD.action(rec_, "idle", E_, 0.0, E_ + 1000.0 + 1801.0, 10.0) == "look"
      and LD.action(rec_, "shell", E_, 0.0, E_ + 1000.0 + 1801.0, 10.0) == "look", None)
LD.advance(rec_, "look", E_ + 3000.0)
check("18 ladder: the cold call is 10 minutes after the look", LD.action(rec_, "idle", E_, 0.0, E_ + 3000.0 + 599.0, 10.0) == "" and LD.action(rec_, "idle", E_, 0.0, E_ + 3000.0 + 601.0, 10.0) == "cold", None)
LD.advance(rec_, "cold", E_ + 3700.0)
check("18 ladder: the builder is 10 minutes after the cold call", LD.action(rec_, "idle", E_, 0.0, E_ + 3700.0 + 601.0, 10.0) == "builder" and LD.action(rec_, "idle", E_, 0.0, E_ + 3700.0 + 599.0, 10.0) == "", None)
LD.advance(rec_, "builder", E_ + 4400.0)
check("18 ladder: past the last rung there is nothing to do; the order is ask, look, cold, builder", LD.action(rec_, "idle", E_, 0.0, 9e9, 10.0) == "" and LD.RUNGS == ("ask", "look", "cold", "builder"), LD.RUNGS)
check("18 ladder: a mover whose pane is gone starts at the cold call, with no pane to wait for", LD.action(LD.enter(None, "x", [1.0, 1.0], 0.0, gone=True), "", 0.0, 0.0, E_, 10.0) == "cold", None)

# A. the whole ladder on an untaken hand-off: ask at the hand-off audit's due time, look at +30, cold at +40 (it gives nothing: the builder at once), no return to the sender
item(1800, mover="home-peer", handoff=rec("home-peer")); cli_row("home-peer", "idle", IDLE17)
done = hot(N0, 1800)
e = entry(1800) or {}
check("18 A ask: a delivered hand-off not taken in 10 minutes: the mover gets the hand-off's own notice once more (not a reminder, not the stall wording), the item stays with it",
      done == ["a1800"] and len(notices("home-peer", 1800)) == 1 and "reminder" not in notices("home-peer", 1800)[0][1] and "no turn running" not in notices("home-peer", 1800)[0][1]
      and mt(1800)["mover"] == "home-peer" and ho(1800).get("to") == "home-peer" and not pushes_to("team-back", "a1800") and not COLD_MSGS, (done, pushes(), mt(1800)))
check("18 A ask: …ONE record: the item's entry in stall.json carries who brought it (the hand-off audit) and the rung taken; the hand-off record has no second ladder of its own",
      e.get("via") == "handoff" and e.get("step") == 1 and e.get("last") == N0 and not ho(1800).get("reminded_at") and not ho(1800).get("recovery_at") and len(slog(1800)) == 1 and "has not taken it" in slog(1800)[0], (e, ho(1800), slog(1800)))
check("18 A ask: …the hand-off audit leaves it on the next ticks, and the silence audit does not start a second ladder on the untaken hand-off: still one notice, one entry",
      hot(N0 + 2 * MIN, 1800) == [] and stk(N0 + 2 * MIN) == [] and hot(N0 + 9 * MIN, 1800) == [] and stk(N0 + 12 * MIN) == [] and len(notices("home-peer", 1800)) == 1 and entry(1800).get("step") == 1, (pushes_to("home-peer"), entry(1800)))
check("18 A look: 29 minutes after the ask, nothing", stk(N0 + 29 * MIN) == [] and len(notices("home-peer", 1800)) == 1, pushes_to("home-peer"))
done = stk(N0 + 31 * MIN)
check("18 A look: 31 minutes after it, the pane has no turn running: the notice goes again", done == ["a1800"] and len(notices("home-peer", 1800)) == 2 and entry(1800).get("step") == 2 and not COLD_MSGS, (done, pushes_to("home-peer"), entry(1800)))
check("18 A cold: 9 minutes after the look, nothing", stk(N0 + 40 * MIN) == [] and not COLD_MSGS, COLD_MSGS)
done = stk(N0 + 41 * MIN + 1)
r_ = ho(1800)
check("18 A cold: 10 minutes after the look, the cold call is asked; it gave nothing, so the item goes on at once to the project's builder", "a1800" in done and len(COLD_MSGS) == 1 and mt(1800)["mover"] == "team-back" and r_.get("to") == "team-back"
      and r_.get("via") == "redirect" and (r_.get("cold") or {}).get("state") == "failed", (done, mt(1800), r_))
check("18 A builder: …the item did not go back to its sender: no message put it to home-send as its owner, and nothing was asked of the fleet's builder", not [p for p in pushes_to("home-send", "a1800") if "comes back to you" in p[1]]
      and not [p for p in pushes() if "comes back to you" in p[1]] and not recovery_pushes("a1800") and len(pushes_to("team-back", "a1800")) >= 1, pushes())
check("18 A: the History lines read in the ladder's order: the ask, the look, the cold call, the builder", [("has not taken it" in x) for x in slog(1800)[:2]] == [True, True] and "cold call was asked" in slog(1800)[2] and "to the builder" in slog(1800)[3], slog(1800))
close_ = lambda *ids: [ (lambda d: (d.update(status="completed"), (T / f"store/a/{i}.json").write_text(json.dumps(d))))(rd(i)) for i in ids ]
close_(1800)

# B. a pane with a turn running at the look is left alone; the look comes when it is idle
item(1801, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "busy", IDLE17)
hot(N0, 1801)
check("18 B: a hand-off to a busy pane is still asked at the audit's due time", len(notices("home-peer2", 1801)) == 1 and entry(1801).get("step") == 1, (pushes_to("home-peer2"), entry(1801)))
check("18 B look: 35 minutes on and the pane has a turn running: nothing is sent", stk(N0 + 35 * MIN) == [] and len(notices("home-peer2", 1801)) == 1, pushes_to("home-peer2"))
cli_row("home-peer2", "idle", N0 + 36 * MIN)
check("18 B look: the turn ends and the pane is idle: the look sends the notice again at once (the 30 minutes after the ask are already over)", stk(N0 + 37 * MIN) == ["a1801"] and len(notices("home-peer2", 1801)) == 2, pushes_to("home-peer2"))
close_(1801)

# C. a mover whose pane is gone has nothing to ask: the ladder starts at the cold call
COLD_MSGS.clear()
item(1802, mover="home-dead", handoff=rec("home-dead"));
done = hot(N0, 1802)
check("18 C gone: the cold call is asked at once and nothing is sent to the gone session; it gave nothing, so the project's builder has the item and the sender gets no return",
      "a1802" in done and len(COLD_MSGS) == 1 and not pushes_to("home-dead", "a1802") and mt(1802)["mover"] == "team-back" and ho(1802).get("via") == "redirect" and not recovery_pushes("a1802"), (done, mt(1802), pushes()))
close_(1802)

# D. nobody to take it: the last rung asks the project's -main agent once (the fleet's builder when the project has a builder); the item stays with its mover; the owner is not asked
set_cfg(cold_call=False); COLD_MSGS.clear()
item(1803, project="projects/beta", mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1803); stk(N0 + 31 * MIN)
check("18 D: ask, then look: two notices and no recovery request yet", len(notices("home-peer2", 1803)) == 2 and not main_recovery_pushes("a1803"), pushes_to("home-peer2"))
done = stk(N0 + 41 * MIN + 1)
check("18 D last: the cold call is off, the project lists no builder: ONE message asks its -main agent to decide; the item stays with its mover and is not put to the owner",
      "a1803" in done and len(main_recovery_pushes("a1803")) == 1 and mt(1803)["mover"] == "home-peer2" and ho(1803).get("recovery_at") and "decision" not in (mt(1803).get("needs") or []) and not mt(1803).get("ask"), (done, main_recovery_pushes("a1803"), mt(1803)))
check("18 D last: …and later passes send nothing more", stk(N0 + 3 * 3600) == [] and hot(N0 + 3 * 3600, 1803) == [] and len(main_recovery_pushes("a1803")) == 1, main_recovery_pushes("a1803"))
close_(1803); set_cfg()

# E. two failed pushes: the ask cannot reach the mover, the ladder starts at the cold call
COLD_MSGS.clear()
item(1804, mover="home-peer", handoff=rec("home-peer", delivered_at=None, attempts=2, queued_at=None)); cli_row("home-peer", "idle", IDLE17)
r_ = server._handoff_fallback("a1804", "a push to home-peer failed twice"); drain()
check("18 E: a push that failed twice starts the ladder at the cold call, with no ask", len(COLD_MSGS) == 1 and not notices("home-peer", 1804) and mt(1804)["mover"] == "team-back", (COLD_MSGS, mt(1804)))
close_(1804)

# F. the mover starting work ends the ladder: taken, and the next rung never comes
COLD_MSGS.clear()
item(1805, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1805)
start(1805, "home-peer2", goal="on it"); drain()
n_ = len(pushes_to("home-peer2", "a1805"))
stk(N0 + 31 * MIN); hot(N0 + 31 * MIN, 1805)
later_ = pushes_to("home-peer2", "a1805")[n_:]
check("18 F: the mover starts work on the item: the hand-off is taken, the entry is no longer the hand-off audit's, and the look never comes: whatever the silence audit then sends is in its own wording, never the hand-off notice again",
      ho(1805).get("taken_at") and (entry(1805) or {}).get("via") != "handoff" and len(notices("home-peer2", 1805)) == 1 and all("is handed to you by" not in p[1] for p in later_) and not COLD_MSGS
      and all("no turn running" in p[1] for p in later_), (ho(1805), entry(1805), pushes_to("home-peer2", "a1805")))
close_(1805)

# H. someone other than the mover writes to the item in the middle of the ladder: that restarts the episode, but the item stays on the ladder and the ask is not sent a second time
COLD_MSGS.clear()
item(1809, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1809)
upd(1809, "home-send", goal="more detail for whoever takes it"); drain()
a_, b_ = stk(N0 + 5 * MIN), hot(N0 + 6 * MIN, 1809)
check("18 H write: the sender writes after the ask: the silence audit sends no second notice at once and the hand-off audit does not bring the item again (one notice, no stall wording)",
      a_ == [] and b_ == [] and len(pushes_to("home-peer2", "a1809")) == 1 and len(notices("home-peer2", 1809)) == 1, (a_, b_, pushes_to("home-peer2", "a1809")))
e_ = entry(1809) or {}
check("18 H write: …the entry is the same ladder's: still the hand-off audit's (`via`), on the look, counted from the ask", e_.get("via") == "handoff" and e_.get("step") == 1 and e_.get("last") == N0, e_)
check("18 H write: …the look comes 30 minutes after the ask as it would have: nothing at 29, the notice again after", stk(N0 + 29 * MIN) == [] and len(notices("home-peer2", 1809)) == 1
      and stk(N0 + 40 * MIN) == ["a1809"] and len(notices("home-peer2", 1809)) == 2 and entry(1809).get("step") == 2, (pushes_to("home-peer2", "a1809"), entry(1809)))
p_ = LD.episode
same_ = lambda a, b: a == b
r0_ = {"mover": "x", "ver": [1.0, 1.0], "conf": 0.0, "step": 1, "last": 5.0, "via": "handoff"}
w_ = p_(r0_, "x", [2.0, 2.0], same_, 0.0, 0.0)
check("18 H pure: a write (a new version) keeps the mover, the hand-off audit's mark and the rung taken; a taken hand-off, a new mover or an entry the silence audit made starts over as before",
      w_ is not r0_ and w_["via"] == "handoff" and w_["step"] == 1 and w_["last"] == 5.0 and w_["ver"] == [2.0, 2.0] and "via" not in p_(r0_, "x", [2.0, 2.0], same_, 0.0, None)
      and "via" not in p_(r0_, "y", [2.0, 2.0], same_, 0.0, 0.0) and "via" not in p_({**r0_, "via": "stall"}, "x", [2.0, 2.0], same_, 0.0, 0.0) and p_(r0_, "x", [1.0, 1.0], same_, 0.0, 0.0) is r0_, w_)
g_ = p_(LD.enter(None, "x", [1.0, 1.0], 0.0, gone=True), "x", [2.0, 2.0], same_, 0.0, 0.0)
check("18 H pure: a gone mover's entry stays at the cold call after a write", g_["via"] == "handoff" and g_.get("gone") and g_["step"] == LD.RUNGS.index("cold"), g_)
close_(1809)

# I. the mover's confirms: at most stall.RESTARTS of them hold the ladder off, and bringing the item to the ladder again does not give them back
COLD_MSGS.clear()
item(1810, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1810)
for k_ in range(1, 6):
    d_ = rd(1810); d_["confirmed"] = N0 + k_ * 30.0; d_["written_by"] = "home-peer2"; (T / "store/a/1810.json").write_text(json.dumps(d_))
    stk(N0 + k_ * 30.0 + 5); hot(N0 + k_ * 30.0 + 6, 1810)
e_ = entry(1810) or {}
check("18 I confirms (pins the stall pass and the pure functions with `confirmed` stamped straight into the item file, as the stall tests do; a real confirm is no start, see 18 N): five confirms by the mover: still one notice, the item stays on the ladder, and only three of them restarted it (the fourth is adopted without a restart)",
      len(pushes_to("home-peer2", "a1810")) == 1 and e_.get("via") == "handoff" and e_.get("restarts") == 3 and e_.get("capped") and e_.get("step") == 1, (pushes_to("home-peer2", "a1810"), e_))
re_ = LD.enter({"mover": "x", "ver": [1.0, 1.0], "restarts": 3, "capped": True, "conf": 9.0}, "x", [1.0, 1.0], 9.0)
check("18 I confirms: pure: bringing the item to the ladder again at the same version keeps the count; a new version (a write) starts it over", re_["restarts"] == 3 and re_.get("capped")
      and not LD.enter({"mover": "x", "ver": [1.0, 1.0], "restarts": 3}, "x", [2.0, 2.0], 9.0).get("restarts"), re_)
close_(1810)

# L. the item goes B -> A -> B within the day: the second hand-off to B is a new one, with the ask and the clock of its own (the entry B had belongs to the first)
COLD_MSGS.clear()
item(1812, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17); cli_row("home-peer", "idle", IDLE17)
hot(N0, 1812)
at1_ = ho(1812)["at"]
hand(1812, "home-peer", sender="home-front"); drain()
hand(1812, "home-peer2", sender="home-front"); drain()
at2_ = ho(1812)["at"]
n_ = len(notices("home-peer2", 1812))
done = hot(N0 + 15 * MIN, 1812)
e_ = entry(1812) or {}
check("18 L back to B: the second hand-off to the same mover is asked once when it is due, like any other (the first one's entry is not its ladder)",
      at2_ != at1_ and done == ["a1812"] and len(notices("home-peer2", 1812)) == n_ + 1, (at1_, at2_, done, pushes_to("home-peer2", "a1812")))
check("18 L back to B: …and its entry is for the new hand-off, asked now, on the look", e_.get("via") == "handoff" and e_.get("ho_at") == at2_ and e_.get("step") == 1 and e_.get("last") == N0 + 15 * MIN, e_)
r1_ = {"mover": "x", "ver": [1.0, 1.0], "step": 3, "last": 5.0, "via": "handoff", "ho_at": 10.0, "gone": True}
check("18 L pure: an entry is kept through a restart, and counts as the ladder, only for the hand-off it was made for",
      LD.on_ladder(r1_, 6.0, 10.0) and not LD.on_ladder(r1_, 6.0, 11.0) and LD.on_ladder(r1_, 6.0) and LD.episode(r1_, "x", [2.0, 2.0], lambda a, b: a == b, 0.0, 10.0)["via"] == "handoff"
      and "via" not in LD.episode(r1_, "x", [2.0, 2.0], lambda a, b: a == b, 0.0, 11.0) and LD.enter(None, "x", [1.0, 1.0], 0.0, at=12.0)["ho_at"] == 12.0, None)
close_(1812)

# M. the hand-off audit brings an untaken hand-off to the ladder while the stall pass is running: the pass's own save keeps that entry
COLD_MSGS.clear()
item(1813, mover="home-peer"); cli_row("home-peer", "idle", IDLE17)
item(1814, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
orig_status_ = server._handoff_status
def inter_(who, idx):
    server._handoff_status = orig_status_
    tick(N0 + 12 * MIN, 1814)                      # the hand-off audit brings item 1814 to the ladder in the middle of the pass (as the push-failure fallback thread does)
    return orig_status_(who, idx)
server._handoff_status = inter_
try:
    out_ = stk(N0 + 12 * MIN)
finally:
    server._handoff_status = orig_status_
check("18 M while the pass runs: the entry the hand-off audit made in the middle of the pass is still there after the pass's save, and the item is asked once", "a1813" in out_ and (entry(1814) or {}).get("via") == "handoff"
      and len(notices("home-peer2", 1814)) == 1, (out_, entry(1814), pushes_to("home-peer2", "a1814")))
n_ = len(notices("home-peer2", 1814))
check("18 M while the pass runs: …so the next hand-off tick does not bring it again and ask twice", hot(N0 + 13 * MIN, 1814) == [] and stk(N0 + 14 * MIN) in ([], ["a1813"]) and len(notices("home-peer2", 1814)) == n_, (pushes_to("home-peer2", "a1814"), entry(1814)))
close_(1813, 1814)

# N. a real confirm by the mover (the tool) is no start; the start then takes the hand-off, so the ladder ends; the silence audit may read the quiet pane afresh, in its own wording
COLD_MSGS.clear()
item(1815, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1815)
server.stackshot_confirm("a1815", sender="home-peer2"); drain()
check("18 N real confirm: …a confirm alone is no start: the hand-off stays untaken", not ho(1815).get("taken_at"), ho(1815))
start(1815, "home-peer2"); drain()
n_ = len(pushes_to("home-peer2", "a1815"))
stk(N0 + 40 * MIN); hot(N0 + 40 * MIN, 1815)
later_ = pushes_to("home-peer2", "a1815")[n_:]
check("18 N real confirm: the confirm, then the start, takes the hand-off; the entry is no longer the hand-off audit's; no hand-off notice comes again, nothing is asked of the cold call, and what the silence audit sends is in its own wording",
      isinstance(ho(1815).get("taken_at"), float) and (entry(1815) or {}).get("via") != "handoff" and len(notices("home-peer2", 1815)) == 1 and all("is handed to you by" not in p[1] for p in later_)
      and all("no turn running" in p[1] for p in later_) and not COLD_MSGS, (ho(1815), entry(1815), pushes_to("home-peer2", "a1815")))
close_(1815)

# J. the later rungs belong to the stall pass: while it is paused ([model] handoff off) the ladder waits, and goes on when the pass runs again
COLD_MSGS.clear()
item(1811, mover="home-peer2", handoff=rec("home-peer2")); cli_row("home-peer2", "idle", IDLE17)
hot(N0, 1811)
set_cfg(handoff=False)
check("18 J paused: while the stall pass is off nothing is sent at the look time", stk(N0 + 40 * MIN) == [] and len(notices("home-peer2", 1811)) == 1, pushes_to("home-peer2", "a1811"))
set_cfg()
check("18 J paused: …and the look is sent when it runs again", stk(N0 + 41 * MIN) == ["a1811"] and len(notices("home-peer2", 1811)) == 2, pushes_to("home-peer2", "a1811"))
close_(1811)

# K. pure: the plan leaves an item the ladder has (a mutation that drops the skip adds an `enter` step here)
envL_ = H.Env(**{**env.__dict__, "now": 200.0 + 601, "ladder": True})
check("18 K plan: with the ladder on a due hand-off is brought to it; one already on it is left alone", [s_.kind for s_ in H.plan({"g1": pitem}, envL_)] == ["enter"]
      and H.plan({"g1": pitem}, H.Env(**{**envL_.__dict__, "laddered": lambda g, w, at: True})) == [], [s_.kind for s_ in H.plan({"g1": pitem}, envL_)])

# G. the flag off (the default, and a flag flipped back): the hand-off ladder as it was, on its own record
ladder_cfg(False)
COLD_MSGS.clear()
item(1806, mover="home-peer", handoff=rec("home-peer")); cli_row("home-peer", "idle", IDLE17)
done = hot(N0, 1806)
check("18 G off: a due hand-off goes down the old ladder: the project's builder first, the sender told, no entry for the one ladder", done == ["a1806"] and mt(1806)["mover"] == "team-back" and entry(1806) is None
      and [p for p in pushes_to("home-send", "a1806") if "not taken" in p[1]], (done, mt(1806), entry(1806)))
close_(1806)
del server._cfg.CFG["ladder"]
item(1807, mover="home-peer", handoff=rec("home-peer")); cli_row("home-peer", "idle", IDLE17)
done = hot(N0, 1807)
check("18 G off: with no [ladder] section at all it is the same (the default is off)", done == ["a1807"] and mt(1807)["mover"] == "team-back" and entry(1807) is None and not server._ladder_on(), (done, mt(1807)))
close_(1807)
ladder_cfg(True)
item(1808, mover="home-peer", handoff=rec("home-peer")); cli_row("home-peer", "idle", IDLE17)
hot(N0, 1808); ladder_cfg(False)
done = hot(N0 + 11 * MIN, 1808)
check("18 G off: a flag turned off mid-ladder gives the item back to the old ladder, which acts on it (the builder)", done == ["a1808"] and mt(1808)["mover"] == "team-back", (done, mt(1808), entry(1808)))
close_(1808); ladder_cfg(True); cli_row("home-peer", "idle", IDLE17)

check("15 every save of the run: no OPEN record named someone but the item's mover (a wrapper on writes.save, all sections)", INV_SAVES[0] > 100 and not INV_BAD, (INV_SAVES[0], INV_BAD[:4]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
