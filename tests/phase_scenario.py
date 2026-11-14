"""Scenario test for the stored phase (metadata.phase: alive | waiting) — fixture data, no live store, no network, no server socket.

An open item stores what the board shows it as, beside the fields that board reading is made from. Every save writes it (server._phase_stamp, called from the one save path, writes.save);
model.view takes the alive-or-waiting decision and the kind of the wait from it and from nothing else (an item that stores no usable pair is shown as the writer would store it, and counted). The
older fields are stored exactly as before. A waiting item also stores `waits_on`, the kind of its wait as the board shows it (time | anchor | item | relay | event),
beside the phase and under the same rules (tests/stamp_scenario.py is the suite of the pass that stamps it on items nobody has saved since).

  1  the phase is stored on every save of an open item, for each of the seven stored states, for an item that stores none, and for each stored wait kind (time, anchor, item, relay, event),
     and for the three ways a doing item reads as waiting (a held doing item, a wake that carries a wait_basis, a wake with every open step dated for a later day)
  2  a closed item stores neither phase nor wait; a close drops the phase an open item stored
  3  a create and an update store it: alive to waiting and back as the fields change (an old state word an item stores is fixture data: no call sets one any more)
  4  the older fields are stored exactly as before (the same save with the stamp off writes the same item, bar the phase), and the wait_kind is never added to an item that stores none
     (a stored wait_kind hands the item to the watchers, and makes derive read a doing item as a conflict)
  5  model.view with the phase stored reads exactly as the fields do, for every case above, and the tool-facing lines (the list word, the model line) are the same
  6  the stored pair decides: a stored phase or kind the fields no longer give (an item written before a later change to them, a wake that has since passed) is what is shown until the sweep restamps it;
     half a pair, or a value that is no phase, is read as the writer would store it and counted (model.UNSTAMPED)
  8  History: the first confirm of an item written before the phase still shows its `confirm` line on both renderers (the phase is left out of the comparison, like `activity`), a phase flip alone adds none, and a stamp that raises never fails the save
  7  the replay: a read-only copy of the live store (the folder named by PHASE_REPLAY_STORE; skipped when it is not set) is read through the old derivation and
     through the new read path, and the displayed state, kind, reason, list word and model line are identical for every item

    tests/run-suite phase        → exit 0 / 1"""
import contextlib, copy, io, json, logging, os, pathlib, re, shutil, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="phasetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
BACK = "team-back"
OWN = "Oliver"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.model import model as _model; from stackshot.waits import dated_wait as _dw; from stackshot.model import ids as _model_ids
from stackshot.web.tools import notes as _notes_tool
from stackshot.web.tools import get as _get_tool
from stackshot.service import item_read as _item_read
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
from stackshot.core import store as _core_store
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # n hours after the suite started, in the instance timezone
wk = lambda h: hrs(h).replace(" ", "T")
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
now_ = time.time()


