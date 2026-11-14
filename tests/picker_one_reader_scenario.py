"""Scenario test for the one reader of a waiting item's stored picker, and the safe `settle` — fixture data, no live store, no network, no server socket.

A waiting item's picker (who takes it when the wait ends) is stored under `mover`, or, in the older form, under `post_wake_mover`. Every reader goes through `model.stored_picker` (and
`watchers.was_picker` for a `watch.was` snapshot), so the two forms read the same everywhere. `model.settle`'s waiting branch (a stored mover that is he, on an item that stood his and now waits)
runs only from the update path (`waiting=True`): the on-save backstop and the start repair leave a waiting item's stored mover alone, since that is where "he picks it up when the wait ends" is written. Covered:

  1  one reader     the picker table through stored_picker, derive, Wait.mover, the view-only wait, waiting.mover_of, telling.held_by, the orphan hand-over's keys and was_picker (old and new snapshot)
  2  end of a wait  a wait on a date alone with a stored mover (no legacy key) ends through turn_alive; with nothing stored through end_date; with the legacy key through turn_alive
  3  settle         the waiting branch only with waiting=True; the alive branches as they were; the on-save backstop and the start repair leave a waiting item's stored mover alone
  4  writers        each writer that turns an item that stood his into a waiting one, and what it leaves stored: the update path, a decision's hand-over, the watchers' turn to him, the board answer, the wait-end fix
  5  phase          waiting before your move before on agent, for a table of items

    tests/run-suite picker_one_reader        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="pickerone-"); T = pathlib.Path(tmp)
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
OLD = now0 - 3 * 3600.0          # last written three hours ago: past the settle window
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
from stackshot.service import mover_steps as _mover_steps
from stackshot.waits import handoff as _ho
from stackshot.audit import audit_run as AR
from stackshot.core import config as _cfg
from stackshot.service import store as _service_store
from stackshot.service import handoff as handoff_svc
from stackshot.service import migrations as migsvc
from stackshot.service import watching as watching_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import writes
from stackshot.service import event_waits as evwaits_svc
from stackshot.service import telling
from stackshot.fleet import liveness as LV
from stackshot.web import home
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
SENT = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
telling.front_sender = lambda who: False
server._own_repo = lambda: "acme/widgets"
server._evwait_preread = lambda kind, phrase: None
evwaits_svc.evw_boxes = lambda: {}
LV.puller_online = lambda rec: bool(rec)
(T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
ZONE_HOURS = 4
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
OWN = model.owner_display()
FB = telling.fallback_mover("projects/zedwork")
assert FB, FB
FUT = day(5)
D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
def its(**meta): return {"status": "open", "metadata": {"project": "projects/zedwork", **meta}}
def guards(on):
    CFG["guards"] = on

# ================================================================ 1. one reader
# the picker as stored → what every reader says. (legacy key, stored mover) → the picker; "" is no stored picker.
TABLE = [
    ("legacy key only",                      dict(post_wake_mover=HELP),                       HELP),
    ("mover only",                           dict(mover=HELP),                                 HELP),
    ("both stored and equal",                dict(post_wake_mover=HELP, mover=HELP),           HELP),
    ("both stored and different: the legacy key wins", dict(post_wake_mover=BACK, mover=HELP), BACK),
    ("a legacy key that is he, beside an agent mover", dict(post_wake_mover=OWN, mover=HELP),  OWN),
    ("a mover that is he, beside an agent legacy key", dict(post_wake_mover=HELP, mover=OWN),  HELP),
    ("a mover that is he, no legacy key",    dict(mover=OWN),                                  OWN),
    ("the word none as a mover",             dict(mover="None"),                               ""),
    ("the word none beside a legacy key",    dict(mover="none", post_wake_mover=HELP),         HELP),
    ("neither",                              dict(),                                           ""),
    ("whitespace is collapsed",              dict(mover="  zed-helper  "),                     HELP),
]
for label, st, want in TABLE:
    check(f"1 stored_picker: {label}", model.stored_picker(st) == want, model.stored_picker(st))
check("1 stored_picker: a missing metadata reads as nothing stored", model.stored_picker({}) == "" and model.stored_picker(None) == "", None)
check("1 the legacy key's name is one constant", model.LEGACY_PICKER_KEY == "post_wake_mover", model.LEGACY_PICKER_KEY)

BASE = dict(needs=[BACK], hold=True, wake=FUT, wait_kind="time")
for label, st, want in TABLE:
    mod = D(**BASE, **st)
    exp = want or BACK        # the default picker when none is stored: the first session in needs
    check(f"1 derive: {label}: the wait's mover is the picker, explicit exactly when one is stored", mod.wait.mover == exp and mod.wait.mover_explicit == bool(want) and mod.picker == exp, mod)
    check(f"1 derive: {label}: the item's own mover stays empty while it waits", mod.mover == "", mod)
    both = st.get("post_wake_mover") and st.get("mover") and model.pick_who(st["mover"]) and model.norm_who(st["post_wake_mover"]) != model.pick_who(st["mover"])
    check(f"1 derive: {label}: one conflict line exactly when both are stored and differ", len(mod.conflicts) == (1 if both else 0), mod.conflicts)
    # the reading of a stored wait the clock has outdated (a view-only wait), read by the same helper
    alive_mod = D(needs=[BACK], **st)
    wm = model._wait_of(its(needs=[BACK], **st), alive_mod, "time")
    check(f"1 view-only wait: {label}", wm.wait.mover == (want or alive_mod.mover) and wm.wait.mover_explicit == bool(want), wm)
    mo = waiting.mover_of({"needs": [], "project": "projects/zedwork", **st})
    exp_mo = (want if want and want != OWN else (model.pick_who(st.get("mover")) if model.pick_who(st.get("mover")) and model.pick_who(st.get("mover")) != OWN else "")) or waiting.fallback_mover("projects/zedwork")
    check(f"1 mover_of: {label}", mo == {"kind": "session", "who": exp_mo}, mo)
    check(f"1 mover_of: {label}: the owner is never returned as a session name", not model.is_owner(mo["who"]), mo)

# a stored picker the item never names in needs is who holds a waiting item (held_by): the legacy key reads as `then`, a stored mover as `mover`, as before
item(1, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, subject="[zed] a picker by mover")
item(2, needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=HELP, subject="[zed] a picker by the old name")
item(3, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=BACK, subject="[zed] two pickers")
item(4, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up")
HB = lambda n: telling.held_by(_service_store._load(f"a{n}"))
check("1 held_by: a picker stored as mover holds the item, worded mover (the notice text does not change)", HB(1) == (HELP, "mover"), HB(1))
check("1 held_by: …stored under the old name, worded then", HB(2) == (HELP, "then"), HB(2))
check("1 held_by: …both stored and different: the old name is read first", HB(3) == (BACK, "then"), HB(3))
check("1 held_by: …he picks it up: the then beside him holds it", HB(4) == (HELP, "then"), HB(4))
check("1 held_by: the same agent through either key", HB(1)[0] == HB(2)[0] == HELP, (HB(1), HB(2)))

# the audit's hand-over to the closest live agent follows the stored keys: the legacy key too
def orphan(**meta):
    it = {"id": "950", "gid": "a950", "subject": "[zed] orphan", "status": "open", "metadata": {"project": "projects/zedwork", "needs": [BACK], **meta}}
    handoff_svc.handoff_write_move(it, _ho.Step("move", "a950", "its holder is gone", frm=BACK, to=HELP, via="orphan"), now0)
    return it["metadata"]
m_ = orphan(post_wake_mover=BACK, hold=True, wake=FUT, wait_kind="time")
check("1 orphan keys: the legacy key that named the old holder follows to the new one", m_.get("post_wake_mover") == HELP and m_["needs"][0] == HELP, m_)
m_ = orphan(mover=BACK, hold=True, wake=FUT, wait_kind="time")
check("1 orphan keys: …a stored mover that named it follows too, and no legacy key appears", m_.get("mover") == HELP and "post_wake_mover" not in m_, m_)
m_ = orphan(mover=BACK, then=BACK, post_wake_mover=BACK, hold=True, wake=FUT, wait_kind="time")
check("1 orphan keys: …all three follow", (m_.get("mover"), m_.get("then"), m_.get("post_wake_mover")) == (HELP, HELP, HELP), m_)

# a watch.was snapshot: written by older code under the legacy key, by newer code under mover
check("1 was_picker: an old snapshot (the legacy key)", wk.was_picker({"post_wake_mover": HELP, "wait_kind": "relay"}) == HELP, None)
check("1 was_picker: …a new one (mover)", wk.was_picker({"mover": HELP, "wait_kind": "relay"}) == HELP, None)
check("1 was_picker: …both: the legacy key first, as everywhere", wk.was_picker({"post_wake_mover": BACK, "mover": HELP}) == BACK, None)
check("1 was_picker: …none, or no snapshot, names nobody", wk.was_picker({"mover": "none"}) == "" and wk.was_picker({}) == "" and wk.was_picker(None) == "", None)
# and the server's read of it: his "arrived" or his words on a relay go to the agent the snapshot names, either form
for n, was in ((6, {"post_wake_mover": HELP}), (7, {"mover": HELP})):
    key = sorted(was)[0]
    ASKED = dict(needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}],
                 watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
    item(n, subject=f"[zed] was {n}", **ASKED)
    m_ = dict(mt(n))
    r = server._watch_answer(rd(n), m_, {"do": "arrived", "text": "", "date": ""}, now0)
    check(f"1 _watch_answer arrived: a snapshot under {key}: the item goes to the agent it names, alive", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))
    item(n + 10, subject=f"[zed] was words {n}", **ASKED)
    m_ = dict(mt(n + 10))
    r = server._watch_answer(rd(n + 10), m_, {"do": "words", "text": "not yet", "date": ""}, now0)
    check(f"1 _watch_answer words: a snapshot under {key}: the agent it names has the item", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))

# ================================================================ 2. the end of a wait on a date alone
def fire(n, **meta):
    """an item that waits on a date alone (no wait_kind), the date passed: run the watchers' pass and return what was stored."""
    item(n, needs=[BACK], until=day(-1), **meta)
    SENT.clear(); moved = watching_svc.watch_pass()
    return f"a{n}" in moved, mt(n)
