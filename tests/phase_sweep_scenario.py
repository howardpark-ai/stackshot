"""Scenario test for the phase sweep (server._phase_sweep, _phase_tick; the minute set's tick `phase_sweep`): the stored phase and waits_on kept true as the clock moves, and the readers take the decision from the pair, so the sweep is what moves the display at an edge.
Fixture data, no live store written, no network, no server socket. The clock is held (tools/stamp_phase.frozen) at every step, so an edge is crossed by choosing the time, never by waiting.

An open item stores `phase` and `waits_on` (tests/phase_scenario.py, tests/stamp_scenario.py). A save restamps them, but the clock moves what the board shows an item as without any write. Once a minute, at the
start and after a config reload the sweep works every open item's pair out again WITHOUT the item lock, compares it with the stored one and calls the stamp pass's own writer (_stamp_one) only for a difference.

  1  edge_E1..E3        a stored value goes stale at the edge (E1 the wake coming within dated_wait_min_hours, E2 a wait_basis wake passing, E3 local midnight of the day a dated step waits for): the sweep just
                        before the edge writes nothing, one sweep after it restamps the item, a second writes nothing (bytes and mtimes equal); only the two keys change
  2  edge_E4..E6        E4 an `after` item closed while the old release stands down, E5 an anchor scoped to / taken off an item with no wait_kind, E6 a changed `dated_wait_min_hours` and a config reload
  3  no_lock            a sweep with nothing to stamp never takes `writes.ITEM_LOCK`; one that stamps waits for it
  4  not_an_event        no save, no GitHub job, no notice, no For you or landed row, no hand-off record, no search touch, no written_by, no state file; no History line on either renderer
  5  closed_untouched   a closed item (a stale stamp on it too) is byte-identical, an unreadable file is skipped
  6  moved              a writer between the read and the replace: `moved`, the write stands, the next sweep stamps it
  7  standby            STACKSHOT_READ_ONLY: no sweep, no write
  8  tick_and_status    the tick is in the table after the anchor pass and skipped while the board is held; one publish only when something was stamped; `phase_sweep` in GET /audit/status
  9  shifts             the fixture store (and a copy of the live store, when PHASE_REPLAY_STORE names one) at +30 min, +1 h, +6 h, the next local midnight, +3 days and +40 days: after one sweep every open
                        item stores the pair derived now, a second sweep writes nothing, nothing but the two keys changed, and the displayed output after the sweep is byte-equal to what the fields alone gave before it

    tests/run-suite phase_sweep        → exit 0 / 1"""
import collections, contextlib, copy, datetime as dt, inspect, io, json, logging, os, pathlib, re, shutil, subprocess, sys, threading, time, zoneinfo
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="phasesweep-"); T = pathlib.Path(tmp)


def mk_toml(root, min_hours=None):
    t = _instance.apply(_instance.base_toml(), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    t, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', t); assert n == 1
    t, n = re.subn(r'(?m)^git = true', 'git = false', t, count=1); assert n == 1
    t, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]', t); assert n == 1
    t, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", t); assert n == 1
    if min_hours is not None:
        t, n = re.subn(r'(?m)^dated_wait_min_hours = \d+(\.\d+)?', f'dated_wait_min_hours = {min_hours}', t); assert n == 1
    return t


