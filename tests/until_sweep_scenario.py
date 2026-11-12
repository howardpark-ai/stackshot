"""Scenario test for the until pass as a sweep: over a grid of old-field combinations (wake and ask_by over past and future dates, every kind of wait with a valid and an invalid target, an after link
open or closed, a hold with or without a pane recycle, needs a session or an outside party, a reason), the real route migrates the store and the ticks (_wake_pass, which runs the watchers) are simulated on
the store before and after, at now + 1 minute, + 3 days and + 20 days. What is checked is what the pass is for, never a form at a time:

  1  nothing the tick before the migration acted on is left unacted after it (a wait lost)
  2  the tick one minute after the migration acts on nothing the tick before it did not act on (the pass wakes nothing)
  3  at later times the only items the tick newly acts on are the ones the pass listed as newly watched, each on or after its own date
  4  the route's lists are consistent: a listed due item is byte for byte untouched, a newly watched date is in the future

An item acted on is one whose file the tick rewrote or one a tick message names. Deterministic (a fixed sample of the grid) and bounded.

    tests/run-suite until_sweep        -> exit 0 / 1"""
import argparse, contextlib, copy, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="untilsweep-"); T = pathlib.Path(tmp)


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
from stackshot.web import server; from stackshot.waits import waiting as W, until_pass as UP, until_write as UW, stall as STALL; from stackshot.model import model as _model; from stackshot.tools import until_migrate as UM; from stackshot.tools import stamp_phase as SP
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
server._front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFGM = server._cfg.CFG.setdefault("model", {})
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
server._tell_woken = lambda gid, owner, note, tag="wake": sent.append((gid, owner, note))
server._tell = lambda *a, **k: sent.append(("tell", a))


import datetime as _dtm, itertools, random
CFGM["migration"] = True
call = lambda **body: server._client_post("box-a", "migrate", {"sender": SENDER, **body})
put(31, needs=[BACK]); put(32, status="completed", needs=[BACK], outcome="done")
DATES = {"past": day(-30), "soon": day(2), "later": day(10), "soon, spaced": day(2) + "  09:30", "later, spaced": day(10) + "  09:30"}      # a hand-edited store can hold a date with a double space inside it: the old readers took it for no date
KINDS = [("", {}), ("time", {"wait_kind": "time"}), ("item", {"wait_kind": "item"}), ("relay", {"wait_kind": "relay", "wait_event": "the vendor's reply"}),
         ("anchor", {"wait_kind": "anchor", "wait_anchor": "https://example.com/x"}), ("anchor, no target", {"wait_kind": "anchor"}),
         ("event", {"wait_kind": "event", "wait_event": "box_online box-b"}), ("event, bogus", {"wait_kind": "event", "wait_event": "bogus"})]
AFTERS = [("", {}), ("open", {"after": ["g31"]}), ("closed", {"after": ["g32"]})]
HOLDS = [("", {}), ("hold", {"hold": True, "hold_set": {"at": now0 - DAY, "by": BACK}}), ("hold+recycle", {"hold": True, "hold_set": {"at": now0 - DAY, "by": BACK}, "recycle": {"at": now0}})]
NEEDS = [("back", {"needs": [BACK]}), ("external", {"needs": ["external"], "post_wake_mover": BACK})]
BASES = [("", False), ("basis", True)]
PLAIN = ("past", "soon", "later")
grid, spaced_grid = [], []
for w, a_, k, af, h, n, b in itertools.product([None, *DATES], [None, *DATES], KINDS, AFTERS, HOLDS, NEEDS, BASES):
    if (w is None and a_ is None) or (b[1] and w is None):
        continue
    (grid if w in (None, *PLAIN) and a_ in (None, *PLAIN) else spaced_grid).append((w, a_, k, af, h, n, b))
random.Random(20261112).shuffle(grid)
random.Random(20261113).shuffle(spaced_grid)
SAMPLE = 700
chosen = grid[:SAMPLE]
for axis in range(7):          # the sample keeps every value of every axis (a fixed seed; nothing is left to chance)
    seen = {repr(c[axis]) for c in chosen}
    for c in grid[SAMPLE:]:
        if repr(c[axis]) not in seen:
            chosen.append(c); seen.add(repr(c[axis]))