ok_, m_ = fire(20, mover=HELP)
check("2 a date-only wait with a stored mover (no legacy key) ends through turn_alive: the mover has it, needs is the mover, then is popped, the arrival is recorded",
      ok_ and m_.get("mover") == HELP and m_.get("needs") == [HELP] and "then" not in m_ and m_.get("woke", {}).get("to") == HELP and "until" not in m_, m_)
ok_, m_ = fire(21, mover=HELP, then=FRONT)
check("2 …a then stored beside it goes with the wait, as turn_alive drops it", ok_ and m_.get("mover") == HELP and "then" not in m_, m_)
ok_, m_ = fire(22)
check("2 a date-only wait with nothing stored ends through end_date: needs stays as stored, the arrival is recorded, no mover is written",
      ok_ and m_.get("needs") == [BACK] and "mover" not in m_ and m_.get("woke", {}).get("to") == BACK and "until" not in m_, m_)
ok_, m_ = fire(23, post_wake_mover=HELP)
check("2 a date-only wait with the legacy key ends through turn_alive: the agent has it, the legacy key is gone", ok_ and m_.get("mover") == HELP and m_.get("needs") == [HELP] and "post_wake_mover" not in m_, m_)
ok_, m_ = fire(24, mover="none")
check("2 …the word none as a mover is no stored picker: end_date, needs stays", ok_ and m_.get("needs") == [BACK] and m_.get("mover") == "none", m_)
ok_, m_ = fire(25, mover=OWN, then=HELP)
check("2 a date-only wait he picks up turns to him with his ask, the then kept beside him (unchanged)", ok_ and m_.get("needs") == ["decision"] and m_.get("then") == HELP and "mover" not in m_, m_)
item(26, needs=[BACK], wait_kind="time", wake=day(-1), mover=HELP, hold=True)
moved = watching_svc.watch_pass()
check("2 a wait with a kind and a stored mover still ends through turn_alive (unchanged)", "a26" in moved and mt(26).get("needs") == [HELP] and mt(26).get("mover") == HELP, mt(26))

