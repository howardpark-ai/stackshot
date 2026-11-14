"""Scenario test for the front-agent watch rule — fixture data, no live store, no network, no server socket.

A front agent does not watch handed-off work itself: an update by a front agent that sets a reminder wake on an ALIVE item another session moves is refused, the mover
being judged as the call leaves the item (so a hand-off in the same call counts). Not gated (the review of that change): a park (hold with its wake, a waiting item's own
timer), a done `check` (the server-run push the rule names), an ask_by (and the retired expected_by, accepted and not stored), the mover's own wake, a wake the item already carries. Checked here:

  * a front agent's wake on an item a background agent moves: refused, the rule named, nothing written; its check and its park are allowed;
  * the mover's own wake and check pass; so does a wake on an item Oliver moves;
  * a hand-off and a wake in the same call by the old mover: refused, since it is no longer the mover; the same by a next line naming another session;
  * watch_reason lets a real exception through, is recorded on the item and in its History line; it is dropped by a later call that changes the wake without a reason,
    by the wake pass, by a done check's close or failure and by the close; a short one is refused; re-sending the same wake is no setting;
  * ask_by stays allowed from a front agent on handed-off work; a retired expected_by from it is accepted and not stored;
  * a background agent, and a sender no page lists, are never refused; a failure of the check itself lets the write through;
  * a front agent's hand-off by a next line needs neither a check nor a wake any more; a background agent's still does;
  * create takes a front agent's check as before, and has no watch_reason;
  * the tool text names the rule and the watch_reason parameter, and no longer teaches a front agent to check on handed-off work.

    tests/run-suite watch        → exit 0 / 1"""
import inspect as _inspect
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="watchtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-nobody")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_OFFSET = 4 * 3600.0                             # the instance timezone (the config's `timezone` above): UTC+4, no DST
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))     # home-nobody is a live session no page lists
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.service import gates; from stackshot.service import checks as checks_svc; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import create as _wt_create; from stackshot.web.tools import text as _wt_text; from stackshot.web.tools import update as _wt_update; from stackshot.github import ghsync; from stackshot.model import model
from stackshot.service import update as _update_svc
from stackshot.anchors import anchors as _anc
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # an expected_by n hours after the suite started (a time of day)
FUT = day(5)
mt = lambda i, letter="a": rd(i, letter)["metadata"]
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
FRONT, BACK, OTHER, NOBODY = "home-front", "team-back", "home-other", "home-nobody"
RULE = "does not watch handed-off work itself"
REASON = "no push reaches me: the builder runs on a box that never messages"
def upd(i, sender, **kw): return _update_svc._update(f"a{i}", sender=sender, **kw)
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, (was, raw(i)))

# ================================================================ the front agent's wake and check on an item a background agent moves
item(1, needs=[BACK])
refused_nw("1 wake: a front agent's wake on an item team-back moves is refused, the rule named", 1, lambda: upd(1, FRONT, wake=FUT), RULE, "stackshot", "watch_reason")
refused_nw("1 wake: …whatever else the call carries", 1, lambda: upd(1, FRONT, wake=FUT, next="home-front: waiting on it"), RULE)
upd(1, FRONT, check="unit_active watchtest.service")
check("1 check: a front agent's done check on that item is the server-run push the rule names: allowed", mt(1).get("check") == "unit_active watchtest.service" and "watch_reason" not in mt(1), mt(1))
upd(1, FRONT, clear_check=True)
out = upd(1, FRONT, next="home-front: look again later")
check("1 other writes: the same front agent's other writes on that item pass", "wake" not in mt(1) and "check" not in mt(1) and "watch_reason" not in mt(1), mt(1))
# the park: a hold with its wake on an item team-back moves is the park's own timer, fired by the server
item(17, needs=[BACK])
BASIS = f"vendor visit booked for {day(7)}"
upd(17, FRONT, hold=True, wake=day(4), wait_basis=BASIS)
check("1 park: a front agent parks an item team-back moves (hold=true with its wake): allowed, no reason needed", hd_(mt(17)) is True and wk_(mt(17)) == day(4) and "watch_reason" not in mt(17), mt(17))
upd(17, FRONT, wake=day(6), wait_basis=BASIS)
check("1 park: …and moves the park's wake later, the item being waiting, not alive", wk_(mt(17)) == day(6) and "watch_reason" not in mt(17), mt(17))
upd(17, FRONT, clear_hold=True)
check("1 park: …released, the item is alive again and a front agent's own wake on it is refused as before", "hold" not in mt(17), mt(17))
refused_nw("1 park: …(the wake went with the hold)", 17, lambda: upd(17, FRONT, wake=FUT), RULE)