chosen += spaced_grid[:150]        # and a smaller sample with a date that has a space inside it
GID0 = 3000
desc = {}
for n_, (w, a_, k, af, h, n, b) in enumerate(chosen):
    i = GID0 + n_
    meta = {**k[1], **af[1], **h[1], **n[1]}
    if w: meta["wake"] = DATES[w]
    if a_: meta["ask_by"] = DATES[a_]
    if b[1]: meta["wait_basis"] = {"text": "the vendor ships on the date", "wake": DATES[w].split("  ")[0], "by": BACK, "at": now0}
    put(i, **meta)
    desc[f"g{i}"] = f"wake={w} ask_by={a_} kind={k[0]!r} after={af[0]!r} hold={h[0]!r} needs={n[0]} basis={b[0]!r}"
IDS = sorted(desc, key=lambda g: int(g[1:]))
S0 = snapshot()

def restore(snap):
    for p in (T / "store/g").glob("*.json"):
        if p.name not in snap:
            p.unlink()
    for name, data in snap.items():
        q = T / "store/g" / name
        if not q.exists() or q.read_bytes() != data:
            q.write_bytes(data)

IGNORED = {"wake", "until", "ask_by", "hold", "hold_set", "wait_kind", "stall", "history"}
def sig_of(g, b, a, told):
    """What a tick did to one item: whether it was told about, and what it reads as after (phase, owner, mover, a kind kept when it had no hold, a hold kept) with every other key the tick changed; the old
    date keys are left out (the migration moves them). A notice leaves the kind and the wait, a release drops them and hands the item on: these tell the two apart."""
    mb, ma = (json.loads(b) if b else {}), json.loads(a)
    m0, m1 = mb.get("metadata") or {}, ma.get("metadata") or {}
    changed = tuple(sorted(k for k in set(m0) | set(m1) if k not in IGNORED and m0.get(k) != m1.get(k)))
    return (bool(told), ma.get("status"), m1.get("owner"), m1.get("mover"), None if m0.get("hold") else bool(m1.get("wait_kind")), bool(m1.get("hold")), changed)

def tick(epoch):
    """{id: what the tick did} for the ids a tick at `epoch` acted on (a file rewritten, or a message that names the item); the store is put back after."""
    before = snapshot(); sent.clear()
    server._wake_pass(_dtm.datetime.fromtimestamp(epoch, server._cfg.tz()))
    after = snapshot()
    notes = {}
    for entry in sent:
        text = str(entry)
        for g in IDS:
            if re.search(rf"(?<![0-9])(g|item |board#|{re.escape('board' + chr(35))}){g[1:]}(?![0-9])", text):
                notes.setdefault(g, []).append(text)
    acted = {f"g{pn}" for pn in (int(k[:-5]) for k in after) if after.get(f"{pn}.json") != before.get(f"{pn}.json")} | set(notes)
    out = {g: sig_of(g, before.get(f"{g[1:]}.json"), after[f"{g[1:]}.json"], g in notes) for g in acted & set(IDS)}
    restore(before)
    return out

res = {}
for k in range(0, len(IDS), 40):
    st_, d_ = call(op="until", items=IDS[k:k + 40])
    assert st_ == 200, (st_, d_)
    for g, r in zip(IDS[k:k + 40], d_["results"]):
        res[g] = r
