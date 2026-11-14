"""Scenario test for the raises the retired idle pass stored — fixture data, no live store, no network.

Covers: the raises the retired idle pass left on stored items. A raise to Oliver's call stored before the last rung existed is still
answered (its "Park until" button with the option's day or the day written in the box, "Not needed"), a stale answer writes nothing, and
a later state change drops the stored metadata.idle.

    tests/run-suite idle        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="idletest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts (the stuck check reads them)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "fleet/b", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "home-gone", "home-dead", "home-off", "home-err"), 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
def fleet(gone=(), long=(), off=False, stopped=""):
    """The fleet as the server reads it. gone = panes whose puller stopped reporting them just now (a relaunch under way: within the
    grace, so not down); long = panes gone for months (past the grace: down, Oliver's one rule); off = machine b's puller is not
    checking in (home-off lives there); stopped = what machine a's puller reports for home-err (its last turn ended in that error)."""
    recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = {"a": {}, "b": {}}
    for n, u in U.items():
        L = "b" if n == "home-off" else "a"
        rows[L][u] = {"name": n, "machine": L, **({"gone": recent} if n in gone else {}), **({"gone": "2026-01-01T00:00:00Z"} if n in long else {}),
                      **({"stopped": stopped} if n == "home-err" and stopped else {})}
    for L, r in rows.items():
        (T / f"fleet/{L}/sessions.json").write_text(json.dumps(r))
    (T / "fleet/b/machine.json").write_text(json.dumps({"letter": "b", "fleet": "otherbox", "claude": "1.0.0", "online": {"ok": not off, "since": "2026-01-01T00:00:00Z"}}))
fleet(gone=("home-gone",))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0}}}))
def item(i, owner, **meta):
    if not any(meta.get(k) for k in ("needs", "hold", "after")):
        meta = {"mover": owner, **meta}      # the creator moves nothing; the scenario's items are moved by the session that used to be their creator, as a stored mover
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.",
                                                       "status": "open", "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60,
                                                       "metadata": {"owner": owner, "project": "projects/alpha", **meta}}))
item(1, U["home-owner"], state="queued")                   # carries a stored idle record the first state change drops
item(2, U["home-gone"])                                    # an item to answer stale
item(3, U["home-stew"])                                    # a stored raise: Park until the option's day
item(4, U["home-owner"], needs="external")                 # waits on someone
item(5, U["home-owner"], hold=True, wake="2099-01-01")     # parked
item(6, U["home-owner"])                                   # a stored raise: Park until a day written in the box
item(7, U["home-owner"])                                   # a stored raise: Not needed
item(8, "cse_0123456789abcdef")                          # a cloud session
item(9, U["home-owner"], after=["a5"])                     # waits on an open item
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.web import server
from stackshot.service import answer as answer_svc
from stackshot.service import wait_gates as wait_gates_svc
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import update as _update_svc
from stackshot.waits import waiting as _wt
from stackshot.web import answers as _web_answers
from stackshot.core import config as _cfg
import datetime as dt
from stackshot.projects import pages as _pages
from stackshot.web import render as _rmod
from stackshot.web import publish as _web_publish
from stackshot.service import runner as runner_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder, asked at the last rung
_wt.cap_needs_owner = lambda: False     # this scenario sets waits far ahead; the cap on a session's wake has its own scenario (waiting)
told = []
HOLD = [False]                                           # True: the send is held back (a held notice returns no thread, as the front gate's does)
def _tw(gid, owner, note, tag="wake"):
    told.append((tag, gid, owner, note))
    return None if HOLD[0] else object()