# ================================================================ the mover's own wake and check pass; Oliver as the mover
item(2, needs=[])                                   # nobody else is named: the keeper of record home-front moves it
upd(2, FRONT, wake=FUT)
check("2 mover: the mover's own wake passes (the keeper of record moves an item with no session in needs)", wk_(mt(2)) == FUT and "watch_reason" not in mt(2), mt(2))
upd(2, FRONT, check="unit_active watchtest.service")
check("2 mover: …and its own check", mt(2).get("check") == "unit_active watchtest.service", mt(2))
item(3, needs=[BACK])
upd(3, BACK, wake=FUT)
check("3 mover: the mover itself (a background agent) sets its wake", wk_(mt(3)) == FUT, mt(3))
upd(3, BACK, check="unit_active watchtest.service")
check("3 mover: …and its check", mt(3).get("check") == "unit_active watchtest.service", mt(3))
ASK = "Decide: ship the thing now · Recommend: ship it · Stakes: a week of delay · By: no date"
item(4, needs=["decision", BACK], ask=ASK, state="your-call")
upd(4, FRONT, wake=FUT)
check("4 Oliver moves it: a front agent's wake on an item he moves is not a watch on another session's work", wk_(mt(4)) == FUT, mt(4))

# ================================================================ a hand-off and a wake in the same call: the old mover is no longer the mover
item(5, needs=[])
refused_nw("5 same call: mover=team-back with a wake, by the old mover, is refused", 5, lambda: upd(5, FRONT, mover=BACK, needs=[BACK], wake=FUT), RULE)
refused_nw("5 same call: …a hand-off by needs alone, with a wake", 5, lambda: upd(5, FRONT, needs=[BACK], wake=FUT), RULE)
refused_nw("5 same call: …a hand-off by a next line naming another session, with a wake", 5, lambda: upd(5, FRONT, next="team-back: do the thing", wake=FUT), RULE)
upd(5, FRONT, mover=BACK, needs=[BACK])
check("5 same call: the hand-off alone is made", mt(5).get("mover") == BACK, mt(5))
refused_nw("5 after: the old mover's wake on the item it handed over is refused too", 5, lambda: upd(5, FRONT, wake=FUT), RULE)
upd(5, BACK, wake=FUT)
check("5 after: …and the new mover's own passes", wk_(mt(5)) == FUT, mt(5))
item(18, needs=[])
upd(18, FRONT, mover=BACK, needs=[BACK], check="unit_active watchtest.service")
check("5 same call: a hand-off with a done check in one call by the old mover is allowed", mt(18).get("mover") == BACK and mt(18).get("check") == "unit_active watchtest.service", mt(18))
item(6, needs=[BACK])
upd(6, FRONT, mover=FRONT, needs=[], wake=FUT)
check("6 hand back: a hand-off back to the sender with its wake in the same call passes (it is the mover then)", wk_(mt(6)) == FUT and mt(6).get("mover") == FRONT, mt(6))

# ================================================================ the reason lets a real exception through, and is recorded
item(7, needs=[BACK])
refused_nw("7 reason: a reason too short to name anything is refused", 7, lambda: upd(7, FRONT, wake=FUT, watch_reason="because"), "watch_reason", "too short")
before = rd(7)
upd(7, FRONT, wake=FUT, watch_reason=REASON)
m = mt(7)
check("7 reason: with a watch_reason naming why no push exists the wake passes and the reason is stored", wk_(m) == FUT and m.get("watch_reason") == REASON, m)
item(8, needs=[BACK])
upd(8, FRONT, wake=FUT, watch_reason=REASON)
upd(8, FRONT, wake=FUT)
check("7 reason: re-sending the wake the item carries sets nothing: no refusal, and the reason stays", wk_(mt(8)) == FUT and mt(8).get("watch_reason") == REASON, mt(8))
refused_nw("7 reason: …moving it later without a reason is a new wake and is refused", 8, lambda: upd(8, FRONT, wake=day(6)), RULE)
upd(8, BACK, wake=day(6))
check("7 reason: …the mover moving it drops the reason, which belonged to the old wake", wk_(mt(8)) == day(6) and "watch_reason" not in mt(8), mt(8))
upd(7, BACK, clear_wake=True, next="team-back: done")
check("7 reason: …the mover clearing the wake drops it too", "wake" not in mt(7) and "watch_reason" not in mt(7), mt(7))
item(9, needs=[BACK])
upd(9, FRONT, next="home-front: another note", watch_reason=REASON)
check("7 reason: a reason on a call that sets no wake or check is not stored", "watch_reason" not in mt(9), mt(9))
upd(9, FRONT, wake=FUT, watch_reason=REASON)
upd(9, FRONT, check="unit_active watchtest.service")
check("7 reason: a check set beside the reason leaves it alone", mt(9).get("watch_reason") == REASON, mt(9))
upd(9, BACK, status="completed", outcome="done", reason="finished", description="- A thing\n- It lives here\n- Done")
check("7 reason: a close drops it", "watch_reason" not in mt(9), mt(9))
# the server's own acts drop it: the wake pass, a done check that closes the item, and one that fails
item(19, needs=[BACK], wake=day(-1), watch_reason=REASON)
wakes_svc.wake_pass()
check("7 reason: the wake pass firing the wake drops the reason", "wake" not in mt(19) and "watch_reason" not in mt(19), mt(19))
item(20, needs=[BACK], check="unit_active watchtest.service", watch_reason=REASON)
checks_svc.check_close("a20", _service_store._load("a20"), "unit_active watchtest.service", time.time())
check("7 reason: a done check closing the item drops it", rd(20)["status"] == "completed" and "watch_reason" not in mt(20), mt(20))
item(21, needs=[BACK], check="unit_active watchtest.service", watch_reason=REASON)
checks_svc.check_fail("a21", _service_store._load("a21"), "unit_active watchtest.service", "the unit was removed", time.time())
check("7 reason: …and one that fails it", "watch_reason" not in mt(21) and "check" not in mt(21), mt(21))

