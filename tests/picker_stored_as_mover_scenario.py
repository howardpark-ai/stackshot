"""Scenario test: the agent a waiting item was handed to stays its live mover when the wait or the hold ends — fixture data, no live store, no network, no server socket.

A waiting item stores who picks it up when the wait ends as `mover` (an old item may still store it under the old key `post_wake_mover`). A wait or a hold never changes who moves the item: only a `mover` write or a hand-over
does. So `clear_wait` and `clear_hold` leave the agent the item was handed to as the mover, never the default mover (the project's builder), whichever key stored it. Covered:

  A  hand-over       a decision's hand-over of a hold with a wake, a parked item and a wait on a date alone, then clear_hold / clear_wait, with the guards off and on
  B  wait-end fix    the filing pass's fix of an after, event and anchor wait stores the picker as `mover`; clear_wait leaves that agent as the mover
  C  snapshot        remember and restore_wait hold and put back the picker as `mover` (an old snapshot too); the server's own answers on a snapshot
  D  old key         an item that still stores the old key: clear_wait and clear_hold keep its agent as the mover; an owner picker, a `mover=` in the same call, clear_mover; reads equal
  E  no fallback     none of the above makes the default mover the mover or tells it

    tests/run-suite picker_stored_as_mover        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="pickeramover-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml, n = re.subn(r'(?m)^session_links = .*$', 'session_links = ""', toml); assert n == 1
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

# ================================================================ the writers' own helpers
def hand(meta, mover_in, then_in, **kw):
    m_ = dict(meta); handover_svc._decision_hand_over(m_, mover_in, then_in, now=now0, **kw); return m_
BASE = {"project": "projects/zedwork", "needs": [BACK]}
def upd(n, **kw): return _update_svc._update(f"a{n}", sender=BACK, **kw)
def remembered(meta):
    m_ = dict(meta); wk.remember(m_, "relay", now0); return m_
def restored(m_):
    m_ = dict(m_); wk.restore_wait(m_, day(9), True, now0); return m_
def fixed(n, nxt, **meta):
    clear_g(); gitem(9202, "zed-helper: build the thing"); gitem(n, nxt, **meta); fix_pass(); return mt(n, "g")
N = [1000]
def cleared(meta, **kw):
    """store `meta` as an item, write `kw` (a clear) on it: → the item's metadata after, its reading, the messages sent."""
    N[0] += 1
    item(N[0], subject=f"[zed] picker {N[0]}", **{k: v for k, v in meta.items() if k != "next"})
    SENT.clear(); upd(N[0], **kw)
    return mt(N[0]), model.derive(rd(N[0]), now0), [x[0] for x in SENT]
def waiting_who(mod_): return mod_.wait.mover if mod_.wait else mod_.mover
def never_default(label, m_, mod_, who, alive=True):
    """the one rule: the agent the item was handed to stays its mover, the default mover (the project's builder) never takes it, and no old key is left."""
    check(f"{label}: {who} stays the mover, the old key is gone", m_.get("mover") == who and LEG not in m_, m_)
    check(f"{label}: the item reads as moved by {who}, not by the default mover ({BACK})", waiting_who(mod_) == who and (mod_.state == "alive") == alive, (mod_.state, mod_.mover, waiting_who(mod_)))

# ================================================================ A. a hand-over, then clear_wait / clear_hold, with the guards off and on
HAND_SHAPES = (("a hold with a wake", {"hold": True, "wake": FUT}, dict(waiting=True)), ("a parked item", {"hold": True, "wake": FUT}, dict(parked=True)), ("a wait on a date alone", {"until": FUT}, dict(waiting=True)))
for g_ in (False, True):
    guards(g_)
    tag = f"(guards {'on' if g_ else 'off'})"
    for label, extra, kw in HAND_SHAPES:
        stored = hand({**BASE, "mover": OWN, "then": HELP, **extra}, OWN, HELP, **kw)
        check(f"A hand-over of {label} stores the picker as `mover`, the old key never {tag}", stores_mover(stored, HELP) and "then" not in stored, stored)
        for clear in ("clear_hold", "clear_wait"):
            if clear == "clear_wait" and "hold" in extra:
                continue          # clear_wait leaves a hold's own flag and date alone (they are cleared with clear_hold)
            m_, mod_, sent = cleared(stored, **{clear: True})
            never_default(f"A hand-over of {label}, {clear} {tag}", m_, mod_, HELP)
            check(f"A hand-over of {label}, {clear} {tag}: nothing of the wait is left stored", not any(k in m_ for k in (*model.WAIT_GROUP, "hold", "wake")), m_)
