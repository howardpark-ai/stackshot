"""Scenario test for the stamp of the stored phase and the kind of its wait on the open items (metadata.phase, metadata.waits_on; server._stamp_one, the stamp and unstamp ops of the migration
route, tools/stamp_phase.py) — fixture data, no live store written, no network, no server socket.

An open item stores `phase` (alive | waiting) and, when waiting, `waits_on` (time | anchor | item | relay | event): what the board shows it as. A save writes both (server._phase_stamp); the stamp pass
writes them on the items nobody has saved since, without being an event on the item: the server works the values out at write time under the item's lock and writes those two keys and nothing else.

  1  kind_stamped_per_case      waits_on equals the kind the board shows for all 23 cases (event too); an alive item has none; phase is right; model.stamp_values says the same
  2  wait_kind_never_added      wait_kind, watches, can_end, basis_wait and derive are identical before and after, per case
  3  only_two_keys_move         each item's JSON without the two keys deep-equals the original (an item with no activity clock gets none)
  4  no_side_effects            no GitHub job, no notice, no For you or landed row, no hand-off record, no search touch, writes.save never called; written_by unchanged; the state folder unchanged
  5  closed_untouched           a closed item is byte-identical and answers `refused`, a stale stamp on it included
  6  idempotent                 a second stamp answers `same` for all and rewrites no file
  7  stale_fixed                a stored waiting the fields no longer read is a `fix`: a read shows the stored waiting before and the fields' alive after
  8  dry_run_read_only          the script's dry run over a copy writes nothing, has the table's columns, flags `edge` for a wait ending within 24 hours, and its proof lines read 0
  9  undo_roundtrip             apply then undo gives byte-identical files (items stamped before return to their old values); twice is a no-op; after a session's write: `kept`
  9b apply_later_save_and_crash a session's save on a stamped item between batches is informational (exit 0), a stamp that itself changed the file still fails; undo after a crash between the server's write and
                                the script's record reads the server's pass record, not the planned keys
  10 race_moved                a writer between the read and the replace: the stamp answers `moved`, the write survives, the next run stamps it
  11 race_lock                  a thread updating the item while the stamp loops: the file ends with the update and the right stamp
  12 stored_waits_on            the stored kind is the one shown; a value that is no kind is half a pair, read from the fields and counted (model.UNSTAMPED)
  13 history_no_line            a stamp-only revision adds no History line and the first confirm still shows `confirm`, on both renderers
  14 gate                       refused with [model] migration off, for a sender or a machine outside the lists, for a body naming any key but the two, for an unknown item; no pause is taken
  8b frozen_clock              the dry run's before and after display passes read one clock: with the clock moving 61 s between them, two unfrozen passes differ on a floor-bound item and two frozen ones do not, and the
                                tool's own report (a copy with no waiting.json baseline) reads display_diff 0
  15 replay_zero_diff           the live store copied (cp -a) into a folder of its own: every open item shown as before after the stamp, only the two keys changed, the counts equal the dry run's
                                (skipped when PHASE_REPLAY_STORE names no store to copy, as in tests/phase_scenario.py)

    tests/run-suite stamp        → exit 0 / 1"""
import collections, contextlib, copy, datetime, fcntl, io, json, logging, os, pathlib, re, shutil, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pr2stamp-"); T = pathlib.Path(tmp)


def mk_toml(root):
    """A config whose every path is inside `root` (the test's own, or a copy the script is pointed at), with no GitHub mirror and no commit."""
    t = _instance.apply(_instance.base_toml(), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    t, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', t); assert n == 1
    t, n = re.subn(r'(?m)^git = true', 'git = false', t, count=1); assert n == 1
    t, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]', t); assert n == 1
    t, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", t); assert n == 1
    return t


(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
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
SENDER = "falcon-engineer"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.model import model as _model; from stackshot.waits import dated_wait as _dw; from stackshot.waits import watchers as wk; from stackshot.tools import stamp_phase as SP
from stackshot.service import update as _update_svc
from stackshot.web import search as _search
from stackshot.github import ghsync as _gh
from stackshot.core import instance as _core_instance
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import migrations as migsvc
from stackshot.service import handoff as handoff_svc, foryou_events as fyev
from stackshot.service import telling
from stackshot.core import store as _core_store
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
ST = T / "state/waiting.json"
ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = _cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False)
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # n hours after the suite started
wk_ = lambda h: hrs(h).replace(" ", "T")
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
now_ = time.time()