S1 = snapshot()
newly = {g: r["newly"] for g, r in res.items() if r.get("newly") and r["action"] == "set"}
due = {g for g, r in res.items() if r.get("due")}
counts = {a: sum(1 for r in res.values() if r["action"] == a) for a in ("set", "same", "kept", "refused", "moved")}
print("INFO sweep:", len(IDS), "items", counts, "newly", len(newly), "due", len(due))
check("4 the sweep ran on a grid with every action in it (rewritten, left, listed, refused) and some newly watched and some due items", all(counts[a] for a in ("set", "same", "kept", "refused")) and newly and due, counts)
check("4 a due item is left byte for byte, and a newly watched date is in the future", all(S1[f"{g[1:]}.json"] == S0[f"{g[1:]}.json"] for g in due) and all(_dtm.datetime.fromisoformat(d.replace(" ", "T")[:16] if "T" in d else d).date() >= _dtm.date.today() for d in newly.values()), None)
CASEWORDS = lambda gs: [f"{g} [{desc[g]}]" for g in sorted(gs)[:12]]
epoch1, epoch2, epoch3 = now0 + 60, now0 + 3 * DAY, now0 + 20 * DAY
acts = {}
for label, ep in (("+1 minute", epoch1), ("+3 days", epoch2), ("+20 days", epoch3)):
    restore(S0); pre_sig = tick(ep); pre = set(pre_sig)
    restore(S1); post_sig = tick(ep); post = set(post_sig)
    acts[label] = (pre, post)
    lost = pre - post
    check(f"1 {label}: nothing the tick before the migration acted on is left unacted after it ({len(lost)} lost of {len(pre)})", not lost, CASEWORDS(lost))
    extra = post - pre
    if label == "+1 minute":
        check(f"2 {label}: the tick after the migration acts on nothing the tick before did not ({len(extra)} new of {len(post)})", not extra, CASEWORDS(extra))
    else:
        unlisted = {g for g in extra if g not in newly or _dtm.datetime.fromtimestamp(ep, server._cfg.tz()).date() < _dtm.date.fromisoformat(newly[g][:10])}
        check(f"3 {label}: the only items the tick newly acts on are the listed newly watched ones, on or after their own date ({len(extra)} new, {len(unlisted)} unlisted)", not unlisted, CASEWORDS(unlisted))
    differ = {g for g in pre & post if not json.loads(S0[f"{g[1:]}.json"])["metadata"].get("hold") and pre_sig[g] != post_sig[g] and not (g in newly and _dtm.datetime.fromtimestamp(ep, server._cfg.tz()).date() >= _dtm.date.fromisoformat(newly[g][:10]))}
    check(f"5 {label}: an item with no hold that both ticks act on gets the same treatment (a notice stays a notice, a release a release, the kind kept alike; a hold's release is checked by 1-3) unless it is listed as newly watched ({len(differ)} differ)", not differ, [f"{g} [{desc[g]}] {pre_sig[g]} -> {post_sig[g]}" for g in sorted(differ)[:8]])

# ---- the classes by name: what the old code read is migrated and unlisted; what it did not is left (past) or listed (future)
def route(i, **meta):
    put(i, **meta); st_, d_ = call(op="until", items=[f"g{i}"], dry=True)
    return d_["results"][0]
