"""Scenario test for the passes that look for a quiet item (silence.findings, stall.not_due, silence.uncovered, server._silence_backstop): they skip exactly what the board shows as waiting, and nothing more.
Fixture items, messages replaced by recorders, a fake clock (every call is given its `now`), no live store, no network, no model call.

  1  the shared test: model.shown_waiting is the board's own phase for an open item. One scenario per exemption kind a quiet-item pass used to carry: a bare wake (ahead, passed) is a backstop and leaves the item on
     agent; a wake with a wait_basis, a hold with a dated wake, a step dated after the wake, an open `after` link and a stored wait (a relay, an outside party) are waits; a hold with a wake inside the hour is not;
     a hold with no wake and no stored state derives parked and waits, while a stored `state: doing` on a hold with no wake (an artificial shape: the server refuses a hold with no date) reads on agent;
     an item behind an `after` link that has closed is not; a closed item is not
  2  the silence rule and the stall pass's `not_due` agree with it: for every kind above, an item the board shows waiting is neither found silent nor looked at by the stall pass, and an item it shows on agent is both;
     the lanes that are not an agent's work (the owner's states, a need of the owner or of an outsider, a mover that is no session) keep their own reasons; an untaken hand-off is the hand-off audit's alone
  3  the evidence: a finding on an item with a wake says that the wake is only a backstop
  4  a fixture board with one item of every kind: every item the board shows on an agent is covered by a silence finding once it has been silent past 45 minutes (an oracle that does not use the rule's own scope test);
     `shown_waiting` and `on_agent` agree with the board's own lists (`home.classify`, the lists the home page draws) for every item of that board
  6  an untaken hand-off: to a back agent the hand-off audit clocks it, so silence leaves it; to a front agent that audit never does, so silence checks it; the backstop lists a back agent's one that stays silent 2 hours
  7  the silence pass and the dates pass on one item whose wake passes after it went quiet send ONE message per episode, in either order
  8  an item the board's model cannot read is on an agent as the board lists it: checked, with a finding that says the record cannot be read
  5  the backstop: `uncovered` lists an item on an agent silent for more than 2 hours that has no finding (a simulated new exemption), not one with a finding, a wait, a quiet time under 2 hours or a build subagent
     running (`skip`); the server's hourly look tells the builder once per item, asks nothing of the owner, makes no board item, and tells again only after the item has had a finding in between

    tests/run-suite quiet_item_checks       -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="quiet-items-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit_run as AR; from stackshot.audit import silence as SL; from stackshot.waits import handoff as HO
from stackshot.waits import stall as ST; from stackshot.model import model as MD; from stackshot.web import home as HOME
H = 3600; M = 60; now = time.time()
ZONE_OFFSET = 4 * H                                    # the instance timezone (the config's `timezone` above): UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight: a fixture's date words stay on one day
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET)); OWNER = "00000000-0000-4000-8000-000000000001"
local_str = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
day_str = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d")
shown = lambda i: "board#" + str(i)                    # the id as the board writes it
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

def item(i, status="open", **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    return f"a{i}", d
def quiet(i, mins, **meta):
    """A doing item on a session whose last activity was `mins` minutes ago (its other clocks are recent: a bare confirm, a server save)."""
    k, d = item(i, **{"state": "doing", "needs": ["home-agent"], "next": "home-agent: build it", **meta})
    d["written_at"] = now - M; d["written_by"] = "home-agent"; d["activity"] = now - mins * M; d["state_updated"] = now - (mins + 5) * M
    return k, d
def helper(i):
    """A plain item that is busy now (written a minute ago), for another to wait after."""
    k, d = item(i, state="doing", needs=["home-agent"], next="home-agent: build it"); d["activity"] = now - M; d["state_updated"] = now - M
    return k, d
BASIS = lambda wake: {"text": "the vendor answers on that day", "wake": wake, "by": "home-agent", "at": now}
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent, pushed = [], []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def push(to, text): pushed.append((to, text)); return True, "delivered"
def env():
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None),
                  deliver=deliver, push=push, sessions=lambda: None, pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})

# ---- the kinds: (key, item, the board shows it waiting, why the stall pass leaves it, open after items)
W_AHEAD, W_PAST, W_SOON, W_FAR = local_str(now + 5 * H), local_str(now - 2 * H), local_str(now + 20 * M), local_str(now + 30 * H)
def kinds():
    k = []
    def add(key, pair, waiting, why="", after=()):
        k.append((key, pair, waiting, why, list(after)))
    add("plain doing, no wake", quiet(1, 50), False)
    add("bare wake ahead", quiet(2, 50, wake=W_AHEAD), False)
    add("bare wake passed", quiet(3, 50, wake=W_PAST), False)
    p = quiet(4, 50, wake=W_AHEAD); p[1]["metadata"]["wait_basis"] = BASIS(W_AHEAD)
    add("wake ahead with a wait_basis", p, True, "the board shows it waiting (time)")
    p = quiet(5, 50, wake=W_PAST); p[1]["metadata"]["wait_basis"] = BASIS(W_PAST)
    add("wake passed with a wait_basis", p, False)
    add("hold with a wake more than an hour ahead", quiet(6, 50, hold=True, wake=W_AHEAD), True, "the board shows it waiting (time)")
    add("stored doing on hold with no wake (artificial: the server refuses it)", quiet(7, 50, hold=True), False)
    p = quiet(15, 50, hold=True); p[1]["metadata"].pop("state")
    add("hold with no wake and no stored state (derives parked)", p, True, "the board shows it waiting (time)")
    add("hold with a wake inside the hour", quiet(8, 50, hold=True, wake=W_SOON), False)
    add("step dated after the wake day", quiet(9, 50, wake=W_FAR, next=f"home-agent: after {day_str(now + 30 * H + 86400)} rerun the drill"), True, "the board shows it waiting (time)")
    add("blocked behind an open item", quiet(10, 50, state="blocked", supplies="its output", after=["a30"]), True, "the board shows it waiting (item)", after=["a30"])
    add("behind an item that has closed", quiet(11, 50, after=["a30"]), False)
    add("a stored wait on a relay", quiet(12, 50, wait_kind="relay", wait_event="the vendor's reply"), True, "the board shows it waiting (relay)")
    add("state outside", quiet(13, 50, state="outside", party="the vendor", wait_kind="relay", wait_event="the vendor's reply"), True, "the board shows it waiting (relay)")
    add("state parked until a dated wake", quiet(14, 50, state="parked", hold=True, wake=W_AHEAD, cap_ok=True), True, "the board shows it waiting (time)")
    return k

OPEN_AFTER = {"a30"}
after_open = lambda it: [a for a in (it.get("metadata") or {}).get("after") or [] if a in OPEN_AFTER]
def opened(pair_after):
    return (lambda it: list(pair_after)) if pair_after else (lambda it: [])

# ---- 1. the shared test, per kind
for key, (gid, d), waiting, why, aft in kinds():
    got = MD.shown_waiting(d, now, (lambda it, a=aft: a))
    check(f"1 the board shows [{key}] {'waiting' if waiting else 'on agent'}", got is waiting, got)
closed = quiet(40, 50); closed[1]["status"] = "completed"; closed[1]["metadata"]["outcome"] = "done"
check("1 a closed item is not shown waiting", MD.shown_waiting(closed[1], now) is False)

# ---- 2. silence and not_due agree with it, per kind
for key, (gid, d), waiting, why, aft in kinds():
    board = {gid: d, **dict([helper(30)] if aft else [])}
    fs, ps = SL.findings(board, now, env())
    found = shown(gid[1:]) in [f["id"] for f in fs]
    check(f"2 silence: [{key}] {'is left alone' if waiting else 'is found at 50 minutes'}", found is (not waiting), fs)
    nd = ST.not_due(d, now, opened(aft))
    check(f"2 not_due: [{key}] {('is left alone: ' + why) if waiting else 'is looked at'}", (nd == why) if waiting else (nd == ""), nd)
    d45 = json.loads(json.dumps(d)); d45["activity"] = now - 40 * M
    fs45, _ = SL.findings({gid: d45, **dict([helper(30)] if aft else [])}, now, env())
    check(f"2 silence: [{key}] 40 minutes of quiet is found by none", not fs45, fs45)
# the lanes that are not an agent's work keep their reasons
owner = quiet(50, 50, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick")
check("2 the owner's item (your-call): not found, and the stall pass says it waits on the owner", SL.findings(dict([owner]), now, env())[0] == [] and ST.not_due(owner[1], now) == "waiting on the owner", ST.not_due(owner[1], now))
dec = quiet(51, 50, needs=["decision"], ask="pick one")
check("2 a doing item that needs a decision: the stall pass leaves it for the owner", ST.not_due(dec[1], now) == "waiting on the owner", ST.not_due(dec[1], now))
ext = quiet(52, 50, needs=["external"])
check("2 a doing item that needs someone outside: the stall pass leaves it for them", ST.not_due(ext[1], now) == "waiting on someone outside", ST.not_due(ext[1], now))
nos = quiet(53, 50, mover="Oliver")
check("2 an item whose mover is the owner, not a session: not found", SL.findings(dict([nos]), now, env())[0] == [], SL.findings(dict([nos]), now, env())[0])
hand = quiet(54, 50, **{HO.KEY: HO.new_record("home-agent", "", "alpha-main", now - 50 * M)}); hand[1]["metadata"][HO.KEY]["taken_at"] = None
check("2 an untaken hand-off is the hand-off audit's alone: not found", SL.findings(dict([hand]), now, env())[0] == [], SL.findings(dict([hand]), now, env())[0])
check("2 the stall pass says a closed item is closed", ST.not_due(closed[1], now) == "closed")
bad = quiet(55, 50); bad[1]["metadata"]["wake"] = {"not": "a string"}
try: bad_nd = ST.not_due(bad[1], now)
except Exception as e: bad_nd = f"raised {e.__class__.__name__}"
check("2 an item the model cannot read is not looked at, and does not raise", bad_nd in ("not readable", ""), bad_nd)
# due_at: a wake still ahead is a backstop and counts nothing
bare = dict([quiet(56, 50, wake=W_AHEAD)])["a56"]
check("2 due_at: a wake still ahead counts nothing from `now`; one that has passed counts from the wake", ST.due_at(bare, now) == 0.0 and ST.due_at(bare, now + 6 * H) > 0.0, (ST.due_at(bare, now), ST.due_at(bare, now + 6 * H)))

# ---- 3. the evidence says the wake is only a backstop
ahead = dict([quiet(60, 50, wake=W_AHEAD)]); past = dict([quiet(61, 50, wake=W_PAST)])
d_ahead = SL.findings(ahead, now, env())[0][0]["detail"]; d_past = SL.findings(past, now, env())[0][0]["detail"]
check("3 a bare wake ahead: the finding says the wake is only a hand-off backstop and no wait, and what would make it one", d_ahead.startswith("no write for 50 minutes and a wake kept as a hand-off's backstop, which is no wait") and "set a wait with until" in d_ahead, d_ahead)
check("3 a bare wake that passed: the finding says the wake has passed and asks for a new date or a wait, not for a hold with that wake", d_past.startswith("no write for 50 minutes and a wake that has passed (write the item, set a new date or a wait") and "hold it with the wake" not in d_past, d_past)
bp = dict([quiet(62, 50, wake=W_PAST)]); bp["a62"]["metadata"]["wait_basis"] = BASIS(W_PAST)
d_basis = SL.findings(bp, now, env())[0][0]["detail"]
check("3 a wake that passed and carries a wait_basis: the same wording (a hold with a wake already past would not help)", d_basis == d_past, d_basis)
check("3 the dates pass words the same case 'past its wake' and the two are one finding of one item: each names the wake as passed", "past its wake" in SL._ac.check_stale(bp["a62"], bp["a62"]["metadata"], "home-agent", lambda x: [], now, now - 50 * M * 3) and "has passed" in d_basis)

# ---- 4. every item the board shows on an agent is covered once it has been silent past 45 minutes
def build_board():
    b = {}
    for _key, (gid, d), _w, _why, _aft in kinds(): b[gid] = d
    b.update([helper(30), quiet(50, 50, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick"), nos, closed, hand])
    return b
board = build_board(); after_of = lambda it: [a for a in (it.get("metadata") or {}).get("after") or [] if a in OPEN_AFTER and board.get(a, {}).get("status") == "open"]
def on_agent_oracle(gid, d):
    """The board's own reading, without the rule's scope test: open, a session is the mover, not the owner's move, phase not waiting."""
    if d.get("status") != "open": return False
    m = d["metadata"]
    if m.get("mover") == "Oliver" or m.get("state") in ("your-call", "your-step"): return False
    if HO.KEY in m and m[HO.KEY].get("taken_at") is None: return False           # the hand-off audit's own ladder
    return MD.view(d, MD.derive(d, now, after_of), now, after_of).state != MD.WAITING