# the end of a wait on a date alone, by what the item stores and whether `external` is in its needs. With external the item goes back to others at its date, as it always did: only the old key turns it
# (turn_alive); a stored mover alone ends it on the date (end_date, needs as stored). Without external a picker under either key turns it. Two forms of the date: until, and a hold with a wake.
PICKERS = (("legacy key", dict(post_wake_mover=HELP), True, True), ("stored mover only", dict(mover=HELP), True, False), ("both", dict(post_wake_mover=HELP, mover=HELP), True, True), ("neither", dict(), False, False))
NUM = 200
for ext_, needs_ in ((True, ["external"]), (False, [BACK])):
    for plabel, st, has_any, has_legacy in PICKERS:
        for dlabel, date in (("until", dict(until=day(-1))), ("wake", dict(hold=True, wake=day(-1)))):
            NUM += 1
            item(NUM, needs=list(needs_), **date, **st)
            SENT.clear(); moved = watching_svc.watch_pass() if dlabel == "until" else wakes_svc.wake_pass(); m_ = mt(NUM)      # a stored until is the watchers' pass; a hold with a wake is the wake pass's
            turns = has_legacy if ext_ else has_any          # main's result for external; the new rule (a stored mover turns it too) only without external
            want_needs = [HELP] if turns else list(needs_)
            if dlabel == "until":
                check(f"2 external={ext_}, {plabel}, a kind-less until: {'turns to the picker (needs is the picker)' if turns else 'ends on the date (needs stays as stored)'}",
                      f"a{NUM}" in moved and m_.get("needs") == want_needs and "woke" in m_ and "until" not in m_ and "post_wake_mover" not in m_
                      and (m_.get("mover") == HELP if turns else m_.get("mover") == st.get("mover")), m_)
            else:      # a hold with a wake and no kind is the wake pass's (no watcher owns it): the hold and wake go, and needs and the stored picker keys stay exactly as stored, on main and here
                check(f"2 external={ext_}, {plabel}, a kind-less hold with a wake: released by the wake pass, needs and the stored keys as stored",
                      f"a{NUM}" in moved and m_.get("needs") == list(needs_) and "hold" not in m_ and "wake" not in m_ and m_.get("post_wake_mover") == st.get("post_wake_mover") and m_.get("mover") == st.get("mover"), m_)
