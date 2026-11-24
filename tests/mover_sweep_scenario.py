"""Scenario test for the mover pass as a sweep: over a grid of stored forms (the old picker key, mover and a then, each absent, an agent, blank, the word none, a session no pane runs, the owner; across every
phase and kind of wait, needs on a session, the owner's decision, an outside party or nothing, and a due hold), the real route moves the store and the ticks (wake_pass, which runs the watchers) are
simulated on the store before and after, at now + 1 minute, + 3 days and + 20 days. What is checked is what the pass is for, never a form at a time:

  1  nothing the tick before the pass acted on is left unacted after it (a wait lost), but for an item whose stored then stood in for a picker (listed by the route as a stand-in)
  2  the tick after the pass acts on nothing the tick before it did not (the pass wakes nothing), but for those stand-ins
  4  the route's lists are consistent: no item is refused, a kept item is byte for byte untouched, every item read before and after reads the same (phase, kind, picker, then, needs, end date) but a stand-in's picker
  5  an item both ticks act on gets the same treatment (a notice stays a notice, a release a release, the kind kept alike), but a stand-in
  6  a second pass moves nothing

An item acted on is one whose file the tick rewrote or one a tick message names. Deterministic (the whole grid, no sample) and bounded.

    tests/run-suite mover_sweep        -> exit 0 / 1"""
import argparse, contextlib, copy, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _midnight
tmp = _scratch.mkdtemp(prefix="moversweep-"); T = pathlib.Path(tmp)


def mk_toml(root):
    """A config whose every path is inside `root`, with no GitHub mirror and no commit."""
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
for d in ("store/a", "store/g", "fleet/a", "state/anchors", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
_midnight.wait_out("Asia/Dubai")      # a local midnight inside the run would move the "today" and "tomorrow" the checks read: start on the far side of one that is close
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
from stackshot.web import server, wiring; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import watchers as WK_, waiting as W, until_pass as UP, until_write as UW, stall as STALL, mover_pass as MP; from stackshot.model import model as _model; from stackshot.tools import until_migrate as UM; from stackshot.tools import mover_migrate as MM; from stackshot.tools import stamp_phase as SP
from stackshot.service import stamp as stamp_svc
from stackshot.service import retire_passes as retire_svc
HOST = stamp_svc.PassHost(server, stamp_svc, retire_svc, wiring.PASS_NAMES)   # the `S` of until_pass: the server module, then the stamp and retire modules that own the names it reads
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import item_read as _item_read
import stackshot.core.config as _cfg_
from stackshot.service import store as _service_store
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.service import answer_handover as _answer_handover
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = _cfg_.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))