guards(False)
# the hand-over of an item waiting on others, or one with a stored wait of its own, stores nothing new for the picker
for label, meta in (("external in needs", {**BASE, "needs": [BACK, "external"], "mover": OWN, "then": HELP, "until": FUT}), ("an open after link", {**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT, "after": ["a1"]})):
    item(1, subject="[zed] an open item the others wait after")
    m_ = hand(meta, OWN, HELP, waiting=True)
    check(f"A hand-over with {label}: no picker is stored as before", LEG not in m_ and "mover" not in m_, m_)

# ================================================================ B. the wait-end fix (the filing pass; its after wait has no end the guards would accept, so the guards stay off here)
for g_ in (False,):
    guards(g_)
    tag = f"(guards {'on' if g_ else 'off'})"
    for n, label, nxt in ((9301, "after", f"zed-back: wait for {ref(9202)} to close, then write the summary"),
                          (9302, "event", "zed-back: wait for other/repo#7 to be merged, then write the summary"),
                          (9303, "anchor", "zed-back: wait for the reply in https://github.com/acme/widgets/issues/5")):
        m0 = fixed(n, nxt)
        check(f"B the wait-end fix ({label}) stores the picker as `mover` and no old key {tag}", stores_mover(m0, BACK) and "wait_kind" in m0, m0)
        m_, mod_, sent = cleared(m0, clear_wait=True)
        never_default(f"B the wait-end fix ({label}), clear_wait {tag}", m_, mod_, BACK, alive=label != "after")   # an after link to an open item still holds the item
        check(f"B the wait-end fix ({label}), clear_wait {tag}: no old key and no wait are stored", not any(k in m_ for k in model.WAIT_GROUP), m_)
guards(False)
clear_g()
m0 = fixed(9305, f"zed-back: wait for {ref(9202)} to close, then write the summary")
check("B the wait-end fix with the default mover as the picker: stored as `mover` too", stores_mover(m0, BACK), m0)
clear_g()

# ================================================================ C. remember and restore_wait: the snapshot holds the picker as `mover`, the round trip puts it back
RW = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "needs": [BACK]}
for label, meta in (("stored as mover", {**RW, "mover": HELP}), ("stored under the old key", {**RW, LEG: HELP}), ("both stored", {**RW, LEG: HELP, "mover": BACK})):
    snap = remembered(meta)["watch"]["was"]
    check(f"C remember, {label}: the snapshot holds `mover`={HELP} and no old key", stores_mover(snap, HELP), snap)
    now = {"project": "projects/zedwork", "needs": ["decision"], "ask": "x", "watch": remembered(meta)["watch"]}
    back = restored(now)
    check(f"C round trip, {label}: the wait is back with the picker stored as `mover` and the new date", stores_mover(back, HELP) and back.get("wait_kind") == "relay" and back.get("ask_by") == day(9), back)
    for g_ in (False, True):
        guards(g_)
        m_, mod_, sent = cleared({**back, "needs": [BACK]}, clear_wait=True)
        never_default(f"C round trip, {label}, clear_wait (guards {'on' if g_ else 'off'})", m_, mod_, HELP)
    guards(False)