fs4, ps4 = SL.findings(board, now, env())
covered4 = {f["id"] for f in fs4} | {p["id"] for p in ps4}
board_ok = {g: d for g, d in board.items() if "activity" in d}
should = sorted(shown(g[1:]) for g, d in board_ok.items() if on_agent_oracle(g, d) and now - d["activity"] > 45 * M)
check("4 the fixture board has on-agent items to cover (the oracle is not empty)", len(should) >= 5, should)
check("4 every item the board shows on an agent and silent past 45 minutes has a silence finding", set(should) <= covered4, sorted(set(should) - covered4))
check("4 …and nothing else has one", covered4 <= set(should), sorted(covered4 - set(should)))
check("4 the backstop finds nothing on that board at 90 minutes of quiet (every such item is covered)", SL.uncovered(board, now, env()) == [], SL.uncovered(board, now, env()))
HOME_ROWS = {g: d for g, d in board.items() if d.get("status") == "open"}
def board_mod(r): return MD.view(r, MD.derive(r, now, after_open=after_of, anchored=lambda it: False), now, after_of)      # the home page's own reading (ui/render.py mod_of)
lists = HOME.classify([dict(d, _gid=g) for g, d in HOME_ROWS.items()], board_mod)
in_list = {which: {r["_gid"] for r, _m in pairs} for which, pairs in lists.items()}
check("4 shown_waiting is the board's Waiting list: every open item of the board, no more and no less", {g for g, d in HOME_ROWS.items() if MD.shown_waiting(d, now, after_of)} == in_list[HOME.WAITING], (in_list[HOME.WAITING],))
sess = lambda g, d: not SL._ac._no_session(SL._ac._item_view(board, g)[3]) and d["metadata"].get("state") not in ("your-call", "your-step")
check("4 on_agent is the board's Agents list for the items a session moves", {g for g, d in HOME_ROWS.items() if SL.on_agent(*(lambda v: (v[0], v[3], v[2]))(SL._ac._item_view(board, g)), now)} == {g for g in in_list[HOME.AGENTS] if sess(g, board[g])},
      ({g for g in in_list[HOME.AGENTS] if sess(g, board[g])},))
