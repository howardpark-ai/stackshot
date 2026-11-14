"""Scenario test for the old parameter `post_wake_mover` as an alias of `mover` (stackshot/model/model.py fold_picker_alias, stackshot/service/update.py and create.py, stackshot/service/gates.py) — a scratch store and
config, no port, no network, no model call.

A waiting item stores who picks it up when the wait ends as `mover`. The parameter that used to carry that, `post_wake_mover`, is read as `mover` until [model] post_wake_alias_until (the code's default
model.PICKER_ALIAS_UNTIL, read at each call). The refusal after that date is a later change; this suite holds the window:

  1  waiting item   the value is stored as `mover`, no old key is stored (a stored one goes), and the reply says so with the date; none clears the picker
  2  alive item     the value is dropped with a note that says how to hand the item over now; it is never stored and never a conflict; a stale old key goes
  3  both given     mover and post_wake_mover with one value are one value; different values are refused, naming mover; mover=none beside it leaves the old name as the picker
  4  a front agent  a front agent's value goes through the same fix as mover's (the project's builder takes it)
  5  create         the same fold on create
  6  the window     [model] post_wake_alias_until is read at each call, the code's default when unset; the example config lists it; the start warns once when it is missing or not a date
  7  keep_picker    an alive item's stale old key is never made the mover by clear_wait or clear_hold; an item that waits on his answer drops an agent picker when its wait ends

    tests/run-suite post_wake_alias        -> exit 0 / 1"""
import contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _midnight
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="postwakealias-"); T = pathlib.Path(tmp)
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
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" the checks read: start on the far side of one that is close
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.model import model as MODEL; from stackshot.service import create as create_svc
from stackshot.service import gates as _gates
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.front_sender = lambda who: False
BACK, OTHER, FRONT = "team-back", "home-other", "home-front"
LEG = MODEL.LEGACY_PICKER_KEY
def upd(i, sender=BACK, **kw):
    if kw.get("until") or kw.get("wait_kind"): kw.setdefault("wait_reason", "the vendor replies only after that date")
    return _wt_update.stackshot_update(f"a{i}", sender=sender, **kw)
local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
w = lambda n: local_day(now0 + n * DAY)
ENDS = _gates.post_wake_alias_until().isoformat()
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(x in str(e) for x in want), str(e)[:600])