check("2 _ends_on_the_date: a wait with a kind never ends on the date; a missing needs reads as no external",
      not watching_svc._ends_on_the_date({"wait_kind": "time"}, D(needs=[BACK], hold=True, wake=FUT, wait_kind="time")) and watching_svc._ends_on_the_date({}, D(hold=True, wake=FUT)), None)

# ================================================================ 3. settle
WAITING_HIS = lambda **m: its(mover=OWN, until=FUT, **m)
check("3 settle: the waiting branch is off by default: a waiting item that stood his keeps its stored mover=he (mover only)", model.settle(WAITING_HIS(needs=[BACK]), True) is None, None)
check("3 settle: …also with an agent in then", model.settle(WAITING_HIS(needs=[BACK], then=BACK), True) is None, None)
check("3 settle: …and with a legacy key stored", model.settle(WAITING_HIS(needs=[BACK], then=BACK, post_wake_mover=HELP), True) is None, None)
check("3 settle: waiting=True, an agent in then: it picks the item up, then goes", model.settle(WAITING_HIS(needs=[BACK], then=BACK), True, waiting=True) == {"mover": BACK, "then": ""}, None)
check("3 settle: waiting=True, no agent in then: only the mover goes", model.settle(WAITING_HIS(needs=[BACK]), True, waiting=True) == {"mover": ""}, None)
check("3 settle: waiting=True, a legacy key stored: only the mover goes", model.settle(WAITING_HIS(needs=[BACK], then=BACK, post_wake_mover=HELP), True, waiting=True) == {"mover": ""}, None)
check("3 settle: waiting=True still needs the proof that it stood his, and leaves an agent's stored mover alone", model.settle(WAITING_HIS(needs=[BACK], then=BACK), False, waiting=True) is None
      and model.settle(its(mover=HELP, needs=[BACK], until=FUT), True, waiting=True) is None, None)