telling.tell_woken = _tw
clock = [now0]
# ---- 2b. a raise stored before the last rung existed: his button answers still apply (the item page's form posts them through answer_svc._answer)
# The server raises no question any more, so the stored raises of items 3, 6 and 7 are set up by hand, in the shape the old pass wrote them.
told.clear()
park = (dt.datetime.fromtimestamp(clock[0], _wt_text.ZONE) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
ASK = "Decide: what to do with this idle item · Recommend: Park until the day · Stakes: it sat idle · By: no date"
def legacy_raise(g_, named=()):
    it_ = rd(g_); mm = it_["metadata"]
    mm.pop("mover", None) if named else None; mm["needs"] = ["decision", *named]; mm["ask"] = ASK      # a session the item named stays named, as the old pass kept it
    mm["idle"] = {"poked": clock[0] - 600, "to": "home-stew", "raised": clock[0] - 300}
    mm["options"] = [{"label": f"Park until {_rmod.when_words(dt.date.fromisoformat(park))}", "line": f"On hold with a wake on {park}; for another day, write it in the box as YYYY-MM-DD with this choice.", "recommended": True, "wake": park},
                     {"label": "Not needed", "line": "It is no longer wanted: the item's mover closes it.", "recommended": False}]
    (T / f"store/a/{g_}.json").write_text(json.dumps(it_))
legacy_raise(3); legacy_raise(6); legacy_raise(7, named=(U["home-owner"],))
opts3 = rd(3)["metadata"]["options"]
import contextlib, io as _io
runner_svc.WAKE_EVENT.clear(); err3 = _io.StringIO()
with contextlib.redirect_stderr(err3):
    r = answer_svc._answer("a3", opts3[0]["label"], "", "")
it3 = rd(3); m3 = it3["metadata"]
check("Park until …: the minute loop is woken, and the log line says it was parked until the day", runner_svc.WAKE_EVENT.is_set() and f"parked until {park}" in err3.getvalue(), err3.getvalue()[-300:])
check("Park until …: his decision is in and the server parks it: waiting until the option's day (the one until date), decision out of needs, the ask and the idle record gone, the state clock moved",
      r == "decision" and m3.get("until") == park and "hold" not in m3 and "wake" not in m3 and "needs" not in m3 and "ask" not in m3 and "idle" not in m3 and it3["state_updated"] >= now0, m3)
check("the answer record carries the park the server set", m3["answers"][-1].get("choice") == opts3[0]["label"] and m3["answers"][-1].get("parked") == park, m3.get("answers"))
check("the park he set from the board stores no hold record and no old field: the one until date is the whole wait",
      "hold_set" not in m3 and "hold" not in m3 and "wake" not in m3, m3)
check("a park is acted on by the server itself: no answer escalation waits on it", "a3" not in _web_answers._answers_load(), _web_answers._answers_load())
check("get shows it waiting until the day", f"until: {park}" in _wt_get.stackshot_get("a3") and "waiting on a time" in _wt_get.stackshot_get("a3"), _wt_get.stackshot_get("a3"))
later = (_pages.zone_now() + dt.timedelta(days=10)).strftime("%Y-%m-%d")
r = answer_svc._answer("a6", rd(6)["metadata"]["options"][0]["label"], f"not before {later}, Pat is away", "")
m6 = rd(6)["metadata"]
check("Park until … with a day written in the box: that day is the wake, his note kept", r == "decision" and m6.get("until") == later and "hold" not in m6
      and m6["answers"][-1].get("text") == f"not before {later}, Pat is away" and m6["answers"][-1].get("parked") == later, m6)
check("…and the park is his own word for that wake: recorded as such (cap_ok), so the wake stands past the cap", m6.get("cap_ok", {}).get("wake") == later and m6["cap_ok"]["by"] == "a board answer"
      and _wt.cap_words(m6, "wake"), m6)
check("a day in the past in the box falls back to the option's day, and an option's day that has passed to [idle] park_days from now; a time of day is kept",
      _pane_recovery._idle_park_at(park, "2020-01-01 was too early") == park and _pane_recovery._idle_park_at("2020-01-02", "") == (_pages.zone_now() + dt.timedelta(days=3)).strftime("%Y-%m-%d")
      and _pane_recovery._idle_park_at(park, f"after {later} 14:30 then") == f"{later}T14:30",
      (_pane_recovery._idle_park_at(park, "2020-01-01 was too early"), _pane_recovery._idle_park_at("2020-01-02", ""), _pane_recovery._idle_park_at(park, f"after {later} 14:30 then")))
check("a session's write cannot carry a wake on an option: the gate drops the key, so no write of a session parks through an option",
      "wake" not in wait_gates_svc._gate_options([{"label": "Park until x", "line": "y", "recommended": True, "wake": "2099-01-01"}, {"label": "Not needed", "line": "z", "recommended": False}])[0],
      wait_gates_svc._gate_options([{"label": "Park until x", "line": "y", "recommended": True, "wake": "2099-01-01"}, {"label": "Not needed", "line": "z", "recommended": False}]))
told.clear()
r = answer_svc._answer("a7", "Not needed", "", "")
check("Not needed: decision leaves needs, no hold, the owner is told with the choice", r == "decision" and "hold" not in rd(7)["metadata"] and rd(7)["metadata"].get("needs") == [U["home-owner"]]
      and any(g == "a7" and "Not needed" in n for t, g, o, n in told), ({k: v for k, v in rd(7)["metadata"].items() if k in ("needs", "mover", "hold", "idle", "next")}, r, [x for x in told if x[1] == "a7"]))
check("there is no \"Nag again\" any more: the word is not an option of any raise, and an answer that is not one of the options is stale and writes nothing",
      not hasattr(server, "IDLE_RETRY_LABEL") and answer_svc._answer("a2", "Nag again", "", "") == "stale" and answer_svc._answer("a2", "Approve", "", "") == "stale" and "answers" not in rd(2)["metadata"], rd(2)["metadata"])

# ---- 3. a state change drops the stored idle record; a keeper parks an item it does not own
it1 = rd(1); it1["metadata"]["idle"] = {"poked": clock[0] - 600, "to": "home-stew", "recovery": clock[0] - 300}; (T / "store/a/1.json").write_text(json.dumps(it1))      # what the retired pass stored
_update_svc._update("a1", clear_needs=True, ask="none", next="home-owner: picked up again", sender="home-owner")
check("a state change drops metadata.idle", "idle" not in rd(1)["metadata"], rd(1)["metadata"])
_update_svc._update("a6", hold=True, wake="2099-01-02", sender="home-stew")
check("a keeper parks an item it does not own with sender=", rd(6)["metadata"].get("until") == "2099-01-02" and "idle" not in rd(6)["metadata"], rd(6)["metadata"])
print(("ok" if not fails else "FAILED") + f": idle scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