later = now + 3 * H
un_later = SL.uncovered(board, later, env())
check("4 three hours on, the one item the backstop lists is the untaken hand-off (the rule leaves it to the hand-off audit, the backstop does not)", [x["id"] for x in un_later] == [shown(54)], un_later)

# ---- 5. the backstop
real_silent = SL.silent
hidden = {"a1"}
SL.silent = lambda it, meta, mover, ao, at, front=None: "" if str(it.get("id")) in {h[1:] for h in hidden} else real_silent(it, meta, mover, ao, at, front)      # a new exemption the rule gained
try:
    b5 = dict([quiet(1, 130), quiet(2, 100), quiet(3, 130)])
    un = SL.uncovered(b5, now, env())
    check("5 an item on an agent silent for 130 minutes that the rule hides is uncovered", [x["id"] for x in un] == [shown(1)] and un[0]["mover"] == "home-agent" and un[0]["silent"] > 2 * H, un)
    check("5 …not one silent for 100 minutes (under 2 hours), and not one the rule found", shown(2) not in [x["id"] for x in un] and shown(3) not in [x["id"] for x in un], un)
    check("5 …and not one a build subagent is running on (skip)", SL.uncovered(b5, now, env(), skip=lambda gid, it, mover: gid == "a1") == [])
    w5 = dict([quiet(1, 130, hold=True, wake=W_AHEAD)])
    check("5 …and not one the board shows waiting", SL.uncovered(w5, now, env()) == [])
    check("5 …and not a closed item", SL.uncovered({"a1": {**quiet(1, 130)[1], "status": "completed", "metadata": {**quiet(1, 130)[1]["metadata"], "outcome": "done"}}}, now, env()) == [])
    # the server's hourly look
    from stackshot.web import server
    told = []; err_lines = []
    real_flag = server._inbox_flag_send
    server._inbox_flag_send = lambda to, text, *a, **k: told.append((to, text))
    server._BACKSTOP_LAST[0] = 0.0; server._BACKSTOP_TOLD.clear()
    late = server._silence_backstop(now=now, items=b5)
    check("5 the server's look returns the uncovered item and tells the builder once, in one message", [x["id"] for x in late] == [shown(1)] and len(told) == 1 and told[0][0] == "falcon-engineer", (late, told))
    txt = told[0][1] if told else ""
    check("5 …the message names the item, says how long, asks nothing of the owner and owes no reply", shown(1) in txt and "no activity for 130 minutes" in txt and "no reply is owed" in txt, txt)
    check("5 …and names no board item to open: nothing but the builder is told", len(told) == 1 and not any(w in txt.lower() for w in ("decision needed", "please decide")), txt)
    n = len(told)
    again = server._silence_backstop(now=now + 30 * M, items=b5)
    check("5 inside the hour the server looks at nothing", again == [] and len(told) == n, (again, len(told)))
    again = server._silence_backstop(now=now + 2 * H, items=b5)
    check("5 an hour on, the item is still uncovered and returned, but the builder is not told twice", [x["id"] for x in again] == [shown(1)] and len(told) == n, (again, len(told)))
    hidden.clear()
    clear = server._silence_backstop(now=now + 4 * H, items=b5)
    check("5 once the rule finds it, the backstop is clear and forgets the item", clear == [] and server._BACKSTOP_TOLD == set(), (clear, server._BACKSTOP_TOLD))
    hidden.add("a1")
    server._silence_backstop(now=now + 6 * H, items=b5)
    check("5 missed again after having a finding, it is told again", len(told) == n + 1, len(told))
    server._inbox_flag_send = real_flag