# the alive branches are as they were, with the parameter either way
for w_ in (False, True):
    check(f"3 settle alive (waiting={w_}): an agent mover on an item in his state becomes he, the agent in then", model.settle(its(mover=BACK, needs=["decision"], ask="Decide: x"), False, waiting=w_) == {"mover": OWN, "then": BACK}, None)
    check(f"3 settle alive (waiting={w_}): the hand-back: he as mover on an agent's item that stood his: the agent in then is the mover, then goes", model.settle(its(mover=OWN, then=BACK, needs=[BACK]), True, waiting=w_) == {"mover": BACK, "then": ""}, None)
    check(f"3 settle alive (waiting={w_}): …with no agent in then only the mover goes", model.settle(its(mover=OWN, needs=[BACK]), True, waiting=w_) == {"mover": ""}, None)
    check(f"3 settle alive (waiting={w_}): …and with no proof it stood his nothing changes", model.settle(its(mover=OWN, then=BACK, needs=[BACK]), False, waiting=w_) is None, None)

# the on-save backstop: an item that stood his is saved as a waiting one with his stored mover: it is left alone
guards(True)
try:
    before = its(needs=["decision"], mover=OWN, then=BACK, ask="Decide: x")
    after_ = its(needs=[BACK], mover=OWN, then=BACK, until=FUT)
    check("3 _settle_mover_on_save: a waiting item that stood his keeps its stored mover and then (nothing settled)", _mover_steps._settle_mover_on_save(after_, before) is False and after_["metadata"]["mover"] == OWN and after_["metadata"]["then"] == BACK, after_)
    alive_ = its(needs=[BACK], mover=OWN, then=BACK)
    check("3 _settle_mover_on_save: …an alive agent's item still hands back as before", _mover_steps._settle_mover_on_save(alive_, before) is True and alive_["metadata"].get("mover") == BACK and "then" not in alive_["metadata"], alive_)
    inhis = its(needs=["decision"], mover=BACK, ask="Decide: x")
    check("3 _settle_mover_on_save: …and an agent mover on his item still becomes he", _mover_steps._settle_mover_on_save(inhis, None) is True and inhis["metadata"]["mover"] == OWN and inhis["metadata"]["then"] == BACK, inhis)
    # the real save path
    item(30, needs=[BACK], mover=BACK)
    it_ = _service_store._load("a30"); it_["metadata"]["needs"] = ["decision", BACK]; it_["metadata"]["ask"] = "Decide: x"
    writes.save("a30", it_)
    check("3 writes.save: (probe) his state makes him the mover, the agent in then", mt(30).get("mover") == OWN and mt(30).get("then") == BACK, mt(30))
    it_ = _service_store._load("a30"); it_["metadata"].update(needs=[BACK], until=FUT); it_["metadata"].pop("ask", None)
    writes.save("a30", it_)
    check("3 writes.save: a save where a wait replaces his state leaves his stored mover and then (he picks it up when the wait ends)", mt(30).get("mover") == OWN and mt(30).get("then") == BACK, mt(30))
    # the start repair
    AN = [{"ts": now0 - 3600, "text": "ok", "choice": "Approve"}]
    item(31, needs=[BACK], mover=OWN, then=BACK, until=FUT, answers=AN, subject="[zed] waiting, his stored mover")
    item(32, needs=[BACK], mover=OWN, then=BACK, answers=AN, subject="[zed] alive, his stale mover")
    before31 = (T / "store/a/31.json").read_bytes()
    done = migsvc.migrate_owner_mover()
    check("3 the start repair: a waiting item's stored mover=he is left byte for byte", (T / "store/a/31.json").read_bytes() == before31 and "a31" not in done, (done, mt(31)))
    check("3 the start repair: …an alive agent's item with his stale mover is still handed back", "a32" in done and mt(32).get("mover") == BACK and "then" not in mt(32), (done, mt(32)))
finally:
    guards(False)

