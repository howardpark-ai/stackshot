"""Scenario test for the picker: on a waiting item `mover` is who picks it up when the wait ends (the read side of "one mover") — fixture data, no live store, no network, no server socket.

An item has one mover field. While it is alive it says who moves the item now; while it waits it says who picks the item up when the wait ends. The old name of the second reading,
post_wake_mover, is still read, and while it is stored (not yet moved into mover) it wins over a stored mover. `then` stands only while the owner is the effective mover (an alive item he moves, a waiting one he picks up). Covered:

  * model.derive: the picker is the stored post_wake_mover, else the stored mover (the word none is no mover), else the default (the builder or -main agent; the owner for a relay); both stored and different → the
    post_wake_mover wins and one conflict line says so; the item's own `mover` stays empty while it waits; no conflict is named for a mover on a waiting item or a `then` beside an agent.
  * `then`: read beside the owner (alive, or the waiting item he picks up), not beside an agent, not stored-and-ignored into a conflict.
  * model.words: `· mover X`, `· mover <owner> (then Y)`; the derived tail still names post_wake_mover.
  * model.settle (waiting=True, the update path's call): a wait that replaces his state makes the agent in `then` the picker; a stored agent mover on a waiting item is never dropped; with a post_wake_mover stored only his mover goes.
  * the server readers: `held_by`, get's mover and then lines, the model-conflict lines.
  * the watchers: a wake the owner picks up keeps the stored `then`; "not yet" keeps the picker (mover) the wait had; a record of the wait written under the old name is still read.
  * the renderer's who line.

    tests/run-suite mover_picker        → exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="moverpicker-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[zed] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
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
def item(i, status="open", subject=None, **meta):
    su = now0 - 10 * DAY
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[zed] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": U["zed-front"], "project": "projects/zedwork", "next": "zed-back: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk; from stackshot.web import render
from stackshot.service import answer as answer_svc
from stackshot.service import client_reads as client_reads_svc
from stackshot.service import item_read as _item_read
from stackshot.core import config as _cfg
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import watching as watching_svc
from stackshot.web.tools import get as _wt_get
from stackshot.service import telling
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
SENT = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
(T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
ZONE_HOURS = 4
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
OWN = model.owner_display()
FB = telling.fallback_mover("projects/zedwork")
assert FB, FB
D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
W_ = lambda mod: model.words(mod)
FUT = day(5)

# ================================================================ derive: the picker
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)
check("picker: a stored mover on a waiting item is who picks it up; it is explicit, no conflict is named, and the item's own mover stays empty while it waits",
      m_.state == "waiting" and m_.wait.mover == HELP and m_.wait.mover_explicit and m_.picker == HELP and m_.mover == "" and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=HELP)
check("picker: …the old name post_wake_mover is read when no mover is stored, and is explicit too", m_.wait.mover == HELP and m_.wait.mover_explicit and m_.wait.post_wake_mover == HELP and m_.picker == HELP and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=HELP)
check("picker: …both stored and equal: no conflict", m_.wait.mover == HELP and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=BACK)
check("picker: …both stored and different: the old name wins while it is stored, and one conflict line says so", m_.wait.mover == BACK and m_.picker == BACK and len(m_.conflicts) == 1 and "mover=zed-helper" in m_.conflicts[0] and "post_wake_mover=zed-back" in m_.conflicts[0] and "post_wake_mover picks it up" in m_.conflicts[0], m_.conflicts)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=BACK, post_wake_mover=OWN, then=HELP)
check("picker: …a stored post_wake_mover that is he beats a stored agent mover, and his then stands (the case main reads the same way)", m_.wait.mover == OWN and m_.then == HELP and len(m_.conflicts) == 1, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, post_wake_mover=HELP, then=BACK)
check("picker: …a stored agent post_wake_mover beats a stored mover that is he, and no then stands", m_.wait.mover == HELP and m_.then == "" and m_.picker == HELP, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover="none")
check("picker: the literal word none stored as a mover is no picker: the default takes it, not explicit, no conflict", m_.wait.mover == BACK and not m_.wait.mover_explicit and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover="None", post_wake_mover=HELP)
check("picker: …nor does it conflict with a stored post_wake_mover, which is the picker", m_.wait.mover == HELP and not m_.conflicts, m_)
check("waiting.mover_of agrees with the picker: an agent post_wake_mover beats a stored mover, and an owner one is skipped for the mover", waiting.mover_of({"needs": [], "mover": BACK, "post_wake_mover": HELP})["who"] == HELP and waiting.mover_of({"needs": [], "mover": HELP, "post_wake_mover": OWN})["who"] == HELP, waiting.mover_of({"needs": [], "mover": BACK, "post_wake_mover": HELP}))
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time")
check("picker: …neither stored: the default (the first session in needs), not explicit", m_.wait.mover == BACK and not m_.wait.mover_explicit and not m_.conflicts, m_)
m_ = D(hold=True, wake=FUT, wait_kind="time")
check("picker: …neither stored and no session in needs: the project's builder or -main agent", m_.wait.mover == FB and not m_.wait.mover_explicit, m_)
m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT)
check("picker: a relay with nothing stored: the owner (the ask-by day turns the item to him)", m_.wait.mover == OWN and not m_.wait.mover_explicit, m_)
m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT, mover=HELP)
check("picker: …a relay with a stored mover: that agent picks it up after his answer", m_.wait.mover == HELP and m_.wait.mover_explicit, m_)
m_ = D(needs=[BACK], mover=HELP)
check("picker: an alive item: the picker is the mover (an agent), or `then` while the owner moves it", m_.picker == HELP and D(needs=["decision"], ask="Decide: x", then=BACK).picker == BACK, m_)
check("picker: next_mover reads the same", D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP).next_mover == HELP, None)

# ================================================================ `then` stands only beside the owner
m_ = D(needs=["decision"], ask="Decide: x", then=BACK)
check("then: an alive item the owner moves reads its stored then", m_.mover == OWN and m_.then == BACK and m_.then_explicit and not m_.conflicts, m_)
m_ = D(needs=[BACK], mover=HELP, then=BACK)
check("then: …an alive item an agent moves reads none (a stored one is not read), and no conflict is named", m_.mover == HELP and m_.then == "" and not m_.then_explicit and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)
check("then: a waiting item he picks up reads its stored then", m_.wait.mover == OWN and m_.then == BACK and m_.then_explicit and m_.picker == OWN, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, then=BACK)
check("then: …a waiting item an agent picks up reads none", m_.wait.mover == HELP and m_.then == "" and not m_.conflicts, m_)
m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT, then=HELP)
check("then: …a relay (he is the default picker) reads its then", m_.wait.mover == OWN and m_.then == HELP, m_)

# ================================================================ words
check("words: a waiting item says who picks it up as its mover", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)) == f"model: waiting on a time (wake {FUT}) · mover zed-helper", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)))
check("words: …he picks it up, with the then beside him", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)) == f"model: waiting on a time (wake {FUT}) · mover {OWN} (then zed-back)", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)))
check("words: …a mover the item does not store is named in the derived tail", W_(D(needs=[BACK], hold=True, wake=FUT)).endswith("· derived: wait_kind, post_wake_mover") and "derived" not in W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=BACK)), W_(D(needs=[BACK], hold=True, wake=FUT)))
check("words: an alive item an agent moves shows no then", W_(D(needs=[BACK], mover=HELP, then=BACK)) == "model: alive · mover zed-helper", W_(D(needs=[BACK], mover=HELP, then=BACK)))

# ================================================================ settle
def S(meta, was_his=True, waiting=True): return model.settle({"status": "open", "metadata": {"project": "projects/zedwork", **meta}}, was_his, waiting=waiting)      # a waiting item settles only from the update path (waiting=True)
check("settle: a wait replaces his state (mover him, an agent in then): the agent picks it up, then goes", S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": BACK, "then": ""}, S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}))
check("settle: …with no agent in then only the stale mover goes", S({"mover": OWN, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": ""}, None)
check("settle: …a post_wake_mover stored beside his mover and an agent in then: only the mover goes, then and the old name stay as stored",
      S({"mover": OWN, "then": BACK, "post_wake_mover": HELP, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": ""}, S({"mover": OWN, "then": BACK, "post_wake_mover": HELP, "hold": True, "wake": FUT, "wait_kind": "time"}))
check("settle: …a stored agent mover on a waiting item is never dropped", S({"mover": HELP, "needs": [BACK], "hold": True, "wake": FUT, "wait_kind": "time"}) is None and S({"mover": HELP, "needs": [BACK], "hold": True, "wake": FUT, "wait_kind": "time"}, False) is None, None)
check("settle: …nor a mover he stored on a waiting item that never stood in his state", S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}, False) is None, None)

# ================================================================ the server's readers
item(1, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=HELP, subject="[zed] a picker by mover")
item(2, needs=[BACK], hold=True, wake=day(5), wait_kind="time", post_wake_mover=HELP, subject="[zed] a picker by the old name")
item(3, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up")
item(4, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=HELP, post_wake_mover=BACK, subject="[zed] two pickers")
item(5, needs=[BACK], mover=HELP, then=BACK, subject="[zed] an agent moves it, with a then")
L = lambda n: _wt_get.stackshot_get(f"a{n}").split("\n")
check("held_by: the picker holds a waiting item, as its mover when it is stored under that name", telling.held_by(_service_store._load("a1")) == (HELP, "mover"), telling.held_by(_service_store._load("a1")))
check("held_by: …under the old name it reads as before, the word then", telling.held_by(_service_store._load("a2")) == (HELP, "then"), telling.held_by(_service_store._load("a2")))
check("held_by: …when he picks it up, the then beside him holds it", telling.held_by(_service_store._load("a3")) == (HELP, "then"), telling.held_by(_service_store._load("a3")))
check("held_by: …both stored and different, the old name is read first, as the hand-over writers read it", telling.held_by(_service_store._load("a4")) == (BACK, "then"), telling.held_by(_service_store._load("a4")))
check("held_by: an alive item an agent moves is held by its mover", telling.held_by(_service_store._load("a5")) == (HELP, "mover"), telling.held_by(_service_store._load("a5")))
g1, g3, g4, g5 = L(1), L(3), L(4), L(5)
check("get: a waiting item shows who picks it up as its mover, and no then line", "mover: zed-helper (picks it up when the wait ends)" in g1 and not any(x.startswith("then:") for x in g1), g1[:6])
check("get: …with the owner as picker, the then is shown", f"mover: {OWN} (picks it up when the wait ends)" in g3 and "then: zed-helper" in g3, g3[:6])
check("get: …the model line says so, and no model-conflict line is printed for a mover on a waiting item", any(x.startswith("model: waiting") and x.endswith("· mover zed-helper") for x in g1) and not any("model conflict" in x for x in g1), g1)
check("get: …two different pickers stored: one conflict line", sum("model conflict" in x for x in g4) == 1, g4)
check("get: an alive item an agent moves shows no then line and no conflict", "mover: zed-helper" in g5 and not any(x.startswith("then:") for x in g5) and not any("model conflict" in x for x in g5), g5)
check("roles: a waiting item's picker has the role then; with him as picker, the then beside him", client_reads_svc._then_label_raw({**rd(1), "gid": "a1"}) == HELP and client_reads_svc._then_label_raw({**rd(3), "gid": "a3"}) == HELP and client_reads_svc._then_label_raw({**rd(5), "gid": "a5"}) == "", None)
check("then label: the notice's then names the picker of a waiting item", telling.then_label({**rd(1), "gid": "a1"}) != "" and telling.then_label({**rd(5), "gid": "a5"}) == "", None)

# ================================================================ the renderer's who line
strip = lambda s: re.sub(r"<[^>]+>", "", s)
bd = ui_render.Board(str(T / "store"), now=datetime.datetime.now(datetime.timezone.utc))
r_ = {"gid": "a1", "metadata": {}}
mk = lambda **kw: model.Model(model.WAITING, then=kw.pop("then", ""), wait=model.Wait(kind="time", kind_explicit=True, until=FUT, **kw))
check("who line: an agent picks it up", strip(bd.wait_who(r_, mk(mover=HELP))) == "zed-helper picks it up · watched by the scheduler", strip(bd.wait_who(r_, mk(mover=HELP))))
check("who line: the owner picks it up, with the then", strip(bd.wait_who(r_, mk(mover=OWN, then=BACK))) == f"{OWN}, then zed-back · watched by the scheduler", strip(bd.wait_who(r_, mk(mover=OWN, then=BACK))))
check("who line: …the owner alone", strip(bd.wait_who(r_, mk(mover=OWN))).startswith(f"{OWN} picks it up"), strip(bd.wait_who(r_, mk(mover=OWN))))
check("who line: nobody", strip(bd.wait_who(r_, mk(mover=""))).startswith("nobody set to pick it up"), strip(bd.wait_who(r_, mk(mover=""))))

# ================================================================ the watchers
# a wake the owner picks up keeps the then stored beside him
item(10, needs=[BACK], hold=True, wake=day(-1), wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up after the wake")
item(11, needs=[BACK], hold=True, wake=day(-1), wait_kind="time", mover=HELP, subject="[zed] an agent picks it up after the wake")
SENT.clear(); moved = watching_svc.watch_pass()
m = mt(10)
check("watch fire: a time wait the owner picks up turns to him and keeps the then stored beside it", "a10" in moved and m.get("needs") == ["decision"] and m.get("then") == HELP and "mover" not in m and "wait_kind" not in m, m)
m = mt(11)
check("watch fire: …one an agent picks up turns alive with him as mover", "a11" in moved and m.get("mover") == HELP and m.get("needs") == [HELP] and "then" not in m, m)

# a relay: the agent stored as its mover picks it up after his answer; "not yet" keeps the wait's picker
item(20, wait_kind="relay", wait_event="the parcel", ask_by=day(-1), mover=HELP, needs=[], subject="[zed] relay with a mover")
item(21, wait_kind="relay", wait_event="the quote", ask_by=day(-1), post_wake_mover=HELP, needs=[], subject="[zed] relay with the old name")
SENT.clear(); moved = watching_svc.watch_pass()
m = mt(20)
check("relay fire: the question goes to him with the picker as then; the record of the wait keeps the mover", "a20" in moved and m.get("needs") == ["decision"] and m.get("then") == HELP and m["watch"]["was"].get("mover") == HELP, m)
m = mt(21)
check("relay fire: …a wait stored under the old name records its picker as mover", "a21" in moved and m["watch"]["was"].get("mover") == HELP and "post_wake_mover" not in m["watch"]["was"] and m.get("then") == HELP, m)
answer_svc._answer("a20", "not yet, ask again on <date>", f"ask again on {day(9)}", "answer")
m = mt(20)
check("relay not yet: the wait is back on the date he gave with its picker kept as the mover", m.get("wait_kind") == "relay" and m.get("ask_by") == day(9) and m.get("mover") == HELP and "then" not in m and "ask" not in m, m)
check("relay not yet: …and the model reads the picker", _item_read._model_of({**rd(20), "gid": "a20"}).wait.mover == HELP and _item_read._model_of({**rd(20), "gid": "a20"}).mover == "", None)
SENT.clear(); answer_svc._answer("a21", "arrived", "", "answer")
m = mt(21)
check("relay arrived: a record of the wait under the old name is still read: the item goes to that agent", m.get("mover") == HELP and m.get("needs") == [HELP] and "ask" not in m, m)
item(22, wait_kind="relay", wait_event="the contract", ask_by=day(-1), mover=BACK, needs=[], subject="[zed] relay, arrived")
watching_svc.watch_pass(); SENT.clear(); answer_svc._answer("a22", "arrived", "", "answer")
m = mt(22)
check("relay arrived: …and one stored under mover goes to the mover", m.get("mover") == BACK and m.get("needs") == [BACK], m)
check("fields: a record of the wait remembers the mover and the then", "mover" in wk.WAS_FIELDS and "then" in wk.WAS_FIELDS and "post_wake_mover" in wk.WAS_FIELDS, wk.WAS_FIELDS)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": mover picker scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