finally:
    SL.silent = real_silent

# ---- 6. an untaken hand-off
def handed(i, to, mins=50, frm="home-agent"):
    k, d = quiet(i, mins, needs=[to], next=f"{to}: build it", **{HO.KEY: HO.new_record(to, "", frm, now - mins * M)})
    return k, d
hb = dict([handed(70, "home-agent", frm="alpha-main")]); hf = dict([handed(71, "alpha-main", frm="home-agent")])
check("6 an untaken hand-off to a back agent is the hand-off audit's: not found at 50 minutes", SL.findings(hb, now, env())[0] == [], SL.findings(hb, now, env())[0])
ff = SL.findings(hf, now, env())[0]
check("6 …to a front agent, which that audit never clocks, silence checks it: found at 50 minutes", [f["id"] for f in ff] == [shown(71)], ff)
check("6 …and a front agent's one that is taken is found as any item is", [f["id"] for f in SL.findings(dict([quiet(72, 50, needs=["alpha-main"], next="alpha-main: build it")]), now, env())[0]] == [shown(72)])
fe = AR.Env(roles={"alpha-main": {"role": "background"}}, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, push=push, sessions=lambda: None,
            pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, front=lambda who, project: who == "home-agent")
check("6 the server's own answer (`Env.front`) decides who is front: swapped, the back agent's hand-off is checked and the front agent's is left", SL.findings(hb, now, fe)[0] != [] and SL.findings(hf, now, fe)[0] == [], (SL.findings(hb, now, fe)[0], SL.findings(hf, now, fe)[0]))
hb2 = dict([handed(73, "home-agent", 130, "alpha-main")])
check("6 the backstop does not exempt a back agent's hand-off: silent 130 minutes with no finding, it is listed", [x["id"] for x in SL.uncovered(hb2, now, env())] == [shown(73)], SL.uncovered(hb2, now, env()))
check("6 …and a front agent's hand-off silent 130 minutes has its finding, so the backstop lists nothing", SL.uncovered(dict([handed(74, "alpha-main", 130)]), now, env()) == [])

