"""Scenario test for the readings the audit passes share (stackshot/audit/silence.py: `reading`, `clock`, `subagent_running`, `minutes`). The file once tested the ten-minute silence pass, the 45-minute news ask;
that pass is retired, and the hourly audit line (audit_hourly), the idle hand-over (hand_idle), the stall ladder (stall, ladder_silence) and the queue reading (queued_behind) keep these readings in use. Fixture items,
a fake clock (every call is given its `now`), no live store, no network, no model call.

  1  reading: an open item of a session in the state doing reads "agent"; not what the board shows waiting (a wake with a wait_basis, a hold with a dated wake, an item behind an open one, a stored wait), the owner's or an outside party's item,
     a state that is itself a wait; a wake alone (ahead or passed) is only a reminder and the item reads on agent; the answer agrees with `model.shown_waiting` for every item of the board; a record the model cannot read reads "unreadable"
  1b clock: the item's `activity` stamp, so a bare confirm and a recent `updated` do not move it; the later of the activity and the moment the item left a hold, a wait or an after link (an item parked 30 hours and woken is quiet from the wake); spans read in hours and minutes
  2  subagent_running: a `work` line in progress, changed within 90 minutes, is a build subagent running on the item; lines only defined, assigned or done, one past the bound, and (with a mover) a line of another agent are not

    tests/run-suite silence       -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="silence-"); T = pathlib.Path(tmp)
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
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.audit import silence as SL; from stackshot.waits import handoff as HO
_cfg.CFG["audit"]["pattern_review"] = "off"      # this suite holds the run to its other stages: the pattern review has its own suite (pattern_review_scenario)
H = 3600; now = time.time()
ZONE_OFFSET = 4 * H                                    # the instance timezone (the config's `timezone` above): UTC+4, no DST
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight: a fixture's date words stay on one day
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET)); OWNER = "00000000-0000-4000-8000-000000000001"
local_str = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
fails = []; ran = []
bid = lambda n: f"board#{n}"                           # an item's id as the board writes it
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

def item(i, status="open", wrote=None, **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if wrote is None else wrote,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"a{i}", d
def build(*pairs): return dict(pairs)


M = 60
def quiet(i, mins, **meta):
    """A doing item on a session whose last activity was `mins` minutes ago (its other clocks are recent: a bare confirm, a server save)."""
    k, d = item(i, wrote=now - M, **{"state": "doing", "needs": ["home-agent"], "next": "home-agent: build it", **meta})
    d["activity"] = now - mins * M
    return k, d

def read_all(items, behind=None):
    """{gid: reading} over the open items, as the passes call it."""
    out = {}
    for gid in sorted(items, key=AC._num):
        if items[gid].get("status") != "open": continue
        it, _meta, after_open, mover = AC._item_view(items, gid)
        out[gid] = SL.reading(it, mover, after_open, now, (behind or {}).get(gid, ""))
    return out

# ---- 1. reading
OPEN_A1 = item(8, wrote=now - M, state="doing", needs=["home-agent"], next="home-agent: build it")
rules = build(
    quiet(1, 50),                                                                                       # on agent
    quiet(3, 50, wake=local_str(now + 5 * H)),                                                          # a wake ahead that stands on a dated event (its wait_basis, set below): the board shows it waiting
    quiet(4, 50, wake=local_str(now - 2 * H)),                                                          # a wake passed, with no write: only a reminder, the board shows it on agent
    quiet(5, 50, hold=True, wake=local_str(now + 5 * H)),                                               # held until a dated wake: the board shows it waiting
    quiet(6, 50, state="blocked", supplies="its output", after=["a8"]),                                 # behind an open item
    quiet(7, 50, wait_kind="relay"),                                                                    # a stored wait
    OPEN_A1,                                                                                            # the open item a6 waits after
    item(10, wrote=now - M, state="your-call", needs=["decision"], ask="pick one", mover="Oliver", next="Oliver: pick"),   # the owner's item
    item(11, status="completed", wrote=now - 40 * H, state="doing", needs=["home-agent"], next="home-agent: done", outcome="done"),   # closed
    item(12, wrote=now - M, state="parked", needs=["home-agent"], hold=True, wake=local_str(now + 3 * H), next="home-agent: later", cap_ok=True),   # a state that is itself a wait
    quiet(13, 50, mover="home-nobody-else"),                                                            # a session mover
    quiet(14, 50, wake=local_str(now + 5 * H)),                                                         # a wake ahead and nothing else is a backstop: the board shows it on agent
)
rules["a3"]["metadata"]["wait_basis"] = {"text": "the vendor answers on that day", "wake": rules["a3"]["metadata"]["wake"], "by": "home-agent", "at": now}
got = read_all(rules)
check("1 an item of a session in the state doing reads on agent", got["a1"] == "agent" and got["a13"] == "agent", got)
check("1 a wake with a wait_basis, a hold with a dated wake, an item behind an open one, a stored wait and a state that is itself a wait read waiting (not on agent)",
      all(got[g] == "" for g in ("a3", "a5", "a6", "a7", "a12")), got)
check("1 the owner's item reads not on agent, and a closed item is not read", got["a10"] == "" and "a11" not in got, got)
check("1 a wake alone, ahead (item 14) or passed (item 4), is a backstop and leaves the item on agent", got["a4"] == "agent" and got["a14"] == "agent", got)
check("1 the pass's set: exactly these items read on agent", sorted(g for g, v in got.items() if v == "agent") == ["a1", "a13", "a14", "a4", "a8"], got)
from stackshot.model import model as MODEL
agree = []
for gid, it_ in rules.items():
    if it_.get("status") != "open": continue
    it, _meta, after_open, mover = AC._item_view(rules, gid)
    if AC._no_session(mover): continue
    agree.append((gid, got[gid] == "agent", not MODEL.shown_waiting(it, now, after_open)))
check("1 for every open item a session moves, reading says on agent exactly when the board does not show it waiting (`model.shown_waiting`)", agree and all(a == b for _g, a, b in agree), [x for x in agree if x[1] != x[2]])
check("1 an item queued behind its mover's other item reads waiting: the queue's answer is passed in", read_all(rules, {"a1": "a8"})["a1"] == "" and read_all(rules)["a1"] == "agent")
check("1 a record the board's model cannot read reads unreadable when its mover is a session", SL.reading(None, "home-agent", [], now) == "unreadable", SL.reading(None, "home-agent", [], now))
check("1 …and an item with no session mover is never on agent, readable or not", SL.reading(None, "", [], now) == "", SL.reading(None, "", [], now))

# ---- 1b. the clock
def woke(i, parked_h, left_ago_m):
    """An item parked for `parked_h` hours (no activity since), released `left_ago_m` minutes ago by a save with no writer: only its state_updated moves."""
    k, d = quiet(i, parked_h * 60 + left_ago_m)
    d["state_updated"] = now - left_ago_m * M; d["updated"] = now - left_ago_m * M
    return k, d
w = build(woke(50, 30, 5))
check("1b the clock of an item parked 30 hours and woken five minutes ago is the wake, not the old activity", abs(SL.clock(w["a50"], "home-agent") - (now - 5 * M)) < 1, SL.clock(w["a50"], "home-agent"))
plain = build(quiet(51, 50)); plain["a51"]["confirmed"] = now - 2 * M; plain["a51"]["state_updated"] = now - 3 * H
check("1b with no release in between the clock is the activity stamp: a bare confirm two minutes ago and a recent `updated` do not move it", abs(SL.clock(plain["a51"], "home-agent") - (now - 50 * M)) < 1, SL.clock(plain["a51"], "home-agent"))
nf = build(item(20, wrote=now - 3 * H, state="doing", needs=["home-agent"], next="home-agent: build it"))
nf["a20"].pop("written_at"); nf["a20"].pop("written_by"); nf["a20"]["updated"] = now - 3 * H; nf["a20"]["state_updated"] = now - 3 * H
check("1b an item saved before the activity field existed is read from its last state change or update", abs(SL.clock(nf["a20"], "home-agent") - (now - 3 * H)) < 1, SL.clock(nf["a20"], "home-agent"))
check("1b spans: minutes up to four hours, hours and minutes past", [SL.minutes(x * M) for x in (50, 239, 240, 241, 600, 1801)] == ["50 minutes", "239 minutes", "4 hours", "4 hours 1 minute", "10 hours", "30 hours 1 minute"])

# ---- 2. subagent_running
from stackshot.model import activity as ACT
def ev(i, ago_min, kind):
    """A doing item of the builder whose last write was 3 hours ago, then one more activity `ago_min` minutes ago."""
    k, d = item(i, wrote=now - 3 * H, state="doing", needs=["home-agent"], next="home-agent: build it", project="projects/alpha")
    d["activity"] = d["state_updated"] = now - 3 * H
    if ago_min is not None: ACT.stamp(d, d, now - ago_min * M, kind)
    return k, d
def wl(state, ago_h, agent="home-agent"): return [{"id": "build-it", "text": "build it", "agent": agent, "state": state, "ts": now - ago_h * H}]
def sub(i, lines, mover="home-agent"):
    """A doing item of `mover` silent for 3 hours (no event, no write), carrying the given work lines."""
    k, d = ev(i, None, ACT.EVENT)
    d["metadata"]["needs"] = [mover]; d["metadata"]["next"] = f"{mover}: build it"
    if lines is not None: d["metadata"]["work"] = lines
    return k, d
subs = build(sub(1, wl("in progress", 0.5)), sub(2, None), sub(3, wl("assigned", 1)), sub(4, wl("defined", 1)), sub(5, wl("done", 1)), sub(6, wl("in progress", 2)), sub(7, wl("in progress", 0.5, "home-nobody-else"), mover="home-nobody-else"))
check("2 a line in progress inside the bound is a subagent running, the same line past it is not, and no line is none; the bound is 90 minutes",
      SL.subagent_running(subs["a1"], now) and not SL.subagent_running(subs["a6"], now) and not SL.subagent_running(subs["a2"], now) and SL.SUBAGENT_S == 90 * M)
check("2 a line only assigned, only defined or done is not a subagent running", not any(SL.subagent_running(subs[g], now) for g in ("a3", "a4", "a5")))
same = lambda a, b: str(a).casefold() == str(b).casefold()
check("2 with a mover given, only a line on a step that opens with that session's name counts", SL.subagent_running(subs["a1"], now, "home-agent", same) and not SL.subagent_running(subs["a1"], now, "other-agent", same)
      and SL.subagent_running(subs["a7"], now, "home-nobody-else", same) and not SL.subagent_running(subs["a7"], now, "home-agent", same))
other = dict(subs["a1"], metadata=dict(subs["a1"]["metadata"], work=[{"id": "x", "text": "x", "agent": "someone-else", "state": "in progress", "ts": now - 600}]))
check("2 a stale status another agent left in progress says nothing about the mover being chased", SL.subagent_running(other, now) and not SL.subagent_running(other, now, "home-agent", same))
check("2 a record with no readable metadata is no subagent", not SL.subagent_running({"metadata": "torn"}, now) and not SL.subagent_running({}, now))

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: silence scenario, {len(ran)} checks")