(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None); os.environ.pop("STACKSHOT_READ_ONLY", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [],
                                                                                "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
BACK = "team-back"; OWN = "Oliver"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.core import runner as R; from stackshot.model import model as _model; from stackshot.tools import stamp_phase as SP
from stackshot.service import handoff as handoff_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import runner as runner_svc
from stackshot.service import telling
from stackshot.core import store as _core_store
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": time.time() - 100 * 86400, "seen": {}, "reported": []}))
server._cfg.CFG.setdefault("model", {}).update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False)
ZONE = zoneinfo.ZoneInfo("Asia/Dubai"); H = 3600.0; DAY = 86400.0
T0 = float(int(time.time() // 60 * 60))                                   # the suite's clock, on a minute
local_str = lambda ep: dt.datetime.fromtimestamp(ep, ZONE).strftime("%Y-%m-%dT%H:%M")
day_of = lambda ep: dt.datetime.fromtimestamp(ep, ZONE).date()
def midnight(d): return dt.datetime(d.year, d.month, d.day, tzinfo=ZONE).timestamp()
frozen = SP.frozen

def put(i, status="open", **meta):
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}; base.update(meta)
    su = T0 - 10 * DAY
    with open(T / f"store/g/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i): return json.loads((T / f"store/g/{i}.json").read_text())
def mt(i): return raw(i)["metadata"]
def bytes_of(i): return (T / f"store/g/{i}.json").read_bytes()
def ns(i): return (T / f"store/g/{i}.json").stat().st_mtime_ns
def pair(i): return (mt(i).get("phase"), mt(i).get("waits_on"))
KEYS = ("phase", "waits_on")
def without(d): return {**d, "metadata": {k: v for k, v in d["metadata"].items() if k not in KEYS}}
def want(i, t):
    with frozen(t): return server._stamp_values(f"g{i}", server._load(f"g{i}"))
def sweep(t):
    with frozen(t): return server._phase_sweep()
def state_listing(): return sorted(str(p.relative_to(T / "state")) for p in (T / "state").rglob("*"))

# ---- fixtures: one item for each edge, a few that never move, and the cases of the earlier suites
D = day_of(T0) + dt.timedelta(days=3)                     # the day a dated step waits for
MID_D = midnight(D)
BASIS = {"text": "the contract renews on 2099-01-20", "wake": local_str(T0 + 3 * H), "by": BACK, "at": T0}
NEXT_FAR = "worker-b: check the build later and report back to the owner"
put(1, needs=[BACK], state="doing", hold=True, wake=local_str(T0 + 3 * H))                                                    # E1: waiting until the hour before the wake
put(2, needs=[BACK], state="doing", wake=local_str(T0 + 3 * H), wait_basis=BASIS, next=NEXT_FAR)                              # E2: the wake itself
put(3, needs=[BACK], state="doing", wake=local_str(MID_D + 12 * H), next=f"team-back: after {D.isoformat()} run the check")   # E3: midnight of the day
put(10, needs=[BACK], state="doing")
put(11, needs=["decision", BACK], state="your-call", ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date")
put(12, needs=[BACK], state="parked", hold=True, wake=local_str(T0 + 20 * DAY), cap_ok={"wake": local_str(T0 + 20 * DAY), "by": "the owner", "quote": "park it until then"})
put(13, needs=[BACK], wait_kind="relay", wait_event="Acme's reply", ask_by=day_of(T0 + 9 * DAY).isoformat())
put(14, needs=[BACK], state="verifying", proof="the run lands", end=day_of(T0 + 30 * DAY).isoformat())
put(15, needs=["external"], state="outside", party="Acme legal", chase=day_of(T0 + 5 * DAY).isoformat())                  # E5 (relay until an anchor is scoped to it)
put(16, needs=[BACK], state="doing", hold=True, wake=local_str(T0 + 90 * DAY))
put(17, needs=[BACK], state="your-step", step="Run the thing once", mover=OWN, next=f"{OWN}: run the thing once")
put(30, needs=[BACK], state="doing")                                                                                     # E4: the item that closes
put(31, needs=[BACK], after=["g30"])                                                                                     # E4: no stored state, waits after g30
put(40, status="completed", needs=[BACK], state="doing", outcome="done")
put(41, status="completed", needs=[BACK], state="doing", outcome="done", phase="waiting", waits_on="time")               # closed, a stale stamp on it
OPEN = [1, 2, 3, 10, 11, 12, 13, 14, 15, 16, 17, 30, 31]
b40, b41 = bytes_of(40), bytes_of(41)

first = sweep(T0)
check("0 the first sweep stamps every open fixture and nothing else, and the stored pair is the derived one", sorted(first) == sorted(f"g{i}" for i in OPEN) and all(pair(i) == (lambda p: (p[0] or None, p[1] or None))(want(i, T0)) for i in OPEN), first)
check("0 …the E1/E2/E3 items start waiting on a time, and a closed item is not touched", [pair(i) for i in (1, 2, 3)] == [("waiting", "time")] * 3 and bytes_of(40) == b40 and bytes_of(41) == b41, [pair(i) for i in (1, 2, 3)])
check("0 …a second sweep writes nothing", sweep(T0) == [], None)

# ---- 1. the clock edges
def edge(label, i, t_before, t_after, was, now_is):
    gid = f"g{i}"
    b, m = bytes_of(i), ns(i)
    check(f"{label}: just before the edge the stored pair is true and a sweep writes nothing", want(i, t_before) == (was[0], was[1] or "") and sweep(t_before) == [] and bytes_of(i) == b and ns(i) == m, (want(i, t_before), pair(i)))
    st = want(i, t_after)
    check(f"{label}: past the edge the derived pair is {now_is} and the stored one is stale", (st[0], st[1] or None) == now_is and pair(i) == was, (st, pair(i)))
    pre = raw(i)
    done = sweep(t_after)
    check(f"{label}: one sweep restamps exactly this item", done == [gid] and pair(i) == now_is, (done, pair(i)))
    check(f"{label}: …only the two keys changed (updated, written_by, activity, hand-off and every other field as they were)", without(raw(i)) == without(pre) and "written_by" not in raw(i) and "activity" not in raw(i), raw(i))
    b, m = bytes_of(i), ns(i)
    check(f"{label}: a second sweep writes nothing (bytes and mtime equal)", sweep(t_after) == [] and bytes_of(i) == b and ns(i) == m, None)

edge("1 E1 (the wake comes within dated_wait_min_hours: 2 h before it)", 1, T0 + 2 * H - 60, T0 + 2 * H + 60, ("waiting", "time"), ("alive", None))
edge("1 E2 (a wait_basis wake passes)", 2, T0 + 3 * H - 60, T0 + 3 * H + 60, ("waiting", "time"), ("alive", None))
edge("1 E3 (local midnight: the day a dated step waits for becomes today)", 3, MID_D - 60, MID_D + 60, ("waiting", "time"), ("alive", None))

# ---- 2. the edges no clock marks
TL = MID_D + 120                                                       # one clock for the rest: after every edge above, so the items above stay as they are
# E4: g30 closes while the old release stands down (switchover on, no fallback): only the sweep restamps g31
CFGM = server._cfg.CFG["model"]; CFGM.update(switchover=True, switchover_fallback=False)
try:
    d30 = raw(30); d30["status"] = "completed"; d30["metadata"]["outcome"] = "done"
    (T / "store/g/30.json").write_text(json.dumps(d30, ensure_ascii=False, indent=1))
    with frozen(TL):
        released = wakes_svc.release_after("g30", "done", "", "")
finally:
    CFGM.update(switchover=False); CFGM.pop("switchover_fallback", None)
check("2 E4: the item g31 waits after closed; the old release stood down, so g31 still stores waiting/item", released == [] and pair(31) == ("waiting", "item"), (released, pair(31)))
pre = raw(31); b30 = bytes_of(30); done = sweep(TL)
check("2 E4: the sweep restamps it alive, and g30 (closed) is left as it is", done == ["g31"] and pair(31) == ("alive", None) and without(raw(31)) == without(pre) and bytes_of(30) == b30, (done, pair(31), mt(30)))
# E5: an anchor scoped to g15 (state outside, no wait_kind): relay -> anchor, and back when it is taken off
check("2 E5: g15 stores waiting/relay", pair(15) == ("waiting", "relay"), pair(15))
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://example.com/x/1", "items": ["g15"], "added": T0, "by": "home-front"}]}))
pre = raw(15); done = sweep(TL)
check("2 E5: an anchor scoped to it changes the kind to anchor on the next sweep, nothing else", done == ["g15"] and pair(15) == ("waiting", "anchor") and without(raw(15)) == without(pre), (done, pair(15)))
(T / "store/anchors.json").write_text("{}")
done = sweep(TL)
check("2 E5: …and removing the anchor changes it back to relay", done == ["g15"] and pair(15) == ("waiting", "relay"), (done, pair(15)))
# E6: [waiting] dated_wait_min_hours (and a config reload)
put(50, needs=[BACK], state="doing", hold=True, wake=local_str(TL + 3 * H))
check("2 E6: a held item waking in 3 hours is waiting under the default of 1 hour", sweep(TL) == ["g50"] and pair(50) == ("waiting", "time") and sweep(TL) == [], pair(50))
(T / "stackshot.toml").write_text(mk_toml(tmp, min_hours=4), encoding="utf-8")
buf = io.StringIO()
with contextlib.redirect_stderr(buf), frozen(TL):
    server._on_hup()
check("2 E6: a reload with dated_wait_min_hours = 4 restamps the item alive at once (no minute to wait)", pair(50) == ("alive", None) and "phase sweep: g50 stamped waiting/time -> alive/-" in buf.getvalue(), (pair(50), buf.getvalue()[-400:]))
check("2 E6: …and the sweep that follows finds nothing", sweep(TL) == [], None)
(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
with contextlib.redirect_stderr(buf), frozen(TL):
    server._on_hup()
check("2 E6: …the reload that puts it back restamps it waiting", pair(50) == ("waiting", "time"), pair(50))
check("2 the start runs the sweep after the wake pass and before the runner starts", (lambda s: 0 < s.index("wake_pass()") < s.index("_phase_tick()") < s.index("_runner.start()"))(inspect.getsource(server._start_background)), None)

# ---- 3. no item lock unless something is stamped
res = {}
def worker():
    res["done"] = sweep(TL)
with writes.ITEM_LOCK:
    th = threading.Thread(target=worker, daemon=True); th.start(); th.join(10)
    check("3 a sweep with nothing to stamp finishes while another thread holds the item lock", not th.is_alive() and res.get("done") == [], res)
    d = raw(10); d["metadata"]["phase"] = "waiting"; d["metadata"]["waits_on"] = "time"
    (T / "store/g/10.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    th = threading.Thread(target=worker, daemon=True); th.start(); th.join(0.7)
    blocked = th.is_alive()
check("3 …a sweep with a difference waits for the lock (the stamp is made under it), then stamps", blocked and (th.join(10) or True) and not th.is_alive() and res["done"] == ["g10"] and pair(10) == ("alive", None), (blocked, res, pair(10)))

# ---- 4. a stamp is not an event on the item
put(60, needs=[BACK], state="doing", hold=True, wake=local_str(TL + 3 * H)); sweep(TL)
d = raw(60); d["metadata"]["phase"] = "alive"; d["metadata"].pop("waits_on")
(T / "store/g/60.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))                     # stale: the fields read waiting
calls = []
real = {(m, k): getattr(m, k) for m, k in ((server, "_foryou_on_save"), (server, "_landed_on_save"), (handoff_svc, "handoff_on_save"), (telling, "tell_woken"), (telling, "push_noted"), (wakes_svc, "wake_tell"))}
real_gh = (server._gh.enabled, server._gh.on_change); real_touch = server._search.touch; real_save = writes.save
def spy(name):
    def f(*a, **k): calls.append(name)
    return f
for m, k in real: setattr(m, k, spy(k))
server._gh.enabled = lambda: True; server._gh.on_change = spy("gh.on_change"); server._search.touch = spy("search.touch"); writes.save = spy("save")
state0 = state_listing()
try:
    done = sweep(TL)
finally:
    for (m, k), v in real.items(): setattr(m, k, v)
    server._gh.enabled, server._gh.on_change = real_gh; server._search.touch = real_touch; writes.save = real_save
check("4 a sweep that stamps calls no save, no GitHub job, no notice, no For you or landed row, no hand-off, no search touch", done == ["g60"] and calls == [], (done, calls))
check("4 …no writer is recorded, no clock moves, the state folder is as it was, no temporary file is left", "written_by" not in raw(60) and raw(60)["updated"] == T0 - 10 * DAY and state_listing() == state0 and not list((T / "store/g").glob(".*")), raw(60))
from stackshot.web import render as root_render
from stackshot.web.ui import render as ui_render
STORE_DIR = str(T / "store")
gitc = lambda *a: subprocess.run(["git", "-C", STORE_DIR, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
def distinct(i):
    d = raw(i); d["description"] = "\n".join(f"- line {n} of item {i}: " + "x%d" % ((n * 7919 + i * 104729) % 100003) * 3 for n in range(12)); d["subject"] = f"[home] history item {i} " + "y%d" % (i * 31337)
    (T / f"store/g/{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
def events(bd, gid): return [k for _t, k, _h in bd.item_events(next(r for r in bd.rows if r["gid"] == gid))[0]]
put(61, needs=[BACK], state="doing", hold=True, wake=local_str(TL + 3 * H)); distinct(61); sweep(TL)
gitc("init", "-q"); gitc("add", "-A"); gitc("commit", "-q", "-m", "older revisions")
done = sweep(TL + 2 * H + 60)                                                                         # g61's wake is within the hour now, and g60's, g50's, g1's own
check("4 a sweep at the edge restamps the item with a stamp-only revision", "g61" in done and pair(61) == ("alive", None), (done, pair(61)))
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    kinds = events(mod_.Board(STORE_DIR), "g61")
    check(f"4 {label}: …and the revision adds no History line", kinds == ["created"], kinds)
shutil.rmtree(T / "store/.git")
TL = TL + 2 * H + 60                                                                                 # the clock the store stands true at now

# ---- 5. closed items and unreadable files
(T / "store/g/98.json").write_text("{ not json")
check("5 a closed item (a stale stamp on it too) is byte-identical after every sweep, and a file that does not read is skipped without a crash", sweep(TL) == [] and bytes_of(40) == b40 and bytes_of(41) == b41, None)
(T / "store/g/98.json").unlink()

# ---- 6. a writer between the read and the replace
put(70, needs=[BACK], state="doing"); sweep(TL)
d = raw(70); d["metadata"]["hold"] = True; d["metadata"]["wake"] = local_str(TL + 5 * DAY)                      # a session put it on hold: the fields now read waiting, the stored pair says alive
(T / "store/g/70.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
real_commit = server._stamp_commit
def racing(p, tmpf, h0):
    x = json.loads(p.read_text()); x["metadata"]["next"] = "team-back: a session wrote this meanwhile"; x["updated"] += 5
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1)); return real_commit(p, tmpf, h0)
moved0 = server._PHASE_SWEEP["moved"]; server._stamp_commit = racing
try:
    done = sweep(TL)
finally:
    server._stamp_commit = real_commit
check("6 a write between the read and the replace: nothing stamped, `moved` counted, the session's change stands, no temporary file left",
      done == [] and server._PHASE_SWEEP["moved"] == moved0 + 1 and mt(70)["next"] == "team-back: a session wrote this meanwhile" and pair(70) == ("alive", None) and not list((T / "store/g").glob(".*")), (done, mt(70)))
done = sweep(TL)
check("6 …the next sweep stamps it, and the session's change survives", done == ["g70"] and pair(70) == ("waiting", "time") and mt(70)["next"] == "team-back: a session wrote this meanwhile", (done, mt(70)))

# ---- 7. the standby copy
d = raw(10); d["metadata"]["hold"] = True; d["metadata"]["wake"] = local_str(TL + 5 * DAY); (T / "store/g/10.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
b, runs0 = bytes_of(10), server._PHASE_SWEEP["runs"]
server._ro._reload_for_test(True)
try:
    got = (sweep(TL), server._phase_tick(), server._stamp_one("g10")["action"])
finally:
    server._ro._reload_for_test(False)
check("7 STACKSHOT_READ_ONLY: the sweep and the tick return nothing, count no run, and write nothing (the stamp itself is refused)", got == ([], [], "refused") and bytes_of(10) == b and server._PHASE_SWEEP["runs"] == runs0, got)
check("7 …off the standby the same sweep stamps it", sweep(TL) == ["g10"] and pair(10) == ("waiting", "time"), pair(10))

# ---- 8. the tick and the status
ticks = runner_svc.ticks(); names = [t.name for t in ticks]
tk = ticks[names.index("phase_sweep")]
check("8 the tick is in the minute set right after the anchor pass, in the settle group, paced, skipped while the board is held", names[names.index("anchor_pass") + 1] == "phase_sweep" and (tk.group, tk.pace, tk.board) == ("settle", "paced", True), names)
d = raw(10); d["metadata"].pop("hold"); d["metadata"].pop("wake")
(T / "store/g/10.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
held = [True]; clk = [100000.0]
rn = R.Runner([tk], holding=lambda: held[0], clock=lambda: clk[0]); rn.run_round()
st = rn.status()["ticks"][0]; b = bytes_of(10)
check("8 while the migration holds the board the tick is skipped and writes nothing", st["skipped"] == 1 and st["runs"] == 0 and bytes_of(10) == b, st)
held[0] = False; pubs = []; server._publish = _wt_anchors._publish = _wt_route._publish = lambda: pubs.append(1)
try:
    with frozen(TL):
        clk[0] += 61; rn.run_round()
        clk[0] += 61; rn.run_round()
finally:
    server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
check("8 …released, the first round stamps it and publishes once; the second finds nothing and publishes nothing", pair(10) == ("alive", None) and pubs == [1], (pair(10), pubs))
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as tc:
    js = tc.get("/audit/status").json()
ps = js.get("phase_sweep") or {}
check("8 GET /audit/status carries phase_sweep (runs, swept, stamped, moved, refused, disagreements, last_run, last_stamped, last_ms, unstamped_reads) and the audit's own keys and runner as before",
      set(ps) == {"runs", "swept", "stamped", "moved", "refused", "disagreements", "last_run", "last_stamped", "last_ms", "unstamped_reads"} and "runner" in js and "enabled" in js, js.keys())
check("8 …its numbers are the sweep's own: runs and stamps counted, the last run's open items, and a difference seen for every stamp or move",
      ps["runs"] >= 10 and ps["swept"] == len([p for p in (T / "store/g").glob("*.json") if json.loads(p.read_text())["status"] == "open"]) and ps["stamped"] >= 16
      and ps["disagreements"] >= ps["stamped"] + ps["moved"] and isinstance(ps["last_run"], float) and isinstance(ps["last_stamped"], float), ps)

# ---- 9. the same store at several clocks: one sweep makes the stored pair the derived one, the display is byte-equal
put(80, needs=[BACK], state="doing", hold=True, wake=local_str(TL + 90 * 60))                                                    # a held wake that comes within the hour before the +30 min clock
put(81, needs=[BACK], state="doing", hold=True, wake=local_str(TL + 4 * H))                                                      # …before the +6 h clock
put(82, needs=[BACK], state="doing", wake=local_str(TL + 2 * DAY), wait_basis={**BASIS, "wake": local_str(TL + 2 * DAY)}, next=NEXT_FAR)  # a basis wake that passes before the +3 days clock
tomorrow = day_of(TL) + dt.timedelta(days=1)
put(83, needs=[BACK], state="doing", wake=local_str(midnight(tomorrow) + 12 * H), next=f"team-back: after {tomorrow.isoformat()} run the check")   # a dated step whose day starts at the next local midnight
check("9 the four items for the clocks start waiting on a time", sweep(TL) == ["g80", "g81", "g82", "g83"] and [pair(i) for i in (80, 81, 82, 83)] == [("waiting", "time")] * 4, [pair(i) for i in (80, 81, 82, 83)])
@contextlib.contextmanager
def fields_only():
    """Every reader works the decision out from the fields alone (model.view patched to the writer's reading): what the board showed before the pair was stored."""
    real = server._model.view
    server._model.view = lambda item, mod, now=None, after_open=None, check=True: server._model._shown(item, mod, now, after_open)
    try:
        yield
    finally:
        server._model.view = real
def shift_proof(label, src_store, base, anchors_file=None):
    nxt_mid = midnight(day_of(base + 60) + dt.timedelta(days=1)) + 60
    shifts = (("+30 min", base + 1800), ("+1 h", base + H), ("+6 h", base + 6 * H), ("next local midnight", nxt_mid), ("+3 days", base + 3 * DAY), ("+40 days", base + 40 * DAY))
    stamped_total = 0
    for name, t in shifts:
        R_ = pathlib.Path(_scratch.mkdtemp(prefix="phasesweep-shift-"))
        real_store, real_anc = _core_store.STORE, server._anc.FILE
        try:
            shutil.copytree(src_store, R_ / "store", ignore=shutil.ignore_patterns(".git", "*.tmp", ".*"))
            _core_store.STORE = R_ / "store"; server._anc.FILE = R_ / "store/anchors.json"
            items0 = SP.load_dir(R_ / "store")
            opens = sorted((g for g, it in items0.items() if it.get("status") == "open"), key=SP.num)
            with frozen(t):
                with fields_only():
                    d0 = {g: SP.display_of(server, items0[g], g) for g in opens}      # what the fields give at this clock, before the sweep
                first_ = server._phase_sweep()
                items1 = SP.load_dir(R_ / "store")
                d1 = {g: SP.display_of(server, items1[g], g) for g in opens}
                derived = {g: server._stamp_values(g, server._load(g)) for g in opens}
            stamped_total += len(first_)
            check(f"9 {label} {name}: after one sweep every open item ({len(opens)}) stores the pair derived now", all((items1[g]["metadata"].get("phase") or "", items1[g]["metadata"].get("waits_on") or "") == derived[g] for g in opens), [g for g in opens if (items1[g]["metadata"].get("phase") or "", items1[g]["metadata"].get("waits_on") or "") != derived[g]][:5])
            check(f"9 {label} {name}: …only the two keys changed, on the items stamped alone, and no closed item was touched", SP.files_outside(items0, items1) == [] and all(items0[g] == items1[g] for g in items0 if g not in opens) and sorted(first_) == sorted(g for g in opens if SP.pair(items0[g]) != SP.pair(items1[g])), (SP.files_outside(items0, items1)[:5], first_[:5]))
            check(f"9 {label} {name}: …the displayed output (state, kind, list word, model line, get's text, the brief's block) after it is byte-equal to what the fields gave before it", d0 == d1, [g for g in opens if d0[g] != d1[g]][:5])
            ms = {p: p.stat().st_mtime_ns for p in (R_ / "store").rglob("*.json")}
            with frozen(t):
                again = server._phase_sweep()
            check(f"9 {label} {name}: …and a second sweep writes nothing (mtimes equal)", again == [] and ms == {p: p.stat().st_mtime_ns for p in (R_ / "store").rglob("*.json")}, again)
        finally:
            _core_store.STORE, server._anc.FILE = real_store, real_anc
            shutil.rmtree(R_, ignore_errors=True)
    return stamped_total

n_fix = shift_proof("fixture", T / "store", TL)
print(f"fixture shifts: {n_fix} stamps over six clocks")
check("9 the fixture clocks crossed edges: at least the four items above (and g70 at +40 days) were restamped", n_fix >= 5, n_fix)
src = pathlib.Path(os.environ.get("PHASE_REPLAY_STORE") or "/nonexistent").expanduser()
if src.is_dir() and any(q.is_dir() and len(q.name) == 1 for q in src.iterdir()):
    n_live = shift_proof("live copy", src, time.time())
    print(f"live copy shifts: {n_live} stamps over six clocks")
else:
    print("replay: skipped (PHASE_REPLAY_STORE names no store here)")

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: phase sweep scenario, {len(ran)} checks")