# ---- 7. the silence pass and the dates pass send one message per episode
def clear_records():
    for f in (T / "state/audit").glob("*.json"): f.unlink()
    sent.clear(); pushed.clear()
def going_quiet(i):
    """A doing item quiet for 50 minutes whose wake is 20 minutes ahead and falls after the last write: the silence pass finds it now, the dates pass once the wake has passed."""
    k, d = quiet(i, 50, wake=local_str(now + 20 * M)); d["written_at"] = now - 50 * M; return {k: d}
def to_mover(): return [t for to, t, _f in sent if to == "home-agent"]
clear_records(); b7 = going_quiet(80)
r1 = SL.silence_pass(now=now, items=b7, env=env())
r2 = AR.dates_pass(now=now + 25 * M, items=b7, anchors={}, env=env())
check("7 silence first, then the wake passes: the dates pass finds the item and sends nothing, one message in all", r1["fresh"] == 1 and r2["findings"] == 1 and r2["fresh"] == 0 and r2["repeats"] == 1 and len(to_mover()) == 1, (r1, r2, to_mover()))
r3 = SL.silence_pass(now=now + 35 * M, items=b7, env=env())
check("7 …and the silence pass later sends nothing either (still the one message)", r3["fresh"] == 0 and len(to_mover()) == 1, (r3, to_mover()))
clear_records(); b7 = going_quiet(81)
r1 = AR.dates_pass(now=now + 25 * M, items=b7, anchors={}, env=env())
r2 = SL.silence_pass(now=now + 30 * M, items=b7, env=env())
check("7 the other order (the dates pass sends first): the silence pass finds it and sends nothing, one message in all", r1["fresh"] == 1 and r2["findings"] == 1 and r2["fresh"] == 0 and len(to_mover()) == 1, (r1, r2, to_mover()))
clear_records()

