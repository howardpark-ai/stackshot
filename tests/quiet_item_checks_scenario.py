"""Scenario test for the passes that look for a quiet item (silence.reading, stall.not_due): they skip exactly what the board shows as waiting, and nothing more. Fixture items, a fake clock (every call is given its `now`),
no live store, no network, no model call. (The file once also tested the ten-minute silence pass and its backstop, now retired: the hourly audit line and the idle hand-over read the same `silence.reading`.)

  1  the shared test: model.shown_waiting is the board's own phase for an open item. One scenario per exemption kind a quiet-item pass used to carry: a bare wake (ahead, passed) is a backstop and leaves the item on
     agent; a wake with a wait_basis, a hold with a dated wake, a step dated after the wake, an open `after` link and a stored wait (a relay, an outside party) are waits; a hold with a wake inside the hour is not;
     a hold with no wake and no stored state derives parked and waits, while a stored `state: doing` on a hold with no wake (an artificial shape: the server refuses a hold with no date) reads on agent;
     an item behind an `after` link that has closed is not; a closed item is not
  2  `silence.reading` and the stall pass's `not_due` agree with it: for every kind above, an item the board shows waiting does not read on agent and is not looked at by the stall pass, and an item it shows on agent
     reads on agent and is looked at; the lanes that are not an agent's work (the owner's states, a need of the owner or of an outsider, a mover that is no session) keep their own reasons
  3  the dates pass words a wake that passed as "past its wake"
  4  a fixture board with one item of every kind: `reading` says on agent for exactly the items the board's own reading puts on an agent (an oracle that does not use `reading`);
     `shown_waiting` and `reading` agree with the board's own lists (`home.classify`, the lists the home page draws) for every item of that board
  8  an item the board's model cannot read is on an agent as the board lists it: `reading` says so, and the stall pass still leaves it alone
  9  a stored `until` is read as a wake is (`wake_value`) by `reading` and the stall pass: one record, one reading, whichever field holds the date

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

from stackshot.core import config as _cfg; from stackshot.audit import audit_checks as AC; from stackshot.audit import silence as SL; from stackshot.waits import handoff as HO
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

# ---- 2. reading and not_due agree with it, per kind
def reads_agent(board, gid, aft_fn=None):
    """What a pass that asks `silence.reading` says of the item: the item view the passes build (the mover, the open after items), then the reading."""
    it, _meta, after_open_, mover = AC._item_view(board, gid)
    return SL.reading(it, mover, after_open_, now) == "agent"
for key, (gid, d), waiting, why, aft in kinds():
    board = {gid: d, **dict([helper(30)] if aft else [])}
    on = reads_agent(board, gid)
    check(f"2 reading: [{key}] {'is not on agent' if waiting else 'is on agent'}", on is (not waiting), on)
    nd = ST.not_due(d, now, opened(aft))
    check(f"2 not_due: [{key}] {('is left alone: ' + why) if waiting else 'is looked at'}", (nd == why) if waiting else (nd == ""), nd)
# the lanes that are not an agent's work keep their reasons
owner = quiet(50, 50, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick")
check("2 the owner's item (your-call): not on agent, and the stall pass says it waits on the owner", not reads_agent(dict([owner]), "a50") and ST.not_due(owner[1], now) == "waiting on the owner", ST.not_due(owner[1], now))
dec = quiet(51, 50, needs=["decision"], ask="pick one")
check("2 a doing item that needs a decision: the stall pass leaves it for the owner", ST.not_due(dec[1], now) == "waiting on the owner", ST.not_due(dec[1], now))
ext = quiet(52, 50, needs=["external"])
check("2 a doing item that needs someone outside: the stall pass leaves it for them", ST.not_due(ext[1], now) == "waiting on someone outside", ST.not_due(ext[1], now))
nos = quiet(53, 50, mover="Oliver")
check("2 an item whose mover is the owner, not a session: not on agent", not reads_agent(dict([nos]), "a53"))
hand = quiet(54, 50, **{HO.KEY: HO.new_record("home-agent", "", "alpha-main", now - 50 * M)}); hand[1]["metadata"][HO.KEY]["taken_at"] = None
check("2 an untaken hand-off still reads on agent (the hand-off audit's own ladder is the passes' business, not the reading's)", reads_agent(dict([hand]), "a54"))
check("2 the stall pass says a closed item is closed", ST.not_due(closed[1], now) == "closed")
bad = quiet(55, 50); bad[1]["metadata"]["wake"] = {"not": "a string"}
try: bad_nd = ST.not_due(bad[1], now)
except Exception as e: bad_nd = f"raised {e.__class__.__name__}"
check("2 an item the model cannot read is not looked at, and does not raise", bad_nd in ("not readable", ""), bad_nd)
# due_at: a wake still ahead is a backstop and counts nothing
bare = dict([quiet(56, 50, wake=W_AHEAD)])["a56"]
check("2 due_at: a wake still ahead counts nothing from `now`; one that has passed counts from the wake", ST.due_at(bare, now) == 0.0 and ST.due_at(bare, now + 6 * H) > 0.0, (ST.due_at(bare, now), ST.due_at(bare, now + 6 * H)))

# ---- 3. the dates pass words a wake that passed
bp = dict([quiet(62, 50, wake=W_PAST)]); bp["a62"]["metadata"]["wait_basis"] = BASIS(W_PAST)
check("3 the dates pass words a wake that passed (with a wait_basis too) as 'past its wake'", "past its wake" in AC.check_stale(bp["a62"], bp["a62"]["metadata"], "home-agent", lambda x: [], now, now - 50 * M * 3))

# ---- 4. every item the board shows on an agent reads on agent
def build_board():
    b = {}
    for _key, (gid, d), _w, _why, _aft in kinds(): b[gid] = d
    b.update([helper(30), quiet(50, 50, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick"), nos, closed, hand])
    return b
board = build_board(); after_of = lambda it: [a for a in (it.get("metadata") or {}).get("after") or [] if a in OPEN_AFTER and board.get(a, {}).get("status") == "open"]
def on_agent_oracle(gid, d):
    """The board's own reading, without `reading`: open, a session is the mover, not the owner's move, phase not waiting."""
    if d.get("status") != "open": return False
    m = d["metadata"]
    if m.get("mover") == "Oliver" or m.get("state") in ("your-call", "your-step"): return False
    return MD.view(d, MD.derive(d, now, after_of), now, after_of).state != MD.WAITING
read4 = {g for g, d in board.items() if d.get("status") == "open" and reads_agent(board, g)}
should = sorted(g for g, d in board.items() if on_agent_oracle(g, d))
check("4 the fixture board has on-agent items (the oracle is not empty)", len(should) >= 5, should)
check("4 every item the board shows on an agent reads on agent, and nothing else does", read4 == set(should), (sorted(read4 ^ set(should)),))
HOME_ROWS = {g: d for g, d in board.items() if d.get("status") == "open"}
def board_mod(r): return MD.view(r, MD.derive(r, now, after_open=after_of, anchored=lambda it: False), now, after_of)      # the home page's own reading (ui/render.py mod_of)
lists = HOME.classify([dict(d, _gid=g) for g, d in HOME_ROWS.items()], board_mod)
in_list = {which: {r["_gid"] for r, _m in pairs} for which, pairs in lists.items()}
check("4 shown_waiting is the board's Waiting list: every open item of the board, no more and no less", {g for g, d in HOME_ROWS.items() if MD.shown_waiting(d, now, after_of)} == in_list[HOME.WAITING], (in_list[HOME.WAITING],))
sess = lambda g, d: not AC._no_session(AC._item_view(board, g)[3]) and d["metadata"].get("state") not in ("your-call", "your-step")
check("4 reading is the board's Agents list for the items a session moves", {g for g in HOME_ROWS if reads_agent(board, g)} == {g for g in in_list[HOME.AGENTS] if sess(g, board[g])},
      ({g for g in in_list[HOME.AGENTS] if sess(g, board[g])},))

# ---- 8. an item the board's model cannot read
real_derive = MD.derive
def bad_derive(item, *a, **k):
    if str(item.get("id")) == "90": raise ValueError("the fields do not read")
    return real_derive(item, *a, **k)
bk, bd = quiet(90, 50)
MD.derive = bad_derive
try:
    lst = HOME.classify([dict(bd, _gid=bk)], lambda r: MD.view(r, MD.derive(r, now), now))
    check("8 the board lists an item its model cannot read among the agents", [r["_gid"] for r, _m in lst[HOME.AGENTS]] == [bk], lst)
    check("8 so reading says unreadable for a session's item, and nothing for an item with no session mover", SL.reading(bd, "home-agent", [], now) == "unreadable" and SL.reading(bd, "", [], now) == "", SL.reading(bd, "home-agent", [], now))
    check("8 the stall pass still leaves an unreadable item alone (it names the reason)", ST.not_due(bd, now) == "not readable", ST.not_due(bd, now))
finally:
    MD.derive = real_derive

# ---- 9. a stored `until` is read as a wake is (wake_value), by `reading` and the stall pass
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
    return {"waiting": MD.shown_waiting(d, at), "agent": reads_agent(board9, k), "not_due": ST.not_due(d, at), "due_at": ST.due_at(d, at) > 0.0}
for label, date in (("a date ahead", W_AHEAD), ("a date-only day ahead", day_str(now + 30 * H))):
    for mins in (50, 130):
        a_, b_ = twin(100, mins, until=date)
        ra, rb = reading9(a_), reading9(b_)
        check(f"9 {label}, quiet {mins} minutes: `reading` and the stall pass read an `until` as they read the same date as a wake with a basis", ra == rb, (ra, rb))
ua, _ub = twin(110, 130, until=W_AHEAD)
r_ahead = reading9(ua)
check("9 a stored until ahead is a wait: shown waiting, not on agent, left alone by the stall pass (it names the board's reason), and counted from nothing", r_ahead["waiting"] and not r_ahead["agent"] and r_ahead["not_due"] == "the board shows it waiting (time)" and not r_ahead["due_at"], r_ahead)
up, wp = twin(111, 130, until=W_PAST)
r_past, r_wp = reading9(up), reading9(wp)
check("9 a stored until that has passed is a wait that is due, which the board still shows waiting: the passes leave it to the server's watcher, and the stall pass counts from the date", r_past["waiting"] and not r_past["agent"] and r_past["not_due"] == "the board shows it waiting (time)" and r_past["due_at"], r_past)
check("9 ...while the same date as a wake with a basis, passed, is a backstop that ended: on agent, looked at by the stall pass", not r_wp["waiting"] and r_wp["agent"] and r_wp["not_due"] == "", r_wp)
bw = quiet(112, 130, until=W_AHEAD, wake=W_PAST)
check("9 an until ahead beside a bare wake that passed: the board shows it waiting, so neither pass looks at it", reading9(bw)["waiting"] and not reading9(bw)["agent"], reading9(bw))


if fails:
    print(f"{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: quiet item checks scenario, {len(ran)} checks")
