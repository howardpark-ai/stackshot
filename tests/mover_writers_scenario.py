"""Scenario test for the server's own writers of a waiting item's picker — fixture data, no live store, no network, no server socket.

Every place the server itself stores who picks a waiting item up when the wait ends stores it as `mover`, never as the old key `post_wake_mover`; every read of it is as before (the same picker, the same
session told, the same arrival). One rule holds on every save that names the picker: a write that sets `mover` on a waiting item drops a stored old key (the old key reads first, so it would outvote the new
mover), `clear_mover` and `clear_wait` drop both keys, and `clear_wait` also drops a stored `mover` that is he (the pick-up went with the wait) while an agent's `mover` stays as the live mover. Covered:

  1  wait-end fix    each op of the filing pass's wait fix (after, event, anchor) stores the picker as it did (the old key): deferred on purpose, see 9
  2  hand-over       a decision's hand-over of a time wait (a hold with a wake, a wait on a date alone) is exactly as on main (the one writer deferred to the later steps: it still stores the old key, so a later
                     clear_hold, clear_wait or clear_wake ends as it always did); the shapes that store nothing (external, an open after, a hold with no wake, a dead then, the watchers off) are as they were
  3  snapshot        a watch.was snapshot and its restore are as on main (deferred on purpose, see 9): each key goes back as it was stored (the old word none included); was_picker reads every form
  4  plan            the cold call's answer key stays post_wake_mover, the validated answer carries `mover`; the state migration's plan sets `mover` and drops a stored old key; its route applies the save rule
  5  save rule       an update that sets mover on a waiting item with an old key stored; clear_mover and clear_wait on each form (old key, mover, both, he, an agent); an alive item; an item with external in needs
  6  differential    an item stored under the old key against the same stored as `mover`: the picker, the session told, the arrival, the item after the wake — equal, but for the word held_by gives

    tests/run-suite mover_writers        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="moverwriters-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[zed] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-zed"): (T / d).mkdir(parents=True)
NAMES = ("zed-stew", "zed-back", "zed-helper", "zed-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/zedwork": {"title": "Zedwork", "name": "Zedwork", "org": "zed", "tags": [], "type": "project",
                                                                                   "session": "zed-stew", "status": "active", "board": [], "board_open": 0,
                                                                                   "agents": {"zed-front": "the front", "zed-back": "the back", "zed-helper": "the helper"},
                                                                                   "back_agents": {"zed-back": "the back", "zed-helper": "the helper"}}}}))
(T / "brain/projects/zedwork.md").write_text("---\ntitle: Zedwork\ndisplay-name: zed-stew\nagents:\n  zed-front: the front\n  background:\n    zed-back: the back\n    zed-helper: the helper\n---\n\n# Zedwork\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", subject=None, store="a", **meta):
    su = now0 - 10 * DAY
    (T / f"store/{store}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[zed] item {i}", "description": DESC, "status": status,
                                                             "updated": su, "state_updated": su, "confirmed": su,
                                                             "metadata": {"owner": U["zed-front"], "project": "projects/zedwork", "next": "zed-back: do the thing", **meta}}))
def rd(i, store="a"): return json.loads((T / f"store/{store}/{i}.json").read_text())
def mt(i, store="a"): return rd(i, store)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk
from stackshot.model import cold_call as cold
from stackshot.model import holders as _holders
from stackshot.model import migration as M
from stackshot.audit import audit_run as AR
from stackshot.core import config as _cfg
from stackshot.service import store as _service_store
from stackshot.service import update as _update_svc
from stackshot.service import migrations as migsvc
from stackshot.service import watching as watching_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import event_waits as evwaits_svc
from stackshot.service import telling
from stackshot.service import answer_handover as handover_svc
from stackshot.service import wait_gates as wait_gates_svc, released as released_svc
from stackshot.service import wait_fixes as _wait_fixes_svc
from stackshot.fleet import liveness as LV
from stackshot.web import home
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
SENT = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
telling.front_sender = lambda who: False
released_svc._own_repo = lambda: "acme/widgets"
wait_gates_svc._evwait_preread = lambda kind, phrase: None
evwaits_svc.evw_boxes = lambda: {}
LV.puller_online = lambda rec: bool(rec)
(T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
ZONE_HOURS = 4
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
OWN = model.owner_display()
LEG = model.LEGACY_PICKER_KEY
FUT = day(5)
D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
def its(**meta): return {"status": "open", "metadata": {"project": "projects/zedwork", **meta}}
def guards(on): CFG["guards"] = on
def old_form(meta):
    """the item as main stored it: the picker under the old key (a `mover` that was popped there is not carried over)."""
    m = dict(meta)
    if "mover" in m: m[LEG] = m.pop("mover")
    return m
def stores_mover(meta, who): return meta.get("mover") == who and LEG not in meta
def stores_old(meta, who): return meta.get(LEG) == who and "mover" not in meta

# ================================================================ 1. the wait-end fix (the filing pass)
ROLES = {BACK: {"role": "background"}, HELP: {"role": "background"}, FRONT: {"role": "front"}}
def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: FRONT, builder=lambda p: BACK, page_of=lambda p: ("", None), deliver=lambda to, text, fyi=False: (True, "[200] ok"), sessions=lambda: None,
                             pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
OLD = now0 - 3 * 3600.0
def gitem(i, nxt, **meta):
    (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[zed] item {i}", "description": DESC, "status": "open", "updated": OLD, "written_at": OLD, "written_by": BACK,
                                                    "state_updated": OLD, "confirmed": OLD,
                                                    "metadata": {"owner": U[FRONT], "project": "projects/zedwork", "state": "doing", "needs": [BACK], "next": nxt, **meta}}))
ref = lambda n: f"board#{n}"      # an item reference built at run time, so no literal id sits in the file
gid = lambda n: f"g{n}"
def fix_pass():
    items_ = {f"g{p.stem}": json.loads(p.read_text()) for p in (T / "store/g").glob("*.json")}
    return AR.filing_pass(now=now0, items=items_, anchors={}, env=env(wait_end=_wait_fixes_svc._wait_end_fix, wait_facts=_wait_fixes_svc._wait_end_facts))
def clear_g():
    for p in (T / "store/g").glob("*.json"): p.unlink()
(T / "state/audit").mkdir(parents=True, exist_ok=True)
gitem(9202, "zed-helper: build the thing")
gitem(9201, f"zed-back: wait for {ref(9202)} to close, then write the summary")
gitem(9203, f"zed-back: wait for {ref(9202)} to close, then write the summary", mover=BACK)
gitem(9204, f"zed-back: wait for {ref(9202)} to close, then write the summary", **{LEG: HELP})         # an old key left on an alive item: the new picker replaces it
r = fix_pass()
for n in (9201, 9203, 9204):
    m_ = mt(n, "g"); mod_ = model.derive(rd(n, "g"), now0)
    check(f"1 after (g{n}): the item waits on the item's close, with the mover stored as the old key, as on main (deferred, see section 9)", m_.get("wait_kind") == "item" and stores_old(m_, BACK) and mod_.state == "waiting" and mod_.wait.mover == BACK and mod_.wait.mover_explicit, m_)
    check(f"1 after (g{n}): the session it is told is the mover, worded mover", telling.held_by(rd(n, "g"))[0] == BACK, telling.held_by(rd(n, "g")))
check("1 after: the pass said it fixed them", len(r.get("wait_end", {}).get("fixed", [])) == 3, r.get("wait_end"))
clear_g()
gitem(9211, "zed-back: wait for other/repo#7 to be merged, then write the summary")
gitem(9213, "zed-back: wait for the reply in https://github.com/acme/widgets/issues/5")
gitem(9214, "zed-back: wait for other/repo#7 to be merged, then write the summary", **{LEG: HELP}, wait_kind="event", wait_event="pr_merged other/repo#7", state=None)
r = fix_pass()
for n, what in ((9211, "event"), (9213, "anchor")):
    m_ = mt(n, "g")
    check(f"1 {what} wait (g{n}): stored with the old key, as on main", m_.get("wait_kind") == what and stores_old(m_, BACK) and model.derive(rd(n, "g"), now0).state == "waiting" and model.derive(rd(n, "g"), now0).wait.mover == BACK, (m_, r.get("wait_end")))
check("1 a stored event wait that only lacks its backstop (the fix writes a day): the old key left on it stays", mt(9214, "g").get(LEG) == HELP, mt(9214, "g"))
clear_g()

# ================================================================ 2. a decision's hand-over of a time wait
def hand(meta, mover_in, then_in, **kw):
    m_ = dict(meta); handover_svc._decision_hand_over(m_, mover_in, then_in, now=now0, **kw); return m_
BASE = {"project": "projects/zedwork", "needs": [BACK]}
m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True)
check("2 a hold with a wake and an agent in then: a time wait, the picker = then under the old key (deferred on purpose: see the end-of-wait matrix below), then cleared, the stamp set", m_.get("wait_kind") == "time" and stores_old(m_, HELP) and "then" not in m_ and m_["watch"]["set_at"] == now0, m_)
m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, parked=True)
check("2 …a parked item is the same", m_.get("wait_kind") == "time" and stores_old(m_, HELP) and "then" not in m_, m_)
m_ = hand({**BASE, "mover": OWN, "then": HELP, "until": FUT}, OWN, HELP, waiting=True)
check("2 a wait on a date alone: no kind, the picker = then under the old key, then cleared", "wait_kind" not in m_ and stores_old(m_, HELP) and "then" not in m_ and m_["until"] == FUT, m_)
m_ = hand({**BASE, "then": HELP, LEG: BACK, "hold": True, "wake": FUT}, "", HELP, waiting=True)
check("2 an old key stored on the item is replaced by the then (the one picker, never two)", stores_old(m_, HELP), m_)
m_ = hand({**BASE, "mover": BACK, "then": HELP, "until": FUT}, BACK, HELP, waiting=True)
check("2 a stored agent mover: the then takes it, as on main (the old key is the picker and reads first)", m_.get(LEG) == HELP and m_.get("mover") == BACK and D(**m_).wait.mover == HELP, m_)
# the shapes that store no picker are as they were
item(1, subject="[zed] an open item the others wait after")
for label, meta, kw in (("an open after link", {**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT, "after": ["a1"]}, dict(waiting=True)),
                        ("a hold with no wake", {**BASE, "mover": OWN, "then": HELP, "hold": True}, dict(waiting=True)),
                        ("a then that is no live session", {**BASE, "mover": OWN, "then": "nobody-here", "hold": True, "wake": FUT}, dict(waiting=True)),
                        ("he as then", {**BASE, "mover": OWN, "then": OWN, "hold": True, "wake": FUT}, dict(waiting=True))):
    m_ = hand(meta, OWN, meta.get("then", ""), **kw)
    check(f"2 {label}: no picker is stored, as before", "mover" not in m_ and LEG not in m_ and "wait_kind" not in m_, m_)
check("2 …an open after link keeps then for the release of the after (as before)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT, "after": ["a1"]}, OWN, HELP, waiting=True).get("then") == HELP, None)
_orig_enabled = server._watch.enabled
server._watch.enabled = lambda: False
try:
    m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True)
finally:
    server._watch.enabled = _orig_enabled
check("2 the watchers off: no time wait is stored, then stays with the old park (as before)", "mover" not in m_ and LEG not in m_ and "wait_kind" not in m_ and m_.get("then") == HELP, m_)
# external in needs: exactly as on main (then dropped, nothing stored), for the wait on a date alone and for the hold with a wake
for label, extra in (("a wait on a date alone", {"until": FUT}), ("a hold with a wake", {"hold": True, "wake": FUT})):
    meta = {"project": "projects/zedwork", "needs": [BACK, "external"], "mover": OWN, "then": HELP, **extra}
    m_ = hand(meta, OWN, HELP, waiting=True)
    check(f"2 external in needs, {label}: then is dropped, the mover he goes, no picker and no kind stored: the item is as main left it", m_ == {k: v for k, v in meta.items() if k not in ("mover", "then")}, m_)
    m_ = hand({**meta, LEG: BACK}, OWN, HELP, waiting=True)
    check(f"2 …with the old key stored on it: it stays as it was, never moved", m_.get(LEG) == BACK and "mover" not in m_ and "then" not in m_, m_)

# ================================================================ 3. the snapshot of a wait, and its restore
def remembered(meta):
    m_ = dict(meta); wk.remember(m_, "relay", now0); return m_
RW = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "needs": [BACK]}
for label, meta, want in (("a wait stored as mover", {**RW, "mover": HELP}, {"mover": HELP}), ("a wait stored under the old key", {**RW, LEG: HELP}, {LEG: HELP}),
                          ("both stored", {**RW, LEG: HELP, "mover": BACK}, {LEG: HELP, "mover": BACK}), ("the old key with the word none", {**RW, LEG: "none"}, {LEG: "none"}),
                          ("a wait on a date alone under the old key", {"until": FUT, "needs": [BACK], LEG: HELP}, {LEG: HELP})):
    m_ = remembered(meta)
    check(f"3 remember, {label}: the snapshot holds the keys as stored (no key is translated)", {k: m_["watch"]["was"].get(k) for k in (LEG, "mover") if k in m_["watch"]["was"]} == want, m_["watch"])
check("3 was_picker reads every form (old snapshot, new snapshot, both)", wk.was_picker({LEG: HELP}) == wk.was_picker({"mover": HELP}) == HELP and wk.was_picker({LEG: BACK, "mover": HELP}) == BACK, None)
check("3 was_picker: a snapshot's word none under the old key is a session of that name, under `mover` nobody (as on main)", wk.was_picker({LEG: "none"}) == "none" and wk.was_picker({"mover": "none"}) == "", None)
def restored(was, **now_meta):
    m_ = {"project": "projects/zedwork", "needs": ["decision"], "ask": "x", "watch": {"asked": "relay", "was": was, "at": now0}, **now_meta}
    wk.restore_wait(m_, day(9), True, now0); return m_
for label, was, ok in (("an old snapshot (the old key)", {"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, lambda m: stores_old(m, HELP)),
                       ("a new snapshot (mover)", {"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, lambda m: stores_mover(m, HELP)),
                       ("both keys", {"wait_kind": "relay", "wait_event": "the reply", LEG: HELP, "mover": HELP}, lambda m: m.get(LEG) == HELP and m.get("mover") == HELP),
                       ("the old key with the word none", {"wait_kind": "relay", "wait_event": "the reply", LEG: "none"}, lambda m: m.get(LEG) == "none" and "mover" not in m)):
    m_ = restored(was)
    check(f"3 restore_wait, {label}: the wait is back with its keys as they were stored", ok(m_) and m_.get("wait_kind") == "relay" and m_.get("ask_by") == day(9), m_)
m_ = restored({"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, **{LEG: BACK})
check("3 restore_wait: an old key still on the item is replaced by the snapshot's, as on main", stores_old(m_, HELP), m_)
m_ = restored({"until": FUT, "needs": [BACK, "external"], LEG: HELP})
check("3 restore_wait: a wait on a date alone with external in needs and the old key goes back with that key (its end reads it: as on main)", m_.get(LEG) == HELP and "mover" not in m_, m_)
# the server reads the snapshot either way
for n, was in ((6, {LEG: HELP}), (7, {"mover": HELP})):
    item(n, subject=f"[zed] was {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
    m_ = dict(mt(n)); r = wait_gates_svc._watch_answer(rd(n), m_, {"do": "arrived", "text": "", "date": ""}, now0)
    check(f"3 _watch_answer arrived, snapshot {sorted(was)[0]}: the agent it names has the item", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))
    item(n + 10, subject=f"[zed] was again {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
    m_ = dict(mt(n + 10)); r = wait_gates_svc._watch_answer(rd(n + 10), m_, {"do": "wait", "text": "", "date": day(9)}, now0)
    check(f"3 _watch_answer not yet, snapshot {sorted(was)[0]}: the wait is back with its picker under the key the snapshot held", (stores_old(m_, HELP) if LEG in was else stores_mover(m_, HELP)) and m_.get("ask_by") == day(9) and "waits again" in r, (r, m_))

# ================================================================ 4. the plan: the cold call's edge and the migration
TODAY = __import__("datetime").date.today()
iso = lambda n: (TODAY + __import__("datetime").timedelta(days=n)).isoformat()
MOV = [BACK, HELP]
ans = {"wait": "yes", "kind": "item", "input": {"after": [ref(23)]}, "end": iso(5), "post_wake_mover": "ZED-BACK", "reason": "r", "confidence": "high"}
res, why = cold.validate_hidden(ans, TODAY, MOV, gid(22), lambda s: gid(23) if s == ref(23) else "", [], "")
check("4 cold call: the validated answer carries the picker as `mover` (copied from the list), never the old key", res is not None and res.get("mover") == BACK and LEG not in res, (res, why))
res2, why2 = cold.validate_hidden({**ans, "post_wake_mover": "somebody"}, TODAY, MOV, gid(22), lambda s: gid(23), [], "")
check("4 cold call: a name that is not on the list is still refused", res2 is None and "post-wake mover" in why2, (res2, why2))
check("4 cold call: the model-facing prompt still names post_wake_mover as the answer key", any(LEG in str(v) for v in vars(cold).values() if isinstance(v, str) and '"wait": "yes"' in v), None)
check("4 migration: the route's fields take mover and may drop the old key", "mover" in M.OPEN_SET_FIELDS and LEG in M.DROP_FIELDS, None)
# the route applies the save rule: a write that sets mover on an item with an old key stored drops it (the plan itself drops it too: migration_scenario)
guards(True)
try:
    for n, sets, drops, label in ((30, {"mover": BACK}, [], "the old key goes beside a mover the write sets"), (31, {"mover": BACK}, [LEG], "…and the plan's own drop of it passes the route"), (32, {"wait_kind": "relay"}, [], "a write that sets no mover leaves the old key"), (33, {"mover": BACK, LEG: BACK}, [], "a write that names both keys is stored as written")):
        item(n, subject=f"[zed] migrate {n}", needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=day(5), **{LEG: HELP})
        it_ = rd(n)
        out = migsvc.migrate_one({"item": f"a{n}", "set": sets, "drop": drops, "expect": it_["updated"], "expect_sig": list(migsvc.migrate_sig(f"a{n}", it_)), "kind": "test", "note": "t"})
        want_gone = "mover" in sets and LEG not in sets
        check(f"4 migration route: {label}", out["action"] in ("set", "already") and (stores_mover(mt(n), BACK) if want_gone else (mt(n).get(LEG) == (BACK if LEG in sets else HELP))), (out, mt(n)))
finally:
    guards(False)

# ================================================================ 5. the save rule (the update path)
def upd(n, **kw): return _update_svc._update(f"a{n}", sender=BACK, **kw)
def ruled(n, start, **kw):
    item(n, subject=f"[zed] rule {n}", **start)
    upd(n, **kw)
    return mt(n)
WAITING_KEYS = dict(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT)
for g_ in (False, True):
    guards(g_)
    tag = f"(guards {'on' if g_ else 'off'})"
    m_ = ruled(100, {**WAITING_KEYS, LEG: HELP}, mover=BACK)
    check(f"5 a mover set on a waiting item that stores the old key: the old key goes, the new mover is the picker {tag}", stores_mover(m_, BACK) and D(**m_).wait.mover == BACK, m_)
    m_ = ruled(101, {**WAITING_KEYS, LEG: HELP, "mover": HELP}, mover=BACK)
    check(f"5 …with both stored {tag}", stores_mover(m_, BACK) and D(**m_).wait.mover == BACK, m_)
    m_ = ruled(102, {**WAITING_KEYS, "mover": HELP}, mover=BACK)
    check(f"5 …with only a mover stored: replaced, no old key appears {tag}", stores_mover(m_, BACK), m_)
    m_ = ruled(103, {**WAITING_KEYS, LEG: HELP}, clear_mover=True)
    check(f"5 clear_mover on a waiting item with the old key: both go, so the old key cannot become the picker {tag}", "mover" not in m_ and LEG not in m_ and D(**m_).wait.mover == OWN and not D(**m_).wait.mover_explicit, m_)      # a relay's default picker is he
    m_ = ruled(104, {**WAITING_KEYS, LEG: HELP, "mover": BACK}, clear_mover=True)
    check(f"5 clear_mover with both stored: both go {tag}", "mover" not in m_ and LEG not in m_, m_)
    m_ = ruled(105, {**WAITING_KEYS, "mover": HELP}, clear_mover=True)
    check(f"5 clear_mover with a mover only: it goes {tag}", "mover" not in m_ and LEG not in m_, m_)
    m_ = ruled(106, {**WAITING_KEYS, LEG: HELP}, clear_wait=True)
    check(f"5 clear_wait with the old key: the wait and the old key go {tag}", all(k not in m_ for k in ("wait_kind", LEG, "mover")), m_)
    m_ = ruled(107, {**WAITING_KEYS, "mover": HELP}, clear_wait=True)
    check(f"5 clear_wait with an agent's mover: the wait goes, the agent stays as the live mover {tag}", "wait_kind" not in m_ and m_.get("mover") == HELP and LEG not in m_ and D(**m_).state == "alive" and D(**m_).mover == HELP, m_)
    m_ = ruled(108, {**WAITING_KEYS, "mover": OWN, "then": HELP}, clear_wait=True)
    check(f"5 clear_wait with a stored mover that is he (he picked the item up when the wait ended): it goes with the wait {tag}", "wait_kind" not in m_ and "mover" not in m_ and LEG not in m_, m_)
    m_ = ruled(109, {**WAITING_KEYS, "mover": HELP, LEG: BACK}, clear_wait=True)
    check(f"5 clear_wait with both stored: the old key goes with the wait, the agent mover stays {tag}", "wait_kind" not in m_ and m_.get("mover") == HELP and LEG not in m_, m_)
    m_ = ruled(110, {**WAITING_KEYS, LEG: OWN, "mover": HELP}, clear_wait=True)
    check(f"5 clear_wait with the old key that is he beside an agent mover: the old key goes, the agent stays {tag}", "wait_kind" not in m_ and m_.get("mover") == HELP and LEG not in m_, m_)
guards(False)
# alive items and writes that name nothing
item(120, subject="[zed] alive his", needs=["decision"], ask="Decide: x", mover=OWN, then=HELP)
upd(120, clear_wait=True)
check("5 clear_wait on an alive item that is his: nothing waited, so his mover stays", mt(120).get("mover") == OWN and mt(120).get("then") == HELP, mt(120))
item(121, subject="[zed] alive agent", needs=[BACK], mover=BACK)
upd(121, mover=HELP)
check("5 a mover set on an alive item: the plain write, no old key appears", stores_mover(mt(121), HELP), mt(121))
item(122, subject="[zed] alive stray", needs=[BACK], **{LEG: HELP})
upd(122, mover=BACK)
check("5 a mover set on an alive item that stores a stray old key: the rule is for a wait, the stray stays as it was (the model lists it)", mt(122).get(LEG) == HELP and mt(122).get("mover") == BACK, mt(122))
item(123, subject="[zed] other write", **{**WAITING_KEYS, LEG: HELP})
upd(123, next="zed-back: a note")
check("5 a write that names no mover leaves the old key where it was (no migration of stored items here)", mt(123).get(LEG) == HELP and "mover" not in mt(123), mt(123))
item(124, subject="[zed] clear both", **{**WAITING_KEYS, LEG: HELP})
try:
    upd(124, clear_wait=True, post_wake_mover=HELP)
    check("5 clear_wait with the old parameter in the same call is refused as before", False, mt(124))
except Exception as e:  # noqa: BLE001
    check("5 clear_wait with the old parameter in the same call is refused as before", "does not go with" in str(e), str(e))
item(125, subject="[zed] the old parameter", needs=[BACK])
upd(125, wait_kind="time", hold=True, wake=FUT, post_wake_mover=HELP)
check("5 the old parameter is untouched here: it still stores the old key (the alias is a later change)", mt(125).get(LEG) == HELP and "mover" not in mt(125), mt(125))
# the rule on the write's own sets and drops (model.settle_picker_keys, which the update path calls after it applies a write's fields)
def applied(meta, setv=None, drop=()):
    m_ = dict(meta); _holders._model_apply(m_, "open", dict(setv or {}), set(drop)); model.settle_picker_keys(m_, dict(setv or {}), set(drop), model.waits_stored(meta)); return m_
RELAY = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT, "needs": [BACK]}
m_ = applied({**RELAY, "mover": OWN, "then": HELP}, drop={"ask_by"})
check("5 one wait field dropped is no clear_wait: a mover that is he stays", m_.get("mover") == OWN and "ask_by" not in m_, m_)
m_ = applied({**RELAY, "mover": OWN, "then": HELP}, setv={"mover": OWN}, drop=set(model.WAIT_GROUP))
check("5 clear_wait beside a mover the same write sets: the mover the write names stays, whoever it is", m_.get("mover") == OWN and "wait_kind" not in m_, m_)
m_ = applied({**RELAY, LEG: HELP}, setv={"mover": BACK, LEG: FRONT})
check("5 a write that names the old key itself (the old parameter) is stored as written, beside its mover", m_.get("mover") == BACK and m_.get(LEG) == FRONT, m_)
m_ = applied({**RELAY, LEG: HELP}, setv={"mover": BACK})
check("5 …and one that names only the mover drops the old key", stores_mover(m_, BACK), m_)
m_ = applied({**RELAY, LEG: HELP, "mover": HELP}, drop={"mover"})
check("5 clear_mover drops both keys at the function too", "mover" not in m_ and LEG not in m_, m_)
# external in needs: the rule is the same, and the end of a wait on a date alone is the one the earlier rule decided (only the old key turns it)
item(126, subject="[zed] external, date only", needs=[BACK, "external"], until=FUT, **{LEG: HELP})
upd(126, mover=BACK)
check("5 external in needs, a wait on a date alone, the old key stored, an update sets mover: the old key goes (the one picker is the new mover)", stores_mover(mt(126), BACK), mt(126))
item(128, subject="[zed] date only, old key", needs=[BACK], until=FUT, **{LEG: HELP})
upd(128, mover=BACK)
check("5 a wait on a date alone (stored as an until, folded for the write): a mover set drops the old key like any wait", stores_mover(mt(128), BACK) and mt(128).get("until") == FUT, mt(128))
item(129, subject="[zed] date only, he picks it up", needs=[BACK], until=FUT, mover=OWN, then=HELP)
upd(129, clear_wait=True)
check("5 clear_wait on a wait on a date alone that he picks up: the date, the pick-up and nothing else go", "until" not in mt(129) and "mover" not in mt(129) and mt(129).get("then") == HELP, mt(129))
item(127, subject="[zed] external, with a kind", **{**WAITING_KEYS, "needs": [BACK, "external"], LEG: HELP})
upd(127, mover=BACK)
check("5 external in needs, a wait with a kind: the same", stores_mover(mt(127), BACK), mt(127))

# ================================================================ 6. the differential: an item stored under the old key against the same stored as `mover`, read by every reader
def readers(n, meta):
    """what each reader returns for the item stored as `meta`: the picker, the session told, its word, the arrival and the item after the wake pass (the date moved into the past)."""
    item(n, subject=f"[zed] twin {n}", **meta)
    mod_ = model.derive(rd(n), now0)
    held = telling.held_by(rd(n))
    picker = (mod_.wait.mover, mod_.wait.mover_explicit, mod_.picker) if mod_.wait else (mod_.mover,)
    past = dict(meta)
    for k in ("wake", "until", "ask_by"):
        if k in past: past[k] = day(-1)
    item(n + 500, subject=f"[zed] twin fired {n}", **past)
    SENT.clear(); watching_svc.watch_pass()
    after = mt(n + 500)
    woke = after.get("woke", {})
    return {"picker": picker, "told": held[0], "word": held[1], "state": mod_.state,
            "after": {"mover": after.get("mover"), "needs": after.get("needs"), "woke_to": woke.get("to"), "then": after.get("then"), "decision": "decision" in (after.get("needs") or [])},
            "messages": sorted(x[1] for x in SENT)}
DIFFS = []
def compare(label, new_meta, n):
    a, b = readers(n, old_form(new_meta)), readers(n + 20, new_meta)
    same = {k: a[k] == b[k] for k in a}
    differs = [k for k, v in same.items() if not v]
    # the stored key is the one difference; the word held_by gives the session is `then` for the old key, `mover` for the new, never a different session
    check(f"6 {label}: the same picker, session told, arrival and item after the wake (differences: {differs or 'none'})", set(differs) <= {"word"} and a["told"] == b["told"], (a, b))
    if differs: DIFFS.append((label, differs))
    return a, b
for label, meta in (("time wait stored as mover", {**BASE, "mover": HELP, "wait_kind": "time", "hold": True, "wake": FUT}),
                    ("wait on a date alone stored as mover", {**BASE, "mover": HELP, "until": FUT}),
                    ("item wait stored as mover", {**BASE, "mover": BACK, "wait_kind": "item", "after": ["a9"], "until": FUT}),
                    ("event wait stored as mover", {**BASE, "mover": BACK, "wait_kind": "event", "wait_event": "pr_merged other/repo#7", "until": FUT}),
                    ("relay wait", {**BASE, "mover": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}),
                    ("a snapshot restore (relay) with a mover", restored({"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, needs=[BACK]))):
    compare(label, meta, 200 + 3 * len(DIFFS) + len(ran) % 7)
# he is the picker: a relay turns to him, the then beside him is read
a, b = compare("relay wait he picks up, then beside him", {**BASE, "mover": OWN, "then": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}, 300)
check("6 …he picks it up, and then stands beside him", a["after"]["decision"] and b["after"]["decision"] and a["after"]["then"] == b["after"]["then"], (a, b))
# external in needs, a wait on a date alone: the stored picker's key decides the end (PR one's rule): only the old key turns it. A hand-over stores no picker for it, so the shape does not arise from a writer here.
a = readers(310, {**BASE, "needs": [BACK, "external"], LEG: HELP, "until": FUT})
b = readers(311, {**BASE, "needs": [BACK, "external"], "mover": HELP, "until": FUT})
check("6 external in needs, a date-only wait, stored under the old key versus mover: the earlier rule still holds (only the old key turns the item to its picker; a stored mover alone ends on the date)",
      a["after"]["needs"] == [HELP] and b["after"]["needs"] == [BACK, "external"] and a["picker"] == b["picker"], (a, b))

# ================================================================ 7. a stored old key the save rule drops is no change to the wait: its chases and its clock stay
SET_AT = now0 - 5000.0
CHASES = [{"at": now0 - 100, "by": "the server", "note": "a chase"}]
WAITS = {"relay": dict(wait_kind="relay", wait_event="the reply", ask_by=FUT),
         "anchor": dict(wait_kind="anchor", wait_anchor="https://github.com/acme/widgets/issues/5", wait_event="the reply", ask_by=FUT),
         "time": dict(wait_kind="time", hold=True, wake=FUT)}
SHAPES = {"old key": {LEG: HELP}, "both": {LEG: HELP, "mover": BACK}, "mover": {"mover": HELP}, "nothing": {}}
WRITES = {"mover=": dict(mover=FRONT), "clear_mover": dict(clear_mover=True), "a plain note": dict(next="zed-back: a note")}
n7 = 700
for wl, wmeta in WAITS.items():
    for sl, smeta in SHAPES.items():
        for ol, kw in WRITES.items():
            n7 += 1
            item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **wmeta, **smeta)
            try:
                upd(n7, **kw); err = ""
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            m_ = mt(n7)
            check(f"7 {wl} wait, {sl} stored, {ol}: the chases and the wait's clock stay as they were{(' (refused: ' + err + ')') if err else ''}", not err and m_.get("chases") == CHASES and (m_.get("watch") or {}).get("set_at") == SET_AT, m_)
# what does change the wait still restarts it: a moved date, and the old key named on purpose
for wl, kw in (("relay", dict(ask_by=day(9))), ("relay", dict(post_wake_mover=BACK))):
    n7 += 1
    item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **WAITS[wl], **{LEG: HELP})
    upd(n7, **kw)
    m_ = mt(n7)
    check(f"7 {wl} wait, an update of {sorted(kw)[0]}: the wait is new, so its clock is stamped and its chases start over (as on main)", "chases" not in m_ and (m_.get("watch") or {}).get("set_at", 0) > SET_AT, m_)

n7 += 1
item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **WAITS["relay"], **{LEG: HELP})
try:
    upd(n7, mover=FRONT, post_wake_mover="none"); err = ""
except Exception as e:  # noqa: BLE001
    err = str(e)[:200]
m_ = mt(n7)
check(f"7 relay wait, the old key cleared on purpose beside a mover (post_wake_mover=none): the wait is new, so its clock is stamped and its chases start over (as on main){(' (refused: ' + err + ')') if err else ''}", not err and LEG not in m_ and "chases" not in m_ and (m_.get("watch") or {}).get("set_at", 0) > SET_AT, (m_, err))

# ================================================================ 8. a mover that restates the old key changes nothing
def after_wake(n, meta):
    """the stored item, one day on: what the wake pass makes of it (readers' twin with its date in the past)."""
    return readers(n, {k: v for k, v in meta.items() if k not in ("owner", "project")})
EXT = dict(needs=[BACK, "external"], until=FUT)
for label, extra, kw, keeps in (("the same session as the old key", {LEG: HELP}, dict(mover=HELP), True), ("…named in another case", {LEG: HELP}, dict(mover=HELP.upper()), True),
                                ("another session", {LEG: HELP}, dict(mover=BACK), False)):
    n7 += 1
    item(n7, subject=f"[zed] external {n7}", **EXT, **extra)
    upd(n7, **kw)
    m_ = mt(n7)
    r_ = after_wake(n7 + 100, m_)
    check(f"8 external in needs, a wait on a date alone, the old key stored, an update sets mover to {label}: the old key {'stays' if keeps else 'goes'}", (m_.get(LEG) == HELP) == keeps and (LEG not in m_) == (not keeps), m_)
    check(f"8 …and the item ends as {'it did on main (turned alive to the old key agent)' if keeps else 'the new mover has it (a choice of this change: it ends on its date, external still in needs)'}",
          (r_["after"]["needs"] == [HELP]) if keeps else (r_["after"]["needs"] == [BACK, "external"]), r_)
n7 += 1
item(n7, subject=f"[zed] both, equal {n7}", **{**WAITING_KEYS, LEG: HELP, "mover": BACK})
upd(n7, mover=HELP)
check("8 both keys stored with different values, an update sets mover to the old key's session: both name it, the old key stays", mt(n7).get(LEG) == HELP and mt(n7).get("mover") == HELP, mt(n7))
n7 += 1
item(n7, subject=f"[zed] then another {n7}", **{**WAITING_KEYS, LEG: HELP})
upd(n7, mover=HELP); upd(n7, mover=BACK)
check("8 …and a later write of another mover drops it", stores_mover(mt(n7), BACK), mt(n7))
check("8 the rule at the function: a mover equal to the old key (any case) leaves it, a different one drops it",
      applied({**RELAY, LEG: HELP}, setv={"mover": HELP}).get(LEG) == HELP and applied({**RELAY, LEG: HELP}, setv={"mover": HELP.upper()}).get(LEG) == HELP and LEG not in applied({**RELAY, LEG: HELP}, setv={"mover": BACK}), None)
# the migration route, too: a write that sets the mover the old key already names leaves the old key
guards(True)
try:
    for n_, sets, label, gone in ((40, {"mover": HELP}, "a set mover equal to the old key leaves it", False), (41, {"mover": BACK}, "a different one drops it", True)):
        item(n_, subject=f"[zed] migrate {n_}", needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=day(5), **{LEG: HELP})
        it_ = rd(n_)
        out = migsvc.migrate_one({"item": f"a{n_}", "set": sets, "drop": [], "expect": it_["updated"], "expect_sig": list(migsvc.migrate_sig(f"a{n_}", it_)), "kind": "test", "note": "t"})
        check(f"8 migration route: {label}", out["action"] in ("set", "already") and ((LEG not in mt(n_)) == gone) and mt(n_).get("mover") == sets["mover"], (out, mt(n_)))
finally:
    guards(False)

# ================================================================ 9. a clear ends as on main for every writer of a wait's picker (the design of what a clear leaves is a later step)
# The wait-end fix, the decision hand-over and a restored wait still store the old key: stored as `mover`, an agent that is not the default mover would stay on as the live mover after a clear_wait, with a
# hand-off record and a notice; on main the old key went with the wait group and the item ended alive on its default mover. Each clear below ends as it always did.
def cleared(n, meta, **kw):
    item(n, subject=f"[zed] clear {n}", **{k: v for k, v in meta.items() if k not in ("next",)})
    SENT.clear(); upd(n, **kw)
    m_ = mt(n); mod_ = model.derive(rd(n), now0)
    return m_, mod_, list(SENT)
def fixed(n, nxt, **meta):
    clear_g(); gitem(9202, "zed-helper: build the thing"); gitem(n, nxt, **meta); fix_pass(); return mt(n, "g")
CASES = (("the wait-end fix (after), another session stored as the mover", fixed(9205, f"zed-helper: wait for {ref(9202)} to close, then write the summary", mover=HELP), dict(clear_wait=True), "no picker"),
         ("the wait-end fix (event), another session stored as the mover", fixed(9215, "zed-helper: wait for other/repo#7 to be merged, then write the summary", mover=HELP), dict(clear_wait=True), "alive"),
         ("the wait-end fix (anchor)", fixed(9216, "zed-back: wait for the reply in https://github.com/acme/widgets/issues/5"), dict(clear_wait=True), "alive"),
         ("a hand-over (a hold with a wake)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True), dict(clear_hold=True), "alive"),
         ("a hand-over (a parked item)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, parked=True), dict(clear_hold=True), "alive"),
         ("a hand-over (a wait on a date alone)", hand({**BASE, "mover": OWN, "then": HELP, "until": FUT}, OWN, HELP, waiting=True), dict(clear_wait=True), "alive"),
         ("a restored wait (old snapshot)", restored({"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, needs=[BACK]), dict(clear_wait=True), "alive"),
         ("a restored wait (new snapshot: a stored agent mover, which a clear_wait keeps as on main)", restored({"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, needs=[BACK]), dict(clear_wait=True), "agent stays"))
n9 = 800
for label, meta, kw, want in CASES:
    n9 += 1
    clear_g()
    m0 = {k: v for k, v in meta.items() if k not in ("watch",)}
    if label.startswith("the wait-end fix"):
        check(f"9 {label}: stores the picker under the old key, as on main", m0.get(LEG) in (BACK, HELP) and "mover" not in m0, m0)
    m_, mod_, sent = cleared(n9, m0, **kw)
    op = sorted(kw)[0]
    if want == "alive":
        check(f"9 {label}, {op}: the wait, the picker and the pick-up are gone, the item is alive on the default mover ({BACK}), nobody is told", mod_.state == "alive" and mod_.mover == BACK and not any(k in m_ for k in ("wait_kind", "mover", LEG, "until", "hold", "wake")) and not sent, (m_, mod_.mover, sent))
    elif want == "no picker":
        check(f"9 {label}, {op}: no picker is left stored and nobody is told (the item waits on its open after link)", not any(k in m_ for k in ("wait_kind", "mover", LEG)) and not sent, (m_, sent))
    else:
        check(f"9 {label}, {op}: the agent stays the live mover (the one clear_wait rule, as on main)", m_.get("mover") == HELP and LEG not in m_ and mod_.state == "alive", (m_, mod_.mover))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": mover writers scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