# ---- 8. an item the board's model cannot read
real_derive = MD.derive
def bad_derive(item, *a, **k):
    if str(item.get("id")) == "90": raise ValueError("the fields do not read")
    return real_derive(item, *a, **k)
bk, bd = quiet(90, 50); b8 = dict([(bk, bd), quiet(91, 50)])
MD.derive = bad_derive
try:
    lst = HOME.classify([dict(bd, _gid=bk)], lambda r: MD.view(r, MD.derive(r, now), now))
    f8, _p8 = SL.findings(b8, now, env())
    check("8 the board lists an item its model cannot read among the agents", [r["_gid"] for r, _m in lst[HOME.AGENTS]] == [bk], lst)
    check("8 so silence checks it: found at 50 minutes, the evidence says the record cannot be read; its neighbour is found as usual", sorted(f["id"] for f in f8) == [shown(90), shown(91)]
          and "cannot read" in next(f["detail"] for f in f8 if f["id"] == shown(90)), f8)
    b8x = dict([quiet(90, 40)])
    check("8 …not at 40 minutes", SL.findings(b8x, now, env())[0] == [])
    b8l = dict([quiet(90, 130)])
    covered8 = SL.uncovered(b8l, now, env())
    check("8 the backstop has no gap there: an unreadable item silent 130 minutes has its finding, so nothing is uncovered", covered8 == [], covered8)
    check("8 the stall pass still leaves an unreadable item alone (it names the reason)", ST.not_due(bd, now) == "not readable", ST.not_due(bd, now))
finally:
    MD.derive = real_derive

# ---- 9. a stored `until` is read as a wake is (wake_value), by the silence pass, the stall pass and the backstop
# The board reads a stored until as a wait on the date (an open item that stores one is waiting), so the twin of an `until` item is a wake that carries a wait_basis: one record, one reading, whichever field
# holds the date. The two part when the date has passed: a wake with a basis is then a reminder that ended (on agent), while an `until` that has passed is a wait that is due, which the board still shows
# waiting until the server's watcher turns it, so the passes leave it to that watcher exactly as the board does.
def twin(i, mins, **meta):
    """(the item with `until`, the same item with the date as a wake that carries its wait_basis)"""
    date = meta.pop("until")
    k1, d1 = quiet(i, mins, until=date, **meta)
    k2, d2 = quiet(i + 50, mins, wake=date, **meta); d2["metadata"]["wait_basis"] = BASIS(date)
    return (k1, d1), (k2, d2)