old_snap = {"project": "projects/zedwork", "needs": ["decision"], "ask": "x", "watch": {"asked": "relay", "was": {**{k: v for k, v in RW.items() if k != "ask_by"}, "ask_by": day(-1), LEG: HELP}, "at": now0}}
check("C an old snapshot (the old key) is put back as `mover`", stores_mover(restored(old_snap), HELP), restored(old_snap))
check("C was_picker reads the old key, `mover` and both, as before", wk.was_picker({LEG: HELP}) == wk.was_picker({"mover": HELP}) == HELP and wk.was_picker({LEG: BACK, "mover": HELP}) == BACK, None)
check("C a snapshot's word none under the old key stays as stored (a session of that name there)", remembered({**RW, LEG: "none"})["watch"]["was"].get(LEG) == "none" and "mover" not in remembered({**RW, LEG: "none"})["watch"]["was"], None)
# the server's own end of a watcher ask: "not yet" puts the wait back, "arrived" hands the item to the picker
for n, was in ((20, {LEG: HELP}), (21, {"mover": HELP})):
    item(n, subject=f"[zed] was {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
    m_ = dict(mt(n)); r = wait_gates_svc._watch_answer(rd(n), m_, {"do": "wait", "text": "", "date": day(9)}, now0)
    check(f"C 'not yet' on a snapshot of {sorted(was)[0]}: the wait is back with the picker stored as `mover`", stores_mover(m_, HELP) and m_.get("ask_by") == day(9), (r, m_))
    item(n + 10, subject=f"[zed] was again {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
    m_ = dict(mt(n + 10)); r = wait_gates_svc._watch_answer(rd(n + 10), m_, {"do": "arrived", "text": "", "date": ""}, now0)
    check(f"C 'arrived' on a snapshot of {sorted(was)[0]}: the agent it names has the item", m_.get("mover") == HELP and m_.get("needs") == [HELP], (r, m_))

# ================================================================ D. an old item that still stores the picker under the old key
OLD_WAITS = (("a relay wait", {"wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}, "clear_wait"),
             ("an anchor wait", {"wait_kind": "anchor", "wait_anchor": "https://github.com/acme/widgets/issues/5", "wait_event": "the reply", "ask_by": FUT}, "clear_wait"),
             ("an event wait", {"wait_kind": "event", "wait_event": "pr_merged other/repo#7", "until": FUT}, "clear_wait"),
             ("a time wait on a hold", {"wait_kind": "time", "hold": True, "wake": FUT}, "clear_hold"),
             ("a wait on a date alone", {"until": FUT}, "clear_hold"),
             ("a wait on a date alone", {"until": FUT}, "clear_wait"),
             )
for g_ in (False, True):
    guards(g_)
    tag = f"(guards {'on' if g_ else 'off'})"
    for label, wait, clear in OLD_WAITS:
        meta = {**BASE, **wait, LEG: HELP}
        m_, mod_, sent = cleared(meta, **{clear: True})
        never_default(f"D an old item, {label}, {clear} {tag}", m_, mod_, HELP)
        check(f"D an old item, {label}, {clear} {tag}: nothing of the wait is left stored", not any(k in m_ for k in (*model.WAIT_GROUP, "hold", "wake")), m_)
        m2, mod2, _ = cleared({**meta, "mover": HELP}, **{clear: True})
        never_default(f"D an item storing both keys, {label}, {clear} {tag}", m2, mod2, HELP)
guards(False)
# what a clear does not keep
WAITS_ = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}
m_, mod_, sent = cleared({**BASE, **WAITS_, LEG: OWN}, clear_wait=True)
check("D an old key that names he: he picked the item up when the wait ended, so no mover is kept", "mover" not in m_ and LEG not in m_ and "wait_kind" not in m_, m_)
m_, mod_, sent = cleared({**BASE, **WAITS_, LEG: HELP}, clear_wait=True, mover=BACK)
check("D a clear that names a mover: the mover the write names is the one (no pick-up is kept over it)", m_.get("mover") == BACK and LEG not in m_, m_)
m_, mod_, sent = cleared({**BASE, **WAITS_, LEG: HELP}, clear_wait=True, clear_mover=True)
check("D a clear beside clear_mover: nobody is kept", "mover" not in m_ and LEG not in m_ and "wait_kind" not in m_, m_)
m_, mod_, sent = cleared({**BASE, **WAITS_, LEG: HELP}, ask_by=day(8))
check("D a write that leaves the wait standing keeps the old key as it was (no migration of stored items here)", m_.get(LEG) == HELP and "mover" not in m_, m_)
# the reads of an item that still stores the old key are as before: the same picker, the same session told
for label, wait in (("a relay wait", OLD_WAITS[0][1]), ("a time wait", OLD_WAITS[3][1]), ("a wait on a date alone", OLD_WAITS[4][1])):
    a_, b_ = D(**{**BASE, **wait, LEG: HELP}), D(**{**BASE, **wait, "mover": HELP})
    check(f"D reads: {label} stored under the old key reads as the one stored as `mover` (the picker {HELP}, the same state)", a_.state == b_.state == "waiting" and a_.wait.mover == b_.wait.mover == HELP, (a_.wait, b_.wait))

# ================================================================ E. no fallback: a clear that ends a wait never hands the item to the project's builder
for label, meta, clear in (("a hand-over (a hold with a wake)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True), "clear_hold"),
                           ("an old item (a relay wait)", {**BASE, **WAITS_, LEG: HELP}, "clear_wait")):
    m_, mod_, sent = cleared(meta, **{clear: True})
    check(f"E {label}, {clear}: the default mover ({BACK}) is not made the mover, and is told nothing it did not have", m_.get("mover") != BACK and waiting_who(mod_) != BACK and BACK not in sent, (m_, sent))
clear_g()

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": picker stored as mover scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
