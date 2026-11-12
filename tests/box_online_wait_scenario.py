"""Scenario test for the event wait `box_online <machine>` (event_waits.py, server._evwait_box_poll) — fixture data, no live store, no network, no server socket.

An item whose mover waits for an offline machine used to park on a dated backstop and sit there after the machine was back. The wait names the machine; the server reads the machine's puller
check-ins itself (liveness.puller_online) and turns the item to its post-wake mover on the first pass after the machine is online. Covered:

  * the pure half: the phrase (one machine, nothing else), its canonical text and words, what matches (the machine, case ignored), the arrival line, that it is live, that a machine cannot report it.
  * the write: a machine offline now is accepted and stored under its fleet name (a hostname resolves to it); an unknown machine is refused naming the machines the fleet knows; a machine that is online
    now is refused (the precedent of a PR already merged: there is nothing to wait for); a create takes the same gate; the reply says what is watched.
  * the wake: while the machine is offline the pass turns nothing; when its puller checks in again the next pass turns every item waiting for it to its post-wake mover, writes the History line, and tells
    the mover once; a wait on another machine stays.
  * the backstop: a machine that never returns leaves the wait open (the stall pass does not run for it) until the backstop day, when the item comes back saying the event did not come.
  * the tool text names the kind.

    tests/run-suite box_online_wait      → exit 0 / 1"""
import asyncio, datetime, json, os, re, sys, pathlib, time, logging
BID_A = 9210
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="boxonwait-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/clients", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n\n## Current state\n\nthe state.\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
# the fleet: box-a is online, box-b was online hours ago, box-c is named in the fleet's names table and has never checked in
(T / "names.tsv").write_text("host-a\tbox-a\ta\nhost-b\tbox-b\tb\nhost-c\tbox-c\tc\n")
def iso(ts): return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
PULLERS = {"host-a": now0 - 30.0, "host-b": now0 - 3 * 3600.0}
def write_state():
    PULLERS["host-a"] = time.time() - 30.0      # box-a keeps checking in, however long the suite takes
    ms = {h: {"letter": {"host-a": "b", "host-b": "d"}[h], "fleet": {"host-a": "box-a", "host-b": "box-b"}[h], "first": iso(now0 - 9 * DAY), "puller": iso(t), "online_since": iso(t - 600)} for h, t in PULLERS.items()}
    (T / "state/clients/state.json").write_text(json.dumps({"machines": ms, "sessions": {}}))
write_state()
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, subject=None, project="projects/alpha", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.service import writes; from stackshot.model import model; from stackshot.waits import watchers as wk; from stackshot.waits import event_waits as EW; from stackshot.waits import stall as S; from stackshot.web import itempage; from stackshot.service import create as create_svc
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
SENT: list[tuple[str, str, str, str]] = []
server._tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
NOTES: list[tuple[str, str]] = []
_real_save = writes.save
def spy_save(gid, item, writer="", note="", *a, **kw):
    if note: NOTES.append((gid, note))
    return _real_save(gid, item, writer, note, *a, **kw)
writes.save = spy_save
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, FRONT = "team-back", "home-front"
UB = U["team-back"]
CFG = server._cfg.CFG.setdefault("model", {})
CFG.update(guards=False, watchers=True, pause=False)
def sent(tag=None): return [x for x in SENT if tag is None or x[3] == tag]
def reset(): SENT.clear(); NOTES.clear()

# ================================================================ the pure half
P = EW.parse
check("parse: one machine, the case kept, the canonical text and the words", P("box_online box-b") == EW.Spec("box_online", "", "box-b") and P("BOX_ONLINE  Box-B").machine == "Box-B"
      and EW.text(P("box_online box-b")) == "box_online box-b" and EW.words("box_online box-b") == "box-b coming online", [P("box_online box-b")])
for bad in ("box_online", "box_online a b", "box_online -x", "box_online a/b"):
    check(f"parse: {bad!r} is refused with the form", EW.problem(bad) != "" and "box_online <machine>" in EW.problem(bad), EW.problem(bad))