def reading9(pair, at=None):
    k, d = pair; at = now if at is None else at; board9 = {k: d}
    return {"waiting": MD.shown_waiting(d, at), "found": bool(SL.findings(board9, at, env())[0]), "not_due": ST.not_due(d, at), "uncovered": bool(SL.uncovered(board9, at, env())), "due_at": ST.due_at(d, at) > 0.0}
for label, date in (("a date ahead", W_AHEAD), ("a date-only day ahead", day_str(now + 30 * H))):
    for mins in (50, 130):
        a_, b_ = twin(100, mins, until=date)
        ra, rb = reading9(a_), reading9(b_)
        check(f"9 {label}, quiet {mins} minutes: the silence pass, the stall pass and the backstop read an `until` as they read the same date as a wake with a basis", ra == rb, (ra, rb))
ua, _ub = twin(110, 130, until=W_AHEAD)
r_ahead = reading9(ua)
check("9 a stored until ahead is a wait: shown waiting, not found, left alone by the stall pass (it names the board's reason), not uncovered, and counted from nothing", r_ahead["waiting"] and not r_ahead["found"] and r_ahead["not_due"] == "the board shows it waiting (time)" and not r_ahead["uncovered"] and not r_ahead["due_at"], r_ahead)
up, wp = twin(111, 130, until=W_PAST)
r_past, r_wp = reading9(up), reading9(wp)
check("9 a stored until that has passed is a wait that is due, which the board still shows waiting: the three passes leave it to the server's watcher, and the stall pass counts from the date", r_past["waiting"] and not r_past["found"] and not r_past["uncovered"] and r_past["not_due"] == "the board shows it waiting (time)" and r_past["due_at"], r_past)
check("9 ...while the same date as a wake with a basis, passed, is a backstop that ended: on agent, found, looked at by the stall pass", not r_wp["waiting"] and r_wp["found"] and r_wp["not_due"] == "", r_wp)
bw = quiet(112, 130, until=W_AHEAD, wake=W_PAST)
check("9 an until ahead beside a bare wake that passed: the board shows it waiting, so none of the three looks at it", reading9(bw)["waiting"] and not reading9(bw)["found"] and not reading9(bw)["uncovered"], reading9(bw))
wo = quiet(113, 130, wake=W_PAST)
SL_silent = SL.silent
SL.silent = lambda it, meta, mover, ao, at, front=None: ""
try:
    check("9 the backstop lists an on-agent item the rule would hide (a bare wake that passed), and neither an item waiting on an until ahead nor one on an until that passed",
          [x["id"] for x in SL.uncovered(dict([ua, up, wo]), now, env())] == [shown(113)], SL.uncovered(dict([ua, up, wo]), now, env()))
finally:
    SL.silent = SL_silent