# ================================================================ 4. the writers: each ends with no stray stored mover
# the update path: a write that leaves an item that stood his as a waiting one and names no mover (_owner_state_mover → settle(waiting=True))
guards(True)
try:
    was_ = {"id": "40", "status": "open", "metadata": {"project": "projects/zedwork", "needs": ["decision"], "mover": OWN, "then": BACK, "ask": "Decide: x"}}
    now_ = {"id": "40", "status": "open", "metadata": {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "until": FUT}}
    meta_ = dict(now_["metadata"])
    note = _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
    check("4 update path: the stale mover=he is replaced by the agent in then, then goes, and the model reads the agent as the picker", meta_.get("mover") == BACK and "then" not in meta_ and "mover" in note
          and model.derive({**now_, "metadata": meta_}).wait.mover == BACK, (meta_, note))
    meta_ = {**now_["metadata"], "post_wake_mover": HELP}
    _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
    check("4 update path: …with the legacy key stored, only the mover goes", "mover" not in meta_ and meta_.get("post_wake_mover") == HELP and meta_.get("then") == BACK, meta_)
    meta_ = dict(now_["metadata"])
    note = _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, True, was_)
    check("4 update path: a write that names a mover itself is left alone (named)", note == "" and meta_["mover"] == OWN and meta_["then"] == BACK, (meta_, note))
    meta_ = {k: v for k, v in now_["metadata"].items() if k != "then"}
    _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
    check("4 update path: …no agent in then: only the mover goes", "mover" not in meta_, meta_)
finally:
    guards(False)

# a decision's hand-over: his answer on an item that now waits (a park, a pick carrying a wake) pops the mover itself
for label, kw in (("waiting", dict(waiting=True)), ("parked", dict(parked=True))):
    meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}
    server._decision_hand_over(meta_, OWN, BACK, now=now0, **kw)
    check(f"4 _decision_hand_over ({label}): no stored mover=he is left, and the item reads as waiting with an agent picker", "mover" not in meta_ and model.derive(its(**meta_), now0).state == "waiting", meta_)
meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": OWN, "until": FUT}
server._decision_hand_over(meta_, OWN, OWN, waiting=True, now=now0)
check("4 _decision_hand_over: …he as then too: both go", "mover" not in meta_ and "then" not in meta_, meta_)
meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "until": FUT}
server._decision_hand_over(meta_, OWN, BACK, waiting=True, now=now0)
check("4 _decision_hand_over: a date-only wait with an agent in then stores the picker as `mover` (never the old key), then goes", meta_.get("mover") == BACK and "post_wake_mover" not in meta_ and "then" not in meta_, meta_)

# the watchers' turn to him: a wait that ends on a question to him leaves no stored mover (he is the mover by needs=decision), the agent that picks it up after is `then`
meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1)}
wk.turn_to_owner(meta_, HELP, "Did it arrive?", [{"label": "Arrived"}], "it is due", now0)
check("4 turn_to_owner: the stored mover goes, the picker is the then beside him, needs is decision alone", "mover" not in meta_ and meta_.get("then") == HELP and meta_.get("needs") == ["decision"], meta_)

# the board answer: a watcher ask answered "not yet" puts the wait back with its picker (no stray mover=he), "arrived" gives the item to the picker
item(41, needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], subject="[zed] relay answered",
     watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "mover": HELP}, "at": now0}, then=HELP, mover=OWN)
m_ = dict(mt(41))
r = server._watch_answer(rd(41), m_, {"do": "wait", "text": "", "date": day(9)}, now0)
check("4 _watch_answer (not yet): the wait is back with its own picker as mover, then goes, no stray mover=he", m_.get("mover") == HELP and "then" not in m_ and m_.get("ask_by") == day(9) and "waits again" in r, (r, m_))
item(42, needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], subject="[zed] relay arrived", then=HELP, mover=OWN,
     watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "post_wake_mover": HELP}, "at": now0})