def put(i, status="open", letter="g", description=DESC, **meta):
    """An item file as the older writer left it: the wait in wake, ask_by and hold."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    with open(T / f"store/{letter}/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": description, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="g"): return raw(i, letter)["metadata"]
def bytes_of(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_bytes()
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def same_values(a, b): return {k: json.loads(v) for k, v in a.items()} == {k: json.loads(v) for k, v in b.items()}
BOARD = "board" + "#"      # a board id is built at run time, never written as a literal
WAITKEYS = ("until", "wait_kind", "wake", "ask_by", "hold", "hold_set")
wk = lambda m: {k: m.get(k) for k in WAITKEYS if k in m}
sent = []
telling.tell_woken = lambda gid, owner, note, tag="wake": sent.append((gid, owner, note))


import datetime as _dtm, itertools, collections
CFGM["migration"] = True
call = lambda **body: _rt_client._client_post("box-a", "migrate", {"sender": SENDER, **body})
put(31, needs=[BACK])
past, soon, later = day(-30), day(2), day(10)
BK = {"hold_set": {"at": now0 - DAY, "by": BACK}}
WASX = {"wait_kind": "relay", "wait_event": "the vendor's reply", "until": day(6), "then": BACK, "needs": ["external"]}
PHASES = [
    ("alive on a session",           {"needs": [BACK]}),
    ("alive on a decision",          {"needs": ["decision"]}),
    ("alive on nothing",             {"needs": []}),
    ("time wait on a session",       {"needs": [BACK], "wait_kind": "time", "until": soon}),
    ("time wait on nothing",         {"needs": [], "wait_kind": "time", "until": soon}),
    ("time wait, external",          {"needs": ["external"], "wait_kind": "time", "until": soon}),
    ("time wait on a decision",      {"needs": ["decision"], "wait_kind": "time", "until": soon}),
    ("relay",                        {"needs": ["external"], "wait_kind": "relay", "wait_event": "the vendor's reply", "until": later}),
    ("item wait",                    {"needs": [BACK], "wait_kind": "item", "after": ["g31"]}),
    ("anchor wait",                  {"needs": [BACK], "wait_kind": "anchor", "wait_anchor": "https://example.com/x"}),
    ("event wait",                   {"needs": [BACK], "wait_kind": "event", "wait_event": "box_online box-b"}),
    ("until with no kind",           {"needs": [BACK], "until": soon}),
    ("until with no kind, external", {"needs": ["external"], "until": soon}),
    ("due hold",                     {"needs": [BACK], "hold": True, "wake": past, "wait_kind": "time", "state": "parked", **BK}),
    ("due hold on nothing",          {"needs": [], "hold": True, "wake": past, "wait_kind": "time", "state": "parked", **BK}),
]
LEGACY = [("-", None), ("agent", BACK), ("other agent", "home-other"), ("blank", ""), ("none", "none")]
MOVERS = [("-", None), ("agent", BACK), ("other agent", "home-other"), ("owner", OWN)]
THENS = [("-", None), ("live", "home-other"), ("the mover's own", BACK), ("no session", "home-dead"), ("owner", OWN)]
GID0 = 3000
desc, IDS, combos, phases_seen = {}, [], set(), set()
n_ = 0
for (pn, pm), (ln, lv), (mn, mv), (tn, tv) in itertools.product(PHASES, LEGACY, MOVERS, THENS):
    meta = dict(pm)
    if lv is not None: meta["post_wake_mover"] = lv
    if mv is not None: meta["mover"] = mv
    if tv is not None: meta["then"] = tv
    i = GID0 + n_; n_ += 1
    put(i, **meta); desc[f"g{i}"] = f"{pn} | old key {ln} | mover {mn} | then {tn}"; IDS.append(f"g{i}")
    combos.add((pn, ln, mn, tn))
SNAPS = 0
for ln, lv in LEGACY:                                  # the snapshot of a turned wait, with each form of the old key in it, with a then and with a mover
    for wn, extra in (("with a then", {}), ("with a mover", {"mover": "home-other"})):
        was = dict(WASX, **extra)
        if lv is not None: was["post_wake_mover"] = lv
        i = GID0 + n_; n_ += 1
        put(i, needs=["decision"], watch={"asked": "relay", "was": was, "at": now0 - DAY}); desc[f"g{i}"] = f"turned wait, snapshot old key {ln} {wn}"; IDS.append(f"g{i}"); SNAPS += 1
S0 = snapshot()

def restore(snap):
    for p in (T / "store/g").glob("*.json"):
        if p.name not in snap:
            p.unlink()
    for name, data in snap.items():
        q = T / "store/g" / name
        if not q.exists() or q.read_bytes() != data:
            q.write_bytes(data)

IGNORED = {"wake", "until", "ask_by", "hold", "hold_set", "wait_kind", "stall", "history", "mover", "post_wake_mover", "then", "watch"}
def sig_of(g, b, a, told):
    """What a tick did to one item: whether it was told about, and what it reads as after (phase, owner, the stored picker, a kind kept when it had no hold, a hold kept) with every other key the tick changed."""
    mb, ma = (json.loads(b) if b else {}), json.loads(a)
    m0, m1 = mb.get("metadata") or {}, ma.get("metadata") or {}
    changed = tuple(sorted(k for k in set(m0) | set(m1) if k not in IGNORED and m0.get(k) != m1.get(k)))
    return (bool(told), ma.get("status"), m1.get("owner"), _model.stored_picker(m1) or "", None if m0.get("hold") else bool(m1.get("wait_kind")), bool(m1.get("hold")), bool(m1.get("watch")), changed)

def tick(epoch):
    """{id: what the tick did} for the ids a tick at `epoch` acted on (a file rewritten, or a message that names the item); the store is put back after."""
    before = snapshot(); sent.clear()
    wakes_svc.wake_pass(_dtm.datetime.fromtimestamp(epoch, _cfg_.tz()))
    after = snapshot()
    notes = {}
    for entry in sent:
        text = str(entry)
        for g in IDS:
            if re.search(rf"(?<![0-9])(g|item |{re.escape('board' + chr(35))}){g[1:]}(?![0-9])", text):
                notes.setdefault(g, []).append(text)
    acted = {f"g{pn}" for pn in (int(k[:-5]) for k in after) if after.get(f"{pn}.json") != before.get(f"{pn}.json")} | set(notes)
    out = {g: sig_of(g, before.get(f"{g[1:]}.json"), after[f"{g[1:]}.json"], g in notes) for g in acted & set(IDS)}
    restore(before)
    return out

reading = lambda snap, g: MP.reading(HOST, g, json.loads(snap[f"{g[1:]}.json"]))
reads0 = {g: reading(S0, g) for g in IDS}
res = {}
for k in range(0, len(IDS), 40):
    st_, d_ = call(op="mover", items=IDS[k:k + 40])
    assert st_ == 200, (st_, d_)
    for g, r in zip(IDS[k:k + 40], d_["results"]):
        res[g] = r
S1 = snapshot()
reads1 = {g: reading(S1, g) for g in IDS}
counts = collections.Counter(r["action"] for r in res.values())
standin = {g for g, r in res.items() if r.get("standin")}
forms = collections.Counter(r.get("form", "") for r in res.values() if r["action"] == "set")
carrying = [g for g in IDS if "old key -" not in desc[g] or "then -" not in desc[g] or "turned" in desc[g]]
print("INFO sweep:", len(IDS), "items", dict(counts), "stand-ins", len(standin), "distinct forms written", len(forms))
for f, n in sorted(forms.items()): print("INFO   form:", f, n)
print("INFO live-shaped forms covered:", len(combos), "combinations of phase, old key, mover and then +", SNAPS, "snapshots of a turned wait; items carrying an old key, a then or a snapshot:", len(carrying), "of", len(IDS))
check("4 the sweep ran on a grid with every action in it (rewritten, left, listed) and some stand-ins", all(counts[a] for a in ("set", "same", "kept")) and standin, dict(counts))
check("4 no item of the grid is refused (the reading is the same for every form the pass writes, but a stand-in's picker)", not counts["refused"], [f"{g} [{desc[g]}] {r['why']}" for g, r in res.items() if r["action"] == "refused"][:8])
untouched = [g for g, r in res.items() if r["action"] in ("kept", "same") and S1[f"{g[1:]}.json"] != S0[f"{g[1:]}.json"]]
check("4 a kept or unchanged item is byte for byte untouched", not untouched, untouched[:8])
moved = [g for g, r in res.items() if r["action"] == "set"]
check("4 no written item keeps the old key outside a kept form", all("post_wake_mover" not in json.loads(S1[f"{g[1:]}.json"])["metadata"] for g in moved), None)
differ = {g: MP.same(reads0[g], reads1[g], res[g].get("standin", "")) for g in moved}
check("4 every written item reads the same before and after (phase, kind, then, needs, end date, picker but for a stand-in's)", not any(differ.values()), [f"{g} [{desc[g]}] {v}" for g, v in differ.items() if v][:8])
st_, d_ = call(op="mover", items=IDS[:40])
check("6 a second pass over the same items moves nothing and leaves every file as it is", st_ == 200 and all(r["action"] in ("same", "kept") for r in d_["results"]) and snapshot() == S1, [r["action"] for r in d_["results"]][:8])
CASEWORDS = lambda gs: [f"{g} [{desc[g]}]" for g in sorted(gs)[:12]]
epoch1, epoch2, epoch3 = now0 + 60, now0 + 3 * DAY, now0 + 20 * DAY
acts = {}
for label, ep in (("+1 minute", epoch1), ("+3 days", epoch2), ("+20 days", epoch3)):
    restore(S0); pre_sig = tick(ep); pre = set(pre_sig)
    restore(S1); post_sig = tick(ep); post = set(post_sig)
    acts[label] = (pre, post)
    lost = pre - post - standin
    check(f"1 {label}: nothing the tick before the pass acted on is left unacted after it, but a stand-in ({len(lost)} lost of {len(pre)})", not lost, CASEWORDS(lost))
    extra = post - pre - standin
    check(f"2 {label}: the tick after the pass acts on nothing the tick before did not, but a stand-in ({len(extra)} new of {len(post)})", not extra, CASEWORDS(extra))
    diff = {g for g in (pre & post) - standin if pre_sig[g] != post_sig[g]}
    check(f"5 {label}: an item both ticks act on gets the same treatment ({len(diff)} differ)", not diff, [f"{g} [{desc[g]}] {pre_sig[g]} -> {post_sig[g]}" for g in sorted(diff)[:8]])
restore(S1)
check("sweep: the ticks acted on something at every time", all(acts[l][0] for l in acts), {l: (len(a), len(b)) for l, (a, b) in acts.items()})
CFGM["migration"] = False
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(f"ok: mover sweep scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