ev = EW.event
check("match: the machine decides, the case is ignored; no other kind of event matches", EW.matches(P("box_online box-b"), ev("box_online", machine="BOX-B")) and not EW.matches(P("box_online box-b"), ev("box_online", machine="box-a"))
      and not EW.matches(P("box_online box-b"), ev("recycle", machine="box-b")) and not EW.matches(P("recycle box-b"), ev("box_online", machine="box-b")), None)
check("arrival: the event's own words, else a plain line; the kind is live; a machine cannot report it", EW.arrival(ev("box_online", machine="box-b")) == "box-b is online" and EW.live(P("box_online box-b"))
      and "box_online <machine>" in EW.FORMS and "box_online" not in EW.REPORTED, None)
try:
    EW.event_from_report({"kind": "box_online", "machine": "box-b"}); rep_ok = False
except EW.EventWaitError as e:
    rep_ok = "kind is one of" in str(e)
check("report: client.py event refuses box_online (the server reads it itself)", rep_ok is True, rep_ok)
W = lambda **m: {"status": "open", "metadata": {"wait_kind": "event", **m}}
check("watchers: a box_online wait with a backstop is watched; without one it is not", wk.watches(W(wait_event="box_online box-b", ask_by=day(3))) and not wk.watches(W(wait_event="box_online box-b")), None)

# ================================================================ the write
item(10, mover=BACK, subject="[home] doing, will wait for box-b")
out = server._update("a10", sender=BACK, wait_kind="event", wait_event="box_online host-b", ask_by=day(5), post_wake_mover=BACK, mover="none")
check("write: a machine offline now is accepted, stored under its fleet name (a hostname resolves), and the reply says what the server watches",
      mt(10).get("wait_kind") == "event" and mt(10).get("wait_event") == "box_online box-b" and "event wait: the server watches for box-b coming online" in out and "Nothing tells the server" not in out, (mt(10), out[-500:]))
check("write: ...the wait is stamped (watch.set_at)", (mt(10).get("watch") or {}).get("set_at"), mt(10))
item(11, mover=BACK, subject="[home] doing, will wait for box-c")
server._update("a11", sender=BACK, wait_kind="event", wait_event="BOX_ONLINE Box-C", ask_by=day(5), post_wake_mover=BACK, mover="none")
check("write: a machine in the names table that has never checked in is known, and offline: the wait is accepted", mt(11).get("wait_event") == "box_online box-c", mt(11))
item(12, mover=BACK, subject="[home] doing, will try the wrong machine")
refused("write: an unknown machine is refused, naming the machines the fleet knows", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online box-zz", ask_by=day(5), post_wake_mover=BACK, mover="none"),
        "'box-zz' is not one", "box-a, box-b, box-c")