def put(i, status="open", letter="g", **meta):
    """An item file as an older writer left it: no phase."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def AO(i):                      # the items an item waits after that are still open, read from the store as the server reads them
    return [x for x in W.after_of(i["metadata"]) if (T / f"store/{x[0]}/{x[1:]}.json").exists() and raw(int(x[1:]), x[0])["status"] == "open"]
def old_of(it, now=None):
    """The old derivation: the fields alone decide (no phase read), as model.view of model.derive gave before the phase was stored."""
    now = now_ if now is None else now
    return _model.view(it, _model.derive(it, now, after_open=AO, anchored=lambda i: False), now, AO, check=False)
def new_of(it, now=None):
    """The new read path: model.view as every reader calls it, with the stored phase beside the fields."""
    now = now_ if now is None else now
    return _model.view(it, _model.derive(it, now, after_open=AO, anchored=lambda i: False), now, AO)
def bare(it):
    """The item as a writer from before the phase left it."""
    out = copy.deepcopy(it); out.get("metadata", {}).pop("phase", None); return out
def save(i, letter="g"):
    gid = f"{letter}{i}"
    writes.save(gid, _service_store._load(gid))
    return raw(i, letter)
def shown(i, letter="g"): return dict(raw(i, letter), gid=f"{letter}{i}")

# an open item for the blocked and the item-wait cases to wait after, and a closed one
put(31, needs=[BACK], state="doing")
put(32, status="completed", needs=[BACK], state="doing", outcome="done")

NEXT_FAR = "worker-b: check the build later and report back to the owner"     # no date a step could be read for
BASIS = {"text": "the contract renews on 2099-01-20", "wake": wk(24 * 30), "by": BACK, "at": now0}
STEP_DAY = day(8)
# (id, what it is, the metadata, the phase it stores, the wait kind the board shows ("" = alive), the wait_kind it stores after the save ("" = none))
CASES = [
    (1, "doing, stored",                                     dict(needs=[BACK], state="doing"),                                                                   "alive", "", ""),
    (2, "doing, no stored state (read from the fields)",     dict(needs=[BACK]),                                                                                  "alive", "", ""),
    (3, "your-call",                                         dict(needs=["decision", BACK], state="your-call", ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date"), "alive", "", ""),
    (4, "your-step",                                         dict(needs=[BACK], state="your-step", step="Run the thing once", mover=OWN, next=f"{OWN}: run the thing once"), "alive", "", ""),
    (5, "outside (external, a party and a chase day)",       dict(needs=["external"], state="outside", party="Acme legal", chase=day(5)),                       "waiting", "relay", ""),
    (6, "outside, with an anchor stored",                    dict(needs=["external"], state="outside", party="Acme legal", chase=day(5), wait_anchor="https://example.com/x/1"), "waiting", "anchor", ""),
    (7, "blocked (an open after link)",                      dict(needs=[BACK], state="blocked", after=["g31"], supplies="its output"),                           "waiting", "item", ""),
    (8, "parked (a hold, a wake, the owner's words)",        dict(needs=[BACK], state="parked", hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}), "waiting", "time", ""),
    (9, "verifying (an end date)",                           dict(needs=[BACK], state="verifying", proof="the run lands", end=day(5)),                            "waiting", "time", ""),
    (10, "a stored wait_kind=time",                          dict(needs=[BACK], wait_kind="time", wake=day(9)),                                                   "waiting", "time", "time"),
    (11, "a stored wait_kind=anchor",                        dict(needs=[BACK], wait_kind="anchor", wait_anchor="https://example.com/x/2", wait_event="a reply", ask_by=day(9)), "waiting", "anchor", "anchor"),
    (12, "a stored wait_kind=item",                          dict(needs=[BACK], wait_kind="item", after=["g31"]),                                                 "waiting", "item", "item"),
    (13, "a stored wait_kind=relay",                         dict(needs=[BACK], wait_kind="relay", wait_event="Acme's reply", ask_by=day(9)),                    "waiting", "relay", "relay"),
    (14, "a stored wait_kind=event",                         dict(needs=[BACK], wait_kind="event", wait_event="recycle", ask_by=day(9)),                          "waiting", "event", "event"),
    (15, "a held doing item with a far wake",                dict(needs=[BACK], state="doing", hold=True, wake=wk(24 * 5)),                                      "waiting", "time", ""),
    (16, "a doing item whose wake carries a wait_basis",     dict(needs=[BACK], state="doing", wake=wk(24 * 30), wait_basis=BASIS, next=NEXT_FAR),               "waiting", "time", ""),
    (17, "a doing item with every open step dated later",    dict(needs=[BACK], state="doing", wake=wk(24 * 7), next=f"team-back: after {STEP_DAY} run the check"), "waiting", "time", ""),
    (18, "a doing item with a near wake (a reminder)",       dict(needs=[BACK], state="doing", wake=wk(0.5)),                                                     "alive", "", ""),
    (19, "a doing item with a far wake and no basis",        dict(needs=[BACK], state="doing", wake=wk(24 * 5), next=NEXT_FAR),                                  "alive", "", ""),
    (20, "a doing item on hold with no wake",                dict(needs=[BACK], state="doing", hold=True),                                                       "alive", "", ""),
    (21, "no stored state, on hold with a wake (parked)",    dict(needs=[BACK], hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}), "waiting", "time", ""),
    (22, "no stored state, an open after link (blocked)",    dict(needs=[BACK], after=["g31"]),                                                                   "waiting", "item", ""),
    (23, "no stored state, a closed after link",             dict(needs=[BACK], after=["g32"]),                                                                   "alive", "", ""),
]
for i, _name, meta, *_ in CASES:
    put(i, **meta)
before = {i: copy.deepcopy(raw(i)) for i, *_ in CASES}

# ---- 1. every save of an open item stores the phase (and nothing the older fields did not already say)
for i, name, meta, phase, kind, stored_kind in CASES:
    it = raw(i)
    check(f"1 fixture {i} ({name}) stores no phase before the save, as an older writer left it", "phase" not in it["metadata"], it["metadata"])
    old = old_of(shown(i))
    saved = save(i)
    m = saved["metadata"]
    check(f"1 {i} {name}: the save stores phase {phase}", m.get("phase") == phase, m)
    check(f"1 {i} {name}: …and the old derivation reads the same ({phase}, wait {kind or 'none'})", _model.shown_pair(old) == (phase, kind), (_model.shown_pair(old), old))
    check(f"1 {i} {name}: …a wait_kind is stored only when the item already stored one ({stored_kind or 'none'})", (m.get("wait_kind") or "") == stored_kind, m)
    check(f"1 {i} {name}: …and waits_on is the kind the board shows ({kind or 'none: alive'})", m.get("waits_on") == (kind or None) and ("waits_on" not in m or phase == "waiting"), m)

# ---- 2. a closed item stores neither phase nor wait; a close drops the phase
c = save(32)
check("2 a closed item's save stores no phase, no waits_on and no wait_kind", "phase" not in c["metadata"] and "waits_on" not in c["metadata"] and "wait_kind" not in c["metadata"], c["metadata"])
put(33, status="completed", needs=[BACK], state="doing", phase="waiting", waits_on="time", wait_kind="time", outcome="done")
c = save(33)
check("2 …a closed item that carried a phase and a waits_on loses both at the next save (the wait_kind the close drops is not this stamp's to touch)", "phase" not in c["metadata"] and "waits_on" not in c["metadata"], c["metadata"])
check("2 …model.view reads a closed item as dead with the phase stored or not", old_of(shown(32)).state == _model.DEAD and new_of(shown(32)).state == _model.DEAD and _model.stored_phase(shown(33)) == "", None)

# ---- 3. a create and an update store it, as the fields change
def created(out):
    m = re.search(r"created ([a-z]\d+)", out); assert m, out
    return _model_ids._norm_id(m.group(1))
def uptd(gid, **kw): return _update_svc._update(gid, sender="home-front", **kw)
out = _wt_create._create(subject="[home] phase create alive", description=DESC, project="projects/alpha", owner="home-front", next="team-back: write it", needs=[BACK])
gid = created(out)
check("3 a create of a doing item stores phase alive and no wait_kind", _service_store._load(gid)["metadata"].get("phase") == "alive" and "wait_kind" not in _service_store._load(gid)["metadata"], _service_store._load(gid)["metadata"])
uptd(gid, hold=True, wake=day(30), wait_basis=f"the vendor ships on {day(33)}")
m = _service_store._load(gid)["metadata"]
check("3 …an update that parks it (a hold, a wake, a wait_basis) stores phase waiting and waits_on time, and still no wait_kind", m.get("phase") == "waiting" and m.get("waits_on") == "time" and "wait_kind" not in m, m)
uptd(gid, clear_hold=True)
m = _service_store._load(gid)["metadata"]
check("3 …releasing the hold stores phase alive again, and drops the waits_on", m.get("phase") == "alive" and "waits_on" not in m and not m.get("hold"), m)
put(46, needs=[BACK], state="doing")          # an item that stores the old word doing (fixture data: no call sets a state any more)
uptd("g46", hold=True, wake=wk(24 * 5), wait_basis=f"the vendor ships on {day(7)}")
m = mt(46)
check("3 …a stored doing item put on hold with a far wake stores waiting, and the hold ends the stored doing word (the item reads from its fields)", m.get("phase") == "waiting" and m.get("waits_on") == "time" and "state" not in m, m)
out = _wt_create._create(subject="[home] phase create blocked", description=DESC, project="projects/alpha", owner="home-front", next="team-back: write it", needs=[BACK], after=["g31"], ask_by=day(9))
gid_b = created(out)
check("3 a create with an open after link stores phase waiting and waits_on item", _service_store._load(gid_b)["metadata"].get("phase") == "waiting" and _service_store._load(gid_b)["metadata"].get("waits_on") == "item", _service_store._load(gid_b)["metadata"])
out = _wt_create._create(subject="[home] phase create decision", description=DESC, project="projects/alpha", owner="home-front", next=f"{OWN}: decide", needs=["decision"],
                     ask="Decide: ship it · Recommend: yes · Stakes: a week · By: no date")
gid_d = created(out)
check("3 a create that asks the owner stores phase alive", _service_store._load(gid_d)["metadata"].get("phase") == "alive", _service_store._load(gid_d)["metadata"])
out = _wt_create._create(subject="[home] phase create relay", description=DESC, project="projects/alpha", owner="home-front", next="team-back: wait for the reply", needs=[BACK],
                     wait_kind="relay", wait_event="Acme's reply", ask_by=day(6), post_wake_mover=BACK)
gid_r = created(out)
m = _service_store._load(gid_r)["metadata"]
check("3 a create with a wait_kind stores phase waiting and a waits_on equal to the wait_kind it was given", m.get("phase") == "waiting" and m.get("wait_kind") == "relay" and m.get("waits_on") == "relay", m)
uptd(gid, status="completed", outcome="done", reason="finished", description="- The thing is done and closed")
c = _service_store._load(gid)
check("3 an update that closes it leaves no phase, no waits_on and no wait_kind", c["status"] == "completed" and "phase" not in c["metadata"] and "waits_on" not in c["metadata"] and "wait_kind" not in c["metadata"], c["metadata"])
uptd(gid_d, priority="p2")
check("3 a filing edit on an open item keeps the phase (a save restamps it)", _service_store._load(gid_d)["metadata"].get("phase") == "alive", _service_store._load(gid_d)["metadata"])

# ---- 4. the older fields are stored exactly as before: the same save with the stamp off writes the same item, bar the phase
real_stamp = server._phase_stamp
for i, name, *_ in CASES:
    put(i, **before[i]["metadata"])
    server._phase_stamp = lambda gid_, it_: None
    try:
        off = save(i)
    finally:
        server._phase_stamp = real_stamp
    put(i, **before[i]["metadata"])
    on = save(i)
    strip = lambda d: {k: v for k, v in d.items() if k not in ("updated", "written_at")} | {"metadata": {k: v for k, v in d["metadata"].items() if k not in ("phase", "waits_on", "written_at")}}
    check(f"4 {i} {name}: the same save with the stamp off writes the same item, bar the phase and the waits_on", strip(on) == strip(off) and "phase" not in off["metadata"] and "waits_on" not in off["metadata"], (strip(on), strip(off)))
    check(f"4 {i} {name}: …every field the fixture stored is stored still", all(on["metadata"].get(k) == v for k, v in before[i]["metadata"].items() if k != "next"), on["metadata"])      # `next` apart: the owner-step pass of the save adds his step's line to it, as it always did

# ---- 5. the new read path reads exactly as the old derivation, with the phase stored
for i, name, meta, phase, kind, stored_kind in CASES:
    it = shown(i)
    check(f"5 {i} {name}: model.view with the phase stored equals the old derivation, field for field (state, wait kind, until, basis, post-wake mover, today's state)", new_of(it) == old_of(bare(it)), (new_of(it), old_of(bare(it))))
    check(f"5 {i} {name}: …the wire list word and the model line are the same with the phase stored or not", server._item_list(it) == server._item_list(bare(it))
          and _notes_tool._model_lines(it, short=True) == _notes_tool._model_lines(bare(it), short=True) and _model.words(new_of(it)) == _model.words(old_of(bare(it))), None)
    check(f"5 {i} {name}: …and so are get's text and the brief's item block", _get_tool._fmt(it) == _get_tool._fmt(bare(it)) and _get_tool._fmt(it, brief=True) == _get_tool._fmt(bare(it), brief=True), None)
    check(f"5 {i} {name}: …the pair read back is the stored one", _model.shown_pair(new_of(it)) == (phase, kind), _model.shown_pair(new_of(it)))
u0_ = _model.UNSTAMPED["count"]
for i, name, *_r in CASES: new_of(shown(i))
check("5 no unstamped read was counted reading what the saves wrote", _model.UNSTAMPED["count"] == u0_, _model.UNSTAMPED)
check("5 derive is unchanged by the stored phase (the guards read it as stored): a held doing item is still alive to derive", _model.derive(shown(15), now_, AO).state == _model.ALIVE and _model.derive(shown(16), now_, AO).state == _model.ALIVE
      and _model.derive(shown(17), now_, AO).state == _model.ALIVE, None)
check("5 …and the dated step wait still reads as one: dated_wait finds it", _dw.of(shown(17), now_) is not None and _dw.basis_wait(shown(16), now_) is not None and _dw.held_wait(shown(15), now_) is not None, None)

# ---- 6. the stored pair decides: where the fields say otherwise, what the item stores is what the board shows, until the sweep restamps it
buf = io.StringIO()
wrong = shown(1); wrong["metadata"]["phase"] = "waiting"; wrong["metadata"]["waits_on"] = "time"          # an alive item that stores waiting
got = new_of(wrong)
check("6 a stored waiting on an item the fields read as alive: the stored pair decides (waiting on a time)", _model.shown_pair(got) == ("waiting", "time") and old_of(bare(wrong)).state == _model.ALIVE, got)
late = shown(16); late["metadata"]["phase"] = "alive"; late["metadata"].pop("waits_on", None)             # a waiting item stored alive
late_got = new_of(late)
check("6 …a stored alive on an item the fields read as waiting: alive, with the mover the defaults give", late_got.state == _model.ALIVE and late_got.mover and old_of(bare(late)).state == _model.WAITING, late_got)
since = shown(16)                                                  # the wake the phase stood on has since passed: the stored waiting is stale, the fields read alive
since_got = _model.view(since, _model.derive(since, now_ + 40 * DAY, after_open=AO, anchored=lambda i: False), now_ + 40 * DAY, AO)
check("6 …a stored waiting the clock has outdated (the wake has passed) still shows waiting, on its stored kind, until the sweep restamps it", since_got.state == _model.WAITING and since_got.wait.kind == "time"
      and _model.view(since, _model.derive(since, now_ + 40 * DAY, after_open=AO, anchored=lambda i: False), now_ + 40 * DAY, AO, check=False).state == _model.ALIVE, since_got)
u0 = _model.UNSTAMPED["count"]
odd = shown(1); odd["metadata"]["phase"] = "sleeping"
check("6 …a stored value that is no phase is read as none: the item is shown as the writer would store it, and counted as an unstamped read", _model.stored_phase(odd) == "" and new_of(odd) == old_of(bare(odd)) and _model.UNSTAMPED["count"] == u0 + 1, _model.UNSTAMPED)
half = shown(13); half["metadata"].pop("waits_on", None)           # a phase waiting with no kind
check("6 …a stored waiting with no waits_on is half a pair: read as the writer would store it, and counted", new_of(half) == old_of(bare(half)) and _model.UNSTAMPED["count"] == u0 + 2, _model.UNSTAMPED)
kind_wrong = shown(10); kind_wrong["metadata"]["waits_on"] = "item"
k_got = _model.view(kind_wrong, old_of(bare(shown(10))), now_, AO)       # a model read from the fields (kind time) beside a stored waits_on of item
check("6 …a stored waits_on of another kind than the fields read: the stored kind is the one shown, the wake it stands on kept", k_got.wait.kind == "item" and old_of(bare(shown(10))).wait.kind == "time", k_got)
done_it = shown(32); done_it["metadata"]["phase"] = "alive"
done_it["metadata"]["waits_on"] = "time"
check("6 …a closed item that carries a phase reads as no stored phase and no stored waits_on and is dead", _model.stored_phase(done_it) == "" and _model.stored_waits_on(done_it) == "" and new_of(done_it).state == _model.DEAD, None)
check("6 …an item that stores nothing is read as the fields do (the writer's reading), and a closed item is dead", new_of(bare(shown(10))) == old_of(bare(shown(10))) and new_of(shown(32)).state == _model.DEAD, None)
# every other case of the fixture: the stored pair is the one the fields give, so the Model is the same either way
check("6 no model.read_stored, check_stored or DISAGREEMENTS is left: the decision has one source", not any(hasattr(_model, n) for n in ("read_stored", "check_stored", "DISAGREEMENTS", "STALE_AT_EDGE")), None)

# ---- 8. History: a confirm of an item written before the phase is still a confirm; a phase flip alone is no History line
import subprocess; from stackshot.web import render as root_render
from stackshot.web.ui import render as ui_render
STORE_DIR = str(T / "store")
gitc = lambda *a: subprocess.run(["git", "-C", STORE_DIR, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
gitc("init", "-q"); gitc("add", "-A"); gitc("commit", "-q", "-m", "fixture")
def distinct(i):                # the log follows a file across a rename by similarity, and the fixture items are near copies: give each History item a body of its own
    d = raw(i); d["description"] = "\n".join(f"- line {n} of item {i}: " + "x%d" % ((n * 7919 + i * 104729) % 100003) * 3 for n in range(12)); d["subject"] = f"[home] history item {i} " + "y%d" % (i * 31337)
    (T / f"store/g/{i}.json").write_text(json.dumps(d))
def events(bd, gid): return [k for _t, k, _h in bd.item_events(next(r for r in bd.rows if r["gid"] == gid))[0]]
put(41, needs=[BACK], state="doing"); distinct(41)                 # an item an older writer left: no phase
put(42, needs=[BACK], state="doing"); distinct(42)
gitc("add", "-A"); gitc("commit", "-q", "-m", "older revisions")
check("8 the older revision of the item to confirm holds no phase", "phase" not in mt(41), mt(41))
def confirm_revision(i, when):   # the revision a bare confirm writes: `confirmed` moved, the phase stamped by the save, nothing else (the writer stamp a session's confirm adds is no part of this check)
    d = raw(i); d["confirmed"] = when; server._phase_stamp(f"g{i}", d); (T / f"store/g/{i}.json").write_text(json.dumps(d))
confirm_revision(41, now0 - 5 * DAY)
check("8 …the confirm revision moved `confirmed` and added the phase, nothing else", mt(41).get("phase") == "alive" and raw(41)["confirmed"] == now0 - 5 * DAY, raw(41))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    kinds = events(bd, "g41")
    check(f"8 {label}: the first confirm of an item written before the phase shows the History `confirm` line", "confirm" in kinds, kinds)
# the same item confirmed a second time, now that the previous revision carries the phase
gitc("add", "-A"); gitc("commit", "-q", "-m", "confirmed once")
confirm_revision(41, now0 - 4 * DAY)
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    kinds = events(bd, "g41")
    check(f"8 {label}: …and a second confirm shows a second line", kinds.count("confirm") == 2, kinds)
# a confirm that also changed something else is not a bare confirm: no confirm line
d_ = raw(42); d_["confirmed"] = now0; d_["metadata"]["phase"] = "alive"; d_["metadata"]["next"] = "team-back: do another thing"
(T / "store/g/42.json").write_text(json.dumps(d_))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    kinds = events(bd, "g42")
    check(f"8 {label}: a confirm that also edits next is no bare confirm", "confirm" not in kinds and any(k == "edit" for k in kinds), kinds)
# a phase flip alone: alive stored, then waiting stored, nothing else changed
put(43, needs=[BACK], state="doing"); distinct(43); d_ = raw(43); d_["metadata"]["phase"] = "alive"; (T / "store/g/43.json").write_text(json.dumps(d_))
gitc("add", "-A"); gitc("commit", "-q", "-m", "phase alive")
d_["metadata"]["phase"] = "waiting"; (T / "store/g/43.json").write_text(json.dumps(d_))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    kinds = events(bd, "g43")
    check(f"8 {label}: a phase flip alone (alive to waiting, nothing else) adds no History line", kinds == ["created"], kinds)
# a failing stamp never fails the save
put(44, needs=[BACK], state="doing")
real_pair = _model.shown_pair
def boom(*a, **k): raise RuntimeError("stamp broke")
_model.shown_pair = boom
buf = io.StringIO()
try:
    with contextlib.redirect_stderr(buf):
        got44 = save(44)
finally:
    _model.shown_pair = real_pair
put(45, needs=[BACK], state="doing"); ref45 = save(45)
check("8 a phase stamp that raises is caught: the save lands, with no phase and the other fields as a normal save writes them, and a log line says so",
      "phase" not in got44["metadata"] and "phase: g44 not stamped" in buf.getvalue() and ref45["metadata"].get("phase") == "alive"
      and got44["metadata"] == {k: v for k, v in ref45["metadata"].items() if k != "phase"}, (got44, buf.getvalue()))

# ---- 7. the replay: a read-only copy of the live store, old derivation against the new read path
live = pathlib.Path(os.environ.get("PHASE_REPLAY_STORE") or "/nonexistent")
if live.is_dir() and any(p.is_dir() and len(p.name) == 1 for p in live.iterdir()):
    copy_dir = pathlib.Path(_scratch.mkdtemp(prefix="phasereplay-")) / "store"
    shutil.copytree(live, copy_dir, ignore=shutil.ignore_patterns("*.tmp", ".*"))
    for p in copy_dir.rglob("*"):
        if p.is_file():
            p.chmod(0o444)                  # a read-only copy: the replay never writes it, and a write would fail
    real_store = _core_store.STORE
    _core_store.STORE = copy_dir
    rows = []
    try:
        for gid, _path in _core_store._item_files():
            try:
                it = _service_store._load(gid)
            except Exception as e:  # noqa: BLE001
                rows.append((gid, None, f"load: {e}")); continue
            it = dict(it, gid=gid)
            after = lambda i_: _item_read._after_open(i_.get("metadata") or {})
            old = _model.view(bare(it), _model.derive(bare(it), now_, after_open=after, anchored=lambda i: False), now_, after, check=False)
            stamped = copy.deepcopy(it)
            server._phase_stamp(gid, stamped)
            new = _model.view(stamped, _model.derive(stamped, now_, after_open=after, anchored=lambda i: False), now_, after)
            rows.append((gid, it, (old, new, stamped, server._item_list(bare(it)), server._item_list(stamped), _notes_tool._model_lines(bare(it), short=True), _notes_tool._model_lines(stamped, short=True),
                                         _get_tool._fmt(bare(it)) + _get_tool._fmt(bare(it), brief=True), _get_tool._fmt(stamped) + _get_tool._fmt(stamped, brief=True))))
    finally:
        _core_store.STORE = real_store
    bad = [g for g, it, r in rows if it is None]
    check("7 replay: every item of the copy loads", not bad, bad[:5])
    got = [(g, it, r) for g, it, r in rows if it is not None]
    opens = [(g, it, r) for g, it, r in got if it.get("status") == "open"]
    same_state = [g for g, it, (old, new, st, l0, l1, m0, m1, f0, f1) in got if old == new]
    check("7 replay: the new read path equals the old derivation for every item (state, kind, reason, mover, today's state)", len(same_state) == len(got), [g for g, *_ in got if g not in same_state][:10])
    check("7 replay: …the wire list word, the model line, get's text and the brief's item block are identical for every item", all(l0 == l1 and m0 == m1 and f0 == f1 for g, it, (old, new, st, l0, l1, m0, m1, f0, f1) in got), [g for g, it, (old, new, st, l0, l1, m0, m1, f0, f1) in got if l0 != l1 or m0 != m1 or f0 != f1][:10])
    check("7 replay: every open item stores a phase after a save, equal to what the old derivation shows; no closed item does",
          all(st["metadata"].get("phase") == _model.shown_pair(old)[0] for g, it, (old, new, st, *_r) in opens)
          and not any("phase" in st["metadata"] for g, it, (old, new, st, *_r) in got if it.get("status") != "open"), None)
    check("7 replay: every open item stores a waits_on equal to the kind it shows (none for an alive one); no closed item does",
          all((st["metadata"].get("waits_on") or "") == _model.shown_pair(old)[1] for g, it, (old, new, st, *_r) in opens)
          and not any("waits_on" in st["metadata"] for g, it, (old, new, st, *_r) in got if it.get("status") != "open"), None)
    check("7 replay: …and a wait_kind was added to no item that stored none", all((st["metadata"].get("wait_kind") or "") == (it["metadata"].get("wait_kind") or "") for g, it, (old, new, st, *_r) in got), None)
    import collections
    by_phase = collections.Counter(_model.shown_pair(old)[0] for g, it, (old, *_r) in opens)
    by_kind = collections.Counter(_model.shown_pair(old)[1] or "-" for g, it, (old, *_r) in opens if _model.shown_pair(old)[0] == "waiting")
    by_state = collections.Counter(old.today or "-" for g, it, (old, *_r) in opens)
    stored_kind_n = sum(1 for g, it, r in opens if (it["metadata"].get("wait_kind") or ""))
    view_only = sum(1 for g, it, (old, *_r) in opens if _model.derive(bare(it), now_, after_open=lambda i_: _item_read._after_open(i_.get('metadata') or {}), anchored=lambda i: False).state == _model.ALIVE and old.state == _model.WAITING)
    print(f"replay: {len(got)} items read, {len(opens)} open, {len(got) - len(opens)} closed; identical {len(same_state)}/{len(got)} (open {sum(1 for g, it, (old, new, *_r) in opens if old == new)}/{len(opens)}); "
          f"open by phase {dict(by_phase)}; waiting by kind {dict(by_kind)}; open by state read {dict(by_state)}; storing a wait_kind {stored_kind_n}; waiting only by the view {view_only}")
else:
    print("replay: skipped (PHASE_REPLAY_STORE names no store here)")

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: phase scenario, {len(ran)} checks")