def put(i, status="open", letter="g", **meta):
    """An item file as an older writer left it: no phase, no waits_on, no activity clock; in the format the server writes (so a byte-for-byte comparison means something)."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    with open(T / f"store/{letter}/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def bytes_of(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_bytes()
def shown(i, letter="g"): return dict(raw(i, letter), gid=f"{letter}{i}")
def AO(i):
    return [x for x in W.after_of(i["metadata"]) if (T / f"store/{x[0]}/{x[1:]}.json").exists() and raw(int(x[1:]), x[0])["status"] == "open"]
def old_of(it, now=None):
    now = now_ if now is None else now
    return _model.view(it, _model.derive(it, now, after_open=AO, anchored=lambda i: False), now, AO, check=False)
def new_of(it, now=None):
    now = now_ if now is None else now
    return _model.view(it, _model.derive(it, now, after_open=AO, anchored=lambda i: False), now, AO)
def bare(it):
    out = copy.deepcopy(it); out.get("metadata", {}).pop("phase", None); out.get("metadata", {}).pop("waits_on", None); return out
KEYS = ("phase", "waits_on")
def without(d): return {**d, "metadata": {k: v for k, v in d["metadata"].items() if k not in KEYS}}
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def state_listing(): return sorted(str(p.relative_to(T / "state")) for p in (T / "state").rglob("*"))

put(31, needs=[BACK], state="doing")
put(32, status="completed", needs=[BACK], state="doing", outcome="done")
NEXT_FAR = "team-back: check the build later and report back to the owner"
BASIS = {"text": "the subscription renews on 2099-01-20", "wake": wk_(24 * 30), "by": BACK, "at": now0}
STEP_DAY = day(8)
# (id, what it is, the metadata, the phase it shows, the wait kind it shows ("" = alive), the wait_kind it stores)
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
    (15, "a held doing item with a far wake",                dict(needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5)),                                      "waiting", "time", ""),
    (16, "a doing item whose wake carries a wait_basis",     dict(needs=[BACK], state="doing", wake=wk_(24 * 30), wait_basis=BASIS, next=NEXT_FAR),               "waiting", "time", ""),
    (17, "a doing item with every open step dated later",    dict(needs=[BACK], state="doing", wake=wk_(24 * 7), next=f"team-back: after {STEP_DAY} run the check"), "waiting", "time", ""),
    (18, "a doing item with a near wake (a reminder)",       dict(needs=[BACK], state="doing", wake=wk_(0.5)),                                                     "alive", "", ""),
    (19, "a doing item with a far wake and no basis",        dict(needs=[BACK], state="doing", wake=wk_(24 * 5), next=NEXT_FAR),                                  "alive", "", ""),
    (20, "a doing item on hold with no wake",                dict(needs=[BACK], state="doing", hold=True),                                                       "alive", "", ""),
    (21, "no stored state, on hold with a wake (parked)",    dict(needs=[BACK], hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}), "waiting", "time", ""),
    (22, "no stored state, an open after link (blocked)",    dict(needs=[BACK], after=["g31"]),                                                                   "waiting", "item", ""),
    (23, "no stored state, a closed after link",             dict(needs=[BACK], after=["g32"]),                                                                   "alive", "", ""),
]
for i, _name, meta, *_ in CASES:
    put(i, **meta)
# closed items: one clean, one carrying a stale stamp
put(33, status="completed", needs=[BACK], state="doing", phase="waiting", waits_on="time", outcome="done")
orig = {i: copy.deepcopy(raw(i)) for i, *_ in CASES}
orig_bytes = {i: bytes_of(i) for i, *_ in CASES}
pre = {}
def probe_of(i):
    it = shown(i)
    return {"wait_kind": it["metadata"].get("wait_kind"), "watches": wk.watches(it), "can_end": wk.can_end(it["metadata"]), "basis": _dw.basis_wait(it, now_, AO) is not None,
            "derive": _model.derive(it, now_, AO, anchored=lambda i_: False)}
for i, *_ in CASES:
    pre[i] = probe_of(i)

# ---- 1. the stamp writes the kind the board shows
for i, name, meta, phase, kind, stored_kind in CASES:
    it = shown(i)
    check(f"1 fixture {i} ({name}) stores neither key before the stamp", not any(k in it["metadata"] for k in KEYS), it["metadata"])
    mod = old_of(it)
    check(f"1 {i} {name}: model.stamp_values gives ({phase}, {kind or 'none'})", _model.stamp_values(it, mod) == (phase, kind), _model.stamp_values(it, mod))
    r = server._stamp_one(f"g{i}")
    m = mt(i)
    check(f"1 {i} {name}: the stamp answers set and stores phase {phase}", r["action"] == "set" and m.get("phase") == phase, (r, m))
    check(f"1 {i} {name}: …and waits_on {kind or '(none: alive)'}", m.get("waits_on") == (kind or None) and ("waits_on" not in m or phase == "waiting"), m)
    check(f"1 {i} {name}: …the answer names the keys before (absent) and after", r["before"] == {"phase": None, "waits_on": None} and r["after"] == {"phase": phase, "waits_on": kind or None}, r)
closed_item = shown(32)
check("1 model.stamp_values gives nothing for a closed item", _model.stamp_values(closed_item, old_of(closed_item)) == ("", ""), None)

# ---- 2. wait_kind and what the watchers do with an item are not touched
for i, name, meta, phase, kind, stored_kind in CASES:
    post = probe_of(i)
    check(f"2 {i} {name}: wait_kind, watches, can_end, basis_wait and derive are the same after the stamp", post == pre[i], (pre[i], post))
    check(f"2 {i} {name}: …a wait_kind is stored only when the item stored one ({stored_kind or 'none'})", (mt(i).get("wait_kind") or "") == stored_kind, mt(i))

# ---- 3. only the two keys move
for i, name, *_ in CASES:
    check(f"3 {i} {name}: the file without the two keys equals the original, field for field (no activity clock seeded, no clock moved)", without(raw(i)) == without(orig[i]) and "activity" not in raw(i), None)
    check(f"3 {i} {name}: …and the metadata keeps its order, a new key last", list(mt(i))[:len(orig[i]["metadata"])] == list(orig[i]["metadata"]), list(mt(i)))

# ---- 4. a stamp is not an event on the item
for n in (51, 52, 53):
    put(n, needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5)) if n != 53 else put(n, needs=[BACK], state="doing")
calls = []
real = {(m, k): getattr(m, k) for m, k in ((fyev, "_foryou_on_save"), (fyev, "_landed_on_save"), (handoff_svc, "handoff_on_save"))}; real_tw = telling.tell_woken
real_gh = (_gh.enabled, _gh.on_change); real_touch = _search.touch; real_save = writes.save
def spy(name):
    def f(*a, **k): calls.append(name); return None
    return f
for m, k in real:
    setattr(m, k, spy(k))
telling.tell_woken = spy("_tell_woken")
_gh.enabled = lambda: True; _gh.on_change = spy("gh.on_change"); _search.touch = spy("search.touch"); writes.save = spy("save")
state0 = state_listing(); b0 = {n: bytes_of(n) for n in (51, 52, 53)}
try:
    res = [server._stamp_one(f"g{n}") for n in (51, 52, 53)]
finally:
    for (m, k), v in real.items(): setattr(m, k, v)
    telling.tell_woken = real_tw
    _gh.enabled, _gh.on_change = real_gh; _search.touch = real_touch; writes.save = real_save
check("4 a stamp calls no save, no GitHub job, no notice, no For you or landed row, no hand-off, no search touch", calls == [] and [r["action"] for r in res] == ["set"] * 3, (calls, res))
check("4 …no writer is recorded, no hand-off record is made, no clock moves", all("written_by" not in raw(n) and "handoff" not in mt(n) and raw(n)["updated"] == json.loads(b0[n])["updated"] for n in (51, 52, 53)), [raw(n) for n in (51,)])
check("4 …and the state folder is as it was", state_listing() == state0, (state0, state_listing()))
check("4 …no temporary file is left in the store", not list((T / "store/g").glob(".*")), list((T / "store/g").glob(".*")))

# ---- 5. a closed item is left as it is
b32, b33 = bytes_of(32), bytes_of(33)
r32, r33 = server._stamp_one("g32"), server._stamp_one("g33")
check("5 a closed item is refused (closed) and its file is byte-identical", r32["action"] == "refused" and "closed" in r32["why"] and bytes_of(32) == b32, r32)
check("5 …a closed item that carries a stale stamp is refused too and keeps it (its next save drops it)", r33["action"] == "refused" and bytes_of(33) == b33 and mt(33).get("phase") == "waiting", (r33, mt(33)))
check("5 …an item that is not there is refused", server._stamp_one("g9999")["action"] == "refused", None)

# ---- 6. a second stamp changes nothing
mt0 = {i: (T / f"store/g/{i}.json").stat().st_mtime_ns for i, *_ in CASES}
b_all = {i: bytes_of(i) for i, *_ in CASES}
res2 = [server._stamp_one(f"g{i}") for i, *_ in CASES]
check("6 a second stamp answers same for every case", [r["action"] for r in res2] == ["same"] * len(CASES), [r["action"] for r in res2 if r["action"] != "same"])
check("6 …and rewrites no file (bytes and mtimes equal)", all(bytes_of(i) == b_all[i] and (T / f"store/g/{i}.json").stat().st_mtime_ns == mt0[i] for i, *_ in CASES), None)

# ---- 7. a stored waiting the fields no longer read is a fix
put(61, needs=[BACK], state="doing", phase="waiting", waits_on="time")           # stored waiting, but the fields read alive (its wake has passed, say)
check("7 a stale stamp is what a read shows until the stamp (the stored waiting decides; the fields alone read alive)", new_of(shown(61)).state == _model.WAITING and old_of(shown(61)).state == _model.ALIVE, new_of(shown(61)))
r61 = server._stamp_one("g61")
check("7 …the stamp fixes it: phase alive, waits_on gone, the answer names what it was", r61["action"] == "set" and mt(61).get("phase") == "alive" and "waits_on" not in mt(61) and r61["before"] == {"phase": "waiting", "waits_on": "time"}, (r61, mt(61)))
check("7 …and a read after it shows alive, as the fields do", new_of(shown(61)).state == _model.ALIVE and new_of(shown(61)) == old_of(shown(61)), None)

# ---- 8. the script's dry run over a copy
put(62, needs=[BACK], state="doing")                                                  # nothing stored, alive: an add
put(63, needs=[BACK], state="doing", hold=True, wake=wk_(12))                         # nothing stored, a held doing item waking in 12 hours: an edge
put(64, needs=[BACK], state="doing", phase="waiting", waits_on="time")                # stale: a fix
CP = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-copy-"))
shutil.rmtree(CP); shutil.copytree(T, CP)
(CP / "stackshot.toml").write_text(mk_toml(str(CP)), encoding="utf-8")
RDIR = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-rep-"))
env_ = {k: v for k, v in os.environ.items() if k != "STACKSHOT_CONFIG"}; env_["STACKSHOT_CONFIG"] = str(T / "stackshot.toml")
run = lambda *a, **kw: subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/stamp_phase.py"), *a], capture_output=True, text=True, env={**env_, **kw.get("env", {})}, timeout=600)
def tree(root): return {str(p.relative_to(root)): p.read_bytes() for p in sorted(pathlib.Path(root).rglob("*")) if p.is_file()}
live_before, copy_before = tree(T / "store"), tree(CP)
p = run("--dry-run", "--store", str(CP), "--report-dir", str(RDIR))
reps = sorted(RDIR.glob("*.json"))
check("8 a dry run over a copy ends well and writes its report (JSON and markdown)", p.returncode == 0 and len(reps) == 1 and reps[0].with_suffix(".md").exists(), (p.returncode, p.stderr[-800:], p.stdout[-400:]))
check("8 …it writes nothing: neither the original store nor the copy changed by a byte", tree(T / "store") == live_before and tree(CP) == copy_before, None)
if reps:
    rj = json.loads(reps[0].read_text()); md = reps[0].with_suffix(".md").read_text()
    row = {r["gid"]: r for r in rj["rows"]}
    check("8 …the table has the columns (item, old display, stored before, shown now, stored after, watches before=after, change) in the markdown",
          all(w in md for w in ("| item | old display (state, list) | stored before (phase / waits_on / wait_kind) | shown now (phase / kind) | stored after | watches before=after | change |",)), md[:1500])
    check("8 …and in the JSON rows", all({"item", "old_state", "old_list", "before", "wait_kind", "shown", "after", "watches", "change"} <= set(r) for r in rj["rows"]) and len(rj["rows"]) == rj["counts"]["open"], rj["rows"][:1])
    check("8 …a stamped item is `same`, one with nothing stored an `add`, a stale one a `fix`", row["g1"]["change"] == "same" and row["g62"]["change"] == "add" and row["g64"]["change"] == "fix" and row["g61"]["change"] == "same", {g: row[g]["change"] for g in ("g1", "g61", "g62", "g64")})
    check("8 …a wait ending within 24 hours is flagged `edge`, and an alive item is not", row["g63"]["change"] == "edge" and row["g63"]["shown"] == {"phase": "waiting", "waits_on": "time"} and row["g62"]["shown"] == {"phase": "alive", "waits_on": None}, row["g63"])
    check("8 …the proof lines read 0 (display, watches, files outside the two keys, the store written)", all(len(v) == 0 for v in rj["proofs"].values()), rj["proofs"])
    check("8 …a closed item carrying a stamp is counted and not changed", "board#33" in rj["closed_with_a_stale_stamp"] or "g33" in rj["closed_with_a_stale_stamp"], rj["closed_with_a_stale_stamp"])
    check("8 …the items that store a wait_kind are listed and equal to waits_on (no exception)", len(rj["stored_wait_kind"]) == 5 and rj["stored_wait_kind_exceptions"] == [], rj["stored_wait_kind"])
    wk_counts = collections.Counter(w["waits_on"] for w in (row[g]["shown"] for g in row) if w.get("phase") == "waiting")
    check("8 …the waiting-by-kind totals add up to the rows", rj["waiting_by_kind"] == dict(sorted(wk_counts.items())), (rj["waiting_by_kind"], wk_counts))
    pe = run("--dry-run", "--store", str(CP), "--report-dir", str(RDIR), "--expect-waiting", ",".join(f"{k}={v}" for k, v in sorted(wk_counts.items())))
    check("8 …--expect-waiting compares the counts with a figure named", pe.returncode == 0 and any("equal" in (json.loads(f.read_text()).get("expect") or "") for f in sorted(RDIR.glob("*.json"))), pe.stderr[-300:])
pl = run("--dry-run", "--store", str(T), "--report-dir", str(RDIR))
check("8 …a store that is the live store is refused", pl.returncode != 0 and "live store" in (pl.stderr + pl.stdout), (pl.returncode, pl.stderr[-300:]))
check("8 …a dry run needs --store; --apply and --undo need --sender", run("--dry-run").returncode != 0 and run("--apply").returncode != 0 and run("--undo", "x.json").returncode != 0, None)

# ---- 8b. one clock for both display passes of the proof
SEED = "g9999"
def clock_diff(freeze):
    """display_of over every open item twice with the clock moved on 61 s between the passes (the stamp between them takes that long), the way the dry run reads them: → the items whose display differs, and how many were read.
    `freeze` holds one clock for both passes (SP.frozen), as the dry run does. The board prints no computed date and no past-due mark, so what the clock still moves is the age in words of a stale item: one seeded copy of an item (SEED) was confirmed 30 s short of two days before the first pass, which reads "stale 1 d" and, 61 s later, "stale 2 d"."""
    its = SP.load_dir(T / "store"); gids = sorted((g for g, it in its.items() if it.get("status") == "open"), key=SP.num)
    t_a = time.time(); clk = [t_a]; real_time = time.time; time.time = lambda: clk[0]
    seed = copy.deepcopy(its["g8"]); seed["confirmed"] = t_a - 2 * 86400 + 30
    for k in ("hold", "wake", "after", "cap_ok", "end"): seed["metadata"].pop(k, None)            # not held (a held item is never stale), so its age shows
    seed["metadata"]["needs"] = "decision"; seed["metadata"]["mover"] = _core_instance.OWNER
    its[SEED] = seed; gids.append(SEED)
    def read():
        with (SP.frozen(t_a) if freeze else contextlib.nullcontext()):
            return {g: SP.display_of(server, its[g], g) for g in gids}
    try:
        d_a = read(); clk[0] += 61; d_b = read()
    finally:
        time.time = real_time
    return [g for g in gids if d_a[g] != d_b[g]], len(gids)
st_text = ST.read_text(encoding="utf-8")
try:
    ST.write_text("{}")                                          # no baseline, as in a copy of the store
    moved, n_open = clock_diff(False); held, _ = clock_diff(True)
finally:
    ST.write_text(st_text, encoding="utf-8")
check("8b the clock moves 61 s between two unfrozen display passes: the seeded item whose age in words rolls over between them reads differently (the test bites)", moved == [SEED] and n_open > 20, (moved, n_open))
check("8b …with SP.frozen holding one clock for both passes, no item reads differently", held == [], held)
with SP.frozen(123.0):
    in_ = (time.time(), time.time())
check("8b …inside the block the clock reads the one value every time", in_ == (123.0, 123.0), in_)
try:
    with SP.frozen(1.0):
        raise RuntimeError("x")
except RuntimeError:
    pass
check("8b …and an error inside the block puts the real clock back", time.time() > 1e9, time.time())
CP2 = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-nobase-"))
shutil.rmtree(CP2); shutil.copytree(CP, CP2)
(CP2 / "stackshot.toml").write_text(mk_toml(str(CP2)), encoding="utf-8"); (CP2 / "state/waiting.json").unlink(missing_ok=True)
RDIR2 = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-rep2-"))
p2 = run("--dry-run", "--store", str(CP2), "--report-dir", str(RDIR2))
reps2 = sorted(RDIR2.glob("*.json"))
rj2 = json.loads(reps2[0].read_text()) if reps2 else {}
check("8b the dry run over a copy with no waiting.json baseline reports its display diff proof as 0 and ends well", p2.returncode == 0 and len(reps2) == 1 and (rj2.get("proofs") or {}).get("display_diff") == [] and rj2.get("display_diff_detail") == {}, (p2.returncode, (rj2.get("proofs") or {}), p2.stderr[-400:]))

# ---- 9. apply then undo
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return server._client_post("box-a", "migrate", {**body, "sender": SENDER})
CFGM["migration"] = True
RUN = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-run-"))
import argparse
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="")
put(71, needs=[BACK], state="doing", phase="alive")                                         # stamped before, agrees: nothing to do
put(72, needs=[BACK], state="doing", phase="waiting")                                       # stamped before, the fields read alive: a fix
put(73, needs=[BACK], state="parked", hold=True, wake=day(20), cap_ok={"wake": day(20), "by": "the owner", "quote": "park it until then"}, phase="alive")      # stamped before, wrong
put(74, needs=[BACK], state="parked", hold=True, wake=day(21), cap_ok={"wake": day(21), "by": "the owner", "quote": "park it until then"})               # nothing stored, waiting
put(75, needs=[BACK], state="doing")                                                        # nothing stored, alive
snap0 = snapshot()
def cli(fn, app=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    cli.err = err.getvalue()
    try: return rc, json.loads(out.getvalue())
    except ValueError: return rc, out.getvalue()
rc1, out1 = cli(SP.apply)
snap1 = snapshot()
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("9 apply ends well, asks for the plan first and writes an undo file", rc1 == 0 and undo_file.is_file() and out1["written"] >= 5 and out1["files_changed_outside_the_two_keys"] == 0, (rc1, out1))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("9 …the undo file names each item with its keys before and after, the sha256 of the file before and the real result", {"pass_id", "by", "when", "store", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and set(e["before"]) == set(KEYS) for e in uj["items"]) and all(e["result"] in ("set", "same") for e in uj["items"]), uj["items"][:2])
check("9 …the three items stamped before are in it with their old values, and a stamp-ready one is stored", {e["item"]: e["before"] for e in uj["items"]}.get("g72") == {"phase": "waiting", "waits_on": None} and {e["item"]: e["before"] for e in uj["items"]}.get("g73") == {"phase": "alive", "waits_on": None}
      and mt(74).get("waits_on") == "time" and mt(75).get("phase") == "alive" and mt(72).get("phase") == "alive" and "g71" not in {e["item"] for e in uj["items"]}, (mt(72), mt(73), mt(74)))
check("9 …and the pass kept its results on the server (<state>/migration/<pass id>.json)", (T / "state/migration" / f"{uj.get('pass_id')}.json").is_file() and len(json.loads((T / "state/migration" / f"{uj['pass_id']}.json").read_text())["items"]) == out1["written"], uj.get("pass_id"))
rc2, out2 = cli(SP.apply)
check("9 a second apply stamps nothing and writes no file", rc2 == 0 and snapshot() == snap1 and out2.get("stamped") == 0, (rc2, out2))
rc3, out3 = cli(SP.undo, undo=str(undo_file))
check("9 undo puts every file back byte for byte, the items stamped before returning to their old values", rc3 == 0 and snapshot() == snap0 and out3["results"].get("set") == out1["written"], (rc3, out3, [k for k in snap0 if snap0[k] != snapshot().get(k)][:5]))
rc4, out4 = cli(SP.undo, undo=str(undo_file))
check("9 …undo twice is a no-op (every answer is same)", rc4 == 0 and snapshot() == snap0 and set(out4["results"]) == {"same"}, (rc4, out4))
rc5, out5 = cli(SP.apply)
undo2 = pathlib.Path(out5["undo"])
_update_svc._update("g75", sender="home-front", hold=True, wake=day(30), wait_basis=f"the vendor ships on {day(33)}")         # a session parks it after the stamp: the save restamps it waiting
snap_s = snapshot()
rc6, out6 = cli(SP.undo, undo=str(undo2))
check("9 …after a session's write the item answers kept and is left as the session saved it; the others are put back", rc6 == 0 and out6["results"].get("kept") == 1 and "board#75" in " ".join(out6["kept_because_a_later_save_restamped_them"]) and bytes_of(75) == snap_s["75.json"]
      and mt(74).get("waits_on") is None and out6["results"].get("set") == out5["written"] - 1, (rc6, out6))
_update_svc._update("g75", sender="home-front", clear_hold=True)

# ---- 9b. a session saves an already-stamped item between batches; and a run that dies after the server wrote a batch
def item_file(g): return T / f"store/{g[0]}/{g[1:]}.json"
class Hooked(DirectApp):
    """DirectApp with a hook around each real stamp batch (one with a pass_id and no dry)."""
    def __init__(self, before=None, after=None): super().__init__(); self.before, self.after, self.n = before, after, 0
    def call(self, body):
        real = body["op"] == "stamp" and body.get("pass_id") and not body.get("dry")
        if real:
            self.n += 1
            if self.before: self.before(self.n, body)
        r = super().call(body)
        if real and self.after: self.after(self.n, body)
        return r
orig_chunks = SP.chunks
SP.chunks = lambda xs, n=2: orig_chunks(xs, n)          # batches of two, so there is a "between batches"
for i in (91, 92, 93, 94, 95, 96): put(i, needs=[BACK], state="doing")
saved = {}
def session_saves(n, body):
    if n == 1:
        g = saved["g"] = body["items"][0]
        d = json.loads(item_file(g).read_text()); d["updated"] += 5; d["metadata"]["next"] = "team-back: a session saved this between batches"
        item_file(g).write_text(json.dumps(d, ensure_ascii=False, indent=1))
rcA, outA = cli(SP.apply, app=Hooked(after=session_saves))
errA = cli.err
check("9b a session's save on an already-stamped item between batches: exit 0, not counted outside the two keys, listed as informational", rcA == 0 and isinstance(outA, dict) and outA["files_changed_outside_the_two_keys"] == 0
      and outA["saved_by_a_session_since_our_stamp"] == [_gh.shown(saved["g"])] and "informational, not a failure" in errA and _gh.shown(saved["g"]) in errA and outA["written"] >= 6, (rcA, outA, errA[-300:]))
check("9b …and the session's save stands in the file", raw(int(saved["g"][1:]))["metadata"]["next"] == "team-back: a session saved this between batches", None)
# the control: a stamp that itself changes something outside the two keys still fails the run
for i in (97, 98): put(i, needs=[BACK], state="doing")
real_sw = server._stamp_write
server._stamp_write = lambda p, raw_, h0, edits: real_sw(p, dict(raw_, description="changed by a faulty stamp"), h0, edits)
try: rcB, outB = cli(SP.apply)
finally: server._stamp_write = real_sw
check("9b the control: a stamp that changed the file outside the two keys (nothing else saved it) still counts and exits 1", rcB == 1 and outB["files_changed_outside_the_two_keys"] == 2 and outB["saved_by_a_session_since_our_stamp"] == [], (rcB, outB))
# a run that dies after the server wrote its batch and before the script recorded it
put(74, needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5))
tweaked = {}
def drift(n, body):                       # between the plan (waiting / time) and the write the item reads alive: the real stamp is not the planned one
    d = json.loads(item_file("g74").read_text()); d["metadata"].pop("hold"); d["metadata"].pop("wake")
    item_file("g74").write_text(json.dumps(d, ensure_ascii=False, indent=1)); tweaked["bytes"] = bytes_of(74)
def die(n, body): raise RuntimeError("the run died after the server wrote the batch")
crashed = False
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try: SP.apply(argparse.Namespace(**vars(args)), Hooked(before=drift, after=die))
    except RuntimeError: crashed = True
ufile = max(RUN.glob("*/undo.json"), key=lambda p: p.stat().st_mtime)
uc = json.loads(ufile.read_text()); ent = {e["item"]: e for e in uc["items"]}
check("9b a crashed run leaves the entry with no result and the planned keys, while the file holds the real ones", crashed and ent["g74"]["result"] is None and ent["g74"]["after"] == {"phase": "waiting", "waits_on": "time"}
      and (mt(74).get("phase"), mt(74).get("waits_on")) == ("alive", None), (crashed, ent.get("g74"), mt(74)))
rcU, outU = cli(SP.undo, undo=str(ufile))
check("9b undo of it reads the server's pass record: the entry is put back (set, not kept) and the file is byte for byte what it was before the stamp", rcU == 0 and outU["results"] == {"set": 1} and outU["kept_because_a_later_save_restamped_them"] == []
      and bytes_of(74) == tweaked["bytes"] and "taken from the server's pass record" in cli.err, (rcU, outU, cli.err[-300:]))
SP.chunks = orig_chunks
CFGM["migration"] = False

# ---- 10. a writer between the read and the replace
put(81, needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5))
real_commit = server._stamp_commit
def racing(p, tmpf, h0):
    d = json.loads(p.read_text()); d["metadata"]["next"] = "team-back: a session wrote this meanwhile"; d["updated"] = d["updated"] + 5
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    return real_commit(p, tmpf, h0)
server._stamp_commit = racing
try:
    r81 = server._stamp_one("g81")
finally:
    server._stamp_commit = real_commit
check("10 a write between the read and the replace: the stamp answers moved, the write stands and nothing was stamped", r81["action"] == "moved" and mt(81)["next"] == "team-back: a session wrote this meanwhile" and "phase" not in mt(81), (r81, mt(81)))
check("10 …no temporary file is left", not list((T / "store/g").glob(".*")), list((T / "store/g").glob(".*")))
r81b = server._stamp_one("g81")
check("10 …the next run stamps it, and the session's write survives", r81b["action"] == "set" and mt(81)["next"] == "team-back: a session wrote this meanwhile" and mt(81)["phase"] == "waiting", (r81b, mt(81)))

# ---- 11. a session's update while the stamp loops
put(82, needs=[BACK], state="doing")
stop = threading.Event(); errs = []; done = []
def worker():
    try:
        for n in range(50):
            _update_svc._update("g82", sender="home-front", next=f"team-back: step {n}")
        done.append(1)
    except Exception as e:  # noqa: BLE001
        errs.append(repr(e))
    finally:
        stop.set()
th = threading.Thread(target=worker); th.start()
acts = collections.Counter()
rounds = 0
while rounds < 50 or not stop.is_set():
    acts[server._stamp_one("g82")["action"]] += 1; rounds += 1
th.join()
acts[server._stamp_one("g82")["action"]] += 1
f82 = raw(82)
check("11 a thread updating the item while the stamp loops: no error, and no round was moved or refused", not errs and done and set(acts) <= {"set", "same"}, (errs, acts))
check("11 …the file ends with the last update and the right stamp", "step 49" in f82["metadata"]["next"] and (f82["metadata"].get("phase"), f82["metadata"].get("waits_on")) == (("alive", None)) and
      server._stamp_values("g82", f82) == ("alive", ""), (f82["metadata"], acts))

# ---- 12. the read-back check of waits_on
it10 = shown(10)
u0 = _model.UNSTAMPED["count"]
got = new_of(it10)
check("12 a waits_on that agrees: the stored kind is read, and nothing is counted", _model.UNSTAMPED["count"] == u0 and got == old_of(bare(it10)) and _model.stored_waits_on(it10) == "time", _model.UNSTAMPED)
wrong = shown(10); wrong["metadata"]["waits_on"] = "item"
got = new_of(wrong)
check("12 a waits_on of another kind than the fields read: the stored kind is the one shown, nothing counted", got.wait.kind == "item" and old_of(bare(wrong)).wait.kind == "time" and _model.UNSTAMPED["count"] == u0, (got, _model.UNSTAMPED))
alive_w = shown(1); alive_w["metadata"]["waits_on"] = "time"
got = new_of(alive_w)
check("12 a waits_on on an item stored alive is not read: the item is alive (a phase alive carries no kind)", got.state == _model.ALIVE and _model.UNSTAMPED["count"] == u0, got)
odd = shown(10); odd["metadata"]["waits_on"] = "sleeping"
check("12 a value that is no kind is read as none: half a pair, read as the writer would store it and counted", _model.stored_waits_on(odd) == "" and new_of(odd) == old_of(bare(odd)) and _model.UNSTAMPED["count"] == u0 + 1, _model.UNSTAMPED)
closed_w = shown(32); closed_w["metadata"]["waits_on"] = "time"
check("12 a closed item reads no stored waits_on", _model.stored_waits_on(closed_w) == "" and new_of(closed_w).state == _model.DEAD, None)

# ---- 14. the gate
call = lambda machine="box-a", **body: server._client_post(machine, "migrate", {"sender": SENDER, **body})
put(91, needs=[BACK], state="doing")
b91 = bytes_of(91)
CFGM["migration"] = False
st_, d_ = call(op="stamp", items=["g91"])
check("14 the route is refused while [model] migration is off", st_ == 403 and "off" in d_["error"] and bytes_of(91) == b91, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="stamp", items=["g91"], sender="somebody-else")
check("14 …and for a sender outside [model] migration_senders", st_ == 403 and "migration_senders" in d_["error"] and bytes_of(91) == b91, (st_, d_))
st_, d_ = call(machine="home-evil", op="stamp", items=["g91"])
check("14 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(91) == b91, (st_, d_))
st_, d_ = call(op="stamp", items=["g91"], writes=[{"item": "g91", "set": {"mover": BACK}}])
check("14 …a body naming any key but the two (a write, a set) is refused whole", st_ == 400 and "phase and waits_on and nothing else" in d_["error"] and bytes_of(91) == b91, (st_, d_))
st_, d_ = call(op="unstamp", items=[{"item": "g91", "before": {"phase": None, "waits_on": None, "wait_kind": None}, "after": {"phase": "alive", "waits_on": None}}])
check("14 …an undo entry naming a third key (wait_kind) is refused", st_ == 200 and d_["results"][0]["action"] == "refused" and "no other key" in d_["results"][0]["why"], (st_, d_))
st_, d_ = call(op="unstamp", items=[{"item": "g91", "before": {"phase": None, "waits_on": None}, "after": {"phase": "dead", "waits_on": None}}])
check("14 …and one naming a value no stamp writes", d_["results"][0]["action"] == "refused", d_)
st_, d_ = call(op="unstamp", items=[{"item": "g91", "extra": 1, "before": {"phase": None, "waits_on": None}, "after": {"phase": None, "waits_on": None}}])
check("14 …and an entry with a key of its own", d_["results"][0]["action"] == "refused", d_)
st_, d_ = call(op="stamp", items=["g9999", "nonsense"])
check("14 …an unknown item and a malformed id are refused one by one", st_ == 200 and [r["action"] for r in d_["results"]] == ["refused", "refused"], (st_, d_))
st_, d_ = call(op="stamp", items=[])
check("14 …an empty list is refused", st_ == 400, (st_, d_))
st_, d_ = call(op="unstamp", items=["g91"], dry=True)
check("14 …dry goes with stamp only", st_ == 400 and "dry" in d_["error"], (st_, d_))
st_, d_ = call(op="stamp", items=["g91"], dry=True)
check("14 …a dry stamp answers what it would do and writes nothing", st_ == 200 and d_["results"][0]["action"] == "would_set" and d_["results"][0]["after"] == {"phase": "alive", "waits_on": None} and bytes_of(91) == b91, (st_, d_))
st_, d_ = call(op="stamp", items=["g91"])
check("14 …a stamp needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not wk.holding() and mt(91)["phase"] == "alive", (st_, d_, wk.holding()))
CFGM["migration"] = False

# ---- 13. History
from stackshot.web import render as root_render
from stackshot.web.ui import render as ui_render
STORE_DIR = str(T / "store")
gitc = lambda *a: subprocess.run(["git", "-C", STORE_DIR, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
def distinct(i):
    d = raw(i); d["description"] = "\n".join(f"- line {n} of item {i}: " + "x%d" % ((n * 7919 + i * 104729) % 100003) * 3 for n in range(12)); d["subject"] = f"[home] history item {i} " + "y%d" % (i * 31337)
    (T / f"store/g/{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
def events(bd, gid): return [k for _t, k, _h in bd.item_events(next(r for r in bd.rows if r["gid"] == gid))[0]]
put(101, needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5)); distinct(101)
put(102, needs=[BACK], state="doing", hold=True, wake=wk_(24 * 5)); distinct(102)
gitc("init", "-q"); gitc("add", "-A"); gitc("commit", "-q", "-m", "older revisions")
r_stamp = server._stamp_one("g101")
check("13 a stamp-only revision adds phase waiting and waits_on time", r_stamp["action"] == "set" and mt(101).get("phase") == "waiting" and mt(101).get("waits_on") == "time", mt(101))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    kinds = events(mod_.Board(STORE_DIR), "g101")
    check(f"13 {label}: …and adds no History line", kinds == ["created"], kinds)
def confirm_revision(i, when):
    d = raw(i); d["confirmed"] = when; server._phase_stamp(f"g{i}", d); (T / f"store/g/{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
confirm_revision(102, now0 - 5 * DAY)
check("13 the confirm revision of a waiting item moved `confirmed` and added the phase and waits_on, nothing else", mt(102).get("phase") == "waiting" and mt(102).get("waits_on") == "time" and raw(102)["confirmed"] == now0 - 5 * DAY, raw(102))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    kinds = events(mod_.Board(STORE_DIR), "g102")
    check(f"13 {label}: the first confirm of an item written before the stamp still shows the `confirm` line", "confirm" in kinds, kinds)
gitc("add", "-A"); gitc("commit", "-q", "-m", "confirmed once")
confirm_revision(102, now0 - 4 * DAY)
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    kinds = events(mod_.Board(STORE_DIR), "g102")
    check(f"13 {label}: …and a second confirm shows a second line", kinds.count("confirm") == 2, kinds)

# ---- 15. the replay over a copy of the live store
src = pathlib.Path(os.environ.get("PHASE_REPLAY_STORE") or "/nonexistent").expanduser()
if src.is_dir() and any(q.is_dir() and len(q.name) == 1 for q in src.iterdir()):
    R = pathlib.Path(_scratch.mkdtemp(prefix="pr2stamp-replay-"))
    lockfd = os.open(R, os.O_RDONLY | os.O_DIRECTORY); fcntl.flock(lockfd, fcntl.LOCK_SH)          # tmpfiles ageing skips a locked folder
    real_store = _core_store.STORE
    try:
        subprocess.run(["cp", "-a", str(src), str(R / "store")], check=True)
        shutil.rmtree(R / "store" / ".git", ignore_errors=True)
        for d in ("state", "brain/projects", "secrets", "fleet"): (R / d).mkdir(parents=True, exist_ok=True)
        (R / "stackshot.toml").write_text(mk_toml(str(R)), encoding="utf-8")
        pr = run("--dry-run", "--store", str(R), "--report-dir", str(RDIR / "replay"))
        rep_j = sorted((RDIR / "replay").glob("*.json"))
        check("15 replay: the dry run over the copy of the live store ends well with every proof at 0", pr.returncode == 0 and len(rep_j) == 1, (pr.returncode, ({k: v for k, v in (json.loads(rep_j[0].read_text()).get("proofs") or {}).items() if v}, json.loads(rep_j[0].read_text()).get("display_diff_detail")) if rep_j else None, pr.stderr[-300:]))
        _core_store.STORE = R / "store"
        items0 = SP.load_dir(R / "store")
        opens = sorted((g for g, it in items0.items() if it.get("status") == "open"), key=SP.num)
        t_ = time.time()                                              # one clock for both reads: the stamp between them takes a while and a minute edge is no change of the stamp's
        with SP.frozen(t_):
            d0 = {g: SP.display_of(server, items0[g], g) for g in opens}; w0 = {g: bool(wk.watches(items0[g])) for g in opens}
        applied = []
        for k in range(0, len(opens), 40):
            applied += migsvc.migrate_write({"op": "stamp", "items": opens[k:k + 40], "sender": SENDER}, "box-a")["results"]
        items1 = SP.load_dir(R / "store")
        with SP.frozen(t_):
            d1 = {g: SP.display_of(server, items1[g], g) for g in opens}; w1 = {g: bool(wk.watches(items1[g])) for g in opens}
        kinds1 = collections.Counter(items1[g]["metadata"].get("waits_on") for g in opens if items1[g]["metadata"].get("phase") == "waiting")
        check("15 replay: every open item is shown exactly as before the stamp (state, kind, list word, model line, get's text, the brief's block)", all(d0[g] == d1[g] for g in opens), [g for g in opens if d0[g] != d1[g]][:8])
        check("15 replay: …the watchers own the same items", w0 == w1, [g for g in opens if w0[g] != w1[g]][:8])
        check("15 replay: …only the two keys changed in the files, and no closed item was touched", SP.files_outside(items0, items1) == [] and all(items0[g] == items1[g] for g in items0 if g not in opens), SP.files_outside(items0, items1)[:8])
        check("15 replay: …every open item stores a phase, and a waits_on exactly when it is waiting", all(items1[g]["metadata"].get("phase") in ("alive", "waiting") and ("waits_on" in items1[g]["metadata"]) == (items1[g]["metadata"]["phase"] == "waiting") for g in opens), None)
        rj_ = json.loads(rep_j[0].read_text()) if rep_j else {"waiting_by_kind": None}
        check("15 replay: …the waiting-by-kind counts equal the dry run's", rj_["waiting_by_kind"] == dict(sorted(kinds1.items())), (rj_["waiting_by_kind"], dict(kinds1)))
        stored_wk = [g for g in opens if items0[g]["metadata"].get("wait_kind")]
        check("15 replay: …every stored wait_kind equals the waits_on stamped beside it, and wait_kind was added to no item", all(items1[g]["metadata"].get("waits_on") == items0[g]["metadata"]["wait_kind"] for g in stored_wk)
              and all((items1[g]["metadata"].get("wait_kind") or "") == (items0[g]["metadata"].get("wait_kind") or "") for g in opens), [g for g in stored_wk if items1[g]["metadata"].get("waits_on") != items0[g]["metadata"]["wait_kind"]])
        check("15 replay: …the pass wrote nothing it refused", all(r["action"] in ("set", "same") for r in applied), [r for r in applied if r["action"] not in ("set", "same")][:3])
        print(f"replay: {len(items0)} items copied, {len(opens)} open stamped ({collections.Counter(r['action'] for r in applied)}); waiting by kind {dict(kinds1)}; storing a wait_kind {len(stored_wk)}; "
              f"changes by row {rj_.get('by_change')}")
    finally:
        _core_store.STORE = real_store
        os.close(lockfd)
        shutil.rmtree(R, ignore_errors=True)
else:
    print("replay: skipped (PHASE_REPLAY_STORE names no store here)")

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: stamp scenario, {len(ran)} checks")