bk = {"hold_set": {"at": now0 - DAY, "by": BACK}}
past, future = DATES["past"], DATES["later"]
rows = {
    "relay, past ask_by":                   (route(5001, needs=["external"], wait_kind="relay", wait_event="the vendor's reply", ask_by=past), "would_set", "", False),
    "item wait on an open after, past ask_by": (route(5002, needs=[BACK], after=["g31"], wait_kind="item", ask_by=past), "would_set", "", False),
    "anchor with its target, past ask_by":  (route(5003, needs=[BACK], wait_kind="anchor", wait_anchor="https://example.com/x", ask_by=past), "would_set", "", False),
    "event with a valid phrase, past ask_by": (route(5004, needs=[BACK], wait_kind="event", wait_event="box_online box-b", ask_by=past), "would_set", "", False),
    "relay, a past wake and no ask_by":     (route(5005, needs=["external"], wait_kind="relay", wait_event="the vendor's reply", wake=past), "refused", "", False),
    "hold + recycle + wake + open after":   (route(5006, needs=[BACK], hold=True, recycle={"at": now0}, after=["g31"], wake=past, **bk), None, "", False),
    "hold + wake, kind time":               (route(5007, needs=[BACK], hold=True, wait_kind="time", wake=past, **bk), "would_set", "", False),
    "kind time, a later wake, an earlier past ask_by": (route(5014, needs=[BACK], wait_kind="time", wake=future, ask_by=past), "refused", "", False),
    "kind time, a later wake, an earlier future ask_by": (route(5015, needs=[BACK], wait_kind="time", wake=DATES["later"], ask_by=DATES["soon"]), "refused", "", False),
    "relay, a later wake, an earlier past ask_by": (route(5016, needs=["external"], wait_kind="relay", wait_event="the vendor's reply", wake=future, ask_by=past), "would_set", "", False),
    "kind time, a future wake, no hold":     (route(5017, needs=[BACK], wait_kind="time", wake=future), "refused", "", False),
    "kind event (valid), a future wake, no hold": (route(5018, needs=[BACK], wait_kind="event", wait_event="box_online box-b", wake=future), "would_set", "", False),
    "anchor with no target, past wake":      (route(5019, needs=[BACK], wait_kind="anchor", wake=past), "kept", "previously only a notice", True),
    "anchor with no target, future wake":    (route(5020, needs=[BACK], wait_kind="anchor", wake=future), "would_set", "previously only a notice", False),
    "anchor with a blank target, past wake": (route(5021, needs=[BACK], wait_kind="anchor", wait_anchor="  ", wake=past), "kept", "previously only a notice", True),
    "event with a bogus phrase, past wake":  (route(5022, needs=[BACK], wait_kind="event", wait_event="bogus", wake=past), "kept", "previously only a notice", True),
    "event with a bogus phrase, future wake": (route(5023, needs=[BACK], wait_kind="event", wait_event="bogus", wake=future), "would_set", "previously only a notice", False),
    "event with no phrase, future wake":     (route(5024, needs=[BACK], wait_kind="event", wake=future), "would_set", "previously only a notice", False),
    "event with a valid phrase, future wake": (route(5025, needs=[BACK], wait_kind="event", wait_event="box_online box-b", wake=future), "would_set", "", False),
    "anchor with its target, future wake":   (route(5026, needs=[BACK], wait_kind="anchor", wait_anchor="https://example.com/x", wake=future), "would_set", "", False),
    "relay + hold, a wake in 3 days, a spaced ask_by": (route(5027, needs=[BACK], wait_kind="relay", wait_event="the vendor's reply", hold=True, wake=day(3), ask_by=day(10) + "  09:30", **bk), "kept", "", False),
    "hold, a spaced wake":                   (route(5028, needs=[BACK], hold=True, wake=day(3) + "  09:30", **bk), "kept", "", False),
    "hold, a spaced wake in the past":       (route(5029, needs=[BACK], hold=True, wake=past + "  09:30", **bk), "kept", "", False),
    "kind time, a spaced wake":              (route(5030, needs=[BACK], wait_kind="time", wake=day(3) + "  09:30"), "kept", "", False),
    "kind time, a spaced wake in the past":  (route(5031, needs=[BACK], wait_kind="time", wake=past + "  09:30"), "kept", "", False),
    "anchor, a spaced ask_by":               (route(5032, needs=[BACK], wait_kind="anchor", wait_anchor="https://example.com/x", ask_by=day(3) + "  09:30"), "kept", "", False),
    "relay, a single-space ask_by (read as before)": (route(5033, needs=[BACK], wait_kind="relay", wait_event="the vendor's reply", ask_by=day(3) + " 09:30"), "would_set", "", False),
    "anchor with no target, past ask_by":   (route(5008, needs=[BACK], wait_kind="anchor", ask_by=past), "kept", "never watched", True),
    "event with a bogus phrase, past ask_by": (route(5009, needs=[BACK], wait_kind="event", wait_event="bogus", ask_by=past), "kept", "never watched", True),
    "anchor with no target, future ask_by": (route(5010, needs=[BACK], wait_kind="anchor", ask_by=future), "would_set", "never watched", False),
    "event with a bogus phrase, future ask_by": (route(5011, needs=[BACK], wait_kind="event", wait_event="bogus", ask_by=future), "would_set", "never watched", False),
    "hold + recycle, past ask_by":          (route(5012, needs=[BACK], hold=True, recycle={"at": now0}, ask_by=past, **bk), "kept", "never watched", True),
    "wake beside an open after, no kind":   (route(5013, needs=[BACK], after=["g31"], wake=future), "would_set", "previously only a notice", False),
}
for name, (r, action, how, is_due) in rows.items():
    check(f"classes: {name}: " + (f"{action or 'any'}, {how or 'unlisted'}" + (", due" if is_due else "")),
          (action is None or r["action"] == action) and r.get("how", "") == how and bool(r.get("due")) is is_due and bool(r.get("newly")) is (bool(how) and not is_due), r)
restore(S1)
check("sweep: the run did something at every time (the grid is not empty of ticks)", all(acts[l][0] for l in acts) and acts["+20 days"][1] != acts["+1 minute"][1], {l: (len(a), len(b)) for l, (a, b) in acts.items()})
CFGM["migration"] = False
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(f"ok: until sweep scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