refused("write: ...a phrase with no machine is refused with the form", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online", ask_by=day(5), post_wake_mover=BACK, mover="none"), "box_online <machine>")
refused("write: a machine that is online now is refused: there is nothing to wait for (as for a PR already merged)", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online box-a", ask_by=day(5), post_wake_mover=BACK, mover="none"),
        "box-a is online now", "nothing to wait for", "last checked in at", "the same write is accepted once 10 minutes have passed", "after ")
try:
    server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online box-a", ask_by=day(5), post_wake_mover=BACK, mover="none"); why = ""
except Exception as e:
    why = str(e)
m_seen = re.search(r"last checked in at (\d{4}-\d\d-\d\d \d\d:\d\d) (\S+)\)", why); m_after = re.search(r"that check-in, that is after (\d{4}-\d\d-\d\d \d\d:\d\d) (\S+);", why)
_tfmt = lambda t: datetime.datetime.fromtimestamp(t, server.ZONE).strftime("%Y-%m-%d %H:%M")
_seen_ts = server._lv.ts(json.loads((T / "state/clients/state.json").read_text())["machines"]["host-a"]["puller"])
check("write: ...the refusal says when the machine last checked in and the time after which the same write is accepted (check-in + online_minutes), in the instance zone, and no UTC beside it",
      m_seen and m_after and m_seen.group(1) == _tfmt(_seen_ts) and m_after.group(1) == _tfmt(_seen_ts + 600) and m_seen.group(2) == m_after.group(2) == server._cfg.tz_abbr() and "UTC" not in why, why)
check("write: ...a refused write leaves the item as it was", "wait_kind" not in mt(12) and mt(12).get("mover") == BACK, mt(12))
refused("write: ...and the hostname of an online machine is refused the same way", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online host-a", ask_by=day(5), post_wake_mover=BACK, mover="none"), "box-a is online now")
# two records of one fleet name: the newest check-in speaks for the machine, whichever the file lists first
def state_with(ms): (T / "state/clients/state.json").write_text(json.dumps({"machines": ms, "sessions": {}}))
_fresh = {"letter": "d", "fleet": "box-b", "first": iso(now0 - 9 * DAY), "puller": iso(time.time() - 30.0)}
_stale = {"letter": "e", "fleet": "box-b", "first": iso(now0 - 9 * DAY), "puller": iso(now0 - 3 * 3600.0)}
for order, ms in (("stale first", {"host-b-old": _stale, "host-b": _fresh}), ("fresh first", {"host-b": _fresh, "host-b-old": _stale})):
    state_with(ms)
    bx = server._evw_boxes()
    check(f"duplicates ({order}): the record with the newest check-in speaks for the fleet name, under the fleet name and under both hostnames", all(bx[k][1] == _fresh for k in ("box-b", "host-b", "host-b-old")), bx.get("box-b"))
    refused(f"duplicates ({order}): so a wait on that machine is refused as online, not accepted on the stale record", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online box-b", ask_by=day(5), post_wake_mover=BACK, mover="none"), "box-b is online now")
# a clients state that is not a table of records knows no machine and never raises out of the write
for label, ms in (("a machine record that is not a dict", {"host-b": "garbage", "host-a": 7, "host-x": None}), ("machines that is not a dict", ["host-b"]), ("machines that is a string", "host-b")):
    state_with(ms)
    try:
        bx = server._evw_boxes(); ok = {f for f, _r in bx.values()} == {"box-a", "box-b", "box-c"} and all(r == {} for _f, r in bx.values())
    except Exception as e:
        bx, ok = f"{e.__class__.__name__}: {e}", False
    check(f"non-dict state ({label}): no machine is known from it, the names table still is, and nothing raises", ok, bx)
state_with(["host-b"])
check("non-dict state: ...a wait on a machine of the names table is accepted (offline), not an error", server._evw_box_spec(EW.parse("box_online box-b")).machine == "box-b", None)
write_state()
refused("write: the backstop is still required to be after now", lambda: server._update("a12", sender=BACK, wait_kind="event", wait_event="box_online box-b", ask_by=day(0), post_wake_mover=BACK, mover="none"), "is not after now")
server._update("a10", sender=BACK, next="team-back: keep going")
check("write: an unrelated update keeps the wait (the gate reads only a changed wait)", mt(10).get("wait_event") == "box_online box-b", mt(10))
try:
    g, cout = create_svc.create_item(subject="[home] filed waiting on box-b", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: nothing until box-b is back", goal="Done when box-b ran it.",
                                  wait_kind="event", wait_event="box_online box-b", ask_by=day(4), post_wake_mover=BACK, mover="none", request_id="boxon-create-1")
except Exception as e:
    g, cout = None, f"ERR {e}"
check("create: an item can be filed already waiting on a machine, the gate the same", g and server._load(g)["metadata"].get("wait_event") == "box_online box-b" and "event wait:" in cout, cout[-400:])
refused("create: ...and a create for a machine online now is refused", lambda: create_svc.create_item(subject="[home] filed waiting on box-a", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: nothing",
        goal="Done when box-a ran it.", wait_kind="event", wait_event="box_online box-a", ask_by=day(4), post_wake_mover=BACK, mover="none", request_id="boxon-create-2"), "box-a is online now")

# ================================================================ the model reads it as waiting, and the stall pass leaves it alone
m10 = server._model_of({**rd(10), "gid": "a10"})
check("model: the stored wait is waiting, with no mover, the event and its post-wake mover; the stall pass has no work to look at", m10.state == model.WAITING and m10.wait.event == "box_online box-b" and m10.wait.post_wake_mover == BACK
      and not m10.mover and S.not_due({**rd(10), "gid": "a10"}, now0) != "", (m10.state, m10.wait, S.not_due({**rd(10), "gid": "a10"}, now0)))
check("display: the item page says what it waits on and the until word (its backstop day is stored as until)", itempage.wait_what(m10.wait) == "box-b coming online" and itempage.wait_end_label(m10.wait) == "until", itempage.wait_what(m10.wait))

# ================================================================ the wake
for i in (20, 21, 22, 23):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(20, wait_kind="event", wait_event="box_online box-b", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for box-b (one)")
item(21, wait_kind="event", wait_event="box_online box-b", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for box-b (two)")
item(22, wait_kind="event", wait_event="box_online box-c", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for box-c, which stays away")
reset()
check("wake: while box-b is offline the pass turns nothing, however often it runs", server._evwait_poll(now0) == [] and server._evwait_poll(now0 + 60) == [] and mt(20).get("wait_kind") == "event" and not sent(), (mt(20), sent()))
server._EVW_LAST[0] = 0.0
check("wake: ...the runner's tick is the same pass", server._evwait_tick() == [], None)
PULLERS["host-b"] = time.time(); write_state()          # box-b's puller checks in again
reset()
server._EVW_LAST[0] = 0.0
fired = server._evwait_tick()
check("wake: the first pass after the puller checks in turns every item waiting for that machine to its post-wake mover; another machine's wait stays",
      {"a20", "a21", "a10"} <= set(fired) and "a22" not in fired and mt(20).get("mover") == BACK and mt(21).get("mover") == BACK and "wait_kind" not in mt(20) and mt(22).get("wait_kind") == "event", (fired, mt(20), mt(22)))
check("wake: ...with what arrived recorded on the item (woke) and the History line the server writes", "box-b is online again" in mt(20)["woke"]["what"]
      and any(g == "a20" and n.startswith("woke: box-b is online again") for g, n in NOTES), (mt(20).get("woke"), NOTES))
check("wake: ...the mover is told once, in one message that names the items", len([x for x in sent("watch") if x[1] == UB]) == 1 and {"a20", "a21"} <= {g for x in sent("watch") for g in x[0].split(",")}
      and "box-b is online again" in sent("watch")[0][2], sent())
reset()
check("wake: ...the next pass does nothing more", server._evwait_poll(time.time() + 200) == [] and not sent(), sent())

# ================================================================ a machine that never returns: the wait stays until its backstop day
check("never: a machine that stays away leaves its wait open, pass after pass, and the stall pass does not look at it", all(server._evwait_poll(now0 + 300 + 60 * k) == [] for k in range(5)) and mt(22).get("wait_kind") == "event"
      and S.not_due({**rd(22), "gid": "a22"}, now0 + 3 * DAY) != "" and wk.due(rd(22), now0) == "", mt(22))
item(23, wait_kind="event", wait_event="box_online box-c", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] box-c never came back")
reset()
woke = server._watch_pass(now0)
check("backstop: the day passes with the machine still away: the item comes back to its post-wake mover saying the event did not come, naming the machine",
      "a23" in woke and mt(23).get("mover") == BACK and "the event did not come" in mt(23)["woke"]["what"] and "box-c coming online" in mt(23)["woke"]["what"] and "wait_kind" not in mt(23) and "a22" not in woke, (woke, mt(23)))

# ================================================================ a wait left open on a machine that is online (the write refuses it, but a state can change under a stored wait): the pass turns it
write_state()
item(24, wait_kind="event", wait_event="box_online box-a", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] box-a is online")
reset()
check("pass: an open wait whose machine is online turns on the next pass (the refusal is at the write only)", server._evwait_poll(time.time()) == ["a24"] and mt(24).get("mover") == BACK, mt(24))

# ================================================================ the tool text
tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
check("tool text: create and update name box_online in the wait_event parameter and in the description (what it is for; an online or unknown machine is refused)",
      all("box_online <machine>" in tools[n].parameters["properties"]["wait_event"]["description"] and "box_online <machine>" in tools[n].description for n in ("create", "update"))
      and "a machine already online" in tools["update"].description and "unknown name is refused" in tools["update"].description, None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