# ================================================================ ask_by stays allowed from anyone; the retired expected_by is accepted and not stored
item(11, needs=["external"], state="outside", party="Acme legal", chase=day(2))
upd(11, FRONT, ask_by=day(4))
check("8 dates: a front agent's ask_by on handed-off work is allowed", ab_(mt(11)) == day(4), mt(11))
item(10, needs=[BACK], state="doing")
upd(10, FRONT, expected_by=day(1))
check("8 dates: …and a retired expected_by is accepted and not stored", "expected_by" not in mt(10) and mt(10)["state"] == "doing", mt(10))

# ================================================================ only a front agent is refused
item(12, needs=[OTHER])
upd(12, BACK, wake=FUT)
check("9 background: a background agent's wake on an item another session moves is allowed", wk_(mt(12)) == FUT and "watch_reason" not in mt(12), mt(12))
upd(12, BACK, check="unit_active watchtest.service")
check("9 background: …and its check", mt(12).get("check") == "unit_active watchtest.service", mt(12))
item(13, needs=[BACK])
upd(13, NOBODY, wake=FUT)
check("9 unknown: a sender no page lists is allowed (the rule fails open)", wk_(mt(13)) == FUT, mt(13))
item(14, needs=[BACK])
check("9 front test: home-front is front, team-back and home-nobody and the owner are not", telling.front_sender(FRONT) and not telling.front_sender(BACK) and not telling.front_sender(NOBODY)
      and not telling.front_sender(model.owner_display()) and not telling.front_sender(""), None)

def _boom(*a, **k): raise RuntimeError("boom")
_real_others = gates._watch_others
gates._watch_others = _boom
errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf):
    upd(14, FRONT, wake=FUT)
gates._watch_others = _real_others
check("9 fail open: a failure of the check itself passes the write, with one stderr line", wk_(mt(14)) == FUT and errbuf.getvalue().count("watch rule: a14 not judged") == 1, (mt(14), errbuf.getvalue()))
_real_roles = _anc.session_roles
_anc.session_roles = _boom
errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf):
    verdict = telling.front_sender(FRONT)
_anc.session_roles = _real_roles
check("9 fail open: …and a failing front test reads as not front, with a stderr line", verdict is False and errbuf.getvalue().count("watch rule: front test of home-front failed") == 1, errbuf.getvalue())

# ================================================================ the hand-off gate: a front agent's hand-off asks for neither a check nor a wake
item(15, needs=[])
upd(15, FRONT, next="team-back: build it")
check("10 gate: a front agent's hand-off by a next line passes with no check and no wake", "check" not in mt(15) and "wake" not in mt(15) and "team-back: build it" in str(mt(15).get("next")), mt(15))
item(16, owner=U["home-front"], needs=[])
refused("10 gate: a background agent's hand-off is still asked for a check or a wake", lambda: upd(16, BACK, next="home-other: build it"), "nothing would close the item")
upd(16, BACK, next="home-other: build it", wake=FUT)
check("10 gate: …and passes with a wake", wk_(mt(16)) == FUT, mt(16))

# ================================================================ create's check: unchanged, it sets no wake
def mk(owner, **kw): return _wt_create._create(subject="[home] watch create", description=DESC, project="projects/alpha", owner=owner, next="home-front: look", **kw)
out = mk(FRONT, needs=[BACK], check="unit_active watchtest.service")
check("11 create: a front agent's check on an item it creates for team-back is allowed (a done check is the server-run push)", "created" in out, out)
check("11 create: …and create has no watch_reason parameter", "watch_reason" not in _inspect.signature(_wt_create.stackshot_create).parameters, None)

# ================================================================ the tool text says the rule, once, and no longer teaches a front agent to check
upd_d = _wt_update._UPDATE_DESC; cre_d = _wt_text._CHECK_FORM      # create's description carries _CHECK_FORM whole
check("12 text: update and create describe the rule and watch_reason", all("does not watch handed-off work itself" in d and "watch_reason" in d for d in (upd_d, cre_d)), (upd_d[-400:], cre_d[-300:]))
check("12 text: …the old teaching is gone", all("when you check on the work" not in d and "check on work handed to another session" not in d for d in (upd_d, cre_d, _wt_text._CHECK_FORM)), None)
check("12 text: …update takes the parameter", "watch_reason" in _inspect.signature(_wt_update.stackshot_update).parameters, None)
check("12 text: …the wording says what is pushed (a close or a hand-back), not 'writes to it'", all("closes the item or hands it back to you" in d and "writes to it" not in d for d in (upd_d, cre_d)) and "hands it back to you" in gates._WATCH_RULE, None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": watch scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