# ---- 10. the backstop judges a hand-off by the server's own answer to "who is a front agent" (server._front_keeper), the answer the pass was given; and an idle-pass entry covers an item
from stackshot.web import server as SRV
real_fk = SRV._front_keeper
import stackshot.anchors.anchors as ANC
real_file_roles = ANC.file_roles
b10 = dict([handed(120, "alpha-main", 130)])                                    # an untaken hand-off to alpha-main, silent 130 minutes
try:
    # (a) the server calls alpha-main front, the role map does not: the pass checks the hand-off and finds it, so the backstop lists nothing
    SRV._front_keeper = lambda who, project="": (who == "alpha-main", "")
    ANC.file_roles = lambda reg: {"alpha-main": {"role": "background"}}
    found_a = SL.findings(b10, now, SRV._silence_env())[0]
    check("10 the server says alpha-main is front (the role map says back): the pass finds the hand-off", [f["id"] for f in found_a] == [shown(120)], found_a)
    SRV._BACKSTOP_LAST[0] = 0.0; SRV._BACKSTOP_TOLD.clear(); told10 = []; real_flag10 = SRV._inbox_flag_send; SRV._inbox_flag_send = lambda to, text, *a, **k: told10.append((to, text))
    late_a = SRV._silence_backstop(now=now, items=b10)
    check("10 …so the server's backstop, which uses the same answer, lists nothing and tells no one (a default Env would call the hand-off a back agent's, list it and send a false defect message)", late_a == [] and told10 == [], (late_a, told10))
    # (b) the role map calls alpha-main front, the server does not: the pass leaves the hand-off to the hand-off audit, so the backstop lists it
    SRV._front_keeper = lambda who, project="": (False, "")
    ANC.file_roles = lambda reg: {"alpha-main": {"role": "front"}}
    found_b = SL.findings(b10, now, SRV._silence_env())[0]
    check("10 the server says alpha-main is not front (the role map says front): the pass leaves the hand-off to the hand-off audit", found_b == [], found_b)
    SRV._BACKSTOP_LAST[0] = 0.0; SRV._BACKSTOP_TOLD.clear(); del told10[:]
    late_b = SRV._silence_backstop(now=now, items=b10)
    check("10 …so the backstop lists it, silent 130 minutes (a default Env would count a finding the pass never made and hide the gap)", [x["id"] for x in late_b] == [shown(120)] and len(told10) == 1, (late_b, told10))
    # the tick hands the pass's own env on: the backstop is given the one it was built with
    seen_env = []
    real_uncovered = SL.uncovered
    SL.uncovered = lambda items, at, env=None, skip=None: (seen_env.append(env), [])[1]
    SRV._BACKSTOP_LAST[0] = 0.0
    own_env = SRV._silence_env()
    SRV._silence_backstop(now=now, items=b10, env=own_env)
    SRV._BACKSTOP_LAST[0] = 0.0
    SRV._silence_backstop(now=now, items=b10)
    check("10 the backstop passes an env to `uncovered` in every case: the one it is given, else one built the way the pass's is (front = the server's answer)",
          len(seen_env) == 2 and seen_env[0] is own_env and seen_env[1] is not None and seen_env[1].front is not None and seen_env[1].is_front("alpha-main", "") is False, seen_env)
finally:
    SRV._front_keeper = real_fk; ANC.file_roles = real_file_roles; SRV._inbox_flag_send = real_flag10 if "real_flag10" in dir() else SRV._inbox_flag_send
    SL.uncovered = real_uncovered if "real_uncovered" in dir() else SL.uncovered
    SRV._BACKSTOP_TOLD.clear()

# an item the idle pass poked is an idle-pass entry, no finding; silent over 2 hours it is still covered, so the backstop does not list it
pk = quiet(121, 130); pk[1]["metadata"]["idle"] = {"poked": now - 600}; pk[1]["confirmed"] = now - 3 * H; b10p = dict([pk])
fp10, pp10 = SL.findings(b10p, now, env())
check("10 a poked item silent 130 minutes is an idle-pass entry and no finding", fp10 == [] and [p["id"] for p in pp10] == [shown(121)], (fp10, pp10))
check("10 …and the backstop does not list it: the idle-pass entry covers it", SL.uncovered(b10p, now, env()) == [], SL.uncovered(b10p, now, env()))

# the `wake_value` branch of `silent`: reached by any wake (above); by a stored until only when the board still reads the item as on agent, which a stale stored `alive` stamp does
st = quiet(122, 50, until=W_AHEAD, phase="alive")
shown_st = MD.shown_waiting(st[1], now)
if not shown_st:
    d_st = SL.findings(dict([st]), now, env())[0]
    check("10 a stored until read as on agent (a stale alive stamp) reaches the wake branch: found, the evidence names it as a wake that is only a backstop", len(d_st) == 1 and "a wake kept as a hand-off's backstop" in d_st[0]["detail"], d_st)
else:
    print("note: a stored until always shows the item waiting here, so `silent`'s wake_value branch is reached by a wake alone only")

if fails:
    print(f"{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: quiet item checks scenario, {len(ran)} checks")