# ================================================================ 1. a waiting item: the value is stored as mover
item(1, needs=[BACK])
out = upd(1, until=w(3), post_wake_mover=OTHER)
check("1 a date wait with post_wake_mover: the value is stored as mover and no old key is stored", mt(1).get("mover") == OTHER and LEG not in mt(1), mt(1))
check("1 …the reply says it is mover now, what was stored and until when", f"(post_wake_mover is mover now: stored as mover={OTHER}; accepted until {ENDS})" in out, out[-400:])
check("1 …a bare date beside it is a wait, not the backstop of a hand-over: the date is stored as until and no hand-off is recorded", MODEL.derive({**rd(1), "gid": "a1"}).state == MODEL.WAITING and "handoff" not in mt(1) and mt(1).get("until"), mt(1))
check("1 …and the item reads as waiting with that picker",MODEL.derive({**rd(1), "gid": "a1"}).state == MODEL.WAITING and MODEL.stored_picker(mt(1)) == OTHER, mt(1))
item(2, needs=[BACK], until=w(3), wait_kind="time", **{LEG: BACK})
out = upd(2, post_wake_mover=OTHER)
check("1 an item already waiting, a stored old key: the value replaces it, stored as mover, the old key is gone", mt(2).get("mover") == OTHER and LEG not in mt(2), mt(2))
check("1 …and the note is in the reply", "post_wake_mover is mover now" in out, out[-300:])
item(3, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
out = upd(3, post_wake_mover="none")
check("1 post_wake_mover=none clears the picker (no mover, no old key left)", not MODEL.stored_picker(mt(3)) and LEG not in mt(3) and "mover" not in mt(3), mt(3))
check("1 …and the reply names the alias", "post_wake_mover is mover now" in out, out[-300:])
item(4, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
out = upd(4, next=f"{BACK}: a note")
check("1 a write that names no picker leaves the stored one", mt(4).get("mover") == OTHER and "post_wake_mover" not in out, (mt(4), out[-200:]))

# ================================================================ 2. an alive item: the value is dropped with a note
item(10, needs=[BACK])
out = upd(10, post_wake_mover=OTHER)
check("2 an alive item: the value is not stored, as mover or as the old key", "mover" not in mt(10) and LEG not in mt(10), mt(10))
check("2 …the note says what it names and how to hand the item over now", f"(post_wake_mover dropped: it names who picks up a wait, and this item waits on nothing; to hand it over now, mover={OTHER})" in out, out[-400:])
check("2 …and the item stays alive with no conflict", MODEL.derive({**rd(10), "gid": "a10"}).state == "alive" and not MODEL.derive({**rd(10), "gid": "a10"}).conflicts, mt(10))
item(11, needs=[BACK], **{LEG: OTHER})
out = upd(11, post_wake_mover=FRONT)
check("2 an alive item with a stale old key: the key goes and the value is dropped", LEG not in mt(11) and "mover" not in mt(11) and "post_wake_mover dropped" in out, (mt(11), out[-300:]))
item(12, needs=[BACK])
out = upd(12, post_wake_mover="none")
check("2 none on an alive item: nothing to clear, said so", "mover" not in mt(12) and "there is no picker to clear" in out, (mt(12), out[-300:]))

# ================================================================ 3. both given
item(20, needs=[BACK])
refused("3 mover and post_wake_mover that differ are refused, naming mover", lambda: upd(20, until=w(3), mover=OTHER, post_wake_mover=BACK), "mover and post_wake_mover differ", "pass mover=<who> alone")
check("3 …and nothing was written", "mover" not in mt(20) and "until" not in mt(20) and LEG not in mt(20), mt(20))
item(21, needs=[BACK])
out = upd(21, until=w(3), mover=OTHER, post_wake_mover=OTHER)
check("3 the same value in both is one value: stored as mover once, no old key, no alias note", mt(21).get("mover") == OTHER and LEG not in mt(21) and "post_wake_mover is mover now" not in out, (mt(21), out[-300:]))
item(22, needs=[BACK])
out = upd(22, until=w(3), mover="none", post_wake_mover=OTHER)
check("3 mover=none beside post_wake_mover: the old name is the picker (the old way to say no live mover and this one takes it)", mt(22).get("mover") == OTHER and LEG not in mt(22), (mt(22), out[-300:]))

# ================================================================ 4. a front agent's value
item(30, needs=[BACK])
out = upd(30, sender=OTHER, until=w(3), post_wake_mover=FRONT)
check("4 a front agent as the value: the project's builder takes it, as for mover", mt(30).get("mover") == BACK, (mt(30).get("mover"), out[-400:]))
item(31, needs=[BACK])
upd(31, sender=OTHER, until=w(3), mover=FRONT)
check("4 …the same as mover=<front agent> alone", mt(31).get("mover") == mt(30).get("mover"), (mt(31), mt(30)))

# ================================================================ 5. create
g, out = create_svc.create_item(subject="[home] created with the old name", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: wait for the reply", needs=[BACK],
                                wait_kind="relay", wait_event="the vendor's reply", until=w(4), post_wake_mover=OTHER, request_id="pw-create-1")
m_ = mof(g)
check("5 create with a wait: post_wake_mover is stored as mover, no old key, and the reply says so", m_.get("mover") == OTHER and LEG not in m_ and "post_wake_mover is mover now" in out, (out[-300:], m_))
g2, out2 = create_svc.create_item(subject="[home] created alive with the old name", description=DESC, project="projects/alpha", owner=U["home-front"], next=f"{BACK}: work on it", needs=[BACK],
                                  post_wake_mover=OTHER, request_id="pw-create-2")
m2_ = mof(g2)
check("5 create with no wait: the value is dropped with the note", "mover" not in m2_ and LEG not in m2_ and "post_wake_mover dropped" in out2, (out2[-300:], m2_))

# ================================================================ 6. the window
_held_open = _cfg.CFG.setdefault("model", {}).pop("post_wake_alias_until", None)      # the suites hold the window open (tests/_instance.py); the code's own default is read with the key unset
try:
    check("6 the window is a config value read at use: [model] post_wake_alias_until, the code's default when unset", _gates.post_wake_alias_until() == dt.date.fromisoformat(MODEL.PICKER_ALIAS_UNTIL), None)
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        _gates.post_wake_alias_check()
    check("6 the start warns once when the key is missing, naming the key and the date the code stands on", buf.getvalue().count("\n") == 1 and "post_wake_alias_until is missing" in buf.getvalue() and MODEL.PICKER_ALIAS_UNTIL in buf.getvalue(), buf.getvalue())
    _cfg.CFG["model"]["post_wake_alias_until"] = "next week"
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        _gates.post_wake_alias_check()
    check("6 …and when it is not a date", "not a date (next week)" in buf.getvalue(), buf.getvalue())
    check("6 …a value that is not a date reads as the code's default", _gates.post_wake_alias_until() == dt.date.fromisoformat(MODEL.PICKER_ALIAS_UNTIL), None)
    _cfg.CFG["model"]["post_wake_alias_until"] = "2031-03-04"
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        _gates.post_wake_alias_check()
    check("6 a date in the key: no warning, and the date read is that one, so the reply names it", not buf.getvalue() and _gates.post_wake_alias_until() == dt.date(2031, 3, 4), buf.getvalue())
    item(40, needs=[BACK])
    out = upd(40, until=w(3), post_wake_mover=OTHER)
    check("6 …the reply names the date set in the config", "accepted until 2031-03-04" in out, out[-300:])
finally:
    if _held_open is not None:
        _cfg.CFG["model"]["post_wake_alias_until"] = _held_open
    else:
        _cfg.CFG["model"].pop("post_wake_alias_until", None)
_example = (pathlib.Path(STACK) / "stackshot.example.toml").read_text(encoding="utf-8")
check("6 stackshot.example.toml lists post_wake_alias_until with the code's date, next to wait_alias_until (so a start from it warns of nothing)",
      f'post_wake_alias_until = "{MODEL.PICKER_ALIAS_UNTIL}"' in _example and _example.index("wait_alias_until =") < _example.index("post_wake_alias_until ="), MODEL.PICKER_ALIAS_UNTIL)
check("6 …and the suites' own start holds the window open (a fixed date in the example fails no suite after it)", _held_open is None or str(_held_open) >= "2099", _held_open)

# ================================================================ 7. keep_picker acts only on an item that waited
for clear in ("clear_wait", "clear_hold"):
    item(50, needs=[BACK], mover=BACK, **{LEG: OTHER})          # alive (no wait stored), a stale old key
    try:
        upd(50, **{clear: True})
    except Exception:
        pass
    check(f"7 an alive item with a stale old key, {clear}: the old key's agent is not made the mover, the mover it has stays", mt(50).get("mover") == BACK, mt(50))
item(51, needs=[BACK], mover=BACK, **{LEG: OTHER})
out = upd(51, post_wake_mover=OTHER)
check("7 an alive item, the old name written again: the stale old key goes with the dropped value and the mover stays", LEG not in mt(51) and mt(51).get("mover") == BACK and "post_wake_mover dropped" in out, (mt(51), out[-300:]))
_cfg.CFG.setdefault("model", {})["guards"] = False          # the write guards refuse a decision beside a wait; the stored shape of an older item is built by hand and its write is read without them
item(52, needs=["decision"], hold=True, wake=w(3), wait_kind="time", mover=OTHER)
upd(52, clear_wait=True)
check("7 an item that waits on his answer, an agent stored as the picker: clear_wait does not hand it to that agent", mt(52).get("mover") != OTHER, mt(52))
item(53, needs=["decision"], hold=True, wake=w(3), wait_kind="time", mover=OTHER)
upd(53, clear_wait=True, mover=BACK)
check("7 …a mover named in the same call still stands", mt(53).get("mover") == BACK, mt(53))

# ================================================================ 8. one judgement of "waits after the write": the trial and the real write agree
item(60, needs=[BACK])
out = upd(60, until=w(3), needs=[OTHER], post_wake_mover=BACK)
check("8 a hand-off in the same call (needs to another session, a bare date, the old name): the item ends alive, so the value is dropped with the alive note and is not stored",
      LEG not in mt(60) and "stored as mover" not in out and "post_wake_mover dropped" in out, (mt(60), out[-500:]))
check("8 …the date is the backstop of the hand-off and the item is alive, handed to the session in needs, with no picker stored",
      MODEL.derive({**rd(60), "gid": "a60"}).state == "alive" and not MODEL.stored_picker(mt(60)) and mt(60).get("mover") != BACK, mt(60))

item(61, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
out = upd(61, post_wake_mover="none")
check("8 none on a waiting item: the picker is cleared and the note says that, not that something was stored", not MODEL.stored_picker(mt(61)) and LEG not in mt(61) and "none clears the picker" in out and "stored as mover=none" not in out, (mt(61), out[-300:]))

item(62, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
out = upd(62, clear_wait=True, post_wake_mover="none")
check("8 clear_wait with none on a time wait: the item is alive after the write, so none is dropped with the alive note and the live mover stays",
      MODEL.derive({**rd(62), "gid": "a62"}).state == "alive" and mt(62).get("mover") == OTHER and "post_wake_mover dropped" in out and "none clears the picker" not in out, (mt(62), out[-400:]))

item(63, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
refused("8 clear_mover with post_wake_mover=<who>: a clash, naming both, and nothing is written", lambda: upd(63, clear_mover=True, post_wake_mover=BACK), "clear_mover", "post_wake_mover", "contradict")
check("8 …the item is as it was", mt(63).get("mover") == OTHER and LEG not in mt(63), mt(63))
item(64, needs=[BACK], until=w(3), wait_kind="time", mover=OTHER)
refused("8 clear_mover with mover=<who>: still a clash", lambda: upd(64, clear_mover=True, mover=BACK), "clear_mover")

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": post wake alias scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