m_ = dict(mt(42))
r = server._watch_answer(rd(42), m_, {"do": "arrived", "text": "", "date": ""}, now0)
check("4 _watch_answer (arrived): the agent has it, alive, no stray mover=he", m_.get("mover") == HELP and m_.get("needs") == [HELP], (r, m_))
# a decision item parked by his answer through the board's own entry
item(43, needs=["decision"], mover=OWN, then=BACK, ask="Decide: whether to go ahead \u00b7 Recommend: go \u00b7 Stakes: a day either way \u00b7 By: no date",
     options=[{"label": "Approve", "line": "Go ahead as proposed", "recommended": True}, {"label": "Decline", "line": "Do not go ahead", "recommended": False}],
     hold=True, wake=day(30), hold_set={"by": "t", "at": now0}, subject="[zed] a decision on a parked item")
r = server._answer("a43", "Approve", "", "")
check("4 the board's answer on a parked decision: the stored mover=he does not survive his answer, the agent in then is the picker through the wait, stored as `mover`", r == "decision" and mt(43).get("mover") == BACK and "post_wake_mover" not in mt(43) and "decision" not in (mt(43).get("needs") or [])
      and model.derive(rd(43), now0).state == "waiting" and model.derive(rd(43), now0).wait.mover == BACK, (r, mt(43)))

# the wait-end fix: a step in words that waits for another item gets its wait stored with the mover as the picker, never a mover=he
for p in (T / "store/g").glob("*.json"): p.unlink()
ROLES = {BACK: {"role": "background"}, HELP: {"role": "background"}, FRONT: {"role": "front"}}
def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: FRONT, builder=lambda p: BACK, page_of=lambda p: ("", None), deliver=lambda to, text, fyi=False: (True, "[200] ok"), sessions=lambda: None,
                             pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
def gitem(i, nxt, **meta):
    (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[zed] item {i}", "description": DESC, "status": "open", "updated": OLD, "written_at": OLD, "written_by": BACK,
                                                    "state_updated": OLD, "confirmed": OLD,
                                                    "metadata": {"owner": U[FRONT], "project": "projects/zedwork", "state": "doing", "needs": [BACK], "next": nxt, **meta}}))
gitem(9202, "zed-helper: build the thing")
gitem(9201, "zed-back: wait for board#" "9202 to close, then write the summary")
(T / "state/audit").mkdir(parents=True, exist_ok=True)
items_ = {f"g{p.stem}": json.loads(p.read_text()) for p in (T / "store/g").glob("*.json")}
r = AR.filing_pass(now=now0, items=items_, anchors={}, env=env(wait_end=server._wait_end_fix, wait_facts=server._wait_end_facts))
m_ = mt(9201, "g")
check("4 _wait_end_fix: the wait is stored with the mover as the picker, stored as `mover` and never as the old key or as mover=he; the model reads it as waiting on the agent",
      m_.get("after") == ["g9202"] and m_.get("mover") == BACK and "post_wake_mover" not in m_ and model.derive(rd(9201, "g"), now0).state == "waiting" and model.derive(rd(9201, "g"), now0).wait.mover == BACK, (m_, r.get("wait_end")))

# ================================================================ 5. the phase reads
PH = [
    ("until set, mover he",                 dict(until=FUT, mover=OWN, needs=[BACK]),                      home.WAITING),
    ("until set, an agent's picker",        dict(until=FUT, mover=HELP, needs=[BACK]),                     home.WAITING),
    ("legacy key, until set",               dict(until=FUT, post_wake_mover=HELP, needs=[BACK]),           home.WAITING),
    ("a wait with a kind and mover he",     dict(hold=True, wake=FUT, wait_kind="time", mover=OWN, needs=[BACK]), home.WAITING),
    ("alive, mover he",                     dict(mover=OWN, needs=[BACK]),                                 home.YOUR_MOVE),
    ("alive, needs decision",               dict(needs=["decision"], ask="Decide: x"),                     home.YOUR_MOVE),
    ("alive, an agent",                     dict(mover=HELP, needs=[HELP]),                                home.AGENTS),
    ("alive, nothing stored",               dict(needs=[BACK]),                                            home.AGENTS),
]
for label, st, want in PH:
    got = home.list_of(D(**st))
    check(f"5 phase: {label}: {want}", got == want, got)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": picker one reader scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
